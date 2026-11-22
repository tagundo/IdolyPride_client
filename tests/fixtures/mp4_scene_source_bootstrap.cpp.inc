#include <cassert>
#include <cstdint>
#include <string>
#include <vector>
#include <algorithm>
#include <stdexcept>
// Unity/native job, resource and historical-image calls are explicit modeled
// leaves. The real shipping bootstrap Scope and concrete dispatcher execute.
// FORMAL_SCOPE
using Mp4SceneResult=idoly_mp4_source_bootstrap::Result;
namespace mp4child{using Result=Mp4SceneResult;}
namespace idoly_mp4_playback{enum class Phase{acquiring,held};}
struct Source{uint64_t generation=1;void*player=reinterpret_cast<void*>(3);void*presenter=reinterpret_cast<void*>(5);};
bool owner=true,source_current=true,clock_held=true,producer_ready=true,root_ready=true,cohort_ready=true;
bool before_wait=false,before_waited=false,release_wait=false,release_waited=false,initial_ready=true;
bool capture_lost=false,commit_lost=false,throw_before=false;
std::vector<std::string>events;
int configure_calls=0,baseline_calls=0,logical_calls=0,readonly_calls=0,cohort_calls=0,commit_calls=0,promotion_calls=0;bool promotion_wait=false,promotion_waited=false,promotion_reentry=false,release_reentry=false;
int late_source_reads=0;bool observed_loss=false;
unsigned mp4_scene_property_restore_entered=0,mp4_scene_video_handoff_entered=0;
bool game_call(){return owner;}
bool mp4_scene_source_current(){return source_current;}
bool mp4_actor_clock_held(void*){return clock_held;}
namespace idoly_mp4_runtime{
struct{uint64_t generation=2;}job;
struct{ idoly_mp4_playback::Phase phase=idoly_mp4_playback::Phase::acquiring;
 auto automatic_rebuild_phase(){return phase;}}game;
}
struct{unsigned depth=0;}mp4_raw_original_operation;
struct{bool active=false;}mp4_rebuild_ledger;
struct Part{unsigned index=0;int quiet=0,capture=0,release=0;bool current=true;};
Part part_models[4]={{0},{1},{2},{3}};
Mp4SceneResult quiet(void*p){auto&v=*static_cast<Part*>(p);++v.quiet;events.push_back("quiet"+std::to_string(v.index));return Mp4SceneResult::ok;}
Mp4SceneResult release_part(void*p,bool owned){assert(!owned);auto&v=*static_cast<Part*>(p);++v.release;events.push_back("release"+std::to_string(v.index));return Mp4SceneResult::ok;}
bool owner_current(void*p){if(observed_loss)++late_source_reads;return static_cast<Part*>(p)->current&&source_current;}
struct PartApi{void*context;Mp4SceneResult(*quiesce)(void*);Mp4SceneResult(*release)(void*,bool);bool(*owner_current)(void*);bool(*restoration_verified)(void*)=nullptr;Mp4SceneResult(*detach_global_loops)(void*)=nullptr;};
struct{Source source{};bool active=true,invalidated=false,releasing=false;unsigned count=4,configured=15,started=15,released=0,captured=0,all=15;
 bool playback_handoff_running=false,release_owned=false,logical_checkpoint=false,pending_camera_restore=false,pending_dependency_restore=false,detached=false,last_camera_restore=false,last_dependency_restore=false;unsigned restored=0,finalized=0;void*last_player=nullptr,*last_presenter=nullptr;
 void*root_asset=reinterpret_cast<void*>(4);const char*error="none";PartApi parts[4]{};}mp4_scene_host;
