package zonal_ivn_tsn.simulations.pilot.c4_gate_clock_reference.precision;

import zonal_ivn_tsn.simulations.pilot.c4_gate_clock_reference.precision.ClockPrecisionProbe;

network ZonalIVN extends zonal_ivn_tsn.simulations.zonal.networks.ZonalIVN
{
    submodules:
        clockAudit: ClockPrecisionProbe {
            parameters:
                outputFile = default("clock-precision.csv");
                @display("p=50,50;i=block/timer");
        }
}
