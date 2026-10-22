#!/usr/bin/env python3
"""Serial, resumable C4 fixed-profile verification with disk-floor protection."""
from __future__ import annotations
import csv, hashlib, importlib.util, json, os, shutil, subprocess, sys, time, gzip
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
SIM=ROOT/'simulations'
OUT=HERE/'results'
FIXED=SIM/'pilot/c4_fixed_L2_profile'
# Reuse only audited helper code; pin its hash in this pilot's manifest.
spec=importlib.util.spec_from_file_location('fixed_profile_helpers',FIXED/'run_study.py')
r=importlib.util.module_from_spec(spec); sys.modules[spec.name]=r; spec.loader.exec_module(r)
r.HERE=HERE; r.OUT=OUT; r.PILOT_INI=HERE/'pilot.ini'; r.PLUGIN=HERE/'plugin/libc4realclockprobe.so'
r.append_ledger=lambda row: None  # wrapper writes one final direct-tick-corrected ledger row
r.VARIANTS=['D3_fixed_TAS','D3_fixed_noTAS']; r.GATED={'D3_fixed_TAS'}; r.MIN_FREE_GIB=40.0; r.MIN_MEM_GIB=7.0

PROFILE=json.loads((HERE/'frozen_d3_l2_profile.json').read_text())
PROFILE_MAP={k:int(v) for k,v in PROFILE['effective_profile_bps'].items()}
PROFILE_HASH=PROFILE['canonical_sha256']
PLAN=json.loads((HERE/'manifest.json').read_text())
DRIFTS=json.loads((SIM/'pilot/c4_feasibility_decision/results/plan.json').read_text())['dimensioning']['fixed_inputs']['drifts']
PLAN_RUN={'frozen_profile':{'effective_profile_bps':PROFILE_MAP},'profile_sha256':PROFILE_HASH,
          'expected_no_cbs_modules':json.loads((HERE/'treatment_contracts.json').read_text())['expected_no_cbs'],
          'expected_cbs_by_treatment':{},'omnetpp_version':PLAN['runtime']['omnetpp'],'inet_version':PLAN['runtime']['inet'],
          'dimensioning':{'fixed_inputs':{'drifts':DRIFTS}},'calendars':{}}

ORDER=[]
for cell in [('L0','A0'),('L1','A1')]:
 for seed in (43,47): ORDER.append((cell[0],cell[1],seed))
PHASE1_CROSSCHECKS=[('L0','A1',41),('L1','A0',41),('L2','A0',41)]
PHASE2_ORDER=[(load,agg,seed) for load,agg in [('L0','A1'),('L1','A0'),('L2','A0')]
              for seed in (43,47)]


def write_json(path,obj):
 path=Path(path); path.parent.mkdir(parents=True,exist_ok=True); tmp=path.with_suffix(path.suffix+'.tmp')
 with tmp.open('w') as f: json.dump(obj,f,indent=2,sort_keys=True); f.write('\n'); f.flush(); os.fsync(f.fileno())
 tmp.replace(path)

def file_sha(p):
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 return h.hexdigest()

def resources(): return {'free_disk_GiB':r.free_gib(),'MemAvailable_GiB':r.mem_gib()}

def calendar_sig(path):
 sig,rows=r.calendar_signature(Path(path)); return sig,rows

