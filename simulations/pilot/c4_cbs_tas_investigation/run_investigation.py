#!/usr/bin/env python3
"""Staged isolated C4 service audit; no official result path is modified."""
from __future__ import annotations
import argparse, csv, gzip, hashlib, importlib.util, json, math, os, shutil, sys, time
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
SIM=ROOT/'simulations'
OLD=SIM/'pilot/c4_shared_sp_brakes'
OUT=HERE/'results'
REGISTRY=HERE/'candidate_registry.json'
ACTIVE_SPEC={}

spec=importlib.util.spec_from_file_location('isolated_c4_runner_core',HERE/'runner_core.py')
r=importlib.util.module_from_spec(spec); sys.modules[spec.name]=r; spec.loader.exec_module(r)
r.ROOT=ROOT; r.SIM=SIM; r.HERE=HERE; r.OUT=OUT
r.PILOT_INI=HERE/'pilot.ini'; r.PROTOCOL=HERE/'protocol.md'
r.PROFILE_JSON=SIM/'campaigns/p1-v2-official-2026-10/results/calibration/C3_calibration.json'
r.PROFILE_CHECKPOINT=SIM/'campaigns/p1-v2-official-2026-10/results/progress.json'
r.P1_PDF=ROOT/'docs/design/P1-v4.pdf'
r.MAX_JOBS=1; r.FREE_FLOOR_GB=45.0

TAS=sorted(r.TAS_EGRESSES)
QUEUE_MODULES=[f'ZonalIVN.{e}.macLayer.queue.queue[4]' for e in TAS]
QUEUE_MODULES += [f'ZonalIVN.{z}.ZSW.eth[7].macLayer.queue.queue[4]' for z in ('Z1','Z2','Z3')]
# In INET 4.7.0 the transmitter is a direct submodule of eth[]; it is not
# nested below macLayer. Keep the selector aligned with the installed NED.
LINK_MODULES=[f'ZonalIVN.{e}.phyLayer.transmitter' for e in TAS]
LINK_MODULES += ['ZonalIVN.Z3.ZSW.eth[7].phyLayer.transmitter']
ORIG_PROFILE=r.run_profile_for_load
ORIG_OVERRIDES=r.simulation_overrides
ORIG_PLAN=r.run_plan
ORIG_RUN_ONE=r.run_one
ORIG_SIMULATE_RAW_RUN=r.simulate_raw_run
ORIG_COMPRESS=r.compress_or_remove_raw
CURRENT_PHASE='controls'


def current_candidate():
    return ACTIVE_SPEC.get('candidate_id')


def profile_for_load(manifest, load, variant):
    base=ORIG_PROFILE(manifest,load,variant)
    cid=current_candidate()
    if variant!='C4compensated' or cid in (None,'C4_reference'):
        return base
    registry=json.loads(REGISTRY.read_text())
    item=next((x for x in registry.get('candidates',[]) if x['candidate_id']==cid),None)
    if not item or item.get('status')!='registered':
        raise RuntimeError(f'Candidate {cid} is absent or not registered')
    result=dict(base)
    for key,mult in item.get('multipliers_by_queue',{}).items():
        e,tc_text=key.rsplit('/TC',1); key_tuple=(e,int(tc_text))
        if key_tuple not in result:
            raise RuntimeError(f'{cid} attempts to alter queue outside C4 CBS reference: {key}')
        result[key_tuple]=round(result[key_tuple]*float(mult))
    return result

r.run_profile_for_load=profile_for_load

def simulate_raw_run_for_candidate(spec0,manifest):
    # The effective profile is resolved while constructing the OMNeT++ command,
    # before run_one() is called. Bind the candidate ID for that entire step.
    ACTIVE_SPEC.clear(); ACTIVE_SPEC.update(spec0)
    try:
        return ORIG_SIMULATE_RAW_RUN(spec0,manifest)
    finally:
        ACTIVE_SPEC.clear()

r.simulate_raw_run=simulate_raw_run_for_candidate


