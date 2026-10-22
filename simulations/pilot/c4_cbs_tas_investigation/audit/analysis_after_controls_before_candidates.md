# C4 shared-SP-brakes pilot

Exploratory pilot only. `exploratory=true`; `official_c4_frozen=false`. This report does not change the P1, frozen C3 profile, or official C0–C3 results.

Status: **2/2** scheduled executions complete; 0 pending; 4 technical attempts. No C4 final campaign is authorized by this pilot.

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

| Variant | Cell | Seed | Status | Admissible | Simulation valid | Application gates | Queue stability | Sync | TAS/GCL | Calendar |
|---|---|---:|---|---:|---|---|---|---|---|---|
| C3_sync | L2_A1 | 41 | completed | True | True | True | True | None | None / not_applicable | paired |
| C4_shared_SPbrakes | L2_A1 | 41 | completed | True | True | True | False | False | True / pass | paired |

The registered contrasts are `C3_sync − C3_base`, `C4_shared_SPbrakes − C3_sync`, `C4_shared_SPbrakes − C3_base`, and the seed-41-only `C4_shared_SPbrakes − C4_compensated_fullpath_corrected`. Full per-flow/receptor deltas are in `pilot_results.json`; a missing pair is not treated as a zero difference.

| Contrast | Cell | Seed | Calendar paired | LHS all gates | RHS all gates |
|---|---|---:|---|---|---|
| C4_shared_SPbrakes - C3_sync | L2_A1 | 41 | True | False | True |

## Queue and per-flow evidence

The JSON retains packet and image populations, losses, pendings, deadline misses, latency tails, goodput, drops by scope, and queue metrics per execution. Camera deadline gates use image completion, including incomplete images as misses. A brake-only pass is not C4 viability.

| Execution | HPC.eth[0]/TC4 capacity | Six 5 s means (KiB) | Peak (KiB) | Time ≥90% capacity | Sustained growth |
|---|---:|---|---:|---:|---|
| C3_sync_L2_A1_seed41_service_events_v3 | 32.00 | 0.68, 0.68, 0.68, 0.68, 0.68, 0.68 | 2.24 | 0.000% | False |
| C4_reference_L2_A1_seed41_service_events_v2 | 32.00 | 4.41, 9.11, 13.15, 17.39, 21.90, 27.08 | 31.38 | 2.457% | True |

For new runs, link utilization is accepted only if the binary transmitting-state series is ordered and its sample-hold integral lies in [0,1]; invalid series become unavailable. Clock offsets are measured throughout [1,31) s at 1 ms resolution; the report also states the piecewise-linear duration estimate and cannot rule out unsampled excursions. GCL checks verify resolved duration, 100 µs period, phase/offset, clock module, absolute-time schedule, guard band, and gate-state fractions separately.

## Interpretation status

Finding: SP on the three final brake egresses recovered F08–F10 application deadlines. All application gates passed in the three paired L2/A1 seeds (None); queue stability passed across all three (None) and total pilot viability passed across all three (None). The complete treatment therefore did not pass: sustained TC4 queue growth/overflow and the 1 µs clock-offset criterion remain failures. This rejects adopting the tested C4 configuration as-is, but does not rule out every C4 design.

## Final paired results

The comparison uses the same F21/F22 event calendar within each seed. The last-hop comparison is available only for seed 41.

| Treatment / seed | Flow | Received / offered | Packet deadline misses | Loss | p99 (µs) | Max (µs) |
|---|---|---:|---:|---:|---:|---:|
| C3_sync / 41 | F08 | 300000 / 300000 | 0 | 0.0000% | 28.332 | 31.474 |
| C3_sync / 41 | F09 | 300000 / 300000 | 0 | 0.0000% | 27.612 | 31.132 |
| C3_sync / 41 | F10 | 300000 / 300000 | 0 | 0.0000% | 28.332 | 31.308 |
| C4_shared_SPbrakes / 41 | F08 | 300000 / 300000 | 0 | 0.0000% | 97.270 | 97.786 |
| C4_shared_SPbrakes / 41 | F09 | 300000 / 300000 | 0 | 0.0000% | 97.270 | 97.814 |
| C4_shared_SPbrakes / 41 | F10 | 300000 / 300000 | 0 | 0.0000% | 97.269 | 97.785 |

| Treatment / seed | Application gates | Queue stability | Sync ≤1 µs | TAS/GCL | Total pilot viability | Overflow drops* |
|---|---|---|---|---|---|---:|
| C3_sync / 41 | True | True | None | None / not_applicable | True | 0 |
| C4_shared_SPbrakes / 41 | True | False | False | True / pass | False | 48 |

### Camera packet and image results are separate

The packet table reports packet latency and packet losses; the image table reports image completion from availability through the last frame. An incomplete image is counted as a missed image deadline, not as an extra packet loss. `N/A` means the applicable sample population is empty or the metric does not apply.

