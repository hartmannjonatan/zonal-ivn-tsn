#!/usr/bin/env python3
"""Live, single-screen progress panel for the isolated C4 final verification."""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "results"
LOADS = ("L0", "L1", "L2", "L3")
ALIGNS = ("A0", "A1")
SEEDS = (41, 43, 47)
VARIANTS = ("D3_fixed_TAS", "D3_fixed_noTAS")


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return default


def read_ledger(path: Path):
    rows = {}
    try:
        with path.open() as stream:
            for line in stream:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                logical = row.get("logical_execution_id") or row.get("execution_id")
                if logical:
                    rows[logical] = row
    except OSError:
        pass
    return rows


def read_log_tail(path: Path, max_bytes: int = 65536):
    try:
        with path.open("rb") as stream:
            size = stream.seek(0, os.SEEK_END)
            stream.seek(max(0, size - max_bytes))
            tail = stream.read().decode("utf-8", "replace")
        events = [line.strip() for line in tail.splitlines()
                  if "Event #" in line and "completed" in line]
        line = events[-1] if events else ""
        percent = re.search(r"(\d+)% completed", line)
        simtime = re.search(r"\bt=([0-9.eE+-]+)", line)
        age = max(0.0, time.time() - path.stat().st_mtime)
        return {
            "percent": percent.group(1) if percent else None,
            "simtime": simtime.group(1) if simtime else None,
            "log_bytes": size,
            "age_s": age,
        }
    except OSError:
        return None


def memory_available_gib():
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / 1024 / 1024
    except (OSError, ValueError):
        pass
    return None


