# Runtime amendment: escaped SCA `typename` parsing (2026-10-25)

The first C4 matrix position, `C4_L0_A0_seed1001`, completed its OMNeT++ run normally at simulation time 31.05 s. Its postprocessor then rejected the resolved HPC clock with `HPC: corrected SettableClock missing`.

The preserved SCA does contain `C4Instrumented.HPC.clock typename "\"inet.clock.model.SettableClock\""` (and corresponding oscillator/gPTP types). The shared SCA parser leaves escaped quotes and backslashes in string values; the C4 runner previously tested the raw value with `endswith`, causing a false technical rejection before the result report or ledger row was committed.

The C4 runner now normalizes escaped string delimiters for the three type checks (SettableClock, ConstantDriftOscillator, and Gptp). The first reprocessing pass then exposed a second runner-only defect: the gate-state audit referenced `vec_path` without assigning the existing run's vector path. The runner now binds and verifies `dest / f"{config}-#0.vec"` before that audit.

Both are post-processing/validation corrections only. They change no model, configuration, workload, seed, calendar, binary, plugin, or simulation event. The existing normally completed raw run is retained and reprocessed under the corrected runner; no replacement simulation is needed unless reprocessing reveals a separate instrumentation/configuration defect.

The original manifest is preserved in `protocol_history/manifest_before_sca_typename_parser_fix_20261025.json`; the intermediate manifest before the vector-path correction is preserved as `protocol_history/manifest_before_vec_path_fix_20261025.json`. The amended manifest records the original simulation snapshot and each post-processing snapshot so the provenance of the already completed run remains explicit.
