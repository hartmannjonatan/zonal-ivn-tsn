#!/usr/bin/env python3
"""Calibrate C3 at L2/A1, freeze ratios, screen and validate admissible cells."""
import argparse
import csv
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SIM = ROOT / "simulations"
OUTPUT = SIM / "results/C3/p1-validation-64KiB"
CALIBRATION = SIM / "zonal/traffic/cbs_calibration.json"
sys.path.insert(0, str(ROOT / "scripts/run"))
sys.path.insert(0, str(ROOT / "scripts/catalog"))
import validate_c0 as base
from validate_c2 import critical_summary, queue_summary
from generate_cbs import capacity_bps, nominal_reservations, read_flows, route
from generate_c3 import CAP, render

BASELINE_PATHS = {
    "C0": SIM / "results/C0/p1-validation-64KiB/C0_acceptance.json",
    "C1": SIM / "results/C1/p1-validation-64KiB/C1_acceptance.json",
    "C2": SIM / "results/C2/p1-validation-64KiB-final/C2_acceptance.json",
}
MATRIX = [f"Validate_C3_L{load}_A{agg}" for load in range(3) for agg in range(2)]
RAW_SUFFIXES = {".vec", ".vci", ".sca", ".csv", ".log", ".pcap"}
MIN_FREE_BYTES = 20 * 1024**3
CAMPAIGN_SEEDS = set(range(1001, 1031))


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def ratio_key(egress, tc):
    return f"{egress}/TC{tc}"


def rates_at_load(ratio_data, load):
    nominal = nominal_reservations(read_flows())
    overrides = ratio_data["ratios"]
    return {(egress, tc): round(entry["bps"] * float(overrides.get(ratio_key(egress, tc), 1.0)))
            for (entry_load, egress, tc), entry in nominal.items() if entry_load == load}


def cap_screen(ratio_data, loads=range(3)):
    profiles = []
    for load in loads:
        rates = rates_at_load(ratio_data, load)
        total = {}
        for (egress, tc), bps in rates.items():
            total[egress] = total.get(egress, 0) + bps
        violations = [(egress, bps, capacity_bps(egress)) for egress, bps in total.items()
                      if bps > CAP * capacity_bps(egress)]
        profiles.append((load, total, violations))
    return profiles


def screen_candidate(ratio_data):
    profiles = cap_screen(ratio_data)
    return not any(violations for _, _, violations in profiles), profiles


def save_ratio_data(data):
    CALIBRATION.write_text(json.dumps(data, indent=2) + "\n")
    ini, csv_data, screen = render(CALIBRATION)
    from generate_c3 import CSV_OUT, INI_OUT_C3, SCREEN_OUT
    INI_OUT_C3.write_text(ini)
    CSV_OUT.write_text(csv_data)
    SCREEN_OUT.write_text(json.dumps(screen, indent=2) + "\n")


def cleanup_raw_tree(path):
    removed = 0
    if not path.exists():
        return removed
    for p in path.rglob("*"):
        if p.is_file() and p.suffix.lower() in RAW_SUFFIXES:
            p.unlink()
            removed += 1
    for p in sorted(path.rglob("*"), key=lambda x: len(x.parts), reverse=True):
        if p.is_dir():
            try:
                p.rmdir()
            except OSError:
                pass
    return removed


def require_space(where):
    free = shutil.disk_usage(SIM).free
    require(free >= MIN_FREE_BYTES,
            f"Stopping before {where}: only {free / 1024**3:.2f} GiB free; need 20 GiB for one L2 cell")
    return free


def event_signature(run_dir):
    digest = hashlib.sha256()
    count = 0
    with (run_dir / "events.csv").open(newline="") as f:
        for row in csv.DictReader(f):
            fields = (row[k] for k in ("flow", "block", "signature", "duration", "volume_bytes"))
            digest.update(("\x1f".join(fields) + "\n").encode())
            count += 1
    return {"event_rows": count, "sha256": digest.hexdigest()}


