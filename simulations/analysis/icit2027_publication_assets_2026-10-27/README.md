# ICIT results figures and tables

This package is derived only from `simulations/analysis/icit2027_editorial_synthesis_2026-10-27` at the frozen cutoff **2026-10-27T16:43:14-03:00**. `generate_assets.py` reads audited derived data, validates the cutoff and treatment IDs, and writes publication assets. It does not invoke simulations or read live campaign outputs.

## Editorial labels and frozen coverage

| Article label | Historical campaign ID |
|---|---|
| C0 — SP | C0 |
| C1 — Source pre-shaping | C1 |
| C2 — Calibrated CBS | C3 |
| C3 — Joint CBS/TAS | C4 |

Included counts: C0 = 240, C1 = 240, C2 = 180, and C3 = 90. The 90 article-C3 execution IDs and report hashes match `c4_cutoff.json` exactly. Later campaign rows are excluded; the technical-invalid attempt `C4_L1_A0_seed1022` is not an included result. No execution IDs are duplicated.

`table_viability.tex` reports approved/completed runs. Every admissible cell targets 30 repetitions; `†` marks `n<30`. `R` and `S` denote pre-simulation rejection by the reservation and service screens, respectively. Neither symbol means a failed simulation. A pass describes the observed runs, not deterministic or hard-real-time assurance.

The common C2/C3 subset contains 90 pairs: 60/60 C2-fail/C3-pass at L0; 24/24 at L1; and 6/6 both-pass at L2. All pairs match calendar signatures and offered F21/F22 populations. The per-pair evidence is in `paired_viability.csv`.

## Figures and statistics

- **Camera figure:** C0/C1, F02/F05, A1, L0--L3; 30 runs in every treatment/load combination. Small points are individual runs. The larger, treatment-matched symbol is the median across runs; bars are IQR (25th--75th percentile), not confidence intervals. Completion is calculated per run as complete images/offered images. The F02 and F05 callouts show the median per-run completion: **2.39%** and **17.57%**. Aggregated over runs, the corresponding completion fractions are **2.42%** and **17.29%**; these aggregate values are separately preserved in `fig1_camera_summary.csv`. The image p99 is calculated separately per run among complete images only. Dashed lines mark the F02 10-ms and F05 30-ms deadlines. C0's lower survivor-only p99 does not mean better image delivery.
- **Critical-flow figure:** A0, L0--L2. Panel (a) is the per-execution maximum of the flow-level p99 values for F06/F07; panel (b) is the per-execution maximum of the flow-level p99 values for F08--F10. It is neither a packet maximum nor a pooled-population p99. Each small point is one run; treatment-matched larger markers are medians and bars are IQR. Dashed line: 100 µs. C0--C2 have n=30 per plotted cell; C3 counts (30, 21, 3 across L0--L2) are labelled at each group. All observations are retained, including the low brake points: in C3/A0, seed 1006 has a 28.385 µs maximum across brake-flow p99s and seed 1010 has 7.212 µs in both L0 and L1. These agree with the prior consolidation; no cause is inferred. The largest observed brake latency across all 90 C3 runs is **78.460831 µs** (C4_L0_A0_seed1027, F08). A p99 plot alone does not establish hard-deadline compliance.
- `paired_C3_minus_C2_latency.csv` reports, separately, flow-level p99s, observed maxima, their paired differences, and approval. C2--C3 is a full-policy contrast: reservations, the cross-load reservation rule, synchronization, and TAS differ; it does not isolate TAS.
- `table_reservations.csv` retains the complete 24-row selected-port data with exact rates and per-port context. `table_reservations_compact.csv` and `table_reservations.tex` give the requested four-row summary. `idleSlope` is a configured rate per egress/class, not measured utilization. Port totals and headroom apply to one egress only and must not be summed across hops as link use.

## Verified camera aggregates and synchronization

The source values reproduce C0/L3/A1 F02 **219,747 packet losses** and **219,565 incomplete images**, and F05 **360,145 packet losses** and **186,094 incomplete images**. C1 has zero packet losses and zero incomplete images in those cohorts. The C0 L3/A1 annotation uses median run completeness, not the pooled aggregate.

Synchronization was approved on the available samples; continuous-time synchronization conformance was not demonstrated. No plot combines packet/image samples across seeds to create a pooled p99. The simulation is the experimental unit.

## Files and regeneration

- `fig_camera_delivery_latency.{pdf,svg,png}` and `fig_critical_latency.{pdf,svg,png}` (vector PDF/SVG; 400-dpi PNG review copies; 7.0-in canvas width, with tight PDF bounds checked against the IEEE two-column width).
- `table_viability.csv/.tex`, `paired_viability.csv`, `paired_viability_summary_by_load.csv`.
- `fig1_camera_runs.csv`, `fig1_camera_summary.csv`, `fig2_critical_latency_runs.csv`.
- `paired_C3_minus_C2_latency.csv`, `paired_C3_minus_C2_latency_summary.csv`.
- Complete `table_reservations.csv`; compact `table_reservations_compact.csv`; compact `table_reservations.tex`.
- `figure_captions.tex`, `figure_includes.tex`, `analysis_manifest.json`, and `generate_assets.py`.
- Pre-revision copies of the small edited files are retained under `revision_history/pre_presentation_adjustments/`; no raw simulation data were duplicated.

To regenerate with the project's virtual environment:

```bash
MPLCONFIGDIR=/tmp/mpl-icit-publication /home/jonatan/omnetpp/.venv/bin/python3 simulations/analysis/icit2027_publication_assets_2026-10-27/generate_assets.py
```
