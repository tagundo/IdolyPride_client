#define MP4_PARTICLE_POLICY_NO_MAIN
#include "particle-source-policy-host-harness.cpp"
#include "renderer-scene-order.hpp.inc"
namespace mp4ro=idoly_mp4_renderer_scene_order;
struct{const char*sha256="native";uintptr_t singleton=0;Mp4ParticlePolicyCode get{},remove_record{},flush{};}mp4_renderer_scene_order_pins;
bool mp4_actor_mapped(const void*p,size_t n,bool){return mapped(p,n);}bool mp4_actor_refresh_maps(){return true;}
#include "renderer-scene-order-host.cpp.inc"
bool scene_quiet=true,restore_active=false,cache_current=true,read_change_id=false,getter_expire=false;
unsigned local_gets=0,world_gets=0,local_sets=0,world_sets=0,local_resets=0,world_resets=0;
void*scene=nullptr,*singleton=nullptr,*records=nullptr,*rowbounds=nullptr,*visibility=nullptr,*foreign=nullptr,*foreign_go=nullptr;
bool dirty=false,local_no_write=false,world_no_write=false;
struct Value{float v[6];};Value auto_local{{1,2,3,4,5,6}},auto_world{{7,8,9,4,5,6}};
void dirty_publish(){if(!dirty)return;int32_t i=-1;assert(mp4_actor_field(rnative,0x168,i));if(i>=0){float f[6]={20,21,22,23,24,25};::memcpy((uint8_t*)rowbounds+i*24,f,24);put(visibility,i,uint8_t(2));}dirty=false;}
void original_local_get(void*n,void*out){assert(n==rnative);++local_gets;if(local_no_write)return;uint32_t flags=0;assert(mp4_actor_field(n,0x128,flags));if(!(flags&0x800000u))::memcpy((uint8_t*)n+0xd8,&auto_local,24);dirty_publish();::memcpy(out,(uint8_t*)n+0xd8,24);if(read_change_id)put(n,8,int32_t(999));if(getter_expire)finish_current=false;}
void original_world_get(void*n,void*out){assert(n==rnative);++world_gets;if(world_no_write)return;uint32_t flags=0;assert(mp4_actor_field(n,0x128,flags));if(!(flags&0x1000000u))::memcpy((uint8_t*)n+0xc0,&auto_world,24);dirty_publish();::memcpy(out,(uint8_t*)n+0xc0,24);}
void original_local_set(void*n,const void*in){assert(n==rnative);++local_sets;uint32_t flags=0;assert(mp4_actor_field(n,0x128,flags));put(n,0x128,flags|0x800000u);::memcpy((uint8_t*)n+0xd8,in,24);dirty=true;}
void original_world_set(void*n,const void*in){assert(n==rnative);++world_sets;uint32_t flags=0;assert(mp4_actor_field(n,0x128,flags));put(n,0x128,flags|0x1000000u);::memcpy((uint8_t*)n+0xc0,in,24);dirty=true;}
void original_local_reset(void*n){++local_resets;uint32_t flags=0;assert(mp4_actor_field(n,0x128,flags));put(n,0x128,flags&~0x800000u);dirty=true;}
void original_world_reset(void*n){++world_resets;uint32_t flags=0;assert(mp4_actor_field(n,0x128,flags));put(n,0x128,flags&~0x1000000u);dirty=true;}
bool mp4_particle_native_restore_current(uint64_t r){return restore_active&&r==73&&scene_quiet&&finish_current;}
bool mp4_builtin_mesh_cache_current(void*r,uintptr_t n,int32_t id,uint64_t plan,uint64_t cache,uint64_t exclusion,float out[6]){if(!cache_current||r!=renderer||n!=(uintptr_t)rnative||id!=19||plan!=79||cache!=83||exclusion!=61||!finish_current)return false;for(int i=0;i<6;++i)out[i]=0;return true;}
#include "particle-renderer-bounds-host.inc"
bool fence(uint64_t epoch,uint64_t cap){return scene_quiet&&finish_current&&epoch==7&&cap==89;}bool restoring(uint64_t epoch,uint64_t r){return epoch==7&&mp4_particle_native_restore_current(r);}
void bind(Mp4ParticlePolicyCode&b,uintptr_t ptr){b.rva=ptr-1;::memcpy(b.prefix,(void*)ptr,16);regions.push_back({ptr,16});}
void extra_setup(){scene=alloc(0x100);singleton=alloc(8);records=alloc(3*24);rowbounds=alloc(3*24);visibility=alloc(3);foreign=alloc(0x850);foreign_go=alloc(0x50);put(foreign,0,(uintptr_t)vtable);put((uint8_t*)foreign+0x38,0,(uintptr_t)vtable);put(foreign,8,int32_t(101));put(foreign_go,8,int32_t(103));put(foreign,0x30,(uintptr_t)foreign_go);}
void row(void*n,int i){put(n,0x168,int32_t(i));put(n,0x1b4,uint8_t(1));put(n,0x1b5,uint8_t(1));put(records,i*24,(uintptr_t)n+0x38);}
void extra_reset(bool active=true,uint32_t flags=0){reset();scene_quiet=cache_current=true;restore_active=read_change_id=getter_expire=dirty=local_no_write=world_no_write=false;local_gets=world_gets=local_sets=world_sets=local_resets=world_resets=0;::memset(scene,0,0x100);::memset(records,0,3*24);::memset(rowbounds,0,3*24);::memset(visibility,0,3);put(singleton,0,(uintptr_t)scene);mp4_renderer_scene_order_pins.singleton=(uintptr_t)singleton-1;
 for(auto*p:{&mp4_renderer_scene_order_pins.get,&mp4_renderer_scene_order_pins.remove_record,&mp4_renderer_scene_order_pins.flush}){p->rva=(uintptr_t)code-1;::memset(p->prefix,0,16);}put(scene,0x88,(uintptr_t)records);put(scene,0xa8,(uintptr_t)rowbounds);put(scene,0xc8,(uintptr_t)visibility);uint64_t count=active?2:1;for(size_t off:{0x88u,0xa8u,0xc8u}){put(scene,off+16,count);put(scene,off+24,uint64_t(6));}
 put(rnative,0x128,flags);put(rnative,0x38,(uintptr_t)vtable);put(rnative,0xd8,Value{{1,2,3,4,5,6}});put(rnative,0xc0,Value{{7,8,9,4,5,6}});row(foreign,0);if(active)row(rnative,1);else put(rnative,0x168,int32_t(-1));for(int i=0;i<6;++i){put(rowbounds,i*4,float(i+100));put(rowbounds,24+i*4,float(i+200));}put(visibility,0,uint8_t(5));put(visibility,1,uint8_t(7));
 bind(mp4_particle_policy_pins.local_get,(uintptr_t)&original_local_get);bind(mp4_particle_policy_pins.world_get,(uintptr_t)&original_world_get);bind(mp4_particle_policy_pins.local_set,(uintptr_t)&original_local_set);bind(mp4_particle_policy_pins.world_set,(uintptr_t)&original_world_set);bind(mp4_particle_policy_pins.reset_local,(uintptr_t)&original_local_reset);bind(mp4_particle_policy_pins.reset_world,(uintptr_t)&original_world_reset);put(vtable,0x130,(uintptr_t)&original_local_set);put(vtable,0x138,(uintptr_t)&original_world_set);put(vtable,0x140,(uintptr_t)&original_local_reset);put(vtable,0x148,(uintptr_t)&original_world_reset);mp4_renderer_scene_order_context={7,89,fence,restoring};capture();}
