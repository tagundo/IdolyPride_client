#define BIRTH_FIXTURE_NO_MAIN
#include "mp4_child_birth_model.cpp.inc"
#undef BIRTH_FIXTURE_NO_MAIN
#include "native-host.hpp"
static Fixture*f=nullptr;static mp4_director_maintenance::Host*pending_host=nullptr;
static unsigned original_creates=0,original_factories=0,original_enqueues=0,original_collects=0,resets=0,quarantines=0;
static bool intercepted=true,queue_inside_factory=true,collect_inside_factory=true,throw_create=false,throw_factory=false;static AnimationGraph active_handle{};
static void*create_original(void*,uintptr_t){++original_creates;if(throw_create)throw 42;auto head=Fixture::ptr(f->manager)+0x378;auto prev=Fixture::get<uintptr_t>(f->manager,0x378);Fixture::put(f->graphs[0],0,prev);Fixture::put(f->graphs[0],8,head);Fixture::put(f->graphs[0],16,uintptr_t(0));Fixture::put(reinterpret_cast<void*>(prev),8,Fixture::ptr(f->graphs[0]));Fixture::put(f->manager,0x378,Fixture::ptr(f->graphs[0]));return f->graphs[0];}
static birth::Host*context_host=nullptr;static bool nested_probe=false,nest_once=false,change_call=false,change_bindings=false;
static birth::Playable factory_original(void*,AnimationGraph graph,void*,const void*){
 ++original_factories;Call c{};birth::FactoryInput input{};
 if(nested_probe)assert(!context_host->factory_current(c,input));
 else{assert(context_host->factory_current(c,input)&&c.serial==f->call.serial&&input.graph.handle==graph.handle);
  Provisional promise{};assert(f->births.provisional(c,graph,promise)&&promise.birth_receipt&&promise.factory_receipt);
  if(change_call){++f->call.serial;assert(!context_host->factory_current(c,input));--f->call.serial;}
  if(change_bindings){f->bindings=false;assert(!context_host->factory_current(c,input));f->bindings=true;}
  if(nest_once){nest_once=false;nested_probe=true;context_host->factory(reinterpret_cast<void*>(0xdead),graph,reinterpret_cast<void*>(0xbeef),nullptr,0);nested_probe=false;assert(context_host->factory_current(c,input));}
 }
 if(throw_factory)throw 43;return{0x900,20,0};
}
static void enqueue_original(void*,uint32_t op,const AnimationGraph*h){++original_enqueues;f->push(0,op,h->version);}
static void append_original(void*,const AnimationGraph*){}
static void collect_original(void*temporary,void*){++original_collects;auto at=Fixture::get<uintptr_t>(f->queue,0);size_t count=0;while(at){auto*p=reinterpret_cast<void*>(at);Fixture::put(f->data,count*24,Fixture::get<uintptr_t>(p,8));Fixture::put(f->data,count*24+8,Fixture::get<uint32_t>(p,16));Fixture::put(f->data,count*24+16,Fixture::get<uint32_t>(p,24));at=Fixture::get<uintptr_t>(p,0);++count;}Fixture::put(temporary,0,Fixture::ptr(f->data));Fixture::put(temporary,16,uint64_t(count));Fixture::put(temporary,24,uint64_t(64));Fixture::put(f->queue,0,uintptr_t(0));}
static void reset_original(void*temporary){++resets;Fixture::put(temporary,0,uintptr_t(0));Fixture::put(temporary,16,uint64_t(0));}
static void deferred_original(void*){}
int main(int argc,char**argv){assert(argc==2);int mode=std::atoi(argv[1]);Fixture fixture;f=&fixture;birth::Host host(f->births,f->source);context_host=&host;
 birth::HostApi h{};h.call=[](void*,Call&c){c=f->call;return intercepted;};h.bindings=[](void*,birth::CreateFn,birth::FactoryFn){return f->bindings;};h.quarantine=[](void*,const char*){++quarantines;};assert(host.configure(create_original,factory_original,h));
 Call outside{};birth::FactoryInput absent{};assert(!host.factory_current(outside,absent));
 if(mode==4){nested_probe=true;host.factory(reinterpret_cast<void*>(0xdead),f->handle(),reinterpret_cast<void*>(0xbeef),nullptr,0);assert(original_factories==1&&!host.factory_current(outside,absent)&&!quarantines);return 0;}
 host.create(f->manager,0,0x20000000+birth::android_birth_pins.create_return);f->expose();auto input=f->input();
 if(mode==1)nest_once=true;if(mode==2)change_call=true;if(mode==3)throw_factory=true;if(mode==5)change_bindings=true;
 bool threw=false;try{host.factory(reinterpret_cast<void*>(input.asset),input.graph,reinterpret_cast<void*>(input.game_object),reinterpret_cast<void*>(input.method),input.return_pc);}catch(int v){threw=v==43;}
 assert(!host.factory_current(outside,absent)&&original_factories==(mode==1?2u:1u)&&threw==(mode==3)&&quarantines==(mode==3?1u:0u));
 return 0;
}
