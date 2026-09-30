#!/usr/bin/env python3
"""Run and assess the eight full-duration C0 cells against P1 acceptance rules."""
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
# Analysis decision: these 100-us flows are treated as hard-critical for P1
# acceptance while the traffic catalog retains its original criticality labels.
HARD_CRITICAL_OVERRIDES = {"F01", "F06", "F07"}


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def parse_sca(sca_path):
    params = {}
    for line in sca_path.read_text(errors="replace").splitlines():
        if line.startswith("par "):
            _, module, name, value = line.split(" ", 3)
            params[module, name] = value.strip().strip('"')
        elif line.startswith("scalar "):
            _, module, name, value = line.split(" ", 3)
            params[module, name] = value.strip()
        elif line.startswith("statistic "):
            _, module, name = line.split(" ", 2)
            params[module, name] = "recorded"
    return params


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
            expected_capacity = "1048576b" if is_bottleneck else "262144b"
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

    app_flow = load_app_flow_map()
    # Keep only the largest 1% of latency samples per receiver to compute an exact
    # nearest-rank empirical p99 without holding millions of samples in memory.
    latency_count = {}
    latency_tail = {}
    queue_info = {}
    for vector_id, (module, metric) in definitions.items():
        if metric == "latency:vector" and ".app[" in module:
            match = re.fullmatch(r"(.*)\.app\[(\d+)\]", module)
            if match and (match.group(1), int(match.group(2))) in app_flow:
                flow = app_flow[match.group(1), int(match.group(2))]
                node = match.group(1).removeprefix("ZonalIVN.")
                # Latencies are meaningful at receivers only; sender modules also emit vectors.
                if run_summary["flows"].get(flow, {}).get("receivers", {}).get(node) is not None:
                    latency_count[vector_id] = (flow, node, 0)
                    latency_tail[vector_id] = []
        elif metric == "queueBitLength:vector":
            match = re.fullmatch(r"(ZonalIVN\..*\.eth\[\d+\]\.macLayer\.queue\.queue\[(\d+)\])", module)
            if match:
                queue = match.group(1)
                capacity = sca_params.get((queue, "dataCapacity"))
                if capacity:
                    queue_info[vector_id] = {"module": queue, "tc": int(match.group(2)),
                                             "capacity_bits": int(capacity.removesuffix("b")),
                                             "previous": (0.0, 0.0), "bins": [0.0] * 6}

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
            if len(parts) < 4 or not parts[0].isdigit():
                continue
            vector_id = int(parts[0])
            try:
                time = float(parts[-2])
                value = float(parts[-1])
            except ValueError:
                continue
            if vector_id in latency_count and WARMUP <= time < WARMUP + MEASUREMENT + DRAIN:
                flow, node, count = latency_count[vector_id]
                count += 1
                latency_count[vector_id] = (flow, node, count)
                heap = latency_tail[vector_id]
                keep = max(1, math.floor(0.01 * count) + 1)
                if len(heap) < keep:
                    heapq.heappush(heap, value)
                elif value > heap[0]:
                    heapq.heapreplace(heap, value)
            info = queue_info.get(vector_id)
            if info is not None:
                previous_time, previous_value = info["previous"]
                if time >= previous_time:
                    integrate(info, previous_time, time, previous_value)
                    info["previous"] = (time, value)

    latencies = {}
    for vector_id, (flow, node, count) in latency_count.items():
        latencies.setdefault(flow, {})[node] = {
            "samples": count,
            "p99_s": min(latency_tail[vector_id]) if count else None,
            "max_s": max(latency_tail[vector_id]) if count else None,
        }
    stability = []
    for info in queue_info.values():
        previous_time, previous_value = info["previous"]
        integrate(info, previous_time, WARMUP + MEASUREMENT, previous_value)
        means = [area / BIN_SECONDS for area in info["bins"]]
        tail = means[-3:]
        threshold = info["capacity_bits"] * STABILITY_FRACTION
        grows = tail[0] < tail[1] < tail[2] and tail[2] - tail[0] > threshold
        stability.append({"queue": info["module"], "tc": info["tc"],
                          "mean_occupancy_bits_5s": means,
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
    return latencies, stability


def assess_qos(summary, latencies):
    flows = {row["flow_id"]: row for row in csv.DictReader((SIM / "zonal/traffic/flows.csv").open())}
    metrics = {}
    for flow_id, flow in flows.items():
        info = summary["flows"][flow_id]
        source = next(csv.DictReader((summary["directory"] / f"{flow_id}-{flow['source']}-tx.csv").open()))
        offered = int(source["measured_packets"])
        receivers = {}
        for node, rx in info["receivers"].items():
            received = int(rx["measured_packets"])
            app_bytes = int(rx["measured_app_bytes"])
            missed_late = int(rx["deadline_misses"])
            lost_or_late = max(0, offered - (received - missed_late))
            miss_ratio = lost_or_late / offered if offered else 0.0
            receivers[node] = {"offered_packets": offered,
                               "received_packets": received,
                               "deadline_misses_received": missed_late,
                               "deadline_miss_ratio_including_loss": miss_ratio,
                               "goodput_payload_ratio": (app_bytes / int(source["measured_app_bytes"]) if int(source["measured_app_bytes"]) else 0.0),
                               "packet_loss_ratio": max(0, offered - received) / offered if offered else 0.0,
                               "latency": latencies.get(flow_id, {}).get(node)}
        category = ("high-hard" if flow_id in HARD_CRITICAL_OVERRIDES
                    else flow["criticality"])
        for receiver in receivers.values():
            if category.endswith("hard"):
                receiver["viable"] = receiver["deadline_miss_ratio_including_loss"] == 0
            elif "soft" in category:
                receiver["viable"] = receiver["deadline_miss_ratio_including_loss"] <= 0.01
            elif category == "low":
                receiver["viable"] = (receiver["goodput_payload_ratio"] >= 0.95 and
                                      receiver["packet_loss_ratio"] <= 0.01)
            else:
                receiver["viable"] = None
        metrics[flow_id] = {"criticality": category, "receivers": receivers}
    return metrics


def reassess_existing_report(report):
    """Apply the current P1 acceptance categories to a completed cell report."""
    qos = report["qos"]
    for flow_id, metric in qos.items():
        if flow_id in HARD_CRITICAL_OVERRIDES:
            metric["criticality"] = "high-hard"
        category = metric["criticality"]
        for receiver in metric["receivers"].values():
            miss_ratio = receiver["deadline_miss_ratio_including_loss"]
            if category.endswith("hard"):
                receiver["viable"] = miss_ratio == 0
            elif "soft" in category:
                receiver["viable"] = miss_ratio <= 0.01
            elif category == "low":
                receiver["viable"] = (receiver["goodput_payload_ratio"] >= 0.95 and
                                      receiver["packet_loss_ratio"] <= 0.01)
    report["analysis_overrides"] = {
        "high-hard": sorted(HARD_CRITICAL_OVERRIDES),
        "source_catalog_unchanged": True,
    }
    report["viable"] = (
        not report["nonstable_queues"] and
        all(value["viable"] is not False
            for metric in qos.values()
            for value in metric["receivers"].values())
    )
    return report


def run_cell(config, output, env, inet):
    command = [str(ROOT / "src/zonal-ivn-tsn"), "-u", "Cmdenv",
               "-n", f".:{ROOT / 'src'}:{ROOT / 'tests'}:{inet / 'src'}",
               "-f", "omnetpp.ini", "-c", config, "--cmdenv-express-mode=true",
               "--cmdenv-event-banners=false",
               "--**.app[*].latency.result-recording-modes=+vector",
               "--**.queueLength.result-recording-modes=+vector",
               "--**.queueBitLength.result-recording-modes=+vector",
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
    require(int(summary["run"]["load"]) == expected_load, f"{config}: wrong effective offered load")
    require(summary["run"]["aggregation"] == expected_aggregation, f"{config}: wrong aggregation")
    require(float(summary["run"]["warmup"]) == WARMUP and
            float(summary["run"]["measurement"]) == MEASUREMENT, f"{config}: wrong duration")
    vec_path = next(output.glob(f"{config}-#*.vec"), None)
    sca_path = output / f"{config}-#0.sca"
    require(vec_path is not None and sca_path.exists(), f"{config}: missing OMNeT++ result files")
    params = parse_sca(sca_path)
    interfaces, queues = verify_configuration(params, config, run_dir)
    for interface in interfaces:
        for tc in range(8):
            queue = interface + f".queue[{tc}]"
            require(params.get((queue, "queueingTime:histogram")) == "recorded",
                    f"{config}: missing queueing-time histogram at {queue}")
        phy = interface.removesuffix(".macLayer.queue") + ".phyLayer.transmitter"
        require(params.get((phy, "utilization:histogram")) == "recorded",
                f"{config}: missing utilization histogram at {phy}")
    latencies, stability = read_vectors(vec_path, params, summary, len(queues))
    qos = assess_qos(summary, latencies)
    nonstable = [q for q in stability if q["sustained_growth"]]
    for flow, metric in qos.items():
        for receiver, values in metric["receivers"].items():
            if values["viable"] is False:
                break
    cell_viable = (not nonstable and all(v["viable"] is not False
                                        for m in qos.values() for v in m["receivers"].values()))
    report = {"config": config, "load": expected_load, "aggregation": expected_aggregation,
              "offered_packets": summary["source_packets"], "recorded_drops": summary["drops"],
              "egress_interfaces_checked": len(interfaces), "class_queues_checked": len(queues),
              "qos": qos, "queue_stability": stability, "nonstable_queues": nonstable,
              "viable": cell_viable}
    (run_dir / "c0-acceptance.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"PASS {config}: {report['offered_packets']} packets, {report['recorded_drops']} drops, "
          f"{len(interfaces)} egresses/{len(queues)} class queues checked; "
          f"cell {'VIABLE' if cell_viable else 'NONVIABLE'}", flush=True)
    return report, run_dir


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inet-root", default=os.environ.get("INET_ROOT"))
    parser.add_argument("--omnetpp-root", default=os.environ.get("OMNETPP_ROOT"))
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--reassess-existing", action="store_true",
                        help="reapply P1 acceptance categories to completed result reports without rerunning simulations")
    args = parser.parse_args()
    output = SIM / "results/C0/p1-validation"
    configs = [f"Validate_C0_L{level}_A{aggregation}"
               for level in range(4) for aggregation in range(2)]
    if args.reassess_existing:
        reports = []
        for config in configs:
            run_dir = output / f"{config}-0"
            report_path = run_dir / "c0-acceptance.json"
            require(report_path.exists(), f"{config}: missing completed report {report_path}")
            report = reassess_existing_report(json.loads(report_path.read_text()))
            report_path.write_text(json.dumps(report, indent=2) + "\n")
            print(f"REASSESSED {config}: {'VIABLE' if report['viable'] else 'NONVIABLE'}",
                  flush=True)
            reports.append((report, run_dir))
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
        print(f"C0 assessment complete under overrides {sorted(HARD_CRITICAL_OVERRIDES)}: "
              f"{viable}/8 cells meet P1 viability thresholds. Evidence: {output}")
        return
    if not args.inet_root:
        parser.error("Set INET_ROOT or pass --inet-root")
    if args.jobs < 1:
        parser.error("--jobs must be positive")
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
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        reports = list(pool.map(lambda c: run_cell(c, output, env, inet), configs))

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
