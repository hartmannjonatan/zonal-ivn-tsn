#!/usr/bin/env python3
"""Regenerate the frozen, read-only analysis of the current P1 campaign results.

Run from any directory with the repository's Python 3:
  python3 simulations/analysis/icit2027_editorial_synthesis_2026-10-27/analyze_results.py

The script reads only finalized acceptance reports and the C4 cutoff manifest;
it never inspects the active C4 execution as a result and never starts simulations.
"""
from __future__ import annotations

import csv
from collections import Counter
import hashlib
import json
import math
import statistics
import html
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = next(p for p in HERE.parents if (p / "simulations/campaigns/p1-v2-official-2026-10/campaign_manifest.json").exists())
CAMP = ROOT / "simulations/campaigns/p1-v2-official-2026-10"
OUT = HERE
SEEDS = list(range(1001, 1031))
TREATMENTS = ("C0", "C1", "C3", "C4")
REPORT_NAMES = {"C0": "c0-acceptance.json", "C1": "c1-acceptance.json", "C3": "c3-acceptance.json"}
HARD_FLOWS = {"F01", "F02", "F03", "F06", "F07", "F08", "F09", "F10"}
CAMERA_FLOWS = {"F02", "F03", "F04", "F05"}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_json(path: Path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def report_rows():
    reports = []
    # Fixed official campaign records, discovered from their finalized acceptance artifacts.
    for treatment in ("C0", "C1", "C3"):
        base = CAMP / "results/final" / treatment
        name = REPORT_NAMES[treatment]
        for path in sorted(base.rglob(name)):
            d = read_json(path)
            if d.get("campaign_treatment") != treatment:
                continue
            reports.append((treatment, path, d, d.get("calendar_sha256")))
    # C4 is deliberately frozen to the contemporaneous cutoff, not today's growing ledger.
    cutoff = read_json(OUT / "c4_cutoff.json")
    seen = set()
    for item in cutoff["included_rows"]:
        eid = item["execution_id"]
        if eid in seen:
            raise ValueError(f"duplicate C4 cutoff execution {eid}")
        seen.add(eid)
        path = ROOT / item["run_report"]
        if not path.is_file() or sha256(path) != item["run_report_sha256"]:
            raise ValueError(f"C4 report missing or changed: {eid}: {path}")
        d = read_json(path)
        if d.get("treatment") != "C4" or d.get("viable") is None:
            raise ValueError(f"C4 report is not a finalized result: {eid}")
        # C4 report schema omits several ledger identifiers; take them only from the
        # immutable completed-row snapshot, never from the live checkpoint.
        d.setdefault("execution_id", eid)
        parts = eid.split("_")
        d.setdefault("load", item.get("load", parts[1]))
        d.setdefault("aggregation", item.get("alignment", parts[2]))
        d.setdefault("seed", item.get("seed", parts[3].removeprefix("seed")))
        d.setdefault("profile_sha256", item.get("profile_sha256"))
        reports.append(("C4", path, d, item.get("calendar_signature")))
    return reports


def num(x):
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def extract(treatment, path, d, calendar_signature):
    load = d.get("load_name", d.get("load"))
    if isinstance(load, int):
        load = f"L{load}"
    alignment = d.get("aggregation", d.get("alignment"))
    seed = int(d["seed"])
    source_hashes = d.get("configuration_source_hashes") or {}
    source_hash_set_sha256 = hashlib.sha256(json.dumps(source_hashes,sort_keys=True,separators=(",",":")).encode()).hexdigest() if source_hashes else None
    flows = {}
    crit_packet_p99 = []
    crit_packet_max = []
    brake_p99 = []
    brake_max = []
    camera_image_p99 = []
    camera_image_max = []
    hard_passes = []
    packet_loss_sum = 0
    packet_offered_sum = 0
    packet_received_sum = 0
    image_offered_sum = 0
    image_completed_sum = 0
    image_deadline_misses = 0

    for fid, flow in (d.get("qos") or {}).items():
        receivers = {}
        for receiver, r in (flow.get("receivers") or {}).items():
            latency = r.get("latency") or {}
            offered = num(r.get("offered_packets"))
            received = num(r.get("received_packets"))
            packet_loss = max(0, offered - received) if offered is not None and received is not None else None
            packet_offered_sum += offered or 0
            packet_received_sum += received or 0
            packet_loss_sum += packet_loss or 0
            image = r.get("image_completion")
            image_rec = None
            if isinstance(image, dict):
                io = num(image.get("offered_images"))
                ic = num(image.get("completed_images"))
                if io is not None:
                    image_offered_sum += io
                if ic is not None:
                    image_completed_sum += ic
                image_miss = num(image.get("deadline_miss_ratio_including_missing_images"))
                image_deadline_misses += int(round((io or 0) * (image_miss or 0)))
                image_rec = {
                    "unit": "image",
                    "offered": io,
                    "completed": ic,
                    "incomplete": max(0, io - ic) if io is not None and ic is not None else None,
                    "deadline_miss_ratio_including_incomplete": image_miss,
                    "deadline_misses_completed": image.get("deadline_misses_completed"),
                    "p99_completion_s": image.get("p99_s"),
                    "max_completion_s": image.get("max_s"),
                    "quantile_population_complete_images": image.get("samples"),
                    "deadline_s": image.get("deadline_s"),
                }
                if fid in CAMERA_FLOWS:
                    if num(image.get("p99_s")) is not None:
                        camera_image_p99.append(float(image["p99_s"]))
                    if num(image.get("max_s")) is not None:
                        camera_image_max.append(float(image["max_s"]))
            rec = {
                "unit": "packet",
                "offered": offered,
                "received": received,
                "losses_offered_minus_received": packet_loss,
                "packet_loss_ratio": r.get("packet_loss_ratio"),
                "deadline_misses_including_loss_ratio": r.get("deadline_miss_ratio_including_loss"),
                "deadline_misses_received": r.get("deadline_misses_received"),
                "p99_latency_s": latency.get("p99_s"),
                "max_latency_s": latency.get("max_s"),
                "latency_sample_count": latency.get("samples"),
                "goodput_payload_ratio": r.get("goodput_payload_ratio"),
                "useful_throughput_mbps": r.get("useful_throughput_mbps"),
                "reported_receiver_viable": r.get("viable"),
                "image_metrics": image_rec,
            }
            receivers[receiver] = rec
            if fid in HARD_FLOWS:
                hard_passes.append(r.get("viable") is True)
                if fid not in CAMERA_FLOWS and num(latency.get("p99_s")) is not None:
                    crit_packet_p99.append(float(latency["p99_s"]))
                if fid not in CAMERA_FLOWS and num(latency.get("max_s")) is not None:
                    crit_packet_max.append(float(latency["max_s"]))
                if fid in {"F08", "F09", "F10"}:
                    if num(latency.get("p99_s")) is not None:
                        brake_p99.append(float(latency["p99_s"]))
                    if num(latency.get("max_s")) is not None:
                        brake_max.append(float(latency["max_s"]))
        flows[fid] = {"criticality": flow.get("criticality"), "receivers": receivers}

    queues = []
    for q in (d.get("queue_stability") or []):
        if (num(q.get("samples")) or 0) > 0 or (num(q.get("max_occupancy_bits")) or 0) > 0 or q.get("sustained_growth"):
            queues.append({k: q.get(k) for k in (
                "queue", "tc", "capacity_bits", "samples", "mean_occupancy_bits_measurement",
                "mean_occupancy_bits_5s", "max_occupancy_bits", "fraction_measurement_at_least_90pct_capacity",
                "sustained_growth") if k in q})
    overflow_postwarm = d.get("queue_overflow_drop_total_post_warmup_including_drain")
    overflow_legacy = d.get("queue_overflow_drop_total")
    overflow_scope = ("post-warm-up through drain" if overflow_postwarm is not None else
                      ((d.get("metric_windows") or {}).get("SCA_overflow_counters", "legacy/unspecified")))
    # Preserve queue-level drop evidence without repeating the many zero rows
    # for every queue in every run. Original acceptance reports remain intact.
    measurement_drop_rows = [x for x in (d.get("measurement_drops_by_queue") or [])
                             if int(x.get("packets", x.get("overflow_drops_measurement_window", 0)) or 0) != 0
                             or int(x.get("bytes", 0) or 0) != 0]
    overflow_by_queue = d.get("queue_overflow_drops_by_queue") or []
    overflow_by_queue = [x for x in overflow_by_queue
                         if any(int(x.get(k, 0) or 0) != 0 for k in
                                ("packets", "bytes", "overflow_drops", "dropped_packets"))]
    measurement_overflow = sum(int(x.get("packets", x.get("overflow_drops_measurement_window", 0)) or 0) for x in measurement_drop_rows)
    nonstable = d.get("nonstable_queues") or []
    crit_app_pass = bool(hard_passes) and all(hard_passes)
    return {
        "execution_id": d.get("execution_id"),
        "treatment": treatment,
        "load": load,
        "alignment": alignment,
        "seed": seed,
        "report_path": str(path.relative_to(ROOT)),
        "report_sha256": sha256(path),
        "calendar_signature": calendar_signature,
        "profile_sha256": d.get("profile_sha256"),
        "source_hash_set_sha256": source_hash_set_sha256,
        "simulator_binary_sha256": source_hashes.get("src/zonal-ivn-tsn"),
        "top_level_viable": d.get("viable"),
        "critical_flow_gate_derived_from_receiver_flags": crit_app_pass,
        "critical_flow_gate_source": "all high-hard receiver viable fields; distinct from stability and other acceptance flags",
        "nonstable_queue_count": len(nonstable),
        "nonstable_queues": nonstable,
        "queue_overflow_drops_post_warmup_including_drain": overflow_postwarm,
        "queue_overflow_drop_total_reported": overflow_postwarm if overflow_postwarm is not None else overflow_legacy,
        "queue_overflow_drop_scope": overflow_scope,
        "measurement_window_drop_packets_reported": measurement_overflow,
        "measurement_drops_by_queue": measurement_drop_rows,
        "queue_overflow_drops_by_queue_reported": overflow_by_queue,
        "recorded_drops_whole_run": d.get("recorded_drops"),
        "pending_packets_at_simulation_end": d.get("pending_packet_count_at_simulation_end"),
        "offered_packet_receiver_sum": packet_offered_sum,
        "received_packet_receiver_sum": packet_received_sum,
        "packet_loss_receiver_sum": packet_loss_sum,
        "offered_images_sum": image_offered_sum,
        "completed_images_sum": image_completed_sum,
        "image_deadline_misses_sum_derived": image_deadline_misses,
        "critical_noncamera_packet_p99_max_s": max(crit_packet_p99) if crit_packet_p99 else None,
        "critical_noncamera_packet_max_max_s": max(crit_packet_max) if crit_packet_max else None,
        "brake_packet_p99_max_s": max(brake_p99) if brake_p99 else None,
        "brake_packet_max_max_s": max(brake_max) if brake_max else None,
        "camera_image_p99_max_s": max(camera_image_p99) if camera_image_p99 else None,
        "camera_image_max_max_s": max(camera_image_max) if camera_image_max else None,
        "sampled_sync_viable": d.get("sync_sample_viable", d.get("sampled_sync_viable")),
        "continuous_sync_status": d.get("sync_continuous_status", d.get("continuous_sync_status")),
        "technical_valid": d.get("technical_valid", d.get("simulation_valid")),
        "reservation_profile_bps": d.get("reservation_profile_bps"),
        "gcl_summary": (d.get("C4_runtime_contract") or {}).get("GCL"),
        "clock_summary": (d.get("C4_runtime_contract") or {}).get("clock_summary"),
        "admissibility": d.get("admissibility"),
        "drops_metric_windows": d.get("metric_windows"),
        "drop_reconciliation": d.get("drop_reconciliation"),
        "flow_metrics": flows,
        "active_queue_metrics": queues,
    }


def safe_mean(values):
    return statistics.mean(values) if values else None


def paired_summary(rows):
    vals = [r["delta"] for r in rows if isinstance(r.get("delta"), (int, float))]
    if not vals:
        return {"n": 0}
    mean = statistics.mean(vals)
    sd = statistics.stdev(vals) if len(vals) > 1 else None
    # Descriptive normal approximation; report explicitly, not as confirmatory inference.
    half = 1.96 * sd / math.sqrt(len(vals)) if sd is not None else None
    return {"n": len(vals), "mean": mean, "median": statistics.median(vals), "min": min(vals), "max": max(vals),
            "approx_95pct_treating_runs_as_units": [mean-half, mean+half] if half is not None else None}


def run_metrics(run, fid, receiver):
    r = run["flow_metrics"].get(fid, {}).get("receivers", {}).get(receiver)
    if not r:
        return {}
    return {
        "packet_p99_s": r.get("p99_latency_s"),
        "packet_max_s": r.get("max_latency_s"),
        "packet_loss_ratio": r.get("packet_loss_ratio"),
        "packet_misses_including_loss_ratio": r.get("deadline_misses_including_loss_ratio"),
        "packet_offered": r.get("offered"),
        "packet_received": r.get("received"),
        "image_p99_s": (r.get("image_metrics") or {}).get("p99_completion_s"),
        "image_max_s": (r.get("image_metrics") or {}).get("max_completion_s"),
        "image_miss_ratio_including_incomplete": (r.get("image_metrics") or {}).get("deadline_miss_ratio_including_incomplete"),
        "image_offered": (r.get("image_metrics") or {}).get("offered"),
        "image_completed": (r.get("image_metrics") or {}).get("completed"),
    }


def make_comparisons(runs):
    idx = {(r["treatment"], r["load"], r["alignment"], r["seed"]): r for r in runs}
    out = []
    contrasts = (("C1", "C0", "C1-C0"), ("C3", "C1", "C3-C1"), ("C4", "C3", "C4-C3"))
    metrics = ("packet_p99_s", "packet_max_s", "packet_loss_ratio", "packet_misses_including_loss_ratio",
               "image_p99_s", "image_max_s", "image_miss_ratio_including_incomplete")
    for left_t, right_t, label in contrasts:
        for key, left in idx.items():
            if key[0] != left_t:
                continue
            right = idx.get((right_t, *key[1:]))
            if not right:
                continue
            cal_match = left.get("calendar_signature") == right.get("calendar_signature")
            for fid, flow in left["flow_metrics"].items():
                for receiver in flow["receivers"]:
                    lm = run_metrics(left, fid, receiver)
                    rm = run_metrics(right, fid, receiver)
                    for metric in metrics:
                        lv, rv = lm.get(metric), rm.get(metric)
                        if lv is None or rv is None:
                            continue
                        out.append({"contrast": label, "load": key[1], "alignment": key[2], "seed": key[3],
                                    "flow": fid, "receiver": receiver, "metric": metric,
                                    "left_treatment": left_t, "left_value": lv,
                                    "right_treatment": right_t, "right_value": rv,
                                    "delta_left_minus_right": lv-rv,
                                    "relative_delta_percent": (100*(lv-rv)/rv if rv else None),
                                    "calendar_signature_match": cal_match,
                                    "included_in_paired_contrast": cal_match})
    # Alignment contrast: same treatment/load/seed; A1 and A0 are deliberately different calendars.
    # Pair only if measured offered populations match for all flows.
    for treatment in TREATMENTS:
        for load in sorted({r["load"] for r in runs}):
            for seed in SEEDS:
                a0 = idx.get((treatment, load, "A0", seed))
                a1 = idx.get((treatment, load, "A1", seed))
                if not a0 or not a1:
                    continue
                for fid in sorted(set(a0["flow_metrics"]) & set(a1["flow_metrics"])):
                    for receiver in sorted(set(a0["flow_metrics"][fid]["receivers"]) & set(a1["flow_metrics"][fid]["receivers"])):
                        m0, m1 = run_metrics(a0, fid, receiver), run_metrics(a1, fid, receiver)
                        for metric in metrics:
                            v0, v1 = m0.get(metric), m1.get(metric)
                            if v0 is None or v1 is None:
                                continue
                            out.append({"contrast": "A1-A0", "treatment": treatment, "load": load, "seed": seed,
                                        "flow": fid, "receiver": receiver, "metric": metric,
                                        "left_treatment": "A1", "left_value": v1,
                                        "right_treatment": "A0", "right_value": v0,
                                        "delta_left_minus_right": v1-v0,
                                        "relative_delta_percent": 100*(v1-v0)/v0 if v0 else None,
                                        "calendar_signature_match": a1.get("calendar_signature")==a0.get("calendar_signature"),
                                        "included_in_paired_contrast": True,
                                        "pairing_basis": "same load and seed; alignment changes transient-calendar timing; offered flow populations checked in source reports"})
    return out


def write_csv(path, rows, fields=None):
    if fields is None:
        fields = list(dict.fromkeys(k for row in rows for k in row))
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({k: (json.dumps(v, separators=(",", ":")) if isinstance(v, (dict, list)) else v) for k, v in row.items()})


def svg_heatmap(cov):
    rows = ["C0", "C1", "C3", "C4"]
    cols = [(f"L{l}", a) for l in range(4) for a in ("A0", "A1")]
    lookup = {(x["treatment"], x["load"], x["alignment"]): x for x in cov}
    width, height = 1130, 330
    left, top, cw, ch = 105, 75, 122, 54
    pieces = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
              '<rect width="100%" height="100%" fill="white"/>',
              '<text x="24" y="30" font-family="sans-serif" font-size="19" font-weight="bold">Coverage and run-level viability at the frozen cutoff</text>']
    for j, (load, align) in enumerate(cols):
        x = left+j*cw
        pieces.append(f'<text x="{x+cw/2}" y="58" text-anchor="middle" font-family="sans-serif" font-size="13">{load} {align}</text>')
    for i, t in enumerate(rows):
        y = top+i*ch
        pieces.append(f'<text x="{left-18}" y="{y+32}" text-anchor="end" font-family="sans-serif" font-size="14" font-weight="bold">{t}</text>')
        for j,(load,align) in enumerate(cols):
            x=left+j*cw; d=lookup[(t,load,align)]; done=d["completed_valid_included"]; planned=d["planned_positions"]
            if d["rejected_by_triage"]:
                color="#dddddd"; label=f"triage reject {d['rejected_by_triage']}"
            elif planned==0:
                color="#f2f2f2"; label="out of scope"
            elif done==0:
                color="#f7f7f7"; label=f"0/{planned} pending"
            else:
                rate=d["top_level_viable"]/done
                color="#ccebc5" if rate==1 else ("#fdd49e" if rate>0 else "#f4a6a6")
                label=f"{d['top_level_viable']}/{done} pass"
                if done<planned: label += f"; {planned-done} pending"
            pieces.append(f'<rect x="{x+2}" y="{y+2}" width="{cw-4}" height="{ch-4}" rx="4" fill="{color}" stroke="#777"/>')
            pieces.append(f'<text x="{x+cw/2}" y="{y+32}" text-anchor="middle" font-family="sans-serif" font-size="11">{html.escape(label)}</text>')
    pieces.append('<text x="105" y="305" font-family="sans-serif" font-size="11" fill="#444">C4 includes 90 completed_valid rows at 2026-10-27 16:43:14 -03:00; later/failed rows are excluded. Historic C3/C4 correspond to paper C2/C3; L3 is triage-rejected for both.</text>')
    pieces.append('</svg>')
    (OUT/"fig_coverage.svg").write_text("\n".join(pieces),encoding="utf-8")


