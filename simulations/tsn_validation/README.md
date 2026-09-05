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
│   └── mc04_clock_drift_gptp_tas/
│   └── mc05_asynchronous_traffic_shaper/
│   └── mc06_per_stream_filtering_policing/
│   └── mc07_frame_preemption/
└── results/
    └── MC01/
    └── MC02/
    └── MC03/
    └── MC04/
    └── MC05/
    └── MC06/
    └── MC07/
```

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

## MC04 — Clock Drift, gPTP, and TAS

MC04 validates the dependency of multi-hop IEEE 802.1Qbv time-aware shaping on a common time base by correlating local-clock drift, gPTP synchronization, gate alignment, queueing delay, and end-to-end packet lifetime.

The scenario files are located in `./mc04_clock_drift_gptp_tas`, and the generated results are stored in `../results/MC04`.

A scheduled TC1 stream traverses two TAS-enabled switches. Both switches use a 1 ms cycle with a 200 µs TC1 window.

| Node       | gPTP role   | Nominal oscillator drift |
| ---------- | ----------- | -----------------------: |
| `source`   | Grandmaster |                  +20 ppm |
| `switch1`  | Bridge      |                  +80 ppm |
| `switch2`  | Bridge      |                  −80 ppm |
| `receiver` | Slave       |                  +40 ppm |

Five configurations are compared:

* `MC04IdealClocks`: all clocks are ideal and no synchronization is required.
* `MC04DriftNoGptp`: independent clock drift without synchronization.
* `MC04DriftGptp250us`: drift corrected by gPTP every 250 µs.
* `MC04DriftGptp1ms`: drift corrected by gPTP every 1 ms.
* `MC04DriftGptp5ms`: drift corrected by gPTP every 5 ms.

### Results

Without gPTP, the clock differences relative to the source reached approximately `+130 µs` at `switch1`, `−195 µs` at `switch2`, and `+42 µs` at the receiver after 2 seconds. The resulting separation between the switch clocks reached approximately `325 µs`, exceeding the 200 µs TC1 window and removing the overlap between their TAS gates.

The TC1 queueing delay at `switch2` began increasing at approximately 0.95 seconds and reached about `304 µs`. The average packet lifetime increased from `61.75 µs` with ideal clocks to `246.649 µs` without gPTP, an increase of `299.4%`, with a standard deviation of `392.016 µs`.

With gPTP, the residual clock error remained within a few nanoseconds, the gates at both switches remained aligned, the TC1 queueing delay was zero, and the packet lifetime returned to `61.75 µs` with zero variation. Synchronization intervals of 250 µs, 1 ms, and 5 ms produced the same deterministic traffic behavior for the drift and GCL used in this scenario.

The scenario confirms that unsynchronized clock drift can move packets outside downstream TAS windows, forcing them to wait for later cycles. It also validates gPTP as the required time base for deterministic multi-hop TAS in the project. The gPTP tree is configured manually because the INET model does not implement BMCA and supports only two-step synchronization; therefore, the experiment does not represent dynamic grandmaster selection or all hardware timestamping uncertainties.

## MC05 — Asynchronous Traffic Shaping (ATS)

MC05 validates IEEE 802.1Qcr asynchronous traffic shaping by correlating per-stream token state, eligibility time, egress release, queue growth, packet lifetime, and residence-time drops.

The scenario files are located in `./mc05_asynchronous_traffic_shaper`, and the generated results are stored in `../results/MC05`.

Two bursty streams share the same TC1 output queue. Each stream has an independent ingress `EligibilityTimeMeter` and `EligibilityTimeFilter`, while the egress uses a shared `EligibilityTimeQueue` and `EligibilityTimeGate`.

Five configurations are compared:

* `MC05NoAts`: eligibility-time metering and gating are disabled.
* `MC05AtsBase`: ATS with an aggressive-stream CIR of 10.46 Mbit/s.
* `MC05AtsHighCir`: the aggressive-stream CIR is increased to 20.92 Mbit/s.
* `MC05AtsLargeBurst`: the committed burst size is increased.
* `MC05AtsResidence2ms`: packets exceeding a 2 ms residence-time limit are discarded.

### Results

The independent token traces confirmed per-stream metering. In the base configuration, the remaining eligibility time reached approximately 800 µs, matching the expected spacing for a frame of about 1 kB at 10.46 Mbit/s. The queue and gate released packets only when their eligibility time was reached.

| Configuration         | Aggressive packets received | Mean packet lifetime |
| --------------------- | --------------------------: | -------------------: |
| `MC05NoAts`           |                         240 |           304.736 µs |
| `MC05AtsBase`         |                          63 |           18.2239 ms |
| `MC05AtsHighCir`      |                         124 |           12.3175 ms |
| `MC05AtsLargeBurst`   |                          69 |           15.6158 ms |
| `MC05AtsResidence2ms` |                          63 |           1.62392 ms |

The base and high-CIR configurations produced approximately 10.5 and 20.67 Mbit/s, respectively. Increasing the CIR reduced the final TC1 backlog from approximately 178 to 118 packets. Increasing the committed burst size released six additional packets without changing the long-term rate, confirming that CIR controls sustained traffic while burst size controls the initial allowance.

With `maxResidenceTime = 2 ms`, the aggressive filter received 240 packets, forwarded 63, and discarded 177 (`73.75%`). The reference stream still delivered all 96 packets without drops and maintained a mean lifetime between 114.264 and 133.744 µs across the ATS configurations, demonstrating per-stream isolation even though both streams shared TC1.

The aggressive offered load intentionally exceeds its configured CIR and the queues are unlimited, so backlog and latency growth without a residence-time limit are expected. Lifetime statistics include only packets received before the 50 ms simulation ended. Multihop ATS, admission control, analytical worst-case bounds, and interactions with TAS, CBS, or frame preemption are outside the scope of this scenario.

## MC06 — Per-Stream Filtering and Policing (PSFP)

MC06 validates IEEE 802.1Qci per-stream filtering and policing by correlating stream identification, token-meter state, green/red classification, ingress drops, shared-queue behavior, and the end-to-end latency of the protected stream.

The scenario files are located in `./mc06_per_stream_filtering_policing`, and the generated results are stored in `../results/MC06`.

Two streams share TC1 and the same 100 Mbit/s switch output link. UDP destination ports identify the streams at the sources, PCP values encode them on Ethernet, and the switch decodes their stream names before classification. Each stream then follows an independent `gate → SingleRateTwoColorMeter → LabelFilter` path. The meter assigns green or red labels according to CIR and CBS, while the filter discards red packets.

Three configurations are compared:

* `MC06NoPsfp`: the monitored source overruns the shared link without ingress policing.
* `MC06PsfpHealthy`: both streams remain within their contracts with PSFP enabled.
* `MC06PsfpFaulty`: the monitored source offers approximately 133.33 Mbit/s against a 40 Mbit/s CIR, simulating a babbling-idiot source.

### Results

When both sources were conformant, the healthy stream forwarded `120/120` packets and the monitored stream forwarded `229/229`, with no filter drops.

During the source-overrun experiment, the monitored-stream filter discarded `562` of approximately `800` packets (`70.25%`) and forwarded approximately `238`. The resulting payload throughput was about `39.67 Mbit/s`, closely matching its configured `40 Mbit/s` CIR. The healthy-stream filter discarded no packets.

Without PSFP, only `75/120` healthy packets reached the receiver by the end of the 50 ms simulation, and their mean packet lifetime increased to `9.5124 ms`. With PSFP enabled during the same failure, all `120/120` healthy packets arrived and their mean lifetime fell to `107.524 µs`, nearly identical to the conformant PSFP case (`107.82 µs`). This represents a `98.87%` reduction relative to the unprotected case.

The shared queue confirmed the isolation effect: without PSFP, it had already accumulated approximately `23` packets after 4 ms and exceeded `1.1 ms` of queueing time. With PSFP, it remained near `0–1` packet after the initial transient.

The scenario validates that INET 4.7.0 can identify, meter, mark, and discard traffic independently per stream before it reaches a shared egress queue. Its scope is limited to one switch, always-open stream gates, an unbounded egress queue, and two-color policing. Timed stream gates, three-color marking, maximum-SDU filtering, multihop PSFP, and dynamic reconfiguration are outside the scenario.

## MC07 — Frame Preemption

MC07 validates IEEE 802.1Qbu/802.3br frame preemption by measuring the blocking experienced when an express packet arrives during the transmission of a long preemptable packet.

The scenario files are located in `./mc07_frame_preemption`, and the generated results are stored in `../results/MC07`.

Two streams share the switch output link:

| Traffic     | VLAN | PCP | Payload | MAC category |
| ----------- | ---: | --: | ------: | ------------ |
| Preemptable |    1 |   0 |  1472 B | Preemptable  |
| Express     |    1 |   4 |    64 B | Express      |

Strict Priority and frame preemption are compared with the express packet generated 20 µs, 60 µs, or 100 µs after the preemptable packet.

### Results

Without preemption, the express queueing time was `114.624 µs`, `74.624 µs`, and `34.624 µs` for the 20 µs, 60 µs, and 100 µs offsets. The sum of the offset and queueing time remained constant at `134.624 µs`, confirming that Strict Priority cannot interrupt a frame already being transmitted.

With frame preemption, the express queueing time remained at `1.984 µs` for all three offsets. This removed `112.640 µs`, `72.640 µs`, and `32.640 µs` of blocking, corresponding to reductions of `98.27%`, `97.34%`, and `94.27%`.

The express packet lifetime consequently fell from `125.460 µs`, `85.460 µs`, and `45.460 µs` to a constant `12.820 µs`. The packet counters confirmed that one express and one preemptable packet were received in every execution, with no drops or duplicate application deliveries.

The PCAP trace showed the initial preemptable fragment marked with `SMD-S0`, followed by the inserted express frame and the continuation and reassembly of the interrupted frame. This confirms the complete fragmentation, insertion, and reconstruction path implemented by INET.

The scenario validates `EthernetPreemptingMacLayer`, its express `EthernetStreamingMacLayer`, the preemptable `EthernetFragmentingMacLayer`, and `EthernetPreemptingPhyLayer`. PCP classification directs each stream to the appropriate MAC category.

The experiment uses one switch, one packet per stream, and no continuous competing traffic. It validates INET’s frame fragmentation and reassembly model but does not reproduce complete hardware MAC Merge negotiation and verification. Combining preemption with TAS or CBS requires the corresponding queues, gates, and shapers to be placed inside the express or preemptable sub-MACs; enabling preemption flags alone is not sufficient.

