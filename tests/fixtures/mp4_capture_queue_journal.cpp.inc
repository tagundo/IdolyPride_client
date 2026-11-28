#include <cassert>
#include <cstdint>
#include <cstddef>
#include <cstring>
#include <cstdio>
#include <thread>
#include <stdexcept>
#include <type_traits>
#include <utility>
// @QUEUE_JOURNAL@
using namespace idoly_mp4_capture_queue;
static bool main_thread=true,throw_thread=false;
static_assert(std::is_nothrow_constructible<Journal::Capture,Journal&,void*,const Target&,int32_t,uintptr_t>::value);
static_assert(std::is_nothrow_constructible<Journal::Add,Journal&,void*,const Target&,int32_t,uintptr_t>::value);
static_assert(std::is_nothrow_destructible<Journal::Capture>::value&&std::is_nothrow_destructible<Journal::Add>::value);
static_assert(noexcept(std::declval<Journal::Add&>().finish(false)));
static void*const component=reinterpret_cast<void*>(0x1000),*const other=reinterpret_cast<void*>(0x2000),*const controller=reinterpret_cast<void*>(0x3000);
static Target target(uint32_t n=401){Target t{};memcpy(t.bytes,&n,4);return t;}
struct F {
 Journal j{};Set set{};Target held{};uint64_t serial=9;bool rooted=true,request=true,update=true,resource=true,read=true,source=true;
 unsigned calls=0,reads=0,former_reads=0;bool foreign_in_read=false,throw_origin=false,throw_resource=false,throw_read=false,throw_retained=false,throw_update=false;
 static bool thread(){if(throw_thread)throw std::runtime_error("thread");return main_thread;}
 static bool retained(void*c,void*which,uint64_t epoch,uint64_t job){auto&f=*static_cast<F*>(c);if(f.throw_retained)throw std::runtime_error("retained");return f.rooted&&which==component&&epoch==5&&job==6;}
 static bool origin(void*c,void*which,uint64_t*out){auto&f=*static_cast<F*>(c);if(f.throw_origin)throw std::runtime_error("origin");if(!f.request||which!=controller)return false;*out=f.serial;return true;}
 static bool update_origin(void*c,void*which,Origin*out){auto&f=*static_cast<F*>(c);if(f.throw_update)throw std::runtime_error("update");if(!f.update||which!=component)return false;*out={controller,nullptr,nullptr,0,f.serial};return true;}
 static bool birth(void*c,Origin*out,const Target&t){auto&f=*static_cast<F*>(c);if(f.throw_resource)throw std::runtime_error("resource");if(!f.resource||out->controller!=controller||out->serial!=f.serial||!same(t,target()))return false;
  if(out->wrapper&&out->wrapper!=reinterpret_cast<void*>(0x4000))return false;
  if(out->texture&&out->texture!=reinterpret_cast<void*>(0x5000))return false;
  if(out->native&&out->native!=0x6000)return false;
  out->wrapper=reinterpret_cast<void*>(0x4000);out->texture=reinterpret_cast<void*>(0x5000);out->native=0x6000;return true;}
 static bool observe(void*c,void*which,const Target&t,Set*out){auto&f=*static_cast<F*>(c);++f.reads;if(f.throw_read)throw std::runtime_error("read");if(f.foreign_in_read){f.foreign_in_read=false;f.j.foreign();}
  if(!f.read||which!=component)return false;
  *out=f.set;out->exact=f.set.count==1&&same(t,f.held);return true;}
 bool bind(){return j.bind({thread,retained,origin,update_origin,birth,observe},this,component,5,6,{11,22,33});}
 void add(const Target&t=target(),void*which=component){++calls;if(which!=component)return;if(!set.object)set.object=reinterpret_cast<void*>(0x7000);
  if(!set.count){held=t;set.count=1;set.last=1;++set.version;}else if(!same(held,t)){++set.count;++set.last;++set.version;}}
 bool call(uintptr_t lr=11,const Target&t=target(),int event=1010,void*which=component,bool throws=false){Journal::Add a(j,which,t,event,lr);add(t,which);if(throws)throw std::runtime_error("after_add");return a.finish(true);}
 bool pending(const Target&t=target()){return j.pending(component,5,6,t);}
 void clear(){set.count=set.last=0;++set.version;}
};
int main(){unsigned cases=0;
 {F f;assert(f.bind());assert(!f.pending());++cases;}
 {F f;assert(f.bind());assert(f.call());assert(f.pending());assert(f.calls==1&&f.j.receipt().request==9&&f.j.receipt().returned);++cases;}
 {F f;assert(f.bind());assert(f.call());assert(f.call());assert(f.pending());assert(f.calls==2&&f.set.count==1&&f.j.receipt().mutation==2);++cases;}
 {F f;assert(f.bind());assert(f.call());auto old=f.j.receipt();assert(!f.call(99));assert(f.calls==2&&!f.pending()&&f.j.withdrawn());assert(f.set.version==old.set.version);++cases;}
 {F f;assert(f.bind());assert(f.call());assert(!f.call(11,target(),1009));assert(f.calls==2&&!f.pending());++cases;}
 {F f;assert(f.bind());assert(!f.call(11,target(999)));assert(f.calls==1&&!f.pending());++cases;}
 {F f;assert(f.bind());assert(f.call());f.call(99,target(),1010,other);assert(f.calls==2&&f.pending());++cases;}
 {F f;f.add();assert(!f.bind());++cases;}
 {F f;f.rooted=false;assert(!f.bind());++cases;}
 {F f;assert(f.bind());f.request=false;assert(!f.call());assert(f.calls==1&&!f.pending());++cases;}
 {F f;assert(f.bind());f.update=false;assert(!f.call());assert(f.calls==1&&!f.pending());++cases;}
 {F f;assert(f.bind());f.resource=false;assert(!f.call());assert(f.calls==1&&!f.pending());++cases;}
 {F f;assert(f.bind());f.read=false;assert(!f.call());assert(f.calls==1&&!f.pending());++cases;}
 {F f;assert(f.bind());{Journal::Add a(f.j,component,target(),1010,11);f.add();assert(!f.pending());assert(!f.j.finish());assert(a.finish(true));}assert(f.pending()&&f.j.finish());++cases;}
 {F f;assert(f.bind());{Journal::Capture c(f.j,controller,target(),1010,33);assert(f.call(22));assert(!f.j.finish());}assert(f.pending()&&f.j.finish());++cases;}
 {F f;assert(f.bind());{Journal::Capture c(f.j,controller,target(),1010,99);assert(!f.call(22));}assert(f.calls==1&&!f.pending());++cases;}
 {F f;assert(f.bind());{Journal::Capture outer(f.j,controller,target(),1010,33);{Journal::Capture inner(f.j,controller,target(),1010,99);assert(!f.call(22));}}assert(f.calls==1&&!f.pending());++cases;}
 {F f;assert(f.bind());{Journal::Capture outer(f.j,controller,target(),1010,33);{Journal::Capture inner(f.j,controller,target(),1010,33);assert(!f.call(22));}}assert(f.calls==1&&!f.pending());++cases;}
 {F f;assert(f.bind());{Journal::Capture c(f.j,controller,target(),1010,33);assert(!f.call(22,target(999)));}assert(f.calls==1&&!f.pending());++cases;}
 {F f;assert(f.bind());{Journal::Capture c(f.j,controller,target(),1010,33);f.request=false;/* cached typed scope still denotes actual issued body */assert(f.call(22));}assert(f.pending());++cases;}
 {F f;assert(f.bind());{Journal::Add outer(f.j,component,target(),1010,11);assert(!f.call());f.add();assert(!outer.finish(true));}assert(f.calls==2&&!f.pending());++cases;}
 {F f;assert(f.bind());try{f.call(11,target(),1010,component,true);assert(false);}catch(const std::runtime_error&){}assert(f.calls==1&&f.pending()&&!f.j.receipt().returned);++cases;}
 {F f;assert(f.bind());{Journal::Add a(f.j,component,target(),1010,11);assert(a.finish(false));}assert(!f.pending()&&!f.j.withdrawn());++cases;}
 {F f;assert(f.bind());assert(f.call());f.rooted=false;assert(!f.pending());++cases;}
 {F f;assert(f.bind());assert(f.call());f.resource=false;assert(!f.pending());++cases;}
 {F f;assert(f.bind());assert(f.call());f.clear();assert(!f.pending());assert(f.call());assert(f.pending());++cases;}
 {F f;assert(f.bind());assert(f.call());f.clear();f.call(99);assert(!f.pending());++cases;}
 {F f;assert(f.bind());assert(f.call());f.set.object=other;assert(!f.pending());++cases;}
 {F f;assert(f.bind());assert(f.call());++f.set.version;assert(!f.pending());++cases;}
 {F f;assert(f.bind());assert(f.call());++f.set.last;assert(!f.pending());++cases;}
 {F f;assert(f.bind());assert(f.call());f.set.count=2;assert(!f.pending());++cases;}
 {F f;assert(f.bind());assert(f.call());f.source=false;assert(f.pending()&&f.former_reads==0);++cases;}
 {F f;assert(f.bind());assert(f.call());std::thread t([&](){f.j.foreign();});t.join();assert(!f.pending());++cases;}
 {F f;assert(f.bind());{Journal::Add a(f.j,component,target(),1010,11);f.add();f.j.foreign();assert(!a.finish(true));}assert(!f.pending());++cases;}
 {F f;assert(f.bind());assert(f.call());f.foreign_in_read=true;assert(!f.pending());++cases;}
 {F f;assert(f.bind());Target t=target();t.bytes[12]=0xff;t.bytes[36]=0xff;assert(f.call(11,t)&&f.pending());++cases;}
 {F f;assert(f.bind());assert(f.call());assert(!f.j.pending(component,5,7,target())&&!f.j.pending(other,5,6,target())&&!f.j.pending(component,4,6,target()));++cases;}
 {F f;assert(f.bind());assert(f.call());assert(f.j.finish());assert(!f.pending());++cases;}
 {F f;assert(f.bind());f.throw_origin=true;assert(!f.call());assert(f.calls==1&&!f.pending()&&f.j.withdrawn());assert(f.j.finish());++cases;}
 {F f;assert(f.bind());f.throw_resource=true;assert(!f.call());assert(f.calls==1&&!f.pending()&&f.j.withdrawn());assert(f.j.finish());++cases;}
 {F f;assert(f.bind());f.throw_read=true;assert(!f.call());assert(f.calls==1&&!f.pending()&&f.j.withdrawn());assert(f.j.finish());++cases;}
 {F f;assert(f.bind());{Journal::Add a(f.j,component,target(),1010,11);f.add();f.throw_read=true;assert(!a.finish(true));}assert(f.calls==1&&!f.pending()&&f.j.withdrawn());assert(f.j.finish());++cases;}
 {F f;assert(f.bind());f.throw_origin=true;{Journal::Capture c(f.j,controller,target(),1010,33);assert(!f.call(22));}assert(f.calls==1&&!f.pending()&&f.j.withdrawn());assert(f.j.finish());++cases;}
 {F f;assert(f.bind());assert(f.call());f.throw_resource=true;assert(!f.pending()&&f.j.withdrawn());assert(f.j.finish());++cases;}
 {F f;assert(f.bind());f.foreign_in_read=true;assert(!f.call());assert(f.calls==1&&!f.pending()&&f.j.withdrawn());assert(f.j.finish());++cases;}
 {F f;assert(f.bind());f.throw_retained=true;assert(!f.call());assert(f.calls==1&&f.j.withdrawn()&&f.j.finish());++cases;}
 {F f;assert(f.bind());f.throw_update=true;assert(!f.call());assert(f.calls==1&&f.j.withdrawn()&&f.j.finish());++cases;}
 {F f;assert(f.bind());throw_thread=true;assert(!f.call());assert(f.calls==1&&f.j.withdrawn());throw_thread=false;assert(f.j.finish());++cases;}
 {F f;assert(f.bind());throw_thread=true;{Journal::Capture c(f.j,controller,target(),1010,33);f.add();}throw_thread=false;assert(f.calls==1&&f.j.withdrawn()&&f.j.finish());++cases;}
 {F f;assert(f.bind());f.throw_origin=true;{Journal::Capture c(f.j,controller,target(),1010,33);assert(!f.j.finish());f.add();}assert(f.calls==1&&f.j.withdrawn()&&f.j.finish());++cases;}
 {F f;assert(f.bind());try{Journal::Add a(f.j,component,target(),1010,11);f.add();f.throw_read=true;throw std::logic_error("original_body");}catch(const std::logic_error&e){assert(std::string(e.what())=="original_body");}assert(f.calls==1&&f.j.withdrawn()&&f.j.finish());++cases;}
 {F f;assert(f.bind());try{Journal::Add a(f.j,component,target(),1010,11);f.add();f.throw_retained=true;throw std::logic_error("original_body");}catch(const std::logic_error&e){assert(std::string(e.what())=="original_body");}assert(f.calls==1&&f.j.withdrawn()&&f.j.finish());++cases;}
 {F f;assert(f.bind());try{Journal::Add a(f.j,component,target(),1010,11);f.add();f.throw_resource=true;throw std::logic_error("original_body");}catch(const std::logic_error&e){assert(std::string(e.what())=="original_body");}assert(f.calls==1&&f.j.withdrawn()&&f.j.finish());++cases;}
 {F f;assert(f.bind());f.throw_origin=true;try{Journal::Capture c(f.j,controller,target(),1010,33);f.add();throw std::logic_error("original_body");}catch(const std::logic_error&e){assert(std::string(e.what())=="original_body");}assert(f.calls==1&&f.j.withdrawn()&&f.j.finish());++cases;}
 printf("%u queue custody cases passed\n",cases);
}
