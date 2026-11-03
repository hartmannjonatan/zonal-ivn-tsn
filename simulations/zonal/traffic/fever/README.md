# Fever FR250 CAN flow set

`flows.json` is copied unchanged (CRLF → LF) from Jean Carlos Macedo's
`plca-priority-to` repository (`data/flows.json`, commit 79c46a7). That
repository's `scripts/gen_flows.py` (LGPL-3.0-or-later) derived it from a 1 s
CAN capture of a Fever FR250 electric vehicle: 47 CAN IDs with their period
(snapped to standard values), phase, DLC and the gateway's CRITICAL class.
The deadline is the period.

`scripts/run/gen_t1s_fever.py` maps these flows onto 10BASE-T1S nodes of the
hybrid zonal network (follow-up F4).
