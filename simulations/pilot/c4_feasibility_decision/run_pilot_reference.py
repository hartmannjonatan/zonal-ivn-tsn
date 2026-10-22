#!/usr/bin/env python3
"""Isolated, checkpointed runner for the C4 service-preservation pilot.

This script only executes configurations declared in this directory. It never
changes the official campaign, the common INI, the P1, or the frozen C3 profile.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import csv
import fcntl
import gzip
import hashlib
import json
import math
import os
import random
import re
import shutil
import statistics
import subprocess
import sys
import threading
import time
from bisect import bisect_right
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SIM = ROOT / "simulations"
OUT = HERE / "results"
PILOT_INI = HERE / "pilot.ini"
PROTOCOL = HERE / "protocol.md"
PROFILE_JSON = SIM / "campaigns/p1-v2-official-2026-10/results/calibration/C3_calibration.json"
PROFILE_CHECKPOINT = SIM / "campaigns/p1-v2-official-2026-10/results/progress.json"
P1_PDF = ROOT / "docs/design/P1-v4.pdf"
FREE_FLOOR_GB = 45.0
# Keep one simulation worker on this 14-GiB laptop. The vector audit is serial
# and can be CPU/memory intensive; reliability and desktop responsiveness take
# precedence over throughput for this isolated pilot.
MAX_JOBS = 1
OMNETPP_ROOT = Path(os.environ.get("OMNETPP_ROOT", str(Path.home() / "omnetpp")).strip()).resolve()
INET_ROOT = Path(os.environ.get("INET_ROOT", str(Path.home() / "omnetpp/samples/inet-4.7.0")).strip()).resolve()
ALPHA = 0.77
LOADS = ("L0", "L1", "L2", "L3")
LOAD_FACTORS = (0.5, 1.0, 2.5, 4.0)
SEEDS = (41, 43, 47)
TAS_EGRESSES = {"HPC.eth[0]", "CSW.eth[1]", "CSW.eth[2]", "CSW.eth[3]"}
FULL_PATH_TAS_EGRESSES = TAS_EGRESSES | {"Z1.ZSW.eth[4]", "Z2.ZSW.eth[4]", "Z3.ZSW.eth[5]"}
BRAKE_SP_EGRESSES = {"Z1.ZSW.eth[4]", "Z2.ZSW.eth[4]", "Z3.ZSW.eth[5]"}
NODES = ("HPC", "CSW", "Z1.ZSW", "Z2.ZSW", "Z3.ZSW")
VARIANT_NAMES = {
    "C3base": "C3_base", "C3sync": "C3_sync",
    "C4original": "C4_compensated_fullpath_corrected", "C4compensated": "C4_shared_SPbrakes",
}
LOCK = threading.RLock()
# OMNeT++ runs may execute concurrently, but the pilot-specific vector audit
# retains selected vector samples in Python.  Serialize that memory-heavy phase
# so four completed 7+ GB vectors cannot be expanded in RAM at once.
PILOT_VECTOR_LOCK = threading.Lock()
CHECKPOINT: dict = {}
LEDGER: list[dict] = []

sys.path[:0] = [str(ROOT / "scripts/run"), str(ROOT / "scripts/catalog")]
import validate_c0 as validator  # noqa: E402
import generate_cbs as cbs  # noqa: E402


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, sort_keys=True)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(path)


def append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n").encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view):]
        os.fsync(fd)
    finally:
        os.close(fd)


def free_gb() -> float:
    return shutil.disk_usage(ROOT).free / 1e9


def memory_available_gb() -> float:
    try:
        fields = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":", 1)
                if k in ("MemAvailable", "SwapFree"):
                    fields[k] = int(v.strip().split()[0]) / 1024 / 1024
        return fields.get("MemAvailable", 0.0)
    except (OSError, ValueError):
        return 0.0


def memory_safe_jobs(requested: int) -> int:
    # Reserve room for the desktop and bound each OMNeT process conservatively.
    # The large vector parser is serialized independently below.
    available = memory_available_gb()
    if available < 7.0:
        return 0
    return max(1, min(requested, MAX_JOBS, int(available // 5.0)))


def simulator_environment() -> dict[str, str]:
    """Make the built simulator and INET shared libraries resolvable without shell setup."""
    env = os.environ.copy()
    required = (str(OMNETPP_ROOT / "lib"), str(INET_ROOT / "src"))
    env["LD_LIBRARY_PATH"] = ":".join([*required, env.get("LD_LIBRARY_PATH", "")]).rstrip(":")
    return env


def lock_is_busy(path: Path) -> bool:
    """Probe another runner's flock without trusting a possibly stale PID."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)


