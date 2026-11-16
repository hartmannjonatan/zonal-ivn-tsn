#!/usr/bin/env python3
"""Analytic worst-case bound of the radar latency on a T1S PLCA segment,
compared with the simulated maxima (phase sweeps and extra-node scenarios).

Model (10 Mb/s, max_bc = 0, every node sends at most one frame per TO):
  frame time  t(B)  = (MAC bytes + 8 preamble/SFD) * 8 / 10 Mb/s
  data TO     D(B)  = t(B) + IPG (96 bit = 9.6 us)
  empty TO    E     = to_timer 32 bit = 3.2 us
  beacon      Bc    = beacon 20 bit + detection, taken as 2.2 us
  radar frame t_r   = t(64 B) = 57.6 us
  fixed path  H0    = 2.16 us   (T1S min latency 59.76 us - t_r: PHY/propagation + 1 Gb/s store-and-forward)
  1 Gb/s queueing Hq <= 37.0 us (one 1542 B wire frame in progress at ZSW->CSW, plus one in progress and one
                     TC6 LiDAR frame queued ahead at CSW->HPC: 3 x 12.336 us)
Ideal PLCA wait W (radar frame held at PLCA until its next TO):
  standard  : radar just missed its own TO; the rest of the cycle passes:
              W = sum over the other slots (E if silent, D if it may send) + Bc
  priorityTo: a priority TO follows every data TO; worst = ready just after a commit guard
              (1.6 us left), then beacon and the longest other data TO: W = 1.6 + Bc + max D_other,
              or the standard wait when the radar precedes no data TO, whichever is larger.
  multiTo   : longest gap between two radar slots (own slot just missed + Bc if the gap wraps).
Bound L = W + t_r + H0 + Hq.  Floor (unavoidable for any non-preemptive TO scheme when another
node's frame starts just before the radar is ready): D_other + t_r + H0.

INET's PLCA holds a frame in the delay line for at most 400 bit (40 us); if the TO has not
come, it signals a logical collision and the CSMA/CD MAC backs off (51.2 us slots) and retries.
Retries can make the radar miss a TO it would otherwise have used, so simulated maxima can
exceed the ideal bound. The script reports the radar MAC's logical collisions per scenario.
"""
import csv
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SIM = ROOT / "simulations"
RES = SIM / "zonal/t1s_results"

RATE = 10e6
IPG, E, BC, GUARD = 9.6, 3.2, 2.2, 1.6
H0, HQ = 2.16, 3 * 12.336


def t(mac_bytes):
    return (mac_bytes + 8) * 8 / RATE * 1e6


def D(mac_bytes):
    return t(mac_bytes) + IPG


T_R = t(64)
D_SMALL = D(64)          # window, sensor, radar frames (64 B MAC)
D_HEAVY = D(1522)        # 1472 B UDP payload + VLAN
D_FRAG = D(295)          # 245 B UDP payload + VLAN


def slots_standard(extra, d_x):
    """Other slots of a Z2/Z3 segment: coordinator (window), WINDOW (silent), extra nodes."""
    return [D_SMALL, E] + [d_x] * extra


def bounds(mode, extra=0, d_x=D_SMALL):
    others = slots_standard(extra, d_x)
    w_std = sum(others) + BC
    if mode == "standard":
        w = w_std
    elif mode == "priorityTo":
        w = max(GUARD + BC + max(others), D_SMALL + E + BC)  # radar directly after coordinator
    elif mode == "multiTo":
        # radar owns every other slot: 0 1 2 1 3 1 ... ; gaps are single other slots,
        # except the wrap-around gap (last other slot + beacon + coordinator)
        last = others[-1] if extra else others[1]
        w = max(E + max(others), E + last + BC + D_SMALL)
    floor = max(o for o in others) + T_R + H0
    return w, w + T_R + H0 + HQ, floor


def mac_collisions(result_dir, config, node, itervar=None):
    """Logical collisions at the radar MAC (collision signal toggles / 2), per itervar value."""
    out = defaultdict(int)
    for sca in result_dir.glob(f"{config}-*.sca"):
        text = sca.read_text(errors="replace")
        key = None
        if itervar:
            m = re.search(rf"^itervar {itervar} (\S+)", text, re.M)
            key = m.group(1) if m else None
        m = re.search(rf"^scalar \S+\.{node}\.eth\[0\]\.mac collision:count (\S+)", text, re.M)
        if m:
            out[key] += int(float(m.group(1))) // 2
    return out


