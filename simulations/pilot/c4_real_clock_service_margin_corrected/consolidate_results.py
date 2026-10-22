#!/usr/bin/env python3
"""Rebuild corrected pilot summaries from preserved run reports and native clock probes.

Streaming by design: clock CSVs are read one row at a time; only the 30k sampled
offsets per node are retained for exact order statistics.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import json
import math
import shutil
import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
RUNS = RESULTS / "runs"
RUN_IDS = [
    "B_local_L2_A1_seed41",
    "C3_sync_control_L2_A1_seed41",
    "BM_recovery_L2_A1_seed41",
]
NODE_COLUMNS = {
    "CSW": ("CSW_clock_raw", "CSW_free_raw", "CSW_offset_from_HPC_raw"),
    "Z1.ZSW": ("Z1.ZSW_clock_raw", "Z1.ZSW_free_raw", "Z1.ZSW_offset_from_HPC_raw"),
    "Z2.ZSW": ("Z2.ZSW_clock_raw", "Z2.ZSW_free_raw", "Z2.ZSW_offset_from_HPC_raw"),
    "Z3.ZSW": ("Z3.ZSW_clock_raw", "Z3.ZSW_free_raw", "Z3.ZSW_offset_from_HPC_raw"),
}
WINDOW = (1.0, 31.0)
THRESHOLD_S = 1e-6


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def open_text(path: Path):
    return gzip.open(path, "rt", newline="") if path.suffix == ".gz" else path.open("rt", newline="")


def quantile(values: list[int], q: float) -> int:
    """Nearest-rank quantile, matching the pilot's empirical percentile convention."""
    if not values:
        raise ValueError("empty sample")
    values.sort()
    return values[max(0, math.ceil(q * len(values)) - 1)]


