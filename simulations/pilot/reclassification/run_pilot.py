#!/usr/bin/env python3
"""Run the isolated PCP/TC pilot and retain compact, auditable evidence."""
import argparse, csv, hashlib, importlib.util, json, math, os, re, shutil, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SIM = ROOT / "simulations"
sys.path.insert(0, str(ROOT / "scripts/run"))
sys.path.insert(0, str(ROOT / "tests/validation/traffic"))
import validate_c0 as base
import check_traffic as checker

def load_csv(p):
    with Path(p).open(newline="") as f: return list(csv.DictReader(f))
def write_json(p, obj): Path(p).write_text(json.dumps(obj, indent=2, sort_keys=True)+"\n")
def sha(p):
    h=hashlib.sha256()
    with open(p,"rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()
def event_rows(path):
    return [{k:r[k] for k in ("flow","block","signature","start","duration","volume_bytes","volume_layer")}
            for r in load_csv(path)]
def event_signature(path):
    raw=json.dumps([{k:r[k] for k in ("flow","block","signature","start","duration","volume_bytes")}
                    for r in load_csv(path)],separators=(",",":"),sort_keys=False).encode()
    return hashlib.sha256(raw).hexdigest()

def setup_workspace(kind):
    ws=HERE/"workspace"/kind
    (ws/"zonal/traffic").mkdir(parents=True,exist_ok=True)
    (ws/"zonal/configs").mkdir(parents=True,exist_ok=True)
    shutil.copy2(HERE/f"catalog/flows_{kind}.csv",ws/"zonal/traffic/flows.csv")
    shutil.copy2(HERE/f"catalog/catalog_bindings_{kind}.ini",ws/"zonal/configs/catalog-bindings.ini")
    base.SIM=ws
    checker.DATA=HERE/"catalog"/kind
    checker.DATA.mkdir(parents=True,exist_ok=True)
    shutil.copy2(HERE/f"catalog/flows_{kind}.csv",checker.DATA/"flows.csv")
    shutil.copy2(HERE/"catalog/transients.csv",checker.DATA/"transients.csv")
    return ws

def extract_temporal(vec, run_dir, flows, tag):
    """Compact 1 ms association bins; no packet-level causal claims."""
    from array import array
    defs={}
    with vec.open(errors="replace") as f:
        for line in f:
            if line.startswith("vector "):
                p=line.rstrip().split(" ",4)
                if len(p)==5: defs[int(p[1])]=(p[2],p[3])
            elif line and line[0].isdigit(): break
    bindings=base.load_app_flow_map()
    sensor_ids={"F01","F06","F07"}
    sensor_vec={}
    for vid,(module,metric) in defs.items():
        m=re.fullmatch(r"(.*)\.app\[(\d+)\]",module)
        if metric=="latency:vector" and m and (m.group(1),int(m.group(2))) in bindings:
            fid=bindings[m.group(1),int(m.group(2))]
            node=m.group(1).removeprefix("ZonalIVN.")
            if fid in sensor_ids and node in flows[fid]["destinations"].split(";"): sensor_vec[vid]=(fid,node)
    selected=re.compile(r"ZonalIVN\.(?:HPC\.eth\[0\]|CSW\.eth\[0\]|Z[123]\.ZSW\.eth\[[01]\]|(?:LiDAR1|RADAR1|RADAR2|CAM[1-4])\.eth\[0\])\.macLayer\.queue\.queue\[(4|6)\]$")
    qvec={}
    for vid,(module,metric) in defs.items():
        if metric=="queueBitLength:vector" and selected.fullmatch(module): qvec[vid]=module
    bins={i:{"bin_start_s":1+i*.001,"F01_received":0,"F01_misses":0,"F01_miss_latency_max_us":None,
             "F06_received":0,"F06_misses":0,"F06_miss_latency_max_us":None,
             "F07_received":0,"F07_misses":0,"F07_miss_latency_max_us":None} for i in range(30000)}
    qseries={name:{"last":array("d",[0.0])*30000,"max":array("d",[0.0])*30000,
                   "seen":bytearray(30000)} for name in qvec.values()}
    scanned=0
    with vec.open(errors="replace") as f:
        for line in f:
            scanned+=1
            if scanned%5_000_000==0:print(f"[{tag}] temporal scan: {scanned:,} vector lines",flush=True)
            p=line.split()
            if len(p) not in (3,4) or not p[0].isdigit(): continue
            try: vid=int(p[0]); t=float(p[2] if len(p)==4 else p[1]); val=float(p[3] if len(p)==4 else p[2])
            except ValueError: continue
            if vid in sensor_vec:
                fid,node=sensor_vec[vid]; origin=t-val
                if 1 <= origin < 31 and t < 31.05:
                    ix=min(29999,max(0,int((origin-1)*1000))); b=bins[ix]
                    b[f"{fid}_received"]+=1
                    if val > float(flows[fid]["deadline_us"])/1e6:
                        b[f"{fid}_misses"]+=1
                        old=b[f"{fid}_miss_latency_max_us"]
                        b[f"{fid}_miss_latency_max_us"]=max(old or 0,val*1e6)
            if vid in qvec and 1 <= t < 31:
                ix=min(29999,max(0,int((t-1)*1000)))
                item=qseries[qvec[vid]];item["last"][ix]=val;item["max"][ix]=max(item["max"][ix],val);item["seen"][ix]=1
    events=load_csv(run_dir/"events.csv")
    transient=[(float(e["start"]),float(e["start"])+float(e["duration"]),e["flow"]) for e in events]
    camera_counts=[0]*30000;camera_flow_bins=[set() for _ in range(30000)]
    with (run_dir/"releases.csv").open(newline="") as stream:
        for r in csv.DictReader(stream):
            if r["flow"] in {"F02","F03","F04","F05"} and 1 <= float(r["time"]) < 31:
                ix=min(29999,max(0,int((float(r["time"])-1)*1000)))
                camera_counts[ix]+=1;camera_flow_bins[ix].add(r["flow"])
    for name,series in qseries.items():
        previous=0.0
        for i in range(30000):
            if series["seen"][i]:previous=series["last"][i]
            else:series["last"][i]=previous
    for i,b in bins.items():
        t=b["bin_start_s"]+.0005
        active=[fid for a,z,fid in transient if a<=t<z]
        b["F21_active"]=int("F21" in active); b["F22_active"]=int("F22" in active)
        b["camera_release_flows"]=";".join(sorted(camera_flow_bins[i]))
        b["camera_shaper_release_count"]=camera_counts[i]
        b["queue_samples_json"]=json.dumps({name:{"last_bits":series["last"][i],"max_bits":series["max"][i]}
                                             for name,series in qseries.items()},separators=(",",":"))
    dest=HERE/"temporal"/tag; dest.mkdir(parents=True,exist_ok=True)
    out=dest/"association_1ms.csv"
    with out.open("w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(next(iter(bins.values())).keys()),lineterminator="\n"); w.writeheader(); w.writerows(bins.values())
    return {"path":str(out.relative_to(HERE)),"sha256":sha(out),"resolution_s":.001,
            "interpretation":"temporal association only; no per-packet route identity/cause established",
            "sensor_latency_vectors":len(sensor_vec),"selected_queue_vectors":len(qvec),
            "sensor_misses_by_flow":{fid:sum(b[f"{fid}_misses"] for b in bins.values()) for fid in sensor_ids}}

def read_temporal_summary(path):
    p=Path(path);misses={f:0 for f in ("F01","F06","F07")};n=0;queues=0
    with p.open(newline="") as stream:
        for row in csv.DictReader(stream):
            n+=1
            for fid in misses:misses[fid]+=int(row[f"{fid}_misses"])
            if n==1:queues=len(json.loads(row["queue_samples_json"]))
    base.require(n==30000,f"{p}: temporal evidence has {n} rows, expected 30000")
    return {"path":str(p.relative_to(HERE)),"sha256":sha(p),"resolution_s":.001,
            "interpretation":"temporal association only; no per-packet route identity/cause established",
            "sensor_latency_vectors":3,"selected_queue_vectors":queues,"sensor_misses_by_flow":misses}

def check_profile(params, kind, rates_csv):
    rows=load_csv(rates_csv); expect={(f"ZonalIVN.{r['egress']}.macLayer.queue.transmissionSelectionAlgorithm[{r['tc']}]",int(r['idle_slope_bps'])) for r in rows}
    found={m for (m,n),v in params.items() if n=="typename" and "Ieee8021qCreditBasedShaper" in str(v)}
    want={m for m,_ in expect}
    if kind=="C2": base.require(found==want,f"CBS set mismatch: {found ^ want}")
    else: base.require(not found,f"Unexpected CBS algorithms in {kind}: {found}")
    for m,bps in expect:
        raw=params.get((m,"idleSlope"),""); got=round(float(re.fullmatch(r"\s*([0-9.eE+-]+)\s*(?:bps)?\s*",str(raw)).group(1)))
        base.require(got==bps,f"idleSlope mismatch {m}: {got} != {bps}")
    return len(expect)

def run_cell(label, config, kind, treatment, seed, ini, inet, env, rates_csv=None, expected_calendar=None):
    output=HERE/f"results/seed{seed}/{label}"; output.mkdir(parents=True,exist_ok=True)
    compact=HERE/f"results/seed{seed}/{label}.json"
    if compact.is_file():
        saved=json.loads(compact.read_text())
        sig=saved["f21_f22_calendar_sha256"]
        if expected_calendar is not None: base.require(sig==expected_calendar,f"{label}: saved F21/F22 calendar signature mismatch")
        print(f"[{label}] reusing compact audited result",flush=True)
        return saved,sig
    run_dir=output/f"{config}-0"
    log=output/f"{config}.log"
    complete=run_dir.is_dir() and all((run_dir/name).is_file() for name in
        ("run.csv","events.csv","releases.csv","wire.csv","queues.csv","drops.csv"))
    if run_dir.exists() and not complete:
        shutil.rmtree(run_dir)
        for p in list(output.glob(f"{config}-#*.vec"))+list(output.glob(f"{config}-#*.vci"))+list(output.glob(f"{config}-#*.sca")):
            p.unlink()
    cmd=[]
    if not complete:
        cmd=[str(ROOT/"src/zonal-ivn-tsn"),"-u","Cmdenv","-n",f".:{ROOT/'src'}:{ROOT/'tests'}:{inet/'src'}",
             "-f",str(ini.relative_to(SIM)),"-c",config,"--cmdenv-express-mode=true","--cmdenv-event-banners=false",
             "--**.app[*].latency.result-recording-modes=+vector","--**.app[*].imageCompletionLatency.result-recording-modes=+vector",
             "--**.queueLength.result-recording-modes=+vector","--**.queueBitLength.result-recording-modes=+vector",
             "--**.droppedPacketLengthsQueueOverflow.result-recording-modes=+vector","--**.queueingTime.result-recording-modes=+histogram",
             "--**.utilization.result-recording-modes=+histogram",f"--result-dir={output}"]
        with log.open("w") as f:
            proc=subprocess.Popen(cmd,cwd=SIM,env=env,stdout=f,stderr=subprocess.STDOUT)
            last=0
            while proc.poll() is None:
                time.sleep(30)
                if log.exists():
                    text=log.read_text(errors="replace")
                    m=re.findall(r"Event #(\d+) .+?t=([^ ]+)",text)
                    if m and len(m)!=last:
                        last=len(m); print(f"[{label}] {m[-1][0]} events, sim-time {m[-1][1]}",flush=True)
            if proc.returncode:
                raise RuntimeError(f"Simulation failed ({proc.returncode}), inspect {log}")
    base.SIM=setup_workspace(kind); checker.DATA=HERE/"catalog"/kind
    checker.DATA.mkdir(exist_ok=True)
    print(f"[{label}] validating emitted traffic and F21/F22 calendar",flush=True)
    check=subprocess.run([sys.executable,str(HERE/"check_pilot_traffic.py"),str(run_dir),kind],
                         cwd=ROOT,text=True,capture_output=True)
    base.require(check.returncode==0,f"{label}: traffic audit failed: {check.stdout}\n{check.stderr}")
    summary=json.loads((run_dir/"validation.json").read_text()); summary["directory"]=run_dir
    drop_rows=load_csv(run_dir/"drops.csv")
    drops_by_flow={}
    for dr in drop_rows:
        x=drops_by_flow.setdefault(dr["flow"],{"confirmed_drop_packets":0,"sites":[]})
        x["confirmed_drop_packets"]+=int(dr["packets"])
        if int(dr["packets"]):x["sites"].append({"interface":dr["interface"],"packets":int(dr["packets"])})
    require_load=int(summary["run"]["load"]); agg=summary["run"]["aggregation"]
    base.require((require_load,agg)==(2,"A1"),f"{label}: effective cell is L{require_load}/{agg}")
    base.require(float(summary["run"]["warmup"])==1 and float(summary["run"]["measurement"])==30,f"{label}: duration mismatch")
    events_path=run_dir/"events.csv"; sig=event_signature(events_path)
    if expected_calendar is not None: base.require(sig==expected_calendar,f"{label}: F21/F22 calendar signature mismatch")
    else:
        cal=HERE/f"calendars/seed{seed}_events.csv"; cal.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(events_path,cal)
        expected_calendar=sig
    vec=next(output.glob(f"{config}-#*.vec")); sca=output/f"{config}-#0.sca"
    params=base.parse_sca(sca)
    interfaces,queues=base.verify_configuration(params,label,run_dir)
    profile_count=check_profile(params,treatment,rates_csv) if rates_csv else 0
    flows={r["flow_id"]:r for r in load_csv(HERE/f"catalog/flows_{kind}.csv")}
    print(f"[{label}] extracting packet latency and queue metrics",flush=True)
    lat,img,stability,drops,dropvec=base.read_vectors(vec,params,summary,len(queues))
    for fid,flow_info in summary["flows"].items():
        for node,rx in flow_info["receivers"].items():
            samples=lat.get(fid,{}).get(node,{}).get("samples",0)
            base.require(samples==int(rx["measured_packets"]),
                         f"{label}: latency vectors for {fid}/{node} contain {samples} samples, expected {rx['measured_packets']}")
    qos=base.assess_qos(summary,lat,img)
    qtime,util=base.summarize_sca_metrics(params)
    nonstable=[q for q in stability if q["sustained_growth"]]
    viable=not nonstable and all(rx["viable"] is not False for f in qos.values() for rx in f["receivers"].values())
    print(f"[{label}] extracting 1 ms temporal association bins",flush=True)
    temporal_path=HERE/f"temporal/seed{seed}/{label}/association_1ms.csv"
    temporal=(read_temporal_summary(temporal_path) if temporal_path.is_file() else
              extract_temporal(vec,run_dir,flows,f"seed{seed}/{label}"))
    base.require(temporal["sensor_latency_vectors"]>0,f"{label}: no sensor latency vectors available for temporal audit")
    report={"label":label,"configuration":config,"treatment":treatment,"mapping":kind,"seed":seed,
      "exploratory":True,"official_profile_frozen":False,"load":"L2","aggregation":"A1",
      "warmup_s":1,"measurement_s":30,"drain_s":.05,"f21_f22_calendar_sha256":sig,
      "f21_f22_calendar_file":str((HERE/f"calendars/seed{seed}_events.csv").relative_to(HERE)),
      "offered_packets":summary["source_packets"],"drops_entire_run":summary["drops"],
      "confirmed_drop_packets_by_flow":drops_by_flow,
      "pending_packets_at_end":summary.get("pending_packet_count_at_simulation_end",0),
      "pending_by_flow":summary.get("pending_at_simulation_end",[]),"qos":qos,
      "queue_stability":stability,"queueing_time":qtime,"link_utilization":util,
      "measurement_drops_by_queue":drops if dropvec else None,"nonstable_queues":nonstable,"viable":viable,
      "simulation_command":cmd,
      "temporal_association":temporal,"cbs_algorithms_checked":profile_count,
      "configuration_parameters":{k:v for (m,k),v in params.items() if k in ("idleSlope","typename") and "transmissionSelectionAlgorithm" in m}}
    write_json(run_dir/"pilot-acceptance.json",report)
    write_json(HERE/f"results/seed{seed}/{label}.json",report)
    # Preserve compact evidence first; remove large OMNeT raw files only after successful audit.
    (HERE/"raw_retention").mkdir(exist_ok=True)
    keep_raw=(label=="calibration_candidate_01" or
              (viable and kind=="variant" and treatment=="C2" and label!="C2_original" and
               not any((HERE/"raw_retention").glob("viable_candidate_*"))))
    raw_files=list(output.glob(f"{config}-#*.vec"))+list(output.glob(f"{config}-#*.vci"))+list(output.glob(f"{config}-#*.sca"))
    if keep_raw:
        bucket=HERE/"raw_retention"/("failed_candidate_01" if label=="calibration_candidate_01" and not viable else f"viable_candidate_{label}")
        bucket.mkdir(parents=True,exist_ok=True)
        for p in raw_files: shutil.move(str(p),bucket/p.name)
    else:
        for p in raw_files: p.unlink()
    return report,expected_calendar

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--inet-root",default=os.environ.get("INET_ROOT")); ap.add_argument("--omnetpp-root",default=os.environ.get("OMNETPP_ROOT")); ap.add_argument("--controls-only",action="store_true"); args=ap.parse_args()
    if not args.inet_root: ap.error("Set INET_ROOT")
    inet=Path(args.inet_root).resolve(); opp=Path(args.omnetpp_root).resolve() if args.omnetpp_root else Path(shutil.which("opp_run")).resolve().parent.parent
    env=os.environ.copy(); env["LD_LIBRARY_PATH"]=str(opp/"lib")+":"+str(inet/"src")+":"+env.get("LD_LIBRARY_PATH","")
    manifest={"commit":subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip(),"omnetpp":subprocess.check_output(["opp_run","-v"],env=env,text=True,stderr=subprocess.STDOUT).strip(),"inet_root":str(inet),"commands":[],"exploratory":True,"official_profile_frozen":False}
    write_json(HERE/"pilot_manifest.json",manifest)
    eventsig=None; reports=[]
    original_ini=HERE/"pilot-original.ini"; variant_ini=HERE/"pilot-variant.ini"
    jobs=[("C2_original","PilotC2Original","original","C2",original_ini,HERE/"configs/cbs_original_nominal.csv"),
          ("C2_variant_nominal","PilotC2Variant","variant","C2",variant_ini,HERE/"configs/cbs_variant_nominal.csv"),
          ("C0_variant","PilotC0Variant","variant","C0",variant_ini,None),
          ("C1_variant","PilotC1Variant","variant","C1",variant_ini,None)]
    for label,cfg,kind,tr,ini,rates in jobs:
        report,eventsig=run_cell(label,cfg,kind,tr,41,ini,inet,env,rates,eventsig); reports.append(report)
    write_json(HERE/"results/seed41/control-comparison.json",{"exploratory":True,"official_profile_frozen":False,"calibration_found_feasible_candidate":None,"runs":reports})
    if args.controls_only: return
    # The frozen protocol requires candidate adaptation to measured failing flows and queues.
    # Candidate generation/execution is continued by calibrate_pilot.py after the controls.
    print("Controls complete. Seed-41 variant nominal viability:",reports[1]["viable"],flush=True)

if __name__=="__main__": main()
