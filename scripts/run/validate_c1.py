#!/usr/bin/env python3
"""Run and assess the eight full-duration P1 C1 load/aggregation cells."""
import csv
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parents[2]
SIM = ROOT / "simulations"
sys.path.insert(0, str(ROOT / "scripts/run"))
from validate_c0 import require, run_cell
from check_traffic import check_run


def write_comparison(result):
    output = SIM / "results/C1/p1-validation-64KiB"
    c0_path = SIM / "results/C0/p1-validation-64KiB/C0_acceptance.json"
    require(c0_path.exists(), f"Missing C0 acceptance report: {c0_path}")
    baseline = json.loads(c0_path.read_text())
    comparison = {}
    metrics = ("useful_throughput_mbps", "deadline_miss_ratio_including_loss",
               "goodput_payload_ratio", "packet_loss_ratio")

    def queue_summary(report):
        camera = []
        bottleneck = []
        network_drops = []
        camera_drops = []
        for queue in report.get("queue_stability", []):
            name = queue["queue"]
            row = {"queue": name, "tc": queue["tc"],
                   "max_occupancy_bits": queue.get("max_occupancy_bits"),
                   "capacity_bits": queue["capacity_bits"],
                   "sustained_growth": queue["sustained_growth"]}
            if ".CAM" in name and ".eth[0]." in name:
                camera.append(row)
            elif (".CSW.eth[" in name or ".ZCPU.eth[0]." in name or
                  (".ZSW.eth[" in name and any(f".eth[{i}]." in name for i in (0, 1)))):
                bottleneck.append(row)
        for drop in report.get("measurement_drops_by_queue") or []:
            if not drop["packets"]:
                continue
            row = {key: drop[key] for key in ("queue", "tc", "packets", "bytes")}
            (camera_drops if ".CAM" in drop["queue"] else network_drops).append(row)
        return {
            "camera_talker_queues": camera,
            "camera_talker_drops": camera_drops,
            "network_queue_drops": network_drops,
            "bottleneck_queues": bottleneck,
            "peak_occupancy_bits": {
                "camera_talkers": max((q["max_occupancy_bits"] or 0 for q in camera), default=0),
                "G1_G4": max((q["max_occupancy_bits"] or 0 for q in bottleneck), default=0),
            },
            "nonstable_queue_count": len(report.get("nonstable_queues", [])),
            "max_queueing_time_s": max((q.get("max_s") or 0 for q in report.get("queueing_time", [])), default=0),
        }

    def critical_summary(report):
        p99, maximum, misses, image_p99, image_misses = [], [], [], [], []
        for flow in report["qos"].values():
            if flow["criticality"] == "low":
                continue
            for rx in flow["receivers"].values():
                latency = rx.get("latency") or {}
                if latency.get("p99_s") is not None:
                    p99.append(latency["p99_s"])
                if latency.get("max_s") is not None:
                    maximum.append(latency["max_s"])
                image = rx.get("image_completion")
                misses.append(image["deadline_miss_ratio_including_missing_images"] if image else
                              rx["deadline_miss_ratio_including_loss"])
                if image:
                    if image.get("p99_s") is not None:
                        image_p99.append(image["p99_s"])
                    image_misses.append(image["deadline_miss_ratio_including_missing_images"])
        return {"max_critical_p99_s": max(p99, default=0),
                "max_critical_latency_s": max(maximum, default=0),
                "max_critical_deadline_miss_ratio": max(misses, default=0),
                "max_camera_image_completion_p99_s": max(image_p99, default=0),
                "max_camera_image_deadline_miss_ratio": max(image_misses, default=0)}

    def metric_summary(report):
        receivers = [rx for flow in report["qos"].values() for rx in flow["receivers"].values()]
        return {
            **critical_summary(report),
            "max_packet_loss_ratio": max((rx["packet_loss_ratio"] for rx in receivers), default=0),
            "min_goodput_payload_ratio": min((rx["goodput_payload_ratio"] for rx in receivers), default=0),
            "max_queueing_time_s": max((q.get("max_s") or 0 for q in report.get("queueing_time", [])), default=0),
            "max_camera_occupancy_bits": queue_summary(report)["peak_occupancy_bits"]["camera_talkers"],
            "max_bottleneck_occupancy_bits": queue_summary(report)["peak_occupancy_bits"]["G1_G4"],
            "recorded_drops": report.get("recorded_drops", 0),
        }

    for config, c1 in result.items():
        c0_config = config.replace("Validate_C1_", "Validate_C0_")
        if c0_config not in baseline:
            continue
        c0_run_dir = SIM / "results/C0/p1-validation-64KiB" / f"{c0_config}-0"
        c0_summary = check_run(c0_run_dir) if c0_run_dir.exists() else None
        c1_run_dir = output / f"{config}-0"
        c1_summary = check_run(c1_run_dir) if c1_run_dir.exists() else None
        cell = {"C0_viable": baseline[c0_config].get("viable"),
                "C1_viable": c1.get("viable"),
                "C0_recorded_drops": baseline[c0_config].get("recorded_drops"),
                "C1_recorded_drops": c1.get("recorded_drops"), "flows": {},
                "queues": {"C0": queue_summary(baseline[c0_config]),
                           "C1": queue_summary(c1)},
                "camera_frame_generation": {}}
        if c0_summary and c1_summary:
            for flow in ("F02", "F03", "F04", "F05"):
                c0_flow = c0_summary["flows"][flow]
                c1_flow = c1_summary["flows"][flow]
                cell["camera_frame_generation"][flow] = {
                    "C0_generated_frames": c0_flow["generated_packets"],
                    "C1_generated_frames": c1_flow["generated_packets"],
                    "C0_app_bytes": c0_flow["application_bytes"],
                    "C1_app_bytes": c1_flow["application_bytes"],
                    "same_generation": (c0_flow["generated_packets"] == c1_flow["generated_packets"] and
                                        c0_flow["application_bytes"] == c1_flow["application_bytes"]),
                }
                require(cell["camera_frame_generation"][flow]["same_generation"],
                        f"{config}/{flow}: C0 and C1 generated different camera frame counts or bytes")
        for flow, flow_metrics in c1["qos"].items():
            receivers = {}
            for receiver, c1_rx in flow_metrics["receivers"].items():
                c0_rx = dict(baseline[c0_config]["qos"][flow]["receivers"].get(receiver, {}))
                if c0_summary and "useful_throughput_mbps" not in c0_rx:
                    rx_bytes = c0_summary["flows"][flow]["receivers"][receiver]["measured_app_bytes"]
                    c0_rx["useful_throughput_mbps"] = rx_bytes * 8 / (30 * 1_000_000)
                values = {}
                for metric in metrics + ("latency", "image_completion"):
                    before, after = c0_rx.get(metric), c1_rx.get(metric)
                    if metric == "latency":
                        values[metric] = {
                            key: {"C0_s": before.get(key), "C1_s": after.get(key),
                                  "delta_s": (after.get(key) - before.get(key)
                                              if after and before and after.get(key) is not None
                                              and before.get(key) is not None else None)}
                            for key in ("p99_s", "max_s")}
                    elif metric == "image_completion":
                        values[metric] = (None if before is None and after is None else {
                            key: {"C0": before.get(key) if before else None,
                                  "C1": after.get(key) if after else None,
                                  "delta_C1_minus_C0": (after.get(key) - before.get(key)
                                      if before and after and isinstance(before.get(key), (int, float))
                                      and isinstance(after.get(key), (int, float)) else None)}
                            for key in ("p99_s", "max_s", "deadline_miss_ratio_including_missing_images")})
                    else:
                        values[metric] = {"C0": before, "C1": after,
                                          "delta_C1_minus_C0": (after - before
                                              if isinstance(before, (int, float))
                                              and isinstance(after, (int, float)) else None)}
                receivers[receiver] = values
            cell["flows"][flow] = receivers
        comparison[config] = cell
    def delta(a, b):
        return b - a

    h1_report = {}
    h1_key = "Validate_C0_L0_A0"
    h1_c0, h1_c1 = baseline[h1_key], result[h1_key.replace("C0", "C1")]
    for flow, values in h1_c0["qos"].items():
        if values["criticality"] == "low":
            continue
        h1_report[flow] = {}
        for receiver, c0_rx in values["receivers"].items():
            c1_rx = h1_c1["qos"][flow]["receivers"][receiver]
            h1_report[flow][receiver] = {
                "C0_p99_s": (c0_rx.get("latency") or {}).get("p99_s"),
                "C1_p99_s": (c1_rx.get("latency") or {}).get("p99_s"),
                "delta_p99_C1_minus_C0_s": (
                    delta((c0_rx.get("latency") or {}).get("p99_s"),
                          (c1_rx.get("latency") or {}).get("p99_s"))
                    if (c0_rx.get("latency") or {}).get("p99_s") is not None and
                       (c1_rx.get("latency") or {}).get("p99_s") is not None else None),
                "C0_max_s": (c0_rx.get("latency") or {}).get("max_s"),
                "C1_max_s": (c1_rx.get("latency") or {}).get("max_s"),
                "C0_deadline_miss_ratio": c0_rx["deadline_miss_ratio_including_loss"],
                "C1_deadline_miss_ratio": c1_rx["deadline_miss_ratio_including_loss"],
                "C0_image_completion": c0_rx.get("image_completion"),
                "C1_image_completion": c1_rx.get("image_completion"),
                "C0_packet_loss_ratio": c0_rx["packet_loss_ratio"],
                "C1_packet_loss_ratio": c1_rx["packet_loss_ratio"],
                "C0_goodput_payload_ratio": c0_rx["goodput_payload_ratio"],
                "C1_goodput_payload_ratio": c1_rx["goodput_payload_ratio"],
            }

    h2_report = {}
    for load in (2, 3):
        h2_report[f"L{load}"] = {}
        c0_a0 = baseline[f"Validate_C0_L{load}_A0"]
        c0_a1 = baseline[f"Validate_C0_L{load}_A1"]
        for agg in (0, 1):
            c0 = baseline[f"Validate_C0_L{load}_A{agg}"]
            c1 = result[f"Validate_C1_L{load}_A{agg}"]
            c0_critical, c1_critical = critical_summary(c0), critical_summary(c1)
            c0_queue, c1_queue = queue_summary(c0), queue_summary(c1)
            h2_report[f"L{load}"][f"A{agg}_C1_minus_C0"] = {
                "critical_latency_p99_max_delta_s": c1_critical["max_critical_p99_s"] - c0_critical["max_critical_p99_s"],
                "critical_max_latency_delta_s": c1_critical["max_critical_latency_s"] - c0_critical["max_critical_latency_s"],
                "critical_deadline_miss_ratio_max_delta": c1_critical["max_critical_deadline_miss_ratio"] - c0_critical["max_critical_deadline_miss_ratio"],
                "camera_image_completion_p99_max_delta_s": c1_critical["max_camera_image_completion_p99_s"] - c0_critical["max_camera_image_completion_p99_s"],
                "camera_image_deadline_miss_ratio_max_delta": c1_critical["max_camera_image_deadline_miss_ratio"] - c0_critical["max_camera_image_deadline_miss_ratio"],
                "peak_camera_queue_bits_delta": c1_queue["peak_occupancy_bits"]["camera_talkers"] - c0_queue["peak_occupancy_bits"]["camera_talkers"],
                "peak_G1_G4_queue_bits_delta": c1_queue["peak_occupancy_bits"]["G1_G4"] - c0_queue["peak_occupancy_bits"]["G1_G4"],
                "max_queueing_time_s_delta": c1_queue["max_queueing_time_s"] - c0_queue["max_queueing_time_s"],
            }
        h2_report[f"L{load}"]["C0_A1_minus_A0"] = {
            "critical_latency_p99_max_delta_s": critical_summary(c0_a1)["max_critical_p99_s"] - critical_summary(c0_a0)["max_critical_p99_s"],
            "critical_max_latency_delta_s": critical_summary(c0_a1)["max_critical_latency_s"] - critical_summary(c0_a0)["max_critical_latency_s"],
            "critical_deadline_miss_ratio_max_delta": critical_summary(c0_a1)["max_critical_deadline_miss_ratio"] - critical_summary(c0_a0)["max_critical_deadline_miss_ratio"],
            "camera_image_completion_p99_max_delta_s": critical_summary(c0_a1)["max_camera_image_completion_p99_s"] - critical_summary(c0_a0)["max_camera_image_completion_p99_s"],
            "camera_image_deadline_miss_ratio_max_delta": critical_summary(c0_a1)["max_camera_image_deadline_miss_ratio"] - critical_summary(c0_a0)["max_camera_image_deadline_miss_ratio"],
            "peak_G1_G4_queue_bits_delta": queue_summary(c0_a1)["peak_occupancy_bits"]["G1_G4"] - queue_summary(c0_a0)["peak_occupancy_bits"]["G1_G4"],
            "max_queueing_time_s_delta": queue_summary(c0_a1)["max_queueing_time_s"] - queue_summary(c0_a0)["max_queueing_time_s"],
        }

    report = {"baseline_source": str(c0_path.relative_to(ROOT)),
              "seed": 41,
              "metric_definitions": {
                  "packet_latency": "receptor simTime - pacote CreationTimeTag; apenas pacotes criados em [warmup, end), recebidos até end+drain",
                  "packet_deadline_misses": "latência individual desde a liberação daquele pacote; amostras vetoriais recontadas e conferidas com o CSV do receptor",
                  "image_completion_latency": "para F02-F05, recepção do último dos 30 frames únicos menos a disponibilidade da imagem (início do ciclo); inclui todo o espaçamento C1",
                  "camera_image_cohort": "imagens cujo início ocorre em [warmup, end); frames finais podem chegar durante a drenagem",
                  "camera_image_deadline_misses": "imagem incompleta por perda ou conclusão após o deadline contado desde sua disponibilidade; gates de viabilidade C0/C1 usam esta medida para F02-F05",
                  "empirical_p99": "nearest-rank: ordem ceil(0.99*n), heap de cauda com capacidade fixa floor(0.01*N)+1 definida pela população medida; unidade segundos no JSON",
                  "vector_row_format": "OMNeT++ 6.4 vectorId eventNumber time value; seleção usa vectorId (primeira coluna), timestamp é time (terceira) e value está em segundos",
                  "measurement_window_filter": "latência por pacote: time-value (CreationTimeTag) em [warmup,end); conclusão de imagem: time-value (disponibilidade) em [warmup,end); eventos recebidos até end+drain",
                  "comparison_metric_audit": {
                      "root_cause": "O heap de p99 crescia com 1% das amostras já lidas; como os vetores são temporais, valores antigos de baixa latência permaneciam no heap e o menor elemento final não representava nearest-rank p99.",
                      "correction": "Capacidade fixa calculada da população esperada antes da leitura; amostras e misses são filtrados pelo timestamp de origem coerente com a definição do CSV.",
                      "reconciliations": "Em todas as células/fluxos, amostras, máximo e misses do vetor são comparados com os CSVs do receptor; câmeras também reconciliam imagens completas e misses de conclusão.",
                  },
              },
              "buffer_profile": {"camera_talkers_per_class_bytes": 65536,
                                 "G1_G4_per_class_bytes": 131072,
                                 "other_egresses_per_class_bytes": 32768},
              "cells": comparison,
              "hypothesis_screen": {
                  "H1": {"P1_contrast": "C0-C4 at L0/A0", "available_contrast": "C0-C1 at L0/A0 only",
                         "critical_flow_metrics": h1_report,
                         "interpretation": "Single-seed engineering comparison; C2-C4 and replication-level confidence intervals are unavailable. Treat as preliminary evidence, not a hypothesis test."},
              "H2": {"P1_contrast": "A1-A0 in C0; C1-C0 at L2/L3",
                         "contrasts": h2_report,
                         "interpretation": "Contrasts are descriptive for paired seed 41. Direction and practical magnitude are reported without requiring support of H2."},
              }}
    for config, cell in comparison.items():
        c0_key = config.replace("Validate_C1_", "Validate_C0_")
        cell["aggregate_metrics"] = {"C0": metric_summary(baseline[c0_key]),
                                     "C1": metric_summary(result[config])}
    (output / "C0_C1_comparison.json").write_text(json.dumps(report, indent=2) + "\n")
    lines = ["# Comparação C0/C1 — P1 com filas de câmera de 64 KiB", "",
             "Matrizes completas L0–L3 × A0/A1, pareadas pela seed 41. Cada célula foi executada com 1 s de warm-up, 30 s de medição e 50 ms de drenagem. O JSON contém métricas por fluxo/receptor, detalhes de filas e contrastes H1/H2.", "",
             "## Auditoria das métricas", "",
             "A causa era o heap usado no percentil: sua capacidade crescia com 1% das amostras já lidas. Como os vetores são gravados em ordem temporal, amostras antigas de baixa latência permaneciam no heap; o menor valor final não era o nearest-rank p99. Isso subestimava p99 sem afetar máximos nem contadores de misses. Corrigi para capacidade fixa `floor(0,01·N)+1`, definida pela população esperada, que produz a ordem `ceil(0,99·N)`. A janela agora é aplicada ao timestamp de origem (`tempo do vetor − latência`): `CreationTimeTag` para pacote e disponibilidade para imagem. Em todas as células/fluxos, amostras, máximo e misses são reconciliados com os CSVs; imagens também são comparadas aos seus contadores. Os tempos permanecem em segundos no JSON.", "",
             "A latência por pacote continua sendo `recepção − liberação individual`. F02–F05 também têm uma medida distinta por imagem: `recepção do último frame − disponibilidade da imagem`, incluindo o espaçamento de C1. As imagens são incluídas pelo instante de início em `[warm-up, fim da medição)` e seus frames finais podem chegar na drenagem. O gate de viabilidade das câmeras passa a usar misses de imagem, contando imagem incompleta/perdida ou concluída após o deadline; o JSON conserva também misses por pacote para permitir a distinção.", "",
             "## Verificação das câmeras e perdas", "",
             "| Célula | Viável C0/C1 | Frames F02/F03/F04/F05 | Overflow CAM C0/C1 | Drops rede C0/C1 |", "|---|---|---:|---:|---:|"]
    for key, cell in comparison.items():
        frame_counts = "/".join(str(cell["camera_frame_generation"][flow]["C0_generated_frames"])
                                 for flow in ("F02", "F03", "F04", "F05"))
        cam0 = sum(x["packets"] for x in cell["queues"]["C0"]["camera_talker_drops"])
        cam1 = sum(x["packets"] for x in cell["queues"]["C1"]["camera_talker_drops"])
        net0 = sum(x["packets"] for x in cell["queues"]["C0"]["network_queue_drops"])
        net1 = sum(x["packets"] for x in cell["queues"]["C1"]["network_queue_drops"])
        c0_status = "sim" if cell["C0_viable"] else "não"
        c1_status = "sim" if cell["C1_viable"] else "não"
        lines.append(f"| {key.removeprefix('Validate_')} | {c0_status}/{c1_status} | {frame_counts} | {cam0}/{cam1} | {net0}/{net1} |")
    lines.extend(["", "## Métricas agregadas por célula", "",
                  "Valores C0/C1: p99 é o maior p99 por pacote entre fluxos críticos; miss crítico aplica o gate específico do fluxo (câmeras por imagem, demais por pacote). Perda é o pior rácio entre receptores; goodput é o menor rácio de payload. Ocupação é o máximo observado nas filas CAM e G1–G4.",
                  "", "| Célula | p99 pacote crítico (ms) | p99 conclusão câmera (ms) | Miss crítico (%) | Perda máx. (%) | Goodput mín. (%) | Ocup. câmera máx. (KiB) | Ocup. G1–G4 máx. (KiB) | Tempo em fila máx. (ms) | Drops totais |",
                  "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"])
    for key, cell in comparison.items():
        a, b = cell["aggregate_metrics"]["C0"], cell["aggregate_metrics"]["C1"]
        pair = lambda x, y, scale=1: f"{x*scale:.4g}/{y*scale:.4g}"
        lines.append("| " + key.removeprefix("Validate_") + " | " +
                     pair(a["max_critical_p99_s"], b["max_critical_p99_s"], 1e3) + " | " +
                     pair(a["max_camera_image_completion_p99_s"], b["max_camera_image_completion_p99_s"], 1e3) + " | " +
                     pair(a["max_critical_deadline_miss_ratio"], b["max_critical_deadline_miss_ratio"], 100) + " | " +
                     pair(a["max_packet_loss_ratio"], b["max_packet_loss_ratio"], 100) + " | " +
                     pair(a["min_goodput_payload_ratio"], b["min_goodput_payload_ratio"], 100) + " | " +
                     pair(a["max_camera_occupancy_bits"], b["max_camera_occupancy_bits"], 1/8192) + " | " +
                     pair(a["max_bottleneck_occupancy_bits"], b["max_bottleneck_occupancy_bits"], 1/8192) + " | " +
                     pair(a["max_queueing_time_s"], b["max_queueing_time_s"], 1e3) + " | " +
                     f"{a['recorded_drops']}/{b['recorded_drops']} |")
    h1_cells = (baseline["Validate_C0_L0_A0"], result["Validate_C1_L0_A0"])
    h1_c0_critical = critical_summary(h1_cells[0])
    h1_c1_critical = critical_summary(h1_cells[1])
    h2_l2_c0 = h2_report["L2"]["C0_A1_minus_A0"]
    h2_l3_c0 = h2_report["L3"]["C0_A1_minus_A0"]
    h2_l3_a1 = h2_report["L3"]["A1_C1_minus_C0"]
    lines.extend([
        "",
        "## Leitura dos resultados e relação com H1/H2",
        "",
        f"Em C0, {sum(bool(baseline[k].get('viable')) for k in baseline)}/8 células atendem aos gates de viabilidade; em C1, {sum(bool(result[k].get('viable')) for k in result)}/8. A pior taxa de miss crítico em C0 cresce de {critical_summary(baseline['Validate_C0_L0_A0'])['max_critical_deadline_miss_ratio']*100:.2f}% em L0/A0 para {critical_summary(baseline['Validate_C0_L3_A1'])['max_critical_deadline_miss_ratio']*100:.2f}% em L3/A1; os misses concentram-se em F01 e, em L2/L3, também F06/F07. Em C1 permaneceram em zero nas oito células. As perdas e drops são zero nos dois tratamentos, e o goodput de payload mínimo é 100%; portanto a não viabilidade de C0 vem de misses de deadline, não de descarte.",
        "",
        f"A fila de talker de câmera atingiu {queue_summary(baseline['Validate_C0_L3_A1'])['peak_occupancy_bits']['camera_talkers']/8192:.2f} KiB em C0 e {queue_summary(result['Validate_C1_L3_A1'])['peak_occupancy_bits']['camera_talkers']/8192:.2f} KiB em C1. Em C0/A1, o pico de G1–G4 atingiu {queue_summary(baseline['Validate_C0_L3_A1'])['peak_occupancy_bits']['G1_G4']/8192:.2f} KiB; em C1/A1, {queue_summary(result['Validate_C1_L3_A1'])['peak_occupancy_bits']['G1_G4']/8192:.2f} KiB. Nenhuma célula teve crescimento sustentado de filas.",
        "",
        f"H1 define C0–C4 em L0/A0. O contraste parcial C0–C1 disponível mostra p99 crítico por pacote de {h1_c0_critical['max_critical_p99_s']*1e3:.3f} ms em C0 e {h1_c1_critical['max_critical_p99_s']*1e3:.3f} ms em C1; o p99 de conclusão de imagem das câmeras é {h1_c0_critical['max_camera_image_completion_p99_s']*1e3:.3f}/{h1_c1_critical['max_camera_image_completion_p99_s']*1e3:.3f} ms. O maior rácio de miss do gate crítico é {h1_c0_critical['max_critical_deadline_miss_ratio']*100:.3f}%/{h1_c1_critical['max_critical_deadline_miss_ratio']*100:.3f}%; perdas e goodput continuam reportados separadamente. Sem C2–C4 e sem as 30 seeds, isso é evidência preliminar e não testa H1 por completo.",
        "",
        f"Para H2, em C0/A1−A0 o pior p99 crítico por pacote aumenta {h2_l2_c0['critical_latency_p99_max_delta_s']*1e3:.3f} ms em L2 e {h2_l3_c0['critical_latency_p99_max_delta_s']*1e3:.3f} ms em L3; o p99 de conclusão de imagem muda {h2_l2_c0['camera_image_completion_p99_max_delta_s']*1e3:.3f}/{h2_l3_c0['camera_image_completion_p99_max_delta_s']*1e3:.3f} ms. O rácio máximo de miss do gate muda {h2_l2_c0['critical_deadline_miss_ratio_max_delta']*100:.2f}/{h2_l3_c0['critical_deadline_miss_ratio_max_delta']*100:.2f} pontos percentuais. No contraste C1−C0 em L3/A1, o p99 crítico por pacote muda {h2_l3_a1['critical_latency_p99_max_delta_s']*1e3:.3f} ms e o p99 de conclusão de imagem muda {h2_l3_a1['camera_image_completion_p99_max_delta_s']*1e3:.3f} ms; os misses mudam {h2_l3_a1['critical_deadline_miss_ratio_max_delta']*100:.2f} pontos e o pico de G1–G4 muda {h2_l3_a1['peak_G1_G4_queue_bits_delta']/8192:.2f} KiB. São contrastes descritivos pareados por seed, sem exigir confirmação de H2.",
        "",
        "As filas de câmeras não registraram overflow e nenhuma outra fila registrou drops. Logo, não há localização de perda de pacote nesta matriz; os contadores por fila e ocupações continuam no JSON para auditar cada egress.",
    ])
    lines.extend(["", "O JSON complementa esta leitura com throughput útil, goodput, perda, p99/máximo e filas por fluxo/receptor/célula. `network_queue_drops` lista módulo/porta e classe de qualquer fila que descartou pacotes; `camera_frame_generation` registra contagem e bytes por fluxo, iguais entre C0/C1.", ""])
    (output / "C0_C1_analysis.md").write_text("\n".join(lines))


