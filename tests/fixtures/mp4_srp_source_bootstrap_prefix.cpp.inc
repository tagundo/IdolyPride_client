#include <cstdint>
#include <cstddef>
#include <cstring>
#include <cassert>
#include <atomic>
#include <stdexcept>
#include <string>
namespace mp4sb{enum class Phase:size_t{source_configure,early_barrier,source_baselines};struct Key{uint64_t epoch=0,job=0;uintptr_t source=0,root_asset=0;};bool same(const Key&a,const Key&b){return a.epoch==b.epoch&&a.job==b.job&&a.source==b.source&&a.root_asset==b.root_asset;}}
struct Mp4SceneWitness{uint64_t generation=7;void*player=reinterpret_cast<void*>(10),*controller=reinterpret_cast<void*>(11),*camera=reinterpret_cast<void*>(12);};
bool mp4_scene_same_source(const Mp4SceneWitness&a,const Mp4SceneWitness&b){return a.generation==b.generation&&a.player==b.player&&a.controller==b.controller&&a.camera==b.camera;}
namespace idoly_mp4_runtime{struct{uint64_t generation=9;}job;}
struct{Mp4SceneWitness source{};void*root_asset=reinterpret_cast<void*>(13);bool active=true,invalidated=false,releasing=false;}mp4_scene_host;
bool main_thread=true,source_current=true,clock_held=true,camera_active=true,intercepted=true,early_current=true,worker_current=true;
bool game_call(){return main_thread;}bool mp4_scene_source_current(){return source_current;}bool mp4_actor_clock_held(void*){return clock_held;}
struct{struct{bool active()const{return camera_active;}}scope;}mp4_camera_host;bool mp4_camera_interception_published(){return intercepted;}
struct{unsigned depth=0;}mp4_raw_original_operation;struct{bool active=false;}mp4_rebuild_ledger;
struct{mp4sb::Key key{7,9,10,13};uint64_t receipt[3]{1,2,0},producer_receipt=77;}mp4_scene_source_bootstrap;
struct{bool current()const{return early_current;}}mp4_early_source_gates;
bool workers(void*context,const mp4sb::Key&key,uint64_t receipt){assert(context==reinterpret_cast<void*>(1));return worker_current&&mp4sb::same(key,mp4_scene_source_bootstrap.key)&&receipt==77;}
struct{void*context=reinterpret_cast<void*>(1);struct{bool(*current)(void*,const mp4sb::Key&,uint64_t)=workers;}source_producers;}mp4_source_bootstrap_joins;
unsigned restore_calls=0;bool restore_ok=true,readers_idle=true;
namespace mp4srp{constexpr size_t max_capacity=8;struct Image{void*controller=nullptr,*camera=nullptr,*queue=nullptr,*array=nullptr;size_t count=0,capacity=0;uint32_t version=0;bool first=true;void*items[max_capacity]{},*subscribers[8]{};};struct Lease{bool present=false,poison=false,opened=false;bool captured()const{return present;}bool poisoned()const{return poison;}bool open()const{return opened;}bool restore(){++restore_calls;if(!restore_ok)poison=true;return !poison;}};}
struct Mp4SrpControllerHost{Mp4SceneWitness source{};void*context=nullptr;bool(*held_fenced)(void*)=nullptr;bool(*entered_original)(void*)=nullptr;mp4srp::Lease lease;};
struct Mp4SrpDispatchHost{Mp4SrpControllerHost*state=nullptr;bool mutated=false,unknown_mutation=false;};
std::atomic<Mp4SrpDispatchHost*>mp4_srp_dispatch_published{nullptr},mp4_srp_observer_owner{nullptr};std::atomic<bool>mp4_srp_observer_armed{false};
struct Mp4SrpEntered{Mp4SrpDispatchHost*host=nullptr;void*controller=nullptr;bool accepted=false,calling_original=false;Mp4SrpEntered*previous=nullptr;};Mp4SrpEntered*mp4_srp_entered=nullptr;std::atomic<bool>mp4_srp_dispatch_foreign_dirty{false};
mp4srp::Image state_image{};unsigned capture_calls=0,read_calls=0,clear_calls=0,late_calls=0,root_calls=0;bool capture_ok=true,read_ok=true,capture_throws=false,clear_ok=true,late_ok=false;
bool mp4_srp_observer_idle(){return readers_idle;}
bool mp4_srp_state_current(void*,void*,void*){return source_current;}
bool mp4_renderer_srp_source_callbacks_closed(const Mp4SceneWitness&){return source_current;}
bool mp4_srp_state_read(Mp4SrpControllerHost*,mp4srp::Image&out){++read_calls;out=state_image;return read_ok;}
bool mp4_srp_dispatch_capture(Mp4SrpDispatchHost&dispatch,Mp4SrpControllerHost&state,const Mp4SceneWitness&source,void*context,uint64_t epoch,uint64_t job,bool(*current)(void*,uint64_t,uint64_t),bool(*fenced)(void*),bool(*)(void*,void*,void*,uintptr_t,uint64_t*),bool(*loop_held)(void*),mp4srp::Image*initial=nullptr){
 ++capture_calls;assert(current(context,epoch,job)&&fenced(context)&&loop_held(context));if(capture_throws)throw std::runtime_error("capture");
 if(!capture_ok||!read_ok)return false;if(initial)*initial=state_image;state.source=source;state.lease.present=true;dispatch.state=&state;mp4_srp_dispatch_published.store(&dispatch,std::memory_order_release);mp4_srp_observer_owner.store(&dispatch,std::memory_order_release);mp4_srp_observer_armed.store(true,std::memory_order_release);return true;
}
void mp4_srp_dispatch_withdraw(Mp4SrpDispatchHost&dispatch){if(mp4_srp_dispatch_published.load(std::memory_order_acquire)==&dispatch)mp4_srp_dispatch_published.store(nullptr,std::memory_order_release);}
bool mp4_srp_dispatch_clear(Mp4SrpDispatchHost&dispatch){++clear_calls;if(!clear_ok)return false;mp4_srp_dispatch_withdraw(dispatch);if(dispatch.state)dispatch.state->lease={};dispatch={};mp4_srp_observer_owner.store(nullptr,std::memory_order_release);mp4_srp_observer_armed.store(false,std::memory_order_release);return true;}
