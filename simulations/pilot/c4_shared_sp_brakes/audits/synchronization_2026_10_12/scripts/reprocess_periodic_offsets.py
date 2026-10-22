#!/usr/bin/env python3
"""Separate true 1 ms clock reports from same-time correction emissions."""
import csv,gzip,math,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[6]
RUNS=ROOT/'simulations/pilot/c4_shared_sp_brakes/results/runs'
OUT=Path(__file__).resolve().parents[1]/'data'
OUT.mkdir(parents=True,exist_ok=True)
def nr(a,p): return sorted(a)[max(0,math.ceil(p*len(a))-1)] if a else None
records=[]; summaries=[]
for src in sorted(RUNS.glob('*/Pilot_*-0/clock_offsets.csv.gz')):
 execid=src.parts[-3]
 per={}; allrows={}
 with gzip.open(src,'rt') as f:
  for r in csv.DictReader(f):
   t=float(r['simtime_s']); node=r['node']; value=float(r['offset_s'])
   if not 1.0<=t<31.0: continue
   allrows.setdefault(node,[]).append((t,value))
   if abs(t*1000-round(t*1000))<=1e-7:
    per.setdefault(node,[]).append((t,value))
 for node,rows in sorted(per.items()):
  rows.sort(); absvals=[abs(o) for _,o in rows]; peak=max(rows,key=lambda z:abs(z[1]))
  times=[t for t,_ in rows]
  # Estimate duration from recorded 1ms points only; label as sampled interpolation, never as observed continuous behavior.
  dur=0.0
  for (ta,oa),(tb,ob) in zip(rows,rows[1:]):
   aa,ab=abs(oa)-1e-6,abs(ob)-1e-6; dt=tb-ta
   if aa>0 and ab>0:dur+=dt
   elif aa>0>=ab:dur+=dt*aa/(aa-ab)
   elif aa<=0<ab:dur+=dt*ab/(ab-aa)
  mixed=allrows.get(node,[])
  oldpeak=max(mixed,key=lambda z:abs(z[1])) if mixed else None
  non_grid=[x for x in mixed if abs(x[0]*1000-round(x[0]*1000))>1e-7]
  summaries.append({'execution_id':execid,'node':node,'periodic_sample_count':len(rows),
   'periodic_expected_count':30000,'periodic_population_complete':len(rows)==30000,
   'sample_resolution_s':0.001,'sampled_abs_offset_p50_s':nr(absvals,.5),'sampled_abs_offset_p95_s':nr(absvals,.95),
   'sampled_abs_offset_p99_s':nr(absvals,.99),'sampled_abs_offset_max_s':max(absvals) if absvals else None,
   'sampled_signed_offset_at_max_s':peak[1],'sampled_max_time_s':peak[0],
   'offset_at_warmup_end_t1_s':next((o for t,o in rows if abs(t-1.0)<=1e-9),None),
   'sampled_points_abs_over_1us':sum(x>1e-6 for x in absvals),
   'piecewise_linear_sampled_duration_over_1us_s':dur,
   'legacy_all_emissions_count':len(mixed),'legacy_non_grid_emission_count':len(non_grid),
   'legacy_mixed_max_abs_s':abs(oldpeak[1]) if oldpeak else None,'legacy_mixed_max_signed_s':oldpeak[1] if oldpeak else None,
   'legacy_mixed_max_time_s':oldpeak[0] if oldpeak else None,
   'interpretation':'periodic 1ms samples; same-time non-grid timeChanged emissions excluded from distribution because order/state duration is not preserved in compact export; sampled pass does not establish continuous pass'})
  for t,o in rows: records.append((execid,node,t,o))
with gzip.open(OUT/'periodic_offsets_1ms.csv.gz','wt',newline='') as f:
 w=csv.writer(f);w.writerow(['execution_id','node','simtime_s','offset_s']);w.writerows(records)
result={'source':'existing compact clock_offsets.csv.gz files only','window_s':[1.0,31.0],'population':'all 1ms-grid samples with 1<=t<31; no extrapolation; HPC clock vector has matching 1ms points; nearest-rank quantiles',
 'excluded_from_periodic_population':'non-grid timeChanged rows at phase corrections; legacy extractor sorted same-time rows by value and discarded emission order; these remain separately recorded as legacy mixed maximum',
 'continuous_gate':'not inferred from sampled-only data; see direct technical probes', 'runs':summaries}
(OUT/'periodic_offsets_1ms_summary.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({'run_nodes':len(summaries),'sample_counts':sorted(set(x['periodic_sample_count'] for x in summaries)),'max_over_runs_us':max(x['sampled_abs_offset_max_s'] for x in summaries)*1e6,'legacy_max_us':max(x['legacy_mixed_max_abs_s'] for x in summaries)*1e6},indent=2))
