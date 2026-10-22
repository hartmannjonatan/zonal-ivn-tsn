#!/usr/bin/env python3
"""Recompute queue packet service and credit/gate timing from preserved pilot series."""
from __future__ import annotations

import csv, gzip, json
from collections import defaultdict
from pathlib import Path

HERE=Path(__file__).resolve().parent
RESULTS=HERE/'results'
START,END=1.0,31.0
RUNS={
    'C3_sync':'C3_sync_L2_A1_seed41_service_events_v3',
    'C4_reference':'C4_reference_L2_A1_seed41_service_events_v2',
}
TARGETS={
    'HPC.eth[0]/TC4':'ZonalIVN.HPC.eth[0].macLayer.queue.queue[4]',
    'CSW.eth[1]/TC4':'ZonalIVN.CSW.eth[1].macLayer.queue.queue[4]',
    'CSW.eth[2]/TC4':'ZonalIVN.CSW.eth[2].macLayer.queue.queue[4]',
    'CSW.eth[3]/TC4':'ZonalIVN.CSW.eth[3].macLayer.queue.queue[4]',
    'Z1.ZSW.eth[7]/TC4':'ZonalIVN.Z1.ZSW.eth[7].macLayer.queue.queue[4]',
    'Z2.ZSW.eth[7]/TC4':'ZonalIVN.Z2.ZSW.eth[7].macLayer.queue.queue[4]',
    'Z3.ZSW.eth[7]/TC4':'ZonalIVN.Z3.ZSW.eth[7].macLayer.queue.queue[4]',
}
TAS_PORTS=('HPC.eth[0]','CSW.eth[1]','CSW.eth[2]','CSW.eth[3]')
STAT_NAMES={'incomingPacketLengths':'incoming','outgoingPacketLengths':'outgoing','droppedPacketLengthsQueueOverflow':'drops'}

def iter_csv_gz(path):
    with gzip.open(path,'rt',newline='') as f:
        yield from csv.DictReader(f)

def integrate_states(rows, module_field, state_field, initial_by_module, start=START,end=END):
    """Integrate right-continuous transition state; preserves input order at equal timestamps."""
    by=defaultdict(list)
    for row in rows:
        module=row[module_field]
        t=float(row['simtime_s'])
        if start <= t < end:
            by[module].append((t,int(float(row[state_field]))))
    out={}
    for module,events in by.items():
        state=int(initial_by_module.get(module,0)); prev=start; area=0.0
        for t,value in events:
            if t>prev and state: area+=t-prev
            state=value; prev=t
        if end>prev and state: area+=end-prev
        out[module]=area
    return out

