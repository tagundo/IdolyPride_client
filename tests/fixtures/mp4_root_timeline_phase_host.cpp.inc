#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <cstdlib>
#include <cmath>
#include <new>
#include <string>
namespace mp4actor {struct Handle {uintptr_t handle=0;uint32_t version=0;uint32_t padding=0;};}
namespace mp4game {struct PlayableGraph {uintptr_t handle=0;uint32_t version=0;uint32_t padding=0;};struct Layout{size_t player_director_controller=64,controller_directors=72;};}
namespace mp4world {struct DirectorGraphIdentity{uintptr_t native=0,slot=0;uint32_t version=0;};}
struct Mp4SceneWitness {void*player=nullptr;void*director=nullptr;void*camera_director=nullptr;uint64_t generation=0;};
void* p(uintptr_t x){return reinterpret_cast<void*>(x);}
Mp4SceneWitness selected{p(1),p(2),nullptr,7};
bool thread_ok=true,source_ok=true,registry_ok=true,clock_active=true,clock_held=true,parts_ok=true,children_ok=true;
bool intrinsic_ok=true,normal_closed=true,mutate_list=false,mutate_source=false;
uint32_t list_version=1;int visits=0;double current_time=10;
bool game_call(){return thread_ok;}
bool mp4_source_verified=true,mp4_actor_source_verified=true;
bool mp4_scene_same_source(const Mp4SceneWitness&a,const Mp4SceneWitness&b){return a.player==b.player&&a.director==b.director&&a.camera_director==b.camera_director&&a.generation==b.generation;}
bool mp4_scene_source_current(){return source_ok;}
bool mp4_scene_normal_animation_closed(){return normal_closed;}
bool mp4_scene_parts_available(){return parts_ok;}
struct Part{void*context=nullptr;bool(*restoration_verified)(void*)=nullptr;};
bool child_verified(void*){return children_ok;}
struct Host {bool active=true,invalidated=false,releasing=false;unsigned admitted=7,configured=31,captured=1,prepared=31,restored=31,finalized=2,all=31;Mp4SceneWitness source=selected,admitted_source=selected;Part parts[5]{};}mp4_scene_host;
bool admission_receipt=true;bool mp4_stage_admission_source(const Mp4SceneWitness&w){return admission_receipt&&w.generation==selected.generation;}
struct SourceHost{bool verified=true;Mp4SceneWitness source=selected;}mp4_camera_host,mp4_stage_host,mp4_world_host;
namespace idoly_mp4_playback {enum class Phase {acquiring,held,starting,playing,restoring};}
namespace idoly_mp4_runtime {
struct Clock{bool active()const{return clock_active;}bool held()const{return clock_held;}}clock;
const Clock&native_clock_scope(){return clock;}
struct Game {idoly_mp4_playback::Phase phase=idoly_mp4_playback::Phase::held;
 bool selected_scene_witness(Mp4SceneWitness&out){out=selected;return source_ok;}
 idoly_mp4_playback::Phase automatic_rebuild_phase(){return phase;}
 struct Description {double previous_time_seconds=10;}desc;
 const Description&description(){return desc;}
}game;
}
struct RebuiltGraph {uint64_t epoch=7,receipt=1;uintptr_t source_asset=7,native=6,slot=5;bool invoked=true;};
struct Ledger {uint64_t epoch=7,transaction=1;bool active=false,evaluation_pending=false;void*director=p(2);void*asset=p(7);size_t transaction_begin=0,graph_count=1;RebuiltGraph graphs[1]{};}mp4_rebuild_ledger;
struct Api {void*(*director_get_asset)(void*,void*)=nullptr;double(*director_get_time)(void*,void*)=nullptr;void(*director_graph_injected)(void*,mp4game::PlayableGraph*,void*)=nullptr;}mp4_api;
void* get_asset(void*,void*){return p(7);}double get_time(void*,void*){return current_time;}
void get_graph(void*,mp4game::PlayableGraph*out,void*){*out={5,7,0};}
enum class Mp4TimelineProofPhase:uint8_t {admission=0,active=1,source_restore_plan=2,source_restore=source_restore_plan,source_restored=3};
struct Mp4TimelineContext {Mp4TimelineProofPhase phase=Mp4TimelineProofPhase::active;Mp4SceneWitness witness{};mp4world::DirectorGraphIdentity identity{};void*director=nullptr;void*asset=nullptr;void*root_script=nullptr;mp4actor::Handle graph{},root{},nodes[4096]{};void*scripts[4096]{};size_t node_count=0;bool keep(void*){return true;}};
struct Hooks{bool(*current)(const Mp4TimelineContext&)=nullptr;}mp4_timeline_hooks;
bool(*mp4_timeline_intrinsic_restore_verified)(const Mp4TimelineContext&)=nullptr;
bool mp4_scene_registry_current_graph(uintptr_t native,uintptr_t slot,uint32_t version){return registry_ok&&native==6&&slot==5&&version==7;}
bool mp4_timeline_pins_current(){return true;}
struct {int root=0;}mp4_timeline_pins;
bool mp4_timeline_exact(void*,int){return true;}
bool mp4_timeline_director(Mp4TimelineContext&c){c.director=c.witness.director;c.asset=p(7);return true;}
void* mp4_timeline_script(mp4actor::Handle){return p(8);}
bool mp4_timeline_tracks(Mp4TimelineContext&){return true;}
bool mp4_timeline_entries(Mp4TimelineContext&){return true;}
bool mp4_timeline_runtime_elements(Mp4TimelineContext&,bool){return true;}
bool mp4_timeline_lists_current(const Mp4TimelineContext&){return true;}
bool mp4_root_track_field(void*,const char*,size_t){return true;}
template<class T>bool mp4_actor_field(void*object,size_t offset,T&out){
 if constexpr(sizeof(T)==sizeof(void*)){void*value=nullptr;
  if(object==p(1)&&offset==64)value=p(3);
  else if(object==p(3)&&offset==72)value=p(4);
  else return false;
  std::memcpy(&out,&value,sizeof value);return true;
 }else if constexpr(sizeof(T)==sizeof(uint32_t)){
  if(object!=p(4)||offset!=28)return false;
  std::memcpy(&out,&list_version,sizeof list_version);return true;
 }
 return false;
}
bool mp4_actor_list(void*list,void***data,size_t*count,size_t){if(list!=p(4))return false;*data=nullptr;*count=0;return true;}
struct Mp4ActorTempRoot {void*value;explicit Mp4ActorTempRoot(void*v):value(v){}void*get()const{return value;}};
uint32_t mp4_retain(void*object){return static_cast<uint32_t>(reinterpret_cast<uintptr_t>(object));}
void* weak_get(uint32_t root){return p(root);}void weak_free(uint32_t){}
bool mp4_type_is(void*object,const char*){return object==p(2);}bool mp4_alive(void*object){return object!=nullptr;}
bool mp4_receipt_graph(mp4actor::Handle h,uintptr_t*native,uint32_t*version){*native=6;*version=h.version;return h.handle==5;}
bool mp4_director_graph_nodes(const mp4world::DirectorGraphIdentity&,mp4actor::Handle*out,size_t,size_t*count){out[0]={9,1,0};*count=1;return true;}
struct StateApi{int(*graph_root_count)(mp4actor::Handle*,void*)=nullptr;void(*graph_root)(mp4actor::Handle*,int,mp4actor::Handle*,void*)=nullptr;};
int root_count(mp4actor::Handle*,void*){return 1;}void root(mp4actor::Handle*,int,mp4actor::Handle*out,void*){*out={9,1,0};}
StateApi mp4_actor_state_api(){return {root_count,root};}
// SHIPPING_ROOT_TIMELINE_PHASE_HOST
bool intrinsic(const Mp4TimelineContext&){return intrinsic_ok;}
bool visited(const Mp4TimelineContext&,void*){++visits;if(mutate_list)++list_version;if(mutate_source)source_ok=false;return true;}
int main(int argc,char**argv){assert(argc==2);const std::string mode=argv[1];
 mp4_api={get_asset,get_time,get_graph};mp4_timeline_hooks.current=mp4_timeline_phase_current;
 mp4_timeline_intrinsic_restore_verified=intrinsic;for(auto&part:mp4_scene_host.parts)part.restoration_verified=child_verified;
 Mp4TimelineContext c{};c.witness=selected;c.director=p(2);c.asset=p(7);c.identity={6,5,7};
 if(mode=="admission"||mode=="admission_after_stage_cleanup"||mode=="admission_receipt_lost"||mode=="admission_other_source"||mode=="admission_unpublished"){
  c.phase=Mp4TimelineProofPhase::admission;mp4_scene_host.active=false;
  if(mode=="admission_after_stage_cleanup")mp4_stage_host.source.generation=0;
  if(mode=="admission_receipt_lost")admission_receipt=false;
  if(mode=="admission_other_source")mp4_scene_host.admitted_source.generation=8;
  if(mode=="admission_unpublished")mp4_scene_host.admitted=3;
  assert(mp4_timeline_restoration_plan_closed(c)==(mode=="admission"||mode=="admission_after_stage_cleanup"));return 0;}
 if(mode=="active_stage_source_lost"){mp4_stage_host.source.generation=8;assert(!mp4_timeline_phase_current(c));return 0;}
 if(mode=="current_missing_callback"){mp4_timeline_hooks.current=nullptr;assert(!mp4_timeline_current(c));return 0;}
 if(mode=="current_foreign_graph"){registry_ok=false;assert(!mp4_timeline_current(c));return 0;}
 if(mode=="active_held_partial"){assert(mp4_timeline_restoration_plan_closed(c));return 0;}
 if(mode=="active_started_partial"){idoly_mp4_runtime::game.phase=idoly_mp4_playback::Phase::playing;assert(!mp4_timeline_restoration_plan_closed(c));return 0;}
 if(mode=="active_started_complete"){idoly_mp4_runtime::game.phase=idoly_mp4_playback::Phase::playing;mp4_scene_host.captured=31;assert(mp4_timeline_restoration_plan_closed(c));return 0;}
 if((mode.rfind("restore_final_",0)==0&&mode!="restore_final_visitor")||mode=="restore_plan_before_children"){
  c.phase=mode=="restore_plan_before_children"?Mp4TimelineProofPhase::source_restore_plan:Mp4TimelineProofPhase::source_restored;
  idoly_mp4_runtime::game.phase=idoly_mp4_playback::Phase::restoring;mp4_scene_host.captured=31;
  if(mode=="restore_plan_before_children"||mode=="restore_final_children_pending")children_ok=false;
  if(mode=="restore_final_parent_pending")mp4_scene_host.finalized=0;
  if(mode=="restore_final_eval_pending")mp4_rebuild_ledger.evaluation_pending=true;
  if(mode=="restore_final_speed_pending")intrinsic_ok=false;
  assert(mp4_timeline_restoration_plan_closed(c)==(mode=="restore_final_full"||mode=="restore_plan_before_children"));return 0;
 }
 auto phase=Mp4TimelineProofPhase::active;bool expected=mode=="capture_partial";
 if(mode=="capture_unconfigured")mp4_scene_host.configured=15;
 if(mode=="capture_wrong_phase")idoly_mp4_runtime::game.phase=idoly_mp4_playback::Phase::restoring;
 if(mode=="capture_clock_running")clock_held=false;
 if(mode=="capture_admission")phase=Mp4TimelineProofPhase::admission;
 if(mode.rfind("restore_",0)==0){phase=Mp4TimelineProofPhase::source_restore_plan;idoly_mp4_runtime::game.phase=idoly_mp4_playback::Phase::restoring;
  if(mode!="restore_partial")mp4_scene_host.captured=31;
  if(mode=="restore_final_visitor")phase=Mp4TimelineProofPhase::source_restored;
  if(mode=="restore_unprepared")mp4_scene_host.prepared=15;
  if(mode=="restore_nonheld")clock_held=false;
  expected=mode=="restore_plan"||mode=="restore_final_visitor";
 }
 if(mode=="context_wrong_list_version")mutate_list=true;
 if(mode=="context_source_lost")mutate_source=true;
 const bool result=mp4_timeline_visit_owned_contexts(phase,visited,nullptr);assert(result==expected);
 if(expected)assert(visits==1);
}
