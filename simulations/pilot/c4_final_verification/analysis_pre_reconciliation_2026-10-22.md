# C4 absolute-profile final verification — current audit and coverage

**Status:** `exploratory=true`; `official_c4_frozen=false`. This is a partial, resource-paused exploratory study, not an official C4 validation. No tuning or P1 change was made.

## Decision now

The absolute 24-entry `D3_coordinated_20pct` profile is empirically viable in the cells actually covered: L0/A0 with seeds 41, 43, 47; L1/A1 with seed 41; and L2/A1 with seeds 41, 43, 47. All 14 usable positions (10 audited reuse + 4 new) passed the technical, application, queue-stability, sampled-synchronization, and zero-overflow checks. This supports further evaluation of the fixed profile in those cells, but not adding it as a frozen P1 policy yet: the authorized matrix stopped before the L0/A1, L1/A0 and L2/A0 crosschecks, and L1/A1 seeds 43/47 remain incomplete. L3 was rejected analytically for this fixed profile and was not simulated.

On L0/A0, gates-open and TAS treatments both pass. TAS has no observed effect on F06/F07 packet latency in these results, while it increases brake and transient flow latency. It does not improve application pass/fail or loss/stability outcomes in this cell. That makes noTAS the lower-delay option in the observed L0/A0 data; it does not establish that TAS is unnecessary in other cells.

## Prior questions resolved

The detailed audit is in [answers_previous_questions.md](answers_previous_questions.md). The effective CSW→Z3 per-class buffer is **1,048,576 bits = 131,072 bytes = 128 KiB**, in both scaled and fixed-profile runs. “1 MiB” was an earlier bit/byte labeling error, not a buffer modification. The resolved SCA and reports confirm the same capacity.

For the same cell/seed, scaled versus fixed comparisons hold workload, calendar, classification, topology, PHY, GCL, clocks and software identity constant to the extent recorded; the material service change is the absolute set of 24 CBS reservations and derived sendSlope values. It is a whole-profile intervention, not evidence about one queue. The fixed table and its hash are in [frozen_profile_table.csv](frozen_profile_table.csv) and [manifest.json](manifest.json).

The existing C3 controls are valid, load-specific official C3 profiles. C3 L0/A0 seed 41 loses 72,373 packets by queue overflow and fails application gates; C3 L1/A1 seed 41 loses 59,460 and fails application and stability gates. The fixed D3 profile passes the same-cell seed-41 comparisons. That demonstrates an outcome difference under the broader reservation policy; it does not isolate the cause to one egress or prove that transient traffic alone caused C3’s failure.

The D3 used here is `D3_coordinated_20pct` from the feasibility study’s L2/A1 seed-41 result, hash `571e3a10e004005b2994aadc6dc495db730f6e9b8842af2550ebcbb3d6eb33be`. It is not the older, brake-failing D3 from `c4_joint_dimensioning`.

Synchronization uses simultaneous corrected-clock reads in native integer ticks, subtracted before serialization. The reused profiles contain 30,000 periodic 1 ms samples per node in `[1,31)` plus discrete clock-change snapshots; the four new L0/A0 runs preserve the same direct-tick audit. All audited samples pass ≤1 µs (the observed periodic maxima in reused L2/A1 are 20–50 ns; seed-43 new L0/A0 maxima are at most 60 ns). This does not establish continuous conformance. The JSON preserves legacy per-run sync flags and separately records the authoritative direct-tick reprocessing so those historical flags are not silently rewritten.

## Frozen profile and triage

The canonical profile has 24 port/TC reservations. All ports remain below the 75% aggregate cap; the tightest is `CSW.eth[3]` at 707.606774 Mb/s on a 1 Gb/s egress, leaving 42.393226 Mb/s to the cap. Other notable totals are `HPC.eth[0]` 406.375399 Mb/s; `Z1.ZSW.eth[0]` 545.25 Mb/s; `Z2.ZSW.eth[0]` 218.53 Mb/s; and `Z1/Z2.ZSW.eth[7]` 61.68 Mb/s on 100 Mb/s links. These are sums of configured class reservations, not measured link utilization or consumed bandwidth. See the full table for every row and margin.

L3/A0 and L3/A1 were rejected before simulation for this fixed profile. The recorded permanent demand at `CSW.eth[0]` is 862.656 Mb/s against a fixed-profile CBS service upper bound of 539.16 Mb/s. Under the stated workload and bound, the candidate cannot serve that permanent demand. This rejects this fixed candidate at L3; it does not prove that CBS/TAS generally cannot serve L3.

