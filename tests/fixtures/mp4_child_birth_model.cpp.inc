// Unit model of exact shared birth/provisional code, not whole-scene/GPU proof.
#define Host ModelHost
#define main journal_fixture_main
#include "mp4_child_journal_model.cpp.inc"
#undef main
#undef Host
#include "birth-scope.hpp"
#include "source-origin.hpp"
#include "typed-host.hpp"
#include "pins.inc"
namespace birth=mp4_director_birth;
struct Fixture:ModelHost {
 birth::Scope births;birth::SourceOrigin source;Journal pending;Api journal_api{};
 bool source_current=true,invoked=true,bindings=true,root_good=true,published=false;
 unsigned creates=0,factories=0,quarantines=0;int promotion=0;
 alignas(16)unsigned char assets[2][0x80]{},directors[2][0x80]{},klass[0x200]{},method[0x80]{};
 birth::SourceTuple tuples[2]{};size_t tuple_count=1;
 Call call{Kind::rebuild,7,1,0xabc,0x55,0x66,1001};
 static Fixture*active;
 Fixture(){active=this;for(auto s:std::vector<Span>{{assets,sizeof assets},{directors,sizeof directors},{klass,sizeof klass},{method,sizeof method}})spans.push_back(s);
  const uintptr_t head=ptr(manager)+0x378;put(manager,0x378,head);put(manager,0x380,head);
  put(klass,0x198,uintptr_t(0x10000000)+birth::android_birth_pins.factory);put(klass,0x1a0,ptr(method));
  for(unsigned i=0;i<2;++i){put(assets[i],0,ptr(klass));tuples[i]={ptr(directors[i]),ptr(assets[i]),0x111+i,ptr(klass),ptr(method),7,50+i};}
  auto reader=api().read;
  birth::OriginApi origin{};origin.context=this;origin.game_base=0x10000000;origin.engine_base=0x20000000;origin.pins=birth::android_birth_pins;
  origin.get_asset=[](void*d,const void*)->void*{for(auto&t:active->tuples)if(t.director==ptr(d))return reinterpret_cast<void*>(t.asset);return nullptr;};
  origin.get_game_object=[](void*d,const void*)->void*{for(auto&t:active->tuples)if(t.director==ptr(d))return reinterpret_cast<void*>(t.game_object);return nullptr;};
  origin.tuple_count=[](void*p,const Call&){return static_cast<Fixture*>(p)->tuple_count;};
  origin.tuple=[](void*p,const Call&,size_t i,birth::SourceTuple&out){auto&f=*static_cast<Fixture*>(p);if(i>=f.tuple_count)return false;out=f.tuples[i];return true;};
  origin.source_current=[](void*p,const Call&,const birth::SourceTuple&){return static_cast<Fixture*>(p)->source_current;};
  origin.invoked=[](void*p,const Call&){return static_cast<Fixture*>(p)->invoked;};origin.read=reader;
  origin.bindings_current=[](void*p,const birth::OriginApi&){return static_cast<Fixture*>(p)->bindings;};assert(source.configure(origin));
  birth::Api b{};b.context=this;b.manager=ptr(manager);b.read=reader;
  b.current=[](void*p,const Call&c){auto&f=*static_cast<Fixture*>(p);return f.source_current&&c.epoch==7&&c.source_asset==0xabc;};
  b.operation_invoked=[](void*p,const Call&){return static_cast<Fixture*>(p)->invoked;};
  b.create_origin=[](void*p,uintptr_t m,const Call&c){return static_cast<Fixture*>(p)->source.create(c,m);};
  b.factory_origin=[](void*p,const Call&c,const birth::FactoryInput&i){return static_cast<Fixture*>(p)->source.factory(c,i);};
  b.binding_current=[](void*p,const Call&c,const birth::FactoryInput&i){return static_cast<Fixture*>(p)->source.retained(c,i);};
  b.returned_root=[](void*p,const birth::FactoryInput&,birth::Playable v){auto&f=*static_cast<Fixture*>(p);return f.root_good&&v.handle==0x900&&v.version==20;};
  assert(births.configure(b));auto j=api();j.basis=[](void*,const Call&,AnimationGraph,uint32_t,Basis*){return false;};
  j.provisional_play=[](void*p,const Call&c,AnimationGraph g,Provisional*out){return static_cast<Fixture*>(p)->births.provisional(c,g,*out);};
  j.provisional_current=[](void*p,const Provisional&v){return static_cast<Fixture*>(p)->births.provisional_current(v);};
  j.promote=[](void*p,const Call&c,const Provisional&v,Basis*out){auto&f=*static_cast<Fixture*>(p);if(f.promotion==2)return world::Result::failed;if(!f.published)return world::Result::waiting;birth::Receipt r{};if(!f.births.completed(v,r)||c.serial!=r.parent.serial)return world::Result::failed;*out={v.graph,v.epoch,100,101,102,v.source_asset};if(f.promotion==1)out->graph.native++;return world::Result::ok;};
  journal_api=j;assert(pending.configure(j));
 }
 birth::FactoryInput input(unsigned i=0){return{tuples[i].asset,tuples[i].game_object,tuples[i].method,uintptr_t(0x10000000)+birth::android_birth_pins.internal_return,handle()};}
 bool create(bool expose=false,bool duplicate=false,bool director_path=false){birth::Ticket t{};auto prior=source.enter_create(ptr(manager),uintptr_t(0x20000000)+(director_path?birth::android_birth_pins.director_create_return:birth::android_birth_pins.create_return));bool ok=births.create_before(call,ptr(manager),0,t);source.leave_create(prior);if(!ok)return false;
  const auto head=ptr(manager)+0x378;const auto previous=get<uintptr_t>(manager,0x378);put(graphs[0],0,previous);put(graphs[0],8,head);put(reinterpret_cast<void*>(previous),8,ptr(graphs[0]));put(manager,0x378,ptr(graphs[0]));if(!expose)put(graphs[0],16,uintptr_t(0));
  if(duplicate){put(manager,0x378,ptr(graphs[1]));put(graphs[0],8,ptr(graphs[1]));put(graphs[1],0,ptr(graphs[0]));put(graphs[1],8,head);}
  ++creates;return births.create_after(t,ptr(graphs[0]));
 }
 void expose(){put(graphs[0],16,ptr(slots[0]));}
 bool factory(bool finish=true,unsigned i=0){birth::Ticket t{};if(!births.factory_before(call,input(i),t))return false;++factories;return !finish||births.factory_after(t,{0x900,20,0});}
 bool enqueue(){Ticket t{};if(!pending.native_begin(Hook::enqueue,ptr(manager),0,handle(),t))return false;push(0,0);return pending.native_end(t);}
 bool auth(){DirectorAuthorization out{};return pending.authorization(ModelHost::pending(),out);}
 bool collect(){Ticket t{};return pending.collect_begin(ptr(queue),t);}
 bool initial(){return pending.begin(call)&&pending.invoked()&&create()&&(expose(),factory());}
};
Fixture*Fixture::active=nullptr;

