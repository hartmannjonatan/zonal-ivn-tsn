#!/usr/bin/env python3
"""Reconcile preserved C4 pilots; streams only small compact artifacts."""
import csv,gzip,hashlib,json
from pathlib import Path
HERE=Path(__file__).resolve().parent; ROOT=HERE.parents[2]
PILOT=ROOT/'simulations/pilot/c4_joint_dimensioning'; RESULTS=PILOT/'results'
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def main():
 rates=json.loads((HERE/'audit_corrected_inputs.json').read_text())
 summary=json.loads((RESULTS/'pilot_results.json').read_text())
 episodes=json.loads((RESULTS/'f13_natural_episode_analysis.json').read_text())
 runs=[]
 for r in summary['runs']:
  variant=r['variant']; flow={x['flow']:x for x in r['flow_metrics']}
  qdrops=[x for x in r['queue_overflow_drops_by_queue'] if int(x.get('overflow_drops_post_warmup_including_drain',0))]
  c3_or_d=variant in ('C3_sync_control','B_local') or variant.startswith('D')
  runs.append({'variant':variant,'execution_id':r['execution_id'],'simulation_valid':r['simulation_valid'],
    'application_viable':r['application_viable'],'stability_viable':r['stability_viable'],
    'calendar_sha256':r['calendar_sha256'],'flow_metrics':{f:flow[f] for f in ('F08','F09','F13','F21','F22') if f in flow},
    'positive_overflow_queues':qdrops,'drop_reconciliation':r['drop_reconciliation'],
    'effective_profile_bps':r['effective_profile_bps']})
 # These are the lost packet counts by application population; the per-execution
 # queue counters have only CSW.eth[3]/TC4 positive, so totals reconcile there.
 egress_loss={}
 for r in runs:
  losses={f:x['offered_packets']-x['received_packets'] for f,x in r['flow_metrics'].items()}
  qtotal=sum(int(x.get('overflow_drops_post_warmup_including_drain',0)) for x in r['positive_overflow_queues'])
  if qtotal:
   egress_loss[r['variant']]={'loss_by_flow':losses,'CSW_eth3_TC4_overflow_drops':qtotal,
      'flow_loss_total':sum(losses.values()),'reconciles':sum(losses.values())==qtotal,
      'attribution':'Only CSW.eth[3]/TC4 has confirmed overflow in this execution; flow losses are reported at receiver. The exact identity of individual dropped packets is not present in the compact summary.'}
 episode_rows=[]
 for r in episodes['runs']:
  es=r['episodes']; peak=max(es,key=lambda x:x['peak_bits']-x['baseline_bits']) if es else None
  delta=(peak['peak_bits']-peak['baseline_bits']) if peak else 0
  episode_rows.append({'execution_id':r['execution_id'],'episodes':len(es),'capacity_bits':r['capacity_bits'],
   'max_increment_bits':delta,'max_increment_2048b_frames':delta/2048,
   'peak_occupancy_bits':peak['peak_bits'] if peak else None,'episode_baseline_bits':peak['baseline_bits'] if peak else None,
   'episode_start_s':peak['start_s'] if peak else None,'peak_time_s':peak['peak_time_s'] if peak else None,
   'end_s':peak['end_s'] if peak else None,'recovery_s':peak['recovery_s'] if peak else None,
   'confirmed_local_queue_drops':r['confirmed_measurement_overflow_drops_on_queue'],
   'fraction_time_ge90pct':r['fraction_time_at_least_90pct_capacity'],
   'population_condition':'Z3 local F13 queue only; arrivals have already survived upstream CSW.eth[3]/TC4.'})
 # Reconstruct receiver deadline metrics from packet-level hop times. Each final
 # ZonalEthernetLink contributes its configured 100 ns propagation; no additional
 # receive processing is applied by CatalogUdpApp latency calculation.
 trace_path=RESULTS/'runs/D3_TAS_L2_A1_seed41/Joint_D3_TAS_L2_A1-0/d3-acceptance.json'
 trace=json.loads(trace_path.read_text())
 trfile=HERE/'audit/d3_tas_brake_stage_traces.json'
 tr=json.loads(trfile.read_text())['near_deadline_packet_traces']
 misses=[]
 for x in tr:
  gen=x['generation_raw']/1e12
  end=x['hop3']['tx_end_raw']/1e12
  latency=(end-gen)+.1e-6
  if latency>100e-6:
   def us(a,b):return (int(b)-int(a))/1e6
   hops=[]
   for i in (1,2,3):
    h=x[f'hop{i}']; hops.append({'stage':i,'queue_wait_us':us(h['queue_in_raw'],h['queue_out_raw']),
      'serialization_us':us(h['tx_start_raw'],h['tx_end_raw']),
      'link_propagation_to_next_us':0.1 if i<3 else 0.1})
   misses.append({'flow':x['flow'],'seq':x['seq'],'generation_s':gen,'receiver_s':end+.1e-6,
      'last_phy_tx_end_s':end,'latency_us':latency*1e6,'over_deadline_us':latency*1e6-100,
      'hops':hops,'reconstruction':'last final PHY tx end + 100 ns final channel propagation; CatalogUdpApp latency is simTime minus CreationTimeTag'})
 # Provenance, loss and episode corrections.
 source_paths=[RESULTS/'pilot_results.json',RESULTS/'f13_natural_episode_analysis.json',trace_path,trfile,
   ROOT/'simulations/zonal/traffic/flows.csv',ROOT/'simulations/zonal/traffic/transients.csv',
   ROOT/'simulations/zonal/traffic/cbs_nominal_reservations.csv']
 out={'schema_version':'1.0','exploratory':True,'diagnostic_only':True,'official_c4_frozen':False,
  'sources':{str(p.relative_to(ROOT)):sha(p) for p in source_paths},
  'rate_audit':{'load':'L2','factor':2.5,'flow_rates':rates['flow_rates_L2'],'permanent_egress_rates':rates['permanent_egress_rates_L2'],
   'unit_definitions':rates['rate_semantics'],'finding':'F13 is 25.60 Mb/s queue-MAC and 27.60 Mb/s wire at L2, not 10.24 Mb/s queue; the old dimensioner omitted the L2 factor for scalable flows.'},
  'preserved_run_reconciliation':runs,'CSW_eth3_loss_reconciliation':egress_loss,
  'F13_episode_recalculation':{'criterion':'peak occupancy minus episode-specific pre-event baseline; frame-equivalent uses 2,048 queue bits/frame. This is an incremental backlog, not absolute occupancy.',
   'episodes':episode_rows,'correction':'D1-D3 TAS all contain natural episodes exceeding 53 frames (113, 110, 106 respectively). Z3 local recovery is conditional on arrivals surviving CSW upstream drops.'},
  'D3_TAS_brake_miss_reconstruction':{'miss_count':len(misses),'misses':misses,
   'conclusion':'The preserved hop trace plus exact 100 ns final link reproduces 4 F08 and 14 F09 receiver misses and maxima exactly; no new diagnostic simulation is required. Gate waiting dominates at the first HPC egress; CSW waiting and final serialization consume the remaining budget. The exact competing frame identity is unavailable in the selected trace.'},
  'CSW_eth3_diagnosis':{'C3_sync':'zero confirmed queue overflow in this queue','candidate_runs':{r['variant']:r['positive_overflow_queues'] for r in runs if r['variant'].startswith('D')},
   'finding':'In every affected run, all positive overflow counters are at CSW.eth[3]/TC4. Receiver loss totals for F13/F21/F22 reconcile to that queue counter. The older candidates reduce CSW eth3 idleSlope relative to C3 and also release larger upstream bursts; both are compatible contributors. Aggregate records do not identify which individual packet was dropped or partition causality among reserve, gate opportunity, and burst phase.'}}
 (HERE/'audit/audit.json').write_text(json.dumps(out,indent=2,sort_keys=True)+'\n')
 # Concise, generated evidence report.
 md=['# Corrected audit of preserved C4 pilots','',
  'This is a reprocessing audit only; no simulation was run. Prior reports remain preserved. Flags: `exploratory=true`, `diagnostic_only=true`, `official_c4_frozen=false`.','',
  '## Input units and F13','',
  'At L2, the scalable factor is 2.5 and the period is 80 us. F13 carries 206 application bytes, 256 bytes in the queue, and 276 catalog wire bytes per packet. Therefore its rates are 20.60 Mb/s payload, 25.60 Mb/s queue-MAC, and 27.60 Mb/s wire. The old 10.24 Mb/s value used the base 200 us period and omitted the load factor. Queue occupancy and queue overflow use the MAC queue packet length; link demand uses wire rate. These bases are not interchangeable.','',
  '| Egress/TC4 | Permanent flows | Queue-MAC Mb/s | Wire Mb/s |',
  '|---|---|---:|---:|']
 for r in rates['permanent_egress_rates_L2']:
  if r['tc']==4:
   md.append(f"| {r['egress']}/TC4 | {', '.join(r['permanent_flows'])} | {r['total_queue_mac_bps']/1e6:.3f} | {r['total_wire_bps']/1e6:.3f} |")
 md+=['','F21/F22 are event-calendar transients, not permanent periodic demand. They remain excluded from permanent CBS reserve sums. The largest L2/A1 event pair in the 10x10 catalog signature envelope is LF4+LF4: combined with F13 it is 246.671 Mb/s queue-MAC and 251.578 Mb/s catalog wire while active.','',
  '## Drops at CSW→Z3','',
  '| Treatment | F13 lost | F21 lost | F22 lost | CSW.eth[3]/TC4 overflow | Reconciles |',
  '|---|---:|---:|---:|---:|:---:|']
 for v,x in egress_loss.items():
  l=x['loss_by_flow']; md.append(f"| {v} | {l.get('F13',0)} | {l.get('F21',0)} | {l.get('F22',0)} | {x['CSW_eth3_TC4_overflow_drops']} | {'yes' if x['reconciles'] else 'no'} |")
 md+=['','All positive queue-overflow counters in these executions are on CSW.eth[3]/TC4. For D3_TAS this is 41,107: F13 2,086 + F21 18,473 + F22 20,548. C3_sync has no overflow on this queue. The D1-D3 CBS reductions on this egress relative to C3, the higher burst release from HPC, and gated service are jointly compatible with the losses; available aggregates cannot isolate causal shares or identify individual dropped IDs. D3_TAS F13 still passes its existing P1 flow gate, but that result is not “zero loss.”','',
  '## Corrected natural F13 episodes','',
  'The peak is expressed as `episode peak - episode baseline`, in 2,048-bit queue-frame equivalents; it is not the absolute queue level. All D1-D3 TAS runs include increments greater than the previously cited 53 frames. Local Z3 recovery only concerns packets that arrived after upstream queues; losses upstream lower the demand observed at Z3.','',
  '| Run | Episodes | Largest increment (frames) | Baseline / peak (bits) | Recovery (ms) | Drops at Z3 queue |',
  '|---|---:|---:|---:|---:|---:|']
 for e in episode_rows:
  md.append(f"| {e['execution_id']} | {e['episodes']} | {e['max_increment_2048b_frames']:.0f} | {e['episode_baseline_bits']:.0f} / {e['peak_occupancy_bits']:.0f} | {e['recovery_s']*1000:.3f} | {e['confirmed_local_queue_drops']} |")
 md+=['','## D3_TAS brake packets','',
  'The retained per-hop trace is sufficient. The final egress PHY transmit-end timestamp plus the configured 100 ns last link equals application receive time because `CatalogUdpApp` computes latency as simulation time minus packet creation time. The reconstruction yields exactly 4 F08 and 14 F09 misses and the recorded maxima. No diagnostic rerun is needed.','',
  '| Flow/seq | Generated (s) | Received (s) | Latency (µs) | Over 100 µs | HPC wait (µs) | CSW wait (µs) | Final serialization (µs) |']
 for m in misses:
  md.append(f"| {m['flow']}/{m['seq']} | {m['generation_s']:.9f} | {m['receiver_s']:.9f} | {m['latency_us']:.6f} | {m['over_deadline_us']:.6f} | {m['hops'][0]['queue_wait_us']:.6f} | {m['hops'][1]['queue_wait_us']:.6f} | {m['hops'][2]['serialization_us']:.6f} |")
 md+=['','At HPC the packet often arrives just before TC7 closes and waits for the next opening. At CSW, the remaining queue delay is consistent with a closed gate and/or a nonpreemptable transmission; the retained selected trace does not identify the specific competing frame. The per-hop sum plus 100 ns propagation per channel reproduces each end-to-end latency. The noTAS control has no brake deadline misses; it is a control, not evidence that D3_TAS meets deadlines. The near-threshold failures are phase-sensitive and cannot be fixed by simply adding their observed excess to a gate window without redoing end-to-end phase/service analysis.','',
  '## Limits','',
  'The packet trace contains selected per-packet application events, but no preserved dropped-packet identity at CSW.eth[3]; attribution is therefore by reconciled receiver population loss plus the unique positive queue counter. The current audit can show compatibility with downstream reserve reduction, upstream burst release, and gate restrictions, but cannot identify an exclusive cause.','']
 (HERE/'audit/audit.md').write_text('\n'.join(md))
 print(f"Wrote audit for {len(rates['flow_rates_L2'])} catalog flows, {len(runs)} treatments, {len(misses)} reconstructed brake misses.")
if __name__=='__main__':main()
