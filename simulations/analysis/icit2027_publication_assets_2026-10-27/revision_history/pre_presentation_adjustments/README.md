# ICIT results figures and tables

Generated from the frozen editorial synthesis at `simulations/analysis/icit2027_editorial_synthesis_2026-10-27`; cutoff **2026-10-27T16:43:14-03:00**. The script reads audited derived data only and does not invoke simulations or inspect live campaign output.

## Editorial labels and coverage

| Article label | Historical campaign ID |
|---|---|
| C0 — SP | C0 |
| C1 — Source pre-shaping | C1 |
| C2 — Calibrated CBS | C3 |
| C3 — Joint CBS/TAS | C4 |

The frozen data contain C0: 240 runs, C1: 240, C2: 180, and C3: 90. In the main viability table, each admissible position targets 30 runs; `$^\dagger$` marks `n<30`. `R` indicates rejection by the CBS reservation screen and `S` rejection by the service screen. Rejected positions are not counted as failed simulations.

The common C2/C3 subset has 90 pairs: 60 C2-fail/C3-pass at L0, 24 at L1, and 6 both-pass at L2. `paired_viability.csv` checks calendar signature and offered F21/F22 populations for each pair.

## Statistics and units

- Figure 1 uses C0/C1, F02/F05, A1, L0--L3; the run-level CSV also includes L0/A0. Completion is complete images divided by offered images for each run. Image p99 is computed within each run among complete images only, in milliseconds. Points are runs, diamonds are medians, and bars are interquartile ranges across runs. Deadlines: F02 10 ms; F05 30 ms.
- Figure 2 uses A0, L0--L2. Per run, panel (a) is `max(p99(F06), p99(F07))`; panel (b) is `max(p99(F08), p99(F09), p99(F10))`, in microseconds. This is a maximum across flow-specific run p99s, not a pooled percentile. Each point is an execution; diamonds and bars show median and IQR. The line is the 100 µs deadline. Partial C3 counts are printed above the groups; absent groups are not zero-valued.
- `paired_C3_minus_C2_latency.csv` separates paired changes in the maximum flow-level p99, maximum observed latency, and approval. C3--C2 compares full policies, including CBS profile and synchronization, as well as gates.
- The reservation table reports configured `idleSlope` in Mb/s. Port totals/headroom are per egress; they are not link utilization and must not be summed across hops as consumed bandwidth.

## Verified aggregates and caveats

For C0/L3/A1, the generated data reproduce F02 losses/incomplete images `219,747/219,565` and F05 `360,145/186,094`; C1 has zero packet losses and zero incomplete images in these cohorts. The low C0/F02 completion fraction is annotated. A lower p99 among C0's surviving complete images is not evidence of better delivery.

The displayed and exported results use only the frozen 90-run C3 (historic C4) cutoff. The earlier technical failed attempt and any later campaign results are excluded. Synchronization evidence remains sampled; it does not establish continuous-time compliance. Figures are exploratory run-level summaries and do not pool packets/images across seeds as independent experimental units.

## Files

- `fig_camera_delivery_latency.{pdf,svg,png}` and `fig_critical_latency.{pdf,svg,png}`
- `table_viability.csv/.tex`, `paired_viability.csv`, `paired_viability_summary_by_load.csv`
- `fig1_camera_runs.csv`, `fig1_camera_summary.csv`, `fig2_critical_latency_runs.csv`
- `paired_C3_minus_C2_latency.csv`, `paired_C3_minus_C2_latency_summary.csv`
- `table_reservations.csv/.tex`, `figure_captions.tex`, `figure_includes.tex`
- `analysis_manifest.json`, `generate_assets.py`

## Regenerate

```bash
/home/jonatan/omnetpp/.venv/bin/python3 simulations/analysis/icit2027_publication_assets_2026-10-27/generate_assets.py
```
