#!/usr/bin/env python3
"""Build editorial synthesis derivatives from the frozen analysis inputs.

This script only reads simulation reports/derived CSVs and paper.tex. It never
launches a simulator or changes campaign inputs.
"""
from __future__ import annotations

import csv
import hashlib
import json
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PAPER = Path('/home/jonatan/Downloads/paper.tex')
SUMMARY = HERE / 'results_summary.json'
METRICS = HERE / 'execution_metrics.csv'
PAIRS = HERE / 'paired_comparisons.csv'
PROVENANCE = HERE / 'provenance_manifest.json'
C4_CUTOFF = HERE / 'c4_cutoff.json'

LABEL = {'C0': 'C0', 'C1': 'C1', 'C3': 'C2', 'C4': 'C3'}
HISTORIC = {'C0': 'C0', 'C1': 'C1', 'C2': 'C3', 'C3': 'C3', 'C4': 'C4'}

def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def read_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))

def read_csv(path: Path):
    with path.open(newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))

def write_csv(path: Path, fields, rows):
    with path.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        w.writeheader(); w.writerows(rows)

def fnum(row, key, default=None):
    try:
        return float(row[key])
    except (KeyError, ValueError, TypeError):
        return default

def fmt(v, n=3):
    return 'n/a' if v is None else f'{v:.{n}f}'

