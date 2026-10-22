#!/usr/bin/env python3
"""Finalize corrected historical C4 summaries from retained compact exports only."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
OLD=ROOT/'simulations/pilot/c4_service_preservation/results'
P=OLD/'pilot_results.json'; data=json.loads(P.read_text())
queue={}
for eid in ('C4compensated_L2_A1_seed41_instrumentation_v5','C4compensated_L2_A1_seed43','C4compensated_L2_A1_seed47'):
    row=next(r for r in data['runs'] if r.get('execution_id')==eid)
    q=next(q for q in row.get('queue_stability',[]) if q.get('queue')=='ZonalIVN.HPC.eth[0].macLayer.queue.queue[4]')
    queue[eid]={'capacity_bits':q['capacity_bits'],'capacity_KiB':q['capacity_bits']/8192,
      'six_5s_means_bits':q['mean_occupancy_bits_5s'],'six_5s_means_KiB':[v/8192 for v in q['mean_occupancy_bits_5s']],
      'mean_bits':q['mean_occupancy_bits_measurement'],'max_bits':q['max_occupancy_bits'],
      'fraction_ge_90pct':q['fraction_measurement_at_least_90pct_capacity'],'sustained_growth':q['sustained_growth'],
      'independent_recalculation_verified_at_original_extraction':row.get('queue_recalculation_verified') is True,
      'change_point_trace_retained':(OLD/'runs'/eid).exists()}
data['historical_export_audit']['HPC_eth0_TC4_queue_recalculation']=queue
ds=data['decision_summary']
ds['gptp_warmup_convergence_passed']=ds.pop('gptp_sync_passed',None)
ds['gptp_measurement_assessed']=False
ds['gptp_measurement_status']='unavailable_missing_full_measurement_series'
ds['measured_gate_count']=None
ds['resolved_gate_configuration_count']=56
ds['measured_gates_pass']=None
ds['gate_state_measurement_status']='unavailable_state_series_removed'
ds['historical_f10_route_coverage_passed']=False
ds['c4_compensated_all_l2_queue_stable']=all(not queue[k]['sustained_growth'] for k in queue)
ds['cbs_service_fully_preserved']=ds['c4_compensated_all_l2_queue_stable']
ds['c4_compensated_hpc_tc4_sustained_growth_seeds']=[41,43,47]
ds['c4_compensated_hpc_tc4_queue_capacity_KiB']=32.0
ds['c4_compensated_hpc_tc4_final_5s_mean_KiB']={str(seed):queue[eid]['six_5s_means_KiB'][-1] for seed,eid in zip((41,43,47),queue)}
tmp=P.with_suffix('.json.tmp');tmp.write_text(json.dumps(data,indent=2,sort_keys=True)+'\n');tmp.replace(P)

correction_path=OLD/'audit-corrections.json';corr=json.loads(correction_path.read_text()) if correction_path.exists() else {}
corr['queue_audit']=queue
corr['decision_changes']={'HPC_eth0_TC4_sustained_growth_seeds':[41,43,47],
  'effective_gate_configuration_pass_is_not_measured_gate_state_pass':True,
  'historical_F10_last_hop_TAS_covered':False,'full_measurement_clock_offsets_available':False,
  'physical_link_utilization_available':False}
correction_path.write_text(json.dumps(corr,indent=2,sort_keys=True)+'\n')

lines=['# Historical C4 pilot: corrected offline audit','',
 'This correction uses existing resolved SCA, compact result rows, and retained queue change-point evidence only. No new simulation ran. The original JSON/Markdown are preserved in `history/pre-c4-route-util-sync-audit-20261009/`.','',
 '## F08–F10 routes and historical gate coverage','',
 '| Flow | Receiver | Actual path | Link rates | Historical last-hop gate |','|---|---|---|---|---|',
 '| F08 | BRAKE1 | HPC.eth[0] → CSW.eth[1] → Z1.ZSW.eth[4] | 1G / 1G / 100Mbit/s | yes, Z1.eth[4] |',
 '| F09 | BRAKE2 | HPC.eth[0] → CSW.eth[2] → Z2.ZSW.eth[4] | 1G / 1G / 100Mbit/s | yes, Z2.eth[4] |',
 '| F10 | BRAKE3 | HPC.eth[0] → CSW.eth[3] → Z3.ZSW.eth[5] | 1G / 1G / 100Mbit/s | **no**; historical GCL used Z3.eth[4] |','',
 'The three actual brake-facing outputs carry only their own brake application flow. The historical GCL/SCA reparse confirms 56 configured gates and their 100 µs period, open durations, offset, absolute-time schedule, associated clock, and implicit guard band after normalizing string/time units. Therefore the old `effective_gcl.status=fail` on the corrected v5 rows was an export comparison error; the corrected **configuration** status is pass. This does not imply full route coverage: F10 was not gate-covered. Gate-state sample series were deleted, so a measured gate-state pass is unavailable. The old C4 runs are not reclassified as full-path TAS runs.','',
 '## Link utilization and synchronization','',
 'The original PHY `transmitting` vectors are not retained. `wire.csv.gz` has interface/flow byte aggregates but no transmission intervals, so the time-weighted link busy fraction is unavailable for all historical rows. Negative exported fractions are marked unavailable; no modulo, clipping, or zero substitution was applied. The old C3/C4 clock summary covers only the last 100 ms of warm-up; full `[1,31)` s offset maxima and time beyond the 1 µs threshold cannot be recalculated because the compact clock series is absent. The C3_sync seed-43 warm-up summary reaches **30 ns** absolute offset (not 20 ns). It does not establish synchronization over the measurement.','',
 '## HPC.eth[0]/TC4 queue service and stability','',
 'The 32 KiB queue’s compact change-point metrics show sustained growth in all three compensated L2/A1 seeds. Seed 41 was independently recalculated in this audit; seeds 43 and 47 retain the original extraction’s `queue_recalculation_verified=true` flag and their exact change-point series.','',
 '| Seed / run | Capacity | Six successive 5 s means (KiB) | Peak (KiB) | Fraction ≥90% | Sustained growth |','|---|---:|---|---:|---:|---|']
for seed,eid in zip((41,43,47),queue):
    q=queue[eid]
    means=', '.join(f"{x:.2f}" for x in q['six_5s_means_KiB'])
    lines.append(f"| {seed} / `{eid}` | {q['capacity_KiB']:.2f} KiB | {means} | {q['max_bits']/8192:.2f} | {q['fraction_ge_90pct']:.4f} | {q['sustained_growth']} |")
lines += ['', 'At seed 41 the six means rise from 4.41 to 27.08 KiB, with a 31.38 KiB peak. Seed 43 rises 4.22→28.91 KiB (31.86 KiB peak); seed 47 rises 4.21→27.10 KiB (30.88 KiB peak). This is progressive accumulation toward the finite buffer, not merely a temporary association with one transient. A zero `nonstable_queues` count in the earlier summary did not establish recovery; sustained six-bin growth is the relevant evidence here. The previous conclusion that C4 fully preserved CBS service is withdrawn.','',
 '## Export correction ledger','',
 '| Field | Corrected value | Source | Effect on gates/conclusion |','|---|---|---|---|']
for c in corr.get('corrections',[]):
    lines.append(f"| `{c['field']}` / `{c['execution_id']}` | `{c['corrected']}` | {c['source']} | no new execution; C4 remains nonviable and CBS stability fails |")
lines += ['', 'Application results (including F08/F09 deadline failures and camera image completion) remain the historical measured outcomes. GCL configuration status is separated from actual route coverage and observed gate-state status. Link utilization and full-measurement synchronization are unavailable, not passed. The corrected evidence strengthens the rejection of the *tested historical configuration* as fully service-preserving; it does not prove every possible C4/TAS arrangement fails.', '']
(OLD/'analysis.md').write_text('\n'.join(lines))
print('Historical audit summary finalized from retained outputs; no simulations run.')
