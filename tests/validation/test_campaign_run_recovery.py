import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CAMPAIGN = ROOT / "simulations/campaigns/p1-v2-official-2026-10"
sys.path.insert(0, str(CAMPAIGN))
SCRIPT = CAMPAIGN / "run_campaign.py"
SPEC = importlib.util.spec_from_file_location("official_run_campaign", SCRIPT)
RUNNER = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(RUNNER)


class CampaignRunRecoveryTests(unittest.TestCase):
    def make_raw_attempt(self, log_text: str):
        config = "Validate_C3_L2_A1"
        seed = 1024
        with tempfile.TemporaryDirectory(prefix="recovery-test-", dir=RUNNER.SIM) as temp:
            dest = Path(temp) / "attempt"
            run_dir = dest / f"{config}-0"
            run_dir.mkdir(parents=True)
            (dest / f"{config}.log").write_text(log_text)
            expected_resultdir = str(dest.relative_to(RUNNER.SIM))
            for extension in ("sca", "vec"):
                (dest / f"{config}-#0.{extension}").write_text(
                    f'attr configname "{config}"\n'
                    f'attr seedset "{seed}"\n'
                    f'attr resultdir "{expected_resultdir}"\n'
                )
            for name in ("run.csv", "events.csv", "drops.csv", "wire.csv",
                         "queues.csv", "releases.csv"):
                (run_dir / name).write_text("fixture\n")
            return RUNNER.completed_raw_run_matches(dest, config, seed)

    def test_rejects_signal_terminated_run_even_when_finish_and_end_exist(self):
        log = ("<!> SIGINT or SIGTERM received, exiting -- at t=9.793s\n"
               "Calling finish() at end of Run #0...\nEnd.\n")
        self.assertFalse(self.make_raw_attempt(log))

    def test_accepts_run_that_reached_configured_time_limit(self):
        log = ("Simulation time limit reached -- at t=31.05s\n"
               "Calling finish() at end of Run #0...\nEnd.\n")
        self.assertTrue(self.make_raw_attempt(log))


if __name__ == "__main__":
    unittest.main()
