#!/usr/bin/env python3
"""Run full-duration C0/C1 cells and assess them against P1 acceptance rules."""
import argparse
import csv
import heapq
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parents[2]
SIM = ROOT / "simulations"
sys.path.insert(0, str(ROOT / "tests/validation/traffic"))
from check_traffic import check_run

WARMUP = 1.0
MEASUREMENT = 30.0
DRAIN = 0.05
BIN_SECONDS = 5.0
STABILITY_FRACTION = 0.05
def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def offered_camera_images(flow, run):
    """Count scheduled image availabilities in the P1 measurement cohort."""
    period = float(flow["period_us"]) / 1e6
    if flow["scalable"] == "1":
        period /= (0.5, 1.0, 2.5, 4.0)[int(run["load"])]
    phase = int(flow["phase_numerator"]) / int(flow["phase_denominator"])
    offset = 0.0 if run["aggregation"] == "A1" else period * phase
    # A sub-picosecond epsilon compensates float conversion of exact simtime
    # boundaries while preserving the half-open [warmup,end) cohort.
    start = max(0, math.ceil((WARMUP - offset) / period - 1e-12))
    stop = max(0, math.ceil((WARMUP + MEASUREMENT - offset) / period - 1e-12))
    return max(0, stop - start)


def parse_sca(sca_path):
    params = {}
    current_statistic = None
    for line in sca_path.read_text(errors="replace").splitlines():
        if line.startswith("par "):
            current_statistic = None
            _, module, name, value = line.split(" ", 3)
            params[module, name] = value.strip().strip('"')
        elif line.startswith("scalar "):
            current_statistic = None
            _, module, name, value = line.split(" ", 3)
            params[module, name] = value.strip()
        elif line.startswith("statistic "):
            _, module, name = line.split(" ", 2)
            params[module, name] = "recorded"
            current_statistic = (module, name)
        elif current_statistic and line.startswith("field "):
            _, field, value = line.split(" ", 2)
            try:
                params[current_statistic[0], current_statistic[1] + ":" + field] = float(value)
            except ValueError:
                pass
        elif line.startswith(("run ", "config ", "param ", "scalar ", "statistic ")):
            current_statistic = None
    return params


def scalar_field(params, module, statistic, field):
    value = params.get((module, statistic + ":" + field))
    return value if isinstance(value, (int, float)) and math.isfinite(value) else None


def summarize_sca_metrics(params):
    queueing_time = []
    utilization = []
    for (module, name), value in params.items():
        if value != "recorded":
            continue
        if name == "queueingTime:histogram":
            match = re.fullmatch(r"(ZonalIVN\..*\.eth\[\d+\]\.macLayer\.queue\.queue\[(\d+)\])", module)
            if match:
                queueing_time.append({
                    "queue": module, "tc": int(match.group(2)),
                    "samples": int(scalar_field(params, module, name, "count") or 0),
                    "mean_s": scalar_field(params, module, name, "mean"),
                    "max_s": scalar_field(params, module, name, "max"),
                })
        elif name == "utilization:histogram" and module.endswith(".phyLayer.transmitter"):
            utilization.append({
                "transmitter": module,
                "interface": module.removesuffix(".phyLayer.transmitter"),
                "samples": int(scalar_field(params, module, name, "count") or 0),
                "mean_percent": scalar_field(params, module, name, "mean"),
                "max_percent": scalar_field(params, module, name, "max"),
            })
    return sorted(queueing_time, key=lambda row: (row["queue"], row["tc"])), sorted(
        utilization, key=lambda row: row["transmitter"])


