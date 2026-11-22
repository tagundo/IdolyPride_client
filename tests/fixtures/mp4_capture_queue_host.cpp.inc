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
static thread_local bool owner_thread=true;
static bool throw_target=false,throw_allocation=false,throw_maps=false;
static bool source_current=true,prefix_current=true,allocation_current=true,allocation_queued=true,maps_current=true;
static unsigned forbidden_controller_reads=0,source_reads=0;
struct Object{const char*type;uintptr_t native;void*field32=nullptr;void*field168=nullptr;int id=401;bool alive=true;};
struct HashSet{const char*type="HashSet`1";int32_t count=0,last=0,version=0;idoly_mp4_capture_queue::Target target{};};
static Object component{"VL.Rendering.VLSRPCapture",100},controller{"VL.Rendering.VLSRPCameraController",200},wrapper{"VL.VLRenderTexture",300},texture{"UnityEngine.RenderTexture",400};
static HashSet set;
static std::map<uint32_t,void*> roots;
static uint32_t root_next=0;
static bool game_call(){return owner_thread;}
static bool mp4_exact_type(void*p,const char*n){return p&&strcmp(static_cast<Object*>(p)->type,n)==0;}
static bool mp4_alive(void*p){return p&&static_cast<Object*>(p)->alive;}
static void*weak_get(uint32_t n){auto i=roots.find(n);return i==roots.end()?nullptr:i->second;}
static void weak_free(uint32_t n){roots.erase(n);}
static uint32_t mp4_retain(void*p){auto n=++root_next;roots[n]=p;return n;}
static bool mp4_actor_refresh_maps(){if(throw_maps)throw std::runtime_error("maps");return maps_current;}
static bool mp4_actor_mapped(void*p,size_t,bool){return p!=nullptr;}
template<class T>static bool mp4_actor_field(void*p,size_t at,T&out){
 if(p==&controller&&!source_current)++forbidden_controller_reads;
 if(p==&set){int32_t v;if(at==16)v=set.count;else if(at==20)v=set.last;else if(at==24)v=set.version;else return false;
  if(sizeof(T)!=4)return false;
  memcpy(&out,&v,4);return true;}
 auto*o=static_cast<Object*>(p);if(!o)return false;
 if(at==16&&sizeof(T)==sizeof(uintptr_t)){memcpy(&out,&o->native,sizeof(out));return true;}
 void*v=at==32?o->field32:at==168?o->field168:nullptr;
 if((at==32||at==168)&&sizeof(T)==sizeof(void*)){memcpy(&out,&v,sizeof(out));return true;}return false;
}
static void*object_class(void*p){return p==&set?static_cast<void*>(&set):nullptr;}
static const char*class_name(void*p){return p==&set?"HashSet`1":nullptr;}
static const char*class_namespace(void*p){return p==&set?"System.Collections.Generic":nullptr;}
static bool mp4_renderer_capture_i32_field(void*p,const char*n,size_t&at){if(p!=&set)return false;at=strcmp(n,"_count")==0?16:strcmp(n,"_lastIndex")==0?20:strcmp(n,"_version")==0?24:0;return at!=0;}
struct alignas(8) Mp4CaptureTarget40{uint8_t bytes[40]{};};
static bool mp4_renderer_capture_set_idle(void*p){return p==&component&&(!component.field32||(set.count==0&&set.last==0));}
static bool mp4_renderer_capture_request_set_owned(void*p,const Mp4CaptureTarget40&t){idoly_mp4_capture_queue::Target v{};memcpy(v.bytes,t.bytes,40);return p==&component&&set.count==1&&idoly_mp4_capture_queue::same(v,set.target);}
namespace mp4game{struct Binding{uintptr_t rva;uint8_t prefix[16];};}
// @QUEUE_PINS@

