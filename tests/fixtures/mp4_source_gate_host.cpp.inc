
#include <cstdint>
#include <cstddef>
#include <cstring>
#include <cmath>
#include <initializer_list>
#include <type_traits>
#include "mp4_engine_clock.hpp"
#include <vector>
#include <string>
#include <cassert>
using namespace idoly_mp4_world;
struct Arr{std::vector<void*>items;std::vector<LoopEntry>loops;bool is_loop=false;};
struct Cloth{bool live=true,enabled=false;} cloth_item;
struct Fixture{
 alignas(8) unsigned char manager[128]{},buckets[16*24]{},info[8][80]{};
 char names[8][40]{};Arr families[4],loop;
 bool source=true,held=true,actors=true,normal=true,routes=true,thread=true,lookup_bad=false;
 unsigned calls=0,root_count=0;void*roots[64]{};
} f;
FixedGate gate;unsigned native_calls=0;bool lose_normal=false;
template<class T>void put(void*p,size_t at,T v){memcpy(static_cast<unsigned char*>(p)+at,&v,sizeof v);}
template<class T>T get(const void*p,size_t at){T v{};memcpy(&v,static_cast<const unsigned char*>(p)+at,sizeof v);return v;}
bool contains(uintptr_t a,size_t n,const void*p,size_t len){const uintptr_t b=reinterpret_cast<uintptr_t>(p);return a>=b&&n<=len&&a-b<=len-n;}
bool mapped(uintptr_t a,size_t n){
 if(!a||!n)return false;
 if(contains(a,n,f.manager,sizeof f.manager)||contains(a,n,f.buckets,sizeof f.buckets)
 ||contains(a,n,f.info,sizeof f.info)||contains(a,n,f.names,sizeof f.names))return true;
 for(auto&x:f.families)if(contains(a,n,x.items.data(),x.items.size()*sizeof(void*)))return true;
 return contains(a,n,f.loop.loops.data(),f.loop.loops.size()*sizeof(LoopEntry));
}
bool source(void*c){++f.calls;return c==&f&&f.source;}
bool held(void*){return f.held;}
bool actors(void*){return f.actors;}
bool disturb_animation=false;void disturb_actual_animation();
bool normal(void*){if(lose_normal)f.source=false;if(disturb_animation)disturb_actual_animation();return f.normal;}
bool routes(){return f.routes&&gate.installed();}
bool type(void*p,const char*n){if(!strcmp(n,"System.Array")){for(auto&a:f.families)if(p==&a)return true;return p==&f.loop;}return p==&cloth_item&&!strcmp(n,"UnityEngine.Cloth");}
bool alive(void*p){return p==&cloth_item&&cloth_item.live;}
uint32_t retain(void*p){for(unsigned i=0;i<64;++i)if(!f.roots[i]){f.roots[i]=p;++f.root_count;return i+1;}return 0;}
void*retained(uint32_t i){return i&&i<=64?f.roots[i-1]:nullptr;}
void free_root(uint32_t i){assert(i&&i<=64&&f.roots[i-1]);f.roots[i-1]=nullptr;--f.root_count;}
size_t length(void*p){auto*a=static_cast<Arr*>(p);return a->is_loop?a->loops.size():a->items.size();}
void*data(void*p){auto*a=static_cast<Arr*>(p);return a->is_loop?static_cast<void*>(a->loops.data()):static_cast<void*>(a->items.data());}
void*find(void*t,bool inactive,Method*){assert(!inactive);auto n=reinterpret_cast<uintptr_t>(t);assert(n>=1&&n<=4);return &f.families[n-1];}
void*current_loop(Method*){return &f.loop;}
bool enabled(void*p,Method*){assert(p==&cloth_item);return cloth_item.enabled;}
void*native_registry(){return f.manager;}
const void*native_type(int32_t id){
 if(f.lookup_bad&&id==54)return f.info[1];
 for(size_t i=0;i<16;++i){auto*p=f.buckets+i*24;if(get<uint32_t>(p,0)<0xfffffffeu&&get<uint32_t>(p,8)==uint32_t(id))return reinterpret_cast<void*>(get<uintptr_t>(p,16));}return nullptr;
}
bool owner_thread(){return f.thread;}
bool original(){++f.calls;++native_calls;return true;}
void row(unsigned i,uint32_t id,const char*name){assert(i<8);strcpy(f.names[i],name);put(f.info[i],16,reinterpret_cast<uintptr_t>(f.names[i]));put(f.info[i],40,id);put(f.buckets+i*24,0,uint32_t(0x100+i*4));put(f.buckets+i*24,8,id);put(f.buckets+i*24,16,reinterpret_cast<uintptr_t>(f.info[i]));}
Api api(){Api a{};a.source_current=source;a.clock_held=held;a.actor_jobs_closed=actors;a.normal_animation_closed=normal;
 a.routes_ready=routes;a.mapped=mapped;a.is_type=type;a.alive=alive;a.retain=retain;a.retained=retained;a.release_root=free_root;
 a.array_length=length;a.array_data=data;a.find_objects=find;a.current_loop=current_loop;a.cloth_enabled=enabled;
 a.native_registry=native_registry;a.native_type=native_type;a.rigidbody_type=reinterpret_cast<void*>(1);a.rigidbody2d_type=reinterpret_cast<void*>(2);
 a.cloth_type=reinterpret_cast<void*>(3);a.character_controller_type=reinterpret_cast<void*>(4);a.fixed_update_type=reinterpret_cast<void*>(5);return a;}
