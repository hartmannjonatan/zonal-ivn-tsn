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
AUDIT_DIR = SIM / "pilot/c4_gate_clock_reference/results/audits/audit_2026-10-14"
DRIFTS = HERE / "clock_drift_ppm_by_seed_node.json"
CAL = OUT / "calendars/seed41_L2_A1_F21_F22.csv"
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

def calendar_signature(path: Path):
    with path.open(newline='') as f: rows=list(csv.DictReader(f))
    cols=('flow','block','signature','start','duration','volume_bytes')
    payload=[{k:r[k] for k in cols} for r in rows]
    return hashlib.sha256(json.dumps(payload,separators=(',',':')).encode()).hexdigest(),rows

def source_hashes():
    paths=[P1, PROFILE_C3, PROFILE_CHECKPOINT, A005_RESULT, DRIFTS, CAL,
           HERE/'protocol.md',HERE/'protocol_addendum_001.md',HERE/'protocol_addendum_002.md',HERE/'protocol_addendum_003.md',HERE/'protocol_addendum_004.md',PILOT_INI,HERE/'run_pilot.py',HERE/'pilot_status.py',
           HERE/'plugin/RealClockTraceProbe.cc',HERE/'plugin/ClockPrecisionProbe.cc',
           HERE/'plugin/Makefile',PLUGIN,HERE/'RealClockTraceProbe.ned',HERE/'ClockPrecisionProbe.ned',
           SIM/'omnetpp.ini',SIM/'zonal/traffic/flows.csv',SIM/'zonal/networks/ZonalIVN.ned',
           ROOT/'src/common/TrafficPlan.cc',ROOT/'src/common/TrafficPlan.ned',
           ROOT/'src/common/TrafficAudit.cc',ROOT/'src/common/ZonalEthernetLink.ned',
           ROOT/'scripts/run/validate_c0.py',AUDIT_DIR/'audit.md',AUDIT_DIR/'audit.json']
    return {str(p.relative_to(ROOT)):sha(p) for p in paths if p.is_file()}

