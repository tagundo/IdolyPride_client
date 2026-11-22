#include <atomic>
#include <cassert>
#include <cstdint>
#include <cstddef>
#include <cstring>
#include <cstdlib>
#include <cstdio>
#include <initializer_list>
#include <utility>
enum class Mp4SceneResult{ok,waiting,unsupported,stale};
// This ticket/service fixture models a non-GL backend. The actual GL bootstrap
// owner is independently extracted and executed by test_mp4_gl_bootstrap_host.
Mp4SceneResult mp4_gpu_gl_preflight(uint64_t,uint64_t){return Mp4SceneResult::ok;}
struct Mp4RenderContext{void*pointer=nullptr;};
struct Mp4RenderSubmission{Mp4RenderContext context{};uint64_t source_generation=0,job_generation=0,tick=0,draw_token=0;bool prewarm=false;};
namespace mp4game{struct Binding{uintptr_t rva=0;uint8_t prefix[16]{};};}
namespace mp4_gl_completion {struct Witness {uintptr_t manager=0,device=0,gl_context=0;uint64_t generation=0;uint32_t minimum_serial=0;};enum class Result{ok,waiting};}
std::atomic<bool> mp4_gl_observer_published{false};
bool mp4_gl_hook_receipts(void*){return false;}
namespace mp4_gl_host {struct Observer{mp4_gl_completion::Result witness(mp4_gl_completion::Witness&){return mp4_gl_completion::Result::waiting;}bool completed(const mp4_gl_completion::Witness&,uintptr_t){return false;}}observer;}
struct GlPins{uintptr_t manager_cell=0;};GlPins mp4_gl_source_pins(){return {};}
bool mp4_gl_native_read(void*,uintptr_t,void*,size_t){return false;}
namespace mp4_gpu_fence{
struct Code{uintptr_t rva=0;uint8_t prefix[16]{};};
struct Pins{const char*engine_sha="engine";Code command_type{1,{}},ctor{2,{}},dispose{3,{}},create{4,{}},execute{5,{}},supports{6,{}},submit{7,{}};};
Pins android_gpu_fence_pins,ios_gpu_fence_pins;
bool same_pins(const Pins&a,const Pins&b){return a.command_type.rva==b.command_type.rva;}
struct Context{void*pointer;};
enum class Result{ready,waiting,quarantined};
struct Device {void*device=nullptr;bool gl_completion=false;};
struct Api{bool(*capture_gl_witness)(void*,const Device&,mp4_gl_completion::Witness&)=nullptr;bool(*gl_completed)(void*,const mp4_gl_completion::Witness&,void*)=nullptr;void*context=nullptr;uintptr_t managed_base=0,engine_base=0;bool(*sources)(void*,const Pins&)=nullptr;bool(*owner_thread)(void*)=nullptr;bool(*mapped)(void*,uintptr_t,size_t,bool)=nullptr;bool(*read)(void*,uintptr_t,void*,size_t)=nullptr;void*(*new_command)(void*)=nullptr;uint32_t(*retain)(void*,void*)=nullptr;void*(*target)(void*,uint32_t)=nullptr;void(*release)(void*,uint32_t)=nullptr;};
struct PinnedHost{Api services{};const Pins*pins=nullptr;};
Api pinned_api(PinnedHost&h){return h.services;}
Result poll_fixture=Result::ready;bool begin_fail=false,dispatch_returned=true;int retires=0,submits=0,source_checks=0;
class Ledger{bool configured_=false,active_=false,sealed_=false;uint64_t epoch_=0,sequence_=0,retired_=0;Context context_{};public:
 bool configure(const Api&a,const Pins&p,uint64_t epoch){if(configured_||!a.sources(a.context,p))return false;configured_=true;epoch_=epoch;return true;}
 bool configured()const{return configured_;}
 bool begin_draw(uint64_t epoch,uint64_t sequence,Context context){if(begin_fail){begin_fail=false;return false;}if(!configured_||active_||epoch!=epoch_||sequence!=sequence_+1)return false;active_=true;sequence_=sequence;context_=context;return true;}
 bool pending_context(uint64_t epoch,uint64_t sequence,Context c)const{return active_&&epoch==epoch_&&sequence==sequence_&&c.pointer==context_.pointer;}
 Result submit_returned(uint64_t epoch,uint64_t sequence,Context c){assert(pending_context(epoch,sequence,c));++submits;return poll_fixture;}
 bool last_dispatch_returned(){return dispatch_returned;}
 void submit_failed(uint64_t,uint64_t,Context){poll_fixture=Result::quarantined;}
 bool end_draw(uint64_t epoch,uint64_t sequence){if(!active_||epoch!=epoch_||sequence!=sequence_)return false;active_=false;return poll_fixture!=Result::quarantined;}
 Result poll(uint64_t epoch,uint64_t sequence=0){assert(epoch==epoch_&&(!sequence||sequence==sequence_));return poll_fixture;}
 bool retire_sequence(uint64_t epoch,uint64_t sequence){if(epoch!=epoch_||sequence!=retired_+1)return false;++retires;retired_=sequence;return true;}
 bool draw_fenced(uint64_t epoch,uint64_t sequence){return epoch==epoch_&&sequence==sequence_&&!active_&&poll_fixture==Result::ready;}
 void seal(uint64_t epoch){if(epoch==epoch_)sealed_=true;}
 bool final_fenced(uint64_t epoch){return epoch==epoch_&&sealed_&&!active_&&poll_fixture==Result::ready;}
 void unknown_gpu_work(uint64_t epoch){assert(epoch==epoch_);poll_fixture=Result::quarantined;}
 bool release(uint64_t epoch){if(!final_fenced(epoch))return false;*this=Ledger{};return true;}
};
}
bool on_thread=true,source_verified=true,actor_verified=true,code_verified=true,class_verified=true,producers=true,map_allowed=true;
uintptr_t image_base=0x1000,mp4_native_base=0x2000;
bool&mp4_source_verified=source_verified;bool&mp4_actor_source_verified=actor_verified;
std::atomic<bool>mp4_native_clock_source_ready{true};
struct{const char*native_sha256="engine";}mp4_native_profile;
struct alignas(16) Blob{uint8_t bytes[128]{};}command_class,command,ctor_method,dispose_method,create_method;
bool game_call(){return on_thread;}
bool mp4_prefix(const mp4game::Binding&){return code_verified;}
bool mp4_hook_was_statically_verified(const mp4game::Binding&){return false;}
bool mp4_mapped(uintptr_t,size_t,bool){return map_allowed;}
bool mp4_native_mapped(uintptr_t,size_t,unsigned){return map_allowed;}
bool mp4_actor_mapped(void*,size_t,bool){return map_allowed;}
bool mp4_actor_refresh_maps(){return map_allowed;}
template<class T>void put(void*p,size_t at,T value){std::memcpy(static_cast<uint8_t*>(p)+at,&value,sizeof value);}
template<class T>bool mp4_actor_field(void*p,size_t at,T&value){if(!p||at+sizeof(T)>128)return false;std::memcpy(&value,static_cast<uint8_t*>(p)+at,sizeof value);return true;}
void*font_method_impl(void*k,const char*n,int32_t argc){if(k!=&command_class)return nullptr;if(!std::strcmp(n,".ctor")&&argc==0)return &ctor_method;if(!std::strcmp(n,"Dispose")&&argc==0)return &dispose_method;if(!std::strcmp(n,"CreateGraphicsFence")&&argc==2)return &create_method;return nullptr;}
auto font_method=&font_method_impl;
void*font_new_impl(void*k){return k==&command_class?&command:nullptr;}auto font_new=&font_new_impl;
void*object_class(void*p){return p==&command?&command_class:nullptr;}
void*mp4_resolved_type_class(const mp4game::Binding&b,const char*ns,const char*name){assert(b.rva==1&&!std::strcmp(ns,"UnityEngine.Rendering")&&!std::strcmp(name,"CommandBuffer"));return class_verified?&command_class:nullptr;}
uint32_t mp4_retain(void*){return 1;}void*weak_get(uint32_t){return &command;}void weak_free(uint32_t){}
// SHIPPING_GPU_FENCE_HOST
bool producer_check(uint64_t source,uint64_t epoch){++mp4_gpu_fence::source_checks;return producers&&source==4&&epoch==9;}
void setup(){for(auto pair:{std::pair<Blob*,uintptr_t>{&ctor_method,2},{&dispose_method,3},{&create_method,4}}){put<uintptr_t>(pair.first,0,image_base+pair.second);put<void*>(pair.first,32,&command_class);put<uint8_t>(pair.first,82,pair.second==4?2:0);}mp4_gpu_graphics_producers_closed=producer_check;}
Mp4RenderSubmission ticket(uint64_t token=17){return {{&command},4,9,0,token,false};}
int main(int argc,char**argv){assert(argc==2);setup();int c=std::atoi(argv[1]);auto s=ticket();using R=Mp4SceneResult;using F=mp4_gpu_fence::Result;
 if(c==0){assert(mp4_gpu_begin_draw(s)==R::ok);assert(mp4_gpu_record_submit(s));assert(mp4_gpu_end_draw(s));assert(mp4_gpu_draw_fenced(9,17));assert(mp4_gpu_release(9));assert(!mp4_gpu_fence_host.configured);}
 else if(c>=1&&c<=5){if(c==1)producers=false;if(c==2)source_verified=false;if(c==3)class_verified=false;if(c==4)put<uint8_t>(&create_method,82,1);if(c==5)put<void*>(&dispose_method,32,&command);assert(mp4_gpu_begin_draw(s)==R::unsupported);}
 else if(c==6){assert(mp4_gpu_begin_draw(s)==R::ok);auto stale=s;stale.job_generation++;assert(!mp4_gpu_record_submit(stale));assert(!mp4_gpu_end_draw(stale));assert(mp4_gpu_record_submit(s));assert(mp4_gpu_end_draw(s));}
 else if(c==7){assert(mp4_gpu_begin_draw(s)==R::ok);assert(!mp4_gpu_draw_fenced(9,17));assert(mp4_gpu_end_draw(s));assert(mp4_gpu_begin_draw(s)==R::stale);}
 else if(c==8){assert(mp4_gpu_begin_draw(s)==R::ok);assert(mp4_gpu_end_draw(s));mp4_gpu_fence::poll_fixture=F::waiting;assert(mp4_gpu_preflight(4,9)==R::waiting);assert(mp4_gpu_begin_draw(ticket(21))==R::waiting);assert(mp4_gpu_fence_host.sequence==1&&!mp4_gpu_fence_host.draw);}
 else if(c==9){assert(mp4_gpu_begin_draw(s)==R::ok);assert(mp4_gpu_end_draw(s));mp4_gpu_fence::begin_fail=true;assert(mp4_gpu_begin_draw(ticket(21))==R::stale);assert(mp4_gpu_fence::retires==1);assert(mp4_gpu_begin_draw(ticket(22))==R::ok);assert(mp4_gpu_fence::retires==1);}
 else if(c==10){assert(mp4_gpu_begin_draw(s)==R::ok);assert(mp4_gpu_end_draw(s));source_verified=false;producers=false;assert(mp4_gpu_final_fenced(9));assert(mp4_gpu_release(9));assert(mp4_gpu_fence::source_checks==1);}
 else if(c==11){assert(mp4_gpu_begin_draw(s)==R::ok);assert(mp4_gpu_end_draw(s));assert(!mp4_gpu_final_fenced(8));assert(!mp4_gpu_fence_host.sealed);assert(mp4_gpu_preflight(4,9)==R::ok);}
 else if(c==12){assert(mp4_gpu_begin_draw(s)==R::ok);mp4_gpu_submit_failed(s);assert(!mp4_gpu_end_draw(s));assert(!mp4_gpu_release(9));}
 else if(c==13){assert(mp4_gpu_begin_draw(s)==R::ok);mp4_gpu_fence::dispatch_returned=false;assert(!mp4_gpu_record_submit(s));assert(mp4_gpu_end_draw(s));}
 else if(c==14){uint64_t v=0x123456789abcdefULL,out=0;assert(mp4_gpu_host_read(nullptr,reinterpret_cast<uintptr_t>(&v),&out,8)&&out==v);map_allowed=false;assert(!mp4_gpu_host_read(nullptr,reinterpret_cast<uintptr_t>(&v),&out,8));}
 else if(c==15){assert(mp4_gpu_preflight(4,9)==R::ok);assert(!mp4_gpu_fence_host.configured);on_thread=false;assert(mp4_gpu_preflight(4,9)==R::stale);assert(mp4_gpu_begin_draw(s)==R::stale);}
 else if(c==16){assert(mp4_gpu_begin_draw(s)==R::ok);assert(mp4_gpu_end_draw(s));auto foreign=ticket(22);foreign.source_generation++;assert(mp4_gpu_begin_draw(foreign)==R::stale);assert(mp4_gpu_fence::retires==0);}
 else if(c==17){assert(mp4_gpu_begin_draw(s)==R::ok);assert(mp4_gpu_end_draw(s));mp4_gpu_unknown_work(9);assert(!mp4_gpu_release(9));}
 else return 2;
 return 0;
}