#ifndef BIRTH_FIXTURE_NO_MAIN
int main(int argc,char**argv){assert(argc==2);const int mode=std::atoi(argv[1]);Fixture f;
 if(mode==0){assert(f.initial()&&f.enqueue()&&f.pending.end());assert(!f.auth()&&f.pending.waiting_publication()&&!f.pending.failed());f.published=true;assert(f.auth());return 0;}
 if(mode==1){assert(f.pending.begin(f.call)&&f.pending.invoked()&&f.create());f.expose();assert(!f.enqueue()&&f.pending.failed());return 0;}
 if(mode==2){assert(!f.create(true)&&f.births.failed());return 0;}
 if(mode==3){assert(!f.create(false,true)&&f.births.failed());return 0;}
 if(mode==4){f.invoked=false;assert(!f.create());return 0;}
 if(mode==5){assert(f.create());f.expose();auto i=f.input();i.return_pc++;birth::Ticket t{};assert(!f.births.factory_before(f.call,i,t));return 0;}
 if(mode==6){assert(f.create());f.expose();auto i=f.input();i.method++;birth::Ticket t{};assert(!f.births.factory_before(f.call,i,t));return 0;}
 if(mode==7){assert(f.create());f.expose();auto i=f.input();i.game_object++;birth::Ticket t{};assert(!f.births.factory_before(f.call,i,t));return 0;}
 if(mode==8){assert(f.create());f.expose();auto i=f.input();i.asset++;birth::Ticket t{};assert(!f.births.factory_before(f.call,i,t));return 0;}
 if(mode==9){assert(f.create());f.expose();Fixture::put(f.klass,0x198,uintptr_t(0x123));assert(!f.factory());return 0;}
 if(mode==10){assert(f.create());f.expose();f.source_current=false;assert(!f.factory());return 0;}
 if(mode==11){assert(f.create());f.expose();Fixture::put(f.slots[0],0x20,uint32_t(22));assert(!f.factory());return 0;}
 if(mode==12){assert(f.create());f.expose();f.root_good=false;assert(!f.factory());return 0;}
 if(mode==13){assert(f.create());f.expose();assert(f.factory(false));Provisional p{};assert(f.births.provisional(f.call,f.handle(),p));birth::Receipt r{};assert(!f.births.completed(p,r));return 0;}
 if(mode==14){assert(f.initial()&&f.enqueue()&&f.pending.end());Call next{Kind::maintenance,7,2,0xabc,0x55,0x66};assert(f.pending.begin(next)&&f.pending.invoked());auto head=Fixture::get<uintptr_t>(f.queue,0);assert(!f.collect()&&!f.pending.failed()&&f.pending.waiting_publication()&&Fixture::get<uintptr_t>(f.queue,0)==head);f.published=true;assert(f.collect());return 0;}
 if(mode==15){assert(f.initial()&&f.enqueue()&&f.pending.end());f.published=true;f.promotion=1;assert(!f.auth()&&!f.pending.waiting_publication());return 0;}
 if(mode==16){assert(f.initial()&&f.enqueue()&&f.pending.end());f.promotion=2;assert(!f.auth()&&!f.pending.waiting_publication());return 0;}
 if(mode==17){f.tuple_count=2;assert(f.create());f.expose();assert(f.factory(true,1));return 0;}
 if(mode==18){f.tuple_count=1;assert(f.create());f.expose();assert(!f.factory(true,1));return 0;}
 if(mode==19){assert(f.initial());Provisional p{};assert(f.births.provisional(f.call,f.handle(),p));++p.original_receipt;assert(!f.births.provisional_current(p));return 0;}
 if(mode==20){assert(f.initial());Provisional p{};assert(f.births.provisional(f.call,f.handle(),p));f.births.detach();assert(!f.births.provisional_current(p));return 0;}
 if(mode==22){assert(f.initial()&&f.enqueue()&&f.pending.end());f.invoked=false;assert(!f.auth()&&f.pending.waiting_publication());f.published=true;assert(f.auth());return 0;}
 if(mode==23){assert(f.initial()&&f.enqueue()&&f.pending.end());f.published=true;f.tuples[0].asset++;assert(!f.auth());return 0;}
 if(mode==24){assert(f.initial()&&f.enqueue()&&f.pending.end());Call m{Kind::maintenance,7,2,0xabc,0x55,0x66};assert(f.pending.begin(m)&&f.pending.invoked());f.push(1,0);assert(!f.collect()&&f.pending.failed()&&!f.pending.waiting_publication());return 0;}
 if(mode==25||mode==26){f.call.kind=mode==25?Kind::zero_evaluate:Kind::saved_evaluate;assert(f.initial()&&f.enqueue()&&f.pending.end());f.published=true;assert(f.auth());return 0;}
 if(mode==27){f.call.kind=Kind::native_phase;assert(f.pending.begin(f.call)&&f.pending.invoked());assert(!f.create());return 0;}
 if(mode==28){f.call.kind=Kind::zero_evaluate;f.call.original_receipt=0;assert(!f.pending.begin(f.call)&&!f.create());return 0;}
 if(mode==29){assert(f.create(false,false,true));f.expose();assert(f.factory());return 0;}
 if(mode==21){f.bindings=false;assert(!f.create());return 0;}
 return 2;
}

#endif