def validate_c3_parameters(config, report, output, expected_ratio_data):
    params = base.parse_sca(output / f"{config}-#0.sca")
    profile = rates_at_load(expected_ratio_data, report["load"])
    expected_modules = {f"ZonalIVN.{egress}.macLayer.queue.transmissionSelectionAlgorithm[{tc}]"
                        for egress, tc in profile}
    observed_modules = {module for (module, name), value in params.items()
                        if name == "typename" and "Ieee8021qCreditBasedShaper" in str(value)}
    require(observed_modules == expected_modules,
            f"{config}: calibrated CBS modules mismatch; missing={sorted(expected_modules-observed_modules)}, extra={sorted(observed_modules-expected_modules)}")
    seen_rates = {}
    by_port = {}
    for (egress, tc), expected_bps in profile.items():
        module = f"ZonalIVN.{egress}.macLayer.queue.transmissionSelectionAlgorithm[{tc}]"
        actual = params.get((module, "idleSlope"))
        require(actual is not None, f"{config}: missing {module}.idleSlope")
        actual_bps = round(float(str(actual).removesuffix("bps")))
        require(actual_bps == expected_bps,
                f"{config}: {module} resolved to {actual_bps}, expected {expected_bps}")
        seen_rates[module] = actual_bps
        by_port[egress] = by_port.get(egress, 0) + actual_bps
    for egress, reservation in by_port.items():
        require(reservation <= CAP * capacity_bps(egress),
                f"{config}: {egress} total reservation {reservation} exceeds 75% cap")
    report["cbs_calibrated"] = {
        "module_count": len(seen_rates), "idle_slope_by_module_bps": seen_rates,
        "total_reservation_by_egress_bps": by_port,
        "cap_fraction": CAP, "within_cap": True,
        "frozen_ratios": expected_ratio_data["ratios"],
    }


def run_trial(label, ratio_data, env, inet):
    free = require_space(label)
    trial_dir = SIM / "results/C3/calibration" / label
    if trial_dir.exists():
        shutil.rmtree(trial_dir)
    trial_dir.mkdir(parents=True, exist_ok=True)
    config = "Calibrate_C3_L2_A1"
    try:
        save_ratio_data(ratio_data)
        ok, profiles = screen_candidate(ratio_data)
        require(ok, f"{label}: calibration candidate exceeds the 75% cap")
        report, run_dir = base.run_cell(
            config, trial_dir, env=env, inet=inet, execute=True,
            result_dir_override=str(trial_dir.relative_to(SIM)),
            extra_args=("--**.numCredits.result-recording-modes=vector,max,min,timeavg",))
        validate_c3_parameters(config, report, trial_dir, ratio_data)
        sig = event_signature(run_dir)
        report["transient_event_signature"] = sig
        report["space_before_run_free_bytes"] = free
        report["space_after_raw_cleanup_free_bytes"] = None
        report["calibration_trial"] = label
        (run_dir / "c3-acceptance.json").write_text(json.dumps(report, indent=2) + "\n")
        removed = cleanup_raw_tree(trial_dir)
        report["temporary_raw_files_removed"] = removed
        report["space_after_raw_cleanup_free_bytes"] = shutil.disk_usage(SIM).free
        (run_dir / "c3-acceptance.json").write_text(json.dumps(report, indent=2) + "\n")
        return report
    except BaseException:
        # A failed, incomplete, or misconfigured candidate is not retained.
        shutil.rmtree(trial_dir, ignore_errors=True)
        raise


def load_c2_cell(config):
    path = SIM / "results/C2/p1-validation-64KiB-final" / f"{config}-0/c2-acceptance.json"
    require(path.is_file(), f"Missing preserved C2 summary {path}")
    return json.loads(path.read_text())


def read_profile_targets(data):
    meta = data["calibration"]
    return [key for key in meta["affected_egress_classes"]]


def set_ratio_for_bps(data, key, bps):
    egress, tc = key.rsplit("/TC", 1)
    nominal = nominal_reservations(read_flows())[2, egress, int(tc)]["bps"]
    data["ratios"][key] = round(bps / nominal, 9)


def target_bps(data, key, load=2):
    egress, tc = key.rsplit("/TC", 1)
    return round(nominal_reservations(read_flows())[load, egress, int(tc)]["bps"] * data["ratios"][key])


