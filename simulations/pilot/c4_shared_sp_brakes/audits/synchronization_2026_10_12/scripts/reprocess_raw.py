#!/usr/bin/env python3
"""Order-preserving audit of retained INET timeChanged vectors."""
import gzip, csv, json, math, statistics, sys
from pathlib import Path
from collections import defaultdict
src=Path(sys.argv[1]); out=Path(sys.argv[2]); out.mkdir(parents=True,exist_ok=True)
ids={0:'HPC',118:'CSW',353:'Z1.ZSW',1221:'Z2.ZSW',2089:'Z3.ZSW'}
series={name:[] for name in ids.values()}
with gzip.open(src,'rt',errors='replace') as f:
    for line in f:
        if not line or not line[0].isdigit(): continue
        p=line.split()
        if len(p)<4: continue
        try: vid=int(p[0])
        except ValueError: continue
        node=ids.get(vid)
        if node:
            try: series[node].append((int(p[1]),float(p[2]),float(p[3])))
            except ValueError: pass
# sort by simulation time then the globally recorded event number (not clock value)
for node in series: series[node].sort(key=lambda r:(r[1],r[0]))
with gzip.open(out/'ordered_timechanged_seed41.csv.gz','wt',newline='') as f:
    w=csv.writer(f); w.writerow(['node','event_number','simtime_s','emitted_clock_time_s'])
    for node,rows in series.items():
        for ev,t,v in rows: w.writerow([node,ev,format(t,'.12g'),format(v,'.15g')])
# preserve same-timestamp ordered emission groups; first=pre-state emission, last=post-state emission when correction
summary={}
for node,rows in series.items():
    groups=[]
    for ev,t,v in rows:
        if groups and groups[-1][0]==t: groups[-1][1].append((ev,v))
        else: groups.append([t,[(ev,v)]])
    dup=[(t,x) for t,x in groups if len(x)>1]
    summary[node]={'rows':len(rows),'unique_timestamps':len(groups),'timestamps_with_multiple_emissions':len(dup),
      'multi_emission_examples':[{'simtime_s':t,'events':x[:6],'delta_last_minus_first_s':x[-1][1]-x[0][1]} for t,x in dup[:12] ],
      'first_sample':rows[0] if rows else None,'last_sample':rows[-1] if rows else None}
# Piecewise function represented by each timestamp's left-limit (first event) and right-limit (last event).
def grouped(node):
    res=[]
    for ev,t,v in series[node]:
        if res and res[-1][0]==t: res[-1][2]=v; res[-1][3]=ev
        else: res.append([t,v,v,ev]) # t, left, right, last event
    # first event preserves left-limit, last preserves right-limit
    return res
G={n:grouped(n) for n in series}
def value_at(node,t,side='right'):
    a=G[node]
    lo,hi=0,len(a)
    while lo<hi:
        m=(lo+hi)//2
        if a[m][0]<t: lo=m+1
        else: hi=m
    i=lo
    if i<len(a) and a[i][0]==t: return a[i][1] if side=='left' else a[i][2]
    if i==0 or i>=len(a): return None
    ta,_,va,_=a[i-1]; tb,vb,_,_=a[i]
    if tb==ta: return None
    return va+(vb-va)*(t-ta)/(tb-ta)
# Build offset event list over measurement window. Evaluate right and left limits at every clock event,
# plus 1 ms same-time grid samples. Interpolation never spans a correction jump.
start,end=1.0,31.0
metrics={}
for node in ('CSW','Z1.ZSW','Z2.ZSW','Z3.ZSW'):
    points=[]
    ts=sorted({t for n in G for t,_,_,_ in G[n] if start<=t<end})
    for t in ts:
        for side in ('left','right'):
            x=value_at(node,t,side); h=value_at('HPC',t,side)
            if x is not None and h is not None: points.append((t,side,x-h))
    vals=[abs(x[2]) for x in points]
    # grid at 1ms boundaries, post-event convention. Include t=1, then 1ms until <31.
    grid=[]
    k=1000
    while k<31000:
        t=k/1000
        x=value_at(node,t,'right'); h=value_at('HPC',t,'right')
        if x is not None and h is not None: grid.append((t,x-h))
        k+=1
    gv=sorted(abs(o) for _,o in grid)
    p99=gv[math.ceil(.99*len(gv))-1] if gv else None
    maxp=max(points,key=lambda x:abs(x[2])) if points else None
    atwarm=(value_at(node,1.0,'right')-value_at('HPC',1.0,'right')) if value_at(node,1.0,'right') is not None else None
    above=sum(abs(o)>1e-6 for _,o in grid)
    metrics[node]={'offset_at_1s_s':atwarm,'max_abs_offset_event_sided_s':abs(maxp[2]) if maxp else None,
      'max_event_sided':{'simtime_s':maxp[0],'side':maxp[1],'signed_offset_s':maxp[2]} if maxp else None,
      'abs_grid_p50_s':gv[math.ceil(.50*len(gv))-1] if gv else None,'abs_grid_p95_s':gv[math.ceil(.95*len(gv))-1] if gv else None,
      'abs_grid_p99_s':p99,'abs_grid_max_s':max(gv) if gv else None,'grid_samples':len(grid),'grid_above_1us':above,
      'duration_above_1us_piecewise_s':None,
      'resolution_s':'1 ms periodic clock emission; event-side jumps additionally evaluated from preserved event-number order',
      'note':'duration calculation not yet integrated; event-side peak includes both limits at discontinuities'}
# duration above threshold over piecewise intervals, using end left limits and start right limits; zero-measure jumps excluded
for node in metrics:
    events=sorted({t for n in G for t,_,_,_ in G[n] if start<=t<=end})
    duration=0.
    for ta,tb in zip(events,events[1:]):
        oa=value_at(node,ta,'right')-value_at('HPC',ta,'right')
        ob=value_at(node,tb,'left')-value_at('HPC',tb,'left')
        if oa is None or ob is None: continue
        dt=tb-ta; aa=abs(oa)-1e-6; ab=abs(ob)-1e-6
        if aa>0 and ab>0: duration+=dt
        elif aa>0>=ab: duration+=dt*aa/(aa-ab)
        elif aa<=0<ab: duration+=dt*ab/(ab-aa)
    metrics[node]['duration_above_1us_piecewise_s']=duration
result={'source_vec':str(src),'vector_ids':ids,'series':summary,'offsets':metrics,'method':'event-number-preserving; tie groups retain first emission as left-limit and last as post-event state; continuous interpolation only between neighboring timestamps using left/right appropriate limits; no extrapolation outside sampled window'}
(out/'raw_reprocess_seed41.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({'series':summary,'offsets':metrics},indent=2))
