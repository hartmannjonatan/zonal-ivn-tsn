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

**Choice: per-segment anchor phase.** Z1 anchors at `k·250 µs` and Z3 at `k·250 µs + 245 µs`.
Each direction gets its own round on its own segment, and the release offsets are planned per round (`scripts/run/gen_t1s_taplca.py`, `PLAN`):

| round | Z1 (engine bus, anchors 0/250/500/750 µs) | Z3 (transmission bus, anchors 245/495/745/995 µs) |
|---|---|---|
| r0 | ECM PT02 request, ETC PT06 | coordinator delivers PT02 request; APP PT02 reply |
| r1 | coordinator delivers PT01 request; ECM PT01 reply | coordinator delivers PT01 reply to TCU |
| r2 | coordinator delivers PT02 reply; MAP PT07, PT03 (ms 3), LAMBDA (ms 5) | TCU PT04 / GEAR / OSS (10 ms flows); window |
| r3 | ECM PT05; window | TCU PT01 request |

Release offset = round anchor − 15 µs. The window (TC3) gate opens for 60 µs (one 64 B frame) at the start of the window round.
In NOMINAL the critical flows run only in ms 0 of every 10 ms, so the gate has a 10 ms period and is open throughout ms 1–9.
The coordinator may burst (`max_bc` = 1 or 2) so that two critical frames for the same segment fit in one TO 0.

Each request/response therefore costs a fixed number of rounds. In the smoke tests both RTTs are **835 µs including processing, with 0.03 µs of variation** (nominal).
The rounds took slightly longer than the analytic estimate (~600 µs), so each direction lands one round later than planned, but always the same round.
Tightening φ_z and the plan is the next step (the T_A/phase sweep).

## 4. What did not work (smoke tests, 1.6 s, seed 1001)

- **Fixed rounds, first plan (3 frames per round):** a 64 B frame TO takes about 80 µs, so 3 frames plus BEACON and empty TOs overrun 250 µs.
  The response then slips by one round (RTT variation 136–250 µs, max 0.90 ms), and the window loses frames.
- **T_A = 500 and 1000 µs (rounds):** each node gets only one TO per T_A. The ECM needs about 3 frames/ms in stress, so its queues grow without bound (RTT of hundreds of ms).
  T_A is limited by the busiest node's frame rate.
- **Fine grid (T_A = 25/50/100 µs, catch-up, step-2 offsets snapped to the grid):** the result is no better than the gPTP schedule (stress PT01 RTT variation 292 µs vs 164 µs).
  Anchoring only the idle phase does not remove the jitter. The jitter comes from which other frames share the cycle, so the fixed round plan is what makes the timing deterministic.

## 5. Minimum campaign (running)

Launcher: `scripts/run/run_t1s_taplca_30s.sh` (entry `simulations/zonal_t1s_taplca.ini`), runs 0–2 (seeds 1001–1003), 30 s + 1 s warm-up, 18 in parallel.
Results go to `simulations/results/t1s/taplca/<cfg>/`. Report: `scripts/run/t1s_taplca_report.py` → `simulations/zonal/t1s_results/taplca.csv`.

| config | description |
|---|---|
| `TA_{NOMINAL,STRESS}_RANDOM_30s` | unscheduled (random phases), standard PLCA |
| `TA_{NOMINAL,STRESS}_IDEAL_30s` | step-2 schedule + TAS 400 µs, ideal clocks |
| `TA_{NOMINAL,STRESS}_GPTP_30s` | step-2 schedule + TAS 400 µs, gPTP clocks |
| `TA_{NOMINAL,STRESS}_TAPLCA250_BC1_30s` | TA-PLCA, T_A = 250 µs, per-segment phase, gPTP, coordinator max_bc = 1 |
| `TA_{NOMINAL,STRESS}_TAPLCA250_BC2_30s` | same, max_bc = 2 |
| `TA_{NOMINAL,STRESS}_TAF25_30s` | fine grid T_A = 25 µs (negative control) |

All of them include the 2.9 µs server processing time.

## 6. Preliminary results against the hypotheses (smoke, 0.6 s measured, 1 seed; to be replaced by the campaign)

| | nominal | stress |
|---|---|---|
| (a) delay variation ≤ ideal-clock schedule | **Yes**: PT01/PT02 RTT variation 0.03 µs (ideal clocks: 49/40 µs), PT04 0.06 µs | **No**: the response slips by 1–3 rounds (variation 250–750 µs vs 298/250 µs for ideal clocks) |
| (b) max RTT + processing < 1 ms | **Yes**: 835 µs (processing included) | **No**: max 1.08 ms (BC2) to 1.40 ms (BC1) |
| (c) bandwidth cost = idle time | BEACON held 35 % (Z1) and 53 % (Z3) of the time; window loss ≈ 0 | the stress load (~86 % of the Z1 bus with 64 B frames) does not fit in 250 µs rounds; the window (TC3) traffic is starved |

Reading: TA-PLCA makes the PCP 7 timing deterministic when the segment has idle time to spend on anchoring (nominal).
At ~86 % utilization there is no idle time to spend, and that cost is hypothesis (c) in its sharpest form.
For the paper, the claim must be bounded by load. A load sweep is the natural figure.

## 7. Next steps

1. Run the report over the campaign results and update section 6 (3 seeds).
2. Sweep the phase φ_Z3 and T_A (S1) with the round plan regenerated for each T_A, aiming for an RTT of about 600 µs.
3. Run the stress variant with a lighter window load, or with window traffic outside the T1S segment, to find the load at which TA-PLCA stops paying off.
4. Run 10 seeds × 30 s on the lab server.