def calibrate(env, inet, output):
    data = json.loads(CALIBRATION.read_text())
    meta = data["calibration"]
    require(meta["load"] == "L2" and meta["aggregation"] == "A1",
            "P1 C3 calibration must remain at L2/A1")
    require(meta["seed"] not in CAMPAIGN_SEEDS,
            "Calibration seed must be outside the final campaign set")
    targets = read_profile_targets(data)
    c2 = load_c2_cell("Validate_C2_L2_A1")
    history = [{"trial": "C2_nominal_baseline", "viable": c2["viable"],
                "recorded_drops": c2["recorded_drops"],
                "failed_flows": failing_flows(c2),
                "ratios": {key: 1.0 for key in targets},
                "note": "Existing seed-41 C2 L2/A1 summary; no raw data or simulation recreated."}]
    # Resume from complete prior coarse trials after a calibration target is
    # expanded. Partial trial trees are removed by run_trial and are ignored.
    prior_trials = []
    for trial_dir in sorted((SIM / "results/C3/calibration").glob("coarse-*")):
        report_path = trial_dir / "Calibrate_C3_L2_A1-0/c3-acceptance.json"
        if not report_path.is_file():
            continue
        prior_report = json.loads(report_path.read_text())
        prior_label = prior_report.get("calibration_trial", trial_dir.name)
        suffix = prior_label.split("-", 2)[-1]
        target = next((key for key in targets
                       if key.rsplit("/TC", 1)[0].replace(".", "_").replace("[", "").replace("]", "")
                       + "-TC" + key.rsplit("/TC", 1)[1] == suffix), None)
        prior_trials.append((trial_dir.name, prior_report, target))
    current = None
    frozen_signature = None
    if prior_trials:
        for label, prior_report, target in prior_trials:
            history.append({"trial": label, "stage": "coarse", "target": target,
                            "viable": prior_report["viable"],
                            "recorded_drops": prior_report["recorded_drops"],
                            "failed_flows": failing_flows(prior_report),
                            "ratios": deepcopy(prior_report["cbs_calibrated"]["frozen_ratios"]),
                            "report_path": str(Path("results/C3/calibration") / label / f"{prior_report['config']}-0/c3-acceptance.json"),
                            "resumed_calibration": True})
        last_label, current, _ = prior_trials[-1]
        frozen_signature = current["transient_event_signature"]
        # A new target can be appended while preserving all already validated
        # calibrated ratios from the last complete candidate.
        data["ratios"].update(current["cbs_calibrated"]["frozen_ratios"])
        data["calibration"]["resumed_from_trial"] = last_label
    else:
        current = None
    coarse = float(meta["coarse_step_fraction_of_port_rate"])
    fine = float(meta["fine_step_fraction_of_port_rate"])
    existing_indices = [int(label.split("-", 2)[1]) for label, _, _ in prior_trials
                        if label.split("-", 2)[1].isdigit()]
    trial_index = max(existing_indices, default=-1) + 1

    # Coarse stage: one deterministic +10%-of-port step per affected egress/class
    # in the declared order, cycling until the P1 viability gates pass.
    while current is None or not current["viable"]:
        made_progress = False
        failing_ids = ({item.split("/", 1)[0] for item in failing_flows(current)}
                       if current is not None else {item.split("/", 1)[0] for item in history[0]["failed_flows"]})
        flow_targets = {}
        for flow in read_flows():
            tc = int(flow["traffic_class"])
            if tc not in (4, 6):
                continue
            egresses = set()
            for destination in flow["destinations"].split(";"):
                egresses.update(route(flow["source"], destination))
            flow_targets[flow["flow_id"]] = {ratio_key(egress, tc) for egress in egresses
                                                if (egress, tc) in rates_at_load(data, 2)}
        active_targets = [key for key in targets if any(key in flow_targets.get(fid, set())
                                                        for fid in failing_ids)]
        for key in active_targets:
            egress, tc = key.rsplit("/TC", 1)
            old_bps = target_bps(data, key)
            candidate = deepcopy(data)
            new_bps = old_bps + round(coarse * capacity_bps(egress))
            set_ratio_for_bps(candidate, key, new_bps)
            admissible, _ = screen_candidate(candidate)
            step_kind = "coarse"
            if not admissible:
                # Test the final deterministic step up to the exact 75% bound
                # before concluding that this egress is exhausted. The regular
                # coarse step is capped at 10% of link rate; this last increment
                # may be smaller because another full step would be inadmissible.
                port_limit = math.floor(CAP * capacity_bps(egress))
                other_reservations = sum(
                    bps for (port, traffic_class), bps in rates_at_load(data, 2).items()
                    if port == egress and (port, traffic_class) != (egress, int(tc)))
                cap_limited_bps = min(new_bps, port_limit - other_reservations)
                if cap_limited_bps <= old_bps:
                    history.append({"trial": f"cap-screen-{trial_index:03d}", "status": "rejected_before_run",
                                    "target": key, "candidate_idle_slope_bps": new_bps,
                                    "reason": "No positive deterministic increment remains below the 75% total port cap"})
                    continue
                new_bps = cap_limited_bps
                candidate = deepcopy(data)
                set_ratio_for_bps(candidate, key, new_bps)
                admissible, _ = screen_candidate(candidate)
                if not admissible:
                    history.append({"trial": f"cap-screen-{trial_index:03d}", "status": "rejected_before_run",
                                    "target": key, "candidate_idle_slope_bps": new_bps,
                                    "reason": "Exact 75% cap-limited profile failed the multi-load reservation screen"})
                    continue
                step_kind = "cap_limited_final_step"
            label = f"coarse-{trial_index:03d}-{egress.replace('.', '_').replace('[','').replace(']','')}-TC{tc}"
            print(f"C3 calibration {label}: {new_bps/1e6:.3f} Mb/s at {key}", flush=True)
            candidate_report = run_trial(label, candidate, env, inet)
            signature = candidate_report["transient_event_signature"]
            if frozen_signature is None:
                frozen_signature = signature
            if signature != frozen_signature:
                shutil.rmtree(SIM / "results/C3/calibration" / label, ignore_errors=True)
                raise RuntimeError(f"{label}: transient event signature changed across calibration runs; candidate discarded")
            history.append({"trial": label, "stage": "coarse", "target": key,
                            "idle_slope_bps": new_bps, "viable": candidate_report["viable"],
                            "increment_bps": new_bps - old_bps, "step_kind": step_kind,
                            "recorded_drops": candidate_report["recorded_drops"],
                            "failed_flows": failing_flows(candidate_report),
                            "ratios": deepcopy(candidate["ratios"]),
                            "report_path": str((Path("results/C3/calibration") / label / f"{candidate_report['config']}-0/c3-acceptance.json"))})
            current, data = candidate_report, candidate
            trial_index += 1
            made_progress = True
            if current["viable"]:
                break
        if current is not None and current["viable"]:
            break
        if not made_progress:
            checkpoint = {"status": "calibration_infeasible_under_75_percent_cap",
                          "calibration": meta, "history": history,
                          "last_candidate": current, "ratios": data["ratios"],
                          "last_active_targets": active_targets,
                          "last_failing_flows": sorted(failing_ids)}
            (output / "C3_calibration.json").write_text(json.dumps(checkpoint, indent=2) + "\n")
            raise RuntimeError("C3 did not meet viability at L2/A1 before all affected egresses reached the 75% cap")

    # Refinement: try reducing each affected reservation by 2% of link rate;
    # keep reductions only when every P1 viability gate still passes.
    accepted_steps = 0
    while True:
        accepted_this_pass = False
        for key in targets:
            egress, tc = key.rsplit("/TC", 1)
            while True:
                old_bps = target_bps(data, key)
                nominal_bps = nominal_reservations(read_flows())[2, egress, int(tc)]["bps"]
                new_bps = old_bps - round(fine * capacity_bps(egress))
                if new_bps < nominal_bps:
                    break
                candidate = deepcopy(data)
                set_ratio_for_bps(candidate, key, new_bps)
                admissible, _ = screen_candidate(candidate)
                if not admissible:
                    break
                label = f"fine-{trial_index:03d}-{egress.replace('.', '_').replace('[','').replace(']','')}-TC{tc}"
                print(f"C3 calibration {label}: test reduction to {new_bps/1e6:.3f} Mb/s at {key}", flush=True)
                candidate_report = run_trial(label, candidate, env, inet)
                if candidate_report["transient_event_signature"] != frozen_signature:
                    shutil.rmtree(SIM / "results/C3/calibration" / label, ignore_errors=True)
                    raise RuntimeError(f"{label}: transient event signature changed; trial discarded")
                history.append({"trial": label, "stage": "fine_reduction", "target": key,
                                "idle_slope_bps": new_bps, "viable": candidate_report["viable"],
                                "recorded_drops": candidate_report["recorded_drops"],
                                "failed_flows": failing_flows(candidate_report),
                                "ratios": deepcopy(candidate["ratios"]),
                                "report_path": str(Path("results/C3/calibration") / label / f"{candidate_report['config']}-0/c3-acceptance.json")})
                trial_index += 1
                if candidate_report["viable"]:
                    current, data = candidate_report, candidate
                    accepted_steps += 1
                    accepted_this_pass = True
                else:
                    break
        if not accepted_this_pass:
            break

    data["calibration"]["status"] = "complete_viability_reached_and_reduced"
    data["calibration"]["final_trial_label"] = current["calibration_trial"]
    data["calibration"]["frozen_at"] = "L2/A1, seed 41"
    data["calibration"]["coarse_step_bps_rule"] = "up to 10% of egress port rate, one affected egress/class at a time in deterministic path/failure order; test one final cap-limited increment when a full step would exceed the 75% total-port cap"
    data["calibration"]["fine_step_bps_rule"] = "2% of egress port rate, one affected egress/class at a time; keep only viable reductions"
    data["calibration"]["accepted_fine_reductions"] = accepted_steps
    data["calibration"]["final_viability"] = True
    data["calibration"]["transient_event_signature"] = frozen_signature
    data["calibration"]["history_file"] = "simulations/results/C3/calibration/C3_calibration.json"
    save_ratio_data(data)
    screen = json.loads((ROOT / "simulations/zonal/traffic/c3_reservation_screen.json").read_text())
    calibration_report = {
        "status": data["calibration"]["status"], "source": "P1 §§4.4, 5.3, 5.4",
        "calibration": data["calibration"], "frozen_ratios": data["ratios"],
        "reservation_screens": screen["screens"], "inadmissible_loads": screen["inadmissible_loads"],
        "baseline_C2_L2_A1": history[0], "final_calibration_report": current,
        "trial_history": history,
        "storage_policy": {"raw_files_deleted_after_each_valid_trial": True,
                           "partial_or_invalid_trial_trees_deleted": True,
                           "retained_per_trial": "validation.json and c3-acceptance.json summaries only"},
    }
    (SIM / "results/C3/calibration/C3_calibration.json").write_text(json.dumps(calibration_report, indent=2) + "\n")
    return data, current, frozen_signature, calibration_report


