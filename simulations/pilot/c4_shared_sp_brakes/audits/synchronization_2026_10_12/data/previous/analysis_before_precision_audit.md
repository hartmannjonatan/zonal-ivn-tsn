# C4 shared-SP-brakes pilot

Exploratory pilot only. `exploratory=true`; `official_c4_frozen=false`. This report does not change the P1, frozen C3 profile, or official C0–C3 results.

Status: **16/16** scheduled executions complete; 0 pending; 4 technical attempts. No C4 final campaign is authorized by this pilot.

The fixed CBS source is official profile **reduction_11** (SHA-256 `b669e3f54725f8c68dc10e9ba54a3c99694e7cb0514dbe21d1e5a38c50d47c22`). Compensation is fixed at `idleSlope_C3 / 0.77` only on CBS queues whose egress receives TAS. No C3 retuning is performed.

## Historical pilot correction

The previous C4 pilot remains preserved under `../c4_service_preservation/`. Its `effective_gcl` settings were rechecked from retained SCA after normalizing time units. Configuration fidelity and application-route coverage are separate: historical GCL used `Z3.ZSW.eth[4]`, while F10 exits at `Z3.ZSW.eth[5]`. Historical link utilization and full-measurement clock offsets are unavailable where their source series were not retained. See the corrected historical `analysis.md` and `audit-corrections.json`.

## F08–F10 route and egress table

| Flow | Receiver | Actual egress route and speed | `C4_shared_SPbrakes` service |
|---|---|---|---|
| F08 (TC7) | BRAKE1 | HPC.eth[0] (1000 Mb/s) → CSW.eth[1] (1000 Mb/s) → Z1.ZSW.eth[4] (100 Mb/s) | TAS on HPC/CSW; final brake output SP permanently open |
| F09 (TC7) | BRAKE2 | HPC.eth[0] (1000 Mb/s) → CSW.eth[2] (1000 Mb/s) → Z2.ZSW.eth[4] (100 Mb/s) | TAS on HPC/CSW; final brake output SP permanently open |
| F10 (TC7) | BRAKE3 | HPC.eth[0] (1000 Mb/s) → CSW.eth[3] (1000 Mb/s) → Z3.ZSW.eth[5] (100 Mb/s) | TAS on HPC/CSW; final brake output SP permanently open |

The application catalog confirms each last-hop brake egress carries only its own brake flow: Z1 `eth[4]`→F08, Z2 `eth[4]`→F09, Z3 `eth[5]`→F10. gPTP control traffic is tracked separately. All treatments use `StreamingTransmitter`/`DestreamingReceiver`; applications remain scheduled by OMNeT++ simulation time while TAS uses synchronized local clocks.

Per-packet timestamps for F08–F10 at all three hops are unavailable with the current shared `TrafficAudit` output, which aggregates counts and bytes by flow/interface/queue. The runner records this limitation explicitly; it will not claim packet-level gate-wait or hop-by-hop causality from aggregate vectors.

## Preflight screens

All eight L/A combinations are screened. CBS reservations are not clipped. L3 cells that exceed the 75% per-port ceiling are rejected before execution.

| Variant | Cell | Admissible | Reservation rejection ports | Other screen failures |
|---|---|---:|---|---|
| C3_base | L0_A0 | True | — | — |
| C3_base | L0_A1 | True | — | — |
| C3_base | L1_A0 | True | — | — |
| C3_base | L1_A1 | True | — | — |
| C3_base | L2_A0 | True | — | — |
| C3_base | L2_A1 | True | — | — |
| C3_base | L3_A0 | False | CSW.eth[0], Z1.ZSW.eth[0] | — |
| C3_base | L3_A1 | False | CSW.eth[0], Z1.ZSW.eth[0] | — |
| C3_sync | L0_A0 | True | — | — |
| C3_sync | L0_A1 | True | — | — |
| C3_sync | L1_A0 | True | — | — |
| C3_sync | L1_A1 | True | — | — |
| C3_sync | L2_A0 | True | — | — |
| C3_sync | L2_A1 | True | — | — |
| C3_sync | L3_A0 | False | CSW.eth[0], Z1.ZSW.eth[0] | — |
| C3_sync | L3_A1 | False | CSW.eth[0], Z1.ZSW.eth[0] | — |
| C4_compensated_fullpath_corrected | L0_A0 | True | — | — |
| C4_compensated_fullpath_corrected | L0_A1 | True | — | — |
| C4_compensated_fullpath_corrected | L1_A0 | True | — | — |
| C4_compensated_fullpath_corrected | L1_A1 | True | — | — |
| C4_compensated_fullpath_corrected | L2_A0 | True | — | — |
| C4_compensated_fullpath_corrected | L2_A1 | True | — | — |
| C4_compensated_fullpath_corrected | L3_A0 | False | CSW.eth[0], Z1.ZSW.eth[0] | — |
| C4_compensated_fullpath_corrected | L3_A1 | False | CSW.eth[0], Z1.ZSW.eth[0] | — |
| C4_shared_SPbrakes | L0_A0 | True | — | — |
| C4_shared_SPbrakes | L0_A1 | True | — | — |
| C4_shared_SPbrakes | L1_A0 | True | — | — |
| C4_shared_SPbrakes | L1_A1 | True | — | — |
| C4_shared_SPbrakes | L2_A0 | True | — | — |
| C4_shared_SPbrakes | L2_A1 | True | — | — |
| C4_shared_SPbrakes | L3_A0 | False | CSW.eth[0], Z1.ZSW.eth[0] | — |
| C4_shared_SPbrakes | L3_A1 | False | CSW.eth[0], Z1.ZSW.eth[0] | — |

### Effective reservation totals for the shared-SP L2/A1 profile

These are the configured sums of TC4/TC6 idleSlope on each physical egress for `C4_shared_SPbrakes`, derived by preflight from the effective profile; the manifest contains the same breakdown for all treatments and loads. No clipping was applied. The configured total is below 75% on every listed port.

| Egress | TC4+TC6 idleSlope (Mb/s) | Physical rate (Mb/s) | Port fraction | Headroom to 75% (Mb/s) |
|---|---:|---:|---:|---:|
| CAM1.eth[0] | 56.850 | 1000.000 | 5.685% | 693.150 |
| CAM2.eth[0] | 56.850 | 1000.000 | 5.685% | 693.150 |
| CAM3.eth[0] | 56.850 | 1000.000 | 5.685% | 693.150 |
| CAM4.eth[0] | 56.850 | 1000.000 | 5.685% | 693.150 |
| CSW.eth[0] | 539.160 | 1000.000 | 53.916% | 210.840 |
| CSW.eth[1] | 115.948 | 1000.000 | 11.595% | 634.052 |
| CSW.eth[2] | 115.948 | 1000.000 | 11.595% | 634.052 |
| CSW.eth[3] | 321.558 | 1000.000 | 32.156% | 428.442 |
| HPC.eth[0] | 187.636 | 1000.000 | 18.764% | 562.364 |
| LiDAR1.eth[0] | 308.400 | 1000.000 | 30.840% | 441.600 |
| RADAR1.eth[0] | 1.680 | 100.000 | 1.680% | 73.320 |
| RADAR2.eth[0] | 1.680 | 100.000 | 1.680% | 73.320 |
| Z1.ZSW.eth[0] | 545.250 | 1000.000 | 54.525% | 204.750 |
| Z1.ZSW.eth[6] | 27.600 | 100.000 | 27.600% | 47.400 |
| Z1.ZSW.eth[7] | 61.680 | 100.000 | 61.680% | 13.320 |
| Z2.ZSW.eth[0] | 218.530 | 1000.000 | 21.853% | 531.470 |
| Z2.ZSW.eth[6] | 27.600 | 100.000 | 27.600% | 47.400 |
| Z2.ZSW.eth[7] | 61.680 | 100.000 | 61.680% | 13.320 |
| Z3.ZSW.eth[0] | 115.380 | 1000.000 | 11.538% | 634.620 |
| Z3.ZSW.eth[7] | 27.600 | 100.000 | 27.600% | 47.400 |

