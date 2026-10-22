# Answers to prior C4 questions

Audit date: 2026-10-20. This file answers the requested questions from preserved files only. No configuration was changed to reconcile an experimental discrepancy.

## a. Effective buffers

The effective CSW→Z3 queue capacity is **128 KiB = 131,072 bytes = 1,048,576 bits** in both the load-scaled and absolute-profile runs. The P1 v4 specifies 128 KiB per class at bottlenecks G1–G4, and `simulations/zonal/configs/classification.ini` applies `128KiB` to every CSW egress queue. The resolved SCA for the fixed pilot records `*.CSW.eth[*].macLayer.queue.queue[*].dataCapacity 128KiB` and each instantiated queue as `dataCapacity 1048576b`; the prior scaled D3 SCA records the same effective value. The fixed pilot’s queue report also uses `capacity_bits=1048576`.

The phrase “1 MiB” in the prior fixed-profile analysis was a unit-label error: it treated 1,048,576 **bits** as 1,048,576 **bytes**. There was no buffer change. The prior report was corrected and its former version preserved in `simulations/pilot/c4_fixed_L2_profile/results/history/analysis_pre_buffer_unit_correction_2026-10-20.md`. Other capacities resolve per P1: 32 KiB = 32,768 B = 262,144 bits; camera talker egresses are 64 KiB = 65,536 B = 524,288 bits.

Sources: [`P1-v4.pdf`](../../../docs/design/P1-v4.pdf), `simulations/zonal/configs/classification.ini`, fixed SCA `results/runs/D3_fixed_TAS_L0_A0_seed41/Joint_D3_fixed_TAS_L0_A0-#0.sca.gz`, and scaled SCA `simulations/pilot/c4_feasibility_decision/results/runs/D3_TAS_L0_A0_seed41/Joint_D3_TAS_L0_A0-#0.sca.gz`.

## b. Isolation of scaled versus fixed-profile contrasts

For the paired cells L0/A0 and L1/A1 at seed 41, the resolved configuration comparison shows that the **material functional intervention is the full set of CBS idleSlope values**, with dependent `sendSlope = idleSlope − bitrate`; all 24 entries change from load-scaled D3 values to the absolute L2 D3 values. Example: `Z1.ZSW.eth[0]/TC4` is 47.37 Mb/s in scaled L0 and 236.85 Mb/s fixed; at L1 it is 94.74 Mb/s versus 236.85 Mb/s. The CBS type, initial credit, limits, `extraLength=64 b`, `extraDuration=0 s`, and guard-band credit policy remain the same.

The following were checked and match for each same-cell/seed contrast: resolved buffers (including 128 KiB CSW queues), workload load/alignment, catalog/classification/PCP-to-TC rules, network routes, 1 s warm-up, `[1,31)` measurement and 50 ms drain, cell-specific F21/F22 calendar signatures, seed and drift CLI arguments, gPTP configuration, TAS GCL (or empty periodic schedules for noTAS), OMNeT++ 6.4.0, INET 4.7.0, executable SHA-256 `ca8e9d75878fe89c664f392126403b44a31c79b03d4dcacf949fbc4e95ba32a7`, and the probe shared library SHA-256 `70e335e9d9c07690b219399e1e4753f3c015598089e109d229f62982c3fc4d7e`. Probe C++ sources are byte-identical. The pilot NED wrapper differs only in its package name; the INI/config names and output paths differ to isolate each pilot. Those differences are instrumentation namespace/config bookkeeping, not traffic or service settings.

Thus the comparison is suitable as an exploratory profile-policy contrast, with the limitation that all 24 reservations change together; it cannot identify a single-queue cause. Historical executable hash availability is complete for these D3 run records as recorded in their manifests; the same current executable hash is present in both plans. No buffer or workload discrepancy was found.

Sources: fixed `results/manifest.json`, fixed `results/plan.json`, feasibility `results/plan.json`, per-run command arrays and resolved SCA files.

## c. Existing C3_sync controls

The controls are correctly constructed from the load-specific official C3 profile, not from an incorrect or stale D3 profile. The plan’s independent recomputation agrees with the reported C3 hashes: L0/A0 `669b8980905e4e4e3c3b68cae0e5daab55e3034f5bfc3e86f32794f51801f2c7`; L1/A1 `02c595a538e17b77fbc94954741bb9bf193bd8311417f3aeda2129d477de5ed9`. Their transient calendar signatures also match their cell seed-41 references.

