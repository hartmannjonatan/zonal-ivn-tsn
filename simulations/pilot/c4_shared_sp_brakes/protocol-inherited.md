# C4 service-preservation pilot protocol

Status: preregistered pilot; this setup task did not launch simulations. Two earlier user launches created eight technical attempts that stopped during startup: the first had an invalid `simtime-resolution` placement; explicitly forcing `fs` in the next correction exceeded OMNeT++'s representable time range. The pilot now inherits the default resolution used by the official campaign. A third launch completed four full L2/A1 seed-41 simulations, but the runner falsely rejected all four during its CBS audit: the SCA parser retained `.macLayer.queue.transmissionSelectionAlgorithm` in the egress key, while the expected key contains only the interface. Inspection confirms all four effective `idleSlope` maps equal their requested profiles once normalized. The parser is corrected, and completed raw runs are now recognized by config, seed, input file, and successful end-of-run log markers, allowing metrics to be reprocessed without rerunning OMNeT++. The twelve attempts remain in `results/technical_attempts.jsonl`; raw data remain in `results/runs/` until the runner reconciles and compacts them. No pilot result has yet been committed to `runs.jsonl`. Earlier plans are preserved in `results/plan_history/`. This directory is isolated from the P1 and official C0–C3 campaign; the sole CBS source remains the accepted official C3 profile `reduction_11`.

## Question and variants

The pilot separates the effect of gPTP from the effect of TAS, and tests only the P1-determined compensation. All variants preserve the workload, topology, routes, buffers, PCP/TC mapping, FIFO order within TC, descending TC priority, and non-preemptive Ethernet.

| Variant | CBS | gPTP | TAS |
|---|---|---|---|
| `C3_base` | Frozen C3 profile | Off | Off |
| `C3_sync` | Same frozen C3 profile | On | Off; all gates remain open |
| `C4_original` | Same frozen C3 profile | On | P1 GCL; one diagnostic at L2/A1 seed 41 |
| `C4_compensated` | Frozen C3, divided by 0.77 only on CBS queues on TAS egresses | On | Same P1 GCL |

TAS egresses are `HPC.eth[0]`, `CSW.eth[1..3]`, and `Z1/Z2/Z3.ZSW.eth[4]`. CBS is configured only on positive-permanent-reservation egress/class pairs present in the frozen profile. F21/F22 remain PCP4/TC4, excluded from permanent reservations; a transient-only egress remains SP. No zero-slope CBS instance is added.

## Effective GCL and service model

The 100 us cycle is represented with INET 4.7 `PeriodicGate` instances synchronized to each node clock. TC7 is open for 10 us and closed for 90 us (`initiallyOpen=true`, durations `[10us,90us]`, offset 0). TC0–TC6 are open for 77 us and closed for 23 us; the 90 us phase offset of the `[77us,23us]` cycle makes them closed for 10 us, open from 10–87 us, then closed for 13 us. The latter is the P1 13 us explicit closed guard. INET's implicit guard band remains enabled, so a frame that cannot finish before gate closure cannot start. Ethernet frame preemption remains off.

INET 4.7 source inspection confirms that `CreditBasedGate` freezes credit when its linked periodic gate is closed. `accumulateCreditInGuardBand` defaults to false, so credit also does not accumulate during the implicit guard band. `PeriodicGate` checks frame completion before the next close when implicit guard band is enabled. Since the CBS idleSlope and sendSlope remain configured in the usual way, `0.77 * idleSlope` is used only as a first-order average-service estimate for a continuously backlogged queue; it is not treated as a measured guarantee. The pilot records credit vectors and gate states to test the estimate. The P1 compensation is fixed at `idleSlope_C4 = idleSlope_C3 / 0.77`; no tuning is permitted.

The seven TAS egresses are screened at every L/A cell. For each port, the preflight checks aggregate TC4+TC6 configured CBS reservation against 75% of physical rate, permanent offered load against the 77% TC0–TC6 open-time budget, and per-TC permanent load against estimated CBS service. TC7 has 10% of physical port rate available; the screen adds the catalog brake load and a gPTP serialization estimate derived from the INET 4.7 message structures and the configured intervals. These are analytical screening estimates, not simulation measurements. Implicit guard-band loss and interference are reported as unmodeled margin; the simulation decides behavior.

## gPTP and random pairing

