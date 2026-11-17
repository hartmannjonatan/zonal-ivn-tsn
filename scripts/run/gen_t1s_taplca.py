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
SAME_PHI_US = tuple(range(0, 250, 20))
TIME_ERROR_US = (-50, -20, -10, -5, 5, 10, 20, 50)


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


def gate_lines(nominal, crit_ms=None, time_error_us=None):
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
        start, init = PHASE[z] + (time_error_us or {}).get(z, 0), "false"
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


def fine_plca_lines(crit_ms, gptp, max_bc, fine_us=FINE_FILL_US, time_error_us=None):
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
        err = (time_error_us or {}).get(z, 0)
        offs = {(o + err) % 10000 for o in offs}
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
    # S2: coordinator time error. The Z3 coordinator's anchors and gate schedule are shifted by e us against the
    # gPTP time that the sources (and the Z1 coordinator) use; final configuration, nominal.
    saved = dict(PLAN); PLAN.update(PLAN2); PHASE[3] = 40
    crit = sorted(set(range(0, 10, 10)) | {3, 6} | {9})
    for e in TIME_ERROR_US:
        body = (processing_lines() + fine_plca_lines(crit, True, 1, time_error_us={3: e}) + gate_lines(True, crit, time_error_us={3: e})
                + ["**.transmissionGate[3].enableImplicitGuardBand = false"] + offset_lines(col))
        tag = f"TA_NOMINAL_TAPLCA250_P2_PHI40_FINE_TE{'m' if e < 0 else 'p'}{abs(e)}"
        L += section(f"{tag}_30s", "T1S_PT_NOMINAL_SYNCTAS4_GPTP_30s",
                     f"Final TA-PLCA, nominal, Z3 coordinator anchors shifted by {e} us (time error)", f"{tag}_30s", body)
    PLAN.clear(); PLAN.update(saved); PHASE[3] = PHI_Z3_US
    # TA-PLCA v2 (event anchors), nominal, gap sweep
    saved_phase = PHASE[3]; PHASE[3] = 0
    for G in EVT_GAPS_US:
        for gptp in (True, False):
            tag = f"TA_NOMINAL_EVT_G{G}" + ("" if gptp else "_IDEAL")
            body = (processing_lines() + event_lines(G, col, gptp) + gate_lines(True, [0, 3, 6, 9])
                    + ["**.transmissionGate[3].enableImplicitGuardBand = false"])
            L += section(f"{tag}_30s", "T1S_PT_NOMINAL_SYNCTAS4_GPTP_30s" if gptp else "T1S_PT_NOMINAL_SYNCTAS4_30s",
                         f"TA-PLCA v2: event anchors, gap {G} us, {'gPTP' if gptp else 'ideal'} clocks, nominal", f"{tag}_30s", body)
    # calibrated timing (measured): a follower's frame ends ~62.4 us after its TO starts
    # (anchor + 2 + 3.2 id); the reply cycle offset is swept
    for G in (15, 25, 35):
        for ru in (130, 150, 180, 220):
            for gptp in (True, False):
                tag = f"TA_NOMINAL_EVC_G{G}_R{ru}" + ("" if gptp else "_IDEAL")
                body = (processing_lines() + event_lines(G, col, gptp, ru, EVT_FRAME_END_CAL)
                        + gate_lines(True, [0, 3, 6, 9]) + ["**.transmissionGate[3].enableImplicitGuardBand = false"])
                L += section(f"{tag}_30s", "T1S_PT_NOMINAL_SYNCTAS4_GPTP_30s" if gptp else "T1S_PT_NOMINAL_SYNCTAS4_30s",
                             f"TA-PLCA v2, calibrated event anchors, gap {G} us, reply cycle +{ru} us, {'gPTP' if gptp else 'ideal'}",
                             f"{tag}_30s", body)
    # v2 load sweep (chains every per ms) with the generic event planner and gate
    for per in LOAD2_MS:
        for gptp in (True, False):
            tag = f"TA_LOAD{per}_EVC2" + ("" if gptp else "_IDEAL")
            L += section(f"{tag}_30s", "T1S_PT_NOMINAL_SYNCTAS4_GPTP_30s" if gptp else "T1S_PT_NOMINAL_SYNCTAS4_30s",
                         f"TA-PLCA v2 load plan, PT01/PT02 every {per} ms, {'gPTP' if gptp else 'ideal'} clocks",
                         f"{tag}_30s", load_lines(per, col, gptp))
    # v2 (G35/R150) robustness, ablation and time-error configs
    _, server_ = app_index()
    v2 = "TA_NOMINAL_EVC_G35_R150"
    for tag, desc, lines in (
            ("D100", "drift U(-100, 100) ppm", ["**.clock.oscillator.driftRate = uniform(-100ppm, 100ppm)"]),
            ("SYNC31", "Sync every 31.25 ms", ["**.gptp.syncInterval = 31.25ms"]),
            ("PROC20", "processing 20 us", [f"*.{n}.app[{k}].processingTime = 20us" for n, k in server_.values()]),
            ("PROC50", "processing 50 us", [f"*.{n}.app[{k}].processingTime = 50us" for n, k in server_.values()]),
            ("NOGATE", "ablation T2: no TAS gate",
             [f"{sw}.queue.transmissionGate[3].initiallyOpen = true" for sw in COORD.values()]
             + [f"{sw}.queue.transmissionGate[3].durations = []" for sw in COORD.values()])):
        L += [f"[Config {v2}_{tag}_30s]", f"extends = {v2}_30s", f'description = "TA-PLCA v2 (G35/R150), nominal, {desc}"',
              f"result-dir = results/t1s/taplca/{v2}_{tag}_30s"] + lines + [""]
    saved_phase = PHASE[3]; PHASE[3] = 0
    for e in TIME_ERROR_US:
        tag = f"{v2}_TE{'m' if e < 0 else 'p'}{abs(e)}"
        body = (processing_lines() + event_lines(35, col, True, 150, EVT_FRAME_END_CAL, shift={3: e})
                + gate_lines(True, [0, 3, 6, 9], time_error_us={3: e}) + ["**.transmissionGate[3].enableImplicitGuardBand = false"])
        L += section(f"{tag}_30s", "T1S_PT_NOMINAL_SYNCTAS4_GPTP_30s",
                     f"TA-PLCA v2 (G35/R150), Z3 coordinator anchors and gate shifted by {e} us", f"{tag}_30s", body)
    PHASE[3] = saved_phase
    for tag, val in (("PROC403", "403us"), ("PROC0", "0us")):
        L += [f"[Config TA_NOMINAL_EVC_G35_R150_{tag}_30s]", "extends = TA_NOMINAL_EVC_G35_R150_30s",
              f'description = "TA-PLCA v2 (calibrated event anchors), server processing {val}"',
              f"result-dir = results/t1s/taplca/TA_NOMINAL_EVC_G35_R150_{tag}_30s"] + \
             [f"*.{n}.app[{k}].processingTime = {val}" for n, k in server_.values()] + [""]
    L += ["[Config TA_NOMINAL_EVT_G15_PROC403_30s]", "extends = TA_NOMINAL_EVT_G15_30s",
          'description = "TA-PLCA v2 (event anchors, gap 15 us), server processing 403 us"',
          "result-dir = results/t1s/taplca/TA_NOMINAL_EVT_G15_PROC403_30s"] + \
         [f"*.{n}.app[{k}].processingTime = 403us" for n, k in server_.values()] + [""]
    PHASE[3] = saved_phase
    # Robustness of the final configuration: clock quality and server processing time
    base = "TA_NOMINAL_TAPLCA250_P2_PHI40_FINE_30s"
    _, server = app_index()
    for tag, desc, lines in (
            ("D100", "gPTP clocks with drift U(-100, 100) ppm", ["**.clock.oscillator.driftRate = uniform(-100ppm, 100ppm)"]),
            ("SYNC31", "gPTP Sync every 31.25 ms", ["**.gptp.syncInterval = 31.25ms"]),
            ("PROC20", "server processing 20 us", [f"*.{n}.app[{k}].processingTime = 20us" for n, k in server.values()]),
            ("PROC50", "server processing 50 us", [f"*.{n}.app[{k}].processingTime = 50us" for n, k in server.values()]),
            ("PROC0", "server processing 0 us", [f"*.{n}.app[{k}].processingTime = 0us" for n, k in server.values()]),
            ("PROC403", "server processing 403 us (vehicle middleware P99)", [f"*.{n}.app[{k}].processingTime = 403us" for n, k in server.values()]),
            ("NOGATE", "ablation T2: no TAS gate on the coordinators (TC3 always open)",
             [f"{sw}.queue.transmissionGate[3].initiallyOpen = true" for sw in COORD.values()]
             + [f"{sw}.queue.transmissionGate[3].durations = []" for sw in COORD.values()])):
        L += [f"[Config {base[:-4]}_{tag}_30s]", f"extends = {base}",
              f'description = "Final TA-PLCA configuration, nominal, {desc}"',
              f"result-dir = results/t1s/taplca/{base[:-4]}_{tag}_30s"] + lines + [""]
    for tag, val in (("PROC0", "0us"), ("PROC403", "403us")):
        L += [f"[Config TA_NOMINAL_GPTP_{tag}_30s]", "extends = TA_NOMINAL_GPTP_30s",
              f'description = "Baseline gPTP schedule, nominal, server processing {val}"',
              f"result-dir = results/t1s/taplca/TA_NOMINAL_GPTP_{tag}_30s"] + [f"*.{n}.app[{k}].processingTime = {val}" for n, k in server.values()] + [""]
    (SIM / "zonal/configs/t1s_taplca.ini").write_text("\n".join(L))
    (SIM / "zonal_t1s_taplca.ini").write_text(
        "# Entry point for the TA-PLCA campaign (needs ../prioplca).\n"
        "include zonal_t1s.ini\ninclude zonal/configs/t1s_dualbus.ini\ninclude zonal/configs/t1s_powertrain.ini\n"
        "include zonal/configs/t1s_ev.ini\ninclude zonal/configs/t1s_dualbus_final.ini\n"
        "include zonal/configs/t1s_dualbus_clock.ini\ninclude zonal/configs/t1s_taplca.ini\n")


