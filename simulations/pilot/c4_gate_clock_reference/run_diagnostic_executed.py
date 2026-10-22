#!/usr/bin/env python3
"""Sequential, isolated runner for the A005 gate-clock diagnostic."""
from __future__ import annotations
import argparse, csv, gzip, hashlib, importlib.util, json, os, shutil, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SIM = ROOT / "simulations"
OLD = SIM / "pilot/c4_cbs_tas_investigation"
OUT = HERE / "results"
os.environ.setdefault("MALLOC_ARENA_MAX", "2")
os.environ.setdefault("OMP_NUM_THREADS", "1")
TARGET_EGRESSES = ("HPC.eth[0]", "CSW.eth[1]", "CSW.eth[2]", "CSW.eth[3]")
QUEUE_MODULES = [f"ZonalIVN.{e}.macLayer.queue.queue[4]" for e in TARGET_EGRESSES]
GATE_MODULES = [f"ZonalIVN.{e}.macLayer.queue.transmissionGate[4]" for e in TARGET_EGRESSES]
CREDIT_MODULES = [f"ZonalIVN.{e}.macLayer.queue.transmissionSelectionAlgorithm[4]" for e in TARGET_EGRESSES]
CLOCK_MODULES = ["ZonalIVN.HPC.clock", "ZonalIVN.CSW.clock", *(f"ZonalIVN.Z{i}.ZSW.clock" for i in (1, 2, 3))]
VARIANTS = ("A005_local", "A005_ideal_all", "A005_ideal_HPC")
VARIANT_CLOCKS = {
    "A005_local": set(),
    "A005_ideal_all": set(TARGET_EGRESSES),
    "A005_ideal_HPC": {"HPC.eth[0]"},
}

spec = importlib.util.spec_from_file_location("c4_gate_clock_inherited_runner", OLD / "run_investigation.py")
inherited = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = inherited
assert spec.loader is not None
spec.loader.exec_module(inherited)
r = inherited.r

# Redirect every generated result/config reference into this isolated pilot.
inherited.HERE = HERE
inherited.OUT = OUT
inherited.REGISTRY = HERE / "candidate_registry.json"
r.HERE = HERE
r.OUT = OUT
r.PILOT_INI = HERE / "pilot.ini"
r.PROTOCOL = HERE / "protocol.md"
r.PROFILE_JSON = SIM / "campaigns/p1-v2-official-2026-10/results/calibration/C3_calibration.json"
r.PROFILE_CHECKPOINT = SIM / "campaigns/p1-v2-official-2026-10/results/progress.json"
r.P1_PDF = ROOT / "docs/design/P1-v4.pdf"
r.MAX_JOBS = 1
r.FREE_FLOOR_GB = 45.0

def a005_profile_for_load(manifest, load, variant):
    if load != 2 or variant != "C4compensated":
        raise RuntimeError("This isolated diagnostic is restricted to L2/A1 C4 A005")
    registry = json.loads((HERE / "candidate_registry.json").read_text())
    candidate = next(c for c in registry["candidates"] if c["candidate_id"] == "A005")
    profile = {}
    for key, value in candidate["effective_profile_bps"].items():
        egress, tc = key.rsplit("/TC", 1)
        profile[egress, int(tc)] = int(value)
    return profile
r.run_profile_for_load = a005_profile_for_load

def diagnostic_plan(phase: str, registry=None):
    if phase not in ("diagnostic", "clock_reference_diagnostic"):
        return []
    variants = VARIANTS
    return [{"execution_id": f"{v}_L2_A1_seed41_v1", "variant": "C4compensated",
             "cell": "L2_A1", "load_index": 2, "alignment": 1, "seed": 41,
             "kind": "gate_clock_reference_diagnostic", "candidate_id": "A005",
             "diagnostic_variant": v, "allow_inadmissible": True}
            for v in variants]

inherited.plan_for_phase = diagnostic_plan
r.run_plan = lambda: diagnostic_plan("diagnostic")