Mp4SceneResult mp4_scene_part_result(const PartApi&,Mp4SceneResult r){return r;}
Mp4SceneResult mp4_scene_configure(){if(!source_current)return Mp4SceneResult::stale;++configure_calls;events.push_back("configure");return Mp4SceneResult::ok;}
void mp4_scene_revoke_grants(void*)noexcept{events.push_back("withdraw");}
void mp4_scene_drop_roots(){events.push_back("drop");mp4_scene_host.active=false;mp4_scene_host.source={};mp4_scene_host.source.player=nullptr;mp4_scene_host.root_asset=nullptr;}
unsigned catalogue_clears=0;
void mp4_birth_catalogue_clear(){++catalogue_clears;events.push_back("catalogue");}
struct{bool active=false;int acquires=0,releases=0;bool started()const{return active;}bool current()const{return active&&source_current;}
 Mp4SceneResult acquire(){events.push_back("gate");++acquires;active=true;return Mp4SceneResult::ok;}
 Mp4SceneResult release_after_fence(){events.push_back("ungate");++releases;active=false;return Mp4SceneResult::ok;}}mp4_early_source_gates;
// Actual graphics/engine leaves are modeled separately from Source CPU gates.
struct {bool active=false;uint64_t source=0,job=0;}mp4_render_hold_state;
bool render_acquire_ready=true,render_checkpoint_ready=true,render_retire_ready=true,render_retire_reentry=false;
int render_acquires=0,render_checkpoints=0,render_retires=0;
Mp4SceneResult mp4_scene_source_bootstrap_release();
Mp4SceneResult mp4_scene_source_bootstrap_before_part_release(bool);
Mp4SceneResult mp4_render_hold_acquire(uint64_t source,uint64_t job){++render_acquires;events.push_back("render-acquire");if(!render_acquire_ready)return Mp4SceneResult::waiting;
 if(mp4_render_hold_state.active)return mp4_render_hold_state.source==source&&mp4_render_hold_state.job==job?Mp4SceneResult::ok:Mp4SceneResult::stale;
 mp4_render_hold_state={true,source,job};return Mp4SceneResult::ok;}
bool mp4_render_hold_scope_checkpoint(uint64_t source,uint64_t job){++render_checkpoints;events.push_back("render-checkpoint");return render_checkpoint_ready&&mp4_render_hold_state.active&&mp4_render_hold_state.source==source&&mp4_render_hold_state.job==job;}
Mp4SceneResult mp4_render_hold_retire(uint64_t job){++render_retires;events.push_back("render-retire");if(render_retire_reentry){assert(mp4_scene_source_bootstrap_release()==Mp4SceneResult::waiting);assert(mp4_scene_source_bootstrap_before_part_release(false)==Mp4SceneResult::waiting);}
 if(!render_retire_ready||!mp4_render_hold_state.active||mp4_render_hold_state.job!=job){return Mp4SceneResult::waiting;}mp4_render_hold_state={};return Mp4SceneResult::ok;}
