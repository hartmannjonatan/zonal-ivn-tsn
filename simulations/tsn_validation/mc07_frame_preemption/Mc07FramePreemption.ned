import inet.networks.base.WiredNetworkBase;
import inet.node.ethernet.Eth100M;
import inet.node.ethernet.Eth1G;
import inet.node.tsn.TsnDevice;
import inet.node.tsn.TsnSwitch;

package zonal_ivn_tsn.simulations.tsn_validation.mc07_frame_preemption;

network Mc07FramePreemption extends WiredNetworkBase
{
    parameters:
        @display("bgb=780,360");

    submodules:
        sourcePreemptable: TsnDevice {
            @display("p=120,100");
        }

        sourceExpress: TsnDevice {
            @display("p=120,250");
        }

        switch: TsnSwitch {
            @display("p=390,175");
        }

        receiver: TsnDevice {
            @display("p=660,175");
        }

    connections:
        sourcePreemptable.ethg++ <--> Eth1G <--> switch.ethg++;
        sourceExpress.ethg++ <--> Eth1G <--> switch.ethg++;
        switch.ethg++ <--> Eth100M <--> receiver.ethg++;
}