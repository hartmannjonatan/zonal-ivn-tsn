#!/usr/bin/env python3
"""Reprocess existing C0/C1/C2 artifacts into a raw-evidence C2 diagnosis."""
import csv
import argparse
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

from validate_c0 import parse_sca
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "catalog"))
from generate_cbs import LOAD_FACTORS, read_flows, route

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "simulations/results/C2/p1-validation-64KiB-final"
COMPARISON = OUT / "C0_C1_C2_comparison.json"
DIAG_JSON = OUT / "C0_C1_C2_diagnostic.json"
DIAG_MD = OUT / "C0_C1_C2_diagnostic.md"
WARMUP, MEASUREMENT, DRAIN = 1.0, 30.0, 0.05
SIM_END = WARMUP + MEASUREMENT + DRAIN
NEAR_CAPACITY = 0.95
LIMITATIONS_PT = [
    "Os CSVs de fila e transmissão por fluxo agregam o run inteiro; não guardam timestamp por pacote, então não permitem taxas nem drops por fluxo recortados exatamente para a janela de medição.",
    "O vetor timestampado droppedPacketLengthsQueueOverflow identifica fila e tamanho, mas não o fluxo; drops exatos da janela são informados por fila, enquanto a atribuição por fluxo vem dos CSVs agregados do run.",
    "A taxa de entrada da fila é uma estimativa wire-equivalente: bytes do CSV de fila multiplicados pela razão wire_bytes/mac_bytes do catálogo. A contabilização transiente é, portanto, estimada.",
    "Os vetores de ocupação são grandes; este diagnóstico os reprocessa a partir das simulações já gravadas, sem executar o OMNeT++ novamente.",
]


def rows(path):
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def key_iface(module):
    return module.split(".macLayer.queue.queue[", 1)[0]


def device_kind(iface, sources):
    node = iface.removeprefix("ZonalIVN.").split(".eth[", 1)[0]
    return "talker" if node in sources else "switch_or_forwarder"


def diagnostic_route(source, destination):
    if source.endswith(".ZCPU") and destination.endswith(".ZCPU"):
        source_zone, destination_zone = source.split(".", 1)[0], destination.split(".", 1)[0]
        return [f"{source}.eth[0]", f"{source_zone}.ZSW.eth[0]",
                f"CSW.eth[{destination_zone[1]}]", f"{destination_zone}.ZSW.eth[1]",
                f"{destination}.eth[0]"]
    return route(source, destination)


def vector_definitions(path):
    wanted = {}
    with path.open(errors="replace") as f:
        for line in f:
            if line.startswith("vector "):
                parts = line.rstrip().split(" ", 4)
                if len(parts) != 5:
                    continue
                vid, module, metric = int(parts[1]), parts[2], parts[3]
                m = re.fullmatch(r"(ZonalIVN\..*\.eth\[\d+\]\.macLayer\.queue\.queue\[(\d+)\])", module)
                if m and metric in ("queueBitLength:vector", "droppedPacketLengthsQueueOverflow:vector"):
                    wanted[vid] = {"module": m.group(1), "tc": int(m.group(2)), "metric": metric}
            elif line and line[0].isdigit():
                break
    return wanted


