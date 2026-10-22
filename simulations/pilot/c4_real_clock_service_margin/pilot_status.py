#!/usr/bin/env python3
"""Compact live status for the isolated C4 real-clock pilot."""
import json, os, shutil, subprocess
from pathlib import Path

HERE=Path(__file__).resolve().parent
OUT=HERE/'results'
ROOT=HERE.parents[2]

def main():
    try: cp=json.loads((OUT/'checkpoint.json').read_text())
    except Exception: cp={'status':'not_started','completed':[],'active':None}
    ledger=[]
    p=OUT/'runs.jsonl'
    if p.exists():
        for line in p.read_text().splitlines():
            try: ledger.append(json.loads(line))
            except json.JSONDecodeError: pass
    try:
        mem=next(int(x.split()[1]) for x in Path('/proc/meminfo').read_text().splitlines() if x.startswith('MemAvailable:'))/1024/1024
    except Exception: mem=None
    free=shutil.disk_usage(ROOT).free/(1024**3)
    procs=subprocess.run(['pgrep','-af','opp_run|zonal-ivn-tsn'],text=True,capture_output=True).stdout.splitlines()
    procs=[x for x in procs if 'pgrep -af' not in x and 'pilot_status.py' not in x]
    print(json.dumps({'status':cp.get('status'),'phase':cp.get('phase'),'active':cp.get('active'),
                      'valid_treatment_slots':cp.get('valid_treatment_slots',cp.get('completed',[])),
                      'methodological_slots_completed':cp.get('seed41_methodological_runs',len(cp.get('completed',[]))),
                      'superseded_execution_ids':cp.get('superseded_execution_ids',[]),
                      'technical_replacements_used':cp.get('technical_replacements_used',0),
                      'technical_attempts_count':cp.get('technical_attempts_count'),
                      'ledger_rows':len(ledger),'last_error':cp.get('last_error'),
                      'free_GiB':round(free,1),'MemAvailable_GiB':round(mem,1) if mem is not None else None,
                      'simulation_processes':procs,'conditional_phase':cp.get('conditional_phase','not_started'),
                      'exploratory':True,'official_c4_frozen':False},indent=2))

if __name__=='__main__': main()
