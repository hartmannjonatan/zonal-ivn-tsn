# Exploratory C4 study: CBS and TAS

This report consolidates the exploratory development of C4, the final verification of its absolute reservation policy, and the later operational freeze for the official runner. The exploration is closed. **`D3_coordinated_20pct`** is the study-recommended and operationally frozen C4 candidate. The official snapshot is `c4-d3-99e3ff698b48258c` (manifest SHA-256 `99e3ff698b48258c91424992d7d4d7608588201d9c1bb1687f59b5af46fc96c3`). At the 25 October 2026 status check, official C4 remained not started (0/180) and not validated. The exploratory pilot manifests correctly retain `official_c4_frozen=false`; the later official manifest records `official_c4_frozen=true` and `official_c4_validated=false`. This report does not change the P1 PDF, C0–C3, or the registered campaign matrix, and it does not confirm H1–H5.

## Specification and problem

The [final P1](../../docs/design/P1-final.pdf) keeps the original C4 as its starting reference: C3 CBS with TAS on the seven egresses along the brake paths, using a 100 µs cycle, a 10 µs window for TC7, 77 µs for TC0–TC6, and 13 µs closed. The specification also defines an exploratory stage to study the CBS/TAS interaction and propose a suitable configuration. The development details and results below complement the P1; they do not change its starting reference.

In the INET version used here, CBS credit evolves subject to the queue and TAS gate conditions. Guard bands, non-preemptive transmission, and whether a frame fits in the remaining open window further restrict the service actually available. Therefore, copying an `idleSlope` calibrated without TAS does not guarantee the same useful rate after gates are introduced. Dividing `idleSlope` by `0.77` was an approximation based on the nominal TC0–TC6 open fraction, not a service guarantee: it does not fully represent credit, guard bands, phase, serialization, or frame fit. It is also not an allowance for gPTP traffic. gPTP is additional control traffic classified in TC7; the experiments do not establish that its mere presence explains every failure.

These outcomes are distinct: a **deadline miss** is a late delivery; an **overflow** is a packet dropped because a queue is full; **stability** is the operational gate applied to queue evolution after warm-up. A run can pass one and fail another. The credit/gate interaction was already known and motivated this study; the pilots did not discover it.

## Study timeline