def generate_calendar(load,agg,seed):
 """Run init-only TrafficPlan with an empty calendar; no methodological time advances."""
 cell=f'{load}_{agg}'; cdir=OUT/'calendars'/cell; cdir.mkdir(parents=True,exist_ok=True)
 target=cdir/f'seed{seed}_events.csv'; meta=Path(str(target)+'.json')
 if target.exists() and meta.exists():
  m=json.loads(meta.read_text()); sig,rows=calendar_sig(target)
  if sig==m['signature'] and len(rows)==60:return sig
  raise RuntimeError(f'Existing calendar does not match its frozen metadata: {target}')
 if r.free_gib()<r.MIN_FREE_GIB+4 or r.mem_gib()<r.MIN_MEM_GIB: raise RuntimeError('Resource floor prevents calendar initialization')
 empty=OUT/'calendar_generation'/'empty_calendar.csv'; empty.parent.mkdir(parents=True,exist_ok=True)
 # Generate once per cell/seed from the same OMNeT RNG streams and TrafficPlan as treatment runs.
 base=OUT/'calendar_generation'/f'{cell}_seed{seed}'; gen=base; attempt=0
 while gen.exists():
  attempt+=1; gen=Path(str(base)+f'_attempt_{attempt:03d}')
 gen.mkdir(parents=True,exist_ok=False)
 profile=PROFILE_MAP
 config,args=r.sim_args('D3_fixed_TAS',gen,seed,profile,empty,PLAN_RUN,load,agg)
 args=[x for x in args if not x.startswith('--*.trafficPlan.transientCalendarFile=')]
 args += ['--*.trafficPlan.transientCalendarFile=""','--sim-time-limit=0s']
 env=os.environ.copy(); env['LD_LIBRARY_PATH']=':'.join([str(r.OMNET/'lib'),str(r.INET/'src'),env.get('LD_LIBRARY_PATH','')]).rstrip(':')
 cmd=[str(ROOT/'src/zonal-ivn-tsn')]+args
 log=gen/f'{config}-calendar-init.log'
 with log.open('w') as f: p=subprocess.run(cmd,cwd=SIM,env=env,stdout=f,stderr=subprocess.STDOUT,timeout=180)
 # TrafficPlan outputDirectory resolves beneath result-dir/config/runnumber.
 candidates=list(gen.rglob('events.csv'))
 if p.returncode or len(candidates)!=1: raise RuntimeError(f'Calendar-only initialization failed; rc={p.returncode}, events={len(candidates)}, log={log}')
 shutil.copy2(candidates[0],target)
 sig,rows=calendar_sig(target)
 if len(rows)!=60 or {x['flow'] for x in rows}!={'F21','F22'}: raise RuntimeError('Generated calendar population invalid')
 write_json(meta,{'cell':cell,'seed':seed,'signature':sig,'event_count':len(rows),'source':'TrafficPlan init-only with empty transientCalendarFile; dedicated seeded RNGs; no simulated time advanced','source_file_sha256':file_sha(target),'command':cmd,'log_sha256':file_sha(log)})
 PLAN_RUN['calendars'][f'{cell}/seed{seed}']={'signature':sig,'event_count':len(rows),'path':str(target)}
 return sig

def load_existing_calendars():
 # Reuse verified seed-41 and L2 seed-43/47 calendars from the source studies.
 for cell,seeds,base in [('L0_A0',[41],'c4_fixed_L2_profile'),('L1_A1',[41],'c4_fixed_L2_profile'),('L2_A1',[41,43,47],'c4_feasibility_decision')]:
  for seed in seeds:
   src=SIM/'pilot'/base/'results/calendars'/cell/f'seed{seed}_events.csv'
   sig,rows=calendar_sig(src)
   dest=OUT/'calendars'/cell/f'seed{seed}_events.csv'; dest.parent.mkdir(parents=True,exist_ok=True)
   shutil.copy2(src,dest)
   PLAN_RUN['calendars'][f'{cell}/seed{seed}']={'signature':sig,'event_count':len(rows),'path':str(dest)}
   write_json(Path(str(dest)+'.json'),{'cell':cell,'seed':seed,'signature':sig,'event_count':len(rows),'source':str(src.relative_to(ROOT)),'source_sha256':file_sha(src)})

def preflight_cell(load,agg):
 """Resolve CBS and gates at time zero before any measurement run for this config."""
 cell=f'{load}_{agg}'; cal=OUT/'calendars'/cell/'seed41_events.csv'
 if not cal.exists(): cal=OUT/'calendars'/cell/'seed43_events.csv'
 if not cal.exists(): raise RuntimeError(f'No calendar to exercise resolved preflight for {cell}')
 dest=OUT/'preflight'/cell; dest.mkdir(parents=True,exist_ok=True)
 rows=[]
 for variant in ['D3_fixed_TAS','D3_fixed_noTAS']:
  one=dest/variant
  if one.exists():
   record=json.loads((one/'preflight.json').read_text()); rows.append(record); continue
  one.mkdir(parents=True,exist_ok=False)
  config,args=r.sim_args(variant,one,41,PROFILE_MAP,cal,PLAN_RUN,load,agg)
  args.append('--sim-time-limit=0s')
  env=os.environ.copy(); env['LD_LIBRARY_PATH']=':'.join([str(r.OMNET/'lib'),str(r.INET/'src'),env.get('LD_LIBRARY_PATH','')]).rstrip(':')
  cmd=[str(ROOT/'src/zonal-ivn-tsn')]+args
  log=one/f'{config}-preflight.log'
  if r.free_gib()<44 or r.mem_gib()<7: raise RuntimeError(f'Resource floor before preflight: {resources()}')
  with log.open('w') as f: proc=subprocess.run(cmd,cwd=SIM,env=env,stdout=f,stderr=subprocess.STDOUT,timeout=180)
  sca=one/f'{config}-#0.sca'
  if proc.returncode or not sca.is_file(): raise RuntimeError(f'Preflight failed: {variant}/{cell}, rc={proc.returncode}, {log}')
  cbs=r.profile_sca_check(sca,PROFILE_MAP,require_credit_statistics=False)
  gate=(r.gcl_check(sca,variant) if variant=='D3_fixed_TAS' else r.no_tas_check(sca,one/'no-packet-trace.csv'))
  logtext=log.read_text(errors='replace')
  if not cbs['pass'] or gate.get('status')!='pass' or '<!> Error:' in logtext:
   raise RuntimeError(f'Preflight contract failed {variant}/{cell}: CBS={cbs["pass"]}, gates={gate.get("status")}')
  row={'variant':variant,'cell':cell,'methodological_execution':False,'returncode':proc.returncode,
       'calendar_sha256':calendar_sig(cal)[0],'profile_sha256':PROFILE_HASH,'cbs_validation':cbs,
       'gate_validation':gate,'sca_sha256':file_sha(sca),'log_sha256':file_sha(log),'resource_after':resources()}
  write_json(one/'preflight.json',row); rows.append(row)
 write_json(dest/'preflight_summary.json',{'status':'pass','cell':cell,'treatments':rows})

