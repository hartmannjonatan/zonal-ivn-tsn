# Corrected isolated C4 seed-41 pilot

**Status:** preregistered before any new simulation. This is an exploratory continuation of the audit dated 2026-10-18. It does not revise P1, C0–C3, the frozen C3 profile, official configurations, workload, buffers, routes, clocks, drifts, or gPTP. `exploratory=true`; `official_c4_frozen=false`.

The gate-runtime validator correction is recorded in [protocol_addendum_2026-10-19_gate-runtime-check.md](protocol_addendum_2026-10-19_gate-runtime-check.md). It changes only post-processing validity checks; it does not change a treatment, acceptance criterion, workload, or simulation.

## Scope and preservation

All prior pilot runs remain historical. The six recent variants audited on 2026-10-18 configured idleSlope values but did not instantiate `Ieee8021qCreditBasedShaper`; those runs are **gated-SP diagnostics, not CBS treatments**. They are excluded as controls for this corrected run set. The older `A005_local_L2_A1_seed41_v1` run did instantiate CBS, but its executable hash is unavailable, so it can only be a historical reference. No prior run is overwritten, and this directory does not share results with the official campaign.

The corrected output is under this directory's `results/`. Execution is serial (`jobs=1`) with a 40-GiB free-disk floor and 7-GiB `MemAvailable` floor. The runner checks for an active official campaign or another OMNeT++ process, checkpoints after each treatment, and stops on resource-floor crossings. Vector extraction streams rows to compressed evidence; no vector is loaded into memory as a whole. A treatment is not repeated for a performance failure. At most one replacement is permitted for a demonstrated technical failure, with the failed attempt retained separately.

## Fixed workload and execution order

Cell L2/A1, seed 41; warm-up `[0,1)` s, measurement `[1,31)` s, drain `[31,31.05]` s. Use the existing seed-41 F21/F22 calendar and verify the complete calendar signature and event populations in every run. Apply the saved node drift values and use the same RNG stream assignment, applications, deadlines, queue capacities, routes, priorities, FIFO discipline, Ethernet PHY, gPTP, and no-preemption behavior.

Run B first. Do not proceed until it passes the CBS, GCL, calendar, gate-event, credit-sample, packet identity, and measurement-accounting checks below. B need not pass application or stability gates; the historical growth is the behavior this control is intended to reproduce. If B diverges materially from the historical A005 execution and the divergence cannot be accounted for by identified source/build or instrumentation differences, stop before any other treatment.

After B is technically reliable, run `C3_sync_control`, then `BM_recovery` if no hard service upper bound disproves admissibility. R, RP, and RPM are rejected before execution below. Maximum is six completed methodological seed-41 runs, including B. This stage authorizes no seeds 43/47, L0/A0, L1/A1, artificial backlog, or final C4 campaign.

Before releasing C3/BM, independently recompute all queue-occupancy metrics from the retained compact change-point trace and reconcile them against the validator's per-queue results. Then compare B with the older valid A005 run using the same occupancy-trace integrator. The historical executable hash is absent, so this is a behavior-level check, not binary equivalence. A material divergence is preregistered as either (i) HPC/TC4's six-bin mean-occupancy slope not remaining positive and within ±25% of the historical slope, or (ii) any other named bottleneck queue (CSW eth[1..3]/TC4 or Z3 eth[7]/TC4) differing from a historical 5-second-bin mean by more than 25% of that queue's capacity. Any accounting mismatch also blocks continuation. In that case preserve and report B, set the checkpoint to `paused_for_B_comparison_review`, and do not run C3/BM automatically.

| Treatment | Gate contract | CBS contract | Seed-41 disposition before results |
|---|---|---|---|
| B | Local A005 GCL: period 100 µs, TC4 open 77 µs at phase 10 µs, TC7 open 10 µs at phase 0; local HPC clock at each egress | A005 | Required control |
| C3_sync_control | No periodic TAS closures; gPTP active | Official frozen `reduction_11` L2 profile | Control, subject to port cap |
| BM_recovery | Same GCL as B | A005 plus only Z3.ZSW.eth[7]/TC4 = 28.152 Mb/s | Run only if admissibility remains inconclusive or sufficient |
| R | Period 99.995 µs; TC4 open 47.995 µs; TC7 open 52 µs, reference phases | A005 | Rejected by HPC/TC4 upper bound |
| RP | Same cadence as R; CSW eth[1..3] TC7 open phase 1 µs, encoded offset 98.995 µs modulo 99.995 µs | A005 | Rejected by HPC/TC4 upper bound |
| RPM | Exactly RP GCL, including the CSW TC7 phase; same gates as RP | Same as BM, only Z3 eth7/TC4 = 28.152 Mb/s | Rejected by HPC/TC4 upper bound |