def failing_flows(report):
    failed = []
    for flow_id, flow in report.get("qos", {}).items():
        for receiver, metrics in flow.get("receivers", {}).items():
            if metrics.get("viable") is False:
                failed.append(f"{flow_id}/{receiver}")
    return failed


def source_cohort_counts(report):
    return {fid: {rx: int(metrics["offered_packets"])
                  for rx, metrics in flow["receivers"].items()}
            for fid, flow in report["qos"].items()}


def check_workload_pairing(c3_report, c2_report, context):
    c3, c2 = source_cohort_counts(c3_report), source_cohort_counts(c2_report)
    require(c3 == c2, f"{context}: C3 source-cohort counts differ from the paired C2 seed-41 workload")


def simulate_final_cell(config, env, inet, ratio_data, expected_signature):
    require_space(config)
    output = OUTPUT
    output.mkdir(parents=True, exist_ok=True)
    # Delete stale/partial artifacts for this cell before a clean execution.
    stale_run = output / f"{config}-0"
    if stale_run.exists():
        shutil.rmtree(stale_run)
    for p in output.glob(f"{config}-#*"):
        if p.is_file():
            p.unlink()
    log = output / f"{config}.log"
    if log.exists():
        log.unlink()
    try:
        report, run_dir = base.run_cell(
            config, output, env=env, inet=inet, execute=True,
            result_dir_override=str(output.relative_to(SIM)),
            extra_args=("--**.numCredits.result-recording-modes=vector,max,min,timeavg",))
        validate_c3_parameters(config, report, output, ratio_data)
        sig = event_signature(run_dir)
        require(sig == expected_signature,
                f"{config}: F21/F22 event signature differs from the calibrated L2/A1 run")
        c2_config = config.replace("Validate_C3_", "Validate_C2_")
        check_workload_pairing(report, load_c2_cell(c2_config), config)
        report["transient_event_signature"] = sig
        (run_dir / "c3-acceptance.json").write_text(json.dumps(report, indent=2) + "\n")
        cleanup_raw_tree(run_dir)
        for suffix in (".vec", ".vci", ".sca", ".log"):
            for p in output.glob(f"{config}-*{suffix}"):
                if p.is_file():
                    p.unlink()
        (run_dir / "c3-acceptance.json").write_text(json.dumps(report, indent=2) + "\n")
        return report
    except BaseException:
        shutil.rmtree(stale_run, ignore_errors=True)
        for p in output.glob(f"{config}-#*"):
            if p.is_file():
                p.unlink()
        if log.exists():
            log.unlink()
        raise


