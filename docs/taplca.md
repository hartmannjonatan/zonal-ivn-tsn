# Time-Anchored PLCA (TA-PLCA): implementation and minimum campaign

Status: 2026-11-14. Nominal headline comparison complete with 10 seeds × 30 s for TA-PLCA (plans 1 and 2) and the three baselines (section 6.4).
The stress and ideal-clock TA-PLCA variants have 3 seeds.

## 1. Mechanism

TA-PLCA changes only the PLCA **coordinator**, which is the zonal switch port of each 10BASE-T1S segment.
At the end of a PLCA cycle, the coordinator holds the BEACON until the next anchor instant `k·T_A + φ_z` of its own clock.
That clock is the gPTP-synchronized zonal switch clock, or simulation time for the ideal-clock variant.
Every cycle, and therefore every transmit opportunity (TO), then starts at a known time, and the PCP 7 release offsets target those TOs.
The followers run standard PLCA.

Implementation: mode `anchored` of `PrioPlca` (`prioplca/PrioPlca.{h,cc,ned}`). Every line changed in the copied INET control FSM is marked `PrioPlca`.

| parameter | meaning |
|---|---|
| `anchorPeriod` | the anchor grid period T_A |
| `anchorOffsets` | the anchor instants inside each period, in µs (the per-segment phase φ_z, or several anchors) |
| `anchorClockModule` | the coordinator's clock (`^.^.clock` = ZSW gPTP clock); empty = ideal clock |
| `lateBeacon` | `catchup` (default): if a cycle overruns its anchor, the BEACON goes out at once and the grid is rejoined at the next anchor (work-conserving). `skip`: the coordinator waits for the next anchor |
| `followerIdleSleep` | followers past the last TO stop counting idle TOs while they wait for the BEACON. They own no TO there, so this removes events only and does not change the bus behaviour |

The anchor is armed when the coordinator enters `CS_RESYNC`, and the `RESYNC → SEND_BEACON` transition additionally requires that the anchor has been reached.
INET starts the FSM directly in `CS_RESYNC` without running the entry action, so the first anchor is armed in `INITSTAGE_PHYSICAL_LAYER`.

The multiTo `DS_PENDING` crash path is not inherited. Here the coordinator owns exactly one TO per cycle (standard `curID` sequence), and holding the BEACON only lengthens the time spent in `CS_RESYNC`.
No FSM error was seen in any smoke or campaign run so far.

Statistics recorded by each coordinator (scalars):
- `taplcaHoldTotal` / `taplcaHoldShare`: the time the BEACON was held. This is the idle bandwidth cost of hypothesis (c).
- `taplcaCycles` / `taplcaLateCycles`: the cycles that overran their anchor.

Compatibility with standard followers: a follower that waits for the BEACON keeps counting TOs. Per the LAN865x documentation it reaches 255 TOs and then starts a 13 ms timer before reverting to CSMA/CD.
With T_A ≤ 250 µs the hold is below 255 × 3.2 µs ≈ 816 µs, so the counter limit is never reached. With T_A = 1 ms it can be reached, but the 13 ms timer still covers it.
This must still be confirmed against the published Clause 148 text and on a LAN865x.

## 2. Server processing time

`DelayedUdpEchoApp` (`prioplca/DelayedUdpEchoApp.*`) echoes each request after `processingTime = truncnormal(2.9 µs, 0.47 µs)`.
That is 2.9 µs mean and about 4.0 µs P99, as measured on the Raspberry Pi 5 real-time gateway (SCHED_FIFO, isolated core).
It replaces the zero processing time of the earlier campaign in **all** configurations, baselines included, so the reported RTT already contains the processing time.

## 3. Both directions of a request/response

A request A→B is delivered in the TO 0 of B's coordinator, and its response B→A in the TO 0 of A's coordinator.
With a single common anchor phase, one of the two directions waits up to a full T_A.

