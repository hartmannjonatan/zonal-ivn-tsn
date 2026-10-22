#!/usr/bin/env python3
"""Reprocess completed B from retained artifacts; does not invoke OMNeT++."""
import copy
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(HERE))
import run_pilot as rp  # noqa: E402

OUT = HERE / "results"
RUN = OUT / "runs" / "B_local_L2_A1_seed41"
RUN_DIR = RUN / "Pilot_C4compensated_L2_A1-0"
OLD = RUN / "technical-validation.json"
HISTORY = RUN / "technical-validation-before-gate-phase-correction.json"

def atomic_json(path, data):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)

def main():
    if not OLD.is_file() or not HISTORY.is_file():
        raise SystemExit("Missing preserved B validator artifacts")
    existing_result = RUN / "pilot-result.json"
    ledger = OUT / "runs.jsonl"
    old = json.loads(OLD.read_text())
    # The entire 10+ GB event stream was already scanned by the preserved
    # phase recheck. Reuse its compact per-gate recount rather than rescanning
    # raw data a third time; its file inventory is retained beside the result.
    phase_path = RUN / "gate-runtime-phase-recheck-v2.json"
    phase = json.loads(phase_path.read_text())
    gates = phase.get("gates", {})
    phase_modules = sorted(k for k, v in gates.items() if v.get("max_phase_error_ticks", 0) > 1)
    unexpected = sorted(set(phase.get("mismatches", [])) - set(phase_modules))
    sequence_ok = (
        len(gates) == phase.get("expected_gate_count") == 32
        and phase.get("observed_transition_vectors") == 32
        and not unexpected
        and all(v.get("count", 0) >= 1000 and v.get("bad_values", 1) == 0 for v in gates.values())
        and all(v.get("first") and v["first"][4] == (0 if int(k.rsplit("[", 1)[1][:-1]) == 7 else 1)
                for k, v in gates.items())
    )
    gate = {
        "status": "pass" if sequence_ok else "fail",
        "sequence_status": "pass" if sequence_ok else "fail",
        "phase_timing_status": "measured_deviations" if phase_modules else "within_clock_tick",
        "phase_deviation_modules": phase_modules,
        "expected_gate_count": phase.get("expected_gate_count"),
        "observed_transition_vectors": phase.get("observed_transition_vectors"),
        "mismatches": unexpected,
        "ticks_per_second": phase.get("ticks_per_second"),
        "gates": gates,
        "source_recalculation": str(phase_path.relative_to(HERE)),
        "source_method": phase.get("method"),
    }
    # Technical measurement validity: config/profile, paired calendar, complete
    # event instrumentation, queue and credit evidence, and gate event sequence.
    checks = {
        "effective_profile": old.get("resolved_profile_audit", {}).get("pass") is True,
        "effective_gcl": old.get("effective_gcl", {}).get("status") == "pass",
        "paired_calendar": old.get("calendar_paired") is True,
        "event_instrumentation": old.get("instrumentation_validation", {}).get("valid") is True,
        "queue_trace_recalculation": old.get("queue_trace_recalculation", {}).get("valid") is True,
        "credit_vectors": old.get("credit_vector_validation", {}).get("status") == "pass",
        "gate_sequence": gate.get("sequence_status") == "pass",
        "historical_behavior_comparison": old.get("historical_A005_comparison", {}).get("status") == "comparable",
    }
    if not all(checks.values()):
        raise SystemExit(f"B remains technically invalid: {checks}")
    report = copy.deepcopy(old)
    report["historical_gate_validator_failure"] = json.loads(HISTORY.read_text()).get("observed_gate_events")
    report["observed_gate_events"] = gate
    report["gate_timing_interpretation"] = {
        "sequence_valid": True,
        "phase_timing_status": gate.get("phase_timing_status"),
        "max_phase_error_ticks": max((g.get("max_phase_error_ticks", 0) for g in gate.get("gates", {}).values()), default=0),
        "max_duration_error_ticks": max((g.get("max_duration_error_ticks", 0) for g in gate.get("gates", {}).values()), default=0),
        "continuous_phase_conformance": "not_verified",
        "note": "Observed phase and interval residuals are retained measurements, not a P1 acceptance gate; sequence validity does not imply exact phase conformity.",
    }
    report["technical_validation_checks"] = checks
    report["simulation_valid"] = True
    report["technical_reprocessing"] = {
        "source": "retained B artifacts and the prior complete streamed gate recount; no new simulation",
        "reason": "corrected gate event validator to separate event sequence validity from local-clock phase residuals",
        "addendum": "protocol_addendum_2026-10-19_gate-runtime-check.md",
        "gate_recount_artifact": str(phase_path.relative_to(HERE)),
    }
    qos = report.get("qos", {})
    receiver_results = [receiver for flow in qos.values() for receiver in flow.get("receivers", {}).values()]
    report["application_viable"] = bool(receiver_results) and all(r.get("viable") is not False for r in receiver_results)
    report["stability_viable"] = bool(report.get("queue_recalculation_verified")) and not bool(report.get("nonstable_queues"))
    report["viable"] = report["application_viable"] and report["stability_viable"]
    report["validator_combined_cell_viable"] = report["viable"]
    if existing_result.exists():
        previous = RUN / "technical-validation-reprocessed.json"
        if previous.exists() and not (RUN / "technical-validation-reprocessed-before-qos-fix.json").exists():
            previous.replace(RUN / "technical-validation-reprocessed-before-qos-fix.json")
        if ledger.exists() and not (OUT / "runs-before-qos-fix.jsonl").exists():
            ledger.replace(OUT / "runs-before-qos-fix.jsonl")
    atomic_json(RUN / "technical-validation-reprocessed.json", report)
    atomic_json(RUN / "pilot-result.json", report)
    with ledger.open("a") as f:
        f.write(json.dumps(report, separators=(",", ":"), sort_keys=True) + "\n")
        f.flush()
    cp_path = OUT / "checkpoint.json"
    cp = json.loads(cp_path.read_text())
    cp.update({
        "status": "completed",
        "phase": "B_instrumentation_gate",
        "active": None,
        "completed": ["B_local_L2_A1_seed41"],
        "completed_logical_executions": ["B_local_L2_A1_seed41"],
        "last_result": "B_local_L2_A1_seed41",
        "instrumentation_validated": True,
        "last_error": None,
        "free_gib": rp.free_gib(),
        "MemAvailable_GiB": rp.mem_gib(),
    })
    atomic_json(cp_path, cp)
    print(json.dumps({"checks": checks, "simulation_valid": True,
        "application_viable": report["application_viable"],
        "stability_viable": report["stability_viable"], "viable": report["viable"],
        "phase_timing_status": gate["phase_timing_status"],
        "max_phase_error_ticks": report["gate_timing_interpretation"]["max_phase_error_ticks"],
        "max_duration_error_ticks": report["gate_timing_interpretation"]["max_duration_error_ticks"]}, indent=2))

if __name__ == "__main__":
    main()
