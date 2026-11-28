#include <cstdint>
#include <cstddef>
#include <cstring>
#include <cstdlib>
#include <cassert>
#include "history.hpp"
namespace mp4child{struct Graph{uintptr_t handle=0;uint32_t version=0,padding=0;};}
namespace mp4_director_birth{struct SourceTuple{uintptr_t director=0,asset=0,game_object=0,klass=0,method=0;uint64_t epoch=0,capture=0;};struct Playable{uintptr_t handle=0;uint32_t version=0,padding=0;};}
namespace mp4_director_maintenance{enum class Kind{rebuild=3,saved_evaluate=5};struct Call{Kind kind=Kind::rebuild;uint64_t epoch=0,serial=0;uintptr_t source_asset=0,receiver=0,method=0;uint64_t original_receipt=0;};}
namespace mp4world{struct DirectorGraphIdentity{uintptr_t native=0,slot=0;uint32_t version=0;};}
struct Mp4TimelineContext{mp4world::DirectorGraphIdentity identity{};mp4_director_birth::Playable root{};};
struct Mp4ChildLineageProof{mp4_director_birth::SourceTuple owner{};mp4world::DirectorGraphIdentity graph{};mp4_director_birth::Playable root{};uint64_t source_capture=0;};
struct Mp4RootHistoryLineagePool{struct Record{mp4_director_birth::SourceTuple owner{};Mp4TimelineContext*context=nullptr;mp4_root_history::Image*image=nullptr;mp4_director_maintenance::Call retired_call{};uint64_t id=0;bool retired=false;};Record records[3]{};size_t count=3;}mp4_root_history_lineage_pool;
struct Model{int mode=0;bool thread=true,retired=true,proof=true;uint64_t actual_capture=2;unsigned retirement_queries=0,old_capi=0;Mp4ChildLineageProof before{},actual{};mp4_director_maintenance::Call call{};Mp4TimelineContext contexts[3]{};}model;
bool game_call(){return model.thread;}bool mp4_child_tuple_same(const mp4_director_birth::SourceTuple&a,const mp4_director_birth::SourceTuple&b){return a.director==b.director&&a.asset==b.asset&&a.game_object==b.game_object&&a.klass==b.klass&&a.method==b.method&&a.epoch==b.epoch&&a.capture==b.capture;}
bool mp4_child_call_same(const mp4_director_maintenance::Call&a,const mp4_director_maintenance::Call&b){return a.kind==b.kind&&a.epoch==b.epoch&&a.serial==b.serial&&a.source_asset==b.source_asset&&a.receiver==b.receiver&&a.method==b.method&&a.original_receipt==b.original_receipt;}
mp4child::Graph mp4_child_identity_handle(const mp4world::DirectorGraphIdentity&i){return {i.slot,i.version,0};}
bool mp4_child_module_retired(const Mp4ChildLineageProof&,const mp4_director_maintenance::Call&){++model.retirement_queries;return model.retired;}
bool mp4_child_module_before_proof(const mp4_director_maintenance::Call&,uintptr_t,uintptr_t,uint32_t,Mp4ChildLineageProof*out,uint64_t*actual){*out=model.actual;*actual=model.actual_capture;return model.proof;}