**Choice: per-segment anchor phase plus a per-direction round plan.** Z1 anchors at `k·250 µs` and Z3 at `k·250 µs + φ`.
Every cross-bus frame is planned in a round of its sender's segment and is delivered in a later round of the far segment (`scripts/run/gen_t1s_taplca.py`, `PLAN`).
φ and the round of the TCU request were chosen by a sweep (section 5). The result is **φ = 65 µs**, with the TCU request in Z3 round 1:

| round | Z1 (engine bus, anchors 0/250/500/750 µs) | Z3 (transmission bus, anchors 65/315/565/815 µs) |
|---|---|---|
| r0 | ECM PT02 request, ETC PT06 | coordinator delivers PT02 request; APP PT02 reply |
| r1 | ECM PT03 (ms 3) | TCU PT01 request |
| r2 | MAP PT07, LAMBDA PT08 (ms 5); deliveries of the PT01 request / PT02 reply | GEAR PT09 (ms 2), OSS PT10 (ms 4) |
| r3 | ECM PT05; window (40 µs gate) | TCU PT04 (ms 6); window (40 µs gate) |

Release offset = round anchor − 15 µs.

The window (TC3) gate opens for only 40 µs, which is one 64 B frame, at the start of the segment's window round. That round therefore ends before the next critical round.
In NOMINAL the cross-bus flows run only in ms 0, 3 and 6 of every 10 ms. There the gate follows the same pattern, and in the other ms it stays open, except during the last 250 µs before a critical ms (guard round).
That guard is needed because the window sources (HPC) run on simulation time, while the anchors follow the drifting gPTP clocks (±50 ppm). The window phase relative to the rounds therefore slides over seconds.
Without the guard, a window frame now and then spills into a critical round, and the RTT jumps between regimes of 585, 650, 835 and 1085 µs (seen in the first 30 s campaign, section 6).

The coordinator burst is `max_bc = 1`, so two critical frames for the same segment fit in one TO 0. `max_bc = 2` lengthens the window rounds and makes cycles late.

## 4. What did not work (smoke tests, 1.6–4 s)

- **T_A = 500 and 1000 µs:** each node gets only one TO per T_A. The ECM needs about 3 frames/ms in stress (and about 1.3/ms in nominal), so its queues grow without bound (RTT of hundreds of ms).
  T_A is limited by the frame rate of the busiest node.
- **Fixed rounds with 3 frames per round:** a 64 B frame TO takes about 80 µs. Three frames plus the BEACON and the empty TOs overrun 250 µs, and the cycle runs late.
  With `catchup`, the next round then starts late, and the frames planned for it slip by one round (+250 µs).
  Rounds must carry at most 2 frames, or 3 when the following round has no critical traffic.
- **Fine grid (T_A = 25/50/100 µs, catch-up, step-2 offsets snapped to the grid):** no better than the gPTP schedule.
  In 3 seeds × 30 s, stress PT01 RTT variation is 413 µs vs 442 µs (gPTP) and 307 µs (ideal); nominal is 290 µs vs 325 µs (gPTP).
  Re-anchoring the idle phase does not remove the jitter, because the jitter comes from which other frames share the cycle. A round plan is what makes the timing deterministic.

## 5. Sweeps (4 s runs, seed 1001, gPTP, `max_bc = 1`)

- **S1a, Z3 phase φ = 5…245 µs (step 20), TCU request one round before the PT02 round:** no φ makes both RTTs deterministic.
  The best nominal points are φ = 205 µs (PT01 835 µs and PT02 1085 µs, both with variation < 0.1 µs, but PT02 > 1 ms) and φ = 105 µs (PT02 835 µs deterministic, PT01 not).
- **S1b, φ ∈ {65, 105, 145, 185, 205, 225} × TCU round ∈ {0, 1, 2}:** nominal **φ = 65 µs with TCU round 1 gives PT01 585 µs and PT02 643 µs, both with variation ≤ 0.04 µs**.
  φ = 185 µs with TCU round 0 gives 643/653 µs, also deterministic. In stress, no point is deterministic for both RTTs below 1 ms; the best is φ = 205 µs, round 1, at 1153 µs.
