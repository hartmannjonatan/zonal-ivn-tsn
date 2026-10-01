package zonal_ivn_tsn.applications;
import inet.applications.contract.IApp;

// One application per flow and role. All packet/timing fields come from TrafficPlan.
simple CatalogUdpApp like IApp
{
    parameters:
        @class(CatalogUdpApp);
        int flowId;
        bool source;
        @display("i=block/app");
        @signal[packetSent](type=inet::Packet);
        @signal[packetReceived](type=inet::Packet);
        @signal[latency](type=simtime_t);
        @statistic[latency](unit=s; record=histogram; interpolationmode=none);
        @signal[imageCompletionLatency](type=simtime_t);
        @statistic[imageCompletionLatency](unit=s; record=vector,histogram; interpolationmode=none);
    gates:
        input socketIn;
        output socketOut;
}
