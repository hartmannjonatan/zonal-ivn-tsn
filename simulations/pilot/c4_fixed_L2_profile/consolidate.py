#!/usr/bin/env python3
"""Consolidate the four fixed-L2-profile runs and historical comparators."""
import csv, gzip, hashlib, json, math
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
OUT=HERE/'results'
HIST=ROOT/'simulations/pilot/c4_feasibility_decision/results/runs'
ORDER=[('D3_fixed_TAS','L0_A0'),('D3_fixed_noTAS','L0_A0'),('D3_fixed_TAS','L1_A1'),('D3_fixed_noTAS','L1_A1')]
OLD={'D3_scaled_TAS':lambda cell:f'D3_TAS_{cell}_seed41','D3_scaled_noTAS':lambda cell:f'D3_noTAS_{cell}_seed41','C3_sync':lambda cell:f'C3_sync_control_{cell}_seed41'}
def read(p): return json.loads(Path(p).read_text())
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def receiver_metrics(report):
    rows=[]
    for flow,fd in report.get('qos',{}).items():
        for receiver,m in fd.get('receivers',{}).items():
            lat=m.get('latency') or {}; img=m.get('image_completion') or {}
            rows.append({'flow':flow,'receiver':receiver,'criticality':fd.get('criticality'),
              'offered_packets':m.get('offered_packets'),'received_packets':m.get('received_packets'),
              'packet_loss_ratio':m.get('packet_loss_ratio'),'deadline_misses_received':m.get('deadline_misses_received'),
              'deadline_miss_ratio_including_loss':m.get('deadline_miss_ratio_including_loss'),
              'packet_latency_samples':lat.get('samples'),'packet_p99_s':lat.get('p99_s'),'packet_max_s':lat.get('max_s'),
              'packet_misses_from_samples':lat.get('deadline_misses_from_samples'),'goodput_payload_ratio':m.get('goodput_payload_ratio'),
              'useful_throughput_mbps':m.get('useful_throughput_mbps'),'receiver_gate':m.get('viable'),
              'image_offered':img.get('offered_images'),'image_completed':img.get('completed_images'),
              'image_packet_samples':img.get('samples'),'image_p99_s':img.get('p99_s'),'image_max_s':img.get('max_s'),
              'image_deadline_miss_ratio_including_missing':img.get('deadline_miss_ratio_including_missing_images'),
              'image_deadline_misses_completed':img.get('deadline_misses_completed')})
    return rows
def queue_metrics(report):
    keys=['ZonalIVN.HPC.eth[0].macLayer.queue.queue[4]','ZonalIVN.CSW.eth[1].macLayer.queue.queue[4]',
          'ZonalIVN.CSW.eth[2].macLayer.queue.queue[4]','ZonalIVN.CSW.eth[3].macLayer.queue.queue[4]',
          'ZonalIVN.Z1.ZSW.eth[0].macLayer.queue.queue[4]','ZonalIVN.Z2.ZSW.eth[0].macLayer.queue.queue[4]',
          'ZonalIVN.Z3.ZSW.eth[7].macLayer.queue.queue[4]']
    rows={x['queue']:x for x in report.get('queue_stability',[])}
    drops={x['queue']:x for x in report.get('queue_overflow_drops_by_queue',[])}
    out=[]
    for k in keys:
        q=rows.get(k,{})
        d=drops.get(k,{})
        out.append({'queue':k,'tc':q.get('tc'),'capacity_bits':q.get('capacity_bits'),
          'mean_occupancy_bits_5s':q.get('mean_occupancy_bits_5s'),'mean_occupancy_bits_measurement':q.get('mean_occupancy_bits_measurement'),
          'peak_bits':q.get('max_occupancy_bits'),'fraction_measurement_ge_90pct':q.get('fraction_measurement_at_least_90pct_capacity'),
          'sustained_growth':q.get('sustained_growth'),'drops_measurement':d.get('overflow_drops_measurement_window'),
          'drops_drain':d.get('overflow_drops_drain'),'drops_postwarmup_including_drain':d.get('overflow_drops_post_warmup_including_drain')})
    return out
