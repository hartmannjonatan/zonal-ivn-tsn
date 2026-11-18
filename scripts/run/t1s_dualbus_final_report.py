#!/usr/bin/env python3
"""Report the 30 s / 10-seed final runs of the dual-bus T1S study
(results/t1s/final/<cfg>_30s): cross-bus latency, delay variation and
inter-arrival jitter, readings lost and window losses, baseline vs
synchronized + TAS 400 us. Output: markdown on stdout and
simulations/zonal/t1s_results/dualbus_final_30s.csv.
"""
import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from compare_t1s import SIM  # noqa: E402
import gen_t1s_ev as GE  # noqa: E402
import gen_t1s_powertrain as G  # noqa: E402
from t1s_relief_report import read_runs, row, window_and_counts  # noqa: E402

RES = SIM / "zonal/t1s_results"
FIN = SIM / "results/t1s/final"
VARIANTS = (("", "standard"), ("_SYNCTAS4", "synchronized + TAS 400 µs"),
            ("_SYNCTAS4_GPTP", "sync + TAS, gPTP clocks"), ("_SYNCTAS4_FREE", "sync + TAS, free-running clocks"))

PT_SENS = (("_SYNCTAS4_GPTP_SYNC31", "sync + TAS, gPTP, Sync 31.25 ms"),
           ("_SYNCTAS4_GPTP_D10", "sync + TAS, gPTP, drift ±10 ppm"),
           ("_SYNCTAS4_GPTP_D100", "sync + TAS, gPTP, drift ±100 ppm"))
EV_VARIANTS = (("", "standard"), ("_SYNCTAS4_GPTP", "sync + TAS, gPTP clocks"))


def app_index(mod):
    """(node, app index, vector name) -> flow id, for a scenario generator module."""
    out, per = {}, defaultdict(int)
    for fid, label, kind, a, b, *_ in mod.FLOWS:
        ia = per[a]; per[a] += 1
        ib = per[b]; per[b] += 1
        out[(b, ib, "endToEndDelay:vector") if kind == "oneway" else (a, ia, "roundTripTime:vector")] = fid
    return out


def scenario_rows(mod, prefix, label, variants):
    idx, rows = app_index(mod), []
    for prof, col in mod.PROFILES.items():
        for suf, vname in variants:
            cfg = f"{prefix}_{prof}{suf}"
            d, scas = runs_of(cfg)
            if not scas:
                continue
            runs, wl = defaultdict(list), 0
            for sca in scas:
                _, l_ = window_and_counts(d, f"{cfg}_30s", sca)
                wl += l_

                def want(m_, name):
                    m = re.search(r"\.(\w+)\.app\[(\d+)\](?:\.sink)?$", m_)
                    return idx.get((m.group(1), int(m.group(2)), name)) if m else None
                for k, v in read_runs(sca.with_suffix(".vec"), want).items():
                    runs[k] += v
            for fid, flabel, kind, a, b, *periods in mod.FLOWS:
                per = float(periods[col - 5][:-2]) * (1000 if periods[col - 5].endswith("ms") else 1)
                path = "cross-bus" if mod.ZONE_OF[a] != mod.ZONE_OF[b] else "same bus"
                r = row(f"{label} {prof.lower()}", vname, f"{fid} {'RTT' if kind == 'reqresp' else 'one-way'}",
                        runs[fid], per, {"window_lost": wl, "readings_lost": "", "seeds": len(scas), "path": path})
                if r:
                    rows.append(r)
    return rows


def runs_of(cfg):
    d = FIN / f"{cfg}_30s"
    return d, sorted(d.glob(f"{cfg}_30s-*.sca"))


def main():
    rows = []
    for suf, vname in VARIANTS:
        cfg = "T1S_DUAL_1ms_S3" + suf
        d, scas = runs_of(cfg)
        runs, wl, sent, recv = defaultdict(list), 0, 0, 0
        for sca in scas:
            text, l_ = window_and_counts(d, f"{cfg}_30s", sca)
            wl += l_
            sent += sum(int(float(x)) for x in re.findall(r"^scalar \S+\.S\d\[\d+\]\.app\[0\]\.io packetSent:count (\S+)", text, re.M))
            recv += sum(int(float(x)) for x in re.findall(r"^scalar \S+\.ECU\d\.app\[\d+\] packetReceived:count (\S+)", text, re.M))

            def want(mod, name):
                m = re.search(r"\.ECU(\d)\.app\[\d+\]$", mod)
                return ("Z1->Z3" if m.group(1) == "3" else "Z3->Z1") if m and name == "endToEndDelay:vector" else None
            for k, v in read_runs(sca.with_suffix(".vec"), want).items():
                runs[k] += v
        for k in ("Z1->Z3", "Z3->Z1"):
            r = row("generic 1000 µs, 6 nodes", vname, k, runs[k], 1000,
                    {"window_lost": wl, "readings_lost": sent - recv, "seeds": len(scas)})
            if r:
                rows.append(r)
    rows += scenario_rows(G, "T1S_PT", "powertrain", VARIANTS + PT_SENS)
    rows += scenario_rows(GE, "T1S_EV", "ev", EV_VARIANTS)
    rows += scenario_rows(G, "T1S_PTS", "powertrain same switch", EV_VARIANTS)
    print("| Case | Variant | Flow | Seeds | Samples | Mean / p99 / max µs | Delay variation µs | Std µs | Inter-arrival jitter µs | > 1 ms | Window lost |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        print(f"| {r['case']} | {r['variant']} | {r['flow']}{' (' + r['path'] + ')' if r.get('path') else ''} | {r['seeds']} | {r['samples']} | "
              f"{r['mean_us']:.0f} / {r['p99_us']:.0f} / {r['max_us']:.0f} | {r['pdv_us']:.0f} | {r['std_us']:.1f} | "
              f"{r['interarrival_jitter_us']:.0f} | {r['over_ref']} | {r['window_lost']} |")
    if rows:
        keys = list(dict.fromkeys(k for r in rows for k in r))
        with (RES / "dualbus_final_30s.csv").open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            w.writerows(rows)


if __name__ == "__main__":
    main()
