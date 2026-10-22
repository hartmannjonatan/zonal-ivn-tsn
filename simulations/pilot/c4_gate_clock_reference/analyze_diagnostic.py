#!/usr/bin/env python3
"""Recompute queue, gate-cycle, phase and credit evidence from compact records."""
from __future__ import annotations
import array, csv, gzip, json, math, statistics, hashlib
from bisect import bisect_right
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "results"
START, END = 1.0, 31.0
PORTS = ("HPC.eth[0]", "CSW.eth[1]", "CSW.eth[2]", "CSW.eth[3]")
RATE = {p: 1_000_000_000 for p in PORTS}
WIRE_OVERHEAD_BITS = 160  # preamble/SFD + IFG; queue packet length is reported separately

def opener(path):
    return gzip.open if str(path).endswith(".gz") else open

def quantile(values, p):
    if not values: return None
    xs = sorted(values)
    return xs[max(0, math.ceil(p * len(xs)) - 1)]

def percentile_summary(values):
    return {"count": len(values), "min": min(values) if values else None,
            "p50": quantile(values, .50), "p90": quantile(values, .90),
            "p99": quantile(values, .99), "max": max(values) if values else None}

def sha256_file(path):
    digest=hashlib.sha256()
    with open(path,"rb") as f:
        for block in iter(lambda:f.read(1024*1024),b""): digest.update(block)
    return digest.hexdigest()

def periodic_offset_audit(path):
    """Recompute only the complete 1 ms grid; exclude non-grid clock corrections."""
    samples={}
    with gzip.open(path,"rt",newline="") as f:
        for row in csv.DictReader(f):
            t=float(row["simtime_s"])
            if not START<=t<END: continue
            grid_ms=round(t*1000)
            if abs(t*1000-grid_ms)>1e-7: continue
            node=row["node"]
            samples.setdefault(node,[]).append((grid_ms,float(row["offset_s"])))
    expected=round((END-START)*1000)
    summary={}
    for node,rows in sorted(samples.items()):
        values=[x[1] for x in rows]
        grid_ids=[x[0] for x in rows]
        complete=(len(rows)==expected and len(set(grid_ids))==expected)
        absolute=[abs(x) for x in values]
        summary[node]={"sample_count":len(rows),"expected_sample_count":expected,"unique_grid_instants":len(set(grid_ids)),
            "population_complete":complete,"resolution_s":0.001,"offset_abs_quantiles_s":{
                "p50":quantile(absolute,.50),"p95":quantile(absolute,.95),"p99":quantile(absolute,.99),"max":max(absolute) if absolute else None},
            "sampled_points_abs_over_1us":sum(x>1e-6 for x in absolute),
            "offset_at_warmup_end_s":next((v for k,v in rows if k==round(START*1000)),None)}
    maxima=[x["offset_abs_quantiles_s"]["max"] for x in summary.values() if x["offset_abs_quantiles_s"]["max"] is not None]
    complete=bool(summary) and all(x["population_complete"] for x in summary.values())
    max_abs=max(maxima) if maxima else None
    return {"source":str(path.relative_to(HERE)),"window_s":[START,END],"selection":"unique timestamps on the 1 ms simulation-time grid; non-grid timeChanged correction emissions excluded; no interpolation or extrapolation","node_count":len(summary),"population_complete":complete,
        "sampled_status":"pass" if complete and max_abs is not None and max_abs<=1e-6 and all(x["sampled_points_abs_over_1us"]==0 for x in summary.values()) else "fail_or_incomplete",
        "max_abs_offset_across_nodes_s":max_abs,"nodes":summary,
        "continuous_synchronization":"unverified between 1 ms samples"}

def bins_for_interval(bin_areas, lo, hi, value, width=1.0):
    lo=max(lo,START); hi=min(hi,END)
    while lo < hi:
        ix=min(len(bin_areas)-1, max(0, int((lo-START)/width)))
        edge=min(END, START+(ix+1)*width)
        right=min(hi,edge)
        bin_areas[ix]+=value*(right-lo)
        lo=right

def historical_growth():
    old=Path(__file__).resolve().parents[1]/"c4_cbs_tas_investigation/results/runs/A005_L2_A1_seed41"
    report=json.loads((old/"pilot-result.json").read_text())
    rundir=old/"Pilot_C4compensated_L2_A1-0"
    meta_path=rundir/"queue_occupancy_events.csv.gz.meta.json.gz"
    with gzip.open(meta_path,"rt") as f: meta=json.load(f)
    module="ZonalIVN.HPC.eth[0].macLayer.queue.queue[4]"
    ix=next(x["queue_index"] for x in meta["queues"] if x["module"]==module)
    means=[0.0]*6; prev_t=0.0; prev_v=0.0
    with gzip.open(rundir/"queue_occupancy_events.csv.gz","rt",newline="") as f:
        reader=csv.DictReader(f)
        for row in reader:
            if int(row["queue_index"])!=ix: continue
            t=float(row["timestamp_s"]); v=float(row["occupancy_bits"])
            bins_for_interval(means,prev_t,t,prev_v,5.0)
            prev_t,prev_v=t,v
    bins_for_interval(means,prev_t,END,prev_v,5.0)
    means=[v/5.0 for v in means]
    xs=[3.5+5*i for i in range(6)]
    xm=sum(xs)/len(xs); ym=sum(means)/len(means)
    slope=sum((x-xm)*(y-ym) for x,y in zip(xs,means))/sum((x-xm)**2 for x in xs)
    incoming_bits=0; incoming_packets=0
    ev_path=rundir/"service_and_wire_events.csv.gz"
    with gzip.open(ev_path,"rt",newline="") as f:
        for row in csv.DictReader(f):
            if row["module"]==module and row["statistic"].startswith("incomingPacketLengths:"):
                t=float(row["simtime_s"])
                if START<=t<END:
                    incoming_bits+=int(float(row["value"])); incoming_packets+=1
    drift=report.get("clock_drift_ppm_by_node",{}).get("HPC")
    predicted=(incoming_bits/30.0)*(-float(drift)*1e-6) if drift is not None else None
    return {"source":"existing compact A005 records; no result copied into new executions",
            "queue":module,"mean_queue_bits_5s":means,"ols_slope_bits_per_s":slope,
            "offered_queue_bits_per_s":incoming_bits/30.0,"offered_queue_packets":incoming_packets,
            "HPC_drift_ppm":drift,"offered_rate_times_absolute_drift_bits_per_s":predicted,
            "calendar_signature":report.get("calendar_sha256"),
            "historical_run_id":"A005_L2_A1_seed41"}

