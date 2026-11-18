#!/usr/bin/env python3
"""Exit 0 if the OMNeT++ run (results dir, config, run number) finished: its .sca exists and the
last vector record reaches the configured sim-time-limit (a killed run also writes its .sca, since
finish() is called on SIGTERM; .vci/.vec exist from the start of a run)."""
import re
import sys
from pathlib import Path

d, cfg, run = Path(sys.argv[1]), sys.argv[2], int(sys.argv[3])
seed = 1001 + run
sca = list(d.glob(f"{cfg}-finalSeed={seed},*.sca"))
vci = list(d.glob(f"{cfg}-finalSeed={seed},*.vci"))
if not sca or not vci:
    sys.exit(1)
lim = [float(m) for m in re.findall(r"^config sim-time-limit ([\d.]+)s", sca[0].read_text(errors="replace"), re.M)]
end = 0.0
for line in vci[0].open(errors="replace"):
    p = line.split()
    if len(p) >= 7 and p[0].isdigit():
        try:
            end = max(end, float(p[6]))   # block: id offset length startEvent endEvent startTime endTime ...
        except ValueError:
            pass
sys.exit(0 if lim and end >= lim[0] - 0.2 else 1)
