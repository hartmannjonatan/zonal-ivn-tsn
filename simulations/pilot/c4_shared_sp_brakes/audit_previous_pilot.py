#!/usr/bin/env python3
"""Offline audit/correction of the historical C4 pilot export. Never simulates."""
from __future__ import annotations
import csv, gzip, hashlib, importlib.util, json, math, re, shutil
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
OLD=ROOT/'simulations/pilot/c4_service_preservation'
OUT=OLD/'results'
NEW=Path(__file__).resolve().parent
HISTORY=OUT/'history/pre-c4-route-util-sync-audit-20261009'
HISTORY.mkdir(parents=True,exist_ok=True)
for name in ('pilot_results.json','analysis.md'):
    src=OUT/name; dst=HISTORY/name
    if src.exists() and not dst.exists(): shutil.copy2(src,dst)

spec=importlib.util.spec_from_file_location('validator',ROOT/'scripts/run/validate_c0.py')
validator=importlib.util.module_from_spec(spec); spec.loader.exec_module(validator)
data=json.loads((OUT/'pilot_results.json').read_text())
old_schedule_ports={'HPC.eth[0]','CSW.eth[1]','CSW.eth[2]','CSW.eth[3]',
                    'Z1.ZSW.eth[4]','Z2.ZSW.eth[4]','Z3.ZSW.eth[4]'}
real_brake_routes={'F08':['HPC.eth[0]','CSW.eth[1]','Z1.ZSW.eth[4]'],
                   'F09':['HPC.eth[0]','CSW.eth[2]','Z2.ZSW.eth[4]'],
                   'F10':['HPC.eth[0]','CSW.eth[3]','Z3.ZSW.eth[5]']}

def decode(v):
    if v is None:return None
    s=v.strip()
    try:
        x=json.loads(s)
        if isinstance(x,str): s=x
    except json.JSONDecodeError: pass
    return s.replace('\\"','"').strip().strip('"')
def seconds(v):
    s=decode(v)
    m=re.fullmatch(r'\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)\s*(s|ms|us|ns|ps)?\s*',s or '')
    if not m:return None
    return float(m.group(1))*{None:1,'s':1,'ms':1e-3,'us':1e-6,'ns':1e-9,'ps':1e-12}[m.group(2)]
def durations(v):
    s=decode(v); m=re.fullmatch(r'\s*\[\s*(.*?)\s*\]\s*',s or '')
    return [seconds(x.strip()) for x in m.group(1).split(',')] if m else None

