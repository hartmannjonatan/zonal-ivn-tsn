#!/usr/bin/env python3
"""Run or reassess the P1 C2 nominal-CBS matrix and compare it with C0/C1."""
import csv
import argparse
import json
import math
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SIM = ROOT / "simulations"
OUTPUT = SIM / "results/C2/p1-validation-64KiB-final"
sys.path.insert(0, str(ROOT / "scripts/run"))
sys.path.insert(0, str(ROOT / "scripts/catalog"))
from validate_c0 import parse_sca, require, run_cell
from generate_cbs import nominal_reservations, read_flows

CONFIGS = [f"Validate_C2_L{load}_A{agg}" for load in range(4) for agg in range(2)]


def critical_summary(report):
    p99, misses, image_p99 = [], [], []
    for flow in report["qos"].values():
        if flow["criticality"] == "low":
            continue
        for rx in flow["receivers"].values():
            latency = rx.get("latency") or {}
            if latency.get("p99_s") is not None:
                p99.append(latency["p99_s"])
            image = rx.get("image_completion")
            misses.append(image["deadline_miss_ratio_including_missing_images"] if image else
                          rx["deadline_miss_ratio_including_loss"])
            if image and image.get("p99_s") is not None:
                image_p99.append(image["p99_s"])
    receivers = [rx for flow in report["qos"].values() for rx in flow["receivers"].values()]
    return {"max_critical_p99_s": max(p99, default=0),
            "max_camera_image_completion_p99_s": max(image_p99, default=0),
            "max_critical_deadline_miss_ratio": max(misses, default=0),
            "max_packet_loss_ratio": max((rx["packet_loss_ratio"] for rx in receivers), default=0),
            "min_goodput_payload_ratio": min((rx["goodput_payload_ratio"] for rx in receivers), default=0)}


def queue_summary(report):
    camera, bottleneck = [], []
    for queue in report.get("queue_stability", []):
        name = queue["queue"]
        row = {"queue": name, "tc": queue["tc"],
               "max_occupancy_bits": queue.get("max_occupancy_bits"),
               "capacity_bits": queue["capacity_bits"],
               "sustained_growth": queue["sustained_growth"]}
        if ".CAM" in name and ".eth[0]." in name:
            camera.append(row)
        elif (".CSW.eth[" in name or ".ZCPU.eth[0]." in name or
              (".ZSW.eth[" in name and any(f".eth[{i}]." in name for i in (0, 1)))):
            bottleneck.append(row)
    return {"peak_occupancy_bits": {
                "camera_talkers": max((q["max_occupancy_bits"] or 0 for q in camera), default=0),
                "G1_G4": max((q["max_occupancy_bits"] or 0 for q in bottleneck), default=0)},
            "max_queueing_time_s": max((q.get("max_s") or 0 for q in report.get("queueing_time", [])), default=0)}


def expected_profile(load):
    return {(f"ZonalIVN.{egress}.macLayer.queue.transmissionSelectionAlgorithm[{tc}]", entry["bps"])
            for (entry_load, egress, tc), entry in nominal_reservations(read_flows()).items()
            if entry_load == load}


