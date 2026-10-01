#ifndef ZONAL_CATALOG_UDP_APP_H
#define ZONAL_CATALOG_UDP_APP_H
#include "../common/TrafficPlan.h"
#include "inet/common/INETDefs.h"
#include "inet/transportlayer/contract/udp/UdpSocket.h"
#include <cstdint>
#include <map>
#include <set>

class CatalogUdpApp : public omnetpp::cSimpleModule, public inet::UdpSocket::ICallback {
    TrafficPlan *plan=nullptr;
    const CatalogFlow *flow=nullptr;
    inet::UdpSocket socket;
    inet::L3Address destination;
    omnetpp::cMessage *timer=nullptr;
    bool source=false;
    long sequence=0, cycle=0, eventPacket=0, cameraPacket=0;
    int eventIndex=0;
    long packets=0, appBytes=0, measuredPackets=0, measuredBytes=0, misses=0;
    long measuredImages=0, completedImages=0, imageDeadlineMisses=0;
    long duplicates=0, lastSequence=-1;
    uint64_t sequenceSum=0;
    omnetpp::simtime_t first=-1, last=-1, minGap=1e6, maxGap=0;
    omnetpp::simtime_t maxLatency=0;
    long minSize=1000000,maxSize=0;
    omnetpp::simsignal_t sentSignal,receivedSignal,latencySignal,imageCompletionLatencySignal;
    struct ImageReception { std::set<long> sequences; omnetpp::simtime_t lastArrival=0; };
    std::map<long, ImageReception> imageReceptions;
    void emitPacket(int size);
    void countPacket(int size, long seq, omnetpp::simtime_t created);
    void countCameraImageCompletion(long seq);
    void scheduleNext();
  protected:
    int numInitStages() const override {return inet::NUM_INIT_STAGES;}
    void initialize(int stage) override;
    void handleMessage(omnetpp::cMessage *msg) override;
    void finish() override;
    void socketDataArrived(inet::UdpSocket *,inet::Packet *) override;
    void socketErrorArrived(inet::UdpSocket *,inet::Indication *) override;
    void socketClosed(inet::UdpSocket *) override {}
  public:
    ~CatalogUdpApp() override {cancelAndDelete(timer);}
};
#endif
