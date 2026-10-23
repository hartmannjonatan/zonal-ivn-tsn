#!/usr/bin/env python3
"""Manual entry point for full or two-machine sharded official campaigns.

The child runners retain independent manifests, locks, ledgers and checkpoints.
Shard runs use machine-local result trees and are merged only by the audited
merge tool after both machines finish. This script never starts simulations
unless an explicit execution mode is selected.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
C0_C3_RUNNER = HERE / "run_campaign.py"
C4_RUNNER = HERE / "c4_official" / "run_c4_campaign.py"
C3_RESULTS = HERE / "results"
C4_RESULTS = HERE / "c4_official" / "results" / "C4"
SHARD_PREPARER = HERE / "prepare_parallel_campaign.py"


def require_c3_profile_accepted() -> dict:
    calibration_path = C3_RESULTS / "calibration" / "C3_calibration.json"
    if not calibration_path.is_file():
        raise RuntimeError("C0-C3 calibration record is missing; this orchestrator will not run calibration")
    calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
    if calibration.get("status") != "frozen_and_accepted":
        raise RuntimeError("C3 profile is not frozen and accepted; refusing to start the final sequence")
    return calibration


def require_final_c0_c3_complete() -> dict:
    path = C3_RESULTS / "campaign_results.json"
    if not path.is_file():
        raise RuntimeError("C0-C3 final campaign summary is absent; C4 cannot start yet")
    summary = json.loads(path.read_text(encoding="utf-8"))
    if not summary.get("complete") or summary.get("completed_runs") != summary.get("expected_runs"):
        raise RuntimeError(
            "C0-C3 final matrix is incomplete; resume it before C4 "
            f"({summary.get('completed_runs')}/{summary.get('expected_runs')} results)"
        )
    if summary.get("c4_executed") is not False:
        raise RuntimeError("C0-C3 summary has an unexpected C4 execution flag; audit before continuing")
    return summary


def run(command: list[str]) -> int:
    print("$ " + " ".join(command), flush=True)
    result = subprocess.run(command, cwd=ROOT)
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight-only", action="store_true",
                      help="check frozen C3 status and C4 static/resource contracts; never simulates")
    mode.add_argument("--run", action="store_true",
                      help="resume C0-C3 final cells, then run C4 only after C0-C3 is complete")
    mode.add_argument("--c0-c3-only", action="store_true",
                      help="resume only the existing C0-C3 final runner")
    mode.add_argument("--c4-only", action="store_true",
                      help="run C4 only; requires accepted C3 calibration and paired C0 calendars, not C3 final completion")
    mode.add_argument("--c1-c2-shard", action="store_true",
                      help="run only C1 and C2 final treatments on this machine")
    mode.add_argument("--c3-c4-shard", action="store_true",
                      help="run C3 final treatment, then C4, sequentially on this machine")
    mode.add_argument("--preflight-c1-c2-shard", action="store_true",
                      help="validate the prepared C1/C2 shard without starting simulations")
    mode.add_argument("--preflight-c3-c4-shard", action="store_true",
                      help="validate this C0-owning host for its local C3/C4 shard without starting simulations")
    parser.add_argument("--resume", action="store_true",
                        help="required for execution modes; children reuse only matching valid ledger entries")
    parser.add_argument("--jobs", type=int, default=1,
                        help="C0-C3 worker count (defaults to 1 and is capped by available RAM); C4 is serialized")
    parser.add_argument("--shard-id", help="stable local shard name; required for either shard mode")
    args = parser.parse_args()
    if not 1 <= args.jobs <= 4:
        parser.error("--jobs must be between 1 and 4")
    execution_mode = args.run or args.c0_c3_only or args.c4_only or args.c1_c2_shard or args.c3_c4_shard
    if execution_mode and not args.resume:
        parser.error("execution modes require --resume")

    shard_mode=args.c1_c2_shard or args.c3_c4_shard
    preflight_shard_mode=args.preflight_c1_c2_shard or args.preflight_c3_c4_shard
    if shard_mode and not args.shard_id:
        parser.error("--shard-id is required for a shard mode")
    if (not shard_mode or preflight_shard_mode) and args.shard_id:
        parser.error("--shard-id is only valid with a shard mode")
    if args.c1_c2_shard and args.c3_c4_shard:
        parser.error("select only one shard mode")

    if args.preflight_only:
        require_c3_profile_accepted()
        print("C0-C3 calibration: frozen_and_accepted", flush=True)
        return run([sys.executable, str(C4_RUNNER), "--preflight-only"])

    if args.preflight_c1_c2_shard:
        return run([sys.executable, str(SHARD_PREPARER), "--verify-c1-c2-replica"])

    if args.preflight_c3_c4_shard:
        rc=run([sys.executable, str(SHARD_PREPARER), "--verify-secondary"])
        if rc: return rc
        return run([sys.executable, str(C4_RUNNER), "--preflight-only"])

    if args.c4_only:
        # C4 depends on the already frozen C3 calibration profile and paired
        # calendars, not on completion of the separate C0-C3 final matrix.
        # The C4 child runner still refuses concurrent C0-C3/OMNeT processes.
        require_c3_profile_accepted()
        return run([sys.executable, str(C4_RUNNER), "--run", "--resume", "--jobs", "1"])

    if args.c1_c2_shard:
        require_c3_profile_accepted()
        rc=run([sys.executable, str(SHARD_PREPARER), "--verify-c1-c2-replica"])
        if rc: return rc
        return run([sys.executable, str(C0_C3_RUNNER), "--phase", "final", "--resume",
                    "--jobs", str(args.jobs), "--treatments", "C1,C2", "--shard-id", args.shard_id])

    if args.c3_c4_shard:
        require_c3_profile_accepted()
        rc=run([sys.executable, str(SHARD_PREPARER), "--verify-secondary"])
        if rc: return rc
        rc=run([sys.executable, str(C0_C3_RUNNER), "--phase", "final", "--resume",
                "--jobs", str(args.jobs), "--treatments", "C3", "--shard-id", args.shard_id])
        if rc:
            print("C3 shard exited with status {}; C4 was not started.".format(rc),
                  file=sys.stderr, flush=True)
            return rc
        print("C3 shard exited cleanly; starting its sequential C4 runner.", flush=True)
        return run([sys.executable, str(C4_RUNNER), "--run", "--resume", "--jobs", "1"])

    if args.c0_c3_only:
        require_c3_profile_accepted()
        return run([sys.executable, str(C0_C3_RUNNER), "--phase", "final", "--resume",
                    "--jobs", str(args.jobs)])

    # Default full sequence. Child processes own their locks and checkpoints;
    # C4 starts only after the C0-C3 child exits and its durable summary passes.
    require_c3_profile_accepted()
    rc = run([sys.executable, str(C0_C3_RUNNER), "--phase", "final", "--resume",
              "--jobs", str(args.jobs)])
    if rc:
        print(f"C0-C3 runner exited with status {rc}; C4 was not started.", file=sys.stderr, flush=True)
        return rc
    require_final_c0_c3_complete()
    print("C0-C3 final matrix is complete; starting the separately checkpointed C4 matrix.", flush=True)
    return run([sys.executable, str(C4_RUNNER), "--run", "--resume", "--jobs", "1"])


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"Campaign orchestration stopped safely: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(2)
