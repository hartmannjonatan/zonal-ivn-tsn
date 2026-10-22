# C4 real-clock service-margin pilot protocol

Status: preregistered exploratory engineering study. This does not revise P1, official C0–C3, the frozen C3 profile, prior pilots, or the official C4 campaign. Flags: `exploratory=true`, `official_c4_frozen=false`.

## Question and fixed conditions

Test cadence, phase coordination, and local recovery margin for permanent F13 separately, using real synchronized node clocks. No simulation-time gate clocks, seed-specific drift values, future packet schedule knowledge, workload changes, new TAS at `Z3.ZSW.eth[7]`, or official C4 campaign are allowed.

The L2/A1 seed-41 comparison uses A005 unchanged except `BM_recovery` and `RPM_combined`, which multiply only `Z3.ZSW.eth[7]/TC4` idleSlope by 1.02. Other seeds and cells, if authorized by the selection rule, retain the same gate construction and derive CBS from that cell's frozen C3 profile. Workload, F21/F22 event calendars, RNG stream separation, application simulation-time reference, routes, PHY, link speeds, buffers, PCP/TC, FIFO, priority, no-preemption, gPTP, and oscillator settings remain fixed. Brake-only egresses remain SP with permanently open gates; transient-only egresses remain SP; no gate is added at Z3 eth7.

Every output is paired to an immutable F21/F22 calendar generated once for that cell/seed. Seed alone is not proof of pairing. The existing seed-41 L2/A1 calendar is copied into this pilot and replayed; its original SHA-256 is checked and recorded.

## Deterministic gate construction, fixed before outcomes

Installed INET is 4.7.0. `PeriodicGate` with `scheduleForAbsoluteTime=true` schedules a change at `getClockTime()+duration-offset`; `SettableClock` adjusts absolute clock events after clock-time/rate changes. The HPC grandmaster has no external absolute frequency reference. gPTP can align the participating clocks relative to HPC, but cannot reveal HPC's error against simulation time. Therefore the rule uses only the configured absolute drift bound (±50 ppm), the application period, topology/PHY constants, frozen A005 CBS reservations, and the existing sampled relative-clock error bound; no seed realization is used to select parameters.

**Cadence rule.** Set the gate-clock period to `P = 100 us × (1 − 50×10⁻⁶) = 99.995 us`. For a slowest allowed master this limits the simulation-time period to 100 us; for a faster master, cycles are shorter. The phase against simulation-time application releases is allowed to sweep; each opening/closing interval is sized for a bounded wait rather than assuming absolute phase lock.

**Open-time rule.** For each shared egress, reserve a conservative one-maximum-frame implicit guard band `G = 1542 bytes × 8 / 1 Gbit/s = 12.336 us` per period. Let `R` be the sum of frozen A005 CBS idleSlopes on that port, and require non-TC7 open time `W_other ≥ 1.10 × (R / lineRate) × P + G`. Choose the largest common TC7-open duration on the four shared egresses, rounded down to whole microseconds, that satisfies this inequality on every port. On L2/A1 the binding egress is CSW.eth[3]/TC4: `R=323.166234 Mb/s`, yielding `W_other_min≈47.89 us`; the preregistered common TC7 window is **52 us** and the complementary non-TC7 window is **47.995 us**. The worst-case guarded service screen is approximately 356.6 Mb/s at CSW.eth[3], about 10.3% above its A005 reservation; this is a capacity screen, not a service guarantee. Credit behavior, frame fit, gates, and observed service are measured separately. Other TC0–TC6 classes share that interval under the configured priority/CBS rules.

`R_cadence` uses TC7 durations `[52 us, 47.995 us]` and TC0–TC6 durations `[47.995 us, 52 us]` on all four shared outputs. The period is 99.995 us. It preserves the reference normalized offsets: TC7 offset 0; TC0–TC6 offset `0.9×P=89.9955 us` (the prior 90/100 period phase). `B_local` retains the audited local-clock GCL `[77,23] us`, offset 90 us for TC0–TC6, and `[10,90] us`, offset 0 for TC7.

**Phase rule.** `RP_cadence_phase` keeps the exact R period and durations. HPC TC7 opening phase remains 0. For CSW eth[1..3], shift TC7 opening by **+1 us** relative to HPC, represented by `offset=P−1 us=98.995 us` in INET's `PeriodicGate` convention. This is calculated from 84 wire bytes at 1 Gbit/s (0.672 us serialization) plus the configured 100 ns link delay, rounded up to 1 us. The extra 228 ns is only nominal phase margin; relative clock samples, corrections, and event order are audited. It does not assert continuous ≤1 us synchronization. TC0–TC6 offsets remain the R reference offsets. Thus R has no phase optimization and RP changes only the four TC7 phases downstream.

