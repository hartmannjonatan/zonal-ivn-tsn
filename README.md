# Zonal IVN TSN benchmark

This repository contains the OMNeT++/INET zonal in-vehicle Ethernet model, P1 traffic profiles, official campaign tools, and analysis artifacts.

## Reference and organization

- [Final P1 specification](docs/design/P1-final.pdf); [design notes](docs/design/README.md).
- `src/`, `simulations/zonal/` — model modules, network topology, and canonical traffic configuration.
- `simulations/campaigns/p1-v2-official-2026-10/` — official P1 campaign manifests, ledgers, checkpoints, and operator guide. C0–C3 and C4 keep separate ledgers/checkpoints.
- `simulations/c4_official/` — frozen operational C4 profile, validation contract, and clock probes.
- `simulations/pilot/` — exploratory evidence; the closed CBS/TAS study is summarized in [README_C4_CBS_TAS.md](simulations/pilot/README_C4_CBS_TAS.md).
- `simulations/analysis/icit2027_editorial_synthesis_2026-10-27/` — frozen, audit-ready analysis inputs for the paper.
- `simulations/analysis/icit2027_publication_assets_2026-10-27/` — publication figures, tables, captions, and the script that regenerates them without simulations.
- `scripts/`, `tests/validation/` — build, campaign validation, and regression checks.

## Build

Use OMNeT++ 6.4.0 and INET 4.7.0. Load the OMNeT++ environment and set `INET_ROOT` to the INET checkout before compiling:

```bash
source /path/to/omnetpp/setenv
export INET_ROOT=/path/to/inet-4.7.0
bash scripts/run/build.sh
```

## Official campaign

Read the [campaign operator guide](simulations/campaigns/p1-v2-official-2026-10/README.md) before running. It covers the two-machine split, runtime bundle, safe preflight, dashboard, resume, and result merge. Do not launch child runners directly or run two campaign workers on one host.

On the C0-owning host, the read-only status panel and C3/C4 preflight are:

```bash
python3 simulations/campaigns/p1-v2-official-2026-10/campaign_status.py
python3 simulations/campaigns/p1-v2-official-2026-10/run_official_campaign.py --preflight-c3-c4-shard
```

As of the last local status check (2026-10-28 20:27 −03:00), C0 and C3 were complete, C4 had 90/180 valid results, and its checkpoint was `paused_technical_review` with no active simulator. **Review that checkpoint and its failed-run log before resuming.** The nine-run priority order is recorded in the C4 runtime amendment; after the technical pause is resolved, the C4-specific resume command is documented in the [C4 guide](simulations/campaigns/p1-v2-official-2026-10/c4_official/README.md).

For the closed exploratory C4 development and the paper-ready ICIT assets, use the linked pilot and analysis READMEs; neither is an official campaign result.
