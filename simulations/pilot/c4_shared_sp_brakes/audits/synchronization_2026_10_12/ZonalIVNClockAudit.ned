package zonal_ivn_tsn.simulations.pilot.c4_shared_sp_brakes.audits.synchronization_2026_10_12;

import zonal_ivn_tsn.simulations.zonal.networks.ZonalIVN;
import zonal_ivn_tsn.simulations.pilot.c4_shared_sp_brakes.audits.synchronization_2026_10_12.ClockAuditProbe;

network ZonalIVNClockAudit extends ZonalIVN
{
    submodules:
        clockAudit: ClockAuditProbe {
            parameters:
                outputFile = default("clock-audit.csv");
                @display("p=50,50;i=block/timer");
        }
}
