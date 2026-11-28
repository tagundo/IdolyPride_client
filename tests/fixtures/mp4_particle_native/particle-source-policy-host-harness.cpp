#include <cassert>
#include <cstdio>
#include <cstdint>
#include <cstddef>
#include <cstdlib>
#include <cstring>
#include <initializer_list>
#include <map>
#include <memory>
#include <vector>
#include "particle-state-image.hpp.inc"
namespace mp4ps=idoly_mp4_particle_state;using Method=void;
struct Region{uintptr_t first;size_t bytes;};std::vector<Region>regions;std::vector<std::unique_ptr<uint8_t[]>>storage;
void*alloc(size_t n){storage.emplace_back(new uint8_t[n]{});void*p=storage.back().get();regions.push_back({(uintptr_t)p,n});return p;}
bool mapped(const void*p,size_t n){auto a=(uintptr_t)p;for(auto r:regions)if(a>=r.first&&a+n>=a&&a+n<=r.first+r.bytes)return true;return false;}
template<class T>bool mp4_actor_field(void*p,size_t at,T&out){if(!mapped((uint8_t*)p+at,sizeof out))return false;::memcpy(&out,(uint8_t*)p+at,sizeof out);return true;}
template<class T>void put(void*p,size_t at,T v){assert(mapped((uint8_t*)p+at,sizeof v));::memcpy((uint8_t*)p+at,&v,sizeof v);}
bool mp4_particle_native_state_mapped(uintptr_t p,size_t n){return mapped((void*)p,n);}bool mp4_native_mapped(uintptr_t p,size_t n,int){return mapped((void*)p,n);}
bool main_thread=true,source=true,held=true,verified=true,live=true,finish_current=true;bool game_call(){return main_thread;}bool mp4_alive(void*p){return live&&p&&mapped(p,24);}bool mp4_stage_owner(void*){return source;}bool mp4_actor_clock_held(void*){return held;}
void*particle=nullptr,*renderer=nullptr,*go=nullptr,*native=nullptr,*rnative=nullptr,*gnative=nullptr,*state=nullptr,*modules=nullptr,*parameters=nullptr,*parts=nullptr,*renderer_type=nullptr,*code=nullptr,*vtable=nullptr,*array=nullptr;
std::map<uint32_t,void*>roots;uint32_t root_next=1;unsigned retains=0,frees=0;bool retain_fail=false;
uint32_t mp4_retain(void*p){++retains;if(retain_fail||!p)return 0;roots[root_next]=p;return root_next++;}void*weak_get(uint32_t r){auto it=roots.find(r);return it==roots.end()?nullptr:it->second;}void weak_free(uint32_t r){++frees;roots.erase(r);}
struct Mp4ActorTempRoot{uint32_t root;explicit Mp4ActorTempRoot(void*p):root(mp4_retain(p)){}~Mp4ActorTempRoot(){if(root)weak_free(root);}void*get(){return weak_get(root);}};
namespace mp4game{struct Binding{uintptr_t rva=0;uint8_t prefix[16]{};};}struct Mp4TimelineTypePin{const char*name=nullptr;mp4game::Binding binding{};};
struct Mp4ParticlePolicyCode{uintptr_t rva=0;uint8_t prefix[16]{};};
struct{const char*sha256="native";uintptr_t renderer_vtable=0;Mp4TimelineTypePin renderer{};mp4game::Binding render_mode{},global_block_get{},global_block_set{},shared_materials{};Mp4ParticlePolicyCode module_enabled{},params_policy{},module_roles{},local_get{},world_get{},local_set{},world_set{},reset_local{},reset_world{};}mp4_particle_policy_pins;
uintptr_t mp4_native_base=0,image_base=0;struct{const char*native_sha256="native";}mp4_native_profile;
bool mp4_source_verified=true,mp4_stage_source_verified=true;bool mp4_prefix(const mp4game::Binding&){return verified;}bool mp4_hook_was_statically_verified(const mp4game::Binding&){return false;}
bool mp4_timeline_class(const Mp4TimelineTypePin&){return verified;}bool mp4_timeline_exact(void*p,const Mp4TimelineTypePin&){return p==renderer;}
std::map<void*,const char*> extra_types;
bool mp4_type_is(void*p,const char*t){auto it=extra_types.find(p);if(it!=extra_types.end()&&!::strcmp(it->second,t))return true;return (p==particle&&!::strcmp(t,"UnityEngine.ParticleSystem"))||(p==go&&!::strcmp(t,"UnityEngine.GameObject"));}
struct Mp4SceneWitness{uint64_t generation=7;};
bool mp4_scene_same_source(const Mp4SceneWitness&a,const Mp4SceneWitness&b){return a.generation==b.generation;}
struct{Mp4SceneWitness source{};struct StageOwner{void*particle=nullptr;}owners[256]{};size_t count=1;bool configured=true,restored=false;}mp4_stage_host;
namespace idoly_mp4_runtime{struct{uint64_t generation=11;}job;}
namespace idoly_mp4_stage{struct Owner{void*particle=nullptr,*producer=nullptr;uint32_t producer_kind=0;};}
uint64_t public_capture=13;bool public_restored=false;
struct{bool snapshot_receipt(void*p,idoly_mp4_stage::Owner*out,uint64_t*r,bool*restored){if(p!=particle||!source||!public_capture)return false;*out={p,p,1};*r=public_capture;*restored=public_restored;return true;}}mp4_stage_particles;
struct{const char*sha256="native";uintptr_t vtable=0;}mp4_particle_manager_pins;
struct Mp4ParticleStateNativeValue{uint8_t bytes[352]{};};
struct{uintptr_t rva=0;uint8_t prefix[16]{};}mp4_particle_state_pin;
unsigned finish_calls=0;Mp4ParticleStateNativeValue original_finish(void*){++finish_calls;put(native,0x6c,uint8_t(0));return{};}
// This harness executes the production typed C++ aggregate call at the actual
// function pointer. ARM entry pin/executable mapping are modeled separately.
#include "particle-native-finish-receipt-host.cpp.inc"
void*component_gameobject(void*p,Method*){return p==particle||p==renderer?go:nullptr;}
void*components_internal(void*object,void*type,bool b,bool recursive,bool inactive,bool reverse,void*result,Method*){assert(object==go&&type==renderer_type&&b&&!recursive&&inactive&&!reverse&&!result);return array;}
int32_t mode=0;int32_t render_mode(void*p,Method*){assert(p==renderer);return mode;}
struct{mp4game::Binding component_gameobject{},components_internal{};}mp4_stage_profile;
template<class T>T mp4_equipment_call(const mp4game::Binding&b){return reinterpret_cast<T>(image_base+b.rva);}
void*mp4_type_get_object(void*){return renderer_type;}size_t array_count=1;
bool mp4_stage_array(void*p,void***out,size_t*n,size_t limit){if(p!=array||array_count>limit)return false;*out=reinterpret_cast<void**>(array);*n=array_count;return true;}
#include "particle-source-policy-host.inc"
bool exclusion(const Mp4ParticleFinishOwner&o,uint64_t b){return finish_current&&b==61&&o.managed==particle&&o.capture==public_capture;}
void setup(){particle=alloc(32);renderer=alloc(32);go=alloc(32);native=alloc(0xb0);rnative=alloc(0x850);gnative=alloc(0x50);state=alloc(0x220);modules=alloc(0x1490);parameters=alloc(0x60);parts=alloc(0x20);renderer_type=alloc(32);code=alloc(16);vtable=alloc(0x180);array=alloc(2*sizeof(void*));}
void reset(){main_thread=true;mp4_particle_source_policy_clear();mp4_particle_finish_reset();source=held=verified=live=finish_current=true;mp4_source_verified=mp4_stage_source_verified=true;retain_fail=false;mode=0;public_capture=13;public_restored=false;array_count=1;mp4_stage_host.source.generation=7;idoly_mp4_runtime::job.generation=11;mp4_native_profile.native_sha256="native";mp4_native_base=1;image_base=0;
 ::memset(state,0,0x220);::memset(modules,0,0x1490);::memset(parameters,0,0x60);put(particle,16,(uintptr_t)native);put(renderer,16,(uintptr_t)rnative);put(go,16,(uintptr_t)gnative);put(native,0,(uintptr_t)vtable);mp4_particle_manager_pins.vtable=(uintptr_t)vtable-1;put(native,8,int32_t(17));put(native,0x30,(uintptr_t)gnative);put(native,0x38,(uintptr_t)parts);put(native,0x40,(uintptr_t)parameters);put(native,0x48,(uintptr_t)state);put(native,0x50,(uintptr_t)modules);put(native,0x6c,uint8_t(0));put(rnative,0,(uintptr_t)vtable);put(rnative,8,int32_t(19));put(rnative,0x30,(uintptr_t)gnative);put(gnative,8,int32_t(23));put(modules,0x21c,uint32_t(4));put(array,0,renderer);
 mp4_particle_policy_pins.renderer_vtable=(uintptr_t)vtable-1;for(auto*p:{&mp4_particle_policy_pins.module_enabled,&mp4_particle_policy_pins.params_policy,&mp4_particle_policy_pins.module_roles}){p->rva=(uintptr_t)code-1;::memset(p->prefix,0,16);}mp4_stage_profile.component_gameobject.rva=(uintptr_t)&component_gameobject;mp4_stage_profile.components_internal.rva=(uintptr_t)&components_internal;mp4_particle_policy_pins.render_mode.rva=(uintptr_t)&render_mode;
 mp4_particle_state_pin.rva=(uintptr_t)&original_finish-1;::memcpy(mp4_particle_state_pin.prefix,(void*)&original_finish,16);regions.push_back({(uintptr_t)&original_finish,16});mp4_particle_finish_context.exclusion_current=exclusion;Mp4ParticleFinishReceipt f{};assert(mp4_particle_finish_issue(particle,61,&f)&&f.serial);}
