"""Execute the shipping fresh Play/Reset hooks and their source certificates.

Managed roots, factory request, MethodInfo/caller memory and Unity originals are
explicit host leaves. This proves the extracted hook protocol, not a game run.
The complete Replay/request wrapper is exercised in test_mp4_fresh_protocol.
"""
from pathlib import Path
import shutil
import subprocess

import pytest
from test_mp4_native_boundary import definition


ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "client-presentation/native/bridge.cpp"


FIXTURE = r'''
#include <atomic>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <map>
#include <stdexcept>
#include <string>
#include <vector>
namespace idoly_mp4_replay { // SHIPPING_UNITASK_ABI
}
using Method=const void;struct MethodInfo {uintptr_t entry=0;};using VoidMethod=void(*)(void*,Method*);
namespace pin{struct Entry{uintptr_t rva;};constexpr Entry mp4_timeline_play{0x100},mp4_reset_actor_model{0x200},mp4_director_play{0x300};}
namespace mp4game{struct Layout{size_t player_director_controller=1,camera_main=2,controller_master=3,controller_directors=4,photo_root_mode=5,photo_mode_player=6,presenter_player=7;};struct PlayableGraph{uint64_t handle=0;};struct Binding{uintptr_t rva;uint8_t prefix[16];};}
enum class Mp4FreshResult{ok,waiting,stale,unsupported,failed};
struct Object{bool alive=true,playing=true,paused=false;int mode=0,state=1;std::map<size_t,void*>fields;};
Object player,presenter,timeline,camera,controller,master,child,list,foreign,end_task_source,photo_mode;
std::vector<void*>directors{&child};std::map<uint32_t,void*>roots;uint32_t next_root=1;
bool unity_thread=true,request_valid=true,held=false,graph_ready=false,throw_play=false,throw_reset=false;
bool photo_source=true,end_fails=false;int end_status=0;unsigned end_calls=0,end_consumes=0,ended_observers=0;
bool memory_cell_mapped=true,memory_method_mapped=true,backend_good=true;
bool continuation_prefix=true,scheduler_prefix=true,caller_mapped=true;unsigned mp4_fresh_injected_reset_depth=0;uint64_t caller_instruction=0xd63f0120u;
unsigned original_plays=0,original_timeline_plays=0,original_resets=0,scheduled_resets=0,events=0,photo_observations=0;const char*last_error="none";
uintptr_t image_base=0x10000000;MethodInfo method{image_base+pin::mp4_reset_actor_model.rva},wrong_method{method.entry};Method*cell_method=&method;
#ifdef IDOLY_DARWIN_BRIDGE
constexpr uintptr_t reset_return=0x75dad28,reset_continuation=0x75dab3c;
constexpr uintptr_t photo_return=0x6fdf5bc,photo_scheduler=0x6fdf4cc,base_return=0x6feede4,base_scheduler=0x6feed60;
constexpr uint64_t photo_branch=0x942fa313,base_branch=0x9422b840;
#else
constexpr uintptr_t reset_return=0x8d76594,reset_continuation=0x8d763a4;
constexpr uintptr_t photo_return=0x88804a8,photo_scheduler=0x88803c8,base_return=0x888dec4,base_scheduler=0x888de44;
constexpr uint64_t photo_branch=0x9426ea0a,base_branch=0x941c94ae;
#endif
uintptr_t fixture_caller=image_base+reset_return;
mp4game::Binding mp4_fresh_origin_pause_pin{};
bool mp4_prefix(const mp4game::Binding&binding){return (continuation_prefix&&binding.rva==reset_continuation)||(scheduler_prefix&&(binding.rva==photo_scheduler||binding.rva==base_scheduler))||binding.rva==mp4_fresh_origin_pause_pin.rva;}
bool game_call(){return unity_thread;}bool mp4_source_verified=true;std::atomic<bool>ready{true};
namespace idoly_mp4_runtime{
struct FreshFactoryRequest{uint64_t serial=0,identity=0;void*player=nullptr;};
FreshFactoryRequest request{7,12,&::player};
void*selected_player_value=&::player,*selected_presenter_value=&::presenter;uint64_t selected_identity=12;
struct Game{void*selected_player(){return selected_player_value;}void*selected_presenter(){return selected_presenter_value;}}game;
struct Selection{uint64_t identity(void*p){return p==&::player?selected_identity:0;}}selection;
bool fresh_factory_request(void*p,FreshFactoryRequest*out){if(out)*out={};if(!request_valid||p!=&::player||!out)return false;*out=request;return true;}
bool fresh_factory_request_scope(FreshFactoryRequest*out){if(out)*out={};if(!request_valid||!out)return false;*out=request;return true;}
struct Clock{bool held(){return ::held;}}clock;Clock&native_clock_scope(){return clock;}
void diagnostic_event(const char*,const char*){++events;}
void observe_presenter(void*p){assert(p==&::presenter);selected_presenter_value=p;}
void observe_presenter_ended(void*p){assert(p==&::presenter);++ended_observers;selected_player_value=selected_presenter_value=nullptr;}
}
bool mp4_actor_field(void*object,size_t offset,void*&value){auto&o=*static_cast<Object*>(object);auto it=o.fields.find(offset);if(it==o.fields.end())return false;value=it->second;return true;}
bool mp4_actor_list(void*object,void***values,size_t*count,size_t max){if(object!=&list||directors.size()>max)return false;*values=directors.data();*count=directors.size();return true;}
bool mp4_alive(void*object){return object&&static_cast<Object*>(object)->alive;}
bool mp4_type_is(void*object,const char*type){if(object==&presenter)return !std::strcmp(type,photo_source?"Solis.Photography.PhotographyLivePresenter":"Solis.OutGame.LivePlayerScreenPresenter");return (object==&master||object==&child)&&!std::strcmp(type,"UnityEngine.Playables.PlayableDirector");}
struct PhotoWeak{void*get(bool){return photo_source?&presenter:nullptr;}}mp4_photography_presenter;
void mp4_observe_photography_presenter(){++photo_observations;}
void*mp4_selected_controller(void*p){return p==&presenter?&controller:nullptr;}
uint32_t mp4_retain(void*object){const auto id=next_root++;roots[id]=object;return id;}
void*weak_get(uint32_t id){auto it=roots.find(id);return it==roots.end()?nullptr:it->second;}
void weak_free(uint32_t id){assert(roots.erase(id)==1);}
struct Mp4ActorTempRoot{uint32_t root;explicit Mp4ActorTempRoot(void*p):root(mp4_retain(p)){}~Mp4ActorTempRoot(){weak_free(root);}void*get(){return weak_get(root);}};
template<class T>struct ScopedValue{T&slot;T old;ScopedValue(T&slot,T value):slot(slot),old(slot){slot=value;}~ScopedValue(){slot=old;}};
bool mp4_mapped(uintptr_t at,size_t size,bool executable){
 if(at==image_base+reset_return-4&&size==4&&executable)return caller_mapped;
 if((at==image_base+photo_return-4||at==image_base+base_return-4)&&size==4&&executable)return true;
 if(size!=8||executable)return false;
#ifdef IDOLY_DARWIN_BRIDGE
 if(at==image_base+0xa4712a8)return memory_cell_mapped;
#else
 if(at==image_base+0x99d37a8)return memory_cell_mapped;
#endif
 return (at==reinterpret_cast<uintptr_t>(&method)||at==reinterpret_cast<uintptr_t>(&wrong_method))&&memory_method_mapped;
}
template<class T>T read(void*p,size_t offset){assert(!offset);T value{};
#ifdef IDOLY_DARWIN_BRIDGE
 constexpr uintptr_t cell=0xa4712a8;
#else
 constexpr uintptr_t cell=0x99d37a8;
#endif
 if(reinterpret_cast<uintptr_t>(p)==image_base+photo_return-4)std::memcpy(&value,&photo_branch,sizeof value);
 else if(reinterpret_cast<uintptr_t>(p)==image_base+base_return-4)std::memcpy(&value,&base_branch,sizeof value);
 else if(reinterpret_cast<uintptr_t>(p)==image_base+reset_return-4)std::memcpy(&value,&caller_instruction,sizeof value);
 else if(reinterpret_cast<uintptr_t>(p)==image_base+cell)std::memcpy(&value,&cell_method,sizeof value);
 else std::memcpy(&value,p,sizeof value);return value;
}
bool source_playing(void*p,Method*){return static_cast<Object*>(p)->playing;}bool source_paused(void*p,Method*){return static_cast<Object*>(p)->paused;}
void set_playing(void*p,bool value,Method*){static_cast<Object*>(p)->playing=value;}int32_t source_state(void*p,Method*){return static_cast<Object*>(p)->state;}
struct Api{double(*director_get_duration)(void*,Method*);int32_t(*director_get_mode)(void*,Method*);void(*director_set_mode)(void*,int32_t,Method*);
 void(*director_graph_injected)(void*,mp4game::PlayableGraph*,Method*);bool(*graph_valid)(mp4game::PlayableGraph*,Method*);
 struct{bool(*player_playing)(void*,Method*)=source_playing;bool(*player_paused)(void*,Method*)=source_paused;void(*player_set_playing)(void*,bool,Method*)=set_playing;int32_t(*director_state)(void*,Method*)=source_state;}automatic_playback;
}mp4_api;
double duration(void*p,Method*){assert(p==&master);return 1.;}int32_t get_mode(void*p,Method*){return static_cast<Object*>(p)->mode;}
void set_mode(void*p,int32_t mode,Method*){assert(held&&mode==1);static_cast<Object*>(p)->mode=mode;}
void get_graph(void*p,mp4game::PlayableGraph*g,Method*){assert(p==&master);g->handle=graph_ready?1:0;}
bool valid_graph(mp4game::PlayableGraph*g,Method*){return g->handle==1&&graph_ready;}
struct FreshHost{bool active=false;struct{void*player=&::player;}source;const char*error="none";}mp4_fresh_host;
std::atomic<bool>mp4_fresh_withdrawn{false};
using Mp4FreshOriginResult=Mp4FreshResult;uint64_t mp4_fresh_terminal_identity=0;
struct Origin{struct{
 idoly_mp4_replay::UniTask16(*presenter_end)(void*,idoly_mp4_replay::CancellationToken8,Method*)=nullptr;
 int32_t(*task_status)(idoly_mp4_replay::UniTask16*,Method*)=nullptr;
 idoly_mp4_replay::UniTask16(*task_get_awaiter)(idoly_mp4_replay::UniTask16*,Method*)=nullptr;
 void(*task_get_result)(idoly_mp4_replay::UniTask16*,Method*)=nullptr;
 void*(*scene_instance)(Method*)=nullptr;void*(*top_screen)(void*,Method*)=nullptr;
}original_api;}origin;
Origin&mp4_fresh_origin_state(){return origin;}
void photo_end(void*p,Method*){assert(p==&presenter&&held);++end_calls;if(!end_fails){player.playing=false;master.state=0;}}
VoidMethod mp4_photography_end_original=photo_end;
void pause_original(void*p,Method*){assert(p==&player&&held&&mp4_fresh_injected_reset_depth);master.state=0;player.paused=true;}
idoly_mp4_replay::UniTask16 presenter_end(void*p,idoly_mp4_replay::CancellationToken8 token,Method*){assert(p==&presenter&&!token.source&&held&&!player.playing);++end_calls;return {&end_task_source,42};}
int32_t task_status(idoly_mp4_replay::UniTask16*t,Method*){assert(t->source==&end_task_source&&t->token_and_padding==42);return end_status;}
idoly_mp4_replay::UniTask16 task_awaiter(idoly_mp4_replay::UniTask16*t,Method*){assert(end_status==1);return *t;}
void task_result(idoly_mp4_replay::UniTask16*t,Method*){assert(t->source==&end_task_source&&end_status==1);++end_consumes;}
Mp4FreshResult mp4_fresh_fail(Mp4FreshResult result,const char*error){last_error=error;return result;}
void mp4_director_play_hook(void*,Method*);
void play_original(void*self,Method*given){assert(self==&master||self==&child||self==&foreign);++original_plays;if(throw_play)throw std::runtime_error("original Play");if(self==&master&&held)assert(master.mode==1&&child.mode==3);(void)given;}
void timeline_original(void*self,Method*given){
 assert(self==&timeline);++original_timeline_plays;player.playing=true;
 // A host forward need not preserve the original tail-call LR. The shipping
 // Photo wrapper must carry its exact source caller through scoped TLS.
 ScopedValue<uintptr_t> caller(fixture_caller,photo_source?image_base+0xdead:fixture_caller);
 mp4_director_play_hook(&master,given);++scheduled_resets;
}
void reset_original(void*,Method*){++original_resets;if(throw_reset)throw std::runtime_error("original ResetActorModel");}
namespace mp4_bootstrap{struct Install{uintptr_t target=0;};struct EventPin{};EventPin ios_fresh_video_event_pins[9];}
struct Mp4ManagedHookReceipt{uintptr_t rva=0,base=0;void*replacement=nullptr;void**original_location=nullptr;void*trampoline=nullptr,*stub=nullptr;};
constexpr size_t mp4_managed_hook_capacity=4;Mp4ManagedHookReceipt mp4_managed_hook_receipts[4];std::atomic<size_t>mp4_managed_hook_count{3};
struct Backend{bool receipt(size_t,uintptr_t target,uintptr_t hook,uintptr_t original,uintptr_t stub,mp4_bootstrap::Install*out){
 if(!backend_good||!out)return false;for(size_t i=0;i<3;++i){auto&r=mp4_managed_hook_receipts[i];if(target==image_base+r.rva&&hook==reinterpret_cast<uintptr_t>(r.replacement)&&original==reinterpret_cast<uintptr_t>(r.trampoline)&&stub==reinterpret_cast<uintptr_t>(r.stub)){out->target=target;return true;}}return false;
}}mp4_managed_source_backend;
bool mp4_fresh_video_static_event_current(const pin::Entry&e,const mp4_bootstrap::EventPin&,uintptr_t hook,uintptr_t original){
 if(!backend_good)return false;for(size_t i=0;i<3;++i){auto&r=mp4_managed_hook_receipts[i];if(r.rva==e.rva&&r.base==image_base&&reinterpret_cast<uintptr_t>(r.replacement)==hook&&reinterpret_cast<uintptr_t>(r.trampoline)==original&&r.stub)return true;}return false;
}
#define __builtin_return_address(depth) reinterpret_cast<void*>(fixture_caller)
// SHIPPING_FRONTEND
#undef __builtin_return_address
// SHIPPING_STAGE
// SHIPPING_NO_ORIGIN
void source_play(Method*given){
 ScopedValue<uintptr_t> caller(fixture_caller,image_base+(photo_source?photo_return:base_return));
 if(photo_source)mp4_timeline_play_hook(&timeline,given);else timeline_original(&timeline,given);
}
int main(int argc,char**argv){
 assert(argc==2);std::string scenario=argv[1];const bool cleanup_outgame=scenario.rfind("cleanup_",0)==0&&scenario.size()>8&&scenario.compare(scenario.size()-8,8,"_outgame")==0;
 if(cleanup_outgame)scenario.resize(scenario.size()-8);
 photo_source=!cleanup_outgame&&scenario!="end_outgame"&&scenario!="outgame_base_forward"&&scenario!="selected_clear_preplay_outgame"&&scenario!="reset_outgame_valid";
 player.fields[1]=&timeline;controller.fields[2]=&camera;timeline.fields[3]=&master;timeline.fields[4]=&list;master.mode=0;child.mode=3;
 presenter.fields[5]=&photo_mode;photo_mode.fields[6]=&player;presenter.fields[7]=&player;
 mp4_api.director_get_duration=duration;mp4_api.director_get_mode=get_mode;mp4_api.director_set_mode=set_mode;mp4_api.director_graph_injected=get_graph;mp4_api.graph_valid=valid_graph;
 mp4_timeline_play_original=timeline_original;mp4_director_play_original=play_original;mp4_reset_actor_model_original=reset_original;
 origin.original_api.presenter_end=presenter_end;origin.original_api.task_status=task_status;origin.original_api.task_get_awaiter=task_awaiter;origin.original_api.task_get_result=task_result;
 origin.original_api.scene_instance=[](Method*)->void*{return &foreign;};origin.original_api.top_screen=[](void*p,Method*)->void*{assert(p==&foreign);return &presenter;};
 mp4_fresh_origin_pause_pin.rva=reinterpret_cast<uintptr_t>(pause_original)-image_base;
 const pin::Entry*entries[]={&pin::mp4_timeline_play,&pin::mp4_reset_actor_model,&pin::mp4_director_play};
 const uintptr_t hooks[]={reinterpret_cast<uintptr_t>(mp4_timeline_play_hook),reinterpret_cast<uintptr_t>(mp4_reset_actor_model_hook),reinterpret_cast<uintptr_t>(mp4_director_play_hook)};
 void**slots[]={reinterpret_cast<void**>(&mp4_timeline_play_original),reinterpret_cast<void**>(&mp4_reset_actor_model_original),reinterpret_cast<void**>(&mp4_director_play_original)};
 for(size_t i=0;i<3;++i)mp4_managed_hook_receipts[i]={entries[i]->rva,image_base,reinterpret_cast<void*>(hooks[i]),slots[i],*slots[i],reinterpret_cast<void*>(i+1)};
 assert(mp4_fresh_play_frontends_ready());
 if(scenario.rfind("certificate_",0)==0){
  if(scenario=="certificate_source")mp4_source_verified=false;
  else if(scenario=="certificate_ready")ready=false;
  else if(scenario=="certificate_backend")backend_good=false;
  else if(scenario=="certificate_base")++mp4_managed_hook_receipts[0].base;
  else if(scenario=="certificate_hook")mp4_managed_hook_receipts[0].replacement=nullptr;
  else if(scenario=="certificate_original")mp4_timeline_play_original=reset_original;
  else if(scenario=="certificate_stub")mp4_managed_hook_receipts[0].stub=nullptr;
  else if(scenario=="certificate_master_hook")mp4_managed_hook_receipts[2].replacement=nullptr;
  else if(scenario=="certificate_master_original")mp4_director_play_original=reset_original;
  else if(scenario=="certificate_master_stub")mp4_managed_hook_receipts[2].stub=nullptr;
#ifndef IDOLY_DARWIN_BRIDGE
  else if(scenario=="certificate_slot")mp4_managed_hook_receipts[0].original_location=nullptr;
  else if(scenario=="certificate_duplicate"){mp4_managed_hook_receipts[3]=mp4_managed_hook_receipts[0];mp4_managed_hook_count=4;}
#endif
  else assert(false);assert(!mp4_fresh_play_frontends_ready());return 0;
 }
 if(scenario=="ordinary"){mp4_director_play_hook(&master,&method);assert(original_plays==1&&roots.empty()&&!mp4_fresh_play_gate.deferred);return 0;}
 if(scenario=="ordinary_timeline"){mp4_timeline_play_hook(&timeline,&method);assert(original_timeline_plays==1&&original_plays==1&&roots.empty()&&!mp4_fresh_play_gate.deferred);return 0;}
 mp4_fresh_play_gate.armed=true;
 if(scenario=="no_request"){request_valid=false;mp4_director_play_hook(&master,&method);assert(original_plays==1&&roots.empty());return 0;}
 if(scenario=="foreign_director"){mp4_director_play_hook(&child,&method);assert(original_plays==1&&roots.empty());return 0;}
 if(scenario=="late_play_cleanup"){
  assert(mp4_fresh_stop_disposable()==Mp4FreshResult::waiting&&!mp4_fresh_play_gate.ending&&roots.empty()&&!end_calls);
 }
 if(scenario=="unknown_first"){
  mp4_director_play_hook(&master,&method);held=true;
  assert(mp4_fresh_play_gate.failed&&mp4_fresh_withdrawn&&mp4_fresh_play_gate.await_scheduler);
  assert(!scheduled_resets&&!mp4_fresh_play_gate.reset_requests&&!mp4_fresh_play_gate.reset_required&&!original_plays);
  assert(mp4_fresh_stop_disposable()==Mp4FreshResult::waiting&&!end_calls&&!mp4_fresh_play_gate.ending);
  source_play(&method);assert(scheduled_resets==1&&mp4_fresh_play_gate.reset_requests==1&&!mp4_fresh_play_gate.await_scheduler);
  assert(mp4_fresh_stop_disposable()==Mp4FreshResult::waiting&&!end_calls);
  mp4_reset_actor_model_hook(&player,&method);--scheduled_resets;
  assert(mp4_fresh_play_gate.reset_returned&&mp4_fresh_play_gate.reset_returns==1);
  assert(mp4_fresh_stop_disposable()==Mp4FreshResult::ok&&end_calls==1&&!original_plays);
  mp4_fresh_play_gate_clear();assert(roots.empty());return 0;
 }
 if(scenario.rfind("selected_clear_preplay",0)==0)idoly_mp4_runtime::selected_player_value=idoly_mp4_runtime::selected_presenter_value=nullptr;
 if(scenario=="timeline_forward"||scenario=="outgame_base_forward"){player.playing=false;source_play(&method);assert(player.playing&&original_timeline_plays==1);}
 else source_play(&method);
 assert(original_plays==0&&roots.size()==6&&mp4_fresh_play_gate.deferred&&mp4_fresh_play_gate_current()&&mp4_fresh_play_gate.reset_required);
 assert(mp4_fresh_staged_camera(&camera)&&!mp4_fresh_staged_camera(&foreign));mp4_fresh_host.active=true;assert(!mp4_fresh_staged_camera(&camera));mp4_fresh_host.active=false;
 if(scenario.rfind("cleanup_",0)==0){
  held=true;assert(scheduled_resets==1&&mp4_fresh_play_gate.reset_requests==1&&!original_plays);
  const bool unknown=scenario=="cleanup_unknown_complete"||scenario=="cleanup_unknown_pending"||scenario=="cleanup_mixed";
  if(scenario=="cleanup_unknown_complete"){
   mp4_reset_actor_model_hook(&player,&method);--scheduled_resets;
   assert(mp4_fresh_play_gate.reset_returns==1&&mp4_fresh_play_gate.reset_returned);
  }
  if(unknown)mp4_director_play_hook(&master,&method); // No original caller schedules a Reset.
  if(scenario=="cleanup_two_known"||scenario=="cleanup_three_known"||scenario=="cleanup_mixed")source_play(&method);
  if(scenario=="cleanup_three_known")source_play(&method);
  const uint64_t expected=original_timeline_plays;
  assert(mp4_fresh_play_gate.failed&&mp4_fresh_withdrawn&&!mp4_fresh_play_gate_current()&&!original_plays);
  assert(mp4_fresh_play_gate.reset_requests==expected&&scheduled_resets==expected-original_resets);
  // Clearing the UI selection must not revoke custody of callbacks already
  // scheduled by the actual original callers whose bodies returned.
  idoly_mp4_runtime::selected_player_value=idoly_mp4_runtime::selected_presenter_value=nullptr;
  while(scheduled_resets){
   assert(mp4_fresh_stop_disposable()==Mp4FreshResult::waiting&&!end_calls&&!mp4_fresh_play_gate.ending&&roots.size()==6);
   mp4_reset_actor_model_hook(&player,&method);--scheduled_resets;
   assert(mp4_fresh_play_gate.reset_returns==original_resets);
   assert(mp4_fresh_play_gate.reset_returned==(scheduled_resets==0));
  }
  assert(mp4_fresh_stop_disposable()==Mp4FreshResult::ok&&end_calls==1&&mp4_fresh_play_gate.ending);
  assert(original_resets==expected&&!original_plays&&mp4_fresh_play_gate.failed);
 }else if(scenario.rfind("end_",0)==0||scenario=="late_play_cleanup"){
  held=true;graph_ready=true;
  assert(mp4_fresh_release_deferred_play()==Mp4FreshResult::ok&&original_plays==1);
  if(scenario=="end_wait_reset"){
   const auto before=events;
   for(int i=0;i<3;++i)assert(mp4_fresh_stop_disposable()==Mp4FreshResult::waiting&&!mp4_fresh_play_gate.ending&&!end_calls);
   assert(mp4_fresh_play_gate.reset_cleanup_wait&&events==before+1&&roots.size()==6&&!original_resets);
  }
  mp4_reset_actor_model_hook(&player,&method);assert(original_resets==1&&mp4_fresh_play_gate.reset_returned);
  if(scenario=="end_unheld"){held=false;assert(mp4_fresh_stop_disposable()==Mp4FreshResult::failed&&!end_calls);}
  else{
   end_fails=scenario=="end_failed";if(scenario=="end_selected_clear")idoly_mp4_runtime::selected_player_value=idoly_mp4_runtime::selected_presenter_value=nullptr;
   if(scenario=="end_wrong_binding")photo_mode.fields[6]=&foreign;
   const auto stopped=mp4_fresh_stop_disposable();
   if(scenario=="end_wrong_binding")assert(stopped==Mp4FreshResult::stale&&!end_calls&&!ended_observers);
   else if(end_fails){assert(end_calls==1&&stopped==Mp4FreshResult::failed&&mp4_fresh_play_gate.stop_failed&&!ended_observers);assert(mp4_fresh_stop_disposable()==Mp4FreshResult::failed&&end_calls==1);}
   else{
    assert(end_calls==1&&stopped==Mp4FreshResult::ok&&!player.playing&&master.state==0&&ended_observers==1&&mp4_fresh_terminal_identity==12);
    // The original End/Pause happened under the held export clock. Its
    // returned task can now settle under ordinary loader time exactly once.
    held=false;
    if(!photo_source){assert(roots.size()==7&&mp4_fresh_no_origin_settled()==Mp4FreshResult::waiting&&!end_consumes);end_status=1;}
    assert(mp4_fresh_no_origin_settled()==Mp4FreshResult::ok&&mp4_fresh_no_origin_settled()==Mp4FreshResult::ok);
    assert(end_calls==1&&end_consumes==unsigned(!photo_source)&&roots.size()==6);
    assert(mp4_fresh_no_mv_origin_candidate());
    idoly_mp4_runtime::selected_player_value=&player;idoly_mp4_runtime::selected_presenter_value=&presenter;
    player.playing=true;player.paused=true;assert(mp4_fresh_no_mv_origin_candidate());
    ++idoly_mp4_runtime::selected_identity;assert(!mp4_fresh_no_mv_origin_candidate());
    player.playing=player.paused=false;assert(mp4_fresh_no_mv_origin_candidate());
   }
  }
 }else if(scenario=="duplicate_play"){
  mp4_director_play_hook(&master,&method);assert(mp4_fresh_play_gate.failed&&mp4_fresh_withdrawn&&!original_plays&&roots.size()==6);
  assert(!std::strcmp(mp4_fresh_host.error,"fresh_duplicate_play_request"));
 }else if(scenario=="changed_request"){
  ++idoly_mp4_runtime::request.serial;mp4_director_play_hook(&master,&method);assert(mp4_fresh_play_gate.failed&&!mp4_fresh_play_gate_current()&&!original_plays);
 }else if(scenario=="changed_master"){
  timeline.fields[3]=&child;assert(!mp4_fresh_play_gate_current()&&mp4_fresh_release_deferred_play()==Mp4FreshResult::stale&&!original_plays);
 }else if(scenario.rfind("reset_",0)==0){
  void*self=&player;Method*given=&method;
  if(scenario=="reset_cell")cell_method=&wrong_method;
  else if(scenario=="reset_method")method.entry++;
  else if(scenario=="reset_cell_unmapped")memory_cell_mapped=false;
  else if(scenario=="reset_method_unmapped")memory_method_mapped=false;
  else if(scenario=="reset_receiver")self=&foreign;
  else if(scenario=="reset_wrong_method")given=&wrong_method;
  else if(scenario=="reset_caller")++fixture_caller;
  else if(scenario=="reset_caller_unmapped")caller_mapped=false;
  else if(scenario=="reset_instruction")caller_instruction=0xd63f0100u;
  else if(scenario=="reset_continuation")continuation_prefix=false;
  else if(scenario=="reset_injected")mp4_fresh_injected_reset_depth=1;
  else if(scenario=="reset_throw")throw_reset=true;
  else assert(scenario=="reset_valid"||scenario=="reset_outgame_valid");
  try{mp4_reset_actor_model_hook(self,given);assert(!throw_reset);}catch(const std::runtime_error&){assert(throw_reset);}
  const bool valid=scenario=="reset_valid"||scenario=="reset_outgame_valid";
  assert(original_resets==1&&mp4_fresh_play_gate.reset_returned==valid);
  if(valid){mp4_reset_actor_model_hook(self,given);assert(original_resets==2&&mp4_fresh_play_gate.reset_returned);}
 }else{
  assert(mp4_fresh_release_deferred_play()==Mp4FreshResult::stale&&!original_plays);held=true;
  if(scenario=="unsupported_mode"){master.mode=2;assert(mp4_fresh_release_deferred_play()==Mp4FreshResult::unsupported&&!original_plays);}
  else if(scenario=="play_throw"){
   throw_play=true;try{(void)mp4_fresh_release_deferred_play();assert(false);}catch(const std::runtime_error&){}
   assert(original_plays==1&&mp4_fresh_play_gate.forward_started&&!mp4_fresh_play_gate.forwarded);
   assert(mp4_fresh_release_deferred_play()==Mp4FreshResult::failed&&original_plays==1);
  }else{
   assert((scenario=="release_wait"||scenario=="timeline_forward"||scenario=="outgame_base_forward"||scenario.rfind("selected_clear_preplay",0)==0)&&mp4_fresh_release_deferred_play()==Mp4FreshResult::waiting&&original_plays==1);
   assert(mp4_fresh_release_deferred_play()==Mp4FreshResult::waiting&&original_plays==1);
   graph_ready=true;assert(mp4_fresh_release_deferred_play()==Mp4FreshResult::ok&&original_plays==1);
   assert(master.mode==1&&child.mode==3);
  }
 }
 mp4_fresh_play_gate_clear();assert(roots.empty()&&!mp4_fresh_play_gate.deferred&&!mp4_fresh_staged_camera(&camera));
}
'''


