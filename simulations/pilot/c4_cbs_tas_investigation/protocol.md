# C4 CBS-under-TAS service investigation (exploratory)

## Scope and freeze

This isolated pilot examines whether the fixed `idleSlope_C3 / 0.77` compensation under the existing four shared TAS egresses loses usable CBS service, and tests only the six user-predeclared compensation variants. It does not change P1, hypotheses, official C0–C3, the frozen `reduction_11` profile, C3, workload, routes, buffers, deadlines, drain, clocks, GCL, CBS implementation, guard bands, or preemption. `exploratory=true`; `official_c4_frozen=false`; no final C4 matrix is authorized.

Use `C4_shared_SPbrakes`: TAS/GCL on HPC→CSW and CSW→Z1/Z2/Z3 only; SP with permanently open gates on the actual BRAKE1/2/3 egresses. The official C3 profile remains `reduction_11`. PCP/TC, FIFO and strict priority are unchanged. F21/F22 remain transient-only where applicable and are not included in permanent CBS reservations.

## Registered execution plan and limits

First perform data/source audit and synchronization JSON correction. Then run two L2/A1 seed-41 controls with targeted temporal instrumentation: `C3_sync` with the frozen C3 profile and no TAS; `C4_reference` with the existing `C3/0.77` profile on the four TAS egresses. Existing runs are reusable only if configuration, profile, calendar, PHY, metric population and required temporal evidence are all equivalent. Current SCA summaries alone are insufficient to establish the requested time-resolved queue conservation and service, so the two controls are planned as new runs in this isolated directory.

Before running any compensation candidate, publish the mechanism audit, exact profile/rate table and a signed candidate registry. Candidate IDs and transformations are fixed as follows, all L2/A1 seed 41 and relative to C4 reference:

1. `M`: only if a defensible mechanism-derived transformation can be calculated from the two controls before inspecting any candidate result; otherwise record `not_generated` and do not replace it.
2. `H005`: +0.5% on HPC/TC4 only.
3. `A001`: +0.1% on all CBS queues at HPC/TC4, CSW eth[1..3]/TC4, and the corresponding gate-eligible TC6 queues.
4. `A005`: +0.5% on the same set.
5. `A010`: +1% on the same set.
6. `A020`: +2% on the same set.

These are relative multipliers of the C4 reference reservation, not physical-port percentages. The increase must preserve dependent `sendSlope` defaults. Apply the 75% aggregate reservation ceiling per physical port with pre-execution rejection and no clipping. Keep SP at transient-only egresses and keep F21/F22 out of permanent reservation calculations. Candidate signatures are deterministic over the complete sorted (egress,TC,idleSlope) vector; duplicate vectors are logged and not executed. No unused slot is replaced.

Evaluate each unique admissible candidate against every application gate and every P1 queue-stability gate. Run the full eligible candidate list to determine the least normalized reservation increase among passing candidates; tie order is `M`, `H005`, `A001`, `A005`, `A010`, `A020`. If none pass seed 41, stop with “nenhum candidato aprovado pela investigação limitada definida.” If one is selected, freeze it and run `C3_sync`, `C4_reference`, and the selected candidate at L2/A1 on seeds 43 and 47, with the existing seed-matched calendars and drifts. Then run selected candidate, `C3_sync`, and `C4_reference` at L0/A0 and L1/A1, seed 41, applying the same transformation to that load's C3 profile. No retuning is allowed.

Maximum methodological runs: 16 = 2 seed-41 controls + at most 6 seed-41 candidates + 6 paired seed-43/47 checks + 2 extrapolation cells. Technical failures/replacements are logged separately and do not expand the methodological candidate set or cell list. Do not use seeds 1001–1030.

## Common conditions and evidence

All runs use warm-up 1 s, measurement `[1,31)` s, drain to 31.05 s; exact existing F21/F22 calendar per load/alignment/seed; existing clock drift table; simulation-time application scheduling; unchanged GCL, gPTP, FIFO, buffers, speeds, routes and PHY. Hash the code/config/profile/calendar and record commands/versions before each run. Do not compare unmatched calendars.

Targeted evidence must retain class queue arrivals, removals for transmission, overflow drops, population at the measurement start/end, packet-in-service state, queue occupancy, CBS credit changes, transmitting state, gate state, guard-band state, and valid physical link transmission evidence. Reconcile `Q_end = Q_start + arrivals - queue_removals - drops` with packet-in-service and boundary events represented consistently. Distinguish queue bits from physical-wire bits and CBS class service from total link utilization. Synchronization is reported as sampled-pass or sampled-violation separately from continuous-unverified; do not infer continuous compliance from periodic samples.

Keep compact compressed time-series and exact latency samples/denominators needed for gates and quantiles, plus configurations, calendars, profile/signature, commands, ledger, and checkpoint. Preserve at least one failed-candidate evidence set and selected-candidate evidence if any. Check free disk before/after every run; do not delete raw evidence until independent extraction and reconciliation pass. No run begins below 45 GB free or below 7 GB available RAM; one simulation job at a time, vector extraction serially.

## Causality and interpretation

Separate nominal GCL open fraction, actual eligible service/credit evolution, measured class service, offered workload, queue population and physical link use. A 77% open fraction is not assumed to imply `0.77 × idleSlope` service. The C4-vs-C3 contrast includes both TAS/gPTP and any compensation changes and is not a gate-only effect. Passing brake deadlines alone is not overall viability. No new deadline-margin threshold is introduced; report margins, including the previous 2.186 µs F08–F10 margin, as diagnostics.

