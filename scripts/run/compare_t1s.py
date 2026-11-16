#!/usr/bin/env python3
"""Compare per-flow QoS of C0 on ZonalIVN and ZonalIVNT1S (10BASE-T1S variant).

Inputs are the paired runs of simulations/zonal/configs/t1s.ini
(configs C0_L1_A0_2s and T1S_C0). Per receiver it uses:
  - CatalogUdpApp receiver/talker CSVs (measured packets, deadline misses, max);
  - the application latency:vector (measured cohort only) for mean and the
    nearest-rank p99, pooled over seeds;
  - TrafficAudit drops.csv for queue overflow drops.
Losses = talker measured packets - receiver measured packets.
"""
import argparse
import csv
import math
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SIM = ROOT / "simulations"


def app_flow_map():
    mapping = {}
    pat = re.compile(r"^\*\.([A-Za-z0-9_.]+)\.app\[(\d+)\]\.flowId\s*=\s*(\d+)")
    for line in (SIM / "zonal/configs/catalog-bindings.ini").read_text().splitlines():
        m = pat.match(line.strip())
        if m:
            mapping[(m.group(1), int(m.group(2)))] = f"F{int(m.group(3)):02d}"
    return mapping


def read_vec(path, network, flows):
    ids = {}
    samples = defaultdict(list)
    with path.open() as f:
        for line in f:
            if line.startswith("vector "):
                parts = line.split()
                m = re.fullmatch(re.escape(network) + r"\.(.*)\.app\[(\d+)\]", parts[2])
                if m and parts[3] == "latency:vector":
                    key = (m.group(1), int(m.group(2)))
                    if key in flows:
                        ids[parts[1]] = (flows[key], m.group(1))
            elif line[:1].isdigit():
                vid, _, _, value = line.split("\t")
                if vid in ids:
                    samples[ids[vid]].append(float(value))
    return samples


def read_csv(path):
    with path.open() as f:
        return list(csv.DictReader(f))


def collect(config, network, seeds, base):
    flows = app_flow_map()
    per = defaultdict(lambda: {"lat": [], "tx": 0, "rx": 0, "miss": 0, "max": 0.0,
                               "deadline": None, "per_seed": []})
    drops = defaultdict(int)
    for run, seed in enumerate(seeds):
        rd = base / f"{config}-{run}"
        vec = base / f"{config}-seed={seed}-#0.vec"
        lat = read_vec(vec, network, flows)
        tx = {}
        for p in rd.glob("F*-tx.csv"):
            row = read_csv(p)[0]
            tx[row["flow"]] = int(row["measured_packets"])
        for p in sorted(rd.glob("F*-rx.csv")):
            row = read_csv(p)[0]
            key = (row["flow"], row["node"])
            d = per[key]
            rx = int(row["measured_packets"])
            values = lat.get(key, [])
            if len(values) != rx:
                raise SystemExit(f"{config} seed {seed} {key}: {len(values)} latency samples vs {rx} measured")
            d["lat"] += values
            d["tx"] += tx[row["flow"]]
            d["rx"] += rx
            d["miss"] += int(row["deadline_misses"])
            d["max"] = max(d["max"], float(row["max_latency"]))
            d["deadline"] = float(row["deadline_s"])
            d["per_seed"].append((seed, tx[row["flow"]] - rx, int(row["deadline_misses"]), float(row["max_latency"])))
        for row in read_csv(rd / "drops.csv"):
            drops[row["flow"]] += int(row["packets"])
    return per, drops


def summarize(d):
    v = sorted(d["lat"])
    n = len(v)
    return {
        "samples": n,
        "mean_us": sum(v) / n * 1e6 if n else float("nan"),
        "p99_us": v[max(0, math.ceil(0.99 * n) - 1)] * 1e6 if n else float("nan"),
        "max_us": d["max"] * 1e6,
        "lost": d["tx"] - d["rx"],
        "misses": d["miss"],
        "deadline_us": (d["deadline"] or 0) * 1e6,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seeds", default="1001,1002,1003")
    ap.add_argument("--base", default="C0_L1_A0_2s:results/t1s/C0:ZonalIVN",
                    help="config:result-dir:network of the reference runs")
    ap.add_argument("--t1s", default="T1S_C0:results/t1s/T1S_C0:ZonalIVNT1S",
                    help="config:result-dir:network of the T1S runs")
    ap.add_argument("--out", default=str(SIM / "results/t1s/comparison.csv"))
    args = ap.parse_args()
    seeds = [int(s) for s in args.seeds.split(",")]
    bc, bd, bn = args.base.split(":")
    tc, td, tn = args.t1s.split(":")
    base, base_drops = collect(bc, bn, seeds, SIM / bd)
    t1s, t1s_drops = collect(tc, tn, seeds, SIM / td)
    rows = []
    for key in sorted(set(base) | set(t1s)):
        a, b = summarize(base[key]), summarize(t1s[key])
        rows.append({"flow": key[0], "receiver": key[1], "deadline_us": a["deadline_us"],
                     **{f"c0_{k}": v for k, v in a.items() if k != "deadline_us"},
                     **{f"t1s_{k}": v for k, v in b.items() if k != "deadline_us"},
                     "c0_queue_drops": base_drops.get(key[0], 0),
                     "t1s_queue_drops": t1s_drops.get(key[0], 0)})
    with open(args.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print("| Flow | Rx | Deadline µs | Mean µs C0 → T1S | p99 µs C0 → T1S | Max µs C0 → T1S | Lost C0/T1S | Misses C0/T1S | Drops C0/T1S |")
    print("|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        print(f"| {r['flow']} | {r['receiver']} | {r['deadline_us']:.0f} | {r['c0_mean_us']:.2f} → {r['t1s_mean_us']:.2f} | "
              f"{r['c0_p99_us']:.2f} → {r['t1s_p99_us']:.2f} | {r['c0_max_us']:.2f} → {r['t1s_max_us']:.2f} | "
              f"{r['c0_lost']}/{r['t1s_lost']} | {r['c0_misses']}/{r['t1s_misses']} | {r['c0_queue_drops']}/{r['t1s_queue_drops']} |")


if __name__ == "__main__":
    main()
