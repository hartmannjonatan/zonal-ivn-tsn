# C4 joint GCL/CBS pilot

This isolated exploratory pilot evaluates three preregistered joint GCL/CBS designs for C4 with real local clocks. It preserves the P1, official configurations, C0–C3 and the frozen C3 profile. No official C4 campaign is started and `official_c4_frozen=false`.

Read [`protocol.md`](protocol.md), then [`results/analysis.md`](results/analysis.md) and [`results/pilot_results.json`](results/pilot_results.json). The report covers the completed L2/A1, seed-41 screen: B/A005 and C3_sync were reused after equivalence checks; D1–D3 each ran with TAS and with gates open at identical CBS reservations. No candidate passed all application gates, so the preregistered seed 43/47 and L0/L1 checks were not triggered.

`dimension_candidates.py` deterministically builds the three frozen profiles. `run_joint_pilot.py` runs the isolated simulations one at a time with checkpointing and resource floors. Use its documented `--plan`, `--self-test-validation`, `--preflight`, and `--run-initial` options only when intentionally reproducing this pilot. The report-only command is:

```sh
python3 simulations/pilot/c4_joint_dimensioning/consolidate_results.py
```

It does not launch simulations. `results/checkpoint.json` and `results/runs.jsonl` preserve runner progress and original execution fields; `results/runs_audited.jsonl` is the corrected derived ledger, including the native-tick clock audit. Compressed vectors, packet/queue events, clock precision data, gate states, credit evidence and per-flow outputs are retained under `results/runs/`; old pilot evidence was not removed. Before any future run, check free space and retain at least 40 GiB.