The fixed phase objective is to make the CSW TC7 opening contain the expected arrival interval from the upstream 64%-window, leaving relative-clock uncertainty visible. There is no later phase retuning. Tie-breaking is irrelevant because the formula yields one schedule.

## F13 recovery calculation

A005 L2/A1 has `idleSlope=27.600 Mb/s` at Z3.ZSW.eth[7]/TC4; catalog wire demand for F13 is also 27.600 Mb/s. The one authorized intervention is `28.152 Mb/s`, so nominal incremental rate over catalog demand is 0.552 Mb/s (2% relative), before observed CBS/gate/credit effects. The audit's representative end-of-measurement backlog is 108,544 queue bits = 53 F13 packets at 2,048 queue bits/packet. At 276 wire bytes/packet that is 117,024 wire bits; at 0.552 Mb/s the idealized recovery time is about **0.212 s** while the source remains active. This estimate assumes the configured increment becomes additional F13 service and is not an acceptance result. The configured reservation stays below 75% of the 100 Mb/s port. No larger increment is permitted.

## Variants, contrasts, and selection

Initial L2/A1 seed 41 runs, in order: `B_local`, `R_cadence`, `RP_cadence_phase`, `BM_recovery`, `RPM_combined`, `C3_sync_control`. The first B run validates instrumentation and boundary accounting; if those fail, no later methodological run starts until a documented technical repair/replacement (maximum two technical replacements, not new candidate profiles).

Contrasts: R−B (cadence/windows), RP−R (phase), BM−B (local F13 recovery), RPM−RP (F13 recovery under changed gates), RPM−BM (phase under the same recovery profile), and selected candidate−C3_sync_control (combined TAS/CBS difference; not TAS-only).

Selection considers only R, RP, RPM. A candidate is selectable only if it passes all P1 application and stability gates, synchronization/GCL remain separately reported, queue balances close, and the predeclared measured service margin passes: on every measured 5 s interval with backlog, service wire bits must exceed same-interval offered wire bits, plus the interval's queue growth must be nonpositive after separating confirmed drops. Prefer fewer interventions in order R, RP, RPM. If service evidence or queue balance is unavailable, the candidate is not selectable. If none passes, stop. Only a selected candidate is tested fixed in seeds 43/47 with B and C3_sync; it then continues unchanged to L0/A0 and L1/A1 seed41 only if both additional seeds pass. No retuning follows verification results.

Budget: up to six initial variants, six verification executions (candidate/B/C3_sync for seeds 43 and 47), and four extrapolations (candidate/C3_sync for L0/A0 and L1/A1): 16 methodological executions maximum. Reuse is allowed only with identical configuration/profile/calendar and required instrumentation. At most two technical replacements. Triaged-rejected cells do not count as simulations. No extra candidates, seeds, durations, or cells.

## Criteria, instrumentation, and retention

Use 1 s warm-up, `[1,31)` s measurement, and 50 ms drain. Apply the current P1 gates and repository stability proxy unchanged; report the proxy and queue trajectory separately. Report packet/image populations and deadlines, F13/F21/F22, F08–F10, all other flows, queue capacity/occupancy/drops, service and offered demand in separate queue-data and wire units, CBS credit, gate/guard-band states, and sampled synchronization separately from continuous behavior. Utilization must be rebuilt from valid transmission evidence, not sentinel vectors.

For B, validate stable flow/sequence/receptor identity at each relevant queue/transmission event, native timestamps/event ordering, queue-boundary `Q(1−)`/`Q(31−)` balances, and gate/credit/clock event extraction before proceeding. Retain compressed event traces sufficient to reconstruct the selected packet paths, event ordering, queue service and all quantiles/gates. Any unexplained residual makes the corresponding accounting claim inconclusive. Observers are passive but not assumed neutral; compare B against existing A005 results and report perturbation limits.

Run one simulation at a time, extract serially/streaming, checkpoint after each execution, and never delete previous pilot/campaign data. Preserve newly produced raw vectors only until compact extraction independently validates; retain compact compressed evidence and raw evidence for critical/unreconciled runs. Before every run require at least **40 GiB** free disk and at least 7 GiB available RAM; pause below either threshold. Use reduced OS scheduling priority and do not run multiple jobs. A run is not complete until its ledger row and checkpoint are atomically written.

## Frozen source identities

Source specification: `P1-v4.pdf`; official calibration profile: `reduction_11`; pilot reference: `simulations/pilot/c4_gate_clock_reference/results/audits/audit_2026-10-14/`. The generated `protocol_manifest.json` records hashes of the P1, campaign profile/checkpoint, seed-41 calendar, source audit, runner, plugin, INET source files/version, current commit, local modifications, commands, and environment before the first simulation.
