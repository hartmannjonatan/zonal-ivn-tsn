# C4 final verification pilot — preregistered protocol

Created 2026-10-20 before new methodological executions. `exploratory=true`; `official_c4_frozen=false`. This does not modify P1, C0–C3 or the official campaign.

## Candidate and treatments

Candidate `D3_coordinated_20pct`, sourced from the accepted L2/A1 result `D3_TAS_L2_A1_seed41` in the C4 feasibility study, is frozen by the canonical 24-entry profile hash in `manifest.json`. The table, GCL and parameter contract are copied locally. Every idleSlope remains at the absolute L2 value for all loads, including talkers, TC6 and non-TAS egresses; no per-load ratio or clipping is allowed. `sendSlope=idleSlope−physical bitrate`; credit parameters remain initialCredit=0, transmitCreditLimit=0, unbounded min/max/maxInterferenceSize, `accumulateCreditInGuardBand=false`, extraLength 64 bits and extraDuration 0. No CBS is instantiated on Z1/Z2 CPU eth0 TC4 or Z3 switch eth1 TC4; those transient-only queues remain SP.

`D3_fixed_TAS` uses the frozen 100 µs GCL, 55 µs TC4 and 30 µs TC7 openings, initially open, absolute schedules on synchronized node clocks, implicit guard band, with HPC eth0 TC4 offset 70 µs and CSW eth1/2/3 TC4 offset 69.324 µs; TC7 offsets are 0 and 99.324 µs respectively. `D3_fixed_noTAS` retains precisely the same CBS/gPTP and uses permanently open gates (no periodic schedules). The two-run pair within each cell/seed is the TAS contrast. C3 comparisons remain system comparisons because their reservation profile differs.

## Matrix, reuse and order

Main matrix: L0–L2 × A0/A1 × seeds 41/43/47 × two treatments = 36 positions. Valid reused positions are registered in `matrix.csv`. Phase 1 first fills seeds 43/47 for L0/A0 and L1/A1, then seed 41 pairs for L0/A1, L1/A0 and L2/A0. If any valid performance failure occurs, finish its pair and halt conditional expansion. Only if all phase-1 positions pass may remaining seed/cell positions be scheduled. No parameter changes or retuning are permitted.

L3 is triaged separately. It is rejected without simulation if the absolute profile’s service upper bound is below permanent demand. Otherwise run seed 41 pairs first and expand to 43/47 only after both pass. At most 48 methodological positions, including reuse, and at most two replacements for demonstrated technical invalidity. Performance failures are retained and never replaced. No official seeds 1001–1030.

Each cell/seed uses one immutable F21/F22 calendar created once by the registered seed, then reused byte-for-byte in both treatments. Existing calendars are reused only by signature. Seeds alone do not establish pairing. Drift values use the pilot’s separate seeded oscillator streams and identical seed in both treatments. Each run is 1 s warm-up, `[1,31)` s measurement and 50 ms drain.

## Technical/admission/application gates

Before measurement, require all 24 CBS modules and exact parameters, profile hash, gate contract and all-class gate parameters, SP exceptions, resolved P1 buffers, correct cell workload, seed/calendar signatures and no active official campaign. Recheck final SCA/events. A missing credit vector, mismatched SCA/runtime GCL or unresolved buffer is technical invalidity.

Apply current P1 application and stability gates unchanged. Report simulation validity, profile/GCL validity, application outcome, confirmed loss/overflow, queue-stability proxy, sampled sync and continuous-sync status separately. Camera packet and image populations are separate; incomplete images enter image misses. Queue indicators use `[1,31)` boundaries, real capacity, and preserve in-service packets/residuals. Native simultaneous tick subtraction is used for synchronization. A 1 ms sampled pass is not continuous conformance.

F13 is reported as observed natural-episode recovery while offered load remains active, defensible service margin, or not identifiable. No artificial backlog and no retrospective “53 frames” gate. Empty endpoints with equal arrivals/departures do not establish lack of service margin.

## Storage and stopping rule

One simulator at a time, minimum 40 GiB free disk and 7 GiB MemAvailable before and throughout a run. New evidence is extracted incrementally and losslessly compressed with byte/hash verification. Preserve per-flow p99/max-recalculable upper-tail samples, counts/gates, compact queue time series, clock tick samples, credit samples, calendars, configuration and hashes. Do not remove historical files. When projected temporary+retained output would cross the 40 GiB floor, stop before launch, write checkpoint/ledger and list exact unexecuted positions. The present baseline is approximately 58 GiB free; a conservative projection for all 14 phase-1 new runs exceeds the 18 GiB spendable space, so run only a bounded batch that stays above the floor and then re-evaluate.