def completed_raw_run_matches(dest, config, seed):
    """Also recognize the exact completed isolated-run input path.

    The inherited runner's recovery predicate hard-coded the historical pilot
    INI path. This pilot copies that configuration into its own directory, so
    use the actual isolated path while retaining all completion checks.
    """
    sca=dest/f'{config}-#0.sca'; vec=dest/f'{config}-#0.vec'; log=dest/f'{config}.log'
    run_dir=dest/f'{config}-0'
    required=(sca,vec,log,run_dir/'events.csv',run_dir/'releases.csv')
    if not all(p.is_file() and p.stat().st_size>0 for p in required): return False
    attrs={k:v for k,v in __import__('re').findall(r'^attr (\S+) (.*)$',sca.read_text(errors='replace'),__import__('re').MULTILINE)}
    log_text=log.read_text(errors='replace')
    return (attrs.get('configname')==config and attrs.get('seedset')==str(seed)
      and attrs.get('inifile')=='pilot/c4_cbs_tas_investigation/pilot.ini'
      and 'Simulation time limit reached -- at t=31.05s' in log_text
      and 'Calling finish() at end of Run #0...' in log_text
      and '<!> Error:' not in log_text)

r.completed_raw_run_matches=completed_raw_run_matches


def extra_vectors(spec0,manifest):
    config,dest,extras=ORIG_OVERRIDES(spec0,manifest)
    # Keep the existing end-to-end queue/application metrics. Add packet-sized
    # admission/removal vectors only at the seven queues that can explain the
    # recorded CBS growth, plus physical busy-state transitions on those links.
    for module in QUEUE_MODULES:
        parameter_path='*.'+module.removeprefix('ZonalIVN.')
        for stat in ('incomingPacketLengths','outgoingPacketLengths','droppedPacketLengthsQueueOverflow'):
            extras.append(f'--{parameter_path}.{stat}.result-recording-modes=vector')
    # The native-tick probe observes all five corrected clocks and free clocks
    # simultaneously, emits in event order, and derives offsets before text I/O.
    run_dir=OUT/'runs'/spec0['execution_id']
    trace=run_dir/'clock_precision.csv'
    plugin=HERE/'precision/plugin/libclockprecision.so'
    extras += ['--network=zonal_ivn_tsn.simulations.pilot.c4_cbs_tas_investigation.precision.ZonalIVN',
               f'--*.clockAudit.outputFile="{trace.resolve()}"',
               '--*.clockAudit.sampleInterval=1ms','--*.clockAudit.stopAt=31.05s',
               '-l',str(plugin)]
    return config,dest,extras
r.simulation_overrides=extra_vectors


def parse_service_vectors(dest,config,run_dir):
    vec=dest/f'{config}-#0.vec'
    if not vec.exists() and (dest/f'{config}-#0.vec.gz').exists():
        vec=dest/f'{config}-#0.vec.gz'
    if not vec.exists():
        raise RuntimeError(f'missing raw vector before extraction: {vec}')
    opener=gzip.open if str(vec).endswith('.gz') else open
    defs={}; selected={}
    with opener(vec,'rt',errors='replace') as f:
        for line in f:
            if line.startswith('vector '):
                parts=line.rstrip().split(' ',4)
                if len(parts)==5:
                    vid=int(parts[1]); module=parts[2]; name=parts[3]
                    if module in QUEUE_MODULES and any(n in name for n in ('incomingPacketLengths:','outgoingPacketLengths:','droppedPacketLengthsQueueOverflow:')):
                        defs[vid]=(module,name)
                    elif module in LINK_MODULES and name.startswith('transmitting:'):
                        defs[vid]=(module,name)
            elif line and line[0].isdigit():
                break
    if not defs:
        raise RuntimeError('targeted CBS queue event vectors were not written')
    out=run_dir/'service_and_wire_events.csv.gz'
    with gzip.open(out,'wt',newline='',encoding='utf-8',compresslevel=6) as gz:
        w=csv.writer(gz); w.writerow(('vector_id','event_number','module','statistic','simtime_s','value'))
        with opener(vec,'rt',errors='replace') as f:
            for line in f:
                p=line.split()
                if len(p)!=4 or not p[0].isdigit(): continue
                vid=int(p[0]); info=defs.get(vid)
                if info is None: continue
                module,name=info
                w.writerow((vid,p[1],module,name,p[2],p[3]))
    return out