| Study | Question and treatments | Scope | Result and limitation |
|---|---|---|---|
| [`c4_service_preservation`](c4_service_preservation/results/analysis.md) | Does the initial TAS setup cover the brake egresses? Audit of routes, GCL, utilization, and synchronization. | Initial pilot; historical evidence. | Corrected the route association: BRAKE3 actually exits through Z3.ZSW.eth[5], while the earlier GCL targeted eth[4]. Exported utilization was invalid and synchronization coverage was insufficient; do not use this as full-path validation. |
| [`c4_shared_sp_brakes`](c4_shared_sp_brakes/results/analysis.md) | SP on the brakes' last hops and TAS on the four shared links; C3_base/C3_sync controls. | L2/A1, seeds 41/43/47, plus a full-path diagnostic in seed 41. | The brakes passed on the partially gated path, but HPC/TC4 overflowed and failed the stability gate; Z3/TC4 also grew. The corrected full-path run had brake misses. The `C3/0.77` rule did not preserve stability. |
| [`c4_gate_clock_reference`](c4_gate_clock_reference/results/audits/audit_2026-10-14/audit.md) | Same A005 profile, workload, and calendar; gates on local clocks, HPC gate on ideal time, or all four gates on ideal time. | L2/A1, seed 41, three diagnostic variants. | Isolated the temporal-reference dependence of the HPC gate: local-clock growth was about 3,300.9 bit/s and was practically zero with the HPC gate on simulation time. Ideal gates changed downstream results and did not demonstrate global stability. The study did not fully separate cadence from phase. |
| [`c4_real_clock_service_margin`](c4_real_clock_service_margin/results/analysis.md) and [`c4_cbs_tas_investigation`](c4_cbs_tas_investigation/README.md) | Audits of CBS, B/C3_sync, local compensation and small reservation increases; R/RP/RPM variants. | Mostly L2/A1, seed 41; conditional expansions were not run. | Corrected B reproduced HPC growth. BM (+2% only at F13/Z3) recovered one natural local episode but did not fix HPC. R/RP/RPM with A005 and about 48% TC4-open time were rejected by the service upper bound before simulation. None of these results proves general CBS+TAS infeasibility. |
| [`c4_real_clock_service_margin_corrected`](c4_real_clock_service_margin_corrected/results/analysis.md) | Correct missing CBS instances, validators, admissibility, and the F13 criterion. | B, C3_sync, and BM; analysis of R/RP/RPM. | Confirmed that the earlier pilot without instantiated CBS was not evidence about CBS. Equal arrivals and departures in windows with empty endpoints follow from conservation and do not prove a lack of headroom. Local recovery after upstream losses does not demonstrate service for the full offered demand. |
| [`c4_joint_dimensioning`](c4_joint_dimensioning/results/analysis.md) | Jointly size GCL and CBS: historical D1–D3. | L2/A1 and limited development. | **Historical D3** had 4 F08 misses and 14 F09 misses, CSW→Z3 overflow, and F13/F21/F22 losses. Do not confuse it with the later candidate. |
| [`c4_feasibility_decision`](c4_feasibility_decision/results/final_analysis_2026-10-20.md) | Evaluate `D3_coordinated_20pct` and profiles scaled by load. | L2/A1, seeds 41/43/47; L0/A0 and L1/A1, seed 41. | The new candidate passed L2; the load-scaled rule failed at L0/A0 and L1/A1. This motivated testing the absolute L2 profile at lower loads. |
| [`c4_fixed_L2_profile`](c4_fixed_L2_profile/results/analysis.md) | Absolute L2 profile versus the load-scaled profile, with and without TAS. | L0/A0 and L1/A1, seed 41. | All four fixed-profile treatments passed in this initial check. This was not multi-seed or full-matrix coverage. |
| [`c4_final_verification`](c4_final_verification/analysis.md) and [`reconciliation 2026-10-22`](c4_final_verification/results/reconciliation_2026-10-22.json) | Final paired verification of the absolute profile with TAS/noTAS. | L0–L2 × A0/A1 × seeds 41/43/47; audited reuses included. | All 36/36 positions are covered: 26 new and 10 reused. Reconciled results pass the recorded gates. The 12 L3 positions were rejected before simulation by service triage. This is the current source for the exploratory decision. |
| Official operational freeze | Hash-pin the selected candidate for later official evaluation. | Static freeze, no simulation. | Snapshot `c4-d3-99e3ff698b48258c`; 180 L0–L2 positions prepared. The freeze does not validate C4. |

The intermediate audits and earlier reports remain in their original directories. Superseded summaries should not be read as the current status when a later reconciliation exists. No simulations were run while preparing this documentation.

## What the clock-reference diagnostic showed

The three A005 variants kept the profile, load, seed, and F21/F22 calendar signature; the authorized functional difference was the gate time reference on the four shared egresses:

| Variant | Gate reference | Cycles in `[1,31)` | Observed HPC/TC4 slope |
|---|---|---:|---:|
| `A005_local` | synchronized local clocks | 299,993 | growth of about 3,300.9 bit/s |
| `A005_ideal_HPC` | simulation time at HPC→CSW only | HPC 300,000; CSW egresses 299,993 | practically zero at HPC/TC4 |
| `A005_ideal_all` | simulation time at all four gates | 300,000 | practically zero at HPC/TC4 |

Applications are scheduled in simulation time; local gates use clocks synchronized to the grandmaster. Relative synchronization among nodes does not ensure that their corrected clock cadence matches the simulation-time calendar used by the applications. Changing only the HPC gate's time reference recovered seven cycles in the measurement window and removed growth at that queue under this condition. The experiment tested dependence on the time reference, including cadence and phase, but did not fully separate the two or resolve downstream stability. Ideal-time gates were **diagnostic controls**, not realistic candidates; the final exploratory design returned to local clocks.

## Corrections that changed the interpretation