# ---------------------------------------------------------------------------------------------
# TA-PLCA v2: event anchors. Instead of a uniform round grid, each coordinator gets an anchor
# exactly where a planned cross-bus frame has arrived (+ gap G), so no hop waits for a whole
# round. Timing model (64 B frame, measured): BEACON 2 us, empty TO 3.2 us, a frame TO ends
# ~82.5 us after it starts, so follower i's frame ends ~ anchor + 2 + 3.2 i + 82.5; a delivery
# cycle (coordinator TO 0) is complete at ~anchor + 101; the responder replies in a new cycle
# REPLY_US after the delivery anchor. Elsewhere a 25 us grid (standard-like PLCA), kept GUARD_EVT
# us away from every event anchor; local releases are placed in quiet intervals.
EVT_FRAME_END = {2: 90.9, 3: 94.1}     # follower PLCA ID -> frame end after its cycle's anchor
REPLY_US = 110
EVT_FRAME_END_CAL = {i: 2 + 3.2 * i + 62.4 for i in range(1, 8)}
GUARD_EVT = 30
EVT_GAPS_US = (10, 15, 20, 25, 30, 40, 60, 150)


def event_plan(G, reply_us=None, frame_end=None, ids=None, shift=None):
    """Anchors (us within 10 ms, gPTP time) per segment and release offsets (us) per flow."""
    A = {1: set(), 3: set()}
    rel = {}
    FE = frame_end or EVT_FRAME_END
    RU = reply_us or REPLY_US
    ID = {"ECM": 2, "APP": 3, "TCU": 2}
    ID.update(ids or {})
    def chain_req_resp(seg_c, seg_s, t0, id_c, id_s):
        """client on seg_c (PLCA id id_c) sends at anchor t0; server on seg_s (id_s) replies."""
        A[seg_c].add(t0)
        d1 = round(t0 + FE[id_c] + G)          # far coordinator delivers the request
        A[seg_s].add(d1)
        r1 = d1 + RU                                 # server's reply cycle
        A[seg_s].add(r1)
        d2 = round(r1 + FE[id_s] + G)          # client's coordinator delivers the reply
        A[seg_c].add(d2)
        return t0 - GUARD_US
    def one_way(seg_a, seg_b, t0, id_a):
        A[seg_a].add(t0)
        A[seg_b].add(round(t0 + FE[id_a] + G))
        return t0 - GUARD_US
    rel["PT02"] = chain_req_resp(1, 3, 0, ID["ECM"], ID["APP"])    # ECM (Z1) -> APP (Z3), ms 0
    rel["PT01"] = chain_req_resp(3, 1, 400, ID["TCU"], ID["ECM"])  # TCU (Z3) -> ECM (Z1), ms 0
    rel["PT03"] = one_way(1, 3, 3000, ID["ECM"])                   # ECM -> TCU, ms 3
    rel["PT04"] = one_way(3, 1, 6000, ID["TCU"])                   # TCU -> ECM, ms 6
    # local and 10 ms flows: quiet intervals of every ms (Z1: 100-355 and 850-975; Z3 likewise)
    rel.update({"PT05": 845, "PT06": 120, "PT07": 120, "PT08": 5120, "PT09": 2120, "PT10": 4120})
    for k in rel:
        rel[k] %= 10000
    out = {}
    for z in (1, 3):
        ev = sorted(A[z])
        grid = set()
        for t in range(0, 10000, FINE_FILL_US):
            # no fine cycle may start after the planned frame has reached the coordinator (e - G)
            # minus one empty cycle, or during the anchored cycle itself
            if all(not (e - G - GUARD_EVT < t <= e) and not (e < t < e + 100) for e in ev + [e + 10000 for e in ev] + [e - 10000 for e in ev]):
                grid.add(t)
        sh = (shift or {}).get(z, 0)          # S2: this coordinator's clock is off by sh
        out[z] = sorted({(t + sh) % 10000 for t in grid | set(ev)})
    return out, rel


