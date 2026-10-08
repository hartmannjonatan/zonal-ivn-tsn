#!/usr/bin/env python3
"""Assemble the final isolated pilot JSON and Markdown from compact run records."""
import csv,hashlib,json
from pathlib import Path
H=Path(__file__).resolve().parent
def readj(p):return json.loads(Path(p).read_text())
def readcsv(p):
    with Path(p).open(newline="") as f:return list(csv.DictReader(f))
def writej(p,x):Path(p).write_text(json.dumps(x,indent=2,sort_keys=True)+"\n")
def sha(p):
    d=hashlib.sha256(Path(p).read_bytes()).hexdigest();return d
def rx(report,fid):
    m=report.get("qos",{}).get(fid,{})
    return m.get("receivers",{})
def flow_summary(run,fid,deadline_us=None):
    q=run.get("qos",{}).get(fid,{}); receivers=q.get("receivers",{})
    out=[]
    for node,x in receivers.items():
        image=x.get("image_completion")
        lat=x.get("latency") or {}
        offered=int(x.get("offered_packets") or 0)
        if image:
            absolute_misses=int(image.get("deadline_misses_completed",0))+max(0,int(image.get("offered_images",0))-int(image.get("completed_images",0)))
        else:
            absolute_misses=max(0,offered-(int(x.get("received_packets") or 0)-int(x.get("deadline_misses_received") or 0)))
        out.append({"receiver":node,"criticality":q.get("criticality"),"offered_packets":offered,
            "received_packets":x.get("received_packets"),"confirmed_drops":run.get("confirmed_drop_packets_by_flow",{}).get(fid,{}).get("confirmed_drop_packets",0),
            "pending_locations":[p for p in run.get("pending_by_flow",[]) if p.get("flow")==fid],
            "deadline_us":(image or {}).get("deadline_s",None) and (image["deadline_s"]*1e6) or deadline_us,
            "deadline_misses_absolute_including_loss":absolute_misses,
            "deadline_misses_received_late":((image or {}).get("deadline_misses_completed",0) if image else x.get("deadline_misses_received")),
            "deadline_miss_ratio":(image or {}).get("deadline_miss_ratio_including_missing_images") if image else x.get("deadline_miss_ratio_including_loss"),
            "p99_s":lat.get("p99_s"),"max_s":lat.get("max_s"),"goodput_mbps":x.get("useful_throughput_mbps"),
            "goodput_payload_ratio":x.get("goodput_payload_ratio"),"packet_loss_ratio":x.get("packet_loss_ratio"),
            "image_completion":image,"gate_pass":x.get("viable")})
    return out
def fmt(v,scale=1,suffix=""):
    if v is None:return "indisponível"
    return f"{v*scale:.4g}{suffix}"

