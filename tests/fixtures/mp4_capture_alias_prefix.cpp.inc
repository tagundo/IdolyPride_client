#include <cassert>
#include <cstdint>
#include <cstddef>
#include <cstring>
#include <cstdio>
#include <map>
#include <string>
#include <stdexcept>
#include <atomic>
#include <thread>
// @QUEUE_JOURNAL@
// @QUEUE_GATE@
using std::strcmp;
static uintptr_t image_base=0;
static thread_local bool on_thread=true;
static bool source_current=true,prefix_current=true,allocation_current=true,allocation_queued=true,maps_current=true;
static unsigned forbidden_controller_reads=0,source_reads=0;
static int controller_reads=0,retains=0,release_count=0,fail_root=0;

struct Object{const char*type;uintptr_t native;void*field32=nullptr;void*field168=nullptr;int id=401;bool alive=true;};
struct HashSet{const char*type="HashSet`1";int32_t count=0,last=0,version=0;idoly_mp4_capture_queue::Target target{};};
static Object component{"VL.Rendering.VLSRPCapture",201},controller{"VL.Rendering.VLSRPCameraController",200},wrapper{"VL.VLRenderTexture",300},texture{"UnityEngine.RenderTexture",401};
static HashSet set;
static Object renderer{"VL.Rendering.VLSRPRenderer",301},queue{"List",0};
struct Mp4SceneWitness{uint64_t generation=0;void*controller=nullptr;};
static std::map<uint32_t,void*> roots;
static uint32_t root_next=0;
static bool game_call(){return on_thread;}
static bool mp4_exact_type(void*p,const char*n){return p&&strcmp(static_cast<Object*>(p)->type,n)==0;}
static bool mp4_alive(void*p){return p&&static_cast<Object*>(p)->alive;}
static void*weak_get(uint32_t n){auto i=roots.find(n);return i==roots.end()?nullptr:i->second;}
static void weak_free(uint32_t n){assert(roots.erase(n)==1);++release_count;}
static uint32_t mp4_retain(void*p){++retains;auto n=++root_next;if(retains==fail_root)return 0;roots[n]=p;return n;}
static bool mp4_actor_refresh_maps(){return maps_current;}
static bool mp4_actor_mapped(void*p,size_t,bool){return p!=nullptr;}
template<class T>static bool mp4_actor_field(void*p,size_t at,T&out){
 if(p==&controller){if(!source_current)++forbidden_controller_reads;if(at==168)++controller_reads;}
 if(p==&set){int32_t v;if(at==16)v=set.count;else if(at==20)v=set.last;else if(at==24)v=set.version;else return false;
  if(sizeof(T)!=4)return false;
  memcpy(&out,&v,4);return true;}
 auto*o=static_cast<Object*>(p);if(!o)return false;
 if(p==&wrapper&&at==16&&sizeof(T)==sizeof(void*)){void*v=&texture;memcpy(&out,&v,sizeof(out));return true;}
 if(p==&renderer&&at==48&&sizeof(T)==sizeof(void*)){void*v=&queue;memcpy(&out,&v,sizeof(out));return true;}
 if(at==16&&sizeof(T)==sizeof(uintptr_t)){memcpy(&out,&o->native,sizeof(out));return true;}
 void*v=at==32?o->field32:at==168?o->field168:nullptr;
 if((at==32||at==168)&&sizeof(T)==sizeof(void*)){memcpy(&out,&v,sizeof(out));return true;}return false;
}
static void*object_class(void*p){return p;}
static const char*class_name(void*p){return p==&set?"HashSet`1":nullptr;}
static const char*class_namespace(void*p){return p==&set?"System.Collections.Generic":nullptr;}
static bool mp4_renderer_capture_i32_field(void*p,const char*n,size_t&at){if(p!=&set)return false;at=strcmp(n,"_count")==0?16:strcmp(n,"_lastIndex")==0?20:strcmp(n,"_version")==0?24:0;return at!=0;}
struct alignas(8) Mp4CaptureTarget40{uint8_t bytes[40]{};};
static bool mp4_renderer_capture_set_idle(void*p){return p==&component&&(!component.field32||(set.count==0&&set.last==0));}
static bool single_owned=true;
static bool mp4_renderer_capture_request_set_owned(void*p,const Mp4CaptureTarget40&t){idoly_mp4_capture_queue::Target v{};memcpy(v.bytes,t.bytes,40);return p==&component&&single_owned&&set.count==1&&idoly_mp4_capture_queue::same(v,set.target);}
namespace mp4game{struct Binding{uintptr_t rva;uint8_t prefix[16];};}
// @QUEUE_PINS@

