#!/usr/bin/env python3
"""Final statistics (follow-up F6): 30 s measurement, seeds 1001-1010, L1/A0.

Configs: C0 (seeds 1001-1005 from Validate_C0_L1_A0_P1seeds, bit-identical to
the official campaign; 1006-1010 from C0_L1_A0_30s), T1S_C0_30s,
T1S_C0_PrioTo_30s, T1S_C0_TAS_30s, T1S_HYBRID_B6_30s. Per config and flow
(seeds pooled): measured packets, losses, deadline misses, mean, nearest-rank
p99, max. Hybrid body flows are added from their UdpSink delay vectors.
Output: markdown on stdout and simulations/zonal/t1s_results/final_30s.csv.
"""
import csv
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from compare_t1s import SIM, app_flow_map, read_vec  # noqa: E402
from t1s_hybrid_report import body_delays  # noqa: E402

RES = SIM / "zonal/t1s_results"
FINAL = SIM / "results/t1s/final"
SEEDS = list(range(1001, 1011))


def runs(label):
    """Yield (result_dir, run_dir, vec, network) for the 10 seeds of a config."""
    if label == "C0":
        for k, seed in enumerate(SEEDS[:5]):
            d = SIM / "results/t1s/C0_P1_L1_A0"
            yield d / f"Validate_C0_L1_A0_P1seeds-{k}", d / f"Validate_C0_L1_A0_P1seeds-seed={seed}-#0.vec", "ZonalIVN"
        for k, seed in enumerate(SEEDS[5:], start=5):
            d = FINAL / "C0_L1_A0_30s"
            yield d / f"C0_L1_A0_30s-{k}", d / f"C0_L1_A0_30s-seed={seed}-#0.vec", "ZonalIVN"
        return
    net = "ZonalIVNT1SHybrid" if "HYBRID" in label else "ZonalIVNT1S"
    for k, seed in enumerate(SEEDS):
        d = FINAL / label
        yield d / f"{label}-{k}", d / f"{label}-seed={seed}-#0.vec", net


def p99(v):
    v = sorted(v)
    return v[max(0, math.ceil(0.99 * len(v)) - 1)] if v else float("nan")


def main():
    flows = app_flow_map()
    labels = ["C0", "T1S_C0_30s", "T1S_C0_PrioTo_30s", "T1S_C0_TAS_30s", "T1S_HYBRID_B6_30s"]
    table = {}
    deadlines = {}
    for label in labels:
        agg = defaultdict(lambda: {"lat": [], "max": 0.0, "lost": 0, "miss": 0})
        up, down = [], []
        nseeds = 0
        for rd, vec, net in runs(label):
            if not vec.exists():
                continue
            nseeds += 1
            lat = read_vec(vec, net, flows)
            tx = {}
            for p in rd.glob("F*-tx.csv"):
                r = next(csv.DictReader(p.open()))
                tx[r["flow"]] = int(r["measured_packets"])
            for p in rd.glob("F*-rx.csv"):
                r = next(csv.DictReader(p.open()))
                key = (r["flow"], r["node"])
                a = agg[key]
                a["lat"] += lat.get(key, [])
                a["max"] = max(a["max"], float(r["max_latency"]))
                a["lost"] += tx[r["flow"]] - int(r["measured_packets"])
                a["miss"] += int(r["deadline_misses"])
                deadlines[key] = float(r["deadline_s"]) * 1e6
            if "HYBRID" in label:
                u, d = body_delays(vec)
                up += u
                down += d
        table[label] = (agg, up, down, nseeds)
    out = []
    keys = sorted({k for a, *_ in table.values() for k in a})
    head = " | ".join(f"{l.replace('_30s', '')}" for l in labels)
    print(f"Seeds per config: " + ", ".join(f"{l} {table[l][3]}" for l in labels))
    print(f"\nMax latency µs (misses / lost) per flow, 30 s, seeds pooled\n")
    print(f"| Flow | Rx | Deadline µs | {head} |")
    print("|---|---|---|" + "---|" * len(labels))
    for key in keys:
        cells = []
        for l in labels:
            a = table[l][0].get(key)
            if not a or not a["lat"]:
                cells.append("—")
                continue
            cells.append(f"{a['max'] * 1e6:.1f} ({a['miss']}/{a['lost']})")
            out.append({"config": l, "flow": key[0], "receiver": key[1], "deadline_us": deadlines.get(key, ""),
                        "samples": len(a["lat"]), "mean_us": round(sum(a["lat"]) / len(a["lat"]) * 1e6, 3),
                        "p99_us": round(p99(a["lat"]) * 1e6, 3), "max_us": round(a["max"] * 1e6, 3),
                        "lost": a["lost"], "misses": a["miss"]})
        print(f"| {key[0]} | {key[1]} | {deadlines.get(key, 0):.0f} | " + " | ".join(cells) + " |")
    _, up, down, _ = table["T1S_HYBRID_B6_30s"]
    for name, v in (("BODY_UP", up), ("BODY_DOWN", down)):
        if v:
            out.append({"config": "T1S_HYBRID_B6_30s", "flow": name, "receiver": "", "deadline_us": 10000,
                        "samples": len(v), "mean_us": round(sum(v) / len(v) * 1e6, 3), "p99_us": round(p99(v) * 1e6, 3),
                        "max_us": round(max(v) * 1e6, 3), "lost": "", "misses": sum(1 for x in v if x > 0.01)})
            print(f"\nHybrid {name.lower()}: {len(v)} packets, mean {sum(v) / len(v) * 1e6:.1f} µs, "
                  f"p99 {p99(v) * 1e6:.1f} µs, max {max(v) * 1e6:.1f} µs, misses (> 10 ms) {sum(1 for x in v if x > 0.01)}")
    print("\nRadar/window detail (mean / p99 / max µs):")
    for f in ("F06", "F07", "F15", "F16", "F17"):
        parts = []
        for l in labels:
            r = next((o for o in out if o["config"] == l and o["flow"] == f), None)
            if r:
                parts.append(f"{l.replace('_30s', '')} {r['mean_us']:.1f}/{r['p99_us']:.1f}/{r['max_us']:.1f}")
        print(f"- {f}: " + "; ".join(parts))
    with (RES / "final_30s.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)


if __name__ == "__main__":
    main()
