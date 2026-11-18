#!/usr/bin/env python3
"""Report the TA-PLCA campaign (results/t1s/taplca/<cfg>/ or a --root holding <cfg>/ dirs).

Per configuration and PCP 7 powertrain flow: samples, mean, max, delay variation
(max - min), standard deviation, P99 and samples above 1 ms, pooled over runs;
plus window (F15/F17) losses and the TA-PLCA anchor statistics (share of time the
coordinators held the BEACON = idle bandwidth cost, late cycles).
Output: markdown on stdout and a CSV (default simulations/zonal/t1s_results/taplca.csv).

Usage: t1s_taplca_report.py [--root DIR] [--csv FILE] [CFG ...]
"""
import argparse
import csv
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gen_t1s_powertrain as G  # noqa: E402

SIM = Path(__file__).resolve().parents[2] / "simulations"
CROSS = {"PT01", "PT02", "PT03", "PT04"}


def flow_index():
    out, per = {}, defaultdict(int)
    for fid, label, kind, a, b, *_ in G.FLOWS:
        ia = per[a]; per[a] += 1
        ib = per[b]; per[b] += 1
        out[(b, ib, "endToEndDelay:vector") if kind == "oneway" else (a, ia, "roundTripTime:vector")] = fid
    return out


IDX = flow_index()


def read_vec(vec):
    ids, out = {}, defaultdict(list)
    with vec.open() as f:
        for line in f:
            if line.startswith("vector "):
                p = line.split()
                m = re.search(r"\.(\w+)\.app\[(\d+)\](?:\.sink)?$", p[2])
                k = IDX.get((m.group(1), int(m.group(2)), p[3])) if m else None
                if k:
                    ids[p[1]] = k
            elif line[:1].isdigit():
                p = line.split("\t")
                k = ids.get(p[0])
                if k:
                    out[k].append(float(p[3]) * 1e6)
    return out


def read_sca(sca):
    """anchor stats per coordinator and window losses."""
    text = sca.read_text(errors="replace")
    a = {}
    for m in re.finditer(r'^scalar (\S+ZSW\.eth\[\d\]\.plca) (taplca\w+) (\S+)', text, re.M):
        a[(m.group(1).split(".")[1], m.group(2))] = float(m.group(3))
    simtime = float(re.search(r"^attr sim-time-limit \"?([\d.]+)", text, re.M).group(1)) if re.search(r"^attr sim-time-limit", text, re.M) else None
    return a, simtime, text


def window_lost(sca_text, rdir):
    run = re.search(r'^attr runnumber "?(\d+)', sca_text, re.M).group(1)
    cfg = re.search(r'^attr configname "?(\w+)', sca_text, re.M).group(1)
    rd = rdir / f"{cfg}-{run}"
    tx, lost = {}, 0
    for p in rd.glob("F*-tx.csv"):
        r = next(csv.DictReader(p.open()))
        tx[r["flow"]] = int(r["measured_packets"])
    for p in rd.glob("F*-rx.csv"):
        r = next(csv.DictReader(p.open()))
        if r["flow"] in ("F15", "F17"):
            lost += tx[r["flow"]] - int(r["measured_packets"])
    return lost if tx else None


def stats(v):
    n = len(v)
    if not n:
        return None
    mu = sum(v) / n
    sd = math.sqrt(sum((x - mu) ** 2 for x in v) / n)
    s = sorted(v)
    return {"n": n, "mean_us": round(mu, 2), "min_us": round(s[0], 2), "max_us": round(s[-1], 2),
            "pdv_us": round(s[-1] - s[0], 2), "std_us": round(sd, 2),
            "p99_us": round(s[min(n - 1, int(math.ceil(0.99 * n)) - 1)], 2),
            "over_1ms": sum(1 for x in v if x > 1000)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(SIM / "results/t1s/taplca"))
    ap.add_argument("--csv", default=str(SIM / "zonal/t1s_results/taplca.csv"))
    ap.add_argument("cfgs", nargs="*")
    a = ap.parse_args()
    root = Path(a.root)
    cfgs = a.cfgs or sorted(p.name for p in root.iterdir() if p.is_dir())
    rows = []
    for cfg in cfgs:
        d = root / cfg
        scas = sorted(d.glob("*.sca"))
        if not scas:
            continue
        lat, wl, hold, late, cycles, dur_seg = defaultdict(list), [], defaultdict(float), defaultdict(float), defaultdict(float), defaultdict(float)
        for sca in scas:
            for k, v in read_vec(sca.with_suffix(".vec")).items():
                lat[k] += v
            an, _, text = read_sca(sca)
            w = window_lost(text, d)
            if w is not None:
                wl.append(w)
            for (seg, name), val in an.items():
                if name == "taplcaHoldTotal":
                    hold[seg] += val
                elif name == "taplcaMeasuredTime":
                    dur_seg[seg] += val
                elif name == "taplcaCycles":
                    cycles[seg] += val
                elif name == "taplcaLateCycles":
                    late[seg] += val
        extra = {"runs": len(scas), "window_lost": sum(wl) if wl else "",
                 "hold_share_Z1": round(hold["Z1"] / dur_seg["Z1"], 4) if dur_seg["Z1"] else "",
                 "hold_share_Z3": round(hold["Z3"] / dur_seg["Z3"], 4) if dur_seg["Z3"] else "",
                 "late_share_Z1": round(late["Z1"] / cycles["Z1"], 4) if cycles["Z1"] else "",
                 "late_share_Z3": round(late["Z3"] / cycles["Z3"], 4) if cycles["Z3"] else ""}
        for fid, label, kind, *_ in G.FLOWS:
            s = stats(lat.get(fid, []))
            if s:
                rows.append({"config": cfg, "flow": fid, "kind": "RTT" if kind == "reqresp" else "one-way",
                             "cross_bus": fid in CROSS, **s, **extra})
    if not rows:
        print("no results"); return
    keys = list(rows[0].keys())
    Path(a.csv).parent.mkdir(parents=True, exist_ok=True)
    with open(a.csv, "w", newline="") as f:
        w = csv.DictWriter(f, keys); w.writeheader(); w.writerows(rows)
    print("| config | flow | kind | n | mean | max | PDV | std | P99 | >1ms | win lost | hold Z1/Z3 | late Z1/Z3 |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        if r["cross_bus"]:
            print(f"| {r['config']} | {r['flow']} | {r['kind']} | {r['n']} | {r['mean_us']} | {r['max_us']} | {r['pdv_us']} | "
                  f"{r['std_us']} | {r['p99_us']} | {r['over_1ms']} | {r['window_lost']} | {r['hold_share_Z1']}/{r['hold_share_Z3']} | "
                  f"{r['late_share_Z1']}/{r['late_share_Z3']} |")


if __name__ == "__main__":
    main()