# Keep exact C4/A005 command generation, changing only the four gate clockModule
# values. The original A005 command and calendar are preserved in this folder.
ORIGINAL_ADD_MODES = inherited.add_target_modes
def add_modes_and_gate_clock(run_spec, manifest):
    config, dest, extras = ORIGINAL_ADD_MODES(run_spec, manifest)
    old_network = "--network=zonal_ivn_tsn.simulations.pilot.c4_cbs_tas_investigation.precision.ZonalIVN"
    new_network = "--network=zonal_ivn_tsn.simulations.pilot.c4_gate_clock_reference.precision.ZonalIVN"
    extras = [new_network if arg == old_network else arg for arg in extras]
    ideal_egresses = VARIANT_CLOCKS[run_spec["diagnostic_variant"]]
    for egress in TARGET_EGRESSES:
        if egress in ideal_egresses:
            prefix = f"--*.{egress}.macLayer.queue.transmissionGate[*].clockModule="
            for i, arg in enumerate(extras):
                if arg.startswith(prefix):
                    extras[i] = prefix + '""'
    # Pin measurement vectors on only the four target TC4 egress queues.
    for module in QUEUE_MODULES:
        parameter = "*." + module.removeprefix("ZonalIVN.")
        extras += [f"--{parameter}.{name}.result-recording-modes=vector" for name in
                   ("queueLength", "queueBitLength", "incomingPacketLengths",
                    "outgoingPacketLengths", "droppedPacketLengthsQueueOverflow")]
    return config, dest, extras
inherited.add_target_modes = add_modes_and_gate_clock
r.simulation_overrides = add_modes_and_gate_clock

# The inherited postprocessor is intentionally single-run and streaming for
# service events. Retain the source vector only until our event-order extractor
# finishes; never let the inherited raw-output cleanup delete it first.
inherited.ORIG_COMPRESS = lambda dest, config, run_dir, keep: None
r.compress_or_remove_raw = lambda dest, config, run_dir, keep: None

def _definitions(vec_path: Path):
    defs = {}
    opener = gzip.open if vec_path.suffix == ".gz" else open
    with opener(vec_path, "rt", errors="replace") as stream:
        for line in stream:
            if line.startswith("vector "):
                p = line.rstrip("\n").split(" ", 4)
                if len(p) == 5:
                    defs[int(p[1])] = (p[2], p[3])
            elif line and line[0].isdigit():
                break
    return defs

def extract_event_records(dest: Path, config: str, run_dir: Path, variant: str):
    vec = dest / f"{config}-#0.vec"
    if not vec.is_file():
        raise RuntimeError(f"raw vector missing before event-order extraction: {vec}")
    definitions = _definitions(vec)
    selected = {}
    for vector_id, (module, name) in definitions.items():
        if module in QUEUE_MODULES and name.startswith((
                "queueLength:", "queueBitLength:", "incomingPacketLengths:",
                "outgoingPacketLengths:", "droppedPacketLengthsQueueOverflow:")):
            selected[vector_id] = (module, name)
        elif module in GATE_MODULES and name.startswith(("gateState:", "guardBandState:")):
            selected[vector_id] = (module, name)
        elif module in CREDIT_MODULES and name.startswith("numCredits:"):
            selected[vector_id] = (module, name)
        elif module in CLOCK_MODULES and name.startswith("timeChanged:"):
            selected[vector_id] = (module, name)
        elif any(module == f"ZonalIVN.{e}.phyLayer.transmitter" for e in TARGET_EGRESSES) and name.startswith("transmitting:"):
            selected[vector_id] = (module, name)
    required = {"queueBitLength:", "queueLength:", "incomingPacketLengths:",
                "outgoingPacketLengths:", "numCredits:", "gateState:", "guardBandState:", "timeChanged:"}
    present = {name.split(":", 1)[0] + ":" for _, name in selected.values()}
    missing = required - present
    if missing:
        raise RuntimeError(f"selected vector definitions missing {sorted(missing)}")
    out = run_dir / "gate_clock_queue_events.csv.gz"
    opener = gzip.open if vec.suffix == ".gz" else open
    row_order = 0
    counts = {}
    with gzip.open(out, "wt", newline="", encoding="utf-8", compresslevel=6) as output:
        writer = csv.writer(output)
        writer.writerow(("record_order", "vector_id", "event_number", "simtime_s", "value", "module", "statistic"))
        with opener(vec, "rt", errors="replace") as stream:
            for line in stream:
                p = line.split()
                if len(p) != 4 or not p[0].isdigit():
                    continue
                vector_id = int(p[0]); meta = selected.get(vector_id)
                if meta is None:
                    continue
                module, name = meta
                row_order += 1
                counts[name] = counts.get(name, 0) + 1
                writer.writerow((row_order, vector_id, p[1], p[2], p[3], module, name))
    if row_order == 0 or any(counts.get(name, 0) == 0 for _, name in selected.values()):
        raise RuntimeError("event-order vector extraction produced empty selected vectors")
    metadata = {"variant": variant, "config": config, "raw_vector_sha256": r.sha256(vec),
                "event_file": str(out.relative_to(HERE)), "selected_vector_count": len(selected),
                "selected_vectors": {str(k): {"module": v[0], "statistic": v[1], "samples": counts.get(v, 0)}
                                     for k, v in selected.items()},
                "records": row_order, "record_order": "original line order in OMNeT++ .vec file",
                "time_window_s": [1.0, 31.0], "status": "complete"}
    (run_dir / "gate_clock_queue_events.json").write_text(json.dumps(metadata, indent=2) + "\n")
    # Source vector is discarded only after the compressed selected evidence is
    # readable and all required statistic families are populated.
    with gzip.open(out, "rt", newline="", encoding="utf-8") as stream:
        header = stream.readline()
        first = stream.readline()
        if not header.startswith("record_order,") or not first:
            raise RuntimeError("compressed event evidence failed read-back check")
    vec.unlink()
    return metadata

