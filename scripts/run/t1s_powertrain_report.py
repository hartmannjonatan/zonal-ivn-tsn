#!/usr/bin/env python3
"""Report the powertrain dual-bus T1S scenario.

Per profile and powertrain flow (PT01..PT10): one-way latency (endToEndDelay at
the sink) or request/response round-trip time (roundTripTime at the client),
seeds pooled; plus the catalog flows sharing the path (brake F08-F10 at PCP 7,
radar F06/F07, windows F15/F17). Output: markdown on stdout and
simulations/zonal/t1s_results/powertrain.csv.
"""
import csv
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from compare_t1s import SIM  # noqa: E402
import gen_t1s_powertrain as G  # noqa: E402

RES = SIM / "zonal/t1s_results"
RDIR = SIM / "results/t1s/T1S_PT"
CAT = ("F06", "F07", "F08", "F09", "F10", "F15", "F17")


def p99(v):
    v = sorted(v)
    return v[max(0, math.ceil(0.99 * len(v)) - 1)] if v else float("nan")


def app_index():
    """(node, app index) -> (flow id, metric) for the vectors to read."""
    out = {}
    per = defaultdict(int)
    for fid, label, kind, a, b, *_ in G.FLOWS:
        ia = per[a]; per[a] += 1
        ib = per[b]; per[b] += 1
        if kind == "oneway":
            out[(b, ib, "endToEndDelay:vector")] = fid
        else:
            out[(a, ia, "roundTripTime:vector")] = fid
    return out


def read(vec, idx):
    ids, out = {}, defaultdict(list)
    with vec.open() as f:
        for line in f:
            if line.startswith("vector "):
                parts = line.split()
                m = re.search(r"\.(\w+)\.app\[(\d+)\](?:\.sink)?$", parts[2])
                if m:
                    key = (m.group(1), int(m.group(2)), parts[3])
                    if key in idx:
                        ids[parts[1]] = out[idx[key]]
            elif line[:1].isdigit():
                f0 = line.split("\t", 1)[0]
                if f0 in ids:
                    ids[f0].append(float(line.rsplit("\t", 1)[1]) * 1e6)
    return out


def main():
    idx = app_index()
    rows = []
    for prof, col in G.PROFILES.items():
        cfg = f"T1S_PT_{prof}"
        scas = sorted(RDIR.glob(f"{cfg}-seed=*-#*.sca"))
        if not scas:
            continue
        lat = defaultdict(list)
        cat = defaultdict(lambda: {"max": 0.0, "lost": 0, "miss": 0})
        for sca in scas:
            for k, v in read(sca.with_suffix(".vec"), idx).items():
                lat[k] += v
            text = sca.read_text(errors="replace")
            run = re.search(r'^attr runnumber "?(\d+)', text, re.M).group(1)
            rd = RDIR / f"{cfg}-{run}"
            tx = {}
            for p in rd.glob("F*-tx.csv"):
                r = next(csv.DictReader(p.open()))
                tx[r["flow"]] = int(r["measured_packets"])
            for p in rd.glob("F*-rx.csv"):
                r = next(csv.DictReader(p.open()))
                if r["flow"] in CAT:
                    a = cat[r["flow"]]
                    a["max"] = max(a["max"], float(r["max_latency"]) * 1e6)
                    a["lost"] += tx[r["flow"]] - int(r["measured_packets"])
                    a["miss"] += int(r["deadline_misses"])
        for fid, label, kind, a, b, *periods in G.FLOWS:
            period = periods[col - 5]
            per_us = float(period[:-2]) * (1000 if period.endswith("ms") else 1)
            v = lat[fid]
            cross = G.ZONE_OF[a] != G.ZONE_OF[b]
            rows.append({"profile": prof, "flow": fid, "description": label, "kind": kind,
                         "path": "cross-bus" if cross else "same bus", "period_us": per_us,
                         "samples": len(v), "mean_us": round(sum(v) / len(v), 3) if v else "",
                         "p99_us": round(p99(v), 3) if v else "", "max_us": round(max(v), 3) if v else "",
                         "over_100us": sum(1 for x in v if x > 100), "over_period": sum(1 for x in v if x > per_us)})
        for f in CAT:
            rows.append({"profile": prof, "flow": f, "description": "catalog flow", "kind": "catalog", "path": "",
                         "period_us": "", "samples": "", "mean_us": "", "p99_us": "", "max_us": round(cat[f]["max"], 3),
                         "over_100us": cat[f]["miss"], "over_period": cat[f]["lost"]})
    print("| Profile | Flow | Description | Path | Period µs | Samples | Mean / p99 / max µs | > 100 µs | > period |")
    print("|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        if r["kind"] == "catalog":
            continue
        print(f"| {r['profile']} | {r['flow']} | {r['description']} | {r['path']} | {r['period_us']:.0f} | {r['samples']} | "
              f"{r['mean_us']} / {r['p99_us']} / {r['max_us']} | {r['over_100us']} | {r['over_period']} |")
    print("\nCatalog flows (max µs, misses, lost):")
    for r in rows:
        if r["kind"] == "catalog":
            print(f"- {r['profile']} {r['flow']}: {r['max_us']} µs, misses {r['over_100us']}, lost {r['over_period']}")
    if rows:
        with (RES / "powertrain.csv").open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)


if __name__ == "__main__":
    main()
