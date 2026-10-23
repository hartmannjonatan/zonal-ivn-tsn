#!/usr/bin/env python3
"""Static and post-run contract checks for the frozen official C4 treatment."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
C4 = ROOT / "simulations/c4_official"
CAMPAIGN = ROOT / "simulations/campaigns/p1-v2-official-2026-10/c4_official"
PROFILE_JSON = C4 / "frozen_d3_l2_profile.json"
PROFILE_CSV = C4 / "frozen_profile_table.csv"
PROFILE_INI = C4 / "C4_D3_absolute_profile.ini"
CONFIG_INI = CAMPAIGN / "c4_official.ini"
TAS_EGRESSES = {"HPC.eth[0]", "CSW.eth[1]", "CSW.eth[2]", "CSW.eth[3]"}
NO_CBS = {
    "Z1.ZCPU.eth[0]/TC4", "Z2.ZCPU.eth[0]/TC4", "Z3.ZSW.eth[1]/TC4"
}
BRAKE_SP_EGRESSES = {"Z1.ZSW.eth[4]", "Z2.ZSW.eth[4]", "Z3.ZSW.eth[5]"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def profile_rows() -> list[dict[str, str]]:
    with PROFILE_CSV.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    require(len(rows) == 24, f"expected 24 frozen CBS rows, got {len(rows)}")
    keys = [f"{r['egress']}/TC{r['TC']}" for r in rows]
    require(len(keys) == len(set(keys)), "duplicate egress/TC in frozen profile")
    require(not (set(keys) & NO_CBS), "transient-only SP egress received CBS")
    return rows


def ini_parameters(path: Path) -> dict[tuple[str, str], str]:
    values: dict[tuple[str, str], str] = {}
    pattern = re.compile(r'^\*\.([^=]+?)\s*=\s*(.*?)\s*$')
    for line in path.read_text().splitlines():
        m = pattern.match(line.strip())
        if m:
            module, name = m.group(1).rsplit(".", 1)
            values[(module, name)] = m.group(2).strip('"')
    return values


def validate_static() -> dict:
    frozen = json.loads(PROFILE_JSON.read_text())
    rows = profile_rows()
    require(frozen.get("canonical_sha256") == "571e3a10e004005b2994aadc6dc495db730f6e9b8842af2550ebcbb3d6eb33be",
            "canonical D3 profile hash differs from accepted exploratory candidate")
    table_rates = {f"{r['egress']}/TC{r['TC']}": int(r["idleSlope_bps"]) for r in rows}
    require(table_rates == frozen["effective_profile_bps"], "CSV table differs from frozen JSON profile")
    params = ini_parameters(PROFILE_INI)
    expected_params = {}
    for r in rows:
        egress, tc = r["egress"], r["TC"]
        prefix = f"{egress}.macLayer.queue.transmissionSelectionAlgorithm[{tc}]"
        expected_params[(prefix, "typename")] = "Ieee8021qCreditBasedShaper"
        expected_params[(prefix, "idleSlope")] = f"{r['idleSlope_bps']}bps"
        expected_params[(prefix, "initialCredit")] = f"{r['initialCredit']}b"
        expected_params[(prefix, "transmitCreditLimit")] = f"{r['transmitCreditLimit']}b"
        expected_params[(prefix, "minCredit")] = f"{r['minCredit']} b"
        expected_params[(prefix, "maxCredit")] = f"{r['maxCredit']} b"
        expected_params[(prefix, "maxInterferenceSize")] = "inf b"
        expected_params[(prefix, "accumulateCreditInGuardBand")] = r["accumulateCreditInGuardBand"].lower()
        expected_params[(prefix, "extraLength")] = r["extraLength"]
        expected_params[(prefix, "extraDuration")] = r["extraDuration"]
    for key, expected in expected_params.items():
        actual = params.get(key)
        require(actual == expected, f"profile INI mismatch {key}: {actual!r} != {expected!r}")
    ini_modules = {m.rsplit(".macLayer.queue.transmissionSelectionAlgorithm[", 1)[0] + "/TC" + m.rsplit("[", 1)[1].split("]", 1)[0]
                   for m, p in params if p == "typename" and "transmissionSelectionAlgorithm[" in m}
    expected_modules = set(table_rates)
    require(ini_modules == expected_modules, f"profile INI module set mismatch: missing={expected_modules-ini_modules}, extra={ini_modules-expected_modules}")

    cfg = CONFIG_INI.read_text()
    require("[Config C4D3_TAS]" in cfg, "missing C4D3_TAS")
    require("C4D3AbsoluteProfile" in cfg and "C4GptpInstrumented" in cfg,
            "C4 config does not extend frozen CBS and clock configurations")
    require("[Config Validate_C4_L3_" not in cfg, "L3 must not be an executable C4 config")
    require("[Config C4_open" not in cfg and "C4_noTAS" not in cfg,
            "open-gate C4 must not be an official treatment")
    require("[55us, 45us]" in cfg and "[30us, 70us]" in cfg,
            "GCL duration schedule differs from D3_coordinated_20pct")
    for text in ("70us", "69.324us", "99.324us", "scheduleForAbsoluteTime = true",
                 'clockModule = "^.^.^.^.clock"', "enableImplicitGuardBand = true"):
        require(text in cfg, f"missing frozen GCL property: {text}")
    scheduled_ports = set(re.findall(r'^\*\.(HPC\.eth\[0\]|CSW\.eth\[1\.\.3\])\.macLayer\.queue\.transmissionGate\[', cfg, re.M))
    require(scheduled_ports == {"HPC.eth[0]", "CSW.eth[1..3]"}, f"unexpected scheduled egress declarations: {scheduled_ports}")
    require(all(f"*.{port}.macLayer.queue.transmissionGate[*].durations = []" in cfg for port in BRAKE_SP_EGRESSES),
            "brake last-hop gates must remain permanently open under SP")
    require(all(f"*.{port}.macLayer.queue.transmissionGate[*].durations = []" in cfg for port in ("Z1.ZCPU.eth[0]", "Z2.ZCPU.eth[0]", "Z3.ZSW.eth[1]")),
            "transient-only SP egresses must remain permanently open")

    return {
        "status": "pass",
        "profile_hash": frozen["canonical_sha256"],
        "cbs_modules": len(rows),
        "no_cbs_sp_egresses": sorted(NO_CBS),
        "tas_egresses": sorted(TAS_EGRESSES),
        "brake_sp_egresses": sorted(BRAKE_SP_EGRESSES),
        "l3_executable": False,
        "official_open_gate_treatment": False,
    }


def _unit_value(value: str) -> float:
    m = re.fullmatch(r"\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*(bps|b)?\s*", value)
    require(m is not None, f"cannot parse numeric SCA value {value!r}")
    return float(m.group(1))


def validate_effective_profile(params: dict[tuple[str, str], str]) -> dict:
    """Check SCA parameters after a manual run; absent type/credit is a hard error."""
    rows = profile_rows()
    expected = {f"ZonalIVN.{r['egress']}.macLayer.queue.transmissionSelectionAlgorithm[{r['TC']}]": r for r in rows}
    actual_modules = {module for module, name in params if name == "typename" and "transmissionSelectionAlgorithm[" in module and
                      params[(module, name)].endswith("Ieee8021qCreditBasedShaper")}
    require(actual_modules == set(expected), f"runtime CBS module set mismatch: missing={set(expected)-actual_modules}, extra={actual_modules-set(expected)}")
    verified = 0
    for module, row in expected.items():
        require(params.get((module, "typename"), "").endswith("Ieee8021qCreditBasedShaper"), f"{module}: CBS type not instantiated")
        require(abs(_unit_value(params.get((module, "idleSlope"), "nan")) - int(row["idleSlope_bps"])) <= 0.5,
                f"{module}: idleSlope mismatch")
        fields = {"initialCredit": int(row["initialCredit"]), "transmitCreditLimit": int(row["transmitCreditLimit"]),
                  "minCredit": float(row["minCredit"]), "maxCredit": float(row["maxCredit"])}
        for name, want in fields.items():
            actual = params.get((module, name))
            require(actual is not None, f"{module}: SCA missing {name}")
            if math.isinf(want):
                require(actual.lower().replace(" ", "") in ("inf", "infb", "-inf", "-infb"), f"{module}: {name} mismatch {actual}")
            else:
                require(abs(_unit_value(actual) - want) <= 0.5, f"{module}: {name} mismatch")
        require(params.get((module, "accumulateCreditInGuardBand"), "").lower() == "false", f"{module}: guard-band credit policy mismatch")
        require(abs(_unit_value(params.get((module, "extraLength"), "nan")) - 64) <= 0.5, f"{module}: extraLength mismatch")
        extra_duration = params.get((module, "extraDuration"), "").replace(" ", "").lower()
        require(extra_duration in ("0s", "0", "0.0s"), f"{module}: extraDuration mismatch")
        max_interference = params.get((module, "maxInterferenceSize"), "").replace("\\", "").replace('"', "").replace(" ", "").lower()
        require(max_interference in ("infb", "inf"), f"{module}: maxInterferenceSize mismatch")
        bitrate = _unit_value(params.get((module, "bitrate"), "nan"))
        idle = int(row["idleSlope_bps"])
        spend = _unit_value(params.get((module, "transmitCreditSpendRate"), "nan"))
        require(abs(spend - (bitrate - idle)) <= 0.5, f"{module}: derived sendSlope/credit spend mismatch")
        send_slope = _unit_value(params.get((module, "sendSlope"), "nan"))
        require(abs(send_slope - int(row["sendSlope_bps"])) <= 0.5, f"{module}: sendSlope mismatch")
        verified += 1
    return {"status": "pass", "observed_cbs_modules": len(actual_modules), "verified_cbs_modules": verified}


def validate_gcl_params(params: dict[tuple[str, str], str]) -> dict:
    expected = {}
    for port in TAS_EGRESSES:
        for tc in range(8):
            module = f"ZonalIVN.{port}.macLayer.queue.transmissionGate[{tc}]"
            expected[module] = ([55e-6, 45e-6], 70e-6 if port == "HPC.eth[0]" else 69.324e-6) if tc < 7 else (
                [30e-6, 70e-6], 0.0 if port == "HPC.eth[0]" else 99.324e-6)
    for module, (durations, offset) in expected.items():
        actual_durations = params.get((module, "durations"))
        require(actual_durations is not None, f"{module}: missing effective durations")
        nums = [float(x) for x in re.findall(r"([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)", actual_durations)]
        units = re.findall(r"(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\s*(s|ms|us|ns|ps)", actual_durations)
        scale = {"s": 1, "ms": 1e-3, "us": 1e-6, "ns": 1e-9, "ps": 1e-12}
        got = [x * scale[u] for x, u in zip(nums, units)]
        require(len(got) == 2 and all(abs(a-b) <= 1e-12 for a,b in zip(got,durations)), f"{module}: GCL duration mismatch {actual_durations}")
        got_offset = params.get((module, "offset"))
        require(got_offset is not None, f"{module}: missing effective offset")
        parsed = re.fullmatch(r"\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*(s|ms|us|ns|ps)\s*", got_offset)
        require(parsed is not None, f"{module}: invalid offset {got_offset}")
        got_offset_s = float(parsed.group(1)) * scale[parsed.group(2)]
        require(abs((got_offset_s - offset) % 100e-6) <= 1e-12 or abs((offset-got_offset_s) % 100e-6) <= 1e-12,
                f"{module}: offset modulo-period mismatch {got_offset}")
        require(params.get((module, "initiallyOpen")) == "true", f"{module}: initiallyOpen mismatch")
        require(params.get((module, "scheduleForAbsoluteTime")) == "true", f"{module}: scheduleForAbsoluteTime mismatch")
        require(params.get((module, "enableImplicitGuardBand")) == "true", f"{module}: implicit guard-band mismatch")
        require(params.get((module, "clockModule"), "").strip('"') == "^.^.^.^.clock", f"{module}: local clock reference mismatch")
    unexpected = []
    for (module, name), value in params.items():
        if name == "durations" and ".transmissionGate[" in module and value not in ("[]", ""):
            if module not in expected:
                unexpected.append(module)
    require(not unexpected, f"periodic gates outside four shared egresses: {unexpected}")
    return {"status": "pass", "scheduled_gate_modules": len(expected), "tas_egresses": sorted(TAS_EGRESSES)}


def self_test() -> dict:
    static = validate_static()
    rows = profile_rows()
    fake = {}
    for r in rows:
        module = f"ZonalIVN.{r['egress']}.macLayer.queue.transmissionSelectionAlgorithm[{r['TC']}]"
        fake[(module, "typename")] = "Ieee8021qCreditBasedShaper"
        fake[(module, "idleSlope")] = f"{r['idleSlope_bps']}bps"
        fake[(module, "initialCredit")] = f"{r['initialCredit']}b"
        fake[(module, "transmitCreditLimit")] = f"{r['transmitCreditLimit']}b"
        fake[(module, "minCredit")] = f"{r['minCredit']} b"
        fake[(module, "maxCredit")] = f"{r['maxCredit']} b"
        fake[(module, "accumulateCreditInGuardBand")] = "false"
        fake[(module, "extraLength")] = "64b"
        fake[(module, "extraDuration")] = "0s"
        fake[(module, "bitrate")] = f"{r['bitrate_bps']}bps"
        fake[(module, "transmitCreditSpendRate")] = f"{int(r['bitrate_bps'])-int(r['idleSlope_bps'])}bps"
        fake[(module, "sendSlope")] = f"{r['sendSlope_bps']}bps"
        fake[(module, "maxInterferenceSize")] = "inf b"
    good = validate_effective_profile(fake)
    bad_no_cbs = dict(fake)
    for key in list(bad_no_cbs):
        if "CSW.eth[3]" in key[0] and "transmissionSelectionAlgorithm" in key[0]:
            del bad_no_cbs[key]
    try:
        validate_effective_profile(bad_no_cbs)
        raise AssertionError("validator accepted historical no-CBS signature")
    except ValueError:
        pass
    historical_no_cbs = (ROOT / "simulations/pilot/c4_real_clock_service_margin/results/technical/"
                         "network_name_smoke/Pilot_C4compensated_L2_A1-#0.sca")
    historical_no_cbs_rejected = None
    if historical_no_cbs.is_file():
        historical_params = {}
        for line in historical_no_cbs.read_text(errors="replace").splitlines():
            if line.startswith("par "):
                _, module, name, value = line.split(" ", 3)
                historical_params[(module, name)] = value.strip().strip('"')
        try:
            validate_effective_profile(historical_params)
            raise AssertionError("validator accepted the preserved historical no-CBS SCA")
        except ValueError:
            historical_no_cbs_rejected = True
    gates = {}
    for port in TAS_EGRESSES:
        for tc in range(8):
            module = f"ZonalIVN.{port}.macLayer.queue.transmissionGate[{tc}]"
            is_tc7 = tc == 7
            gates[(module, "durations")] = "[30us,70us]" if is_tc7 else "[55us,45us]"
            gates[(module, "offset")] = ("0s" if port == "HPC.eth[0]" else "99.324us") if is_tc7 else (
                "70us" if port == "HPC.eth[0]" else "69.324us")
            gates[(module, "initiallyOpen")] = "true"
            gates[(module, "scheduleForAbsoluteTime")] = "true"
            gates[(module, "enableImplicitGuardBand")] = "true"
            gates[(module, "clockModule")] = "^.^.^.^.clock"
    good_gcl = validate_gcl_params(gates)
    wrong_rpm_phase = dict(gates)
    wrong_rpm_phase[("ZonalIVN.CSW.eth[1].macLayer.queue.transmissionGate[7]", "offset")] = "0us"
    try:
        validate_gcl_params(wrong_rpm_phase)
        raise AssertionError("validator accepted RPM's documented wrong-phase signature")
    except ValueError:
        pass
    return {"static": static, "synthetic_runtime_contract": good,
            "synthetic_gcl_contract": good_gcl,
            "known_no_cbs_rejected": True,
            "preserved_historical_no_cbs_sca_rejected": historical_no_cbs_rejected,
            "known_rpm_wrong_phase_rejected_by_gcl_contract": True}


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), indent=2))
    else:
        print(json.dumps(validate_static(), indent=2))
