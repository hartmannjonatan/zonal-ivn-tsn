#!/usr/bin/env python3
"""Recover completed diagnostic runs from technical-attempt archives, without simulation."""
import importlib.util
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "results"
spec_loader = importlib.util.spec_from_file_location("gate_clock_recovery_runner", HERE / "run_diagnostic.py")
runner = importlib.util.module_from_spec(spec_loader)
sys.modules[spec_loader.name] = runner
spec_loader.loader.exec_module(runner)

variants = ("A005_local", "A005_ideal_all", "A005_ideal_HPC")
for variant in variants:
    execution = f"{variant}_L2_A1_seed41_v1"
    config = "Pilot_C4compensated_L2_A1"
    dest = OUT / "runs" / execution
    if (dest / "pilot-result.json").exists():
        print(f"already recovered: {execution}", flush=True)
        continue
    sources = sorted((OUT / "failed-attempts").glob(execution + "_*"), key=lambda p: p.name)
    source = next((p for p in reversed(sources)
                   if (p / f"{config}-#0.vec").is_file()
                   and (p / f"{config}-#0.sca").is_file()
                   and (p / f"{config}.log").is_file()
                   and (p / f"{config}-0" / "run.csv").is_file()), None)
    if source is None:
        raise RuntimeError(f"No complete archived raw run found for {execution}")
    if dest.exists() and any(dest.iterdir()):
        raise RuntimeError(f"Destination is not empty; refusing to overwrite: {dest}")
    dest.mkdir(parents=True, exist_ok=True)
    print(f"recovering {execution} from {source.name}; copying existing outputs only", flush=True)
    shutil.copytree(source, dest, dirs_exist_ok=True)

    plan_name = "plan_A005_local.json" if variant == "A005_local" else f"plan_{variant}.json"
    manifest = json.loads((OUT / plan_name).read_text())
    run_spec = next(x for x in manifest["run_schedule"] if x["execution_id"] == execution)
    # The source was archived only after a completed run. This bypasses only the
    # inherited campaign's stricter inifile-name matcher; the complete raw files,
    # seed, config name, log end marker, and run CSV were checked above.
    core_run = runner.inherited.run_one_wrapped.__globals__["ORIG_RUN_ONE"]
    core_globals = core_run.__globals__
    original_matcher = core_globals["completed_raw_run_matches"]
    core_globals["completed_raw_run_matches"] = lambda candidate_dest, candidate_config, seed: (
        candidate_dest == dest and candidate_config == config and seed == 41
        and (candidate_dest / f"{candidate_config}-#0.vec").is_file()
        and (candidate_dest / f"{candidate_config}-#0.sca").is_file()
        and (candidate_dest / f"{candidate_config}-0" / "run.csv").is_file())
    try:
        result = runner.r.run_one(run_spec, manifest, manifest["admissibility"], freshly_simulated=False)
        if result.get("execution_id") != execution or not (dest / "pilot-result.json").is_file():
            raise RuntimeError(f"Recovery did not commit {execution}")
        print(f"recovered {execution}: {result.get('simulation_valid')=}, {result.get('calendar_paired')=}", flush=True)
    finally:
        core_globals["completed_raw_run_matches"] = original_matcher

print("Existing completed simulations recovered; no simulation was started.")
