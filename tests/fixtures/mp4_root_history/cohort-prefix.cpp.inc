#include <cstdint>
#include <cstddef>
#include <cstring>
#include <cstdlib>
#include <atomic>
#include <cassert>
#include <map>
#include "history.hpp"
namespace mp4actor{struct Handle{uintptr_t handle=0;uint32_t version=0,padding=0;};}
namespace mp4world{struct DirectorGraphIdentity{uintptr_t native=0,slot=0;uint32_t version=0;};}
namespace mp4child{enum class Result:int{ok=0,waiting=1,invalid=-1,stale=-2,unsupported=-3,failed=-4};}
namespace mp4target{enum class Result:int{ok,waiting,stale,unsupported};}
enum class Mp4SceneResult:int{ok,waiting,stale,unsupported};
enum class Mp4TimelineProofPhase:uint8_t{admission,active,source_restore_plan,source_restored,source_bootstrap_plan};
struct Mp4SceneWitness{void*player=nullptr,*director=nullptr;uint64_t generation=7;};
uint32_t mp4_retain(void*);void*weak_get(uint32_t);void weak_free(uint32_t);
struct Mp4TimelineList {void*owner=nullptr,*list=nullptr,*array=nullptr,*element=nullptr;size_t owner_offset=0,stride=0;int32_t count=0,version=0;uint8_t*data=nullptr;};
// ACTUAL_CONTEXT
struct Mp4AudioProgramImage{};
namespace mp4_source_factory{struct Receipt{struct{struct{uint64_t serial=0;}ticket;struct{uintptr_t graph_native=0;uint32_t graph_version=0;}image;}source;mp4actor::Handle root{};};}
struct Mp4RootCaptureMarker{uint64_t epoch=0,serial=0;};
struct {bool active=true;unsigned captured=0,all=15,released=0,started=15;Mp4SceneWitness source{};}mp4_scene_host;
struct {unsigned depth=0;}mp4_raw_original_operation;namespace idoly_mp4_runtime{struct{uint64_t generation=9;}job;}
std::atomic<uint64_t>mp4_root_capture_withdraw_sequence{0};
struct Mp4RootHistoryInitialSeal{uint64_t epoch=0,capture=0;}mp4_root_history_initial_seal;
struct Model{int mode=0;bool thread=true,window=true,plan=true,logical=true,physical=false,full=false,active_ok=true,borrowed=false,source=true,target=true,activation=true;uint64_t module_image=17;int objects[2]{};uint8_t bytes[2][8]{{1},{2}};unsigned reads=0;std::map<uint32_t,void*>gc;uint32_t next=0;}model;
bool game_call(){return model.thread;}uint32_t mp4_retain(void*p){if(!p)return 0;const auto id=++model.next;model.gc[id]=p;return id;}void*weak_get(uint32_t id){auto it=model.gc.find(id);return it==model.gc.end()?nullptr:it->second;}void weak_free(uint32_t id){assert(model.gc.erase(id)==1);}
namespace idoly_mp4_actor_placement{struct Address{void*value;};}void*operator new(size_t,idoly_mp4_actor_placement::Address a)noexcept{return a.value;}
bool mp4_stage_source_window(){return model.window;}bool mp4_root_logical_capture_current(){return model.logical;}struct{bool current(){return model.window;}}mp4_early_source_gates;
struct Mp4SourcePlanEntry{Mp4TimelineContext*context=nullptr;struct Output{Mp4AudioProgramImage*audio=nullptr;}*outputs=nullptr;size_t output_count=0;mp4_source_factory::Receipt construction{};};
struct{Mp4SourcePlanEntry roots[65]{};size_t count=2;}mp4_source_director_plans;
bool mp4_source_director_plan_current(){return model.plan&&model.source;}bool mp4_source_director_plan_build(const Mp4SceneWitness&){return model.plan;}bool mp4_source_director_plan_close(size_t){return model.plan;}
bool mp4_timeline_current(const Mp4TimelineContext&c){return model.source&&(c.phase!=Mp4TimelineProofPhase::active||model.active_ok);}
bool mp4_source_factory_receipt(decltype(mp4_source_factory::Receipt{}.source.ticket)t,mp4_source_factory::Receipt*out){if(!model.source||t.serial<1||t.serial>2)return false;*out=mp4_source_director_plans.roots[t.serial-1].construction;return true;}
struct Mp4RootHistoryRead{mp4_root_history::View view{};mp4_root_history::List list{};};
bool mp4_root_history_read(Mp4TimelineContext&c,Mp4RootHistoryRead&out,const mp4_root_history::Module*mods,size_t count){++model.reads;if(!mp4_timeline_current(c))return false;size_t i=c.director==&model.objects[0]?0:1;auto&v=out.view;v.director=c.director;v.asset=c.asset;v.epoch=7;v.graph=c.graph.handle;v.root=c.root.handle;v.graph_version=v.root_version=2;out.list={c.root_script,(void*)0x10,(void*)(uintptr_t)(0x20+i),(void*)0x30,24,8,1,3,model.bytes[i]};v.lists=&out.list;v.list_count=1;v.modules=mods;v.module_count=count;return true;}
bool mp4_root_capture_marker(size_t,Mp4RootCaptureMarker*out){if(!model.physical)return false;*out={7,19};return true;}
bool mp4_source_plan_outputs(Mp4SourcePlanEntry&){return model.source;}
struct Mp4RootHistoryModules{mp4_root_history::Module values[4]{};size_t count=0;};
bool mp4_root_history_modules(Mp4SourcePlanEntry&e,Mp4RootHistoryModules&out){if(!model.physical)return false;out.count=1;out.values[0]={1,(void*)0x50,e.context->director,nullptr,nullptr,7,model.module_image};return true;}
mp4target::Result mp4_target_image_capture_recorded(uint64_t){return model.target?mp4target::Result::ok:mp4target::Result::unsupported;}
Mp4SceneResult mp4_root_capture_activation_targets(){return model.activation?Mp4SceneResult::ok:Mp4SceneResult::unsupported;}
bool mp4_root_history_initial_sealed(uint64_t epoch){return mp4_root_history_initial_seal.epoch==epoch&&mp4_root_history_initial_seal.capture;}
struct{bool finalized=false;}mp4_child_readonly_source;bool mp4_child_readonly_full_current(){return model.full;}

bool mp4_root_history_initial_borrowed(){return model.borrowed;}

bool mp4_root_history_full_close(Mp4SourcePlanEntry&e,Mp4RootHistoryModules&out){return mp4_source_plan_outputs(e)&&mp4_root_history_modules(e,out);}
