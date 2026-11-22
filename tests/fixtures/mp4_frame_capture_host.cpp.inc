#include <cstdint>
#include <cstdio>
#include <cassert>
#include <cstring>
#include <vector>
#include <map>
#include <string>
#include <atomic>
using Method=void;
namespace idoly_mp4_game{enum class Result:int{ok=0,waiting=1,unsupported=-1,invalid=-2,failed=-3,stale=-4};}
enum class Mp4SceneResult:int{ok=0,waiting=1,unsupported=-1,invalid=-2,failed=-3,stale=-4};
namespace mp4frame{using Result=Mp4SceneResult;}
// REAL_PRODUCTION_BANK
namespace mp4production=idoly_mp4_capture_production;
struct Obj{alignas(16)uint8_t data[256]{};const char*type;};Obj controller{},camera{},old_target{},old_rt{},old_capture{},old_capture_rt{},new_target{},new_rt{},private_wrapper{},private_rt{},name{};
void*ref(Obj&o){return o.data;}std::map<void*,Obj*>objects;std::map<uint32_t,void*>roots;uint32_t next_root=0;bool thread_ok=true,current_ok=true,jobs_ok=true,program_ok=true,gpu_ok=true,consumers_ok=true,owner_retired=false,alias_ok=true,frontend_ok=true,native_quiet=true,fail_root=false;unsigned old_reads=0;uint64_t origin_serial=0;
template<class T>void put(Obj&o,size_t at,T x){std::memcpy(o.data+at,&x,sizeof x);}
template<class T>bool mp4_actor_field(void*p,size_t at,T&out){if(p==ref(controller)){assert(current_ok);++old_reads;}auto i=objects.find(p);if(i==objects.end()||at+sizeof out>sizeof i->second->data)return false;std::memcpy(&out,i->second->data+at,sizeof out);return true;}
bool game_call(){return thread_ok;}bool mp4_actor_refresh_maps(){return true;}bool mp4_alive(void*p){return objects.count(p);}
bool mp4_exact_type(void*p,const char*t){return objects.count(p)&&!std::strcmp(objects[p]->type,t);}
uint32_t mp4_retain(void*p){if(!p||fail_root)return 0;roots[++next_root]=p;return next_root;}void*weak_get(uint32_t h){return roots.count(h)?roots[h]:nullptr;}void weak_free(uint32_t h){assert(roots.erase(h)==1);}
struct Mp4ActorTempRoot{uint32_t root;explicit Mp4ActorTempRoot(void*p):root(mp4_retain(p)){}~Mp4ActorTempRoot(){if(root)weak_free(root);}void*get()const{return weak_get(root);}};
struct Mp4SceneWitness{uint64_t generation=0;void*controller=nullptr,*camera=nullptr;};
bool mp4_scene_same_source(const Mp4SceneWitness&a,const Mp4SceneWitness&b){return a.generation==b.generation&&a.controller==b.controller&&a.camera==b.camera;}
struct{bool active=true,invalidated=false,releasing=false;unsigned configured=15,all=15;Mp4SceneWitness source{};}mp4_scene_host;
bool mp4_scene_source_current(){return current_ok;}
namespace idoly_mp4_runtime{
struct{uint64_t generation=9;}job;struct Clock{bool held(){return jobs_ok;}}clock;Clock&native_clock_scope(){return clock;}
struct Game{uint64_t capture_request_origin_serial(void*){return origin_serial;}bool install_capture_operations(idoly_mp4_game::Result(*b)(void*,uint64_t*),bool(*e)(void*,uint64_t,bool)){return b&&e;}}game;
}
struct Mp4CaptureProductionHost;
struct ScopeModel{
 void*context=nullptr;bool(*held)(void*)=nullptr;bool(*produced)(void*,uint64_t,uint64_t,void*,void*,uintptr_t)=nullptr;bool(*unreferenced)(void*,void*,void*,uintptr_t)=nullptr;bool(*preserve)(void*,void*)=nullptr;
 bool captured=false,detached=false,restored=false,released_flag=true,abandoned=false;void*original=nullptr,*output=nullptr;
 Mp4SceneResult prepare(){if(!held(context))return Mp4SceneResult::waiting;put(controller,160,static_cast<void*>(nullptr));detached=true;return Mp4SceneResult::ok;}
 bool ready(){return captured&&detached&&!restored;}
 Mp4SceneResult observe_export_capture(void*w){void*t=nullptr;uintptr_t n=0;if(!mp4_actor_field(w,16,t)||!mp4_actor_field(t,16,n)||!produced(context,7,9,w,t,n))return Mp4SceneResult::stale;output=w;return Mp4SceneResult::ok;}
 Mp4SceneResult restore(){if(!held(context))return Mp4SceneResult::waiting;put(controller,160,original);detached=false;restored=true;return Mp4SceneResult::ok;}
 Mp4SceneResult verify_held(){return restored&&held(context)?Mp4SceneResult::ok:Mp4SceneResult::stale;}
 void abandon(){abandoned=true;}
 Mp4SceneResult release(){if(abandoned&&detached&&original&&!preserve(context,original))return Mp4SceneResult::waiting;
  if(output){void*t=nullptr;uintptr_t n=0;assert(mp4_actor_field(output,16,t)&&mp4_actor_field(t,16,n));if(!unreferenced(context,output,t,n)){if(!abandoned||!preserve(context,output))return Mp4SceneResult::waiting;}else put(private_rt,16,uintptr_t(0));}
  released_flag=true;captured=false;return Mp4SceneResult::ok;}
 bool released(){return released_flag;}
};
struct Mp4PausedImageHost{ScopeModel scope;void*original_capture=nullptr;bool configured=false;};
struct Mp4CaptureProductionHost{mp4production::Bank bank;Mp4SceneWitness source{};uint64_t job=0,publication_request=0;void*target=nullptr,*target_texture=nullptr;uintptr_t target_native=0;void*retirement=nullptr;bool(*adopt)(void*,const mp4production::Resource&)=nullptr;bool configured=false,publication_configured=false;};
struct Mp4CaptureQueueHost{bool bound=false;};
struct Mp4CaptureAliasHost{bool bound=false;void*context=nullptr;bool(*unwound)(void*,uint64_t,uint64_t)=nullptr;bool(*gpu)(void*,uint64_t,uint64_t)=nullptr;bool(*allocation)(void*,uint64_t,uint64_t,void*,void*,uintptr_t,bool*)=nullptr;bool(*detach)(void*,uint64_t,uint64_t,void*,void*,uintptr_t)=nullptr;bool(*consumers)(void*,uint64_t,uint64_t,void*,void*,uintptr_t)=nullptr;};
uint64_t mp4_capture_queue_readers=0,mp4_capture_native_write_serial=0;unsigned mp4_owned_render_depth=0,mp4_unowned_render_depth=0;
struct{bool configured=false;uint64_t source=7,epoch=9;bool draw=false;uint64_t sequence=1,retired=1;}mp4_gpu_fence_host,mp4_gpu_auxiliary_host;
bool hold_checkpoint=true;unsigned paused_finish_calls=0;
bool mp4_render_hold_gpu_checkpoint(uint64_t job){assert(job==9);return hold_checkpoint;}
bool mp4_gpu_final_fenced(uint64_t){return gpu_ok;}Mp4SceneResult mp4_gpu_preflight(uint64_t,uint64_t){return gpu_ok?Mp4SceneResult::ok:Mp4SceneResult::waiting;}
bool mp4_capture_native_quiescent(){return native_quiet;}bool mp4_capture_native_frontend_current(){return frontend_ok;}bool mp4_capture_native_property(int32_t*out){*out=57;return frontend_ok;}bool mp4_capture_frontends_current(uintptr_t*out){*out=11;return frontend_ok;}bool mp4_capture_queue_frontends_current(){return frontend_ok;}
mp4frame::Result mp4_paused_image_capture(Mp4PausedImageHost&h,const Mp4SceneWitness&,uint64_t,void*context,bool(*held)(void*),bool(*produced)(void*,uint64_t,uint64_t,void*,void*,uintptr_t),bool(*unref)(void*,void*,void*,uintptr_t),bool(*preserve)(void*,void*)){
 h.configured=true;if(!held(context))return Mp4SceneResult::waiting;h.original_capture=ref(old_capture);h.scope.context=context;h.scope.held=held;h.scope.produced=produced;h.scope.unreferenced=unref;h.scope.preserve=preserve;h.scope.captured=true;h.scope.released_flag=false;h.scope.original=ref(old_capture);return Mp4SceneResult::ok;}