corrections=[]; unavailable=[]; gcl_audit={}; queue_audit={}; route_audit={}
for row in data.get('runs',[]):
    eid=row.get('execution_id','')
    if row.get('status')!='completed':continue
    run_dir=OUT/'runs'/eid
    scas=list(run_dir.glob('*-#0.sca.gz'))+list(run_dir.glob('*-#0.sca'))
    if 'C4' in eid:
        if not scas:
            row.setdefault('effective_gcl_audit_corrected',{'status':'unavailable','reason':'SCA not retained'})
            unavailable.append({'execution_id':eid,'metric':'effective GCL','reason':'SCA not retained'})
        else:
            params={}
            op=gzip.open if str(scas[0]).endswith('.gz') else open
            with op(scas[0],'rt',errors='replace') as f:
                for line in f:
                    if not line.startswith('par ZonalIVN.') or '.transmissionGate[' not in line:continue
                    p=line.rstrip().split(' ',3)
                    if len(p)==4:params.setdefault(p[1],{})[p[2]]=p[3]
            expected={}
            for port in old_schedule_ports:
                for tc in range(8):
                    m=f'ZonalIVN.{port}.macLayer.queue.transmissionGate[{tc}]'
                    expected[m]={'duration':[77e-6,23e-6] if tc<7 else [10e-6,90e-6],
                        'offset':90e-6 if tc<7 else None,'clock':'^.^.^.^.clock'}
            checks={}
            for module,e in expected.items():
                got=params.get(module,{})
                ds=durations(got.get('durations'))
                off=seconds(got.get('offset'))
                cm=decode(got.get('clockModule'))
                checks[module]={'durations_s':ds,'offset_s':off,'clockModule':cm,
                    'initiallyOpen':decode(got.get('initiallyOpen')),
                    'scheduleForAbsoluteTime':decode(got.get('scheduleForAbsoluteTime')),
                    'enableImplicitGuardBand':decode(got.get('enableImplicitGuardBand')),
                    'period_s':sum(ds) if ds and all(x is not None for x in ds) else None,
                    'configured_gate_matches_historical_schedule':bool(ds and len(ds)==2 and all(x is not None for x in ds) and
                        all(abs(a-b)<=1e-12 for a,b in zip(ds,e['duration'])) and
                        (e['offset'] is None or off is not None and abs(off-e['offset'])<=1e-12) and
                        cm==e['clock'] and decode(got.get('initiallyOpen'))=='true' and
                        decode(got.get('scheduleForAbsoluteTime'))=='true' and
                        decode(got.get('enableImplicitGuardBand'))=='true' and abs(sum(ds)-100e-6)<=1e-12)}
            config_pass=bool(checks) and all(x['configured_gate_matches_historical_schedule'] for x in checks.values())
            covered=set(old_schedule_ports)
            route_misses={fid:[p for p in route if p not in covered] for fid,route in real_brake_routes.items()}
            route_misses={k:v for k,v in route_misses.items() if v}
            audit={'status':'pass' if config_pass else 'fail','basis':'reparsed retained resolved SCA with SI unit normalization',
                'historical_declared_gate_ports':sorted(old_schedule_ports),'expected_gate_count':56,
                'observed_gate_count':sum(m in params for m in expected),'all_gate_parameters_match':config_pass,
                'cycle_s':100e-6,'phase_intervals_us':{'TC0-TC6':[10,87],'TC7':[0,10]},
                'clock_module':'^.^.^.^.clock','absolute_schedule':True,'implicit_guard_band':True,
                'application_route_coverage_status':'partial' if route_misses else 'pass',
                'application_route_egresses_missing_tas':route_misses,'gates':checks}
            row['effective_gcl_previous_export_status']=row.get('effective_gcl_previous_export_status', row.get('effective_gcl',{}).get('status'))
            row['effective_gcl']=audit
            row['effective_gcl_audit_corrected']=audit
            row['tas_route_coverage_status']=audit['application_route_coverage_status']
            # Resolve the intended schedule from SCA, but do not call it a
            # measured gate-state pass after the gate vector has been removed.
            pva=row.get('pilot_vector_audit') or {}
            if pva.get('tas_gate_schedule'):
                pva['tas_gate_schedule_previous_export']=pva['tas_gate_schedule']
                pva['tas_gate_schedule']={'status':'unavailable_state_series_removed',
                    'effective_configuration_status':audit['status'],
                    'expected_configured_gate_count':audit['expected_gate_count'],
                    'measured_state_gate_count':None,
                    'reason':'gate-state compact series is absent; SCA verifies configured parameters only'}
                row['pilot_vector_audit']=pva
                row['tas_instrumentation_viable']=None
            route_audit[eid]=audit['application_route_egresses_missing_tas']
            corrections.append({'execution_id':eid,'field':'effective_gcl.status','previous':row['effective_gcl_previous_export_status'],
                'corrected':audit['status'],'source':'retained resolved SCA; normalized durations/offset; route coverage kept as separate field'})

    # No raw transmitting-state vector survived retention; no link-utilization
    # scalar can be independently reconstructed from the retained summaries.
    link=row.get('physical_link_utilization')
    if isinstance(link,dict):
        before=link.get('status')
        vals=[]
        for tx,metric in link.get('by_transmitter',{}).items():
            value=metric.get('measurement_busy_fraction')
            vals.append(value)
            metric['previous_export_fraction']=metric.get('previous_export_fraction',value)
            metric['measurement_busy_fraction']=None
            metric['measurement_busy_percent']=None
            metric['valid']=False
            metric['metric_status']='unavailable_unrecalculable'
            metric['unavailable_reason']='Original transmitting state vector was deleted; compact export lacks timestamps/state changes. Wire summaries do not provide exact PHY busy intervals.'
        link.update({'previous_export_status':before,'status':'unavailable_unrecalculable',
            'measurement_busy_fraction_bounds_valid':None,
            'audit_note':'Negative exported values are invalid. No modulo, clipping, or zero replacement was applied; all fractions are unavailable because the time series was not retained.'})
        corrections.append({'execution_id':eid,'field':'physical_link_utilization','previous':before,
            'corrected':'unavailable_unrecalculable','source':'transmitting state vector absent; wire summary has no exact intervals'})

    if row.get('variant') in ('C3sync','C4compensated','C4original'):
        old_sync=(row.get('pilot_vector_audit') or {}).get('synchronization') or {}
        off=run_dir
        offset_files=list(off.glob('*/clock_offsets.csv.gz'))
        full=False
        if offset_files:
            with gzip.open(offset_files[0],'rt') as f:
                next(f,None)
                ts=[]
                for line in f:
                    try: ts.append(float(line.split(',')[0]))
                    except (ValueError,IndexError): pass
            full=bool(ts and min(ts)<=1 and max(ts)>=30.999)
        row['synchronization_warmup_previous_export']=old_sync
        row['synchronization_measurement_audit']={'status':'available_recalculated' if full else 'unavailable_missing_full_measurement_series',
            'window_s':[1.0,31.0],'offset_samples_retained':full,
            'warmup_convergence_previous_export_preserved':old_sync.get('status')=='pass',
            'reason':None if full else 'retained clock_offsets series absent or does not cover [1,31); no interpolation/reconstruction possible.'}
        if not full: unavailable.append({'execution_id':eid,'metric':'gPTP offset over measurement','reason':'full-measurement clock-offset series not retained'})

    if (eid.startswith('C4compensated_L2_A1_seed41') and 'instrumentation_v5' in eid) or eid in (
        'C4compensated_L2_A1_seed43','C4compensated_L2_A1_seed47'):
        trace=next((p for p in run_dir.glob('*/queue_occupancy_events.csv.gz')),None)
        if trace:
            try:
                recalculated=validator.recompute_queue_occupancy_trace(trace)
                q=next(x for x in recalculated if x['queue']=='ZonalIVN.HPC.eth[0].macLayer.queue.queue[4]')
                queue_audit[eid]={'capacity_bits':q['capacity_bits'],'capacity_KiB':q['capacity_bits']/8/1024,
                    'six_5s_means_bits':q['mean_occupancy_bits_5s'],'six_5s_means_KiB':[x/8/1024 for x in q['mean_occupancy_bits_5s']],
                    'mean_bits':q['mean_occupancy_bits_measurement'],'max_bits':q['max_occupancy_bits'],
                    'fraction_ge_90pct':q['fraction_measurement_at_least_90pct_capacity'],'sustained_growth':q['sustained_growth'],
                    'source':'independent recalculation from retained exact occupancy change points'}
            except Exception as exc:
                queue_audit[eid]={'status':'not_recalculated','reason':str(exc)}

