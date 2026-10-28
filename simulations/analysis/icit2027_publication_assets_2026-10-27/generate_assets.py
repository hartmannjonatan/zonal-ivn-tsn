#!/usr/bin/env python3
"""Generate article-ready figures/tables from the frozen ICIT synthesis cutoff.

This script only reads the audited synthesis artifacts and writes derived files;
it never invokes a simulator or reads live campaign outputs.
"""
from __future__ import annotations

import csv
from decimal import Decimal
import hashlib
import json
import math
import os
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "simulations/analysis/icit2027_editorial_synthesis_2026-10-27"
OUT = Path(__file__).resolve().parent
ARTICLE_TO_HISTORY = {"C0": "C0", "C1": "C1", "C2": "C3", "C3": "C4"}
HISTORY_TO_ARTICLE = {v: k for k, v in ARTICLE_TO_HISTORY.items()}
LOADS = ["L0", "L1", "L2", "L3"]
ALIGNMENTS = ["A0", "A1"]
TREATMENTS = ["C0", "C1", "C2", "C3"]
COLORS = {"C0": "#35658D", "C1": "#D97827", "C2": "#3F8062", "C3": "#A34F75"}
MARKERS = {"C0": "o", "C1": "s", "C2": "^", "C3": "D"}
HISTORICAL_SOURCE_TREATMENT = {"C0": "C0", "C1": "C1", "C2": "C3", "C3": "C4"}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_csv(path: Path, rows: list[dict], fields: list[str] | None = None) -> None:
    if fields is None:
        fields = list(rows[0]) if rows else []
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def float_or_none(x):
    return None if x is None else float(x)


def receiver_for(run: dict, fid: str) -> tuple[str, dict]:
    recs = run["flow_metrics"][fid]["receivers"]
    # All flows selected here have one intended receiver in the audited summary.
    if len(recs) != 1:
        raise ValueError(f"Expected one receiver for {fid}, got {list(recs)}")
    return next(iter(recs.items()))


def source_run_lookup(data: dict) -> dict[tuple[str, str, str, int], dict]:
    lookup = {}
    for hist, info in data["treatment_summary"].items():
        article = HISTORY_TO_ARTICLE[hist]
        for run in info["runs"]:
            key = (article, run["load"], run["alignment"], int(run["seed"]))
            if key in lookup:
                raise ValueError(f"Duplicate run key {key}")
            lookup[key] = run
    return lookup


def percentile(values, q):
    v = np.asarray([x for x in values if x is not None and math.isfinite(float(x))], dtype=float)
    if not len(v):
        return None
    return float(np.quantile(v, q, method="linear"))


def median(values):
    return percentile(values, 0.5)


def image_rows(lookup: dict) -> list[dict]:
    rows = []
    for (t, load, align, seed), run in sorted(lookup.items()):
        if t not in ("C0", "C1") or align not in ("A0", "A1") or load not in LOADS:
            continue
        for fid in ("F02", "F05"):
            receiver, p = receiver_for(run, fid)
            im = p["image_metrics"]
            if im is None:
                raise ValueError(f"Missing image metrics {run['execution_id']} {fid}")
            offered_i = int(im["offered"])
            completed = int(im["completed"])
            rows.append({
                "article_treatment": t,
                "historical_treatment": run["treatment"],
                "execution_id": run["execution_id"],
                "load": load, "alignment": align, "seed": seed,
                "calendar_signature": run["calendar_signature"],
                "flow": fid, "receiver": receiver,
                "offered_packets": int(p["offered"]),
                "received_packets": int(p["received"]),
                "lost_packets": int(p["losses_offered_minus_received"]),
                "packet_loss_ratio": float(p["packet_loss_ratio"]),
                "offered_images": offered_i,
                "complete_images": completed,
                "incomplete_images": int(im["incomplete"]),
                "image_deadline_misses_completed": int(im["deadline_misses_completed"]),
                "image_deadline_misses_including_incomplete": int(im["deadline_misses_completed"])+int(im["incomplete"]),
                "image_deadline_miss_ratio_including_incomplete": float(im["deadline_miss_ratio_including_incomplete"]),
                "image_completion_fraction": completed / offered_i if offered_i else None,
                "p99_image_completion_ms_complete_only": float_or_none(im["p99_completion_s"])*1000 if im["p99_completion_s"] is not None else None,
                "max_image_completion_ms_complete_only": float_or_none(im["max_completion_s"])*1000 if im["max_completion_s"] is not None else None,
                "p99_quantile_population_complete_images": int(im["quantile_population_complete_images"]),
                "deadline_ms": float(im["deadline_s"])*1000,
                "packet_p99_ms": float(p["p99_latency_s"])*1000 if p["p99_latency_s"] is not None else None,
                "packet_max_ms": float(p["max_latency_s"])*1000 if p["max_latency_s"] is not None else None,
            })
    return rows


def summarize_image_rows(rows: list[dict]) -> list[dict]:
    groups = defaultdict(list)
    for r in rows:
        groups[(r["article_treatment"], r["flow"], r["alignment"], r["load"])].append(r)
    out = []
    for (t, fid, a, l), rs in sorted(groups.items()):
        compl = [r["image_completion_fraction"] for r in rs]
        lat = [r["p99_image_completion_ms_complete_only"] for r in rs]
        out.append({
            "article_treatment": t, "flow": fid, "alignment": a, "load": l,
            "n_runs": len(rs),
            "completion_fraction_mean_across_runs": float(np.mean(compl)),
            "completion_fraction_median_across_runs": median(compl),
            "completion_fraction_q25_across_runs": percentile(compl, .25),
            "completion_fraction_q75_across_runs": percentile(compl, .75),
            "p99_complete_image_ms_median_across_runs": median(lat),
            "p99_complete_image_ms_q25_across_runs": percentile(lat, .25),
            "p99_complete_image_ms_q75_across_runs": percentile(lat, .75),
            "n_runs_with_defined_complete_image_p99": sum(x is not None for x in lat),
            "offered_images_sum": sum(r["offered_images"] for r in rs),
            "complete_images_sum": sum(r["complete_images"] for r in rs),
            "incomplete_images_sum": sum(r["incomplete_images"] for r in rs),
            "image_deadline_misses_completed_sum": sum(r["image_deadline_misses_completed"] for r in rs),
            "image_deadline_misses_including_incomplete_sum": sum(r["image_deadline_misses_including_incomplete"] for r in rs),
            "offered_packets_sum": sum(r["offered_packets"] for r in rs),
            "lost_packets_sum": sum(r["lost_packets"] for r in rs),
            "deadline_ms": rs[0]["deadline_ms"],
        })
    return out


