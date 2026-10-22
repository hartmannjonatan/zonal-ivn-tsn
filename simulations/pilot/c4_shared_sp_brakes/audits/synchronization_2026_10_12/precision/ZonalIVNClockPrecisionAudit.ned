package zonal_ivn_tsn.simulations.pilot.c4_shared_sp_brakes.audits.synchronization_2026_10_12.precision;

import zonal_ivn_tsn.simulations.zonal.networks.ZonalIVN;
import zonal_ivn_tsn.simulations.pilot.c4_shared_sp_brakes.audits.synchronization_2026_10_12.precision.ClockPrecisionProbe;

network ZonalIVNClockPrecisionAudit extends ZonalIVN
{
    submodules:
        clockAudit: ClockPrecisionProbe {
            parameters:
                outputFile = default("clock-precision.csv");
                @display("p=50,50;i=block/timer");
        }
}
