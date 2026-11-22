#include <cassert>
#include <cstdio>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <atomic>
#include <map>
#include <vector>
#include <memory>
#include <stdexcept>
using Method=void;
namespace mp4game{struct Binding{uintptr_t rva=0;uint8_t prefix[16]{};};}
bool binding_current=true;bool mp4_prefix(const mp4game::Binding&){return binding_current;}
bool mp4_hook_was_statically_verified(const mp4game::Binding&){return false;}
bool mp4_particle_source_policy_bindings(){return binding_current;}

struct Region{uintptr_t at;size_t n;};std::vector<Region>regions;
std::vector<std::unique_ptr<uint8_t[]>>storage;
void*alloc(size_t n){storage.emplace_back(new uint8_t[n]{});void*p=storage.back().get();regions.push_back({(uintptr_t)p,n});return p;}
bool mapped(const void*p,size_t n){auto a=(uintptr_t)p;for(auto r:regions)if(a>=r.at&&a+n>=a&&a+n<=r.at+r.n)return true;return false;}
template<class T>bool mp4_actor_field(void*p,size_t at,T&out){if(!mapped((uint8_t*)p+at,sizeof out))return false;::memcpy(&out,(uint8_t*)p+at,sizeof out);return true;}
template<class T>void put(void*p,size_t at,T v){assert(mapped((uint8_t*)p+at,sizeof v));::memcpy((uint8_t*)p+at,&v,sizeof v);}
bool mp4_particle_native_state_mapped(uintptr_t p,size_t n){return mapped((void*)p,n);}
bool on_main=true,alive=true,stage_current=true,clock_held=true,control_current=true;
unsigned gc_calls=0,retains=0,frees=0,handoffs=0;
bool game_call(){return on_main;}bool mp4_alive(void*p){return alive&&p&&mapped(p,24);}
std::map<uint32_t,void*>roots;uint32_t nextroot=1;
uint32_t mp4_retain(void*p){assert(on_main);++gc_calls;++retains;if(!p)return 0;roots[nextroot]=p;return nextroot++;}
void*weak_get(uint32_t r){assert(on_main);++gc_calls;auto it=roots.find(r);return it==roots.end()?nullptr:it->second;}
void weak_free(uint32_t r){assert(on_main);++gc_calls;++frees;roots.erase(r);}
struct Mp4ActorTempRoot{uint32_t r;explicit Mp4ActorTempRoot(void*p):r(mp4_retain(p)){}~Mp4ActorTempRoot(){if(r)weak_free(r);}void*get(){return weak_get(r);}};
struct Mp4SceneWitness{uint64_t generation=0;void*player=nullptr;};
bool mp4_scene_same_source(const Mp4SceneWitness&a,const Mp4SceneWitness&b){return a.generation==b.generation&&a.player==b.player;}
struct Owner{void*particle=nullptr;};
struct{Mp4SceneWitness source{};Owner owners[256]{};size_t count=0;bool configured=false;}mp4_stage_host;
struct{Mp4SceneWitness source{};}mp4_scene_host;
bool mp4_stage_owner(void*){return stage_current;}bool mp4_actor_clock_held(void*){return clock_held;}
bool mp4_stage_control_current(void*,const Owner&){return control_current;}
std::atomic<bool>mp4_stage_foreign_dirty{false};
namespace idoly_mp4_runtime{struct{uint64_t generation=0;}job;void observe_source_will_change(void*){++handoffs;}}
std::map<void*,void*>go_of,transform_of,parent_of;
void*component_go(void*p,Method*){return go_of[p];}void*get_transform(void*p,Method*){return transform_of[p];}
void*get_parent(void*p,Method*){return parent_of[p];}
struct{mp4game::Binding component_gameobject{(uintptr_t)&component_go},particle_playing{},particle_paused{},particle_stopped{};}mp4_stage_profile;
struct{mp4game::Binding game_object_transform{(uintptr_t)&get_transform};}mp4_cam_profile;
struct{mp4game::Binding parent{(uintptr_t)&get_parent};}mp4_actor_profile;
template<class T>T mp4_equipment_call(const mp4game::Binding&p){return reinterpret_cast<T>(p.rva);}template<class T>T mp4_cam_call(const mp4game::Binding&p){return reinterpret_cast<T>(p.rva);}
struct ActorApi{void*(*transform_parent)(void*,Method*);};ActorApi mp4_actor_state_api(){return{get_parent};}
bool early=true,fixed_continuity=true,anim_continuity=true,anim_closed=true;
struct Early{bool current(){return early;}uint64_t fixed_serial(){return 41;}uint64_t animation_serial(){return 43;}}mp4_early_source_gates;
struct Gate{bool animation=false;bool lease_continuity(uint64_t e,uint64_t s,Early*p){return e==7&&s==(animation?43:41)&&p==&mp4_early_source_gates&&(animation?anim_continuity:fixed_continuity);}bool closed(uint64_t e){return e==7&&anim_closed;}}mp4_fixed_gate{false},mp4_animation_gate{true};
bool quiet=true,allowed=true,playing=false,paused=true,stopped=false;
struct{bool mutation_quiet(){return quiet;}bool allow_simulate(void*,float,bool,bool,bool){return allowed;}}mp4_stage_particles;
bool mp4_stage_hooks_intercept(bool thread){return thread&&stage_current;}
struct StageApi{bool(*playing)(void*,Method*);bool(*paused)(void*,Method*);bool(*stopped)(void*,Method*);};
bool isplaying(void*,Method*){return playing;}bool ispaused(void*,Method*){return paused;}bool isstopped(void*,Method*){return stopped;}StageApi mp4_stage_api(){return{isplaying,ispaused,isstopped};}
struct{unsigned depth=0;}mp4_raw_original_operation;struct{bool active=false;}mp4_rebuild_ledger;
struct Node{struct{void*target=nullptr;}key;};struct Operation{};
struct ActivationOrigin{bool published=false;uint64_t receipt=0;Node node{};Operation operation{};};
const ActivationOrigin*mp4_activation_origin=nullptr;bool origin_ok=true,origin_throw=false;
uint64_t origin_cb(Operation,const Node&){if(origin_throw)throw std::runtime_error("observer");return origin_ok&&mp4_activation_origin?mp4_activation_origin->receipt:0;}
uint64_t(*mp4_activation_callback_origin)(Operation,const Node&)=origin_cb;
struct{void*object=nullptr;bool desired=false;uint64_t serial=0;uint64_t restoring_setter_receipt(void*p,bool v){return p==object&&desired==v?serial:0;}}mp4_activation_targets;
struct Mp4ParticleFinishOwner{void*managed=nullptr;uintptr_t native=0,particles=0,parameters=0,state=0,modules=0;int32_t instance=0;uint64_t capture=0;};
unsigned mp4_owned_render_depth=0,mp4_unowned_render_depth=0;bool mp4_owned_render_ticket_active=false;
#include "particle-mutation-exclusion-host.inc"
using Mp4ParticleSimulate=void(*)(void*,float,bool,bool,bool,Method*);
#include "particle-mutation-hooks.inc"
void*p=nullptr,*go=nullptr,*tr=nullptr,*ancestor=nullptr,*atr=nullptr,*foreign_go=nullptr;ActivationOrigin origin{};
Mp4ParticleFinishOwner owner{};unsigned originals=0;bool original_throw=false,nest=false;Method*last_method=nullptr;bool last_value=false;float last_seconds=0;
void original_active(void*self,bool v,Method*m){++originals;last_method=m;last_value=v;if(nest){nest=false;mp4_source_game_object_active_hook(self,v,m);}if(original_throw)throw 17;}
void original_sim(void*,float s,bool c,bool r,bool f,Method*m){++originals;last_seconds=s;last_method=m;assert(!c&&r&&!f);if(original_throw)throw 19;}
void*newobject(int id){void*o=alloc(32);void*n=alloc(0x100);put(o,16,(uintptr_t)n);put(n,8,(int32_t)id);return o;}
void setup(){p=newobject(1);go=newobject(2);tr=newobject(3);ancestor=newobject(4);atr=newobject(5);foreign_go=newobject(6);go_of[p]=go;go_of[tr]=go;go_of[atr]=ancestor;transform_of[go]=tr;transform_of[ancestor]=atr;parent_of[tr]=atr;parent_of[atr]=nullptr;}
void reset(){on_main=true;binding_current=true;mp4_particle_mutation_clear();alive=stage_current=clock_held=control_current=early=fixed_continuity=anim_continuity=anim_closed=quiet=allowed=paused=true;playing=stopped=false;mp4_stage_host={};mp4_stage_host.source={7,p};mp4_stage_host.count=1;mp4_stage_host.owners[0]={p};mp4_stage_host.configured=true;mp4_scene_host.source=mp4_stage_host.source;idoly_mp4_runtime::job.generation=11;mp4_stage_foreign_dirty=false;origin={true,53,{{go}},{}};mp4_activation_origin=nullptr;mp4_activation_targets={};origin_ok=true;origin_throw=false;mp4_raw_original_operation.depth=0;mp4_rebuild_ledger.active=false;mp4_owned_render_depth=mp4_unowned_render_depth=0;mp4_owned_render_ticket_active=false;originals=handoffs=0;original_throw=nest=false;mp4_source_game_object_active_original=original_active;parent_of[tr]=atr;parent_of[atr]=nullptr;put(p,16,(uintptr_t)regions[1].at);put((void*)regions[1].at,8,(int32_t)1);assert(mp4_particle_mutation_capture());uintptr_t n=0;int32_t id=0;assert(mp4_particle_mutation_unity_identity(p,&n,&id));owner={};owner.managed=p;owner.native=n;owner.instance=id;owner.capture=29;}
int main(){setup();unsigned cases=0;auto boundary=[](){auto b=mp4_particle_mutation_issue_boundary();assert(b);assert(mp4_particle_mutation_exclusion(owner,b));return b;};
 {reset();auto b=boundary();mp4_activation_origin=&origin;mp4_source_game_object_active_hook(go,true,(Method*)23);mp4_activation_origin=nullptr;assert(originals==1&&last_value&&last_method==(Method*)23&&!handoffs&&!mp4_particle_mutation_host.depth);assert(!mp4_particle_mutation_exclusion(owner,b));assert(boundary()!=b);++cases;}
 {reset();mp4_source_game_object_active_hook(foreign_go,false,nullptr);assert(originals==1&&!handoffs&&boundary());++cases;}
 {reset();auto b=boundary();mp4_source_game_object_active_hook(ancestor,false,nullptr);assert(originals==1&&handoffs==1&&!mp4_particle_mutation_exclusion(owner,b));++cases;}
 {reset();auto b=boundary();auto roots_before=roots.size();auto calls=gc_calls;on_main=false;mp4_source_game_object_active_hook(go,true,nullptr);assert(originals==1&&gc_calls==calls&&roots.size()==roots_before);on_main=true;assert(!mp4_particle_mutation_exclusion(owner,b));mp4_particle_mutation_clear();assert(roots.empty());++cases;}
 {reset();mp4_activation_origin=&origin;nest=true;mp4_source_game_object_active_hook(go,true,nullptr);mp4_activation_origin=nullptr;assert(originals==2&&!handoffs&&!mp4_particle_mutation_host.depth&&boundary());++cases;}
 {reset();mp4_activation_origin=&origin;original_throw=true;bool caught=false;try{mp4_source_game_object_active_hook(go,false,nullptr);}catch(int n){caught=n==17;}mp4_activation_origin=nullptr;assert(caught&&originals==1&&!mp4_particle_mutation_host.depth&&handoffs==1);++cases;}
 {reset();mp4_activation_origin=&origin;origin_throw=true;mp4_source_game_object_active_hook(go,true,nullptr);mp4_activation_origin=nullptr;assert(originals==1&&handoffs>=1&&!mp4_particle_mutation_host.depth);++cases;}
 {reset();mp4_activation_targets={go,true,61};mp4_source_game_object_active_hook(go,true,nullptr);mp4_activation_targets={};assert(originals==1&&!handoffs&&boundary());++cases;}
 {reset();mp4_activation_targets={go,true,61};mp4_source_game_object_active_hook(go,false,nullptr);assert(originals==1&&handoffs==1);++cases;}
 {reset();mp4_activation_origin=&origin;origin_ok=false;mp4_source_game_object_active_hook(go,true,nullptr);assert(originals==1&&handoffs==1);mp4_activation_origin=nullptr;++cases;}
 {reset();mp4_activation_origin=&origin;origin.node.key.target=ancestor;mp4_source_game_object_active_hook(go,true,nullptr);assert(originals==1&&handoffs==1);mp4_activation_origin=nullptr;++cases;}
 {reset();mp4_particle_simulate_observed(original_sim,p,.25f,false,true,false,(Method*)31);assert(originals==1&&last_seconds==.25f&&last_method==(Method*)31&&!handoffs&&boundary());++cases;}
 {reset();allowed=false;mp4_particle_simulate_observed(original_sim,p,.5f,false,true,false,nullptr);assert(originals==1&&handoffs==1);++cases;}
 {reset();original_throw=true;bool caught=false;try{mp4_particle_simulate_observed(original_sim,p,.25f,false,true,false,nullptr);}catch(int n){caught=n==19;}assert(caught&&originals==1&&!mp4_particle_mutation_host.depth&&!mp4_particle_simulate_mutation_origin&&handoffs==1);++cases;}
 {reset();auto b=boundary();mp4_particle_render_mutation_observe();assert(!mp4_particle_mutation_exclusion(owner,b)&&boundary()!=b);++cases;}
 {reset();auto b=boundary();parent_of[tr]=nullptr;assert(!mp4_particle_mutation_exclusion(owner,b));++cases;}
 {reset();auto b=boundary();put((void*)regions[1].at,8,(int32_t)99);assert(!mp4_particle_mutation_exclusion(owner,b));++cases;}
 {reset();auto b=boundary();idoly_mp4_runtime::job.generation++;assert(!mp4_particle_mutation_exclusion(owner,b));++cases;}
 {reset();auto b=boundary();mp4_scene_host.source.generation++;assert(!mp4_particle_mutation_exclusion(owner,b));++cases;}
 {reset();auto b=boundary();quiet=false;assert(!mp4_particle_mutation_exclusion(owner,b));++cases;}
 {reset();auto b=boundary();mp4_raw_original_operation.depth=1;assert(!mp4_particle_mutation_exclusion(owner,b));++cases;}
 {reset();auto b=boundary();mp4_rebuild_ledger.active=true;assert(!mp4_particle_mutation_exclusion(owner,b));++cases;}
 {reset();auto b=boundary();mp4_owned_render_depth=1;assert(!mp4_particle_mutation_exclusion(owner,b));++cases;}
 {reset();auto b=boundary();mp4_unowned_render_depth=1;assert(!mp4_particle_mutation_exclusion(owner,b));++cases;}
 {reset();auto b=boundary();mp4_owned_render_ticket_active=true;assert(!mp4_particle_mutation_exclusion(owner,b));++cases;}
 {reset();auto b=boundary();fixed_continuity=false;assert(!mp4_particle_mutation_exclusion(owner,b));++cases;}
 {reset();auto b=boundary();anim_closed=false;assert(!mp4_particle_mutation_exclusion(owner,b));++cases;}
 {reset();auto b=boundary();playing=true;assert(!mp4_particle_mutation_exclusion(owner,b));++cases;}
 {reset();paused=false;stopped=true;assert(boundary());++cases;}
 {reset();auto b=boundary();paused=false;assert(!mp4_particle_mutation_exclusion(owner,b));++cases;}
 {reset();mp4_activation_origin=&origin;Mp4ParticleMutationTicket t{};assert(mp4_particle_mutation_begin(go,true,t,true)&&t.active);auto n=roots.size();mp4_particle_mutation_clear();assert(roots.size()==n&&mp4_particle_mutation_host.active);assert(mp4_particle_mutation_end(t,true));mp4_activation_origin=nullptr;mp4_particle_mutation_clear();assert(roots.empty());++cases;}
 {reset();auto b=boundary();mp4_particle_mutation_clear();assert(!mp4_particle_mutation_exclusion(owner,b));assert(mp4_particle_mutation_capture());assert(boundary()!=b);++cases;}
 {reset();auto b=boundary();binding_current=false;assert(!mp4_particle_mutation_exclusion(owner,b));binding_current=true;++cases;}
 mp4_particle_mutation_clear();assert(roots.empty());std::printf("%u actual mutation/ordinary-hook cases passed\n",cases);
}
