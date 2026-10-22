# Clock timestamp precision audit — C4 shared-SP-brakes pilot

**Finding:** the reported exact `−10 µs` peaks are serialization/subtraction artifacts, not observed differences between the parent clocks. The old observer wrote absolute `double` clock values through a default `std::ofstream` (six significant digits); the Python analyzer then subtracted those already-rounded strings. New simultaneous native-tick probes at the cited instants find only `−20 ns` and `−40 ns`. Across the corrected two-second windows, no observed offset exceeded `1 µs`. This does not prove continuous compliance over a 30-second measurement.

This is an isolated instrumentation/export correction. No gPTP, oscillator drift, workload, GCL, CBS, P1, or acceptance criterion was changed. The independent CBS queue growth/instability finding remains.

## Code-path diagnosis

The old [`ClockAuditProbe.cc`](../plugin/ClockAuditProbe.cc) stored time as `double` and wrote `simTime().dbl()`, signal values, `IClock::getClockTime().dbl()`, and the `SettableClock` underlying/free clock `.dbl()` values to a default-formatted stream. No `setprecision` was set. For values near 1.25–1.80 seconds, the default six significant digits quantize absolute time to roughly 10 µs. [`analyze_probe.py`](../scripts/analyze_probe.py) parsed those strings as Python floats and computed `node_clock_s - hpc_clock_s` afterward. The old output therefore did not preserve enough information for sub-microsecond subtraction.

`signal_matches_direct_getter` in the old analysis compared `signal_value_s` with the corresponding getter value after both had been written at the same six-digit precision. Agreement at that point only demonstrated agreement after rounding; it was not an independent precision check. The free-clock and compensation timelines in that export also used the same default formatting, so their absolute readings cannot support nanosecond-level comparisons.

The corrected isolated observer [`ClockPrecisionProbe.cc`](plugin/ClockPrecisionProbe.cc) snapshots the five corrected `clocktime_t` values at one event, snapshots the underlying free clocks separately, computes `value - hpc` while still in the native fixed-point type, and writes signed integer raw ticks. The file records `simTime` raw ticks and scale exponent, event number, per-row sequence, emitter/signal, raw signal time where applicable, corrected clock, free clock, and direct offset. INET's synchronized parent is the `SettableClock` used as the configured TAS clock; its underlying oscillator is recorded in separate columns and is not substituted for it. For double-valued compensation signals, the observer uses `max_digits10`.

The OMNeT++ scale is `−12`, i.e. 1 ps per raw tick for these records. Equal-time rows retain observer sequence and event number; no value sorting, interpolation, or extrapolation is used for this audit. Each row is a same-event snapshot. Signal callbacks are kept distinct from the periodic observer population.

## Reproduction at the two alleged peaks

| Run / time | Legacy absolute timestamps (HPC; node) | Legacy subtraction | Corrected simultaneous readings | Corrected offset |
|---|---|---:|---|---:|
| C3_sync, 1.801 s, Z1 | 1.80094; 1.80093 s | −10 µs | 1,800,935,020,000; 1,800,935,000,000 ticks | −20 ns |
| C4_shared_SPbrakes, 1.247 s, CSW | 1.24696; 1.24695 s | −10 µs | 1,246,955,010,000; 1,246,954,990,000 ticks | −20 ns |
| C4_shared_SPbrakes, 1.247 s, Z1 | 1.24696; 1.24695 s | −10 µs | 1,246,955,010,000; 1,246,954,990,000 ticks | −20 ns |
| C4_shared_SPbrakes, 1.247 s, Z2/Z3 | 1.24696; 1.24695 s | −10 µs | 1,246,955,010,000; 1,246,954,970,000 ticks | −40 ns |

Ticks in the corrected column are `clocktime_t` raw ticks at 1 ps/tick. The HPC raw reading is the common reference; the shown slave tick is its simultaneous corrected parent-clock value. The old output rounded both numbers independently before subtraction. The exact source rows (including event number, row sequence, free clock and offsets for every node) are in [`precision_peak_snippets.csv`](precision_peak_snippets.csv); complete corrected CSVs, commands and logs are retained below `technical/`.

The original full-run compact offset vectors independently agree at the target instants: C3_sync/Z1 at 1.801 s is `−2.0000000100495186e−08 s`; C4/CSW and Z1 at 1.247 s are `−2.0000000100495186e−08 s`, and Z2/Z3 are `−3.9999999978945766e−08 s` (the slight non-round numbers reflect conversion of vector doubles). The high-precision technical probe records exact 20/40 ns ticks. This is a cross-check, not a reconstruction from drift or neighboring samples.

## Corrected probe populations

Window: `[1,3)` s, two short technical executions, seed 43, 1 ms periodic observer plus parent `timeChanged` callbacks. Percentiles use nearest rank on absolute offsets. Callback records and periodic samples are reported separately; neither is interpolated.