There is one domain with HPC grandmaster, CSW bridge, and three zonal-switch bridges. HPC transmits on `eth0`; CSW receives on `eth0` and transmits on `eth1..3`; each zone switch receives on `eth0` and transmits on `eth1..8`. Sync interval is 125 ms and peer-delay interval is 1 s. Only those five nodes participate; endpoint devices do not. Each participant uses `ConstantDriftOscillator`, with one seed-and-node keyed value sampled uniformly from -50 to +50 ppm and held constant. The same generated drift table is reused by all three gPTP variants for a seed. gPTP packets without PCP use the classifier's explicit default gate 7; packets carrying PCP continue through the identity PCP-to-TC map.

The traffic generator's source explicitly uses independent RNG indices 0 and 1 for F21 and F22. The events are generated during `TrafficPlan.initialize`, before network events, and the clock drift is supplied as an explicit pilot value rather than consuming OMNeT RNG state. Every run still writes `events.csv`; the runner compares the exact F21/F22 rows and SHA-256 signature within each load/alignment/seed group. A mismatch invalidates the affected paired group. Same seed alone is not considered proof.

## Runs, order, and acceptance

Each executed run uses seed 41, 43, or 47; 1 s warm-up, 30 s measurement, and 50 ms drain. The plan is:

1. L2/A1 seed 41: `C3_base`, `C3_sync`, `C4_compensated` if admissible; then at most one `C4_original` diagnostic, even if inadmissible.
2. L2/A1 seeds 43 and 47: the three primary variants, using the exact frozen seed-specific profile with no retuning and only when admissible.
3. L0/A0 seed 41 and L1/A1 seed 41: `C3_base`, `C3_sync`, and `C4_compensated` when admissible.

Maximum: 9 main L2/A1 executions, 6 extrapolation checks, and 1 diagnostic = **16**. No cells or seeds are added automatically. Preflight rejections and technical failures are separate from completed simulations.

Application viability uses the common P1 validator's per-flow gates, packet/image denominators, queue drop and stability rules. `application_viable` is kept separate from `admissible`, `simulation_valid`, synchronization, and TAS instrumentation. As a pilot-specific synchronization diagnostic, all four downstream clocks must be within 1 us of HPC at the end of warm-up and remain within 1 us over the final 100 ms of warm-up; this is explicitly an operational pilot threshold, not a new P1 gate. For TAS runs, gate-state vectors must show the configured open fractions within one gate-transition sampling interval; missing gate vectors make the TAS instrumentation gate unavailable, not passed.

The runner reports the five requested comparisons independently: `C3_sync − C3_base`, `C4_original − C3_sync`, `C4_compensated − C4_original`, `C4_compensated − C3_sync`, and `C4_compensated − C3_base`. The original-versus-compensated contrast is limited to the one diagnostic cell if no further original runs are authorized. With at most three seeds, there are no confirmatory claims about research hypotheses.

## Metrics and evidence retention

The common validator records flow/receptor packet and camera-image metrics, queue drops, and exact occupancy change points; the pilot independently recomputes queue indicators before removing raw vectors. The pilot additionally captures time-weighted physical-link utilization from `transmitting` state vectors (not the invalid SCA histogram mean), gate and guard-band state changes, clock-time vectors at 1 ms intervals, gPTP rate-ratio/pdelay/drop statistics, CBS credit vectors, and resolved `idleSlope` parameters. Send-event logs are parsed for gPTP message type and interface; if the installed runtime does not expose enough information, counts/bytes are marked unavailable and the serializer-based estimate remains explicitly an estimate.

Exact upper-tail latency samples and sample counts remain in `latency_upper_tails.json.gz`, sufficient to recompute the nearest-rank p99 and maximum; misses remain tied to the same vector populations. Queue traces and metadata remain compressed, with exact change points, capacity, units, initial state, and half-open measurement window. Calendar CSVs, resolved configuration/commands, hashes, queue and gate/clock traces, ledger rows, and compact metrics are retained. One completed nonviable raw vector and one viable raw vector are retained if such cases occur. Other raw vectors are removed only after all compact traces, populations, gates, calendars, and queue recomputations reconcile. The runner stops submitting work below 45 GB free space.

Final files are `results/pilot_results.json` and `results/analysis.md`; the committed result ledger is `results/runs.jsonl`, technical attempts are separate in `results/technical_attempts.jsonl`, and `results/checkpoint.json` plus `results/plan.json` provide recovery/audit. A completed ledger row is never rerun. After a process interruption, uncommitted files under that scheduled run ID are moved to `results/failed-attempts/` with a file inventory before retry. On resume, cleanup of a committed run is completed if power failed after its ledger write but before compression. Technical attempts do not count as gate results or as completed scheduled executions. `exploratory=true`; `official_c4_frozen=false`.
