#!/usr/bin/env python3
"""Run the preregistered bounded exploratory CBS search for the PCP variant."""
import argparse,csv,json,os,re,shutil,subprocess,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent; ROOT=HERE.parents[2]; SIM=ROOT/"simulations"
sys.path.insert(0,str(HERE));sys.path.insert(0,str(ROOT/"scripts/catalog"))
import run_pilot as pilot
from generate_cbs import capacity_bps
route=pilot.checker.route

def loadj(p): return json.loads(Path(p).read_text())
def rows(p):
    with Path(p).open(newline="") as f:return list(csv.DictReader(f))
def writej(p,v): Path(p).write_text(json.dumps(v,indent=2,sort_keys=True)+"\n")
def profile_rows(profile,template):
    totals={}
    for (e,_),bps in profile.items():totals[e]=totals.get(e,0)+bps
    result=[]
    for (e,tc),bps in sorted(profile.items()):
        row=dict(template[e,tc]);row["idle_slope_bps"]=bps;row["idle_slope_mbps"]=bps/1e6
        cap=int(row["port_rate_bps"]);row["total_port_reservation_bps"]=totals[e]
        row["cap_fraction"]=totals[e]/cap;row["headroom_to_75pct_bps"]=int(.75*cap)-totals[e]
        result.append(row)
    return result
