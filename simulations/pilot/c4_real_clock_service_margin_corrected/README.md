# Corrected C4 service-margin pilot

This isolated seed-41 continuation repairs the CBS construction and audit defects found in the 2026-10-18 audit. Its historical predecessor runs remain preserved as gated-SP diagnostics without CBS. Read `protocol.md` and `treatment_contracts.json` for the preregistered scope and effective parameter contract.

The executor runs serially, checkpoints each treatment, stops below 40 GiB free disk or 7 GiB available memory, and refuses to start alongside the official campaign or another simulator. It streams vectors and retains compressed audit evidence. B is a release gate: its compact queue trace is independently recalculated and compared with the historical A005 CBS run before C3/BM can start; the preregistered comparison limits are in `protocol.md`. `results/plan.json`, `results/protocol_manifest.json`, and `results/expected_cbs_profile_table.csv` record the pre-run hashes, effective module/rate contract, and service-admissibility decisions. `results/checkpoint.json` and `results/runs.jsonl` are the progress/result sources of truth.

Run commands from the repository root:

```bash
source /home/jonatan/omnetpp-env.sh
export INET_ROOT=/home/jonatan/omnetpp/samples/inet-4.7.0
python3 simulations/pilot/c4_real_clock_service_margin_corrected/run_pilot.py --self-test-validation
python3 simulations/pilot/c4_real_clock_service_margin_corrected/run_pilot.py --plan
python3 simulations/pilot/c4_real_clock_service_margin_corrected/run_pilot.py --preflight
python3 simulations/pilot/c4_real_clock_service_margin_corrected/run_pilot.py --run-first
python3 simulations/pilot/c4_real_clock_service_margin_corrected/run_pilot.py --continue-initial
python3 simulations/pilot/c4_real_clock_service_margin_corrected/dashboard.py
```

`--run-first` executes only B/A005. Inspect `results/checkpoint.json`, `results/runs.jsonl`, and the completed B report before using `--continue-initial`. The remaining run list is taken from the frozen plan; R/RP/RPM are rejected before simulation when the optimistic CBS credit-service upper bound is below observed queue demand. This stage does not authorize seeds 43/47, L0/L1, artificial backlog, or the final C4 campaign.

The historical demand extraction is reproducible with `python3 simulations/pilot/c4_real_clock_service_margin_corrected/derive_historical_demand.py`; it streams the preserved valid A005 service vector and writes a compact JSON summary.

The initial seed-41 set is complete: B, `C3_sync_control`, and BM. The checkpoint and `results/runs.jsonl` are authoritative for execution state; `results/pilot_results.json` and `results/analysis.md` are the current consolidated analysis. B and BM pass application gates but fail the existing stability gate because HPC/TC4 grows; the C3 control passes application and stability gates. R, RP, and RPM were rejected before execution by the preregistered optimistic upper-service bound. No C4 treatment has been frozen or validated, and no other seed/cell or final C4 campaign was run.

The old synchronization summary based on interpolated vectors is preserved as historical and is not decision evidence. The current audit uses the simultaneous native-tick samples from each `clock_precision.csv`, computes offsets before rounding, and verifies every stored offset against `node_clock_raw - HPC_clock_raw`. Sampled offsets pass 1 µs at the 1 ms observation points; continuous conformity remains unverified. Rebuild the consolidation without running OMNeT++ with:

```bash
python3 simulations/pilot/c4_real_clock_service_margin_corrected/consolidate_results.py
```

This produces compressed, recalculable native-tick offset samples under each run. B's earlier strict gate-timing rejection and correction remain documented in `protocol_addendum_2026-10-19_gate-runtime-check.md`; B's event accounting retains an unresolved one-frame boundary residual, which is not classified as a drop. BM's 2% local increase on Z3/TC4 recovered an observed natural F13 queue episode while F13 remained active, but it did not remove HPC/TC4 growth and does not establish a general service guarantee. The F13 backlog-injection diagnostic, further seeds, extrapolations, and final C4 campaign remain unexecuted.

The full raw B traces remain preserved. Later-run compression was accepted only after streaming decompression reproduced the original SHA-256; the compact event, queue, gate, credit, and clock evidence is retained.