def viability_and_pairs(data: dict, lookup: dict):
    cov_path = SOURCE / "coverage_editorial.csv"
    coverage = {}
    with cov_path.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            coverage[(r["paper_treatment"], r["load"], r["alignment"])] = r
    rows = []
    for load in LOADS:
        for align in ALIGNMENTS:
            row = {"load_alignment": f"{load}/{align}", "load": load, "alignment": align}
            for t in TREATMENTS:
                c = coverage[(t, load, align)]
                n = int(c["completed_valid_included"])
                approved = int(c["approved"])
                rejected = int(c["rejected_by_triage"])
                status = c["status"]
                if n:
                    cell = f"{approved}/{n}" + ("†" if n < int(c["planned"]) else "")
                    table_state = "partial" if n < int(c["planned"]) else "observed"
                elif rejected:
                    marker = "R" if t == "C2" else "S"
                    cell, table_state = f"—{marker}", "rejected_by_reservation" if marker == "R" else "rejected_by_service_screen"
                else:
                    cell, table_state = "—", "not_observed"
                row[t] = cell
                for field, val in {
                    "n_planned": int(c["planned"]), "n_included": n,
                    "n_approved": approved,
                    "n_valid_performance_reprovals": int(c["valid_performance_reprovals"]),
                    "rejected_by_triage": rejected,
                    "coverage_status": status, "table_status": table_state,
                    "seeds": c["seeds"],
                }.items():
                    row[f"{t}_{field}"] = val
            rows.append(row)
    pairs = []
    # Editorial C2 is campaign C3; editorial C3 is campaign C4.
    for load in ("L0", "L1", "L2"):
        for align in ALIGNMENTS:
            c2runs = {s: r for (t,l,a,s),r in lookup.items() if t == "C2" and l == load and a == align}
            c3runs = {s: r for (t,l,a,s),r in lookup.items() if t == "C3" and l == load and a == align}
            for seed in sorted(set(c2runs) & set(c3runs)):
                a, b = c2runs[seed], c3runs[seed]
                pop_equal = True
                f21f22 = {}
                for fid in ("F21", "F22"):
                    _, pa = receiver_for(a, fid); _, pb = receiver_for(b, fid)
                    oa, ob = int(pa["offered"]), int(pb["offered"])
                    f21f22[f"{fid}_offered_c2"] = oa
                    f21f22[f"{fid}_offered_c3"] = ob
                    f21f22[f"{fid}_population_match"] = oa == ob
                    pop_equal &= oa == ob
                sig_equal = a["calendar_signature"] == b["calendar_signature"]
                pairs.append({
                    "load": load, "alignment": align, "seed": seed,
                    "C2_execution_id": a["execution_id"], "C3_execution_id": b["execution_id"],
                    "C2_historical_treatment": a["treatment"], "C3_historical_treatment": b["treatment"],
                    "C2_calendar_signature": a["calendar_signature"], "C3_calendar_signature": b["calendar_signature"],
                    "calendar_signature_match": sig_equal,
                    "F21_F22_offered_populations_match": pop_equal,
                    **f21f22,
                    "C2_approved": bool(a["top_level_viable"]),
                    "C3_approved": bool(b["top_level_viable"]),
                    "paired_approval_delta_C3_minus_C2": int(bool(b["top_level_viable"])) - int(bool(a["top_level_viable"])),
                    "pairing_verified": sig_equal and pop_equal,
                })
    summaries = []
    for load in ("L0", "L1", "L2"):
        ps = [p for p in pairs if p["load"] == load]
        summaries.append({
            "load": load, "n_common_pairs": len(ps),
            "n_calendar_and_population_verified": sum(p["pairing_verified"] for p in ps),
            "C2_approved_pairs": sum(p["C2_approved"] for p in ps),
            "C3_approved_pairs": sum(p["C3_approved"] for p in ps),
            "C2_fail_C3_pass": sum(not p["C2_approved"] and p["C3_approved"] for p in ps),
            "C2_pass_C3_fail": sum(p["C2_approved"] and not p["C3_approved"] for p in ps),
            "both_pass": sum(p["C2_approved"] and p["C3_approved"] for p in ps),
            "both_fail": sum(not p["C2_approved"] and not p["C3_approved"] for p in ps),
        })
    return rows, pairs, summaries


def critical_flow_rows(lookup: dict):
    rows = []
    for (t, load, align, seed), run in sorted(lookup.items()):
        if t not in TREATMENTS or load not in ("L0", "L1", "L2") or align != "A0":
            continue
        for fid in ("F06", "F07", "F08", "F09", "F10"):
            receiver, p = receiver_for(run, fid)
            deadline = 100.0  # all selected critical flows have 100 us deadline in P1
            p99 = float(p["p99_latency_s"])*1e6 if p["p99_latency_s"] is not None else None
            mx = float(p["max_latency_s"])*1e6 if p["max_latency_s"] is not None else None
            rows.append({
                "article_treatment": t, "historical_treatment": run["treatment"],
                "execution_id": run["execution_id"], "flow": fid, "receiver": receiver,
                "load": load, "alignment": align, "seed": seed,
                "calendar_signature": run["calendar_signature"],
                "offered_packets": int(p["offered"]), "received_packets": int(p["received"]),
                "lost_packets": int(p["losses_offered_minus_received"]),
                "deadline_misses_received": int(p["deadline_misses_received"]),
                "deadline_misses_including_losses": int(p["deadline_misses_received"])+int(p["losses_offered_minus_received"]),
                "deadline_miss_ratio_including_losses": float(p["deadline_misses_including_loss_ratio"]),
                "deadline_us": deadline, "p99_latency_us": p99, "max_latency_us": mx,
                "p99_margin_us": deadline-p99 if p99 is not None else None,
                "max_observed_margin_us": deadline-mx if mx is not None else None,
                "receiver_viable": p["reported_receiver_viable"],
                "execution_viable": bool(run["top_level_viable"]),
                "nonstable_queue_count": run["nonstable_queue_count"],
            })
    return rows


