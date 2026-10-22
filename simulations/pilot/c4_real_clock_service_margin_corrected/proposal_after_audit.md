# Proposed prospective addendum: C4 real-clock service evidence

**Status:** proposed after review of the existing pilot results; not preregistered and not authorized for execution. It does not change P1, official profiles, or the C4 campaign.

## Purpose

The previous F13 rule required departures to exceed arrivals in every arbitrary five-second bin where any backlog appeared. In bins with no drops and both endpoint queues empty, conservation forces departures to equal arrivals. That rule cannot measure spare service in such a bin. The next protocol should instead identify actual backlog episodes and either observe recovery while sources remain active or explicitly classify service margin as unidentifiable.

## Prerequisites

Before any new simulation, the runner must prove in the run SCA that each expected CBS egress has an instantiated `Ieee8021qCreditBasedShaper` and resolved idleSlope, sendSlope, credit bounds and guard-band policy. The validator must fail if a requested CBS module is absent. RPM must be checked against the preregistered phase independently: CSW eth1–3 TC7 offset 98.995 µs modulo 99.995 µs, matching RP. Validate both effective configuration and observed gate-state event times. Keep all per-class gates, guard bands and priorities visible; opening fractions alone are not service measurements.

## Evidence classes and decision rule

For each F13 backlog episode, use a common event order and account for queue-resident and in-service packets separately:

`Q_end = Q_start + arrivals − departures − confirmed_drops`.

1. **Natural episode evidence.** Declare an episode only when queue occupancy rises above a predeclared baseline while offered sources remain active. Report the maximum backlog, time-weighted occupancy, interval arrivals/departures/drops, and time to return within the baseline tolerance. If no episode occurs, natural-workload recovery is **not identifiable**; do not call it pass or fail.
2. **Capacity-bound evidence.** Construct an arrival envelope and a conservative lower/upper service envelope using effective CBS credit behavior, gate windows, implicit guard band, frame fit, serialization and IFG, clock cadence, and competing traffic. A sufficient result requires a defensible lower service bound that supports the predeclared recovery horizon for the stated backlog. An insufficient result requires a defensible upper bound that cannot meet the stated demand/horizon. Overlapping bounds or missing mechanism data are **not identifiable**. Do not substitute idleSlope or `idleSlope × open fraction` for a service bound.
3. **Controlled backlog diagnostic.** Only if natural episodes do not identify recovery and the diagnostic is separately authorized, start with a declared 53-frame F13 backlog (108,544 queue bits under the historical queue accounting) while F13 sources remain active. Record the exact initial state and event ordering. Before the run, declare (a) maximum permitted drops (default zero), (b) the baseline tolerance (one maximum F13 queue frame), (c) the deadline `H_recovery` from an analytical service bound or an operationally justified requirement, and (d) whether sources must remain continuously active for all of `H_recovery`. The outcome is sufficient only if the backlog returns within tolerance by `H_recovery` without drops; insufficient only if a justified upper service bound precludes that result or the fully instrumented test exceeds `H_recovery`; otherwise unidentifiable. The previous 0.212 s estimate assumed an additional 0.552 Mb/s of realized service and cannot set `H_recovery` by itself.

For all three evidence classes, preserve queue bits and packet counts, queue-resident versus in-service state, offered arrivals, departures, confirmed drops, active-source status, CBS credit, gate state and timestamps. Use actual event identities/order when available. Missing accounting terms make the episode unidentifiable; do not silently assign a residual to loss or in-service traffic.

## Treatment and run sequence

Do not transfer the failed pilot's “valid treatment” labels. Preserve its results as gate/SP diagnostics and retain the old A005 execution as a historical CBS reference. A future seed-41 stage should proceed in this order:

1. Validate the corrected runner and SCA contract with no simulation.
2. Run corrected B/A005 at L2/A1, seed 41, with the existing paired calendar and the original 1 s warm-up, 30 s measurement, and 50 ms drain. Compare it to the earlier A005 control using a common extraction. Stop and diagnose if CBS parameters or queue accounting do not match expectation.
3. Only after that control passes, run R, RP, corrected BM, corrected RPM, and a correctly configured `C3_sync_control` as the matched seed-41 set. Freeze all settings and the episode/service rule before these runs. The corrected RPM must share RP's GCL and differ only in the registered Z3 eth7/TC4 CBS override.
4. Select no treatment unless application gates, stability, technical validity, phase conformance and the predeclared F13 evidence all pass. If the natural runs do not exercise recoverable backlog, decide separately whether to authorize one controlled-backlog diagnostic; do not append it automatically to the old budget.
5. Consider seeds 43/47 and L0/A0 and L1/A1 only after the seed-41 treatment and the diagnostic interpretation are accepted. Reuse no prior pilot as a verification of the corrected CBS treatments.

## Reporting

Report three statuses separately: **sufficient**, **insufficient**, or **not identifiable** for F13 service evidence; P1 application/stability gates; and synchronization sample/continuous evidence. Keep `exploratory=true` and `official_c4_frozen=false` until an authorized, preregistered evaluation establishes otherwise. This proposal makes no claim about which of R, RP, or RPM will pass.