def summarize(report):
    critical = critical_summary(report)
    queues = queue_summary(report)
    receivers = [rx for flow in report["qos"].values() for rx in flow["receivers"].values()]
    return {"viable": report["viable"], "recorded_drops": report["recorded_drops"],
            "pending_packets_at_simulation_end": report["pending_packet_count_at_simulation_end"],
            "critical_packet_p99_max_s": critical["max_critical_p99_s"],
            "critical_packet_max_max_s": max((rx.get("latency", {}).get("max_s") or 0 for flow in report["qos"].values()
                                               if flow["criticality"] != "low" for rx in flow["receivers"].values()), default=0),
            "critical_camera_image_completion_p99_max_s": critical["max_camera_image_completion_p99_s"],
            "critical_deadline_miss_ratio_max": critical["max_critical_deadline_miss_ratio"],
            "packet_loss_ratio_max": critical["max_packet_loss_ratio"],
            "goodput_payload_ratio_min": critical["min_goodput_payload_ratio"],
            "camera_queue_occupancy_max_bits": queues["peak_occupancy_bits"]["camera_talkers"],
            "G1_G4_queue_occupancy_max_bits": queues["peak_occupancy_bits"]["G1_G4"],
            "queueing_time_max_s": queues["max_queueing_time_s"],
            "nonstable_queues": len(report["nonstable_queues"]),
            "camera_source_queue_drops": report["camera_source_queue_drops"],
            "measurement_drop_samples_available": report["measurement_drop_samples_available"]}


