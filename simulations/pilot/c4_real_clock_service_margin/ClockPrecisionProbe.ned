package zonal_ivn_tsn.simulations.pilot.c4_real_clock_service_margin;

simple ClockPrecisionProbe
{
    parameters:
        double sampleInterval @unit(s) = default(1ms);
        double stopAt @unit(s) = default(31.05s);
        string outputFile;
        @class(ClockPrecisionProbe);
}
