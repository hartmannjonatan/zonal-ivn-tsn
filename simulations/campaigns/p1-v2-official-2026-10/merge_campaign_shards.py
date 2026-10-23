#!/usr/bin/env python3
"""Return the remote C1/C2 shard to the C0-owning C3/C4 host and merge offline."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
RESULTS = HERE / "results"
LEDGER = RESULTS / "runs.jsonl"
INDEX = RESULTS / "calendars/calendar_index.json"
CALIBRATION = RESULTS / "calibration/C3_calibration.json"
EXPECTED = {t: {f"{t}_{load}_A{alignment}_seed{seed}"
                for load in ("L0", "L1", "L2", "L3") for alignment in ("A0", "A1")
                for seed in range(1001, 1031)} for t in ("C1", "C2")}


def require(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(message)


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def read_rows(path: Path) -> list[dict]:
    rows = []
    if path.is_file():
        with path.open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                if line.strip():
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError as exc:
                        raise SystemExit(f"Invalid JSONL row {line_number} in {path}: {exc}") from exc
    return rows


def files_under(path: Path) -> dict[str, dict]:
    require(path.is_dir(), f"Shard result directory missing: {path}")
    return {str(item.relative_to(ROOT)): {"bytes": item.stat().st_size, "sha256": sha(item)}
            for item in sorted(path.rglob("*")) if item.is_file() and not item.name.endswith(".lock")}


def c4_runner():
    path = HERE / "c4_official/run_c4_campaign.py"
    spec = importlib.util.spec_from_file_location("c4_runner_for_merge", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def campaign_runner():
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    spec = importlib.util.spec_from_file_location("campaign_runner_for_merge", HERE / "run_campaign.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    module.INET = Path(os.environ.get("INET_ROOT", "/home/jonatan/omnetpp/samples/inet-4.7.0")).resolve()
    module.OMNETPP = Path(os.environ.get("OMNETPP_ROOT", "/home/jonatan/omnetpp")).resolve()
    return module


def write_transfer_manifest(destination: Path) -> dict:
    shard_path = RESULTS / "shard_manifest.json"
    shard = read_json(shard_path)
    require(shard.get("status") == "completed" and shard.get("treatments") == ["C1", "C2"],
            "Remote C1/C2 shard must be complete before transfer")
    rows = [row for row in read_rows(LEDGER) if row.get("stage") == "final" and
            row.get("campaign_treatment") in ("C1", "C2")]
    for treatment in ("C1", "C2"):
        ids = {row.get("execution_id") for row in rows if row.get("campaign_treatment") == treatment}
        require(ids == EXPECTED[treatment] and len(ids) == 240,
                f"Remote {treatment} ledger must contain its exact 240 admissible IDs")
    require(len(rows) == 480 and all(row.get("simulation_valid") is True for row in rows),
            "Remote C1/C2 results contain duplicate or technically invalid records")
    campaign = read_json(HERE / "campaign_manifest.json")
    split = read_json(HERE / "parallel_campaign_contract.json")
    require(campaign.get("commit") == split.get("commit"), "Remote campaign commit differs from split contract")
    require(shard.get("campaign_contract_sha256") == split.get("campaign_contract_sha256") and
            shard.get("calendar_contract_sha256") == split.get("C0_calendar_contract_sha256") and
            shard.get("final_ledger_sha256") == sha(LEDGER),
            "Remote C1/C2 shard manifest does not certify this runtime, calendar set, and ledger")
    for row in rows:
        key = f"{row['load_name']}/{row['aggregation_name']}/seed{row['seed']}"
        calendar_index = read_json(INDEX)
        require(key in calendar_index and calendar_index[key]["sha256"] == row.get("calendar_sha256"),
                f"Remote {row['execution_id']} has a calendar outside the imported paired set")
    inventories = {treatment: files_under(RESULTS / "final" / treatment)
                   for treatment in ("C1", "C2")}
    payload = {
        "schema_version": 1,
        "campaign_id": "p1-v2-official-2026-10",
        "shard": "C1C2",
        "source_commit": campaign["commit"],
        "campaign_contract_sha256": split["campaign_contract_sha256"],
        "campaign_manifest_sha256": sha(HERE / "campaign_manifest.json"),
        "calendar_contract_sha256": split["C0_calendar_contract_sha256"],
        "shard_manifest_sha256": sha(shard_path),
        "source_ledger_sha256": sha(LEDGER),
        "execution_ids": sorted(EXPECTED["C1"] | EXPECTED["C2"]),
        "treatment_files": inventories,
        "merge_started": False,
        "simulation_started": False,
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, destination)
    return {"status": "transfer_manifest_written", "path": str(destination),
            "C1C2_records": len(rows),
            "files": sum(len(value) for value in inventories.values()),
            "bytes_to_transfer": sum(info["bytes"] for values in inventories.values()
                                     for info in values.values()),
            "simulation_started": False}


def verify_inventory(inventory: dict[str, dict]) -> None:
    for relative, facts in inventory.items():
        path = ROOT / relative
        require(path.is_file(), f"Transferred result file is missing: {relative}")
        require(path.stat().st_size == facts["bytes"] and sha(path) == facts["sha256"],
                f"Transferred file differs from its source hash/size: {relative}")


def merge_transferred(manifest_path: Path, source_ledger: Path) -> dict:
    manifest = read_json(manifest_path)
    require(manifest.get("shard") == "C1C2" and manifest.get("merge_started") is False,
            "Expected a fresh C1/C2 transfer manifest")
    campaign = read_json(HERE / "campaign_manifest.json")
    split = read_json(HERE / "parallel_campaign_contract.json")
    require(campaign.get("commit") == manifest.get("source_commit") == split.get("commit"),
            "Source and destination checkouts are not at the same campaign commit")
    require(split.get("campaign_contract_sha256") == manifest.get("campaign_contract_sha256"),
            "Campaign runtime/source contract differs between machines")
    require(sha(HERE / "campaign_manifest.json") == manifest.get("campaign_manifest_sha256"),
            "Campaign manifest differs from the imported shard")
    require(split.get("C0_calendar_contract_sha256") == manifest.get("calendar_contract_sha256"),
            "Paired transient calendar contracts differ")
    shard_path = RESULTS / "parallel-transfer/C1C2_shard_manifest.json"
    require(shard_path.is_file() and sha(shard_path) == manifest.get("shard_manifest_sha256"),
            "Transferred C1/C2 shard manifest is missing or has changed")
    source_shard = read_json(shard_path)
    require(source_shard.get("status") == "completed" and source_shard.get("treatments") == ["C1", "C2"] and
            source_shard.get("campaign_contract_sha256") == manifest.get("campaign_contract_sha256") and
            source_shard.get("calendar_contract_sha256") == manifest.get("calendar_contract_sha256"),
            "Transferred C1/C2 shard manifest does not certify the expected completed shard")
    verify_inventory({relative: facts for group in manifest["treatment_files"].values()
                       for relative, facts in group.items()})
    require(sha(source_ledger) == manifest.get("source_ledger_sha256"),
            "Transferred C1/C2 source ledger hash mismatch")
    source_rows = [row for row in read_rows(source_ledger) if row.get("stage") == "final" and
                   row.get("campaign_treatment") in ("C1", "C2")]
    require({row.get("execution_id") for row in source_rows} == set(manifest["execution_ids"])
            and len(source_rows) == 480, "Transferred source ledger does not match its exact C1/C2 matrix")
    require(all(row.get("simulation_valid") is True for row in source_rows),
            "C1/C2 source ledger contains technically invalid results; inspect without merging")
    index = read_json(INDEX)
    for row in source_rows:
        key = f"{row['load_name']}/{row['aggregation_name']}/seed{row['seed']}"
        require(key in index and index[key].get("sha256") == row.get("calendar_sha256"),
                f"C0 calendar on the coordinator does not match {row.get('execution_id')}")
    current_rows = read_rows(LEDGER)
    current = {row.get("execution_id"): row for row in current_rows if row.get("stage") == "final" and
               row.get("campaign_treatment") in ("C1", "C2")}
    source = {row["execution_id"]: row for row in source_rows}
    require(set(current) <= set(source), "Coordinator has unexpected C1/C2 records")
    for execution_id, row in current.items():
        require(row == source[execution_id], f"Already imported C1/C2 row differs: {execution_id}")
    c3_ids = {row.get("execution_id") for row in current_rows if row.get("stage") == "final" and
              row.get("campaign_treatment") == "C3"}
    expected_c3 = {f"C3_{load}_A{alignment}_seed{seed}"
                   for load in ("L0", "L1", "L2") for alignment in ("A0", "A1")
                   for seed in range(1001, 1031)}
    require(c3_ids == expected_c3 and len(c3_ids) == 180,
            "Coordinator must complete the C3 shard before importing C1/C2")
    c3_manifest = read_json(RESULTS / "shard_manifest.json")
    require(c3_manifest.get("status") == "completed" and c3_manifest.get("treatments") == ["C3"],
            "Coordinator C3 shard manifest is not complete")
    c4 = c4_runner()
    c4_snapshot = c4.verify_snapshot()
    c4_rows = c4.read_ledger()
    expected_c4 = {f"C4_{load}_A{alignment}_seed{seed}"
                   for load in ("L0", "L1", "L2") for alignment in ("A0", "A1")
                   for seed in range(1001, 1031)}
    require({row.get("execution_id") for row in c4_rows} == expected_c4 and len(c4_rows) == 180,
            "Coordinator must complete its C4 shard before the final merge")
    require(c4_snapshot.get("snapshot_id") == split.get("C4_snapshot_id"),
            "Coordinator C4 frozen snapshot differs from the split contract")
    to_append = [row for row in source_rows if row["execution_id"] not in current]
    with LEDGER.open("ab") as output:
        for row in to_append:
            output.write((json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode())
        output.flush()
        os.fsync(output.fileno())
    for row in source_rows:
        key = f"{row['load_name']}/{row['aggregation_name']}/seed{row['seed']}"
        treatments = index[key].setdefault("treatments", [])
        for treatment in ("C1", "C2"):
            if row.get("campaign_treatment") == treatment and treatment not in treatments:
                treatments.append(treatment)
    temporary_index = INDEX.with_name(INDEX.name + ".tmp")
    temporary_index.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary_index, INDEX)
    runner = campaign_runner()
    runner.MANIFEST = campaign
    runner.final_campaign(read_json(CALIBRATION), execute_treatments=[])
    summary = read_json(RESULTS / "campaign_results.json")
    require(summary.get("completed_runs") == summary.get("expected_runs") == 900 and
            summary.get("complete") is True, "Rebuilt C0-C3 summary is not 900/900 complete")
    completion = {"campaign_id": manifest["campaign_id"], "status": "parallel shards merged",
                  "C0_C3_completed": summary["completed_runs"], "C0_C3_expected": 900,
                  "C4_completed": len(c4_rows), "C4_expected": 180,
                  "source_commit": manifest["source_commit"],
                  "campaign_contract_sha256": manifest["campaign_contract_sha256"],
                  "C4_snapshot_id": c4_snapshot["snapshot_id"], "simulation_started": False}
    completion_path = RESULTS / "parallel_campaign_merge.json"
    completion_path.write_text(json.dumps(completion, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest["merge_started"] = True
    manifest["merged_records"] = 480
    manifest["merge_summary_sha256"] = sha(completion_path)
    manifest_path.with_name(manifest_path.name + ".merged").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return completion


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write-transfer-manifest", metavar="PATH",
                       help="on the remote C1/C2 host, inventory a completed shard without duplicating it")
    group.add_argument("--merge-transferred", action="store_true",
                       help="on the C0/C3/C4 host, verify and merge the returned C1/C2 shard offline")
    parser.add_argument("--manifest", type=Path, help="transfer-manifest path on the C0-owning host")
    parser.add_argument("--source-ledger", type=Path, help="copied remote runs.jsonl on the coordinator")
    args = parser.parse_args()
    if args.write_transfer_manifest:
        result = write_transfer_manifest(Path(args.write_transfer_manifest))
    else:
        require(args.manifest is not None and args.source_ledger is not None,
                "--merge-transferred requires --manifest and --source-ledger")
        result = merge_transferred(args.manifest, args.source_ledger)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