## Executions and paired comparisons

| Variant | Cell | Seed | Status | Admissible | Simulation valid | Application gates | Queue stability | Sync (audited) | TAS/GCL | Calendar |
|---|---|---:|---|---:|---|---|---|---|---|---|
| C3_base | L2_A1 | 41 | completed | True | True | True | True | None | None / not_applicable | paired |
| C3_sync | L2_A1 | 41 | completed | True | True | True | True | Inconclusive (sampled pass) | None / not_applicable | paired |
| C4_shared_SPbrakes | L2_A1 | 41 | completed | True | True | True | False | Inconclusive (sampled pass) | True / pass | paired |
| C4_compensated_fullpath_corrected | L2_A1 | 41 | completed | True | True | False | False | Inconclusive (sampled pass) | True / pass | paired |
| C3_base | L2_A1 | 43 | completed | True | True | True | True | None | None / not_applicable | paired |
| C3_sync | L2_A1 | 43 | completed | True | True | True | True | Fail (10 µs probe) | None / not_applicable | paired |
| C4_shared_SPbrakes | L2_A1 | 43 | completed | True | True | True | False | Fail (10 µs probe) | True / pass | paired |
| C3_base | L2_A1 | 47 | completed | True | True | True | True | None | None / not_applicable | paired |
| C3_sync | L2_A1 | 47 | completed | True | True | True | True | Inconclusive (sampled pass) | None / not_applicable | paired |
| C4_shared_SPbrakes | L2_A1 | 47 | completed | True | True | True | False | Inconclusive (sampled pass) | True / pass | paired |
| C3_base | L0_A0 | 41 | completed | True | True | False | True | None | None / not_applicable | paired |
| C3_sync | L0_A0 | 41 | completed | True | True | False | True | Inconclusive (sampled pass) | None / not_applicable | paired |
| C4_shared_SPbrakes | L0_A0 | 41 | completed | True | True | False | False | Inconclusive (sampled pass) | True / pass | paired |
| C3_base | L1_A1 | 41 | completed | True | True | False | False | None | None / not_applicable | paired |
| C3_sync | L1_A1 | 41 | completed | True | True | False | False | Inconclusive (sampled pass) | None / not_applicable | paired |
| C4_shared_SPbrakes | L1_A1 | 41 | completed | True | True | False | False | Inconclusive (sampled pass) | True / pass | paired |

The registered contrasts are `C3_sync − C3_base`, `C4_shared_SPbrakes − C3_sync`, `C4_shared_SPbrakes − C3_base`, and the seed-41-only `C4_shared_SPbrakes − C4_compensated_fullpath_corrected`. Full per-flow/receptor deltas are in `pilot_results.json`; a missing pair is not treated as a zero difference.

| Contrast | Cell | Seed | Calendar paired | LHS all gates | RHS all gates |
|---|---|---:|---|---|---|
| C3_sync - C3_base | L2_A1 | 41 | True | False | True |
| C3_sync - C3_base | L2_A1 | 43 | True | False | True |
| C3_sync - C3_base | L2_A1 | 47 | True | False | True |
| C3_sync - C3_base | L0_A0 | 41 | True | False | False |
| C3_sync - C3_base | L1_A1 | 41 | True | False | False |
| C4_shared_SPbrakes - C3_sync | L2_A1 | 41 | True | False | False |
| C4_shared_SPbrakes - C3_sync | L2_A1 | 43 | True | False | False |
| C4_shared_SPbrakes - C3_sync | L2_A1 | 47 | True | False | False |
| C4_shared_SPbrakes - C3_sync | L0_A0 | 41 | True | False | False |
| C4_shared_SPbrakes - C3_sync | L1_A1 | 41 | True | False | False |
| C4_shared_SPbrakes - C3_base | L2_A1 | 41 | True | False | True |
| C4_shared_SPbrakes - C3_base | L2_A1 | 43 | True | False | True |
| C4_shared_SPbrakes - C3_base | L2_A1 | 47 | True | False | True |
| C4_shared_SPbrakes - C3_base | L0_A0 | 41 | True | False | False |
| C4_shared_SPbrakes - C3_base | L1_A1 | 41 | True | False | False |
| C4_shared_SPbrakes - C4_compensated_fullpath_corrected | L2_A1 | 41 | True | False | False |

## Queue and per-flow evidence

The JSON retains packet and image populations, losses, pendings, deadline misses, latency tails, goodput, drops by scope, and queue metrics per execution. Camera deadline gates use image completion, including incomplete images as misses. A brake-only pass is not C4 viability.

| Execution | HPC.eth[0]/TC4 capacity | Six 5 s means (KiB) | Peak (KiB) | Time ≥90% capacity | Sustained growth |
|---|---:|---|---:|---:|---|
| C3base_L2_A1_seed41 | 32.00 | 0.68, 0.68, 0.68, 0.68, 0.68, 0.68 | 2.24 | 0.000% | False |
| C3sync_L2_A1_seed41 | 32.00 | 0.68, 0.68, 0.68, 0.68, 0.68, 0.68 | 2.24 | 0.000% | False |
| C4compensated_L2_A1_seed41 | 32.00 | 4.41, 9.11, 13.15, 17.39, 21.90, 27.08 | 31.38 | 2.457% | True |
| C4original_L2_A1_seed41 | 32.00 | 4.41, 9.11, 13.15, 17.39, 21.90, 27.08 | 31.38 | 2.457% | True |
| C3base_L2_A1_seed43 | 32.00 | 0.68, 0.68, 0.68, 0.68, 0.68, 0.68 | 2.24 | 0.000% | False |
| C3sync_L2_A1_seed43 | 32.00 | 0.68, 0.68, 0.68, 0.68, 0.68, 0.68 | 2.24 | 0.000% | False |
| C4compensated_L2_A1_seed43 | 32.00 | 4.22, 8.57, 13.68, 19.11, 24.07, 28.91 | 31.86 | 8.485% | True |
| C3base_L2_A1_seed47 | 32.00 | 0.68, 0.68, 0.68, 0.68, 0.68, 0.68 | 2.24 | 0.000% | False |
| C3sync_L2_A1_seed47 | 32.00 | 0.68, 0.68, 0.68, 0.68, 0.68, 0.68 | 2.24 | 0.000% | False |
| C4compensated_L2_A1_seed47 | 32.00 | 4.21, 8.51, 13.27, 17.74, 22.74, 27.10 | 30.88 | 1.265% | True |
| C3base_L0_A0_seed41 | 32.00 | 0.50, 0.50, 0.50, 0.50, 0.50, 0.50 | 2.24 | 0.000% | False |
| C3sync_L0_A0_seed41 | 32.00 | 0.50, 0.50, 0.50, 0.50, 0.50, 0.50 | 2.24 | 0.000% | False |
| C4compensated_L0_A0_seed41 | 32.00 | 1.30, 2.42, 3.54, 4.65, 5.77, 6.88 | 7.95 | 0.000% | True |
| C3base_L1_A1_seed41 | 32.00 | 0.57, 0.57, 0.57, 0.57, 0.57, 0.57 | 2.24 | 0.000% | False |
| C3sync_L1_A1_seed41 | 32.00 | 0.57, 0.57, 0.57, 0.57, 0.57, 0.57 | 2.24 | 0.000% | False |
| C4compensated_L1_A1_seed41 | 32.00 | 1.54, 2.88, 4.22, 5.56, 6.91, 8.25 | 9.45 | 0.000% | True |

