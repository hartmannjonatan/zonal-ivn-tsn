package zonal_ivn_tsn.applications;

import inet.queueing.sink.PassivePacketSink;

// Sink of a request/response client (UdpApp + UdpEchoApp server): the echoed
// packet keeps its CreationTimeTag, so dataAge at reception is the round-trip time.
simple RttSink extends PassivePacketSink
{
    parameters:
        @class(inet::queueing::PassivePacketSink);
        @statistic[roundTripTime](title="request/response round-trip time"; source="dataAge(packetPushed)"; unit=s; record=vector,histogram; interpolationmode=none);
        @statistic[responses](title="responses received"; source=packetPushed; record=count; interpolationmode=none);
}
