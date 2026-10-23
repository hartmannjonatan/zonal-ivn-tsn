#!/usr/bin/env python3
"""Checkpointed, single-process runner for the frozen official C4 matrix.

This runner is deliberately opt-in: without --run it never launches OMNeT++.
Its ledger/checkpoint live below results/C4 and are independent of the C0-C3
campaign state.
"""
from __future__ import annotations

import argparse
import csv
import fcntl
import gzip
import hashlib
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

# parents[4] is the repository root for this isolated runner.  Keeping this
# explicit matters: an earlier draft used parents[5], which pointed outside
# the checkout and made every campaign-relative path invalid.
ROOT = Path(__file__).resolve().parents[4]
SIM = ROOT / "simulations"
HERE = Path(__file__).resolve().parent
C4_DIR = ROOT / "simulations/c4_official"
OUT = HERE / "results/C4"
MANIFEST = HERE / "manifest.json"
MATRIX = HERE / "matrix.csv"
C3_RESULTS = ROOT / "simulations/campaigns/p1-v2-official-2026-10/results"
CALENDAR_INDEX = C3_RESULTS / "calendars/calendar_index.json"
P1_RUNNER = HERE.parent / "run_campaign.py"
CONFIG_INI = HERE / "c4_official.ini"
PROFILE_INI = C4_DIR / "C4_D3_absolute_profile.ini"
PLUGIN = C4_DIR / "plugin/libc4realclockprobe.so"
EXECUTABLE = ROOT / "src/zonal-ivn-tsn"
INET_ROOT = Path(os.environ.get("INET_ROOT", "/home/jonatan/omnetpp/samples/inet-4.7.0")).resolve()
OMNETPP_ROOT = Path(os.environ.get("OMNETPP_ROOT", "/home/jonatan/omnetpp")).resolve()
SEEDS = tuple(range(1001, 1031))
LOADS = ("L0", "L1", "L2")
ALIGNMENTS = ("A0", "A1")
DISK_FLOOR_GIB = 40.0
PRELAUNCH_MEM_FLOOR_GIB = 6.0
RUNTIME_MEM_FLOOR_GIB = 4.0
MAX_JOBS = 1
SIMULATION_SECONDS = 31.05

sys.path[:0] = [str(ROOT / "scripts/run"), str(ROOT / "tests/validation/traffic"), str(C4_DIR)]
import validate_c0 as validator  # noqa: E402
import validate_c4_contract as contract  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def free_gib() -> float:
    return shutil.disk_usage(ROOT).free / (1024 ** 3)


def mem_available_gib() -> float:
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) / (1024 ** 2)
    return 0.0


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(path)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def append_jsonl(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)


def read_ledger() -> list[dict]:
    path = OUT / "ledger.jsonl"
    if not path.exists():
        return []
    rows = []
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                rows.append(json.loads(line))
    ids = [row["execution_id"] for row in rows]
    require(len(ids) == len(set(ids)), "duplicate C4 execution IDs in ledger")
    return rows


def calendar_signature(path: Path) -> tuple[str, int]:
    payload = []
    with path.open(newline="") as stream:
        for row in csv.DictReader(stream):
            payload.append({k: row[k] for k in ("flow", "block", "signature", "start", "duration", "volume_bytes")})
    sig = hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()
    return sig, len(payload)


def position_rows() -> list[dict]:
    with MATRIX.open(newline="") as stream:
        return list(csv.DictReader(stream))


def verify_snapshot() -> dict:
    m = json.loads(MANIFEST.read_text())
    require(m.get("snapshot_id") and m.get("official_c4_frozen") is True and
            m.get("official_c4_validated") is False, "C4 freeze flags/identity are inconsistent")
    require(m.get("profile_sha256") == json.loads((C4_DIR / "frozen_d3_l2_profile.json").read_text())["canonical_sha256"],
            "C4 manifest profile hash mismatch")
    failures = []
    for rel, expected in m["input_file_hashes"].items():
        path = ROOT / rel if not Path(rel).is_absolute() else Path(rel)
        if not path.is_file() or sha256(path) != expected:
            failures.append(rel)
    for rel, expected in m.get("external_file_hashes", {}).items():
        if rel.startswith("@INET_ROOT/"):
            root = os.environ.get("INET_ROOT")
            require(root, "Set INET_ROOT before validating the frozen C4 runtime")
            path = Path(root) / rel.removeprefix("@INET_ROOT/")
        elif rel.startswith("@OMNETPP_ROOT/"):
            root = os.environ.get("OMNETPP_ROOT")
            if not root:
                opp_run = shutil.which("opp_run")
                require(opp_run, "Set OMNETPP_ROOT or put opp_run on PATH before validating the frozen C4 runtime")
                root = str(Path(opp_run).resolve().parent.parent)
            path = Path(root) / rel.removeprefix("@OMNETPP_ROOT/")
        else:
            # Legacy snapshots used absolute local paths. Keep them readable,
            # but new frozen snapshots use portable runtime-root tokens.
            path = Path(rel)
        if not path.is_file() or sha256(path) != expected:
            failures.append(rel)
    require(not failures, f"frozen C4 snapshot inputs changed/missing: {failures}")
    source_hashes = m["input_file_hashes"] | m.get("external_file_hashes", {})
    snapshot = hashlib.sha256("\n".join(f"{k} {source_hashes[k]}" for k in sorted(source_hashes)).encode()).hexdigest()
    require(snapshot == m.get("snapshot_sha256"), "C4 snapshot digest mismatch")
    return m