## Results and paired contrasts

The 36 L0–L2 positions and 12 L3 positions are enumerated in [matrix.csv](matrix.csv). Fourteen L0–L2 positions are usable: ten were reused after profile/calendar/source audit, and four were newly simulated in L0/A0 seeds 43 and 47. The 10 reused positions are L0/A0 seed 41 (two treatments), L1/A1 seed 41 (two), and L2/A1 seeds 41/43/47 (six).

| Cell/seed | TAS | Gates open | Paired calendar | Result |
|---|---:|---:|---|---|
| L0/A0, 41 | reused, pass | reused, pass | same signature | zero losses, queue drops and misses |
| L0/A0, 43 | new, pass | new, pass | same signature | zero losses, queue drops and misses |
| L0/A0, 47 | new, pass | new, pass | same signature | zero losses, queue drops and misses |
| L1/A1, 41 | reused, pass | reused, pass | same signature | zero losses, queue drops and misses |
| L2/A1, 41/43/47 | reused, pass | reused, pass | same within each seed | zero losses, queue drops and misses |

The new L0/A0 pair offered 2,293,533 packets in seed 43 and 2,271,537 in seed 47; both treatments within each seed share the calendar signature and offered population. The seed-41 pair has the same paired treatment property. Across the three L0/A0 seeds, TAS and noTAS have identical aggregate packet-loss, deadline-miss, overflow-drop and maximum packet-latency values. For example, the maximum F08/F09/F10 latencies are approximately 77.8–78.1 µs with TAS and 30.4–31.4 µs with gates open; both are below their applicable deadlines, with no misses. F06/F07 maxima are the same between treatments (about 56–59 µs). F21/F22 also show higher latency under TAS (about 157–162 µs versus 106–115 µs in the listed L0/A0 seeds), with no misses. Detailed per-flow/receptor packet and image metrics remain in the per-run reports embedded in [pilot_results.json](pilot_results.json).

For L1/A1 seed 41 and L2/A1 seeds 41/43/47, both paired treatments pass with zero overflow; the source reports include all flow/receptor and queue metrics. C3 comparisons are separate because they use load-scaled C3 reservations; the existing seed-41 controls fail as described above.

## Coverage and interruption

The matrix has 48 positions total: 14 usable, 12 L3 analytical rejections, 20 not run, one incomplete TAS attempt, and its matched noTAS treatment not started. The L1/A1 seed-43 TAS attempt stopped at simulation time 19.360009212 s after the projected output threatened the disk floor. Its 57 retained artifacts (7.56 GB before compression, 1.35 GB compressed) are listed with round-trip hashes in `partial_attempt_retention.json`; no final gate result exists, so it is **not** a methodological result. No performance failure was observed before the stop, and no replacement was started.

The isolated pilot directory currently occupies about 7.9 GB. At the checkpoint, free disk was 49.84 GiB and available memory 9.63 GiB. The corrected conservative projection requires 58.875 GiB before starting the first remaining L1/A1 pair (40 GiB floor + 4.875 GiB retained-pair estimate + 14 GiB temporary headroom). The cleanup operation later raised free space to 114.62 GiB (9.63 GiB available memory), above the corrected threshold. The pilot remains paused and no simulator or campaign runner was auto-started. It can be manually resumed after reviewing the corrected runner addendum; do not overwrite the partial attempt. The runner correction fixed omitted phase-1 crosschecks, added sampled-sync to stop conditions, and raised temporary-output estimates. It did not change the frozen profile, workload, protocol or search.

## Recommendation

Do **not** freeze this as P1’s C4 policy yet. Retain it as a promising absolute-reservation candidate, with empirical support for L0/A0, L1/A1 seed 41, and L2/A1. Complete the preregistered crosschecks and conditional cells only when the storage floor can be respected. If TAS brings no clear benefit against gates-open in a cell while increasing brake and transient latency, the P1 revision should state the purpose TAS serves and retain the matched noTAS control. The current evidence does not show C4 superiority over C3 and does not support an official C4 campaign.

Files: [protocol.md](protocol.md), [manifest.json](manifest.json), [matrix.csv](matrix.csv), [results/checkpoint.json](results/checkpoint.json), [results/runs.jsonl](results/runs.jsonl), [pilot_results.json](pilot_results.json), and [runner_correction_addendum.json](runner_correction_addendum.json).
