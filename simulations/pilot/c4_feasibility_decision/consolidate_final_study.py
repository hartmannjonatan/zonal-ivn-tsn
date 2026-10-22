#!/usr/bin/env python3
"""Build a compact final report from preserved C4 decision-pilot artifacts."""
from __future__ import annotations
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / "simulations/pilot/c4_feasibility_decision"
RUNS = BASE / "results/runs"
OUT = BASE / "results"

def read(path):
    return json.loads(path.read_text())

def sha(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda:f.read(1024*1024), b""): h.update(block)
    return h.hexdigest()

def metrics_from(report):
    out={}
    for flow, fdata in report.get("qos",{}).items():
        for receiver, x in fdata.get("receivers",{}).items():
            image=x.get("image_completion")
            out.setdefault(flow,{})[receiver]={
                "criticality":fdata.get("criticality"),
                "offered_packets":x.get("offered_packets"),
                "received_packets":x.get("received_packets"),
                "packet_loss_ratio":x.get("packet_loss_ratio"),
                "deadline_misses_received":x.get("deadline_misses_received"),
                "deadline_miss_ratio_including_loss":x.get("deadline_miss_ratio_including_loss"),
                "latency_samples":x.get("latency",{}).get("samples"),
                "latency_p99_s":x.get("latency",{}).get("p99_s"),
                "latency_max_s":x.get("latency",{}).get("max_s"),
                "goodput_payload_ratio":x.get("goodput_payload_ratio"),
                "image_completion":image,
            }
    return out

def compact_report(run_id, path, source="new"):
    d=read(path)
    positive=[]
    for row in d.get("queue_overflow_drops_by_queue",[]):
        n=row.get("overflow_drops_post_warmup_including_drain",0)
        if n: positive.append({"queue":row.get("queue"),"tc":row.get("tc"),"drops_post_warmup_including_drain":n,"capacity_bits":row.get("capacity_bits")})
    return {
      "execution_id":run_id,"source_status":source,"report_path":str(path.relative_to(ROOT)),
      "cell":d.get("cell"),"load":d.get("load"),"aggregation":d.get("aggregation"),"seed":d.get("seed"),
      "simulation_valid":d.get("simulation_valid"),"application_viable":d.get("application_viable"),
      "stability_viable":d.get("stability_viable"),"sampled_synchronization_viable":d.get("synchronization_sample_viable"),
      "continuous_synchronization":"not_verified" if d.get("synchronization_continuous_status") in (None,"not_verified") else d.get("synchronization_continuous_status"),
      "combined_viable":d.get("validator_combined_cell_viable",d.get("viable")),
      "calendar_sha256":d.get("calendar_sha256"),"calendar_event_count":d.get("calendar_event_count"),
      "effective_profile_sha256":d.get("effective_profile_sha256"),"effective_profile_bps":d.get("effective_profile_bps"),
      "effective_gcl":d.get("effective_gcl"),"command":d.get("command"),"config":d.get("config"),
      "runtime_versions":d.get("runtime_versions"),"raw_vector_sha256":d.get("raw_vector_sha256"),
      "instrumentation_validation":d.get("instrumentation_validation"),"credit_vector_validation":d.get("credit_vector_validation"),
      "drop_reconciliation":d.get("drop_reconciliation"),
      "offered_packets":d.get("offered_packets"),"pending_packet_count_at_simulation_end":d.get("pending_packet_count_at_simulation_end"),
      "queue_overflow_drop_total_post_warmup_including_drain":d.get("queue_overflow_drop_total_post_warmup_including_drain"),
      "positive_overflow_queues":positive,"nonstable_queues":d.get("nonstable_queues"),
      "qos_by_flow_receiver":metrics_from(d),
      "input_artifact_sha256":sha(path),
    }

