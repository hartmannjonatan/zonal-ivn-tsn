#!/usr/bin/env python3
"""Preserve the failed attempt and freeze a versioned technical-only correction."""
import hashlib,json,sys,time
from pathlib import Path
HERE=Path(__file__).resolve().parent; ROOT=HERE.parents[2]; OUT=HERE/'results'
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def atomic(p,d):
 q=p.with_suffix(p.suffix+'.tmp');q.write_text(json.dumps(d,indent=2,sort_keys=True)+'\n');q.replace(p)
def main():
 cp=json.loads((OUT/'checkpoint.json').read_text())
 if cp.get('status')!='failed_technical' or cp.get('active') is not None or cp.get('last_execution_id')!='D1_TAS_L2_A1_seed41':
  raise SystemExit('Expected one failed D1 technical attempt and no active process')
 failed=OUT/'runs/D1_TAS_L2_A1_seed41/technical-validation.json'
 if not failed.is_file(): raise SystemExit('Missing technical failure report')
 for source,dest in [(OUT/'plan.json',OUT/'plan_technical_attempt_01.json'),(OUT/'protocol_manifest.json',OUT/'protocol_manifest_technical_attempt_01.json')]:
  if not dest.exists():dest.write_bytes(source.read_bytes())
 sys.path.insert(0,str(HERE));import run_study
 plan=run_study.make_plan()
 plan['technical_correction']={'id':'technical-correction-1','cause':'base network selected without isolated packet/clock probe submodules','correction':'select pilot wrapper NED that adds only the probes','previous_plan_sha256':sha(OUT/'plan_technical_attempt_01.json'),'failed_attempt_report_sha256':sha(failed),'methodological_parameters_changed':False,'replacement_attempt_budget_remaining':1}
 atomic(OUT/'plan.json',plan)
 old=json.loads((OUT/'protocol_manifest_technical_attempt_01.json').read_text())
 manifest={'status':'technical_correction_frozen_before_replacement','plan_sha256':sha(OUT/'plan.json'),'protocol_sha256':sha(HERE/'protocol.md'),
   'technical_correction_path':str((HERE/'technical_correction_2026-10-19.md').relative_to(ROOT)),
   'technical_correction_sha256':sha(HERE/'technical_correction_2026-10-19.md'),
   'previous_manifest_sha256':sha(OUT/'protocol_manifest_technical_attempt_01.json'),
   'previous_plan_sha256':sha(OUT/'plan_technical_attempt_01.json'),'source_hashes':plan['source_hashes'],
   'current_commit':plan['git_commit'],'working_tree_status':plan['working_tree_status_at_plan'],'created_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())}
 atomic(OUT/'protocol_manifest.json',manifest)
 cp.update({'status':'planned','phase':'technical_replacement_preflight','active':None,
   'previous_technical_failure':{'execution_id':'D1_TAS_L2_A1_seed41','attempt_number':1,'path':str(failed.relative_to(ROOT)),'cause':'missing audit probes due wrong network selector'},
   'technical_replacement_budget_remaining':1,'instrumentation_validated':True,'plan_version':2})
 atomic(OUT/'checkpoint.json',cp)
 print('Versioned technical correction frozen; no simulation launched.')
if __name__=='__main__':main()
