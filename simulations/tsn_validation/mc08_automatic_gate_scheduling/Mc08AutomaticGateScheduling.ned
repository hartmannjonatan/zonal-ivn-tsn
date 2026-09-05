import inet.networks.base.TsnNetworkBase;
import inet.node.ethernet.Eth100M;
import inet.node.ethernet.Eth1G;
import inet.node.tsn.TsnDevice;
import inet.node.tsn.TsnSwitch;

package zonal_ivn_tsn.simulations.tsn_validation.mc08_automatic_gate_scheduling;

network Mc08AutomaticGateScheduling extends TsnNetworkBase
{
    parameters:
        @display("bgb=1000,500");

    submodules:
        sourceCritical: TsnDevice {
            parameters:
                numEthInterfaces = 1;
                @display("p=100,130");
        }

        sourceBackground: TsnDevice {
            parameters:
                numEthInterfaces = 1;
                @display("p=100,350");
        }

        switch1: TsnSwitch {
            parameters:
                numEthInterfaces = 3;
                @display("p=370,240");
        }

        switch2: TsnSwitch {
            parameters:
                numEthInterfaces = 2;
                @display("p=630,240");
        }

        receiver: TsnDevice {
            parameters:
                numEthInterfaces = 1;
                @display("p=890,240");
        }

    connections:
        sourceCritical.ethg++ <--> Eth1G <--> switch1.ethg++;
        sourceBackground.ethg++ <--> Eth1G <--> switch1.ethg++;

        switch1.ethg++ <--> Eth100M <--> switch2.ethg++;
        switch2.ethg++ <--> Eth100M <--> receiver.ethg++;
}