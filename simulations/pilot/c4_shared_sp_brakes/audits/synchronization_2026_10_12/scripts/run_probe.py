#!/usr/bin/env python3
"""Launch one isolated short clock probe with the existing pilot configuration/calendar."""
import json, os, subprocess, sys, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[6]
HERE=Path(__file__).resolve().parents[1]
SIM=ROOT/'simulations'
PILOT=ROOT/'simulations/pilot/c4_shared_sp_brakes'
AUDIT=PILOT/'audits/synchronization_2026_10_12'
INET=Path('/home/jonatan/omnetpp/samples/inet-4.7.0')
variant=sys.argv[1] if len(sys.argv)>1 else 'C3sync'
seed=int(sys.argv[2]) if len(sys.argv)>2 else 43
import importlib.util
specmod=importlib.util.spec_from_file_location('pilot_runner',PILOT/'run_pilot.py')
runner=importlib.util.module_from_spec(specmod); specmod.loader.exec_module(runner)
manifest=json.loads((PILOT/'results/plan.json').read_text())
spec={'variant':variant,'cell':'L2_A1','seed':seed,'load_index':2,'execution_id':f'AUDIT_{variant}_L2_A1_seed{seed}'}
config,dest,extras=runner.simulation_overrides(spec,manifest)
out=AUDIT/'technical'/f'{variant}_L2_A1_seed{seed}'
out.mkdir(parents=True,exist_ok=True)
trace=out/'clock_audit.csv'
extras += [f'--sim-time-limit=3.05s',
  f'--network=zonal_ivn_tsn.simulations.pilot.c4_shared_sp_brakes.audits.synchronization_2026_10_12.ZonalIVNClockAudit',
  f'--*.clockAudit.outputFile="{trace}"',
  '--*.clockAudit.sampleInterval=1ms','--*.clockAudit.stopAt=3.05s',
  '--**.clock.underlyingClock.emitClockTimeInterval=1ms',
  '--**.clock.underlyingClock.timeChanged.result-recording-modes=vector',
  '--**.clock.oscillatorCompensationChanged.result-recording-modes=vector']
cmd=[str(ROOT/'src/zonal-ivn-tsn'),'-u','Cmdenv','-n',f'.:{ROOT/"src"}:{ROOT/"tests"}:{INET/"src"}',
  '-f','omnetpp.ini','-c',config,'--cmdenv-express-mode=true','--cmdenv-event-banners=false',
  f'--result-dir={out.relative_to(SIM)}','-l',str(AUDIT/'plugin/libclockaudit.so'),*extras]
cmd_record={'argv':cmd,'cwd':str(SIM),'started_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
 'variant':variant,'cell':'L2_A1','seed':seed,'sim_time_limit_s':3.05,'measurement_observation_s':[1.0,3.0],
 'drifts_ppm':manifest['parameters']['clock_drift_ppm_by_seed_node'][str(seed)],
 'calendar':str((PILOT/'results/calendars/L2_A1'/f'seed{seed}_events.csv').resolve()),
 'calendar_sha256':runner.sha256(PILOT/'results/calendars/L2_A1'/f'seed{seed}_events.csv')}
(AUDIT/'technical'/f'{variant}_L2_A1_seed{seed}'/'command.json').write_text(json.dumps(cmd_record,indent=2)+'\n')
with (out/'simulation.log').open('w') as log:
 p=subprocess.run(cmd,cwd=SIM,stdout=log,stderr=subprocess.STDOUT,env=runner.simulator_environment())
cmd_record.update({'return_code':p.returncode,'finished_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'trace_exists':trace.exists(),'log':str((out/'simulation.log').relative_to(AUDIT))})
(AUDIT/'technical'/f'{variant}_L2_A1_seed{seed}'/'command.json').write_text(json.dumps(cmd_record,indent=2)+'\n')
print(json.dumps(cmd_record,indent=2))
if p.returncode: sys.exit(p.returncode)
