#!/usr/bin/env python3
"""Isolated, checkpointed official C0-C3 campaign runner for the current P1."""
import argparse,csv,fcntl,gzip,hashlib,json,math,os,shutil,statistics,subprocess,sys,time,threading
from concurrent.futures import FIRST_COMPLETED,ThreadPoolExecutor,wait
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]; SIM=ROOT/'simulations'; HERE=Path(__file__).resolve().parent; OUT=HERE/'results'
sys.path[:0]=[str(ROOT/'scripts/run'),str(ROOT/'scripts/catalog')]
import validate_c0 as validator, generate_cbs as cbs
from calibration_search import profile_signature, ordered_candidates, propose_increment, reduction_target
SEEDS=range(1001,1031); LOADS=('L0','L1','L2','L3'); FREE_FLOOR_GB=45
MEMORY_RESERVE_GIB=4.0; MEMORY_PER_JOB_GIB=2.5
# Keep the preregistered operational limit in the immutable protocol snapshot,
# while enforcing the user's current four-job runtime cap in this executor.
PREREGISTERED_MAX_WORKERS=8; RUNTIME_MAX_WORKERS=4
RESUME=False; MAX_WORKERS=PREREGISTERED_MAX_WORKERS; RUNTIME_WORKERS=RUNTIME_MAX_WORKERS
STOP_AFTER_CELL=None; LOCK=threading.RLock()
SELECTED_TREATMENTS=None; SHARD_ID=None
LOCK_FD=None; LEDGER_INDEX={}; ACTIVE_EXECUTIONS=set()
def req(ok,msg):
    if not ok: raise RuntimeError(msg)
def readj(p): return json.loads(Path(p).read_text())
def fsync_dir(path):
    try:
        fd=os.open(str(path),os.O_RDONLY|os.O_DIRECTORY)
        try: os.fsync(fd)
        finally: os.close(fd)
    except OSError: pass
def fsync_file(path):
    try:
        fd=os.open(str(path),os.O_RDONLY)
        try:os.fsync(fd)
        finally:os.close(fd)
    except OSError:pass
def writej(p,x):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_name(p.name+'.tmp')
    with tmp.open('w',encoding='utf-8') as f:
        f.write(json.dumps(x,indent=2,sort_keys=True)+'\n');f.flush();os.fsync(f.fileno())
    tmp.replace(p);fsync_dir(p.parent)
def predeclared_protocol():
    return {'p1_section':'4.4','status':'preregistered_before_calibration_runs',
      'start':'C2 nominal at L2/A1, seed 41; the nominal run is a control and does not count as a new candidate',
      'targets':'Only TC4/TC6 egresses actually traversed by currently failing flows, based on generate_cbs.route; F21/F22 remain excluded from permanent nominal load.',
      'order':'Rank eligible egress/classes by maximum measured queueingTime, then mean queueingTime, route order, egress, TC, and flow ID. After every run, recompute failures and waits.',
      'increase_step':'10% of physical port line rate for one eligible egress/class per candidate; cap aggregate CBS reservation at 75% per port; reject pre-execution if the cap would be crossed.',
      'candidate_budget':{'maximum_new_candidate_executions':24,'rejected_before_execution_do_not_consume_execution_budget':True},
      'stop_increases':'Stop at first candidate passing all P1 viability gates. If the 24-candidate budget is exhausted, report exactly “nenhum candidato viável encontrado pela busca definida” and do not run C3 final cells.',
      'reduction_step':'Starting with the first viable profile, reduce one above-nominal egress/class by 2% of its physical port rate, bounded below by that L2 nominal. Test at most 12 reductions; retain only passing reductions.',
      'profile_acceptance':'The profile after reductions is checked unchanged at seeds 41, 43, and 47, with C2 nominal controls at seeds 43 and 47. Freeze ratios only if all three profile runs pass all P1 gates and calendars pair within each seed.',
      'other_loads':'Apply frozen candidate/nominal ratios to each load and pre-screen each port against 75%; never clip or retune a cell.',
      'transient_pairing':'Hash exact events.csv rows for F21/F22 by load/alignment/seed, compare across treatments; archive calendar and hash.',
      'final_campaign_concurrency':{'max_parallel_runs':PREREGISTERED_MAX_WORKERS,'basis':'user-authorized high-throughput resume; eight CPU-bound jobs, unrestricted CPU affinity, normal CPU priority, best-effort I/O priority 0, and a 45 GB disk stop floor; leave four logical CPUs schedulable for the OS and SSH'},
      'destination_egress_exclusion':'Only route-helper egresses are eligible; no CBS is applied to a receiver-only/destination egress.',
      'scope':'Exploratory calibration on seed 41 plus fixed-profile checks on 43 and 47; these seeds are distinct from final 1001–1030.'}