def verify_configuration(params, config, run_dir):
    interfaces = sorted({module.removesuffix(".classifier")
                         for module, name in params
                         if name == "mapping" and module.endswith(".macLayer.queue.classifier")})
    require(interfaces, f"{config}: no per-egress PCP classifiers in SCA")
    expected_map = [[tc] * 8 for tc in range(8)]
    expected_map_text = json.dumps(expected_map, separators=(",", ":"))
    queue_modules = []
    for interface in interfaces:
        classifier = interface + ".classifier"
        actual_mapping = json.dumps(json.loads(params[classifier, "mapping"]), separators=(",", ":"))
        require(actual_mapping == expected_map_text, f"{config}: PCP-to-TC mapping differs at {interface}")
        selection = interface.rsplit(".classifier", 1)[0].removesuffix(".classifier")
        selection = interface.replace(".classifier", "")
        selector = selection.removesuffix(".classifier") + ".transmissionSelection"
        require(params.get((selector, "reverseOrder")) == "true",
                f"{config}: strict priority is not descending at {interface}")
        for tc in range(8):
            gate = interface.replace(".classifier", "") + f".transmissionGate[{tc}]"
            require(params.get((gate, "initiallyOpen")) == "true", f"{config}: gate {gate} is not open")
            require(params.get((gate, "durations")) == "[]", f"{config}: unexpected gate schedule at {gate}")
            queue = interface.replace(".classifier", "") + f".queue[{tc}]"
            require("DropTailQueue" in params.get((queue, "typename"), ""),
                    f"{config}: {queue} is not drop-tail")
            require(params.get((queue, "packetCapacity")) == "-1",
                    f"{config}: {queue} has a packet limit instead of byte-only capacity")
            cap = params.get((queue, "dataCapacity"))
            require(cap is not None, f"{config}: {queue} has no finite byte capacity")
            # G1-G4 are CSW links, zonal switch backbone/CPU uplinks, and CPU uplinks.
            is_bottleneck = (".CSW.eth[" in interface or
                             re.search(r"\.Z[123]\.ZSW\.eth\[[01]\]", interface) or
                             re.search(r"\.Z[123]\.ZCPU\.eth\[0\]", interface))
            is_camera_talker = re.search(r"\.CAM[1-4]\.eth\[0\]", interface)
            expected_capacity = ("1048576b" if is_bottleneck else
                                 "524288b" if is_camera_talker else "262144b")
            require(cap == expected_capacity,
                    f"{config}: {queue} capacity {cap}, expected {expected_capacity}")
            queue_modules.append(queue)
    # Every traffic source and switch must actually have class-based egress queues.
    source_nodes = {row["source"] for row in csv.DictReader((SIM / "zonal/traffic/flows.csv").open())}
    expected_nodes = {"ZonalIVN." + n for n in source_nodes}
    expected_nodes |= {"ZonalIVN.CSW", *(f"ZonalIVN.Z{i}.ZSW" for i in (1, 2, 3))}
    for node in expected_nodes:
        require(params.get((node, "hasEgressTrafficShaping")) == "true",
                f"{config}: class queues are not enabled on {node}")
    # Confirm real packets arrived in the class selected by each catalog PCP.
    pcp = {r["flow_id"]: int(r["pcp"])
           for r in csv.DictReader((SIM / "zonal/traffic/flows.csv").open())}
    expected_active = {}
    with (run_dir / "queues.csv").open() as stream:
        for row in csv.DictReader(stream):
            if int(row["packets"]) > 0:
                expected_active.setdefault(row["interface"] + ".macLayer.queue", set()).add(
                    pcp[row["flow"]])
    observed_active = {}
    for (module, name), value in params.items():
        match = re.fullmatch(r"(ZonalIVN\..*\.macLayer\.queue)\.queue\[(\d+)\]", module)
        if match and name == "queueLength:max" and float(value) > 0:
            observed_active.setdefault(match.group(1), set()).add(int(match.group(2)))
    for queue, classes in expected_active.items():
        require(observed_active.get(queue, set()) == classes,
                f"{config}: observed PCP queues at {queue} are {observed_active.get(queue, set())}, expected {classes}")
    return interfaces, queue_modules


def load_app_flow_map():
    flow_by_app = {}
    pattern = re.compile(r"^\*\.([A-Za-z0-9_.]+)\.app\[(\d+)\]\.flowId\s*=\s*(\d+)")
    for line in (SIM / "zonal/configs/catalog-bindings.ini").read_text().splitlines():
        match = pattern.match(line.strip())
        if match:
            node, app, flow_id = match.groups()
            flow_by_app[("ZonalIVN." + node, int(app))] = f"F{int(flow_id):02d}"
    return flow_by_app