For new runs, link utilization is accepted only if the binary transmitting-state series is ordered and its sample-hold integral lies in [0,1]; invalid series become unavailable. Clock offsets are measured throughout [1,31) s at 1 ms resolution; the report also states the piecewise-linear duration estimate and cannot rule out unsampled excursions. GCL checks verify resolved duration, 100 µs period, phase/offset, clock module, absolute-time schedule, guard band, and gate-state fractions separately.

## Interpretation status

Finding: SP on the three final brake egresses recovered F08–F10 application deadlines. All application gates passed in the three paired L2/A1 seeds (True); queue stability passed across all three (False) and total pilot viability passed across all three (False). The complete treatment therefore did not pass: sustained TC4 queue growth/overflow and the 1 µs clock-offset criterion remain failures. This rejects adopting the tested C4 configuration as-is, but does not rule out every C4 design.

## Final paired results

The comparison uses the same F21/F22 event calendar within each seed. The last-hop comparison is available only for seed 41.

| Treatment / seed | Flow | Received / offered | Packet deadline misses | Loss | p99 (µs) | Max (µs) |
|---|---|---:|---:|---:|---:|---:|
| C3_base / 41 | F08 | 300000 / 300000 | 0 | 0.0000% | 28.332 | 31.474 |
| C3_base / 41 | F09 | 300000 / 300000 | 0 | 0.0000% | 27.612 | 31.132 |
| C3_base / 41 | F10 | 300000 / 300000 | 0 | 0.0000% | 28.332 | 31.308 |
| C3_sync / 41 | F08 | 300000 / 300000 | 0 | 0.0000% | 28.332 | 31.474 |
| C3_sync / 41 | F09 | 300000 / 300000 | 0 | 0.0000% | 27.612 | 31.132 |
| C3_sync / 41 | F10 | 300000 / 300000 | 0 | 0.0000% | 28.332 | 31.308 |
| C4_shared_SPbrakes / 41 | F08 | 300000 / 300000 | 0 | 0.0000% | 97.270 | 97.786 |
| C4_shared_SPbrakes / 41 | F09 | 300000 / 300000 | 0 | 0.0000% | 97.270 | 97.814 |
| C4_shared_SPbrakes / 41 | F10 | 300000 / 300000 | 0 | 0.0000% | 97.269 | 97.785 |
| C4_compensated_fullpath_corrected / 41 | F08 | 300000 / 300000 | 300000 | 0.0000% | 941.941 | 949.127 |
| C4_compensated_fullpath_corrected / 41 | F09 | 300000 / 300000 | 300000 | 0.0000% | 939.909 | 947.100 |
| C4_compensated_fullpath_corrected / 41 | F10 | 300000 / 300000 | 300000 | 0.0000% | 1037.917 | 1045.116 |
| C3_base / 43 | F08 | 300000 / 300000 | 0 | 0.0000% | 28.332 | 31.474 |
| C3_base / 43 | F09 | 300000 / 300000 | 0 | 0.0000% | 27.612 | 31.132 |
| C3_base / 43 | F10 | 300000 / 300000 | 0 | 0.0000% | 28.332 | 31.456 |
| C3_sync / 43 | F08 | 300000 / 300000 | 0 | 0.0000% | 28.332 | 31.474 |
| C3_sync / 43 | F09 | 300000 / 300000 | 0 | 0.0000% | 27.612 | 31.132 |
| C3_sync / 43 | F10 | 300000 / 300000 | 0 | 0.0000% | 28.332 | 31.456 |
| C4_shared_SPbrakes / 43 | F08 | 300000 / 300000 | 0 | 0.0000% | 97.293 | 97.793 |
| C4_shared_SPbrakes / 43 | F09 | 300000 / 300000 | 0 | 0.0000% | 97.294 | 97.793 |
| C4_shared_SPbrakes / 43 | F10 | 300000 / 300000 | 0 | 0.0000% | 97.295 | 97.793 |
| C3_base / 47 | F08 | 300000 / 300000 | 0 | 0.0000% | 28.332 | 31.474 |
| C3_base / 47 | F09 | 300000 / 300000 | 0 | 0.0000% | 27.612 | 31.132 |
| C3_base / 47 | F10 | 300000 / 300000 | 0 | 0.0000% | 28.332 | 31.697 |
| C3_sync / 47 | F08 | 300000 / 300000 | 0 | 0.0000% | 28.332 | 31.474 |
| C3_sync / 47 | F09 | 300000 / 300000 | 0 | 0.0000% | 27.612 | 31.132 |
| C3_sync / 47 | F10 | 300000 / 300000 | 0 | 0.0000% | 28.332 | 31.697 |
| C4_shared_SPbrakes / 47 | F08 | 300000 / 300000 | 0 | 0.0000% | 97.282 | 97.786 |
| C4_shared_SPbrakes / 47 | F09 | 300000 / 300000 | 0 | 0.0000% | 97.285 | 97.786 |
| C4_shared_SPbrakes / 47 | F10 | 300000 / 300000 | 0 | 0.0000% | 97.284 | 97.785 |

| Treatment / seed | Application gates | Queue stability | Sync ≤1 µs | TAS/GCL | Total pilot viability | Overflow drops* |
|---|---|---|---|---|---|---:|
| C3_base / 41 | True | True | None | None / not_applicable | True | 0 |
| C3_sync / 41 | True | True | False | None / not_applicable | False | 0 |
| C4_shared_SPbrakes / 41 | True | False | False | True / pass | False | 48 |
| C4_compensated_fullpath_corrected / 41 | False | False | False | True / pass | False | 48 |
| C3_base / 43 | True | True | None | None / not_applicable | True | 0 |
| C3_sync / 43 | True | True | False | None / not_applicable | False | 0 |
| C4_shared_SPbrakes / 43 | True | False | False | True / pass | False | 168 |
| C3_base / 47 | True | True | None | None / not_applicable | True | 0 |
| C3_sync / 47 | True | True | False | None / not_applicable | False | 0 |
| C4_shared_SPbrakes / 47 | True | False | False | True / pass | False | 125 |

