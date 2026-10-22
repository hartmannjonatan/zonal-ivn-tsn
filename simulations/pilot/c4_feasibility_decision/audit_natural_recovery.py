#!/usr/bin/env python3
"""Audit natural backlog episodes in preregistered CBS queues from change points."""
from __future__ import annotations
import csv, gzip, json, math
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
TARGETS={
    'D1_TAS_L2_A1_seed41': ['ZonalIVN.CSW.eth[3].macLayer.queue.queue[4]', 'ZonalIVN.Z3.ZSW.eth[7].macLayer.queue.queue[4]'],
    'D1_noTAS_L2_A1_seed41': ['ZonalIVN.CSW.eth[3].macLayer.queue.queue[4]', 'ZonalIVN.Z3.ZSW.eth[7].macLayer.queue.queue[4]'],
    'D2_TAS_L2_A1_seed41': ['ZonalIVN.CSW.eth[3].macLayer.queue.queue[4]', 'ZonalIVN.Z3.ZSW.eth[7].macLayer.queue.queue[4]'],
    'D2_noTAS_L2_A1_seed41': ['ZonalIVN.CSW.eth[3].macLayer.queue.queue[4]', 'ZonalIVN.Z3.ZSW.eth[7].macLayer.queue.queue[4]'],
    'D3_TAS_L2_A1_seed41': ['ZonalIVN.CSW.eth[3].macLayer.queue.queue[4]', 'ZonalIVN.Z3.ZSW.eth[7].macLayer.queue.queue[4]'],
    'D3_noTAS_L2_A1_seed41': ['ZonalIVN.CSW.eth[3].macLayer.queue.queue[4]', 'ZonalIVN.Z3.ZSW.eth[7].macLayer.queue.queue[4]'],
}
FRAME_BITS=2048
HORIZON=5.0

def path_for(logical):
    runs=ROOT/'simulations/pilot/c4_feasibility_decision/results/runs'
    run=runs/logical
    if logical.startswith('D1_TAS'):
        run=runs/(logical+'_technical_attempt_001')
    return run/('Joint_'+logical.removesuffix('_L2_A1_seed41')+'_L2_A1-0')

def episodes(directory, module, details_path):
    meta_path=Path(str(directory/'queue_occupancy_events.csv.gz')+'.meta.json.gz')
    with gzip.open(meta_path,'rt') as f: meta=json.load(f)
    entry=next(q for q in meta['queues'] if q['module']==module)
    qi=int(entry['queue_index'])
    count=recovered=0; baseline=0.0; q_at_1=0.0; q_at_31=0.0; active=None
    increments=[]; durations=[]; largest=[]
    fields=['start_s','end_s','baseline_bits','peak_bits','peak_s','increment_peak_bits','duration_s','recovered_within_horizon','right_censored']
    with gzip.open(details_path,'wt',newline='',compresslevel=6) as out:
      writer=csv.DictWriter(out,fieldnames=fields); writer.writeheader()
      with gzip.open(directory/'queue_occupancy_events.csv.gz','rt',newline='') as f:
        for row in csv.DictReader(f):
            if int(row['queue_index'])!=qi: continue
            t=float(row['timestamp_s']); v=float(row['occupancy_bits'])
            if t<1.0:
                baseline=v; q_at_1=v
            if t<31.0: q_at_31=v
            if t<1.0 or t>=31.0: continue
            if active is None:
                if v>baseline+FRAME_BITS: active={'start_s':t,'baseline_bits':baseline,'peak_bits':v,'peak_s':t}
            else:
                if v>active['peak_bits']: active['peak_bits']=v; active['peak_s']=t
                if v<=active['baseline_bits']+FRAME_BITS:
                    active.update(end_s=t,duration_s=t-active['start_s'])
                    active['increment_peak_bits']=active['peak_bits']-active['baseline_bits']
                    active['recovered_within_horizon']=active['duration_s']<=HORIZON
                    active['right_censored']=False
                    writer.writerow(active); count+=1
                    recovered+=int(active['recovered_within_horizon'])
                    increments.append(active['increment_peak_bits']); durations.append(active['duration_s'])
                    largest.append(active.copy()); largest=sorted(largest,key=lambda x:x['increment_peak_bits'],reverse=True)[:10]
                    active=None; baseline=v
      if active is not None:
        active.update(end_s='',duration_s=31.0-active['start_s'])
        active['increment_peak_bits']=active['peak_bits']-active['baseline_bits']
        active['recovered_within_horizon']=False; active['right_censored']=True
        writer.writerow(active); count+=1; increments.append(active['increment_peak_bits']); durations.append(active['duration_s'])
        largest.append(active.copy()); largest=sorted(largest,key=lambda x:x['increment_peak_bits'],reverse=True)[:10]
    def quantile(vals,q):
        if not vals:return None
        vals=sorted(vals); return vals[math.ceil(q*len(vals))-1]
    return {'queue':module,'capacity_bits':int(entry['capacity_bits']),'frame_threshold_bits':FRAME_BITS,
            'episode_count':count,'recovered_count':recovered,
            'increment_peak_bits':{'max':max(increments,default=None),'p50':quantile(increments,.50),'p95':quantile(increments,.95),'p99':quantile(increments,.99)},
            'duration_s':{'max':max(durations,default=None),'p50':quantile(durations,.50),'p95':quantile(durations,.95),'p99':quantile(durations,.99)},
            'largest_episodes':largest,'episode_details_gzip':details_path.name,
            'Q_1_minus_bits':q_at_1,'Q_31_minus_bits':q_at_31,
            'source_active_condition':'F13 is a periodic permanent source throughout [1,31); queue-level episode attribution is not flow-specific at CSW.eth[3].',
            'drops_scope':'D2 treatment-level technical report has zero confirmed queue drops; therefore episode drops=0 is global-run evidence, not packet-tagged episode attribution.'}

def main():
    out={'baseline_rule':'episode starts when occupancy rises above pre-crossing baseline + 2048 bits; ends when it returns to or below that level.',
         'recovery_horizon_s':HORIZON,'window_s':[1,31],'frame_bits':FRAME_BITS,'runs':{}}
    details_dir=ROOT/'simulations/pilot/c4_feasibility_decision/results'
    for logical,queues in TARGETS.items():
        d=path_for(logical);out['runs'][logical]={}
        for q in queues:
            slug=q.replace('ZonalIVN.','').replace('.','_')
            details=details_dir/f'natural_episodes_{logical}_{slug}.csv.gz'
            out['runs'][logical][q]=episodes(d,q,details)
    p=details_dir/'natural_recovery.json'
    p.write_text(json.dumps(out,indent=2)+'\n');print(p.relative_to(ROOT))

if __name__=='__main__':main()
