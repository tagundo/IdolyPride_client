// Engine/IL2CPP/GPU services below are explicit host models; implementation is extracted from shipping source.

#include <cassert>
#include <cstdint>
#include <cstddef>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>
#include <vector>
#include <stdexcept>
#include <atomic>
using Method=void;enum class Mp4SceneResult{ok,waiting,stale,unsupported,failed};struct Binding{uintptr_t rva=0;};uintptr_t image_base=0;
struct Obj{uint8_t raw[320]{};};Obj batch,atlas,flares[7],elements[7],camera,data,dict,list,queue,backing;
struct Mp4SceneWitness{uint64_t generation=7;void*camera=::flares;};
struct CacheImage{void*flare=nullptr,*atlas=nullptr;void*element[256]{};size_t count=0;};
struct Mp4ProFlareSourcePlan{Mp4SceneWitness source;void*batch=::flares;uint64_t initialized=0,serial=13;struct{CacheImage image;}retained;};Mp4ProFlareSourcePlan plans[7];Mp4ProFlareSourcePlan*mp4_proflare_source_plans=plans;size_t mp4_proflare_source_plan_count=7;
struct Mp4ProFlareScalarImage{bool captured=false;};struct Mp4ProFlareSubImage{};struct Mp4ProFlareDataImage{void*object=nullptr;bool captured=false,gpu_touched=false;};
struct{Mp4SceneWitness source;}mp4_stage_host;namespace idoly_mp4_runtime{struct{uint64_t generation=11;}job;}
bool boundary=true,schema=true,valid=true,cache_ok=true,capture_ok=true,pass_ok=true,source_data=false,source_atlas=true,throw_start=false;
unsigned starts=0,scalar_captures=0,sub_captures=0,reads=0,captures=0,pass_calls=0,binds=0;size_t occupancy=0,capacity=0,source_occupancy=0;
unsigned depth=0;struct Mp4ProFlareAccess{Mp4ProFlareAccess(){++depth;}~Mp4ProFlareAccess(){--depth;}};bool mp4_proflare_source_boundary(){return boundary;}bool mp4_proflare_source_schema(){return schema;}
std::atomic<bool>mp4_proflare_access_withdrawn{false},mp4_proflare_access_published{false};
namespace mp4pf{enum class Result{ok,failed};struct List{void*object=nullptr,*array=nullptr;void**rows=nullptr;size_t count=0,capacity=0;};struct Dictionary{void*object=nullptr,*buckets=nullptr,*entries=nullptr,*comparer=nullptr,*keys=nullptr,*values=nullptr;};struct Queue{void*object=nullptr,*array=nullptr;};struct Image{void*batch=nullptr,*atlas=nullptr;List list,data;Queue queue;Dictionary dictionary;};struct PromotedImage{Image image;void*list[16]{},*data[16]{};int queue[16]{},buckets[16]{},entries[16]{};};class LogicalImage{Image before{};public:bool capture(const Image&i){before=i;return true;}bool restore_image(const Image&i,PromotedImage*out){*out={};out->image=i;out->image.list.count=before.list.count;return true;}};}
struct{void*batch=nullptr;uint64_t epoch=0,owner=0;uint32_t root=0;bool restoring=false;}mp4_proflare_registry_host;
struct{bool captured=false;bool active(){return captured;}bool current(){return valid;}}mp4_proflare_registry_scope;
void*registry_rows[16]{};void*data_rows[1]{};std::map<uint32_t,void*>roots;uint32_t next_root=0;
uint32_t mp4_retain(void*p){roots[++next_root]=p;return next_root;}void*weak_get(uint32_t r){auto i=roots.find(r);return i==roots.end()?nullptr:i->second;}void weak_free(uint32_t r){roots.erase(r);}
bool game_call(){return true;}bool mp4_proflare_source_plan_current(const Mp4ProFlareSourcePlan&p){return valid&&p.serial&&p.retained.image.flare&&p.batch==&batch;}
bool mp4_scene_same_source(const Mp4SceneWitness&a,const Mp4SceneWitness&b){return a.generation==b.generation&&a.camera==b.camera;}
bool mp4_proflare_registry_read(void*,mp4pf::Image*out){++reads;*out={};out->batch=&batch;out->atlas=source_atlas?&atlas:nullptr;out->list={&list,&backing,registry_rows,occupancy,capacity};out->data={&list,&backing,data_rows,source_data?size_t(1):0,size_t(1)};out->dictionary.object=&dict;out->queue.object=&queue;return true;}
bool mp4_proflare_registry_write(void*,const mp4pf::Image&i,void*const*,const int*,const int*,const int*,void*const*){occupancy=i.list.count;return true;}
void mp4_proflare_registry_release(){if(mp4_proflare_registry_host.root)weak_free(mp4_proflare_registry_host.root);mp4_proflare_registry_host={};mp4_proflare_registry_scope.captured=false;}
mp4pf::Result mp4_proflare_registry_capture(void*b,void*const*f,size_t n,uint64_t epoch){assert(b==&batch&&n==7&&epoch==7&&occupancy==source_occupancy&&capacity>=7);for(size_t i=0;i<n;++i)assert(f[i]==&flares[i]);++captures;mp4_proflare_registry_scope.captured=true;return mp4pf::Result::ok;}
using Mp4ProFlareStart=void(*)(void*,Method*);void actual_start(void*,Method*){}Mp4ProFlareStart mp4_proflare_start_trampoline=actual_start;struct{Binding start;int data=1;}mp4_proflare_pins;
const void*font_method(void*,const char*,int){return &atlas;}void*object_class(void*p){return p;}
template<class T>bool mp4_actor_field(void*p,size_t at,T&out){if(p==&data&&at==24){void*cam=mp4_stage_host.source.camera;std::memcpy(&out,&cam,sizeof out);return true;}std::memcpy(&out,static_cast<uint8_t*>(p)+at,sizeof out);return true;}
template<class T>bool mp4_stage_store(void*p,size_t at,const T&v){std::memcpy(static_cast<uint8_t*>(p)+at,&v,sizeof v);return true;}
bool mp4_proflare_cache_route_current(const Mp4ProFlareSourcePlan&p){return p.batch==&batch;}
bool mp4_proflare_cache_prepare(void*f,Method*,Mp4ProFlareStart,uint64_t*out){++starts;static_cast<uint8_t*>(f)[256]=1;++occupancy;if(capacity<occupancy)capacity=occupancy;*out=31+starts;if(throw_start)throw std::runtime_error("source");return cache_ok;}
bool mp4_proflare_scalar_capture(Mp4ProFlareScalarImage&i,void*,int){++scalar_captures;i.captured=capture_ok;return capture_ok;}
bool mp4_proflare_sub_capture(Mp4ProFlareSubImage&,void*,size_t*){++sub_captures;return capture_ok;}
bool mp4_proflare_registry_list(void*,const char*,size_t,int,mp4pf::List*out){*out={&list,&backing,data_rows,source_data?size_t(1):0,size_t(1)};return true;}
bool mp4_proflare_existing_current(void*,const Mp4ProFlareDataImage&i){return i.object==&data&&mp4_proflare_registry_scope.active();}
bool mp4_proflare_data_capture(Mp4ProFlareDataImage&i,void*d,void*b,void*c,bool(*current)(void*,const Mp4ProFlareDataImage&),void*ctx,size_t){assert(d==&data&&b==&batch&&c==mp4_stage_host.source.camera);i.object=d;i.captured=true;return current(ctx,i);}
bool mp4_proflare_pass_configure(const Mp4SceneWitness&){++pass_calls;return pass_ok;}