### Camera packet and image results are separate

The packet table reports packet latency and packet losses; the image table reports image completion from availability through the last frame. An incomplete image is counted as a missed image deadline, not as an extra packet loss. `N/A` means the applicable sample population is empty or the metric does not apply.

| Execution | Flow | Offered / received packets | Packet drops | Packet deadline misses | Packet p99 / max (ms) |
|---|---|---:|---:|---:|---:|
| C3base_L0_A0_seed41 | F02 | 28110 / 23263 | 4847 | 19261 | 51.198574 / 53.369739 |
| C3base_L0_A0_seed41 | F03 | 28140 / 23639 | 4501 | 19489 | 51.236399 / 55.503072 |
| C3base_L0_A0_seed41 | F04 | 28140 / 28140 | 0 | 4035 | 36.872263 / 37.103072 |
| C3base_L0_A0_seed41 | F05 | 28110 / 28110 | 0 | 3997 | 36.872263 / 37.103072 |
| C3sync_L0_A0_seed41 | F02 | 28110 / 23263 | 4847 | 19261 | 51.198574 / 53.369739 |
| C3sync_L0_A0_seed41 | F03 | 28140 / 23639 | 4501 | 19489 | 51.236399 / 55.503072 |
| C3sync_L0_A0_seed41 | F04 | 28140 / 28140 | 0 | 4035 | 36.872263 / 37.103072 |
| C3sync_L0_A0_seed41 | F05 | 28110 / 28110 | 0 | 3997 | 36.872263 / 37.103072 |
| C4compensated_L0_A0_seed41 | F02 | 28110 / 23263 | 4847 | 19261 | 51.198574 / 53.369739 |
| C4compensated_L0_A0_seed41 | F03 | 28140 / 23639 | 4501 | 19489 | 51.236399 / 55.503072 |
| C4compensated_L0_A0_seed41 | F04 | 28140 / 28140 | 0 | 4035 | 36.872263 / 37.103072 |
| C4compensated_L0_A0_seed41 | F05 | 28110 / 28110 | 0 | 3997 | 36.872263 / 37.103072 |
| C3base_L1_A1_seed41 | F02 | 56250 / 50278 | 5972 | 31350 | 25.606247 / 28.969752 |
| C3base_L1_A1_seed41 | F03 | 56250 / 50078 | 6172 | 31216 | 26.485200 / 29.636424 |
| C3base_L1_A1_seed41 | F04 | 56250 / 56250 | 0 | 0 | 20.763667 / 21.499323 |
| C3base_L1_A1_seed41 | F05 | 56250 / 56250 | 0 | 0 | 20.887058 / 21.632657 |
| C3sync_L1_A1_seed41 | F02 | 56250 / 50278 | 5972 | 31350 | 25.606247 / 28.969752 |
| C3sync_L1_A1_seed41 | F03 | 56250 / 50078 | 6172 | 31216 | 26.485200 / 29.636424 |
| C3sync_L1_A1_seed41 | F04 | 56250 / 56250 | 0 | 0 | 20.763667 / 21.499323 |
| C3sync_L1_A1_seed41 | F05 | 56250 / 56250 | 0 | 0 | 20.887058 / 21.632657 |
| C4compensated_L1_A1_seed41 | F02 | 56250 / 50278 | 5972 | 31350 | 25.606247 / 28.969752 |
| C4compensated_L1_A1_seed41 | F03 | 56250 / 50078 | 6172 | 31216 | 26.485200 / 29.636424 |
| C4compensated_L1_A1_seed41 | F04 | 56250 / 56250 | 0 | 0 | 20.763667 / 21.499323 |
| C4compensated_L1_A1_seed41 | F05 | 56250 / 56250 | 0 | 0 | 20.887058 / 21.632657 |
| C4compensated_L2_A1_seed41 | F02 | 140610 / 140610 | 0 | 0 | 6.223607 / 6.341499 |
| C4compensated_L2_A1_seed41 | F03 | 140610 / 140610 | 0 | 0 | 6.276467 / 6.329823 |
| C4compensated_L2_A1_seed41 | F04 | 140610 / 140610 | 0 | 0 | 6.329788 / 6.329824 |
| C4compensated_L2_A1_seed41 | F05 | 140610 / 140610 | 0 | 0 | 6.383129 / 6.383157 |
| C4original_L2_A1_seed41 | F02 | 140610 / 140610 | 0 | 0 | 6.223607 / 6.341499 |
| C4original_L2_A1_seed41 | F03 | 140610 / 140610 | 0 | 0 | 6.276467 / 6.329823 |
| C4original_L2_A1_seed41 | F04 | 140610 / 140610 | 0 | 0 | 6.329788 / 6.329824 |
| C4original_L2_A1_seed41 | F05 | 140610 / 140610 | 0 | 0 | 6.383129 / 6.383157 |
| C4compensated_L2_A1_seed43 | F02 | 140610 / 140610 | 0 | 0 | 6.223611 / 6.341664 |
| C4compensated_L2_A1_seed43 | F03 | 140610 / 140610 | 0 | 0 | 6.276466 / 6.341664 |
| C4compensated_L2_A1_seed43 | F04 | 140610 / 140610 | 0 | 0 | 6.329789 / 6.341664 |
| C4compensated_L2_A1_seed43 | F05 | 140610 / 140610 | 0 | 0 | 6.383129 / 6.383157 |
| C4compensated_L2_A1_seed47 | F02 | 140610 / 140610 | 0 | 0 | 6.223610 / 6.342071 |
| C4compensated_L2_A1_seed47 | F03 | 140610 / 140610 | 0 | 0 | 6.276467 / 6.342071 |
| C4compensated_L2_A1_seed47 | F04 | 140610 / 140610 | 0 | 0 | 6.329794 / 6.342071 |
| C4compensated_L2_A1_seed47 | F05 | 140610 / 140610 | 0 | 0 | 6.383129 / 6.383157 |

