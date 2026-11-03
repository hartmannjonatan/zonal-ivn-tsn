# 10BASE-T1S variant (ZonalIVNT1S) — C0 comparison

`networks/ZonalIVNT1S.ned` is a copy of `ZonalIVN` (unchanged). In each zone, the
dedicated 100 Mb/s WINDOW and RADAR links are replaced by one 10BASE-T1S
segment: a zonal switch port using `EthernetPlcaInterface` connected via
`EthernetMultidropLink` to a `WireJunction`, with the endpoints attached the
same way (pattern of `simulations/t1s_feasibility`).

| Zone | ZSW T1S port | Segment (PLCA node ID) | plca_node_count | Other port changes |
|---|---|---|---|---|
| Z1 | eth5 | ZSW 0, WINDOW1 1 | 2 | none |
| Z2 | eth2 | ZSW 0, RADAR1 1, WINDOW2 2 | 3 | AUDIO2 eth5, DISPLAY2 eth6, BE2 eth7 (6 access ports) |
| Z3 | eth2 | ZSW 0, RADAR2 1, WINDOW3 2 | 3 | AUDIO3 eth6, BE3 eth7 (6 access ports) |

Z1 has no radar; WINDOW1 takes ID 1 so that `plca_node_count` equals the number
of nodes and no empty transmit opportunity is added. All segments: 10 Mb/s,
`to_timer_length = 32b`, `max_bc = 0`.

`configs/t1s.ini` (entry point `simulations/zonal_t1s.ini`, which includes the
unchanged `omnetpp.ini`):

- `T1SNetwork`: network, bitrates, PLCA parameters, static
  `macTable.forwardingTable` for Z2/Z3 with the renumbered ports (generated
  from `catalog-bindings.ini`; Z1 is unchanged).
- PCP strict priority on T1S: the `queue` submodule of `EthernetPlcaInterface`
  (default `EthernetQueue`, FIFO) is replaced on the switch T1S ports and the
  radar talkers by `Ieee8021qTimeAwareShaper` with gates always open, identity
  PCPn→TCn mapping, `reverseOrder = true`, drop-tail 32 KiB/TC (same as the
  100 Mb/s access ports and radar talkers in C0). The outer 1000-packet limit
  that `EthernetPlcaInterface` sets by default is removed. TrafficAudit checks
  that every queued frame enters the TC equal to its PCP, and it did on all T1S
  queues. WINDOW endpoints are receive-only and keep the default queue.
- `C0_L1_A0_2s`: C0 on ZonalIVN, L1, A0, warm-up 1 s, measurement 2 s,
  seeds 1001–1003 (the first three P1 final seeds). `T1S_C0` is the same on
  ZonalIVNT1S.
- Workaround: with INET master, `PacketTransmitter`/`PacketReceiver` declare
  `@statistic[propagationTime]` without the signal, so C0 (statistic-recording
  on) aborts at setup. Both paired configs set
  `**.propagationTime.statistic-recording = false`.

Limitation: TrafficAudit only audits wire transmissions at
`phyLayer.outboundEmitter`, so frames on the T1S segments are not in
`wire.csv` (their queues and the 1 Gb/s hops are audited).

```bash
cd simulations
for c in C0_L1_A0_2s T1S_C0; do
  ../src/zonal-ivn-tsn -n ".:../src:../tests:$INET_ROOT/src" -f zonal_t1s.ini -u Cmdenv -c $c
done
cd ..
python3 scripts/run/compare_t1s.py
```

## Result (OMNeT++ 6.4.0, INET master 7b0a6de5ce, 3 seeds pooled)

Mean and nearest-rank p99 from the application `latency` vectors (measured
cohort), max and deadline misses from the receiver CSVs, losses = talker minus
receiver measured packets, drops from TrafficAudit `drops.csv`.

| Flow | Rx | Deadline µs | Mean µs C0 → T1S | p99 µs C0 → T1S | Max µs C0 → T1S | Lost C0/T1S | Misses C0/T1S | Drops C0/T1S |
|---|---|---|---|---|---|---|---|---|
| F01 | HPC | 100 | 38.06 → 38.06 | 48.73 → 48.73 | 59.44 → 59.44 | 0/0 | 0/0 | 0/0 |
| F02 | HPC | 10000 | 248.99 → 249.02 | 474.88 → 474.88 | 499.13 → 499.13 | 0/0 | 0/0 | 0/0 |
| F03 | HPC | 10000 | 244.39 → 244.22 | 451.13 → 451.13 | 451.55 → 451.55 | 0/0 | 0/0 | 0/0 |
| F04 | HPC | 30000 | 244.38 → 244.21 | 451.13 → 451.13 | 451.13 → 451.13 | 0/0 | 0/0 | 0/0 |
| F05 | HPC | 30000 | 244.37 → 244.21 | 451.13 → 451.13 | 451.13 → 451.13 | 0/0 | 0/0 | 0/0 |
| F06 | HPC | 100 | 19.70 → 67.54 | 30.08 → 78.59 | 30.49 → 90.92 | 0/0 | 0/0 | 0/0 |
| F07 | HPC | 100 | 15.44 → 67.54 | 25.08 → 73.80 | 25.08 → 74.00 | 0/0 | 0/0 | 0/0 |
| F08 | BRAKE1 | 100 | 7.89 → 7.89 | 24.81 → 24.81 | 30.41 → 30.41 | 0/0 | 0/0 | 0/0 |
| F09 | BRAKE2 | 100 | 8.27 → 8.27 | 23.61 → 23.61 | 30.81 → 30.81 | 0/0 | 0/0 | 0/0 |
| F10 | BRAKE3 | 100 | 13.68 → 13.68 | 27.81 → 27.81 | 31.42 → 31.42 | 0/0 | 0/0 | 0/0 |
| F11 | AUDIO1 | 10000 | 26.98 → 26.98 | 42.38 → 42.38 | 47.98 → 47.98 | 0/0 | 0/0 | 0/0 |
| F12 | AUDIO2 | 10000 | 47.04 → 47.04 | 57.27 → 57.27 | 58.87 → 58.87 | 0/0 | 0/0 | 0/0 |
| F13 | AUDIO3 | 10000 | 35.07 → 35.07 | 45.38 → 45.38 | 57.04 → 57.04 | 0/0 | 0/0 | 0/0 |
| F14 | DISPLAY1 | 30000 | 151.11 → 151.11 | 161.34 → 161.34 | 162.94 → 162.94 | 0/0 | 0/0 | 0/0 |
| F14 | DISPLAY2 | 30000 | 151.11 → 151.11 | 161.34 → 161.34 | 162.94 → 162.94 | 0/0 | 0/0 | 0/0 |
| F15 | WINDOW1 | 50000 | 7.93 → 64.68 | 25.21 → 81.76 | 30.81 → 90.89 | 0/0 | 0/0 | 0/0 |
| F16 | WINDOW2 | 50000 | 7.93 → 73.90 | 25.01 → 109.63 | 30.61 → 110.21 | 0/0 | 0/0 | 0/0 |
| F17 | WINDOW3 | 50000 | 8.22 → 74.14 | 24.81 → 109.64 | 42.75 → 110.22 | 0/0 | 0/0 | 0/0 |
| F18 | BE1 | 0 | 148.34 → 148.34 | 166.56 → 166.56 | 168.16 → 168.16 | 0/0 | 0/0 | 0/0 |
| F19 | BE2 | 0 | 148.33 → 148.33 | 166.56 → 166.56 | 168.16 → 168.16 | 0/0 | 0/0 | 0/0 |
| F20 | BE3 | 0 | 148.62 → 148.62 | 166.56 → 166.56 | 173.22 → 173.22 | 0/0 | 0/0 | 0/0 |
| F21 | Z3.ZCPU | 10000 | 51.81 → 51.81 | 118.42 → 118.42 | 159.19 → 159.19 | 0/0 | 0/0 | 0/0 |
| F22 | Z3.ZCPU | 10000 | 50.00 → 50.00 | 73.06 → 73.06 | 99.92 → 99.92 | 0/0 | 0/0 | 0/0 |

- Radar (F06/F07, deadline 100 µs): mean +48/+52 µs, max 90.9/74.0 µs. No
  misses, but the margin shrinks to ~9 µs. The extra delay is 10 Mb/s
  serialization of a 72-byte frame (~58 µs) plus waiting for the PLCA transmit
  opportunity.
