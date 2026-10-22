#!/usr/bin/env python3
"""Single-screen live dashboard for the isolated C4 service-preservation pilot."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "results"
LOG_PERCENT = re.compile(r"\b(\d{1,3})% completed\s+\(\d{1,3}% total\)")


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def read_ledger():
    rows = []
    try:
        with (OUT / "runs.jsonl").open(encoding="utf-8") as f:
            for line in f:
                try:
                    if line.strip(): rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    except OSError:
        pass
    return rows


def read_attempts():
    rows = []
    try:
        with (OUT / "technical_attempts.jsonl").open(encoding="utf-8") as f:
            for line in f:
                try:
                    if line.strip(): rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    except OSError:
        pass
    return rows


def progress(path: Path):
    try:
        with path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 200_000))
            tail = f.read().decode("utf-8", errors="replace")
        matches = LOG_PERCENT.findall(tail)
        return min(100, int(matches[-1][0])) if matches else None
    except OSError:
        return None


def cell_label(spec):
    return f"{spec.get('cell', '?')} seed {spec.get('seed', '?')}"


def render():
    manifest = read_json(OUT / "plan.json", {}) or {}
    checkpoint = read_json(OUT / "checkpoint.json", {}) or {}
    rows = read_ledger()
    attempts = read_attempts()
    planned = manifest.get("run_schedule", [])
    byid = {r.get("execution_id"): r for r in rows}
    active = checkpoint.get("active", {}) or {}
    completed = sum(r.get("status") == "completed" for r in rows)
    failed = len(attempts)
    rejected = sum(r.get("status") == "rejected_before_execution" for r in rows)
    pending = [x for x in planned if x["execution_id"] not in byid]
    lines = [
        "C4 SERVICE-PRESERVATION PILOT  |  exploratory=true  |  official_c4_frozen=false",
        f"Updated: {time.strftime('%Y-%m-%d %H:%M:%S')}   Phase: {checkpoint.get('phase', 'not started')}",
        f"Completed: {completed}/{len(planned)}   Technical attempts: {failed}   Preflight rejections: {rejected}   Pending/retry: {len(pending)}",
        f"Jobs: {checkpoint.get('max_parallel_runs', 4)}   Free disk: {checkpoint.get('free_gb', '—')} GB   Floor: 45 GB",
        "",
        "ACTIVE RUNS",
        "ID                                      VARIANT          CELL/SEED      PROGRESS",
        "-" * 88,
    ]
    if not active:
        lines.append("(none)")
    else:
        for execution_id, item in sorted(active.items()):
            p = progress(HERE / item.get("log", "")) if item.get("log") else None
            phase = item.get("status", "starting")
            state = phase if phase in {"waiting_for_postprocessing", "validating_raw_outputs",
                                      "waiting_for_vector_audit", "extracting_pilot_vectors"} else (f"{p}%" if p is not None else phase)
            lines.append(f"{execution_id[:39]:39} {item.get('variant', ''):15} {item.get('cell', '')} seed {item.get('seed', ''):<3} {state}")
    lines += ["", "EXECUTION SCHEDULE", "STATUS                     VARIANT          CELL/SEED      KIND"]
    lines.append("-" * 88)
    for spec in planned:
        row = byid.get(spec["execution_id"])
        status = row.get("status", "pending") if row else "pending"
        if row and row.get("status") == "completed":
            status += f" / app={'PASS' if row.get('application_viable') else 'FAIL'}"
            status += f" / total={'PASS' if row.get('pilot_viable') else 'FAIL'}"
        lines.append(f"{status[:26]:26} {spec['variant']:16} {cell_label(spec):20} {spec['kind']}")
    lines += ["", "LATEST RESULT / ERROR"]
    last = rows[-1] if rows else None
    if last:
        lines.append(f"{last.get('execution_id')} — {last.get('status')}")
        if last.get("error"):
            lines.append(last["error"][:180])
        elif last.get("status") == "completed":
            lines.append(f"admissible={last.get('admissible')} valid={last.get('simulation_valid')} app_viable={last.get('application_viable')} sync={last.get('synchronization_viable')} TAS={last.get('tas_instrumentation_viable')}")
    else:
        lines.append("No execution recorded yet.")
    if attempts:
        attempt = attempts[-1]
        lines += ["", "LATEST TECHNICAL ATTEMPT (not a gate result)",
                  f"{attempt.get('execution_id')} — {attempt.get('error', 'technical failure')[:180]}"]
    lines += ["", "Ctrl+C exits dashboard. This display is read-only; run_pilot.py owns execution and checkpointing."]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interval", type=float, default=1.0)
    args = parser.parse_args()
    try:
        while True:
            sys.stdout.write("\033[2J\033[H" + render() + "\n")
            sys.stdout.flush()
            time.sleep(max(0.25, args.interval))
    except KeyboardInterrupt:
        sys.stdout.write("\nDashboard stopped. Pilot process, if any, is unaffected.\n")


if __name__ == "__main__":
    main()
