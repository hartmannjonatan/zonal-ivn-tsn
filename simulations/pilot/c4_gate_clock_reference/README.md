# C4 gate-clock reference diagnostic

This isolated diagnostic compares A005 with local TAS clocks, an ideal simulation-time reference on HPC→CSW, and ideal references on all four shared egresses. The three L2/A1, seed-41 runs are paired with the same F21/F22 calendar. No simulation is active; P1, official settings and the frozen C3 profile remain unchanged.

The current audit is [`results/audits/audit_2026-10-14/audit.md`](results/audits/audit_2026-10-14/audit.md), with machine-readable evidence in [`audit.json`](results/audits/audit_2026-10-14/audit.json). It recalculates boundary balances for HPC/TC4 and CSW.eth[1..3]/TC4, uses each queue's actual capacity when checking stability, identifies Z3.ZSW.eth[7]/TC4 as the permanent F13 queue, and distinguishes the operational stability proxy from P1's qualitative wording. The prior report and pre-audit summary are preserved in that audit directory.

Three runs are complete, all application gates pass, and the 1 ms sampled synchronization check passes; continuous synchronization remains unverified. The repository stability predicate rejects all three: `A005_local` at HPC/TC4 and both ideal controls at Z3/TC4. `A005_ideal_HPC` has positive CSW.eth[1]/eth[2] trends, but their ~20.7 kbit rise is below the 52.4 kbit threshold for 128 KiB queues. Changing only the HPC reference removes HPC's measured growth; ideal-all timing removes the CSW trend while the late episodic Z3 rise still trips the proxy. Ideal timing remains a diagnostic control, not an approved C4 solution.

Compact traces and calendars remain in `results/runs/` and `results/calendars/`. Reprocessing commands, hashes, storage inventory and limitations are listed in the audit JSON. Reprocess the queue evidence without launching OMNeT++ with:

```sh
python3 simulations/pilot/c4_gate_clock_reference/results/audits/audit_2026-10-14/reprocess_audit.py
python3 simulations/pilot/c4_gate_clock_reference/results/audits/audit_2026-10-14/recalculate_z3.py
python3 simulations/pilot/c4_gate_clock_reference/results/audits/audit_2026-10-14/make_plots.py
python3 simulations/pilot/c4_gate_clock_reference/results/audits/audit_2026-10-14/consolidate_audit.py
```

`analyze_diagnostic.py` now stores the current queue state at the end of the measurement window instead of the preceding vector row. The original summary is retained as `results/audits/audit_2026-10-14/diagnostic_results_before_audit.json`. Flags remain `exploratory=true`, `diagnostic_only=true`, `official_c4_frozen=false`.