def run_pair(load,agg,seed):
 cell=f'{load}_{agg}'; logicals=[f'D3_fixed_TAS_{cell}_seed{seed}',f'D3_fixed_noTAS_{cell}_seed{seed}']
 # Sizing uses completed same-cell pairs when available; includes a 25% safety factor and temporary raw-output headroom.
 reference={'L0':3.3,'L1':3.9,'L2':5.0}[load]
 projected=reference*1.25
 # Conservative raw-output headroom based on the first completed L0 pair and
 # the interrupted L1 run (which had already emitted 5.5 GiB at 51%). A pair
 # must fit while preserving the 40 GiB floor; do not start from a nominal
 # compressed-size estimate alone.
 peak_temp={'L0':11.0,'L1':14.0,'L2':18.0}[load]
 res=resources()
 if res['free_disk_GiB'] < 40+projected+peak_temp:
  cp=json.loads((OUT/'checkpoint.json').read_text()); cp.update({'status':'paused_resource_projection','active':None,'stop_reason':f'Cannot safely start {cell}/seed{seed}: free {res["free_disk_GiB"]:.2f} GiB; projected pair {projected:.2f} GiB plus raw temporary peak {peak_temp:.1f} GiB would cross 40 GiB floor','resources':res}); write_json(OUT/'checkpoint.json',cp); return False
 sig=PLAN_RUN['calendars'][f'{cell}/seed{seed}']['signature']
 results=[]
 for variant,logical in zip(['D3_fixed_TAS','D3_fixed_noTAS'],logicals):
  cp=json.loads((OUT/'checkpoint.json').read_text())
  completed=set(cp.get('completed_new_logical_executions',[]))
  if logical in completed:
   report=json.loads((OUT/'runs'/logical/'pilot-result.json').read_text()); results.append(report); continue
  before=resources(); cp.update({'status':'running','phase':'phase1','active':{'execution_id':logical,'variant':variant,'cell':cell,'seed':seed,'started_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'resources_before':before},'resources':before}); write_json(OUT/'checkpoint.json',cp)
  report=r.run_one(variant,PLAN_RUN,seed=seed,load=load,aggregation=agg,execution_id_override=logical)
  if report.get('calendar_sha256')!=sig or report.get('calendar_paired') is not True: raise RuntimeError(f'Calendar mismatch for {logical}')
  # Reprocess corrected synchronized offsets from simultaneously sampled native ticks.
  # The helper may suffix an actual attempt directory when preserving an earlier
  # technical failure. Always follow its returned execution_id, never assume the
  # logical id is the artifact directory.
  actual_id=report.get('execution_id',logical)
  run_dir=OUT/'runs'/actual_id; precision=next(run_dir.glob('**/clock_precision.csv.gz'))
  from importlib.util import spec_from_file_location,module_from_spec
  csp=spec_from_file_location('fixed_consolidator',FIXED/'consolidate.py'); cm=module_from_spec(csp); csp.loader.exec_module(cm)
  native=cm.clock_precision_summary(precision)
  report['synchronization_native_tick_audit']=native
  report['synchronization_sample_viable']=native['observed_sample_pass']
  report['synchronization_continuous_status']='not_verified'
  # Replace pilot-result with corrected direct-tick view and append a run ledger record.
  write_json(run_dir/'pilot-result.json',report)
  with (OUT/'runs.jsonl').open('a') as f: f.write(json.dumps({'execution_id':actual_id,'logical_execution_id':logical,'cell':cell,'seed':seed,'variant':variant,'calendar_sha256':sig,'simulation_valid':report.get('simulation_valid'),'application_viable':report.get('application_viable'),'stability_viable':report.get('stability_viable'),'synchronization_sample_viable':native['observed_sample_pass'],'resource_before':before,'resource_after':resources()},separators=(',',':'))+'\n'); f.flush(); os.fsync(f.fileno())
  cp=json.loads((OUT/'checkpoint.json').read_text()); completed=set(cp.get('completed_new_logical_executions',[])); completed.add(logical); cp['completed_new_logical_executions']=sorted(completed); cp['active']=None; cp['last_result']=actual_id; cp['resources']=resources(); cp['status']='running'; write_json(OUT/'checkpoint.json',cp)
  results.append(report)
  if not report.get('simulation_valid'): raise RuntimeError(f'Technically invalid execution; stop: {logical}')
 # Stop conditional expansion after any valid acceptance-gate failure. The pair
 # has already been completed, so its matched contrast remains auditable.
 if any(x.get('application_viable') is not True or x.get('stability_viable') is not True or
        x.get('synchronization_sample_viable') is not True or
        x.get('simulation_valid') is not True for x in results):
  cp=json.loads((OUT/'checkpoint.json').read_text()); cp.update({'status':'stopped_valid_performance_failure','active':None,'stop_reason':f'Valid performance failure in completed paired cell {cell}/seed{seed}; conditional expansion halted','resources':resources()}); write_json(OUT/'checkpoint.json',cp); return False
 cp=json.loads((OUT/'checkpoint.json').read_text()); cp.update({'status':'running','active':None,'last_completed_pair':f'{cell}/seed{seed}','resources':resources()}); write_json(OUT/'checkpoint.json',cp)
 return True

def main():
 import argparse
 ap=argparse.ArgumentParser(); ap.add_argument("--prepare-only",action="store_true"); args=ap.parse_args()
 if r.official_active(): raise RuntimeError('Official campaign active; do not launch this pilot')
 if r.free_gib()<40 or r.mem_gib()<7: raise RuntimeError(f'Resource floor: {resources()}')
 lock=OUT/'.final-verification.lock'; lock.parent.mkdir(parents=True,exist_ok=True)
 import fcntl
 with lock.open('a+') as lf:
  try: fcntl.flock(lf,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError: raise RuntimeError('Verification runner already active')
  load_existing_calendars()
  # Calendar generation is deterministic, init-only and outside methodological run counts.
  all_cells=[(l,a) for l in ('L0','L1','L2') for a in ('A0','A1')]
  for load,agg in all_cells:
   for seed in (41,43,47):
    target=OUT/'calendars'/f'{load}_{agg}'/f'seed{seed}_events.csv'
    if not target.exists():
     generate_calendar(load,agg,seed)
    else:
     meta=json.loads(Path(str(target)+'.json').read_text()); actual,rows=calendar_sig(target)
     if actual!=meta['signature'] or len(rows)!=meta['event_count']: raise RuntimeError(f'Existing calendar metadata mismatch: {target}')
     PLAN_RUN['calendars'][f'{load}_{agg}/seed{seed}']={'signature':actual,'event_count':len(rows),'path':str(target)}
  for load,agg in all_cells: preflight_cell(load,agg)
  cp=json.loads((OUT/'checkpoint.json').read_text())
  cp.update({'status':'phase1_ready','active':None,'calendar_generation_complete':True,'planned_new_pairs':[f'{l}_{a}_seed{s}' for l,a,s in ORDER],'resources':resources()}); write_json(OUT/'checkpoint.json',cp)
  if args.prepare_only: return
  for load,agg,seed in ORDER:
   if not run_pair(load,agg,seed): return
  cp=json.loads((OUT/'checkpoint.json').read_text()); cp.update({'status':'phase1_crosschecks_ready','active':None,'phase1_initial_batch_complete':True,'planned_phase1_crosschecks':[f'{l}_{a}_seed{s}' for l,a,s in PHASE1_CROSSCHECKS],'resources':resources()}); write_json(OUT/'checkpoint.json',cp)
  for load,agg,seed in PHASE1_CROSSCHECKS:
   if not run_pair(load,agg,seed): return
  cp=json.loads((OUT/'checkpoint.json').read_text()); cp.update({'status':'phase2_ready','active':None,'phase1_complete':True,'planned_phase2_pairs':[f'{l}_{a}_seed{s}' for l,a,s in PHASE2_ORDER],'resources':resources()}); write_json(OUT/'checkpoint.json',cp)
  for load,agg,seed in PHASE2_ORDER:
   if not run_pair(load,agg,seed): return
  cp=json.loads((OUT/'checkpoint.json').read_text()); cp.update({'status':'phase2_complete','active':None,'phase2_complete':True,'resources':resources()}); write_json(OUT/'checkpoint.json',cp)

if __name__=='__main__': main()
