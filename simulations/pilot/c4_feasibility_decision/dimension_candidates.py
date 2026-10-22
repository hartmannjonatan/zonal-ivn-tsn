#!/usr/bin/env python3
"""Deterministic, offline GCL/CBS candidates for the isolated feasibility pilot."""
from __future__ import annotations
import csv, hashlib, json, math
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
HERE=Path(__file__).resolve().parent
SIM=ROOT/'simulations'
FLOW_FILE=SIM/'zonal/traffic/flows.csv'
TRANSIENT_FILE=SIM/'zonal/traffic/transients.csv'
RESERVATION_FILE=SIM/'zonal/traffic/cbs_nominal_reservations.csv'
C3_FILE=SIM/'campaigns/p1-v2-official-2026-10/results/calibration/C3_calibration.json'
C3_PROGRESS=SIM/'campaigns/p1-v2-official-2026-10/results/progress.json'
A005_FILE=SIM/'pilot/c4_real_clock_service_margin_corrected/results/runs/B_local_L2_A1_seed41/pilot-result.json'
OLD_CONTRACT=SIM/'pilot/c4_joint_dimensioning/treatment_contracts.json'
OLD_DIMENSION=SIM/'pilot/c4_joint_dimensioning/results/dimensioning.json'
PORTS=('HPC.eth[0]','CSW.eth[1]','CSW.eth[2]','CSW.eth[3]')
EGRESSES=tuple(p+'/TC4' for p in PORTS)
PERIOD_US=100.0
TC7_OPEN_US=30.0
F13_EGRESS='Z3.ZSW.eth[7]/TC4'
MARGINS={'D1_D3_GCL_service_corrected':1.10,'D2_coordinated_10pct':1.10,'D3_coordinated_20pct':1.20}

def sha(p:Path)->str:
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()

def readcsv(p):
    with p.open(newline='') as f:return list(csv.DictReader(f))