| Execution | Flow | Offered / received packets | Packet drops | Packet deadline misses | Packet p99 / max (ms) |
|---|---|---:|---:|---:|---:|

| Execution | Flow | Offered / complete images | Incomplete images | Image deadline misses / offered | Image p99 / max (ms) |
|---|---|---:|---:|---:|---:|

*Overflow count scope is after warm-up through the 50 ms drain; the JSON also separates measurement-window and drain counts.

C4_shared_SPbrakes passed every application gate at L2/A1 in seeds 41, 43, and 47, including the brake flows, cameras, and deadline-sensitive sensors. F08–F10 had zero losses and zero deadline misses out of 300,000 packets per flow in each seed; maxima were close to the 100 µs limit. By contrast, in the seed-41 full-path diagnostic, each brake flow missed the deadline on all 300,000 packets. The paired results are consistent with the final-hop gate schedule causing the latency increase, but the retained instrumentation lacks packet timestamps at each hop, so exact per-packet gate-wait causality is unavailable.

In C4_shared_SPbrakes L2/A1, HPC.eth[0]/TC4 grew in all three seeds and produced 48, 168, and 125 post-warm-up overflow drops respectively. Seed 43 also had sustained growth at Z3.ZSW.eth[7]/TC4. Thus the brake improvement did not establish a viable C4: the queues were not stable and synchronization failed.

The L0/A0 and L1/A1 C3 controls already fail high-hard camera/sensor application gates; the C4 treatment does not recover them. Treat these cells as evidence of pre-existing control limitations, not a newly introduced C4-only failure.

### Paired brake-flow effects at L2/A1

The table reports treatment-minus-control deltas for F08–F10. Calendars are paired within each seed. Positive latency deltas mean higher latency; application miss deltas use packet misses, while camera-image gates are reported separately in the per-flow JSON.

| Contrast / seed | Flow | Δ p99 (µs) | Δ max (µs) | Δ packet deadline misses | Treatment pilot viability | Control pilot viability |
|---|---|---:|---:|---:|---|---|
| C4_shared_SPbrakes − C3_sync / 41 | F08 | 68.938 | 66.312 | 0 | False | True |
| C4_shared_SPbrakes − C3_sync / 41 | F09 | 69.658 | 66.682 | 0 | False | True |
| C4_shared_SPbrakes − C3_sync / 41 | F10 | 68.937 | 66.476 | 0 | False | True |

The shared-SP treatment reduced F08–F10 p99 by roughly 0.84–0.94 ms versus the seed-41 full-path diagnostic, while all three brake flows moved from 300,000 deadline misses to zero. This is a paired treatment difference, not packet-level proof that the final gate alone caused each packet's delay; hop timestamps were not retained.

### Overflow locations and CBS credit evidence

Overflow counters below are queue-level and do not identify the dropped flow; per-flow receive/loss metrics cannot be assigned to a specific egress drop without packet-level drop tracing. The whole-run TrafficAudit count, SCA count, and post-warm-up measurement-plus-drain count reconcile for these executions; drain drops were zero.

| Execution | Queue / TC | Capacity (KiB) | Measurement overflow drops | Drain drops | Whole-run / post-warm-up total |
|---|---|---:|---:|---:|---:|
| C4_reference_L2_A1_seed41_service_events_v2 | CSW.eth[3].macLayer.queue.queue[4] / TC4 | 128.00 | 48 | 0 | 48 |

For the critical L2/A1 `C4_shared_SPbrakes` executions, `HPC.eth[0]/TC4` sustained queue growth in all three seeds (the six 5 s means rise monotonically). Drops were observed at CSW→Z3/TC4 in seeds 41 and 47, and at HPC→CSW/TC4 in seed 43; seed 43 also showed sustained growth at Z3.ZSW.eth[7]/TC4. These are direct queue/drop observations; catalog routing establishes which traffic classes traverse the queues, but not which individual frame was discarded.

| Seed | CBS queue | idleSlope (Mb/s) | Credit min / max / time-average (reported units) |
|---:|---|---:|---:|
| 41 | HPC.eth[0]/TC4 | 187.636 | -10021.317813696001 / 4513.039584018928 / -2929.5187302784807 |
| 41 | CSW.eth[0]/TC4 | 227.400 | -9370.092800000002 / 2676.4452432 / -6915.759216079361 |
| 41 | CSW.eth[3]/TC4 | 321.558 | -8369.255059488003 / 7605.9504520028 / -917.2115197623897 |
| 41 | Z3.ZSW.eth[7]/TC4 | 27.600 | -1598.5920000000003 / 0 / -1059.8759782875322 |

The credit statistics above are reported from the installed INET CBS vectors; their units follow the underlying INET signal and are not converted here. `idleSlope/0.77` is a configured reservation compensation, not a measured throughput guarantee. Queue growth and overflow demonstrate that the tested service did not maintain stable occupancy.

