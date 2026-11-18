#!/usr/bin/env python3
"""Step 1 and step 2 on the dual T1S buses. Coordinator relief on the dual T1S buses: standard PLCA vs burst (max_bc = 3)
vs PrioPlca multiTo (coordinator every other slot), and scheduled traffic:
synchronized releases (_SYNC) and synchronized + TC3 gate (_SYNCTAS).

Cases: generic cross-bus reading T1S_DUAL_1ms_S5 (8 nodes) and
T1S_DUAL_200us_S3 (6 nodes); powertrain T1S_PT_NOMINAL / T1S_PT_STRESS.
Per case and variant: latency (min / mean / p99 / max), delay variation
(max - min), inter-arrival jitter of the cross-bus flows, readings lost
(sent - received) and window losses (F15 + F17). 802.1DG reference 1 ms.
Output: markdown on stdout and simulations/zonal/t1s_results/relief.csv.
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
from t1s_powertrain_report import app_index  # noqa: E402
from t1s_jitter_report import stats  # noqa: E402

RES = SIM / "zonal/t1s_results"
VARIANTS = (("", "standard"), ("_BC3", "burst max_bc=3"), ("_MTC", "multiTo coordinator"),
            ("_SYNC", "synchronized"), ("_SYNCTAS", "synchronized + TAS"), ("_SYNCTAS4", "synchronized + TAS 400 µs"))


def p99(v):
    v = sorted(v)
    return v[max(0, math.ceil(0.99 * len(v)) - 1)] if v else float("nan")


def window_and_counts(rdir, cfg, sca):
    text = sca.read_text(errors="replace")
    run = re.search(r'^attr runnumber "?(\d+)', text, re.M).group(1)
    rd = rdir / f"{cfg}-{run}"
    tx, lost = {}, 0
    for p in rd.glob("F*-tx.csv"):
        r = next(csv.DictReader(p.open()))
        tx[r["flow"]] = int(r["measured_packets"])
    for p in rd.glob("F*-rx.csv"):
        r = next(csv.DictReader(p.open()))
        if r["flow"] in ("F15", "F17"):
            lost += tx[r["flow"]] - int(r["measured_packets"])
    return text, lost


def read_runs(vec, want):
    """{key: [[(t, us), ...] per vector]}"""
    ids, out = {}, defaultdict(list)
    with vec.open() as f:
        for line in f:
            if line.startswith("vector "):
                p = line.split()
                k = want(p[2], p[3])
                if k is not None:
                    ids[p[1]] = []
                    out[k].append(ids[p[1]])
            elif line[:1].isdigit():
                p = line.rstrip("\n").split("\t")
                if p[0] in ids:
                    ids[p[0]].append((float(p[2]), float(p[3]) * 1e6))
    return out


def row(case, variant, key, runs, period, extra):
    s = stats(runs, period)
    if not s:
        return None
    lat = [v for r in runs for _, v in r]
    return {"case": case, "variant": variant, "flow": key, "period_us": period, **s,
            "p99_us": round(p99(lat), 3), **extra}


def main():
    rows = []
    rdir = SIM / "results/t1s/T1S_DUAL"
    for base, n, period in (("T1S_DUAL_1ms_S3", 3, 1000), ("T1S_DUAL_1ms_S5", 5, 1000), ("T1S_DUAL_200us_S3", 3, 200)):
        for suf, vname in VARIANTS:
            cfg = base + suf
            runs, wl, sent, recv = defaultdict(list), 0, 0, 0
            scas = sorted(rdir.glob(f"{cfg}-seed=*-#*.sca"))
            for sca in scas:
                text, l_ = window_and_counts(rdir, cfg, sca)
                wl += l_
                sent += sum(int(float(x)) for x in re.findall(r"^scalar \S+\.S\d\[\d+\]\.app\[0\]\.io packetSent:count (\S+)", text, re.M))
                recv += sum(int(float(x)) for x in re.findall(r"^scalar \S+\.ECU\d\.app\[\d+\] packetReceived:count (\S+)", text, re.M))

                def want(mod, name):
                    m = re.search(r"\.ECU(\d)\.app\[\d+\]$", mod)
                    return ("Z1->Z3" if m.group(1) == "3" else "Z3->Z1") if m and name == "endToEndDelay:vector" else None
                for k, v in read_runs(sca.with_suffix(".vec"), want).items():
                    runs[k] += v
            if not scas:
                continue
            for k in ("Z1->Z3", "Z3->Z1"):
                r = row(f"generic {period} µs, {3 + n} nodes", vname, k, runs[k], period,
                        {"window_lost": wl, "readings_lost": sent - recv})
                if r:
                    rows.append(r)
    idx = app_index()
    rdir = SIM / "results/t1s/T1S_PT"
    for prof, col in G.PROFILES.items():
        for suf, vname in VARIANTS:
            cfg = f"T1S_PT_{prof}{suf}"
            runs, wl = defaultdict(list), 0
            scas = sorted(rdir.glob(f"{cfg}-seed=*-#*.sca"))
            for sca in scas:
                _, l_ = window_and_counts(rdir, cfg, sca)
                wl += l_

                def want(mod, name):
                    m = re.search(r"\.(\w+)\.app\[(\d+)\](?:\.sink)?$", mod)
                    return idx.get((m.group(1), int(m.group(2)), name)) if m else None
                for k, v in read_runs(sca.with_suffix(".vec"), want).items():
                    runs[k] += v
            if not scas:
                continue
            for fid, label, kind, a, b, *periods in G.FLOWS:
                if G.ZONE_OF[a] == G.ZONE_OF[b]:
                    continue
                per = float(periods[col - 5][:-2]) * (1000 if periods[col - 5].endswith("ms") else 1)
                r = row(f"powertrain {prof.lower()}", vname, f"{fid} {'RTT' if kind == 'reqresp' else 'one-way'}",
                        runs[fid], per, {"window_lost": wl, "readings_lost": ""})
                if r:
                    rows.append(r)
    print("| Case | Variant | Flow | Mean / p99 / max µs | Delay variation µs | Inter-arrival jitter µs | > 1 ms | Readings lost | Window lost |")
    print("|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        print(f"| {r['case']} | {r['variant']} | {r['flow']} | {r['mean_us']:.0f} / {r['p99_us']:.0f} / {r['max_us']:.0f} | "
              f"{r['pdv_us']:.0f} | {r['interarrival_jitter_us']:.0f} | {r['over_ref']} | {r['readings_lost']} | {r['window_lost']} |")
    if rows:
        with (RES / "relief.csv").open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)


if __name__ == "__main__":
    main()