- **Route and GCL:** the initial route association applied TAS to Z3.eth[4], while BRAKE3 exits through eth[5]. The audit corrected the port mapping; it did not change the topology to make the port list match.
- **Offsets:** event ordering, rounded timestamps, and invalid interpolation produced false millisecond and −10 µs peaks. Later audits computed differences between simultaneous readings in native ticks before serialization. The old values remain historical and are not confirmed real excursions.
- **CBS:** an intermediate stage wrote `idleSlope` for nonexistent submodules and accepted missing credit data; that run was not a valid CBS control. The corrected executor and validator require an instantiated shaper and effective parameters.
- **Treatment identity and phase:** intermediate runs had divergences between registered and executed phases, including RPM. Corrected reports distinguish the planned treatment, effective configuration, and observed states; incompatible runs were not accepted as valid replacements.
- **Demand and units:** at L2, F13 is 25.60 Mb/s in queue bits (256 bytes × 12,500 frames/s) and 27.60 Mb/s on the wire; 10.24 Mb/s came from using the base period without the L2 factor. The effective CSW→Z3 queue is 128 KiB = 131,072 bytes = 1,048,576 bits; “1 MiB” was a unit-label error, not a buffer change.
- **F13 and accounting:** realized throughput is not available capacity. In a window that starts and ends empty, with no losses, conservation forces departures to equal arrivals; this does not show that there is no headroom. Local recovery after upstream losses also does not prove service for the full offered demand. Reports retain unreconciled residuals as residuals rather than turning them into drops or service.
- **Stability:** the proxy uses 5-second windows/means and the actual capacity of each queue. It can flag an increase after a burst without proving unbounded continuous deficit. The recorded binary gates remain as defined, with physical interpretation stated separately.

Detailed references: [clock and queue audit](c4_gate_clock_reference/results/audits/audit_2026-10-14/audit.md), [clock-precision audit](c4_real_clock_service_margin_corrected/results/analysis.md), [audit of the run without CBS](c4_real_clock_service_margin/results/audits/audit_2026-10-18/audit.md), [reconciled buffer/profile/synchronization answers](c4_final_verification/answers_previous_questions.md), and [final reconciled analysis](c4_final_verification/analysis.md).

## Profile recommended by the exploratory development

The candidate is **`D3_coordinated_20pct`**, not the earlier D3 from `c4_joint_dimensioning`. Its canonical profile SHA-256 is `571e3a10e004005b2994aadc6dc495db730f6e9b8842af2550ebcbb3d6eb33be`; the complete 24-reservation table, with idleSlope, sendSlope, rate, credits, and policy, is in [`frozen_profile_table.csv`](c4_final_verification/frozen_profile_table.csv).

| Element | Exploratory configuration |
|---|---|
| GCL period | 100 µs |
| Open windows | TC7: 30 µs; TC0–TC6: 55 µs; remaining 15 µs closed |
| Coordinated phase | CSW offset: +0.676 µs relative to HPC (TC4 starts at 30.676 µs; TC7 at 0.676 µs) |
| TAS | Four shared links: HPC→CSW and CSW→Z1/Z2/Z3 |
| SP | Brake-only egresses and TC4 egresses used exclusively by transients with no permanent reservation |
| CBS profile | 24 absolute L2 reservations kept unchanged at L0–L2; no load scaling |

The recorded sizing uses `idleSlope ≈ 1.20 × R_design / 0.42664`, where `0.42664=(55−12.336)/100`. The factor 1.20 is a selected design margin; 0.42664 approximates the credit-eligible fraction after transmission margin and is not a formal service lower bound. The CSW→Z3 demand uses the catalog event envelope with F13 and F21/F22 active: 246.671 Mb/s in queue bits and 251.578 Mb/s on the wire. Permanent F13 alone is 25.60 Mb/s in the queue and 27.60 Mb/s on the wire. The formula and envelope are documented in [`dimensioning.json`](c4_feasibility_decision/results/dimensioning.json) and [`final_analysis_2026-10-20.md`](c4_feasibility_decision/results/final_analysis_2026-10-20.md).

