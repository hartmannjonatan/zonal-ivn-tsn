#!/usr/bin/env python3
"""Classic CAN worst-case response-time analysis of the Fever FR250 message set,
compared with the simulated 10BASE-T1S latencies (follow-up F8).

Analysis: Davis, Burns, Bril, Lukkien, "Controller Area Network (CAN)
schedulability analysis: Refuted, revisited and revised", Real-Time Systems
35(3), 2007 (eqs. for C_m, B_m, t_m, Q_m, w_m(q), R_m), for an error-free bus,
fixed-priority non-preemptive arbitration, zero queuing jitter (variant: jitter
= one bit-time-scaled frame), deadlines = periods.

  C_m = (g + 8 s_m + 13 + floor((g + 8 s_m - 1) / 4)) * tau_bit   (worst-case stuffing)
        g = 34 (11-bit ID) or 54 (29-bit ID), s_m = data bytes
  B_m = max C_k over lower-priority messages k
  t_m = B_m + sum_{k in hep(m)} ceil((t_m + J_k) / T_k) C_k          (busy period)
  Q_m = ceil((t_m + J_m) / T_m)
  w_m(q) = B_m + q C_m + sum_{k in hp(m)} ceil((w_m(q) + J_k + tau_bit) / T_k) C_k
  R_m = max_{q < Q_m} (J_m + w_m(q) - q T_m + C_m)

Priority = arbitration order of the identifier: an 11-bit ID is compared with the
first 11 bits of a 29-bit ID and wins ties (SRR/IDE recessive).
Bit rates: 500 kbit/s (inferred from the capture), plus 250 kbit/s and 1 Mbit/s.
Variants: flows.json as used in F4; and 000C7FD3 with its measured 80 ms period.
The T1S values are the simulated max latencies of F4 (fever_ecu.csv, fever_gw.csv).
"""
import csv
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SIM = ROOT / "simulations"
RES = SIM / "zonal/t1s_results"
FLOWS = json.loads((SIM / "zonal/traffic/fever/flows.json").read_text())


def is_ext(can_id):
    return len(can_id) > 3          # oscilloscope export: 8 hex digits = extended, 3 = standard


def arb_key(can_id):
    v = int(can_id, 16)
    return (v >> 18, 1, v & 0x3FFFF) if is_ext(can_id) else (v, 0, 0)


def c_bits(can_id, dlc):
    g = 54 if is_ext(can_id) else 34
    return g + 8 * dlc + 13 + (g + 8 * dlc - 1) // 4


def rta(msgs, rate, jitter=False, key=None):
    tau = 1 / rate
    ms = sorted(msgs, key=key or (lambda m: arb_key(m["id"])))
    for m in ms:
        m["C"] = c_bits(m["id"], m["dlc"]) * tau
        m["T"] = m["period_ms"] / 1000
        m["J"] = m["C"] if jitter else 0.0
    out = {}
    for i, m in enumerate(ms):
        hp, lp = ms[:i], ms[i + 1:]
        B = max((k["C"] for k in lp), default=0.0)
        t = m["C"]
        for _ in range(10000):                       # busy period
            nt = B + sum(math.ceil((t + k["J"]) / k["T"]) * k["C"] for k in hp + [m])
            if abs(nt - t) < 1e-12:
                break
            t = nt
            if t > 10:
                break
        Q = math.ceil((t + m["J"]) / m["T"])
        R = 0.0
        for q in range(Q):
            w = B + q * m["C"]
            for _ in range(10000):
                nw = B + q * m["C"] + sum(math.ceil((w + k["J"] + tau) / k["T"]) * k["C"] for k in hp)
                if abs(nw - w) < 1e-12:
                    break
                w = nw
                if w > 10:
                    break
            R = max(R, m["J"] + w - q * m["T"] + m["C"])
        out[m["id"]] = R
    return out


def simulate_can(msgs, rate, horizon=6.0, key=None):
    """Event simulation of the CAN bus with the trace phases (one hyperperiod, 6 s):
    non-preemptive fixed-priority arbitration, worst-case stuffing frame lengths,
    error-free. Returns max latency (release -> end of frame) per ID."""
    import heapq
    key = key or (lambda m: arb_key(m["id"]))
    tau = 1 / rate
    rel = []
    for m in msgs:
        C, T, ph = c_bits(m["id"], m["dlc"]) * tau, m["period_ms"] / 1000, m["phase_ms"] / 1000
        k = 0
        while ph + k * T < horizon:
            rel.append((ph + k * T, m["id"], C, key(m)))
            k += 1
    rel.sort()
    t, i, ready, worst = 0.0, 0, [], {}
    while i < len(rel) or ready:
        if not ready and rel[i][0] > t:
            t = rel[i][0]
        while i < len(rel) and rel[i][0] <= t + 1e-12:
            r, mid, C, k = rel[i]
            heapq.heappush(ready, (k, r, mid, C))
            i += 1
        k, r, mid, C = heapq.heappop(ready)        # arbitration at the start of a frame
        t += C
        worst[mid] = max(worst.get(mid, 0.0), t - r)
    return worst


def dm_key(m):
    """Deadline-monotonic priority order (hypothetical re-assignment of identifiers)."""
    return (m["deadline_ms"], arb_key(m["id"]))


def t1s_max(name):
    p = RES / name
    return {r["can_id"]: float(r["max_us"]) for r in csv.DictReader(p.open())} if p.exists() else {}


