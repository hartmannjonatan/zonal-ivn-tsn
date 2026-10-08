# Zonal model implementation

- `networks/ZonalIVN.ned` composes the central switch, three zone switches, zone controllers, and vehicle endpoints. Switches and zone CPUs are separate modules so routes and queue behavior can be inspected at each Ethernet egress.
- `configs/` layers topology, static forwarding/classification, catalog bindings, offered-load and aggregation settings, recording, and treatment-specific mechanisms. `omnetpp.ini` includes these layers for the runnable configurations.
- `traffic/` contains canonical CSV inputs and generated OMNeT++ catalog files. Generation details are in [`docs/traffic-catalog/README.md`](../../docs/traffic-catalog/README.md).

The implementation uses explicit VLAN/MAC bindings, static forwarding, PCP-to-traffic-class classification, and multicast forwarding for F14. Each traffic class has a separate FIFO queue; C0/C1 use strict priority, while C2/C3 enable custom CBS only on egresses with positive permanent reservations. Queue capacities are configured by egress role in the INI files. These are implementation notes; P1 remains the source for experiment requirements.
