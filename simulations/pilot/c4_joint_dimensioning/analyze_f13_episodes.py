#!/usr/bin/env python3
"""Post-process preregistered natural F13 backlog episodes from retained queue traces."""
import csv
import gzip
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PILOT = ROOT / "simulations/pilot/c4_joint_dimensioning"
OUT = PILOT / "results"
TARGET = "ZonalIVN.Z3.ZSW.eth[7].macLayer.queue.queue[4]"
START, END = 1.0, 31.0
THRESHOLD_BITS = 2048
RECOVERY_HORIZON_S = 5.0


def analyze(run_id):
    run = OUT / "runs" / run_id
    artifact_dirs = [p for p in run.iterdir() if p.is_dir() and p.name.endswith("-0")]
    if len(artifact_dirs) != 1:
        raise RuntimeError(f"Expected one artifact directory in {run}")
    artifact = artifact_dirs[0]
    with gzip.open(artifact / "queue_occupancy_events.csv.gz.meta.json.gz", "rt") as f:
        meta = json.load(f)
    q = next((x for x in meta["queues"] if x["module"] == TARGET), None)
    if q is None:
        raise RuntimeError(f"Missing {TARGET} in queue metadata")
    qindex = str(q["queue_index"])
    path = artifact / "queue_occupancy_events.csv.gz"
    previous = 0.0
    before_start = None
    events = []
    with gzip.open(path, "rt", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["queue_index"] != qindex:
                continue
            t = float(row["timestamp_s"])
            value = float(row["occupancy_bits"])
            if t < START:
                previous = value
                continue
            if t >= END:
                break
            if before_start is None:
                before_start = previous
            events.append((t, value))
            previous = value
    q_start_minus = previous if before_start is None else before_start
    baseline = q_start_minus
    active = None
    episodes = []
    for t, value in events:
        if active is None:
            if value > baseline + THRESHOLD_BITS:
                active = {"start_s": t, "baseline_bits": baseline,
                          "threshold_bits": baseline + THRESHOLD_BITS,
                          "peak_bits": value, "peak_time_s": t}
        else:
            if value > active["peak_bits"]:
                active["peak_bits"] = value
                active["peak_time_s"] = t
            if value <= active["threshold_bits"]:
                active["end_s"] = t
                active["recovery_s"] = t - active["start_s"]
                active["censored_at_window_end"] = False
                active["within_5s"] = active["recovery_s"] <= RECOVERY_HORIZON_S
                episodes.append(active)
                baseline = value
                active = None
    if active is not None:
        active["end_s"] = END
        active["recovery_s"] = None
        active["censored_at_window_end"] = True
        active["within_5s"] = False
        episodes.append(active)
    pilot = json.loads((run / "pilot-result.json").read_text())
    drop_rows = [x for x in pilot.get("queue_overflow_drops_by_queue", []) if x.get("queue") == TARGET]
    confirmed_drops = sum(int(x.get("overflow_drops_measurement_window", 0)) for x in drop_rows)
    maxq = next(x for x in pilot["queue_stability"] if x["queue"] == TARGET)
    active_source = True  # F13 is periodic throughout [1,31) in the frozen catalog/workload.
    for item in episodes:
        item["source_active_through_episode"] = active_source and item["end_s"] < END
        item["confirmed_queue_drops_during_episode"] = None if confirmed_drops else 0
        item["natural_recovery_evidence"] = (
            "candidate episode meets the preregistered observed threshold, recovers within 5 s while F13 source is active, and the queue has zero measured-window overflow drops"
            if item["within_5s"] and item["source_active_through_episode"] and confirmed_drops == 0
            else "episode does not satisfy every preregistered recovery condition"
        )
    status = "not_identifiable" if not episodes else (
        "sufficient" if any(x["within_5s"] and x["source_active_through_episode"] and confirmed_drops == 0 for x in episodes)
        else "insufficient")
    return {
        "execution_id": run_id, "queue": TARGET, "queue_index": int(qindex),
        "capacity_bits": int(q["capacity_bits"]), "measurement_window_s": [START, END],
        "window_convention": "half-open [1,31); occupancy is right-continuous; same-time CSV row order retained",
        "baseline_at_1minus_bits": q_start_minus,
        "threshold_above_baseline_bits": THRESHOLD_BITS,
        "recovery_horizon_s": RECOVERY_HORIZON_S,
        "episodes": episodes,
        "confirmed_measurement_overflow_drops_on_queue": confirmed_drops,
        "max_occupancy_bits": maxq["max_occupancy_bits"],
        "mean_occupancy_bits": maxq["mean_occupancy_bits_measurement"],
        "mean_occupancy_bits_5s": maxq["mean_occupancy_bits_5s"],
        "fraction_time_at_least_90pct_capacity": maxq["fraction_measurement_at_least_90pct_capacity"],
        "source_active_assumption": "F13 catalog periodic source is enabled throughout [1,31); verify against the preserved release calendar/source configuration",
        "status": status,
        "limitations": [
            "The queue trace has simulation timestamps and queue occupancy but no event sequence number; CSV row order is preserved for equal timestamps.",
            "Queue-overflow counters are per queue and measurement window, not timestamped per episode; zero queue-level drops makes episode classification possible here.",
            "This natural trace does not test the historical 53-frame backlog unless that magnitude is actually present in the episode peak."
        ]
    }


def main():
    runs = [f"{candidate}_{mode}_L2_A1_seed41"
            for candidate in ("D1", "D2", "D3") for mode in ("TAS", "noTAS")]
    result = {"schema_version": "c4-joint-f13-episodes-v1", "exploratory": True,
              "official_c4_frozen": False, "episode_rule": {
                  "threshold": "> baseline + 2048 queue bits", "recovery_horizon_s": 5.0,
                  "source_must_remain_active": True, "zero_queue_drops_required": True},
              "runs": [analyze(run) for run in runs]}
    path = OUT / "f13_natural_episode_analysis.json"
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(path)


if __name__ == "__main__":
    main()
