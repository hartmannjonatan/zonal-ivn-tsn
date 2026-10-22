#include <fstream>
#include <iomanip>
#include <cstdio>
#include <sstream>
#include <string>
#include <vector>

#include "inet/clock/contract/IClock.h"
#include "inet/common/Simsignals.h"
#include "inet/physicallayer/common/Signal.h"
#include "inet/queueing/gate/PeriodicGate.h"
#include "inet/queueing/gate/CreditBasedGate.h"
#include "inet/common/packet/Packet.h"

using namespace omnetpp;
using namespace inet;

namespace zonal_ivn_tsn::pilot {

class RealClockTraceProbe final : public cSimpleModule, public cListener {
  private:
    std::ofstream out;
    IClock *hpcClock = nullptr;
    cModule *systemRoot = nullptr;
    uint64_t order = 0;
    std::vector<cComponent *> subscribed;
    simsignal_t pushStarted = cComponent::registerSignal("packetPushStarted");
    simsignal_t pulled = cComponent::registerSignal("packetPulled");
    simsignal_t removed = cComponent::registerSignal("packetRemoved");
    simsignal_t dropped = cComponent::registerSignal("packetDropped");
    simsignal_t sentLower = cComponent::registerSignal("packetSentToLower");
    simsignal_t txStarted = cComponent::registerSignal("transmissionStarted");
    simsignal_t txEnded = cComponent::registerSignal("transmissionEnded");
    simsignal_t gateChanged = cComponent::registerSignal("gateStateChanged");
    simsignal_t guardChanged = cComponent::registerSignal("guardBandStateChanged");
    simsignal_t creditsChanged = cComponent::registerSignal("creditsChanged");
    simsignal_t queueLengthChanged = cComponent::registerSignal("queueLength");
    simsignal_t queueBitsChanged = cComponent::registerSignal("queueBitLength");
    simsignal_t timeChanged = cComponent::registerSignal("timeChanged");

    static bool selectedPacket(const Packet *packet, int& flow, unsigned long& seq) {
        if (packet == nullptr || std::sscanf(packet->getName(), "F%d-%lu", &flow, &seq) != 2)
            return false;
        return flow == 8 || flow == 9 || flow == 10 || flow == 13 || flow == 21 || flow == 22;
    }

    static std::string quote(const std::string& value) {
        std::string result = "\"";
        for (char c : value) {
            if (c == '"') result += '"';
            result += c;
        }
        return result + '"';
    }

    void row(const char *kind, cComponent *source, const std::string& packetId,
             int flow, unsigned long seq, long bytes, const std::string& value = "") {
        const auto now = simTime();
        out << getSimulation()->getEventNumber() << ',' << ++order << ',' << now.raw() << ','
            << quote(source->getFullPath()) << ',' << kind << ',' << packetId << ','
            << flow << ',' << seq << ',' << bytes << ',' << value << '\n';
    }

    void packetRow(cComponent *source, simsignal_t signal, cObject *object) {
        auto packet = dynamic_cast<Packet *>(object);
        int flow = 0;
        unsigned long seq = 0;
        if (!selectedPacket(packet, flow, seq)) return;
        const char *kind = signal == pushStarted ? "queue_push_start" :
                           signal == pulled ? "queue_pulled_out" :
                           signal == removed ? "queue_removed" :
                           signal == dropped ? "packet_dropped" : "packet_sent_lower";
        row(kind, source, packet->getName(), flow, seq, packet->getDataLength().get());
    }

    void subscribeTree(cModule *module) {
        const std::string path = module->getFullPath();
        auto subscribe = [&](simsignal_t signal) {
            module->subscribe(signal, this);
            subscribed.push_back(module);
        };
        if (path.find(".queue.queue[") != std::string::npos) {
            subscribe(pushStarted);
            subscribe(pulled);
            subscribe(removed);
            subscribe(dropped);
            subscribe(queueLengthChanged);
            subscribe(queueBitsChanged);
        }
        if (path.find(".transmitter") != std::string::npos) {
            subscribe(sentLower);
            subscribe(txStarted);
            subscribe(txEnded);
        }
        if (path.find(".transmissionGate[") != std::string::npos) {
            subscribe(gateChanged);
            subscribe(guardChanged);
        }
        if (path.find(".transmissionSelectionAlgorithm[") != std::string::npos ||
            path.find(".transmissionGate[") != std::string::npos)
            subscribe(creditsChanged);
        if (std::string(module->getName()) == "clock")
            subscribe(timeChanged);
        for (cModule::SubmoduleIterator it(module); !it.end(); ++it)
            subscribeTree(*it);
    }

    int numInitStages() const override { return NUM_INIT_STAGES; }