| Execution | Flow | Offered / complete images | Incomplete images | Image deadline misses / offered | Image p99 / max (ms) |
|---|---|---:|---:|---:|---:|
| C3base_L0_A0_seed41 | F02 | 937 / 696 | 241 | 937 / 937 | 46.685901 / 53.369733 |
| C3base_L0_A0_seed41 | F03 | 938 / 717 | 221 | 938 / 938 | 48.569736 / 54.020282 |
| C3base_L0_A0_seed41 | F04 | 938 / 938 | 0 | 938 / 938 | 37.103072 / 37.103072 |
| C3base_L0_A0_seed41 | F05 | 937 / 937 | 0 | 937 / 937 | 37.103072 / 37.103072 |
| C3sync_L0_A0_seed41 | F02 | 937 / 696 | 241 | 937 / 937 | 46.685901 / 53.369733 |
| C3sync_L0_A0_seed41 | F03 | 938 / 717 | 221 | 938 / 938 | 48.569736 / 54.020282 |
| C3sync_L0_A0_seed41 | F04 | 938 / 938 | 0 | 938 / 938 | 37.103072 / 37.103072 |
| C3sync_L0_A0_seed41 | F05 | 937 / 937 | 0 | 937 / 937 | 37.103072 / 37.103072 |
| C4compensated_L0_A0_seed41 | F02 | 937 / 696 | 241 | 937 / 937 | 46.685901 / 53.369733 |
| C4compensated_L0_A0_seed41 | F03 | 938 / 717 | 221 | 938 / 938 | 48.569736 / 54.020282 |
| C4compensated_L0_A0_seed41 | F04 | 938 / 938 | 0 | 938 / 938 | 37.103072 / 37.103072 |
| C4compensated_L0_A0_seed41 | F05 | 937 / 937 | 0 | 937 / 937 | 37.103072 / 37.103072 |
| C3base_L1_A1_seed41 | F02 | 1875 / 1466 | 409 | 1875 / 1875 | 24.969754 / 27.151868 |
| C3base_L1_A1_seed41 | F03 | 1875 / 1484 | 391 | 1875 / 1875 | 25.236401 / 27.899321 |
| C3base_L1_A1_seed41 | F04 | 1875 / 1875 | 0 | 0 / 1875 | 21.499322 / 21.499323 |
| C3base_L1_A1_seed41 | F05 | 1875 / 1875 | 0 | 0 / 1875 | 21.632656 / 21.632657 |
| C3sync_L1_A1_seed41 | F02 | 1875 / 1466 | 409 | 1875 / 1875 | 24.969754 / 27.151868 |
| C3sync_L1_A1_seed41 | F03 | 1875 / 1484 | 391 | 1875 / 1875 | 25.236401 / 27.899321 |
| C3sync_L1_A1_seed41 | F04 | 1875 / 1875 | 0 | 0 / 1875 | 21.499322 / 21.499323 |
| C3sync_L1_A1_seed41 | F05 | 1875 / 1875 | 0 | 0 / 1875 | 21.632656 / 21.632657 |
| C4compensated_L1_A1_seed41 | F02 | 1875 / 1466 | 409 | 1875 / 1875 | 24.969754 / 27.151868 |
| C4compensated_L1_A1_seed41 | F03 | 1875 / 1484 | 391 | 1875 / 1875 | 25.236401 / 27.899321 |
| C4compensated_L1_A1_seed41 | F04 | 1875 / 1875 | 0 | 0 / 1875 | 21.499322 / 21.499323 |
| C4compensated_L1_A1_seed41 | F05 | 1875 / 1875 | 0 | 0 / 1875 | 21.632656 / 21.632657 |
| C4compensated_L2_A1_seed41 | F02 | 4687 / 4687 | 0 | 0 / 4687 | 6.329810 / 6.341499 |
| C4compensated_L2_A1_seed41 | F03 | 4687 / 4687 | 0 | 0 / 4687 | 6.329816 / 6.329823 |
| C4compensated_L2_A1_seed41 | F04 | 4687 / 4687 | 0 | 0 / 4687 | 6.329822 / 6.329824 |
| C4compensated_L2_A1_seed41 | F05 | 4687 / 4687 | 0 | 0 / 4687 | 6.383156 / 6.383157 |
| C4original_L2_A1_seed41 | F02 | 4687 / 4687 | 0 | 0 / 4687 | 6.329810 / 6.341499 |
| C4original_L2_A1_seed41 | F03 | 4687 / 4687 | 0 | 0 / 4687 | 6.329816 / 6.329823 |
| C4original_L2_A1_seed41 | F04 | 4687 / 4687 | 0 | 0 / 4687 | 6.329822 / 6.329824 |
| C4original_L2_A1_seed41 | F05 | 4687 / 4687 | 0 | 0 / 4687 | 6.383156 / 6.383157 |
| C4compensated_L2_A1_seed43 | F02 | 4687 / 4687 | 0 | 0 / 4687 | 6.329814 / 6.341664 |
| C4compensated_L2_A1_seed43 | F03 | 4687 / 4687 | 0 | 0 / 4687 | 6.329817 / 6.341664 |
| C4compensated_L2_A1_seed43 | F04 | 4687 / 4687 | 0 | 0 / 4687 | 6.329823 / 6.341664 |
| C4compensated_L2_A1_seed43 | F05 | 4687 / 4687 | 0 | 0 / 4687 | 6.383157 / 6.383157 |
| C4compensated_L2_A1_seed47 | F02 | 4687 / 4687 | 0 | 0 / 4687 | 6.329820 / 6.342071 |
| C4compensated_L2_A1_seed47 | F03 | 4687 / 4687 | 0 | 0 / 4687 | 6.341499 / 6.342071 |
| C4compensated_L2_A1_seed47 | F04 | 4687 / 4687 | 0 | 0 / 4687 | 6.342069 / 6.342071 |
| C4compensated_L2_A1_seed47 | F05 | 4687 / 4687 | 0 | 0 / 4687 | 6.383157 / 6.383157 |

*Overflow count scope is after warm-up through the 50 ms drain; the JSON also separates measurement-window and drain counts.

C4_shared_SPbrakes passed every application gate at L2/A1 in seeds 41, 43, and 47, including the brake flows, cameras, and deadline-sensitive sensors. F08–F10 had zero losses and zero deadline misses out of 300,000 packets per flow in each seed; maxima were close to the 100 µs limit. By contrast, in the seed-41 full-path diagnostic, each brake flow missed the deadline on all 300,000 packets. The paired results are consistent with the final-hop gate schedule causing the latency increase, but the retained instrumentation lacks packet timestamps at each hop, so exact per-packet gate-wait causality is unavailable.

In C4_shared_SPbrakes L2/A1, HPC.eth[0]/TC4 grew in all three seeds and produced 48, 168, and 125 post-warm-up overflow drops respectively. Seed 43 also had sustained growth at Z3.ZSW.eth[7]/TC4. Thus the brake improvement did not establish a viable C4: queue stability failed, while synchronization is not approved after the export correction and direct-probe audit.

The L0/A0 and L1/A1 C3 controls already fail high-hard camera/sensor application gates; the C4 treatment does not recover them. Treat these cells as evidence of pre-existing control limitations, not a newly introduced C4-only failure.

### Paired brake-flow effects at L2/A1

The table reports treatment-minus-control deltas for F08–F10. Calendars are paired within each seed. Positive latency deltas mean higher latency; application miss deltas use packet misses, while camera-image gates are reported separately in the per-flow JSON.

