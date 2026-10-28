# C4 runtime amendment — 2026-10-25

The first launch attempt for `C4_L0_A0_seed1001` stopped before network initialization because the NED search path named `src` and `tests` relative to `simulations/`, while those source trees are at the repository root. The captured OMNeT++ log reports `Cannot canonicalize 'src'`.

The runner now resolves those two search paths as `../src` and `../tests` from its existing `cwd=simulations`. This changes only NED source discovery; it does not change the C4 network, traffic, timing, buffers, CBS profile, GCL, clocks, or result criteria. The failed attempt is retained under the C4 run evidence and is classified as a technical startup failure, not a methodological result.

The prior frozen manifest is preserved in `protocol_history/manifest_before_ned_path_fix_2026-10-25.json`. The active manifest snapshot ID is refreshed solely to include the corrected runner and this amendment. The selected candidate and all effective simulation parameters remain unchanged.

The zero-time configuration smoke test then resolved every NED package and exposed a second pre-run INI type error: INET 4.7 declares `initialCredit`, `transmitCreditLimit`, `minCredit`, and `maxCredit` as dimensionless credit values, but the frozen profile suffixed them with the bit unit. The 24 CBS instances now express those unchanged values as `0`, `0`, `-inf`, and `inf` credits. The actual bit-valued `maxInterferenceSize` and `extraLength` remain in bits. No CBS rate, credit value, or shaper behavior is changed; only invalid units were removed. The first smoke log is preserved under `results/C4/technical/ned_path_smoke_20261025/`.

The static contract validator previously encoded the same invalid bit suffixes and therefore rejected the corrected dimensionless credit settings. It now validates the profile values in credit units as defined by the installed INET 4.7 NED; effective numerical values remain the frozen CSV values. This is a contract-parser correction, not a parameter change.

A second zero-time smoke reached network initialization and found that `matrix.csv` already stores the calendar path relative to the runner's `cwd=simulations`, but `command_for()` prefixed the campaign directory a second time. Calendar resolution now uses `simulations / matrix.calendar_file`, consistent with the validated matrix path and calendar index. The failed startup is retained as a technical attempt; it generated no application packets and is not a methodological result.