ORIGINAL_RUN_ONE = inherited.run_one_wrapped
def run_one_with_event_extraction(run_spec, manifest, preflight, freshly_simulated=False):
    row = ORIGINAL_RUN_ONE(run_spec, manifest, preflight, freshly_simulated)
    config = f"Pilot_{run_spec['variant']}_{run_spec['cell']}"
    dest = OUT / "runs" / run_spec["execution_id"]
    run_dir = dest / f"{config}-0"
    metadata = extract_event_records(dest, config, run_dir, run_spec["diagnostic_variant"])
    row["diagnostic_variant"] = run_spec["diagnostic_variant"]
    row["gate_clock_reference"] = {"ideal_simtime_egresses": sorted(VARIANT_CLOCKS[run_spec["diagnostic_variant"]]),
                                   "local_clock_egresses": sorted(set(TARGET_EGRESSES) - VARIANT_CLOCKS[run_spec["diagnostic_variant"]]),
                                   "other_clocks_unchanged": True}
    row["event_order_extraction"] = metadata
    row["retained_raw_vector"] = False
    row["raw_vector_retention_reason"] = "Selected event-number records, clock/gate/credit/queue evidence, SCA, and validation metrics verified in compressed artifacts."
    (dest / "pilot-result.json").write_text(json.dumps(row, indent=2, ensure_ascii=False) + "\n")
    # Replace the ledger's just-written row with enriched metadata.
    ledger = OUT / "runs.jsonl"
    if ledger.exists():
        rows = [json.loads(line) for line in ledger.read_text().splitlines() if line.strip()]
        rows = [row if x.get("execution_id") == run_spec["execution_id"] else x for x in rows]
        ledger.write_text("".join(json.dumps(x, separators=(",", ":"), ensure_ascii=False) + "\n" for x in rows))
    return row
r.run_one = run_one_with_event_extraction

def run_manifest_for_one(variant: str):
    manifest = inherited.manifest_for("diagnostic")
    schedule = [x for x in diagnostic_plan("diagnostic") if x["diagnostic_variant"] == variant]
    manifest["phase"] = "gate_clock_reference_diagnostic"
    manifest["run_schedule"] = schedule
    manifest["budget"] = {"maximum_full_runs": 3, "sequential": True}
    manifest["diagnostic"] = {"exploratory": True, "diagnostic_only": True,
        "official_c4_frozen": False, "A005_candidate_id": "A005",
        "candidate_effective_profile_bps": next(c["effective_profile_bps"] for c in json.loads((HERE / "candidate_registry.json").read_text())["candidates"] if c["candidate_id"] == "A005"),
            "calendar_pairing_signature_expected": "cb74a68801e037dce0480422e4371150c2c95765974b0ef3857f1633b54a600d",
        "calendar_event_count_expected": 60,
        "variant": variant, "gate_clock_ideal_egresses": sorted(VARIANT_CLOCKS[variant]),
        "all_other_parameters_frozen": True}
    for path in (HERE / "run_diagnostic.py", HERE / "clock_drift_ppm_by_seed_node.json",
                 HERE / "precision/plugin/libclockprecision.so",
                 OUT / "calendars/L2_A1/seed41_events.csv"):
        manifest["versions_and_hashes"][str(path.relative_to(ROOT))] = r.sha256(path)
    return manifest

