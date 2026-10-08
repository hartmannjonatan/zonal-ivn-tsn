import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts/run"))
import validate_c0


class DropScopeReconciliationTests(unittest.TestCase):
    def test_reconciles_equal_post_warmup_counts_without_equating_full_run_total(self):
        result = validate_c0.reconcile_queue_overflow_scopes(
            "Validate_C0_L3_A1",
            [{"queue": "CSW.eth[0]/TC4", "sca_post_warmup": 19388,
              "vector_post_warmup": 19388}],
            whole_run_drop_total=20138,
        )
        self.assertEqual(result["whole_run_minus_post_warmup_scope_delta"], 750)
        self.assertEqual(
            result["sca_and_timestamped_queue_overflow_drops_post_warmup_including_drain"],
            19388,
        )

    def test_rejects_sca_and_vector_disagreement_in_shared_scope(self):
        with self.assertRaisesRegex(RuntimeError, "differs from timestamped"):
            validate_c0.reconcile_queue_overflow_scopes(
                "fixture",
                [{"queue": "SW.eth[0]/TC4", "sca_post_warmup": 9,
                  "vector_post_warmup": 8}],
                whole_run_drop_total=20,
            )

    def test_rejects_post_warmup_total_above_whole_run_audit(self):
        with self.assertRaisesRegex(RuntimeError, "exceeds whole-run"):
            validate_c0.reconcile_queue_overflow_scopes(
                "fixture",
                [{"queue": "SW.eth[0]/TC4", "sca_post_warmup": 21,
                  "vector_post_warmup": 21}],
                whole_run_drop_total=20,
            )


if __name__ == "__main__":
    unittest.main()
