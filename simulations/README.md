# Simulations

`zonal/` contains the P1 network model, traffic configuration, and treatment definitions. `campaigns/p1-v2-official-2026-10/` contains the isolated official runner, calibration protocol, checkpoints, and campaign results. Its results are separate from all historical runs.

`pilot/reclassification/` preserves the exploratory old-versus-revised mapping study and the evidence behind the mapping formalized in the final P1. It is not part of the official aggregates. The [pilot index](pilot/README.md) links to the consolidated, closed C4 CBS/TAS exploration. `tsn_validation/` contains small INET mechanism scenarios retained for reference and visual inspection.

The official runner supports resume from audited records and currently limits execution to four parallel jobs. Run `python3 simulations/campaigns/p1-v2-official-2026-10/run_campaign.py --help` for options. Do not mix files under `simulations/results/` or the pilot results with the official campaign output.