def check_cbs_configuration(config, report, run_dir):
    load = report["load"]
    params = parse_sca(OUTPUT / f"{config}-#0.sca")
    expected = expected_profile(load)
    credit_trace_available = has_credit_vectors(config)
    observed_modules = {
        module for (module, name), value in params.items()
        if name == "typename" and "Ieee8021qCreditBasedShaper" in str(value)
    }
    expected_modules = {module for module, _ in expected}
    require(observed_modules == expected_modules,
            f"{config}: CBS modules differ from generated nominal profile; "
            f"missing={sorted(expected_modules-observed_modules)}, extra={sorted(observed_modules-expected_modules)}")
    reservation_rows = []
    for module, expected_bps in sorted(expected):
        typename = params.get((module, "typename"), "")
        require("Ieee8021qCreditBasedShaper" in typename,
                f"{config}: {module} is not an INET Ieee8021qCreditBasedShaper")
        raw = str(params.get((module, "idleSlope"), ""))
        match = re.fullmatch(r"\s*([0-9.eE+-]+)\s*(?:bps)?\s*", raw)
        require(match is not None, f"{config}: cannot parse {module}.idleSlope={raw!r}")
        actual_bps = round(float(match.group(1)))
        require(actual_bps == expected_bps,
                f"{config}: {module}.idleSlope={actual_bps}, P1 nominal is {expected_bps} bit/s")
        credit_stats = {}
        for field in ("min", "max", "timeavg"):
            raw_credit = params.get((module, f"numCredits:{field}"))
            try:
                credit_value = float(raw_credit) if raw_credit is not None else None
            except (TypeError, ValueError):
                credit_value = None
            if credit_trace_available:
                require(credit_value is not None and math.isfinite(credit_value),
                        f"{config}: invalid CBS credit {field} summary for {module}: {raw_credit!r}")
            credit_stats[field] = credit_value
        reservation_rows.append({"algorithm": module, "idle_slope_bps": expected_bps,
                                 "idle_slope_mbps": expected_bps / 1e6,
                                 "credit_min": credit_stats["min"],
                                 "credit_max": credit_stats["max"],
                                 "credit_timeavg": credit_stats["timeavg"]})
    return {"configured_algorithms": len(expected),
            "active_classes": [4, 6],
            "idle_slope_source": "sum of permanent per-flow P1 R_wire routed through this egress; scalable flows multiplied by L factor",
            "transient_flows_excluded_from_reservations": ["F21", "F22"],
            "credit_trace_available": credit_trace_available,
            "credit_trace_role": "explanatory per P1 §5.4; not a primary viability gate",
            "reservations": reservation_rows}


def has_credit_vectors(config):
    vec_path = next(OUTPUT.glob(f"{config}-#*.vec"), None)
    if vec_path is None:
        return False
    load = int(config.split("_L", 1)[1][0])
    expected_modules = {module for module, _ in expected_profile(load)}
    observed_modules = set()
    with vec_path.open(errors="replace") as stream:
        for line in stream:
            if line.startswith("vector "):
                parts = line.split()
                if len(parts) >= 4 and parts[3] == "numCredits:vector":
                    observed_modules.add(parts[2])
            if line and line[0].isdigit():
                break
    return observed_modules == expected_modules


def same_transient_events(run_dir, reference_dir, context):
    def rows(path):
        with (path / "events.csv").open(newline="") as stream:
            return [tuple(row[key] for key in ("flow", "block", "signature", "duration", "volume_bytes"))
                    for row in csv.DictReader(stream)]
    require(rows(run_dir) == rows(reference_dir),
            f"{context}: F21/F22 event signatures differ from paired seed-41 reference")


