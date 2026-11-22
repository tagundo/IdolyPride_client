#define MP4_PARTICLE_BOUNDS_NO_MAIN
#define MP4_PARTICLE_POLICY_NO_MAIN
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
bool mp4_particle_native_state_mapped(uintptr_t p,size_t n,bool=false){return mapped((void*)p,n);}bool mp4_native_mapped(uintptr_t p,size_t n,int){return mapped((void*)p,n);}
bool main_thread=true,source=true,held=true,verified=true,live=true,finish_current=true;bool game_call(){return main_thread;}bool mp4_alive(void*p){return live&&p&&mapped(p,24);}bool mp4_stage_owner(void*){return source;}bool mp4_actor_clock_held(void*){return held;}
void*particle=nullptr,*renderer=nullptr,*go=nullptr,*native=nullptr,*rnative=nullptr,*gnative=nullptr,*state=nullptr,*modules=nullptr,*parameters=nullptr,*parts=nullptr,*renderer_type=nullptr,*code=nullptr,*vtable=nullptr,*array=nullptr,*component_array=nullptr;
std::map<uint32_t,void*>roots;uint32_t root_next=1;unsigned retains=0,frees=0;bool retain_fail=false;
uint32_t mp4_retain(void*p){++retains;if(retain_fail||!p)return 0;roots[root_next]=p;return root_next++;}void*weak_get(uint32_t r){auto it=roots.find(r);return it==roots.end()?nullptr:it->second;}void weak_free(uint32_t r){++frees;roots.erase(r);}
struct Mp4ActorTempRoot{uint32_t root;explicit Mp4ActorTempRoot(void*p):root(mp4_retain(p)){}~Mp4ActorTempRoot(){if(root)weak_free(root);}void*get(){return weak_get(root);}};
namespace mp4game{struct Binding{uintptr_t rva=0;uint8_t prefix[16]{};};}struct Mp4TimelineTypePin{const char*name=nullptr;mp4game::Binding binding{};};
struct Mp4ParticlePolicyCode{uintptr_t rva=0;uint8_t prefix[16]{};};
struct{const char*sha256="native";uintptr_t renderer_vtable=0;Mp4TimelineTypePin renderer{};mp4game::Binding set_active{},render_mode{},global_block_get{},global_block_set{},shared_materials{};Mp4ParticlePolicyCode module_enabled{},params_policy{},module_roles{},local_get{},world_get{},local_set{},world_set{},reset_local{},reset_world{};}mp4_particle_policy_pins;
uintptr_t mp4_native_base=0,image_base=0;struct{const char*native_sha256="native";}mp4_native_profile;
bool mp4_source_verified=true,mp4_stage_source_verified=true;bool mp4_prefix(const mp4game::Binding&){return verified;}bool mp4_hook_was_statically_verified(const mp4game::Binding&){return verified;}
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
struct{const char*sha256="native";uintptr_t vtable=0,singleton=0;}mp4_particle_manager_pins;
struct Mp4ParticleStateNativeValue{uint8_t bytes[352]{};};
struct{uintptr_t rva=0;uint8_t prefix[16]{};}mp4_particle_state_pin;
unsigned finish_calls=0;Mp4ParticleStateNativeValue original_finish(void*){++finish_calls;put(native,0x6c,uint8_t(0));return{};}
// This harness executes the production typed C++ aggregate call at the actual
// function pointer. ARM entry pin/executable mapping are modeled separately.
#include "particle-native-finish-receipt-host.cpp.inc"
void*component_gameobject(void*p,Method*){return p==particle||p==renderer?go:nullptr;}
void*components_internal(void*object,void*type,bool b,bool recursive,bool inactive,bool reverse,void*result,Method*){assert(object==go&&type==renderer_type&&b&&!recursive&&inactive&&!reverse&&!result);return component_array;}
int32_t mode=0;int32_t render_mode(void*p,Method*){assert(p==renderer);return mode;}
struct{mp4game::Binding component_gameobject{},components_internal{};}mp4_stage_profile;
template<class T>T mp4_equipment_call(const mp4game::Binding&b){return reinterpret_cast<T>(image_base+b.rva);}
void*mp4_type_get_object(void*){return renderer_type;}size_t array_count=1;
bool mp4_stage_array(void*p,void***out,size_t*n,size_t limit){if(p==component_array){*out=reinterpret_cast<void**>(component_array);*n=1;return limit>=1;}if(p!=array||array_count>limit)return false;*out=reinterpret_cast<void**>(array);*n=array_count;return true;}
#include "particle-source-policy-host.inc"
bool exclusion(const Mp4ParticleFinishOwner&o,uint64_t b){return finish_current&&b==61&&o.managed==particle&&o.capture==public_capture;}
void setup(){particle=alloc(32);renderer=alloc(32);go=alloc(32);native=alloc(0xb0);rnative=alloc(0x850);gnative=alloc(0x50);state=alloc(0x220);modules=alloc(0x1490);parameters=alloc(0x60);parts=alloc(0x20);renderer_type=alloc(32);code=alloc(16);vtable=alloc(0x180);array=alloc(2*sizeof(void*));component_array=array;}
void reset(){array=component_array;main_thread=true;mp4_particle_source_policy_clear();mp4_particle_finish_reset();source=held=verified=live=finish_current=true;mp4_source_verified=mp4_stage_source_verified=true;retain_fail=false;mode=0;public_capture=13;public_restored=false;array_count=1;mp4_stage_host.source.generation=7;idoly_mp4_runtime::job.generation=11;mp4_native_profile.native_sha256="native";mp4_native_base=1;image_base=0;
 ::memset(state,0,0x220);::memset(modules,0,0x1490);::memset(parameters,0,0x60);put(particle,16,(uintptr_t)native);put(renderer,16,(uintptr_t)rnative);put(go,16,(uintptr_t)gnative);put(native,0,(uintptr_t)vtable);mp4_particle_manager_pins.vtable=(uintptr_t)vtable-1;put(native,8,int32_t(17));put(native,0x30,(uintptr_t)gnative);put(native,0x38,(uintptr_t)parts);put(native,0x40,(uintptr_t)parameters);put(native,0x48,(uintptr_t)state);put(native,0x50,(uintptr_t)modules);put(native,0x6c,uint8_t(0));put(rnative,0,(uintptr_t)vtable);put(rnative,8,int32_t(19));put(rnative,0x30,(uintptr_t)gnative);put(gnative,8,int32_t(23));put(modules,0x21c,uint32_t(4));put(array,0,renderer);
 mp4_particle_policy_pins.renderer_vtable=(uintptr_t)vtable-1;for(auto*p:{&mp4_particle_policy_pins.module_enabled,&mp4_particle_policy_pins.params_policy,&mp4_particle_policy_pins.module_roles}){p->rva=(uintptr_t)code-1;::memset(p->prefix,0,16);}mp4_stage_profile.component_gameobject.rva=(uintptr_t)&component_gameobject;mp4_stage_profile.components_internal.rva=(uintptr_t)&components_internal;mp4_particle_policy_pins.render_mode.rva=(uintptr_t)&render_mode;
 mp4_particle_state_pin.rva=(uintptr_t)&original_finish-1;::memcpy(mp4_particle_state_pin.prefix,(void*)&original_finish,16);regions.push_back({(uintptr_t)&original_finish,16});mp4_particle_finish_context.exclusion_current=exclusion;Mp4ParticleFinishReceipt f{};assert(mp4_particle_finish_issue(particle,61,&f)&&f.serial);}
