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

namespace mp4world=idoly_mp4_world;
mp4world::AnimationGate mp4_animation_gate;unsigned native_phases=0,unexpected_phases=0;std::string scenario;
int mp4_world_host=1;uintptr_t mp4_native_base=1;mp4world::DirectorRegistryProfile mp4_director_profile{};
struct Registry{
 mp4world::DirectorRegistrySummary state{};
 mp4child::Result admit(mp4world::DirectorRegistryApi,void*,const mp4world::DirectorRegistryProfile&,uintptr_t){
  state={};if(!source_live)return world::Result::stale;if(scenario=="unclosed_output")return world::Result::unsupported;
  uintptr_t node=QueueFixture::get<uintptr_t>(f->queue,0);while(node){++state.pending_valid;node=QueueFixture::get<uintptr_t>(reinterpret_cast<void*>(node),0);if(state.pending_valid>32)return world::Result::unsupported;}return world::Result::ok;
 }
 const mp4world::DirectorRegistrySummary&summary()const{return state;}
 mp4child::Result maintenance_ready(mp4world::DirectorRegistryApi api,void*ctx,const mp4world::DirectorRegistryProfile&p,uintptr_t base){
  const auto r=admit(api,ctx,p,base);if(r!=world::Result::ok)return r;
  uintptr_t node=QueueFixture::get<uintptr_t>(f->queue,0);while(node){auto*n=reinterpret_cast<void*>(node);auto slot=QueueFixture::get<uintptr_t>(n,8);auto version=QueueFixture::get<uint32_t>(n,16);auto op=QueueFixture::get<uint32_t>(n,24);
   mp4world::DirectorPending pending{{QueueFixture::get<uintptr_t>(reinterpret_cast<void*>(slot),0x28),slot,version,0,0,0},node,op};mp4world::DirectorAuthorization out{};
   if(!api.pending_authorized||!api.pending_authorized(ctx,pending,&out))return world::Result::unsupported;node=QueueFixture::get<uintptr_t>(n,0);
  }return state.pending_valid?world::Result::ok:world::Result::invalid;
 }
}mp4_director_registry;
bool mp4_animation_routes_ready(){return bindings;}
mp4world::DirectorRegistryApi mp4_director_api(){mp4world::DirectorRegistryApi a{};a.pending_authorized=[](void*,const mp4world::DirectorPending&p,mp4world::DirectorAuthorization*out){return out&&mp4_child_pending_host.journal().authorization(p,*out);};return a;}
void collect_phase(void*temporary,void*){uintptr_t cursor=QueueFixture::get<uintptr_t>(f->queue,0);size_t count=0;while(cursor){auto*n=reinterpret_cast<void*>(cursor);QueueFixture::put(f->data,count*24,QueueFixture::get<uintptr_t>(n,8));QueueFixture::put(f->data,count*24+8,QueueFixture::get<uint32_t>(n,16));QueueFixture::put(f->data,count*24+16,QueueFixture::get<uint32_t>(n,24));cursor=QueueFixture::get<uintptr_t>(n,0);++count;}
 QueueFixture::put(f->queue,0,uintptr_t(0));QueueFixture::put(f->queue,8,QueueFixture::get<uint64_t>(f->queue,8)+count);QueueFixture::put(temporary,0,QueueFixture::ptr(f->data));QueueFixture::put(temporary,16,uint64_t(count));QueueFixture::put(temporary,24,uint64_t(64));}
