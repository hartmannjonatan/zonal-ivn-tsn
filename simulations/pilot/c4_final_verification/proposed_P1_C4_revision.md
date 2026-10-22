# Prospective P1 change proposal — C4 only

**Status:** proposal for review; not applied. `exploratory=true`; `official_c4_frozen=false`.

The current evidence does not justify freezing C4 or starting its official campaign. If the remaining verification matrix passes, revise the C4 definition prospectively as follows:

1. Define the candidate by the complete, absolute `D3_coordinated_20pct` 24-entry L2 CBS table and the exact D3 GCL in `frozen_profile_table.csv` and `treatment_contracts.json`; do not scale these rates by L0/L1 factors or recompute them per load. Publish the canonical profile hash in the protocol.
2. Apply TAS only to the four shared egresses HPC→CSW and CSW→Z1/Z2/Z3, using the frozen local-clock schedule and guard-band semantics. Keep SP on the actual brake-only last hops and on egresses whose only reserved-TC traffic is transient with zero permanent reserve.
3. Keep gPTP, application clock references, drift model, FIFO, class priorities, no-preemption behavior, routes, buffers and workload fixed. Define gates-open under the same absolute CBS table as a paired diagnostic control. Compare C4 to C3 as a whole system-policy contrast, not as a TAS-only effect.
4. Require the existing P1 application, packet/image, loss, stability and deadline gates. Report sampled synchronization separately from continuous conformance; the latter remains unverified by the current 1 ms sampling. Distinguish technical validity and analytical admissibility from empirical acceptance.
5. Restrict any official domain to cells that pass the fixed-profile service triage. The current fixed candidate is inadmissible at L3 under the recorded CSW→HPC permanent-demand upper-bound test; no L3 result should be extrapolated from lower loads.
6. Include at least the missing L0/A1, L1/A0, L2/A0 checks and L1/A1 seeds 43/47 before selecting this candidate for a full campaign. Preserve the matched TAS/noTAS design, and keep seeds 1001–1030 for the later official campaign rather than treating pilot seeds as confirmatory.

Configuration changes: add/replace only the C4 reservation table and C4 GCL treatment if approved. Clarifications: document buffer units, absolute profile semantics, SP exceptions, sampled-sync limits, and the meaning of the C3 contrast. Do not edit P1, C0–C3, or official configuration files as part of this proposal.