The candidate family was selected offline before execution; it was not a sequence of post-result retunes. D1 had the lowest normalized increase score but its TAS run failed an application gate. D2 and D3 passed the required seed-41 gates and natural-service checks. The preregistered tie/selection rule chose the passing profile with the lower sum of normalized idleSlope increases over changed queues: D3 scored 1.051093563 versus D2 at 1.113086179. D3 was then held fixed for the registered seeds 43/47 and subsequent cell checks. This identifies the selected candidate within the bounded family, not a global optimum.

The increases were not uniform: four reservations were resized for upstream service (HPC.eth[0]/TC4 and CSW.eth[1..3]/TC4), Z3.eth[7]/TC4 received a relative +2% for F13, and the full absolute L2 table was then used at lower loads. The 24-entry table below is in Mb/s; the linked CSV remains authoritative at exact integer bit/s and includes sendSlope, physical rate, credit limits, and guard-band parameters.

| Egress | TC | idleSlope (Mb/s) | Egress | TC | idleSlope (Mb/s) |
|---|---:|---:|---|---:|---:|
| CAM1.eth[0] | 4 | 56.850 | CAM2.eth[0] | 4 | 56.850 |
| CAM3.eth[0] | 4 | 56.850 | CAM4.eth[0] | 4 | 56.850 |
| HPC.eth[0] | 4 | 406.375399 | CSW.eth[0] | 4 | 227.400 |
| CSW.eth[0] | 6 | 311.760 | CSW.eth[1] | 4 | 251.115695 |
| CSW.eth[2] | 4 | 251.115695 | CSW.eth[3] | 4 | 707.606774 |
| LiDAR1.eth[0] | 6 | 308.400 | RADAR1.eth[0] | 6 | 1.680 |
| RADAR2.eth[0] | 6 | 1.680 | Z1.ZSW.eth[0] | 4 | 236.850 |
| Z1.ZSW.eth[0] | 6 | 308.400 | Z1.ZSW.eth[6] | 4 | 27.600 |
| Z1.ZSW.eth[7] | 4 | 61.680 | Z2.ZSW.eth[0] | 4 | 216.850 |
| Z2.ZSW.eth[0] | 6 | 1.680 | Z2.ZSW.eth[6] | 4 | 27.600 |
| Z2.ZSW.eth[7] | 4 | 61.680 | Z3.ZSW.eth[0] | 4 | 113.700 |
| Z3.ZSW.eth[0] | 6 | 1.680 | Z3.ZSW.eth[7] | 4 | 28.152 |

For every row, `sendSlope = idleSlope − physical bitrate`; initial credit and transmit-credit limit are 0 b; min/max credit are −∞/+∞; `maxInterferenceSize=∞ b`; `accumulateCreditInGuardBand=false`; `extraLength=64 b`; and `extraDuration=0 s`. CBS is explicitly instantiated as `Ieee8021qCreditBasedShaper` only for these 24 positive-reservation port/TC pairs. The TC4 egresses that carry only F21/F22 and have no permanent reservation (`Z1.ZCPU.eth[0]`, `Z2.ZCPU.eth[0]`, `Z3.ZSW.eth[1]`) remain SP; no `idleSlope=0` shaper is instantiated. Other non-CBS classes remain under strict priority.

Per-port reservation totals are below 75%. For example, CSW.eth[3] has 707.607 Mb/s configured (70.76% of its 1 Gb/s physical rate; 42.393 Mb/s headroom to 75%). This is configured reservation, not measured utilization or bandwidth consumed. Summing reservations across hops is not consumption on one link. The complete frozen table and effective profile are in [`frozen_profile_table.csv`](../c4_official/frozen_profile_table.csv), [`frozen_d3_l2_profile.json`](../c4_official/frozen_d3_l2_profile.json), and [`C4_D3_absolute_profile.ini`](../c4_official/C4_D3_absolute_profile.ini). Profile SHA-256: `571e3a10e004005b2994aadc6dc495db730f6e9b8842af2550ebcbb3d6eb33be`; CSV SHA-256: `cdaa1186f60f48983eabae06787346fc581584032ac79dfc2e51b74f43be460c`.