static void target_ctor(Mp4CaptureTarget40*out,void*p,const void*){if(throw_target)throw std::runtime_error("target_ctor");memcpy(out->bytes,&static_cast<Object*>(p)->id,4);}
static struct{mp4game::Binding target_ctor{reinterpret_cast<uintptr_t>(::target_ctor),{}};}mp4_capture_owned_pins;
static bool mp4_prefix(const mp4game::Binding&){return prefix_current;}
using Method=void;
namespace mp4production{struct Resource{uint64_t epoch=5,job=6;void*wrapper=::std::addressof(::wrapper),*texture=::std::addressof(::texture);uintptr_t native=400;bool wrapper_returned=true,texture_returned=true,native_known=true;};}
struct Bank{mp4production::Resource r{};bool has=true,cursor=true;uint32_t count()const{return 1;}bool historical(uint32_t i,mp4production::Resource*out)const{if(i||!has)return false;*out=r;return true;}bool publication_origin(void*p,uint64_t s)const{return cursor&&p==&controller&&s==9;}};
struct Mp4CaptureProductionHost{Bank bank{};struct{uint64_t generation=5;void*controller=&::controller;}source;uint64_t job=6;bool configured=true;};
static Mp4CaptureProductionHost production;
static Mp4CaptureProductionHost*mp4_capture_production_published=&production;
static uint64_t issued_serial=9;
static uint64_t mp4_capture_production_request(void*p){return production.configured&&p==&controller?issued_serial:0;}
static bool mp4_capture_production_assignment_current(void*,uint64_t,uint64_t){++source_reads;return source_current;}
// @QUEUE_HOST@
static bool allocation(void*,uint64_t e,uint64_t j,void*w,void*t,uintptr_t n,bool*q){if(throw_allocation)throw std::runtime_error("allocation");*q=allocation_queued;return allocation_current&&e==5&&j==6&&w==&wrapper&&t==&texture&&n==400;}
static void reset(){assert(roots.empty()&&!mp4_capture_queue_retiring&&!mp4_capture_queue_readers&&!mp4_capture_queue_published);owner_thread=source_current=prefix_current=allocation_current=allocation_queued=maps_current=true;
 throw_target=throw_allocation=throw_maps=false;
 component={"VL.Rendering.VLSRPCapture",100};controller={"VL.Rendering.VLSRPCameraController",200};wrapper={"VL.VLRenderTexture",300};texture={"UnityEngine.RenderTexture",400};
 controller.field168=&component;set=HashSet{};production=Mp4CaptureProductionHost{};mp4_capture_production_published=&production;issued_serial=9;source_reads=forbidden_controller_reads=0;
}
static idoly_mp4_capture_queue::Target t(){idoly_mp4_capture_queue::Target v{};memcpy(v.bytes,&texture.id,4);return v;}
static bool bind(Mp4CaptureQueueHost&h){return mp4_capture_queue_bind(h,production,&production,allocation,true);}
static void add_original(){component.field32=&set;if(!set.count){set.count=set.last=1;++set.version;set.target=t();}}
static bool add(Mp4CaptureQueueHost&h,uintptr_t lr=0){if(!lr)lr=mp4_capture_queue_pins.update_add;auto value=t();Mp4CaptureQueueAdd gate;assert(mp4_capture_queue_add_enter(gate,&component));idoly_mp4_capture_queue::Journal::Add call(h.journal,&component,value,1010,lr);add_original();return call.finish(true);}
static bool pending(Mp4CaptureQueueHost&h){Mp4CaptureTarget40 expected{};target_ctor(&expected,&texture,nullptr);return mp4_capture_queue_pending(&h,5,6,&component,expected);}
static void finish(Mp4CaptureQueueHost&h){assert(mp4_capture_queue_finish(h));assert(roots.empty());}
int main(){unsigned cases=0;
 {reset();Mp4CaptureQueueHost h;assert(bind(h));assert(add(h)&&pending(h));finish(h);++cases;}
 {reset();component.field32=&set;Mp4CaptureQueueHost h;assert(bind(h));assert(add(h)&&pending(h));finish(h);++cases;}
 {reset();Mp4CaptureQueueHost h;assert(bind(h));assert(add(h));assert(!add(h,999)&&!pending(h));finish(h);++cases;}
 {reset();Mp4CaptureQueueHost h;assert(bind(h));assert(add(h));source_current=false;unsigned before=source_reads;assert(pending(h));assert(source_reads==before&&!forbidden_controller_reads);finish(h);++cases;}
 {reset();Mp4CaptureQueueHost h;assert(bind(h));assert(add(h));production.bank.has=false;assert(pending(h));finish(h);++cases;}
 {reset();Mp4CaptureQueueHost h;assert(bind(h));production.bank.r.wrapper_returned=false;assert(!add(h)&&!pending(h));finish(h);++cases;}
 {reset();Mp4CaptureQueueHost h;assert(bind(h));production.bank.r.texture_returned=false;assert(!add(h)&&!pending(h));finish(h);++cases;}
 {reset();Mp4CaptureQueueHost h;assert(bind(h));allocation_queued=false;assert(!add(h)&&!pending(h));finish(h);++cases;}
 {reset();Mp4CaptureQueueHost h;assert(bind(h));assert(add(h));allocation_current=false;assert(!pending(h));finish(h);++cases;}
 {reset();Mp4CaptureQueueHost h;assert(bind(h));issued_serial=0;assert(!add(h)&&!pending(h));finish(h);++cases;}
 {reset();Mp4CaptureQueueHost h;assert(bind(h));production.bank.cursor=false;assert(!add(h)&&!pending(h));finish(h);++cases;}
 {reset();Mp4CaptureQueueHost h;assert(bind(h));{idoly_mp4_capture_queue::Journal::Capture c(h.journal,&controller,t(),1010,mp4_capture_queue_pins.request_capture);assert(add(h,mp4_capture_queue_pins.capture_add));}assert(pending(h));finish(h);++cases;}
 {reset();Mp4CaptureQueueHost h;assert(bind(h));{idoly_mp4_capture_queue::Journal::Capture c(h.journal,&controller,t(),1010,999);assert(!add(h,mp4_capture_queue_pins.capture_add));}assert(!pending(h));finish(h);++cases;}
 {reset();Mp4CaptureQueueHost h;assert(bind(h));assert(add(h));component.native=101;assert(!pending(h));component.native=100;finish(h);++cases;}
 {reset();Mp4CaptureQueueHost h;assert(bind(h));assert(add(h));roots[h.root]=&controller;assert(!pending(h));finish(h);++cases;}
 {reset();Mp4CaptureQueueHost h;assert(bind(h));assert(add(h));set.target.bytes[0]^=1;assert(!pending(h));finish(h);++cases;}
 {reset();Mp4CaptureQueueHost h;assert(bind(h));assert(add(h));set.count=2;assert(!pending(h));finish(h);++cases;}
 {reset();source_current=false;Mp4CaptureQueueHost h;assert(!bind(h)&&roots.empty());++cases;}
 {reset();add_original();Mp4CaptureQueueHost h;assert(!bind(h)&&roots.empty());++cases;}
 {reset();Mp4CaptureQueueHost h;assert(!mp4_capture_queue_bind(h,production,&production,allocation,false)&&roots.empty());++cases;}
 {reset();Mp4CaptureQueueHost h;assert(bind(h));assert(add(h));prefix_current=false;assert(!pending(h));finish(h);++cases;}
 {reset();Mp4CaptureQueueHost h;assert(bind(h));assert(add(h));mp4_capture_queue_foreign();assert(!pending(h));finish(h);++cases;}
 {reset();Mp4CaptureQueueHost h;assert(bind(h));assert(add(h));{Mp4CaptureTarget40 expected{};target_ctor(&expected,&texture,nullptr);Mp4CaptureQueueCancel c;assert(mp4_capture_queue_cancel_begin(&h,c,5,6,&component,expected)&&c.current());set.count=set.last=0;++set.version;assert(c.current()&&mp4_renderer_capture_set_idle(&component));}finish(h);++cases;}
 {reset();Mp4CaptureQueueHost h;assert(bind(h));assert(add(h));{Mp4CaptureQueueAdd hold;assert(mp4_capture_queue_add_enter(hold,&component));Mp4CaptureTarget40 expected{};target_ctor(&expected,&texture,nullptr);Mp4CaptureQueueCancel c;assert(!mp4_capture_queue_cancel_begin(&h,c,5,6,&component,expected));assert(set.count==1);}finish(h);++cases;}
 {reset();Mp4CaptureQueueHost h;assert(bind(h));assert(add(h));{Mp4CaptureTarget40 expected{};target_ctor(&expected,&texture,nullptr);Mp4CaptureQueueCancel c;assert(mp4_capture_queue_cancel_begin(&h,c,5,6,&component,expected));assert(!add(h,999));assert(!c.current()&&set.count==1);}finish(h);++cases;}
 {reset();Mp4CaptureQueueHost h;assert(bind(h));assert(add(h));std::atomic<bool>started{false},entered{false};std::thread worker;
  {Mp4CaptureTarget40 expected{};target_ctor(&expected,&texture,nullptr);Mp4CaptureQueueCancel c;assert(mp4_capture_queue_cancel_begin(&h,c,5,6,&component,expected));
   worker=std::thread([&](){owner_thread=false;started.store(true);Mp4CaptureQueueAdd hold;assert(mp4_capture_queue_add_enter(hold,&component));entered.store(true);add_original();});
   while(!started.load()||!h.journal.withdrawn())std::this_thread::yield();
   assert(!entered.load()&&!c.current());/* cleanup aborts; native duty remains */}
  worker.join();assert(entered.load()&&set.count==1);finish(h);++cases;}
 {reset();Mp4CaptureQueueHost h;assert(bind(h));assert(add(h));std::atomic<bool>started{false},entered{false};std::thread worker;
  {Mp4CaptureTarget40 expected{};target_ctor(&expected,&texture,nullptr);Mp4CaptureQueueCancel c;assert(mp4_capture_queue_cancel_begin(&h,c,5,6,&component,expected));
   /* exact original Remove's CPU mutation, with no authored callbacks */set.count=set.last=0;++set.version;
   worker=std::thread([&](){owner_thread=false;started.store(true);Mp4CaptureQueueAdd hold;assert(mp4_capture_queue_add_enter(hold,&component));entered.store(true);add_original();});
   while(!started.load()||!h.journal.withdrawn())std::this_thread::yield();
   assert(!entered.load()&&!c.current()&&set.count==0);/* cannot dispose native */}
  worker.join();assert(entered.load()&&set.count==1);finish(h);++cases;}
 {reset();Mp4CaptureQueueHost h;assert(bind(h));assert(add(h));maps_current=false;assert(!pending(h));finish(h);++cases;}
 {reset();Mp4CaptureQueueHost h;assert(bind(h));Mp4CaptureQueueReader reader;assert(reader.begin());uint32_t root=h.root;assert(!mp4_capture_queue_finish(h));assert(h.bound&&h.root==root&&weak_get(root)==&component&&mp4_capture_queue_retiring==&h);assert(reader.published()==nullptr);Mp4CaptureQueueHost next;assert(!bind(next));reader.leave();finish(h);++cases;}
 {reset();Mp4CaptureQueueHost h;assert(bind(h));Mp4CaptureQueueReader reader;assert(reader.begin()&&reader.published()==&h);assert(!mp4_capture_queue_finish(h));assert(reader.published()==&h&&h.epoch==5&&h.job==6&&h.component==&component);assert(!bind(h));reader.leave();finish(h);production.job=7;assert(bind(h)&&h.job==7&&!pending(h));finish(h);++cases;}
 {reset();Mp4CaptureQueueHost h;assert(bind(h));{Mp4CaptureQueueAdd lease;assert(mp4_capture_queue_add_enter(lease,&component));assert(!mp4_capture_queue_finish(h)&&h.bound&&h.root);add_original();}finish(h);++cases;}
 {reset();Mp4CaptureQueueReader reader;assert(reader.begin()&&reader.published()==nullptr);Mp4CaptureQueueHost h;assert(!bind(h));reader.leave();assert(bind(h));finish(h);++cases;}
 {reset();Mp4CaptureQueueHost h;assert(bind(h));Mp4CaptureQueueReader reader;assert(reader.begin());assert(add(h));Mp4CaptureTarget40 expected{};target_ctor(&expected,&texture,nullptr);Mp4CaptureQueueCancel c;assert(!mp4_capture_queue_cancel_begin(&h,c,5,6,&component,expected));reader.leave();finish(h);++cases;}
 {reset();Mp4CaptureQueueHost h;assert(bind(h));std::atomic<bool>begun{false},load{false};std::thread worker([&](){owner_thread=false;Mp4CaptureQueueReader reader;assert(reader.begin());begun.store(true);while(!load.load())std::this_thread::yield();assert(reader.published()==nullptr);});
  while(!begun.load())std::this_thread::yield();
  uint32_t root=h.root;assert(!mp4_capture_queue_finish(h)&&h.bound&&h.root==root);Mp4CaptureQueueHost next;assert(!bind(next));load.store(true);worker.join();finish(h);++cases;}
 {reset();Mp4CaptureQueueHost h;assert(bind(h));std::atomic<bool>loaded{false},release{false};std::thread worker([&](){owner_thread=false;Mp4CaptureQueueReader reader;assert(reader.begin());auto*old=reader.published();assert(old==&h);loaded.store(true);while(!release.load())std::this_thread::yield();assert(old->bound&&old->epoch==5&&old->job==6&&old->component==&component);});
  while(!loaded.load())std::this_thread::yield();
  assert(!mp4_capture_queue_finish(h));Mp4CaptureQueueHost next;assert(!bind(next)&&roots.size()==1);release.store(true);worker.join();finish(h);++cases;}
 {reset();Mp4CaptureQueueHost h;assert(bind(h));throw_target=true;assert(!add(h)&&set.count==1&&h.journal.withdrawn());finish(h);++cases;}
 {reset();Mp4CaptureQueueHost h;assert(bind(h));throw_allocation=true;assert(!add(h)&&set.count==1&&h.journal.withdrawn());finish(h);++cases;}
 {reset();Mp4CaptureQueueHost h;assert(bind(h));throw_maps=true;assert(!add(h)&&set.count==1&&h.journal.withdrawn());finish(h);++cases;}
 {reset();Mp4CaptureQueueHost h;assert(bind(h));try{Mp4CaptureQueueAdd lease;assert(mp4_capture_queue_add_enter(lease,&component));idoly_mp4_capture_queue::Journal::Add call(h.journal,&component,t(),1010,mp4_capture_queue_pins.update_add);add_original();throw_target=true;throw std::logic_error("original_body");}catch(const std::logic_error&e){assert(std::string(e.what())=="original_body");}assert(set.count==1&&h.journal.withdrawn()&&mp4_capture_queue_readers==0);finish(h);++cases;}
 printf("%u concrete queue host cases passed\n",cases);
}