uint64_t capture(){uint64_t r=0;assert(mp4_particle_source_policy_capture(particle,&r)&&r);return r;}
mp4ps::Owner owner(){mp4ps::Owner o{};assert(mp4_particle_source_policy_owner(particle,&o));return o;}

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
bool mp4_particle_native_restore_current(uint64_t);
bool mp4_builtin_mesh_cache_current(void*,uintptr_t,int32_t,uint64_t,uint64_t,uint64_t,float[6]);
#include "particle-renderer-bounds-host.inc"
bool fence(uint64_t epoch,uint64_t cap){return scene_quiet&&finish_current&&epoch==7&&cap==89;}bool restoring(uint64_t epoch,uint64_t r){return epoch==7&&mp4_particle_native_restore_current(r);}
void bind(Mp4ParticlePolicyCode&b,uintptr_t ptr){b.rva=ptr-1;::memcpy(b.prefix,(void*)ptr,16);regions.push_back({ptr,16});}
void extra_setup(){scene=alloc(0x100);singleton=alloc(8);records=alloc(3*24);rowbounds=alloc(3*24);visibility=alloc(3);foreign=alloc(0x850);foreign_go=alloc(0x50);put(foreign,0,(uintptr_t)vtable);put((uint8_t*)foreign+0x38,0,(uintptr_t)vtable);put(foreign,8,int32_t(101));put(foreign_go,8,int32_t(103));put(foreign,0x30,(uintptr_t)foreign_go);}
void row(void*n,int i){put(n,0x168,int32_t(i));put(n,0x1b4,uint8_t(1));put(n,0x1b5,uint8_t(1));put(records,i*24,(uintptr_t)n+0x38);}
void extra_reset(bool active=true,uint32_t flags=0){reset();scene_quiet=cache_current=true;restore_active=read_change_id=getter_expire=dirty=local_no_write=world_no_write=false;local_gets=world_gets=local_sets=world_sets=local_resets=world_resets=0;::memset(scene,0,0x100);::memset(records,0,3*24);::memset(rowbounds,0,3*24);::memset(visibility,0,3);put(singleton,0,(uintptr_t)scene);mp4_renderer_scene_order_pins.singleton=(uintptr_t)singleton-1;
 for(auto*p:{&mp4_renderer_scene_order_pins.get,&mp4_renderer_scene_order_pins.remove_record,&mp4_renderer_scene_order_pins.flush}){p->rva=(uintptr_t)code-1;::memset(p->prefix,0,16);}put(scene,0x88,(uintptr_t)records);put(scene,0xa8,(uintptr_t)rowbounds);put(scene,0xc8,(uintptr_t)visibility);uint64_t count=active?2:1;for(size_t off:{0x88u,0xa8u,0xc8u}){put(scene,off+16,count);put(scene,off+24,uint64_t(6));}
 put(rnative,0x128,flags);put(rnative,0x38,(uintptr_t)vtable);put(rnative,0xd8,Value{{1,2,3,4,5,6}});put(rnative,0xc0,Value{{7,8,9,4,5,6}});row(foreign,0);if(active)row(rnative,1);else put(rnative,0x168,int32_t(-1));for(int i=0;i<6;++i){put(rowbounds,i*4,float(i+100));put(rowbounds,24+i*4,float(i+200));}put(visibility,0,uint8_t(5));put(visibility,1,uint8_t(7));
 bind(mp4_particle_policy_pins.local_get,(uintptr_t)&original_local_get);bind(mp4_particle_policy_pins.world_get,(uintptr_t)&original_world_get);bind(mp4_particle_policy_pins.local_set,(uintptr_t)&original_local_set);bind(mp4_particle_policy_pins.world_set,(uintptr_t)&original_world_set);bind(mp4_particle_policy_pins.reset_local,(uintptr_t)&original_local_reset);bind(mp4_particle_policy_pins.reset_world,(uintptr_t)&original_world_reset);put(vtable,0x130,(uintptr_t)&original_local_set);put(vtable,0x138,(uintptr_t)&original_world_set);put(vtable,0x140,(uintptr_t)&original_local_reset);put(vtable,0x148,(uintptr_t)&original_world_reset);mp4_renderer_scene_order_context={7,89,fence,restoring};}
Mp4ParticleRendererBounds take(){Mp4ParticleRendererBounds b{};assert(mp4_particle_renderer_bounds_capture(renderer,79,83,61,&b)&&b.captured);return b;}

