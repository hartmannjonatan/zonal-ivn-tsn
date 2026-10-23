import gzip
import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = ROOT / "simulations/campaigns/p1-v2-official-2026-10/c4_official/run_c4_campaign.py"
SPEC = importlib.util.spec_from_file_location("c4_runner_retention_test", RUNNER_PATH)
C4 = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(C4)


class C4VectorRetentionTests(unittest.TestCase):
    def test_only_dense_credit_and_gate_slice_is_retained(self):
        source_text = (
            "version 3\n"
            "vector 1 X numCredits:vector ETV\n"
            "vector 2 X gateState:vector ETV\n"
            "vector 3 X guardBandState:vector ETV\n"
            "vector 4 X timeChanged:vector ETV\n"
            "1 1 1.009 5\n"
            "1 2 1.015 -2\n"
            "2 3 1.010 1\n"
            "2 4 1.019 0\n"
            "3 5 1.0 1\n"
            "3 6 30.999 0\n"
            "4 7 0.5 0.123\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.vec"
            output = Path(directory) / "runtime.vec.gz"
            source.write_text(source_text, encoding="utf-8")
            summary = C4.retain_runtime_vectors(source, output)
            with gzip.open(output, "rt", encoding="utf-8") as stream:
                retained = stream.read()

        self.assertNotIn("1 1 1.009 5", retained)
        self.assertIn("1 2 1.015 -2", retained)
        self.assertIn("2 3 1.010 1", retained)
        self.assertIn("2 4 1.019 0", retained)
        self.assertIn("3 5 1.0 1", retained)
        self.assertIn("3 6 30.999 0", retained)
        self.assertIn("4 7 0.5 0.123", retained)
        self.assertTrue(summary["lossless_selected_evidence"])
        self.assertEqual(summary["credit_vector_retention_window_s"], [1.01, 1.02])


if __name__ == "__main__":
    unittest.main()