bool srp_captured=false,srp_capture_ready=true,srp_current_ready=true,srp_release_ready=true,srp_restore_ready=true,srp_mutated=false,srp_restored=false;
int srp_capture_calls=0,srp_restore_calls=0;
bool mp4_srp_source_capture(){if(!srp_capture_ready)return false;if(!srp_captured){++srp_capture_calls;events.push_back("srp");srp_captured=true;}return srp_current_ready;}
bool mp4_srp_source_initial_current(){return srp_captured&&srp_current_ready;}
void mp4_srp_source_withdraw()noexcept{events.push_back("srp-withdraw");}
bool mp4_srp_source_restore(){if(!srp_captured||!srp_mutated||srp_restored)return true;++srp_restore_calls;events.push_back("srp-restore");if(!srp_restore_ready)return false;srp_restored=true;return true;}
bool mp4_srp_source_release(){if(!srp_release_ready||(srp_mutated&&!srp_restored))return false;events.push_back("unsrp");srp_captured=srp_mutated=srp_restored=false;return true;}
struct{bool captured=false;}mp4_volume_assembly;
bool mp4_camera_source_baselines_capture_or_verify(){if(!mp4_volume_assembly.captured){++baseline_calls;events.push_back("baseline");mp4_volume_assembly.captured=true;}return source_current;}
Mp4SceneResult mp4_camera_source_baselines_release(){events.push_back("unbaseline");mp4_volume_assembly.captured=false;return Mp4SceneResult::ok;}
struct{unsigned completed=0;}mp4_stage_source_logical;
struct Logical{bool current()const{return mp4_stage_source_logical.completed==7&&source_current;}}mp4_control_assets,mp4_director_nodes,mp4_activation_nodes;
Mp4SceneResult mp4_stage_source_logical_capture(){++logical_calls;events.push_back("logical");mp4_stage_source_logical.completed=7;return Mp4SceneResult::ok;}
Mp4SceneResult mp4_root_capture_logical(){return mp4_stage_source_logical_capture();}
bool mp4_stage_source_logical_release(){events.push_back("unlogical");mp4_stage_source_logical.completed=0;return true;}
struct{uint64_t serial=0;bool finalized=false;}mp4_child_readonly_source;
bool full_child=false;
mp4child::Result mp4_child_readonly_capture(uint64_t*out){++readonly_calls;events.push_back("readonly");mp4_child_readonly_source.serial=500+idoly_mp4_runtime::job.generation;*out=mp4_child_readonly_source.serial;return Mp4SceneResult::ok;}
bool mp4_child_readonly_current(){if(observed_loss)++late_source_reads;return mp4_child_readonly_source.serial&&source_current;}
mp4child::Result mp4_child_readonly_finalize(){events.push_back("finalize");if(!full_child)return Mp4SceneResult::unsupported;mp4_child_readonly_source.finalized=true;return Mp4SceneResult::ok;}
void mp4_child_readonly_withdraw_source()noexcept{events.push_back("readonly-withdraw");}
bool mp4_child_readonly_release(){events.push_back("unreadonly");mp4_child_readonly_source={};return true;}
struct WorldScope{bool owned=false;bool active()const{return owned;}bool adopted_fixed_current()const{return owned&&source_current;}bool restorable()const{if(observed_loss)++late_source_reads;return owned&&source_current;}};
struct{WorldScope scope;bool animation_owned=false;}mp4_world_host;
struct{}mp4_world_adopted_animation;
struct{template<class T>bool lease_current(T&,void*)const{return mp4_world_host.animation_owned&&source_current;}}mp4_animation_gate;
Mp4SceneResult mp4_world_full_quiesce_adopting_source_gates(){events.push_back("world");mp4_world_host.scope.owned=true;mp4_world_host.animation_owned=true;return Mp4SceneResult::ok;}
enum class Mp4SceneOperation{capture};
Mp4SceneResult mp4_scene_run(Mp4SceneOperation){for(auto&p:part_models){++p.capture;events.push_back("capture"+std::to_string(p.index));mp4_scene_host.captured|=1u<<p.index;}if(capture_lost){source_current=false;observed_loss=true;}return Mp4SceneResult::ok;}
struct{uint64_t epoch=0,capture=0;}mp4_root_history_initial_seal;
bool mp4_root_history_initial_sealed(uint64_t epoch){return epoch&&epoch==mp4_root_history_initial_seal.epoch&&mp4_root_history_initial_seal.capture;}
void mp4_stage_admission_drop()noexcept{}
void mp4_stage_withdraw_interception()noexcept{}
Mp4SceneResult mp4_scene_fail(Mp4SceneResult result,const char*error){mp4_scene_host.error=error;return result;}
bool mp4_scene_owner_current(void*){return owner&&source_current&&!mp4_scene_host.invalidated;}
// CONCRETE_HOST
// OUTER_QUIESCE
// OUTER_RELEASE
struct Recipe{uint64_t value=0;bool held=false,withdrawn=false;};
Recipe recipes[3];int release_calls[3]{};
using Key=mp4sb::Key;
uint64_t recipe_id(size_t index,const Key&key){return key.job*1000+index+1;}
mp4sb::Result external_advance(size_t i,const Key&key,uint64_t*out){*out=0;events.push_back("external"+std::to_string(i));
 if(i==0&&!producer_ready)return mp4sb::Result::unsupported;
 if(i==1){if(!root_ready)return mp4sb::Result::unsupported;if(throw_before)throw 1;if(before_wait&&!before_waited){before_waited=true;recipes[i].held=true;return mp4sb::Result::waiting;}}
 if(i==2){++cohort_calls;assert(mp4_scene_host.captured==15&&mp4_world_host.scope.active());for(auto&p:part_models)assert(p.capture==1);if(!cohort_ready)return mp4sb::Result::unsupported;full_child=true;}
 recipes[i].value=recipe_id(i,key);recipes[i].held=true;recipes[i].withdrawn=false;*out=recipes[i].value;return mp4sb::Result::ok;}