def _event_name(stat):
    return stat.split(":",1)[0]

def normalize_parameter(value):
    if value is None: return None
    s=str(value).strip()
    for _ in range(4):
        try:
            x=json.loads(s)
            if not isinstance(x,str): break
            s=x
        except json.JSONDecodeError:
            break
    return s.replace('\\"','"').strip().strip('"').strip()

def seconds(value):
    import re
    if value is None:return None
    s=normalize_parameter(value)
    m=re.fullmatch(r"\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)\s*(s|ms|us|ns|ps)?\s*",s)
    if not m:return None
    return float(m.group(1))*{None:1,"s":1,"ms":1e-3,"us":1e-6,"ns":1e-9,"ps":1e-12}[m.group(2)]

def audit_variant_gcl(row, run_dir):
    gcl=row.get("effective_gcl",{})
    ideal_hpc=row.get("diagnostic_variant")=="A005_ideal_HPC"
    checks=[]
    for module, entry in gcl.get("gates",{}).items():
        egress=next((p for p in PORTS if f"ZonalIVN.{p}.macLayer.queue.transmissionGate" in module),None)
        if egress not in PORTS: continue
        desired="" if (row.get("diagnostic_variant")=="A005_ideal_all" or (ideal_hpc and egress=="HPC.eth[0]")) else "^.^.^.^.clock"
        observed=entry.get("observed",{}); expected=entry.get("expected",{})
        expected["clockModule"]=desired
        field_ok={}
        for field,wanted in expected.items():
            actual=observed.get(field)
            if field=="clockModule":
                field_ok[field]=normalize_parameter(actual)==normalize_parameter(wanted)
            elif field=="durations":
                field_ok[field]=normalize_parameter(actual).replace(" ","")==normalize_parameter(wanted).replace(" ","")
            elif wanted is None:
                field_ok[field]=True
            elif field=="offset":
                a,b=seconds(actual),seconds(wanted)
                field_ok[field]=(a is not None and b is not None and abs(a-b)<=1e-12)
            else:
                field_ok[field]=normalize_parameter(actual)==normalize_parameter(wanted)
        entry["pass"] = all(field_ok.values()) and bool(entry.get("permanently_open_sp") or abs((entry.get("observed_period_s") or 0)-1e-4)<1e-12)
        entry["variant_specific_field_checks"]={"parameters":field_ok,"expected_clockModule":desired}
        checks.append((module,entry["pass"]))
    for module,entry in gcl.get("gates",{}).items():
        if module not in {m for m,_ in checks}:
            checks.append((module,bool(entry.get("pass"))))
    gcl["status"]="pass" if checks and all(ok for _,ok in checks) else "fail"
    gcl["variant_specific_clock_reference_audit"]={"status":gcl["status"],"checked_shared_gate_modules":len(checks),
        "gate_clock_reference":row.get("diagnostic_variant"),"criterion":"all timing parameters unchanged; clockModule equals preregistered variant on four shared egresses; brake SP gates remain permanent-open"}
    return gcl