- Window (F15–F17, deadline 50 ms): mean 8 → 65–74 µs, max ≤ 110 µs, far
  below the deadline. Z2/Z3 are worse than Z1 because the segment has one more
  node (the cycle is longer) and radar frames share it.
- No losses or queue drops in either network.
- Other flows: packet counts are identical. F01, F08–F14 and F18–F22 are
  bit-identical. Cameras F02–F05 change by ≤ 0.17 µs in the mean (p99/max
  unchanged), because the radar frames now reach the shared uplinks
  (ZSW eth0 → CSW → HPC) ~50 µs later and interleave differently with the
  camera bursts.

Run time: 6 runs in parallel, 162 s wall (C0 ~145 s, T1S ~160 s per run).

## Step 1 — radar worst case on T1S

### Alignment A1 (L1, seeds 1001–1003, `T1S_C0_A1` vs `C0_L1_A1_2s`)

A1 only changes the camera phases (and the F22 transient start); radar and
window offsets are fixed in the catalog. Radar on T1S: F06 mean 67.2 µs,
p99 90.0, max 90.7 µs; F07 mean 67.1, p99 85.7, max 85.7 µs (C0 A1: max
42.2 / 37.2 µs). Window F15–F17 max 90.9 / 110.2 / 114.5 µs. No losses,
drops or misses. All non-T1S flows are identical to C0 A1 except the camera
means (≤ 3.9 µs on F02 because of the shifted radar arrival on the shared
uplink; p99/max unchanged). Full table:
`python3 scripts/run/compare_t1s.py --base C0_L1_A1_2s:results/t1s/C0_A1:ZonalIVN --t1s T1S_C0_A1:results/t1s/T1S_C0_A1:ZonalIVNT1S`.

### Radar phase sweep (`T1S_RadarPhase`, `scripts/run/t1s_radar_phase.py`)

The catalog offsets (F06 20 µs, F07 25 µs) are replaced by one common radar
offset, 0–195 µs in 5 µs steps (one 200 µs window period; the 1 ms radar
period is a multiple of it, so the radar/window phase is fixed within a run).
L1/A0, seed 1001, 1 s warm-up + 1 s measurement (1000 radar packets per
flow and offset). Everything else is as in T1S_C0.

| Radar offset µs | F06 max µs | F06 misses /1000 | F07 max µs | F07 misses /1000 |
|---|---|---|---|---|
| 0 | 86.7 | 0 | 85.8 | 0 |
| 5 | 81.9 | 0 | 81.7 | 0 |
| 10 | 89.0 | 0 | 87.9 | 0 |
| 15 | 84.0 | 0 | 83.6 | 0 |
| 20 | 90.9 | 0 | 78.8 | 0 |
| 25 | 86.1 | 0 | 85.0 | 0 |
| 30 | 82.2 | 0 | 80.9 | 0 |
| 35 | 88.3 | 0 | 87.2 | 0 |
| 40 | 83.3 | 0 | 83.1 | 0 |
| 45 | 102.7 | 1 | 90.0 | 0 |
| 50 | 146.6 | 268 | 85.0 | 0 |
| 55 | 152.9 | 644 | 144.4 | 206 |
| 60 | 148.4 | 956 | 147.9 | 591 |
| 65 | 143.4 | 975 | 143.4 | 906 |
| 70 | 143.0 | 982 | 138.4 | 961 |
| 75 | 145.5 | 994 | 145.3 | 985 |
| 80 | 140.3 | 997 | 140.3 | 991 |
| 85 | 135.1 | 1000 | 135.5 | 999 |
| 90 | 130.3 | 776 | 154.5 | 1000 |
| 95 | 125.3 | 467 | 137.2 | 825 |
| 100 | 120.3 | 135 | 132.2 | 425 |
| 105 | 115.3 | 116 | 127.2 | 241 |
| 110 | 110.3 | 15 | 122.2 | 42 |
| 115 | 105.3 | 9 | 117.2 | 23 |
| 120 | 100.3 | 4 | 112.2 | 13 |
| 125 | 95.3 | 0 | 107.2 | 1 |
| 130 | 90.3 | 0 | 102.2 | 1 |
| 135 | 85.3 | 0 | 97.2 | 0 |
| 140 | 81.5 | 0 | 92.2 | 0 |
| 145 | 92.7 | 0 | 87.2 | 0 |
| 150 | 94.5 | 0 | 94.5 | 0 |
| 155 | 90.0 | 0 | 89.5 | 0 |
| 160 | 85.0 | 0 | 84.5 | 0 |
| 165 | 91.9 | 0 | 91.7 | 0 |
| 170 | 86.9 | 0 | 86.7 | 0 |
| 175 | 82.1 | 0 | 82.3 | 0 |
| 180 | 89.0 | 0 | 88.1 | 0 |
| 185 | 84.2 | 0 | 84.0 | 0 |
| 190 | 80.8 | 0 | 79.4 | 0 |
| 195 | 85.9 | 0 | 85.3 | 0 |

- Worst case: F06 152.9 µs at offset 55 µs; F07 154.5 µs at offset 90 µs.
  This is about 50 % above the 100 µs deadline.
- Misses appear for offsets 45–120 µs (F06) and 55–130 µs (F07). Between
  about 65 and 90 µs almost every radar packet misses. There are no losses.
- The catalog offsets (20/25 µs) are in the safe region, which is why
  T1S_C0 showed max ≈ 91 µs. The 100 µs deadline is met only because of the
  chosen phase.
- The bad band starts when the radar becomes ready just after the window
  frame for that zone (F15/F16/F17 at 50/55/60 µs from HPC) reaches the
  coordinator. The radar then waits for the coordinator's ~67 µs window frame
  before its own ~58 µs frame. The worst value is ~28 µs above the estimate
  (67 + 58 + hops ≈ 125 µs). This is consistent with also missing the radar's
  own transmit opportunity (rest of the PLCA cycle + beacon) and queueing on
  the 1 Gb/s hops, but it was not traced packet by packet.

Run time step 1: 6 A1 runs + 40 sweep runs (8 parallel) in 733 s wall.

## Step 2 — brake on the T1S segment (stress case)

`networks/ZonalIVNT1SBrake.ned` puts BRAKEx on its zone's segment as well
(Z1: {ZSW 0, WINDOW1 1, BRAKE1 2}, Z2/Z3: {ZSW 0, RADAR 1, WINDOW 2,
BRAKE 3}; port map in the NED header; tables in config `T1SBrakeNetwork`).
`T1S_BRAKE` is C0, L1/A0, 2 s, seeds 1001–1003. `T1S_BRAKE_BC3` is the same
with PLCA burst mode `max_bc = 3` on the coordinator ports only. Both record
queue occupancy of every PLCA queue. `ZonalIVNT1S` now takes the segment
sizes as NED parameters (`plcaNodeCountZ1..Z3`, same defaults). A regression
run of T1S_C0 seed 1001 after this change gives byte-identical receiver CSVs.

Downstream demand on each segment is brake 64 B / 100 µs (PCP7) + window
64 B / 200 µs (PCP3) = 15 000 frames/s, all from the coordinator. Without burst
the coordinator gets one frame per PLCA cycle, and a cycle with one frame is
≈ 67 µs + beacon + the other nodes' empty TOs. That serves fewer than
15 000 frames/s, so strict priority starves the window class.

Results: 3 seeds pooled, 60 000 brake, 30 000 window and 6 000 radar
measured packets per flow.

| Flow | T1S_BRAKE mean / p99 / max µs | misses | lost | T1S_BRAKE_BC3 mean / p99 / max µs | misses | lost |
|---|---|---|---|---|---|---|
| F06 radar Z2 | 165.0 / 200.3 / 217.7 | 6000 (100 %) | 0 | 267.5 / 401.5 / 419.0 | 6000 (100 %) | 0 |
| F07 radar Z3 | 164.5 / 207.2 / 219.5 | 6000 (100 %) | 0 | 267.1 / 401.2 / 414.0 | 6000 (100 %) | 0 |
| F08 brake Z1 | 110.1 / 148.5 / 170.7 | 37 710 (63 %) | 0 | 98.4 / 137.6 / 158.4 | 28 629 (48 %) | 0 |
| F09 brake Z2 | 111.1 / 200.0 / 225.9 | 35 742 (60 %) | 0 | 109.7 / 199.9 / 226.0 | 34 005 (57 %) | 0 |
| F10 brake Z3 | 115.4 / 200.1 / 227.2 | 39 457 (66 %) | 0 | 114.9 / 204.2 / 225.3 | 37 825 (63 %) | 0 |
| F15 window Z1 | 179 069 / 185 914 / 186 010 | 16 425 | 13 473 (45 %) | 120 243 / 123 001 / 123 079 | 24 741 | 5 016 (17 %) |
| F16 window Z2 | 153 949 / 158 983 / 158 999 | 19 158 | 10 665 (36 %) | 141 700 / 145 886 / 145 905 | 20 865 | 8 928 (30 %) |
| F17 window Z3 | 153 971 / 158 991 / 159 002 | 19 158 | 10 665 (36 %) | 141 721 / 145 894 / 145 904 | 20 865 | 8 928 (30 %) |

