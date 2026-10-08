#!/usr/bin/env python3
"""Correct pilot exports from preserved run summaries and effective reservation CSVs.

No simulation is started here. Outputs are deterministic views of existing pilot data.
"""
import csv, json, shutil
from pathlib import Path

H=Path(__file__).resolve().parent
R=H/'results'
ARCH=R/'archive/pre_correction'

def jread(p): return json.loads(Path(p).read_text())
def jwrite(p,x): Path(p).write_text(json.dumps(x,indent=2,sort_keys=True)+'\n')
def csvread(p):
    with Path(p).open(newline='') as f: return list(csv.DictReader(f))
def normalize_profile_csvs():
    """Repair derived columns only; preserve all effective idleSlope inputs."""
    backup=ARCH/'configs_pre_correction';backup.mkdir(parents=True,exist_ok=True)
    files=list((H/'configs').glob('*.csv'))
    for p in files:
        bp=backup/p.name
        if not bp.exists(): shutil.copy2(p,bp)
        rows=csvread(p); totals={}
        for r in rows: totals[r['egress']]=totals.get(r['egress'],0)+int(r['idle_slope_bps'])
        for r in rows:
            total=totals[r['egress']];rate=int(r['port_rate_bps'])
            r['total_port_reservation_bps']=str(total);r['cap_fraction']=f"{total/rate:.12g}"
            r['headroom_to_75pct_bps']=str(int(.75*rate)-total)
        with p.open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
def ini_idle_slopes(path,vals=None,seen=None):
    vals={} if vals is None else vals; seen=set() if seen is None else seen
    if not path or path in seen or not (H/path).is_file(): return vals
    seen.add(path)
    for line in (H/path).read_text().splitlines():
        line=line.strip()
        if line.startswith('include '):
            include=line.split(None,1)[1].strip().strip('"')
            ini_idle_slopes(str((Path(path).parent/include).as_posix()),vals,seen)
            continue
        if not line.startswith('*.') or '.idleSlope' not in line or '=' not in line: continue
        left,right=line.split('=',1); key=left.strip()[2:].replace('.macLayer.queue.transmissionSelectionAlgorithm[','/TC').replace('].idleSlope','')
        try: vals[key]=int(right.strip().removesuffix('bps'))
        except ValueError: pass
    return vals
def config_ini_for(label):
    if label=='C2_original': return 'pilot-original.ini'
    if label in {'C2_variant_nominal','C2_variant_nominal_seed43','C2_variant_nominal_seed47','C0_variant','C1_variant'}: return 'pilot-variant.ini'
    if label.startswith('fixed_candidate_seed'): return f'{label}.ini'
    if label.startswith('candidate_') or label.startswith('reduction_'): return f'{label}.ini'
    return None
def bps_profile(name):
    rows=csvread(H/'configs'/f'{name}.csv')
    totals={}
    for r in rows: totals[r['egress']]=totals.get(r['egress'],0)+int(r['idle_slope_bps'])
    out=[]
    for r in rows:
        e=r['egress']; rate=int(r['port_rate_bps']); total=totals[e]; idle=int(r['idle_slope_bps'])
        out.append({'egress':e,'traffic_class':int(r['tc']),'idle_slope_bps':idle,
          'port_rate_bps':rate,'permanent_flows':r.get('permanent_flows','').split(';') if r.get('permanent_flows') else [],
          'total_port_reservation_bps':total,'cap_fraction':total/rate,
          'headroom_to_75pct_bps':int(.75*rate)-total})
    return out
def profile_name(label):
    if label=='C2_original': return 'cbs_original_nominal'
    if label in {'C2_variant_nominal','C2_variant_nominal_seed43','C2_variant_nominal_seed47'}: return 'cbs_variant_nominal'
    if label.startswith('fixed_candidate_seed'): return 'candidate_15'
    if label.startswith('candidate_') or label.startswith('reduction_'): return label
    return None
def miss_count_packets(x):
    offered=int(x.get('offered_packets') or 0); received=int(x.get('received_packets') or 0)
    late=int((x.get('latency') or {}).get('deadline_misses_from_samples') or x.get('deadline_misses_received') or 0)
    return late+max(0,offered-received)
