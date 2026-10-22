#!/usr/bin/env python3
"""Read-only structural/resource check; never launches OMNeT++ or edits the plan."""
from __future__ import annotations
import importlib.util, json, re, sys, tempfile
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
OUT=HERE/'results'
spec=importlib.util.spec_from_file_location('pilot_runner',HERE/'run_pilot.py')
runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
plan_path=OUT/'plan.json'
if not plan_path.exists(): raise SystemExit('FAIL: run --plan first; no simulation started')
plan=json.loads(plan_path.read_text())
current=runner.make_manifest()
errors=[]
if plan.get('versions_and_hashes')!=current.get('versions_and_hashes'): errors.append('source/config hash mismatch; review and regenerate the plan')
if plan.get('official_profile',{}).get('profile_id')!='reduction_11': errors.append('profile is not frozen reduction_11')
if len(plan.get('run_schedule',[]))!=16: errors.append('schedule is not exactly 16 executions')
if runner.official_campaign_active(): errors.append('official C0-C3 campaign lock/process is active')
if not (ROOT/'src/zonal-ivn-tsn').is_file(): errors.append('built simulator binary missing')
inet=Path(plan.get('inet_root',''))
if not (inet/'src').is_dir(): errors.append('INET source directory missing; check INET_ROOT')
omnet_root=Path.home()/'omnetpp'
if not (omnet_root/'lib/liboppcommon.so').is_file(): errors.append('OMNeT++ shared runtime missing; check OMNETPP_ROOT')
if runner.free_gb()<runner.FREE_FLOOR_GB: errors.append('free disk below 45 GB execution floor')
if runner.memory_safe_jobs(1)<1: errors.append('available RAM below safe start threshold')
ini=(HERE/'pilot.ini').read_text()
configs={f"Pilot_{x['variant']}_{x['cell']}" for x in plan['run_schedule']}
sections={line.strip()[8:-1] for line in ini.splitlines() if line.startswith('[Config ')}
if not configs<=sections: errors.append(f"missing INI configs: {sorted(configs-sections)}")
if plan['route_audit']['brake_exit_exclusivity']['Z3.ZSW.eth[5]']['application_flows']!=['F10']:
    errors.append('F10 route/egress audit does not resolve to Z3.ZSW.eth[5]')
if len(plan['run_schedule']) != plan['budget']['total_scheduled']: errors.append('budget does not match run schedule')

# Resolve every planned OMNeT command/config and check per-variant gate/PHY
# overrides without touching the pilot's real calendar or output directories.
original_out=runner.OUT
with tempfile.TemporaryDirectory(prefix='c4pilot-readiness-') as temporary_out:
    runner.OUT=Path(temporary_out)
    for item in plan['run_schedule']:
        calendar=runner.OUT/'calendars'/item['cell']/f"seed{item['seed']}_events.csv"
        if item['variant']!='C3base' and not calendar.exists():
            calendar.parent.mkdir(parents=True,exist_ok=True);calendar.write_text('dry-run-placeholder\n')
        config, dest, args=runner.simulation_overrides(item,plan)
        if config not in sections: errors.append(f'config missing for {item["execution_id"]}')
        if '--**.transmitter.typename="StreamingTransmitter"' not in args or '--**.receiver.typename="DestreamingReceiver"' not in args:
            errors.append(f'PHY override mismatch for {item["execution_id"]}')
        allargs=' '.join(args)
        if item['variant']=='C4compensated':
            if 'CSW.eth[3].macLayer.queue.transmissionGate[0..6].durations=[77us,23us]' not in allargs:
                errors.append('shared-SP treatment is missing the CSW→Z3 shared TAS egress')
            if 'Z3.ZSW.eth[5].macLayer.queue.transmissionGate[0..6].durations=[77us,23us]' in allargs:
                errors.append('shared-SP treatment incorrectly gates F10 final egress')
            if 'Z3.ZSW.eth[5].macLayer.queue.transmissionGate[*].durations=[]' not in allargs:
                errors.append('F10 final output is not held SP/all-open')
        if item['variant']=='C4original':
            if 'Z3.ZSW.eth[5].macLayer.queue.transmissionGate[0..6].durations=[77us,23us]' not in allargs:
                errors.append('fullpath diagnostic does not gate actual F10 egress eth[5]')
runner.OUT=original_out

sp2=importlib.util.spec_from_file_location('pilot_dashboard',HERE/'pilot_status.py')
dashboard=importlib.util.module_from_spec(sp2);sp2.loader.exec_module(dashboard)
if 'C4 SHARED-SP-BRAKES PILOT' not in dashboard.render(): errors.append('dashboard frame could not be rendered')
if errors:
    print('READINESS=FAIL')
    for e in errors: print(f'- {e}')
    sys.exit(1)
print('READINESS=PASS')
print(f"Profile: reduction_11 | Scheduled executions: {len(plan['run_schedule'])} | Config sections: {len(configs)}")
print(f"Space: {runner.free_gb():.1f} GB free (floor {runner.FREE_FLOOR_GB:.0f}) | RAM: {runner.memory_available_gb():.1f} GB available | safe jobs now: {runner.memory_safe_jobs(runner.MAX_JOBS)}")
print(f"Official campaign active: {runner.official_campaign_active()} | Simulator launched: no")