PLCA coordinator queues (max over seeds, mean time-average):
- TC3 (window) is full in every zone and both variants: 512 packets = 32 KiB,
  ≈ 32.2 KB time-average. Every loss is a TC3 tail drop at the T1S port.
  T1S_BRAKE: 18 672 / 14 463 / 14 466 drops at Z1/Z2/Z3, whole run.
  T1S_BRAKE_BC3: 5 988 / 11 856 / 11 859.
- TC7 (brake) peaks at 2 packets (≈ 25 B average). Brake is never dropped,
  but it misses its 100 µs deadline in 48–66 % of packets.
- TC0 shows a single packet in Z1/Z2. It is not a catalog frame, because
  TrafficAudit's queues.csv has no catalog flow in TC0 there.

Observations:
- Brake, window and radar together do not fit on one 10 Mb/s PLCA segment.
  All three critical classes fail. Radar misses in 100 % of packets, because
  it must now wait for a brake frame (and often a window frame) every cycle.
- Burst mode (`max_bc = 3` on the coordinator) moves capacity downstream. The
  Z1 brake improves (misses 63 → 48 %) and window losses fall. But the radar
  waits behind up to four coordinator frames, so its max doubles
  (≈ 218 → 419 µs). In Z2/Z3 the brake barely changes. Burst does not make
  the segment feasible.

## Step 3 — more nodes per segment (extension, not part of the P1 catalog)

`networks/ZonalIVNT1SExtra.ned` extends ZonalIVNT1S with `extraNodes`
additional TsnDevices per segment (`X1[]`, `X2[]`, `X3[]`). They take the next
PLCA IDs, and `plca_node_count` is adjusted. Segment sizes for
extraNodes = 0 / 2 / 5 are 3 / 5 / 8 nodes in Z2/Z3 and 2 / 4 / 7 in Z1.
The extra nodes send UDP to HPC on VLAN 30, PCP 0, with a static forwarding
entry in every zonal switch and the CSW. The start phase is random per node
and seed. Two profiles:

- `T1S_EXTRA_SENSOR`: 14 B payload (64 B frame) every 1 ms per node.
- `T1S_EXTRA_HEAVY`: 1472 B payload (1518 B frame, ≈ 1.2 ms on the wire)
  every 10 ms per node.

Both run C0, L1/A0, 2 s, seeds 1001–1003; summarize them with
`scripts/run/t1s_stress.py`. Every extra-node packet sent after warm-up
reached HPC (sensor 36 900 / 92 250, heavy 3 690 / 9 225 for 2 / 5 extra
nodes). extraNodes = 0 reproduces T1S_C0 exactly.

Radar max µs, misses out of 6 000; window max µs, losses out of 30 000:

| Profile | Nodes Z2/Z3 (Z1) | F06 max / misses | F07 max / misses | F15 max / lost | F16 max / lost | F17 max / lost |
|---|---|---|---|---|---|---|
| — | 3 (2) | 90.9 / 0 | 74.0 / 0 | 90.9 / 0 | 110.2 / 0 | 110.2 / 0 |
| sensor | 5 (4) | 225.0 / 2 000 | 97.2 / 0 | 146.7 / 0 | 177.1 / 0 | 160.8 / 0 |
| sensor | 8 (7) | 225.0 / 2 702 | 195.8 / 2 001 | 217.5 / 0 | 239.6 / 0 | 283.9 / 0 |
| heavy | 5 (4) | 1 382.6 / 2 600 | 1 329.8 / 2 600 | 1 795.7 / 0 | 2 295.0 / 0 | 1 330.3 / 0 |
| heavy | 8 (7) | 1 974.5 / 6 000 | 4 268.7 / 6 000 | 107 422 / 1 182 | 138 133 / 8 395 | 138 172 / 8 420 |

Means (µs): F06 67.6 → 113.1 → 128.9 (sensor) and → 251.0 → 724.9 (heavy).
F16 73.9 → 83.6 → 117.3 (sensor) and → 448.3 → 135 824 (heavy).

Observations:
- Sensor nodes (64 B / 1 ms) cost one ~58 µs frame plus a TO per node and
  cycle. With 5 nodes on the segment, one seed (2 000 packets, i.e. every
  packet of that seed) already misses the radar deadline, at ≈ 225 µs. The
  outcome depends on phase, as in step 1. With 8 nodes both radars miss in
  some seeds, and the window stays well within 50 ms.
- A single 1518 B frame occupies the medium for ≈ 1.2 ms, more than 10× the
  radar deadline. With heavy participants the radar misses in 43 %
  (5 nodes) to 100 % (8 nodes) of packets, with max 1.3–4.3 ms.
- With 8 heavy nodes, the coordinator's single TO per (now long) cycle no
  longer carries the 5 000 window frames/s. TC3 fills (512 pk), and windows
  lose 4–28 % with ≈ 107–138 ms latency.
- Upstream traffic from the extra nodes is never lost: each node has its own
  TO and a low duty cycle.

## Step 4 — validation of the original C0 against the official campaign

Config `Validate_C0_L1_A0_P1seeds` (`zonal/configs/c0_reference.ini`, included
by `zonal_t1s.ini`) extends the unmodified `Validate_C0_L1_A0`: 1 s warm-up,
30 s measurement, 50 ms drain, the campaign's vector recording. It adds only
seeds 1001–1005, a result directory and
`**.propagationTime.statistic-recording = false` (INET master). Run 4 in
parallel (≈ 140 MB RSS each, ≈ 19 min per run, 2 225 s wall). Report:
`python3 scripts/run/validate_c0_reference.py`.

**Match with the repository's official campaign results (INET 4.7.0): exact.**
- `analysis/icit2027_publication_assets_2026-10-27/fig2_critical_latency_runs.csv`
  (F06–F10 per seed): offered, lost, misses, p99 and max are identical for all
  25 seed × flow rows (0 mismatches, p99/max to 1 ns).
- `analysis/icit2027_editorial_synthesis_2026-10-27/selected_run_metrics.csv`:
  offered and received packets (e.g. 2 941 003 for seed 1001), offered and
  complete images (7 500/7 500), and the critical non-camera p99/max
  (48.732 / 59.436 µs) are identical for every seed.

So this INET master build reproduces the official C0 results bit for bit,
and the propagationTime workaround does not affect them.

All 22 flows, seeds 1001–1005 pooled (30 s), against the 2 s baseline
(`C0_L1_A0_2s`, seeds 1001–1003). There are no losses or deadline misses in
either:

