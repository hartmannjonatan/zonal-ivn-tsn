#!/usr/bin/env python3
"""Compact live status display for the fixed-L2-profile pilot."""
import json, os, shutil, time
from pathlib import Path
HERE=Path(__file__).resolve().parent
OUT=HERE/'results'
ORDER=['D3_fixed_TAS_L0_A0_seed41','D3_fixed_noTAS_L0_A0_seed41','D3_fixed_TAS_L1_A1_seed41','D3_fixed_noTAS_L1_A1_seed41']
def main():
    while True:
        try: cp=json.loads((OUT/'checkpoint.json').read_text())
        except Exception: cp={}
        os.system('clear')
        print('C4 fixed absolute D3/L2 pilot | exploratory=true | official_c4_frozen=false')
        print('='*76)
        print(f"Status: {cp.get('status','not_started')} | phase: {cp.get('phase','-')}")
        active=cp.get('active') or {}
        if active:
            print(f"Active: {active.get('execution_id')} | elapsed {active.get('elapsed_s','-')} s | simulator percent from log")
        completed=set(cp.get('completed_logical_executions',[]))
        for logical in ORDER:
            path=OUT/'runs'/logical/'pilot-result.json'
            if path.is_file():
                try:
                    r=json.loads(path.read_text())
                    state=f"done | technical={r.get('simulation_valid')} app={r.get('application_viable')} stability={r.get('stability_viable')} sync_sample={r.get('synchronization_sample_viable')}"
                except Exception: state='result JSON unreadable'
            elif logical in completed: state='ledger completed; result pending inspection'
            elif active.get('logical_execution_id')==logical:
                lp=OUT/'runs'/logical/f"Joint_{logical.rsplit('_seed',1)[0]}.log"
                if not lp.is_file():
                    # actual output config names are based on variant and load/alignment
                    candidates=list((OUT/'runs'/logical).glob('*.log')) if (OUT/'runs'/logical).exists() else []
                    lp=candidates[0] if candidates else None
                pct='unknown'
                if lp and lp.exists():
                    try:
                        import re
                        txt=lp.read_text(errors='ignore')[-12000:]
                        matches=re.findall(r'(\d+)% completed',txt)
                        if matches: pct=matches[-1]+'%'
                    except Exception: pass
                state=f"running | {pct}"
            else: state='pending'
            print(f"{logical:<37} {state}")
        print(f"Disk free: {shutil.disk_usage(HERE).free/1024**3:.1f} GiB | MemAvailable: {float([x.split()[1] for x in open('/proc/meminfo') if x.startswith('MemAvailable:')][0])/1024/1024:.1f} GiB")
        print('Ctrl-C exits dashboard only.')
        time.sleep(3)
if __name__=='__main__': main()
