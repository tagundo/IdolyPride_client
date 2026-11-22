// Engine/IL2CPP/GPU services below are explicit host models; implementation is extracted from shipping source.

#include <cassert>
#include <cstdint>
#include <cstddef>
#include <cstdio>
#include <map>
using Method=void;enum class Mp4SceneResult{ok,waiting,stale,unsupported,failed};
struct Obj{uintptr_t native=0;int32_t id=0;bool active=false;}camera,native_camera,feature,native_feature;
struct Mp4SceneWitness{uint64_t generation=7;void*camera=&::camera;};
struct{Mp4SceneWitness source;}mp4_stage_host,mp4_scene_host;namespace idoly_mp4_runtime{struct{uint64_t generation=11;}job;}namespace mp4sourceworkers{struct{uint64_t watch=19;}host;}
struct Host{bool captured=true;uint64_t serial=23;void*batch=&feature;}coordinator,*mp4_proflare_coordinator=nullptr;size_t mp4_proflare_source_plan_count=0;
struct Mp4ProFlareAccess{Mp4ProFlareAccess(){}~Mp4ProFlareAccess(){}};
bool thread=true,boundary=true,lookup=true,alive=true,ready=true,retain_ok=true;int shape=0;unsigned traversals=0,frees=0;std::map<uint32_t,void*>roots;uint32_t nextroot=0;
bool game_call(){return thread;}bool mp4_alive(void*){return alive;}bool mp4_proflare_source_boundary(){return boundary;}bool mp4_proflare_ready(void*){return ready;}bool mp4_scene_same_source(const Mp4SceneWitness&a,const Mp4SceneWitness&b){return a.generation==b.generation&&a.camera==b.camera;}
template<class T>bool mp4_actor_field(void*p,size_t at,T&out){if(at==16){if constexpr(sizeof(T)==8){out=reinterpret_cast<T>(static_cast<Obj*>(p)->native);return true;}}if(at==8){if constexpr(sizeof(T)==4){out=static_cast<T>(static_cast<Obj*>(p)->id);return true;}}if(at==24){if constexpr(sizeof(T)==1){out=static_cast<T>(static_cast<Obj*>(p)->active);return true;}}return false;}
uint32_t mp4_retain(void*p){if(!retain_ok)return 0;roots[++nextroot]=p;return nextroot;}void*weak_get(uint32_t r){auto i=roots.find(r);return i==roots.end()?nullptr:i->second;}void weak_free(uint32_t r){++frees;roots.erase(r);}
bool mp4_renderer_proflare_source(void*c,void**f,void**co,void**r,void**b,void**d){++traversals;if(!lookup||c!=&camera)return false;*f=shape?&feature:nullptr;*co=shape==2?&feature:nullptr;*r=shape==3?&feature:nullptr;*b=shape==4?&feature:nullptr;*d=shape==5?&feature:nullptr;return true;}

#include "capture-witness-host.inc"

void reset(){thread=true;assert(mp4_proflare_empty_capture_release()&&roots.empty());boundary=lookup=alive=ready=retain_ok=true;shape=0;traversals=frees=0;camera.native=(uintptr_t)&native_camera;native_camera.id=41;feature.native=(uintptr_t)&native_feature;native_feature.id=43;feature.active=false;mp4_stage_host={};mp4_scene_host={};idoly_mp4_runtime::job.generation=11;mp4sourceworkers::host.watch=19;mp4_proflare_coordinator=nullptr;mp4_proflare_source_plan_count=0;coordinator={};}
int main(){unsigned cases=0;reset();uint64_t r=99;assert(!mp4_proflare_capture_current(&r)&&!r&&!traversals);++cases;
 reset();assert(mp4_proflare_capture_empty_source()==Mp4SceneResult::ok&&traversals>=2);assert(mp4_proflare_capture_current(&r)&&r);auto serial=r;assert(mp4_proflare_capture_empty_source()==Mp4SceneResult::ok&&mp4_proflare_capture_current(&r)&&r==serial);++cases;
 reset();shape=1;assert(mp4_proflare_capture_empty_source()==Mp4SceneResult::ok&&mp4_proflare_capture_current(&r)&&roots.size()==2);++cases;
 for(int bad=0;bad<9;++bad){reset();if(bad==0)boundary=false;if(bad==1)lookup=false;if(bad==2)alive=false;if(bad==3)mp4sourceworkers::host.watch=0;if(bad==4)shape=2;if(bad==5)shape=3;if(bad==6)shape=4;if(bad==7)shape=5;if(bad==8){shape=1;feature.active=true;}assert(mp4_proflare_capture_empty_source()!=Mp4SceneResult::ok&&!mp4_proflare_empty_capture.captured&&roots.empty());++cases;}
 reset();retain_ok=false;assert(mp4_proflare_capture_empty_source()==Mp4SceneResult::failed&&roots.empty());++cases;
 for(int bad=0;bad<7;++bad){reset();assert(mp4_proflare_capture_empty_source()==Mp4SceneResult::ok);if(bad==0)++idoly_mp4_runtime::job.generation;if(bad==1)++mp4_stage_host.source.generation;if(bad==2)++native_camera.id;if(bad==3)shape=1;if(bad==4)lookup=false;if(bad==5)roots.clear();if(bad==6)mp4_proflare_source_plan_count=1;r=99;assert(!mp4_proflare_capture_current(&r)&&!r);++cases;}
 reset();assert(mp4_proflare_capture_empty_source()==Mp4SceneResult::ok);thread=false;auto n=roots.size();auto f=frees;assert(!mp4_proflare_capture_current(&r)&&!mp4_proflare_empty_capture_release()&&roots.size()==n&&frees==f);thread=true;++cases;
 reset();mp4_proflare_coordinator=&coordinator;assert(mp4_proflare_capture_current(&r)&&r==23);ready=false;assert(!mp4_proflare_capture_current(&r)&&!r);ready=true;coordinator.captured=false;assert(!mp4_proflare_capture_current(&r));++cases;
 reset();assert(!mp4_proflare_capture_current(nullptr));assert(mp4_proflare_empty_capture_release()&&roots.empty());std::printf("%u actual PF nonzero/verified-zero capture witness cases passed\n",cases);}
