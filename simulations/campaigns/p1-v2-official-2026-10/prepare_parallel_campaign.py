#!/usr/bin/env python3
"""Prepare the C0-owning C3/C4 host and its remote C1/C2 replica.

This tool never invokes OMNeT++. It validates the completed C0 baseline,
migrates campaign provenance without rewriting old run records, and packages
only calendars/profile/runtime artifacts needed by the C1/C2 host.
"""
from __future__ import annotations

import argparse
import fcntl
import gzip
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
RESULTS = HERE / "results"
MANIFEST = HERE / "campaign_manifest.json"
LEDGER = RESULTS / "runs.jsonl"
INDEX = RESULTS / "calendars/calendar_index.json"
CALIBRATION = RESULTS / "calibration/C3_calibration.json"
C4_DIR = HERE / "c4_official"
BUNDLE_SCHEMA = 1
OFFICIAL_SEEDS = range(1001, 1031)
OFFICIAL_LOADS = ("L0", "L1", "L2", "L3")
OFFICIAL_ALIGNMENTS = ("A0", "A1")
MIGRATION_SOURCE_CHANGES = {
    "scripts/run/validate_c0.py",
    "simulations/campaigns/p1-v2-official-2026-10/run_campaign.py",
    "src/common/TrafficPlan.cc",
    "src/common/TrafficPlan.ned",
    # C0 was produced by the prior local binary; this compiled binary adds the
    # explicitly authorized calendar replay path implemented in TrafficPlan.
    "src/zonal-ivn-tsn",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with tmp.open("rb") as stream:
        os.fsync(stream.fileno())
    tmp.replace(path)


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Cannot read JSON {path}: {exc}") from exc


def read_ledger(path: Path) -> list[dict]:
    rows = []
    try:
        with path.open(encoding="utf-8") as stream:
            for line_no, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise SystemExit(f"Invalid ledger line {line_no} in {path}: {exc}") from exc
    except OSError as exc:
        raise SystemExit(f"Cannot read ledger {path}: {exc}") from exc
    return rows


def expected_ids(treatment: str) -> set[str]:
    loads = ("L0", "L1", "L2") if treatment == "C3" else OFFICIAL_LOADS
    return {f"{treatment}_{load}_{alignment}_seed{seed}"
            for load in loads for alignment in OFFICIAL_ALIGNMENTS for seed in OFFICIAL_SEEDS}


def calendar_signature(path: Path) -> tuple[str, int]:
    import csv
    payload = []
    with path.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            payload.append({key: row[key] for key in
                            ("flow", "block", "signature", "start", "duration", "volume_bytes")})
    signature = hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()
    return signature, len(payload)


def calendar_contract() -> tuple[str, dict]:
    index = read_json(INDEX)
    contract = {}
    for key, entry in sorted(index.items()):
        path = HERE / entry["file"]
        require(path.is_file(), f"Missing paired transient calendar {path}")
        signature, count = calendar_signature(path)
        require(signature == entry.get("sha256") and count == int(entry.get("event_count", -1)),
                f"Calendar signature/count mismatch for {key}")
        contract[key] = {"sha256": signature, "event_count": count, "file_sha256": sha(path)}
    digest = hashlib.sha256(json.dumps(contract, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return digest, contract


def campaign_runner():
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    spec = importlib.util.spec_from_file_location("campaign_runner_for_split", HERE / "run_campaign.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    module.INET = Path(os.environ.get("INET_ROOT", "/home/jonatan/omnetpp/samples/inet-4.7.0")).resolve()
    module.OMNETPP = Path(os.environ.get("OMNETPP_ROOT", "/home/jonatan/omnetpp")).resolve()
    return module


def c4_runner():
    spec = importlib.util.spec_from_file_location("c4_runner_for_split", C4_DIR / "run_c4_campaign.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def current_identity() -> tuple[object, dict, str]:
    runner = campaign_runner()
    try:
        identity = runner.metadata()
    except Exception as exc:
        raise SystemExit(f"Cannot resolve current OMNeT++/INET campaign identity: {exc}") from exc
    return runner, identity, runner.campaign_contract_digest(identity)


def c0_rows_and_artifacts(parent_manifest: dict) -> tuple[list[dict], dict]:
    rows = read_ledger(LEDGER)
    c0 = [row for row in rows if row.get("stage") == "final" and
          row.get("campaign_treatment", row.get("treatment")) == "C0"]
    ids = [row.get("execution_id") for row in c0]
    expected = expected_ids("C0")
    require(len(ids) == len(set(ids)), "Duplicate C0 execution IDs in the existing ledger")
    require(set(ids) == expected,
            f"C0 baseline must contain exactly 240 final IDs; found {len(ids)}, missing {len(expected-set(ids))}, extra {len(set(ids)-expected)}")
    for row in c0:
        require(row.get("campaign_id") == parent_manifest.get("campaign_id"),
                f"C0 row belongs to another campaign: {row.get('execution_id')}")
        old_sources = row.get("configuration_source_hashes", {})
        for source, old_hash in parent_manifest.get("source_hashes", {}).items():
            if source in old_sources:
                require(old_sources[source] == old_hash,
                        f"C0 source provenance differs from its parent manifest: {row.get('execution_id')} {source}")
        retained = row.get("retained", {})
        for field in ("packet_image_quantile_samples", "queue_occupancy_events", "queue_occupancy_metadata"):
            rel = retained.get(field)
            require(rel and (HERE / rel).is_file(),
                    f"C0 audit artifact missing for {row.get('execution_id')}: {field}={rel}")
        result_rel = row.get("command", {}).get("result_dir")
        require(result_rel, f"C0 command result_dir missing: {row.get('execution_id')}")
        run_dir = ROOT / "simulations" / result_rel / (row.get("config", "") + "-0")
        require((run_dir / (row.get("config", "") + "-#0.sca.gz")).is_file(),
                f"C0 compressed SCA evidence missing for {row.get('execution_id')}")
    index = read_json(INDEX)
    required_keys = {f"{load}/{alignment}/seed{seed}" for load in OFFICIAL_LOADS
                     for alignment in OFFICIAL_ALIGNMENTS for seed in OFFICIAL_SEEDS}
    require(required_keys <= set(index),
            f"C0 paired calendar index is incomplete; missing {len(required_keys-set(index))} official calendars")
    digest, contract = calendar_contract()
    for row in c0:
        key = f"{row['load_name']}/{row['aggregation_name']}/seed{row['seed']}"
        require(row.get("calendar_sha256") == contract[key]["sha256"],
                f"C0 run/calendar mismatch for {row.get('execution_id')}")
    return c0, {"sha256": digest, "entries": len(contract), "contract": contract}


def acquire_lock_check() -> None:
    lock = RESULTS / ".campaign.lock"
    if not lock.exists():
        return
    fd = os.open(lock, os.O_RDONLY)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("C0-C3 runner is active; stop preparation and do not modify campaign metadata")
        else:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def prepare_primary() -> dict:
    acquire_lock_check()
    parent = read_json(MANIFEST)
    require(parent.get("commit") == "41d558c005f3c4740f1e4aa79fddca5479900bac",
            "Unexpected parent campaign manifest; audit it manually before migration")
    require(parent.get("binary_sha256") == "682070643132e54b0fdd46093aa3a30725be5d8aea9597f64336311148ffc074",
            "Parent binary identity differs from the audited C0 campaign manifest")
    runner, current, current_contract = current_identity()
    status = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True)
    require(not status.strip(), "Commit all campaign/sharding/C4 source and snapshot files before preparing the two-host continuation")
    require(current.get("working_tree_clean") is True,
            "Current campaign sources are not clean; refusing to freeze cross-host identity")
    require(parent.get("p1_pdf_sha256") == current.get("previous_p1_pdf_sha256"),
            "Current P1 history does not identify the exact P1 used by the existing campaign")
    for invariant in ("mapping", "queueing", "p1_clarification"):
        require(parent.get(invariant) == current.get(invariant),
                f"Campaign invariant changed during continuation: {invariant}")
    for key in ("loads", "alignments", "seeds", "warmup_s", "measurement_s", "drain_s", "C3_L3"):
        require(parent.get("matrix", {}).get(key) == current.get("matrix", {}).get(key),
                f"Campaign matrix changed during continuation: {key}")
    for source, old_hash in parent.get("source_hashes", {}).items():
        now = current.get("source_hashes", {}).get(source)
        require(now is not None, f"Parent source disappeared from current manifest: {source}")
        if now != old_hash:
            require(source in MIGRATION_SOURCE_CHANGES,
                    f"Undocumented simulation-source change blocks continuation: {source}")
    c0, calendars = c0_rows_and_artifacts(parent)
    calibration = read_json(CALIBRATION)
    require(calibration.get("status") == "frozen_and_accepted" and
            calibration.get("final_profile_id") == "reduction_11",
            "C3 calibration is not the accepted reduction_11 profile")
    require(len(calibration.get("selected_profile_bps", {})) > 0,
            "Accepted C3 calibration has no frozen reservation table")
    archive = HERE / "protocol_history" / f"campaign_manifest_before_parallel_{parent['commit'][:12]}.json"
    parent_hash = sha(MANIFEST)
    if archive.exists():
        require(sha(archive) == parent_hash,
                f"Existing parent-manifest archive differs: {archive}")
    else:
        archive.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(MANIFEST, archive)
    protocol_archive = HERE / "protocol_history" / "calibration_protocol_before_parallel.json"
    if protocol_archive.exists():
        require(sha(protocol_archive) == sha(HERE / "calibration_protocol.json"),
                f"Existing preregistered protocol archive differs: {protocol_archive}")
    else:
        shutil.copy2(HERE / "calibration_protocol.json", protocol_archive)
    current["continuation"] = {
        "schema_version": 1,
        "status": "audited_two_host_continuation; prior C0 rows retain their original provenance",
        "parent_manifest_path": str(archive.relative_to(HERE)),
        "parent_manifest_sha256": parent_hash,
        "parent_commit": parent["commit"],
        "parent_binary_sha256": parent["binary_sha256"],
        "continuation_binary_sha256": current["binary_sha256"],
        "binary_transition": "C0 retains its original executable/results; C1-C4 use the current binary containing only the audited optional F21/F22 calendar replay change in TrafficPlan.cc/.ned, and replay the exact C0 event calendars",
        "parent_p1_sha256": parent["p1_pdf_sha256"],
        "legacy_C0_final_records": len(c0),
        "legacy_C0_source_change_allowlist": sorted(MIGRATION_SOURCE_CHANGES),
        "legacy_C0_calendar_contract_sha256": calendars["sha256"],
        "C3_calibration_sha256": sha(CALIBRATION),
        "C3_profile_id": calibration["final_profile_id"],
        "future_transient_policy": "C1/C2/C3 explicitly replay C0 calendar files; C4 already consumes the same frozen calendar rows",
        "migration_does_not_rewrite_C0_ledger_or_reports": True,
    }
    current["previous_manifest_path"] = str(archive.relative_to(HERE))
    current["previous_manifest_sha256"] = parent_hash
    current["preregistered_protocol_archive"] = str(protocol_archive.relative_to(HERE))
    current["preregistered_protocol_sha256"] = sha(protocol_archive)
    atomic_json(MANIFEST, current)
    contract = {"schema_version": 1, "campaign_contract_sha256": current_contract,
                "campaign_manifest_sha256": sha(MANIFEST), "commit": current["commit"],
                "binary_sha256": current["binary_sha256"],
                "C0_legacy_records": len(c0), "C0_calendar_contract_sha256": calendars["sha256"],
                "C3_calibration_sha256": sha(CALIBRATION), "C3_profile_id": calibration["final_profile_id"],
                "C4_snapshot_id": read_json(C4_DIR / "manifest.json").get("snapshot_id"),
                "assignments": {"remote_imported_host": ["C1", "C2"],
                                "C0_primary_host": ["C3", "C4"]},
                "official_C4_open": False, "simulation_started": False}
    atomic_json(HERE / "parallel_campaign_contract.json", contract)
    return {"status": "primary_prepared", "simulation_started": False,
            "manifest_sha256": sha(MANIFEST), "contract": contract,
            "c0_records": len(c0), "calendar_entries": calendars["entries"],
            "calibration": calibration["final_profile_id"]}


def bundle_files() -> list[Path]:
    index = read_json(INDEX)
    files = [MANIFEST, HERE / "calibration_protocol.json", CALIBRATION, INDEX,
             ROOT / "src/zonal-ivn-tsn",
             ROOT / "simulations/c4_official/frozen_d3_l2_profile.json",
             ROOT / "simulations/c4_official/frozen_profile_table.csv",
             ROOT / "simulations/c4_official/C4_D3_absolute_profile.ini",
             ROOT / "simulations/c4_official/plugin/libc4realclockprobe.so",
             C4_DIR / "manifest.json", C4_DIR / "matrix.csv", C4_DIR / "checkpoint_template.json",
             HERE / "parallel_campaign_contract.json"]
    for entry in index.values():
        files.append(HERE / entry["file"])
    # Preserve the true pre-migration manifest/protocol archives on the
    # secondary host; otherwise its first runner startup would mislabel the
    # imported continuation manifest as the old P1-v3 snapshot.
    history = HERE / "protocol_history"
    if history.is_dir():
        files.extend(path for path in history.rglob("*") if path.is_file())
    unique = sorted(set(files))
    missing = [str(path) for path in unique if not path.is_file()]
    require(not missing, "Runtime bundle inputs missing:\n  " + "\n  ".join(missing))
    return unique


def export_bundle(destination: Path) -> dict:
    contract = read_json(HERE / "parallel_campaign_contract.json")
    require(contract.get("simulation_started") is False, "Invalid parallel campaign contract")
    runner, identity, fingerprint = current_identity()
    require(fingerprint == contract["campaign_contract_sha256"], "Current source/runtime no longer matches prepared contract")
    require(identity.get("commit") == contract["commit"], "Repository commit differs from prepared contract")
    files = bundle_files()
    entries = {str(path.relative_to(ROOT)): sha(path) for path in files}
    c4 = read_json(C4_DIR / "manifest.json")
    bundle_index = {"schema_version": BUNDLE_SCHEMA, "campaign_id": "p1-v2-official-2026-10",
                    "commit": contract["commit"], "campaign_contract_sha256": fingerprint,
                    "campaign_manifest_sha256": sha(MANIFEST),
                    "calibration_sha256": sha(CALIBRATION),
                    "calendar_contract_sha256": contract["C0_calendar_contract_sha256"],
                    "c4_snapshot_id": c4["snapshot_id"], "external_file_hashes": c4["external_file_hashes"],
                    "files": entries}
    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_suffix(destination.suffix + ".tmp")
    with tarfile.open(tmp, "w:gz") as archive:
        for path in files:
            archive.add(path, arcname=str(path.relative_to(ROOT)), recursive=False)
        payload = json.dumps(bundle_index, sort_keys=True, indent=2).encode() + b"\n"
        info = tarfile.TarInfo("parallel_bundle_index.json")
        info.size = len(payload); info.mode = 0o644
        import io
        archive.addfile(info, io.BytesIO(payload))
    os.replace(tmp, destination)
    return {"status": "bundle_exported", "path": str(destination), "bytes": destination.stat().st_size,
            "sha256": sha(destination), "files": len(files), "calendar_contract_sha256": bundle_index["calendar_contract_sha256"],
            "c4_snapshot_id": bundle_index["c4_snapshot_id"], "simulation_started": False}


def safe_bundle_members(archive: tarfile.TarFile) -> dict[str, tarfile.TarInfo]:
    members = {}
    for item in archive.getmembers():
        path = PurePosixPath(item.name)
        require(not path.is_absolute() and ".." not in path.parts,
                f"Unsafe path in bundle: {item.name}")
        require(item.isfile(), f"Bundle contains non-regular file: {item.name}")
        require(item.size <= 2_000_000_000, f"Bundle member unexpectedly large: {item.name}")
        require(item.name not in members, f"Duplicate path in bundle: {item.name}")
        members[item.name] = item
    return members


def import_bundle(bundle: Path) -> dict:
    acquire_lock_check()
    existing_ledger = RESULTS / "runs.jsonl"
    if existing_ledger.is_file():
        old_rows = read_ledger(existing_ledger)
        final_rows = [row for row in old_rows if row.get("stage") == "final"]
        require(not final_rows,
                "C1/C2 replica already has final rows; preserve/audit them before importing a new shard")
    existing_c4_ledger = C4_DIR / "results/C4/ledger.jsonl"
    if existing_c4_ledger.is_file() and existing_c4_ledger.stat().st_size:
        raise SystemExit("Secondary checkout already has C4 ledger data; refusing to mix shards")
    current_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    with tarfile.open(bundle, "r:gz") as archive:
        members = safe_bundle_members(archive)
        require("parallel_bundle_index.json" in members, "Bundle index missing")
        index_stream = archive.extractfile(members["parallel_bundle_index.json"])
        assert index_stream
        package = json.load(index_stream)
        require(package.get("schema_version") == BUNDLE_SCHEMA and package.get("commit") == current_commit,
                "Secondary host repository must be at the exact bundled commit")
        required = set(package.get("files", {})) | {"parallel_bundle_index.json"}
        require(set(members) == required, "Bundle file set differs from its signed inventory")
        for rel, expected_hash in package["files"].items():
            target = ROOT / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(members[rel]); assert source
            tmp = target.with_name(target.name + ".bundle.tmp")
            with source, tmp.open("wb") as out:
                shutil.copyfileobj(source, out, 1024 * 1024)
                out.flush(); os.fsync(out.fileno())
            require(sha(tmp) == expected_hash, f"Bundle hash mismatch: {rel}")
            os.replace(tmp, target)
    runner, identity, fingerprint = current_identity()
    require(fingerprint == package["campaign_contract_sha256"], "Machine-local code/runtime differs from bundle contract")
    require(sha(MANIFEST) == package["campaign_manifest_sha256"], "Imported campaign manifest hash mismatch")
    require(sha(CALIBRATION) == package["calibration_sha256"], "Imported C3 calibration profile hash mismatch")
    digest, _ = calendar_contract()
    require(digest == package["calendar_contract_sha256"], "Imported paired calendar set mismatch")
    c4 = c4_runner()
    verified = c4.verify_snapshot()
    require(verified["snapshot_id"] == package["c4_snapshot_id"], "Imported C4 snapshot mismatch")
    rows = c4.verify_calendars()
    return {"status": "bundle_imported_and_verified", "simulation_started": False,
            "commit": current_commit, "campaign_contract_sha256": fingerprint,
            "calendar_entries": len(read_json(INDEX)), "c4_positions": len(rows),
            "c4_snapshot_id": verified["snapshot_id"],
            "external_runtime_hashes_verified": len(package.get("external_file_hashes", {}))}


def verify_shard(kind: str) -> dict:
    contract = read_json(HERE / "parallel_campaign_contract.json")
    runner, identity, fingerprint = current_identity()
    require(fingerprint == contract["campaign_contract_sha256"], "Current runtime/source contract mismatch")
    require(sha(MANIFEST) == contract["campaign_manifest_sha256"], "Campaign manifest differs from split contract")
    digest, entries = calendar_contract()
    require(digest == contract["C0_calendar_contract_sha256"], "Paired calendar set differs from split contract")
    calibration = read_json(CALIBRATION)
    require(sha(CALIBRATION) == contract["C3_calibration_sha256"] and
            calibration.get("status") == "frozen_and_accepted" and
            calibration.get("final_profile_id") == "reduction_11",
            "C3 calibration differs from frozen split contract")
    if kind == "primary-c1c2":
        migrated = read_json(MANIFEST)
        continuation=migrated.get("continuation", {})
        parent_path=HERE/continuation.get("parent_manifest_path", "__missing__")
        require(parent_path.is_file() and sha(parent_path)==continuation.get("parent_manifest_sha256"),
                "Primary parent-manifest archive is absent or changed")
        require(continuation.get("legacy_C0_final_records") == 240,
                "Primary host has no audited C0 continuation record")
        c0 = [r for r in read_ledger(LEDGER) if r.get("stage") == "final" and
              r.get("campaign_treatment", r.get("treatment")) == "C0"]
        require(len(c0) == 240, "Primary host must retain all 240 completed C0 records")
    elif kind == "replica-c1c2":
        continuation = read_json(MANIFEST).get("continuation", {})
        parent_path = HERE / continuation.get("parent_manifest_path", "__missing__")
        require(parent_path.is_file() and sha(parent_path) == continuation.get("parent_manifest_sha256"),
                "Imported C1/C2 host is missing the audited parent-manifest archive")
        rows = read_ledger(LEDGER)
        unexpected = [row.get("execution_id") for row in rows if row.get("stage") == "final" and
                      row.get("campaign_treatment") not in ("C1", "C2")]
        require(not unexpected, f"C1/C2 replica contains final rows outside its assigned shard: {unexpected[:5]}")
        c4_ledger = C4_DIR / "results/C4/ledger.jsonl"
        require(not c4_ledger.is_file() or c4_ledger.stat().st_size == 0,
                "C1/C2 replica unexpectedly contains C4 final results")
    else:
        c4 = c4_runner(); c4manifest = c4.verify_snapshot(); c4rows = c4.verify_calendars()
        require(c4manifest["snapshot_id"] == contract["C4_snapshot_id"] and len(c4rows) == 180,
                "C4 snapshot/calendar matrix mismatch on secondary host")
    runner.check_resources_for_jobs(1)
    return {"status": "shard_preflight_pass", "shard": kind, "simulation_started": False,
            "commit": identity["commit"], "campaign_contract_sha256": fingerprint,
            "calendar_entries": len(entries), "calendar_contract_sha256": digest,
            "C3_profile": calibration["final_profile_id"],
            "C4_snapshot_id": contract["C4_snapshot_id"],
            "resources": {"available_memory_gib": round(runner.mem_available_gib(), 2),
                          "free_disk_gb": round(runner.free_gb(), 2), "jobs": 1}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--prepare-primary", action="store_true",
                       help="validate C0 and write the explicit continuation manifest; no simulations")
    group.add_argument("--export-secondary-bundle", metavar="PATH",
                       help="package calendars, accepted profile and runtime identity for the remote C1/C2 host")
    group.add_argument("--import-secondary-bundle", metavar="PATH",
                       help="verify commit/runtime, then import calendars/profile for the C1/C2 host")
    group.add_argument("--verify-primary", action="store_true",
                       help="verify the prepared C1/C2 host")
    group.add_argument("--verify-c1-c2-replica", action="store_true",
                       help="verify an imported C1/C2 host; C0 result files are not required there")
    group.add_argument("--verify-secondary", action="store_true",
                       help="verify the imported C3/C4 host including the frozen C4 snapshot")
    args = parser.parse_args()
    if args.prepare_primary:
        result = prepare_primary()
    elif args.export_secondary_bundle:
        result = export_bundle(Path(args.export_secondary_bundle))
    elif args.import_secondary_bundle:
        result = import_bundle(Path(args.import_secondary_bundle))
    elif args.verify_primary:
        result = verify_shard("primary-c1c2")
    elif args.verify_c1_c2_replica:
        result = verify_shard("replica-c1c2")
    else:
        result = verify_shard("secondary-c3c4")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
