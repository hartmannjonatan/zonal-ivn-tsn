#!/usr/bin/env python3
"""Build a Fever-style CAN flow set (JSON) from an oscilloscope CAN capture.

Port of plca-priority-to's scripts/gen_flows.py (Copyright (C) 2026 Jean Carlos
Macedo, LGPL-3.0-or-later) for new captures, with three changes:
  * the ID width is read from the digit count (8 hex digits = 29-bit, 3 = 11-bit),
    not from the numeric value;
  * default period = median inter-arrival snapped to standard values (as in
    gen_flows.py); --period-method robust instead divides every gap by its
    nearest integer multiple of the lower-quartile gap, which recovers the period
    when frames are missing from the capture (gaps of 2x, 3x... the period) but
    over-estimates the rate of sporadic IDs; IDs with irregular gaps
    ((max-min)/median >= 0.2) are marked "regular": false either way;
  * it never overwrites an existing file: the default output is
    simulations/zonal/traffic/fever/flows_<capture-name>.json.

Output fields are those of flows.json (id, period_ms, deadline_ms, phase_ms, dlc,
class, count_in_trace, index, length_B) plus id_bits, median_gap_ms and
missing_frames_est. CRITICAL = the gateway's critical CAN IDs of plca-priority-to.

usage: fever_gen_flows.py CAPTURE.csv [--out FILE] [--critical ID,ID,...]
"""
import argparse
import csv
import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CRITICAL = {"18FF95EF", "18FE2895", "18FF2895", "18FF9528", "18FFA738", "18FFA7EF",
            "18FF28A7", "18FFEFA7", "18FD50A7", "18FF50A7", "18FE50A7", "18FF1EEF"}
STD_PERIODS_MS = [1, 2, 5, 10, 20, 25, 40, 50, 100, 200, 250, 300, 400, 500, 600, 1000, 2000, 5000]
BASE_LEN = 46


def t_seconds(s):
    s = s.strip()
    for suf, k in (("ms", 1e-3), ("us", 1e-6), ("ns", 1e-9), ("s", 1.0)):
        if s.endswith(suf):
            return float(s[:-len(suf)]) * k
    return float(s)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("capture")
    ap.add_argument("--out")
    ap.add_argument("--critical", help="comma-separated CAN IDs (default: plca-priority-to list)")
    ap.add_argument("--period-method", choices=["median", "robust"], default="median")
    a = ap.parse_args()
    cap = Path(a.capture)
    out = Path(a.out) if a.out else ROOT / f"simulations/zonal/traffic/fever/flows_{cap.stem}.json"
    if out.exists():
        raise SystemExit(f"{out} exists; refusing to overwrite (choose --out)")
    critical = set(a.critical.upper().split(",")) if a.critical else CRITICAL

    rows = []
    with cap.open(newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(line.replace("\r", "") for line in f):
            if r.get("ID") and r.get("Time"):
                rows.append((t_seconds(r["Time"]), r["ID"].strip().upper(), int(r.get("DLC") or 8)))
    t0 = min(t for t, _, _ in rows)
    span = max(t for t, _, _ in rows) - t0
    by_id = {}
    for t, i, dlc in rows:
        by_id.setdefault(i, []).append((t - t0, dlc))

    flows = []
    for i, ev in sorted(by_id.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        ts = sorted(t for t, _ in ev)
        gaps = [(b - a) * 1e3 for a, b in zip(ts, ts[1:])]
        if gaps:
            med = statistics.median(gaps)
            regular = (max(gaps) - min(gaps)) / med < 0.2
            if a.period_method == "robust":
                base = sorted(gaps)[len(gaps) // 4]             # lower quartile: one period
                p_raw = statistics.median(g / max(1, round(g / base)) for g in gaps)
            else:
                p_raw = med
            period = min(STD_PERIODS_MS, key=lambda x: abs(x - p_raw))
            missing = sum(max(1, round(g / period)) - 1 for g in gaps)
        else:
            p_raw, period, missing, regular = None, max(1000, round(span * 1000)), 0, None
        flows.append({"id": i, "id_bits": 29 if len(i) > 3 else 11, "period_ms": period, "deadline_ms": period,
                      "phase_ms": round(ts[0] * 1e3 % period, 3), "dlc": ev[0][1],
                      "class": "CRITICAL" if i in critical else "OTHER", "count_in_trace": len(ts),
                      "median_gap_ms": round(p_raw, 3) if p_raw else None, "regular": regular,
                      "missing_frames_est": missing})
    for k, fl in enumerate(flows):
        fl["index"] = k
        fl["length_B"] = BASE_LEN + k
    out.write_text(json.dumps(flows, indent=1))
    print(f"{cap.name}: {len(rows)} frames over {span:.3f} s, {len(flows)} IDs, "
          f"{sum(1000 / f['period_ms'] for f in flows):.0f} frames/s modelled, "
          f"{sum(f['missing_frames_est'] for f in flows)} frames estimated missing, "
          f"{sum(1 for f in flows if f['regular'] is False)} irregular IDs -> {out}")


if __name__ == "__main__":
    main()
