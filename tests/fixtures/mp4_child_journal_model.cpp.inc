// Unit model of the actual shared journal. No original native/GPU claim.
#include "mp4_engine_clock.hpp"
#include "pending-journal.hpp"
#include <cassert>
#include <vector>
#include <string>
#include <cstdlib>
using namespace mp4_director_maintenance;
using world::AnimationGraph;using world::DirectorAuthorization;using world::DirectorPending;
struct Host{
 alignas(16) unsigned char manager[0x500]{},queue[16]{},graphs[2][0xf8]{},slots[2][0x40]{},nodes[32][32]{},vectors[2][2][512]{},temporary[32]{},data[32*24]{};
 Journal journal;bool frame_exact=true;unsigned frame_phase=5;bool current=true,origin=true,source_closed=true,owns[2]={true,true},before_output=true;size_t next_node=0;uint64_t serial=0;
 struct Span{void*p;size_t n;};std::vector<Span>spans;
 Host(){spans={{manager,sizeof manager},{queue,sizeof queue},{graphs,sizeof graphs},{slots,sizeof slots},{nodes,sizeof nodes},{vectors,sizeof vectors},{temporary,sizeof temporary},{data,sizeof data}};
  put(manager,0x478,ptr(queue));for(unsigned i=0;i<2;++i){put(slots[i],0x20,uint32_t(20));put(slots[i],0x28,ptr(graphs[i]));put(graphs[i],16,ptr(slots[i]));put(manager,i?0x3a8:0x388,ptr(vectors[i][0]));put(manager,(i?0x3a8:0x388)+24,uint64_t(32*2));}assert(journal.configure(api()));}
 static uintptr_t ptr(const void*p){return reinterpret_cast<uintptr_t>(p);}template<class T>static void put(void*p,size_t at,T v){memcpy(static_cast<unsigned char*>(p)+at,&v,sizeof v);}template<class T>static T get(void*p,size_t at){T v{};memcpy(&v,static_cast<unsigned char*>(p)+at,sizeof v);return v;}
 AnimationGraph handle(unsigned i=0,uint32_t version=20){return{ptr(slots[i]),version,0};}
 world::DirectorGraphIdentity id(unsigned i=0){return{ptr(graphs[i]),ptr(slots[i]),get<uint32_t>(slots[i],0x20),1,2,0};}
 Api api(){Api a{};a.context=this;a.manager=ptr(manager);a.tagged_queue=true;
  a.current=[](void*p,const Call&c){return static_cast<Host*>(p)->current&&c.epoch==7&&c.source_asset==0xabc;};
  a.call_origin=[](void*p,const Call&c){return static_cast<Host*>(p)->origin&&c.receiver==0x55&&c.method==0x66;};
  a.hook_origin=[](void*p,Hook,uintptr_t,const Call&){return static_cast<Host*>(p)->origin;};
  a.future_producers_closed=[](void*p,const Call&){return static_cast<Host*>(p)->source_closed;};
  a.frame_deferred_current=[](void*p,const Call&c){auto&h=*static_cast<Host*>(p);return h.frame_exact&&h.frame_phase==5&&c.kind==Kind::native_phase&&c.serial==h.serial&&c.original_receipt==1000+c.serial&&c.method==0x66;};
  a.retired_output=[](void*p,uint64_t e,uintptr_t n,uintptr_t s,uint32_t v,uint64_t r,uintptr_t o){auto&h=*static_cast<Host*>(p);return h.before_output&&e==7&&n==ptr(h.graphs[0])&&s==ptr(h.slots[0])&&v==20&&r==1001&&o==0x700;};
  a.read=[](void*p,uintptr_t at,void*out,size_t n){auto&h=*static_cast<Host*>(p);for(auto s:h.spans){auto b=ptr(s.p);if(at>=b&&n<=s.n&&at-b<=s.n-n){memcpy(out,reinterpret_cast<void*>(at),n);return true;}}return false;};
  a.basis=[](void*p,const Call&c,AnimationGraph g,uint32_t,Basis*out){auto&h=*static_cast<Host*>(p);for(unsigned i=0;i<2;++i)if(g.handle==ptr(h.slots[i])&&h.owns[i]){*out={h.id(i),7,c.serial,0x91,0x92,0xabc};return true;}return false;};return a;}
 bool begin(Kind k=Kind::play){Call c{k,7,++serial,0xabc,0x55,0x66,(k==Kind::rebuild||k==Kind::native_phase)?1000+serial:0};return journal.begin(c)&&journal.invoked();}
 void push(unsigned i,unsigned op,uint32_t version=20){assert(next_node<32);void*n=nodes[next_node++];put(n,0,get<uintptr_t>(queue,0));put(n,8,ptr(slots[i]));put(n,16,version);put(n,24,uint32_t(op));put(queue,0,ptr(n));put(queue,8,get<uint64_t>(queue,8)+1);}
 void append(unsigned i,unsigned which,bool relocate=false,uint32_t version=20){const size_t at=which?0x3a8:0x388;auto base=get<uintptr_t>(manager,at);auto n=get<uint64_t>(manager,at+16);if(relocate){memcpy(vectors[which][1],reinterpret_cast<void*>(base),size_t(n)*16);base=ptr(vectors[which][1]);put(manager,at,base);}put(reinterpret_cast<void*>(base),size_t(n)*16,handle(i,version));put(manager,at+16,n+1);}
 bool produce(unsigned i,unsigned op,bool relocate=false,uint32_t version=20){Ticket t{};auto kind=op<7?Hook::enqueue:op==7?Hook::append_a:Hook::append_b;if(!journal.native_begin(kind,ptr(manager),op,handle(i,version),t))return false;if(op<7)push(i,op,version);else append(i,op==8,relocate,version);return journal.native_end(t);}
 DirectorPending pending(unsigned i=0,unsigned op=0,uintptr_t record=0){return{id(i),record?record:get<uintptr_t>(queue,0),op};}
 bool auth(unsigned i=0,unsigned op=0,uintptr_t record=0){DirectorAuthorization out{};return journal.authorization(pending(i,op,record),out);}
 bool collect(){Ticket t{};if(!journal.collect_begin(ptr(queue),t))return false;uintptr_t cursor=get<uintptr_t>(queue,0);size_t count=0;while(cursor){auto*n=reinterpret_cast<void*>(cursor);put(data,count*24,get<uintptr_t>(n,8));put(data,count*24+8,get<uint32_t>(n,16));put(data,count*24+16,get<uint32_t>(n,24));cursor=get<uintptr_t>(n,0);++count;}put(queue,0,uintptr_t(0));put(queue,8,get<uint64_t>(queue,8)+count);put(temporary,0,ptr(data));put(temporary,16,uint64_t(count));put(temporary,24,uint64_t(64));return journal.collect_end(t,ptr(temporary));}
};
int main(int argc,char**argv){assert(argc==2);int mode=std::atoi(argv[1]);Host h;
 if(mode==0){assert(h.begin()&&h.produce(0,0)&&h.journal.end()&&h.auth());assert(h.begin(Kind::maintenance)&&h.collect()&&h.journal.end());assert(!h.auth());return 0;}
 if(mode==1){h.push(0,0);assert(!h.begin()&&h.journal.failed());return 0;}
 if(mode==2){h.push(1,0,18);assert(h.begin()&&h.journal.end());return 0;}
 if(mode==3){h.source_closed=false;assert(!h.begin(Kind::maintenance));return 0;}
 if(mode==4){assert(h.begin());assert(!h.produce(0,1)&&h.journal.failed());return 0;}
 if(mode==5){assert(h.begin());h.owns[1]=false;assert(!h.produce(1,0));return 0;}
 if(mode==6){assert(h.begin()&&h.produce(0,0));h.push(0,0);assert(!h.auth()&&!h.journal.end());return 0;}
 if(mode==7){assert(h.begin()&&h.produce(0,0)&&h.journal.end());assert(h.begin(Kind::maintenance));h.push(1,0);auto head=Host::get<uintptr_t>(h.queue,0);assert(!h.collect()&&Host::get<uintptr_t>(h.queue,0)==head);return 0;}
 if(mode==8){assert(h.begin(Kind::rebuild)&&h.produce(0,7));auto old=Host::get<uintptr_t>(h.manager,0x388);assert(h.produce(1,7,true));auto now=Host::get<uintptr_t>(h.manager,0x388);assert(old!=now&&h.auth(0,7,now)&&h.auth(1,7,now+16)&&h.journal.end());return 0;}
 if(mode==9){assert(h.begin(Kind::rebuild)&&h.produce(0,8)&&h.journal.end());assert(h.begin(Kind::maintenance)&&h.journal.deferred_begin(1));assert(h.produce(1,8));Host::put(h.manager,0x3b8,uint64_t(0));assert(h.journal.deferred_end(1)&&h.journal.end());return 0;}
 if(mode==10){assert(h.begin(Kind::rebuild)&&h.produce(0,7)&&h.journal.end());assert(h.begin(Kind::maintenance));h.append(1,0);auto n=Host::get<uint64_t>(h.manager,0x398);assert(!h.journal.deferred_begin(0)&&Host::get<uint64_t>(h.manager,0x398)==n);return 0;}
 if(mode==11){assert(h.begin()&&h.produce(0,0)&&h.journal.end());assert(h.begin(Kind::maintenance)&&h.collect());for(unsigned k=0;k<16;++k){assert(h.produce(0,k%7)&&h.collect());}assert(h.journal.end());return 0;}
 if(mode==12){assert(h.begin()&&h.produce(0,0));auto record=Host::get<uintptr_t>(h.queue,0);h.current=false;assert(!h.auth()&&!h.journal.end());h.journal.detach();assert(!h.journal.active()&&record);return 0;}
 if(mode==13){assert(h.begin(Kind::rebuild));Host::put(h.slots[0],0x20,uint32_t(22));assert(h.produce(0,2,false,22)&&h.journal.end());assert(h.journal.pending_destroy_receipt(7,Host::ptr(h.graphs[0]),Host::ptr(h.slots[0]),20,1001,0x700));assert(!h.journal.pending_destroy_receipt(7,Host::ptr(h.graphs[0]),Host::ptr(h.slots[0]),20,1002,0x700));assert(!h.journal.pending_destroy_receipt(7,Host::ptr(h.graphs[0]),Host::ptr(h.slots[0]),18,1001,0x700));h.before_output=false;assert(!h.journal.pending_destroy_receipt(7,Host::ptr(h.graphs[0]),Host::ptr(h.slots[0]),20,1001,0x700));return 0;}
 if(mode==14){assert(h.begin()&&h.produce(0,0)&&h.journal.end());Host::put(h.slots[0],0x20,uint32_t(22));assert(!h.auth());return 0;}
 if(mode==15){assert(h.begin()&&h.produce(0,0));Host::put(h.nodes[0],24,uint32_t(1));assert(!h.auth());return 0;}
 if(mode==16){assert(h.begin());h.origin=false;Ticket t{};assert(!h.journal.native_begin(Hook::enqueue,Host::ptr(h.manager),0,h.handle(),t));return 0;}
 if(mode==17){assert(h.begin());Ticket t{};assert(h.journal.native_begin(Hook::enqueue,Host::ptr(h.manager),0,h.handle(),t));h.push(0,0);h.push(1,0);assert(!h.journal.native_end(t));return 0;}
 if(mode==18){assert(h.begin());Ticket t{};assert(h.journal.native_begin(Hook::enqueue,Host::ptr(h.manager),0,h.handle(),t));h.push(0,0);++t.sequence;assert(!h.journal.native_end(t));return 0;}
 if(mode==19){assert(h.begin(Kind::rebuild)&&h.produce(0,7)&&h.journal.end());h.source_closed=false;assert(!h.begin(Kind::maintenance));assert(Host::get<uint64_t>(h.manager,0x398)==1);return 0;}
 if(mode==20){assert(h.begin()&&h.produce(0,0)&&h.journal.end());Call c{Kind::maintenance,7,1,0xabc,0x55,0x66};assert(!h.journal.begin(c));return 0;}
 if(mode==21){assert(h.begin());h.journal.detach();h.current=false;DirectorAuthorization out{};assert(!h.journal.authorization(h.pending(),out));return 0;}
 if(mode==22){assert(h.begin(Kind::native_phase)&&h.produce(0,7)&&h.journal.end());assert(h.begin(Kind::native_phase)&&!h.journal.maintenance_closed()&&h.journal.deferred_closed()&&h.journal.deferred_begin(0));Host::put(h.manager,0x398,uint64_t(0));assert(h.journal.deferred_end(0)&&h.journal.end());return 0;}
 if(mode==23){assert(h.begin(Kind::native_phase)&&h.produce(0,8)&&h.journal.end());assert(h.begin(Kind::native_phase)&&h.journal.deferred_begin(1));Host::put(h.manager,0x3b8,uint64_t(0));assert(h.journal.deferred_end(1)&&h.journal.end());return 0;}
 if(mode>=24&&mode<=28){if(mode==27){auto api=h.api();api.frame_deferred_current=nullptr;h.journal=Journal{};assert(h.journal.configure(api));}assert(h.begin(Kind::rebuild)&&h.produce(0,7)&&h.journal.end());
  assert(h.begin(mode==28?Kind::play:Kind::native_phase));if(mode==24)h.frame_phase=0;if(mode==25)++h.serial;if(mode==26)h.frame_exact=false;assert(!h.journal.deferred_begin(0)&&Host::get<uint64_t>(h.manager,0x398)==1);return 0;}
 if(mode==29){assert(h.begin(Kind::rebuild)&&h.produce(0,7)&&h.journal.end());h.frame_phase=0;assert(h.begin(Kind::maintenance)&&h.journal.maintenance_closed()&&h.journal.deferred_closed()&&h.journal.deferred_begin(0));return 0;}
 if(mode==30){Call call{Kind::native_phase,7,++h.serial,0xabc,0x55,0x66,1000+h.serial};assert(h.journal.begin(call)&&!h.journal.current_call(call));assert(h.journal.invoked()&&h.journal.current_call(call));auto wrong=call;++wrong.original_receipt;assert(!h.journal.current_call(wrong));assert(h.journal.end()&&!h.journal.current_call(call));return 0;}
 if(mode==31){assert(h.begin(Kind::native_phase)&&h.produce(0,7)&&h.journal.end());assert(h.begin(Kind::native_phase)&&h.journal.deferred_begin(0)&&h.produce(1,7));Host::put(h.manager,0x398,uint64_t(0));assert(h.journal.deferred_end(0)&&h.journal.end());return 0;}
 if(mode==32){assert(h.begin(Kind::native_phase)&&h.produce(0,7)&&h.journal.end());assert(h.begin(Kind::native_phase));h.source_closed=false;assert(!h.journal.deferred_begin(0)&&Host::get<uint64_t>(h.manager,0x398)==1);return 0;}
 if(mode==33){Call call{Kind::native_phase,7,++h.serial,0xabc,0x55,0x66,0};assert(h.journal.begin(call)&&h.journal.invoked());assert(!h.journal.deferred_closed());return 0;}
 if(mode==34){assert(h.begin(Kind::native_phase));h.current=false;assert(!h.journal.deferred_closed()&&!h.journal.current_call(h.journal.call()));return 0;}
 return 2;
}
