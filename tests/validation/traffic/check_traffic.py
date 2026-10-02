#!/usr/bin/env python3
"""Independent checks of emitted schedules, byte conservation and observed wire paths.

Usage: python3 tests/validation/traffic/check_traffic.py <run-directory>
The CSV inputs are the canonical P1 catalog. No INET or third-party Python modules
are needed to recheck the exported evidence.
"""
import csv
import json
import math
import re
from collections import defaultdict
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / 'simulations/zonal/traffic'


def read(path):
    # Traffic release schedules can be very large single CSV fields (one
    # serialized field per release row); Python's default 128 KiB cap is too
    # small for the P1 high-load matrices.
    csv.field_size_limit(sys.maxsize)
    with path.open() as file:
        return list(csv.DictReader(file))


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def close(a, b, context):
    require(math.isclose(float(a), float(b), rel_tol=0, abs_tol=2e-9), f'{context}: {a} != {b}')


ZONES = {
    'Z1': ['LiDAR1', 'CAM1', 'BRAKE1', 'WINDOW1', 'AUDIO1', 'DISPLAY1', 'BE1'],
    'Z2': ['RADAR1', 'CAM2', 'BRAKE2', 'WINDOW2', 'AUDIO2', 'DISPLAY2', 'BE2'],
    'Z3': ['RADAR2', 'CAM3', 'CAM4', 'BRAKE3', 'WINDOW3', 'AUDIO3', 'BE3'],
}


def zone(node):
    return next(z for z, devices in ZONES.items() if node in devices or node == z + '.ZCPU')


def access_port(node):
    return 1 if node.endswith('.ZCPU') else ZONES[zone(node)].index(node) + 2


def route(source, destination):
    def eth(node, port):
        return f'ZonalIVN.{node}.eth[{port}]'
    path = [eth(source, 0)]
    if source == 'HPC':
        z = zone(destination)
        return path + [eth('CSW', int(z[1])), eth(z + '.ZSW', access_port(destination))]
    src_zone = zone(source)
    if destination == 'HPC':
        return path + [eth(src_zone + '.ZSW', 0), eth('CSW', 0)]
    dst_zone = zone(destination)
    if dst_zone == src_zone:
        return path + [eth(dst_zone + '.ZSW', access_port(destination))]
    return path + [eth(src_zone + '.ZSW', 0), eth('CSW', int(dst_zone[1])),
                   eth(dst_zone + '.ZSW', access_port(destination))]


def tuple_counts(row, overhead=0):
    if row is None:
        return (0, 0, 0)
    n = int(row['packets'])
    return n, int(row['sequence_sum']), int(row.get('app_bytes', row.get('bytes'))) - overhead * n


