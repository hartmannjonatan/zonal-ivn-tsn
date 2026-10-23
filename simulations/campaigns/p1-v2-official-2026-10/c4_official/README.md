# Official C4 freeze

This isolated runner applies the exploratory candidate `D3_coordinated_20pct` as the operational C4 profile. The profile is frozen for the upcoming official evaluation; C4 is **not yet officially validated**. The P1 reference configuration remains documented in [P1-final.pdf](../../../../docs/design/P1-final.pdf); this freeze is a versioned operational addendum, not an edit to P1.

The 24-row absolute CBS table is in [`simulations/c4_official/frozen_profile_table.csv`](../../../c4_official/frozen_profile_table.csv), with its complete effective values embedded in `manifest.json`. The canonical profile SHA-256 is `571e3a10e004005b2994aadc6dc495db730f6e9b8842af2550ebcbb3d6eb33be`. `C4_D3_absolute_profile.ini` instantiates `Ieee8021qCreditBasedShaper` explicitly for every row. Reservations remain absolute at L0–L2; no load factor or recalibration is applied.

TAS is used only on HPC→CSW and CSW→Z1/Z2/Z3. SP remains on the three actual brake last hops and on the three transient-only egresses without a permanent CBS reservation. L3 is excluded by the fixed-profile service bound at CSW.eth[0] (539.16 Mb/s versus 862.656 Mb/s permanent demand), not by the 75% cap. No `C4_open` treatment is in the official matrix. C4−C3 is a comparison of complete policies; exploratory open-gate controls are not an official TAS-only contrast.

## Manual operation

The combined official campaign can be split across two machines. The checkout retaining the completed C0 results runs C3 and then C4; a second checkout imports the shared runtime bundle and runs C1/C2. Follow the exact preparation, preflight, start, resume, and merge commands in [the simulations guide](../../../README.md). Do not launch a second simulator on either host.

The static C4 preflight does not run OMNeT++:

```bash
source /home/jonatan/omnetpp-env.sh
export INET_ROOT=/home/jonatan/omnetpp/samples/inet-4.7.0
export OMNETPP_ROOT=/home/jonatan/omnetpp
python3 simulations/campaigns/p1-v2-official-2026-10/run_official_campaign.py --preflight-only
```

If the isolated probe library is missing, build it first (this only compiles the audit probes):

```bash
source /home/jonatan/omnetpp-env.sh
export INET_ROOT=/home/jonatan/omnetpp/samples/inet-4.7.0
cd simulations/c4_official/plugin
opp_makemake -f --make-so -o c4realclockprobe -O build -P "$PWD" -I"$INET_ROOT/src" -L"$INET_ROOT/src" -lINET
make MODE=release -j1
cd ../../..
```

In another terminal, use the shared C0–C4 dashboard. It reads the C0–C3 and C4 ledgers/checkpoints independently; it does not combine or modify them:

```bash
python3 simulations/campaigns/p1-v2-official-2026-10/campaign_status.py
```

```bash
source /home/jonatan/omnetpp-env.sh
export INET_ROOT=/home/jonatan/omnetpp/samples/inet-4.7.0
export OMNETPP_ROOT=/home/jonatan/omnetpp
python3 simulations/campaigns/p1-v2-official-2026-10/run_official_campaign.py --preflight-c3-c4-shard
```

After an interruption, inspect the dashboard and checkpoint, then rerun the assigned shard command with its original `--shard-id`. Machine A runs C3 and C4 sequentially; Machine B runs C1/C2. Each runner reuses only complete ledger rows matching its contract and calendar signatures. Both use one job. The C0–C3 runner requires more than 45 GB free disk and leaves at least 4 GiB of available memory plus 2.5 GiB per active job. C4 is serialized and stops before launch below 40 GiB free disk or 6 GiB available memory; during a C4 run it sends SIGTERM below 40 GiB or 4 GiB available memory. Technical attempts are preserved separately; performance failures remain valid results and are not replaced.

The C3/C4 machine keeps its own C0 result tree and does not transfer it to Machine B. After both shards finish, transfer only the C1/C2 result trees, source ledger, shard manifest, and hash inventory back to Machine A. The offline merger verifies those files and reconstructs the C0–C3 aggregate without starting simulations. Do not manually concatenate ledgers or edit checkpoints.

## Matrix and retained evidence

The frozen matrix contains 180 positions: L0–L2 × A0/A1 × seeds 1001–1030, 1 s warm-up, measurement `[1,31)` s and 50 ms drain. It reuses the current campaign's calendar file for each cell/seed and checks its event signature and byte hash. The runner records to `results/C4/`, separate from the existing C0–C3 ledger and checkpoint.

It validates the resolved SCA contract (CBS module set and parameters, queue capacities, classification, GCL and clock configuration) before committing a result. The first manual run still has runtime checks pending: confirm the effective SCA and GCL, observed traffic-calendar signature/population, gate-state and guard-band behavior, and native-tick clock samples. Sampled synchronization is reported separately; continuous clock conformity remains unverified.

After successful extraction, raw scalar/log/CSV artifacts are losslessly compressed and hash-checked. Exact queue-occupancy change points are retained in the independently verified lossless `p1-queue-occupancy-events-v2-varint` format. The C4 vector retention keeps exact gate and credit samples over a 10 ms audit slice, full guard-band state samples and clock/gPTP correction vectors; full-window gate/credit summaries, compact latency tails, flow counters, queue metrics and clock offsets are retained separately. The full vector is deleted only after those artifacts and the run report pass reconciliation. This provides bounded storage while preserving the documented audit scope; continuous clock conformity is still not claimed.