def credit_vector_review(run_dir):
    """Record limitations and event evidence used for credit-slope inference."""
    return {'credit_vector':str((run_dir/'pilot_other_vectors.csv.gz').relative_to(HERE)),
            'gate_state_vector':str((run_dir/'gate_states.csv.gz').relative_to(HERE)),
            'guard_band_vector':str((run_dir/'guard_band_states.csv.gz').relative_to(HERE)),
            'queue_occupancy_vector':str((run_dir/'queue_occupancy_events.csv.gz').relative_to(HERE)),
            'arrivals_departures_drops_and_phy_busy':str((run_dir/'service_and_wire_events.csv.gz').relative_to(HERE)),
            'rate_reason_method':'Infer gain/spend/freeze intervals from consecutive native simulation-time credit values; cross-check gate, implicit guard-band and PHY transmitting state. The INET internal isInterpacketGap state is not directly exported; negative sendSlope intervals include transmission plus interpacket gap, so individual boundary attribution is not claimed.'}


def analyze_clock_trace(path):
    if not path.is_file(): raise RuntimeError(f'missing direct clock trace: {path}')
    nodes=('CSW','Z1.ZSW','Z2.ZSW','Z3.ZSW')
    vals={n:[] for n in nodes}; maxrows={n:None for n in nodes}; scale=None
    with path.open(newline='') as f:
        for row in csv.DictReader(f):
            if scale is None: scale=int(row['simtime_scale_exp'])
            if row['record_kind']!='periodic': continue
            t=int(row['simtime_raw'])*(10**scale)
            if not (1.0<=t<31.0): continue
            for n in nodes:
                raw=int(row[f'{n}_offset_from_HPC_raw']); vals[n].append(raw)
                if maxrows[n] is None or abs(raw)>abs(maxrows[n]['ticks']):
                    maxrows[n]={'ticks':raw,'simtime_s':row['simtime_exact_s'],'event_number':int(row['event_number'])}
    summaries={}
    for n,arr in vals.items():
        q=sorted(abs(x) for x in arr)
        p99=q[max(0,math.ceil(.99*len(q))-1)] if q else None
        threshold=int(math.ceil(1e-6/(10**scale))) if scale is not None else None
        summaries[n]={'sample_count':len(arr),'sample_interval_s':.001,'p99_abs_s':p99*10**scale if p99 is not None else None,
          'max_abs_s':abs(maxrows[n]['ticks'])*10**scale if maxrows[n] else None,'max_signed_s':maxrows[n]['ticks']*10**scale if maxrows[n] else None,
          'max_time_s':maxrows[n]['simtime_s'] if maxrows[n] else None,'max_event_number':maxrows[n]['event_number'] if maxrows[n] else None,
          'samples_abs_over_1us':sum(abs(x)>threshold for x in arr) if threshold is not None else None,
          'passes_sampled_threshold':bool(arr) and all(abs(x)<=threshold for x in arr) if threshold is not None else None,
          'scale_exp':scale}
    return {'status':'sampled_pass_continuous_unverified' if all(x['passes_sampled_threshold'] for x in summaries.values()) else 'sampled_violation_continuous_unverified',
      'continuous_compliance':'unverified','window_s':[1.0,31.0],'resolution_s':.001,'method':'simultaneous IClock::getClockTime() readings; native tick subtraction before serialization; event-order rows retained; periodic samples only used for the distribution','nodes':summaries}


