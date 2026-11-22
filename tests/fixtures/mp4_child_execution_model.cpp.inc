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
// ACTUAL_RAW_SCOPE
// ACTUAL_RAW_QUERY
void*mp4_scene_root_asset_receipt(uint64_t epoch){return epoch==7?mp4_scene_host.root_asset:nullptr;}
void rebuild(void*,const void*){++raw_calls;assert(mp4_raw_original_operation.invoked);if(mode==9)throw 42;if(mode==8)source_live=f->current=false;current_graph=f->handle(1);}
void evaluate(void*,const void*){++raw_calls;}
void resume(void*,const void*){++raw_calls;play_state=1;}
void pause(void*,const void*){++raw_calls;play_state=0;}
void play(void*,const void*){++raw_calls;play_state=1;}
int32_t state(void*,const void*){return play_state;}
struct GameApi{struct{mp4child::Original director_rebuild=rebuild,director_resume=resume,director_pause=pause,director_play=play;int32_t(*director_state)(void*,const void*)=state;}automatic_playback;
 mp4child::Original director_evaluate=evaluate;
 void(*director_graph_injected)(void*,mp4child::Graph*,const void*)=[](void*,mp4child::Graph*out,const void*){*out=current_graph;};}mp4_api;
namespace mp4game{using PlayableGraph=mp4child::Graph;}
#include "execution-host.inc"
void enqueue_original(void*,uint32_t op,const AnimationGraph*h){f->push(h->handle==QueueFixture::ptr(f->slots[1])?1:0,op,h->version);}
void append_original(void*,const AnimationGraph*){}
void collect_original(void*,void*){}
void manager_original(void*){}
void reset_original(void*){}
int main(int argc,char**argv){assert(argc==2);mode=std::atoi(argv[1]);QueueFixture fixture;f=&fixture;current_graph=f->handle();
 auto api=f->api();api.call_origin=[](void*,const Call&c){return mp4_child_planned_operation(c);};api.hook_origin=[](void*,Hook h,uintptr_t r,const Call&){return mp4_child_pending_host.native_entry(h,r);};
 Originals originals{enqueue_original,{append_original,append_original},collect_original,reset_original,{manager_original,manager_original}};mp4_director_maintenance::HostApi ha{};ha.bindings_current=[](void*,const Originals&){return bindings;};ha.quarantine=[](void*,const char*){++quarantines;};assert(mp4_child_pending_host.configure(api,originals,ha));
 mp4_child_execution_hooks.prepare=[](Kind,const mp4child::State&,mp4child::Graph,uint64_t*ticket,uint64_t*receipt){
  assert(!mp4_raw_original_operation.depth);if(mode==1)return world::Result::waiting;*ticket=++tickets;*receipt=mode==3?0:1000+tickets;if(mode==2)return world::Result::unsupported;if(mode==4)source_live=false;return world::Result::ok;};
 mp4_child_execution_hooks.entered=[](uint64_t,const mp4child::State&,const Call&call){assert(mp4_raw_original_operation.depth&&mp4_raw_original_operation.invoked&&mp4_child_pending_host.journal().active()&&mp4_child_call_same(mp4_child_pending_host.journal().call(),call));return mode!=17;};
 mp4_child_execution_hooks.returned=[](uint64_t,const mp4child::State&,const mp4child::Mutation&m){assert(mp4_raw_original_operation.depth&&m.issued&&m.returned);if(mode==19)throw 19;return mode!=18;};
 mp4_child_execution_hooks.finish=[](uint64_t,const mp4child::State&,const mp4child::Mutation&m){assert(!mp4_raw_original_operation.depth&&m.returned);++finishes;if(mode==6&&finishes==1)return world::Result::waiting;return world::Result::ok;};
 mp4_child_execution_hooks.settle=[](const mp4child::State&,const mp4child::Mutation&){++settles;if(mode==7&&settles==1)return world::Result::waiting;return world::Result::ok;};
 mp4_child_execution_hooks.bindings=[](){return bindings;};mp4_child_execution_hooks.abandon=[](uint64_t)noexcept{++abandons;};mp4_child_execution_hooks.quarantine=[](const char*)noexcept{++quarantines;};
 mp4child::CallHost calls;mp4child::CallApi ca{};ca.rebuild=rebuild;ca.evaluate=evaluate;ca.resume=resume;ca.pause=pause;
 ca.current=[](void*,const mp4child::State&s){return mp4_child_execution_current(s);};ca.held=mp4_actor_clock_held;ca.bindings_current=[](void*,mp4child::Original,mp4child::Original,mp4child::Original,mp4child::Original){return bindings;};ca.actual_operation=[](void*,Call*out){return mp4_director_actual_operation(out);};ca.execute=mp4_child_execute;assert(calls.configure(ca));
 mp4child::State s{};s.owner={0x55,0x222,0x333,0x444,0x555,7,50};s.root_asset=0xabc;s.graph=current_graph;mp4child::Mutation mutation{};auto before=current_graph;
 if(mode==5)f->push(0,0);
 if(mode==10)bindings=false;
 if(mode==11)held=false;
 if(mode==12)mp4_child_execution_hooks.prepare=nullptr;
 if(mode==20)mp4_child_execution_hooks.entered=nullptr;
 if(mode==21)mp4_child_execution_hooks.returned=nullptr;
 if(mode==19){bool caught=false;try{calls.invoke(Kind::rebuild,s,&mutation);}catch(int v){caught=v==19;}assert(caught&&raw_calls==1&&mutation.issued&&mutation.returned&&!mp4_raw_original_operation.depth&&quarantines==1);return 0;}
 if(mode==9){bool caught=false;try{calls.invoke(Kind::rebuild,s,&mutation);}catch(int v){caught=v==42;}assert(caught&&raw_calls==1&&mutation.issued&&!mutation.returned&&!mp4_raw_original_operation.depth&&quarantines==1);return 0;}
 const auto result=calls.invoke(mode==13?Kind::play:(mode==14?Kind::stop:Kind::rebuild),s,&mutation);
 if(mode==1||mode==2||mode==3||mode==4||mode==5||mode==10||mode==11||mode==12||mode==17||mode==20||mode==21){assert(result!=world::Result::ok&&!raw_calls&&!mutation.issued&&!mp4_raw_original_operation.depth);return 0;}
 if(mode==18){assert(result==world::Result::failed&&raw_calls==1&&mutation.issued&&mutation.returned&&!finishes&&quarantines==1&&!mp4_raw_original_operation.depth);return 0;}
 if(mode==8){assert(result==world::Result::stale&&raw_calls==1&&mutation.issued&&mutation.returned&&quarantines==1&&!mp4_raw_original_operation.depth);return 0;}
 if(mode==6)assert(result==world::Result::waiting&&mutation.issued&&mutation.returned);else assert(result==world::Result::ok);
 assert(raw_calls==1&&!mp4_raw_original_operation.depth&&!mp4_child_pending_host.journal().active());
 if(mode==15){mutation.call.original_receipt++;assert(mp4_child_confirm(nullptr,mutation.call.kind,s,mutation,before,current_graph)==world::Result::failed);return 0;}
 if(mode==16){before.version+=2;assert(mp4_child_confirm(nullptr,mutation.call.kind,s,mutation,before,current_graph)==world::Result::failed);return 0;}
 auto confirm=mp4_child_confirm(nullptr,mutation.call.kind,s,mutation,before,current_graph);if(mode==7){assert(confirm==world::Result::waiting);confirm=mp4_child_confirm(nullptr,mutation.call.kind,s,mutation,before,current_graph);}
 assert(confirm==world::Result::ok&&raw_calls==1&&finishes==(mode==6?2:1));
 source_live=false;mp4_child_execution_release();assert(!mp4_child_execution_bank.count&&!mp4_child_pending_host.journal().active()&&abandons==1);
}