def compare_cells(c0, c1, c2):
    combined = {}
    for config in CONFIGS:
        base_name = config.replace("Validate_C2_", "Validate_C0_")
        left_name = config.replace("Validate_C2_", "Validate_C1_")
        reports = {"C0": c0[base_name], "C1": c1[left_name], "C2": c2[config]}
        flow_rows = {}
        for flow, metric in reports["C2"]["qos"].items():
            receivers = {}
            for receiver, c2_values in metric["receivers"].items():
                values = {label: report["qos"][flow]["receivers"][receiver]
                          for label, report in reports.items()}
                receivers[receiver] = {
                    "useful_throughput_mbps": {label: value["useful_throughput_mbps"] for label, value in values.items()},
                    "goodput_payload_ratio": {label: value["goodput_payload_ratio"] for label, value in values.items()},
                    "packet_loss_ratio": {label: value["packet_loss_ratio"] for label, value in values.items()},
                    "deadline_miss_ratio_including_loss": {label: value["deadline_miss_ratio_including_loss"] for label, value in values.items()},
                    "packet_latency": {label: value["latency"] for label, value in values.items()},
                    "image_completion": {label: value["image_completion"] for label, value in values.items()},
                }
            flow_rows[flow] = {"criticality": metric["criticality"], "receivers": receivers}
        aggregate = {}
        for label, report in reports.items():
            critical = critical_summary(report)
            queues = queue_summary(report)
            aggregate[label] = {
                "viable": report["viable"], "recorded_drops": report["recorded_drops"],
                "critical_packet_p99_max_s": critical["max_critical_p99_s"],
                "critical_camera_image_completion_p99_max_s": critical["max_camera_image_completion_p99_s"],
                "critical_deadline_miss_ratio_max": critical["max_critical_deadline_miss_ratio"],
                "packet_loss_ratio_max": critical["max_packet_loss_ratio"],
                "goodput_payload_ratio_min": critical["min_goodput_payload_ratio"],
                "camera_queue_occupancy_max_bits": queues["peak_occupancy_bits"]["camera_talkers"],
                "G1_G4_queue_occupancy_max_bits": queues["peak_occupancy_bits"]["G1_G4"],
                "queueing_time_max_s": queues["max_queueing_time_s"],
                "packets_pending_at_simulation_end": report.get("pending_packet_count_at_simulation_end", 0),
                "nonstable_queues": len(report["nonstable_queues"]),
            }
        combined[config] = {
            "C0_viable": reports["C0"]["viable"], "C1_viable": reports["C1"]["viable"],
            "C2_viable": reports["C2"]["viable"],
            "C0_recorded_drops": reports["C0"]["recorded_drops"],
            "C1_recorded_drops": reports["C1"]["recorded_drops"],
            "C2_recorded_drops": reports["C2"]["recorded_drops"],
            "camera_frame_generation": {
                flow: {"C0_generated_frames": reports["C0"]["qos"][flow]["receivers"][next(iter(reports["C0"]["qos"][flow]["receivers"]))]["offered_packets"],
                       "C2_generated_frames": reports["C2"]["qos"][flow]["receivers"][next(iter(reports["C2"]["qos"][flow]["receivers"]))]["offered_packets"],
                       "same_generation": reports["C0"]["qos"][flow]["receivers"][next(iter(reports["C0"]["qos"][flow]["receivers"]))]["offered_packets"] == reports["C2"]["qos"][flow]["receivers"][next(iter(reports["C2"]["qos"][flow]["receivers"]))]["offered_packets"]}
                for flow in ("F02", "F03", "F04", "F05")},
            "flows": flow_rows, "aggregate_metrics": aggregate,
            "C2_nominal_reservations": reports["C2"]["cbs_nominal"]}
    return combined