uint64_t capture(){uint64_t r=0;assert(mp4_particle_source_policy_capture(particle,&r)&&r);return r;}
mp4ps::Owner owner(){mp4ps::Owner o{};assert(mp4_particle_source_policy_owner(particle,&o));return o;}
#ifndef MP4_PARTICLE_POLICY_NO_MAIN
int main(){setup();unsigned cases=0;
 {reset();auto r=capture();auto o=owner();uint64_t actual=0;assert(o.policy==r&&mp4_particle_source_policy_owned(o,&actual)&&actual==r);++cases;}
 {reset();mode=1;capture();assert(owner().policy);++cases;}
 {reset();mode=4;put(modules,0x21c,uint32_t(5));capture();assert(owner().policy);++cases;}
 for(int m:{2,3,5}){reset();mode=m;uint64_t r=0;assert(!mp4_particle_source_policy_capture(particle,&r)&&!r);++cases;}
 for(size_t at:{0xfb8u,0x11d0u,0x1218u,0x1248u,0x10c8u,0xb98u}){reset();put(modules,at,uint8_t(1));uint64_t r=0;assert(!mp4_particle_source_policy_capture(particle,&r)&&!r);++cases;}
 {reset();put(parameters,0x40,uint32_t(1));uint64_t r=0;assert(!mp4_particle_source_policy_capture(particle,&r));++cases;}
 {reset();put(modules,0x21c,uint32_t(6));uint64_t r=0;assert(!mp4_particle_source_policy_capture(particle,&r));++cases;}
 for(size_t at:{0x360u,0x420u,0x428u}){reset();put(modules,at,uintptr_t(1));uint64_t r=0;assert(!mp4_particle_source_policy_capture(particle,&r));++cases;}
 for(size_t at:{0x1d0u,0x210u}){reset();put(state,at,uint64_t(1));uint64_t r=0;assert(!mp4_particle_source_policy_capture(particle,&r));++cases;}
 {reset();put(modules,0x430,(uintptr_t)native);capture();assert(owner().policy);++cases;}
 {reset();put(modules,0x430,uintptr_t(1));uint64_t r=0;assert(!mp4_particle_source_policy_capture(particle,&r));++cases;}
 {reset();capture();auto o=owner();o.policy++;uint64_t r=0;assert(!mp4_particle_source_policy_owned(o,&r)&&!r);++cases;}
 {reset();capture();auto o=owner();finish_current=false;uint64_t r=0;assert(mp4_particle_source_policy_owned(o,&r)&&r&&!mp4_particle_source_policy_current(o,&r));++cases;}
 {reset();capture();auto o=owner();put(state,0x1d0,uint64_t(3));uint64_t r=0;assert(mp4_particle_source_policy_current(o,&r));++cases;}
 {reset();capture();auto o=owner();put(modules,0x11d0,uint8_t(1));uint64_t r=0;assert(!mp4_particle_source_policy_owned(o,&r));++cases;}
 {reset();capture();auto o=owner();idoly_mp4_runtime::job.generation++;uint64_t r=0;assert(!mp4_particle_source_policy_owned(o,&r));++cases;}
 {reset();capture();auto o=owner();mp4_stage_host.source.generation++;uint64_t r=0;assert(!mp4_particle_source_policy_current(o,&r));++cases;}
 {reset();capture();auto o=owner();put(rnative,8,int32_t(20));uint64_t r=0;assert(!mp4_particle_source_policy_current(o,&r));++cases;}
 {reset();capture();auto o=owner();put(native,0x50,(uintptr_t)state);uint64_t r=0;assert(!mp4_particle_source_policy_owned(o,&r));++cases;}
 {reset();capture();auto o=owner();put(native,0x30,(uintptr_t)rnative);uint64_t r=0;assert(!mp4_particle_source_policy_owned(o,&r));++cases;}
 {reset();array_count=0;uint64_t r=0;assert(!mp4_particle_source_policy_capture(particle,&r));++cases;}
 {reset();array_count=2;put(array,sizeof(void*),renderer);uint64_t r=0;assert(!mp4_particle_source_policy_capture(particle,&r));++cases;}
 {reset();mp4_native_profile.native_sha256="other";uint64_t r=0;assert(!mp4_particle_source_policy_capture(particle,&r));++cases;}
 {reset();capture();auto o=owner();source=false;uint64_t r=0;assert(!mp4_particle_source_policy_owned(o,&r));++cases;}
 {reset();capture();auto o=owner();roots.erase(mp4_particle_source_policies[0].roots[1]);uint64_t r=0;assert(!mp4_particle_source_policy_owned(o,&r));++cases;}
 {reset();uint64_t a=capture(),b=0;assert(!mp4_particle_source_policy_capture(particle,&b)&&!b);mp4_particle_source_policy_clear();Mp4ParticleFinishReceipt f{};assert(mp4_particle_finish_issue(particle,61,&f));assert(capture()>a);++cases;}
 {reset();auto count=roots.size();retain_fail=true;uint64_t r=0;assert(!mp4_particle_source_policy_capture(particle,&r));retain_fail=false;assert(roots.size()==count);++cases;}
 mp4_particle_source_policy_clear();if(mp4_particle_source_renderer_type){weak_free(mp4_particle_source_renderer_type);mp4_particle_source_renderer_type=0;}::free(mp4_particle_source_policies);mp4_particle_source_policies=nullptr;assert(roots.empty());std::printf("%u real SourcePolicy/Finish host cases passed\n",cases);
}

#endif