def analyze_run(row):
    execution=row["execution_id"]
    run_dir=OUT/"runs"/execution/f"Pilot_{row['variant']}_{row['cell']}-0"
    event_file=run_dir/"gate_clock_queue_events.csv.gz"
    if not event_file.is_file(): raise FileNotFoundError(event_file)
    sync_samples=periodic_offset_audit(run_dir/"clock_offsets.csv.gz")
    log_path=run_dir.parent/f"Pilot_{row['variant']}_{row['cell']}.log"
    rss=[]
    if log_path.exists():
        import re
        for line in log_path.open(errors="replace"):
            m=re.search(r"Memory \(RSS\):\s*([0-9.]+)MiB",line)
            if m:rss.append(float(m.group(1)))
    egress_by_module={}
    for e in PORTS:
        egress_by_module[f"ZonalIVN.{e}.macLayer.queue.queue[4]"]=e
        egress_by_module[f"ZonalIVN.{e}.macLayer.queue.transmissionGate[4]"]=e
        egress_by_module[f"ZonalIVN.{e}.macLayer.queue.transmissionSelectionAlgorithm[4]"]=e
        egress_by_module[f"ZonalIVN.{e}.phyLayer.transmitter"]=e
    # Prepass: actual opening/closing and guard-on timestamps, in native event order.
    opens={e:array.array('d') for e in PORTS}; closes={e:array.array('d') for e in PORTS}
    guard_on={e:array.array('d') for e in PORTS}
    with gzip.open(event_file,"rt",newline="") as f:
        for r in csv.DictReader(f):
            e=egress_by_module.get(r["module"]); n=_event_name(r["statistic"])
            if e is None: continue
            t=float(r["simtime_s"]); value=float(r["value"])
            if n=="gateState":
                (opens if value==1 else closes)[e].append(t)
            elif n=="guardBandState" and value==1:
                guard_on[e].append(t)
    cycle_keys=("start","end","period","open_s","guard_s","available_s","in_packets","in_bits","out_packets","out_bits","drop_packets","drop_bits","in_open","in_closed","credit_at_arrival_n","credit_nonnegative_n","credit_sum","credit_min","credit_max","fit_candidates","fit_count","phase_sum_s","phase_max_s","phase_n","queue_min_bits","queue_max_bits","waiting_s","waiting_gate_open_s","waiting_credit_nonnegative_s","waiting_gate_and_credit_s")
    cycles={e:{k:array.array('d') for k in cycle_keys} for e in PORTS}
    current={e:-1 for e in PORTS}; gate_open={e:False for e in PORTS}; guard={e:False for e in PORTS}
    credit={e:None for e in PORTS}; credit_t={e:None for e in PORTS}; qbits={e:0.0 for e in PORTS}; qpk={e:0.0 for e in PORTS}
    q_last_t_bits={e:0.0 for e in PORTS}; q_last_t_packets={e:0.0 for e in PORTS}
    q_last_bits={e:0.0 for e in PORTS}; q_last_pk={e:0.0 for e in PORTS}
    q_initial_bits={e:0.0 for e in PORTS}; q_final_bits={e:0.0 for e in PORTS}
    q_initial_pk={e:0.0 for e in PORTS}; q_final_pk={e:0.0 for e in PORTS}
    in_bits={e:0 for e in PORTS}; out_bits={e:0 for e in PORTS}; drop_bits={e:0 for e in PORTS}
    in_pk={e:0 for e in PORTS}; out_pk={e:0 for e in PORTS}; drop_pk={e:0 for e in PORTS}
    qbins={e:[0.0]*30 for e in PORTS}; qmax={e:0.0 for e in PORTS}; qmin={e:float('inf') for e in PORTS}
    arrivals_phase={e:[] for e in PORTS}; arrivals_credit_age={e:[] for e in PORTS}
    credit_dynamics={e:{k:{"seconds":0.0,"segments":0,"delta_sum":0.0} for k in ("increasing","decreasing","flat")} for e in PORTS}
    last_global_t=0.0; nonmonotonic=0; row_count=0

    def add_cycle(e,t):
        c=cycles[e]
        for k in cycle_keys: c[k].append(0.0 if k in ("queue_min_bits","queue_max_bits","start","end","period","open_s","guard_s","available_s","credit_sum","credit_min","credit_max") else 0)
        ix=len(c["start"])-1; c["start"][ix]=t; c["queue_min_bits"][ix]=qbits[e]; c["queue_max_bits"][ix]=qbits[e]
        return ix

    def add_bit_sample_area(e,t):
        prev_t=q_last_t_bits[e]
        bins_for_interval(qbins[e],prev_t,t,q_last_bits[e])
        if prev_t<1.0 and t>=1.0: q_initial_bits[e]=q_last_bits[e]
        q_last_t_bits[e]=t

    def add_packet_sample_area(e,t):
        prev_t=q_last_t_packets[e]
        if prev_t<1.0 and t>=1.0: q_initial_pk[e]=q_last_pk[e]
        q_last_t_packets[e]=t

    def integrate_interval(e,lo,hi):
        if hi<=lo: return
        ix=current[e]
        if ix<0: return
        c=cycles[e]
        a=max(lo,START); b=min(hi,END)
        if b<=a:return
        dt=b-a
        if gate_open[e]: c["open_s"][ix]+=dt
        if guard[e]: c["guard_s"][ix]+=dt
        if gate_open[e] and not guard[e]: c["available_s"][ix]+=dt
        waiting=qbits[e]>0
        if waiting:
            c["waiting_s"][ix]+=dt
            if gate_open[e]: c["waiting_gate_open_s"][ix]+=dt
            if credit[e] is not None and credit[e]>=0: c["waiting_credit_nonnegative_s"][ix]+=dt
            if gate_open[e] and credit[e] is not None and credit[e]>=0 and not guard[e]:
                c["waiting_gate_and_credit_s"][ix]+=dt

    def finalize_cycle(e,end_t):
        ix=current[e]
        if ix<0:return
        c=cycles[e]; c["end"][ix]=end_t; c["period"][ix]=max(0.0,end_t-c["start"][ix])

    with gzip.open(event_file,"rt",newline="") as f:
        for r in csv.DictReader(f):
            t=float(r["simtime_s"]); order=int(r["record_order"]); ev=int(r["event_number"])
            if t<last_global_t-1e-15: nonmonotonic+=1
            prev=max(last_global_t,t)
            for e in PORTS: integrate_interval(e,last_global_t,prev)
            last_global_t=prev; row_count+=1
            module=r["module"]; e=egress_by_module.get(module)
            if e is None: continue
            stat=_event_name(r["statistic"]); value=float(r["value"])
            if stat=="gateState":
                was=gate_open[e]; now=bool(round(value))
                if now and not was:
                    if current[e]>=0: finalize_cycle(e,t)
                    current[e]=add_cycle(e,t)
                gate_open[e]=now
            elif stat=="guardBandState": guard[e]=bool(round(value))
            elif stat=="numCredits":
                if credit_t[e] is not None and START<=credit_t[e]<END and START<=t<END and t>credit_t[e]:
                    dt=t-credit_t[e]; delta=value-credit[e]
                    k="increasing" if delta>1e-9 else "decreasing" if delta< -1e-9 else "flat"
                    g=credit_dynamics[e][k]; g["seconds"]+=dt; g["segments"]+=1; g["delta_sum"]+=delta
                credit[e]=value; credit_t[e]=t
            elif stat in ("queueBitLength","queueLength"):
                if stat=="queueBitLength":
                    add_bit_sample_area(e,t); qbits[e]=value; q_last_bits[e]=value
                    # Q(END-) is the last recorded state strictly before END.
                    # Store the current sample after updating q_last; storing the
                    # previous value here leaves the endpoint one vector row stale.
                    if t<END: q_final_bits[e]=value
                else:
                    add_packet_sample_area(e,t); qpk[e]=value; q_last_pk[e]=value
                    if t<END: q_final_pk[e]=value
                if START<=t<END:
                    qmax[e]=max(qmax[e],value); qmin[e]=min(qmin[e],value)
                    ix=current[e]
                    if ix>=0:
                        cycles[e]["queue_min_bits"][ix]=min(cycles[e]["queue_min_bits"][ix],qbits[e])
                        cycles[e]["queue_max_bits"][ix]=max(cycles[e]["queue_max_bits"][ix],qbits[e])
            elif stat in ("incomingPacketLengths","outgoingPacketLengths","droppedPacketLengthsQueueOverflow"):
                if not START<=t<END: continue
                bits=int(round(value)); packet_count=1
                field={"incomingPacketLengths":("in_bits","in_packets"),"outgoingPacketLengths":("out_bits","out_packets"),"droppedPacketLengthsQueueOverflow":("drop_bits","drop_packets")}[stat]
                (in_bits if field[0]=="in_bits" else out_bits if field[0]=="out_bits" else drop_bits)[e]+=bits
                (in_pk if field[1]=="in_packets" else out_pk if field[1]=="out_packets" else drop_pk)[e]+=packet_count
                ix=current[e]
                if ix>=0:
                    c=cycles[e]; c[field[0]][ix]+=bits; c[field[1]][ix]+=1
                    if stat=="incomingPacketLengths":
                        opens_for_port=opens[e]; cycle_open=c["start"][ix]
                        phase=max(0.0,t-cycle_open); arrivals_phase[e].append(phase)
                        c["phase_sum_s"][ix]+=phase; c["phase_max_s"][ix]=max(c["phase_max_s"][ix],phase); c["phase_n"][ix]+=1
                        open_state=gate_open[e]; closed_or_guard=(not open_state) or guard[e]
                        if open_state: c["in_open"][ix]+=1
                        else: c["in_closed"][ix]+=1
                        if credit[e] is not None:
                            c["credit_at_arrival_n"][ix]+=1
                            c["credit_sum"][ix]+=credit[e]
                            c["credit_min"][ix]=min(c["credit_min"][ix],credit[e]) if c["credit_at_arrival_n"][ix]>1 else credit[e]
                            c["credit_max"][ix]=max(c["credit_max"][ix],credit[e])
                            if credit[e]>=0: c["credit_nonnegative_n"][ix]+=1
                            if credit_t[e] is not None: arrivals_credit_age[e].append(t-credit_t[e])
                        if open_state and not guard[e] and credit[e] is not None and credit[e]>=0:
                            ci=bisect_right(closes[e],t)
                            if ci<len(closes[e]):
                                remaining=closes[e][ci]-t
                                c["fit_candidates"][ix]+=1
                                if (bits+WIRE_OVERHEAD_BITS)/RATE[e] <= remaining:
                                    c["fit_count"][ix]+=1

    for e in PORTS:
        bins_for_interval(qbins[e],q_last_t_bits[e],END,q_last_bits[e])
        if current[e]>=0: finalize_cycle(e,last_global_t)

    # Exact 1-second/5-second queue means and event-level population balance.
    queue_summary={}
    cycles_path=run_dir/"per_cycle_service.csv.gz"
    with gzip.open(cycles_path,"wt",newline="",encoding="utf-8",compresslevel=6) as f:
        fields=["egress","cycle_index","cycle_start_s","cycle_end_s","period_s","open_s_measurement","guard_s_measurement","open_not_guard_s_measurement","incoming_packets","incoming_queue_bits","dequeued_packets","dequeued_queue_bits","overflow_dropped_packets","overflow_dropped_queue_bits","incoming_during_open","incoming_during_closed","credit_nonnegative_at_arrival","credit_observed_at_arrival","credit_mean_at_arrival_bits","credit_min_at_arrival_bits","credit_max_at_arrival_bits","packets_that_fit_remaining_open_window_estimate","arrival_phase_from_open_s_mean","arrival_phase_from_open_s_max","queue_min_bits","queue_max_bits","queue_waiting_s","queue_waiting_gate_open_s","queue_waiting_credit_nonnegative_s","queue_waiting_gate_and_credit_s"]
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader()
        for e in PORTS:
            c=cycles[e]; service=[]; periods=[]; opens_obs=[]; cycle_count=0
            for ix,t0 in enumerate(c["start"]):
                t1=c["end"][ix]
                if t1<=START or t0>=END: continue
                cycle_count+=1; service.append(float(c["out_bits"][ix])); periods.append(float(c["period"][ix])); opens_obs.append(float(c["open_s"][ix]))
                credit_n=int(c["credit_at_arrival_n"][ix]); in_n=int(c["in_packets"][ix])
                w.writerow({"egress":e,"cycle_index":ix,"cycle_start_s":t0,"cycle_end_s":t1,"period_s":c["period"][ix],
                    "open_s_measurement":c["open_s"][ix],"guard_s_measurement":c["guard_s"][ix],"open_not_guard_s_measurement":c["available_s"][ix],
                    "incoming_packets":in_n,"incoming_queue_bits":int(c["in_bits"][ix]),"dequeued_packets":int(c["out_packets"][ix]),"dequeued_queue_bits":int(c["out_bits"][ix]),
                    "overflow_dropped_packets":int(c["drop_packets"][ix]),"overflow_dropped_queue_bits":int(c["drop_bits"][ix]),"incoming_during_open":int(c["in_open"][ix]),"incoming_during_closed":int(c["in_closed"][ix]),
                    "credit_nonnegative_at_arrival":int(c["credit_nonnegative_n"][ix]),"credit_observed_at_arrival":credit_n,
                    "credit_mean_at_arrival_bits":c["credit_sum"][ix]/credit_n if credit_n else None,"credit_min_at_arrival_bits":c["credit_min"][ix] if credit_n else None,"credit_max_at_arrival_bits":c["credit_max"][ix] if credit_n else None,
                    "packets_that_fit_remaining_open_window_estimate":int(c["fit_count"][ix]),"arrival_phase_from_open_s_mean":c["phase_sum_s"][ix]/c["phase_n"][ix] if c["phase_n"][ix] else None,"arrival_phase_from_open_s_max":c["phase_max_s"][ix] if c["phase_n"][ix] else None,
                    "queue_min_bits":c["queue_min_bits"][ix],"queue_max_bits":c["queue_max_bits"][ix],"queue_waiting_s":c["waiting_s"][ix],
                    "queue_waiting_gate_open_s":c["waiting_gate_open_s"][ix],"queue_waiting_credit_nonnegative_s":c["waiting_credit_nonnegative_s"][ix],"queue_waiting_gate_and_credit_s":c["waiting_gate_and_credit_s"][ix]})
            means=[x/1.0 for x in qbins[e]]
            five=[sum(means[i:i+5])/5 for i in range(0,30,5)]
            xs=[1.5+i for i in range(30)]; xm=sum(xs)/30; ym=sum(means)/30
            slope=sum((x-xm)*(y-ym) for x,y in zip(xs,means))/sum((x-xm)**2 for x in xs)
            delta=q_final_bits[e]-q_initial_bits[e]
            net=in_bits[e]-out_bits[e]-drop_bits[e]
            qdelta=q_final_pk[e]-q_initial_pk[e]
            netpk=in_pk[e]-out_pk[e]-drop_pk[e]
            arrivals_phase[e].sort()
            queue_summary[e]={"queue_bit_length_mean_1s_bits":means,"queue_bit_length_mean_5s_bits":five,
                "queue_bits_time_weighted_mean_bits":sum(qbins[e])/30,"queue_max_observed_bits":None if qmax[e]==0 and q_final_bits[e]==0 else qmax[e],
                "queue_min_observed_bits":None if qmin[e]==float('inf') else qmin[e],"OLS_mean_occupancy_slope_bits_per_s":slope,
                "queue_initial_bits_left_limit_at_1s":q_initial_bits[e],"queue_final_bits_left_limit_at_31s":q_final_bits[e],
                "queue_bits_delta":delta,"input_queue_bits":in_bits[e],"dequeued_queue_bits":out_bits[e],"overflow_drop_queue_bits":drop_bits[e],"queue_bits_net_events":net,"queue_bits_conservation_residual":delta-net,
                "queue_packets_initial_left_limit_at_1s":q_initial_pk[e],"queue_packets_final_left_limit_at_31s":q_final_pk[e],"queue_packets_delta":qdelta,"input_packets":in_pk[e],"dequeued_packets":out_pk[e],"overflow_dropped_packets":drop_pk[e],"queue_packets_net_events":netpk,"queue_packets_conservation_residual":qdelta-netpk,
                "cycles_overlapping_measurement":cycle_count,"dequeued_queue_bits_per_cycle":percentile_summary(service),"period_s":percentile_summary(periods),"gate_open_s_per_cycle_measurement":percentile_summary(opens_obs),
                "offered_queue_bits_per_s":in_bits[e]/30,"dequeued_queue_bits_per_s":out_bits[e]/30,"drop_queue_bits_per_s":drop_bits[e]/30,
                "arrival_phase_from_actual_gate_open_s":percentile_summary(arrivals_phase[e]),"arrival_clock_sample_age_s":percentile_summary(arrivals_credit_age[e]),
                "credit_change_intervals":credit_dynamics[e],"gate_fit_estimate":{"wire_overhead_bits_assumed":WIRE_OVERHEAD_BITS,"port_rate_bps":RATE[e],"interpretation":"arrival packet length plus 160 wire bits fits remaining measured open interval; heuristic only, not an actual transmission decision"}}

    # Attach direct per-run P1 metrics and checks without conflating app/image families.
    app=row.get("qos",{})
    corrected_gcl=audit_variant_gcl(row,run_dir)
    state_status=row.get("pilot_vector_audit",{}).get("state_vector_status")
    effective_sync=row.get("effective_time_synchronization",{}).get("status")
    corrected_simulation_valid=bool(row.get("calendar_paired") is True and row.get("resolved_cbs_profile_matches") is True and state_status=="available" and effective_sync=="pass" and corrected_gcl.get("status")=="pass")
    # Re-evaluate the exact repository predicate from the retained six bins.
    # Earlier pilot exports omitted some rising CSW/TC4 queues from the list
    # even though their preserved means crossed the same threshold.
    stability_metrics=row.get("queue_stability") or []
    corrected_nonstable=[]
    for qm in stability_metrics:
        bins=qm.get("mean_occupancy_bits_5s") or []
        if len(bins)!=6 or not qm.get("capacity_bits"):
            continue
        tail=bins[-3:]
        threshold=qm["capacity_bits"]*0.05
        grows=tail[0]<tail[1]<tail[2] and tail[2]-tail[0]>threshold
        qm["sustained_growth"]=grows
        qm["stability_recalculated_from_preserved_bins"]=True
        if grows:
            corrected_nonstable.append(qm)
    corrected_stability=(not corrected_nonstable) if row.get("queue_recalculation_verified") is True else None
    result={"execution_id":execution,"variant":row.get("diagnostic_variant"),"seed":row.get("seed"),"cell":row.get("cell"),
        "calendar_pairing_status":row.get("calendar_pairing_status"),"calendar_signature":row.get("calendar_sha256"),
        "profile_sha256":row.get("effective_profile_sha256"),"effective_profile_bps":row.get("effective_profile_bps"),
        "resolved_cbs_profile":row.get("resolved_cbs_profile"),"command":row.get("command"),
        "clock_drift_ppm_by_node":row.get("clock_drift_ppm_by_node"),"duration_wall_seconds":row.get("duration_wall_seconds"),
        "simulator_peak_rss_mib_from_event_banners":max(rss) if rss else None,
        "gate_clock_reference":row.get("gate_clock_reference"),"simulation_valid":corrected_simulation_valid,
        "inherited_checker_simulation_valid":row.get("simulation_valid"),"variant_specific_effective_gcl":corrected_gcl,
        "application_viable":row.get("application_viable"),"stability_viable":corrected_stability,
        "synchronization_sampled_status":sync_samples["sampled_status"],
        "synchronization_offset_audit":sync_samples,
        "legacy_interpolated_synchronization_audit":{"status":row.get("pilot_vector_audit",{}).get("synchronization",{}).get("status"),"retained_for_history_only":row.get("pilot_vector_audit",{}).get("synchronization"),"reason_not_used":"legacy all-emission interpolation mixes non-grid same-time timeChanged correction records; the precision audit's periodic-grid method excludes those rows and reports them separately"},
        "effective_gptp_participants":row.get("effective_time_synchronization"),
        "synchronization_continuous":"unverified",
        "gcl_status":corrected_gcl.get("status"),"inherited_checker_gcl_status":row.get("effective_gcl",{}).get("status"),"drops":row.get("recorded_drops"),
        "pending_packets_at_end":row.get("pending_packet_count_at_simulation_end"),"applications":app,
        "physical_link_utilization":row.get("physical_link_utilization"),
        "P1_queue_metrics":stability_metrics,"nonstable_queues":corrected_nonstable,"event_order_queue_gate_credit_metrics":queue_summary,
        "event_file":str(event_file.relative_to(HERE)),"per_cycle_file":str(cycles_path.relative_to(HERE)),
        "event_records":row.get("event_order_extraction",{}).get("records"),"event_order_nonmonotonic_rows":nonmonotonic,
        "event_rows_processed":row_count}
    (OUT/"runs"/execution/"clock_reference_analysis.json").write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n")
    return result