static void target_callout();
static void target_ctor(Mp4CaptureTarget40*out,void*p,const void*){memcpy(out->bytes,&static_cast<Object*>(p)->id,4);target_callout();}
static struct{mp4game::Binding target_ctor{reinterpret_cast<uintptr_t>(::target_ctor),{}};}mp4_capture_owned_pins;
static bool mp4_prefix(const mp4game::Binding&){return prefix_current;}
using Method=void;
namespace mp4production{struct Resource{uint64_t epoch=9,job=17;void*wrapper=::std::addressof(::wrapper),*texture=::std::addressof(::texture);uintptr_t native=401;bool wrapper_returned=true,texture_returned=true,native_known=true;};}
struct Bank{mp4production::Resource r{};bool has=true,cursor=true;uint32_t count()const{return 1;}bool historical(uint32_t i,mp4production::Resource*out)const{if(i||!has)return false;*out=r;return true;}bool publication_origin(void*p,uint64_t s)const{return cursor&&p==&controller&&s==9;}};
struct Mp4CaptureProductionHost{Bank bank{};Mp4SceneWitness source{9,&::controller};uint64_t job=17;bool configured=true;};
static Mp4CaptureProductionHost production;
static Mp4CaptureProductionHost*mp4_capture_production_published=&production;
static uint64_t issued_serial=9;
static uint64_t mp4_capture_production_request(void*p){return production.configured&&p==&controller?issued_serial:0;}
static bool mp4_capture_production_assignment_current(void*,uint64_t,uint64_t){++source_reads;return source_current;}

// @QUEUE_HOST@

static Mp4CaptureQueueHost producer;
static bool mp4_source_verified=true,mp4_actor_source_verified=true;
static bool source_available=true,queue_empty=true,queue_stable=true;
static bool consumer_receipt=true,detached_receipt=true,complete_birth=true;
static bool unwound=true,retired=true,produced=true,do_throw=false,reenter=false,inject_after=false,ctor_withdraw=false;
static bool callback_reentry=false,consumer_add=false,foreign_during_remove=false;
static int remove_calls=0,reentry_denied=0;static void*alias_context=nullptr;
static bool callback_reentry_test();
struct Mp4OriginalRendererSource{Mp4SceneWitness scene{};void*renderer=nullptr;};
static bool mp4_original_renderer_source_detail(Mp4OriginalRendererSource&o){if(!source_available)return false;o={{9,&controller},&renderer};return true;}
static bool mp4_scene_same_source(const Mp4SceneWitness&a,const Mp4SceneWitness&b){return a.generation==b.generation&&a.controller==b.controller;}
static bool mp4_renderer_srp_field(void*p,const char*n,size_t at,bool statik,void*&field){field=p;return p==&renderer&&!strcmp(n,"m_ActiveRenderPassQueue")&&at==48&&!statik;}
static bool mp4_renderer_srp_list(void*p,void**&items,size_t&n,void*&array,uint32_t&v,size_t){items=nullptr;array=p;v=7;n=queue_empty?0:1;return p==&queue;}
static bool mp4_renderer_srp_list_same(void*p,void*array,uint32_t v,void*const*,size_t n,size_t){return queue_stable&&p==&queue&&array==p&&v==7&&n==0&&queue_empty;}
static bool remove_original(void*,const Mp4CaptureTarget40*,const Method*);
#define mp4_capture_alias_pins actual_capture_alias_pins
// @ALIAS_PINS@
#undef mp4_capture_alias_pins
static auto mp4_capture_alias_pins=[](){auto p=actual_capture_alias_pins;p.remove.rva=reinterpret_cast<uintptr_t>(remove_original);return p;}();
static idoly_mp4_capture_queue::Target target(){idoly_mp4_capture_queue::Target value{};memcpy(value.bytes,&texture.id,4);return value;}
static void add_original(){component.field32=&set;if(!set.count){set.count=set.last=1;++set.version;set.target=target();}}
static void actual_add(bool owned){Mp4CaptureQueueAdd lease;assert(mp4_capture_queue_add_enter(lease,&component));idoly_mp4_capture_queue::Journal::Add call(producer.journal,&component,target(),1010,owned?mp4_capture_queue_pins.update_add:999);add_original();call.finish(true);}
static void clear_set(){set.count=set.last=0;++set.version;}
static bool query_unwound(void*,uint64_t e,uint64_t j){assert(!producer.gate.cancel_on_thread());if(callback_reentry){callback_reentry=false;assert(callback_reentry_test());}return e==9&&j==17&&unwound;}
static bool query_retired(void*,uint64_t e,uint64_t j){assert(!producer.gate.cancel_on_thread());return e==9&&j==17&&retired;}
static bool query_produced(void*,uint64_t e,uint64_t j,void*w,void*t,uintptr_t n,bool*can_queue){assert(!producer.gate.cancel_on_thread());*can_queue=complete_birth;return e==9&&j==17&&produced&&w==&wrapper&&t==&texture&&n==401;}
static bool query_detached(void*,uint64_t e,uint64_t j,void*w,void*t,uintptr_t n){assert(!producer.gate.cancel_on_thread());return e==9&&j==17&&w==&wrapper&&t==&texture&&n==401&&detached_receipt;}
static bool query_consumers(void*,uint64_t e,uint64_t j,void*w,void*t,uintptr_t n){assert(!producer.gate.cancel_on_thread());if(consumer_add){consumer_add=false;actual_add(false);}return e==9&&j==17&&w==&wrapper&&t==&texture&&n==401&&consumer_receipt;}