bool external_current(size_t i,const Key&key,uint64_t receipt){return source_current&&recipes[i].held&&!recipes[i].withdrawn&&receipt==recipe_id(i,key)&&receipt==recipes[i].value;}
void external_withdraw(size_t i){events.push_back("xwithdraw"+std::to_string(i));recipes[i].withdrawn=true;}
mp4sb::Result external_release(size_t i){if(release_reentry&&i==2){assert(mp4_scene_source_bootstrap_release()==Mp4SceneResult::waiting);assert(mp4_scene_source_bootstrap_before_part_release(false)==Mp4SceneResult::waiting);}
 ++release_calls[i];events.push_back("xrelease"+std::to_string(i));if(i==1&&release_wait&&!release_waited){release_waited=true;return mp4sb::Result::waiting;}recipes[i]={};return mp4sb::Result::ok;}
template<size_t I>mp4sb::Provider external(){return {
 [](void*,const Key&k,uint64_t*r){return external_advance(I,k,r);},
 [](void*,const Key&k,uint64_t r){return external_current(I,k,r);},
 [](void*,const Key&){external_withdraw(I);},
 [](void*,const Key&){return external_release(I);}};}
bool initial_commit(void*,const Key&key,uint64_t receipt){++commit_calls;events.push_back("commit");assert(full_child&&mp4_child_readonly_source.finalized&&receipt==recipes[2].value);if(!initial_ready)return false;if(commit_lost){source_current=false;observed_loss=true;return false;}mp4_root_history_initial_seal={key.epoch,receipt};return true;}
mp4sb::Result before_part_release(void*,const Key&,bool){if(promotion_reentry){assert(mp4_scene_source_bootstrap_before_part_release(true)==Mp4SceneResult::waiting);assert(mp4_scene_source_bootstrap_release()==Mp4SceneResult::waiting);}
 ++promotion_calls;events.push_back("promote");
 for(const auto&p:part_models)assert(p.release==0);
 assert(recipes[2].held&&mp4_child_readonly_source.finalized);
 if(promotion_wait&&!promotion_waited){promotion_waited=true;return mp4sb::Result::waiting;}
 return mp4sb::Result::ok;
}
void bind(){for(unsigned i=0;i<4;++i)mp4_scene_host.parts[i]={&part_models[i],quiet,release_part,owner_current};
 mp4_scene_host.parts[3].detach_global_loops=[](void*){events.push_back("detach");return Mp4SceneResult::ok;};
 mp4_source_bootstrap_joins.context=&recipes;mp4_source_bootstrap_joins.source_producers=external<0>();mp4_source_bootstrap_joins.provisional_roots=external<1>();mp4_source_bootstrap_joins.physical_cohort=external<2>();mp4_source_bootstrap_joins.initial_commit=initial_commit;mp4_source_bootstrap_joins.before_part_release=before_part_release;}
