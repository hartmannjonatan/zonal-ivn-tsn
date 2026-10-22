#!/usr/bin/env python3
"""Re-export completed pilot rows with application and stability gates separated."""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "results"


def load_runner():
    spec = importlib.util.spec_from_file_location("c4_pilot_runner", HERE / "run_pilot.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    runner = load_runner()
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    history = OUT / "plan_history"
    history.mkdir(parents=True, exist_ok=True)
    for name in ("runs.jsonl", "pilot_results.json", "analysis.md"):
        source = OUT / name
        if source.exists():
            shutil.copy2(source, history / f"{source.stem}-before-gate-family-split-{stamp}{source.suffix}")

    rows = runner.current_ledger()
    corrected = 0
    for i, row in enumerate(rows):
        if row.get("status") != "completed":
            continue
        report_path = OUT / "runs" / row["execution_id"] / "pilot-result.json"
        report = json.loads(report_path.read_text())
        if report.get("gate_family_split_corrected"):
            rows[i] = report
            continue
        before = report_path.with_name("pilot-result-before-gate-family-split.json")
        if not before.exists():
            shutil.copy2(report_path, before)

        report["validator_combined_cell_viable"] = report.get("viable")
        report["application_viable"], report["application_gate_failures"] = runner.application_gate_summary(report)
        report["stability_viable"] = runner.stability_gate_result(report)
        report["pilot_viable"] = bool(
            report.get("admissible") is True and
            report.get("simulation_valid") is True and
            report["application_viable"] is True and
            report["stability_viable"] is True and
            report.get("synchronization_viable") is not False and
            report.get("tas_instrumentation_viable") is not False)
        report["status"] = "completed"
        report["gate_family_split_corrected"] = {
            "method": "derive application gates from each receiver's explicit P1 viable flag; derive stability separately from the independently recalculated queue trace",
            "simulation_rerun": False,
            "source": str(report_path.relative_to(HERE)),
            "previous_application_viable_semantics": "copied validator cell viability, which also included queue stability",
        }
        report["result_file"] = str(report_path.relative_to(HERE))
        rows[i] = report
        runner.write_json(report_path, report)
        for suffix in ("-pilot-acceptance.json",):
            acceptance = report_path.parent / f"{row.get('variant','').lower()}{suffix}"
            if acceptance.exists():
                runner.write_json(acceptance, report)
        corrected += 1

    ledger = OUT / "runs.jsonl"
    tmp = ledger.with_suffix(".jsonl.tmp")
    tmp.write_text("".join(json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n" for row in rows))
    os.replace(tmp, ledger)
    manifest = json.loads((OUT / "plan.json").read_text())
    runner.regenerate_reports(manifest)
    data_path = OUT / "pilot_results.json"
    data = json.loads(data_path.read_text())
    data["postprocessing"] = {
        "scope": "analysis/export correction only; no simulation or workload changes",
        "gate_family_split_corrected_rows": corrected,
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "runner_sha256_at_execution": manifest.get("versions_and_hashes", {}).get(
            "simulations/pilot/c4_shared_sp_brakes/run_pilot.py"),
        "runner_sha256_current_export_logic": runner.sha256(HERE / "run_pilot.py"),
    }
    runner.write_json(data_path, data)
    runner.append_jsonl(OUT / "recovery_events.jsonl", {
        "event": "application_and_stability_gate_families_separated",
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "rows_reprocessed": corrected,
        "simulation_rerun": False,
        "backup_directory": str(history.relative_to(HERE)),
        "C4_shared_L2_A1_application_gates_pass": data.get("decision_summary", {}).get(
            "c4_shared_spbrakes_l2_a1_all_application_gates_pass"),
        "C4_shared_L2_A1_stability_pass": data.get("decision_summary", {}).get(
            "c4_shared_spbrakes_l2_a1_queue_stability_pass"),
    })
    print(json.dumps({
        "completed_rows_reclassified": corrected,
        "decision_summary": data.get("decision_summary"),
        "backup_directory": str(history),
        "pilot_results": str(data_path),
    }, indent=2))


if __name__ == "__main__":
    main()