def svg_bars(title, subtitle, labels, values, units, outname, deadline=None):
    width,height=850,390; left,top,plotw,ploth=95,95,690,225
    maxv=max([v for v in values if v is not None]+([deadline] if deadline else [1]))
    maxv=maxv*1.18
    pieces=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
            '<rect width="100%" height="100%" fill="white"/>',
            f'<text x="24" y="30" font-family="sans-serif" font-size="19" font-weight="bold">{html.escape(title)}</text>',
            f'<text x="24" y="55" font-family="sans-serif" font-size="12" fill="#444">{html.escape(subtitle)}</text>']
    for i in range(5):
        y=top+ploth*i/4; val=maxv*(1-i/4)
        pieces.append(f'<line x1="{left}" y1="{y}" x2="{left+plotw}" y2="{y}" stroke="#ddd"/>')
        pieces.append(f'<text x="{left-8}" y="{y+4}" text-anchor="end" font-family="sans-serif" font-size="10">{val:.2g}</text>')
    if deadline is not None:
        y=top+ploth*(1-deadline/maxv)
        pieces.append(f'<line x1="{left}" y1="{y}" x2="{left+plotw}" y2="{y}" stroke="#b2182b" stroke-dasharray="6,4"/>')
        pieces.append(f'<text x="{left+plotw-5}" y="{y-5}" text-anchor="end" font-family="sans-serif" font-size="10" fill="#b2182b">deadline {deadline:g} {units}</text>')
    colors=["#2166ac","#67a9cf","#ef8a62","#b2182b"]
    n=len(labels); slot=plotw/max(1,n); bw=min(90,slot*.55)
    for i,(label,val) in enumerate(zip(labels,values)):
        x=left+i*slot+(slot-bw)/2
        if val is None: continue
        barh=ploth*val/maxv; y=top+ploth-barh
        pieces.append(f'<rect x="{x}" y="{y}" width="{bw}" height="{barh}" fill="{colors[i%len(colors)]}"/>')
        pieces.append(f'<text x="{x+bw/2}" y="{y-5}" text-anchor="middle" font-family="sans-serif" font-size="10">{val:.3g}</text>')
        pieces.append(f'<text x="{left+i*slot+slot/2}" y="{top+ploth+22}" text-anchor="middle" font-family="sans-serif" font-size="12">{html.escape(label)}</text>')
    pieces.append(f'<text x="20" y="{top+ploth/2}" transform="rotate(-90,20,{top+ploth/2})" font-family="sans-serif" font-size="12">Median of per-run worst-flow p99 ({units})</text>')
    pieces.append('</svg>')
    (OUT/outname).write_text("\n".join(pieces),encoding="utf-8")


