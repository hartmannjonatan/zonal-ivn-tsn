#!/usr/bin/env python3
"""Reconcile catalog rates, losses, and natural F13 episodes from preserved pilots.

Reads preserved artifacts only. Writes compact outputs under this isolated study.
"""
from __future__ import annotations
import csv, hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PILOT = ROOT / "simulations/pilot/c4_joint_dimensioning"
CORRECTED = ROOT / "simulations/pilot/c4_real_clock_service_margin_corrected"
HERE = Path(__file__).resolve().parent
FLOWS = ROOT / "simulations/zonal/traffic/flows.csv"
RESERVATIONS = ROOT / "simulations/zonal/traffic/cbs_nominal_reservations.csv"
FACTORS = {"L0": 0.5, "L1": 1.0, "L2": 2.5, "L3": 4.0}

def sha(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""): h.update(chunk)
    return h.hexdigest()

def load_csv(path):
    with path.open(newline="") as f: return list(csv.DictReader(f))

def main():
    flows={r["flow_id"]:r for r in load_csv(FLOWS)}
    routes=[]
    for row in load_csv(RESERVATIONS):
        if row["load"]!="L2": continue
        ids=[x for x in row["permanent_flows"].split(";") if x]
        frows=[]
        for fid in ids:
            f=flows[fid]
            factor=FACTORS["L2"] if int(f["scalable"]) else 1.0
            period_us=float(f["period_us"])/factor
            ppc=int(f["packets_per_cycle"])
            rate=lambda field: int(f[field])*8*ppc/(period_us*1e-6)
            frows.append({"flow":fid,"effective_period_us":period_us,"payload_bps":rate("app_bytes"),
                          "queue_mac_bps":rate("mac_bytes"),"wire_bps":rate("wire_bytes")})
        routes.append({"egress":row["egress"],"tc":int(row["traffic_class"]),"permanent_flows":ids,
                       "catalog_idleSlope_bps":int(row["idle_slope_bps"]),"flows":frows,
                       "total_payload_bps":sum(x["payload_bps"] for x in frows),
                       "total_queue_mac_bps":sum(x["queue_mac_bps"] for x in frows),
                       "total_wire_bps":sum(x["wire_bps"] for x in frows)})
    load_factors=[]
    for fid,f in flows.items():
        factor=FACTORS["L2"] if int(f["scalable"]) else 1.0
        period=float(f["period_us"])/factor if float(f["period_us"]) else None
        ppc=int(f["packets_per_cycle"])
        calc=({label:int(f[key])*8*ppc/(period*1e-6) for label,key in
              [("payload","app_bytes"),("queue_mac","mac_bytes"),("wire","wire_bytes")]} if period else None)
        load_factors.append({"flow":fid,"source":f["source"],"destinations":f["destinations"],"path":f["path"],
          "pcp":int(f["pcp"]),"tc":int(f["traffic_class"]),"scalable":bool(int(f["scalable"])),
          "base_period_us":float(f["period_us"]),"effective_L2_period_us":period,
          "app_bytes":int(f["app_bytes"]),"ip_bytes":int(f["ip_bytes"]),"mac_bytes":int(f["mac_bytes"]),
          "wire_bytes":int(f["wire_bytes"]),"payload_rate_bps":calc["payload"] if calc else None,
          "queue_mac_rate_bps":calc["queue_mac"] if calc else None,"wire_rate_bps":calc["wire"] if calc else None,
          "catalog_base_wire_rate_bps":float(f["wire_rate_mbps"])*1e6 if f["wire_rate_mbps"] else None,
          "expected_L2_wire_rate_bps":calc["wire"] if calc else None,
          "rate_source":"periodic catalog" if period else "event calendar; no periodic rate"})
    D=json.load((PILOT/"results/pilot_results.json").open())
    runs=[]
    for r in D["runs"]:
        flowmap={x["flow"]:x for x in r["flow_metrics"]}
        drops=r.get("queue_overflow_drops_by_queue",[])
        runs.append({"variant":r["variant"],"cell":r["cell"],"seed":r["seed"],
          "simulation_valid":r["simulation_valid"],"application_viable":r["application_viable"],
          "stability_viable":r["stability_viable"],"calendar_sha256":r["calendar_sha256"],
          "source_result":r.get("source_result"),"effective_profile_bps":r.get("effective_profile_bps"),
          "flows":{fid:{"offered_packets":m["offered_packets"],"received_packets":m["received_packets"],
                         "lost_packets":m["offered_packets"]-m["received_packets"],
                         "packet_loss_ratio":m["packet_loss_ratio"],"deadline_misses_received":m["deadline_misses_received"],
                         "deadline_miss_ratio_including_loss":m["deadline_miss_ratio_including_loss"],
                         "p99_s":m["p99_s"],"max_s":m["max_s"],"gate_viable":m["flow_gate_viable"]}
                   for fid,m in flowmap.items()},
          "drops_by_queue":drops,"recorded_drop_total":sum(int(x.get("overflow_drops",x.get("overflow_drops_post_warmup_including_drain",0))) for x in drops),
          "recorded_drop_reconciliation":r.get("drop_reconciliation"),"evidence_artifacts":r.get("evidence_artifacts")})
    episode=json.load((PILOT/"results/f13_natural_episode_analysis.json").open())
    # Keep only exact numeric summary fields and preserve the source object/hash for audit.
    episodes=episode
    old={}
    for run in runs:
        if run["variant"].startswith("D") or run["variant"] in ("B_local","C3_sync_control"):
            old[run["variant"]]={"F13":run["flows"].get("F13"),"F21":run["flows"].get("F21"),"F22":run["flows"].get("F22"),
              "drop_reconciliation":run["recorded_drop_reconciliation"]}
    out={"schema_version":"1.0","exploratory":True,"official_c4_frozen":False,
      "source_files":{str(p.relative_to(ROOT)):sha(p) for p in [FLOWS,RESERVATIONS,PILOT/"results/pilot_results.json",PILOT/"results/f13_natural_episode_analysis.json"]},
      "load_factor_L2":2.5,"rate_semantics":{"payload":"app_bytes × 8 / effective period","queue_mac":"mac_bytes × 8 / effective period; queue packet length in INET is MAC frame data length","wire":"wire_bytes × 8 / effective period, including catalog wire overhead; not queue occupancy"},
      "flow_rates_L2":load_factors,"permanent_egress_rates_L2":routes,"runs":runs,
      "f13_episode_analysis_preserved":episodes,"f13_drop_and_loss_summaries":old,
      "correction_findings":{"dimensioning_script_bug":"dimension_candidates.py computed queue rate using catalog base period without dividing by TrafficPlan factor for scalable flows; for L2, F13 was 10.24 Mb/s instead of 25.60 Mb/s.",
        "F13_D3_TAS_loss":"2,086 / 375,000 measurement packets absent; the independent queue-overflow counter assigns all 2,086 to CSW.eth[3]/TC4; this remains an application-gate result per its existing tolerance, not zero loss.",
        "scope_note":"F13 local Z3 queue episode recovery is conditional on packets that actually arrived. Upstream CSW.eth[3] drops reduce local arrival demand and do not establish service for the full offered population."}}
    outpath=HERE/"audit_corrected_inputs.json"
    outpath.write_text(json.dumps(out,indent=2,sort_keys=True)+"\n")
    print(json.dumps({"output":str(outpath.relative_to(ROOT)),"flow_count":len(load_factors),"permanent_egress_count":len(routes),
      "F13_L2":next(x for x in load_factors if x['flow']=='F13'),"runs":len(runs),"bytes":outpath.stat().st_size},indent=2))
if __name__=="__main__": main()
