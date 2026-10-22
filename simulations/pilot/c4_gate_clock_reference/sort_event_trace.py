#!/usr/bin/env python3
"""Stable external sort of compact queue/gate events by OMNeT++ event number."""
import gzip
import hashlib
import json
import shutil
import subprocess
import csv
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "results"
RUNS = OUT / "runs"
VARIANTS = ("A005_local", "A005_ideal_all", "A005_ideal_HPC")
TEMP = OUT / "sort_tmp"
TEMP.mkdir(parents=True, exist_ok=True)

def sha256(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda:f.read(1024*1024),b""): h.update(block)
    return h.hexdigest()

for variant in VARIANTS:
    run=RUNS/f"{variant}_L2_A1_seed41_v1"
    event=run/"Pilot_C4compensated_L2_A1-0"/"gate_clock_queue_events.csv.gz"
    metadata=run/"Pilot_C4compensated_L2_A1-0"/"gate_clock_queue_events.json"
    if not event.is_file() or not metadata.is_file():
        raise RuntimeError(f"Missing compact events or metadata for {variant}")
    meta=json.loads(metadata.read_text())
    if meta.get("event_number_sorted"):
        print(f"already sorted: {variant}",flush=True); continue
    original_sha=sha256(event)
    tmp=event.with_suffix(".csv.gz.sorting")
    with tmp.open("wb") as dst:
        decompressor=subprocess.Popen(["gzip","-cd",str(event)],stdout=subprocess.PIPE)
        sorter=subprocess.Popen(["sort","--stable","--parallel=1","--buffer-size=512M","-T",str(TEMP),"-t,","-k3,3n","-k1,1n"],stdin=decompressor.stdout,stdout=subprocess.PIPE)
        decompressor.stdout.close()
        compressor=subprocess.Popen(["gzip","-c"],stdin=sorter.stdout,stdout=dst)
        sorter.stdout.close()
        rc_comp=compressor.wait(); rc_sort=sorter.wait(); rc_dec=decompressor.wait()
    if (rc_dec,rc_sort,rc_comp)!=(0,0,0):
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"External sort failed for {variant}: gzip={rc_dec}, sort={rc_sort}, gzipout={rc_comp}")
    # Verify exact row count, sorted event numbers, stable tie order, and header.
    count=0; previous_event=-1; previous_order=-1
    with gzip.open(tmp,"rt",newline="",encoding="utf-8") as f:
        header=f.readline().strip()
        if header!="record_order,vector_id,event_number,simtime_s,value,module,statistic":
            raise RuntimeError(f"Unexpected event CSV header for {variant}: {header}")
        for p in csv.reader(f):
            if len(p)!=7: raise RuntimeError(f"Malformed row in {variant}")
            order,event_no=int(p[0]),int(p[2])
            if event_no<previous_event or (event_no==previous_event and order<previous_order):
                raise RuntimeError(f"Unsorted event order in {variant} at row {count}")
            previous_event,previous_order=event_no,order
            count+=1
    if count!=int(meta["records"]):
        raise RuntimeError(f"Record count changed for {variant}: expected {meta['records']}, got {count}")
    sorted_sha=sha256(tmp)
    tmp.replace(event)
    meta["original_event_trace_sha256_before_sort"]=original_sha
    meta["event_number_sorted"]=True
    meta["sort_key"]="numeric event_number, then original .vec line record_order"
    meta["sort_algorithm"]="GNU sort --stable --parallel=1 --buffer-size=512MiB; external temporary runs"
    meta["sorted_records"]=count
    meta["sorted_event_trace_sha256"]=sorted_sha
    metadata.write_text(json.dumps(meta,indent=2,ensure_ascii=False)+"\n")
    print(f"sorted {variant}: {count:,} records; sha256={sorted_sha}; source retained in record_order field",flush=True)

shutil.rmtree(TEMP)
print("All compact traces are chronologically ordered by OMNeT++ event number.")
