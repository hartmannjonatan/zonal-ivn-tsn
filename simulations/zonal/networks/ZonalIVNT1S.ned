package zonal_ivn_tsn.simulations.zonal.networks;

import inet.node.tsn.TsnDevice;
import inet.node.tsn.TsnSwitch;
import inet.networklayer.configurator.ipv4.Ipv4NetworkConfigurator;
import inet.linklayer.configurator.common.MacForwardingTableConfigurator;
import zonal_ivn_tsn.nodes.ZonalController;
import zonal_ivn_tsn.common.ZonalEthernetLink;
import zonal_ivn_tsn.common.TrafficPlan;
import zonal_ivn_tsn.common.TrafficAudit;
import inet.node.ethernet.EthernetMultidropLink;
import inet.physicallayer.wired.common.WireJunction;

// ZonalIVN variant: in every zone the dedicated 100 Mb/s WINDOW and RADAR
// access links are replaced by one 10BASE-T1S PLCA multidrop segment.
// The zonal switch port is the PLCA coordinator (node ID 0); RADAR = 1,
// WINDOW = 2 (Z1 has no radar, so WINDOW1 = 1); plca_node_count equals the
// number of nodes on the segment. Port map changes versus ZonalIVN:
//   Z1: eth5 = T1S {WINDOW1}                      (indices unchanged, 7 access ports)
//   Z2: eth2 = T1S {RADAR1, WINDOW2}, CAM2 eth3, BRAKE2 eth4, AUDIO2 eth5,
//       DISPLAY2 eth6, BE2 eth7                    (6 access ports)
//   Z3: eth2 = T1S {RADAR2, WINDOW3}, CAM3 eth3, CAM4 eth4, BRAKE3 eth5,
//       AUDIO3 eth6, BE3 eth7                      (6 access ports)
// MacForwardingTableConfigurator cannot handle WireJunction; the traffic
// configurations use static forwarding tables (configs/t1s.ini).
network ZonalIVNT1S
{
    parameters:
        bool hasTraffic = default(false);
        // Same 1280x720 top view as INET's InVehicleNetworkShowcase.
        // Vehicle front is RIGHT; vehicle left is UP (driver's perspective).
        // Positions are illustrative mounting locations, not cable-length inputs.
        @display("bgi=background/car;bgb=1280,720");
        @figure[title](type=text; pos=35,25; text="ZONAL IVN | 10BASE-T1S"; font=Arial,20,bold; color=#0f172a);
        @figure[orientation](type=text; pos=35,60; text="TOP VIEW  |  REAR <--- ---> FRONT  |  Vehicle left: top"; font=Arial,12; color=#475569);
        @figure[Z1label](type=text; pos=810,140; text="Z1 | FRONT LEFT"; font=Arial,14,bold; color=#2563eb);
        @figure[Z2label](type=text; pos=810,575; text="Z2 | FRONT RIGHT"; font=Arial,14,bold; color=#15803d);
        @figure[Z3label](type=text; pos=285,140; text="Z3 | REAR"; font=Arial,14,bold; color=#c2410c);
        @figure[pcpTitle](type=text; pos=240,620; text="PACKET PCP"; font=Arial,11,bold; color=#0f172a);
        @figure[pcp0swatch](type=oval; pos=340,622; size=12,12; fillColor=#E69F00; lineColor=#E69F00);
        @figure[pcp0label](type=text; pos=357,620; text="PCP 0"; font=Arial,10; color=#0f172a);
        @figure[pcp1swatch](type=oval; pos=415,622; size=12,12; fillColor=#56B4E9; lineColor=#56B4E9);
        @figure[pcp1label](type=text; pos=432,620; text="PCP 1"; font=Arial,10; color=#0f172a);
        @figure[pcp2swatch](type=oval; pos=490,622; size=12,12; fillColor=#009E73; lineColor=#009E73);
        @figure[pcp2label](type=text; pos=507,620; text="PCP 2"; font=Arial,10; color=#0f172a);
        @figure[pcp3swatch](type=oval; pos=565,622; size=12,12; fillColor=#F0E442; lineColor=#F0E442);
        @figure[pcp3label](type=text; pos=582,620; text="PCP 3"; font=Arial,10; color=#0f172a);
        @figure[pcp4swatch](type=oval; pos=640,622; size=12,12; fillColor=#0072B2; lineColor=#0072B2);
        @figure[pcp4label](type=text; pos=657,620; text="PCP 4"; font=Arial,10; color=#0f172a);
        @figure[pcp5swatch](type=oval; pos=715,622; size=12,12; fillColor=#D55E00; lineColor=#D55E00);
        @figure[pcp5label](type=text; pos=732,620; text="PCP 5"; font=Arial,10; color=#0f172a);
        @figure[pcp6swatch](type=oval; pos=790,622; size=12,12; fillColor=#CC79A7; lineColor=#CC79A7);
        @figure[pcp6label](type=text; pos=807,620; text="PCP 6"; font=Arial,10; color=#0f172a);
        @figure[pcp7swatch](type=oval; pos=865,622; size=12,12; fillColor=#000000; lineColor=#000000);
        @figure[pcp7label](type=text; pos=882,620; text="PCP 7"; font=Arial,10; color=#0f172a);
        @figure[pcpOtherSwatch](type=oval; pos=940,622; size=12,12; fillColor=#666666; lineColor=#666666);
        @figure[pcpOtherLabel](type=text; pos=957,620; text="Outro (sem PCP)"; font=Arial,10; color=#0f172a);
        @figure[legend](type=text; pos=245,650; text="Blue: LC/LB 1 Gbit/s  |  Teal: LA-H 1 Gbit/s  |  Gray: LA-L 100 Mbit/s  |  Purple: 10BASE-T1S 10 Mbit/s"; font=Arial,12; color=#334155);
        @figure[hint](type=text; pos=245,680; text="Open Z1 / Z2 / Z3: switch + CPU + LP (1 Gbit/s). All physical links: 100 ns."; font=Arial,11; color=#475569);
    submodules:
        trafficPlan: TrafficPlan if hasTraffic {
            @display("p=90,580");
        }
        trafficAudit: TrafficAudit if hasTraffic {
            @display("p=90,650");
        }
        configurator: Ipv4NetworkConfigurator {
            @display("p=85,120;is=s;t=IPv4 setup");
        }
        macForwardingTableConfigurator: MacForwardingTableConfigurator if !hasTraffic {
            @display("p=85,215;is=s;t=Static L2 setup");
        }
        HPC: TsnDevice {
            numEthInterfaces = 1;
            @display("p=620,300;i=device/server;is=s;t=VC_SOC");
        }
        CSW: TsnSwitch {
            numEthInterfaces = 4;
            @display("p=745,350;i=device/switch;is=s;t=Central switch");
        }
        Z1: ZonalController {
            ZSW.eth[5].typename = "EthernetPlcaInterface";
            ZSW.eth[5].plca.plca_node_count = 2;
            ZSW.eth[5].plca.local_nodeID = 0;
            @display("p=875,290;b=74,40,rect,#dbeafe,#2563eb,2;i=device/switch;is=s;t=Front-left controller");
        }
        LiDAR1: TsnDevice {
            numEthInterfaces = 1;
            @display("p=1030,315;i=device/scanner;is=s;t=LIDAR");
        }
        CAM1: TsnDevice {
            numEthInterfaces = 1;
            @display("p=1000,235;i=misc/camera;t=CAMERA");
        }
        BRAKE1: TsnDevice {
            numEthInterfaces = 1;
            @display("p=850,195;i=block/cogwheel;is=s;t=BRAKE");
        }
        WINDOW1: TsnDevice {
            numEthInterfaces = 1;
            eth[0].typename = "EthernetPlcaInterface";
            eth[0].plca.plca_node_count = 2;
            eth[0].plca.local_nodeID = 1;
            @display("p=700,210;i=block/control;is=s;t=WINDOW");
        }
        AUDIO1: TsnDevice {
            numEthInterfaces = 1;
            @display("p=790,265;i=device/receiverdish;is=vs;t=AUDIO");
        }
        DISPLAY1: TsnDevice {
            numEthInterfaces = 1;
            @display("p=685,280;i=device/terminal;is=s;t=DISPLAY");
        }
        BE1: TsnDevice {
            numEthInterfaces = 1;
            @display("p=950,285;i=device/card;is=vs;t=BE");
        }
        Z2: ZonalController {
            numAccessPorts = 6;
            ZSW.eth[2].typename = "EthernetPlcaInterface";
            ZSW.eth[2].plca.plca_node_count = 3;
            ZSW.eth[2].plca.local_nodeID = 0;
            @display("p=875,435;b=74,40,rect,#dcfce7,#15803d,2;i=device/switch;is=s;t=Front-right controller");
        }
        RADAR1: TsnDevice {
            numEthInterfaces = 1;
            eth[0].typename = "EthernetPlcaInterface";
            eth[0].plca.plca_node_count = 3;
            eth[0].plca.local_nodeID = 1;
            @display("p=1060,405;i=device/receiverdish;is=s;t=RADAR");
        }
        CAM2: TsnDevice {
            numEthInterfaces = 1;
            @display("p=1000,485;i=misc/camera;t=CAMERA");
        }
        BRAKE2: TsnDevice {
            numEthInterfaces = 1;
            @display("p=850,525;i=block/cogwheel;is=s;t=BRAKE");
        }
        WINDOW2: TsnDevice {
            numEthInterfaces = 1;
            eth[0].typename = "EthernetPlcaInterface";
            eth[0].plca.plca_node_count = 3;
            eth[0].plca.local_nodeID = 2;
            @display("p=700,510;i=block/control;is=s;t=WINDOW");
        }
        AUDIO2: TsnDevice {
            numEthInterfaces = 1;
            @display("p=790,460;i=device/receiverdish;is=vs;t=AUDIO");
        }
        DISPLAY2: TsnDevice {
            numEthInterfaces = 1;
            @display("p=685,430;i=device/terminal;is=s;t=DISPLAY");
        }
        BE2: TsnDevice {
            numEthInterfaces = 1;
            @display("p=950,445;i=device/card;is=vs;t=BE");
        }
        Z3: ZonalController {
            numAccessPorts = 6;
            ZSW.eth[2].typename = "EthernetPlcaInterface";
            ZSW.eth[2].plca.plca_node_count = 3;
            ZSW.eth[2].plca.local_nodeID = 0;
            @display("p=440,350;b=74,40,rect,#ffedd5,#c2410c,2;i=device/switch;is=s;t=Rear controller");
        }
        RADAR2: TsnDevice {
            numEthInterfaces = 1;
            eth[0].typename = "EthernetPlcaInterface";
            eth[0].plca.plca_node_count = 3;
            eth[0].plca.local_nodeID = 1;
            @display("p=235,350;i=device/receiverdish;is=s;t=RADAR");
        }
        CAM3: TsnDevice {
            numEthInterfaces = 1;
            @display("p=275,250;i=misc/camera;t=CAMERA");
        }
        CAM4: TsnDevice {
            numEthInterfaces = 1;
            @display("p=275,475;i=misc/camera;t=CAMERA");
        }
        BRAKE3: TsnDevice {
            numEthInterfaces = 1;
            @display("p=400,200;i=block/cogwheel;is=s;t=BRAKE");
        }
        WINDOW3: TsnDevice {
            numEthInterfaces = 1;
            eth[0].typename = "EthernetPlcaInterface";
            eth[0].plca.plca_node_count = 3;
            eth[0].plca.local_nodeID = 2;
            @display("p=505,210;i=block/control;is=s;t=WINDOW");
        }
        AUDIO3: TsnDevice {
            numEthInterfaces = 1;
            @display("p=440,485;i=device/receiverdish;is=vs;t=AUDIO");
        }
        T1S1: WireJunction {
            @display("p=760,215;is=vs;t=T1S Z1");
        }
        T1S2: WireJunction {
            @display("p=900,385;is=vs;t=T1S Z2");
        }
        T1S3: WireJunction {
            @display("p=360,300;is=vs;t=T1S Z3");
        }
        BE3: TsnDevice {
            numEthInterfaces = 1;
            @display("p=355,375;i=device/card;is=vs;t=BE");
        }
    connections:
        // Stable backbone port map: CSW eth0=HPC, eth1=Z1, eth2=Z2, eth3=Z3.
        HPC.ethg[0] <--> LC: ZonalEthernetLink {
            @display("ls=#2563eb,3;t=LC");
        } <--> CSW.ethg[0];
        CSW.ethg[1] <--> LB1: ZonalEthernetLink {
            @display("ls=#2563eb,3;t=LB1");
        } <--> Z1.uplink;
        Z1.access[0] <--> LA_H_LiDAR1: ZonalEthernetLink {
            datarate = 1Gbps;
            @display("ls=#0d9488,2;tt=LA-H | 1 Gbit/s | 100 ns");
        } <--> LiDAR1.ethg[0];
        Z1.access[1] <--> LA_H_CAM1: ZonalEthernetLink {
            datarate = 1Gbps;
            @display("ls=#0d9488,2;tt=LA-H | 1 Gbit/s | 100 ns");
        } <--> CAM1.ethg[0];
        Z1.access[2] <--> LA_L_BRAKE1: ZonalEthernetLink {
            datarate = 100Mbps;
            @display("ls=#64748b,1;tt=LA-L | 100 Mbit/s | 100 ns");
        } <--> BRAKE1.ethg[0];
        Z1.access[3] <--> T1S_Z1_SW: EthernetMultidropLink {
            length = 100cm;
            @display("ls=#a855f7,1;tt=10BASE-T1S | 10 Mbit/s | PLCA");
        } <--> T1S1.port++;
        T1S1.port++ <--> T1S_Z1_WINDOW1: EthernetMultidropLink {
            length = 50cm;
            @display("ls=#a855f7,1;tt=10BASE-T1S | 10 Mbit/s | PLCA");
        } <--> WINDOW1.ethg[0];
        Z1.access[4] <--> LA_L_AUDIO1: ZonalEthernetLink {
            datarate = 100Mbps;
            @display("ls=#64748b,1;tt=LA-L | 100 Mbit/s | 100 ns");
        } <--> AUDIO1.ethg[0];
        Z1.access[5] <--> LA_L_DISPLAY1: ZonalEthernetLink {
            datarate = 100Mbps;
            @display("ls=#64748b,1;tt=LA-L | 100 Mbit/s | 100 ns");
        } <--> DISPLAY1.ethg[0];
        Z1.access[6] <--> LA_L_BE1: ZonalEthernetLink {
            datarate = 100Mbps;
            @display("ls=#64748b,1;tt=LA-L | 100 Mbit/s | 100 ns");
        } <--> BE1.ethg[0];
        CSW.ethg[2] <--> LB2: ZonalEthernetLink {
            @display("ls=#2563eb,3;t=LB2");
        } <--> Z2.uplink;
        Z2.access[0] <--> T1S_Z2_SW: EthernetMultidropLink {
            length = 100cm;
            @display("ls=#a855f7,1;tt=10BASE-T1S | 10 Mbit/s | PLCA");
        } <--> T1S2.port++;
        T1S2.port++ <--> T1S_Z2_RADAR1: EthernetMultidropLink {
            length = 50cm;
            @display("ls=#a855f7,1;tt=10BASE-T1S | 10 Mbit/s | PLCA");
        } <--> RADAR1.ethg[0];
        T1S2.port++ <--> T1S_Z2_WINDOW2: EthernetMultidropLink {
            length = 50cm;
            @display("ls=#a855f7,1;tt=10BASE-T1S | 10 Mbit/s | PLCA");
        } <--> WINDOW2.ethg[0];
        Z2.access[1] <--> LA_H_CAM2: ZonalEthernetLink {
            datarate = 1Gbps;
            @display("ls=#0d9488,2;tt=LA-H | 1 Gbit/s | 100 ns");
        } <--> CAM2.ethg[0];
        Z2.access[2] <--> LA_L_BRAKE2: ZonalEthernetLink {
            datarate = 100Mbps;
            @display("ls=#64748b,1;tt=LA-L | 100 Mbit/s | 100 ns");
        } <--> BRAKE2.ethg[0];
        Z2.access[3] <--> LA_L_AUDIO2: ZonalEthernetLink {
            datarate = 100Mbps;
            @display("ls=#64748b,1;tt=LA-L | 100 Mbit/s | 100 ns");
        } <--> AUDIO2.ethg[0];
        Z2.access[4] <--> LA_L_DISPLAY2: ZonalEthernetLink {
            datarate = 100Mbps;
            @display("ls=#64748b,1;tt=LA-L | 100 Mbit/s | 100 ns");
        } <--> DISPLAY2.ethg[0];
        Z2.access[5] <--> LA_L_BE2: ZonalEthernetLink {
            datarate = 100Mbps;
            @display("ls=#64748b,1;tt=LA-L | 100 Mbit/s | 100 ns");
        } <--> BE2.ethg[0];
        CSW.ethg[3] <--> LB3: ZonalEthernetLink {
            @display("ls=#2563eb,3;t=LB3");
        } <--> Z3.uplink;
        Z3.access[0] <--> T1S_Z3_SW: EthernetMultidropLink {
            length = 100cm;
            @display("ls=#a855f7,1;tt=10BASE-T1S | 10 Mbit/s | PLCA");
        } <--> T1S3.port++;
        T1S3.port++ <--> T1S_Z3_RADAR2: EthernetMultidropLink {
            length = 50cm;
            @display("ls=#a855f7,1;tt=10BASE-T1S | 10 Mbit/s | PLCA");
        } <--> RADAR2.ethg[0];
        T1S3.port++ <--> T1S_Z3_WINDOW3: EthernetMultidropLink {
            length = 50cm;
            @display("ls=#a855f7,1;tt=10BASE-T1S | 10 Mbit/s | PLCA");
        } <--> WINDOW3.ethg[0];
        Z3.access[1] <--> LA_H_CAM3: ZonalEthernetLink {
            datarate = 1Gbps;
            @display("ls=#0d9488,2;tt=LA-H | 1 Gbit/s | 100 ns");
        } <--> CAM3.ethg[0];
        Z3.access[2] <--> LA_H_CAM4: ZonalEthernetLink {
            datarate = 1Gbps;
            @display("ls=#0d9488,2;tt=LA-H | 1 Gbit/s | 100 ns");
        } <--> CAM4.ethg[0];
        Z3.access[3] <--> LA_L_BRAKE3: ZonalEthernetLink {
            datarate = 100Mbps;
            @display("ls=#64748b,1;tt=LA-L | 100 Mbit/s | 100 ns");
        } <--> BRAKE3.ethg[0];
        Z3.access[4] <--> LA_L_AUDIO3: ZonalEthernetLink {
            datarate = 100Mbps;
            @display("ls=#64748b,1;tt=LA-L | 100 Mbit/s | 100 ns");
        } <--> AUDIO3.ethg[0];
        Z3.access[5] <--> LA_L_BE3: ZonalEthernetLink {
            datarate = 100Mbps;
            @display("ls=#64748b,1;tt=LA-L | 100 Mbit/s | 100 ns");
        } <--> BE3.ethg[0];
}
