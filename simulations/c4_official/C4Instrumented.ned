package zonal_ivn_tsn.simulations.c4_official;

import zonal_ivn_tsn.simulations.zonal.networks.ZonalIVN;

network C4Instrumented extends ZonalIVN
{
    submodules:
        realClockTrace: RealClockTraceProbe {
            @display("p=90,710;i=block/table;t=C4 packet trace");
        }
        clockPrecision: ClockPrecisionProbe {
            @display("p=90,750;i=block/table;t=native clock audit");
        }
}
