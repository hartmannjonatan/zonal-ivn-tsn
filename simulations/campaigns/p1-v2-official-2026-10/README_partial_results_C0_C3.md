# Partial official-campaign results: C0 and C3

**Snapshot:** 25 October 2026, 12:35 BRT. This is a live, interim summary of the official P1 v2 campaign. It does not replace the final campaign analysis.

> **Historical snapshot:** the progress and active-run statements below describe only the timestamp above and are not current campaign status. For current progress, use [`campaign_status.py`](campaign_status.py) and the per-run checkpoints. This file is retained as a dated record; do not use its pending counts to resume the campaign.

## Scope and status

The official campaign uses 1 s warm-up, a 30 s measurement interval `[1,31)`, 50 ms drain, and seeds 1001–1030. The common mapping is PCP6/TC6 for F01/F06/F07, PCP4/TC4 for F02–F05/F11–F14/F21–F22, PCP7/TC7 for F08–F10, PCP3/TC3 for F15–F17, and PCP0/TC0 for F18–F20. C0 uses strict priority; C3 uses the frozen calibrated CBS profile `reduction_11` on admissible egresses, with the other classes under strict priority. Buffers follow the campaign manifest.

The live status panel reported 411 ledgered results out of 900 admissible C0–C3 positions: 240 C0 and 171 C3. C0 is complete. C3 has 30/30 results in L0/A0, L0/A1, L1/A0, L1/A1, and L2/A0; L2/A1 has 21/30 ledgered, with seed 1022 running at 73.3% and eight more seeds not yet complete. C3/L3 is inadmissible under the campaign's reservation screen and was not simulated. C1/C2 results are on the other machine and are not included in this local ledger snapshot. The campaign-wide summary has not yet been generated.

The dashboard percentage is execution coverage, not a pass rate. A completed, technically processed run can fail application or stability gates. The current runner was active on `C3_L2_A1_seed1022`; its outcome is intentionally not included below.

## C0: completed baseline

| Cell | Completed | Runs passing all recorded viability gates | Overflow drops after warm-up through drain | Result |
|---|---:|---:|---:|---|
| L0/A0, L0/A1 | 30 each | 30 each | 0 | Pass |
| L1/A0, L1/A1 | 30 each | 30 each | 0 | Pass |
| L2/A0, L2/A1 | 30 each | 30 each | 0 | Pass |
| L3/A0 | 30 | 30 | 0 | Pass |
| L3/A1 | 30 | 0 | 579,892 | Fail: camera packet/image delivery |

Overall, 210/240 runs passed all recorded gates. All 30 L3/A1 runs failed because F02 and F05 failed their hard camera gates. The loss counters reconcile to the overflow counter at `ZonalIVN.CSW.eth[0]`, TC4: F02 lost 219,747 of 6,750,000 offered packets (3.26%); F05 lost 360,145 of 6,750,000 (5.34%). Across the 30 runs, 579,892 overflow drops occurred in the `[1,31)` measurement window, with no additional drain drops in that cell. The whole-run TrafficAudit count is 602,392; its additional 22,500 events are warm-up events (750 per run) and must not be presented as measurement losses.

Camera image completion makes the effect clearer: F02 had 219,565 misses among 225,000 offered images (97.58%), and F05 had 186,094/225,000 (82.71%). Completed images did not exceed their image deadlines; the gate failures came from incomplete images after packet loss. The camera talker source queues recorded zero drops. No queue was classified as persistently growing in C0. Thus C0 passes through L3/A0, but the full C0 matrix is not entirely viable.

The old scalar `mean_percent`/`max_percent` values for link utilization are not valid time-weighted utilization for `[1,31)`. The retained data lack timestamped busy intervals, so the audited measurement-window utilization is unavailable; do not use those values to explain the C0 outcome. See the [C0 utilization audit](results/audit/c0_link_utilization_audit_20261008.md).

## C3: partial calibrated-CBS campaign

`reduction_11` was accepted and frozen after passing the calibration checks at L2/A1, seeds 41, 43, and 47. For the official campaign, its frozen candidate-to-nominal ratios are applied to each load, subject to the per-port 75% admissibility screen; the official lower-load profiles are therefore not the same absolute reservations as the L2 calibration profile. The C3 result record is labeled `campaign_treatment=C3`; its internal INI configuration is named `Validate_C2_*` because C3 adds the calibrated profile to the C2 CBS mechanism.