def clock_precision_summary(path):
    """Summarize simultaneous integer-tick clock offsets without interpolation."""
    nodes=['CSW','Z1.ZSW','Z2.ZSW','Z3.ZSW']
    stats={kind:{n:{'samples':0,'samples_abs_gt_1us':0,'max_abs_offset_s':0.0,
                    'max_sample':None} for n in nodes} for kind in ('periodic','signal')}
    with gzip.open(path,'rt',newline='') as f:
        reader=csv.DictReader(f)
        for row in reader:
            kind=row.get('record_kind')
            if kind not in stats: continue
            exp=int(row['simtime_scale_exp']); tick=10.0**exp
            time_s=int(row['simtime_raw'])*tick
            if not 1.0 <= time_s < 31.0: continue
            threshold_raw=1e-6/tick
            for n in nodes:
                raw=int(row[f'{n}_offset_from_HPC_raw']); item=stats[kind][n]
                item['samples']+=1
                if abs(raw)>threshold_raw: item['samples_abs_gt_1us']+=1
                if abs(raw)*tick>item['max_abs_offset_s']:
                    item['max_abs_offset_s']=abs(raw)*tick
                    item['max_sample']={'sequence':int(row['sequence']),'event_number':int(row['event_number']),
                        'simtime_raw':int(row['simtime_raw']),'simtime_s':time_s,
                        'signed_offset_raw':raw,'offset_s':raw*tick,'record_kind':kind,'emitter':row['emitter'],'signal':row['signal']}
            if 'scale_exp' not in stats: stats['scale_exp']=exp
    per=stats.pop('periodic'); sig=stats.pop('signal'); scale=stats.pop('scale_exp',None)
    per_pass=all(per[n]['samples']>0 and per[n]['max_abs_offset_s']<=1e-6 for n in nodes)
    sig_pass=all(sig[n]['samples']>0 and sig[n]['max_abs_offset_s']<=1e-6 for n in nodes)
    return {'method':'simultaneous corrected IClock::getClockTime() snapshots; integer native ticks subtracted before serialization; no interpolation',
      'definition':'offset_i = corrected_clock_i_raw - corrected_HPC_raw at the same probe event',
      'window_s':[1,31],'tick_scale_exp':scale,'threshold_s':1e-6,
      'periodic_sample_pass':per_pass,'clock_event_snapshot_pass':sig_pass,'observed_sample_pass':per_pass and sig_pass,
      'continuous_conformity':'not_verified; 1 ms periodic samples and discrete clock-signal snapshots do not cover every instant',
      'periodic':per,'signal':sig}
