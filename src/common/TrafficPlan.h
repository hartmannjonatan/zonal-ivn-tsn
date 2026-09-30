#ifndef ZONAL_TRAFFIC_PLAN_H
#define ZONAL_TRAFFIC_PLAN_H
#include <omnetpp.h>
#include <array>
#include <fstream>
#include <string>
#include <vector>

struct CatalogFlow {
    int id, appBytes, burst, pcp, vlan;
    bool scalable;
    std::string name, family, source, destinations, criticality;
    double period, offset, phase, deadline;
};
struct TrafficEvent {
    int block, signature;
    double start, duration;
    long volume;
    std::string name;
};
class TrafficPlan : public omnetpp::cSimpleModule {
  public:
    std::array<CatalogFlow,23> flows;
    std::array<std::vector<TrafficEvent>,2> events;
    double factor, warmup, measurement, end;
    bool aligned, trace, transientsOnly, exhaustive;
    std::string directory;
    std::ofstream releases;
    const CatalogFlow& flow(int id) const { return flows.at(id); }
    double period(const CatalogFlow& f) const { return f.period / (f.scalable ? factor : 1); }
    double offset(const CatalogFlow& f) const;
  protected:
    void initialize() override;
    void handleMessage(omnetpp::cMessage *) override;
};
#endif
