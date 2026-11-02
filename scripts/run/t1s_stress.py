#!/usr/bin/env python3
"""Summarize T1S stress runs (T1S_BRAKE, T1S_BRAKE_BC3, T1S_EXTRA_*, T1S_C0...).

For each config, runs are grouped by their iteration variables except the
seed; per group and flow it pools latency samples over seeds (mean,
nearest-rank p99), and reports max latency, deadline misses and losses
(talker minus receiver measured packets). It also reports, per zonal switch
PLCA port, the max queue length per traffic class, the time-average queue
bits, and TrafficAudit queue drops, plus packets HPC received from the extra
T1S nodes (UdpSinkApp app[20]).

usage: t1s_stress.py CONFIG[:RESULTDIR] ... [--flows F06,F07,...]
"""
import argparse
import csv
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from compare_t1s import SIM, app_flow_map, read_vec  # noqa: E402


def parse_sca(path):
    attrs, itervars, scalars = {}, {}, {}
    for line in path.read_text(errors="replace").splitlines():
        if line.startswith("attr "):
            _, k, v = line.split(" ", 2)
            attrs[k] = v.strip('"')
        elif line.startswith("itervar "):
            _, k, v = line.split(" ", 2)
            itervars[k] = v.strip('"')
        elif line.startswith("scalar "):
            _, module, name, value = line.split(" ", 3)
            try:
                scalars[module, name] = float(value)
            except ValueError:
                pass
    return attrs, itervars, scalars


def p99(values):
    v = sorted(values)
    return v[max(0, math.ceil(0.99 * len(v)) - 1)] if v else float("nan")


def summarize(config, result_dir, flows_wanted):
    flows = app_flow_map()
    groups = defaultdict(lambda: {"seeds": [], "flows": defaultdict(lambda: {"lat": [], "lost": 0, "miss": 0, "max": 0.0}),
                                  "queues": defaultdict(lambda: {"len_max": 0, "bits_avg": []}),
                                  "drops": defaultdict(int), "x_rx": 0, "x_tx": 0})
    for sca in sorted(result_dir.glob(f"{config}-*.sca")):
        attrs, itervars, scalars = parse_sca(sca)
        if attrs.get("configname") != config:
            continue
        network = attrs["network"].rsplit(".", 1)[-1]
        key = tuple(sorted((k, v) for k, v in itervars.items() if k != "seed"))
        g = groups[key]
        g["seeds"].append(attrs.get("seedset"))
        rd = result_dir / f"{config}-{attrs['runnumber']}"
        lat = read_vec(sca.with_suffix(".vec"), network, flows)
        tx = {}
        for p in rd.glob("F*-tx.csv"):
            row = next(csv.DictReader(p.open()))
            tx[row["flow"]] = int(row["measured_packets"])
        for p in rd.glob("F*-rx.csv"):
            row = next(csv.DictReader(p.open()))
            if flows_wanted and row["flow"] not in flows_wanted:
                continue
            f = g["flows"][row["flow"], row["node"]]
            values = lat.get((row["flow"], row["node"]), [])
            if len(values) != int(row["measured_packets"]):
                raise SystemExit(f"{sca.name}: {row['flow']} vector/CSV sample mismatch")
            f["lat"] += values
            f["lost"] += tx[row["flow"]] - int(row["measured_packets"])
            f["miss"] += int(row["deadline_misses"])
            f["max"] = max(f["max"], float(row["max_latency"]))
        for (module, name), value in scalars.items():
            m = re.search(r"\.(Z\d)\.ZSW\.(eth\[\d+\])\.queue\.queue\[(\d)\]$", module)
            if m:
                q = g["queues"][m.group(1), m.group(2), int(m.group(3))]
                if name == "queueLength:max":
                    q["len_max"] = max(q["len_max"], value)
                elif name == "queueBitLength:timeavg":
                    q["bits_avg"].append(value)
            if module.endswith(".HPC.app[20].io") and name == "packetReceived:count":
                g["x_rx"] += int(value)
            if re.search(r"\.X\d\[\d+\]\.app\[0\]\.io$", module) and name == "packetSent:count":
                g["x_tx"] += int(value)
        for row in csv.DictReader((rd / "drops.csv").open()):
            g["drops"][row["interface"].split(".", 1)[1], row["flow"]] += int(row["packets"])
    return groups


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("configs", nargs="+")
    ap.add_argument("--flows", default="F06,F07,F08,F09,F10,F15,F16,F17")
    ap.add_argument("--csv", help="write the per-flow table to this CSV")
    args = ap.parse_args()
    wanted = set(args.flows.split(",")) if args.flows else None
    out_rows = []
    for spec in args.configs:
        config, _, rdir = spec.partition(":")
        groups = summarize(config, SIM / (rdir or f"results/t1s/{config}"), wanted)
        for key, g in sorted(groups.items(), key=lambda kv: [int(v) if v.isdigit() else v for _, v in kv[0]]):
            label = config + "".join(f" {k}={v}" for k, v in key)
            print(f"\n### {label}  (seeds {','.join(sorted(g['seeds']))})")
            print("| Flow | Rx | Mean µs | p99 µs | Max µs | Lost | Misses |")
            print("|---|---|---|---|---|---|---|")
            for (flow, node), f in sorted(g["flows"].items()):
                n = len(f["lat"])
                mean = sum(f["lat"]) / n * 1e6 if n else float("nan")
                row = {"config": config, **dict(key), "flow": flow, "receiver": node, "samples": n,
                       "mean_us": round(mean, 3), "p99_us": round(p99(f["lat"]) * 1e6, 3),
                       "max_us": round(f["max"] * 1e6, 3), "lost": f["lost"], "misses": f["miss"]}
                out_rows.append(row)
                print(f"| {flow} | {node} | {row['mean_us']:.2f} | {row['p99_us']:.2f} | {row['max_us']:.2f} | {f['lost']} | {f['miss']} |")
            active = [(k, q) for k, q in sorted(g["queues"].items()) if q["len_max"] > 0]
            if active:
                print("\nPLCA port queues (max over seeds of max length; mean time-avg occupancy):")
                for (z, eth, tc), q in active:
                    avg = sum(q["bits_avg"]) / len(q["bits_avg"]) / 8 if q["bits_avg"] else float("nan")
                    print(f"- {z}.ZSW.{eth} TC{tc}: max {q['len_max']:.0f} pk, time-avg {avg:.1f} B")
            drops = {k: v for k, v in g["drops"].items() if v}
            print(f"Queue drops (TrafficAudit, whole run, all seeds): {drops or 'none'}")
            if g["x_tx"]:
                print(f"Extra-node packets after warm-up, sent / received by HPC (all seeds): {g['x_tx']} / {g['x_rx']}")
    if args.csv:
        fields = []
        for r in out_rows:
            fields += [k for k in r if k not in fields]
        with open(args.csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(out_rows)


if __name__ == "__main__":
    main()
