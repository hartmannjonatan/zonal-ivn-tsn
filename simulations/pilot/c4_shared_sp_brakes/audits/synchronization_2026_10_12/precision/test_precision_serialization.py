#!/usr/bin/env python3
"""Round-trip the precision probe's signed integer tick representation."""
import csv
import io
from decimal import Decimal
import math

SCALE_EXP = -12  # verified from the OMNeT++ runtime for these runs
SCALE = 10 ** (-SCALE_EXP)
BASE_S = 1.246955010
BASE = round(BASE_S * SCALE)

def round_trip(delta_s):
    delta_ticks = round(delta_s * SCALE)
    clock_hpc_raw = BASE
    clock_node_raw = BASE + delta_ticks
    offset_raw = clock_node_raw - clock_hpc_raw  # native integer subtraction, before CSV
    buf = io.StringIO(newline="")
    w = csv.writer(buf)
    w.writerow([clock_hpc_raw, clock_node_raw, offset_raw, SCALE_EXP])
    loaded = next(csv.reader(io.StringIO(buf.getvalue())))
    h, n, diff, exp = map(int, loaded)
    assert n - h == diff == offset_raw
    return diff / SCALE, (BASE + delta_ticks) / SCALE

cases = [20e-9, 30e-9, 1e-6, 10e-6, 1e-6 - 1e-12, 1e-6 + 1e-12,
         -(1e-6 - 1e-12), -(1e-6 + 1e-12)]
for delta in cases:
    got, _ = round_trip(delta)
    assert got == delta, (delta, got)
    assert (abs(got) > 1e-6) == (abs(delta) > 1e-6), (delta, got)

# Reproduce the prior failure mode using six significant digits on absolute times.
hpc = 1.246955010
node = 1.246954990
legacy = float(format(node, ".6g")) - float(format(hpc, ".6g"))
assert Decimal("1.246954990") - Decimal("1.246955010") == Decimal("-0.000000020")
assert math.isclose(legacy, -10e-6, rel_tol=0, abs_tol=1e-15)
print("PASS: integer-tick round trip preserves 20/30 ns, 1/10 us, and +/-1 ps around 1 us")
print(f"Legacy six-significant-digit subtraction: true offset {-20e-9:.12g} s, exported offset {legacy:.12g} s")
