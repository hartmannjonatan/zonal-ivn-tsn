#!/usr/bin/env python3
"""Reconcile final C4 pilot coverage and reused native-tick sync evidence.

This is post-processing only. It never launches OMNeT++ or edits run artifacts.
"""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import re
import shutil
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "results"
FIXED = ROOT / "simulations/pilot/c4_fixed_L2_profile/consolidate.py"
LOADS = ("L0", "L1", "L2")
ALIGNS = ("A0", "A1")
SEEDS = (41, 43, 47)
VARIANTS = ("D3_fixed_TAS", "D3_fixed_noTAS")


def read(path: Path):
    return json.loads(path.read_text())


def write(path: Path, value):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
    tmp.replace(path)


def sha(path: Path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def current_resources():
    free = shutil.disk_usage(HERE).free / 1024**3
    available = None
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                available = int(line.split()[1]) / 1024**2
                break
    except (OSError, ValueError):
        pass
    return {"free_disk_GiB": round(free, 3), "MemAvailable_GiB": round(available, 3) if available is not None else None}


def main():
    if not (HERE / "analysis.md").exists():
        raise RuntimeError("Expected prior analysis is missing; refusing to create an unanchored reconciliation")
    for name in ("analysis.md", "pilot_results.json", "matrix.csv", "results/checkpoint.json"):
        source = HERE / name
        backup = source.with_name(source.stem + "_pre_reconciliation_2026-10-22" + source.suffix)
        if source.exists() and not backup.exists():
            shutil.copy2(source, backup)

    spec = importlib.util.spec_from_file_location("c4_fixed_consolidator", FIXED)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    manifest = read(HERE / "manifest.json")
    checkpoint = read(OUT / "checkpoint.json")
    prior = read(HERE / "pilot_results.json")
    old_positions = {(x["load"], x["aggregation"], x["seed"], x["treatment"]): x for x in prior["positions"]}

    reused = {}
    for row in manifest.get("reused_methodological_positions", []):
        cell, seed, variant = row["position"].split("/")
        key = f"{variant}_{cell}_seed{seed[4:]}"
        reused[key] = row

    ledger_rows = []
    for line in (OUT / "runs.jsonl").read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if "position" in row:  # imported reuse ledger row
            continue
        logical = row.get("logical_execution_id") or re.sub(r"_technical_attempt_\d+$", "", row["execution_id"])
        ledger_rows.append((logical, row))
    new = {}
    for logical, row in ledger_rows:
        if logical in new:
            raise RuntimeError(f"Duplicate ledger result for {logical}")
        new[logical] = row

    executions = []
    positions = []
    expected = set()
    for load in LOADS:
        for align in ALIGNS:
            for seed in SEEDS:
                cell = f"{load}_{align}"
                for variant in VARIANTS:
                    logical = f"{variant}_{cell}_seed{seed}"
                    expected.add(logical)
                    if logical in reused:
                        manifest_row = reused[logical]
                        run_dir = ROOT / manifest_row["source"]
                        report_path = run_dir / "pilot-result.json"
                        kind = "reused"
                        audit_path = next(run_dir.glob("**/clock_precision.csv.gz"), None)
                        if audit_path is None:
                            raise RuntimeError(f"Missing preserved native-tick audit for reused run {logical}")
                        sync = module.clock_precision_summary(audit_path)
                        actual_id = manifest_row["execution_id"]
                        legacy_sync = read(report_path).get("synchronization_sample_viable")
                    else:
                        ledger = new.get(logical)
                        if ledger is None:
                            raise RuntimeError(f"No completed ledger row for authorized position {logical}")
                        actual_id = ledger["execution_id"]
                        run_dir = OUT / "runs" / actual_id
                        report_path = run_dir / "pilot-result.json"
                        kind = "completed_new"
                        report0 = read(report_path)
                        sync = report0.get("synchronization_native_tick_audit")
                        if not sync:
                            audit_path = next(run_dir.glob("**/clock_precision.csv.gz"), None)
                            if audit_path is None:
                                raise RuntimeError(f"Missing native-tick summary and source audit for {logical}")
                            sync = module.clock_precision_summary(audit_path)
                        legacy_sync = report0.get("synchronization_sample_viable")

                    report = read(report_path)
                    if not sync.get("observed_sample_pass"):
                        raise RuntimeError(f"Direct native-tick synchronization audit does not pass for {logical}")
                    if kind == "completed_new":
                        ledger = new[logical]
                        for field in ("simulation_valid", "application_viable", "stability_viable", "synchronization_sample_viable"):
                            if ledger.get(field) is not True:
                                raise RuntimeError(f"Ledger gate {field} is not true for {logical}")
                    for field in ("simulation_valid", "application_viable", "stability_viable"):
                        if report.get(field) is not True:
                            raise RuntimeError(f"Run report gate {field} is not true for {logical}")

                    source_rel = str(report_path.relative_to(ROOT))
                    report_hash = sha(report_path)
                    queue_rows = module.queue_metrics(report)
                    flow_rows = module.receiver_metrics(report)
                    row = old_positions.get((load, align, seed, variant), {
                        "load": load, "aggregation": align, "seed": seed, "treatment": variant
                    })
                    row.update({
                        "position_status": kind,
                        "source_execution": actual_id,
                        "notes": "Post-run reconciled from the preserved report and direct native-tick audit; no simulation was rerun.",
                        "source_report": source_rel,
                        "source_report_sha256": report_hash,
                        "technical_valid": report.get("simulation_valid"),
                        "application_viable": report.get("application_viable"),
                        "stability_viable": report.get("stability_viable"),
                        "sampled_sync_viable": sync["observed_sample_pass"],
                        "continuous_sync": "not_verified",
                        "queue_overflow_drops": report.get("queue_overflow_drop_total_post_warmup_including_drain"),
                        "pending_at_end": report.get("pending_packet_count_at_simulation_end"),
                        "offered_packets": report.get("total_offered_packets"),
                        "calendar_sha256": report.get("calendar_sha256"),
                        "effective_profile_sha256": report.get("effective_profile_sha256"),
                        "sync_audit_authoritative": sync,
                        "legacy_report_sampled_sync_flag": legacy_sync,
                        "run_report": {
                            "path": source_rel,
                            "sha256": report_hash,
                            "qos_by_flow_receiver": flow_rows,
                            "queue_stability_targets": queue_rows,
                            "overflow_drops_by_queue": report.get("queue_overflow_drops_by_queue"),
                            "drop_reconciliation": report.get("drop_reconciliation"),
                            "pending_packet_count_at_simulation_end": report.get("pending_packet_count_at_simulation_end"),
                            "gcl_status": (report.get("effective_gcl") or {}).get("status"),
                            "profile_validation": report.get("resolved_profile_audit"),
                        },
                    })
                    positions.append(row)

                    max_ns = max(v["max_abs_offset_s"] for group in (sync["periodic"], sync["signal"]) for v in group.values()) * 1e9
                    periodic_min = min(v["samples"] for v in sync["periodic"].values())
                    periodic_max = max(v["samples"] for v in sync["periodic"].values())
                    signal_min = min(v["samples"] for v in sync["signal"].values())
                    signal_max = max(v["samples"] for v in sync["signal"].values())
                    executions.append({
                        "logical_execution_id": logical,
                        "execution_id": actual_id,
                        "position": f"{cell}/seed{seed}/{variant}",
                        "kind": kind,
                        "report_path": source_rel,
                        "report_sha256": report_hash,
                        "calendar_sha256": report.get("calendar_sha256"),
                        "simulation_valid": report.get("simulation_valid"),
                        "application_viable": report.get("application_viable"),
                        "stability_viable": report.get("stability_viable"),
                        "synchronization_sample_viable": sync["observed_sample_pass"],
                        "legacy_report_sync_flag": legacy_sync,
                        "synchronization_continuous_status": "not_verified",
                        "synchronization_max_abs_offset_ns": max_ns,
                        "periodic_samples_per_node": {"minimum": periodic_min, "maximum": periodic_max},
                        "clock_event_snapshots_per_node": {"minimum": signal_min, "maximum": signal_max},
                        "native_tick_csv_path": str(next(run_dir.glob("**/clock_precision.csv.gz")).relative_to(ROOT)),
                        "native_tick_csv_sha256": sha(next(run_dir.glob("**/clock_precision.csv.gz"))),
                        "queue_overflow_drops_postwarmup_including_drain": report.get("queue_overflow_drop_total_post_warmup_including_drain"),
                    })

    if len(expected) != 36 or len(executions) != 36:
        raise RuntimeError(f"Coverage mismatch: expected 36; reconciled {len(executions)}")
    if set(new) != (expected - set(reused)):
        raise RuntimeError(f"New-result ledger mismatch: expected {len(expected-set(reused))}, found {len(new)}")

    # Preserve all 12 L3 positions as triage rejections; no L3 run is permitted by this triage.
    for row in prior["positions"]:
        if row["load"] == "L3":
            positions.append(row)
    if len(positions) != 48:
        raise RuntimeError(f"Expected 48 matrix rows after triage, found {len(positions)}")

    # Preserve the old JSON before updating current derived status and metrics.
    prior["positions"] = positions
    prior["coverage_counts"] = {
        "methodological_positions_total": 48,
        "main_matrix_l0_l2_total": 36,
        "reused_valid": 10,
        "new_completed_valid": 26,
        "l0_l2_positions_unresolved": 0,
        "l3_triage_rejected_no_simulation": 12,
        "authorized_positions_not_run": 0,
        "technical_interrupted_attempts_non_results": 2,
        "technical_replacements_completed": 2,
    }
    prior["completion_reconciliation"] = {
        "source": "reconcile_completion.py; preserved run reports, runs.jsonl, manifest reuse identities, and native-tick clock_precision.csv.gz",
        "timestamp_local": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "main_matrix_complete": True,
        "all_36_main_positions_technical_application_stability_and_sampled_sync_pass": True,
        "continuous_sync": "not_verified",
        "runner_phase2_proceeded_while_reused_manifest_sync_states_were_false_or_pending": True,
        "posthoc_direct_tick_reconciliation_all_10_reused_positions_pass": True,
        "conditional_expansion_effect": "No actual sampled-sync failure was found in the reused positions after recalculation; the missing pre-phase-2 audit was a control-flow/auditability gap, not a discovered performance failure.",
        "executions": executions,
    }
    resources = current_resources()
    prior["current_completion_state"] = {
        "checkpoint_status": "phase2_complete",
        "active": False,
        "l0_l2_covered": 36,
        "l0_l2_total": 36,
        "l3_rejected_by_triage": 12,
        "remaining_authorized_simulations": 0,
        "resources_at_reconciliation": resources,
    }
    write(HERE / "pilot_results.json", prior)

    # Update the simple matrix using the exact same identities.
    source_by_pos = {(x["load"], x["aggregation"], x["seed"], x["treatment"]): x for x in positions}
    matrix = HERE / "matrix.csv"
    with matrix.open(newline="") as stream:
        original = list(csv.DictReader(stream))
        fields = list(original[0])
    with matrix.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for old in original:
            key = (old["load"], old["aggregation"], int(old["seed"]), old["treatment"])
            updated = dict(old)
            p = source_by_pos[key]
            updated["position_status"] = p["position_status"]
            updated["source_execution"] = p.get("source_execution", "")
            updated["notes"] = p.get("notes", old.get("notes", ""))
            writer.writerow(updated)

    # Reconcile the state file while preserving contradictory pre-run values as historical fields.
    state_path = OUT / "checkpoint.json"
    state = read(state_path)
    hist = state.setdefault("historical_fields_pre_reconciliation", {})
    for key in ("stop_reason", "next_batch", "last_error", "phase1_pending", "free_gib", "MemAvailable_GiB", "completed_positions"):
        if key in state:
            hist.setdefault(key, state[key])
    canonical_ids = sorted(expected)
    state.update({
        "status": "phase2_complete",
        "phase": "complete",
        "active": None,
        "phase1_complete": True,
        "phase2_started": True,
        "phase2_complete": True,
        "completed_positions": 36,
        "completed_new_logical_executions": sorted(expected - set(reused)),
        "completed_logical_executions": canonical_ids,
        "reused_valid_positions": 10,
        "phase1_pending": [],
        "technical_interrupted_attempts_non_results": 2,
        "technical_replacements_used": 2,
        "remaining_authorized_positions": 0,
        "triage_rejected_l3_positions": 12,
        "stop_reason": None,
        "next_batch": "No further methodological runs remain in this authorized pilot: L0-L2 are covered and all L3 positions were rejected by the frozen triage.",
        "last_error": None,
        "resources": resources,
        "completion_reconciliation": "results/reconciliation_2026-10-22.json",
    })
    write(state_path, state)

    # Write an independently inspectable reconciliation summary.
    legacy_false = [x for x in executions if x["legacy_report_sync_flag"] is False]
    sync = {
        "method": "recomputed direct-tick summary for reused runs; same direct-IClock integer-tick method used by current reports for new runs",
        "threshold_us": 1.0,
        "window_s": [1.0, 31.0],
        "reused_positions_total": 10,
        "reused_positions_direct_tick_pass": sum(x["synchronization_sample_viable"] for x in executions if x["kind"] == "reused"),
        "reused_positions_legacy_flag_false_but_direct_pass": len(legacy_false),
        "reused_positions_direct_tick_fail": sum(not x["synchronization_sample_viable"] for x in executions if x["kind"] == "reused"),
        "continuous_conformity": "not_verified",
        "reused_runs": [x for x in executions if x["kind"] == "reused"],
    }
    audit = {
        "exploratory": True,
        "official_c4_frozen": False,
        "as_of_local": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "reconciliation_script_sha256": sha(Path(__file__)),
        "clock_summary_helper_sha256": sha(FIXED),
        "authority": {"execution_reports": "pilot_results.json positions[].run_report.path and results/runs.jsonl", "reuse_identity": "manifest.json reused_methodological_positions", "protocol": "protocol.md", "triage": "triage.json"},
        "coverage": prior["coverage_counts"],
        "gate_summary": {field: sum(x[field] is True for x in executions) for field in ("simulation_valid", "application_viable", "stability_viable", "synchronization_sample_viable")},
        "native_tick_reconciliation": sync,
        "conditional_expansion_audit": {
            "preregistered_rule": "finish the matched pair then stop conditional expansion on any valid application, stability, sampled-sync, or technical failure in the phase-1 set",
            "runner_behavior": "the corrected run_pair stop predicate checked newly executed pair reports; reused positions were not fed into that predicate before phase2",
            "posthoc_result": "the 10 reused positions all pass the direct native-tick audit; the 4 old false flags were legacy-vector results and the 6 pending positions are now directly recalculated from preserved samples",
            "impact": "no sampled-sync failure is present in the reused evidence, so no demonstrated failed gate was bypassed; however the phase transition was not guarded by an explicit audit of reused positions at execution time",
            "newly_executed_phase_checks": "all 26 new reports and ledger rows pass simulation validity, application, stability, and sampled synchronization",
        },
        "technical_attempts": {
            "non_methodological_interrupted_attempts": 2,
            "completed_replacements": 2,
            "examples": ["D3_fixed_TAS_L1_A1_seed43: controlled resource-safe interruption, then completed result", "D3_fixed_TAS_L0_A1_seed43: power-loss partial at 49%, then completed technical replacement"],
            "partial_attempts_are_not_methodological_results": True,
        },
        "resources_at_reconciliation": resources,
        "executions": executions,
    }
    write(OUT / "reconciliation_2026-10-22.json", audit)
    print(json.dumps({"coverage": audit["coverage"], "gates": audit["gate_summary"], "sync_reused": {k: sync[k] for k in sync if k != "reused_runs"}, "resources": resources}, indent=2))


if __name__ == "__main__":
    main()
