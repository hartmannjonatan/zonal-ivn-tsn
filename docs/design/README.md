# Design notes

The authoritative specification is the [final P1](P1-final.pdf), installed from the attachment dated 2026-10-22. Its SHA-256 is `2c26a823006a3122692fdcbae931a10af12b10bd10b67375e7bf4969bec59e7f`.

[`P1-v4.pdf`](P1-v4.pdf) is retained as the previous specification because historical campaign and pilot manifests record its bytes. It was present in the repository on 2026-10-03; SHA-256: `87809f1b5e22f72e7c58ad2f3a90aab8476e58a80e7417b82f47897af66235f5`. It is historical, not the current design authority.

This page records only project-specific context that is useful beyond the specification.

## Exploratory mapping pilot

The first P1 mapping put some camera and audio flows in TC6 with the LiDAR/radar sensors. An isolated L2/A1 pilot compared that mapping with a two-class CBS mapping that reserves TC6 for the 100 µs sensors and groups the remaining CBS traffic in TC4. The pilot provided evidence for changing the common mapping, but it is exploratory and is excluded from the official campaign aggregates.

The revised mapping is PCP6/TC6 for F01, F06, and F07; PCP4/TC4 for F02–F05, F11–F14, F21, and F22; PCP7/TC7 for F08–F10; PCP3/TC3 for F15–F17; and PCP0/TC0 for F18–F20. The final P1 formalizes this mapping. TC6 and TC4 are benchmark CBS classes; this project does not claim standard SR-A/SR-B contracts.

The corrected pilot report distinguishes the first viable fixed profile (`candidate_15`, checked with seeds 41, 43, and 47) from the last tested reduction (`reduction_12`, checked only with seed 41). The latter is not established as a minimum or optimum. See [`simulations/pilot/reclassification/results/analysis_corrected.md`](../../simulations/pilot/reclassification/results/analysis_corrected.md) and its adjacent JSON for the evidence and limitations.

## Official campaign

The existing official campaign uses a separate manifest and results directory under `simulations/campaigns/p1-v2-official-2026-10/`; its frozen provenance remains bound to the P1 v4 bytes above. Do not rewrite that manifest to point at the newer PDF. Pilot and earlier C0–C3 results are historical context only. The campaign report and checkpoint in that directory define its execution state. The C4 exploratory studies and their current reconciled conclusion are summarized in [`simulations/pilot/README_C4_CBS_TAS.md`](../../simulations/pilot/README_C4_CBS_TAS.md); that report does not freeze C4 operationally or start its official campaign.