| Flow | Rx | Deadline µs | Received | Lost | Misses | p99 µs (30 s / 2 s) | Max µs (30 s / 2 s) |
|---|---|---|---|---|---|---|---|
| F01 | HPC | 100 | 1500000 | 0 | 0 | 48.73 / 48.73 | 59.44 / 59.44 |
| F02 | HPC | 10000 | 281250 | 0 | 0 | 474.88 / 474.88 | 499.13 / 499.13 |
| F03 | HPC | 10000 | 281250 | 0 | 0 | 451.13 / 451.13 | 451.55 / 451.55 |
| F04 | HPC | 30000 | 281250 | 0 | 0 | 451.13 / 451.13 | 451.13 / 451.13 |
| F05 | HPC | 30000 | 281250 | 0 | 0 | 451.13 / 451.13 | 451.13 / 451.13 |
| F06 | HPC | 100 | 150000 | 0 | 0 | 30.08 / 30.08 | 30.49 / 30.49 |
| F07 | HPC | 100 | 150000 | 0 | 0 | 25.08 / 25.08 | 25.08 / 25.08 |
| F08 | BRAKE1 | 100 | 1500000 | 0 | 0 | 24.81 / 24.81 | 30.41 / 30.41 |
| F09 | BRAKE2 | 100 | 1500000 | 0 | 0 | 23.61 / 23.61 | 30.81 / 30.81 |
| F10 | BRAKE3 | 100 | 1500000 | 0 | 0 | 27.55 / 27.81 | 31.75 / 31.42 |
| F11 | AUDIO1 | 10000 | 750000 | 0 | 0 | 42.38 / 42.38 | 47.98 / 47.98 |
| F12 | AUDIO2 | 10000 | 750000 | 0 | 0 | 57.27 / 57.27 | 58.87 / 58.87 |
| F13 | AUDIO3 | 10000 | 750000 | 0 | 0 | 45.34 / 45.38 | 58.20 / 57.04 |
| F14 | DISPLAY1 | 30000 | 750000 | 0 | 0 | 161.34 / 161.34 | 162.94 / 162.94 |
| F14 | DISPLAY2 | 30000 | 750000 | 0 | 0 | 161.34 / 161.34 | 162.94 / 162.94 |
| F15 | WINDOW1 | 50000 | 750000 | 0 | 0 | 25.21 / 25.21 | 30.81 / 30.81 |
| F16 | WINDOW2 | 50000 | 750000 | 0 | 0 | 25.01 / 25.01 | 30.61 / 30.61 |
| F17 | WINDOW3 | 50000 | 750000 | 0 | 0 | 24.89 / 24.81 | 42.75 / 42.75 |
| F18 | BE1 | 0 | 243190 | 0 | 0 | 166.56 / 166.56 | 168.16 / 168.16 |
| F19 | BE2 | 0 | 243195 | 0 | 0 | 166.56 / 166.56 | 168.16 / 168.16 |
| F20 | BE3 | 0 | 243190 | 0 | 0 | 166.56 / 166.56 | 180.23 / 173.22 |
| F21 | Z3.ZCPU | 10000 | 282619 | 0 | 0 | 116.82 / 118.42 | 166.95 / 159.19 |
| F22 | Z3.ZCPU | 10000 | 256693 | 0 | 0 | 72.81 / 73.06 | 100.27 / 99.92 |

Camera images (offered / complete / image deadline misses): F02 9375/9375/0, F03 9375/9375/0, F04 9375/9375/0, F05 9375/9375/0

The 2 s baseline gives the same p99 and max for 17 of the 23 receivers.
Small differences appear only in flows whose tail depends on rare events
that a 2 s window samples less: F10 p99 27.55 vs 27.81 µs and max 31.75 vs
31.42 µs; F13, F17, F20; and F21/F22, the transient flows with random
signatures. All are within ±8 µs and far from the deadlines.

Run-level aggregates against `selected_run_metrics.csv` (repo / now):

| Seed | Offered pkts (repo / now) | Received (repo / now) | Images offered/complete (repo / now) | Critical non-camera p99 max µs (repo / now) | Max (repo / now) | Camera image p99 max µs (repo) |
|---|---|---|---|---|---|---|
| 1001 | 2941003 / 2941003 | 2941003 / 2941003 | 7500/7500 / 7500/7500 | 48.732 / 48.732 | 59.436 / 59.436 | 499.132 |
| 1002 | 2933244 / 2933244 | 2933244 / 2933244 | 7500/7500 / 7500/7500 | 48.732 / 48.732 | 59.436 / 59.436 | 499.132 |
| 1003 | 2938851 / 2938851 | 2938851 / 2938851 | 7500/7500 / 7500/7500 | 48.732 / 48.732 | 59.436 / 59.436 | 499.132 |
| 1004 | 2936479 / 2936479 | 2936479 / 2936479 | 7500/7500 / 7500/7500 | 48.732 / 48.732 | 59.436 / 59.436 | 499.132 |
| 1005 | 2944310 / 2944310 | 2944310 / 2944310 | 7500/7500 / 7500/7500 | 48.732 / 48.732 | 59.436 / 59.436 | 499.132 |

## Step 5 — PrioPlca on the T1S segments

### Integration

`prioplca/` holds `PrioPlca.{h,cc,ned}` and the license files, taken unchanged
(CRLF → LF only) from Jean Carlos Macedo's `plca-priority-to` repository
(GitLab, commit 79c46a7). `PrioPlca.cc` is derived from INET's `EthernetPlca`
(Copyright (C) 2023 OpenSim Ltd.) and keeps its LGPL-3.0-or-later header.
It builds as a separate shared library and does not touch the zonal-ivn-tsn
build:

```bash
cd prioplca && opp_makemake -f -s -o prioplca -DINET_IMPORT -I$INET_ROOT/src -L$INET_ROOT/src '-lINET$(D)' && make MODE=release
cd ../simulations
../src/zonal-ivn-tsn -n ".:../src:../tests:../prioplca:$INET_ROOT/src" -l ../prioplca/prioplca \
    -f zonal_t1s_prioplca.ini -u Cmdenv -c <config> [-r '$extra>0']
```

`zonal/configs/t1s_prioplca.ini` sets `**.plca.typename = "PrioPlca"`. Only
`EthernetPlcaInterface` has a `plca` submodule, so this reaches the T1S ports
and nodes only. Modes: `standard`; `priorityTo` (a 128-bit priority TO with a
16-bit commit guard after every TO that carried data); `multiTo` (static slot
list). The ZSW coordinator keeps ID 0.

Constraints that shaped the configurations:
- `priorityTo` requires `priorityNodeID > 0`, so the coordinator can never
  own the priority TO. It goes to the radar (ID 1) in Z2/Z3. Z1 has no
  upstream critical node and stays in standard mode.
- Brake frames are sent by the coordinator, and BRAKEx only receives. A
  priority TO for the brake node would therefore have no effect. The brake
  scenario uses `multiTo` instead, giving the coordinator every other slot.
- PrioPlca has no fragmentation mode. Fragmentation in `plca-priority-to`
  means splitting the background frames, so it is applied here to the heavy
  nodes: 245 B payload every 1.667 ms (6 fragments per 10 ms, same rate).
- `ZonalIVNT1SExtra` now sets its segment sizes with `default(...)`, so
  `multiTo` can lengthen the cycle. Values are unchanged.
- The extra nodes' delay is measured with INET `UdpSink` at HPC (`XDelay`).
  Standard mode was rerun the same way; its flows are identical to step 3.

**Sanity:** `T1S_C0_PrioStd` (PrioPlca, standard mode, on all 8 T1S nodes)
against `T1S_C0`, seed 1001. All 51 TrafficAudit/application CSVs and all
vector data are byte-identical.

### a. Radar phase sweep, 45–130 µs (seed 1001, 1 000 packets per point)

`priorityTo` gives the radar the priority TO. `multiTo` uses Z2/Z3 cycle
`0 1 2 1` (the radar owns 2 of 4 slots).

