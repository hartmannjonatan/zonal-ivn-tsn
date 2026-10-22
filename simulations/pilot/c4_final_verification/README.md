# C4 absolute-profile final verification (exploratory)

This isolated pilot evaluates the absolute 24-entry `D3_coordinated_20pct` reservation profile with frozen TAS and gates-open treatments. It does not modify P1 or the official C0–C3 profiles. Status: `exploratory=true`, `official_c4_frozen=false`.

- `answers_previous_questions.md`: buffer, isolation, C3 control, D3 identity, and synchronization audit.
- `protocol.md`, `manifest.json`, `frozen_profile_table.csv`, `treatment_contracts.json`: preregistered protocol and immutable candidate definition.
- `matrix.csv`, `results/checkpoint.json`, `results/runs.jsonl`: coverage and checkpoint. Reused positions are explicitly sourced; partial attempts are not results.
- `pilot_results.json`, `analysis.md`: current consolidated data and interpretation.
- `results/reconciliation_2026-10-22.json` and `reconcile_completion.py`: post-run reconciliation of reused native-tick synchronization data, coverage, and the runner's conditional phase transition. This script only reads saved results and does not run simulations.
- `proposed_P1_C4_revision.md`: prospective C4-only proposal; not applied.
- `runner_correction_addendum.json`: technical runner corrections after freezing the protocol.

The authorized pilot scope is complete: 36/36 L0–L2 positions are covered, and all 12 L3 positions were rejected by the frozen pre-run triage. Ten results were reused and 26 newly completed; two interrupted technical attempts were preserved and replaced. The checkpoint reports `phase2_complete` with no active run. The reused synchronization flags were recalculated from native-tick evidence; continuous conformance remains unverified. See `analysis.md` for the runner-transition audit and limitations. Do not start the official C4 campaign from this pilot.

## Live progress panel

From the repository root, run:

```bash
python3 simulations/pilot/c4_final_verification/dashboard.py
```

The panel refreshes in place every three seconds and shows completed, reused, active, pending, and triage-rejected positions, plus the active simulator's log progress and available memory/disk. Use `--interval 5` to change the refresh period or `--once` for a single snapshot. Pressing Ctrl-C closes only the panel; it does not stop the runner.
