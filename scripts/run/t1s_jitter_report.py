#!/usr/bin/env python3
"""Latency jitter of the dual-bus and powertrain T1S flows.

For every flow (one vector per sink, or per request/response client) and run:
  - delay variation (PDV): max - min latency, and the standard deviation;
  - inter-arrival jitter: max |arrival_k - arrival_(k-1) - period| at the
    receiver, i.e. how far the readings drift from the sender period.
Seeds are pooled (PDV over all samples; inter-arrival over each run).
Deadlines: IEEE 802.1DG working-group reference for safety-relevant control,
1 ms MAC-to-MAC (README_t1s F1b), instead of the P1 100 us value.
Output: markdown on stdout, simulations/zonal/t1s_results/jitter_powertrain.csv
and jitter_dualbus.csv.
"""
import csv
import math
import re
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from compare_t1s import SIM  # noqa: E402
import gen_t1s_powertrain as G  # noqa: E402
from t1s_powertrain_report import app_index  # noqa: E402

RES = SIM / "zonal/t1s_results"
REF_US = 1000.0     # 802.1DG reference latency, safety-relevant control


def vectors(vec, want):
    """want(module, name) -> key or None. Returns {key: [(t, value_us), ...]} for this run."""
    ids, out = {}, defaultdict(list)
    with vec.open() as f:
        for line in f:
            if line.startswith("vector "):
                p = line.split()
                k = want(p[2], p[3])
                if k is not None:
                    ids[p[1]] = out[k]
            elif line[:1].isdigit():
                p = line.rstrip("\n").split("\t")
                if p[0] in ids:
                    ids[p[0]].append((float(p[2]), float(p[3]) * 1e6))
    return out


def stats(runs, period_us):
    lat = [v for r in runs for _, v in r]
    ia = 0.0
    for r in runs:
        ts = [t for t, _ in sorted(r)]
        for a, b in zip(ts, ts[1:]):
            ia = max(ia, abs((b - a) * 1e6 - period_us))
    if not lat:
        return None
    return {"samples": len(lat), "min_us": round(min(lat), 3), "mean_us": round(st.mean(lat), 3),
            "max_us": round(max(lat), 3), "pdv_us": round(max(lat) - min(lat), 3),
            "std_us": round(st.pstdev(lat), 3), "interarrival_jitter_us": round(ia, 3),
            "over_ref": sum(1 for v in lat if v > REF_US)}


def per_us(s):
    return float(s[:-2]) * (1000 if s.endswith("ms") else 1)


def powertrain():
    idx = app_index()
    rows = []
    for prof, col in G.PROFILES.items():
        runs = defaultdict(list)
        for vec in sorted((SIM / "results/t1s/T1S_PT").glob(f"T1S_PT_{prof}-seed=*-#*.vec")):
            def want(mod, name):
                m = re.search(r"\.(\w+)\.app\[(\d+)\](?:\.sink)?$", mod)
                return idx.get((m.group(1), int(m.group(2)), name)) if m else None
            for k, v in vectors(vec, want).items():
                runs[k].append(v)
        for fid, label, kind, a, b, *periods in G.FLOWS:
            s = stats(runs[fid], per_us(periods[col - 5]))
            if s:
                rows.append({"profile": prof, "flow": fid, "description": label,
                             "metric": "round-trip" if kind == "reqresp" else "one-way",
                             "path": "cross-bus" if G.ZONE_OF[a] != G.ZONE_OF[b] else "same bus",
                             "period_us": per_us(periods[col - 5]), **s})
    return rows


def dualbus():
    rows = []
    for plabel, period in (("1ms", 1000), ("200us", 200)):
        for n in (1, 3, 5):
            runs = defaultdict(list)
            for vec in sorted((SIM / "results/t1s/T1S_DUAL").glob(f"T1S_DUAL_{plabel}_S{n}-seed=*-#*.vec")):
                def want(mod, name):
                    m = re.search(r"\.ECU(\d)\.app\[\d+\]$", mod)
                    if m and name == "endToEndDelay:vector":
                        return "Z1->Z3" if m.group(1) == "3" else "Z3->Z1"
                    return None
                # one vector per sensor: keep them as separate runs for inter-arrival
                ids, out = {}, defaultdict(list)
                with vec.open() as f:
                    for line in f:
                        if line.startswith("vector "):
                            p = line.split()
                            k = want(p[2], p[3])
                            if k:
                                ids[p[1]] = []
                                runs[k].append(ids[p[1]])
                        elif line[:1].isdigit():
                            p = line.rstrip("\n").split("\t")
                            if p[0] in ids:
                                ids[p[0]].append((float(p[2]), float(p[3]) * 1e6))
            for k in ("Z1->Z3", "Z3->Z1"):
                s = stats(runs[k], period)
                if s:
                    rows.append({"period_us": period, "sensors_per_bus": n, "segment_nodes": 3 + n,
                                 "direction": k, **s})
    return rows


def main():
    pt, db = powertrain(), dualbus()
    print(f"Powertrain (802.1DG reference {REF_US:.0f} µs):\n")
    print("| Profile | Flow | Path | Metric | Period µs | Min / mean / max µs | PDV µs | Std µs | Inter-arrival jitter µs | > 1 ms |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for r in pt:
        print(f"| {r['profile']} | {r['flow']} {r['description']} | {r['path']} | {r['metric']} | {r['period_us']:.0f} | "
              f"{r['min_us']} / {r['mean_us']} / {r['max_us']} | {r['pdv_us']} | {r['std_us']} | {r['interarrival_jitter_us']} | {r['over_ref']} |")
    print("\nDual bus, cross-bus readings:\n")
    print("| Period µs | Nodes/bus | Direction | Min / mean / max µs | PDV µs | Std µs | Inter-arrival jitter µs | > 1 ms |")
    print("|---|---|---|---|---|---|---|---|")
    for r in db:
        print(f"| {r['period_us']} | {r['segment_nodes']} | {r['direction']} | {r['min_us']} / {r['mean_us']} / {r['max_us']} | "
              f"{r['pdv_us']} | {r['std_us']} | {r['interarrival_jitter_us']} | {r['over_ref']} |")
    for name, rows in (("jitter_powertrain.csv", pt), ("jitter_dualbus.csv", db)):
        if rows:
            with (RES / name).open("w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0]))
                w.writeheader()
                w.writerows(rows)


if __name__ == "__main__":
    main()