#include <set>
struct Material{void*shader=nullptr;std::map<int,int>properties;};struct Block{std::map<int,int>properties;};
void*shader=nullptr,*source_material=nullptr,*material_array=nullptr,*renderer_array=nullptr,*global_native=nullptr;
std::map<int,int>current_block;bool current_present=false,cleanup_allowed=true;unsigned copies=0,disposals=0,destroys=0;std::set<void*>private_materials,private_blocks;
void*material_shader(void*m,Method*){return static_cast<Material*>(m)->shader;}
void*material_new(void*s){auto*m=new Material;m->shader=s;regions.push_back({(uintptr_t)m,sizeof *m});extra_types[m]="UnityEngine.Material";private_materials.insert(m);return m;}
void material_copy(void*to,void*from,Method*){static_cast<Material*>(to)->properties=static_cast<Material*>(from)->properties;++copies;}
void material_destroy(void*p){assert(private_materials.erase(p)==1);extra_types.erase(p);delete static_cast<Material*>(p);++destroys;}
void*block_new(){auto*p=new Block;regions.push_back({(uintptr_t)p,sizeof *p});extra_types[p]="UnityEngine.MaterialPropertyBlock";private_blocks.insert(p);return p;}
bool block_valid(void*p){return private_blocks.count(p);}bool block_empty(void*p,Method*){assert(block_valid(p));return static_cast<Block*>(p)->properties.empty();}
void block_dispose(void*p,Method*){assert(private_blocks.erase(p)==1);extra_types.erase(p);delete static_cast<Block*>(p);++disposals;}
void global_get(void*r,void*b,Method*){assert(r==renderer&&block_valid(b));static_cast<Block*>(b)->properties=current_present?current_block:std::map<int,int>{};}
void global_set(void*r,void*b,Method*){assert(r==renderer);current_present=b!=nullptr;current_block=b?static_cast<Block*>(b)->properties:std::map<int,int>{};put(rnative,0x138,b?(uintptr_t)global_native:0);}
void*shared_materials(void*r,Method*){assert(r==renderer);return array;}
struct Images{void*(*material_shader)(void*,Method*)=nullptr;void*(*material_new)(void*)=nullptr;void(*material_copy)(void*,void*,Method*)=nullptr;void(*material_destroy)(void*)=nullptr;void*(*block_new)()=nullptr;bool(*block_valid)(void*)=nullptr;bool(*block_empty)(void*,Method*)=nullptr;void(*block_dispose)(void*,Method*)=nullptr;};
struct PresentationApi{Images images;};PresentationApi mp4_actor_presentation_api(void*){return{{material_shader,material_new,material_copy,material_destroy,block_new,block_valid,block_empty,block_dispose}};}
bool mp4_actor_global_block_presence(void*r,int32_t slot,bool*out){if(!out||r!=renderer||slot!=-1)return false;uintptr_t p=0;if(!mp4_actor_field(rnative,0x138,p))return false;*out=p!=0;return true;}

#include "particle-renderer-presentation-host.inc"
void present_setup(){shader=alloc(32);extra_types[shader]="UnityEngine.Shader";source_material=new Material;regions.push_back({(uintptr_t)source_material,sizeof(Material)});extra_types[source_material]="UnityEngine.Material";static_cast<Material*>(source_material)->shader=shader;material_array=alloc(2*sizeof(void*));global_native=alloc(32);renderer_array=array;}
void present_reset(bool present,bool empty){array=renderer_array;extra_reset();cleanup_allowed=true;copies=disposals=destroys=0;current_present=present;current_block.clear();if(!empty)current_block={{1,41},{2,43}};put(rnative,0x138,present?(uintptr_t)global_native:0);array=material_array;array_count=1;put(array,0,source_material);static_cast<Material*>(source_material)->shader=shader;static_cast<Material*>(source_material)->properties={{3,47},{4,53}};mp4_particle_policy_pins.global_block_get.rva=(uintptr_t)&global_get;mp4_particle_policy_pins.global_block_set.rva=(uintptr_t)&global_set;mp4_particle_policy_pins.shared_materials.rva=(uintptr_t)&shared_materials;}
uint64_t active_boundary=61;
namespace mp4actor{struct Handle{uintptr_t handle=0;uint32_t version=0,padding=0;};}
bool mp4_actor_same_handle(mp4actor::Handle a,mp4actor::Handle b){return a.handle==b.handle&&a.version==b.version;}
enum class Mp4ControlSourceRole:uint8_t{director,activation,particle};
struct Mp4ControlSourceLeaf{mp4actor::Handle node{};void*script=nullptr,*target=nullptr;uint32_t seed=0;Mp4ControlSourceRole role=Mp4ControlSourceRole::particle;};
struct Mp4TimelineContext{Mp4SceneWitness witness{};void*director=nullptr,*asset=nullptr;mp4actor::Handle graph{};};
struct AdmissionEntry{struct{void*particle=nullptr,*producer=nullptr;uint32_t producer_kind=1;}owner{};uintptr_t particle_native=0;int32_t particle_id=0;void*particle_go=nullptr;mp4actor::Handle node{};};
struct{AdmissionEntry particles[2]{};size_t count=1;uint64_t receipt=17;bool committed=true;}mp4_stage_admission_particles;
bool admission=true,resolved=true,capable=true,context_match=true;
bool mp4_stage_admission_source(const Mp4SceneWitness&w){return admission&&source&&w.generation==7;}
bool mp4_stage_admission_identity(const AdmissionEntry&e){return admission&&e.owner.particle==particle&&e.particle_native==(uintptr_t)native&&e.particle_id==17;}
bool mp4_stage_admission_resolve(const AdmissionEntry&e,mp4actor::Handle*out){if(!resolved||!mp4_stage_admission_identity(e))return false;*out=e.node;return true;}
bool mp4_stage_admission_particle(const Mp4SceneWitness&w,void*d,void*a,mp4actor::Handle g,mp4actor::Handle node,void*script,void*p,uint32_t seed){const auto&e=mp4_stage_admission_particles.particles[0];return context_match&&mp4_stage_admission_particles.committed&&mp4_stage_admission_source(w)&&d==go&&a==renderer_type&&g.handle==101&&g.version==2&&mp4_actor_same_handle(node,e.node)&&script==e.owner.producer&&p==particle&&seed==77;}
struct Mp4BuiltinSource{void*particle=nullptr,*renderer=nullptr;uintptr_t native=0;int32_t instance=0;uint32_t path=0;uint64_t receipt=0;};
struct{bool(*source_current)(const Mp4BuiltinSource&)=nullptr;bool(*held_current)(const Mp4BuiltinSource&,uint64_t)=nullptr;}mp4_builtin_context;
struct BuiltinPlan{Mp4BuiltinSource source{};uint64_t receipt=0;}builtin_plan;
uint32_t expected_path=0;uint64_t nextplan=91;
bool mp4_builtin_plan_create(const Mp4BuiltinSource&s,uint64_t*out){*out=0;if(s.path!=expected_path||!mp4_builtin_context.source_current||!mp4_builtin_context.source_current(s))return false;builtin_plan={s,++nextplan};*out=builtin_plan.receipt;return true;}
const BuiltinPlan*mp4_builtin_plan_current(void*r,uint64_t plan){return plan&&plan==builtin_plan.receipt&&r==renderer&&mp4_builtin_context.source_current&&mp4_builtin_context.source_current(builtin_plan.source)?&builtin_plan:nullptr;}
bool mp4_particle_mutation_exclusion(const Mp4ParticleFinishOwner&o,uint64_t e){return finish_current&&e==active_boundary&&o.managed==particle;}
bool mp4_particle_native_capability();
#include "particle-source-program-host.inc"
void*script=nullptr;Mp4TimelineContext context{};Mp4ControlSourceLeaf leaf{};
void program_setup(){script=alloc(32);}
void program_reset(){mp4_particle_source_program_clear();reset();admission=resolved=capable=context_match=true;expected_path=0;builtin_plan={};mp4_stage_admission_particles={};mp4_stage_admission_particles.count=1;mp4_stage_admission_particles.receipt=17;mp4_stage_admission_particles.committed=true;mp4_stage_admission_particles.particles[0]={{particle,script,1},(uintptr_t)native,17,go,{103,2,0}};context={{7},go,renderer_type,{101,2,0}};leaf={{103,2,0},script,particle,77,Mp4ControlSourceRole::particle};}
uint64_t create(){uint64_t r=0;assert(mp4_particle_source_program_create(context,leaf,&r)&&r);return r;}