## Clock synchronization and gate audit

Downstream offsets were sampled at approximately 1 ms through the full measurement window [1,31) s. Piecewise-linear interpolation estimates time above 1 µs; excursions between samples remain unobserved.

| Seed | Node | Max absolute offset (µs) | Estimated time above 1 µs (s) | Pass |
|---:|---|---:|---:|---|
| 41 | CSW.clock | 706.468 | 0.092276 | False |
| 41 | Z1.ZSW.clock | 409.874 | 0.092310 | False |
| 41 | Z2.ZSW.clock | 1378.346 | 0.146755 | False |
| 41 | Z3.ZSW.clock | 676.796 | 0.146245 | False |

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
| 43 | HPC.eth[0] | N/A | unavailable |
| 43 | CSW.eth[0] | N/A | unavailable |
| 43 | CSW.eth[1] | N/A | unavailable |
| 43 | CSW.eth[2] | N/A | unavailable |
| 43 | CSW.eth[3] | N/A | unavailable |
| 43 | Z1.ZSW.eth[4] | N/A | unavailable |
| 43 | Z2.ZSW.eth[4] | N/A | unavailable |
| 43 | Z3.ZSW.eth[5] | N/A | unavailable |
| 47 | HPC.eth[0] | N/A | unavailable |
| 47 | CSW.eth[0] | N/A | unavailable |
| 47 | CSW.eth[1] | N/A | unavailable |
| 47 | CSW.eth[2] | N/A | unavailable |
| 47 | CSW.eth[3] | N/A | unavailable |
| 47 | Z1.ZSW.eth[4] | N/A | unavailable |
| 47 | Z2.ZSW.eth[4] | N/A | unavailable |
| 47 | Z3.ZSW.eth[5] | N/A | unavailable |

The selected valid egress values are corroborative physical-state measurements, not CBS service guarantees. A separate independent wire-summary check was unavailable because retained wire summary data were missing; results do not substitute the invalid `CSW.eth[0]` series with a derived estimate.


All scheduled GCLs passed the effective-configuration and measured gate-state checks. The 24 always-open brake SP gates in C4_shared_SPbrakes were verified from effective SCA parameters, because a permanently open gate has no transition vector. The full-path diagnostic schedules TAS on all seven egresses and has corresponding gate-state evidence. A valid GCL does not imply synchronized clocks or end-to-end viability.

## Decision findings for this exploratory pilot

- **Did SP on the real final brake egresses recover F08–F10?** Yes, for the tested L2/A1 seeds 41, 43, and 47: all 300,000 packets per flow were received with zero loss and zero packet deadline misses. The largest shared-SP brake latency was 97.814 µs against a 100 µs deadline, leaving only 2.186 µs of observed margin.
- **Did the complete treatment pass all applications and queue stability?** No. Application gates passed for all L2/A1 shared-SP runs, but the treatment failed stability in each seed; the gPTP ≤1 µs synchronization criterion also failed in each seed. At L0/A0 and L1/A1, the existing C3 control already failed application gates, so this pilot did not recover the complete workload there.
- **Did HPC/TC4 keep growing?** Yes. Its six 5 s means increased in every shared-SP L2/A1 seed; overflow was 48, 168, and 125 packets for seeds 41, 43, and 47. Seed 43 also showed sustained growth at Z3.ZSW.eth[7]/TC4.
- **Was synchronization adequate throughout measurement?** No. Approximately 1 ms samples cover [1,31) s, and the sampled maximum absolute offsets exceeded 1 µs at one or more downstream clocks in all seeds (maximum across nodes: 1.378 ms, 2.519 ms, and 1.929 ms). Inter-sample excursions cannot be excluded.
- **Does this justify an official C4 change?** It supports investigating a prospective C4 design that keeps brake-facing egresses under SP, but it does not validate C4. The shared-SP variant still needs investigation of CBS queue growth/overflow and gPTP synchronization; the full-path diagnostic shows why the final brake gates are problematic under this workload.
- **What would a later official evaluation need?** Update the prospective P1 only after review to specify the real route-derived brake egresses and SP exception, retain `C3_sync` as a paired control, and require the full application, synchronization, GCL, and queue-stability gates. This pilot does not revise the P1 or confirm H1–H5.

## Nonstable queues

| Execution | Queue / TC | Capacity (KiB) | Mean (KiB) | Peak (KiB) | Time ≥90% | Six 5 s means (KiB) |
|---|---|---:|---:|---:|---:|---|
| C4_reference_L2_A1_seed41_service_events_v2 | HPC.eth[0].macLayer.queue.queue[4] / TC4 | 32.00 | 15.51 | 31.38 | 2.457% | 4.41, 9.11, 13.15, 17.39, 21.90, 27.08 |

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
