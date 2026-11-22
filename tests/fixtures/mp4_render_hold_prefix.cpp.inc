#include <atomic>
#include <cassert>
#include <cstdint>
#include <cstddef>
#include <cstring>
#include <stdexcept>
#include <thread>
#include <iostream>
#include <functional>
using Method=void;using VoidMethod=void(*)(void*,Method*);
struct Mp4RenderContext{void*pointer=nullptr;};
struct Mp4RenderSubmission{Mp4RenderContext context{};uint64_t source_generation=0,job_generation=0,tick=0,draw_token=0;bool prewarm=false;};
enum class Mp4SceneResult:int{ok,waiting,unsupported,stale,invalid,failed};
thread_local bool owner_thread=true,private_time=false,private_rng=false;
bool game_call(){return owner_thread;}
// SHIPPING_CORE
void mp4_render_stack_hook(Mp4RenderContext,void*,Method*);
void mp4_render_camera_hook(Mp4RenderContext,void*,Method*);
namespace mp4game{struct Binding{uint64_t rva=0;uint8_t prefix[16]{};};}
namespace pin{struct Entry{uint64_t rva=0;uint8_t bytes[16]{};};Entry mp4_render_stack{1,{}},mp4_render_camera{2,{}},mp4_camera_manual_render{3,{}};}
bool frontends_ok=true;
bool mp4_hook_was_statically_verified(const mp4game::Binding&b){return frontends_ok&&b.rva>=1&&b.rva<=3;}
bool mp4_capture_static_frontend(const pin::Entry&,uintptr_t,uintptr_t original){return frontends_ok&&original;}
struct Receipt{uintptr_t rva=0;void*stub=nullptr,*trampoline=nullptr;void**original_location=nullptr;};
Receipt mp4_managed_hook_receipts[3];std::atomic<size_t>mp4_managed_hook_count{3};constexpr size_t mp4_managed_hook_capacity=3;
struct Source{uint64_t generation=4;void*player=reinterpret_cast<void*>(0x100),*presenter=reinterpret_cast<void*>(0x101),*camera=reinterpret_cast<void*>(0x200);};
struct{Source source{};unsigned started=15,released=0;bool logical_checkpoint=false,release_owned=true,releasing=false;}mp4_scene_host;
struct Key{uint64_t epoch=4,job=9;};
struct Scope{bool clean_value=false,transferred_value=false,draining_value=false;unsigned started_value=0;bool draining()const{return draining_value;}bool clean()const{return clean_value;}bool transferred()const{return transferred_value;}unsigned started()const{return started_value;}};
struct{Key key{};Scope scope{};bool pre_released=false;unsigned retired=0,withdrawn=0;}mp4_scene_source_bootstrap;
bool key_current=true,early_current=true;bool mp4_scene_bootstrap_key(const Key&k){return key_current&&k.epoch==4&&k.job==9;}
struct{bool current()const{return early_current;}}mp4_early_source_gates;
struct{unsigned depth=0;}mp4_raw_original_operation;struct{bool active=false;}mp4_rebuild_ledger;
struct{bool invalidated=false;const char*error="none";}mp4_camera_host;
struct Mp4SrpRenderKey{uint64_t generation=0,tick=0;bool prewarm=false;};
bool mp4_srp_same_key(const Mp4SrpRenderKey&a,const Mp4SrpRenderKey&b){return a.generation==b.generation&&a.tick==b.tick&&a.prewarm==b.prewarm;}
struct SrpState{Source source;};SrpState srp_state;
struct Srp{uint64_t epoch=4,job=9,frame_receipt=13;SrpState*state=&srp_state;bool have_frame=true,physical_valid=true;uint64_t physical_receipt=14;Mp4SrpRenderKey physical_key{9,7,false};void*physical_context=reinterpret_cast<void*>(0x300);void*native_context=reinterpret_cast<void*>(0x300);Mp4SrpRenderKey last{9,7,false};}srp;
std::atomic<Srp*>mp4_srp_dispatch_published{&srp};bool render_intent=true,srp_draw_receipt=true;
bool mp4_srp_dispatch_intent(const Srp&,Mp4SrpRenderKey&k){k={9,7,false};return render_intent;}
bool mp4_srp_dispatch_draw_receipt(Srp&,uint64_t job,uint64_t tick,bool prewarm,Mp4RenderContext ctx,void*camera,uint64_t draw,uint64_t*out){*out=0;if(!srp_draw_receipt||job!=9||tick!=7||prewarm||ctx.pointer!=srp.native_context||camera!=mp4_scene_host.source.camera||!draw)return false;*out=13;return true;}
struct Ledger{bool configured_value=false,pending=true;bool configured()const{return configured_value;}bool pending_auxiliary(uint64_t job,uint64_t sequence)const{return pending&&job==9&&sequence==1;}};
struct GpuHost{bool configured=false,draw=false;uint64_t source=0,epoch=0,active_token=0,auxiliary_recipe=0,sequence=0,retired=0,last_token=0;Ledger ledger{};}mp4_gpu_fence_host,mp4_gpu_auxiliary_host;
bool graphics_closed=true;bool graphics(uint64_t source,uint64_t job){return graphics_closed&&source==4&&job==9;}
bool(*mp4_gpu_graphics_producers_closed)(uint64_t,uint64_t)=graphics;
Mp4RenderSubmission mp4_owned_render_submission{};bool mp4_owned_render_ticket_active=false,gpu_ticket=true;
bool mp4_gpu_ticket(const Mp4RenderSubmission&s){return gpu_ticket&&s.source_generation==4&&s.job_generation==9&&s.draw_token==17&&s.context.pointer==srp.native_context;}
Mp4RenderCamera mp4_render_stack_original=nullptr,mp4_render_camera_original=nullptr;
struct Frame{bool active=false;Source source{};uint64_t job=9;}mp4_frame_capture_host;
bool frame_gpu_retired=true;int gpu_queries=0;
bool mp4_frame_capture_gpu_retired(void*,uint64_t source,uint64_t job){++gpu_queries;return frame_gpu_retired&&source==4&&job==9;}
namespace idoly_mp4_runtime{struct Work{bool request_active=false,readback_active=false,pending=false;};struct Game{bool primary_started=false;Work work{};Work capture_worker_snapshot()const{return work;}bool primary_playback_mutation_started()const{return primary_started;}}game;}
uint64_t mp4_capture_queue_readers=0;uint8_t mp4_capture_queue_untracked=0;bool native_quiet=true;bool mp4_capture_native_quiescent(){return native_quiet;}
void mp4_owned_render_call(Mp4RenderCamera,Mp4RenderContext,void*,Method*);
void mp4_particle_render_observed(Mp4RenderCamera,Mp4RenderContext,void*,Method*);
// SHIPPING_HOST
// SHIPPING_RETIREMENT
unsigned mp4_owned_render_depth=0,mp4_unowned_render_depth=0;bool callback_idle=true,srp_idle=true,mono_idle=true,actor_slots_idle=true,request_idle=true,bank_idle=true;
bool mp4_source_callbacks_idle(){return callback_idle;}bool mp4_srp_observer_idle(){return srp_idle;}
struct{bool callbacks_unwound()const{return mono_idle;}}mp4_actor_mono_gate;
struct{bool transient_slots_unwound()const{return actor_slots_idle;}}mp4_actor_presentation_scope;
namespace idoly_mp4_capture_publication{struct Request{static bool stack_unwound(){return request_idle;}};}
namespace mp4production{struct Bank{static bool all_scopes_unwound(){return bank_idle;}};}
struct{size_t material_count=0;struct{bool slot_displaced=false;}materials[256];}mp4_equipment_targets;
void*mp4_capture_production_published=nullptr;void*mp4_capture_queue_published=nullptr,*mp4_capture_queue_retiring=nullptr;
// SHIPPING_CONSUMERS
std::atomic<int>automatic_originals{0},manual_originals{0};int owned_attempts=0,suspensions=0,particle_observations=0;bool original_throw=false,nested_auto=false,monitor_allowed=false,manual_nested=false,submit_context=false,direct_monitor=false,bad_frame=false,bad_context=false;
std::function<void()>automatic_action;
void automatic_original(Mp4RenderContext ctx,void*camera,Method*method){++automatic_originals;if(automatic_action)automatic_action();if(nested_auto){nested_auto=false;mp4_render_camera_hook(ctx,reinterpret_cast<void*>(0x222),method);}if(submit_context)mp4_render_hold_context_submit(ctx,true);if(original_throw)throw 7;(void)camera;}
void manual_original(void*camera,Method*method){++manual_originals;if(manual_nested)mp4_render_camera_hook({srp.native_context},camera,method);if(original_throw)throw 8;}
void mp4_particle_render_observed(Mp4RenderCamera original,Mp4RenderContext context,void*camera,Method*method){
 Mp4RenderHoldOriginal hold;if(!hold.enter(original,context,camera)){mp4_camera_host.invalidated=true;mp4_camera_host.error="render_hold_original_unclosed";return;}
 ++particle_observations;struct End{~End(){++particle_observations;}}end;original(context,camera,method);hold.returned();
}
void mp4_owned_render_call(Mp4RenderCamera original,Mp4RenderContext context,void*camera,Method*method){
 ++owned_attempts;
 if(!__atomic_load_n(&mp4_render_hold_state.published,__ATOMIC_SEQ_CST)||!game_call()){mp4_particle_render_observed(original,context,camera,method);return;}
 if(camera!=mp4_scene_host.source.camera){++suspensions;mp4_particle_render_observed(original,context,camera,method);return;}
 private_time=private_rng=true;mp4_owned_render_submission={context,4,9,7,17,false};mp4_owned_render_ticket_active=true;
 struct Exit{~Exit(){private_time=private_rng=false;mp4_owned_render_ticket_active=false;}}exit;
 mp4_particle_render_observed(original,context,camera,method);
}
void mp4_render_stack_hook(Mp4RenderContext context,void*camera,Method*method){mp4_render_hold_automatic(Mp4RenderHoldKind::stack,mp4_render_stack_original,context,camera,method);}
void mp4_render_camera_hook(Mp4RenderContext context,void*camera,Method*method){mp4_render_hold_automatic(Mp4RenderHoldKind::single,mp4_render_camera_original,context,camera,method);}
bool monitor_origin(void*camera,Mp4MonitorCameraOrigin*out){if(!monitor_allowed)return false;*out={4,9,7,61,62,63,reinterpret_cast<void*>(0x111),camera,reinterpret_cast<void*>(0x444),0x555};if(direct_monitor){Mp4RenderHoldFrameOrigin frame{};if(!mp4_render_hold_frame_current(&frame))return false;out->route=Mp4MonitorCameraRoute::urp_direct;out->frame_serial=frame.serial+(bad_frame?1:0);out->context=bad_context?reinterpret_cast<void*>(0x999):frame.context.pointer;}return true;}
void setup(){mp4_render_stack_original=mp4_render_camera_original=automatic_original;mp4_camera_manual_render_original=manual_original;
 mp4_managed_hook_receipts[0]={1,reinterpret_cast<void*>(mp4_render_stack_hook),reinterpret_cast<void*>(automatic_original),reinterpret_cast<void**>(&mp4_render_stack_original)};
 mp4_managed_hook_receipts[1]={2,reinterpret_cast<void*>(mp4_render_camera_hook),reinterpret_cast<void*>(automatic_original),reinterpret_cast<void**>(&mp4_render_camera_original)};
 mp4_managed_hook_receipts[2]={3,reinterpret_cast<void*>(mp4_camera_manual_render_hook),reinterpret_cast<void*>(manual_original),reinterpret_cast<void**>(&mp4_camera_manual_render_original)};
}
void acquire(){assert(mp4_render_hold_acquire(4,9)==Mp4SceneResult::ok);assert(mp4_render_hold_job_quiet(4,9));}
void auto_call(void*camera=nullptr){mp4_render_stack_hook({srp.native_context},camera?camera:mp4_scene_host.source.camera,nullptr);}
void cleanup(){auto&b=mp4_scene_source_bootstrap;mp4_scene_host.released=15;b.scope.clean_value=true;assert(mp4_render_hold_scope_checkpoint(4,9));assert(mp4_render_hold_retire(9)==Mp4SceneResult::ok);}

void aux_setup(){mp4_monitor_camera_render_origin=monitor_origin;monitor_allowed=true;mp4_gpu_auxiliary_host.configured=mp4_gpu_auxiliary_host.draw=true;mp4_gpu_auxiliary_host.source=4;mp4_gpu_auxiliary_host.epoch=9;mp4_gpu_auxiliary_host.active_token=63;mp4_gpu_auxiliary_host.sequence=1;mp4_gpu_auxiliary_host.auxiliary_recipe=(uint64_t(0x4d4f)<<48)|1;}
bool frame_enter(Mp4RenderHoldFrame&frame){return frame.enter(4,9,7,false,{srp.native_context},mp4_scene_host.source.camera);}
