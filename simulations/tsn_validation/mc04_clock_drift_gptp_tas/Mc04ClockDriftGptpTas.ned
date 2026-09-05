import inet.networks.base.TsnNetworkBase;
import inet.node.ethernet.Eth100M;
import inet.node.tsn.TsnDevice;
import inet.node.tsn.TsnSwitch;

package zonal_ivn_tsn.simulations.tsn_validation.mc04_clock_drift_gptp_tas;

network Mc04ClockDriftGptpTas extends TsnNetworkBase
{
    parameters:
        @display("bgb=900,360");

    submodules:
        source: TsnDevice {
            @display("p=110,180");
        }

        switch1: TsnSwitch {
            @display("p=340,180");
        }

        switch2: TsnSwitch {
            @display("p=570,180");
        }

        receiver: TsnDevice {
            @display("p=800,180");
        }

    connections:
        source.ethg++ <--> Eth100M { length = 10m; } <--> switch1.ethg++;
        switch1.ethg++ <--> Eth100M { length = 10m; } <--> switch2.ethg++;
        switch2.ethg++ <--> Eth100M { length = 10m; } <--> receiver.ethg++;
}