#include "TrafficPlan.h"
#include "inet/common/INETDefs.h"
#include "inet/common/packet/Packet.h"
#include "inet/linklayer/ethernet/common/EthernetMacHeader_m.h"
#include "inet/linklayer/ieee8021q/Ieee8021qTagHeader_m.h"
#include "inet/networklayer/ipv4/Ipv4Header_m.h"
#include "inet/transportlayer/udp/UdpHeader_m.h"
#include <map>
#include <iomanip>
#include <algorithm>
using namespace omnetpp;
using namespace inet;

class TrafficAudit : public cSimpleModule, public cListener {
    struct Count {long packets=0,bytes=0,min=100000,max=0;uint64_t sequences=0;double first=-1,last=-1;};
    TrafficPlan *plan=nullptr;
    simsignal_t wireSignal,queueSignal,dropSignal;
    std::vector<std::pair<cModule *,simsignal_t>> subscriptions;
    std::map<std::pair<std::string,int>,Count> wires,queues,drops;
    std::map<std::string,simtime_t> nextAvailable;
    void subscribeTree(cModule *m) {
        std::string path=m->getFullPath();
        simsignal_t signal=SIMSIGNAL_NULL;
        if(path.find(".phyLayer.outboundEmitter")!=std::string::npos)signal=wireSignal;
        else if(std::string(m->getName())=="queue" && m->isVector()) {
            m->subscribe(queueSignal,this);subscriptions.push_back({m,queueSignal});
            signal=dropSignal;
        }
        if(signal!=SIMSIGNAL_NULL){m->subscribe(signal,this);subscriptions.push_back({m,signal});}
        for(cModule::SubmoduleIterator i(m);!i.end();++i)subscribeTree(*i);
    }
    int numInitStages() const override{return NUM_INIT_STAGES;}
    void initialize(int stage) override {
        if(stage!=INITSTAGE_LAST)return;
        plan=check_and_cast<TrafficPlan *>(getParentModule()->getSubmodule("trafficPlan"));
        wireSignal=registerSignal("packetSentToLower");queueSignal=registerSignal("packetPushStarted");dropSignal=registerSignal("packetDropped");
        subscribeTree(getParentModule());
    }
    void handleMessage(cMessage *) override {throw cRuntimeError("Audit is passive");}
    void receiveSignal(cComponent *component,simsignal_t signal,cObject *object,cObject *) override {
        auto packet=dynamic_cast<Packet *>(object);if(!packet)return;
        int fid=0;unsigned long seq=0;
        if(sscanf(packet->getName(),"F%d-%lu",&fid,&seq)!=2 || fid<1 || fid>22)return;
        auto f=plan->flow(fid);
        auto module=check_and_cast<cModule *>(component);
        auto path=module->getFullPath();auto ethEnd=path.find("].",path.find(".eth["));
        if(ethEnd==std::string::npos)throw cRuntimeError("Audit cannot identify interface: %s",path.c_str());
        auto ethPath=path.substr(0,ethEnd+1);
        auto key=std::make_pair(ethPath,fid);
        Count *count=nullptr;long bytes=0;
        if(signal==wireSignal) {
            // PHY packet already includes 8 B preamble/SFD; IFG is time, not packet data.
            auto mac=packet->peekAt<EthernetMacHeader>(B(8));
            if(mac->getTypeOrLength()!=0x8100)throw cRuntimeError("%s missing VLAN tag at %s",f.name.c_str(),path.c_str());
            auto vlan=packet->peekAt<Ieee8021qTagEpdHeader>(B(22));
            auto ip=packet->peekAt<Ipv4Header>(B(26));
            auto udp=packet->peekAt<UdpHeader>(B(46));
            int ipBytes=ip->getTotalLengthField().get();
            int payload=ipBytes-28;
            if(vlan->getVid()!=f.vlan || vlan->getPcp()!=f.pcp || udp->getDestinationPort()!=5000+fid)
                throw cRuntimeError("%s wrong VLAN/PCP/UDP at %s",f.name.c_str(),path.c_str());
            if(ipBytes>1500 || (fid<21 && payload!=f.appBytes))throw cRuntimeError("%s incorrect IPv4/payload size",f.name.c_str());
            bool multicast=mac->getDest().isMulticast();
            if(multicast!=(fid==14))throw cRuntimeError("Incorrect multicast addressing for %s",f.name.c_str());
            bytes=packet->getByteLength()+12;
            if(bytes!=std::max(64,ipBytes+22)+20)throw cRuntimeError("%s unexpected wire bytes %ld for IP %d",f.name.c_str(),bytes,ipBytes);
            auto eth=getSimulation()->getModuleByPath(ethPath.c_str());
            double rate=eth->par("bitrate");
            auto found=nextAvailable.find(ethPath);
            if(found!=nextAvailable.end() && simTime()+SimTime(2,SIMTIME_PS)<found->second)
                throw cRuntimeError("Serialization/IFG violated at %s",ethPath.c_str());
            nextAvailable[ethPath]=simTime()+SimTime(bytes*8.0/rate);
            count=&wires[key];
        }
        else {
            if(module->getIndex()!=f.pcp)throw cRuntimeError("%s reached wrong TC at %s",f.name.c_str(),path.c_str());
            count=signal==dropSignal?&drops[key]:&queues[key];bytes=packet->getByteLength();
        }
        count->packets++;count->bytes+=bytes;count->sequences+=seq;
        count->min=std::min(count->min,bytes);count->max=std::max(count->max,bytes);
        if(count->first<0)count->first=simTime().dbl();count->last=simTime().dbl();
    }
    void finish() override {
        for(auto item:{std::make_pair("wire",&wires),std::make_pair("queues",&queues),std::make_pair("drops",&drops)}) {
            std::ofstream out(plan->directory+"/"+item.first+".csv");
            out<<"interface,flow,packets,bytes,min_size,max_size,sequence_sum,first,last\n"<<std::setprecision(15);
            for(auto& entry:*item.second) {
                auto& c=entry.second;out<<entry.first.first<<",F"<<std::setw(2)<<std::setfill('0')<<entry.first.second<<','<<c.packets<<','<<c.bytes<<','<<c.min<<','<<c.max<<','<<c.sequences<<','<<c.first<<','<<c.last<<'\n';
            }
        }
    }
  public:
    ~TrafficAudit() override {
        // Modules may already have been deleted; OMNeT++ removes listener links on deletion.
    }
};
Define_Module(TrafficAudit);