- **L0/A0 seed 41:** simulation valid; applications fail; stability passes. It records 72,373 overflow drops: 36,778 at Z1 uplink TC4 and 35,595 at Z2 uplink TC4 (each queue capacity 1,048,576 bits). F02/F03 lose 4,847/4,501 packets, respectively; F04/F05 have substantial deadline misses; F06/F07 also miss deadlines. F21/F22 are heavily affected.
- **L1/A1 seed 41:** simulation valid; applications and stability fail. It records 59,460 overflow drops: 25,389 at CSW→Z3 TC4, 15,673 at Z1 uplink TC4 and 18,398 at Z2 uplink TC4. CSW TC4 has sustained growth in the P1 queue proxy. F02/F03 lose 5,972/6,172 packets, and F06/F07 miss deadlines; F21/F22 also lose many packets.

**Demonstrated:** these are valid runs of the load-specific official profiles; the packet losses are reconciled with switch queue overflows, primarily at TC4 egresses. The absolute L2 policy assigns far higher fixed uplink reservations than the L0/L1 scaled profiles, and its seed-41 runs at the corresponding cells pass with zero overflow. The transient transfer sizes and event count are not scaled down with the permanent-load factor in P1, so reducing permanent traffic alone does not eliminate the transient service demand.

**Not demonstrated as a unique causal decomposition:** aggregate queue-drop counters do not identify every dropped packet’s flow. It is consistent with the evidence that load-scaled TC4 service, unchanged F21/F22 bursts and aligned/staggered packet phases interact; the preserved runs do not isolate those contributions. The fixed-versus-scaled contrast changes the whole reservation table, so it is not a single-port intervention.

Source: `simulations/pilot/c4_feasibility_decision/results/plan.json` (`control_audit`), `results/final_results_2026-10-20.json`, and each control’s `pilot-result.json`.

## d. D3 identity and reusable runs

The candidate is **`D3_coordinated_20pct`**, specifically the effective profile from `simulations/pilot/c4_feasibility_decision/results/final_results_2026-10-20.json`, `D3_TAS_L2_A1_seed41`. Its canonical hash is `571e3a10e004005b2994aadc6dc495db730f6e9b8842af2550ebcbb3d6eb33be`; the full 24-row table is copied to `frozen_profile_table.csv`. It is the redimensioned candidate that passed L2/A1 in seeds 41, 43 and 47. It is distinct from the older `D3` in `c4_joint_dimensioning`, which used another profile and had brake deadline failures.

Existing executions with the complete absolute profile and matching D3 GCL are: the six L2/A1 TAS/noTAS executions in `c4_feasibility_decision` (both treatments × seeds 41/43/47), plus the four seed-41 fixed-profile executions in `c4_fixed_L2_profile` (L0/A0 and L1/A1 × TAS/noTAS). Those ten positions are reusable subject to the frozen manifest’s parameter, calendar, source and evidence checks. The scaled L0/L1 D3 executions are not executions of this absolute profile.

## e. Synchronization evidence

The current fixed-profile pilot’s authoritative clock evaluation subtracts **simultaneous corrected-clock readings as native integer ticks before serialization**. In `[1,31)`, each node has 30,000 periodic 1 ms samples per run; discrete clock-change snapshots are also retained. Across the four fixed seed-41 runs, periodic maxima are 20–50 ns and the clock-event-snapshot maxima are at most 50 ns; no observed sample exceeds 1 µs. Reprocessing the preserved `clock_precision.csv.gz` for the six L2/A1 D3 executions gives the same sampled pass: seed 41 maxima ≤30 ns, seed 43 ≤50 ns, seed 47 ≤50 ns. This supersedes legacy vector-derived failures.

This is **sampled** evidence only. Periodic and clock-change samples do not establish continuous conformance between observations; the continuous status remains `not_verified`. The older L2 aggregate’s false legacy sync flags do not invalidate the technical/profile/calendar evidence; the direct-native-tick reprocessing is separately recorded in this study manifest.