The machine-readable independent treatment contract is `treatment_contracts.json`. The runner's emitted command is checked against that contract; the validator does not infer the expected treatment from the runner's branch conditions.

## CBS construction and validation contract

For each positive-reservation port/TC in A005 or the official C3 L2 profile, the runner explicitly sets the optional `transmissionSelectionAlgorithm[tc].typename` to `Ieee8021qCreditBasedShaper` and sets `idleSlope`. It does not apply CBS to egresses with zero permanent reservation, including the transient-only exceptions. In particular, Z1.ZCPU.eth[0]/TC4, Z2.ZCPU.eth[0]/TC4, and Z3.ZSW.eth[1]/TC4 must not instantiate CBS. F21/F22 remain PCP4/TC4 and share CBS only where their route has a positive permanent TC4 reservation.

The resolved SCA must contain exactly the expected CBS modules and no extras. Every module must resolve to the expected class and rate, the correct physical bitrate, `sendSlope = idleSlope - bitrate`, `idleCreditGainRate = idleSlope`, `transmitCreditSpendRate = bitrate - idleSlope`, `initialCredit=0`, `transmitCreditLimit=0`, `minCredit=-inf`, `maxCredit=inf`, `accumulateCreditInGuardBand=false`, `maxInterferenceSize=inf`, `extraLength=64 b`, and `extraDuration=0 s`. Gate-to-CBS linkage and queue/scheduler plumbing must match INET's `Ieee8021qCreditBasedShaper`; a configuration-line request alone is not acceptance. The run must contain actual `numCredits` vectors and credit-change events for every expected CBS instance. Empty or absent credit evidence fails instrumentation validation.

The expected port/TC contract is generated from the immutable A005 source profile and official frozen C3 L2 profile, with BM/RPM's single exact override. A table with every effective rate and all resolved defaults is written before execution and repeated from each run's SCA afterward. All per-port CBS sums must be no more than 75% of physical line rate. Effective GCL SCA values and observed gate-state transitions are checked independently. Gate event records include simulation time, event number/order, state, and local/HPC clock readings in native ticks. Validate period, open/closed duration, phase modulo period, initial state, implicit guard band, and TC4/TC7 overlap; duty fraction alone is insufficient.

Old non-CBS SCA files must be rejected by this checker. Historical A005 SCA must be recognized as a CBS instance with its effective INET defaults. Neither check modifies a historical run.

## Pre-execution service admissibility

The inspected INET 4.7 `CreditBasedGate::updateCurrentCreditGainRate()` increases credit at idleSlope only when the class is eligible, decreases it at `transmitCreditSpendRate = bitrate - idleSlope` during its transmission and interpacket gap, and sets its credit rate to zero when its linked periodic gate is closed or reports an implicit guard band (`accumulateCreditInGuardBand=false`). `PeriodicGate::canPacketFlowThrough()` requires the full packet data length plus `extraLength` to finish before the next close. These are installed-source findings; no normative CBS claim is made.

For a continuously backlogged class over a long interval, ignoring initial/final credit boundary terms, credit balance gives the optimistic wire service bound

`wire_service <= idleSlope × eligible_credit_gain_time`.

Eligible gain time is no greater than the gate-open time; actual frame-fit guard band, drops, and competition can only lower available evidence of service. A finite-window upper-bound correction records the maximum possible positive pre-measurement credit bank from the 1-s warm-up and at most one maximum-frame credit debt at the measurement boundary. Queue bits are no greater than serialized wire bits, so a wire-service upper bound below the queue-bit offer proves insufficiency. An upper bound above demand does not prove sufficiency. A lower bound below demand alone is not a rejection.

