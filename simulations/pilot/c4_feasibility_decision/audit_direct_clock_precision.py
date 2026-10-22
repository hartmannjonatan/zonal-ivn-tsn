#!/usr/bin/env python3
"""Recompute observed clock offsets from native simultaneous ClockPrecisionProbe ticks.

This deliberately does not interpolate between samples or replace the legacy
vector-derived synchronization field. It reports the two populations
separately: 1 ms periodic samples and all direct probe records.
"""
from __future__ import annotations

import csv
import gzip
import json
import math
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "simulations/pilot/c4_feasibility_decision/results/direct_clock_audit.json"
RUNS = ROOT / "simulations/pilot/c4_feasibility_decision/results/runs"
HIST = ROOT / "simulations/pilot/c4_real_clock_service_margin_corrected/results/runs"
NODES = ("CSW", "Z1.ZSW", "Z2.ZSW", "Z3.ZSW")
START_RAW = 1_000_000_000_000  # simtime ticks at 1 ps precision
STOP_RAW = 31_000_000_000_000
THRESHOLD_S = 1e-6


def quantile(values: list[int], q: float) -> int | None:
    if not values:
        return None
    vals = sorted(abs(v) for v in values)
    return vals[max(0, math.ceil(q * len(vals)) - 1)]


def summarize(path: Path) -> dict:
    opener = gzip.open if path.suffix == ".gz" else open
    exact_scale_exp = None
    rows = {"periodic": {n: [] for n in NODES}, "all_direct_records": {n: [] for n in NODES}}
    maxima = {pop: {n: {"abs_raw": -1, "simtime_raw": None, "signed_raw": None,
                        "event_number": None, "sequence": None, "record_kind": None}
                    for n in NODES} for pop in rows}
    warmup = {n: None for n in NODES}
    periodic_times = []
    population_counts = {"periodic": 0, "all_direct_records": 0}
    with opener(path, "rt", newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        required = {"sequence", "event_number", "simtime_raw", "simtime_scale_exp", "record_kind"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(f"Unexpected ClockPrecisionProbe schema: {reader.fieldnames}")
        for row in reader:
            if row.get("record_kind") not in rows:
                continue
            t = int(row["simtime_raw"])
            exp = int(row["simtime_scale_exp"])
            if exact_scale_exp is None:
                exact_scale_exp = exp
            if exp != exact_scale_exp:
                raise ValueError("Mixed simtime scale exponents")
            if row.get("record_kind") == "periodic" and t <= START_RAW:
                for node in NODES:
                    raw = int(row[f"{node}_offset_from_HPC_raw"])
                    if warmup[node] is None or t > warmup[node]["simtime_raw"]:
                        warmup[node] = {"simtime_raw": t, "offset_raw": raw}
            if not START_RAW <= t < STOP_RAW:
                continue
            pop = row["record_kind"]
            population_counts[pop] += 1
            for node in NODES:
                raw = int(row[f"{node}_offset_from_HPC_raw"])
                if pop == "periodic":
                    rows[pop][node].append(raw)
                    if node == NODES[0]:
                        periodic_times.append(t)
                rows["all_direct_records"][node].append(raw)
                for which in ({pop} if pop == "periodic" else set()) | {"all_direct_records"}:
                    m = maxima[which][node]
                    if abs(raw) > m["abs_raw"]:
                        maxima[which][node] = {"abs_raw": abs(raw), "simtime_raw": t,
                                               "signed_raw": raw, "event_number": int(row["event_number"]),
                                               "sequence": int(row["sequence"]), "record_kind": pop}
    if exact_scale_exp is None:
        raise ValueError("No direct clock samples in [1,31)")
    scale = 10.0 ** exact_scale_exp
    threshold_raw = round(THRESHOLD_S / scale)
    result = {"path": str(path.relative_to(ROOT)), "sha256": __import__("hashlib").sha256(path.read_bytes()).hexdigest(),
              "window_s": [1, 31], "scale_exp": exact_scale_exp, "tick_s": scale,
              "definition": "corrected_clock_i_raw - corrected_HPC_raw captured simultaneously in ClockPrecisionProbe before serialization",
              "threshold_1us_raw": threshold_raw,
              "periodic_sample_resolution_median_s": (statistics.median([b-a for a,b in zip(periodic_times, periodic_times[1:])]) * scale if len(periodic_times)>1 else None),
              "populations": {}}
    for pop, per_node in rows.items():
        result["populations"][pop] = {"count_per_probe_record": population_counts["periodic"] if pop == "periodic" else population_counts["all_direct_records"], "nodes": {}}
        for node, values in per_node.items():
            maxrow = maxima[pop][node]
            result["populations"][pop]["nodes"][node] = {
                "samples": len(values), "max_abs_offset_s": maxrow["abs_raw"] * scale,
                "max_abs_offset_us": maxrow["abs_raw"] * scale * 1e6,
                "max_sample": maxrow,
                "p99_abs_offset_s": (quantile(values, .99) * scale) if values else None,
                "samples_abs_gt_1us": sum(abs(v) > threshold_raw for v in values),
                "max_warmup_end_periodic_sample": ({"simtime_raw": warmup[node]["simtime_raw"],
                    "offset_raw": warmup[node]["offset_raw"], "offset_s": warmup[node]["offset_raw"] * scale,
                    "offset_us": warmup[node]["offset_raw"] * scale * 1e6}
                    if pop == "periodic" and warmup[node] else None),
            }
    return result


def main() -> int:
    targets = []
    for d in (RUNS, HIST):
        if not d.exists():
            continue
        for p in sorted(d.glob("**/clock_precision.csv*")):
            # Reused controls and finalized study executions only, excluding zero-time preflights.
            if "preflight" in str(p):
                continue
            if d == HIST or d == RUNS:
                targets.append(p)
    rows = []
    errors = []
    for p in targets:
        try:
            rows.append(summarize(p))
        except Exception as exc:
            errors.append({"path": str(p.relative_to(ROOT)), "error": str(exc)})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"derived_from_native_simultaneous_ticks": True,
                               "continuous_conformance": "not_verified",
                               "legacy_vector_audit_preserved_separately": True,
                               "runs": rows, "errors": errors}, indent=2) + "\n")
    print(json.dumps({"output": str(OUT.relative_to(ROOT)), "runs": len(rows), "errors": errors}, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