bool mp4_paused_image_finish(Mp4PausedImageHost&h,bool done){++paused_finish_calls;if(!done||!h.scope.released())return false;h.configured=false;return true;}
bool mp4_capture_production_wrapper_texture(void*w,void**out){return mp4_actor_field(w,16,*out);}
bool prod_current(void*context,uint64_t e,uint64_t j){auto&h=*static_cast<Mp4CaptureProductionHost*>(context);void*t=nullptr;return current_ok&&e==7&&j==9&&mp4_actor_field(ref(controller),152,t)&&t==h.target;}
bool prod_owned(void*,void*c,uint64_t s){return c==ref(controller)&&s&&s==origin_serial;}
bool prod_descriptor(void*,const mp4production::Descriptor&d){return d.fields[0]==64&&d.fields[1]==64;}
bool prod_name(void*,void*n){return n==ref(name);}
bool prod_capture(void*,void*,void**w,void**t){return mp4_actor_field(ref(controller),160,*w)&&(!*w||mp4_actor_field(*w,16,*t));}
bool prod_native(void*t,uintptr_t*out){return mp4_actor_field(t,16,*out);}
bool mp4_capture_production_bind(Mp4CaptureProductionHost&h,const Mp4SceneWitness&s,uint64_t job,void*sink,bool(*adopt)(void*,const mp4production::Resource&),bool,uintptr_t){h.source=s;h.job=job;h.retirement=sink;h.adopt=adopt;h.configured=true;assert(mp4_actor_field(s.controller,152,h.target)&&mp4_actor_field(h.target,16,h.target_texture));
 const mp4production::Api a{game_call,prod_current,prod_current,prod_owned,prod_owned,prod_descriptor,prod_name,prod_capture,mp4_capture_production_wrapper_texture,prod_native,mp4_retain,weak_get,weak_free};return h.bank.bind(a,&h,s.controller,7,9,11,12,13);}
