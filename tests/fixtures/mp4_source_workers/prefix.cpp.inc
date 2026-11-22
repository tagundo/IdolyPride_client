#include <atomic>
#include <cstdint>
#include <cstddef>
#include <cstring>
#include <cstdlib>
#include <iostream>
#include <stdexcept>
#include <vector>
#include <unordered_map>
#include <functional>
#include <memory>
#include <string>
#include <cassert>
#include <thread>
thread_local bool test_game_thread=true;
bool game_call(){return test_game_thread;}
namespace idoly_mp4_source_bootstrap {
enum class Result:int{ok=0,waiting=1,unsupported=-1,invalid=-2,failed=-3,stale=-4};
struct Key{uint64_t epoch=0,job=0;uintptr_t source=0,root_asset=0;};
bool same(const Key&a,const Key&b){return a.epoch==b.epoch&&a.job==b.job&&a.source==b.source&&a.root_asset==b.root_asset;}
struct Provider{Result(*advance)(void*,const Key&,uint64_t*)=nullptr;bool(*current)(void*,const Key&,uint64_t)=nullptr;void(*withdraw)(void*,const Key&)=nullptr;Result(*release)(void*,const Key&)=nullptr;};
}
namespace mp4_animation_defaults {struct Object{void*managed=nullptr;uintptr_t native=0;int32_t instance_id=0;uint32_t strong_root=0;};}
namespace pin {struct Entry{uint64_t rva=0;uint8_t bytes[16]{};};Entry mp4_brain_update{1,{}},mp4_core_camera{2,{}},mp4_psyllium_execute{3,{}};}
namespace mp4game {struct Binding{uint64_t rva=0;uint8_t prefix[16]{};};}
namespace mp4stage {enum class Result{ok,waiting,failed};}
struct TestObject{alignas(16) uint8_t bytes[512]{};alignas(16) uint8_t native[768]{};int32_t id=0;};
struct TestList{std::vector<void*> values;};
std::vector<std::unique_ptr<TestObject>> objects;
std::unordered_map<void*,TestObject*> object_map;
std::unordered_map<uint32_t,void*> roots;
uint32_t next_root=0;int retain_calls=0,retain_fail_at=0,weak_free_calls=0,field_calls=0;
int complete_calls=0,complete_fail_at=0,complete_throw_at=0,particle_advance_calls=0,particle_release_calls=0;
int roster_collect_calls=0,roster_current_calls=0,roster_release_calls=0;
bool selected_ok=true,early_ok=true,pins_ok=true,scope_ok=true,animation_gate_ok=true,actor_gate_ok=true,mono_ok=true,presentation_ok=true;
bool camera_ok=true,stage_ok=true,equipment_ok=true,psyllium_ok=true,vlb_ok=true,roster_ok=true,roster_current_ok=true,roster_release_ok=true;
bool roster_throw=false,roster_partial=false,release_roots_during_callback=false,controller_ok=true,equipment_list_ok=true,particle_current_ok=true;
int particle_waits=0,particle_release_waits=0;uint64_t particle_receipt=71;
std::function<void()> complete_action,particle_release_action,roster_release_action,roster_release_post_action;
size_t callback_count();
template<class T>void set_field(void*p,size_t off,T value){std::memcpy(static_cast<uint8_t*>(p)+off,&value,sizeof(value));}
template<class T>bool mp4_actor_field(void*p,size_t off,T&out){++field_calls;if(!p)return false;std::memcpy(&out,static_cast<uint8_t*>(p)+off,sizeof(out));return true;}
void* new_object(int id){auto p=std::make_unique<TestObject>();p->id=id;void*o=p->bytes;uintptr_t n=reinterpret_cast<uintptr_t>(p->native);set_field(o,16,n);set_field(p->native,8,id);object_map[o]=p.get();objects.push_back(std::move(p));return o;}
bool mp4_alive(void*p){return p&&object_map.count(p);}
uint32_t mp4_retain(void*p){++retain_calls;if(retain_fail_at==retain_calls)return 0;if(!mp4_alive(p))return 0;roots[++next_root]=p;return next_root;}
void* weak_get(uint32_t r){auto it=roots.find(r);return it==roots.end()?nullptr:it->second;}
void weak_free(uint32_t r){if(callback_count())release_roots_during_callback=true;assert(roots.erase(r)==1);++weak_free_calls;}
bool mp4_hook_was_statically_verified(const mp4game::Binding&b){return pins_ok&&b.rva>=1&&b.rva<=3;}
struct Mp4SceneWitness{};
struct ActorOwner{void*animator=nullptr;void*actor=nullptr;};
struct ActorHost{uint64_t epoch=7;void*player=nullptr;size_t count=0;ActorOwner owners[32]{};struct Scope{bool owner_current(){return scope_ok;}}scope;}mp4_actor_host;
bool mp4_actor_selected_source(void*){return selected_ok;}
bool mp4_actor_owner(void*,const ActorOwner&o){return mp4_alive(o.actor)&&mp4_alive(o.animator);}
bool mp4_actor_list(void*p,void***v,size_t*n,size_t cap){if(!p||!v||!n)return false;auto*l=static_cast<TestList*>(p);*v=l->values.data();*n=l->values.size();return *n<=cap;}
bool mp4_type_is(void*p,const char*name){return p&&std::string(name)=="VL.VLActorFootShadow"&&object_map.at(p)->id==3;}
struct Gate{bool closed(uint64_t){return animation_gate_ok;}bool held(uint64_t){return actor_gate_ok;}bool current(){return mono_ok;}}mp4_animation_gate,mp4_actor_gate,mp4_actor_mono_gate;
struct Presentation{bool scalar_owner_current(){return presentation_ok;}}mp4_actor_presentation_scope;
struct Source{uint64_t generation=7;void*player=nullptr;};
struct CameraHost{Source source{};struct Scope{bool active()const{return camera_ok;}}scope;bool producer_completion_failed=false;}mp4_camera_host;
struct {uint64_t serial=0;}mp4_camera_pipeline_invocation;
bool mp4_camera_interception_published(){return camera_ok;}
bool mp4_camera_source_current(void*){return camera_ok;}
struct StageHost{Source source{};bool configured=true;size_t controller_count=1;void*controllers[4]{};}mp4_stage_host;
std::atomic<bool> mp4_stage_lease_active{true};
bool mp4_stage_owner(void*){return stage_ok;}
struct EquipmentScope{bool source_quiescent(){return equipment_ok;}}mp4_stage_equipment;
struct PsyScope{bool source_quiescent(){return psyllium_ok;}}mp4_stage_psyllium;
mp4stage::Result mp4_stage_vlb_fence(){return vlb_ok?mp4stage::Result::ok:mp4stage::Result::waiting;}
bool mp4_stage_controller_receipted(void*){return controller_ok;}
struct EarlyGates{bool current(){return early_ok;}}mp4_early_source_gates;
struct SceneHost{Mp4SceneWitness source;}mp4_scene_host;
struct Mp4EquipmentTarget{void*object=nullptr;uint32_t kind=0;};
std::vector<Mp4EquipmentTarget> equipment_targets;
bool mp4_equipment_target_list(Mp4EquipmentTarget*out,size_t&n,bool){n=equipment_targets.size();if(!equipment_list_ok||n>256)return false;for(size_t i=0;i<n;++i)out[i]=equipment_targets[i];return true;}
idoly_mp4_source_bootstrap::Key selected_key{7,11,0x12340,0x56780};
bool mp4_scene_bootstrap_key(const idoly_mp4_source_bootstrap::Key&k){return selected_ok&&idoly_mp4_source_bootstrap::same(k,selected_key);}
struct Mp4AnimationSourceRoster{mp4_animation_defaults::Object objects[8]{};size_t count=0;bool partial=false;};
std::vector<void*> roster_targets;
bool mp4_animation_source_animators(const Mp4SceneWitness&,Mp4AnimationSourceRoster&r){++roster_collect_calls;
 for(auto*p:roster_targets){auto&o=r.objects[r.count++];o.managed=p;o.strong_root=mp4_retain(p);if(!o.strong_root)return false;mp4_actor_field(p,16,o.native);mp4_actor_field(reinterpret_cast<void*>(o.native),8,o.instance_id);if(roster_partial){r.partial=true;return false;}}
 if(roster_throw){throw std::runtime_error("modeled public query");}return roster_ok;
}
bool mp4_animation_source_current(const Mp4AnimationSourceRoster&r){++roster_current_calls;if(!roster_current_ok||r.partial)return false;for(size_t i=0;i<r.count;++i)if(weak_get(r.objects[i].strong_root)!=r.objects[i].managed)return false;return true;}
bool mp4_animation_source_object(const Mp4AnimationSourceRoster&r,size_t i,mp4_animation_defaults::Object*out){if(!out||i>=r.count)return false;*out=r.objects[i];return true;}
bool mp4_animation_source_release(Mp4AnimationSourceRoster&r){++roster_release_calls;if(roster_release_action)roster_release_action();if(!roster_release_ok)return false;for(size_t i=r.count;i;--i){auto&o=r.objects[i-1];if(o.strong_root){weak_free(o.strong_root);o.strong_root=0;}}r={};if(roster_release_post_action)roster_release_post_action();return true;}
bool mp4_animation_animator_complete(const mp4_animation_defaults::Object&o){++complete_calls;if(complete_action)complete_action();if(complete_throw_at==complete_calls)throw std::runtime_error("modeled original Complete");if(complete_fail_at==complete_calls)return false;set_field(reinterpret_cast<void*>(o.native),0x238,uint64_t(0));set_field(reinterpret_cast<void*>(o.native),0x240,int32_t(0));return true;}
idoly_mp4_source_bootstrap::Result mp4_particle_source_bootstrap_advance(void*,const idoly_mp4_source_bootstrap::Key&,uint64_t*out){++particle_advance_calls;*out=0;if(particle_waits-->0)return idoly_mp4_source_bootstrap::Result::waiting;*out=particle_receipt;return idoly_mp4_source_bootstrap::Result::ok;}
bool mp4_particle_source_bootstrap_current(void*,const idoly_mp4_source_bootstrap::Key&,uint64_t r){return particle_current_ok&&r&&r==particle_receipt;}
int particle_withdraw_calls=0;
void mp4_particle_source_bootstrap_withdraw(void*,const idoly_mp4_source_bootstrap::Key&){++particle_withdraw_calls;}
idoly_mp4_source_bootstrap::Result mp4_particle_source_bootstrap_release(void*,const idoly_mp4_source_bootstrap::Key&){++particle_release_calls;if(particle_release_action)particle_release_action();return particle_release_waits-->0?idoly_mp4_source_bootstrap::Result::waiting:idoly_mp4_source_bootstrap::Result::ok;}
struct {idoly_mp4_source_bootstrap::Provider source_producers;}mp4_source_bootstrap_joins;
