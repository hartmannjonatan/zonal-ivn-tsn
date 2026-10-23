import hashlib
import importlib.util
import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "simulations/campaigns/p1-v2-official-2026-10/merge_campaign_shards.py"
SPEC = importlib.util.spec_from_file_location("merge_campaign_shards", SCRIPT)
MERGE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MERGE)


def facts(payload: bytes) -> dict:
    return {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}


class CampaignTransferBundleTests(unittest.TestCase):
    def test_inspects_complete_hash_verified_bundle(self):
        commit = "a" * 40
        contract_hash = "b" * 64
        c1_path = "simulations/campaigns/p1-v2-official-2026-10/results/final/C1/result.json"
        c2_path = "simulations/campaigns/p1-v2-official-2026-10/results/final/C2/result.json"
        ledger_path = "simulations/campaigns/p1-v2-official-2026-10/results/runs.jsonl"
        shard_path = "simulations/campaigns/p1-v2-official-2026-10/results/shard_manifest.json"
        outputs = {
            c1_path: b'{"treatment":"C1"}\n',
            c2_path: b'{"treatment":"C2"}\n',
            ledger_path: b'{"stage":"final"}\n',
            shard_path: b'{"status":"completed"}\n',
        }
        transfer = {
            "campaign_id": "p1-v2-official-2026-10",
            "campaign_contract_sha256": contract_hash,
            "calendar_contract_sha256": "c" * 64,
            "campaign_manifest_sha256": "d" * 64,
            "execution_ids": [],
            "merge_started": False,
            "shard": "C1C2",
            "shard_manifest_sha256": facts(outputs[shard_path])["sha256"],
            "simulation_started": False,
            "source_commit": commit,
            "source_ledger_sha256": facts(outputs[ledger_path])["sha256"],
            "treatment_files": {"C1": {c1_path: facts(outputs[c1_path])},
                                "C2": {c2_path: facts(outputs[c2_path])}},
        }
        transfer_bytes = (json.dumps(transfer, sort_keys=True) + "\n").encode()
        members = dict(outputs)
        members[MERGE.TRANSFER_MANIFEST_MEMBER] = transfer_bytes
        index = {
            "schema_version": MERGE.TRANSFER_BUNDLE_SCHEMA,
            "campaign_id": "p1-v2-official-2026-10",
            "source_commit": commit,
            "campaign_contract_sha256": contract_hash,
            "members": {name: facts(payload) for name, payload in members.items()},
        }
        index_bytes = (json.dumps(index, sort_keys=True) + "\n").encode()
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_path = Path(temp_dir) / "shard.tar.gz"
            with tarfile.open(archive_path, "w:gz") as archive:
                for name, payload in {**members, MERGE.TRANSFER_BUNDLE_INDEX: index_bytes}.items():
                    info = tarfile.TarInfo(name)
                    info.size = len(payload)
                    archive.addfile(info, io.BytesIO(payload))
            parsed, tar_members, parsed_index = MERGE.inspect_transfer_bundle(archive_path)

        self.assertEqual(parsed["source_commit"], commit)
        self.assertEqual(set(parsed_index["members"]), set(members))
        self.assertIn(c1_path, tar_members)
        self.assertIn(c2_path, tar_members)

    def test_rejects_path_traversal_member(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_path = Path(temp_dir) / "unsafe.tar.gz"
            with tarfile.open(archive_path, "w:gz") as archive:
                info = tarfile.TarInfo("../outside.txt")
                payload = b"bad"
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))
            with tarfile.open(archive_path, "r:gz") as archive:
                with self.assertRaises(SystemExit):
                    MERGE.safe_tar_members(archive)


if __name__ == "__main__":
    unittest.main()
