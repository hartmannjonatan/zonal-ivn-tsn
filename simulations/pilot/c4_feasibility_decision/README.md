# C4 feasibility decision pilot

This isolated study audits corrected C4 inputs, evaluates the preregistered D1–D3 GCL/CBS candidates, and runs fixed-profile checks only where authorized. It does not change P1, C0–C3, the frozen C3 profile, or official configurations. C4 remains exploratory and is not frozen.

The current consolidated decision is in [`results/final_analysis_2026-10-20.md`](results/final_analysis_2026-10-20.md) and [`results/final_results_2026-10-20.json`](results/final_results_2026-10-20.json). The JSON retains per-flow/per-receiver metrics, profiles, effective GCLs, run commands, versions, hashes, and conditional-group outcomes.

Input corrections and historical evidence are in [`audit/audit.md`](audit/audit.md), [`audit/d3_tas_brake_stage_traces.json`](audit/d3_tas_brake_stage_traces.json), and [`audit_corrected_inputs.json`](audit_corrected_inputs.json). The prospective design, selection record, checkpoint, and paired cell results are preserved under `results/`.

To regenerate the consolidated Markdown and JSON from preserved run reports, execute `python3 simulations/pilot/c4_feasibility_decision/consolidate_final_study.py` from the repository root. No simulation is started by this command. Earlier pilot results remain in their original directories; no historical raw data was deleted.
