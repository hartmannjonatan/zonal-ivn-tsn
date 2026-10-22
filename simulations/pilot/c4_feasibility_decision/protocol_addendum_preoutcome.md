# Pre-outcome operationalization addendum

Created before any new candidate had a result. This addendum makes the previously preregistered phrase “adequate service/recovery evidence” operational; it does not change the candidate family, P1 acceptance gates, thresholds, or run budget.

A seed-41 candidate is eligible for fixed-profile checks only if all of the following hold:

1. Its resolved CBS/GCL/calendar/credit instrumentation is technically valid, the paired calendar signature matches, and sampled synchronization passes (continuous synchronization remains unverified).
2. Every P1 application and queue-stability gate passes.
3. There are zero confirmed overflow drops and zero receiver packet losses in F13, F21, and F22 over the measurement window; those flows have no unresolved pending population at observation end. The flow gate alone does not replace this condition.
4. At CSW.eth[3]/TC4 and Z3.ZSW.eth[7]/TC4, every natural backlog episode whose increment exceeds one 2,048-bit F13 queue frame returns to its pre-episode baseline within 5 s while F13 and the applicable transient sources remain active, with no drops during that episode. Report source-off episodes separately. If no episode exercises recovery at one of these queues, service margin for that queue is `not_identifiable` and the candidate is not selected for additional seeds.
5. Report the measured incoming and outgoing queue bits, backlog trajectory, active F21/F22 event signature, and source-side losses for every episode. Do not infer a guaranteed lower service bound from throughput or from the sizing estimate.

This is an empirical selection rule for allocating the already-authorized conditional runs, not a new P1 gate and not evidence of general feasibility. Among eligible candidates, select the least normalized increase above C3, with the preregistered D1→D2→D3 tie order. If none qualify, stop after the seed-41 set; do not run conditional cells.