def main():
    mapping=readcsv(H/"mapping_table.csv"); nominal=readj(H/"mapping_and_nominal_reservations.json")
    controls=readj(H/"results/seed41/control-comparison.json")
    search=readj(H/"results/calibration_search.json") if (H/"results/calibration_search.json").exists() else None
    env=readj(H/"pilot_manifest.json")
    runs={r["label"]:r for r in controls["runs"]}
    if search:
        for e in search["search_history"]:
            p=e.get("summary_file")
            if p and (H/p).exists():
                r=readj(H/p);runs[r["label"]]=r
        for e in search.get("reductions",[]):
            p=f"results/seed41/{e['candidate']}.json"
            if (H/p).exists():runs[e["candidate"]]=readj(H/p)
        for s in search.get("robustness_seeds_43_47",[]):
            for key in ("nominal","fixed_candidate"):
                r=s.get(key)
                if r:runs[r["label"]]=r
    for label,run in runs.items():
        profile_file=None;ini_file=None
        if label=="C2_original": profile_file="configs/cbs_original_nominal.csv";ini_file="pilot-original.ini"
        elif label in {"C2_variant_nominal","C2_variant_nominal_seed43","C2_variant_nominal_seed47"}:
            profile_file="configs/cbs_variant_nominal.csv";ini_file="pilot-variant.ini"
        elif label.startswith("candidate_"):
            profile_file=f"configs/{label}.csv";ini_file=f"{label}.ini"
        elif label.startswith("reduction_"):
            profile_file=f"configs/{label}.csv";ini_file=f"{label}.ini"
        elif label.startswith("fixed_candidate_seed"):
            profile_file="configs/candidate_15.csv";ini_file=f"{label}.ini"
        elif label in {"C0_variant","C1_variant"}:
            ini_file="pilot-variant.ini"
        run["configuration_ini"]=ini_file
        run["configuration_ini_sha256"]=sha(H/ini_file) if ini_file and (H/ini_file).is_file() else None
        run["reservation_profile_csv"]=profile_file
        run["reservation_profile_sha256"]=sha(H/profile_file) if profile_file and (H/profile_file).is_file() else None
        run["effective_cbs_profile"]=[]
        if profile_file:
            for row in readcsv(H/profile_file):
                e=row["egress"];tc=int(row["tc"])
                run["effective_cbs_profile"].append({"module":f"ZonalIVN.{e}.macLayer.queue.transmissionSelectionAlgorithm[{tc}]",
                    "traffic_class":tc,"idle_slope_bps":int(row["idle_slope_bps"]),"port_rate_bps":int(row["port_rate_bps"]),
                    "permanent_flows":row["permanent_flows"].split(";") if row.get("permanent_flows") else [],
                    "total_port_reservation_bps":int(row["total_port_reservation_bps"]),"cap_fraction":float(row["cap_fraction"]),
                    "headroom_to_75pct_bps":int(row["headroom_to_75pct_bps"])})
        run["effective_cbs_algorithm_count"]=len(run["effective_cbs_profile"])
        if not run.get("simulation_command"):
            config=run["configuration"];seed=int(run.get("seed",41));inet=env_inet=readj(H/"pilot_manifest.json").get("inet_root")
            out=H/f"results/seed{seed}/{label}"
            run["simulation_command"]=[str(H.parents[2]/"src/zonal-ivn-tsn"),"-u","Cmdenv","-n",f".:{H.parents[2]/'src'}:{H.parents[2]/'tests'}:{inet}/src",
                "-f",f"simulations/pilot/reclassification/{ini_file}","-c",config,"--cmdenv-express-mode=true","--cmdenv-event-banners=false",
                "--**.app[*].latency.result-recording-modes=+vector","--**.app[*].imageCompletionLatency.result-recording-modes=+vector",
                "--**.queueLength.result-recording-modes=+vector","--**.queueBitLength.result-recording-modes=+vector",
                "--**.droppedPacketLengthsQueueOverflow.result-recording-modes=+vector","--**.queueingTime.result-recording-modes=+histogram",
                "--**.utilization.result-recording-modes=+histogram",f"--result-dir={out.resolve()}"]
            run["simulation_command_reconstructed"]=True
        else:run["simulation_command_reconstructed"]=False
        run_dir=H/f"results/seed{run.get('seed',41)}/{label}/{run.get('configuration')}-0"
        drop_path=run_dir/"drops.csv"
        if drop_path.is_file():
            drop_rows=readcsv(drop_path)
            table={(r["flow_id"],"variant" if run.get("mapping")=="variant" else "original"):r for r in mapping}
            per_flow={}
            for dr in drop_rows:
                fid=dr["flow"];mapping_row=table.get((fid,"variant" if run.get("mapping")=="variant" else "original"),{})
                tc=int(mapping_row.get("variant_tc" if run.get("mapping")=="variant" else "original_tc",0))
                entry=per_flow.setdefault(fid,{"confirmed_drop_packets":0,"sites":[]})
                entry["confirmed_drop_packets"]+=int(dr["packets"])
                if int(dr["packets"]):entry["sites"].append({"interface":dr["interface"],"traffic_class":tc,
                    "packets":int(dr["packets"]),"bytes":int(dr["bytes"])})
            run["confirmed_drop_packets_by_flow"]=per_flow
            qstats={(q["queue"],int(q["tc"])):q for q in run.get("queue_stability",[])}
            mdrops={(q["queue"],int(q["tc"])):q for q in run.get("measurement_drops_by_queue") or []}
            grouped={}
            for dr in drop_rows:
                fid=dr["flow"];mapping_row=table.get((fid,"variant" if run.get("mapping")=="variant" else "original"),{})
                tc=int(mapping_row.get("variant_tc" if run.get("mapping")=="variant" else "original_tc",0))
                key=(dr["interface"],tc);x=grouped.setdefault(key,{"queue":f"{dr['interface']}.macLayer.queue.queue[{tc}]","interface":dr["interface"],"tc":tc,"drops_packets":0,"drops_bytes":0,"flows":{}})
                x["drops_packets"]+=int(dr["packets"]);x["drops_bytes"]+=int(dr["bytes"])
                if int(dr["packets"]):x["flows"][fid]=int(dr["packets"])
            for key,x in grouped.items():
                x["capacity_bits"]=(qstats.get(key) or {}).get("capacity_bits")
                x["max_occupancy_bits"]=(qstats.get(key) or {}).get("max_occupancy_bits")
                x["mean_occupancy_bits_5s"]=(qstats.get(key) or {}).get("mean_occupancy_bits_5s")
                x["measurement_window_drops"]=(mdrops.get(key) or {}).get("packets")
            run["drops_by_queue_entire_run"]=[grouped[k] for k in sorted(grouped)]
            run["drops_reconciled_from_export"]=(sum(x["drops_packets"] for x in grouped.values())==int(run.get("drops_entire_run",0)))
    flow_info={r["flow_id"]:r for r in readcsv(H/"catalog/flows_variant.csv")}
    cfgs=["pilot-common.ini","pilot-original.ini","pilot-variant.ini","generate_pilot.py","run_pilot.py","calibrate_pilot.py","run_reductions.py","search_protocol.json"]
    config_hashes={p:sha(H/p) for p in cfgs if (H/p).is_file()}
    nominal_by_key={(q["egress"],int(q["tc"])):q for q in nominal["nominal_reservations_l2"]["variant"]}
    profiles=[]
    if search:
        nominal_profile=[]
        for q0 in nominal["nominal_reservations_l2"]["variant"]:
            q=dict(q0);q["nominal_idle_slope_bps"]=int(q["idle_slope_bps"]);q["candidate_to_nominal_ratio"]=1.0;nominal_profile.append(q)
        profiles.append({"candidate":"variant_nominal","status":"executed","source":"configs/cbs_variant_nominal.csv","reservations":nominal_profile})
        for entry in list(search.get("search_history",[]))+list(search.get("reductions",[])):
            raw=entry.get("profile_bps")
            if not raw: continue
            vals={}
            for key,bps in raw.items():
                e,tc=key.rsplit("/TC",1); vals[(e,int(tc))]=int(bps)
            totals={}
            for (e,_),bps in vals.items():totals[e]=totals.get(e,0)+bps
            reservations=[]
            for (e,tc),bps in sorted(vals.items()):
                n=nominal_by_key[e,tc];total=totals[e];cap=int(n["port_rate_bps"])
                reservations.append({"egress":e,"tc":tc,"idle_slope_bps":bps,"nominal_idle_slope_bps":int(n["idle_slope_bps"]),
                    "candidate_to_nominal_ratio":bps/int(n["idle_slope_bps"]),"permanent_flows":n["permanent_flows"],
                    "port_rate_bps":cap,"total_port_reservation_bps":total,"cap_fraction":total/cap,
                    "headroom_to_75pct_bps":int(.75*cap)-total})
            profiles.append({"candidate":entry["candidate"],"status":entry["status"],"reservations":reservations})
    if search:search["robustness_profile_seed41"]="candidate_15" if search.get("calibration_found_feasible_candidate") else None
    data={"exploratory":True,"official_profile_frozen":False,
          "calibration_found_feasible_candidate":bool(search and search.get("calibration_found_feasible_candidate")),
          "objective":"isolated L2/A1 seed-41 reclassification/CBS pilot; no official P1 or scenario config changed",
          "environment":env,"configuration_sha256":config_hashes,
          "protocol":readj(H/"search_protocol.json"),"mapping_table":mapping,
          "catalog_divergence_resolution":"Seven flows (F02,F03,F11,F12,F13,F21,F22) were PCP6/TC6 in canonical catalog but are explicitly remapped to PCP4/TC4 in pilot. F01,F06,F07 stay PCP6/TC6; other groups match requested mapping.",
          "nominal_reservations_l2":nominal["nominal_reservations_l2"],
          "candidate_reservations":profiles,
          "comparison_dimensions":{"mapping_effect":{"control":"C2_original","variant":"C2_variant_nominal","seed":41,"paired_calendar":runs["C2_original"].get("f21_f22_calendar_sha256")==runs["C2_variant_nominal"].get("f21_f22_calendar_sha256")},
            "calibration_effect":{"nominal":"C2_variant_nominal","first_viable":"candidate_15","selected_after_seed41_reductions":search.get("selected_seed41_profile") if search else None,"seed":41},
            "robustness":{"fixed_profile":search.get("robustness_profile_seed41") if search else None,"seeds":[s.get("seed") for s in (search or {}).get("robustness_seeds_43_47",[])],"profiles_not_retuned":True}},
          "run_calendar_signatures":{k:v.get("f21_f22_calendar_sha256") for k,v in runs.items()},
          "calendar_files":{str(p.relative_to(H)):sha(p) for p in H.glob("calendars/*_events.csv")},
          "runs":runs,"calibration_search":search,
          "per_flow_by_run":{label:{fid:flow_summary(r,fid,float(flow_info[fid]["deadline_us"]) if flow_info[fid]["deadline_us"] else None) for fid in sorted(r.get("qos",{}))} for label,r in runs.items()},
          "temporal_evidence":{label:r.get("temporal_association") for label,r in runs.items()},
          "limitations":["Temporal overlap is association only; without per-packet route identity it does not establish causal attribution.",
            "A cell is accepted only when complete packet-latency vector populations reconcile with receiver CSV counts.",
            "Only L2/A1 is tested; exploratory seeds 43 and 47 are conditional and are not the final 1001–1030 campaign."]}
    writej(H/"results/pilot_results.json",data)
    md=["# Piloto exploratório de separação CBS por PCP/TC","",
        "Este relatório descreve somente o experimento isolado em `simulations/pilot/reclassification`. O P1, as configurações/generadores oficiais e os resultados anteriores foram preservados. `exploratory=true`; `official_profile_frozen=false`.","",
        "## Protocolo e execução","",
        f"Commit observado: `{env.get('commit')}`; o working tree já estava dirty antes do piloto. OMNeT++: `{env.get('omnetpp','').splitlines()[1] if len(env.get('omnetpp','').splitlines())>1 else env.get('omnetpp')}`. INET: `{env.get('inet_version')}` em `{env.get('inet_root')}`. Escopo: L2/A1; seed 41 para controles/calibração, seeds 43 e 47 somente para robustez condicional; warm-up 1 s, medição 30 s, drenagem 50 ms. Buffers: 64 KiB/TC em CAM1–CAM4, 128 KiB/TC em G1–G4 e 32 KiB/TC nos demais. O calendário F21/F22 é gerado no início nos RNG streams dedicados e pareado por SHA-256 dentro de cada seed.","",
        "O JSON inclui o comando Cmdenv por execução, INI e hashes do INI/CSV de reservas, além do idleSlope completo por módulo/porta/TC. O comando da primeira execução C2 original, coletada antes da correção de logging, foi reconstruído com os mesmos flags de gravação das execuções corrigidas. `pilot_manifest.json` registra o commit, versões e que nenhum perfil oficial foi modificado pelo piloto.","",
        "A execução C2 variante inicial foi rejeitada antes da análise: o `.vec` tinha definições sem amostras e os CSVs saíram fora da pasta piloto. A instrumentação foi corrigida e a execução refeita; ela não consta como tratamento válido nem como candidato.","",
        "## Fluxos e mapeamento","",
        "A tabela confirma todos os 22 IDs. F02/F03, F11–F13 e F21/F22 divergiam do papel explicitado: eram PCP6/TC6 no catálogo original, mas são PCP4/TC4 nesta variante. PCP classifica para TC de mesmo índice em todos os egressos; VLAN, destinos, rotas, FIFO por TC, prioridade estrita e ausência de preempção permanecem fixos.","",
        "| Fluxo | VLAN | P1 PCP→TC | Mecanismo C2 original | Piloto PCP→TC | Mecanismo C2 piloto |","|---|---:|---:|---|---:|---|"]
    for r in mapping:md.append(f"| {r['flow_id']} {r['source']}→{r['destinations']} | {r['vlan']} | {r['original_pcp']}→{r['original_tc']} | {r['original_mechanism']} | {r['variant_pcp']}→{r['variant_tc']} | {r['variant_mechanism']} |")
    md += ["","## Reservas permanentes nominais L2","",
           "As reservas foram recalculadas a partir de `R_wire` dos fluxos permanentes efetivamente roteados; F21/F22 foram excluídos. O limite é soma CBS ≤75% de cada egress.","",
           "| Mapeamento | Egress | TC | Fluxos permanentes | Reserva | Soma da porta | Margem até 75% |","|---|---|---:|---|---:|---:|---:|"]
    for kind,arr in nominal["nominal_reservations_l2"].items():
        for q in arr:md.append(f"| {kind} | {q['egress']} | {q['tc']} | {', '.join(q['permanent_flows'])} | {q['idle_slope_mbps']:.3f} Mb/s | {q['total_port_reservation_bps']/1e6:.3f} Mb/s | {q['headroom_to_75pct_bps']/1e6:.3f} Mb/s |")
    md += ["","## Comparações e gates","",
           "O JSON entrega, por execução e fluxo, pacotes oferecidos/recebidos, perdas confirmadas por fluxo quando exportadas, pendências com localização, misses e proporções, deadline, p99/máximo, goodput, conclusão de imagem, gates e filas. A comparação de efeito de mapeamento é C2 original versus C2 variante nominal; efeito de calibração é C2 variante nominal versus perfil selecionado; robustez compara o perfil fixo com o C2 variante nominal nas seeds 43 e 47 somente se o perfil passar na seed 41.","",
           "| Execução | Mapeamento | Seed | Viável em todos gates P1 | Drops | Pendentes no fim | Filas instáveis | Assinatura F21/F22 |","|---|---|---:|---|---:|---:|---:|---|"]
    for label,r in runs.items():md.append(f"| {label} | {r.get('mapping')} | {r.get('seed')} | {'sim' if r.get('viable') else 'não'} | {r.get('drops_entire_run')} | {r.get('pending_packets_at_end')} | {len(r.get('nonstable_queues',[]))} | `{r.get('f21_f22_calendar_sha256')}` |")
    md += ["","### Fluxos — resumo por tratamento","",
           "`misses` é a proporção de deadline misses incluindo as perdas, conforme critério P1; nas câmeras inclui imagens incompletas e a latência imagem-disponível→último frame recebido. Latência individual por pacote segue separada no JSON.","",
           "| Fluxo | C2 P1 original: misses/p99/gate | C2 variante nominal: misses/p99/gate | C0 variante: misses/p99/gate | C1 variante: misses/p99/gate | Perfil calibrado: misses/p99/gate |","|---|---|---|---|---|---|"]
    labels=["C2_original","C2_variant_nominal","C0_variant","C1_variant","calibration_candidate_01"]
    selected=search.get("selected_seed41_profile") if search else None
    if selected and selected in runs:labels[4]=selected
    def flow_text(label,fid):
        r=runs.get(label);rs=rx(r,fid) if r else {}
        if not rs:return "—"
        vals=[]
        for node,x in rs.items():
            im=x.get("image_completion");miss=(im or {}).get("deadline_miss_ratio_including_missing_images",x.get("deadline_miss_ratio_including_loss"))
            lat=x.get("latency") or {};p99=lat.get("p99_s")
            gate="N/A" if x.get("viable") is None else ("pass" if x.get("viable") else "fail")
            vals.append(f"{node}: {fmt(miss*100 if miss is not None else None,suffix='%')}/{fmt(p99*1e6 if p99 is not None else None,suffix=' µs')}/{gate}")
        return "; ".join(vals)
    for fid in sorted(mapping,key=lambda x:int(x["flow_id"][1:])):md.append(f"| {fid['flow_id']} | {flow_text(labels[0],fid['flow_id'])} | {flow_text(labels[1],fid['flow_id'])} | {flow_text(labels[2],fid['flow_id'])} | {flow_text(labels[3],fid['flow_id'])} | {flow_text(labels[4],fid['flow_id'])} |")
    md += ["","## Busca CBS exploratória","",""]
    if search:
        md.append(f"Resultado: **{'candidato empiricamente viável encontrado' if search['calibration_found_feasible_candidate'] else search['failure_wording']}**. O resultado é limitado a esta busca e à seed 41; não demonstra impossibilidade geral.")
        md += ["","| Candidato | Fase | Estado | Alvos | Viável | Razão/observação |","|---|---|---|---|---|---|"]
        for c in search["search_history"]:
            targets=", ".join(f"{x['egress']}/TC{x['tc']}" for x in c.get("targets",[]))
            md.append(f"| {c['candidate']} | {c.get('phase','nominal')} | {c['status']} | {targets} | {c.get('viable','—')} | {c.get('rejection_reason') or ', '.join(c.get('failed_flows_after_run',[]))} |")
        md += ["","### Mudanças de reserva por perfil","",
               "Cada linha mostra a reserva final, razão candidato/nominal, soma CBS da porta e margem até 75%; as tabelas completas por porta/TC também estão no JSON.","",
               "| Candidato | Porta/TC | Nominal | Candidato | Razão | Soma porta | Margem 75% |","|---|---|---:|---:|---:|---:|---:|"]
        for profile in profiles:
            for q in profile["reservations"]:
                if q["idle_slope_bps"]==q["nominal_idle_slope_bps"] and profile["candidate"]!="variant_nominal":continue
                md.append(f"| {profile['candidate']} | {q['egress']}/TC{q['tc']} | {q['nominal_idle_slope_bps']/1e6:.3f} Mb/s | {q['idle_slope_bps']/1e6:.3f} Mb/s | {q['candidate_to_nominal_ratio']:.3f} | {q['total_port_reservation_bps']/1e6:.3f} Mb/s | {q['headroom_to_75pct_bps']/1e6:.3f} Mb/s |")
        if search.get("robustness_seeds_43_47"):
            md += ["","Verificação sem recalibração nas seeds 43 e 47:",""]
            for s in search["robustness_seeds_43_47"]:md.append(f"- Seed {s['seed']}: nominal viável={s['nominal']['viable']}; perfil fixo viável={s['fixed_candidate_viable']}; calendário pareado `{s['calendar_sha256']}`.")
        md += ["","### Reduções após viabilidade","",
               f"Primeiro perfil viável: `{search.get('search_phase_summary',{}).get('viability_candidate','candidate_15')}`. O perfil mantido fixo nas seeds 43/47 foi esse candidato inicial. Foram executadas {len(search.get('reductions',[]))} reduções de 2%; a seleção final seed-41 foi `{search.get('selected_seed41_profile')}`. Somente reduções que passaram todos os gates substituíram o perfil viável anterior.","",
               "| Redução | Porta/TC reduzida | Viável | Drops | Pendentes | Filas instáveis |","|---|---|---|---:|---:|---:|"]
        for r in search.get("reductions",[]):
            rr=runs.get(r["candidate"],{});target=", ".join(f"{x['egress']}/TC{x['tc']}" for x in r.get("targets",[]))
            md.append(f"| {r['candidate']} | {target} | {r.get('viable')} | {rr.get('drops_entire_run','—')} | {rr.get('pending_packets_at_end','—')} | {len(rr.get('nonstable_queues',[])) if rr else '—'} |")
        md += ["","Candidatos 07–12 não foram gerados porque as coordenadas individuais elegíveis se esgotaram após o candidato 06; a busca passou aos testes acoplados 13–18 e parou no candidato 15, o primeiro viável. `not_generated` indica fase encerrada sem perfil novo, não rejeição de uma simulação. Candidatos 16–24 não foram necessários após a viabilidade.",""]
    else:md.append("A busca CBS ainda não foi executada.")
    md += ["","## Filas e relação temporal","",
           "O JSON contém média/máximo de `queueingTime`, ocupação máxima e média temporal em bins, drops de overflow por fila e indicadores de crescimento sustentado. A tabela destaca a saída CSW.eth[0] para HPC, uplinks de Z1/Z2/Z3 e a saída HPC TC4; todos os outros egressos continuam no JSON. O campo da tabela é o contador de drops da execução inteira; `measurement_drops_by_queue` separa a janela de 30 s. `nonstable_queues=0` significa que o critério de crescimento sustentado não foi acionado; não significa ausência de overflow: C2 variante nominal teve 140.938 drops apesar de zero filas classificadas como instáveis.","",
           "| Execução | Fila/TC | Espera média/máxima (µs) | Ocupação média temporal/pico (KiB) | Capacidade (KiB) | Drops | Crescimento sustentado |","|---|---|---:|---:|---:|---:|---|"]
    qlabels=["C2_variant_nominal","candidate_15","reduction_12"]
    qkeys=[("CSW.eth[0]",4),("CSW.eth[0]",6),("HPC.eth[0]",4),("Z1.ZSW.eth[0]",4),("Z1.ZSW.eth[0]",6),("Z2.ZSW.eth[0]",4),("Z2.ZSW.eth[0]",6),("Z3.ZSW.eth[0]",4),("Z3.ZSW.eth[7]",4)]
    for label in qlabels:
        run=runs.get(label)
        if not run:continue
        for port,tc in qkeys:
            name=f"ZonalIVN.{port}.macLayer.queue.queue[{tc}]"
            wait=next((q for q in run.get("queueing_time",[]) if q.get("queue")==name),{})
            stab=next((q for q in run.get("queue_stability",[]) if q.get("queue")==name),{})
            drop=next((q for q in run.get("drops_by_queue_entire_run",[]) if q.get("queue")==name),{})
            means=stab.get("mean_occupancy_bits_5s") or []
            avg=sum(means)/len(means)/8192 if means else None
            peak=stab.get("max_occupancy_bits");peak=peak/8192 if peak is not None else None
            cap=stab.get("capacity_bits");cap=cap/8192 if cap is not None else None
            w=(f"{fmt(wait.get('mean_s')*1e6)}/{fmt(wait.get('max_s')*1e6)}" if wait.get("samples") and wait.get("mean_s") is not None and wait.get("max_s") is not None else "indisponível")
            o=(f"{fmt(avg)}/{fmt(peak)}" if avg is not None and peak is not None else "indisponível")
            md.append(f"| {label} | {port}/TC{tc} | {w} | {o} | {fmt(cap)} | {drop.get('drops_packets',0)} | {stab.get('sustained_growth','indisponível')} |")
    md += ["",
           "A evidência temporal de 1 ms combina misses dos sensores por instante de criação, liberações de câmera, intervalos F21/F22 e amostras compactas de ocupação nas filas selecionadas. Isso sustenta associação temporal, não causalidade exata, porque não há rastreamento de identidade do pacote em todos os saltos.","",
           "## Conclusão e limites","",
           "O resultado sustenta investigar a revisão do mapeamento no P1: na seed 41, F01 mudou de 99,983% de misses e p99 2,946 ms para zero misses/p99 62,8 µs; F06 mudou de 99,996%/18,369 ms para zero/68,4 µs. O C2 variante nominal, porém, deslocou as falhas para F02/F03 (100% de misses de conclusão de imagem), F13 e F21/F22, somando 140.938 drops confirmados. O candidato 15 removeu essas falhas sem transferi-las a outros fluxos e passou todos os gates na seed 41; também passou nas seeds 43 e 47 com reservas fixas. Os doze testes de redução subsequentes continuaram viáveis na seed 41, e `reduction_12` é a menor reserva encontrada pela sequência testada. Isso é evidência exploratória, não validação de C3 nem prova estatística.","",
           "H1 define comparação C0–C4 em L0/A0; como o piloto só executou L2/A1, H1 não foi testada. H2 depende de contrastes A1−A0 e C1−C0 em L2/L3; esta única célula fornece apenas diagnóstico descritivo e não testa H2. Nenhuma conclusão exige confirmar H1/H2, e as hipóteses não foram alteradas para favorecer CBS.","",
           "O candidato 15, não `reduction_12`, é o perfil fixo verificado em seeds 43 e 47; `reduction_12` só foi testado na seed 41. C0/C1 também passaram nesta célula. A revisão do protocolo oficial ainda requer decisão após análise. Se a revisão for aceita, será necessário atualizar o mapeamento common e reexecutar as células comparativas com mapeamento comum; estas seeds exploratórias não substituem a campanha 1001–1030 nem iniciam essa campanha.","",
           "Artefatos compactos, calendários e histórico permanecem sob `simulations/pilot/reclassification`; vetores grandes só são retidos para o candidato reprovado representativo e o primeiro viável, quando encontrados."]
    (H/"results/analysis.md").write_text("\n".join(md)+"\n")
if __name__=="__main__":main()
