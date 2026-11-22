// Actual shared lineage with actual Birth receipt model and typed API fixtures.
#include <cstring>
#define BIRTH_FIXTURE_NO_MAIN
#include "mp4_child_birth_model.cpp.inc"
#undef BIRTH_FIXTURE_NO_MAIN
#include "child-scope.hpp"
namespace mp4child=mp4_child_source;namespace mp4world=idoly_mp4_world;
namespace mp4actor{using Handle=mp4child::Graph;}
namespace mp4game{using PlayableGraph=mp4child::Graph;}
Fixture*f=nullptr;bool held=true;int mode=0,publishes=0,captures=0;bool actual=true;
alignas(16)uint8_t native_director[0x200]{};mp4child::Graph current_graph{};
struct Catalogue{birth::SourceTuple tuples[65]{};size_t count=1;uint64_t epoch=7,capture=50;void*asset=reinterpret_cast<void*>(0xabc);bool captured=true;}mp4_birth_catalogue;
bool game_call(){return true;}
bool mp4_actor_clock_held(void*){return held;}
bool mp4_child_native_owner(void*,const birth::SourceTuple&t){return f->source_current&&t.director==f->tuples[0].director&&t.asset==f->tuples[0].asset;}
bool mp4_child_native_object(void*,uintptr_t object,const char*,uintptr_t*out){if(object!=f->tuples[0].director||!f->source_current)return false;*out=reinterpret_cast<uintptr_t>(native_director);return true;}
template<class T>bool mp4_actor_field(void*p,size_t at,T&out){return f->api().read(f,reinterpret_cast<uintptr_t>(p)+at,&out,sizeof out);}
bool mp4_actor_same_handle(mp4actor::Handle a,mp4actor::Handle b){return a.handle==b.handle&&(a.version&~uint32_t(1))==(b.version&~uint32_t(1));}
struct StateApi{
 bool(*graph_valid)(mp4actor::Handle*,const void*)=[](mp4actor::Handle*g,const void*){uint32_t v=0;return g&&mp4_actor_field(reinterpret_cast<void*>(g->handle),0x20,v)&&v==(g->version&~uint32_t(1));};
 bool(*playable_valid)(mp4actor::Handle*,const void*)=[](mp4actor::Handle*r,const void*){return r&&r->handle==0x900&&r->version==20;};
 int32_t(*graph_root_count)(mp4actor::Handle*,const void*)=[](mp4actor::Handle*,const void*){return 1;};
 void(*graph_root)(mp4actor::Handle*,int32_t,mp4actor::Handle*,const void*)=[](mp4actor::Handle*,int32_t,mp4actor::Handle*out,const void*){*out={0x900,20,0};};
};
StateApi mp4_actor_state_api(){return{};}
struct GameApi{void(*director_graph_injected)(void*,mp4game::PlayableGraph*,const void*)=[](void*,mp4game::PlayableGraph*out,const void*){*out=current_graph;};}mp4_api;
bool mp4_director_actual_operation(Call*out){if(!actual)return false;*out=f->call;return true;}
#include "lineage-host.inc"
void publication(mp4child::Graph graph,birth::Playable root={0x900,20,0}){current_graph=graph;Fixture::put(native_director,0x88,graph);Fixture::put(native_director,0x98,root);}
int main(int argc,char**argv){assert(argc==2);mode=std::atoi(argv[1]);Fixture fixture;f=&fixture;f->spans.push_back({native_director,sizeof native_director});mp4_birth_catalogue.tuples[0]=f->tuples[0];publication(f->handle(1));
 mp4_child_lineage_hooks.capture=[](const birth::SourceTuple&,mp4child::Graph,birth::Playable,uint64_t*receipt){++captures;*receipt=501;return world::Result::ok;};
 mp4_child_lineage_hooks.retired=[](const Mp4ChildLineageProof&p,const Call&c){return mode!=5&&p.source_capture==501&&c.serial==f->call.serial&&c.original_receipt==1001&&Fixture::get<uint32_t>(f->slots[1],0x20)==22;};
 mp4_child_lineage_hooks.publish=[](const Mp4ChildLineageProof&,const birth::Receipt&r,const birth::SourceTuple&t,const world::DirectorGraphIdentity&i,uint64_t*receipt){
  ++publishes;assert(r.birth&&r.factory&&r.returned&&t.director==f->tuples[0].director&&i.slot==Fixture::ptr(f->slots[0]));
  if(mode==6&&publishes==1)return world::Result::waiting;if(mode==10)f->source_current=false;if(mode==15)publication(f->handle(1));*receipt=mode==7?0:502;return world::Result::ok;};
 if(mode==11)mp4_child_lineage_hooks.capture=nullptr;
 const auto captured=mp4_child_lineage_capture();if(mode==11){assert(captured==world::Result::unsupported&&!captures);return 0;}assert(captured==world::Result::ok&&captures==1);
 mp4child::State state{};state.owner=f->tuples[0];state.root_asset=0xabc;state.graph=f->handle(1);
 assert(mp4_child_lineage(nullptr,state,current_graph)==world::Result::ok);
 if(mode==0)return 0;
 if(mode==1){publication(f->handle(0));assert(mp4_child_lineage(nullptr,state,current_graph)==world::Result::unsupported&&!publishes);return 0;}
 assert(f->create());f->expose();assert(f->factory());mp4_child_birth_scope=f->births;mp4_child_birth_origin=f->source;
 auto call=f->call;if(mode==8)++call.serial;
 const bool observed=mp4_child_lineage_factory_return(call,f->handle(0));if(mode==8){assert(!observed&&!publishes);return 0;}assert(observed);
 if(mode==14)assert(mp4_child_lineage_factory_return(call,f->handle(0)));
 if(mode==3){assert(mp4_child_lineage(nullptr,state,f->handle(0))==world::Result::waiting&&!publishes);return 0;}
 Fixture::put(f->slots[1],0x20,uint32_t(22));publication(f->handle(0));
 if(mode==4)Fixture::put(native_director,0x98,birth::Playable{0x901,20,0});
 if(mode==9)f->tuples[0].asset++;
 auto result=mp4_child_lineage(nullptr,state,f->handle(0));
 if(mode==4){assert(result==world::Result::waiting&&!publishes);return 0;}
 if(mode==5||mode==7){assert(result==world::Result::unsupported&&!mp4_child_lineage_bank.retired_count);return 0;}
 if(mode==9||mode==10||mode==15){assert(result==world::Result::stale&&!mp4_child_lineage_bank.retired_count);return 0;}
 if(mode==6){assert(result==world::Result::waiting&&!mp4_child_lineage_bank.retired_count);result=mp4_child_lineage(nullptr,state,f->handle(0));}
 assert(result==world::Result::ok&&mp4_child_lineage_bank.retired_count==1&&mp4_child_lineage_bank.nodes[0].current.source_capture==502&&publishes==(mode==6?2:1));
 assert(mp4_child_invalid_graph(state.owner,f->handle(1))==world::Result::ok);
 if(mode==13)assert(mp4_child_invalid_graph(state.owner,{0x123,20,0})==world::Result::unsupported);
 f->source_current=false;mp4_child_lineage_release();assert(!mp4_child_lineage_bank.active&&!mp4_child_lineage_bank.count);
}
