package zonal_ivn_tsn.simulations.zonal.networks;

import inet.node.ethernet.EthernetMultidropLink;
import inet.node.tsn.TsnDevice;

// Extension (not part of the P1 catalog): ZonalIVNT1S with `extraNodes`
// additional TsnDevices on every zone's 10BASE-T1S segment. They take the next
// free PLCA node IDs (Z1: 2.., Z2/Z3: 3..), so a segment holds
// 2 + extraNodes (Z1) or 3 + extraNodes (Z2/Z3) nodes. Their traffic (sensor
// or heavy background frames towards HPC) is set in configs/t1s.ini.
network ZonalIVNT1SExtra extends ZonalIVNT1S
{
    parameters:
        int extraNodes = default(0);
        plcaNodeCountZ1 = default(2 + extraNodes);
        plcaNodeCountZ2 = default(3 + extraNodes);
        plcaNodeCountZ3 = default(3 + extraNodes);
    submodules:
        X1[extraNodes]: TsnDevice {
            numEthInterfaces = 1;
            eth[0].typename = "EthernetPlcaInterface";
            eth[0].plca.plca_node_count = parent.plcaNodeCountZ1;
            eth[0].plca.local_nodeID = 2 + index;
            @display("p=620,140,row,40;i=block/source;is=vs;t=T1S node");
        }
        X2[extraNodes]: TsnDevice {
            numEthInterfaces = 1;
            eth[0].typename = "EthernetPlcaInterface";
            eth[0].plca.plca_node_count = parent.plcaNodeCountZ2;
            eth[0].plca.local_nodeID = 3 + index;
            @display("p=980,560,row,40;i=block/source;is=vs;t=T1S node");
        }
        X3[extraNodes]: TsnDevice {
            numEthInterfaces = 1;
            eth[0].typename = "EthernetPlcaInterface";
            eth[0].plca.plca_node_count = parent.plcaNodeCountZ3;
            eth[0].plca.local_nodeID = 3 + index;
            @display("p=250,560,row,40;i=block/source;is=vs;t=T1S node");
        }
    connections:
        for i=0..extraNodes-1 {
            T1S1.port++ <--> EthernetMultidropLink {
                length = 50cm;
                @display("ls=#a855f7,1");
            } <--> X1[i].ethg[0];
            T1S2.port++ <--> EthernetMultidropLink {
                length = 50cm;
                @display("ls=#a855f7,1");
            } <--> X2[i].ethg[0];
            T1S3.port++ <--> EthernetMultidropLink {
                length = 50cm;
                @display("ls=#a855f7,1");
            } <--> X3[i].ethg[0];
        }
}
