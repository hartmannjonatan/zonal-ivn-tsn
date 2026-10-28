# C4 execution-order amendment — 2026-10-27

The frozen C4 campaign remains the same 180-position matrix (L0–L2, A0/A1,
seeds 1001–1030), with unchanged configurations, calendars, criteria, and
snapshot. To obtain an early descriptive view for the paper, the resumed runner
will process these nine positions first:

| Seed | Priority cells |
|---|---|
| 1001 | L1/A1, L2/A0, L2/A1 |
| 1015 | L1/A1, L2/A0, L2/A1 |
| 1030 | L1/A1, L2/A0, L2/A1 |

The seeds are fixed before these executions and spread across the configured
seed range. After those nine positions, the runner processes every remaining
matrix position in its canonical order, skipping only valid ledger entries.
The interrupted `C4_L1_A0_seed1021` attempt remains a technical interruption;
its partial output is preserved and the existing one-replacement allowance is
used when the row is resumed.

This is an execution-order change only. It does not reduce or redefine the
official matrix. Results from the nine-position early sample are descriptive
and cannot be presented as general viability across cells or seeds. Any paper
statement must report the exact numerator/denominator and identify that the
full campaign is still running; the completed 30-seed matrix remains the
planned basis for final claims.

The canonical `matrix.csv`, snapshot manifest, treatment parameters, and all
80 valid completed ledger records remain unchanged. The wrapper writes a
hash-pinned order record and a reordered permutation under
`results/C4/execution-order-amendments/` and uses that permutation in memory.