## Operational freeze compared with the P1 starting reference

| Feature | P1 C4 starting/reference design | Frozen operational candidate |
|---|---|---|
| CBS | C3 CBS profile | Fixed absolute 24-row `D3_coordinated_20pct` profile |
| TAS locations | Seven egresses along the brake paths | Four shared egresses only: HPC.eth[0] and CSW.eth[1..3] |
| TC0–TC6 | 77 µs open, 13 µs closed | 55 µs open, 45 µs closed |
| TC7 | 10 µs open | 30 µs open, 70 µs closed |
| Period | 100 µs | 100 µs |
| Brake final egresses | TAS in the reference design | SP, permanently open, at Z1.ZSW.eth[4], Z2.ZSW.eth[4], and Z3.ZSW.eth[5] |
| Clock reference | P1 reference setup | Synchronized local node clocks at the four TAS egresses; applications remain scheduled in simulation time |
| Reservation scaling | Reference profile | Absolute L2 rates at L0–L2; never scaled by load |

The schedules use absolute-time scheduling, start open, and enable implicit guard bands. HPC TC7 starts at phase 0 µs and TC0–TC6 at 30 µs. On CSW.eth[1..3], TC7 starts at 0.676 µs and TC0–TC6 at 30.676 µs. The INET offset parameters are 99.324 µs for TC7 and 69.324 µs for TC0–TC6, modulo 100 µs; these parameter values are not themselves the start phases. The CSW shift of 0.676 µs is the selected phase coordination. It does not use an ideal simulation-time clock.

The real-clock model retains HPC as grandmaster, the registered HPC→CSW→zone-switch hierarchy, 125 ms synchronization interval, 1 s peer-delay interval, and 10 ns nominal ticks. Per-node constant drifts are fixed per seed using the registered SHA-256-derived stream, independent of traffic RNG consumption. The final exploratory matrix retained 30,000 periodic samples per node/run and a maximum absolute sampled offset of 60 ns. Sampled synchronization passed; continuous clock conformance remains **not verified**.

The later operational freeze is recorded in [`c4_official/manifest.json`](../campaigns/p1-v2-official-2026-10/c4_official/manifest.json), snapshot `c4-d3-99e3ff698b48258c` (snapshot SHA-256 `99e3ff698b48258c91424992d7d4d7608588201d9c1bb1687f59b5af46fc96c3`, base commit `62664fb9f9e751dfd9813c4ca49eec494b8990a0`). It sets `official_c4_frozen=true`, `official_c4_validated=false`, `campaign_started=false`. The operational addendum is [`C4_operational_freeze_addendum.md`](../c4_official/C4_operational_freeze_addendum.md); it does not edit the P1 PDF.

The prepared official C4 matrix contains one treatment and 180 positions: L0–L2 × A0/A1 × seeds 1001–1030, 1 s warm-up, `[1,31)` measurement and 50 ms drain. It uses the existing official F21/F22 calendar for each cell/seed. L3 is excluded because permanent demand at CSW.eth[0] is 862.656 Mb/s while the fixed profile has only 539.160 Mb/s combined TC4+TC6 idleSlope there. That optimistic service upper bound is already below permanent offered demand. This is not a 75% cap violation.

The official runner stores C4 in a separate results/checkpoint tree, validates the resolved CBS modules, gates, clocks, buffers and calendar before accepting results, and resumes only matching verified runs. It runs as a single job and does not add `C4_open`. C4−C3 compares complete policies, including CBS reservation and synchronization differences; it is not an isolated TAS contrast. Exploratory noTAS results are attribution controls only. First-run runtime confirmation is still required for resolved SCA values, observed gate and guard-band states, calendar population/signature, native-tick clock samples, and application/stability gates. A frozen profile is prepared for evaluation; it is not already validated.

## Final reconciled result

