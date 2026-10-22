#!/usr/bin/env python3
"""Run full-duration C0/C1 cells and assess them against P1 acceptance rules."""
import argparse
import csv
import gzip
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


def reconcile_queue_overflow_scopes(config, per_queue, whole_run_drop_total):
    """Compare SCA and timestamped drops in the same post-warm-up window.

    TrafficAudit aggregates from t=0, while SCA counters use OMNeT++'s
    automatic warm-up filter. The timestamped packet-length vector supplies
    the matching SCA population and separates measurement from drain.
    """
    for item in per_queue:
        sca_count = int(item["sca_post_warmup"])
        vector_count = int(item["vector_post_warmup"])
        require(sca_count == vector_count,
                f"{config}: {item['queue']} SCA post-warm-up overflow count {sca_count} "
                f"differs from timestamped post-warm-up samples {vector_count}")

    post_warmup_total = sum(int(item["sca_post_warmup"]) for item in per_queue)
    whole_run_drop_total = int(whole_run_drop_total)
    require(post_warmup_total <= whole_run_drop_total,
            f"{config}: post-warm-up SCA overflow total {post_warmup_total} "
            f"exceeds whole-run TrafficAudit drops {whole_run_drop_total}")
    return {
        "traffic_audit_drops_entire_simulation": whole_run_drop_total,
        "sca_and_timestamped_queue_overflow_drops_post_warmup_including_drain": post_warmup_total,
        "whole_run_minus_post_warmup_scope_delta": whole_run_drop_total - post_warmup_total,
        "whole_run_scope": "TrafficAudit queue packetDropped callbacks from t=0 through simulation end",
        "sca_scope": "droppedPacketsQueueOverflow count with OMNeT++ automatic warm-up filtering; t>=warmup through drain",
        "timestamped_scope": "droppedPacketLengthsQueueOverflow vector, independently split into measurement and drain after warm-up",
        "limitation": "drops.csv stores whole-run aggregates and first/last timestamps, not a warm-up-binned count; the scope delta is not silently called a measurement loss",
    }


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
                # These are arithmetic statistics over UtilizationFilter output
                # samples, not a time-weighted mean/max over the measurement
                # window. The SCA scalar does not retain timestamps or interval
                # durations, so it cannot be converted after the run.
                "mean_percent": None,
                "max_percent": None,
                "diagnostic_histogram_sample_mean_percent": scalar_field(
                    params, module, name, "mean"),
                "diagnostic_histogram_sample_max_percent": scalar_field(
                    params, module, name, "max"),
                "metric_status": "unavailable_time_weighted_utilization",
                "unavailable_reason": (
                    "Only whole-simulation histogram summary fields were retained; "
                    "sample timestamps and interval durations are unavailable, "
                    "and audited rows contain zero utilization despite nonzero "
                    "transmitter throughput."
                ),
            })
    return sorted(queueing_time, key=lambda row: (row["queue"], row["tc"])), sorted(
        utilization, key=lambda row: row["transmitter"])