def comparison_document(c3_reports, screen, calibration):
    baselines = {label: json.loads(path.read_text()) for label, path in BASELINE_PATHS.items()}
    cells = {}
    for load in range(4):
        for agg in range(2):
            config = f"Validate_C3_L{load}_A{agg}"
            cell = {"reservation_status": "reservation_infeasible" if load == 3 else "simulated",
                    "treatments": {}, "flows": {}}
            baseline_reports = {}
            for label, result in baselines.items():
                base_config = config.replace("Validate_C3_", f"Validate_{label}_")
                baseline_reports[label] = result[base_config]
            if load < 3:
                c3 = c3_reports[config]
            else:
                c3 = None
            for label, report in [*baseline_reports.items(), *(([("C3", c3)] if c3 else []))]:
                cell["treatments"][label] = summarize(report)
            for fid, flow in baseline_reports["C2"]["qos"].items():
                cell["flows"][fid] = {"criticality": flow["criticality"], "receivers": {}}
                for rx in flow["receivers"]:
                    cell["flows"][fid]["receivers"][rx] = {}
                    for label, report in baseline_reports.items():
                        cell["flows"][fid]["receivers"][rx][label] = deepcopy(report["qos"][fid]["receivers"][rx])
                    if c3:
                        cell["flows"][fid]["receivers"][rx]["C3"] = deepcopy(c3["qos"][fid]["receivers"][rx])
            cells[config] = cell
    viability = {label: sum(bool(cell["treatments"].get(label, {}).get("viable"))
                            for cell in cells.values()) for label in ("C0", "C1", "C2", "C3")}
    document = {
        "source": "P1 updated; same seed-41 workload; C3 calibrated only at L2/A1",
        "matrix": "L0-L2 x A0/A1 simulated; L3 A0/A1 screened reservation-infeasible and not executed",
        "durations": {"warmup_s": 1, "measurement_s": 30, "drain_s": 0.05},
        "reservation_cap_fraction": CAP,
        "calibration": calibration,
        "reservation_screen": screen["screens"],
        "viability_counts": viability,
        "C3_simulated_cells": sum(c["reservation_status"] == "simulated" for c in cells.values()),
        "C3_reservation_infeasible_cells": [k for k, c in cells.items() if c["reservation_status"] == "reservation_infeasible"],
        "hypothesis_H3": "C3−C2 is reported descriptively at L2/A1 (calibration point) and other admissible cells; one seed does not establish statistical confirmation. L3 is a reservation boundary, not an execution failure.",
        "storage": "Raw .vec/.vci/.sca/.csv/.log files are removed after each complete, validated cell; invalid/partial runs are deleted.",
        "cells": cells,
    }
    return document


