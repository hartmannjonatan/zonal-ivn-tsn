import unittest
import csv
import gzip
import json
import tempfile
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "simulations/campaigns/p1-v2-official-2026-10"))
from calibration_search import (ordered_candidates, profile_signature,
                                propose_increment, reduction_target)
from scripts.run.validate_c0 import recompute_queue_occupancy_trace


class CalibrationSearchTests(unittest.TestCase):
    def setUp(self):
        self.capacities = {"P": 1_000_000_000, "Q": 1_000_000_000}
        self.nominal = {("P", 4): 500_000_000, ("Q", 4): 100_000_000}

    def test_full_ten_percent_increment_is_admissible(self):
        proposal = propose_increment(self.nominal, [(0, 0, 0, "P", 4, "F02")],
                                     self.capacities, {profile_signature(self.nominal)})
        self.assertEqual(proposal["step_bps"], 100_000_000)
        self.assertEqual(proposal["profile"][("P", 4)], 600_000_000)
        self.assertEqual(proposal["rejections"], [])

    def test_increment_crossing_cap_is_rejected_without_clipping(self):
        chosen = {("P", 4): 700_000_000}
        proposal = propose_increment(chosen, [(0, 0, 0, "P", 4, "F02")],
                                     self.capacities, {profile_signature(chosen)})
        self.assertIsNone(proposal["profile"])
        self.assertEqual(proposal["rejections"][0]["reason"], "75pct_cap")
        self.assertEqual(proposal["rejections"][0]["step_bps"], 100_000_000)

    def test_duplicate_profile_is_skipped_for_next_target(self):
        chosen = dict(self.nominal)
        same = dict(chosen); same[("P", 4)] += 100_000_000
        candidates = [(0, 0, 0, "P", 4, "F02"), (0, 0, 1, "Q", 4, "F02")]
        proposal = propose_increment(chosen, candidates, self.capacities,
                                     {profile_signature(chosen), profile_signature(same)})
        self.assertEqual(proposal["target"], ("Q", 4))
        self.assertEqual(proposal["rejections"][0]["reason"], "duplicate_profile")

    def test_no_admissible_proposal_stops_explicitly(self):
        proposal = propose_increment(self.nominal, [], self.capacities,
                                     {profile_signature(self.nominal)})
        self.assertEqual(proposal["stop_reason"], "no_new_admissible_profile")

    def test_reductions_are_bounded_by_nominal_and_deterministic(self):
        chosen = {("P", 4): 600_000_000, ("Q", 4): 120_000_000}
        nominal = {("P", 4): 500_000_000, ("Q", 4): 100_000_000}
        self.assertEqual(reduction_target(chosen, nominal, {}), ("P", 4))
        self.assertIsNone(reduction_target(nominal, nominal, {}))

    def test_ranked_routes_allow_a_modified_target_to_be_proposed_again(self):
        flows = {"F02": {"traffic_class": 4, "source": "CAM1", "destinations": "HPC"}}
        candidates = ordered_candidates({"F02"}, flows, lambda *_: ["CAM1.eth[0]", "CSW.eth[0]"],
                                        {("CAM1.eth[0]", 4), ("CSW.eth[0]", 4)}, {})
        self.assertEqual(candidates[0][3:5], ("CAM1.eth[0]", 4))

    def test_queue_event_trace_recomputes_all_occupancy_indicators(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trace.csv.gz"
            meta = {"format": "p1-queue-occupancy-events-v1",
                    "measurement_window_s": [1.0, 31.0],
                    "observation_window_s": [0.0, 31.05],
                    "bin_width_s": 5.0, "near_capacity_threshold": 0.9,
                    "queues": [{"queue_index": 0, "module": "Q", "tc": 4, "capacity_bits": 100}]}
            with gzip.open(str(path) + ".meta.json.gz", "wt") as out:
                json.dump(meta, out)
            with gzip.open(path, "wt", newline="") as out:
                writer = csv.writer(out)
                writer.writerow(["queue_index", "timestamp_s", "occupancy_bits"])
                for t, value in [(0, 0), (1, 50), (6, 100), (11, 0),
                                 (16, 95), (21, 0), (26, 100), (31, 0), (31.05, 0)]:
                    writer.writerow([0, t, value])
            result = recompute_queue_occupancy_trace(path)[0]
            self.assertEqual(result["mean_occupancy_bits_5s"], [50, 100, 0, 95, 0, 100])
            self.assertEqual(result["mean_occupancy_bits_measurement"], 57.5)
            self.assertEqual(result["max_occupancy_bits"], 100)
            self.assertEqual(result["fraction_measurement_at_least_90pct_capacity"], 0.5)
            self.assertFalse(result["sustained_growth"])


if __name__ == "__main__":
    unittest.main()
