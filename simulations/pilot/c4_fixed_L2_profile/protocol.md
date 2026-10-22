# Fixed absolute D3/L2 profile pilot (preregistered 2026-10-20)

Status: `exploratory=true`, `official_c4_frozen=false`.

## Question and frozen intervention

Test whether the complete absolute D3 profile from `simulations/pilot/c4_feasibility_decision/results/final_results_2026-10-20.json` / `D3_TAS_L2_A1_seed41` removes lower-load failures. The canonical full-profile SHA-256 is `571e3a10e004005b2994aadc6dc495db730f6e9b8842af2550ebcbb3d6eb33be`. The same 24 port/TC idleSlope values are used in L0/A0 and L1/A1; no load scaling, candidate/nominal ratio, clipping, or retuning is applied. `D3_fixed_TAS` uses the full L2 GCL contract; `D3_fixed_noTAS` keeps identical CBS and gPTP and leaves periodic gate schedules empty.

The three egresses with zero permanent-reservation service remain SP/no-CBS: Z1.ZCPU.eth[0]/TC4, Z2.ZCPU.eth[0]/TC4, Z3.ZSW.eth[1]/TC4. All other listed profile classes instantiate the INET credit-based shaper. `sendSlope = idleSlope - physicalBitrate`; credit starts at 0, `transmitCreditLimit=0`, min/max credit unbounded, `accumulateCreditInGuardBand=false`, `extraLength=64 b`, `extraDuration=0 s`.

## Frozen gates

Period 100 us; TC4 opens 55 us and TC7 30 us; initial state open; absolute schedule on synchronized local clock reference `^.^.^.^.clock`; implicit guard band enabled. Offsets: HPC eth0 TC4 70 us, TC7 0; CSW eth1/2/3 TC4 69.324 us, TC7 99.324 us (modulo 100 us). The noTAS treatment uses no periodic durations, without changing any reservation.

## Cells, order, and budget

All runs use seed 41, warm-up 1 s, measurement `[1,31)`, drain 50 ms, one simulation at a time. Run order:

1. D3_fixed_TAS, L0/A0
2. D3_fixed_noTAS, L0/A0
3. D3_fixed_TAS, L1/A1
4. D3_fixed_noTAS, L1/A1

Maximum four methodological executions, plus at most one retry per cell only for a documented technical failure. Performance failures do not authorize retries. Stop before further simulations if configuration, calendar, credit instrumentation, or technical validation fails. Each cell uses its own existing workload and exact prior seed41 transient-calendar file; signatures are stored in `results/plan.json`. Same seed alone is not proof of pairing.

## Controls and acceptance

Existing `C3_sync_control` L0/A0 and L1/A1 reports were audited without reruns. They resolve to the official load-specific C3 profiles and matching cell calendars; their recorded performance failures remain outcomes of the official profile. The old scaled D3 runs remain historical comparisons.

Apply P1 application and stability gates unchanged. Preserve packet and image populations separately, including incomplete camera images as image misses. Report losses, pending packets, latency, goodput, queue stability, sampled synchronization and continuous-synchronization status separately. Distinguish configured idleSlope from realized service. For queue conservation use the same measurement boundaries and keep in-service packets separate; unexplained residuals remain explicit.

## Resource, retention, and provenance

Serialize runs. Require at least 40 GiB free disk and 7 GiB `MemAvailable` before launch and during each run; stop gracefully if a floor is crossed. Stream vector extraction and gzip with verified decompression hashes; retain compact evidence and historical files. Nothing historical is deleted or overwritten.

Frozen D3 profile SHA: `571e3a10e004005b2994aadc6dc495db730f6e9b8842af2550ebcbb3d6eb33be`. Plan, calendars, contract and input hashes are in `results/plan.json` and `results/manifest.json`.