| Run | Node | Population (n) | p99 | offset | | Max | offset | | Samples >1 µs |
|---|---|---:|---:|---:|---:|
| C3_sync | CSW | periodic 2,000 / callbacks 2,048 | 0.01 / 0.01 µs | 0.02 / 0.02 µs | 0 / 0 |
| C3_sync | Z1 | 2,000 / 2,048 | 0.02 / 0.02 µs | 0.03 / 0.03 µs | 0 / 0 |
| C3_sync | Z2 | 2,000 / 2,048 | 0.02 / 0.02 µs | 0.03 / 0.03 µs | 0 / 0 |
| C3_sync | Z3 | 2,000 / 2,048 | 0.02 / 0.02 µs | 0.02 / 0.02 µs | 0 / 0 |
| C4 shared-SP | CSW | 2,000 / 2,048 | 0.02 / 0.02 µs | 0.02 / 0.02 µs | 0 / 0 |
| C4 shared-SP | Z1 | 2,000 / 2,048 | 0.03 / 0.03 µs | 0.03 / 0.03 µs | 0 / 0 |
| C4 shared-SP | Z2 | 2,000 / 2,048 | 0.04 / 0.04 µs | 0.05 / 0.05 µs | 0 / 0 |
| C4 shared-SP | Z3 | 2,000 / 2,048 | 0.03 / 0.03 µs | 0.04 / 0.04 µs | 0 / 0 |

The two samples at exactly `t=1 s` are included because the declared window is `[1,3)`. There are 2,000 periodic times and 2,048 parent `timeChanged` records per clock in the window. The biggest corrected observed offset is 50 ns (C4/Z2); no observed sample is near the 1 µs limit. A 2-second probe and the full-run 1 ms grid do not rule out excursions between observations or outside these short runs.

## Serialization regression check

[`test_precision_serialization.py`](test_precision_serialization.py) passed integer-tick round trips for known 20 ns, 30 ns, 1 µs and 10 µs offsets, plus `1 µs ± 1 ps`. It confirmed that the native-tick encoding preserves the 1 µs boundary exactly. Its legacy demonstration applies six-significant-digit formatting to absolute times near 1.247 s: a true `−20 ns` difference serializes as `1.24696 − 1.24695 = −10.0000000001 µs`, creating a false violation. The same quantization can also erase or change a true small offset; therefore old rounded offsets cannot be corrected by algebra after export.

## Runs, provenance, and preserved evidence

Two short technical probes were necessary because the prior CSV had irreversibly discarded the digits needed to resolve the question. Both reused the existing L2/A1 seed-43 transient calendar (SHA-256 `5163828318dfc113d004cb4e1f60773b9a0fbe225a31ed8e1182d93353b46982`), the existing recorded drift values and C3/C4 settings, with warm-up 1 s, observation `[1,3)` s, termination 3.05 s. C3_sync completed at 2026-10-12 23:56:48 UTC; C4 shared-SP completed at 23:59:25 UTC. Both returned code 0. These are instrumented technical reruns, not application/queue validation or replacement 30-second executions.

- C3 probe: `C3sync_L2_A1_seed43_v1`, raw trace SHA-256 `289f882b5a499cd8550fd63a1c02694adf4f398bae2950a4e6a230708a1156e1`.
- C4 probe: `C4compensated_L2_A1_seed43_v1`, raw trace SHA-256 `513694573248c659e47398b7d19b9ff329b5b6417934a6cdd7ebd10ef21e6704`.
- Observer source SHA-256: `ce1b87bf9c80515285726d784b9586ddcb8ef4842ad7912b8c0db662fd98ba4e`.
- The full command, configuration overrides, drift, calendar hash, completion status and trace hash are recorded in each `technical/<run>/command.json`. `precision_summary.json` contains the exact target values and per-population counts/quantiles/maxima; [`legacy_precision_comparison.csv`](legacy_precision_comparison.csv) places the old and corrected values side by side, and [`precision_manifest.json`](precision_manifest.json) records hashes and versions; the consolidated [`precision_audit.json`](precision_audit.json) combines diagnosis, exact results, run metadata and provenance. The raw CSVs and neighboring rows are retained for independent checking.
- OMNeT++ 6.4.0 and INET 4.7.0 (`dfe270b21f`) were used. No shared simulation source or official campaign was changed.
- Previous pilot and synchronization-audit reports are retained under `data/previous/` before this precision correction.

## Answers and corrected interpretation

1. **Was the original write precision insufficient?** Yes. Default stream formatting emitted six significant digits for absolute `double` timestamps.
2. **Was the old offset subtracted after rounding?** Yes. The analyzer parsed the rounded strings and then subtracted them.
3. **Can rounding alone reproduce the peaks?** Yes, exactly to the observed `−10 µs` scale; the legacy rows at the cited times show the rounded values, while the new simultaneous reads and original compact offsets show only tens of nanoseconds.
4. **What is the corrected maximum?** In these two `[1,3)` s seed-43 probes, 30 ns for C3_sync and 50 ns for C4 shared-SP (the latter at Z2). The original full-run 1 ms grid's maximum remains 0.06 µs over its retained runs.
5. **Are there corrected readings above 1 µs?** None in the 2,000 periodic or 2,048 parent `timeChanged` observations per node in either short probe; none in the retained full-run 1 ms grid. This is a sampled result, not proof of continuous compliance.
6. **Which prior conclusions change?** Withdraw “real 10 µs excursions confirmed,” the resulting synchronization-gate failure attributed to those peaks, and any causal interpretation based on them. Replace with “rounded-export artifact; all audited samples are below 1 µs; continuous compliance is unverified.” Keep the independent C4 rejection due to CBS queue growth/instability. C4 is not validated.

