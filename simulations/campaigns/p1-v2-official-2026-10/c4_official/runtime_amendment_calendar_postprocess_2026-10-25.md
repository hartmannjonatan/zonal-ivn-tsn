# C4 runtime amendment: post-processing and completed-run recovery

Date: 2026-10-25. This amendment records three extraction defects found after `C4_L0_A0_seed1001` reached the configured normal end at 31.05 s.

1. `calendar_signature()` returns `(sha256, row_count)`, but the runner called `len()` on the integer row count. The check now compares the returned count directly.
2. The traffic checker assumed the network root was `ZonalIVN`; C4's instrumented network root is `C4Instrumented`. The checker now derives and validates the single observed root before reconstructing routes.
3. The shared result validator also hard-coded `ZonalIVN` when matching SCA module paths, queues and application vectors. It now takes the validated root from the traffic audit (defaulting to `ZonalIVN` for C0-C3).

The preserved raw C4 run passed schedule, size, VLAN/PCP, route and packet accounting checks after these corrections: 0 recorded drops and 0 packets pending at the simulation end. The runner supports `--reprocess-existing-only --execution-id ...`; this validates and commits existing output without launching OMNeT++. Ordinary `--run --resume` also recognizes an existing raw run only when its log proves normal completion and required artifacts are present.

No simulation behavior changed: workload, topology, buffers, CBS/GCL, clocks, seed, simulation command and acceptance thresholds are unchanged. The preserved execution was run under the immediately previous snapshot; its ledger records both `simulation_snapshot_id` and the post-processing snapshot. This is a technical/export correction, not a new simulation or a performance result.


4. A second root-name assumption remained in C4-only validation: observed gate vectors, gPTP parameter paths, and queue/drop vector discovery still used the standard `ZonalIVN` prefix. These checks now use the validated runtime root (`C4Instrumented`) end-to-end. The shared SCA queue summary accepts both recognized roots, while per-run vector selection remains constrained to the root established by the traffic audit. This is a post-processing correction only.

5. The shared validator used the validated root internally but omitted it from its returned report. C4 then fell back to `ZonalIVN` while checking CBS/GCL SCA module paths. The report now carries `network_root`, and the C4 contract self-test covers both `ZonalIVN` and `C4Instrumented`. This closes the root-name mismatch in post-processing; no model or simulation input changed.
