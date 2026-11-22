#include <cassert>
#include <cstdio>
#include <stdexcept>
#include <cmath>
#include <cstdint>
#include <limits>
#include "video_frame.inc"
namespace v=idoly_mp4_video_frame;
struct Host {
 v::State s{};unsigned writes=0;int64_t set=-1;bool current=true,fail=false,throws=false,reentrant=false;v::Scope* scope=nullptr;
 static bool read(void* p,const v::Identity& id,v::State* out){auto&h=*static_cast<Host*>(p);if(!h.current||!v::same(h.s.identity,id))return false;*out=h.s;return true;}
 static bool write(void*p,const v::Identity&id,int64_t f){auto&h=*static_cast<Host*>(p);++h.writes;h.set=f;if(h.throws)throw std::runtime_error("set_frame");h.s.seek_pending=true;
 if(h.reentrant){h.scope->frame_ready(id,f);h.scope->seek_completed(id);assert(!h.scope->native_drain_completed(id));}return !h.fail;}
 v::Ops ops(){return {this,read,write};}
 void complete(v::Scope&scope,int64_t frame){s.frame=frame;s.seek_pending=false;assert(scope.frame_ready(s.identity,frame));assert(scope.seek_completed(s.identity));assert(scope.native_drain_completed(s.identity));}
};
Host host(){Host h;h.s.identity={reinterpret_cast<void*>(1),reinterpret_cast<void*>(2),101,102,7,9};h.s.texture=reinterpret_cast<void*>(3);h.s.texture_native=103;h.s.prepared=h.s.paused=true;h.s.seek_pending=false;h.s.frame=0;return h;}
int main(){using R=v::Result;int cases=0;int64_t f=-1;
 assert(v::frame_for_normalized_time(1.,29.97,100,&f)&&f==29);assert(v::frame_for_normalized_time(1.001001001001001,29.97,100,&f)&&f==30);++cases;
 assert(v::frame_for_normalized_time(-0.1,30,100,&f)&&f==0);assert(v::frame_for_normalized_time(10,30,300,&f)&&f==299);++cases;
 assert(!v::frame_for_normalized_time(NAN,30,100,&f));assert(!v::frame_for_normalized_time(1,INFINITY,100,&f));assert(!v::frame_for_normalized_time(1,30,0,&f));assert(!v::frame_for_normalized_time(1,30,UINT64_MAX,&f));++cases;
 {auto h=host();v::Scope s;assert(s.bind(h.ops(),h.s.identity));assert(s.request(1,30,300)==R::waiting&&h.set==30&&h.writes==1);assert(s.request(1,30,300)==R::waiting&&h.writes==1);assert(s.request(2,30,300)==R::invalid);h.complete(s,30);assert(s.poll()==R::ready&&s.receipt()==1);++cases;}
 {auto h=host();v::Scope s;s.bind(h.ops(),h.s.identity);s.request(1,30,300);h.s.frame=30;h.s.seek_pending=false;assert(s.poll()==R::waiting);s.frame_ready(h.s.identity,30);s.native_drain_completed(h.s.identity);assert(s.poll()==R::waiting);s.seek_completed(h.s.identity);assert(s.poll()==R::waiting);s.native_drain_completed(h.s.identity);assert(s.poll()==R::ready);++cases;}
 {auto h=host();v::Scope s;s.bind(h.ops(),h.s.identity);s.request(1,30,300);h.complete(s,29);assert(s.poll()==R::waiting);h.complete(s,30);assert(s.poll()==R::ready);++cases;}
 {auto h=host();v::Scope s;s.bind(h.ops(),h.s.identity);s.request(1,30,300);h.complete(s,30);h.s.seek_pending=true;assert(s.poll()==R::waiting);h.s.seek_pending=false;assert(s.poll()==R::ready);++cases;}
 {auto h=host();v::Scope s;s.bind(h.ops(),h.s.identity);s.request(0,30,300);h.complete(s,0);assert(s.poll()==R::ready);for(int i=1;i<4;++i)assert(s.request(i/120.,30,300)==R::ready);assert(h.writes==1);assert(s.request(4/120.,30,300)==R::waiting&&h.writes==2&&h.set==1);++cases;}
 {auto h=host();v::Scope s;s.bind(h.ops(),h.s.identity);s.request(0,30,300);h.complete(s,0);assert(s.poll()==R::ready);h.s.texture_native=999;assert(s.request(0,30,300)==R::waiting&&h.writes==2);++cases;}
 {auto h=host();v::Scope s;s.bind(h.ops(),h.s.identity);s.request(0,30,300);auto wrong=h.s.identity;++wrong.job;assert(!s.frame_ready(wrong,0)&&!s.seek_completed(wrong)&&!s.native_drain_completed(wrong));assert(s.poll()==R::waiting);++cases;}
 {auto h=host();v::Scope s;s.bind(h.ops(),h.s.identity);h.current=false;assert(s.request(0,30,300)==R::stale&&h.writes==0);++cases;}
 {auto h=host();v::Scope s;s.bind(h.ops(),h.s.identity);s.request(0,30,300);h.current=false;assert(s.poll()==R::stale);++cases;}
 {auto h=host();v::Scope s;s.bind(h.ops(),h.s.identity);h.fail=true;assert(s.request(0,30,300)==R::failed&&s.poll()==R::invalid);++cases;}
 {auto h=host();v::Scope s;s.bind(h.ops(),h.s.identity);h.throws=true;try{s.request(0,30,300);assert(false);}catch(const std::runtime_error&){}assert(s.poll()==R::invalid);++cases;}
 {auto h=host();v::Scope s;s.bind(h.ops(),h.s.identity);h.scope=&s;h.reentrant=true;s.request(0,30,300);assert(s.poll()==R::waiting);h.s.seek_pending=false;s.native_drain_completed(h.s.identity);assert(s.poll()==R::ready);++cases;}
 {auto h=host();v::Scope s;s.bind(h.ops(),h.s.identity);s.request(0,30,300);h.complete(s,0);assert(s.poll()==R::ready);h.s.playing=true;assert(s.request(0,30,300)==R::waiting&&h.writes==1);++cases;}
 {auto h=host();v::Scope s;assert(!s.bind({},h.s.identity));assert(s.bind(h.ops(),h.s.identity));assert(!s.bind(h.ops(),h.s.identity));s.abandon();assert(s.request(0,30,300)==R::invalid);++cases;}
 {auto h=host();v::Scope s;s.bind(h.ops(),h.s.identity);h.s.prepared=false;assert(s.request(0,30,300)==R::waiting&&h.writes==0);h.s.prepared=true;s.frame_ready(h.s.identity,0);assert(s.prepared_frame()==R::waiting);s.native_drain_completed(h.s.identity);assert(s.prepared_frame()==R::ready);assert(s.request(0,30,300)==R::ready&&h.writes==0);++cases;}
 std::printf("%d private video frame scheduling cases passed; native events modeled\n",cases);
}
