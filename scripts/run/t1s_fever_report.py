#!/usr/bin/env python3
"""Report the Fever CAN scenario (follow-up F4): latency of every CAN ID from its
T1S node to HPC (UdpSink endToEndDelay at HPC.app[20 + index]) against its
deadline (= period), pooled over seeds, plus the window flows sharing the
segments. Output: markdown on stdout, simulations/zonal/t1s_results/fever_<variant>.csv.
"""
import csv
import json
import math
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SIM = ROOT / "simulations"
RES = SIM / "zonal/t1s_results"
FLOWS = json.loads((SIM / "zonal/traffic/fever/flows.json").read_text())


def p99(v):
    v = sorted(v)
    return v[max(0, math.ceil(0.99 * len(v)) - 1)] if v else float("nan")


def collect(cfg):
    rdir = SIM / f"results/t1s/{cfg}"
    lat = defaultdict(list)
    sent, recv = defaultdict(int), defaultdict(int)
    window = defaultdict(lambda: [0.0, 0])
    for sca in sorted(rdir.glob(f"{cfg}-seed=*-#0.sca")):
        text = sca.read_text(errors="replace")
        run = re.search(r'^attr runnumber "?(\d+)', text, re.M).group(1)
        for m in re.finditer(r"^scalar \S+\.HPC\.app\[(\d+)\] packetReceived:count (\S+)", text, re.M):
            if int(m.group(1)) >= 20:
                recv[int(m.group(1)) - 20] += int(float(m.group(2)))
        ports = {}
        for m in re.finditer(r'^par \S+\.(B\d\[\d+\])\.app\[(\d+)\]\.io destPort (\d+)', text, re.M):
            ports[m.group(1), m.group(2)] = int(m.group(3)) - 8000
        for m in re.finditer(r"^scalar \S+\.(B\d\[\d+\])\.app\[(\d+)\]\.io packetSent:count (\S+)", text, re.M):
            k = ports.get((m.group(1), m.group(2)))
            if k is not None:
                sent[k] += int(float(m.group(3)))
        ids = {}
        with sca.with_suffix(".vec").open() as f:
            for line in f:
                if line.startswith("vector "):
                    parts = line.split()
                    m = re.search(r"\.HPC\.app\[(\d+)\]$", parts[2])
                    if m and parts[3] == "endToEndDelay:vector" and int(m.group(1)) >= 20:
                        ids[parts[1]] = int(m.group(1)) - 20
                elif line[:1].isdigit():
                    vid = line.split("\t", 1)[0]
                    if vid in ids:
                        lat[ids[vid]].append(float(line.rsplit("\t", 1)[1]))
        rd = rdir / f"{cfg}-{run}"
        for p in rd.glob("F1[5-7]-*-rx.csv"):
            r = next(csv.DictReader(p.open()))
            w = window[r["flow"]]
            w[0] = max(w[0], float(r["max_latency"]) * 1e6)
        for p in rd.glob("F1[5-7]-HPC-tx.csv"):
            r = next(csv.DictReader(p.open()))
            window[r["flow"]][1] += int(r["measured_packets"])
    return lat, sent, recv, window


def main():
    for variant, cfg in (("ECU", "T1S_FEVER_ECU"), ("GW", "T1S_FEVER_GW")):
        lat, sent, recv, window = collect(cfg)
        rows = []
        for f in FLOWS:
            v = lat.get(f["index"], [])
            d = f["deadline_ms"] * 1000
            rows.append({"can_id": f["id"], "class": f["class"], "period_ms": f["period_ms"], "packets": len(v),
                         "mean_us": round(sum(v) / len(v) * 1e6, 2) if v else "",
                         "p99_us": round(p99(v) * 1e6, 2) if v else "",
                         "max_us": round(max(v) * 1e6, 2) if v else "",
                         "misses": sum(1 for x in v if x * 1e6 > d),
                         "sent_minus_received": sent[f["index"]] - recv[f["index"]],
                         "max_over_deadline_pct": round(max(v) * 1e6 / d * 100, 2) if v else ""})
        with (RES / f"fever_{variant.lower()}.csv").open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        print(f"\n### {cfg}")
        print("| Class | CAN IDs | Packets | Mean µs | p99 µs | Max µs | Worst max/deadline | Misses | Sent − received |")
        print("|---|---|---|---|---|---|---|---|---|")
        for cls in ("CRITICAL", "OTHER", "all"):
            sel = [r for r in rows if cls == "all" or r["class"] == cls]
            allv = [x for f in FLOWS if cls == "all" or f["class"] == cls for x in lat.get(f["index"], [])]
            print(f"| {cls} | {len(sel)} | {len(allv)} | {sum(allv) / len(allv) * 1e6:.1f} | {p99(allv) * 1e6:.1f} | "
                  f"{max(allv) * 1e6:.1f} | {max(r['max_over_deadline_pct'] for r in sel):.2f} % | "
                  f"{sum(r['misses'] for r in sel)} | {sum(r['sent_minus_received'] for r in sel)} |")
        print("Window max µs: " + ", ".join(f"{k} {v[0]:.1f}" for k, v in sorted(window.items())))
        worst = sorted(rows, key=lambda r: -(r["max_over_deadline_pct"] or 0))[:3]
        print("Tightest CAN IDs: " + "; ".join(f"{r['can_id']} ({r['period_ms']} ms) max {r['max_us']} µs" for r in worst))


if __name__ == "__main__":
    main()
