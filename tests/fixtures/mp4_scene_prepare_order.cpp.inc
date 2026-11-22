#include <cstdint>
#include <cassert>
#include <string>
#include <vector>
#include <algorithm>
// The shipping aggregate dispatcher executes. Captured-part masks, initial
// source-GPU fence and original PF/part callbacks are explicit input services.
enum class Mp4SceneResult{ok,waiting,stale,invalid,unsupported,failed};
enum class Mp4SceneOperation{capture,prepare,reset,restore};
bool main_thread=true,owner_current=true,gpu_ready=true,pf_ready=true,pf_reset=false,pf_busy=false,pf_reentry=false;
unsigned mp4_scene_property_restore_entered=0,mp4_scene_video_handoff_entered=0;
std::vector<std::string>events;int pf_calls=0,pf_resets=0;
namespace idoly_mp4_runtime{struct{uint64_t generation=9;}job;}
struct Part{unsigned index=0;Mp4SceneResult(*capture)(void*)=nullptr;Mp4SceneResult(*prepare)(void*)=nullptr;Mp4SceneResult(*reset)(void*)=nullptr;Mp4SceneResult(*restore)(void*)=nullptr;void*context=nullptr;};
struct{bool active=true,playback_handoff_running=false;unsigned configured=15,all=15,captured=15,prepared=0,reset=0,restored=0,count=4;struct{uint64_t generation=7;}source;const char*error="none";Part parts[4];}mp4_scene_host;
bool game_call(){return main_thread;}bool mp4_scene_owner_current(void*){return owner_current;}
Mp4SceneResult mp4_scene_fail(Mp4SceneResult r,const char*error){mp4_scene_host.error=error;return r;}
bool mp4_gpu_initial_source_fenced(uint64_t source,uint64_t job){events.push_back("gpu");return gpu_ready&&source==7&&job==9;}
Mp4SceneResult mp4_scene_run(Mp4SceneOperation);
Mp4SceneResult mp4_proflare_prepare_first_render(){++pf_calls;if(pf_busy)return Mp4SceneResult::waiting;pf_busy=true;
 if(pf_reentry){pf_reentry=false;assert(mp4_scene_run(Mp4SceneOperation::prepare)==Mp4SceneResult::waiting);}
 pf_busy=false;if(!pf_ready)return Mp4SceneResult::waiting;if(!pf_reset){pf_reset=true;++pf_resets;events.push_back("pf-reset");}return Mp4SceneResult::ok;}
Mp4SceneResult invoke(void*p){events.push_back("part"+std::to_string(static_cast<Part*>(p)->index));return Mp4SceneResult::ok;}
Mp4SceneResult mp4_root_capture_part(unsigned,const Part&){assert(false);return Mp4SceneResult::failed;}
Mp4SceneResult mp4_scene_part_result(const Part&,Mp4SceneResult r){return r;}
struct Mp4ScenePropertyRestoreScope{bool active=false;explicit Mp4ScenePropertyRestoreScope(bool requested,unsigned){assert(!requested);}bool finish(Mp4SceneResult){return true;}};
// ACTUAL_SCENE_RUN
int main(int argc,char**argv){assert(argc==2);const std::string name=argv[1];for(unsigned i=0;i<4;++i)mp4_scene_host.parts[i]={i,invoke,invoke,invoke,invoke,mp4_scene_host.parts+i};
 if(name=="capture_missing")mp4_scene_host.captured=7;
 if(name=="gpu_wait"){gpu_ready=false;}if(name=="pf_wait"){pf_ready=false;}if(name=="pf_reentry"){pf_reentry=true;}
 if(name=="property_active"){mp4_scene_property_restore_entered=1;}if(name=="video_active"){mp4_scene_video_handoff_entered=1;}if(name=="playback_active"){mp4_scene_host.playback_handoff_running=true;}
 auto r=mp4_scene_run(Mp4SceneOperation::prepare);
 if(name=="capture_missing"){assert(r==Mp4SceneResult::invalid&&events.empty()&&!pf_calls);return 0;}
 if(name=="property_active"||name=="video_active"||name=="playback_active"){assert(r==Mp4SceneResult::waiting&&events.empty()&&!pf_calls);return 0;}
 if(name=="gpu_wait"){assert(r==Mp4SceneResult::waiting&&!pf_calls&&!mp4_scene_host.prepared);gpu_ready=true;r=mp4_scene_run(Mp4SceneOperation::prepare);}
 if(name=="pf_wait"){assert(r==Mp4SceneResult::waiting&&pf_calls==1&&!pf_resets&&!mp4_scene_host.prepared);pf_ready=true;r=mp4_scene_run(Mp4SceneOperation::prepare);}
 assert(r==Mp4SceneResult::ok&&mp4_scene_host.prepared==15&&pf_resets==1);
 const auto pf=std::find(events.begin(),events.end(),"pf-reset"),actor=std::find(events.begin(),events.end(),"part0");assert(pf<actor);
 const auto count=events.size();assert(mp4_scene_run(Mp4SceneOperation::prepare)==Mp4SceneResult::ok&&pf_resets==1&&events.size()==count+1);return 0;}