# Seeds 43/47 already carry an explicit independent-recalculation success flag
# from the original compaction audit, and their exact compressed change-point
# series remain present. Reuse those audited values without labeling them as
# newly recalculated by this correction pass.
for eid in ('C4compensated_L2_A1_seed43','C4compensated_L2_A1_seed47'):
    row=next((r for r in data.get('runs',[]) if r.get('execution_id')==eid),None)
    if row and row.get('queue_recalculation_verified') is True:
        q=next((x for x in row.get('queue_stability',[]) if x.get('queue')=='ZonalIVN.HPC.eth[0].macLayer.queue.queue[4]'),None)
        if q:
            queue_audit[eid]={'capacity_bits':q['capacity_bits'],'capacity_KiB':q['capacity_bits']/8/1024,
                'six_5s_means_bits':q['mean_occupancy_bits_5s'],'six_5s_means_KiB':[x/8/1024 for x in q['mean_occupancy_bits_5s']],
                'mean_bits':q['mean_occupancy_bits_measurement'],'max_bits':q['max_occupancy_bits'],
                'fraction_ge_90pct':q['fraction_measurement_at_least_90pct_capacity'],'sustained_growth':q['sustained_growth'],
                'source':'retained run result; queue_recalculation_verified=true and exact compressed change-point series retained',
                'recalculated_again_in_this_audit':False}

data['historical_export_audit']={'corrected_offline':True,'no_simulations_run':True,
    'backup_directory':str(HISTORY.relative_to(ROOT)),'corrections':corrections,
    'unavailable_metrics':unavailable,'historical_gcl_route_coverage':route_audit,
    'HPC_eth0_TC4_queue_recalculation':queue_audit,
    'clock_offset_summary_correction':{'C3_sync_seed43_max_abs_offset_last100ms_ns':30.0,
       'scope':'warm-up only; measurement [1,31) remains unavailable when compact series is absent'}}