def main():
    rows = []
    # Phase sweeps (Z2/Z3 base segment, 3 nodes), band 45-130 us common to all modes.
    sweeps = {"standard": ("radar_phase_standard.csv", SIM / "results/t1s/radar_phase", "T1S_RadarPhase"),
              "priorityTo": ("radar_phase_priorityTo.csv", SIM / "results/t1s/prioplca/radar_phase_PrioTo",
                             "T1S_RadarPhase_PrioTo"),
              "multiTo": ("radar_phase_multiTo.csv", SIM / "results/t1s/prioplca/radar_phase_MultiTo",
                          "T1S_RadarPhase_MultiTo")}
    for mode, (name, rdir, cfg) in sweeps.items():
        data = [r for r in csv.DictReader((RES / name).open()) if 45 <= int(r["radar_offset_us"]) <= 130]
        obs = max(max(float(r["F06_max_us"]), float(r["F07_max_us"])) for r in data)
        coll = sum(mac_collisions(rdir, cfg, n, "radarOffset").get(str(int(r["radar_offset_us"])), 0)
                   for r in data for n in ("RADAR1", "RADAR2"))
        w, bound, floor = bounds(mode)
        rows.append(("Phase sweep, 3 nodes (radar offset 45–130 µs)", mode, w, floor, bound, obs, coll,
                     2 * 18 * 1000))
    # Extra nodes.
    profiles = {"SENSOR": D_SMALL, "HEAVY": D_HEAVY, "HEAVYFRAG": D_FRAG}
    modes = {"Std": "standard", "PrioTo": "priorityTo", "MultiTo": "multiTo"}
    extra_rows = list(csv.DictReader((RES / "extra_nodes_modes.csv").open()))
    for prof, d_x in profiles.items():
        for m_key, mode in modes.items():
            cfg = f"T1S_EXTRA_{prof}_{m_key}"
            sel = [r for r in extra_rows if r["config"] == cfg and r["flow"] in ("F06", "F07")]
            if not sel:
                continue
            rdir = SIM / "results/t1s/prioplca" / cfg
            for extra in ("2", "5"):
                obs = max(float(r["max_us"]) for r in sel if r["extra"] == extra)
                coll = sum(mac_collisions(rdir, cfg, n, "extra").get(extra, 0) for n in ("RADAR1", "RADAR2"))
                w, bound, floor = bounds(mode, int(extra), d_x)
                rows.append((f"{prof.lower()} nodes, {3 + int(extra)} per segment", mode, w, floor, bound, obs,
                             coll, 2 * 3 * 2000))
    print("| Scenario | Mode | Ideal PLCA wait W µs | Floor µs | Bound µs (W + t_r + H0 + Hq) | Observed max µs "
          "| Within bound | Radar MAC logical collisions / packets |")
    print("|---|---|---|---|---|---|---|---|")
    out = []
    for sc, mode, w, floor, bound, obs, coll, pkts in rows:
        ok = obs <= bound + 1e-6
        print(f"| {sc} | {mode} | {w:.1f} | {floor:.1f} | {bound:.1f} | {obs:.1f} | {'yes' if ok else 'NO (+%.1f)' % (obs - bound)} "
              f"| {coll} / {pkts} |")
        out.append({"scenario": sc, "mode": mode, "plca_wait_us": round(w, 2), "floor_us": round(floor, 2),
                    "bound_us": round(bound, 2), "observed_max_us": obs, "within_bound": ok,
                    "radar_mac_logical_collisions": coll, "radar_packets": pkts})
    with (RES / "plca_bound.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    print(f"\nConstants: t_r = {T_R:.1f} µs, D(64 B) = {D_SMALL:.1f} µs, D(1522 B) = {D_HEAVY:.1f} µs, "
          f"D(295 B) = {D_FRAG:.1f} µs, H0 = {H0} µs, Hq ≤ {HQ:.1f} µs")


if __name__ == "__main__":
    main()