def marker(source, name):
    return source.split(f"// BEGIN_{name}", 1)[1].split(f"// END_{name}", 1)[0]


@pytest.fixture(scope="module")
def play_staging_binaries(tmp_path_factory):
    compiler = shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        pytest.skip("C++ compiler required")
    shipping = BRIDGE.read_text()
    body = FIXTURE.replace("// SHIPPING_FRONTEND", marker(shipping, "MP4_FRESH_PLAY_FRONTEND"))
    replay_header = (ROOT / "client-presentation/native/mp4_replay.hpp").read_text()
    abi = ";\n".join(definition(replay_header, name) for name in ("struct UniTask16 {", "struct CancellationToken8 {")) + ";"
    body = body.replace("// SHIPPING_UNITASK_ABI", abi)
    body = body.replace("// SHIPPING_NO_ORIGIN", marker(shipping, "MP4_FRESH_NO_ORIGIN_HOST"))
    binaries = {}
    for platform in ("android", "ios"):
        directory = tmp_path_factory.mktemp(f"fresh-play-{platform}")
        source, binary = directory / "play.cpp", directory / "play"
        source.write_text(body.replace("// SHIPPING_STAGE", marker(shipping, "MP4_FRESH_PLAY_STAGE")))
        flags = ["-DIDOLY_DARWIN_BRIDGE"] if platform == "ios" else []
        result = subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                                 "-Wno-misleading-indentation", "-I", str(ROOT / "client-presentation/native"),
                                 *flags, str(source), "-o", str(binary)],
                                capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
        binaries[platform] = binary
    return binaries


