#!/usr/bin/env python3
"""Execute only the preregistered D3 conditional phase, serially and checkpointed."""
from __future__ import annotations
import argparse, fcntl, gzip, json, subprocess, sys, time
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
OUT=HERE/'results'
sys.path.insert(0,str(HERE))
import run_study as runner
from audit_direct_clock_precision import summarize as summarize_clock

ORDER=('D3_TAS','D3_noTAS','C3_sync_control')

def read_json(path): return json.loads(path.read_text())

def report_for(logical_id):
    rows=[]
    for p in (OUT/'runs').glob(f'{logical_id}*/pilot-result.json'):
        d=read_json(p)
        if d.get('logical_execution_id',d.get('execution_id'))==logical_id and d.get('simulation_valid') is True:
            rows.append((p,d))
    if len(rows)!=1:
        raise RuntimeError(f'Expected exactly one valid report for {logical_id}; found {len(rows)}')
    return rows[0]

def direct_sync_pass(report_path):
    run_dir=report_path.parent
    probes=sorted(run_dir.glob('**/clock_precision.csv*'))
    if len(probes)!=1: return False, {'error':f'expected one clock precision trace, got {len(probes)}'}
    audit=summarize_clock(probes[0])
    nodes=audit['populations']['periodic']['nodes']
    passed=bool(nodes) and all(x['samples']>0 and x['max_abs_offset_s']<=1e-6 and x['samples_abs_gt_1us']==0 for x in nodes.values())
    return passed, {'path':str(probes[0].relative_to(ROOT)),'max_abs_offset_us_by_node':{n:x['max_abs_offset_us'] for n,x in nodes.items()},
        'samples_abs_gt_1us_by_node':{n:x['samples_abs_gt_1us'] for n,x in nodes.items()},'sampled_pass':passed,
        'continuous_conformance':'not_verified'}

def evaluate_group(cell,seed):
    group=[]; gates=True
    for variant in ORDER:
        logical=f'{variant}_{cell}_seed{seed}'
        path,r=report_for(logical)
        sync_ok,sync=direct_sync_pass(path)
        zero_drops=(int(r.get('queue_overflow_drop_total_post_warmup_including_drain',-1))==0 and
                    int(r.get('recorded_drops',-1))==0)
        row={'logical_execution_id':logical,'report_path':str(path.relative_to(ROOT)),
             'simulation_valid':r.get('simulation_valid'),'application_viable':r.get('application_viable'),
             'stability_viable':r.get('stability_viable'),'sampled_synchronization_viable':sync_ok,
             'zero_confirmed_drops':zero_drops,'calendar_sha256':r.get('calendar_sha256'),
             'effective_profile_sha256':r.get('effective_profile_sha256'),'synchronization':sync}
        row['passes_conditional_gates']=all((row['simulation_valid'] is True,row['application_viable'] is True,
            row['stability_viable'] is True,row['sampled_synchronization_viable'] is True,row['zero_confirmed_drops'] is True))
        gates &= row['passes_conditional_gates']
        group.append(row)
    signatures={x['calendar_sha256'] for x in group}
    pair_ok=len(signatures)==1 and all(x['calendar_sha256'] for x in group)
    for x in group: x['paired_calendar_group_pass']=pair_ok
    return {'cell':cell,'seed':seed,'treatments':group,'calendar_pair_pass':pair_ok,
            'group_pass':bool(gates and pair_ok)}

def compact(logical):
    path,_=report_for(logical)
    cmd=[sys.executable,str(HERE/'compact_exact_samples.py'),str(path.parent),'--delete-after-verify']
    subprocess.run(cmd,cwd=ROOT,check=True)

