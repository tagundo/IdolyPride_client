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
unsigned current_calls=0;bool current(void*,uint64_t e){++current_calls;return source&&e==11;}bool held(void*){return clock_held;}
bool inventory(void*,Owner*out,size_t,size_t*n){if(throw_inventory)throw 7;out[0]=owner;*n=1;return true;}bool current_owner(void*,const Owner&){return owner_ok;}
bool input(void*,const Owner&,Input*out){*out=inputs;return true;}bool drift_final=false;unsigned image_calls=0;bool image(void*,const Owner&,Cache*out){++image_calls;*out=cache;if(drift_final&&image_calls>=3)source=false;return true;}
bool authorize(void*,const Owner&,Handle graph,void*o,uint64_t*t){*t=1;return trusted&&graph.handle==42&&o==owner.owner_object;}
bool result_current(void*,const Owner&,Handle graph,Handle result){return result_ok&&graph.handle==42&&result.handle==101;}
bool write(void*,const Owner&,const Cache&c){++writes;if(!writer_ok)return false;cache=c;return true;}
uint32_t keep(void*p){if(++retain_calls==fail_retain)return 0;roots[++next]=p;return next;}
bool root_lost=false;void*get(uint32_t h){if(root_lost)return nullptr;auto it=roots.find(h);return it==roots.end()?nullptr:it->second;}void drop(uint32_t h){assert(roots.erase(h)==1);}
Api api(){return {current,held,inventory,[](void*){++inventory_releases;},current_owner,input,image,authorize,result_current,write,keep,get,drop};}
void mutate(){cache={&objects[8],19,0,0,1,1,0};}
int main(int argc,char**argv){assert(argc==2);const int mode=atoi(argv[1]);Scope scope;Snapshot snap{};
 if(mode==1){assert(!scope.snapshot(owner,&snap));return 0;}
 assert(scope.capture(api(),&scope,11)==Result::ok);const int initial_roots=roots.size();
 if(mode==21)drift_final=true;
 if(mode==2)clock_held=false;if(mode==3)source=false;if(mode==4)owner_ok=false;
 if(mode==5)++inputs.seed;if(mode==6)cache.duration=6;if(mode==7)root_lost=true;
 Owner query=owner;
 if(mode>=8&&mode<15){void**p[]={&query.asset,&query.director,&query.timeline,&query.track,&query.clip,&query.source_object,&query.owner_object};*p[mode-8]=&objects[15];}
 if(mode==15)++query.native;if(mode==16)scope.invalidate();
 if(mode==17){Ticket ticket;assert(scope.before(owner.asset,{42,2,0},owner.owner_object,ticket)==Dispatch::owned);assert(!scope.snapshot(owner,&snap));mutate();assert(scope.after(ticket,{101,2,0},true)==Result::ok);assert(scope.snapshot(owner,&snap));assert(snap.event_count==1&&snap.touched&&!snap.restored&&snap.current.duration==19&&snap.initial.duration==5);assert(scope.restore()==Result::ok);assert(scope.snapshot(owner,&snap)&&snap.restored&&snap.current.duration==5);assert(scope.release(false)==Result::ok&&roots.empty());return 0;}
 if(mode==18){assert(!scope.snapshot(owner,nullptr));assert(scope.release(false)==Result::ok&&roots.empty());return 0;}
 const bool good=mode==0||mode==19||mode==20;const auto before_writes=writes;assert(scope.snapshot(query,&snap)==good);assert(writes==before_writes);
 if(good){assert(snap.epoch==11&&snap.index==0&&!snap.event_count&&!snap.touched&&!snap.restored&&snap.initial.duration==5&&snap.current.duration==5&&snap.owner.asset==owner.asset);assert(roots.size()==size_t(initial_roots));}
 else assert(!snap.epoch);
 if(mode==19){assert(scope.release(false)==Result::ok);assert(!scope.snapshot(owner,&snap));return 0;}
 if(mode==20){scope.invalidate();assert(!scope.snapshot(owner,&snap));}
 // Root loss models an actual GC-handle invalidation. Restore its bookkeeping
 // before cleanup; no fake captured image is published by failed queries.
 if(mode==7)root_lost=false;
 assert(scope.release(false)==Result::ok&&roots.empty());
}