def scan_vectors(path, sca):
    definitions = vector_definitions(path)
    occupancy = {vid: {"time": 0.0, "value": 0.0, "area": 0.0,
                       "near": 0.0, "max": 0.0}
                 for vid, d in definitions.items() if d["metric"] == "queueBitLength:vector"}
    for vid, info in occupancy.items():
        raw = sca.get((definitions[vid]["module"], "dataCapacity"))
        info["capacity"] = int(str(raw).removesuffix("b")) if raw else 0
    drops = defaultdict(lambda: {"measurement_packets": 0, "measurement_bytes": 0,
                                 "all_recorded_packets": 0, "all_recorded_bytes": 0})

    def add_interval(info, start, end, cap):
        left, right = max(start, WARMUP), min(end, WARMUP + MEASUREMENT)
        if right <= left:
            return
        dt = right - left
        info["area"] += info["value"] * dt
        if info["value"] >= cap * NEAR_CAPACITY:
            info["near"] += dt

    with path.open(errors="replace") as f:
        for line in f:
            parts = line.split()
            if len(parts) not in (3, 4) or not parts[0].isdigit():
                continue
            try:
                if len(parts) == 4:
                    vid, timestamp, value = int(parts[0]), float(parts[2]), float(parts[3])
                else:
                    vid, timestamp, value = int(parts[0]), float(parts[1]), float(parts[2])
            except ValueError:
                continue
            d = definitions.get(vid)
            if d is None:
                continue
            if d["metric"] == "queueBitLength:vector":
                info = occupancy[vid]
                # Maximum is window-scoped; the vector is event-held between samples.
                if timestamp >= WARMUP and timestamp < WARMUP + MEASUREMENT:
                    info["max"] = max(info["max"], info["value"], value)
                add_interval(info, info["time"], timestamp,
                             info.get("capacity", float("inf")))
                info["time"], info["value"] = timestamp, value
            else:
                acc = drops[d["module"], d["tc"]]
                acc["all_recorded_packets"] += 1
                acc["all_recorded_bytes"] += int(value)
                if WARMUP <= timestamp < WARMUP + MEASUREMENT:
                    acc["measurement_packets"] += 1
                    acc["measurement_bytes"] += int(value)
    for info in occupancy.values():
        add_interval(info, info["time"], WARMUP + MEASUREMENT, info["capacity"])
    return definitions, occupancy, drops


