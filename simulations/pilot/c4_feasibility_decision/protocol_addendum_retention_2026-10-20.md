# Retention addendum, 2026-10-20

This addendum changes evidence storage only. It does not change treatments, workload, seeds, gates, CBS profiles, acceptance rules, or candidate selection. It applies before any conditional seed/load execution.

The full OMNeT++ vector remains the source for the validated report. To keep the 40 GiB free-space floor across the authorized conditional runs, a full vector may be removed only after `compact_exact_samples.py` has:

1. streamed and verified the decompressed full-vector SHA-256 against the run report;
2. retained the original ETV text records for every receiver `latency` and `imageCompletionLatency` sample selected from the P1 cohort `[1,31)` s, including the 50 ms drain boundary;
3. independently reconciled each sample population, nearest-rank p99, maximum, and deadline-miss count to the report;
4. written `qos_samples.vec.gz` and its manifest with source/compressed hashes.

The compact exact sample vector is supplemented by the already retained and validated queue-occupancy change points, packet-event trace, direct clock samples, gate/guard-band state series, CBS-credit vectors, SCA, and run log. The manifest records the original full-vector hash and the fact of removal. If any check fails, the full vector is retained and the execution cannot advance to the next run until storage is resolved without crossing the 40 GiB floor.

Full vectors from previously completed seed-41 runs may use the same evidence-preserving compaction after validation. Historical pilots are not modified. Each simulation remains serial, with a resource check before launch and after compaction.