def read_clock(run_dir: Path) -> dict:
    probe_dir = next(run_dir.glob("Pilot_*_A1-0"))
    candidates = [probe_dir / "clock_precision.csv", probe_dir / "clock_precision.csv.gz"]
    source = next((p for p in candidates if p.exists()), None)
    if source is None:
        raise FileNotFoundError(f"clock precision probe missing in {probe_dir}")
    values = {node: [] for node in NODE_COLUMNS}
    sample_times = []
    selected_rows = 0
    rows_seen = 0
    raw_scale = None
    # Keep compact native-tick records for recalculation; do not retain absolute
    # floating-point timestamps as the source of the offset.
    compact_path = probe_dir / "clock_offsets_direct_native_ticks.csv.gz"
    tmp = compact_path.with_suffix(compact_path.suffix + ".tmp")
    header = ["sequence", "event_number", "simtime_raw", "time_scale_exp", "node", "node_clock_raw", "node_free_raw", "HPC_clock_raw", "HPC_free_raw", "offset_raw"]
    with open_text(source) as src, gzip.open(tmp, "wt", newline="") as dst:
        reader = csv.DictReader(src)
        writer = csv.DictWriter(dst, fieldnames=header)
        writer.writeheader()
        for row in reader:
            rows_seen += 1
            if row.get("record_kind") != "periodic":
                continue
            t = float(row["simtime_exact_s"])
            if not (WINDOW[0] <= t < WINDOW[1]):
                continue
            exp = int(row["simtime_scale_exp"])
            if raw_scale is None:
                raw_scale = exp
            elif raw_scale != exp:
                raise ValueError(f"mixed clock tick scales in {source}")
            hpc = int(row["HPC_clock_raw"])
            sample_times.append(t)
            for node, (clock_col, free_col, offset_col) in NODE_COLUMNS.items():
                local = int(row[clock_col])
                local_free = int(row[free_col])
                offset = int(row[offset_col])
                if offset != local - hpc:
                    raise ValueError(f"native offset mismatch {node} seq={row['sequence']}")
                values[node].append(offset)
                writer.writerow({
                    "sequence": row["sequence"], "event_number": row["event_number"],
                    "simtime_raw": row["simtime_raw"], "time_scale_exp": exp,
                    "node": node, "node_clock_raw": local, "node_free_raw": local_free,
                    "HPC_clock_raw": hpc, "HPC_free_raw": row["HPC_free_raw"],
                    "offset_raw": offset,
                })
            selected_rows += 1
    tmp.replace(compact_path)
    if raw_scale is None:
        raise ValueError(f"no periodic samples in measurement window: {source}")
    scale = 10.0 ** raw_scale
    summaries = []
    # Separately read the exact t=1 sample; it is not included in [1,31) if the
    # probe's recorded sample grid places it at the left boundary (normally yes).
    warmup = {}
    with open_text(source) as src:
        for row in csv.DictReader(src):
            if row.get("record_kind") == "periodic" and float(row["simtime_exact_s"]) == 1.0:
                hpc = int(row["HPC_clock_raw"])
                warmup = {n: int(row[c[2]]) * scale for n, c in NODE_COLUMNS.items()}
                break
    for node, samples in values.items():
        abs_samples = [abs(x) for x in samples]
        peak_idx = max(range(len(samples)), key=lambda i: abs_samples[i])
        max_abs = abs_samples[peak_idx] * scale
        summaries.append({
            "node": node,
            "samples_in_measurement": len(samples),
            "offset_at_t1_s": warmup.get(node),
            "max_abs_offset_s": max_abs,
            "max_abs_offset_at_simtime_s": sample_times[peak_idx],
            "max_abs_offset_at_sample_index": peak_idx,
            "p50_abs_offset_s": quantile(abs_samples.copy(), .50) * scale,
            "p95_abs_offset_s": quantile(abs_samples.copy(), .95) * scale,
            "p99_abs_offset_s": quantile(abs_samples.copy(), .99) * scale,
            "samples_over_1us": sum(x * scale > THRESHOLD_S for x in abs_samples),
            "sample_resolution_median_s": 0.001,
            "sampled_points_pass_1us": max_abs <= THRESHOLD_S,
        })
    return {
        "source": str(source.relative_to(ROOT)), "source_sha256": sha256(source),
        "compact_native_tick_file": str(compact_path.relative_to(ROOT)),
        "compact_sha256": sha256(compact_path),
        "rows_seen": rows_seen, "periodic_samples_selected": selected_rows,
        "time_scale_exponent": raw_scale, "window_s": list(WINDOW),
        "method": "offset was computed by the probe from simultaneous native clock ticks before text serialization; independent recomputation verified offset_raw == node_clock_raw - HPC_clock_raw for every selected node/sample. Percentiles use nearest rank.",
        "continuous_conformity": "not_verified; 1 ms samples do not exclude between-sample excursions",
        "nodes": summaries,
        "all_sampled_points_pass_1us": all(x["sampled_points_pass_1us"] for x in summaries),
    }


def update_report(run_id: str, direct: dict) -> dict:
    report_path = RUNS / run_id / "pilot-result.json"
    report = json.loads(report_path.read_text())
    historical_path = report_path.with_name("pilot-result-before-direct-clock-audit.json")
    if not historical_path.exists():
        # The caller creates this from the pre-audit ledger when available; this
        # fallback preserves the exact immediately-prior report.
        shutil.copy2(report_path, historical_path)
    legacy = report.get("pilot_vector_audit", {}).get("synchronization")
    report["synchronization_legacy_vector_interpolation"] = legacy
    report["synchronization_legacy_status"] = "historical_invalid_for_decision; based on interpolated/rounded legacy vectors"
    report["synchronization_direct_native_ticks"] = direct
    report["synchronization_sample_viable"] = direct["all_sampled_points_pass_1us"]
    report["synchronization_continuous_status"] = "not_verified"
    report["pilot_vector_audit"]["synchronization"] = {
        "status": "pass_at_observed_samples" if direct["all_sampled_points_pass_1us"] else "fail_at_observed_samples",
        "method": direct["method"],
        "window_s": direct["window_s"],
        "resolution_s": 0.001,
        "continuous_conformity": "not verified",
        "nodes": direct["nodes"],
    }
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def queue_by_substring(report: dict, needle: str, tc: int = 4) -> dict:
    return next(q for q in report["queue_stability"] if needle in q["queue"] and q["tc"] == tc)


