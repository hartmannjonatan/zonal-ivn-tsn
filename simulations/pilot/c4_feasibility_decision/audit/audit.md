# Corrected audit of preserved C4 pilots

This is a reprocessing audit only; no simulation was run. Prior reports remain preserved. Flags: `exploratory=true`, `diagnostic_only=true`, `official_c4_frozen=false`.

## Input units and F13

At L2, the scalable factor is 2.5 and the period is 80 us. F13 carries 206 application bytes, 256 bytes in the queue, and 276 catalog wire bytes per packet. Therefore its rates are 20.60 Mb/s payload, 25.60 Mb/s queue-MAC, and 27.60 Mb/s wire. The old 10.24 Mb/s value used the base 200 us period and omitted the load factor. Queue occupancy and queue overflow use the MAC queue packet length; link demand uses wire rate. These bases are not interchangeable.

| Egress/TC4 | Permanent flows | Queue-MAC Mb/s | Wire Mb/s |
|---|---|---:|---:|
| CAM1.eth[0]/TC4 | F02 | 56.100 | 56.850 |
| CAM2.eth[0]/TC4 | F03 | 56.100 | 56.850 |
| CAM3.eth[0]/TC4 | F04 | 56.100 | 56.850 |
| CAM4.eth[0]/TC4 | F05 | 56.100 | 56.850 |
| CSW.eth[0]/TC4 | F02, F03, F04, F05 | 224.400 | 227.400 |
| CSW.eth[1]/TC4 | F11, F14 | 86.480 | 89.280 |
| CSW.eth[2]/TC4 | F12, F14 | 86.480 | 89.280 |
| CSW.eth[3]/TC4 | F13 | 25.600 | 27.600 |
| HPC.eth[0]/TC4 | F11, F12, F13, F14 | 137.680 | 144.480 |
| Z1.ZSW.eth[0]/TC4 | F02 | 56.100 | 56.850 |
| Z1.ZSW.eth[6]/TC4 | F11 | 25.600 | 27.600 |
| Z1.ZSW.eth[7]/TC4 | F14 | 60.880 | 61.680 |
| Z2.ZSW.eth[0]/TC4 | F03 | 56.100 | 56.850 |
| Z2.ZSW.eth[6]/TC4 | F12 | 25.600 | 27.600 |
| Z2.ZSW.eth[7]/TC4 | F14 | 60.880 | 61.680 |
| Z3.ZSW.eth[0]/TC4 | F04, F05 | 112.200 | 113.700 |
| Z3.ZSW.eth[7]/TC4 | F13 | 25.600 | 27.600 |

F21/F22 are event-calendar transients, not permanent periodic demand. They remain excluded from permanent CBS reserve sums. The largest L2/A1 event pair in the 10x10 catalog signature envelope is LF4+LF4: combined with F13 it is 246.671 Mb/s queue-MAC and 251.578 Mb/s catalog wire while active.

## Drops at CSW→Z3

| Treatment | F13 lost | F21 lost | F22 lost | CSW.eth[3]/TC4 overflow | Reconciles |
|---|---:|---:|---:|---:|:---:|
| D1_TAS | 3702 | 21516 | 23341 | 48559 | yes |
| D1_noTAS | 2575 | 16454 | 18672 | 37701 | yes |
| D2_TAS | 1680 | 20521 | 22338 | 44539 | yes |
| D2_noTAS | 1445 | 14329 | 15971 | 31745 | yes |
| D3_TAS | 2086 | 18473 | 20548 | 41107 | yes |
| D3_noTAS | 1361 | 12199 | 13529 | 27089 | yes |

All positive queue-overflow counters in these executions are on CSW.eth[3]/TC4. For D3_TAS this is 41,107: F13 2,086 + F21 18,473 + F22 20,548. C3_sync has no overflow on this queue. The D1-D3 CBS reductions on this egress relative to C3, the higher burst release from HPC, and gated service are jointly compatible with the losses; available aggregates cannot isolate causal shares or identify individual dropped IDs. D3_TAS F13 still passes its existing P1 flow gate, but that result is not “zero loss.”

## Corrected natural F13 episodes

The peak is expressed as `episode peak - episode baseline`, in 2,048-bit queue-frame equivalents; it is not the absolute queue level. All D1-D3 TAS runs include increments greater than the previously cited 53 frames. Local Z3 recovery only concerns packets that arrived after upstream queues; losses upstream lower the demand observed at Z3.

