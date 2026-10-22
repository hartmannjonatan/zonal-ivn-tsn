#!/usr/bin/env python3
"""Run the preregistered BM variant after correcting its gate mapping."""
import fcntl
import importlib.util
import json
import pathlib
import time

ROOT = pathlib.Path(__file__).resolve().parents[3]
HERE = ROOT / "simulations/pilot/c4_real_clock_service_margin"
SPEC = importlib.util.spec_from_file_location("c4pilot", HERE / "run_pilot.py")
pilot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pilot)

RESULTS = HERE / "results"
RUN_ID = "BM_recovery_L2_A1_seed41_technical_replacement_001"
OLD_ID = "BM_recovery_L2_A1_seed41"

def main():
    plan = json.loads((RESULTS / "plan.json").read_text())
    checkpoint = json.loads((RESULTS / "checkpoint.json").read_text())
    if checkpoint.get("active") is not None:
        raise SystemExit("checkpoint reports an active run")
    if OLD_ID not in checkpoint.get("completed", []):
        raise SystemExit("the original BM run is not recorded as completed")
    if (RESULTS / "runs" / RUN_ID).exists():
        raise SystemExit(f"replacement directory already exists: {RUN_ID}")
    if pilot.free_gib() < pilot.MIN_FREE_GIB or pilot.mem_gib() < pilot.MIN_MEM_GIB:
        raise SystemExit(f"resource floor not met: free={pilot.free_gib():.1f} GiB, available memory={pilot.mem_gib():.1f} GiB")

    # Verify all frozen source identities except the runner itself, whose
    # correction is explicitly recorded in addendum 006.
    current = pilot.source_hashes()
    frozen = plan["source_hashes"]
    changed = [key for key in frozen if key != "simulations/pilot/c4_real_clock_service_margin/run_pilot.py" and current.get(key) != frozen[key]]
    if changed:
        raise SystemExit("unexpected frozen input changes: " + ", ".join(changed))

    with pilot.LOCK.open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("pilot runner lock is held")
        print(f"Starting {RUN_ID}; free={pilot.free_gib():.1f} GiB, memory available={pilot.mem_gib():.1f} GiB", flush=True)
        result = pilot.run_one("BM_recovery", plan, execution_id_override=RUN_ID, technical_replacement_of=OLD_ID)
        if not result.get("simulation_valid") or result.get("effective_gcl", {}).get("status") != "pass":
            raise SystemExit("technical replacement failed configuration/instrumentation validation; raw evidence retained")
        checkpoint = json.loads((RESULTS / "checkpoint.json").read_text())
        checkpoint["technical_replacements_used"] = int(checkpoint.get("technical_replacements_used", 1)) + 1
        checkpoint["technical_replacement_completed"] = RUN_ID
        checkpoint["technical_replacement_reason"] = "BM gate schedule corrected to preregistered B_local schedule; original retained and excluded from corrected contrasts"
        checkpoint["free_gib"] = pilot.free_gib()
        checkpoint["MemAvailable_GiB"] = pilot.mem_gib()
        pilot.write_checkpoint(checkpoint)
        with (RESULTS / "technical_attempts.jsonl").open("a") as f:
            f.write(json.dumps({"attempt_id": RUN_ID, "kind": "technical_replacement_completed", "replaces": OLD_ID,
                                "reason": "original BM used R gate durations; replacement used B-local durations",
                                "simulation_valid": result.get("simulation_valid"),
                                "effective_gcl_status": result.get("effective_gcl", {}).get("status"),
                                "calendar_signature": result.get("calendar_sha256"),
                                "completed_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}) + "\n")
        print(f"Completed {RUN_ID}; gates/profile/calendar validated. free={pilot.free_gib():.1f} GiB, memory available={pilot.mem_gib():.1f} GiB")

if __name__ == "__main__":
    main()
