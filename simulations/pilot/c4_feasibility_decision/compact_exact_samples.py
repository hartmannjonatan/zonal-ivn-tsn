#!/usr/bin/env python3
"""Extract exact QoS vector samples before optional removal of full vector files.

The gzip output contains the original OMNeT++ vector headers and unchanged ETV
sample lines for the same measurement cohorts used by validate_c0.py. It can be
fed to an independent quantile/miss recalculation without loading the full
multi-gigabyte vector. Full vectors are removed only with --delete-after-verify.
"""
from __future__ import annotations
import argparse, csv, gzip, hashlib, heapq, json, math, os, re, tempfile, resource
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
SIM=ROOT/'simulations'
WARMUP=1.0; MEASUREMENT=30.0; DRAIN=.05

def sha_stream(stream):
    h=hashlib.sha256()
    for chunk in iter(lambda:stream.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()

def sha_path(path):
    with path.open('rb') as f:return sha_stream(f)

def main():
    resource.setrlimit(resource.RLIMIT_AS,(2*1024**3,2*1024**3))
    ap=argparse.ArgumentParser(); ap.add_argument('run_dir',type=Path); ap.add_argument('--delete-after-verify',action='store_true')
    a=ap.parse_args(); dest=a.run_dir.resolve()
    report=json.loads((dest/'pilot-result.json').read_text())
    vecs=list(dest.glob('*.vec.gz'))
    if not vecs: raise SystemExit('No compressed full vector found')
    if len(vecs)!=1: raise SystemExit(f'Expected one vector, found {len(vecs)}')
    source=vecs[0]; run_dir=dest/(source.name.split('-#')[0]+'-0')
    app_flow={}
    import sys
    sys.path.insert(0,str(ROOT/'scripts/run'))
    import validate_c0
    app_flow=validate_c0.load_app_flow_map()
    catalog={r['flow_id']:r for r in csv.DictReader((SIM/'zonal/traffic/flows.csv').open(newline=''))}
    expected={}; vector_meta={}; definitions={}; receivers={}
    for flow,metric in report['qos'].items():
        for node,r in metric['receivers'].items():
            lat=r.get('latency') or {}
            if lat.get('samples',0): receivers[(flow,node,'latency')]=r
            im=r.get('image_completion')
            if isinstance(im,dict) and im.get('samples',0): receivers[(flow,node,'imageCompletionLatency')]=r
    # The vector header block is first in the OMNeT++ file.
    with gzip.open(source,'rt',errors='replace') as f:
        for line in f:
            if line.startswith('vector '):
                p=line.rstrip('\n').split(' ',4)
                if len(p)!=5: continue
                vid=int(p[1]); module=p[2]; metric=p[3]
                match=re.fullmatch(r'(.*)\.app\[(\d+)\]',module)
                if not match or (match.group(1),int(match.group(2))) not in app_flow: continue
                flow=app_flow[match.group(1),int(match.group(2))]; node=match.group(1).removeprefix('ZonalIVN.')
                kind=metric.removesuffix(':vector')
                key=(flow,node,kind)
                if key in receivers:
                    definitions[vid]=line; r=receivers[key]
                    expected[vid]={'flow':flow,'receiver':node,'kind':kind,
                        'samples':int(r['latency']['samples'] if kind=='latency' else r['image_completion']['samples']),
                        'p99_s':float(r['latency']['p99_s'] if kind=='latency' else r['image_completion']['p99_s']),
                        'max_s':float(r['latency']['max_s'] if kind=='latency' else r['image_completion']['max_s']),
                        'deadline_misses':int(r['deadline_misses_received'] if kind=='latency' else r['image_completion']['deadline_misses_from_samples']),
                        'deadline_s':(float(r['image_completion']['deadline_s']) if kind=='imageCompletionLatency' else float(catalog[flow]['deadline_us'] or 0)/1e6)}
            elif line and line[0].isdigit(): break
    if not definitions: raise SystemExit('No receiver latency/image vectors mapped to the report')
    # Keep original ETV lines and maintain the same nearest-rank p99 tail as the validator.
    heaps={}; counts={vid:0 for vid in expected}; misses={vid:0 for vid in expected}; maxima={vid:None for vid in expected}
    for vid,m in expected.items(): heaps[vid]=[]
    fd,tmpname=tempfile.mkstemp(prefix='qos_samples.',suffix='.vec.gz.tmp',dir=dest); os.close(fd); tmp=Path(tmpname)
    src_hash=hashlib.sha256(); src_bytes=0
    try:
      with gzip.open(source,'rb') as raw, gzip.open(tmp,'wt',encoding='utf-8',compresslevel=6) as out:
        out.write('version 3\n# Exact receiver latency samples selected from the original full vector.\n')
        for line in definitions.values(): out.write(line)
        for bline in raw:
            src_hash.update(bline); src_bytes+=len(bline)
            try: line=bline.decode('utf-8')
            except UnicodeDecodeError: continue
            p=line.split()
            if len(p)!=4 or not p[0].isdigit(): continue
            vid=int(p[0]); meta=expected.get(vid)
            if meta is None: continue
            try: simtime=float(p[2]); value=float(p[3])
            except ValueError: continue
            origin=simtime-value
            if meta['kind']=='latency':
                if not (WARMUP-1e-12 <= origin < WARMUP+MEASUREMENT and simtime < WARMUP+MEASUREMENT+DRAIN): continue
            else:
                if not (WARMUP-1e-12 <= origin < WARMUP+MEASUREMENT and simtime < WARMUP+MEASUREMENT+DRAIN): continue
            out.write(line)
            counts[vid]+=1
            if meta['deadline_s']>0 and value>float(meta['deadline_s']): misses[vid]+=1
            maxima[vid]=value if maxima[vid] is None else max(maxima[vid],value)
            heap=heaps[vid]; keep=max(1,math.floor(.01*meta['samples'])+1)
            if len(heap)<keep: heapq.heappush(heap,value)
            elif value>heap[0]: heapq.heapreplace(heap,value)
      # Verify the source and every sample population/summary before atomic publish.
      src_hash_hex=src_hash.hexdigest()
      if report.get('raw_vector_sha256') and src_hash_hex!=report['raw_vector_sha256']:
          raise RuntimeError('Decompressed vector hash differs from pilot result')
      checks=[]
      for vid,m in expected.items():
          p99=min(heaps[vid]) if counts[vid] else None
          ok=(counts[vid]==m['samples'] and maxima[vid] is not None and
              math.isclose(maxima[vid],m['max_s'],rel_tol=0,abs_tol=1e-12) and
              p99 is not None and math.isclose(p99,m['p99_s'],rel_tol=0,abs_tol=1e-12))
          ok=ok and misses[vid]==m['deadline_misses']
          checks.append({'vector_id':vid,**m,'observed_samples':counts[vid],'observed_p99_s':p99,
                         'observed_max_s':maxima[vid],'observed_deadline_misses':misses[vid],'verified':ok})
      if not all(x['verified'] for x in checks):
          print(json.dumps({'failed_sample_checks':[x for x in checks if not x['verified']]},indent=2))
          raise RuntimeError('Exact sample cross-check failed; full vector retained')
      os.replace(tmp,dest/'qos_samples.vec.gz')
      outpath=dest/'qos_samples.vec.gz'; out_hash=sha_path(outpath)
      meta={'source_full_vector':source.name,'source_uncompressed_sha256':src_hash_hex,'source_uncompressed_bytes':src_bytes,
          'source_gzip_sha256':sha_path(source),'compact_sample_file':outpath.name,
          'compact_gzip_sha256':out_hash,'method':'original ETV vector sample lines filtered by the same CreationTime cohort [1,31) and drain end as validate_c0.py; original numerical text preserved',
          'nearest_rank_method':'minimum of the largest floor(0.01*n)+1 values, matching validate_c0.py',
          'checks':checks,'all_verified':True,'full_vector_removed':False}
      (dest/'qos_samples_manifest.json').write_text(json.dumps(meta,indent=2)+'\n')
      if a.delete_after_verify:
          # Confirm the compressed source still decompresses to the validated hash before removal.
          with gzip.open(source,'rb') as f:
              if sha_stream(f)!=src_hash_hex: raise RuntimeError('Full vector changed before removal')
          source.unlink(); meta['full_vector_removed']=True
          (dest/'qos_samples_manifest.json').write_text(json.dumps(meta,indent=2)+'\n')
      print(json.dumps({'run':dest.name,'samples_file_bytes':outpath.stat().st_size,
          'full_vector_bytes':source.stat().st_size if source.exists() else None,'removed':meta['full_vector_removed'],
          'all_verified':meta['all_verified'],'metrics':len(checks)},indent=2))
    finally:
      if tmp.exists(): tmp.unlink()
if __name__=='__main__': main()
