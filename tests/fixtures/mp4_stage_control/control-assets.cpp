#include <cassert>
#include <cstdint>
#include <cstddef>
#include <cstdlib>
#include <cstring>
#include <map>
#include <string>
#include <limits>
#include "control-asset-scope.hpp.inc"
using namespace idoly_mp4_control_assets;
int objects[16]{};Owner owner{&objects[0],&objects[1],&objects[2],&objects[3],&objects[4],&objects[5],&objects[6],100};
Input inputs{42,&objects[5],nullptr,7,1,1,0,2};
Cache cache{&objects[7],5,1,1,0,0,1};
int inventory_releases=0;bool throw_inventory=false;
bool source=true,clock_held=true,owner_ok=true,trusted=true,result_ok=true,writer_ok=true;int writes=0,retain_calls=0,fail_retain=0;uint32_t next=0;std::map<uint32_t,void*>roots;
bool current(void*,uint64_t e){return source&&e==11;}bool held(void*){return clock_held;}
bool inventory(void*,Owner*out,size_t,size_t*n){if(throw_inventory)throw 7;out[0]=owner;*n=1;return true;}bool current_owner(void*,const Owner&){return owner_ok;}
bool input(void*,const Owner&,Input*out){*out=inputs;return true;}bool image(void*,const Owner&,Cache*out){*out=cache;return true;}
bool authorize(void*,const Owner&,Handle graph,void*o,uint64_t*t){*t=1;return trusted&&graph.handle==42&&o==owner.owner_object;}
bool result_current(void*,const Owner&,Handle graph,Handle result){return result_ok&&graph.handle==42&&result.handle==101;}
bool write(void*,const Owner&,const Cache&c){++writes;if(!writer_ok)return false;cache=c;return true;}
uint32_t keep(void*p){if(++retain_calls==fail_retain)return 0;roots[++next]=p;return next;}
void*get(uint32_t h){auto it=roots.find(h);return it==roots.end()?nullptr:it->second;}void drop(uint32_t h){assert(roots.erase(h)==1);}
Api api(){return {current,held,inventory,[](void*){++inventory_releases;},current_owner,input,image,authorize,result_current,write,keep,get,drop};}
void mutate(){cache={&objects[8],19,0,0,1,1,0};}
int main(int argc,char**argv){assert(argc==2);std::string c=argv[1];Scope scope;
 if(c=="inventory_exception"){throw_inventory=true;try{(void)scope.capture(api(),&scope,11);assert(false);}catch(int v){assert(v==7);}assert(inventory_releases==1);assert(scope.release(false)==Result::ok&&roots.empty());return 0;}
 if(c=="capture_invalid"){inputs.prefab=&objects[9];assert(scope.capture(api(),&scope,11)==Result::unsupported);assert(scope.release(false)==Result::ok&&roots.empty());return 0;}
 if(c=="capture_partial"){fail_retain=4;assert(scope.capture(api(),&scope,11)==Result::failed);assert(scope.release(false)==Result::ok&&roots.empty());return 0;}
 if(c=="infinity")cache.duration=std::numeric_limits<double>::infinity();
 assert(scope.capture(api(),&scope,11)==Result::ok&&scope.current()&&inventory_releases==1);
 if(c=="unknown"){Ticket ticket;assert(scope.before(&objects[10],{42,2,0},owner.owner_object,ticket)==Dispatch::forward&&!ticket.owned&&scope.current());}
 else if(c=="untrusted"){trusted=false;Ticket ticket;assert(scope.before(owner.asset,{42,2,0},owner.owner_object,ticket)==Dispatch::forward&&!scope.current());}
 else if(c=="unreceipted"){cache.duration=99;assert(!scope.current());Ticket ticket;assert(scope.before(owner.asset,{42,2,0},owner.owner_object,ticket)!=Dispatch::owned);}
 else if(c=="input_change"){++inputs.seed;assert(!scope.current()&&scope.restore()==Result::stale);}
 else {
  Ticket ticket;assert(scope.before(owner.asset,{42,2,0},owner.owner_object,ticket)==Dispatch::owned);
  if(c=="inflight"){assert(scope.release(false)==Result::waiting);assert(scope.restore()==Result::waiting);}
  if(c=="owner_lost"){source=false;assert(scope.after(ticket,{101,2,0},true)==Result::stale);assert(!writes);assert(scope.release(false)==Result::ok&&roots.empty());return 0;}
  mutate();assert(scope.current());
  if(c=="original_exception"){assert(scope.after(ticket,{},false)==Result::failed);assert(scope.restore()==Result::ok&&writes==1);assert(scope.release(false)==Result::ok&&roots.empty());return 0;}
  if(c=="wrong_result")result_ok=false;
  const auto after=scope.after(ticket,{101,2,0},true);
  assert(after==(result_ok?Result::ok:Result::failed));
  if(result_ok)assert(scope.factory_receipted(owner.asset,{101,2,0}));
  if(c=="cleanup_false"){assert(scope.release(false)==Result::ok&&writes==0&&cache.duration==19&&roots.empty());return 0;}
  if(c=="restore_superseded"){cache.duration=77;assert(scope.restore()==Result::stale&&writes==0);assert(scope.release(false)==Result::ok&&roots.empty());return 0;}
  if(c=="restore_owner_lost"){owner_ok=false;assert(scope.restore()==Result::stale&&writes==0);assert(scope.release(false)==Result::ok&&roots.empty());return 0;}
  if(c=="restore_writer_failed"){writer_ok=false;assert(scope.restore()==Result::stale&&writes==1);assert(scope.release(false)==Result::ok&&roots.empty());return 0;}
  assert(scope.restore()==Result::ok&&writes==1&&cache.controlled_asset==&objects[7]);
  if(c=="infinity")assert(cache.duration==std::numeric_limits<double>::infinity());else assert(cache.duration==5);
  assert(scope.restore()==Result::ok&&writes==1);
 }
 assert(scope.release(false)==Result::ok&&roots.empty());
 if(c=="reuse"){source=true;assert(scope.capture(api(),&scope,11)==Result::ok);assert(scope.release(false)==Result::ok&&roots.empty());}
}