def require(x,m):
    if not x: raise RuntimeError(m)

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--inet-root",default=os.environ.get("INET_ROOT"));ap.add_argument("--omnetpp-root",default=os.environ.get("OMNETPP_ROOT"));a=ap.parse_args()
    inet=Path(a.inet_root).resolve();opp=Path(a.omnetpp_root).resolve() if a.omnetpp_root else Path(shutil.which("opp_run")).resolve().parent.parent
    env=os.environ.copy();env["LD_LIBRARY_PATH"]=str(opp/"lib")+":"+str(inet/"src")+":"+env.get("LD_LIBRARY_PATH","")
    nominal={ (r["egress"],int(r["tc"])):int(r["idle_slope_bps"]) for r in rows(HERE/"configs/cbs_variant_nominal.csv") }
    meta={(r["egress"],int(r["tc"])):r for r in rows(HERE/"configs/cbs_variant_nominal.csv")}
    original=loadj(HERE/"results/seed41/C2_original.json")
    variant=loadj(HERE/"results/seed41/C2_variant_nominal.json")
    history=[{"candidate":"nominal_variant","status":"executed","profile_source":"configs/cbs_variant_nominal.csv","viable":variant["viable"],"summary_file":"results/seed41/C2_variant_nominal.json"}]
    best=variant; best_rates=dict(nominal); found=bool(variant["viable"]); selected="nominal_variant" if found else None
    cap=.75; budget=24; reduction_budget=12
    if not found:
        failed={fid for fid,f in variant["qos"].items() if any(rx["viable"] is False for rx in f["receivers"].values())}
        vflows={r["flow_id"]:r for r in rows(HERE/"catalog/flows_variant.csv")}
        qwait={(q["queue"],q["tc"]):(q.get("max_s") or 0,q.get("mean_s") or 0) for q in variant["queueing_time"]}
        # Prespecified ranking: measured max wait, mean wait, then source-to-destination route order.
        coordinates=[]
        failing_sorted=sorted(failed)
        for fid in failing_sorted:
            f=vflows[fid];tc=int(f["traffic_class"])
            if tc not in (4,6):continue
            ordered=[]
            for dest in f["destinations"].split(";"):
                for e in route(f["source"],dest):
                    e=e.removeprefix("ZonalIVN.");key=(e,tc)
                    if key in nominal and key not in ordered:ordered.append(key)
            coordinates.extend((key,fid,rank) for rank,key in enumerate(ordered))
        coordinates=sorted(set(coordinates),key=lambda x:(-qwait.get((f"ZonalIVN.{x[0][0]}.macLayer.queue.queue[{x[0][1]}]",x[0][1]),(0,0))[0],
                                                          -qwait.get((f"ZonalIVN.{x[0][0]}.macLayer.queue.queue[{x[0][1]}]",x[0][1]),(0,0))[1],
                                                          x[2],x[0][0],x[1]))
        tried=set();profiles=[]
        current=dict(nominal)
        def emit_candidate(number,new,phase,targets):
            nonlocal current,best,found,selected
            total={}
            for (e,tc),bps in new.items():total[e]=total.get(e,0)+bps
            bad=[e for e,n in total.items() if n>cap*capacity_bps(e)]
            entry={"candidate":f"candidate_{number:02d}","phase":phase,"targets":[{"egress":e,"tc":tc} for e,tc in targets],
                   "profile_bps":{f"{e}/TC{tc}":bps for (e,tc),bps in sorted(new.items())},
                   "port_totals_bps":total,"status":"rejected_before_execution" if bad else "pending_execution",
                   "rejection_reason":("75% aggregate reservation ceiling exceeded: "+", ".join(bad)) if bad else None}
            if bad:
                history.append(entry);return False
            if new==current:
                entry["status"]="rejected_before_execution";entry["rejection_reason"]="duplicate/no positive increment";history.append(entry);return False
            number_label=f"candidate_{number:02d}";config=f"PilotC2Candidate{number:02d}"
            root=HERE/f"{number_label}.ini";csvpath=HERE/f"configs/{number_label}.csv"
            ini=["include pilot-variant.ini","",f"[Config {config}]","extends = PilotC2Variant",f"result-dir = results/seed41/{number_label}","seed-set = 41"]
            prof=profile_rows(new,meta)
            for (e,tc),bps in sorted(new.items()):
                mod=f"*.{e}.macLayer.queue.transmissionSelectionAlgorithm[{tc}]"
                ini.append(f"{mod}.idleSlope = {bps}bps")
            root.write_text("\n".join(ini)+"\n")
            with csvpath.open("w",newline="") as f:
                w=csv.DictWriter(f,fieldnames=prof[0].keys(),lineterminator="\n");w.writeheader();w.writerows(prof)
            entry["status"]="executed";entry["config_file"]=root.name;entry["profile_file"]=str(csvpath.relative_to(HERE))
            report,sig=pilot.run_cell(number_label,config,"variant","C2",41,root,inet,env,csvpath,variant["f21_f22_calendar_sha256"])
            entry["summary_file"]=str((HERE/f"results/seed41/{number_label}.json").relative_to(HERE));entry["viable"]=bool(report["viable"])
            entry["failed_flows_after_run"]=[fid for fid,ff in report["qos"].items() if any(rx["viable"] is False for rx in ff["receivers"].values())]
            history.append(entry);profiles.append((entry,new,report))
            current=dict(new)
            if report["viable"]:found=True;selected=number_label;best=report;best_rates=dict(new)
            return True
        # Candidates 1-12: measured-wait ordered, deterministic coordinate increases, <=10% per port.
        n=1
        while n<=12:
            latest=profiles[-1][2] if profiles else variant
            failed_now={fid for fid,f in latest["qos"].items() if any(rx["viable"] is False for rx in f["receivers"].values())}
            waits={(q["queue"],int(q["tc"])):(q.get("max_s") or 0,q.get("mean_s") or 0) for q in latest["queueing_time"]}
            eligible=[item for item in coordinates if item[1] in failed_now and item[0] not in tried]
            eligible.sort(key=lambda x:(-waits.get((f"ZonalIVN.{x[0][0]}.macLayer.queue.queue[{x[0][1]}]",x[0][1]),(0,0))[0],
                                       -waits.get((f"ZonalIVN.{x[0][0]}.macLayer.queue.queue[{x[0][1]}]",x[0][1]),(0,0))[1],
                                       x[2],x[0][0],x[1]))
            if not eligible:break
            key,fid,rank=eligible[0]
            if n>12:break
            tried.add(key);room=int(cap*capacity_bps(key[0]))-sum(v for (e,_),v in current.items() if e==key[0])
            if room<=0:
                history.append({"candidate":f"candidate_{n:02d}","status":"rejected_before_execution","phase":"coordinate","targets":[{"egress":key[0],"tc":key[1]}],"rejection_reason":"no headroom under 75% cap"});n+=1;continue
            nxt=dict(current);nxt[key]+=min(round(.10*capacity_bps(key[0])),room)
            emit_candidate(n,nxt,"coordinate",[key]);
            if found:break
            n+=1
        if n<13:n=13
        # Candidates 13-18: coupled path increments for currently failed flows.
        while not found and 13<=n<=18:
            latest=profiles[-1][2] if profiles else variant
            failed_now={fid for fid,f in latest["qos"].items() if any(rx["viable"] is False for rx in f["receivers"].values())}
            flow_order=sorted(failed_now,key=lambda fid:(-(latest["qos"][fid]["receivers"][next(iter(latest["qos"][fid]["receivers"]))].get("deadline_miss_ratio_including_loss",0)),fid))
            if not flow_order:break
            fid=flow_order[(n-13)%len(flow_order)];f=vflows[fid];tc=int(f["traffic_class"]);path=[]
            for dest in f["destinations"].split(";"):
                for e in route(f["source"],dest):
                    key=(e.removeprefix("ZonalIVN."),tc)
                    if key in nominal and key not in path:path.append(key)
            nxt=dict(current);targets=[];blocked=False
            for key in path:
                room=int(cap*capacity_bps(key[0]))-sum(v for (e,_),v in nxt.items() if e==key[0])
                if room<=0:blocked=True;break
                nxt[key]+=min(round(.10*capacity_bps(key[0])),room);targets.append(key)
            if blocked or not targets:
                history.append({"candidate":f"candidate_{n:02d}","status":"rejected_before_execution","phase":"coupled_path","target_flow":fid,"rejection_reason":"75% cap leaves no positive increment on full path"});n+=1;continue
            emit_candidate(n,nxt,"coupled_path",targets);n+=1
            if found:break
        # Candidates 19-24: backtrack the best nonviable executed profile by 2% steps.
        while not found and 19<=n<=24 and profiles:
            eligible=[p for p in profiles if not p[2]["viable"]]
            if not eligible:break
            def score(item):
                report=item[2];miss=sum((rx.get("image_completion") or {}).get("deadline_miss_ratio_including_missing_images",rx.get("deadline_miss_ratio_including_loss",0)) or 0 for f in report["qos"].values() for rx in f["receivers"].values())
                drops=report["drops_entire_run"];wait=max((q.get("max_s") or 0 for q in report["queueing_time"]),default=0)
                hard=sum(1 for f in report["qos"].values() if f["criticality"].endswith("hard") for rx in f["receivers"].values() if rx["viable"] is False)
                return hard,miss,drops,wait,int(item[0]["candidate"].rsplit("_",1)[1])
            parent=sorted(eligible,key=score)[0];parent_rates=parent[1];new=dict(parent_rates)
            adjustable=sorted((k for k in new if new[k]>nominal[k]),key=lambda k:(-(new[k]-nominal[k]),-qwait.get((f"ZonalIVN.{k[0]}.macLayer.queue.queue[{k[1]}]",k[1]),(0,0))[0],k))
            if not adjustable:break
            key=adjustable[(n-19)%len(adjustable)];new[key]=max(nominal[key],new[key]-round(.02*capacity_bps(key[0])))
            emit_candidate(n,new,"backtrack",[key]);n+=1
            if found:break
    # If viable, perform up to 12 strict 2% reductions from the selected profile.
    reductions=[]
    if found and selected!="nominal_variant":
        current=dict(best_rates)
        for ix in range(1,reduction_budget+1):
            adjustable=sorted((k for k in current if current[k]>nominal[k]),key=lambda k:(-(current[k]-nominal[k]),-qwait.get((f"ZonalIVN.{k[0]}.macLayer.queue.queue[{k[1]}]",k[1]),(0,0))[0],k))
            if not adjustable:break
            key=adjustable[(ix-1)%len(adjustable)];new=dict(current);new[key]=max(nominal[key],new[key]-round(.02*capacity_bps(key[0])))
            # Reuse the exact candidate runner; reduction candidate numbering is disjoint from viability candidates.
            config=f"PilotC2Reduction{ix:02d}";label=f"reduction_{ix:02d}";root=HERE/f"{label}.ini";csvpath=HERE/f"configs/{label}.csv"
            ini=["include pilot-variant.ini","",f"[Config {config}]","extends = PilotC2Variant",f"result-dir = results/seed41/{label}","seed-set = 41"]
            prof=profile_rows(new,meta)
            for (e,tc),bps in sorted(new.items()):
                ini.append(f"*.{e}.macLayer.queue.transmissionSelectionAlgorithm[{tc}].idleSlope = {bps}bps")
            root.write_text("\n".join(ini)+"\n")
            with csvpath.open("w",newline="") as f:
                w=csv.DictWriter(f,fieldnames=prof[0].keys(),lineterminator="\n");w.writeheader();w.writerows(prof)
            report,_=pilot.run_cell(label,config,"variant","C2",41,root,inet,env,csvpath,variant["f21_f22_calendar_sha256"])
            reduction={"candidate":label,"status":"executed","targets":[{"egress":key[0],"tc":key[1]}],"viable":report["viable"],"profile_file":str(csvpath.relative_to(HERE))}
            reductions.append(reduction)
            if report["viable"]:current=new;best_rates=new;best=report;selected=label
    robustness=[]
    if found:
        fixed_rates_csv=(HERE/"configs/cbs_variant_nominal.csv" if selected=="nominal_variant" else HERE/f"configs/{selected}.csv")
        for seed in (43,47):
            nominal_config=f"PilotC2VariantSeed{seed}"
            nominal_report,seed_signature=pilot.run_cell(f"C2_variant_nominal_seed{seed}",nominal_config,"variant","C2",seed,
                HERE/"pilot-variant.ini",inet,env,HERE/"configs/cbs_variant_nominal.csv",None)
            fixed_config=f"PilotC2RobustCandidate{seed}";fixed_label=f"fixed_candidate_seed{seed}"
            fixed_ini=HERE/f"{fixed_label}.ini"
            prof=profile_rows(best_rates,meta);ini=["include pilot-variant.ini","",f"[Config {fixed_config}]","extends = PilotC2Variant",f"result-dir = results/seed{seed}/{fixed_label}",f"seed-set = {seed}"]
            for r in rows(fixed_rates_csv):
                e=r["egress"];tc=int(r["tc"]);bps=int(r["idle_slope_bps"])
                ini.append(f"*.{e}.macLayer.queue.transmissionSelectionAlgorithm[{tc}].idleSlope = {bps}bps")
            fixed_ini.write_text("\n".join(ini)+"\n")
            fixed_report,_=pilot.run_cell(fixed_label,fixed_config,"variant","C2",seed,fixed_ini,inet,env,
                fixed_rates_csv,seed_signature)
            robustness.append({"seed":seed,"calendar_sha256":seed_signature,"nominal":nominal_report,
                               "fixed_candidate":fixed_report,"fixed_candidate_viable":fixed_report["viable"]})
    result={"exploratory":True,"official_profile_frozen":False,"calibration_found_feasible_candidate":found,
            "selected_seed41_profile":selected,"failure_wording":None if found else "nenhum candidato viável encontrado pela busca exploratória definida",
            "search_limits":{"max_new_viability_candidates":24,"max_reductions_if_viable":12,"cap_fraction":.75,"coarse_fraction_max":.10,"fine_fraction":.02,"never_below_nominal":True},
            "search_history":history,"reductions":reductions,"selected_profile_bps":{f"{e}/TC{tc}":v for (e,tc),v in sorted(best_rates.items())},
            "original_mapping_control":{"viable":original["viable"],"summary_file":"results/seed41/C2_original.json"},
            "variant_nominal":{"viable":variant["viable"],"summary_file":"results/seed41/C2_variant_nominal.json"},
            "robustness_seeds_43_47":robustness}
    writej(HERE/"results/calibration_search.json",result)
    writej(HERE/"results/candidate_history.json",{"search_history":history,"reductions":reductions})
    print("Calibration search finished:",result["failure_wording"] or f"found viable profile {selected}",flush=True)

if __name__=="__main__":main()