| Cell | Completed | Passing all recorded gates | Observed outcome so far |
|---|---:|---:|---|
| L0/A0 | 30/30 | 0/30 | Overflow in every run; failures include cameras/sensors, F13, and F21/F22. TC4 overflow is concentrated at Z1/Z2 uplinks. |
| L0/A1 | 30/30 | 0/30 | Overflow and non-stable queues in a subset; the same flow groups fail in every run. |
| L1/A0 | 30/30 | 0/30 | Overflow in every run; F02/F03, F06/F07, and F21/F22 fail in every run. |
| L1/A1 | 30/30 | 0/30 | Overflow in every run, including Z1/Z2 uplinks and CSW→Z3 TC4; F13 also fails in every run. |
| L2/A0 | 30/30 | 30/30 | All completed runs pass. |
| L2/A1 | 21/30 ledgered; seed 1022 active | 20/21 completed runs | Seed 1021 fails stability only: sustained growth in Z3.ZSW.eth[7]/TC4, without overflow; the other 20 completed runs pass. |

In L0, F02/F03, F04/F05, F06/F07, F13, and F21/F22 are among the failing flows across both alignments. In L1, F02/F03, F06/F07, and F21/F22 fail across both alignments; F13 additionally fails in L1/A1. These are observed run-level gate outcomes, not a causal proof that CBS alone produced each failure. The queue counters localize important loss points: for example, L0/A0 overflow is concentrated at Z1/Z2 `eth[0]` TC4; L1/A1 additionally has substantial CSW `eth[3]` TC4 overflow.

The L2/A1 seed 1021 stability failure is specifically `ZonalIVN.Z3.ZSW.eth[7].macLayer.queue.queue[4]` (TC4): its capacity is 262,144 bits, peak occupancy 57,344 bits, and the six 5 s means rise from about 3.45 kbit to 55.86 kbit. It has no overflow and the application gates pass in that run, but the sustained-growth proxy fails. This is why “no drops” alone does not establish stability.

These official results show that passing the three calibration seeds at L2/A1 did not guarantee viability after the calibrated ratios were applied at lower loads, and even the partial L2/A1 official cell has one stability failure so far. Wait for the remaining L2/A1 runs and the complete campaign analysis before estimating robustness or drawing final conclusions about the P1 hypotheses.

## Interpretation and limits

- C0 is a usable completed baseline, but its L3/A1 camera loss means it is not an all-cells-pass baseline.
- C3 is still partial. Its L0/L1 failures and the seed-1021 L2/A1 stability failure are valid unfavorable outcomes; they must remain in the final analysis.
- The calibration's success at L2/A1 and the official campaign's scaled lower-load failures are different pieces of evidence. They do not justify silently retuning the official profile.
- C0/C3 contrasts should be made only on matched cell/seed records and with the same metric definitions. C1/C2 and the other machine's ledger still need verified merge before campaign-level comparisons.
- Link utilization is unavailable as a measurement-window time-weighted quantity in the current retained C0 data. Queue occupancy, overflow, packet/image populations, and latency samples remain separately reported in the ledger.
- Neither these interim results nor completion percentages confirm or reject the research hypotheses. C4 has not started in the official campaign and is not covered here.

## Reproducibility and source files

- Campaign definition, cell matrix, mapping, and buffer rules: [`campaign_manifest.json`](campaign_manifest.json)
- Per-run ledger and exact flow/queue metrics: [`results/runs.jsonl`](results/runs.jsonl)
- Live progress/checkpoint: [`results/progress.json`](results/progress.json), [`results/checkpoint.json`](results/checkpoint.json), and [`campaign_status.py`](campaign_status.py)
- C3 calibration and frozen-profile verification: [`results/calibration/C3_calibration.json`](results/calibration/C3_calibration.json)
- C0 utilization limitation and correction: [`results/audit/c0_link_utilization_audit_20261008.md`](results/audit/c0_link_utilization_audit_20261008.md)
- Effective flow mapping: [`flow_mapping.csv`](flow_mapping.csv)

The counts and current-run state above are a snapshot, not a self-updating report. Refresh them from the ledger and status panel after C3 advances; do not edit the ledger or checkpoint manually.