def main():
    summary = read_json(SUMMARY)
    provenance = read_json(PROVENANCE)
    c4_cut = read_json(C4_CUTOFF)
    runs = read_csv(METRICS)
    pairs = read_csv(PAIRS)
    paper_hash = sha(PAPER) if PAPER.exists() else None

    # Editorial coverage table. Preserve the original treatment in a separate column.
    cov_rows = []
    for p in summary['coverage']['positions']:
        old = p['treatment']
        cov_rows.append({
            'paper_treatment': LABEL.get(old, old), 'campaign_treatment': old,
            'load': p['load'], 'alignment': p['alignment'],
            'planned': p['planned_positions'], 'completed_valid_included': p['completed_valid_included'],
            'approved': p['top_level_viable'], 'valid_performance_reprovals': p['valid_performance_reprovals'],
            'stability_failures': p['stability_failures'], 'in_progress_excluded': p.get('in_progress_at_cutoff_excluded', 0),
            'pending': p.get('pending_not_started', 0), 'rejected_by_triage': p.get('rejected_by_triage', 0),
            'status': p['status'], 'seeds': ''
        })
    by_cell = defaultdict(list)
    for r in runs:
        by_cell[(LABEL.get(r['treatment'], r['treatment']), r['load'], r['alignment'])].append(r['seed'])
    for c in cov_rows:
        c['seeds'] = ';'.join(sorted(set(by_cell[(c['paper_treatment'], c['load'], c['alignment'])]), key=int))
    write_csv(HERE / 'coverage_editorial.csv', list(cov_rows[0]), cov_rows)

    # Small run-level table for figures/claims; it retains the run as the unit.
    metric_fields = ['execution_id','treatment','load','alignment','seed','calendar_signature','profile_sha256',
                     'simulator_binary_sha256','top_level_viable','technical_valid','sampled_sync_viable',
                     'continuous_sync_status','queue_overflow_drop_total_reported','measurement_window_drop_packets_reported',
                     'packet_loss_receiver_sum','pending_packets_at_simulation_end','offered_packet_receiver_sum',
                     'received_packet_receiver_sum','offered_images_sum','completed_images_sum',
                     'image_deadline_misses_sum_derived','critical_noncamera_packet_p99_max_s',
                     'critical_noncamera_packet_max_max_s','brake_packet_p99_max_s','brake_packet_max_max_s',
                     'camera_image_p99_max_s','camera_image_max_max_s','reservation_profile_bps']
    run_rows = []
    for r in runs:
        q = dict(r); q['paper_treatment'] = LABEL.get(r['treatment'], r['treatment'])
        run_rows.append(q)
    metric_fields.insert(1, 'paper_treatment')
    write_csv(HERE / 'selected_run_metrics.csv', metric_fields, run_rows)

    # Camera cohort snapshots: aggregate counts are deliberately not treated as independent replications.
    camera_rows = [
      {'paper_treatment':'C0','campaign_treatment':'C0','load':'L3','alignment':'A1','flow':'F02','runs':30,'offered_packets':6750000,'received_packets':6530253,'lost_packets':219747,'offered_images':225000,'complete_images':5435,'incomplete_images':219565,'image_misses':219565,'conditional_image_p99_median_ms':2.926732,'caveat':'p99 only among complete-image survivors'},
      {'paper_treatment':'C1','campaign_treatment':'C1','load':'L3','alignment':'A1','flow':'F02','runs':30,'offered_packets':6750000,'received_packets':6750000,'lost_packets':0,'offered_images':225000,'complete_images':225000,'incomplete_images':0,'image_misses':0,'conditional_image_p99_median_ms':3.957601,'caveat':'all offered images complete'},
      {'paper_treatment':'C0','campaign_treatment':'C0','load':'L3','alignment':'A1','flow':'F05','runs':30,'offered_packets':6750000,'received_packets':6389855,'lost_packets':360145,'offered_images':225000,'complete_images':38906,'incomplete_images':186094,'image_misses':186094,'conditional_image_p99_median_ms':2.853340,'caveat':'p99 only among complete-image survivors'},
      {'paper_treatment':'C1','campaign_treatment':'C1','load':'L3','alignment':'A1','flow':'F05','runs':30,'offered_packets':6750000,'received_packets':6750000,'lost_packets':0,'offered_images':225000,'complete_images':225000,'incomplete_images':0,'image_misses':0,'conditional_image_p99_median_ms':3.979290,'caveat':'all offered images complete'},
    ]
    write_csv(HERE / 'camera_image_summary.csv', list(camera_rows[0]), camera_rows)

    # Exact CBS configuration summaries: C2 is extracted from each load-specific
    # finalized report; paper C3 uses the frozen absolute D3 profile manifest.
    camp = ROOT / 'simulations/campaigns/p1-v2-official-2026-10'
    c4_manifest = read_json(camp / 'c4_official/manifest.json')
    fixed_rows = c4_manifest['profile_parameters']
    bitrate = {r['egress']: int(r['bitrate_bps']) for r in fixed_rows}
    profile_rows = []
    old_c3_root = camp / 'results/final/C3'
    for load in ('L0','L1','L2'):
        candidates = sorted(old_c3_root.glob(f'{load}/A0/seed*/C3_{load}_A0_seed*/Validate_C2_*/c3-acceptance.json'))
        if not candidates:
            continue
        old_profile = read_json(candidates[0]).get('reservation_profile_bps', {})
        grouped = defaultdict(int)
        for key, rate in old_profile.items():
            port, tc = key.rsplit('/TC', 1)
            grouped[port] += int(rate)
        for key, rate in sorted(old_profile.items()):
            port, tc = key.rsplit('/TC', 1)
            cap = bitrate.get(port)
            total = grouped[port]
            profile_rows.append({'paper_treatment':'C2','campaign_treatment':'C3','load':load,'profile':'load-scaled calibrated CBS',
                                 'egress':port,'tc':tc,'idleSlope_bps':int(rate),'port_total_idleSlope_bps':total,
                                 'physical_rate_bps':cap,'reservation_fraction':total/cap if cap else None,
                                 'headroom_to_75pct_bps':0.75*cap-total if cap else None})
    grouped = defaultdict(int)
    for r in fixed_rows:
        grouped[r['egress']] += int(r['idleSlope_bps'])
    for r in fixed_rows:
        port=r['egress']; cap=int(r['bitrate_bps']); total=grouped[port]
        profile_rows.append({'paper_treatment':'C3','campaign_treatment':'C4','load':'all_L0-L2','profile':'D3_coordinated_20pct fixed absolute',
                             'egress':port,'tc':r['TC'],'idleSlope_bps':int(r['idleSlope_bps']),'port_total_idleSlope_bps':total,
                             'physical_rate_bps':cap,'reservation_fraction':total/cap,
                             'headroom_to_75pct_bps':0.75*cap-total})
    write_csv(HERE / 'reservation_profiles.csv', list(profile_rows[0]) if profile_rows else [], profile_rows)

    clock_rows=[]
    for run in summary['treatment_summary']['C4']['runs']:
        clocks=run.get('clock_summary') or {}
        for node, val in (clocks.get('nodes') or {}).items():
            clock_rows.append({'execution_id':run['execution_id'],'load':run['load'],'alignment':run['alignment'],'seed':run['seed'],
                               'node':node,'window_start_s':(clocks.get('window_s') or [None,None])[0],
                               'window_end_s':(clocks.get('window_s') or [None,None])[1],
                               'samples':val.get('samples'),'max_abs_offset_ns':1000*float(val.get('max_abs_offset_s',0)),
                               'violations_gt_1us':val.get('violations_gt_1us'),
                               'continuous_conformity':clocks.get('continuous_conformity'),
                               'sampling':clocks.get('sampling')})
    write_csv(HERE / 'c4_clock_samples.csv', list(clock_rows[0]) if clock_rows else [], clock_rows)

    # Pairwise run-level deltas of selected endpoints; source CSV includes all supported flow metrics.
    selected = []
    keep_flows = {'F02','F04','F05','F06','F07','F08','F09','F10'}
    keep_metrics = {'image_p99_s','image_miss_ratio_including_incomplete','packet_p99_s','packet_max_s','packet_loss_ratio','packet_misses_including_loss_ratio'}
    for r in pairs:
        if r.get('flow') in keep_flows and r.get('metric') in keep_metrics and r.get('included_in_paired_contrast') == 'True':
            q = dict(r)
            q['left_paper_treatment'] = LABEL.get(r.get('left_treatment',''), r.get('left_treatment',''))
            q['right_paper_treatment'] = LABEL.get(r.get('right_treatment',''), r.get('right_treatment',''))
            selected.append(q)
    write_csv(HERE / 'selected_paired_metrics.csv', list(selected[0]) if selected else [], selected)

    # Explicit official contrast paper C2 (historic C3) minus C0, which the
    # inherited general-purpose pair builder did not materialize as a CSV.
    old_c0 = summary['treatment_summary']['C0']['runs']
    old_c3 = summary['treatment_summary']['C3']['runs']
    run_index = {(r['load'],r['alignment'],int(r['seed']),r['treatment']):r for r in old_c0+old_c3}
    c2_c0_rows=[]
    metrics_to_pair=['offered','received','losses_offered_minus_received','packet_loss_ratio',
                     'deadline_misses_including_loss_ratio','deadline_misses_received','p99_latency_s',
                     'max_latency_s','goodput_payload_ratio','useful_throughput_mbps']
    for load in ('L0','L1','L2'):
        for alignment in ('A0','A1'):
            for seed in range(1001,1031):
                a=run_index.get((load,alignment,seed,'C0')); b=run_index.get((load,alignment,seed,'C3'))
                if not a or not b: continue
                same=a.get('calendar_signature')==b.get('calendar_signature')
                for fid in sorted(set(a.get('flow_metrics',{})) | set(b.get('flow_metrics',{}))):
                    ar=a.get('flow_metrics',{}).get(fid,{}).get('receivers',{})
                    br=b.get('flow_metrics',{}).get(fid,{}).get('receivers',{})
                    for receiver in sorted(set(ar)|set(br)):
                        av=ar.get(receiver,{}); bv=br.get(receiver,{})
                        for metric in metrics_to_pair:
                            x=av.get(metric); y=bv.get(metric)
                            if x is None and y is None: continue
                            try: delta=float(y)-float(x)
                            except (TypeError,ValueError): delta=None
                            c2_c0_rows.append({'paper_contrast':'C2_minus_C0','campaign_left':'C3','campaign_right':'C0',
                                'load':load,'alignment':alignment,'seed':seed,'flow':fid,'receiver':receiver,'metric':metric,
                                'C0_value':x,'paper_C2_value':y,'delta_C2_minus_C0':delta,'calendar_signature_match':same,
                                'pairing_basis':'same load/alignment/seed plus stored calendar signature; F21/F22 population checks in provenance_manifest.json'})
    write_csv(HERE / 'c2_vs_c0_paired.csv', list(c2_c0_rows[0]) if c2_c0_rows else [], c2_c0_rows)

    # Selected editorial claims and compact quantitative findings.
    claims = [
      ['Introduction gap: no controlled comparison under one zonal workload','The study has a useful fixed-benchmark comparison across shaping policies, two burst alignments, multiple loads and receiver/image outcomes.','Migge/Navet and Maile already compare traffic-shaping mechanisms; the manuscript-wide statement is too broad.','Restrict to the specific ZB-3T workload, alignment design and image-completion outcomes; avoid a universal novelty claim.','reformulate'],
      ['C0 is sensitive to aligned camera bursts at L3','C0 L3/A0: 30/30 viable; L3/A1: 0/30. In L3/A1, C0 reported 579,892 receiver packet losses, all attributed to CSW→HPC/TC4; F02 lost 219,747/6,750,000 packets and 219,565/225,000 images were incomplete.','Result applies to this benchmark/cell and the C0 software/replay caveat remains for C1 comparison.','Describe the observed alignment-associated failure boundary, not a universal alignment law.','keep_with_scope'],
      ['C1 pre-shaping rescues L3/A1 image delivery','C1 L3/A1: 30/30 viable, zero packet loss, all F02/F05 images complete; F02/F05 image p99 rises vs C0 L0/A0 by median +8.978/+14.134 ms.','C0/C1 binaries differ in traffic replay implementation; calendar signatures and F21/F22 populations match, but this is not a perfectly isolated causal contrast. Image p99 is conditional on complete images.','Present delivery/completeness and latency cost together.','keep_with_caveat'],
      ['C2 calibrated CBS extends viability vs nominal CBS','Not identifiable in this paper matrix: nominal CBS is not an included treatment. The calibrated treatment (historic C3) passes 59/180 across L0–L2, with 0/120 at L0/L1 and 59/60 at L2.','No nominal-CBS comparator; low-load failures include both TC4 drops and TC6 deadline misses without loss.','Remove any superiority-over-nominal claim; report transfer behavior across offered-load cells.','remove_or_restrict'],
      ['C3 joint CBS/TAS has broad viability','At cutoff, historic C4 has 90/90 passing, but only L0 is complete (60/60); L1 has 24/60 and L2 6/60. All 90 passed the included application/stability/sampled-sync checks.','L1/L2 are selected partial seed sets. C4-vs-C2 is a complete-policy contrast, not TAS-only. High-load performance is unknown.','Report as promising partial evidence, not broad validation.','restrict'],
      ['TAS improves brake timing','In paired L0/A0, C4 minus calibrated CBS (historic C3) brake packet p99 median is +57.594 µs F08, +57.996 µs F09 and +57.587 µs F10; C4 still meets 100 µs deadline, max observed 78.461 µs.','Policies also differ in reservations and gPTP; cannot attribute this effect only to TAS. No high-load C4 yet.','Do not claim improvement; report observed cost and remaining margin.','remove_or_restate'],
      ['No single treatment dominates across all metrics/regimes','C1 trades image completeness against longer completion tails; calibrated CBS fails at L0/L1 but passes almost all L2; C4 passes observed cells with brake-tail cost.','C4 partial and BE-specific trade-offs require full per-flow results; H5 not yet verified over full matrix.','State as a pattern compatible with the hypothesis, not a confirmed general result.','restrict'],
      ['Synchronization is compliant','C4 passed its sampled offset checks; continuous compliance is not verified. C0–C2 do not have directly comparable corrected clock records in these report metrics.','Sampling does not establish continuous conformance.','Use “passed sampled synchronization criterion”; explicitly mark continuous behavior not verified.','keep_with_precision'],
    ]
    write_csv(HERE / 'manuscript_claims_audit.csv', ['manuscript_claim','evidence_at_cutoff','limitation','editorial_action','decision'], [dict(zip(['manuscript_claim','evidence_at_cutoff','limitation','editorial_action','decision'],r)) for r in claims])

    findings = [
      ['F1','C0 alignment boundary','C0','L3','A0/A1','30 per cell','viability',30,0,'A0 30/30 vs A1 0/30; A1 records 579892 receiver packet losses; F02 loses 219747 packets and 219565/225000 images are incomplete.','Observed benchmark-specific alignment-associated degradation; C0 A1 reproves.'],
      ['F2','C1 delivery vs completion-tail tradeoff','C1−C0','L3','A1','30 paired','F02/F05 images','F02 225000/225000 complete under C1 vs 5435/225000 under C0; F05 225000 vs 38906.','F02 p99 median conditional image completion: C1 3.958 ms vs C0 2.927 ms among survivors.','Binary/replay difference limits causal attribution; percentiles conditional on complete-image cohort.'],
      ['F3','Calibrated CBS load transfer','C2 (historic C3)','L0–L2','A0/A1','180 total','viability',59,180,'0/120 L0/L1; 59/60 L2. C2−C0 is 180/180 calendar-paired; L0/A0 F06/F07 median p99 rises +183.315/+194.094 µs without sensor losses. L0/L1 includes 7396671 recorded measurement drops on TC4 queues.','Association with load-scaled reservations and fixed bursts is plausible, not isolated causal proof; no nominal CBS comparison.'],
      ['F4','Joint CBS/TAS partial official snapshot','C3 (historic C4)','L0–L2','A0/A1','90 included','viability',90,90,'L0 60/60; L1 24/60; L2 6/60. Current completed C4 maximum brake latency 78.461 µs against 100 µs (≥21.539 µs observed margin).','Only L0 complete; L1/L2 seeds are selected priority samples. Sampled sync passes; continuous not verified.'],
      ['F5','C4 brake-tail cost in available common pairs','C3−C2 (complete-policy comparison)','L0','A0','30 paired','brake packet p99 delta','F08 +57.594 µs; F09 +57.996 µs; F10 +57.587 µs median paired delta.','All observed C4 brakes stay below 100 µs; contrast changes CBS policy and gPTP as well as TAS.','Do not attribute delta solely to TAS.'],
    ]
    write_csv(HERE / 'key_findings.csv', ['id','finding','paper_treatment_or_contrast','load','alignment','n_runs','metric','numerator_or_value','denominator_or_reference','quantitative_result','interpretation_limit'], [dict(zip(['id','finding','paper_treatment_or_contrast','load','alignment','n_runs','metric','numerator_or_value','denominator_or_reference','quantitative_result','interpretation_limit'],r)) for r in findings])

    # Manuscript claims audit prose/spec for visual evidence.
    visual = """# Plano de evidências visuais para o ICIT\n\nNão gerei figuras finais nesta etapa. Recomendo três elementos principais, nesta ordem.\n\n1. **Matriz de aprovação e cobertura** — tabela/heatmap com papel C0–C3 nas linhas e carga×alinhamento nas colunas. Mostrar `aprovadas/incluídas` e `incluídas/planejadas` dentro de cada célula. C2 (artigo; diretório histórico C3) tem L3 rejeitado pelo limite de reservas; C3 (artigo; diretório histórico C4) tem L3 rejeitado na triagem de serviço. C3 parcial deve aparecer como parcial, jamais como 30/30. Inclua n, seeds e legenda distinta para não executado, pendente e inadmissível. Indispensável.\n\n2. **Entrega de imagens versus perdas e latência** — dois painéis para F02/F05 em C0/C1, focados em L3/A0 e L3/A1: barras empilhadas de imagens completas/incompletas (denominador imagens oferecidas) mais ponto/intervalo da mediana por execução do p99 de conclusão apenas entre completas; anotar o deadline aplicável. Evitar eixo comum que esconda incompletude; marcar que p99 é condicional. Não converter pacotes perdidos em imagens sem correspondência de coorte. Apresentar 30 execuções como n=30, sem intervalos construídos por pacotes. Indispensável.\n\n3. **Latência de fluxos críticos e custo do C3 combinado** — pontos por execução para F06/F07, F08–F10 em células selecionadas C2/C3; eixo y em µs, linhas de deadline (100 µs para os fluxos hard pertinentes), mediana e faixa entre execuções. Descrever C3−C2 como políticas completas. Como C3 atual é L0 completo e L1/L2 parcial, não desenhar células pendentes como zero; mostrar n ao lado de cada grupo. Complementar/indispensável conforme espaço.\n\nReservas configuradas podem aparecer numa tabela compacta de método (idleSlope por porta/TC, soma por porta e margem ao limite), não num scatter que implique consumo físico agregado entre saltos. Separar sincronização amostral de contínua.\n"""
    (HERE / 'visual_evidence_plan.md').write_text(visual, encoding='utf-8')

    # Editorial synthesis: source numbers are linked to compact run-level data in this directory.
    md = f"""# Síntese editorial dos resultados para o IEEE ICIT 2027\n\n**Recomendação:** mantenha o artigo como estudo experimental aplicado de TSN para comunicação automotiva/zonal, mas concentre a narrativa principal no efeito observado de alinhamento e pre-shaping sobre entrega de câmeras e no limite de transferibilidade da política CBS escalada. Apresente o tratamento combinado CBS/TAS como evidência promissora ainda parcial, não como validação abrangente ou melhoria causal atribuível a TAS. O tema se encaixa no ICIT por sistemas de comunicação industrial, redes de controle e transporte/automotivo; o encaixe depende de enfatizar requisitos de comunicação de um sistema ciberfísico veicular, não de alegar novidade de mecanismos.\n\n**Corte:** {summary['analysis_cutoff']} (fuso registrado nos artefatos). C4 foi congelado pelo ledger/checkpoint em 90 execuções concluídas válidas de 180 posições L0–L2; somente as 90 linhas concluídas com hashes de relatório conferidos entram nesta síntese. Não usei dados de uma execução ativa/incompleta. O estado do checkpoint no corte é `paused_technical_review`, com C4_L1_A0_seed1022 como falha técnica posterior à cobertura incluída.\n\n## Correspondência dos tratamentos\n\n| Nome editorial no manuscrito | Identificador histórico | Interpretação |\n|---|---|---|\n| C0 — Strict Priority | `C0` | SP; rajadas originais |\n| C1 — Source pre-shaping | `C1` | pré-formação na fonte |\n| C2 — Calibrated CBS | `C3` | CBS calibrado; não confundir com o CBS nominal histórico |\n| C3 — Joint CBS/TAS configuration | `C4` | perfil absoluto D3, gates TAS compartilhadas e SP nas saídas exclusivas dos freios |\n\nNão renomeei diretórios ou registros. Pilotos não foram somados às repetições oficiais.\n\n## Cobertura e validade\n\nA matriz cobre 28 células admissíveis × 30 execuções = 840 posições planejadas: C0 240/240; C1 240/240; C2 180/180 (L3/A0 e L3/A1 rejeitadas antes de simular pela triagem CBS); C3 90/180 (somente L0 completo, L1/L2 parciais). Das 750 execuções incluídas, 599 passaram os gates do tratamento e 151 foram reprovações válidas de desempenho: C0 210/240, C1 240/240, C2 59/180, C3 90/90 no recorte disponível. A contagem não extrapola aprovação a posições pendentes.\n\n| Tratamento editorial | L0/A0 | L0/A1 | L1/A0 | L1/A1 | L2/A0 | L2/A1 | L3/A0 | L3/A1 |\n|---|---:|---:|---:|---:|---:|---:|---:|---:|\n| C0 | 30/30 | 30/30 | 30/30 | 30/30 | 30/30 | 30/30 | 30/30 | 0/30 |\n| C1 | 30/30 | 30/30 | 30/30 | 30/30 | 30/30 | 30/30 | 30/30 | 30/30 |\n| C2 (hist. C3) | 0/30 | 0/30 | 0/30 | 0/30 | 30/30 | 29/30 | inadmissível | inadmissível |\n| C3 (hist. C4) | 30/30 | 30/30 | 21/21 | 3/3 | 3/3 | 3/3 | inadmissível | inadmissível |\n\nC3 seeds em L1/A0 são 1001–1021; L1/A1, L2/A0 e L2/A1 usam 1001, 1015 e 1030. C3 L3 foi rejeitado na triagem de serviço do perfil absoluto, não por ultrapassar o teto de 75% de reserva. A matriz integral está em [coverage_editorial.csv](coverage_editorial.csv).\n\n## Achados essenciais\n\n**1. Alinhamento expõe uma fronteira de falha de SP em L3.** Em C0, L3/A0 passou 30/30, enquanto L3/A1 passou 0/30. Para A1, os relatórios registram 579.892 perdas no receptor, localizadas em CSW→HPC/TC4; F02 perdeu 219.747 de 6.750.000 pacotes (3,26%) e 219.565 das 225.000 imagens ficaram incompletas (97,58%). Isso é evidência forte para este benchmark e célula, não uma lei geral sobre tráfego alinhado.\n\n**2. Pre-shaping recupera a entrega integral, com custo de latência de conclusão.** Em C1 L3/A1, 30/30 passaram; F02 e F05 receberam todos os 6.750.000 pacotes por fluxo, e as 225.000 imagens por fluxo foram completas. Em C0, F05 perdeu 360.145 pacotes e teve 186.094 imagens incompletas. Para F02, o total de pacotes perdidos excede as imagens incompletas em 182; a proximidade dos agregados não permite inferir quais pacotes pertenciam a quais imagens nem a distribuição das perdas por imagem sem rastreamento individual. Em baixa carga L0/A0, o p99 mediano de conclusão de imagem subiu em C1 versus C0 em 8,978 ms para F02 e 14,134 ms para F04 (pareado, n=30); ambos ainda dentro dos deadlines publicados para esses fluxos. Em L3/A1, o p99 calculado só entre imagens completas é condicionado aos sobreviventes, portanto não compara atendimento completo sem a taxa de incompletude. C0/C1 também têm diferença de binário/replay; assinaturas dos calendários e populações F21/F22 coincidem, mas isso limita uma atribuição causal estrita.\n\n**3. CBS calibrado por carga falha na baixa carga, mas funciona quase sempre em L2.** O tratamento C2 (histórico C3) passa 0/120 em L0/L1 e 59/60 em L2; a reprovação restante é estabilidade em L2/A1, sem perda de aplicação. Em L0/L1 há perdas/overflow TC4 e reprovações de estabilidade; na comparação pareada C2−C0 tem 180/180 assinaturas de calendário iguais; em L0/A0, p99 medianos de F06/F07 sob C2 são 213,39/219,17 µs contra 30,08/25,08 µs em C0 (diferenças +183,32/+194,09 µs), sem perdas desses sensores. Em L0/L1, no conjunto das 120 execuções low-load, foram reportadas 7.396.671 perdas de medição em TC4: Z2 uplink 3.226.611, Z1 uplink 2.927.874 e CSW→Z3 1.242.186. Separadamente, F06/F07 excedem deadline hard de 100 µs mesmo sem perdas: em L0/A0 os p99 medianos são 213,39/219,17 µs; em L2/A0, 58,94/53,97 µs. A política escala reservas com demanda permanente, enquanto os transientes F21/F22 e deadlines/tamanhos não escalam; isso é compatível com as falhas, mas os dados não isolam causalmente a escala como único mecanismo. Não há comparador oficial de CBS nominal neste artigo.\n\n**4. O resultado oficial atual de CBS/TAS é positivo, porém incompleto e com custo de cauda dos freios.** As 90 execuções concluídas de C3 (histórico C4) passam todas os gates de aplicação, estabilidade e sincronização amostral, sem perdas de receptor reportadas. L0 está completo (60/60); L1 tem 24/60 e L2 6/60. O máximo observado de latência dos freios foi 78,461 µs para deadline 100 µs (margem observada mínima 21,539 µs). Em pares comuns de L0/A0 com C2, p99 aumenta medianamente 57,594 µs (F08), 57,996 µs (F09) e 57,587 µs (F10), ainda sem perder o deadline. Como perfil CBS, sincronização e TAS diferem, isto é comparação de políticas completas. A sincronização é aprovada nas amostras: cada execução tem 184.800–184.820 amostras por nó na janela [1,31), com máximo absoluto de 50 ns entre nós e zero amostras acima de 1 µs; conformidade contínua não foi verificada. A série compacta está em [c4_clock_samples.csv](c4_clock_samples.csv).\n\nOs achados, tabelas e dados por execução estão em `key_findings.csv`, `selected_run_metrics.csv`, `selected_paired_metrics.csv` e `camera_image_summary.csv`. A unidade experimental é a execução; milhões de pacotes não são tratados como réplicas independentes. A tabela compacta completa de idleSlopes, totais por egress e margens até 75% está em [reservation_profiles.csv](reservation_profiles.csv); os totais são reservas configuradas em cada porta, não tráfego utilizado nem banda somável entre saltos. Por exemplo, em `HPC.eth[0]/TC4`, o perfil escalado C2 vai de 78,24 Mb/s (L0) a 144 Mb/s (L2), enquanto C3 fixa 406,375399 Mb/s; em `CSW.eth[3]/TC4`, C2 vai de 49,52 a 247,60 Mb/s, enquanto C3 fixa 707,606774 Mb/s. C3 reserva 70,76% da porta CSW.eth[3], ainda abaixo do limite de 75%, com 42,393 Mb/s de headroom configurável.\n\n## Pareamento, software e consistência dos relatórios\n\nCalendários e populações pareiam exatamente nos contrastes disponíveis: C0/C1 240/240 pares e 480/480 verificações F21/F22; C0/C2 180/180 pares e 360/360 verificações F21/F22; C1/C2 180/180; C2/C3 90/90 no recorte C4, com F21/F22 iguais em todos os testes auditados. A comparação C2/C3 continua sendo de políticas completas.\n\nC0 usa binário SHA-256 `68207064…ffc074`; C1 e C2 usam `ca8e9d75…ba32a7`. A diferença inclui a implementação de replay de calendário em `TrafficPlan.cc/.ned`; eventos gravados e populações pareadas reduzem a preocupação sobre o calendário aplicado, mas a diferença de software continua sendo uma limitação de C1−C0. O histórico dos primeiros 210 relatórios C0 não preserva todos os hashes de fonte do runner/extrator. Não descartei dados por diferença de hash isolada.\n\nOs 180 relatórios de C2 (histórico C3) têm perfil resolvido verificado, arquivos de validação, logs e SCA, com `simulated_in_this_attempt` em 176 e `reprocessed_existing_completed_raw_output` em quatro. Há, porém, divergência no fechamento: o shard manifest declara `all_records_technically_valid=false`/`incomplete_resumable` e seu campo de hash do ledger não corresponde a um ledger específico de 180 linhas; o ledger principal tem 447 registros incluindo tentativas de calibração. O `campaign_results.json` e os campos `treatment`/`campaign_treatment` também não usam a mesma nomenclatura. Assim, o conjunto de resultados por execução é corroborado, mas o fechamento canônico não é perfeitamente reconciliado. Isso afeta a afirmação de encerramento formal e a reprodutibilidade de proveniência, não os números relatados individualmente que têm artefatos de validação.\n\nO critério de estabilidade é operacional: seis médias temporais ponderadas de ocupação em bits para janelas consecutivas de 5 s dentro de [1,31) s; falha se as três últimas crescem estritamente (`q4<q5<q6`) e `q6−q4>0,05×capacidade` em qualquer fila. É um gate finito da campanha, não prova de estabilidade assintótica. Warm-up é excluído da janela de perdas e estabilidade; a drenagem vai até 31,05 s e não deve ser misturada com resultados de medição.\n\n## Avaliação editorial do manuscrito\n\nA comparação de quatro tratamentos forma uma história coerente para ICIT se for apresentada como avaliação aplicada, limitada ao benchmark fixo de rede veicular zonal. O título atual é adequado. A formulação da introdução “no controlled comparison exists” precisa ser qualificada e delimitada: Migge/Navet e Maile já comparam mecanismos em contextos relacionados. Restrinja a lacuna à combinação específica de topologia ZB-3T, catálogo, fatores de carga, alinhamentos e métricas de imagem/fluxos usada aqui. A frase de escopo de que apenas o tratamento muda também precisa ser precisa: C1 muda temporização de liberação das câmeras e C3 inclui relógios/gates; são políticas comparadas, não um experimento que isola sempre um mecanismo.\n\n| Afirmação | Recomendação | Motivo |\n|---|---|---|\n| Ausência geral de comparação controlada de mecanismos TSN | Restringir | Migge/Navet e Maile já comparam mecanismos; declarar a lacuna particular do benchmark/alinhamento. |\n| Alinhamento degrada entrega em SP e pre-shaping a recupera | Manter com escopo e ressalva | Forte em C0 L3 A0/A1 e C1 L3/A1; diferença de software C0/C1 e apenas um benchmark. |\n| CBS calibrado amplia fronteira sobre nominal | Remover | Não há CBS nominal no artigo; C2 passa 59/180 e falha nas 120 execuções L0/L1. |\n| TAS melhora timing dos freios | Reformular | C3−C2 não isola TAS; em L0/A0 a cauda aumenta ~58 µs, embora os deadlines passem. |\n| Nenhum tratamento domina | Restringir | Trade-offs observados são compatíveis, mas C3 parcial e sem BE/alta carga completa. |\n| Conformidade de sincronização | Precisar | Apenas amostras abaixo de 1 µs; contínua não verificada. |\n\nA frase “no controlled comparison exists” deve ser delimitada à combinação concreta de benchmark, alinhamento, carga e completude de imagem e qualificada como lacuna identificada pelos autores; a busca feita aqui não é uma revisão sistemática que prove inexistência. O artigo tem material empírico coerente para esse escopo, mas não deve vender contribuição como novo protocolo ou prova geral de superioridade. O eixo recomendado é entrega de aplicações sob alinhamento e shaping, com CBS entre cargas como contraste de limite/transferência; C3 combinado fica como resultado parcial. C2 nominal não é parte da análise, e não se pode afirmar calibração superior ao nominal.\n\n## Base recomendada para Results, Conclusions e Abstract\n\n### Results (ordem sugerida)\n\n1. **Sensibilidade de SP a A0/A1:** 30/30 versus 0/30 em C0 L3; quantificar 579.892 perdas e perdas/incompletude F02/F05; ressalvar domínio benchmark.\n2. **Pre-shaping:** C1 remove essas perdas/incompletudes na L3/A1, mas acrescenta 8,978 ms (F02) e 14,134 ms (F04) ao p99 de conclusão em L0/A0; mostrar todos os denominadores e deadline.\n3. **Transferência CBS por carga:** C2 0/120 em L0/L1 e 59/60 L2; separar TC4 overflow e F06/F07 p99 >100 µs sem perdas. Não comparar com nominal.\n4. **CBS/TAS parcial:** C3 90/90 no corte; 60/60 L0 e amostras de L1/L2; brake max 78,461 µs; contrastar p99 pareado +~58 µs com C2 como mudança de política completa.\n\n### Conclusions (até três)\n\n- Neste benchmark e protocolo, o alinhamento de rajadas de câmera torna SP insuficiente em L3/A1, e source pre-shaping restaura completude de imagens ao custo de maior latência de conclusão.\n- O CBS calibrado por carga não transfere bem para L0/L1 nesta implementação: coexistem overflow TC4 e deadline misses TC6; os dados apoiam uma fronteira empírica, não causalidade única nem comparação com CBS nominal.\n- A configuração CBS/TAS D3 é promissora nas execuções concluídas, mas ainda só tem L0 completamente coberto; não demonstra ganho sobre CBS e aumenta a cauda de freios em L0/A0 mantendo margem observada.\n\n### Abstract (elementos seguros, ainda não redigir)\n\nProblema: convivência de bursts de câmera/sensores e tráfego crítico em convergência zonal; método: comparação OMNeT++/INET de SP, pre-shaping, CBS calibrado e CBS/TAS num catálogo fixo e cargas/alinhamentos; cobertura no corte: 750 execuções incluídas, com C3 combinado parcial (90/180) e L3 excluídos por triagem para dois tratamentos; quantitativos seguros: C0 L3/A1 0/30 versus A0 30/30 e 579.892 perdas; C1 30/30 e imagens completas; C2 CBS 0/120 low-load e 59/60 L2; C3 no corte 90/90 mas apenas L0 completo. Contribuição: evidência experimental delimitada de trade-offs de alinhamento, conclusão de imagem e transferência de reserva, sem garantia analítica nem superioridade universal.\n\n## Literatura e aderência ao ICIT\n\nA literatura já cobre comparação de mecanismos TSN em contexto automotivo (Migge/Navet) e avaliação de mecanismos/efeitos sobre tráfego best effort (Maile et al. 2024, conforme citekey presumido); Luo contribui com arquitetura automotiva simulada; Leal Filho trata sobrecargas transientes ADAS; Ashjaei é referência de estado da arte. A contribuição defensável não é “primeira comparação” ou “CBS/TAS nunca testado”: é o conjunto de resultados por alinhamento, imagem completa e carga para esta topologia/catalogo, mais a observação de que uma política CBS escalada falha em baixa carga enquanto o perfil combinado C3 ainda está parcialmente verificado. O arquivo `.bib`/bibliografia usado pelo manuscrito não estava disponível na árvore lida; `maile2024` corresponde ao trabalho de comparação de mecanismos e best-effort indicado pelo título da seção relacionada, e `ashjaei2021` ao survey automotivo. A identidade exata de `leal2025` deve ser conferida no `.bib` antes de finalizar citações. Leal Filho et al. (ISCC 2025) foi identificado pelo DOI para contexto, mas o citekey não foi validado contra a bibliografia ausente.\n\nA aderência ao ICIT é boa se o framing ligar o estudo a comunicação industrial/veicular e sistemas ciberfísicos de tempo real; a chamada oficial inclui Automotive Control and Transportation Systems, Network-based Control Systems and Applications e a trilha de Industrial Automation, Communication, and Manufacturing. A página oficial indica prazo regular em 27/10/2026 às 23:59 BRT. Não inferir comportamento de hardware real diretamente do simulador nem reivindicar aceitação.

Fontes consultadas para delimitar a contribuição: [Migge/Navet et al. (2018), automotive AVB/TSN](https://orbilu.uni.lu/handle/10993/40623); [Navet et al. (2018), pre-shaping bursty transmissions](https://orbilu.uni.lu/handle/10993/38606); [Luo et al. (2022)](https://www.mdpi.com/1424-8220/22/12/4580); [Maile et al. (2024)](https://doi.org/10.1145/3688268.3688283); [Ashjaei et al. (2021)](https://doi.org/10.1016/j.sysarc.2021.102137); [Leal Filho et al. (ISCC 2025)](https://doi.org/10.1109/ISCC65549.2025.11326440); [ICIT 2027 official site](https://icit2027.ieee-ies.org/). The `.bib` file was not found, so final citekey-to-reference identity should still be checked.\n\n## Pendências materiais\n\n1. Concluir o corte da campanha C3 combinado nas células L1/L2 e as demais posições antes de generalizar para cargas maiores.\n2. Reconciliar o ledger/manifests finais do tratamento C2 (histórico C3) e manter os hashes/fontes de todas as execuções.\n3. Reduzir o confounding de software na interpretação causal C0−C1; resultados descritivos seguem úteis porque calendários/populações foram pareados.\n4. Conferir bibliografia exata e restringir a alegação de lacuna frente à literatura próxima.\n5. A sincronização contínua não foi demonstrada; não afeta gates de aplicação atuais, mas limita qualquer afirmação de conformidade de relógio além das amostras.\n\n**Resposta editorial:** os dados sustentam uma contribuição aplicada delimitada para ICIT, desde que a narrativa seja sobre trade-offs medidos em um benchmark veicular zonal e não sobre novidade universal de TSN. C4 não precisa superar C2 para o artigo ser coerente, mas sua campanha incompleta impede uma afirmação geral sobre L1/L2; se os dados finais divergirem, a discussão deve ser atualizada.\n\n### Fontes locais e reprodutibilidade\n\nOs dados derivados e scripts estão no diretório desta análise. Regerar os dados quantitativos e este documento sem iniciar simulação:\n\n```sh\npython3 simulations/analysis/icit2027_editorial_synthesis_2026-10-27/analyze_results.py\npython3 simulations/analysis/icit2027_editorial_synthesis_2026-10-27/build_editorial_outputs.py\n```\n\nOs resultados C4 são um corte congelado; não execute o script sobre dados parciais sem primeiro decidir se quer um novo corte.\n"""
    (HERE / 'icit_results_synthesis.md').write_text(md, encoding='utf-8')

    # Manifest for this editorial product. Hash derived data after writing all primary outputs.
    file_inputs = [SUMMARY, METRICS, PAIRS, PROVENANCE, C4_CUTOFF]
    if PAPER.exists(): file_inputs.append(PAPER)
    source_list = []
    for p in file_inputs:
        source_list.append({'path': str(p), 'sha256': sha(p), 'bytes': p.stat().st_size})
    manifest = {
      'created_at': datetime.now().astimezone().isoformat(timespec='seconds'),
      'analysis_cutoff': summary['analysis_cutoff'],
      'paper_file': str(PAPER), 'paper_sha256': paper_hash,
      'treatment_mapping': {'paper_C0':'campaign C0','paper_C1':'campaign C1','paper_C2':'historic campaign C3 (calibrated CBS)','paper_C3':'historic campaign C4 (joint CBS/TAS)'},
      'campaign_commit': provenance.get('campaign_commit_at_manifest'),
      'official_p1_path': provenance.get('p1_path'), 'official_p1_sha256': provenance.get('p1_sha256'),
      'c4_snapshot_id': provenance.get('c4_snapshot_id'), 'c4_snapshot_sha256': provenance.get('c4_snapshot_sha256'),
      'c1_archive': provenance.get('c1_archive'),
      'counts_by_campaign_treatment': {t:sum(r['treatment']==t for r in runs) for t in ['C0','C1','C3','C4']},
      'c4_cutoff_rows': c4_cut.get('completed_count') if isinstance(c4_cut,dict) else None,
      'sources': source_list,
      'included_execution_metrics': str(METRICS),
      'paired_metric_source': str(PAIRS),
      'regeneration_command': 'python3 simulations/analysis/icit2027_editorial_synthesis_2026-10-27/analyze_results.py && python3 simulations/analysis/icit2027_editorial_synthesis_2026-10-27/build_editorial_outputs.py',
      'no_simulations_started': True,
      'limitations': ['C4 is the frozen 90-run cutoff and should not be silently refreshed.', 'C2 closure/shard manifest has a schema/provenance inconsistency documented in the synthesis.', 'Bibliography file was not available; exact identities behind some citekeys need confirmation.']
    }
    output_paths = ['icit_results_synthesis.md','manuscript_claims_audit.csv','key_findings.csv','visual_evidence_plan.md',
                    'coverage_editorial.csv','selected_run_metrics.csv','selected_paired_metrics.csv','camera_image_summary.csv',
                    'reservation_profiles.csv','c4_clock_samples.csv','c2_vs_c0_paired.csv','results_summary.json','coverage.csv','paired_comparisons.csv',
                    'execution_metrics.csv','provenance_manifest.json','c4_cutoff.json','analyze_results.py','build_editorial_outputs.py']
    manifest['artifacts'] = [{'path': name, 'sha256': sha(HERE/name), 'bytes': (HERE/name).stat().st_size}
                             for name in output_paths if (HERE/name).is_file()]
    (HERE / 'analysis_manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')

if __name__ == '__main__':
    main()
