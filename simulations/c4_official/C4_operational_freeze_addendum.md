# C4 operational freeze addendum

**Snapshot:** recorded in `simulations/campaigns/p1-v2-official-2026-10/c4_official/manifest.json`. This addendum freezes an operational candidate before the official C4 campaign. It does not amend the P1 PDF, and it does not establish official validation.

## Candidate and provenance

The selected profile is `D3_coordinated_20pct`, from `simulations/pilot/c4_feasibility_decision/results/final_results_2026-10-20.json`, candidate run `D3_TAS_L2_A1_seed41`. The final exploratory reconciliation is `simulations/pilot/c4_final_verification/results/reconciliation_2026-10-22.json`: all 36 L0–L2 positions were covered (26 new and 10 audited reuses); application, stability-proxy and sampled synchronization gates passed in those positions. The profile was also selected after the registered pilot checks in seeds 41, 43 and 47. The older `D3` from `c4_joint_dimensioning` is a different profile and is not used.

These are exploratory results, not the official C4 matrix. Sampled synchronization passed; continuous conformity was not verified. The exact profile, source files, executable, plugin, INET/OMNeT++ libraries, calendar signatures, and historical evidence are hash-pinned in the manifest. The canonical 24-row profile digest is `571e3a10e004005b2994aadc6dc495db730f6e9b8842af2550ebcbb3d6eb33be`; the CSV is the readable table and the manifest embeds all rows and CBS parameters.

## Frozen configuration

The absolute per-egress/per-TC idle slopes in `frozen_profile_table.csv` are used unchanged for L0, L1 and L2. No factor-of-load scaling, recalibration, or reuse of the pre-redimensioned historical D3 is permitted. `sendSlope = idleSlope − physical bitrate`; initial credit and transmit credit limit are 0 b; min/max credit are −∞/+∞; `maxInterferenceSize=∞ b`; `accumulateCreditInGuardBand=false`; extra length is 64 b and extra duration is 0 s. The INET module is explicitly `inet.linklayer.ieee8021q.Ieee8021qCreditBasedShaper`, connected through the existing per-TC queue-selection path. The runtime validator checks every expected module and rejects missing or unexpected CBS modules.

The 100 µs local-clock GCL is:

| Egress | TC0–TC6 | TC7 |
|---|---|---|
| HPC.eth[0] | 55 µs open, 45 µs closed; offset 70 µs | 30 µs open, 70 µs closed; offset 0 µs |
| CSW.eth[1], [2], [3] | 55 µs open, 45 µs closed; offset 69.324 µs | 30 µs open, 70 µs closed; offset 99.324 µs |

Schedules are absolute-time schedules using each node's synchronized local `SettableClock`, initially open, with implicit guard bands enabled. TAS is instantiated only on these four shared egresses. The actual last hops `Z1.ZSW.eth[4]`, `Z2.ZSW.eth[4]`, `Z3.ZSW.eth[5]` stay SP with permanently open schedules. `Z1.ZCPU.eth[0]/TC4`, `Z2.ZCPU.eth[0]/TC4`, and `Z3.ZSW.eth[1]/TC4` remain SP because their permanent reserve is zero and they carry only transients. The erroneous older BRAKE3 port `[4]` is not used; its route exits `Z3.ZSW.eth[5]`.

The gPTP hierarchy and `ConstantDriftOscillator` are the validated real-clock model: HPC is grandmaster, CSW bridges from HPC to its three zone uplinks, and zone switches synchronize on their HPC-facing uplinks. The synchronization and peer-delay intervals remain 125 ms and 1 s, respectively; nominal tick is 10 ns. The runner assigns deterministic per-seed/per-node constant drifts drawn over [−50,+50] ppm using a SHA-256-derived independent stream, without coupling to traffic RNG consumption. Applications remain scheduled in simulation time. Exact derivation and inputs are recorded in the runner and snapshot.

Buffers, workload, routes, catalog mapping, deadlines, FIFO, descending strict priority and non-preemption remain the P1 configuration. In particular, camera talker queues remain 64 KiB; CSW/switch bottleneck queues remain 128 KiB; other queues remain 32 KiB. The runtime SCA validator checks resolved byte capacities.

## P1 reference difference

The final P1 retains its original C4 as the starting/reference design: C3 CBS with a 100 µs cycle, 10 µs open for TC7, 77 µs open for TC0–TC6, and 13 µs closed, applied to seven egresses on the brake paths. This operational candidate differs in the profile (absolute D3 CBS values), gate openings and phases, and TAS location (the four shared links only, with SP on the actual brake last hops). The exploratory study in the P1 motivates exploring that interaction; this addendum records the selected operational implementation for prospective official evaluation.

The exploratory L3 triage rejects this fixed profile because CSW.eth[0]'s combined TC4/TC6 permanent CBS service upper bound is 539.16 Mb/s while L3 permanent demand is 862.656 Mb/s. This is not a 75% reservation-cap rejection. Accordingly L3 has no official C4 simulation positions under this frozen profile.

## Official evaluation and interpretation

The prepared matrix is L0–L2 × A0/A1 × seeds 1001–1030 (180 positions), with 1 s warm-up, measurement `[1,31)` s and 50 ms drain. Each execution uses the existing official calendar for the same cell/seed. A single C4 treatment is run; no `C4_open` treatment is added. C4−C3 compares complete policies and does not isolate TAS. Exploratory open-gate controls can inform interpretation but are not a substitute for an official TAS-only contrast.

The first manual run must pass runtime checks for resolved CBS/GCL/clock/buffer parameters, observed calendar identity and population, gate/guard-band vectors, and native-tick synchronization samples. Evaluation applies the P1 application, loss, goodput and stability gates without retuning. Camera packet and image completion metrics remain distinct. Synchronization approval is explicitly sampled; continuous conformity is not claimed. Completion of the matrix alone will not mean C4 is validated.

The runner is opt-in, serialized at one job, checkpointed, and refuses to start below 40 GiB free disk or 6 GiB available memory. It monitors a 4 GiB runtime memory floor and 40 GiB disk floor, commits only audited results, preserves technical attempts separately, and never replaces a valid unfavorable result. C0–C3 checkpoints and results remain separate and untouched. At freeze, 240 final C0 positions were complete and 660 final C1–C3 positions remained pending; this C4 executor does not launch them.