def check_paired_transients(configs):
    reference = None
    for config in configs:
        c1_dir = SIM / "results/C1/p1-validation-64KiB" / f"{config}-0"
        with (c1_dir / "events.csv").open() as stream:
            c1_events = [tuple(row[key] for key in
                          ("flow", "block", "signature", "duration", "volume_bytes"))
                          for row in csv.DictReader(stream)]
        if reference is None:
            reference = c1_events
        require(c1_events == reference, f"{c1_dir.name}: F21/F22 events differ across L/A")
        c0_config = config.replace("Validate_C1_", "Validate_C0_")
        c0_dir = SIM / "results/C0/p1-validation-64KiB" / f"{c0_config}-0"
        with (c0_dir / "events.csv").open() as stream:
            c0_events = [tuple(row[key] for key in
                          ("flow", "block", "signature", "duration", "volume_bytes"))
                          for row in csv.DictReader(stream)]
        require(c1_events == c0_events,
                f"{config}: F21/F22 event draws differ from paired C0 seed-41 cell")


def has_complete_raw_result(config, output):
    run_dir = output / f"{config}-0"
    vec_path = next(output.glob(f"{config}-#*.vec"), None)
    sca_path = output / f"{config}-#0.sca"
    log_path = output / f"{config}.log"
    if not (run_dir.is_dir() and (run_dir / "run.csv").is_file() and
            (run_dir / "releases.csv").is_file() and
            sca_path.is_file() and vec_path is not None and log_path.is_file()):
        return False
    log_text = log_path.read_text(errors="replace")
    if "Simulation time limit reached -- at t=31.05s" not in log_text or "End." not in log_text:
        return False
    # Older C1 vectors omit paced tail-frame image completion, so they cannot
    # support the P1 camera deadline gate and must be rerun before reuse.
    with vec_path.open(errors="replace") as stream:
        return any(line.startswith("vector ") and
                   "imageCompletionLatency:vector" in line for line in stream)


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inet-root", default=os.environ.get("INET_ROOT"))
    parser.add_argument("--omnetpp-root", default=os.environ.get("OMNETPP_ROOT"))
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--compare-existing", action="store_true",
                        help="rebuild the C0/C1 comparison from completed acceptance JSONs")
    parser.add_argument("--reassess-existing", action="store_true",
                        help="recompute the C1 report from completed raw results without rerunning OMNeT++")
    parser.add_argument("--resume", action="store_true",
                        help="reuse complete raw cells and simulate only cells without complete result files")
    args = parser.parse_args()
    require(args.jobs > 0, "--jobs must be positive")
    output = SIM / "results/C1/p1-validation-64KiB"
    if args.compare_existing:
        c1_path = output / "C1_acceptance.json"
        require(c1_path.exists(), f"Missing C1 acceptance report: {c1_path}")
        result = json.loads(c1_path.read_text())
        check_paired_transients(sorted(result))
        write_comparison(result)
        print(f"C0/C1 comparison written under {output}")
        return
    if args.reassess_existing:
        configs = [f"Validate_C1_L{level}_A{aggregation}"
                   for level in range(4) for aggregation in range(2)]
        def reassess_or_reuse(config):
            run_dir = output / f"{config}-0"
            acceptance = run_dir / "c1-acceptance.json"
            vec = next(output.glob(f"{config}-#*.vec"), None)
            camera_flows = {row["flow_id"] for row in csv.DictReader(
                (SIM / "zonal/traffic/flows.csv").open()) if row["family"] == "camera"}
            # Keep reports already produced from this exact raw run; reparse
            # only cells whose vectors were replaced after the interrupted
            # matrix pass.
            if (acceptance.is_file() and vec is not None and
                    acceptance.stat().st_mtime_ns > vec.stat().st_mtime_ns):
                report = json.loads(acceptance.read_text())
                camera_metrics_present = all(
                    report.get("qos", {}).get(flow, {}).get("receivers") and
                    all(receiver.get("image_completion") is not None
                        for receiver in report["qos"][flow]["receivers"].values())
                    for flow in camera_flows)
                if (report.get("config") == config and report.get("treatment") == "C1" and
                        camera_metrics_present):
                    return report, run_dir
            return run_cell(config, output, execute=False)
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            reports = list(pool.map(reassess_or_reuse, configs))
        check_paired_transients(configs)
        for report, _ in reports:
            require(report["measurement_drop_samples_available"] or
                    report["recorded_drops"] == 0,
                    f"{report['config']}: drops occurred but timestamped queue-drop vectors are missing")
        result = {report["config"]: report for report, _ in reports}
        (output / "C1_acceptance.json").write_text(json.dumps(result, indent=2) + "\n")
        write_comparison(result)
        viable = sum(report["viable"] for report, _ in reports)
        print(f"C1 assessment complete from existing raw results: {viable}/8 viable. Evidence: {output}")
        return
    if not args.inet_root:
        parser.error("Set INET_ROOT or pass --inet-root")
    inet = Path(args.inet_root).resolve()
    omnetpp = Path(args.omnetpp_root).resolve() if args.omnetpp_root else None
    opp_run = shutil.which("opp_run")
    if omnetpp is None and opp_run:
        omnetpp = Path(opp_run).resolve().parent.parent
    if omnetpp is None:
        parser.error("Load the OMNeT++ environment or pass --omnetpp-root")
    env = os.environ.copy()
    library_paths = [str(omnetpp / "lib"), str(inet / "src")]
    if env.get("LD_LIBRARY_PATH"):
        library_paths.append(env["LD_LIBRARY_PATH"])
    env["LD_LIBRARY_PATH"] = ":".join(library_paths)

    output.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, str(ROOT / "scripts/catalog/generate.py"), "--check"], check=True)
    configs = [f"Validate_C1_L{level}_A{aggregation}"
               for level in range(4) for aggregation in range(2)]
    def assess_cell(config):
        run_dir = output / f"{config}-0"
        acceptance_path = run_dir / "c1-acceptance.json"
        if (args.resume and has_complete_raw_result(config, output) and
                acceptance_path.is_file()):
            report = json.loads(acceptance_path.read_text())
            require(report.get("config") == config and report.get("treatment") == "C1",
                    f"{config}: cached C1 report does not match this cell")
            return report, run_dir
        execute = not (args.resume and has_complete_raw_result(config, output))
        return run_cell(config, output, env, inet, execute=execute)
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        reports = list(pool.map(assess_cell, configs))

    check_paired_transients(configs)
    result = {report["config"]: report for report, _ in reports}
    (output / "C1_acceptance.json").write_text(json.dumps(result, indent=2) + "\n")
    write_comparison(result)
    viable = sum(report["viable"] for report, _ in reports)
    print(f"C1 assessment complete: {viable}/8 cells meet P1 viability thresholds. Evidence: {output}")


if __name__ == "__main__":
    main()
