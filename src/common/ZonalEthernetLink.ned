package zonal_ivn_tsn.common;

import inet.node.ethernet.EthernetLink;

// P1 §2.4: full-duplex pairs use this channel once in each direction.
// LC, LB, LP, LA-H: default 1 Gbit/s; LA-L overrides to 100 Mbit/s.
channel ZonalEthernetLink extends EthernetLink
{
    datarate = default(1Gbps);
    length = default(20m);
    delay = 100ns;
    ber = 0;
    per = 0;
    @display("ls=#2563eb,2");
}