size_t event(const std::string&v){auto at=std::find(events.begin(),events.end(),v);assert(at!=events.end());return size_t(at-events.begin());}
int main(int argc,char**argv){assert(argc==2);const std::string mode=argv[1];bind();
 if(mode=="render_hold_wait")render_acquire_ready=false;
 if(mode=="render_retire_reentry")render_retire_reentry=true;
 if(mode=="srp_capture_refuses")srp_capture_ready=false;
 if(mode=="srp_restore_wait"){srp_mutated=true;srp_restore_ready=false;}
 if(mode=="srp_release_wait")srp_mutated=true;
 if(mode=="missing_producer")mp4_source_bootstrap_joins.source_producers={};
 if(mode=="before_wait"||mode=="outer_abort")before_wait=true;
 if(mode=="before_throw")throw_before=true;
 if(mode=="missing_commit")mp4_source_bootstrap_joins.initial_commit=nullptr;
 if(mode=="commit_refuses")initial_ready=false;
 if(mode=="cohort_refuses")cohort_ready=false;
 if(mode=="source_loss")capture_lost=true;
 if(mode=="commit_source_loss")commit_lost=true;
 if(mode=="cleanup_wait"){before_wait=true;release_wait=true;}
 if(mode=="transferred_release_wait")release_wait=true;
 if(mode=="missing_handoff")mp4_source_bootstrap_joins.before_part_release=nullptr;
 if(mode=="handoff_wait")promotion_wait=true;
 if(mode=="handoff_reentry")promotion_reentry=true;
 if(mode=="release_reentry")release_reentry=true;
 auto result=mode=="outer_abort"?mp4_scene_quiesce(nullptr):mp4_scene_source_bootstrap_quiesce();
 if(mode=="render_hold_wait"){assert(result==Mp4SceneResult::waiting&&mp4_early_source_gates.active&&!mp4_render_hold_state.active&&baseline_calls==0&&logical_calls==0&&part_models[0].quiet==0);render_acquire_ready=true;result=mp4_scene_source_bootstrap_quiesce();assert(render_acquires==2);}
 if(mode=="outer_abort"){
  assert(result==Mp4SceneResult::waiting&&mp4_early_source_gates.active&&mp4_scene_source_bootstrap.scope.active());
  source_current=false;mp4_scene_host.invalidated=true;observed_loss=true;
  assert(mp4_scene_quiesce(nullptr)==Mp4SceneResult::stale&&mp4_early_source_gates.active);
  assert(mp4_scene_release(nullptr,false)==Mp4SceneResult::ok&&!mp4_early_source_gates.active&&!mp4_scene_host.active&&late_source_reads==0);
  return 0;
 }
 if(mode=="srp_capture_refuses"){assert(result!=Mp4SceneResult::ok&&baseline_calls==0&&logical_calls==0&&!mp4_early_source_gates.active);return 0;}
 if(mode=="missing_producer"){assert(result==Mp4SceneResult::unsupported&&mp4_early_source_gates.acquires==0&&baseline_calls==0&&logical_calls==0&&commit_calls==0);return 0;}
 if(mode=="before_wait"||mode=="cleanup_wait"){
  assert(result==Mp4SceneResult::waiting&&configure_calls==1&&baseline_calls==1&&logical_calls==1&&readonly_calls==0&&mp4_early_source_gates.current());
  if(mode=="cleanup_wait"){source_current=false;observed_loss=true;result=mp4_scene_source_bootstrap_quiesce();assert(result==Mp4SceneResult::waiting&&mp4_early_source_gates.active&&recipes[1].held&&mp4_scene_source_bootstrap.scope.draining());
   result=mp4_scene_source_bootstrap_quiesce();assert(result!=Mp4SceneResult::ok&&!mp4_early_source_gates.active&&mp4_scene_source_bootstrap.scope.clean());return 0;}
  result=mp4_scene_source_bootstrap_quiesce();assert(configure_calls==1&&baseline_calls==1&&logical_calls==1&&part_models[0].quiet==1);
 }
 if(mode=="before_throw"||mode=="missing_commit"||mode=="commit_refuses"||mode=="cohort_refuses"||mode=="source_loss"||mode=="commit_source_loss"){
  assert(result!=Mp4SceneResult::ok&&!mp4_scene_source_bootstrap.scope.transferred()&&!mp4_early_source_gates.active);
  assert(!mp4_root_history_initial_sealed(1));if(mode=="before_throw")assert(cohort_calls==0&&readonly_calls==0);
  if(mode=="source_loss"||mode=="commit_source_loss")assert(late_source_reads==0);
  if(mode=="source_loss")assert(cohort_calls==0&&commit_calls==0&&!mp4_child_readonly_source.finalized);
  return 0;
 }
 assert(result==Mp4SceneResult::ok&&mp4_scene_source_bootstrap.scope.transferred()&&mp4_root_history_initial_sealed(1));
 assert(event("gate")<event("quiet0")&&event("quiet2")<event("external0")&&event("baseline")<event("logical")&&event("logical")<event("external1")&&event("external1")<event("readonly")&&event("readonly")<event("world")&&event("world")<event("capture0")&&event("capture3")<event("external2")&&event("external2")<event("finalize")&&event("finalize")<event("commit"));
 assert(cohort_calls==1&&commit_calls==1);
 assert(event("external0")<event("srp")&&event("srp")<event("baseline"));
 if(mode=="srp_current_lost"){
  srp_current_ready=false;auto&h=mp4_scene_source_bootstrap;const auto i=static_cast<size_t>(mp4sb::Phase::source_baselines);
  assert(!mp4_scene_bootstrap_current(&h,h.key,h.receipt[i],i));srp_current_ready=true;
 }
 if(mode=="srp_restore_wait"){
  assert(mp4_scene_source_bootstrap_before_part_release(true)==Mp4SceneResult::waiting&&srp_captured&&!srp_restored);
  for(const auto&p:part_models){assert(p.release==0);}
  assert(promotion_calls==0);srp_restore_ready=true;
 }

 if(mode=="property_restore_reentry"||mode=="video_handoff_reentry"||mode=="playback_handoff_reentry"){
  const auto count=events.size();if(mode=="property_restore_reentry")mp4_scene_property_restore_entered=1;if(mode=="video_handoff_reentry")mp4_scene_video_handoff_entered=1;if(mode=="playback_handoff_reentry")mp4_scene_host.playback_handoff_running=true;
  assert(mp4_scene_release(nullptr,true)==Mp4SceneResult::waiting&&events.size()==count&&!mp4_scene_host.releasing&&mp4_scene_source_bootstrap.scope.transferred());mp4_scene_property_restore_entered=mp4_scene_video_handoff_entered=0;mp4_scene_host.playback_handoff_running=false;
 }
 if(mode=="foreign_release"){
  const auto seen=events.size();owner=false;
  assert(mp4_scene_source_bootstrap_quiesce()==Mp4SceneResult::waiting);
  assert(mp4_scene_source_bootstrap_before_part_release(true)==Mp4SceneResult::waiting);
  assert(mp4_scene_source_bootstrap_release()==Mp4SceneResult::waiting);
  assert(events.size()==seen&&catalogue_clears==0&&mp4_early_source_gates.active);
  owner=true;
 }
 if(mode=="idempotent"){assert(mp4_scene_source_bootstrap_quiesce()==Mp4SceneResult::ok&&commit_calls==1&&part_models[0].capture==1);return 0;}
 if(mode=="missing_handoff"){
  assert(mp4_scene_source_bootstrap_before_part_release(true)==Mp4SceneResult::unsupported&&mp4_early_source_gates.active);
  assert(mp4_scene_source_bootstrap_release()==Mp4SceneResult::waiting);for(const auto&p:part_models)assert(p.release==0);return 0;
 }
 if(mode=="handoff_wait"){
  assert(mp4_scene_source_bootstrap_before_part_release(true)==Mp4SceneResult::waiting&&mp4_early_source_gates.active);
  for(const auto&p:part_models)assert(p.release==0);
 }
 assert(mp4_scene_source_bootstrap_before_part_release(true)==Mp4SceneResult::ok);
 assert(mp4_scene_source_bootstrap_before_part_release(true)==Mp4SceneResult::ok&&promotion_calls==(promotion_wait?2:1));
 assert(mp4_scene_bootstrap_parts_release()==Mp4SceneResult::ok);
 if(mode=="srp_release_wait"){
  assert(srp_restored&&srp_restore_calls==1);srp_release_ready=false;srp_restore_ready=false;
  assert(mp4_scene_source_bootstrap_release()==Mp4SceneResult::waiting&&srp_captured&&mp4_early_source_gates.active);
  assert(srp_restore_calls==1);srp_release_ready=true;
 }

 if(mode=="transferred_release_wait"){
  assert(mp4_scene_source_bootstrap_release()==Mp4SceneResult::waiting&&mp4_early_source_gates.active&&mp4_scene_source_bootstrap.retiring);
  assert(catalogue_clears==0);
  assert(release_calls[2]==1&&release_calls[1]==1&&mp4_child_readonly_source.serial==0);
  assert(mp4_scene_source_bootstrap_quiesce()==Mp4SceneResult::waiting);
 }
 if(mode=="render_checkpoint_wait"){render_checkpoint_ready=false;assert(mp4_scene_source_bootstrap_release()==Mp4SceneResult::waiting&&mp4_render_hold_state.active&&catalogue_clears==0&&render_retires==0);render_checkpoint_ready=true;}
 if(mode=="render_retire_wait"){render_retire_ready=false;assert(mp4_scene_source_bootstrap_release()==Mp4SceneResult::waiting&&mp4_render_hold_state.active&&catalogue_clears==0&&render_retires==1);render_retire_ready=true;}
 if(mode=="render_retire_source_changed"){source_current=false;observed_loss=true;}
 assert(mp4_scene_source_bootstrap_release()==Mp4SceneResult::ok&&!mp4_early_source_gates.active&&!mp4_scene_source_bootstrap.scope.transferred()&&!mp4_root_history_initial_sealed(1));
 assert(!mp4_render_hold_state.active&&render_retires==(mode=="render_retire_wait"?2:1));if(mode=="render_retire_source_changed")assert(late_source_reads==0);
 assert(event("render-acquire")<event("quiet0")&&event("ungate")<event("render-checkpoint")&&event("render-retire")<event("catalogue"));
 assert(release_calls[2]==1&&release_calls[0]==1);
 assert(catalogue_clears==1&&event("catalogue")>event("ungate")&&event("catalogue")>event("xrelease2"));
 assert(event("xwithdraw0")<event("xrelease2")&&event("xwithdraw1")<event("xrelease2"));
 assert(event("promote")<event("release0"));
 if(mode=="srp_restore_wait"||mode=="srp_release_wait")assert(event("srp-restore")<event("promote"));
 assert(event("unbaseline")<event("unsrp")&&event("unsrp")<event("ungate"));
 assert(event("release0")<event("ungate")&&event("xrelease2")<event("ungate"));
 if(mode=="reuse"){
  ++idoly_mp4_runtime::job.generation;mp4_scene_host.released=mp4_scene_host.captured=0;
  for(auto&p:part_models){p.capture=0;}
  mp4_world_host.scope.owned=false;mp4_world_host.animation_owned=false;full_child=false;
  assert(mp4_scene_source_bootstrap_quiesce()==Mp4SceneResult::ok&&commit_calls==2&&mp4_root_history_initial_sealed(1));
 }
}
