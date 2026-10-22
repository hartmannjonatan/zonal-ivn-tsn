# C4 absolute-profile final verification — reconciled status

**Status:** `exploratory=true`; `official_c4_frozen=false`. No P1, C0–C3, frozen-profile, workload, or official-campaign files were changed. No new simulation was launched during this reconciliation.

## Completion

The authorized study is complete. Its 36 L0–L2 positions are covered by 26 new executions and 10 audited reuses. All 36 are technically valid and pass the recorded application, queue-stability, and sampled-synchronization gates. All 36 report zero post-warm-up queue-overflow drops and zero packets pending at simulation end. The TAS/noTAS treatments have matching F21/F22 calendar signatures within each cell and seed.

The remaining 12 positions are L3 treatments rejected before simulation by the frozen triage: the fixed profile's optimistic CBS service bound at CSW.eth[0] is below the permanent offered demand. This is a rejection of this fixed profile under the registered bound, not a general impossibility result for CBS/TAS. There are no remaining authorized simulation positions, and no runner is active.

| Coverage item | Count | Disposition |
|---|---:|---|
| L0–L2 methodological positions | 36/36 | 10 reused, 26 new; reconciled gates pass |
| L3 positions | 12/12 | Rejected by pre-run triage; no simulations |
| Authorized positions remaining | 0 | The registered scope is exhausted |
| Interrupted technical attempts | 2 | Non-results; both have completed replacements |

The partial L0/A1 seed-43 attempt stopped at 49% after the host reboot and remains preserved separately. Its replacement is `D3_fixed_TAS_L0_A1_seed43_technical_attempt_001`, which has a completed report, matching calendar signature, and passing technical/application/stability/sampled-sync gates. The earlier controlled interruption of L1/A1 seed 43 is likewise a non-result; the paired cell later completed. Neither partial attempt is counted as a methodological position.

## Reconciliation of reused synchronization results

The reused reports carried stale or pending sampled-sync fields. I recalculated the 10 reused runs from their preserved `clock_precision.csv.gz`, using simultaneous corrected-clock reads and subtracting integer native ticks before serialization. The measurement window is `[1,31)` s and the threshold is 1 µs. Every reused run passes both periodic samples and clock-change snapshots. Periodic coverage is 30,000 samples per node/run; clock-change snapshots range from 154,566 to 154,800 per node/run. The largest absolute sampled offset among the reused runs is 60 ns. Across all 36 completed positions, the recorded maximum is also 60 ns. Continuous synchronization remains **not verified** because samples do not establish the bound at every instant.

| Reused cell / seed | TAS max | noTAS max | Prior report flags | Recalculated direct-tick audit |
|---|---:|---:|---|---|
| L0/A0, 41 | 30 ns | 50 ns | both false | both pass |
| L1/A1, 41 | 30 ns | 50 ns | both false | both pass |
| L2/A1, 41 | 30 ns | 60 ns | both marked pending | both pass |
| L2/A1, 43 | 50 ns | 50 ns | both false | both pass |
| L2/A1, 47 | 50 ns | 50 ns | both false | both pass |

Eight old false flags are superseded as current metrics by the direct-tick calculation; the two L2/A1 seed-41 legacy flags were already true. The old values remain in `pilot_results.json` under `legacy_report_sampled_sync_flag`, and the original report files were not edited. The frozen `manifest.json` also remains unchanged; its old “pending” labels are historical provenance, while `results/reconciliation_2026-10-22.json` is the current sync authority.

## Did the runner proceed despite failed reused gates?

The preregistered rule says to stop conditional expansion after completing a matched pair if a valid application, stability, sampled-sync, or technical gate fails. The corrected runner applies that stop predicate to newly executed pairs. It did not first feed all reused manifest rows into the same predicate before entering phase 2. At that time, four reused rows had legacy false sync flags and six were labeled pending, so the phase transition was not guarded by a fully reconciled reused-position audit. This is a control-flow and auditability gap.

The post-run audit now resolves that gap empirically: **none of the 10 reused runs has a sampled-sync failure in the preserved native-tick evidence**. The four false legacy pairs were artifacts of the earlier synchronization export; the six pending rows also pass when recalculated. The 26 new runs pass all four recorded gates, as shown by their final reports and ledger entries. Therefore, no actual sampled-sync failure was bypassed, and the existing results remain usable for the registered exploratory comparison. The fact that phase 2 proceeded should still be recorded as a process deviation: the reused rows were justified only by this later audit, not by an explicit pre-phase-2 gate check.

The runner's result status is `phase2_complete`; it did not crash or stop at an unhandled error. It stopped because the authorized L0–L2 sequence was exhausted and all L3 cells were triaged out. The previous checkpoint's reboot/storage `stop_reason`, `next_batch`, pending list, and coverage count were stale. Those values were preserved under `historical_fields_pre_reconciliation`; the current checkpoint now records zero active and zero remaining positions.

## Evidence and scope limits

- [protocol.md](protocol.md) and [manifest.json](manifest.json) remain the preregistered contract and immutable profile identity.
- [matrix.csv](matrix.csv) lists all 48 positions as 36 covered and 12 triage-rejected.
- [pilot_results.json](pilot_results.json) now contains the reconciled per-position flags, direct-tick summaries, per-flow/receptor metrics, selected queue metrics, and report paths/hashes.
- [results/runs.jsonl](results/runs.jsonl) and each linked `pilot-result.json` remain the execution ledger and detailed source reports.
- [results/reconciliation_2026-10-22.json](results/reconciliation_2026-10-22.json) records all 36 report identities, direct-sync sample counts/maxima, gate counts, technical attempts, and the runner-transition audit.
- [reconcile_completion.py](reconcile_completion.py) reproduces the reconciliation without invoking OMNeT++.
- Pre-reconciliation copies of the analysis, JSON, matrix, and checkpoint are retained with the suffix `_pre_reconciliation_2026-10-22`.

This remains exploratory evidence for the fixed D3 absolute profile, not official C4 validation or evidence of continuous clock conformance. L3 remains outside the tested domain. No further execution is authorized by this completed step.