#include "coordinator-types.inc"

bool physical=true,scalar_current=true,sub_current=true;
bool mp4_proflare_physical(void*b,uint64_t*out){*out=physical?13:0;return physical&&b==&batch;}
bool mp4_proflare_scalar_current(const Mp4ProFlareScalarImage&i){return i.captured&&scalar_current;}
bool mp4_proflare_sub_current(const Mp4ProFlareSubImage&){return sub_current;}

#include "coordinator-empty-lease.inc"

void reset(){static Mp4ProFlareCoordinator h;h={};mp4_proflare_coordinator=&h;h.serial=13;h.prepared=true;h.batch=&batch;h.count=1;h.source=mp4_stage_host.source;h.flares[0].scalar.captured=true;static Mp4ProFlareOwnedElement e;e.scalar.captured=true;h.flares[0].elements=&e;h.flares[0].count=1;physical=scalar_current=sub_current=valid=true;mp4_proflare_registry_scope.captured=true;source_data=false;data_rows[0]=&data;}
int main(){unsigned cases=0;reset();uint64_t r=0;assert(mp4_proflare_empty_data_lease(&batch,mp4_stage_host.source.camera,&r)&&r==13);++cases;
 for(int bad=0;bad<10;++bad){reset();if(bad==0)physical=false;if(bad==1)scalar_current=false;if(bad==2)sub_current=false;if(bad==3)valid=false;if(bad==4)mp4_proflare_registry_scope.captured=false;if(bad==5)mp4_proflare_coordinator->prepared=false;if(bad==6)mp4_proflare_coordinator->existing.object=&data;if(bad==7)source_data=true;if(bad==8)mp4_proflare_coordinator->flares[0].scalar.captured=false;if(bad==9)mp4_proflare_coordinator=nullptr;r=99;assert(!mp4_proflare_empty_data_lease(&batch,mp4_stage_host.source.camera,&r)&&!r);++cases;}
 reset();r=99;assert(!mp4_proflare_empty_data_lease(&data,mp4_stage_host.source.camera,&r)&&!r);assert(!mp4_proflare_empty_data_lease(&batch,&data,&r)&&!r);assert(!mp4_proflare_empty_data_lease(&batch,mp4_stage_host.source.camera,nullptr));++cases;
 std::printf("%u actual PF pre-first-Data captured-image lease cases passed\n",cases);}
