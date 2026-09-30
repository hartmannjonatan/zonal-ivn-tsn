# C0 P1 audit results

The full-duration acceptance audit ran all eight `L0–L3 × A0–A1` cells with
seed 41, 1 s warm-up, 30 s measurement and 50 ms drain. Each cell passed the
technical checks for 42 egress interfaces and 336 per-class queues, including
PCP→TC mapping, strict-priority order, open gates, DropTail, configured byte
capacity, queue activity, queueing-time histograms and link-utilization
histograms. No queue was classified as having sustained growth after warm-up.

## Cell results

| Cell | Offered packets | Recorded drops | Sustained-growth queues | P1 viability |
|---|---:|---:|---:|---|
| L0/A0 | 2,275,881 | 34,875 | 0 | Not viable |
| L0/A1 | 2,275,911 | 34,884 | 0 | Not viable |
| L1/A0 | 2,886,020 | 69,750 | 0 | Not viable |
| L1/A1 | 2,886,080 | 69,768 | 0 | Not viable |
| L2/A0 | 4,716,437 | 174,375 | 0 | Not viable |
| L2/A1 | 4,716,467 | 174,384 | 0 | Not viable |
| L3/A0 | 6,546,854 | 279,000 | 0 | Not viable |
| L3/A1 | 6,546,854 | 279,000 | 0 | Not viable |

No cell meets all P1 viability criteria (0/8). For this analysis, F01 and
F06/F07 are treated as `high-hard`, as directed, while the canonical traffic
catalog remains unchanged. Under this policy, hard-deadline misses occur in
F01 at L0/A1 and L1–L3 (up to 21.85%), and in F06/F07 at L2/A1 and L3 (up to
18.75%). F02/F03 also fail their hard deadline in every cell. The exact
hard-flow miss ratios by cell are:

| Cell | Hard-critical flows with misses (miss ratio) |
|---|---|
| L0/A0 | F02 30%; F03 30% |
| L0/A1 | F01 1.25%; F02 30%; F03 30% |
| L1/A0 | F02 30%; F03 30% |
| L1/A1 | F01 3.13%; F02 30%; F03 30% |
| L2/A0 | F01 2.66%; F02 30%; F03 30% |
| L2/A1 | F01 10.00%; F02 30%; F03 30%; F06 6.25%; F07 6.25% |
| L3/A0 | F01 14.31%; F02 30%; F03 30%; F06 6.25%; F07 6.25% |
| L3/A1 | F01 21.85%; F02 30%; F03 30%; F06 18.75%; F07 18.75% |

In every cell, F02–F05 lose
exactly 30% of offered packets at the transmitting queues of CAM1–CAM4 before
the frames reach the CSW. Each camera releases 30 frames of 1,496 bytes as one
image burst, while those access-port class queues have the P1 capacity of
32 KiB: 21 frames fit and the remaining 9 are dropped. As a result, F02/F03
miss the hard-deadline criterion, and F04/F05 exceed the 1% soft-deadline miss
limit. Their application goodput ratio is 0.70 and packet loss is 0.30 in all
eight cells. The loss is at the camera source ports, so it is not caused by
forwarding, multicast replication or an undersized CSW bottleneck queue.

The other hard-critical flows F08–F10 have zero misses in all cells. The
soft-deadline flows F11–F14 and F21/F22 meet the 1% miss criterion; both F14
multicast receivers are accounted for independently. F18–F20 meet the
best-effort thresholds with full measured payload goodput and no packet loss.

F01 and F06/F07 are an analysis override: the P1 catalog labels them `high`,
and this audit treats their 100 µs deadlines as hard-critical per the user's
decision. The override is recorded in `C0_acceptance.json` and can be applied
again without rerunning OMNeT++ using
`python3 scripts/run/validate_c0.py --reassess-existing`. The CSV catalog and
generated traffic configuration are unchanged.

## Interpretation and next step

C0 is now validated as a reproducible, structurally correct SP baseline, but it
is not a viable design treatment. Its dominant failure is the per-camera source
queue overflow caused by preserving the 30-frame burst. C1 should therefore
apply only the P1-defined source pre-shaping to F02–F05, preserve total packet
count, size, cycle, rate and deadlines, then repeat the same eight-cell audit
with the same hard-critical override. The comparison should check that source
drops disappear and track the effects on F01/F06/F07 latency and misses as well
as all existing P1 metrics.

Full per-flow and per-queue reports, including p99, maximum latency, deadline
misses, goodput, losses, six queue-occupancy windows and configuration evidence,
are generated under the ignored path
`simulations/results/C0/p1-validation/`. The consolidated machine-readable
report is `C0_acceptance.json`. Seed 41 is the engineering audit seed; the
30-repetition campaign with seeds 1001–1030 remains pending.