def read_vectors(vec_path, sca_params, run_summary, expected_queue_count):
    definitions = {}
    with vec_path.open(errors="replace") as stream:
        for line in stream:
            if line.startswith("vector "):
                parts = line.rstrip().split(" ", 4)
                if len(parts) == 5:
                    definitions[int(parts[1])] = (parts[2], parts[3])
            elif line and line[0].isdigit():
                # OMNeT++ writes all vector definitions before event samples;
                # stop here instead of scanning the full, multi-GB file twice.
                break

    app_flow = load_app_flow_map()
    flow_catalog = {row["flow_id"]: row for row in
                    csv.DictReader((SIM / "zonal/traffic/flows.csv").open())}
    load_factor = (0.5, 1.0, 2.5, 4.0)[int(run_summary["run"]["load"])]
    aligned = run_summary["run"]["aggregation"] == "A1"
    camera_schedule = {}
    for flow_id, flow in flow_catalog.items():
        if flow["family"] == "camera":
            period = float(flow["period_us"]) / 1e6
            if flow["scalable"] == "1":
                period /= load_factor
            phase = int(flow["phase_numerator"]) / int(flow["phase_denominator"])
            camera_schedule[flow_id] = (period, 0.0 if aligned else period * phase,
                                        int(flow["packets_per_cycle"]))
    # Keep only the largest 1% of latency samples per receiver to compute an exact
    # nearest-rank empirical p99 without holding millions of samples in memory.
    latency_count = {}
    latency_tail = {}
    image_latency_count = {}
    image_latency_tail = {}
    image_vector_receivers = set()
    queue_info = {}
    drop_vector_info = {}
    for vector_id, (module, metric) in definitions.items():
        if metric == "latency:vector" and ".app[" in module:
            match = re.fullmatch(r"(.*)\.app\[(\d+)\]", module)
            if match and (match.group(1), int(match.group(2))) in app_flow:
                flow = app_flow[match.group(1), int(match.group(2))]
                node = match.group(1).removeprefix("ZonalIVN.")
                # Latencies are meaningful at receivers only; sender modules also emit vectors.
                if run_summary["flows"].get(flow, {}).get("receivers", {}).get(node) is not None:
                    deadline = float(run_summary["flows"][flow].get("deadline_us") or 0) / 1e6
                    latency_count[vector_id] = (flow, node, 0, 0, deadline)
                    expected = run_summary["flows"][flow]["receivers"][node]["measured_packets"]
                    latency_tail[vector_id] = {"keep": max(1, math.floor(0.01 * expected) + 1), "values": []}
        elif metric == "imageCompletionLatency:vector" and ".app[" in module:
            match = re.fullmatch(r"(.*)\.app\[(\d+)\]", module)
            if match and (match.group(1), int(match.group(2))) in app_flow:
                flow = app_flow[match.group(1), int(match.group(2))]
                node = match.group(1).removeprefix("ZonalIVN.")
                if run_summary["flows"].get(flow, {}).get("receivers", {}).get(node) is not None:
                    deadline = float(run_summary["flows"][flow].get("deadline_us") or 0) / 1e6
                    image_latency_count[vector_id] = (flow, node, 0, 0, deadline)
                    receiver_csv = (Path(run_summary["directory"]) /
                                    f"{flow}-{node}-rx.csv")
                    receiver_row = next(csv.DictReader(receiver_csv.open()))
                    expected = int(receiver_row.get("completed_images") or 0)
                    image_latency_tail[vector_id] = {"keep": max(1, math.floor(0.01 * expected) + 1), "values": []}
                    image_vector_receivers.add((flow, node))
        elif metric == "queueBitLength:vector":
            match = re.fullmatch(r"(ZonalIVN\..*\.eth\[\d+\]\.macLayer\.queue\.queue\[(\d+)\])", module)
            if match:
                queue = match.group(1)
                capacity = sca_params.get((queue, "dataCapacity"))
                if capacity:
                    queue_info[vector_id] = {"module": queue, "tc": int(match.group(2)),
                                             "capacity_bits": int(capacity.removesuffix("b")),
                                             "previous": (0.0, 0.0), "bins": [0.0] * 6,
                                             "max_occupancy_bits": 0.0}
        elif metric == "droppedPacketLengthsQueueOverflow:vector":
            match = re.fullmatch(r"(ZonalIVN\..*\.eth\[\d+\]\.macLayer\.queue\.queue\[(\d+)\])", module)
            if match:
                drop_vector_info[vector_id] = {"module": match.group(1), "tc": int(match.group(2)),
                                               "packets": 0, "bytes": 0}

    # Legacy C0 vectors contain every burst frame at the common image-release
    # time, so image completion can be reconstructed exactly without rerunning.
    fallback_receivers = {
        (flow_id, receiver)
        for flow_id, flow in run_summary["flows"].items()
        for receiver in flow["receivers"]
        if flow_id in camera_schedule and
        (flow_id, receiver) not in image_vector_receivers and
        run_summary["run"].get("source_pre_shaping", "0") == "0"
    }
    fallback_images = {}

    def integrate(info, start, stop, value):
        left = max(start, WARMUP)
        right = min(stop, WARMUP + MEASUREMENT)
        if right <= left:
            return
        while left < right:
            index = min(5, int((left - WARMUP) // BIN_SECONDS))
            boundary = WARMUP + (index + 1) * BIN_SECONDS
            end = min(right, boundary)
            info["bins"][index] += value * (end - left)
            left = end

    with vec_path.open(errors="replace") as stream:
        for line in stream:
            parts = line.split()
            if len(parts) not in (3, 4) or not parts[0].isdigit():
                continue
            try:
                # OMNeT++ 6.4 writes vectorId eventNumber time value (ETV).
                if len(parts) == 4:
                    vector_id, time, value = int(parts[0]), float(parts[2]), float(parts[3])
                else:
                    vector_id, time, value = int(parts[0]), float(parts[1]), float(parts[2])
            except ValueError:
                continue
            # The OMNeT vector timestamp is the receive/event time, while the
            # measured packet cohort is selected by CreationTimeTag at the
            # receiver. Recover that cohort timestamp before applying the
            # measurement window so the vector population matches the CSV.
            packet_origin = time - value
            if (vector_id in latency_count and
                    WARMUP - 1e-12 <= packet_origin < WARMUP + MEASUREMENT and
                    time < WARMUP + MEASUREMENT + DRAIN):
                flow, node, count, misses, deadline = latency_count[vector_id]
                count += 1
                misses += int(deadline > 0 and value > deadline)
                latency_count[vector_id] = (flow, node, count, misses, deadline)
                tail = latency_tail[vector_id]
                heap = tail["values"]
                keep = tail["keep"]
                if len(heap) < keep:
                    heapq.heappush(heap, value)
                elif value > heap[0]:
                    heapq.heapreplace(heap, value)
                if (flow, node) in fallback_receivers:
                    period, offset, packets_per_image = camera_schedule[flow]
                    created = time - value
                    image_index = round((created - offset) / period)
                    available = round((offset + period * image_index) * 1e12) / 1e12
                    if WARMUP <= available < WARMUP + MEASUREMENT:
                        require(abs(created - available) <= 5e-12,
                                f"{flow}/{node}: C0 packet timestamp does not match image availability")
                        key = (flow, node, image_index)
                        image = fallback_images.setdefault(key, {"frames": 0, "last_rx": 0.0})
                        image["frames"] += 1
                        image["last_rx"] = max(image["last_rx"], time)
            # Image completion vectors are timestamped at final-frame arrival;
            # their measurement cohort is image availability, recovered from
            # the completion latency itself.
            image_origin = time - value
            if (vector_id in image_latency_count and
                    # Vector timestamps and values are serialized to 12 decimal
                    # places; subtraction can place an exact warm-up-boundary
                    # image a fraction of a picosecond below WARMUP.
                    WARMUP - 1e-12 <= image_origin < WARMUP + MEASUREMENT and
                    time < WARMUP + MEASUREMENT + DRAIN):
                flow, node, count, misses, deadline = image_latency_count[vector_id]
                count += 1
                misses += int(deadline > 0 and value > deadline)
                image_latency_count[vector_id] = (flow, node, count, misses, deadline)
                tail = image_latency_tail[vector_id]
                heap = tail["values"]
                keep = tail["keep"]
                if len(heap) < keep:
                    heapq.heappush(heap, value)
                elif value > heap[0]:
                    heapq.heapreplace(heap, value)
            info = queue_info.get(vector_id)
            if info is not None:
                previous_time, previous_value = info["previous"]
                if time >= previous_time:
                    integrate(info, previous_time, time, previous_value)
                    if time > WARMUP and previous_time < WARMUP + MEASUREMENT:
                        info["max_occupancy_bits"] = max(info["max_occupancy_bits"], previous_value)
                    info["previous"] = (time, value)
                    if WARMUP <= time < WARMUP + MEASUREMENT:
                        info["max_occupancy_bits"] = max(info["max_occupancy_bits"], value)
            dropped = drop_vector_info.get(vector_id)
            if dropped is not None and WARMUP <= time < WARMUP + MEASUREMENT:
                dropped["packets"] += 1
                dropped["bytes"] += int(value)

    latencies = {}
    for vector_id, (flow, node, count, misses, deadline) in latency_count.items():
        p99 = min(latency_tail[vector_id]["values"]) if count else None
        if count and deadline > 0 and misses / count > 0.01:
            require(p99 is not None and p99 > deadline,
                    f"{flow}/{node}: >1% vector-derived misses but nearest-rank p99={p99} s does not exceed {deadline} s")
        latencies.setdefault(flow, {})[node] = {
            "samples": count,
            "deadline_misses_from_samples": misses,
            "p99_s": p99,
            "max_s": max(latency_tail[vector_id]["values"]) if count else None,
        }
    image_latencies = {}
    for vector_id, (flow, node, count, misses, deadline) in image_latency_count.items():
        image_latencies.setdefault(flow, {})[node] = {
            "samples": count,
            "deadline_misses_from_samples": misses,
            "p99_s": min(image_latency_tail[vector_id]["values"]) if count else None,
            "max_s": max(image_latency_tail[vector_id]["values"]) if count else None,
        }
    fallback_groups = {}
    for (flow, node, image_index), image in fallback_images.items():
        period, offset, packets_per_image = camera_schedule[flow]
        if image["frames"] != packets_per_image:
            continue
        available = round((offset + period * image_index) * 1e12) / 1e12
        latency = image["last_rx"] - available
        deadline = float(flow_catalog[flow].get("deadline_us") or 0) / 1e6
        group = fallback_groups.setdefault((flow, node), {"values": [], "misses": 0})
        group["values"].append(latency)
        group["misses"] += int(deadline > 0 and latency > deadline)
    for (flow, node), group in fallback_groups.items():
        if (flow, node) in image_vector_receivers:
            continue
        values = sorted(group["values"])
        count = len(values)
        keep = max(1, math.floor(0.01 * count) + 1)
        image_latencies.setdefault(flow, {})[node] = {
            "samples": count,
            "deadline_misses_from_samples": group["misses"],
            "p99_s": values[count - keep] if count else None,
            "max_s": values[-1] if count else None,
            "reconstructed_from_packet_vectors": True,
        }
    stability = []
    for info in queue_info.values():
        previous_time, previous_value = info["previous"]
        integrate(info, previous_time, WARMUP + MEASUREMENT, previous_value)
        if previous_time < WARMUP + MEASUREMENT:
            info["max_occupancy_bits"] = max(info["max_occupancy_bits"], previous_value)
        means = [area / BIN_SECONDS for area in info["bins"]]
        tail = means[-3:]
        threshold = info["capacity_bits"] * STABILITY_FRACTION
        grows = tail[0] < tail[1] < tail[2] and tail[2] - tail[0] > threshold
        stability.append({"queue": info["module"], "tc": info["tc"],
                          "mean_occupancy_bits_5s": means,
                          "max_occupancy_bits": info["max_occupancy_bits"],
                          "capacity_bits": info["capacity_bits"],
                          "sustained_growth": grows})
    require(queue_info, f"{vec_path.name}: no queue occupancy samples available")
    require(len(queue_info) == expected_queue_count,
            f"{vec_path.name}: found {len(queue_info)} per-class occupancy series, expected {expected_queue_count}")
    require(latencies, f"{vec_path.name}: no per-flow latency samples available")
    for flow, info in run_summary["flows"].items():
        for receiver in info["receivers"]:
            samples = latencies.get(flow, {}).get(receiver)
            received = info["receivers"][receiver]["measured_packets"]
            require(samples is not None or received == 0,
                    f"{flow}/{receiver}: missing latency vector for delivered packets")
            if samples is None:
                latencies.setdefault(flow, {})[receiver] = {"samples": 0, "p99_s": None, "max_s": None}
            else:
                require(samples["samples"] == received,
                        f"{flow}/{receiver}: latency vector has {samples['samples']} samples, receiver CSV has {received} measured packets")
                csv_max = info["receivers"][receiver]["max_latency_s"]
                require(samples["max_s"] is not None and
                        math.isclose(samples["max_s"], csv_max, rel_tol=0, abs_tol=1e-12),
                        f"{flow}/{receiver}: vector maximum {samples['max_s']} differs from receiver CSV {csv_max}")
                csv_misses = info["receivers"][receiver]["deadline_misses"]
                require(samples["deadline_misses_from_samples"] == csv_misses,
                        f"{flow}/{receiver}: vector-derived deadline misses {samples['deadline_misses_from_samples']} differs from receiver CSV {csv_misses}")
    drop_by_queue = {(item["module"], item["tc"]): item for item in drop_vector_info.values()}
    measurement_drops = [{
        "queue": info["module"], "tc": info["tc"],
        "packets": drop_by_queue.get((info["module"], info["tc"]), {}).get("packets", 0),
        "bytes": drop_by_queue.get((info["module"], info["tc"]), {}).get("bytes", 0),
    } for info in queue_info.values()]
    return latencies, image_latencies, stability, measurement_drops, bool(drop_vector_info)


def assess_qos(summary, latencies, image_latencies):
    flows = {row["flow_id"]: row for row in csv.DictReader((SIM / "zonal/traffic/flows.csv").open())}
    metrics = {}
    for flow_id, flow in flows.items():
        info = summary["flows"][flow_id]
        source = next(csv.DictReader((summary["directory"] / f"{flow_id}-{flow['source']}-tx.csv").open()))
        offered = int(source["measured_packets"])
        offered_images = (offered_camera_images(flow, summary["run"])
                          if flow["family"] == "camera" else 0)
        receivers = {}
        for node, rx in info["receivers"].items():
            received = int(rx["measured_packets"])
            app_bytes = int(rx["measured_app_bytes"])
            missed_late = int(rx["deadline_misses"])
            lost_or_late = max(0, offered - (received - missed_late))
            miss_ratio = lost_or_late / offered if offered else 0.0
            image_rx = next(csv.DictReader((summary["directory"] / f"{flow_id}-{node}-rx.csv").open()))
            image = None
            if flow["family"] == "camera":
                image_samples = image_latencies.get(flow_id, {}).get(node)
                require(image_samples is not None,
                        f"{flow_id}/{node}: missing image-completion metric or exact C0 reconstruction")
                image_completed = int(image_rx.get("completed_images") or image_samples["samples"])
                image_misses = int(image_rx.get("image_deadline_misses") or
                                   image_samples["deadline_misses_from_samples"])
                require(image_samples["samples"] == image_completed,
                        f"{flow_id}/{node}: image-completion vector count does not match completed-images CSV")
                require(image_samples["deadline_misses_from_samples"] == image_misses,
                        f"{flow_id}/{node}: vector-derived image deadline misses differ from receiver CSV")
                image_loss_or_late = max(0, offered_images - image_completed) + image_misses
                image = {**(image_latencies.get(flow_id, {}).get(node) or
                            {"samples": 0, "p99_s": None, "max_s": None}),
                         "offered_images": offered_images,
                         "source_reported_measured_images": (int(source["measured_images"])
                                                              if source.get("measured_images") not in (None, "")
                                                              else None),
                         "completed_images": image_completed,
                         "deadline_misses_completed": image_misses,
                         "deadline_miss_ratio_including_missing_images": (
                             image_loss_or_late / offered_images if offered_images else 0.0),
                         "deadline_s": float(flow["deadline_us"]) / 1e6,
                         "metric_source": ("packet-vector reconstruction" if
                                           image_samples.get("reconstructed_from_packet_vectors")
                                           else "imageCompletionLatency vector")}
            receivers[node] = {"offered_packets": offered,
                               "received_packets": received,
                               "useful_throughput_mbps": app_bytes * 8 / (MEASUREMENT * 1_000_000),
                               "deadline_misses_received": missed_late,
                               "deadline_miss_ratio_including_loss": miss_ratio,
                               "goodput_payload_ratio": (app_bytes / int(source["measured_app_bytes"]) if int(source["measured_app_bytes"]) else 0.0),
                               "packet_loss_ratio": max(0, offered - received) / offered if offered else 0.0,
                               "latency": latencies.get(flow_id, {}).get(node),
                               "image_completion": image}
        category = flow["criticality"]
        for receiver in receivers.values():
            if category.endswith("hard"):
                deadline_misses = (receiver["image_completion"]["deadline_miss_ratio_including_missing_images"]
                                   if receiver["image_completion"] else
                                   receiver["deadline_miss_ratio_including_loss"])
                receiver["viable"] = deadline_misses == 0
            elif "soft" in category:
                deadline_misses = (receiver["image_completion"]["deadline_miss_ratio_including_missing_images"]
                                   if receiver["image_completion"] else
                                   receiver["deadline_miss_ratio_including_loss"])
                receiver["viable"] = deadline_misses <= 0.01
            elif category == "low":
                receiver["viable"] = (receiver["goodput_payload_ratio"] >= 0.95 and
                                      receiver["packet_loss_ratio"] <= 0.01)
            else:
                receiver["viable"] = None
        metrics[flow_id] = {"criticality": category, "receivers": receivers}
    return metrics


def run_cell(config, output, env=None, inet=None, execute=True):
    if execute:
        command = [str(ROOT / "src/zonal-ivn-tsn"), "-u", "Cmdenv",
                   "-n", f".:{ROOT / 'src'}:{ROOT / 'tests'}:{inet / 'src'}",
                   "-f", "omnetpp.ini", "-c", config, "--cmdenv-express-mode=true",
                   "--cmdenv-event-banners=false",
                   "--**.app[*].latency.result-recording-modes=+vector",
                   "--**.app[*].imageCompletionLatency.result-recording-modes=+vector",
                   "--**.queueLength.result-recording-modes=+vector",
                   "--**.queueBitLength.result-recording-modes=+vector",
                   "--**.droppedPacketLengthsQueueOverflow.result-recording-modes=+vector",
                   "--**.queueingTime.result-recording-modes=+histogram",
                   "--**.utilization.result-recording-modes=+histogram"]
        log = output / f"{config}.log"
        with log.open("w") as stream:
            result = subprocess.run(command, cwd=SIM, env=env, stdout=stream, stderr=subprocess.STDOUT)
        contents = log.read_text(errors="replace")
        require(result.returncode == 0 and "<!> Error:" not in contents and
                "Simulation time limit reached" in contents, f"{config} failed; inspect {log}")
    run_dir = output / f"{config}-0"
    summary = check_run(run_dir)
    summary["directory"] = run_dir
    expected_load = int(config.split("_L", 1)[1][0])
    expected_aggregation = "A" + config.rsplit("_A", 1)[1]
    treatment = config.split("_", 2)[1]
    require(int(summary["run"]["load"]) == expected_load, f"{config}: wrong effective offered load")
    require(summary["run"]["aggregation"] == expected_aggregation, f"{config}: wrong aggregation")
    expected_shaping = "1" if treatment == "C1" else "0"
    require(summary["run"].get("source_pre_shaping", "0") == expected_shaping,
            f"{config}: wrong source pre-shaping mode")
    if treatment == "C1":
        require(math.isclose(float(summary["run"]["adas_spacing_limit"]), 324e-6, abs_tol=1e-12) and
                math.isclose(float(summary["run"]["vision_spacing_limit"]), 500e-6, abs_tol=1e-12),
                f"{config}: C1 spacing limits differ from P1")
    require(float(summary["run"]["warmup"]) == WARMUP and
            float(summary["run"]["measurement"]) == MEASUREMENT, f"{config}: wrong duration")
    vec_path = next(output.glob(f"{config}-#*.vec"), None)
    sca_path = output / f"{config}-#0.sca"
    require(vec_path is not None and sca_path.exists(), f"{config}: missing OMNeT++ result files")
    params = parse_sca(sca_path)
    interfaces, queues = verify_configuration(params, config, run_dir)
    camera_source_queue_drops = {}
    for camera, tc in (("CAM1", 6), ("CAM2", 6), ("CAM3", 4), ("CAM4", 4)):
        queue = f"ZonalIVN.{camera}.eth[0].macLayer.queue.queue[{tc}]"
        dropped = params.get((queue, "droppedPacketsQueueOverflow:count"))
        require(dropped is not None, f"{config}: missing drop counter for {queue}")
        camera_source_queue_drops[camera] = int(float(dropped))
        require(camera_source_queue_drops[camera] == 0,
                f"{config}: camera source queue overflow at {queue}: {dropped}")
        flow = f"F{int(camera[-1]) + 1:02d}" if camera in ("CAM1", "CAM2") else f"F{int(camera[-1]) + 1:02d}"
        generated = summary["flows"][flow]["generated_packets"]
        require(generated % 30 == 0,
                f"{config}: {flow} generated {generated} frames, not complete 30-frame images")
    for interface in interfaces:
        for tc in range(8):
            queue = interface + f".queue[{tc}]"
            require(params.get((queue, "queueingTime:histogram")) == "recorded",
                    f"{config}: missing queueing-time histogram at {queue}")
        phy = interface.removesuffix(".macLayer.queue") + ".phyLayer.transmitter"
        require(params.get((phy, "utilization:histogram")) == "recorded",
                f"{config}: missing utilization histogram at {phy}")
    latencies, image_latencies, stability, measurement_drops, drop_vectors_available = read_vectors(
        vec_path, params, summary, len(queues))
    if treatment == "C1" and summary["drops"] > 0:
        require(drop_vectors_available and len(measurement_drops) == len(queues),
                f"{config}: drops occurred but timestamped per-queue samples are missing")
    qos = assess_qos(summary, latencies, image_latencies)
    queueing_time, link_utilization = summarize_sca_metrics(params)
    require(len(queueing_time) == len(queues),
            f"{config}: missing queueing-time histogram summaries ({len(queueing_time)}/{len(queues)})")
    # Physical utilization is recorded at both ends of each of the 28
    # full-duplex links (56 transmitters); class egress queues exist on 42 of
    # those interfaces.
    require(len(link_utilization) == 56,
            f"{config}: missing utilization histogram summaries ({len(link_utilization)}/56 transmitters)")
    nonstable = [q for q in stability if q["sustained_growth"]]
    for flow, metric in qos.items():
        for receiver, values in metric["receivers"].items():
            if values["viable"] is False:
                break
    cell_viable = (not nonstable and all(v["viable"] is not False
                                        for m in qos.values() for v in m["receivers"].values()))
    report = {"config": config, "treatment": treatment,
              "load": expected_load, "aggregation": expected_aggregation,
              "offered_packets": summary["source_packets"], "recorded_drops": summary["drops"],
              "camera_source_queue_drops": camera_source_queue_drops,
              "egress_interfaces_checked": len(interfaces), "class_queues_checked": len(queues),
              "qos": qos, "queue_stability": stability,
              "queueing_time": queueing_time, "link_utilization": link_utilization,
              "measurement_drops_by_queue": (measurement_drops
                                               if drop_vectors_available or summary["drops"] == 0
                                               else None),
              "measurement_drop_samples_available": drop_vectors_available,
              "measurement_drops_zero_inferred": not drop_vectors_available and summary["drops"] == 0,
              "acceptance_policy": {
                  "hard_critical_flows": sorted(
                      row["flow_id"] for row in csv.DictReader(
                          (SIM / "zonal/traffic/flows.csv").open())
                      if row["criticality"].endswith("hard")),
                  "criticality_source": "simulations/zonal/traffic/flows.csv",
                  "camera_deadline_gate": "deadline from image availability to reception of the last of 30 frames; incomplete images count as misses",
                  "noncamera_deadline_gate": "per-packet latency from CreationTimeTag to receiver; packet losses count as misses",
              },
              "nonstable_queues": nonstable,
              "viable": cell_viable}
    (run_dir / f"{treatment.lower()}-acceptance.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"PASS {config}: {report['offered_packets']} packets, {report['recorded_drops']} drops, "
          f"{len(interfaces)} egresses/{len(queues)} class queues checked; "
          f"cell {'VIABLE' if cell_viable else 'NONVIABLE'}", flush=True)
    return report, run_dir


def has_complete_raw_result(config, output):
    run_dir = output / f"{config}-0"
    vec_path = next(output.glob(f"{config}-#*.vec"), None)
    sca_path = output / f"{config}-#0.sca"
    log_path = output / f"{config}.log"
    if not (run_dir.is_dir() and (run_dir / "run.csv").is_file() and
            (run_dir / "releases.csv").is_file() and sca_path.is_file() and
            vec_path is not None and log_path.is_file()):
        return False
    log_text = log_path.read_text(errors="replace")
    if "Simulation time limit reached -- at t=31.05s" not in log_text or "End." not in log_text:
        return False
    if config.startswith("Validate_C0_"):
        # C0's unpaced image completion is exactly reconstructible from the
        # packet vectors, so legacy C0 cells without this vector remain valid.
        return True
    with vec_path.open(errors="replace") as stream:
        for line in stream:
            if line.startswith("vector ") and "imageCompletionLatency:vector" in line:
                return True
            if line and line[0].isdigit():
                return False
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inet-root", default=os.environ.get("INET_ROOT"))
    parser.add_argument("--omnetpp-root", default=os.environ.get("OMNETPP_ROOT"))
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--reassess-existing", action="store_true",
                        help="reapply P1 acceptance categories to completed result reports without rerunning simulations")
    parser.add_argument("--resume", action="store_true",
                        help="reuse complete raw cells with the required metric vectors and run missing cells")
    args = parser.parse_args()
    require(args.jobs > 0, "--jobs must be positive")
    output = SIM / "results/C0/p1-validation-64KiB"
    configs = [f"Validate_C0_L{level}_A{aggregation}"
               for level in range(4) for aggregation in range(2)]
    if args.reassess_existing:
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            reports = list(pool.map(lambda config: run_cell(config, output, execute=False), configs))
        reference = None
        for _, run_dir in reports:
            with (run_dir / "events.csv").open() as stream:
                events = [(r["flow"], r["block"], r["signature"], r["duration"], r["volume_bytes"])
                          for r in csv.DictReader(stream)]
            if reference is None:
                reference = events
            require(events == reference, f"{run_dir.name}: F21/F22 transient events not paired")
        result = {report["config"]: report for report, _ in reports}
        (output / "C0_acceptance.json").write_text(json.dumps(result, indent=2) + "\n")
        viable = sum(report["viable"] for report, _ in reports)
        print(f"C0 assessment complete from existing raw results: {viable}/8 cells meet "
              f"P1 viability thresholds. Evidence: {output}")
        return
    if not args.inet_root:
        parser.error("Set INET_ROOT or pass --inet-root")
    inet = Path(args.inet_root).resolve()
    omnetpp = Path(args.omnetpp_root).resolve() if args.omnetpp_root else None
    opp_run = shutil.which("opp_run")
    if omnetpp is None and opp_run:
        omnetpp = Path(opp_run).resolve().parent.parent
    if omnetpp is None:
        parser.error("Load the OMNeT++ environment or pass --omnetpp-root")
    env = os.environ.copy()
    library_paths = [str(omnetpp / "lib"), str(inet / "src")]
    if env.get("LD_LIBRARY_PATH"):
        library_paths.append(env["LD_LIBRARY_PATH"])
    env["LD_LIBRARY_PATH"] = ":".join(library_paths)
    output.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, str(ROOT / "scripts/catalog/generate.py"), "--check"], check=True)
    def assess_cell(config):
        execute = not (args.resume and has_complete_raw_result(config, output))
        return run_cell(config, output, env, inet, execute=execute)
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        reports = list(pool.map(assess_cell, configs))

    # L/A may change camera alignment and scaling but must retain paired transient choices.
    reference = None
    for _, run_dir in reports:
        with (run_dir / "events.csv").open() as stream:
            events = [(r["flow"], r["block"], r["signature"], r["duration"], r["volume_bytes"])
                      for r in csv.DictReader(stream)]
        if reference is None:
            reference = events
        require(events == reference, f"{run_dir.name}: F21/F22 transient events not paired")
    result = {report["config"]: report for report, _ in reports}
    (output / "C0_acceptance.json").write_text(json.dumps(result, indent=2) + "\n")
    viable = sum(report["viable"] for report, _ in reports)
    print(f"C0 assessment complete: {viable}/8 cells meet P1 viability thresholds. "
          f"Evidence: {output}")


if __name__ == "__main__":
    main()