int mp4_builtin_android_pins=0,mp4_builtin_ios_pins=0;
enum class Mp4SceneResult:int{ok=0,waiting=1,unsupported=-1,invalid=-2,failed=-3,stale=-4};
struct{Mp4SceneWitness source{};bool active=true;unsigned restored=0,all=15;}mp4_scene_host;
unsigned mp4_owned_render_depth=0,mp4_unowned_render_depth=0;bool mp4_owned_render_ticket_active=false;
namespace mp4_gpu_fence{enum class Result{ready,waiting,quarantined};}
struct Ledger{bool wait=false,bad=false;unsigned polls=0,retires=0;mp4_gpu_fence::Result poll(uint64_t,uint64_t){++polls;return bad?mp4_gpu_fence::Result::quarantined:wait?mp4_gpu_fence::Result::waiting:mp4_gpu_fence::Result::ready;}bool retire_sequence(uint64_t,uint64_t){++retires;return !bad&&!wait;}};
struct GPU{bool configured=false,draw=false;uint64_t source=7,epoch=11,retired=0,sequence=0;Ledger ledger;}mp4_gpu_fence_host,mp4_gpu_auxiliary_host;
struct{unsigned depth=0;}mp4_raw_original_operation;struct{bool active=false;}mp4_rebuild_ledger;
struct{bool active=false;unsigned depth=0;uint64_t generation=1;}mp4_particle_mutation_host;
struct{uint64_t serial=61,generation=1;}mp4_particle_mutation_boundary;
bool mp4_particle_mutation_bindings(){return verified;}
bool mutation_good=true;bool mp4_particle_mutation_source(){return mutation_good&&source&&mp4_particle_mutation_host.active;}
bool mp4_particle_mutation_closed(){return mp4_particle_mutation_source()&&!mp4_particle_mutation_host.depth&&!mp4_raw_original_operation.depth&&!mp4_rebuild_ledger.active;}
bool mp4_particle_mutation_capture(){mp4_particle_mutation_host.active=true;return mutation_good;}
void mp4_particle_mutation_clear(){mp4_particle_mutation_host.active=false;}
uint64_t mp4_particle_mutation_issue_boundary(){if(!mp4_particle_mutation_closed())return 0;active_boundary=++mp4_particle_mutation_boundary.serial;mp4_particle_mutation_boundary.generation=mp4_particle_mutation_host.generation;return active_boundary;}
using Mp4ParticleSimulate=void(*)(void*,float,bool,bool,bool,Method*);
void dummy_simulate(void*,float,bool,bool,bool,Method*){}Mp4ParticleSimulate mp4_particle_simulate_original=dummy_simulate;
using Mp4SourceGameObjectActive=void(*)(void*,bool,Method*);void dummy_active(void*,bool,Method*){}Mp4SourceGameObjectActive mp4_source_game_object_active_original=dummy_active;
#include "particle-manager-scope.hpp.inc"
namespace mp4pm=idoly_mp4_particle_manager;
struct Mp4ParticleManagerContext {
 uint64_t epoch=0,capture=0;
 // Actual continuously-held Stage/NativeParticle job + registry fence. These
 // are real receipt providers, not Clock.held()/selected native epoch aliases.
 bool(*fence_current)(uint64_t,uint64_t)=nullptr;
 bool(*restore_current)(uint64_t,uint64_t)=nullptr;
}mp4_particle_manager_context;
bool mp4_particle_manager_current(void*,uint64_t epoch){auto&c=mp4_particle_manager_context;
 return game_call()&&c.epoch==epoch&&c.capture&&mp4_stage_owner(nullptr)&&mp4_native_base
  &&mp4_native_profile.native_sha256&&!std::strcmp(mp4_native_profile.native_sha256,mp4_particle_manager_pins.sha256);}
bool mp4_particle_manager_held(void*){auto&c=mp4_particle_manager_context;
 return mp4_particle_manager_current(nullptr,c.epoch)&&mp4_actor_clock_held(nullptr)&&c.fence_current&&c.fence_current(c.epoch,c.capture);}
