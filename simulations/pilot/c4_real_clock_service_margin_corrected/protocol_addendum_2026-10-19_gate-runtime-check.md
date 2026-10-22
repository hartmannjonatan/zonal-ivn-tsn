# Technical addendum — gate runtime validation correction

**Date:** 2026-10-19  
**Scope:** post-processing correction for the already completed `B_local_L2_A1_seed41` run. This is not a workload, GCL, reservation, model, or search-method change.

The first technical validator required every consecutive gate transition to match the nominal local-clock interval within one simulator tick and treated every local-clock phase residual above one tick as a failed execution. It rejected B after the simulator completed. That criterion was an implementation choice in the pilot validator, not a P1 gate-acceptance criterion.

The retained event trace shows 32 expected gate modules, 620,985 transitions per module, ordered events, and alternating open/closed states. The parsed effective GCL matches the registered B contract. The trace also records local-clock phase residuals after clock corrections: the largest observed residual is 70 ns; the largest consecutive interval deviation is 10 ns. These timing deviations remain reported as measurements. The correction validates transition coverage/order/state sequence separately from phase timing and does not claim exact phase conformity or continuous synchronization.

The installed INET implementation schedules absolute clock events and a `SettableClock` can process an overdue event when a correction advances its clock. Therefore a raw consecutive local-clock interval is not, by itself, a valid one-tick test of the GCL configuration. No model source, clock setting, GCL, workload, or simulation result was changed. B is reprocessed from its retained traces; it is not rerun.

The original failed technical-validation JSON is preserved as `technical-validation-before-gate-phase-correction.json`. Corrected results identify the measured gate timing residuals and preserve the old result as history.

