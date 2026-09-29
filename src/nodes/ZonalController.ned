package zonal_ivn_tsn.nodes;

import inet.node.tsn.TsnDevice;
import inet.node.tsn.TsnSwitch;
import zonal_ivn_tsn.common.ZonalEthernetLink;

// P1 §2.3: packaging only, NOT a forwarding node itself.
// The boundary wires add no channel: each physical link has exactly one delay.
module ZonalController
{
    parameters:
        int numAccessPorts = default(7);
        @display("bgb=500,280;b=110,56,rect,#e2e8f0,#475569,2;i=device/switch;t=Switch + CPU");
        @figure[title](type=text; pos=25,20; text="Zonal controller | switch + processing endpoint"; font=Arial,14,bold; color=#334155);
        @figure[note](type=text; pos=25,245; text="eth0: backbone | eth1: CPU | eth2..8: access"; color=#475569);
    gates:
        inout uplink;
        inout access[numAccessPorts];
    submodules:
        ZSW: TsnSwitch {
            numEthInterfaces = 2 + parent.numAccessPorts;
            @display("p=160,130;i=device/switch;is=l;t=Zonal switch");
        }
        ZCPU: TsnDevice {
            numEthInterfaces = 1;
            @display("p=370,130;i=device/cpu;is=l;t=Processing endpoint");
        }
    connections:
        uplink <--> ZSW.ethg[0];
        ZSW.ethg[1] <--> LP: ZonalEthernetLink {
            @display("ls=#7c3aed,3;t=LP | 1 Gbit/s");
        } <--> ZCPU.ethg[0];
        for i=0..numAccessPorts-1 {
            access[i] <--> ZSW.ethg[i+2];
        }
}
