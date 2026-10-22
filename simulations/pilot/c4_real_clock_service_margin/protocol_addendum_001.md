# Technical addendum 001 — network identity in exported paths

This addendum records a technical correction after the first B run and before any other methodological variant. The original protocol remains preserved in `protocol.md` and `results/protocol_manifest.json`.

The first `B_local` simulation completed its 31.05 s limit, but inherited validation failed because the pilot-derived network type was named `ZonalIVNRealClockTrace`. That altered the root prefix in `wire.csv`, `queues.csv`, and `drops.csv` to `ZonalIVNRealClockTrace.*`, while the canonical route checker expects `ZonalIVN.*`. The flow source and receiver CSVs both report 775,000 F01 packets with identical sequence sums and application bytes; this was a postprocessing path-identity mismatch, not evidence of packet loss. The output was retained intact under `results/technical/attempt_001_network_prefix/` and is marked technically invalid for route-based reconciliation.

The isolated pilot network type is renamed to `ZonalIVN`, preserving the same inherited topology and adding only the two pilot probes. No workload, route, clock, gate, CBS, PHY, or acceptance setting changes. Rebuild the probe and repeat only the B control as technical replacement 1 of the maximum two. The corrected SCA/export route prefix must equal `ZonalIVN.*` before any later variant is permitted.