def summarize(runid,path,kind):
    r=read(path)
    artifact_dir=Path(path).parent
    precision_path=artifact_dir.glob('**/clock_precision.csv.gz')
    precision_path=next(precision_path,None)
    direct_sync=clock_precision_summary(precision_path) if precision_path else None
    return {'execution_id':runid,'kind':kind,'source_path':str(Path(path).relative_to(ROOT)),'source_sha256':sha(path),
      'variant':r.get('variant'),'cell':r.get('cell'),'seed':r.get('seed'),'config':r.get('config'),
      'simulation_valid':r.get('simulation_valid'),'application_viable':r.get('application_viable'),
      'stability_viable':r.get('stability_viable'),'synchronization_sample_viable':direct_sync.get('observed_sample_pass') if direct_sync else None,
      'synchronization_continuous_status':'not_verified','synchronization_native_tick_audit':direct_sync,
      'legacy_vector_synchronization_audit':(r.get('pilot_vector_audit') or {}).get('synchronization'),'calendar_sha256':r.get('calendar_sha256'),
      'calendar_event_count':r.get('calendar_event_count'),'calendar_paired':r.get('calendar_paired'),
      'effective_profile_sha256':r.get('effective_profile_sha256'),'effective_profile_bps':r.get('effective_profile_bps'),
      'effective_gcl':r.get('effective_gcl'),'observed_gate_events':r.get('observed_gate_events'),
      'credit_vector_validation':r.get('credit_vector_validation'),'resolved_profile_audit':r.get('resolved_profile_audit'),
      'instrumentation_validation':r.get('instrumentation_validation'),'qos_by_flow_receiver':receiver_metrics(r),
      'queue_stability_by_target':queue_metrics(r),'all_nonstable_queues':r.get('nonstable_queues'),
      'overflow_drop_total_postwarmup_including_drain':r.get('queue_overflow_drop_total_post_warmup_including_drain'),
      'overflow_drops_by_queue':r.get('queue_overflow_drops_by_queue'),'measurement_drops_by_queue':r.get('measurement_drops_by_queue'),
      'drop_reconciliation':r.get('drop_reconciliation'),'pending_packet_count_at_simulation_end':r.get('pending_packet_count_at_simulation_end'),
      'pending_packets_at_simulation_end':r.get('pending_packets_at_simulation_end'),'pilot_vector_synchronization':(r.get('pilot_vector_audit') or {}).get('synchronization'),
      'physical_link_utilization_status':(r.get('physical_link_utilization') or {}).get('status'),
      'queue_trace_recalculation':r.get('queue_trace_recalculation'),'duration_wall_seconds':r.get('duration_wall_seconds'),
      'command':r.get('command'),'runtime_versions':r.get('runtime_versions'),'raw_vector_sha256':r.get('raw_vector_sha256'),
      'retention_manifest':read(Path(path).parent/'retention_manifest.json') if (Path(path).parent/'retention_manifest.json').exists() else None,
      'full_report_path':str(Path(path).relative_to(ROOT))}
def getflow(run,flow):
    return [x for x in run['qos_by_flow_receiver'] if x['flow']==flow]
