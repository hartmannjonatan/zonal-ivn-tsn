import inet.common.Module;
import inet.networklayer.configurator.contract.IL3NetworkConfigurator;
import inet.networklayer.configurator.contract.INetworkConfigurator;
import inet.node.ethernet.EthernetLink;
import inet.node.tsn.TsnDevice;
import inet.node.tsn.TsnSwitch;
import inet.visualizer.contract.IIntegratedVisualizer;

package zonal_ivn_tsn.simulations.tsn_validation.mc01_pcp_strict_priority;

network Mc01PcpStrictPriority extends Module
{
    parameters:
        bool hasGlobalArp = default(true);

        // Evita tráfego ARP interferindo no experimento.
        *.ipv4.arp.typename = default(hasGlobalArp ? "GlobalArp" : "Arp");

        @display("bgb=1000,450");

    submodules:
        sourceBe: TsnDevice {
            @display("p=280,130;i=device/pc");
        }

        sourceHp: TsnDevice {
            @display("p=280,320;i=device/pc");
        }

        switch: TsnSwitch {
            @display("p=610,225");
        }

        receiver: TsnDevice {
            @display("p=880,225;i=device/server");
        }

        visualizer: <default(firstAvailableOrEmpty("IntegratedCanvasVisualizer"))>
                    like IIntegratedVisualizer if typename != "" {
            @display("p=100,80;is=s");
        }

        configurator: <default("Ipv4NetworkConfigurator")>
                      like IL3NetworkConfigurator if typename != "" {
            @display("p=100,180;is=s");
        }

        macForwardingTableConfigurator:
            <default(hasGlobalArp ? "MacForwardingTableConfigurator" : "")>
            like INetworkConfigurator if typename != "" {
            @display("p=100,280;is=s");
        }

    connections:
        // Entradas rápidas: não queremos congestionamento nos emissores.
        sourceBe.ethg++ <--> EthernetLink {
            datarate = 1Gbps;
        } <--> switch.ethg++;

        sourceHp.ethg++ <--> EthernetLink {
            datarate = 1Gbps;
        } <--> switch.ethg++;

        // eth[2] do switch é a saída congestionada.
        switch.ethg++ <--> EthernetLink {
            datarate = 100Mbps;
        } <--> receiver.ethg++;
}