| Run | Episodes | Largest increment (frames) | Baseline / peak (bits) | Recovery (ms) | Drops at Z3 queue |
|---|---:|---:|---:|---:|---:|
| D1_TAS_L2_A1_seed41 | 71 | 113 | 4096 / 235520 | 443.025 | 0 |
| D1_noTAS_L2_A1_seed41 | 101 | 101 | 4096 / 210944 | 394.079 | 0 |
| D2_TAS_L2_A1_seed41 | 67 | 110 | 6144 / 231424 | 429.695 | 0 |
| D2_noTAS_L2_A1_seed41 | 90 | 62 | 67584 / 194560 | 238.414 | 0 |
| D3_TAS_L2_A1_seed41 | 68 | 106 | 4096 / 221184 | 412.887 | 0 |
| D3_noTAS_L2_A1_seed41 | 86 | 11 | 155648 / 178176 | 34.312 | 0 |

## D3_TAS brake packets

The retained per-hop trace is sufficient. The final egress PHY transmit-end timestamp plus the configured 100 ns last link equals application receive time because `CatalogUdpApp` computes latency as simulation time minus packet creation time. The reconstruction yields exactly 4 F08 and 14 F09 misses and the recorded maxima. No diagnostic rerun is needed.

| Flow/seq | Generated (s) | Received (s) | Latency (µs) | Over 100 µs | HPC wait (µs) | CSW wait (µs) | Final serialization (µs) |
| F08/34022 | 3.402200000 | 3.402300012 | 100.012000 | 0.012000 | 81.570028 | 11.229972 | 5.760000 |
| F08/75656 | 7.565600000 | 7.565700012 | 100.012000 | 0.012000 | 81.387939 | 11.412061 | 5.760000 |
| F08/117290 | 11.729000000 | 11.729100012 | 100.012000 | 0.012000 | 81.205850 | 11.594150 | 5.760000 |
| F08/159262 | 15.926200000 | 15.926300652 | 100.652000 | 0.652000 | 81.834138 | 11.605862 | 5.760000 |
| F09/34874 | 3.487402000 | 3.487502422 | 100.422485 | 0.422485 | 81.612755 | 11.597730 | 5.760000 |
| F09/34948 | 3.494802000 | 3.494902599 | 100.599000 | 0.599000 | 81.790175 | 11.596825 | 5.760000 |
| F09/76508 | 7.650802000 | 7.650902245 | 100.245298 | 0.245298 | 81.430666 | 11.602632 | 5.760000 |
| F09/76582 | 7.658202000 | 7.658302422 | 100.421814 | 0.421814 | 81.608086 | 11.601728 | 5.760000 |
| F09/118142 | 11.814202000 | 11.814302072 | 100.072331 | 0.072331 | 81.248577 | 11.611754 | 5.760000 |
| F09/118216 | 11.821602000 | 11.821702252 | 100.252000 | 0.252000 | 81.425997 | 11.614003 | 5.760000 |
| F09/160114 | 16.011402000 | 16.011502702 | 100.701814 | 0.701814 | 81.876865 | 11.612949 | 5.760000 |
| F09/160151 | 16.015102000 | 16.015202092 | 100.092000 | 0.092000 | 81.965575 | 10.914425 | 5.760000 |
| F09/201748 | 20.174802000 | 20.174902515 | 100.514909 | 0.514909 | 81.694776 | 11.608133 | 5.760000 |
| F09/201785 | 20.178502000 | 20.178602092 | 100.092000 | 0.092000 | 81.783486 | 11.096514 | 5.760000 |
| F09/243382 | 24.338202000 | 24.338302334 | 100.334067 | 0.334067 | 81.512687 | 11.609380 | 5.760000 |
| F09/243419 | 24.341902000 | 24.342002092 | 100.092000 | 0.092000 | 81.601397 | 11.278603 | 5.760000 |
| F09/285016 | 28.501602000 | 28.501702155 | 100.154754 | 0.154754 | 81.330598 | 11.612156 | 5.760000 |
| F09/285053 | 28.505302000 | 28.505402092 | 100.092000 | 0.092000 | 81.419308 | 11.460692 | 5.760000 |

At HPC the packet often arrives just before TC7 closes and waits for the next opening. At CSW, the remaining queue delay is consistent with a closed gate and/or a nonpreemptable transmission; the retained selected trace does not identify the specific competing frame. The per-hop sum plus 100 ns propagation per channel reproduces each end-to-end latency. The noTAS control has no brake deadline misses; it is a control, not evidence that D3_TAS meets deadlines. The near-threshold failures are phase-sensitive and cannot be fixed by simply adding their observed excess to a gate window without redoing end-to-end phase/service analysis.

## Limits

The packet trace contains selected per-packet application events, but no preserved dropped-packet identity at CSW.eth[3]; attribution is therefore by reconciled receiver population loss plus the unique positive queue counter. The current audit can show compatibility with downstream reserve reduction, upstream burst release, and gate restrictions, but cannot identify an exclusive cause.
