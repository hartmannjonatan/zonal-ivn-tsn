#!/usr/bin/env python3
"""Deterministically consolidate the isolated C4 joint-dimensioning pilot."""
from __future__ import annotations

import hashlib
import json
import shutil
import csv
import gzip
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PILOT = ROOT / "simulations/pilot/c4_joint_dimensioning"
RESULTS = PILOT / "results"


def read_json(path: Path):
    with path.open() as f:
        return json.load(f)


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def num(x, digits=6):
    if x is None:
        return "—"
    return f"{x:.{digits}g}"


def run_data(row):
    if row.get("status") == "reused_audited_result":
        p = ROOT / row["reused_result_path"]
        source = "reused_audited_result"
    else:
        p = RESULTS / "runs" / row["logical_execution_id"] / "pilot-result.json"
        source = "new_simulation"
    d = read_json(p)
    return p, source, d


def queue_by_name(d, name):
    return next((q for q in d.get("queue_stability", []) if q.get("queue", "").endswith(name)), None)


def flow_rows(d):
    rows = []
    for flow, flow_data in sorted(d.get("qos", {}).items()):
        for receiver, m in sorted(flow_data.get("receivers", {}).items()):
            latency = m.get("latency") or {}
            image = m.get("image_completion")
            rows.append({
                "flow": flow,
                "receiver": receiver,
                "criticality": m.get("criticality"),
                "offered_packets": m.get("offered_packets"),
                "received_packets": m.get("received_packets"),
                "packet_loss_ratio": m.get("packet_loss_ratio"),
                "deadline_misses_received": m.get("deadline_misses_received"),
                "deadline_miss_ratio_including_loss": m.get("deadline_miss_ratio_including_loss"),
                "latency_samples": latency.get("samples"),
                "p99_s": latency.get("p99_s"),
                "max_s": latency.get("max_s"),
                "goodput_payload_ratio": m.get("goodput_payload_ratio"),
                "useful_throughput_mbps": m.get("useful_throughput_mbps"),
                "flow_gate_viable": m.get("viable"),
                "image_completion": image,
            })
    return rows


def clock_precision_summary(path: Path):
    """Recompute simultaneous native-tick offsets from the direct probe CSV."""
    nodes = ["CSW", "Z1.ZSW", "Z2.ZSW", "Z3.ZSW"]
    stats = {kind: {n: {"count": 0, "max_abs_offset_s": 0.0, "samples_over_1us": 0}
                    for n in nodes} for kind in ("periodic", "signal")}
    for row in csv.DictReader(gzip.open(path, "rt", newline="")):
        kind = row.get("record_kind")
        if kind not in stats:
            continue
        scale = int(row["simtime_scale_exp"])
        sim_s = int(row["simtime_raw"]) * (10.0 ** scale)
        if not (1.0 <= sim_s < 31.0):
            continue
        for node in nodes:
            raw = row.get(f"{node}_offset_from_HPC_raw", "")
            if not raw:
                continue
            off_s = abs(int(raw)) * (10.0 ** scale)
            item = stats[kind][node]
            item["count"] += 1
            item["max_abs_offset_s"] = max(item["max_abs_offset_s"], off_s)
            if off_s > 1e-6:
                item["samples_over_1us"] += 1
    periodic_pass = all(v["count"] > 0 and v["max_abs_offset_s"] <= 1e-6
                        for v in stats["periodic"].values())
    event_pass = all(v["count"] > 0 and v["max_abs_offset_s"] <= 1e-6
                     for v in stats["signal"].values())
    return {
        "method": "simultaneous IClock::getClockTime() snapshots; integer native simtime ticks subtracted before serialization; periodic and clock-signal records kept separate",
        "window_s": [1.0, 31.0], "threshold_s": 1e-6,
        "periodic_sample_pass": periodic_pass, "clock_event_snapshot_pass": event_pass,
        "observed_sample_pass": periodic_pass and event_pass,
        "continuous_conformity": "not_verified; periodic sampling is 1 ms and event snapshots do not cover all instants",
        "by_record_kind_and_node": stats,
    }