def verify_calendars() -> list[dict]:
    index = json.loads(CALENDAR_INDEX.read_text())
    rows = position_rows()
    require(len(rows) == 180, f"official C4 matrix must contain 180 positions, got {len(rows)}")
    for row in rows:
        key = f"{row['load']}/{row['alignment']}/seed{row['seed']}"
        entry = index.get(key)
        require(entry is not None, f"missing existing official transient calendar {key}")
        path = ROOT / "simulations/campaigns/p1-v2-official-2026-10" / entry["file"]
        require(path.is_file(), f"missing calendar file {path}")
        signature, event_count = calendar_signature(path)
        require(signature == entry["sha256"] == row["calendar_signature"], f"calendar signature mismatch for {key}")
        require(event_count == int(entry["event_count"]) == int(row["calendar_event_count"]), f"calendar event-count mismatch for {key}")
        require(sha256(path) == row["calendar_file_sha256"], f"calendar file bytes changed for {key}")
    return rows


def active_official_runner() -> bool:
    lock_path = C3_RESULTS / ".campaign.lock"
    if lock_path.exists():
        fd = os.open(lock_path, os.O_RDONLY)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
        finally:
            os.close(fd)
    try:
        for proc in Path("/proc").iterdir():
            if not proc.name.isdigit() or int(proc.name) in (os.getpid(), os.getppid()):
                continue
            try:
                comm = (proc / "comm").read_text().strip()
                argv = (proc / "cmdline").read_bytes().split(b"\0")
            except OSError:
                continue
            if comm in {"opp_run", "zonal-ivn-tsn"}:
                return True
            if any(Path(x.decode(errors="ignore")).name == P1_RUNNER.name for x in argv if x):
                return True
    except OSError:
        pass
    return False


def check_resources(prelaunch: bool = True) -> dict:
    disk, mem = free_gib(), mem_available_gib()
    mem_floor = PRELAUNCH_MEM_FLOOR_GIB if prelaunch else RUNTIME_MEM_FLOOR_GIB
    require(disk >= DISK_FLOOR_GIB, f"disk floor reached: {disk:.2f} GiB free (<{DISK_FLOOR_GIB})")
    require(mem >= mem_floor, f"memory floor reached: {mem:.2f} GiB available (<{mem_floor})")
    return {"free_disk_gib": round(disk, 3), "MemAvailable_gib": round(mem, 3),
            "disk_floor_gib": DISK_FLOOR_GIB, "memory_floor_gib": mem_floor}


def seed_drifts(seed: int, nodes: tuple[str, ...]) -> dict[str, float]:
    # Independent, deterministic uniform draws; SHA-256 avoids coupling drift
    # draws to OMNeT++ traffic/gPTP RNG stream consumption or event ordering.
    values = {}
    for node in nodes:
        word = int.from_bytes(hashlib.sha256(
            f"p1-v2-official-2026-10:C4:ConstantDriftOscillator:{seed}:{node}".encode()).digest()[:8], "big")
        values[node] = -50.0 + 100.0 * word / (2**64 - 1)
    return values


def command_for(row: dict, dest: Path) -> list[str]:
    load, alignment, seed = row["load"], row["alignment"], int(row["seed"])
    config = f"Validate_C4_{load}_{alignment}"
    run_dir = dest / f"{config}-0"
    run_dir.mkdir(parents=True, exist_ok=True)
    calendar = ROOT / "simulations/campaigns/p1-v2-official-2026-10" / row["calendar_file"]
    calendar_from_sim = calendar.relative_to(SIM)
    network_paths = ".:c4_official:src:tests:" + str(INET_ROOT / "src")
    command = [str(EXECUTABLE), "-u", "Cmdenv", "-n", network_paths,
               "-f", "omnetpp.ini", "-f", "c4_official/C4_D3_absolute_profile.ini",
               "-f", str(CONFIG_INI.relative_to(SIM)), "-c", config,
               "-l", str(PLUGIN), "--cmdenv-express-mode=true", "--cmdenv-event-banners=false",
               f"--seed-set={seed}", f"--result-dir={dest.relative_to(SIM)}",
               "--network=zonal_ivn_tsn.simulations.c4_official.C4Instrumented",
               "--**.app[*].latency.result-recording-modes=+vector",
               "--**.app[*].imageCompletionLatency.result-recording-modes=+vector",
               "--**.queueLength.result-recording-modes=+vector",
               "--**.queueBitLength.result-recording-modes=+vector",
               "--**.droppedPacketLengthsQueueOverflow.result-recording-modes=+vector",
               "--**.queueingTime.result-recording-modes=+histogram",
               "--**.utilization.result-recording-modes=+histogram",
               "--**.transmissionGate[*].gateState.result-recording-modes=vector",
               "--**.transmissionGate[*].guardBandState.result-recording-modes=vector",
               "--**.numCredits.result-recording-modes=vector,max,min,timeavg",
               f'--*.trafficPlan.transientCalendarFile="{calendar_from_sim.as_posix()}"',
               f'--*.realClockTrace.outputFile="{(run_dir / "packet_events.csv").resolve()}"',
               f'--*.clockPrecision.outputFile="{(run_dir / "clock_precision.csv").resolve()}"',
               "--*.realClockTrace.packetTraceStride=256", "--*.realClockTrace.gateTraceUntil=1ms",
               "--*.clockPrecision.sampleInterval=1ms", "--*.clockPrecision.stopAt=31.05s",
               "--**.clock.timeChanged.result-recording-modes=vector",
               "--**.clock.emitClockTimeInterval=1ms",
               "--**.gptp.gmRateRatio.result-recording-modes=+vector",
               "--**.gptp.neighborRateRatio.result-recording-modes=+vector",
               "--**.gptp.pdelay.result-recording-modes=+vector",
               "--**.gptp.packetDropNotAddressedToUs.result-recording-modes=+count,sum(packetBytes),vector(packetBytes)"]
    for node, drift in seed_drifts(seed, ("HPC", "CSW", "Z1.ZSW", "Z2.ZSW", "Z3.ZSW")).items():
        command.append(f"--*.{node}.clock.oscillator.driftRate={drift:.12f}ppm")
    return command