- **S1c, PT03/PT04 rounds:** these flows stayed variable (up to ~440 µs) until the gate also protected ms 3 and ms 6. With that guard, PT03 is at 400.01 µs and PT04 at 270.01 µs, both with variation < 0.1 µs.

These sweep configs are in `t1s_taplca.ini`: `*_PHI<φ>_30s`, `*_PHI<φ>_RT<r>_30s`, `*_PHI65_RT1_P3R<a>_P4R<b>_30s`.
They were run at commit e213be4's parent; their offsets follow the PLAN defaults of that time, so regenerating them now changes the plan of the non-swept flows.

## 6. Results

### 6.1 First minimum campaign (3 seeds × 30 s, first round plan: φ = 245 µs, no gate guard; results in `results/t1s/taplca/*_v1`)

Cross-bus PCP 7 flows, pooled over 3 seeds. All values in µs, RTT including processing.

| config | PT01 RTT mean / max / variation | PT02 RTT mean / max / variation | >1 ms (PT01+PT02) | window lost |
|---|---|---|---|---|
| NOMINAL random | 467 / 720 / 440 | 448 / 598 / 307 | 0 | 0 |
| NOMINAL ideal-clock schedule | 439 / 611 / 191 | 438 / 464 / 45 | 0 | 0 |
| NOMINAL gPTP schedule | 463 / 746 / 325 | 451 / 847 / 502 | 0 | 0 |
| NOMINAL TA-PLCA v1 (BC1) | 768 / 1335 / 750 | 858 / 1335 / 750 | 2127 | 0 |
| STRESS random | 430 / 633 / 356 | 473 / 797 / 519 | 0 | 0 |
| STRESS ideal-clock schedule | 337 / 609 / 307 | 325 / 546 / 265 | 0 | 0 |
| STRESS gPTP schedule | 351 / 744 / 442 | 340 / 847 / 566 | 0 | 0 |
| STRESS TA-PLCA v1 (BC1) | 842 / 1335 / 750 | 869 / 1403 / 750 | 10064 | 883 k (all) |

The v1 plan was deterministic in the 0.6 s smoke test, but not over 30 s, because of the window-phase drift explained in section 3. That led to the guard and the new plan.

### 6.2 Final plan (φ = 65 µs, guard), 4 s check

| config | PT01 RTT | PT02 RTT | PT03 | PT04 | window lost | BEACON held Z1 / Z3 |
|---|---|---|---|---|---|---|
| NOMINAL TA-PLCA, gPTP | 585.02 (var. 0.01) | 643.42 (0.04) | 400.01 (0.07) | 270.01 (0.06) | 1 | 35 % / 53 % |
| NOMINAL TA-PLCA, ideal clocks | 588 (250, one slip) | 643.41 (0.00) | 400.01 (0.00) | 270.01 (0.00) | 2 | 35 % / 53 % |
| STRESS TA-PLCA, gPTP | 997 / max 1085 (431) | 976 / max 1403 (500) | 650.02 (0.07) | 265 (260) | 28 k (~94 %) | 42 % / 58 % |

The 30 s runs are in progress: NOMINAL TA-PLCA gPTP with 10 seeds, STRESS gPTP and NOMINAL ideal with 3 seeds (`results/t1s/taplca/TA_*_TAPLCA250_BC1*_30s`).

### 6.2b Final plan (φ = 65 µs), 30 s runs

| config | seeds | PT01 RTT mean / max / variation / std | PT02 RTT mean / max / variation | PT03 / PT04 variation | window lost |
|---|---|---|---|---|---|
| NOMINAL TA-PLCA, gPTP | 10 | 587.8 / 835.0 / 250.1 / 26.4 | 645.6 / 653.1 / 9.7 | 0.11 / 0.11 | 0 |
| NOMINAL TA-PLCA, ideal clocks | 3 | 586.9 / 835.0 / 250.0 / 21.6 | 643.4 / 643.4 / 0.0 | 0.00 / 0.00 | 0 |
| STRESS TA-PLCA, gPTP | 3 | 1082 / 1085 / 431 | 905 / 1403 / 500 | 68 / 260 | 821 k |