def paired_latency(lookup: dict):
    rows = []
    for load in ("L0", "L1", "L2"):
        for align in ALIGNMENTS:
            a = {s:r for (t,l,al,s),r in lookup.items() if t=="C2" and l==load and al==align}
            b = {s:r for (t,l,al,s),r in lookup.items() if t=="C3" and l==load and al==align}
            for seed in sorted(set(a)&set(b)):
                r2,r3=a[seed],b[seed]
                _,p2=receiver_for(r2,"F06")
                _,p3=receiver_for(r3,"F06")
                row={"load":load,"alignment":align,"seed":seed,
                    "C2_execution_id":r2["execution_id"],"C3_execution_id":r3["execution_id"],
                    "calendar_signature_match":r2["calendar_signature"]==r3["calendar_signature"],
                    "C2_approved":bool(r2["top_level_viable"]),"C3_approved":bool(r3["top_level_viable"]),
                    "approval_delta_C3_minus_C2":int(bool(r3["top_level_viable"]))-int(bool(r2["top_level_viable"]))}
                for fid in ("F06","F07","F08","F09","F10"):
                    _,x=receiver_for(r2,fid); _,y=receiver_for(r3,fid)
                    for stat,field,mult in (("p99","p99_latency_s",1e6),("max","max_latency_s",1e6)):
                        xval=float(x[field])*mult if x[field] is not None else None
                        yval=float(y[field])*mult if y[field] is not None else None
                        row[f"C2_{fid}_{stat}_us"]=xval
                        row[f"C3_{fid}_{stat}_us"]=yval
                        row[f"delta_C3_minus_C2_{fid}_{stat}_us"]=(yval-xval) if xval is not None and yval is not None else None
                # Distinct statistic: max of flow-level per-run p99s and max observed latencies.
                p99_2=max(row[f"C2_{f}_p99_us"] for f in ("F08","F09","F10"))
                p99_3=max(row[f"C3_{f}_p99_us"] for f in ("F08","F09","F10"))
                max_2=max(row[f"C2_{f}_max_us"] for f in ("F08","F09","F10"))
                max_3=max(row[f"C3_{f}_max_us"] for f in ("F08","F09","F10"))
                row.update({"C2_brake_max_flow_p99_us":p99_2,"C3_brake_max_flow_p99_us":p99_3,
                    "delta_brake_max_flow_p99_us":p99_3-p99_2,
                    "C2_brake_max_observed_us":max_2,"C3_brake_max_observed_us":max_3,
                    "delta_brake_max_observed_us":max_3-max_2})
                rows.append(row)
    summaries=[]
    for load in ("L0","L1","L2"):
        for align in ALIGNMENTS:
            rs=[r for r in rows if r["load"]==load and r["alignment"]==align]
            if not rs: continue
            summary={"load":load,"alignment":align,"n_pairs":len(rs),
                "n_calendar_signature_matches":sum(bool(r["calendar_signature_match"]) for r in rs),
                "median_delta_brake_max_flow_p99_us":median([r["delta_brake_max_flow_p99_us"] for r in rs]),
                "min_delta_brake_max_flow_p99_us":min(r["delta_brake_max_flow_p99_us"] for r in rs),
                "max_delta_brake_max_flow_p99_us":max(r["delta_brake_max_flow_p99_us"] for r in rs),
                "median_delta_brake_max_observed_us":median([r["delta_brake_max_observed_us"] for r in rs]),
                "min_delta_brake_max_observed_us":min(r["delta_brake_max_observed_us"] for r in rs),
                "max_delta_brake_max_observed_us":max(r["delta_brake_max_observed_us"] for r in rs),
                "C2_fail_C3_pass":sum(not r["C2_approved"] and r["C3_approved"] for r in rs),
                "both_pass":sum(r["C2_approved"] and r["C3_approved"] for r in rs)}
            for fid in ("F06","F07","F08","F09","F10"):
                for stat in ("p99","max"):
                    vals=[r[f"delta_C3_minus_C2_{fid}_{stat}_us"] for r in rs]
                    summary[f"median_delta_{fid}_{stat}_us"]=median(vals)
                    summary[f"min_delta_{fid}_{stat}_us"]=min(vals)
                    summary[f"max_delta_{fid}_{stat}_us"]=max(vals)
            summaries.append(summary)
    return rows,summaries


def make_viability_tex(rows: list[dict]) -> str:
    lines=[r"\begin{table}[t]",r"\centering",r"\caption{Viability outcomes and completed-run coverage}",r"\label{tab:viability}",r"\footnotesize",r"\setlength{\tabcolsep}{3.5pt}",r"\begin{tabular}{@{}lcccc@{}}",r"\toprule",r"Cell & C0 & C1 & C2 & C3 \\",r"\midrule"]
    for r in rows:
        vals=[]
        for t in TREATMENTS:
            value=r[t]
            if value.endswith("†"):
                value=value[:-1]+r"$^{\dagger}$"
            elif value.startswith("—"):
                marker=value[-1]
                value=r"--$^{"+marker+r"}$"
            vals.append(value)
        lines.append(f"{r['load_alignment']} & " + " & ".join(vals) + r" \\")
    lines += [r"\bottomrule",r"\end{tabular}",r"\par\vspace{2pt}",r"\begin{minipage}{\columnwidth}\footnotesize",r"\textit{Note:} Entries are approved/completed runs; each admissible cell targets 30 runs. $^{\dagger}$ marks partial coverage ($n<30$). $R$ and $S$ denote pre-simulation rejection in the reservation and service screens, respectively; neither is an observed simulation failure. Approval describes observed runs and is not a deterministic guarantee.",r"\end{minipage}",r"\end{table}"]
    return "\n".join(lines)+"\n"


def reservation_assets():
    source=SOURCE/"reservation_profiles.csv"
    bykey={}
    with source.open(encoding="utf-8",newline="") as f:
        for r in csv.DictReader(f):
            bykey[(r["paper_treatment"],r["load"],r["egress"],r["tc"])]=r
    requested=[("CSW$\\rightarrow$HPC", "CSW.eth[0]", "6"),
        ("HPC$\\rightarrow$CSW", "HPC.eth[0]", "4"),
        ("Z1$\\rightarrow$CSW", "Z1.ZSW.eth[0]", "4"),
        ("CSW$\\rightarrow$Z3", "CSW.eth[3]", "4")]
    rows=[]
    for path,egress,tc in requested:
        for load in ("L0","L1","L2"):
            c2=bykey[("C2",load,egress,tc)]
            c3=bykey[("C3","all_L0-L2",egress,tc)]
            for article,r,profile in (("C2",c2,"load-scaled calibrated CBS"),("C3",c3,"D3_coordinated_20pct fixed absolute")):
                rows.append({"article_treatment":article,"historical_treatment":HISTORICAL_SOURCE_TREATMENT[article],
                    "load":load,"path":path,"egress_interface":egress,"tc":int(tc),"profile":profile,
                    "idleSlope_Mbps":float(r["idleSlope_bps"])/1e6,"idleSlope_bps":int(float(r["idleSlope_bps"])),
                    "port_total_idleSlope_Mbps":float(r["port_total_idleSlope_bps"])/1e6,
                    "physical_rate_Mbps":float(r["physical_rate_bps"])/1e6,
                    "port_reservation_fraction":float(r["reservation_fraction"]),
                    "headroom_to_75pct_Mbps":float(r["headroom_to_75pct_bps"])/1e6})
    return rows