def write_svg_plot(path: Path, title: str, series, y_label: str, y_max: float, y_ticks):
    """Small dependency-free line plot; series is [(label, values, color)]."""
    width, height = 900, 360
    left, right, top, bottom = 76, 24, 42, 64
    pw, ph = width-left-right, height-top-bottom
    x = lambda i: left + (pw * i / 5)
    y = lambda v: top + ph * (1 - v/y_max)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
           '<rect width="100%" height="100%" fill="white"/>',
           f'<text x="{width/2}" y="25" text-anchor="middle" font-family="sans-serif" font-size="17">{title}</text>']
    for tick in y_ticks:
        yy = y(tick)
        out += [f'<line x1="{left}" y1="{yy:.1f}" x2="{width-right}" y2="{yy:.1f}" stroke="#dddddd"/>',
                f'<text x="{left-10}" y="{yy+4:.1f}" text-anchor="end" font-family="sans-serif" font-size="11">{tick:g}</text>']
    out += [f'<line x1="{left}" y1="{top}" x2="{left}" y2="{height-bottom}" stroke="#333"/>',
            f'<line x1="{left}" y1="{height-bottom}" x2="{width-right}" y2="{height-bottom}" stroke="#333"/>',
            f'<text x="18" y="{top+ph/2}" transform="rotate(-90 18 {top+ph/2})" text-anchor="middle" font-family="sans-serif" font-size="12">{y_label}</text>']
    for i in range(6):
        out.append(f'<text x="{x(i):.1f}" y="{height-bottom+18}" text-anchor="middle" font-family="sans-serif" font-size="11">{i*5}-{(i+1)*5}</text>')
    for idx, (label, vals, color) in enumerate(series):
        pts = ' '.join(f'{x(i):.1f},{y(float(v)):.1f}' for i,v in enumerate(vals))
        out.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2.2"/>')
        for i,v in enumerate(vals):
            out.append(f'<circle cx="{x(i):.1f}" cy="{y(float(v)):.1f}" r="3" fill="{color}"/>')
        lx = left + idx*165
        out.append(f'<line x1="{lx}" y1="{height-23}" x2="{lx+18}" y2="{height-23}" stroke="{color}" stroke-width="3"/>')
        out.append(f'<text x="{lx+24}" y="{height-19}" font-family="sans-serif" font-size="11">{label}</text>')
    out.append('</svg>')
    path.write_text('\n'.join(out))