| Contrast / seed | Flow | Δ p99 (µs) | Δ max (µs) | Δ packet deadline misses | Treatment pilot viability | Control pilot viability |
|---|---|---:|---:|---:|---|---|
| C3_sync − C3_base / 41 | F08 | 0.000 | 0.000 | 0 | False | True |
| C3_sync − C3_base / 41 | F09 | 0.000 | 0.000 | 0 | False | True |
| C3_sync − C3_base / 41 | F10 | 0.000 | 0.000 | 0 | False | True |
| C3_sync − C3_base / 43 | F08 | 0.000 | 0.000 | 0 | False | True |
| C3_sync − C3_base / 43 | F09 | 0.000 | 0.000 | 0 | False | True |
| C3_sync − C3_base / 43 | F10 | 0.000 | 0.000 | 0 | False | True |
| C3_sync − C3_base / 47 | F08 | 0.000 | 0.000 | 0 | False | True |
| C3_sync − C3_base / 47 | F09 | 0.000 | 0.000 | 0 | False | True |
| C3_sync − C3_base / 47 | F10 | 0.000 | 0.000 | 0 | False | True |
| C4_shared_SPbrakes − C3_sync / 41 | F08 | 68.938 | 66.312 | 0 | False | False |
| C4_shared_SPbrakes − C3_sync / 41 | F09 | 69.658 | 66.682 | 0 | False | False |
| C4_shared_SPbrakes − C3_sync / 41 | F10 | 68.937 | 66.476 | 0 | False | False |
| C4_shared_SPbrakes − C3_sync / 43 | F08 | 68.961 | 66.319 | 0 | False | False |
| C4_shared_SPbrakes − C3_sync / 43 | F09 | 69.682 | 66.661 | 0 | False | False |
| C4_shared_SPbrakes − C3_sync / 43 | F10 | 68.963 | 66.337 | 0 | False | False |
| C4_shared_SPbrakes − C3_sync / 47 | F08 | 68.950 | 66.312 | 0 | False | False |
| C4_shared_SPbrakes − C3_sync / 47 | F09 | 69.673 | 66.654 | 0 | False | False |
| C4_shared_SPbrakes − C3_sync / 47 | F10 | 68.952 | 66.088 | 0 | False | False |
| C4_shared_SPbrakes − C3_base / 41 | F08 | 68.938 | 66.312 | 0 | False | True |
| C4_shared_SPbrakes − C3_base / 41 | F09 | 69.658 | 66.682 | 0 | False | True |
| C4_shared_SPbrakes − C3_base / 41 | F10 | 68.937 | 66.476 | 0 | False | True |
| C4_shared_SPbrakes − C3_base / 43 | F08 | 68.961 | 66.319 | 0 | False | True |
| C4_shared_SPbrakes − C3_base / 43 | F09 | 69.682 | 66.661 | 0 | False | True |
| C4_shared_SPbrakes − C3_base / 43 | F10 | 68.963 | 66.337 | 0 | False | True |
| C4_shared_SPbrakes − C3_base / 47 | F08 | 68.950 | 66.312 | 0 | False | True |
| C4_shared_SPbrakes − C3_base / 47 | F09 | 69.673 | 66.654 | 0 | False | True |
| C4_shared_SPbrakes − C3_base / 47 | F10 | 68.952 | 66.088 | 0 | False | True |
| C4_shared_SPbrakes − C4_compensated_fullpath_corrected / 41 | F08 | -844.671 | -851.341 | -300000 | False | False |
| C4_shared_SPbrakes − C4_compensated_fullpath_corrected / 41 | F09 | -842.640 | -849.286 | -300000 | False | False |
| C4_shared_SPbrakes − C4_compensated_fullpath_corrected / 41 | F10 | -940.648 | -947.332 | -300000 | False | False |

The shared-SP treatment reduced F08–F10 p99 by roughly 0.84–0.94 ms versus the seed-41 full-path diagnostic, while all three brake flows moved from 300,000 deadline misses to zero. This is a paired treatment difference, not packet-level proof that the final gate alone caused each packet's delay; hop timestamps were not retained.

### Overflow locations and CBS credit evidence

Overflow counters below are queue-level and do not identify the dropped flow; per-flow receive/loss metrics cannot be assigned to a specific egress drop without packet-level drop tracing. The whole-run TrafficAudit count, SCA count, and post-warm-up measurement-plus-drain count reconcile for these executions; drain drops were zero.

| Execution | Queue / TC | Capacity (KiB) | Measurement overflow drops | Drain drops | Whole-run / post-warm-up total |
|---|---|---:|---:|---:|---:|
| C3base_L0_A0_seed41 | Z1.ZSW.eth[0].macLayer.queue.queue[4] / TC4 | 128.00 | 36778 | 0 | 36778 |
| C3base_L0_A0_seed41 | Z2.ZSW.eth[0].macLayer.queue.queue[4] / TC4 | 128.00 | 35595 | 0 | 35595 |
| C3base_L1_A1_seed41 | CSW.eth[3].macLayer.queue.queue[4] / TC4 | 128.00 | 25389 | 0 | 25389 |
| C3base_L1_A1_seed41 | Z1.ZSW.eth[0].macLayer.queue.queue[4] / TC4 | 128.00 | 15673 | 0 | 15673 |
| C3base_L1_A1_seed41 | Z2.ZSW.eth[0].macLayer.queue.queue[4] / TC4 | 128.00 | 18398 | 0 | 18398 |
| C3sync_L0_A0_seed41 | Z1.ZSW.eth[0].macLayer.queue.queue[4] / TC4 | 128.00 | 36778 | 0 | 36778 |
| C3sync_L0_A0_seed41 | Z2.ZSW.eth[0].macLayer.queue.queue[4] / TC4 | 128.00 | 35595 | 0 | 35595 |
| C3sync_L1_A1_seed41 | CSW.eth[3].macLayer.queue.queue[4] / TC4 | 128.00 | 25389 | 0 | 25389 |
| C3sync_L1_A1_seed41 | Z1.ZSW.eth[0].macLayer.queue.queue[4] / TC4 | 128.00 | 15673 | 0 | 15673 |
| C3sync_L1_A1_seed41 | Z2.ZSW.eth[0].macLayer.queue.queue[4] / TC4 | 128.00 | 18398 | 0 | 18398 |
| C4compensated_L0_A0_seed41 | CSW.eth[3].macLayer.queue.queue[4] / TC4 | 128.00 | 49 | 0 | 49 |
| C4compensated_L0_A0_seed41 | Z1.ZSW.eth[0].macLayer.queue.queue[4] / TC4 | 128.00 | 36778 | 0 | 36778 |
| C4compensated_L0_A0_seed41 | Z2.ZSW.eth[0].macLayer.queue.queue[4] / TC4 | 128.00 | 35595 | 0 | 35595 |
| C4compensated_L1_A1_seed41 | CSW.eth[3].macLayer.queue.queue[4] / TC4 | 128.00 | 25855 | 0 | 25855 |
| C4compensated_L1_A1_seed41 | Z1.ZSW.eth[0].macLayer.queue.queue[4] / TC4 | 128.00 | 15673 | 0 | 15673 |
| C4compensated_L1_A1_seed41 | Z2.ZSW.eth[0].macLayer.queue.queue[4] / TC4 | 128.00 | 18398 | 0 | 18398 |
| C4compensated_L2_A1_seed41 | CSW.eth[3].macLayer.queue.queue[4] / TC4 | 128.00 | 48 | 0 | 48 |
| C4compensated_L2_A1_seed43 | HPC.eth[0].macLayer.queue.queue[4] / TC4 | 32.00 | 168 | 0 | 168 |
| C4compensated_L2_A1_seed47 | CSW.eth[3].macLayer.queue.queue[4] / TC4 | 128.00 | 125 | 0 | 125 |
| C4original_L2_A1_seed41 | CSW.eth[3].macLayer.queue.queue[4] / TC4 | 128.00 | 48 | 0 | 48 |

