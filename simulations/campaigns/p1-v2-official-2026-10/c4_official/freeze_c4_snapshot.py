#!/usr/bin/env python3
"""Create the hash-pinned C4 manifest and 180-position calendar matrix.

This is a metadata-only command. It never invokes OMNeT++ or any simulator.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
SIM = ROOT / "simulations"
OUT = HERE / "results/C4"
INDEX = ROOT / "simulations/campaigns/p1-v2-official-2026-10/results/calendars/calendar_index.json"
RUNS = ROOT / "simulations/campaigns/p1-v2-official-2026-10/results/runs.jsonl"
CHECKPOINT = ROOT / "simulations/campaigns/p1-v2-official-2026-10/results/checkpoint.json"
PROFILE = ROOT / "simulations/c4_official/frozen_d3_l2_profile.json"
PROFILE_CSV = ROOT / "simulations/c4_official/frozen_profile_table.csv"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run_git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def json_write(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def relevant_files(calendar_paths: set[Path]) -> set[Path]:
    paths = {
        ROOT / "docs/design/P1-final.pdf",
        ROOT / "simulations/omnetpp.ini",
        ROOT / "src/zonal-ivn-tsn",
        ROOT / "simulations/c4_official/frozen_d3_l2_profile.json",
        ROOT / "simulations/c4_official/frozen_profile_table.csv",
        ROOT / "simulations/c4_official/C4_D3_absolute_profile.ini",
        ROOT / "simulations/c4_official/C4Instrumented.ned",
        ROOT / "simulations/c4_official/ClockPrecisionProbe.ned",
        ROOT / "simulations/c4_official/RealClockTraceProbe.ned",
        ROOT / "simulations/c4_official/validate_c4_contract.py",
        ROOT / "simulations/c4_official/C4_operational_freeze_addendum.md",
        ROOT / "simulations/c4_official/.gitignore",
        ROOT / "simulations/c4_official/plugin/ClockPrecisionProbe.cc",
        ROOT / "simulations/c4_official/plugin/RealClockTraceProbe.cc",
        ROOT / "simulations/c4_official/plugin/Makefile",
        ROOT / "simulations/c4_official/plugin/libc4realclockprobe.so",
        ROOT / "simulations/campaigns/p1-v2-official-2026-10/c4_official/run_c4_campaign.py",
        ROOT / "simulations/campaigns/p1-v2-official-2026-10/c4_official/c4_official.ini",
        ROOT / "simulations/campaigns/p1-v2-official-2026-10/c4_official/freeze_c4_snapshot.py",
        ROOT / "simulations/campaigns/p1-v2-official-2026-10/c4_official/c4_status.py",
        ROOT / "simulations/campaigns/p1-v2-official-2026-10/c4_official/matrix.csv",
        ROOT / "simulations/campaigns/p1-v2-official-2026-10/c4_official/README.md",
        ROOT / "simulations/campaigns/p1-v2-official-2026-10/c4_official/.gitignore",
        ROOT / "simulations/campaigns/p1-v2-official-2026-10/run_official_campaign.py",
        ROOT / "simulations/campaigns/p1-v2-official-2026-10/prepare_parallel_campaign.py",
        ROOT / "simulations/campaigns/p1-v2-official-2026-10/merge_campaign_shards.py",
        ROOT / "simulations/campaigns/p1-v2-official-2026-10/campaign_status.py",
        ROOT / "simulations/README.md",
        ROOT / "simulations/campaigns/p1-v2-official-2026-10/run_campaign.py",
        ROOT / "simulations/campaigns/p1-v2-official-2026-10/calibration_protocol.json",
        ROOT / "simulations/pilot/c4_feasibility_decision/results/final_results_2026-10-20.json",
        ROOT / "simulations/pilot/c4_feasibility_decision/conditional_phase_preregistration_2026-10-20.md",
        ROOT / "simulations/pilot/c4_final_verification/results/reconciliation_2026-10-22.json",
        ROOT / "simulations/pilot/c4_final_verification/triage.json",
        ROOT / "simulations/pilot/c4_final_verification/protocol.md",
        ROOT / "simulations/pilot/c4_final_verification/frozen_d3_l2_profile.json",
        ROOT / "simulations/pilot/c4_final_verification/frozen_profile_table.csv",
        ROOT / "simulations/pilot/c4_fixed_L2_profile/results/frozen_d3_l2_profile.json",
        ROOT / "simulations/pilot/c4_fixed_L2_profile/results/frozen_profile_table.csv",
        ROOT / "simulations/pilot/c4_real_clock_service_margin/results/technical/network_name_smoke/Pilot_C4compensated_L2_A1-#0.sca",
        ROOT / "simulations/zonal/networks/ZonalIVN.ned",
        ROOT / "simulations/zonal/configs/base.ini",
        ROOT / "simulations/zonal/configs/topology.ini",
        ROOT / "simulations/zonal/configs/traffic.ini",
        ROOT / "simulations/zonal/configs/loads.ini",
        ROOT / "simulations/zonal/configs/aggregation.ini",
        ROOT / "simulations/zonal/configs/classification.ini",
        ROOT / "simulations/zonal/configs/synchronization.ini",
        ROOT / "simulations/zonal/configs/catalog-bindings.ini",
        ROOT / "simulations/zonal/configs/mechanisms/C2_nominal_cbs.ini",
        ROOT / "simulations/zonal/configs/mechanisms/C3_calibrated_cbs.ini",
        ROOT / "simulations/zonal/traffic/flows.csv",
        ROOT / "simulations/zonal/traffic/transients.csv",
        ROOT / "scripts/run/validate_c0.py",
        ROOT / "scripts/catalog/generate.py",
    }
    # These registries are mutable as C0-C3 final treatments run. C4 pins the
    # immutable calendar files and each matrix row's signature/event count;
    # campaign state at freeze remains provenance metadata below. Hashing the
    # registries here would invalidate the frozen C4 snapshot during normal
    # C0-C3 progress even when every paired calendar is unchanged.
    paths.update(calendar_paths)
    # Include all source inputs and NED declarations used to resolve the model.
    for folder, suffixes in ((ROOT / "src", {".cc", ".h", ".ned", ".msg", ".sm"}),
                             (ROOT / "simulations/zonal", {".ned", ".ini", ".csv", ".xml"}),
                             (ROOT / "tests/validation/traffic", {".py", ".json", ".csv"})):
        paths.update(p for p in folder.rglob("*") if p.is_file() and p.suffix in suffixes)
    missing = sorted(str(p.relative_to(ROOT)) for p in paths if not p.is_file())
    if missing:
        raise SystemExit("Cannot freeze C4; required inputs missing:\n  " + "\n  ".join(missing))
    return paths


def main() -> None:
    frozen = json.loads(PROFILE.read_text())
    if frozen["canonical_sha256"] != "571e3a10e004005b2994aadc6dc495db730f6e9b8842af2550ebcbb3d6eb33be":
        raise SystemExit("Frozen D3 candidate does not match the selected exploratory profile")
    calendar_index = json.loads(INDEX.read_text())
    rows, calendar_paths = [], set()
    for load in ("L0", "L1", "L2"):
        for alignment in ("A0", "A1"):
            for seed in range(1001, 1031):
                key = f"{load}/{alignment}/seed{seed}"
                entry = calendar_index.get(key)
                if not entry:
                    raise SystemExit(f"Missing paired transient calendar {key}")
                calendar = ROOT / "simulations/campaigns/p1-v2-official-2026-10" / entry["file"]
                calendar_paths.add(calendar)
                rows.append({"treatment": "C4", "load": load, "alignment": alignment,
                             "seed": seed, "execution_id": f"C4_{load}_{alignment}_seed{seed}",
                             "status": "planned", "calendar_key": key,
                             "calendar_file": str(calendar.relative_to(SIM)),
                             "calendar_signature": entry["sha256"],
                             "calendar_event_count": int(entry["event_count"]),
                             "calendar_file_sha256": sha(calendar)})
    matrix_path = HERE / "matrix.csv"
    with matrix_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    run_rows = [json.loads(line) for line in RUNS.read_text().splitlines() if line.strip()]
    final = [r for r in run_rows if r.get("stage") == "final"]
    by_treatment = {}
    for treatment in ("C0", "C1", "C2", "C3"):
        entries = [r for r in final if r.get("treatment") == treatment]
        observed_ids = {r.get("execution_id") for r in entries}
        loads = range(3) if treatment == "C3" else range(4)
        expected_ids = {f"{treatment}_L{load}_A{alignment}_seed{seed}"
                        for load in loads for alignment in (0, 1) for seed in range(1001, 1031)}
        unexpected_ids = sorted(observed_ids - expected_ids)
        if unexpected_ids:
            raise SystemExit(f"Unexpected final {treatment} ledger positions: {unexpected_ids[:5]}")
        ids = observed_ids & expected_ids
        by_treatment[treatment] = {"valid_ledger_records": len(ids), "unique_positions": len(ids),
                                   "completed_positions": len(ids),
                                   "expected_positions": 240 if treatment != "C3" else 180,
                                   "pending_positions": max(0, (240 if treatment != "C3" else 180) - len(ids)),
                                   "pending_execution_ids": sorted(expected_ids - ids)}
    cp = json.loads(CHECKPOINT.read_text())
    pilot_decision = json.loads((ROOT / "simulations/pilot/c4_feasibility_decision/results/final_results_2026-10-20.json").read_text())
    reconciliation = json.loads((ROOT / "simulations/pilot/c4_final_verification/results/reconciliation_2026-10-22.json").read_text())
    triage = json.loads((ROOT / "simulations/pilot/c4_final_verification/triage.json").read_text())
    source_profiles = [json.loads((ROOT / p).read_text()) for p in (
        "simulations/pilot/c4_final_verification/frozen_d3_l2_profile.json",
        "simulations/pilot/c4_fixed_L2_profile/results/frozen_d3_l2_profile.json")]
    if any(p.get("canonical_sha256") != frozen["canonical_sha256"] or
           p.get("effective_profile_bps") != frozen["effective_profile_bps"] for p in source_profiles):
        raise SystemExit("C4 implementation profile differs from the pilot frozen profile")
    selected = pilot_decision["candidate_selection_record"]
    d3 = pilot_decision["preregistered_candidate_designs"]["D3"]
    if selected.get("selected_profile_id") != "D3_coordinated_20pct" or d3.get("profile_bps") != frozen["effective_profile_bps"]:
        raise SystemExit("The selected feasibility candidate is not the frozen D3 profile")
    if set(d3.get("GCL", {})) != {"HPC.eth[0]", "CSW.eth[1]", "CSW.eth[2]", "CSW.eth[3]"}:
        raise SystemExit("Selected D3 GCL does not cover exactly the four shared egresses")

    paths = relevant_files(calendar_paths)
    file_hashes = {str(p.relative_to(ROOT)): sha(p) for p in sorted(paths)}
    inet_value = os.environ.get("INET_ROOT", "/home/jonatan/omnetpp/samples/inet-4.7.0")
    omnet_value = os.environ.get("OMNETPP_ROOT")
    if omnet_value:
        omnet_root = Path(omnet_value)
    else:
        opp_run = shutil.which("opp_run")
        if not opp_run:
            raise SystemExit("Set OMNETPP_ROOT or put opp_run on PATH before freezing C4")
        omnet_root = Path(opp_run).resolve().parent.parent
    inet_root = Path(inet_value).resolve()
    external_paths = {
        "@INET_ROOT/src/libINET.so": inet_root / "src/libINET.so",
        "@INET_ROOT/src/inet/linklayer/ieee8021q/Ieee8021qCreditBasedShaper.ned": inet_root / "src/inet/linklayer/ieee8021q/Ieee8021qCreditBasedShaper.ned",
        "@INET_ROOT/src/inet/linklayer/ieee8021q/Ieee8021qCreditBasedGate.ned": inet_root / "src/inet/linklayer/ieee8021q/Ieee8021qCreditBasedGate.ned",
        "@INET_ROOT/src/inet/queueing/gate/CreditBasedGate.cc": inet_root / "src/inet/queueing/gate/CreditBasedGate.cc",
        "@INET_ROOT/src/inet/queueing/gate/CreditBasedGate.h": inet_root / "src/inet/queueing/gate/CreditBasedGate.h",
        "@INET_ROOT/src/inet/queueing/gate/PeriodicGate.cc": inet_root / "src/inet/queueing/gate/PeriodicGate.cc",
        "@INET_ROOT/src/inet/queueing/gate/PeriodicGate.h": inet_root / "src/inet/queueing/gate/PeriodicGate.h",
        "@OMNETPP_ROOT/lib/liboppsim.so": omnet_root / "lib/liboppsim.so",
        "@OMNETPP_ROOT/bin/opp_run": omnet_root / "bin/opp_run",
    }
    missing_external = [f"{key} -> {path}" for key, path in external_paths.items() if not path.is_file()]
    if missing_external:
        raise SystemExit("Cannot freeze C4 without runtime sources/libraries: " + ", ".join(missing_external))
    external_hashes = {key: sha(path) for key, path in external_paths.items()}
    with PROFILE_CSV.open(newline="", encoding="utf-8") as stream:
        profile_parameters = list(csv.DictReader(stream))
    matrix_hash = sha(matrix_path)
    all_hashes = file_hashes | external_hashes
    matrix_canonical = hashlib.sha256("\n".join(f"{k} {all_hashes[k]}" for k in sorted(all_hashes)).encode()).hexdigest()
    snapshot_id = "c4-d3-" + matrix_canonical[:16]
    status = {"campaign_id": "p1-v2-official-2026-10", "checkpoint_status_at_freeze": cp.get("status"),
              "active_process": cp.get("active_process"), "campaign_active": False,
              "final_positions": by_treatment, "c0_c3_final_completed": sum(x["completed_positions"] for x in by_treatment.values()),
              "c0_c3_final_pending": sum(x["pending_positions"] for x in by_treatment.values()),
              "c2_calibration_records_not_final": sum(1 for r in run_rows if r.get("stage") == "calibration" and r.get("treatment") == "C2"),
              "C3_L3_positions": {"status": "inadmissible_not_simulated", "positions": 60},
              "ledger_file_sha256_at_freeze": sha(RUNS), "checkpoint_file_sha256_at_freeze": sha(CHECKPOINT),
              "campaign_manifest_sha256": sha(ROOT / "simulations/campaigns/p1-v2-official-2026-10/campaign_manifest.json")}
    if status["c0_c3_final_completed"] != 240 or status["c0_c3_final_pending"] != 660:
        raise SystemExit(f"Unexpected C0-C3 official state: {status}")
    manifest = {
        "schema_version": "1.0", "campaign_id": "p1-v2-official-2026-10-C4",
        "snapshot_id": snapshot_id, "snapshot_sha256": matrix_canonical,
        "snapshot_created_local": "2026-10-22", "base_commit": run_git("rev-parse", "HEAD"),
        "working_tree_clean": False, "working_tree_status_at_freeze": run_git("status", "--short"),
        "exploratory": False, "official_c4_frozen": True, "official_c4_validated": False,
        "campaign_started": False, "simulation_started_by_freeze_step": False,
        "selected_candidate": "D3_coordinated_20pct",
        "selected_exploratory_execution": "D3_TAS_L2_A1_seed41",
        "profile_sha256": frozen["canonical_sha256"], "profile_rows": 24,
        "profile_parameters": profile_parameters,
        "profile_provenance_equivalence": {"selected_candidate_id": selected["selected_profile_id"],
            "selected_candidate_profile_matches_frozen": True,
            "final_verification_profile_sha256": source_profiles[0]["canonical_sha256"],
            "c4_fixed_l2_profile_sha256": source_profiles[1]["canonical_sha256"],
            "profile_tables_identical_sha256": sha(ROOT / "simulations/pilot/c4_final_verification/frozen_profile_table.csv"),
            "selected_candidate_gcl_egresses": sorted(d3["GCL"])},
        "profile_csv_sha256": sha(PROFILE_CSV), "profile_ini_sha256": sha(ROOT / "simulations/c4_official/C4_D3_absolute_profile.ini"),
        "gcl": frozen["gcl"], "gcl_candidate_design_details": d3["GCL"], "pilot_provenance": {
            "candidate_decision": "simulations/pilot/c4_feasibility_decision/results/final_results_2026-10-20.json",
            "candidate_decision_sha256": sha(ROOT / "simulations/pilot/c4_feasibility_decision/results/final_results_2026-10-20.json"),
            "candidate_reconciliation": "simulations/pilot/c4_final_verification/results/reconciliation_2026-10-22.json",
            "candidate_reconciliation_sha256": sha(ROOT / "simulations/pilot/c4_final_verification/results/reconciliation_2026-10-22.json"),
            "coverage": reconciliation["coverage"], "gate_summary": reconciliation["gate_summary"],
            "exploratory_final_candidate_assessment": pilot_decision["candidate_selection_record"]["candidate_assessment"]["D3"],
            "L3_triage": triage["L3"]},
        "runtime_versions": {"omnetpp": "omnetpp-6.4.0", "inet": "inet-4.7.0-dfe270b21f",
                              "executable_sha256": sha(ROOT / "src/zonal-ivn-tsn"),
                              "inet_library_sha256": sha(Path("/home/jonatan/omnetpp/samples/inet-4.7.0/src/libINET.so")) if Path("/home/jonatan/omnetpp/samples/inet-4.7.0/src/libINET.so").is_file() else None,
                              "probe_plugin_sha256": sha(ROOT / "simulations/c4_official/plugin/libc4realclockprobe.so")},
        "matrix": {"path": "simulations/campaigns/p1-v2-official-2026-10/c4_official/matrix.csv",
                   "positions": len(rows), "sha256": matrix_hash,
                   "loads": ["L0", "L1", "L2"], "alignments": ["A0", "A1"],
                   "seeds": list(range(1001, 1031)), "treatments": ["C4"],
                   "warmup_s": 1, "measurement_window_s": [1, 31], "drain_s": 0.05,
                   "paired_calendar_source": "current official C0 campaign calendars, keyed by load/alignment/seed",
                   "L3": {"status": "rejected_by_triage_not_simulated", "positions": 60,
                          "reason": "fixed-profile service upper bound at CSW.eth[0] (539.16 Mb/s) is below L3 permanent demand (862.656 Mb/s); not a reservation-cap rejection"}},
        "triage": {"L3": triage["L3"], "L0_L2": triage["L0_L2"],
                   "all_port_reservation_caps_pass": triage["all_port_reservation_caps_pass"]},
        "buffers": {"camera_talker_queues": {"bytes": 65536, "bits": 524288},
                    "CSW_and_switch_bottleneck_queues": {"bytes": 131072, "bits": 1048576},
                    "other_queues": {"bytes": 32768, "bits": 262144},
                    "runtime_source": "P1-final plus effective SCA checks in scripts/run/validate_c0.py"},
        "c0_c3_state_at_freeze": status,
        "input_file_hashes": file_hashes,
        "external_file_hashes": external_hashes,
        "storage_policy": {"min_free_gib_before_and_during_run": 40, "jobs": 1,
                           "retain_exact_queue_change_points_in_lossless_delta_varint_format": True,
                           "retain_exact_packet_image_quantile_tails_and_native_clock_samples": True,
                           "retain_exact_credit_gate_guard_band_and_gptp_vectors_only": True,
                           "drop_full_vectors_only_after_filtered_evidence_and_all_gates_reconcile": True,
                           "never_delete_historical_pilot_or_C0_C3_results": True},
        "operational_contract": {"C4_open_in_official_matrix": False,
                                 "C4_minus_C3_interpretation": "complete policy comparison; not an isolated TAS contrast",
                                 "P1_reference_difference": "D3 absolute 24-reservation profile; TAS on four shared egresses only; SP on three real brake last hops; 55us TC0-6 and 30us TC7 windows in a 100us cycle with coordinated offsets",
                                 "clock_drift_method": "For each seed and node, SHA256('p1-v2-official-2026-10:C4:ConstantDriftOscillator:{seed}:{node}'), first 64 bits as unsigned integer u, drift=-50+100*u/(2^64-1) ppm; fixed per execution and independent of traffic RNG streams",
                                 "admissibility": "L0-L2 fixed-profile triage accepted; L3 rejected before simulation because CSW.eth[0] service upper bound 539.16 Mb/s < 862.656 Mb/s permanent demand; no clipping",
                                 "evaluation": "Apply current P1 flow/application/image/loss/goodput/deadline and queue-stability gates; report technical validity, GCL, sampled sync and continuous-sync status separately; do not retune on failure",
                                 "retries": "Only technically invalid executions may receive one audited replacement at the same seed; valid performance failures are retained and never replaced",
                                 "runtime_checks_pending_first_manual_run": ["effective SCA CBS/GCL/clock/buffer values",
                                    "observed gate states/guard bands", "calendar event and population signature",
                                    "native tick clock probe and sampled synchronization", "application/stability gates"],
                                 "continuous_clock_conformity": "not verified by sampled audit"}}
    OUT.mkdir(parents=True, exist_ok=True)
    if (OUT / "ledger.jsonl").exists() and (OUT / "ledger.jsonl").stat().st_size:
        raise SystemExit("C4 ledger already exists; freeze script will not replace existing campaign state")
    json_write(HERE / "manifest.json", manifest)
    template = {"campaign_id": manifest["campaign_id"], "status": "frozen_not_started",
                    "phase": "preflight_pending", "active": None, "completed": 0, "expected": len(rows),
                    "snapshot_id": snapshot_id, "official_c4_validated": False,
                    "updated_local": "2026-10-22"}
    json_write(HERE / "checkpoint_template.json", template)
    compact_state = {k: {"completed": v["completed_positions"], "pending": v["pending_positions"]}
                     for k, v in status["final_positions"].items()}
    print(json.dumps({"status": "frozen_metadata_created", "simulation_started": False,
                      "snapshot_id": snapshot_id, "positions": len(rows), "matrix_sha256": matrix_hash,
                      "C0_C3_final_positions": compact_state,
                      "C2_calibration_records_separate": status["c2_calibration_records_not_final"],
                      "C3_L3_positions_rejected": 60}, indent=2))


if __name__ == "__main__":
    main()