def make_plan():
    a005,c3,caldata,audit=load_profiles()
    calsha,calrows=calendar_signature(CAL)
    if calsha!='cb74a68801e037dce0480422e4371150c2c95765974b0ef3857f1633b54a600d': raise RuntimeError('Seed-41 transient calendar does not match audited signature')
    shared_bps={p:{k:v for k,v in a005.items() if k.startswith(p+'/')} for p in PORTS}
    line=1_000_000_000
    screens={}
    for p,d in shared_bps.items():
        reserve=sum(d.values())
        other_cap=max(0.0,(OTHER_OPEN-GUARD_MAX)/P_CLOCK*line)
        screens[p]={'cbs_idle_slope_sum_bps':reserve,'reservation_fraction_physical':reserve/line,
                    'configured_cap_headroom_75_bps':.75*line-reserve,
                    'non_tc7_open_s':OTHER_OPEN,'guard_band_max_s':GUARD_MAX,
                    'conservative_service_screen_bps':other_cap,
                    'screen_headroom_bps':other_cap-reserve,
                    'screen_headroom_fraction_of_reservation':(other_cap-reserve)/reserve if reserve else None,
                    'passes_75pct':reserve<=.75*line,'passes_10pct_post_guard_margin':other_cap>=1.1*reserve}
    zb=next((v for k,v in a005.items() if k=='Z3.ZSW.eth[7]/TC4'),None)
    if zb!=27_600_000: raise RuntimeError(f'A005 Z3/eth7 TC4 expected 27.6 Mbps, found {zb}')
    drift=json.loads(DRIFTS.read_text())
    return {'pilot_id':'c4-real-clock-service-margin','exploratory':True,'official_c4_frozen':False,'created_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
      'git_commit':subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,text=True,capture_output=True).stdout.strip(),
      'working_tree_status_at_plan':subprocess.run(['git','status','--short'],cwd=ROOT,text=True,capture_output=True).stdout,
      'omnetpp_version':(OMNET/'Version').read_text().strip(),'inet_version':(INET/'Version').read_text().strip(),
      'inet_source_sha256':{str(p.relative_to(INET)):sha(p) for p in [INET/'src/inet/queueing/gate/PeriodicGate.cc',INET/'src/inet/queueing/gate/CreditBasedGate.cc',INET/'src/inet/clock/model/SettableClock.cc',INET/'src/inet/clock/model/OscillatorBasedClock.cc',INET/'src/inet/clock/servo/StepClockServo.cc',INET/'src/inet/clock/oscillator/ConstantDriftOscillator.h']},
      'p1':{'path':str(P1.relative_to(ROOT)),'sha256':sha(P1)},'official_profile':{'id':'reduction_11','sha256':sha(PROFILE_C3),'checkpoint_sha256':sha(PROFILE_CHECKPOINT),'selected_L2_bps':c3,'status':caldata.get('status')},
      'A005_source':{'execution_id':audit.get('execution_id'),'profile_sha256':audit.get('effective_profile_sha256'),'effective_profile_bps':a005},
      'calendar':{'path':str(CAL.relative_to(ROOT)),'sha256_file':sha(CAL),'signature':calsha,'event_count':len(calrows)},
      'drifts_by_seed_node':drift,'parameters':{'load':'L2','aggregation':'A1','seed':41,'warmup_s':1,'measurement_s':30,'drain_s':.05,'max_parallel_jobs':1,'minimum_free_GiB':MIN_FREE_GIB,'minimum_MemAvailable_GiB':MIN_MEM_GIB},
      'cadence_rule':{'period_clock_s':P_CLOCK,'derivation':'100 us*(1-50 ppm), worst-slow grandmaster bound','max_frame_guard_band_s':GUARD_MAX,'minimum_other_open_fraction_rule':'1.10*sum(idleSlope)/lineRate + one maximum-frame guard-band per period','tc7_open_s':TC7_OPEN,'other_tc_open_s':OTHER_OPEN,'reference_offsets':{'TC7':'0','TC0..TC6':'0.9*period'},'R_offsets':'reference normalized phases unchanged','RP_offsets':'CSW eth1..3 TC7 opening +1us; encoded as period-1us'},
      'phase_rule':{'one_way_wire_time_s':84*8/1e9,'link_delay_s':100e-9,'offset_s':1e-6,'nominal_margin_s':1e-6-(84*8/1e9+100e-9),'clock_relative_sample_gate':'<=1us samples only; continuous compliance unverified'},
      'F13_recovery':{'A005_idleSlope_bps':zb,'catalog_wire_demand_bps':27_600_000,'candidate_idleSlope_bps':round(zb*1.02),'added_nominal_bps':round(zb*.02),'representative_queue_backlog_bits':108544,'representative_packets':53,'wire_bits_backlog':53*276*8,'estimated_recovery_s':(53*276*8)/(zb*.02),'estimate_assumption':'additional idleSlope maps to additional F13 wire service; must verify from measured service'},
      'reservation_screens':screens,'variants':VARIANTS,'schedule_initial':[{'variant':v,'cell':'L2_A1','seed':41,'execution_id':f'{v}_L2_A1_seed41'} for v in VARIANTS],
      'conditional_schedule':{'verification_after_selection':[{'variant':'selected','cell':'L2_A1','seed':s} for s in (43,47)]+[{'variant':'B_local','cell':'L2_A1','seed':s} for s in (43,47)]+[{'variant':'C3_sync_control','cell':'L2_A1','seed':s} for s in (43,47)],'extrapolation_after_both_seeds_pass':[{'variant':'selected','cell':c,'seed':41} for c in ('L0_A0','L1_A1')]+[{'variant':'C3_sync_control','cell':c,'seed':41} for c in ('L0_A0','L1_A1')]},
      'selection':{'candidates':['R_cadence','RP_cadence_phase','RPM_combined'],'gates':'all current P1 application+stability gates and valid/closed queue accounting','service_margin':'each measured 5s interval with backlog has wire service > wire arrivals and nonpositive queue growth after confirmed drops','intervention_tiebreak':'R then RP then RPM'},
      'budget':{'max_methodological_executions':16,'seed41_initial':6,'seed43_47_verification':6,'L0_L1_extrapolation':4,'max_technical_replacements':2},'source_hashes':source_hashes()}

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
            offset=('98.995us' if variant=='RP_cadence_phase' and port.startswith('CSW.') else '0s')
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
          '--network=zonal_ivn_tsn.simulations.pilot.c4_real_clock_service_margin.ZonalIVN',
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