def patch_current_views():
    """Correct only this pilot's newly generated rows; retain legacy computation as history."""
    p=OUT/'runs.jsonl'
    if not p.exists(): return
    rows=[]
    for line in p.read_text().splitlines():
        try: row=json.loads(line)
        except json.JSONDecodeError: continue
        run_dir=OUT/'runs'/row['execution_id']/f"Pilot_{row['variant']}_{row['cell']}-0"
        trace=OUT/'runs'/row['execution_id']/'clock_precision.csv'
        if trace.exists():
            old=row.setdefault('pilot_vector_audit',{}).get('synchronization')
            if old: row['pilot_vector_audit']['synchronization_historical_invalid_precision_or_interpolation']=old
            sync=analyze_clock_trace(trace)
            row['pilot_vector_audit']['synchronization']=sync
            row['synchronization_viable']=None
            row['synchronization_viability_status']=sync['status']
            row['synchronization_sampled_viable']=(sync['status']=='sampled_pass_continuous_unverified')
            row['synchronization_continuous_viable']=None
            cpath=trace.with_suffix('.csv.gz')
            if not cpath.exists():
                with trace.open('rb') as src,gzip.open(cpath,'wb',compresslevel=6) as dst: shutil.copyfileobj(src,dst)
                trace.unlink()
            row.setdefault('evidence',{})['direct_native_clock_trace']=str(cpath.relative_to(HERE))
            row['credit_service_audit']=credit_vector_review(run_dir)
            service=run_dir/'service_and_wire_events.csv.gz'
            if service.exists():
                row['credit_service_audit']['arrivals_departures_drops_and_phy_busy']=str(service.relative_to(HERE))
                row['service_event_extraction_status']='complete'
                row['physical_link_busy_status']='unavailable_selector_mismatch_in_completed_controls'
                row.setdefault('evidence',{})['service_and_wire_events']=str(service.relative_to(HERE))
            else:
                row['credit_service_audit']['arrivals_departures_drops_and_phy_busy_status']='unavailable_instrumentation_extraction'
                row['service_event_extraction_status']='failed_postprocessing_callback_order'
            row['stability_viable']=(bool(row.get('queue_recalculation_verified')) and not bool(row.get('nonstable_queues')))
            row['application_stability_viable']=(row.get('application_viable') is True and row['stability_viable'] is True)
            row['pilot_viable']=bool(row.get('admissible') is True and row.get('simulation_valid') is True
                and row['application_stability_viable'] is True and row.get('synchronization_sampled_viable') is True
                and row.get('effective_gcl',{}).get('status') in ('pass','not_applicable'))
            # Update immutable per-run result with current and historical sync fields.
            report=OUT/'runs'/row['execution_id']/'pilot-result.json'
            if report.exists(): report.write_text(json.dumps(row,indent=2,ensure_ascii=False)+'\n')
        rows.append(row)
    tmp=p.with_suffix('.jsonl.tmp'); tmp.write_text(''.join(json.dumps(x,separators=(',',':'),ensure_ascii=False)+'\n' for x in rows)); tmp.replace(p)
    # The common historical runner regenerates an interim report. Preserve that
    # output as non-authoritative until this investigation-specific exporter runs.


