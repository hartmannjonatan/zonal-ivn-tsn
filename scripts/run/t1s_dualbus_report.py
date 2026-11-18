#!/usr/bin/env python3
"""Report the dual-bus T1S scenario (cross-bus sensor reading).

Per period and sensors-per-bus: the cross-bus readings (S1[*] -> ECU3 and
S3[*] -> ECU1, endToEndDelay at ECUz.app[*]) and the catalog flows that share
the path: brake F08-F10 (PCP 7 like the readings), radar F06/F07 and the
windows on the T1S segments (F15, F17). Seeds are pooled. Misses of the
readings are counted against 100 us (the P1 PCP 7 deadline) and against the
reading period. Output: markdown on stdout and
simulations/zonal/t1s_results/dualbus.csv.
"""
import csv
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from compare_t1s import SIM, app_flow_map, read_vec  # noqa: E402

RES = SIM / "zonal/t1s_results"
RDIR = SIM / "results/t1s/T1S_DUAL"
FLOWS = ("F06", "F07", "F08", "F09", "F10", "F15", "F17")
PERIODS = (("1ms", 1000), ("200us", 200))
SENSORS = (1, 3, 5)


def p99(v):
    v = sorted(v)
    return v[max(0, math.ceil(0.99 * len(v)) - 1)] if v else float("nan")


def readings(vec):
    """endToEndDelay samples of ECU1/ECU3 sinks -> {'Z1->Z3': [...], 'Z3->Z1': [...]}"""
    ids, out = {}, {"Z1->Z3": [], "Z3->Z1": []}
    with vec.open() as f:
        for line in f:
            if line.startswith("vector "):
                parts = line.split()
                m = re.search(r"\.ECU(\d)\.app\[\d+\]$", parts[2])
                if parts[3] == "endToEndDelay:vector" and m:
                    ids[parts[1]] = out["Z1->Z3" if m.group(1) == "3" else "Z3->Z1"]
            elif line[:1].isdigit():
                f0 = line.split("\t", 1)[0]
                if f0 in ids:
                    ids[f0].append(float(line.rsplit("\t", 1)[1]) * 1e6)
    return out


def main():
    flows = app_flow_map()
    rows = []
    for plabel, period_us in PERIODS:
        for n in SENSORS:
            cfg = f"T1S_DUAL_{plabel}_S{n}"
            agg = defaultdict(lambda: {"max": 0.0, "lost": 0, "miss": 0})
            rd_all = {"Z1->Z3": [], "Z3->Z1": []}
            sent = recv = 0
            scas = sorted(RDIR.glob(f"{cfg}-seed=*-#*.sca"))
            for sca in scas:
                text = sca.read_text(errors="replace")
                run = re.search(r'^attr runnumber "?(\d+)', text, re.M).group(1)
                rd = RDIR / f"{cfg}-{run}"
                tx = {}
                for p in rd.glob("F*-tx.csv"):
                    r = next(csv.DictReader(p.open()))
                    tx[r["flow"]] = int(r["measured_packets"])
                for p in rd.glob("F*-rx.csv"):
                    r = next(csv.DictReader(p.open()))
                    if r["flow"] not in FLOWS:
                        continue
                    a = agg[r["flow"]]
                    a["max"] = max(a["max"], float(r["max_latency"]) * 1e6)
                    a["lost"] += tx[r["flow"]] - int(r["measured_packets"])
                    a["miss"] += int(r["deadline_misses"])
                for k, v in readings(sca.with_suffix(".vec")).items():
                    rd_all[k] += v
                for m in re.finditer(r"^scalar \S+\.S\d\[\d+\]\.app\[0\]\.io packetSent:count (\S+)", text, re.M):
                    sent += int(float(m.group(1)))
                for m in re.finditer(r"^scalar \S+\.ECU\d\.app\[\d+\] packetReceived:count (\S+)", text, re.M):
                    recv += int(float(m.group(1)))
            if not scas:
                continue
            row = {"period_us": period_us, "sensors_per_bus": n, "segment_nodes": 3 + n, "seeds": len(scas)}
            for k, v in rd_all.items():
                key = "r13" if k == "Z1->Z3" else "r31"
                row[f"{key}_packets"] = len(v)
                row[f"{key}_mean_us"] = round(sum(v) / len(v), 3) if v else ""
                row[f"{key}_p99_us"] = round(p99(v), 3) if v else ""
                row[f"{key}_max_us"] = round(max(v), 3) if v else ""
                row[f"{key}_misses_100us"] = sum(1 for x in v if x > 100)
                row[f"{key}_misses_period"] = sum(1 for x in v if x > period_us)
            row["readings_sent_minus_received"] = sent - recv
            for f in FLOWS:
                row[f"{f}_max_us"] = round(agg[f]["max"], 3)
                row[f"{f}_misses"] = agg[f]["miss"]
                row[f"{f}_lost"] = agg[f]["lost"]
            rows.append(row)
    print("| Period | Nodes/bus | Z1→Z3 reading mean / p99 / max µs | >100 µs | Z3→Z1 reading mean / p99 / max µs | >100 µs | "
          "> period | Brake F08–F10 max µs (misses) | Radar F06/F07 max µs | Window F15/F17 max µs (lost) |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        print(f"| {r['period_us']} µs | {r['segment_nodes']} | {r['r13_mean_us']} / {r['r13_p99_us']} / {r['r13_max_us']} | "
              f"{r['r13_misses_100us']}/{r['r13_packets']} | {r['r31_mean_us']} / {r['r31_p99_us']} / {r['r31_max_us']} | "
              f"{r['r31_misses_100us']}/{r['r31_packets']} | {r['r13_misses_period'] + r['r31_misses_period']} | "
              f"{r['F08_max_us']:.1f} / {r['F09_max_us']:.1f} / {r['F10_max_us']:.1f} "
              f"({r['F08_misses'] + r['F09_misses'] + r['F10_misses']}) | {r['F06_max_us']:.1f} / {r['F07_max_us']:.1f} | "
              f"{r['F15_max_us']:.1f} / {r['F17_max_us']:.1f} ({r['F15_lost'] + r['F17_lost']}) |")
    if rows:
        with (RES / "dualbus.csv").open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)


if __name__ == "__main__":
    main()
