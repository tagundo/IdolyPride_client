// Engine/IL2CPP/GPU services below are explicit host models; implementation is extracted from shipping source.

#include <cassert>
#include <cstdint>
#include <cstddef>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>
#include <initializer_list>
using Method=void;
struct Object{uint8_t bytes[256]{};};Object flare,atlas,element,elements,array,transform,go,feature,compute,render,batch,camera,other;
struct Mp4SceneWitness{uint64_t generation=7;void*camera=::camera.bytes;};struct Mp4TimelineContext{Mp4SceneWitness witness;int phase=0;};
struct Mp4ProFlareCacheImage{void*flare=nullptr,*atlas=nullptr,*elements=nullptr,*array=nullptr,*transform=nullptr,*go=nullptr,*batch=nullptr;uintptr_t batch_native=0;void*element[256]{};size_t count=0;};
struct{Mp4SceneWitness source;}mp4_stage_host;struct{int flare=1;}mp4_proflare_pins;
bool main_thread=true,source=true,schema=true,pins=true,live=true,cache=true,source_lookup=true;uint64_t initialized_receipt=0;unsigned lookups=0;Mp4ProFlareCacheImage actual;
std::map<uint32_t,void*>roots;uint32_t nextroot=0;int allocations=0,fail_after=-1;
bool game_call(){return main_thread;}bool mp4_timeline_source_plan_phase(int p){return p==0||p==4;}bool mp4_stage_admission_source(const Mp4SceneWitness&w){return source&&w.generation==7&&w.camera==camera.bytes;}bool mp4_proflare_source_schema(){return schema;}bool mp4_timeline_exact(void*f,int){return f==flare.bytes;}bool mp4_alive(void*){return live;}
bool mp4_scene_same_source(const Mp4SceneWitness&a,const Mp4SceneWitness&b){return a.generation==b.generation&&a.camera==b.camera;}bool mp4_control_source_current(void*,uint64_t s){return source&&s==7;}
uint32_t mp4_retain(void*p){if(fail_after>=0&&allocations++==fail_after)return 0;roots[++nextroot]=p;return nextroot;}void*weak_get(uint32_t r){auto i=roots.find(r);return i==roots.end()?nullptr:i->second;}void weak_free(uint32_t r){roots.erase(r);}
bool mp4_proflare_cache_image(void*f,Mp4ProFlareCacheImage*out,bool){if(!cache||f!=flare.bytes)return false;*out=actual;return true;}
bool mp4_proflare_cache_same(const Mp4ProFlareCacheImage&a,const Mp4ProFlareCacheImage&b){return !std::memcmp(&a,&b,sizeof a);}
bool mp4_proflare_cache_current(void*f,uint64_t*out){*out=f==flare.bytes?initialized_receipt:0;return *out!=0;}
bool mp4_renderer_proflare_source(void*c,void**f,void**co,void**r,void**b,void**d){++lookups;if(!source_lookup||c!=camera.bytes)return false;*f=feature.bytes;*co=compute.bytes;*r=render.bytes;*b=batch.bytes;*d=nullptr;return true;}
bool mp4_proflare_pass_setter(void*p,size_t index){return pins&&p==(index?render.bytes:compute.bytes);}
template<class T>bool mp4_actor_field(void*p,size_t at,T&out){if(at+sizeof out>sizeof(Object))return false;std::memcpy(&out,static_cast<uint8_t*>(p)+at,sizeof out);return true;}
template<class T>void put(void*p,size_t at,T v){std::memcpy(static_cast<uint8_t*>(p)+at,&v,sizeof v);}

#include "source-plan-host.inc"

void reset(){assert(mp4_proflare_source_plans_retire());assert(roots.empty());main_thread=source=schema=pins=live=cache=source_lookup=true;initialized_receipt=0;lookups=0;allocations=0;fail_after=-1;actual={};actual.flare=flare.bytes;actual.atlas=atlas.bytes;actual.elements=elements.bytes;actual.array=array.bytes;actual.transform=transform.bytes;actual.go=go.bytes;actual.element[0]=element.bytes;actual.count=1;put(feature.bytes,48,static_cast<void*>(compute.bytes));put(feature.bytes,56,static_cast<void*>(render.bytes));put(feature.bytes,80,static_cast<void*>(batch.bytes));put(compute.bytes,136,static_cast<void*>(batch.bytes));put(render.bytes,136,static_cast<void*>(batch.bytes));mp4_stage_host={};}
int main(){unsigned cases=0;reset();Mp4TimelineContext c;assert(mp4_proflare_source_component_plan_unlocked(c,flare.bytes,go.bytes));assert(mp4_proflare_source_plan_count==1&&roots.size()==11);auto*p=mp4_proflare_source_plan_find(flare.bytes);assert(p&&p->serial&&!p->initialized);assert(mp4_proflare_source_component_plan_unlocked(c,flare.bytes,go.bytes)&&mp4_proflare_source_plan_count==1);++cases;
 reset();c.phase=4;assert(mp4_proflare_source_component_plan_unlocked(c,flare.bytes,go.bytes));++cases;c.phase=0;
 for(int bad=0;bad<10;++bad){reset();if(bad==0)source=false;if(bad==1)schema=false;if(bad==2)pins=false;if(bad==3)live=false;if(bad==4)cache=false;if(bad==5)source_lookup=false;if(bad==6)c.phase=2;if(bad==7)actual.go=other.bytes;if(bad==8)actual.batch=other.bytes;if(bad==9)main_thread=false;assert(!mp4_proflare_source_component_plan_unlocked(c,flare.bytes,go.bytes)&&!mp4_proflare_source_plan_count&&roots.empty());main_thread=true;c.phase=0;++cases;}
 for(int fail=0;fail<11;++fail){reset();fail_after=fail;assert(!mp4_proflare_source_component_plan_unlocked(c,flare.bytes,go.bytes)&&!mp4_proflare_source_plan_count&&roots.empty());++cases;}
 reset();assert(mp4_proflare_source_component_plan_unlocked(c,flare.bytes,go.bytes));p=mp4_proflare_source_plan_find(flare.bytes);auto serial=p->serial;auto*r=const_cast<Mp4ProFlareSourcePlan*>(p);r->initialized=initialized_receipt=61;actual.batch=batch.bytes;actual.batch_native=71;assert(mp4_proflare_source_plan_current(*p));source=false;source_lookup=false;unsigned before=lookups;assert(mp4_proflare_source_plan_retained(*p)&&p->serial==serial&&lookups==before);++cases;
 initialized_receipt=62;assert(!mp4_proflare_source_plan_retained(*p));initialized_receipt=61;put(render.bytes,136,static_cast<void*>(other.bytes));assert(!mp4_proflare_source_plan_retained(*p));put(render.bytes,136,static_cast<void*>(batch.bytes));assert(mp4_proflare_source_plan_retained(*p));++cases;
 roots.erase(p->retained.roots[0]);assert(!mp4_proflare_source_plan_retained(*p));++cases;
 reset();assert(mp4_proflare_source_component_plan_unlocked(c,flare.bytes,go.bytes));main_thread=false;assert(!mp4_proflare_source_plans_retire()&&mp4_proflare_source_plan_count==1&&!roots.empty());main_thread=true;assert(mp4_proflare_source_plans_retire()&&roots.empty());++cases;
 std::free(mp4_proflare_source_plans);mp4_proflare_source_plans=nullptr;std::printf("%u actual PF source-plan/retained-construction cases passed\n",cases);}