def main():
    rows=[]
    for variant,cell in ORDER:
        runid=f'{variant}_{cell}_seed41'; p=OUT/'runs'/runid/'pilot-result.json'
        if not p.is_file(): raise SystemExit(f'missing run result: {p}')
        rows.append(summarize(runid,p,'new_fixed_profile'))
    history={}
    for cell in ['L0_A0','L1_A1']:
        history[cell]={}
        for label,fn in OLD.items():
            rid=fn(cell); p=HIST/rid/'pilot-result.json'
            if not p.is_file(): raise SystemExit(f'missing historical comparison: {p}')
            history[cell][label]=summarize(rid,p,'historical_scaled_or_official_control')
    # Pairing and contrasts.
    contrasts={}
    for cell in ['L0_A0','L1_A1']:
        fixed={x['variant']:x for x in rows if x['cell']==cell}
        fixed_profile=fixed['D3_fixed_TAS']['effective_profile_bps']
        scaled_profile=history[cell]['D3_scaled_TAS']['effective_profile_bps']
        extra=sum(float(value)-float(scaled_profile.get(key,0)) for key,value in fixed_profile.items())
        contrasts[cell]={'fixed_TAS_vs_fixed_noTAS':{'same_profile':fixed['D3_fixed_TAS']['effective_profile_sha256']==fixed['D3_fixed_noTAS']['effective_profile_sha256'],
             'same_calendar':fixed['D3_fixed_TAS']['calendar_sha256']==fixed['D3_fixed_noTAS']['calendar_sha256'],
             'application_viable':[fixed['D3_fixed_TAS']['application_viable'],fixed['D3_fixed_noTAS']['application_viable']],
             'stability_viable':[fixed['D3_fixed_TAS']['stability_viable'],fixed['D3_fixed_noTAS']['stability_viable']],
             'sync_sample_viable':[fixed['D3_fixed_TAS']['synchronization_sample_viable'],fixed['D3_fixed_noTAS']['synchronization_sample_viable']],
             'drops':[fixed['D3_fixed_TAS']['overflow_drop_total_postwarmup_including_drain'],fixed['D3_fixed_noTAS']['overflow_drop_total_postwarmup_including_drain']]},
          'fixed_TAS_vs_scaled_TAS':{'fixed_profile_sha256':fixed['D3_fixed_TAS']['effective_profile_sha256'],'scaled_profile_sha256':history[cell]['D3_scaled_TAS']['effective_profile_sha256'],
             'application_viable':[fixed['D3_fixed_TAS']['application_viable'],history[cell]['D3_scaled_TAS']['application_viable']],
             'stability_viable':[fixed['D3_fixed_TAS']['stability_viable'],history[cell]['D3_scaled_TAS']['stability_viable']],
             'drops':[fixed['D3_fixed_TAS']['overflow_drop_total_postwarmup_including_drain'],history[cell]['D3_scaled_TAS']['overflow_drop_total_postwarmup_including_drain']],
             'configured_idleSlope_sum_increase_bps':extra},
          'fixed_noTAS_vs_scaled_noTAS':{'fixed_profile_sha256':fixed['D3_fixed_noTAS']['effective_profile_sha256'],'scaled_profile_sha256':history[cell]['D3_scaled_noTAS']['effective_profile_sha256'],
             'application_viable':[fixed['D3_fixed_noTAS']['application_viable'],history[cell]['D3_scaled_noTAS']['application_viable']],
             'stability_viable':[fixed['D3_fixed_noTAS']['stability_viable'],history[cell]['D3_scaled_noTAS']['stability_viable']],
             'drops':[fixed['D3_fixed_noTAS']['overflow_drop_total_postwarmup_including_drain'],history[cell]['D3_scaled_noTAS']['overflow_drop_total_postwarmup_including_drain']]},
          'fixed_TAS_vs_C3_sync':{'reservation_profiles_differ':fixed['D3_fixed_TAS']['effective_profile_sha256']!=history[cell]['C3_sync']['effective_profile_sha256'],
             'application_viable':[fixed['D3_fixed_TAS']['application_viable'],history[cell]['C3_sync']['application_viable']],
             'stability_viable':[fixed['D3_fixed_TAS']['stability_viable'],history[cell]['C3_sync']['stability_viable']],
             'drops':[fixed['D3_fixed_TAS']['overflow_drop_total_postwarmup_including_drain'],history[cell]['C3_sync']['overflow_drop_total_postwarmup_including_drain']]}}
    plan=read(OUT/'plan.json'); manifest=read(OUT/'manifest.json')
    targeted={}
    for x in rows:
        wanted={'F02','F03','F06','F07','F08','F09','F10','F13','F21','F22'}
        targeted[x['execution_id']]={'flows':[f for f in x['qos_by_flow_receiver'] if f['flow'] in wanted],
          'tc4_queues':[q for q in x['queue_stability_by_target'] if q['queue'].endswith('queue[4]')]}
    result={'schema_version':1,'exploratory':True,'official_c4_frozen':False,'study':'c4_fixed_L2_profile',
      'authority':'four new L0/A0 and L1/A1 seed41 simulations only; no official C4 campaign',
      'frozen_profile_sha256':plan['profile_sha256'],'frozen_profile_table_path':'simulations/pilot/c4_fixed_L2_profile/results/frozen_profile_table.csv',
      'frozen_profile_table_sha256':plan.get('profile_table_sha256'),'expected_port_reservations':plan['expected_port_reservations'],
      'run_order':[f'{v}_{c}_seed41' for v,c in ORDER],'completed_new_execution_count':len(rows),
      'pairing':{k:{'signature':v['signature'],'event_count':v['event_count'],'source_calendar':v['copied_from']} for k,v in plan['calendars'].items()},
      'historical_controls_audit':plan['control_audit'],'new_runs':rows,'historical_comparators':history,'contrasts':contrasts,
      'targeted_findings':targeted,
      'decision':{'all_four_technical_valid':all(x['simulation_valid'] for x in rows),
        'all_four_application_viable':all(x['application_viable'] for x in rows),
        'all_four_stability_viable':all(x['stability_viable'] for x in rows),
        'all_four_gcl_or_noTAS_contract_valid':all((x['effective_gcl'] or {}).get('status') in ('pass','not_applicable') and (x['observed_gate_events'] or {}).get('status')=='pass' for x in rows),
        'all_four_sampled_sync_viable':all(x['synchronization_sample_viable'] is True for x in rows),
        'continuous_sync':'not_verified','all_four_queue_overflow_drops_zero':all((x['overflow_drop_total_postwarmup_including_drain'] or 0)==0 for x in rows),
        'conclusion':'Fixed absolute D3/L2 reservations removed the observed application/drop failures in these two seed-41 cells for both TAS and noTAS, but this is not matrix-wide or multi-seed validation. The direct native-tick synchronization audit and the P1 technical/application/stability gates are reported separately.'},
      'protocol_path':'simulations/pilot/c4_fixed_L2_profile/protocol.md','manifest':manifest,
      'source_data_inventories':{r['execution_id']:{'full_report_path':r['full_report_path'],'retention_manifest':r['retention_manifest']} for r in rows}}
    (OUT/'pilot_results.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    lines=['# C4 fixed L2 profile pilot: results','',f"Status: `exploratory=true`; `official_c4_frozen=false`. Frozen D3/L2 profile SHA-256: `{plan['profile_sha256']}`.",'',
      '## Execution matrix','', '| Cell | Treatment | Technical | Applications | Stability | Sampled sync | Overflow drops | Calendar signature |','|---|---|---:|---:|---:|---:|---:|---|']
    for cell in ['L0_A0','L1_A1']:
      for v in ['D3_fixed_TAS','D3_fixed_noTAS']:
       x=next(r for r in rows if r['cell']==cell and r['variant']==v)
       lines.append(f"| {cell.replace('_','/')} | {v} | {x['simulation_valid']} | {x['application_viable']} | {x['stability_viable']} | {x['synchronization_sample_viable']} | {x['overflow_drop_total_postwarmup_including_drain']} | `{x['calendar_sha256']}` |")
    lines+=['','All four treatments use the same absolute 24-entry L2 profile (no load scaling), seed 41, the exact cell-specific calendar, 1 s warm-up, `[1,31)` measurement and 50 ms drain. TAS uses the frozen D3/L2 GCL. noTAS preserves CBS and gPTP with periodic gate schedules absent. Results are technical outcomes from this pilot only.','',
      'The synchronization column is recalculated from the retained `clock_precision.csv.gz`, using simultaneous corrected-clock reads and native integer-tick subtraction. It supersedes the conflicting legacy vector-derived field, retained separately in the JSON. Maximum absolute offsets across the four runs were 20–50 ns in both the 1 ms periodic samples and clock-change snapshots (30,000 periodic samples per node/run); observed samples pass 1 µs, while continuous conformity remains unverified. The probe samples periodically at 1 ms and records clock-change events; this does not prove every instant between records.','',
      '## Comparison against load-scaled D3 and C3 controls','', '| Cell | Contrast | Fixed result | Historical result | Drops fixed / historical | Profile relation |','|---|---|---|---|---:|---|']
    for cell in ['L0_A0','L1_A1']:
      for contrast,a,b in [('TAS fixed vs scaled','D3_fixed_TAS','D3_scaled_TAS'),('noTAS fixed vs scaled','D3_fixed_noTAS','D3_scaled_noTAS'),('fixed TAS vs official C3','D3_fixed_TAS','C3_sync')]:
       fixed=next(r for r in rows if r['cell']==cell and r['variant']==a); old=history[cell][b]
       rel='same' if fixed['effective_profile_sha256']==old['effective_profile_sha256'] else 'different profiles'
       lines.append(f"| {cell.replace('_','/')} | {contrast} | app={fixed['application_viable']}, stability={fixed['stability_viable']} | app={old['application_viable']}, stability={old['stability_viable']} | {fixed['overflow_drop_total_postwarmup_including_drain']} / {old['overflow_drop_total_postwarmup_including_drain']} | {rel} |")
    lines+=['','The C3 comparison is a system comparison with different reservation profiles. The fixed-TAS vs scaled-TAS contrast holds the GCL family constant but changes all CBS reservations; it is not a single-port causal effect. TAS vs noTAS with the same fixed profile isolates the effect of the gate schedules for that cell.','',
      '## Flow metrics','', 'The following table reports packet-level metrics for every flow/receptor. Camera image-completion metrics are separate; missing images remain included in the image miss ratio. Full precision and all receiver records are in `pilot_results.json`.','',
      '| Cell | Treatment | Flow | Receiver | Offered | Received | Loss ratio | Misses incl loss | p99 packet (µs) | Max packet (µs) | Goodput | Image offered/completed | Image miss ratio | Image p99 (ms) | Gate |','|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|']
    for x in rows:
      for f in x['qos_by_flow_receiver']:
       def fmt(v,scale=1): return '—' if v is None else f'{v*scale:.4g}'
       image=f"{f['image_offered'] or 0}/{f['image_completed'] or 0}" if f['image_offered'] is not None else '—'
       lines.append(f"| {x['cell'].replace('_','/')} | {x['variant']} | {f['flow']} | {f['receiver']} | {f['offered_packets']} | {f['received_packets']} | {fmt(f['packet_loss_ratio'])} | {f['deadline_misses_received']} | {fmt(f['packet_p99_s'],1e6)} | {fmt(f['packet_max_s'],1e6)} | {fmt(f['goodput_payload_ratio'])} | {image} | {fmt(f['image_deadline_miss_ratio_including_missing'])} | {fmt(f['image_p99_s'],1e3)} | {f['receiver_gate']} |")
    lines+=['','## Queue, drop, and clock evidence','',
      'The JSON contains window-separated drops, queue occupancy (five-second bins, mean, peak, capacity and near-capacity fraction), synchronization samples and continuous-status limitations, gate configuration/runtime checks, credit vectors and retained-data manifests. Queue and packet conservation fields are preserved; do not infer a physical loss from a pending packet or an unexplained residual.','',
      '## Reservation cost','', 'The 24-row absolute profile table is `frozen_profile_table.csv`. Per-port reservation totals, physical line rate, fraction and headroom to 75% are in `pilot_results.json`. The four egresses nearest the limit are listed below.','', '| Port | L2 fixed CBS sum (Mb/s) | Physical (Mb/s) | Fraction | Headroom to 75% (Mb/s) |','|---|---:|---:|---:|---:|']
    caps=plan['expected_port_reservations']
    for e,v in sorted(caps.items(),key=lambda kv:kv[1]['cap_fraction'],reverse=True)[:8]: lines.append(f"| {e} | {v['idleSlope_sum_bps']/1e6:.3f} | {v['physical_rate_bps']/1e6:.0f} | {100*v['cap_fraction']:.2f}% | {v['headroom_to_75pct_bps']/1e6:.3f} |")
    lines+=['','## Targeted queue and flow findings','',
      '| Cell | Treatment | HPC/TC4 peak | CSW→Z3/TC4 peak | Z1 uplink/TC4 peak | Z2 uplink/TC4 peak | Z3 access/TC4 peak |','|---|---|---:|---:|---:|---:|---:|']
    qlabels=['HPC.eth[0]','CSW.eth[3]','Z1.ZSW.eth[0]','Z2.ZSW.eth[0]','Z3.ZSW.eth[7]']
    for x in rows:
      qmap={q['queue'].replace('ZonalIVN.','').split('.macLayer')[0]:q for q in x['queue_stability_by_target']}
      vals=[]
      for port in qlabels:
        q=qmap.get(port,{})
        vals.append('—' if q.get('peak_bits') is None else f"{q['peak_bits']/8:.0f} B / {q['capacity_bits']/8:.0f} B")
      lines.append(f"| {x['cell'].replace('_','/')} | {x['variant']} | "+' | '.join(vals)+' |')
    lines+=['',
      'All camera packets and images were delivered in these runs: F02/F03 had 937/938 complete images in L0/A0 and 1,875/1,875 in L1/A1; packet and image miss ratios were zero. F06/F07, F21/F22 and F13 also had offered=received and zero loss/misses. F13 delivered 75,000 packets in L0 and 150,000 in L1; its Z3 access TC4 peak was 2,048 bits (one 256-byte frame), with zero overflow and no sustained growth. The workload therefore does not demonstrate recovery of the historical 53-frame backlog; it demonstrates service without that backlog under these two lighter cells.','',
      'The maximum brake packet latency was about 77.88 µs with TAS and 31.42 µs with gates open, against the catalog 100 µs deadline. Thus the worst observed TAS brake margin was about 22.12 µs; brake gates pass, but the noTAS comparison is materially faster. CSW→Z3 TC4 peaks at 14,224 bits in L0 TAS and 38,576 bits in L1 TAS (26,400 bits in L1 noTAS), all below its 1 MiB queue capacity and with no overflow. Z1/Z2 uplink TC4 peaks are at most 24,144 bits against 1 MiB, with no drops.','']
    lines+=['','## Decision','',
      'Across the four runs, packet losses and queue overflow drops are zero, all per-flow application gates pass (including camera image completion, sensors, F21/F22 and brakes), and the P1 stability proxy passes with zero nonstable queues. The exact gate contract and observed gate-event checks pass for TAS; the noTAS cases pass the permanently-open/no-periodic-schedule contract. Direct native-tick synchronization samples also pass the 1 µs check, but continuous conformity is not established. Therefore the answer to “did every gate pass?” is: all measured application, stability, technical, GCL/noTAS and observed-sample gates pass; continuous synchronization remains unverified and is not called passed.','',
      'The fixed profile removes the Z1/Z2 uplink overflow and related deadline failures seen in the load-scaled D3 and C3 controls in these two cells. The two reservations-identical TAS/noTAS pairs both pass, while TAS increases some packet latencies (notably the brake paths from about 19–31 µs to about 77–78 µs at the maximum). This pilot cannot attribute the fixed-vs-scaled improvement to an individual queue because 22 reservation entries changed together.','',
      'The added configured CBS idleSlope summed over the network’s per-port/per-TC entries is about 2,509.270 Mb/s in L0/A0 and 1,881.953 Mb/s in L1/A1 versus the corresponding load-scaled D3 profile. This is a sum of configured per-hop reservations, not consumed bandwidth. No per-port 75% cap is exceeded; CSW.eth[3] is the tightest at 70.76%, leaving 42.393 Mb/s headroom.','',
      '## Scope and conclusion','',
      'Do not call this official C4 validation. The absolute policy is tested only in L0/A0 and L1/A1 at seed 41. No other seeds, loads, retuning, artificial backlog, or official C4 campaign were run. The answer to whether the fixed policy removed each observed failure is determined from the four application, loss and stability gates above; the sampled synchronization gate is reported independently, and continuous conformance remains unverified.','',
      '## Artifacts and provenance','', '- Protocol: `protocol.md`.','- Frozen 24-entry table: `results/frozen_profile_table.csv`.','- Per-run reports, traces and compression manifests: `results/runs/<execution_id>/`.','- Checkpoint: `results/checkpoint.json`; ledger: `results/runs.jsonl`.','- Version, source, executable, library, plugin, calendar and profile hashes: `results/manifest.json`.','- Reproduction: `python3 simulations/pilot/c4_fixed_L2_profile/run_fixed.py --resume` only if a run stopped; use the checkpoint before restarting.']
    (OUT/'analysis.md').write_text('\n'.join(lines)+'\n')
if __name__=='__main__': main()
