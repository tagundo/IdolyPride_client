#include <atomic>
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>
std::string mode;std::vector<std::string>events;
namespace mp4stage {
enum class Result{ok,waiting,invalid,unsupported,failed,stale};
struct EquipmentScope{Result configure(int,void**,size_t,void*);Result admit();Result release(bool);};
Result admit_particles(int,int*,size_t,void*);Result admit_psyllium(int,void*,void*,void*);
}
using Mp4SceneResult=mp4stage::Result;
struct Mp4SceneWitness{void*camera=nullptr;uint64_t generation=1;};
struct Host{bool configured=false,admitting=false;int owners[2]{};size_t count=1;void*psyllium=nullptr;void*controllers[1]{};size_t controller_count=0;const char*error="none";Mp4SceneWitness source{};}mp4_stage_host;
struct{const char*error="none";}mp4_equipment_targets;
std::atomic<bool>mp4_stage_foreign_dirty{false};
int release_calls=0,drop_calls=0,observe_calls=0,seal_calls=0,capture_calls=0;bool observed=false,sealed=false;
uint64_t mp4_stage_admission_begin(const Mp4SceneWitness&){events.push_back("begin");return mode=="no_attempt"?0:17;}
bool mp4_stage_admission_observe(uint64_t attempt,const Mp4SceneWitness&){assert(attempt==17&&mp4_stage_host.admitting&&!release_calls&&!drop_calls);events.push_back("observe");++observe_calls;if(mode=="observe_throw")throw 7;observed=true;return mode!="observe_failed";}
bool mp4_stage_admission_seal(uint64_t attempt,bool success){assert(attempt==17&&release_calls==1&&drop_calls==1&&!mp4_stage_host.admitting&&!mp4_stage_host.configured);events.push_back(success?"seal":"abort");++seal_calls;assert(!success||observed);sealed=success&&mode!="seal_failed";return sealed;}
void mp4_stage_drop_roots(){events.push_back("drop");++drop_calls;assert(release_calls==1);mp4_stage_host={};}
int mp4_stage_api(){return 1;}int mp4_stage_psy_api(){return 2;}int mp4_stage_equipment_make_api(){return 3;}
bool mp4_stage_collect(const Mp4SceneWitness&w){events.push_back("collect");mp4_stage_host.source=w;if(mode=="collect_throw")throw 3;if(mode=="palette_wait")mp4_stage_host.psyllium=&mp4_stage_host;return mode!="collect_failed";}
bool mp4_stage_psy_palette(void*,void**,void**,bool){events.push_back("palette");return false;}
Mp4SceneResult mp4_stage_result(mp4stage::Result r){return r;}
namespace mp4stage {
Result EquipmentScope::configure(int api,void**,size_t,void*){assert(api==3);events.push_back("equipment_configure");return mode=="equipment_configure_failed"?Result::unsupported:Result::ok;}
Result EquipmentScope::admit(){events.push_back("equipment_admit");if(mode=="equipment_throw")throw 9;return mode=="equipment_failed"?Result::unsupported:Result::ok;}
Result EquipmentScope::release(bool owned){assert(!owned&&mp4_stage_host.admitting);events.push_back("release");++release_calls;if(mode=="cleanup_throw")throw 11;return mode=="cleanup_failed"?Result::failed:Result::ok;}
Result admit_particles(int api,int*,size_t,void*){assert(api==1);events.push_back("particles");return mode=="particles_failed"?Result::unsupported:Result::ok;}
Result admit_psyllium(int api,void*,void*,void*){assert(api==2);events.push_back("psyllium");return mode=="psyllium_failed"?Result::unsupported:Result::ok;}
}
bool mp4_stage_refresh_inventory(){events.push_back("inventory");return mode!="capture_inventory";}
bool mp4_stage_refresh_controls(){events.push_back("controls");return mode!="capture_controls";}
bool mp4_stage_admission_before_capture(const Mp4SceneWitness&){events.push_back("before_capture");assert(!capture_calls);return sealed&&mode!="capture_receipt";}
struct Capture{mp4stage::Result capture(){events.push_back("capture");++capture_calls;return mp4stage::Result::ok;}}mp4_stage_equipment,mp4_stage_particles,mp4_stage_psyllium;
#include "particle-admission-wiring.cpp.inc"
int main(int argc,char**argv){assert(argc==2);mode=argv[1];Mp4SceneWitness w;auto result=mp4_stage_admit(nullptr,w);
 if(mode=="no_attempt"){assert(result==Mp4SceneResult::unsupported&&!release_calls&&!drop_calls&&!observe_calls&&!seal_calls);return 0;}
 assert(release_calls==1&&drop_calls==1&&seal_calls==1);
 const bool providers=mode=="normal"||mode=="cleanup_failed"||mode=="cleanup_throw"||mode=="seal_failed"||mode.rfind("capture_",0)==0;
 assert((observe_calls==1)==(providers||mode=="observe_failed"||mode=="observe_throw"));
 const bool success=mode=="normal"||mode.rfind("capture_",0)==0;assert((result==Mp4SceneResult::ok)==success&&sealed==success);
 if(success){mp4_stage_host.configured=true;mp4_stage_host.source=w;auto captured=mp4_stage_capture(nullptr);const bool full=mode=="normal";assert((captured==Mp4SceneResult::ok)==full&&capture_calls==(full?3:0));
 auto before=events.begin();for(auto i=events.begin();i!=events.end();++i)if(*i=="before_capture")before=i;if(full){assert(before!=events.begin()&&before+1!=events.end()&&*(before+1)=="capture");}}
 return 0;
}
