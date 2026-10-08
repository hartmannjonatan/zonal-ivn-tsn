# Design notes

[P1 v4](P1-v4.pdf) is the authoritative specification. This page records only project-specific context that is useful beyond the specification.

## Exploratory mapping pilot

The first P1 mapping put some camera and audio flows in TC6 with the LiDAR/radar sensors. An isolated L2/A1 pilot compared that mapping with a two-class CBS mapping that reserves TC6 for the 100 µs sensors and groups the remaining CBS traffic in TC4. The pilot provided evidence for changing the common mapping, but it is exploratory and is excluded from the official campaign aggregates.

The revised mapping is PCP6/TC6 for F01, F06, and F07; PCP4/TC4 for F02–F05, F11–F14, F21, and F22; PCP7/TC7 for F08–F10; PCP3/TC3 for F15–F17; and PCP0/TC0 for F18–F20. P1 v4 formalizes this mapping. TC6 and TC4 are benchmark CBS classes; this project does not claim standard SR-A/SR-B contracts.

The corrected pilot report distinguishes the first viable fixed profile (`candidate_15`, checked with seeds 41, 43, and 47) from the last tested reduction (`reduction_12`, checked only with seed 41). The latter is not established as a minimum or optimum. See [`simulations/pilot/reclassification/results/analysis_corrected.md`](../../simulations/pilot/reclassification/results/analysis_corrected.md) and its adjacent JSON for the evidence and limitations.

## Official campaign

The official P1 v4 campaign uses a separate manifest and results directory under `simulations/campaigns/p1-v2-official-2026-10/`. Pilot and earlier C0–C3 results are historical context only. The campaign report and checkpoint in that directory define its current execution state.
