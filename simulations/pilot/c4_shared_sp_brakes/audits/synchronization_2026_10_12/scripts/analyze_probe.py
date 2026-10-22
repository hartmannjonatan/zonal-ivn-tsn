#!/usr/bin/env python3
import csv,gzip,json,math,sys
from pathlib import Path
nodes={'CSW':'csw','Z1.ZSW':'z1','Z2.ZSW':'z2','Z3.ZSW':'z3'}
node_order=['HPC','CSW','Z1.ZSW','Z2.ZSW','Z3.ZSW']
def quantile(a,p): return sorted(a)[max(0,math.ceil(p*len(a))-1)] if a else None
for arg in sys.argv[1:]:
 p=Path(arg); op=gzip.open if str(p).endswith('.gz') else open
 with op(p,'rt') as f: rows=list(csv.DictReader(f))
 begin,end=1.,3.; result={'trace':str(p),'trace_rows':len(rows),'measurement_slice_s':[begin,end], 'nodes':{},'compensation_ppm':{},'signal_propagation':{}}
 for node,pref in nodes.items():
  base=f'ZonalIVNClockAudit.{node}.clock'
  periodic=[r for r in rows if r['record_kind']=='periodic' and begin<=float(r['simtime_s'])<end]
  direct=[r for r in rows if r['record_kind']=='signal' and r['emitter']==base and r['signal']=='timeChanged' and begin<=float(r['simtime_s'])<end]
  def one(rs,kind):
   vals=[(float(r[pref+'_clock_s'])-float(r['hpc_clock_s']),float(r['simtime_s']),r) for r in rs]
   av=[abs(x[0]) for x in vals]; peak=max(vals,key=lambda x:abs(x[0])) if vals else (None,None,None)
   return {'population':kind,'count':len(vals),'p50_abs_s':quantile(av,.5),'p95_abs_s':quantile(av,.95),'p99_abs_s':quantile(av,.99),
    'max_abs_s':max(av) if av else None,'max_signed_s':peak[0],'max_time_s':peak[1], 'samples_abs_over_1us':sum(x>1e-6 for x in av),
    'distinct_times_abs_over_1us':len({round(t,12) for v,t,_ in vals if abs(v)>1e-6}),
    'signal_value_matches_getClockTime_count':sum(abs(float(r['signal_value_s'])-float(r[pref+'_clock_s']))<=1e-12 for r in rs),
    'signal_value_checked_count':len(rs)}
  result['nodes'][node]={'observer_periodic_samples':one(periodic,'audit module samples, 1ms'),
    'direct_timeChanged_callbacks':one(direct,'callbacks from this node SettableClock, event ordered'),
    'free_clock_relative_at_near_1_and_2_999s':None}
  def near(t): return min(periodic,key=lambda r:abs(float(r['simtime_s'])-t))
  a,b=near(1.0),near(2.999)
  free_a=float(a[pref+'_free_s'])-float(a['hpc_free_s']); free_b=float(b[pref+'_free_s'])-float(b['hpc_free_s'])
  result['nodes'][node]['free_clock_relative_at_near_1_and_2_999s']={'near_1s_s':free_a,'near_2_999s_s':free_b,'change_s':free_b-free_a}
  # event emissions at repeated same timestamp; these are ordered callback snapshots, duration is not inferred from points.
  by={}
  for r in direct: by.setdefault(r['simtime_s'],[]).append(r)
  result['nodes'][node]['same_timestamp_direct_callback_groups']=[{'simtime_s':t,'count':len(v),'values_s':[float(x['signal_value_s']) for x in v],
   'direct_offsets_s':[(float(x[pref+'_clock_s'])-float(x['hpc_clock_s'])) for x in v]} for t,v in by.items() if len(v)>1][:20]
 for node in nodes:
  base=f'ZonalIVNClockAudit.{node}.clock'
  vals=[(float(r['simtime_s']),float(r['signal_value_s'])) for r in rows if r['record_kind']=='signal' and r['emitter']==base and r['signal']=='oscillatorCompensationChanged' and begin<=float(r['simtime_s'])<end]
  result['compensation_ppm'][node]={'count':len(vals),'unit':'ppm','min_ppm':min((v for _,v in vals),default=None),'max_ppm':max((v for _,v in vals),default=None),'last_ppm':vals[-1][1] if vals else None,'timeline_s_ppm':vals}
 result['signal_propagation']={'underlying_clock_timeChanged_rows_seen_by_listener_on_parent':sum(r['record_kind']=='signal' and r['signal']=='timeChanged' and r['emitter'].endswith('.clock.underlyingClock') for r in rows),
  'meaning':'A cComponent listener subscribed on SettableClock receives bubbled child signal events too, identifiable by source path. INET ClockBase @statistic uses localSignal(timeChanged), so these child events are excluded from that vector.'}
 out=p.parent/'probe_summary.json'; out.write_text(json.dumps(result,indent=2)+'\n')
 print(json.dumps({'summary':str(out),'nodes':{n:{'periodic_max_us':v['observer_periodic_samples']['max_abs_s']*1e6,'periodic_n_above1':v['observer_periodic_samples']['samples_abs_over_1us'],'callback_max_us':v['direct_timeChanged_callbacks']['max_abs_s']*1e6,'callback_n_above1':v['direct_timeChanged_callbacks']['samples_abs_over_1us']} for n,v in result['nodes'].items()},'compensation_updates':{n:v['count'] for n,v in result['compensation_ppm'].items()}},indent=2))
 with p.open('rb') as fi,gzip.open(str(p)+'.gz','wb',compresslevel=6) as fo:
  while b:=fi.read(1024*1024): fo.write(b)
 p.unlink()
