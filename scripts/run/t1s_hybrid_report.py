#!/usr/bin/env python3
"""Report the hybrid T1S scenario (follow-up F3).

Per profile (10 ms / 1 ms body flows) and body-node count: catalog flows on
the T1S segment (window F15-F17) and the critical flows kept on point-to-point
links (radar F06-F07, brake F08-F10), plus the body flows: upstream status
(B* -> HPC, endToEndDelay at HPC.app[20]) and downstream commands
(HPC -> B*, endToEndDelay at B*.app[1]). Deadline of body flows = period.
Seeds are pooled. Output: markdown on stdout and
simulations/zonal/t1s_results/hybrid.csv.
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
FLOWS = ("F06", "F07", "F08", "F09", "F10", "F15", "F16", "F17")
DEADLINE = {"F06": 100, "F07": 100, "F08": 100, "F09": 100, "F10": 100, "F15": 50000, "F16": 50000, "F17": 50000}


def p99(v):
    v = sorted(v)
    return v[max(0, math.ceil(0.99 * len(v)) - 1)] if v else float("nan")


def body_delays(vec):
    ids, up, down = {}, [], []
    with vec.open() as f:
        for line in f:
            if line.startswith("vector "):
                parts = line.split()
                if parts[3] == "endToEndDelay:vector":
                    if parts[2].endswith(".HPC.app[20]"):
                        ids[parts[1]] = up
                    elif re.search(r"\.B\d\[\d+\]\.app\[1\]$", parts[2]):
                        ids[parts[1]] = down
            elif line[:1].isdigit():
                f0 = line.split("\t", 1)[0]
                if f0 in ids:
                    ids[f0].append(float(line.rsplit("\t", 1)[1]))
    return up, down


def main():
    flows = app_flow_map()
    rows = []
    for profile, suffix, period_us in (("10 ms", "", 10000), ("1 ms", "_FAST", 1000)):
        rdir = SIM / f"results/t1s/T1S_HYBRID{suffix}"
        for n in (0, 2, 4, 6):
            cfg = f"T1S_HYBRID{suffix}_B{n}"
            agg = defaultdict(lambda: {"lat": [], "max": 0.0, "lost": 0, "miss": 0})
            up, down, sent_up, recv_up, sent_dn, recv_dn = [], [], 0, 0, 0, 0
            for sca in sorted(rdir.glob(f"{cfg}-seed=*-#0.sca")):
                text = sca.read_text(errors="replace")
                run = re.search(r'^attr runnumber "?(\d+)', text, re.M).group(1)
                rd = rdir / f"{cfg}-{run}"
                lat = read_vec(sca.with_suffix(".vec"), "ZonalIVNT1SHybrid", flows)
                tx = {}
                for p in rd.glob("F*-tx.csv"):
                    r = next(csv.DictReader(p.open()))
                    tx[r["flow"]] = int(r["measured_packets"])
                for p in rd.glob("F*-rx.csv"):
                    r = next(csv.DictReader(p.open()))
                    if r["flow"] not in FLOWS:
                        continue
                    a = agg[r["flow"]]
                    a["lat"] += lat.get((r["flow"], r["node"]), [])
                    a["max"] = max(a["max"], float(r["max_latency"]))
                    a["lost"] += tx[r["flow"]] - int(r["measured_packets"])
                    a["miss"] += int(r["deadline_misses"])
                u, d = body_delays(sca.with_suffix(".vec"))
                up += u
                down += d
                for m in re.finditer(r"^scalar \S+\.(B\d\[\d+\]\.app\[0\]\.io|HPC\.app\[(\d+)\]\.io) packetSent:count (\S+)", text, re.M):
                    if m.group(1).startswith("B"):
                        sent_up += int(float(m.group(3)))
                    elif int(m.group(2)) >= 21:
                        sent_dn += int(float(m.group(3)))
                for m in re.finditer(r"^scalar \S+\.(HPC\.app\[20\]|B\d\[\d+\]\.app\[1\]) packetReceived:count (\S+)", text, re.M):
                    if m.group(1).startswith("HPC"):
                        recv_up += int(float(m.group(2)))
                    else:
                        recv_dn += int(float(m.group(2)))
            if not agg:
                continue
            row = {"profile": profile, "body_nodes_per_zone": n, "segment_nodes": 2 + n}
            for f in FLOWS:
                a = agg[f]
                row[f"{f}_max_us"] = round(a["max"] * 1e6, 3)
                row[f"{f}_misses"] = a["miss"]
                row[f"{f}_lost"] = a["lost"]
            for name, v, s_, r_ in (("up", up, sent_up, recv_up), ("down", down, sent_dn, recv_dn)):
                row[f"body_{name}_packets"] = len(v)
                row[f"body_{name}_mean_us"] = round(sum(v) / len(v) * 1e6, 3) if v else ""
                row[f"body_{name}_p99_us"] = round(p99(v) * 1e6, 3) if v else ""
                row[f"body_{name}_max_us"] = round(max(v) * 1e6, 3) if v else ""
                row[f"body_{name}_misses"] = sum(1 for x in v if x * 1e6 > period_us)
                row[f"body_{name}_sent_minus_received"] = s_ - r_
            rows.append(row)
    print("| Body period | Nodes/segment | Radar F06/F07 max µs (misses) | Brake F08–F10 max µs (misses) | "
          "Window F15/F16/F17 max µs (lost) | Body up mean / p99 / max µs (misses) | Body down mean / p99 / max µs (misses) |")
    print("|---|---|---|---|---|---|---|")
    for r in rows:
        def fmt(fs):
            return " / ".join(f"{r[f + '_max_us']:.1f}" for f in fs)
        body = []
        for d in ("up", "down"):
            if r[f"body_{d}_packets"]:
                body.append(f"{r[f'body_{d}_mean_us']:.1f} / {r[f'body_{d}_p99_us']:.1f} / {r[f'body_{d}_max_us']:.1f} "
                            f"({r[f'body_{d}_misses']})")
            else:
                body.append("—")
        print(f"| {r['profile']} | {r['segment_nodes']} | {fmt(('F06', 'F07'))} ({r['F06_misses'] + r['F07_misses']}) | "
              f"{fmt(('F08', 'F09', 'F10'))} ({r['F08_misses'] + r['F09_misses'] + r['F10_misses']}) | "
              f"{fmt(('F15', 'F16', 'F17'))} ({r['F15_lost'] + r['F16_lost'] + r['F17_lost']}) | {body[0]} | {body[1]} |")
    with (RES / "hybrid.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main()
