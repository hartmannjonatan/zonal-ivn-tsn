#!/usr/bin/env python3
"""Run one authorized short precision-only probe. Existing attempts are never overwritten."""
import hashlib, importlib.util, json, os, subprocess, sys, time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[6]
HERE=Path(__file__).resolve().parent
SIM=ROOT/'simulations'
PILOT=ROOT/'simulations/pilot/c4_shared_sp_brakes'
AUDIT=PILOT/'audits/synchronization_2026_10_12'
PRECISION=AUDIT/'precision'
INET=Path('/home/jonatan/omnetpp/samples/inet-4.7.0')
variant=sys.argv[1] if len(sys.argv)>1 else 'C3sync'
if variant not in ('C3sync','C4compensated'):
    raise SystemExit('variant must be C3sync or C4compensated')
seed=43
specmod=importlib.util.spec_from_file_location('pilot_runner',PILOT/'run_pilot.py')
runner=importlib.util.module_from_spec(specmod); specmod.loader.exec_module(runner)
manifest=json.loads((PILOT/'results/plan.json').read_text())
spec={'variant':variant,'cell':'L2_A1','seed':seed,'load_index':2,'execution_id':f'PRECISION_AUDIT_{variant}_L2_A1_seed{seed}_v1'}
config,_,extras=runner.simulation_overrides(spec,manifest)
out=PRECISION/'technical'/f'{variant}_L2_A1_seed43_v1'
out.mkdir(parents=True,exist_ok=False)
trace=out/'clock_precision.csv'
extras += ['--sim-time-limit=3.05s',
  '--network=zonal_ivn_tsn.simulations.pilot.c4_shared_sp_brakes.audits.synchronization_2026_10_12.precision.ZonalIVNClockPrecisionAudit',
  f'--*.clockAudit.outputFile="{trace}"',
  '--*.clockAudit.sampleInterval=1ms','--*.clockAudit.stopAt=3.05s',
  '--**.clock.underlyingClock.emitClockTimeInterval=1ms',
  '--**.clock.underlyingClock.timeChanged.result-recording-modes=vector',
  '--**.clock.oscillatorCompensationChanged.result-recording-modes=vector']
cmd=[str(ROOT/'src/zonal-ivn-tsn'),'-u','Cmdenv','-n',f'.:{ROOT/"src"}:{ROOT/"tests"}:{INET/"src"}',
  '-f','omnetpp.ini','-c',config,'--cmdenv-express-mode=true','--cmdenv-event-banners=false',
  f'--result-dir={out.relative_to(SIM)}','-l',str(PRECISION/'plugin/libclockprecision.so'),*extras]
calendar=PILOT/'results/calendars/L2_A1/seed43_events.csv'
record={'execution_id':spec['execution_id'],'argv':cmd,'cwd':str(SIM),'variant':variant,'cell':'L2_A1','seed':seed,
 'warmup_s':1.0,'observation_window_s':[1.0,3.0],'simulation_time_limit_s':3.05,'drifts_ppm':manifest['parameters']['clock_drift_ppm_by_seed_node'][str(seed)],
 'calendar':str(calendar.resolve()),'calendar_sha256':runner.sha256(calendar),
 'profile':'unchanged pilot profile; no recalibration','instrumentation':'ClockTime raw ticks; direct parent-minus-HPC subtraction before serialization'}
(out/'command.json').write_text(json.dumps(record,indent=2)+'\n')
with (out/'simulation.log').open('w') as log:
    result=subprocess.run(cmd,cwd=SIM,stdout=log,stderr=subprocess.STDOUT,env=runner.simulator_environment())
record.update({'return_code':result.returncode,'finished_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'trace_exists':trace.exists(),
 'trace_sha256':hashlib.sha256(trace.read_bytes()).hexdigest() if trace.exists() else None,'log':'simulation.log'})
(out/'command.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps(record,indent=2))
raise SystemExit(result.returncode)
