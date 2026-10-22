#!/usr/bin/env python3
"""Recompute the preregistered F13 service-margin test from compact pilot evidence."""
from __future__ import annotations

import csv
import gzip
import hashlib
import json
import math
import pathlib
import re
import statistics
import sys
from decimal import Decimal

ROOT = pathlib.Path(__file__).resolve().parent
RESULTS = ROOT / "results"
RUNS = RESULTS / "runs"
OUT = RESULTS
TARGET_QUEUE = "ZonalIVN.Z3.ZSW.eth[7].macLayer.queue.queue[4]"
BIN_EDGES = [Decimal(x) for x in ("1", "6", "11", "16", "21", "26", "31")]
WINDOW_START = Decimal("1")
WINDOW_END = Decimal("31")
WIRE_BITS_PER_FRAME = 276 * 8
QUEUE_BITS_PER_FRAME = 256 * 8
CLOCK_TICKS_PER_SECOND = 10**12  # confirmed: 576000 ticks is 576 us at 1 Gb/s for 576 wire bits
OFFSET_LIMIT_RAW = 10**6  # 1 us at the native 1 ps SimTime scale
VARIANTS = [
    "B_local", "R_cadence", "RP_cadence_phase", "BM_recovery",
    "RPM_combined", "C3_sync_control",
]
CANDIDATES = ["R_cadence", "RP_cadence_phase", "RPM_combined"]
BM_CORRECTED_ID = "BM_recovery_L2_A1_seed41_technical_replacement_001"


def sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def json_file(path: pathlib.Path):
    return json.loads(path.read_text())