| Offset µs | F06 max std / prioTo / multiTo | F06 misses std / prioTo / multiTo | F07 max std / prioTo / multiTo | F07 misses std / prioTo / multiTo |
|---|---|---|---|---|
| 45 | 102.7 / 92.7 / 90.0 | 1 / 0 / 0 | 90.0 / 78.1 / 89.3 | 0 / 0 / 0 |
| 50 | 146.6 / 146.0 / 97.3 | 268 / 200 / 0 | 85.0 / 85.0 / 85.0 | 0 / 0 / 0 |
| 55 | 152.9 / 153.2 / 152.9 | 644 / 683 / 216 | 144.4 / 141.2 / 92.3 | 206 / 169 / 0 |
| 60 | 148.4 / 148.4 / 147.9 | 956 / 949 / 515 | 147.9 / 147.9 / 136.2 | 591 / 621 / 207 |
| 65 | 143.4 / 143.4 / 144.2 | 975 / 975 / 862 | 143.4 / 143.4 / 143.4 | 906 / 897 / 473 |
| 70 | 143.0 / 143.0 / 150.1 | 982 / 991 / 973 | 138.4 / 138.4 / 138.4 | 961 / 952 / 814 |
| 75 | 145.5 / 144.4 / 145.1 | 994 / 996 / 985 | 145.3 / 145.1 / 145.1 | 985 / 985 / 947 |
| 80 | 140.3 / 139.4 / 140.3 | 997 / 999 / 994 | 140.3 / 140.5 / 140.5 | 991 / 992 / 981 |
| 85 | 135.1 / 135.1 / 135.5 | 1000 / 947 / 999 | 135.5 / 135.9 / 135.5 | 999 / 998 / 993 |
| 90 | 130.3 / 130.1 / 141.5 | 776 / 690 / 957 | 154.5 / 130.5 / 142.2 | 1000 / 959 / 997 |
| 95 | 125.3 / 125.1 / 149.5 | 467 / 387 / 745 | 137.2 / 125.5 / 149.5 | 825 / 681 / 976 |
| 100 | 120.3 / 120.1 / 144.5 | 135 / 90 / 443 | 132.2 / 120.5 / 144.5 | 425 / 270 / 770 |
| 105 | 115.3 / 115.1 / 139.5 | 116 / 72 / 218 | 127.2 / 115.5 / 139.5 | 241 / 180 / 501 |
| 110 | 110.3 / 110.1 / 134.5 | 15 / 7 / 34 | 122.2 / 110.5 / 134.5 | 42 / 26 / 112 |
| 115 | 105.3 / 105.1 / 129.5 | 9 / 4 / 20 | 117.2 / 105.5 / 129.5 | 23 / 17 / 76 |
| 120 | 100.3 / 100.1 / 124.5 | 4 / 3 / 12 | 112.2 / 100.5 / 124.5 | 13 / 8 / 49 |
| 125 | 95.3 / 95.1 / 119.5 | 0 / 0 / 3 | 107.2 / 95.5 / 119.5 | 1 / 0 / 8 |
| 130 | 90.3 / 90.1 / 114.5 | 0 / 0 / 3 | 102.2 / 93.2 / 114.5 | 1 / 0 / 8 |
| **total misses (18 000)** | | 8339 / 7993 / 7979 | | 8210 / 7755 / 7912 |
Neither mechanism removes the worst case. Across the band, `priorityTo` cuts
misses by ≈ 4–6 % and `multiTo` by ≈ 4 % on F06. `multiTo` helps at 50–65 µs
but is worse above 90 µs, because its longer cycle delays the coordinator's
window frame into the radar's path. The max stays at ≈ 140–153 µs: when the
radar becomes ready, the coordinator's window frame (≈ 67 µs, not
preemptable) is already on the wire. The radar then needs its own ≈ 58 µs
frame plus the 1 Gb/s hops. A different TO order cannot shorten either part,
so with 64 B frames at 10 Mb/s the 100 µs radar deadline is phase-dependent
whatever the PLCA variant.

### b. Brake on the segment (3 seeds, 2 s)

Radar: misses out of 6 000. Brake: misses out of 60 000. Window: losses out
of 30 000.

| Mode | F06 / F07 max µs | Radar misses F06 / F07 | Brake max µs F08 / F09 / F10 | Brake misses F08 / F09 / F10 | Window lost F15 / F16 / F17 | Prio TOs/s |
|---|---|---|---|---|---|---|
| standard (T1S_BRAKE) | 217.7 / 219.5 | 6000 / 6000 | 170.7 / 225.9 / 227.2 | 37 710 / 35 742 / 39 457 | 13 473 / 10 665 / 10 665 | — |
| burst max_bc=3 (T1S_BRAKE_BC3) | 419.0 / 414.0 | 6000 / 6000 | 158.4 / 226.0 / 225.3 | 28 629 / 34 005 / 37 825 | 5 016 / 8 928 / 8 928 | — |
| priorityTo radar | 152.0 / 146.8 | 3013 / 2914 | 170.7 / 238.8 / 241.8 | 37 710 / 49 020 / 51 412 | 13 473 / 22 236 / 22 233 | 769 (Z2/Z3) |
| multiTo coord (0 1 0 2 0 3) | 274.3 / 280.2 | 6000 / 6000 | 153.4 / 219.1 / 227.7 | 27 876 / 34 521 / 38 449 | 4 287 / 9 468 / 9 468 | — |
| multiTo coord+radar (0 1 0 2 0 1 0 3) | 224.5 / 219.5 | 6000 / 6000 | 153.4 / 214.7 / 226.1 | 27 876 / 34 650 / 38 227 | 4 287 / 9 516 / 9 516 | — |

Z1 has no radar and runs standard PLCA under priorityTo, so its F08/F15 are
identical to standard. Brake misses stay at 46–86 % in every mode. One
coordinator frame (≈ 67 µs) plus the brake's own frame already exceeds the
100 µs deadline whenever a window frame is in progress, and no TO scheme
changes that. `priorityTo` halves the radar misses, but its 769 extra TOs per
second take capacity from the coordinator. Z2/Z3 brake misses rise to
82–86 % and window losses to 74 %. `multiTo` for the coordinator recovers
some window capacity (Z1 losses 45 → 14 %) and Z1 brake misses (63 → 46 %),
but makes the radar worse.

### c. Extra nodes, 5 and 8 nodes per Z2/Z3 segment (3 seeds, 2 s)

`priorityTo` gives the radar the priority TO. `multiTo` gives the radar every
other slot (`0 1 2 1 3 1 4` / `0 1 2 1 3 1 4 1 5 1 6 1 7`). Radar misses are
out of 6 000 and window losses out of 30 000. "Extra-node delay" is the delay
of the extra nodes' packets to HPC (all delivered in every run).

| Profile, nodes | Mode | F06 max / misses | F07 max / misses | Window max µs (or lost) | Extra-node delay mean / p99 µs | Prio TOs/s |
|---|---|---|---|---|---|---|
| sensor, 5 | standard | 225.0 / 2000 | 97.2 / 0 | 177.1 | 116.1 / 498.5 | — |
| sensor, 5 | priorityTo | 152.0 / 2000 | 97.2 / 0 | 167.7 | 119.2 / 498.5 | 469 |
| sensor, 5 | multiTo | 139.9 / 1514 | 85.7 / 0 | 182.6 | 118.3 / 498.5 | — |
| sensor, 8 | standard | 225.0 / 2702 | 195.8 / 2001 | 283.9 | 133.6 / 501.4 | — |
| sensor, 8 | priorityTo | 146.6 / 1419 | 135.1 / 3072 | 364.6 | 147.3 / 569.8 | 674 |
| sensor, 8 | multiTo | 152.9 / 1751 | 231.7 / 1868 | 401.6 | 147.5 / 567.1 | — |
| heavy, 5 | standard | 1382.6 / 2600 | 1329.8 / 2600 | 2295 | 1322.9 / 1510.1 | — |
| heavy, 5 | priorityTo | 1297.9 / 1699 | 1255.3 / 2592 | 2501 | 1322.1 / 1510.8 | 346 |
| heavy, 5 | multiTo | 1321.8 / 1625 | 1267.4 / 1806 | 2414 | 1315.5 / 1510.8 | — |
| heavy, 8 | standard | 1974.5 / 6000 | 4268.7 / 6000 | lost 1 182 / 8 395 / 8 420 | 1902.4 / 4422.6 | — |
| heavy, 8 | priorityTo | 1393.9 / 5123 | 1612.7 / 4887 | lost 1 182 / 11 034 / 11 065 | 1911.3 / 4421.9 | 261 |
| heavy, 8 | multiTo | 2053.7 / 4936 | 2497.3 / 4831 | lost 1 182 / 11 614 / 11 636 | 1906.2 / 4422.6 | — |
| heavy frag, 5 | standard | 646.3 / 2761 | 402.1 / 3070 | 620 | 309.0 / 619.9 | — |
| heavy frag, 5 | priorityTo | 333.9 / 2334 | 331.2 / 2631 | 574 | 312.7 / 619.9 | 415 |
| heavy frag, 8 | standard | 802.0 / 6000 | 799.9 / 6000 | lost 13 511 / 18 925 / 18 592 | 574.8 / 1151.5 | — |
| heavy frag, 8 | priorityTo | 333.9 / 4855 | 337.3 / 5443 | lost 13 511 / 21 641 / 21 531 | 557.0 / 1171.9 | 315 |

Observations:
- With sensor nodes, both mechanisms bound the radar near the
  single-blocking-frame limit (≈ 135–153 µs instead of 225 µs). They do not
  reach 100 µs, for the reason found in (a). Misses fall by up to ≈ 50 % but
  remain phase-dependent; for F07 with 8 nodes, priorityTo even misses more
  than standard.
- The cost to the extra nodes is small. Their mean delay rises by ≈ 3–14 µs
  and their p99 by up to ≈ 70 µs (8 sensor nodes), with no losses. The window
  pays more: max 284 → 365–402 µs with 8 sensor nodes, still far below 50 ms.
- With 1518 B frames the radar is dominated by one ≈ 1.2 ms frame in
  progress, which neither mechanism can preempt (max ≥ 1.25 ms). With 8 heavy
  nodes the coordinator capacity lost to the priority TOs or the longer cycle
  raises window losses from 28 % to 37–39 %.
