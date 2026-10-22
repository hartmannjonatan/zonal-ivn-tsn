#!/usr/bin/env python3
"""Single-screen live dashboard for the isolated C4 shared-SP-brakes pilot."""
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


def live_resources():
    """Show current host headroom even before the runner has written a checkpoint."""
    try:
        free = os.statvfs(HERE)
        disk_gb = free.f_bavail * free.f_frsize / 1e9
    except OSError:
        disk_gb = None
    try:
        with open('/proc/meminfo', encoding='ascii') as stream:
            mem_kb = next(int(line.split()[1]) for line in stream if line.startswith('MemAvailable:'))
        memory_gb = mem_kb / 1024 / 1024
    except (OSError, StopIteration, ValueError):
        memory_gb = None
    safe_jobs = None if memory_gb is None else (0 if memory_gb < 7 else max(1, min(4, int(memory_gb // 5))))
    return disk_gb, memory_gb, safe_jobs


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
    variant_ids = manifest.get("variant_ids", {})
    byid = {r.get("execution_id"): r for r in rows}
    active = checkpoint.get("active", {}) or {}
    disk_gb, memory_gb, safe_jobs = live_resources()
    if safe_jobs is None: safe_jobs = checkpoint.get('current_safe_jobs')
    if safe_jobs is not None:
        # The host may have RAM for more jobs than this pilot permits. Show the
        # same capped value that the runner will actually use.
        safe_jobs = min(safe_jobs, checkpoint.get('max_parallel_runs', 1))
    if memory_gb is None: memory_gb = checkpoint.get('memory_available_gb')
    if disk_gb is None: disk_gb = checkpoint.get('free_gb')
    completed = sum(r.get("status") == "completed" for r in rows)
    failed = len(attempts)
    rejected = sum(r.get("status") == "rejected_before_execution" for r in rows)
    pending = [x for x in planned if x["execution_id"] not in byid]
    lines = [
        "C4 SHARED-SP-BRAKES PILOT  |  exploratory=true  |  official_c4_frozen=false",
        f"Updated: {time.strftime('%Y-%m-%d %H:%M:%S')}   Phase: {checkpoint.get('phase', 'not started')}",
        f"Completed: {completed}/{len(planned)}   Technical attempts: {failed}   Preflight rejections: {rejected}   Pending/retry: {len(pending)}",
        f"Jobs: {safe_jobs if safe_jobs is not None else '—'} safe now / {checkpoint.get('max_parallel_runs', 4)} cap   RAM: {memory_gb:.1f} GB available   Disk: {disk_gb:.1f} GB free (floor 45)" if memory_gb is not None and disk_gb is not None else f"Jobs: {safe_jobs if safe_jobs is not None else '—'} safe now / {checkpoint.get('max_parallel_runs', 4)} cap   RAM: {memory_gb if memory_gb is not None else '—'} GB   Disk: {disk_gb if disk_gb is not None else '—'} GB (floor 45)",
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
            variant = variant_ids.get(item.get('variant', ''), item.get('variant', ''))
            lines.append(f"{execution_id[:39]:39} {variant[:15]:15} {item.get('cell', '')} seed {item.get('seed', ''):<3} {state}")
    lines += ["", "EXECUTION SCHEDULE", "STATUS                     VARIANT          CELL/SEED      KIND"]
    lines.append("-" * 88)
    for spec in planned:
        row = byid.get(spec["execution_id"])
        status = row.get("status", "pending") if row else "pending"
        if row and row.get("status") == "completed":
            status += f" / app={'PASS' if row.get('application_viable') else 'FAIL'}"
            status += f" / total={'PASS' if row.get('pilot_viable') else 'FAIL'}"
        label = variant_ids.get(spec['variant'], spec['variant'])
        lines.append(f"{status[:26]:26} {label[:16]:16} {cell_label(spec):20} {spec['kind']}")
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
