# 10BASE-T1S feasibility test

Checks that a `TsnSwitch` port can act as the PLCA coordinator of a 10BASE-T1S
multidrop segment.

- `switch.eth[0]`: point-to-point 1 Gb/s link to `gbDevice`.
- `switch.eth[1]`: `EthernetPlcaInterface`, 10 Mb/s, PLCA node ID 0, connected
  through `EthernetMultidropLink` + `WireJunction` to `t1sDevice[0]` and
  `t1sDevice[1]` (PLCA node IDs 1 and 2, `plca_node_count = 3`).
- Traffic: UDP 64 B payload every 1 ms, `gbDevice -> t1sDevice[0]` (port 1000)
  and `t1sDevice[0] -> gbDevice` (port 1001).

```bash
source /path/to/omnetpp/setenv
export INET_ROOT=/path/to/inet
./run -u Cmdenv -c Feasibility
```

`MacForwardingTableConfigurator` is disabled because it crashes on topologies
with a `WireJunction`; the switch learns MAC addresses instead.

## Result (1 s, OMNeT++ 6.4.0, INET master 7b0a6de5ce)

| Direction | Sent | Received | Mean latency | Max latency |
|---|---|---|---|---|
| gbDevice -> t1sDevice[0] | 1001 | 1000 | 152.9 us | 209.3 us |
| t1sDevice[0] -> gbDevice | 1001 | 1000 | 152.3 us | 208.7 us |

The missing packet in each direction is in flight at the time limit. No
physical PLCA collisions; the MAC-level `collision` signal toggles because
PLCA asserts COL to defer the MAC until its transmit opportunity.