For the critical L2/A1 `C4_shared_SPbrakes` executions, `HPC.eth[0]/TC4` sustained queue growth in all three seeds (the six 5 s means rise monotonically). Drops were observed at CSW→Z3/TC4 in seeds 41 and 47, and at HPC→CSW/TC4 in seed 43; seed 43 also showed sustained growth at Z3.ZSW.eth[7]/TC4. These are direct queue/drop observations; catalog routing establishes which traffic classes traverse the queues, but not which individual frame was discarded.

| Seed | CBS queue | idleSlope (Mb/s) | Credit min / max / time-average (reported units) |
|---:|---|---:|---:|
| 41 | HPC.eth[0]/TC4 | 187.636 | -10021.317813696001 / 4513.039584018928 / -2929.5187302784807 |
| 41 | CSW.eth[0]/TC4 | 227.400 | -9370.092800000002 / 2676.4452432 / -6915.759216079361 |
| 41 | CSW.eth[3]/TC4 | 321.558 | -8369.255059488003 / 7605.9504520028 / -917.2115197623897 |
| 41 | Z3.ZSW.eth[7]/TC4 | 27.600 | -1598.5920000000003 / 0 / -1059.8759782875322 |
| 43 | HPC.eth[0]/TC4 | 187.636 | -10021.317813696001 / 4515.054986204652 / -2887.2150282884027 |
| 43 | CSW.eth[0]/TC4 | 227.400 | -9370.092800000002 / 2965.501797 / -6911.349760877183 |
| 43 | CSW.eth[3]/TC4 | 321.558 | -8369.255059488001 / 7519.42872201386 / -993.1307361024172 |
| 43 | Z3.ZSW.eth[7]/TC4 | 27.600 | -1598.5920000000003 / 0 / -1059.138287952096 |
| 47 | HPC.eth[0]/TC4 | 187.636 | -10021.317813696001 / 4512.72116510922 / -2905.729059925089 |
| 47 | CSW.eth[0]/TC4 | 227.400 | -9370.092800000002 / 2817.196065 / -6895.032263278204 |
| 47 | CSW.eth[3]/TC4 | 321.558 | -8369.255059488001 / 7784.01183146809 / -1031.1660362301336 |
| 47 | Z3.ZSW.eth[7]/TC4 | 27.600 | -1598.5920000000003 / 0 / -1057.7570352104365 |

The credit statistics above are reported from the installed INET CBS vectors; their units follow the underlying INET signal and are not converted here. `idleSlope/0.77` is a configured reservation compensation, not a measured throughput guarantee. Queue growth and overflow demonstrate that the tested service did not maintain stable occupancy.

## Clock synchronization and gate audit

The synchronization export was audited against the installed INET 4.7 sources and reprocessed from retained vectors. The former millisecond maxima and interpolated violation durations are invalid: equal-simulation-time `SettableClock.timeChanged` values were sorted by clock value, losing setter emission order and treating transition states as ordinary samples. Corrected regular 1 ms samples over `[1,31)` s show no point above 1 µs (maximum 0.06 µs across the retained run/node series), but sampling does not establish continuous compliance. Two direct seed-43 technical probes observed real 10 µs parent-clock excursions in `C3_sync` at Z1, 1.801 s, and in `C4_shared_SPbrakes` at all downstream clocks, 1.247 s. Thus the strict synchronization gate is **not approved**, and its continuous violation duration is unavailable. This also demonstrates the phenomenon without TAS.

The detailed per-run/node old-versus-corrected table, direct probes, vector-emitter audit, gPTP evidence, hashes and preserved evidence are in the [synchronization audit](../audits/synchronization_2026_10_12/audit.md) and [audit JSON](../audits/synchronization_2026_10_12/audit.json). The old report and result JSON are preserved under that audit's `data/previous/` directory. This correction does not change the independent TC4 queue-instability finding.

### Corrected physical-link utilization

Utilization is the sample-hold integral of the binary transmitting-state vector over [1,31) s. Invalid state values are marked unavailable; they are not clipped, absolutized, or replaced with zero. In particular, `CSW.eth[0]` carries traffic but its retained transmitter state contains −1 sentinel samples, so its utilization is unavailable and is excluded from service claims. The prior negative histogram export is not used.

| C4_shared_SPbrakes seed | Egress | Busy fraction | Status |
|---:|---|---:|---|
| 41 | HPC.eth[0] | 31.516% | valid |
| 41 | CSW.eth[0] | N/A | unavailable |
| 41 | CSW.eth[1] | 14.586% | valid |
| 41 | CSW.eth[2] | 14.586% | valid |
| 41 | CSW.eth[3] | 13.186% | valid |
| 41 | Z1.ZSW.eth[4] | 5.760% | valid |
| 41 | Z2.ZSW.eth[4] | 5.760% | valid |
| 41 | Z3.ZSW.eth[5] | 5.760% | valid |
| 43 | HPC.eth[0] | 31.515% | valid |
| 43 | CSW.eth[0] | N/A | unavailable |
| 43 | CSW.eth[1] | 14.586% | valid |
| 43 | CSW.eth[2] | 14.585% | valid |
| 43 | CSW.eth[3] | 13.617% | valid |
| 43 | Z1.ZSW.eth[4] | 5.760% | valid |
| 43 | Z2.ZSW.eth[4] | 5.760% | valid |
| 43 | Z3.ZSW.eth[5] | 5.760% | valid |
| 47 | HPC.eth[0] | 31.516% | valid |
| 47 | CSW.eth[0] | N/A | unavailable |
| 47 | CSW.eth[1] | 14.586% | valid |
| 47 | CSW.eth[2] | 14.586% | valid |
| 47 | CSW.eth[3] | N/A | unavailable |
| 47 | Z1.ZSW.eth[4] | 5.760% | valid |
| 47 | Z2.ZSW.eth[4] | 5.760% | valid |
| 47 | Z3.ZSW.eth[5] | 5.760% | valid |

The selected valid egress values are corroborative physical-state measurements, not CBS service guarantees. A separate independent wire-summary check was unavailable because retained wire summary data were missing; results do not substitute the invalid `CSW.eth[0]` series with a derived estimate.


All scheduled GCLs passed the effective-configuration and measured gate-state checks. The 24 always-open brake SP gates in C4_shared_SPbrakes were verified from effective SCA parameters, because a permanently open gate has no transition vector. The full-path diagnostic schedules TAS on all seven egresses and has corresponding gate-state evidence. A valid GCL does not imply synchronized clocks or end-to-end viability.

## Decision findings for this exploratory pilot