def run_group(cell,seed,plan,cp):
    sig=plan['calendars'][f'{cell}/seed{seed}']['signature']
    for v in ORDER:
        logical=f'{v}_{cell}_seed{seed}'
        try:
            report_for(logical)
            continue
        except RuntimeError:
            pass
        if runner.free_gib()<runner.MIN_FREE_GIB or runner.mem_gib()<runner.MIN_MEM_GIB:
            raise RuntimeError(f'Resource floor before {logical}: free={runner.free_gib():.1f} GiB, MemAvailable={runner.mem_gib():.1f} GiB')
        report=runner.run_one(v,plan,seed,cell.split('_')[0],cell.split('_')[1])
        if report.get('calendar_sha256')!=sig: raise RuntimeError(f'Calendar signature mismatch after {logical}')
        compact(logical)
        cp=runner.state(); cp.update({'phase':'conditional_verification','conditional_active_group':f'{cell}_seed{seed}',
            'last_completed_conditional_treatment':logical,'free_gib':runner.free_gib(),'MemAvailable_GiB':runner.mem_gib()})
        runner.write_checkpoint(cp)
    outcome=evaluate_group(cell,seed)
    p=OUT/f'conditional_{cell}_seed{seed}.json'; p.write_text(json.dumps(outcome,indent=2)+'\n')
    cp=runner.state(); groups=cp.setdefault('conditional_groups',{}); groups[f'{cell}_seed{seed}']=outcome
    cp.update({'active':None,'conditional_active_group':None,'free_gib':runner.free_gib(),'MemAvailable_GiB':runner.mem_gib(),
        'phase':'conditional_verification','conditional_stop_reason':None if outcome['group_pass'] else f'conditional gates failed for {cell} seed {seed}'})
    runner.write_checkpoint(cp)
    return outcome

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--phase',choices=('seeds','low-load','l1-after-l0-result'),required=True); a=ap.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    with (OUT/'.pilot.lock').open('a+') as lf:
        try: fcntl.flock(lf,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: raise SystemExit('Pilot runner already active')
        plan=read_json(OUT/'plan.json')
        if runner.source_hashes()!=plan.get('source_hashes'): raise SystemExit('Frozen source/configuration hashes changed; conditional runs refused')
        selection=read_json(OUT/'selected_candidate.json')
        if selection.get('selected_candidate')!='D3': raise SystemExit('D3 is not the preregistered selected candidate')
        if a.phase=='seeds':
            for seed in (43,47):
                result=run_group('L2_A1',seed,plan,runner.state())
                print(json.dumps(result,indent=2),flush=True)
                if not result['group_pass']:
                    cp=runner.state(); cp.update({'conditional_low_load_authorized':False,'phase':'conditional_stopped_after_seed_failure'})
                    runner.write_checkpoint(cp); return
            cp=runner.state(); cp.update({'conditional_low_load_authorized':True,'phase':'conditional_seed_checks_passed'})
            runner.write_checkpoint(cp)
            return
        if a.phase=='l1-after-l0-result':
            cp=runner.state()
            groups=cp.get('conditional_groups',{})
            l0=groups.get('L0_A0_seed41')
            if cp.get('conditional_low_load_authorized') is not True:
                raise SystemExit('L1 continuation refused: conditional seed checks did not authorize low-load work')
            if not l0 or l0.get('seed')!=41 or l0.get('cell')!='L0_A0':
                raise SystemExit('L1 continuation refused: no audited L0/A0 seed41 group exists')
            for seed in (43,47):
                prior=groups.get(f'L2_A1_seed{seed}')
                if not prior or prior.get('group_pass') is not True:
                    raise SystemExit(f'L1 continuation refused: L2/A1 seed {seed} did not pass')
            if 'L1_A1_seed41' in groups:
                raise SystemExit('L1 continuation refused: result group already exists; reconcile rather than rerun')
            result=run_group('L1_A1',41,plan,cp)
            cp=runner.state()
            l0_pass=bool(cp.get('conditional_groups',{}).get('L0_A0_seed41',{}).get('group_pass'))
            cp.update({'phase':'conditional_low_load_complete','status':'conditional_pilot_complete',
                'conditional_low_load_all_gates_pass':bool(l0_pass and result['group_pass']),
                'active':None,'free_gib':runner.free_gib(),'MemAvailable_GiB':runner.mem_gib()})
            runner.write_checkpoint(cp)
            print(json.dumps(result,indent=2),flush=True)
            return
        cp=runner.state()
        if cp.get('conditional_low_load_authorized') is not True: raise SystemExit('Low-load phase not authorized: both seed checks have not passed')
        for cell in ('L0_A0','L1_A1'):
            result=run_group(cell,41,plan,cp)
            print(json.dumps(result,indent=2),flush=True)
            if not result['group_pass']:
                cp=runner.state(); cp.update({'phase':'conditional_stopped_after_low_load_failure'})
                runner.write_checkpoint(cp); return
        cp=runner.state(); cp.update({'status':'conditional_pilot_complete','phase':'conditional_all_passed','active':None})
        runner.write_checkpoint(cp)

if __name__=='__main__': main()