## Technical instrumentation addendum (2026-10-13)

The first completed seed-41 controls did not retain queue arrival/departure vectors. Their summaries remain under `historical/instrumentation_incomplete/` and are classified `methodological_result_usable=false`; they are not candidates or evidence for queue conservation/service. A 100 ms technical smoke test confirmed that the installed INET 4.7.0 queues emit the required `incomingPacketLengths`, `outgoingPacketLengths`, and overflow-length vectors when the per-module modes are explicitly appended with `+vector`. The isolated extractor also had looked for the vector in the run subdirectory rather than the result directory. Both technical issues are corrected in `run_investigation.py`; this does not alter model behavior, workload, or registered candidate transformations. The two seed-41 controls are replaced once as `C3_sync_L2_A1_seed41_service_events_v2` and `C4_reference_L2_A1_seed41_service_events_v2`, with identical configs, seed, calendars and profiles. Prior complete simulations and partial technical attempts remain preserved. This instrumentation addendum supersedes only the data-retention/extraction implementation, not the experimental method or 16-run methodological budget.

### Post-processing correction (append-only, 2026-10-13)

The v2 C3 simulation itself completed, but its wrapper allowed the inherited raw-vector retention callback to run before the pilot-specific event extraction. That callback removed the root `.vec`; the v2 C3 row therefore has valid model/application/queue summaries but **does not** have the required CBS packet-event series and is excluded from service and conservation analysis. Its raw vector cannot be reconstructed from the retained aggregates. The v2 C4 simulation completed and its root `.vec` remains preserved; it will be post-processed from that exact raw run without re-simulation. The runner now suppresses inherited cleanup until after the selective extraction and commits the compact event file before applying raw retention. The initial-control guard now checks only controls declared in the active schedule; it no longer requires an unrelated C3_base run. A fresh C3 technical replacement is scheduled under `C3_sync_L2_A1_seed41_service_events_v3`; v2 remains historical/instrumentation-incomplete. These are executor/retention corrections only and do not expand the two-control budget, candidate set, or methodological search.

### Cohort-gate correction (append-only, 2026-10-13)

The first resume completed the C3_sync v3 cohort and extracted its compact event file, but the phase guard compared against both scheduled controls even though C4_reference was in a distinct technical cohort. It paused before the C4 post-processing cohort. The guard now checks only the just-completed cohort. C4_reference v2 remains complete and its root vector is still present; resume will post-process it without re-simulation. This changes only runner sequencing and does not change controls, candidate count, or methodology.

### Control audit and candidate registration addendum (2026-10-13)

Both seed-41 controls are complete and paired on the same 60-event F21/F22 calendar (SHA-256 `cb74a68801e037dce0480422e4371150c2c95765974b0ef3857f1633b54a600d`). C3_sync v3 passes application and queue-stability gates; C4_reference v2 passes application gates but fails queue stability. Their sampled native-tick synchronization checks pass at 1 ms resolution; continuous compliance is unverified. C3 v2 remains instrumentation-incomplete and is not used for service analysis.

A post-run audit found that the targeted physical-busy extractor selected `eth[].macLayer.phyLayer.transmitter`, while INET 4.7.0 defines the transmitter at `eth[].phyLayer.transmitter`. The compact control files therefore contain no selected `transmitting` transitions, and physical-link busy fraction for both completed controls is unavailable; no reconstruction from total-link counters is substituted. The isolated selector is corrected for all subsequent runs. CBS class service remains computed from the class queue's own packet-length arrivals/removals, not physical-link busy time. Exact queue conservation at the `[1,31)` boundaries is also marked unavailable for strict equality where queue occupancy vectors lack event numbers needed to order same-timestamp transitions; measured residuals are retained as diagnostics and not rounded away.

Candidate `M` is registered before any candidate run. For each CBS class queue actually configured on the four gate egresses, its multiplier over `C4_reference` is `0.77/f_eligible`, where `f_eligible=(measured gate-open duration − measured implicit-guard duration)/30 s` from C4_reference. This implements `I_M=I_C3/f_eligible` using the observed mechanism. The values are: HPC.eth[0]/TC4 0.7699489122; CSW.eth[1]/TC4 0.7699799970; CSW.eth[2]/TC4 0.7699805135; CSW.eth[3]/TC4 0.7663432133. This is a seed-41, control-informed exploratory estimate: the guard-band duration depends on packet-fit/queue state and it is not a service guarantee. The generated effective profile and all six fixed candidates, signatures, per-port totals and 75% headroom are recorded in `candidate_registry.json`; that registry is immutable for the candidate phase. All six signatures are distinct and every candidate is below the 75% per-port ceiling. The exact registry hash and source/config hashes are captured in the candidate-phase manifest before execution.

The registered order remains `M`, `H005`, `A001`, `A005`, `A010`, `A020`; no unused position is replaced. Selection remains the lowest sum of per-queue reservation increases normalized by physical port rate among candidates passing all application and stability gates, with the registered order as tie-breaker. Control synchronization is not counted as continuously compliant and is not folded into the application/stability gate.

### Physical-transmitter extraction correction (append-only, 2026-10-13)

The corrected selector has been checked against the INET 4.7.0 NED/vector definition in the preserved technical smoke output. The historical controls are not re-run solely to recreate this metric because their raw vectors have already been removed after compact extraction; their physical-link busy metric remains unavailable. Future candidates record the correctly selected state vector. This correction affects physical-link utilization only, not queue service, credit, gate, application or stability measurements.
