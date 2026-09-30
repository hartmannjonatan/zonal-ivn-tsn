package zonal_ivn_tsn.common;

simple TrafficPlan
{
    parameters:
        @class(TrafficPlan);
        xml catalog;
        int loadLevel = default(1);
        string aggregation = default("A0");
        double warmup @unit(s) = default(1s);
        double measurement @unit(s) = default(30s);
        // Diagnostic-only: production configurations keep both false.
        bool transientsOnly = default(false);
        bool exhaustiveSignatures = default(false);
        string outputDirectory;
        bool traceReleases = default(false);
        @display("i=block/table;t=F01-F22 / L / A");
}
