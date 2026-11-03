#!/usr/bin/env python3
"""Report the load / alignment robustness study (follow-up F7).

Per configuration and cell (L2/L3 x A0/A1, seeds pooled): max latency, deadline
misses and losses per flow class, verdict against the benchmark deadlines
(catalog: radar/brake 100 us, window 50 ms, cameras 10/30 ms, ...) and against
the IEEE 802.1DG reference deadlines (radar/brake 1 ms, ADAS camera 16 ms,
window/body 50 ms). Output: markdown on stdout and
simulations/zonal/t1s_results/loads.csv.
"""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from t1s_stress import SIM, summarize  # noqa: E402

RES = SIM / "zonal/t1s_results"
CONFIGS = [("C0 (100 Mb/s)", "C0_LOADS", "results/t1s/loads/C0"),
           ("T1S standard", "T1S_C0_LOADS", "results/t1s/loads/T1S_C0"),
           ("T1S + TAS gate", "T1S_C0_TAS_L2", "results/t1s/loads/T1S_C0_TAS"),
           ("T1S + TAS gate", "T1S_C0_TAS_L3", "results/t1s/loads/T1S_C0_TAS"),
           ("T1S + PrioPlca priorityTo", "T1S_C0_PrioTo_LOADS", "results/t1s/loads/T1S_C0_PrioTo"),
           ("Hybrid, 8 nodes/segment", "T1S_HYBRID_B6_LOADS", "results/t1s/loads/T1S_HYBRID_B6")]
CLASSES = {"radar": ("F06", "F07"), "brake": ("F08", "F09", "F10"), "window": ("F15", "F16", "F17"),
           "camera": ("F02", "F03", "F04", "F05")}
REF_US = {"radar": 1000, "brake": 1000, "window": 50000, "camera": 16000}


def main():
    out = []
    print("| Config | Load | Align | Radar max µs (misses) | Brake max µs (misses) | Window max µs (lost) | "
          "Camera max µs (lost) | Other flows: misses / lost | Benchmark | 802.1DG reference |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for label, cfg, rdir in CONFIGS:
        groups = summarize(cfg, SIM / rdir, None)
        for key, g in sorted(groups.items()):
            kv = dict(key)
            load = kv.get("load", "3" if cfg.endswith("L3") else "2" if cfg.endswith("L2") else "?")
            agg = kv.get("agg", "?")
            cls = {}
            for c, fl in CLASSES.items():
                sel = [f for (fid, _), f in g["flows"].items() if fid in fl]
                cls[c] = (max((f["max"] for f in sel), default=0) * 1e6, sum(f["miss"] for f in sel),
                          sum(f["lost"] for f in sel))
            others = [f for (fid, _), f in g["flows"].items() if not any(fid in fl for fl in CLASSES.values())]
            o_miss, o_lost = sum(f["miss"] for f in others), sum(f["lost"] for f in others)
            all_miss = sum(f["miss"] for f in g["flows"].values())
            all_lost = sum(f["lost"] for f in g["flows"].values())
            bench = "pass" if all_miss == 0 and all_lost == 0 else "fail"
            ref_ok = all(cls[c][2] == 0 and cls[c][0] <= REF_US[c] for c in CLASSES) and o_lost == 0
            ref = "pass" if ref_ok else "fail"
            print(f"| {label} | L{load} | {agg} | {cls['radar'][0]:.1f} ({cls['radar'][1]}) | "
                  f"{cls['brake'][0]:.1f} ({cls['brake'][1]}) | {cls['window'][0]:.1f} ({cls['window'][2]}) | "
                  f"{cls['camera'][0]:.1f} ({cls['camera'][2]}) | {o_miss} / {o_lost} | {bench} | {ref} |")
            row = {"config": label, "ini_config": cfg, "load": f"L{load}", "alignment": agg,
                   "seeds": len(g["seeds"]), "benchmark": bench, "reference_802_1dg": ref,
                   "other_misses": o_miss, "other_lost": o_lost}
            for c, (mx, miss, lost) in cls.items():
                row.update({f"{c}_max_us": round(mx, 3), f"{c}_misses": miss, f"{c}_lost": lost})
            out.append(row)
    with (RES / "loads.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)


if __name__ == "__main__":
    main()