def digest(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
REUSE_WITH_DOCUMENTED_AMENDMENT={
  'simulations/campaigns/p1-v2-official-2026-10/run_campaign.py',
  # Two-host preflight/parser corrections do not alter the simulation model.
  'simulations/campaigns/p1-v2-official-2026-10/prepare_parallel_campaign.py',
  'simulations/campaigns/p1-v2-official-2026-10/flow_mapping.csv',
  'scripts/run/validate_c0.py',
  # User-authorized runtime-only increase from four to eight concurrent jobs;
  # its previous version and amendment are retained under protocol_history/.
  'simulations/campaigns/p1-v2-official-2026-10/calibration_protocol.json',
}
def source_hashes_reusable(old,current):
    """Allow only documented orchestration, presentation, and retention fixes."""
    if not old:return False
    return all(path in REUSE_WITH_DOCUMENTED_AMENDMENT or current.get(path)==sha
               for path,sha in old.items()) and all(path in current for path in old)
def outdir(*parts):
    p=OUT.joinpath(*parts);p.mkdir(parents=True,exist_ok=True);return p
def free_gb(): return shutil.disk_usage(ROOT).free/1e9
def mem_available_gib():
    for line in Path('/proc/meminfo').read_text().splitlines():
        if line.startswith('MemAvailable:'): return int(line.split()[1])/(1024**2)
    return 0.0
def check_resources_for_jobs(jobs):
    available=mem_available_gib()
    req(available >= MEMORY_RESERVE_GIB + MEMORY_PER_JOB_GIB*jobs,
        f'insufficient available memory for {jobs} jobs: {available:.2f} GiB available; '
        f'requires {MEMORY_RESERVE_GIB + MEMORY_PER_JOB_GIB*jobs:.2f} GiB and leaves '
        f'{MEMORY_RESERVE_GIB:.1f} GiB for the OS')
    req(free_gb() > FREE_FLOOR_GB,
        f'low-space checkpoint before launching jobs: {free_gb():.1f} GB free; floor is {FREE_FLOOR_GB} GB')
def acquire_campaign_lock():
    global LOCK_FD
    LOCK_FD=os.open(OUT/'.campaign.lock',os.O_CREAT|os.O_RDWR,0o644)
    try: fcntl.flock(LOCK_FD,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError as e:
        os.close(LOCK_FD);LOCK_FD=None
        raise RuntimeError('another campaign runner holds results/.campaign.lock; refusing a concurrent run') from e
    os.ftruncate(LOCK_FD,0);os.write(LOCK_FD,f'{os.getpid()}\n'.encode());os.fsync(LOCK_FD)
def append_durable_jsonl(path,row):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    payload=(json.dumps(row,separators=(',',':'),sort_keys=True)+'\n').encode()
    fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o644)
    try:
        view=memoryview(payload)
        while view:
            written=os.write(fd,view);view=view[written:]
        os.fsync(fd)
    finally: os.close(fd)
    fsync_dir(p.parent)
def recover_ledger():
    """Keep every valid committed line and quarantine malformed bytes before resume."""
    global LEDGER_INDEX
    path=OUT/'runs.jsonl';LEDGER_INDEX={}
    if not path.exists(): return
    valid=[];invalid=[]
    with path.open('rb') as f:
        for raw in f:
            if not raw.strip(): continue
            try:
                row=json.loads(raw)
                if not isinstance(row,dict) or not row.get('execution_id'): raise ValueError('missing execution_id')
                if not raw.endswith(b'\n'): raw=raw+b'\n'
            except (json.JSONDecodeError,ValueError):
                invalid.append(raw);continue
            valid.append(raw)
    if invalid:
        stamp=time.strftime('%Y%m%dT%H%M%S',time.gmtime())
        quarantine=outdir('audit','ledger-recovery')/f'invalid-ledger-bytes-{stamp}.bin'
        with quarantine.open('wb') as f:
            f.write(b''.join(invalid));f.flush();os.fsync(f.fileno())
        tmp=path.with_name(path.name+'.recovered.tmp')
        with tmp.open('wb') as f:
            f.write(b''.join(valid));f.flush();os.fsync(f.fileno())
        tmp.replace(path);fsync_dir(path.parent)
        append_durable_jsonl(OUT/'audit'/'recovery_events.jsonl',{
            'event':'malformed_ledger_bytes_quarantined','utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
            'quarantine':str(quarantine.relative_to(HERE)),'bytes':sum(map(len,invalid)),
            'valid_records_retained':len(valid)})
    offset=0
    with path.open('rb') as f:
        for raw in f:
            if not raw.strip(): offset+=len(raw);continue
            row=json.loads(raw);eid=row['execution_id']
            if eid in LEDGER_INDEX: raise RuntimeError(f'duplicate execution_id in ledger: {eid}')
            LEDGER_INDEX[eid]={'offset':offset,'length':len(raw)};offset+=len(raw)
def ledger_record(execution_id):
    meta=LEDGER_INDEX.get(execution_id)
    if not meta:return None
    with (OUT/'runs.jsonl').open('rb') as f:
        f.seek(meta['offset']);return json.loads(f.read(meta['length']))
def archive_incomplete_attempt(dest,exec_id,stage,t,l,a,seed):
    """Preserve an uncommitted run directory and free its canonical path for resume."""
    stamp=time.strftime('%Y%m%dT%H%M%S',time.gmtime())
    parent=outdir('failed-attempts','uncommitted',stage,t,LOADS[l],f'A{a}',f'seed{seed}')
    target=parent/f'{exec_id}_{stamp}'
    suffix=1
    while target.exists():
        target=parent/f'{exec_id}_{stamp}_{suffix}';suffix+=1
    files=[{'path':str(p.relative_to(dest)),'bytes':p.stat().st_size} for p in dest.rglob('*') if p.is_file()]
    os.replace(dest,target);fsync_dir(target.parent)
    writej(target/'attempt_metadata.json',{
      'status':'interrupted_uncommitted_attempt','execution_id':exec_id,'stage':stage,'treatment':t,
      'load':LOADS[l],'alignment':f'A{a}','seed':seed,'archived_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
      'reason':'nonempty canonical result directory had no matching durable runs.jsonl entry during --resume',
      'raw_files_preserved':files})
    dest.mkdir(parents=True,exist_ok=True)
    append_durable_jsonl(OUT/'audit'/'recovery_events.jsonl',{
      'event':'uncommitted_attempt_archived','utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
      'execution_id':exec_id,'path':str(target.relative_to(HERE)),'files':len(files),
      'bytes':sum(x['bytes'] for x in files)})
def nominal_by_load():
    rows=cbs.nominal_reservations(cbs.read_flows()); out={}
    for (load,e,tc),v in rows.items():out[load,e,tc]=v
    return out
def port_rates(profile):
    totals={}
    for (e,_),x in profile.items():totals[e]=totals.get(e,0)+x
    return totals
def capcheck(profile): return [e for e,x in port_rates(profile).items() if x>.75*cbs.capacity_bps(e)]
def runid(t,l,a,s): return f'{t}_{LOADS[l]}_A{a}_seed{s}'
def calendar_sig(run_dir):
    rows=list(csv.DictReader((run_dir/'events.csv').open()))
    payload=[{k:r[k] for k in ('flow','block','signature','start','duration','volume_bytes')} for r in rows]
    return hashlib.sha256(json.dumps(payload,separators=(',',':')).encode()).hexdigest(),rows
def completed_raw_run_matches(dest,config,seed):
    """Allow postprocessing reuse only when OMNeT finished and raw identity matches."""
    log=dest/f'{config}.log';sca=dest/f'{config}-#0.sca';vec=dest/f'{config}-#0.vec'
    rd=dest/f'{config}-0'
    if not all(p.is_file() for p in (log,sca,vec,rd/'run.csv',rd/'events.csv',rd/'drops.csv',rd/'wire.csv',rd/'queues.csv',rd/'releases.csv')):
        return False
    tail=log.read_text(errors='replace')[-200_000:]
    if 'Calling finish() at end of Run' not in tail or 'End.' not in tail:
        return False
    expected_dir=str(dest.relative_to(SIM))
    for path in (sca,vec):
        attrs={}
        with path.open(errors='replace') as stream:
            for line in stream:
                if line.startswith('attr '):
                    parts=line.rstrip().split(' ',2)
                    if len(parts)==3:attrs[parts[1]]=parts[2].strip('"')
                elif line and line[0].isdigit():break
        if attrs.get('configname')!=config or attrs.get('seedset')!=str(seed) or attrs.get('resultdir')!=expected_dir:
            return False
    return True
def compress_result_files(dest,config,run_dir):
    for p in (dest/f'{config}-#0.sca',dest/f'{config}.log'):
        if p.exists():
            target=Path(str(p)+'.gz')
            tmp=Path(str(target)+'.tmp')
            with p.open('rb') as src,gzip.open(tmp,'wb',compresslevel=6) as dst:shutil.copyfileobj(src,dst)
            fsync_file(tmp);tmp.replace(target);fsync_dir(target.parent);p.unlink();fsync_dir(p.parent)
    for p in dest.glob(f'{config}-#*.vec'):
        p.unlink()
    # A vector index has no audit value after its corresponding raw vector has
    # been removed; it cannot be used to query or reconstruct data by itself.
    for p in dest.glob(f'{config}-#*.vci'):
        if not (dest / p.name.replace('.vci','.vec')).exists(): p.unlink()
    fsync_dir(dest)
    for name in ('releases.csv','queues.csv','drops.csv','wire.csv','events.csv'):
        p=run_dir/name
        if p.exists():
            target=Path(str(p)+'.gz');tmp=Path(str(target)+'.tmp')
            with p.open('rb') as src,gzip.open(tmp,'wb',compresslevel=6) as dst:shutil.copyfileobj(src,dst)
            fsync_file(tmp);tmp.replace(target);fsync_dir(target.parent);p.unlink();fsync_dir(p.parent)
def sim(t,l,a,seed,profile=None,stage='final',label=None):
    key=runid(t,l,a,seed); config=f'Validate_{("C2" if t=="C3" else t)}_{LOADS[l]}_A{a}'
    exec_id=label or key; dest=outdir(stage,t,LOADS[l],f'A{a}',f'seed{seed}',exec_id)
    profile_dict={f'{e}/TC{tc}':r for (e,tc),r in (profile or {}).items()}
    profile_hash=hashlib.sha256(json.dumps(profile_dict,sort_keys=True).encode()).hexdigest()
    ledger=OUT/'runs.jsonl'
    old=ledger_record(exec_id) if RESUME else None
    if old is not None:
        expected=(old.get('campaign_treatment')==t and old.get('load')==l and old.get('aggregation')==f'A{a}'
          and old.get('seed')==seed and old.get('profile_sha256')==profile_hash
          and old.get('config')==config
          and source_hashes_reusable(old.get('configuration_source_hashes',{}), MANIFEST['source_hashes']))
        req(expected,f'{exec_id}: checkpoint mismatch in treatment/load/alignment/seed/profile/source hashes')
        tail=HERE/old['retained']['packet_image_quantile_samples']
        req(tail.is_file(),f'{exec_id}: compact latency samples missing; refusing resume')
        index=OUT/'calendars/calendar_index.json';idx=readj(index) if index.exists() else {}
        ckey=f'{LOADS[l]}/A{a}/seed{seed}'
        req(ckey in idx and idx[ckey]['sha256']==old.get('calendar_sha256'),
            f'{exec_id}: calendar signature does not match the active campaign index')
        existing_rd=dest/f'{config}-0'
        compress_result_files(dest,config,existing_rd)
        return old
    reprocess_existing=False
    if any(dest.iterdir()):
        if RESUME and completed_raw_run_matches(dest,config,seed):
            reprocess_existing=True
            append_durable_jsonl(OUT/'audit'/'recovery_events.jsonl',{
              'event':'completed_raw_simulation_reprocessed_after_postprocessing_failure',
              'utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'execution_id':exec_id,
              'path':str(dest.relative_to(HERE)),'reason':'OMNeT completed successfully; prior run stopped during validator reconciliation'})
        elif RESUME: archive_incomplete_attempt(dest,exec_id,stage,t,l,a,seed)
        else: raise RuntimeError(f'{exec_id}: result directory already exists without a reusable complete campaign checkpoint; preserving it as incomplete')
    req(free_gb()>FREE_FLOOR_GB,f"low-space checkpoint: {free_gb():.1f} GB free")
    with LOCK:
        ACTIVE_EXECUTIONS.add(exec_id)
        writej(OUT/'checkpoint.json',{'campaign_id':'p1-v2-official-2026-10','stage':stage,
          'active_process':True,'executor_pid':os.getpid(),'active_execution_ids':sorted(ACTIVE_EXECUTIONS),
          'max_parallel_runs':RUNTIME_WORKERS,'active_execution_id':exec_id,'free_gb':free_gb(),
          'timestamp':time.time(),'checkpoint_note':'raw output is retained until metrics and compact temporal evidence reconcile'})
    extras=[f'--seed-set={seed}']
    calendar_key=f'{LOADS[l]}/A{a}/seed{seed}'
    calendar_index=OUT/'calendars/calendar_index.json'
    if stage=='final' and t!='C0':
        req(calendar_index.is_file(),f'{key}: paired C0 calendar index missing')
        calendar_entries=readj(calendar_index)
        req(calendar_key in calendar_entries,f'{key}: paired C0 calendar missing: {calendar_key}')
        calendar_entry=calendar_entries[calendar_key]
        calendar_path=HERE/calendar_entry['file']
        req(calendar_path.is_file(),f'{key}: paired C0 calendar file missing: {calendar_path}')
        calendar_sig_existing,calendar_events_existing=calendar_sig(calendar_path)
        req(calendar_sig_existing==calendar_entry['sha256'] and
            len(calendar_events_existing)==int(calendar_entry['event_count']),
            f'{key}: paired C0 calendar does not match its index: {calendar_key}')
        calendar_from_sim=calendar_path.relative_to(SIM).as_posix()
        extras.append(f'--*.trafficPlan.transientCalendarFile={calendar_from_sim}')
    if t in ('C2','C3'):extras.append('--**.numCredits.result-recording-modes=vector,max,min,timeavg')
    if profile: extras += [f'--*.{e}.macLayer.queue.transmissionSelectionAlgorithm[{tc}].idleSlope={r}bps' for (e,tc),r in sorted(profile.items())]
    report,rd=validator.run_cell(config,dest,ENV,INET,execute=not reprocess_existing,
       result_dir_override=str(dest.relative_to(SIM)),extra_args=tuple(extras),
       resource_mem_floor_gib=3.0)
    rd=Path(rd);sig,events=calendar_sig(rd); ckey=f'{LOADS[l]}/A{a}/seed{seed}'
    csv_trace=rd/'queue_occupancy_events.csv.gz'
    req(csv_trace.is_file() and Path(str(csv_trace)+'.meta.json.gz').is_file(),
        f'{exec_id}: compact queue occupancy event trace missing')
    trace=validator.compact_queue_occupancy_trace(csv_trace)
    recomputed=validator.recompute_queue_occupancy_trace(trace)
    recorded={x['queue']:x for x in report.get('queue_stability',[])}
    req(len(recomputed)==len(recorded),f'{exec_id}: queue trace population mismatch')
    for q in recomputed:
        ref=recorded[q['queue']]
        for field in ('mean_occupancy_bits_5s','mean_occupancy_bits_measurement',
                      'fraction_measurement_at_least_90pct_capacity','max_occupancy_bits',
                      'capacity_bits','sustained_growth'):
            x,y=q[field],ref[field]
            if isinstance(x,list):
                req(len(x)==len(y) and all(math.isclose(a,b,rel_tol=1e-10,abs_tol=1e-9) for a,b in zip(x,y)),
                    f'{exec_id}: independently recomputed {field} mismatch at {q["queue"]}')
            elif isinstance(x,float):
                req(math.isclose(x,y,rel_tol=1e-10,abs_tol=1e-9),
                    f'{exec_id}: independently recomputed {field} mismatch at {q["queue"]}')
            else:req(x==y,f'{exec_id}: independently recomputed {field} mismatch at {q["queue"]}')
    # The compact delta trace has now been independently decoded and compared
    # against every reported queue metric; only now discard the CSV duplicate.
    csv_trace.unlink();Path(str(csv_trace)+'.meta.json.gz').unlink()
    with LOCK:
        index=outdir('calendars')/'calendar_index.json';idx=readj(index) if index.exists() else {}
        if ckey in idx:req(idx[ckey]['sha256']==sig,f'{key}: transient calendar not paired')
        else:
            cp=outdir('calendars',LOADS[l],f'A{a}')/f'seed{seed}_events.csv';shutil.copy2(rd/'events.csv',cp)
            idx[ckey]={'sha256':sig,'file':str(cp.relative_to(HERE)),'event_count':len(events),'treatments':[t]}
        if t not in idx[ckey]['treatments']:idx[ckey]['treatments'].append(t)
        writej(index,idx)
    sca=next(dest.glob(f'{config}-#0.sca'));params=validator.parse_sca(sca)
    observed={}
    import re
    for (m,n),v in params.items():
        z=re.fullmatch(r'(ZonalIVN\..*)\.macLayer\.queue\.transmissionSelectionAlgorithm\[(\d+)\]',m)
        if z and n=='idleSlope':
            q=re.fullmatch(r'([\d.eE+-]+)\s*(?:bps)?',str(v))
            if q:observed[z.group(1).removeprefix('ZonalIVN.'),int(z.group(2))]=round(float(q.group(1)))
    if profile:
        mismatch={f'{e}/TC{tc}':(rate,observed.get((e,tc))) for (e,tc),rate in profile.items() if observed.get((e,tc))!=rate}
        req(not mismatch,f'{key}: resolved CBS profile mismatch: {mismatch}')
    tailfile=rd/'latency_upper_tails.json.gz'
    req(tailfile.is_file(),f'{exec_id}: compact latency sample archive missing')
    with gzip.open(tailfile,'rt',encoding='utf-8') as f:tails=json.load(f)
    for fid,q in report['qos'].items():
      for node,rx in q['receivers'].items():
        pt=tails['packet'].get(f'{fid}/{node}')
        req((pt or {}).get('sample_count')==(rx.get('latency') or {}).get('samples'),f'{fid}/{node}: retained packet-tail population mismatch')
        im=rx.get('image_completion')
        if im:
          it=tails['image'].get(f'{fid}/{node}')
          req((it or {}).get('sample_count')==im.get('samples'),f'{fid}/{node}: retained image-tail population mismatch')
    report.update({'campaign_id':'p1-v2-official-2026-10','stage':stage,'execution_id':exec_id,'campaign_treatment':t,'seed':seed,'load_name':LOADS[l],
       'aggregation_name':f'A{a}','calendar_sha256':sig,'calendar_event_count':len(events),
       'simulation_run_status':'reprocessed_existing_completed_raw_output' if reprocess_existing else 'simulated_in_this_attempt',
       'reservation_profile_bps':{f'{e}/TC{tc}':r for (e,tc),r in (profile or {}).items()},
       'resolved_profile_verified':bool(profile),'resolved_sca_sha256':digest(sca),
       'configuration_source_hashes':MANIFEST['source_hashes'],'command':{'config':config,'seed_set':seed,'result_dir':str(dest.relative_to(SIM)),'overrides':extras},
       'shard_id':SHARD_ID,
       'retained':{'packet_image_quantile_samples':str((rd/'latency_upper_tails.json.gz').relative_to(HERE)),
          'queue_occupancy_events':str(trace.relative_to(HERE)),
          'queue_occupancy_metadata':str(Path(str(trace)+'.meta.json.gz').relative_to(HERE)),
          'queue_occupancy_recalculation_verified':True,
          'queue_occupancy':'exact change-point trace; six 5-second means, mean, peak, >=90% fraction, and sustained-growth flag independently recalculated before raw-vector removal',
          'sca_log':'gzip','raw_vectors':'deleted only after compact queue trace and metrics independently reconciled',
          'event_release_queue_drop_csv':'gzip after validation'}})
    report['profile_sha256']=profile_hash
    jpath=rd/f'{t.lower()}-acceptance.json';writej(jpath,report)
    for p in (tailfile,trace,Path(str(trace)+'.meta.json.gz'),jpath,rd/'validation.json'):
        if p.exists():fsync_file(p)
    with LOCK:
        offset=ledger.stat().st_size if ledger.exists() else 0
        append_durable_jsonl(ledger,report)
        LEDGER_INDEX[exec_id]={'offset':offset,'length':ledger.stat().st_size-offset}
        ACTIVE_EXECUTIONS.discard(exec_id)
        ledger_records=len(LEDGER_INDEX)
        writej(OUT/'checkpoint.json',{'campaign_id':'p1-v2-official-2026-10','stage':stage,
          'latest_execution_id':exec_id,'completed_ledger_records':ledger_records,
          'latest_calendar_sha256':sig,'free_gb':free_gb(),'timestamp':time.time(),
          'active_process':True,'executor_pid':os.getpid(),'active_execution_ids':sorted(ACTIVE_EXECUTIONS),
          'max_parallel_runs':RUNTIME_WORKERS})
    # The durable ledger commit precedes deletion of raw simulator evidence.
    # If power fails before this cleanup, --resume will reuse the committed row
    # and finish compression; if it fails before commit, the raw run is intact.
    compress_result_files(dest,config,rd)
    return report

def profile_rows(profile,load,nominal,flows):
    totals=port_rates(profile); rows=[]
    for (e,tc),rate in sorted(profile.items()):
        bps=nominal.get((e,tc),0)
        rows.append({'egress':e,'tc':tc,'idle_slope_bps':rate,'nominal_idle_slope_bps':bps,
          'candidate_to_nominal_ratio':rate/nominal.get((e,tc),0) if nominal.get((e,tc),0) else None,'port_rate_bps':cbs.capacity_bps(e),
          'total_port_reservation_bps':totals[e],'cap_fraction':totals[e]/cbs.capacity_bps(e),
          'headroom_to_75pct_bps':int(.75*cbs.capacity_bps(e))-totals[e],
          'permanent_flows':sorted(flows.get((e,tc),set()))})
    return rows

def resume_calibration_after_interruption():
    """Resume reductions from the latest audited passing profile.

    Completed candidates and reductions are ledger-reused. The next interrupted
    reduction is retried only after its complete vector and transient calendar
    match the deterministic proposal.
    """
    by=nominal_by_load();nom={(e,tc):v['bps'] for (l,e,tc),v in by.items() if l==2}
    flows={(e,tc):v['flows'] for (l,e,tc),v in by.items() if l==2}
    records=[json.loads(x) for x in (OUT/'runs.jsonl').read_text().splitlines() if x.strip()]
    byid={r.get('execution_id'):r for r in records}
    nominal=byid.get('C2_nominal_seed41_retention_audit') or byid.get('C2_nominal_seed41')
    candidate=byid.get('candidate_11')
    req(nominal and candidate and candidate.get('viable') is True,
        'resume requires the audited nominal and viable candidate_11')
    req(nominal['calendar_sha256']==candidate['calendar_sha256'],
        'candidate_11 is not paired with the nominal F21/F22 calendar')
    def profile_of(run):
        return {(k.rsplit('/TC',1)[0],int(k.rsplit('/TC',1)[1])):int(v)
                for k,v in run.get('reservation_profile_bps',{}).items()}
    selected=profile_of(candidate);selected_run=candidate;final_id='candidate_11'
    req(selected and len(selected)==len(nom) and not capcheck(selected),
        'candidate_11 reservation vector is incomplete or exceeds the 75% port cap')
    reductions=[];rejected=set();seen={profile_signature(nom)}
    reduction_runs=sorted((r for r in records if r.get('stage')=='calibration'
        and str(r.get('execution_id','')).startswith('reduction_')),
        key=lambda r:int(r['execution_id'].split('_')[-1]))
    req([int(r['execution_id'].split('_')[-1]) for r in reduction_runs]==list(range(1,len(reduction_runs)+1)),
        'reduction ledger has a gap; cannot safely resume the registered sequence')
    for r in records:
        p=profile_of(r)
        if p:seen.add(profile_signature(p))
    for r in reduction_runs:
        trial=profile_of(r);ix=int(r['execution_id'].split('_')[-1])
        changed=[k for k in selected if trial.get(k)!=selected[k]]
        req(len(changed)==1,'completed reduction is not a single-class decrement from the prior accepted profile')
        key=changed[0];step=selected[key]-trial[key]
        req(step>0 and trial[key]>=nom[key] and not capcheck(trial),
            f'{r["execution_id"]} is not a valid bounded reduction')
        reductions.append({'id':r['execution_id'],'status':'completed_reused','target':f'{key[0]}/TC{key[1]}',
            'step_bps':step,'viable':r['viable'],'profile_signature':profile_signature(trial),
            'profile':profile_rows(trial,'L2',nom,flows),'calendar_sha256':r['calendar_sha256']})
        if r['viable']:
            selected=trial;selected_run=r;final_id=r['execution_id'];rejected.clear()
        else:rejected.add(key)
    next_ix=len(reduction_runs)+1
    req(next_ix<=13,'registered twelve-reduction budget has already been exhausted')
    queue_waits={(q['queue'].removeprefix('ZonalIVN.').split('.macLayer.queue.queue[')[0],q['tc']):
        (q.get('max_s') or 0,q.get('mean_s') or 0) for q in selected_run.get('queueing_time',[])}
    target=reduction_target(selected,nom,queue_waits,rejected)
    req(target is not None,'no new reduction target is admissible under the registered rule')
    step=min(round(.02*cbs.capacity_bps(target[0])),selected[target]-nom[target])
    trial=dict(selected);trial[target]-=step;trial_sig=profile_signature(trial)
    interrupted_id=f'reduction_{next_ix:02d}'
    interrupted=OUT/f'calibration/C3/L2/A1/seed41/{interrupted_id}'
    vec=next(interrupted.glob('*.vec'),None) if interrupted.exists() else None
    req(vec is not None,f'{interrupted_id} partial vector missing; refusing to infer the interrupted profile')
    import re
    partial=dict(nom);pat=re.compile(r'^config \*\.(.*?)\.macLayer\.queue\.transmissionSelectionAlgorithm\[(\d+)\]\.idleSlope ([0-9.eE+-]+)bps$')
    for line in vec.open(errors='replace'):
        if line.startswith('config cmdenv-event-banners'):break
        match=pat.match(line.strip())
        if match:partial[match.group(1),int(match.group(2))]=round(float(match.group(3)))
    req(partial==trial and profile_signature(partial)==trial_sig,
        f'{interrupted_id} partial effective profile differs from the deterministic next reduction')
    run_dir=interrupted/'Validate_C2_L2_A1-0'
    req((run_dir/'events.csv').is_file(),f'{interrupted_id} calendar file is missing')
    partial_calendar,_=calendar_sig(run_dir)
    index=readj(OUT/'calendars/calendar_index.json');calendar_key='L2/A1/seed41'
    req(partial_calendar==candidate['calendar_sha256']==index[calendar_key]['sha256'],
        f'{interrupted_id} F21/F22 calendar does not match the paired campaign calendar')
    archive_root=OUT/'failed-attempts';archive_root.mkdir(parents=True,exist_ok=True)
    prior_archives=sorted(archive_root.glob(f'{interrupted_id}_interrupted_*'))
    attempt_no=len(prior_archives)+1
    archive=archive_root/f'{interrupted_id}_interrupted_attempt{attempt_no:02d}_20261004'
    req(not archive.exists(),'interrupted reduction archive path already exists; refusing to overwrite evidence')
    archive.mkdir(parents=True)
    shutil.move(str(interrupted),str(archive/'run'))
    audit={'execution_id':interrupted_id,'attempt_number':attempt_no,'status':'interrupted_technical_no_gate',
        'preserved_path':str((archive/'run').relative_to(HERE)),'deterministic_target':f'{target[0]}/TC{target[1]}',
        'step_bps':step,'profile_signature':trial_sig,'calendar_sha256':partial_calendar,
        'vec_sha256':digest(archive/'run'/vec.name),'log_sha256':digest(archive/'run'/'Validate_C2_L2_A1.log'),
        'cause':'no normal simulation completion or gate record; previous boot ended abruptly and journal contains no diagnosed kernel/OOM/I/O cause',
        'counts_against_reduction_budget':False}
    writej(OUT/'audit'/f'{interrupted_id}_interruption_attempt{attempt_no:02d}_20261004.json',audit)
    history=[{'id':r['execution_id'],'status':
        ('completed_historical_incompatible' if int(r['execution_id'].split('_')[-1])<=3
         else 'completed_corrected_search_reused'),'viable':r['viable'],
        'profile_signature':profile_signature(profile_of(r)),'calendar_sha256':r['calendar_sha256']}
        for r in records if str(r.get('execution_id','')).startswith('candidate_')]
    history.append({'id':'candidate_04','status':'interrupted_technical_no_gate',
        'candidate_slot_consumed':True,'preserved_path':'results/calibration/C3/L2/A1/seed41/candidate_04'})
    for ix in range(next_ix,13):
        waits={(q['queue'].removeprefix('ZonalIVN.').split('.macLayer.queue.queue[')[0],q['tc']):
            (q.get('max_s') or 0,q.get('mean_s') or 0) for q in selected_run.get('queueing_time',[])}
        key=reduction_target(selected,nom,waits,rejected)
        if key is None:break
        decrement=min(round(.02*cbs.capacity_bps(key[0])),selected[key]-nom[key])
        proposed=dict(selected);proposed[key]-=decrement;signature=profile_signature(proposed)
        if signature in seen:
            reductions.append({'id':f'reduction_{ix:02d}','status':'rejected_before_execution',
                'target':f'{key[0]}/TC{key[1]}','step_bps':decrement,'profile_signature':signature,
                'reason':'duplicate_profile'});rejected.add(key);continue
        seen.add(signature)
        result=sim('C3',2,1,41,proposed,'calibration',f'reduction_{ix:02d}')
        reductions.append({'id':f'reduction_{ix:02d}','status':'executed','target':f'{key[0]}/TC{key[1]}',
            'step_bps':decrement,'viable':result['viable'],'profile_signature':signature,
            'profile':profile_rows(proposed,'L2',nom,flows),
            'technical_retry_of_interrupted_attempt':ix==next_ix})
        if result['viable']:
            selected=proposed;selected_run=result;final_id=f'reduction_{ix:02d}';rejected.clear()
        else:rejected.add(key)
        writej(OUT/'progress.json',{'campaign_id':'p1-v2-official-2026-10',
            'status':'calibration_reductions_running','phase':f'C3 reductions — {final_id if result["viable"] else f"reduction_{ix:02d}"}',
            'active_process':True,'active_execution_id':f'reduction_{ix:02d}',
            'candidate_slots_consumed':11,'candidate_slots_remaining':13,
            'interrupted_attempts':['candidate_04 (slot consumed; no gate)',
                'reduction_01 (two technical attempts; no gate)',
                f'{interrupted_id} (prior partial attempt; retried as same reduction slot)'],
            'reduction_attempts_completed':ix,'reduction_budget':12,
            'calendar_sha256':candidate['calendar_sha256'],'final_campaign_started':False,
            'updated_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())})
    checks=[{'seed':41,'fixed_profile_id':final_id,'fixed_viable':selected_run['viable'],
        'calendar_paired':selected_run['calendar_sha256']==nominal['calendar_sha256'],
        'reused_execution_id':selected_run['execution_id']}]
    for seed in (43,47):
        control=sim('C2',2,1,seed,nom,'calibration',f'C2_nominal_seed{seed}')
        fixed=sim('C3',2,1,seed,selected,'calibration',f'{final_id}_fixed_seed{seed}')
        checks.append({'seed':seed,'fixed_profile_id':final_id,'nominal_viable':control['viable'],
            'fixed_viable':fixed['viable'],'calendar_paired':control['calendar_sha256']==fixed['calendar_sha256'],
            'nominal_execution_id':control['execution_id'],'fixed_execution_id':fixed['execution_id']})
    accepted=all(x['fixed_viable'] and x['calendar_paired'] for x in checks)
    ratios={f'{e}/TC{tc}':v/nom[(e,tc)] for (e,tc),v in sorted(selected.items())} if accepted else {}
    record={'status':'frozen_and_accepted' if accepted else 'seed41_candidate_failed_additional_verification',
        'calibration_seed41_viable':True,'final_profile_id':final_id if accepted else None,
        'profile_verified_seeds':checks,'calibration_found_feasible_candidate':True,
        'conclusion':'perfil aceito nas seeds 41, 43 e 47' if accepted else
            'houve perfil viável na seed 41, mas falhou na verificação adicional; C3 não entra na matriz final',
        'selected_profile_bps':{f'{e}/TC{tc}':v for (e,tc),v in selected.items()} if accepted else {},
        'frozen_candidate_to_nominal_ratios':ratios,'nominal_run_viable':nominal['viable'],
        'candidate_history':history,'reduction_history':reductions,
        'protocol':readj(HERE/'calibration_protocol.json'),
        'budget':{'max_new_candidate_executions':24,'reductions_max':12,'candidate_executions':11,
            'reduction_attempts':len(reductions),'technical_interrupted_attempts':4,
            'candidate_rejected_before_execution':0,'candidate_positions_not_generated_after_stop':13},
        'resumed_after_process_interruption':True,'reused_profile_id':final_id,
        'interrupted_attempt_preserved':str(archive.relative_to(HERE))}
    writej(OUT/'calibration/C3_calibration.json',record)
    writej(OUT/'progress.json',{'campaign_id':'p1-v2-official-2026-10','status':'calibration_complete',
        'phase':'C3 calibration complete; final campaign starting' if accepted else 'C3 verification failed; final C0-C2 starting',
        'active_process':True,'active_execution_id':None,'calibration_profile_accepted':accepted,
        'calibration_final_profile_id':record['final_profile_id'],'candidate_slots_consumed':11,
        'interrupted_attempts':['candidate_04 (slot consumed; no gate)',
            'reduction_01 (two technical attempts; no gate)',
            f'{interrupted_id} (prior partial attempt; retried as same reduction slot)'],
        'reduction_attempts_completed':len(reductions),'final_campaign_started':False,
        'calendar_sha256':candidate['calendar_sha256'],'updated_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())})
    return record

def write_effective_mapping():
    rows=[]
    nominal_l2={(e,tc):v['bps'] for (load,e,tc),v in nominal_by_load().items() if load==2}
    for f in cbs.read_flows():
        tc=int(f['traffic_class']);cam=f['family']=='camera'
        c1='SP + source camera pre-shaping' if cam else 'SP'
        cbs_mech=('custom CBS TC'+str(tc)+' only where permanent nominal reservation is positive' if tc in (4,6) else 'SP')
        transient_note='transient; excluded from permanent reservation' if f['family']=='transient' else ''
        egresses=[]
        for destination in f['destinations'].split(';'):
          for egress in cbs.route(f['source'],destination):
            if egress not in egresses:egresses.append(egress)
        per_egress=[]
        for egress in egresses:
            rate=nominal_l2.get((egress,tc),0)
            mechanism=(f'CBS_TC{tc}_idleSlope_{rate}bps' if tc in (4,6) and rate>0 else
                       'SP_no_positive_permanent_reservation')
            per_egress.append(f'{egress}:{mechanism}')
        cbs_egresses=';'.join(e for e in egresses if tc in (4,6) and nominal_l2.get((e,tc),0)>0)
        sp_egresses=';'.join(e for e in egresses if tc in (4,6) and nominal_l2.get((e,tc),0)<=0)
        rows.append({'flow_id':f['flow_id'],'source':f['source'],'destinations':f['destinations'],
          'vlan':f['vlan'],'pcp':f['pcp'],'traffic_class':tc,'classification':'identity PCP→TC',
          'route_egresses':' ; '.join(egresses),'C0':'SP','C1':c1,'C2':cbs_mech,
          'C2_CBS_egresses_L2':cbs_egresses,'C2_SP_egresses_L2':sp_egresses,
          'C2_egress_mechanisms_L2':' ; '.join(per_egress),
          'C3':'calibrated CBS only on positive-permanent-reservation egresses' if tc in (4,6) else 'SP',
          'C3_eligible_CBS_egresses':cbs_egresses,
          'CBS_note':transient_note})
    expected={'6':{'F01','F06','F07'},'4':{'F02','F03','F04','F05','F11','F12','F13','F14','F21','F22'},
      '7':{'F08','F09','F10'},'3':{'F15','F16','F17'},'0':{'F18','F19','F20'}}
    req({r['flow_id'] for r in rows}=={f'F{i:02d}' for i in range(1,23)},'effective map does not contain exactly F01-F22')
    for pcp,ids in expected.items():
      req({r['flow_id'] for r in rows if r['pcp']==pcp and str(r['traffic_class'])==pcp}==ids,
          f'effective PCP/TC{pcp} set differs from the current P1')
    with (HERE/'flow_mapping.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)

def calibration(resume=False):
    if RESUME:
        return resume_calibration_after_interruption()
    by=nominal_by_load();nom={ (e,tc):v['bps'] for (l,e,tc),v in by.items() if l==2};flows={(e,tc):v['flows'] for (l,e,tc),v in by.items() if l==2}
    protocol=readj(HERE/'calibration_protocol.json')
    nominal_previous=sim('C2',2,1,41,nom,'calibration','C2_nominal_seed41')
    old_trace=nominal_previous.get('retained',{}).get('queue_occupancy_events')
    audit_repeat_required=not (old_trace and (HERE/old_trace).is_file() and
                               nominal_previous.get('retained',{}).get('queue_occupancy_recalculation_verified'))
    nominal_run=(sim('C2',2,1,41,nom,'calibration','C2_nominal_seed41_retention_audit')
                 if audit_repeat_required else nominal_previous)
    req(nominal_run['calendar_sha256']==nominal_previous['calendar_sha256'],
        'retention audit repeat did not reproduce the existing F21/F22 calendar')
    if audit_repeat_required:
      for field in ('offered_packets','recorded_drops','flow_populations','pending_packet_count_at_simulation_end',
                    'pending_packets_at_simulation_end','camera_source_queue_drops','queue_overflow_drop_total'):
        req(nominal_run.get(field)==nominal_previous.get(field),
            f'retention audit repeat differs from the prior nominal on {field}')
      gate_state=lambda run:{fid:{node:values.get('viable') for node,values in metric['receivers'].items()}
                             for fid,metric in run['qos'].items()}
      req(gate_state(nominal_run)==gate_state(nominal_previous),
          'retention audit repeat changed an existing nominal flow gate')
    history=[{'id':'C2_nominal_seed41','status':'historical_control_missing_independent_occupancy_trace',
       'viable':nominal_previous['viable'],'calendar_sha256':nominal_previous['calendar_sha256'],
       'non_recalculable_from_retained_data':['queue_occupancy_event_series','independent_90pct_time_fraction'],
       'comparison_profiles_and_timestamps_preserved':True},
       {'id':'C2_nominal_seed41_retention_audit' if audit_repeat_required else 'C2_nominal_seed41',
        'status':'reexecuted_only_to_complete_required_occupancy_audit' if audit_repeat_required else 'reused_with_verified_occupancy_trace',
        'viable':nominal_run['viable'],'calendar_sha256':nominal_run['calendar_sha256'],
        'profile':profile_rows(nom,'L2',nom,flows)}]
    chosen=dict(nom);last=nominal_run;found=bool(last['viable']);pid='nominal' if found else None
    # Reconcile the four prior candidate profile identities. Only candidate_01
    # follows the registered deterministic selector. The others remain
    # preserved historical attempts and consume their already allocated slots.
    prior=[];seen_signatures={profile_signature(nom)};profile_by_id={}
    ledger=OUT/'runs.jsonl'
    if ledger.exists():
      for line in ledger.read_text().splitlines():
        r=json.loads(line)
        if r.get('stage')!='calibration' or r.get('campaign_treatment')!='C3' or r.get('seed')!=41:continue
        if not str(r.get('execution_id','')).startswith('candidate_'):continue
        vec={}
        for key,value in r.get('reservation_profile_bps',{}).items():
          e,tc=key.rsplit('/TC',1);vec[e,int(tc)]=int(value)
        sig=profile_signature(vec);seen_signatures.add(sig);profile_by_id[r['execution_id']]=vec
        prior.append({'id':r['execution_id'],'status':'completed_historical','viable':r['viable'],
          'profile_signature':sig,'profile':profile_rows(vec,'L2',nom,flows)})
    # The interrupted candidate_04 has no gate record. Preserve its full-vector
    # identity from the command overrides in its .vec header; it is not resumed
    # as a search proposal unless the corrected selector chooses that same vector.
    partial_dir=OUT/'calibration/C3/L2/A1/seed41/candidate_04'
    partial_vec=next(partial_dir.glob('*.vec'),None) if partial_dir.exists() else None
    if partial_vec:
      text=partial_vec.open(errors='replace').read(2_000_000)
      import re
      partial=dict(nom)
      for match in re.finditer(r'^config\s+\*\.([A-Za-z0-9_.]+)\.macLayer\.queue\.transmissionSelectionAlgorithm\[(\d+)\]\.idleSlope\s+([0-9.eE+-]+)bps\s*$',text,re.M):
        partial[match.group(1),int(match.group(2))]=round(float(match.group(3)))
      sig=profile_signature(partial);seen_signatures.add(sig)
      prior.append({'id':'candidate_04_interrupted','status':'interrupted_technical_no_gate','profile_signature':sig,
        'profile_reconstructed_from_initial_vec_config_overrides':True,'profile':profile_rows(partial,'L2',nom,flows)})
    history.extend(prior)
    # Previous candidate runs do not match the next preregistered proposal.
    # Preserve them, count their four proposal slots, and resume from nominal.
    if prior:
      fail=[fid for fid,q in nominal_run['qos'].items() if any(rx['viable'] is False for rx in q['receivers'].values())]
      fmap={x['flow_id']:x for x in cbs.read_flows()}
      waits={ (q['queue'].removeprefix('ZonalIVN.').split('.macLayer.queue.queue[')[0],q['tc']):(q.get('max_s') or 0,q.get('mean_s') or 0) for q in nominal_run.get('queueing_time',[])}
      first=propose_increment(nom,ordered_candidates(fail,fmap,cbs.route,set(nom),waits),
        {e:cbs.capacity_bps(e) for e,_ in nom},{profile_signature(nom),*(x['profile_signature'] for x in prior)})
      for entry in history:
        if entry.get('id','').startswith('candidate_'):
          entry['search_trajectory_compatible']=False
          entry['reason_incompatible']='Does not match the next proposal under the preregistered global queue-wait ranking; preserved outside the corrected trajectory.'
      history.append({'id':'corrected_search_first_proposal','status':'verified_not_yet_executed',
        'target':f"{first['target'][0]}/TC{first['target'][1]}" if first['target'] else None,
        'profile_signature':first.get('profile_signature'),'step_bps':first.get('step_bps')})
    candidate_executions=4 # four unique proposal slots were already attempted; candidate_04 was technical/incomplete
    candidate_position=4
    blocked=set()
    while not found and candidate_executions<24:
        fail=[fid for fid,q in last['qos'].items() if any(rx['viable'] is False for rx in q['receivers'].values())]
        fmap={x['flow_id']:x for x in cbs.read_flows()}; wait={ (q['queue'].removeprefix('ZonalIVN.').split('.macLayer.queue.queue[')[0],q['tc']):(q.get('max_s') or 0,q.get('mean_s') or 0) for q in last.get('queueing_time',[])}
        candidates=ordered_candidates(fail,fmap,cbs.route,set(nom),wait,blocked)
        proposal=propose_increment(chosen,candidates,{e:cbs.capacity_bps(e) for e,_ in nom},seen_signatures)
        for reject in proposal['rejections']:
          history.append({'id':f'proposal_rejected_{len(history)+1:03d}','status':'rejected_before_execution',**reject})
        if proposal['profile'] is None:
            history.append({'id':f'candidate_position_{candidate_position+1:02d}','status':'not_generated','reason':proposal['stop_reason']})
            break
        candidate_position+=1;candidate_id=f'candidate_{candidate_position:02d}'
        trial=proposal['profile'];e,tc=proposal['target'];fid=proposal['flow_id'];step=proposal['step_bps']
        # Each new unique proposal occupies one preregistered slot; technical
        # retry attempts are tracked separately by sim() and do not expand it.
        candidate_executions+=1;seen_signatures.add(proposal['profile_signature'])
        r=sim('C3',2,1,41,trial,'calibration',candidate_id)
        history.append({'id':candidate_id,'status':'executed','target':f'{e}/TC{tc}','failed_flow_target':fid,'step_bps':step,
          'profile_signature':proposal['profile_signature'],'viable':r['viable'],'profile':profile_rows(trial,'L2',nom,flows)})
        chosen=trial;last=r;found=bool(r['viable']);pid=candidate_id if found else None
    reductions=[];reduction_attempts=0;rejected_reduction_targets=set()
    if found:
        while reduction_attempts<12:
            waits={ (q['queue'].removeprefix('ZonalIVN.').split('.macLayer.queue.queue[')[0],q['tc']):(q.get('max_s') or 0,q.get('mean_s') or 0) for q in last.get('queueing_time',[])}
            key=reduction_target(chosen,nom,waits,rejected_reduction_targets)
            if key is None:break
            e,tc=key;excess=chosen[key]-nom[key];step=min(round(.02*cbs.capacity_bps(e)),excess)
            reduction_attempts+=1;ix=reduction_attempts
            trial=dict(chosen);trial[e,tc]-=step
            sig=profile_signature(trial)
            if sig in seen_signatures:
                reductions.append({'id':f'reduction_{ix:02d}','status':'rejected_before_execution',
                  'target':f'{e}/TC{tc}','step_bps':step,'reason':'duplicate_profile','profile_signature':sig})
                rejected_reduction_targets.add((e,tc));continue
            seen_signatures.add(sig)
            r=sim('C3',2,1,41,trial,'calibration',f'reduction_{ix:02d}')
            reductions.append({'id':f'reduction_{ix:02d}','target':f'{e}/TC{tc}','step_bps':step,'viable':r['viable'],
                'profile_signature':sig,'profile':profile_rows(trial,'L2',nom,flows)})
            if r['viable']:
                chosen=trial;last=r;pid=f'reduction_{ix:02d}';rejected_reduction_targets.clear()
            else:rejected_reduction_targets.add((e,tc))
    checks=[]
    if found:
        for seed in (43,47):
            c2run=sim('C2',2,1,seed,nom,'calibration',f'C2_nominal_seed{seed}')
            c3run=sim('C3',2,1,seed,chosen,'calibration',f'{pid}_fixed_seed{seed}')
            checks.append({'seed':seed,'fixed_profile_id':pid,'nominal_viable':c2run['viable'],'fixed_viable':c3run['viable'],
              'calendar_paired':c2run['calendar_sha256']==c3run['calendar_sha256']})
    accepted=bool(found and len(checks)==2 and all(x['fixed_viable'] and x['calendar_paired'] for x in checks))
    ratios={f'{e}/TC{tc}':v/nom[(e,tc)] for (e,tc),v in sorted(chosen.items())} if accepted else {}
    status=('frozen_and_accepted' if accepted else
            'seed41_candidate_failed_additional_verification' if found else
            'none_candidate_viable_by_defined_search')
    record={'status':status,
      'calibration_seed41_viable':found,'final_profile_id':pid if accepted else None,'profile_verified_seeds':checks,
      'calibration_found_feasible_candidate':found,
      'conclusion':('perfil aceito nas seeds 41, 43 e 47' if accepted else
        'nenhum candidato viável encontrado pela busca definida' if not found else
        'houve perfil viável na seed 41, mas não passou a verificação adicional; C3 não será incluído na matriz final'),
      'selected_profile_bps':{f'{e}/TC{tc}':v for (e,tc),v in chosen.items()} if accepted else {},
      'frozen_candidate_to_nominal_ratios':ratios,'nominal_run_viable':nominal_run['viable'],
      'candidate_history':history,'reduction_history':reductions,'protocol':protocol,
      'budget':{'max_new_candidate_executions':24,'reductions_max':12,
        'candidate_executions':candidate_executions,'candidate_rejected_before_execution':sum(x['status']=='rejected_before_execution' for x in history),
        'candidate_positions_recorded':sum(x['status'] in ('executed','rejected_before_execution') for x in history),
        'candidate_positions_not_generated_after_stop':max(0,24-candidate_executions),
        'reduction_attempts':reduction_attempts,'reduction_rejected_or_nonviable':sum(x.get('viable') is False for x in reductions),
        'reduction_preexecution_rejections':sum(x.get('status')=='rejected_before_execution' for x in reductions)},
      'claim':'No global optimum is implied by the bounded search.'}
    writej(OUT/'calibration/C3_calibration.json',record);return record

def final_campaign(cal, execute_treatments=None):
    execute_treatments=set(execute_treatments if execute_treatments is not None else ('C0','C1','C2','C3'))
    accepted=cal['status']=='frozen_and_accepted'; by=nominal_by_load();inadmissible=[]
    for t in ('C0','C1','C2','C3'):
      if t not in execute_treatments:
        continue
      for l in range(4):
       for a in range(2):
        if t=='C3' and (not accepted or l==3):
            continue
        profile=None
        if t=='C2':profile={(e,tc):v['bps'] for (ll,e,tc),v in by.items() if ll==l}
        if t=='C3':
            profile={}
            for k,ratio in cal['frozen_candidate_to_nominal_ratios'].items():
                e,tc=k.rsplit('/TC',1);profile[e,int(tc)]=round(by.get((l,e,int(tc)),{'bps':0})['bps']*ratio)
            bad=capcheck(profile)
            if bad:
                inadmissible.append({'treatment':'C3','load':LOADS[l],'aggregation':f'A{a}','status':'reservation_inadmissible','ports':bad,'simulated':False});continue
        # Bound the queue to one cell and at most one future per worker. This
        # limits memory retained by the Python executor and makes cell-boundary
        # pausing/recovery explicit while preserving the preregistered order.
        completed=0;seeds=iter(SEEDS)
        check_resources_for_jobs(RUNTIME_WORKERS)
        with ThreadPoolExecutor(max_workers=RUNTIME_WORKERS) as pool:
            pending={}
            for _ in range(RUNTIME_WORKERS):
                try:seed=next(seeds)
                except StopIteration:break
                check_resources_for_jobs(len(pending)+1)
                future=pool.submit(sim,t,l,a,seed,profile,'final');pending[future]=seed
            while pending:
                done,_=wait(pending,return_when=FIRST_COMPLETED)
                for future in done:
                    seed=pending.pop(future);future.result();completed+=1
                    try:next_seed=next(seeds)
                    except StopIteration:continue
                    check_resources_for_jobs(len(pending)+1)
                    new_future=pool.submit(sim,t,l,a,next_seed,profile,'final');pending[new_future]=next_seed
        cell=f'{t}_{LOADS[l]}_A{a}'
        ledger_count=len(LEDGER_INDEX)
        writej(OUT/'checkpoint.json',{'campaign_id':'p1-v2-official-2026-10','stage':'final',
          'active_process':True,'executor_pid':os.getpid(),'active_execution_ids':[],
          'completed_ledger_records':ledger_count,'completed_seeds_in_last_cell':completed,
          'latest_completed_cell':cell,'free_gb':free_gb(),'timestamp':time.time(),
          'max_parallel_runs':RUNTIME_WORKERS,'pause_boundary':'cell'})
        progress=readj(OUT/'progress.json') if (OUT/'progress.json').exists() else {}
        progress.update({'status':'final_campaign_running','phase':'C0-C3 official matrix running',
          'latest_completed_cell':cell,'completed_seeds_in_last_cell':completed,
          'updated_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())})
        if STOP_AFTER_CELL==cell:
            progress.update({'status':'paused_at_cell_boundary','active_process':False,
              'paused_after_cell':cell,'updated_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())})
            writej(OUT/'progress.json',progress)
            writej(OUT/'checkpoint.json',{'campaign_id':'p1-v2-official-2026-10','stage':'final',
              'active_process':False,'executor_pid':os.getpid(),'active_execution_ids':[],
              'completed_ledger_records':ledger_count,'latest_completed_cell':cell,
              'free_gb':free_gb(),'timestamp':time.time(),'max_parallel_runs':RUNTIME_WORKERS,
              'pause_boundary':'cell','status':'paused_at_cell_boundary'})
            return
    for a in range(2):
      inadmissible.append({'treatment':'C3','load':'L3','aggregation':f'A{a}',
        'status':'reservation_frontier_inadmissible','simulated':False,
        'reason':'CSW→HPC permanent TC4+TC6 demand exceeds 75% of 1 Gb/s under the frozen mapping'})
    # Rebuild from the ledger so a resumed process includes prior completed runs.
    if (OUT/'runs.jsonl').exists():
        ledger=[json.loads(x) for x in (OUT/'runs.jsonl').read_text().splitlines() if x.strip()]
        reports=[r for r in ledger if r.get('stage')=='final']
    if SELECTED_TREATMENTS is not None:
      shard_path=OUT/'shard_manifest.json'
      shard=readj(shard_path)
      expected_ids=set()
      for treatment in SELECTED_TREATMENTS:
        loads_for_treatment=('L0','L1','L2') if treatment=='C3' else LOADS
        for load_name in loads_for_treatment:
          for alignment in ('A0','A1'):
            for seed in SEEDS:
              expected_ids.add(f'{treatment}_{load_name}_{alignment}_seed{seed}')
      shard_rows=[r for r in reports if r.get('campaign_treatment') in SELECTED_TREATMENTS]
      actual_ids=[r.get('execution_id') for r in shard_rows]
      req(len(actual_ids)==len(set(actual_ids)), 'duplicate final IDs in this shard ledger')
      require_ids=set(actual_ids)
      shard['expected_final_records']=len(expected_ids)
      shard['completed_final_records']=len(require_ids & expected_ids)
      shard['missing_final_ids']=sorted(expected_ids-require_ids)
      shard['unexpected_final_ids']=sorted(require_ids-expected_ids)
      shard['all_records_technically_valid']=all(r.get('simulation_valid') is True for r in shard_rows)
      shard['status']='completed' if (require_ids==expected_ids and shard['all_records_technically_valid']) else 'incomplete_resumable'
      shard['final_ledger_sha256']=digest(OUT/'runs.jsonl')
      shard['updated_utc']=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
      writej(shard_path,shard)
    expected=3 * 8 * len(SEEDS)
    if accepted:
      expected += 6 * len(SEEDS) # C3/L0-L2/A0-A1, screened below for inadmissibility.
      bad_cells={(x['load'],x['aggregation']) for x in inadmissible
                 if x['treatment']=='C3' and x['load']!='L3'}
      expected -= len(bad_cells)*len(SEEDS)
    matrix=[]
    for t in ('C0','C1','C2','C3'):
      for l in LOADS:
       for a in ('A0','A1'):
        rr=[r for r in reports if r['campaign_treatment']==t and r['load_name']==l and r['aggregation_name']==a]
        if t=='C3' and l=='L3':status='reservation_frontier_inadmissible'
        elif t=='C3' and not accepted:status='not_run_calibration_not_accepted'
        elif t=='C3' and any(x['treatment']=='C3' and x['load']==l and x['aggregation']==a for x in inadmissible):status='reservation_inadmissible'
        elif len(rr)==len(SEEDS):status='complete'
        elif rr:status='incomplete'
        else:status='not_started'
        matrix.append({'treatment':t,'load':l,'aggregation':a,'status':status,'completed_seeds':len(rr),'expected_seeds':len(SEEDS),'simulated':bool(rr)})
    final={'manifest':MANIFEST,'calibration':cal,'expected_runs':expected,'matrix':matrix,
      'completed_runs':len(reports),'runs':reports,'inadmissible_cells':inadmissible,'c4_executed':False,
      'historical_results_included':False,'pilot_included':False,'complete':len(reports)==expected}
    writej(OUT/'campaign_results.json',final);make_comparison(final)

def make_comparison(data):
    runs=data['runs'];by={(r['campaign_treatment'],r['load_name'],r['aggregation_name'],r['seed']):r for r in runs}
    contrasts={};flow_effects={};alignment_effects={}
    def stats(delta,base):
      if not delta:return {'n_paired':0,'mean_absolute_change':None,'mean_relative_change_percent':None,'ci95_t':None}
      m=statistics.mean(delta);sd=statistics.stdev(delta) if len(delta)>1 else 0
      half=2.045*sd/math.sqrt(len(delta)) if len(delta)>1 else None
      bm=statistics.mean(base) if base else 0
      return {'n_paired':len(delta),'mean_absolute_change':m,'mean_relative_change_percent':100*m/bm if bm else None,
        'ci95_t':[m-half,m+half] if half is not None else None}
    def value(run,flow_receiver,name):
      fid,node=flow_receiver.split('/',1);rs=run.get('qos',{}).get(fid,{}).get('receivers',{});r=rs.get(node,{})
      if name=='packet_p99_s':return (r.get('latency') or {}).get('p99_s')
      if name=='packet_max_s':return (r.get('latency') or {}).get('max_s')
      if name=='packet_deadline_miss_ratio':return r.get('deadline_miss_ratio_including_loss')
      if name=='image_p99_s':return (r.get('image_completion') or {}).get('p99_s')
      if name=='image_deadline_miss_ratio':return (r.get('image_completion') or {}).get('deadline_miss_ratio_including_missing_images')
      return r.get('goodput_payload_ratio')
    for l in LOADS:
      for a in ('A0','A1'):
        key=f'{l}/{a}';contrasts[key]={}
        for left,right in [('C1','C0'),('C2','C0'),('C3','C2')]:
          deltas=[]
          for seed in SEEDS:
            if (left,l,a,seed) not in by or (right,l,a,seed) not in by:continue
            L=by[left,l,a,seed]['viable'];R=by[right,l,a,seed]['viable'];deltas.append(int(L)-int(R))
          if deltas:
            mean=statistics.mean(deltas);sd=statistics.stdev(deltas) if len(deltas)>1 else 0
            half=2.045*sd/math.sqrt(len(deltas)) if len(deltas)>1 else None
            contrasts[key][f'{left}_minus_{right}_viability']={'n_paired':len(deltas),'mean_cell_viability_difference':mean,
              'ci95_t_approx':[mean-half,mean+half] if half is not None else None}
          all_flows=sorted({f'{fid}/{node}' for r in runs for fid,q in r.get('qos',{}).items() for node in q.get('receivers',{})})
          flow_effects.setdefault(key,{})[f'{left}_minus_{right}']={}
          for fid in all_flows:
            flow_effects[key][f'{left}_minus_{right}'][fid]={}
            for metric in ('packet_p99_s','packet_max_s','packet_deadline_miss_ratio','image_p99_s','image_deadline_miss_ratio','goodput_payload_ratio'):
              ds=[];bs=[]
              for seed in SEEDS:
                if (left,l,a,seed) in by and (right,l,a,seed) in by:
                  x=value(by[left,l,a,seed],fid,metric);y=value(by[right,l,a,seed],fid,metric)
                  if x is not None and y is not None:ds.append(x-y);bs.append(y)
              flow_effects[key][f'{left}_minus_{right}'][fid][metric]=stats(ds,bs)
    # P1 H2: aligned minus staggered patterns at L2/L3 for C0 and C1.
    for l in ('L2','L3'):
      alignment_effects[l]={}
      for t in ('C0','C1'):
        alignment_effects[l][t]={}
        for fid in sorted({f'{fid}/{node}' for r in runs for fid,q in r.get('qos',{}).items() for node in q.get('receivers',{})}):
          alignment_effects[l][t][fid]={}
          for metric in ('packet_p99_s','packet_max_s','packet_deadline_miss_ratio','image_p99_s','image_deadline_miss_ratio','goodput_payload_ratio'):
            ds=[];bs=[]
            for seed in SEEDS:
              if (t,l,'A1',seed) in by and (t,l,'A0',seed) in by:
                x=value(by[t,l,'A1',seed],fid,metric);y=value(by[t,l,'A0',seed],fid,metric)
                if x is not None and y is not None:ds.append(x-y);bs.append(y)
            alignment_effects[l][t][fid][metric]=stats(ds,bs)
    result={'campaign':'p1-v2-official-2026-10','manifest':data['manifest'],'calibration':data['calibration'],
      'executed_runs':len(runs),'expected_runs':data['expected_runs'],'complete':data['complete'],
      'inadmissible_cells':data['inadmissible_cells'],'paired_cell_level_contrasts':contrasts,
      'paired_flow_metric_effects':flow_effects,'alignment_A1_minus_A0_L2_L3':alignment_effects,
      'runs':runs,'historical_results_excluded':True,'pilot_excluded':True,'C4_executed':False}
    by_load=nominal_by_load()
    if data['calibration'].get('calibration_found_feasible_candidate'):
      l2nom={(e,tc):v['bps'] for (ll,e,tc),v in by_load.items() if ll==2}
      chosen={}
      for k,v in data['calibration'].get('selected_profile_bps',{}).items():
        e,tc=k.rsplit('/TC',1);chosen[e,int(tc)]=int(v)
      frows={(e,tc):v['flows'] for (ll,e,tc),v in by_load.items() if ll==2}
      result['final_calibration_profile_L2']=profile_rows(chosen,'L2',l2nom,frows)
    else:result['final_calibration_profile_L2']=[]
    result['retention_inventory']={'bytes':sum(p.stat().st_size for p in OUT.rglob('*') if p.is_file()),
      'free_disk_gb':free_gb(),'raw_vectors_policy':'deleted only after per-run validation and compact exact tail extraction',
      'max_parallel_runs':RUNTIME_MAX_WORKERS,
      'runtime_concurrency_addendum':'user-authorized cap of four jobs; preregistered eight-job operational limit retained in calibration_protocol.json and history'}
    writej(OUT/'comparison.json',result)
    lines=['# Campanha oficial C0–C3 — P1 vigente','',
      f"Status: {'completa' if data['complete'] else 'incompleta'} ({len(runs)}/{data['expected_runs']} execuções). Piloto e históricos excluídos. C4 não executado.",'',
      f"Calibração C3: `{data['calibration']['status']}`, perfil final `{data['calibration'].get('final_profile_id')}`. C3/L3 não simulado conforme a triagem de reserva.",'',
      '## Mapeamento e matriz','','Veja `flow_mapping.csv` para PCP→TC e mecanismos efetivos por fluxo. O JSON discrimina células completas, não iniciadas, incompletas e inadmissíveis; cada célula admissível requer as 30 seeds pareadas. Reserva CBS é TC6/TC4 customizada, FIFO por classe; o comparativo não assume contratos SR padronizados.','',
      '## Calibração e reservas','','O histórico completo distingue controle nominal, candidatos executados, rejeições prévias à execução e posições não geradas. Quando houve perfil aceito, `comparison.json` exporta `idleSlope`, soma por porta, fração da taxa, margem ao teto de 75% e razão candidato/nominal por egress/TC.','',
      '## Comparações pareadas','','A unidade experimental é a execução. O JSON contém deltas absolutos e relativos pareados por seed, com IC t de 95% para viabilidade e métricas por fluxo. Latência e misses de câmeras são separados em pacote e imagem. H1 é examinada em L0/A0 nos tratamentos disponíveis C0–C3; H2 por A1−A0 em C0/C1 a L2/L3 e por C1−C0; H3 por C3−C2 em L2, se C3 for aceito. ICs são descritivos e não substituem os gates.','',
      '## Células inadmissíveis/incompletas','',json.dumps(data['inadmissible_cells'],indent=2),'',
      'A campanha só pode ser declarada concluída quando todas as células admissíveis tiverem 30 execuções e todas as verificações de pareamento e auditoria passarem.']
    (OUT/'analysis.md').write_text('\n'.join(lines)+'\n')

def metadata():
    files=['simulations/campaigns/p1-v2-official-2026-10/run_campaign.py',
      'simulations/campaigns/p1-v2-official-2026-10/run_official_campaign.py',
      'simulations/campaigns/p1-v2-official-2026-10/prepare_parallel_campaign.py',
      'simulations/campaigns/p1-v2-official-2026-10/merge_campaign_shards.py',
      'simulations/campaigns/p1-v2-official-2026-10/calibration_search.py',
      'simulations/campaigns/p1-v2-official-2026-10/calibration_protocol.json',
      'simulations/campaigns/p1-v2-official-2026-10/flow_mapping.csv',
      'simulations/zonal/traffic/flows.csv','simulations/zonal/traffic/transients.csv','simulations/zonal/traffic/catalog.xml',
      'simulations/zonal/configs/catalog-bindings.ini','simulations/zonal/configs/classification.ini',
      'simulations/zonal/configs/mechanisms/C0_strict_priority.ini','simulations/zonal/configs/mechanisms/C1_source_preshaping.ini',
      'simulations/zonal/configs/mechanisms/C2_nominal_rates.ini','simulations/zonal/configs/mechanisms/C2_nominal_cbs.ini',
      'simulations/zonal/traffic/cbs_nominal_reservations.csv',
      'simulations/omnetpp.ini','scripts/catalog/generate.py','scripts/catalog/generate_cbs.py',
      'scripts/run/validate_c0.py','scripts/run/validate_c2.py','scripts/run/validate_c3.py',
      'tests/validation/traffic/check_traffic.py','src/zonal-ivn-tsn']
    for directory in (ROOT/'src',ROOT/'simulations/zonal/configs'):
      for path in directory.rglob('*'):
        if path.is_file() and path.suffix in ('.cc','.h','.ned','.msg','.ini','.xml'):
          files.append(str(path.relative_to(ROOT)))
    files=sorted(set(files))
    status=subprocess.check_output(['git','status','--short'],cwd=ROOT,text=True)
    current_p1=ROOT/'docs/design/P1-final.pdf';previous_p1=ROOT/'docs/design/P1-v4.pdf'
    return {'campaign_id':'p1-v2-official-2026-10','p1_pdf':str(current_p1.relative_to(ROOT)),
      'p1_pdf_sha256':digest(current_p1),
      'previous_p1_pdf':str(previous_p1.relative_to(ROOT)),
      'previous_p1_pdf_sha256':digest(previous_p1),
      'p1_clarification':{'transient_only_TC4_egresses':['Z1.ZCPU.eth[0]','Z2.ZCPU.eth[0]','Z3.ZSW.eth[1]'],
        'mechanism':'SP when permanent nominal reservation is zero; F21/F22 remain PCP4/TC4 and share CBS only on egresses with positive permanent TC4 reservation',
        'configuration_matches_audited_runs_and_pilot':True},
      'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
      'local_changes':status,'working_tree_clean':not bool(status.strip()),
      'reproduction_commands':['source /home/jonatan/omnetpp-env.sh',
        'export INET_ROOT=/home/jonatan/omnetpp/samples/inet-4.7.0',
        'python3 simulations/campaigns/p1-v2-official-2026-10/run_campaign.py --phase calibration',
        'python3 simulations/campaigns/p1-v2-official-2026-10/run_campaign.py --phase final --resume'],
      'source_hashes':{p:digest(ROOT/p) for p in files},'omnetpp':'6.4.0','inet':'4.7.0',
      'binary_sha256':digest(ROOT/'src/zonal-ivn-tsn'),
      'inet_version_token':(INET/'Version').read_text().strip(),'inet_version_file_sha256':digest(INET/'Version'),
      'omnetpp_runtime_version':next(line for line in subprocess.check_output(
        [str(OMNETPP/'bin/opp_run'),'-v'],text=True,stderr=subprocess.STDOUT).splitlines()
        if line.startswith('Version:')),
      'matrix':{'treatments':['C0','C1','C2','C3'],'loads':list(LOADS),'alignments':['A0','A1'],'seeds':list(SEEDS),
         'warmup_s':1,'measurement_s':30,'drain_s':0.05,'C3_L3':'inadmissible reservation boundary; not simulated','C4':'excluded'},
      'mapping':{'PCP6_TC6':['F01','F06','F07'],'PCP4_TC4':['F02','F03','F04','F05','F11','F12','F13','F14','F21','F22'],
        'PCP7_TC7':['F08','F09','F10'],'PCP3_TC3':['F15','F16','F17'],'PCP0_TC0':['F18','F19','F20']},
      'queueing':{'FIFO_per_TC':True,'strict_priority_descending':True,'preemption':False,'CBS_custom_TCs':[6,4],
        'CBS_enabled_only_for_positive_permanent_nominal_reservation':True,
        'transient_only_TC4_uses_SP':['Z1.ZCPU.eth[0]','Z2.ZCPU.eth[0]','Z3.ZSW.eth[1]'],
        'standard_SR_contracts_claimed':False,'buffer_bytes_per_class':{'camera_talker_ports':65536,'G1_G4':131072,'others':32768}}}

def parse_treatments(value):
    if value is None:return None
    selected=tuple(x.strip() for x in value.split(',') if x.strip())
    req(selected and len(selected)==len(set(selected)), '--treatments must be a nonempty comma-separated unique list')
    req(set(selected)<= {'C0','C1','C2','C3'}, '--treatments may contain only C0,C1,C2,C3')
    return selected

def calendar_contract_digest(index_path):
    index=readj(index_path)
    contract={}
    for key,row in sorted(index.items()):
        path=HERE/row['file']
        req(path.is_file(),f'calendar contract references missing file: {path}')
        signature,event_rows=calendar_sig(path)
        req(signature==row.get('sha256') and len(event_rows)==int(row.get('event_count',-1)),
            f'calendar contract mismatch for {key}')
        contract[key]={'sha256':signature,'event_count':len(event_rows),'file_sha256':digest(path)}
    return hashlib.sha256(json.dumps(contract,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def campaign_contract_digest(manifest):
    fields=('campaign_id','commit','source_hashes','binary_sha256','omnetpp','inet',
            'inet_version_token','inet_version_file_sha256','omnetpp_runtime_version',
            'p1_pdf_sha256','previous_p1_pdf_sha256','matrix','mapping','queueing')
    payload={key:manifest.get(key) for key in fields}
    return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def main():
    global ENV,INET,OMNETPP,MANIFEST,RESUME,RUNTIME_WORKERS,STOP_AFTER_CELL,SELECTED_TREATMENTS,SHARD_ID
    p=argparse.ArgumentParser();p.add_argument('--inet-root',default=os.environ.get('INET_ROOT'));p.add_argument('--omnetpp-root',default=os.environ.get('OMNETPP_ROOT'))
    p.add_argument('--phase',choices=['calibration','final','all'],default='all');p.add_argument('--resume',action='store_true')
    p.add_argument('--jobs',type=int,default=1,help=f'parallel simulations (1..{RUNTIME_MAX_WORKERS}, additionally capped by available memory)')
    p.add_argument('--stop-after-cell',help='finish and checkpoint this cell, then exit cleanly (e.g. C0_L3_A1)')
    p.add_argument('--treatments',help='final-matrix subset, comma separated (e.g. C1,C2); requires --shard-id')
    p.add_argument('--shard-id',help='stable identifier for this machine-local result shard')
    a=p.parse_args();RESUME=a.resume;RUNTIME_WORKERS=a.jobs;STOP_AFTER_CELL=a.stop_after_cell
    SELECTED_TREATMENTS=parse_treatments(a.treatments);SHARD_ID=a.shard_id
    if SELECTED_TREATMENTS is not None:
        req(a.phase=='final','--treatments is supported only with --phase final')
        req(SHARD_ID and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}',SHARD_ID),
            'a safe --shard-id is required with --treatments')
    else:
        req(SHARD_ID is None,'--shard-id requires --treatments')
    req(1<=RUNTIME_WORKERS<=RUNTIME_MAX_WORKERS,
        f'--jobs must be between 1 and {RUNTIME_MAX_WORKERS} under the current runtime cap')
    check_resources_for_jobs(RUNTIME_WORKERS)
    req(a.inet_root,'Set INET_ROOT')
    INET=Path(a.inet_root).resolve();OMNETPP=Path(a.omnetpp_root).resolve() if a.omnetpp_root else Path(shutil.which('opp_run')).resolve().parent.parent
    ENV=os.environ.copy();ENV['LD_LIBRARY_PATH']=':'.join(filter(None,[str(OMNETPP/'lib'),str(INET/'src'),ENV.get('LD_LIBRARY_PATH','')]))
    OUT.mkdir(parents=True,exist_ok=True)
    acquire_campaign_lock()
    recover_ledger()
    startup_progress=readj(OUT/'progress.json') if (OUT/'progress.json').exists() else {}
    startup_progress.update({'active_process':True,'executor_pid':os.getpid(),
      'runtime_workers':RUNTIME_WORKERS,'cpu_affinity':'all scheduler-available CPUs',
      'process_priority':'normal (no taskset/nice/ionice throttling)',
      'updated_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())})
    writej(OUT/'progress.json',startup_progress)
    writej(OUT/'checkpoint.json',{'campaign_id':'p1-v2-official-2026-10','stage':a.phase,
      'active_process':True,'executor_pid':os.getpid(),'active_execution_ids':[],
      'completed_ledger_records':len(LEDGER_INDEX),'free_gb':free_gb(),'timestamp':time.time(),
      'max_parallel_runs':RUNTIME_WORKERS,'status':'starting_or_resuming'})
    protocol_path=HERE/'calibration_protocol.json'
    protocol=predeclared_protocol()
    if protocol_path.exists(): req(readj(protocol_path)==protocol,'predeclared calibration protocol changed; create a new campaign version')
    else:
      req(a.phase in ('calibration','all'),'calibration protocol is absent; run calibration phase before final phase')
      writej(protocol_path,protocol)
    write_effective_mapping()
    mp=HERE/'campaign_manifest.json';current=metadata()
    if mp.exists():
        old=readj(mp)
        for k in ('commit','omnetpp','inet','matrix','mapping','binary_sha256','inet_version_token','inet_version_file_sha256','omnetpp_runtime_version'):
            req(old[k]==current[k],f'manifest mismatch in {k}; refusing reuse')
        req(source_hashes_reusable(old.get('source_hashes',{}),current['source_hashes']),
            'source hash mismatch outside documented orchestration/retention/presentation fixes')
        archive=HERE/'protocol_history';archive.mkdir(exist_ok=True)
        if old.get('continuation'):
            # A two-host contract pins this manifest byte-for-byte. Rewriting it
            # on each resume would invalidate the peer's contract and could also
            # mislabel the migrated snapshot as the original P1-v3 manifest.
            parent_path=HERE/old['continuation']['parent_manifest_path']
            req(parent_path.is_file() and digest(parent_path)==old['continuation']['parent_manifest_sha256'],
                'parallel continuation parent manifest archive is missing or changed')
            protocol_archive=HERE/old.get('preregistered_protocol_archive','__missing__')
            req(protocol_archive.is_file() and digest(protocol_archive)==old.get('preregistered_protocol_sha256'),
                'parallel continuation protocol archive is missing or changed')
            for field in ('previous_manifest_sha256','previous_manifest_path',
                          'preregistered_protocol_sha256','preregistered_protocol_archive'):
                current[field]=old[field]
            current['continuation']=old['continuation']
            MANIFEST=old
        else:
            old_manifest=archive/'campaign_manifest_p1-v3.json'
            old_protocol=archive/'calibration_protocol_preregistered.json'
            if not old_manifest.exists():shutil.copy2(mp,old_manifest)
            if not old_protocol.exists():shutil.copy2(protocol_path,old_protocol)
            current['previous_manifest_sha256']=digest(old_manifest)
            current['previous_manifest_path']=str(old_manifest.relative_to(HERE))
            current['preregistered_protocol_sha256']=digest(protocol_path)
            current['preregistered_protocol_archive']=str(old_protocol.relative_to(HERE))
            MANIFEST=current;writej(mp,MANIFEST)
            addendum={'created_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
              'status':'P1 v4 clarification and technical execution addendum; preregistered search rules unchanged',
              'p1_pdf':current['p1_pdf'],'p1_pdf_sha256':current['p1_pdf_sha256'],
              'previous_p1_pdf':current['previous_p1_pdf'],'previous_p1_pdf_sha256':current['previous_p1_pdf_sha256'],
              'preregistered_protocol_sha256':digest(protocol_path),
              'clarification':'CBS TC4/TC6 only where permanent nominal reservation is positive. Transit-only TC4 egresses remain SP; F21/F22 retain PCP4/TC4 and share CBS only on egresses with positive permanent TC4 load.',
              'technical_fixes':['full 10% line-rate increments with pre-execution 75% rejection','deterministic full-vector signatures and duplicate proposal rejection','no permanent ban on previously changed queues','explicit candidate/reduction IDs and termination when no admissible novel proposal remains','exact queue occupancy change-point trace independently verified before raw vector deletion'],
              'search_method_changed':False}
            writej(archive/'p1-v4-technical-addendum.json',addendum)
    else:MANIFEST=current;writej(mp,MANIFEST)
    subprocess.run([sys.executable,str(ROOT/'scripts/catalog/generate.py'),'--check'],check=True)
    subprocess.run([sys.executable,str(ROOT/'scripts/catalog/generate_cbs.py'),'--check'],check=True)
    if a.phase in ('calibration','all'):
        cal=calibration()
        writej(OUT/'calibration/C3_calibration.json',cal)
    else:
        cal_path=OUT/'calibration/C3_calibration.json';req(cal_path.is_file(),'C3 calibration result missing; run --phase calibration first')
        cal=readj(cal_path)
    if a.phase in ('final','all'):
        progress=readj(OUT/'progress.json') if (OUT/'progress.json').exists() else {}
        progress.update({'status':'final_campaign_running','phase':'C0-C3 official matrix running',
            'active_process':True,'final_campaign_started':True,
            'expected_final_runs':900 if cal.get('status')=='frozen_and_accepted' else 720,
            'updated_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())})
        writej(OUT/'progress.json',progress)
        if SELECTED_TREATMENTS is not None:
            shard_path=OUT/'shard_manifest.json'
            shard={'schema_version':1,'campaign_id':'p1-v2-official-2026-10',
                   'shard_id':SHARD_ID,'treatments':list(SELECTED_TREATMENTS),
                   'commit':MANIFEST['commit'],'binary_sha256':MANIFEST['binary_sha256'],
                   'campaign_contract_sha256':campaign_contract_digest(MANIFEST),
                   'calibration_sha256':digest(OUT/'calibration/C3_calibration.json'),
                   'calendar_contract_sha256':calendar_contract_digest(OUT/'calendars/calendar_index.json'),
                   'status':'running_or_resumable'}
            if shard_path.exists():
                old_shard=readj(shard_path)
                for field in ('schema_version','campaign_id','shard_id','treatments','commit','binary_sha256',
                              'campaign_contract_sha256','calibration_sha256','calendar_contract_sha256'):
                    req(old_shard.get(field)==shard.get(field),
                        f'shard manifest mismatch in {field}; use the original shard identity/artifacts')
            else:writej(shard_path,shard)
        final_campaign(cal,execute_treatments=SELECTED_TREATMENTS)
    # A normal process exit is also reflected durably for the SSH dashboard.
    progress=readj(OUT/'progress.json') if (OUT/'progress.json').exists() else {}
    if progress.get('status')!='paused_at_cell_boundary':
        progress.update({'active_process':False,'updated_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())})
        writej(OUT/'progress.json',progress)
    checkpoint=readj(OUT/'checkpoint.json') if (OUT/'checkpoint.json').exists() else {}
    checkpoint.update({'active_process':False,'executor_pid':os.getpid(),'active_execution_ids':[],
      'completed_ledger_records':len(LEDGER_INDEX),'free_gb':free_gb(),'timestamp':time.time()})
    writej(OUT/'checkpoint.json',checkpoint)
    if LOCK_FD is not None:
        fcntl.flock(LOCK_FD,fcntl.LOCK_UN);os.close(LOCK_FD);LOCK_FD=None
if __name__=='__main__':main()