def main():
    cp=read(OUT/"checkpoint.json")
    ids=cp["completed_logical_executions"]
    runs=[]
    for rid in ids:
        if rid.startswith("B_local_") or rid=="C3_sync_control_L2_A1_seed41":
            p=ROOT/f"simulations/pilot/c4_real_clock_service_margin_corrected/results/runs/{rid}/pilot-result.json"
            src="reused-after-equivalence-check"
        elif rid=="D1_TAS_L2_A1_seed41":
            # The first artifact is a failed technical export; the preserved
            # technical-attempt replacement has the completed, valid metrics.
            p=RUNS/(rid+"_technical_attempt_001")/"pilot-result.json"
            src="technical-replacement"
        else:
            p=RUNS/rid/"pilot-result.json"
            src="new"
        if p.exists(): runs.append(compact_report(rid,p,src))
    conditional={}
    for name in ("conditional_L2_A1_seed43.json","conditional_L2_A1_seed47.json","conditional_L0_A0_seed41.json","conditional_L1_A1_seed41.json"):
        p=OUT/name
        if p.exists(): conditional[name]=read(p)
    audit=read(BASE/"audit_corrected_inputs.json")
    selection=read(OUT/"selected_candidate.json")
    hash_paths=[
      "omnetpp.ini","src/zonal-ivn-tsn","src/common/TrafficPlan.cc","src/common/TrafficPlan.ned",
      "simulations/zonal/traffic/flows.csv",str((BASE/"pilot.ini").relative_to(ROOT)),
      str((BASE/"run_study.py").relative_to(ROOT)),str((BASE/"run_conditional_phase.py").relative_to(ROOT)),
      str((BASE/"plugin/libc4realclockprobe.so").relative_to(ROOT)),
      str((OUT/"dimensioning.json").relative_to(ROOT)),str((OUT/"candidate_contract.json").relative_to(ROOT)),
      str((BASE/"protocol.md").relative_to(ROOT)),
    ]
    source_hashes={p:sha(ROOT/p) for p in hash_paths if (ROOT/p).is_file()}
    result={
      "schema_version":"1.0","study":"C4 bounded feasibility decision pilot","generated_local_date":"2026-10-20",
      "exploratory":True,"official_c4_frozen":False,"official_c4_campaign_started":False,
      "conclusion":"No candidate demonstrated viability across all conditions tested. D3 is viable at L2/A1 in seeds 41,43,47, but the unchanged D3 design and C3 control both fail application gates in L0/A0 and fail application plus stability in L1/A1. This is bounded evidence, not proof of general CBS+TAS incompatibility.",
      "execution_accounting":{"logical_methodological_treatments_completed":len(ids),"new_logical_treatments":18,"reused_equivalent_controls":2,"simulation_invocations_including_one_technical_retry":19,"new_or_reused_records_included":len(runs),"conditional_groups":{k:v.get("group_pass") for k,v in conditional.items()},"technical_attempts_separate":[{"id":"D1_TAS_L2_A1_seed41 technical attempt/replacement history","path":"simulations/pilot/c4_feasibility_decision/results/runs/D1_TAS_L2_A1_seed41_technical_attempt_001/pilot-result.json","note":"One technical-invalid attempt and one preserved replacement belong to the same logical treatment; no extra candidate/profile was added."}],"active":None,"official_campaign_runs":0},
      "corrected_input_accounting":audit,
      "preregistered_candidate_designs":read(OUT/"dimensioning.json").get("candidate_designs"),
      "candidate_selection_record":selection,
      "runs":runs,"conditional_groups":conditional,
      "historical_brake_trace_path":"simulations/pilot/c4_feasibility_decision/audit/d3_tas_brake_stage_traces.json",
      "historical_f13_csw_drop_table_path":"simulations/pilot/c4_feasibility_decision/audit/audit.md",
      "reproducibility":{"protocol":"simulations/pilot/c4_feasibility_decision/protocol.md","preoutcome_addendum":"simulations/pilot/c4_feasibility_decision/protocol_addendum_preoutcome.md","conditional_preregistration":"simulations/pilot/c4_feasibility_decision/conditional_phase_preregistration_2026-10-20.md","runner":"simulations/pilot/c4_feasibility_decision/run_conditional_phase.py","manifest":"simulations/pilot/c4_feasibility_decision/results/checkpoint.json","sha256_by_path":source_hashes},
      "limitations":["F13/F21/F22 loss allocation at CSW.eth[3]/TC4 is supported by reconciled receiver losses and per-queue overflow counters. The current consolidated derivative does not yet contain packet-level drop IDs; relevant compressed packet-event traces remain preserved for a future streaming extraction.","The detailed four F08 and fourteen F09 misses belong to the earlier c4_joint_dimensioning D3_TAS treatment. Do not transfer them to the separately configured D3 profile in this decision pilot; the latter's per-packet QoS report shows zero brake misses in L2/A1 seed 41,43,47.","The L0/L1 failures are also present in C3_sync controls; they bound the tested operating cells but do not isolate TAS as their cause.","Clock synchronization passes the sampled ≤1 µs check in available runs; continuous conformance is not verified.","Three candidate profiles do not establish general infeasibility."],
    }
    (OUT/"final_results_2026-10-20.json").write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n")
    md=[]
    md += ["# C4 bounded feasibility study — 20 October 2026","","This is an isolated exploratory study using corrected pilot inputs. It does not modify P1, C0–C3, the frozen C3 profile, or official configurations. No official C4 campaign was started.","","## Decision","","**No candidate demonstrated viability across the full tested set.** The selected D3 profile passed the L2/A1 application, stability, drop, and sampled-synchronization gates in seed 41 and in fixed-profile checks at seeds 43 and 47. The same D3 TAS and noTAS treatments and the C3_sync control all failed application gates in L0/A0; in L1/A1 all three failed application and stability gates. This is bounded evidence against adopting D3 as a load-independent C4 profile, not proof that CBS+TAS is generally infeasible.","","Synchronization passed only on the sampled observations; continuous conformance remains unverified.","","## Corrected offered-load accounting","","At L2 the multiplier is 2.5 and F13 period is 80 µs. F13 has 206 application bytes, 256 bytes in the MAC queue, and 276 catalog wire bytes per frame. Thus at 12,500 frames/s the rates are 20.60 Mb/s payload, 25.60 Mb/s queue-MAC, and 27.60 Mb/s wire. The old 10.24 Mb/s value used the base 200 µs period without L2 scaling. Queue occupancy uses queue-MAC bytes; link demand includes wire overhead. These quantities must not be mixed.","","For CSW→Z3/TC4, the corrected permanent demand is 25.60 Mb/s in queued bits and 27.60 Mb/s on wire from F13. F21/F22 are excluded from permanent reserve calculations but share TC4 during events. The catalog's largest paired LF4 event envelope is 246.671 Mb/s queue-MAC and 251.578 Mb/s wire when F13 and both transients are active.","","## Historical result corrections","","The earlier `c4_joint_dimensioning` D3_TAS result lost 2,086 F13 packets out of 375,000 offered (0.5563%) at the application population level. This remains a separate gate decision: its configured flow gate passed, but the loss is not zero. Reconciled queue-overflow counts at CSW.eth[3]/TC4 were 41,107: F13 2,086, F21 18,473, F22 20,548. Across D1–D3, all positive overflow counters were on this egress; individual drop IDs are not present in the current derived audit. The combined evidence is compatible with reduced downstream CBS reservation, burst release from HPC, and TAS restrictions; aggregate counts do not isolate their causal shares.","","The corrected natural F13 episode analysis uses increments above a local baseline. Maximum increments exceeded the formerly cited 53-frame episode: D1 TAS 113 frames, D2 TAS 110, D3 TAS 106; D3 noTAS 11. The local Z3 queue recovered those observed episodes in approximately 443, 430, 413, and 34 ms respectively, but that is recovery of packets that survived upstream. Upstream loss reduces the arrival population at Z3 and cannot demonstrate service for the full offered demand.","","The older `c4_joint_dimensioning` D3_TAS trace has four F08 and fourteen F09 deadline misses. The saved stage trace decomposes them across HPC wait (~81 µs), CSW wait (~11–11.6 µs), final serialization (5.76 µs), and propagation; the maxima are 100.652 µs (F08) and 100.702 µs (F09). This is phase-sensitive end-to-end behavior, not evidence that adding only the observed 0.7 µs is sufficient. These misses must not be attributed to the separately configured D3 profile in this decision study: its measured L2/A1 maximum F08/F09/F10 latencies in seed41 are 77.804/77.879/77.826 µs with zero misses and zero drops.","","## Candidate design and outcomes","","D1–D3 were selected offline before their new execution using the preregistered bounded design family and normalized CBS increase cost; D3 was the lowest-cost eligible candidate after D1 failed its seed41 gates. This identifies the best of the tested eligible designs, not a global optimum. The exact gates, CBS contracts, and profiles remain in the run JSON and candidate contract.","","| Cell / seed | Treatments | Application | Stability | Sampled sync | Drops | Interpretation |","|---|---|---:|---:|---:|---:|---|","| L2/A1, 41 | D1, D2, D3 TAS/noTAS; B and C3 references | D1 TAS fails; D2/D3 pass | D1–D3 pass | Pass in sampled checks | D3 zero; see individual reports | D3 selected among eligible profiles |","| L2/A1, 43 | D3 TAS, D3 noTAS, C3_sync | All pass | All pass | Pass | 0 each | Fixed D3 passed this exploratory seed |","| L2/A1, 47 | D3 TAS, D3 noTAS, C3_sync | All pass | All pass | Pass | 0 each | Fixed D3 passed this exploratory seed |","| L0/A0, 41 | D3 TAS, D3 noTAS, C3_sync | All fail | All pass | Sampled pass | 72,373 each | Common failure exists in C3 control; not TAS-specific |","| L1/A1, 41 | D3 TAS, D3 noTAS, C3_sync | All fail | All fail | Sampled pass | 44,956 / 34,071 / 59,460 | Common operating-cell problem; D3 TAS is not viable here |","","At L0/A0, the 72,373 drops are identical across all arms: 36,778 at Z1.ZSW.eth[0]/TC4 plus 35,595 at Z2.ZSW.eth[0]/TC4. At L1/A1, the drops are distributed as follows:","","| Treatment | CSW.eth[3]/TC4 | Z1.ZSW.eth[0]/TC4 | Z2.ZSW.eth[0]/TC4 | Total |","|---|---:|---:|---:|---:|","| D3_TAS | 10,885 | 15,673 | 18,398 | 44,956 |","| D3_noTAS | 0 | 15,673 | 18,398 | 34,071 |","| C3_sync | 25,389 | 15,673 | 18,398 | 59,460 |","","L1 failures are not attributable to TAS alone: noTAS and C3_sync also fail, and all three share the Z1/Z2 loss counters. D3_TAS additionally loses at CSW→Z3; C3_sync has the larger CSW count. Flow-level populations and deadline/image gates are preserved in the JSON.","","## Interpretation and recommendation","","The evidence supports a bounded statement: among the three prospectively tested GCL/CBS candidates, D3 is promising at L2/A1 across the three tested seeds, while the tested load-scaled D3 profile is not viable across L0/A0 and L1/A1; C3 controls fail in those cells too. Therefore the study does not justify freezing C4 or starting the official campaign. It also does not demonstrate general incompatibility. A prospective C4 revision would need an explicit per-load construction rule and must address common low-load Z1/Z2 overloads and L1 instability before another viability claim. Any next pilot should preserve paired noTAS/C3 controls and test the specific cell-level cause rather than retune after outcomes.","","## Reproducibility and preserved evidence","","- Protocol and candidate selection: [`protocol.md`](../protocol.md), [`dimensioning.json`](dimensioning.json), [`selected_candidate.json`](selected_candidate.json).","- Input correction and historical F13/brake audit: [`audit/audit.md`](../audit/audit.md), [`audit_corrected_inputs.json`](../audit_corrected_inputs.json), [`audit/d3_tas_brake_stage_traces.json`](../audit/d3_tas_brake_stage_traces.json).","- Conditional results: [`conditional_L2_A1_seed43.json`](conditional_L2_A1_seed43.json), [`conditional_L2_A1_seed47.json`](conditional_L2_A1_seed47.json), [`conditional_L0_A0_seed41.json`](conditional_L0_A0_seed41.json), [`conditional_L1_A1_seed41.json`](conditional_L1_A1_seed41.json).","- Full structured comparison: [`final_results_2026-10-20.json`](final_results_2026-10-20.json).","- Checkpoint and completion ledger: [`checkpoint.json`](checkpoint.json).","- Active jobs: none. New raw packet/event traces were kept compressed where needed for audit; earlier pilot artifacts were not deleted.","","## Metric caveats","","The overflow counters here cover post-warm-up through drain, as recorded by the runner; receiver populations cover offered/received packets in the run's measurement accounting. Do not compare them as if their time windows were identical. F13 recovered locally after upstream filtering/loss, so local recovery is not full-demand recovery. Continuous clock conformance is not verified. The historical D3 brake trace does not record application reception timestamps directly; receive times are reconstructed from the last PHY transmit-end plus the configured 100 ns propagation, which matches the application's latency definition.",""]
    md += ["","Execution accounting: 20 logical methodological treatments are complete. Eighteen were newly run and two equivalent controls were reused. One extra technical-invalid attempt and its valid technical replacement are retained separately for the same D1_TAS slot; they do not enlarge the candidate count.","","Candidate reservation totals and gate windows were read from the preregistered `dimensioning.json` (port sums include all CBS classes):","","| Candidate | TC4 open / 100 µs | TC7 open / 100 µs | CSW.eth[3] CBS total | HPC.eth[0] CBS total |","|---|---:|---:|---:|---:|","| D1 | 82 µs | 30 µs | 479.910 Mb/s (47.99%) | 275.610 Mb/s (27.56%) |","| D2 | 50 µs | 30 µs | 734.748 Mb/s (73.47%) | 421.963 Mb/s (42.20%) |","| D3 | 55 µs | 30 µs | 707.607 Mb/s (70.76%) | 406.375 Mb/s (40.64%) |","","All listed port sums are below the 75% cap. They are reservation totals, not a guarantee of service under gates; the test results remain empirical and paired with noTAS controls.","","The low-cell flow failures are present in the full JSON. In L0/A0, all arms share F02/F03 packet and image misses, F04/F05 packet deadline misses despite complete images, F06/F07 packet deadline misses, and F21/F22 losses; C3_sync additionally has F13 deadline misses. In L1/A1, all arms share F02/F03 camera losses/image misses, F06/F07 deadline misses, and F21/F22 losses. C3_sync also has severe F13 deadline misses; D3_TAS has overflow at CSW→Z3 while D3_noTAS does not. Thus the common low-cell failures predate or exist without TAS, while the additional CSW overflow is treatment-dependent.",""]
    (OUT/"final_analysis_2026-10-20.md").write_text("\n".join(md))
    print(f"wrote {OUT/'final_analysis_2026-10-20.md'} and {OUT/'final_results_2026-10-20.json'} with {len(runs)} run reports")

if __name__=="__main__": main()
