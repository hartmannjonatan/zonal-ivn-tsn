# TSN Validation Micro-scenarios

This directory contains minimal scenarios used to validate individual TSN mechanisms available in INET 4.7.0.

## Directory structure

```text
simulations/
├── omnetpp.ini
├── tsn_validation/
│   ├── README.md
│   └── mc01_pcp_strict_priority/
└── results/
    └── MC01/
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
