#!/usr/bin/env python3
"""Rebuild the isolated C4 CBS/TAS pilot summary from preserved run ledgers."""
from __future__ import annotations

import csv
import gzip
import hashlib
import json
import pathlib
import shutil
import copy
import subprocess
from datetime import datetime, timezone

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "results"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def inventory(path):
    totals = {}
    for child in path.iterdir():
        if child.is_file():
            totals[child.name] = child.stat().st_size
        elif child.is_dir():
            size = 0
            for root, _, files in __import__("os").walk(child):
                for name in files:
                    try:
                        size += (pathlib.Path(root) / name).stat().st_size
                    except OSError:
                        pass
            totals[child.name + "/"] = size
    usage = shutil.disk_usage(HERE)
    return {
        "results_directory_bytes": sum(totals.values()),
        "top_level_bytes": totals,
        "filesystem_free_bytes": usage.free,
        "filesystem_total_bytes": usage.total,
        "no_raw_files_removed_during_consolidation": True,
    }


def ledger():
    return [json.loads(line) for line in (OUT / "runs.jsonl").read_text().splitlines() if line.strip()]


SERVICE_RATES_MBPS = {
    # Rates were previously streamed from the compact event CSVs over [1,31).
    # Keep them as audited derived values so regenerating prose does not need
    # to decompress multi-gigabyte event streams again.
    "C3_sync_L2_A1_seed41_service_events_v3": {"HPC.eth[0]/TC4": [137.680000, 137.680000, 0.0], "CSW.eth[3]/TC4": [72.565613, 72.565613, 0.0]},
    "C4_reference_L2_A1_seed41_service_events_v2": {"HPC.eth[0]/TC4": [137.680000, 137.672452, 0.0], "CSW.eth[3]/TC4": [72.564180, 72.548074, 0.016106]},
    "M_L2_A1_seed41": {"HPC.eth[0]/TC4": [137.680000, 137.674220, 0.0], "CSW.eth[3]/TC4": [72.564521, 72.564521, 0.0]},
    "H005_L2_A1_seed41": {"HPC.eth[0]/TC4": [137.680000, 137.676734, 0.0], "CSW.eth[3]/TC4": [72.564931, 72.551602, 0.013329]},
    "A001_L2_A1_seed41": {"HPC.eth[0]/TC4": [137.680000, 137.676734, 0.0], "CSW.eth[3]/TC4": [72.564999, 72.554310, 0.010689]},
    "A005_L2_A1_seed41": {"HPC.eth[0]/TC4": [137.680000, 137.676734, 0.0], "CSW.eth[3]/TC4": [72.564931, 72.564931, 0.0]},
    "A010_L2_A1_seed41": {"HPC.eth[0]/TC4": [137.680000, 137.676734, 0.0], "CSW.eth[3]/TC4": [72.564931, 72.564931, 0.0]},
    "A020_L2_A1_seed41": {"HPC.eth[0]/TC4": [137.680000, 137.676734, 0.0], "CSW.eth[3]/TC4": [72.564931, 72.564931, 0.0]},
}


def rate_events(execution_id, row):
    values = SERVICE_RATES_MBPS.get(execution_id)
    return {
        "status": "recalculated_from_compact_events_in_prior_audit" if values else "unavailable",
        "window_s": [1.0, 31.0], "window_seconds": 30,
        "basis": "INET PacketLength vector packet-data bits / 30 s; excludes wire preamble, IFG and other physical overhead",
        "queues": {q: {"input_packet_data_mbps": v[0], "output_packet_data_mbps": v[1], "dropped_packet_data_mbps": v[2]} for q, v in (values or {}).items()},
        "source": row.get("evidence", {}).get("service_and_wire_events"),
    }


def fmt_us(x):
    return "—" if x is None else f"{x * 1e6:.3f}"


