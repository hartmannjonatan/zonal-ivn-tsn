import inet.common.Module;
import inet.networklayer.configurator.contract.IL3NetworkConfigurator;
import inet.networklayer.configurator.contract.INetworkConfigurator;
import inet.node.ethernet.EthernetLink;
import inet.node.ethernet.EthernetMultidropLink;
import inet.node.tsn.TsnDevice;
import inet.node.tsn.TsnSwitch;
import inet.physicallayer.wired.common.WireJunction;
import inet.visualizer.contract.IIntegratedVisualizer;

package zonal_ivn_tsn.simulations.t1s_feasibility;

// Feasibility test: TsnSwitch port 1 acts as the PLCA coordinator (node ID 0)
// of a 10BASE-T1S multidrop segment with two TsnDevices (node IDs 1 and 2).
// Port 0 connects a 1 Gb/s TsnDevice.
network T1sFeasibility extends Module
{
    parameters:
        bool hasGlobalArp = default(true);
        int plcaNodeCount = default(3);

        *.ipv4.arp.typename = default(hasGlobalArp ? "GlobalArp" : "Arp");

        @display("bgb=900,450");

    submodules:
        gbDevice: TsnDevice {
            @display("p=150,225;i=device/pc");
        }

        switch: TsnSwitch {
            eth[1].typename = "EthernetPlcaInterface";
            eth[1].plca.plca_node_count = parent.plcaNodeCount;
            eth[1].plca.local_nodeID = 0;
            @display("p=400,225");
        }

        junction: WireJunction {
            @display("p=600,225");
        }

        t1sDevice[2]: TsnDevice {
            eth[0].typename = "EthernetPlcaInterface";
            eth[0].plca.plca_node_count = parent.plcaNodeCount;
            eth[0].plca.local_nodeID = this.index + 1;
            @display("p=800,125,column,200;i=device/card");
        }

        visualizer: <default(firstAvailableOrEmpty("IntegratedCanvasVisualizer"))>
                    like IIntegratedVisualizer if typename != "" {
            @display("p=100,80;is=s");
        }

        configurator: <default("Ipv4NetworkConfigurator")>
                      like IL3NetworkConfigurator if typename != "" {
            @display("p=100,180;is=s");
        }

        // MacForwardingTableConfigurator segfaults on topologies containing a
        // WireJunction (null Interface on links touching the junction), so the
        // switch relies on MAC learning instead.
        macForwardingTableConfigurator: <default("")>
            like INetworkConfigurator if typename != "" {
            @display("p=100,280;is=s");
        }

    connections:
        // switch.eth[0]: point-to-point 1 Gb/s
        gbDevice.ethg++ <--> EthernetLink {
            datarate = 1Gbps;
        } <--> switch.ethg++;

        // switch.eth[1]: 10BASE-T1S multidrop segment
        switch.ethg++ <--> EthernetMultidropLink {
            length = 100cm;
        } <--> junction.port++;
        for i=0..1 {
            junction.port++ <--> EthernetMultidropLink {
                length = 50cm;
            } <--> t1sDevice[i].ethg++;
        }
}
