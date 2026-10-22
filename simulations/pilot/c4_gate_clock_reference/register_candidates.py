#!/usr/bin/env python3
"""Create the immutable pre-candidate registry from controls and protocol rules."""
import hashlib, importlib.util, json, math, sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
RESULTS=HERE/'results'
spec=importlib.util.spec_from_file_location('c4_runner_core',HERE/'runner_core.py')
r=importlib.util.module_from_spec(spec);sys.modules[spec.name]=r;spec.loader.exec_module(r)
manifest=r.make_manifest()
ref=r.run_profile_for_load(manifest,2,'C4compensated')
c3=r.run_profile_for_load(manifest,2,'C3sync')
aud=json.loads((RESULTS/'mechanism_audit_controls.json').read_text())
mech=aud['runs']['C4_reference']['gate_timing']
ports=sorted(r.TAS_EGRESSES)
# One mechanism-derived multiplier per actually configured CBS TC at a gated egress.
# The observed eligible fraction is open time minus guard-band time, divided by
# measurement duration. This is an exploratory control-informed estimate, not a guarantee.
m_mult={}
for (port,tc),rate in sorted(ref.items()):
    if port not in r.TAS_EGRESSES: continue
    q=f'{port}/TC{tc}'
    if q not in mech: raise SystemExit(f'missing gate/guard evidence for {q}')
    f=float(mech[q]['credit_positive_eligible_fraction_estimate'])
    if not 0 < f <= 1: raise SystemExit(f'invalid eligible fraction {f} for {q}')
    m_mult[q]=0.77/f
# Resolve physical port rates from the installed topology profile; every altered
# egress is 1 Gb/s. Other profile ports are also included in each cap total.
port_rate={p:1_000_000_000 for p,tc in ref}
port_rate.update({p:1_000_000_000 for p,tc in c3})
base_totals={}
for (p,tc),bps in ref.items():base_totals[p]=base_totals.get(p,0)+int(bps)
base_sig=lambda profile:hashlib.sha256(json.dumps([[p,t,int(v)] for (p,t),v in sorted(profile.items())],separators=(',',':')).encode()).hexdigest()
base_signature=base_sig(ref)
specs=[('M',m_mult,'mechanism_derived_control_estimate'),('H005',{'HPC.eth[0]/TC4':1.005},'predeclared_HPC_only_plus_0.5_percent'),
       ('A001',{f'{p}/TC{tc}':1.001 for p,tc in ref if p in r.TAS_EGRESSES},'predeclared_all_gated_CBS_plus_0.1_percent'),
       ('A005',{f'{p}/TC{tc}':1.005 for p,tc in ref if p in r.TAS_EGRESSES},'predeclared_all_gated_CBS_plus_0.5_percent'),
       ('A010',{f'{p}/TC{tc}':1.01 for p,tc in ref if p in r.TAS_EGRESSES},'predeclared_all_gated_CBS_plus_1_percent'),
       ('A020',{f'{p}/TC{tc}':1.02 for p,tc in ref if p in r.TAS_EGRESSES},'predeclared_all_gated_CBS_plus_2_percent')]
seen={base_signature}; candidates=[]; occupied=[]
for cid,mults,method in specs:
    profile=dict(ref)
    for key,mul in mults.items():
        p,tc=key.rsplit('/TC',1); k=(p,int(tc))
        if k not in profile: raise SystemExit(f'{cid} target is not an effective CBS queue: {key}')
        profile[k]=round(profile[k]*float(mul))
    sig=base_sig(profile); totals={}
    for (p,tc),bps in profile.items():totals[p]=totals.get(p,0)+bps
    checks={p:{'total_reservation_bps':totals[p],'port_rate_bps':port_rate[p],
               'cap_fraction':totals[p]/port_rate[p],'headroom_to_75pct_bps':int(.75*port_rate[p])-totals[p],
               'admissible':totals[p] <= .75*port_rate[p]} for p in sorted(totals)}
    duplicate=sig in seen
    cap_ok=all(x['admissible'] for x in checks.values())
    status='registered' if (not duplicate and cap_ok) else ('rejected_duplicate' if duplicate else 'rejected_75pct_cap')
    if status=='registered':seen.add(sig);occupied.append(cid)
    normalized=sum((profile[k]-ref[k])/port_rate[k[0]] for k in profile if k[0] in r.TAS_EGRESSES)
    candidates.append({'candidate_id':cid,'status':status,'transformation':method,
      'multipliers_by_queue':mults,'base_reference_profile_sha256':base_signature,
      'effective_profile_bps':{f'{p}/TC{tc}':bps for (p,tc),bps in sorted(profile.items())},
      'effective_profile_sha256':sig,'port_reservations':checks,
      'normalized_sum_increase':normalized,'duplicate_of':None if not duplicate else 'earlier_registered_profile',
      'method_inputs':({'effective_eligible_fraction_by_queue':{k:mech[k]['credit_positive_eligible_fraction_estimate'] for k in mults},
         'formula':'I_M(q)=I_C3(q)/f_eligible(q); equivalently I_ref(q)*0.77/f_eligible(q)',
         'measurement':'C4_reference seed41 L2/A1, [1,31), open gate minus observed guard-band duration',
         'limitation':'control-informed estimate; guard-band duration depends on observed packet fit and queue state; does not guarantee service or stability'} if cid=='M' else {})})
registry={'exploratory':True,'official_c4_frozen':False,'profile_id':'reduction_11','reference':'C4_shared_SPbrakes / idleSlope_C3 divided by 0.77','seed41_cell':'L2_A1',
 'candidate_limit':6,'candidate_ids_predeclared':['M','H005','A001','A005','A010','A020'],
 'candidate_order':['M','H005','A001','A005','A010','A020'],'selection_rule':'among seed41 candidates passing all P1 application and stability gates, minimize sum of per-queue reservation increments divided by physical port rate; tie order is candidate_order',
 'ceiling_rule':'sum all effective CBS idleSlope on each physical egress; reject before execution if >75%; never clip',
 'base_reference_profile_bps':{f'{p}/TC{tc}':bps for (p,tc),bps in sorted(ref.items())},'base_reference_profile_sha256':base_signature,
 'C3_profile_bps':{f'{p}/TC{tc}':bps for (p,tc),bps in sorted(c3.items())},
 'measured_gate_eligible_fraction':{k:v['credit_positive_eligible_fraction_estimate'] for k,v in mech.items()},
 'candidate_generation_note':'Only the six predefined positions are considered. Duplicate/cap-rejected/not-generated positions are not replaced.',
 'candidates':candidates,'selected_candidate_id':None,'selection_status':'pending_seed41_candidate_gates'}
out=HERE/'candidate_registry.json';out.write_text(json.dumps(registry,indent=2,ensure_ascii=False)+'\n')
print('registry',out)
for x in candidates:
 print(x['candidate_id'],x['status'],'sig',x['effective_profile_sha256'][:12],'norm_increase',f"{x['normalized_sum_increase']:.12g}")
 for p in ports:
  c=x['port_reservations'][p]
  print(' ',p,x['effective_profile_bps'].get(f'{p}/TC4'), 'total',c['total_reservation_bps'],'fraction',f"{c['cap_fraction']:.6%}",'headroom',c['headroom_to_75pct_bps'])