def gate_text(sim, app, stability, sync):
    def mark(v):
        return "✓" if v is True else "✗" if v is False else "?"
    if any(v is False for v in (sim, app, stability, sync)):
        return f"FAIL sim{mark(sim)} app{mark(app)} stab{mark(stability)} sync{mark(sync)}"
    return f"PASS sim{mark(sim)} app{mark(app)} stab{mark(stability)} sync{mark(sync)}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interval", type=float, default=3.0,
                        help="refresh interval in seconds (default: 3)")
    parser.add_argument("--once", action="store_true", help="draw once and exit")
    args = parser.parse_args()

    manifest = read_json(HERE / "manifest.json", {})
    triage = read_json(HERE / "triage.json", {})
    reconciliation = read_json(OUT / "reconciliation_2026-10-22.json", {})
    reconciled = {row.get("logical_execution_id"): row
                  for row in reconciliation.get("executions", [])
                  if row.get("logical_execution_id")}
    reused_rows = manifest.get("reused_methodological_positions", [])
    reused = {}
    for row in reused_rows:
        # Some imported rows retain legacy execution IDs (D3_TAS/D3_noTAS).
        # Normalize by the preregistered position, which is the canonical identity.
        position = row.get("position", "")
        pieces = position.split("/")
        if len(pieces) == 3 and pieces[1].startswith("seed"):
            cell, seed = pieces[0], pieces[1][4:]
            variant = pieces[2]
            key = f"{variant}_{cell}_seed{seed}"
        else:
            key = row.get("execution_id")
        if key:
            reused[key] = row
    while True:
        cp = read_json(OUT / "checkpoint.json", {})
        ledger = read_ledger(OUT / "runs.jsonl")
        completed_new = set(cp.get("completed_new_logical_executions", []))
        completed_all = set(cp.get("completed_logical_executions", []))
        active = cp.get("active") or {}
        active_logical = active.get("logical_execution_id") or active.get("execution_id")
        active_id = active.get("execution_id")

        total_main = len(LOADS[:3]) * len(ALIGNS) * len(SEEDS) * len(VARIANTS)
        complete_ids = set(reused) | completed_new
        active_is_new = bool(active_logical and active_logical not in complete_ids)
        complete_count = len(complete_ids)
        active_count = 1 if active_is_new else 0
        pending_count = max(0, total_main - complete_count - active_count)

        if cp.get("phase2_complete") or cp.get("status") == "phase2_complete":
            phase = "Planned L0–L2 matrix complete"
        elif cp.get("phase1_complete"):
            phase = "Phase 2 — conditional seeds"
        elif cp:
            phase = "Phase 1 — initial cells and cross-checks"
        else:
            phase = "Not started"
        active_detail = "No active simulation"
        active_log = None
        if active:
            variant = active.get("variant", "")
            cell = active.get("cell", "")
            logical = active_logical or "unknown"
            attempt = active.get("attempt_number", "?")
            load, _, align = cell.partition("_")
            expected_log = f"Joint_{variant}_{load}_{align}.log"
            run_dir = OUT / "runs" / str(active_id or logical)
            candidates = [run_dir / expected_log]
            if not candidates[0].exists():
                candidates = list(run_dir.glob("*.log"))[:1]
            active_log = candidates[0] if candidates else None
            log_state = read_log_tail(active_log) if active_log else None
            if log_state and log_state["percent"] is not None:
                freshness = "" if log_state["age_s"] < 120 else " log sem atualização"
                active_detail = (f"{logical} | tentativa {attempt} | {log_state['percent']}%"
                                 f" | t={log_state['simtime'] or '?'} s / 31,05 s{freshness}")
            else:
                active_detail = f"{logical} | tentativa {attempt} | iniciando / aguardando log"

        if sys.stdout.isatty():
            sys.stdout.write("\033[2J\033[H")
        print("C4 — VERIFICAÇÃO EXPLORATÓRIA FINAL | D3 absoluto | exploratory=true")
        print("=" * 112)
        print(f"Checkpoint: {cp.get('status', 'missing')} | {phase} | último par: {cp.get('last_completed_pair', '—')}")
        print(f"Ativo: {active_detail}")
        print(f"L0–L2: {complete_count:2d}/36 completos ({len(reused)} reutilizados + {len(completed_new)} novos)"
              f" | {active_count} ativo | {pending_count} pendentes")
        l3_text = triage.get("L3", {}).get("interpretation", "triagem ausente")
        l3_rejected = "inadmissible" in l3_text.lower() or "inadmissível" in l3_text.lower()
        print(f"L3: {'12 posições rejeitadas antes da simulação' if l3_rejected else 'triagem/revisão necessária'}"
              f" | teto do estudo: 48 posições")
        free_gib = shutil.disk_usage(HERE).free / 1024**3
        mem_gib = memory_available_gib()
        mem_text = f"{mem_gib:.1f} GiB" if mem_gib is not None else "indisponível"
        print(f"Recursos: disco livre {free_gib:.1f} GiB | MemAvailable {mem_text}"
              f" | política do runner: máximo 1 simulador serial; neste momento sem simulador ativo")
        print("-" * 112)
        print(f"{'Célula / seed':<17} {'D3_fixed_TAS':<43} {'D3_fixed_noTAS':<43}")
        print("-" * 112)

        for load in LOADS:
            for align in ALIGNS:
                for seed in SEEDS:
                    cell = f"{load}_{align}"
                    row = f"{cell}/s{seed}"
                    states = []
                    for variant in VARIANTS:
                        logical = f"{variant}_{cell}_seed{seed}"
                        if load == "L3" and l3_rejected:
                            state = "REJECTED — triage"
                        elif logical == active_logical:
                            data = read_log_tail(active_log) if active_log else None
                            if data and data["percent"] is not None:
                                state = f"RUN {data['percent']}% t={data['simtime'] or '?'}s (try {active.get('attempt_number','?')})"
                            else:
                                state = "RUN starting"
                        elif logical in completed_new:
                            entry = ledger.get(logical, {})
                            # If the ledger is incomplete, use the per-run result once.
                            if not entry:
                                result_path = OUT / "runs" / logical / "pilot-result.json"
                                report = read_json(result_path, {})
                                entry = {
                                    "simulation_valid": report.get("simulation_valid"),
                                    "application_viable": report.get("application_viable"),
                                    "stability_viable": report.get("stability_viable"),
                                    "synchronization_sample_viable": report.get("synchronization_sample_viable"),
                                }
                            state = gate_text(entry.get("simulation_valid"), entry.get("application_viable"),
                                              entry.get("stability_viable"), entry.get("synchronization_sample_viable"))
                        elif logical in reused:
                            entry = reused[logical]
                            current = reconciled.get(logical)
                            if current:
                                state = gate_text(current.get("simulation_valid"), current.get("application_viable"),
                                                  current.get("stability_viable"), current.get("synchronization_sample_viable"))
                            else:
                                sync = entry.get("sync_sample_viable")
                                if sync is None and "pending_current_sync_reprocess" in str(entry.get("status", "")):
                                    suffix = "REUSE — sync pendente"
                                else:
                                    suffix = gate_text(entry.get("simulation_valid"), entry.get("application_viable"),
                                                       entry.get("stability_viable"), sync)
                                state = suffix
                        else:
                            # Preserve visibility of an interrupted directory while its replacement runs.
                            candidate_dirs = [OUT / "runs" / logical]
                            candidate_dirs += list((OUT / "runs").glob(logical + "_technical_attempt_*"))
                            if any(p.exists() and not (p / "pilot-result.json").exists() for p in candidate_dirs):
                                state = "PARTIAL / retry pending"
                            else:
                                state = "WAITING"
                        states.append(state)
                    print(f"{row:<17} {states[0]:<43.43} {states[1]:<43.43}")

        print("-" * 112)
        print("Status por execução: PASS/FAIL mostra simulação, aplicações, estabilidade e sincronização amostral (✓/✗/?).")
        print("L3 usa a triagem congelada; sincronização contínua segue não verificada. Ctrl-C fecha só o painel.")
        if active_log:
            print(f"Log ativo: {active_log}")
        print(f"Atualizado: {time.strftime('%Y-%m-%d %H:%M:%S')} | refresh {args.interval:g}s")
        sys.stdout.flush()
        if args.once:
            break
        try:
            time.sleep(max(0.5, args.interval))
        except KeyboardInterrupt:
            print("\nPainel fechado; a execução permanece independente do dashboard.")
            break


if __name__ == "__main__":
    main()
