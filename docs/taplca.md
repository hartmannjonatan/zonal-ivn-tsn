# Time-Anchored PLCA (TA-PLCA): implementation and minimum campaign

Status: 2026-11-13. Implementation and smoke tests are done, and the minimum campaign (3 seeds × 30 s) is running.
The 10-seed numbers are **pending**.

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

### 6.3 Hypotheses (status)

- **(a) Delay variation ≤ the ideal-clock schedule.** Nominal: **yes** in the 4 s check. All four cross-bus flows vary by < 0.1 µs, against 45–191 µs (ideal clocks) and 325–502 µs (gPTP) in the 30 s baselines. To be confirmed by the 30 s / 10-seed runs. Stress: **no**.
- **(b) Max RTT + processing < 1 ms.** Nominal: **yes**, 585 µs and 643 µs including the 2.9 µs processing. That leaves 357–415 µs for software, which almost covers the 403 µs P99 of the vehicle middleware path. Stress: **no** (max 1.08–1.40 ms).
- **(c) Bandwidth cost bounded by the anchoring idle time.** The coordinators hold the BEACON 35 % (Z1) and 53 % (Z3) of the time in nominal, and the window still loses ~0 frames.
  In stress, the Z1 bus is already ~86 % busy with 64 B frames, the cost cannot be paid, and the window (TC3) traffic loses ~94 % of its frames.
  The claim must be bounded by load: TA-PLCA pays off when the segment has idle time to spend on anchoring.

## 7. Next steps

1. Report the 30 s runs and update 6.2 and 6.3. Then run the baselines with 10 seeds too, for the paper's 10 × 30 s rule (lab server).
2. Load sweep between nominal and stress, to locate where TA-PLCA stops paying off.
3. Model the window sources on the HPC (gPTP master) clock as well, which is more realistic, and check whether the guard round can be dropped.
4. Turn the hand-made plan into an algorithm, a small search over (φ, round per flow) with a bus-timing model. This is the D2 per-flow offsets folded into TA-PLCA.