def plan_for_phase(phase, registry=None):
    def entry(variant,eid,candidate=None,kind='control'):
        x={'execution_id':eid,'variant':variant,'cell':'L2_A1','load_index':2,'alignment':1,'seed':41,'kind':kind,'allow_inadmissible':True}
        if candidate: x['candidate_id']=candidate
        return x
    if phase=='controls':
        a=entry('C3sync','C3_sync_L2_A1_seed41_service_events_v3',None,'technical_replacement')
        b=entry('C4compensated','C4_reference_L2_A1_seed41_service_events_v2','C4_reference','instrumentation_repair')
        a['instrumentation_supersedes']=['C3_sync_L2_A1_seed41']
        b['instrumentation_supersedes']=['C4_reference_L2_A1_seed41']
        return [a,b]
    if phase=='candidates':
        return [entry('C4compensated',f"{x['candidate_id']}_L2_A1_seed41",x['candidate_id'],'candidate') for x in (registry or {}).get('candidates',[]) if x.get('status')=='registered']
    if phase=='verification':
        cid=(registry or {}).get('selected_candidate_id')
        if not cid: return []
        entries=[]
        for seed in (43,47):
            entries += [dict(entry('C3sync',f'C3_sync_L2_A1_seed{seed}',None,'verification'),seed=seed),
                        dict(entry('C4compensated',f'C4_reference_L2_A1_seed{seed}','C4_reference','verification'),seed=seed),
                        dict(entry('C4compensated',f'{cid}_L2_A1_seed{seed}',cid,'verification'),seed=seed)]
        return entries
    if phase=='extrapolation':
        cid=(registry or {}).get('selected_candidate_id')
        if not cid:return []
        return [dict(entry('C4compensated',f'{cid}_{cell}_seed41',cid,'extrapolation'),cell=cell,load_index=load,alignment=align,seed=41)
            for load,align,cell in ((0,0,'L0_A0'),(1,1,'L1_A1'))]
    raise ValueError(phase)
r.run_plan=lambda:plan_for_phase(CURRENT_PHASE, json.loads(REGISTRY.read_text()) if REGISTRY.exists() else None)


def normalize_result_root(dest,config):
    """Map the audit-only derived-network prefix back to canonical ZonalIVN paths.

    The derived NED inherits the identical topology and only adds a clock observer;
    older technical attempt files used its type name as the result root. Preserve the
    original root in run metadata while normalizing module paths consumed by the
    existing validator. Future NED uses the canonical root type directly.
    """
    old='ZonalIVNClockPrecisionAudit.'; new='ZonalIVN.'
    for path in [*dest.glob(f'{config}-#*.sca')]:
        text=path.read_text(errors='replace')
        if old in text: path.write_text(text.replace(old,new))
    for path in dest.glob(f'{config}-#*.vec'):
        tmp=path.with_suffix(path.suffix+'.normalized')
        with path.open('r',errors='replace') as src,tmp.open('w') as dst:
            for line in src:
                dst.write(line.replace(old,new) if line.startswith(('vector ','attr ')) else line)
        tmp.replace(path)

