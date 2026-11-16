#!/usr/bin/env python3
"""Plausibility and pattern analysis of the Fever FR250 CAN capture.

Input: the oscilloscope serial-decode export used by plca-priority-to
(data/fever_fr250_can_trace.csv: Marked, Time, Serial Bus, ID, Type, DLC, Data,
CRC, Errors). Checks:
  1. integrity: frame types, decode errors, CRC field, DLC/data consistency;
  2. identifier structure: 11/29-bit, J1939 fields (priority, PGN, PDU format,
     source address), proprietary PGNs;
  3. timing per ID: count, median/min/max inter-arrival, jitter, regularity, and
     the period snapping used by gen_flows.py (flows.json);
  4. bus timing: minimum frame spacing -> implied bit rate, bus load estimate;
  5. payload behaviour: constant vs changing payloads, counters.
usage: fever_trace_analysis.py [trace.csv] [flows.json]
       fever_trace_analysis.py --decoded DECODED.csv --dbc FILE.dbc [--flows flows.json]

--decoded analyses a DBC-decoded signal log (one row per received message,
"Timestamp" in ms, one column per DBC signal, values forward-filled), as written
by the Raspberry Pi logger: duration, message rate, per-message rate estimated
from rows whose changed signals all belong to one DBC message, DBC cycle times,
and the vehicle state over time (speed, torque, brake pressure, gear, SOC).
"""
import csv
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

TRACE = Path(sys.argv[1] if len(sys.argv) > 1 else
             "/mnt/c/Users/Jean/Documents/GitLab/plca-priority-to/data/fever_fr250_can_trace.csv")
FLOWS = Path(sys.argv[2] if len(sys.argv) > 2 else
             Path(__file__).resolve().parents[2] / "simulations/zonal/traffic/fever/flows.json")


def t_s(s):
    s = s.strip()
    for suf, k in (("ms", 1e-3), ("us", 1e-6), ("ns", 1e-9), ("s", 1.0)):
        if s.endswith(suf):
            return float(s[:-len(suf)]) * k
    return float(s)


def can_bits(ext, dlc):
    """Nominal CAN 2.0 frame length in bits without stuffing, plus 3-bit IFS."""
    base = 67 if ext else 47     # SOF..EOF fields for extended / standard frames
    return base + 8 * dlc + 3


