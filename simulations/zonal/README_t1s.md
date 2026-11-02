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

The 2 s baseline gives the same p99 and max for 15 of the 23 receivers.
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
