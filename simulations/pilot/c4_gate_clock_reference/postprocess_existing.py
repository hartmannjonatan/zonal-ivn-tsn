#!/usr/bin/env python3
"""Finish compact extraction from already-completed raw vectors only."""
import importlib.util, json, sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("gate_clock_runner_for_extraction",HERE/"run_diagnostic.py")
runner=importlib.util.module_from_spec(spec);sys.modules[spec.name]=runner;spec.loader.exec_module(runner)
OUT=HERE/"results"
OLD=HERE.parents[1]/"c4_cbs_tas_investigation/results/runs/A005_L2_A1_seed41/pilot-result.json"
reference=json.loads(OLD.read_text())
variants=("A005_local","A005_ideal_all","A005_ideal_HPC")
ledger_path=OUT/"runs.jsonl"
ledger=[json.loads(x) for x in ledger_path.read_text().splitlines() if x.strip()] if ledger_path.exists() else []
for variant in variants:
    execution=f"{variant}_L2_A1_seed41_v1"
    dest=OUT/"runs"/execution
    config="Pilot_C4compensated_L2_A1"
    run_dir=dest/f"{config}-0"
    report_path=dest/"pilot-result.json"
    row=json.loads(report_path.read_text())
    if row.get("effective_profile_bps")!=reference.get("effective_profile_bps"):
        raise RuntimeError(f"{execution}: effective profile differs from saved A005 rates")
    if row.get("calendar_sha256")!="cb74a68801e037dce0480422e4371150c2c95765974b0ef3857f1633b54a600d" or row.get("calendar_paired") is not True:
        raise RuntimeError(f"{execution}: F21/F22 calendar was not paired")
    if not row.get("event_order_extraction",{}).get("status")=="complete":
        meta=runner.extract_event_records(dest,config,run_dir,variant)
        row["event_order_extraction"]=meta
    row["diagnostic_variant"]=variant
    row["gate_clock_reference"]={"ideal_simtime_egresses":sorted(runner.VARIANT_CLOCKS[variant]),
        "local_clock_egresses":sorted(set(runner.TARGET_EGRESSES)-runner.VARIANT_CLOCKS[variant]),
        "other_clocks_unchanged":True}
    row["retained_raw_vector"]=False
    row["raw_vector_retention_reason"]="The complete compact event-order trace was verified; SCA, logs, traffic traces and validator metrics are retained."
    report_path.write_text(json.dumps(row,indent=2,ensure_ascii=False)+"\n")
    ledger=[row if x.get("execution_id")==execution else x for x in ledger]
ledger_path.write_text("".join(json.dumps(x,separators=(",",":"),ensure_ascii=False)+"\n" for x in ledger))
print("Compacted event-order vectors for completed runs only; no simulation was started.")
