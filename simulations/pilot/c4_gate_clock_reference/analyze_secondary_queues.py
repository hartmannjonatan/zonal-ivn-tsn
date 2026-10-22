#!/usr/bin/env python3
"""Stream compact queue occupancy evidence for HPC/TC4 and Z3/TC4."""
import csv, gzip, hashlib, json, math
from pathlib import Path

HERE=Path(__file__).resolve().parent
OUT=HERE/"results"
START,END=1.0,31.0
TARGETS={
    "HPC.eth[0]/TC4":"ZonalIVN.HPC.eth[0].macLayer.queue.queue[4]",
    "Z3.ZSW.eth[7]/TC4":"ZonalIVN.Z3.ZSW.eth[7].macLayer.queue.queue[4]",
}
VARIANTS=("A005_local","A005_ideal_all","A005_ideal_HPC")

def integrate(bins,lo,hi,value):
    lo=max(lo,START);hi=min(hi,END)
    while lo<hi:
        ix=min(29,max(0,int(lo-START)))
        edge=min(END,START+ix+1)
        right=min(hi,edge)
        bins[ix]+=value*(right-lo)
        lo=right

def sha256(path):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        for block in iter(lambda:f.read(1<<20),b""):h.update(block)
    return h.hexdigest()

def run(variant):
    ledger=[json.loads(x) for x in (OUT/"runs.jsonl").read_text().splitlines() if x.strip()]
    row=next(x for x in ledger if x.get("diagnostic_variant")==variant)
    run_dir=OUT/"runs"/row["execution_id"]/f"Pilot_{row['variant']}_{row['cell']}-0"
    series={}
    with gzip.open(run_dir/"queue_occupancy_events.csv.gz.meta.json.gz","rt") as f: meta=json.load(f)
    ids={label:next(x["queue_index"] for x in meta["queues"] if x["module"]==module) for label,module in TARGETS.items()}
    by_id={v:k for k,v in ids.items()}
    for label in TARGETS:
        series[label]={"bins_area":[0.0]*30,"last_t":0.0,"last_v":0.0,"last_seen_t":-1.0,"nonmonotonic_rows":0,"initial_bits":None,"final_bits":0.0,"peak_bits":0.0,"events":0}
    source=run_dir/"queue_occupancy_events.csv.gz"
    with gzip.open(source,"rt",newline="") as f:
        for r in csv.DictReader(f):
            qid=int(r["queue_index"])
            label=by_id.get(qid)
            if label is None:continue
            x=series[label];t=float(r["timestamp_s"]);v=float(r["occupancy_bits"]);x["events"]+=1
            if t<x["last_seen_t"]-1e-15:x["nonmonotonic_rows"]+=1
            x["last_seen_t"]=max(x["last_seen_t"],t)
            integrate(x["bins_area"],x["last_t"],t,x["last_v"])
            if t<=START:x["initial_bits"]=v
            if t<END:x["final_bits"]=v
            if START<=t<END:x["peak_bits"]=max(x["peak_bits"],v)
            x["last_t"]=t;x["last_v"]=v
    result={}
    for label,x in series.items():
        integrate(x["bins_area"],x["last_t"],END,x["last_v"])
        means=[v for v in x["bins_area"]]  # each bin width is 1 second
        six=[sum(means[i:i+5])/5 for i in range(0,30,5)]
        result[label]={"module":TARGETS[label],"queue_index":ids[label],"capacity_bits":262144,"occupancy_unit":"bits","measurement_window_s":[START,END],"bin_width_s":1.0,
            "initial_state_bits_at_or_before_1s":x["initial_bits"],"final_state_bits_before_31s":x["final_bits"],"max_state_bits_in_window":x["peak_bits"],"mean_occupancy_bits_1s":means,"mean_occupancy_bits_5s":six,
            "mean_occupancy_bits_30s":sum(means)/30,"events_for_queue":x["events"],"nonmonotonic_timestamp_rows":x["nonmonotonic_rows"],"series_source":str(source.relative_to(HERE)),"source_sha256":sha256(source),
            "method":"right-continuous piecewise-constant queue occupancy; integrate each interval to the next state update over [1,31); same-queue CSV row order resolves equal timestamps"}
    return result

