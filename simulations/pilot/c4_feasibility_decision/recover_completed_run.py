#!/usr/bin/env python3
"""Finish validation/retention for a completed simulation without rerunning it."""
from __future__ import annotations
import fcntl, json, os, resource, sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/'scripts/run'))
sys.path.insert(0,str(HERE))
import run_study as runner

def main():
    lock_handle=runner.LOCK.open('a+')
    try: fcntl.flock(lock_handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError: raise SystemExit('Runner lock is held; refusing concurrent recovery')
    # Keep any accidental allocation bounded; the normal streaming pass needs far less.
    resource.setrlimit(resource.RLIMIT_AS,(4*1024**3,4*1024**3))
    plan=json.loads((HERE/'results/plan.json').read_text())
    variant='D3_TAS'; logical='D3_TAS_L2_A1_seed41'
    dest=HERE/'results/runs'/logical
    config='Joint_D3_TAS_L2_A1'; run_dir=dest/(config+'-0')
    cp=runner.state()
    if (dest/'pilot-result.json').is_file() and (run_dir/'retention_manifest.json').is_file() and logical in cp.get('completed',[]):
        print(json.dumps({'execution_id':logical,'status':'already_finalized','action':'no-op'}));return
    vec=next(dest.glob(config+'-#*.vec')); sca=dest/(config+'-#0.sca'); log=dest/(config+'.log')
    if not ('Simulation time limit reached -- at t=31.05s' in log.read_text(errors='replace') and 'End.' in log.read_text(errors='replace')):
        raise SystemExit('Refusing recovery: raw log does not show normal completion at 31.05 s')
    if not (run_dir/'d3-acceptance.json').is_file():
        raise SystemExit('Refusing recovery: completed base acceptance report is missing')
    report=json.loads((run_dir/'d3-acceptance.json').read_text())
    profile=runner.profile_for(variant,plan,'L2','A1')
    calendar=HERE/'results/calendars/L2_A1/seed41_events.csv'
    _config,args=runner.sim_args(variant,dest,41,profile,calendar,plan,'L2','A1')
    command=[str(runner.ROOT/'src/zonal-ivn-tsn')]+args
    signature,_=runner.calendar_signature(calendar)
    observed,calendar_rows=runner.parse_calendar_from_run(run_dir)
    expected=plan['calendars']['L2_A1/seed41']['signature']
    profile_check=runner.profile_sca_check(sca,profile)
    gcl=runner.gcl_check(sca,variant)
    instr_ok,instr=runner.instrumentation_check(run_dir,expected)
    credit=runner.credit_vector_check(run_dir,profile)
    gates=runner.gate_runtime_check(run_dir,variant)
    q_ok,q_audit=runner.verify_queue_trace_against_report(run_dir,report)
    report['queue_recalculation_verified']=q_ok
    report['queue_trace_recalculation']={'valid':q_ok,**q_audit}
    technical=(signature==expected and observed==expected and profile_check['pass'] and
               instr_ok and q_ok and credit['status']=='pass' and gcl['status']=='pass' and gates['status']=='pass')
    pilot_vectors=runner.shared.extract_pilot_vectors(vec,report,run_dir,'C4joint')
    report.update({'exploratory':True,'official_c4_frozen':False,'variant':variant,'variant_id':variant,
        'execution_id':logical,'logical_execution_id':logical,'attempt_number':1,'technical_replacement':False,
        'cell':'L2_A1','seed':41,'calendar_sha256':observed,'calendar_event_count':len(calendar_rows),
        'calendar_paired':signature==expected and observed==expected,'effective_profile_bps':profile,
        'effective_profile_sha256':runner.check_profile(profile),'resolved_profile_audit':profile_check,
        'effective_gcl':gcl,'observed_gate_events':gates,'credit_vector_validation':credit,
        'pilot_vector_audit':pilot_vectors,'instrumentation_validation':{'valid':instr_ok,**instr},
        'simulation_valid':technical,'validator_combined_cell_viable':report.get('viable'),
        'application_viable':all(r.get('viable') is not False for flow in report.get('qos',{}).values()
                                  for r in flow.get('receivers',{}).values()),
        'stability_viable':not bool(report.get('nonstable_queues')) if q_ok else None,
        'synchronization_sample_viable':None,'synchronization_continuous_status':'not_verified',
        'raw_vector_sha256':runner.sha(vec),'command':command,
        'runtime_versions':{'omnetpp':plan['omnetpp_version'],'inet':plan['inet_version']},
        'recovered_postprocessing':True,'recovery_note':'Simulation ended normally; runner process stopped before ledger/retention finalization. No simulation was repeated.'})
    if not technical:
        runner.atomic(dest/'technical-validation.json',report)
        raise SystemExit('Completed simulation failed technical validation; evidence retained, not counted as valid')
    retained=[]
    for name in ('packet_events.csv','clock_precision.csv','events.csv'):
        p=run_dir/name
        if p.exists(): retained.append(runner.gzip_verified(p))
    runner.atomic(run_dir/'retention_manifest.json',{'compression':retained,'full_vector_retained':True,
        'raw_vector_sha256':report['raw_vector_sha256'],'compact_metrics_verified':True,
        'queue_trace_verified':q_ok,'credit_vectors_verified':credit['status']=='pass'})
    runner.atomic(dest/'pilot-result.json',report); runner.append_ledger(report)
    cp=runner.state(); completed=cp.get('completed',[])
    if logical not in completed: completed.append(logical)
    logicals=cp.get('completed_logical_executions',[])
    if logical not in logicals: logicals.append(logical)
    cp.update({'status':'completed','phase':'initial_seed41','active':None,'completed':completed,
        'completed_logical_executions':logicals,'last_result':logical,'last_error_history':
        [x for x in [cp.get('last_error')] if x and 'D1_TAS_L2_A1_seed41' in x],
        'free_gib':runner.free_gib(),'MemAvailable_GiB':runner.mem_gib()})
    cp.pop('last_error',None); runner.write_checkpoint(cp)
    for p in (sca,log,vec):
        if p.exists(): retained.append(runner.gzip_verified(p))
    runner.atomic(run_dir/'retention_manifest.json',{'compression':retained,
        'full_vector_retained_compressed':True,'raw_vector_sha256':report['raw_vector_sha256'],
        'compact_metrics_verified':True,'queue_trace_verified':q_ok,'credit_vectors_verified':credit['status']=='pass'})
    print(json.dumps({'execution_id':logical,'technical_valid':technical,'application_viable':report['application_viable'],
        'stability_viable':report['stability_viable'],'drops':report['recorded_drops'],
        'free_gib':runner.free_gib(),'MemAvailable_GiB':runner.mem_gib()},indent=2))

if __name__=='__main__': main()
