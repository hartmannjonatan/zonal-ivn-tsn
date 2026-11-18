#!/usr/bin/env python3
"""Radar phase sweep on ZonalIVNT1S (config T1S_RadarPhase in zonal/configs/t1s.ini).

  generate  write catalog variants with F06/F07 offset = 0..195 us (5 us step)
  run       run every iteration of T1S_RadarPhase (parallel, --jobs)
  analyze   per offset: radar mean/max latency, deadline misses, losses

Environment: OMNeT++ setenv sourced and INET_ROOT set (for `run`).
"""
import argparse
import csv
import os
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SIM = ROOT / "simulations"
OUT = SIM / "results/t1s/radar_phase"
OFFSETS_US = list(range(0, 200, 5))
CONFIG = "T1S_RadarPhase"


def generate():
    src = (SIM / "zonal/traffic/catalog.xml").read_text()
    (OUT / "catalogs").mkdir(parents=True, exist_ok=True)
    for off in OFFSETS_US:
        text = src
        for fid in (6, 7):
            pat = re.compile(rf'(<flow id="{fid}" name="F0{fid}"[^>]*?) offset="[^"]*"')
            text, n = pat.subn(rf'\1 offset="{off * 1e-6:g}"', text)
            assert n == 1, fid
        (OUT / "catalogs" / f"catalog_radar{off}us.xml").write_text(text)
    print(f"{len(OFFSETS_US)} catalogs in {OUT / 'catalogs'}")


def run(jobs):
    inet = os.environ["INET_ROOT"]
    cmd = ["../src/zonal-ivn-tsn", "-n", f".:../src:../tests:{inet}/src", "-f", "zonal_t1s.ini",
           "-u", "Cmdenv", "-c", CONFIG, "--cmdenv-express-mode=true", "--cmdenv-status-frequency=600s"]
    (OUT / "logs").mkdir(parents=True, exist_ok=True)

    def one(i):
        with open(OUT / "logs" / f"run{i}.log", "w") as log:
            return i, subprocess.call(cmd + ["-r", str(i)], cwd=SIM, stdout=log, stderr=subprocess.STDOUT)

    start = time.time()
    with ThreadPoolExecutor(jobs) as pool:
        for i, rc in pool.map(one, range(len(OFFSETS_US))):
            if rc:
                print(f"run {i} failed ({rc})")
    print(f"wall time {time.time() - start:.0f} s")


def analyze(config=CONFIG, out=OUT):
    """Per radar offset: F06/F07 max latency, deadline misses, losses."""
    rows = []
    for sca in out.glob(f"{config}-radarOffset=*-#0.sca"):
        text = sca.read_text()
        off = int(re.search(r"^itervar radarOffset (\d+)", text, re.M).group(1))
        run = int(re.search(r'^attr runnumber "?(\d+)', text, re.M).group(1))
        assert f"catalog_radar{off}us.xml" in text, off
        rd = out / f"{config}-{run}"
        row = {"radar_offset_us": off}
        for flow, node in (("F06", "RADAR1"), ("F07", "RADAR2")):
            rx = list(csv.DictReader((rd / f"{flow}-HPC-rx.csv").open()))[0]
            tx = list(csv.DictReader((rd / f"{flow}-{node}-tx.csv").open()))[0]
            row[f"{flow}_max_us"] = round(float(rx["max_latency"]) * 1e6, 3)
            row[f"{flow}_misses"] = int(rx["deadline_misses"])
            row[f"{flow}_lost"] = int(tx["measured_packets"]) - int(rx["measured_packets"])
        rows.append(row)
    rows.sort(key=lambda r: r["radar_offset_us"])
    with (out / "radar_phase.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    for r in rows:
        print(r)
    for flow in ("F06", "F07"):
        worst = max(rows, key=lambda r: r[f"{flow}_max_us"])
        print(f"{flow}: worst max {worst[f'{flow}_max_us']} us at offset {worst['radar_offset_us']} us; "
              f"misses {sum(r[f'{flow}_misses'] for r in rows)}; "
              f"offsets with misses: {[r['radar_offset_us'] for r in rows if r[f'{flow}_misses']]}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["generate", "run", "analyze", "all"])
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--config", default=CONFIG, help="analyze: config name")
    ap.add_argument("--dir", default=None, help="analyze: result dir relative to simulations/")
    a = ap.parse_args()
    if a.action in ("generate", "all"):
        generate()
    if a.action in ("run", "all"):
        run(a.jobs)
    if a.action in ("analyze", "all"):
        analyze(a.config, SIM / a.dir if a.dir else OUT)
