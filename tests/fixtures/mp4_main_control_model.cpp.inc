#include "mp4_playback_state.hpp"
#include <cstring>
// Actual shared execution + CallHost + Journal with modeled source modules.
#define Host QueueFixture
#define main queue_fixture_main
#include "mp4_child_journal_model.cpp.inc"
#undef main
#undef Host
#include "native-host.hpp"
#include "birth-scope.hpp"
#include "source-origin.hpp"
#include "child-scope.hpp"
#include "original-call-host.hpp"
namespace mp4child=mp4_child_source;
namespace mp4world=idoly_mp4_world;
QueueFixture*f=nullptr;bool source_live=true,held=true,thread=true,bindings=true,physical=true;
int mode=0,raw_calls=0,finishes=0,settles=0,abandons=0,quarantines=0,play_state=0;
uint64_t tickets=0;mp4child::Graph current_graph{};
bool game_call(){return thread;}
struct Catalogue{void*director=reinterpret_cast<void*>(0x55);}mp4_birth_catalogue;
struct RngGate{template<class F>bool isolate(F action){action();return source_live;}}mp4_actor_mono_gate;
struct Scene{bool active=true;struct{uint64_t generation=7;}source;uint32_t root_asset_handle=1;void*root_asset=reinterpret_cast<void*>(0xabc);}mp4_scene_host;
bool mp4_scene_source_current(){return source_live;}
struct{uint64_t epoch=7;uintptr_t asset=0xabc;}mp4_child_lineage_bank;
bool mp4_child_lineage_current(){return source_live;}
bool mp4_child_native_owner(void*,const mp4_director_birth::SourceTuple&t){return source_live&&t.director==0x55;}
bool mp4_birth_catalogue_membership(const Call&c){return source_live&&c.epoch==7&&c.source_asset==0xabc&&c.receiver==0x55;}
bool mp4_actor_clock_held(void*){return held;}
bool mp4_director_boundary_closed(void*){return physical;}
bool mp4_child_call_same(const Call&a,const Call&b){return a.kind==b.kind&&a.epoch==b.epoch&&a.serial==b.serial&&a.original_receipt==b.original_receipt&&a.receiver==b.receiver&&a.source_asset==b.source_asset&&a.method==b.method;}
bool mp4_child_graph_same(mp4child::Graph a,mp4child::Graph b){return a.handle==b.handle&&a.version==b.version;}
bool mp4_child_tuple_same(const mp4_director_birth::SourceTuple&a,const mp4_director_birth::SourceTuple&b){return a.director==b.director&&a.asset==b.asset&&a.epoch==b.epoch&&a.capture==b.capture;}
mp4child::Result mp4_child_lineage(void*,const mp4child::State&,mp4child::Graph g){return source_live&&mp4_child_graph_same(g,current_graph)?mp4child::Result::ok:mp4child::Result::stale;}
// These held-only fixtures explicitly refuse native-frame authority.
bool mp4_native_phase_origin(uint64_t,void*,uintptr_t){return false;}
// ACTUAL_RAW_SCOPE
// ACTUAL_RAW_QUERY
void*mp4_scene_root_asset_receipt(uint64_t epoch){return epoch==7?mp4_scene_host.root_asset:nullptr;}
void rebuild(void*,const void*){++raw_calls;assert(mp4_raw_original_operation.invoked);if(mode==9)throw 42;if(mode==8)source_live=f->current=false;auto old=current_graph;unsigned next=old.handle==QueueFixture::ptr(f->slots[0])?1:0;QueueFixture::put(reinterpret_cast<void*>(old.handle),0x20,old.version+2);current_graph=f->handle(next,QueueFixture::get<uint32_t>(f->slots[next],0x20));}
void evaluate(void*,const void*){++raw_calls;}
void resume(void*,const void*){++raw_calls;play_state=1;}
void pause(void*,const void*){++raw_calls;play_state=0;}
void play(void*,const void*){++raw_calls;play_state=1;}
int32_t state(void*,const void*){return play_state;}
double native_time=13.25;int native_mode=0;
struct GameApi{double(*director_get_time)(void*,const void*)=[](void*,const void*){return native_time;};int32_t(*director_get_mode)(void*,const void*)=[](void*,const void*){return native_mode;};struct{mp4child::Original director_rebuild=rebuild,director_resume=resume,director_pause=pause,director_play=play;int32_t(*director_state)(void*,const void*)=state;}automatic_playback;
 mp4child::Original director_evaluate=evaluate;
 void(*director_graph_injected)(void*,mp4child::Graph*,const void*)=[](void*,mp4child::Graph*out,const void*){*out=current_graph;};}mp4_api;
