#!/usr/bin/env python3
"""Make simultaneous native-tick clock samples authoritative for sync status."""
from __future__ import annotations
import copy, json, shutil, time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'simulations/pilot/c4_feasibility_decision/results'

def main():
    audit=json.loads((OUT/'direct_clock_audit.json').read_text())
    by_path={r['path']:r for r in audit['runs']}
    changed={}
    for result_path in (OUT/'runs').glob('*/pilot-result.json'):
        result=json.loads(result_path.read_text())
        d=Path(result.get('run_dir',''))
        # Prefer the explicit compact-clock file path in the extraction result directory.
        run_dir=result_path.parent
        key=next((k for k in by_path if k.startswith(str(run_dir.relative_to(ROOT))) and 'clock_precision.csv' in k),None)
        if key is None:
            continue
        row=by_path[key]; nodes=row['populations']['periodic']['nodes']
        passed=bool(nodes) and all(v['samples']>0 and v['max_abs_offset_s']<=1e-6 and v['samples_abs_gt_1us']==0 for v in nodes.values())
        old=copy.deepcopy(result.get('synchronization_sample_viable'))
        legacy=copy.deepcopy(result.get('pilot_vector_audit',{}).get('synchronization'))
        result['synchronization_sample_viable']=passed
        result['synchronization_continuous_status']='not_verified'
        result['synchronization_legacy_vector_status']=legacy
        result['synchronization_legacy_report_value']=old
        result['synchronization_precision_audit']={'source':key,
            'population':'30,000 periodic simultaneous native-tick samples/node over [1,31) s',
            'method':'ClockPrecisionProbe subtracts corrected local and HPC clock ticks before serialization',
            'max_abs_offset_us_by_node':{n:v['max_abs_offset_us'] for n,v in nodes.items()},
            'samples_abs_gt_1us_by_node':{n:v['samples_abs_gt_1us'] for n,v in nodes.items()},
            'sampled_threshold_pass':passed,'continuous_conformance':'not_verified'}
        result.setdefault('pilot_vector_audit',{})['synchronization']={'status':'superseded_by_simultaneous_native_tick_audit',
            'legacy_status':legacy.get('status') if isinstance(legacy,dict) else legacy}
        result_path.write_text(json.dumps(result,indent=2)+'\n'); changed[result.get('execution_id')]=result
    ledger=OUT/'runs.jsonl'
    backup=OUT/'runs_before_direct_clock_reconcile.jsonl'
    if ledger.exists() and not backup.exists(): shutil.copy2(ledger,backup)
    lines=[]
    if ledger.exists():
      for line in ledger.read_text().splitlines():
        if not line.strip():continue
        row=json.loads(line); eid=row.get('execution_id')
        if eid in changed: row=changed[eid]
        elif eid:
            # Reused controls have direct-clock evidence in the audit but remain historical source files.
            match=next((v for k,v in by_path.items() if f'/{eid}_' in k or f'/{eid}/' in k),None)
            if match:
                ns=match['populations']['periodic']['nodes']; ok=bool(ns) and all(x['samples'] and x['max_abs_offset_s']<=1e-6 and not x['samples_abs_gt_1us'] for x in ns.values())
                row['synchronization_sample_viable']=ok; row['synchronization_continuous_status']='not_verified'
                row['synchronization_precision_audit']={'max_abs_offset_us_by_node':{n:x['max_abs_offset_us'] for n,x in ns.items()},'sampled_threshold_pass':ok,'continuous_conformance':'not_verified'}
        lines.append(json.dumps(row,sort_keys=True))
    if lines: ledger.write_text('\n'.join(lines)+'\n')
    cp_path=OUT/'checkpoint.json'; cp=json.loads(cp_path.read_text())
    previous=cp.pop('last_error',None)
    if previous: cp['historical_last_error']={'message':previous,'attempt_recorded_in':'simulations/pilot/c4_feasibility_decision/results/technical_attempts.jsonl','resolved_by':'D1 technical replacement; not a current runner error'}
    cp.update({'status':'completed','phase':'initial_seed41_reconciled','active':None,'synchronization_audit':'simulations/pilot/c4_feasibility_decision/results/direct_clock_audit.json','last_reconciled_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())})
    cp_path.write_text(json.dumps(cp,indent=2)+'\n')
    print(json.dumps({'updated_run_reports':len(changed),'checkpoint_status':cp['status'],'current_last_error':cp.get('last_error'),'historical_error_preserved':bool(previous)},indent=2))

if __name__=='__main__':main()
