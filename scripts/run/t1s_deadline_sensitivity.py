#!/usr/bin/env python3
"""Deadline sensitivity of the T1S scenarios, from existing summary CSVs only.

For every scenario/mode and flow class (radar F06-F07, brake F08-F10,
window F15-F17) it reports the minimum deadline that would give zero misses
(the observed max latency over the class; infinite if any packet was lost)
and pass/fail at 100 us, 150 us, 250 us, 500 us and 1 ms.

Inputs: simulations/zonal/t1s_results/*.csv. Output: markdown on stdout and
simulations/zonal/t1s_results/deadline_sensitivity.csv.
"""
import csv
import math
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RES = ROOT / "simulations/zonal/t1s_results"
CLASSES = {"radar": ("F06", "F07"), "brake": ("F08", "F09", "F10"), "window": ("F15", "F16", "F17")}
DEADLINES_US = (100, 150, 250, 500, 1000)


def rows(name):
    with (RES / name).open() as f:
        return list(csv.DictReader(f))


def collect():
    """Yield (scenario, mode, flow, max_us, lost)."""
    for r in rows("c0_vs_t1s_L1_A0.csv"):
        yield "Baseline L1/A0", "C0 (100 Mb/s links)", r["flow"], float(r["c0_max_us"]), int(r["c0_lost"])
        yield "T1S L1/A0", "standard", r["flow"], float(r["t1s_max_us"]), int(r["t1s_lost"])
    for r in rows("c0_vs_t1s_L1_A1.csv"):
        yield "T1S L1/A1", "standard", r["flow"], float(r["t1s_max_us"]), int(r["t1s_lost"])
    for name, mode in (("radar_phase_standard.csv", "standard"), ("radar_phase_priorityTo.csv", "priorityTo"),
                       ("radar_phase_multiTo.csv", "multiTo")):
        for r in rows(name):
            if not 45 <= int(r["radar_offset_us"]) <= 130:
                continue  # common band of all three sweeps
            for f in ("F06", "F07"):
                yield "T1S radar phase sweep 45-130 us", mode, f, float(r[f"{f}_max_us"]), int(r[f"{f}_lost"])
    brake_modes = {"T1S_BRAKE": "standard", "T1S_BRAKE_BC3": "burst max_bc=3", "T1S_BRAKE_PrioTo": "priorityTo radar",
                   "T1S_BRAKE_MultiToCoord": "multiTo coord", "T1S_BRAKE_MultiToCoordRadar": "multiTo coord+radar"}
    for r in rows("brake_modes.csv"):
        yield "T1S + brake on segment", brake_modes[r["config"]], r["flow"], float(r["max_us"]), int(r["lost"])
    for r in rows("extra_nodes_modes.csv"):
        if r["flow"] == "X":
            continue
        profile, mode = r["config"].removeprefix("T1S_EXTRA_").split("_")
        nodes = 3 + int(r["extra"])
        yield f"T1S + {profile.lower()} nodes, {nodes} per segment", mode.replace("Std", "standard").replace(
            "PrioTo", "priorityTo").replace("MultiTo", "multiTo"), r["flow"], float(r["max_us"]), int(r["lost"])


def main():
    agg = defaultdict(lambda: {"max": 0.0, "lost": 0})
    order = []
    for scenario, mode, flow, mx, lost in collect():
        for cls, flows in CLASSES.items():
            if flow in flows:
                key = (scenario, mode, cls)
                if key not in agg:
                    order.append(key)
                agg[key]["max"] = max(agg[key]["max"], mx)
                agg[key]["lost"] += lost
    out = []
    print("| Scenario | Mode | Class | Min. deadline for 0 misses | " + " | ".join(
        f"{d} µs" if d < 1000 else "1 ms" for d in DEADLINES_US) + " |")
    print("|---|---|---|---|" + "---|" * len(DEADLINES_US))
    for key in order:
        a = agg[key]
        need = math.inf if a["lost"] else a["max"]
        verdict = ["pass" if need <= d else "fail" for d in DEADLINES_US]
        need_txt = f"∞ (lost {a['lost']})" if a["lost"] else (f"{need:.1f} µs" if need < 1000 else f"{need / 1000:.2f} ms")
        print(f"| {key[0]} | {key[1]} | {key[2]} | {need_txt} | " + " | ".join(verdict) + " |")
        out.append({"scenario": key[0], "mode": key[1], "class": key[2], "max_latency_us": round(a["max"], 3),
                    "lost": a["lost"], "min_deadline_us": "inf" if a["lost"] else round(need, 3),
                    **{f"pass_{d}us": v == "pass" for d, v in zip(DEADLINES_US, verdict)}})
    with (RES / "deadline_sensitivity.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)


if __name__ == "__main__":
    main()
