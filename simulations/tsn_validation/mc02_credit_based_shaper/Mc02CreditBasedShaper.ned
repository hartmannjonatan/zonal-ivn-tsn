import inet.linklayer.configurator.common.MacForwardingTableConfigurator;
import inet.networklayer.configurator.ipv4.Ipv4NetworkConfigurator;
import inet.node.ethernet.Eth100M;
import inet.node.ethernet.Eth1G;
import inet.node.tsn.TsnDevice;
import inet.node.tsn.TsnSwitch;
import inet.visualizer.contract.IIntegratedVisualizer;

package zonal_ivn_tsn.simulations.tsn_validation.mc02_credit_based_shaper;

//
// MC02: validation of IEEE 802.1Qav Credit-Based Shaping.
//
// The two sources use 1 Gbit/s ingress links so that they do not become
// bottlenecks. Both streams compete for the 100 Mbit/s switch output.
//
network Mc02CreditBasedShaper
{
    parameters:
        @display("bgb=900,420");

    submodules:
        visualizer: <default(firstAvailableOrEmpty("IntegratedCanvasVisualizer"))>
                    like IIntegratedVisualizer if typename != "" {
            @display("p=100,80;is=s");
        }

        configurator: Ipv4NetworkConfigurator {
            @display("p=80,140");
        }

        forwardingTableConfigurator: MacForwardingTableConfigurator {
            @display("p=80,220");
        }

        sourceBe: TsnDevice {
            @display("p=250,120");
        }

        sourceShaped: TsnDevice {
            @display("p=250,300");
        }

        switch: TsnSwitch {
            @display("p=500,210");
        }

        receiver: TsnDevice {
            @display("p=760,210");
        }

    connections:
        // switch.eth[0]: best-effort ingress
        sourceBe.ethg++ <--> Eth1G <--> switch.ethg++;

        // switch.eth[1]: shaped-stream ingress
        sourceShaped.ethg++ <--> Eth1G <--> switch.ethg++;

        // switch.eth[2]: shared bottleneck where CBS is applied
        switch.ethg++ <--> Eth100M <--> receiver.ethg++;
}