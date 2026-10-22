# C4 fixed L2 profile pilot

This isolated pilot tests the complete absolute D3/L2 CBS profile in L0/A0 and L1/A1, with matched TAS and noTAS runs. It used four seed-41 simulations, each with a cell-specific F21/F22 calendar, 1 s warm-up, 30 s measurement, and 50 ms drain.

The fixed profile removed the application and overflow failures seen in the load-scaled D3/C3 controls in these two tested cells: all four runs passed the technical, application, queue-stability, and relevant GCL/noTAS checks, with zero queue-overflow drops. The TAS and noTAS runs both passed; TAS increased brake latency relative to the same-profile noTAS control. Simultaneous native-tick clock samples were below 1 µs, while continuous synchronization conformity remains unverified. The result is limited to seed 41 and these two cells.

See [`results/analysis.md`](results/analysis.md) and [`results/pilot_results.json`](results/pilot_results.json) for the comparisons, flow and queue metrics, reservations, calendar pairing, and evidence inventory. The complete 24-entry frozen table is [`results/frozen_profile_table.csv`](results/frozen_profile_table.csv); its canonical profile hash is in `results/plan.json`. The preregistration is [`protocol.md`](protocol.md).

To reproduce, run `python3 simulations/pilot/c4_fixed_L2_profile/run_fixed.py` from the repository root. Runs are serial and update `results/checkpoint.json` and `results/runs.jsonl`. Resume only after checking the checkpoint: `python3 simulations/pilot/c4_fixed_L2_profile/run_fixed.py --resume`. The live display is `python3 simulations/pilot/c4_fixed_L2_profile/dashboard.py`. Never start another runner while one is active. Rebuild the consolidated reports from preserved artifacts with `python3 simulations/pilot/c4_fixed_L2_profile/consolidate.py`.

This remains exploratory: it does not modify P1, official C0–C3, or freeze/validate the full C4 campaign.