def event_lines(G, col, gptp=True, reply_us=None, frame_end=None, ids=None, shift=None):
    anchors, rel = event_plan(G, reply_us, frame_end, ids, shift)
    L = ['**.plca.typename = "PrioPlca"', '**.plca.mode = "anchored"']
    for z, sw in COORD.items():
        L += [f"{sw}.plca.anchorPeriod = 10ms", f'{sw}.plca.anchorOffsets = "{" ".join(str(t) for t in anchors[z])}"',
              f"{sw}.plca.max_bc = 1"]
        if gptp:
            L.append(f'{sw}.plca.anchorClockModule = "^.^.clock"')
    sender, _ = app_index()
    for f in FLOWS:
        n, k = sender[f[0]]
        L.append(f"*.{n}.app[{k}].source.initialProductionOffset = {rel[f[0]]}us")
    return L


# ---------------------------------------------------------------------------------------------
# TA-PLCA v2 under load: the request/response chains repeat every `per` ms (10 = nominal,
# 1 = stress). Every planned cycle is an event anchor with a modelled length; the TC3 (window)
# gate is open only where a window cycle (~100 us) cannot delay a planned cycle.
LOAD2_MS = (10, 5, 2, 1)
CYCLE_US, LOCALS_US, GATE_LEAD_US = 100, 230, 105   # lead: window cycle + margin (+ G + GUARD_EVT)


