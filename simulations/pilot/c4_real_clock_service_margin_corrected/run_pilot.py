#!/usr/bin/env python3
"""Serial, checkpointed runner for the isolated C4 real-clock service-margin pilot."""
from __future__ import annotations
import argparse, csv, fcntl, gzip, hashlib, json, math, os, re, shutil, signal, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SIM = ROOT / "simulations"
OUT = HERE / "results"
INET = Path(os.environ.get("INET_ROOT", str(Path.home()/"omnetpp/samples/inet-4.7.0"))).resolve()
OMNET = Path(os.environ.get("OMNETPP_ROOT", str(Path.home()/"omnetpp"))).resolve()
P1 = ROOT / "docs/design/P1-v4.pdf"
PROFILE_C3 = SIM / "campaigns/p1-v2-official-2026-10/results/calibration/C3_calibration.json"
PROFILE_CHECKPOINT = SIM / "campaigns/p1-v2-official-2026-10/results/progress.json"
A005_RESULT = SIM / "pilot/c4_gate_clock_reference/results/runs/A005_local_L2_A1_seed41_v1/pilot-result.json"
AUDIT_DIR = SIM / "pilot/c4_real_clock_service_margin/results/audits/audit_2026-10-18"
DRIFTS = HERE / "clock_drift_ppm_by_seed_node.json"
CAL = OUT / "calendars/seed41_L2_A1_F21_F22.csv"
HIST_DEMAND = HERE / 'historical_A005_service_demand.json'
NOMINAL_RATES = SIM / 'zonal/traffic/cbs_nominal_reservations.csv'
LOCK = OUT / ".pilot.lock"
MIN_FREE_GIB = 40.0
MIN_MEM_GIB = 7.0
MAX_JOBS = 1
PILOT_INI = HERE / "pilot.ini"
PLUGIN = HERE / "plugin/libc4realclockprobe.so"

sys.path.insert(0, str(ROOT / "scripts/run"))
import validate_c0 as validator
sys.path.insert(0, str(SIM / "pilot/c4_shared_sp_brakes"))
import run_pilot as shared

VARIANTS = ["B_local", "R_cadence", "RP_cadence_phase", "BM_recovery", "RPM_combined", "C3_sync_control"]
GATED = {"B_local", "R_cadence", "RP_cadence_phase", "BM_recovery", "RPM_combined"}
PORTS = ["HPC.eth[0]", "CSW.eth[1]", "CSW.eth[2]", "CSW.eth[3]"]
NODES = ["HPC", "CSW", "Z1.ZSW", "Z2.ZSW", "Z3.ZSW"]
P_CLOCK = 99.995e-6
TC7_OPEN = 52e-6
OTHER_OPEN = P_CLOCK - TC7_OPEN
GUARD_MAX = 1542*8/1e9


def sha(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()

def gzip_verified(path: Path):
    """Compress one evidence file and remove the source only after byte verification."""
    target=Path(str(path)+'.gz'); tmp=Path(str(target)+'.tmp')
    source_hash=sha(path); source_bytes=path.stat().st_size
    with path.open('rb') as src,gzip.open(tmp,'wb',compresslevel=6) as dst:
        shutil.copyfileobj(src,dst,1024*1024)
    check=hashlib.sha256()
    with gzip.open(tmp,'rb') as src:
        for block in iter(lambda:src.read(1024*1024),b''): check.update(block)
    if check.hexdigest()!=source_hash:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f'Compressed evidence failed byte verification; original retained: {path}')
    tmp.replace(target)
    compressed_hash=sha(target)
    path.unlink()
    return {'source_name':path.name,'compressed_name':target.name,'uncompressed_sha256':source_hash,
            'compressed_sha256':compressed_hash,'uncompressed_bytes':source_bytes,'compressed_bytes':target.stat().st_size,
            'verified_by_streaming_decompression':True,'source_removed_after_verification':True}

def atomic(path: Path, data):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.tmp')
    with tmp.open('w') as f: json.dump(data,f,indent=2,sort_keys=True); f.write('\n'); f.flush(); os.fsync(f.fileno())
    tmp.replace(path)

def free_gib(): return shutil.disk_usage(ROOT).free/(1024**3)
def mem_gib():
    try:
        for line in open('/proc/meminfo'):
            if line.startswith('MemAvailable:'): return int(line.split()[1])/1024/1024
    except OSError: pass
    return 0

def official_active():
    lock=SIM/'campaigns/p1-v2-official-2026-10/results/.campaign.lock'
    fd=os.open(lock,os.O_CREAT|os.O_RDWR,0o644)
    try:
        try: fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: return True
        finally:
            try: fcntl.flock(fd,fcntl.LOCK_UN)
            except OSError: pass
    finally: os.close(fd)
    try:
        cp=json.loads((lock.parent/'checkpoint.json').read_text())
        return bool(cp.get('active_process') and cp.get('executor_pid') and Path(f"/proc/{cp['executor_pid']}").exists())
    except Exception: return False

def load_profiles():
    c3=json.loads(PROFILE_C3.read_text())
    cp=json.loads(PROFILE_CHECKPOINT.read_text())
    if c3.get('status')!='frozen_and_accepted' or c3.get('final_profile_id')!='reduction_11' or cp.get('calibration_final_profile_id')!='reduction_11' or cp.get('calibration_profile_accepted') is not True:
        raise RuntimeError('Official reduction_11 identity/checkpoint check failed')
    a005=json.loads(A005_RESULT.read_text())
    if a005.get('effective_profile_sha256') is None or a005.get('diagnostic_variant')!='A005_local': raise RuntimeError('A005 source run is not the audited A005_local L2/A1 run')
    return ({k:int(v) for k,v in a005['effective_profile_bps'].items()},
            {k:int(v) for k,v in c3['selected_profile_bps'].items()}, c3, a005)