def write_svg(all_runs):
    w,h=1000,420;L,R,T,B=80,30,35,48
    colors={"A005_local":"#c62828","A005_ideal_all":"#1565c0","A005_ideal_HPC":"#2e7d32"}
    series={v:all_runs[v]["Z3.ZSW.eth[7]/TC4"]["mean_occupancy_bits_1s"] for v in VARIANTS}
    ymax=max(max(xs) for xs in series.values())*1.08
    def xx(i):return L+i*(w-L-R)/29
    def yy(v):return T+(h-T-B)*(1-v/ymax)
    parts=[]
    for j in range(6):
        y=ymax*j/5; y0=yy(y)
        parts.append(f'<line x1="{L}" y1="{y0:.1f}" x2="{w-R}" y2="{y0:.1f}" stroke="#ddd"/><text x="{L-8}" y="{y0+4:.1f}" text-anchor="end" font-size="11">{y/1000:.0f}k</text>')
    for v,xs in series.items():
        pts=" ".join(f"{xx(i):.1f},{yy(x):.1f}" for i,x in enumerate(xs))
        parts.append(f'<polyline fill="none" stroke="{colors[v]}" stroke-width="2" points="{pts}"/>')
    for i,v in enumerate(VARIANTS):
        x=L+i*255;parts.append(f'<line x1="{x}" y1="{h-16}" x2="{x+24}" y2="{h-16}" stroke="{colors[v]}" stroke-width="3"/><text x="{x+30}" y="{h-12}" font-size="12">{v}</text>')
    svg=f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}"><rect width="100%" height="100%" fill="white"/><text x="{w/2}" y="18" text-anchor="middle" font-size="15">Z3.ZSW.eth[7]/TC4: 1-second time-weighted occupancy</text>{"".join(parts)}<text x="{w/2}" y="{h-1}" text-anchor="middle" font-size="11">measurement bin, [1,2) through [30,31) seconds</text><text transform="translate(18,{h/2}) rotate(-90)" text-anchor="middle" font-size="11">queue bits</text></svg>'
    (OUT/"z3_tc4_occupancy.svg").write_text(svg)

def append_report_section(all_runs):
    path=OUT/"analysis.md"
    existing=path.read_text()
    marker="## Secondary queue time series"
    if marker in existing: existing=existing[:existing.index(marker)].rstrip()+"\n"
    lines=[marker,"","The full queue-state event series remains available for independent inspection. The following time-weighted 1-second means are recomputed from its right-continuous piecewise-constant samples; they make the within-measurement changes visible and avoid inferring a queue trend from only six 5-second averages.","","![Z3.ZSW.eth[7]/TC4 1-second occupancy](z3_tc4_occupancy.svg)","","| Variant | Z3.ZSW.eth[7]/TC4 5-second mean occupancy (kbit) | P1 sustained-growth flag |", "|---|---|---|"]
    for variant in VARIANTS:
        q=all_runs[variant]["Z3.ZSW.eth[7]/TC4"]
        p1=next((x for x in json.loads((OUT/"runs"/(variant+"_L2_A1_seed41_v1")/"pilot-result.json").read_text()).get("nonstable_queues",[]) if x.get("queue")==q["module"]),None)
        flag=bool(p1 and p1.get("sustained_growth"))
        vals=" / ".join(f"{v/1000:.1f}" for v in q["mean_occupancy_bits_5s"])
        lines.append(f"| {variant} | {vals} | {flag} |")
    lines += ["","In the local case, the Z3 queue's 5-second means fall from the early burst level through the fifth bin, then jump in the final bin. Under both ideal treatments they rise after the initial interval, stay near 64–67 kbit for several bins, and jump in the last bin. The 1-second graph and compact queue-state events show this non-monotone time course; the P1 stability flag remains as recorded and is not reinterpreted from six means alone.",""]
    path.write_text(existing+"\n".join(lines))

def main():
    all_runs={v:run(v) for v in VARIANTS}
    doc={"queue_stability_scope":"half-open [1,31) s; queue-bit events preserved from each simulation","variants":all_runs}
    secondary=OUT/"secondary_queue_analysis.json"
    secondary.write_text(json.dumps(doc,indent=2,ensure_ascii=False)+"\n")
    write_svg(all_runs)
    append_report_section(all_runs)
    summary_path=OUT/"diagnostic_results.json"
    summary=json.loads(summary_path.read_text())
    summary["secondary_queue_analysis"]=doc
    for name in ("analyze_secondary_queues.py",):
        f=HERE/name;summary.setdefault("analysis_artifacts",{})[name]={"sha256":sha256(f),"bytes":f.stat().st_size}
    for name in ("secondary_queue_analysis.json","z3_tc4_occupancy.svg","analysis.md"):
        f=OUT/name;summary.setdefault("result_artifacts",{})[name]={"sha256":sha256(f),"bytes":f.stat().st_size}
    summary_path.write_text(json.dumps(summary,indent=2,ensure_ascii=False)+"\n")
    for v in VARIANTS:
        for label,x in all_runs[v].items():print(v,label,"5s means",[round(n,1) for n in x["mean_occupancy_bits_5s"]],"monotonic errors",x["nonmonotonic_timestamp_rows"])

if __name__=="__main__":main()