def read_clock_summary(path: Path) -> dict:
    summary = {}
    with path.open(newline="") as stream:
        reader = csv.DictReader(stream)
        header = reader.fieldnames or []
        scale = None
        for row in reader:
            sim_raw = int(row["simtime_raw"])
            exp = int(row["simtime_scale_exp"])
            scale = 10.0 ** exp
            sim_s = sim_raw * scale
            if not (1.0 <= sim_s < 31.0):
                continue
            for node in ("HPC", "CSW", "Z1.ZSW", "Z2.ZSW", "Z3.ZSW"):
                col = node + "_offset_from_HPC_raw"
                raw = int(row[col])
                item = summary.setdefault(node, {"samples": 0, "violations_gt_1us": 0, "max_abs_offset_s": 0.0,
                                                 "max_abs_offset_raw": 0, "record_kinds": {}})
                absolute = abs(raw)
                item["samples"] += 1
                item["violations_gt_1us"] += int(absolute * scale > 1e-6)
                item["max_abs_offset_raw"] = max(item["max_abs_offset_raw"], absolute)
                item["max_abs_offset_s"] = item["max_abs_offset_raw"] * scale
                kind = row["record_kind"]
                item["record_kinds"][kind] = item["record_kinds"].get(kind, 0) + 1
    require(summary and all(v["samples"] > 0 for v in summary.values()), "clock probe emitted no measurement samples")
    return {"window_s": [1.0, 31.0], "sampling": "1 ms periodic plus native-tick clock-change snapshots",
            "continuous_conformity": "not_verified", "nodes": summary,
            "sampled_viable": all(v["violations_gt_1us"] == 0 for v in summary.values())}


