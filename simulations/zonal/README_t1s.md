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