void setup(){
 for(size_t i=0;i<16;++i)put(f.buckets+i*24,0,uint32_t(0xffffffff));
 row(0,54,"Rigidbody");row(1,50,"Rigidbody2D");row(2,183,"Cloth");row(3,143,"CharacterController");
 put(f.manager,64,reinterpret_cast<uintptr_t>(f.buckets));put(f.manager,72,uint32_t(15*8));put(f.manager,76,uint32_t(4));put(f.manager,80,uint32_t(12));
 f.loop.is_loop=true;
 f.loop.loops={{reinterpret_cast<void*>(100),nullptr,0,0,2,0},
  {reinterpret_cast<void*>(5),nullptr,0,0x3330,1,0},
  {reinterpret_cast<void*>(101),reinterpret_cast<void*>(500),0,0,0,0},
  {reinterpret_cast<void*>(102),nullptr,0,0,0,0}};
 assert(gate.install({original,owner_thread}));
}

static_assert(!std::is_copy_constructible<SourceGateLease>::value&&!std::is_copy_assignable<SourceGateLease>::value,"real gate leases are noncopyable");
static_assert(std::is_move_constructible<SourceGateLease>::value&&!std::is_move_assignable<SourceGateLease>::value,"no overwriting an existing physical duty");
AnimationGate animation;SourceGateLease*inside_token=nullptr;void*inside_owner=nullptr;bool release_inside=false;
void animation_original(){if(release_inside){assert(inside_token&&inside_owner&&!animation.release_lease(*inside_token,inside_owner));}}
void animation_setup(){AnimationApi a{};a.owner_thread=owner_thread;for(auto&call:a.original)call=animation_original;assert(animation.install(a));}


