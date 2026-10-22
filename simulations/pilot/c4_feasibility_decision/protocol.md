# C4 feasibility decision pilot: preregistered protocol

Status: `exploratory=true`, `official_c4_frozen=false`. This isolated study does not change P1, C0-C3, the frozen C3 `reduction_11` profile, or the official C4 campaign.

## Corrected input basis

At L2, scalable periodic flows use `effective_period = catalog_period / 2.5`. F13 is 206 application bytes, 256 MAC queue bytes, and 276 catalog wire bytes every 80 us: respectively 20.60, 25.60, and 27.60 Mb/s. Queue population uses MAC frame bytes; link serialization follows the installed INET PHY. The earlier 10.24 Mb/s F13 queue demand omitted the L2 factor. F21/F22 are event-calendar transients and excluded from permanent CBS sums.

All 100 F21/F22 signature pairs were enumerated for A1 simultaneous starts. The largest pair is LF4/LF4: 1,322 packets each over 145.553 ms; together with F13 this is 246.671 Mb/s of MAC queue bits and 251.578 Mb/s of catalog wire bits while active. This is a design envelope, not a permanent average reservation.

## Model and candidate family

The installed INET `CreditBasedGate` spends credit during transmission/IFG; it accrues idleSlope only while its periodic gate is open, outside its implicit guard band, and not transmitting. With `accumulateCreditInGuardBand=false`, credit freezes in closed/guard-band intervals. Candidate service sizing uses `(TC4 open - simultaneous TC4/TC7 overlap - (max TC4 MAC serialization + PeriodicGate extraLength + 96-bit IFG)/1Gbps) / 100us`. This is an optimistic credit budget, not a guaranteed service lower bound. CBS values are the selected queue/wire demand times a preregistered 10% or 20% engineering allowance divided by that budget. No clipping is allowed.

* `D1`: preserve D3 GCL (TC4 82 us, TC7 30 us, 12 us overlap) and recompute CBS for the full simultaneous transient envelope, with 10% allowance.
* `D2`: coordinated, non-overlapping GCL; TC7 30 us, TC4 50 us, 20 us gap, 10% allowance.
* `D3`: same phase rule, TC4 55 us, 15 us gap, 20% allowance.

For D2/D3, TC7 starts at phase 0 on HPC and +0.676 us on CSW egresses (0.576 us maximum brake-frame serialization plus 0.100 us link propagation); TC4 opens after TC7 closes. Applications remain scheduled in simulation time and gates use local gPTP clocks. D1 retains its recorded offsets. All non-target gates preserve C3 behavior. Z3/eth7/TC4 remains A005 x 1.02 = 28.152 Mb/s, with no TAS added there.

Each candidate has a noTAS control with the same CBS and gPTP, plus reused `B_local` and `C3_sync_control` references only after exact-equivalence checks. Three candidate pairs run serially in L2/A1 seed 41. If and only if a candidate passes technical validation, the unchanged P1 application/stability gates, sampled synchronization, and preregistered service/loss evidence, select the passing candidate with the smallest normalized CBS increase above C3; ties use D1, D2, D3 order. Keep it fixed for L2/A1 seeds 43/47, then—only if those pass—L0/A0 and L1/A1 seed 41. No retuning or additional candidates are authorized.

## Gates, service evidence, and stop rules

P1 deadlines/tolerances and the existing queue-stability proxy remain unchanged. Technical validity, applications, stability, sampled synchronization, continuous synchronization, analytical admissibility, and natural service/recovery evidence remain separate. Report every confirmed F13/F21/F22 overflow even if a P1 flow gate passes. F13 episode sizes are baseline-relative; recovery at Z3 is conditional on upstream packet survival. Upstream loss reduces downstream demand and cannot prove service for the full offered workload. No arbitrary-window `departures > arrivals` rule is used: equal throughput with empty boundaries is conservation, not spare capacity.

Runs are serial (`jobs=1`) and require at least 40 GiB free disk and 7 GiB `MemAvailable`; stop before launch or terminate cleanly below either floor. Compress vectors only after derived checks and streaming round-trip verification. Historical pilot folders are read-only. No D3 reproduction is planned because preserved hop traces plus the documented 100 ns final channel reconstruct and exactly match receiver latency maxima and miss counts.

`results/plan.json` and `results/protocol_manifest.json` freeze configurations, commands, runtime hashes, calendars, independent CBS/GCL contracts, and working-tree state before the first new run.
