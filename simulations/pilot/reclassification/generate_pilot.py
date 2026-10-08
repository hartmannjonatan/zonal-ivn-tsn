#!/usr/bin/env python3
"""Generate isolated reclassification-pilot catalogs and nominal CBS profiles."""
import csv
import json
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "scripts/catalog"))
from generate_cbs import LOAD_FACTORS, capacity_bps, nominal_reservations, read_flows

CATALOG = ROOT / "simulations/zonal/traffic/catalog.xml"
TRANSIENTS = ROOT / "simulations/zonal/traffic/transients.csv"
BINDINGS = ROOT / "simulations/zonal/configs/catalog-bindings.ini"
VARIANT_IDS = {"F02", "F03", "F11", "F12", "F13", "F21", "F22"}
CAP = 0.75


def read_csv(path):
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def make_catalogs():
    source_xml = ET.parse(CATALOG)
    original_xml = ET.ElementTree(ET.fromstring(ET.tostring(source_xml.getroot())))
    variant_xml = ET.ElementTree(ET.fromstring(ET.tostring(source_xml.getroot())))
    variant_flows = read_flows()
    original_rows = read_flows()
    rows_by_id = {f["flow_id"]: f for f in variant_flows}
    for element in variant_xml.getroot().findall("flow"):
        fid = element.get("name")
        if fid in VARIANT_IDS:
            element.set("pcp", "4")
            rows_by_id[fid]["pcp"] = "4"
            rows_by_id[fid]["traffic_class"] = "4"
    original_xml.write(HERE / "catalog/catalog_original.xml", encoding="utf-8", xml_declaration=True)
    variant_xml.write(HERE / "catalog/catalog_variant.xml", encoding="utf-8", xml_declaration=True)
    shutil.copy2(TRANSIENTS, HERE / "catalog/transients.csv")
    for name, rows in (("original", original_rows), ("variant", variant_flows)):
        with (HERE / f"catalog/flows_{name}.csv").open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys(), lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
    original_bindings = BINDINGS.read_text()
    variant_bindings = original_bindings.replace(
        'xmldoc("../traffic/catalog.xml")', 'xmldoc("catalog_variant.xml")')
    original_bindings = original_bindings.replace(
        'xmldoc("../traffic/catalog.xml")', 'xmldoc("catalog_original.xml")')
    # Change only PCP values in stream encoder/decoder rows for the declared IDs.
    def remap_binding(match):
        fid, vlan, pcp = match.groups()
        return f'{{stream: "{fid}", vlan: {vlan}, pcp: {4 if fid in VARIANT_IDS else pcp}}}'
    variant_bindings = re.sub(
        r'\{stream: "(F\d\d)", vlan: (\d+), pcp: (\d+)\}', remap_binding, variant_bindings)
    (HERE / "catalog/catalog_bindings_original.ini").write_text(original_bindings)
    (HERE / "catalog/catalog_bindings_variant.ini").write_text(variant_bindings)
    return original_rows, variant_flows


