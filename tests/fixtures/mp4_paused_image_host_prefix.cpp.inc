#include <cassert>
#include <cstdint>
#include <cstddef>
#include <cstring>
#include <initializer_list>
#include <string>
#include <unordered_map>
#include <stdexcept>
using Method=void;
namespace idoly_mp4_camera_state {enum class Result:int{ok=0,waiting=1,unsupported=-1,invalid=-2,failed=-3,stale=-4};}
// __FRAME_SCOPE__
namespace mp4frame=idoly_mp4_paused_frame;
struct Obj{alignas(16) uint8_t bytes[512]{};std::string type;};
Obj controller{},camera{},target{},original{},private_wrapper{},target_rt{},private_rt{},backup_rt{},foreign{};
std::unordered_map<void*,Obj*> objects;
std::unordered_map<void*,mp4frame::Descriptor> descriptors;
std::unordered_map<uint32_t,void*> roots;uint32_t root_serial=0;
bool thread_ok=true,current_ok=true,held_clock=true,held_gpu=true,idle=true,aliases_clear=true,preserve_good=true;
bool production_good=true,owned_good=true,fail_root=false,throw_destroy=false,defer_destroy=false;
int field_writes=0,destroys=0,preserves=0,allocations=0,global_writes=0;
template<class T>void put(Obj&o,size_t at,T value){std::memcpy(o.bytes+at,&value,sizeof value);}
void*ref(Obj&o){return o.bytes;}
bool game_call(){return thread_ok;}
bool mp4_exact_type(void*p,const char*t){auto i=objects.find(p);return i!=objects.end()&&i->second->type==t;}
template<class T>bool mp4_actor_field(void*p,size_t at,T&out){auto i=objects.find(p);if(i==objects.end()||at+sizeof out>512)return false;std::memcpy(&out,i->second->bytes+at,sizeof out);return true;}
bool mp4_actor_mapped(void*p,size_t size,bool){auto a=reinterpret_cast<uintptr_t>(p);for(auto&row:objects){auto b=reinterpret_cast<uintptr_t>(row.first);if(a>=b&&a-b<=512&&size<=512-(a-b))return true;}return false;}
bool mp4_alive(void*p){uintptr_t native=0;return mp4_actor_field(p,16,native)&&native;}
uint32_t mp4_retain(void*p){if(!p||fail_root)return 0;roots[++root_serial]=p;return root_serial;}
void*weak_get(uint32_t h){auto i=roots.find(h);return i==roots.end()?nullptr:i->second;}
void weak_free(uint32_t h){assert(roots.erase(h)==1);}
struct Mp4SceneWitness{uint64_t generation=0;void*controller=nullptr,*camera=nullptr,*player=nullptr;};
bool mp4_scene_same_source(const Mp4SceneWitness&a,const Mp4SceneWitness&b){return a.generation==b.generation&&a.controller==b.controller&&a.camera==b.camera&&a.player==b.player;}
struct SceneHost{bool active=true,invalidated=false,releasing=false;unsigned configured=15;static constexpr unsigned all=15;Mp4SceneWitness source{};}mp4_scene_host;
struct{bool verified=true;}mp4_camera_host;
bool mp4_scene_source_current(){return current_ok;}
namespace idoly_mp4_runtime{
struct {uint64_t generation=9;}job;
struct Clock{bool held(){return held_clock;}}clock;
Clock&native_clock_scope(){return clock;}
struct Game{bool owned_pending_capture(void*c,void*k,void*w){return owned_good&&c==ref(camera)&&k==ref(controller)&&w==ref(private_wrapper);}}game;
}
bool mp4_renderer_capture_idle(void*p){assert(p==ref(camera));return idle;}
void mp4_camera_barrier(void*owner,void**slot,void*value){assert(owner==ref(controller)&&slot==reinterpret_cast<void**>(controller.bytes+160));++field_writes;std::memcpy(slot,&value,sizeof value);}
struct Mp4PausedTextureStorage{void*object=nullptr;uint32_t root=0;uintptr_t native=0;};
bool mp4_paused_texture_read(void*p,mp4frame::Texture*out){
 if(out)*out={};
 uintptr_t native=0;auto d=descriptors.find(p);
 if(!out||!mp4_exact_type(p,"UnityEngine.RenderTexture")||!mp4_actor_field(p,16,native)||!native||d==descriptors.end())return false;
 *out={p,native,d->second};return true;
}
mp4frame::Result mp4_paused_texture_allocate(Mp4PausedTextureStorage&h,void*source,const mp4frame::Descriptor&d,mp4frame::Texture*out){
 assert(source==ref(target_rt));++allocations;h.object=ref(backup_rt);h.native=303;h.root=mp4_retain(h.object);put(backup_rt,16,h.native);descriptors[h.object]=d;
 return mp4_paused_texture_read(h.object,out)?mp4frame::Result::ok:mp4frame::Result::failed;
}
bool mp4_paused_texture_copy_supported(const mp4frame::Texture&a,const mp4frame::Texture&b){return a.object&&b.object&&a.object!=b.object&&!std::memcmp(&a.descriptor,&b.descriptor,sizeof a.descriptor);}
bool mp4_paused_texture_destroy(Mp4PausedTextureStorage&h,mp4frame::Texture&out){if(h.root)weak_free(h.root);h.root=0;put(backup_rt,16,uintptr_t(0));out={};return true;}
struct{uint64_t source=0,job=0;}mp4_paused_copy_bank;
uint64_t ticket_serial=0;bool copy_ready=false,copy_returned=false;int copies=0;
mp4frame::Result mp4_paused_copy_begin(void*,const mp4frame::Texture&,const mp4frame::Texture&,uint64_t*t){*t=++ticket_serial;copy_returned=false;return mp4frame::Result::ok;}
void mp4_paused_copy_original(void*,void*,void*){++copies;copy_returned=true;}
mp4frame::Result mp4_paused_copy_complete(void*,uint64_t,bool returned){assert(returned&&copy_returned);return mp4frame::Result::ok;}
mp4frame::Result mp4_paused_copy_poll(void*,uint64_t){return copy_ready?mp4frame::Result::ok:mp4frame::Result::waiting;}
bool mp4_paused_copy_retire(void*,uint64_t){return copy_ready;}
bool mp4_paused_copy_finish(uint64_t s,uint64_t j,bool actual){assert(actual&&mp4_paused_copy_bank.source==s&&mp4_paused_copy_bank.job==j);mp4_paused_copy_bank={};return true;}
void destroy_original(void*p,bool allow,Method*){assert(p==ref(private_rt)&&!allow);++destroys;if(throw_destroy)throw 41;if(!defer_destroy)put(private_rt,16,uintptr_t(0));}
struct{uintptr_t object_destroy_immediate=reinterpret_cast<uintptr_t>(destroy_original);}mp4_cam_profile;
template<class F>F mp4_cam_call(uintptr_t p){return reinterpret_cast<F>(p);}
bool held_fence(void*p){assert(p==&held_gpu);return held_gpu;}
bool production_provider(void*p,uint64_t epoch,uint64_t job,void*w,void*t,uintptr_t native){
 assert(p==&held_gpu);return production_good&&epoch==7&&job==9&&w==ref(private_wrapper)&&t==ref(private_rt)&&native==202;
}
bool alias_provider(void*p,void*w,void*t,uintptr_t native){assert(p==&held_gpu&&w==ref(private_wrapper)&&t==ref(private_rt)&&native==202);return aliases_clear;}
bool preservation_provider(void*p,void*w){assert(p==&held_gpu&&(w==ref(original)||w==ref(private_wrapper)));++preserves;return preserve_good;}
void setup(){
 for(auto pair:{std::pair<Obj*,const char*>{&controller,"VL.Rendering.VLSRPCameraController"},{&camera,"UnityEngine.Camera"},{&target,"VL.VLRenderTexture"},{&original,"VL.VLRenderTexture"},{&private_wrapper,"VL.VLRenderTexture"},{&target_rt,"UnityEngine.RenderTexture"},{&private_rt,"UnityEngine.RenderTexture"},{&backup_rt,"UnityEngine.RenderTexture"},{&foreign,"UnityEngine.RenderTexture"}}){pair.first->type=pair.second;objects[ref(*pair.first)]=pair.first;}
 put(controller,16,uintptr_t(1010));put(camera,16,uintptr_t(1020));put(target_rt,16,uintptr_t(101));put(private_rt,16,uintptr_t(202));
 put(controller,80,ref(camera));put(controller,152,ref(target));put(controller,160,ref(original));put(target,16,ref(target_rt));put(private_wrapper,16,ref(private_rt));
 mp4frame::Descriptor d{};d.width=256;d.height=144;d.samples=d.depth=d.mips=1;d.format=8;d.dimension=2;descriptors[ref(target_rt)]=d;descriptors[ref(private_rt)]=d;
 mp4_scene_host.source={7,ref(controller),ref(camera),reinterpret_cast<void*>(1)};
}
