#include <cstdint>
#include <cstddef>
#include <cstdlib>
#include <new>
#include <cassert>
#include <atomic>
namespace mp4_director_maintenance{enum class Kind{play=1,stop=2,rebuild=3,saved_evaluate=5};struct Call{Kind kind=Kind::saved_evaluate;uint64_t epoch=7,serial=11;uintptr_t source_asset=99,receiver=1,method=3;uint64_t original_receipt=13;};}
namespace mp4world{struct DirectorGraphIdentity{uintptr_t native=0,slot=0;uint32_t version=2;};}
namespace mp4_director_birth{struct Playable{uintptr_t handle=0;uint32_t version=2,padding=0;};}
namespace mp4child{struct Owner{uintptr_t director=1,asset=11;uint64_t epoch=7;};struct Handle{uintptr_t handle=0;uint32_t version=2,pad=0;};struct State{Owner owner{};uintptr_t root_asset=99;double time=1.5,root_speed=1;int mode=1,state=0;};struct Checkpoint{uint64_t epoch=7;uintptr_t root_asset=99,director=2;Handle graph{0x201,2,0},root{0x301,2,0};double time=2.5;int mode=1,state=0;mp4_director_maintenance::Call saved_evaluate{};};using Graph=Handle;}
enum class Mp4TimelineProofPhase{admission,active,source_restore_plan,source_restored};struct Witness{uint64_t generation=7;void*director=(void*)1;};
struct Mp4TimelineContext{Mp4TimelineProofPhase phase=Mp4TimelineProofPhase::active;Witness witness{};void*director=nullptr,*asset=nullptr,*root_script=nullptr;mp4world::DirectorGraphIdentity identity{};mp4child::Handle graph{},root{};};
struct Image{bool captured_ok=true;bool captured()const{return captured_ok;}}images[4];
struct Entry{Mp4TimelineContext*context=nullptr;Image*image=nullptr;};
struct{bool ready=true,inside=false;size_t count=2;uint64_t epoch=7,job=9,withdraw=0;Entry entries[65]{};}mp4_root_history_initial_cohort;
struct Record{bool retired=false;uint64_t id=0;mp4child::Owner owner{};Mp4TimelineContext*context=nullptr;Image*image=nullptr;struct{uint64_t producer=1,callback=2,output=3;}receipts;};
struct{bool inside=false;size_t depth=0;uint64_t epoch=7,job=9;Record records[65]{};}mp4_root_history_lineage_pool;
struct Proof{mp4child::Owner owner{};mp4world::DirectorGraphIdentity graph{};mp4_director_birth::Playable root{};uint64_t source_capture=0;};
struct Mp4ChildLineageBank{struct Node{Proof current{};bool factory_returned=false;}nodes[65]{};size_t count=2;}mp4_child_lineage_bank;
struct{unsigned depth=0;}mp4_raw_original_operation;struct{Witness source{};void*root_asset=(void*)99;bool active=true,invalidated=false,releasing=false;unsigned captured=15,prepared=15,all=15;}mp4_scene_host;
std::atomic<uint64_t>mp4_root_capture_withdraw_sequence{0};namespace idoly_mp4_runtime{struct{uint64_t generation=9;}job;}
namespace mp4play{enum class OperationStep{restore_evaluate,restore_state};}
struct Request{bool complete=true;struct{bool issued=true,returned=true;mp4_director_maintenance::Call call{};}mutation;mp4child::State source{};};struct{Request requests[2]{};}mp4_main_control_bank;
struct Model{bool speeds=true,restoring=true,owner=true,held=true,bindings=true,lineage=true,source_current=true,fields=true,sealed=true,current=true,identity=true,publication=true,checkpoint=true,marker=true;size_t count=2;mp4child::State states[2]{};mp4child::Checkpoint child{};Mp4TimelineContext before[2]{},fresh[2]{};unsigned reads=0,writes=0;}model;
bool game_call(){return model.owner;}bool mp4_actor_clock_held(void*){return model.held;}bool mp4_child_readonly_bindings(){return model.bindings;}bool mp4_child_lineage_current(){return model.lineage;}bool mp4_scene_source_current(){return model.source_current&&model.current;}
bool mp4_scene_same_source(const Witness&a,const Witness&b){return a.generation==b.generation&&a.director==b.director;}bool mp4_root_history_initial_sealed(uint64_t){return model.sealed;}
bool mp4_child_tuple_same(const mp4child::Owner&a,const mp4child::Owner&b){return a.director==b.director&&a.asset==b.asset&&a.epoch==b.epoch;}
bool mp4_child_playable_same(mp4_director_birth::Playable a,mp4_director_birth::Playable b){return a.handle==b.handle&&a.version==b.version;}
mp4child::Graph mp4_child_identity_handle(const mp4world::DirectorGraphIdentity&i){return {i.slot,i.version,0};}
bool mp4_child_native_owner(void*,const mp4child::Owner&){return model.identity;}
Record*mp4_root_history_record(uint64_t id){++model.reads;return id&&id<=2?&mp4_root_history_lineage_pool.records[id-1]:nullptr;}
bool mp4_root_history_record_identity(const Record&r,const mp4child::Owner&o,mp4child::Graph g,mp4_director_birth::Playable root){return mp4_child_tuple_same(r.owner,o)&&r.context&&r.context->identity.slot==g.handle&&r.context->identity.version==g.version&&r.context->root.handle==root.handle&&r.context->root.version==root.version;}
bool mp4_timeline_current(const Mp4TimelineContext&){assert(false&&"readonly final query entered aggregate owner/current");return false;}

bool mp4_child_publication(const mp4child::Owner&o,mp4child::Graph graph,mp4world::DirectorGraphIdentity*out,mp4_director_birth::Playable*root){++model.reads;for(size_t i=0;i<2;++i){const auto&p=mp4_child_lineage_bank.nodes[i].current;if(mp4_child_tuple_same(o,p.owner)&&graph.handle==p.graph.slot&&graph.version==p.graph.version){*out=p.graph;*root=p.root;return model.publication;}}return false;}
struct{bool child_fields_restored(){return model.fields;}bool root_speeds_restored(){return model.speeds;}size_t count(){return model.count;}const mp4child::State*source(size_t i){return i<2?&model.states[i]:nullptr;}bool director_fields_checkpoint(uintptr_t director,mp4child::Checkpoint&out){assert(director==2);out=model.child;return model.checkpoint;}}mp4_child_source_scope;
double get_time(void*,void*){++model.reads;return model.states[0].time;}int get_mode(void*,void*){++model.reads;return model.states[0].mode;}int get_state(void*,void*){++model.reads;return model.states[0].state;}
struct{void*director_evaluate=(void*)3;decltype(&get_time)director_get_time=get_time;decltype(&get_mode)director_get_mode=get_mode;struct{void*director_resume=(void*)7,*director_pause=(void*)5;decltype(&get_state)director_state=get_state;}automatic_playback;}mp4_api;
namespace idoly_mp4_playback{enum class Phase{restoring,playing};}namespace idoly_mp4_runtime{struct{bool automatic_source_playback_state_restored(uint64_t){return model.marker;}idoly_mp4_playback::Phase automatic_rebuild_phase(){return model.restoring?idoly_mp4_playback::Phase::restoring:idoly_mp4_playback::Phase::playing;}}game;}