using Mp4SceneResult=Result;
struct Mp4SceneWitness{uint64_t generation=0,token=0;};
bool mp4_scene_same_source(const Mp4SceneWitness&a,const Mp4SceneWitness&b){return a.generation==b.generation&&a.token==b.token;}
struct{Mp4SceneWitness source{7,11};}mp4_scene_host;
namespace idoly_mp4_runtime{struct{uint64_t generation=9;}job;}
bool source_window=true;bool game_call(){return f.thread;}
bool mp4_stage_source_window(){return f.thread&&f.source&&f.held&&source_window;}
FixedGate&mp4_fixed_gate=gate;AnimationGate&mp4_animation_gate=animation;
struct WorldHost{Scope scope;Mp4SceneWitness source{7,11};uint64_t epoch=7;bool animation_owned=false,restoration_verified=false,invalidated=false;const char*error="none";}mp4_world_host;
unsigned legacy_capture=0;Mp4SceneResult mp4_world_result(Result r){return r;}
Mp4SceneResult mp4_world_driving_quiesce(){return Result::ok;}Mp4SceneResult mp4_world_driving_release(){return Result::ok;}
Mp4SceneResult mp4_world_capture_legacy(void*){++legacy_capture;auto&h=mp4_world_host;if(!h.animation_owned){if(!animation.acquire(h.epoch))return Result::unsupported;h.animation_owned=true;}return h.scope.capture();}
// SOURCE_GATE_ADOPTION_HOST
void disturb_actual_animation(){f.thread=false;assert(animation.invoke(0));f.thread=true;disturb_animation=false;}
int main(int argc,char**argv){assert(argc==2);setup();animation_setup();assert(mp4_world_host.scope.configure(api(),&gate,&f,7,0x3330));const std::string mode=argv[1];
 if(mode=="host_adopt"){
  assert(mp4_early_source_gates.acquire()==Result::ok);const auto fixed=mp4_early_source_gates.fixed_serial(),anim=mp4_early_source_gates.animation_serial();const auto n=native_calls;
  assert(mp4_world_capture_adopting_source_gates()==Result::ok&&!legacy_capture&&native_calls==n&&mp4_early_source_gates.current());assert(mp4_world_host.scope.adopted_fixed_serial()==fixed&&mp4_world_adopted_animation.serial()==anim);
  assert(mp4_world_full_quiesce_adopting_source_gates()==Result::ok&&!legacy_capture);assert(mp4_early_source_gates.release_after_fence()==Result::waiting);assert(mp4_world_release_source_checked(nullptr,false)==Result::ok&&mp4_early_source_gates.release_after_fence()==Result::ok&&gate.native_condition());
 }else if(mode=="host_legacy"){
  assert(mp4_world_capture_adopting_source_gates()==Result::ok&&legacy_capture==1);assert(mp4_world_release_source_checked(nullptr,false)==Result::ok&&gate.native_condition());
 }else if(mode=="host_measure_refuses"){
  assert(mp4_early_source_gates.acquire()==Result::ok);f.normal=false;assert(mp4_world_capture_adopting_source_gates()==Result::unsupported&&mp4_early_source_gates.current()&&!mp4_world_host.scope.active());assert(mp4_world_release_source_checked(nullptr,false)==Result::ok&&mp4_early_source_gates.release_after_fence()==Result::ok);
 }else if(mode=="host_partial_transfer"){
  assert(mp4_early_source_gates.acquire()==Result::ok);disturb_animation=true;assert(mp4_world_capture_adopting_source_gates()==Result::stale&&mp4_world_host.scope.active()&&mp4_world_host.scope.adopted_fixed_current()&&!mp4_world_host.animation_owned);
  assert(mp4_early_source_gates.release_after_fence()==Result::waiting);assert(mp4_world_release_source_checked(nullptr,false)==Result::ok&&mp4_early_source_gates.release_after_fence()==Result::ok);
 }else if(mode=="host_source_lost_cleanup"){
  assert(mp4_early_source_gates.acquire()==Result::ok&&mp4_world_capture_adopting_source_gates()==Result::ok);f.source=false;assert(mp4_world_release_source_checked(nullptr,false)==Result::ok&&mp4_early_source_gates.release_after_fence()==Result::ok);
 }else if(mode=="host_cleanup_wrong_thread"){
  assert(mp4_early_source_gates.acquire()==Result::ok&&mp4_world_capture_adopting_source_gates()==Result::ok);f.thread=false;assert(mp4_world_release_source_checked(nullptr,false)==Result::waiting&&mp4_world_host.epoch==7&&mp4_world_host.source.generation==7&&mp4_world_host.animation_owned);f.thread=true;assert(mp4_world_release_source_checked(nullptr,false)==Result::ok&&mp4_early_source_gates.release_after_fence()==Result::ok);
 }else if(mode=="host_early_partial_acquire"){
  assert(animation.acquire(99));assert(mp4_early_source_gates.acquire()==Result::unsupported&&mp4_early_source_gates.fixed_serial()&&!mp4_early_source_gates.animation_serial());assert(mp4_early_source_gates.release_after_fence()==Result::ok&&animation.healthy(99));assert(animation.release(99));
 }else if(mode=="host_detach_adopted"){
  assert(mp4_early_source_gates.acquire()==Result::ok&&mp4_world_capture_adopting_source_gates()==Result::ok);assert(mp4_world_detach_source_gates_checked(nullptr)==Result::ok&&!gate.healthy(7));assert(mp4_early_source_gates.release_after_fence()==Result::ok);assert(mp4_world_detach_source_gates_checked(nullptr)==Result::ok&&mp4_world_release_source_checked(nullptr,false)==Result::ok);
 }else if(mode=="host_detach_configured_only"){
  assert(mp4_early_source_gates.acquire()==Result::ok);assert(mp4_world_detach_source_gates_checked(nullptr)==Result::ok&&mp4_early_source_gates.current());assert(mp4_world_release_source_checked(nullptr,false)==Result::ok&&mp4_early_source_gates.release_after_fence()==Result::ok);
 }else if(mode=="host_job_changed"){
  assert(mp4_early_source_gates.acquire()==Result::ok);idoly_mp4_runtime::job.generation=10;assert(!mp4_early_source_gates.current()&&mp4_world_capture_adopting_source_gates()==Result::stale);assert(mp4_world_release_source_checked(nullptr,false)==Result::ok&&mp4_early_source_gates.release_after_fence()==Result::ok);
 }else if(mode=="host_dirty_retained"){
  assert(mp4_early_source_gates.acquire()==Result::ok&&mp4_world_capture_adopting_source_gates()==Result::ok);animation.release(7);assert(!mp4_early_source_gates.current());assert(mp4_early_source_gates.release_after_fence()==Result::waiting);assert(mp4_world_release_source_checked(nullptr,false)==Result::ok&&mp4_early_source_gates.release_after_fence()==Result::ok);
 }else if(mode=="host_reacquire_same_epoch"){
  assert(mp4_early_source_gates.acquire()==Result::ok);const auto old=mp4_early_source_gates.fixed_serial();assert(mp4_early_source_gates.release_after_fence()==Result::ok&&mp4_early_source_gates.acquire()==Result::ok&&mp4_early_source_gates.fixed_serial()>old);assert(mp4_early_source_gates.release_after_fence()==Result::ok&&mp4_world_release_source_checked(nullptr,false)==Result::ok);
 }else return 2;
 assert(f.root_count==0);return 0;
}