def main():
    variants = {"flows.json": FLOWS,
                "000C7FD3 at 80 ms": [dict(f, period_ms=80, deadline_ms=80) if f["id"] == "000C7FD3" else dict(f)
                                      for f in FLOWS]}
    t1s_ecu, t1s_gw = t1s_max("fever_ecu.csv"), t1s_max("fever_gw.csv")
    rows = []
    for vname, msgs in variants.items():
        for rate in (250e3, 500e3, 1e6):
            for jit in (False, True):
                R = rta([dict(m) for m in msgs], rate, jit)
                util = sum(c_bits(m["id"], m["dlc"]) / rate / (m["period_ms"] / 1000) for m in msgs)
                for m in msgs:
                    rows.append({"variant": vname, "bitrate_kbps": int(rate / 1000), "jitter": jit,
                                 "can_id": m["id"], "class": m["class"], "period_ms": m["period_ms"],
                                 "can_wcrt_us": round(R[m["id"]] * 1e6, 1),
                                 "can_wcrt_over_deadline_pct": round(R[m["id"]] * 1e3 / m["deadline_ms"] * 100, 2),
                                 "can_bus_utilisation_pct": round(util * 100, 1),
                                 "t1s_ecu_max_us": t1s_ecu.get(m["id"], ""), "t1s_gw_max_us": t1s_gw.get(m["id"], "")})
    with (RES / "can_rta_fever.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    print("| Variant | CAN bit rate | Jitter | Bus utilisation (worst-case frames) | CAN WCRT max (all / CRITICAL) | "
          "Worst WCRT / deadline | Deadline misses (WCRT > D) |")
    print("|---|---|---|---|---|---|---|")
    for vname in variants:
        for rate in (250, 500, 1000):
            for jit in (False, True):
                sel = [r for r in rows if r["variant"] == vname and r["bitrate_kbps"] == rate and r["jitter"] == jit]
                crit = [r for r in sel if r["class"] == "CRITICAL"]
                print(f"| {vname} | {rate} kbit/s | {'C_m' if jit else '0'} | {sel[0]['can_bus_utilisation_pct']} % | "
                      f"{max(r['can_wcrt_us'] for r in sel):.0f} / {max(r['can_wcrt_us'] for r in crit):.0f} µs | "
                      f"{max(r['can_wcrt_over_deadline_pct'] for r in sel):.1f} % | "
                      f"{sum(1 for r in sel if r['can_wcrt_over_deadline_pct'] > 100)} |")
    print("\nPer CAN ID, flows.json, 500 kbit/s, no jitter: CAN WCRT (analysis) vs T1S simulated max (F4)\n")
    print("| CAN ID | Class | Period ms | CAN WCRT µs | T1S max µs (per ECU) | T1S max µs (gateway) |")
    print("|---|---|---|---|---|---|")
    sel = [r for r in rows if r["variant"] == "flows.json" and r["bitrate_kbps"] == 500 and not r["jitter"]]
    for r in sorted(sel, key=lambda r: arb_key(r["can_id"])):
        print(f"| {r['can_id']} | {r['class']} | {r['period_ms']} | {r['can_wcrt_us']:.0f} | "
              f"{r['t1s_ecu_max_us']} | {r['t1s_gw_max_us']} |")
    print("\nPriority order and release pattern, 500 kbit/s (max latency over all IDs / CRITICAL / misses):\n")
    print("| Case | All IDs max µs | CRITICAL max µs | IDs over deadline |")
    print("|---|---|---|---|")
    base = [dict(m) for m in FLOWS]
    cases = [("CAN WCRT, ID priorities (analysis, synchronous release)", rta([dict(m) for m in base], 500e3)),
             ("CAN WCRT, deadline-monotonic priorities (analysis)", rta([dict(m) for m in base], 500e3, key=dm_key)),
             ("CAN simulated, ID priorities, trace phases (6 s)", simulate_can(base, 500e3)),
             ("CAN simulated, deadline-monotonic, trace phases (6 s)", simulate_can(base, 500e3, key=dm_key)),
             ("T1S simulated (F4, per ECU)", {k: v / 1e6 for k, v in t1s_ecu.items()}),
             ("T1S simulated (F4, gateway)", {k: v / 1e6 for k, v in t1s_gw.items()})]
    dl = {m["id"]: m["deadline_ms"] / 1000 for m in base}
    cl = {m["id"]: m["class"] for m in base}
    summary = []
    for name, R in cases:
        allm = max(R.values()) * 1e6
        crm = max(v for k, v in R.items() if cl[k] == "CRITICAL") * 1e6
        miss = [k for k, v in R.items() if v > dl[k]]
        summary.append({"case": name, "all_max_us": round(allm, 1), "critical_max_us": round(crm, 1),
                        "ids_over_deadline": " ".join(miss)})
        print(f"| {name} | {allm:.0f} | {crm:.0f} | {len(miss)} {('(' + ', '.join(miss) + ')') if miss else ''} |")
    with (RES / "can_vs_t1s_summary.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(summary[0]))
        w.writeheader()
        w.writerows(summary)
    crit = [r for r in sel if r["class"] == "CRITICAL"]
    print(f"\nCRITICAL IDs, 500 kbit/s: CAN WCRT max {max(r['can_wcrt_us'] for r in crit):.0f} µs; "
          f"T1S simulated max {max(float(r['t1s_ecu_max_us']) for r in crit):.0f} µs (per ECU), "
          f"{max(float(r['t1s_gw_max_us']) for r in crit):.0f} µs (gateway)")


if __name__ == "__main__":
    main()
