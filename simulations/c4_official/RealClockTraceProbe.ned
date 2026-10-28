package zonal_ivn_tsn.simulations.c4_official;

simple RealClockTraceProbe
{
    parameters:
        string outputFile;
        int packetTraceStride = default(256);
        double gateTraceUntil @unit(s) = default(1ms);
        bool traceQueueStates = default(false);
        bool traceCreditStates = default(false);
        @class(zonal_ivn_tsn::pilot::RealClockTraceProbe);
}