bool mp4_capture_queue_bind(Mp4CaptureQueueHost&h,Mp4CaptureProductionHost&,void*,bool(*)(void*,uint64_t,uint64_t,void*,void*,uintptr_t,bool*),bool){h.bound=true;return true;}
bool mp4_capture_alias_bind(Mp4CaptureAliasHost&h,const Mp4SceneWitness&,uint64_t,void*ctx,bool(*unwound)(void*,uint64_t,uint64_t),bool(*gpu)(void*,uint64_t,uint64_t),bool(*allocation)(void*,uint64_t,uint64_t,void*,void*,uintptr_t,bool*),Mp4CaptureQueueHost&,bool(*detach)(void*,uint64_t,uint64_t,void*,void*,uintptr_t),bool(*consumers)(void*,uint64_t,uint64_t,void*,void*,uintptr_t)){
 h.context=ctx;h.unwound=unwound;h.gpu=gpu;h.allocation=allocation;h.detach=detach;h.consumers=consumers;h.bound=true;return true;}
bool mp4_capture_production_publication_bind(Mp4CaptureProductionHost&h,int32_t,void*ctx,bool(*program)(void*,uint64_t,uint64_t),bool){h.publication_configured=program(ctx,7,9);return h.publication_configured;}
bool mp4_capture_production_produced(void*context,uint64_t e,uint64_t j,void*w,void*t,uintptr_t n){auto&h=*static_cast<Mp4CaptureProductionHost*>(context);mp4production::Resource r{};return e==7&&j==9&&h.bank.produced(w,t,&r)&&r.native==n;}
bool mp4_capture_production_issue(Mp4CaptureProductionHost&h,void*,uint64_t){return prod_current(&h,7,9)&&h.bank.can_prepare();}
bool mp4_capture_publication_completed(Mp4CaptureProductionHost&,uint64_t){return current_ok;}
bool mp4_capture_production_descriptor(Mp4CaptureProductionHost*,const mp4production::Descriptor&d){return prod_descriptor(nullptr,d);}
bool mp4_capture_production_transfer_all(Mp4CaptureProductionHost&h){for(uint32_t i=0;i<h.bank.count();++i)if(!h.bank.transferred(i)&&!h.bank.transfer(i,h.retirement,h.adopt))return false;return true;}
bool mp4_capture_production_finish(Mp4CaptureProductionHost&h){if(!h.bank.finish())return false;h.configured=false;return true;}
bool mp4_capture_alias_unreferenced(void*context,void*w,void*t,uintptr_t n){auto&h=*static_cast<Mp4CaptureAliasHost*>(context);bool queued=false;return alias_ok&&h.bound&&h.unwound(h.context,7,9)&&h.gpu(h.context,7,9)&&h.allocation(h.context,7,9,w,t,n,&queued)&&h.detach(h.context,7,9,w,t,n)&&h.consumers(h.context,7,9,w,t,n);}
bool mp4_capture_alias_release(Mp4CaptureAliasHost&h){h.bound=false;return true;}bool mp4_capture_queue_finish(Mp4CaptureQueueHost&h){h.bound=false;return true;}
int32_t rt_width(void*,Method*){return 64;}int32_t rt_height(void*,Method*){return 64;}
void destroy(void*t,bool,Method*){assert(t==ref(private_rt));put(private_rt,16,uintptr_t(0));}
uintptr_t image_base=0;struct{struct{uintptr_t rva=reinterpret_cast<uintptr_t>(destroy);}object_destroy_immediate;}mp4_cam_profile;
template<class T,class B>T mp4_cam_call(const B&b){return reinterpret_cast<T>(b.rva);}
// ACTUAL_JOIN
bool jobs(void*,const Mp4SceneWitness&,uint64_t){return jobs_ok;}bool program(void*,const Mp4SceneWitness&,uint64_t,void*w,void*t,uintptr_t n){return program_ok&&w==ref(old_capture)&&t==ref(old_capture_rt)&&n==101;}
bool retired(void*,uint64_t,uint64_t){return gpu_ok;}bool consumers(void*,uint64_t,uint64_t,void*,void*,uintptr_t){return consumers_ok;}bool detached(void*,uint64_t,uint64_t,void*,void*,uintptr_t){return owner_retired;}
Mp4FrameCaptureCoordinator api(){return{&program_ok,jobs,program,retired,consumers,detached};}
void setup(){objects.clear();for(auto pair:{std::pair<Obj*,const char*>{&controller,"VL.Rendering.VLSRPCameraController"},{&camera,"UnityEngine.Camera"},{&old_target,"VL.VLRenderTexture"},{&old_rt,"UnityEngine.RenderTexture"},{&old_capture,"VL.VLRenderTexture"},{&old_capture_rt,"UnityEngine.RenderTexture"},{&new_target,"VL.VLRenderTexture"},{&new_rt,"UnityEngine.RenderTexture"},{&private_wrapper,"VL.VLRenderTexture"},{&private_rt,"UnityEngine.RenderTexture"},{&name,"System.String"}}){std::memset(pair.first->data,0,256);pair.first->type=pair.second;objects[ref(*pair.first)]=pair.first;}
 roots.clear();next_root=old_reads=0;hold_checkpoint=true;paused_finish_calls=0;thread_ok=current_ok=jobs_ok=program_ok=gpu_ok=consumers_ok=alias_ok=frontend_ok=native_quiet=true;owner_retired=fail_root=false;origin_serial=0;mp4_capture_native_write_serial=mp4_capture_queue_readers=0;mp4_owned_render_depth=mp4_unowned_render_depth=0;mp4_gpu_fence_host.configured=mp4_gpu_auxiliary_host.configured=false;
 mp4_frame_capture_host=Mp4FrameCaptureHost{};for(auto&r:mp4_frame_capture_custody)r={};mp4_scene_host.active=true;mp4_scene_host.invalidated=mp4_scene_host.releasing=false;mp4_scene_host.configured=mp4_scene_host.all=15;mp4_scene_host.source={7,ref(controller),ref(camera)};
 put(controller,80,ref(camera));put(controller,152,ref(old_target));put(controller,160,ref(old_capture));put(old_target,16,ref(old_rt));put(old_capture,16,ref(old_capture_rt));put(old_capture_rt,16,uintptr_t(101));put(old_rt,16,uintptr_t(102));put(new_target,16,ref(new_rt));put(new_rt,16,uintptr_t(103));}
