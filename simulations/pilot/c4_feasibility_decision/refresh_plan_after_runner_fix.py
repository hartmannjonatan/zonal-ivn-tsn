#!/usr/bin/env python3
"""Freeze only the technical retry-path correction, preserving the prior plan."""
import hashlib,json,sys,time
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];OUT=HERE/'results'
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def atomic(p,d):
 q=p.with_suffix(p.suffix+'.tmp');q.write_text(json.dumps(d,indent=2,sort_keys=True)+'\n');q.replace(p)
def main():
 cp=json.loads((OUT/'checkpoint.json').read_text())
 if cp.get('status')!='planned' or cp.get('active') is not None or cp.get('previous_technical_failure',{}).get('execution_id')!='D1_TAS_L2_A1_seed41':
  raise SystemExit('Expected an inactive planned checkpoint after D1 instrumentation failure')
 if cp.get('attempts_by_logical_execution',{}).get('D1_TAS_L2_A1_seed41') not in (None,1):
  raise SystemExit('A technical replacement was already attempted')
 prev=OUT/'plan.json'; preserved=OUT/'plan_before_runner_retry_fix.json'
 if not preserved.exists():preserved.write_bytes(prev.read_bytes())
 sys.path.insert(0,str(HERE));import run_study
 plan=run_study.make_plan()
 plan['technical_correction']={'id':'technical-correction-1-plus-retry-guard','cause':'initial network selector omitted probes; first correction was blocked by a runner guard on retained failed-attempt metadata',
  'correction':'use isolated probe wrapper and allow exactly one retry in a separate attempt directory','methodological_parameters_changed':False,
  'previous_plan_sha256':sha(preserved),'failed_attempt_report_sha256':sha(OUT/'runs/D1_TAS_L2_A1_seed41/technical-validation.json'),
  'replacement_attempt_budget_remaining':1}
 atomic(OUT/'plan.json',plan)
 manifest={'status':'technical_correction_v2_frozen_before_replacement','plan_sha256':sha(OUT/'plan.json'),'protocol_sha256':sha(HERE/'protocol.md'),
  'technical_correction_sha256':sha(HERE/'technical_correction_2026-10-19.md'),'previous_manifest_sha256':sha(OUT/'protocol_manifest.json'),
  'previous_plan_sha256':sha(preserved),'source_hashes':plan['source_hashes'],'current_commit':plan['git_commit'],
  'working_tree_status':plan['working_tree_status_at_plan'],'created_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())}
 atomic(OUT/'protocol_manifest.json',manifest)
 cp['plan_version']=3;cp['phase']='technical_replacement_preflight';cp['status']='planned';cp['technical_replacement_budget_remaining']=1
 atomic(OUT/'checkpoint.json',cp)
 print('Versioned retry-guard correction frozen; no simulation launched.')
if __name__=='__main__':main()
