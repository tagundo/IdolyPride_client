#include <cassert>
#include <cstdint>
#include <cstddef>
#include <cstring>
#include <string>
#include <initializer_list>
using Method=const void;
namespace mp4actor{struct Handle{uintptr_t handle=0;uint32_t version=0,padding=0;};}
namespace mp4game{struct Binding{uintptr_t rva=0;uint8_t prefix[16]{};};}
namespace mp4stage{struct Layout{static constexpr size_t control_particle=32,control_random_seed=24,clip_asset=40;};constexpr size_t max_particles=8;struct Owner{void*particle=nullptr;uint32_t producer_kind=1;};}
struct Mp4TimelineTypePin{const char*name;mp4game::Binding binding;};
struct Witness{uint64_t generation=11;void*environment=nullptr;};
enum class Mp4TimelineProofPhase:uint8_t{admission,active,source_restore,source_restored};enum class Mp4TimelineVerdict:uint8_t{unrecognized,closed,unclosed};
struct Mp4TimelineContext{Mp4TimelineProofPhase phase=Mp4TimelineProofPhase::active;Witness witness{};void*director=nullptr,*asset=nullptr;mp4actor::Handle graph{42,2,0};};
struct Mp4TimelineRuntime{void*clip=nullptr;};
struct Script{const char*name="UnityEngine.Timeline.ParticleControlPlayable";uint8_t pad[16]{};uint32_t seed=7,pad2=0;void*particle=nullptr;};
static_assert(offsetof(Script,seed)==24&&offsetof(Script,particle)==32);
struct Clip{uint8_t pad[40]{};Script*asset=nullptr;};
static Script pc,foreign,light{ ".LightControlMixerBehaviour" },control_asset{"UnityEngine.Timeline.ControlPlayableAsset"},light_asset{".LightControlClip"},unknown{"Other.Unknown"};
static int ps=1,otherps=2,director=3,asset=4,userdata=5;static void*array[2]{&ps,nullptr};static size_t array_count=1;
static bool pins_current=true,source_current=true,source_admitted=true,full_owner=true,control_current=true,graph_valid=true,path_valid=true;
static size_t scripts_queries=0;
struct Path{uint16_t director=0,root=0,length=1,inputs[64]{};};
struct{bool configured=true,graph_receipt=true,rebuilding=false,restored=false;Witness source{};Path control_paths[2]{};size_t director_count=1,count=1;void*directors[2]{&director},*director_assets[2]{&asset};mp4actor::Handle graph_receipts[2]{{42,2,0}};mp4stage::Owner owners[2]{{&ps,1}};void*current_producers[2]{&pc};uint32_t source_seeds[2]{7};}mp4_stage_host;
struct{unsigned captured=4;}mp4_scene_host;
bool mp4_stage_source_verified=true;uintptr_t image_base=0;
struct{mp4game::Binding playable_graph_get;}mp4_actor_profile;
bool game_call(){return true;}bool mp4_timeline_pins_current(){return pins_current;}bool mp4_prefix(const mp4game::Binding&){return pins_current;}bool mp4_hook_was_statically_verified(const mp4game::Binding&){return false;}void*mp4_timeline_class(const Mp4TimelineTypePin&p){return const_cast<char*>(p.name);}
bool mp4_timeline_exact(void*s,const Mp4TimelineTypePin&p){return s&&!std::strcmp(static_cast<Script*>(s)->name,p.name);}
bool mp4_timeline_current(const Mp4TimelineContext&){return source_current;}bool mp4_actor_same_handle(mp4actor::Handle a,mp4actor::Handle b){return a.handle==b.handle&&a.version==b.version;}int mp4_timeline_node_index(const Mp4TimelineContext&,mp4actor::Handle n){return n.handle==3?0:-1;}
void*mp4_timeline_script(mp4actor::Handle n){++scripts_queries;return n.handle==3?&pc:nullptr;}
struct API{bool(*playable_valid)(mp4actor::Handle*,Method*);int(*graph_root_count)(mp4actor::Handle*,Method*);void(*graph_root)(mp4actor::Handle*,int,mp4actor::Handle*,Method*);int(*playable_input_count)(mp4actor::Handle*,Method*);void(*playable_input)(mp4actor::Handle*,int,mp4actor::Handle*,Method*);};
bool valid(mp4actor::Handle*n,Method*){return graph_valid&&(n->handle==1||n->handle==3);}
int roots(mp4actor::Handle*,Method*){return 1;}void root(mp4actor::Handle*,int,mp4actor::Handle*out,Method*){*out={1,2,0};}
int inputs(mp4actor::Handle*n,Method*){return n->handle==1?1:0;}void input(mp4actor::Handle*,int,mp4actor::Handle*out,Method*){*out={path_valid?uintptr_t(3):uintptr_t(4),2,0};}
API mp4_actor_state_api(){return {valid,roots,root,inputs,input};}void get_graph(mp4actor::Handle*,mp4actor::Handle*out,Method*){*out={42,2,0};}
bool mp4_type_is(void*p,const char*){return p==&ps||p==&otherps;}bool mp4_alive(void*p){return p;}
template<class T>bool mp4_actor_field(void*p,size_t at,T&v){if(!p)return false;std::memcpy(&v,static_cast<uint8_t*>(p)+at,sizeof v);return true;}
bool admission_receipt=true,admission_duplicate=false;void*admission_particle=&ps;
bool mp4_stage_admission_particle(const Witness&w,void*d,void*a,mp4actor::Handle graph,mp4actor::Handle node,void*script,void*particle,uint32_t seed){
 return admission_receipt&&!admission_duplicate&&source_current&&w.generation==11&&d==&director&&a==&asset&&graph.handle==42&&graph.version==2&&node.handle==3&&node.version==2&&script==&pc&&particle==admission_particle&&seed==7;
}
bool mp4_equipment_graph_witness(const Witness&){return source_admitted;}bool mp4_scene_same_source(const Witness&a,const Witness&b){return a.generation==b.generation;}
struct Mp4ActorTempRoot{void*p;explicit Mp4ActorTempRoot(void*x):p(x){}void*get()const{return p;}};
void*mp4_stage_children(void*){return array;}bool mp4_stage_array(void*a,void***out,size_t*n,size_t){*out=static_cast<void**>(a);*n=array_count;return true;}
bool mp4_stage_full_owner(void*){return full_owner;}bool mp4_stage_control_current(void*,const mp4stage::Owner&){return control_current;}
#include "pins.inc"
#include "provider.cpp"
// This fixture isolates the retained PC primitive. Complete source Control
// topology/parent/resource-plan joins are exercised by control-source-admission.
bool source_delegate=false;size_t source_node_calls=0,source_runtime_calls=0,source_userdata_calls=0;
Mp4TimelineVerdict mp4_control_source_node_verdict(const Mp4TimelineContext&c,mp4actor::Handle n,void*s){assert(c.phase==Mp4TimelineProofPhase::admission&&n.handle==3);++source_node_calls;return mp4_timeline_exact(s,mp4_stage_other_pins.particle)||mp4_timeline_exact(s,mp4_stage_other_pins.director_control)||mp4_timeline_exact(s,mp4_stage_other_pins.activation)?(source_delegate?Mp4TimelineVerdict::closed:Mp4TimelineVerdict::unclosed):Mp4TimelineVerdict::unrecognized;}
Mp4TimelineVerdict mp4_control_source_runtime_verdict(const Mp4TimelineContext&,const Mp4TimelineRuntime&r){++source_runtime_calls;if(!r.clip)return Mp4TimelineVerdict::unrecognized;void*a=nullptr;if(!mp4_actor_field(r.clip,40,a))return Mp4TimelineVerdict::unclosed;return mp4_timeline_exact(a,mp4_stage_other_pins.control_asset)?(source_delegate?Mp4TimelineVerdict::closed:Mp4TimelineVerdict::unclosed):Mp4TimelineVerdict::unrecognized;}
bool mp4_control_source_userdata(const Mp4TimelineContext&c,mp4actor::Handle n,void*s,void*d){assert(c.phase==Mp4TimelineProofPhase::admission&&n.handle==3&&s==&pc&&d==&userdata);++source_userdata_calls;return source_delegate;}
int main(int argc,char**argv){assert(argc==2);const std::string c=argv[1];Mp4TimelineContext ctx;ctx.director=&director;ctx.asset=&asset;pc.particle=&ps;mp4_actor_profile.playable_graph_get.rva=reinterpret_cast<uintptr_t>(get_graph);mp4actor::Handle node{3,2,0};
 if(c=="delegate_source_node"||c=="delegate_source_reject"){ctx.phase=Mp4TimelineProofPhase::admission;source_delegate=c=="delegate_source_node";assert(mp4_stage_other_node(ctx,node,&pc)==(source_delegate?Mp4TimelineVerdict::closed:Mp4TimelineVerdict::unclosed));assert(mp4_stage_other_userdata(ctx,node,&pc,&userdata)==source_delegate);assert(source_node_calls==1&&source_userdata_calls==1);return 0;}
 if(c=="delegate_source_runtime"){ctx.phase=Mp4TimelineProofPhase::admission;source_delegate=true;Clip clip;clip.asset=&control_asset;Mp4TimelineRuntime runtime{&clip};assert(mp4_stage_other_runtime(ctx,runtime)==Mp4TimelineVerdict::closed&&source_runtime_calls==1);return 0;}
 if(c=="delegate_other_phase"){source_delegate=true;assert(mp4_stage_other_node(ctx,node,&pc)==Mp4TimelineVerdict::closed&&source_node_calls==0);return 0;}
 if(c=="delegate_unknown"){ctx.phase=Mp4TimelineProofPhase::admission;source_delegate=true;assert(mp4_stage_other_node(ctx,node,&unknown)==Mp4TimelineVerdict::unrecognized&&source_node_calls==1);return 0;}
 if(c=="admission"||c=="admit_foreign"||c=="admit_duplicate"||c=="admit_receipt"||c=="admit_timeline_sibling"||c=="admit_unpublished")ctx.phase=Mp4TimelineProofPhase::admission;
 if(c=="admit_foreign")admission_particle=&otherps;else if(c=="admit_duplicate")admission_duplicate=true;else if(c=="admit_timeline_sibling"){array[0]=&otherps;array_count=1;}else if(c=="admit_unpublished")admission_receipt=false;else if(c=="admit_receipt")source_admitted=false;
 if(c=="pins_lost")pins_current=false;else if(c=="source_lost")source_current=false;else if(c=="zero_seed")pc.seed=0;else if(c=="seed_changed")pc.seed=8;else if(c=="wrong_particle")pc.particle=&otherps;else if(c=="wrong_path")path_valid=false;else if(c=="wrong_graph")ctx.graph.version=4;else if(c=="uncaptured")mp4_scene_host.captured=0;else if(c=="scope_lost")full_owner=false;else if(c=="producer_lost")control_current=false;else if(c=="wrong_producer")mp4_stage_host.current_producers[0]=&foreign;else if(c=="source_epoch")++mp4_stage_host.source.generation;
 if(c=="restore"||c=="restore_pending"){ctx.phase=Mp4TimelineProofPhase::source_restored;mp4_stage_host.restored=c=="restore";}
 if(c=="restore_plan")ctx.phase=Mp4TimelineProofPhase::source_restore;
 if(c=="light"){assert(mp4_stage_other_node(ctx,node,&light)==Mp4TimelineVerdict::unclosed);return 0;}
 if(c=="unknown"){assert(mp4_stage_other_node(ctx,node,&unknown)==Mp4TimelineVerdict::unrecognized);return 0;}
 if(c=="control_runtime"||c=="light_runtime"||c=="unknown_runtime"){Clip clip;clip.asset=c=="control_runtime"?&control_asset:c=="light_runtime"?&light_asset:&unknown;Mp4TimelineRuntime runtime{&clip};assert(mp4_stage_other_runtime(ctx,runtime)==(c=="unknown_runtime"?Mp4TimelineVerdict::unrecognized:Mp4TimelineVerdict::unclosed));return 0;}
 const bool ok=c=="active"||c=="admit_timeline_sibling"||c=="admission"||c=="restore"||c=="restore_plan"||c=="userdata";
 if(ctx.phase==Mp4TimelineProofPhase::admission){assert(mp4_stage_other_particle_node(ctx,node,&pc)==ok);}
 const bool complete=ok&&ctx.phase!=Mp4TimelineProofPhase::admission;
 assert(mp4_stage_other_node(ctx,node,&pc)==(complete?Mp4TimelineVerdict::closed:Mp4TimelineVerdict::unclosed));
 assert(mp4_stage_other_userdata(ctx,node,&pc,&userdata)==complete);
}