def postprocess_existing_b(plan):
    """Validate and compact the already completed B run without rerunning OMNeT++."""
    variant='B_local'; eid='B_local_L2_A1_seed41'; dest=OUT/'runs'/eid
    config='Pilot_C4compensated_L2_A1'; run_dir=dest/f'{config}-0'
    log=dest/f'{config}.log'; sca=dest/f'{config}-#0.sca'; vec=next(dest.glob(f'{config}-#*.vec'),None)
    if vec is None or not log.is_file() or 'Simulation time limit reached' not in log.read_text(errors='replace'):
        raise RuntimeError('No completed raw B run is available to reprocess')
    env=os.environ.copy(); env['LD_LIBRARY_PATH']=':'.join([str(OMNET/'lib'),str(INET/'src'),env.get('LD_LIBRARY_PATH','')]).rstrip(':')
    expected,_=calendar_signature(CAL)
    cp=state(); cp.update({'status':'postprocessing','phase':'validate_existing_B','active':{'execution_id':eid,'variant':variant,'percent':100,'pid':None}}); write_checkpoint(cp)
    report,_=validator.run_cell(config,dest,env=env,inet=INET,execute=False,result_dir_override=str(dest.relative_to(SIM)),extra_args=(),allow_gptp_control=True,allow_scheduled_gates=True)
    vector_audit=shared.extract_pilot_vectors(vec,report,run_dir,'C4compensated')
    signature,calendar_rows=parse_calendar_from_run(run_dir)
    profile=profile_for(variant,plan); profile_check=profile_sca_check(sca,profile); gcl=gcl_check(sca,variant)
    instr_ok,instr=instrumentation_check(run_dir,expected)
    report.update({'exploratory':True,'official_c4_frozen':False,'variant':variant,'variant_id':variant,'execution_id':eid,'cell':'L2_A1','seed':41,'calendar_sha256':signature,'calendar_event_count':len(calendar_rows),'calendar_paired':signature==expected,'effective_profile_bps':profile,'effective_profile_sha256':check_profile(profile),'resolved_profile_audit':profile_check,'effective_gcl':gcl,'pilot_vector_audit':vector_audit,'instrumentation_validation':{'valid':instr_ok,**instr},'simulation_valid':signature==expected and profile_check['pass'] and gcl['status']=='pass' and instr_ok,'application_viable':report.get('viable'),'stability_viable':not bool(report.get('nonstable_queues')),'raw_vector_sha256':sha(vec),'duration_wall_seconds':'reprocessed_existing_execution','runtime_versions':{'omnetpp':plan['omnetpp_version'],'inet':plan['inet_version']},'technical_reprocess':True})
    if not instr_ok or not profile_check['pass'] or gcl['status']!='pass' or signature!=expected:
        raise RuntimeError('Reprocessed B failed configuration/instrumentation checks; raw evidence retained')
    for name in ('packet_events.csv','clock_precision.csv','events.csv'):
        evidence=run_dir/name
        if evidence.exists():
            with evidence.open('rb') as src,gzip.open(str(evidence)+'.gz','wb',compresslevel=6) as dst: shutil.copyfileobj(src,dst)
            evidence.unlink()
    reportpath=dest/'pilot-result.json'; atomic(reportpath,report); append_ledger(report)
    cp=state(); cp.update({'status':'completed','phase':'B_instrumentation_gate','active':None,'completed':cp.get('completed',[])+[eid],'last_result':eid,'instrumentation_validated':True,'free_gib':free_gib(),'MemAvailable_GiB':mem_gib(),'technical_replacements_used':1}); write_checkpoint(cp)
    for p in (sca,log):
        if p.exists():
            with p.open('rb') as src,gzip.open(str(p)+'.gz','wb',compresslevel=6) as dst: shutil.copyfileobj(src,dst)
            p.unlink()
    vec.unlink()
    return report

