#include "TrafficPlan.h"
#include <algorithm>
#include <filesystem>
#include <iomanip>
#include <cmath>
using namespace omnetpp;
Define_Module(TrafficPlan);

void TrafficPlan::initialize()
{
    int level=par("loadLevel");
    if(level<0 || level>3) throw cRuntimeError("loadLevel must be 0..3");
    factor=std::array<double,4>{0.5,1,2.5,4}.at(level);
    std::string aggregation=par("aggregation").stdstringValue();
    if(aggregation!="A0" && aggregation!="A1") throw cRuntimeError("aggregation must be A0 or A1");
    aligned=aggregation=="A1";
    const std::string volumeLayer="app";
    warmup=par("warmup"); measurement=par("measurement"); end=warmup+measurement;
    if(warmup<0 || measurement<=0 || std::floor(measurement)!=measurement)
        throw cRuntimeError("measurement must be a positive whole number of seconds; warmup >= 0");
    directory=par("outputDirectory").stdstringValue();
    std::filesystem::create_directories(directory);
    trace=par("traceReleases");
    sourcePreShaping=par("sourcePreShaping");
    adasSpacingLimit=par("adasSpacingLimit");
    visionSpacingLimit=par("visionSpacingLimit");
    transientsOnly=par("transientsOnly");exhaustive=par("exhaustiveSignatures");
    if(exhaustive && !transientsOnly)throw cRuntimeError("Signature sweep is only for isolated diagnostics");
    if(trace) {
        releases.open(directory+"/releases.csv");
        releases << "flow,time,count,app_bytes,block\n" << std::setprecision(15);
        if(!releases) throw cRuntimeError("Cannot open release trace");
    }
    auto root=par("catalog").xmlValue();
    for(auto e:root->getChildrenByTagName("flow")) {
        auto a=[e](const char *s){auto v=e->getAttribute(s);if(!v)throw cRuntimeError("Missing flow attribute %s",s);return v;};
        int id=atoi(a("id")); if(id<1 || id>22) throw cRuntimeError("Invalid flow id");
        auto& f=flows[id]; f.id=id; f.name=a("name");f.source=a("source");f.destinations=a("destinations");
        f.family=a("family"); f.appBytes=atoi(a("app_bytes"));f.burst=atoi(a("burst"));
        f.pcp=atoi(a("pcp"));f.vlan=atoi(a("vlan"));f.scalable=atoi(a("scalable"));
        f.period=atof(a("period"));f.offset=atof(a("offset"));f.phase=atof(a("phase"));
        f.deadline=atof(a("deadline"));f.criticality=a("criticality");
    }
    for(int id=1;id<=22;id++) if(flows[id].name.empty())throw cRuntimeError("Missing flow %d",id);
    struct Signature {std::string name;double duration;long volume;};
    std::vector<Signature> signatures;
    for(auto e:root->getChildrenByTagName("signature"))
        signatures.push_back({e->getAttribute("name"),atof(e->getAttribute("duration")),atol(e->getAttribute("volume"))});
    if(signatures.size()!=10)throw cRuntimeError("Expected ten empirical signatures");
    std::ofstream out(directory+"/events.csv");
    out<<"flow,block,signature,start,duration,volume_bytes,volume_layer\n"<<std::setprecision(15);
    for(int block=0;block<int(measurement);block++) {
        double firstEnd=0;
        for(int stream=0;stream<2;stream++) {
            int index=exhaustive?(block+5*stream)%10:intuniform(0,9,stream); // Dedicated RNG per transient flow.
            auto& s=signatures[index];
            double start=warmup+block+0.005;
            if(stream==1 && !aligned)start=firstEnd+0.010;
            if(stream==0)firstEnd=start+s.duration;
            if(start+s.duration>warmup+block+1)throw cRuntimeError("Transient exceeds its one-second block");
            events[stream].push_back({block,index,start,s.duration,s.volume,s.name});
            out<<"F"<<21+stream<<','<<block<<','<<s.name<<','<<start<<','<<s.duration<<','<<s.volume<<','<<volumeLayer<<'\n';
        }
    }
    std::ofstream manifest(directory+"/run.csv");
    manifest<<"load,aggregation,factor,warmup,measurement,volume_layer,transients_only,exhaustive,source_pre_shaping,adas_spacing_limit,vision_spacing_limit\n"
            <<level<<','<<aggregation<<','<<factor<<','<<warmup<<','<<measurement<<','<<volumeLayer<<','<<transientsOnly<<','<<exhaustive<<','
            <<sourcePreShaping<<','<<adasSpacingLimit<<','<<visionSpacingLimit<<'\n';
}
double TrafficPlan::offset(const CatalogFlow& f) const
{
    if(f.family=="camera")return aligned?0:period(f)*f.phase;
    if(f.family=="best_effort")return period(f)*f.phase;
    return f.offset;
}
double TrafficPlan::cameraSpacing(const CatalogFlow& f) const
{
    if(!sourcePreShaping || f.family!="camera") return 0;
    const double limit = f.id <= 3 ? adasSpacingLimit : visionSpacingLimit;
    return std::min(limit, period(f) / 30.0);
}
void TrafficPlan::handleMessage(cMessage *) { throw cRuntimeError("TrafficPlan has no runtime messages"); }
