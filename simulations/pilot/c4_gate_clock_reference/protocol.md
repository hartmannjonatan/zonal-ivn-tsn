# C4 gate-clock reference diagnostic

**Status:** exploratory, diagnostic only; it does not modify P1, the frozen C3 profile, official C0–C3, prior pilots, or the official campaign. `exploratory=true`, `diagnostic_only=true`, `official_c4_frozen=false`.

## Fixed design

The only workload is L2/A1, seed 41, with the previously paired F21/F22 calendar, 1 s warm-up, measurement `[1,31)` s, and 50 ms drain. The A005 C4 CBS profile is taken from the existing registered A005 candidate and must match the previous effective profile SHA-256 before each run. Keep application timing, gPTP, oscillator drifts, routes, VLAN/PCP/TC, FIFO, priorities, buffers, PHY, CBS slopes and limits, GCL periods, durations, and numeric offsets unchanged. Brake-only egresses remain SP with gates permanently open.

| Variant | Gate clock reference |
|---|---|
| `A005_local` | Local synchronized clock at HPC→CSW and CSW→Z1/Z2/Z3, as in the earlier pilot |
| `A005_ideal_all` | Simulation time (`clockModule=""`) at all four shared TAS egresses |
| `A005_ideal_HPC` | Simulation time only at HPC→CSW; local synchronized clocks at the three CSW egresses |

No node clock, CBS clock, interface, or application clock is replaced. No reservation or CBS/GCL parameter is changed. The ideal-clock cases are artificial controls only.

## Execution and resource policy

At most three complete executions, one per variant, run sequentially. Re-run `A005_local` because the earlier compact occupancy series omitted event numbers, preventing exact event-order population reconciliation. Before each launch the runner checks for an active official campaign, at least 45 GB free disk, and a single simulation process. It launches one OMNeT++ process at a time with reduced CPU priority and keeps vector extraction streaming to avoid retaining CBS vectors in Python memory. It records process peak RSS, runtime, free storage, logs, exact arguments, configuration hashes, profile hash, and calendar hash.

The full `.vec` is retained only until the streaming extractor validates all selected vectors and writes compressed event records. The compressed records retain event number and original line order for queue lengths/bits, queue arrivals/withdrawals/drops, CBS credits, TAS gate/guard state, clocks and transmitter state. A failure leaves the raw vector untouched. No other raw pilot or campaign result is removed.

## Analysis and limits

Queue conservation uses the same half-open `[1,31)` timestamp window for q-bit states and packet-length events, with the pre-window state as `Q_initial` and last state before 31 s as `Q_final`. Queue `queueBitLength` is INET's atomic statistic based on push-start, pull, remove and drop signals; it is not inferred from packet events alone. The extracted queue events have OMNeT++ event numbers and source-file row order. Ordering across different signals in one event can still be ambiguous where OMNeT++ emits multiple records with identical event number and timestamp; this is reported rather than invented.

Per-cycle service is computed from packet lengths entering/leaving the TC4 queue and actual gate transition times. Queue data bits are kept distinct from physical-wire serialization/IFG. Credit is joined by sample-hold only within measured intervals. The 1 ms corrected-clock trace is retained for synchronization context, but no continuous synchronization claim is made. Per-packet flow identity is unavailable in the queue length signals, so aggregate TC4 queue events are not assigned to individual flows.

All P1 application and stability gates are reported for the diagnostic treatments. A positive result with ideal gate clocks identifies a timing mechanism; it is not an approved C4 setting or validation.

## Completed run interpretation

The three planned simulations completed on the same paired calendar and fixed A005 profile. Corrected periodic offset extraction selects only the unique 1 ms grid samples and excludes non-grid `timeChanged` correction emissions. Each run has 30,000 samples per downstream clock, no sampled point above 1 µs, and a maximum absolute sampled offset below 0.05 µs. Continuous synchronization between samples remains unverified. The inherited interpolated all-emission audit is preserved as legacy data and is not used for the corrected sample gate.

With local gates, HPC/TC4's 5-second means have an OLS slope of about 3,300.9 bit/s. Replacing only the HPC gate clock with simulation time removes that queue growth and yields the same HPC cycle count/service as the all-ideal variant. The local gate has 299,993 measurement cycles (median 100.002398 µs) versus 300,000 cycles (100 µs) with the ideal HPC reference. The all-ideal treatment also removes positive slopes on CSW→Z1/Z2 that remain when only HPC is ideal. This supports a timebase relationship, but ideal references are diagnostic controls only.

The HPC local queue's endpoint population does not exactly reconcile with packet-length events: 12,176 bits and one packet remain as explicit residuals. They are not classified as drops. Stability fails in all three variants: HPC/TC4 grows with local gates; Z3.ZSW.eth[7]/TC4 grows in both ideal variants. All application gates pass and recorded packet drops are zero. Therefore the diagnostic explains the HPC residual mechanism but does not establish network-wide stability or validate C4.

Execution bookkeeping: three methodological simulations were completed; a stale NED package declaration caused one startup-only technical failure, and the inherited runner's wrong `run.csv` lookup caused three post-processing failures after completed simulations. Their raw outputs were retained and recovered without additional simulations. Final hashes and the completed checkpoint are in `results/diagnostic_results.json` and `results/checkpoint.json`.
