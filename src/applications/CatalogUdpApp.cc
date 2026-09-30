#include "CatalogUdpApp.h"
#include "CatalogColorPacket.h"
#include "inet/applications/base/ApplicationPacket_m.h"
#include "inet/common/TimeTag_m.h"
#include "inet/common/ModuleAccess.h"
#include "inet/common/packet/Packet.h"
#include "inet/networklayer/common/L3AddressResolver.h"
#include "inet/networklayer/contract/IInterfaceTable.h"
#include "inet/networklayer/common/NetworkInterface.h"
#include "inet/networklayer/common/FragmentationTag_m.h"
#include "inet/transportlayer/contract/udp/UdpCommand_m.h"
#include <algorithm>
#include <iomanip>
using namespace omnetpp;
using namespace inet;
Define_Module(CatalogUdpApp);

void CatalogUdpApp::initialize(int stage)
{
    if(stage!=INITSTAGE_APPLICATION_LAYER)return;
    plan=check_and_cast<TrafficPlan *>(getSimulation()->getSystemModule()->getSubmodule("trafficPlan"));
    flow=&plan->flow(par("flowId"));source=par("source");
    sentSignal=registerSignal("packetSent");receivedSignal=registerSignal("packetReceived");latencySignal=registerSignal("latency");
    socket.setOutputGate(gate("socketOut"));socket.setCallback(this);
    socket.bind(source?-1:5000+flow->id);
    socket.setMulticastLoop(false);
    if(flow->id==14) {
        if(source) {
            auto table=check_and_cast<IInterfaceTable *>(getContainingNode(this)->getSubmodule("interfaceTable"));
            socket.setMulticastOutputInterface(table->findInterfaceByName("eth0")->getInterfaceId());
        }
        else socket.joinMulticastGroup(L3Address("239.0.0.14"));
    }
    if(source) {
        destination=L3AddressResolver().resolve(flow->id==14?"239.0.0.14":flow->destinations.c_str());
        timer=new cMessage(flow->name.c_str());
        if(!plan->transientsOnly || flow->id>=21)scheduleNext();
    }
}
void CatalogUdpApp::scheduleNext()
{
    simtime_t next;
    if(flow->family=="transient") {
        auto& events=plan->events.at(flow->id-21);
        if(eventIndex>=int(events.size()))return;
        auto& e=events[eventIndex];
        // Measured volumes are application bytes; 1472 + IP/UDP 28 = MTU 1500.
        long segment=1472;
        long total=(e.volume+segment-1)/segment;
        if(eventPacket>=total){eventIndex++;eventPacket=0;scheduleNext();return;}
        next=SimTime(e.start)+SimTime(e.duration*double(eventPacket)/double(total));
    }
    else next=SimTime(plan->offset(*flow))+SimTime(plan->period(*flow))*cycle;
    if(next<SimTime(plan->end))scheduleAt(next,timer);
}
void CatalogUdpApp::handleMessage(cMessage *msg)
{
    if(msg!=timer){socket.processMessage(msg);return;}
    int size=flow->appBytes;int block=-1;
    if(flow->family=="transient") {
        auto& e=plan->events.at(flow->id-21).at(eventIndex);block=e.block;
        long segment=1472;
        long remaining=e.volume-eventPacket*segment;
        size=std::min(segment,remaining);
        eventPacket++;
    }
    int burst=flow->family=="camera"?flow->burst:1;
    if(plan->trace)plan->releases<<flow->name<<','<<simTime()<<','<<burst<<','<<size<<','<<block<<'\n';
    for(int i=0;i<burst;i++)emitPacket(size);
    cycle++;scheduleNext();
}
void CatalogUdpApp::emitPacket(int size)
{
    auto packet=new CatalogColorPacket((flow->name+"-"+std::to_string(sequence)).c_str());
    packet->setVisualPcp(flow->pcp);
    auto payload=makeShared<ApplicationPacket>();payload->setChunkLength(B(size));
    payload->setSequenceNumber(sequence);payload->addTag<CreationTimeTag>()->setCreationTime(simTime());
    packet->insertAtBack(payload);packet->addTag<FragmentationReq>()->setDontFragment(true);
    countPacket(size,sequence,simTime());sequence++;
    emit(sentSignal,packet);socket.sendTo(packet,destination,5000+flow->id);
}
void CatalogUdpApp::countPacket(int size,long seq,simtime_t created)
{
    packets++;appBytes+=size;sequenceSum+=seq;
    minSize=std::min(minSize,long(size));maxSize=std::max(maxSize,long(size));
    if(first<0)first=simTime();
    if(last>=0){auto gap=simTime()-last;minGap=std::min(minGap,gap);maxGap=std::max(maxGap,gap);}
    last=simTime();
    if(created>=SimTime(plan->warmup) && created<SimTime(plan->end)) {
        measuredPackets++;measuredBytes+=size;
        if(!source) {
            simtime_t latency=simTime()-created;maxLatency=std::max(maxLatency,latency);
            emit(latencySignal,latency);
            if(flow->deadline>0 && latency>SimTime(flow->deadline))misses++;
        }
    }
}
void CatalogUdpApp::socketDataArrived(UdpSocket *,Packet *packet)
{
    if(source)throw cRuntimeError("Source unexpectedly received a datagram");
    auto payload=packet->peekAtFront<ApplicationPacket>();
    long seq=payload->getSequenceNumber();
    if(seq<=lastSequence)duplicates++;lastSequence=seq;
    countPacket(B(packet->getDataLength()).get(),seq,payload->getTag<CreationTimeTag>()->getCreationTime());
    emit(receivedSignal,packet);delete packet;
}
void CatalogUdpApp::socketErrorArrived(UdpSocket *,Indication *indication)
{
    std::string message=indication->getName();delete indication;throw cRuntimeError("UDP error: %s",message.c_str());
}
void CatalogUdpApp::finish()
{
    if(!plan)return;
    std::string node=getContainingNode(this)->getFullPath();node=node.substr(node.find('.')+1);
    std::ofstream out(plan->directory+"/"+flow->name+"-"+node+(source?"-tx.csv":"-rx.csv"));
    out<<"flow,node,role,packets,app_bytes,measured_packets,measured_app_bytes,first,last,min_gap,max_gap,min_size,max_size,sequence_sum,duplicates_or_reorder,deadline_s,deadline_misses,max_latency\n"<<std::setprecision(15);
    out<<flow->name<<','<<node<<','<<(source?"tx":"rx")<<','<<packets<<','<<appBytes<<','<<measuredPackets<<','<<measuredBytes<<','<<first<<','<<last<<','<<minGap<<','<<maxGap<<','<<minSize<<','<<maxSize<<','<<sequenceSum<<','<<duplicates<<','<<flow->deadline<<','<<misses<<','<<maxLatency<<'\n';
    recordScalar("catalogPackets",packets);recordScalar("catalogAppBytes",appBytes);
    recordScalar("deadlineMisses",misses);recordScalar("maxLatency",maxLatency);
}
