package zonal_ivn_tsn.simulations.pilot.c4_fixed_L2_profile;

simple RealClockTraceProbe
{
    parameters:
        string outputFile;
        @class(zonal_ivn_tsn::pilot::RealClockTraceProbe);
}

network ZonalIVN extends zonal_ivn_tsn.simulations.zonal.networks.ZonalIVN
{
    submodules:
        realClockTrace: RealClockTraceProbe {
            @display("p=90,710;i=block/table;t=pilot trace");
        }
        clockPrecision: ClockPrecisionProbe {
            @display("p=90,750;i=block/table;t=native clock audit");
        }
}