def verify_effective_command_deltas():
    manifest = inherited.manifest_for("diagnostic")
    expected_profiles = [None]
    commands = {}
    candidate = next(c for c in json.loads((HERE / "candidate_registry.json").read_text())["candidates"]
                     if c["candidate_id"] == "A005")
    reference_profile = candidate["effective_profile_bps"]
    for variant in VARIANTS:
        item = next(x for x in diagnostic_plan("diagnostic") if x["diagnostic_variant"] == variant)
        inherited.ACTIVE_SPEC.clear(); inherited.ACTIVE_SPEC.update(item)
        _, _, args = add_modes_and_gate_clock(item, manifest)
        effective = {}
        for arg in args:
            if ".idleSlope=" in arg:
                left, value = arg.split(".idleSlope=", 1)
                egress = left.split("--*.", 1)[1].split(".macLayer", 1)[0]
                tc = left.split("transmissionSelectionAlgorithm[", 1)[1].split("]", 1)[0]
                effective[f"{egress}/TC{tc}"] = int(value.removesuffix("bps"))
        if effective != reference_profile:
            raise RuntimeError(f"{variant}: generated A005 idleSlope vector differs from registered profile")
        clocks = {arg.split(".clockModule=", 1)[0].removeprefix("--*."): arg.split(".clockModule=", 1)[1]
                  for arg in args if ".clockModule=" in arg and
                  any(arg.startswith(f"--*.{egress}.macLayer.queue.transmissionGate") for egress in TARGET_EGRESSES)}
        if len(clocks) != 4:
            raise RuntimeError(f"{variant}: expected four effective shared-egress gate clocks, got {len(clocks)}")
        expected_ideal = VARIANT_CLOCKS[variant]
        for egress in TARGET_EGRESSES:
            key = f"{egress}.macLayer.queue.transmissionGate[*]"
            expected = '""' if egress in expected_ideal else '"^.^.^.^.clock"'
            if clocks.get(key) != expected:
                raise RuntimeError(f"{variant}: unexpected clock reference for {egress}: {clocks.get(key)}")
        commands[variant] = {"effective_profile_bps": effective, "gate_clock_overrides": clocks,
                             "functional_overrides_sha256": hashlib.sha256("\n".join(sorted(
                                 a for a in args if ".clockModule=" in a or ".idleSlope=" in a or
                                 ".durations=" in a or ".offset=" in a or ".initiallyOpen=" in a)).encode()).hexdigest()}
    inherited.ACTIVE_SPEC.clear()
    return commands

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.plan == args.run:
        parser.error("choose exactly one of --plan or --run")
    OUT.mkdir(parents=True, exist_ok=True)
    # Copy the exact paired calendar without regenerating any application event.
    old_calendar = OLD / "results/calendars/L2_A1/seed41_events.csv"
    new_calendar = OUT / "calendars/L2_A1/seed41_events.csv"
    new_calendar.parent.mkdir(parents=True, exist_ok=True)
    if not new_calendar.exists():
        shutil.copy2(old_calendar, new_calendar)
    calendar_content_sha = r.sha256(new_calendar)
    old_index = json.loads((OLD / "results/calendars/calendar_index.json").read_text())
    cal_sha = old_index["L2_A1/seed41"]["sha256"]
    if cal_sha != "cb74a68801e037dce0480422e4371150c2c95765974b0ef3857f1633b54a600d":
        raise SystemExit(f"calendar pairing signature mismatch: {cal_sha}")
    if args.plan:
        command_audit = verify_effective_command_deltas()
        plans = {v: run_manifest_for_one(v) for v in VARIANTS}
        r.write_json(OUT / "plan_index.json", {"protocol": r.PROTOCOL.name, "calendar_pairing_signature": cal_sha,
            "calendar_file_sha256": calendar_content_sha,
            "effective_command_audit": command_audit,
            "runs": [{"variant": v, "execution_id": plans[v]["run_schedule"][0]["execution_id"],
                      "manifest_sha256": hashlib.sha256(json.dumps(plans[v], sort_keys=True).encode()).hexdigest()} for v in VARIANTS],
            "exploratory": True, "diagnostic_only": True, "official_c4_frozen": False})
        for v, manifest in plans.items():
            r.write_json(OUT / f"plan_{v}.json", manifest)
        r.write_json(OUT / "checkpoint.json", {"phase": "planned", "next": VARIANTS[0],
            "completed": [], "active": None, "calendar_pairing_signature": cal_sha,
            "calendar_file_sha256": calendar_content_sha,
            "free_disk_gb": round(r.free_gb(), 2), "available_memory_gb": round(r.memory_available_gb(), 2),
            "exploratory": True, "diagnostic_only": True, "official_c4_frozen": False})
        print(f"Planned 3 sequential full runs; calendar SHA-256 {cal_sha}; free disk {r.free_gb():.1f} GB; available RAM {r.memory_available_gb():.1f} GB")
        return
    plan = json.loads((OUT / "plan_index.json").read_text())
    for variant in VARIANTS:
        manifest = json.loads((OUT / f"plan_{variant}.json").read_text())
        # Verify source/config/profile/calendar identity at every resume point.
        expected_hash = next(x["manifest_sha256"] for x in plan["runs"] if x["variant"] == variant)
        actual_hash = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
        if actual_hash != expected_hash or r.sha256(new_calendar) != calendar_content_sha:
            raise RuntimeError(f"manifest or calendar changed for {variant}")
        if r.official_campaign_active():
            raise RuntimeError("official campaign active; refusing diagnostic run")
        if r.free_gb() < r.FREE_FLOOR_GB:
            raise RuntimeError(f"free disk {r.free_gb():.1f} GB below floor {r.FREE_FLOOR_GB:.1f} GB")
        pid_file = OUT / "active_simulation.pid"
        if pid_file.exists() and Path(f"/proc/{pid_file.read_text().strip()}").exists():
            raise RuntimeError(f"another diagnostic process is active: PID {pid_file.read_text().strip()}")
        r.write_json(OUT / "checkpoint.json", {"phase": "simulating", "next": variant,
            "completed": [x["variant"] for x in plan["runs"] if (OUT / "runs" / x["execution_id"] / "pilot-result.json").exists()],
            "active": variant, "pid": os.getpid(), "calendar_pairing_signature": cal_sha,
            "calendar_file_sha256": calendar_content_sha,
            "free_disk_gb": round(r.free_gb(), 2), "available_memory_gb": round(r.memory_available_gb(), 2),
            "exploratory": True, "diagnostic_only": True, "official_c4_frozen": False})
        # The inherited executor uses cohort parallelism. Restrict its one-item
        # manifest to enforce strict serialization and checkpoint after each.
        r.run_plan = lambda m=manifest: m["run_schedule"]
        manifest["run_schedule"] = [x for x in manifest["run_schedule"] if x["diagnostic_variant"] == variant]
        r.write_json(OUT / "plan.json", manifest)
        current_script_manifest = manifest
        r.execute(current_script_manifest, resume=args.resume or variant != VARIANTS[0])
        inherited.patch_current_views()
        completed = []
        ledger = OUT / "runs.jsonl"
        if ledger.exists():
            completed = [json.loads(line).get("diagnostic_variant") for line in ledger.read_text().splitlines() if line.strip()]
        r.write_json(OUT / "checkpoint.json", {"phase": "between_runs", "next": VARIANTS[VARIANTS.index(variant)+1] if variant != VARIANTS[-1] else None,
            "completed": completed, "active": None, "calendar_pairing_signature": cal_sha,
            "calendar_file_sha256": calendar_content_sha,
            "free_disk_gb": round(r.free_gb(), 2), "available_memory_gb": round(r.memory_available_gb(), 2),
            "exploratory": True, "diagnostic_only": True, "official_c4_frozen": False})
        print(json.dumps({"finished": variant, "free_disk_gb": round(r.free_gb(), 2),
                          "available_memory_gb": round(r.memory_available_gb(), 2), "completed": completed}), flush=True)
    print("All three diagnostic variants completed.")

if __name__ == "__main__":
    main()
