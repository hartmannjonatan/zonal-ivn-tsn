#!/usr/bin/env python3
"""Streaming extraction of brake packet stages from a preserved trace.

The trace has no application-reception event. This script reconstructs queue and
transmission stages only; it deliberately does not label final-TX completion as
application reception or infer deadline misses from it.
"""
import array, csv, gzip, json, sys
from pathlib import Path

def main(src: Path, dst: Path):
    N=310000
    fields={f:array.array('q',[-1])*(N*12) for f in (8,9)}
    idxs={
      (8,'queue_push_start','HPC.eth[0]'):0,(8,'queue_pulled_out','HPC.eth[0]'):1,
      (8,'phy_tx_start','HPC.eth[0]'):2,(8,'phy_tx_end','HPC.eth[0]'):3,
      (8,'queue_push_start','CSW.eth[1]'):4,(8,'queue_pulled_out','CSW.eth[1]'):5,
      (8,'phy_tx_start','CSW.eth[1]'):6,(8,'phy_tx_end','CSW.eth[1]'):7,
      (8,'queue_push_start','Z1.ZSW.eth[4]'):8,(8,'queue_pulled_out','Z1.ZSW.eth[4]'):9,
      (8,'phy_tx_start','Z1.ZSW.eth[4]'):10,(8,'phy_tx_end','Z1.ZSW.eth[4]'):11,
      (9,'queue_push_start','HPC.eth[0]'):0,(9,'queue_pulled_out','HPC.eth[0]'):1,
      (9,'phy_tx_start','HPC.eth[0]'):2,(9,'phy_tx_end','HPC.eth[0]'):3,
      (9,'queue_push_start','CSW.eth[2]'):4,(9,'queue_pulled_out','CSW.eth[2]'):5,
      (9,'phy_tx_start','CSW.eth[2]'):6,(9,'phy_tx_end','CSW.eth[2]'):7,
      (9,'queue_push_start','Z2.ZSW.eth[4]'):8,(9,'queue_pulled_out','Z2.ZSW.eth[4]'):9,
      (9,'phy_tx_start','Z2.ZSW.eth[4]'):10,(9,'phy_tx_end','Z2.ZSW.eth[4]'):11,
    }
    seen=0
    with gzip.open(src,'rt',newline='') as inp:
      reader=csv.DictReader(inp)
      for row in reader:
        fid=int(row['flow'])
        if fid not in fields: continue
        source=row['source'].removeprefix('ZonalIVN.')
        port=next((p for p in ('HPC.eth[0]','CSW.eth[1]','CSW.eth[2]','Z1.ZSW.eth[4]','Z2.ZSW.eth[4]') if source.startswith(p)),None)
        key=(fid,row['kind'],port)
        j=idxs.get(key)
        if j is None: continue
        seq=int(row['seq'])
        if 0<=seq<N:
          fields[fid][seq*12+j]=int(row['simtime_raw'])
        seen+=1
        if seen and seen%2_000_000==0: print(f'captured {seen:,} selected stage events',file=sys.stderr,flush=True)
    # Keep all in-measurement packets whose last-hop TX is within 3 us of the P1 deadline.
    result=[]
    for fid in (8,9):
      a=fields[fid]
      for seq in range(N):
        o=seq*12; gen=a[o]; end=a[o+11]
        if gen<0 or end<0 or not (1_000_000_000_000 <= gen < 31_000_000_000_000): continue
        tx_latency=end-gen
        if tx_latency>=97_000_000:
          result.append({'flow':f'F{fid:02d}','seq':seq,'generation_raw':gen,
            'hop1':{'queue_in_raw':a[o],'queue_out_raw':a[o+1],'tx_start_raw':a[o+2],'tx_end_raw':a[o+3]},
            'hop2':{'queue_in_raw':a[o+4],'queue_out_raw':a[o+5],'tx_start_raw':a[o+6],'tx_end_raw':a[o+7]},
            'hop3':{'queue_in_raw':a[o+8],'queue_out_raw':a[o+9],'tx_start_raw':a[o+10],'tx_end_raw':a[o+11]},
            'generation_to_last_phy_tx_end_us':tx_latency/1e6,
            'application_receive_raw':'not_recorded_in_source_trace'})
    out={'source':str(src),'selected_stage_events':seen,'raw_time_unit':'simtime_t.raw(); 1 ps per tick in this build',
         'interpretation':'No application reception timestamp is present; last PHY TX end is not treated as delivery.',
         'near_deadline_packet_traces':result}
    dst.parent.mkdir(parents=True,exist_ok=True)
    dst.write_text(json.dumps(out,indent=2)+'\n')
    print(f'output={dst} selected_events={seen} near_deadline={len(result)}',flush=True)
if __name__=='__main__': main(Path(sys.argv[1]),Path(sys.argv[2]))