def compact_reservation_assets():
    """Wide, exact-precision table; source is the audited per-port reservation CSV."""
    source=SOURCE/"reservation_profiles.csv"
    rows={}
    with source.open(encoding="utf-8",newline="") as f:
        for r in csv.DictReader(f):
            rows[(r["paper_treatment"],r["load"],r["egress"],r["tc"])]=r
    paths=[("CSW$\\rightarrow$HPC / TC6","CSW.eth[0]","6"),
        ("HPC$\\rightarrow$CSW / TC4","HPC.eth[0]","4"),
        ("Z1$\\rightarrow$CSW / TC4","Z1.ZSW.eth[0]","4"),
        ("CSW$\\rightarrow$Z3 / TC4","CSW.eth[3]","4")]
    compact=[]
    for label,egress,tc in paths:
        x={"egress_class":label,"egress_interface":egress,"tc":int(tc)}
        for load in ("L0","L1","L2"):
            x[f"C2_{load}_idleSlope_bps"]=int(Decimal(rows[("C2",load,egress,tc)]["idleSlope_bps"]))
            x[f"C2_{load}_idleSlope_Mbps_exact"]=format(Decimal(rows[("C2",load,egress,tc)]["idleSlope_bps"])/Decimal(1_000_000),"f")
        fixed=rows[("C3","all_L0-L2",egress,tc)]
        fixed_bps=int(Decimal(fixed["idleSlope_bps"]))
        # Verify source has a single fixed profile and reproduce it in all load columns.
        x["C3_fixed_L0_L2_idleSlope_bps"]=fixed_bps
        x["C3_fixed_L0_L2_idleSlope_Mbps_exact"]=format(Decimal(fixed["idleSlope_bps"])/Decimal(1_000_000),"f")
        # Audit context: totals and 75% headroom belong to this egress port.
        for article,load,source_row in [("C2",l,rows[("C2",l,egress,tc)]) for l in ("L0","L1","L2")]+[("C3","fixed",fixed)]:
            prefix=f"{article}_{load}"
            x[f"{prefix}_port_total_idleSlope_bps"]=int(Decimal(source_row["port_total_idleSlope_bps"]))
            x[f"{prefix}_headroom_to_75pct_bps"]=int(Decimal(source_row["headroom_to_75pct_bps"]))
        compact.append(x)
    return compact


def reservation_compact_tex(rows: list[dict]) -> str:
    lines=[r"\begin{table}[t]",r"\centering",r"\caption{Configured CBS idleSlope per egress and class (Mb/s). C2 scales reservations with load; C3 uses the fixed, redesigned profile across L0--L2.}",r"\label{tab:compact-reservations}",r"\footnotesize",r"\setlength{\tabcolsep}{3pt}",r"\begin{tabular}{@{}lrrrr@{}}",r"\toprule",r"Egress / class & C2/L0 & C2/L1 & C2/L2 & C3 fixed \\",r"\midrule"]
    for r in rows:
        vals=[Decimal(r[f"C2_{l}_idleSlope_Mbps_exact"]) for l in ("L0","L1","L2")]
        vals.append(Decimal(r["C3_fixed_L0_L2_idleSlope_Mbps_exact"]))
        lines.append(r["egress_class"]+" & "+" & ".join(f"{v:.3f}" for v in vals)+r" \\")
    lines += [r"\bottomrule",r"\end{tabular}",r"\par\vspace{2pt}",r"\begin{minipage}{\columnwidth}\footnotesize",r"Values are configured idleSlope rates, not measured utilization. Full precision in bit/s and per-port totals/headroom are in \texttt{table\_reservations\_compact.csv}; do not sum different egresses as bandwidth consumed on one link.",r"\end{minipage}",r"\end{table}"]
    return "\n".join(lines)+"\n"


def plot_camera(rows: list[dict], summary: list[dict]):
    # 7.1 in double-column width; two rows of compact panels.
    fig,axs=plt.subplots(2,2,figsize=(7.0,5.25),constrained_layout=True)
    panels=[("F02","completion",axs[0,0],"(a)"),("F02","latency",axs[0,1],"(b)"),
        ("F05","completion",axs[1,0],"(c)"),("F05","latency",axs[1,1],"(d)")]
    xbase=np.arange(4,dtype=float)
    offsets={"C0":-.14,"C1":.14}
    for fid,metric,ax,panel in panels:
        for t in ("C0","C1"):
            for i,load in enumerate(LOADS):
                rs=[r for r in rows if r["flow"]==fid and r["alignment"]=="A1" and r["load"]==load and r["article_treatment"]==t]
                vals=[r["image_completion_fraction"] if metric=="completion" else r["p99_image_completion_ms_complete_only"] for r in rs]
                vals=np.asarray([v for v in vals if v is not None],dtype=float)
                x=xbase[i]+offsets[t]
                # Deterministic jitter, one dot per independent execution.
                rng=np.random.default_rng(900+i*11+(0 if t=="C0" else 1)+(0 if fid=="F02" else 50))
                jitter=rng.uniform(-.045,.045,len(vals))
                ax.scatter(np.full(len(vals),x)+jitter,vals,s=12,alpha=.58,color=COLORS[t],marker=MARKERS[t],linewidths=0.25,edgecolors="white",zorder=2)
                if len(vals):
                    med=float(np.median(vals)); q1,q3=np.quantile(vals,[.25,.75])
                    ax.errorbar([x],[med],yerr=[[med-q1],[q3-med]],fmt=MARKERS[t],markersize=7,
                        color=COLORS[t],markerfacecolor=COLORS[t],markeredgecolor="#222222",
                        ecolor=COLORS[t],elinewidth=1.1,capsize=2,zorder=4)
        ax.set_xticks(xbase,LOADS)
        ax.grid(axis="y",color="#dddddd",linewidth=.55)
        ax.set_axisbelow(True)
        if metric=="completion":
            ax.set_ylim(-.04,1.06)
            ax.set_ylabel("Complete images / offered images")
            ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0, decimals=0))
            ax.set_title(f"{panel} {fid}: image completion",loc="left",fontsize=9,fontweight="bold")
        else:
            deadline=10 if fid=="F02" else 30
            ax.axhline(deadline,color="#222222",linestyle=(0,(4,2)),linewidth=1.0,zorder=1)
            ax.set_ylabel("Per-run image-completion p99 (ms)")
            ax.set_title(f"{panel} {fid}: p99 among complete images",loc="left",fontsize=9,fontweight="bold")
            maxval=max([v for r in rows if r["flow"]==fid and r["alignment"]=="A1" for v in [r["p99_image_completion_ms_complete_only"]] if v is not None]+[deadline])
            ax.set_ylim(0,max(deadline*1.12,maxval*1.08))
        if metric=="completion":
            rs=[r for r in rows if r["flow"]==fid and r["alignment"]=="A1" and r["load"]=="L3" and r["article_treatment"]=="C0"]
            median_pct=100*median([r["image_completion_fraction"] for r in rs])
            aggregate_pct=100*sum(r["complete_images"] for r in rs)/sum(r["offered_images"] for r in rs)
            # Annotate the same run-level median represented by the large marker.
            # The aggregate is recorded separately in README/CSVs, not mixed into this callout.
            y=median([r["image_completion_fraction"] for r in rs])
            text_x,text_y=(2.05,.38) if fid=="F02" else (2.05,.40)
            ax.annotate(f"Median {median_pct:.2f}%",xy=(3+offsets["C0"],y),
                xytext=(text_x,text_y),textcoords="data",fontsize=7.0,ha="center",
                arrowprops=dict(arrowstyle="-",color=COLORS["C0"],lw=.7),color=COLORS["C0"])
        ax.set_xlabel("Load")
    # One legend for the complete figure, avoiding covering any data.
    from matplotlib.lines import Line2D
    handles=[Line2D([0],[0],marker=MARKERS[t],color="none",markerfacecolor=COLORS[t],markeredgecolor="#222222",markersize=6,label=t) for t in ("C0","C1")]
    handles.append(Line2D([0],[0],color="#222",linestyle=(0,(4,2)),linewidth=1,label="Deadline line"))
    fig.legend(handles=handles,loc="upper center",ncol=3,frameon=False,bbox_to_anchor=(.5,1.04),fontsize=8)
    fig.savefig(OUT/"fig_camera_delivery_latency.pdf",bbox_inches="tight")
    fig.savefig(OUT/"fig_camera_delivery_latency.svg",bbox_inches="tight")
    fig.savefig(OUT/"fig_camera_delivery_latency.png",dpi=400,bbox_inches="tight")
    plt.close(fig)


