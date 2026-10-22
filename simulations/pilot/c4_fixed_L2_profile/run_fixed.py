#!/usr/bin/env python3
"""Serial runner for the preregistered four-cell fixed-D3-profile pilot."""
import argparse, fcntl, json, os, subprocess, sys, time, hashlib
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
SIM=ROOT/'simulations'
sys.path.insert(0,str(HERE))
import run_study as r

ORDER=[('D3_fixed_TAS','L0','A0'),('D3_fixed_noTAS','L0','A0'),
       ('D3_fixed_TAS','L1','A1'),('D3_fixed_noTAS','L1','A1')]

def load_plan():
    p=json.loads((r.OUT/'plan.json').read_text())
    frozen=p['frozen_profile']['effective_profile_bps']
    canon=hashlib.sha256(json.dumps(frozen,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    if canon!=p['profile_sha256'] or canon!='571e3a10e004005b2994aadc6dc495db730f6e9b8842af2550ebcbb3d6eb33be':
        raise RuntimeError('Frozen profile canonical hash mismatch')
    contract=json.loads((r.HERE/'treatment_contracts.json').read_text())
    for treatment in r.VARIANTS:
        if contract['treatments'][treatment]['CBS_profile_sha256']!=canon:
            raise RuntimeError(f'Contract/profile mismatch for {treatment}')
        if set(p['expected_cbs_by_treatment'][treatment])!=set(frozen):
            raise RuntimeError('Incomplete CBS port/TC contract')
    return p

def ensure_resources(stage):
    free=r.free_gib(); mem=r.mem_gib()
    if free<r.MIN_FREE_GIB or mem<r.MIN_MEM_GIB:
        raise RuntimeError(f'Resource floor before {stage}: disk={free:.1f} GiB, MemAvailable={mem:.1f} GiB')
    return {'free_disk_GiB':round(free,2),'MemAvailable_GiB':round(mem,2)}

def runtime_preflights(plan):
    """Resolve exact configuration for each cell/treatment at t=0; no workload execution."""
    done=[]
    for variant,load,agg in ORDER:
        resources=ensure_resources('preflight')
        cell=f'{load}_{agg}'; cal=r.HERE/'results/calendars'/cell/'seed41_events.csv'
        profile=r.profile_for(variant,plan,load,agg)
        dest=r.OUT/f'preflight_{variant}_{cell}'; dest.mkdir(parents=True,exist_ok=False)
        config,args=r.sim_args(variant,dest,41,profile,cal,plan,load,agg)
        args.append('--sim-time-limit=0s')
        env=os.environ.copy(); env['LD_LIBRARY_PATH']=':'.join([str(r.OMNET/'lib'),str(r.INET/'src'),env.get('LD_LIBRARY_PATH','')]).rstrip(':')
        cmd=[str(ROOT/'src/zonal-ivn-tsn')]+args
        log=dest/f'{config}-preflight.log'
        with log.open('w') as f:
            proc=subprocess.run(cmd,cwd=SIM,env=env,stdout=f,stderr=subprocess.STDOUT,timeout=180)
        sca=dest/f'{config}-#0.sca'
        if proc.returncode or not sca.is_file(): raise RuntimeError(f'Preflight failed ({variant}/{cell}), see {log}')
        cbs=r.profile_sca_check(sca,profile,require_credit_statistics=False)
        gate=(r.gcl_check(sca,variant) if variant in r.GATED else r.no_tas_check(sca,dest/'no-packet-trace.csv'))
        if not cbs['pass'] or gate.get('status')!='pass':
            raise RuntimeError(f'Preflight contract failed for {variant}/{cell}: CBS={cbs["pass"]}, gates={gate.get("status")}')
        logtext=log.read_text(errors='replace')
        if '<!> Error:' in logtext: raise RuntimeError(f'Preflight has runtime error: {log}')
        row={'variant':variant,'cell':cell,'methodological_execution':False,'returncode':proc.returncode,
             'profile_sha256':r.check_profile(profile),'cbs_validation':cbs,'gate_validation':gate,
             'resource_before':resources,'sca_sha256':r.sha(sca),'log_sha256':r.sha(log)}
        r.atomic(dest/'preflight.json',row); done.append(row)
    r.atomic(r.OUT/'preflight_summary.json',{'status':'pass','runs':done})
    return done

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--preflight-only',action='store_true'); ap.add_argument('--resume',action='store_true'); args=ap.parse_args()
    r.OUT.mkdir(parents=True,exist_ok=True)
    lock=r.OUT/'.fixed-profile.lock'
    with lock.open('a+') as lf:
        try: fcntl.flock(lf,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: raise SystemExit('Fixed-profile pilot runner already active')
        plan=load_plan()
        if r.official_active(): raise RuntimeError('Official campaign active; refusing pilot run')
        selftest=r.self_test_validation()
        r.atomic(r.OUT/'validator_self_test.json',selftest)
        if not selftest.get('self_test_pass'): raise RuntimeError('Historical validator self-test did not pass')
        if not (r.OUT/'preflight_summary.json').exists() or args.preflight_only:
            runtime_preflights(plan)
        if args.preflight_only: return
        cp=r.state()
        completed=set(cp.get('completed_logical_executions',[]))
        if completed and not args.resume: raise RuntimeError('Checkpoint already has completed executions; use --resume')
        cp.update({'status':'running','phase':'fixed_profile_L0_L1','planned':[f'{v}_{l}_{a}_seed41' for v,l,a in ORDER],
                   'completed_logical_executions':sorted(completed),'active':None,'exploratory':True,'official_c4_frozen':False,
                   'resource_floor':{'disk_GiB':r.MIN_FREE_GIB,'MemAvailable_GiB':r.MIN_MEM_GIB}})
        r.write_checkpoint(cp)
        for variant,load,agg in ORDER:
            logical=f'{variant}_{load}_{agg}_seed41'
            if logical in completed: continue
            before=ensure_resources(logical)
            cell=f'{load}_{agg}'
            calendar=plan['calendars'][f'{cell}/seed41']
            actual,_=r.calendar_signature(r.HERE/'results/calendars'/cell/'seed41_events.csv')
            if actual!=calendar['signature']: raise RuntimeError(f'Calendar signature changed for {logical}')
            result=r.run_one(variant,plan,seed=41,load=load,aggregation=agg,execution_id_override=logical)
            completed.add(logical)
            cp=r.state(); cp.update({'status':'running','phase':'fixed_profile_L0_L1','completed_logical_executions':sorted(completed),
                'last_result':logical,'active':None,'last_resource_check':before,'resource_after':{'free_disk_GiB':r.free_gib(),'MemAvailable_GiB':r.mem_gib()}})
            r.write_checkpoint(cp)
            if not result.get('simulation_valid'): raise RuntimeError(f'Technical validation failed for {logical}; stopping dependent runs')
        cp=r.state(); cp.update({'status':'completed','phase':'all_four_complete','active':None,'completed_logical_executions':sorted(completed),
             'completed_count':len(completed),'free_disk_GiB':r.free_gib(),'MemAvailable_GiB':r.mem_gib()}); r.write_checkpoint(cp)

if __name__=='__main__': main()
