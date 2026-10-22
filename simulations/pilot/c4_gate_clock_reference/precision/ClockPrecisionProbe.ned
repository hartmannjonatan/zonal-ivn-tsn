package zonal_ivn_tsn.simulations.pilot.c4_gate_clock_reference.precision;

simple ClockPrecisionProbe
{
    parameters:
        double sampleInterval @unit(s) = default(1ms);
        double stopAt @unit(s) = default(3.05s);
        string outputFile;
        @class(ClockPrecisionProbe);
}