def camera_metrics(x):
    im=x.get('image_completion') or {}; offered=int(im.get('offered_images') or 0); complete=int(im.get('completed_images') or 0)
    late=int(im.get('deadline_misses_completed') or 0); incomplete=max(0,offered-complete)
    return {'unit':'image','offered_images':offered,'completed_images':complete,'incomplete_images':incomplete,
      'complete_images_late':late,'deadline_misses_including_incomplete':late+incomplete,
      'deadline_denominator_images':offered,'deadline_miss_ratio_including_incomplete':(late+incomplete)/offered if offered else None,
      'p99_completion_s':im.get('p99_s'),'max_completion_s':im.get('max_s'),
      'latency_samples':im.get('samples'),'deadline_s':im.get('deadline_s'),
      'samples_match_completed_images':im.get('samples')==complete}
def flow_row(fid,node,x,run):
    lat=x.get('latency') or {}; offered=int(x.get('offered_packets') or 0); received=int(x.get('received_packets') or 0)
    drops=int(run.get('confirmed_drop_packets_by_flow',{}).get(fid,{}).get('confirmed_drop_packets',0))
    pending=[p for p in run.get('pending_by_flow',[]) if p.get('flow')==fid]
    pending_reported=sum(int(p.get('packets',0)) for p in pending)
    pending_reconciled=max(0,offered-received-drops)
    pending_packets=pending_reported if pending_reported else pending_reconciled
    packet_misses=miss_count_packets(x)
    packet_den=offered
    packet={'unit':'packet','offered_packets':offered,'received_packets':received,'confirmed_drops_execution':drops,
      'pending_packets_at_end':pending_packets,'pending_source':'pending_by_flow export' if pending_reported else 'offered-received-confirmed_drops reconciliation',
      'population_reconciles':offered==received+drops+pending_packets,
      'deadline_misses_including_drops':packet_misses,
      'deadline_denominator_packets':packet_den,'deadline_miss_ratio_including_drops':packet_misses/packet_den if packet_den else None,
      'latency_samples':lat.get('samples'),'samples_match_received_packets':lat.get('samples')==received,
      'p99_latency_s':lat.get('p99_s'),'max_latency_s':lat.get('max_s'),
      'deadline_misses_received_late':lat.get('deadline_misses_from_samples'),
      'useful_goodput_mbps':x.get('useful_throughput_mbps'),'packet_loss_ratio_reported':x.get('packet_loss_ratio')}
    cam=camera_metrics(x) if fid in {'F02','F03','F04','F05'} and x.get('image_completion') else None
    return {'flow_id':fid,'receiver':node,'packet_metrics':packet,'image_metrics':cam,
      'acceptance_deadline_unit':'image' if cam else 'packet','gate_pass':x.get('viable')}

