# C4 shared-link / SP-brake pilot

This is an isolated, exploratory C4 pilot. It does not modify the P1, the frozen C3 profile, official C0–C3 configurations, or the official campaign. The previous pilot remains at [`../c4_service_preservation/`](../c4_service_preservation/) as historical evidence.

The completed pilot contains 16/16 scheduled runs, including paired L2/A1 runs for seeds 41, 43, and 47. SP at the route-correct brake outputs recovered F08–F10 application deadlines, but C4 did not pass overall because TC4 queues were unstable and the strict gPTP ≤1 µs criterion remains unapproved. The old millisecond offset maxima were an export-order artifact; corrected 1 ms samples are below threshold, while direct seed-43 probes observed rare 10 µs excursions in both C3_sync and C4. Read the [pilot analysis](results/analysis.md), [synchronization audit](audits/synchronization_2026_10_12/audit.md), and [structured results](results/pilot_results.json). These exploratory results do not validate or freeze an official C4.

The experiment compares `C3_base`, `C3_sync`, `C4_shared_SPbrakes`, and a one-seed `C4_compensated_fullpath_corrected` diagnostic. The shared-SP-brakes treatment gates only `HPC.eth[0]`, `CSW.eth[1..3]`; the brake-facing outputs `Z1.ZSW.eth[4]`, `Z2.ZSW.eth[4]`, and `Z3.ZSW.eth[5]` remain SP with always-open gates. C4 CBS compensation is fixed at `idleSlope_C3 / 0.77` only on CBS queues subject to TAS. Profile identity is checked against the official campaign checkpoint and `reduction_11` calibration record.

The runner uses one simulation job on this laptop, serial post-processing, a 45 GB free-space floor, atomic checkpoint/ledger writes, and refuses to run while the official campaign lock/process is active. For additional desktop responsiveness, launch it at reduced CPU/I/O priority with `nice -n 15 ionice -c 3`. It sets OMNeT++/INET library paths itself, so an interactive shell setup is not required. It never reuses historical output. No simulation is started by `--plan` or `--check`.

After reviewing the plan, run:

```bash
python3 simulations/pilot/c4_shared_sp_brakes/run_pilot.py --plan
python3 simulations/pilot/c4_shared_sp_brakes/pilot_status.py
nice -n 15 ionice -c 3 python3 -u simulations/pilot/c4_shared_sp_brakes/run_pilot.py --run
```

Resume only this pilot after checking its checkpoint and dashboard:

```bash
nice -n 15 ionice -c 3 python3 -u simulations/pilot/c4_shared_sp_brakes/run_pilot.py --run --resume
```

The dashboard is read-only and refreshes in place. Results and resumable state are stored only under `results/`. Current shared `TrafficAudit` output has no per-packet timestamps at each hop, so exact F08–F10 gate-wait attribution is unavailable unless isolated hop-level instrumentation is added before running. See [`protocol.md`](protocol.md) for the preregistered run order, criteria, retention, and limits. `exploratory=true`; `official_c4_frozen=false`.