def read_sca_params(path):
    params={}
    with path.open(errors='replace') as f:
        for line in f:
            if not line.startswith('par ZonalIVN.'): continue
            p=line.rstrip().split(' ',3)
            if len(p)==4: params[(p[1],p[2])]=p[3]
    return params

def gcl_check(sca,variant):
    if variant=='C3_sync_control': return {'status':'not_applicable'}
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
            local_b_schedule=variant in ('B_local','BM_recovery')
            expected=([77e-6,23e-6] if tc<7 else [10e-6,90e-6]) if local_b_schedule else ([47.995e-6,52e-6] if tc<7 else [52e-6,47.995e-6])
            expected_off=(90e-6 if tc<7 else 0.0) if local_b_schedule else (89.9955e-6 if tc<7 else (98.995e-6 if variant=='RP_cadence_phase' and port.startswith('CSW.') else 0.0))
            actual[m]={'durations':decoded(d),'offset':decoded(off),'clockModule':decoded(params.get((m,'clockModule'))),'initiallyOpen':decoded(params.get((m,'initiallyOpen'))),'scheduleForAbsoluteTime':decoded(params.get((m,'scheduleForAbsoluteTime'))),'enableImplicitGuardBand':decoded(params.get((m,'enableImplicitGuardBand')))}
            got=duration_list(d); offset_s=seconds(decoded(off) or '')
            if got is None or len(got)!=2 or any(abs(x-y)>1e-12 for x,y in zip(got,expected)) or offset_s is None or abs(offset_s-expected_off)>1e-12 or actual[m]['clockModule']!='^.^.^.^.clock' or actual[m]['initiallyOpen']!='true' or actual[m]['scheduleForAbsoluteTime']!='true' or actual[m]['enableImplicitGuardBand']!='true': bad.append(m)
    return {'status':'pass' if not bad else 'fail','expected_gate_count':32,'observed_gate_count':len(actual),'mismatches':bad,'gates':actual}

def profile_sca_check(sca,profile):
    # The installed OMNeT++ result records effective command/INI overrides
    # as `config` rows; these submodule parameters aren't emitted as `par` rows.
    resolved={}
    with sca.open(errors='replace') as f:
        for line in f:
            if not line.startswith('config '): continue
            p=line.rstrip().split(' ',2)
            if len(p)==3: resolved[p[1]]=p[2]
    mismatches={}
    for key,v in profile.items():
        e,tc=key.rsplit('/TC',1)
        config_path=f'*.{e}.macLayer.queue.transmissionSelectionAlgorithm[{tc}].idleSlope'
        raw=resolved.get(config_path)
        if raw is None: mismatches[key]={'expected':v,'actual':None}; continue
        n=re.search(r'[-+]?\d+(?:\.\d+)?',raw)
        if not n or round(float(n.group()))!=v: mismatches[key]={'expected':v,'actual':raw}
    return {'pass':not mismatches,'mismatches':mismatches}

def state():
    try:return json.loads((OUT/'checkpoint.json').read_text())
    except Exception:return {'status':'not_started','active':None,'completed':[]}

def write_checkpoint(cp): atomic(OUT/'checkpoint.json',cp)
def append_ledger(row):
    p=OUT/'runs.jsonl'; p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('a') as f: f.write(json.dumps(row,separators=(',',':'),sort_keys=True)+'\n'); f.flush(); os.fsync(f.fileno())