bool mp4_particle_manager_member_identity(uintptr_t native,mp4pm::Member*out){
 if(!out||!native||!mp4_actor_mapped(reinterpret_cast<void*>(native),0xa8,false))return false;
 uintptr_t vtable=0;int32_t instance=0;
 if(!mp4_actor_field(reinterpret_cast<void*>(native),0,vtable)||vtable!=mp4_native_base+mp4_particle_manager_pins.vtable
  ||!mp4_actor_field(reinterpret_cast<void*>(native),8,instance)||!instance)return false;
 *out={native,instance};return true;
}
bool mp4_particle_manager_view(void*,unsigned which,mp4pm::View*out){
 if(!out||which>1||!mp4_particle_manager_held(nullptr))return false;
 *out={};
 uintptr_t manager=0,data=0;uint64_t count=0,encoded=0;const uintptr_t global=mp4_native_base+mp4_particle_manager_pins.singleton;
 if(!mp4_actor_mapped(reinterpret_cast<void*>(global),8,false)||!mp4_actor_field(reinterpret_cast<void*>(global),0,manager)
  ||!manager||!mp4_actor_mapped(reinterpret_cast<void*>(manager),64,false))return false;
 const size_t at=which?32:0;
 if(!mp4_actor_field(reinterpret_cast<void*>(manager),at,data)||!mp4_actor_field(reinterpret_cast<void*>(manager),at+16,count)
  ||!mp4_actor_field(reinterpret_cast<void*>(manager),at+24,encoded)||count>(encoded>>1)||(encoded>>1)>mp4pm::max_rows
  ||count>mp4pm::max_rows||(count&&(!data||(data&7)||!mp4_actor_mapped(reinterpret_cast<void*>(data),count*8,false))))return false;
 *out={manager,data,static_cast<size_t>(count),static_cast<size_t>(encoded>>1)};return true;
}
bool mp4_particle_manager_same_view(unsigned which,const mp4pm::View&v){mp4pm::View now{};return mp4_particle_manager_view(nullptr,which,&now)
 &&now.manager==v.manager&&now.data==v.data&&now.count==v.count&&now.capacity==v.capacity;}
bool mp4_particle_manager_member(void*,const mp4pm::View&v,size_t row,mp4pm::Member*out){
 if(!out||row>=v.count||!mp4_particle_manager_held(nullptr))return false;
 uintptr_t native=0;
 return mp4_actor_mapped(reinterpret_cast<void*>(v.data),v.count*8,false)
  &&mp4_actor_field(reinterpret_cast<void*>(v.data),row*8,native)&&mp4_particle_manager_member_identity(native,out);
}
bool mp4_particle_manager_index(void*,mp4pm::Member m,int32_t*out){mp4pm::Member actual{};
 return out&&mp4_particle_manager_held(nullptr)&&mp4_particle_manager_member_identity(m.native,&actual)&&mp4pm::same(actual,m)
  &&mp4_actor_field(reinterpret_cast<void*>(m.native),0x68,*out);}
bool mp4_particle_manager_restore_current(void*,uint64_t epoch,uint64_t restore){auto&c=mp4_particle_manager_context;
 return mp4_particle_manager_current(nullptr,epoch)&&mp4_particle_manager_held(nullptr)&&restore&&c.restore_current&&c.restore_current(epoch,restore);}
bool mp4_particle_manager_write_row(void*,const mp4pm::View&v,size_t row,mp4pm::Member m,uint64_t restore){
 mp4pm::Member actual{};if(row>=v.count||!mp4_particle_manager_restore_current(nullptr,mp4_particle_manager_context.epoch,restore)||!mp4_particle_manager_member_identity(m.native,&actual)||!mp4pm::same(actual,m)
  ||(!mp4_particle_manager_same_view(0,v)&&!mp4_particle_manager_same_view(1,v))
  ||!mp4_actor_mapped(reinterpret_cast<void*>(v.data+row*8),8,true))return false;
 ::memcpy(reinterpret_cast<void*>(v.data+row*8),&m.native,8);return true;
}
bool mp4_particle_manager_write_index(void*,mp4pm::Member m,int32_t index,uint64_t restore){
 mp4pm::Member actual{};if(index<0||static_cast<size_t>(index)>=mp4pm::max_rows||!mp4_particle_manager_restore_current(nullptr,mp4_particle_manager_context.epoch,restore)
  ||!mp4_particle_manager_member_identity(m.native,&actual)||!mp4pm::same(actual,m)
  ||!mp4_actor_mapped(reinterpret_cast<void*>(m.native+0x68),4,true))return false;
 ::memcpy(reinterpret_cast<void*>(m.native+0x68),&index,4);return true;
}
mp4pm::Api mp4_particle_manager_api(){mp4pm::Api a{};a.current=mp4_particle_manager_current;a.held=mp4_particle_manager_held;
 a.view=mp4_particle_manager_view;a.member=mp4_particle_manager_member;a.index=mp4_particle_manager_index;
 a.write_row=mp4_particle_manager_write_row;a.write_index=mp4_particle_manager_write_index;a.restoration=mp4_particle_manager_restore_current;return a;}