def plot_critical(rows: list[dict]):
    fig,axs=plt.subplots(1,2,figsize=(7.0,3.30),constrained_layout=True)
    xbase=np.arange(3,dtype=float)
    offsets={"C0":-.27,"C1":-.09,"C2":.09,"C3":.27}
    metrics=[("radar","(a) Radar flows F06–F07",("F06","F07")),("brake","(b) Brake flows F08–F10",("F08","F09","F10"))]
    from matplotlib.lines import Line2D
    for ax,(label,title,flows) in zip(axs,metrics):
        for t in TREATMENTS:
            for i,load in enumerate(("L0","L1","L2")):
                selected=[]
                for runid in sorted(set(r["execution_id"] for r in rows if r["article_treatment"]==t and r["load"]==load)):
                    fr=[r for r in rows if r["execution_id"]==runid and r["flow"] in flows]
                    if len(fr)==len(flows):
                        selected.append((max(r["p99_latency_us"] for r in fr),runid))
                vals=np.asarray([v for v,_ in selected],dtype=float)
                x=xbase[i]+offsets[t]
                rng=np.random.default_rng(321+i*19+TREATMENTS.index(t)+(0 if label=="radar" else 80))
                jitter=rng.uniform(-.045,.045,len(vals))
                ax.scatter(np.full(len(vals),x)+jitter,vals,s=14,alpha=.62,color=COLORS[t],marker=MARKERS[t],edgecolors="white",linewidths=.25,zorder=2)
                if len(vals):
                    med=float(np.median(vals));q1,q3=np.quantile(vals,[.25,.75])
                    ax.errorbar([x],[med],yerr=[[med-q1],[q3-med]],fmt=MARKERS[t],markersize=7,
                        color=COLORS[t],markerfacecolor=COLORS[t],markeredgecolor="#222222",
                        ecolor=COLORS[t],elinewidth=1,capsize=2,zorder=4)
                    # C0--C2 have complete n=30 coverage in these cells; label
                    # C3 explicitly because its A0 coverage is partial at L1/L2.
                    if t == "C3":
                        ax.annotate(f"n={len(vals)}",(x,med),xytext=(0,5),textcoords="offset points",ha="center",fontsize=6.5,color=COLORS[t])
        ax.axhline(100,color="#222",linestyle=(0,(4,2)),linewidth=1.0,zorder=1)
        ax.set_xticks(xbase,["L0","L1","L2"])
        ax.set_xlabel("Load (A0)")
        ax.set_ylabel("Per-run maximum of flows' individual p99s (µs)")
        ax.set_title(title,loc="left",fontsize=9,fontweight="bold")
        ax.grid(axis="y",color="#dddddd",linewidth=.55);ax.set_axisbelow(True)
        ymax=max([r["p99_latency_us"] for r in rows if r["flow"] in flows]+[100])
        ax.set_ylim(0,ymax*1.16)
    handles=[Line2D([0],[0],marker=MARKERS[t],color="none",markerfacecolor=COLORS[t],markeredgecolor="#222222",markersize=6,label=t) for t in TREATMENTS]
    handles.append(Line2D([0],[0],color="#222",linestyle=(0,(4,2)),linewidth=1,label="100 µs deadline"))
    fig.legend(handles=handles,loc="upper center",ncol=5,frameon=False,bbox_to_anchor=(.5,1.12),fontsize=8)
    fig.savefig(OUT/"fig_critical_latency.pdf",bbox_inches="tight")
    fig.savefig(OUT/"fig_critical_latency.svg",bbox_inches="tight")
    fig.savefig(OUT/"fig_critical_latency.png",dpi=400,bbox_inches="tight")
    plt.close(fig)


