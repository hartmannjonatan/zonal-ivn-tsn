import inet.networks.base.TsnNetworkBase;
import inet.node.ethernet.EthernetLink;
import inet.node.tsn.TsnDevice;
import inet.node.tsn.TsnSwitch;

package zonal_ivn_tsn.simulations.tsn_validation.mc05_asynchronous_traffic_shaper;

network Mc05AsynchronousTrafficShaper extends TsnNetworkBase
{
    parameters:
        @display("bgb=900,430");

    types:
        channel AccessLink extends EthernetLink
        {
            datarate = 1Gbps;
            delay = 1us;
        }

        channel OutputLink extends EthernetLink
        {
            datarate = 100Mbps;
            delay = 1us;
        }

    submodules:
        sourceReference: TsnDevice {
            @display("p=170,140");
        }

        sourceAggressive: TsnDevice {
            @display("p=170,290");
        }

        switch: TsnSwitch {
            @display("p=450,215");
        }

        receiver: TsnDevice {
            @display("p=730,215");
        }

    connections:
        sourceReference.ethg++ <--> AccessLink <--> switch.ethg++;
        sourceAggressive.ethg++ <--> AccessLink <--> switch.ethg++;
        switch.ethg++ <--> OutputLink <--> receiver.ethg++;
}