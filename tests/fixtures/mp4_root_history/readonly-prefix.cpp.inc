#include <cstdint>
#include <cstddef>
#include <cstring>
#include <cstdlib>
#include <atomic>
#include <cassert>
namespace mp4actor{struct Handle{uintptr_t handle=0;uint32_t version=0,padding=0;};}
namespace mp4_director_birth{struct SourceTuple{uintptr_t director=0,asset=0,game_object=0,klass=0,method=0;uint64_t epoch=0,capture=0;};struct Playable{uintptr_t handle=0;uint32_t version=0,padding=0;};}
namespace mp4child{using Graph=mp4actor::Handle;enum class Result:int{ok=0,waiting=1,invalid=-1,stale=-2,unsupported=-3,failed=-4};constexpr size_t max_directors=65,max_edges=512;struct State{mp4_director_birth::SourceTuple owner{};uintptr_t root_asset=0;Graph graph{};mp4_director_birth::Playable root{};double time=0,root_speed=1;int32_t mode=0,state=0;};struct Edge{uint16_t parent=0,child=0;uint64_t receipt=0;};}
namespace mp4world{struct DirectorGraphIdentity{uintptr_t native=0,slot=0;uint32_t version=0;};}
namespace mp4dn{enum class Result:int{ok=0,stale=-1};enum class Round{source};struct Key{void*director=nullptr,*asset=nullptr,*target=nullptr;};struct Node{Key key{};void*script=nullptr;mp4actor::Handle graph{},runtime{},node{};uint64_t factory=0,birth=0;};}
namespace mp4drive{enum class Result:int{ok=0,failed=-1};struct Role{mp4dn::Node node{};uint64_t source_capture=0;bool active=false;};using Emit=bool(*)(void*,const Role&);}
struct Mp4TimelineContext{void*director=nullptr,*asset=nullptr;mp4world::DirectorGraphIdentity identity{};mp4actor::Handle root{};};
struct Mp4DirectorNodeVisit{mp4dn::Round round;bool(*emit)(void*,const mp4dn::Node&);void*context;};
struct{unsigned depth=0;}mp4_raw_original_operation;struct{struct{uint64_t generation=7;}source;}mp4_scene_host;
namespace idoly_mp4_runtime{struct{uint64_t generation=9;}job;}
struct{mp4_director_birth::SourceTuple tuples[65]{};size_t count=2;uint64_t capture=11;void*asset=(void*)0x777;}mp4_birth_catalogue;
struct{struct Entry{Mp4TimelineContext*context=nullptr;struct{struct{struct{uint64_t serial=0;}ticket;}source;}construction;}roots[65]{};size_t count=2;uint64_t serial=13;}mp4_source_director_plans;
struct Model{int mode=0;bool thread=true,window=true,bindings=true,plan=true,native=true,publication=true,node=true,dependencies=true,catalogue=true,active=true,full=false,driver=true;unsigned calls=0,writes=0;mp4child::State live[2]{},saved[2]{};Mp4TimelineContext contexts[2]{};mp4dn::Node role{};}model;
bool game_call(){return model.thread;}bool mp4_stage_source_window(){return model.window;}bool mp4_child_readonly_bindings(){return model.bindings;}
bool mp4_child_native_owner(void*,const mp4_director_birth::SourceTuple&t){return model.native&&t.epoch==7&&t.capture==11;}
bool mp4_child_tuple_same(const mp4_director_birth::SourceTuple&a,const mp4_director_birth::SourceTuple&b){return a.director==b.director&&a.asset==b.asset&&a.game_object==b.game_object&&a.klass==b.klass&&a.method==b.method&&a.epoch==b.epoch&&a.capture==b.capture;}
bool mp4_child_graph_same(mp4child::Graph a,mp4child::Graph b){return a.handle==b.handle&&a.version==b.version;}bool mp4_child_playable_same(mp4_director_birth::Playable a,mp4_director_birth::Playable b){return a.handle==b.handle&&a.version==b.version;}
size_t index(void*d){for(size_t i=0;i<2;++i)if(model.live[i].owner.director==(uintptr_t)d)return i;assert(false);return 0;}
bool mp4_child_publication(const mp4_director_birth::SourceTuple&t,mp4child::Graph g,mp4world::DirectorGraphIdentity*out,mp4_director_birth::Playable*root){++model.calls;auto i=index((void*)t.director);if(!model.publication||!mp4_child_graph_same(g,model.live[i].graph))return false;*out=model.contexts[i].identity;*root=model.live[i].root;return true;}
double get_time(void*d,void*){++model.calls;return model.live[index(d)].time;}int32_t get_mode(void*d,void*){++model.calls;return model.live[index(d)].mode;}int32_t get_state(void*d,void*){++model.calls;return model.live[index(d)].state;}
struct{decltype(&get_time)director_get_time=get_time;decltype(&get_mode)director_get_mode=get_mode;struct{decltype(&get_state)director_state=get_state;}automatic_playback;}mp4_api;
void mp4_child_graph(void*d,mp4child::Graph*out,void*){++model.calls;*out=model.live[index(d)].graph;}
double mp4_child_root_speed(const mp4_director_birth::Playable*p,void*){++model.calls;for(auto&s:model.live)if(s.root.handle==p->handle)return s.root_speed;return 0;}
bool mp4_stage_source_catalogue(){return model.catalogue;}bool mp4_source_director_plan_current(){return model.plan;}template<class T>bool mp4_source_director_plan_build(const T&){return model.plan;}
bool mp4_director_node_current(void*,const mp4dn::Node&){return model.node;}bool mp4_child_driving_runtime_active(Mp4TimelineContext&,const mp4dn::Node&,bool*out){*out=model.active;return model.plan;}
struct{bool captured(){return true;}bool current(){return model.node;}}mp4_director_nodes;
mp4dn::Result mp4_director_node_context(Mp4DirectorNodeVisit*v,Mp4TimelineContext&c){if(c.director!=model.contexts[0].director)return mp4dn::Result::ok;if(model.mode==15)return mp4dn::Result::stale;return v->emit(v->context,model.role)?mp4dn::Result::ok:mp4dn::Result::stale;}
bool mp4_child_dependencies(void*,const mp4_director_birth::SourceTuple*,size_t,mp4child::Edge*out,size_t,size_t*count,uint64_t*receipt){out[0]={0,1,17};*count=1;*receipt=19;return model.dependencies;}
mp4child::Result mp4_child_dependencies_current(void*,const mp4child::Edge*,size_t,uint64_t receipt){return model.dependencies&&receipt==19?mp4child::Result::ok:mp4child::Result::stale;}
bool mp4_child_lineage_current(){return model.full;}struct{bool captured(){return model.full;}size_t count(){return 2;}const mp4child::State*source(size_t i){return &model.saved[i];}}mp4_child_source_scope;
struct{bool captured(){return model.full;}bool failed(){return !model.driver;}}mp4_child_driving_scope;
bool mp4_child_driving_bindings(void*){return model.driver;}bool mp4_child_driving_source_current(void*,uint64_t epoch,uintptr_t asset){return model.full&&epoch==7&&asset==0x777;}
bool mp4_child_driving_same_node(const mp4dn::Node&a,const mp4dn::Node&b){return a.script==b.script&&a.node.handle==b.node.handle&&a.key.director==b.key.director&&a.key.target==b.key.target;}
mp4drive::Result mp4_child_driving_roles(mp4dn::Round,mp4drive::Emit emit,void*c,uint64_t*recipe){*recipe=23;mp4drive::Role role{model.role,29,model.active};if(model.mode==31)role.source_capture=0;if(model.mode==32)role.node.script=(void*)0x999;if(model.mode==33)return mp4drive::Result::ok;return emit(c,role)?mp4drive::Result::ok:mp4drive::Result::failed;}
