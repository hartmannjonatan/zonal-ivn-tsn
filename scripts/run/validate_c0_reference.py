#!/usr/bin/env python3
"""Step 4 check: original C0 L1/A0 (30 s, seeds 1001-1005) on this INET.

Reports for all 22 flows (per receiver, 5 seeds pooled): measured packets,
losses (talker minus receiver measured packets), deadline misses, nearest-rank
p99 and max latency. Compares them with
  * the 2 s baseline C0_L1_A0_2s (seeds 1001-1003), and
  * the official campaign values stored in the repository:
    - simulations/analysis/icit2027_publication_assets_2026-10-27/
      fig2_critical_latency_runs.csv (per seed, F06-F10: offered/received/
      lost/misses/p99/max), and
    - simulations/analysis/icit2027_editorial_synthesis_2026-10-27/
      selected_run_metrics.csv (per seed, run-level aggregates).
"""
import csv
import math
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from compare_t1s import SIM, app_flow_map, read_vec  # noqa: E402

CONFIG = "Validate_C0_L1_A0_P1seeds"
RESULTS = SIM / "results/t1s/C0_P1_L1_A0"
SEEDS = [1001, 1002, 1003, 1004, 1005]
FIG2 = SIM / "analysis/icit2027_publication_assets_2026-10-27/fig2_critical_latency_runs.csv"
RUNS = SIM / "analysis/icit2027_editorial_synthesis_2026-10-27/selected_run_metrics.csv"


def nearest_rank_p99(values):
    v = sorted(values)
    return v[max(0, math.ceil(0.99 * len(v)) - 1)] if v else float("nan")


def load_run(config, result_dir, run, seed, network):
    rd = result_dir / f"{config}-{run}"
    lat = read_vec(result_dir / f"{config}-seed={seed}-#0.vec", network, app_flow_map())
    tx = {}
    for p in rd.glob("F*-tx.csv"):
        row = next(csv.DictReader(p.open()))
        tx[row["flow"]] = int(row["measured_packets"])
    out = {}
    images = {}
    for p in rd.glob("F*-rx.csv"):
        row = next(csv.DictReader(p.open()))
        key = (row["flow"], row["node"])
        values = lat.get(key, [])
        if len(values) != int(row["measured_packets"]):
            raise SystemExit(f"{rd.name} {key}: {len(values)} vector samples vs {row['measured_packets']} measured")
        out[key] = {"offered": tx[row["flow"]], "received": int(row["measured_packets"]),
                    "misses": int(row["deadline_misses"]), "max": float(row["max_latency"]),
                    "lat": values, "deadline": float(row["deadline_s"])}
        images[key] = (int(row["measured_images"]), int(row["completed_images"]),
                       int(row["image_deadline_misses"]))
    return out, images