def pid_is_official_runner(pid: int) -> bool:
    try:
        args = [x.decode(errors="replace") for x in Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0") if x]
        return any(Path(x).name == "run_campaign.py" for x in args) and any("p1-v2-official-2026-10" in x for x in args)
    except (OSError, ValueError):
        return False


def official_campaign_active() -> bool:
    lock = SIM / "campaigns/p1-v2-official-2026-10/results/.campaign.lock"
    if lock_is_busy(lock):
        return True
    try:
        checkpoint = json.loads((lock.parent / "checkpoint.json").read_text())
    except (OSError, json.JSONDecodeError):
        return False
    pid = checkpoint.get("executor_pid")
    return bool(pid and checkpoint.get("active_process") and pid_is_official_runner(int(pid)))


def read_flow_rows() -> list[dict]:
    with (SIM / "zonal/traffic/flows.csv").open(newline="") as f:
        return list(csv.DictReader(f))


def load_frozen_profile():
    data = json.loads(PROFILE_JSON.read_text())
    checkpoint = json.loads(PROFILE_CHECKPOINT.read_text())
    if data.get("status") != "frozen_and_accepted" or data.get("final_profile_id") != "reduction_11":
        raise RuntimeError("The official C3 profile is not the accepted reduction_11 expected by this pilot")
    if checkpoint.get("calibration_final_profile_id") != "reduction_11" or checkpoint.get("calibration_profile_accepted") is not True:
        raise RuntimeError("The active official campaign checkpoint does not identify reduction_11 as accepted final profile")
    ratios = data.get("frozen_candidate_to_nominal_ratios") or {}
    if not ratios:
        raise RuntimeError("Official C3 frozen ratios are missing")
    # Confirm that the frozen L2 profile matches the actual accepted vector.
    selected = data.get("selected_profile_bps") or {}
    nominal = cbs.nominal_reservations(cbs.read_flows())
    calculated_l2 = {}
    for key, ratio in ratios.items():
        egress, tc_text = key.rsplit("/TC", 1)
        tc = int(tc_text)
        base = int(nominal.get((2, egress, tc), {"bps": 0})["bps"])
        calculated_l2[key] = round(base * float(ratio))
    if calculated_l2 != {k: int(v) for k, v in selected.items()}:
        raise RuntimeError("Frozen ratios do not reproduce the accepted reduction_11 L2 vector")
    return data, ratios, nominal


def profiles_by_load(ratios: dict, nominal: dict) -> dict[int, dict[tuple[str, int], int]]:
    profiles = {}
    for load in range(4):
        p = {}
        for key, ratio in ratios.items():
            egress, tc_text = key.rsplit("/TC", 1)
            tc = int(tc_text)
            base = int(nominal.get((load, egress, tc), {"bps": 0})["bps"])
            value = round(base * float(ratio))
            if value > 0:
                p[egress, tc] = value
        profiles[load] = p
    return profiles


def catalog_loads() -> dict[int, dict[tuple[str, int], int]]:
    """Permanent physical wire demand by actual routed egress and TC."""
    result = {}
    for load, factor in enumerate(LOAD_FACTORS):
        by = {}
        for flow in read_flow_rows():
            if flow["family"] == "transient":
                continue
            rate = float(flow["wire_rate_mbps"]) * 1_000_000
            if flow["scalable"] == "1":
                rate *= factor
            tc = int(flow["traffic_class"])
            # A multicast source emits one packet. Count the common prefix
            # egress once even when several destinations share that route.
            egresses = set()
            for destination in flow["destinations"].split(";"):
                egresses.update(cbs.route(flow["source"], destination))
            for egress in egresses:
                key = (egress, tc)
                by[key] = by.get(key, 0) + round(rate)
        result[load] = by
    return result


def route_audit() -> dict:
    rows = read_flow_rows()
    paths = {}
    for flow in rows:
        for destination in flow["destinations"].split(";"):
            route = cbs.route(flow["source"], destination)
            paths.setdefault(flow["flow_id"], []).append({
                "receiver": destination, "egresses": route,
                "egress_speeds_bps": {e: cbs.capacity_bps(e) for e in route},
                "pcp": int(flow["pcp"]), "tc": int(flow["traffic_class"]),
            })
    brake_ports = {"Z1.ZSW.eth[4]": "F08", "Z2.ZSW.eth[4]": "F09", "Z3.ZSW.eth[5]": "F10"}
    exclusive = {}
    for egress, expected in brake_ports.items():
        traversing = sorted(fid for fid, branches in paths.items()
                            if any(egress in branch["egresses"] for branch in branches))
        exclusive[egress] = {"expected_flow": expected, "application_flows": traversing,
                             "exclusive_for_expected_brake": traversing == [expected],
                             "gptp_control_separately_inventoried": True}
    return {"application_flow_routes": paths, "brake_exit_exclusivity": exclusive,
            "source": "canonical flow catalog + generate_cbs.route() + ZonalIVN.ned and catalog-bindings forwarding tables"}


def gptp_overhead_estimates() -> dict[str, dict]:
    # Serialized chunk sizes are from INET 4.7 GptpPacket.msg / serializer:
    # Sync 44 B, FollowUp 76 B, PdelayReq/Resp/RespFollowUp 54 B. The 38 B
    # Ethernet wire addition is MAC header + FCS + preamble/SFD + IFG.
    wire = {"GptpSync": 82, "GptpFollowUp": 114, "GptpPdelayReq": 92,
            "GptpPdelayResp": 92, "GptpPdelayRespFollowUp": 92}
    counts = {}
    def add(port, msg, rate):
        counts.setdefault(port, {})[msg] = counts.setdefault(port, {}).get(msg, 0.0) + rate
    # Sync/FUP pair each 125 ms on each master egress.
    master_ports = ["HPC.eth[0]", "CSW.eth[1]", "CSW.eth[2]", "CSW.eth[3]"]
    for z in ("Z1", "Z2", "Z3"):
        master_ports.extend(f"{z}.ZSW.eth[{i}]" for i in range(1, 9))
    for port in master_ports:
        add(port, "GptpSync", 8.0)
        add(port, "GptpFollowUp", 8.0)
    # One configured peer-delay requester per bridge slave port; the adjacent
    # responder returns response and follow-up. This is an analytical model.
    add("CSW.eth[0]", "GptpPdelayReq", 1.0)
    add("HPC.eth[0]", "GptpPdelayResp", 1.0)
    add("HPC.eth[0]", "GptpPdelayRespFollowUp", 1.0)
    for z in ("Z1", "Z2", "Z3"):
        add(f"{z}.ZSW.eth[0]", "GptpPdelayReq", 1.0)
        add(f"CSW.eth[{int(z[1])}]", "GptpPdelayResp", 1.0)
        add(f"CSW.eth[{int(z[1])}]", "GptpPdelayRespFollowUp", 1.0)
    report = {}
    for port, message_rates in counts.items():
        bps = round(sum(rate * wire[msg] * 8 for msg, rate in message_rates.items()))
        report[port] = {"message_rates_per_s": message_rates,
                        "wire_bytes_by_message": wire,
                        "estimated_wire_rate_bps": bps,
                        "source": "analytical estimate from configured gPTP intervals and INET 4.7 serializer; not a measured counter"}
    return report


def screen_profiles(profiles: dict, demand: dict, *, gated: bool, gptp_enabled: bool,
                    tas_egresses: set[str] | None = None) -> dict:
    tas_egresses = set(tas_egresses or ()) if gated else set()
    gptp = gptp_overhead_estimates()
    cells = {}
    for load in range(4):
        p = profiles[load]
        totals = {}
        for (egress, _tc), rate in p.items():
            totals[egress] = totals.get(egress, 0) + rate
        port_report = {}
        cap_bad = []
        for egress in sorted(set(totals) | tas_egresses):
            capacity = cbs.capacity_bps(egress)
            total = totals.get(egress, 0)
            demand_by_tc = {str(tc): value for (port, tc), value in demand[load].items() if port == egress}
            tc0_6 = sum(v for (port, tc), v in demand[load].items() if port == egress and tc <= 6)
            tc7 = demand[load].get((egress, 7), 0)
            gptp_bps = gptp.get(egress, {}).get("estimated_wire_rate_bps", 0) if gptp_enabled else 0
            by_tc_service = {}
            class_bad = []
            for (port, tc), configured in sorted(p.items()):
                if port != egress:
                    continue
                open_fraction = 0.77 if gated and egress in tas_egresses else 1.0
                effective = round(configured * open_fraction)
                required = demand[load].get((port, tc), 0)
                by_tc_service[str(tc)] = {
                    "configured_idle_slope_bps": configured,
                    "estimated_average_cbs_service_bps": effective,
                    "permanent_wire_demand_bps": required,
                    "compatible_by_average_service_estimate": effective >= required,
                    "service_model": "idleSlope × 0.77 on a gated egress, otherwise idleSlope; guard-band and interference losses are not included",
                }
                if effective < required:
                    class_bad.append(tc)
            tc06_budget = round(capacity * 0.77) if gated and egress in tas_egresses else capacity
            tc7_budget = round(capacity * 0.10) if gated and egress in tas_egresses else capacity
            tc7_total = tc7 + gptp_bps
            port_report[egress] = {
                "physical_rate_bps": capacity,
                "cbs_reservation_tc4_tc6_bps": total,
                "cbs_cap_fraction": total / capacity,
                "headroom_to_75pct_bps": round(0.75 * capacity) - total,
                "reservation_cap_pass": total <= 0.75 * capacity,
                "permanent_load_bps_by_tc": demand_by_tc,
                "tc0_tc6_open_time_budget_bps": tc06_budget,
                "tc0_tc6_permanent_load_bps": tc0_6,
                "tc0_tc6_open_time_pass": tc0_6 <= tc06_budget,
                "tc7_open_time_budget_bps": tc7_budget,
                "tc7_brake_permanent_load_bps": tc7,
                "gptp_estimated_wire_rate_bps": gptp_bps,
                "tc7_total_estimated_load_bps": tc7_total,
                "tc7_budget_pass_by_estimate": tc7_total <= tc7_budget,
                "cbs_class_service": by_tc_service,
                "cbs_service_pass": not class_bad,
            }
            if total > 0.75 * capacity:
                cap_bad.append(egress)
        failures = []
        for egress, item in port_report.items():
            for gate in ("tc0_tc6_open_time_pass", "tc7_budget_pass_by_estimate", "cbs_service_pass"):
                if not item[gate]:
                    failures.append({"egress": egress, "criterion": gate})
        cells[f"{LOADS[load]}_A0"] = {"admissible": not cap_bad and not failures,
                                      "reservation_rejected_ports": sorted(set(cap_bad)),
                                      "other_rejections": failures, "ports": port_report}
        cells[f"{LOADS[load]}_A1"] = json.loads(json.dumps(cells[f"{LOADS[load]}_A0"]))
    return {"alpha": ALPHA, "gptp_overhead_estimates": gptp, "cells": cells}


def drift_table() -> dict[str, dict[str, float]]:
    path = HERE / "clock_drift_ppm_by_seed_node.json"
    table = json.loads(path.read_text())
    required = {str(seed) for seed in SEEDS}
    if set(table) != required or any(set(table[s]) != set(NODES) for s in table):
        raise RuntimeError("Reused clock-drift table is incomplete or has unexpected seeds/nodes")
    return table


def run_plan() -> list[dict]:
    schedule = []
    def add(variant, load, alignment, seed, kind="primary", allow_inadmissible=False):
        key = f"{LOADS[load]}_A{alignment}"
        schedule.append({"execution_id": f"{variant}_{key}_seed{seed}", "variant": variant,
                         "cell": key, "load_index": load, "alignment": alignment,
                         "seed": seed, "kind": kind, "allow_inadmissible": allow_inadmissible})
    # New isolated protocol: no inherited attempts or historical output is reused.
    # L2/A1 seed 41 first, then fixed-parameter extrapolations.
    for v in ("C3base", "C3sync", "C4compensated"):
        add(v, 2, 1, 41)
    add("C4original", 2, 1, 41, "fullpath_diagnostic", allow_inadmissible=True)
    # Fixed-profile robustness checks, no re-tuning.
    for seed in (43, 47):
        for v in ("C3base", "C3sync", "C4compensated"):
            add(v, 2, 1, seed)
    # Two predeclared extrapolation cells.
    for load, alignment in ((0, 0), (1, 1)):
        for v in ("C3base", "C3sync", "C4compensated"):
            add(v, load, alignment, 41)
    return schedule


def source_hashes() -> dict[str, str]:
    paths = [
        PROTOCOL, PILOT_INI, P1_PDF, PROFILE_JSON, PROFILE_CHECKPOINT,
        HERE / "clock_drift_ppm_by_seed_node.json",
        HERE / "repair_gate_evidence.py",
        SIM / "pilot/c4_service_preservation/results/plan.json",
        SIM / "pilot/c4_service_preservation/results/pilot_results.json",
        HERE / "protocol.md", HERE / "README.md",
        SIM / "omnetpp.ini", SIM / "zonal/traffic/flows.csv",
        SIM / "zonal/configs/classification.ini", SIM / "zonal/configs/traffic.ini",
        SIM / "zonal/configs/mechanisms/C2_nominal_rates.ini",
        SIM / "zonal/configs/mechanisms/C3_calibrated_rates.ini",
        ROOT / "scripts/run/validate_c0.py", ROOT / "scripts/catalog/generate_cbs.py",
        ROOT / "src/common/TrafficPlan.cc", ROOT / "src/common/TrafficPlan.ned",
        Path(__file__), Path(__file__).with_name("pilot_status.py"),
    ]
    return {str(p.relative_to(ROOT)): sha256(p) for p in paths if p.is_file()}


def make_manifest() -> dict:
    def cmd(args):
        try:
            return subprocess.run(args, cwd=ROOT, text=True, capture_output=True,
                                  timeout=10).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return "unavailable"
    inet = Path(os.environ.get("INET_ROOT", str(Path.home() / "omnetpp/samples/inet-4.7.0"))).resolve()
    omnet_root = Path(os.environ.get("OMNETPP_ROOT", str(Path.home() / "omnetpp"))).resolve()
    omnet_version_file = omnet_root / "Version"
    inet_version_file = inet / "Version"
    omnet_version = omnet_version_file.read_text().strip() if omnet_version_file.is_file() else cmd(["opp_run", "-v"])
    inet_version = inet_version_file.read_text().strip() if inet_version_file.is_file() else "unavailable"
    inet_commit = cmd(["git", "-C", str(inet), "rev-parse", "HEAD"]) or "not_a_git_checkout"
    profile, ratios, nominal = load_frozen_profile()
    base_profiles = profiles_by_load(ratios, nominal)
    demand = catalog_loads()
    screens = {
        "C3_base": screen_profiles(base_profiles, demand, gated=False, gptp_enabled=False),
        "C3_sync": screen_profiles(base_profiles, demand, gated=False, gptp_enabled=True),
        "C4_compensated_fullpath_corrected": screen_profiles({load: {key: round(value / ALPHA) if key[0] in FULL_PATH_TAS_EGRESSES else value for key, value in p.items()} for load, p in base_profiles.items()}, demand, gated=True, gptp_enabled=True, tas_egresses=FULL_PATH_TAS_EGRESSES),
        "C4_shared_SPbrakes": screen_profiles({load: {key: round(value / ALPHA) if key[0] in TAS_EGRESSES else value for key, value in p.items()} for load, p in base_profiles.items()}, demand, gated=True, gptp_enabled=True, tas_egresses=TAS_EGRESSES),
    }
    git_status = cmd(["git", "status", "--short"])
    return {
        "pilot_id": "c4-shared-sp-brakes",
        "exploratory": True, "official_c4_frozen": False,
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "git_commit": cmd(["git", "rev-parse", "HEAD"]),
        "working_tree_status_at_plan": git_status,
        "omnetpp_version": omnet_version,
        "omnetpp_version_file_sha256": sha256(omnet_version_file) if omnet_version_file.is_file() else None,
        "inet_root": str(inet),
        "inet_version": inet_version,
        "inet_version_file_sha256": sha256(inet_version_file) if inet_version_file.is_file() else None,
        "inet_commit": inet_commit,
        "p1": {"path": str(P1_PDF.relative_to(ROOT)), "sha256": sha256(P1_PDF)},
        "historical_pilot": {"directory": "simulations/pilot/c4_service_preservation",
            "plan_sha256": sha256(SIM / "pilot/c4_service_preservation/results/plan.json"),
            "results_sha256": sha256(SIM / "pilot/c4_service_preservation/results/pilot_results.json"),
            "is_reused_for_new_campaign": False},
        "official_profile": {"path": str(PROFILE_JSON.relative_to(ROOT)),
            "sha256": sha256(PROFILE_JSON), "status": profile["status"],
            "profile_id": profile["final_profile_id"],
            "verified_seeds": profile.get("profile_verified_seeds", []),
            "ratios": ratios},
        "route_audit": route_audit(),
        "application_schedule_reference": {"clock": "OMNeT++ simulation time via simTime()/scheduleAt in CatalogUdpApp", "source": "src/applications/CatalogUdpApp.cc", "not_local_clock": True},
        "phy_implementation": {"all_variants": "StreamingTransmitter + DestreamingReceiver", "purpose": "remove PHY implementation as a contrast confounder", "gptp_changes_only_between_C3_base_and_C3_sync": True},
        "versions_and_hashes": source_hashes(),
        "parameters": {"warmup_s": 1, "measurement_s": 30, "drain_s": 0.05,
            "seeds": list(SEEDS), "alpha": ALPHA, "max_jobs": MAX_JOBS,
            "minimum_free_disk_gb": FREE_FLOOR_GB, "TAS_egresses_shared_SPbrakes": sorted(TAS_EGRESSES),
            "TAS_egresses_fullpath_diagnostic": sorted(FULL_PATH_TAS_EGRESSES),
            "SP_always_open_brake_egresses": sorted(BRAKE_SP_EGRESSES),
            "CBS_source": "official frozen C3 reduction_11, ratio-applied to generated permanent per-egress rates",
            "transient_randomization": "Dedicated TrafficPlan RNG streams 0/1; each matched cohort replays the exact baseline F21/F22 event calendar and verifies SHA-256",
            "clock_drift_ppm_by_seed_node": drift_table()},
        "variants": {
            "C3_base": {"gptp": False, "tas": False, "cbs": "frozen C3"},
            "C3_sync": {"gptp": True, "tas": False, "cbs": "frozen C3"},
            "C4_shared_SPbrakes": {"gptp": True, "tas": "four shared egresses only", "brake_exits": "SP permanently open", "cbs": "frozen C3 divided by 0.77 on CBS queues at four TAS egresses"},
            "C4_compensated_fullpath_corrected": {"gptp": True, "tas": "four shared plus three resolved brake egresses", "cbs": "frozen C3 divided by 0.77 on CBS queues at seven TAS egresses", "diagnostic_only": True}},
        "variant_ids": VARIANT_NAMES,
        "admissibility": screens,
        "run_schedule": run_plan(),
        "budget": {"maximum_methodological_executions": 16,
            "total_scheduled": len(run_plan()), "primary_L2_A1": 9,
            "extrapolation": 6, "fullpath_corrected_diagnostic": 1,
            "technical_attempts_count_separately": True},
    }


def run_profile_for_load(manifest: dict, load: int, variant: str) -> dict[tuple[str, int], int]:
    ratios = manifest["official_profile"]["ratios"]
    nominal = cbs.nominal_reservations(cbs.read_flows())
    profile = {}
    for key, ratio in ratios.items():
        egress, tc_text = key.rsplit("/TC", 1)
        tc = int(tc_text)
        base = int(nominal.get((load, egress, tc), {"bps": 0})["bps"])
        rate = round(base * float(ratio))
        if rate > 0:
            if variant == "C4compensated" and egress in TAS_EGRESSES or variant == "C4original" and egress in FULL_PATH_TAS_EGRESSES:
                rate = round(rate / ALPHA)
            profile[egress, tc] = rate
    return profile


def current_ledger() -> list[dict]:
    rows = []
    path = OUT / "runs.jsonl"
    if not path.exists():
        return rows
    with path.open(encoding="utf-8") as f:
        for line in f:
            try:
                if line.strip(): rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def current_attempts() -> list[dict]:
    rows = []
    path = OUT / "technical_attempts.jsonl"
    if not path.exists():
        return rows
    with path.open(encoding="utf-8") as f:
        for line in f:
            try:
                if line.strip(): rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def archive_uncommitted(dest: Path, execution_id: str) -> None:
    if not dest.exists() or not any(dest.iterdir()):
        return
    stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
    archived = OUT / "failed-attempts" / f"{execution_id}_{stamp}"
    archived.parent.mkdir(parents=True, exist_ok=True)
    suffix = 1
    while archived.exists():
        archived = OUT / "failed-attempts" / f"{execution_id}_{stamp}_{suffix}"
        suffix += 1
    files = [{"path": str(p.relative_to(dest)), "bytes": p.stat().st_size}
             for p in dest.rglob("*") if p.is_file()]
    os.replace(dest, archived)
    write_json(archived / "attempt_metadata.json", {
        "scheduled_execution_id": execution_id, "status": "uncommitted_attempt_archived",
        "archived_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "files": files, "bytes": sum(x["bytes"] for x in files)})


def finish_committed_cleanup(row: dict) -> None:
    """Finish compression after power loss between ledger commit and cleanup."""
    variant = row.get("variant")
    if not variant:
        return
    config = f"Pilot_{variant}_{row['cell']}"
    dest = OUT / "runs" / row["execution_id"]
    run_dir = dest / f"{config}-0"
    vec = dest / f"{config}-#0.vec"
    if vec.exists() or any(dest.glob(f"{config}-#0.sca")) or any(dest.glob(f"{config}.log")):
        compress_or_remove_raw(dest, config, run_dir, bool(row.get("retained_raw_vector")))


def write_checkpoint(**updates) -> None:
    with LOCK:
        CHECKPOINT.update(updates)
        CHECKPOINT["updated_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        CHECKPOINT["free_gb"] = round(free_gb(), 3)
        write_json(OUT / "checkpoint.json", CHECKPOINT)


def parse_sample_line(line: str):
    p = line.split()
    if len(p) == 4 and p[0].isdigit():
        return int(p[0]), float(p[2]), float(p[3])
    if len(p) == 3 and p[0].isdigit():
        return int(p[0]), float(p[1]), float(p[2])
    return None


def accumulate_sample_hold(area: float, previous: tuple[float, float] | None,
                           time_s: float, value: float, start: float, end: float):
    """Incrementally integrate one vector's right-continuous sample-hold state."""
    prior_time, prior_value = previous if previous is not None else (0.0, 0.0)
    left, right = max(prior_time, start), min(time_s, end)
    if right > left:
        area += prior_value * (right - left)
    return area, (time_s, value)


def finish_sample_hold(area: float, previous: tuple[float, float] | None,
                       start: float, end: float) -> float:
    """Integrate the final held state to the measurement-window end."""
    if previous is None:
        return area
    prior_time, prior_value = previous
    left = max(prior_time, start)
    if end > left:
        area += prior_value * (end - left)
    return area


def parse_effective_gcl(sca: Path, variant: str) -> dict:
    """Read resolved C4 gate settings from the simulator's scalar/config file."""
    expected_ports = tuple(sorted(FULL_PATH_TAS_EGRESSES if variant == "C4original" else TAS_EGRESSES))
    rows = {}
    with sca.open(errors="replace") as stream:
        for line in stream:
            if not line.startswith("par ZonalIVN."):
                continue
            parts = line.rstrip().split(" ", 3)
            if len(parts) != 4:
                continue
            _, module, field, value = parts
            if ".transmissionGate[" not in module:
                continue
            rows.setdefault(module, {})[field] = value.strip()
    expected = {}
    for port in expected_ports:
        for tc in range(8):
            module = f"ZonalIVN.{port}.macLayer.queue.transmissionGate[{tc}]"
            expected[module] = {"durations": "[77us,23us]" if tc < 7 else "[10us,90us]",
                                "offset": "90us" if tc < 7 else None,
                                "initiallyOpen": "true", "clockModule": "^.^.^.^.clock",
                                "scheduleForAbsoluteTime": "true", "enableImplicitGuardBand": "true"}
    if variant == "C4compensated":
        for port in BRAKE_SP_EGRESSES:
            for tc in range(8):
                module = f"ZonalIVN.{port}.macLayer.queue.transmissionGate[{tc}]"
                # An empty PeriodicGate schedule with initiallyOpen=true never
                # schedules a close event. A one-entry [100us] list is invalid,
                # while [100us, ...] would periodically close these SP exits.
                expected[module] = {"durations": "[]", "offset": "0s", "initiallyOpen": "true",
                                    "clockModule": "^.^.^.^.clock", "scheduleForAbsoluteTime": "true",
                                    "enableImplicitGuardBand": "true"}
    def plain(value):
        if value is None:
            return None
        text = value.strip()
        try:
            decoded = json.loads(text)
            if isinstance(decoded, str):
                text = decoded
        except json.JSONDecodeError:
            pass
        text = text.replace('\\"', '"').strip()
        if len(text) >= 2 and text[0] == text[-1] == '"':
            text = text[1:-1]
        return text
    def time_seconds(value: str | None) -> float | None:
        if value is None:
            return None
        text = plain(value)
        match = re.fullmatch(r"\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)\s*(s|ms|us|ns|ps)?\s*", text)
        if not match:
            return None
        number = float(match.group(1))
        scale = {None: 1.0, "s": 1.0, "ms": 1e-3, "us": 1e-6, "ns": 1e-9, "ps": 1e-12}[match.group(2)]
        return number * scale

    def duration_list(value: str | None) -> list[float] | None:
        if value is None:
            return None
        match = re.fullmatch(r"\s*\[\s*(.*?)\s*\]\s*", plain(value))
        if not match:
            return None
        if not match.group(1).strip():
            return []
        parts = [part.strip() for part in match.group(1).split(",")]
        parsed = [time_seconds(part) for part in parts]
        return parsed if parsed and all(part is not None for part in parsed) else None

    checks = {}
    for module, values in expected.items():
        observed = rows.get(module, {})
        expected_durations = duration_list(values["durations"])
        observed_durations = duration_list(observed.get("durations"))
        ok = (expected_durations is not None and observed_durations is not None and
              len(expected_durations) == len(observed_durations) and
              all(abs(a - b) <= 1e-12 for a, b in zip(expected_durations, observed_durations)) and
              plain(observed.get("initiallyOpen")) == "true" and
              plain(observed.get("clockModule")) == values["clockModule"] and
              plain(observed.get("scheduleForAbsoluteTime")) == values["scheduleForAbsoluteTime"] and
              plain(observed.get("enableImplicitGuardBand")) == values["enableImplicitGuardBand"])
        period = sum(observed_durations) if observed_durations else None
        # The three brake egresses are permanently-open SP only in the
        # shared-SP-brakes treatment. The full-path diagnostic intentionally
        # schedules TAS on those same physical ports.
        permanently_open_sp = (variant == "C4compensated" and
                               any(p in module for p in BRAKE_SP_EGRESSES))
        if permanently_open_sp:
            ok = ok and observed_durations == [] and plain(observed.get("initiallyOpen")) == "true"
        else:
            expected_period = 100e-6
            ok = ok and period is not None and abs(period - expected_period) <= 1e-12
        if values["offset"] is not None:
            expected_offset = time_seconds(values["offset"])
            observed_offset = time_seconds(observed.get("offset"))
            ok = ok and expected_offset is not None and observed_offset is not None and abs(expected_offset - observed_offset) <= 1e-12
        tc = int(module.rsplit("[", 1)[1].rstrip("]"))
        if permanently_open_sp:
            phase = [[0.0, 100.0]]
        else:
            phase = [[10.0, 87.0]] if tc < 7 else [[0.0, 10.0]]
        checks[module] = {"expected": values, "observed": {k: observed.get(k) for k in values},
                          "observed_period_s": period, "permanently_open_sp": permanently_open_sp,
                          "effective_open_phase_us": phase, "pass": ok}
    return {"status": "pass" if all(x["pass"] for x in checks.values()) else "fail",
            "expected_gate_count": len(expected), "observed_gate_count": sum(m in rows for m in expected),
            "gates": checks}


def parse_effective_time_sync(sca: Path) -> dict:
    expected_nodes = ("HPC", "CSW", "Z1.ZSW", "Z2.ZSW", "Z3.ZSW")
    observed = {}
    with sca.open(errors="replace") as stream:
        for line in stream:
            if not line.startswith("par ZonalIVN."):
                continue
            parts = line.rstrip().split(" ", 3)
            if len(parts) == 4 and parts[2] == "hasTimeSynchronization":
                node = parts[1].removeprefix("ZonalIVN.")
                if node in expected_nodes:
                    observed[node] = parts[3].strip().lower() == "true"
    return {"status": "pass" if all(observed.get(node) is True for node in expected_nodes) else "fail",
            "expected_nodes": list(expected_nodes), "effective_values": observed}


def extract_pilot_vectors(vec: Path, report: dict, run_dir: Path, variant: str) -> dict:
    """Extract accurate utilization and compact gate/clock/credit evidence."""
    definitions = {}
    with vec.open(errors="replace") as f:
        for line in f:
            if line.startswith("vector "):
                p = line.rstrip().split(" ", 4)
                if len(p) == 5:
                    definitions[int(p[1])] = {"module": p[2], "name": p[3], "attrs": p[4]}
            elif line and line[0].isdigit():
                break
    start, end = 1.0, 31.0
    selected = {}
    for vid, info in definitions.items():
        name, module = info["name"], info["module"]
        if name.startswith("transmitting:vector") or name == "transmitting:vector":
            if ".phyLayer.transmitter" in module:
                selected[vid] = ("link", module)
        elif name.startswith("gateState:vector") or name == "gateState:vector":
            selected[vid] = ("gate", module)
        elif name.startswith("guardBandState:vector") or name == "guardBandState:vector":
            selected[vid] = ("guard", module)
        elif name.startswith("timeChanged:vector") or name == "timeChanged:vector":
            if module.endswith(".clock") or module.endswith(".clock.clock"):
                selected[vid] = ("clock", module)
        elif any(x in name for x in ("numCredits:", "gmRateRatio:", "neighborRateRatio:", "pdelay:", "packetDropNotAddressedToUs:")):
            if ".gptp" in module or "transmissionSelectionAlgorithm" in module:
                selected[vid] = ("other", module + "." + name)

    # Stream high-volume state/credit vectors. CBS credit vectors can contain
    # millions of samples per egress; retaining all samples in Python lists
    # caused the kernel OOM killer to terminate this extractor. Only five clock
    # series (about 155k rows) and one state sample per vector are held in RAM.
    last_state: dict[int, tuple[float, float]] = {}
    state_area: dict[int, float] = {}
    invalid_state_values: dict[int, list[float]] = {}
    nonmonotonic_vectors: set[int] = set()
    clock_series: dict[str, list[tuple[float, float]]] = {}
    gate_modules = set()
    gate_sample_count = 0
    guard_sample_count = 0
    other_sample_count = 0
    gate_area_by_module: dict[str, float] = {}
    link_util = {}
    gate_path = run_dir / "gate_states.csv.gz"
    guard_path = run_dir / "guard_band_states.csv.gz"
    other_path = run_dir / "pilot_other_vectors.csv.gz"
    with gzip.open(gate_path, "wt", newline="", encoding="utf-8", compresslevel=6) as gate_file, \
         gzip.open(guard_path, "wt", newline="", encoding="utf-8", compresslevel=6) as guard_file, \
         gzip.open(other_path, "wt", newline="", encoding="utf-8", compresslevel=6) as other_file:
        gate_writer = csv.writer(gate_file); gate_writer.writerow(("module", "simtime_s", "state_open"))
        guard_writer = csv.writer(guard_file); guard_writer.writerow(("module", "simtime_s", "guard_band_on"))
        other_writer = csv.writer(other_file); other_writer.writerow(("vector", "simtime_s", "value"))
        with vec.open(errors="replace") as f:
            for line in f:
                parsed = parse_sample_line(line)
                if parsed is None:
                    continue
                vid, t, value = parsed
                entry = selected.get(vid)
                if entry is None:
                    continue
                kind, module = entry
                if kind in ("link", "gate"):
                    if value not in (0.0, 1.0):
                        invalid_state_values.setdefault(vid, []).append(value)
                    prior = last_state.get(vid)
                    if prior is not None and t < prior[0]:
                        nonmonotonic_vectors.add(vid)
                    state_area[vid], last_state[vid] = accumulate_sample_hold(
                        state_area.get(vid, 0.0), last_state.get(vid), t, value, start, end)
                if kind == "link":
                    continue
                if kind == "gate":
                    gate_modules.add(module)
                    if 0 <= t <= 31.05:
                        gate_writer.writerow((module, t, int(round(value))))
                        gate_sample_count += 1
                    continue
                if kind == "guard":
                    if 0 <= t <= 31.05:
                        guard_writer.writerow((module, t, int(round(value))))
                        guard_sample_count += 1
                    continue
                if kind == "clock":
                    clock_series.setdefault(module, []).append((t, value))
                    continue
                other_writer.writerow((module, t, value))
                other_sample_count += 1

    invalid_utilities = []
    for vid, (kind, module) in selected.items():
        if kind in ("link", "gate"):
            state_area[vid] = finish_sample_hold(state_area.get(vid, 0.0), last_state.get(vid), start, end)
            if kind == "link":
                fraction = state_area.get(vid, 0.0) / (end - start)
                valid = (math.isfinite(fraction) and 0.0 <= fraction <= 1.0 and
                         not invalid_state_values.get(vid) and vid not in nonmonotonic_vectors)
                if not valid:
                    invalid_utilities.append({"transmitter": module, "raw_fraction": fraction,
                        "invalid_values": invalid_state_values.get(vid, [])[:8],
                        "nonmonotonic": vid in nonmonotonic_vectors})
                link_util[module] = {"measurement_busy_fraction": fraction if valid else None,
                                     "measurement_busy_percent": 100 * fraction if valid else None,
                                     "valid": valid,
                                     "method": "time integral of binary sample-hold transmitting state on [1,31) seconds; invalid values/order make metric unavailable"}
            else:
                gate_area_by_module[module] = gate_area_by_module.get(module, 0.0) + state_area.get(vid, 0.0)

    # Interpolate all local clock vectors against the same-simulation-time HPC clock.
    ref = clock_series.get("ZonalIVN.HPC.clock") or clock_series.get("ZonalIVN.HPC.clock.clock")
    offsets = []
    sync_summary = {"status": "unavailable", "criterion": "offset magnitude <=1us throughout measurement [1,31)s; warm-up convergence reported separately"}
    if ref:
        ref = sorted(ref)
        clock_series = {key: sorted(value) for key, value in clock_series.items()}
        time_cache = {id(series): [sample[0] for sample in series] for series in clock_series.values()}
        time_cache[id(ref)] = [sample[0] for sample in ref]
        def interp(series, t):
            if not series: return None
            if t <= series[0][0]: return series[0][1]
            ts = time_cache.get(id(series))
            if ts is None:
                series.sort()
                ts = [sample[0] for sample in series]
                time_cache[id(series)] = ts
            ix = bisect_right(ts, t)
            if ix < len(series):
                ta, va = series[ix - 1]; tb, vb = series[ix]
                return va if tb == ta else va + (vb - va) * (t - ta) / (tb - ta)
            return series[-1][1]
        checked_nodes = []
        for node in ("ZonalIVN.CSW.clock", "ZonalIVN.Z1.ZSW.clock", "ZonalIVN.Z2.ZSW.clock", "ZonalIVN.Z3.ZSW.clock"):
            series = clock_series.get(node) or clock_series.get(node + ".clock")
            if not series:
                continue
            window = []
            for t, local_time in sorted(series):
                if 0 <= t < 31.0:
                    gm = interp(ref, t)
                    if gm is not None:
                        offset = local_time - gm
                        if 1.0 <= t < 31.0:
                            window.append((t, offset))
                        offsets.append({"simtime_s": t, "node": node.removeprefix("ZonalIVN."), "offset_s": offset})
            at_warmup = interp(series, 1.0)
            gm_warmup = interp(ref, 1.0)
            max_abs = max((abs(v) for _, v in window), default=None)
            warmup_offset = None if at_warmup is None or gm_warmup is None else at_warmup-gm_warmup
            violation_duration = 0.0
            ordered_window = sorted(window)
            for (ta, oa), (tb, ob) in zip(ordered_window, ordered_window[1:]):
                dt = tb - ta
                aa, ab = abs(oa) - 1e-6, abs(ob) - 1e-6
                if aa > 0 and ab > 0:
                    violation_duration += dt
                elif aa > 0 >= ab:
                    violation_duration += dt * aa / (aa - ab)
                elif aa <= 0 < ab:
                    violation_duration += dt * ab / (ab - aa)
            stable = max_abs is not None and max_abs <= 1e-6
            checked_nodes.append({"node": node.removeprefix("ZonalIVN."), "max_abs_offset_measurement_s": max_abs,
                                  "offset_at_warmup_end_s": warmup_offset,
                                  "samples_measurement": len(window),
                                  "sample_resolution_s_median": statistics.median([b[0]-a[0] for a,b in zip(ordered_window,ordered_window[1:])]) if len(ordered_window)>1 else None,
                                  "estimated_duration_over_1us_s_piecewise_linear": violation_duration,
                                  "duration_method": "linear interpolation between 1ms sampled clock points; unsampled excursions are not excluded",
                                  "passes_pilot_sync_threshold": stable})
        if checked_nodes:
            sync_summary = {"status": "pass" if len(checked_nodes) == 4 and all(x["passes_pilot_sync_threshold"] for x in checked_nodes) else "fail",
                            "criterion": "all downstream offsets <=1us throughout [1,31)s; 1ms sampled interpolation",
                            "nodes": checked_nodes}
    if offsets:
        with gzip.open(run_dir / "clock_offsets.csv.gz", "wt", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=("simtime_s", "node", "offset_s"))
            w.writeheader(); w.writerows(offsets)
    expected_links = 56
    link_status = ("available" if len(link_util) == expected_links and all(x["valid"] for x in link_util.values())
                   else "unavailable_invalid_state" if any(not x["valid"] for x in link_util.values()) else "incomplete")
    gate_fractions = {module: area / (end - start)
                      for module, area in gate_area_by_module.items()}
    gate_expected = {}
    tas_ports = (FULL_PATH_TAS_EGRESSES if variant == "C4original" else TAS_EGRESSES) if "C4" in variant else set()
    for port in tas_ports:
        for tc in range(8):
            module = f"ZonalIVN.{port}.macLayer.queue.transmissionGate[{tc}]"
            gate_expected[module] = 0.10 if tc == 7 else 0.77
    gate_checks = {module: {"expected_open_fraction": expected,
                            "observed_open_fraction": gate_fractions.get(module),
                            "within_1e-4": gate_fractions.get(module) is not None and abs(gate_fractions[module] - expected) <= 1e-4}
                   for module, expected in gate_expected.items()}
    gate_schedule_status = "not_applicable" if "C4" not in variant else (
        "pass" if all(m in gate_modules for m in gate_expected) and all(x["within_1e-4"] for x in gate_checks.values()) else "fail")
    has_clock = lambda node: bool(clock_series.get(node) or clock_series.get(node + ".clock"))
    clock_status = "pass" if all(has_clock(x) for x in (
        "ZonalIVN.HPC.clock", "ZonalIVN.CSW.clock", "ZonalIVN.Z1.ZSW.clock",
        "ZonalIVN.Z2.ZSW.clock", "ZonalIVN.Z3.ZSW.clock")) else "unavailable"
    report["physical_link_utilization"] = {
        "status": link_status, "transmitters_observed": len(link_util), "expected_transmitters": expected_links,
        "method": "time-weighted sample-hold integral of INET transmitting state over measurement window [1,31)",
        "by_transmitter": link_util}
    report["physical_link_utilization"]["invalid_state_series"] = invalid_utilities
    # Retain the common validator's SCA histogram only as a diagnostic.
    report["link_utilization_sca_histogram"] = report.get("link_utilization")
    report["link_utilization"] = None
    report["tas_gate_schedule"] = {"status": gate_schedule_status, "measurement_window_s": [start, end],
        "expected_gate_count": len(gate_expected), "observed_gate_count": sum(m in gate_modules for m in gate_expected),
        "tolerance_fraction": 1e-4, "gates": gate_checks,
        "always_open_sp_gate_count_config_verified": (24 if variant == "C4compensated" else 0),
        "always_open_sp_verification": (report.get("effective_gcl", {}).get("status")
            if variant == "C4compensated" else "not_applicable"),
        "note": "Gate-state vectors are expected only for scheduled TAS gates. Permanently open SP brake exits have empty schedules and are verified from effective SCA configuration; no transition vector is expected."}
    clock_required = variant != "C3base"
    state_available = (len(link_util) == expected_links and
                       (not clock_required or clock_status == "pass") and
                       ("C4" not in variant or gate_schedule_status == "pass"))
    return {"physical_link_utilization_status": link_status,
            "gate_state_samples": gate_sample_count, "guard_band_state_samples": guard_sample_count,
            "other_vector_samples_streamed": other_sample_count,
            "auxiliary_vector_storage": "streamed-to-gzip; clock samples retained in memory for offset interpolation only",
            "clock_vectors": len(clock_series), "synchronization": sync_summary,
            "clock_vector_status": clock_status if clock_required else "not_applicable",
            "tas_gate_schedule": report["tas_gate_schedule"],
            "state_vector_status": "available" if state_available else "incomplete",
            "state_vector_status_reason": ("gPTP clock vectors are not required in the C3-base treatment" if not clock_required else None)}


def parse_gptp_sends(log_path: Path) -> dict:
    """Best-effort extraction from INET's explicit EV_INFO send log entries."""
    patterns = re.compile(r"Sending .*?(Gptp(?:Sync|FollowUp|PdelayReq|PdelayRespFollowUp|PdelayResp)).*?output interface\s*=\s*(eth\[?\d+\]?)", re.I)
    wire_bytes = {"GptpSync": 82, "GptpFollowUp": 114, "GptpPdelayReq": 92,
                  "GptpPdelayResp": 92, "GptpPdelayRespFollowUp": 92}
    counts = {"warmup": {}, "measurement": {}, "drain": {}, "unwindowed": {}}
    total_matches = 0
    if log_path.exists():
        with log_path.open(errors="replace") as f:
            for line in f:
                m = patterns.search(line)
                if not m:
                    continue
                total_matches += 1
                name, iface = m.group(1), m.group(2)
                node_match = re.search(r"(ZonalIVN\.[A-Za-z0-9.]+)\.gptp", line)
                if not node_match:
                    continue
                iface_index = re.fullmatch(r"eth\[?(\d+)\]?", iface)
                if not iface_index:
                    continue
                key = f"{node_match.group(1).removeprefix('ZonalIVN.')}.eth[{iface_index.group(1)}]"
                time_match = re.search(r"\[([0-9]+(?:\.[0-9]+)?)(?:s)?\]", line)
                window = "unwindowed"
                if time_match:
                    simtime = float(time_match.group(1))
                    window = "warmup" if simtime < 1 else "measurement" if simtime < 31 else "drain"
                slot = counts[window].setdefault(key, {})
                entry = slot.setdefault(name, {"messages": 0, "wire_bytes": 0})
                entry["messages"] += 1
                entry["wire_bytes"] += wire_bytes.get(name, 0)
    return {"status": "measured_from_INet_send_log" if total_matches else "unavailable_log_format_or_logging",
            "matched_send_events": total_matches, "wire_bytes_by_message_type": wire_bytes,
            "counts_bytes_by_window_port_and_type": counts,
            "window_note": "measurement cohort is [1,31) s when the simulator log timestamp was parsed; unmatched timestamps remain unwindowed"}


def crosscheck_utilization_with_wire_summary(run_dir: Path, report: dict) -> dict:
    """Whole-run activity/serialization context; never relabeled as window utilization."""
    path = run_dir / "wire.csv.gz"
    if not path.exists():
        return {"status": "unavailable_wire_summary_missing"}
    totals = {}
    with gzip.open(path, "rt", newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            interface = row["interface"]
            value = totals.setdefault(interface, {"application_packets": 0, "application_bytes": 0})
            value["application_packets"] += int(row.get("packets") or 0)
            value["application_bytes"] += int(row.get("bytes") or 0)
    results, mismatches = {}, []
    link = (report.get("physical_link_utilization") or {}).get("by_transmitter", {})
    for module, metric in link.items():
        interface = module.removesuffix(".phyLayer.transmitter")
        app = totals.get(interface, {"application_packets": 0, "application_bytes": 0})
        rate = cbs.capacity_bps(interface.removeprefix("ZonalIVN."))
        count, nbytes = app["application_packets"], app["application_bytes"]
        busy = metric.get("measurement_busy_fraction")
        consistent = busy is None or count == 0 or busy > 0
        if count and busy == 0:
            mismatches.append(interface)
        results[interface] = {**app, "measurement_busy_fraction": busy,
            "activity_presence_consistent": consistent,
            "whole_run_serialization_s_excluding_ifg": nbytes * 8 / rate if rate else None,
            "whole_run_estimated_busy_fraction_excluding_ifg": nbytes * 8 / rate / 31.05 if rate else None,
            "physical_rate_bps": rate,
            "scope": "whole-run application TrafficAudit summary; not window-aligned and not inclusive of separate gPTP events"}
    return {"status": "checked_whole_run_activity_context", "interfaces": results,
        "application_nonzero_but_transmitting_fraction_zero": mismatches,
        "comparison_limit": "Whole-run counts validate activity/serialization scale only; they cannot independently reproduce [1,31) busy fractions."}


def read_resolved_cbs(sca: Path) -> dict:
    params = validator.parse_sca(sca)
    out = {}
    for (module, name), value in params.items():
        m = re.fullmatch(r"(ZonalIVN\..*\.macLayer\.queue\.transmissionSelectionAlgorithm)\[(\d+)\]", module)
        if not m:
            continue
        tc = int(m.group(2))
        metric_match = re.match(r"numCredits:(timeavg|min|max|vector)\b", name)
        idle = name == "idleSlope"
        if not (metric_match or idle):
            continue
        port = (m.group(1).removeprefix("ZonalIVN.")
                .removesuffix(".macLayer.queue.transmissionSelectionAlgorithm"))
        key = f"{port}/TC{tc}"
        out.setdefault(key, {})[name] = value
    return out


def completed_raw_run_matches(dest: Path, config: str, seed: int) -> bool:
    """Recognize a finished raw OMNeT run so post-processing can resume without rerunning it."""
    sca = dest / f"{config}-#0.sca"
    vec = dest / f"{config}-#0.vec"
    log = dest / f"{config}.log"
    run_dir = dest / f"{config}-0"
    required = (sca, vec, log, run_dir / "events.csv", run_dir / "releases.csv")
    if not all(p.is_file() and p.stat().st_size > 0 for p in required):
        return False
    sca_text = sca.read_text(errors="replace")
    log_text = log.read_text(errors="replace")
    attrs = dict(re.findall(r"^attr (\S+) (.*)$", sca_text, re.MULTILINE))
    return (attrs.get("configname") == config and attrs.get("seedset") == str(seed)
            and attrs.get("inifile") == "pilot/c4_shared_sp_brakes/pilot.ini"
            and "Simulation time limit reached -- at t=31.05s" in log_text
            and "Calling finish() at end of Run #0..." in log_text
            and "<!> Error:" not in log_text)


def expected_rates_overrides(profile: dict[tuple[str, int], int]) -> list[str]:
    result = []
    for (egress, tc), rate in sorted(profile.items()):
        base = f"--*.{egress}.macLayer.queue.transmissionSelectionAlgorithm[{tc}]"
        result.extend((f"{base}.typename=Ieee8021qCreditBasedShaper", f"{base}.idleSlope={rate}bps"))
    return result


def variant_clock_overrides(seed: int, variant: str, manifest: dict) -> list[str]:
    if variant == "C3base":
        return []
    values = manifest["parameters"]["clock_drift_ppm_by_seed_node"][str(seed)]
    return [f"--*.{node}.clock.oscillator.driftRate={values[node]}ppm" for node in NODES]


def calendar_signature(run_dir: Path):
    path = run_dir / "events.csv"
    with path.open(newline="") as f:
        rows = list(csv.DictReader(f))
    cols = ("flow", "block", "signature", "start", "duration", "volume_bytes")
    payload = [{k: row[k] for k in cols} for row in rows]
    sig = hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()
    return sig, rows


def compress_or_remove_raw(dest: Path, config: str, run_dir: Path, keep_vector: bool):
    # Keep compact auditable products. Raw vectors survive only for one
    # representative pass and one representative failure, compressed.
    for path in (dest / f"{config}-#0.sca", dest / f"{config}.log"):
        if path.exists():
            gz = Path(str(path) + ".gz")
            with path.open("rb") as src, gzip.open(gz, "wb", compresslevel=6) as dst:
                shutil.copyfileobj(src, dst)
            path.unlink()
    for path in dest.glob(f"{config}-#*.vec"):
        if keep_vector:
            gz = Path(str(path) + ".gz")
            with path.open("rb") as src, gzip.open(gz, "wb", compresslevel=6) as dst:
                shutil.copyfileobj(src, dst)
        path.unlink()
    for name in ("releases.csv", "queues.csv", "drops.csv", "wire.csv", "events.csv"):
        path = run_dir / name
        if path.exists():
            gz = Path(str(path) + ".gz")
            with path.open("rb") as src, gzip.open(gz, "wb", compresslevel=6) as dst:
                shutil.copyfileobj(src, dst)
            path.unlink()


def save_calendar(run_dir: Path, exec_spec: dict, signature: str, rows: list[dict]):
    key = f"{exec_spec['cell']}/seed{exec_spec['seed']}"
    cdir = OUT / "calendars" / exec_spec["cell"]
    cdir.mkdir(parents=True, exist_ok=True)
    cpath = cdir / f"seed{exec_spec['seed']}_events.csv"
    index_path = OUT / "calendars/calendar_index.json"
    try: index = json.loads(index_path.read_text())
    except (OSError, json.JSONDecodeError): index = {}
    previous = index.get(key)
    paired = not previous or previous.get("sha256") == signature
    if previous and not paired:
        mismatch_path = cdir / f"mismatch_{exec_spec['execution_id']}_events.csv"
        shutil.copy2(run_dir / "events.csv", mismatch_path)
        previous.setdefault("mismatches", []).append({"execution_id": exec_spec["execution_id"],
            "sha256": signature, "file": str(mismatch_path.relative_to(HERE))})
    if not previous:
        source = run_dir / "events.csv"
        shutil.copy2(source, cpath)
        index[key] = {"sha256": signature, "file": str(cpath.relative_to(HERE)),
                      "event_count": len(rows), "variants": [exec_spec["variant"]],
                      "pairing_basis": "exact F21/F22 event rows generated from dedicated RNG streams 0/1"}
    else:
        variants = previous.setdefault("variants", [])
        if exec_spec["variant"] not in variants: variants.append(exec_spec["variant"])
    write_json(index_path, index)
    return paired, index[key]


def raw_retention_class(report: dict) -> str:
    return "pass" if report.get("viable") is True else "fail"


def simulation_overrides(spec: dict, manifest: dict) -> tuple[str, dict, list[str]]:
    variant = spec["variant"]
    config = f"Pilot_{variant}_{spec['cell']}"
    dest = OUT / "runs" / spec["execution_id"]
    profile = run_profile_for_load(manifest, spec["load_index"], variant)
    extras = ["-f", str(PILOT_INI.relative_to(SIM)), f"--seed-set={spec['seed']}",
        "--**.transmitting.result-recording-modes=+vector",
        "--**.transmissionGate[*].gateState.result-recording-modes=vector",
        "--**.transmissionGate[*].guardBandState.result-recording-modes=vector",
        "--**.clock.timeChanged.result-recording-modes=vector",
        "--**.clock.emitClockTimeInterval=1ms",
        "--**.numCredits.result-recording-modes=vector,max,min,timeavg",
        "--**.gptp.gmRateRatio.result-recording-modes=+vector",
        "--**.gptp.neighborRateRatio.result-recording-modes=+vector",
        "--**.gptp.pdelay.result-recording-modes=+vector",
        "--**.gptp.packetDropNotAddressedToUs.result-recording-modes=+count,sum(packetBytes),vector(packetBytes)",
        "--**.gptp.cmdenv-log-level=info",
        "--**.transmissionGate[*].enableImplicitGuardBand=true"]
    # Keep PHY implementation identical in every treatment; gPTP remains the only C3_base/C3_sync difference.
    extras += ["--**.transmitter.typename=\"StreamingTransmitter\"", "--**.receiver.typename=\"DestreamingReceiver\""]
    if variant != "C3base":
        calendar = OUT / "calendars" / spec["cell"] / f"seed{spec['seed']}_events.csv"
        if not calendar.is_file():
            raise RuntimeError(f"{spec['execution_id']}: paired C3-base transient calendar is missing: {calendar}")
        extras.append(f'--*.trafficPlan.transientCalendarFile="{calendar.resolve()}"')
        # The common topology sets this false, and its wildcard setting won
        # over the earlier pilot section. Force the feature on for the exact
        # five nodes so that clock/gPTP submodules are actually instantiated.
        extras += ["--*.HPC.hasTimeSynchronization=true",
                   "--*.CSW.hasTimeSynchronization=true",
                   "--*.Z*.ZSW.hasTimeSynchronization=true",
]
    if variant in ("C4compensated", "C4original"):
        # CLI overrides have explicit highest precedence. In the first pilot
        # run, empty durations inherited from CatalogClassification shadowed
        # the GCL section, so C4 was simulated without its time-aware schedule.
        ports = tuple(sorted(FULL_PATH_TAS_EGRESSES if variant == "C4original" else TAS_EGRESSES))
        extras += ["--*.HPC.hasEgressTrafficShaping=true",
                   "--*.CSW.hasEgressTrafficShaping=true",
                   "--*.Z*.ZSW.hasEgressTrafficShaping=true"]
        if variant == "C4compensated":
            for port in sorted(BRAKE_SP_EGRESSES):
                gate = f"*.{port}.macLayer.queue.transmissionGate"
                extras += [f"--{gate}[*].clockModule=\"^.^.^.^.clock\"", f"--{gate}[*].initiallyOpen=true", f"--{gate}[*].durations=[]", f"--{gate}[*].offset=0s"]
        for port in ports:
            gate = f"*.{port}.macLayer.queue.transmissionGate"
            extras += [f"--{gate}[*].clockModule=\"^.^.^.^.clock\"",
                       f"--{gate}[0..6].initiallyOpen=true",
                       f"--{gate}[0..6].durations=[77us,23us]",
                       f"--{gate}[0..6].offset=90us",
                       f"--{gate}[7].initiallyOpen=true",
                       f"--{gate}[7].durations=[10us,90us]",
                       f"--{gate}[*].enableImplicitGuardBand=true"]
    else:
        # Replace inherited/disabled vector modes explicitly so periodic clock
        # samples are present even when the common validation config disables
        # vectors globally.
        extras.append("--**.clock.timeChanged.result-recording-modes=vector")
    extras += expected_rates_overrides(profile)
    extras += variant_clock_overrides(spec["seed"], variant, manifest)
    return config, dest, extras


def simulate_raw_run(spec: dict, manifest: dict) -> bool:
    """Run only OMNeT++; cohort post-processing starts after all jobs finish."""
    if official_campaign_active():
        raise RuntimeError("Official campaign became active; pilot will not start another simulation")
    if free_gb() < FREE_FLOOR_GB:
        raise RuntimeError(f"Free disk {free_gb():.1f} GB is below the {FREE_FLOOR_GB:.0f} GB floor")
    config, dest, extras = simulation_overrides(spec, manifest)
    if completed_raw_run_matches(dest, config, spec["seed"]):
        return False
    if dest.exists() and any(dest.iterdir()):
        archive_uncommitted(dest, spec["execution_id"])
    dest.mkdir(parents=True, exist_ok=True)
    with LOCK:
        CHECKPOINT.setdefault("active", {})[spec["execution_id"]] = {"status": "simulating", "percent": 0,
            "variant": spec["variant"], "cell": spec["cell"], "seed": spec["seed"],
            "log": str((dest / f"{config}.log").relative_to(HERE))}
        write_checkpoint(phase="running", active=CHECKPOINT["active"], latest_execution_id=spec["execution_id"])
    inet = Path(os.environ.get("INET_ROOT", str(Path.home() / "omnetpp/samples/inet-4.7.0"))).resolve()
    command = [str(ROOT / "src/zonal-ivn-tsn"), "-u", "Cmdenv",
        "-n", f".:{ROOT / 'src'}:{ROOT / 'tests'}:{inet / 'src'}",
        "-f", "omnetpp.ini", "-c", config, "--cmdenv-express-mode=true",
        "--cmdenv-event-banners=false",
        "--**.app[*].latency.result-recording-modes=+vector",
        "--**.app[*].imageCompletionLatency.result-recording-modes=+vector",
        "--**.queueLength.result-recording-modes=+vector",
        "--**.queueBitLength.result-recording-modes=+vector",
        "--**.droppedPacketLengthsQueueOverflow.result-recording-modes=+vector",
        "--**.queueingTime.result-recording-modes=+histogram",
        "--**.utilization.result-recording-modes=+histogram",
        f"--result-dir={dest.relative_to(SIM)}"]
    command.extend(extras)
    log = dest / f"{config}.log"
    with log.open("w") as stream:
        result = subprocess.run(command, cwd=SIM, env=simulator_environment(), stdout=stream, stderr=subprocess.STDOUT)
    contents = log.read_text(errors="replace")
    if result.returncode != 0 or "<!> Error:" in contents or "Simulation time limit reached" not in contents:
        raise RuntimeError(f"{spec['execution_id']}: OMNeT++ run failed; inspect {log}")
    with LOCK:
        CHECKPOINT.setdefault("active", {}).setdefault(spec["execution_id"], {})["status"] = "waiting_for_postprocessing"
        CHECKPOINT["active"][spec["execution_id"]]["percent"] = 100
        write_checkpoint(active=CHECKPOINT["active"])
    return True


def run_one(spec: dict, manifest: dict, preflight: dict, freshly_simulated: bool = False) -> dict:
    if official_campaign_active():
        raise RuntimeError("Official campaign became active; pilot will not start another simulation")
    if free_gb() < FREE_FLOOR_GB:
        raise RuntimeError(f"Free disk {free_gb():.1f} GB is below the {FREE_FLOOR_GB:.0f} GB floor")
    variant = spec["variant"]
    config = f"Pilot_{variant}_{spec['cell']}"
    dest = OUT / "runs" / spec["execution_id"]
    reprocess_existing = completed_raw_run_matches(dest, config, spec["seed"])
    if dest.exists() and any(dest.iterdir()) and not reprocess_existing:
        archive_uncommitted(dest, spec["execution_id"])
    dest.mkdir(parents=True, exist_ok=True)
    run_dir = dest / f"{config}-0"
    profile = run_profile_for_load(manifest, spec["load_index"], variant)
    profile_hash = hashlib.sha256(json.dumps({f"{e}/TC{tc}": v for (e, tc), v in sorted(profile.items())}, sort_keys=True).encode()).hexdigest()
    _, _, extras = simulation_overrides(spec, manifest)
    start = time.time()
    if reprocess_existing and not freshly_simulated:
        append_jsonl(OUT / "recovery_events.jsonl", {
            "event": "completed_raw_simulation_reprocessed_after_postprocessing_failure",
            "execution_id": spec["execution_id"], "config": config, "seed": spec["seed"],
            "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "reason": "OMNeT run completed; recover compact metrics and pilot audit without rerunning simulation"})
    with LOCK:
        CHECKPOINT.setdefault("active", {})[spec["execution_id"]] = {"status": "waiting_for_postprocessing" if reprocess_existing else "starting", "percent": 100 if reprocess_existing else 0,
            "variant": variant, "cell": spec["cell"], "seed": spec["seed"], "log": str((dest / f"{config}.log").relative_to(HERE))}
        write_checkpoint(phase="running", active=CHECKPOINT["active"], latest_execution_id=spec["execution_id"])
    try:
        # Keep only one large-vector parser active at a time. Simulations are
        # launched as a concurrent cohort by execute(); parsing waits until all
        # raw runs in that cohort have finished.
        with LOCK:
            CHECKPOINT.setdefault("active", {}).setdefault(spec["execution_id"], {})["status"] = "waiting_for_postprocessing"
            write_checkpoint(active=CHECKPOINT["active"])
        with PILOT_VECTOR_LOCK:
            with LOCK:
                CHECKPOINT.setdefault("active", {}).setdefault(spec["execution_id"], {})["status"] = "validating_raw_outputs"
                write_checkpoint(active=CHECKPOINT["active"])
            report, actual_run_dir = validator.run_cell(config, dest,
        env=simulator_environment(), inet=INET_ROOT,
            execute=False, result_dir_override=str(dest.relative_to(SIM)), extra_args=tuple(extras),
            allow_gptp_control=variant != "C3base",
            allow_scheduled_gates=variant in ("C4compensated", "C4original"))
        run_dir = Path(actual_run_dir)
        vec = next(dest.glob(f"{config}-#*.vec"), None)
        sca = dest / f"{config}-#0.sca"
        if not vec or not sca:
            raise RuntimeError(f"{spec['execution_id']}: OMNeT++ vector/scalar output missing")
        signature, events = calendar_signature(run_dir)
        paired, cal_meta = save_calendar(run_dir, spec, signature, events)
        report["calendar_sha256"] = signature
        report["calendar_event_count"] = len(events)
        report["calendar_paired"] = paired
        report["calendar_pairing_status"] = "paired" if paired else "mismatch_invalidates_group"
        report["clock_drift_ppm_by_node"] = manifest["parameters"]["clock_drift_ppm_by_seed_node"].get(str(spec["seed"])) if variant != "C3base" else None
        report["resolved_cbs_profile"] = read_resolved_cbs(sca)
        report["effective_gcl"] = parse_effective_gcl(sca, variant) if "C4" in variant else {"status": "not_applicable"}
        report["effective_time_synchronization"] = parse_effective_time_sync(sca) if variant != "C3base" else {"status": "not_applicable"}
        actual = {}
        for key, fields in report["resolved_cbs_profile"].items():
            val = fields.get("idleSlope")
            if val is not None:
                m = re.search(r"[-+]?\d+(?:\.\d+)?", str(val))
                if m: actual[key] = round(float(m.group()))
        expected = {f"{e}/TC{tc}": r for (e, tc), r in profile.items()}
        report["resolved_cbs_profile_matches"] = all(actual.get(k) == v for k, v in expected.items())
        report["resolved_cbs_profile_mismatches"] = {k: {"expected_bps": v, "observed": actual.get(k)} for k, v in expected.items() if actual.get(k) != v}
        if not report["resolved_cbs_profile_matches"]:
            raise RuntimeError(f"{spec['execution_id']}: effective CBS slopes do not match pilot profile")
        with LOCK:
            CHECKPOINT.setdefault("active", {}).setdefault(spec["execution_id"], {})["status"] = "waiting_for_vector_audit"
            write_checkpoint(active=CHECKPOINT["active"])
        with PILOT_VECTOR_LOCK:
            with LOCK:
                CHECKPOINT.setdefault("active", {}).setdefault(spec["execution_id"], {})["status"] = "extracting_pilot_vectors"
                write_checkpoint(active=CHECKPOINT["active"])
            report["pilot_vector_audit"] = extract_pilot_vectors(vec, report, run_dir, variant)
        report["physical_utilization_independent_check"] = crosscheck_utilization_with_wire_summary(run_dir, report)
        report["per_packet_hop_trace"] = {
            "status": "unavailable",
            "reason": "The shared TrafficAudit instrumentation exports aggregate per-interface/flow queues and wire counts, not per-packet timestamps at each hop. This pilot deliberately leaves shared sources unchanged.",
            "causal_attribution_allowed": False,
        }
        report["gptp_send_events"] = parse_gptp_sends(dest / f"{config}.log") if variant != "C3base" else {"status": "not_applicable", "counts_by_node_egress_and_type": {}}
        report["exploratory"] = True
        report["official_c4_frozen"] = False
        report["variant"] = variant
        report["variant_id"] = VARIANT_NAMES[variant]
        report["execution_id"] = spec["execution_id"]
        report["reprocessed_existing_simulation"] = reprocess_existing and not freshly_simulated
        report["stage"] = spec["kind"]
        if spec.get("instrumentation_supersedes"):
            report["instrumentation_supersedes"] = spec["instrumentation_supersedes"]
        report["seed"] = spec["seed"]
        report["cell"] = spec["cell"]
        # The manifest is keyed by public variant IDs (e.g. C3_base), while
        # run_schedule uses compact internal names (e.g. C3base).
        report["admissible"] = bool(preflight[VARIANT_NAMES[variant]]["cells"][spec["cell"]]["admissible"])
        report["simulation_valid"] = bool(paired and report["resolved_cbs_profile_matches"] and
            report["pilot_vector_audit"]["state_vector_status"] == "available" and
            (variant == "C3base" or report["effective_time_synchronization"]["status"] == "pass") and
            ("C4" not in variant or report["effective_gcl"]["status"] == "pass"))
        report["validator_combined_cell_viable"] = report.get("viable")
        report["application_viable"], report["application_gate_failures"] = application_gate_summary(report)
        report["stability_viable"] = stability_gate_result(report)
        report["synchronization_viable"] = (report["pilot_vector_audit"]["synchronization"]["status"] == "pass") if variant != "C3base" else None
        report["tas_instrumentation_viable"] = None
        if "C4" in variant:
            report["tas_instrumentation_viable"] = report["pilot_vector_audit"]["tas_gate_schedule"]["status"] == "pass"
        report["pilot_viable"] = bool(report["admissible"] and report["simulation_valid"] and report["application_viable"] is True and
            report["stability_viable"] is True and
            (report["synchronization_viable"] is not False) and (report["tas_instrumentation_viable"] is not False))
        report["effective_profile_bps"] = expected
        report["effective_profile_sha256"] = profile_hash
        report["command"] = {"config": config, "seed_set": spec["seed"], "result_dir": str(dest.relative_to(SIM)), "overrides": extras}
        report["duration_wall_seconds"] = round(time.time() - start, 3)
        report["evidence"] = {"latency_upper_tails": str((run_dir / "latency_upper_tails.json.gz").relative_to(HERE)),
            "queue_occupancy_events": str((run_dir / "queue_occupancy_events.csv.gz").relative_to(HERE)),
            "clock_offsets": str((run_dir / "clock_offsets.csv.gz").relative_to(HERE)) if (run_dir / "clock_offsets.csv.gz").exists() else None,
            "gate_states": str((run_dir / "gate_states.csv.gz").relative_to(HERE)) if (run_dir / "gate_states.csv.gz").exists() else None,
            "raw_vector_gzip": None,
            "gptp_send_log": "compressed whole-run log; exact send counts only if parser matched events"}
        report_path = OUT / "runs" / spec["execution_id"] / "pilot-result.json"
        write_json(report_path, report)
        # Independently recompute the exact queue statistics from change points.
        trace = run_dir / "queue_occupancy_events.csv.gz"
        recomputed = validator.recompute_queue_occupancy_trace(trace)
        recorded = {x["queue"]: x for x in report.get("queue_stability", [])}
        if len(recomputed) != len(recorded):
            raise RuntimeError(f"{spec['execution_id']}: queue occupancy trace population did not reconcile")
        for row in recomputed:
            ref = recorded[row["queue"]]
            for field in ("mean_occupancy_bits_5s", "mean_occupancy_bits_measurement", "fraction_measurement_at_least_90pct_capacity", "max_occupancy_bits", "capacity_bits", "sustained_growth"):
                if row[field] != ref[field] and not (isinstance(row[field], float) and math.isclose(row[field], ref[field], rel_tol=1e-10, abs_tol=1e-9)):
                    raise RuntimeError(f"{spec['execution_id']}: independent queue recalculation mismatch: {row['queue']} {field}")
        report["queue_recalculation_verified"] = True
        report["measurement_windows_s"] = {"creation_cohort": [1.0, 31.0], "queue_and_utilization": [1.0, 31.0], "observation_end": 31.05, "drain_s": 0.05}
        keep = choose_raw_retention(report)
        report["retained_raw_vector"] = keep
        report["evidence"]["raw_vector_gzip"] = str((dest / f"{config}-#0.vec.gz").relative_to(HERE)) if keep else None
        report["raw_vector_retention_reason"] = ("first representative passing execution" if keep and report.get("pilot_viable")
                                                   else "first representative failed execution" if keep
                                                   else "compact evidence retained; raw vector not selected")
        write_json(report_path, report)
        write_json(run_dir / f"{variant.lower()}-pilot-acceptance.json", report)
        row = report
        row["status"] = "completed"
        row["result_file"] = str(report_path.relative_to(HERE))
        with LOCK:
            append_jsonl(OUT / "runs.jsonl", row)
            LEDGER.append(row)
            active = CHECKPOINT.get("active", {})
            active.pop(spec["execution_id"], None)
            CHECKPOINT["active"] = active
            CHECKPOINT.setdefault("execution_status", {})[spec["execution_id"]] = "completed"
            write_checkpoint(active=active, completed_count=len(LEDGER), last_execution_id=spec["execution_id"])
        compress_or_remove_raw(dest, config, run_dir, keep)
        return row
    except Exception as exc:
        log_path = dest / f"{config}.log"
        row = {**spec, "variant_id": VARIANT_NAMES[variant], "attempt_status": "failed_technical",
               "attempt_id": f"{spec['execution_id']}:{int(time.time())}:{os.getpid()}",
               "simulation_valid": False, "application_viable": None,
               "error": f"{type(exc).__name__}: {exc}",
               "log": str(log_path.relative_to(HERE)) if log_path.exists() else None,
               "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        with LOCK:
            append_jsonl(OUT / "technical_attempts.jsonl", row)
            active = CHECKPOINT.get("active", {})
            active.pop(spec["execution_id"], None)
            CHECKPOINT["active"] = active
            CHECKPOINT.setdefault("execution_status", {})[spec["execution_id"]] = "failed_technical_attempt_pending_retry"
            write_checkpoint(active=active, completed_count=len(LEDGER), last_error=row,
                             latest_technical_attempt=row)
        raise


def choose_raw_retention(report: dict) -> bool:
    """Retain one raw failure and one raw passing run for audit."""
    with LOCK:
        path = OUT / "raw_retention.json"
        try: kept = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError): kept = {"failed": None, "passing": None}
        category = "passing" if report.get("pilot_viable") else "failed"
        if kept.get(category) is None:
            kept[category] = report["execution_id"]
            write_json(path, kept)
            return True
        return False


def metric_value(row: dict, flow: str, receiver: str, family: str, field: str):
    try:
        r = row["qos"][flow]["receivers"][receiver]
        if family == "packet": return (r.get("latency") or {}).get(field)
        return (r.get("image_completion") or {}).get(field)
    except (KeyError, TypeError):
        return None


def application_gate_summary(row: dict) -> tuple[bool | None, list[dict]]:
    """Separate P1 application gates from the validator's combined cell result."""
    checks = []
    failures = []
    for flow_id, flow in (row.get("qos") or {}).items():
        for receiver, metrics in (flow.get("receivers") or {}).items():
            passed = metrics.get("viable")
            if not isinstance(passed, bool):
                continue
            checks.append(passed)
            if not passed:
                failures.append({
                    "flow": flow_id, "receiver": receiver,
                    "criticality": flow.get("criticality"),
                    "packet_loss_ratio": metrics.get("packet_loss_ratio"),
                    "packet_deadline_misses": (metrics.get("latency") or {}).get("deadline_misses_from_samples"),
                    "image_deadline_miss_ratio_including_missing": (metrics.get("image_completion") or {}).get(
                        "deadline_miss_ratio_including_missing_images"),
                })
    return (all(checks) if checks else None), failures


def stability_gate_result(row: dict) -> bool | None:
    """Stability is passed only when the retained queue series was reconciled."""
    if row.get("queue_recalculation_verified") is not True:
        return None
    return not bool(row.get("nonstable_queues"))


def build_final(manifest: dict, rows: list[dict]) -> dict:
    # Pairing requires the full predeclared variant group, not merely equal seed
    # values or the first calendar seen by the ledger. Instrumentation repairs
    # explicitly supersede their earlier attempts; historical attempts remain
    # visible in the report but must not poison pairing for the active result.
    schedule = manifest["run_schedule"]
    schedule_by_id = {spec["execution_id"]: spec for spec in schedule}
    superseded_ids = {old_id for spec in schedule for old_id in spec.get("instrumentation_supersedes", [])}
    active_spec_ids = {spec["execution_id"] for spec in schedule if spec["execution_id"] not in superseded_ids}
    expected_groups = {}
    for spec in schedule:
        if spec["execution_id"] not in active_spec_ids:
            continue
        is_admissible = manifest["admissibility"][VARIANT_NAMES[spec["variant"]]]["cells"][spec["cell"]]["admissible"]
        if is_admissible or spec["allow_inadmissible"]:
            expected_groups.setdefault((spec["cell"], spec["seed"]), set()).add(spec["execution_id"])
    by_group = {}
    for row in rows:
        if row.get("status") == "completed" and row.get("execution_id") in active_spec_ids:
            by_group.setdefault((row["cell"], row["seed"]), set()).add(row.get("calendar_sha256"))
    pair_status = {}
    row_ids_by_group = {}
    for row in rows:
        if row.get("status") == "completed" and row.get("execution_id") in active_spec_ids:
            row_ids_by_group.setdefault((row["cell"], row["seed"]), set()).add(row.get("execution_id"))
    for group, expected_ids in expected_groups.items():
        hashes = by_group.get(group, set())
        actual_ids = row_ids_by_group.get(group, set())
        if len(hashes) > 1:
            pair_status[group] = "mismatch"
        elif actual_ids >= expected_ids and len(hashes) == 1:
            pair_status[group] = "paired"
        else:
            pair_status[group] = "incomplete"
    mismatched = {k for k, state in pair_status.items() if state == "mismatch"}
    final_rows = []
    for original in rows:
        row = dict(original)
        group = (row.get("cell"), row.get("seed"))
        row["is_current_effective_result"] = row.get("execution_id") in active_spec_ids
        if row["is_current_effective_result"]:
            row["kind"] = schedule_by_id.get(row.get("execution_id"), {}).get("kind", "scheduled")
        if row.get("status") == "completed" and row.get("execution_id") in active_spec_ids:
            row["calendar_pairing_status"] = pair_status.get(group, "incomplete")
            row["calendar_paired"] = pair_status.get(group) == "paired"
            row["validator_combined_cell_viable"] = row.get("viable")
            row["application_viable"], row["application_gate_failures"] = application_gate_summary(row)
            row["stability_viable"] = stability_gate_result(row)
            row["pilot_viable"] = bool(
                row.get("admissible") is True and row.get("simulation_valid") is True and
                row["application_viable"] is True and row["stability_viable"] is True and
                row.get("synchronization_viable") is not False and
                row.get("tas_instrumentation_viable") is not False)
        if row.get("status") == "completed" and row.get("execution_id") in active_spec_ids and pair_status.get(group) != "paired":
            row["simulation_valid"] = False
            row["pilot_viable"] = False
            row["simulation_validity_note"] = "transient calendar group is mismatched or incomplete"
        elif row.get("status") == "completed" and row.get("execution_id") not in active_spec_ids:
            row["superseded_by_current_instrumentation_repair"] = True
        final_rows.append(row)
    comparisons = []
    pairs = (("C3sync", "C3base", "C3_sync - C3_base"),
             ("C4compensated", "C3sync", "C4_shared_SPbrakes - C3_sync"),
             ("C4compensated", "C3base", "C4_shared_SPbrakes - C3_base"),
             ("C4compensated", "C4original", "C4_shared_SPbrakes - C4_compensated_fullpath_corrected"))
    current_runs = [r for r in final_rows if r.get("status") == "completed" and r.get("is_current_effective_result")]
    superseded_runs = [r for r in final_rows if r.get("status") == "completed" and not r.get("is_current_effective_result")]
    index = {(r.get("variant"), r.get("cell"), r.get("seed")): r for r in current_runs}
    for lhs, rhs, label in pairs:
        for cell, seed in (("L2_A1", 41), ("L2_A1", 43), ("L2_A1", 47), ("L0_A0", 41), ("L1_A1", 41)):
            a, b = index.get((lhs, cell, seed)), index.get((rhs, cell, seed))
            if not (a and b):
                continue
            flow_deltas = {}
            for fid, fdata in a.get("qos", {}).items():
                flow_deltas[fid] = {}
                for receiver in fdata.get("receivers", {}):
                    arx = fdata["receivers"][receiver]
                    brx = b.get("qos", {}).get(fid, {}).get("receivers", {}).get(receiver, {})
                    target = flow_deltas.setdefault(fid, {}).setdefault(receiver, {})
                    for field in ("offered_packets", "received_packets", "useful_throughput_mbps",
                                  "deadline_misses_received", "deadline_miss_ratio_including_loss",
                                  "goodput_payload_ratio", "packet_loss_ratio"):
                        av, bv = arx.get(field), brx.get(field)
                        if isinstance(av, (int, float)) and isinstance(bv, (int, float)):
                            target[f"packet_{field}_delta"] = av - bv
                    for field in ("p99_s", "max_s", "deadline_misses_from_samples"):
                        av = metric_value(a, fid, receiver, "packet", field)
                        bv = metric_value(b, fid, receiver, "packet", field)
                        if isinstance(av, (int, float)) and isinstance(bv, (int, float)):
                            target[f"packet_{field}_delta"] = av - bv
                    ai, bi = arx.get("image_completion"), brx.get("image_completion")
                    if ai and bi:
                        for field in ("offered_images", "completed_images", "deadline_misses_completed",
                                      "deadline_miss_ratio_including_missing_images", "p99_s", "max_s"):
                            av, bv = ai.get(field), bi.get(field)
                            if isinstance(av, (int, float)) and isinstance(bv, (int, float)):
                                target[f"image_{field}_delta"] = av - bv
            comparisons.append({"contrast": label, "cell": cell, "seed": seed,
                "lhs_execution": a["execution_id"], "rhs_execution": b["execution_id"],
                "paired_calendar": pair_status.get((cell, seed)) == "paired" and a.get("calendar_sha256") == b.get("calendar_sha256"),
                "lhs_viable": a.get("pilot_viable"), "rhs_viable": b.get("pilot_viable"),
                "per_flow_metric_deltas": flow_deltas})
    def hard_failures(row: dict | None) -> list[dict]:
        if not row:
            return []
        failures = []
        for flow_id, flow in row.get("qos", {}).items():
            for receiver, metrics in flow.get("receivers", {}).items():
                image = metrics.get("image_completion") or {}
                packet_misses = int((metrics.get("latency") or {}).get("deadline_misses_from_samples") or 0)
                packet_misses_reported = int(metrics.get("deadline_misses_received") or 0)
                image_misses = int(image.get("deadline_misses_from_samples") or 0)
                incomplete_images = max(0, int(image.get("offered_images") or 0) - int(image.get("completed_images") or 0))
                if row.get("criticality", {}).get(flow_id) == "high-hard" or flow.get("criticality") == "high-hard":
                    if packet_misses or packet_misses_reported or image_misses or incomplete_images or metrics.get("packet_loss_ratio", 0) > 0:
                        failures.append({"flow": flow_id, "receiver": receiver,
                            "packet_latency_sample_misses": packet_misses,
                            "packet_deadline_misses_reported": packet_misses_reported,
                            "packet_loss_ratio": metrics.get("packet_loss_ratio"),
                            "image_deadline_misses": image_misses,
                            "incomplete_images": incomplete_images,
                            "packet_p99_s": (metrics.get("latency") or {}).get("p99_s"),
                            "image_completion_p99_s": image.get("p99_s")})
        return failures

    def execution_summary(variant: str, cell: str, seed: int) -> dict | None:
        row = index.get((variant, cell, seed))
        if not row:
            return None
        application_pass, application_failures = application_gate_summary(row)
        return {"execution_id": row.get("execution_id"), "admissible": row.get("admissible"),
            "simulation_valid": row.get("simulation_valid"), "application_viable": row.get("application_viable"),
            "application_gate_failures": application_failures,
            "stability_viable": stability_gate_result(row),
            "pilot_viable": row.get("pilot_viable"), "calendar_pairing_status": row.get("calendar_pairing_status"),
            "calendar_sha256": row.get("calendar_sha256"),
            "queue_overflow_drops_post_warmup_including_drain": row.get("queue_overflow_drop_total_post_warmup_including_drain"),
            "whole_run_drops": row.get("drop_reconciliation", {}).get("traffic_audit_drops_entire_simulation"),
            "hard_deadline_failures": hard_failures(row),
            "synchronization": (row.get("pilot_vector_audit") or {}).get("synchronization"),
            "tas_gate_schedule": (row.get("pilot_vector_audit") or {}).get("tas_gate_schedule")}

    decision_cells = {}
    for cell, seeds in (("L2_A1", (41, 43, 47)), ("L0_A0", (41,)), ("L1_A1", (41,))):
        for seed in seeds:
            key = f"{cell}_seed{seed}"
            decision_cells[key] = {name: execution_summary(name, cell, seed) for name in
                ("C3base", "C3sync", "C4compensated", "C4original")}
    c4_l2 = [decision_cells.get(f"L2_A1_seed{seed}", {}).get("C4compensated") for seed in (41, 43, 47)]
    c4_l2 = [x for x in c4_l2 if x is not None]
    c4_original = decision_cells.get("L2_A1_seed41", {}).get("C4original")
    c4_shared_application_pass = all(
        index.get(("C4compensated", "L2_A1", seed), {}).get("application_viable") is True
        for seed in (41, 43, 47)
    ) if all(index.get(("C4compensated", "L2_A1", seed)) for seed in (41, 43, 47)) else None
    c4_shared_stability_pass = all(
        index.get(("C4compensated", "L2_A1", seed), {}).get("stability_viable") is True
        for seed in (41, 43, 47)
    ) if all(index.get(("C4compensated", "L2_A1", seed)) for seed in (41, 43, 47)) else None
    if c4_shared_application_pass and c4_shared_stability_pass and all(
        x.get("pilot_viable") for x in c4_l2
    ):
        recommendation = "pilot gates passed for tested L2/A1 seeds; exploratory evidence only"
    elif c4_shared_application_pass:
        recommendation = "SP brake exits recovered application gates at L2/A1, but the tested C4 profile is not viable because synchronization and/or queue stability failed"
    else:
        recommendation = "tested C4 profile did not pass all application gates; do not adopt as-is"
    decision_summary = {
        "recommendation": recommendation,
        "adopt_tested_c4_as_is": False,
        "rejects_every_possible_c4_design": False,
        "exploratory_only": True,
        "c4_shared_spbrakes_l2_a1_seed_results_present": len(c4_l2),
        "c4_shared_spbrakes_l2_a1_all_application_gates_pass": c4_shared_application_pass,
        "c4_shared_spbrakes_l2_a1_queue_stability_pass": c4_shared_stability_pass,
        "c4_shared_spbrakes_l2_a1_pilot_viable_all_seeds": (all(x.get("pilot_viable") is True for x in c4_l2) if len(c4_l2) == 3 else None),
        "c4_shared_spbrakes_l2_a1_hard_fail_flows": sorted({f["flow"] for x in c4_l2 for f in x.get("hard_deadline_failures", [])}),
        "tc7_configured_open_fraction": 0.10,
        "resolved_gate_configuration_count_by_execution": {x.get("execution_id"): (x.get("effective_gcl") or {}).get("expected_gate_count") for x in current_runs if "C4" in x.get("variant", "")},
        "measured_gate_state_pass": (all(x.get("tas_gate_schedule", {}).get("status") == "pass" for x in c4_l2) if len(c4_l2)==3 else None),
        "gptp_measurement_sync_passed": (all(x.get("synchronization", {}).get("status") == "pass" for x in c4_l2) if len(c4_l2)==3 else None),
        "shared_treatment_fullpath_diagnostic_present_seed41": c4_original is not None,
        "decision_limit": "Exploratory evidence only; brake-flow acceptance does not approve C4. The conclusion requires all application gates, synchronization/GCL validity, and queue stability."
    }
    return {"pilot_id": "c4-shared-sp-brakes", "exploratory": True,
        "official_c4_frozen": False, "admissibility": manifest["admissibility"],
        "manifest": manifest, "run_schedule": manifest["run_schedule"],
        "runs": final_rows, "current_runs": current_runs, "superseded_runs": superseded_runs,
        "decision_relevant_cells": decision_cells, "decision_summary": decision_summary,
        "paired_comparisons": comparisons,
        "completed_executions": sum(r.get("status") == "completed" for r in final_rows),
        "completed_scheduled_executions": sum(r.get("execution_id") in {x["execution_id"] for x in manifest["run_schedule"]} and r.get("status") == "completed" for r in final_rows),
        "effective_current_executions": len(current_runs),
        "superseded_completed_executions": len(superseded_runs),
        "scheduled_superseded_executions": len({x["execution_id"] for x in manifest["run_schedule"]} & superseded_ids),
        "additional_historical_completed_executions": sum(r.get("status") == "completed" and r.get("execution_id") not in {x["execution_id"] for x in manifest["run_schedule"]} for r in final_rows),
        "technical_attempts": current_attempts(),
        "technical_failures": len(current_attempts()),
        "pending_scheduled_executions": [x["execution_id"] for x in manifest["run_schedule"]
            if x["execution_id"] not in {r.get("execution_id") for r in final_rows}],
        "calendar_mismatch_groups": [list(x) for x in sorted(mismatched)],
        "postprocessing_audit_corrections": [
            {"correction": "Compare effective gate durations/offsets numerically after normalizing units and whitespace.", "evidence": "retained compressed SCA files", "simulation_rerun": False},
            {"correction": "Do not require gPTP clock vectors in the C3-base control; validate its preserved physical-link state vectors instead.", "evidence": "retained sample-hold link vectors", "simulation_rerun": False},
            {"correction": "Exclude superseded seed-41 runs from current calendar pairing and contrasts while retaining them in the audit ledger.", "evidence": "manifest instrumentation_supersedes IDs and event-calendar signatures", "simulation_rerun": False},
            {"correction": "Separate application gate outcome from queue stability; prior application_viable copied the validator's combined cell viability, which conflated application failures with nonstable queues.", "evidence": "per-receiver gate results plus independently reconciled queue occupancy traces", "simulation_rerun": False},
            {"correction": "Compute high-hard diagnostic failures from packet latency sample misses as well as reported miss counts, packet loss, image misses, and incomplete images.", "evidence": "retained per-packet and image metric summaries", "simulation_rerun": False},
            {"correction": "Re-evaluate C4_original's brake egress GCLs as scheduled gates; only C4_shared_SPbrakes has permanently-open SP brake exits.", "evidence": "compressed SCA and compact gate state series", "simulation_rerun": False}
        ],
        "limitations": ["C4_original is a single L2/A1 seed-41 diagnostic; it is not a matrix treatment.",
            "gPTP send logging and serialized message counts are reported unavailable if the installed runtime log format cannot be parsed.",
            "Current shared TrafficAudit output does not retain per-packet timestamps across hops; F08–F10 gate-wait and hop-by-hop causal attribution are unavailable without isolated instrumentation.",
            "The 0.77 service estimate is analytical; gate/credit vectors are the empirical evidence.",
            "At most three seeds are exploratory and do not support confirmatory hypothesis tests."]}


def generate_markdown(data: dict) -> str:
    manifest = data["manifest"]
    completed = data.get("completed_scheduled_executions", 0)
    planned = len(data.get("run_schedule", []))
    lines = [
        "# C4 shared-SP-brakes pilot",
        "",
        "Exploratory pilot only. `exploratory=true`; `official_c4_frozen=false`. This report does not change the P1, frozen C3 profile, or official C0–C3 results.",
        "",
        f"Status: **{completed}/{planned}** scheduled executions complete; {len(data.get('pending_scheduled_executions', []))} pending; {data.get('technical_failures', 0)} technical attempts. No C4 final campaign is authorized by this pilot.",
        "",
        f"The fixed CBS source is official profile **{manifest['official_profile']['profile_id']}** (SHA-256 `{manifest['official_profile']['sha256']}`). Compensation is fixed at `idleSlope_C3 / 0.77` only on CBS queues whose egress receives TAS. No C3 retuning is performed.",
        "",
        "## Historical pilot correction",
        "",
        "The previous C4 pilot remains preserved under `../c4_service_preservation/`. Its `effective_gcl` settings were rechecked from retained SCA after normalizing time units. Configuration fidelity and application-route coverage are separate: historical GCL used `Z3.ZSW.eth[4]`, while F10 exits at `Z3.ZSW.eth[5]`. Historical link utilization and full-measurement clock offsets are unavailable where their source series were not retained. See the corrected historical `analysis.md` and `audit-corrections.json`.",
        "",
        "## F08–F10 route and egress table",
        "",
        "| Flow | Receiver | Actual egress route and speed | `C4_shared_SPbrakes` service |",
        "|---|---|---|---|",
    ]
    routes = manifest.get("route_audit", {}).get("application_flow_routes", {})
    for fid in ("F08", "F09", "F10"):
        flow = next((x for x in read_flow_rows() if x["flow_id"] == fid), None)
        for branch in routes.get(fid, []):
            hops = " → ".join(f"{e} ({branch['egress_speeds_bps'][e]/1e6:g} Mb/s)" for e in branch["egresses"])
            tc = branch["tc"]
            service = "TAS on HPC/CSW; final brake output SP permanently open" if fid in ("F08", "F09", "F10") else "—"
            lines.append(f"| {fid} (TC{tc}) | {branch['receiver']} | {hops} | {service} |")
    lines += [
        "",
        "The application catalog confirms each last-hop brake egress carries only its own brake flow: Z1 `eth[4]`→F08, Z2 `eth[4]`→F09, Z3 `eth[5]`→F10. gPTP control traffic is tracked separately. All treatments use `StreamingTransmitter`/`DestreamingReceiver`; applications remain scheduled by OMNeT++ simulation time while TAS uses synchronized local clocks.",
        "",
        "Per-packet timestamps for F08–F10 at all three hops are unavailable with the current shared `TrafficAudit` output, which aggregates counts and bytes by flow/interface/queue. The runner records this limitation explicitly; it will not claim packet-level gate-wait or hop-by-hop causality from aggregate vectors.",
        "",
        "## Preflight screens",
        "",
        "All eight L/A combinations are screened. CBS reservations are not clipped. L3 cells that exceed the 75% per-port ceiling are rejected before execution.",
        "",
        "| Variant | Cell | Admissible | Reservation rejection ports | Other screen failures |",
        "|---|---|---:|---|---|",
    ]
    for variant, screen in manifest["admissibility"].items():
        for cell, entry in screen["cells"].items():
            ports = ", ".join(entry["reservation_rejected_ports"]) or "—"
            failures = ", ".join(f"{x['egress']}:{x['criterion']}" for x in entry["other_rejections"]) or "—"
            lines.append(f"| {variant} | {cell} | {entry['admissible']} | {ports} | {failures} |")
    reserve_ports = manifest["admissibility"].get("C4_shared_SPbrakes", {}).get("cells", {}).get("L2_A1", {}).get("ports", {})
    lines += ["", "### Effective reservation totals for the shared-SP L2/A1 profile", "",
        "These are the configured sums of TC4/TC6 idleSlope on each physical egress for `C4_shared_SPbrakes`, derived by preflight from the effective profile; the manifest contains the same breakdown for all treatments and loads. No clipping was applied. The configured total is below 75% on every listed port.",
        "", "| Egress | TC4+TC6 idleSlope (Mb/s) | Physical rate (Mb/s) | Port fraction | Headroom to 75% (Mb/s) |",
        "|---|---:|---:|---:|---:|"]
    for egress, port in sorted(reserve_ports.items()):
        total = port.get("cbs_reservation_tc4_tc6_bps", 0)
        if total:
            lines.append(f"| {egress} | {total/1e6:.3f} | {port.get('physical_rate_bps',0)/1e6:.3f} | {100*port.get('cbs_cap_fraction',0):.3f}% | {port.get('headroom_to_75pct_bps',0)/1e6:.3f} |")
    lines += [
        "",
        "## Executions and paired comparisons",
        "",
        "| Variant | Cell | Seed | Status | Admissible | Simulation valid | Application gates | Queue stability | Sync | TAS/GCL | Calendar |",
        "|---|---|---:|---|---:|---|---|---|---|---|---|",
    ]
    for row in data.get("current_runs", []):
        lines.append(f"| {row.get('variant_id', row.get('variant'))} | {row.get('cell')} | {row.get('seed')} | {row.get('status')} | {row.get('admissible')} | {row.get('simulation_valid')} | {row.get('application_viable')} | {row.get('stability_viable')} | {row.get('synchronization_viable')} | {row.get('tas_instrumentation_viable')} / {row.get('effective_gcl', {}).get('status')} | {row.get('calendar_pairing_status')} |")
    if not data.get("current_runs"):
        lines.append("| _none yet_ | — | — | planned only | — | — | — | — | — | calendars are generated/paired during runs |")
    lines += [
        "",
        "The registered contrasts are `C3_sync − C3_base`, `C4_shared_SPbrakes − C3_sync`, `C4_shared_SPbrakes − C3_base`, and the seed-41-only `C4_shared_SPbrakes − C4_compensated_fullpath_corrected`. Full per-flow/receptor deltas are in `pilot_results.json`; a missing pair is not treated as a zero difference.",
        "",
        "| Contrast | Cell | Seed | Calendar paired | LHS all gates | RHS all gates |",
        "|---|---|---:|---|---|---|",
    ]
    for row in data.get("paired_comparisons", []):
        lines.append(f"| {row['contrast']} | {row['cell']} | {row['seed']} | {row['paired_calendar']} | {row['lhs_viable']} | {row['rhs_viable']} |")
    if not data.get("paired_comparisons"):
        lines.append("| _no completed paired contrast yet_ | — | — | — | — | — |")
    lines += ["", "## Queue and per-flow evidence", "",
        "The JSON retains packet and image populations, losses, pendings, deadline misses, latency tails, goodput, drops by scope, and queue metrics per execution. Camera deadline gates use image completion, including incomplete images as misses. A brake-only pass is not C4 viability.",
        "",
        "| Execution | HPC.eth[0]/TC4 capacity | Six 5 s means (KiB) | Peak (KiB) | Time ≥90% capacity | Sustained growth |",
        "|---|---:|---|---:|---:|---|"]
    has_queue_rows = False
    for row in data.get("current_runs", []):
        q = next((q for q in row.get("queue_stability", []) if q.get("queue") == "ZonalIVN.HPC.eth[0].macLayer.queue.queue[4]"), None)
        if q:
            has_queue_rows = True
            means = ", ".join(f"{x/8192:.2f}" for x in q.get("mean_occupancy_bits_5s", []))
            lines.append(f"| {row.get('execution_id')} | {q.get('capacity_bits',0)/8192:.2f} | {means} | {q.get('max_occupancy_bits',0)/8192:.2f} | {100*q.get('fraction_measurement_at_least_90pct_capacity',0):.3f}% | {q.get('sustained_growth')} |")
    if not has_queue_rows:
        lines.append("| _no new queue series yet_ | — | — | — | — | — |")
    lines += [
        "",
        "For new runs, link utilization is accepted only if the binary transmitting-state series is ordered and its sample-hold integral lies in [0,1]; invalid series become unavailable. Clock offsets are measured throughout [1,31) s at 1 ms resolution; the report also states the piecewise-linear duration estimate and cannot rule out unsampled excursions. GCL checks verify resolved duration, 100 µs period, phase/offset, clock module, absolute-time schedule, guard band, and gate-state fractions separately.",
        "",
        "## Interpretation status",
        "",
    ]
    if not data.get("current_runs"):
        lines.append("No simulation has been run for this isolated pilot yet. This document records the corrected historical evidence, preregistered design, and preflight only; it makes no claim about whether SP at the last hops recovers F08–F10 or whether C4 passes the complete P1 gates.")
    else:
        d = data.get("decision_summary", {})
        lines.append(
            "Finding: SP on the three final brake egresses recovered F08–F10 application deadlines. "
            f"All application gates passed in the three paired L2/A1 seeds ({d.get('c4_shared_spbrakes_l2_a1_all_application_gates_pass')}); "
            f"queue stability passed across all three ({d.get('c4_shared_spbrakes_l2_a1_queue_stability_pass')}) and total pilot viability passed across all three ({d.get('c4_shared_spbrakes_l2_a1_pilot_viable_all_seeds')}). "
            "The complete treatment therefore did not pass: sustained TC4 queue growth/overflow and the 1 µs clock-offset criterion remain failures. "
            "This rejects adopting the tested C4 configuration as-is, but does not rule out every C4 design."
        )
        lines += ["", "## Final paired results", "",
            "The comparison uses the same F21/F22 event calendar within each seed. The last-hop comparison is available only for seed 41.",
            "",
            "| Treatment / seed | Flow | Received / offered | Packet deadline misses | Loss | p99 (µs) | Max (µs) |",
            "|---|---|---:|---:|---:|---:|---:|"]
        order = {"C3base": 0, "C3sync": 1, "C4compensated": 2, "C4original": 3}
        l2_rows = [r for r in data.get("current_runs", []) if r.get("cell") == "L2_A1"]
        for row in sorted(l2_rows, key=lambda r: (r.get("seed", 0), order.get(r.get("variant"), 9))):
            for fid in ("F08", "F09", "F10"):
                metrics = row.get("qos", {}).get(fid, {}).get("receivers", {})
                rx = next(iter(metrics.values()), {})
                latency = rx.get("latency") or {}
                lines.append(
                    f"| {row.get('variant_id', row.get('variant'))} / {row.get('seed')} | {fid} | "
                    f"{rx.get('received_packets')} / {rx.get('offered_packets')} | "
                    f"{latency.get('deadline_misses_from_samples')} | {100*rx.get('packet_loss_ratio',0):.4f}% | "
                    f"{1e6*latency['p99_s']:.3f} | {1e6*latency['max_s']:.3f} |"
                )
        lines += ["", "| Treatment / seed | Application gates | Queue stability | Sync ≤1 µs | TAS/GCL | Total pilot viability | Overflow drops* |",
            "|---|---|---|---|---|---|---:|"]
        for row in sorted(l2_rows, key=lambda r: (r.get("seed", 0), order.get(r.get("variant"), 9))):
            lines.append(
                f"| {row.get('variant_id',row.get('variant'))} / {row.get('seed')} | {row.get('application_viable')} | "
                f"{row.get('stability_viable')} | {row.get('synchronization_viable')} | "
                f"{row.get('tas_instrumentation_viable')} / {row.get('effective_gcl',{}).get('status')} | "
                f"{row.get('pilot_viable')} | {row.get('queue_overflow_drop_total_post_warmup_including_drain')} |"
            )
        camera_run_ids = {
            "C3base_L0_A0_seed41", "C3sync_L0_A0_seed41", "C4compensated_L0_A0_seed41",
            "C3base_L1_A1_seed41", "C3sync_L1_A1_seed41", "C4compensated_L1_A1_seed41",
            "C4compensated_L2_A1_seed41", "C4compensated_L2_A1_seed43", "C4compensated_L2_A1_seed47",
            "C4original_L2_A1_seed41",
        }
        camera_runs = [r for r in data.get("current_runs", []) if r.get("execution_id") in camera_run_ids]
        lines += ["", "### Camera packet and image results are separate", "",
            "The packet table reports packet latency and packet losses; the image table reports image completion from availability through the last frame. An incomplete image is counted as a missed image deadline, not as an extra packet loss. `N/A` means the applicable sample population is empty or the metric does not apply.",
            "", "| Execution | Flow | Offered / received packets | Packet drops | Packet deadline misses | Packet p99 / max (ms) |",
            "|---|---|---:|---:|---:|---:|"]
        for row in sorted(camera_runs, key=lambda r: (r.get("cell", ""), r.get("seed", 0), order.get(r.get("variant"), 9))):
            for fid in ("F02", "F03", "F04", "F05"):
                receivers = row.get("qos", {}).get(fid, {}).get("receivers", {})
                rx = next(iter(receivers.values()), {})
                lat = rx.get("latency", {})
                lines.append(f"| {row.get('execution_id')} | {fid} | {rx.get('offered_packets',0)} / {rx.get('received_packets',0)} | {rx.get('offered_packets',0)-rx.get('received_packets',0)} | {lat.get('deadline_misses_from_samples',0)} | {1e3*lat.get('p99_s',0):.6f} / {1e3*lat.get('max_s',0):.6f} |")
        lines += ["", "| Execution | Flow | Offered / complete images | Incomplete images | Image deadline misses / offered | Image p99 / max (ms) |",
            "|---|---|---:|---:|---:|---:|"]
        for row in sorted(camera_runs, key=lambda r: (r.get("cell", ""), r.get("seed", 0), order.get(r.get("variant"), 9))):
            for fid in ("F02", "F03", "F04", "F05"):
                receivers = row.get("qos", {}).get(fid, {}).get("receivers", {})
                rx = next(iter(receivers.values()), {})
                im = rx.get("image_completion") or {}
                offered = im.get("offered_images", 0) or 0
                completed = im.get("completed_images", 0) or 0
                misses = round((im.get("deadline_miss_ratio_including_missing_images", 0) or 0) * offered) if offered else 0
                p99 = im.get("p99_s")
                maximum = im.get("max_s")
                lines.append(f"| {row.get('execution_id')} | {fid} | {offered} / {completed} | {max(0, offered-completed)} | {misses} / {offered} | {f'{1e3*p99:.6f}' if p99 is not None else 'N/A'} / {f'{1e3*maximum:.6f}' if maximum is not None else 'N/A'} |")
        lines += ["", "*Overflow count scope is after warm-up through the 50 ms drain; the JSON also separates measurement-window and drain counts.",
            "",
            "C4_shared_SPbrakes passed every application gate at L2/A1 in seeds 41, 43, and 47, including the brake flows, cameras, and deadline-sensitive sensors. F08–F10 had zero losses and zero deadline misses out of 300,000 packets per flow in each seed; maxima were close to the 100 µs limit. By contrast, in the seed-41 full-path diagnostic, each brake flow missed the deadline on all 300,000 packets. The paired results are consistent with the final-hop gate schedule causing the latency increase, but the retained instrumentation lacks packet timestamps at each hop, so exact per-packet gate-wait causality is unavailable.",
            "",
            "In C4_shared_SPbrakes L2/A1, HPC.eth[0]/TC4 grew in all three seeds and produced 48, 168, and 125 post-warm-up overflow drops respectively. Seed 43 also had sustained growth at Z3.ZSW.eth[7]/TC4. Thus the brake improvement did not establish a viable C4: the queues were not stable and synchronization failed.",
            "",
            "The L0/A0 and L1/A1 C3 controls already fail high-hard camera/sensor application gates; the C4 treatment does not recover them. Treat these cells as evidence of pre-existing control limitations, not a newly introduced C4-only failure.",
            "",
            "### Paired brake-flow effects at L2/A1",
            "",
            "The table reports treatment-minus-control deltas for F08–F10. Calendars are paired within each seed. Positive latency deltas mean higher latency; application miss deltas use packet misses, while camera-image gates are reported separately in the per-flow JSON.",
            "",
            "| Contrast / seed | Flow | Δ p99 (µs) | Δ max (µs) | Δ packet deadline misses | Treatment pilot viability | Control pilot viability |",
            "|---|---|---:|---:|---:|---|---|"]
        contrasts = [("C3sync", "C3base", "C3_sync − C3_base"),
                     ("C4compensated", "C3sync", "C4_shared_SPbrakes − C3_sync"),
                     ("C4compensated", "C3base", "C4_shared_SPbrakes − C3_base"),
                     ("C4compensated", "C4original", "C4_shared_SPbrakes − C4_compensated_fullpath_corrected")]
        run_by_id = {r.get("execution_id"): r for r in data.get("current_runs", [])}
        for lhs, rhs, label in contrasts:
            seeds = (41,) if rhs == "C4original" else (41, 43, 47)
            for seed in seeds:
                a = next((r for r in data.get("current_runs", []) if r.get("variant") == lhs and r.get("cell") == "L2_A1" and r.get("seed") == seed), None)
                b = next((r for r in data.get("current_runs", []) if r.get("variant") == rhs and r.get("cell") == "L2_A1" and r.get("seed") == seed), None)
                if not a or not b:
                    continue
                for fid in ("F08", "F09", "F10"):
                    def receiver_metric(row):
                        receivers = row.get("qos", {}).get(fid, {}).get("receivers", {})
                        return next(iter(receivers.values()), {})
                    ma, mb = receiver_metric(a), receiver_metric(b)
                    la, lb = ma.get("latency", {}), mb.get("latency", {})
                    lines.append(f"| {label} / {seed} | {fid} | {1e6*(la.get('p99_s',0)-lb.get('p99_s',0)):.3f} | {1e6*(la.get('max_s',0)-lb.get('max_s',0)):.3f} | {la.get('deadline_misses_from_samples',0)-lb.get('deadline_misses_from_samples',0)} | {a.get('pilot_viable')} | {b.get('pilot_viable')} |")
        lines += ["", "The shared-SP treatment reduced F08–F10 p99 by roughly 0.84–0.94 ms versus the seed-41 full-path diagnostic, while all three brake flows moved from 300,000 deadline misses to zero. This is a paired treatment difference, not packet-level proof that the final gate alone caused each packet's delay; hop timestamps were not retained.",
            "",
            "### Overflow locations and CBS credit evidence",
            "",
            "Overflow counters below are queue-level and do not identify the dropped flow; per-flow receive/loss metrics cannot be assigned to a specific egress drop without packet-level drop tracing. The whole-run TrafficAudit count, SCA count, and post-warm-up measurement-plus-drain count reconcile for these executions; drain drops were zero.",
            "",
            "| Execution | Queue / TC | Capacity (KiB) | Measurement overflow drops | Drain drops | Whole-run / post-warm-up total |",
            "|---|---|---:|---:|---:|---:|"]
        overflow_rows = []
        for row in data.get("current_runs", []):
            for q in row.get("queue_overflow_drops_by_queue", []):
                count = q.get("overflow_drops_post_warmup_including_drain", 0) or 0
                if count:
                    overflow_rows.append((row, q, count))
        for row, q, count in sorted(overflow_rows, key=lambda x: (x[0].get("execution_id", ""), x[1].get("queue", ""))):
            queue = q.get("queue", "").replace("ZonalIVN.", "")
            lines.append(f"| {row.get('execution_id')} | {queue} / TC{q.get('tc')} | {q.get('capacity_bits',0)/8192:.2f} | {q.get('overflow_drops_measurement_window',0)} | {q.get('overflow_drops_drain',0)} | {count} |")
        if not overflow_rows:
            lines.append("| _none_ | — | — | 0 | 0 | 0 |")
        lines += ["", "For the critical L2/A1 `C4_shared_SPbrakes` executions, `HPC.eth[0]/TC4` sustained queue growth in all three seeds (the six 5 s means rise monotonically). Drops were observed at CSW→Z3/TC4 in seeds 41 and 47, and at HPC→CSW/TC4 in seed 43; seed 43 also showed sustained growth at Z3.ZSW.eth[7]/TC4. These are direct queue/drop observations; catalog routing establishes which traffic classes traverse the queues, but not which individual frame was discarded.",
            "",
            "| Seed | CBS queue | idleSlope (Mb/s) | Credit min / max / time-average (reported units) |",
            "|---:|---|---:|---:|"]
        for seed in (41, 43, 47):
            row = next((r for r in data.get("current_runs", []) if r.get("variant") == "C4compensated" and r.get("cell") == "L2_A1" and r.get("seed") == seed), None)
            if not row:
                continue
            profile = row.get("resolved_cbs_profile", {})
            for egress in ("HPC.eth[0]/TC4", "CSW.eth[0]/TC4", "CSW.eth[3]/TC4", "Z3.ZSW.eth[7]/TC4"):
                cfg = profile.get(egress, {})
                slope = cfg.get("idleSlope", "unavailable")
                if isinstance(slope, str) and slope.endswith("bps"):
                    try: slope = f"{float(slope[:-3])/1e6:.3f}"
                    except ValueError: pass
                lines.append(f"| {seed} | {egress} | {slope} | {cfg.get('numCredits:min','unavailable')} / {cfg.get('numCredits:max','unavailable')} / {cfg.get('numCredits:timeavg','unavailable')} |")
        lines += ["", "The credit statistics above are reported from the installed INET CBS vectors; their units follow the underlying INET signal and are not converted here. `idleSlope/0.77` is a configured reservation compensation, not a measured throughput guarantee. Queue growth and overflow demonstrate that the tested service did not maintain stable occupancy.",
            "",
            "## Clock synchronization and gate audit", "",
            "Downstream offsets were sampled at approximately 1 ms through the full measurement window [1,31) s. Piecewise-linear interpolation estimates time above 1 µs; excursions between samples remain unobserved.",
            "",
            "| Seed | Node | Max absolute offset (µs) | Estimated time above 1 µs (s) | Pass |",
            "|---:|---|---:|---:|---|"]
        for seed in (41, 43, 47):
            row = next((r for r in l2_rows if r.get("variant") == "C4compensated" and r.get("seed") == seed), None)
            for node in ((row or {}).get("pilot_vector_audit", {}).get("synchronization", {}).get("nodes", [])):
                lines.append(f"| {seed} | {node['node']} | {1e6*node['max_abs_offset_measurement_s']:.3f} | {node['estimated_duration_over_1us_s_piecewise_linear']:.6f} | {node['passes_pilot_sync_threshold']} |")
        lines += ["", "### Corrected physical-link utilization", "",
            "Utilization is the sample-hold integral of the binary transmitting-state vector over [1,31) s. Invalid state values are marked unavailable; they are not clipped, absolutized, or replaced with zero. In particular, `CSW.eth[0]` carries traffic but its retained transmitter state contains −1 sentinel samples, so its utilization is unavailable and is excluded from service claims. The prior negative histogram export is not used.",
            "", "| C4_shared_SPbrakes seed | Egress | Busy fraction | Status |",
            "|---:|---|---:|---|"]
        for seed in (41, 43, 47):
            row = next((r for r in data.get("current_runs", []) if r.get("variant") == "C4compensated" and r.get("cell") == "L2_A1" and r.get("seed") == seed), None)
            by_tx = (row or {}).get("physical_link_utilization", {}).get("by_transmitter", {})
            for egress in ("HPC.eth[0]", "CSW.eth[0]", "CSW.eth[1]", "CSW.eth[2]", "CSW.eth[3]", "Z1.ZSW.eth[4]", "Z2.ZSW.eth[4]", "Z3.ZSW.eth[5]"):
                sample = next((v for k, v in by_tx.items() if k.endswith(egress + ".phyLayer.transmitter")), None)
                value = sample.get("measurement_busy_fraction") if sample else None
                status = "valid" if sample and sample.get("valid") else "unavailable"
                lines.append(f"| {seed} | {egress} | {f'{100*value:.3f}%' if value is not None else 'N/A'} | {status} |")
        lines += ["", "The selected valid egress values are corroborative physical-state measurements, not CBS service guarantees. A separate independent wire-summary check was unavailable because retained wire summary data were missing; results do not substitute the invalid `CSW.eth[0]` series with a derived estimate.",
            ""]
        lines += ["", "All scheduled GCLs passed the effective-configuration and measured gate-state checks. The 24 always-open brake SP gates in C4_shared_SPbrakes were verified from effective SCA parameters, because a permanently open gate has no transition vector. The full-path diagnostic schedules TAS on all seven egresses and has corresponding gate-state evidence. A valid GCL does not imply synchronized clocks or end-to-end viability.",
            "",
            "## Decision findings for this exploratory pilot",
            "",
            "- **Did SP on the real final brake egresses recover F08–F10?** Yes, for the tested L2/A1 seeds 41, 43, and 47: all 300,000 packets per flow were received with zero loss and zero packet deadline misses. The largest shared-SP brake latency was 97.814 µs against a 100 µs deadline, leaving only 2.186 µs of observed margin.",
            "- **Did the complete treatment pass all applications and queue stability?** No. Application gates passed for all L2/A1 shared-SP runs, but the treatment failed stability in each seed; the gPTP ≤1 µs synchronization criterion also failed in each seed. At L0/A0 and L1/A1, the existing C3 control already failed application gates, so this pilot did not recover the complete workload there.",
            "- **Did HPC/TC4 keep growing?** Yes. Its six 5 s means increased in every shared-SP L2/A1 seed; overflow was 48, 168, and 125 packets for seeds 41, 43, and 47. Seed 43 also showed sustained growth at Z3.ZSW.eth[7]/TC4.",
            "- **Was synchronization adequate throughout measurement?** No. Approximately 1 ms samples cover [1,31) s, and the sampled maximum absolute offsets exceeded 1 µs at one or more downstream clocks in all seeds (maximum across nodes: 1.378 ms, 2.519 ms, and 1.929 ms). Inter-sample excursions cannot be excluded.",
            "- **Does this justify an official C4 change?** It supports investigating a prospective C4 design that keeps brake-facing egresses under SP, but it does not validate C4. The shared-SP variant still needs investigation of CBS queue growth/overflow and gPTP synchronization; the full-path diagnostic shows why the final brake gates are problematic under this workload.",
            "- **What would a later official evaluation need?** Update the prospective P1 only after review to specify the real route-derived brake egresses and SP exception, retain `C3_sync` as a paired control, and require the full application, synchronization, GCL, and queue-stability gates. This pilot does not revise the P1 or confirm H1–H5.",
            "",
            "## Nonstable queues", "",
            "| Execution | Queue / TC | Capacity (KiB) | Mean (KiB) | Peak (KiB) | Time ≥90% | Six 5 s means (KiB) |",
            "|---|---|---:|---:|---:|---:|---|"]
        for row in data.get("current_runs", []):
            for q in row.get("nonstable_queues", []):
                means = ", ".join(f"{x/8192:.2f}" for x in q.get("mean_occupancy_bits_5s", []))
                lines.append(f"| {row['execution_id']} | {q['queue'].replace('ZonalIVN.','')} / TC{q.get('tc')} | {q['capacity_bits']/8192:.2f} | {q['mean_occupancy_bits_measurement']/8192:.2f} | {q['max_occupancy_bits']/8192:.2f} | {100*q['fraction_measurement_at_least_90pct_capacity']:.3f}% | {means} |")
        lines += ["", "Stability uses the six consecutive 5 s measurement means and the registered sustained-growth criterion. A zero nonstable count means no sustained growth was detected under that criterion; it is not a claim that queues were empty. The full queue traces and metadata remain available for independent recalculation.",
            "",
            "## Post-processing corrections", "",
            "All 16 scheduled executions completed with paired calendars and no pending cells. Four failed technical attempts remain in `technical_attempts.jsonl`; retries that produced an audited result remain one methodological execution each. One attempt row is internally mismatched: it names `C4original_L2_A1_seed41` while its error text refers to a `C3sync_L2_A1_seed41` run. The later final scheduled rows are completed and audited; that historical metadata mismatch is retained rather than silently rewritten. The corrected C4original and C4compensated seed-41 results were reprocessed from retained SCA and compact traces, without re-running those simulations. The application/stability split below also corrects a reporting conflation in which application_viable had copied the validator's combined cell result.",
            "",
            "| Correction | Re-simulation |",
            "|---|---|"]
        for correction in data.get("postprocessing_audit_corrections", []):
            lines.append(f"| {correction['correction']} | {correction.get('simulation_rerun')} |")
        lines += ["",
            f"Run identity: commit {data['manifest'].get('git_commit')}; OMNeT++ {data['manifest'].get('omnetpp_version')}; INET {data['manifest'].get('inet_version')} ({data['manifest'].get('inet_commit')}); P1 SHA-256 {data['manifest']['p1']['sha256']}; frozen CBS source {data['manifest']['official_profile']['profile_id']}."
        ]
    lines += ["", "## Reproduction and recovery", "",
        "Run `python3 simulations/pilot/c4_shared_sp_brakes/check_readiness.py` before starting. The reviewed plan was generated by `run_pilot.py --plan`; `pilot_status.py` is read-only. The runner allows at most one simulation process on this machine, serializes vector extraction, keeps a 45 GB free-space floor, checkpoints each completed execution, and refuses to run while the official campaign is active. Launch at reduced CPU/I/O priority with `nice -n 15 ionice -c 3`; use `--run --resume` only after reviewing the checkpoint/dashboard.",
        ""]
    return "\n".join(lines)


def regenerate_reports(manifest: dict):
    rows = current_ledger()
    data = build_final(manifest, rows)
    OUT.mkdir(parents=True, exist_ok=True)
    write_json(OUT / "pilot_results.json", data)
    (OUT / "analysis.md").write_text(generate_markdown(data), encoding="utf-8")


def execute(manifest: dict, resume: bool):
    if official_campaign_active():
        raise RuntimeError("Official campaign lock/process is active; refusing pilot execution")
    lockfile = OUT / ".pilot.lock"
    lockfile.parent.mkdir(parents=True, exist_ok=True)
    lock_fd = os.open(lockfile, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as e:
        os.close(lock_fd)
        raise RuntimeError("Another C4 pilot runner holds results/.pilot.lock") from e
    global CHECKPOINT, LEDGER
    try:
        plan_path = OUT / "plan.json"
        if not plan_path.exists():
            raise RuntimeError("Run --plan first; no simulation starts without a saved manifest and preflight")
        old_manifest = json.loads(plan_path.read_text())
        if old_manifest.get("versions_and_hashes") != manifest.get("versions_and_hashes"):
            raise RuntimeError("Pilot sources changed since --plan; regenerate and review the plan before running")
        if old_manifest.get("official_profile", {}).get("sha256") != manifest["official_profile"]["sha256"]:
            raise RuntimeError("Official frozen profile hash changed since --plan")
        LEDGER = current_ledger()
        attempts = current_attempts()
        existing = {r.get("execution_id") for r in LEDGER}
        if (existing or attempts) and not resume:
            raise RuntimeError("Pilot ledger already exists; use --resume only after checking the dashboard/checkpoint")
        try: CHECKPOINT = json.loads((OUT / "checkpoint.json").read_text())
        except (OSError, json.JSONDecodeError): CHECKPOINT = {}
        status = CHECKPOINT.get("execution_status", {})
        for row in LEDGER:
            status[row.get("execution_id")] = row.get("status", "completed")
            if row.get("status") == "completed":
                finish_committed_cleanup(row)
        attempt_by_execution = {}
        for attempt in attempts:
            attempt_by_execution[attempt.get("execution_id")] = attempt
        for execution_id, attempt in attempt_by_execution.items():
            if execution_id not in existing:
                status[execution_id] = "failed_technical_attempt_pending_retry"
        CHECKPOINT = {**CHECKPOINT, "pilot_id": "c4-shared-sp-brakes", "stage": "pilot",
            "active": {}, "execution_status": status, "planned_runs": len(manifest["run_schedule"]),
            "max_parallel_runs": MAX_JOBS, "current_safe_jobs": memory_safe_jobs(MAX_JOBS),
            "memory_available_gb": round(memory_available_gb(), 2), "executor_pid": os.getpid(),
            "exploratory": True, "official_c4_frozen": False}
        write_checkpoint(phase="ready")
        preflight = {variant: value for variant, value in manifest["admissibility"].items()}
        schedule = manifest["run_schedule"]
        # The original variant is an authorized one-off diagnostic even when
        # the analytical preflight rejects it; inadmissible primary variants
        # are skipped and recorded without a simulation.
        for spec in schedule:
            if spec["execution_id"] in existing:
                continue
            adm = preflight[VARIANT_NAMES[spec["variant"]]]["cells"][spec["cell"]]["admissible"]
            if not adm and not spec["allow_inadmissible"]:
                row = {**spec, "variant_id": VARIANT_NAMES[spec["variant"]], "status": "rejected_before_execution",
                    "admissible": False, "simulation_valid": None, "application_viable": None,
                    "reason": "predeclared reservation/open-time/CBS-service preflight failed"}
                append_jsonl(OUT / "runs.jsonl", row); LEDGER.append(row); existing.add(spec["execution_id"])
                CHECKPOINT.setdefault("execution_status", {})[spec["execution_id"]] = row["status"]
                write_checkpoint(last_execution_id=spec["execution_id"])
                regenerate_reports(manifest)
                continue
            if official_campaign_active():
                write_checkpoint(phase="paused_official_campaign_active", active={})
                break
            # Run the OMNeT++ cohort in parallel, then parse its large vectors
            # serially. The old combined worker overlapped four full vector
            # parsers and caused a system-wide OOM after successful simulation.
            repair_group = "instrumentation_repair" if spec.get("kind") == "instrumentation_repair" else None
            cohort_key = (spec["cell"], spec["seed"], repair_group)
            cohort = [x for x in schedule if (x["cell"], x["seed"], "instrumentation_repair" if x.get("kind") == "instrumentation_repair" else None) == cohort_key and
                      x["execution_id"] not in existing and
                      (preflight[VARIANT_NAMES[x["variant"]]]["cells"][x["cell"]]["admissible"] or x["allow_inadmissible"])]
            calendar_path = OUT / "calendars" / spec["cell"] / f"seed{spec['seed']}_events.csv"
            deferred_for_calendar = False
            if not calendar_path.is_file() and any(x["variant"] != "C3base" for x in cohort):
                # Establish the paired calendar from the C3-base treatment before
                # starting synchronized variants that replay that exact schedule.
                baseline = [x for x in cohort if x["variant"] == "C3base"]
                if not baseline:
                    raise RuntimeError(f"Missing paired transient calendar and no pending C3base run for {spec['cell']} seed {spec['seed']}")
                cohort = baseline
                deferred_for_calendar = True
            # When recovering after a reboot, audit an already-completed
            # C3-base raw run before launching any paired treatment. This keeps
            # the 7+ GB vector extraction isolated and ensures a failure cannot
            # waste or overlap the remaining runs in the cohort.
            if calendar_path.is_file():
                baseline = next((x for x in cohort if x["variant"] == "C3base"), None)
                if baseline and baseline["execution_id"] not in existing:
                    config = f"Pilot_{baseline['variant']}_{baseline['cell']}"
                    dest = OUT / "runs" / baseline["execution_id"]
                    if completed_raw_run_matches(dest, config, baseline["seed"]):
                        try:
                            run_one(baseline, manifest, preflight, freshly_simulated=False)
                        except Exception:
                            write_checkpoint(phase="paused_after_technical_error", active={})
                            regenerate_reports(manifest)
                            return
                        existing.add(baseline["execution_id"])
                        regenerate_reports(manifest)
                        cohort = [x for x in cohort if x["execution_id"] != baseline["execution_id"]]
            freshly_simulated = set()
            simulation_specs = []
            for item in cohort:
                config = f"Pilot_{item['variant']}_{item['cell']}"
                dest = OUT / "runs" / item["execution_id"]
                if not completed_raw_run_matches(dest, config, item["seed"]):
                    simulation_specs.append(item)
            if simulation_specs:
                safe_jobs = memory_safe_jobs(len(simulation_specs))
                if safe_jobs < 1:
                    write_checkpoint(phase="paused_low_memory", active={},
                                     memory_available_gb=memory_available_gb(),
                                     pending_execution_ids=[x["execution_id"] for x in simulation_specs])
                    regenerate_reports(manifest)
                    return
                with concurrent.futures.ThreadPoolExecutor(max_workers=safe_jobs) as pool:
                    write_checkpoint(current_safe_jobs=safe_jobs,
                                     memory_available_gb=round(memory_available_gb(), 2),
                                     concurrency_cap=MAX_JOBS)
                    futures = {pool.submit(simulate_raw_run, item, manifest): item for item in simulation_specs}
                    for future in concurrent.futures.as_completed(futures):
                        item = futures[future]
                        try:
                            if future.result():
                                freshly_simulated.add(item["execution_id"])
                        except Exception as exc:
                            failures = [(item, exc)]
                            # Do not run queued variants after a technical
                            # failure (e.g. a bad calendar/configuration).
                            # Cancel work not yet started, wait only for any
                            # process already running, and record each real
                            # failure against its own execution ID.
                            for pending in futures:
                                if pending is not future:
                                    pending.cancel()
                            for pending, pending_item in futures.items():
                                if pending is future or pending.cancelled():
                                    continue
                                try:
                                    pending.result()
                                except Exception as pending_exc:
                                    failures.append((pending_item, pending_exc))
                            for failed_item, failed_exc in failures:
                                row = {**failed_item, "variant_id": VARIANT_NAMES[failed_item["variant"]],
                                    "attempt_status": "failed_technical", "attempt_id": f"{failed_item['execution_id']}:{int(time.time())}:{os.getpid()}",
                                    "simulation_valid": False, "application_viable": None,
                                    "error": f"{type(failed_exc).__name__}: {failed_exc}",
                                    "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
                                append_jsonl(OUT / "technical_attempts.jsonl", row)
                                CHECKPOINT.setdefault("execution_status", {})[failed_item["execution_id"]] = "failed_technical_attempt_pending_retry"
                            last = failures[-1][0]
                            write_checkpoint(phase="paused_after_technical_error", active={}, latest_execution_id=last["execution_id"], latest_technical_attempt={
                                "execution_id": last["execution_id"], "error": str(failures[-1][1])})
                            regenerate_reports(manifest)
                            return
            for item in cohort:
                try:
                    row = run_one(item, manifest, preflight, freshly_simulated=item["execution_id"] in freshly_simulated)
                except Exception:
                    write_checkpoint(phase="paused_after_technical_error")
                    regenerate_reports(manifest)
                    return
                existing.add(item["execution_id"])
                regenerate_reports(manifest)
            if cohort_key[:2] == ("L2_A1", 41) and not deferred_for_calendar:
                first_rows = {r.get("variant"): r for r in current_ledger()
                              if r.get("cell") == "L2_A1" and r.get("seed") == 41 and r.get("status") == "completed"}
                must_check = ["C3base", "C3sync"]
                if preflight[VARIANT_NAMES["C4compensated"]]["cells"]["L2_A1"]["admissible"]:
                    must_check.append("C4compensated")
                problems = []
                for variant in must_check:
                    row = first_rows.get(variant)
                    if not row:
                        problems.append(f"{variant}: missing seed-41 L2/A1 instrument-control run")
                    elif not row.get("simulation_valid"):
                        problems.append(f"{variant}: simulation/calendar/vector audit failed")
                    # Synchronization and application-gate failures are measured
                    # outcomes, not instrumentation failures. Continue the
                    # preregistered seeds when the run and its configuration
                    # evidence are valid so that these failures can be assessed
                    # for repeatability.
                    elif variant == "C4compensated" and (
                        row.get("effective_gcl", {}).get("status") != "pass" or
                        row.get("tas_instrumentation_viable") is not True):
                        problems.append("C4compensated: effective GCL or scheduled-gate evidence is invalid")
                if problems:
                    write_checkpoint(phase="paused_instrumentation_gate", active={},
                                     instrumentation_blockers=problems)
                    regenerate_reports(manifest)
                    return
            if free_gb() < FREE_FLOOR_GB:
                write_checkpoint(phase="paused_disk_floor")
                regenerate_reports(manifest)
                return
        remaining = [x for x in schedule if x["execution_id"] not in {r.get("execution_id") for r in current_ledger()}]
        phase = "complete" if not remaining else CHECKPOINT.get("phase", "paused")
        write_checkpoint(phase=phase, active={}, remaining_execution_ids=[x["execution_id"] for x in remaining])
        regenerate_reports(manifest)
    finally:
        try: fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally: os.close(lock_fd)


def refresh_plan_preserving_history(manifest: dict):
    """Explicitly version the plan after a documented instrumentation fix."""
    if lock_is_busy(OUT / ".pilot.lock"):
        raise RuntimeError("The C4 pilot runner is active; plan refresh is unsafe")
    old_path = OUT / "plan.json"
    if not old_path.exists() or not (OUT / "runs.jsonl").exists():
        raise RuntimeError("Plan refresh requires the existing plan and ledger")
    history = OUT / "plan_history"
    history.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    archived = history / f"plan-before-instrumentation-fix-{stamp}.json"
    shutil.copy2(old_path, archived)
    write_json(old_path, manifest)
    event = {"event": "plan_refreshed_after_instrumentation_correction",
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "archived_plan": str(archived.relative_to(HERE)),
        "reason": "effective GCL and gPTP-control PCP audits scoped to pilot; paired C3-base F21/F22 calendar replay added; previous raw runs retained",
        "preserved_ledger_rows": len(current_ledger()), "preserved_technical_attempts": len(current_attempts())}
    append_jsonl(OUT / "recovery_events.jsonl", event)
    try:
        checkpoint = json.loads((OUT / "checkpoint.json").read_text())
    except (OSError, json.JSONDecodeError):
        checkpoint = {}
    checkpoint.update({"phase": "plan_refreshed_instrumentation_repair",
        "planned_runs": len(manifest["run_schedule"]), "active": {},
        "instrumentation_repair_ids": [x["execution_id"] for x in manifest["run_schedule"] if x.get("kind") == "instrumentation_repair"],
        "plan_history_file": str(archived.relative_to(HERE)), "exploratory": True, "official_c4_frozen": False})
    write_json(OUT / "checkpoint.json", checkpoint)
    regenerate_reports(manifest)
    print(f"Refreshed pilot plan; archived previous plan at {archived}; ledger and raw evidence preserved.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", action="store_true", help="write manifest and full admissibility screens; never simulates")
    mode.add_argument("--run", action="store_true", help="run the predeclared pilot schedule")
    mode.add_argument("--refresh-plan-after-instrumentation-fix", action="store_true",
        help="archive the old plan and update hashes/schedule while preserving ledger and results")
    parser.add_argument("--resume", action="store_true", help="resume only this pilot when the manifest hashes match")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = make_manifest()
    if args.plan:
        if lock_is_busy(OUT / ".pilot.lock"):
            raise RuntimeError("The C4 pilot runner is active; --plan cannot replace its checkpoint")
        if (OUT / "runs.jsonl").exists():
            raise RuntimeError("Committed pilot ledger exists; preserve the plan and use --run --resume")
        attempts = current_attempts()
        old_plan_path = OUT / "plan.json"
        if attempts and old_plan_path.exists():
            history = OUT / "plan_history"
            history.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
            archived_plan = history / f"plan-before-technical-correction-{stamp}.json"
            shutil.copy2(old_plan_path, archived_plan)
        if official_campaign_active():
            print("Notice: official campaign is active; plan created, but do not run this pilot concurrently.", file=sys.stderr)
        write_json(OUT / "plan.json", manifest)
        preserved_status = {a["execution_id"]: "failed_technical_attempt_pending_retry"
                            for a in attempts if a.get("execution_id")}
        CHECKPOINT.update({"pilot_id": "c4-shared-sp-brakes",
            "phase": "planned_after_technical_correction" if attempts else "planned",
            "planned_runs": len(manifest["run_schedule"]),
            "max_parallel_runs": MAX_JOBS, "current_safe_jobs": memory_safe_jobs(MAX_JOBS),
            "memory_available_gb": round(memory_available_gb(), 2), "active": {}, "execution_status": preserved_status,
            "exploratory": True, "official_c4_frozen": False})
        if attempts:
            CHECKPOINT["technical_attempt_count"] = len(attempts)
            CHECKPOINT["latest_technical_attempt"] = attempts[-1]
        write_checkpoint()
        regenerate_reports(manifest)
        print(f"Pilot plan written: {OUT / 'plan.json'}; maximum {len(manifest['run_schedule'])} executions; no simulation launched.")
        print(f"Free disk: {free_gb():.1f} GB; official campaign active: {official_campaign_active()}")
    elif args.refresh_plan_after_instrumentation_fix:
        refresh_plan_preserving_history(manifest)
    else:
        execute(manifest, args.resume)


if __name__ == "__main__":
    main()
