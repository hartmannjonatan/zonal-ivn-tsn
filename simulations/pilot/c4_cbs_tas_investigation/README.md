# C4 CBS under TAS pilot

This isolated exploratory pilot tests the CBS service deficit under TAS and evaluates six preregistered compensation candidates. It does not change P1, official C0–C3, the frozen C3 `reduction_11` profile, or official C4 settings. The result is **no candidate approved**; `exploratory=true` and `official_c4_frozen=false`.

TAS is enabled on HPC→CSW and CSW→Z1/Z2/Z3. The actual BRAKE1/2/3 egresses remain SP with gates permanently open. The protocol, route resolution, candidate budget, and acceptance gates are recorded in [`protocol.md`](protocol.md).

## Results

- [Detailed analysis](results/analysis.md)
- [Structured results](results/pilot_results.json)
- [Candidate profiles and port reservations](candidate_registry.json)
- [Execution checkpoint](results/checkpoint.json)
- [Consolidation corrections](results/consolidation_audit.json)
- Compact flow, queue, clock, gate, credit, guard-band, and service evidence is retained under `results/runs/`.

All six candidates passed application gates but failed the registered finite-window stability gate at HPC/TC4. Therefore no seed-43/47 fixed-profile checks or low-load extrapolations were run. The pilot does not establish that C4 or CBS is generally infeasible.

## Reproducing the analysis

The simulations have already completed. To rebuild the report from the saved ledger, candidate registry, and audited event summaries, run:

```sh
python3 simulations/pilot/c4_cbs_tas_investigation/consolidate_results.py
```

The original execution plan, exact run commands, versions, hashes, calendars, and checkpoint are retained in `results/`. The checkpoint is final (`complete_no_candidate_approved`); do not restart or resume its simulation phase. No OMNeT++ simulation is needed to regenerate the analysis.