@pytest.mark.parametrize("scenario", [
    "ordinary", "ordinary_timeline", "no_request", "foreign_director", "unknown_first", "duplicate_play", "changed_request", "changed_master", "release_wait", "unsupported_mode", "play_throw",
    "timeline_forward", "outgame_base_forward", "selected_clear_preplay_photo", "selected_clear_preplay_outgame",
    "cleanup_two_known", "cleanup_three_known", "cleanup_unknown_complete", "cleanup_unknown_pending", "cleanup_mixed",
    "cleanup_two_known_outgame", "cleanup_three_known_outgame", "cleanup_unknown_complete_outgame", "cleanup_unknown_pending_outgame", "cleanup_mixed_outgame",
    "reset_valid", "reset_outgame_valid", "reset_cell", "reset_method", "reset_cell_unmapped", "reset_method_unmapped", "reset_receiver", "reset_wrong_method", "reset_throw",
    "reset_caller", "reset_caller_unmapped", "reset_instruction", "reset_continuation", "reset_injected",
    "end_photo", "end_outgame", "end_unheld", "end_failed", "end_selected_clear", "end_wrong_binding", "end_wait_reset", "late_play_cleanup",
    "certificate_source", "certificate_ready", "certificate_backend", "certificate_base", "certificate_hook", "certificate_original", "certificate_stub",
    "certificate_master_hook", "certificate_master_original", "certificate_master_stub",
])
@pytest.mark.parametrize("platform", ["android", "ios"])
def test_shipping_fresh_play_staging_and_real_reset_methodinfo_gate(play_staging_binaries, scenario, platform):
    binary = play_staging_binaries[platform]
    result = subprocess.run([str(binary), scenario], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("scenario", ["certificate_slot", "certificate_duplicate"])
def test_shipping_android_play_install_receipt_rejects_stale_or_duplicate_hook(play_staging_binaries, scenario):
    result = subprocess.run([str(play_staging_binaries["android"]), scenario], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr


def test_shipping_original_end_preparation_is_joined_before_clock_release():
    bridge = BRIDGE.read_text()
    prepare = definition(bridge, "Mp4FreshResult mp4_fresh_prepare_finish(void*)")
    assert prepare.index("mp4_fresh_stop_disposable()") < prepare.index("h.pre_release_done=true")
    assert "if(stopped==Mp4FreshResult::waiting)return stopped" in prepare
    runtime = (ROOT / "client-presentation/native/mp4_runtime.hpp").read_text()
    boundary = definition(runtime, "inline bool native_fresh_render_boundary_impl(void*manager,double wall)")
    assert boundary.index("api.prepare_finish(api.context)") < boundary.index("game.end_fresh()") < boundary.index("clock.restore(manager,wall,false)")
    cleanup = boundary[boundary.index("api.prepare_finish(api.context)"):boundary.index("game.end_fresh()")]
    assert "if(prepared==Result::waiting)return native_boundary_clock_tick(manager,wall)" in cleanup
