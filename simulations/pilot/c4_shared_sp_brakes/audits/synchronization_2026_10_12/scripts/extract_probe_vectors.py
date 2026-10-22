#!/usr/bin/env python3
import gzip,csv,json,sys
from pathlib import Path
src=Path(sys.argv[1]); out=Path(sys.argv[2]); out.parent.mkdir(parents=True,exist_ok=True)
want_nodes=('HPC','CSW','Z1.ZSW','Z2.ZSW','Z3.ZSW')
def sample(line):
 p=line.split()
 if len(p)>=4 and p[0].isdigit():
  try:return int(p[0]),int(p[1]),float(p[2]),float(p[3])
  except ValueError:return None
 return None
with src.open(errors='replace') as f:
 defs={}
 for line in f:
  if line.startswith('vector '):
   x=line.rstrip().split(' ',4)
   if len(x)==5:
    module,name=x[2],x[3]
    relevant=any(module.startswith('ZonalIVNClockAudit.'+n+'.clock') for n in want_nodes)
    if relevant and (name.startswith('timeChanged:') or name.startswith('oscillatorCompensationChanged:')) or ('.gptp' in module and any(k in name for k in ('gmRateRatio:','neighborRateRatio:','pdelay:'))):
     defs[int(x[1])]={'module':module,'name':name,'attrs':x[4]}
  elif line and line[0].isdigit(): break
with out.open('w',newline='') as raw:
 w=csv.writer(raw);w.writerow(['vector','module','name','event_number','simtime_s','value'])
 with src.open(errors='replace') as f:
  for line in f:
   p=sample(line)
   if p and p[0] in defs:
    vid,event,t,v=p;d=defs[vid]
    if 0<=t<=3.05:w.writerow([vid,d['module'],d['name'],event,format(t,'.12g'),format(v,'.15g')])
meta={'source_vec':str(src),'vector_defs':defs,'window_s':[0,3.05]}
out.with_suffix('.meta.json').write_text(json.dumps(meta,indent=2)+'\n')
with out.open('rb') as fi,gzip.open(str(out)+'.gz','wb',compresslevel=6) as fo:
 while b:=fi.read(1024*1024):fo.write(b)
out.unlink()
print(json.dumps({'vectors':len(defs),'file':str(out)+'.gz','bytes':Path(str(out)+'.gz').stat().st_size},indent=2))
