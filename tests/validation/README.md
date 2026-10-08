# P1 validation

This directory contains focused checks for the implemented benchmark. The acceptance criteria and required metrics are defined by [P1 v4](../../docs/design/P1-v4.pdf).

- `traffic/` checks the 22-flow catalog, payload/wire sizes, timing, VLAN/PCP, L/A workload, multicast, and transient calendars.
- `topology/` checks the NED network and connectivity.
- `classification/` and `source_preshaping/` cover C0 and C1.
- `cbs/` covers CBS configuration, reservation search helpers, and C2/C3-related checks.
- `tas/` and `integration/` retain extension points and are not part of the current C0–C3 campaign.

Use the corresponding `scripts/run/validate_*.py` entry point for a full treatment validation. Run the focused regression tests with `python3 -m unittest discover -s tests/validation/cbs -p 'test_*.py'` and `python3 -m unittest discover -s tests/validation/traffic -p 'test_*.py'`. Campaign acceptance and result extraction are recorded with each execution in the official campaign directory.
