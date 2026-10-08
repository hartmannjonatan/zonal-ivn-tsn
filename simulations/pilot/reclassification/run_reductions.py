#!/usr/bin/env python3
"""Run the preregistered, seed-41 2%-step reductions from the viable profile."""
import csv,json,os,shutil,subprocess,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent; ROOT=HERE.parents[2]; SIM=ROOT/'simulations'
sys.path.insert(0,str(HERE));sys.path.insert(0,str(ROOT/'scripts/catalog'))
import run_pilot as pilot
from generate_cbs import capacity_bps

def readcsv(p):
    with Path(p).open(newline='') as f:return list(csv.DictReader(f))
def writej(p,x):Path(p).write_text(json.dumps(x,indent=2,sort_keys=True)+'\n')
def write_profile(path,profile,meta):
    totals={}
    for (e,_),bps in profile.items():totals[e]=totals.get(e,0)+bps
    out=[]
    for (e,tc),bps in sorted(profile.items()):
        r=dict(meta[e,tc]);r.update(idle_slope_bps=bps,idle_slope_mbps=bps/1e6,
            total_port_reservation_bps=totals[e],cap_fraction=totals[e]/int(meta[e,tc]['port_rate_bps']),
            headroom_to_75pct_bps=int(.75*int(meta[e,tc]['port_rate_bps']))-totals[e])
        out.append(r)
    with Path(path).open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=out[0].keys(),lineterminator='\n');w.writeheader();w.writerows(out)
    return out

def main():
    nominal_rows=readcsv(HERE/'configs/cbs_variant_nominal.csv')
    nominal={(r['egress'],int(r['tc'])):int(r['idle_slope_bps']) for r in nominal_rows}
    meta={(r['egress'],int(r['tc'])):r for r in nominal_rows}
    selected=readcsv(HERE/'configs/candidate_15.csv')
    current={(r['egress'],int(r['tc'])):int(r['idle_slope_bps']) for r in selected}
    baseline=json.loads((HERE/'results/seed41/candidate_15.json').read_text())
    qwait={}
    for q in baseline['queueing_time']:
        m=q['queue'].split('.macLayer.queue.queue[')[0].removeprefix('ZonalIVN.')
        qwait[(m,int(q['tc']))]=(q.get('max_s') or 0,q.get('mean_s') or 0)
    env=os.environ.copy();env.setdefault('INET_ROOT','/home/jonatan/omnetpp/samples/inet-4.7.0');env.setdefault('OMNETPP_ROOT','/home/jonatan/omnetpp')
    inet=Path(env['INET_ROOT']).resolve();opp=Path(env.get('OMNETPP_ROOT',shutil.which('opp_run') and Path(shutil.which('opp_run')).resolve().parent.parent)).resolve()
    env['LD_LIBRARY_PATH']=str(opp/'lib')+':'+str(inet/'src')+':'+env.get('LD_LIBRARY_PATH','')
    sig=baseline['f21_f22_calendar_sha256']; reductions=[]
    for ix in range(1,13):
        adjustable=sorted((k for k in current if current[k]>nominal[k]),
            key=lambda k:(-(current[k]-nominal[k]),-qwait.get(k,(0,0))[0],k))
        if not adjustable:break
        key=adjustable[(ix-1)%len(adjustable)]
        new=dict(current);new[key]=max(nominal[key],new[key]-round(.02*capacity_bps(key[0])))
        label=f'reduction_{ix:02d}';config=f'PilotC2Reduction{ix:02d}';ini=HERE/f'{label}.ini';rates=HERE/'configs'/f'{label}.csv'
        profile=write_profile(rates,new,meta)
        lines=['include pilot-variant.ini','',f'[Config {config}]','extends = PilotC2Variant',f'result-dir = results/seed41/{label}','seed-set = 41']
        for (e,tc),bps in sorted(new.items()):lines.append(f'*.{e}.macLayer.queue.transmissionSelectionAlgorithm[{tc}].idleSlope = {bps}bps')
        ini.write_text('\n'.join(lines)+'\n')
        caps={}
        for (e,tc),bps in new.items():caps[e]=caps.get(e,0)+bps
        over=[e for e,total in caps.items() if total>.75*capacity_bps(e)]
        if over:
            reductions.append({'candidate':label,'status':'rejected_before_execution','targets':[{'egress':key[0],'tc':key[1]}],
                'reason':'75% aggregate reservation ceiling exceeded','ports':over})
            continue
        report,_=pilot.run_cell(label,config,'variant','C2',41,ini,inet,env,rates,sig)
        entry={'candidate':label,'status':'executed','targets':[{'egress':key[0],'tc':key[1]}],
               'viable':report['viable'],'profile_file':str(rates.relative_to(HERE)),
               'summary_file':f'results/seed41/{label}.json',
               'profile_bps':{f'{e}/TC{tc}':bps for (e,tc),bps in sorted(new.items())}}
        reductions.append(entry)
        if report['viable']:current=new
        state=json.loads((HERE/'results/calibration_search.json').read_text())
        state['reductions']=reductions
        if report['viable']:
            state['selected_seed41_profile']=label
            state['selected_profile_bps']=entry['profile_bps']
        writej(HERE/'results/calibration_search.json',state)
        writej(HERE/'results/reduction_history.json',{'algorithm':'inherited preregistered 2% port-rate decrement, highest-added reservation first then measured max queue wait; failed trials do not replace the best viable profile','tested_profile_bps':entry['profile_bps'],'reductions':reductions})
    state=json.loads((HERE/'results/calibration_search.json').read_text());state['reductions']=reductions
    writej(HERE/'results/calibration_search.json',state)
    writej(HERE/'results/reduction_history.json',{'algorithm':'inherited preregistered 2% port-rate decrement, highest-added reservation first then measured max queue wait; failed trials do not replace the best viable profile','reductions':reductions})
    print('Reduction exploration finished:',len(reductions),'tests',flush=True)
if __name__=='__main__':main()