def write_markdown(document):
    lines = ["# C3 — validação CBS calibrado", "",
             "C3 preserva o catálogo, as liberações, as filas e o restante do tratamento C2. As razões calibradas foram obtidas uma única vez em L2/A1 com seed 41, após aumentar os egressos afetados em passos determinísticos de 10% da taxa do link até cumprir os gates P1 e reduzir em passos de 2% da taxa do link enquanto os gates continuaram aprovados. As razões finais foram congeladas antes da validação das outras células.", "",
             "O teto de 75% é aplicado à soma das reservas TC6+TC4 por egress. C3/L3/A0 e C3/L3/A1 são inadmissíveis porque CSW→HPC requer 862,656 Mb/s permanentes nominais, acima de 750 Mb/s; não foram simulados nem recortados. As demais células admissíveis foram simuladas com seed 41, 1 s de warm-up, 30 s de medição e 50 ms de drenagem.", "",
             "## Comparação por célula", "",
             "| Célula | C3 status | Viab. C0/C1/C2/C3 | Drops C3 | Pendentes C3 | p99 crítico C3 (ms) | Miss crítico máx C3 (%) | Perda máx C3 (%) | Goodput mín C3 (%) | Q não estáveis |", "|---|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for config, cell in document["cells"].items():
        treatments = cell["treatments"]
        viable = "/".join("sim" if treatments.get(label, {}).get("viable") else
                          "não" if treatments.get(label, {}).get("viable") is False else "—"
                          for label in ("C0", "C1", "C2", "C3"))
        c3 = treatments.get("C3")
        if c3:
            lines.append(f"| {config.replace('Validate_C3_', '')} | simulada | {viable} | {c3['recorded_drops']} | {c3['pending_packets_at_simulation_end']} | {c3['critical_packet_p99_max_s']*1e3:.4f} | {c3['critical_deadline_miss_ratio_max']*100:.3f} | {c3['packet_loss_ratio_max']*100:.3f} | {c3['goodput_payload_ratio_min']*100:.2f} | {c3['nonstable_queues']} |")
        else:
            lines.append(f"| {config.replace('Validate_C3_', '')} | reservation-infeasible | {viable} | — | — | — | — | — | — | — |")
    lines += ["", "## Reservas congeladas", "", "| Egress/TC | Razão C3/C2 | idleSlope C3 em L2 (Mb/s) | Reservado por porta no máximo entre L0–L2 |", "|---|---:|---:|---:|"]
    calibration = document["calibration"]
    ratios = calibration["frozen_ratios"]
    from generate_cbs import nominal_reservations
    for key, ratio in sorted(ratios.items()):
        egress, tc_text = key.rsplit("/TC", 1)
        tc = int(tc_text)
        nominal = nominal_reservations(read_flows())[2, egress, tc]["bps"]
        rates = [document["reservation_screen"][f"L{load}"].get(egress, {}).get("total_cbs_reservation_bps", 0) for load in range(3)]
        val = round(nominal * ratio)
        lines.append(f"| `{egress} TC{tc}` | {ratio:.6f} | {val/1e6:.3f} | {max(rates)/1e6:.3f} Mb/s |")
    lines += ["", "## Leitura e rastreabilidade", "",
              f"Células simuladas: {document['C3_simulated_cells']}; reservation-infeasible: {len(document['C3_reservation_infeasible_cells'])}. Viabilidade nas execuções seed 41: " + ", ".join(f"{label} {count}/{6 if label != 'C0' and label != 'C1' and label != 'C2' else 8}" for label, count in document["viability_counts"].items()) + ". Os JSONs contêm p99/máximo, misses, goodput, perda, utilização, filas e métricas por fluxo/receptor.", "",
              "A comparação C3−C2 em L2/A1 reutiliza a própria célula de calibração após congelar as razões. As diferenças são diagnósticas de uma seed, não confirmação estatística de H3. C3/L3 permanece a fronteira prevista pelo limite de reserva do P1. Câmeras continuam sem pre-shaping; melhoria é atribuível ao serviço CBS configurado, dentro do limite por porta.", "",
              "Resultados da comparação em `C0_C1_C2_C3_comparison.json`; reservas por porta em `cbs_calibrated_reservations.csv`; história de calibração em `simulations/results/C3/calibration/C3_calibration.json`. Os dados brutos grandes foram apagados logo após validar cada célula.", ""]
    (OUTPUT / "C0_C1_C2_C3_analysis.md").write_text("\n".join(lines))


def validate_matrix(env, inet, data, signature, screen):
    reports = {}
    for config in MATRIX:
        if config == "Validate_C3_L2_A1":
            # Reuse the complete final calibration run at the frozen ratio.
            calibration_file = SIM / "results/C3/calibration/C3_calibration.json"
            cal = json.loads(calibration_file.read_text())
            report = deepcopy(cal["final_calibration_report"])
            report["config"] = config
            report["treatment"] = "C3"
            report["validation_cell_reused_from_calibration"] = True
            destination = OUTPUT / f"{config}-0"
            destination.mkdir(parents=True, exist_ok=True)
            (destination / "c3-acceptance.json").write_text(json.dumps(report, indent=2) + "\n")
            # Retain only the small run summary needed for the matrix comparison.
            calibration_run = SIM / "results/C3/calibration" / cal["calibration"]["final_trial_label"] / f"Calibrate_C3_L2_A1-0/validation.json"
            if calibration_run.is_file():
                shutil.copy2(calibration_run, destination / "validation.json")
            check_workload_pairing(report, load_c2_cell("Validate_C2_L2_A1"), config)
            reports[config] = report
            continue
        print(f"C3 full-matrix validation: {config}", flush=True)
        report = simulate_final_cell(config, env, inet, data, signature)
        reports[config] = report
        (OUTPUT / f"{config}-0/c3-acceptance.json").write_text(json.dumps(report, indent=2) + "\n")
    # The two L3 cells are represented as screened boundaries, never as failures.
    result = {name: report for name, report in reports.items()}
    (OUTPUT / "C3_acceptance.json").write_text(json.dumps(result, indent=2) + "\n")
    document = comparison_document(reports, screen, json.loads((SIM / "results/C3/calibration/C3_calibration.json").read_text()))
    (OUTPUT / "C0_C1_C2_C3_comparison.json").write_text(json.dumps(document, indent=2) + "\n")
    write_markdown(document)
    return reports, document


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inet-root", default=os.environ.get("INET_ROOT"))
    parser.add_argument("--omnetpp-root", default=os.environ.get("OMNETPP_ROOT"))
    parser.add_argument("--recalibrate", action="store_true",
                        help="perform deterministic calibration and run all admissible C3 cells")
    parser.add_argument("--matrix-only", action="store_true",
                        help="reuse the frozen calibration JSON and validate the admissible matrix")
    args = parser.parse_args()
    require(bool(args.inet_root), "Set INET_ROOT or pass --inet-root")
    inet = Path(args.inet_root).resolve()
    omnetpp = Path(args.omnetpp_root).resolve() if args.omnetpp_root else None
    opp_run = shutil.which("opp_run")
    if omnetpp is None and opp_run:
        omnetpp = Path(opp_run).resolve().parent.parent
    require(omnetpp is not None, "Load OMNeT++ or pass --omnetpp-root")
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = ":".join(filter(None, [str(omnetpp / "lib"), str(inet / "src"), env.get("LD_LIBRARY_PATH", "")]))
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (SIM / "results/C3/calibration").mkdir(parents=True, exist_ok=True)
    require((SIM / "results/C2/p1-validation-64KiB-final/C0_C1_C2_diagnostic.json").is_file(),
            "Preserved C2 raw-evidence diagnostic is required to identify calibration targets")
    for path in BASELINE_PATHS.values():
        require(path.is_file(), f"Missing preserved baseline analysis {path}")
    subprocess.run([sys.executable, str(ROOT / "scripts/catalog/generate.py"), "--check"], check=True)
    subprocess.run([sys.executable, str(ROOT / "scripts/catalog/generate_cbs.py"), "--check"], check=True)
    if not args.matrix_only:
        data, calibration_report, signature, calibration = calibrate(env, inet, OUTPUT)
    else:
        data = json.loads(CALIBRATION.read_text())
        require(data["calibration"].get("status") == "complete_viability_reached_and_reduced",
                "No frozen, viability-qualified C3 calibration is available")
        prior = json.loads((SIM / "results/C3/calibration/C3_calibration.json").read_text())
        calibration_report = prior["final_calibration_report"]
        signature = prior["calibration"]["transient_event_signature"]
        calibration = prior
    save_ratio_data(data)
    screen = json.loads((ROOT / "simulations/zonal/traffic/c3_reservation_screen.json").read_text())
    require(screen["inadmissible_loads"] == ["L3"],
            f"Unexpected C3 admissibility screen {screen['inadmissible_loads']}; inspect cap and ratios")
    require_space("C3 matrix")
    reports, document = validate_matrix(env, inet, data, signature, screen)
    print(f"C3 calibration and validation complete: "
          f"{sum(r['viable'] for r in reports.values())}/{len(reports)} executed cells viable; "
          f"L3 excluded by the 75% reservation cap. Results: {OUTPUT}", flush=True)


if __name__ == "__main__":
    main()