- **Did SP on the real final brake egresses recover F08–F10?** Yes, for the tested L2/A1 seeds 41, 43, and 47: all 300,000 packets per flow were received with zero loss and zero packet deadline misses. The largest shared-SP brake latency was 97.814 µs against a 100 µs deadline, leaving only 2.186 µs of observed margin.
- **Did the complete treatment pass all applications and queue stability?** No. Application gates passed for all L2/A1 shared-SP runs, but the treatment failed stability in each seed; the strict gPTP ≤1 µs criterion is not approved (a 10 µs excursion was directly observed in seed 43, while seeds 41 and 47 have sampled-pass but continuous-time-inconclusive evidence). At L0/A0 and L1/A1, the existing C3 control already failed application gates, so this pilot did not recover the complete workload there.
- **Did HPC/TC4 keep growing?** Yes. Its six 5 s means increased in every shared-SP L2/A1 seed; overflow was 48, 168, and 125 packets for seeds 41, 43, and 47. Seed 43 also showed sustained growth at Z3.ZSW.eth[7]/TC4.
- **Was synchronization adequate throughout measurement?** Not approved. The old millisecond maxima and short interpolated durations came from same-time correction-emission order in the exporter. Corrected 1 ms samples are below 1 µs but cannot prove a continuous pass; direct 2 s seed-43 probes found 10 µs excursions both in C3_sync without TAS and in C4_shared_SPbrakes. See the linked synchronization audit for per-node values and limitations.
- **Does this justify an official C4 change?** It supports investigating a prospective C4 design that keeps brake-facing egresses under SP, but it does not validate C4. The shared-SP variant still needs investigation of CBS queue growth/overflow and gPTP synchronization; the full-path diagnostic shows why the final brake gates are problematic under this workload.
- **What would a later official evaluation need?** Update the prospective P1 only after review to specify the real route-derived brake egresses and SP exception, retain `C3_sync` as a paired control, and require the full application, synchronization, GCL, and queue-stability gates. This pilot does not revise the P1 or confirm H1–H5.

## Nonstable queues

| Execution | Queue / TC | Capacity (KiB) | Mean (KiB) | Peak (KiB) | Time ≥90% | Six 5 s means (KiB) |
|---|---|---:|---:|---:|---:|---|
| C4compensated_L2_A1_seed41 | HPC.eth[0].macLayer.queue.queue[4] / TC4 | 32.00 | 15.51 | 31.38 | 2.457% | 4.41, 9.11, 13.15, 17.39, 21.90, 27.08 |
| C4original_L2_A1_seed41 | HPC.eth[0].macLayer.queue.queue[4] / TC4 | 32.00 | 15.51 | 31.38 | 2.457% | 4.41, 9.11, 13.15, 17.39, 21.90, 27.08 |
| C4compensated_L2_A1_seed43 | HPC.eth[0].macLayer.queue.queue[4] / TC4 | 32.00 | 16.43 | 31.86 | 8.485% | 4.22, 8.57, 13.68, 19.11, 24.07, 28.91 |
| C4compensated_L2_A1_seed43 | Z3.ZSW.eth[7].macLayer.queue.queue[4] / TC4 | 32.00 | 2.40 | 8.25 | 0.000% | 0.34, 0.36, 0.31, 3.16, 5.08, 5.17 |
| C4compensated_L2_A1_seed47 | HPC.eth[0].macLayer.queue.queue[4] / TC4 | 32.00 | 15.60 | 30.88 | 1.265% | 4.21, 8.51, 13.27, 17.74, 22.74, 27.10 |
| C4compensated_L0_A0_seed41 | HPC.eth[0].macLayer.queue.queue[4] / TC4 | 32.00 | 4.09 | 7.95 | 0.000% | 1.30, 2.42, 3.54, 4.65, 5.77, 6.88 |
| C3base_L1_A1_seed41 | CSW.eth[0].macLayer.queue.queue[4] / TC4 | 128.00 | 28.63 | 67.20 | 0.000% | 36.44, 37.11, 24.38, 19.68, 25.21, 28.96 |
| C3sync_L1_A1_seed41 | CSW.eth[0].macLayer.queue.queue[4] / TC4 | 128.00 | 28.63 | 67.20 | 0.000% | 36.44, 37.11, 24.38, 19.68, 25.21, 28.96 |
| C4compensated_L1_A1_seed41 | HPC.eth[0].macLayer.queue.queue[4] / TC4 | 32.00 | 4.89 | 9.45 | 0.000% | 1.54, 2.88, 4.22, 5.56, 6.91, 8.25 |
| C4compensated_L1_A1_seed41 | CSW.eth[0].macLayer.queue.queue[4] / TC4 | 128.00 | 28.63 | 67.20 | 0.000% | 36.44, 37.11, 24.38, 19.68, 25.21, 28.96 |

Stability uses the six consecutive 5 s measurement means and the registered sustained-growth criterion. A zero nonstable count means no sustained growth was detected under that criterion; it is not a claim that queues were empty. The full queue traces and metadata remain available for independent recalculation.

## Post-processing corrections

All 16 scheduled executions completed with paired calendars and no pending cells. Four failed technical attempts remain in `technical_attempts.jsonl`; retries that produced an audited result remain one methodological execution each. One attempt row is internally mismatched: it names `C4original_L2_A1_seed41` while its error text refers to a `C3sync_L2_A1_seed41` run. The later final scheduled rows are completed and audited; that historical metadata mismatch is retained rather than silently rewritten. The corrected C4original and C4compensated seed-41 results were reprocessed from retained SCA and compact traces, without re-running those simulations. The application/stability split below also corrects a reporting conflation in which application_viable had copied the validator's combined cell result.

| Correction | Re-simulation |
|---|---|
| Compare effective gate durations/offsets numerically after normalizing units and whitespace. | False |
| Do not require gPTP clock vectors in the C3-base control; validate its preserved physical-link state vectors instead. | False |
| Exclude superseded seed-41 runs from current calendar pairing and contrasts while retaining them in the audit ledger. | False |
| Separate application gate outcome from queue stability; prior application_viable copied the validator's combined cell viability, which conflated application failures with nonstable queues. | False |
| Compute high-hard diagnostic failures from packet latency sample misses as well as reported miss counts, packet loss, image misses, and incomplete images. | False |
| Re-evaluate C4_original's brake egress GCLs as scheduled gates; only C4_shared_SPbrakes has permanently-open SP brake exits. | False |

Run identity: commit 003e44d6cf9387e3332ed6cbfe5812958780e7fb; OMNeT++ omnetpp-6.4.0; INET inet-4.7.0-dfe270b21f (not_a_git_checkout); P1 SHA-256 87809f1b5e22f72e7c58ad2f3a90aab8476e58a80e7417b82f47897af66235f5; frozen CBS source reduction_11.

## Reproduction and recovery

Run `python3 simulations/pilot/c4_shared_sp_brakes/check_readiness.py` before starting. The reviewed plan was generated by `run_pilot.py --plan`; `pilot_status.py` is read-only. The runner allows at most one simulation process on this machine, serializes vector extraction, keeps a 45 GB free-space floor, checkpoints each completed execution, and refuses to run while the official campaign is active. Launch at reduced CPU/I/O priority with `nice -n 15 ionice -c 3`; use `--run --resume` only after reviewing the checkpoint/dashboard.
