#!/usr/bin/env python3
"""Repair completed pilot exports from preserved SCA and compact evidence."""
from __future__ import annotations

import gzip
import importlib.util
import json
import os
import shutil
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "results"
REPAIRS = {
    "C4compensated_L2_A1_seed41": "C4compensated",
    "C4original_L2_A1_seed41": "C4original",
}


def load_runner():
    spec = importlib.util.spec_from_file_location("c4_pilot_runner", HERE / "run_pilot.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    runner = load_runner()
    ledger_path = OUT / "runs.jsonl"
    rows = runner.current_ledger()
    by_id = {row.get("execution_id"): (i, row) for i, row in enumerate(rows)}
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    history = OUT / "plan_history"
    history.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ledger_path, history / f"runs-before-completed-audit-repair-{stamp}.jsonl")
    manifest = json.loads((OUT / "plan.json").read_text())

    for execution_id, variant in REPAIRS.items():
        if execution_id not in by_id:
            raise SystemExit(f"Missing completed ledger row: {execution_id}")
        i, old_row = by_id[execution_id]
        report_path = OUT / "runs" / execution_id / "pilot-result.json"
        report = json.loads(report_path.read_text())
        if report.get("completed_audit_repair"):
            report["status"] = "completed"
            rows[i] = report
            continue

        report_backup = report_path.with_name("pilot-result-before-completed-audit-repair.json")
        if not report_backup.exists():
            shutil.copy2(report_path, report_backup)

        if variant == "C4original":
            # Brake egresses are permanently-open SP only in the shared-SP
            # treatment. The diagnostic schedules TAS on those same ports.
            config = report["config"]
            sca_gz = report_path.parent / f"{config}-#0.sca.gz"
            if not sca_gz.is_file():
                raise SystemExit(f"Missing preserved scalar configuration: {sca_gz}")
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".sca", delete=False) as tmp:
                temp_sca = Path(tmp.name)
                with gzip.open(sca_gz, "rt", errors="replace") as src:
                    shutil.copyfileobj(src, tmp)
            try:
                effective_gcl = runner.parse_effective_gcl(temp_sca, variant)
            finally:
                temp_sca.unlink(missing_ok=True)
            report["effective_gcl"] = effective_gcl
            report["simulation_valid"] = bool(
                report.get("calendar_pairing_status") == "paired" and
                report.get("resolved_cbs_profile_matches") and
                report.get("pilot_vector_audit", {}).get("state_vector_status") == "available" and
                report.get("effective_time_synchronization", {}).get("status") == "pass" and
                effective_gcl.get("status") == "pass")
            report["completed_audit_repair"] = {
                "source": str(sca_gz.relative_to(HERE)),
                "method": "re-read preserved effective SCA parameters with the corrected variant-aware parser; compact gate/link vectors were already retained",
                "previous_issue": "brake egresses were incorrectly treated as permanently-open SP in the full-path TAS diagnostic",
                "simulation_rerun": False,
                "effective_gcl_status": effective_gcl.get("status"),
            }

        report["status"] = "completed"
        report["result_file"] = str(report_path.relative_to(HERE))
        rows[i] = report
        runner.write_json(report_path, report)
        acceptance_path = report_path.parent / f"{variant.lower()}-pilot-acceptance.json"
        if acceptance_path.exists():
            runner.write_json(acceptance_path, report)

    tmp = ledger_path.with_suffix(".jsonl.tmp")
    tmp.write_text("".join(json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n" for row in rows))
    os.replace(tmp, ledger_path)
    checkpoint = json.loads((OUT / "checkpoint.json").read_text())
    checkpoint.update({
        "active": {}, "phase": "ready_after_completed_audit_repairs",
        "completed_count": sum(row.get("status") == "completed" for row in rows),
        "updated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "recovery_note": "Completed C4 audit exports repaired from preserved SCA and compact traces; no simulation rerun.",
    })
    runner.write_json(OUT / "checkpoint.json", checkpoint)
    runner.regenerate_reports(manifest)
    runner.append_jsonl(OUT / "recovery_events.jsonl", {
        "event": "completed_audit_exports_repaired",
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "execution_ids": list(REPAIRS), "simulation_rerun": False,
        "C4original_effective_gcl": rows[by_id["C4original_L2_A1_seed41"][0]].get("effective_gcl", {}).get("status"),
        "C4compensated_status": rows[by_id["C4compensated_L2_A1_seed41"][0]].get("status"),
        "prior_ledger_copy": str((history / f"runs-before-completed-audit-repair-{stamp}.jsonl").relative_to(HERE)),
    })
    print(json.dumps({eid: {
        "status": rows[by_id[eid][0]].get("status"),
        "simulation_valid": rows[by_id[eid][0]].get("simulation_valid"),
        "application_viable": rows[by_id[eid][0]].get("application_viable"),
        "pilot_viable": rows[by_id[eid][0]].get("pilot_viable"),
        "effective_gcl": rows[by_id[eid][0]].get("effective_gcl", {}).get("status"),
    } for eid in REPAIRS}, indent=2))


if __name__ == "__main__":
    main()