def create_figures(runs, cov):
    svg_heatmap(cov)
    # Per-run maximum across the three brake receivers; median across executions.
    vals=[]; labels=[]
    for t in ("C0","C1","C3","C4"):
        rr=[r for r in runs if r["treatment"]==t and r["load"]=="L0" and r["alignment"]=="A0"]
        v=[r["brake_packet_p99_max_s"]*1e6 for r in rr if r["brake_packet_p99_max_s"] is not None]
        labels.append(t); vals.append(statistics.median(v) if v else None)
    svg_bars("Brake packet-tail latency at L0/A0", "Per run: maximum p99 among F08–F10; bars are medians across available seeds (n=30 except cutoff-defined C4).", labels, vals, "µs", "fig_brake_p99_l0a0.svg")
    vals=[]; labels=[]
    for t in ("C0","C1","C3","C4"):
        rr=[r for r in runs if r["treatment"]==t and r["load"]=="L0" and r["alignment"]=="A0"]
        # F02/F03 are the hard cameras with a 10 ms image deadline. Do not
        # combine them with F04/F05, whose 30 ms deadlines differ.
        v=[]
        for run in rr:
            tails=[]
            for fid in ("F02","F03"):
                for receiver in run["flow_metrics"].get(fid,{}).get("receivers",{}).values():
                    image=(receiver.get("image_metrics") or {})
                    if image.get("p99_completion_s") is not None:
                        tails.append(image["p99_completion_s"]*1e3)
            if tails: v.append(max(tails))
        labels.append(t); vals.append(statistics.median(v) if v else None)
    svg_bars("Hard-camera image-completion tail at L0/A0", "Per run: maximum image p99 among F02/F03 (10 ms deadlines); incomplete images remain separate misses.", labels, vals, "ms", "fig_camera_image_p99_l0a0.svg", deadline=10.0)


