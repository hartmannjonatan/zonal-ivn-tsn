#include <omnetpp.h>
#include <fstream>
#include <iomanip>
#include <string>
#include <vector>
#include "inet/clock/contract/IClock.h"
#include "inet/clock/model/SettableClock.h"

using namespace omnetpp;
using namespace inet;

class ClockAuditProbe : public cSimpleModule, public cListener
{
    struct ClockRef { std::string name; IClock *corrected; IClock *freeClock; };
    std::vector<ClockRef> clocks;
    std::ofstream out;
    cMessage *timer = nullptr;
    uint64_t sequence = 0;
    double interval = 0.001;
    double stopAt = 3.05;

    void writeRow(const char *kind, const std::string& emitter, double signalValue, const char *signalName)
    {
        out << sequence++ << ',' << simTime().dbl() << ',' << kind << ',' << emitter << ',' << signalName << ',' << signalValue;
        for (const auto& c : clocks) out << ',' << c.corrected->getClockTime().dbl();
        for (const auto& c : clocks) out << ',' << c.freeClock->getClockTime().dbl();
        out << '\n';
        out.flush();
    }
  protected:
    void initialize() override
    {
        interval = par("sampleInterval").doubleValue();
        stopAt = par("stopAt").doubleValue();
        out.open(par("outputFile").stringValue(), std::ios::out | std::ios::trunc);
        if (!out) throw cRuntimeError("Cannot open clock audit output file");
        out << "order,simtime_s,record_kind,emitter,signal,signal_value_s,hpc_clock_s,csw_clock_s,z1_clock_s,z2_clock_s,z3_clock_s,hpc_free_s,csw_free_s,z1_free_s,z2_free_s,z3_free_s\n";
        auto root = getSimulation()->getSystemModule();
        const char *names[] = {"HPC", "CSW", "Z1.ZSW", "Z2.ZSW", "Z3.ZSW"};
        for (auto name : names) {
            std::string path = std::string(name) + ".clock";
            auto module = root->getModuleByPath(path.c_str());
            auto corrected = dynamic_cast<IClock *>(module);
            if (!corrected) throw cRuntimeError("Clock audit target is missing/not IClock: %s", path.c_str());
            auto settable = dynamic_cast<SettableClock *>(module);
            if (!settable) throw cRuntimeError("Clock audit target is not SettableClock: %s", path.c_str());
            clocks.push_back({name, corrected, settable->getUnderlyingClock()});
            module->subscribe(registerSignal("timeChanged"), this);
            module->subscribe(registerSignal("oscillatorCompensationChanged"), this);
        }
        timer = new cMessage("clockAuditPeriodicSample");
        scheduleAt(simTime() + interval, timer);
    }
    void handleMessage(cMessage *msg) override
    {
        if (msg != timer) throw cRuntimeError("Unexpected message in ClockAuditProbe");
        writeRow("periodic", "-", 0.0, "-");
        if (simTime().dbl() + interval <= stopAt) scheduleAt(simTime() + interval, timer);
    }
    void receiveSignal(cComponent *source, simsignal_t signal, const SimTime& value, cObject *) override
    {
        writeRow("signal", source->getFullPath(), value.dbl(), getSignalName(signal));
    }
    void receiveSignal(cComponent *source, simsignal_t signal, double value, cObject *) override
    {
        writeRow("signal", source->getFullPath(), value, getSignalName(signal));
    }
    void finish() override { if (out.is_open()) out.close(); }
    ~ClockAuditProbe() override { cancelAndDelete(timer); }
};

Define_Module(ClockAuditProbe);
