#!/usr/bin/env python3
"""Stream queue-bit demand from the preserved valid historical A005 CBS run."""
import csv, gzip, hashlib, json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
SOURCE=ROOT/'simulations/pilot/c4_gate_clock_reference/results/runs/A005_local_L2_A1_seed41_v1/Pilot_C4compensated_L2_A1-0/service_and_wire_events.csv.gz'
OUT=Path(__file__).resolve().parent/'historical_A005_service_demand.json'
WINDOW=(1.0,31.0)
EGRESSES=('HPC.eth[0]','CSW.eth[1]','CSW.eth[2]','CSW.eth[3]','Z3.ZSW.eth[7]')
STATS=('incomingPacketLengths:vector','outgoingPacketLengths:vector','droppedPacketLengthsQueueOverflow:vector')

def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()

totals={f'{e}/TC4':{s:0 for s in STATS} for e in EGRESSES}
with gzip.open(SOURCE,'rt',newline='') as stream:
    for row in csv.DictReader(stream):
        module=row.get('module','')
        if not any(f'.{e}.macLayer.queue.queue[4]' in module for e in EGRESSES): continue
        stat=row.get('statistic','')
        if stat not in STATS: continue
        try:t=float(row['simtime_s']); bits=int(float(row['value']))
        except (ValueError,KeyError): continue
        if not (WINDOW[0] <= t < WINDOW[1]): continue
        egress=next(e for e in EGRESSES if f'.{e}.macLayer.queue.queue[4]' in module)
        totals[f'{egress}/TC4'][stat]+=bits

result={'source_path':str(SOURCE.relative_to(ROOT)),'source_sha256':sha(SOURCE),
        'execution_id':'A005_local_L2_A1_seed41_v1','execution_classification':'historical valid CBS reference; executable hash unavailable',
        'window_s':{'start_inclusive':WINDOW[0],'end_exclusive':WINDOW[1]},
        'source_vector_units':'bits per packet sample; integrated by summation',
        'queue_bit_rates_bps':{},'queue_bit_totals':totals,
        'interpretation':'historical offered/served queue-bit rates; not a service guarantee or a new simulation'}
for key,values in totals.items():
    result['queue_bit_rates_bps'][key]={name:bits/(WINDOW[1]-WINDOW[0]) for name,bits in values.items()}
OUT.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
print(json.dumps({'output':str(OUT.relative_to(ROOT)),'source_sha256':result['source_sha256'],
                  'queue_bit_rates_bps':result['queue_bit_rates_bps']},indent=2,sort_keys=True))