def audit_observed_gate_states(vec_path: Path) -> dict:
    """Stream gate/guard-band state vectors over measurement and a dense 10ms slice.

    This is an event-state sanity check over a 10 ms measurement subwindow, not
    a continuous clock-conformity proof or a substitute for the SCA GCL check.
    """
    expected = {f"ZonalIVN.{port}.macLayer.queue.transmissionGate[{tc}]"
                for port in ("HPC.eth[0]", "CSW.eth[1]", "CSW.eth[2]", "CSW.eth[3]")
                for tc in range(8)}
    gate_vectors: dict[int, tuple[str, str]] = {}
    credit_vectors: dict[int, str] = {}
    state = {}
    credit_stats = {}
    state_metrics = {"gateState:vector", "guardBandState:vector"}
    with vec_path.open(errors="replace") as stream:
        for line in stream:
            if line.startswith("vector "):
                parts = line.split()
                if len(parts) >= 5 and parts[3] in state_metrics and parts[2] in expected:
                    vector_id = int(parts[1])
                    gate_vectors[vector_id] = (parts[2], parts[3])
                    state[vector_id] = {"samples_1ms": 0, "states_1ms": set(), "transitions_1ms": 0,
                                        "last_1ms": None, "samples_measurement": 0,
                                        "states_measurement": set(), "transitions_measurement": 0,
                                        "last_measurement": None}
                elif len(parts) >= 5 and parts[3] == "numCredits:vector":
                    vector_id = int(parts[1])
                    credit_vectors[vector_id] = parts[2]
                    credit_stats[vector_id] = {"samples": 0, "first_time_s": None, "last_time_s": None,
                        "first_credit": None, "last_credit": None, "min_credit": None, "min_time_s": None,
                        "max_credit": None, "max_time_s": None, "negative_samples": 0,
                        "zero_samples": 0, "positive_samples": 0}
                continue
            parts = line.split()
            if len(parts) != 4 or not parts[0].isdigit():
                continue
            vector_id = int(parts[0])
            try:
                time_s, value = float(parts[2]), float(parts[3])
            except ValueError:
                continue
            if vector_id in gate_vectors:
                item = state[vector_id]
                value = round(value)
                if 1 <= time_s < 31:
                    item["samples_measurement"] += 1
                    item["states_measurement"].add(value)
                    if item["last_measurement"] is not None and value != item["last_measurement"]:
                        item["transitions_measurement"] += 1
                    item["last_measurement"] = value
                if 1.01 <= time_s < 1.02:
                    item["samples_1ms"] += 1
                    item["states_1ms"].add(value)
                    if item["last_1ms"] is not None and value != item["last_1ms"]:
                        item["transitions_1ms"] += 1
                    item["last_1ms"] = value
            elif vector_id in credit_vectors and 1 <= time_s < 31:
                item = credit_stats[vector_id]
                if item["samples"] == 0:
                    item["first_time_s"], item["first_credit"] = time_s, value
                    item["min_credit"], item["min_time_s"] = value, time_s
                    item["max_credit"], item["max_time_s"] = value, time_s
                item["samples"] += 1
                item["last_time_s"], item["last_credit"] = time_s, value
                if value < item["min_credit"]:
                    item["min_credit"], item["min_time_s"] = value, time_s
                if value > item["max_credit"]:
                    item["max_credit"], item["max_time_s"] = value, time_s
                item["negative_samples"] += value < 0
                item["zero_samples"] += value == 0
                item["positive_samples"] += value > 0
    gate_names = {module for module, metric in gate_vectors.values() if metric == "gateState:vector"}
    guard_names = {module for module, metric in gate_vectors.values() if metric == "guardBandState:vector"}
    require(gate_names == expected,
            f"observed gate-state vector set mismatch: missing={sorted(expected-gate_names)}, extra={sorted(gate_names-expected)}")
    require(guard_names == expected,
            f"observed guard-band vector set mismatch: missing={sorted(expected-guard_names)}, extra={sorted(guard_names-expected)}")
    require(credit_vectors and any(item["samples"] for item in credit_stats.values()),
            "no CBS credit samples were observed during the measurement window")
    require(any(state[vector_id]["samples_measurement"] for vector_id in gate_vectors
                if gate_vectors[vector_id][1] == "guardBandState:vector"),
            "no guard-band state samples were observed during the measurement window")
    details = {"gate_state": {}, "guard_band_state": {}}
    for vector_id, (module, metric) in gate_vectors.items():
        item = state[vector_id]
        require(item["states_measurement"] <= {0, 1},
                f"{module}/{metric}: unexpected measurement state samples: {item}")
        if metric == "gateState:vector":
            require(item["samples_measurement"] > 0 and item["samples_1ms"] >= 20 and
                    item["states_1ms"] == {0, 1} and item["transitions_1ms"] >= 10,
                    f"{module}: gate-state changes were not observed in [1.01,1.02)s: {item}")
        details["gate_state" if metric == "gateState:vector" else "guard_band_state"][module] = {
            "samples_measurement_30s": item["samples_measurement"],
            "states_measurement": sorted(item["states_measurement"]),
            "transitions_measurement": item["transitions_measurement"],
            "samples_10ms_audit_window": item["samples_1ms"],
            "states_10ms_audit_window": sorted(item["states_1ms"]),
            "transitions_10ms_audit_window": item["transitions_1ms"]}
    credit_summary = {credit_vectors[vector_id]: item for vector_id, item in credit_stats.items()}
    return {"status": "pass", "measurement_window_s": [1, 31], "dense_audit_window_s": [1.01, 1.02],
            "scheduled_gates": len(gate_names), "continuous_conformity": "not_verified", "per_gate": details,
            "credit_vector_summary": {"unit": "credit units as emitted by INET numCredits signal",
                                      "scope": "measurement samples only; exact event series retained in dense 10ms window",
                                      "vectors": credit_summary}}


