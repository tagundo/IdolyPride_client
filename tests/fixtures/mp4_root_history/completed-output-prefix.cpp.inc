#include <cstdint>
#include <cstddef>
#include <cstdlib>
#include <cassert>
namespace mp4actor{struct Handle{uintptr_t handle=0;uint32_t version=4,padding=0;};}
namespace mp4child{struct Graph{uintptr_t handle=100;uint32_t version=4,padding=0;};}
namespace mp4world{struct AnimationOutput{uintptr_t handle=400;uint32_t version=4,padding=0;};}
namespace mp4_director_maintenance{struct Call{uint64_t serial=11;};}
namespace mp4_director_birth{struct SourceTuple{};struct Playable{uintptr_t handle=0;uint32_t version=4;};struct Receipt{bool returned=false;Playable root{};struct{mp4child::Graph graph{};}input;uint64_t birth=0,factory=0;mp4_director_maintenance::Call parent{};};}
struct Mp4ChildFactoryContext{mp4_director_maintenance::Call operation{};mp4_director_birth::SourceTuple owner{};struct{mp4child::Graph graph{};}input;struct{struct{uintptr_t native=300;}graph;uint64_t birth_receipt=17,factory_receipt=19;}birth;};struct Method{};
struct Model{bool thread=true,held=true,lineage=true,invoked=true,journal=true,source_image=true,complete=true,graph_valid=true,root_valid=true,output_valid=true,field=true;unsigned reads=0,counts=0;uintptr_t graph_native=300,back=100,output_native=500;uint32_t version=4;int size=1;bool change_count=false,missing_output=false;mp4_director_birth::Receipt completed{};}model;
bool mp4_output_calls_verified=true;uintptr_t image_base=0;struct{struct{size_t node_graph=40;}native_graph;struct{size_t slot_output=40;}native_output;}mp4_actor_profile;
struct Binding{uintptr_t rva=0;};bool output_valid(mp4world::AnimationOutput*,Method*){++model.reads;return model.output_valid;}int32_t count(mp4child::Graph*,Method*){++model.reads;++model.counts;return model.size+(model.change_count&&model.counts>1?1:0);}void at(mp4child::Graph*,int32_t,mp4world::AnimationOutput*out,Method*){++model.reads;*out={model.missing_output?402u:400u,4,0};}
struct{Binding output_valid{(uintptr_t)::output_valid},graph_output_count{(uintptr_t)count},graph_output{(uintptr_t)at};}mp4_world_profile;
bool game_call(){return model.thread;}bool mp4_actor_clock_held(void*){return model.held;}bool mp4_child_lineage_current(){return model.lineage;}bool mp4_child_invoked_operation(mp4_director_maintenance::Call){return model.invoked;}bool mp4_child_graph_same(mp4child::Graph a,mp4child::Graph b){return a.handle==b.handle&&a.version==b.version;}bool mp4_child_call_same(mp4_director_maintenance::Call a,mp4_director_maintenance::Call b){return a.serial==b.serial;}
struct{struct Journal{bool current_call(mp4_director_maintenance::Call){return model.journal;}}journal_value;Journal&journal(){return journal_value;}}mp4_child_pending_host;
bool mp4_root_history_source_image_for_operation(mp4_director_maintenance::Call,mp4_director_birth::SourceTuple,uint64_t*out){*out=23;return model.source_image;}bool mp4_child_completed_factory(const Mp4ChildFactoryContext&,mp4_director_birth::Receipt*out){*out=model.completed;return model.complete;}
struct Api{bool(*graph_valid)(mp4actor::Handle*,Method*)=[](mp4actor::Handle*,Method*){++model.reads;return model.graph_valid;};bool(*playable_valid)(mp4actor::Handle*,Method*)=[](mp4actor::Handle*,Method*){++model.reads;return model.root_valid;};};Api mp4_actor_state_api(){return {};}
template<class T>bool mp4_actor_field(void*p,size_t offset,T&out){++model.reads;if(!model.field)return false;uintptr_t v=0;const uintptr_t key=(uintptr_t)p;if(key==100&&offset==40)v=model.graph_native;else if(key==300&&offset==16)v=model.back;else if(key==400&&offset==32)v=model.version;else if(key==400&&offset==40)v=model.output_native;else return false;out=static_cast<T>(v);return true;}
