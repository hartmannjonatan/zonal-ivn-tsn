# Simulations

`zonal/` contains the OMNeT++ model and generated traffic configuration. `campaigns/p1-v2-official-2026-10/` contains the official C0–C3 runner and calibration record; `campaigns/p1-v2-official-2026-10/c4_official/` contains the frozen C4 treatment and its separate ledger. Historical and exploratory outputs remain outside official aggregates.

The final matrix is split across two machines to avoid copying the large C0 baseline:

- **Machine A (the checkout with the completed C0 results):** run C3 and then C4. It retains C0, C3, and C4 and is the final merge host.
- **Machine B:** import the small runtime bundle from A and run C1 and C2. It does not need C0 result files; it needs the same committed checkout, OMNeT++ 6.4.0, INET 4.7.0, compiled model, and imported calendars/profile.

Both machines must use the same committed code snapshot and matching runtime versions. Do not run two campaign workers on the same machine. The commands below use one simulation job per host, keep each simulator serialized, and stop safely if available memory or disk crosses the configured floor. The campaign is resumable; always reuse the same shard ID on restart.

## Prepare the two machines

First make the implementation commit available on Machine B. If pushing this repository is blocked by GitHub's pack-size limit, transfer an incremental Git bundle from A; the commands are shown below. On Machine A, source the installed OMNeT++ environment and check the host has adequate free space (the C0–C3 runner requires more than 45 GB; C4 requires at least 40 GiB and 6 GiB available memory):

```bash
source /home/jonatan/omnetpp-env.sh
export INET_ROOT=/home/jonatan/omnetpp/samples/inet-4.7.0
export OMNETPP_ROOT=/home/jonatan/omnetpp
python3 simulations/campaigns/p1-v2-official-2026-10/prepare_parallel_campaign.py --prepare-primary
python3 simulations/campaigns/p1-v2-official-2026-10/prepare_parallel_campaign.py --export-secondary-bundle /tmp/p1-c1c2-runtime-bundle.tar.gz
```

The `p1-c1c2-runtime-bundle.tar.gz` contains calendars, the accepted C3 profile, the paired campaign contract, and the compiled model needed by C1/C2. It does not contain C0 results or historical C4 pilot data. Full C4 snapshot verification is performed by Machine A's C3/C4 preflight.

To transfer the source commits without pushing the repository's full object pack, on A create an incremental bundle from the shared remote base:

```bash
git bundle create /tmp/p1-two-host-source.bundle origin/main..HEAD
git bundle verify /tmp/p1-two-host-source.bundle
```

Copy both `/tmp/p1-two-host-source.bundle` and `/tmp/p1-c1c2-runtime-bundle.tar.gz` to B. In B's existing clone, fetch the incremental bundle and check out the exact commit printed by A:

```bash
git fetch /path/to/p1-two-host-source.bundle HEAD:refs/heads/p1-two-host-ready
git checkout --detach p1-two-host-ready
```

Then install matching OMNeT++/INET versions, source the environment, and import the runtime bundle. The importer verifies the source commit, runtime contract, calendar signatures, and file hashes before allowing the C1/C2 preflight.

```bash
source /home/jonatan/omnetpp-env.sh
export INET_ROOT=/home/jonatan/omnetpp/samples/inet-4.7.0
export OMNETPP_ROOT=/home/jonatan/omnetpp
python3 simulations/campaigns/p1-v2-official-2026-10/prepare_parallel_campaign.py --import-secondary-bundle /path/to/p1-c1c2-runtime-bundle.tar.gz
```

Run both static preflights before starting either matrix:

```bash
# Machine A: C3 then C4
python3 simulations/campaigns/p1-v2-official-2026-10/run_official_campaign.py --preflight-c3-c4-shard

# Machine B: C1 and C2
python3 simulations/campaigns/p1-v2-official-2026-10/run_official_campaign.py --preflight-c1-c2-shard
```

These preflights do not start OMNeT++. Resolve any failure before launching the long runs.

## Run and monitor

Start the following commands on their assigned hosts. They may run at the same time because they use disjoint result trees and separate locks; each host runs one simulator at a time.

```bash
# Machine A (the C0-owning checkout)
python3 simulations/campaigns/p1-v2-official-2026-10/run_official_campaign.py --c3-c4-shard --resume --shard-id machine-a-c3c4 --jobs 1

# Machine B
python3 simulations/campaigns/p1-v2-official-2026-10/run_official_campaign.py --c1-c2-shard --resume --shard-id machine-b-c1c2 --jobs 1
```

In another terminal on each host, run the dashboard:

```bash
python3 simulations/campaigns/p1-v2-official-2026-10/campaign_status.py
```

Machine A executes all admissible C3 cells before starting C4. C4 does not wait for the C1/C2 shard. If a process exits due to a resource floor or technical error, inspect the dashboard/checkpoint, address the reported constraint, and rerun the identical command with the same shard ID. Valid completed ledger entries are reused; performance failures remain results and are not replaced.

## Return and merge C1/C2

After Machine B reports its C1/C2 shard complete, create a hash inventory there:

```bash
python3 simulations/campaigns/p1-v2-official-2026-10/merge_campaign_shards.py --write-transfer-manifest /tmp/p1-c1c2-transfer.json
```

Transfer the manifest, `results/runs.jsonl`, `results/shard_manifest.json`, and these two result trees from B to the same relative locations on A:

- `simulations/campaigns/p1-v2-official-2026-10/results/final/C1/`
- `simulations/campaigns/p1-v2-official-2026-10/results/final/C2/`
- B `results/runs.jsonl` → A `results/parallel-transfer/C1C2_source_runs.jsonl`
- B `results/shard_manifest.json` → A `results/parallel-transfer/C1C2_shard_manifest.json`
- transfer manifest → A `results/parallel-transfer/C1C2_transfer_manifest.json`

Use `rsync -a` for the result trees; it can resume interrupted copies. Then, on A, run the offline merger:

```bash
python3 simulations/campaigns/p1-v2-official-2026-10/merge_campaign_shards.py \
  --merge-transferred \
  --manifest simulations/campaigns/p1-v2-official-2026-10/results/parallel-transfer/C1C2_transfer_manifest.json \
  --source-ledger simulations/campaigns/p1-v2-official-2026-10/results/parallel-transfer/C1C2_source_runs.jsonl
```

The merger verifies every transferred file hash, the shard/ledger identities, calendar signatures, local C3 and C4 completion, and the shared campaign contract. It then rebuilds the C0–C3 aggregate without simulations. The C4 ledger remains separate and is shown by the dashboard. Do not manually concatenate JSONL ledgers or edit checkpoints.

`campaign_status.py` shows the local host's shard during execution; after merge on A it shows the consolidated C0–C4 status. The authoritative C0 results and calendars remain on A. No results from pilots or historical campaigns are included.
