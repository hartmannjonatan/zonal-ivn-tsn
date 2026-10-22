#!/usr/bin/env python3
"""Single-screen status view for the corrected C4 pilot."""
import json, os, re, time
from pathlib import Path

HERE=Path(__file__).resolve().parent
OUT=HERE/'results'

def read(path,default):
    try:return json.loads(path.read_text())
    except (OSError,json.JSONDecodeError):return default

while True:
    cp=read(OUT/'checkpoint.json',{'status':'not_started','active':None,'completed':[]})
    plan=read(OUT/'plan.json',{})
    ledger=[]
    try:
        with (OUT/'runs.jsonl').open() as f:
            for line in f:
                try:ledger.append(json.loads(line))
                except json.JSONDecodeError:pass
    except OSError:pass
    active=cp.get('active') or {}
    order=plan.get('pre_execution_decisions',{}).get('run',[])
    done=set(cp.get('completed_logical_executions',[]))
    results={x.get('execution_id'):x for x in ledger}
    rows=[]
    for variant in order:
        eid=f'{variant}_L2_A1_seed41'
        if eid in done: status='COMPLETE'
        elif active.get('logical_execution_id',active.get('execution_id'))==eid:
            actual=active.get('execution_id',eid)
            config='Pilot_C3sync_L2_A1' if variant=='C3_sync_control' else 'Pilot_C4compensated_L2_A1'
            log=OUT/'runs'/actual/f'{config}.log'
            if log.is_file():
                try:
                    with log.open('rb') as stream:
                        size=stream.seek(0,2); stream.seek(max(0,size-131072))
                        text=stream.read().decode(errors='replace')
                    tail=next((line.strip() for line in reversed(text.splitlines())
                               if 'completed' in line and 'Event #' in line),'')
                    m=re.search(r'(\d+)% completed',tail)
                    percent=f'{m.group(1)}%' if m else 'starting'
                    sim=re.search(r't=([0-9.]+)',tail)
                    simtime=f"t={sim.group(1)}s" if sim else ''
                    fresh=(time.time()-log.stat().st_mtime)<90
                    status=(f'RUNNING {percent} {simtime}; log {log.stat().st_size} B' if fresh else f'STALE LOG {percent} {simtime}; inspect checkpoint')
                except OSError: status='LOG UNREADABLE; inspect checkpoint'
            else: status='STARTING; no simulator log yet'
        elif results.get(eid): status='LEDGERED'
        else: status='WAITING'
        rows.append((variant,status))
    rejected=plan.get('pre_execution_decisions',{}).get('reject',{})
    os.system('clear' if os.name=='posix' else 'cls')
    print('Corrected C4 isolated pilot — L2/A1, seed 41')
    print(f"Checkpoint: {cp.get('status')} / {cp.get('phase','-')}   |   completed {len(done)}/{len(order)}   |   PID {active.get('pid','-')}")
    print(f"Disk free: {cp.get('free_gib','-')} GiB   |   MemAvailable: {cp.get('MemAvailable_GiB','-')} GiB   |   jobs: 1")
    print('\nScheduled after triage:')
    for name,status in rows:print(f'  {name:24} {status}')
    if rejected:
        print('\nRejected before simulation:')
        for name,item in sorted(rejected.items()):print(f"  {name:24} {item.get('status')}")
    if cp.get('last_error'):print('\nLast error:',cp['last_error'])
    print('\nCtrl+C exits this view only; it does not stop a simulation.')
    time.sleep(3)