def main():
    per_seed = {}
    seed_images = {}
    pooled = defaultdict(lambda: {"offered": 0, "received": 0, "misses": 0, "max": 0.0, "lat": []})
    image_totals = defaultdict(lambda: [0, 0, 0])
    for run, seed in enumerate(SEEDS):
        data, images = load_run(CONFIG, RESULTS, run, seed, "ZonalIVN")
        per_seed[seed] = data
        seed_images[seed] = (sum(v[0] for v in images.values()), sum(v[1] for v in images.values()))
        for key, d in data.items():
            p = pooled[key]
            for k in ("offered", "received", "misses"):
                p[k] += d[k]
            p["max"] = max(p["max"], d["max"])
            p["lat"] += d["lat"]
            p["deadline"] = d["deadline"]
        for key, (m, c, miss) in images.items():
            t = image_totals[key]
            t[0] += m
            t[1] += c
            t[2] += miss

    short = defaultdict(lambda: {"lat": [], "max": 0.0, "lost": 0, "misses": 0})
    for run, seed in enumerate(SEEDS[:3]):
        data, _ = load_run("C0_L1_A0_2s", SIM / "results/t1s/C0", run, seed, "ZonalIVN")
        for key, d in data.items():
            s = short[key]
            s["lat"] += d["lat"]
            s["max"] = max(s["max"], d["max"])
            s["lost"] += d["offered"] - d["received"]
            s["misses"] += d["misses"]

    print("## All flows, 30 s, seeds 1001-1005 pooled (vs 2 s baseline, seeds 1001-1003)\n")
    print("| Flow | Rx | Deadline µs | Received | Lost | Misses | p99 µs (30 s / 2 s) | Max µs (30 s / 2 s) |")
    print("|---|---|---|---|---|---|---|---|")
    rows = []
    for key in sorted(pooled):
        p, s = pooled[key], short[key]
        p99_30 = nearest_rank_p99(p["lat"]) * 1e6
        p99_2 = nearest_rank_p99(s["lat"]) * 1e6
        rows.append({"flow": key[0], "receiver": key[1], "deadline_us": p["deadline"] * 1e6,
                     "offered": p["offered"], "received": p["received"], "lost": p["offered"] - p["received"],
                     "misses": p["misses"], "p99_us_30s": round(p99_30, 3), "max_us_30s": round(p["max"] * 1e6, 3),
                     "p99_us_2s": round(p99_2, 3), "max_us_2s": round(s["max"] * 1e6, 3),
                     "lost_2s": s["lost"], "misses_2s": s["misses"]})
        print(f"| {key[0]} | {key[1]} | {p['deadline'] * 1e6:.0f} | {p['received']} | {p['offered'] - p['received']} "
              f"| {p['misses']} | {p99_30:.2f} / {p99_2:.2f} | {p['max'] * 1e6:.2f} / {s['max'] * 1e6:.2f} |")
    with (RESULTS / "c0_reference_flows.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    cams = {k: v for k, v in image_totals.items() if v[0]}
    print("\nCamera images (offered / complete / image deadline misses): " +
          ", ".join(f"{k[0]} {v[0]}/{v[1]}/{v[2]}" for k, v in sorted(cams.items())))

    print("\n## Official campaign values in the repository (per seed, F06-F10)\n")
    print("| Seed | Flow | Offered (repo / now) | Lost (repo / now) | Misses (repo / now) | p99 µs (repo / now) | Max µs (repo / now) | Match |")
    print("|---|---|---|---|---|---|---|---|")
    mismatches = 0
    for row in csv.DictReader(FIG2.open()):
        if row["article_treatment"] != "C0" or row["load"] != "L1" or row["alignment"] != "A0":
            continue
        seed = int(row["seed"])
        if seed not in per_seed:
            continue
        d = per_seed[seed][row["flow"], row["receiver"]]
        now = (d["offered"], d["offered"] - d["received"], d["misses"],
               nearest_rank_p99(d["lat"]) * 1e6, d["max"] * 1e6)
        ref = (int(row["offered_packets"]), int(row["lost_packets"]), int(row["deadline_misses_received"]),
               float(row["p99_latency_us"]), float(row["max_latency_us"]))
        ok = now[:3] == ref[:3] and all(abs(a - b) < 1e-3 for a, b in zip(now[3:], ref[3:]))
        mismatches += not ok
        print(f"| {seed} | {row['flow']} | {ref[0]} / {now[0]} | {ref[1]} / {now[1]} | {ref[2]} / {now[2]} | "
              f"{ref[3]:.3f} / {now[3]:.3f} | {ref[4]:.3f} / {now[4]:.3f} | {'yes' if ok else 'NO'} |")

    print("\n## Run-level aggregates (selected_run_metrics.csv)\n")
    print("| Seed | Offered pkts (repo / now) | Received (repo / now) | Images offered/complete (repo / now) | Critical non-camera p99 max µs (repo / now) | Max (repo / now) | Camera image p99 max µs (repo) |")
    print("|---|---|---|---|---|---|---|")
    critical = {"F01", "F06", "F07", "F08", "F09", "F10"}
    for row in csv.DictReader(RUNS.open()):
        if row["treatment"] != "C0" or row["load"] != "L1" or row["alignment"] != "A0":
            continue
        seed = int(row["seed"])
        if seed not in per_seed:
            continue
        data = per_seed[seed]
        offered = sum(d["offered"] for d in data.values())
        received = sum(d["received"] for d in data.values())
        crit = [(k, d) for k, d in data.items() if k[0] in critical]
        p99max = max(nearest_rank_p99(d["lat"]) for _, d in crit) * 1e6
        maxmax = max(d["max"] for _, d in crit) * 1e6
        print(f"| {seed} | {row['offered_packet_receiver_sum']} / {offered} | {row['received_packet_receiver_sum']} / {received} "
              f"| {row['offered_images_sum']}/{row['completed_images_sum']} / {seed_images[seed][0]}/{seed_images[seed][1]} | "
              f"{float(row['critical_noncamera_packet_p99_max_s']) * 1e6:.3f} / {p99max:.3f} | "
              f"{float(row['critical_noncamera_packet_max_max_s']) * 1e6:.3f} / {maxmax:.3f} | "
              f"{float(row['camera_image_p99_max_s']) * 1e6:.3f} |")
    print(f"\nF06-F10 per-seed mismatches against the repository: {mismatches}")


if __name__ == "__main__":
    main()