def diagnose_cell(config, flows, source_nodes):
    run_dir = OUT / f"{config}-0"
    sca = parse_sca(OUT / f"{config}-#0.sca")
    report = json.loads((run_dir / "c2-acceptance.json").read_text())
    flow_by_id = {f["flow_id"]: f for f in flows}
    load = int(config.split("_L", 1)[1][0])
    vec_path = next(OUT.glob(f"{config}-#*.vec"))
    defs, occupancy, drop_vec = scan_vectors(vec_path, sca)
    drop_rows = rows(run_dir / "drops.csv")
    queue_rows = rows(run_dir / "queues.csv")
    wire_rows = rows(run_dir / "wire.csv")
    drop_by_queue_flow = defaultdict(int)
    for row in drop_rows:
        tc = int(flow_by_id[row["flow"]]["traffic_class"])
        module = f'{row["interface"]}.macLayer.queue.queue[{tc}]'
        drop_by_queue_flow[module, row["flow"]] += int(row["packets"])
    input_by_queue_flow = defaultdict(lambda: {"packets": 0, "catalog_wire_equiv_bytes": 0.0})
    for row in queue_rows:
        flow = flow_by_id[row["flow"]]
        tc = int(flow["traffic_class"])
        module = f'{row["interface"]}.macLayer.queue.queue[{tc}]'
        ratio = float(flow["wire_bytes"]) / float(flow["mac_bytes"])
        input_by_queue_flow[module, row["flow"]]["packets"] += int(row["packets"])
        input_by_queue_flow[module, row["flow"]]["catalog_wire_equiv_bytes"] += int(row["bytes"]) * ratio
    output_by_queue_flow = defaultdict(lambda: {"packets": 0, "wire_bytes": 0})
    for row in wire_rows:
        flow = flow_by_id[row["flow"]]
        tc = int(flow["traffic_class"])
        module = f'{row["interface"]}.macLayer.queue.queue[{tc}]'
        output_by_queue_flow[module, row["flow"]]["packets"] += int(row["packets"])
        output_by_queue_flow[module, row["flow"]]["wire_bytes"] += int(row["bytes"])

    queue_modules = set()
    for (module, name), _ in sca.items():
        if name == "dataCapacity" and module.endswith(".macLayer.queue.queue[0]"):
            base = module.rsplit("[", 1)[0]
            queue_modules.update(f"{base}[{tc}]" for tc in range(8))
    for module, _ in drop_by_queue_flow:
        queue_modules.add(module)
    for (module, _), _ in input_by_queue_flow.items():
        queue_modules.add(module)
    queue_diagnostics = []
    for module in sorted(queue_modules):
        m = re.fullmatch(r"(ZonalIVN\..*\.eth\[(\d+)\]\.macLayer\.queue\.queue\[(\d+)\])", module)
        if not m:
            continue
        iface, port, tc = key_iface(module), int(m.group(2)), int(m.group(3))
        cap_raw = sca.get((module, "dataCapacity"))
        if cap_raw is None:
            continue
        capacity = int(str(cap_raw).removesuffix("b"))
        total_overflow = int(float(sca.get((module, "droppedPacketsQueueOverflow:count"), 0)))
        flow_drops = {flow: count for (q, flow), count in drop_by_queue_flow.items() if q == module}
        flow_drop_total = sum(flow_drops.values())
        if total_overflow != flow_drop_total:
            raise RuntimeError(f"{config} {module}: SCA drops={total_overflow}, flow CSV={flow_drop_total}")
        meas_drop = drop_vec.get((module, tc), {}).get("measurement_packets")
        occ = next((v for vid, v in occupancy.items() if defs[vid]["module"] == module), None)
        max_raw = sca.get((module, "queueBitLength:max"))
        mean_raw = sca.get((module, "queueBitLength:timeavg"))
        max_bits = float(max_raw) if max_raw is not None else None
        mean_full = float(mean_raw) if mean_raw is not None else None
        trans = [f for f, row in flow_by_id.items()
                 if f in ("F21", "F22") and iface in {f"ZonalIVN.{p}" for dest in row["destinations"].split(";")
                     for p in diagnostic_route(row["source"], dest)} and int(row["traffic_class"]) == tc]
        permanent = sorted({f for f, row in flow_by_id.items()
                            if row["family"] != "transient" and int(row["traffic_class"]) == tc
                            and any(iface == f"ZonalIVN.{p}" for dest in row["destinations"].split(";")
                                    for p in diagnostic_route(row["source"], dest))})
        idle = sca.get((f"{iface}.macLayer.queue.transmissionSelectionAlgorithm[{tc}]", "idleSlope"))
        idle_bps = None
        if idle:
            mat = re.search(r"([0-9.eE+-]+)", str(idle))
            idle_bps = float(mat.group(1)) if mat else None
        in_rows = {f: row for (q, f), row in input_by_queue_flow.items() if q == module}
        out_rows = {f: row for (q, f), row in output_by_queue_flow.items() if q == module}
        input_wire_bytes = sum(v["catalog_wire_equiv_bytes"] for v in in_rows.values())
        output_wire_bytes = sum(v["wire_bytes"] for v in out_rows.values())
        active_flows = sorted(set(in_rows) | set(out_rows) | set(flow_drops))
        per_flow = {}
        for fid in active_flows:
            per_flow[fid] = {
                "role": "transient" if flow_by_id[fid]["family"] == "transient" else "permanent",
                "input_packets_run_aggregate": in_rows.get(fid, {}).get("packets", 0),
                "input_wire_equivalent_bytes_run_aggregate_estimated": round(in_rows.get(fid, {}).get("catalog_wire_equiv_bytes", 0)),
                "output_packets_run_aggregate": out_rows.get(fid, {}).get("packets", 0),
                "output_wire_bytes_run_aggregate": out_rows.get(fid, {}).get("wire_bytes", 0),
                "confirmed_overflow_packets_post_warmup_run": flow_drops.get(fid, 0),
            }
        input_bps = input_wire_bytes * 8 / SIM_END
        output_bps = output_wire_bytes * 8 / SIM_END
        overload_ratio = input_bps / idle_bps if idle_bps else None
        near_fraction = None
        mean_measurement = None
        if occ:
            duration = MEASUREMENT
            near_fraction = occ["near"] / duration
            mean_measurement = occ["area"] / duration
        saturated = (total_overflow > 0 or float(max_bits or 0) >= capacity * NEAR_CAPACITY or
                     float(mean_full or 0) >= capacity * NEAR_CAPACITY)
        if not saturated and not flow_drops:
            continue
        queue_diagnostics.append({
            "module": module, "device_role": device_kind(iface, source_nodes),
            "interface": iface, "port_index": port, "traffic_class": tc,
            "capacity_bits": capacity, "capacity_bytes": capacity // 8,
            "max_occupancy_bits_post_warmup_including_drain": max_bits,
            "max_occupancy_bits_measurement_vector": (occ["max"] if occ else None),
            "mean_occupancy_bits_post_warmup_including_drain": mean_full,
            "mean_occupancy_bits_measurement_vector": mean_measurement,
            "fraction_measurement_time_at_or_above_95pct_capacity": near_fraction,
            "confirmed_overflow_packets_post_warmup_including_drain": total_overflow,
            "confirmed_overflow_packets_measurement_window": meas_drop,
            "overflow_by_flow_post_warmup_run": flow_drops,
            "idle_slope_bps": idle_bps, "catalog_permanent_flows_through_class": permanent,
            "catalog_transient_flows_through_class_excluded_from_reservation": trans,
            "measured_input_rate_wire_equivalent_run_average_bps": input_bps,
            "measured_output_rate_wire_bytes_run_average_bps": output_bps,
            "input_rate_to_idle_slope_ratio_run_average": overload_ratio,
            "input_rate_method": "queues.csv full-run packet/byte counts converted by catalog wire_bytes/mac_bytes ratio; divided by 31.05 s; estimated wire-equivalent rate",
            "output_rate_method": "wire.csv full-run serialized bytes divided by 31.05 s; includes warm-up and drain",
            "flows_observed_at_queue": per_flow,
        })

    # Source population reconciliation is run-wide and receiver deliveries are
    # kept separate for multicast, where one source packet has two deliveries.
    validation = json.loads((run_dir / "validation.json").read_text())
    received_drops_pending = {}
    drops_by_flow = defaultdict(int)
    for row in drop_rows:
        drops_by_flow[row["flow"]] += int(row["packets"])
    pending_by_flow = defaultdict(int)
    for row in validation.get("pending_at_simulation_end", []):
        pending_by_flow[row["flow"]] += int(row["packets"])
    for fid, flow_data in validation["flows"].items():
        receivers = {rx: vals["packets"] for rx, vals in flow_data["receivers"].items()}
        measured = {rx: {"offered_packets": report["qos"][fid]["receivers"][rx]["offered_packets"],
                         "received_by_end_of_drain": report["qos"][fid]["receivers"][rx]["received_packets"],
                         "not_delivered_by_end_of_drain": (
                             report["qos"][fid]["receivers"][rx]["offered_packets"] -
                             report["qos"][fid]["receivers"][rx]["received_packets"])}
                    for rx in receivers}
        generated = int(flow_data["generated_packets"])
        receiver_deliveries = sum(receivers.values())
        if len(receivers) == 1:
            residual = generated - receiver_deliveries - drops_by_flow[fid] - pending_by_flow[fid]
            received_drops_pending[fid] = {
                "source_packets_generated_run": generated, "packets_received_run_by_receiver": receivers,
                "measurement_cohort_delivery_accounting": measured,
                "confirmed_overflow_drops_post_warmup_run": drops_by_flow[fid],
                "still_pending_at_end_by_flow": pending_by_flow[fid],
                "unreconciled_residual_packets": residual,
                "reconciles": residual == 0,
                "deadline_or_loss_gate_scope": "measurement-cohort receiver delivery before end of 50 ms drain; distinct from physical queue drops",
            }
        else:
            received_drops_pending[fid] = {
                "source_packets_generated_run": generated, "packets_received_run_by_receiver": receivers,
                "measurement_cohort_delivery_accounting": measured,
                "confirmed_overflow_drops_post_warmup_run": drops_by_flow[fid],
                "still_pending_at_end_by_flow": pending_by_flow[fid],
                "reconciliation_note": "multicast: shared-path source packet loss can suppress two receiver deliveries; do not subtract summed receiver deliveries from source packets as a unicast conservation equation",
            }
    role_totals = defaultdict(int)
    for q in queue_diagnostics:
        role_totals[q["device_role"]] += q["confirmed_overflow_packets_post_warmup_including_drain"]
    diagnostic_drop_sum = sum(role_totals.values())
    if diagnostic_drop_sum != report["recorded_drops"]:
        raise RuntimeError(f"{config}: detailed drop queues sum to {diagnostic_drop_sum}, report says {report['recorded_drops']}")
    return {
        "config": config,
        "time_scopes": {"measurement_window_s": [WARMUP, WARMUP + MEASUREMENT],
                        "post_warmup_through_simulation_end_s": [WARMUP, SIM_END],
                        "simulation_end_s": SIM_END,
                        "drop_scalar_scope": "OMNeT++ warm-up-excluded scalar through simulation end, includes drain",
                        "queue_csv_scope": "whole simulation event aggregation; individual rows retain first/last timestamps, not per-packet timestamps",
                        "queue_vector_occupancy_scope": "piecewise-constant integration in [1,31); maximum from vector and SCA post-warmup scalar"},
        "queue_overflow_diagnostics": queue_diagnostics,
        "confirmed_overflow_totals_by_device_role": dict(role_totals),
        "source_delivery_drop_pending_reconciliation": received_drops_pending,
        "totals": {"source_packets_generated": validation["source_packets"],
                   "confirmed_overflow_drops_post_warmup_including_drain": report["recorded_drops"],
                   "pending_packets_at_end": report["pending_packet_count_at_simulation_end"],
                   "measurement_window_overflow_drops": sum(q.get("confirmed_overflow_packets_measurement_window") or 0 for q in queue_diagnostics),
                   "nonstable_queues_legacy_metric": len(report.get("nonstable_queues", [])),
                   "nonstable_criterion": "legacy checker: the means of the last three 5 s bins must increase strictly and the first-to-third increase must exceed 5% of queue capacity; bounded full queues and repeated drops can still score stable"},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reuse-extracted", action="store_true",
                        help="reuse queue/vector extraction already written to the diagnostic JSON")
    args = parser.parse_args()
    flows = read_flows()
    source_nodes = {f["source"] for f in flows}
    original = json.loads(COMPARISON.read_text())
    if args.reuse_extracted:
        document = json.loads(DIAG_JSON.read_text())
        diagnostics = document["cells"]
    else:
        diagnostics = {}
        for load in range(4):
            for agg in range(2):
                config = f"Validate_C2_L{load}_A{agg}"
                print(f"Reprocessing existing vectors and scalars: {config}", flush=True)
                diagnostics[config] = diagnose_cell(config, flows, source_nodes)
        document = {
        "source": "Existing simulation artifacts only; no simulation rerun or parameter change",
        "base_comparison": "C0_C1_C2_comparison.json (preserved)",
        "measurement_window": "[1.000, 31.000) s; source cohort selected by existing validation artifacts",
        "simulation_stop": "31.050 s, retaining the configured 50 ms drain",
        "thresholds": {"near_capacity": ">=95% of dataCapacity", "occupancy_method": "event-held queueBitLength vector, time-integrated over measurement window"},
        "limitations": LIMITATIONS_PT,
        "viability_counts": original["viability_counts"],
        "C2_nonstable_metric_interpretation": "nonstable_queues=0 não demonstra recuperação: o critério legado requer médias dos últimos três bins de 5 s estritamente crescentes e aumento superior a 5% da capacidade; ocupação limitada pela capacidade com drops recorrentes pode ser classificada como estável.",
        "cells": diagnostics,
        }
    for config, cell in diagnostics.items():
        run_dir = OUT / f"{config}-0"
        report = json.loads((run_dir / "c2-acceptance.json").read_text())
        validation = json.loads((run_dir / "validation.json").read_text())
        role_totals = defaultdict(int)
        for q in cell["queue_overflow_diagnostics"]:
            role_totals[q["device_role"]] += q["confirmed_overflow_packets_post_warmup_including_drain"]
        if sum(role_totals.values()) != report["recorded_drops"]:
            raise RuntimeError(f"{config}: diagnostic drops do not reconcile with recorded total")
        cell["confirmed_overflow_totals_by_device_role"] = dict(role_totals)
        for q in cell["queue_overflow_diagnostics"]:
            for key in ("max_occupancy_bits_post_warmup_including_drain",
                        "mean_occupancy_bits_post_warmup_including_drain"):
                if q.get(key) is not None:
                    q[key] = float(q[key])
        cell["totals"]["measurement_window_overflow_drops"] = sum(
            q.get("confirmed_overflow_packets_measurement_window") or 0
            for q in cell["queue_overflow_diagnostics"])
        for fid, flow in validation["flows"].items():
            for receiver in flow["receivers"]:
                measured = report["qos"][fid]["receivers"][receiver]
                cell["source_delivery_drop_pending_reconciliation"][fid]["measurement_cohort_delivery_accounting"] = {
                    receiver: {"offered_packets": measured["offered_packets"],
                               "received_by_end_of_drain": measured["received_packets"],
                               "not_delivered_by_end_of_drain": measured["offered_packets"] - measured["received_packets"]}}
    document["cells"] = diagnostics
    document["limitations"] = LIMITATIONS_PT
    document.pop("limitations_pt", None)
    document["C2_nonstable_metric_interpretation"] = (
        "nonstable_queues=0 não demonstra recuperação: o critério legado requer médias dos últimos três bins de 5 s estritamente crescentes e aumento superior a 5% da capacidade; ocupação limitada pela capacidade com drops recorrentes pode ser classificada como estável.")
    DIAG_JSON.write_text(json.dumps(document, indent=2) + "\n")
    write_markdown(document)


