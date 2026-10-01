# C0 P1 audit results

The complete seed-41 audit covers all eight `L0–L3 × A0–A1` cells with a 1 s
warm-up, 30 s measurement window and 50 ms drain. Each cell passed the
configuration checks for 42 egress interfaces and 336 per-class queues,
including PCP→TC mapping, strict-priority order, open gates, DropTail and the
P1 byte capacities. Queue growth checks found no sustained growth. There were
zero packet drops in every cell, including all four camera talkers.

## Cell results

| Cell | Offered packets | Drops | Hard-critical flows with deadline misses | P1 viability |
|---|---:|---:|---|---|
| L0/A0 | 2,275,881 | 0 | none | Viable |
| L0/A1 | 2,275,911 | 0 | F01 1.874% | Not viable |
| L1/A0 | 2,886,020 | 0 | F01 0.152% | Not viable |
| L1/A1 | 2,886,080 | 0 | F01 4.375% | Not viable |
| L2/A0 | 4,716,437 | 0 | F01 7.729%; F06 6.113%; F07 6.176% | Not viable |
| L2/A1 | 4,716,467 | 0 | F01 14.998%; F06/F07 12.499% each | Not viable |
| L3/A0 | 6,546,854 | 0 | F01 25.764%; F06/F07 12.500% each | Not viable |
| L3/A1 | 6,546,854 | 0 | F01 33.096%; F06/F07 31.250% each | Not viable |

F01 and F06/F07 are `high-hard`, as specified by the updated catalog and the
user's classification decision. C0 meets the P1 viability gate in 1/8 cells;
all other cells fail because of hard-deadline misses, not packet loss. F02–F05
generate complete camera bursts and have no talker queue overflow with the
corrected 64 KiB per-class capacity.

The earlier apparent 30% loss was caused by the former 32 KiB camera talker
queues. Those historical runs are not part of this corrected comparison. The
current 64 KiB camera talker queues, 128 KiB G1–G4 bottleneck queues, and 32 KiB
other queues match the corrected P1 profile.

The latency audit found a nearest-rank p99 calculation defect: the old heap
grew with the number of samples while reading time-ordered vectors, retaining
early low-latency values and understating p99. The fixed-size upper-tail heap
now uses the expected cohort size, and vector sample counts, maxima and
deadline misses reconcile with receiver CSVs. For C0/L3/A1, the corrected
metrics for the 100 µs flows are:

| Flow | Deadline misses | p99 | Maximum |
|---|---:|---:|---:|
| F01 | 397,150 / 1,200,000 (33.096%) | 578.356 µs | 591.020 µs |
| F06 | 37,500 / 120,000 (31.250%) | 383.756 µs | 396.556 µs |
| F07 | 37,500 / 120,000 (31.250%) | 379.428 µs | 379.428 µs |

For camera flows, packet latency remains the time from an individual frame's
release to reception. The P1 deadline gate separately uses image completion:
availability of the image to reception of its last one of 30 frames. C0's
unshaped frames share an image release time; C1's image metric includes the
pre-shaping spacing. The two measurements are not interchangeable.

The full machine-readable report, including per-flow goodput, packet loss,
latency, queue occupancy and queueing metrics, is generated at
`simulations/results/C0/p1-validation-64KiB/C0_acceptance.json`. The paired C0/C1
analysis is at `simulations/results/C1/p1-validation-64KiB/`.

Seed 41 is the engineering audit seed. It does not replace the final campaign
of 30 repetitions with seeds 1001–1030.
