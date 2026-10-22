# Isolated C4 shared-link / SP-brake pilot protocol

Status: preregistered setup, not yet simulated. This protocol does not update the P1 or official C0–C3. It uses the official accepted final CBS profile `reduction_11`; the runner checks both the calibration result and campaign checkpoint and records their hashes. The previous `c4_service_preservation` pilot is preserved unchanged as historical evidence.

## Question and configurations

Test whether leaving only the three actual brake-facing outputs under SP while retaining TAS on the shared egresses recovers F08–F10 deadlines without failing any other application or queue-stability gate.

| Variant | gPTP | CBS | TAS |
|---|---|---|---|
| `C3_base` | Off | Official frozen `reduction_11` profile | Off |
| `C3_sync` | On | Same profile | Off |
| `C4_shared_SPbrakes` | On | C3 idleSlope divided by 0.77 only on CBS queues at shared TAS egresses | `HPC.eth[0]`, `CSW.eth[1..3]`; the three brake exits are SP and permanently open |
| `C4_compensated_fullpath_corrected` | On | Same fixed compensation on every CBS queue at all seven TAS egresses | Four shared egresses plus `Z1.ZSW.eth[4]`, `Z2.ZSW.eth[4]`, `Z3.ZSW.eth[5]`; one seed-41 diagnostic only |

All treatments use the same `StreamingTransmitter` / `DestreamingReceiver` PHY implementation. C3_base disables gPTP; C3_sync enables it. FIFO, strict-priority ordering, PCP/TC mapping, no preemption, routes, endpoints, workload, offsets, buffers, deadlines, and the transient calendar remain unchanged. F21/F22 remain PCP4/TC4 and are not included in permanent CBS reservations. No CBS is added to their transient-only outgoing ports.

Applications are scheduled against OMNeT++ simulation time by `CatalogUdpApp`; they are not moved to local clock time. TAS is phase-locked to each synchronized node clock. The difference between those references is intentionally retained and measured. The five gPTP participants use `ConstantDriftOscillator`; this pilot reuses the exact seed/node drift table from the previous pilot at `clock_drift_ppm_by_seed_node.json`.

## Route and egress resolution

The route table comes from `ZonalIVN.ned`, forwarding entries, and `generate_cbs.route()`. Each shared segment is 1 Gbit/s. Brake-facing links are 100 Mbit/s.

| Flow | Receiver | Egresses in route | TAS in shared-SP treatment | Queue |
|---|---|---|---|---|
| F08 | BRAKE1 | HPC.eth[0] → CSW.eth[1] → Z1.ZSW.eth[4] | HPC/CSW only; Z1 brake exit SP | PCP7/TC7 at each hop |
| F09 | BRAKE2 | HPC.eth[0] → CSW.eth[2] → Z2.ZSW.eth[4] | HPC/CSW only; Z2 brake exit SP | PCP7/TC7 at each hop |
| F10 | BRAKE3 | HPC.eth[0] → CSW.eth[3] → Z3.ZSW.eth[5] | HPC/CSW only; Z3 brake exit SP | PCP7/TC7 at each hop |

Among the 22 application flows, the three brake-facing outputs carry only their respective F08, F09, or F10. gPTP control traffic is inventoried separately by the runner. The previous pilot incorrectly scheduled `Z3.ZSW.eth[4]` instead of the F10 route's actual `eth[5]`; those historical runs are not silently relabeled as full-path TAS results.

## Cells and execution budget

Each run uses seed 41, 43, or 47, 1 s warm-up, 30 s measurement, and 50 ms drain. The schedule is fixed:

1. L2/A1 seed 41: all four variants, with `C3_base` first to generate the F21/F22 calendar and the other three replaying it exactly.
2. L2/A1 seeds 43 and 47: the three main variants (`C3_base`, `C3_sync`, `C4_shared_SPbrakes`), no parameter changes.
3. L0/A0 seed 41 and L1/A1 seed 41: the same three main variants.

Maximum: 16 methodological executions (9 primary L2/A1, 6 extrapolation, 1 full-path diagnostic). The full-path diagnostic is not a primary treatment or an additional seed. No C4 matrix, extra cells, seeds, retuning, or C3 recalibration are authorized. All eight L/A cells are preflighted for the 75% aggregate CBS reservation ceiling, TAS gate/open-time estimates, packet fit, service budget, phase/deadline budget, and gPTP control traffic. L3 remains rejected if its unchanged frozen reservations exceed the limit; no clipping is applied.

The runner is capped at one simulation process on this 14-GiB laptop, parses large output serially, and audits a recovered completed C3-base raw run before starting its paired treatments. It stops below 45 GB free disk and records technical attempts separately from methodological executions. Launching with `nice -n 15 ionice -c 3` further lowers CPU and I/O scheduling priority to keep the desktop responsive. It supplies the OMNeT++/INET shared-library paths itself, so startup does not depend on an interactive shell having sourced `omnetpp-env.sh`. Checkpoint/ledger writes are atomic. It refuses to run if the official campaign lock/process becomes active. Resume is permitted only when the full manifest hashes and profile identity still match.

## Pairing and acceptance

`C3_base` writes an F21/F22 event calendar once per cell/seed. All other treatments load that calendar and the runner verifies exact event rows and SHA-256, with separate OMNeT++ RNG streams retained for F21 and F22. Pairing failure invalidates the affected comparison. Equal seeds alone are not evidence of pairing.

The runner evaluates all P1 application gates, including per-packet deadlines, camera image completion (incomplete images count as image misses), losses, pending packets, goodput, and queue stability. Brake flow passes alone do not approve C4. Simulation validity, synchronization, GCL, application gates, analytical admissibility, and queue stability are reported separately. A missing or invalid metric never passes a gate.

The synchronized-clock check uses the full `[1,31)` measurement, with the 1 ms clock sample resolution explicitly reported. Piecewise-linear offset and threshold-duration estimates do not rule out excursions between samples. GCL checks include duration, period, offset/phase, initially-open state, and clock module. Queue evidence includes exact compact change points, capacity, maximum and mean occupancy, six 5 s means, near-capacity time, CBS credits, and overflow drops. Link utilization is accepted only for valid binary ordered state series whose recomputed fraction is within `[0,1]`; invalid values are reported unavailable, never clipped.

Comparisons are kept distinct: `C3_sync − C3_base`, `C4_shared_SPbrakes − C3_sync`, `C4_shared_SPbrakes − C3_base`, and the seed-41-only `C4_shared_SPbrakes − C4_compensated_fullpath_corrected`. They do not prove H1–H5 or officially validate C4.

## Retention and outputs

Each run retains a resolved configuration, exact command, profile and calendar hashes, full event signature, receiver/flow outputs, packet and image latency samples sufficient to recompute quantiles, drops/pending counts, compressed queue change points, clock offsets, GCL/guard-band states, CBS credits, and gates. The current shared `TrafficAudit` instrumentation aggregates packet counts/bytes by interface, flow, and queue; it does not retain per-packet timestamps across hops. Therefore exact packet-level gate-wait/serialization/processing attribution for F08–F10 is unavailable unless added in an isolated source worktree before execution. Large raw vectors are removed only after independent recomputation and reconciliation; representative failing/passing raw vectors remain compressed. The runner never deletes the older pilot or official campaign data.

The dashboard is `pilot_status.py`. The plan/checkpoint, ledger, technical-attempt log, compact evidence, JSON, and Markdown live under this directory's `results/`. The historical audit is separate from new simulation results. `exploratory=true`; `official_c4_frozen=false`.