void ready(){auto&h=mp4_frame_capture_host;assert(mp4_frame_capture_baseline(h,mp4_scene_host.source,9,api())==Mp4SceneResult::ok);assert(mp4_frame_capture_prepare(h)==Mp4SceneResult::ok);put(controller,152,ref(new_target));assert(mp4_frame_capture_bind_production(h)==Mp4SceneResult::ok&&h.production.target==ref(new_target));}
void produce(uint64_t operation,bool partial=false){auto&h=mp4_frame_capture_host;origin_serial=operation;auto u=h.production.bank.update(ref(controller),operation,11);assert(u.owned());mp4production::Descriptor d{};d.fields[0]=d.fields[1]=64;{auto w=h.production.bank.wrapper(ref(private_wrapper),&d,ref(name),12);assert(w.owned());{auto t=h.production.bank.texture(ref(private_rt),&d,13);assert(t.owned());put(private_rt,16,uintptr_t(202));assert(t.finish(!partial));}if(!partial)put(private_wrapper,16,ref(private_rt));assert(w.finish(!partial));}if(!partial)put(controller,160,ref(private_wrapper));assert(u.finish(!partial));}
void clean(bool owned=true){auto&h=mp4_frame_capture_host;origin_serial=0;assert(mp4_frame_capture_seal(h));if(owned){put(controller,152,ref(old_target));assert(mp4_frame_capture_restore(h)==Mp4SceneResult::ok);}assert(mp4_frame_capture_release(h,owned)==Mp4SceneResult::ok);assert(mp4_frame_capture_finish(h,true));put(private_rt,16,uintptr_t(0));put(old_capture_rt,16,uintptr_t(0));mp4_frame_capture_collect_natural();assert(roots.empty());}
int main(){unsigned cases=0;
 {setup();ready();uint64_t op=0;assert(mp4_frame_capture_begin(ref(controller),&op)==Mp4SceneResult::ok&&op);produce(op);assert(mp4_frame_capture_end(ref(controller),op,true));origin_serial=0;clean();++cases;}
 {setup();auto a=api();a.source_jobs_held=nullptr;assert(mp4_frame_capture_baseline(mp4_frame_capture_host,mp4_scene_host.source,9,a)==Mp4SceneResult::invalid&&!mp4_frame_capture_host.active);++cases;}
 {setup();ready();mp4_gpu_auxiliary_host.configured=true;mp4_gpu_auxiliary_host.sequence=2;mp4_gpu_auxiliary_host.retired=1;assert(mp4_frame_capture_held(&mp4_frame_capture_host));mp4_gpu_auxiliary_host.configured=false;clean();++cases;}
 {setup();ready();jobs_ok=false;uint64_t op=1;assert(mp4_frame_capture_begin(ref(controller),&op)==Mp4SceneResult::stale&&!op);jobs_ok=true;clean();++cases;}
 {setup();ready();program_ok=false;uint64_t op=1;assert(mp4_frame_capture_begin(ref(controller),&op)==Mp4SceneResult::unsupported&&!op);program_ok=true;clean();++cases;}
 {setup();ready();++mp4_capture_native_write_serial;uint64_t op=1;assert(mp4_frame_capture_begin(ref(controller),&op)==Mp4SceneResult::unsupported&&!op);clean();++cases;}
 {setup();ready();gpu_ok=false;uint64_t op=1;assert(mp4_frame_capture_begin(ref(controller),&op)==Mp4SceneResult::waiting&&!op);gpu_ok=true;clean();++cases;}
 {setup();ready();put(controller,160,ref(old_capture));uint64_t op=1;assert(mp4_frame_capture_begin(ref(controller),&op)==Mp4SceneResult::stale&&!op);put(controller,160,static_cast<void*>(nullptr));clean();++cases;}
 {setup();ready();uint64_t op=0;assert(mp4_frame_capture_begin(ref(controller),&op)==Mp4SceneResult::ok);produce(op,true);assert(!mp4_frame_capture_end(ref(controller),op,false));origin_serial=0;clean();++cases;}
 {setup();ready();uint64_t op=0;assert(mp4_frame_capture_begin(ref(controller),&op)==Mp4SceneResult::ok);produce(op);assert(mp4_frame_capture_end(ref(controller),op,true));origin_serial=0;mp4_frame_capture_seal(mp4_frame_capture_host);put(controller,152,ref(old_target));assert(mp4_frame_capture_restore(mp4_frame_capture_host)==Mp4SceneResult::ok);consumers_ok=false;assert(mp4_frame_capture_release(mp4_frame_capture_host,true)==Mp4SceneResult::waiting);consumers_ok=true;assert(mp4_frame_capture_release(mp4_frame_capture_host,true)==Mp4SceneResult::ok);assert(mp4_frame_capture_finish(mp4_frame_capture_host,true)&&roots.empty());++cases;}
 {setup();ready();uint64_t op=0;assert(mp4_frame_capture_begin(ref(controller),&op)==Mp4SceneResult::ok);produce(op);assert(mp4_frame_capture_end(ref(controller),op,true));origin_serial=0;const auto before=old_reads;current_ok=false;clean(false);assert(old_reads==before);++cases;}
 {setup();ready();uint64_t op=0;assert(mp4_frame_capture_begin(ref(controller),&op)==Mp4SceneResult::ok);produce(op);current_ok=false;const auto before=old_reads;assert(!mp4_frame_capture_end(ref(controller),op,false));origin_serial=0;clean(false);assert(old_reads==before);++cases;}
 {setup();ready();mp4_frame_capture_seal(mp4_frame_capture_host);origin_serial=77;assert(mp4_frame_capture_release(mp4_frame_capture_host,false)==Mp4SceneResult::waiting);origin_serial=0;clean();++cases;}
 {setup();ready();auto&h=mp4_frame_capture_host;mp4_frame_capture_seal(h);put(controller,152,ref(old_target));assert(mp4_frame_capture_restore(h)==Mp4SceneResult::ok&&mp4_frame_capture_release(h,true)==Mp4SceneResult::ok);assert(!mp4_frame_capture_finish(h,false)&&h.active);assert(mp4_frame_capture_finish(h,true)&&roots.empty());++cases;}
 {setup();ready();auto&h=mp4_frame_capture_host;assert(mp4_frame_capture_seal(h));put(controller,152,ref(old_target));
  assert(mp4_frame_capture_restore(h)==Mp4SceneResult::ok&&mp4_frame_capture_release(h,true)==Mp4SceneResult::ok);
  const auto source=h.source;const auto held_roots=roots.size();void*context=h.api.context;
  hold_checkpoint=false;assert(!mp4_frame_capture_finish(h,true)&&h.active&&h.job==9&&h.api.context==context
    &&h.source.generation==source.generation&&h.image.configured&&roots.size()==held_roots&&paused_finish_calls==0);
  hold_checkpoint=true;assert(mp4_frame_capture_finish(h,true)&&!h.active&&!h.job&&roots.empty()&&paused_finish_calls==1);++cases;}
 std::printf("%u Frame/Capture join cases; actual Bank and join, physical/GPU leaf calls modeled\n",cases);
}
