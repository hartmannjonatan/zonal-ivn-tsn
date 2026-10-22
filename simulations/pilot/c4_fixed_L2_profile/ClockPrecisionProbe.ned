package zonal_ivn_tsn.simulations.pilot.c4_fixed_L2_profile;

simple ClockPrecisionProbe
{
    parameters:
        double sampleInterval @unit(s) = default(1ms);
        double stopAt @unit(s) = default(31.05s);
        string outputFile;
        @class(ClockPrecisionProbe);
}
