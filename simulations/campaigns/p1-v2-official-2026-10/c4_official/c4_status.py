#!/usr/bin/env python3
"""Read-only C4 progress dashboard; --watch clears and redraws one screen."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "results/C4"


def snapshot() -> dict:
    checkpoint_path = OUT / "checkpoint.json"
    ledger_path = OUT / "ledger.jsonl"
    template_path = HERE / "checkpoint_template.json"
    checkpoint = (json.loads(checkpoint_path.read_text()) if checkpoint_path.exists() else
                  json.loads(template_path.read_text()) if template_path.exists() else {})
    rows = []
    if ledger_path.exists():
        with ledger_path.open(encoding="utf-8") as stream:
            for line in stream:
                if line.strip():
                    rows.append(json.loads(line))
    ids = [r["execution_id"] for r in rows]
    if len(ids) != len(set(ids)):
        raise RuntimeError("duplicate execution IDs in C4 ledger; stop and audit before resuming")
    return checkpoint | {"ledger_rows": len(rows), "valid_rows": sum(r.get("status") == "completed_valid" for r in rows),
                         "nonviable_rows": sum(r.get("status") == "completed_valid" and not r.get("result_viable") for r in rows),
                         "technical_attempts": len((OUT / "technical_attempts.jsonl").read_text().splitlines()) if (OUT / "technical_attempts.jsonl").exists() else 0}


def render(data: dict) -> str:
    done = int(data.get("valid_rows", 0))
    expected = int(data.get("expected", 180))
    active = data.get("active") or {}
    if active:
        cell = f"{active.get('load', '?')}/{active.get('alignment', '?')} seed {active.get('seed', '?')}"
        percent = active.get("percent")
        running = f"{cell} | {percent if percent is not None else 'percentual indisponível'}% | PID {active.get('pid', '?')}"
    else:
        running = "nenhuma simulação ativa"
    resources = data.get("resources") or {}
    disk = resources.get("free_disk_gib", resources.get("free_disk_GiB", "n/d"))
    memory = resources.get("MemAvailable_gib", resources.get("MemAvailable_GiB", "n/d"))
    percent = 100 * done / expected if expected else 100
    return ("C4 oficial — snapshot isolado\n"
            f"Estado: {data.get('status', 'ainda não iniciado')} | fase: {data.get('phase', 'n/d')}\n"
            f"Concluídas válidas: {done}/{expected} ({percent:.1f}%) | reprovação válida: {data.get('nonviable_rows', 0)}\n"
            f"Ativa: {running}\n"
            f"Tentativas técnicas preservadas: {data.get('technical_attempts', 0)}\n"
            f"Disco livre: {disk} GiB | MemAvailable: {memory} GiB\n"
            f"Snapshot: {data.get('snapshot_id', 'n/d')} | campanha validada: {data.get('official_c4_validated', False)}\n"
            f"Atualizado: {data.get('updated_local', 'n/d')}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--watch", action="store_true", help="redraw the same terminal screen every 2 seconds")
    parser.add_argument("--interval", type=float, default=2.0)
    args = parser.parse_args()
    while True:
        try:
            data = snapshot()
            if args.watch:
                print("\033[2J\033[H", end="")
            print(render(data), flush=True)
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            print(f"C4 dashboard cannot read the checkpoint/ledger yet: {exc}", flush=True)
        if not args.watch:
            break
        time.sleep(max(0.5, args.interval))


if __name__ == "__main__":
    main()