def main():
    flows={r['flow_id']:r for r in readcsv(FLOW_FILE)}
    transients=readcsv(TRANSIENT_FILE)
    reservations=readcsv(RESERVATION_FILE)
    c3=json.loads(C3_FILE.read_text()); checkpoint=json.loads(C3_PROGRESS.read_text())
    if c3.get('status')!='frozen_and_accepted' or c3.get('final_profile_id')!='reduction_11' or checkpoint.get('calibration_final_profile_id')!='reduction_11' or checkpoint.get('calibration_profile_accepted') is not True:
        raise SystemExit('Frozen C3 reduction_11 profile not confirmed')
    c3_profile={k:int(v) for k,v in c3['selected_profile_bps'].items()}
    a005=json.loads(A005_FILE.read_text())
    if not a005.get('simulation_valid') or not a005.get('effective_profile_bps'):
        raise SystemExit('Audited A005 profile not available')
    a005_profile={k:int(v) for k,v in a005['effective_profile_bps'].items()}
    factor=2.5
    def periodic_rate(flow_id, layer):
        f=flows[flow_id]
        p=float(f['period_us'])/(factor if int(f['scalable']) else 1)
        return int(f[layer])*8*int(f['packets_per_cycle'])/(p*1e-6)
    # Permanent L2 rates are kept in separate units. CBS idleSlope follows the catalog R_wire basis.
    perm={}
    for row in reservations:
        if row['load']!='L2' or int(row['traffic_class'])!=4: continue
        ids=[x for x in row['permanent_flows'].split(';') if x]
        perm[row['egress']+'/TC4']={
          'flows':ids,
          'payload_bps':sum(periodic_rate(fid,'app_bytes') for fid in ids),
          'queue_mac_bps':sum(periodic_rate(fid,'mac_bytes') for fid in ids),
          'wire_bps':sum(periodic_rate(fid,'wire_bytes') for fid in ids),
          'catalog_idleSlope_bps':int(row['idle_slope_bps'])}
    # F21/F22 are not part of permanent reservations. Use a catalog-wide, A1 aligned worst-pair envelope.
    sig=[]
    for s in transients:
        volume=int(s['volume_bytes']); duration=float(s['duration_ms'])/1000
        packets=math.ceil(volume/1472)
        queue_bits=(volume+packets*(1522-1472))*8
        wire_bits=(volume+packets*(1542-1472))*8
        sig.append({'id':s['signature_id'],'volume_app_bytes':volume,'duration_s':duration,'packets':packets,
                    'queue_bps':queue_bits/duration,'wire_bps':wire_bits/duration})
    pairs=[]
    for a in sig:
      for b in sig:
        overlap=min(a['duration_s'],b['duration_s'])
        pairs.append({'F21_signature':a['id'],'F22_signature':b['id'],'overlap_s':overlap,
                      'aggregate_queue_rate_bps':perm['CSW.eth[3]/TC4']['queue_mac_bps']+a['queue_bps']+b['queue_bps'],
                      'aggregate_wire_rate_bps':perm['CSW.eth[3]/TC4']['wire_bps']+a['wire_bps']+b['wire_bps']})
    worst=max(pairs,key=lambda x:x['aggregate_wire_rate_bps'])
    envelope={**worst,'permanent_F13_queue_bps':perm['CSW.eth[3]/TC4']['queue_mac_bps'],
      'permanent_F13_wire_bps':perm['CSW.eth[3]/TC4']['wire_bps'],
      'catalog_basis':'all 10x10 event-signature pairs; A1 same start; bursts uniform packetizer over recorded duration; transients excluded from permanent reservation but included in service envelope'}
    # Maximum TC4 packet is F14/transient MAC frame 1522 B. PeriodicGate requires dataLength+64b to fit;
    # the installed Ethernet PHY then holds 96b IFG. Use both in the conservative nonpreemptive blocking guard.
    mac_max_bytes=max(int(f['mac_bytes']) for f in flows.values() if int(f['traffic_class'])==4)
    gate_fit_s=(mac_max_bytes*8+64)/1e9
    ifg_s=96/1e9
    blocking_guard_us=(gate_fit_s+ifg_s)*1e6
    # D3's event-derived contract is copied verbatim for the schedule-preserving arm.
    oldc=json.loads(OLD_CONTRACT.read_text())
    d3=oldc['treatments']['D3_TAS']['gates']
    old_d3=json.loads(OLD_DIMENSION.read_text())['candidate_designs']['D3']
    d3_overlap={k:float(v['tc4_tc7_overlap_us']) for k,v in old_d3['service_by_port'].items()}
    candidates={}
    specs=[
      ('D1_D3_GCL_service_corrected',82.0,12.0,1.10,'preserve D3 GCL and correct the CBS service budget'),
      ('D2_coordinated_10pct',50.0,0.0,1.10,'phase-coordinated non-overlap windows with a 10% envelope target'),
      ('D3_coordinated_20pct',55.0,0.0,1.20,'same coordinated phase, 5 us more TC4, 20% envelope target'),
    ]
    cbs_rows=readcsv(RESERVATION_FILE)
    physical={r['egress']:int(r['port_rate_bps']) for r in cbs_rows if r['load']=='L2'}
    for cid,t4,overlap,margin,label in specs:
        rates=dict(c3_profile)
        gates={}
        credit_budget={}
        for port,key in zip(PORTS,EGRESSES):
            ov=d3_overlap[port] if cid.startswith('D1_') else 0.0
            eligible=(t4-ov-blocking_guard_us)/PERIOD_US
            if eligible<=0: raise SystemExit(f'{cid} has no credit-open time at {port}')
            demand=envelope['aggregate_wire_rate_bps'] if port=='CSW.eth[3]' else perm[key]['wire_bps']
            reserve=math.ceil(margin*demand/eligible)
            rates[key]=reserve
            credit_budget[port]={'permanent_wire_demand_bps':perm[key]['wire_bps'],
              'permanent_queue_demand_bps':perm[key]['queue_mac_bps'],
              'transient_envelope_wire_bps':envelope['aggregate_wire_rate_bps'] if port=='CSW.eth[3]' else 0,
              'chosen_wire_demand_bps':demand,'margin_factor':margin,'tc4_open_us':t4,
              'tc7_tc4_overlap_us':ov,'gate_fit_plus_ifg_guard_us':blocking_guard_us,
              'credit_eligible_fraction_estimate':eligible,'idleSlope_bps':reserve,
              'idleSlope_C3_bps':c3_profile[key],'idleSlope_A005_bps':a005_profile[key],
              'ratio_to_C3':reserve/c3_profile[key],'ratio_to_A005':reserve/a005_profile[key],
              'target_wire_service_bps':margin*demand,
              'service_bound':'optimistic upper budget under assumed credit-eligible interval; not a guaranteed lower bound'}
            if cid.startswith('D1_'):
                contract=d3
                off4=float(contract['class4_offset_s_by_egress'][port])
                off7=float(contract['class7_offset_s_by_egress'][port])
                open7=float(contract['class7_open_s']); period=float(contract['period_s'])
            else:
                start7=0.0 if port=='HPC.eth[0]' else .676e-6
                start4=start7+TC7_OPEN_US*1e-6
                open7=TC7_OPEN_US*1e-6; period=PERIOD_US*1e-6
                off7=(period-start7)%period; off4=(period-start4)%period
            gates[port]={'period_s':period,'tc4_open_s':t4*1e-6,'tc7_open_s':open7,
              'tc4_offset_parameter_s':off4,'tc7_offset_parameter_s':off7,
              'tc4_start_phase_s':(period-off4)%period,'tc7_start_phase_s':(period-off7)%period,
              'clockModule':'^.^.^.^.clock','scheduleForAbsoluteTime':True,'initiallyOpen':True,
              'enableImplicitGuardBand':True,'extraLength_bits':64,'extraDuration_s':0,
              'TC0_to_TC6_schedule':'TC4 schedule','TC7_schedule':'TC7 schedule'}
        # Corrected local F13 service holds the A005*1.02 value (2% above R_wire demand), not a queue-rate reinterpretation.
        rates[F13_EGRESS]=round(a005_profile[F13_EGRESS]*1.02)
        caps={}
        for k,v in rates.items():
            port,tc=k.rsplit('/TC',1)
            caps[port]=caps.get(port,0)+v
        caprows=[]
        for p,total in sorted(caps.items()):
            pr=physical.get(p,1_000_000_000)
            caprows.append({'port':p,'CBS_sum_bps':total,'physical_rate_bps':pr,'fraction':total/pr,
              'headroom_to_75pct_bps':.75*pr-total,'passes_75pct':total<=.75*pr})
        candidates[cid]={'description':label,'GCL':gates,'CBS_profile_bps':rates,'CBS_reserve_sizing':credit_budget,
          'F13_local_Z3_eth7_idleSlope_bps':rates[F13_EGRESS],
          'F13_local_ratio_to_C3':rates[F13_EGRESS]/c3_profile[F13_EGRESS],
          'port_reservation_caps':caprows,'passes_75pct':all(x['passes_75pct'] for x in caprows),
          'target_service_evidence':'must be checked empirically; analytical rates are estimates only'}
    out={'schema_version':'1.0','exploratory':True,'official_c4_frozen':False,'candidate_generation':'dimension_candidates.py',
      'fixed_scope':{'cell':'L2/A1','seed':41,'warmup_s':1,'measurement_s':[1,31],'drain_s':.05,
        'P1_changed':False,'C0_C3_changed':False,'official_C4_campaign_started':False,'C3_profile_id':'reduction_11',
        'transient_classification':'F21/F22 PCP4 TC4; excluded from permanent CBS sums, included in burst service envelope',
        'F13_Z3_eth7_rule':'retain A005*1.02 = 28.152 Mb/s; this equals 2% above F13 R_wire 27.60 Mb/s, and 9.97% above its 25.60 Mb/s queue data rate'},
      'model':{'load_factor_L2':factor,'permanent_egress_rates':perm,'all_transient_signatures':sig,
        'worst_A1_transient_pair_envelope':envelope,'max_tc4_mac_bytes':mac_max_bytes,
        'INET_PeriodicGate_fit_guard_us':gate_fit_s*1e6,'INET_IFG_bits':96,'nonpreemptive_guard_us':blocking_guard_us,
        'CBS_credit_update':'CreditBasedGate gains idleSlope only while periodic gate open/outside implicit guard band; it spends during TX and IFG; frozen while periodic gate closed/guardband when accumulateCreditInGuardBand=false.',
        'effective_fraction_formula':'(TC4_open - simultaneous_TC4_TC7_overlap - (max_MAC_bits + PeriodicGate extraLength + IFG bits)/R_port)/period',
        'limitations':'formula estimates available credit evolution; it is not a defensible lower service guarantee and does not model event-level phase/jitter/competition exactly'},
      'margin_rule':{'D1_D3_GCL_service_corrected':0.10,'D2_coordinated_10pct':0.10,'D3_coordinated_20pct':0.20,
        'rationale':'10% tests modest reserve above the worst signature-pair mean wire demand; 20% tests a higher buffer without exceeding 75% CBS cap. These are predeclared empirical design points, not P1 gates.'},
      'candidates':candidates,'source_hashes':{str(p.relative_to(ROOT)):sha(p) for p in [FLOW_FILE,TRANSIENT_FILE,RESERVATION_FILE,C3_FILE,C3_PROGRESS,A005_FILE,OLD_CONTRACT,OLD_DIMENSION]},
      'controls':{'B_local':'reuse only with existing exact hash/calendar/profile/runtime audit','C3_sync_control':'reuse only with existing exact hash/calendar/profile/runtime audit'},
      'selection_rule':'In seed41 choose among candidates that pass all P1 application/stability gates, sampled synchronization, technical contracts, and show no confirmed overflow-driven loss in F13/F21/F22 plus adequate service/recovery evidence. Select smallest increase in normalized port reservations; tie: D1, D2, D3. No selection from partial improvements.',
      'conditional_rule':'If one is selected, keep exact profile/GCL fixed in seeds43/47 with paired calendars and C3_sync; then same three treatments in L0/A0 and L1/A1 seed41, deriving every CBS rate from the load-specific C3 profile using the frozen candidate ratios for four gated TC4 ports and the fixed 1.02 local F13 ratio. No retuning.',
      'budget':{'initial_new_simulations':6,'reused_controls':2,'initial_total_methodological_treatments':8,'seed43_47_if_selected':6,'L0_L1_if_seed_checks_pass':6,'maximum':20,'jobs':1,'free_disk_min_GiB':40,'MemAvailable_min_GiB':7,'max_technical_replacements':1,'diagnostic_D3_rerun':0,'reason_no_diagnostic':'preserved packet-stage times plus 100ns final link delay reconstruct and match exact receiver maxima and miss counts'}}
    outp=HERE/'results/candidate_contract.json';outp.parent.mkdir(parents=True,exist_ok=True);outp.write_text(json.dumps(out,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'output':str(outp.relative_to(ROOT)),'worst_A1_pair':envelope,'caps':{cid:{x['port']:round(x['fraction']*100,3) for x in c['port_reservation_caps']} for cid,c in candidates.items()},
      'gated_rates':{cid:{k:c['CBS_profile_bps'][k] for k in EGRESSES} for cid,c in candidates.items()},'all_cap_pass':all(c['passes_75pct'] for c in candidates.values())},indent=2))
if __name__=='__main__':main()
