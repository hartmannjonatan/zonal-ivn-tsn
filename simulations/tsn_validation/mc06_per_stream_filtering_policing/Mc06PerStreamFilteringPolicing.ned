import inet.networks.base.TsnNetworkBase;
import inet.node.ethernet.EthernetLink;
import inet.node.tsn.TsnDevice;
import inet.node.tsn.TsnSwitch;

package zonal_ivn_tsn.simulations.tsn_validation.mc06_per_stream_filtering_policing;

network Mc06PerStreamFilteringPolicing extends TsnNetworkBase
{
    parameters:
        @display("bgb=850,400");

    submodules:
        sourceHealthy: TsnDevice {
            parameters:
                numEthInterfaces = 1;
                @display("p=120,120");
        }

        sourceMonitored: TsnDevice {
            parameters:
                numEthInterfaces = 1;
                @display("p=120,280");
        }

        switch: TsnSwitch {
            parameters:
                numEthInterfaces = 3;
                @display("p=430,200");
        }

        receiver: TsnDevice {
            parameters:
                numEthInterfaces = 1;
                @display("p=730,200");
        }

    connections:
        sourceHealthy.ethg[0] <--> EthernetLink <--> switch.ethg[0];
        sourceMonitored.ethg[0] <--> EthernetLink <--> switch.ethg[1];
        switch.ethg[2] <--> EthernetLink <--> receiver.ethg[0];
}