void unexpected_phase(){++unexpected_phases;}
void push_registered(){auto h=f->handle();f->spans.push_back({&h,sizeof h});mp4_child_pending_host.enqueue(f->manager,1,&h);f->spans.pop_back();}
void actual_phase5(){++native_phases;assert(mp4_animation_gate.maintenance_inflight(7)&&mp4_raw_original_operation.kind==6&&mp4_raw_original_operation.invoked);
 mp4_child_pending_host.collect(f->temporary,f->queue);f->next_node=0;
 if((scenario=="reappend"&&native_phases==1)||scenario=="budget"){push_registered();}
 if(scenario=="sourcechange")source_live=f->current=false;if(scenario=="throws")throw 42;
}
void(*mp4_animation_original[8])()={unexpected_phase,unexpected_phase,unexpected_phase,unexpected_phase,unexpected_phase,actual_phase5,unexpected_phase,unexpected_phase};
#include "deferred-host.inc"
void parent_original(){if(scenario!="no_work")push_registered();}
int main(int argc,char**argv){assert(argc==2);scenario=argv[1];QueueFixture fixture;f=&fixture;current_graph=f->handle();
 auto api=f->api();api.call_origin=[](void*,const Call&c){return mp4_child_planned_operation(c);};api.hook_origin=[](void*,Hook h,uintptr_t r,const Call&){return mp4_child_pending_host.native_entry(h,r);};
 Originals originals{enqueue_original,{append_original,append_original},collect_phase,reset_original,{manager_original,manager_original}};mp4_director_maintenance::HostApi ha{};ha.bindings_current=[](void*,const Originals&){return bindings;};ha.quarantine=[](void*,const char*){++quarantines;};assert(mp4_child_pending_host.configure(api,originals,ha));
 mp4_child_execution_hooks.entered=[](uint64_t,const mp4child::State&,const Call&){return true;};
 mp4_child_execution_hooks.returned=[](uint64_t,const mp4child::State&,const mp4child::Mutation&){return true;};
 mp4_child_execution_hooks.bindings=[](){return bindings;};mp4_child_execution_hooks.prepare=[](Kind,const mp4child::State&,mp4child::Graph,uint64_t*,uint64_t*){return world::Result::ok;};mp4_child_execution_hooks.finish=[](uint64_t,const mp4child::State&,const mp4child::Mutation&){return world::Result::ok;};mp4_child_execution_hooks.settle=[](const mp4child::State&,const mp4child::Mutation&){return world::Result::ok;};mp4_child_execution_hooks.abandon=[](uint64_t)noexcept{};mp4_child_execution_hooks.quarantine=[](const char*)noexcept{++quarantines;};
 mp4world::AnimationApi animation{};animation.owner_thread=game_call;for(size_t i=0;i<8;++i)animation.original[i]=mp4_animation_original[i];assert(mp4_animation_gate.install(animation)&&mp4_animation_gate.acquire(7));
 mp4child::State s{};s.owner={0x55,0x222,0x333,0x444,0x555,7,50};s.root_asset=0xabc;s.graph=current_graph;mp4child::Mutation mutation{};
 {Mp4OriginalOperationScope scope(7,2,reinterpret_cast<void*>(0x55),reinterpret_cast<uintptr_t>(parent_original),0);assert(scope.valid);const auto&r=mp4_raw_original_operation;Call call{Kind::stop,r.epoch,r.serial,r.root_asset,r.director,r.method,r.receipt};assert(mp4_child_pending_host.journal().begin(call));scope.invoked();assert(mp4_child_pending_host.journal().invoked());parent_original();assert(mp4_child_pending_host.journal().end());mutation={call,true,true};}
 auto&record=mp4_child_execution_bank.records[mp4_child_execution_bank.count++];record.source=s;record.mutation=mutation;record.finished=true;
 if(scenario=="physical")physical=false;if(scenario=="active_grant")assert(mp4_animation_gate.grant(7,0));if(scenario=="unreturned")mutation.returned=false;if(scenario=="unfinished")record.finished=false;if(scenario=="unowned_queue")f->push(0,1);
 if(scenario=="throws"){bool caught=false;try{mp4_child_deferred_settle(s,mutation);}catch(int value){caught=value==42;}assert(caught&&native_phases==1&&quarantines==1&&!mp4_animation_gate.healthy(7)&&!unexpected_phases);return 0;}
 auto result=mp4_child_deferred_settle(s,mutation);
 if(scenario=="physical"||scenario=="active_grant"){assert(result==world::Result::waiting&&!native_phases);return 0;}
 if(scenario=="unreturned"||scenario=="unfinished"||scenario=="unclosed_output"||scenario=="unowned_queue"){assert(result!=world::Result::ok&&!native_phases);return 0;}
 if(scenario=="sourcechange"){assert(result==world::Result::stale&&native_phases==1&&quarantines==1);return 0;}
 if(scenario=="budget"){for(size_t i=1;i<mp4child::max_directors*2;++i){assert(result==world::Result::waiting);result=mp4_child_deferred_settle(s,mutation);}assert(result==world::Result::waiting&&native_phases==mp4child::max_directors*2);assert(mp4_child_deferred_settle(s,mutation)==world::Result::unsupported);return 0;}
 if(scenario=="reappend"){assert(result==world::Result::waiting&&native_phases==1);result=mp4_child_deferred_settle(s,mutation);assert(native_phases==2);}
 assert(result==world::Result::ok&&native_phases==(scenario=="no_work"?0u:scenario=="reappend"?2u:1u)&&!unexpected_phases&&mp4_animation_gate.closed(7));
 const auto count=native_phases;assert(mp4_child_deferred_settle(s,mutation)==world::Result::ok&&native_phases==count);
 source_live=false;mp4_child_deferred_release();assert(!mp4_child_deferred_bank.count);
}