| Item | Current status |
|---|---|
| L0–L2 | 36/36 positions covered: 26 new runs and 10 audited reused results |
| Treatments | Fixed D3 with TAS and with gates open, paired by cell/seed |
| Applications and stability | Passed all 36 positions under the recorded gates |
| Overflow/pending | Zero post-warm-up queue-overflow drops and zero reported packets pending in all 36 positions |
| Synchronization | Sampled criterion passed; 30,000 periodic samples per node/run, aggregate maximum 60 ns; continuous conformance not verified |
| L3 | 12/12 positions rejected before simulation: optimistic CBS service upper bound at CSW.eth[0] is below permanent demand for the fixed profile |
| Technical attempts | Two interrupted attempts preserved as non-results and replaced; they are not methodological positions |
| Runner | The stop check was not applied to reused positions before conditional expansion. The later audit found no actual failure, but the process deviation remains recorded |

L3 was rejected because demand exceeded the estimated service bound for the fixed profile, **not** because the configured reservations exceeded the 75% cap. The matrix, ledger, and per-run calculations are in [analysis.md](c4_final_verification/analysis.md), [pilot_results.json](c4_final_verification/pilot_results.json), [matrix.csv](c4_final_verification/matrix.csv), and [reconciliation_2026-10-22.json](c4_final_verification/results/reconciliation_2026-10-22.json).

Across 18 paired TAS/noTAS comparisons with identical reservations, both treatments passed the gates. TAS increased brake maximum latency by a per-flow median of about 46–47 µs and p99 by about 47–52 µs; this is exploratory evidence and does not demonstrate a compensating TAS benefit. The worst F08–F10 maximum in TAS was 78.108645 µs, leaving 21.891355 µs to the 100 µs deadline. noTAS is an attribution control, not a mandatory official treatment. C4/C3 comparisons also change reservation policy and synchronization, so they do not isolate TAS.

## Conclusion and next step

The study found an empirically viable CBS+TAS configuration in the tested domain: L0–L2, alignments A0/A1, and seeds 41/43/47. The absolute profile also passed with gates open. In paired comparisons with identical reservations, both treatments passed; TAS increased latency, especially on the brake paths, without demonstrating a compensating benefit. This does not establish universal superiority, does not resolve L3, does not prove continuous clock conformance, and does not confirm H1–H5. It does not prove that other CBS+TAS configurations are impossible.

The decision is to **close the exploration and retain `D3_coordinated_20pct` as the operationally frozen candidate for C4**. Its versioned addendum states how it differs from the P1 starting reference, its admissible domain, effective parameters, acceptance criteria, and limits of comparison with C3. This freeze is in the official runner's manifest; it does not edit the P1 PDF and does not certify results. As last recorded, the official C4 campaign had not started and C4 remained unvalidated. C0–C3 remain in their existing campaign state; no `C4_open` treatment is added.

## Reports and source data

- [Final consolidated report](c4_final_verification/analysis.md) and [reconciled JSON](c4_final_verification/pilot_results.json).
- [Protocol and frozen contract](c4_final_verification/protocol.md), [manifest](c4_final_verification/manifest.json), [full table](c4_final_verification/frozen_profile_table.csv), and [checkpoint](c4_final_verification/results/checkpoint.json).
- [Audited prior questions](c4_final_verification/answers_previous_questions.md) and [2026-10-22 reconciliation](c4_final_verification/results/reconciliation_2026-10-22.json).
- [Feasibility and sizing study](c4_feasibility_decision/results/final_analysis_2026-10-20.md).
- [Prospective C4-only revision proposal](c4_final_verification/proposed_P1_C4_revision.md), which was not applied.
- [Operational C4 freeze addendum](../c4_official/C4_operational_freeze_addendum.md), [official manifest](../campaigns/p1-v2-official-2026-10/c4_official/manifest.json), and [implemented C4 profile INI](../c4_official/C4_D3_absolute_profile.ini).
- [Official C4 runner operation guide](../campaigns/p1-v2-official-2026-10/c4_official/README.md).

Raw files remain in their source pilot directories and are not duplicated here. This consolidated conclusion uses `c4_final_verification` as the current source while retaining historical analyses to trace corrections and changes in interpretation.
