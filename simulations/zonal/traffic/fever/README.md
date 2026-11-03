# Fever FR250 CAN flow set

`flows.json` is copied unchanged (CRLF → LF) from Jean Carlos Macedo's
`plca-priority-to` repository (`data/flows.json`, commit 79c46a7). That
repository's `scripts/gen_flows.py` (LGPL-3.0-or-later) derived it from a 1 s
CAN capture of a Fever FR250 electric vehicle: 47 CAN IDs with their period
(snapped to standard values), phase, DLC and the gateway's CRITICAL class.
The deadline is the period.

`scripts/run/gen_t1s_fever.py` maps these flows onto 10BASE-T1S nodes of the
hybrid zonal network (follow-up F4).

## Plausibility of the capture (`scripts/run/fever_trace_analysis.py`)

Run against the original oscilloscope export
(`plca-priority-to/data/fever_fr250_can_trace.csv`, 674 decoded frames over
999.8 ms; not copied here):

- **Consistent with a real J1939-style bus.** 46 of 47 IDs are 29-bit
  extended IDs; the oscilloscope prints extended IDs with 8 hex digits, so
  000001F2 and 00000000 are extended too. Only 30C is an 11-bit standard ID.
  The IDs come from 20 source addresses (likely ECUs), and priority 6
  dominates (24 IDs). 26 of the 46 use proprietary PGNs (PF 0xFF), whose
  meaning is manufacturer-specific and cannot be checked without the DBC.
  All frames are data frames with DLC 8, and no decode errors are flagged.
  (gen_t1s_fever.py, F4, grouped 000001F2 and 00000000 with 30C as one
  "STD" node; this changes the node grouping, not the traffic.)
- **Periods are clean.** The regular IDs sit on standard rates (10, 20,
  100, 200, 300, 500 ms) with inter-arrival jitter (max − min) / period below 7 %
  (0–1 % for most). gen_flows.py
  snapped them within ±1.2 %. The exception is 000C7FD3 (median 80 ms,
  snapped to 100 ms, +25 %).
- **Frames are missing from the capture.** On the periodic IDs, gaps are
  exact multiples of the period (2–15×), implying 167 of 774 frames (≈ 22 %)
  missing. 11 frames are malformed: truncated or merged data bytes, or no
  CRC. This points to the oscilloscope decoder dropping back-to-back frames,
  because CAN itself retransmits. Correcting for it gives ≈ 840–870
  frames/s, which matches the 872 frames/s of flows.json. The measured 674
  frames/s underestimates the bus.
- **Bit rate.** Timestamps have 0.01–0.1 ms resolution (34 consecutive pairs
  share a timestamp), so the bit rate cannot be measured exactly. The
  frequent 280 µs back-to-back spacing matches 500 kbit/s (an extended 8-byte
  frame lasts 268–308 µs). The bus load would then be ≈ 18–21 %, or
  ≈ 22–26 % with the missing frames.
- **Limits.** The capture is 1 s long: 4 IDs are seen once and 20 IDs only
  2–5 times, so their periods are weakly determined. 34 of the 43 repeated
  IDs carry a constant payload, so it was a single, probably stationary,
  vehicle state. There is no DBC, so the function of each ID is unknown. The
  irregular 000C7Fxx IDs and ID 00000000 (constant payload) cannot be
  interpreted.

## Processing a new capture

`flows.json` stays as it is. For a new capture (same oscilloscope CSV
format: Time, ID, DLC, Data, CRC, Errors), from the repository root:

```bash
python3 scripts/run/fever_trace_analysis.py NEW.csv simulations/zonal/traffic/fever/flows.json   # plausibility
python3 scripts/run/fever_gen_flows.py NEW.csv            # -> simulations/zonal/traffic/fever/flows_NEW.json
#   options: --period-method robust (recover periods despite missing frames),
#            --critical ID,ID,... (default: the plca-priority-to CRITICAL list)
python3 scripts/run/gen_t1s_fever.py --flows simulations/zonal/traffic/fever/flows_NEW.json --tag new
#   -> zonal/configs/t1s_fever_new.ini, zonal_t1s_fever_new.ini, configs T1S_FEVER_NEW_ECU / _GW
cd simulations && ../src/zonal-ivn-tsn -n ".:../src:../tests:$INET_ROOT/src" -f zonal_t1s_fever_new.ini -u Cmdenv -c T1S_FEVER_NEW_ECU
cd .. && python3 scripts/run/t1s_fever_report.py --flows simulations/zonal/traffic/fever/flows_NEW.json --tag new
```

`fever_gen_flows.py` refuses to overwrite an existing file. Run on the
original capture, it reproduces `flows.json` exactly (periods, phases,
classes, indices). New flow files carry `id_bits`, which `gen_t1s_fever.py`
uses for the ECU grouping, so 8-digit IDs below 0x7FF are grouped by their
source address. In the original F4 mapping, 000001F2 and 00000000 sit in the
"STD" node.