def analyze_run(run_id, is_reference=False):
    root=RESULTS/'runs'/run_id
    run_dir=root/f"Pilot_{'C3sync' if not is_reference else 'C4compensated'}_L2_A1-0"
    service=run_dir/'service_and_wire_events.csv.gz'
    if not service.is_file(): raise FileNotFoundError(service)
    acc={key:{'counts':{s:0 for s in ('incoming','outgoing','drops')},'bits':{s:0.0 for s in ('incoming','outgoing','drops')}} for key in TARGETS}
    module_to_key={v:k for k,v in TARGETS.items()}
    link_busy=defaultdict(float); link_last={}; link_prev_time={}
    with gzip.open(service,'rt',newline='') as f:
        for row in csv.DictReader(f):
            t=float(row['simtime_s']); mod=row['module']; stat=row['statistic'].split(':',1)[0]; val=float(row['value'])
            if START <= t < END and mod in module_to_key and stat in STAT_NAMES:
                kind=STAT_NAMES[stat]; a=acc[module_to_key[mod]]
                a['counts'][kind]+=1; a['bits'][kind]+=val
            if mod.endswith('.phyLayer.transmitter') and stat=='transmitting':
                if mod in link_last and t>link_prev_time[mod] and START < t:
                    left=max(START,link_prev_time[mod]); right=min(END,t)
                    if right>left and link_last[mod]: link_busy[mod]+=right-left
                if START <= t < END:
                    link_last[mod]=int(val);link_prev_time[mod]=t
                elif t < START:
                    link_last[mod]=int(val);link_prev_time[mod]=t
    # Queue index metadata gives the module/capacity mapping. Recompute the
    # left-limit occupancy at both half-open measurement boundaries.
    meta=json.loads(gzip.open(run_dir/'queue_occupancy_events.csv.gz.meta.json.gz','rt').read())
    qmap={x['module']:x for x in meta['queues']}
    qkeys=set(TARGETS.values()); qindexes={qmap[m]['queue_index']:m for m in qkeys}
    occupancy={m:{'before_start':0.0,'before_end':0.0} for m in qkeys}
    with gzip.open(run_dir/'queue_occupancy_events.csv.gz','rt',newline='') as f:
        for row in csv.DictReader(f):
            qi=int(row['queue_index']); m=qindexes.get(qi)
            if m is None: continue
            t=float(row['timestamp_s']);v=float(row['occupancy_bits'])
            if t<START: occupancy[m]['before_start']=v
            if t<END: occupancy[m]['before_end']=v
    queues={}
    for key,module in TARGETS.items():
        a=acc[key];q=occupancy[module];delta=q['before_end']-q['before_start']
        predicted=a['bits']['incoming']-a['bits']['outgoing']-a['bits']['drops']
        queues[key]={**a,'occupancy_bits_start_left_limit':q['before_start'],'occupancy_bits_end_left_limit':q['before_end'],
            'occupancy_delta_bits':delta,'conservation_residual_bits':delta-predicted,
            'capacity_bits':qmap[module]['capacity_bits'],
            'incoming_rate_bps':a['bits']['incoming']/(END-START),
            'outgoing_rate_bps':a['bits']['outgoing']/(END-START),
            'drop_rate_bps':a['bits']['drops']/(END-START),
            'conservation_check':'pass' if abs(delta-predicted)<=1e-6 else 'review'}
    # Gate/guard intervals are already retained as compact state transitions.
    gate_path=run_dir/'gate_states.csv.gz';guard_path=run_dir/'guard_band_states.csv.gz'
    gate_rows=list(iter_csv_gz(gate_path));guard_rows=list(iter_csv_gz(guard_path))
    initial_gate={f'ZonalIVN.{port}.macLayer.queue.transmissionGate[4]':1 for port in ('HPC.eth[0]','CSW.eth[1]','CSW.eth[2]','CSW.eth[3]')}
    open_s=integrate_states(gate_rows,'module','state_open',initial_gate)
    # Guard vectors encode active=true; false is the no-guard state.
    guard_s=integrate_states(guard_rows,'module','guard_band_on',{}) if guard_rows and 'guard_band_on' in guard_rows[0] else {}
    gate_timing={}
    for key in ('HPC.eth[0]/TC4','CSW.eth[1]/TC4','CSW.eth[2]/TC4','CSW.eth[3]/TC4'):
        gm='ZonalIVN.'+key.split('/')[0]+'.macLayer.queue.transmissionGate[4]'
        gs=open_s.get(gm)
        gr=guard_s.get(gm)
        gate_timing[key]={'open_seconds_observed':gs,'open_fraction_observed':gs/(END-START) if gs is not None else None,
            'guard_seconds_observed':gr,'credit_positive_eligible_fraction_estimate':(gs-gr)/(END-START) if gs is not None and gr is not None else None,
            'status':'measured_from_state_vectors' if gs is not None and gr is not None else 'partial_or_unavailable'}
    for module,state in link_last.items():
        left=max(START,link_prev_time[module])
        if END>left and state: link_busy[module]+=END-left
    # Credit vectors are change points; integrate each previous value over its
    # hold interval and classify the observed derivative. Equal-time changes
    # are retained in input order but contribute no duration.
    credit_prev={};credit_stats=defaultdict(lambda:{'positive_seconds':0.0,'negative_seconds':0.0,'flat_seconds':0.0,
        'positive_credit_bits':0.0,'negative_credit_bits':0.0,'positive_slopes_bps':[],'negative_slopes_bps':[]})
    other=run_dir/'pilot_other_vectors.csv.gz'
    for row in iter_csv_gz(other):
        vec=row['vector']; t=float(row['simtime_s'])
        if not vec.endswith('.numCredits:vector'): continue
        module=vec.removesuffix('.numCredits:vector')
        if module not in {f"ZonalIVN.{e}.macLayer.queue.transmissionSelectionAlgorithm[4]" for e in TAS_PORTS}:
            continue
        value=float(row['value']); prev=credit_prev.get(module)
        if prev is not None:
            pt,pv=prev
            left=max(START,pt);right=min(END,t)
            if right>left:
                slope=(value-pv)/(t-pt) if t>pt else 0.0
                summary=credit_stats[module]
                if slope>1.0:
                    summary['positive_seconds']+=right-left;summary['positive_credit_bits']+=max(0,value-pv);summary['positive_slopes_bps'].append(slope)
                elif slope< -1.0:
                    summary['negative_seconds']+=right-left;summary['negative_credit_bits']+=max(0,pv-value);summary['negative_slopes_bps'].append(slope)
                else: summary['flat_seconds']+=right-left
        credit_prev[module]=(t,value)
    credit_summary={}
    for module,values in credit_stats.items():
        x=dict(values)
        for k in ('positive_slopes_bps','negative_slopes_bps'):
            arr=x[k];x[k+'_median']=sorted(arr)[len(arr)//2] if arr else None
            x[k+'_sample_count']=len(arr);x.pop(k)
        credit_summary[module]=x
    physical_busy={m:{'busy_seconds':v,'busy_fraction':v/(END-START)} for m,v in link_busy.items()}
    # Keep direct control result flags as the authoritative P1 application/queue gates.
    report=json.loads((root/'pilot-result.json').read_text())
    return {'execution_id':run_id,'variant':report.get('variant_id'),'seed':report.get('seed'),'cell':report.get('cell'),
        'calendar_sha256':report.get('calendar_sha256'),'calendar_paired':report.get('calendar_paired'),
        'simulation_valid':report.get('simulation_valid'),'application_viable':report.get('application_viable'),
        'stability_viable':report.get('stability_viable'),'synchronization_sampled':report.get('synchronization_viability_status'),
        'continuous_synchronization':'unverified','effective_gcl':report.get('effective_gcl',{}).get('status'),
        'dropped_packets':report.get('dropped_packets'), 'drops_by_interface':report.get('drops_by_interface'),
        'queue_stability':report.get('queue_stability'), 'queues':queues,'gate_timing':gate_timing,
        'credit_evolution':credit_summary,
        'physical_link_busy':physical_busy if physical_busy else None,
        'physical_link_busy_status':'unavailable_selector_mismatch_in_completed_controls' if not physical_busy else 'recomputed_from_retained_transmitting_state',
        'evidence':{'service_events':str(service.relative_to(HERE)),'queue_occupancy':str((run_dir/'queue_occupancy_events.csv.gz').relative_to(HERE)),
                    'gate_states':str(gate_path.relative_to(HERE)),'guard_band_states':str(guard_path.relative_to(HERE)),
                    'pilot_other_vectors':str((run_dir/'pilot_other_vectors.csv.gz').relative_to(HERE))}}

if __name__=='__main__':
    data={'exploratory':True,'official_c4_frozen':False,'measurement_window_s':[START,END],
          'measurement_interval_convention':'half-open [1,31); queue boundaries are the left limit immediately before each boundary event.',
          'bit_unit':'packet queue data length in bits as emitted by INET packet length vectors; IFG/preamble are not added to queue-data service.',
          'runs':{name:analyze_run(eid,name=='C4_reference') for name,eid in RUNS.items()}}
    out=RESULTS/'mechanism_audit_controls.json';out.write_text(json.dumps(data,indent=2)+'\n')
    for name,row in data['runs'].items():
        print(name,row['simulation_valid'],row['application_viable'],row['stability_viable'],row['calendar_sha256'])
        for q,v in row['queues'].items():print(q,round(v['incoming_rate_bps']/1e6,3),round(v['outgoing_rate_bps']/1e6,3),v['counts'],round(v['conservation_residual_bits'],3),v['conservation_check'])
        print('gate',row['gate_timing'])
    print('wrote',out)
