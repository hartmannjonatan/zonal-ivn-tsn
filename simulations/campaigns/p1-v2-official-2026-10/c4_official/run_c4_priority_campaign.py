#!/usr/bin/env python3
"""Run a predeclared C4 preview subset first, then the full frozen matrix.

This wrapper changes execution order only. It leaves the official matrix,
snapshot inputs, treatments, and 180-position denominator unchanged.
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_c4_campaign as runner

PRIORITY_CELLS = (("L1", "A1"), ("L2", "A0"), ("L2", "A1"))
PRIORITY_SEEDS = (1001, 1015, 1030)
OUT = runner.OUT


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def prepare_priority_order() -> Path:
    official_rows = runner.position_rows()
    ids = [row["execution_id"] for row in official_rows]
    if len(official_rows) != 180 or len(set(ids)) != 180:
        raise RuntimeError("official C4 matrix must contain 180 unique positions")

    by_id = {row["execution_id"]: row for row in official_rows}
    priority_ids = [
        f"C4_{load}_{alignment}_seed{seed}"
        for seed in PRIORITY_SEEDS
        for load, alignment in PRIORITY_CELLS
    ]
    missing = [execution_id for execution_id in priority_ids if execution_id not in by_id]
    if missing:
        raise RuntimeError(f"priority positions missing from official matrix: {missing}")

    ordered_ids = priority_ids + [execution_id for execution_id in ids if execution_id not in set(priority_ids)]
    ordered_rows = [by_id[execution_id] for execution_id in ordered_ids]
    schedule_dir = OUT / "execution-order-amendments"
    schedule_dir.mkdir(parents=True, exist_ok=True)
    matrix_path = schedule_dir / "priority_matrix_2026-10-27.csv"
    with matrix_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(official_rows[0]))
        writer.writeheader()
        writer.writerows(ordered_rows)

    manifest_path = schedule_dir / "priority_order_2026-10-27.json"
    content = {
        "amendment": "execution-order-only; no treatment, workload, matrix membership, or acceptance-rule changes",
        "campaign_snapshot_id": json.loads(runner.MANIFEST.read_text())["snapshot_id"],
        "official_matrix_sha256": sha256(runner.MATRIX),
        "priority_matrix_sha256": sha256(matrix_path),
        "priority_cells": [f"{load}/{alignment}" for load, alignment in PRIORITY_CELLS],
        "priority_seeds": list(PRIORITY_SEEDS),
        "priority_execution_ids": priority_ids,
        "priority_positions": len(priority_ids),
        "total_positions": len(ordered_rows),
        "interpretation": "early descriptive coverage only; not a replacement for the 30-seed official matrix or evidence of general viability",
        "wrapper_sha256": sha256(Path(__file__).resolve()),
    }
    encoded = json.dumps(content, indent=2, sort_keys=True) + "\n"
    if manifest_path.exists() and manifest_path.read_text(encoding="utf-8") != encoded:
        raise RuntimeError(f"existing priority-order amendment differs: {manifest_path}")
    if not manifest_path.exists():
        manifest_path.write_text(encoded, encoding="utf-8")

    # The frozen runner continues to validate the canonical matrix hash in the
    # manifest. Only its in-memory row order is redirected to this verified
    # permutation; every original row and calendar signature remains intact.
    runner.MATRIX = matrix_path
    if runner.position_rows() != ordered_rows:
        raise RuntimeError("priority schedule failed round-trip validation")
    return manifest_path


def main() -> None:
    if len(sys.argv) < 2 or "--run" not in sys.argv or "--resume" not in sys.argv:
        raise SystemExit("usage: run_c4_priority_campaign.py --run --resume --jobs 1")
    if "--reprocess-existing-only" in sys.argv:
        raise SystemExit("priority wrapper is only for resuming the full matrix")
    amendment = prepare_priority_order()
    print(f"Execution-order amendment: {amendment}", flush=True)
    print("The first nine uncompleted positions are the predeclared three-seed sample; the remaining official matrix follows.", flush=True)
    runner.main()


if __name__ == "__main__":
    main()