def main():
    raw = report_rows()
    runs = [extract(*item) for item in raw]
    # Detect duplicate execution identity before producing summaries.
    ids = [r["execution_id"] for r in runs]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate execution IDs across included treatments")

    cov = []
    for t in TREATMENTS:
        for load_i in range(4):
            load = f"L{load_i}"
            for alignment in ("A0", "A1"):
                if t in ("C3", "C4") and load_i == 3:
                    rejected = 30
                    planned = 30
                    status = "rejected_by_triage_not_simulated"
                elif t == "C4" and load_i > 2:
                    rejected = 0
                    planned = 0
                    status = "out_of_scope"
                elif t == "C3" and load_i == 3:
                    rejected = 30
                    planned = 30
                    status = "rejected_by_triage_not_simulated"
                else:
                    rejected = 0
                    planned = 30
                    status = "planned"
                group = [r for r in runs if r["treatment"] == t and r["load"] == load and r["alignment"] == alignment]
                included = len(group)
                valid = included  # all included reports pass the finalized-report/hash and unique-ID checks above
                pass_n = sum(r.get("top_level_viable") is True for r in group)
                app_fail = sum(r.get("critical_flow_gate_derived_from_receiver_flags") is False for r in group)
                stability_fail = sum(r.get("nonstable_queue_count", 0) > 0 for r in group)
                cutoff = read_json(OUT/"c4_cutoff.json")
                active = 0  # this cutoff is paused with no active execution; failed attempt is tracked separately
                pending = max(0, planned - included - rejected - active)
                cov.append({"treatment": t, "load": load, "alignment": alignment, "planned_positions": planned,
                            "completed_valid_included": valid, "top_level_viable": pass_n,
                            "valid_performance_reprovals": included-pass_n,
                            "derived_critical_application_failures": app_fail,
                            "stability_failures": stability_fail,
                            "technical_attempt_accounting": ("see C4 technical_attempts.jsonl; attempts are not result rows" if t=="C4" else "not fully recorded in the preserved treatment ledger"),
                            "in_progress_at_cutoff_excluded": active,
                            "pending_not_started": pending,
                            "rejected_by_triage": rejected,
                            "status": status if rejected else ("complete" if planned and included==planned else "partial" if included else status)})
    comparisons = make_comparisons(runs)
    sums = {}
    for contrast in sorted({r["contrast"] for r in comparisons}):
        crows = [r for r in comparisons if r["contrast"] == contrast and r.get("included_in_paired_contrast")]
        keys = sorted({(r["load"], r.get("alignment"), r.get("treatment"), r["flow"], r["receiver"], r["metric"]) for r in crows})
        groups = []
        for load, align, trt, flow, receiver, metric in keys:
            vals = [r["delta_left_minus_right"] for r in crows if (r["load"],r.get("alignment"),r.get("treatment"),r["flow"],r["receiver"],r["metric"])==(load,align,trt,flow,receiver,metric)]
            groups.append({"load":load,"alignment":align,"treatment":trt,"flow":flow,"receiver":receiver,"metric":metric,**paired_summary([{"delta":v} for v in vals])})
        sums[contrast] = groups

    coverage = {"positions": cov, "counts": {t: sum(r["completed_valid_included"] for r in cov if r["treatment"]==t) for t in TREATMENTS}}
    overall = {}
    for t in TREATMENTS:
        rr=[r for r in runs if r["treatment"]==t]
        overall[t]={"n":len(rr),"top_level_viable":sum(r.get("top_level_viable") is True for r in rr),
                    "critical_flow_gate_pass_derived":sum(r.get("critical_flow_gate_derived_from_receiver_flags") is True for r in rr),
                    "stability_reprovals":sum(r.get("nonstable_queue_count",0)>0 for r in rr),
                    "runs_with_packet_receiver_losses":sum(r.get("packet_loss_receiver_sum",0)>0 for r in rr),
                    "overflow_drops_post_warmup_drain_sum_only_explicit_scope":sum(r.get("queue_overflow_drops_post_warmup_including_drain") or 0 for r in rr),
                    "measurement_window_drop_packets_reported_sum":sum(r.get("measurement_window_drop_packets_reported") or 0 for r in rr),
                    "recorded_whole_run_drops_sum":sum(r.get("recorded_drops_whole_run") or 0 for r in rr),
                    "pending_at_simulation_end_sum":sum(r.get("pending_packets_at_simulation_end") or 0 for r in rr),
                    "runs":rr}
    summary = {
        "schema_version": 1,
        "analysis_cutoff": read_json(OUT/"c4_cutoff.json")["cutoff_local"],
        "experimental_unit": "one completed simulation execution (seed/cell); packet samples are not treated as independent replicates",
        "coverage": coverage,
        "treatment_summary": overall,
        "c4_fixed_profile_rows": read_json(CAMP/"c4_official/manifest.json").get("profile_rows"),
        "c4_gcl_contract": read_json(CAMP/"c4_official/manifest.json").get("gcl"),
        "paired_contrasts": sums,
        "paper_treatment_mapping": {"paper_C0":"campaign C0", "paper_C1":"campaign C1", "paper_C2":"campaign C3 (calibrated CBS)", "paper_C3":"campaign C4 (joint CBS/TAS)"},
        "paper_hypothesis_assessment": [{
            "wording": "The relative benefit of progressively richer TSN traffic-shaping treatments over Strict Priority grows with offered load and burst alignment, with no single treatment dominating all load/alignment/metric combinations.",
            "status": "partially_supported_but_not_confirmed",
            "evidence": "C0 changes from 30/30 viable at L3/A0 to 0/30 at L3/A1; C1 passes 30/30 in both; calibrated CBS (paper C2) passes 0/120 at L0/L1 and 59/60 at L2; joint CBS/TAS (paper C3) has only a partial official cutoff.",
            "limitation": "The C3 (paper) campaign is incomplete, C2 nominal is not a treatment, C0/C1 software differs, and C2/C3 are complete-policy contrasts."
        }],
        "scientific_claim_candidates": [
            {"claim":"Source pre-shaping prevents the aligned high-load camera loss/incomplete-image failure observed under SP.",
             "strength":"strong_case_specific_empirical_finding",
             "evidence_location":"paired_contrasts C1-C0; L3/A1; F02/F05 packet and image metrics",
             "novelty_limit":"Automotive QoS/pre-shaping itself is established; novelty depends on the zonal workload, paired alignment experiment and image-completion evidence."},
            {"claim":"Load-scaled calibrated CBS did not preserve low-load viability in this campaign configuration.",
             "strength":"moderate_operational_finding",
             "evidence_location":"paper C2 = historic C3 coverage L0/L1 and queue/drop metrics",
             "novelty_limit":"No C2 nominal contrast; causal contribution of scaling and transient load is not isolated."},
            {"claim":"A fixed C4 candidate is promising at low load, with a substantial brake-tail cost relative to C3.",
             "strength":"preliminary_only",
             "evidence_location":"paper C3 = historic C4 cutoff L0/A0 and L0/A1 plus paired C4-C2 rows",
             "novelty_limit":"Official C4 is incomplete; high-load effects remain unknown and C4-C3 is a full-policy comparison."}
        ],
        "limitations": [
            "C4 is the fixed cutoff of 90 completed_valid rows at 2026-10-27T16:43:14-03:00; the failed technical attempt and any later ledger rows are excluded.",
            "C1 imported archive reports are paired only where per-run calendar signatures match; the current on-disk calendar CSVs were regenerated and are not substitutes for historical run signatures.",
            "For packet flows, deadline misses include packet loss as specified by each report. Camera image-completion metrics are kept separate from packet latency.",
            "Queue stability summaries are run-level validator outputs; they do not prove asymptotic stability.",
            "C4 synchronization is sample-based in the included reports; continuous conformance remains not verified.",
            "Paper C2 maps to historical campaign C3 (calibrated CBS); the nominal CBS treatment is not included in the paper comparison, so calibration superiority over nominal is not evaluated."
        ]
    }
    (OUT/"results_summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    write_csv(OUT/"coverage.csv", cov)
    write_csv(OUT/"paired_comparisons.csv", comparisons)
    # Compact per-execution CSV as a convenient audit index.
    # One scalar/index row per execution. The detailed per-flow and queue records
    # are in results_summary.json; do not serialize nested JSON blobs into CSV.
    write_csv(OUT/"execution_metrics.csv", [
        {k:v for k,v in r.items() if not isinstance(v,(dict,list))}
        for r in runs
    ])
    # Publication figures intentionally deferred; this stage prepares editorial evidence only.
    p1=ROOT/"docs/design/P1-final.pdf"
    campaign_manifest=read_json(CAMP/"campaign_manifest.json")
    c4_manifest=read_json(CAMP/"c4_official/manifest.json")
    cutoff=read_json(OUT/"c4_cutoff.json")
    source_paths=[
        "docs/design/P1-final.pdf",
        "simulations/campaigns/p1-v2-official-2026-10/campaign_manifest.json",
        "simulations/campaigns/p1-v2-official-2026-10/parallel_campaign_contract.json",
        "simulations/campaigns/p1-v2-official-2026-10/calibration_protocol.json",
        "simulations/campaigns/p1-v2-official-2026-10/c4_official/manifest.json",
        "simulations/campaigns/p1-v2-official-2026-10/c4_official/matrix.csv",
        "simulations/pilot/README_C4_CBS_TAS.md",
        "simulations/analysis/vtc2027_spring_recent_results_2026-10-26/import_staging/c1_archive/simulations/campaigns/p1-v2-official-2026-10/campaign_manifest.json",
        "simulations/analysis/vtc2027_spring_recent_results_2026-10-26/import_staging/c1_archive/simulations/campaigns/p1-v2-official-2026-10/parallel_campaign_contract.json",
        "simulations/analysis/vtc2027_spring_recent_results_2026-10-26/import_staging/c1_archive/simulations/campaigns/p1-v2-official-2026-10/calibration_protocol.json",
        "simulations/analysis/vtc2027_spring_recent_results_2026-10-26/import_staging/c1_archive/simulations/campaigns/p1-v2-official-2026-10/results/runs.jsonl",
        "simulations/analysis/vtc2027_spring_recent_results_2026-10-26/import_staging/c1_archive/simulations/campaigns/p1-v2-official-2026-10/results/calendars/calendar_index.json",
        "simulations/analysis/icit2027_editorial_synthesis_2026-10-27/c4_cutoff.json",
        "simulations/analysis/icit2027_editorial_synthesis_2026-10-27/analyze_results.py",
    ]
    sources=[]
    for rel in source_paths:
        path=ROOT/rel
        if path.is_file(): sources.append({"path":rel,"sha256":sha256(path),"bytes":path.stat().st_size})
    archive=Path("/home/jonatan/Downloads/p1-c1-results-partial.tar.gz")
    c1_source_ledger=ROOT/"simulations/analysis/vtc2027_spring_recent_results_2026-10-26/import_staging/c1_archive/simulations/campaigns/p1-v2-official-2026-10/results/runs.jsonl"
    source_set_counts={}
    for treatment in TREATMENTS:
        counts=Counter(r.get("source_hash_set_sha256") or "C4_snapshot_manifest_only" for r in runs if r["treatment"]==treatment)
        source_set_counts[treatment]=dict(counts)
    pair_audit={}
    run_index={(r["treatment"],r["load"],r["alignment"],r["seed"]):r for r in runs}
    for left,right in (("C0","C1"),("C1","C3"),("C0","C3"),("C3","C4")):
        common=[(load,align,seed) for (t,load,align,seed) in run_index
                if t==left and (right,load,align,seed) in run_index]
        signature_matches=0
        event_population_checks=0
        event_population_matches=0
        for load,align,seed in common:
            a,b=run_index[(left,load,align,seed)],run_index[(right,load,align,seed)]
            signature_matches += int(bool(a.get("calendar_signature")) and a.get("calendar_signature")==b.get("calendar_signature"))
            for fid in ("F21","F22"):
                ar=a.get("flow_metrics",{}).get(fid,{}).get("receivers",{})
                br=b.get("flow_metrics",{}).get(fid,{}).get("receivers",{})
                for receiver in sorted(set(ar)&set(br)):
                    event_population_checks += 1
                    event_population_matches += int(ar[receiver].get("offered")==br[receiver].get("offered"))
        pair_audit[f"{left}-{right}"]={"common_execution_pairs":len(common),
            "exact_calendar_signature_matches":signature_matches,
            "F21_F22_receiver_population_checks":event_population_checks,
            "F21_F22_exact_population_matches":event_population_matches,
            "calendar_signature_scope":"historical event-calendar signature stored in each finalized result; not byte comparison against regenerated current CSVs"}
    archive_ledger_count=sum(1 for line in c1_source_ledger.open() if line.strip()) if c1_source_ledger.is_file() else None
    c1_contract=json.loads((ROOT/"simulations/analysis/vtc2027_spring_recent_results_2026-10-26/import_staging/c1_archive/simulations/campaigns/p1-v2-official-2026-10/parallel_campaign_contract.json").read_text())
    provenance={
        "analysis_cutoff_local":cutoff["cutoff_local"],
        "c4_membership_rule":cutoff["basis"],
        "campaign_commit_at_manifest":campaign_manifest.get("commit"),
        "c4_snapshot_id":c4_manifest.get("snapshot_id"),
        "c4_snapshot_sha256":c4_manifest.get("snapshot_sha256"),
        "p1_path":"docs/design/P1-final.pdf",
        "p1_sha256":sha256(p1),
        "campaign_versions":{"omnetpp":campaign_manifest.get("omnetpp"),"omnetpp_runtime_version":campaign_manifest.get("omnetpp_runtime_version"),"inet":campaign_manifest.get("inet"),"inet_version_token":campaign_manifest.get("inet_version_token")},
        "c1_archive":{"path":str(archive),"sha256":"350efd7503556e287af0441881beb0028cb98ab8c4bcdfda11964b48c4e68288","bytes":6114344088,"preserved_original":True,
                       "archive_member_count":14914,"uncompressed_regular_file_bytes":6708329030,"unsafe_paths":0,"symlinks":0,
                       "source_ledger_rows":archive_ledger_count,"source_ledger_other_rows_excluded":max(0,(archive_ledger_count or 0)-240),
                       "imported_final_c1_rows":240,"duplicate_execution_ids":0,"report_calendar_ledger_mismatches":0,
                       "conflicts_at_target":0,"integration":"atomic rename of extracted results/final/C1 into campaign results/final/C1; no campaign ledger/calendar/manifest overwritten",
                       "source_campaign_commit":campaign_manifest.get("commit"),
                       "archive_parallel_contract_c4_snapshot_id":c1_contract.get("C4_snapshot_id"),
                       "current_c4_snapshot_id":c4_manifest.get("snapshot_id"),
                       "contract_difference_interpretation":"the shard package names the preceding C4 snapshot; this is a campaign-package provenance mismatch, not a C1 runtime-profile input because C1 does not instantiate/use C4"},
        "technical_attempts_c4":{"current_file":"simulations/campaigns/p1-v2-official-2026-10/c4_official/results/C4/technical_attempts.jsonl","row_count_at_analysis":6,
                                 "historical_sidecars":"technical_attempts_before_snapshot_partition.jsonl and technical_attempts_pre_current_snapshot.jsonl overlap earlier attempts; do not add sidecar counts as unique attempts",
                                 "not_included_as_simulation_results":True},
        "included_execution_count":len(runs),
        "included_by_treatment":{t:overall[t]["n"] for t in TREATMENTS},
        "included_executions":[{k:r[k] for k in ("execution_id","treatment","load","alignment","seed","report_path","report_sha256","calendar_signature","profile_sha256")} for r in runs],
        "source_hash_set_fingerprints_by_treatment":source_set_counts,
        "pairing_audit":pair_audit,
        "execution_source_hash_sets":[
            {"fingerprint_sha256":hashlib.sha256(json.dumps(d.get("configuration_source_hashes") or {},sort_keys=True,separators=(",",":")).encode()).hexdigest(),
             "configuration_source_hashes":d.get("configuration_source_hashes")}
            for d in {hashlib.sha256(json.dumps(item[2].get("configuration_source_hashes") or {},sort_keys=True,separators=(",",":")).encode()).hexdigest():item[2]
                      for item in raw if item[2].get("configuration_source_hashes")}.values()
        ],
        "c4_excluded_active_execution":cutoff.get("excluded_active_execution_id"),
        "source_files":sources,
        "manuscript_search":{"provided_tex_reviewed":True,"paper_path":"/home/jonatan/Downloads/paper.tex","paper_sha256":"e92ca675ad3112f44bc3bbb339c2f43a0f411214b798d304d3412f23288b33f1","bibliography_file_found":False,"limitation":"The attached TeX was available, but its references.bib was not present in the repository or Downloads; exact citekey-to-bibliography matching remains unverified."},
        "literature_sources":[
            {"citation":"Navet et al. (2017), Insights on the performance and configuration of AVB and TSN in automotive applications","url":"https://nicolas.navet.eu/publications.html","note":"P1 reference is an IEEE-SA Automotive Ethernet Technology Day presentation; not evidence that this project's specific combined evaluation is novel."},
            {"citation":"Migge et al. (2018), Insights on the performance and configuration of AVB and TSN in automotive Ethernet networks","url":"https://orbilu.uni.lu/handle/10993/40623","note":"P1 uses the published automotive Ethernet TSN study as traffic/mechanism context."},
            {"citation":"Luo et al. (2022), Design methodology of automotive time-sensitive network system based on OMNeT++ simulation system","doi":"10.3390/s22124580","url":"https://www.mdpi.com/1424-8220/22/12/4580","note":"P1 uses it for the reference automotive TSN/zonal traffic architecture."},
            {"citation":"IEEE ICIT 2027 Call for Papers and topics","url":"https://icit2027.ieee-ies.org/","note":"Official page lists Automotive Control and Transportation Systems and Network-based Control Systems and Applications; hard regular-paper deadline is 27 October 2026 23:59 BRT."},
            {"citation":"Maile et al. (2024), On the Effect of TSN Forwarding Mechanisms on Best-Effort Traffic","url":"https://doi.org/10.1145/3688268.3688283","note":"Compares SP, ATS, CBS, ETS and TAS; supports avoiding a broad first-comparison claim."},
            {"citation":"Leal Filho et al. (ISCC 2025), Predicting Transient Overloads Related to ADAS in Time-sensitive Vehicular Networks","url":"https://doi.org/10.1109/ISCC65549.2025.11326440","note":"Related transient-overload work; the exact manuscript citekey was not matched to a provided bibliography file."},
            {"citation":"Ashjaei et al. (2021), Time-Sensitive Networking in automotive embedded systems: State of the art and research opportunities","url":"https://doi.org/10.1016/j.sysarc.2021.102137","note":"Automotive TSN survey and context, not a directly matched experimental baseline."}
        ],
        "regeneration":{"command":"python3 simulations/analysis/icit2027_editorial_synthesis_2026-10-27/analyze_results.py && python3 simulations/analysis/icit2027_editorial_synthesis_2026-10-27/build_editorial_outputs.py","reads_only_final_reports_and_frozen_c4_cutoff":True,"starts_simulations":False}
    }
    derived_paths=("analysis.md","README.md","results_summary.json","coverage.csv",
                   "paired_comparisons.csv","execution_metrics.csv",)
    provenance["derived_artifact_sha256"]={rel:sha256(OUT/rel) for rel in derived_paths if (OUT/rel).is_file()}
    (OUT/"provenance_manifest.json").write_text(json.dumps(provenance,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(json.dumps({"runs":len(runs),"by_treatment":{t:overall[t]["n"] for t in TREATMENTS},
                      "coverage_written":len(cov),"paired_rows":len(comparisons),"output":str(OUT)},indent=2))


if __name__ == "__main__":
    main()
