# C4 real-clock service-margin pilot

This is an isolated exploratory pilot. It is **not** official C4 validation. The authoritative post-run audit is [audit.md](results/audits/audit_2026-10-18/audit.md), with machine-readable evidence in [audit.json](results/audits/audit_2026-10-18/audit.json) and a prospective, not-yet-authorized protocol proposal in [proposal_addendum.md](results/audits/audit_2026-10-18/proposal_addendum.md).

The audit found that the six seed-41 runs did not instantiate CBS: the pilot runner wrote `idleSlope` values to optional transmission-selection submodules but omitted their CBS `typename`. The run summaries and historical comparisons are preserved, but they are not valid evidence for the registered CBS treatments. RPM also ran with R's 0 µs phase instead of RP's registered 98.995 µs modulo 99.995 µs phase. F13's physical CBS margin is inconclusive; recovery of the historical backlog was not evaluated.

No simulations were run during the audit. Pre-audit summaries and the 14 October gate-clock audit are preserved under `results/audits/audit_2026-10-18/preserved_before_audit/`. Raw data were neither copied nor deleted. The original protocol and addenda remain unchanged. Keep `exploratory=true` and `official_c4_frozen=false`.

To reproduce the audit from existing files, run `reprocess_existing.py` and then `apply_audit_overlay.py` from the audit directory. These scripts only read saved data and update audit/summary files; they do not invoke OMNeT++.