def check_run(directory):
    flows = {r['flow_id']: r for r in read(DATA / 'flows.csv')}
    signatures = {r['signature_id']: r for r in read(DATA / 'transients.csv')}
    run = read(directory / 'run.csv')[0]
    k, warmup, duration = (float(run[x]) for x in ['factor', 'warmup', 'measurement'])
    require(k == [0.5, 1, 2.5, 4][int(run['load'])], 'Load factor mismatch')
    require(run['volume_layer'] == 'app', 'Transient volume must be application bytes')
    end = warmup + duration
    only_transients = run['transients_only'] == '1'
    source_pre_shaping = run.get('source_pre_shaping', '0') == '1'
    events = read(directory / 'events.csv')
    by_event = {(r['flow'], int(r['block'])): r for r in events}
    require(len(by_event) == len(events) == 2 * int(duration), 'Missing or duplicate events')
    for block in range(int(duration)):
        e1, e2 = [by_event[f, block] for f in ['F21', 'F22']]
        close(e1['start'], warmup + block + .005, 'F21 start')
        close(e2['start'], float(e1['start']) + (float(e1['duration']) + .010 if run['aggregation'] == 'A0' else 0), 'F22 start')
        for event in [e1, e2]:
            signature = signatures[event['signature']]
            close(event['duration'], float(signature['duration_ms']) / 1000, 'Empirical duration')
            require(int(event['volume_bytes']) == int(signature['volume_bytes']), 'Empirical volume changed')
            require(float(event['start']) + float(event['duration']) <= warmup + block + 1 + 1e-12, 'Event crosses block')
    if run['exhaustive'] == '1':
        for fid in ['F21', 'F22']:
            require({e['signature'] for e in events if e['flow'] == fid} == set(signatures), f'{fid}: incomplete signature sweep')

    releases = defaultdict(list)
    for row in read(directory / 'releases.csv'):
        releases[row['flow']].append(row)
    applications = {}
    for path in directory.glob('F*-*.csv'):
        row = read(path)[0]
        applications[row['flow'], row['node'], row['role']] = row
    wires = {(r['interface'], r['flow']): r for r in read(directory / 'wire.csv')}
    queues = {(r['interface'], r['flow']): r for r in read(directory / 'queues.csv')}
    drops = {(r['interface'], r['flow']): r for r in read(directory / 'drops.csv')}
    expected_wire_keys = set()
    summary = {'run': run, 'source_packets': 0, 'drops': sum(int(r['packets']) for r in drops.values()),
               'pending_at_simulation_end': [], 'flows': {}}
    pending_by_queue = defaultdict(dict)

    for fid, f in flows.items():
        expected = []  # time, count, app bytes per packet, event block
        if f['family'] == 'transient':
            for block in range(int(duration)):
                event = by_event[fid, block]
                volume = int(event['volume_bytes'])
                n = math.ceil(volume / 1472)
                for j in range(n):
                    expected.append((float(event['start']) + float(event['duration']) * j / n,
                                     1, min(1472, volume - 1472 * j), block))
        elif not only_transients:
            period = float(f['period_us']) / 1e6 / (k if f['scalable'] == '1' else 1)
            phase = int(f['phase_numerator']) / int(f['phase_denominator'])
            offset = float(f['offset_us']) / 1e6
            if f['family'] == 'camera':
                offset = 0 if run['aggregation'] == 'A1' else phase * period
            if f['family'] == 'best_effort':
                offset = phase * period
            n = math.ceil(round((end - offset) / period, 9))
            if f['family'] == 'camera' and source_pre_shaping:
                limit = 324e-6 if fid in ('F02', 'F03') else 500e-6
                spacing = min(limit, period / 30)
                # Match the C++ operations exactly: each double parameter is
                # converted to SimTime ticks first, then the integral period
                # and spacing are multiplied by cycle/packet. Quantizing only
                # the final timestamp differs by one packet at some boundaries
                # (e.g. C/30=213333.333... ps).
                ticks_per_second = 10**12  # OMNeT++ default simtime-resolution: 1 ps
                offset_ticks = round(offset * ticks_per_second)
                period_ticks = round(period * ticks_per_second)
                spacing_ticks = round(spacing * ticks_per_second)
                end_ticks = round(end * ticks_per_second)
                cycle_count = (end_ticks - offset_ticks + period_ticks - 1) // period_ticks
                expected = [((offset_ticks + cycle * period_ticks + packet * spacing_ticks) /
                             ticks_per_second, 1, int(f['app_bytes']), -1)
                            for cycle in range(cycle_count) for packet in range(30)]
            else:
                expected = [(offset + j * period, int(f['packets_per_cycle']), int(f['app_bytes']), -1)
                            for j in range(n)]
        actual = releases[fid]
        require(len(actual) == len(expected), f'{fid} releases: {len(actual)} != {len(expected)}')
        for row, (t, count, size, block) in zip(actual, expected):
            close(row['time'], t, f'{fid} release time')
            require((int(row['count']), int(row['app_bytes']), int(row['block'])) == (count, size, block), f'{fid} packetization')
        n = sum(e[1] for e in expected)
        byte_count = sum(e[1] * e[2] for e in expected)
        measured = [e for e in expected if e[0] >= warmup - 1e-12 and e[0] < end]
        tx = applications[fid, f['source'], 'tx']
        expected_counts = (n, n * (n - 1) // 2, byte_count)
        require(tuple_counts(tx) == expected_counts, f'{fid} generated counts/bytes/sequence mismatch')
        require(int(tx['measured_packets']) == sum(e[1] for e in measured), f'{fid} measurement cohort count')
        require(int(tx['measured_app_bytes']) == sum(e[1] * e[2] for e in measured), f'{fid} measurement cohort bytes')
        if n:
            close(tx['first'], expected[0][0], f'{fid} first release')
            close(tx['last'], expected[-1][0], f'{fid} last release')
        source_wire_bytes = sum(count * (max(64, size + 50) + 20) for _, count, size, _ in expected)
        info = {'generated_packets': n, 'application_bytes': byte_count,
                'offered_wire_bytes': source_wire_bytes, 'deadline_us': f['deadline_us'], 'receivers': {}}
        summary['source_packets'] += n
        for destination in f['destinations'].split(';'):
            current = expected_counts
            for interface in route(f['source'], destination):
                key = interface, fid
                if n:
                    expected_wire_keys.add(key)
                lost = tuple_counts(drops.get(key), 50)
                queued = queues.get(key)
                if queued is not None:
                    require(tuple_counts(queued, 50) == current, f'{key} queue arrival mismatch')
                transmitted = tuple_counts(wires.get(key), 70)
                residual = tuple(c - t - d for c, t, d in zip(current, transmitted, lost))
                require(all(value >= 0 for value in residual),
                        f'{key} conservation has negative residual: incoming {current}, '
                        f'transmitted {transmitted}, dropped {lost}')
                if any(residual):
                    # CBS may legitimately leave packets in a class queue at the
                    # fixed P1 simulation stop. Do not call them drops: require
                    # the residual to be present in the corresponding final
                    # queue occupancy recorded by OMNeT++.
                    tc = int(f['traffic_class'])
                    previous = pending_by_queue[key[0], tc].get(fid)
                    if previous is None or residual[0] > previous[0]:
                        pending_by_queue[key[0], tc][fid] = residual
                current = transmitted
            rx = applications[fid, destination, 'rx']
            require(tuple_counts(rx) == current, f'{fid} sink {destination}: missing/extra packets')
            require(int(rx['duplicates_or_reorder']) == 0, f'{fid}: duplicate/reordered packets')
            close(rx['deadline_s'], float(f['deadline_us'] or 0) / 1e6, f'{fid} deadline')
            info['receivers'][destination] = {
                'packets': int(rx['packets']),
                'measured_packets': int(rx['measured_packets']),
                'measured_app_bytes': int(rx['measured_app_bytes']),
                'deadline_misses': int(rx['deadline_misses']),
                'max_latency_s': float(rx['max_latency'])}
        summary['flows'][fid] = info
    if pending_by_queue:
        sca = next(iter(directory.parent.glob(f'{directory.name.replace("-0", "")}-#*.sca')), None)
        require(sca is not None, 'Pending packets found but scalar file is unavailable for queue reconciliation')
        queue_last = {}
        for line in sca.open(errors='replace'):
            if not line.startswith('scalar ') or ' queueLength:last ' not in line:
                continue
            fields = line.split()
            match = re.search(r'^(.*\.macLayer\.queue\.queue\[(\d+)\])$', fields[1])
            if match:
                queue_last[match.group(1), int(match.group(2))] = int(float(fields[-1]))
        for (interface, tc), by_flow in pending_by_queue.items():
            module = f'{interface}.macLayer.queue.queue[{tc}]'
            residual_packets = sum(residual[0] for residual in by_flow.values())
            observed = queue_last.get((module, tc))
            require(observed is not None and residual_packets <= observed,
                    f'{interface} TC{tc}: {residual_packets} untransmitted packets are not '
                    f'accounted for by final queue occupancy ({observed})')
            summary['pending_at_simulation_end'].extend(
                {'interface': interface, 'flow': flow, 'traffic_class': tc,
                 'packets': residual[0], 'sequence_sum': residual[1],
                 'application_bytes': residual[2]}
                for flow, residual in by_flow.items())
        summary['pending_packet_count_at_simulation_end'] = sum(
            entry['packets'] for entry in summary['pending_at_simulation_end'])
    else:
        summary['pending_packet_count_at_simulation_end'] = 0
    require(set(wires) == expected_wire_keys, f'Unexpected/missing egresses: {set(wires) ^ expected_wire_keys}')
    if not only_transients:
        require(len(applications) == 45, 'Expected 22 senders and 23 receivers')
    (directory / 'validation.json').write_text(json.dumps(summary, indent=2) + '\n')
    return summary


def check_pairing(output):
    reference = None
    for level in range(4):
        for aggregation in range(2):
            events = read(output / f'Validate_L{level}_A{aggregation}-0/events.csv')
            samples = [(r['flow'], r['block'], r['signature'], r['duration'], r['volume_bytes']) for r in events]
            if reference is None:
                reference = samples
            require(samples == reference, 'L/A changed the random realization')
    reseeded = read(output / 'ValidateReseed-0/events.csv')
    require([(r['flow'], r['block'], r['signature'], r['duration'], r['volume_bytes']) for r in reseeded] != reference,
            'Reseeding did not change transient samples')


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    result = check_run(Path(sys.argv[1]))
    print(f'PASS: schedules, sizes, VLAN/PCP audit, routes, multicast and packet accounting; '
          f'{result["drops"]} recorded drops, '
          f'{result["pending_packet_count_at_simulation_end"]} packets pending at simulation end.')