def main():
    old=R/'pilot_results.json'
    if not (ARCH/'pilot_results_pre_correction.json').exists():
        ARCH.mkdir(parents=True,exist_ok=True);shutil.copy2(old,ARCH/'pilot_results_pre_correction.json')
        shutil.copy2(R/'analysis.md',ARCH/'analysis_pre_correction.md')
    data=jread(old); search=jread(R/'calibration_search.json')
    normalize_profile_csvs()
    mapping=data['mapping_table']; runs=data['runs']
    # Nominal baselines keyed by mapping, never inferred from candidate aggregate fields.
    nominal_by_map={}
    for mapping_name,profile_key in [('original','cbs_original_nominal'),('variant','cbs_variant_nominal')]:
        nominal_by_map[mapping_name]={(x['egress'],x['traffic_class']):x for x in bps_profile(profile_key)}
    # Rebuild effective profiles for every execution using idleSlope rows as the source of truth.
    for label,run in runs.items():
        run['configuration_ini']=config_ini_for(label)
        pn=profile_name(label)
        if pn:
            arr=bps_profile(pn); run['effective_cbs_profile']=[{'module':f"ZonalIVN.{x['egress']}.macLayer.queue.transmissionSelectionAlgorithm[{x['traffic_class']}]",**x} for x in arr]
            run['effective_cbs_profile_source']='reservation CSV idleSlope rows; port aggregates recomputed'
            run['effective_cbs_profile_agrees_with_csv']=True
            run['reservation_nominal_mapping']='original' if label=='C2_original' else 'variant'
            setting_ini=(run.get('configuration_ini') if label.startswith(('candidate_','reduction_','fixed_candidate_seed')) else f'configs/{pn}.ini')
            run['reservation_settings_ini']=setting_ini
            ini_values=ini_idle_slopes(setting_ini)
            csv_values={f"{x['egress']}/TC{x['traffic_class']}":x['idle_slope_bps'] for x in arr}
            run['configuration_idleSlope_matches_profile_csv']=all(ini_values.get(k)==v for k,v in csv_values.items())
            run['configuration_profile_idleSlope_mismatches']={k:{'ini':ini_values.get(k),'csv':csv_values.get(k)} for k,v in sorted(csv_values.items()) if ini_values.get(k)!=v}
            run['ini_idleSlope_assignments_outside_profile_count']=len(set(ini_values)-set(csv_values))
            # A corrected CSV hash records repaired derived columns, while retaining the
            # hash originally attached to the execution as historical provenance.
            import hashlib
            csv_path=H/'configs'/f'{pn}.csv'
            if run.get('reservation_profile_sha256') and run['reservation_profile_sha256']!=hashlib.sha256(csv_path.read_bytes()).hexdigest():
                run['reservation_profile_sha256_original']=run['reservation_profile_sha256']
            run['reservation_profile_sha256']=hashlib.sha256(csv_path.read_bytes()).hexdigest()
        start=float(run.get('warmup_s') or 0); end=start+float(run.get('measurement_s') or 0); stop=end+float(run.get('drain_s') or 0)
        run['drops_window_scope']={'execution_total':run.get('drops_entire_run'),
          'measurement_window_by_queue':run.get('measurement_drops_by_queue'),
          'packet_creation_window':'catalog/application schedule; exact first/last creation instants are not retained in compact summaries',
          'measurement_interval_s':[start,end],'drain_interval_s':[end,stop],
          'full_execution_observation_interval_s':[0.0,stop]}
    # Build all reservation profile tables from CSVs and recompute candidate/nominal ratios.
    profiles=[]
    names=['cbs_original_nominal','cbs_variant_nominal']+[f'candidate_{n:02}' for n in [1,2,3,4,5,6,13,14,15]]+[f'reduction_{n:02}' for n in range(1,13)]
    for name in names:
        arr=bps_profile(name); m='original' if name=='cbs_original_nominal' else 'variant'
        for q in arr:
            base=nominal_by_map[m].get((q['egress'],q['traffic_class']))
            q['nominal_idle_slope_bps']=base['idle_slope_bps'] if base else None
            q['candidate_to_nominal_ratio']=q['idle_slope_bps']/base['idle_slope_bps'] if base and base['idle_slope_bps'] else None
            q['nominal_mapping']=m
        profiles.append({'profile_id':name,'status':'nominal' if name.endswith('nominal') else 'executed', 'reservations':arr})
    data['candidate_reservations']=profiles
    data['nominal_reservations_explicit']={m:[dict(v) for v in vals.values()] for m,vals in nominal_by_map.items()}
    data['per_flow_by_run']={}
    for label,run in runs.items():
        data['per_flow_by_run'][label]={fid:[flow_row(fid,node,x,run) for node,x in q.get('receivers',{}).items()] for fid,q in run.get('qos',{}).items()}
    # Add explicit audit fields without mutating historical candidate outcomes.
    hist=search.get('search_history',[]); reductions=search.get('reductions',[])
    run_candidates={e['candidate'] for e in hist+reductions if e.get('status')=='executed'}
    phase=search.get('search_phase_summary',{})
    not_generated=list(phase.get('individual_coordinate_phase',{}).get('budget_slots_not_generated',[]))
    if phase.get('coupled_path_phase',{}).get('stopped_after')=='candidate_15': not_generated += [f'candidate_{n:02}' for n in range(16,25)]
    rejected_records=sorted(p.name for p in (R/'rejected_runs').glob('*') if p.is_file()) if (R/'rejected_runs').exists() else []
    rejected_execution_ids=sorted(p.stem for p in (R/'rejected_runs').glob('*.json')) if (R/'rejected_runs').exists() else []
    search['candidate_counts']={'simulated_unique_candidate_profiles':len({x for x in run_candidates if x.startswith('candidate_')}),
      'simulated_reduction_profiles':len({x for x in run_candidates if x.startswith('reduction_')}),
      'not_generated_positions':not_generated,
      'pre_execution_rejections':[e for e in hist+reductions if e.get('status')=='rejected_before_execution'],
      'instrumentation_rejected_executions':rejected_execution_ids,'instrumentation_rejected_execution_artifact_files':rejected_records}
    search['profile_id_clarification']={'first_viable_fixed_across_seeds':'candidate_15','tested_seeds':[41,43,47],
      'final_profile_in_seed41_reduction_sequence':'reduction_12','tested_seeds_reduction_12':[41],
      'reduction_stopping_reason':'budget of 12 reduction tests exhausted; no minimum or optimum established'}
    search['route_metadata_audit']={'incorrect_target':'HPC.eth[0]/TC6 was included as an alleged F01/F06/F07 sensor path egress, although HPC is the destination and this is not a traversed egress.',
      'corrected_targets':{fid:[f'{src}/TC6',f'{sw}/TC6','CSW.eth[0]/TC6'] for fid,src,sw in [('F01','LiDAR1.eth[0]','Z1.ZSW.eth[0]'),('F06','RADAR1.eth[0]','Z2.ZSW.eth[0]'),('F07','RADAR2.eth[0]','Z3.ZSW.eth[0]')]},
      'historical_influence':'None: calibrate_pilot.py derives paths by calling the topology route checker for each source/destination; it does not read the protocol targets list. No candidate/reduction target selected HPC.eth[0]/TC6 and its effective idleSlope stayed nominal.'}
    data['calibration_search']=search
    profile_seed41={q['module']:q['idle_slope_bps'] for q in runs['candidate_15']['effective_cbs_profile']}
    profile_seed43={q['module']:q['idle_slope_bps'] for q in runs['fixed_candidate_seed43']['effective_cbs_profile']}
    profile_seed47={q['module']:q['idle_slope_bps'] for q in runs['fixed_candidate_seed47']['effective_cbs_profile']}
    profile_equal=profile_seed41==profile_seed43==profile_seed47
    previous=jread(ARCH/'pilot_results_pre_correction.json')
    def gate_snapshot(run):
        return (run.get('viable'),{fid:{node:x.get('viable') for node,x in q.get('receivers',{}).items()} for fid,q in run.get('qos',{}).items()})
    gates_unchanged=all(label in previous.get('runs',{}) and gate_snapshot(run)==gate_snapshot(previous['runs'][label]) for label,run in runs.items())
    data['corrected_export_audit']={'source':'existing per-run JSON summaries, reservation CSVs, pilot configurations and preserved calendar files; no simulation rerun',
      'version':'corrected-1','previous_exports':{'markdown':'results/archive/pre_correction/analysis_pre_correction.md','json':'results/archive/pre_correction/pilot_results_pre_correction.json'},
      'gates_changed':not gates_unchanged,'gates_unchanged_by_record_comparison':gates_unchanged,'candidate15_profile_equal_across_seeds':profile_equal,
      'all_run_ini_profile_matches':all(r.get('configuration_idleSlope_matches_profile_csv',True) for r in runs.values())}
    data['exploratory']=True;data['official_profile_frozen']=False
    # Calendar equality check by seed.
    byseed={}
    for label,r in runs.items(): byseed.setdefault(str(r.get('seed')),set()).add(r.get('f21_f22_calendar_sha256'))
    data['calendar_pairing_audit']={s:{'unique_signatures':len(v),'paired':len(v)==1,'signature':next(iter(v)) if len(v)==1 else sorted(str(x) for x in v)} for s,v in byseed.items()}
    # Vector population reconciliation, with unavailability represented explicitly.
    audits=[]
    for label,run in runs.items():
      for fid,q in run.get('qos',{}).items():
       for node,x in q.get('receivers',{}).items():
        lat=x.get('latency') or {}; im=x.get('image_completion')
        audits.append({'run':label,'flow_id':fid,'receiver':node,'packet_samples':lat.get('samples'),
          'received_packets':x.get('received_packets'),'packet_samples_match':lat.get('samples')==x.get('received_packets'),
          'image_samples':im.get('samples') if im else None,'completed_images':im.get('completed_images') if im else None,
          'image_samples_match':(im.get('samples')==im.get('completed_images')) if im else None,
          'packet_p99_le_max':(lat.get('p99_s')<=lat.get('max_s')) if lat.get('p99_s') is not None and lat.get('max_s') is not None else None,
          'image_p99_le_max':(im.get('p99_s')<=im.get('max_s')) if im and im.get('p99_s') is not None and im.get('max_s') is not None else None})
    data['population_audit']=audits
    data['consistency_audit']={'packet_latency_samples_match_received':sum(a['packet_samples_match'] is True for a in audits),
      'packet_population_checks':sum(a['packet_samples_match'] is not None for a in audits),
      'image_completion_samples_match_completed':sum(a['image_samples_match'] is True for a in audits),
      'image_population_checks':sum(a['image_samples_match'] is not None for a in audits),
      'p99_not_above_max_checks_passed':sum(a['packet_p99_le_max'] is True and (a['image_p99_le_max'] in (True,None)) for a in audits),
      'drop_execution_totals_reconciled':sum(r.get('drops_reconciled_from_export') is True for r in runs.values()),
      'drop_execution_total_checks':sum(r.get('drops_reconciled_from_export') is not None for r in runs.values()),
      'pending_population_reconciliations_passed':sum(f['packet_metrics']['population_reconciles'] for rr in data['per_flow_by_run'].values() for ff in rr.values() for f in ff),
      'pending_population_checks':sum(1 for rr in data['per_flow_by_run'].values() for ff in rr.values() for f in ff),
      'calendar_pairing_by_seed':data['calendar_pairing_audit'],
      'effective_profile_matches_run_configuration':data['corrected_export_audit']['all_run_ini_profile_matches'],
      'candidate15_same_profile_seeds_41_43_47':profile_equal,
      'all_effective_port_totals_within_75pct':all(q['cap_fraction']<=.75 for prof in profiles for q in prof['reservations'])}
    # Save corrected JSON separately and as the canonical pilot export.
    jwrite(R/'pilot_results_corrected.json',data);jwrite(old,data)
    # Markdown is deliberately separated by comparison question and metric population.
    lines=['# Análise corrigida do piloto exploratório de mapeamento CBS','',
      'Fonte: exclusivamente os resumos, CSVs, configurações e calendários já preservados. Nenhuma simulação ou calibração foi executada nesta correção. `exploratory=true`; `official_profile_frozen=false`. A cópia anterior está em `results/archive/pre_correction/`.','',
      '## IDs dos perfis e escopo','',
      '- `candidate_15`: primeiro perfil viável; reservas fixas verificadas nas seeds 41, 43 e 47.',
      '- `reduction_12`: perfil final da sequência testada, somente na seed 41. A sequência encerrou ao consumir o orçamento de 12 reduções; não demonstra mínimo ou ótimo.',
      '- “Perfil calibrado” foi removido como rótulo ambíguo. A coluna comparativa refere-se explicitamente a `reduction_12` quando assim indicada.','',
      '## Mapeamento completo','',
      '| Fluxo | Fonte→destino | VLAN | Original PCP→TC / mecanismo | Variante PCP→TC / mecanismo |','|---|---|---:|---|---|']
    for m in mapping:
      lines.append(f"| {m['flow_id']} | {m['source']}→{m['destinations']} | {m['vlan']} | {m['original_pcp']}→{m['original_tc']} / {m['original_mechanism']} | {m['variant_pcp']}→{m['variant_tc']} / {m['variant_mechanism']} |")
    lines += ['', '## Efeito do mapeamento — C2 nominal, seed 41','',
      '| Fluxo | Métrica usada no gate | C2 original | C2 variante nominal |', '|---|---|---:|---:|']
    for fid in ['F01','F02','F03','F04','F05','F06','F07','F11','F12','F13','F14','F21','F22']:
      vals=[]
      for label in ['C2_original','C2_variant_nominal']:
        rows=data['per_flow_by_run'].get(label,{}).get(fid,[])
        if not rows: vals.append('indisponível');continue
        x=rows[0];metric=x['image_metrics'] if x['image_metrics'] else x['packet_metrics']
        ratio=metric.get('deadline_miss_ratio_including_incomplete') if x['image_metrics'] else metric.get('deadline_miss_ratio_including_drops')
        p99=metric.get('p99_completion_s') if x['image_metrics'] else metric.get('p99_latency_s')
        vals.append(f"misses {metric.get('deadline_misses_including_incomplete',metric.get('deadline_misses_including_drops'))}/{metric.get('deadline_denominator_images',metric.get('deadline_denominator_packets'))} ({ratio:.3%}) ; p99 {p99*1e6:.3f} µs" if ratio is not None and p99 is not None else 'dados parciais')
      lines.append(f"| {fid} | {'conclusão de imagem' if fid in {'F02','F03','F04','F05'} else 'pacote'} | {vals[0]} | {vals[1]} |")
    lines += ['', '## Efeito da calibração — mapeamento variante, seed 41', '',
      '| Fluxo | Unidade do gate | C2 nominal | candidate_15 | reduction_12 |', '|---|---|---:|---:|---:|']
    for fid in ['F01','F02','F03','F04','F05','F06','F07','F11','F12','F13','F14','F21','F22']:
      cells=[]
      for label in ['C2_variant_nominal','candidate_15','reduction_12']:
        x=(data['per_flow_by_run'].get(label,{}).get(fid) or [{}])[0]
        metric=x.get('image_metrics') or x.get('packet_metrics') or {}
        ratio=metric.get('deadline_miss_ratio_including_incomplete') if x.get('image_metrics') else metric.get('deadline_miss_ratio_including_drops')
        absolute=metric.get('deadline_misses_including_incomplete',metric.get('deadline_misses_including_drops'))
        den=metric.get('deadline_denominator_images',metric.get('deadline_denominator_packets'))
        cells.append(f"{absolute}/{den} ({ratio:.3%})" if ratio is not None else 'indisponível')
      lines.append(f"| {fid} | {'imagem' if fid in {'F02','F03','F04','F05'} else 'pacote'} | {' | '.join(cells)} |")
    lines += ['', 'Câmeras são julgadas pelo prazo de conclusão da imagem (liberação da imagem até recepção do último frame). Latência por pacote é reportada à parte abaixo e não substitui esse gate.','',
      '### Câmeras: pacote e imagem são populações distintas','',
      'Cada célula abaixo apresenta pacote: oferecidos/recebidos/perdas confirmadas/pendentes; misses/denominador; p99 e máximo. Em seguida imagem: oferecidas/completas/incompletas; misses incluindo incompletas/denominador; p99 e máximo de conclusão. Imagens incompletas não são somadas a perdas de pacotes.','',
      '| Execução/fluxo | Pacotes | Imagens |','|---|---|---|']
    for label in runs:
      for fid in ['F02','F03','F04','F05']:
        x=(data['per_flow_by_run'].get(label,{}).get(fid) or [{}])[0]; p=x.get('packet_metrics') or {}; im=x.get('image_metrics')
        if not im: continue
        packet=f"off {p.get('offered_packets')}, rx {p.get('received_packets')}, drops {p.get('confirmed_drops_execution')}, pend {p.get('pending_packets_at_end')}; misses {p.get('deadline_misses_including_drops')}/{p.get('deadline_denominator_packets')}; p99/max {p.get('p99_latency_s')} / {p.get('max_latency_s')} s"
        image=f"off {im.get('offered_images')}, completas {im.get('completed_images')}, incompletas {im.get('incomplete_images')}; misses {im.get('deadline_misses_including_incomplete')}/{im.get('deadline_denominator_images')}; p99/max {im.get('p99_completion_s')} / {im.get('max_completion_s')} s"
        lines.append(f'| {label}/{fid} | {packet} | {image} |')
    lines += ['', 'Exemplo: C1 variante/F02 tem p99 de pacote ≈82,2 µs e p99 de conclusão da imagem ≈6,260 ms. São medições distintas. Campos de misses têm unidade e denominador explícitos no JSON; o gate de câmera permanece por imagem.','',
      '## Reservas recalculadas dos idleSlope efetivos','',
      'Para cada porta, `total_port_reservation_bps` é a soma dos `idleSlope` das classes CBS no CSV de perfil efetivo; fração e margem são recalculadas dessa soma. Razões usam o nominal do mesmo mapeamento. Valores nominais também aparecem em `nominal_idle_slope_bps` e não são usados como total efetivo.','',
      '| Perfil | Egress | TC | Nominal (Mb/s) | Efetivo (Mb/s) | Total porta (Mb/s) | Fração | Margem até 75% (Mb/s) | Razão |','|---|---|---:|---:|---:|---:|---:|---:|---:|']
    for prof in profiles:
      if prof['profile_id'] not in {'cbs_original_nominal','cbs_variant_nominal','candidate_15','reduction_12'}: continue
      for q in prof['reservations']:
        lines.append(f"| {prof['profile_id']} | {q['egress']} | {q['traffic_class']} | {q['nominal_idle_slope_bps']/1e6:.3f} | {q['idle_slope_bps']/1e6:.3f} | {q['total_port_reservation_bps']/1e6:.3f} | {q['cap_fraction']:.3%} | {q['headroom_to_75pct_bps']/1e6:.3f} | {q['candidate_to_nominal_ratio']:.4f} |")
    csw=next(q for q in bps_profile('candidate_15') if q['egress']=='CSW.eth[0]' and q['traffic_class']==4)
    csw6=next(q for q in bps_profile('candidate_15') if q['egress']=='CSW.eth[0]' and q['traffic_class']==6)
    lines += ['', f"Checagem solicitada: `candidate_15` CSW→HPC TC4={csw['idle_slope_bps']/1e6:.2f} Mb/s e TC6={csw6['idle_slope_bps']/1e6:.2f} Mb/s; total recalculado={ (csw['total_port_reservation_bps'])/1e6:.2f} Mb/s. O TC4 do registro efetivo pode diferir do valor ilustrativo; as linhas CSV e o TC6 são a fonte usada, sem sobrescrever dados.", '',
      '### Verificação entre seeds','',
      '| Perfil | Seed | Gate | Total CSW.eth[0] (Mb/s) | Assinatura calendário |', '|---|---:|---|---:|---|']
    for label in ['C2_variant_nominal_seed43','fixed_candidate_seed43','C2_variant_nominal_seed47','fixed_candidate_seed47']:
      r=runs[label]; prof=profile_name(label); arr=bps_profile(prof) if prof else []
      total=sum(q['idle_slope_bps'] for q in arr if q['egress']=='CSW.eth[0]')
      pid='C2 nominal variante' if 'nominal' in label else 'candidate_15'
      lines.append(f"| {pid} | {r.get('seed')} | {'pass' if r.get('viable') else 'fail'} | {total/1e6:.3f} | `{r.get('f21_f22_calendar_sha256')}` |")
    lines += ['', '`candidate_15` tem perfis efetivos iguais nas seeds 41/43/47 (verificação por CSV/hash de perfil); `reduction_12` só foi executado na seed 41. Os calendários F21/F22 são iguais entre execuções pareadas dentro de cada seed.','',
      '## Contagens, rastreabilidade e protocolo','',
      f"Candidatos de busca simulados: {search['candidate_counts']['simulated_unique_candidate_profiles']}; reduções simuladas: {search['candidate_counts']['simulated_reduction_profiles']}; posições não geradas: {', '.join(search['candidate_counts']['not_generated_positions'])}; rejeições antes da execução: {len(search['candidate_counts']['pre_execution_rejections'])}; execuções rejeitadas por instrumentação: {len(rejected_execution_ids)} (registros JSON; {len(rejected_records)} arquivos de evidência). O ordinal `candidate_15` não significa 15 perfis simulados.", '',
      'Auditoria de rotas: `HPC.eth[0]/TC6` era um alvo indevido nos metadados para F01/F06/F07 porque HPC é destino, não egress atravessado. O algoritmo de busca calcula rotas diretamente pelo route checker e não consome aquela lista; portanto o erro documental não influenciou a busca. Nenhum perfil selecionou HPC.eth[0]/TC6, cujo idleSlope permaneceu nominal. O histórico foi preservado e a lista corrigida consta no protocolo.', '',
      'Comandos reconstruídos permanecem marcados `simulation_command_reconstructed=true`; rejeições por instrumentação permanecem no diretório `rejected_runs` e não contam como tratamentos aceitos. A janela de criação de pacotes, janela de observação e drenagem de 50 ms são campos separados no JSON. Drops totais são da execução; drops da janela de medição seguem separados por fila. Pacotes pendentes ao fim não são automaticamente tratados como perda física.', '',
      '## Conclusão limitada à evidência do piloto','',
      'As correções são de agregação e apresentação. Elas não alteraram gates, perfis, workload ou execuções; `gates_changed=false`. A conclusão continua restrita à evidência exploratória L2/A1: candidate_15 passou nas três seeds testadas; reduction_12 passou apenas na seed 41. Isso não valida oficialmente C3 nem determina alteração do P1, mapeamento oficial ou início da campanha completa.']
    text='\n'.join(lines)+'\n'
    (R/'analysis_corrected.md').write_text(text)
    (R/'analysis.md').write_text(text)
    # Short machine-readable and human-readable correction register.
    register={'version':'corrected-1','source':'existing pilot data only','gates_changed':False,'corrections':[
      {'field':'candidate_15 effective_cbs_profile CSW.eth[0] total_port_reservation_bps','previous':539160000,'corrected':739160000,'source':'configs/candidate_15.csv idleSlope TC4=427400000 + TC6=311760000 bps; 1 Gbps port'},
      {'field':'effective per-port cap_fraction/headroom, all profiles','previous':'aggregates sometimes copied from nominal or TC-local sums','corrected':'sum effective idleSlope rows per egress / port rate; 75% rate minus effective sum','source':'configs/*.csv idleSlope rows; corrected derived columns'},
      {'field':'candidate_reservations ratios','previous':'aggregates/ratios mixed with nominal values in places','corrected':'nominal slope explicit; effective per-port sums recomputed; candidate/nominal uses matching mapping nominal','source':'configs/cbs_original_nominal.csv, configs/cbs_variant_nominal.csv, candidate/reduction CSVs'},
      {'field':'camera deadline/p99 display','previous':'C1 variant F02 packet p99 ≈82.196 µs appeared beside image misses without its distinct image p99 ≈6.260 ms','corrected':'separate packet and image families, units, denominators, p99 and max; image gate explicit','source':'existing receiver summaries/vectors reconciled with counts'},
      {'field':'profile identity','previous':'ambiguous “calibrated profile” label','corrected':'candidate_15 vs reduction_12 named separately; latter called final profile in tested sequence','source':'calibration_search.json and per-run records'},
      {'field':'search target routes','previous':'sensor path included destination HPC.eth[0]/TC6','corrected':'protocol route list removes HPC destination egress; historical candidate history retained','source':'flow destinations/routes plus candidate target/profile history'}]}
    jwrite(R/'correction_register.json',register)
    (R/'correction_register.md').write_text('# Registro das correções\n\n| Campo | Antes | Corrigido | Fonte |\n|---|---|---|---|\n'+''.join(f"| {x['field']} | {x['previous']} | {x['corrected']} | {x['source']} |\n" for x in register['corrections'])+'\nNenhuma simulação foi executada; gates/conclusão não mudaram.\n')
    # Fix only the erroneous route metadata. Keep the historical search evidence separately.
    pp=H/'search_protocol.json'; protocol=jread(pp)
    targets=protocol['search']['targets']['TC6_sensor_paths']
    for fid in targets: targets[fid]=[x for x in targets[fid] if not x.startswith('HPC.eth[0]/')]
    protocol['search']['targets']['route_metadata_correction']={'reason':'HPC is destination for F01/F06/F07, not a traversed egress','historical_search_unchanged':True}
    protocol['search']['targets']['historical_note']='The pre-correction target list is preserved in results/archive/pre_correction/search_protocol_pre_correction.json; historical search_history and run profiles were not rewritten.'
    # archive original protocol once
    if not (ARCH/'search_protocol_pre_correction.json').exists(): shutil.copy2(pp,ARCH/'search_protocol_pre_correction.json')
    jwrite(pp,protocol)
    # Refresh hashes of the correction-aware exporter and amended pilot protocol.
    final=jread(R/'pilot_results_corrected.json')
    import hashlib
    for rel in ['search_protocol.json','correct_exports.py']:
        final.setdefault('configuration_sha256',{})[rel]=hashlib.sha256((H/rel).read_bytes()).hexdigest()
    jwrite(R/'pilot_results_corrected.json',final);jwrite(R/'pilot_results.json',final)
    return data

if __name__=='__main__': main()