def check_profile(profile):
    return hashlib.sha256(json.dumps(profile,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def physical_rate_bps(egress):
    # Port map in ZonalIVN.ned: LA-L is 100 Mb/s; the backbone, LA-H and
    # zonal uplinks are 1 Gb/s. Profiled low-speed endpoints are RADARs and
    # ZSW access ports eth[6..8].
    if egress.startswith('RADAR') or re.fullmatch(r'Z[123]\.ZSW\.eth\[(6|7|8)\]',egress):
        return 100_000_000
    return 1_000_000_000

def reservation_admissibility(profiles):
    out={}
    for variant,profile in profiles.items():
        totals={}
        for key,rate in profile.items():
            egress,_=key.rsplit('/TC',1); totals[egress]=totals.get(egress,0)+int(rate)
        rows={}
        for egress,total in sorted(totals.items()):
            capacity=physical_rate_bps(egress)
            rows[egress]={'idleSlope_sum_bps':total,'physical_rate_bps':capacity,
                'cap_fraction':total/capacity,'headroom_to_75pct_bps':round(.75*capacity)-total,
                'passes_75pct':total<=.75*capacity}
        out[variant]={'by_egress':rows,'all_egresses_pass_75pct':all(x['passes_75pct'] for x in rows.values())}
    return out

def cbs_gate_upper_bound(idle_slope_bps, period_s, open_s, min_packet_queue_bits=2048,
                         line_rate_bps=1_000_000_000):
    """Optimistic sustained wire-service bound under INET CreditBasedGate.

    Credits accrue only while the periodic gate is open, the class is not
    transmitting, and the periodic gate does not report guard band. During
    transmission and IFG the configured sendSlope spends credit. Ignoring
    guard band and all competing classes gives the absolute upper bound
    idleSlope * open_fraction. The packet-fit bound uses the smallest known
    queue packet as the most optimistic guard-band case; it is not a lower
    service guarantee.
    """
    # INET PeriodicGate checks (packet data length + extraLength) / bitrate;
    # extraLength=64 bits on CreditBasedGate. With the smallest known TC4
    # queue packet (256 B), this is an optimistic 264 B fit interval.
    fit_s = (min_packet_queue_bits + 64) / line_rate_bps
    eligible_s = max(0.0, open_s - fit_s)
    fractions = {'no_guard_absolute_upper': open_s / period_s,
                 'smallest_packet_fit_upper': eligible_s / period_s}
    return {
        'idleSlope_bps': idle_slope_bps,
        'period_s': period_s,
        'gate_open_s': open_s,
        'minimum_queue_packet_bits_assumed': min_packet_queue_bits,
        'credit_gate_extraLength_bits': 64,
        'smallest_packet_guard_time_s': fit_s,
        'eligible_credit_gain_time_s_best_case_s': eligible_s,
        'best_case_guarded_upper_service_bps': idle_slope_bps * fractions['smallest_packet_fit_upper'],
        'no_guard_absolute_upper_service_bps': idle_slope_bps * fractions['no_guard_absolute_upper'],
        'assumptions': ['no competing class ever consumes service',
                        'queue remains continuously backlogged',
                        'all queue packets have the smallest TC4 size',
                        'credit is fully usable and no limiting credit bounds apply'],
        'interpretation': 'upper bound only; neither bound is a service guarantee'
    }

def treatment_contracts():
    return json.loads((HERE/'treatment_contracts.json').read_text())

def f13_rule():
    return {
        'status_values': ['sufficient', 'insufficient', 'not_identifiable'],
        'natural_episode_definition': 'Start an episode when queue occupancy rises above the pre-episode baseline by more than one maximum F13 queue frame; end when it returns to or below baseline plus one maximum frame.',
        'baseline': 'Q immediately before the threshold crossing; if no earlier event exists in [1,31), use Q(1-).',
        'tolerance_bits': 2048,
        'active_offer_condition': 'F13 source remains in its catalog-active period through recovery; report inactive periods separately.',
        'recovery_horizon_s': 5.0,
        'horizon_rationale': 'One P1 queue-stability aggregation interval; diagnostic episode horizon only, not a new P1 gate.',
        'boundary': 'Semi-open measurement [1,31); episodes crossing t=31 are right-censored, with Q(31-) and in-service packets reported separately.',
        'drops': 'Any confirmed drop during an episode prevents classifying that episode as successful recovery.',
        'no_episode': 'natural backlog recovery is not identifiable; do not infer margin or insufficiency.',
        'throughput': 'report realized queue-bit arrivals and departures separately; equality with empty endpoints is conservation, not capacity evidence.',
        'historical_53_frame_recovery': 'not evaluated unless a natural run contains and recovers that backlog; no artificial backlog in this stage.'
    }

def service_admissibility(profiles,historical_demand=None,nominal_rates=None):
    result={}
    historical=(historical_demand or {}).get('queue_bit_rates_bps',{})
    wire_demand={f"{x['egress']}/TC{x['tc']}":x['permanent_wire_rate_bps'] for x in (nominal_rates or [])}
    for variant,profile in profiles.items():
        rows={}
        if variant in ('R_cadence','RP_cadence_phase','RPM_combined'):
            open_s=OTHER_OPEN
            period=P_CLOCK
        elif variant in ('B_local','BM_recovery'):
            open_s=77e-6
            period=100e-6
        else:
            open_s=None; period=None
        for key,rate in sorted(profile.items()):
            egress,tc=key.rsplit('/TC',1)
            if variant not in GATED or egress not in PORTS or tc!='4':
                continue
            bound=cbs_gate_upper_bound(int(rate),period,open_s,
                                       min_packet_queue_bits=256*8,
                                       line_rate_bps=physical_rate_bps(egress))
            demand=historical.get(key,{}).get('incomingPacketLengths:vector')
            nominal_wire=wire_demand.get(key)
            boundary_credit_bits=int(rate * (open_s/period) * 1.0)
            boundary_debt_bits=1542*8
            no_guard_finite_upper=(bound['no_guard_absolute_upper_service_bps'] +
                                   (boundary_credit_bits+boundary_debt_bits)/30.0)
            # Comparing an optimistic wire-service bound against a queue-bit
            # demand is conservative: each queue bit needs at least one wire bit.
            status='inconclusive'
            if demand is not None and no_guard_finite_upper < demand:
                status='inadmissible_upper_bound_below_queue_offer'
            rows[key]={**bound,'historical_queue_offer_bps':demand,
                       'catalog_permanent_wire_demand_bps':nominal_wire,
                       'demand_provenance':'historical A005 incomingPacketLengths vector on [1,31); queue bits. Link-rate demand is separate catalog permanent R_wire from L2 cbs_nominal_reservations.csv.',
                       'warmup_credit_bank_upper_bound_bits':boundary_credit_bits,
                       'measurement_final_frame_debt_upper_bound_bits':boundary_debt_bits,
                       'finite_measurement_no_guard_upper_service_bps':no_guard_finite_upper,
                       'triage_status':status,
            'proof_note':('Even the no-guard, no-competition upper service bound (including a bounded warm-up credit bank) is below the historical queue-bit offer.' if status.startswith('inadmissible') else 'Available upper bound does not prove insufficiency or sufficient service.')}
        result[variant]={'by_egress_tc':rows,
            'treatment_status':('inadmissible' if any(x['triage_status'].startswith('inadmissible') for x in rows.values()) else ('inconclusive' if rows else 'not_applicable'))}
    return result

def calendar_signature(path: Path):
    with path.open(newline='') as f: rows=list(csv.DictReader(f))
    cols=('flow','block','signature','start','duration','volume_bytes')
    payload=[{k:r[k] for k in cols} for r in rows]
    return hashlib.sha256(json.dumps(payload,separators=(',',':')).encode()).hexdigest(),rows

def source_hashes():
    paths=[P1, PROFILE_C3, PROFILE_CHECKPOINT, A005_RESULT, DRIFTS, CAL,
           HERE/'protocol.md',HERE/'protocol_addendum_2026-10-19_gate-runtime-check.md',HERE/'treatment_contracts.json',HERE/'derive_historical_demand.py',HERE/'reprocess_B.py',HIST_DEMAND,PILOT_INI,HERE/'run_pilot.py',
           HERE/'plugin/RealClockTraceProbe.cc',HERE/'plugin/ClockPrecisionProbe.cc',
           HERE/'plugin/Makefile',PLUGIN,HERE/'RealClockTraceProbe.ned',HERE/'ClockPrecisionProbe.ned',
           SIM/'omnetpp.ini',SIM/'zonal/traffic/flows.csv',SIM/'zonal/traffic/transients.csv',NOMINAL_RATES,SIM/'zonal/networks/ZonalIVN.ned',
           SIM/'zonal/configs/classification.ini',SIM/'zonal/configs/mechanisms/C0_strict_priority.ini',
           SIM/'zonal/configs/mechanisms/C2_nominal_cbs.ini',SIM/'zonal/configs/mechanisms/C2_nominal_rates.ini',
           SIM/'zonal/configs/mechanisms/C3_calibrated_cbs.ini',SIM/'zonal/configs/mechanisms/C3_calibrated_rates.ini',
           ROOT/'src/common/TrafficPlan.cc',ROOT/'src/common/TrafficPlan.ned',
           ROOT/'src/common/TrafficAudit.cc',ROOT/'src/common/ZonalEthernetLink.ned',
           ROOT/'scripts/run/validate_c0.py',ROOT/'src/zonal-ivn-tsn',INET/'src/libINET.so',
           OMNET/'lib/liboppcmdenv.so',OMNET/'lib/liboppenvir.so',OMNET/'lib/liboppsim.so',
           OMNET/'lib/liboppcommon.so',OMNET/'lib/liboppnedxml.so',AUDIT_DIR/'audit.md',AUDIT_DIR/'audit.json']
    return {str(p.relative_to(ROOT) if p.is_relative_to(ROOT) else p):sha(p) for p in paths if p.is_file()}

def make_plan():
    a005,c3,caldata,audit=load_profiles()
    calsha,calrows=calendar_signature(CAL)
    if calsha!='cb74a68801e037dce0480422e4371150c2c95765974b0ef3857f1633b54a600d': raise RuntimeError('Seed-41 transient calendar does not match audited signature')
    zb=next((v for k,v in a005.items() if k=='Z3.ZSW.eth[7]/TC4'),None)
    if zb!=27_600_000: raise RuntimeError(f'A005 Z3/eth7 TC4 expected 27.6 Mbps, found {zb}')
    drift=json.loads(DRIFTS.read_text())
    profiles={v:profile_for(v,{'A005_source':{'effective_profile_bps':a005},'official_profile':{'selected_L2_bps':c3}}) for v in VARIANTS}
    nominal_rates=[]
    with NOMINAL_RATES.open(newline='') as f:
        for row in csv.DictReader(f):
            if row['load']=='L2': nominal_rates.append({'egress':row['egress'],'tc':int(row['traffic_class']),
                'permanent_wire_rate_bps':int(row['idle_slope_bps']),'permanent_flows':row['permanent_flows']})
    historical_demand=json.loads(HIST_DEMAND.read_text())
    expected_cbs={variant:{key:{'type':treatment_contracts()['expected_cbs']['type'],'idleSlope_bps':int(value),
                                 'sendSlope_bps':int(value)-physical_rate_bps(key.rsplit('/TC',1)[0]),
                                 'bitrate_bps':physical_rate_bps(key.rsplit('/TC',1)[0]),
                                 'initialCredit':0,'transmitCreditLimit':0,'minCredit':-math.inf,'maxCredit':math.inf,
                                 'accumulateCreditInGuardBand':False,'maxInterferenceSize':'inf b','extraLength':'64 b','extraDuration':'0 s'}
                                for key,value in profile.items()} for variant,profile in profiles.items()}
    contracts=treatment_contracts()
    svc=service_admissibility(profiles,historical_demand,nominal_rates)
    # R/RP/RPM are screened using the installed CBS credit equation.  The
    # no-guard upper bound is intentionally optimistic; falling below the
    # queue-bit offer is sufficient to reject, while exceeding it is only
    # inconclusive.
    run_variants=['B_local','C3_sync_control','BM_recovery']
    rejected={v:{'status':'inadmissible_before_execution','reason':svc[v]['by_egress_tc']['HPC.eth[0]/TC4']['proof_note']}
              for v in ('R_cadence','RP_cadence_phase','RPM_combined')}
    return {'pilot_id':'c4-real-clock-service-margin-corrected','exploratory':True,'official_c4_frozen':False,'created_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
      'git_commit':subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,text=True,capture_output=True).stdout.strip(),
      'working_tree_status_at_plan':subprocess.run(['git','status','--short'],cwd=ROOT,text=True,capture_output=True).stdout,
      'omnetpp_version':(OMNET/'Version').read_text().strip(),'inet_version':(INET/'Version').read_text().strip(),
      'executables_and_runtime_libraries':{str(p):sha(p) for p in [ROOT/'src/zonal-ivn-tsn',PLUGIN,INET/'src/libINET.so',OMNET/'lib/liboppcmdenv.so',OMNET/'lib/liboppenvir.so',OMNET/'lib/liboppsim.so',OMNET/'lib/liboppcommon.so',OMNET/'lib/liboppnedxml.so'] if p.is_file()},
      'inet_source_sha256':{str(p.relative_to(INET)):sha(p) for p in [INET/'src/inet/queueing/gate/PeriodicGate.cc',INET/'src/inet/queueing/gate/PeriodicGate.ned',INET/'src/inet/queueing/gate/CreditBasedGate.cc',INET/'src/inet/queueing/gate/CreditBasedGate.ned',INET/'src/inet/linklayer/ieee8021q/Ieee8021qCreditBasedShaper.ned',INET/'src/inet/linklayer/ieee8021q/Ieee8021qCreditBasedGate.ned',INET/'src/inet/clock/model/SettableClock.cc',INET/'src/inet/clock/model/SettableClock.ned',INET/'src/inet/clock/model/OscillatorBasedClock.cc',INET/'src/inet/clock/servo/StepClockServo.cc',INET/'src/inet/clock/oscillator/ConstantDriftOscillator.h']},
      'p1':{'path':str(P1.relative_to(ROOT)),'sha256':sha(P1)},'official_profile':{'id':'reduction_11','sha256':sha(PROFILE_C3),'checkpoint_sha256':sha(PROFILE_CHECKPOINT),'selected_L2_bps':c3,'status':caldata.get('status')},
      'A005_source':{'execution_id':audit.get('execution_id'),'profile_sha256':audit.get('effective_profile_sha256'),'effective_profile_bps':a005},
      'historical_queue_demand':historical_demand,
      'catalog_permanent_wire_demand_L2':nominal_rates,
      'calendar':{'path':str(CAL.relative_to(ROOT)),'sha256_file':sha(CAL),'signature':calsha,'event_count':len(calrows)},
      'drifts_by_seed_node':drift,'parameters':{'load':'L2','aggregation':'A1','seed':41,'warmup_s':1,'measurement_s':30,'drain_s':.05,'max_parallel_jobs':1,'minimum_free_GiB':MIN_FREE_GIB,'minimum_MemAvailable_GiB':MIN_MEM_GIB},
      'treatment_contracts_sha256':sha(HERE/'treatment_contracts.json'),
      'cadence_rule':contracts['treatments'],
      'phase_rule':{'one_way_wire_time_s':84*8/1e9,'link_delay_s':100e-9,'offset_s':1e-6,'nominal_margin_s':1e-6-(84*8/1e9+100e-9),'clock_relative_sample_gate':'<=1us samples only; continuous compliance unverified'},
      'F13_recovery':{'egress_tc':'Z3.ZSW.eth[7]/TC4','physical_rate_bps':physical_rate_bps('Z3.ZSW.eth[7]'),
          'A005_idleSlope_bps':zb,'A005_reservation_fraction':zb/physical_rate_bps('Z3.ZSW.eth[7]'),
          'catalog_permanent_wire_demand_bps':next((x['permanent_wire_rate_bps'] for x in nominal_rates if x['egress']=='Z3.ZSW.eth[7]' and x['tc']==4),None),
          'historical_queue_offer_bps':historical_demand['queue_bit_rates_bps'].get('Z3.ZSW.eth[7]/TC4',{}).get('incomingPacketLengths:vector'),
          'historical_queue_departure_bps':historical_demand['queue_bit_rates_bps'].get('Z3.ZSW.eth[7]/TC4',{}).get('outgoingPacketLengths:vector'),
          'candidate_idleSlope_bps':28152000,'added_nominal_bps':552000,
          'candidate_reservation_fraction':28152000/physical_rate_bps('Z3.ZSW.eth[7]'),
          'evidence_status_pre_run':'not_identifiable_for natural backlog recovery until an episode exceeding one frame is observed',
          'rule':f13_rule()},
      'reservation_admissibility_all_profile_egresses':reservation_admissibility(profiles),
      'cbs_service_admissibility':svc,
      'expected_cbs_by_treatment':expected_cbs,
      'expected_no_cbs_modules':treatment_contracts()['expected_no_cbs'],
      'pre_execution_decisions':{'run':run_variants,'reject':rejected,'B_is_control_required_even_if_application_or_stability_gates_fail':True},
      'variants':VARIANTS,'schedule_initial':[{'variant':v,'cell':'L2_A1','seed':41,'execution_id':f'{v}_L2_A1_seed41'} for v in run_variants],
      'not_authorized_in_this_stage':['seeds 43/47','L0/A0','L1/A1','artificial backlog','C4 final campaign'],
      'selection':{'only_if_an_executed_treatment_passes_all_P1_application_and_stability_gates_and_has sufficient F13 evidence':'select as a prospective verification candidate only; this stage does not authorize follow-up cells','F13_evidence':f13_rule(),'no_candidate_if_service_evidence_not_identifiable':True},
      'budget':{'max_complete_methodological_executions_seed41':6,'planned_after_triage':len(run_variants),'max_technical_replacements_per_proven_failure':1,'other_seeds_or_cells_authorized':False},'source_hashes':source_hashes()}

def profile_for(variant, plan):
    a=plan['A005_source']['effective_profile_bps']
    if variant=='C3_sync_control': return {k:int(v) for k,v in plan['official_profile']['selected_L2_bps'].items()}
    p={k:int(v) for k,v in a.items()}
    if variant in ('BM_recovery','RPM_combined'): p['Z3.ZSW.eth[7]/TC4']=round(p['Z3.ZSW.eth[7]/TC4']*1.02)
    return p

def gate_overrides(variant):
    if variant=='C3_sync_control': return []
    out=['--*.HPC.hasEgressTrafficShaping=true','--*.CSW.hasEgressTrafficShaping=true','--*.Z*.ZSW.hasEgressTrafficShaping=true']
    for port in PORTS:
        root=f'*.{port}.macLayer.queue.transmissionGate'
        out += [f'--{root}[*].clockModule="^.^.^.^.clock"','--'+root+'[*].initiallyOpen=true','--'+root+'[*].enableImplicitGuardBand=true']
        if variant in ('B_local','BM_recovery'):
            out += [f'--{root}[0..6].durations=[77us,23us]',f'--{root}[0..6].offset=90us',f'--{root}[7].durations=[10us,90us]',f'--{root}[7].offset=0s']
        else:
            out += [f'--{root}[0..6].durations=[47.995us,52us]',f'--{root}[0..6].offset=89.9955us',f'--{root}[7].durations=[52us,47.995us]']
            offset=('98.995us' if variant in ('RP_cadence_phase','RPM_combined') and port.startswith('CSW.') else '0s')
            out += [f'--{root}[7].offset={offset}']
    return out

def sim_args(variant, run_dir, seed, profile, calendar_path, plan):
    config='Pilot_C3sync_L2_A1' if variant=='C3_sync_control' else 'Pilot_C4compensated_L2_A1'
    trace_dir=run_dir/f'{config}-0'
    trace_dir.mkdir(parents=True,exist_ok=True)
    args=['-u','Cmdenv','-n',f'.:{ROOT/"src"}:{ROOT/"tests"}:{INET/"src"}',
          '-f','omnetpp.ini','-f',str(PILOT_INI.relative_to(SIM)),'-c',config,
          '-l',str(PLUGIN),'--cmdenv-express-mode=true','--cmdenv-event-banners=false',
          f'--seed-set={seed}',f'--result-dir={run_dir.relative_to(SIM)}',
          '--network=zonal_ivn_tsn.simulations.pilot.c4_real_clock_service_margin_corrected.ZonalIVN',
          '--**.app[*].latency.result-recording-modes=+vector','--**.app[*].imageCompletionLatency.result-recording-modes=+vector',
          '--**.queueLength.result-recording-modes=+vector','--**.queueBitLength.result-recording-modes=+vector',
          '--**.droppedPacketLengthsQueueOverflow.result-recording-modes=+vector','--**.transmissionGate[*].gateState.result-recording-modes=vector',
          '--**.transmissionGate[*].guardBandState.result-recording-modes=vector','--**.numCredits.result-recording-modes=vector,max,min,timeavg',
          '--**.clock.emitClockTimeInterval=1ms','--**.clock.timeChanged.result-recording-modes=vector',
          '--**.gptp.gmRateRatio.result-recording-modes=+vector','--**.gptp.neighborRateRatio.result-recording-modes=+vector',
          '--**.transmitter.typename="StreamingTransmitter"','--**.receiver.typename="DestreamingReceiver"',
          '--*.trafficPlan.transientCalendarFile="'+str(calendar_path.resolve())+'"',
          '--*.realClockTrace.outputFile="'+str((trace_dir/'packet_events.csv').resolve())+'"',
          '--*.clockPrecision.outputFile="'+str((trace_dir/'clock_precision.csv').resolve())+'"',
          '--*.clockPrecision.sampleInterval=1ms','--*.clockPrecision.stopAt=31.05s',
          '--*.HPC.hasTimeSynchronization=true','--*.CSW.hasTimeSynchronization=true','--*.Z*.ZSW.hasTimeSynchronization=true']
    drift=plan['drifts_by_seed_node'][str(seed)]
    for node,value in drift.items(): args.append(f'--*.{node}.clock.oscillator.driftRate={value}ppm')
    args+=gate_overrides(variant)
    for key,value in sorted(profile.items()):
        egress,tc=key.rsplit('/TC',1)
        args.append(f'--*.{egress}.macLayer.queue.transmissionSelectionAlgorithm[{tc}].typename="Ieee8021qCreditBasedShaper"')
        args.append(f'--*.{egress}.macLayer.queue.transmissionSelectionAlgorithm[{tc}].idleSlope={value}bps')
    return config,args

def parse_calendar_from_run(run_dir):
    sig,rows=calendar_signature(run_dir/'events.csv')
    return sig,rows

def instrumentation_check(run_dir, expected_calendar):
    trace=run_dir/'packet_events.csv'; clock=run_dir/'clock_precision.csv'; events=run_dir/'events.csv'
    required=[trace,clock,events]
    if not all(p.is_file() and p.stat().st_size>0 for p in required): return False,{'reason':'missing_or_empty_instrumentation_file'}
    cal,rows=parse_calendar_from_run(run_dir)
    kinds={}; packet_id_present=False; invalid=[]
    with trace.open(newline='') as f:
        for r in csv.DictReader(f):
            kinds[r['kind']]=kinds.get(r['kind'],0)+1
            if r['packet_id']: packet_id_present=True
            if r['kind'] in ('queue_push_start','queue_pulled_out','phy_tx_start','phy_tx_end') and not r['packet_id']: invalid.append(r)
    has_packet=all(kinds.get(k,0)>0 for k in ('queue_push_start','queue_pulled_out','phy_tx_start','phy_tx_end'))
    result={'event_count':sum(kinds.values()),'event_kinds':kinds,'unique_selected_packet_ids':None,'packet_id_present':packet_id_present,'packet_id_count_method':'not_counted_to_keep_validation_memory_bounded','calendar_sha256':cal,'calendar_event_count':len(rows),'calendar_matches':cal==expected_calendar,'has_all_packet_boundaries':has_packet,'clock_csv_bytes':clock.stat().st_size,'trace_csv_bytes':trace.stat().st_size}
    return bool(result['calendar_matches'] and has_packet and packet_id_present),result

def verify_queue_trace_against_report(run_dir, report):
    """Recompute queue metrics from the retained compact change-point trace."""
    trace=run_dir/'queue_occupancy_events.csv.gz'
    meta=Path(str(trace)+'.meta.json.gz')
    if not trace.is_file() or not meta.is_file():
        return False,{'status':'unavailable','reason':'queue_occupancy_trace_or_metadata_missing'}
    recomputed=validator.recompute_queue_occupancy_trace(trace)
    recorded={x['queue']:x for x in report.get('queue_stability',[])}
    if len(recomputed)!=len(recorded):
        return False,{'status':'fail','reason':'queue_population_mismatch','recomputed':len(recomputed),'recorded':len(recorded)}
    fields=('mean_occupancy_bits_5s','mean_occupancy_bits_measurement',
            'fraction_measurement_at_least_90pct_capacity','max_occupancy_bits',
            'capacity_bits','sustained_growth')
    mismatches=[]
    for row in recomputed:
        ref=recorded.get(row['queue'])
        if ref is None:
            mismatches.append({'queue':row['queue'],'reason':'queue_missing_from_report'}); continue
        for field in fields:
            a,b=row[field],ref.get(field)
            if isinstance(a,list):
                equal=(isinstance(b,list) and len(a)==len(b) and
                       all(math.isclose(float(x),float(y),rel_tol=1e-10,abs_tol=1e-8) for x,y in zip(a,b)))
            elif isinstance(a,float):
                equal=(b is not None and math.isclose(a,float(b),rel_tol=1e-10,abs_tol=1e-8))
            else: equal=a==b
            if not equal:
                mismatches.append({'queue':row['queue'],'field':field,'trace_value':a,'reported_value':b})
    target_modules={
        'ZonalIVN.HPC.eth[0].macLayer.queue.queue[4]',
        'ZonalIVN.CSW.eth[1].macLayer.queue.queue[4]',
        'ZonalIVN.CSW.eth[2].macLayer.queue.queue[4]',
        'ZonalIVN.CSW.eth[3].macLayer.queue.queue[4]',
        'ZonalIVN.Z3.ZSW.eth[7].macLayer.queue.queue[4]'}
    targets=[x for x in recomputed if x['queue'] in target_modules]
    return not mismatches,{'status':'pass' if not mismatches else 'fail',
        'trace_sha256':sha(trace),'metadata_sha256':sha(meta),
        'queue_count':len(recomputed),'method':'independent streaming recomputation from retained right-continuous queue occupancy change points',
        'mismatches':mismatches,'recomputed_targets':targets}

def historical_b_comparison(current_trace, current_report, current_audit=None):
    """Compare corrected B with the old valid A005 CBS control before unblocking later runs."""
    old_report_path=A005_RESULT
    old=json.loads(old_report_path.read_text())
    old_run=SIM/'pilot/c4_gate_clock_reference/results/runs/A005_local_L2_A1_seed41_v1/Pilot_C4compensated_L2_A1-0'
    old_trace=old_run/'queue_occupancy_events.csv.gz'
    if not old_trace.is_file():
        return {'status':'inconclusive','reason':'historical_queue_occupancy_trace_missing',
                'old_report':str(old_report_path.relative_to(ROOT))}
    old_ok,old_audit=verify_queue_trace_against_report(old_run,old)
    new_ok,new_audit=(current_audit[0],current_audit[1]) if current_audit is not None else verify_queue_trace_against_report(current_trace.parent,current_report)
    old_by={x['queue']:x for x in old_audit.get('recomputed_targets',[])}
    new_by={x['queue']:x for x in new_audit.get('recomputed_targets',[])}
    targets={
        'HPC.eth[0]/TC4':'ZonalIVN.HPC.eth[0].macLayer.queue.queue[4]',
        'CSW.eth[1]/TC4':'ZonalIVN.CSW.eth[1].macLayer.queue.queue[4]',
        'CSW.eth[2]/TC4':'ZonalIVN.CSW.eth[2].macLayer.queue.queue[4]',
        'CSW.eth[3]/TC4':'ZonalIVN.CSW.eth[3].macLayer.queue.queue[4]',
        'Z3.ZSW.eth[7]/TC4':'ZonalIVN.Z3.ZSW.eth[7].macLayer.queue.queue[4]'}
    comparison={}
    material=[]
    for label,module in targets.items():
        a,b=old_by.get(module),new_by.get(module)
        if a is None or b is None:
            material.append(label); comparison[label]={'status':'missing_queue'}; continue
        old_bins=a['mean_occupancy_bits_5s']; new_bins=b['mean_occupancy_bits_5s']
        old_slope=(old_bins[-1]-old_bins[0])/25.0
        new_slope=(new_bins[-1]-new_bins[0])/25.0
        capacity=max(int(a['capacity_bits']),int(b['capacity_bits']))
        if label=='HPC.eth[0]/TC4':
            # Preregistered engineering tolerance: the historical trajectory is
            # reproduced when positive growth remains within 25% of its old
            # six-bin slope. This is a technical comparison gate, not a P1 gate.
            reference=old_slope
            reproduced=(reference>0 and new_slope>0 and abs(new_slope-reference)<=0.25*abs(reference))
            if not reproduced: material.append(label)
        else:
            # A quarter queue-capacity displacement in a 5 s-bin profile is
            # treated as material; small event-order/build drift is reported.
            deviation=max(abs(float(x)-float(y)) for x,y in zip(old_bins,new_bins))
            reproduced=deviation<=0.25*capacity
            if not reproduced: material.append(label)
        comparison[label]={'historical_bins_bits':old_bins,'corrected_B_bins_bits':new_bins,
            'historical_slope_bits_per_s':old_slope,'corrected_B_slope_bits_per_s':new_slope,
            'max_bin_mean_difference_bits':max(abs(float(x)-float(y)) for x,y in zip(old_bins,new_bins)),
            'capacity_bits':capacity,'material_divergence_threshold_bits':(0.25*abs(old_slope)*25 if label=='HPC.eth[0]/TC4' else 0.25*capacity),
            'reproduces_historical_behavior':reproduced}
    reliable=old_ok and new_ok and not material
    return {'status':'comparable' if reliable else 'material_divergence_or_accounting_failure',
        'old_executable_hash':'unavailable in historical manifest; comparison is behavior-level only',
        'historical_execution_id':old.get('execution_id'),'old_trace_sha256':sha(old_trace),
        'old_trace_recalculation':old_audit,'corrected_B_trace_recalculation':new_audit,
        'comparison_tolerance_registered_before_execution':{'HPC.eth[0]/TC4':'positive 5-second-bin mean slope within 25% of historical slope',
            'other_target_queues':'maximum absolute difference of 5-second-bin means <= 25% of queue capacity'},
        'by_queue':comparison,'material_or_unverifiable_queues':material,
        'note':'Historical executable hash is missing; this checks consistency of preserved evidence and reproduction of coarse queue behavior, not binary equivalence.'}

def read_sca_params(path):
    params={}
    opener=gzip.open if str(path).endswith('.gz') else open
    with opener(path,'rt',errors='replace') as f:
        for line in f:
            if not line.startswith('par ZonalIVN.'): continue
            p=line.rstrip().split(' ',3)
            if len(p)==4: params[(p[1],p[2])]=p[3]
    return params

def gcl_check(sca,variant):
    if variant=='C3_sync_control': return {'status':'not_applicable'}
    contracts=treatment_contracts()['treatments']
    contract=contracts[variant]['gates']
    if isinstance(contract,str):
        contract=contracts[contract.split(':',1)[1]]['gates']
    params=read_sca_params(sca); bad=[]; actual={}
    def decoded(raw):
        if raw is None: return None
        value=raw.strip()
        # SCA strings are quoted and escaped (e.g. "\"[77us, 23us]\"").
        for _ in range(2):
            try:
                parsed=json.loads(value)
                if not isinstance(parsed,str): break
                value=parsed
            except (json.JSONDecodeError, TypeError):
                break
        return value.strip()
    def seconds(token):
        m=re.fullmatch(r'\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)\s*(s|ms|us|ns|ps)?\s*',token)
        if not m: return None
        scale={'s':1.0,'ms':1e-3,'us':1e-6,'ns':1e-9,'ps':1e-12,None:1.0}[m.group(2)]
        return float(m.group(1))*scale
    def duration_list(raw):
        value=decoded(raw)
        if value is None or not (value.startswith('[') and value.endswith(']')): return None
        tokens=[x.strip() for x in value[1:-1].split(',') if x.strip()]
        parsed=[seconds(x) for x in tokens]
        return parsed if all(x is not None for x in parsed) else None
    for port in PORTS:
        for tc in range(8):
            m=f'ZonalIVN.{port}.macLayer.queue.transmissionGate[{tc}]'
            d=params.get((m,'durations')); off=params.get((m,'offset'))
            period=float(contract['period_s'])
            expected=([float(contract['class4_open_s']),period-float(contract['class4_open_s'])]
                      if tc<7 else [float(contract['class7_open_s']),period-float(contract['class7_open_s'])])
            if tc<7: expected_off=float(contract['class4_offset_s'])
            else: expected_off=float(contract.get('class7_offset_s_by_egress',{}).get(port,contract.get('class7_offset_s',0.0)))
            actual[m]={'durations':decoded(d),'offset':decoded(off),'clockModule':decoded(params.get((m,'clockModule'))),'initiallyOpen':decoded(params.get((m,'initiallyOpen'))),'scheduleForAbsoluteTime':decoded(params.get((m,'scheduleForAbsoluteTime'))),'enableImplicitGuardBand':decoded(params.get((m,'enableImplicitGuardBand')))}
            got=duration_list(d); offset_s=seconds(decoded(off) or '')
            if got is None or len(got)!=2 or any(abs(x-y)>1e-12 for x,y in zip(got,expected)) or offset_s is None or abs(offset_s-expected_off)>1e-12 or actual[m]['clockModule']!=contract['clockModule'] or actual[m]['initiallyOpen']!=str(contract['initiallyOpen']).lower() or actual[m]['scheduleForAbsoluteTime']!=str(contract['scheduleForAbsoluteTime']).lower() or actual[m]['enableImplicitGuardBand']!=str(contract['implicit_guard_band']).lower(): bad.append(m)
    return {'status':'pass' if not bad else 'fail','expected_gate_count':32,'observed_gate_count':len(actual),'mismatches':bad,'expected_contract':contract,'gates':actual}

def no_tas_check(sca,trace_path):
    params=read_sca_params(sca); scheduled=[]
    for (module,name),raw in params.items():
        if 'transmissionGate[' not in module or name!='durations': continue
        value=raw.strip()
        if value not in ('"[]"','[]','""',''):
            # Any non-empty periodic schedule means this control is not plain
            # CBS+SP, even if it happens to remain open in the measured window.
            scheduled.append({'module':module,'durations':raw})
    gate_events=0
    if trace_path.is_file():
        with trace_path.open(errors='replace') as f:
            for line in f:
                if ',gate_state,' in line and '.transmissionGate[' in line:
                    gate_events+=1
    return {'status':'pass' if not scheduled and gate_events==0 else 'fail',
            'nonempty_periodic_schedules':scheduled,'observed_periodic_gate_transitions':gate_events,
            'method':'SCA check for empty/missing durations plus packet-event trace check for no periodic gate transitions'}

def profile_sca_check(sca,profile):
    # Require the effective typename request and the instantiated INET module,
    # not merely an idleSlope override for an optional submodule.
    resolved={}; module_pars={}; num_credit_modules=set()
    opener=gzip.open if str(sca).endswith('.gz') else open
    with opener(sca,'rt',errors='replace') as f:
        for line in f:
            p=line.rstrip().split(' ',3)
            if len(p)<3: continue
            if p[0]=='config' and len(p)>=3:
                resolved[p[1]]=p[2] if len(p)==3 else p[2]+' '+p[3]
            elif p[0]=='par' and len(p)==4:
                module_pars[(p[1],p[2])]=p[3]
            elif p[0] in ('scalar','statistic') and len(p)>=3 and 'numCredits' in p[2]:
                num_credit_modules.add(p[1])
    mismatches={}; expected_modules=set(); credit_state={}; contract=treatment_contracts()['expected_cbs']
    def string_value(raw):
        if raw is None: return None
        value=raw.strip()
        for _ in range(2):
            try:
                parsed=json.loads(value)
                if isinstance(parsed,str): value=parsed
                else: break
            except (json.JSONDecodeError,TypeError): break
        return value.strip()
    def numeric(raw):
        value=string_value(raw)
        if value is None: return None
        low=value.lower().strip()
        if low in ('inf','+inf','infinity','+infinity','inf b','+inf b','infinity b'): return math.inf
        if low in ('-inf','-infinity','-inf b','-infinity b'): return -math.inf
        m=re.search(r'[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?',value)
        return float(m.group()) if m else None
    for key,v in profile.items():
        e,tc=key.rsplit('/TC',1)
        wildcard=f'*.{e}.macLayer.queue.transmissionSelectionAlgorithm[{tc}]'
        module=f'ZonalIVN.{e}.macLayer.queue.transmissionSelectionAlgorithm[{tc}]'
        expected_modules.add(module)
        typename=contract['type']
        type_cfg=resolved.get(wildcard+'.typename')
        idle_cfg=resolved.get(wildcard+'.idleSlope')
        type_par=module_pars.get((module,'typename'))
        idle_par=module_pars.get((module,'idleSlope'))
        send_par=module_pars.get((module,'sendSlope'))
        required=('initialCredit','minCredit','maxCredit','transmitCreditLimit','accumulateCreditInGuardBand',
                  'maxInterferenceSize','extraLength','extraDuration','bitrate','idleCreditGainRate','transmitCreditSpendRate')
        absent=[name for name in required if (module,name) not in module_pars]
        errors=[]
        if type_cfg is None or 'Ieee8021qCreditBasedShaper' not in string_value(type_cfg): errors.append('missing_or_wrong_typename_config')
        if type_par is None or typename not in string_value(type_par): errors.append('CBS_module_not_instantiated')
        if numeric(idle_cfg) is None or abs(numeric(idle_cfg)-v)>0.5: errors.append('idleSlope_config_mismatch')
        if numeric(idle_par) is None or abs(numeric(idle_par)-v)>0.5: errors.append('effective_idleSlope_mismatch')
        send_expected=int(v)-physical_rate_bps(e)
        rate_par=module_pars.get((module,'bitrate'))
        if numeric(send_par) is None or abs(numeric(send_par)-send_expected)>0.5: errors.append('effective_sendSlope_mismatch')
        if absent: errors.append('missing_credit_parameters:'+','.join(absent))
        expected_numeric={'initialCredit':0.0,'transmitCreditLimit':0.0,'minCredit':-math.inf,'maxCredit':math.inf,
                          'maxInterferenceSize':math.inf,'extraLength':64.0,'extraDuration':0.0,
                          'bitrate':float(physical_rate_bps(e)),'idleCreditGainRate':float(v),
                          'transmitCreditSpendRate':float(physical_rate_bps(e)-int(v))}
        for name,expected_value in expected_numeric.items():
            actual=numeric(module_pars.get((module,name)))
            if actual is None or (math.isfinite(expected_value) and abs(actual-expected_value)>0.5) or (not math.isfinite(expected_value) and actual!=expected_value):
                errors.append('credit_parameter_mismatch:'+name)
        if string_value(module_pars.get((module,'accumulateCreditInGuardBand')))!='false': errors.append('guard_band_credit_policy_mismatch')
        if module not in num_credit_modules: errors.append('numCredits_result_missing')
        credit_state[module]={name:module_pars.get((module,name)) for name in required}
        if errors:
            mismatches[key]={'expected_idleSlope_bps':v,'expected_type':typename,
                'actual':{'typename_config':type_cfg,'module_typename':type_par,'idleSlope_config':idle_cfg,
                          'idleSlope_parameter':idle_par,'sendSlope_parameter':send_par,
                          'numCredits_recorded':module in num_credit_modules,'missing_credit_parameters':absent},
                'errors':errors}
    actual_modules={module for (module,name),value in module_pars.items()
        if name=='typename' and 'Ieee8021qCreditBasedShaper' in string_value(value)}
    unexpected=sorted(actual_modules-expected_modules)
    if unexpected: mismatches['unexpected_CBS_modules']={'actual':unexpected,'errors':['CBS_module_not_in_profile']}
    forbidden=[]
    for key in treatment_contracts().get('expected_no_cbs',[]):
        e,tc=key.rsplit('/TC',1); forbidden.append(f'ZonalIVN.{e}.macLayer.queue.transmissionSelectionAlgorithm[{tc}]')
    wrongly_instantiated=sorted(actual_modules.intersection(forbidden))
    if wrongly_instantiated: mismatches['CBS_on_zero_permanent_reservation_egress']={'actual':wrongly_instantiated,'errors':['CBS_must_not_be_instantiated']}
    return {'pass':not mismatches,'expected_cbs_modules':len(profile),'observed_cbs_modules':len(actual_modules),
        'validated_cbs_modules':len(profile)-sum(1 for k in mismatches if k!='unexpected_CBS_modules'),
        'expected_no_cbs_modules':forbidden,'credit_state_by_module':credit_state,'unexpected_CBS_modules':unexpected,'mismatches':mismatches}

def credit_vector_check(run_dir,profile):
    path=run_dir/'pilot_other_vectors.csv.gz'
    if not path.is_file(): return {'status':'fail','reason':'credit_vector_file_missing','modules':{}}
    counts={f'ZonalIVN.{k.rsplit("/TC",1)[0]}.macLayer.queue.transmissionSelectionAlgorithm[{k.rsplit("TC",1)[1]}]':0 for k in profile}
    with gzip.open(path,'rt',newline='',encoding='utf-8') as stream:
        for row in csv.DictReader(stream):
            name=row.get('vector','')
            if 'numCredits:vector' not in name: continue
            m=re.match(r'^(ZonalIVN\..*\.macLayer\.queue\.transmissionSelectionAlgorithm\[\d+\])\.numCredits:vector',name)
            if m and m.group(1) in counts: counts[m.group(1)]+=1
    missing=[module for module,count in counts.items() if count==0]
    return {'status':'pass' if not missing else 'fail','modules':counts,
            'missing_credit_vectors':missing,'sample_source':'streamed .vec samples to pilot_other_vectors.csv.gz in original ticks/credit units'}

def gate_runtime_check(run_dir,variant):
    if variant=='C3_sync_control': return {'status':'not_applicable'}
    contract=treatment_contracts()['treatments'][variant]['gates']
    if isinstance(contract,str): contract=treatment_contracts()['treatments'][contract.split(':',1)[1]]['gates']
    trace=run_dir/'packet_events.csv'; clock=run_dir/'clock_precision.csv'
    if not trace.is_file() or not clock.is_file(): return {'status':'fail','reason':'gate_or_clock_trace_missing'}
    exp=None
    with clock.open(newline='') as f:
        reader=csv.DictReader(f)
        first=next(reader,None)
        if first: exp=int(first['simtime_scale_exp'])
    if exp is None: return {'status':'fail','reason':'clock_time_scale_missing'}
    tick_s=10.0**exp
    specs={}
    period=float(contract['period_s'])
    for port in PORTS:
        for tc in range(8):
            durations=([float(contract['class4_open_s']),period-float(contract['class4_open_s'])]
                       if tc<7 else [float(contract['class7_open_s']),period-float(contract['class7_open_s'])])
            off=float(contract.get('class7_offset_s_by_egress',{}).get(port,contract.get('class7_offset_s',0.0))) if tc==7 else float(contract['class4_offset_s'])
            off=off%period; phase=off; idx=0; state=bool(contract['initiallyOpen'])
            while phase>0:
                duration=durations[idx]
                if phase>=duration:
                    state=not state; phase-=duration; idx=(idx+1)%2
                else: break
            first_delay=durations[idx]-phase
            expected_state=not state
            module=f'ZonalIVN.{port}.macLayer.queue.transmissionGate[{tc}]'
            period_raw=round(period/tick_s)
            offset_raw=round(off/tick_s)
            phase_open=(-offset_raw)%period_raw
            phase_closed=(phase_open+round(durations[0]/tick_s))%period_raw
            specs[module]={'durations_raw':[round(x/tick_s) for x in durations],
                           'period_raw':period_raw,'phase_open_raw':phase_open,'phase_closed_raw':phase_closed,
                           'first_delay_raw':round(first_delay/tick_s),
                           'first_state':int(expected_state),'initial_state':bool(contract['initiallyOpen'])}
    observed={m:{'count':0,'first':None,'last':None,'bad_values':0,'max_duration_error_ticks':0,'duration_samples':0,'min_interval_ticks':None,'max_interval_ticks':None,'max_phase_error_ticks':0,'phase_error_samples':0} for m in specs}
    with trace.open(newline='',encoding='utf-8') as stream:
        for row in csv.DictReader(stream):
            if row.get('kind')!='gate_state': continue
            module=row.get('source','')
            if module not in specs: continue
            m=observed[module]; m['count']+=1
            parsed=dict(part.split('=',1) for part in row.get('value','').split(';') if '=' in part)
            if 'local_clock_raw' not in parsed or 'state' not in parsed:
                m['bad_values']+=1; continue
            current=(int(row['event']),int(row['order']),int(row['simtime_raw']),int(parsed['local_clock_raw']),int(parsed['state']))
            prior=m['last']
            if m['first'] is None: m['first']=current
            if prior is not None:
                if (current[0],current[1])<=(prior[0],prior[1]) or current[4]==prior[4]: m['bad_values']+=1
                d=current[3]-prior[3]
                if d<0: m['bad_values']+=1
                else:
                    expected=specs[module]['durations_raw'][0 if prior[4]==1 else 1]
                    err=abs(d-expected)
                    m['duration_samples']+=1
                    m['max_duration_error_ticks']=max(m['max_duration_error_ticks'],err)
                    m['min_interval_ticks']=d if m['min_interval_ticks'] is None else min(m['min_interval_ticks'],d)
                    m['max_interval_ticks']=d if m['max_interval_ticks'] is None else max(m['max_interval_ticks'],d)
            phase=current[3]%specs[module]['period_raw']
            target=specs[module]['phase_open_raw'] if current[4] else specs[module]['phase_closed_raw']
            phase_error=min((phase-target)%specs[module]['period_raw'],(target-phase)%specs[module]['period_raw'])
            m['phase_error_samples']+=1
            m['max_phase_error_ticks']=max(m['max_phase_error_ticks'],phase_error)
            m['last']=current
    bad=[]
    for module,m in observed.items():
        spec=specs[module]; first=m['first']
        if m['count']<1000 or first is None or m['bad_values']:
            bad.append(module); continue
        first_state_ok=first[4]==spec['first_state']
        # Do not turn clock-step phase variation into a technical failure. The
        # installed SettableClock may execute an overdue absolute ClockEvent
        # immediately after a correction; this shifts the observed local phase.
        # Keep every measured phase/interval deviation, while validating that
        # the scheduled state sequence is present, ordered and alternating.
        m['first_phase_error_ticks']=min((first[3]%spec['period_raw']-
            (spec['phase_open_raw'] if first[4] else spec['phase_closed_raw']))%spec['period_raw'],
            ((spec['phase_open_raw'] if first[4] else spec['phase_closed_raw'])-
             first[3]%spec['period_raw'])%spec['period_raw'])
        if not first_state_ok: bad.append(module)
    phase_deviation_modules=[m for m,v in observed.items() if v['max_phase_error_ticks']>1]
    return {'status':'pass' if not bad else 'fail','sequence_status':'pass' if not bad else 'fail',
            'phase_timing_status':'measured_deviations' if phase_deviation_modules else 'within_clock_tick',
            'phase_deviation_modules':phase_deviation_modules,'expected_gate_count':len(specs),
            'observed_transition_vectors':sum(1 for m in observed.values() if m['count']>0),
            'mismatches':bad,'ticks_per_second':10**(-exp),'gates':observed,
            'method':'streamed gate transitions; validates all expected gate modules, first state, monotonic event order, and alternating open/close sequence. Per-event local-clock phase errors and consecutive interval errors are measured and retained, not used as a technical-failure gate because installed SettableClock can execute overdue absolute ClockEvents immediately after corrections.'}

def self_test_validation():
    a005,_,_,_=load_profiles()
    old_good=SIM/'pilot/c4_gate_clock_reference/results/runs/A005_local_L2_A1_seed41_v1/Pilot_C4compensated_L2_A1-#0.sca'
    old_bad=SIM/'pilot/c4_real_clock_service_margin/results/runs/B_local_L2_A1_seed41/Pilot_C4compensated_L2_A1-#0.sca.gz'
    old_rpm=SIM/'pilot/c4_real_clock_service_margin/results/runs/RPM_combined_L2_A1_seed41/Pilot_C4compensated_L2_A1-#0.sca.gz'
    if not old_good.is_file() or not old_bad.is_file() or not old_rpm.is_file():
        raise RuntimeError('Historical SCA artifacts required for validator self-test are missing')
    good=profile_sca_check(old_good,a005)
    bad=profile_sca_check(old_bad,a005)
    local_gcl=gcl_check(old_good,'B_local')
    rpm_gcl=gcl_check(old_rpm,'RPM_combined')
    return {'historical_CBS_A005':{'path':str(old_good.relative_to(ROOT)),'pass':good['pass'],'observed_cbs_modules':good['observed_cbs_modules'],'mismatches':good['mismatches']},
            'audited_no_CBS_B':{'path':str(old_bad.relative_to(ROOT)),'rejected':not bad['pass'],'observed_cbs_modules':bad['observed_cbs_modules'],'mismatches':bad['mismatches']},
            'historical_B_GCL':{'path':str(old_good.relative_to(ROOT)),'pass':local_gcl['status']=='pass','mismatches':local_gcl['mismatches']},
            'audited_RPM_phase_mismatch':{'path':str(old_rpm.relative_to(ROOT)),'rejected':rpm_gcl['status']=='fail','mismatches':rpm_gcl['mismatches']},
            'self_test_pass':good['pass'] and not bad['pass'] and good['observed_cbs_modules']==len(a005) and local_gcl['status']=='pass' and rpm_gcl['status']=='fail'}

def state():
    try:return json.loads((OUT/'checkpoint.json').read_text())
    except Exception:return {'status':'not_started','active':None,'completed':[]}

def write_checkpoint(cp): atomic(OUT/'checkpoint.json',cp)
def append_ledger(row):
    p=OUT/'runs.jsonl'; p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('a') as f: f.write(json.dumps(row,separators=(',',':'),sort_keys=True)+'\n'); f.flush(); os.fsync(f.fileno())

def write_expected_profile_table(plan):
    rows=[]
    for variant,profile in plan['expected_cbs_by_treatment'].items():
        for key,values in profile.items():
            egress,tc=key.rsplit('/TC',1)
            rows.append({'variant':variant,'egress':egress,'tc':tc,'module_type':values['type'],
                'idleSlope_bps':values['idleSlope_bps'],'sendSlope_bps':values['sendSlope_bps'],
                'bitrate_bps':values['bitrate_bps'],'initialCredit':values['initialCredit'],
                'transmitCreditLimit':values['transmitCreditLimit'],'minCredit':values['minCredit'],
                'maxCredit':values['maxCredit'],'accumulateCreditInGuardBand':values['accumulateCreditInGuardBand'],
                'maxInterferenceSize':values['maxInterferenceSize'],'extraLength':values['extraLength'],
                'extraDuration':values['extraDuration']})
    for variant in VARIANTS:
        for key in plan['expected_no_cbs_modules']:
            egress,tc=key.rsplit('/TC',1)
            rows.append({'variant':variant,'egress':egress,'tc':tc,'module_type':'SP/no CBS',
                         'idleSlope_bps':'','sendSlope_bps':'','bitrate_bps':physical_rate_bps(egress),
                         'initialCredit':'','transmitCreditLimit':'','minCredit':'','maxCredit':'',
                         'accumulateCreditInGuardBand':'','maxInterferenceSize':'','extraLength':'','extraDuration':''})
    path=OUT/'expected_cbs_profile_table.csv'; path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    return path

def run_one(variant,plan,execution_id_override=None,technical_replacement_of=None):
    if official_active(): raise RuntimeError('Official campaign is active; refusing pilot launch')
    if free_gib()<MIN_FREE_GIB or mem_gib()<MIN_MEM_GIB: raise RuntimeError(f'Resource floor: free={free_gib():.1f}GiB, MemAvailable={mem_gib():.1f}GiB')
    process_rows=subprocess.run(['ps','-eo','pid=,comm='],text=True,capture_output=True,check=True).stdout.splitlines()
    active_simulators=[row.strip() for row in process_rows if row.strip().split()[-1:] in (["opp_run"],["zonal-ivn-tsn"])]
    if active_simulators:
        raise RuntimeError('Another OMNeT++ simulation process is active')
    logical_id=execution_id_override or f'{variant}_L2_A1_seed41'
    cp=state(); attempt_counts=cp.setdefault('attempts_by_logical_execution',{}); attempt_no=int(attempt_counts.get(logical_id,0))+1
    if attempt_no>2: raise RuntimeError(f'Maximum one technical replacement already used for {logical_id}')
    canonical=OUT/'runs'/logical_id
    if (canonical/'pilot-result.json').is_file() or (canonical/'technical-validation.json').is_file():
        raise RuntimeError(f'Existing finalized attempt requires ledger/checkpoint reconciliation; refusing to rerun or overwrite: {canonical}')
    actual_id=logical_id if not canonical.exists() else f'{logical_id}_technical_attempt_{attempt_no-1:03d}'
    dest=OUT/'runs'/actual_id
    if dest.exists(): raise RuntimeError(f'Attempt output directory already exists; preserved without overwrite: {dest}')
    attempt_counts[logical_id]=attempt_no; write_checkpoint(cp)
    spec={'variant':variant,'cell':'L2_A1','seed':41,'logical_execution_id':logical_id,'execution_id':actual_id,
          'attempt_number':attempt_no,'technical_replacement':attempt_no>1}
    dest.mkdir(parents=True,exist_ok=False)
    config,args=sim_args(variant,dest,41,profile_for(variant,plan),CAL,plan)
    env=os.environ.copy(); env['LD_LIBRARY_PATH']=':'.join([str(OMNET/'lib'),str(INET/'src'),env.get('LD_LIBRARY_PATH','')]).rstrip(':')
    cmd=[str(ROOT/'src/zonal-ivn-tsn')]+args
    log=dest/f'{config}.log'
    cp=state(); cp.update({'status':'running','phase':'simulation','active':{'execution_id':spec['execution_id'],'logical_execution_id':logical_id,'attempt_number':attempt_no,'variant':variant,'cell':'L2_A1','seed':41,'pid':None,'started_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'percent':None},'free_gib':free_gib(),'MemAvailable_GiB':mem_gib()}); write_checkpoint(cp)
    logstream=log.open('w')
    proc=subprocess.Popen(cmd,cwd=SIM,env=env,stdout=logstream,stderr=subprocess.STDOUT,start_new_session=True,preexec_fn=lambda: os.nice(12))
    cp['active']['pid']=proc.pid; write_checkpoint(cp)
    start=time.time(); last=0
    try:
        while proc.poll() is None:
            time.sleep(10)
            if time.time()-last>=30:
                last=time.time(); cp=state(); cp['active']={'execution_id':spec['execution_id'],'logical_execution_id':logical_id,'attempt_number':attempt_no,'variant':variant,'cell':'L2_A1','seed':41,'pid':proc.pid,'started_utc':cp.get('active',{}).get('started_utc'),'elapsed_s':round(time.time()-start,1),'percent':None,'progress_note':'simulator emits no reliable event-time percentage; process alive','log_bytes':log.stat().st_size if log.exists() else 0}; cp['free_gib']=free_gib(); cp['MemAvailable_GiB']=mem_gib(); write_checkpoint(cp)
            if free_gib()<MIN_FREE_GIB or mem_gib()<MIN_MEM_GIB:
                os.killpg(proc.pid,signal.SIGTERM)
                raise RuntimeError(f'Resource floor crossed during run: free={free_gib():.1f}GiB, memory={mem_gib():.1f}GiB')
        logstream.close()
        if proc.returncode!=0: raise RuntimeError(f'OMNeT++ exit={proc.returncode}; see {log}')
        if 'Simulation time limit reached' not in log.read_text(errors='replace'):
            raise RuntimeError('OMNeT++ log lacks normal simulation-time completion')
        cp=state(); cp.update({'status':'postprocessing','phase':'validate','active':{'execution_id':spec['execution_id'],'variant':variant,'percent':100,'pid':None}}); write_checkpoint(cp)
        report,run_dir=validator.run_cell(config,dest,env=env,inet=INET,execute=False,result_dir_override=str(dest.relative_to(SIM)),extra_args=(),allow_gptp_control=True,allow_scheduled_gates=variant in GATED)
        run_dir=Path(run_dir); sca=dest/f'{config}-#0.sca'; vec=next(dest.glob(f'{config}-#*.vec'),None)
        if vec is None: raise RuntimeError('Raw vector not produced')
        # The previous pilot's parser is streaming and keeps only sparse clock data in RAM.
        vector_audit=shared.extract_pilot_vectors(vec,report,run_dir,'C4compensated' if variant in GATED else 'C3sync')
        signature,calendar_rows=parse_calendar_from_run(run_dir)
        expected,_=calendar_signature(CAL)
        profile=profile_for(variant,plan)
        profile_check=profile_sca_check(sca,profile)
        gcl=gcl_check(sca,variant) if variant in GATED else {'status':'not_applicable'}
        instr_ok,instr=instrumentation_check(run_dir,expected)
        credit_vectors=credit_vector_check(run_dir,profile)
        gate_events=gate_runtime_check(run_dir,variant) if variant in GATED else no_tas_check(sca,run_dir/'packet_events.csv')
        queue_trace_ok,queue_trace_audit=verify_queue_trace_against_report(run_dir,report)
        b_comparison=(historical_b_comparison(run_dir/'queue_occupancy_events.csv.gz',report,(queue_trace_ok,queue_trace_audit))
                      if variant=='B_local' else None)
        b_reproduction_ok=(b_comparison is not None and b_comparison['status']=='comparable') if variant=='B_local' else None
        technical_valid=(signature==expected and profile_check['pass'] and instr_ok and queue_trace_ok and credit_vectors['status']=='pass' and
                         (gcl['status']=='pass' and gate_events['status']=='pass' if variant in GATED else gate_events['status']=='pass'))
        report['queue_recalculation_verified']=queue_trace_ok
        report['queue_trace_recalculation']={'valid':queue_trace_ok,**queue_trace_audit}
        if variant=='B_local':
            report['historical_A005_comparison']=b_comparison
            report['B_control_reproduction_pass']=b_reproduction_ok
        combined_viability=report.get('viable')
        # The acceptance validator uses None for medium-criticality flows that
        # have no P1 binary gate. Such flows are neutral, not failures.
        receiver_gates=[r for m in report.get('qos',{}).values() for r in m.get('receivers',{}).values()]
        app_viability=bool(receiver_gates) and all(r.get('viable') is not False for r in receiver_gates)
        queue_stability=(not bool(report.get('nonstable_queues')) if report.get('queue_recalculation_verified') is True else None)
        sync_status=(vector_audit.get('synchronization') or {}).get('status')
        report.update({'exploratory':True,'official_c4_frozen':False,'variant':variant,'variant_id':variant,'execution_id':spec['execution_id'],'logical_execution_id':logical_id,'attempt_number':attempt_no,'technical_replacement':attempt_no>1,'cell':'L2_A1','seed':41,'calendar_sha256':signature,'calendar_event_count':len(calendar_rows),'calendar_paired':signature==expected,'effective_profile_bps':profile,'effective_profile_sha256':check_profile(profile),'resolved_profile_audit':profile_check,'effective_gcl':gcl,'observed_gate_events':gate_events,'credit_vector_validation':credit_vectors,'pilot_vector_audit':vector_audit,'instrumentation_validation':{'valid':instr_ok,**instr},'simulation_valid':technical_valid,'validator_combined_cell_viable':combined_viability,'application_viable':app_viability,'stability_viable':queue_stability,'synchronization_sample_viable':None if sync_status in (None,'unavailable') else sync_status=='pass','synchronization_continuous_status':'not_verified','raw_vector_sha256':sha(vec),'duration_wall_seconds':round(time.time()-start,1),'command':cmd,'runtime_versions':{'omnetpp':plan['omnetpp_version'],'inet':plan['inet_version']}})
        if technical_replacement_of:
            report['technical_replacement'] = True
            report['technical_replacement_of'] = technical_replacement_of
        if not report['simulation_valid']:
            atomic(dest/'technical-validation.json',report)
            raise RuntimeError('Execution failed resolved CBS/GCL/calendar/credit/instrumentation validation; raw evidence retained')
        # Compact only after a streaming byte-for-byte round-trip check. Preserve
        # full vectors, which allow exact reprocessing of quantiles and signals.
        retained=[]
        for evidence_name in ('packet_events.csv','clock_precision.csv','events.csv'):
            evidence=run_dir/evidence_name
            if evidence.exists(): retained.append(gzip_verified(evidence))
        atomic(run_dir/'retention_manifest.json',{'compression':retained,
            'full_vector_retained':True,'raw_vector_sha256':sha(vec),
            'compact_metrics_verified':True,'queue_trace_verified':queue_trace_ok,
            'credit_vectors_verified':credit_vectors['status']=='pass'})
        reportpath=dest/'pilot-result.json'; atomic(reportpath,report); append_ledger(report)
        b_gate_pass=technical_valid and b_reproduction_ok if variant=='B_local' else None
        cp=state(); cp.update({'status':'completed','phase':'B_instrumentation_gate' if variant=='B_local' and b_gate_pass else 'paused_for_B_comparison_review' if variant=='B_local' else 'initial_seed41','active':None,'completed':cp.get('completed',[])+[spec['execution_id']],'completed_logical_executions':cp.get('completed_logical_executions',[])+[logical_id],'last_result':spec['execution_id'],'instrumentation_validated':b_gate_pass if variant=='B_local' else cp.get('instrumentation_validated'),'free_gib':free_gib(),'MemAvailable_GiB':mem_gib()}); write_checkpoint(cp)
        # Raw vectors are redundant after successful validation and compact extraction; retain SCA/log compressed, and preserve no full vector by default.
        retained=[]
        for p in (sca,log,vec):
            if p.exists(): retained.append(gzip_verified(p))
        atomic(dest/'retention_manifest.json',{'compression':retained,
            'full_vector_retained_compressed':True,'raw_vector_sha256':report['raw_vector_sha256'],
            'compact_metrics_verified':True,'queue_trace_verified':queue_trace_ok,
            'credit_vectors_verified':credit_vectors['status']=='pass'})
        return report
    except BaseException as exc:
        try:
            if proc.poll() is None:
                os.killpg(proc.pid,signal.SIGTERM)
                try: proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid,signal.SIGKILL); proc.wait(timeout=5)
        except (ProcessLookupError,subprocess.TimeoutExpired): pass
        try: logstream.close()
        except Exception: pass
        cp=state(); cp.update({'status':'failed_technical','phase':'paused_after_technical_error','active':None,'last_error':f'{type(exc).__name__}: {exc}','last_execution_id':spec['execution_id'],'free_gib':free_gib(),'MemAvailable_GiB':mem_gib()}); write_checkpoint(cp)
        (OUT/'technical_attempts.jsonl').parent.mkdir(parents=True,exist_ok=True)
        with (OUT/'technical_attempts.jsonl').open('a') as f: f.write(json.dumps({'execution_id':spec['execution_id'],'logical_execution_id':logical_id,'attempt_number':attempt_no,'variant':variant,'attempt_dir':str(dest.relative_to(ROOT)),'error':str(exc),'timestamp_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())})+'\n')
        raise

def runtime_preflight(plan):
    """Instantiate the corrected B network at t=0 to verify runtime module resolution only."""
    if official_active(): raise RuntimeError('Official campaign is active; refusing pilot preflight')
    if free_gib()<MIN_FREE_GIB or mem_gib()<MIN_MEM_GIB: raise RuntimeError('Resource floor prevents preflight')
    dest=OUT/'preflight_B'; suffix=0
    while dest.exists():
        suffix+=1; dest=OUT/f'preflight_B_attempt_{suffix:03d}'
    dest.mkdir(parents=True,exist_ok=False)
    config,args=sim_args('B_local',dest,41,profile_for('B_local',plan),CAL,plan)
    args.append('--sim-time-limit=0s')
    env=os.environ.copy(); env['LD_LIBRARY_PATH']=':'.join([str(OMNET/'lib'),str(INET/'src'),env.get('LD_LIBRARY_PATH','')]).rstrip(':')
    cmd=[str(ROOT/'src/zonal-ivn-tsn')]+args
    log=dest/f'{config}-preflight.log'
    with log.open('w') as f:
        proc=subprocess.run(cmd,cwd=SIM,env=env,stdout=f,stderr=subprocess.STDOUT,timeout=180)
    sca=dest/f'{config}-#0.sca'
    if proc.returncode!=0 or not sca.is_file():
        raise RuntimeError(f'Runtime preflight failed with exit {proc.returncode}; see {log}')
    profile=profile_for('B_local',plan)
    cbs=profile_sca_check(sca,profile); gcl=gcl_check(sca,'B_local')
    logtext=log.read_text(errors='replace')
    result={'execution_type':'runtime_configuration_preflight_only','simulation_time_limit_s':0,
            'methodological_execution':False,'command':cmd,'returncode':proc.returncode,
            'runtime_versions':{'omnetpp':plan['omnetpp_version'],'inet':plan['inet_version']},
            'resolved_profile_audit':cbs,'effective_gcl':gcl,
            'has_runtime_error':('<!> Error:' in logtext),'technical_preflight_pass':cbs['pass'] and gcl['status']=='pass' and '<!> Error:' not in logtext,
            'raw_artifacts':{'sca_sha256':sha(sca),'log_sha256':sha(log)},
            'resource_after_preflight':{'free_disk_GiB':free_gib(),'MemAvailable_GiB':mem_gib()}}
    atomic(dest/'preflight.json',result)
    if not result['technical_preflight_pass']:
        raise RuntimeError('Runtime preflight did not resolve all CBS/GCL contracts')
    return result

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--plan',action='store_true'); ap.add_argument('--self-test-validation',action='store_true'); ap.add_argument('--preflight',action='store_true'); ap.add_argument('--run-first',action='store_true'); ap.add_argument('--continue-initial',action='store_true'); args=ap.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    with LOCK.open('a+') as lf:
        try: fcntl.flock(lf,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: raise SystemExit('Pilot runner already active')
        if args.self_test_validation:
            result=self_test_validation()
            print(json.dumps(result,indent=2,sort_keys=True))
            if not result['self_test_pass']: raise SystemExit(1)
            return
        if args.preflight:
            plan_path=OUT/'plan.json'
            if not plan_path.is_file(): raise SystemExit('Run --plan first')
            plan=json.loads(plan_path.read_text())
            if source_hashes()!=plan.get('source_hashes'): raise SystemExit('Sources changed since plan freeze')
            result=runtime_preflight(plan)
            print(f"Runtime preflight passed: {result['resolved_profile_audit']['observed_cbs_modules']} CBS modules; no measurement launched.")
            return
        if args.plan:
            existing_cp=state()
            if existing_cp.get('status') not in ('not_started','planned') or existing_cp.get('completed_logical_executions') or existing_cp.get('active'):
                raise SystemExit('A plan/checkpoint already contains execution state; refusing to replace it')
            plan=make_plan()
            (OUT/'plan.json').write_text(json.dumps(plan,indent=2,sort_keys=True)+'\n')
            expected_table=write_expected_profile_table(plan)
            atomic(OUT/'protocol_manifest.json',{'status':'frozen_before_execution','plan_sha256':sha(OUT/'plan.json'),'protocol_sha256':sha(HERE/'protocol.md'),'created_utc':plan['created_utc'],'source_hashes':plan['source_hashes'],'current_commit':plan['git_commit'],'working_tree_status':plan['working_tree_status_at_plan']})
            write_checkpoint({'pilot_id':plan['pilot_id'],'status':'planned','phase':'preflight','active':None,'completed':[],'instrumentation_validated':False,'max_parallel_jobs':1,'resource_floor_gib':MIN_FREE_GIB,'free_gib':free_gib(),'MemAvailable_GiB':mem_gib(),'exploratory':True,'official_c4_frozen':False})
            print(f"Plan written; expected CBS/SP table: {expected_table.relative_to(ROOT)}; free {free_gib():.1f} GiB; memory available {mem_gib():.1f} GiB; no simulation launched.")
            return
        plan_path=OUT/'plan.json'
        if not plan_path.is_file(): raise SystemExit('Run --plan first; no simulation can start without a frozen manifest')
        plan=json.loads(plan_path.read_text())
        current_hashes=source_hashes()
        if current_hashes!=plan.get('source_hashes'):
            raise SystemExit('Pilot source/configuration hashes changed since preregistration; freeze a reviewed new plan before execution')
        if not args.run_first and not args.continue_initial: raise SystemExit('Choose --plan, --run-first, or --continue-initial')
        if args.run_first:
            cp=state()
            if 'B_local_L2_A1_seed41' in cp.get('completed_logical_executions',[]): raise SystemExit('B_local already completed and audited; refusing duplicate execution')
            run_one('B_local',plan); print('B_local completed; inspect all technical checks before any further run.'); return
        cp=state()
        if not cp.get('instrumentation_validated'): raise SystemExit('B_local configuration, paired calendar, queue accounting, credit/gate instrumentation, or historical A005 comparison has not passed; refusing remaining candidates')
        done=set(cp.get('completed_logical_executions',[]))
        for variant in plan['pre_execution_decisions']['run'][1:]:
            eid=f'{variant}_L2_A1_seed41'
            if eid in done: continue
            run_one(variant,plan)
        print('Initial six seed-41 executions complete; selection and conditional cells remain pending analysis.')
if __name__=='__main__': main()
