#!/usr/bin/env python3
"""Deterministic offline joint GCL/CBS design; reads only frozen pilot inputs."""
import csv, json, math, hashlib
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
SIM=ROOT/'simulations'
C3_PATH=SIM/'campaigns/p1-v2-official-2026-10/results/calibration/C3_calibration.json'
C3_CHECK=SIM/'campaigns/p1-v2-official-2026-10/results/progress.json'
A005_PATH=SIM/'pilot/c4_real_clock_service_margin_corrected/results/runs/B_local_L2_A1_seed41/pilot-result.json'
DEMAND_PATH=SIM/'pilot/c4_real_clock_service_margin_corrected/historical_A005_service_demand.json'
FLOW_PATH=SIM/'zonal/traffic/flows.csv'
RES_PATH=SIM/'zonal/traffic/cbs_nominal_reservations.csv'
TREATMENTS=[
    {'id':'D1','tc4_open_us':90.0,'tc7_open_us':20.0,'overlap_us':10.0},
    {'id':'D2','tc4_open_us':85.0,'tc7_open_us':25.0,'overlap_us':10.0},
    {'id':'D3','tc4_open_us':82.0,'tc7_open_us':30.0,'overlap_us':12.0},
]
PERIOD_US=100.0
SERVICE_TARGET_FACTOR=1.20
CAP_FRACTION=0.75
MAX_FRAME_MAC_BYTES=1542
EXTRA_LENGTH_BITS=64
RELATIVE_PHASE_ENVELOPE_US=1.0
PORTS={'HPC.eth[0]':'1e9','CSW.eth[1]':'1e9','CSW.eth[2]':'1e9','CSW.eth[3]':'1e9'}
EGRESS_TO_HIST={'HPC.eth[0]':'HPC.eth[0]/TC4','CSW.eth[1]':'CSW.eth[1]/TC4','CSW.eth[2]':'CSW.eth[2]/TC4','CSW.eth[3]':'CSW.eth[3]/TC4'}

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def physical_rate(egress):
    if egress.startswith('RADAR') or egress.startswith(('Z1.ZSW.eth[6]','Z1.ZSW.eth[7]','Z1.ZSW.eth[8]','Z2.ZSW.eth[6]','Z2.ZSW.eth[7]','Z2.ZSW.eth[8]','Z3.ZSW.eth[6]','Z3.ZSW.eth[7]','Z3.ZSW.eth[8]')): return 100_000_000
    return 1_000_000_000
def circular_overlap(start_a,len_a,start_b,len_b,period):
    # Integer nanosecond-grid interval intersection on a circular period.
    a=[]
    for s,l in [(start_a%period,len_a)]:
        e=s+l
        a += [(s,min(e,period))]
        if e>period:a.append((0,e-period))
    b=[]
    for s,l in [(start_b%period,len_b)]:
        e=s+l;b += [(s,min(e,period))]
        if e>period:b.append((0,e-period))
    return sum(max(0,min(x2,y2)-max(x1,y1)) for x1,x2 in a for y1,y2 in b)