Mp4ParticleRendererBounds take(){Mp4ParticleRendererBounds b{};assert(mp4_particle_renderer_bounds_capture(renderer,79,83,61,&b)&&b.captured);return b;}
#ifndef MP4_PARTICLE_BOUNDS_NO_MAIN
int main(){setup();extra_setup();unsigned cases=0;
 for(uint32_t flags:{0u,0x800000u,0x1000000u,0x1800000u}){extra_reset(true,flags);auto b=take();auto foreign_before=Value{};::memcpy(&foreign_before,rowbounds,24);put(rnative,0xd8,Value{{31,32,33,34,35,36}});put(rnative,0xc0,Value{{41,42,43,44,45,46}});::memset((uint8_t*)rowbounds+24,33,24);put(visibility,1,uint8_t(99));restore_active=true;assert(mp4_particle_renderer_bounds_restore(b,73,83,61)&&b.restored);assert(local_sets==1&&world_sets==1&&local_resets==unsigned(!(flags&0x800000u))&&world_resets==unsigned(!(flags&0x1000000u)));assert(!::memcmp(rowbounds,&foreign_before,24));++cases;}
 {extra_reset(false);auto b=take();restore_active=true;assert(!b.registered&&mp4_particle_renderer_bounds_restore(b,73,83,61));++cases;}
 {extra_reset();auto b=take();mp4ro::Row a{},z{};mp4ro::View v{};assert(mp4_renderer_scene_order_view(nullptr,&v));assert(mp4_renderer_scene_order_row(nullptr,v,0,&a)&&mp4_renderer_scene_order_row(nullptr,v,1,&z));restore_active=true;assert(mp4_renderer_scene_order_swap(nullptr,v,0,1,a,z,73));assert(mp4_particle_renderer_bounds_restore(b,73,83,61));int32_t at=-1;assert(mp4_actor_field(rnative,0x168,at)&&at==0);assert(!::memcmp(rowbounds,b.scene_bounds,24));++cases;}
 {extra_reset();auto b=take();assert(!mp4_particle_renderer_bounds_restore(b,73,83,61)&&!local_sets);++cases;}
 {extra_reset();auto b=take();restore_active=true;assert(!mp4_particle_renderer_bounds_restore(b,74,83,61)&&!local_sets);++cases;}
 {extra_reset();auto b=take();restore_active=true;finish_current=false;assert(!mp4_particle_renderer_bounds_restore(b,73,83,61)&&!local_sets);++cases;}
 {extra_reset();auto b=take();restore_active=true;cache_current=false;assert(!mp4_particle_renderer_bounds_restore(b,73,83,61));++cases;}
 {extra_reset();auto b=take();restore_active=true;assert(!mp4_particle_renderer_bounds_restore(b,73,84,61));++cases;}
 {extra_reset();auto b=take();restore_active=true;assert(!mp4_particle_renderer_bounds_restore(b,73,83,62));++cases;}
 {extra_reset();read_change_id=true;Mp4ParticleRendererBounds b{};assert(!mp4_particle_renderer_bounds_capture(renderer,79,83,61,&b));++cases;}
 {extra_reset();getter_expire=true;Mp4ParticleRendererBounds b{};assert(!mp4_particle_renderer_bounds_capture(renderer,79,83,61,&b));++cases;}
 {extra_reset();put(vtable,0x130,uintptr_t(1));Mp4ParticleRendererBounds b{};assert(!mp4_particle_renderer_bounds_capture(renderer,79,83,61,&b));++cases;}
 {extra_reset();auto b=take();b.policy++;restore_active=true;assert(!mp4_particle_renderer_bounds_restore(b,73,83,61)&&!local_sets);++cases;}
 {extra_reset();auto b=take();put(rnative,0x168,int32_t(-1));restore_active=true;assert(!mp4_particle_renderer_bounds_restore(b,73,83,61));++cases;}
 {extra_reset();auto b=take();restore_active=true;put(scene,0xf8,uint32_t(1));assert(!mp4_particle_renderer_bounds_restore(b,73,83,61));++cases;}
 {extra_reset();auto b=take();restore_active=true;put(scene,0x58,uint64_t(1));assert(!mp4_particle_renderer_bounds_restore(b,73,83,61));++cases;}
 {extra_reset();auto b=take();put(records,24,(uintptr_t)foreign+0x38);restore_active=true;assert(!mp4_particle_renderer_bounds_restore(b,73,83,61));++cases;}
 {extra_reset(true,0x800000u);Value invalid{{1,2,3,-1,2,3}};put(rnative,0xd8,invalid);Mp4ParticleRendererBounds b{};assert(!mp4_particle_renderer_bounds_capture(renderer,79,83,61,&b));++cases;}
 {extra_reset(true,0x800000u);Value invalid{{__builtin_inff(),2,3,1,2,3}};put(rnative,0xd8,invalid);Mp4ParticleRendererBounds b{};assert(!mp4_particle_renderer_bounds_capture(renderer,79,83,61,&b));++cases;}
 {extra_reset();local_no_write=true;Mp4ParticleRendererBounds b{};assert(!mp4_particle_renderer_bounds_capture(renderer,79,83,61,&b));++cases;}
 {extra_reset();world_no_write=true;Mp4ParticleRendererBounds b{};assert(!mp4_particle_renderer_bounds_capture(renderer,79,83,61,&b));++cases;}
 mp4_particle_source_policy_clear();if(mp4_particle_source_renderer_type)weak_free(mp4_particle_source_renderer_type);::free(mp4_particle_source_policies);assert(roots.empty());std::printf("%u actual PSR bounds/current-row cases passed\n",cases);
}

#endif