def run_one_wrapped(spec0,manifest,preflight,freshly_simulated=False):
    ACTIVE_SPEC.clear(); ACTIVE_SPEC.update(spec0)
    config=f"Pilot_{spec0['variant']}_{spec0['cell']}"
    dest=OUT/'runs'/spec0['execution_id']; run_dir=dest/f'{config}-0'
    normalize_result_root(dest,config)
    # Suppress inherited cleanup before its run_one() reaches the retention
    # callback. Pilot-specific vectors must be extracted while the raw vector
    # is still present at the root of the result directory.
    r.compress_or_remove_raw=lambda dest,config,run_dir,keep: None
    row=ORIG_RUN_ONE(spec0,manifest,preflight,freshly_simulated)
    try:
        service_path=parse_service_vectors(dest,config,run_dir)
    except Exception as exc:
        row['status']='completed_instrumentation_incomplete'
        row['service_event_extraction_status']='failed'
        row['service_event_extraction_error']=f'{type(exc).__name__}: {exc}'
        row['raw_vector_retained_for_recovery']=True
        report=dest/'pilot-result.json'
        report.write_text(json.dumps(row,indent=2,ensure_ascii=False)+'\n')
        ledger=OUT/'runs.jsonl'
        if ledger.exists():
            items=[]
            for line in ledger.read_text().splitlines():
                try: item=json.loads(line)
                except json.JSONDecodeError: continue
                items.append(row if item.get('execution_id')==spec0['execution_id'] else item)
            ledger.write_text(''.join(json.dumps(x,separators=(',',':'),ensure_ascii=False)+'\n' for x in items))
        r.append_jsonl(OUT/'technical_attempts.jsonl',{
            **spec0,'attempt_status':'failed_technical_postprocessing',
            'attempt_id':f"{spec0['execution_id']}:service_extract:{int(time.time())}",
            'simulation_completed':True,'simulation_rerun_required_for_recovery':True,
            'error':row['service_event_extraction_error'],
            'timestamp_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())})
        raise
    row.setdefault('credit_service_audit',{})['arrivals_departures_drops_and_phy_busy']=str(service_path.relative_to(HERE))
    row.setdefault('evidence',{})['service_and_wire_events']=str(service_path.relative_to(HERE))
    row['service_event_extraction_status']='complete'
    row['physical_link_busy_status']='unavailable_selector_mismatch_in_completed_controls'
    report=dest/'pilot-result.json'
    report.write_text(json.dumps(row,indent=2,ensure_ascii=False)+'\n')
    ledger=OUT/'runs.jsonl'
    if ledger.exists():
        items=[]
        for line in ledger.read_text().splitlines():
            try: item=json.loads(line)
            except json.JSONDecodeError: continue
            items.append(row if item.get('execution_id')==spec0['execution_id'] else item)
        ledger.write_text(''.join(json.dumps(x,separators=(',',':'),ensure_ascii=False)+'\n' for x in items))
    ORIG_COMPRESS(dest,config,run_dir,bool(row.get('retained_raw_vector')))
    return row
r.run_one=run_one_wrapped

# The wrapper above extracts study-specific packet events before raw retention.
r.compress_or_remove_raw=lambda dest,config,run_dir,keep: None


def add_target_modes(spec0,manifest):
    config,dest,extras=ORIG_OVERRIDES(spec0,manifest)
    for module in QUEUE_MODULES:
        parameter_path='*.'+module.removeprefix('ZonalIVN.')
        for stat in ('incomingPacketLengths','outgoingPacketLengths','droppedPacketLengthsQueueOverflow'):
            extras.append(f'--{parameter_path}.{stat}.result-recording-modes=+vector')
    run_dir=OUT/'runs'/spec0['execution_id']; trace=run_dir/'clock_precision.csv'
    extras += ['--network=zonal_ivn_tsn.simulations.pilot.c4_cbs_tas_investigation.precision.ZonalIVN',
      f'--*.clockAudit.outputFile="{trace.resolve()}"','--*.clockAudit.sampleInterval=1ms','--*.clockAudit.stopAt=31.05s','-l',str(HERE/'precision/plugin/libclockprecision.so')]
    return config,dest,extras
r.simulation_overrides=add_target_modes


def extract_service_events(dest,config,run_dir,keep):
    vec=run_dir/f'{config}-#0.vec'
    # Use exact vector definitions and retain only relevant push/pull/drop and
    # transmitter state transitions, then allow the normal raw-vector policy.
    if vec.exists(): parse_service_vectors(dest,config,run_dir)
    return ORIG_COMPRESS(dest,config,run_dir,keep)
# Cleanup is deliberately deferred to run_one_wrapped after its own extraction.
r.compress_or_remove_raw=lambda dest,config,run_dir,keep: None


def manifest_for(phase):
    global CURRENT_PHASE
    CURRENT_PHASE=phase
    manifest=r.make_manifest()
    manifest['run_schedule']=plan_for_phase(phase,json.loads(REGISTRY.read_text()) if REGISTRY.exists() else None)
    manifest['phase']=phase
    manifest['exploratory']=True; manifest['official_c4_frozen']=False
    manifest['run_budget']={'maximum_methodological_runs':16,'phase_control':2,'candidate_limit':6,'verification_limit':6,'extrapolation_limit':2,'technical_attempts_separate':True}
    manifest['instrumentation']={'queue_targets':QUEUE_MODULES,'transmitter_targets':LINK_MODULES,'clock_probe_source':str(HERE/'precision/plugin/ClockPrecisionProbe.cc'),'clock_probe_method':'native ticks, simultaneous subtraction before serialization; corrected and free clock readings; event order preserved'}
    manifest['versions_and_hashes'][str((HERE/'protocol.md').relative_to(ROOT))]=r.sha256(HERE/'protocol.md')
    manifest['versions_and_hashes'][str((HERE/'run_investigation.py').relative_to(ROOT))]=r.sha256(Path(__file__))
    manifest['versions_and_hashes'][str((HERE/'runner_core.py').relative_to(ROOT))]=r.sha256(HERE/'runner_core.py')
    manifest['versions_and_hashes'][str((HERE/'pilot.ini').relative_to(ROOT))]=r.sha256(HERE/'pilot.ini')
    manifest['versions_and_hashes'][str((HERE/'candidate_registry.json').relative_to(ROOT))]=r.sha256(REGISTRY) if REGISTRY.is_file() else None
    manifest['versions_and_hashes'][str((HERE/'register_candidates.py').relative_to(ROOT))]=r.sha256(HERE/'register_candidates.py')
    manifest['versions_and_hashes'][str((HERE/'audit_service_controls.py').relative_to(ROOT))]=r.sha256(HERE/'audit_service_controls.py')
    for f in (HERE/'precision/plugin/ClockPrecisionProbe.cc',HERE/'precision/ClockPrecisionProbe.ned',HERE/'precision/ZonalIVNClockPrecisionAudit.ned'):
        manifest['versions_and_hashes'][str(f.relative_to(ROOT))]=r.sha256(f)
    manifest['registered_protocol_sha256']=r.sha256(HERE/'protocol.md')
    return manifest


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--phase',choices=('controls','candidates','verification','extrapolation'),required=True)
    ap.add_argument('--plan',action='store_true'); ap.add_argument('--run',action='store_true'); ap.add_argument('--resume',action='store_true')
    args=ap.parse_args()
    if args.plan==args.run: raise SystemExit('choose exactly one of --plan or --run')
    OUT.mkdir(parents=True,exist_ok=True)
    # A fresh protocol-bound plan is written for each registered phase; prior
    # plan/checkpoint files are retained in plan_history before replacement.
    manifest=manifest_for(args.phase)
    if args.plan:
        plan=OUT/'plan.json'
        if plan.exists():
            hist=OUT/'plan_history';hist.mkdir(parents=True,exist_ok=True)
            shutil.copy2(plan,hist/f'plan_before_{args.phase}_{int(time.time())}.json')
        r.write_json(plan,manifest)
        r.write_json(OUT/'checkpoint.json',{'pilot_id':'c4-cbs-tas-investigation','phase':f'planned_{args.phase}','planned_runs':len(manifest['run_schedule']),'completed_runs':len(r.current_ledger()),'exploratory':True,'official_c4_frozen':False,'free_disk_gb':round(r.free_gb(),2),'available_memory_gb':round(r.memory_available_gb(),2)})
        print(json.dumps({'phase':args.phase,'scheduled':manifest['run_schedule'],'profile':manifest['official_profile']['profile_id'],'protocol_sha256':manifest['registered_protocol_sha256'],'free_disk_gb':round(r.free_gb(),2),'available_memory_gb':round(r.memory_available_gb(),2)},indent=2))
        return
    expected=json.loads((OUT/'plan.json').read_text())
    if expected.get('phase')!=args.phase: raise SystemExit('saved plan phase differs; run --plan for this phase first')
    if expected.get('versions_and_hashes')!=manifest.get('versions_and_hashes'): raise SystemExit('code/config/protocol hash changed since plan; preserve history and re-plan')
    if not (HERE/'precision/plugin/libclockprecision.so').is_file(): raise SystemExit('clock probe plugin missing; run build_clock_probe.sh')
    if args.phase=='candidates' and not REGISTRY.exists(): raise SystemExit('candidate registry must be saved before running candidates')
    r.execute(manifest,resume=args.resume)
    patch_current_views()
    print(json.dumps({'phase':args.phase,'completed':len(r.current_ledger()),'free_disk_gb':round(r.free_gb(),2),'available_memory_gb':round(r.memory_available_gb(),2)},indent=2))

if __name__=='__main__':main()
