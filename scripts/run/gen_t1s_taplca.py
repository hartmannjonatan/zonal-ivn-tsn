#!/usr/bin/env python3
"""Generate the Time-Anchored PLCA (TA-PLCA) campaign for the powertrain dual-bus scenario.

TA-PLCA (PrioPlca mode "anchored"): the coordinator of each T1S segment (the zonal
switch port) holds the BEACON until the next anchor instant k * T_A + phi_z of its
gPTP-synchronized clock, so every PLCA cycle (and therefore every transmit
opportunity, TO) starts at a known time. The PCP 7 release offsets are chosen so
that each frame is queued just before the cycle (round) it is planned for.

Both directions of a request/response (the hard part): a frame that crosses from
one segment to the other is delivered in the far coordinator's TO 0, i.e. right
after a far-segment anchor. With one common anchor phase, the response would wait
up to a whole T_A. We use a per-segment anchor phase instead: Z1 anchors at
k * T_A, Z3 anchors at k * T_A + PHI_Z3. PHI_Z3 is chosen so that (i) the
requests sent by Z1 in its round 0 reach Z3 just before the Z3 round 0, (ii) the
Z3 replies/requests sent in that Z3 round reach Z1 before the Z1 round 2 and
(iii) the ECM reply sent in Z1 round 2 reaches Z3 before the Z3 round 2. With
T_A = 250 us and ~72 us per 64 B frame TO this gives 221 + d <= PHI_Z3 <= 276 - d
(d = switch path delay + margin); PHI_Z3 = 245 us.

Round plan (T_A = 250 us, rounds r0..r3 of each 1 ms; 10 ms flows use ms index m):
  Z1 r0: ECM PT02 request, ETC PT06, MAP PT07           (window gate closed)
  Z1 r1: ECM PT05, ECM PT03 (m=3)                         (window)
  Z1 r2: coordinator delivers PT01 request + PT02 reply; ECM PT01 reply
  Z1 r3: LAMBDA PT08 (m=5)                                (window)
  Z3 r0: TCU PT01 request, APP PT02 reply (after the coordinator delivered the request)
  Z3 r1: TCU PT04 (m=6), GEAR PT09 (m=2)                  (window)
  Z3 r3: OSS PT10 (m=4)                                   (window)
Release offset = anchor of the planned round - GUARD.

Baselines get the same server processing time as TA-PLCA (DelayedUdpEchoApp,
truncnormal(2.9 us, 0.47 us): 2.9 us mean / ~4.0 us P99 measured on the
Raspberry Pi 5 real-time gateway), so all four configurations are comparable.

Writes simulations/zonal/configs/t1s_taplca.ini and simulations/zonal_t1s_taplca.ini.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SIM = ROOT / "simulations"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from gen_t1s_powertrain import FLOWS, PROFILES, SYNC_OFFSET_US, ZONE_OF  # noqa: E402

TA_US = 250
PHI_Z3_US = 65
GUARD_US = 15
PROC = "truncnormal(2.9us, 0.47us)"
COORD = {1: "*.Z1.ZSW.eth[5]", 3: "*.Z3.ZSW.eth[6]"}
PHASE = {1: 0, 3: PHI_Z3_US}
# flow -> (round, ms index for 10 ms flows); the segment is the one of the sender
PLAN = {"PT01": (1, 0), "PT02": (0, 0), "PT03": (1, 3), "PT04": (3, 6), "PT05": (3, 0),
        "PT06": (0, 0), "PT07": (2, 0), "PT08": (2, 5), "PT09": (2, 2), "PT10": (2, 4)}
# TC3 (window) gate per segment: open only during the first WINDOW_OPEN_US of these rounds
# (one 64 B frame), closed otherwise; in NOMINAL the critical flows only run in ms 0 of
# every 10 ms, so the gate has a 10 ms period and is open all the time in ms 1-9.
WINDOW_ROUNDS = {1: (3,), 3: (2,)}
WINDOW_OPEN_US = 40          # a window frame may start only in the first 40 us, so the round ends before the next critical one
NOMINAL_CRITICAL_MS = {0, 3, 6}   # NOMINAL: ms with cross-bus PCP 7 traffic (PT01/PT02 in ms 0, PT03 in ms 3, PT04 in ms 6)
NOMINAL_GUARD_US = 250       # NOMINAL: window gate closes one round before the critical ms (no frame spills into it)
WINDOW_CLOSED_ROUNDS = (0,)          # TC3 gate closed during these rounds (relative to the segment phase)
SWEEP_TA_US = (250, 500, 1000)
SWEEP_PHI_US = tuple(range(5, 250, 20))
SWEEP2_PHI_US = (65, 75, 85, 95, 105, 115, 125, 135, 145, 185, 205, 225)
SWEEP2_TCU_ROUNDS = (0, 1, 2)
PLAN2 = {"PT01": (1, 0), "PT02": (3, -1), "PT03": (1, 3), "PT04": (3, 6), "PT05": (0, 0),
         "PT06": (0, 0), "PT07": (2, 0), "PT08": (2, 5), "PT09": (2, 2), "PT10": (2, 4)}
SWEEP_PLAN2_PHI_US = (10, 20, 30, 40)
LOAD_SWEEP_MS = (5, 2)
FINE_FILL_US = 25


def release_us(fid, period_us):
    r, m = PLAN[fid]
    z = ZONE_OF[next(f for f in FLOWS if f[0] == fid)[3]]
    t = PHASE[z] + r * TA_US - GUARD_US + m * 1000
    return t % period_us


def app_index():
    """(node, app index) of the sender of every flow and of the echo servers (same order as gen_t1s_powertrain.apps)."""
    per = {n: 0 for n in ZONE_OF}
    sender, server = {}, {}
    for fid, label, kind, a, b, *periods in FLOWS:
        sender[fid] = (a, per[a]); per[a] += 1
        if kind == "reqresp":
            server[fid] = (b, per[b])
        per[b] += 1
    return sender, server


def us(p):
    return int(p[:-2]) * 1000 if p.endswith("ms") else int(p[:-2])


def processing_lines():
    _, server = app_index()
    L = ["# Server processing time of the request/response flows (Raspberry Pi 5 RT gateway)."]
    for fid, (n, k) in server.items():
        L += [f'*.{n}.app[{k}].typename = "DelayedUdpEchoApp"', f"*.{n}.app[{k}].processingTime = {PROC}"]
    return L


def offset_lines(col, period_override=None):
    sender, _ = app_index()
    L = []
    for f in FLOWS:
        fid, period = f[0], f[col]
        if period_override and fid in period_override:
            period = period_override[fid]
        n, k = sender[fid]
        L.append(f"*.{n}.app[{k}].source.initialProductionOffset = {release_us(fid, us(period))}us")
    return L


FINE_TA_US = (25, 50, 100)
LEAD_US = 2   # a release this long before an anchor is pending when the BEACON goes out


def fine_offset_lines(col, ta):
    """Step-2 (SYNCTAS4) offsets snapped to just before the next anchor of the grid."""
    sender, _ = app_index()
    L = []
    for f in FLOWS:
        fid, period = f[0], f[col]
        n, k = sender[fid]
        o = SYNC_OFFSET_US[fid]
        snapped = -(-o // ta) * ta - LEAD_US
        if snapped < 0:
            snapped += 1000
        L.append(f"*.{n}.app[{k}].source.initialProductionOffset = {snapped}us")
    return L


def gate_lines(nominal, crit_ms=None):
    """TC3 (window) gate on the coordinator ports, in the coordinator clock. Closed except
    during the first WINDOW_OPEN_US of the segment's window rounds; NOMINAL: 10 ms period,
    that pattern in ms 0 only and open in ms 1-9."""
    L = []
    for z, sw in COORD.items():
        period = 10000 if nominal else 1000
        opens = []   # [start, end) open intervals relative to the segment phase
        crit = sorted(crit_ms if crit_ms is not None else NOMINAL_CRITICAL_MS) if nominal else [0]
        for i, m in enumerate(crit):
            for r in WINDOW_ROUNDS[z]:
                opens.append((m * 1000 + r * TA_US, m * 1000 + r * TA_US + WINDOW_OPEN_US))
            if nominal:   # free ms up to the next critical ms, minus one guard round
                nxt = crit[i + 1] if i + 1 < len(crit) else 10
                if nxt > m + 1:
                    opens.append(((m + 1) * 1000, nxt * 1000 - NOMINAL_GUARD_US))
        opens.sort()
        durs, t, state = [], 0, False   # schedule starts closed at the segment phase
        for a_, b_ in opens:
            durs += [a_ - t, b_ - a_]
            t = b_
        start, init = PHASE[z], "false"
        if t < period:   # trailing closed part: start the schedule there and merge it with the leading one
            c = period - t
            durs[0] += c
            start -= c
        L += [f"{sw}.queue.transmissionGate[3].initiallyOpen = {init}",
              f"{sw}.queue.transmissionGate[3].durations = [{', '.join(f'{d}us' for d in durs)}]",
              f"{sw}.queue.transmissionGate[3].offset = {(period - start) % period}us"]
    return L


def plca_lines(ta_us, gptp, max_bc):
    L = ['**.plca.typename = "PrioPlca"', '**.plca.mode = "anchored"']
    for z, sw in COORD.items():
        L += [f"{sw}.plca.anchorPeriod = {ta_us}us", f'{sw}.plca.anchorOffsets = "{PHASE[z] % ta_us}"',
              f"{sw}.plca.max_bc = {max_bc}"]
        if gptp:
            L.append(f'{sw}.plca.anchorClockModule = "^.^.clock"')
    return L


def fine_plca_lines(crit_ms, gptp, max_bc, fine_us=FINE_FILL_US):
    """Anchor only where needed: 250 us rounds in the critical ms and in the last round before
    each of them, a fine grid (standard-like PLCA with catch-up) everywhere else. 10 ms period."""
    L = ['**.plca.typename = "PrioPlca"', '**.plca.mode = "anchored"']
    crit = set(crit_ms)
    for z, sw in COORD.items():
        offs = set()
        for m in range(10):
            base = m * 1000 + PHASE[z]
            coarse_from = 0 if m in crit else (750 if (m + 1) % 10 in crit else 1000)
            for t in range(0, coarse_from, fine_us):
                offs.add((base + t) % 10000)
            for r in range(4):
                if r * TA_US >= coarse_from:
                    offs.add((base + r * TA_US) % 10000)
        L += [f"{sw}.plca.anchorPeriod = 10ms", f'{sw}.plca.anchorOffsets = "{" ".join(str(o) for o in sorted(offs))}"',
              f"{sw}.plca.max_bc = {max_bc}"]
        if gptp:
            L.append(f'{sw}.plca.anchorClockModule = "^.^.clock"')
    return L


def section(name, base, desc, rdir, body):
    return [f"[Config {name}]", f"extends = {base}", f'description = "{desc}"',
            f"result-dir = results/t1s/taplca/{rdir}"] + body + [""]


def ini():
    L = ["# GENERATED by scripts/run/gen_t1s_taplca.py. Do not edit.",
         "# TA-PLCA (Time-Anchored PLCA) vs baselines, powertrain dual T1S bus, 30 s runs",
         "# (runs 0..9 = seeds 1001..1010 as in the *_30s bases; the minimum campaign uses runs 0-2).", ""]
    for prof, col in PROFILES.items():
        p = f"T1S_PT_{prof}"
        L += section(f"TA_{prof}_RANDOM_30s", f"{p}_30s",
                     f"Baseline: unscheduled (random phases), standard PLCA, {prof.lower()}, server processing",
                     f"TA_{prof}_RANDOM_30s", processing_lines())
        L += section(f"TA_{prof}_IDEAL_30s", f"{p}_SYNCTAS4_30s",
                     f"Baseline: ideal-clock schedule + TAS 400 us, standard PLCA, {prof.lower()}, server processing",
                     f"TA_{prof}_IDEAL_30s", processing_lines())
        L += section(f"TA_{prof}_GPTP_30s", f"{p}_SYNCTAS4_GPTP_30s",
                     f"Baseline: gPTP schedule + TAS 400 us, standard PLCA, {prof.lower()}, server processing",
                     f"TA_{prof}_GPTP_30s", processing_lines())
        for bc in (1, 2):
            for ta in SWEEP_TA_US:
                tag = f"TA_{prof}_TAPLCA{ta}_BC{bc}"
                body = (processing_lines() + plca_lines(ta, True, bc) + gate_lines(prof == 'NOMINAL')
                        + ["**.transmissionGate[3].enableImplicitGuardBand = false"] + offset_lines(col))
                L += section(f"{tag}_30s", f"{p}_SYNCTAS4_GPTP_30s",
                             f"TA-PLCA T_A = {ta} us (Z3 phase {PHI_Z3_US} us), gPTP clocks, coordinator max_bc = {bc}, {prof.lower()}",
                             f"{tag}_30s", body)
            tag = f"TA_{prof}_TAPLCA{TA_US}_BC{bc}_IDEAL"
            body = (processing_lines() + plca_lines(TA_US, False, bc) + gate_lines(prof == 'NOMINAL')
                    + ["**.transmissionGate[3].enableImplicitGuardBand = false"] + offset_lines(col))
            L += section(f"{tag}_30s", f"{p}_SYNCTAS4_30s",
                         f"TA-PLCA T_A = {TA_US} us, ideal clocks, coordinator max_bc = {bc}, {prof.lower()}",
                         f"{tag}_30s", body)
        for ta in FINE_TA_US:
            for gptp in (True, False):
                tag = f"TA_{prof}_TAF{ta}" + ("" if gptp else "_IDEAL")
                base = f"{p}_SYNCTAS4_GPTP_30s" if gptp else f"{p}_SYNCTAS4_30s"
                body = processing_lines() + ['**.plca.typename = "PrioPlca"', '**.plca.mode = "anchored"']
                for z, sw in COORD.items():
                    body += [f"{sw}.plca.anchorPeriod = {ta}us", f'{sw}.plca.anchorOffsets = "0"']
                    if gptp:
                        body.append(f'{sw}.plca.anchorClockModule = "^.^.clock"')
                body += fine_offset_lines(col, ta)
                L += section(f"{tag}_30s", base,
                             f"TA-PLCA fine grid T_A = {ta} us, catch-up, step-2 schedule snapped to the grid, "
                             f"{'gPTP' if gptp else 'ideal'} clocks, {prof.lower()}", f"{tag}_30s", body)
        # S1a: Z3 anchor phase sweep (round plan, T_A = 250 us, gPTP, max_bc = 1)
        for phi in SWEEP_PHI_US:
            PHASE[3] = phi
            tag = f"TA_{prof}_TAPLCA250_BC1_PHI{phi}"
            body = (processing_lines() + plca_lines(TA_US, True, 1) + gate_lines(prof == 'NOMINAL')
                    + ["**.transmissionGate[3].enableImplicitGuardBand = false"] + offset_lines(col))
            L += section(f"{tag}_30s", f"{p}_SYNCTAS4_GPTP_30s",
                         f"TA-PLCA T_A = {TA_US} us, Z3 phase {phi} us, gPTP clocks, coordinator max_bc = 1, {prof.lower()}",
                         f"{tag}_30s", body)
        PHASE[3] = PHI_Z3_US
        # S1b: Z3 phase x round of the TCU PT01 request (Z3 round, relative to the segment phase)
        for phi in SWEEP2_PHI_US:
            for rt in SWEEP2_TCU_ROUNDS:
                PHASE[3] = phi
                PLAN["PT01"] = (rt, 0)
                tag = f"TA_{prof}_TAPLCA250_BC1_PHI{phi}_RT{rt}"
                body = (processing_lines() + plca_lines(TA_US, True, 1) + gate_lines(prof == 'NOMINAL')
                        + ["**.transmissionGate[3].enableImplicitGuardBand = false"] + offset_lines(col))
                L += section(f"{tag}_30s", f"{p}_SYNCTAS4_GPTP_30s",
                             f"TA-PLCA T_A = {TA_US} us, Z3 phase {phi} us, TCU request in Z3 round {rt}, gPTP, max_bc = 1, {prof.lower()}",
                             f"{tag}_30s", body)
                if (phi, rt) == (185, 0):
                    body = (processing_lines() + plca_lines(TA_US, False, 1) + gate_lines(prof == 'NOMINAL')
                            + ["**.transmissionGate[3].enableImplicitGuardBand = false"] + offset_lines(col))
                    L += section(f"{tag}_IDEAL_30s", f"{p}_SYNCTAS4_30s",
                                 f"TA-PLCA T_A = {TA_US} us, Z3 phase {phi} us, TCU request in Z3 round {rt}, ideal clocks, max_bc = 1, {prof.lower()}",
                                 f"{tag}_IDEAL_30s", body)
        PHASE[3] = PHI_Z3_US
        PLAN["PT01"] = (1, 0)
        # S1c: rounds of the one-way cross-bus flows PT03 (Z1) and PT04 (Z3) at the best (phase, TCU round)
        PHASE[3] = 65
        PLAN["PT01"] = (1, 0)
        for r3 in range(4):
            for r4 in range(4):
                PLAN["PT03"] = (r3, 3)
                PLAN["PT04"] = (r4, 6)
                tag = f"TA_{prof}_TAPLCA250_BC1_PHI65_RT1_P3R{r3}_P4R{r4}"
                body = (processing_lines() + plca_lines(TA_US, True, 1) + gate_lines(prof == 'NOMINAL')
                        + ["**.transmissionGate[3].enableImplicitGuardBand = false"] + offset_lines(col))
                L += section(f"{tag}_30s", f"{p}_SYNCTAS4_GPTP_30s",
                             f"TA-PLCA T_A = {TA_US} us, Z3 phase 65 us, TCU request in Z3 round 1, PT03 round {r3}, PT04 round {r4}, gPTP, max_bc = 1, {prof.lower()}",
                             f"{tag}_30s", body)
        PHASE[3] = PHI_Z3_US
        PLAN["PT01"] = (1, 0)
        PLAN["PT03"] = (1, 3)
        PLAN["PT04"] = (3, 6)
        # Plan 2: the ECM sends the PT02 request in Z1 round 3 of the previous ms, so it reaches Z3
        # well before the Z3 round 0 (margin ~145 us); PT05 moves to Z1 round 0. Margins of every
        # cross-segment arrival to the next far anchor are >= ~50 us for phi ~ 20 us.
        saved = dict(PLAN)
        PLAN.update(PLAN2)
        for phi in SWEEP_PLAN2_PHI_US:
            PHASE[3] = phi
            tag = f"TA_{prof}_TAPLCA250_P2_PHI{phi}"
            for gptp in (True, False):
                body = (processing_lines() + plca_lines(TA_US, gptp, 1) + gate_lines(prof == 'NOMINAL')
                        + ["**.transmissionGate[3].enableImplicitGuardBand = false"] + offset_lines(col))
                L += section(f"{tag}{'' if gptp else '_IDEAL'}_30s", f"{p}_SYNCTAS4{'_GPTP' if gptp else ''}_30s",
                             f"TA-PLCA plan 2, T_A = {TA_US} us, Z3 phase {phi} us, {'gPTP' if gptp else 'ideal'} clocks, max_bc = 1, {prof.lower()}",
                             f"{tag}{'' if gptp else '_IDEAL'}_30s", body)
        PLAN.clear(); PLAN.update(saved)
        PHASE[3] = PHI_Z3_US
    # Load sweep: PT01/PT02 period between NOMINAL (10 ms) and STRESS (1 ms); everything else as NOMINAL.
    col = PROFILES["NOMINAL"]
    sender, _ = app_index()
    for per in LOAD_SWEEP_MS:
        over = {"PT01": f"{per}ms", "PT02": f"{per}ms"}
        period_lines = [f"*.{sender[f][0]}.app[{sender[f][1]}].source.productionInterval = {per}ms" for f in over]
        L += section(f"TA_LOAD{per}_GPTP_30s", "T1S_PT_NOMINAL_SYNCTAS4_GPTP_30s",
                     f"Baseline: gPTP schedule + TAS 400 us, PT01/PT02 every {per} ms, server processing",
                     f"TA_LOAD{per}_GPTP_30s", processing_lines() + period_lines)
        saved = dict(PLAN); PLAN.update(PLAN2); PHASE[3] = 40
        crit = sorted(set(range(0, 10, per)) | {3, 6} | {(m - 1) % 10 for m in range(0, 10, per)})
        body = (processing_lines() + period_lines + plca_lines(TA_US, True, 1) + gate_lines(True, crit)
                + ["**.transmissionGate[3].enableImplicitGuardBand = false"] + offset_lines(col, over))
        L += section(f"TA_LOAD{per}_TAPLCA250_P2_PHI40_30s", "T1S_PT_NOMINAL_SYNCTAS4_GPTP_30s",
                     f"TA-PLCA plan 2 (phi 40 us), gPTP, PT01/PT02 every {per} ms",
                     f"TA_LOAD{per}_TAPLCA250_P2_PHI40_30s", body)
        PLAN.clear(); PLAN.update(saved); PHASE[3] = PHI_Z3_US
    # "Anchor only where needed": fine grid outside the critical ms (plan 2, phi 40 us)
    for per in (10, 5, 2):
        over = {"PT01": f"{per}ms", "PT02": f"{per}ms"} if per != 10 else {}
        period_lines = [f"*.{sender[f][0]}.app[{sender[f][1]}].source.productionInterval = {per}ms" for f in over]
        saved = dict(PLAN); PLAN.update(PLAN2); PHASE[3] = 40
        crit = sorted(set(range(0, 10, per)) | {3, 6} | {(m - 1) % 10 for m in range(0, 10, per)})
        tag = "TA_NOMINAL" if per == 10 else f"TA_LOAD{per}"
        body = (processing_lines() + period_lines + fine_plca_lines(crit, True, 1) + gate_lines(True, crit)
                + ["**.transmissionGate[3].enableImplicitGuardBand = false"] + offset_lines(col, over))
        L += section(f"{tag}_TAPLCA250_P2_PHI40_FINE_30s", "T1S_PT_NOMINAL_SYNCTAS4_GPTP_30s",
                     f"TA-PLCA plan 2 (phi 40 us), anchored rounds only in critical ms, {FINE_FILL_US} us grid elsewhere, gPTP, PT01/PT02 every {per} ms",
                     f"{tag}_TAPLCA250_P2_PHI40_FINE_30s", body)
        PLAN.clear(); PLAN.update(saved); PHASE[3] = PHI_Z3_US
    (SIM / "zonal/configs/t1s_taplca.ini").write_text("\n".join(L))
    (SIM / "zonal_t1s_taplca.ini").write_text(
        "# Entry point for the TA-PLCA campaign (needs ../prioplca).\n"
        "include zonal_t1s.ini\ninclude zonal/configs/t1s_dualbus.ini\ninclude zonal/configs/t1s_powertrain.ini\n"
        "include zonal/configs/t1s_ev.ini\ninclude zonal/configs/t1s_dualbus_final.ini\n"
        "include zonal/configs/t1s_dualbus_clock.ini\ninclude zonal/configs/t1s_taplca.ini\n")


if __name__ == "__main__":
    ini()
    print("written t1s_taplca.ini, zonal_t1s_taplca.ini")
