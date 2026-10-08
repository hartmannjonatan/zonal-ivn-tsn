#!/usr/bin/env python3
"""Rebuild the compact C3 calibration diagnosis without running simulations."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "simulations/results"
C3_DIR = RESULTS / "C3/p1-validation-64KiB"
C3_CAL = C3_DIR / "C3_calibration.json"
C2_ACCEPT = RESULTS / "C2/p1-validation-64KiB-final/C2_acceptance.json"
C0_ACCEPT = RESULTS / "C0/p1-validation-64KiB/C0_acceptance.json"
C1_ACCEPT = RESULTS / "C1/p1-validation-64KiB/C1_acceptance.json"
OUT_JSON = C3_DIR / "C0_C1_C2_C3_calibration_comparison.json"
OUT_MD = C3_DIR / "C0_C1_C2_C3_calibration_analysis.md"


def read(path):
    return json.loads(path.read_text())


def selected_flow_metrics(candidate, flow_ids):
    data = {}
    for flow_id in flow_ids:
        flow = candidate.get("qos", {}).get(flow_id, {})
        receivers = {}
        for receiver, m in flow.get("receivers", {}).items():
            receivers[receiver] = {
                "offered_packets": m.get("offered_packets"),
                "received_packets": m.get("received_packets"),
                "deadline_misses_received": m.get("deadline_misses_received"),
                "deadline_miss_ratio_including_loss": m.get("deadline_miss_ratio_including_loss"),
                "packet_loss_ratio": m.get("packet_loss_ratio"),
                "goodput_payload_ratio": m.get("goodput_payload_ratio"),
                "useful_throughput_mbps": m.get("useful_throughput_mbps"),
                "latency": m.get("latency"),
                "image_completion": m.get("image_completion"),
                "viable": m.get("viable"),
            }
        data[flow_id] = {"criticality": flow.get("criticality"), "receivers": receivers}
    return data


def queue_diagnosis(candidate):
    drops = {q["queue"]: q for q in candidate.get("measurement_drops_by_queue", [])}
    stability = {q["queue"]: q for q in candidate.get("queue_stability", [])}
    rows = []
    for name, s in stability.items():
        if ".macLayer.queue.queue[" not in name:
            continue
        q = drops.get(name, {})
        means = s.get("mean_occupancy_bits_5s") or []
        capacity = s.get("capacity_bits")
        rows.append({
            "queue": name,
            "tc": s.get("tc"),
            "capacity_bits": capacity,
            "maximum_occupancy_bits": s.get("max_occupancy_bits"),
            "mean_of_5s_mean_occupancy_bits": sum(means) / len(means) if means else None,
            "five_second_mean_occupancy_samples_bits": means,
            "maximum_fraction_of_capacity": (s.get("max_occupancy_bits") / capacity) if capacity else None,
            "overflow_drops_measurement_window": q.get("packets", 0),
            "sustained_growth": s.get("sustained_growth"),
        })
    rows.sort(key=lambda x: x["queue"])
    return rows


def main():
    calibration = read(C3_CAL)
    candidate = calibration["last_candidate"]
    c2 = read(C2_ACCEPT)["Validate_C2_L2_A1"]
    c0 = read(C0_ACCEPT)["Validate_C0_L2_A1"]
    c1 = read(C1_ACCEPT)["Validate_C1_L2_A1"]
    flows = ["F01", "F02", "F03", "F06", "F07", "F13", "F21", "F22"]
    c3_flows = selected_flow_metrics(candidate, flows)
    c2_flows = selected_flow_metrics(c2, flows)
    c0_flows = selected_flow_metrics(c0, flows)
    c1_flows = selected_flow_metrics(c1, flows)

    trials = []
    for h in calibration.get("history", []):
        if "report_path" not in h:
            continue
        p = (ROOT / "simulations" / h["report_path"]).resolve()
        if not p.exists():
            continue
        report = read(p)
        trials.append({
            "trial": h.get("trial"),
            "target": h.get("target"),
            "stage": h.get("stage", "coarse"),
            "target_idle_slope_bps": report.get("cbs_calibrated", {}).get("idle_slope_by_module_bps", {}),
            "viable": report.get("viable"),
            "recorded_drops": report.get("recorded_drops"),
            "pending_packets_at_simulation_end": report.get("pending_packet_count_at_simulation_end"),
            "failing_flows": h.get("failed_flows", []),
            "report_path": h["report_path"],
        })

    queue_rows = queue_diagnosis(candidate)
    measured_drop_rows = candidate.get("measurement_drops_by_queue", [])
    drop_total = sum(q.get("packets", 0) for q in measured_drop_rows)
    endpoint_rates = candidate["cbs_calibrated"]
    endpoint = {
        "trial": candidate.get("calibration_trial"),
        "load": "L2",
        "aggregation": "A1",
        "seed": 41,
        "offered_packets": candidate.get("offered_packets"),
        "recorded_drops_full_run": candidate.get("recorded_drops"),
        "queue_overflow_drops_measurement_window": drop_total,
        "pending_packets_at_simulation_end": candidate.get("pending_packet_count_at_simulation_end"),
        "camera_source_queue_drops": candidate.get("camera_source_queue_drops"),
        "viable": candidate.get("viable"),
        "failing_flows": calibration.get("last_failing_flows", []),
        "nonstable_queues": candidate.get("nonstable_queues", []),
        "egress_interfaces_checked": candidate.get("egress_interfaces_checked"),
        "class_queues_checked": candidate.get("class_queues_checked"),
        "temporary_raw_files_removed": candidate.get("temporary_raw_files_removed"),
        "space_before_run_free_bytes": candidate.get("space_before_run_free_bytes"),
        "space_after_raw_cleanup_free_bytes": candidate.get("space_after_raw_cleanup_free_bytes"),
        "total_reservation_by_egress_bps": endpoint_rates.get("total_reservation_by_egress_bps", {}),
        "reservation_cap_fraction": endpoint_rates.get("cap_fraction"),
        "within_cap": endpoint_rates.get("within_cap"),
        "frozen_ratios": endpoint_rates.get("frozen_ratios", {}),
        "flow_metrics": c3_flows,
        "queue_metrics": queue_rows,
        "queueing_time_active": [q for q in candidate.get("queueing_time", []) if q.get("samples", 0)],
        "link_utilization_top10_max_percent": sorted(
            candidate.get("link_utilization", []), key=lambda x: x.get("max_percent") or 0, reverse=True
        )[:10],
    }
    def baseline_summary(report, flow_metrics):
        return {
            "load": "L2", "aggregation": "A1", "seed": 41,
            "offered_packets": report.get("offered_packets"),
            "recorded_drops_full_run": report.get("recorded_drops"),
            "pending_packets_at_simulation_end": report.get("pending_packet_count_at_simulation_end"),
            "viable": report.get("viable"),
            "nonstable_queue_count": len(report.get("nonstable_queues", [])),
            "flow_metrics": flow_metrics,
        }

    baseline_c0 = baseline_summary(c0, c0_flows)
    baseline_c1 = baseline_summary(c1, c1_flows)
    c2_endpoint = {
        "load": "L2", "aggregation": "A1", "seed": 41,
        "offered_packets": c2.get("offered_packets"),
        "recorded_drops_full_run": c2.get("recorded_drops"),
        "pending_packets_at_simulation_end": c2.get("pending_packet_count_at_simulation_end"),
        "viable": c2.get("viable"),
        "flow_metrics": c2_flows,
    }
    c2_signature = c2.get("transient_event_signature")
    c3_signature = candidate.get("transient_event_signature")
    same_transients = (c2_signature == c3_signature) if c2_signature and c3_signature else None
    analysis = {
        "status": "C3_CALIBRATION_INFEASIBLE_NOT_VALIDATED",
        "source_p1": "Updated P1, §§4.4–5.4; calibration L2/A1, seed 41, 1 s warm-up, 30 s measurement, 50 ms drain; maximum 75% total reservation per egress.",
        "strict_p1_decision": "No frozen C3 profile and no final C3 matrix: every measured candidate failed viability, including the maximum admissible reservations on the remaining egresses that served failing flows.",
        "calibration_trials_completed": len(trials),
        "calibration_seed": 41,
        "calibration_cells": [{"load": "L2", "aggregation": "A1"}],
        "c3_final_matrix_executed": False,
        "c3_l3_excluded_by_reservation_cap": True,
        "c2_baseline": c2_endpoint,
        "c0_baseline": baseline_c0,
        "c1_baseline": baseline_c1,
        "c3_max_cap_diagnostic_candidate": endpoint,
        "transient_event_signatures_match_c2": same_transients,
        "transient_signature_comparison_status": "unavailable: C2 acceptance report does not contain a transient event signature",
        "comparability_limit": "C3-vs-C2 figures are an exploratory single-seed calibration diagnostic only; exact F21/F22 event matching against C2 cannot be verified, and this is not a frozen-treatment matrix or confirmatory H3 test.",
        "calibration_history": trials,
        "queue_saturation_metric_limit": "The collected queue vectors provide five-second mean samples and observed maxima, not the fraction of time near capacity; no near-capacity time percentage is inferred.",
        "pending_semantics": "Pending packets at end of drain are reported separately from confirmed queue overflow drops and are not automatically counted as physical loss.",
    }
    OUT_JSON.write_text(json.dumps(analysis, indent=2) + "\n")

    lines = [
        "# C0/C1/C2/C3 — diagnóstico de calibração C3",
        "",
        "## Decisão conforme o P1",
        "",
        "C3 foi implementado como tratamento candidato e a calibração L2/A1 (seed 41) foi executada, mas **não foi possível congelar um perfil viável**. Todos os candidatos medidos falharam no gate de viabilidade; os últimos testes levaram CSW→HPC, Z1→CSW e Z2→CSW ao teto de 75% da capacidade da porta, sem eliminar os misses high-hard de F01, F06 e F07. Seguindo o P1, o executor parou antes da matriz C3 L0–L2. Portanto C3 ainda não está validado e não há comparação final C3 contra C0/C1/C2.",
        "",
        f"Foram concluídos **{len(trials)} ensaios de calibração** em L2/A1. Os resultados compactos dos ensaios estão preservados em `simulations/results/C3/calibration/`; os arquivos OMNeT++ de grande porte foram removidos depois da extração. O disco tinha {endpoint['space_before_run_free_bytes'] / 1024**3:.1f} GiB livres antes do último ensaio e {endpoint['space_after_raw_cleanup_free_bytes'] / 1024**3:.1f} GiB após a limpeza.",
        "",
        "## Comparação com os cenários anteriores em L2/A1",
        "",
        "| Métrica em L2/A1, seed 41 | C0 SP | C1 pre-shaping | C2 CBS nominal | C3 candidato admissível* |",
        "|---|---:|---:|---:|---:|",
        f"| Pacotes oferecidos | {baseline_c0['offered_packets']:,} | {baseline_c1['offered_packets']:,} | {c2_endpoint['offered_packets']:,} | {endpoint['offered_packets']:,} |",
        f"| Drops registrados na execução | {baseline_c0['recorded_drops_full_run']:,} | {baseline_c1['recorded_drops_full_run']:,} | {c2_endpoint['recorded_drops_full_run']:,} | {endpoint['recorded_drops_full_run']:,} |",
        f"| Pendentes ao final da drenagem | não registrado | não registrado | {c2_endpoint['pending_packets_at_simulation_end']} | {endpoint['pending_packets_at_simulation_end']} |",
        f"| Gate de viabilidade | {baseline_c0['viable']} | {baseline_c1['viable']} | {c2_endpoint['viable']} | {endpoint['viable']} |",
        f"| Drops de overflow na janela | {sum(q.get('packets', 0) for q in c0.get('measurement_drops_by_queue', [])):,} | {sum(q.get('packets', 0) for q in c1.get('measurement_drops_by_queue', [])):,} | {sum(q.get('packets', 0) for q in c2.get('measurement_drops_by_queue', [])):,} | {drop_total:,} |",
        f"| Filas com crescimento sustentado | {len(c0.get('nonstable_queues', []))} | {len(c1.get('nonstable_queues', []))} | {len(c2.get('nonstable_queues', []))} | {len(endpoint['nonstable_queues'])} |",
        "",
        "*C3 é o candidato diagnóstico do último ensaio de calibração, não uma configuração congelada. C0/C1/C2/C3 oferecem o mesmo total de pacotes no L2/A1; as métricas completas por fluxo estão no JSON. C0 e C1 não registraram a contagem de pacotes pendentes ao término, por isso não inferimos zero. C3 inspecionou 42 interfaces de egress e 336 filas por classe: não houve overflow, drops na fila de origem das quatro câmeras ou pacotes pendentes ao fim da drenagem. A inviabilidade de C3 decorre dos deadlines high-hard restantes, não de perda física observada nesse candidato.",
        "",
        "A sequência exata de eventos de F21/F22 no candidato C3 foi registrada, mas os relatórios de C0/C1/C2 não contêm assinaturas correspondentes. Portanto, não é possível confirmar pareamento dos transientes; seed igual não basta para concluir que F21/F22 tiveram ocorrências idênticas. A comparação final de tratamentos não foi produzida.",
        "",
        "## Fluxos de prazo crítico",
        "",
        "| Fluxo | C0: misses | C1: misses | C2: misses | C3 candidato: misses | C3 p99 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for fid in ("F01", "F06", "F07"):
        cm = next(iter(c2_flows[fid]["receivers"].values()))
        m0 = next(iter(c0_flows[fid]["receivers"].values()))
        m1 = next(iter(c1_flows[fid]["receivers"].values()))
        nm = next(iter(c3_flows[fid]["receivers"].values()))
        np99 = (nm.get("latency") or {}).get("p99_s")
        lines.append(f"| {fid} | {m0.get('deadline_misses_received'):,} ({m0.get('deadline_miss_ratio_including_loss', 0):.2%}) | {m1.get('deadline_misses_received'):,} ({m1.get('deadline_miss_ratio_including_loss', 0):.2%}) | {cm.get('deadline_misses_received'):,} ({cm.get('deadline_miss_ratio_including_loss', 0):.2%}) | {nm.get('deadline_misses_received'):,} ({nm.get('deadline_miss_ratio_including_loss', 0):.2%}) | {np99 * 1e6:.2f} µs |")
    lines += [
        "",
        "No último candidato, F01 teve 32,50% de deadline misses e p99 de 653,72 µs; F06 teve 31,25% e p99 de 555,89 µs; F07 teve 31,25% e p99 de 551,94 µs. Os três têm prazo de 100 µs. Cada p99 usa as mesmas amostras de latência por pacote usadas para contar misses, portanto os resultados são consistentes. F02/F03 e F13 não falharam os respectivos gates nesse candidato; F21/F22 tiveram zero misses nele, mas sua comparação entre configurações não está confirmada como pareada.",
        "",
        "## Reservas máximas verificadas",
        "",
        "| Egress TC6 | `idleSlope` no ensaio final | Total CBS no egress | Limite P1 |",
        "|---|---:|---:|---:|",
    ]
    by_module = endpoint_rates["idle_slope_by_module_bps"]
    egress_ports = [
        ("CSW.eth[0]", "ZonalIVN.CSW.eth[0].macLayer.queue.transmissionSelectionAlgorithm[6]"),
        ("Z1.ZSW.eth[0]", "ZonalIVN.Z1.ZSW.eth[0].macLayer.queue.transmissionSelectionAlgorithm[6]"),
        ("Z2.ZSW.eth[0]", "ZonalIVN.Z2.ZSW.eth[0].macLayer.queue.transmissionSelectionAlgorithm[6]"),
    ]
    for port, mod in egress_ports:
        rate = by_module[mod]
        total = endpoint_rates["total_reservation_by_egress_bps"][port]
        lines.append(f"| {port} | {rate / 1e6:.2f} Mb/s | {total / 1e6:.2f} Mb/s | 750 Mb/s |")
    lines += [
        "",
        "A triagem adaptativa priorizou somente egressos nas rotas dos fluxos que continuavam reprovados. Os candidatos finais elevaram Z1 e Z2 a 750 Mb/s e CSW.eth[0] a 636,3 Mb/s; o restante do serviço permanente continuou reservado conforme o catálogo. Não foi excedido o teto nem alterado o workload, buffers ou drenagem.",
        "",
        "## Filas, perdas e limites das métricas",
        "",
        "As 336 filas têm amostras médias em janelas de 5 s, máximo observado e contador de overflow na janela de medição. No candidato final, todos os contadores de overflow foram zero; não houve filas classificadas como crescimento sustentado e as amostras pendentes no encerramento foram zero. As médias por janela e máximos estão no JSON. O vetor não registra fração temporal próxima à capacidade, portanto o relatório não inventa essa porcentagem.",
        "",
        "## Hipóteses e próximo passo",
        "",
        "A evidência desta única seed é compatível com redução de perdas e de misses para parte dos fluxos em relação ao CBS nominal, mas não testa H3 sob o protocolo final: o perfil falha os deadlines hard e não pode ser congelado. A conclusão atual é **C3 calibração inviável sob o teto de 75% na calibração definida**, não confirmação nem refutação estatística de H3. Conforme o P1, não se executa nem reporta uma matriz final C3 com este candidato.",
        "",
        "Para retomar após uma decisão metodológica documentada, rever o dimensionamento CBS/escopo do P1; não se deve simplesmente exceder 75%, alterar os fluxos ou declarar sucesso pelos resultados parciais. O relatório JSON adjacente conserva métricas por fluxo, fila e ensaio, assim como os limites de interpretação.",
        "",
    ]
    OUT_MD.write_text("\n".join(lines))
    print(f"Wrote {OUT_JSON.relative_to(ROOT)} and {OUT_MD.relative_to(ROOT)} ({len(trials)} trials)")


if __name__ == "__main__":
    main()