PT01 takes the planned 585 µs in about 99 % of the samples. About 1 % slip by exactly one round, to 835 µs.
The slips occur with ideal clocks too, at times that repeat with catalog periods (x.0311/.0411, x.0611, x.0811, x.1711 s and triplets 50 ms apart).
They are therefore caused by backbone (CSW) traffic that delays a cross-switch frame past an anchor, which means the PT01 path has too little anchor margin.
The alternative plan φ = 185 µs with the TCU request in Z3 round 0 is deterministic in its 4 s check (PT01 643.42 µs, PT02 653.02 µs, PT03 270.01 µs, PT04 208.41 µs, all with variation ≤ 0.07 µs).
Its 30 s / 3-seed runs (gPTP and ideal) are in progress.

### 6.3 Plan 2: the ECM request one round earlier

The PT01 slips of plan 1 come from thin anchor margins: the TCU request reached Z1 only ~8 µs before the Z1 anchor, and backbone interference of up to ~12 µs pushed it past.
Plan 2 moves the ECM PT02 request to Z1 round 3 of the previous ms, which leaves ~145 µs of margin to the Z3 round 0. PT05 moves to Z1 round 0.
A φ sweep (10/20/30/40 µs, 2 seeds × 10 s, gPTP and ideal) gives slips at 10 and 20 µs, and none at 30 and 40 µs. **φ = 40 µs** was chosen (`PLAN2`, configs `TA_*_TAPLCA250_P2_PHI<φ>*`).

### 6.4 Headline comparison: NOMINAL, 10 seeds × 30 s

Cross-bus PCP 7 flows, all values in µs, RTT including the 2.9 µs processing. Variation = max − min. Baselines and TA-PLCA use gPTP clocks unless noted.

| flow | metric | random | ideal-clock schedule | gPTP schedule | TA-PLCA plan 1 (φ = 65) | **TA-PLCA plan 2 (φ = 40)** |
|---|---|---|---|---|---|---|
| PT01 RTT (TCU→ECM→TCU) | mean / max | 462 / 720 | 439 / 613 | 465 / 746 | 588 / 835 | **835.0 / 835.0** |
| | variation / std | 442 / 84.4 | 192 / 9.9 | 325 / 53.7 | 250 / 26.4 (1 % slips) | **0.08 / 0.02** |
| PT02 RTT (ECM→APP→ECM) | mean / max | 449 / 667 | 438 / 541 | 451 / 848 | 646 / 653 | **903.0 / 903.1** |
| | variation / std | 394 / 47.0 | 122 / 7.6 | 503 / 28.0 | 9.7 / 4.0 | **0.15 / 0.02** |
| PT03 one-way (ECM→TCU) | variation | 190 | 102 | 197 | 0.11 | **0.11** |
| PT04 one-way (TCU→ECM) | variation | 300 | 105 | 242 | 0.11 | **0.11** |
| samples > 1 ms | | 0 | 0 | 0 | 0 | **0** |
| window (TC3) frames lost | | 0 | 0 | 0 | 0 | **~10 %** (303 k of ~3 M) |
| BEACON hold share Z1 / Z3 | | – | – | – | 35 % / 53 % | **42 % / 53 %** |

With ideal clocks (3 seeds), plan 2 has 0.00 µs variation on all four flows. With gPTP, the residual 0.08–0.15 µs is the clock error plus the random processing time.
In **STRESS** (3 seeds), plan 2 keeps the PCP 7 flows deterministic as well: PT01 835.02 µs (variation 0.06), PT02 903.02 µs (0.11), PT03 and PT04 variation 0.09 µs.
The price is that the window (TC3) traffic loses ~91 % of its frames.