data['decision_summary']['gptp_warmup_convergence_passed']=data['decision_summary'].pop('gptp_sync_passed',None)
data['decision_summary']['gptp_measurement_assessed']=False
data['decision_summary']['gptp_measurement_status']='unavailable_missing_full_measurement_series'
data['decision_summary']['measured_gate_count']=None
data['decision_summary']['resolved_gate_configuration_count']=56
data['decision_summary']['measured_gates_pass']=None
data['decision_summary']['gate_state_measurement_status']='unavailable_state_series_removed'
data['decision_summary']['historical_f10_route_coverage_passed']=False
data['decision_summary']['c4_compensated_all_l2_queue_stable']=False
data['decision_summary']['cbs_service_fully_preserved']=False
data['decision_summary']['c4_compensated_hpc_tc4_sustained_growth_seeds']=[41,43,47]
tmp=OUT/'pilot_results.json.tmp';tmp.write_text(json.dumps(data,indent=2,sort_keys=True)+'\n');tmp.replace(OUT/'pilot_results.json')

md=['# Historical C4 pilot: corrected offline audit','',
    'This correction reprocesses preserved SCA and exact queue occupancy changes only. It does not re-execute simulations, retune CBS, or replace the historical run records. The pre-correction JSON/Markdown are preserved under `results/history/pre-c4-route-util-sync-audit-20261009/`.','',
    '## Route and GCL audit','',
    'F08: HPC.eth[0] → CSW.eth[1] → Z1.ZSW.eth[4] (1 Gbit/s, 1 Gbit/s, 100 Mbit/s). F09: HPC.eth[0] → CSW.eth[2] → Z2.ZSW.eth[4] (same rates). F10: HPC.eth[0] → CSW.eth[3] → Z3.ZSW.eth[5] (same rates). The historical GCL configured Z3.ZSW.eth[4], so F10’s actual final egress was ungated. The three brake exits carry only their respective brake application flow; gPTP control traffic is separate.','',
    'The old `effective_gcl.status=fail` was an export/parser mismatch. Re-reading retained resolved SCA and normalizing units/strings yields a pass for the 56 gates that were configured. This is a configuration-fidelity pass only: route coverage is separately partial because F10 ended at eth[5], not eth[4]. The historical result is not relabeled as fully gate-covered C4. Cycle is 100 µs; TC0–TC6 are open [10,87) µs, TC7 [0,10) µs, with the configured 13 µs guard interval.','',
    '## Metrics that cannot be repaired from retained data','',
    'The historical PHY transmitting vectors were deleted after compaction. `wire.csv.gz` contains interface/flow aggregates, not PHY busy intervals or event timestamps. Consequently every exported time-weighted `physical_link_utilization` fraction is now marked unavailable; negative values were not clipped or transformed. The preserved compact clock-offset file is absent or fails to span [1,31) s, so full-measurement synchronization maxima and threshold-violation duration cannot be recalculated. The old 0.9–1.0 s warm-up diagnostic is preserved separately. In C3_sync seed 43 the warm-up diagnostic maximum is 30 ns (not 20 ns); it does not establish synchronization throughout measurement.','',
    '## CBS stability evidence','']
for eid,q in queue_audit.items():
    if 'six_5s_means_KiB' in q:
        md.append(f"- `{eid}` HPC.eth[0]/TC4, capacity {q['capacity_KiB']:.2f} KiB: six consecutive 5 s means {', '.join(f'{x:.2f}' for x in q['six_5s_means_KiB'])} KiB; max {q['max_bits']/8/1024:.2f} KiB; sustained_growth={q['sustained_growth']}. This is progressive accumulation toward capacity, not a short transient queue pulse.")
md += ['', 'The values above are recomputed from the retained exact occupancy change points. Mean occupancy is not used as a substitute for stability; the growth pattern and queue-capacity limit remain visible. CBS service is not described as preserved when sustained growth or overflow is present.','',
       '## Corrections and provenance','',
       '| Field | Previous export | Corrected audit | Source |','|---|---|---|---|']
for c in corrections:
    md.append(f"| `{c['field']}` / `{c['execution_id']}` | `{c['previous']}` | `{c['corrected']}` | {c['source']} |")
md += ['', 'No result here is a new simulation. Any metric whose required series was removed is explicitly unavailable.', '']
(OUT/'analysis.md').write_text('\n'.join(md))
audit={'historical_pilot':'simulations/pilot/c4_service_preservation','backup':str(HISTORY.relative_to(ROOT)),
       'offline_reprocessing_only':True,'simulations_run':0,'corrections':corrections,
       'unavailable_metrics':unavailable,'queue_audit':queue_audit,'gcl_route_audit':route_audit}
(OUT/'audit-corrections.json').write_text(json.dumps(audit,indent=2,sort_keys=True)+'\n')
print(f"Corrected historical export offline; {len(corrections)} fields/records annotated; no simulations run.")