def main():
    checkpoint = read_json(RESULTS / "checkpoint.json")
    plan = read_json(RESULTS / "plan.json")
    dim = read_json(RESULTS / "dimensioning.json")
    f13 = read_json(RESULTS / "f13_natural_episode_analysis.json")
    run_rows = [json.loads(line) for line in (RESULTS / "runs.jsonl").read_text().splitlines() if line.strip()]
    entries = []
    for row in run_rows:
        path, source, d = run_data(row)
        variant = row.get("variant") or d.get("variant")
        is_candidate = variant in {"D1_TAS", "D1_noTAS", "D2_TAS", "D2_noTAS", "D3_TAS", "D3_noTAS"}
        if is_candidate:
            selected_queues = {
                key: queue_by_name(d, key)
                for key in ["HPC.eth[0].macLayer.queue.queue[4]", "CSW.eth[1].macLayer.queue.queue[4]",
                            "CSW.eth[2].macLayer.queue.queue[4]", "CSW.eth[3].macLayer.queue.queue[4]",
                            "Z3.ZSW.eth[7].macLayer.queue.queue[4]"]
            }
            artifact_dir = next((p for p in path.parent.iterdir() if p.is_dir() and p.name.startswith("Joint_")), path.parent)
            evidence = {
                name: {"path": rel(artifact_dir / name), "sha256": sha(artifact_dir / name)}
                for name in ["packet_events.csv.gz", "queue_occupancy_events.csv.gz", "gate_states.csv.gz",
                             "guard_band_states.csv.gz", "pilot_other_vectors.csv.gz", "clock_offsets.csv.gz", "clock_precision.csv.gz",
                             "latency_upper_tails.json.gz", "d3-acceptance.json" if variant.startswith("D3") else f"{variant[:2].lower()}-acceptance.json"]
                if (artifact_dir / name).exists()
            }
            run_retention = path.parent / "retention_manifest.json"
            evidence["retention_manifest"] = {"path": rel(run_retention), "sha256": sha(run_retention),
                                                "content": read_json(run_retention)} if run_retention.exists() else None
            precision_file = artifact_dir / "clock_precision.csv.gz"
            sync_precision = clock_precision_summary(precision_file) if precision_file.exists() else None
        else:
            selected_queues = {"HPC.eth[0]/TC4": queue_by_name(d, "HPC.eth[0].macLayer.queue.queue[4]"),
                               "Z3.eth[7]/TC4": queue_by_name(d, "Z3.ZSW.eth[7].macLayer.queue.queue[4]")}
            evidence = {"source_report": {"path": rel(path), "sha256": sha(path)}}
            sync_precision = None
        entries.append({
            "execution_id": row["logical_execution_id"], "variant": variant,
            "source_classification": source, "source_result": rel(path), "source_result_sha256": sha(path),
            "configuration": d.get("config"), "seed": d.get("seed"), "cell": d.get("cell"),
            "simulation_valid": d.get("simulation_valid"), "application_viable": d.get("application_viable"),
            "stability_viable": d.get("stability_viable"),
            "synchronization_sample_viable": (sync_precision["observed_sample_pass"] if sync_precision else d.get("synchronization_sample_viable")),
            "synchronization_continuous_status": d.get("synchronization_continuous_status"),
            "effective_gcl_status": (d.get("effective_gcl") or {}).get("status"),
            "observed_gate_status": (d.get("observed_gate_events") or {}).get("status"),
            "offered_packets_total": d.get("offered_packets"), "drops_post_warmup_and_drain": d.get("queue_overflow_drop_total_post_warmup_including_drain"),
            "pending_at_end": d.get("pending_packet_count_at_simulation_end"),
            "pending_packets_at_simulation_end": d.get("pending_packets_at_simulation_end"),
            "flow_populations": d.get("flow_populations"), "metric_windows": d.get("metric_windows"),
            "drop_reconciliation": d.get("drop_reconciliation"),
            "queue_overflow_drops_by_queue": d.get("queue_overflow_drops_by_queue"),
            "measurement_drops_by_queue": d.get("measurement_drops_by_queue"),
            "all_queue_stability": d.get("queue_stability"), "all_queueing_time": d.get("queueing_time"),
            "calendar_sha256": d.get("calendar_sha256"), "calendar_paired": d.get("calendar_paired"),
            "effective_profile_sha256": d.get("effective_profile_sha256"),
            "effective_profile_bps": d.get("effective_profile_bps"),
            "flow_metrics": flow_rows(d), "selected_queues": selected_queues,
            "credit_validation": d.get("credit_vector_validation"),
            "gate_contract": d.get("effective_gcl"), "observed_gates": d.get("observed_gate_events"),
            "synchronization_samples": (sync_precision if sync_precision else (d.get("pilot_vector_audit") or {}).get("synchronization")),
            "synchronization_legacy_export": (d.get("pilot_vector_audit") or {}).get("synchronization") if sync_precision else None,
            "evidence_artifacts": evidence,
            "execution_command": d.get("command") if source == "new_simulation" else None,
            "reuse_equivalence": row.get("reuse_equivalence"),
        })

    candidates = {}
    for cid, c in dim["candidate_designs"].items():
        candidates[cid] = {
            "gcl": c["gcl"], "all_port_caps_pass": c["all_port_caps_pass"],
            "profile_bps": c["profile_bps"], "port_caps": c["port_caps"],
            "service_by_port": c["service_by_port"], "demand_sources": c["demand_sources"],
            "z3_eth7_idleSlope_bps": c["z3_eth7_idleSlope_bps"],
            "z3_eth7_ratio_to_C3": c["z3_eth7_ratio_to_C3"],
        }

    new_runs = [e for e in entries if e["source_classification"] == "new_simulation"]
    candidate_results = [e for e in new_runs if e["variant"].startswith(("D1", "D2", "D3"))]
    all_candidates_pass = any(e["application_viable"] and e["stability_viable"] and e["simulation_valid"] for e in candidate_results)
    by_variant = {e["variant"]: e for e in entries}
    def metric(e, flow, receiver, key):
        return next(x for x in e["flow_metrics"] if x["flow"] == flow and x["receiver"] == receiver)[key]
    contrasts = {}
    for cid in ("D1", "D2", "D3"):
        tas, not_as, c3 = by_variant[f"{cid}_TAS"], by_variant[f"{cid}_noTAS"], by_variant["C3_sync_control"]
        def delta(a,b,field,flow=None,rx=None):
            av = a[field] if flow is None else metric(a,flow,rx,field)
            bv = b[field] if flow is None else metric(b,flow,rx,field)
            return av-bv
        contrasts[cid] = {}
        for name,a,b in [("TAS_minus_C3_sync",tas,c3),("TAS_minus_noTAS",tas,not_as),("noTAS_minus_C3_sync",not_as,c3)]:
            contrasts[cid][name] = {
                "queue_overflow_drops_delta": delta(a,b,"drops_post_warmup_and_drain"),
                "F08_max_latency_us_delta": delta(a,b,"max_s","F08","BRAKE1")*1e6,
                "F09_max_latency_us_delta": delta(a,b,"max_s","F09","BRAKE2")*1e6,
                "F10_max_latency_us_delta": delta(a,b,"max_s","F10","BRAKE3")*1e6,
                "F21_loss_percentage_points_delta": delta(a,b,"packet_loss_ratio","F21","Z3.ZCPU")*100,
                "F22_loss_percentage_points_delta": delta(a,b,"packet_loss_ratio","F22","Z3.ZCPU")*100,
            }
    out = {
        "schema_version": 1, "pilot_id": "c4-joint-dimensioning", "exploratory": True,
        "official_c4_frozen": False, "official_c4_campaign_started": False,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "scope": {"cell": "L2/A1", "seed": 41, "warmup_s": 1, "measurement_s": [1, 31], "drain_s": 0.05,
                  "new_full_simulations": len(new_runs), "reused_audited_controls": sum(e["source_classification"] == "reused_audited_result" for e in entries),
                  "methodological_treatments_total": len(entries), "conditional_seed_checks_executed": False,
                  "conditional_load_checks_executed": False, "artificial_backlog_executed": False,
                  "conditional_reason": "No D1/D2/D3 TAS candidate passed the application gates in seed 41; therefore the preregistered selection condition for seeds 43/47 and L0/L1 was not met."},
        "protocol_source": {"path": rel(RESULTS / "plan.json"), "sha256": sha(RESULTS / "plan.json"),
                            "manifest": rel(RESULTS / "protocol_manifest.json"), "manifest_sha256": sha(RESULTS / "protocol_manifest.json"),
                            "protocol_markdown": rel(PILOT / "protocol.md"), "protocol_sha256": sha(PILOT / "protocol.md")},
        "reproducibility": {
            "git_commit_at_plan": plan.get("git_commit"), "working_tree_status_at_plan": plan.get("working_tree_status_at_plan"),
            "omnetpp_version": plan.get("omnetpp_version"), "inet_version": plan.get("inet_version"),
            "inet_source_sha256": plan.get("inet_source_sha256"),
            "executables_and_runtime_libraries": plan.get("executables_and_runtime_libraries"),
            "source_hashes": plan.get("source_hashes"), "calendar_manifest": plan.get("calendars"),
            "pilot_ini_sha256": sha(PILOT / "pilot.ini"), "runner_sha256": sha(PILOT / "run_joint_pilot.py"),
            "dimension_candidate_script_sha256": sha(PILOT / "dimension_candidates.py"),
            "probe_source_sha256": {"ClockPrecisionProbe.cc": sha(PILOT / "plugin/ClockPrecisionProbe.cc"),
                                    "RealClockTraceProbe.cc": sha(PILOT / "plugin/RealClockTraceProbe.cc"),
                                    "libc4realclockprobe.so": sha(PILOT / "plugin/libc4realclockprobe.so")},
        },
        "dimensioning_method": dim["design_method"], "candidate_designs": candidates,
        "paired_contrasts": contrasts,
        "acceptance_policy": dim["acceptance"], "fixed_inputs": dim["fixed_inputs"],
        "runs": entries, "f13_natural_episode_analysis": f13,
        "incidents": [
            {"kind": "preflight_technical", "description": "Initial probe-package preflight failed before a methodology run; isolated NED packaging was corrected and the preflight then passed.", "methodological_run": False},
            {"kind": "retention_technical", "description": "Concurrent gzip writers conflicted on the D1_TAS temporary vector; original vector was preserved, invalid temporary removed, then recompressed with streaming gzip and source SHA-256 round-trip verified. No simulation rerun.", "methodological_run": False, "record": rel(RESULTS / "technical_attempts.jsonl"), "amendment": rel(RESULTS / "retention_amendment.json")},
        ],
        "checkpoint": {"status": checkpoint.get("status"), "completed": checkpoint.get("completed", []),
                       "active": checkpoint.get("active"), "max_parallel_jobs": checkpoint.get("max_parallel_jobs"),
                       "resource_floor_gib": checkpoint.get("resource_floor_gib")},
        "storage": {"pilot_directory_bytes": sum(p.stat().st_size for p in PILOT.rglob("*") if p.is_file()),
                    "free_bytes": shutil.disk_usage(ROOT).free, "free_gib": shutil.disk_usage(ROOT).free / (1024**3),
                    "retained_policy": "compressed raw vectors/traces and compact per-run derivatives retained; no old pilot data deleted"},
        "conclusion": {"candidate_selected": False, "reason": "No TAS candidate passed all application acceptance gates in the seed-41 screening; no conditionally authorized follow-up was triggered.",
                       "result_classification": "no viable candidate among the three prespecified candidates in this pilot space; not a general impossibility result", "candidate_any_seed41_pass": all_candidates_pass},
    }
    json_path = RESULTS / "pilot_results.json"
    json_path.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    audited_ledger = RESULTS / "runs_audited.jsonl"
    with audited_ledger.open("w") as f:
        for e in entries:
            f.write(json.dumps({
                "execution_id": e["execution_id"], "variant": e["variant"],
                "source_classification": e["source_classification"], "source_result": e["source_result"],
                "simulation_valid": e["simulation_valid"], "application_viable": e["application_viable"],
                "stability_viable": e["stability_viable"],
                "synchronization_sample_viable_direct_probe": e["synchronization_sample_viable"],
                "synchronization_continuous_status": e["synchronization_continuous_status"],
                "legacy_synchronization_export_preserved": e["synchronization_legacy_export"],
                "drops_post_warmup_and_drain": e["drops_post_warmup_and_drain"],
                "calendar_sha256": e["calendar_sha256"], "effective_profile_sha256": e["effective_profile_sha256"],
                "audited_summary": "results/pilot_results.json"
            }, separators=(",", ":"), sort_keys=True) + "\n")

    plots = RESULTS / "plots"
    plots.mkdir(exist_ok=True)
    hpc_series = []
    z3_series = []
    colors = {"B_local":"#616161", "C3_sync_control":"#1565c0", "D1_TAS":"#c62828", "D2_TAS":"#ef6c00", "D3_TAS":"#2e7d32"}
    for e in entries:
        if e["variant"] in colors:
            hpcq = e["selected_queues"].get("HPC.eth[0].macLayer.queue.queue[4]")
            z3q = e["selected_queues"].get("Z3.ZSW.eth[7].macLayer.queue.queue[4]")
            if hpcq:
                hpc_series.append((e["variant"], [v/8 for v in hpcq.get("mean_occupancy_bits_5s", [])], colors[e["variant"]]))
            if z3q:
                z3_series.append((e["variant"], [v/8 for v in z3q.get("mean_occupancy_bits_5s", [])], colors[e["variant"]]))
    write_svg_plot(plots / "hpc_tc4_queue.svg", "HPC / TC4 queue mean by 5-second bin", hpc_series, "mean occupancy (bytes)", 20000, [0,5000,10000,15000,20000])
    write_svg_plot(plots / "z3_tc4_queue.svg", "Z3 / TC4 queue mean by 5-second bin", z3_series, "mean occupancy (bytes)", 32768, [0,8192,16384,24576,32768])
    brake_series = []
    for e in entries:
        if e["variant"] in {"D1_TAS", "D2_TAS", "D3_TAS"}:
            vals=[]
            for f,rx in [("F08","BRAKE1"),("F09","BRAKE2"),("F10","BRAKE3")]:
                m=next(x for x in e["flow_metrics"] if x["flow"]==f and x["receiver"]==rx)
                vals.append(m["max_s"]*1e6)
            brake_series.append((e["variant"], vals, colors[e["variant"]]))
    write_svg_plot(plots / "brake_deadline_maxima.svg", "Brake maximum packet latency (100 µs deadline)", brake_series, "maximum latency (µs)", 120, [0,30,60,90,100,120])

    md = []
    md += ["# C4 joint GCL/CBS dimensioning pilot — results", "",
           "**Status:** exploratory and isolated. `official_c4_frozen=false`; no official C4 campaign was started. This report covers only L2/A1, seed 41. The six new simulations and two audited reused controls are complete; conditional seeds and loads were not triggered because none of D1–D3 passed the application gates.", "",
           "## Scope and validity", "",
           "The run set was B/A005, C3_sync, and D1–D3 each with TAS and with the same CBS profile but gates open. The reused controls were admitted only after hashes, profile, calendar, clock drift arguments, runtime and existing report metrics were matched. The six new runs have valid CBS instantiation and credit vectors, paired calendar signatures, and compact event/queue/gate evidence. Each checked 24 expected CBS modules and 336 class queues. Technical validity does not imply performance viability. `runs.jsonl` preserves runner-time fields; `runs_audited.jsonl` and this report contain the corrected direct-probe synchronization field. The original execution ledger is not overwritten.", "",
           "| Treatment | Source | Sim valid | Applications | Stability | Synchronization sample flag | Drops after warm-up incl. drain |", "|---|---|---:|---:|---:|---:|---:|"]
    for e in entries:
        md.append(f"| {e['variant']} | {e['source_classification']} | {e['simulation_valid']} | {e['application_viable']} | {e['stability_viable']} | {e['synchronization_sample_viable']} | {e['drops_post_warmup_and_drain']:,} |")
    md += ["", f"All new simulations used the same 60-event F21/F22 calendar in `results/calendars/seed41_events.csv`; SHA-256: `cb74a68801e037dce0480422e4371150c2c95765974b0ef3857f1633b54a600d`. The window is `[1,31)` s, with 1 s warm-up and 50 ms drain. The campaign has one job at a time. The pilot directory occupies approximately {sum(p.stat().st_size for p in PILOT.rglob('*') if p.is_file())/(1024**3):.1f} GiB, filesystem free space is {shutil.disk_usage(ROOT).free/(1024**3):.1f} GiB, and current available memory is {float(Path('/proc/meminfo').read_text().split('MemAvailable:')[1].split()[0])/(1024**2):.1f} GiB; the 40-GiB storage floor was respected.", "",
           "## Candidate profiles and analytical status", "",
           "Candidate construction was frozen before simulation. The period is 100 µs; TC4 and TC7 open durations are D1 90/20 µs, D2 85/25 µs, D3 82/30 µs, with explicit overlap, implicit guard band, and fixed local-clock phase rules. Reservations were dimensioned from the greater of measured historical queue-bit demand or permanent catalog queue-bit demand with a 20% headroom target over estimated eligible credit time. The eligible-time formula subtracts gate overlap, a 12.4 µs frame guard, and 1 µs phase allowance. This gives an optimistic service estimate only; there is no defensible analytical lower bound. Candidates are empirical probes, not analytically guaranteed.", "",
           "| Candidate | TC4 open | TC7 open | HPC/TC4 idleSlope | CSW eth1/2 TC4 | CSW eth3 TC4 | Z3 eth7 TC4 | 75% cap | Optimistic upper service HPC / CSW1 / CSW3 |", "|---|---:|---:|---:|---:|---:|---:|---|---|"]
    for cid,c in candidates.items():
        prof=c['profile_bps']; serv=c['service_by_port']; cap=c['all_port_caps_pass']
        md.append(f"| {cid} | {c['gcl']['tc4_open_us']:.0f} µs | {c['gcl']['tc7_open_us']:.0f} µs | {prof['HPC.eth[0]/TC4']/1e6:.3f} Mb/s | {prof['CSW.eth[1]/TC4']/1e6:.3f} Mb/s | {prof['CSW.eth[3]/TC4']/1e6:.3f} Mb/s | {prof['Z3.ZSW.eth[7]/TC4']/1e6:.3f} Mb/s | {cap} | {serv['HPC.eth[0]']['optimistic_service_upper_bound_bps']/1e6:.2f} / {serv['CSW.eth[1]']['optimistic_service_upper_bound_bps']/1e6:.2f} / {serv['CSW.eth[3]']['optimistic_service_upper_bound_bps']/1e6:.2f} Mb/s |")
    md += ["", "All aggregate port caps passed the 75% ceiling without clipping. D1–D3 keep the local F13 reservation at 28.152 Mb/s, +2% over A005; no TAS was added to Z3 eth7. Ratios to C3/A005 and all per-port sums, headroom and service assumptions are retained in `results/pilot_results.json` under `candidate_designs`.", "",
           "| Candidate | Egress / TC4 | idleSlope | Ratio to C3 | Ratio to A005 | Total CBS / port rate | Headroom to 75% |", "|---|---|---:|---:|---:|---:|---:|"]
    for cid,c in candidates.items():
        for port in ["HPC.eth[0]", "CSW.eth[1]", "CSW.eth[2]", "CSW.eth[3]"]:
            key=f"{port}/TC4"; svc=c["service_by_port"][port]; cap=c["port_caps"][port]
            md.append(f"| {cid} | {key} | {c['profile_bps'][key]/1e6:.3f} Mb/s | {svc['ratio_to_C3']:.3f}× | {svc['ratio_to_A005']:.3f}× | {cap['CBS_sum_bps']/1e6:.3f} / {cap['physical_rate_bps']/1e6:.0f} Mb/s ({100*cap['cap_fraction']:.2f}%) | {cap['headroom_bps_to_75pct']/1e6:.3f} Mb/s |")
    md += ["", "The aggregate-port sums include every CBS class on that port, not only TC4. The service figures above remain optimistic upper estimates, not lower guarantees.", "",
           "## Application outcomes", "",
           "| Candidate | Mode | F08 max / misses | F09 max / misses | F10 max / misses | F21 loss | F22 loss | Total queue-overflow drops |", "|---|---|---:|---:|---:|---:|---:|---:|"]
    for cid in candidates:
        for mode in ["TAS","noTAS"]:
            e=next(x for x in entries if x['variant']==f'{cid}_{mode}')
            flows={x['flow']:x for x in e['flow_metrics'] if x['receiver'] in ['BRAKE1','BRAKE2','BRAKE3','Z3.ZCPU']}
            def fm(fid,rx): return next(x for x in e['flow_metrics'] if x['flow']==fid and x['receiver']==rx)
            f8,f9,f10=fm('F08','BRAKE1'),fm('F09','BRAKE2'),fm('F10','BRAKE3')
            f21,f22=fm('F21','Z3.ZCPU'),fm('F22','Z3.ZCPU')
            md.append(f"| {cid} | {mode} | {f8['max_s']*1e6:.3f} µs / {f8['deadline_misses_received']:,} | {f9['max_s']*1e6:.3f} µs / {f9['deadline_misses_received']:,} | {f10['max_s']*1e6:.3f} µs / {f10['deadline_misses_received']:,} | {f21['packet_loss_ratio']*100:.2f}% | {f22['packet_loss_ratio']*100:.2f}% | {e['drops_post_warmup_and_drain']:,} |")
    md += ["", "D1, D2 and D3 with TAS all missed F08 and F09 deadlines; D3 was closest but still had four F08 misses (max 100.652 µs) and 14 F09 misses (max 100.702 µs), against the 100 µs deadline. The noTAS controls met brake packet deadlines, but are not C4 candidates and still lost F21/F22 packets. Across candidates, D3 had the least transient loss, but remained materially lossy (30.57% F21 and 37.14% F22 with TAS). Thus no candidate met the complete application gates. These comparisons do not establish superiority over C3: candidate−C3 combines TAS and CBS resizing; candidate−noTAS isolates the gates at fixed reservations.", "",
           "In all six new runs, the queue-overflow counters localize the confirmed drops to `CSW.eth[3]/TC4` (D1/D2/D3 TAS: 48,559/44,539/41,107; noTAS: 37,701/31,745/27,089). The counters are queue aggregates, so they do not assign every individual dropped packet to F21, F22 or another flow. F21/F22 offer/receive deficits are reported per flow; their packets are not pending at the end, but do not equate the flow deficit one-to-one with the queue's aggregate drop count.", "",
           "Paired differences are shown below; positive loss differences mean more loss than the comparator. All entries use the same seed-41 calendar. Max-latency deltas are in µs, transient-loss deltas in percentage points.", "",
           "| Candidate | Contrast | Δ total drops | Δ F08 max | Δ F09 max | Δ F10 max | Δ F21 loss | Δ F22 loss |", "|---|---|---:|---:|---:|---:|---:|---:|"]
    for cid,items in contrasts.items():
        for key,label in [("TAS_minus_C3_sync","TAS − C3_sync"),("TAS_minus_noTAS","TAS − noTAS (gate effect at fixed CBS)"),("noTAS_minus_C3_sync","noTAS − C3_sync (CBS resizing without TAS)")]:
            c=items[key]
            md.append(f"| {cid} | {label} | {c['queue_overflow_drops_delta']:+,} | {c['F08_max_latency_us_delta']:+.3f} | {c['F09_max_latency_us_delta']:+.3f} | {c['F10_max_latency_us_delta']:+.3f} | {c['F21_loss_percentage_points_delta']:+.2f} pp | {c['F22_loss_percentage_points_delta']:+.2f} pp |")
    md += ["", "The TAS−noTAS contrast shows the cost of the gates at equal reservations in this cell; noTAS−C3_sync shows the cost of CBS resizing without TAS. Candidate−C3_sync combines both changes and must not be interpreted as a pure TAS effect.", "",
           "All 22 flows and receivers, packet/image denominators, misses, p99, maxima, goodput and per-flow gate flags are included for each treatment in the JSON. Cameras keep packet metrics separate from image-completion metrics. F21/F22 loss is counted as failure to deliver by the observation end, with pending populations preserved separately in the run records.", "",
           "## Queue stability and F13", "",
           "Queue plots use the preserved six 5 s means (bytes); brake maxima are packet latency from the per-flow sample populations.", "",
           "![HPC TC4 queue means](plots/hpc_tc4_queue.svg)", "",
           "![Z3 TC4 queue means](plots/z3_tc4_queue.svg)", "",
           "![Brake maximum latency](plots/brake_deadline_maxima.svg)", "",
           "All six D1–D3 runs passed the existing stability proxy; the audited B/A005 control reproduces the sustained HPC/TC4 growth and fails that proxy. This demonstrates that the joint GCL/reservation designs suppress the observed HPC backlog for this seed, but does not override their application failures.", "",
           "The natural F13 episode analysis used the preregistered event threshold (> baseline + 2,048 bits), recovery within 5 s while F13 remained active, and zero measurement-window queue drops. Every observed episode completed. In D1/D2/D3 TAS there were 71/67/68 episodes, with longest recoveries 443/430/413 ms and peaks 29,696/28,928/27,904 bytes. No F13 queue overflow drops were observed. The 53-frame historical backlog was not recreated; this supports only recovery of the naturally observed episodes in these seed-41 traces, not a guarantee for arbitrary 53-frame backlog. Full episode data and rule are in `results/f13_natural_episode_analysis.json`.", "",
           "## Synchronization and limitations", "",
           "The legacy `pilot_vector_audit.synchronization` summary reports millisecond-scale excursions, but it conflicts with the preserved direct probe. Reprocessing `clock_precision.csv.gz` shows simultaneous native-tick clock reads: across all six new runs, periodic 1 ms samples and clock-change snapshots remain below 1 µs (D1_TAS maxima are 20–50 ns by node). The direct-probe observed-sample criterion passes. This does not establish continuous conformity: periodic coverage is 1 ms and event snapshots do not cover every instant. The old derived summary is retained per run as `synchronization_legacy_export`, not used as the current result. The discrepancy is localized to the legacy derived synchronization result; its exact parser step was not independently reconstructed here. The direct probe subtracts simultaneous native clock ticks before text conversion.", "",
           "No candidate was selected, so the conditional seed 43/47 checks, L0/A0 and L1/A1 extrapolations, and artificial-backlog tests were not executed. The result is **no viable candidate among the three prespecified designs in this pilot space**, not proof that C4 is generally impossible. Any next study needs a prospectively revised gate/reservation design that preserves brake deadlines while controlling F21/F22 loss, then independent seed checks. No official C4 profile is frozen.", "",
           "## Reproduction and retained evidence", "",
           "The run commands, effective parameters, software versions, profile hashes, gate evidence, credit vectors and retained artifact hashes are in `results/pilot_results.json`; the authoritative preregistration is `protocol.md` plus `results/plan.json` and `results/protocol_manifest.json`. Rebuild the report with `python3 simulations/pilot/c4_joint_dimensioning/consolidate_results.py`. No simulation is started by that command.", "",
           f"Generated {datetime.now(timezone.utc).isoformat()}.", ""]
    (RESULTS / "analysis.md").write_text("\n".join(md))
    manifest = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "generator": rel(PILOT / "consolidate_results.py"), "generator_sha256": sha(PILOT / "consolidate_results.py"),
        "outputs": {"analysis.md": sha(RESULTS / "analysis.md"), "pilot_results.json": sha(json_path),
                    "runs_audited.jsonl": sha(audited_ledger)},
        "inputs": {"runs.jsonl": sha(RESULTS / "runs.jsonl"), "dimensioning.json": sha(RESULTS / "dimensioning.json"),
                   "f13_natural_episode_analysis.json": sha(RESULTS / "f13_natural_episode_analysis.json"),
                   "plan.json": sha(RESULTS / "plan.json"), "protocol_manifest.json": sha(RESULTS / "protocol_manifest.json"),
                   "protocol.md": sha(PILOT / "protocol.md"), "README.md": sha(PILOT / "README.md"),
                   "checkpoint.json": sha(RESULTS / "checkpoint.json")},
    }
    (RESULTS / "analysis_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"analysis": rel(RESULTS / "analysis.md"), "json": rel(json_path), "manifest": rel(RESULTS / "analysis_manifest.json"),
                      "treatments": len(entries), "new_simulations": len(new_runs), "all_candidate_pass": all_candidates_pass}, indent=2))


if __name__ == "__main__":
    main()
