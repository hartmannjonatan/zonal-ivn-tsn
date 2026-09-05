import inet.networks.base.TsnNetworkBase;
import inet.node.ethernet.EthernetLink;
import inet.node.tsn.TsnDevice;
import inet.node.tsn.TsnSwitch;

package zonal_ivn_tsn.simulations.tsn_validation.mc03_time_aware_shaper;

//
// Two traffic classes compete for the same 100 Mbit/s egress link.
// TAS is configured only on switch.eth[2], towards the receiver.
//
network Mc03TimeAwareShaper extends TsnNetworkBase
{
    parameters:
        @display("bgb=800,400");

    submodules:
        sourceBe: TsnDevice {
            @display("p=200,120");
        }

        sourceScheduled: TsnDevice {
            @display("p=200,280");
        }

        switch: TsnSwitch {
            @display("p=430,200");
        }

        receiver: TsnDevice {
            @display("p=680,200");
        }

    connections:
        // Fast ingress links avoid adding relevant ingress serialization delay.
        sourceBe.ethg++ <--> EthernetLink {
            datarate = 1Gbps;
            delay = 100ns;
        } <--> switch.ethg++;

        sourceScheduled.ethg++ <--> EthernetLink {
            datarate = 1Gbps;
            delay = 100ns;
        } <--> switch.ethg++;

        // Shared bottleneck where Strict Priority and TAS are compared.
        switch.ethg++ <--> EthernetLink {
            datarate = 100Mbps;
            delay = 100ns;
        } <--> receiver.ethg++;
}