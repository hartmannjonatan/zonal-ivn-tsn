# TSN Validation Micro-scenarios

This directory contains minimal scenarios used to validate individual TSN mechanisms available in INET 4.7.0.

## Directory structure

```text
simulations/
├── ...
├── tsn_validation/
│   ├── README.md
│   └── mc01_pcp_strict_priority/
│   └── mc02_credit_based_shaper/
│   └── mc03_time_aware_shaper/
└── results/
    └── MC01/
    └── MC02/
    └── MC03/
```

- The NED files and scenario configuration are located in [`./mc01_pcp_strict_priority`](./mc01_pcp_strict_priority).
- Configurations are selected through `simulations/omnetpp.ini`.
- Generated results are stored in `../results/MC01`.

## MC01 — VLAN/PCP and Strict Priority

MC01 validates the application → stream → VLAN/PCP → traffic class → queue → `PriorityScheduler` path and verifies that high-priority traffic is served first when the switch output link is congested.

Two sources compete for the same output link to the receiver:

| Traffic | VLAN | PCP | Traffic class |
|---|---:|---:|---|
| Best effort (`sourceBe`) | 1 | 0 | TC0 |
| High priority (`sourceHp`) | 1 | 5 | TC1 |

Two configurations are compared:

- `MC01Fifo`: both traffic flows share a FIFO queue.
- `MC01StrictPriority`: traffic is classified into TC0 and TC1 and served using Strict Priority.

### Results

The IEEE 802.1Q headers were verified directly in the frames. With Strict Priority, the HP queue remained between 0 and 1 packet even while the BE backlog increased. The average HP packet lifetime decreased from `1.68187 ms` with FIFO to `84.7764 µs`, a reduction of `94.96%`.

The scenario confirms correct traffic classification and effective preference for HP traffic. Scheduling is non-preemptive: an HP frame must still wait for a BE frame that is already being transmitted.

## MC02 — Credit-Based Shaper (CBS)

MC02 validates IEEE 802.1Qav credit-based shaping and relates credit evolution, `idleSlope`/`sendSlope`, output rate, queue growth, and interference from competing best-effort traffic.

The scenario files are located in `./mc02_credit_based_shaper`, and the generated results are stored in `../results/MC02`.

Two sources compete for the same 100 Mbit/s switch output link:

| Traffic                  | VLAN | PCP | Traffic class | Offered payload |
| ------------------------ | ---: | --: | ------------- | --------------: |
| Best effort (`sourceBe`) |    1 |   0 | TC0           |      100 Mbit/s |
| Shaped (`sourceShaped`)  |    1 |   5 | TC1           |       80 Mbit/s |

Five configurations are compared:

* `MC02NoCbs`: TC1 uses Strict Priority without rate shaping.
* `MC02Cbs20`: CBS with `idleSlope = 20 Mbit/s`.
* `MC02Cbs40`: CBS with `idleSlope = 40 Mbit/s`.
* `MC02Cbs60`: CBS with `idleSlope = 60 Mbit/s`.
* `MC02Cbs40Sparse`: the offered shaped load is below `idleSlope`, allowing the queue to empty between packets.

### Results

The credit traces showed the expected positive and negative ramps. For the 100 Mbit/s output link, INET automatically calculated `sendSlope` as −80, −60, and −40 Mbit/s for the three CBS configurations. Negative credit temporarily blocked TC1, while the sparse case returned the credit to zero whenever its queue became empty.

The steady TC1 output rates were approximately 19.6, 39, and 58.8 Mbit/s for `idleSlope` values of 20, 40, and 60 Mbit/s. Without CBS, TC1 reached approximately 83.3 Mbit/s. Lower `idleSlope` values increased the TC1 backlog while releasing more output capacity to TC0.

The scenario confirms that CBS controls TC1 eligibility, while Strict Priority applies whenever TC1 is eligible. The total offered load intentionally exceeds the output-link capacity and the queues are unlimited, so backlog growth is expected. TAS guard bands and frame preemption are outside the scope of this scenario.

## MC03 — Manual Time-Aware Shaper (TAS)

MC03 validates manual IEEE 802.1Qbv time-aware shaping by correlating gate states, queue release times, queueing delay, and end-to-end packet lifetime.

The scenario files are located in `./mc03_time_aware_shaper`, and the generated results are stored in `../results/MC03`.

Two sources compete for the same 100 Mbit/s switch output link:

| Traffic                       | VLAN | PCP | Traffic class |
| ----------------------------- | ---: | --: | ------------- |
| Best effort (`sourceBe`)      |    1 |   0 | TC0           |
| Scheduled (`sourceScheduled`) |    1 |   5 | TC1           |

Seven configurations are compared:

* `MC03OpenGates`: both gates remain open, resulting in Strict Priority.
* `MC03TasManual`: 1 ms cycle with TC1 open for 100 µs and TC0 for 900 µs.
* `MC03TasWideWindow`: the TC1 window is increased to 200 µs.
* `MC03TasOffset250`: the schedule is shifted by 250 µs.
* `MC03TasCycle2ms`: a 2 ms cycle with a 200 µs TC1 window.
* `MC03TasLateArrival`: TC1 packets arrive immediately after their window closes.
* `MC03TasNoGuardBand`: the implicit TC0 guard band is disabled.

### Results

The gate-state and queue-release traces confirmed that each class transmitted only during its configured windows. With aligned manual TAS, the average TC1 packet lifetime decreased from `52.8737 µs` with open gates to `17.48 µs`, a reduction of `66.94%`, while its standard deviation fell from `34.4676 µs` to zero.

The offset and late-arrival configurations produced deterministic lifetimes of `765.78 µs` and `905.78 µs`, confirming that packets arriving outside their window wait for the next gate opening. Disabling the guard band restored the latency variation observed with open gates, demonstrating that a non-preemptive BE frame can extend into the TC1 window.

The scenario validates manual GCL configuration through `initiallyOpen`, `durations`, and `offset`, as well as INET’s implicit guard-band behavior. It uses one switch and a perfect simulation clock; multi-switch synchronization, clock drift, gPTP, automatic GCL scheduling, and frame preemption are outside its scope.