For R/RP/RPM, HPC.eth[0]/TC4 has idleSlope 188.574546 Mb/s and TC4 open time 47.995/99.995 = 47.9974%. Even with no guard band and no competing class, its sustained service upper bound is about 90.51 Mb/s. The maximum positive starting credit bank from warm-up is bounded by 188.574546 Mb/s × 0.479974 × 1 s; spread across 30 s this adds at most about 3.02 Mb/s, plus less than one maximum-frame boundary debt. This remains below the historical 137.68 Mb/s queue-bit offer at HPC/TC4. Therefore R/RP/RPM are inadmissible and are not simulated. Phase changes do not alter this per-port upper bound.

B and BM use 77% TC4 opening. Their optimistic no-guard long-run upper bound is about 145.20 Mb/s; the small-frame best-case guard-band screen is lower, but the upper bound does not prove insufficient service. Neither screen proves sufficient service: gates of higher classes, packet fit, and actual credit/gate cycles require measurement. B is still required as control. BM's changed Z3 reservation alone is admissible under the 75% port cap; it must not be presented as proof of F13 service margin.

The preregistered triage in `plan.json` records all port/TC sums, offer/service units, boundary terms, and statuses. No reserve or GCL is changed to make a rejected candidate pass.

## F13 evidence rule

The old rule requiring departures to exceed arrivals in every arbitrary 5-s bin with any queue pulse is not used: when both endpoint states are empty and there are no drops, conservation requires departures equal arrivals. Current reporting separates realized throughput from capacity.

On F13's `Z3.ZSW.eth[7]/TC4` queue, define a natural backlog episode when occupancy rises above its pre-episode baseline by more than one maximum F13 queue frame (2,048 queue bits); recovery occurs when occupancy returns to or below baseline plus 2,048 bits. Report every arrival, removal, drop, in-service packet, active-source state, and `Q(1-)`/`Q(31-)` using a common event order. A drop prevents calling that episode successful recovery. The diagnostic horizon is 5 seconds from threshold crossing—one P1 stability aggregation interval, not a new P1 gate. Episodes crossing t=31 are right-censored. If no episode crosses the threshold, natural recovery is **not identifiable**. Report whether sources remain active throughout recovery. Do not infer recovery of the historical 53-frame backlog, and do not run an artificial-backlog test in this stage.

## Accounting, gates, applications, and stability

The packet-event probe writes queue push/removal/drop, dequeue-to-transmitter, PHY start/end, gate/guard-band state, CBS credit and clock events with event order and native simulation ticks. The validator also retains the full queue-occupancy change-point trace; queue-length and queue-bit-length statistics are derived from packet operation signals in INET, not assumed to be directly emitted signals. It distinguishes queue-resident packets from a packet in service. Measurement conservation is computed with the same half-open window `[1,31)` and consistent event ordering:

`Q(31-) = Q(1-) + arrivals - departures_from_queue - confirmed_drops`.

Queue counts/bits and packet-in-service state are also reported separately; unexplained residuals make that queue's service/conservation evidence inconclusive. Results retain P1's current application and sustained-growth stability gates without changing tolerances. Camera packet latency and image completion remain separate; incomplete images count as image misses. Brake maximum latency and deadline margin are per receiver. Synchronization reports sampled ≤1 µs separately from continuous compliance, which remains unverified without continuous evidence.

For F13, report (1) offered/served throughput, (2) identified natural backlog episodes and recovery while offer remains active, and (3) defensible capacity bounds. Status is one of `sufficient`, `insufficient`, or `not_identifiable`. If no episode exercises recovery and the bounds overlap demand, service margin is not identifiable. This prevents a queue-empty result from being treated as proof of spare service.

## Retention and reproducibility

The plan manifest stores commit, working-tree state, exact commands, P1/profile/calendar/clock/config/source hashes, OMNeT++/INET versions, executable and runtime-library hashes. Preserve the pre-run plan and each effective SCA, compact result JSON, ledger/checkpoint, exact transient calendar and signature, compressed packet/credit/gate/clock evidence, trace hashes, and all failure artifacts needed for audit. Process vectors by streaming; verify derived credit sample counts, queue balances, flow/image populations, percentiles, gates, and calendars before deleting a raw `.vec`. Compress large text artifacts only after those checks. Never remove the prior pilots or any official results.
