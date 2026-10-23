import csv
import gzip
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/run"))
import validate_c0  # noqa: E402


class QueueTraceCodecTests(unittest.TestCase):
    def test_compact_trace_recomputes_identically(self):
        with tempfile.TemporaryDirectory() as temp:
            trace = Path(temp) / "queue_occupancy_events.csv.gz"
            metadata = {
                "format": "p1-queue-occupancy-events-v1",
                "time_semantics": "right-continuous",
                "occupancy_unit": "bits",
                "initial_state": "all queues are 0 bits at t=0 s",
                "measurement_window_s": [1.0, 31.0],
                "observation_window_s": [0.0, 31.05],
                "measurement_window_convention": "half-open [start,end); integrate through the end boundary",
                "bin_width_s": 5.0,
                "near_capacity_threshold": 0.90,
                "queues": [{"queue_index": 0, "module": "HPC.eth[0].queue", "tc": 4,
                            "capacity_bits": 1_048_576}],
            }
            with gzip.open(str(trace) + ".meta.json.gz", "wt", encoding="utf-8") as stream:
                json.dump(metadata, stream)
            rows = [
                [0, 0.0, 0], [0, 1.0, 8_192], [0, 6.0, 16_384],
                [0, 11.0, 4_096], [0, 16.0, 8_192], [0, 21.0, 0],
                [0, 26.0, 8_192], [0, 31.0, 0], [0, 31.05, 0],
            ]
            with gzip.open(trace, "wt", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(["queue_index", "timestamp_s", "occupancy_bits"])
                for row in rows:
                    writer.writerow([row[0], format(row[1], ".17g"), row[2]])

            compact = validate_c0.compact_queue_occupancy_trace(trace)
            old_metrics = validate_c0.recompute_queue_occupancy_trace(trace)
            compact_metrics = validate_c0.recompute_queue_occupancy_trace(compact)
            self.assertEqual(old_metrics, compact_metrics)
            self.assertLess(compact.stat().st_size, trace.stat().st_size)

    def test_tick_conversion_rejects_unrepresentable_time(self):
        self.assertEqual(validate_c0._exact_timestamp_ticks(1.000000000000001), 1_000_000_000_000_001)
        with self.assertRaises(RuntimeError):
            validate_c0._exact_timestamp_ticks(1.0000000000000002)


if __name__ == "__main__":
    unittest.main()
