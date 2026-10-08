# Scripts

- `catalog/generate.py` exports the canonical CSV catalog to OMNeT++ XML and INI bindings; `--check` verifies generated outputs.
- `catalog/generate_cbs.py` generates nominal CBS reservations from permanent routed flows.
- `catalog/generate_c3.py` generates legacy calibration artifacts; the official search is implemented by the campaign package.
- `run/build.sh` checks generated catalog files and builds the C++ model against INET.
- `run/validate_traffic.py` and `run/validate_c0.py` through `validate_c3.py` run the traffic and treatment validators. `diagnose_c2.py` and `analyze_c3_calibration.py` provide focused diagnostics.

The official campaign runner and its read-only progress dashboard are in `simulations/campaigns/p1-v2-official-2026-10/`. Validation scripts write to the configured simulation results area; inspect each script's `--help` before use.