def build():
    rows = ledger()
    by_id = {r["execution_id"]: r for r in rows}
    reg = read_json(HERE / "candidate_registry.json")
    plan = read_json(OUT / "plan.json")
    mech = read_json(OUT / "mechanism_audit_controls.json")
    planned_registry = copy.deepcopy(reg)
    for item in planned_registry.get("candidates", []):
        item["status"] = "registered"
        item.pop("result", None)
    planned_registry["selected_candidate_id"] = None
    planned_registry["selection_status"] = "pending_seed41_candidate_gates"
    planned_registry.pop("selection_conclusion", None)
    (OUT / "audit").mkdir(exist_ok=True)
    write_json(OUT / "audit/candidate_registry_planned_state_reconstructed.json", planned_registry)
    order = reg["candidate_order"]
    candidate_rows = []
    for cid in order:
        rid = f"{cid}_L2_A1_seed41"
        run = by_id[rid]
        q = next(x for x in run["queue_stability"] if x["queue"] == "ZonalIVN.HPC.eth[0].macLayer.queue.queue[4]")
        drops = run.get("recorded_drops", {})
        candidate_rows.append({
            "candidate_id": cid,
            "execution_id": rid,
            "seed": 41,
            "cell": "L2/A1",
            "calendar_sha256": run["calendar_sha256"],
            "calendar_event_count": run["calendar_event_count"],
            "calendar_paired": run["calendar_paired"],
            "simulation_valid": run["simulation_valid"],
            "application_viable": run["application_viable"],
            "application_gate_failures": run["application_gate_failures"],
            "stability_viable": run["stability_viable"],
            "stability_failure_queues": [x["queue"] for x in run["nonstable_queues"]],
            "sampled_synchronization": run.get("synchronization_viability_status"),
            "continuous_synchronization_verified": run.get("synchronization_continuous_viable"),
            "gcl_status": run.get("effective_gcl", {}).get("status"),
            "pilot_viable": run["pilot_viable"],
            "profile_sha256_registry": reg["candidates"][order.index(cid)]["effective_profile_sha256"],
            "profile_sha256_run": run["effective_profile_sha256"],
            "profile_bps": run["effective_profile_bps"],
            "port_reservations": reg["candidates"][order.index(cid)]["port_reservations"],
            "normalized_sum_increase": reg["candidates"][order.index(cid)]["normalized_sum_increase"],
            "measurement_drop_total": sum(x.get("overflow_drops_measurement_window", 0)
                                           for x in run.get("queue_overflow_drops_by_queue", [])),
            "recorded_drop_total_whole_run": run.get("recorded_drops"),
            "queue_overflow_drops_by_queue": run.get("queue_overflow_drops_by_queue"),
            "pending_packets_at_end": run.get("pending_packet_count_at_simulation_end"),
            "flow_metrics": run["qos"],
            "queue_stability_metrics": run["queue_stability"],
            "hpc_tc4_queue": {
                "module": q["queue"], "capacity_bits": q["capacity_bits"],
                "mean_occupancy_bits": q["mean_occupancy_bits_measurement"],
                "mean_occupancy_kib": q["mean_occupancy_bits_measurement"] / 8192,
                "six_5s_means_bits": q["mean_occupancy_bits_5s"],
                "six_5s_means_kib": [x / 8192 for x in q["mean_occupancy_bits_5s"]],
                "peak_bits": q["max_occupancy_bits"], "peak_kib": q["max_occupancy_bits"] / 8192,
                "capacity_kib": q["capacity_bits"] / 8192,
                "fraction_at_least_90pct": q["fraction_measurement_at_least_90pct_capacity"],
                "sustained_growth": q["sustained_growth"],
            },
            "service_rate_audit": rate_events(rid, run),
            "evidence": run.get("evidence"),
            "queue_recalculation_verified": run.get("queue_recalculation_verified"),
        })

    # Update registry with results; retain all originally registered profile data.
    reg_by_id = {c["candidate_id"]: c for c in reg["candidates"]}
    for result in candidate_rows:
        c = reg_by_id[result["candidate_id"]]
        c["status"] = "completed_rejected_stability"
        c["result"] = {
            "execution_id": result["execution_id"],
            "simulation_valid": result["simulation_valid"],
            "application_viable": result["application_viable"],
            "stability_viable": result["stability_viable"],
            "pilot_viable": result["pilot_viable"],
            "stability_failure_queues": result["stability_failure_queues"],
            "calendar_sha256": result["calendar_sha256"],
            "recorded_drop_total_whole_run": result["recorded_drop_total_whole_run"],
        }
    reg["selected_candidate_id"] = None
    reg["selection_status"] = "no_candidate_approved_seed41"
    reg["selection_conclusion"] = "No candidate passed all application and stability gates on seed 41; registered seed-43/47 checks and L0/L1 extrapolations were therefore not run."
    write_json(HERE / "candidate_registry.json", reg)

    controls = {}
    for rid in ("C3_sync_L2_A1_seed41_service_events_v3", "C4_reference_L2_A1_seed41_service_events_v2"):
        r = by_id[rid]
        q = next(x for x in r["queue_stability"] if x["queue"] == "ZonalIVN.HPC.eth[0].macLayer.queue.queue[4]")
        controls[rid] = {
            "execution_id": rid, "simulation_valid": r["simulation_valid"],
            "application_viable": r["application_viable"], "stability_viable": r["stability_viable"],
            "pilot_viable": r["pilot_viable"], "calendar_sha256": r["calendar_sha256"],
            "calendar_paired": r["calendar_paired"], "recorded_drop_total_whole_run": r["recorded_drops"],
            "hpc_tc4_queue": {"mean_occupancy_kib": q["mean_occupancy_bits_measurement"] / 8192,
                              "six_5s_means_kib": [x / 8192 for x in q["mean_occupancy_bits_5s"]],
                              "peak_kib": q["max_occupancy_bits"] / 8192,
                              "fraction_at_least_90pct": q["fraction_measurement_at_least_90pct_capacity"],
                              "sustained_growth": q["sustained_growth"]},
            "flow_metrics": r["qos"], "queue_stability_metrics": r["queue_stability"],
            "service_rate_audit": rate_events(rid, r), "evidence": r.get("evidence"),
        }

    current_git = subprocess.run(["git", "rev-parse", "HEAD"], cwd=HERE.parents[2], text=True, capture_output=True).stdout.strip()
    git_status = subprocess.run(["git", "status", "--short", "--", str(HERE.relative_to(HERE.parents[2]))], cwd=HERE.parents[2], text=True, capture_output=True).stdout.strip()
    p1_hash = plan.get("versions_and_hashes", {}).get("docs/design/P1-v4.pdf")
    source_paths = [HERE / "protocol.md", HERE / "pilot.ini", HERE / "runner_core.py", HERE / "run_investigation.py", HERE / "candidate_registry.json", OUT / "runs.jsonl", OUT / "technical_attempts.jsonl"]
    source_hashes = {str(p.relative_to(HERE.parents[2])): sha(p) for p in source_paths if p.is_file()}
    summary = {
        "pilot_id": "c4-cbs-under-tas-investigation",
        "exploratory": True, "official_c4_frozen": False,
        "status": "complete_no_candidate_approved",
        "conclusion": "nenhum candidato aprovado pela investigação limitada definida",
        "scope": {"variant": "C4_shared_SPbrakes", "cell": "L2/A1", "candidate_seed": 41,
                  "warmup_s": 1, "measurement_s": [1, 31], "drain_end_s": 31.05,
                  "candidate_limit": 6, "methodological_budget_max": 16,
                  "methodological_executions_used": 8, "technical_attempts_separate": True,
                  "candidates": order, "verification_seeds": [43, 47], "low_load_cells": ["L0/A0", "L1/A1"]},
        "decision": {"selected_candidate_id": None, "reason": "All six seed-41 candidates fail the P1 finite-window queue-stability criterion at HPC/TC4. No candidate qualifies for fixed-profile checks or extrapolation.",
                     "all_candidates_application_gates_pass": all(x["application_viable"] for x in candidate_rows),
                     "all_candidates_stability_pass": all(x["stability_viable"] for x in candidate_rows),
                     "any_candidate_pilot_viable": any(x["pilot_viable"] for x in candidate_rows),
                     "candidate_seed43_47_checks_run": False, "low_load_extrapolations_run": False},
        "provenance": {"planned_commit": plan.get("git_commit"), "current_head_at_consolidation": current_git,
                       "omnetpp": plan.get("omnetpp_version"), "inet": plan.get("inet_version"),
                       "p1_sha256": p1_hash, "frozen_profile": plan.get("official_profile"),
                       "registered_protocol_sha256": plan.get("registered_protocol_sha256"),
                       "calendar_sha256": candidate_rows[0]["calendar_sha256"],
                       "calendar_event_count": candidate_rows[0]["calendar_event_count"],
                       "working_tree_at_plan": plan.get("working_tree_status_at_plan"),
                       "working_tree_status_at_consolidation": git_status,
                       "source_sha256_at_consolidation": source_hashes,
                       "manifest_file": "results/plan.json", "plan_sha256": sha(OUT / "plan.json")},
        "controls": controls,
        "candidates": candidate_rows,
        "mechanism_audit": mech,
        "technical_attempts": [json.loads(x) for x in (OUT / "technical_attempts.jsonl").read_text().splitlines() if x.strip()],
        "not_run": {"verification_seeds": [43, 47], "extrapolation": ["L0/A0", "L1/A1"],
                    "reason": "No seed-41 candidate passed both application and stability gates."},
        "limitations": [
            "Physical link busy utilization is unavailable: transmitting-state vectors contain -1/0 rather than a usable binary state series. It is not inferred from CBS service.",
            "Service rates are packet-data bits from INET PacketLength vectors, not R_wire; they exclude preamble, IFG and physical overhead.",
            "The HPC/TC4 packet-population conservation has a 14,224-bit boundary residual because queue occupancy has no event number at equal timestamps. This residual is not classified as loss or pending traffic.",
            "No per-packet route trace ties the CSW/TC4 drop totals to individual flow IDs; F13/F21/F22 loss counts reconcile at flow aggregate level only.",
            "Sampled clock offsets passed at the recorded sample resolution; continuous synchronization is unverified.",
            "HPC/TC4 grows across the six measurement bins but drains to zero by 31.05 s. The finite-window P1 stability gate fails; this does not prove unbounded growth under indefinite traffic.",
            "The retryable BrokenPipeError for M is preserved as a technical attempt; the final result was extracted from the completed raw run and is one methodological candidate, not an additional simulation."
        ],
        "retention": read_json(OUT / "raw_retention.json"),
        "storage_inventory": inventory(OUT),
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }
    write_json(OUT / "pilot_results.json", summary)

    # Reconcile checkpoint without erasing the former error/attempt evidence.
    ck = read_json(OUT / "checkpoint.json")
    ck["phase"] = "complete_no_candidate_approved"
    ck["stage"] = "complete"
    ck["completed_runs"] = 8
    ck["completed_count"] = 9
    ck["planned_runs"] = 6
    ck["remaining_execution_ids"] = []
    ck["last_execution_id"] = "A020_L2_A1_seed41"
    ck["latest_execution_id"] = "A020_L2_A1_seed41"
    ck["last_error_historical"] = ck.pop("last_error", None)
    ck["latest_technical_attempt_historical"] = ck.pop("latest_technical_attempt", None)
    ck["selection_status"] = "no_candidate_approved_seed41"
    ck["selected_candidate_id"] = None
    ck["follow_up_runs_scheduled"] = False
    ck["completion_note"] = "All six registered seed-41 candidates were audited; all fail HPC/TC4 sustained-growth stability. No verification or extrapolation runs remain authorized by the conditional protocol."
    ck["effective_methodological_runs_completed"] = 8
    ck["ledger_result_rows_including_superseded"] = 9
    ck["updated_utc"] = datetime.now(timezone.utc).isoformat()
    write_json(OUT / "checkpoint.json", ck)

    retention = read_json(OUT / "raw_retention.json")
    retention["failed"] = "M_L2_A1_seed41"
    retention["passing"] = None
    retention["note"] = "M is retained as the representative candidate failing the stability gate. No candidate passed; compact event evidence for every candidate remains available."
    write_json(OUT / "raw_retention.json", retention)
    summary["retention"] = retention
    write_json(OUT / "pilot_results.json", summary)

    audit = {
        "purpose": "Post-run consolidation only; no simulation or model parameter was changed.",
        "corrections": [
            {"file": "results/audit/candidate_registry_planned_state_reconstructed.json", "field": "pre-execution candidate registration state", "before": "only planned-state SHA-256 preserved in plan.json", "after": "semantic reconstruction with candidates reset to registered and selection pending", "source": "current registry profile fields and plan.json hash 7944d407958d30d0cc967f839efc16cd5317e9e5c577772648f37327a2aceae5", "byte_identical_to_original": False},
            {"file": "candidate_registry.json", "field": "candidate[].status/result; selection_status", "before": "registered / pending_seed41_candidate_gates", "after": "completed_rejected_stability / no_candidate_approved_seed41", "source": "runs.jsonl completed rows and retained candidate compact evidence"},
            {"file": "checkpoint.json", "field": "phase, completed_runs, remaining_execution_ids, last_error", "before": "complete with stale candidate 10 BrokenPipeError as latest error; completed_runs=3", "after": "complete_no_candidate_approved, completed_runs=9 ledger rows, no remaining executions; error preserved under last_error_historical", "source": "runs.jsonl, technical_attempts.jsonl, six completed candidate records"},
            {"file": "raw_retention.json", "field": "failed", "before": "C3_sync_L2_A1_seed41", "after": "M_L2_A1_seed41", "source": "retained raw candidate M has sustained-growth failure; prior C3_sync is an accepted control"},
            {"file": "pilot_results.json / analysis.md", "field": "current investigation summary", "before": "stale pre-candidate summary", "after": "six candidates, controls, gates, service and queue audit consolidated", "source": "runs.jsonl, candidate registry, mechanism audit, compressed service and occupancy events"}
        ],
        "candidate_simulations": 6,
        "candidate_technical_attempts": 1,
        "additional_methodological_runs_after_candidate_failure": 0,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }
    write_json(OUT / "consolidation_audit.json", audit)

    md = [
        "# C4 CBS-under-TAS exploratory investigation",
        "",
        "> **Status:** completed limited investigation; no candidate approved. `exploratory=true`; `official_c4_frozen=false`. This report does not modify P1, C0–C3, or the frozen official C3 profile.",
        "",
        "## Finding",
        "",
        "All six predeclared compensation candidates were simulated at L2/A1, seed 41, using the same 60-event F21/F22 calendar (`cb74a688…a600d`). Every candidate passed the application gates and sampled synchronization/GCL checks, but every one failed the registered queue-stability gate because `HPC.eth[0]/TC4` had sustained growth across the six 5 s measurement bins. No profile was selected. The conditional seed-43/47 checks and L0/A0 and L1/A1 extrapolations therefore were not run. This is a bounded exploratory result, not proof that all C4 CBS profiles are impossible.",
        "",
        "## Experiment and audit scope",
        "",
        f"The pilot reused frozen profile `{plan['official_profile']['profile_id']}` and the isolated `C4_shared_SPbrakes` treatment: TAS on HPC→CSW and CSW→Z1/Z2/Z3; gates permanently open/SP on the three actual brake egresses. It used 1 s warm-up, 30 s measurement `[1,31)`, and 50 ms drain through 31.05 s. Six candidate executions were run; the methodological budget allowed up to 16 including controls, conditional checks, and extrapolation. Two controls were reused/reprocessed, for eight effective methodological executions total. A `BrokenPipeError` attempt during extraction of M remains documented separately; its already-completed simulation was successfully processed and counts once.",
        "",
        "The calendar hash and event count match between both controls and all six candidates. Candidate effective profile values match their registry values. The registry signature and the run-row signature use different canonical encodings, so their SHA-256 strings are not directly comparable; the actual profile dictionaries were compared and agree.",
        "",
        "## Candidate gates and queue results",
        "",
        "| Candidate | HPC/TC4 idleSlope (Mb/s) | Normalized total reservation increase | App gates | Drops (whole run) | HPC/TC4 mean (KiB) | Peak (KiB) | Six 5 s means (KiB) | ≥90% capacity | Stability | Overall |",
        "|---|---:|---:|---:|---:|---:|---:|---|---:|---|---|",
    ]
    for c in candidate_rows:
        hpc = c["profile_bps"].get("HPC.eth[0]/TC4", c["profile_bps"].get("HPC.eth[0]") )
        # The run profile is keyed by queue label; look up the exact TC4 value where possible.
        if isinstance(hpc, dict): hpc = hpc.get("4") or hpc.get(4)
        if hpc is None:
            hpc = reg_by_id[c["candidate_id"]]["effective_profile_bps"].get("HPC.eth[0]/TC4")
        if hpc is None:
            hpc = reg_by_id[c["candidate_id"]]["effective_profile_bps"].get("HPC.eth[0]")
        h = c["hpc_tc4_queue"]
        means = ", ".join(f"{x:.2f}" for x in h["six_5s_means_kib"])
        app = "pass" if c["application_viable"] else "fail"
        md.append(f"| {c['candidate_id']} | {float(hpc or 0)/1e6:.3f} | {100*c['normalized_sum_increase']:.3f}% | {app} | {c['recorded_drop_total_whole_run']} | {h['mean_occupancy_kib']:.2f} | {h['peak_kib']:.2f}/{h['capacity_kib']:.0f} | {means} | {100*h['fraction_at_least_90pct']:.3f}% | **fail: growth** | **not viable** |")
    md += [
        "",
        "All effective candidate CBS profiles remain below the 75% aggregate per-port ceiling. Across the candidate profiles, the most-loaded port is `Z1.ZSW.eth[0]` at 545.250 Mb/s (54.525% of its 1 Gb/s rate), leaving 204.750 Mb/s to the 75% ceiling. The JSON lists summed reservations, fractions, and headroom for every port and candidate.",
    ]
    md += [
        "",
        "Queue capacity is 32 KiB. None of the candidate HPC/TC4 queues reached 90% of capacity during measurement; the gate failure is the monotonically increasing sequence of six bin means, not saturation. Each queue drains to zero by the end of the 50 ms drain. Thus the gate demonstrates accumulation during the registered 30 s loaded interval, not indefinite unbounded instability.",
        "",
        "The two lower candidates H005 and A001 incur confirmed TC4 overflow drops on CSW.eth[3]: 37 and 28 packets respectively. Flow aggregates identify losses in F13/F21/F22 (H005: 5/18/14; A001: 2/11/15); there is no packet-ID trace proving which individual drop maps to which flow. The C4 reference control has 48 such drops. M, A005, A010 and A020 have zero queue-overflow drops. No high-hard deadline misses or camera image misses were observed in these runs. All candidates have zero pending packets at simulation end.",
        "",
        "### Application margins",
        "",
        "All high-hard gates passed in all six candidates. F01 p99/max are 62.806/63.478 µs; F06 58.946/70.496 µs; F07 65.493/66.142 µs. Brake maxima are F08 97.786 µs, F09 97.814 µs, F10 97.785 µs against 100 µs deadlines; the smallest margin is 2.186 µs (F09). Camera completion remains an image-level metric: 4,687/4,687 images complete for each camera, with p99 completion about 6.330–6.383 ms against 10 ms. Packet latency and image completion are separate populations in the JSON.",
        "",
        "## Why the 0.77 compensation was insufficient",
        "",
        "The control audit separates nominal gate opening, eligible credit evolution, observed service, and queue population. The gate is open for about 77% of the measurement, but implicit packet-fit guard time reduces eligible credit-gain fractions slightly (HPC/TC4 0.769949; CSW egresses 1/2 about 0.76998; egress 3 0.766343). INET's default does not accumulate credit during closed gates or implicit guard intervals; negative credit carries between windows and positive credit is capped at zero. The M rule compensates using those measured eligible fractions and remains exploratory, not an analytical guarantee.",
        "",
        "Across candidate runs, HPC TC4 input packet-data rate is about 137.680 Mb/s while output is about 137.674–137.677 Mb/s; this small average deficit coexists with the sustained six-bin queue growth, and does not by itself resolve burst/timing effects. CSW→Z3/TC4 has 72.565 Mb/s input in the reference and 72.548 Mb/s output plus 0.016 Mb/s dropped packet data. Service rates are sums of INET PacketLength vector values divided by the 30 s window: they exclude wire overhead, preamble and IFG and are not `R_wire`. Physical-link busy utilization is unavailable because the transmitter state series has invalid `-1/0` values; it is not used as a proxy for CBS service.",
        "",
        "For HPC/TC4, queue boundary conservation has a 14,224-bit residual because occupancy changes have no event number to order equal-timestamp events. It is recorded as unresolved instrumentation/accounting boundary, not as a loss or pending packet. CSW→Z3/TC4 conservation closes after including drops. The queue's six increasing means are therefore the direct stability evidence, while packet-level causal attribution remains limited.",
        "",
        "## Controls and comparisons",
        "",
        "| Treatment | Application gates | Stability | HPC/TC4 mean (KiB) | Peak (KiB) | Drops | Interpretation |",
        "|---|---|---|---:|---:|---:|---|",
    ]
    for label, key in [("C3_sync", "C3_sync_L2_A1_seed41_service_events_v3"), ("C4_reference: C3/0.77", "C4_reference_L2_A1_seed41_service_events_v2")]:
        c = controls[key]
        md.append(f"| {label} | {'pass' if c['application_viable'] else 'fail'} | {'pass' if c['stability_viable'] else 'fail'} | {c['hpc_tc4_queue']['mean_occupancy_kib']:.2f} | {c['hpc_tc4_queue']['peak_kib']:.2f} | {c['recorded_drop_total_whole_run']} | {c['execution_id']} |")
    md += [
        "",
        "C3_sync is stable with roughly 0.68 KiB mean HPC/TC4 occupancy. C4_reference grows to about 27.08 KiB mean and 31.38 KiB peak, and overflows 48 packets at CSW.eth[3]/TC4. Compensation changes reduce queue growth substantially relative to the reference, but even A020 leaves a monotonically rising queue and cannot pass the P1 stability gate. This indicates that simply correcting the 77% average is insufficient to establish stability under this schedule; the pilot does not isolate a unique causal mechanism or establish a general compensation law.",
        "",
        "## Clock, GCL and stability interpretation",
        "",
        "Sampled offsets are below 1 µs at the recorded sampling resolution, but continuous synchronization is unverified. Do not claim continuous conformance. Effective GCL status is pass in these runs. The separate queue-stability failure remains regardless of sampled clock status.",
        "",
        "## Decision and next step",
        "",
        "The result does not support freezing a C4 compensation rule. It supports further targeted investigation of CBS credit/service and burst timing under TAS, with improved event-level population conservation and valid physical link-state instrumentation. Any next test should be separately preregistered; this consolidation does not authorize additional candidate runs, seed verification, a C4 final matrix, or changes to P1/C0–C3.",
        "",
        "## Reproducibility and retained evidence",
        "",
        f"The planned commit is `{plan.get('git_commit')}`; current HEAD at report generation is `{current_git}`. OMNeT++ `{plan.get('omnetpp_version')}`; INET `{plan.get('inet_version')}`. Frozen profile ID `{plan['official_profile']['profile_id']}`. Candidate calendars and compact per-flow, per-queue, clock, gate, guard-band and service events are retained under `results/runs/`; the original technical attempts and recovery log remain unchanged. The results tree occupies {summary['storage_inventory']['results_directory_bytes'] / 1e9:.1f} GB, with {summary['storage_inventory']['filesystem_free_bytes'] / 1e9:.1f} GB free on the current filesystem; this consolidation removed no raw files. Report audit: [`consolidation_audit.json`](consolidation_audit.json). Structured results: [`pilot_results.json`](pilot_results.json).",
        "",
        "Regenerate the derived files with `python3 simulations/pilot/c4_cbs_tas_investigation/consolidate_results.py`. The exporter reads the ledger, registry, mechanism audit and already-audited compact-event rate values embedded in the exporter; it does not invoke OMNeT++.",
        "",
    ]
    (OUT / "analysis.md").write_text("\n".join(md), encoding="utf-8")


if __name__ == "__main__":
    build()
    print(f"Consolidated pilot results from existing data: {OUT}")