def q_state_summary(run_dir: pathlib.Path):
    meta_path = run_dir / "queue_occupancy_events.csv.gz.meta.json.gz"
    data_path = run_dir / "queue_occupancy_events.csv.gz"
    with gzip.open(meta_path, "rt") as f:
        meta = json.load(f)
    qinfo = next(q for q in meta["queues"] if q["module"] == TARGET_QUEUE)
    qidx = int(qinfo["queue_index"])
    cap = int(qinfo["capacity_bits"])
    # Keep only the 30,000 1-ms time-weighted means for the plot, plus exact 5-s
    # integral/max/boundary statistics. The original event trace remains retained.
    width = Decimal("0.001")
    bins_1ms = 30000
    integrals = [Decimal(0) for _ in range(6)]
    peaks = [0 for _ in range(6)]
    micro_integrals = [Decimal(0) for _ in range(bins_1ms)]
    q = 0
    prev_t = Decimal(0)
    boundary_states = {edge: None for edge in BIN_EDGES}
    seen = 0
    last_t = Decimal(-1)
    with gzip.open(data_path, "rt", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if int(row["queue_index"]) != qidx:
                continue
            t = Decimal(row["timestamp_s"])
            new_q = int(row["occupancy_bits"])
            if t < last_t:
                raise ValueError(f"queue event timestamps are not ordered: {t} < {last_t}")
            last_t = t
            seen += 1
            if t < WINDOW_START:
                q = new_q
                prev_t = t
                continue
            for edge in BIN_EDGES:
                if boundary_states[edge] is None and t >= edge:
                    boundary_states[edge] = q
            if t >= WINDOW_END:
                break
            # Integrate the previous state to this event, clipped to [1,31).
            lo = max(prev_t, WINDOW_START)
            hi = min(t, WINDOW_END)
            if hi > lo:
                first5 = max(0, min(5, int((lo - WINDOW_START) // Decimal(5))))
                last5 = max(0, min(5, int((hi - WINDOW_START) // Decimal(5))))
                cursor = lo
                while cursor < hi:
                    b5 = min(5, int((cursor - WINDOW_START) // Decimal(5)))
                    end5 = min(hi, BIN_EDGES[b5 + 1])
                    integrals[b5] += Decimal(q) * (end5 - cursor)
                    cursor = end5
                first1 = max(0, min(bins_1ms - 1, int((lo - WINDOW_START) / width)))
                cursor = lo
                while cursor < hi:
                    b1 = max(0, min(bins_1ms - 1, int((cursor - WINDOW_START) / width)))
                    end1 = min(hi, WINDOW_START + width * (b1 + 1))
                    micro_integrals[b1] += Decimal(q) * (end1 - cursor)
                    cursor = end1
                for b5 in range(6):
                    if lo < BIN_EDGES[b5 + 1] and hi > BIN_EDGES[b5]:
                        peaks[b5] = max(peaks[b5], q)
            q = new_q
            prev_t = t
        else:
            q31minus = q
    previous = q
    for edge in BIN_EDGES:
        if boundary_states[edge] is None:
            boundary_states[edge] = previous
        previous = boundary_states[edge]
    q1minus = boundary_states[WINDOW_START]
    q31minus = boundary_states[WINDOW_END]
    means5 = [float(v / Decimal(5)) for v in integrals]
    means1ms = [float(v / width) for v in micro_integrals]
    return {
        "queue": TARGET_QUEUE,
        "queue_index": qidx,
        "capacity_bits": cap,
        "event_rows_scanned_for_queue": seen,
        "boundary_convention": "Q(1-) and Q(31-) from right-continuous occupancy, events at boundary excluded from preceding interval",
        "Q_1minus_bits": q1minus,
        "Q_31minus_bits": q31minus,
        "delta_Q_bits": q31minus - q1minus,
        "boundary_states_bits": [boundary_states[edge] for edge in BIN_EDGES],
        "mean_occupancy_bits_5s": means5,
        "max_occupancy_bits_5s": peaks,
        "mean_occupancy_bits_1ms": means1ms,
        "measurement_peak_bits": max(peaks, default=0),
        "capacity_fraction_peak": max(peaks, default=0) / cap,
    }


def trace_f13_summary(run_dir: pathlib.Path):
    trace = run_dir / "packet_events.csv.gz"
    qstats = [
        {"push": 0, "pull": 0, "drop": 0, "remove": 0,
         "push_queue_bits": 0, "pull_queue_bits": 0,
         "drop_queue_bits": 0, "remove_queue_bits": 0}
        for _ in range(6)
    ]
    totals = {k: 0 for k in ("push", "pull", "drop", "remove")}
    clock_samples: dict[str, list[int]] = {}
    free_clock_samples: dict[str, list[int]] = {}
    examples = {}
    first_packet_id = {}
    representative_paths = {}
    gate_state_stats = {}
    guard_state_stats = {}
    credit_stats = {}
    trace_rows = 0
    # The row format has no commas in packet names or source paths. Parsing only
    # selected F13 rows avoids materializing the 4+ GB trace in memory.
    with gzip.open(trace, "rb") as f:
        header = next(f)
        expected = b"event,order,simtime_raw,source,kind,packet_id,flow,seq,data_bits,value"
        if header.rstrip(b"\r\n") != expected:
            raise ValueError(f"unexpected trace header: {header!r}")
        for line in f:
            trace_rows += 1
            parts = line.rstrip(b"\r\n").split(b",")
            if len(parts) != 10:
                continue
            kind = parts[4]
            source = parts[3].strip(b'"').decode(errors="replace")
            raw = int(parts[2])
            if kind in (b"gate_state", b"guard_band_state"):
                table = gate_state_stats if kind == b"gate_state" else guard_state_stats
                state = parts[9] == b"1"
                entry = table.setdefault(source, {"last_raw": None, "last_state": None, "open_ticks": 0, "closed_ticks": 0, "measurement_changes": 0})
                if entry["last_raw"] is not None:
                    lo = max(entry["last_raw"], CLOCK_TICKS_PER_SECOND)
                    hi = min(raw, 31 * CLOCK_TICKS_PER_SECOND)
                    if hi > lo:
                        entry["open_ticks" if entry["last_state"] else "closed_ticks"] += hi - lo
                if CLOCK_TICKS_PER_SECOND <= raw < 31 * CLOCK_TICKS_PER_SECOND:
                    entry["measurement_changes"] += 1
                entry["last_raw"] = raw
                entry["last_state"] = state
                continue
            if kind == b"cbs_credit":
                if CLOCK_TICKS_PER_SECOND <= raw < 31 * CLOCK_TICKS_PER_SECOND:
                    value = float(parts[9])
                    entry = credit_stats.setdefault(source, {"samples": 0, "min_raw_value": value, "max_raw_value": value, "first_raw_value": value, "last_raw_value": value})
                    entry["samples"] += 1
                    entry["min_raw_value"] = min(entry["min_raw_value"], value)
                    entry["max_raw_value"] = max(entry["max_raw_value"], value)
                    entry["last_raw_value"] = value
                continue
            if kind == b"clock_time_changed":
                if raw < CLOCK_TICKS_PER_SECOND or raw >= 31 * CLOCK_TICKS_PER_SECOND:
                    continue
                value = parts[9].decode(errors="replace")
                fields = dict(piece.split("=", 1) for piece in value.split(";") if "=" in piece)
                if "offset_raw" in fields:
                    if source.endswith(".clock.underlyingClock"):
                        node = source.removeprefix("ZonalIVN.").removesuffix(".clock.underlyingClock")
                        free_clock_samples.setdefault(node, []).append(int(fields["offset_raw"]))
                    elif source.endswith(".clock"):
                        node = source.removeprefix("ZonalIVN.").removesuffix(".clock")
                        clock_samples.setdefault(node, []).append(int(fields["offset_raw"]))
                continue
            if raw < CLOCK_TICKS_PER_SECOND or raw >= 31 * CLOCK_TICKS_PER_SECOND:
                continue
            flow = parts[6].decode(errors="replace")
            packet_id = parts[5].decode(errors="replace")
            if flow in {"8", "9", "10", "13", "21", "22"}:
                if flow not in first_packet_id and kind == b"queue_push_start":
                    first_packet_id[flow] = packet_id
                    representative_paths[flow] = []
                if packet_id and first_packet_id.get(flow) == packet_id:
                    representative_paths[flow].append({
                        "event": int(parts[0]), "order": int(parts[1]),
                        "time_s": raw / CLOCK_TICKS_PER_SECOND,
                        "source": source, "kind": kind.decode(),
                        "packet_id": packet_id, "packet_data_length_bits": int(parts[8]),
                    })
            if flow != "13" or source != TARGET_QUEUE:
                continue
            b = min(5, (raw - CLOCK_TICKS_PER_SECOND) // (5 * CLOCK_TICKS_PER_SECOND))
            kind_map = {
                b"queue_push_start": "push",
                b"queue_pulled_out": "pull",
                b"packet_dropped": "drop",
                b"queue_removed": "remove",
            }
            label = kind_map.get(kind)
            if label is None:
                continue
            bits = int(parts[8])
            qstats[b][label] += 1
            qstats[b][f"{label}_queue_bits"] += bits
            totals[label] += 1
            key = label
            example = {"event": int(parts[0]), "order": int(parts[1]),
                       "time_s": raw / CLOCK_TICKS_PER_SECOND,
                       "source": source, "kind": kind.decode(),
                       "packet_id": packet_id, "queue_packet_bits": bits}
            if key not in examples:
                examples[key] = {"first": example}
            examples[key]["last"] = example
    # Native offsets are already subtracted in the simulator before formatting.
    def summarize_clock_samples(samples):
        summary = {}
        for node, vals in samples.items():
            absvals = sorted(abs(v) for v in vals)
            n = len(absvals)
            p99 = absvals[max(0, math.ceil(0.99 * n) - 1)] if n else None
            summary[node] = {
                "samples": n,
                "max_abs_offset_ns": (absvals[-1] / 1000) if n else None,
                "p99_abs_offset_ns": (p99 / 1000) if n else None,
                "samples_over_1us": sum(v > OFFSET_LIMIT_RAW for v in absvals),
                "max_sampled_offset_ticks": absvals[-1] if n else None,
            }
        return summary

    def close_state_duration(table):
        for entry in table.values():
            if entry["last_raw"] is not None and entry["last_raw"] < 31 * CLOCK_TICKS_PER_SECOND:
                delta = 31 * CLOCK_TICKS_PER_SECOND - max(entry["last_raw"], CLOCK_TICKS_PER_SECOND)
                if delta > 0:
                    entry["open_ticks" if entry["last_state"] else "closed_ticks"] += delta
            entry["open_s"] = entry.pop("open_ticks") / CLOCK_TICKS_PER_SECOND
            entry["closed_s"] = entry.pop("closed_ticks") / CLOCK_TICKS_PER_SECOND
            duration = entry["open_s"] + entry["closed_s"]
            entry["open_fraction"] = entry["open_s"] / duration if duration else None
            entry.pop("last_raw", None)
            entry.pop("last_state", None)
    close_state_duration(gate_state_stats)
    close_state_duration(guard_state_stats)
    sync = summarize_clock_samples(clock_samples)
    free_sync = summarize_clock_samples(free_clock_samples)
    bins = []
    for i, x in enumerate(qstats):
        offered_wire = x["push"] * WIRE_BITS_PER_FRAME
        service_wire = x["pull"] * WIRE_BITS_PER_FRAME
        bins.append({
            "interval_s": [float(BIN_EDGES[i]), float(BIN_EDGES[i + 1])],
            **x,
            "offered_wire_bits": offered_wire,
            "service_wire_bits": service_wire,
            "offered_wire_bps": offered_wire / 5.0,
            "service_wire_bps": service_wire / 5.0,
            "wire_bits_per_frame": WIRE_BITS_PER_FRAME,
            "queue_bits_per_frame": QUEUE_BITS_PER_FRAME,
        })
    return {
        "trace_sha256": sha256(trace),
        "trace_uncompressed_rows_scanned": trace_rows,
        "target_queue_packet_events_total": totals,
        "target_queue_packet_events_measurement": {k: sum(x[k] for x in qstats) for k in totals},
        "target_queue_packet_event_examples": examples,
        "bins_5s": bins,
        "representative_first_packet_paths": representative_paths,
        "representative_packet_ids": first_packet_id,
        "sampled_clock_offsets": sync,
        "free_oscillator_clock_offsets": free_sync,
        "gate_state_duration_s": gate_state_stats,
        "guard_band_state_duration_s": guard_state_stats,
        "cbs_credit_samples_raw_units": credit_stats,
        "sampled_sync_assessment": {
            "nodes_expected": ["HPC", "CSW", "Z1.ZSW", "Z2.ZSW", "Z3.ZSW"],
            "all_expected_nodes_observed": all(node in sync for node in ("HPC", "CSW", "Z1.ZSW", "Z2.ZSW", "Z3.ZSW")),
            "pass_at_observed_samples_le_1us": all(
                node in sync and sync[node]["max_abs_offset_ns"] is not None and sync[node]["max_abs_offset_ns"] <= 1000
                for node in ("HPC", "CSW", "Z1.ZSW", "Z2.ZSW", "Z3.ZSW")
            ),
            "continuous_compliance": "not verified by discrete timeChanged samples",
        },
        "clock_sample_method": "offset_raw = local clock ticks - HPC ticks calculated in probe before text serialization; 1 ps SimTime tick",
    }


def load_run(variant: str):
    eid = BM_CORRECTED_ID if variant == "BM_recovery" and (RUNS / BM_CORRECTED_ID).is_dir() else f"{variant}_L2_A1_seed41"
    dest = RUNS / eid
    run_dir = next(dest.glob("*-0"))
    result = json_file(dest / "pilot-result.json")
    accept_name = "c3sync-acceptance.json" if variant == "C3_sync_control" else "c4compensated-acceptance.json"
    accept = json_file(run_dir / accept_name)
    f13 = result.get("qos", {}).get("F13", {}).get("receivers", {}).get("AUDIO3", {})
    brake = {}
    for fid in ("F08", "F09", "F10"):
        item = result.get("qos", {}).get(fid, {})
        # These brake flows are unicast; the actual key is the catalog receiver.
        for receiver, metrics in item.get("receivers", {}).items():
            brake[fid] = {"receiver": receiver, **metrics}
    sync = trace_f13_summary(run_dir)
    legacy_gate_schedule = result.get("tas_gate_schedule")
    corrected_gate_schedule = None
    if variant != "C3_sync_control":
        gate_rows = {}
        effective_gates = result.get("effective_gcl", {}).get("gates", {})
        measured_gates = sync["gate_state_duration_s"]
        for module, config in effective_gates.items():
            tokens = re.findall(r"([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)\s*(s|ms|us|ns|ps)", config.get("durations", ""))
            scale = {"s": 1.0, "ms": 1e-3, "us": 1e-6, "ns": 1e-9, "ps": 1e-12}
            durations = [float(v) * scale[u] for v, u in tokens]
            expected = durations[0] / sum(durations) if len(durations) == 2 and sum(durations) else None
            observed = measured_gates.get(module, {}).get("open_fraction")
            gate_rows[module] = {
                "expected_open_fraction_from_effective_durations": expected,
                "observed_open_fraction_from_gate_state_trace": observed,
                "within_1e-4": expected is not None and observed is not None and abs(expected - observed) <= 1e-4,
                "effective_durations": config.get("durations"),
                "effective_offset": config.get("offset"),
            }
        corrected_gate_schedule = {
            "status": "pass" if len(gate_rows) == 32 and all(x["within_1e-4"] for x in gate_rows.values()) else "inconclusive_or_fail",
            "expected_gate_count": 32,
            "observed_gate_count": len(gate_rows),
            "tolerance_fraction": 1e-4,
            "expectations_source": "effective_gcl SCA parameters; inherited fixed A005 duty-cycle expectations are retained separately as historical export",
            "gates": gate_rows,
        }
    q = q_state_summary(run_dir)
    by_bin = []
    for i, (counts, occ) in enumerate(zip(sync["bins_5s"], q["mean_occupancy_bits_5s"])):
        idx = len(by_bin)
        peak = q["max_occupancy_bits_5s"][idx]
        qstart, qend = q["boundary_states_bits"][idx:idx + 2]
        by_bin.append({
            "interval_s": counts["interval_s"],
            "F13_queue_push_packets": counts["push"],
            "F13_queue_pull_packets": counts["pull"],
            "F13_queue_drop_packets": counts["drop"],
            "F13_offered_wire_bits": counts["offered_wire_bits"],
            "F13_serviced_wire_bits": counts["service_wire_bits"],
            "F13_offered_wire_bps": counts["offered_wire_bps"],
            "F13_service_wire_bps": counts["service_wire_bps"],
            "queue_mean_bits": occ,
            "queue_peak_bits": peak,
            "queue_start_bits": qstart,
            "queue_end_bits": qend,
            "queue_delta_bits": qend - qstart,
            "queue_balance_residual_bits": (qend - qstart) - (
                counts["push_queue_bits"] - counts["pull_queue_bits"]
                - counts["drop_queue_bits"] - counts["remove_queue_bits"]
            ),
            "backlog_observed": peak > 0,
            "service_exceeds_offer": counts["service_wire_bits"] > counts["offered_wire_bits"],
        })
    queue_bits_balance = q["delta_Q_bits"] - (
        sum(x["push_queue_bits"] for x in sync["bins_5s"])
        - sum(x["pull_queue_bits"] for x in sync["bins_5s"])
        - sum(x["drop_queue_bits"] for x in sync["bins_5s"])
        - sum(x["remove_queue_bits"] for x in sync["bins_5s"])
    )
    sync_pass = sync["sampled_sync_assessment"]["all_expected_nodes_observed"] and sync["sampled_sync_assessment"]["pass_at_observed_samples_le_1us"]
    return {
        "execution_id": eid,
        "variant": variant,
        "validity": {
            "simulation_valid": result.get("simulation_valid"),
            "calendar_paired": result.get("calendar_paired"),
            "calendar_sha256": result.get("calendar_sha256"),
            "instrumentation_valid": result.get("instrumentation_validation", {}).get("valid"),
            "application_viable": result.get("application_viable"),
            "stability_proxy_viable": result.get("stability_viable"),
            "effective_gcl_status": result.get("effective_gcl", {}).get("status"),
            "observed_gate_schedule_pass_recomputed": (corrected_gate_schedule or {}).get("status", "not_applicable"),
            "sampled_sync_pass_recomputed": sync_pass,
            "continuous_sync_compliance": "not verified",
        },
        "recorded_result_gates": accept.get("qos", {}),
        "tas_gate_schedule": corrected_gate_schedule or {"status": "not_applicable"},
        "legacy_tas_gate_schedule_preserved": legacy_gate_schedule,
        "flow_metrics_by_receiver": result.get("qos", {}),
        "all_queue_stability_metrics": accept.get("queue_stability", []),
        "F13_packet_metrics": f13,
        "brake_metrics": brake,
        "Z3_F13_queue": q,
        "Z3_F13_queue_packet_events": sync,
        "Z3_F13_service_by_5s": by_bin,
        "Z3_F13_queue_bits_balance_residual": queue_bits_balance,
        "acceptance_queue_stability": next((x for x in accept.get("queue_stability", []) if x.get("queue") == TARGET_QUEUE), None),
        "effective_profile_bps": result.get("effective_profile_bps"),
    }


def main():
    checkpoint = json_file(RESULTS / "checkpoint.json")
    completed = set(checkpoint.get("completed", []))
    runs = {}
    for variant in VARIANTS:
        eid = f"{variant}_L2_A1_seed41"
        if eid not in completed and not (variant == "BM_recovery" and BM_CORRECTED_ID in completed and (RUNS / BM_CORRECTED_ID).is_dir()):
            raise SystemExit(f"missing completed run: {eid}")
        print(f"Analyzing {eid}...", flush=True)
        runs[variant] = load_run(variant)
    candidates = {}
    for variant in CANDIDATES:
        r = runs[variant]
        bits = r["Z3_F13_queue_bits_balance_residual"]
        all_bins = r["Z3_F13_service_by_5s"]
        margin_bins = [x for x in all_bins if x["backlog_observed"]]
        margin_ok = bool(margin_bins) and all(x["service_exceeds_offer"] and x["queue_delta_bits"] <= 0
                        for x in margin_bins)
        per_bin_balance = all(x["queue_balance_residual_bits"] == 0 for x in all_bins)
        base_ok = all(r["validity"][k] for k in ("simulation_valid", "calendar_paired", "instrumentation_valid", "application_viable", "stability_proxy_viable", "sampled_sync_pass_recomputed")) and r["validity"]["effective_gcl_status"] == "pass" and bits == 0 and per_bin_balance
        candidates[variant] = {"base_gates_and_balance_pass": base_ok, "service_margin_pass": margin_ok, "selectable": bool(base_ok and margin_ok),
                               "per_bin_queue_balance_pass": per_bin_balance,
                               "backlogged_intervals": len(margin_bins),
                               "service_margin_note": "wire service must strictly exceed same-interval wire offer; all six intervals are checked if backlog appears"}
    selected = next((v for v in CANDIDATES if candidates[v]["selectable"]), None)
    for variant, data in candidates.items():
        data["selection_rank"] = CANDIDATES.index(variant) + 1
    contrasts = {}
    def qfocus(variant):
        rows = runs[variant]["all_queue_stability_metrics"]
        patterns = ["HPC.eth[0].macLayer.queue.queue[4]", "CSW.eth[1].macLayer.queue.queue[4]",
                    "CSW.eth[2].macLayer.queue.queue[4]", "CSW.eth[3].macLayer.queue.queue[4]",
                    "Z3.ZSW.eth[7].macLayer.queue.queue[4]"]
        return {p: next((x for x in rows if x.get("queue", "").endswith(p)), None) for p in patterns}
    def flatten_flow_metrics(variant):
        ret = {}
        for flow, detail in runs[variant]["flow_metrics_by_receiver"].items():
            for receiver, metrics in detail.get("receivers", {}).items():
                ret[(flow, receiver)] = metrics
        return ret
    for left, right, label in [
        ("R_cadence", "B_local", "R_minus_B"),
        ("RP_cadence_phase", "R_cadence", "RP_minus_R"),
        ("BM_recovery", "B_local", "BM_minus_B"),
        ("RPM_combined", "RP_cadence_phase", "RPM_minus_RP"),
        ("RPM_combined", "BM_recovery", "RPM_minus_BM"),
    ]:
        lf, rf = flatten_flow_metrics(left), flatten_flow_metrics(right)
        flow_deltas = {}
        for key in sorted(set(lf) & set(rf)):
            lm, rm = lf[key], rf[key]
            llat, rlat = lm.get("latency") or {}, rm.get("latency") or {}
            flow_deltas[f"{key[0]}@{key[1]}"] = {
                "received_packets_delta": (lm.get("received_packets", 0) or 0) - (rm.get("received_packets", 0) or 0),
                "packet_loss_ratio_delta": (lm.get("packet_loss_ratio", 0) or 0) - (rm.get("packet_loss_ratio", 0) or 0),
                "deadline_miss_ratio_delta": (lm.get("deadline_miss_ratio_including_loss", 0) or 0) - (rm.get("deadline_miss_ratio_including_loss", 0) or 0),
                "p99_latency_delta_s": (llat.get("p99_s") or 0) - (rlat.get("p99_s") or 0),
                "max_latency_delta_s": (llat.get("max_s") or 0) - (rlat.get("max_s") or 0),
                "goodput_payload_ratio_delta": (lm.get("goodput_payload_ratio", 0) or 0) - (rm.get("goodput_payload_ratio", 0) or 0),
            }
        lq, rq = qfocus(left), qfocus(right)
        queue_deltas = {}
        for key in lq:
            if lq[key] and rq[key]:
                queue_deltas[key] = {
                    "mean_occupancy_bits_5s_delta": [a-b for a,b in zip(lq[key]["mean_occupancy_bits_5s"], rq[key]["mean_occupancy_bits_5s"])],
                    "max_occupancy_bits_delta": lq[key]["max_occupancy_bits"] - rq[key]["max_occupancy_bits"],
                    "sustained_growth_left": lq[key]["sustained_growth"],
                    "sustained_growth_right": rq[key]["sustained_growth"],
                }
        contrasts[label] = {"left_minus_right": f"{left} - {right}", "flow_metric_deltas": flow_deltas, "focused_queue_deltas": queue_deltas}
    if selected:
        sf, c3f = flatten_flow_metrics(selected), flatten_flow_metrics("C3_sync_control")
        contrasts["selected_minus_C3_sync_control"] = {"left_minus_right": f"{selected} - C3_sync_control", "flow_metric_deltas": {}}
        for key in sorted(set(sf) & set(c3f)):
            lm, rm = sf[key], c3f[key]
            llat, rlat = lm.get("latency") or {}, c3f[key].get("latency") or {}
            contrasts["selected_minus_C3_sync_control"]["flow_metric_deltas"][f"{key[0]}@{key[1]}"] = {
                "received_packets_delta": (lm.get("received_packets", 0) or 0) - (rm.get("received_packets", 0) or 0),
                "packet_loss_ratio_delta": (lm.get("packet_loss_ratio", 0) or 0) - (rm.get("packet_loss_ratio", 0) or 0),
                "deadline_miss_ratio_delta": (lm.get("deadline_miss_ratio_including_loss", 0) or 0) - (rm.get("deadline_miss_ratio_including_loss", 0) or 0),
                "p99_latency_delta_s": (llat.get("p99_s") or 0) - (rlat.get("p99_s") or 0),
                "max_latency_delta_s": (llat.get("max_s") or 0) - (rlat.get("max_s") or 0),
                "goodput_payload_ratio_delta": (lm.get("goodput_payload_ratio", 0) or 0) - (rm.get("goodput_payload_ratio", 0) or 0),
            }
    output = {
        "schema": "c4-real-clock-service-margin-pilot-v1",
        "exploratory": True,
        "diagnostic_only": False,
        "official_c4_frozen": False,
        "status": "conditional_runs_pending" if selected else "no_selectable_candidate_after_seed41",
        "selected_candidate": selected,
        "protocol_path": "simulations/pilot/c4_real_clock_service_margin/protocol.md",
        "checkpoint": checkpoint,
        "selection_rule": "Predeclared in protocol.md: app/stability/GCL/calendars and exact queue balance, then each 5 s interval with backlog must have service wire bits > offered wire bits and nonpositive queue growth; choose fewer interventions R, RP, RPM.",
        "measurement": {"window_s": [1, 31], "convention": "half-open", "drain_end_s": 31.05,
                        "queue_bits_per_F13_frame": QUEUE_BITS_PER_FRAME, "wire_bits_per_F13_frame": WIRE_BITS_PER_FRAME,
                        "wire_bytes_per_F13_frame": 276, "native_time_tick_s": 1e-12},
        "candidate_eligibility": candidates,
        "technical_replacements": ([
            {"treatment_slot": "B_local", "execution_id": "B_local_L2_A1_seed41", "replaces_attempt": "B_local_L2_A1_seed41_attempt_002", "reason": "the earlier completed B attempt lacked PacketQueue dequeue events because the probe subscribed to packetPulledOut instead of the installed INET 4.7 packetPulled signal; the final B slot uses the corrected event instrumentation"},
            {"treatment_slot": "BM_recovery", "execution_id": BM_CORRECTED_ID, "replaces": "BM_recovery_L2_A1_seed41", "reason": "the first BM execution used R cadence gates, but BM was preregistered with B_local gates; the corrected B schedule was rerun with the same profile and event calendar"},
        ] if BM_CORRECTED_ID in completed else []),
        "technical_attempts": [json.loads(line) for line in (RESULTS / "technical_attempts.jsonl").read_text().splitlines() if line.strip()],
        "superseded_executions": [{"execution_id": "BM_recovery_L2_A1_seed41", "used_in_final_comparisons": False, "reason": "effective SCA durations matched R cadence, not preregistered B_local gates; preserved as historical evidence and replaced by the corrected BM execution"}],
        "audit_corrections": {
            "gate_schedule_export": "Per-run gate duty fractions are recomputed from the effective GCL configuration and gate-state traces. The inherited tas_gate_schedule is preserved under legacy_tas_gate_schedule_preserved because its expected fractions were fixed to the old A005 schedule.",
            "instrumentation_memory": "The final trace boundary check is streaming and does not retain all packet identifiers in a Python set; it records packet-id presence and sets the exact unique-id count to unavailable.",
            "BM_configuration": "Only the corrected BM technical replacement is analyzed as the BM treatment; the original R-gate BM record remains in the ledger but is excluded from contrasts."
        },
        "paired_contrasts": contrasts,
        "runs": runs,
        "analysis_script_sha256": sha256(pathlib.Path(__file__)),
    }
    (OUT / "pilot_results.json").write_text(json.dumps(output, indent=2) + "\n")
    print(f"wrote {OUT/'pilot_results.json'}")


if __name__ == "__main__":
    main()