The alternative plan 1b (φ = 185 µs, TCU round 0, 3 seeds) shows rare 1–2-round slips: PT01 max 1143 µs, 17 samples > 1 ms. It is discarded.

### 6.5 Hypotheses

- **(a) Delay variation ≤ the ideal-clock schedule.** **Holds with plan 2 for all four cross-bus flows:** 0.08–0.15 µs against 102–192 µs for the ideal-clock schedule and 197–503 µs for the gPTP schedule, three orders of magnitude lower.
  Plan 1 meets it for 3 of 4 flows, and PT01 misses it because of the 1 % one-round slips.
- **(b) Max RTT + processing < 1 ms.** **Holds:** plan 2 has a max of 835 µs (PT01) and 903 µs (PT02), processing included; plan 1 has 835 and 653 µs. There are 0 samples > 1 ms in all TA-PLCA nominal runs.
  The software budget is tighter than with the schedules, because determinism is bought with round waits. Plan 2 leaves 97–165 µs, which is less than the 403 µs P99 of the vehicle middleware path. Plan 1 leaves 165–347 µs.
  So TA-PLCA trades the mean for the bound: the RTT is larger but exactly known.
- **(c) Bandwidth cost bounded by the anchoring idle time.**
  - The coordinators hold the BEACON 35–42 % (Z1) and 53 % (Z3) of the time.
  - In nominal, the lower-priority window (TC3) traffic loses 0 % of its frames with plan 1 and ~10 % with plan 2, because plan 2 gives the window fewer and shorter gate slots.
  - In stress (~86 % Z1 load with 64 B frames), the PCP 7 flows stay deterministic with plan 2, but the window loses ~91 %.
  - **The cost of determinism falls on the lower classes. It is acceptable when the segment has idle time, and in the paper the claim must be bounded by load.**

### 6.6 Load sweep (PT01/PT02 period 10 / 5 / 2 / 1 ms; 10, 3, 3, 3 seeds × 30 s; plan 2 vs gPTP schedule)

| PT01/PT02 period | worst variation, gPTP schedule | worst variation, TA-PLCA | window lost, TA-PLCA | BEACON hold Z1 / Z3 |
|---|---|---|---|---|
| 10 ms (nominal) | 503 µs | 0.15 µs | 10 % | 42 % / 53 % |
| 5 ms | 566 µs | 0.11 µs | 41 % | 50 % / 61 % |
| 2 ms | 571 µs | 0.10 µs | 86 % | 55 % / 69 % |
| 1 ms (stress) | 566 µs | 0.11 µs | 91 % | 46 % / 57 % |

The PCP 7 determinism does not depend on load. The TC3 loss grows with the share of critical rounds, partly because of the guard rounds. Figure: `fig17_taplca_load`.

### 6.7 Anchor only where needed (final configuration)

Plan 2 anchored every cycle, so the BEACON was also held in milliseconds that carry no cross-bus traffic.
The final configuration keeps the 250 µs rounds only in the critical ms (and in the guard round before each of them). Everywhere else the anchor list is a 25 µs grid, which behaves like standard PLCA with catch-up.
Implementation: one `anchorOffsets` list per coordinator with a 10 ms period (`fine_plca_lines`, configs `*_P2_PHI40_FINE_30s`).

| load | seeds × 30 s | PT01 / PT02 RTT (variation) | PT03 / PT04 variation | window lost | BEACON hold Z1 / Z3 |
|---|---|---|---|---|---|
| nominal (10 ms) | 10 | 835.01 (0.08) / 903.01 (0.15) | 0.11 / 0.11 µs | **0** (was 10 %) | 30 % / 38 % |
| 5 ms | 3 | 835.02 (0.04) / 903.02 (0.11) | 0.09 / 0.09 µs | **9 %** (was 41 %) | 38 % / 48 % |
| 2 ms and 1 ms | – | every ms is critical, so this is identical to plan 2 (86 % / 91 %) | | | |