def main():
    c3=json.loads(C3_PATH.read_text()); cp=json.loads(C3_CHECK.read_text()); a005=json.loads(A005_PATH.read_text()); hist=json.loads(DEMAND_PATH.read_text())
    if c3.get('status')!='frozen_and_accepted' or c3.get('final_profile_id')!='reduction_11' or cp.get('calibration_profile_accepted') is not True: raise SystemExit('C3 reduction_11 checkpoint failed')
    c3_profile={k:int(v) for k,v in c3['selected_profile_bps'].items()}
    a005_profile={k:int(v) for k,v in a005['effective_profile_bps'].items()}
    if not a005.get('simulation_valid') or not a005.get('resolved_profile_audit',{}).get('pass'): raise SystemExit('corrected A005 control not technically valid')
    # Catalog queue-bit rates (MAC-frame bits) from permanent flow IDs actually listed on each port.
    flows={}
    with FLOW_PATH.open(newline='') as f:
        for row in csv.DictReader(f): flows[row['flow_id']]=row
    nominal={}
    with RES_PATH.open(newline='') as f:
        for row in csv.DictReader(f):
            if row['load']!='L2':continue
            e=row['egress']; tc=int(row['traffic_class']); qrate=0.0
            for fid in filter(None,row['permanent_flows'].split(';')):
                flow=flows[fid]; qrate += int(flow['mac_bytes'])*8*int(flow['packets_per_cycle'])/(float(flow['period_us'])*1e-6)
            nominal[f'{e}/TC{tc}']={'catalog_permanent_Rwire_bps':int(row['idle_slope_bps']),
                'catalog_permanent_queue_rate_bps':qrate,'permanent_flows':row['permanent_flows']}
    demands={key:{'historical_queue_offer_bps':float(hist['queue_bit_rates_bps'][key]['incomingPacketLengths:vector']),**nominal.get(key,{})} for key in EGRESS_TO_HIST.values()}
    candidate_data={}
    for t in TREATMENTS:
        t4=t['tc4_open_us'];t7=t['tc7_open_us'];period=PERIOD_US
        # A single maximum TC4 frame plus the installed CBS extraLength must finish before gate close.
        guard_us=(MAX_FRAME_MAC_BYTES*8+EXTRA_LENGTH_BITS)/1e9*1e6
        phase_starts={
            'HPC.eth[0]':t7-t['overlap_us'],
            'CSW.eth[1]':t7-t['overlap_us']+(MAX_FRAME_MAC_BYTES*8/1e9+0.1e-6)*1e6,
            'CSW.eth[2]':t7-t['overlap_us']+(MAX_FRAME_MAC_BYTES*8/1e9+0.1e-6)*1e6,
            'CSW.eth[3]':t7-t['overlap_us']+(84*8/1e9+0.1e-6)*1e6,
        }
        brake_starts={'HPC.eth[0]':0.0,'CSW.eth[1]':(84*8/1e9+0.1e-6)*1e6,
                      'CSW.eth[2]':(84*8/1e9+0.1e-6)*1e6,'CSW.eth[3]':(84*8/1e9+0.1e-6)*1e6}
        rates={k:v for k,v in c3_profile.items()}
        per_egress={}
        for port,key in EGRESS_TO_HIST.items():
            start=phase_starts[port]
            overlap=circular_overlap(start,t4,brake_starts[port],t7,period)
            exclusive=t4-overlap
            # Reserve one additional microsecond against observed relative
            # clock/gate phase variation. This is an engineering envelope
            # derived from the sampled 1-us synchronization criterion, not a
            # continuous-time guarantee.
            effective=max(0.0,exclusive-guard_us-RELATIVE_PHASE_ENVELOPE_US)/period
            demand=max(demands[key]['historical_queue_offer_bps'],demands[key]['catalog_permanent_queue_rate_bps'])
            if effective<=0: raise SystemExit(f'{t["id"]} has no TC4 credit-eligible interval on {port}')
            reserve=math.ceil(SERVICE_TARGET_FACTOR*demand/effective)
            rates[key]=reserve
            per_egress[port]={'tc4_open_us':t4,'tc7_open_us':t7,'tc4_start_phase_us':start%period,
                'tc7_start_phase_us':brake_starts[port],'tc4_tc7_overlap_us':overlap,
                'max_tc4_frame_guard_us':guard_us,'exclusive_credit_eligible_us_estimate':exclusive-guard_us,
                'phase_uncertainty_allowance_us':RELATIVE_PHASE_ENVELOPE_US,
                'eligible_fraction_after_phase_allowance':effective,
                'eligible_fraction_estimate':effective,'historical_queue_demand_bps':demands[key]['historical_queue_offer_bps'],
                'catalog_permanent_queue_demand_bps':demands[key]['catalog_permanent_queue_rate_bps'],
                'catalog_permanent_Rwire_bps':demands[key]['catalog_permanent_Rwire_bps'],
                'target_credit_bound_bps':SERVICE_TARGET_FACTOR*demand,'idleSlope_bps':reserve,
                'idleSlope_C3_bps':c3_profile[key],'idleSlope_A005_bps':a005_profile[key],
                'ratio_to_C3':reserve/c3_profile[key],'ratio_to_A005':reserve/a005_profile[key],
                'optimistic_service_upper_bound_bps':reserve*effective,
                'service_lower_bound_bps':None,
                'service_evidence':'candidate sizing estimate; no defensible analytical lower bound, empirical service must be measured'}
        # Local un-gated Z3 F13 CBS remains permanent and uses the previously fixed +2% exploratory adjustment.
        z3='Z3.ZSW.eth[7]/TC4'; rates[z3]=round(a005_profile[z3]*1.02)
        cap={}
        for key,val in rates.items():
            port,tc=key.rsplit('/TC',1); cap[port]=cap.get(port,0)+val
        cap_rows={port:{'CBS_sum_bps':total,'physical_rate_bps':physical_rate(port),'cap_fraction':total/physical_rate(port),
                        'headroom_bps_to_75pct':.75*physical_rate(port)-total,'passes_75pct':total<=.75*physical_rate(port)} for port,total in sorted(cap.items())}
        # Gate formulas use the NET period, durations and phase starts; offset is period-start under INET convention.
        gcl={'period_us':period,'tc4_open_us':t4,'tc7_open_us':t7,
             'tc4_start_phase_us_by_egress':{k:v%period for k,v in phase_starts.items()},
             'tc7_start_phase_us_by_egress':brake_starts,
             'tc4_offset_parameter_us_by_egress':{k:(period-v)%period for k,v in phase_starts.items()},
             'tc7_offset_parameter_us_by_egress':{k:(period-v)%period for k,v in brake_starts.items()},
             'all_tc0_to_tc6_use_tc4_schedule':True,'implicit_guard_band':True,'initially_open':True,
             'clockModule':'^.^.^.^.clock','scheduleForAbsoluteTime':True}
        candidate_data[t['id']]={'variant':t,'gcl':gcl,'profile_bps':rates,'service_by_port':per_egress,
            'port_caps':cap_rows,'all_port_caps_pass':all(x['passes_75pct'] for x in cap_rows.values()),
            'z3_eth7_idleSlope_bps':rates[z3], 'z3_eth7_ratio_to_C3':rates[z3]/c3_profile[z3],
            'demand_sources':demands}
    out={'schema_version':'1.0','exploratory':True,'official_c4_frozen':False,
        'design_method':{'domain':'three fixed GCL tuples; T=100 us, TC4 open 90/85/82 us, TC7 open 20/25/30 us, with overlaps 10/10/12 us; fixed 12.4 us max-frame guard for 1542-byte TC4 frame plus 64 bits extra length','resolution':'1 us in gate-window tuple; phase values derived to 0.1 us from max-frame serialization or brake-frame serialization plus 100 ns propagation','objective':'maximize a predeclared 20% optimistic credit-service headroom over the greater of observed historical queue-bit offer and permanent catalog queue-bit rate, then preserve 20-30% brake TC7 windows; candidates are reported as plausible empirical tests, never analytically guaranteed','reserve_formula':'idleSlope = ceil(1.20 * max(historical queue-bit offer, permanent catalog queue-bit rate) / estimated eligible_fraction); eligible_fraction=(TC4_open - circular_overlap_with_full_TC7_window - max-frame guard - 1-us relative-phase allowance)/period','relative_phase_allowance':'1 us engineering envelope based on the sampled offset acceptance bound; not proof of continuous synchronization. Relative oscillator drift during a 100-us cycle is also recorded from configured ppm; corrections remain event-driven and are measured, not predicted from seed-specific drift.','conservative_limitation':'This is an optimistic credit-service sizing estimate. Competing traffic and actual credit/gate interactions mean no lower service guarantee is inferred. A positive candidate is plausible for empirical testing, never analytically guaranteed.',
          'phase_rule':'TC7 starts at 0 on HPC and one 84-byte brake-frame serialization plus 100 ns propagation (0.772 us) on CSW egresses. TC4 starts on HPC at TC7_open-overlap; on CSW eth1/2 it is shifted by 1542-byte frame serialization plus 100 ns; on CSW eth3 it is shifted by brake-frame serialization plus 100 ns. The same offsets are retained across seeds; no seed drift or future traffic is consulted.',
          'period_rule':'100 us in local clock units; measured drift/cadence phase sweep is treated as an empirical robustness factor, not compensated per seed.',
          'selection':'smallest total normalized CBS reservation increase above C3 among treatments passing all P1 application/stability gates and observed service/recovery requirements; ties D1, D2, D3.'},
        'fixed_inputs':{'P1_changed':False,'C0_C3_changed':False,'official_C4_campaign_started':False,'load':'L2','aggregation':'A1','seed':41,
          'warmup_s':1,'measurement_s':[1,31],'drain_s':.05,'calendar_sha256':{},'drifts':json.loads((HERE/'clock_drift_ppm_by_seed_node.json').read_text()),
          'C3_profile_id':'reduction_11','A005_profile_id':'A005 from corrected pilot','C3_profile_sha256':hashlib.sha256(json.dumps(c3_profile,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
          'A005_profile_sha256':a005['effective_profile_sha256'],'service_demand_file_sha256':sha(DEMAND_PATH),
          'flow_catalog_sha256':sha(FLOW_PATH),'nominal_reservation_catalog_sha256':sha(RES_PATH)},
        'controls':{'B_local_reuse':'corrected pilot B run, same seed/calendar/profile/runtime/metrics; compare SHA and signatures before reuse','C3_sync_reuse':'corrected pilot C3_sync control, same seed/calendar/profile/runtime/metrics; compare SHA and signatures before reuse'},
        'candidate_designs':candidate_data,
        'budget':{'initial_candidate_runs':6,'reused_controls':2,'conditional_seed_runs':6,'conditional_load_runs':6,'max_methodological_runs':20,'max_technical_replacements':2,'parallel_jobs':1,'free_disk_floor_GiB':40,'MemAvailable_floor_GiB':7},
        'acceptance':{'p1_application_gates':True,'p1_stability_proxy':True,'observed_sync_samples':True,'continuous_sync':'reported separately; not claimed','technical_gcl_credit_calendar_gate':True,'service_evidence':'must show backlog service while source remains active and/or a defensible lower bound; candidate upper bound alone is insufficient','F13_episode':'threshold > one 2048-bit queue frame above baseline; recovery <=5s, zero drops, source active; 5s is diagnostic not P1 gate','hard_deadline':'max latency <=100us for F08-F10; report numerical margin; no added minimum margin criterion','candidate_requires':'all gates plus service/recovery evidence; no partial pass'} }
    caldir=HERE/'results/calendars'
    for seed in [41,43,47]:
        p=caldir/f'seed{seed}_events.csv'
        with p.open(newline='') as f: rows=list(csv.DictReader(f))
        cols=('flow','block','signature','start','duration','volume_bytes')
        sig=hashlib.sha256(json.dumps([{k:r[k] for k in cols} for r in rows],separators=(',',':')).encode()).hexdigest()
        out['fixed_inputs']['calendar_sha256'][str(seed)]=sig
    (HERE/'results/dimensioning.json').write_text(json.dumps(out,indent=2,sort_keys=True)+'\n')
    print(json.dumps({k:{'all_caps':v['all_port_caps_pass'],'rates':{p:row['idleSlope_bps'] for p,row in v['service_by_port'].items()},'eligible':{p:round(row['eligible_fraction_estimate'],4) for p,row in v['service_by_port'].items()}} for k,v in candidate_data.items()},indent=2))
if __name__=='__main__':main()