def write_comparison(cells):
    document = {
        "reference": "P1 atualizado, §§3–5; catálogo canônico R_wire; seed 41",
        "matrix": "L0-L3 × A0/A1; 1 s warm-up + 30 s measurement + 50 ms drain",
        "buffer_profile": {"CAM1_CAM4_per_class_bytes": 65536,
                           "G1_G4_per_class_bytes": 131072,
                           "other_egresses_per_class_bytes": 32768},
        "C2_nominal_CBS": {
            "custom_TCs": {"TC6": ["F01", "F06", "F07"],
                            "TC4": ["F02", "F03", "F04", "F05", "F11", "F12", "F13", "F14", "F21", "F22"]},
            "standard_SR_contracts_claimed": False,
            "reservation_rule": "per egress/class sum of permanent wire rates routed through that port; scalable rates use the selected L factor; F21/F22 are excluded",
            "P1_75_percent_cap_applied": False,
        },
        "cells": cells,
        "viability_counts": {
            label: sum(bool(cell[f"{label}_viable"]) for cell in cells.values())
            for label in ("C0", "C1", "C2")},
        "C2_credit_trace_cells": sum(
            bool(cell["C2_nominal_reservations"]["credit_trace_available"])
            for cell in cells.values()),
        "P1_hypothesis_note": "C2−C0 and C2−C1 are descriptive seed-41 contrasts. H3 requires a subsequent C3−C2 comparison and is not tested here.",
    }
    (OUTPUT / "C0_C1_C2_comparison.json").write_text(json.dumps(document, indent=2) + "\n")
    lines = [
        "# C0/C1/C2 — comparação C2 nominal CBS", "",
        "Matriz seed 41, pareada entre C0, C1 e C2, referente aos resultados históricos sob a configuração indicada no JSON. C2 mantém os bursts originais de câmera e adiciona CBS nominal às classes customizadas TC6/TC4 nos egressos roteados.", "",
        "As taxas idleSlope por egress são a soma das taxas wire permanentes do catálogo roteadas por aquela porta, escaladas pelo nível L quando o fluxo é escalável. F21/F22 usam TC4 enquanto ativos, mas não entram na reserva. TC6/TC4 são classes CBS próprias do benchmark; não se afirma reprodução de SR-A/SR-B. A nova campanha oficial tem runner e comparações isolados.", "",
        "## Resultados por célula", "",
        "| Célula | Viabilidade C0/C1/C2 | Drops C0/C1/C2 | Pendentes fim C2 | p99 crítico pacote C0/C1/C2 (ms) | p99 conclusão imagem C0/C1/C2 (ms) | Miss crítico máx. C0/C1/C2 (%) | Perda máx. (%) | Goodput mín. (%) | Filas não estáveis C2 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for config, cell in cells.items():
        agg = cell["aggregate_metrics"]
        vals = [agg[name] for name in ("C0", "C1", "C2")]
        viable = "/".join("sim" if value["viable"] else "não" for value in vals)
        drops = "/".join(str(value["recorded_drops"]) for value in vals)
        pending = str(vals[2]["packets_pending_at_simulation_end"])
        p99 = "/".join(f"{value['critical_packet_p99_max_s']*1e3:.4f}" for value in vals)
        image = "/".join(f"{value['critical_camera_image_completion_p99_max_s']*1e3:.4f}" for value in vals)
        misses = "/".join(f"{value['critical_deadline_miss_ratio_max']*100:.3f}" for value in vals)
        loss = "/".join(f"{value['packet_loss_ratio_max']*100:.3f}" for value in vals)
        goodput = "/".join(f"{value['goodput_payload_ratio_min']*100:.2f}" for value in vals)
        lines.append(f"| {config.replace('Validate_C2_', '')} | {viable} | {drops} | {pending} | {p99} | {image} | {misses} | {loss} | {goodput} | {agg['C2']['nonstable_queues']} |")
    viab = document["viability_counts"]
    lines += ["", "## Leitura", "",
              f"Viabilidade observada: C0 {viab['C0']}/8, C1 {viab['C1']}/8, C2 {viab['C2']}/8. O JSON traz as métricas detalhadas por fluxo/receptor, a configuração CBS por egress e indica em cada célula se a série explicativa de crédito foi gravada.", "",
              f"Séries de crédito CBS disponíveis nas células C2: {document['C2_credit_trace_cells']}/8. Essa coleta é explicativa no P1; um smoke independente confirmou a instrumentação do vetor e dos resumos.", "",
              "A comparação C2−C0 mostra o efeito de acrescentar a reserva nominal CBS ao baseline SP; C2−C1 contrasta CBS nominal com pre-shaping. C2 conserva os bursts originais e a mesma geração de 30 frames, portanto a fila de câmera pode voltar a enfileirar o burst enquanto CBS limita a elegibilidade de transmissão nas classes SR.", "",
              "A hipótese H3 compara C3 calibrado contra C2 nominal. Ela permanece sem teste até C3 ser implementado/calibrado; os resultados desta única seed são diagnósticos de engenharia, não uma confirmação estatística.", "",
              "As métricas por imagem medem disponibilidade até a recepção do último dos 30 frames; a latência por pacote mede liberação individual até recepção. Ambas são reportadas e não intercambiadas.", ""]
    (OUTPUT / "C0_C1_C2_analysis.md").write_text("\n".join(lines))


def main():
    global OUTPUT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--inet-root", default=os.environ.get("INET_ROOT"))
    parser.add_argument("--omnetpp-root", default=os.environ.get("OMNETPP_ROOT"))
    parser.add_argument("--resume", action="store_true", help="reuse completed C2 raw results and acceptance reports")
    parser.add_argument("--reassess-existing", action="store_true", help="recompute acceptance from completed C2 raw results")
    parser.add_argument("--configs", nargs="+", choices=CONFIGS,
                        help="run/reassess selected independent cells; skip matrix-level comparison output")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT,
                        help="isolated output directory (defaults to the clean final C2 result tree)")
    args = parser.parse_args()
    OUTPUT = args.output_dir if args.output_dir.is_absolute() else ROOT / args.output_dir
    OUTPUT = OUTPUT.resolve()
    require(args.jobs > 0, "--jobs must be positive")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, str(ROOT / "scripts/catalog/generate.py"), "--check"], check=True)
    subprocess.run([sys.executable, str(ROOT / "scripts/catalog/generate_cbs.py"), "--check"], check=True)
    c0_path = SIM / "results/C0/p1-validation-64KiB/C0_acceptance.json"
    c1_path = SIM / "results/C1/p1-validation-64KiB/C1_acceptance.json"
    require(c0_path.is_file() and c1_path.is_file(), "Validated C0 and C1 acceptance JSONs are required for comparison")
    c0, c1 = json.loads(c0_path.read_text()), json.loads(c1_path.read_text())

    inet = Path(args.inet_root).resolve() if args.inet_root else None
    omnetpp = Path(args.omnetpp_root).resolve() if args.omnetpp_root else None
    env = os.environ.copy()
    if not args.reassess_existing and inet is None:
        parser.error("Set INET_ROOT or use --reassess-existing")
    if not args.reassess_existing:
        if omnetpp is None:
            opp_run = __import__("shutil").which("opp_run")
            if opp_run:
                omnetpp = Path(opp_run).resolve().parent.parent
        if omnetpp is None:
            parser.error("Load OMNeT++ or set OMNETPP_ROOT")
        env["LD_LIBRARY_PATH"] = ":".join(str(path) for path in
            [omnetpp / "lib", inet / "src", Path(env["LD_LIBRARY_PATH"]) if env.get("LD_LIBRARY_PATH") else Path("")]
            if str(path) not in ("", "."))

    def assess(config):
        run_dir = OUTPUT / f"{config}-0"
        acceptance = run_dir / "c2-acceptance.json"
        complete = (run_dir / "run.csv").is_file() and (OUTPUT / f"{config}-#0.sca").is_file() and \
                   next(OUTPUT.glob(f"{config}-#*.vec"), None) is not None and \
                   "End." in (OUTPUT / f"{config}.log").read_text(errors="replace")
        if args.resume and complete and acceptance.is_file():
            report = json.loads(acceptance.read_text())
        else:
            if args.reassess_existing:
                require(complete, f"{config}: raw result is incomplete")
            execute = not (complete and (args.resume or args.reassess_existing))
            report, run_dir = run_cell(config, OUTPUT, env, inet, execute=execute,
                                       result_dir_override=str(OUTPUT.relative_to(SIM)),
                                       extra_args=("--**.numCredits.result-recording-modes=vector,max,min,timeavg",))
        cbs = check_cbs_configuration(config, report, run_dir)
        report["cbs_nominal"] = cbs
        (run_dir / "c2-acceptance.json").write_text(json.dumps(report, indent=2) + "\n")
        ref0 = SIM / f"results/C0/p1-validation-64KiB/{config.replace('Validate_C2_', 'Validate_C0_')}-0"
        ref1 = SIM / f"results/C1/p1-validation-64KiB/{config.replace('Validate_C2_', 'Validate_C1_')}-0"
        same_transient_events(run_dir, ref0, f"{config}/C0")
        same_transient_events(run_dir, ref1, f"{config}/C1")
        return report

    selected_configs = args.configs or CONFIGS
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        reports = list(pool.map(assess, selected_configs))
    result = {report["config"]: report for report in reports}
    if set(selected_configs) != set(CONFIGS):
        print(f"C2 selected-cell validation complete: {len(result)} cells in {OUTPUT}")
        return
    (OUTPUT / "C2_acceptance.json").write_text(json.dumps(result, indent=2) + "\n")
    cells = compare_cells(c0, c1, result)
    write_comparison(cells)
    count = sum(bool(report["viable"]) for report in reports)
    print(f"C2 nominal CBS validation complete: {count}/8 viable. Results: {OUTPUT}")


if __name__ == "__main__":
    main()