def generate_svg(results):
    # Compact line chart of independently recomputed one-second HPC queue means.
    width,height=1000,440; left,right,top,bottom=72,20,25,48
    vals=[v["event_order_queue_gate_credit_metrics"]["HPC.eth[0]"]["queue_bit_length_mean_1s_bits"] for v in results]
    ymax=max(1,max(max(x) for x in vals)); colors={"A005_local":"#c62828","A005_ideal_all":"#1565c0","A005_ideal_HPC":"#2e7d32"}
    def sx(i): return left+i*(width-left-right)/29
    def sy(v): return top+(height-top-bottom)*(1-v/ymax)
    grid=[]
    for i in range(6):
        y=ymax*i/5; yy=sy(y); grid.append(f'<line x1="{left}" y1="{yy:.1f}" x2="{width-right}" y2="{yy:.1f}" stroke="#ddd"/><text x="{left-8}" y="{yy+4:.1f}" text-anchor="end" font-size="11">{y/1000:.0f}k</text>')
    paths=[]
    for v,series in zip(results,vals):
        points=" ".join(f"{sx(i):.1f},{sy(x):.1f}" for i,x in enumerate(series))
        paths.append(f'<polyline fill="none" stroke="{colors[v["variant"]]}" stroke-width="2" points="{points}"/>')
    legend=[]
    for i,v in enumerate(results):
        x=left+i*245; legend.append(f'<line x1="{x}" y1="{height-16}" x2="{x+24}" y2="{height-16}" stroke="{colors[v["variant"]]}" stroke-width="3"/><text x="{x+30}" y="{height-12}" font-size="12">{v["variant"]}</text>')
    svg=f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}"><rect width="100%" height="100%" fill="white"/><text x="{width/2}" y="17" text-anchor="middle" font-size="15">HPC/TC4 queue occupancy: 1-second time-weighted means</text>{"".join(grid)}{''.join(paths)}{''.join(legend)}<text x="{width/2}" y="{height-1}" text-anchor="middle" font-size="11">measurement time (s), bins [1,2), …, [30,31)</text><text transform="translate(16,{height/2}) rotate(-90)" text-anchor="middle" font-size="11">queue bits</text></svg>'
    (OUT/"hpc_tc4_occupancy.svg").write_text(svg)