def main():
    rows = []
    with TRACE.open(newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader((line.replace("\r", "") for line in f)):
            if r.get("ID"):
                rows.append(r)
    rows.sort(key=lambda r: t_s(r["Time"]))
    times = [t_s(r["Time"]) for r in rows]
    span = times[-1] - times[0]
    print(f"## Capture\n- frames: {len(rows)}, span {span * 1e3:.1f} ms "
          f"({times[0] * 1e3:.1f} .. {times[-1] * 1e3:.1f} ms), bus field(s): {sorted(set(r['Serial Bus'] for r in rows))}")

    # 1. integrity
    types = Counter(r["Type"] for r in rows)
    errors = [r for r in rows if r["Errors"].strip()]
    bad_len = [r for r in rows if len(r["Data"].split()) != int(r["DLC"] or 0)]
    no_crc = [r for r in rows if not r["CRC"].strip()]
    print(f"\n## 1. Integrity\n- frame types: {dict(types)}\n- frames with decode errors: {len(errors)}"
          f"\n- DLC/data-length mismatches: {len(bad_len)}\n- frames without CRC field: {len(no_crc)}"
          f"\n- DLC distribution: {dict(Counter(int(r['DLC']) for r in rows))}")

    # 2. identifiers
    by_id = defaultdict(list)
    for r, t in zip(rows, times):
        by_id[r["ID"].strip().upper()].append((t, r))
    # The oscilloscope prints extended (29-bit) IDs with 8 hex digits and standard
    # (11-bit) IDs with 3, so the width is read from the digit count, not the value.
    ext = {i for i in by_id if len(i) > 3}
    print(f"\n## 2. Identifiers\n- distinct IDs: {len(by_id)} ({len(ext)} 29-bit, {len(by_id) - len(ext)} 11-bit)")
    prio, pdu1, prop, sas = Counter(), 0, 0, Counter()
    for i in ext:
        v = int(i, 16)
        p, pf, ps, sa = v >> 26, (v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF
        prio[p] += 1
        pdu1 += pf < 0xF0
        prop += pf == 0xFF or pf == 0xEF
        sas[f"{sa:02X}"] += 1
    print(f"- J1939 priority field of 29-bit IDs: {dict(sorted(prio.items()))}"
          f"\n- PDU1 (destination-specific, PF < 0xF0): {pdu1}; PDU2 (broadcast): {len(ext) - pdu1}"
          f"\n- proprietary PGNs (PF 0xFF Proprietary B / 0xEF Proprietary A): {prop} of {len(ext)}"
          f"\n- source addresses: {len(sas)} -> {dict(sas.most_common())}")

    # 3. timing per ID
    flows = {f["id"]: f for f in json.loads(FLOWS.read_text())}
    print("\n## 3. Timing per ID (inter-arrival, ms)\n")
    print("| ID | n | median | min | max | jitter (max−min)/median | regular | flows.json period | snap error |")
    print("|---|---|---|---|---|---|---|---|---|")
    stats = []
    for i, ev in sorted(by_id.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        ts = [t for t, _ in ev]
        gaps = [(b - a) * 1e3 for a, b in zip(ts, ts[1:])]
        fl = flows.get(i, {})
        if gaps:
            med = statistics.median(gaps)
            jit = (max(gaps) - min(gaps)) / med
            regular = jit < 0.2
            snap = (fl.get("period_ms", med) - med) / med * 100
            stats.append((i, len(ts), med, jit, regular))
            print(f"| {i} | {len(ts)} | {med:.2f} | {min(gaps):.2f} | {max(gaps):.2f} | {jit:.2f} | "
                  f"{'yes' if regular else 'no'} | {fl.get('period_ms', '?')} | {snap:+.1f} % |")
        else:
            stats.append((i, 1, None, None, None))
            print(f"| {i} | 1 | — | — | — | — | — (seen once) | {fl.get('period_ms', '?')} (assumed) | — |")
    multi = [s for s in stats if s[2] is not None]
    reg = [s for s in multi if s[4]]
    print(f"\n- IDs seen ≥ 2 times: {len(multi)}; regular (jitter < 20 %): {len(reg)}; "
          f"seen once (period unknown, ≥ capture span assumed): {len(stats) - len(multi)}")
    print(f"- flows.json total: {sum(1000 / f['period_ms'] for f in flows.values()):.0f} frames/s vs "
          f"{len(rows) / span:.0f} frames/s measured in the capture")

    # 4. bus timing
    gaps_all = sorted((b - a) for a, b in zip(times, times[1:]))
    min_gap = gaps_all[0]
    bits = sum(can_bits(r["ID"].strip().upper() in ext, int(r["DLC"])) for r in rows)
    print(f"\n## 4. Bus timing\n- smallest spacing between consecutive frames: {min_gap * 1e6:.0f} µs "
          f"(5th percentile {gaps_all[len(gaps_all) // 20] * 1e6:.0f} µs)")
    for rate in (250e3, 500e3, 1e6):
        ext8 = can_bits(True, 8) / rate
        print(f"  - at {rate / 1e3:.0f} kbit/s an extended 8-byte frame lasts ≥ {ext8 * 1e6:.0f} µs "
              f"(≈ {ext8 * 1.15 * 1e6:.0f} µs with typical stuffing); bus load ≈ "
              f"{bits / span / rate * 100:.1f} % (no stuffing) – {bits * 1.15 / span / rate * 100:.1f} % (+15 % stuffing)")

    # 5. payloads
    const, changing = [], []
    for i, ev in by_id.items():
        datas = {r["Data"].strip() for _, r in ev}
        (const if len(datas) == 1 else changing).append(i)
    multi_ids = [i for i, ev in by_id.items() if len(ev) > 1]
    print(f"\n## 5. Payloads\n- IDs with ≥ 2 frames: {len(multi_ids)}; constant payload: "
          f"{sum(1 for i in multi_ids if i in const)}; changing payload: {sum(1 for i in multi_ids if i in changing)}")
    counters = []
    for i in multi_ids:
        frames = [bytes.fromhex(r["Data"].replace(" ", "")) for _, r in by_id[i]]
        for b in range(min(len(x) for x in frames)):
            seq = [x[b] for x in frames]
            d = [(y - x) % 256 for x, y in zip(seq, seq[1:])]
            if len(d) >= 3 and len(set(d)) == 1 and d[0] != 0:
                counters.append((i, b, d[0]))
                break
    print(f"- byte positions behaving as rolling counters (constant non-zero increment): "
          f"{[f'{i} byte {b} (+{d})' for i, b, d in counters] or 'none'}")


def parse_dbc(path):
    import re
    text = Path(path).read_text(encoding="latin1")
    msgs, sig2msg, cur = {}, {}, None
    for line in text.splitlines():
        m = re.match(r"BO_ (\d+) (\w+): (\d+) (\w+)", line)
        if m:
            cur = m.group(2)
            msgs[cur] = {"id": int(m.group(1)) & 0x1FFFFFFF, "dlc": int(m.group(3)), "tx": m.group(4)}
            continue
        m = re.match(r"\s+SG_ (\w+)", line)
        if m and cur:
            sig2msg[m.group(1)] = cur
    for m in re.finditer(r'BA_ "GenMsgCycleTime" BO_ (\d+) (\d+);', text):
        for v in msgs.values():
            if v["id"] == int(m.group(1)) & 0x1FFFFFFF:
                v["cycle_ms"] = int(m.group(2))
    return msgs, sig2msg


def decoded_main(decoded, dbc, flows_path):
    msgs, sig2msg = parse_dbc(dbc)
    with open(decoded, newline="") as f:
        r = csv.reader(f)
        hdr = next(r)
        col_msg = [sig2msg.get(h) for h in hdr]
        prev, n, t_first, t_last = None, 0, None, None
        attributed = defaultdict(list)          # msg -> timestamps (ms)
        unattributed = ambiguous = 0
        per_second = Counter()
        watch = ["ESC_ABS_VehicleSpeed", "Actual_Motor_speed", "ActualMotorTorque", "DriverDemandTorque",
                 "AcceleratorPedalPosition", "ESC_MasCylBrakePressure", "Gear_status", "Battery_Soc",
                 "Battery_Current", "Charge_Connect_State", "Lateral_Acceleration", "Longitudinal_Acceleration"]
        widx = {w: hdr.index(w) for w in watch if w in hdr}
        series = defaultdict(list)
        for row in r:
            n += 1
            t = float(row[0])
            t_first = t if t_first is None else t_first
            t_last = t
            per_second[int(t // 1000)] += 1
            if prev is not None:
                changed = {col_msg[k] for k in range(1, len(row)) if row[k] != prev[k] and col_msg[k]}
                if len(changed) == 1:
                    attributed[changed.pop()].append(t)
                elif not changed:
                    unattributed += 1
                else:
                    ambiguous += 1
            prev = row
            if n % 200 == 0:
                for w, k in widx.items():
                    series[w].append((t, row[k]))
    dur = (t_last - t_first) / 1000
    print(f"## Decoded capture {Path(decoded).name}\n- rows (messages): {n}, timestamps {t_first:.0f}..{t_last:.0f} ms "
          f"-> {dur:.1f} s, {n / dur:.0f} messages/s on average")
    rates = sorted(per_second.values())
    print(f"- messages per second: min {rates[0]}, median {rates[len(rates) // 2]}, max {rates[-1]} "
          f"(over {len(rates)} one-second bins)")
    print(f"- {len(hdr) - 1} signal columns from {len({m for m in col_msg if m})} of {len(msgs)} DBC messages")
    print(f"- rows attributable to one message by a value change: {sum(len(v) for v in attributed.values())}; "
          f"no value changed: {unattributed}; changes in several messages: {ambiguous}")
    print("\n| DBC message | CAN ID | DBC cycle ms | attributed rows | min period from changes ms | "
          "median period from changes ms |\n|---|---|---|---|---|---|")
    for name, m in sorted(msgs.items(), key=lambda kv: kv[1]["id"]):
        ts = attributed.get(name, [])
        gaps = [b - a for a, b in zip(ts, ts[1:]) if b > a]
        print(f"| {name} | {m['id']:08X} | {m.get('cycle_ms', '—')} | {len(ts)} | "
              f"{min(gaps) if gaps else '—'} | {statistics.median(gaps) if gaps else '—'} |")
    print("\n## Vehicle state (sampled every 200 rows)\n")
    print("| Signal | min | max | distinct values | share of samples ≠ first value |\n|---|---|---|---|---|")
    for w, v in series.items():
        vals = [x for _, x in v if x not in ("",)]
        num = []
        for x in vals:
            try:
                num.append(float(x))
            except ValueError:
                pass
        distinct = len(set(vals))
        moved = sum(1 for x in vals if x != vals[0]) / len(vals) if vals else 0
        rng = f"{min(num):g} | {max(num):g}" if num else "— | —"
        print(f"| {w} | {rng} | {distinct} | {moved * 100:.0f} % |")
    return series


if __name__ == "__main__":
    if "--decoded" in sys.argv:
        import argparse
        ap = argparse.ArgumentParser()
        ap.add_argument("--decoded", required=True)
        ap.add_argument("--dbc", required=True)
        ap.add_argument("--flows", default=str(FLOWS))
        a = ap.parse_args()
        decoded_main(a.decoded, a.dbc, a.flows)
    else:
        main()
