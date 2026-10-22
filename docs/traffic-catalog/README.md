# Traffic catalog

The canonical inputs are `simulations/zonal/traffic/flows.csv` and `transients.csv`. They define the 22 flows, endpoints, sizes, timing, deadlines, VLANs, PCPs, and transient event classes. The [final P1](../design/P1-final.pdf) defines the traffic requirements; this page identifies the implementation files and generation process.

Run `python3 scripts/catalog/generate.py` to generate `catalog.xml` and `configs/catalog-bindings.ini` from the CSV inputs. Use `--check` to verify generated files without rewriting them. `scripts/catalog/generate_cbs.py` derives nominal CBS reservation artifacts from permanent routed traffic; F21/F22 use TC4 when active but are excluded from permanent reservations.

The effective common mapping is PCP6/TC6 for F01/F06/F07, PCP4/TC4 for F02–F05/F11–F14/F21/F22, PCP7/TC7 for F08–F10, PCP3/TC3 for F15–F17, and PCP0/TC0 for F18–F20. CBS uses TC6 and TC4 as custom benchmark classes. In C2/C3, it is enabled only on egresses with a positive permanent nominal reservation; transient-only TC4 egresses remain under SP.

The official campaign stores its per-egress flow mapping, effective reservation profiles, and manifests under `simulations/campaigns/p1-v2-official-2026-10/`. Older calibrated files in `simulations/zonal/traffic/` are historical artifacts, not inputs to the official campaign runner.