def write_markdown(doc):
    lines = ["# Diagnóstico bruto C2 — C0/C1/C2", "",
             "Reprocessamento dos resultados existentes. Nenhuma simulação foi reexecutada; buffers, workload, parâmetros CBS e drenagem de 50 ms foram mantidos. A comparação original `C0_C1_C2_comparison.json` permanece intacta.", "",
             "A janela de medição é `[1,31)` s. Contadores escalares de drops excluem o warm-up e vão até o stop em 31,05 s, incluindo a drenagem. Os CSVs por fluxo agregam o run inteiro e não permitem recortar exatamente por timestamp.", "",
             f"Gate observado: C0 {doc['viability_counts']['C0']}/8; C1 {doc['viability_counts']['C1']}/8; C2 {doc['viability_counts']['C2']}/8. `nonstable_queues=0` usa médias dos últimos três bins de 5 s estritamente crescentes e aumento do primeiro ao terceiro acima de 5% da capacidade; isso não significa recuperação se a fila fica limitada à capacidade e descarta repetidamente.", "",
             "## Egressos com overflow ou saturação", ""]
    for config, cell in doc["cells"].items():
        lines += [f"### {config}", "",
                  "| Papel | Módulo/fila | Capacidade | Máx. pós-warm-up | Ocup. média medida | Tempo ≥95% | Drops run pós-warm-up | Drops [1,31) | Fluxos com drops (run) |", "|---|---|---:|---:|---:|---:|---:|---:|---|"]
        for q in cell["queue_overflow_diagnostics"]:
            flows = ", ".join(f"{k}:{v}" for k, v in q["overflow_by_flow_post_warmup_run"].items()) or "—"
            mean = q["mean_occupancy_bits_measurement_vector"]
            near = q["fraction_measurement_time_at_or_above_95pct_capacity"]
            lines.append(f"| {q['device_role']} | `{q['module']}` | {q['capacity_bytes']} B | {q['max_occupancy_bits_post_warmup_including_drain']:.0f} bit | {f'{mean:.0f} bit' if mean is not None else 'n/d'} | {f'{near*100:.2f}%' if near is not None else 'n/d'} | {q['confirmed_overflow_packets_post_warmup_including_drain']} | {q['confirmed_overflow_packets_measurement_window'] if q['confirmed_overflow_packets_measurement_window'] is not None else 'n/d'} | {flows} |")
        lines.append("")
        lines += ["CBS e taxa de classe nos egressos com gargalo:", "",
                  "| Egress/TC | idleSlope | permanentes reservados | transientes sem reserva | entrada média wire-eq. (run) | saída média wire (run) | entrada/reserva |", "|---|---:|---|---|---:|---:|---:|"]
        for q in cell["queue_overflow_diagnostics"]:
            if q["traffic_class"] not in (4, 6) or not (q["confirmed_overflow_packets_post_warmup_including_drain"] or q["max_occupancy_bits_post_warmup_including_drain"] >= q["capacity_bits"] * NEAR_CAPACITY):
                continue
            trans = ", ".join(q["catalog_transient_flows_through_class_excluded_from_reservation"]) or "—"
            perm = ", ".join(q["catalog_permanent_flows_through_class"]) or "—"
            slope = f"{q['idle_slope_bps']/1e6:.3f} Mb/s" if q["idle_slope_bps"] else "—"
            ratio = f"{q['input_rate_to_idle_slope_ratio_run_average']:.2f}×" if q["input_rate_to_idle_slope_ratio_run_average"] is not None else "—"
            lines.append(f"| `{q['interface']} TC{q['traffic_class']}` | {slope} | {perm} | {trans} | {q['measured_input_rate_wire_equivalent_run_average_bps']/1e6:.3f} Mb/s* | {q['measured_output_rate_wire_bytes_run_average_bps']/1e6:.3f} Mb/s | {ratio}* |")
        lines += ["", "`*` Médias full-run, não recortadas à janela; entrada é estimativa wire-equivalente obtida dos bytes de fila e da razão `wire_bytes/mac_bytes` do catálogo. `idleSlope` é configuração medida/resolvida no SCA. Os fluxos F21/F22 aparecem na demanda/serviço quando ativos, embora excluídos da reserva permanente. O detalhamento JSON registra contagem por fluxo, capacidades, ocupações e limites de interpretação.", ""]
        role_totals = cell["confirmed_overflow_totals_by_device_role"]
        lines.append(f"Reconciliação por papel: {role_totals.get('talker', 0)} drops em talkers + {role_totals.get('switch_or_forwarder', 0)} em switches/forwarders = {cell['totals']['confirmed_overflow_drops_post_warmup_including_drain']} drops confirmados no contador geral. Os drops detalhados por fila reconciliam com o total.")
        lines.append("")
    lines += ["## Entrega, drops e pendências", "",
              "A contabilização do JSON separa a coorte de medição (oferecidos e recebidos até o fim da drenagem, por receptor) do agregado run-wide de pacotes gerados, drops físicos confirmados e pendentes. A coorte informa ausência de entrega até o encerramento, não o local/cause física; os drops por overflow são contadores físicos independentes. Em unicast, o agregado reconcilia gerados = recebidos + drops + pendentes em cada célula. F14 é multicast: drops em trecho compartilhado podem eliminar duas entregas, portanto a soma dos dois receptores não é uma conservação unicast.", "",
              "Os pendentes permanecem em campo próprio e foram conferidos pelo validador anterior com ocupação final das filas. Não os classificamos como perdas físicas. Ainda assim, a inviabilidade não desaparece ao separar categorias: todas as células C2 têm drops de overflow confirmados e misses/perdas de entrega medidos; a maior parte dos fluxos unicast reconcilia integralmente em recepção + drop + pendência, sem resíduo.", "",
              "## Critério de estabilidade e limites", "",
              "O indicador `nonstable_queues` conta crescimento sustentado, não recorrência de overflow nem fração de tempo perto da capacidade. Seu critério é: médias dos últimos três bins de 5 s estritamente crescentes e aumento do primeiro ao terceiro acima de 5% da capacidade. Neste diagnóstico, ocupação média, máximo e fração temporal acima de 95% foram calculados dos vetores `queueBitLength` usando retenção do último valor entre eventos, integração em `[1,31)`. Drops por fila na janela foram contados pelos vetores timestampados; drops por fluxo vêm de CSVs agregados pós-warm-up e não podem ser repartidos com exatidão pela janela. As taxas médias por fluxo também não têm timestamps no CSV, por isso as taxas de classe apresentadas são run-wide e a conversão de entrada é explicitamente estimada.", "",
              "Os resultados sustentam a inviabilidade de C2 nominal sem exigir que C2 seja tornado viável: a reserva cobre os fluxos permanentes conforme o P1, mas não reserva banda para os bursts transientes F21/F22. Em CSW→Z3/TC6, `idleSlope` coincide com a reserva de F13; a taxa média de saída observada fica no mesmo nível, enquanto a entrada wire-equivalente de run excede a reserva e as perdas são majoritariamente F21/F22. A fila fica ≥95% da capacidade por cerca de 99% do tempo medido também entre episódios transitórios, sem intervalo significativo de recuperação. `nonstable_queues=0` só informa que o crescimento líquido não excedeu o critério por bins; não significa que a fila recuperou sem perdas.", "",
              "## Limitações de recuperação", "",
              *[f"- {item}" for item in doc.get("limitations", LIMITATIONS_PT)], ""]
    DIAG_MD.write_text("\n".join(lines))


if __name__ == "__main__":
    main()
