# Technical addendum 002 — postprocessing path argument

The corrected B simulation completed at 31.05 s and the canonical P1 validator reported 4,716,467 packets, zero drops, and 42 egresses/336 class queues checked. A postprocessing helper then raised `NotADirectoryError` because the calendar reader received the `events.csv` filename where it expected the run directory. This is a runner-only defect; no simulation or output data was changed.

The existing raw execution at `results/runs/B_local_L2_A1_seed41/` is retained and will be reprocessed in place after correcting the helper to pass the directory. No new methodological or technical simulation is needed for this correction. The first route-prefix-mismatched B attempt remains separately retained under `results/technical/attempt_001_network_prefix/`.