With this, **(c) holds at nominal load with zero loss for the lower class**. The cost appears only when most milliseconds carry critical cross-bus traffic.
Figures fig15–fig17 use this configuration.

### 6.8 Robustness of the final configuration (nominal, 3 seeds × 30 s)

| variant | PT01 RTT (variation) | PT02 RTT (variation) | PT03 / PT04 variation | window lost |
|---|---|---|---|---|
| reference (drift ±50 ppm, Sync 125 ms, processing 2.9 µs) | 835.01 (0.08) | 903.01 (0.15) | 0.11 / 0.11 µs | 0 |
| drift ±100 ppm | 835.03 (0.08) | 903.03 (0.14) | 0.10 / 0.12 µs | 0 |
| Sync every 31.25 ms | 835.02 (0.04) | 903.02 (0.10) | 0.10 / 0.10 µs | 0 |
| processing 20 µs (constant) | 835.02 (0.04) | 903.02 (0.10) | 0.09 / 0.09 µs | 0 |
| processing 50 µs (constant) | 835.02 (0.04) | 903.02 (0.10) | 0.09 / 0.09 µs | 0 |

Clock quality does not matter: doubling the drift or syncing 4× more often changes nothing beyond 0.05 µs.
Server processing up to at least 50 µs is absorbed by the round structure, because the response waits for its planned round anyway. The RTT does not change, and with a constant processing time the variation halves.

### 6.9 Load sweep and stress with 10 seeds × 30 s (all points)

| load | TA-PLCA PT01 / PT02 RTT (variation) | TA-PLCA PT03 / PT04 variation | gPTP schedule worst variation | window lost, TA-PLCA |
|---|---|---|---|---|
| 5 ms (anchoring only in critical ms) | 835.01 (0.08) / 903.01 (0.15) | 0.11 / 0.11 µs | 567 µs | 9.0 % |
| 2 ms | 835.01 (0.08) / 903.01 (0.16) | 0.11 / **68.1** µs | 571 µs | 86 % |
| 1 ms (stress) | 835.01 (0.08) / 903.01 (0.16) | 0.11 / **68.1** µs | 567 µs | 90 % |

Stress baselines, 10 seeds: random PT02 RTT max 1207 µs (1988 samples > 1 ms); ideal-clock schedule worst variation 308 µs; gPTP 567 µs.
At 2 and 1 ms, PT04 (TCU→ECM, 10 ms) slips by about 68 µs in some seeds, one frame slot of the Z1 delivery round. This is still below the ideal-clock schedule (106 µs) and leaves no sample above 1 ms.

### 6.10 Ablations (nominal, 3 seeds × 30 s)

| variant | PT01 RTT mean / max (variation) | PT02 RTT mean / max (variation) | samples > 1 ms (PT01 + PT02) |
|---|---|---|---|
| TA-PLCA, final | 835 / 835 (0.08) | 903 / 903 (0.15) | 0 |
| **T2: TA-PLCA without the TAS gate** | 933 / 1069 (234) | 933 / 1335 (716) | 6799 of 18 030 |
| S3: TA-PLCA, processing 0 µs | 835 / 835 (0.04) | 903 / 903 (0.10) | 0 |
| S3: TA-PLCA, processing 403 µs | 1038 / 1038 (87) | 1335 / 1335 (0.13) | all |
| S3: gPTP schedule, processing 0 µs | 463 / 746 (325) | 451 / 847 (502) | 0 |
| S3: gPTP schedule, processing 403 µs | 1051 / 1118 (382) | 1031 / 1060 (199) | all |

- **The gate is necessary.** Without it, window frames lengthen the critical rounds, the cross-bus frames miss their anchors, and TA-PLCA loses both its determinism and the 1 ms bound.
- With the 403 µs P99 of the vehicle middleware as processing time, **neither** configuration meets 1 ms. TA-PLCA stays deterministic for PT02 (it waits two more rounds, but always the same two), while the gPTP schedule keeps a 200–380 µs variation.
  The non-real-time path is therefore incompatible with a 1 ms cross-bus loop on this network, whatever the schedule, and the real-time gateway is required.