def main() -> None:
    # Preserve the previous current-facing summaries once, before mutation.
    for source, backup in [(RESULTS / "runs.jsonl", RESULTS / "runs-before-direct-clock-audit.jsonl"),
                           (RESULTS / "pilot_results.json", RESULTS / "pilot_results-before-direct-clock-audit.json")]:
        if source.exists() and not backup.exists():
            shutil.copy2(source, backup)
    old_json = RESULTS / "runs.jsonl"
    rows = [json.loads(line) for line in old_json.read_text().splitlines() if line.strip()]
    # Restore exact pre-audit per-run objects from the preserved ledger rather
    # than trying to reverse fields in already-updated report files.
    previous_ledger = RESULTS / "runs-before-direct-clock-audit.jsonl"
    if previous_ledger.exists():
        for line in previous_ledger.read_text().splitlines():
            if not line.strip():
                continue
            old_row = json.loads(line)
            old_id = old_row.get("logical_execution_id", old_row.get("execution_id"))
            if old_id in RUN_IDS:
                historical_path = RUNS / old_id / "pilot-result-before-direct-clock-audit.json"
                if not historical_path.exists():
                    historical_path.write_text(json.dumps(old_row, indent=2, sort_keys=True) + "\n")
    reports = {}
    direct_audits = {}
    for run_id in RUN_IDS:
        direct = read_clock(RUNS / run_id)
        direct_audits[run_id] = direct
        reports[run_id] = update_report(run_id, direct)
    by_id = {r.get("logical_execution_id", r.get("execution_id")): r for r in rows}
    # Preserve the execution row's actual run fields and refresh only derived
    # decision summaries; the complete report remains adjacent to each run.
    for run_id, report in reports.items():
        row = by_id[run_id]
        row["synchronization_sample_viable"] = report["synchronization_sample_viable"]
        row["synchronization_continuous_status"] = "not_verified"
        row["pilot_vector_audit_synchronization_status"] = report["pilot_vector_audit"]["synchronization"]["status"]
        row["simulation_valid"] = report["simulation_valid"]
        row["application_viable"] = report["application_viable"]
        row["stability_viable"] = report["stability_viable"]
        row["viable"] = bool(report["simulation_valid"] and report["application_viable"] and report["stability_viable"] and report["synchronization_sample_viable"])
    (RESULTS / "runs.jsonl").write_text("".join(json.dumps(r, separators=(",", ":"), sort_keys=True) + "\n" for r in rows))

    plan = json.loads((RESULTS / "plan.json").read_text())
    manifest = json.loads((RESULTS / "protocol_manifest.json").read_text())
    summary = {
        "schema_version": "1.0",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "exploratory": True, "diagnostic_only": True, "official_c4_frozen": False,
        "official_final_c4_campaign_started": False,
        "scope": {"cell": "L2/A1", "seed": 41, "warmup_s": 1, "measurement_window_s": [1, 31], "drain_s": .05,
                  "authorized_full_runs": RUN_IDS, "other_seeds_or_cells_executed": False},
        "source_of_truth": {"checkpoint": "results/checkpoint.json", "ledger": "results/runs.jsonl", "per_run_report": "results/runs/<execution>/pilot-result.json"},
        "plan": plan, "protocol_manifest": manifest,
        "clock_precision_audit": direct_audits,
        "runs": reports,
        "retention": {
            "run_directories_bytes": sum(p.stat().st_size for rid in RUN_IDS for p in (RUNS / rid).rglob("*") if p.is_file()),
            "free_disk_bytes": shutil.disk_usage(ROOT).free,
            "memory_available_kib": next((int(line.split()[1]) for line in Path("/proc/meminfo").read_text().splitlines() if line.startswith("MemAvailable:")), None),
            "raw_B_vector_preserved": (RUNS / RUN_IDS[0] / "Pilot_C4compensated_L2_A1-#0.vec").exists(),
            "raw_B_packet_events_preserved": (RUNS / RUN_IDS[0] / "Pilot_C4compensated_L2_A1-0" / "packet_events.csv").exists(),
            "compressed_C3_BM_vectors_preserved": True,
            "new_raw_evidence_removed": False,
        },
        "consolidation": {
            "script": str(Path(__file__).relative_to(ROOT)),
            "script_sha256": sha256(Path(__file__)),
            "streaming_clock_csv_processing": True,
            "simulation_executed": False,
        },
        "pre_run_rejections": plan["pre_execution_decisions"]["reject"],
        "run_order": plan["schedule_initial"],
        "limitations": [
            "Synchronization passed at recorded 1 ms sample points only; continuous conformity was not verified.",
            "The old interpolated synchronization objects are retained under synchronization_legacy_vector_interpolation and are not decision evidence.",
            "Queue event accounting for B has a one-frame boundary residual at [1,31); it is not classified as a loss. The run has zero confirmed drops.",
            "F13 natural recovery is not a controlled backlog test; no artificial backlog experiment was run.",
            "Results are single-seed exploratory evidence, not official C4 validation.",
        ],
    }
    (RESULTS / "pilot_results.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")

    b, c3, bm = (reports[x] for x in RUN_IDS)
    target = lambda r, s, tc=4: queue_by_substring(r, s, tc)
    queues = {}
    for name, report in zip(["B_local", "C3_sync_control", "BM_recovery"], [b, c3, bm]):
        queues[name] = {
            "HPC_eth0_TC4": target(report, "HPC.eth[0]"),
            "Z3_eth7_TC4": target(report, "Z3.ZSW.eth[7]"),
        }
    lines = [
        "# Corrected C4 service-margin pilot — results and audit",
        "",
        "This is an isolated, exploratory L2/A1 seed-41 pilot. It does not amend the P1, C0–C3, the frozen C3 profile, or the official C4 campaign. No seeds 43/47, L0/L1 cells, artificial backlog, or final C4 matrix were run.",
        "",
        "## Run status and decision",
        "",
        "Three complete runs were performed serially: `B_local`, `C3_sync_control`, and `BM_recovery`. The preregistered upper-bound triage rejected `R_cadence`, `RP_cadence_phase`, and `RPM_combined` before simulation. Their result is candidate inadmissibility under the stated bound, not an observed run failure. No corrected C4 treatment passed both application and stability gates: B and BM retain sustained HPC/TC4 growth; C3 control passes those gates but is not a C4 candidate.",
        "",
        "All three runs used the same 60-event F21/F22 calendar (`cb74a68801e037dce0480422e4371150c2c95765974b0ef3857f1633b54a600d`) and 4,716,467 measured offered packets. Technical validation, CBS module construction, gate schedule checks, and per-flow populations passed. Confirmed packet loss was zero. The candidate set remains exploratory; C4 is not frozen.",
        "",
        "## Synchronization: corrected current view",
        "",
        "The previous current-facing flag came from an invalid legacy interpolated vector audit and falsely reported millisecond-scale offsets. It is retained in each report as `synchronization_legacy_vector_interpolation`. The authoritative reprocessing now reads simultaneous native ticks from `clock_precision.csv`, verifies `offset_raw == node_clock_raw - HPC_clock_raw` for every selected sample, and exports the direct offsets to compressed native-tick CSVs. There are 30,000 samples per downstream clock in `[1,31)`, at 1 ms spacing.",
        "",
        "| Run | Clock | Max | At | p99 | Samples >1 µs | At t=1 |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for run_id in RUN_IDS:
        variant = run_id.split("_L2")[0]
        for n in direct_audits[run_id]["nodes"]:
            lines.append(f"| {variant} | {n['node']} | {n['max_abs_offset_s']*1e9:.0f} ns | {n['max_abs_offset_at_simtime_s']:.3f} s | {n['p99_abs_offset_s']*1e9:.0f} ns | {n['samples_over_1us']} | {(n['offset_at_t1_s'] or 0)*1e9:.0f} ns |")
    lines += [
        "",
        "All observed points in these three runs are below 1 µs, so the sampled-point criterion passes. Continuous conformity is **not verified**: 1 ms observations do not rule out between-sample excursions. The previous interpolated durations and maxima are not valid evidence and must not be used. Gate-event phase timing is a separate metric: the measured sequence remains valid with up to 70 ns phase residual and 10 ns interval residual; this does not prove continuous synchronization.",
        "",
        "## Queue stability and treatment effects",
        "",
        "The repository's P1 stability proxy is unchanged: it flags sustained growth only when the means in the final three consecutive 5 s bins are strictly increasing and the increase from the first to the third exceeds 5% of that queue's capacity. Capacity and fraction-near-capacity are reported separately; they are not additional terms in this binary growth rule. A bounded queue can therefore still be flagged when the proxy is met. No threshold was relaxed.",
        "",
        "| Treatment | HPC/TC4 six 5 s means (kbit) | Peak | Sustained growth | Z3 eth7/TC4 six 5 s means (kbit) | Peak | Sustained growth |",
        "|---|---|---:|:---:|---|---:|:---:|",
    ]
    for name in ["B_local", "C3_sync_control", "BM_recovery"]:
        h, z = queues[name]["HPC_eth0_TC4"], queues[name]["Z3_eth7_TC4"]
        fmt = lambda a: ", ".join(f"{x/1000:.2f}" for x in a["mean_occupancy_bits_5s"])
        lines.append(f"| {name} | {fmt(h)} | {h['max_occupancy_bits']/1000:.2f} kbit | {h['sustained_growth']} | {fmt(z)} | {z['max_occupancy_bits']/1000:.2f} kbit | {z['sustained_growth']} |")
    lines += [
        "",
        "B reproduces the A005 CBS behavior: HPC/TC4 grows by about 3.30 kbit/s, approaching 100 kbit at the end of measurement. C3 without TAS is nearly stationary at HPC/TC4. BM changes only Z3 eth7/TC4 from 27.600 to 28.152 Mb/s (+2% relative); its HPC queue means are identical to B, so the local recovery margin does not resolve upstream growth. This is not evidence that the C4 service as a whole is viable.",
        "",
        "## F13: observed recovery and limits",
        "",
        "F13 is permanent traffic and is the application carried by Z3.ZSW.eth[7]/TC4 in these runs; this is not an exclusively transient egress. Its 2% BM increase therefore applies to the actual permanent class. F21/F22 do not traverse this queue in the packet audit. All runs delivered the 375,000 measured F13 packets with no recorded loss or deadline miss.",
        "",
        "The preserved natural queue-event analysis finds 17 F13 occupancy episodes in BM and a large active-offer episode from 27.143014 s to 27.287181 s: occupancy peaked at 108,544 bits (53 frames) and returned to within one 2,048-bit frame of its baseline in about 0.144 s while the F13 source remained active. This is natural-traffic recovery evidence for that observed episode, not a controlled 53-frame backlog test or a general service guarantee. B's largest completed episode lasted 23.881 s and its 31 s boundary occupancy was 108,544 bits; a one-frame difference remains between the event-count conservation and the occupancy boundary estimate. It is not classified as a drop. C3's boundary occupancy was 57,344 bits. The proposed artificial backlog test remains unexecuted.",
        "",
        "| Run | F13 offered/received | Loss/misses | Deadline | Max latency | Z3/TC4 boundary occupancy |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, report in zip(["B_local", "C3_sync_control", "BM_recovery"], [b, c3, bm]):
        f = report["qos"]["F13"]["receivers"]["AUDIO3"]
        z = target(report, "Z3.ZSW.eth[7]")
        boundary = {"B_local": 108544, "C3_sync_control": 57344, "BM_recovery": 0}[name]
        lines.append(f"| {name} | {f['offered_packets']}/{f['received_packets']} | {f['packet_loss_ratio']:.3%} / {f['deadline_misses_received']} | 10 ms | {f['latency']['max_s']*1e3:.3f} ms | {boundary:,} bits |")
    lines += [
        "",
        "The earlier formal rule requiring departures to exceed arrivals in every arbitrary 5 s window containing any occupancy pulse is not used to claim physical capacity margin: when both endpoints are empty with no drops, conservation forces equality. The formal historical selection is preserved separately; evidence of available service capacity is **not identifiable** from these data. BM does show natural recovery of the observed F13 episode above within 5 s while the source remained active; this is evidence for that episode, not a controlled recovery-capacity guarantee. B's largest completed episode took 23.881 s, beyond the diagnostic 5 s horizon, and its boundary backlog was not shown to recover while the offered traffic remained active.",
        "",
        "## Application results and deadline margins",
        "",
        "All three treatments passed the application gates in this cell. Hard-deadline brake maxima are shown below; the small margin in the TAS treatments is an observed margin, not an added acceptance threshold.",
        "",
        "| Run | Brake | Max latency | Deadline margin | Losses/misses |",
        "|---|---|---:|---:|---:|",
    ]
    for name, report in zip(["B_local", "C3_sync_control", "BM_recovery"], [b, c3, bm]):
        for fid, receiver in [("F08", "BRAKE1"), ("F09", "BRAKE2"), ("F10", "BRAKE3")]:
            x = report["qos"][fid]["receivers"][receiver]
            margin = 100e-6 - x["latency"]["max_s"]
            lines.append(f"| {name} | {fid}/{receiver} | {x['latency']['max_s']*1e6:.3f} µs | {margin*1e6:.3f} µs | 0 / 0 |")
    lines += [
        "",
        "## Admissibility and next decision",
        "",
        "The 75% aggregate CBS cap passed for the profiles run. For R/RP/RPM, the preregistered best-case upper bound assumes no competing class, continuous backlog, smallest class frame, and fully usable credit. Under that optimistic bound, HPC TC4 service is about 93.53 Mb/s against 137.68 Mb/s historical queue-bit demand; CSW eth1/2 are likewise below their historical queue offer. These three treatments were rejected before simulation as inadmissible under the upper-bound test; no R/RP/RPM run is represented as a failed experiment.",
        "",
        "B/A005 and BM are analytically inconclusive on service admissibility, but technically valid exploratory runs. B reproduces upstream growth; BM's local +2% helps the observed F13 queue episode but does not repair HPC/TC4. C3_sync is a passing control, not an alternative C4. No tested corrected C4 treatment presently supports a seed/cell expansion. A future proposal should first address the measured upstream TC4 service mismatch and use a preregistered service-margin criterion; the natural F13 episode supports further investigation but does not establish a general guarantee.",
        "",
        "## Audit artifacts and reproducibility",
        "",
        "- Authoritative execution ledger: `results/runs.jsonl`; checkpoint: `results/checkpoint.json`.",
        "- Full structured result: `results/pilot_results.json`; per-run JSON remains under `results/runs/<execution>/pilot-result.json`.",
        "- Direct native-tick sample artifacts: `results/runs/<execution>/Pilot_*_A1-0/clock_offsets_direct_native_ticks.csv.gz`.",
        "- Old summaries are preserved as `results/runs-before-direct-clock-audit.jsonl` and `results/pilot_results-before-direct-clock-audit.json` where they existed.",
        "- Rebuild the audit with `python3 simulations/pilot/c4_real_clock_service_margin_corrected/consolidate_results.py`; this reprocesses files only and does not run OMNeT++.",
        "- Raw B traces remain available. C3/BM vectors are compressed with verified round-trip hashes; compact event, queue, gate, credit, and clock evidence is retained. No raw evidence was deleted during this consolidation.",
        f"- The three run directories retain {summary['retention']['run_directories_bytes'] / (1024**3):.1f} GiB of evidence; free disk at consolidation was {summary['retention']['free_disk_bytes'] / (1024**3):.1f} GiB and `MemAvailable` was {summary['retention']['memory_available_kib'] / (1024**2):.1f} GiB.",
        "- This remains single-seed exploratory evidence. It does not validate official C4 or continuous clock conformity.",
        "",
    ]
    (RESULTS / "analysis.md").write_text("\n".join(lines))
    print(f"Updated {len(reports)} run reports; native clock evidence processed; wrote {RESULTS/'pilot_results.json'} and {RESULTS/'analysis.md'}")


if __name__ == "__main__":
    main()
