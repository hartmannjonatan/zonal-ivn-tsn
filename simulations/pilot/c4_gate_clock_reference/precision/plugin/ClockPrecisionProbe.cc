#include <omnetpp.h>
#include <fstream>
#include <iomanip>
#include <limits>
#include <string>
#include <vector>
#include "inet/clock/contract/IClock.h"
#include "inet/clock/model/SettableClock.h"

using namespace omnetpp;
using namespace inet;

class ClockPrecisionProbe : public cSimpleModule, public cListener
{
    struct ClockRef { std::string name; IClock *corrected; IClock *freeClock; };
    std::vector<ClockRef> clocks;
    std::ofstream out;
    cMessage *timer = nullptr;
    uint64_t sequence = 0;
    simtime_t interval;
    simtime_t stopAt;

    static void writeRaw(std::ostream& stream, simtime_raw_t raw)
    {
        stream << static_cast<int64_t>(raw);
    }

    void writeRow(const char *kind, const std::string& emitter, const char *signalName,
                  bool signalIsTime, simtime_t signalTime, double signalDouble)
    {
        // Snapshot native fixed-point values and subtract before any textual conversion.
        const simtime_t now = simTime();
        const auto hpc = clocks.front().corrected->getClockTime();
        std::vector<clocktime_t> corrected;
        std::vector<clocktime_t> free;
        std::vector<clocktime_t> offsets;
        corrected.reserve(clocks.size());
        free.reserve(clocks.size());
        offsets.reserve(clocks.size());
        for (const auto& c : clocks) {
            const clocktime_t value = c.corrected->getClockTime();
            corrected.push_back(value);
            free.push_back(c.freeClock->getClockTime());
            offsets.push_back(value - hpc);
        }

        out << sequence++ << ',' << getSimulation()->getEventNumber() << ',';
        writeRaw(out, now.raw());
        out << ',' << SimTime::getScaleExp() << ',' << now.str() << ',' << kind << ',' << emitter << ',' << signalName << ',';
        if (signalIsTime)
            writeRaw(out, signalTime.raw());
        out << ',';
        if (!signalIsTime)
            out << std::setprecision(std::numeric_limits<double>::max_digits10) << signalDouble;
        out << ',' << (signalIsTime ? "simtime_raw" : "double") << ',';
        for (size_t i = 0; i < clocks.size(); ++i) {
            writeRaw(out, corrected[i].raw()); out << ',';
            writeRaw(out, free[i].raw()); out << ',';
            writeRaw(out, offsets[i].raw()); out << ',';
        }
        out << '\n';
        out.flush();
    }

  protected:
    void initialize() override
    {
        interval = SimTime(par("sampleInterval"));
        stopAt = SimTime(par("stopAt"));
        out.open(par("outputFile").stringValue(), std::ios::out | std::ios::trunc);
        if (!out) throw cRuntimeError("Cannot open clock precision audit output file");
        out << "sequence,event_number,simtime_raw,simtime_scale_exp,simtime_exact_s,record_kind,emitter,signal,signal_value_raw,signal_value_double,signal_value_type";
        const char *names[] = {"HPC", "CSW", "Z1.ZSW", "Z2.ZSW", "Z3.ZSW"};
        auto root = getSimulation()->getSystemModule();
        for (auto name : names) {
            std::string path = std::string(name) + ".clock";
            auto module = root->getModuleByPath(path.c_str());
            auto corrected = dynamic_cast<IClock *>(module);
            auto settable = dynamic_cast<SettableClock *>(module);
            if (!corrected || !settable) throw cRuntimeError("Clock precision target is missing/not SettableClock: %s", path.c_str());
            clocks.push_back({name, corrected, settable->getUnderlyingClock()});
            out << ',' << name << "_clock_raw," << name << "_free_raw," << name << "_offset_from_HPC_raw";
            module->subscribe(registerSignal("timeChanged"), this);
            module->subscribe(registerSignal("oscillatorCompensationChanged"), this);
        }
        out << '\n';
        timer = new cMessage("clockAuditPeriodicSample");
        scheduleAt(simTime() + interval, timer);
    }

    void handleMessage(cMessage *msg) override
    {
        if (msg != timer) throw cRuntimeError("Unexpected message in ClockPrecisionProbe");
        writeRow("periodic", "-", "-", false, SIMTIME_ZERO, 0.0);
        if (simTime() + interval <= stopAt) scheduleAt(simTime() + interval, timer);
    }

    void receiveSignal(cComponent *source, simsignal_t signal, const SimTime& value, cObject *) override
    {
        writeRow("signal", source->getFullPath(), getSignalName(signal), true, value, 0.0);
    }

    void receiveSignal(cComponent *source, simsignal_t signal, double value, cObject *) override
    {
        writeRow("signal", source->getFullPath(), getSignalName(signal), false, SIMTIME_ZERO, value);
    }

    void finish() override { if (out.is_open()) out.close(); }
    ~ClockPrecisionProbe() override { cancelAndDelete(timer); }
};

Define_Module(ClockPrecisionProbe);