def hash_and_compress(path: Path) -> dict:
    raw_hash = sha256(path)
    gz = Path(str(path) + ".gz")
    with path.open("rb") as src, gzip.open(gz, "wb", compresslevel=6) as dst:
        shutil.copyfileobj(src, dst, length=1024 * 1024)
    h = hashlib.sha256()
    with gzip.open(gz, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    require(h.hexdigest() == raw_hash, f"lossless compression verification failed for {path}")
    size_raw, size_gz = path.stat().st_size, gz.stat().st_size
    path.unlink()
    return {"raw_sha256": raw_hash, "compressed_sha256": sha256(gz), "raw_bytes": size_raw,
            "compressed_bytes": size_gz, "lossless_verified": True}


RUNTIME_VECTOR_METRICS = {
    "numCredits:vector", "gateState:vector", "guardBandState:vector",
    "timeChanged:vector", "gmRateRatio:vector", "neighborRateRatio:vector",
    "pdelay:vector", "packetDropNotAddressedToUs:vector",
}


def retain_runtime_vectors(vec_path: Path, destination: Path) -> dict:
    """Keep only exact credit, gate, clock-correction and gPTP vector records.

    Packet latency tails, queue occupancy, clock offsets and application/drop
    counters are independently extracted to compact artifacts before this is
    called. The original vector is hashed while streaming, then removed only
    after this focused lossless evidence is closed and verified.
    """
    original_hash = hashlib.sha256()
    selected_ids = set()
    selected_metric_by_id = {}
    selected_counts = {}
    data_counts = {}
    sample_counts_by_metric = {}
    dense_gate_window = (1.01, 1.02)
    temp = Path(str(destination) + ".tmp")
    opener = gzip.open if vec_path.suffix == ".gz" else open
    with opener(vec_path, "rb") as raw_source, gzip.open(temp, "wt", encoding="utf-8", compresslevel=6) as output:
        for raw_line in raw_source:
            original_hash.update(raw_line)
            line = raw_line.decode("utf-8", errors="replace")
            if line.startswith("vector "):
                parts = line.split()
                if len(parts) >= 4 and parts[3] in RUNTIME_VECTOR_METRICS:
                    vector_id = int(parts[1])
                    selected_ids.add(vector_id)
                    selected_metric_by_id[vector_id] = parts[3]
                    selected_counts[parts[3]] = selected_counts.get(parts[3], 0) + 1
                    output.write(line)
                continue
            if line and line[0].isdigit():
                parts = line.split(maxsplit=1)
                if len(parts) == 2 and parts[0].isdigit() and int(parts[0]) in selected_ids:
                    metric = selected_metric_by_id[int(parts[0])]
                    retain = True
                    if metric in {"numCredits:vector", "gateState:vector", "guardBandState:vector"}:
                        event_parts = parts[1].split()
                        try:
                            timestamp = float(event_parts[1])
                        except (IndexError, ValueError):
                            raise RuntimeError(f"{vec_path}: malformed gate-state sample: {line[:160]!r}")
                        if metric == "gateState:vector" or metric == "numCredits:vector":
                            retain = dense_gate_window[0] <= timestamp < dense_gate_window[1]
                        else:
                            retain = 1.0 <= timestamp < 31.0
                    if retain:
                        output.write(line)
                        data_counts[parts[0]] = data_counts.get(parts[0], 0) + 1
                        sample_counts_by_metric[metric] = sample_counts_by_metric.get(metric, 0) + 1
                continue
            # Preserve run/version/attribute metadata, but not declarations
            # for vectors whose samples are intentionally summarized elsewhere.
            output.write(line)
    temp.replace(destination)
    require(selected_ids, f"{vec_path}: no clock/gate/credit runtime vectors selected")
    require(selected_counts.get("numCredits:vector", 0) > 0,
            f"{vec_path}: no actual CBS credit vectors were recorded")
    require(selected_counts.get("gateState:vector", 0) > 0 and
            selected_counts.get("guardBandState:vector", 0) > 0,
            f"{vec_path}: missing actual gate/guard-band vectors")
    require(sample_counts_by_metric.get("numCredits:vector", 0) > 0,
            f"{vec_path}: CBS credit vectors were declared but no credit samples were emitted")
    require(sample_counts_by_metric.get("gateState:vector", 0) > 0 and
            sample_counts_by_metric.get("guardBandState:vector", 0) > 0,
            f"{vec_path}: gate/guard-band vectors were declared but no state samples were emitted")
    compressed_hash = sha256(destination)
    return {"original_vector_sha256": original_hash.hexdigest(),
            "selected_vector_sha256": compressed_hash,
            "selected_vector_count_by_metric": selected_counts,
            "selected_sample_count_by_vector": data_counts,
            "selected_sample_count_by_metric": sample_counts_by_metric,
            "gate_state_retention_window_s": list(dense_gate_window),
            "credit_vector_retention_window_s": list(dense_gate_window),
            "guard_band_retention_window_s": [1.0, 31.0],
            "declared_vectors_without_samples": sorted(vector_id for vector_id in selected_ids
                                                        if data_counts.get(str(vector_id), 0) == 0),
            "retained_metrics": sorted(RUNTIME_VECTOR_METRICS),
            "retention": "lossless subset; application latencies and queue occupancy are preserved in separate exact compact artifacts",
            "lossless_selected_evidence": True,
            "original_bytes": vec_path.stat().st_size,
            "selected_compressed_bytes": destination.stat().st_size}


def compact_raw_outputs(dest: Path, config: str) -> dict:
    run_dir = dest / f"{config}-0"
    compressed = {}
    for path in sorted(dest.glob(f"{config}-#*.vec")):
        selected = run_dir / "runtime_vectors.vec.gz"
        compressed[str(selected.relative_to(dest))] = retain_runtime_vectors(path, selected)
        path.unlink()
    for path in sorted(dest.glob(f"{config}-#*.sca")) + sorted(dest.glob(f"{config}*.log")):
        compressed[str(path.relative_to(dest))] = hash_and_compress(path)
    # Vector-derived exact p99/max samples, six queue bins, credit scalars and
    # all measured populations remain in the acceptance/evidence JSON. The
    # full vector is removed only after those checks have succeeded.
    for path in sorted(run_dir.glob("*.csv")):
        compressed[str(path.relative_to(dest))] = hash_and_compress(path)
    queue_trace = run_dir / "queue_occupancy_events.csv.gz"
    queue_meta = run_dir / "queue_occupancy_events.csv.gz.meta.json.gz"
    if queue_trace.exists():
        require(queue_meta.is_file(), f"{config}: queue trace metadata missing before compaction")
        compact_trace = validator.compact_queue_occupancy_trace(queue_trace)
        compressed[str(compact_trace.relative_to(dest))] = {
            "compressed_bytes": compact_trace.stat().st_size,
            "sha256": sha256(compact_trace),
            "metadata_sha256": sha256(Path(str(compact_trace) + ".meta.json.gz")),
            "lossless_verified": True,
            "format": "p1-queue-occupancy-events-v2-varint",
        }
        # Keep the exact temporal representation; remove only its verified
        # CSV duplicate after the new binary trace can be independently read.
        validator.recompute_queue_occupancy_trace(compact_trace)
        queue_trace.unlink()
        queue_meta.unlink()
    # Once vectors are compressed, their .vci indexes no longer reference a
    # live vector and can be discarded without losing queryable evidence.
    for path in sorted(dest.glob(f"{config}-#*.vci")):
        path.unlink()
    return compressed


def expected_calendar_for_row(row: dict) -> str:
    return row["calendar_signature"]


def run_report(row: dict, manifest: dict, resources: dict) -> dict:
    config = f"Validate_C4_{row['load']}_{row['alignment']}"
    execution_id = f"C4_{row['load']}_{row['alignment']}_seed{row['seed']}"
    dest = OUT / "runs" / execution_id
    require(not dest.exists(), f"result path already exists without reusable ledger identity: {dest}")
    dest.mkdir(parents=True, exist_ok=False)
    command = command_for(row, dest)
    log = dest / f"{config}.log"
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = ":".join(str(p) for p in (OMNETPP_ROOT / "lib", INET_ROOT / "src", Path(env.get("LD_LIBRARY_PATH", "/tmp"))))
    cp = {"campaign_id": "p1-v2-official-2026-10-C4", "status": "running", "phase": "simulation",
          "active": {"execution_id": execution_id, "config": config, "seed": int(row["seed"]),
                     "load": row["load"], "alignment": row["alignment"], "pid": None, "percent": None,
                     "progress_note": "OMNeT++ event-time percent is read from the live log when available"},
          "completed": len(read_ledger()), "expected": 180, "resources": resources,
          "snapshot_id": manifest["snapshot_id"], "updated_local": time.strftime("%Y-%m-%d %H:%M:%S")}
    atomic_json(OUT / "checkpoint.json", cp)
    with log.open("w", encoding="utf-8") as logstream:
        proc = subprocess.Popen(command, cwd=SIM, env=env, stdout=logstream, stderr=subprocess.STDOUT,
                                start_new_session=True, preexec_fn=lambda: os.nice(5))
        cp["active"]["pid"] = proc.pid
        atomic_json(OUT / "checkpoint.json", cp)
        started = time.time()
        while proc.poll() is None:
            time.sleep(10)
            available = mem_available_gib()
            if free_gib() < DISK_FLOOR_GIB or available < RUNTIME_MEM_FLOOR_GIB:
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                proc.wait(timeout=30)
                raise RuntimeError(f"resource floor crossed during {execution_id}: disk={free_gib():.2f}GiB, MemAvailable={available:.2f}GiB")
            logstream.flush()
            tail = log.read_text(errors="replace")[-200_000:]
            matches = re.findall(r"(\d{1,3})% completed", tail)
            cp["active"].update({"pid": proc.pid, "elapsed_s": round(time.time()-started, 1),
                                 "percent": min(100, int(matches[-1])) if matches else None,
                                 "log_bytes": log.stat().st_size,
                                 "MemAvailable_gib": round(available, 3), "free_disk_gib": round(free_gib(), 3)})
            atomic_json(OUT / "checkpoint.json", cp)
    require(proc.returncode == 0, f"OMNeT++ exit={proc.returncode}; inspect {log}")
    log_text = log.read_text(errors="replace")
    require("Simulation time limit reached" in log_text and "End." in log_text, f"{execution_id}: normal simulation end not recorded")

    run_dir = dest / f"{config}-0"
    require((run_dir / "clock_precision.csv").is_file() and (run_dir / "packet_events.csv").is_file(),
            f"{execution_id}: required native clock/packet probes missing")
    expected_sig = expected_calendar_for_row(row)
    observed_sig, observed_events = calendar_signature(run_dir / "events.csv")
    require(observed_sig == expected_sig and len(observed_events) == int(row["calendar_event_count"]),
            f"{execution_id}: transient calendar signature/event count differs")

    # Shared postprocessor streams the large vector file and holds only exact
    # upper tails; its built-in configuration check confirms PCP, FIFO, buffers,
    # scheduled-gate placement, traffic counts and per-queue occupancy.
    application_report, returned_run_dir = validator.run_cell(
        config, dest, env=env, inet=INET_ROOT, execute=False,
        result_dir_override=str(dest.relative_to(SIM)), allow_gptp_control=True,
        allow_scheduled_gates=True)
    require(Path(returned_run_dir) == run_dir, f"{execution_id}: postprocessor selected unexpected run path")
    queue_csv = run_dir / "queue_occupancy_events.csv.gz"
    compact_queue = validator.compact_queue_occupancy_trace(queue_csv)
    compact_queue_metrics = validator.recompute_queue_occupancy_trace(compact_queue)
    reported_queues = {row["queue"]: row for row in application_report.get("queue_stability", [])}
    require(len(compact_queue_metrics) == len(reported_queues),
            f"{execution_id}: compact queue-trace population differs from report")
    for queue in compact_queue_metrics:
        expected_queue = reported_queues.get(queue["queue"])
        require(expected_queue is not None, f"{execution_id}: queue absent from compact-trace report: {queue['queue']}")
        for field in ("mean_occupancy_bits_5s", "mean_occupancy_bits_measurement",
                      "fraction_measurement_at_least_90pct_capacity", "max_occupancy_bits",
                      "capacity_bits", "sustained_growth"):
            actual, expected_value = queue[field], expected_queue[field]
            if isinstance(actual, list):
                require(len(actual) == len(expected_value) and all(
                    math.isclose(x, y, rel_tol=1e-10, abs_tol=1e-9)
                    for x, y in zip(actual, expected_value)),
                    f"{execution_id}: compact-trace {field} mismatch for {queue['queue']}")
            elif isinstance(actual, float):
                require(math.isclose(actual, expected_value, rel_tol=1e-10, abs_tol=1e-9),
                        f"{execution_id}: compact-trace {field} mismatch for {queue['queue']}")
            else:
                require(actual == expected_value,
                        f"{execution_id}: compact-trace {field} mismatch for {queue['queue']}")
    sca = dest / f"{config}-#0.sca"
    params = validator.parse_sca(sca)
    cbs_audit = contract.validate_effective_profile(params)
    gcl_audit = contract.validate_gcl_params(params)
    interfaces, queue_modules, control_queues = validator.verify_configuration(
        params, config, run_dir, allow_gptp_control=True, allow_scheduled_gates=True)
    gptp_nodes = ("HPC", "CSW", "Z1.ZSW", "Z2.ZSW", "Z3.ZSW")
    for node in gptp_nodes:
        require(params.get((f"ZonalIVN.{node}", "hasTimeSynchronization")) == "true", f"{node}: gPTP participant flag missing")
        require(params.get((f"ZonalIVN.{node}.clock", "typename"), "").endswith("SettableClock"), f"{node}: corrected SettableClock missing")
        require(params.get((f"ZonalIVN.{node}.clock.oscillator", "typename"), "").endswith("ConstantDriftOscillator"), f"{node}: validated oscillator missing")
        require(params.get((f"ZonalIVN.{node}.gptp", "typename"), "").endswith("Gptp"), f"{node}: gPTP module missing")
    for node in gptp_nodes:
        require(params.get((f"ZonalIVN.{node}.gptp", "syncInterval")) == "0.125s", f"{node}: sync interval mismatch")
        require(params.get((f"ZonalIVN.{node}.gptp", "pdelayInterval")) == "1s", f"{node}: pdelay interval mismatch")
    clock_summary = read_clock_summary(run_dir / "clock_precision.csv")
    observed_gates = audit_observed_gate_states(vec_path)
    application_report["C4_runtime_contract"] = {"CBS": cbs_audit, "GCL": gcl_audit,
        "gPTP_participants": list(gptp_nodes), "clock_summary": clock_summary,
        "observed_gate_states": observed_gates,
        "sampled_sync_viable": clock_summary["sampled_viable"],
        "continuous_sync_status": "not_verified", "control_queues": control_queues,
        "queue_modules_checked": len(queue_modules), "egress_interfaces_checked": len(interfaces)}
    application_report["simulation_valid"] = True
    application_report["technical_valid"] = True
    application_report["admissibility"] = "pre-screen passed for L0-L2 under the frozen D3 profile; empirical gates are evaluated per run"
    application_report["sync_sample_viable"] = clock_summary["sampled_viable"]
    application_report["sync_continuous_status"] = "not_verified"
    application_report["exploratory"] = False
    application_report["official_c4_frozen"] = True
    application_report["official_c4_validated"] = False
    report_path = dest / "C4_result.json"
    atomic_json(report_path, application_report)
    compressed = compact_raw_outputs(dest, config)
    record = {"campaign_id": "p1-v2-official-2026-10-C4", "execution_id": execution_id,
        "treatment": "C4", "load": row["load"], "alignment": row["alignment"], "seed": int(row["seed"]),
        "status": "completed_valid", "simulation_valid": True, "technical_valid": True,
        "application_viable": application_report["viable"], "stability_viable": not application_report["nonstable_queues"],
        "sampled_sync_viable": clock_summary["sampled_viable"], "continuous_sync_status": "not_verified",
        "calendar_signature": expected_sig, "calendar_file_sha256": row["calendar_file_sha256"],
        "profile_sha256": manifest["profile_sha256"], "snapshot_id": manifest["snapshot_id"],
        "run_report": str(report_path.relative_to(ROOT)), "run_report_sha256": sha256(report_path),
        "compressed_raw_artifacts": compressed, "result_viable": application_report["viable"] and
            (not application_report["nonstable_queues"]) and clock_summary["sampled_viable"],
        "free_disk_gib_after_run": round(free_gib(), 3), "MemAvailable_gib_after_run": round(mem_available_gib(), 3)}
    append_jsonl(OUT / "ledger.jsonl", record)
    cp = {"campaign_id": "p1-v2-official-2026-10-C4", "status": "ready",
          "phase": "completed_position", "latest_completed_execution": execution_id,
          "completed": len(read_ledger()), "expected": 180, "active": None,
          "last_result_viable": record["result_viable"], "snapshot_id": manifest["snapshot_id"],
          "resources": {"free_disk_gib": round(free_gib(), 3), "MemAvailable_gib": round(mem_available_gib(), 3)},
          "updated_local": time.strftime("%Y-%m-%d %H:%M:%S")}
    atomic_json(OUT / "checkpoint.json", cp)
    print(f"C4 {record['status']}: {execution_id}; application={record['application_viable']} stability={record['stability_viable']} sampled_sync={record['sampled_sync_viable']}; {record['free_disk_gib_after_run']:.1f} GiB free", flush=True)
    return record


def archive_incomplete(dest: Path, execution_id: str) -> None:
    if not dest.exists():
        return
    attempt_root = OUT / "failed-attempts" / execution_id
    attempt_root.mkdir(parents=True, exist_ok=True)
    n = len(list(attempt_root.iterdir())) + 1
    target = attempt_root / f"attempt_{n:02d}_{int(time.time())}"
    os.replace(dest, target)
    atomic_json(target / "technical_attempt.json", {"status": "uncommitted_attempt_preserved",
        "execution_id": execution_id, "reason": "run/postprocessing did not commit a valid ledger record",
        "snapshot_id": json.loads(MANIFEST.read_text())["snapshot_id"]})


def preflight() -> dict:
    manifest = verify_snapshot()
    static = contract.validate_static()
    rows = verify_calendars()
    require(not active_official_runner(), "C0-C3 campaign or OMNeT++ process is active; refusing concurrent C4 launch")
    resources = check_resources(prelaunch=True)
    return {"status": "pass", "simulation_started": False, "snapshot_id": manifest["snapshot_id"],
            "positions": len(rows), "static_contract": static, "resources": resources,
            "l3": manifest["triage"]["L3"], "unresolved_runtime_checks": [
                "resolved C4 SCA/profile/GCL/clock parameters", "observed periodic-gate states and guard bands",
                "clock-probe data and sampled synchronization"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight-only", action="store_true", help="static/resource/calendar checks; never launches OMNeT++")
    mode.add_argument("--run", action="store_true", help="run the official 180-position C4 matrix")
    parser.add_argument("--resume", action="store_true", help="resume only positions with no matching valid ledger record")
    parser.add_argument("--jobs", type=int, default=1, help="must remain 1; simulations are serialized for memory/storage safety")
    args = parser.parse_args()
    require(args.jobs == MAX_JOBS, "C4 official runner is intentionally serialized: use --jobs 1")
    if args.preflight_only:
        print(json.dumps(preflight(), indent=2))
        return
    require(args.resume, "--run requires --resume; this runner never overwrites completed results")
    result = preflight()
    OUT.mkdir(parents=True, exist_ok=True)
    lock_path = OUT / ".c4_campaign.lock"
    lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("another C4 runner holds results/C4/.c4_campaign.lock") from exc
        os.ftruncate(lock_fd, 0)
        os.write(lock_fd, f"{os.getpid()}\n".encode())
        os.fsync(lock_fd)
        manifest = verify_snapshot()
        rows = verify_calendars()
        checkpoint = {"campaign_id": "p1-v2-official-2026-10-C4", "status": "ready",
                      "phase": "final_matrix", "completed": len(read_ledger()), "expected": 180,
                      "active": None, "snapshot_id": manifest["snapshot_id"],
                      "l3_rejected": True, "updated_local": time.strftime("%Y-%m-%d %H:%M:%S")}
        atomic_json(OUT / "checkpoint.json", checkpoint)
        known = {row["execution_id"]: row for row in read_ledger()}
        for row in rows:
            resources = check_resources(prelaunch=True)
            require(not active_official_runner(), "C0-C3 campaign/process became active during C4; pausing safely")
            execution_id = f"C4_{row['load']}_{row['alignment']}_seed{row['seed']}"
            old = known.get(execution_id)
            if old:
                require(old.get("status") == "completed_valid" and old.get("snapshot_id") == manifest["snapshot_id"] and
                        old.get("calendar_signature") == row["calendar_signature"] and old.get("profile_sha256") == manifest["profile_sha256"],
                        f"cannot reuse incompatible/invalid ledger record {execution_id}")
                report = ROOT / old["run_report"]
                require(report.is_file() and sha256(report) == old["run_report_sha256"], f"reused C4 report changed: {execution_id}")
                continue
            attempt_log = OUT / "technical_attempts.jsonl"
            prior_attempts = sum(1 for x in attempt_log.read_text().splitlines() if execution_id in x) if attempt_log.exists() else 0
            require(prior_attempts <= 1, f"{execution_id} already used its one technical replacement; manual audit required")
            dest = OUT / "runs" / execution_id
            if dest.exists():
                archive_incomplete(dest, execution_id)
            try:
                run_report(row, manifest, resources)
            except Exception as exc:
                append_jsonl(attempt_log, {"execution_id": execution_id, "status": "technical_invalid_or_interrupted",
                    "error": repr(exc), "snapshot_id": manifest["snapshot_id"],
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "raw_output_preserved": str(dest.relative_to(ROOT)) if dest.exists() else None})
                atomic_json(OUT / "checkpoint.json", {"campaign_id": "p1-v2-official-2026-10-C4",
                    "status": "paused_technical_review", "phase": "final_matrix", "active": None,
                    "failed_execution": execution_id, "completed": len(read_ledger()), "expected": 180,
                    "error": repr(exc), "snapshot_id": manifest["snapshot_id"],
                    "resources": {"free_disk_gib": round(free_gib(),3), "MemAvailable_gib": round(mem_available_gib(),3)}})
                raise
        atomic_json(OUT / "checkpoint.json", {"campaign_id": "p1-v2-official-2026-10-C4",
            "status": "complete", "phase": "final_matrix", "active": None,
            "completed": len(read_ledger()), "expected": 180, "snapshot_id": manifest["snapshot_id"],
            "l3_rejected": True, "updated_local": time.strftime("%Y-%m-%d %H:%M:%S")})
        print(f"C4 matrix complete: {len(read_ledger())}/180; official validation is determined by the reported gates, not by matrix completion.")
    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
            os.close(lock_fd)


if __name__ == "__main__":
    main()