    void initialize(int stage) override {
        if (stage != INITSTAGE_LAST) return;
        out.open(par("outputFile").stringValue(), std::ios::out | std::ios::trunc);
        if (!out) throw cRuntimeError("Cannot open real-clock trace output %s", par("outputFile").stringValue());
        out << "event,order,simtime_raw,source,kind,packet_id,flow,seq,data_bits,value\n";
        auto root = getParentModule();
        systemRoot = root;
        auto hpc = root->getSubmodule("HPC")->getSubmodule("clock");
        hpcClock = check_and_cast<IClock *>(hpc);
        subscribeTree(root);
    }

    IClock *clockFor(const cComponent *source) const {
        std::string path = source->getFullPath();
        const char *node = nullptr;
        if (path.rfind("ZonalIVN.HPC.", 0) == 0) node = "HPC";
        else if (path.rfind("ZonalIVN.CSW.", 0) == 0) node = "CSW";
        else if (path.rfind("ZonalIVN.Z1.ZSW.", 0) == 0) node = "Z1.ZSW";
        else if (path.rfind("ZonalIVN.Z2.ZSW.", 0) == 0) node = "Z2.ZSW";
        else if (path.rfind("ZonalIVN.Z3.ZSW.", 0) == 0) node = "Z3.ZSW";
        if (node == nullptr || systemRoot == nullptr) return nullptr;
        std::string clockPath = std::string(node) + ".clock";
        auto module = systemRoot->getModuleByPath(clockPath.c_str());
        return module ? dynamic_cast<IClock *>(module) : nullptr;
    }

    void finish() override {
        out.flush();
        out.close();
    }

    void handleMessage(cMessage *message) override {
        throw cRuntimeError("RealClockTraceProbe is passive; unexpected message %s", message->getName());
    }

    void receiveSignal(cComponent *source, simsignal_t signal, cObject *object, cObject *) override {
        if (signal == pushStarted || signal == pulled || signal == removed || signal == dropped || signal == sentLower) {
            packetRow(source, signal, object);
            return;
        }
        if (signal == txStarted || signal == txEnded) {
            auto encoded = dynamic_cast<physicallayer::Signal *>(object);
            auto packet = encoded ? dynamic_cast<Packet *>(encoded->getEncapsulatedPacket()) : nullptr;
            int flow = 0;
            unsigned long seq = 0;
            if (selectedPacket(packet, flow, seq))
                row(signal == txStarted ? "phy_tx_start" : "phy_tx_end", source,
                    packet->getName(), flow, seq, packet->getDataLength().get());
            return;
        }
    }

    void receiveSignal(cComponent *source, simsignal_t signal, bool value, cObject *) override {
        if (signal == gateChanged || signal == guardChanged) {
            std::ostringstream formatted;
            formatted << "state=" << (value ? 1 : 0);
            if (signal == gateChanged) {
                auto local = clockFor(source);
                if (local != nullptr && hpcClock != nullptr)
                    formatted << ";local_clock_raw=" << local->getClockTime().raw()
                              << ";hpc_clock_raw=" << hpcClock->getClockTime().raw();
            }
            row(signal == gateChanged ? "gate_state" : "guard_band_state", source, "", 0, 0, 0, formatted.str());
        }
    }

    void receiveSignal(cComponent *source, simsignal_t signal, double value, cObject *) override {
        if (signal == creditsChanged) {
            std::ostringstream formatted;
            formatted << std::setprecision(17) << value;
            row("cbs_credit", source, "", 0, 0, 0, formatted.str());
        }
    }

    void receiveSignal(cComponent *source, simsignal_t signal, intval_t value, cObject *) override {
        if (signal == queueLengthChanged || signal == queueBitsChanged)
            row(signal == queueLengthChanged ? "queue_length_state" : "queue_bits_state",
                source, "", 0, 0, 0, std::to_string(value));
    }

    void receiveSignal(cComponent *source, simsignal_t signal, const SimTime& value, cObject *) override {
        if (signal != timeChanged) return;
        auto clock = dynamic_cast<IClock *>(source);
        if (clock == nullptr || hpcClock == nullptr) return;
        auto local = clock->getClockTime();
        auto gm = hpcClock->getClockTime();
        const auto path = source->getFullPath();
        row("clock_time_changed", source, "", 0, 0, 0,
            std::to_string(value.raw()) + ";local_raw=" + std::to_string(local.raw()) +
            ";hpc_raw=" + std::to_string(gm.raw()) +
            ";offset_raw=" + std::to_string(local.raw() - gm.raw()) +
            ";path=" + path);
    }
};

Define_Module(RealClockTraceProbe);

} // namespace zonal_ivn_tsn::pilot
