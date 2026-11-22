#include <cstddef>
#include <cstdint>
#include <cassert>
#include <cstring>
#include <stdexcept>
#include <cstdio>
namespace mp4_director_maintenance{enum class Kind:uint8_t{play=1,stop=2,rebuild=3,zero_evaluate=4,saved_evaluate=5,maintenance=6,native_phase=7};struct Call{Kind kind=Kind::play;uint64_t epoch=0,serial=0;uintptr_t source_asset=0,receiver=0,method=0;uint64_t original_receipt=0;};}
namespace mp4_director_birth{struct SourceTuple{uintptr_t director=0,asset=0,game_object=0,klass=0,method=0;uint64_t epoch=0,capture=0;};struct Playable{uintptr_t handle=0;uint32_t version=0,padding=0;};}
namespace mp4child{struct Graph{uintptr_t handle=0;uint32_t version=0,padding=0;};struct State{mp4_director_birth::SourceTuple owner{};uintptr_t root_asset=0;};struct Mutation{mp4_director_maintenance::Call call{};bool issued=false,returned=false;};}
namespace mp4world{struct DirectorGraphIdentity{uintptr_t native=0,slot=0;uint32_t version=0;};}
struct Mp4ChildLineageProof{mp4_director_birth::SourceTuple owner{};mp4world::DirectorGraphIdentity graph{};mp4_director_birth::Playable root{};uint64_t source_capture=0;};
struct Mp4ChildExecutionBank{struct Record{mp4child::State source{};mp4child::Graph before{};mp4child::Mutation mutation{};uint64_t ticket=0;bool finished=false,settled=false;};Record records[512]{};size_t count=0;bool running=false;}mp4_child_execution_bank;
struct Mp4ChildModuleOperations{struct Before{Mp4ChildLineageProof source{};uint64_t actual_capture=0;bool retired=false;};struct Record{mp4child::State source{};Mp4ChildLineageProof before{};mp4_director_maintenance::Kind kind=mp4_director_maintenance::Kind::stop;mp4_director_maintenance::Call call{};uint64_t ticket=0,original_receipt=0;size_t before_begin=0,before_count=0;bool entered=false,returned=false,finished=false,abandoned=false;};Record records[512]{};Before before[4096]{};size_t count=0,before_count=0;}mp4_child_module_operations;
struct{struct{void*director_resume=(void*)0x110,*director_pause=(void*)0x120,*director_rebuild=(void*)0x130,*director_play=(void*)0x140;}automatic_playback;void*director_evaluate=(void*)0x150;}mp4_api;
struct{void*director=(void*)0x220;}mp4_birth_catalogue;
struct{uint64_t epoch=0,serial=0,receipt=0;uintptr_t root_asset=0,director=0,method=0;uint8_t kind=0;unsigned depth=0;bool invoked=false;}mp4_raw_original_operation;
struct{bool thread=true,planned=true,invoked=true,native=true,phase=true,throw_planned=false,old_graph_available=false;uint64_t tick=0;uint8_t phase_index=0;}model;
bool game_call(){return model.thread;}
bool mp4_child_call_same(const mp4_director_maintenance::Call&a,const mp4_director_maintenance::Call&b){return a.kind==b.kind&&a.epoch==b.epoch&&a.serial==b.serial&&a.source_asset==b.source_asset&&a.receiver==b.receiver&&a.method==b.method&&a.original_receipt==b.original_receipt;}
bool mp4_child_tuple_same(const mp4_director_birth::SourceTuple&a,const mp4_director_birth::SourceTuple&b){return a.director==b.director&&a.asset==b.asset&&a.game_object==b.game_object&&a.klass==b.klass&&a.method==b.method&&a.epoch==b.epoch&&a.capture==b.capture;}
bool mp4_child_graph_same(mp4child::Graph a,mp4child::Graph b){return a.handle==b.handle&&a.version==b.version;}
bool mp4_child_playable_same(mp4_director_birth::Playable a,mp4_director_birth::Playable b){return a.handle==b.handle&&a.version==b.version;}
mp4child::Graph mp4_child_identity_handle(mp4world::DirectorGraphIdentity x){return{x.slot,x.version,0};}
bool mp4_child_planned_operation(const mp4_director_maintenance::Call&c){if(model.throw_planned)throw std::runtime_error("planned");const auto&r=mp4_raw_original_operation;return model.planned&&r.depth&&r.kind==uint8_t(c.kind)&&r.epoch==c.epoch&&r.serial==c.serial&&r.receipt==c.original_receipt&&r.root_asset==c.source_asset&&r.director==c.receiver&&r.method==c.method;}
bool mp4_child_invoked_operation(const mp4_director_maintenance::Call&c){return model.invoked&&mp4_raw_original_operation.invoked&&mp4_child_planned_operation(c);}
struct{struct Journal{bool alive=true,bad=false,current=true;mp4_director_maintenance::Call value{};bool active()const{return alive;}bool failed()const{return bad;}const mp4_director_maintenance::Call&call()const{return value;}bool current_call(const mp4_director_maintenance::Call&c)const{return alive&&!bad&&current&&mp4_raw_original_operation.invoked&&mp4_child_call_same(c,value);}}j;const Journal&journal()const{return j;}Journal&journal(){return j;}}mp4_child_pending_host;
struct{bool granted_phase(uint64_t e,uint64_t*t,uint8_t*p){if(!model.phase||e!=7)return false;*t=model.tick;*p=model.phase_index;return true;}}mp4_animation_gate;
bool mp4_native_phase_origin(uint64_t e,void*d,uintptr_t m){return model.native&&e==7&&d==(void*)0x220&&model.phase_index<8&&m==0x800u+4u*model.phase_index;}