def load_plan(per, G=35, R=150):
    FE = EVT_FRAME_END_CAL
    ev = {1: [], 3: []}                      # (anchor, modelled cycle length)
    rel = {}
    for m in range(0, 10, per):
        b = m * 1000
        # PT02: ECM (Z1, id 2) -> APP (Z3, id 3) -> ECM
        d1 = round(b + FE[2] + G); r1 = d1 + R; d2 = round(r1 + FE[3] + G)
        ev[1] += [(b, CYCLE_US), (d2, CYCLE_US)]; ev[3] += [(d1, CYCLE_US), (r1, CYCLE_US)]
        # PT01: TCU (Z3, id 2) -> ECM (Z1, id 2) -> TCU
        t = b + 400; d1 = round(t + FE[2] + G); r1 = d1 + R; d2 = round(r1 + FE[2] + G)
        ev[3] += [(t, CYCLE_US), (d2, CYCLE_US)]; ev[1] += [(d1, CYCLE_US), (r1, CYCLE_US)]
    rel["PT02"], rel["PT01"] = -GUARD_US, 400 - GUARD_US
    for m in range(10):                      # Z1 local 1 ms loop: PT05, PT06, PT07 in one cycle
        ev[1].append((m * 1000 + 100, LOCALS_US))
    rel["PT05"] = rel["PT06"] = rel["PT07"] = 100 - GUARD_US
    t = 3770; ev[1].append((t, CYCLE_US)); ev[3].append((round(t + FE[2] + G), CYCLE_US)); rel["PT03"] = t - GUARD_US
    t = 6650; ev[3].append((t, CYCLE_US)); ev[1].append((round(t + FE[2] + G), CYCLE_US)); rel["PT04"] = t - GUARD_US
    for fid, z, t in (("PT08", 1, 5760), ("PT09", 3, 2520), ("PT10", 3, 4520)):
        ev[z].append((t, CYCLE_US)); rel[fid] = t - GUARD_US
    anchors, gates = {}, {}
    for z in (1, 3):
        E = sorted(set(ev[z]))
        wrap = E + [(e + 10000, l) for e, l in E] + [(e - 10000, l) for e, l in E]
        grid = {t for t in range(0, 10000, FINE_FILL_US)
                if all(not (e - G - GUARD_EVT < t <= e) and not (e < t < e + l) for e, l in wrap)}
        anchors[z] = sorted(grid | {e % 10000 for e, _ in E})
        # A window frame dequeued just before the gate closes keeps its cycle busy for ~CYCLE_US. That
        # cycle must end before the exclusion zone (e - G - GUARD_EVT, e] of the next planned anchor: a
        # cycle ending inside it finds the passed grid anchors and the catch-up BEACON goes out at once,
        # so the planned frame (already at the coordinator, or just released) leaves in an unplanned
        # cycle and the latency depends on the window backlog (PT01 RTT 409 vs 437 us, PT03 +134 us).
        lead = GATE_LEAD_US + G + GUARD_EVT
        closed = sorted((max(e - lead, -10000), e + l) for e, l in wrap)
        open_iv, cur = [], 0
        for a, b_ in closed:
            if b_ <= cur:
                continue
            if a > cur:
                open_iv.append((cur, min(a, 10000)))
            cur = max(cur, b_)
            if cur >= 10000:
                break
        if cur < 10000:
            open_iv.append((cur, 10000))
        gates[z] = [(a, b_) for a, b_ in open_iv if b_ - a >= 5]
    # PT01/PT02 repeat every `per` ms and PT05-07 every 1 ms: load_lines reduces those modulo their
    # own period (reducing PT02's -GUARD modulo 1 ms here put its 10 ms release at 985 us, after its anchor)
    return anchors, {k: v if k in ("PT01", "PT02") else v % (1000 if k in ("PT05", "PT06", "PT07") else 10000)
                     for k, v in rel.items()}, gates