bool mp4_particle_manager_finish_member(mp4pm::Member member){
 if(!mp4_particle_manager_current(nullptr,mp4_particle_manager_context.epoch)||!mp4_actor_clock_held(nullptr))return false;
 mp4pm::Member current{};if(!mp4_particle_manager_member_identity(member.native,&current)||!mp4pm::same(current,member))return false;
 const auto&pin=mp4_particle_state_pin;const uintptr_t entry=mp4_native_base+pin.rva;
 if(!mp4_native_mapped(entry,16,5)||::memcmp(reinterpret_cast<void*>(entry),pin.prefix,16))return false;
 using NativeGet=Mp4ParticleStateNativeValue(*)(void*);
 const auto state=reinterpret_cast<NativeGet>(entry)(reinterpret_cast<void*>(member.native));
 // Original GetPlaybackState completes handle70 and pending6c first. Actual
 // native scaled/unscaled delta are both held at zero, so it cannot enter the
 // deferred Simulate branch. No Play/Step/setter manufactures this boundary.
 volatile uint8_t sampled=state.bytes[0];(void)sampled;
 uint8_t pending=1;return mp4_particle_manager_current(nullptr,mp4_particle_manager_context.epoch)
  &&mp4_actor_clock_held(nullptr)&&mp4_particle_manager_member_identity(member.native,&current)&&mp4pm::same(current,member)
  &&mp4_actor_field(reinterpret_cast<void*>(member.native),0x6c,pending)&&pending==0;
}
struct Mp4ParticleNativeStateContext{
 const mp4ps::Owner*owners=nullptr;size_t count=0;
 // Genuine retained selected-asset/native policy receipt and original native
 // GetPlaybackState completion +no-later-scheduling fence. These providers
 // cannot be replaced by a public snapshot receipt or selected epoch.
 bool(*source_policy)(const mp4ps::Owner&,uint64_t*)=nullptr;
 bool(*fence_current)(const mp4ps::Owner&)=nullptr;
 bool(*restore_current)(const mp4ps::Owner&,uint64_t)=nullptr;
}mp4_particle_native_state_context;
bool mp4_particle_native_state_held(void*){const auto&c=mp4_particle_native_state_context;return game_call()&&mp4_stage_owner(nullptr)&&mp4_actor_clock_held(nullptr)
 &&mp4_native_base&&mp4_native_profile.native_sha256&&!::strcmp(mp4_native_profile.native_sha256,mp4_particle_manager_pins.sha256)
 &&c.owners&&c.count&&c.count<=256&&c.source_policy&&c.fence_current&&c.restore_current;}
bool mp4_particle_native_state_source(void*managed,mp4ps::Owner*out,bool*restored){if(!out||!restored||!mp4_particle_native_state_held(nullptr))return false;
 *out={};*restored=false;
 idoly_mp4_stage::Owner public_owner{};uint64_t capture=0;bool public_restored=false;
 if(!mp4_type_is(managed,"UnityEngine.ParticleSystem")||!mp4_alive(managed)
 ||!mp4_stage_particles.snapshot_receipt(managed,&public_owner,&capture,&public_restored)||public_owner.particle!=managed||!capture)return false;
 mp4ps::Owner o{};o.managed=managed;o.capture=capture;uintptr_t table=0;uint8_t pending=1;
 if(!mp4_actor_field(managed,16,o.native)||!mp4_particle_native_state_mapped(o.native,0xa8)
 ||!mp4_actor_field(reinterpret_cast<void*>(o.native),0,table)||table!=mp4_native_base+mp4_particle_manager_pins.vtable
 ||!mp4_actor_field(reinterpret_cast<void*>(o.native),8,o.instance)||!o.instance
 ||!mp4_actor_field(reinterpret_cast<void*>(o.native),0x38,o.particles)||!mp4_particle_native_state_mapped(o.particles,0x18)
 ||!mp4_actor_field(reinterpret_cast<void*>(o.native),0x40,o.parameters)||!mp4_particle_native_state_mapped(o.parameters,0x40)
 ||!mp4_actor_field(reinterpret_cast<void*>(o.native),0x48,o.state)||!mp4_particle_native_state_mapped(o.state,0x220)
 ||!mp4_actor_field(reinterpret_cast<void*>(o.native),0x50,o.modules)||!mp4_particle_native_state_mapped(o.modules,0x12b0)
 ||!mp4_actor_field(reinterpret_cast<void*>(o.native),0x6c,pending)||pending
 ||!mp4_particle_native_state_context.source_policy(o,&o.policy)||!o.policy
 ||!mp4_particle_native_state_context.fence_current(o))return false;
 *out=o;*restored=public_restored;return true;
}
bool mp4_particle_native_state_current(void*,const mp4ps::Owner&o,mp4ps::Owner*out,bool*restored){
 return mp4_particle_native_state_source(o.managed,out,restored)&&mp4ps::same(o,*out);}
bool mp4_particle_native_state_policy(void*,const mp4ps::Owner&o){mp4ps::Owner current{};bool restored=false;
 if(!mp4_particle_native_state_source(o.managed,&current,&restored)||!mp4ps::same(current,o))return false;
 // Source primitive-shape branch skips all mesh selection. The cached mesh
 // and listener must also be NULL; checking the shape enum alone is unsafe.
 uint32_t shape=99;uintptr_t mesh=1,next=1,previous=1,owner=0;
 return mp4_actor_field(reinterpret_cast<void*>(o.modules),0x21c,shape)&&(shape==4||shape==5)
 &&mp4_actor_field(reinterpret_cast<void*>(o.modules),0x360,mesh)&&!mesh
 &&mp4_actor_field(reinterpret_cast<void*>(o.modules),0x420,next)&&!next
 &&mp4_actor_field(reinterpret_cast<void*>(o.modules),0x428,previous)&&!previous
 &&mp4_actor_field(reinterpret_cast<void*>(o.modules),0x430,owner)&&(!owner||owner==o.native);
}
bool mp4_particle_native_state_array(void*,const mp4ps::Owner&o,unsigned which,mp4ps::Array*out){if(!out||which>1||!mp4_particle_native_state_policy(nullptr,o))return false;
 *out={};
 const auto at=o.state+(which?0x200:0x1c0);mp4ps::Array a{};
 if(!mp4_actor_field(reinterpret_cast<void*>(at),0,a.data)||!mp4_actor_field(reinterpret_cast<void*>(at),8,a.label)
 ||!mp4_actor_field(reinterpret_cast<void*>(at),16,a.count)||!mp4_actor_field(reinterpret_cast<void*>(at),24,a.encoded)
 ||a.count>(a.encoded>>1)||(a.encoded>>1)>65536||((a.encoded>>1)&&!a.data))return false;
 *out=a;return true;
}
bool mp4_particle_native_state_range(const mp4ps::Owner&o,uintptr_t at,size_t bytes,bool write){
 for(const auto span:mp4ps::state_spans)if(at==o.state+span.offset&&bytes==span.size)return true;
 for(const auto span:mp4ps::module_spans)if(at==o.modules+span.offset&&bytes==span.size)return true;
 return write&&bytes==8&&(at==o.state+0x1d0||at==o.state+0x210);
}
const mp4ps::Owner*mp4_particle_native_state_owner(uintptr_t at,size_t bytes,bool write){if(!mp4_particle_native_state_held(nullptr))return nullptr;
 const auto&c=mp4_particle_native_state_context;const mp4ps::Owner*found=nullptr;
 for(size_t i=0;i<c.count;++i)if(mp4_particle_native_state_range(c.owners[i],at,bytes,write)){if(found)return nullptr;found=&c.owners[i];}
 if(!found||!mp4_particle_native_state_policy(nullptr,*found)||!mp4_particle_native_state_mapped(at,bytes,write))return nullptr;
 return found;
}
bool mp4_particle_native_state_read(void*,uintptr_t at,size_t bytes,void*out){if(!out||!mp4_particle_native_state_owner(at,bytes,false))return false;::memcpy(out,reinterpret_cast<void*>(at),bytes);return true;}
bool mp4_particle_native_state_restoration(void*,const mp4ps::Owner&o,uint64_t receipt){mp4ps::Owner actual{};bool public_restored=false;
 return receipt&&mp4_particle_native_state_source(o.managed,&actual,&public_restored)&&public_restored&&mp4ps::same(actual,o)
 &&mp4_particle_native_state_context.restore_current(o,receipt);}
