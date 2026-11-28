#include <cstdint>
#include <cstddef>
#include <cstring>
#include <cstdlib>
#include <cassert>
namespace mp4child{struct Graph{uintptr_t handle=0;uint32_t version=0,padding=0;};}
namespace mp4world{struct DirectorGraphIdentity{uintptr_t native=0,slot=0;uint32_t version=0;};}
namespace mp4_director_maintenance{enum class Kind{rebuild=3,native_phase=7};struct Call{Kind kind=Kind::rebuild;uint64_t epoch=7,serial=11;uintptr_t source_asset=2;uint64_t original_receipt=13;};struct Provisional{};}
namespace mp4_director_birth{struct SourceTuple{uintptr_t director=1,asset=2,game_object=3;};struct Playable{uintptr_t handle=200;uint32_t version=4,padding=0;};struct Input{uintptr_t asset=2,game_object=3;mp4child::Graph graph{100,4,0};};struct Receipt{Input input{};Playable root{};mp4_director_maintenance::Call parent{};uint64_t birth=17,factory=19;bool returned=true;};}
namespace mp4_source_factory{struct Receipt{struct{struct{uint64_t serial=23,generation=29;}ticket;mp4_director_birth::Input input{};}source;mp4_director_birth::Playable root{};};}
enum class Mp4TimelineProofPhase{admission=0,active=1,source_restore_plan=2,source_restored=3,source_bootstrap_plan=4};struct Mp4TimelineContext{Mp4TimelineProofPhase phase=Mp4TimelineProofPhase::active;void*director=(void*)1,*asset=(void*)2;struct{uint64_t generation=7;}witness;mp4world::DirectorGraphIdentity identity{300,100,4};mp4child::Graph graph{100,4,0};mp4_director_birth::Playable root{};};
struct Proof{mp4_director_birth::SourceTuple owner{};mp4world::DirectorGraphIdentity graph{300,100,4};mp4_director_birth::Playable root{};uint64_t source_capture=2;};struct Mp4ChildLineageBank{struct Node{Proof current{};bool factory_returned=false;mp4_director_birth::Receipt pending{};};};struct{Mp4ChildLineageBank::Node nodes[2]{};size_t count=1;}mp4_child_lineage_bank;
struct Record{bool retired=false,private_birth=true;mp4_source_factory::Receipt ordinary{};mp4_director_birth::Receipt birth{};}record;
struct Model{int mode=0;bool thread=true,current=true,held=true,lineage=true,owner=true,ordinary=true,record=true,promise=true,complete=true,publication=true,completed_graph=true,operation=true,phase_current=true;mp4_director_birth::Receipt actual{};mp4_director_maintenance::Call call{};unsigned queries=0;}model;
struct{void*root_asset=(void*)2;}mp4_scene_host;
bool game_call(){return model.thread;}bool mp4_timeline_current(const Mp4TimelineContext&){return model.current;}bool mp4_actor_clock_held(void*){return model.held;}bool mp4_timeline_source_plan_phase(Mp4TimelineProofPhase p){return p==Mp4TimelineProofPhase::admission||p==Mp4TimelineProofPhase::source_bootstrap_plan;}
bool mp4_director_actual_operation(mp4_director_maintenance::Call*out){*out=model.call;return model.operation;}bool mp4_native_phase_call_current(const mp4_director_maintenance::Call&,uint64_t*tick,uint8_t*phase){*tick=1;*phase=2;return model.phase_current;}
bool mp4_child_lineage_current(){return model.lineage;}bool mp4_child_native_owner(void*,const mp4_director_birth::SourceTuple&){return model.owner;}bool mp4_child_graph_same(mp4child::Graph a,mp4child::Graph b){return a.handle==b.handle&&a.version==b.version;}mp4child::Graph mp4_child_identity_handle(const mp4world::DirectorGraphIdentity&i){return {i.slot,i.version,0};}
bool mp4_child_call_same(const mp4_director_maintenance::Call&a,const mp4_director_maintenance::Call&b){return a.epoch==b.epoch&&a.serial==b.serial&&a.original_receipt==b.original_receipt;}bool mp4_child_playable_same(mp4_director_birth::Playable a,mp4_director_birth::Playable b){return a.handle==b.handle&&a.version==b.version;}
Record*mp4_root_history_record(uint64_t){++model.queries;return model.record?&record:nullptr;}
bool mp4_source_director_plan_construction(const Mp4TimelineContext&,mp4_source_factory::Receipt*out){*out=record.ordinary;return model.ordinary;}
bool mp4_source_factory_receipt(decltype(mp4_source_factory::Receipt{}.source.ticket),mp4_source_factory::Receipt*out){*out=record.ordinary;return model.ordinary;}
bool mp4_child_completed_graph(const mp4_director_maintenance::Call&,const mp4_director_birth::SourceTuple&,mp4child::Graph,mp4child::Graph,mp4_director_birth::Receipt*out){*out=model.actual;return model.completed_graph;}
struct{bool provisional(const mp4_director_maintenance::Call&,mp4child::Graph,mp4_director_maintenance::Provisional&){return model.promise;}bool completed(mp4_director_maintenance::Provisional,mp4_director_birth::Receipt&out){out=model.actual;return model.complete;}}mp4_child_birth_scope;
bool mp4_child_publication(const mp4_director_birth::SourceTuple&,mp4child::Graph,mp4world::DirectorGraphIdentity*out,mp4_director_birth::Playable*root){*out={300,100,4};*root=model.actual.root;return model.publication;}
