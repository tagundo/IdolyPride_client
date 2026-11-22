#include <cassert>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <string>
#include <unordered_map>
#include <vector>
#include <initializer_list>
using Method=const void;
namespace mp4actor{struct Handle{uintptr_t handle=0;uint32_t version=0,padding=0;};}
namespace mp4ctl{using Handle=mp4actor::Handle;struct Input{uint32_t source_name=0;void*source_default=nullptr,*prefab=nullptr;uint32_t seed=1;uint8_t particles=0,time_control=0,hierarchy=0;int32_t post=0;};struct Cache{void*controlled_asset=nullptr;double duration=0;uint8_t director=1,active=0,loop=0,controlling_directors=0,controlling_particles=0;};}
namespace mp4game{struct Binding{uintptr_t rva=1;uint8_t prefix[16]{};};}
struct Pin{const char*name;mp4game::Binding binding{};};
struct{Pin control_asset{"Control"},director_control{"DirectorNode"},activation{"ActivationNode"},particle{"ParticleNode"};}mp4_stage_other_pins;
struct{Pin plain{"Plain"},clip{"Runtime"};}mp4_timeline_pins;
struct {mp4game::Binding playable_type{},playable_input_count{},playable_input{},script_instance{},field_offset{};}mp4_actor_profile;
namespace mp4stage{struct Layout{static constexpr size_t clip_asset=40,control_particle=32,control_random_seed=24;};}
struct Obj {uint8_t bytes[256]{};const char*type;bool alive=true;explicit Obj(const char*t):type(t){uintptr_t n=reinterpret_cast<uintptr_t>(this)+7;std::memcpy(bytes+16,&n,8);}};
std::unordered_map<void*,Obj*> objects;
void add(Obj&o){objects[&o]=&o;}
template<class T>void set(Obj&o,size_t off,T v){std::memcpy(o.bytes+off,&v,sizeof v);}
struct NativeMethod{uintptr_t entry=0;}methods[3][8];
bool pins=true,field_schema=true,source=true,main_thread=true,raw_current=true,cache_current=true,weak_fail=false,admitted=true,plan_ok=true;
uintptr_t image_base=0;std::string scenario;int plan_calls=0;bool testing=false;size_t callback_kind=0;
uint32_t next_root=0;std::unordered_map<uint32_t,void*>roots;
uint32_t make_weak(void*p,bool){if(weak_fail)return 0;roots[++next_root]=p;return next_root;}auto weak_new=make_weak;
void*weak_get(uint32_t n){auto i=roots.find(n);return i==roots.end()?nullptr:i->second;}void free_weak(uint32_t n){assert(roots.erase(n)==1);}auto weak_free=free_weak;
struct Mp4ActorTempRoot{uint32_t h=0;explicit Mp4ActorTempRoot(void*p){if(p)h=weak_new(p,false);}~Mp4ActorTempRoot(){if(h)weak_free(h);}void*get()const{return weak_get(h);}};
const char*callbacks[]={"OnPlayableCreate","OnPlayableDestroy","OnGraphStart","OnGraphStop","OnBehaviourPlay","OnBehaviourPause","PrepareFrame","ProcessFrame"};
void*object_class(void*p){auto i=objects.find(p);return i==objects.end()?nullptr:const_cast<char*>(i->second->type);}
const void*font_method(void*klass,const char*name,int){size_t k=std::strcmp(static_cast<char*>(klass),"DirectorNode")==0?0:std::strcmp(static_cast<char*>(klass),"ActivationNode")==0?1:2;for(size_t i=0;i<8;++i)if(!std::strcmp(callbacks[i],name))return &methods[k][i];return nullptr;}
template<class T>bool mp4_actor_field(void*p,size_t off,T&out){if(!p)return false;auto it=objects.find(p);if(it!=objects.end()){if(off+sizeof(T)>256)return false;std::memcpy(static_cast<void*>(&out),it->second->bytes+off,sizeof out);return true;}if(off==0&&sizeof(T)==8){std::memcpy(static_cast<void*>(&out),p,8);return true;}if(off==8&&sizeof(T)==4){std::memcpy(static_cast<void*>(&out),static_cast<uint8_t*>(p)+8,4);return true;}return false;}
Obj source_type("Meta");
struct Type {uint8_t bytes[16]{};}source_types[32];
struct Field{Type*type=nullptr;}source_fields[32];
const void*font_field_type(void*f){return static_cast<Field*>(f)->type;}
bool mp4_root_track_field(void*object,const char*name,size_t off,void**out){
 if(!field_schema)return false;
 auto*type=static_cast<char*>(object_class(object));if(!type)return false;uint32_t kind=0;
 if(!std::strcmp(type,"DirectorNode")){if(!std::strcmp(name,"director")&&off==16)kind=18;else if(!std::strcmp(name,"m_SyncTime")&&off==24)kind=2;else if(!std::strcmp(name,"m_AssetDuration")&&off==32)kind=13;}
 if(!std::strcmp(type,"ActivationNode")){if(!std::strcmp(name,"gameObject")&&off==16)kind=18;else if((!std::strcmp(name,"postPlayback")&&off==24)||(!std::strcmp(name,"m_InitialState")&&off==28))kind=17;}
 if(!std::strcmp(type,"ParticleNode")){if(!std::strcmp(name,"m_RandomSeed")&&off==24)kind=9;else if(!std::strcmp(name,"<particleSystem>k__BackingField")&&off==32)kind=18;}
 if(!kind){return false;}
 *out=&source_fields[kind];return true;
}
void*mp4_timeline_class(const Pin&){return pins?const_cast<Pin*>(&mp4_timeline_pins.plain):nullptr;}
bool game_call(){return main_thread;}bool mp4_control_source_pins_ready(){return pins;}bool mp4_stage_other_pins_ready(){return false;}bool mp4_prefix(const mp4game::Binding&){return pins;}bool mp4_hook_was_statically_verified(const mp4game::Binding&){return false;}
bool mp4_timeline_exact(void*p,const Pin&pin){auto i=objects.find(p);return i!=objects.end()&&!std::strcmp(i->second->type,pin.name);}bool mp4_alive(void*p){auto i=objects.find(p);return i!=objects.end()&&i->second->alive;}
bool mp4_type_is(void*p,const char*t){auto i=objects.find(p);if(i==objects.end())return false;const char*expected=!std::strcmp(t,"UnityEngine.Playables.PlayableDirector")?"Director":!std::strcmp(t,"UnityEngine.GameObject")?"GO":!std::strcmp(t,"UnityEngine.ParticleSystem")?"PS":t;return !std::strcmp(i->second->type,expected);}
bool mp4_actor_same_handle(mp4actor::Handle a,mp4actor::Handle b){return a.handle==b.handle&&a.version==b.version;}
struct Node{mp4actor::Handle h{};void*script=nullptr;std::vector<mp4actor::Handle>inputs;bool plain=false;};std::unordered_map<uintptr_t,Node>nodes;
void*mp4_timeline_script(mp4actor::Handle h){auto n=nodes.find(h.handle);return n!=nodes.end()&&n->second.h.version==h.version?n->second.script:nullptr;}
int inputs(mp4actor::Handle*h,Method*){auto n=nodes.find(h->handle);return n==nodes.end()||n->second.h.version!=h->version?-1:static_cast<int>(n->second.inputs.size());}
void input(mp4actor::Handle*h,int i,mp4actor::Handle*out,Method*){auto n=nodes.find(h->handle);*out=n==nodes.end()||i<0||size_t(i)>=n->second.inputs.size()?mp4actor::Handle{}:n->second.inputs[i];}
struct API{decltype(&inputs)playable_input_count=inputs;decltype(&input)playable_input=input;};API mp4_actor_state_api(){return {};}
int plain_type=0;void*mp4_type_get_object(void*){return &plain_type;}
void*get_type(mp4actor::Handle*h,Method*){auto n=nodes.find(h->handle);return n!=nodes.end()&&n->second.plain?&plain_type:nullptr;}
bool mp4_control_passive_graph(mp4ctl::Handle graph,mp4ctl::Handle node){auto n=nodes.find(node.handle);return graph.handle==42&&graph.version==2&&n!=nodes.end()&&n->second.h.version==node.version;}
bool mp4_control_passive_native(void*p,uintptr_t&native){native=0;return p&&mp4_alive(p)&&mp4_actor_field(p,16,native)&&native;}
bool mp4_director_node_schema(void*){return false;}bool mp4_activation_node_schema(void*){return false;}
struct Mp4SceneWitness{uint64_t epoch=1;};enum class Mp4TimelineProofPhase:uint8_t{admission,active,source_restore_plan,source_restored};enum class Mp4TimelineVerdict:uint8_t{unrecognized,closed,unclosed};
struct Mp4TimelineRuntime{void*element=nullptr,*clip=nullptr,*track=nullptr;mp4actor::Handle playable{},mixer{};uint8_t kind=0;};
struct Mp4TimelineContext{struct Identity{uintptr_t native=0x9090;uint32_t version=2;}identity{};mp4actor::Handle root{100,2,0};Mp4TimelineProofPhase phase=Mp4TimelineProofPhase::admission;Mp4SceneWitness witness{};void*director=nullptr,*asset=nullptr;mp4actor::Handle graph{};void*clips[4]{},*clip_tracks[4]{},*tracks[4]{},*elements[4]{};mp4actor::Handle compiled[4]{},nodes[8]{};size_t clip_count=1,track_count=1,element_count=1,node_count=0;};
bool mp4_timeline_current(const Mp4TimelineContext&){return source&&main_thread;}
int mp4_timeline_node_index(const Mp4TimelineContext&c,mp4actor::Handle node){for(size_t i=0;i<c.node_count;++i)if(mp4_actor_same_handle(c.nodes[i],node))return int(i);return -1;}
bool mp4_stage_other_same_graph(const Mp4TimelineContext&c,mp4actor::Handle node,void*script){return mp4_timeline_current(c)&&mp4_timeline_node_index(c,node)>=0&&mp4_timeline_script(node)==script;}
struct Mp4ControlPassiveImage{void*values[8]{};uintptr_t native[4]{};mp4ctl::Input input{};mp4ctl::Cache before{},after{};mp4ctl::Handle graph{},result{};const void*method=nullptr;};
Mp4ControlPassiveImage original{};uint64_t raw_receipt=9;
thread_local const Mp4ControlPassiveImage*mp4_control_passive_publishing=nullptr;thread_local uint64_t mp4_control_passive_publishing_receipt=0;
bool mp4_control_passive_raw_receipted(void*asset,void*director,void*owner,mp4ctl::Handle graph,mp4ctl::Handle result,uint64_t*out,Mp4ControlPassiveImage*raw=nullptr){if(out)*out=0;bool ok=raw_current&&asset==original.values[0]&&director==original.values[1]&&owner==original.values[2]&&mp4_actor_same_handle(graph,original.graph)&&mp4_actor_same_handle(result,original.result);if(ok){if(out)*out=raw_receipt;if(raw)*raw=original;}return ok;}
bool mp4_control_passive_receipted(void*a,void*d,void*o,mp4ctl::Handle g,mp4ctl::Handle r){uint64_t x=0;return cache_current&&mp4_control_passive_raw_receipted(a,d,o,g,r,&x);}
bool mp4_control_passive_same_input(const mp4ctl::Input&a,const mp4ctl::Input&b){return a.source_name==b.source_name&&a.source_default==b.source_default&&a.prefab==b.prefab&&a.seed==b.seed&&a.particles==b.particles&&a.time_control==b.time_control&&a.hierarchy==b.hierarchy&&a.post==b.post;}
void*authored_children[4]{};size_t authored_count=1;
struct Mp4ControlEdgeObservation{void*asset=nullptr,*owner=nullptr,*source=nullptr;mp4ctl::Input input{};void*children[4]{};size_t count=0;};
template<class Current>bool mp4_control_edge_observe_impl(const Mp4TimelineContext&c,size_t index,Mp4ControlEdgeObservation&out,Current current){if(!current(c)||index>=c.clip_count)return false;out.asset=original.values[0];out.owner=original.values[2];out.source=original.values[3];out.input=original.input;out.count=authored_count;for(size_t i=0;i<out.count;++i)out.children[i]=authored_children[i];return true;}
bool mp4_stage_admission_particle(const Mp4SceneWitness&,void*,void*,mp4actor::Handle,mp4actor::Handle,void*,void*,uint32_t){return admitted;}
namespace mp4world {using AnimationGraph=mp4actor::Handle;}
namespace mp4_source_factory {
struct Object{uintptr_t object=0,klass=0,native=0;uint32_t instance=0;};
struct Input{uintptr_t asset=0,game_object=0,method=17,return_pc=19;mp4world::AnimationGraph graph{};};
struct Image{Object asset{},game_object{};uintptr_t graph_native=0x9090;uint32_t graph_version=2;};
struct Ticket{uint64_t serial=0,generation=0;uint16_t depth=0;};
struct Context{Ticket ticket{},parent{0,0,0};Input input{};Image image{};};
struct Receipt{Context source{};mp4actor::Handle root{100,2,0};};
}
mp4_source_factory::Context parent_context{};bool parent_live=true,parent_completed=true;
bool mp4_source_factory_context(mp4world::AnimationGraph g,mp4_source_factory::Context*out){*out={};if(!parent_live||!mp4_actor_same_handle(g,parent_context.input.graph))return false;*out=parent_context;return true;}
bool mp4_source_factory_receipt(mp4_source_factory::Ticket t,mp4_source_factory::Receipt*out){if(!parent_completed||t.serial!=parent_context.ticket.serial||t.generation!=parent_context.ticket.generation||t.depth!=parent_context.ticket.depth)return false;out->source=parent_context;return true;}
#include "control-source-admission-pins.inc"
#include "control-source-admission-host.cpp"
Obj asset("Control"),director("Director"),owner("GO"),source_go("GO"),child("Director"),clip("Clip"),track("Track"),element("Runtime"),timeline("Timeline"),script("DirectorNode"),activation("ActivationNode"),particle("ParticleNode"),ps("PS");
mp4actor::Handle graph{42,2,0},root{101,2,0},leaf{102,2,0},mixer{103,2,0};
bool plan(const Mp4TimelineContext&,const Mp4ControlPassiveImage&,const Mp4ControlSourceLeaf&v){++plan_calls;if(testing&&scenario=="plan_mutates_topology")nodes[root.handle].inputs.clear();if(testing&&scenario=="plan_mutates_target"){void*p=&owner;set(script,16,p);}if(testing&&scenario=="plan_changes_factory")++raw_receipt;if(testing&&scenario=="plan_changes_source")source=false;assert(v.target);return plan_ok;}
int main(int argc,char**argv){assert(argc==2);scenario=argv[1];for(auto*o:{&asset,&director,&owner,&source_go,&child,&clip,&track,&element,&timeline,&script,&activation,&particle,&ps})add(*o);
 for(size_t i=0;i<32;++i){uint32_t bits=uint32_t(i)<<16;std::memcpy(source_types[i].bytes+8,&bits,4);source_fields[i].type=&source_types[i];}
 for(size_t k=0;k<3;++k)for(size_t i=0;i<8;++i)methods[k][i].entry=mp4_control_source_admission_pins.callbacks[k][i].rva;
 mp4_actor_profile.playable_type.rva=reinterpret_cast<uintptr_t>(get_type);set(script,16,static_cast<void*>(&child));set(activation,16,static_cast<void*>(&source_go));set(activation,24,int32_t(0));set(particle,32,static_cast<void*>(&ps));set(particle,24,uint32_t(77));
 nodes[root.handle]={root,nullptr,{leaf},true};nodes[leaf.handle]={leaf,&script,{},false};nodes[mixer.handle]={mixer,nullptr,{root},true};authored_children[0]=&child;
 parent_context.ticket={5,7,1};parent_context.input.asset=reinterpret_cast<uintptr_t>(&timeline);parent_context.input.game_object=reinterpret_cast<uintptr_t>(&owner);parent_context.input.graph=graph;parent_context.image.asset={reinterpret_cast<uintptr_t>(&timeline),11,22,33};parent_context.image.game_object={reinterpret_cast<uintptr_t>(&owner),44,55,66};
 original.values[0]=&asset;original.values[1]=&director;original.values[2]=&owner;original.values[3]=&source_go;original.graph=graph;original.result=root;original.after.director=1;
 set(clip,40,static_cast<void*>(&asset));set(element,24,static_cast<void*>(&clip));set(element,32,root);set(element,48,mixer);
 Mp4TimelineContext c{};c.director=&director;c.asset=&timeline;c.graph=graph;c.clips[0]=&clip;c.clip_tracks[0]=&track;c.tracks[0]=&track;c.elements[0]=&element;c.compiled[0]=mixer;c.node_count=3;c.nodes[0]=root;c.nodes[1]=leaf;c.nodes[2]=mixer;
 Mp4TimelineRuntime r{&element,&clip,&track,root,mixer,0};mp4_control_source_plan=plan;
 const bool particle_case=scenario.rfind("particle",0)==0,active_case=scenario.rfind("activation",0)==0;
 if(particle_case){nodes[leaf.handle].script=&particle;authored_count=0;original.after.director=0;original.input.particles=1;}
 if(active_case){nodes[leaf.handle].script=&activation;authored_count=0;original.after.director=0;original.after.active=1;}
 if(scenario=="empty"){nodes[root.handle].inputs.clear();authored_count=0;original.after.director=0;mp4_control_source_plan=nullptr;}
 if(scenario=="parent_context_absent")parent_live=false;
 if(scenario=="observe_missing_guard"){}else{mp4_control_passive_publishing=&original;mp4_control_passive_publishing_receipt=raw_receipt;}
 if(scenario=="observe_wrong_guard_receipt")++mp4_control_passive_publishing_receipt;
 if(scenario=="observe_pins")pins=false;
 if(scenario=="observe_schema")field_schema=false;
 if(scenario=="observe_foreign")main_thread=false;
 if(scenario=="observe_prefab")original.input.prefab=&owner;
 if(scenario=="observe_time")original.input.time_control=1;
 if(scenario=="observe_unreceipted")raw_current=false;
 if(scenario=="observe_nonplain")nodes[root.handle].plain=false;
 if(scenario=="observe_unknown")nodes[leaf.handle].script=&asset;
 if(scenario=="observe_deep")nodes[leaf.handle].inputs.push_back(mixer);
 if(scenario=="observe_duplicate")nodes[root.handle].inputs.push_back(leaf);
 if(scenario=="observe_callback")++methods[0][6].entry;
 if(scenario=="observe_weak")weak_fail=true;
 if(scenario=="observe_limit")mp4_control_source_sequence=~uint64_t(0);
 const bool observed=scenario.rfind("observe_",0)!=0;
 assert(mp4_control_source_observe(original,raw_receipt)==observed);mp4_control_passive_publishing=nullptr;mp4_control_passive_publishing_receipt=0;
 if(scenario=="one_shot"){auto previous=nodes[root.handle].inputs;nodes[root.handle].inputs.clear();mp4_control_passive_publishing=&original;mp4_control_passive_publishing_receipt=raw_receipt;assert(!mp4_control_source_observe(original,raw_receipt));mp4_control_passive_publishing=nullptr;mp4_control_passive_publishing_receipt=0;nodes[root.handle].inputs=previous;}
 if(scenario=="outside_event"){assert(!mp4_control_source_observe(original,raw_receipt));}
 if(!observed){mp4_control_source_clear();std::free(mp4_control_source_bank);assert(roots.empty());return 0;}
 if(scenario=="parent_context_absent"){assert(!mp4_control_source_runtime(c,r));mp4_control_source_clear();std::free(mp4_control_source_bank);assert(roots.empty());return 0;}
 assert(mp4_control_source_runtime(c,r));testing=true;
 if(scenario=="parent_receipt_expired")parent_completed=false;
 if(scenario=="parent_ticket_changed")++parent_context.ticket.serial;
 if(scenario=="parent_generation_changed")++parent_context.ticket.generation;
 if(scenario=="parent_asset_changed")++parent_context.image.asset.native;
 if(scenario=="parent_owner_changed")++parent_context.image.game_object.instance;
 if(scenario=="parent_graph_changed")++parent_context.image.graph_version;
 if(scenario=="parent_root_changed")++c.root.version;
 if(scenario=="parent_context_asset_changed")c.asset=&asset;

 if(scenario=="unsupported_next_factory"){++raw_receipt;original.input.time_control=1;mp4_control_passive_publishing=&original;mp4_control_passive_publishing_receipt=raw_receipt;assert(!mp4_control_source_observe(original,raw_receipt));mp4_control_passive_publishing=nullptr;mp4_control_passive_publishing_receipt=0;}
 if(scenario=="repeat_factory"){++raw_receipt;mp4_control_passive_publishing=&original;mp4_control_passive_publishing_receipt=raw_receipt;assert(mp4_control_source_observe(original,raw_receipt));mp4_control_passive_publishing=nullptr;mp4_control_passive_publishing_receipt=0;}

 if(scenario=="no_plan")mp4_control_source_plan=nullptr;
 if(scenario=="reject_plan")plan_ok=false;
 if(scenario=="wrong_phase")c.phase=Mp4TimelineProofPhase::active;
 if(scenario=="wrong_element")r.element=&asset;
 if(scenario=="wrong_clip")r.clip=&asset;
 if(scenario=="wrong_track")r.track=&asset;
 if(scenario=="wrong_kind")r.kind=1;
 if(scenario=="wrong_mixer")r.mixer=root;
 if(scenario=="duplicate_element"){c.element_count=2;c.elements[1]=&element;}
 if(scenario=="duplicate_clip"){c.clip_count=2;c.clips[1]=&clip;c.clip_tracks[1]=&track;}
 if(scenario=="duplicate_track"){c.track_count=2;c.tracks[1]=&track;c.compiled[1]=mixer;}
 if(scenario=="wrong_raw_receipt")++raw_receipt;
 if(scenario=="raw_expired")raw_current=false;
 if(scenario=="cache_changed")cache_current=false;
 if(scenario=="source_changed")source=false;
 if(scenario=="pins_changed")pins=false;
 if(scenario=="schema_changed")field_schema=false;
 if(scenario=="graph_changed")c.graph.version=3;
 if(scenario=="node_version")++nodes[leaf.handle].h.version;
 if(scenario=="topology_changed")nodes[root.handle].inputs.clear();
 if(scenario=="callback_changed")++methods[0][7].entry;
 if(scenario=="target_changed")set(script,16,static_cast<void*>(&director));
 if(scenario=="native_changed")set(child,16,uintptr_t(222));
 if(scenario=="target_dead")child.alive=false;
 if(scenario=="authored_missing")authored_count=0;
 if(scenario=="authored_extra"){authored_count=2;authored_children[1]=&director;}
 if(scenario=="weak_expired")roots.erase(mp4_control_source_bank[0].leaves[0].weak_script),mp4_control_source_bank[0].leaves[0].weak_script=0;
 if(scenario=="activation_wrong_target")set(activation,16,static_cast<void*>(&owner));
 if(scenario=="activation_wrong_post")set(activation,24,int32_t(1));
 if(scenario=="activation_wrong_flag")original.after.active=0;
 if(scenario=="particle_unadmitted")admitted=false;
 if(scenario=="particle_wrong_seed")set(particle,24,uint32_t(78));
 if(scenario=="particle_wrong_flag")original.input.particles=0;
 const bool ok=scenario=="normal"||scenario=="activation"||scenario=="particle"||scenario=="empty"||scenario=="repeat_factory"||scenario=="one_shot"||scenario=="outside_event";
 assert(mp4_control_source_runtime(c,r)==ok);
 if(ok&&scenario!="empty"){void*s=nodes[leaf.handle].script;assert(mp4_control_source_node_verdict(c,leaf,s)==Mp4TimelineVerdict::closed);assert(mp4_control_source_userdata(c,leaf,s,&timeline));assert(!mp4_control_source_runtime(c,r,mixer,&script));}
 mp4_control_source_clear();std::free(mp4_control_source_bank);mp4_control_source_bank=nullptr;assert(roots.empty());
}