- Fragmentation (6 × 245 B) together with priorityTo is the closest
  approximation of preemption. It brings the radar max down to ≈ 334 µs
  (from 1.38–1.97 ms), about one fragment plus the radar frame. But every
  fragment needs its own TO, which costs coordinator capacity: with 8
  fragmenting nodes the window loses 45–72 %.

Run time: 93 runs + 3 reruns, 4 in parallel, 2 638 s + 120 s wall
(≈ 115–135 s per 2 s run, ≈ 85 s per sweep point, RSS ≈ 115 MB each).

## Follow-up studies

Summary CSVs of all T1S experiments are versioned in `zonal/t1s_results/`.
A backup copy is in `C:\Users\Jean\Documents\zb3t-t1s-results\`. Raw
`.vec`/`.sca` files stay in `simulations/results/` (gitignored, ≈ 4.7 GB) and
can be regenerated from the configs.

### F1 — Deadline sensitivity (existing results only)

`scripts/run/t1s_deadline_sensitivity.py` computes, for each scenario/mode
and flow class, the smallest deadline that would give zero misses: the
observed max latency over the class, or ∞ if any packet was lost. It also
gives pass/fail at 100 µs, 150 µs, 250 µs, 500 µs and 1 ms. Radar values for
the phase sweeps use the 45–130 µs band common to the three modes. Brake rows
outside the "brake on segment" scenario are brake on its 100 Mb/s link. Output:
`zonal/t1s_results/deadline_sensitivity.csv`.

| Scenario | Mode | Class | Min. deadline for 0 misses | 100 µs | 150 µs | 250 µs | 500 µs | 1 ms |
|---|---|---|---|---|---|---|---|---|
| Baseline L1/A0 | C0 (100 Mb/s links) | radar | 30.5 µs | pass | pass | pass | pass | pass |
| T1S L1/A0 | standard | radar | 90.9 µs | pass | pass | pass | pass | pass |
| Baseline L1/A0 | C0 (100 Mb/s links) | brake | 31.4 µs | pass | pass | pass | pass | pass |
| T1S L1/A0 | standard | brake | 31.4 µs | pass | pass | pass | pass | pass |
| Baseline L1/A0 | C0 (100 Mb/s links) | window | 42.7 µs | pass | pass | pass | pass | pass |
| T1S L1/A0 | standard | window | 110.2 µs | fail | pass | pass | pass | pass |
| T1S L1/A1 | standard | radar | 90.7 µs | pass | pass | pass | pass | pass |
| T1S L1/A1 | standard | brake | 31.4 µs | pass | pass | pass | pass | pass |
| T1S L1/A1 | standard | window | 114.5 µs | fail | pass | pass | pass | pass |
| T1S radar phase sweep 45-130 us | standard | radar | 154.5 µs | fail | fail | pass | pass | pass |
| T1S radar phase sweep 45-130 us | priorityTo | radar | 153.2 µs | fail | fail | pass | pass | pass |
| T1S radar phase sweep 45-130 us | multiTo | radar | 152.9 µs | fail | fail | pass | pass | pass |
| T1S + brake on segment | standard | radar | 219.5 µs | fail | fail | pass | pass | pass |
| T1S + brake on segment | standard | brake | 227.2 µs | fail | fail | pass | pass | pass |
| T1S + brake on segment | standard | window | ∞ (lost 34803) | fail | fail | fail | fail | fail |
| T1S + brake on segment | burst max_bc=3 | radar | 419.0 µs | fail | fail | fail | pass | pass |
| T1S + brake on segment | burst max_bc=3 | brake | 226.0 µs | fail | fail | pass | pass | pass |
| T1S + brake on segment | burst max_bc=3 | window | ∞ (lost 22872) | fail | fail | fail | fail | fail |
| T1S + brake on segment | priorityTo radar | radar | 152.0 µs | fail | fail | pass | pass | pass |
| T1S + brake on segment | priorityTo radar | brake | 241.8 µs | fail | fail | pass | pass | pass |
| T1S + brake on segment | priorityTo radar | window | ∞ (lost 57942) | fail | fail | fail | fail | fail |
| T1S + brake on segment | multiTo coord | radar | 280.2 µs | fail | fail | fail | pass | pass |
| T1S + brake on segment | multiTo coord | brake | 227.7 µs | fail | fail | pass | pass | pass |
| T1S + brake on segment | multiTo coord | window | ∞ (lost 23223) | fail | fail | fail | fail | fail |
| T1S + brake on segment | multiTo coord+radar | radar | 224.5 µs | fail | fail | pass | pass | pass |
| T1S + brake on segment | multiTo coord+radar | brake | 226.1 µs | fail | fail | pass | pass | pass |
| T1S + brake on segment | multiTo coord+radar | window | ∞ (lost 23319) | fail | fail | fail | fail | fail |
| T1S + sensor nodes, 5 per segment | standard | radar | 225.0 µs | fail | fail | pass | pass | pass |
| T1S + sensor nodes, 5 per segment | standard | window | 177.1 µs | fail | fail | pass | pass | pass |
| T1S + sensor nodes, 8 per segment | standard | radar | 225.0 µs | fail | fail | pass | pass | pass |
| T1S + sensor nodes, 8 per segment | standard | window | 283.9 µs | fail | fail | fail | pass | pass |
| T1S + sensor nodes, 5 per segment | priorityTo | radar | 152.0 µs | fail | fail | pass | pass | pass |
| T1S + sensor nodes, 5 per segment | priorityTo | window | 167.7 µs | fail | fail | pass | pass | pass |
| T1S + sensor nodes, 8 per segment | priorityTo | radar | 146.6 µs | fail | pass | pass | pass | pass |
| T1S + sensor nodes, 8 per segment | priorityTo | window | 364.6 µs | fail | fail | fail | pass | pass |
| T1S + sensor nodes, 5 per segment | multiTo | radar | 139.9 µs | fail | pass | pass | pass | pass |
| T1S + sensor nodes, 5 per segment | multiTo | window | 182.6 µs | fail | fail | pass | pass | pass |
| T1S + sensor nodes, 8 per segment | multiTo | radar | 231.7 µs | fail | fail | pass | pass | pass |
| T1S + sensor nodes, 8 per segment | multiTo | window | 401.6 µs | fail | fail | fail | pass | pass |
| T1S + heavy nodes, 5 per segment | standard | radar | 1.38 ms | fail | fail | fail | fail | fail |
| T1S + heavy nodes, 5 per segment | standard | window | 2.30 ms | fail | fail | fail | fail | fail |
| T1S + heavy nodes, 8 per segment | standard | radar | 4.27 ms | fail | fail | fail | fail | fail |
| T1S + heavy nodes, 8 per segment | standard | window | ∞ (lost 17997) | fail | fail | fail | fail | fail |
| T1S + heavy nodes, 5 per segment | priorityTo | radar | 1.30 ms | fail | fail | fail | fail | fail |
| T1S + heavy nodes, 5 per segment | priorityTo | window | 2.50 ms | fail | fail | fail | fail | fail |
| T1S + heavy nodes, 8 per segment | priorityTo | radar | 1.61 ms | fail | fail | fail | fail | fail |
| T1S + heavy nodes, 8 per segment | priorityTo | window | ∞ (lost 23281) | fail | fail | fail | fail | fail |
| T1S + heavy nodes, 5 per segment | multiTo | radar | 1.32 ms | fail | fail | fail | fail | fail |
| T1S + heavy nodes, 5 per segment | multiTo | window | 2.41 ms | fail | fail | fail | fail | fail |
| T1S + heavy nodes, 8 per segment | multiTo | radar | 2.50 ms | fail | fail | fail | fail | fail |
| T1S + heavy nodes, 8 per segment | multiTo | window | ∞ (lost 24432) | fail | fail | fail | fail | fail |
| T1S + heavyfrag nodes, 5 per segment | standard | radar | 646.3 µs | fail | fail | fail | fail | pass |
| T1S + heavyfrag nodes, 5 per segment | standard | window | 620.2 µs | fail | fail | fail | fail | pass |
| T1S + heavyfrag nodes, 8 per segment | standard | radar | 802.0 µs | fail | fail | fail | fail | pass |
| T1S + heavyfrag nodes, 8 per segment | standard | window | ∞ (lost 51028) | fail | fail | fail | fail | fail |
| T1S + heavyfrag nodes, 5 per segment | priorityTo | radar | 333.9 µs | fail | fail | fail | pass | pass |
| T1S + heavyfrag nodes, 5 per segment | priorityTo | window | 573.5 µs | fail | fail | fail | fail | pass |
| T1S + heavyfrag nodes, 8 per segment | priorityTo | radar | 337.3 µs | fail | fail | fail | pass | pass |
| T1S + heavyfrag nodes, 8 per segment | priorityTo | window | ∞ (lost 56683) | fail | fail | fail | fail | fail |

Reading:
- **Radar on T1S.** With the catalog phase the radar meets 100 µs (91 µs),
  but for any phase it needs ≈ 155 µs. With small extra nodes the
  requirement is ≈ 225 µs in standard mode; priorityTo or multiTo bring it to
  140–150 µs. 250 µs is met by every scenario without heavy frames.
- **Brake on the segment** needs ≈ 230–240 µs in every mode, 2.3× the
  catalog deadline. The window then loses packets, so no deadline is met.
- **Window.** Its real catalog deadline is 50 ms. That is met in every
  scenario without losses: T1S, A1, sensor nodes, heavy with 5 nodes
  (≤ 2.5 ms). It fails only where the segment is overloaded and drops
  window frames (brake on segment, 8 heavy or 8 fragmenting nodes).
- **Heavy 1518 B participants** push radar requirements to 1.3–4.3 ms.
  Fragmentation plus priorityTo brings them to ≈ 335 µs.

### F2 — Analytic PLCA worst-case bound versus simulation

`scripts/run/t1s_plca_bound.py` (model and constants in its docstring;
output `zonal/t1s_results/plca_bound.csv`). The radar latency is the PLCA wait
W, plus its own frame t_r = 57.6 µs, plus the fixed path H0 = 2.16 µs
(measured: T1S min 59.76 µs − t_r), plus queueing at the two 1 Gb/s hops,
Hq ≤ 37.0 µs (three 1542 B frames: one in progress at ZSW→CSW, and at CSW→HPC
one in progress plus one TC6 LiDAR frame ahead). Each node sends at most one
frame per TO (max_bc = 0), so the coordinator's window frame is a data TO of
D = 67.2 µs (frame + IPG). Empty TOs take 3.2 µs and the beacon ≈ 2.2 µs.
The *floor* is the latency any non-preemptive TO scheme cannot avoid when
another node's frame starts just before the radar is ready:
D_other + t_r + H0.

| Scenario | Mode | Ideal PLCA wait W µs | Floor µs | Bound µs (W + t_r + H0 + Hq) | Observed max µs | Within bound | Radar MAC logical collisions / packets |
|---|---|---|---|---|---|---|---|
| Phase sweep, 3 nodes (radar offset 45–130 µs) | standard | 72.6 | 127.0 | 169.4 | 154.5 | yes | 4101 / 36000 |
| Phase sweep, 3 nodes (radar offset 45–130 µs) | priorityTo | 72.6 | 127.0 | 169.4 | 153.2 | yes | 3707 / 36000 |
| Phase sweep, 3 nodes (radar offset 45–130 µs) | multiTo | 75.8 | 127.0 | 172.6 | 152.9 | yes | 1708 / 36000 |
| sensor nodes, 5 per segment | standard | 207.0 | 127.0 | 303.8 | 225.0 | yes | 2000 / 12000 |
| sensor nodes, 8 per segment | standard | 408.6 | 127.0 | 505.4 | 225.0 | yes | 4548 / 12000 |
| sensor nodes, 5 per segment | priorityTo | 72.6 | 127.0 | 169.4 | 152.0 | yes | 1312 / 12000 |
| sensor nodes, 8 per segment | priorityTo | 72.6 | 127.0 | 169.4 | 146.6 | yes | 268 / 12000 |
| sensor nodes, 5 per segment | multiTo | 139.8 | 127.0 | 236.6 | 139.9 | yes | 0 / 12000 |
| sensor nodes, 8 per segment | multiTo | 139.8 | 127.0 | 236.6 | 231.7 | yes | 2157 / 12000 |
| heavy nodes, 5 per segment | standard | 2539.8 | 1293.4 | 2636.6 | 1382.6 | yes | 5200 / 12000 |
| heavy nodes, 8 per segment | standard | 6240.6 | 1293.4 | 6337.4 | 4268.7 | yes | 12004 / 12000 |
| heavy nodes, 5 per segment | priorityTo | 1237.4 | 1293.4 | 1334.2 | 1297.9 | yes | 906 / 12000 |
| heavy nodes, 8 per segment | priorityTo | 1237.4 | 1293.4 | 1334.2 | 1612.7 | NO (+278.5) | 3379 / 12000 |
| heavy nodes, 5 per segment | multiTo | 1306.2 | 1293.4 | 1403.0 | 1321.8 | yes | 1128 / 12000 |
| heavy nodes, 8 per segment | multiTo | 1306.2 | 1293.4 | 1403.0 | 2497.3 | NO (+1094.3) | 4866 / 12000 |
| heavyfrag nodes, 5 per segment | standard | 576.6 | 311.8 | 673.4 | 646.3 | yes | 5815 / 12000 |
| heavyfrag nodes, 8 per segment | standard | 1332.6 | 311.8 | 1429.4 | 802.0 | yes | 12000 / 12000 |
| heavyfrag nodes, 5 per segment | priorityTo | 255.8 | 311.8 | 352.6 | 333.9 | yes | 370 / 12000 |
| heavyfrag nodes, 8 per segment | priorityTo | 255.8 | 311.8 | 352.6 | 337.3 | yes | 573 / 12000 |

Constants: t_r = 57.6 µs, D(64 B) = 67.2 µs, D(1522 B) = 1233.6 µs, D(295 B) = 252.0 µs, H0 = 2.16 µs, Hq ≤ 37.0 µs

Findings:
- **The floor already exceeds the deadline.** With only 64 B frames on the
  segment it is 127 µs (67.2 + 57.6 + 2.16), before any 1 Gb/s queueing.
  So no PLCA variant (standard, priorityTo, multiTo) can guarantee 100 µs
  for the radar in every phase. Only preemption or phase control can.
  Observed sweep maxima (152.9–154.5 µs) lie between this floor and the
  bound (169.4–172.6 µs).
- **priorityTo does not lower the 3-node bound.** In Z2/Z3 the radar (ID 1)
  already follows the coordinator, so the priority TO only repeats what the
  normal order gives. It helps when there are other senders (sensor
  nodes: bound 304–505 → 169 µs; observed 225 → 147–152 µs).
- **The miss band is predicted by the window phase.** Misses occur for
  radar offsets 45–120 µs (F06, window F16 at 55 µs) and 55–130 µs (F07, F17
  at 60 µs): from ≈ 10 µs before to ≈ 70 µs (≈ one window TO) after the
  window release. That is when the radar becomes ready while the window
  frame is about to occupy, or occupies, the coordinator's TO.
- **The simulation exceeds the ideal bound in two cases, both with eight
  1518 B senders:** priorityTo +279 µs and multiTo +1 094 µs. INET's PLCA
  keeps a frame in the delay line for at most 40 µs and then signals a
  logical collision. The CSMA/CD MAC then backs off (51.2 µs slots,
  exponential) and may miss TOs. The radar MAC shows thousands of logical
  collisions in these runs (last column). The bound assumes the frame waits
  at PLCA, so it does not cover MAC retries. Backoff dominates when
  1.2 ms frames are frequent.

### F3 — Hybrid scenario: only window and slow body nodes on T1S

`scripts/run/gen_t1s_hybrid.py` generates `networks/ZonalIVNT1SHybrid.ned`
and `configs/t1s_hybrid.ini` (entry point `zonal_t1s_hybrid.ini`). Radar,
brake and every other endpoint keep their original point-to-point links.
Only each WINDOW link is replaced, on the same ZSW port, by a T1S segment
shared with n body nodes `Bz[]` (doors, lighting, seats, ...). The segment
then has 2 + n nodes (coordinator, WINDOW, bodies), up to 8, the IEEE 802.3cg
25 m guarantee. Catalog forwarding tables are unchanged; body entries are
added.

Each body node has one upstream status flow (to HPC:7000, VLAN 31) and one
downstream command flow (from its own UdpSourceApp at HPC to the node, VLAN
32). Both carry 8 B payload (a CAN data field; 64 B frame) at PCP 2, below
the window's PCP 3, with a random phase per seed. The deadline is the
period. Two profiles: 10 ms (typical body) and 1 ms (stress). C0, L1/A0,
2 s, seeds 1001–1003. Report: `scripts/run/t1s_hybrid_report.py` →
`zonal/t1s_results/hybrid.csv`.

| Body period | Nodes/segment | Radar F06/F07 max µs (misses) | Brake F08–F10 max µs (misses) | Window F15/F16/F17 max µs (lost) | Body up mean / p99 / max µs (misses) | Body down mean / p99 / max µs (misses) |
|---|---|---|---|---|---|---|
| 10 ms | 2 | 30.5 / 25.1 (0) | 30.4 / 30.8 / 31.4 (0) | 90.9 / 90.2 / 102.8 (0) | — | — |
| 10 ms | 4 | 30.5 / 25.1 (0) | 30.4 / 30.8 / 31.4 (0) | 138.9 / 160.4 / 154.0 (0) | 103.0 / 410.3 / 532.1 (0) | 85.1 / 119.2 / 232.1 (0) |
| 10 ms | 6 | 30.5 / 25.1 (0) | 30.4 / 30.8 / 31.4 (0) | 151.6 / 168.2 / 231.4 (0) | 126.2 / 489.8 / 538.7 (0) | 95.6 / 187.8 / 206.3 (0) |
| 10 ms | 8 | 30.5 / 25.1 (0) | 30.4 / 30.8 / 31.4 (0) | 212.4 / 169.6 / 172.4 (0) | 132.4 / 450.8 / 511.7 (0) | 97.7 / 208.6 / 230.9 (0) |
| 1 ms | 2 | 30.5 / 25.1 (0) | 30.4 / 30.8 / 31.4 (0) | 90.9 / 90.2 / 102.8 (0) | — | — |
| 1 ms | 4 | 30.5 / 25.1 (0) | 30.4 / 30.8 / 31.4 (0) | 172.9 / 162.2 / 137.7 (0) | 116.5 / 380.2 / 572.3 (0) | 96.1 / 197.6 / 240.2 (0) |
| 1 ms | 6 | 30.5 / 25.1 (0) | 30.4 / 30.8 / 31.4 (0) | 291.9 / 292.3 / 308.6 (0) | 158.8 / 568.4 / 658.5 (0) | 277.4 / 691.0 / 725.3 (0) |
| 1 ms | 8 | 30.5 / 25.1 (0) | 30.4 / 30.8 / 31.4 (0) | 587.2 / 466.5 / 517.1 (0) | 202.1 / 527.7 / 703.9 (0) | 240911.7 / 256128.4 / 256372.8 (40704) |

(Misses in parentheses; body misses are against the 10 ms or 1 ms period.
"lost" is the window's measured losses.)

Findings:
- **Radar and brake are identical to C0** (30.5/25.1 µs and 30.4–31.4 µs,
  0 misses) in every case, because they no longer touch the T1S segment.
- **10 ms body flows: all 8 nodes fit.** No misses or losses. Body
  latency is at most 0.54 ms (≈ 5 % of the 10 ms deadline) and the window
  at most 0.23 ms (deadline 50 ms). Every body packet sent was received.
- **1 ms body flows (stress):** up to 6 nodes per segment fit (4 body
  nodes, max 0.73 ms < 1 ms). With 8 nodes the upstream still fits
  (max 0.70 ms), but the downstream commands collapse: 69 996 of
  ≈ 110 700 are lost, the rest arrive after ≈ 0.25 s, and 40 704 miss.
  All downstream traffic leaves from the coordinator, which gets one TO per
  PLCA cycle (max_bc = 0). Six command flows plus the window (11 000
  frames/s) exceed one frame per cycle once six other nodes also send. The
  limit is the coordinator's downstream share, not the 10 Mb/s bit rate
  (well under 20 % used). The window keeps priority (PCP 3 > PCP 2) and
  loses nothing.
- **Answer:** with typical body periods (≥ 10 ms) the segment holds the
  full 8 nodes with ≥ 95 % deadline margin. Downstream-heavy 1 ms traffic
  limits it to about 6 nodes, unless the coordinator gets burst
  (`max_bc`) or extra TOs (`multiTo`).

### F4 — Real traffic: Fever FR250 CAN trace on T1S nodes

Flow set: `zonal/traffic/fever/flows.json`, copied from plca-priority-to
(see the README there). It has 47 CAN IDs and 872 frames/s, with periods of
10 ms–1 s from the trace and deadline = period; 10 IDs are marked CRITICAL by
that project's gateway table. `scripts/run/gen_t1s_fever.py` generates
`configs/t1s_fever.ini` (entry point `zonal_t1s_fever.ini`) on the hybrid
network: radar and brake on 100 Mb/s, WINDOW on T1S.

Each CAN message is a periodic UDP flow to HPC, one UdpSink per CAN ID. It
uses the trace period and phase and a 36 B payload: IEEE 1722 NTSCF 12 B +
ACF CAN 16 B + 8 data bytes, as in plca-priority-to. UDP/IPv4 adds 28 B, so
the MAC frame is 86 B instead of 64 B raw Ethernet (conservative). VLAN 31,
PCP 2. Two mappings:

- `T1S_FEVER_ECU`: one T1S node per sending ECU. The ECU is the source
  address (last byte) of 29-bit IDs; the 11-bit IDs form one ECU. This gives
  19 ECUs, spread over the zones in snake order of load, 6 body nodes per
  zone (8 nodes per segment). The two lightest ECUs (9C, E8; 1 frame/s
  each) share one node so that 19 ECUs fit in 18 slots. Z1 = A7, F7, F4, 8F,
  F5, 9C+E8; Z2 = 95, EF, 14, A8, D3, EA; Z3 = 28, STD, 94, D4, 38, D0.
- `T1S_FEVER_GW`: a single CAN→Ethernet gateway node on Z1's segment sends
  all 47 IDs (3 nodes per segment).

C0, L1/A0, 2 s, seeds 1001–1003; report `scripts/run/t1s_fever_report.py`
→ `zonal/t1s_results/fever_ecu.csv`, `fever_gw.csv` (per CAN ID).


### T1S_FEVER_ECU
| Class | CAN IDs | Packets | Mean µs | p99 µs | Max µs | Worst max/deadline | Misses | Sent − received |
|---|---|---|---|---|---|---|---|---|
| CRITICAL | 10 | 3117 | 160.2 | 452.8 | 501.0 | 5.01 % | 0 | 3 |
| OTHER | 37 | 2265 | 121.6 | 552.0 | 552.0 | 1.81 % | 0 | 0 |
| all | 47 | 5382 | 143.9 | 452.8 | 552.0 | 5.01 % | 0 | 3 |
Window max µs: F15 218.3, F16 167.9, F17 217.8
Tightest CAN IDs: 18FE50A7 (10 ms) max 501.04 µs; 000C7F28 (25 ms) max 453.24 µs; 18FFEFA7 (10 ms) max 176.44 µs

### T1S_FEVER_GW
| Class | CAN IDs | Packets | Mean µs | p99 µs | Max µs | Worst max/deadline | Misses | Sent − received |
|---|---|---|---|---|---|---|---|---|
| CRITICAL | 10 | 3117 | 165.4 | 452.8 | 501.0 | 5.01 % | 0 | 3 |
| OTHER | 37 | 2265 | 114.3 | 452.0 | 552.0 | 1.95 % | 0 | 0 |
| all | 47 | 5382 | 143.9 | 452.8 | 552.0 | 5.01 % | 0 | 3 |
Window max µs: F15 163.5, F16 93.8, F17 104.6
Tightest CAN IDs: 18FE50A7 (10 ms) max 501.04 µs; 18FFEFA7 (10 ms) max 311.26 µs; 000C7F28 (25 ms) max 488.7 µs

Findings:
- **Every CAN ID meets its deadline with a wide margin.** The worst case is
  501 µs for 18FE50A7 (period 10 ms, CRITICAL), 5 % of its deadline. The 37
  non-critical IDs use at most 2 % of theirs. There are no misses in either
  mapping.
- The two mappings give practically the same latencies. The CAN load is
  small, ≈ 0.75 Mb/s of 86 B frames for the whole vehicle. The latency is
  dominated by PLCA cycle waits and by several messages from the same node
  being released together: with max_bc = 0 each frame needs its own TO.
- Window max ≤ 218 µs (deadline 50 ms). Radar and brake are unchanged
  (100 Mb/s links).
- The 3 packets "sent − received" are frames still in flight at the end of
  the simulation, not losses. Every body-node queue reports
  `droppedPacketsQueueOverflow = 0` in all runs.