def main():
    if not SOURCE.is_dir(): raise SystemExit(f"Missing frozen source {SOURCE}")
    # Fail closed: the directory is intentionally a new immutable-cutoff package.
    manifest=json.loads((SOURCE/"analysis_manifest.json").read_text())
    data=json.loads((SOURCE/"results_summary.json").read_text())
    if data["analysis_cutoff"] != manifest["analysis_cutoff"]:
        raise ValueError("Frozen cutoff mismatch")
    if int(manifest["c4_cutoff_rows"]) != 90:
        raise ValueError("Expected the frozen 90-run combined-treatment cutoff")
    lookup=source_run_lookup(data)
    expected={"C0":240,"C1":240,"C2":180,"C3":90}
    actual={t:sum(k[0]==t for k in lookup) for t in expected}
    if actual!=expected: raise ValueError(f"Frozen treatment counts changed: {actual}")
    # Verify article C3 against the frozen cutoff ledger snapshot, never live files.
    cutoff_rows=json.loads((SOURCE/"c4_cutoff.json").read_text())
    frozen_c3={r["execution_id"]:r["run_report_sha256"] for r in cutoff_rows["included_rows"]}
    summarized_c3={r["execution_id"]:r["report_sha256"] for r in data["treatment_summary"]["C4"]["runs"]}
    if len(frozen_c3)!=90 or frozen_c3!=summarized_c3:
        raise ValueError("Article C3 does not exactly match the frozen C4 cutoff IDs and report hashes")
    all_ids=[r["execution_id"] for summary in data["treatment_summary"].values() for r in summary["runs"]]
    if len(set(all_ids))!=750:
        raise ValueError("Duplicate execution IDs in the frozen result set")

    # Viability table and paired outcome audit.
    vrows,pairs,pair_summary=viability_and_pairs(data,lookup)
    write_csv(OUT/"table_viability.csv",vrows)
    (OUT/"table_viability.tex").write_text(make_viability_tex(vrows),encoding="utf-8")
    write_csv(OUT/"paired_viability.csv",pairs)
    write_csv(OUT/"paired_viability_summary_by_load.csv",pair_summary)
    for load,expected_n,expected_discord in (("L0",60,60),("L1",24,24),("L2",6,0)):
        s=next(r for r in pair_summary if r["load"]==load)
        if s["n_common_pairs"]!=expected_n or s["C2_fail_C3_pass"]!=expected_discord:
            raise ValueError(f"Paired viability count mismatch at {load}: {s}")
    if any(not p["pairing_verified"] for p in pairs): raise ValueError("Unverified common C2/C3 pair")

    # Camera run-level values for A1 figure and supplemental L0/A0 cohort.
    cam=image_rows(lookup)
    cam_selected=[r for r in cam if r["alignment"]=="A1" or (r["load"]=="L0" and r["alignment"]=="A0")]
    write_csv(OUT/"fig1_camera_runs.csv",cam_selected)
    cam_summary=summarize_image_rows(cam_selected)
    write_csv(OUT/"fig1_camera_summary.csv",cam_summary)
    known={("F02",219747,219565),("F05",360145,186094)}
    for fid,expected_loss,expected_inc in known:
        rs=[r for r in cam if r["flow"]==fid and r["article_treatment"]=="C0" and r["load"]=="L3" and r["alignment"]=="A1"]
        gotloss=sum(r["lost_packets"] for r in rs); gotinc=sum(r["incomplete_images"] for r in rs)
        if (gotloss,gotinc)!=(expected_loss,expected_inc):
            raise ValueError(f"Known {fid} aggregate mismatch {(gotloss,gotinc)}")
    c1bad=[r for r in cam if r["article_treatment"]=="C1" and r["load"]=="L3" and r["alignment"]=="A1" and (r["lost_packets"] or r["incomplete_images"])]
    if c1bad: raise ValueError("C1 L3/A1 expected zero camera loss/incomplete images per frozen synthesis")
    camera_low_group={}
    for fid,expected_median,expected_aggregate in (("F02",.023866666666666668,.024155555555555548),
                                                    ("F05",.17573333333333335,.17291555555555557)):
        rs=[r for r in cam if r["flow"]==fid and r["article_treatment"]=="C0" and r["load"]=="L3" and r["alignment"]=="A1"]
        med=median([r["image_completion_fraction"] for r in rs])
        aggregate=sum(r["complete_images"] for r in rs)/sum(r["offered_images"] for r in rs)
        if not math.isclose(med,expected_median,abs_tol=1e-12) or not math.isclose(aggregate,expected_aggregate,abs_tol=1e-12):
            raise ValueError(f"C0/L3/A1 {fid} completion median/aggregate mismatch: {med}, {aggregate}")
        camera_low_group[fid]={"median_fraction":med,"aggregate_fraction":aggregate,
            "median_percent":med*100,"aggregate_percent":aggregate*100}
    plot_camera(cam,cam_summary)

    # Run-level radar/brake statistics in A0, plus full matched C2/C3 seed deltas.
    critical=critical_flow_rows(lookup)
    write_csv(OUT/"fig2_critical_latency_runs.csv",critical)
    pairlat,pairlat_summary=paired_latency(lookup)
    write_csv(OUT/"paired_C3_minus_C2_latency.csv",pairlat)
    write_csv(OUT/"paired_C3_minus_C2_latency_summary.csv",pairlat_summary)
    plot_critical(critical)
    brake_low_points=[]
    for seed,expected_p99 in ((1006,28.385141),(1010,7.212)):
        for load in ("L0","L1"):
            fr=[r for r in critical if r["article_treatment"]=="C3" and r["alignment"]=="A0" and r["load"]==load and int(r["seed"])==seed and r["flow"] in ("F08","F09","F10")]
            got=max(r["p99_latency_us"] for r in fr)
            if len(fr)!=3 or not math.isclose(got,expected_p99,abs_tol=1e-6):
                raise ValueError(f"Audited low brake point mismatch for seed {seed}, {load}: n={len(fr)}, max p99={got}")
            brake_low_points.append({"seed":seed,"load":load,"alignment":"A0",
                "max_of_F08_F10_per_flow_p99_us":got,
                "max_observed_latency_us_in_flows":max(r["max_latency_us"] for r in fr)})
    c3_brake_max=[]
    for run in data["treatment_summary"]["C4"]["runs"]:
        for fid in ("F08","F09","F10"):
            _,metric=receiver_for(run,fid)
            c3_brake_max.append({"execution_id":run["execution_id"],"load":run["load"],"alignment":run["alignment"],
                "seed":int(run["seed"]),"flow":fid,"max_latency_us":float(metric["max_latency_s"])*1e6})
    max_brake_record=max(c3_brake_max,key=lambda r:r["max_latency_us"])
    if not math.isclose(max_brake_record["max_latency_us"],78.460831,abs_tol=1e-6):
        raise ValueError(f"C3 cutoff maximum brake latency changed: {max_brake_record}")

    # Compact selected reserve comparisons, backed by source rate-level rows.
    reserve=reservation_assets()
    write_csv(OUT/"table_reservations.csv",reserve)
    compact_reserves=compact_reservation_assets()
    expected_rates={
        "CSW$\\rightarrow$HPC / TC6":(62352000,124704000,311760000,311760000),
        "HPC$\\rightarrow$CSW / TC4":(78240000,94800000,144480000,406375399),
        "Z1$\\rightarrow$CSW / TC4":(47370000,94740000,236850000,236850000),
        "CSW$\\rightarrow$Z3 / TC4":(49520000,99040000,247600000,707606774),
    }
    for row in compact_reserves:
        got=tuple(row[f"C2_{l}_idleSlope_bps"] for l in ("L0","L1","L2"))+(row["C3_fixed_L0_L2_idleSlope_bps"],)
        if got!=expected_rates[row["egress_class"]]:
            raise ValueError(f"Compact reservation values differ from audited source: {row['egress_class']} {got}")
    write_csv(OUT/"table_reservations_compact.csv",compact_reserves)
    (OUT/"table_reservations.tex").write_text(reservation_compact_tex(compact_reserves),encoding="utf-8")

    captions=r"""% Article-ready captions; editorial labels C0--C3, historical IDs remain in the data/manifest.
\newcommand{\figCameraCaption}{\caption{Image delivery and image-completion latency for F02 and F05 under C0 (SP) and C1 (source pre-shaping), across L0--L3. All panels use A1 and 30 runs per treatment--load combination. Small points are individual runs; the larger treatment-matched marker is the across-run median; bars show the interquartile range (IQR), not a confidence interval. Panels (a,c) show complete images divided by images offered. Panels (b,d) show the p99 image-completion latency computed separately per run among complete images only. Dashed lines mark the 10-ms deadline for F02 and 30-ms deadline for F05. The annotations give the C0/L3/A1 median completion fraction per run (F02: 2.39\%; F05: 17.57\%). Lower survivor-only p99 values under C0 do not imply better delivery. Observed completion is not a deterministic guarantee.}}
\newcommand{\figCriticalCaption}{\caption{Critical-flow latency in A0 for L0--L2. In each execution, panel (a) plots the maximum of the individual flow-level p99 values for F06 and F07; panel (b) plots the maximum of the individual flow-level p99 values for F08--F10. This is a maximum across per-flow p99s within an execution, not a maximum packet latency or a p99 of a pooled population. Small points are individual executions; the larger treatment-matched marker is the across-run median; bars show IQR, not a confidence interval. The dashed line marks the 100-\textmu s deadline. C0--C2 have 30 executions per cell; labels n=30, n=21, and n=3 denote C3 coverage. C3--C2 compares full policies: CBS reservations and their cross-load rule, synchronization, and TAS differ, so the contrast does not isolate TAS. The p99 display does not establish hard-deadline compliance; the maximum observed C3 brake latency in the cutoff is 78.461~\textmu s. Sampled synchronization approval does not demonstrate continuous-time conformance.}}
"""
    (OUT/"figure_captions.tex").write_text(captions,encoding="utf-8")
    includes=r"""% Example inclusions; adjust relative paths to the paper's figure directory.
\input{figure_captions.tex}
\begin{figure*}[t]
  \centering
  \includegraphics[width=\textwidth]{fig_camera_delivery_latency.pdf}
  \figCameraCaption
\end{figure*}

\begin{figure*}[t]
  \centering
  \includegraphics[width=\textwidth]{fig_critical_latency.pdf}
  \figCriticalCaption
\end{figure*}

% table_viability.tex and table_reservations.tex (compact reservations) are standalone environments.
"""
    (OUT/"figure_includes.tex").write_text(includes,encoding="utf-8")

    # Check image-figure groups and critical-flow coverage.
    fig1_groups={(r["article_treatment"],r["flow"],r["load"]) for r in cam if r["alignment"]=="A1"}
    if len(fig1_groups)!=16 or any(sum(1 for r in cam if r["article_treatment"]==t and r["flow"]==fid and r["load"]==l and r["alignment"]=="A1")!=30 for t in ("C0","C1") for fid in ("F02","F05") for l in LOADS):
        raise ValueError("Unexpected camera group size")
    if sum(1 for r in critical if r["article_treatment"]=="C3" and r["load"]=="L0")!=30*5:
        raise ValueError("Unexpected C3 L0/A0 critical-flow coverage")

    cutoff=manifest["analysis_cutoff"]
    included=[]
    for hist,summary in data["treatment_summary"].items():
        for r in summary["runs"]:
            included.append({"execution_id":r["execution_id"],"article_treatment":HISTORY_TO_ARTICLE[hist],"historical_treatment":hist,
                "load":r["load"],"alignment":r["alignment"],"seed":r["seed"],"report_sha256":r["report_sha256"],
                "calendar_signature":r["calendar_signature"]})
    history_dir=OUT/"revision_history/pre_presentation_adjustments"
    preserved_prior=[]
    if history_dir.is_dir():
        for prior in sorted(history_dir.iterdir()):
            if prior.is_file():
                preserved_prior.append({"path":str(prior.relative_to(OUT)),"bytes":prior.stat().st_size,"sha256":sha256(prior)})
    out_manifest={
        "generated_at_local":__import__("datetime").datetime.now().astimezone().isoformat(timespec="seconds"),
        "frozen_cutoff":cutoff,"frozen_source_directory":str(SOURCE.relative_to(ROOT)),
        "source_analysis_manifest_sha256":sha256(SOURCE/"analysis_manifest.json"),
        "source_results_summary_sha256":sha256(SOURCE/"results_summary.json"),
        "source_coverage_sha256":sha256(SOURCE/"coverage_editorial.csv"),
        "source_reservation_profiles_sha256":sha256(SOURCE/"reservation_profiles.csv"),
        "source_c4_cutoff_sha256":sha256(SOURCE/"c4_cutoff.json"),
        "article_to_historical_mapping":ARTICLE_TO_HISTORY,
        "included_run_counts_by_article_treatment":actual,
        "included_run_ids":included,
        "frozen_c4_run_id_and_report_hash_match":True,
        "unique_execution_ids":len(set(all_ids)),
        "exclusions":{"post_cutoff_results":"all excluded by using only frozen synthesis result_summary.json","technical_invalid_attempts":"not included as execution results; source cutoff excludes C4_L1_A0_seed1022"},
        "fig1_filters":{"treatments":["C0","C1"],"flows":["F02","F05"],"alignment":"A1 for all panels; L0/A0 also retained in fig1_camera_runs.csv","loads":LOADS,"n_per_treatment_load_group":30,"statistics":{"completion":"per-run complete/offered images; graph annotations use the median run fraction","image_p99":"computed per run among complete images only; no pooling across runs","group_summary":"median and interquartile range across runs; IQR is not a confidence interval"},"deadlines_ms":{"F02":10,"F05":30},"C0_L3_A1_completion_audit":camera_low_group},
        "fig2_filters":{"treatments":TREATMENTS,"flows":{"radar":["F06","F07"],"brakes":["F08","F09","F10"]},"alignment":"A0","loads":["L0","L1","L2"],"per_run_statistic":"maximum of individual flow-level p99s within one execution; neither maximum latency nor pooled p99","group_summary":"median and interquartile range across runs; IQR is not a confidence interval","deadline_us":100,"C3_partial_n_labels":True},
        "C3_brake_latency_audit":{"largest_observed_latency_us":max_brake_record["max_latency_us"],"execution":max_brake_record,"retained_low_points_seed_1006_1010":brake_low_points},
        "paired_viability":{"common_pairs":len(pairs),"summary_by_load":pair_summary,"calendar_and_F21_F22_population_checked_per_pair":True},
        "reservation_note":"idleSlope values are configured per-egress/per-class CBS reservations, not measured utilization; totals and 75% headroom refer to an individual egress port only.",
        "synchronization_note":"Approval applies to available samples only; continuous-time synchronization conformance was not demonstrated.",
        "prior_small_file_versions_preserved_in":"revision_history/pre_presentation_adjustments/",
        "prior_small_file_versions":preserved_prior,
        "regeneration":"/home/jonatan/omnetpp/.venv/bin/python3 simulations/analysis/icit2027_publication_assets_2026-10-27/generate_assets.py",
    }
    (OUT/"analysis_manifest.json").write_text(json.dumps(out_manifest,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")

    readme=f"""# ICIT results figures and tables

This package is derived only from `{SOURCE.relative_to(ROOT)}` at the frozen cutoff **{cutoff}**. `generate_assets.py` reads audited derived data, validates the cutoff and treatment IDs, and writes publication assets. It does not invoke simulations or read live campaign outputs.

## Editorial labels and frozen coverage

| Article label | Historical campaign ID |
|---|---|
| C0 — SP | C0 |
| C1 — Source pre-shaping | C1 |
| C2 — Calibrated CBS | C3 |
| C3 — Joint CBS/TAS | C4 |

Included counts: C0 = 240, C1 = 240, C2 = 180, and C3 = 90. The 90 article-C3 execution IDs and report hashes match `c4_cutoff.json` exactly. Later campaign rows are excluded; the technical-invalid attempt `C4_L1_A0_seed1022` is not an included result. No execution IDs are duplicated.

`table_viability.tex` reports approved/completed runs. Every admissible cell targets 30 repetitions; `†` marks `n<30`. `R` and `S` denote pre-simulation rejection by the reservation and service screens, respectively. Neither symbol means a failed simulation. A pass describes the observed runs, not deterministic or hard-real-time assurance.

The common C2/C3 subset contains {len(pairs)} pairs: {pair_summary[0]['C2_fail_C3_pass']}/60 C2-fail/C3-pass at L0; {pair_summary[1]['C2_fail_C3_pass']}/24 at L1; and {pair_summary[2]['both_pass']}/6 both-pass at L2. All pairs match calendar signatures and offered F21/F22 populations. The per-pair evidence is in `paired_viability.csv`.

## Figures and statistics

- **Camera figure:** C0/C1, F02/F05, A1, L0--L3; 30 runs in every treatment/load combination. Small points are individual runs. The larger, treatment-matched symbol is the median across runs; bars are IQR (25th--75th percentile), not confidence intervals. Completion is calculated per run as complete images/offered images. The F02 and F05 callouts show the median per-run completion: **{camera_low_group['F02']['median_percent']:.2f}%** and **{camera_low_group['F05']['median_percent']:.2f}%**. Aggregated over runs, the corresponding completion fractions are **{camera_low_group['F02']['aggregate_percent']:.2f}%** and **{camera_low_group['F05']['aggregate_percent']:.2f}%**; these aggregate values are separately preserved in `fig1_camera_summary.csv`. The image p99 is calculated separately per run among complete images only. Dashed lines mark the F02 10-ms and F05 30-ms deadlines. C0's lower survivor-only p99 does not mean better image delivery.
- **Critical-flow figure:** A0, L0--L2. Panel (a) is the per-execution maximum of the flow-level p99 values for F06/F07; panel (b) is the per-execution maximum of the flow-level p99 values for F08--F10. It is neither a packet maximum nor a pooled-population p99. Each small point is one run; treatment-matched larger markers are medians and bars are IQR. Dashed line: 100 µs. C0--C2 have n=30 per plotted cell; C3 counts (30, 21, 3 across L0--L2) are labelled at each group. All observations are retained, including the low brake points: in C3/A0, seed 1006 has a 28.385 µs maximum across brake-flow p99s and seed 1010 has 7.212 µs in both L0 and L1. These agree with the prior consolidation; no cause is inferred. The largest observed brake latency across all 90 C3 runs is **{max_brake_record['max_latency_us']:.6f} µs** ({max_brake_record['execution_id']}, {max_brake_record['flow']}). A p99 plot alone does not establish hard-deadline compliance.
- `paired_C3_minus_C2_latency.csv` reports, separately, flow-level p99s, observed maxima, their paired differences, and approval. C2--C3 is a full-policy contrast: reservations, the cross-load reservation rule, synchronization, and TAS differ; it does not isolate TAS.
- `table_reservations.csv` retains the complete 24-row selected-port data with exact rates and per-port context. `table_reservations_compact.csv` and `table_reservations.tex` give the requested four-row summary. `idleSlope` is a configured rate per egress/class, not measured utilization. Port totals and headroom apply to one egress only and must not be summed across hops as link use.

## Verified camera aggregates and synchronization

The source values reproduce C0/L3/A1 F02 **219,747 packet losses** and **219,565 incomplete images**, and F05 **360,145 packet losses** and **186,094 incomplete images**. C1 has zero packet losses and zero incomplete images in those cohorts. The C0 L3/A1 annotation uses median run completeness, not the pooled aggregate.

Synchronization was approved on the available samples; continuous-time synchronization conformance was not demonstrated. No plot combines packet/image samples across seeds to create a pooled p99. The simulation is the experimental unit.

## Files and regeneration

- `fig_camera_delivery_latency.{{pdf,svg,png}}` and `fig_critical_latency.{{pdf,svg,png}}` (vector PDF/SVG; 400-dpi PNG review copies; 7.0-in canvas width, with tight PDF bounds checked against the IEEE two-column width).
- `table_viability.csv/.tex`, `paired_viability.csv`, `paired_viability_summary_by_load.csv`.
- `fig1_camera_runs.csv`, `fig1_camera_summary.csv`, `fig2_critical_latency_runs.csv`.
- `paired_C3_minus_C2_latency.csv`, `paired_C3_minus_C2_latency_summary.csv`.
- Complete `table_reservations.csv`; compact `table_reservations_compact.csv`; compact `table_reservations.tex`.
- `figure_captions.tex`, `figure_includes.tex`, `analysis_manifest.json`, and `generate_assets.py`.
- Pre-revision copies of the small edited files are retained under `revision_history/pre_presentation_adjustments/`; no raw simulation data were duplicated.

To regenerate with the project's virtual environment:

```bash
MPLCONFIGDIR=/tmp/mpl-icit-publication /home/jonatan/omnetpp/.venv/bin/python3 simulations/analysis/icit2027_publication_assets_2026-10-27/generate_assets.py
```
"""
    (OUT/"README.md").write_text(readme,encoding="utf-8")

    # Record file inventory and rendering sizes after all deliverables are written.
    inventory=[]
    for p in sorted(OUT.iterdir()):
        if p.is_file() and p.name != "analysis_manifest.json":
            inventory.append({"path":p.name,"bytes":p.stat().st_size,"sha256":sha256(p)})
    out_manifest["generated_artifacts"]=inventory
    (OUT/"analysis_manifest.json").write_text(json.dumps(out_manifest,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(json.dumps({"out":str(OUT),"cutoff":cutoff,"runs":actual,"paired":pair_summary,
        "camera_aggregates":{"F02_C0_L3_A1_lost_packets":219747,"F02_C0_L3_A1_incomplete_images":219565,
        "F05_C0_L3_A1_lost_packets":360145,"F05_C0_L3_A1_incomplete_images":186094},
        "artifacts":len(inventory)},indent=2))


if __name__=="__main__":
    main()
