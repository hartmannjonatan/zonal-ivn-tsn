#!/usr/bin/env python3
"""Render the isolated C4 real-clock pilot report from its compact JSON evidence."""
from __future__ import annotations

import csv
import hashlib
import json
import pathlib
import shutil
import subprocess
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent
RESULTS = ROOT / "results"
DATA = RESULTS / "pilot_results.json"
PLAN = json.loads((RESULTS / "plan.json").read_text())
COLORS = {
    "B_local": "#475569", "R_cadence": "#2563eb",
    "RP_cadence_phase": "#7c3aed", "BM_recovery": "#059669",
    "RPM_combined": "#d97706", "C3_sync_control": "#dc2626",
}
LABELS = {
    "B_local": "B local", "R_cadence": "R cadence",
    "RP_cadence_phase": "RP cadence + phase", "BM_recovery": "BM +2% F13",
    "RPM_combined": "RPM phase +2% F13", "C3_sync_control": "C3 sync",
}
FOCUS_QUEUES = [
    "ZonalIVN.HPC.eth[0].macLayer.queue.queue[4]",
    "ZonalIVN.CSW.eth[1].macLayer.queue.queue[4]",
    "ZonalIVN.CSW.eth[2].macLayer.queue.queue[4]",
    "ZonalIVN.CSW.eth[3].macLayer.queue.queue[4]",
    "ZonalIVN.Z3.ZSW.eth[7].macLayer.queue.queue[4]",
]


def sha(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def fnum(value, digits=3):
    if value is None:
        return "—"
    return f"{value:.{digits}f}"


def svg_plot(data, plot_series, queue_name, title, out_path):
    width, height = 1100, 470
    left, right, top, bottom = 86, 30, 54, 72
    chart_w, chart_h = width - left - right, height - top - bottom
    run_values = {}
    ymax = 0.0
    for name, run in data["runs"].items():
        if queue_name == FOCUS_QUEUES[4]:
            vals = run["Z3_F13_queue"]["mean_occupancy_bits_5s"]
        else:
            q = next((x for x in run["all_queue_stability_metrics"] if x.get("queue") == queue_name), None)
            vals = q["mean_occupancy_bits_5s"] if q else []
        points = [(2.5 + 5 * i, val) for i, val in enumerate(vals)]
        run_values[name] = points
        ymax = max(ymax, max(v for _, v in points))
    ymax = max(ymax * 1.12, 1.0)
    x = lambda t: left + (t / 30.0) * chart_w
    y = lambda v: top + chart_h - (v / ymax) * chart_h
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
             '<rect width="100%" height="100%" fill="white"/>',
             f'<text x="{left}" y="30" font-family="sans-serif" font-size="20" font-weight="bold">{title}</text>']
    for j in range(6):
        yy = top + chart_h * j / 5
        val = ymax * (5 - j) / 5
        parts.append(f'<line x1="{left}" y1="{yy:.1f}" x2="{left+chart_w}" y2="{yy:.1f}" stroke="#e2e8f0"/>')
        parts.append(f'<text x="{left-12}" y="{yy+5:.1f}" text-anchor="end" font-family="sans-serif" font-size="12">{val:.0f}</text>')
    for j in range(7):
        xx = left + chart_w * j / 6
        parts.append(f'<line x1="{xx:.1f}" y1="{top}" x2="{xx:.1f}" y2="{top+chart_h}" stroke="#f1f5f9"/>')
        parts.append(f'<text x="{xx:.1f}" y="{top+chart_h+24}" text-anchor="middle" font-family="sans-serif" font-size="12">{j*5}</text>')
    parts.extend([f'<line x1="{left}" y1="{top+chart_h}" x2="{left+chart_w}" y2="{top+chart_h}" stroke="#334155"/>',
                  f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top+chart_h}" stroke="#334155"/>',
                  f'<text x="{left+chart_w/2}" y="{height-14}" text-anchor="middle" font-family="sans-serif" font-size="13">Tempo de medição (s)</text>',
                  f'<text transform="translate(18 {top+chart_h/2}) rotate(-90)" text-anchor="middle" font-family="sans-serif" font-size="13">Ocupação média da fila (bits; bins de 1 ms)</text>'])
    for name, points in run_values.items():
        coords = " ".join(f"{x(t):.1f},{y(v):.1f}" for t, v in points)
        parts.append(f'<polyline fill="none" stroke="{COLORS[name]}" stroke-width="1.7" points="{coords}"/>')
    lx, ly = left + 8, height - 42
    for idx, name in enumerate(run_values):
        col, row = idx % 3, idx // 3
        xx, yy = lx + col * 265, ly + row * 18
        parts.append(f'<line x1="{xx}" y1="{yy-4}" x2="{xx+24}" y2="{yy-4}" stroke="{COLORS[name]}" stroke-width="3"/>')
        parts.append(f'<text x="{xx+30}" y="{yy}" font-family="sans-serif" font-size="12">{LABELS[name]}</text>')
    parts.append('<text x="%d" y="%d" font-family="sans-serif" font-size="11" fill="#475569">Cada ponto é a média temporal exata do intervalo de 5 s; traces de eventos permanecem para auditoria detalhada.</text>' % (left, height - 3))
    parts.append('</svg>')
    out_path.write_text("\n".join(parts) + "\n")


