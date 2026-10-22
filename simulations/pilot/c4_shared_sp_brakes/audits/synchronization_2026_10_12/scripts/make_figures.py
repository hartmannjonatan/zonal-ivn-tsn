#!/usr/bin/env python3
import csv,gzip,html,json,math
from pathlib import Path
A=Path(__file__).resolve().parents[1]
OUT=A/'figures'; OUT.mkdir(exist_ok=True)
def svg_open(title,w=1000,h=540):
 return [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">', '<rect width="100%" height="100%" fill="white"/>',f'<text x="{w/2}" y="30" text-anchor="middle" font-family="sans-serif" font-size="18">{html.escape(title)}</text>']
def axes(parts,x0,y0,w,h,xmin,xmax,ymin,ymax,xticks,yticks,xlabel,ylabel):
 for y in yticks:
  yy=y0+h-(y-ymin)/(ymax-ymin)*h; parts.append(f'<line x1="{x0}" y1="{yy:.2f}" x2="{x0+w}" y2="{yy:.2f}" stroke="#ddd"/>');parts.append(f'<text x="{x0-8}" y="{yy+4:.2f}" text-anchor="end" font-family="sans-serif" font-size="11">{y:g}</text>')
 for x in xticks:
  xx=x0+(x-xmin)/(xmax-xmin)*w;parts.append(f'<line x1="{xx:.2f}" y1="{y0}" x2="{xx:.2f}" y2="{y0+h}" stroke="#eee"/>');parts.append(f'<text x="{xx:.2f}" y="{y0+h+18}" text-anchor="middle" font-family="sans-serif" font-size="11">{x:g}</text>')
 parts.append(f'<rect x="{x0}" y="{y0}" width="{w}" height="{h}" fill="none" stroke="#444"/>')
 parts.append(f'<text x="{x0+w/2}" y="{y0+h+44}" text-anchor="middle" font-family="sans-serif" font-size="12">{html.escape(xlabel)}</text>')
 parts.append(f'<text x="18" y="{y0+h/2}" text-anchor="middle" font-family="sans-serif" font-size="12" transform="rotate(-90 18 {y0+h/2})">{html.escape(ylabel)}</text>')
def mapxy(x,y,x0,y0,w,h,xmin,xmax,ymin,ymax): return x0+(x-xmin)/(xmax-xmin)*w, y0+h-(y-ymin)/(ymax-ymin)*h
# 1ms full-period series for Z2, seed43.
rows=[]
with gzip.open(A/'data/periodic_offsets_1ms.csv.gz','rt') as f:
 for r in csv.DictReader(f):
  if r['node']=='Z2.ZSW.clock' and r['execution_id'] in ('C3sync_L2_A1_seed43','C4compensated_L2_A1_seed43'):
   rows.append((r['execution_id'],float(r['simtime_s']),float(r['offset_s'])*1e6))
p=svg_open('Seed 43, Z2 offset at the retained 1 ms samples (full 30 s)')
x0,y0,w,h=92,70,850,390; xmin,xmax=1,31;ymin,ymax=-0.08,0.08
axes(p,x0,y0,w,h,xmin,xmax,ymin,ymax,[1,5,10,15,20,25,30],[-.08,-.04,0,.04,.08],'Simulation time (s)','Offset to HPC (µs)')
for execid,color,label in [('C3sync_L2_A1_seed43','#1874b4','C3_sync'),('C4compensated_L2_A1_seed43','#d36b1e','C4_shared_SPbrakes')]:
 pts=[mapxy(t,v,x0,y0,w,h,xmin,xmax,ymin,ymax) for e,t,v in rows if e==execid]
 p.append('<polyline fill="none" stroke="'+color+'" stroke-width="1" points="'+' '.join(f'{x:.2f},{y:.2f}' for x,y in pts)+'"/>')
 xx=710 if label=='C3_sync' else 820;p.append(f'<line x1="{xx}" y1="48" x2="{xx+25}" y2="48" stroke="{color}" stroke-width="3"/><text x="{xx+30}" y="52" font-family="sans-serif" font-size="12">{label}</text>')
p.append('<text x="92" y="510" font-family="sans-serif" font-size="11">All 30,000 periodic samples per node are within ±0.06 µs; this does not exclude between-event excursions.</text></svg>');(OUT/'periodic_offsets_seed43.svg').write_text('\n'.join(p))
# Direct technical probes, 1ms observer reads, all downstream clocks.
p=svg_open('Direct simultaneous IClock::getClockTime() probe, seed 43, [1,3) s')
x0,y0,w,h=92,70,850,390;xmin,xmax=1,3;ymin,ymax=-12,12
axes(p,x0,y0,w,h,xmin,xmax,ymin,ymax,[1,1.25,1.5,1.75,2,2.25,2.5,2.75,3],[-12,-8,-4,0,4,8,12],'Simulation time (s)','Offset to HPC (µs)')
colors={'CSW':'#1874b4','Z1.ZSW':'#d36b1e','Z2.ZSW':'#2a9d55','Z3.ZSW':'#9b59b6'}
for variant,filename,ls in [('C3_sync','C3sync_L2_A1_seed43/clock_audit.csv.gz',''),('C4_shared_SPbrakes','C4compensated_L2_A1_seed43/clock_audit.csv.gz','')]:
 path=A/'technical'/filename
 with gzip.open(path,'rt') as f: rr=list(csv.DictReader(f))
 for node,pref in [('CSW','csw'),('Z1.ZSW','z1'),('Z2.ZSW','z2'),('Z3.ZSW','z3')]:
  pts=[]
  for r in rr:
   if r['record_kind']=='periodic' and 1<=float(r['simtime_s'])<3:
    pts.append(mapxy(float(r['simtime_s']),(float(r[pref+'_clock_s'])-float(r['hpc_clock_s']))*1e6,x0,y0,w,h,xmin,xmax,ymin,ymax))
  p.append(f'<polyline fill="none" stroke="{colors[node]}" stroke-width="1" opacity="{0.75 if variant=="C3_sync" else 0.45}" points="'+' '.join(f'{x:.2f},{y:.2f}' for x,y in pts)+'"/>')
# unique legend: color=zone, line style by treatment
for i,(name,color) in enumerate(colors.items()):
 x=100+(i%2)*230; y=490+(i//2)*18;p.append(f'<line x1="{x}" y1="{y}" x2="{x+20}" y2="{y}" stroke="{color}" stroke-width="3"/><text x="{x+25}" y="{y+4}" font-family="sans-serif" font-size="11">{name}</text>')
p.append('<text x="600" y="490" font-family="sans-serif" font-size="11">C3_sync: solid; C4_shared_SPbrakes: lighter same-color line.</text><text x="92" y="530" font-family="sans-serif" font-size="11">Observed isolated samples reach 10 µs (C3_sync/Z1 at 1.801 s; C4 at 1.247 s). A 1 ms probe cannot determine excursion duration.</text></svg>');(OUT/'direct_clock_probe_seed43.svg').write_text('\n'.join(p))
# Legacy same-simtime emission maxima versus periodic samples around saved peak times.
p=svg_open('Same-timestamp correction emissions behind the legacy millisecond maxima',1000,560)
x0,y0,w,h=120,75,800,390;xmin,xmax=-1.2,1.2;ymin,ymax=-0.05,2.7
axes(p,x0,y0,w,h,xmin,xmax,ymin,ymax,[-1,-.5,0,.5,1],[0,.5,1,1.5,2,2.5],'Time from legacy peak (ms)','Offset sample (ms)')
colors=['#1874b4','#d36b1e']
for idx,(run,peak_t,color,label) in enumerate([('C3sync_L2_A1_seed43',30.501115896,colors[0],'C3_sync Z2'),('C4compensated_L2_A1_seed43',30.876118483103,colors[1],'C4_shared Z2')]):
 pth=Path('/home/jonatan/Documentos/UFSC/IVN/zonal-ivn-tsn/simulations/pilot/c4_shared_sp_brakes/results/runs')/run/f'Pilot_{run.rsplit("_seed",1)[0]}-0/clock_offsets.csv.gz'
 with gzip.open(pth,'rt') as f:
  for r in csv.DictReader(f):
   if r['node']=='Z2.ZSW.clock' and abs(float(r['simtime_s'])-peak_t)<.0012:
    x=(float(r['simtime_s'])-peak_t)*1000;y=float(r['offset_s'])*1000
    xx,yy=mapxy(x,y,x0,y0,w,h,xmin,xmax,ymin,ymax);p.append(f'<circle cx="{xx:.2f}" cy="{yy:.2f}" r="3.4" fill="{color}" opacity=".75"/>')
 x=650;y=50+idx*18;p.append(f'<circle cx="{x}" cy="{y}" r="4" fill="{color}"/><text x="{x+10}" y="{y+4}" font-family="sans-serif" font-size="11">{label}</text>')
p.append('<text x="120" y="535" font-family="sans-serif" font-size="11">At the legacy peak time, three same-time values are near 0.02 µs and one is 2.489/2.519 ms; period samples before/after remain near zero.</text></svg>');(OUT/'legacy_peak_same_timestamp.svg').write_text('\n'.join(p))
print('wrote figures',*[x.name for x in OUT.glob('*.svg')])
