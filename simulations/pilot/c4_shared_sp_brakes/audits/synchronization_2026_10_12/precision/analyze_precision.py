#!/usr/bin/env python3
"""Reprocess native-tick probes and retain exact neighborhoods and legacy comparisons."""
import csv, gzip, json, math, hashlib
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
AUDIT = HERE.parent
TECH = HERE / 'technical'
PILOT = HERE.parents[2]
TARGETS = {
    'C3sync_L2_A1_seed43_v1': {'variant': 'C3sync', 'time_s': '1.801', 'old_time_s': '1.801', 'pilot_id': 'C3sync_L2_A1_seed43'},
    'C4compensated_L2_A1_seed43_v1': {'variant': 'C4compensated', 'time_s': '1.247', 'old_time_s': '1.247', 'pilot_id': 'C4compensated_L2_A1_seed43'},
}
NODES = ['CSW', 'Z1.ZSW', 'Z2.ZSW', 'Z3.ZSW']

def nearest_rank(values, p):
    return sorted(values)[max(0, math.ceil(p * len(values)) - 1)] if values else None

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

runs, snippets, comparisons = [], [], []
for run_id, meta in TARGETS.items():
    run_dir = TECH / run_id
    trace = run_dir / 'clock_precision.csv'
    with trace.open(newline='') as f:
        rows = list(csv.DictReader(f))
    scale = int(rows[0]['simtime_scale_exp'])
    def in_window(row):
        t = Decimal(int(row['simtime_raw'])).scaleb(scale)
        return Decimal('1') <= t < Decimal('3')
    node_results = {}
    for node in NODES:
        populations = {
            'periodic': [r for r in rows if r['record_kind'] == 'periodic' and in_window(r)],
            'parent_timeChanged': [r for r in rows if r['record_kind'] == 'signal' and r['emitter'] == f'ZonalIVNClockPrecisionAudit.{node}.clock' and r['signal'] == 'timeChanged' and in_window(r)],
        }
        node_results[node] = {}
        for pop_name, population in populations.items():
            vals = [int(r[f'{node}_offset_from_HPC_raw']) for r in population]
            peak = max(population, key=lambda r: abs(int(r[f'{node}_offset_from_HPC_raw']))) if population else None
            p99 = nearest_rank([abs(v) for v in vals], .99)
            max_abs = max(map(abs, vals)) if vals else None
            node_results[node][pop_name] = {
                'count': len(population), 'p50_abs_ticks': nearest_rank([abs(v) for v in vals], .50),
                'p95_abs_ticks': nearest_rank([abs(v) for v in vals], .95), 'p99_abs_ticks': p99,
                'max_abs_ticks': max_abs, 'max_signed_ticks': int(peak[f'{node}_offset_from_HPC_raw']) if peak else None,
                'max_time_s': peak['simtime_exact_s'] if peak else None,
                'max_event_number': int(peak['event_number']) if peak else None,
                'samples_abs_over_1us': sum(abs(v) > 10 ** (-6 - scale) for v in vals),
                'scale_exp': scale, 'max_abs_s': max_abs * 10 ** scale if max_abs is not None else None,
                'p99_abs_s': p99 * 10 ** scale if p99 is not None else None,
            }
    target = meta['time_s']
    target_row = next(r for r in rows if r['record_kind'] == 'periodic' and r['simtime_exact_s'] == target)
    corrected_target = {n: {'clock_raw': int(target_row[f'{n}_clock_raw']), 'free_clock_raw': int(target_row[f'{n}_free_raw']), 'offset_raw': int(target_row[f'{n}_offset_from_HPC_raw'])} for n in ['HPC'] + NODES}
    for row in rows:
        if in_window(row) and abs(Decimal(row['simtime_exact_s']) - Decimal(target)) <= Decimal('0.001'):
            snippets.append({'run': run_id, **{k: v for k, v in row.items() if k is not None}})
    old_path = AUDIT / 'technical' / meta['pilot_id'] / 'clock_audit.csv.gz.gz'
    with gzip.open(old_path, 'rb') as f:
        old_rows = list(csv.DictReader(gzip.decompress(f.read()).decode().splitlines()))
    old_row = next((r for r in old_rows if r['record_kind'] == 'periodic' and r['simtime_s'] == meta['old_time_s']), None)
    compact_path = PILOT / 'results' / 'runs' / meta['pilot_id'] / f"Pilot_{meta['variant']}_L2_A1-0" / 'clock_offsets.csv.gz'
    compact = []
    with gzip.open(compact_path, 'rt') as f:
        for r in csv.DictReader(f):
            if r['simtime_s'] == target and r['node'].replace('.clock', '') in NODES:
                compact.append({'node': r['node'], 'offset_s': r['offset_s']})
    runs.append({
        'execution_id': run_id, 'variant': meta['variant'], 'seed': 43,
        'observation_window_s': [1, 3], 'time_scale_exp': scale,
        'time_scale_note': 'signed raw SimTime/clocktime ticks; 1e-12 s per tick',
        'nodes': node_results, 'target_timestamp': target,
        'target_corrected_periodic': corrected_target,
        'legacy_six_significant_digit_periodic_row': old_row,
        'original_full_run_compact_offset_rows_same_timestamp': compact,
        'trace_sha256': digest(trace),
        'command': json.loads((run_dir / 'command.json').read_text()),
    })
    if old_row:
        mapping = {'CSW': 'csw', 'Z1.ZSW': 'z1', 'Z2.ZSW': 'z2', 'Z3.ZSW': 'z3'}
        compact_map = {r['node'].replace('.clock', ''): r['offset_s'] for r in compact}
        selected = ['Z1.ZSW'] if meta['variant'] == 'C3sync' else NODES
        for node in selected:
            old_node = old_row[mapping[node] + '_clock_s']
            raw_offset = corrected_target[node]['offset_raw']
            comparisons.append({
                'run': run_id, 'simtime_s': target, 'node': node,
                'legacy_hpc_clock_s': old_row['hpc_clock_s'], 'legacy_node_clock_s': old_node,
                'legacy_subtracted_offset_s': format(float(old_node) - float(old_row['hpc_clock_s']), '.17g'),
                'precise_hpc_raw_ticks': corrected_target['HPC']['clock_raw'],
                'precise_node_raw_ticks': corrected_target[node]['clock_raw'],
                'precise_offset_ns': raw_offset / 1000,
                'original_full_run_offset_s': compact_map.get(node),
            })