bool mp4_particle_native_state_write(void*,uintptr_t at,size_t bytes,const void*in,uint64_t receipt){
 const auto*owner=mp4_particle_native_state_owner(at,bytes,true);if(!owner||!in||!mp4_particle_native_state_restoration(nullptr,*owner,receipt))return false;
 if((at==owner->state+0x1d0||at==owner->state+0x210)){uint64_t value=1;::memcpy(&value,in,sizeof value);if(value)return false;}
 ::memcpy(reinterpret_cast<void*>(at),in,bytes);return true;
}
mp4ps::Api mp4_particle_native_state_api(){return{nullptr,mp4_particle_native_state_current,mp4_particle_native_state_held,mp4_particle_native_state_policy,
 mp4_particle_native_state_array,mp4_particle_native_state_read,mp4_particle_native_state_write,mp4_particle_native_state_restoration};}

#include "renderer-registration-state.hpp.inc"
namespace mp4psrreg=idoly_mp4_renderer_registration;
struct{uint64_t epoch=0,capture=0;bool(*fence_current)(uint64_t,uint64_t)=nullptr;bool(*restore_current)(uint64_t,uint64_t)=nullptr;bool(*source_current)(uintptr_t,int32_t,uint64_t,uint64_t)=nullptr;}mp4_renderer_registration_context;
void*registration_table=nullptr;unsigned registration_calls=0;
bool reg_current(void*,uint64_t e){return e==7&&source;}bool reg_held(void*){auto&c=mp4_renderer_registration_context;return c.fence_current&&c.fence_current(c.epoch,c.capture);}
bool reg_table(void*,mp4psrreg::Table*out){if(!reg_held(nullptr))return false;*out={(uintptr_t)registration_table,(uintptr_t)registration_table,1,1};return true;}
bool reg_row(void*,const mp4psrreg::Table&,size_t i,mp4psrreg::Count*out,bool*occupied){if(i||!reg_held(nullptr))return false;*out={23,1};*occupied=true;return true;}
bool reg_renderer(void*,uintptr_t n,mp4psrreg::Renderer*out){if(n!=(uintptr_t)rnative||!reg_held(nullptr))return false;int32_t id=0;mp4_actor_field(rnative,8,id);auto&c=mp4_renderer_registration_context;if(!c.source_current||!c.source_current(n,id,c.epoch,c.capture))return false;*out={};out->native=n;out->game_object=(uintptr_t)gnative;out->instance=id;out->game_object_id=23;out->property=true;mp4_actor_field(rnative,0x128,out->flags);mp4_actor_field(rnative,0x1b4,out->enabled);mp4_actor_field(rnative,0x1b5,out->active);++registration_calls;return true;}
bool reg_restore(void*,uint64_t e,uint64_t r){auto&c=mp4_renderer_registration_context;return c.restore_current&&c.restore_current(e,r);}
mp4psrreg::Api mp4_renderer_registration_api(){return{nullptr,reg_current,reg_held,reg_table,reg_row,reg_renderer,reg_restore};}
bool mp4_builtin_cache_refresh(void*r,uint64_t plan,uint64_t exclusion,uint64_t*out){*out=0;if(r!=renderer||plan!=builtin_plan.receipt||!mp4_builtin_context.held_current||!mp4_builtin_context.held_current(builtin_plan.source,exclusion))return false;*out=83;return true;}
bool mp4_builtin_mesh_cache_current(void*r,uintptr_t n,int32_t id,uint64_t plan,uint64_t cache,uint64_t exclusion,float out[6]){if(!cache_current||r!=renderer||n!=(uintptr_t)rnative||id!=19||plan!=builtin_plan.receipt||cache!=83||!mp4_builtin_context.held_current||!mp4_builtin_context.held_current(builtin_plan.source,exclusion))return false;for(unsigned i=0;i<6;++i)out[i]=0;return true;}
bool mp4_builtin_mesh_retire(){builtin_plan={};return true;}
#include "particle-native-coordinator-host.inc"
void*manager=nullptr,*manager_global=nullptr,*manager_rows=nullptr;
void full_setup(){setup();extra_setup();present_setup();program_setup();manager=alloc(64);manager_global=alloc(8);manager_rows=alloc(8);registration_table=alloc(16);}
void full_reset(){assert(mp4_particle_native_release(false)==Mp4SceneResult::ok);array=renderer_array;program_reset();present_reset(false,true);auto serial=create();(void)serial;mp4_stage_host.count=1;mp4_stage_host.owners[0].particle=particle;mp4_stage_host.configured=true;mp4_stage_host.restored=false;mp4_scene_host={};mp4_scene_host.source={7};mp4_scene_host.active=true;mp4_scene_host.all=15;mp4_scene_host.restored=0;public_restored=false;mutation_good=true;mp4_particle_mutation_host={};mp4_particle_mutation_host.generation=1;mp4_particle_mutation_boundary={61,1};active_boundary=61;mp4_raw_original_operation.depth=0;mp4_rebuild_ledger.active=false;mp4_gpu_fence_host={};mp4_gpu_auxiliary_host={};mp4_owned_render_depth=mp4_unowned_render_depth=0;mp4_owned_render_ticket_active=false;put(manager_global,0,(uintptr_t)manager);mp4_particle_manager_pins.singleton=(uintptr_t)manager_global-1;::memset(manager,0,64);put(manager,0,(uintptr_t)manager_rows);put(manager,16,uint64_t(1));put(manager,24,uint64_t(2));put(manager_rows,0,(uintptr_t)native);put(native,0x68,int32_t(0));}
void saved_source_returned(){mp4_stage_host.restored=true;mp4_scene_host.restored=mp4_scene_host.all;public_restored=true;}
int main(){full_setup();unsigned cases=0;
 {full_reset();assert(mp4_particle_native_capture()==Mp4SceneResult::ok&&mp4_particle_native_early_current());uint64_t r=0;assert(mp4_particle_native_image_receipt(particle,&r)&&r);uint32_t f=0;assert(mp4_particle_activation_family(particle,&f,&r)&&f==0x5053);assert(mp4_particle_activation_family(renderer,&f,&r)&&f==0x5052);put(state,0x22,uint8_t(91));put(modules,0x480,uint8_t(97));current_present=true;current_block={{1,103}};static_cast<Material*>(source_material)->properties={{4,107}};saved_source_returned();assert(mp4_particle_native_verify_source_restored(nullptr)==Mp4SceneResult::ok);assert(((uint8_t*)state)[0x22]==0&&((uint8_t*)modules)[0x480]==0&&!current_present);assert(mp4_particle_native_release(true)==Mp4SceneResult::ok);++cases;}
 {full_reset();assert(mp4_particle_native_capture()==Mp4SceneResult::ok);assert(mp4_particle_native_capture()==Mp4SceneResult::ok);assert(mp4_particle_native_release(false)==Mp4SceneResult::ok);++cases;}
 {full_reset();assert(mp4_particle_native_capture()==Mp4SceneResult::ok);assert(mp4_particle_native_verify_source_restored(nullptr)==Mp4SceneResult::stale);assert(mp4_particle_native_release(true)==Mp4SceneResult::stale);assert(mp4_particle_native_release(false)==Mp4SceneResult::ok);++cases;}
 {full_reset();assert(mp4_particle_native_capture()==Mp4SceneResult::ok);saved_source_returned();mp4_gpu_fence_host.configured=true;mp4_gpu_fence_host.sequence=1;mp4_gpu_fence_host.ledger.wait=true;assert(mp4_particle_native_verify_source_restored(nullptr)==Mp4SceneResult::waiting);mp4_gpu_fence_host.ledger.wait=false;assert(mp4_particle_native_verify_source_restored(nullptr)==Mp4SceneResult::ok&&mp4_gpu_fence_host.retired==1&&mp4_gpu_fence_host.ledger.retires==1);assert(mp4_particle_native_release(true)==Mp4SceneResult::ok);++cases;}
 {full_reset();assert(mp4_particle_native_capture()==Mp4SceneResult::ok);saved_source_returned();mp4_raw_original_operation.depth=1;assert(mp4_particle_native_verify_source_restored(nullptr)==Mp4SceneResult::stale);assert(mp4_particle_native_release(false)==Mp4SceneResult::waiting);mp4_raw_original_operation.depth=0;assert(mp4_particle_native_release(false)==Mp4SceneResult::ok);++cases;}
 {full_reset();assert(mp4_particle_native_capture()==Mp4SceneResult::ok);mp4_particle_mutation_host.generation++;assert(!mp4_particle_native_early_current());assert(mp4_particle_native_release(false)==Mp4SceneResult::ok);++cases;}
 {full_reset();assert(mp4_particle_native_capture()==Mp4SceneResult::ok);source=false;assert(!mp4_particle_native_early_current());assert(mp4_particle_native_release(false)==Mp4SceneResult::ok);source=true;++cases;}
 {full_reset();assert(mp4_particle_native_capture()==Mp4SceneResult::ok);auto*h=mp4_particle_native_host;h->depth=1;assert(mp4_particle_native_release(false)==Mp4SceneResult::waiting);h->depth=0;assert(mp4_particle_native_release(false)==Mp4SceneResult::ok);++cases;}
 {full_reset();assert(mp4_particle_native_capture()==Mp4SceneResult::ok);main_thread=false;assert(mp4_particle_native_release(false)==Mp4SceneResult::waiting);main_thread=true;assert(mp4_particle_native_release(false)==Mp4SceneResult::ok);++cases;}
 {full_reset();put(state,0x1d0,uint64_t(1));assert(mp4_particle_native_capture()==Mp4SceneResult::unsupported);assert(mp4_particle_native_release(false)==Mp4SceneResult::ok);++cases;}
 {full_reset();assert(mp4_particle_native_capture()==Mp4SceneResult::ok);uint64_t r=0;assert(!mp4_particle_native_image_receipt(renderer,&r)&&!r);uint32_t f=9;assert(!mp4_particle_activation_family(go,&f,&r)&&!f&&!r);assert(mp4_particle_native_release(false)==Mp4SceneResult::ok);++cases;}
 {full_reset();assert(mp4_particle_native_capture()==Mp4SceneResult::ok);saved_source_returned();mp4_gpu_auxiliary_host.configured=true;mp4_gpu_auxiliary_host.sequence=1;mp4_gpu_auxiliary_host.ledger.bad=true;assert(mp4_particle_native_verify_source_restored(nullptr)==Mp4SceneResult::stale);assert(mp4_particle_native_release(false)==Mp4SceneResult::stale);mp4_gpu_auxiliary_host.ledger.bad=false;assert(mp4_particle_native_release(false)==Mp4SceneResult::ok);++cases;}
 if(mp4_particle_source_renderer_type){weak_free(mp4_particle_source_renderer_type);}
 ::free(mp4_particle_source_policies);::free(mp4_particle_source_programs);delete static_cast<Material*>(source_material);assert(roots.empty()&&private_materials.empty()&&private_blocks.empty());std::printf("%u actual native coordinator/full-image cases passed\n",cases);
}