def recompute_queue_occupancy_trace(trace_path):
    """Independently reconstruct measurement occupancy metrics from retained event changes."""
    trace_path = Path(trace_path)
    with gzip.open(str(trace_path) + ".meta.json.gz", "rt", encoding="utf-8") as stream:
        meta = json.load(stream)
    require(meta.get("format") == "p1-queue-occupancy-events-v1",
            f"{trace_path}: unsupported queue trace format")
    start, stop = meta["measurement_window_s"]
    observation_stop = meta["observation_window_s"][1]
    width = float(meta["bin_width_s"])
    threshold_fraction = float(meta["near_capacity_threshold"])
    states = {}
    for q in meta["queues"]:
        qi = int(q["queue_index"])
        states[qi] = {"module": q["module"], "tc": int(q["tc"]),
                      "capacity_bits": int(q["capacity_bits"]),
                      "previous_time": 0.0, "previous_value": 0.0,
                      "bins_area": [0.0] * 6, "near_capacity_s": 0.0,
                      "max_occupancy_bits": 0.0}

    def integrate(state, left, right, value):
        left, right = max(left, start), min(right, stop)
        while left < right:
            index = min(5, int((left - start) // width))
            boundary = start + (index + 1) * width
            end = min(right, boundary)
            state["bins_area"][index] += value * (end - left)
            if value >= threshold_fraction * state["capacity_bits"]:
                state["near_capacity_s"] += end - left
            left = end

    with gzip.open(trace_path, "rt", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        require(reader.fieldnames == ["queue_index", "timestamp_s", "occupancy_bits"],
                f"{trace_path}: unexpected queue trace columns")
        for row in reader:
            qi = int(row["queue_index"])
            require(qi in states, f"{trace_path}: unknown queue index {qi}")
            timestamp = float(row["timestamp_s"])
            value = float(row["occupancy_bits"])
            state = states[qi]
            previous_time, previous_value = state["previous_time"], state["previous_value"]
            if timestamp >= previous_time:
                integrate(state, previous_time, timestamp, previous_value)
                if timestamp > start and previous_time < stop:
                    state["max_occupancy_bits"] = max(state["max_occupancy_bits"], previous_value)
                state["previous_time"], state["previous_value"] = timestamp, value
                if start <= timestamp < stop:
                    state["max_occupancy_bits"] = max(state["max_occupancy_bits"], value)
    result = []
    for qi, state in sorted(states.items()):
        integrate(state, state["previous_time"], stop, state["previous_value"])
        means = [area / width for area in state["bins_area"]]
        tail = means[-3:]
        growth_threshold = state["capacity_bits"] * STABILITY_FRACTION
        sustained_growth = tail[0] < tail[1] < tail[2] and tail[2] - tail[0] > growth_threshold
        result.append({
            "queue": state["module"], "tc": state["tc"],
            "mean_occupancy_bits_5s": means,
            "mean_occupancy_bits_measurement": sum(state["bins_area"]) / (stop - start),
            "fraction_measurement_at_least_90pct_capacity": state["near_capacity_s"] / (stop - start),
            "max_occupancy_bits": state["max_occupancy_bits"],
            "capacity_bits": state["capacity_bits"],
            "sustained_growth": sustained_growth,
        })
    require(len(result) == len(meta["queues"]), f"{trace_path}: queue trace population incomplete")
    require(all(state["previous_time"] <= observation_stop for state in states.values()),
            f"{trace_path}: trace exceeds declared observation window")
    return result


def audit_active_classes(expected_active, observed_active, allow_gptp_control=False):
    """Check catalog classes, optionally allowing gPTP PCP 7 on clock-aware egresses.

    The exception is deliberately narrow: PCP 7 may be an additional active
    queue only on interfaces of the synchronized HPC, CSW, and zonal switches.
    Catalog PCPs must still be present exactly as observed, and all other extra
    classes remain an error.
    """
    extras_by_queue = {}
    for queue, classes in expected_active.items():
        observed = observed_active.get(queue, set())
        extras = observed - classes
        gptp_egress = bool(re.match(
            r"^ZonalIVN\.(?:HPC|CSW|Z[123]\.ZSW)\.eth\[\d+\]\.macLayer\.queue$", queue))
        permitted = {7} if allow_gptp_control and gptp_egress else set()
        require(classes <= observed and extras <= permitted,
                f"observed PCP queues at {queue} are {observed}, expected {classes}"
                + (f" plus gPTP control PCPs {permitted}" if permitted else ""))
        if extras:
            extras_by_queue[queue] = sorted(extras)
    # Control traffic can activate an egress with no catalog data flow.
    for queue, observed in observed_active.items():
        if queue in expected_active or not observed:
            continue
        gptp_egress = bool(re.match(
            r"^ZonalIVN\.(?:HPC|CSW|Z[123]\.ZSW)\.eth\[\d+\]\.macLayer\.queue$", queue))
        require(allow_gptp_control and gptp_egress and observed <= {7},
                f"unexpected active PCP queues at {queue}: {observed}")
        extras_by_queue[queue] = sorted(observed)
    return extras_by_queue


def verify_configuration(params, config, run_dir, allow_gptp_control=False,
                         allow_scheduled_gates=False):
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
        gcl_interfaces = {"ZonalIVN.HPC.eth[0].macLayer.queue",
                          *(f"ZonalIVN.CSW.eth[{i}].macLayer.queue" for i in (1, 2, 3)),
                          *(f"ZonalIVN.Z{z}.ZSW.eth[4].macLayer.queue" for z in (1, 2)),
                          # F10 exits at Z3.ZSW.eth[5]. The corrected full-path
                          # pilot diagnostic gates that actual route egress.
                          "ZonalIVN.Z3.ZSW.eth[5].macLayer.queue"}
        for tc in range(8):
            gate = interface.replace(".classifier", "") + f".transmissionGate[{tc}]"
            require(params.get((gate, "initiallyOpen")) == "true", f"{config}: gate {gate} is not open")
            durations = params.get((gate, "durations"))
            scheduled = durations != "[]"
            require(not scheduled or (allow_scheduled_gates and interface.replace(".classifier", "") in gcl_interfaces),
                    f"{config}: unexpected gate schedule at {gate}")
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
    control_queues = audit_active_classes(expected_active, observed_active,
                                          allow_gptp_control=allow_gptp_control)
    return interfaces, queue_modules, control_queues


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
                                             "max_occupancy_bits": 0.0, "near_capacity_seconds": 0.0}
        elif metric == "droppedPacketLengthsQueueOverflow:vector":
            match = re.fullmatch(r"(ZonalIVN\..*\.eth\[\d+\]\.macLayer\.queue\.queue\[(\d+)\])", module)
            if match:
                drop_vector_info[vector_id] = {"module": match.group(1), "tc": int(match.group(2)),
                                               "packets_post_warmup": 0, "bytes_post_warmup": 0,
                                               "packets_measurement": 0, "bytes_measurement": 0,
                                               "packets_drain": 0, "bytes_drain": 0}

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
        if value >= 0.90 * info["capacity_bits"]:
            info["near_capacity_seconds"] += right - left
        while left < right:
            index = min(5, int((left - WARMUP) // BIN_SECONDS))
            boundary = WARMUP + (index + 1) * BIN_SECONDS
            end = min(right, boundary)
            info["bins"][index] += value * (end - left)
            left = end

    queue_trace_path = Path(run_summary["directory"]) / "queue_occupancy_events.csv.gz"
    queue_index = {module: i for i, module in enumerate(sorted(
        info["module"] for info in queue_info.values()))}
    queue_by_module = {info["module"]: info for info in queue_info.values()}
    trace_metadata = {
        "format": "p1-queue-occupancy-events-v1",
        "time_semantics": "right-continuous piecewise-constant queue occupancy; each row replaces state at timestamp_s",
        "occupancy_unit": "bits",
        "initial_state": "all queues are 0 bits at t=0 s; recorded explicitly in CSV",
        "measurement_window_s": [WARMUP, WARMUP + MEASUREMENT],
        "observation_window_s": [0.0, WARMUP + MEASUREMENT + DRAIN],
        "measurement_window_convention": "half-open [start,end); integrate through the end boundary",
        "bin_width_s": BIN_SECONDS,
        "bin_edges_s": [WARMUP + i * BIN_SECONDS for i in range(7)],
        "near_capacity_threshold": 0.90,
        "queues": [{"queue_index": queue_index[module], "module": module,
                    "tc": queue_by_module[module]["tc"],
                    "capacity_bits": queue_by_module[module]["capacity_bits"]}
                   for module in sorted(queue_index, key=queue_index.get)],
    }
    queue_trace_stream = gzip.open(queue_trace_path, "wt", encoding="utf-8", newline="", compresslevel=6)
    queue_trace_writer = csv.writer(queue_trace_stream)
    queue_trace_writer.writerow(["queue_index", "timestamp_s", "occupancy_bits"])
    for module in sorted(queue_index, key=queue_index.get):
        queue_trace_writer.writerow([queue_index[module], "0", "0"])
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
                if 0 <= time <= WARMUP + MEASUREMENT + DRAIN:
                    queue_trace_writer.writerow([queue_index[info["module"]], format(time, ".17g"), format(value, ".17g")])
            dropped = drop_vector_info.get(vector_id)
            if dropped is not None and time >= WARMUP:
                packet_bytes = int(round(value / 8))  # packetLength result is in bits.
                dropped["packets_post_warmup"] += 1
                dropped["bytes_post_warmup"] += packet_bytes
                if time < WARMUP + MEASUREMENT:
                    dropped["packets_measurement"] += 1
                    dropped["bytes_measurement"] += packet_bytes
                else:
                    dropped["packets_drain"] += 1
                    dropped["bytes_drain"] += packet_bytes

    for module in sorted(queue_index, key=queue_index.get):
        _, value = queue_by_module[module]["previous"]
        queue_trace_writer.writerow([queue_index[module], format(WARMUP + MEASUREMENT + DRAIN, ".17g"), format(value, ".17g")])
    queue_trace_stream.close()
    with gzip.open(str(queue_trace_path) + ".meta.json.gz", "wt", encoding="utf-8", compresslevel=6) as meta_stream:
        json.dump(trace_metadata, meta_stream, separators=(",", ":"))

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
                          "mean_occupancy_bits_measurement": sum(info["bins"]) / MEASUREMENT,
                          "fraction_measurement_at_least_90pct_capacity": info["near_capacity_seconds"] / MEASUREMENT,
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
        "packets": drop_by_queue.get((info["module"], info["tc"]), {}).get("packets_measurement", 0),
        "bytes": drop_by_queue.get((info["module"], info["tc"]), {}).get("bytes_measurement", 0),
        "packets_post_warmup_including_drain": drop_by_queue.get((info["module"], info["tc"]), {}).get("packets_post_warmup", 0),
        "bytes_post_warmup_including_drain": drop_by_queue.get((info["module"], info["tc"]), {}).get("bytes_post_warmup", 0),
        "drain_packets": drop_by_queue.get((info["module"], info["tc"]), {}).get("packets_drain", 0),
        "drain_bytes": drop_by_queue.get((info["module"], info["tc"]), {}).get("bytes_drain", 0),
    } for info in queue_info.values()]
    # Preserve a compressed exact upper tail for the P1 nearest-rank p99 and
    # maximum. The full vectors can then be removed after all run audits pass.
    compact = {"format": "p1-upper-tail-samples-v1", "quantile": "nearest-rank-p99",
               "packet": {}, "image": {}}
    for vector_id, (flow, node, count, misses, deadline) in latency_count.items():
        compact["packet"][f"{flow}/{node}"] = {"sample_count": count, "deadline_misses": misses,
            "deadline_s": deadline, "upper_tail_s": sorted(latency_tail[vector_id]["values"])}
    for vector_id, (flow, node, count, misses, deadline) in image_latency_count.items():
        compact["image"][f"{flow}/{node}"] = {"sample_count": count, "deadline_misses": misses,
            "deadline_s": deadline, "upper_tail_s": sorted(image_latency_tail[vector_id]["values"])}
    for (flow, node), group in fallback_groups.items():
        if (flow, node) in image_vector_receivers:
            continue
        values = sorted(group["values"]); count = len(values); keep = max(1, math.floor(.01*count)+1)
        compact["image"][f"{flow}/{node}"] = {"sample_count":count,"deadline_misses":group["misses"],
            "deadline_s":float(flow_catalog[flow]["deadline_us"])/1e6,
            "upper_tail_s":values[-keep:],"reconstructed_from_packet_vectors":True}
    with gzip.open(Path(run_summary["directory"])/"latency_upper_tails.json.gz", "wt",
                   encoding="utf-8", compresslevel=6) as stream:
        json.dump(compact,stream,separators=(",",":"))
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


def run_cell(config, output, env=None, inet=None, execute=True, result_dir_override=None,
             extra_args=(), allow_gptp_control=False, allow_scheduled_gates=False):
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
        if result_dir_override is not None:
            command.append(f"--result-dir={result_dir_override}")
        command.extend(extra_args)
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
    interfaces, queues, control_queues = verify_configuration(
        params, config, run_dir, allow_gptp_control=allow_gptp_control,
        allow_scheduled_gates=allow_scheduled_gates)
    summary["additional_active_gptp_control_queues"] = control_queues
    camera_source_queue_drops = {}
    flow_classes = {r["flow_id"]: int(r["traffic_class"])
                    for r in csv.DictReader((SIM / "zonal/traffic/flows.csv").open())}
    for camera, flow in (("CAM1", "F02"), ("CAM2", "F03"), ("CAM3", "F04"), ("CAM4", "F05")):
        tc = flow_classes[flow]
        queue = f"ZonalIVN.{camera}.eth[0].macLayer.queue.queue[{tc}]"
        dropped = params.get((queue, "droppedPacketsQueueOverflow:count"))
        require(dropped is not None, f"{config}: missing drop counter for {queue}")
        camera_source_queue_drops[camera] = int(float(dropped))
        require(camera_source_queue_drops[camera] == 0,
                f"{config}: camera source queue overflow at {queue}: {dropped}")
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
    if summary["drops"] > 0:
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
    queue_drops = []
    drop_reconciliation_inputs = []
    vector_drops_by_queue = {(x["queue"], x["tc"]): x for x in measurement_drops}
    for interface in interfaces:
        for tc in range(8):
            module = interface + f".queue[{tc}]"
            raw = params.get((module, "droppedPacketsQueueOverflow:count"), 0)
            vector = vector_drops_by_queue.get((module, tc), {})
            sca_count = int(float(raw))
            vector_count = int(vector.get("packets_post_warmup_including_drain", 0))
            drop_reconciliation_inputs.append({"queue": module,
                "sca_post_warmup": sca_count, "vector_post_warmup": vector_count})
            queue_drops.append({"queue": module, "tc": tc,
                "capacity_bits": int(str(params[(module, "dataCapacity")]).removesuffix("b")),
                "overflow_drops_post_warmup_including_drain": sca_count,
                "overflow_drops_measurement_window": int(vector.get("packets", 0)),
                "overflow_drops_drain": int(vector.get("drain_packets", 0)),
                "overflow_drop_bytes_post_warmup_including_drain": int(vector.get("bytes_post_warmup_including_drain", 0)),
                "drop_metric": "droppedPacketsQueueOverflow SCA/vector; OMNeT++ automatic warm-up filter applies"})
    drop_reconciliation = reconcile_queue_overflow_scopes(
        config, drop_reconciliation_inputs, summary["drops"])
    queue_drop_total_post_warmup = drop_reconciliation[
        "sca_and_timestamped_queue_overflow_drops_post_warmup_including_drain"]
    for flow, metric in qos.items():
        for receiver, values in metric["receivers"].items():
            if values["viable"] is False:
                break
    cell_viable = (not nonstable and all(v["viable"] is not False
                                        for m in qos.values() for v in m["receivers"].values()))
    report = {"config": config, "treatment": treatment,
              "load": expected_load, "aggregation": expected_aggregation,
              "metric_windows": {
                  "simulation_observation_s": [0.0, WARMUP + MEASUREMENT + DRAIN],
                  "packet_creation_cohort_s": [WARMUP, WARMUP + MEASUREMENT],
                  "packet_delivery_observation_end_s": WARMUP + MEASUREMENT + DRAIN,
                  "image_availability_cohort_s": [WARMUP, WARMUP + MEASUREMENT],
                  "queue_occupancy_and_stability_s": [WARMUP, WARMUP + MEASUREMENT],
                  "measurement_drop_vector_s": [WARMUP, WARMUP + MEASUREMENT],
                  "SCA_overflow_counters": "post-warm-up (automatic warm-up filter) through drain; timestamped vector also split by measurement/drain",
                  "SCA_queueingTime_histograms": "entire simulation; not measurement-window filtered",
                  "link_utilization": "unavailable as a time-weighted measurement metric; retained SCA histogram scalars are diagnostic only",
                  "pending_queue_snapshot_s": WARMUP + MEASUREMENT + DRAIN,
              },
              "offered_packets": summary["source_packets"], "recorded_drops": summary["drops"],
              "flow_populations": {fid:{"generated_packets_entire_simulation":info["generated_packets"],
                  "measured_offered_packets":next(csv.DictReader((summary["directory"]/f"{fid}-{next(r['source'] for r in csv.DictReader((SIM/'zonal/traffic/flows.csv').open()) if r['flow_id']==fid)}-tx.csv").open()))['measured_packets']}
                  for fid,info in summary['flows'].items()},
              "pending_packet_count_at_simulation_end": summary.get("pending_packet_count_at_simulation_end", 0),
              "pending_packets_at_simulation_end": summary.get("pending_at_simulation_end", []),
              "camera_source_queue_drops": camera_source_queue_drops,
              "queue_overflow_drops_by_queue": queue_drops,
              "queue_overflow_drop_total_post_warmup_including_drain": queue_drop_total_post_warmup,
              "drop_reconciliation": drop_reconciliation,
              "egress_interfaces_checked": len(interfaces), "class_queues_checked": len(queues),
              "qos": qos, "queue_stability": stability,
              "queueing_time_scope":"whole simulation; includes warm-up and drain",
              "queue_stability_scope":"measurement window [1,31) s; time-integrated 5-second bins",
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
    parser.add_argument("--output-dir", type=Path, default=SIM / "results/C0/p1-validation-64KiB")
    parser.add_argument("--reassess-existing", action="store_true",
                        help="reapply P1 acceptance categories to completed result reports without rerunning simulations")
    parser.add_argument("--resume", action="store_true",
                        help="reuse complete raw cells with the required metric vectors and run missing cells")
    args = parser.parse_args()
    require(args.jobs > 0, "--jobs must be positive")
    output = args.output_dir if args.output_dir.is_absolute() else ROOT / args.output_dir
    output = output.resolve()
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
        return run_cell(config, output, env, inet, execute=execute,
                        result_dir_override=str(output.relative_to(SIM)))
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
