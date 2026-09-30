package zonal_ivn_tsn.common;

// Observes real PHY egress packets, class queues and drops; does not alter traffic.
simple TrafficAudit
{
    parameters:
        @class(TrafficAudit);
        @display("i=block/checker;t=Wire / VLAN / PCP audit");
}