def run_one(variant,plan,execution_id_override=None,technical_replacement_of=None):
    if official_active(): raise RuntimeError('Official campaign is active; refusing pilot launch')
    if free_gib()<MIN_FREE_GIB or mem_gib()<MIN_MEM_GIB: raise RuntimeError(f'Resource floor: free={free_gib():.1f}GiB, MemAvailable={mem_gib():.1f}GiB')
    process_rows=subprocess.run(['ps','-eo','pid=,comm='],text=True,capture_output=True,check=True).stdout.splitlines()
    active_simulators=[row.strip() for row in process_rows if row.strip().split()[-1:] in (["opp_run"],["zonal-ivn-tsn"])]
    if active_simulators:
        raise RuntimeError('Another OMNeT++ simulation process is active')
    spec={'variant':variant,'cell':'L2_A1','seed':41,'execution_id':execution_id_override or f'{variant}_L2_A1_seed41'}
    dest=OUT/'runs'/spec['execution_id']; dest.mkdir(parents=True,exist_ok=True)
    config,args=sim_args(variant,dest,41,profile_for(variant,plan),CAL,plan)
    env=os.environ.copy(); env['LD_LIBRARY_PATH']=':'.join([str(OMNET/'lib'),str(INET/'src'),env.get('LD_LIBRARY_PATH','')]).rstrip(':')
    cmd=[str(ROOT/'src/zonal-ivn-tsn')]+args
    log=dest/f'{config}.log'
    cp=state(); cp.update({'status':'running','phase':'simulation','active':{'execution_id':spec['execution_id'],'variant':variant,'cell':'L2_A1','seed':41,'pid':None,'started_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'percent':0},'free_gib':free_gib(),'MemAvailable_GiB':mem_gib()}); write_checkpoint(cp)
    logstream=log.open('w')
    proc=subprocess.Popen(cmd,cwd=SIM,env=env,stdout=logstream,stderr=subprocess.STDOUT,start_new_session=True,preexec_fn=lambda: os.nice(12))
    cp['active']['pid']=proc.pid; write_checkpoint(cp)
    start=time.time(); last=0
    try:
        while proc.poll() is None:
            time.sleep(10)
            if time.time()-last>=30:
                last=time.time(); cp=state(); cp['active']={'execution_id':spec['execution_id'],'variant':variant,'cell':'L2_A1','seed':41,'pid':proc.pid,'started_utc':cp.get('active',{}).get('started_utc'),'elapsed_s':round(time.time()-start,1),'percent':None,'progress_note':'simulator emits no reliable event-time percentage; process alive','log_bytes':log.stat().st_size if log.exists() else 0}; cp['free_gib']=free_gib(); cp['MemAvailable_GiB']=mem_gib(); write_checkpoint(cp)
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
        gcl=gcl_check(sca,variant)
        instr_ok,instr=instrumentation_check(run_dir,expected)
        report.update({'exploratory':True,'official_c4_frozen':False,'variant':variant,'variant_id':variant,'execution_id':spec['execution_id'],'cell':'L2_A1','seed':41,'calendar_sha256':signature,'calendar_event_count':len(calendar_rows),'calendar_paired':signature==expected,'effective_profile_bps':profile,'effective_profile_sha256':check_profile(profile),'resolved_profile_audit':profile_check,'effective_gcl':gcl,'pilot_vector_audit':vector_audit,'instrumentation_validation':{'valid':instr_ok,**instr},'simulation_valid':signature==expected and profile_check['pass'] and instr_ok and (gcl['status']=='pass' if variant in GATED else True),'application_viable':report.get('viable'),'stability_viable':not bool(report.get('nonstable_queues')),'raw_vector_sha256':sha(vec),'duration_wall_seconds':round(time.time()-start,1),'command':cmd,'runtime_versions':{'omnetpp':plan['omnetpp_version'],'inet':plan['inet_version']}})
        if technical_replacement_of:
            report['technical_replacement'] = True
            report['technical_replacement_of'] = technical_replacement_of
        if not report['simulation_valid']:
            atomic(dest/'technical-validation.json',report)
            raise RuntimeError('Execution failed configuration/calendar/instrumentation validation; raw evidence retained')
        # Preserve exact quantiles/misses and queue traces from validator; keep event traces in gzip.
        trace=run_dir/'packet_events.csv'
        if trace.exists():
            with trace.open('rb') as src, gzip.open(str(trace)+'.gz','wb',compresslevel=6) as dst: shutil.copyfileobj(src,dst)
            trace.unlink()
        for evidence_name in ('clock_precision.csv','events.csv'):
            evidence=run_dir/evidence_name
            if evidence.exists():
                with evidence.open('rb') as src, gzip.open(str(evidence)+'.gz','wb',compresslevel=6) as dst: shutil.copyfileobj(src,dst)
                evidence.unlink()
        reportpath=dest/'pilot-result.json'; atomic(reportpath,report); append_ledger(report)
        cp=state(); cp.update({'status':'completed','phase':'B_instrumentation_gate' if variant=='B_local' else 'initial_seed41','active':None,'completed':cp.get('completed',[])+[spec['execution_id']],'last_result':spec['execution_id'],'instrumentation_validated':instr_ok if variant=='B_local' else cp.get('instrumentation_validated'),'free_gib':free_gib(),'MemAvailable_GiB':mem_gib()}); write_checkpoint(cp)
        # Raw vectors are redundant after successful validation and compact extraction; retain SCA/log compressed, and preserve no full vector by default.
        for p in [sca,log]:
            if p.exists():
                with p.open('rb') as src,gzip.open(str(p)+'.gz','wb',compresslevel=6) as dst: shutil.copyfileobj(src,dst)
                p.unlink()
        if vec.exists(): vec.unlink()
        return report
    except Exception as exc:
        try: logstream.close()
        except Exception: pass
        cp=state(); cp.update({'status':'failed_technical','phase':'paused_after_technical_error','active':None,'last_error':f'{type(exc).__name__}: {exc}','last_execution_id':spec['execution_id'],'free_gib':free_gib(),'MemAvailable_GiB':mem_gib()}); write_checkpoint(cp)
        (OUT/'technical_attempts.jsonl').parent.mkdir(parents=True,exist_ok=True)
        with (OUT/'technical_attempts.jsonl').open('a') as f: f.write(json.dumps({'execution_id':spec['execution_id'],'variant':variant,'error':str(exc),'timestamp_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())})+'\n')
        raise

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--plan',action='store_true'); ap.add_argument('--run-first',action='store_true'); ap.add_argument('--reprocess-first',action='store_true'); ap.add_argument('--continue-initial',action='store_true'); ap.add_argument('--resume',action='store_true'); args=ap.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    with LOCK.open('a+') as lf:
        try: fcntl.flock(lf,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: raise SystemExit('Pilot runner already active')
        if args.plan:
            plan=make_plan()
            (OUT/'plan.json').write_text(json.dumps(plan,indent=2,sort_keys=True)+'\n')
            atomic(OUT/'protocol_manifest.json',{'status':'frozen_before_execution','plan_sha256':sha(OUT/'plan.json'),'protocol_sha256':sha(HERE/'protocol.md'),'created_utc':plan['created_utc'],'source_hashes':plan['source_hashes'],'current_commit':plan['git_commit'],'working_tree_status':plan['working_tree_status_at_plan']})
            write_checkpoint({'pilot_id':plan['pilot_id'],'status':'planned','phase':'preflight','active':None,'completed':[],'instrumentation_validated':False,'max_parallel_jobs':1,'resource_floor_gib':MIN_FREE_GIB,'free_gib':free_gib(),'MemAvailable_GiB':mem_gib(),'exploratory':True,'official_c4_frozen':False})
            print(f"Plan written; free {free_gib():.1f} GiB; memory available {mem_gib():.1f} GiB; no simulation launched.")
            return
        plan_path=OUT/'plan.json'
        if not plan_path.is_file(): raise SystemExit('Run --plan first; no simulation can start without a frozen manifest')
        plan=json.loads(plan_path.read_text())
        current_hashes=source_hashes()
        if current_hashes!=plan.get('source_hashes'):
            raise SystemExit('Pilot source/configuration hashes changed since preregistration; freeze a reviewed new plan before execution')
        if not args.run_first and not args.reprocess_first and not args.continue_initial: raise SystemExit('Choose --plan, --run-first, --reprocess-first, or --continue-initial')
        if args.reprocess_first:
            r=postprocess_existing_b(plan); print('Existing B run reprocessed; instrumentation_valid=',r['instrumentation_validation']['valid']); return
        if args.run_first: run_one('B_local',plan); print('B_local completed; inspect instrumentation_validation before any further run.'); return
        cp=state()
        if not cp.get('instrumentation_validated'): raise SystemExit('B_local instrumentation has not passed; refusing remaining candidates')
        done=set(cp.get('completed',[]))
        for variant in VARIANTS[1:]:
            eid=f'{variant}_L2_A1_seed41'
            if eid in done: continue
            run_one(variant,plan)
        print('Initial six seed-41 executions complete; selection and conditional cells remain pending analysis.')
if __name__=='__main__': main()
