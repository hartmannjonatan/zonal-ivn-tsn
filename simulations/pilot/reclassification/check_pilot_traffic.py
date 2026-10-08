#!/usr/bin/env python3
"""Run the unchanged traffic auditor in a short-lived process to bound memory."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/"tests/validation/traffic"))
import check_traffic
if len(sys.argv)!=3:raise SystemExit("usage: check_pilot_traffic.py RUN_DIR original|variant")
run=Path(sys.argv[1]);kind=sys.argv[2]
check_traffic.DATA=Path(__file__).resolve().parent/"catalog"/kind
result=check_traffic.check_run(run)
print(f"PASS: {run.name}: {result['source_packets']} source packets, {result['drops']} drops, {result['pending_packet_count_at_simulation_end']} pending")