def render_profile(name, flows):
    rows = []
    for (load, egress, tc), item in nominal_reservations(flows).items():
        if load != 2:
            continue
        cap = capacity_bps(egress)
        rows.append({"egress": egress, "tc": tc, "idle_slope_bps": item["bps"],
                     "idle_slope_mbps": item["bps"] / 1e6, "port_rate_bps": cap,
                     "permanent_flows": sorted(item["flows"])})
    totals = {}
    for row in rows:
        totals[row["egress"]] = totals.get(row["egress"], 0) + row["idle_slope_bps"]
    for row in rows:
        row["total_port_reservation_bps"] = totals[row["egress"]]
        row["cap_fraction"] = totals[row["egress"]] / row["port_rate_bps"]
        row["headroom_to_75pct_bps"] = int(CAP * row["port_rate_bps"]) - totals[row["egress"]]
    rows.sort(key=lambda r: (r["egress"], r["tc"]))
    ini = [f"# Pilot-only nominal CBS rates for L2, derived from {name} flow mapping.",
           "# Do not include in official C2/C3 configurations.", f"[Config PilotC2{name.title()}Rates]"]
    for row in rows:
        module = f"*.{row['egress']}.macLayer.queue.transmissionSelectionAlgorithm[{row['tc']}]"
        ini += [f'{module}.typename = "Ieee8021qCreditBasedShaper"',
                f"{module}.idleSlope = {row['idle_slope_bps']}bps",
                f"{module}.numCredits.result-recording-modes = vector,max,min,timeavg"]
    (HERE / f"configs/cbs_{name}_nominal.ini").write_text("\n".join(ini) + "\n")
    with (HERE / f"configs/cbs_{name}_nominal.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys(), lineterminator="\n")
        writer.writeheader()
        for row in rows:
            row = dict(row)
            row["permanent_flows"] = ";".join(row["permanent_flows"])
            writer.writerow(row)
    return rows


def mapping_table(original_rows, variant_rows):
    variant_by_id = {r["flow_id"]: r for r in variant_rows}
    rows = []
    for source in original_rows:
        variant = variant_by_id[source["flow_id"]]
        pcp0, tc0 = int(source["pcp"]), int(source["traffic_class"])
        pcp1, tc1 = int(variant["pcp"]), int(variant["traffic_class"])
        def mechanism(tc, row):
            c1 = "C1=SP+camera pre-shaping" if row["family"] == "camera" else "C1=SP"
            c2 = f"C2=TC{tc} CBS" if tc in (4, 6) else "C2=SP"
            return f"C0=SP; {c1}; {c2}"
        mechanism0 = mechanism(tc0, source)
        mechanism1 = mechanism(tc1, variant)
        rows.append({"flow_id": source["flow_id"], "source": source["source"],
                     "destinations": source["destinations"], "vlan": int(source["vlan"]),
                     "original_pcp": pcp0, "original_tc": tc0,
                     "original_mechanism": mechanism0,
                     "variant_pcp": pcp1, "variant_tc": tc1,
                     "variant_mechanism": mechanism1,
                     "variant_changed": (pcp0, tc0) != (pcp1, tc1)})
    with (HERE / "mapping_table.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys(), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return rows


def main():
    original, variant = make_catalogs()
    orig_rates = render_profile("original", original)
    variant_rates = render_profile("variant", variant)
    rows = mapping_table(original, variant)
    report = {
        "exploratory": True,
        "official_profile_frozen": False,
        "calibration_found_feasible_candidate": None,
        "source_catalog": "simulations/zonal/traffic/flows.csv",
        "pilot_catalogs": {"original": "catalog/catalog_original.xml",
                           "variant": "catalog/catalog_variant.xml"},
        "changed_flow_ids": sorted(VARIANT_IDS),
        "mapping": rows,
        "nominal_reservations_l2": {"original": orig_rates, "variant": variant_rates},
        "cap_fraction": CAP,
        "calendar_method": "TrafficPlan precomputes F21/F22 events during module initialization using dedicated RNG streams 0 and 1; event order in the network cannot affect the calendar. Every pilot run will be checked against the saved first-run events.csv SHA-256.",
        "commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
                                   capture_output=True, check=True).stdout.strip(),
        "working_tree_dirty_before_pilot": True,
    }
    (HERE / "mapping_and_nominal_reservations.json").write_text(json.dumps(report, indent=2) + "\n")
    protocol = {
        "exploratory": True,
        "official_profile_frozen": False,
        "calibration_found_feasible_candidate": None,
        "scope": {"load": "L2", "aggregation": "A1", "seed": 41,
                  "warmup_s": 1, "measurement_s": 30, "drain_s": 0.05,
                  "additional_seeds_if_feasible": [43, 47]},
        "fixed_workload": ["same canonical flow sizes/rates/offsets", "same 64 KiB camera talker queues",
                           "same 128 KiB G1-G4 queues", "same 32 KiB other queues",
                           "same VLANs/destinations/static routes", "no frame preemption",
                           "FIFO within each TC", "TC7>TC6>TC5>TC4>TC3>TC2>TC1>TC0 strict priority"],
        "mapping_changed_flow_ids": sorted(VARIANT_IDS),
        "calendar_pairing": {"generation": "TrafficPlan creates the complete F21/F22 event list at initialization, before the event loop, on dedicated RNG streams 0 and 1.",
                             "verification": "Save the first events.csv as the seed calendar and require byte-identical canonical event rows/SHA-256 for every treatment at that seed. Same seed without the signature check is insufficient.",
                             "event_signature_fields": ["flow", "block", "signature", "start", "duration", "volume_bytes"]},
        "controls": ["C2 original mapping seed41", "C2 variant nominal seed41",
                     "C0 variant seed41", "C1 variant seed41"],
        "search": {
            "nominal_first": True,
            "candidate_budget_max": 24,
            "reduction_budget_after_first_viable_max": 12,
            "coarse_increment_fraction_of_port_rate_max": 0.10,
            "fine_increment_fraction_of_port_rate": 0.02,
            "never_below_permanent_nominal": True,
            "per_port_total_reservation_cap_fraction": 0.75,
            "targets": {
                "TC6_sensor_paths": {
                    "F01": ["LiDAR1.eth[0]/TC6", "Z1.ZSW.eth[0]/TC6", "CSW.eth[0]/TC6", "HPC.eth[0]/TC6"],
                    "F06": ["RADAR1.eth[0]/TC6", "Z2.ZSW.eth[0]/TC6", "CSW.eth[0]/TC6", "HPC.eth[0]/TC6"],
                    "F07": ["RADAR2.eth[0]/TC6", "Z3.ZSW.eth[0]/TC6", "CSW.eth[0]/TC6", "HPC.eth[0]/TC6"]},
                "TC4_flows": {f["flow_id"]: sorted({f"{p}/{4}" for dst in f["destinations"].split(";")
                                                      for p in set(__import__("generate_cbs").route(f["source"], dst))})
                              for f in variant if int(f["traffic_class"]) == 4 and f["family"] != "transient"},
                "priority_order": "Within still-failing paths, sort by measured queueingTime.max descending, then mean descending, then fixed source-to-destination route order and egress name.",
            },
            "candidate_schedule": [
                "Candidates 1-12: one deterministic +up-to-10%-of-port-rate coordinate step at a time, keeping prior increments and choosing from egress/TC targets on currently failing flows by the registered measured-wait order.",
                "Candidates 13-18: coupled +up-to-10%-of-port-rate steps on all eligible TC/egress queues along one currently failing flow path, ordered by the same wait/routing rule.",
                "Candidates 19-24: deterministic backtracking from the best prior nonviable candidate (fewest high-hard misses, then all-flow deadline misses, confirmed drops, worst queue wait, then earlier candidate index), reducing one adjusted target by 2% of its port rate while retaining the other coupled settings; never below nominal.",
                "If any candidate is viable, stop the viability search and perform at most 12 reductions by 2% of port rate, in descending excess-over-nominal then measured-wait order; keep only candidates passing every P1 gate.",
                "Reject before simulation and record any candidate that would exceed 75% total CBS on any egress; if no positive increment remains, do not run it."],
            "failure_wording": "If no candidate among the defined search is viable, report 'nenhum candidato viável encontrado pela busca exploratória definida'; do not infer general impossibility.",
            "viability": "All P1 hard/soft deadline, packet loss, received-delivery/goodput and stable-queue criteria; no p99-only acceptance."},
        "temporal_evidence": {"resolution_s": 0.001,
                              "sensor_latency": "per-packet receiver latency vectors; misses binned by event/creation time",
                              "camera": "image release times and imageCompletionLatency; active release span marked separately",
                              "transients": "F21/F22 event intervals from identical calendar",
                              "queue_traces": "1 ms occupancy summaries on HPC, CSW.eth[0], Z1/Z2/Z3 uplinks and affected talker ports",
                              "interpretation": "temporal association only; no packet-level causal attribution without per-packet route tracing"},
        "retention": {"keep": ["pilot configs", "catalog copies", "F21/F22 calendars", "candidate history", "compact per-flow/queue summaries", "1 ms temporal association CSVs"],
                      "raw_cleanup": "Only after a successful compact and temporal extraction; retain no multi-GB raw vectors by default."},
    }
    (HERE / "search_protocol.json").write_text(json.dumps(protocol, indent=2) + "\n")
    markdown = ["# Piloto isolado de reclassificação PCP/TC", "",
                "Este arquivo e os INIs, catálogos, reservas, históricos e resultados abaixo pertencem somente ao piloto. O P1 e as configurações oficiais não foram alterados por esta geração.", "",
                "| Fluxo | VLAN | Original PCP→TC | Mecanismo original | Variante PCP→TC | Mecanismo na variante |", "|---|---:|---:|---|---:|---|"]
    for r in rows:
        markdown.append(f"| {r['flow_id']} {r['source']}→{r['destinations']} | {r['vlan']} | {r['original_pcp']}→{r['original_tc']} | {r['original_mechanism']} | {r['variant_pcp']}→{r['variant_tc']} | {r['variant_mechanism']} |")
    markdown += ["", "## Divergências resolvidas", "",
                 "O catálogo confirmou que F02/F03 e F11–F13 eram PCP6/TC6, enquanto a proposta os coloca em TC4; F21/F22 também eram PCP6/TC6 e passam a TC4. F04/F05 e F14 já eram PCP4/TC4. F01/F06/F07 já eram PCP6/TC6. A variante troca PCP para 4 nos sete fluxos divergentes; a classificação permanece identidade PCPn→TCn. VLAN, encaminhamento, destino, tamanho e calendário não mudam.", "",
                 "A tabela deve ser lida por tratamento: C0 usa SP; C1 usa SP e aplica pre-shaping somente às câmeras; C2 usa CBS nominal em TC4/TC6 com SP nas demais TCs. O algoritmo, a ordem dos alvos, os limites e o calendário estão em `search_protocol.json`.", "",
                 "## Reservas nominais L2", "",
                 "Os CSVs `configs/cbs_original_nominal.csv` e `configs/cbs_variant_nominal.csv` contêm cada porta/TC, fluxos permanentes roteados, `R_wire`, soma por porta e margem ao teto de 75%. Transientes F21/F22 não entram nas somas.", ""]
    (HERE / "pilot_protocol.md").write_text("\n".join(markdown))
    print(f"Generated isolated mapping for {len(rows)} flows; changed PCP/TC on {len(VARIANT_IDS)} IDs")
    print(f"L2 CBS reservation entries: original={len(orig_rates)}, variant={len(variant_rates)}")


if __name__ == "__main__":
    main()
