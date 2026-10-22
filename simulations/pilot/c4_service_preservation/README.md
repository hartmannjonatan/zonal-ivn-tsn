# C4 service-preservation pilot

This is an isolated exploratory pilot for measuring the effect of gPTP and the P1 time-aware gate schedule on the frozen C3 profile, and for testing the P1-defined deterministic CBS compensation (`alpha = 0.77`). It does not change the P1, common C0–C3 configuration, official campaign results, or official C4 status.

For synchronized variants, validation permits PCP7 as an additional active queue only on gPTP-aware HPC, CSW, and zonal-switch egresses. Catalog PCPs remain mandatory, and any other unexpected active class still fails validation. The extra queues are recorded separately as `additional_active_gptp_control_queues`. C3 base and the official C0/C1 validation retain strict class matching.

Synchronized treatments can consume random numbers before the transient plan initializes, so a matching seed alone does not guarantee the same F21/F22 events. Each synchronized treatment therefore replays the event CSV emitted by the matching C3-base run. The runner waits for C3 base to create that calendar when needed; the pilot-only `TrafficPlan.transientCalendarFile` parameter reads and validates it. Empty by default, it leaves official C0–C3 generation unchanged. C4 validators allow schedules only on the seven predeclared GCL egresses; the pilot's effective-GCL audit checks every gate value against the configured schedule.

The pilot uses only the accepted official C3 profile `reduction_11`. The runner applies that profile at each load from the official frozen ratios and screens all L0–L3/A0–A1 cells. Its final schedule contains 19 execution IDs, including three seed-41 instrumentation-repair IDs; after superseded records are excluded, the results contain 16 effective current runs. Auditing found that the common topology's `hasTimeSynchronization=false` setting won over the pilot configuration. After forcing clock creation, INET exposed two integration requirements: gPTP needs the streaming Ethernet transmitter/receiver pair for PHY reception-boundary signals, and catalog stream filters must guard `udp.destPort` with `has(udp)` because gPTP control frames are non-UDP. The first topology draft also made ZSWs transmit Sync to non-gPTP sensors; they are now leaf `SLAVE_NODE`s synchronized over `eth0`, while HPC is master and CSW is the bridge. Those earlier attempts remain preserved as technical history and are not valid synchronization/C4 controls. The corrected runner explicitly enables synchronization on HPC, CSW and all zonal switches, enables the INET streaming pair, uses guarded pilot-only catalog filters, applies all seven GCL egress schedules as command-line overrides, records clock vectors, and verifies effective settings in the `.sca`. Three seed-41 repair executions do not add experimental candidates or alter the workload.

After setting up OMNeT++/INET as for the official campaign, record the plan first and then run:

```sh
source /home/jonatan/omnetpp-env.sh
export INET_ROOT=/home/jonatan/omnetpp/samples/inet-4.7.0
python3 simulations/pilot/c4_service_preservation/run_pilot.py --plan
ionice -c2 -n0 python3 simulations/pilot/c4_service_preservation/run_pilot.py --run --resume
```

In another terminal (or SSH session), keep the live single-screen dashboard open with:

```sh
python3 simulations/pilot/c4_service_preservation/pilot_status.py --interval 1
```

For this machine, the usual environment setup is `source /home/jonatan/omnetpp-env.sh` followed by `export INET_ROOT=/home/jonatan/omnetpp/samples/inet-4.7.0`. The dashboard can run in another terminal or SSH session.

For this workspace, the corrected plan is versioned with `--refresh-plan-after-instrumentation-fix`; this archives the previous plan and preserves the ledger and all result files. Then use `--run --resume`. A fresh pilot with no ledger or attempts can start with `--plan` and `--run`. Completed ledger rows are reused; valid completed raw output is reprocessed without a rerun; incomplete output is archived under `results/failed-attempts/` before retry. Technical attempts remain separate in `results/technical_attempts.jsonl`. The pilot runner is capped at four jobs and stops before submitting more work if free disk falls below 45 GB or the official campaign lock is held. It does not change the official runner. Do not start this pilot while the official campaign is active.

Ordinary cohorts can run up to four OMNeT++ simulations concurrently. The three instrumentation repairs form a cohort and use the same four-job cap; common validation and pilot-specific vector extraction run one execution at a time. Concurrent parsing of multi-gigabyte `.vec` files caused a system-wide out-of-memory kill. The dashboard reports simulation and post-processing phases separately.

Pilot-specific auxiliary vector extraction streams CBS credit, gPTP, gate, guard-band, and link-state samples directly to compressed CSV. It retains only the five clock series needed for the offset comparison and per-vector integration state in memory. This prevents CBS `numCredits` vectors from expanding into large Python object lists during resumption.

`pilot.ini` contains only pilot-specific gPTP, classification, instrumentation, and TAS settings; it is loaded alongside the common `simulations/omnetpp.ini`. Results, calendars, compact traces, ledger, checkpoint, and final JSON/Markdown are created under this directory's `results/`.

The completed pilot consolidation is in [`results/analysis.md`](results/analysis.md) and [`results/pilot_results.json`](results/pilot_results.json). It recommends keeping the official P1 unchanged: the compensated C4 passes the synchronization and gate-instrumentation checks, but F08/F09 miss their 100 µs deadlines in all three paired L2/A1 seeds. This rejects the tested gate schedule, not every possible C4 design.

The C4 original diagnostic may run even if pre-screened inadmissible, and is always labeled as diagnostic. An inadmissible compensated cell is skipped. C3 L3 is never simulated when the official frozen profile exceeds the 75% port-reservation cap. Results remain exploratory: `official_c4_frozen=false`.
