#!/usr/bin/env python3
"""Materialize isolated C4 study config from its frozen candidate contract."""
import json, hashlib
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
SIM=ROOT/'simulations'
OUT=HERE/'results'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    c=json.loads((OUT/'candidate_contract.json').read_text())
    tc=json.loads((SIM/'pilot/c4_joint_dimensioning/treatment_contracts.json').read_text())
    historical_treatments=tc['treatments']
    tc['exploratory']=True; tc['official_c4_frozen']=False
    tc['profile_scope']='C3 reduction_11-derived candidates; paired TAS/noTAS; F21/F22 remain PCP4/TC4 and excluded from permanent CBS sums.'
    tc['treatments']={}
    names={'D1':'D1_D3_GCL_service_corrected','D2':'D2_coordinated_10pct','D3':'D3_coordinated_20pct'}
    for cid,name in names.items():
        g=c['candidates'][name]['GCL']
        gates={'period_s':1e-4,'class4_open_s':g['HPC.eth[0]']['tc4_open_s'],'class7_open_s':g['HPC.eth[0]']['tc7_open_s'],
          'class4_offset_s_by_egress':{p:x['tc4_offset_parameter_s'] for p,x in g.items()},
          'class7_offset_s_by_egress':{p:x['tc7_offset_parameter_s'] for p,x in g.items()},
          'clockModule':'^.^.^.^.clock','scheduleForAbsoluteTime':True,'initiallyOpen':True,'implicit_guard_band':True,'candidate_name':name}
        tc['treatments'][cid+'_TAS']={'gates':gates,'CBS_profile':name}
        tc['treatments'][cid+'_noTAS']={'gates':{'kind':'permanently_open','CBS_profile_same_as_TAS':True},'CBS_profile':name}
    tc['treatments']['B_local']=historical_treatments['B_local']
    tc['treatments']['C3_sync_control']=historical_treatments['C3_sync_control']
    (HERE/'treatment_contracts.json').write_text(json.dumps(tc,indent=2,sort_keys=True)+'\n')
    old=json.loads((SIM/'pilot/c4_joint_dimensioning/results/dimensioning.json').read_text())
    cand={}
    for cid,name in names.items():
        x=c['candidates'][name]
        cand[cid]={'name':name,'profile_bps':x['CBS_profile_bps'],'GCL':x['GCL'],'port_reservation_caps':x['port_reservation_caps'],'sizing':x['CBS_reserve_sizing']}
    dim={'exploratory':True,'official_c4_frozen':False,'candidate_designs':cand,'fixed_inputs':old['fixed_inputs'],
      'acceptance':c['selection_rule'],'budget':c['budget'],'design_method':c['model'],'source_contract_sha256':sha(OUT/'candidate_contract.json')}
    (OUT/'dimensioning.json').write_text(json.dumps(dim,indent=2,sort_keys=True)+'\n')
    base=(SIM/'pilot/c4_real_clock_service_margin_corrected/pilot.ini').read_text()
    suffix='\n# Isolated joint-dimensioning configurations; never loaded by official runs.\n'
    for load,align in [('L2','A1'),('L0','A0'),('L1','A1')]:
        for name in ['B_local','C3_sync_control']+[f'D{i}_{x}' for i in (1,2,3) for x in ('TAS','noTAS')]:
            suffix+=f'\n[Config Joint_{name}_{load}_{align}]\nextends = PilotGptp, ValidateC2, {load}, {align}\n'
    (HERE/'pilot.ini').write_text(base+suffix)
    for ned in (HERE/'RealClockTraceProbe.ned', HERE/'ClockPrecisionProbe.ned'):
        text=ned.read_text().replace('zonal_ivn_tsn.simulations.pilot.c4_joint_dimensioning',
                                     'zonal_ivn_tsn.simulations.pilot.c4_feasibility_decision')
        ned.write_text(text)
    rp=HERE/'run_study.py'; runner=rp.read_text()
    runner=runner.replace('A005_RESULT = SIM / "pilot/c4_gate_clock_reference/results/runs/A005_local_L2_A1_seed41_v1/pilot-result.json"','A005_RESULT = SIM / "pilot/c4_real_clock_service_margin_corrected/results/runs/B_local_L2_A1_seed41/pilot-result.json"')
    runner=runner.replace("AUDIT_DIR = SIM / 'pilot/c4_real_clock_service_margin/results/audits/audit_2026-10-18'","AUDIT_DIR = HERE / 'audit'")
    runner=runner.replace('"pilot_id":"c4-joint-dimensioning"','"pilot_id":"c4-feasibility-decision"')
    runner=runner.replace('zonal_ivn_tsn.simulations.zonal.networks.ZonalIVN',
                          'zonal_ivn_tsn.simulations.pilot.c4_feasibility_decision.ZonalIVN')
    rp.write_text(runner)
    print('Prepared independent treatment contracts, candidate profiles, pilot INI, and runner paths; no simulation launched.')
if __name__=='__main__': main()