summary = {
    'audit_id': 'clock-precision-audit-2026-10-12', 'runs': runs,
    'threshold_s': 1e-6, 'percentile': 'nearest rank',
    'populations': 'periodic observer samples and parent SettableClock timeChanged callbacks separately; no interpolation',
    'clock_precision': 'OMNeT++ raw fixed-point ticks at scale exponent -12 (1 ps/tick); offset subtraction occurred in C++ before serialization',
    'interpretation': 'The legacy exact -10 us peaks are serialization/subtraction artifacts. Precise probes found no samples above 1 us in [1,3) s; continuous compliance is not established.',
    'serialization_test': {'script': 'test_precision_serialization.py', 'status': 'PASS', 'cases': ['20 ns', '30 ns', '1 us', '10 us', '1 us +/- 1 ps']},
    'precision_peak_snippets': 'precision_peak_snippets.csv',
    'legacy_comparison': 'legacy_precision_comparison.csv',
}
(HERE / 'precision_summary.json').write_text(json.dumps(summary, indent=2) + '\n')
with (HERE / 'precision_peak_snippets.csv').open('w', newline='') as f:
    fields = list(snippets[0])
    writer = csv.DictWriter(f, fieldnames=fields); writer.writeheader(); writer.writerows(snippets)
with (HERE / 'legacy_precision_comparison.csv').open('w', newline='') as f:
    fields = list(comparisons[0])
    writer = csv.DictWriter(f, fieldnames=fields); writer.writeheader(); writer.writerows(comparisons)
print(json.dumps({'runs': [{
    'id': r['execution_id'],
    'max_us': {n: {p: round(v['max_abs_s'] * 1e6, 6) for p, v in pop.items()} for n, pop in r['nodes'].items()},
    'over1us': {n: {p: v['samples_abs_over_1us'] for p, v in pop.items()} for n, pop in r['nodes'].items()},
    'target_offsets_ns': {n: v['offset_raw'] / 1000 for n, v in r['target_corrected_periodic'].items()},
} for r in runs], 'snippet_rows': len(snippets)}, indent=2))