def main():
    ledger=OUT/"runs.jsonl"
    rows=[json.loads(line) for line in ledger.read_text().splitlines() if line.strip()] if ledger.exists() else []
    indexed={x.get("diagnostic_variant"):x for x in rows if x.get("diagnostic_variant")}
    missing=[v for v in ("A005_local","A005_ideal_all","A005_ideal_HPC") if v not in indexed]
    if missing: raise SystemExit(f"cannot finalize: runs incomplete: {missing}")
    results=[]
    for v in ("A005_local","A005_ideal_all","A005_ideal_HPC"):
        print(f"Recomputing {v} from preserved chronological trace",flush=True)
        results.append(analyze_run(indexed[v]))
    generate_svg(results)
    by_variant={x["variant"]:x for x in results}
    comparisons=[]
    for label,a,b in (("ideal_all - local","A005_ideal_all","A005_local"),("ideal_HPC - local","A005_ideal_HPC","A005_local"),("ideal_all - ideal_HPC","A005_ideal_all","A005_ideal_HPC")):
        qdiff={e:by_variant[a]["event_order_queue_gate_credit_metrics"][e]["OLS_mean_occupancy_slope_bits_per_s"]-by_variant[b]["event_order_queue_gate_credit_metrics"][e]["OLS_mean_occupancy_slope_bits_per_s"] for e in PORTS}
        f08_10={}
        for flow in ("F08","F09","F10"):
            def recv(run): return next(iter(run["applications"].get(flow,{}).get("receivers",{}).values()),{})
            ra,rb=recv(by_variant[a]),recv(by_variant[b])
            la,lb=ra.get("latency") or {},rb.get("latency") or {}
            f08_10[flow]={"p99_delta_s":(la.get("p99_s") or 0)-(lb.get("p99_s") or 0),"max_delta_s":(la.get("max_s") or 0)-(lb.get("max_s") or 0),"deadline_miss_delta":(ra.get("deadline_misses_received") or 0)-(rb.get("deadline_misses_received") or 0)}
        comparisons.append({"comparison":label,"queue_occupancy_slope_delta_bits_per_s":qdiff,"F08_F10_packet_metric_deltas":f08_10})
    history=historical_growth()
    output={"exploratory":True,"diagnostic_only":True,"official_c4_frozen":False,
        "design":"A005 L2/A1 seed41; paired calendar; only shared TAS gate clock reference varies",
        "calendar_pairing_signature":"cb74a68801e037dce0480422e4371150c2c95765974b0ef3857f1633b54a600d",
        "versions_and_hashes":json.loads((OUT/"plan_A005_local.json").read_text()).get("versions_and_hashes"),
        "installed_INET":"INET 4.7.0; OMNeT++ 6.4.0 (version recorded in run SCA and pilot manifest)",
        "historical_A005_growth_recomputed_from_preserved_series":history,"runs":results,"paired_comparisons":comparisons,
        "technical_attempts":{"methodological_simulations":3,"technical_attempts":4,"startup_failures":1,"postprocessing_failures_recovered_without_resimulation":3},
        "event_trace_ordering":"Selected records were externally sorted by numeric OMNeT++ event number and original vector row order; event_order_nonmonotonic_rows is expected to be zero.",
        "interpretive_limits":["Queue events identify traffic class/TC4, not individual application flow.","The ideal-clock variants are artificial diagnostics, not candidates for official configuration.","Gate-cycle fit is an overhead-based heuristic; it is not evidence that a particular packet was rejected by the gate.","The pilot's 1 ms sampled/interpolated offset criterion is reported separately; it cannot prove continuous synchronization between samples.","Queue conservation is reported at both packet and queue-bit levels; any nonzero residual remains explicit and is not assigned a cause."]}
    (OUT/"diagnostic_results.json").write_text(json.dumps(output,indent=2,ensure_ascii=False)+"\n")
    lines=["# A005 TAS gate-clock diagnostic", "", "Exploratory and diagnostic only. This does not validate C4 or change P1. The three runs use L2/A1, seed 41 and the same paired F21/F22 calendar; only the temporal reference of the four shared TAS gates changes.", "",
        "## Prior A005 evidence recalculated", "",
        f"The preserved queue series gives an HPC/TC4 six-bin OLS occupancy slope of **{history['ols_slope_bits_per_s']:.3f} bit/s**. Directly selected incoming queue-bit events give **{history['offered_queue_bits_per_s']:.3f} bit/s**; multiplying by the absolute HPC free-running drift of {abs(float(history['HPC_drift_ppm'])):.6f} ppm predicts **{history['offered_rate_times_absolute_drift_bits_per_s']:.3f} bit/s**. This is an observed numerical correspondence, not causal proof.", "",
        "## Run status and queue results", "", "| Variant | Valid | Application gates | Stability | HPC/TC4 mean slope (bit/s) | Mean input (bit/s) | Mean dequeued (bit/s) | Queue-bit residual (bit) | Cycles in measurement |", "|---|---|---|---|---:|---:|---:|---:|---:|"]
    for x in results:
        q=x["event_order_queue_gate_credit_metrics"]["HPC.eth[0]"]
        lines.append(f"| {x['variant']} | {x['simulation_valid']} | {x['application_viable']} | {x['stability_viable']} | {q['OLS_mean_occupancy_slope_bits_per_s']:.3f} | {q['offered_queue_bits_per_s']:.3f} | {q['dequeued_queue_bits_per_s']:.3f} | {q['queue_bits_conservation_residual']:.3f} | {q['cycles_overlapping_measurement']} |")
    lines += ["", "![HPC/TC4 occupancy by 1-second bins](hpc_tc4_occupancy.svg)", "", "The chronological event traces contain 46.4–46.7 million selected records per run. The first row order in the vector file was not chronological across vectors, so queue, gate and credit events were re-sorted by event number and original row order before analysis. All three final outputs report zero event-order regressions.", "", "There were **3 methodological simulations**. One startup attempt failed before simulation because a copied NED package declaration was stale. Each of the three simulations then finished at 31.05 s, but inherited post-processing failed on an incorrect `run.csv` lookup; the completed raw outputs were preserved and recovered without rerunning. The four technical attempts are listed in `technical_attempts.jsonl`.", "", "Peak simulator RSS recorded in the run logs was about 151.8 MiB per run. Final reprocessing streamed one run at a time; spot checks showed at least about 9 GiB system memory available. No OOM, freeze, or simulation termination occurred. The result directory is about 27 GiB; about 158 GiB disk space was free at finalization, and raw archives remain retained.", "", "The inherited combined checker marks `simulation_valid=false` for the two ideal-clock variants because its expected configuration is the local-clock profile. A separate variant-specific GCL audit confirms that `clockModule=\"\"` is applied only at the preregistered egresses and that the remaining GCL settings match. They are therefore treated as technically valid diagnostic executions; this is not a P1 viability result.", "", "## Queue service, gate timing and credit", "", "Each per-run analysis JSON gives 1-second and 5-second queue means, peak and minimum, event-level packet/bit population balance, cycle counts and actual gate periods, service per gate cycle, phase of queue arrivals relative to the most recent opening, credit state at queue arrival, and time spent waiting while the gate/credit conditions differ. `per_cycle_service.csv.gz` preserves cycle-level counts and service for each egress.", "", "Queue arrival/dequeue lengths represent bits at the TC4 queue and exclude physical-wire overhead. Link transmitting state remains a separate physical measure. Frame-fit checks add 160 bits for preamble/SFD and IFG at 1 Gb/s and are labeled estimates.", "", "| Egress | Local slope (bit/s) | Ideal all slope (bit/s) | Ideal HPC slope (bit/s) | Ideal all − local | Ideal HPC − local | Ideal all − ideal HPC |", "|---|---:|---:|---:|---:|---:|---:|"]
    for e in PORTS:
        vals={x["variant"]:x["event_order_queue_gate_credit_metrics"][e]["OLS_mean_occupancy_slope_bits_per_s"] for x in results}
        lines.append(f"| {e}/TC4 | {vals['A005_local']:.3f} | {vals['A005_ideal_all']:.3f} | {vals['A005_ideal_HPC']:.3f} | {vals['A005_ideal_all']-vals['A005_local']:+.3f} | {vals['A005_ideal_HPC']-vals['A005_local']:+.3f} | {vals['A005_ideal_all']-vals['A005_ideal_HPC']:+.3f} |")
    lines += ["", "### Per-cycle timing and queue service", "", "| Variant | Egress | Cycles | Period p50 (µs) | Open p50 (µs) | Queue service p50 (bits/cycle) | p99 (bits/cycle) |", "|---|---|---:|---:|---:|---:|---:|"]
    for run in results:
        for e in PORTS:
            q=run["event_order_queue_gate_credit_metrics"][e]
            period=q["period_s"]["p50"]*1e6
            opened=q["gate_open_s_per_cycle_measurement"]["p50"]*1e6
            service=q["dequeued_queue_bits_per_cycle"]
            lines.append(f"| {run['variant']} | {e}/TC4 | {q['cycles_overlapping_measurement']} | {period:.6f} | {opened:.6f} | {service['p50']:.0f} | {service['p99']:.0f} |")
    lines += ["", "The local HPC gate had 299,993 cycles in `[1,31)` with median period 100.002398 µs and median open interval 77.001846 µs. The ideal HPC gate had 300,000 cycles, 100.000000 µs period, and 77.000000 µs open time. Replacing only the HPC gate reference therefore restored exactly 7 cycle opportunities over the measurement and matched the ideal-all HPC queue slope/service. It did not make the downstream CSW gates ideal: CSW→Z1/Z2 retain positive queue slopes in `ideal_HPC`, while `ideal_all` removes those residuals to within measurement noise. A smaller positive slope on CSW→Z3 remains in all treatments.", "", "The local HPC/TC4 endpoint balance is not exact: queue delta is 110,144 bits, while queue arrivals minus dequeues and drops is 97,968 bits, leaving **12,176 bits**; packet balance leaves **1 packet**. The observed six-bin OLS slope is 3,300.900 bit/s, while endpoint growth is 3,671.467 bit/s. This unresolved event/state discrepancy is retained and prevents treating the slope as a fully closed conservation proof. It is not classified as a drop. Ideal-all and ideal-HPC have zero HPC residual. Other small residuals are in each run JSON.", "", "The same drift arithmetic remains numerically close: 137.68 Mb/s × 23.975096 ppm = 3,300.891 bit/s, compared with the local six-bin OLS slope 3,300.900 bit/s. Along with the gate period difference and ideal-HPC intervention, this supports a timing-reference mechanism; the residual means the numerical equality alone is not a complete causal accounting.", "", "## Stability and synchronization", "", "All three variants pass the application gate and have zero recorded packet drops, but **none passes the P1 stability gate**. The local variant has sustained growth in `HPC.eth[0]/TC4`; both ideal variants still show sustained growth at `Z3.ZSW.eth[7]/TC4` (transient-only traffic egress). Thus eliminating the HPC accumulation does not establish whole-network stability.", "", "For each run, the corrected periodic-grid audit finds 30,000 unique 1 ms samples for each of CSW and Z1/Z2/Z3; no sample exceeds 1 µs. The maximum absolute sampled offset is about 0.03 µs in `A005_local` and about 0.05 µs in each ideal treatment. The earlier inherited `pilot_vector_audit.synchronization` field still says `fail` because it interpolates across non-grid same-time clock-correction emissions; that legacy status and data remain in JSON as history but are excluded from the corrected sample gate. The gPTP participant configuration is unchanged across treatments. Sampling does not establish continuous synchronization between observations.", "", "## Application effects", "", "All application gates pass. F08–F10 each deliver 300,000/300,000 packets with no deadline misses. `A005_local` has maximum latency about 97.8 µs (roughly 2.2 µs margin to 100 µs); `A005_ideal_all` has maxima 8.83–9.77 µs; `A005_ideal_HPC` has maxima about 98.0–99.8 µs, leaving as little as about 0.19 µs margin. The artificial all-ideal timing has substantially different brake latency; it is diagnostic only. Full per-flow/receptor metrics and camera-image metrics remain in each run JSON.", "", "## Interpretation boundary", "", "The result supports a strong association between local-gate time drift and the residual HPC/TC4 growth: changing only HPC's gate to simulation time removes that queue's growth, while gPTP, applications, CBS and downstream gate references stay fixed. Changing only HPC is therefore sufficient to explain this particular HPC residual, but not the remaining CSW/downstream queue behavior. The observed number of gate cycles and queue service are consistent with the application/gate phase-rate mismatch; the existing events do not prove packet-by-packet gate rejection or eliminate every accounting residual. A future C4-only study could compare a gate timebase disciplined to simulation/app time or compensate the cycle phase/rate, but that would be a new design variant requiring explicit protocol review. It must not change app clocks or be treated as a validated fix. The results do not validate C4, do not establish continuous synchronization, and do not pass stability.", ""]
    (OUT/"analysis.md").write_text("\n".join(lines),encoding="utf-8")
    # Store a compact manifest so future regenerations retain their provenance.
    result_json=OUT/"diagnostic_results.json"
    final=json.loads(result_json.read_text())
    artifact_files=("analyze_diagnostic.py","sort_event_trace.py","run_diagnostic_executed.py","run_diagnostic.py","runner_core.py","pilot.ini","protocol.md","README.md")
    final["analysis_artifacts"]={name:{"sha256":sha256_file(HERE/name),"bytes":(HERE/name).stat().st_size} for name in artifact_files if (HERE/name).is_file()}
    final["trace_artifacts"]={}
    for run in results:
        event_path=HERE/run["event_file"]; cycle_path=HERE/run["per_cycle_file"]
        clock_path=event_path.parent/"clock_offsets.csv.gz"
        final["trace_artifacts"][run["execution_id"]]={
            "event_trace_path":str(event_path.relative_to(HERE)),"event_trace_sha256":sha256_file(event_path),"event_trace_bytes":event_path.stat().st_size,"event_trace_records":run["event_records"],"event_order_nonmonotonic_rows":run["event_order_nonmonotonic_rows"],
            "per_cycle_path":str(cycle_path.relative_to(HERE)),"per_cycle_sha256":sha256_file(cycle_path),"per_cycle_bytes":cycle_path.stat().st_size,
            "periodic_clock_offsets_path":str(clock_path.relative_to(HERE)),"periodic_clock_offsets_sha256":sha256_file(clock_path),"periodic_clock_offsets_bytes":clock_path.stat().st_size}
    final["execution_status"]={"phase":"completed_recovered","methodological_simulations":3,"technical_attempts":4,"active_simulations":0,"completed_simulations":3,"rejected_methodological_runs":0,"recovered_postprocessing_failures_without_resimulation":3}
    final["result_artifacts"]={name:{"sha256":sha256_file(OUT/name),"bytes":(OUT/name).stat().st_size} for name in ("analysis.md","hpc_tc4_occupancy.svg","checkpoint.json","runs.jsonl","technical_attempts.jsonl","recovery_events.jsonl","raw_retention.json") if (OUT/name).is_file()}
    result_json.write_text(json.dumps(final,indent=2,ensure_ascii=False)+"\n")
    print(f"Wrote analysis for {len(results)} executions; see {OUT/'analysis.md'}")

if __name__=="__main__": main()
