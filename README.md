# Zonal IVN TSN benchmark

This repository contains an OMNeT++/INET model of a zonal in-vehicle Ethernet network and the traffic, shaping, and validation code for the P1 study.

The current specification is the [final P1](docs/design/P1-final.pdf). The previous [P1 v4](docs/design/P1-v4.pdf) is retained for historical manifests that bind to its hash. Project-specific context is summarized in [design notes](docs/design/README.md); the closed exploratory C4 CBS/TAS study is consolidated in [the C4 pilot report](simulations/pilot/README_C4_CBS_TAS.md).

## Repository layout

- `simulations/zonal/` — network NED, layered INI configuration, and canonical traffic inputs.
- `simulations/campaigns/` — the isolated official campaign runner, manifests, checkpoints, and results.
- `simulations/pilot/` — exploratory pilots and preserved evidence; see the [pilot index](simulations/pilot/README.md).
- `simulations/tsn_validation/` — small INET mechanism scenarios retained as reference cases.
- `src/` — reusable application, traffic-planning, audit, and link modules.
- `scripts/` — catalog generation, build, and validation tools.
- `tests/validation/` — P1 acceptance checks and focused regression tests.
- `docs/` — design notes, catalog notes, and research reports.

## Dependencies

Use OMNeT++ 6.4.0, INET 4.7.0, a C++ toolchain supported by OMNeT++, GNU Make, and Python 3. Load the OMNeT++ environment and set `INET_ROOT` to the INET 4.7.0 checkout before building.

## Build and run

```bash
source /path/to/omnetpp/setenv
export INET_ROOT=/path/to/inet-4.7.0
bash scripts/run/build.sh
python3 simulations/campaigns/p1-v2-official-2026-10/run_campaign.py --phase final --resume --jobs 4
```

The runner supports checkpoints and `--stop-after-cell`; see its `--help` output before starting or resuming a campaign. The current operational worker limit is four.

For the traffic sources and generated files, see [docs/traffic-catalog/README.md](docs/traffic-catalog/README.md). For validation scope, see [tests/validation/README.md](tests/validation/README.md).