namespace mp4game{using PlayableGraph=mp4child::Graph;}
#include "execution-host.inc"
void enqueue_original(void*,uint32_t op,const AnimationGraph*h){f->push(h->handle==QueueFixture::ptr(f->slots[1])?1:0,op,h->version);}
void append_original(void*,const AnimationGraph*){}
void collect_original(void*,void*){}
void manager_original(void*){}
void reset_original(void*){}

struct SourceScope{mp4child::State value{};unsigned children=0;bool captured()const{return true;}size_t count()const{return 1;}const mp4child::State*source(size_t)const{return &value;}mp4child::Result rebuild_children(mp4child::Round){++children;return mode==22&&children==1?world::Result::waiting:world::Result::ok;}}mp4_child_source_scope;
bool mp4_child_bindings_current(){return bindings&&source_live;}
mp4child::Api mp4_child_source_api(){mp4child::Api api{};api.preflight=[](void*,mp4child::Round,Kind,const mp4child::State&,mp4child::Graph){return world::Result::ok;};return api;}
namespace idoly_mp4_runtime{struct Game{bool marker=false;bool automatic_source_playback_state_restored(uint64_t epoch)const{return marker&&epoch==7;}}game;}
#include "main-control-host.inc"
int main(int argc,char**argv){assert(argc==2);const int test=std::atoi(argv[1]);mode=test;QueueFixture fixture;f=&fixture;current_graph=f->handle();play_state=1;
 auto api=f->api();api.call_origin=[](void*,const Call&c){return mp4_child_planned_operation(c);};api.hook_origin=[](void*,Hook h,uintptr_t r,const Call&){return mp4_child_pending_host.native_entry(h,r);};
 Originals originals{enqueue_original,{append_original,append_original},collect_original,reset_original,{manager_original,manager_original}};mp4_director_maintenance::HostApi h{};h.bindings_current=[](void*,const Originals&){return bindings;};h.quarantine=[](void*,const char*){++quarantines;};assert(mp4_child_pending_host.configure(api,originals,h));
 mp4_child_execution_hooks.prepare=[](Kind,const mp4child::State&,mp4child::Graph,uint64_t*ticket,uint64_t*receipt){if(mode==1)return world::Result::waiting;*ticket=++tickets;*receipt=1000+tickets;return world::Result::ok;};
 mp4_child_execution_hooks.entered=[](uint64_t,const mp4child::State&,const Call&call){assert(mp4_raw_original_operation.depth&&mp4_raw_original_operation.invoked&&mp4_child_pending_host.journal().active()&&mp4_child_call_same(mp4_child_pending_host.journal().call(),call));return mode!=17;};
 mp4_child_execution_hooks.returned=[](uint64_t,const mp4child::State&,const mp4child::Mutation&m){assert(mp4_raw_original_operation.depth&&m.issued&&m.returned);if(mode==19)throw 19;return mode!=18;};
 mp4_child_execution_hooks.finish=[](uint64_t,const mp4child::State&,const mp4child::Mutation&){assert(!mp4_raw_original_operation.depth);++finishes;return mode==6&&finishes==1?world::Result::waiting:world::Result::ok;};
 mp4_child_execution_hooks.settle=[](const mp4child::State&,const mp4child::Mutation&){++settles;return mode==7&&settles==1?world::Result::waiting:world::Result::ok;};
 mp4_child_execution_hooks.bindings=[](){return bindings;};mp4_child_execution_hooks.abandon=[](uint64_t)noexcept{++abandons;};mp4_child_execution_hooks.quarantine=[](const char*)noexcept{++quarantines;};
 auto&s=mp4_child_source_scope.value;s.owner={0x55,0x222,0x333,0x444,0x555,7,50};s.root_asset=0xabc;s.graph=current_graph;s.state=1;s.mode=0;s.time=13.25;
 mp4play::Snapshot<mp4game::PlayableGraph> snapshot{};snapshot.graph=current_graph;snapshot.state=s.state;snapshot.mode=s.mode;snapshot.time=s.time;
 mp4play::OperationReceipt receipt{};auto call=[&](mp4play::OperationStep step,mp4play::OperationKind kind){return mp4_main_control(nullptr,step,kind,reinterpret_cast<void*>(0x55),snapshot,&receipt);};
 if(test==23){snapshot.time++;assert(call(mp4play::OperationStep::acquire_pause,mp4play::OperationKind::pause)==mp4play::Result::stale&&!raw_calls);return 0;}
 if(test==24){assert(call(mp4play::OperationStep::start_play,mp4play::OperationKind::resume)==mp4play::Result::stale&&!raw_calls);return 0;}
 if(test==25){assert(mp4_main_control(nullptr,mp4play::OperationStep::acquire_pause,mp4play::OperationKind::pause,reinterpret_cast<void*>(0x56),snapshot,&receipt)==mp4play::Result::stale&&!raw_calls);return 0;}
 if(test==9){bool threw=false;try{call(mp4play::OperationStep::start_rebuild,mp4play::OperationKind::rebuild);}catch(int v){threw=v==42;}assert(threw&&receipt.issued&&!receipt.returned&&raw_calls==1);assert(call(mp4play::OperationStep::start_rebuild,mp4play::OperationKind::rebuild)==mp4play::Result::failed&&raw_calls==1);return 0;}
 if(test==1||test==6||test==7||test==22){auto first=call(mp4play::OperationStep::start_rebuild,mp4play::OperationKind::rebuild);assert(first==mp4play::Result::waiting&&receipt.issued==(test==6||test==7));const int count=raw_calls;mode=0;assert(call(mp4play::OperationStep::start_rebuild,mp4play::OperationKind::rebuild)==mp4play::Result::ok&&raw_calls==(count?count:1));return 0;}
 assert(call(mp4play::OperationStep::acquire_pause,mp4play::OperationKind::pause)==mp4play::Result::ok&&play_state==0);
 assert(call(mp4play::OperationStep::start_rebuild,mp4play::OperationKind::rebuild)==mp4play::Result::ok);
 assert(call(mp4play::OperationStep::zero_evaluate,mp4play::OperationKind::zero_evaluate)==mp4play::Result::ok);
 native_time=0;assert(call(mp4play::OperationStep::start_play,mp4play::OperationKind::play)==mp4play::Result::ok&&play_state==1);
 const auto&start=mp4_main_control_bank.requests[static_cast<size_t>(mp4play::OperationStep::start_play)];assert(start.mutation.call.method==reinterpret_cast<uintptr_t>(play)&&start.mutation.call.method!=reinterpret_cast<uintptr_t>(resume));
 assert(call(mp4play::OperationStep::restore_pause,mp4play::OperationKind::pause)==mp4play::Result::ok);
 assert(call(mp4play::OperationStep::restore_rebuild,mp4play::OperationKind::rebuild)==mp4play::Result::ok);
 native_time=13.25;assert(call(mp4play::OperationStep::restore_evaluate,mp4play::OperationKind::saved_evaluate)==mp4play::Result::ok);
 assert(mp4_child_parent_saved_checkpoint()==world::Result::ok&&mp4_child_parent_state_checkpoint()==world::Result::waiting);
 assert(call(mp4play::OperationStep::restore_state,mp4play::OperationKind::resume)==mp4play::Result::ok);
 assert(mp4_child_parent_state_checkpoint()==world::Result::waiting);idoly_mp4_runtime::game.marker=true;assert(mp4_child_parent_state_checkpoint()==world::Result::ok);
 const auto count=raw_calls;assert(call(mp4play::OperationStep::restore_state,mp4play::OperationKind::resume)==mp4play::Result::ok&&raw_calls==count);
 assert(raw_calls==8);source_live=false;mp4_main_control_release();assert(!mp4_main_control_bank.epoch);
}
