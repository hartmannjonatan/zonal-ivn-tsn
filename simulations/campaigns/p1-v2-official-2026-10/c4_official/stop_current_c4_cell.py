#!/usr/bin/env python3
"""Safely interrupt only the active OMNeT++ C4 cell.

The runner records this as a technical interruption, preserves partial output,
releases its lock, and allows one replacement on --resume. Completed ledger
rows are untouched. The checkpoint PID may be from a nested PID namespace, so
the host PID is resolved by matching the executable and exact result directory.
Default mode is a dry run; --confirm sends SIGTERM only after a unique match.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHECKPOINT = HERE / "results/C4/checkpoint.json"


def process_info(pid: int) -> tuple[str, str, int] | None:
    """Return (comm, cmdline, process-group) for a live host PID."""
    proc = Path("/proc") / str(pid)
    try:
        argv = [x.decode(errors="replace") for x in (proc / "cmdline").read_bytes().split(b"\0") if x]
        comm = (proc / "comm").read_text().strip()
        pgid = os.getpgid(pid)
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        return None
    return comm, " ".join(argv), pgid


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm", action="store_true", help="send SIGTERM after verifying the active OMNeT++ PID")
    args = parser.parse_args()
    if not CHECKPOINT.is_file():
        raise SystemExit(f"C4 checkpoint not found: {CHECKPOINT}")
    state = json.loads(CHECKPOINT.read_text())
    active = state.get("active")
    if state.get("status") != "running" or not active:
        raise SystemExit(f"No active C4 simulation to stop safely (status={state.get('status')!r}). Do not signal a stale PID.")
    checkpoint_pid = int(active.get("pid") or 0)
    execution_id = str(active.get("execution_id") or "")
    if checkpoint_pid <= 1 or not execution_id.startswith("C4_"):
        raise SystemExit("Checkpoint has no trustworthy active PID/execution ID; refusing to signal anything.")
    expected_run = f"results/C4/runs/{execution_id}"
    matches = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        info = process_info(int(entry.name))
        if info is None:
            continue
        comm, cmdline, pgid = info
        if comm == "zonal-ivn-tsn" and expected_run in cmdline:
            matches.append((int(entry.name), cmdline, pgid))
    if len(matches) != 1:
        found = ", ".join(str(item[0]) for item in matches) or "none"
        raise SystemExit(
            f"Expected exactly one host C4 process for {execution_id}, found {len(matches)} ({found}); "
            "refusing to signal anything. Check whether the simulation has already exited."
        )
    pid, cmdline, pgid = matches[0]
    if pgid != pid:
        raise SystemExit(f"Host PID {pid} is not the expected isolated simulation process group; refusing to signal it.")
    proc = Path("/proc") / str(pid)
    print(f"Verified active cell: {execution_id}; host OMNeT++ PID/PGID={pid}; checkpoint PID={checkpoint_pid}; checkpoint={CHECKPOINT}")
    print("SIGTERM will interrupt this cell. Its partial output is retained as a technical attempt; resume will replace this cell once.")
    if not args.confirm:
        print("Dry run only. Repeat with --confirm to stop the active cell.")
        return 0
    # Pin the verified process against PID reuse where Linux pidfds are available.
    pidfd = None
    if hasattr(os, "pidfd_open") and hasattr(signal, "pidfd_send_signal"):
        try:
            pidfd = os.pidfd_open(pid)
            latest = process_info(pid)
            if latest is None or latest[0] != "zonal-ivn-tsn" or expected_run not in latest[1] or latest[2] != pid:
                os.close(pidfd)
                raise SystemExit("Matched host PID changed before signaling; refusing to signal anything.")
            signal.pidfd_send_signal(pidfd, signal.SIGTERM)
        except ProcessLookupError:
            raise SystemExit("Matched simulation exited before SIGTERM; nothing was signaled.")
    else:
        latest = process_info(pid)
        if latest is None or latest[0] != "zonal-ivn-tsn" or expected_run not in latest[1] or latest[2] != pid:
            raise SystemExit("Matched host PID changed before signaling; refusing to signal anything.")
        os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if not proc.exists():
            print(f"Stopped OMNeT++ PID {pid}; wait for the runner to record paused_technical_review before resuming.")
            if pidfd is not None:
                os.close(pidfd)
            return 0
        time.sleep(1)
    if pidfd is not None:
        os.close(pidfd)
    print(f"SIGTERM sent to PID {pid}; it has not exited after 45 s. Do not launch another runner; inspect the checkpoint and log.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
