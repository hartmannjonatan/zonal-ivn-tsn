#!/usr/bin/env python3
"""Check P1 topology against runtime parameters/tables exported by OMNeT++ 6.4.

Usage: python3 tests/validation/topology/check_topology.py <Topology*.sca>
No external Python packages are required. This is not a traffic-catalog test.
"""
import math
from pathlib import Path
import re
import shlex
import sys
from collections import deque


def check(path):
    params, scalars, attrs = {}, {}, {}
    for line in path.read_text().splitlines():
        if line.startswith(('par ', 'scalar ', 'attr configname ')):
            fields = shlex.split(line)
            if fields[0] == 'par':
                params[fields[1], fields[2]] = fields[3]
            elif fields[0] == 'scalar':
                scalars[fields[1], fields[2]] = float(fields[3])
            else:
                attrs[fields[1]] = fields[2]

    # Independent P1 endpoint allocation and fixed switch port contract.
    zones = {
        'Z1': ['LiDAR1', 'CAM1', 'BRAKE1', 'WINDOW1', 'AUDIO1', 'DISPLAY1', 'BE1'],
        'Z2': ['RADAR1', 'CAM2', 'BRAKE2', 'WINDOW2', 'AUDIO2', 'DISPLAY2', 'BE2'],
        'Z3': ['RADAR2', 'CAM3', 'CAM4', 'BRAKE3', 'WINDOW3', 'AUDIO3', 'BE3'],
    }
    high_rate = {'LiDAR1', 'CAM1', 'CAM2', 'CAM3', 'CAM4'}
    endpoints = {'HPC'} | {f'{z}.ZCPU' for z in zones} | set(sum(zones.values(), []))
    switches = {'CSW'} | {f'{z}.ZSW' for z in zones}
    nodes = endpoints | switches
    actual_nodes = {m.removeprefix('ZonalIVN.') for m, p in params if p == 'numEthInterfaces'}
    assert actual_nodes == nodes, f'Unexpected node inventory: {actual_nodes ^ nodes}'

    expected_channels, expected_rates, graph = {}, {}, {n: {} for n in nodes}

    def link(a, ai, b, bi, label, rate, a_gate=None, b_gate=None):
        graph[a][b] = ai
        graph[b][a] = bi
        for node, port, gate in [(a, ai, a_gate), (b, bi, b_gate)]:
            expected_rates[f'ZonalIVN.{node}.eth[{port}]'] = rate
            source_gate = gate or f'{node}.ethg$o[{port}]'
            expected_channels[f'ZonalIVN.{source_gate}.{label}'] = rate

    link('HPC', 0, 'CSW', 0, 'LC', 1e9)
    for index, (zone, devices) in enumerate(zones.items(), 1):
        link('CSW', index, f'{zone}.ZSW', 0, f'LB{index}', 1e9,
             b_gate=f'{zone}.uplink$o')
        link(f'{zone}.ZSW', 1, f'{zone}.ZCPU', 0, 'LP', 1e9)
        for i, device in enumerate(devices):
            fast = device in high_rate
            link(f'{zone}.ZSW', i + 2, device, 0,
                 f'LA_{"H" if fast else "L"}_{device}', 1e9 if fast else 1e8,
                 a_gate=f'{zone}.access$o[{i}]')

    actual_channels = {m for (m, p), v in params.items()
                       if p == 'typename' and 'ZonalEthernetLink' in v}
    assert actual_channels == set(expected_channels), 'Physical channel inventory mismatch'
    assert len(actual_channels) == 56  # 28 full-duplex links, two directed channels each
    for channel, rate in expected_channels.items():
        assert float(params[channel, 'datarate'].removesuffix('bps')) == rate, channel
        assert math.isclose(float(params[channel, 'delay'].removesuffix('s')), 1e-7), channel
        assert params[channel, 'ber'] == params[channel, 'per'] == '0', channel
        assert params[channel, 'disabled'] == 'false', channel
    actual_rates = {m: float(v.removesuffix('bps')) for (m, p), v in params.items()
                    if p == 'bitrate' and re.fullmatch(r'ZonalIVN\..*\.eth\[\d+\]', m)}
    assert actual_rates == expected_rates, 'Interface/channel bitrate mismatch'
    for node in nodes:
        assert int(params[f'ZonalIVN.{node}', 'numEthInterfaces']) == len(graph[node]), node
        for feature in ['hasCutthroughSwitching', 'hasTimeSynchronization',
                        'hasFramePreemption', 'hasStreamRedundancy', 'hasEgressTrafficShaping']:
            assert params[f'ZonalIVN.{node}', feature] == 'false', (node, feature)
    for node in endpoints:
        assert params[f'ZonalIVN.{node}', 'forwarding'] == 'false', node

    # The initialized static forwarding tables must match unique P1 tree paths.
    # This also checks that compound-module boundaries reach the actual ZSW ports.
    for switch in switches:
        assert params[f'ZonalIVN.{switch}', 'hasStp'] == 'false', switch
        table = params[f'ZonalIVN.{switch}.macTable', 'forwardingTable']
        rules = set(re.findall(r'address: "([\w-]+)", interface: "(eth\d+)"', table))
        for destination in endpoints:
            queue = deque([(switch, [])])
            visited = {switch}
            while queue:
                node, route = queue.popleft()
                if node == destination:
                    break
                for neighbor in graph[node]:
                    if neighbor not in visited:
                        visited.add(neighbor)
                        queue.append((neighbor, route + [neighbor]))
            else:
                raise AssertionError(f'No route: {switch} -> {destination}')
            mac = params[f'ZonalIVN.{destination}.eth[0]', 'address'].strip('"')
            expected = (mac, f'eth{graph[switch][route[0]]}')
            assert expected in rules, (switch, destination, expected)
            assert {port for addr, port in rules if addr == mac} == {expected[1]}, destination

    config = attrs['configname']
    if config == 'TopologyConnectivity':
        expected = {'HPC': 48, 'LiDAR1': 2, 'Z1.ZCPU': 2, 'Z2.ZCPU': 2}
        for source, count in expected.items():
            app = f'ZonalIVN.{source}.app[0]'
            assert scalars[app, 'pingTxSeq:count'] == scalars[app, 'pingRxSeq:count'] == count, app
        print('OK: 54/54 ICMP responses; all endpoints, local CPU and cross-zone paths.')
    elif config in {'TopologyValidation', 'SmokeTest'}:
        assert all(v == '0' for (m, p), v in params.items() if p == 'numApps'), 'Unexpected applications'
    else:
        raise AssertionError(f'Unsupported validation configuration: {config}')
    print('OK: 29 nodes, 28 full-duplex links, 56 interface rates, 100 ns, static L2 paths.')


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    check(Path(sys.argv[1]))
