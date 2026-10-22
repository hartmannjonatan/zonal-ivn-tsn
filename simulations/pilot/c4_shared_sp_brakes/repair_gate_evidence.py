#!/usr/bin/env python3
"""Repair the C4-compensated gate audit from retained compact evidence only."""
from __future__ import annotations

import csv
import gzip
import importlib.util
import json
import math
import os
import shutil
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "results"
EXECUTION_ID = "C4compensated_L2_A1_seed41"
CONFIG = "Pilot_C4compensated_L2_A1"


def load_runner():
    spec = importlib.util.spec_from_file_location("c4_pilot_runner", HERE / "run_pilot.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    runner = load_runner()
    report_path = OUT / "runs" / EXECUTION_ID / "pilot-result.json"
    report = json.loads(report_path.read_text())
    evidence_dir = OUT / "runs" / EXECUTION_ID / f"{CONFIG}-0"
    trace_path = evidence_dir / "gate_states.csv.gz"
    if report.get("gate_audit_reprocessed_from_compact_evidence"):
        raise SystemExit("This execution's gate audit is already corrected.")
    if not trace_path.is_file():
        raise SystemExit(f"Missing compact gate-state evidence: {trace_path}")
    if report.get("effective_gcl", {}).get("status") != "pass":
        raise SystemExit("Effective SCA GCL audit did not pass; refusing to repair from vectors alone.")

    start, end = 1.0, 31.0
    expected = {}
    for port in runner.TAS_EGRESSES:
        for tc in range(8):
            expected[f"ZonalIVN.{port}.macLayer.queue.transmissionGate[{tc}]"] = 0.10 if tc == 7 else 0.77
    area, previous, samples = {}, {}, {}
    with gzip.open(trace_path, "rt", newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            module = row["module"]
            if module not in expected:
                continue
            t, state = float(row["simtime_s"]), float(row["state_open"])
            if module in previous and t < previous[module][0]:
                raise SystemExit(f"Non-monotonic compact gate samples for {module}")
            area[module], previous[module] = runner.accumulate_sample_hold(
                area.get(module, 0.0), previous.get(module), t, state, start, end)
            samples[module] = samples.get(module, 0) + 1
    fractions = {}
    for module in expected:
        if module not in previous or samples.get(module, 0) == 0:
            raise SystemExit(f"Missing scheduled TAS gate evidence for {module}")
        total = runner.finish_sample_hold(area.get(module, 0.0), previous[module], start, end)
        fractions[module] = total / (end - start)
    checks = {module: {"expected_open_fraction": target,
                       "observed_open_fraction": fractions[module],
                       "within_1e-4": abs(fractions[module] - target) <= 1e-4,
                       "samples": samples[module]}
              for module, target in expected.items()}
    if not all(item["within_1e-4"] for item in checks.values()):
        raise SystemExit("A scheduled gate fraction does not match the configured TAS schedule.")

    sp_gates = [gate for gate in report["effective_gcl"].get("gates", {}).values()
                if gate.get("permanently_open_sp")]
    if len(sp_gates) != 24 or not all(gate.get("pass") for gate in sp_gates):
        raise SystemExit(f"Expected 24 effective-SCA verified open SP gates; found {len(sp_gates)}.")

    audit = report["pilot_vector_audit"]
    audit["tas_gate_schedule"] = {
        "status": "pass", "measurement_window_s": [start, end],
        "expected_gate_count": len(expected), "observed_gate_count": len(checks),
        "tolerance_fraction": 1e-4, "gates": checks,
        "always_open_sp_gate_count_config_verified": len(sp_gates),
        "always_open_sp_verification": "pass",
        "note": "Scheduled-gate fractions were recomputed from compact sample-hold events. The 24 permanently open SP brake gates have empty schedules, produce no transitions, and were verified from their effective SCA parameters instead of requiring nonexistent state-change vectors."}
    audit["state_vector_status"] = "available" if (
        report.get("physical_link_utilization", {}).get("transmitters_observed", 0) == 56 and
        audit.get("clock_vector_status") == "pass" and audit["tas_gate_schedule"]["status"] == "pass") else "incomplete"
    if audit["state_vector_status"] != "available":
        raise SystemExit("Other required state evidence is incomplete; refusing to label run valid.")
    audit["state_vector_status_reason"] = "Scheduled gates verified from compact vectors; always-open SP gates verified from effective SCA configuration."
    report["simulation_valid"] = bool(
        report.get("calendar_pairing_status") == "paired" and
        report.get("resolved_cbs_profile_matches") and
        audit["state_vector_status"] == "available" and
        report.get("effective_time_synchronization", {}).get("status") == "pass" and
        report.get("effective_gcl", {}).get("status") == "pass")
    report["tas_instrumentation_viable"] = True
    report["pilot_viable"] = bool(
        report.get("admissible") and report["simulation_valid"] and
        report.get("application_viable") and
        report.get("synchronization_viable") is not False and
        report["tas_instrumentation_viable"])
    report["gate_audit_reprocessed_from_compact_evidence"] = {
        "source": str(trace_path.relative_to(HERE)),
        "method": "sample-hold integration over [1,31) s for 32 scheduled gates; 24 no-transition SP gates independently checked in effective SCA",
        "previous_status": "fail (expected 56 state-vector gates, only 32 schedule gates emit transitions)",
        "corrected_status": "pass", "simulation_rerun": False}

    ledger_path = OUT / "runs.jsonl"
    rows = runner.current_ledger()
    matched = [i for i, row in enumerate(rows) if row.get("execution_id") == EXECUTION_ID]
    if len(matched) != 1:
        raise SystemExit(f"Expected exactly one ledger row for {EXECUTION_ID}; found {len(matched)}")
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    history = OUT / "plan_history" / f"runs-before-gate-audit-repair-{stamp}.jsonl"
    history.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ledger_path, history)
    backup_report = report_path.with_name("pilot-result-before-gate-audit-repair.json")
    if not backup_report.exists():
        shutil.copy2(report_path, backup_report)
    acceptance = evidence_dir / "c4compensated-pilot-acceptance.json"
    acceptance_backup = evidence_dir / "c4compensated-pilot-acceptance-before-gate-audit-repair.json"
    if acceptance.exists() and not acceptance_backup.exists():
        shutil.copy2(acceptance, acceptance_backup)
    rows[matched[0]] = report
    tmp = ledger_path.with_suffix(".jsonl.tmp")
    tmp.write_text("".join(json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n" for row in rows))
    os.replace(tmp, ledger_path)
    runner.write_json(report_path, report)
    runner.write_json(acceptance, report)
    manifest = json.loads((OUT / "plan.json").read_text())
    runner.regenerate_reports(manifest)
    runner.append_jsonl(OUT / "recovery_events.jsonl", {
        "event": "C4_compensated_gate_audit_recomputed_from_preserved_compact_evidence",
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "execution_id": EXECUTION_ID, "simulation_rerun_required": False,
        "source": str(trace_path.relative_to(HERE)),
        "effective_sca_gcl_status": report["effective_gcl"]["status"],
        "scheduled_gates_recomputed": len(checks), "always_open_sp_gates_config_verified": len(sp_gates),
        "corrected_simulation_valid": report["simulation_valid"],
        "application_viable": report.get("application_viable"),
        "pilot_viable": report["pilot_viable"],
        "prior_ledger_copy": str(history.relative_to(HERE)),
        "prior_report_copy": str(backup_report.relative_to(HERE))})
    print(json.dumps({"execution_id": EXECUTION_ID, "scheduled_gate_count": len(checks),
        "open_sp_gates_config_verified": len(sp_gates), "simulation_valid": report["simulation_valid"],
        "application_viable": report.get("application_viable"),
        "synchronization_viable": report.get("synchronization_viable"),
        "queue_nonstable_count": len(report.get("nonstable_queues", [])),
        "queue_overflow_drops": report.get("queue_overflow_drop_total_post_warmup_including_drain"),
        "pilot_viable": report["pilot_viable"]}, indent=2))


if __name__ == "__main__":
    main()