def main():
    data = json.loads(DATA.read_text())
    data["analysis_flags"] = {
        "exploratory": True,
        "admissibility": "all six seed-41 variants passed the recorded pre-run screens; no extra cells entered after selection failed",
        "technical_validity": "all six methodological runs valid; B instrumentation validation passed",
        "applications": "P1 application gates pass in all six runs",
        "stability_proxy": "P1/repository queue stability proxy passes in all six runs",
        "synchronization_samples": "all expected node clock samples are <= 1 us; continuous compliance not verified",
        "service_margin": "R, RP, and RPM fail the predeclared strict positive wire-service margin for F13",
        "official_c4_frozen": False,
    }
    data["execution_accounting"] = {
        "methodological_budget_max": 16,
        "methodological_runs_completed": 6,
        "conditional_runs_not_started": 10,
        "conditional_runs_reason": "No R/RP/RPM candidate passed the predeclared seed-41 selection rule because service did not strictly exceed F13 wire demand in all backlogged 5 s intervals.",
        "technical_replacements_completed": 2,
        "technical_attempts_and_smokes_logged": len(data.get("technical_attempts", [])),
        "superseded_BM_wrong_gate_run_excluded": True,
        "active_runs": 0,
    }
    data["F13_measured_service"] = {}
    for variant, run in data["runs"].items():
        service_rows = run["Z3_F13_service_by_5s"]
        q = run["Z3_F13_queue"]
        data["F13_measured_service"][variant] = {
            "queue": q["queue"], "capacity_bits": q["capacity_bits"],
            "Q_1minus_bits": q["Q_1minus_bits"], "Q_31minus_bits": q["Q_31minus_bits"],
            "measurement_peak_bits": q["measurement_peak_bits"],
            "mean_occupancy_bits_5s": q["mean_occupancy_bits_5s"],
            "intervals": service_rows,
            "all_six_bins_queue_balance_residual_bits_zero": all(x["queue_balance_residual_bits"] == 0 for x in service_rows),
            "strict_positive_service_margin_all_backlogged_bins": (
                all(x["service_exceeds_offer"] and x["queue_delta_bits"] <= 0 for x in service_rows if x["backlog_observed"])
                if any(x["backlog_observed"] for x in service_rows) else None
            ),
            "backlogged_bin_count": sum(bool(x["backlog_observed"]) for x in service_rows),
            "cbs_credit_samples_available": bool(run["Z3_F13_queue_packet_events"]["cbs_credit_samples_raw_units"]),
        }
    DATA.write_text(json.dumps(data, indent=2) + "\n")

    plotdir = RESULTS / "figures"
    plotdir.mkdir(exist_ok=True)
    plot_series = None
    svg_plot(data, plot_series, FOCUS_QUEUES[0], "HPC / TC4: ocupação durante a medição", plotdir / "hpc_tc4_occupancy.svg")
    svg_plot(data, plot_series, FOCUS_QUEUES[4], "Z3 eth7 / TC4: fila de F13", plotdir / "z3_tc4_occupancy.svg")

    qmaps = {}
    for variant, run in data["runs"].items():
        qmaps[variant] = {x.get("queue"): x for x in run["all_queue_stability_metrics"]}
    variants = list(data["runs"])
    lines = [
        "# Piloto isolado C4 com relógios reais: margem de serviço",
        "",
        "**Conclusão:** nenhum candidato foi selecionado neste piloto. As seis execuções metodológicas da seed 41 passaram os gates de aplicação, a proxy de estabilidade e os controles técnicos; porém R, RP e RPM não demonstraram margem positiva de serviço para F13 em Z3 eth7/TC4. O serviço medido ficou exatamente igual à oferta (27,60 Mb/s) em cada janela de 5 s, inclusive após o aumento local de idleSlope em 2%. A regra de seleção preregistrada, portanto, encerrou as execuções condicionais sem retunagem.",
        "",
        "Este é um resultado exploratório, não uma validação oficial de C4. A reprovação de seleção por margem de serviço é distinta da proxy de estabilidade do P1, que passou. A campanha final C4 não foi iniciada.",
        "",
        "## Escopo e rastreabilidade",
        "",
        "- Protocolo congelado antes das execuções: [protocol.md](../protocol.md); adendos preservados em ordem, com o fechamento corrigido em [protocol_addendum_007.md](../protocol_addendum_007.md).",
        "- Especificação: P1-v4; perfil C3 oficial congelado: `reduction_11`. INET 4.7.0 (`dfe270b21f`), OMNeT++ 6.4.0. Commit-base registrado: `003e44d6cf9387e3332ed6cbfe5812958780e7fb`; working tree já continha alterações locais antes do piloto, listadas no manifesto congelado. O manifesto e os hashes completos estão em [protocol_manifest.json](protocol_manifest.json) e os suplementos em `protocol_manifest_addendum_*.json`.",
        "- Comandos efetivos gravados linha a linha em [runs.jsonl](runs.jsonl); execução unitária em `run_pilot.py --continue-initial`; reprocessamento: `nice -n 12 python3 simulations/pilot/c4_real_clock_service_margin/analyze_pilot.py`; geração deste relatório/figuras: `python3 simulations/pilot/c4_real_clock_service_margin/render_report.py`.",
        "- Todas as seis execuções usaram L2/A1, seed 41, warm-up de 1 s, medição `[1,31)` s e drenagem até 31,05 s. Calendário F21/F22: 60 eventos, assinatura `cb74a68801e037dce0480422e4371150c2c95765974b0ef3857f1633b54a600d`, idêntica entre tratamentos.",
        "- `pilot_results.json` preserva métricas por fluxo/receptor, populações, latências, gates e a série de 1 ms da fila F13; traces comprimidos preservam eventos ordenados para auditoria. As figuras abaixo mostram as médias temporais exatas dos seis intervalos de 5 s usados também pelo critério de estabilidade.",
        "- O primeiro registro `BM_recovery_L2_A1_seed41` foi preservado, mas excluído das comparações: sua GCL efetiva era a de R, embora BM exigisse a GCL local de B. As tabelas e contrastes usam `BM_recovery_L2_A1_seed41_technical_replacement_001`, validado com GCL de B, perfil A005+2% em Z3/TC4 e o mesmo calendário. A reposição técnica não adiciona um novo candidato metodológico.",
        "- Corrigimos também a exportação herdada da fração de abertura: ela esperava fixamente o duty cycle A005 (77%/10%) e podia marcar R/RP/RPM como reprovados apesar da configuração efetiva. Os campos históricos permanecem em `legacy_tas_gate_schedule`; a visão atual confere durações/offsets efetivos no SCA contra os estados das gates. As seis variantes finais mostram GCL pass (ou não aplicável em C3_sync).",
        "",
        "## Variantes e resultados de seleção",
        "",
        "| Variante | Gates compartilhadas | Perfil CBS | Aplicações | Proxy de estabilidade | GCL | Selecionável? |",
        "|---|---|---|---:|---:|---:|---:|",
        "| B_local | GCL local auditada | A005 | Passa | Passa | Passa | Controle |",
        "| R_cadence | P=99,995 µs; janelas TC7=52 µs e TC0–6=47,995 µs; fase de referência | A005 | Passa | Passa | Passa | Não: sem margem positiva F13 |",
        "| RP_cadence_phase | Mesmo período/janelas de R; CSW eth1–3 TC7 deslocado +1 µs | A005 | Passa | Passa | Passa | Não: sem margem positiva F13 |",
        "| BM_recovery | GCL de B_local | A005, Z3 eth7/TC4 +2% relativo | Passa | Passa | Passa | Controle de recuperação; não selecionável |",
        "| RPM_combined | Mesmo GCL de RP | A005, Z3 eth7/TC4 +2% relativo | Passa | Passa | Passa | Não: sem margem positiva F13 |",
        "| C3_sync_control | Sem TAS periódico | C3 oficial da célula | Passa | Passa | Não aplicável | Controle |",
        "",
        "O aumento local foi `27,600 → 28,152 Mb/s`; não houve alteração em outra reserva. A estimativa anterior ao teste era +0,552 Mb/s sobre a demanda catalogada de F13. Essa estimativa não se converteu em serviço adicional observado. No BM corrigido, a única diferença funcional frente a B é esse idleSlope; portanto BM−B não demonstra ganho de serviço, embora a reserva configurada seja maior.",
        "",
        "## F13: oferta, serviço e balanço",
        "",
        "Em todos os seis bins `[1,6)`, `[6,11)`, …, `[26,31)` s, a fila Z3.ZSW.eth[7]/TC4 teve 62.500 inserções e 62.500 retiradas. Cada quadro corresponde a 2.048 bits na fila e 2.208 bits no enlace (276 B, overhead incluído). Portanto, por bin, demanda e serviço foram 128.000.000 bits de fila (25,60 Mb/s) e 138.000.000 bits de enlace (27,60 Mb/s). Não houve drops/removals; `Q(1−)=Q(31−)=0`, pico 2.048 bits e resíduo de conservação zero. A fila apresenta eventos breves de um quadro, não o backlog histórico de 53 quadros usado na estimativa prévia de recuperação.",
        "",
        "| Variante | IdleSlope Z3 eth7/TC4 | Média da fila por bin de 5 s (bits) | Pico (bits) | Serviço wire / oferta (Mb/s) | Margem estrita? |",
        "|---|---:|---|---:|---:|---:|",
    ]
    for v in variants:
        run = data["runs"][v]
        idle = run["effective_profile_bps"].get("Z3.ZSW.eth[7]/TC4")
        means = run["Z3_F13_queue"]["mean_occupancy_bits_5s"]
        service = run["Z3_F13_service_by_5s"][0]["F13_service_wire_bps"] / 1e6
        peak = run["Z3_F13_queue"]["measurement_peak_bits"]
        margin = data.get("F13_measured_service", {}).get(v, {}).get("strict_positive_service_margin_all_backlogged_bins")
        margin_text = "N/A (sem backlog)" if margin is None else ("Sim" if margin else "Não")
        lines.append(f"| {LABELS[v]} | {idle/1e6:.3f} | {', '.join(fnum(x,1) for x in means)} | {peak:,} | {service:.2f} / 27.60 | {margin_text} |")
    lines.extend([
        "",
        "Embora a fila feche o balanço e a proxy de estabilidade passe, a regra de seleção exige serviço wire estritamente maior que a oferta em cada janela com backlog. O serviço foi igual à oferta em todas as seis janelas; R, RP e RPM falham essa evidência de margem. Os eventos de crédito CBS não foram emitidos nos traces preservados (`cbs_credit_samples_raw_units` vazio), então os dados não demonstram por que o idleSlope maior não aumentou o serviço; não se atribui isso a uma causa interna específica do CBS.",
        "",
        "A estimativa de recuperação de 53 quadros (`108.544 queue bits`, `117.024 wire bits`) em 0,212 s a +0,552 Mb/s era uma hipótese de dimensionamento. As execuções não reproduziram esse backlog em Z3 eth7, de modo que não demonstraram recuperação dessa quantidade enquanto fontes permanecem ativas.",
        "",
        "## Cadência, fase e filas prioritárias",
        "",
        "![Ocupação de HPC/TC4](figures/hpc_tc4_occupancy.svg)",
        "",
        "![Ocupação de Z3 eth7/TC4](figures/z3_tc4_occupancy.svg)",
        "",
        "A inclinação linear ajustada sobre as seis médias de 5 s de HPC/TC4 foi aproximadamente +5,0 bits/s em B, −3,7 bits/s em R/RP/BM/RPM e ~0 em C3. Assim, a correspondência anterior de crescimento contínuo em torno de 3,3 kbit/s não se reproduziu: as novas variantes têm um nível médio próximo de 2,9–3,3 kbits, sem sequência crescente nas três últimas janelas suficiente para acionar a proxy. A proxy usa médias dos seis bins de 5 s e reprova somente se as três últimas forem estritamente crescentes e a diferença entre a última e a primeira superar 5% da capacidade; todos os bins também reportam ocupação máxima, e a fração ≥90% da capacidade é zero nas filas focais. A cadência reduz a latência dos freios contra B, mas aumenta o nível médio de HPC/TC4; não demonstrou crescimento persistente pela regra atual.",
        "",
        "| Fila TC4 | B média 5 s (bits) | R média 5 s (bits) | R pico (bits) | Capacidade (bits) | Proxy R |",
        "|---|---:|---:|---:|---:|---:|",
    ])
    for qname in FOCUS_QUEUES:
        qB, qR = qmaps["B_local"][qname], qmaps["R_cadence"][qname]
        short = qname.replace("ZonalIVN.", "")
        lines.append(f"| `{short}` | {', '.join(fnum(x,0) for x in qB['mean_occupancy_bits_5s'])} | {', '.join(fnum(x,0) for x in qR['mean_occupancy_bits_5s'])} | {qR['max_occupancy_bits']:,} | {qR['capacity_bits']:,} | {'Passa' if not qR['sustained_growth'] else 'Falha'} |")
    lines.extend([
        "",
        "Para as saídas compartilhadas TAS, as reservas CBS permanecem abaixo do teto agregado de 75% da taxa física. A tela de serviço preregistrada, usando 47,995 µs fora de TC7 e uma guard band de 12,336 µs, mantém margem estimada de 10% sobre o idleSlope no egress vinculante CSW eth3; isso é apenas triagem analítica, não garantia de serviço. A mudança de fase RP não alterou materialmente a ocupação média face a R. Sem amostras de crédito, não é possível distinguir com precisão espera por crédito, bloqueio por gate/guard band ou encaixe de quadros como limitante residual.",
        "",
        "## Aplicações e sincronização amostral",
        "",
        "Os três freios tiveram 300.000/300.000 pacotes recebidos por variante, zero perdas e zero misses. Para R, máximos F08/F09/F10 foram 78,978/79,539/78,595 µs, com margens de 21,022/20,461/21,405 µs até o deadline de 100 µs. RP produziu 79,219/79,466/79,038 µs; a fase prescrita preservou os gates, mas não ampliou de forma relevante a margem. B ficou próximo do limite (máximo até 97,814 µs; margem mínima ~2,186 µs). C3_sync teve máximos de 31,052/31,020/31,400 µs. O candidato C4 não supera o controle C3 em latência dos freios.",
        "",
        "Offsets foram calculados em ticks nativos antes da serialização. Em todos os seis tratamentos, os cinco nós esperados foram observados e nenhum sample passou de 1 µs; os máximos por nó estão no JSON. Isso é aprovação nas amostras observadas. Conformidade contínua entre amostras não foi verificada.",
        "",
        "## Contrastes pareados",
        "",
        "| Contraste | Δ máximo F08/F09/F10 (µs) | Δ máximo F13 (µs) | Δ média HPC/TC4 (bits) | Interpretação |",
        "|---|---:|---:|---:|---|",
    ])
    def flow_max(run, flow):
        rec = next(iter(run["flow_metrics_by_receiver"][flow]["receivers"].values()))
        return rec["latency"]["max_s"] * 1e6
    contrast_specs = [
        ("R_cadence", "B_local", "R − B", "Efeito de cadência/janelas"),
        ("RP_cadence_phase", "R_cadence", "RP − R", "Efeito da coordenação de fase"),
        ("BM_recovery", "B_local", "BM − B", "Efeito da reserva local +2%"),
        ("RPM_combined", "RP_cadence_phase", "RPM − RP", "Reserva +2% sob a fase RP"),
        ("RPM_combined", "BM_recovery", "RPM − BM", "Fase RP com a mesma reserva +2%"),
    ]
    for lhs, rhs, label, interpretation in contrast_specs:
        left, right = data["runs"][lhs], data["runs"][rhs]
        brake_delta = [flow_max(left, f) - flow_max(right, f) for f in ("F08", "F09", "F10")]
        f13_delta = flow_max(left, "F13") - flow_max(right, "F13")
        hpc_left = qmaps[lhs][FOCUS_QUEUES[0]]["mean_occupancy_bits_5s"]
        hpc_right = qmaps[rhs][FOCUS_QUEUES[0]]["mean_occupancy_bits_5s"]
        hpc_delta = sum(a-b for a,b in zip(hpc_left, hpc_right)) / 6
        lines.append(f"| {label} | {', '.join(f'{x:+.3f}' for x in brake_delta)} | {f13_delta:+.3f} | {hpc_delta:+.1f} | {interpretation} |")
    lines.extend([
        "| candidato − C3_sync | — | — | — | Nenhum candidato foi escolhido; C4 combina TAS e perfil CBS diferente e não seria efeito exclusivo do TAS. |",
        "",
        "Os contrastes mostram que R melhora os máximos dos freios em relação a B, mas não em relação a C3_sync; RP acrescenta pouco frente a R. BM/RPM aumentam a reserva Z3/TC4, mas o serviço medido não muda. Todos os fluxos e receptores, inclusive câmeras por pacote e conclusão por imagem, estão no JSON. Cada execução passou gates de aplicação e registrou zero drops.",
        "",
        "## Execuções, retenção e próximo estudo",
        "",
        f"Foram concluídas 6/16 execuções metodológicas; as 10 verificações condicionais (seeds 43/47 e cargas L0/A0, L1/A1) não foram iniciadas porque nenhum candidato passou pela regra preregistrada. O ledger técnico preserva preflights sem simulação, o smoke test de 1 ps, duas falhas técnicas B, uma tentativa B concluída mas inelegível por ausência de eventos dequeue, a correção instrumental de B e a reposição BM por GCL errada. A reposição BM passou configuração, calendário e instrumentação; não há execução ativa. Nenhum resultado histórico foi apagado. `results/` ocupa {subprocess.run(['du','-sh',str(RESULTS)],check=True,capture_output=True,text=True).stdout.split()[0]}; o volume tem {subprocess.run(['df','-h',str(ROOT)],check=True,capture_output=True,text=True).stdout.splitlines()[-1].split()[3]} livres, acima do piso de 40 GiB.",
        "",
        "O resultado permite concluir que R/RP não causaram uma tendência crescente detectável em HPC pela proxy aplicada nesta célula e seed; contudo, elevam seu nível médio e não provam folga generalizável. A alteração local +2% não foi necessária para passar gates nesta execução, mas tampouco demonstrou margem extra de recuperação. F13 permaneceu sem margem estrita medida. Portanto, não há configuração empiricamente selecionável segundo o protocolo e não se recomenda congelar C4. Um estudo futuro deveria primeiro instrumentar corretamente a evolução/créditos CBS e acumular episódios de backlog ativo recuperáveis; só então revisar período/fase, sem expandir este orçamento retrospectivamente. Se um desenho futuro mudar período ou fase, a avaliação final precisará do controle C3_sync pareado e incluir as mesmas reservas CBS declaradas.",
        "",
        "## Arquivos",
        "",
        "- [JSON completo](pilot_results.json)",
        "- [Plano e configurações congeladas](plan.json)",
        "- [Manifesto de hashes](protocol_manifest.json)",
        "- [Checkpoint](checkpoint.json)",
        "- [Ledger](runs.jsonl)",
        "- [Trace de eventos comprimido por execução](runs/)",
        "- [Séries de ocupação compactas](runs/)",
    ])
    (RESULTS / "analysis.md").write_text("\n".join(lines) + "\n")

    status = json.loads((RESULTS / "checkpoint.json").read_text())
    prior_error = status.get("last_error")
    if prior_error:
        status["last_technical_note"] = prior_error
    status.update({
        "analysis_status": "completed_no_selectable_candidate_after_seed41",
        "selected_candidate": None,
        "seed41_methodological_runs": 6,
        "conditional_verification_runs_not_started": 10,
        "conditional_skip_reason": "R, RP and RPM all had 27.60 Mb/s measured F13 wire service equal to 27.60 Mb/s offer in every 5 s interval; preregistered positive-margin gate failed.",
        "valid_treatment_slots": ["B_local_L2_A1_seed41", "R_cadence_L2_A1_seed41", "RP_cadence_phase_L2_A1_seed41", "BM_recovery_L2_A1_seed41_technical_replacement_001", "RPM_combined_L2_A1_seed41", "C3_sync_control_L2_A1_seed41"],
        "superseded_execution_ids": ["BM_recovery_L2_A1_seed41"],
        "technical_replacements_used": 2,
        "technical_attempts_count": len(json.loads(DATA.read_text()).get("technical_attempts", [])),
        "last_error": None,
        "active": None,
        "official_c4_frozen": False,
    })
    (RESULTS / "checkpoint.json").write_text(json.dumps(status, indent=2) + "\n")

    (ROOT / "protocol_addendum_007.md").write_text("""# Protocol addendum 007: corrected BM completion and final seed-41 audit\n\nThis addendum records the result after technical completion of the preregistered BM treatment. It does not change P1, the frozen pilot protocol, workload, CBS sizing, gates, criteria, or selection order. The original `BM_recovery_L2_A1_seed41` run remains preserved as historical evidence and is excluded because its effective GCL matched R cadence rather than the preregistered B-local schedule. The replacement `BM_recovery_L2_A1_seed41_technical_replacement_001` used the correct B-local GCL, the fixed A005+2% Z3.ZSW.eth[7]/TC4 profile, and the same F21/F22 calendar signature (`cb74a68801e037dce0480422e4371150c2c95765974b0ef3857f1633b54a600d`). Its effective profile, GCL, calendar, packet instrumentation, and application validator passed. The 2% reserve increase did not change F13 service: each of six 5-second intervals showed 27.60 Mb/s wire service equal to 27.60 Mb/s offer with exact queue balance and no drops.\n\nThe final JSON and Markdown were regenerated from the corrected replacement and compact preserved traces. R, RP, and RPM still fail the preregistered strict positive service-margin rule, so no candidate was selected and the ten conditional runs were not started. Two technical treatment corrections are documented: B dequeue-signal instrumentation and the BM gate mapping. Runner preflight failures and the short instrumentation smoke are recorded separately in `results/technical_attempts.jsonl`; none changes the methodological budget. The inherited gate export is retained as historical data while current gate checks use effective SCA durations and observed gate-state traces.\n\nNo official configuration or historical pilot result was deleted. The current source/analysis/artifact hashes and storage snapshot are in `results/protocol_manifest_addendum_007.json` and `results/analysis_manifest.json`. See [analysis.md](results/analysis.md), [pilot_results.json](results/pilot_results.json), and [checkpoint.json](results/checkpoint.json).\n""")
    (ROOT / "README.md").write_text("""# C4 real-clock service-margin pilot\n\nThis isolated exploratory pilot evaluates a deterministic real-clock TAS cadence, downstream gate phase, and one fixed 2% F13 CBS idleSlope increase. It preserves the official P1 and C0–C3 profiles and does not start the final C4 campaign.\n\nThe preregistered design is in [protocol.md](protocol.md); results and the selection decision are in [results/analysis.md](results/analysis.md) and [results/pilot_results.json](results/pilot_results.json). Six treatment slots completed for L2/A1 seed 41. No candidate met the preregistered F13 positive-service-margin rule, so conditional seeds and load cells were not run. The corrected BM run and final outcome are recorded in [protocol_addendum_007.md](protocol_addendum_007.md); the original mismatched BM run remains historical.\n\nRun `python3 simulations/pilot/c4_real_clock_service_margin/pilot_status.py` for status. Retained traces are compressed under `results/runs/`; prior pilot and campaign data were not removed.\n""")

    addendum = {
        "purpose": "Post-execution analysis/export provenance; does not revise the preregistered protocol or selection rule.",
        "outcome": "No candidate selected after six seed-41 runs; conditional runs not started.",
        "analysis_script_sha256": sha(ROOT / "analyze_pilot.py"),
        "render_script_sha256": sha(ROOT / "render_report.py"),
        "analysis_artifacts": {},
    }
    for path in [DATA, RESULTS / "analysis.md", RESULTS / "checkpoint.json", ROOT / "README.md", ROOT / "pilot_status.py", ROOT / "protocol_addendum_007.md", plotdir / "hpc_tc4_occupancy.svg", plotdir / "z3_tc4_occupancy.svg"]:
        addendum["analysis_artifacts"][str(path.relative_to(ROOT))] = sha(path)
    addendum["technical_replacements_completed"] = 2
    addendum["technical_attempts_path"] = "results/technical_attempts.jsonl"
    addendum["technical_attempts_sha256"] = sha(RESULTS / "technical_attempts.jsonl")
    addendum["superseded_BM_execution"] = "BM_recovery_L2_A1_seed41"
    addendum["corrected_BM_execution"] = "BM_recovery_L2_A1_seed41_technical_replacement_001"
    addendum["updated_runner_sha256"] = sha(ROOT / "run_pilot.py")
    addendum["status_dashboard_sha256"] = sha(ROOT / "pilot_status.py")
    addendum["analyzer_sha256"] = sha(ROOT / "analyze_pilot.py")
    addendum["corrected_BM_artifacts"] = {}
    bm_dir = RESULTS / "runs" / "BM_recovery_L2_A1_seed41_technical_replacement_001"
    for path in [bm_dir / "pilot-result.json", bm_dir / "Pilot_C4compensated_L2_A1-#0.sca.gz",
                 bm_dir / "Pilot_C4compensated_L2_A1.log.gz",
                 bm_dir / "Pilot_C4compensated_L2_A1-#0.vec.sha256"]:
        if path.is_file():
            addendum["corrected_BM_artifacts"][str(path.relative_to(ROOT))] = {"sha256": sha(path), "bytes": path.stat().st_size}
    bm_trace = bm_dir / "Pilot_C4compensated_L2_A1-0" / "packet_events.csv.gz"
    if bm_trace.is_file():
        addendum["corrected_BM_artifacts"][str(bm_trace.relative_to(ROOT))] = {"sha256": sha(bm_trace), "bytes": bm_trace.stat().st_size}
    (RESULTS / "protocol_manifest_addendum_007.json").write_text(json.dumps(addendum, indent=2) + "\n")

    manifest = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "source": "results/pilot_results.json plus compact retained run traces",
        "files": {},
        "storage": {},
    }
    for path in [DATA, RESULTS / "analysis.md", RESULTS / "checkpoint.json", ROOT / "README.md", ROOT / "pilot_status.py", ROOT / "protocol_addendum_007.md", RESULTS / "protocol_manifest_addendum_007.json", RESULTS / "technical_attempts.jsonl", ROOT / "render_report.py", plotdir / "hpc_tc4_occupancy.svg", plotdir / "z3_tc4_occupancy.svg"]:
        manifest["files"][str(path.relative_to(ROOT))] = {"sha256": sha(path), "bytes": path.stat().st_size}
    du = subprocess.run(["du", "-sb", str(RESULTS)], check=True, capture_output=True, text=True)
    manifest["storage"]["results_bytes"] = int(du.stdout.split()[0])
    df = subprocess.run(["df", "-B1", str(ROOT)], check=True, capture_output=True, text=True).stdout.splitlines()[-1].split()
    manifest["storage"]["filesystem_available_bytes"] = int(df[3])
    (RESULTS / "analysis_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Wrote {RESULTS/'analysis.md'} and figures; selected={data['selected_candidate']}; runs={len(data['runs'])}/16")


if __name__ == "__main__":
    main()