def load_lines(per, col, gptp=True):
    anchors, rel, gates = load_plan(per)
    sender, _ = app_index()
    L = processing_lines() + ['**.plca.typename = "PrioPlca"', '**.plca.mode = "anchored"']
    for z, sw in COORD.items():
        L += [f"{sw}.plca.anchorPeriod = 10ms", f'{sw}.plca.anchorOffsets = "{" ".join(str(t) for t in anchors[z])}"',
              f"{sw}.plca.max_bc = 1"]
        if gptp:
            L.append(f'{sw}.plca.anchorClockModule = "^.^.clock"')
        durs, t = [], 0                       # schedule starts closed at 0
        for a, b_ in gates[z]:
            durs += [a - t, b_ - a]; t = b_
        if t < 10000:
            durs[0] += 10000 - t; off = (10000 - t)       # merge the trailing closed part into the first one
        else:
            off = 0
        L += [f"{sw}.queue.transmissionGate[3].initiallyOpen = false",
              f"{sw}.queue.transmissionGate[3].durations = [{', '.join(f'{d}us' for d in durs)}]",
              f"{sw}.queue.transmissionGate[3].offset = {off}us"]
    L.append("**.transmissionGate[3].enableImplicitGuardBand = false")
    for f in FLOWS:
        n, k = sender[f[0]]
        if f[0] in ("PT01", "PT02"):
            L.append(f"*.{n}.app[{k}].source.productionInterval = {per}ms")
            L.append(f"*.{n}.app[{k}].source.initialProductionOffset = {rel[f[0]] % (per * 1000)}us")
        else:
            L.append(f"*.{n}.app[{k}].source.initialProductionOffset = {rel[f[0]]}us")
    return L


