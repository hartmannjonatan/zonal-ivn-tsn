# Reusable modules

- `applications/` — catalog-driven UDP generation and packet coloring for Qtenv visualization.
- `common/TrafficPlan` — deterministic flow, image, and transient-event planning shared by traffic sources and validators.
- `common/TrafficAudit` — runtime counters and audit signals used by result extraction.
- `common/ZonalEthernetLink` — reusable Ethernet link configuration for the zonal model.
- `nodes/ZonalController` — zone controller composition used in the NED topology.

The `Makefile` builds these modules into `src/zonal-ivn-tsn` against the configured INET installation.
