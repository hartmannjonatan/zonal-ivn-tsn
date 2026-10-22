# Technical correction addendum 006: BM gate schedule

This addendum is recorded before the replacement execution. The preregistered protocol, candidate set, thresholds, workload, CBS profile, F21/F22 calendar, seeds, and budget are unchanged.

The configuration audit found that the original `BM_recovery` run used the R cadence schedule `[47.995 us, 52 us]` / `[52 us, 47.995 us]`, although the preregistered BM variant must use the audited B-local schedule `[77 us, 23 us]` / `[10 us, 90 us]`. The original run is preserved and is excluded from the corrected BM−B and RPM−BM contrasts. R, RP, and RPM are unaffected by this finding.

The runner and its effective-GCL checker are being corrected to map `BM_recovery` to B-local gates, retaining A005 plus only the preregistered 2% Z3.ZSW.eth[7]/TC4 idleSlope change. One technical replacement is authorized and used under a new execution ID, with the same seed, L2/A1 workload and F21/F22 signature. This is the second technical replacement within the protocol maximum of two. It is not a new candidate or an additional methodological cell.

The shared validator's `tas_gate_schedule` used fixed A005 duty-cycle expectations for every pilot treatment. The analysis will preserve that old field and recompute the current expected fractions from the SCA `effective_gcl` durations, matching them to the existing gate-state event trace with the preregistered 1e-4 tolerance. This is a post-processing correction; effective GCL configuration is independently checked by the runner. No simulation results or official configuration are overwritten.

The first replacement preflight was stopped before launching OMNeT++ because the runner's `pgrep -af` check matched the command line of its own caller. No simulator process was started and no methodological execution was consumed. The preflight now checks the process executable name (`comm`) only; this technical guard correction is included in the addendum's source hashes.
