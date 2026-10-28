# P1 v2 official campaign — operator guide

This guide is the short operational entry point for the two-machine campaign. The detailed C4 profile and runtime checks are in [`c4_official/README.md`](c4_official/README.md). The campaign runner never changes P1 or retunes a treatment.

## Layout and ownership

- Machine A keeps the original C0 results and runs the C3/C4 shard.
- Machine B imports the verified runtime bundle and runs C1/C2 only.
- C0–C3 and C4 have separate manifests, locks, ledgers, and checkpoints. Do not combine ledgers by hand.
- `campaign_status.py` is the read-only local dashboard. It shows the progress of the local shard; it does not merge Machine B's results.
- The P1 matrix is 30 seeds per admissible treatment/cell, with 1 s warm-up, measurement `[1,31)` s, and 50 ms drain. C4 L3 was rejected by the frozen service screen and is not simulated.

## Prepare and run the two machines

Use the same committed source/runtime bundle and the documented host environment on both machines. From the repository root, load OMNeT++ 6.4.0 and INET 4.7.0 before the preflight or runner commands:

```bash
source /path/to/omnetpp/setenv
export INET_ROOT=/path/to/inet-4.7.0
```

On Machine A, verify and export the C1/C2 runtime bundle:

```bash
python3 simulations/campaigns/p1-v2-official-2026-10/prepare_parallel_campaign.py --prepare-primary
python3 simulations/campaigns/p1-v2-official-2026-10/prepare_parallel_campaign.py \
  --export-secondary-bundle /tmp/p1-c1c2-runtime-bundle.tar.gz
```

Transfer that archive to Machine B. On Machine B, import and verify it, then run only C1/C2:

```bash
python3 simulations/campaigns/p1-v2-official-2026-10/prepare_parallel_campaign.py \
  --import-secondary-bundle /path/to/p1-c1c2-runtime-bundle.tar.gz
python3 simulations/campaigns/p1-v2-official-2026-10/prepare_parallel_campaign.py --verify-c1-c2-replica
python3 simulations/campaigns/p1-v2-official-2026-10/run_official_campaign.py \
  --c1-c2-shard --resume --jobs 1 --shard-id primary-c1c2
```

On Machine A, the standard shard preflight is:

```bash
python3 simulations/campaigns/p1-v2-official-2026-10/run_official_campaign.py --preflight-c3-c4-shard
```

For an unamended standard run, start the shard with:

```bash
python3 simulations/campaigns/p1-v2-official-2026-10/run_official_campaign.py \
  --c3-c4-shard --resume --jobs 1 --shard-id secondary-c3c4
```

The wrapper skips matching valid C3 ledger rows and starts the canonical C4 runner only after its C3 child exits cleanly. C4 itself is serialized; `--jobs` applies only to the C0–C3 runner. Do not start a second campaign process on either host.

## Current checkpoint and safe resume

At the read-only dashboard check on **2026-10-28 20:27 −03:00**, the local host had C0 and C3 complete, C4 at 90/180 valid results, no active simulator, and C4 checkpoint status `paused_technical_review` after `C4_L1_A0_seed1022` exited with an error. Do not resume from this state until the failed-run log and technical-attempt budget have been reviewed. Refresh the dashboard and checkpoint first:

```bash
python3 simulations/campaigns/p1-v2-official-2026-10/campaign_status.py
cat simulations/campaigns/p1-v2-official-2026-10/c4_official/results/C4/checkpoint.json
```

The C4 execution-order amendment prioritizes nine predeclared positions and then continues the full 180-position matrix. Because C3 is already complete on this host, after the technical pause is resolved, continue that amended order with:

```bash
python3 simulations/campaigns/p1-v2-official-2026-10/c4_official/run_c4_priority_campaign.py \
  --run --resume --jobs 1
```

This changes execution order only; it does not reduce the matrix or change treatment parameters. A pass in the early sample is descriptive, not completion of the official matrix. The wrapper writes a hash-pinned execution-order amendment and uses the original C4 ledger/checkpoint.

Do not use the standard `--c3-c4-shard` command to continue this amended C4 order: that orchestrator invokes the canonical C4 order. Use the amendment-specific command above after the technical review.

## Monitor and merge

Open the dashboard in a separate terminal on each machine:

```bash
python3 simulations/campaigns/p1-v2-official-2026-10/campaign_status.py
```

After both shards finish, package Machine B's C1/C2 results:

```bash
python3 simulations/campaigns/p1-v2-official-2026-10/merge_campaign_shards.py \
  --write-transfer-bundle /tmp/p1-c1c2-results.tar.gz
```

Transfer the archive to Machine A, then merge there:

```bash
python3 simulations/campaigns/p1-v2-official-2026-10/merge_campaign_shards.py \
  --merge-transfer-bundle /path/to/p1-c1c2-results.tar.gz
```

The merger verifies the archive inventory, hashes, calendars, and shard records before installing results. Keep the archive and original results until the merge is verified. Never copy or edit checkpoint/ledger rows manually.

## Frozen C4 and evidence

C4 uses the `D3_coordinated_20pct` operational snapshot recorded in `c4_official/manifest.json`, with its own 180-position matrix and checkpoint. The freeze is not official validation: each run must pass technical, application, stability, GCL, and synchronization-sampling checks. Sampled synchronization does not establish continuous-time conformance. Preserve valid performance failures; only technically invalid attempts can be replaced under the frozen attempt limit.