def ini_same():
    """H: both buses on the same zonal switch (Z1 eth5 = bus A, Z1 eth9 = bus B, no window on bus B).
    Writes t1s_taplca_same.ini and zonal_t1s_taplca_same.ini; bus B plays the role of 'zone 3'."""
    global COORD
    saved_coord, COORD = COORD, {1: "*.Z1.ZSW.eth[5]", 3: "*.Z1.ZSW.eth[9]"}
    col = PROFILES["NOMINAL"]
    L = ["# GENERATED by scripts/run/gen_t1s_taplca.py (ini_same). Do not edit.",
         "# TA-PLCA on the same-switch powertrain variant (both buses on Z1).", ""]
    L += section("TA_PTS_NOMINAL_GPTP_30s", "T1S_PTS_NOMINAL_SYNCTAS4_GPTP_30s",
                 "Same switch: gPTP schedule + TAS 400 us, nominal, server processing",
                 "TA_PTS_NOMINAL_GPTP_30s", processing_lines())
    saved = dict(PLAN); PLAN.update(PLAN2)
    crit = [0, 3, 6, 9]
    for phi in SAME_PHI_US:
        PHASE[3] = phi
        body = (processing_lines() + fine_plca_lines(crit, True, 1) + gate_lines(True, crit)
                + ["**.transmissionGate[3].enableImplicitGuardBand = false"] + offset_lines(col))
        L += section(f"TA_PTS_NOMINAL_FINE_PHI{phi}_30s", "T1S_PTS_NOMINAL_SYNCTAS4_GPTP_30s",
                     f"Same switch: final TA-PLCA (plan 2 rounds, anchoring only critical ms), bus B phase {phi} us, gPTP, nominal",
                     f"TA_PTS_NOMINAL_FINE_PHI{phi}_30s", body)
    PLAN.clear(); PLAN.update(saved); PHASE[3] = PHI_Z3_US
    # v2 event anchors on the same switch (bus B ids: TCU 1, APP 2, no window node)
    PHASE[3] = 0
    body = (processing_lines() + event_lines(35, col, True, 150, EVT_FRAME_END_CAL, ids={"TCU": 1, "APP": 2})
            + gate_lines(True, [0, 3, 6, 9]) + ["**.transmissionGate[3].enableImplicitGuardBand = false"])
    L += section("TA_PTS_NOMINAL_EVC_G35_R150_30s", "T1S_PTS_NOMINAL_SYNCTAS4_GPTP_30s",
                 "Same switch: TA-PLCA v2 (event anchors G35/R150), gPTP, nominal", "TA_PTS_NOMINAL_EVC_G35_R150_30s", body)
    PHASE[3] = PHI_Z3_US
    COORD = saved_coord
    (SIM / "zonal/configs/t1s_taplca_same.ini").write_text("\n".join(L))
    (SIM / "zonal_t1s_taplca_same.ini").write_text(
        "# Entry point for TA-PLCA on the same-switch variant (needs ../prioplca).\n"
        "include zonal_t1s.ini\ninclude zonal/configs/t1s_powertrain_same.ini\ninclude zonal/configs/t1s_taplca_same.ini\n")


if __name__ == "__main__":
    ini()
    ini_same()
    print("written t1s_taplca.ini, zonal_t1s_taplca.ini")