### 6.11 S2: coordinator time error (nominal, 3 seeds × 30 s)

The Z3 coordinator's anchors and its gate schedule are shifted by e against the gPTP time used by the sources and by the Z1 coordinator.

| e (µs) | PT01 RTT mean / max (variation) | PT02 RTT (variation) | PT03 / PT04 variation | samples > 1 ms |
|---|---|---|---|---|
| −50 | 1230 / 1353 (578) | 902 (318) | 0.09 / 201 µs | 9002 |
| −20 | 813 / 815 (260) | 903 (0.10) | 0.09 / 0.09 µs | 0 |
| −10 | 825 / 825 (0.04) | 903 (0.10) | 0.09 / 0.09 µs | 0 |
| −5 | 830 / 830 (0.04) | 903 (0.10) | 0.09 / 0.09 µs | 0 |
| 0 | 835 / 835 (0.08) | 903 (0.15) | 0.11 / 0.11 µs | 0 |
| +5 | 840 / 840 (0.04) | 903 (0.10) | 0.09 / 0.09 µs | 0 |
| +10 | 845 / 845 (0.04) | 903 (0.10) | 0.09 / 0.09 µs | 0 |
| +20 | 1335 / 1347 (289) | 835 (250) | 0.09 / 189 µs | 9028 |
| +50 | 1020 / 1100 (115) | 1085 (250) | 260 / 168 µs | 18 016 |

TA-PLCA tolerates a coordinator time error of **±10 µs** with full determinism; the error only shifts the affected RTT by e.
Between 10 and 20 µs, the 15 µs release lead and the anchor margins are used up: frames miss their rounds and the bound is lost.
Hardware-timestamped PTP (< 50 ns on the bench) is three orders of magnitude inside this window. Software-only synchronization (200–500 µs on the Jetson) is far outside it.

### 6.12 H: both buses on the same zonal switch (nominal, 3 seeds × 30 s)

Bus A on Z1 eth5, bus B on Z1 eth9 (no window node on bus B); the same round plan, with the bus B phase φ swept (10 s × 2 seeds, 0–240 µs in steps of 20). Every φ was deterministic over the 10 s sweep, because the cross-bus path is now inside one switch.

| config | PT01 RTT mean / max (variation) | PT02 RTT (variation) | PT03 / PT04 variation | samples > 1 ms |
|---|---|---|---|---|
| gPTP schedule (same switch) | 443 / 676 (262) | 445 / 521 (120) | 171 / 110 µs | 0 |
| TA-PLCA, φ = 40 µs (same plan as two switches) | 835.02 / 835.05 (0.06) | 903.02 (0.10) | 0.03 / 0.02 µs | 0 |
| TA-PLCA, φ = 160 µs (fastest of the sweep) | 575.8 / 835.0 (260; 0.15 % one-round slips) | 575.42 (0.09) | 0.02 / 0.02 µs | 0 |

The plan transfers unchanged to the other topology. A phase tuned for speed (575 µs) is again fragile at the 0.15 % level, the same trade-off between margin and latency as in section 6.2b.
Note: the report keys the hold statistics by zone, so the "hold" column of `taplca.csv` sums both coordinators here (54 % for the two together).

## 7. Next steps

1. Reduce the plan 2 RTTs (one round each is lost against the analytic estimate) and give the window more gate time without touching the critical rounds. A small search over (φ, round per flow) with a bus-timing model would do this, and it is the D2 per-flow offsets folded into TA-PLCA.
2. Load sweep between nominal and stress, to locate where TA-PLCA stops paying off.
3. Model the window sources on the HPC (gPTP master) clock as well, which is more realistic, and check whether the guard round can be dropped.
4. Turn the hand-made plan into an algorithm, a small search over (φ, round per flow) with a bus-timing model. This is the D2 per-flow offsets folded into TA-PLCA.
