#include <cstdint>
#include <cstddef>
#include <cstring>
#include <string>
// SHIPPING_GL_OBSERVER
// SHIPPING_GPU_FENCE_CORE
#include <cassert>
#include <cstdio>
#include <memory>
#include <stdexcept>
#include <vector>
using namespace mp4_gpu_fence;
struct Cmd {
    alignas(8) unsigned char managed[24]{};
    alignas(8) unsigned char native[344]{};
    alignas(8) unsigned char proxy[56]{};
    void* refs[1]{}; uint32_t root=0; bool disposed=false;
};
struct Host {
    Pins pins{};Api api{};void*manager=this;void*device=this;
    bool main=true,sources=true,passed=false,null_hardware=false;
    bool create_throw=false,execute_throw=false,dispose_throw=false;
    bool replace_during_query=false;int queries=0,executes=0,disposes=0;
    bool gl_capture=true,gl_observed=false,gl_capture_throw=false,gl_completion_throw=false,gl_wrong_device=false,gl_switch_query=false;
    int captures=0,observations=0;uint64_t gl_generation=7;uintptr_t gl_context=0x123;uint32_t gl_next=10;
    uintptr_t vt=0x201000;std::vector<std::unique_ptr<Cmd>> commands;
    Host(){
        pins.ctor={1,{}};pins.dispose={2,{}};pins.create={3,{}};pins.execute={4,{}};
        pins.supports={5,{}};pins.hardware_passed={6,{}};
        pins.manager_cell=0x100;pins.device_cell=0x108;
        pins.create_slot=0xaa8;pins.passed_slot=0xad8;pins.release_slot=0xae0;
        pins.drivers[0]={0x1000,0x2000,0x3000,0x4000,{},{},{}};pins.driver_count=1;
        api.context=this;api.managed_base=0x100000;api.engine_base=0x200000;
        api.sources=[](void*x,const Pins&){return static_cast<Host*>(x)->sources;};
        api.owner_thread=[](void*x){return static_cast<Host*>(x)->main;};
        api.mapped=[](void*,uintptr_t p,size_t,bool){return p!=0;};
        api.read=[](void*x,uintptr_t p,void*out,size_t n){
            auto&h=*static_cast<Host*>(x);
            if(p==h.api.engine_base+h.pins.manager_cell){std::memcpy(out,&h.manager,n);return true;}
            if(p==h.api.engine_base+h.pins.device_cell){std::memcpy(out,&h.device,n);return true;}
            if(p==reinterpret_cast<uintptr_t>(h.device)){std::memcpy(out,&h.vt,n);return true;}
            for(auto slot:{h.pins.create_slot,h.pins.passed_slot,h.pins.release_slot}){
                if(p==h.vt+slot){uintptr_t v=h.api.engine_base+(slot==h.pins.create_slot?0x2000:slot==h.pins.passed_slot?0x3000:0x4000);std::memcpy(out,&v,n);return true;}}
            if(p>=0x100000&&p<0x210000){std::memset(out,0,n);return true;}
            std::memcpy(out,reinterpret_cast<void*>(p),n);return true;
        };
        api.new_command=[](void*x)->void*{auto&h=*static_cast<Host*>(x);h.commands.emplace_back(new Cmd);return h.commands.back()->managed;};
        api.retain=[](void*x,void*p){auto&h=*static_cast<Host*>(x);for(auto&c:h.commands)if(c->managed==p)return c->root=static_cast<uint32_t>(&c-&h.commands[0]+1);return uint32_t(0);};
        api.target=[](void*x,uint32_t r)->void*{auto&h=*static_cast<Host*>(x);for(auto&c:h.commands)if(c->root==r)return c->managed;return nullptr;};
        api.release=[](void*x,uint32_t r){auto&h=*static_cast<Host*>(x);for(auto&c:h.commands)if(c->root==r)c->root=0;};
        api.ctor=[](void*x,void*p){auto&h=*static_cast<Host*>(x);for(auto&c:h.commands)if(c->managed==p){void*n=c->native;std::memcpy(c->managed+16,&n,8);}};
        api.create=[](void*x,void*p)->Fence{auto&h=*static_cast<Host*>(x);if(h.create_throw)throw std::runtime_error("create");if(!h.manager)h.manager=&h;
            for(auto&c:h.commands)if(c->managed==p){uint32_t one=1;std::memcpy(c->proxy+32,&one,4);std::memcpy(c->proxy+48,&one,4);std::memcpy(c->proxy+52,&one,4);
                c->refs[0]=c->proxy;void*refs=c->refs;uint64_t count=1;std::memcpy(c->native+0x130,&refs,8);std::memcpy(c->native+0x140,&count,8);
                return {c->proxy,1,1};}return {};};
        api.execute=[](void*x,void*p){auto&h=*static_cast<Host*>(x);++h.executes;
            for(auto&c:h.commands)if(c->managed==p){void*hardware=h.null_hardware?nullptr:reinterpret_cast<void*>(h.pins.drivers[0].gl_completion?h.gl_next++:0x991);std::memcpy(c->proxy+40,&hardware,8);}
            if(h.execute_throw)throw std::runtime_error("execute");};
        api.dispose=[](void*x,void*p){auto&h=*static_cast<Host*>(x);++h.disposes;if(h.dispose_throw)throw std::runtime_error("dispose");for(auto&c:h.commands)if(c->managed==p)c->disposed=true;};
        api.supports=[](void*){return true;};
        api.hardware_passed=[](void*x,void*){auto&h=*static_cast<Host*>(x);++h.queries;if(h.gl_switch_query)++h.gl_generation;if(h.replace_during_query)h.manager=nullptr;return h.passed;};
        api.capture_gl_witness=[](void*x,const Device&d,mp4_gl_completion::Witness&w){auto&h=*static_cast<Host*>(x);++h.captures;assert(h.captures==h.executes+1);if(h.gl_capture_throw)throw std::runtime_error("witness");w={0xabc,h.gl_wrong_device?uintptr_t(1):reinterpret_cast<uintptr_t>(d.device),h.gl_context,h.gl_generation,h.gl_next};return h.gl_capture;};
        api.gl_completed=[](void*x,const mp4_gl_completion::Witness&w,void*p){auto&h=*static_cast<Host*>(x);++h.observations;if(h.gl_completion_throw)throw std::runtime_error("observation");return h.gl_observed&&w.manager==0xabc&&w.device==reinterpret_cast<uintptr_t>(h.device)&&w.generation==h.gl_generation&&w.gl_context==h.gl_context&&reinterpret_cast<uintptr_t>(p)>=w.minimum_serial&&reinterpret_cast<uintptr_t>(p)<h.gl_next;};
    }
    int roots()const{int n=0;for(auto&c:commands)n+=c->root!=0;return n;}
};
static Context ctx{reinterpret_cast<void*>(0x888)};
static void start(Ledger&l,Host&h){assert(l.configure(h.api,h.pins,1));assert(l.begin_draw(1,1,ctx));}
static void queued(Ledger&l,Host&h){start(l,h);assert(l.submit_returned(1,1,ctx)==Result::waiting);assert(l.end_draw(1,1));l.seal(1);}
int main(){int n=0;
 {Host h;Ledger l;queued(l,h);assert(l.poll(1)==Result::waiting);assert(h.roots()==1&&!l.release(1));h.passed=true;assert(l.final_fenced(1));assert(l.release(1)&&h.roots()==0&&h.disposes==1);++n;}
 {Host h;h.null_hardware=true;h.passed=true;Ledger l;queued(l,h);uint32_t v=2;std::memcpy(h.commands[0]->proxy+52,&v,4);assert(l.poll(1)==Result::waiting&&h.queries==0&&h.roots()==1);++n;}
 {Host h;Ledger l;queued(l,h);h.sources=false;h.passed=true;assert(l.final_fenced(1)&&l.release(1));++n;}
 {Host h;h.execute_throw=true;h.passed=true;Ledger l;queued(l,h);assert(l.final_fenced(1)&&l.release(1));++n;}
 {Host h;h.create_throw=true;Ledger l;start(l,h);assert(l.submit_returned(1,1,ctx)==Result::quarantined);assert(!l.end_draw(1,1));l.seal(1);assert(!l.release(1)&&h.roots()==1&&h.executes==0);++n;}
 {Host h;Ledger l;start(l,h);assert(!l.end_draw(1,1));l.seal(1);assert(!l.final_fenced(1));++n;}
 {Host h;Ledger l;start(l,h);l.submit_failed(1,1,ctx);assert(!l.end_draw(1,1));l.seal(1);assert(!l.final_fenced(1));++n;}
 {Host h;Ledger l;queued(l,h);h.manager=nullptr;assert(l.poll(1)==Result::quarantined&&h.queries==0&&h.roots()==1);++n;}
 {Host h;Ledger l;queued(l,h);h.vt+=8;assert(l.poll(1)==Result::quarantined&&h.queries==0&&h.roots()==1);++n;}
 {Host h;Ledger l;queued(l,h);uint64_t count=0;std::memcpy(h.commands[0]->native+0x140,&count,8);assert(l.poll(1)==Result::quarantined&&h.queries==0);++n;}
 {Host h;Ledger l;queued(l,h);void*none=nullptr;std::memcpy(h.commands[0]->managed+16,&none,8);assert(l.poll(1)==Result::quarantined&&h.queries==0);++n;}
 {Host h;Ledger l;queued(l,h);h.replace_during_query=true;h.passed=true;assert(l.poll(1)==Result::quarantined&&h.roots()==1);++n;}
 {Host h;Ledger l;queued(l,h);uint32_t version=3;std::memcpy(h.commands[0]->proxy+52,&version,4);assert(l.poll(1)==Result::quarantined&&h.queries==0);++n;}
 {Host h;h.passed=true;Ledger l;start(l,h);assert(l.submit_returned(1,1,ctx)==Result::waiting);assert(l.submit_returned(1,1,ctx)==Result::waiting);assert(l.end_draw(1,1));assert(l.draw_fenced(1,1));assert(l.retire_sequence(1,1)&&h.roots()==0&&h.disposes==2);assert(l.begin_draw(1,2,ctx));assert(l.submit_returned(1,2,ctx)==Result::waiting);assert(l.end_draw(1,2));l.seal(1);assert(l.release(1)&&h.roots()==0);++n;}
 {Host h;h.passed=true;Ledger l;assert(l.configure(h.api,h.pins,1));for(uint64_t s=1;s<=400;++s){assert(l.begin_draw(1,s,ctx));assert(l.submit_returned(1,s,ctx)==Result::waiting);assert(l.end_draw(1,s));assert(l.retire_sequence(1,s));assert(h.roots()==0&&l.entries()==0);}l.seal(1);assert(l.release(1));++n;}
 {Host h;h.passed=true;Ledger l;queued(l,h);h.dispose_throw=true;assert(!l.release(1)&&h.roots()==1&&h.disposes==1);h.dispose_throw=false;assert(!l.release(1)&&h.disposes==1);++n;}
 {Host h;h.passed=true;Ledger l;queued(l,h);l.unknown_gpu_work(1);assert(!l.final_fenced(1)&&h.roots()==1);++n;}
 {Host h;Ledger l;queued(l,h);h.main=false;assert(l.poll(1)==Result::quarantined&&h.queries==0);++n;}
 {Host h;Ledger l;start(l,h);assert(!l.pending_context(1,1,Context{reinterpret_cast<void*>(1)}));assert(l.pending_context(1,1,ctx));assert(!l.begin_draw(1,2,ctx));assert(l.poll(1)==Result::waiting);++n;}
 {Host h;h.manager=nullptr;h.passed=true;Ledger l;queued(l,h);assert(l.final_fenced(1)&&l.release(1));++n;}
 {Host h;h.passed=true;Ledger l;queued(l,h);assert(l.release(1));assert(l.configure(h.api,h.pins,2));assert(l.begin_draw(2,1,ctx));assert(!l.pending_context(1,1,ctx));l.unknown_gpu_work(1);l.seal(1);l.submit_failed(1,1,ctx);assert(l.submit_returned(1,1,ctx)==Result::quarantined);assert(l.entries()==0);assert(l.submit_returned(2,1,ctx)==Result::waiting);assert(l.end_draw(2,1));l.seal(2);assert(!l.draw_fenced(1,1));assert(l.retire_sequence(2,1));assert(!l.draw_fenced(1,1)&&l.draw_fenced(2,1));assert(!l.final_fenced(1)&&l.final_fenced(2)&&l.release(2));++n;}
 {Host h;Ledger l;queued(l,h);assert(!l.configure(h.api,h.pins,2));h.manager=nullptr;assert(l.poll(1)==Result::quarantined);assert(!l.configure(h.api,h.pins,2)&&h.roots()==1);++n;}

 {Host h;h.pins.drivers[0].gl_completion=true;Ledger l;queued(l,h);h.passed=true;assert(l.poll(1)==Result::waiting&&h.observations==1&&h.roots()==1);h.gl_observed=true;assert(l.final_fenced(1)&&l.release(1)&&h.disposes==1&&h.captures==1);++n;}
 {Host h;h.pins.drivers[0].gl_completion=true;h.gl_observed=true;Ledger l;queued(l,h);assert(l.poll(1)==Result::waiting);h.passed=true;assert(l.final_fenced(1)&&l.release(1));++n;}
 {Host h;h.pins.drivers[0].gl_completion=true;h.api.capture_gl_witness=nullptr;Ledger l;assert(!l.configure(h.api,h.pins,1)&&h.roots()==0);++n;}
 {Host h;h.pins.drivers[0].gl_completion=true;h.api.gl_completed=nullptr;Ledger l;assert(!l.configure(h.api,h.pins,1)&&h.roots()==0);++n;}
 {Host h;h.pins.drivers[0].gl_completion=true;h.gl_capture=false;Ledger l;start(l,h);assert(l.submit_returned(1,1,ctx)==Result::quarantined&&h.executes==0&&h.roots()==1);assert(!l.end_draw(1,1)&&!l.release(1));++n;}
 {Host h;h.pins.drivers[0].gl_completion=true;h.gl_wrong_device=true;Ledger l;start(l,h);assert(l.submit_returned(1,1,ctx)==Result::quarantined&&h.executes==0&&h.roots()==1);++n;}
 {Host h;h.pins.drivers[0].gl_completion=true;h.gl_capture_throw=true;Ledger l;start(l,h);assert(l.submit_returned(1,1,ctx)==Result::quarantined&&h.executes==0&&h.roots()==1);++n;}
 {Host h;h.pins.drivers[0].gl_completion=true;h.passed=true;h.gl_observed=true;Ledger l;queued(l,h);++h.gl_generation;assert(l.poll(1)==Result::waiting&&!l.release(1)&&h.roots()==1&&h.disposes==0);++n;}
 {Host h;h.pins.drivers[0].gl_completion=true;h.passed=true;h.gl_observed=true;Ledger l;queued(l,h);++h.gl_context;assert(l.poll(1)==Result::waiting&&h.roots()==1);++n;}
 {Host h;h.pins.drivers[0].gl_completion=true;h.passed=true;h.gl_observed=true;h.gl_switch_query=true;Ledger l;queued(l,h);assert(l.poll(1)==Result::waiting&&h.roots()==1);++n;}
 {Host h;h.pins.drivers[0].gl_completion=true;h.passed=true;h.gl_observed=true;Ledger l;queued(l,h);void*p=reinterpret_cast<void*>(1000);std::memcpy(h.commands[0]->proxy+40,&p,8);assert(l.poll(1)==Result::waiting&&h.roots()==1);++n;}
 {Host h;h.pins.drivers[0].gl_completion=true;h.passed=true;h.gl_observed=true;Ledger l;queued(l,h);void*p=reinterpret_cast<void*>(9);std::memcpy(h.commands[0]->proxy+40,&p,8);assert(l.poll(1)==Result::waiting&&h.roots()==1);++n;}
 {Host h;h.pins.drivers[0].gl_completion=true;h.passed=true;h.gl_completion_throw=true;Ledger l;queued(l,h);assert(l.poll(1)==Result::waiting&&h.roots()==1);h.gl_completion_throw=false;h.gl_observed=true;assert(l.final_fenced(1)&&l.release(1));++n;}
 {Host h;h.pins.drivers[0].gl_completion=true;h.passed=true;Ledger l;queued(l,h);uint32_t version=2;std::memcpy(h.commands[0]->proxy+52,&version,4);assert(l.poll(1)==Result::waiting&&h.roots()==1&&h.disposes==0);++n;}
 {Host h;h.pins.drivers[0].gl_completion=true;h.passed=true;h.gl_observed=true;Ledger l;start(l,h);assert(l.submit_returned(1,1,ctx)==Result::waiting);assert(l.submit_returned(1,1,ctx)==Result::waiting);assert(l.end_draw(1,1));assert(l.draw_fenced(1,1)&&l.retire_sequence(1,1)&&h.captures==2&&h.disposes==2);++n;}
 {Host h;h.passed=true;h.gl_capture_throw=true;h.gl_completion_throw=true;Ledger l;queued(l,h);assert(l.final_fenced(1)&&l.release(1)&&h.captures==0&&h.observations==0);++n;}
 {Host h;h.pins.drivers[0].gl_completion=true;h.passed=true;h.gl_observed=true;Ledger l;queued(l,h);h.sources=false;assert(l.final_fenced(1)&&l.release(1));++n;}
 {Host h;h.pins.drivers[0].gl_completion=true;h.passed=true;h.gl_observed=true;h.execute_throw=true;Ledger l;queued(l,h);assert(l.final_fenced(1)&&l.release(1)&&h.captures==1);++n;}
 {Host h;h.pins.drivers[0].gl_completion=true;h.passed=true;h.gl_observed=true;h.null_hardware=true;Ledger l;queued(l,h);assert(l.poll(1)==Result::waiting&&h.queries==0&&h.observations==0);++n;}

 {Host h;h.passed=true;Ledger l;assert(l.configure(h.api,h.pins,1)&&l.begin_auxiliary(1,1));assert(l.pending_auxiliary(1,1)&&!l.pending_context(1,1,ctx)&&!l.pending_context(1,1,Context{}));assert(l.auxiliary_returned(1,1)==Result::waiting&&l.end_auxiliary(1,1));assert(l.draw_fenced(1,1)&&l.retire_sequence(1,1));l.seal(1);assert(l.release(1)&&h.executes==1);++n;}
 {Host h;Ledger l;assert(l.configure(h.api,h.pins,1)&&l.begin_auxiliary(1,1));assert(!l.end_auxiliary(1,1)&&l.poll(1)==Result::quarantined&&h.roots()==0);l.seal(1);assert(!l.release(1));++n;}
 {Host h;Ledger l;assert(l.configure(h.api,h.pins,1)&&l.begin_auxiliary(1,1));l.auxiliary_failed(1,1);assert(!l.end_auxiliary(1,1));l.seal(1);assert(!l.final_fenced(1)&&!l.release(1)&&h.executes==0);++n;}
 {Host h;h.passed=true;Ledger l;assert(l.configure(h.api,h.pins,1)&&l.begin_auxiliary(1,1));assert(l.submit_returned(1,1,Context{})==Result::quarantined&&l.submit_returned(1,1,ctx)==Result::quarantined&&l.entries()==0);l.submit_failed(1,1,Context{});l.submit_failed(1,1,ctx);assert(l.auxiliary_returned(1,1)==Result::waiting&&l.end_auxiliary(1,1));l.seal(1);assert(l.final_fenced(1)&&l.release(1));++n;}
 {Host h;h.passed=true;Ledger l;start(l,h);assert(!l.begin_auxiliary(1,2)&&!l.pending_auxiliary(1,1));assert(l.auxiliary_returned(1,1)==Result::quarantined&&l.entries()==0);l.auxiliary_failed(1,1);assert(l.submit_returned(1,1,ctx)==Result::waiting&&l.end_draw(1,1));l.seal(1);assert(l.release(1));++n;}
 {Host h;h.passed=true;Ledger l;assert(l.configure(h.api,h.pins,1)&&l.begin_auxiliary(1,1));assert(!l.pending_auxiliary(2,1)&&l.auxiliary_returned(2,1)==Result::quarantined&&!l.end_auxiliary(2,1)&&l.entries()==0);l.auxiliary_failed(2,1);assert(l.auxiliary_returned(1,1)==Result::waiting&&l.end_auxiliary(1,1));l.seal(1);assert(l.release(1));++n;}
 {Host h;h.pins.drivers[0].gl_completion=true;h.passed=true;Ledger l;assert(l.configure(h.api,h.pins,1)&&l.begin_auxiliary(1,1));assert(l.auxiliary_returned(1,1)==Result::waiting&&l.end_auxiliary(1,1));l.seal(1);assert(!l.final_fenced(1)&&h.roots()==1);h.gl_observed=true;assert(l.final_fenced(1)&&l.release(1)&&h.captures==1&&h.observations>=2);++n;}
 {Host h;h.create_throw=true;Ledger l;assert(l.configure(h.api,h.pins,1)&&l.begin_auxiliary(1,1));assert(l.auxiliary_returned(1,1)==Result::quarantined&&!l.end_auxiliary(1,1));l.seal(1);assert(!l.release(1)&&h.roots()==1&&h.executes==0);++n;}

 {Host h;Ledger l;assert(l.configure(h.api,h.pins,1)&&l.active_fenced(1,0));assert(h.executes==0&&h.disposes==0&&!l.active_fenced(1,1));++n;}
 {Host h;Ledger l;assert(l.configure(h.api,h.pins,1));assert(l.source_queue_barrier(1,1)==Result::waiting&&h.executes==1&&l.last_dispatch_returned());assert(!l.active_fenced(1,1));h.passed=true;assert(l.active_fenced(1,1)&&h.disposes==0&&h.roots()==1);assert(l.retire_sequence(1,1)&&l.begin_draw(1,2,ctx));assert(l.submit_returned(1,2,ctx)==Result::waiting&&l.end_draw(1,2)&&l.active_fenced(1,2));assert(l.retire_sequence(1,2)&&l.begin_draw(1,3,ctx));++n;}
 {Host h;Ledger l;assert(l.source_queue_barrier(1,1)==Result::quarantined&&h.executes==0);++n;}
 {Host h;Ledger l;assert(l.configure(h.api,h.pins,1));assert(l.source_queue_barrier(1,2)==Result::quarantined&&h.executes==0);assert(l.source_queue_barrier(2,1)==Result::quarantined&&h.executes==0);++n;}
 {Host h;Ledger l;assert(l.configure(h.api,h.pins,1)&&l.source_queue_barrier(1,1)==Result::waiting);assert(l.source_queue_barrier(1,1)==Result::quarantined&&h.executes==1);++n;}
 {Host h;Ledger l;assert(l.configure(h.api,h.pins,1)&&l.source_queue_barrier(1,1)==Result::waiting);h.passed=true;l.unknown_gpu_work(1);assert(!l.active_fenced(1,1)&&h.roots()==1&&h.disposes==0);++n;}
 {Host h;Ledger l;start(l,h);assert(!l.active_fenced(1,1)&&!l.active_fenced(1,0));++n;}
 {Host h;Ledger l;assert(l.configure(h.api,h.pins,1)&&l.source_queue_barrier(1,1)==Result::waiting);h.passed=true;l.seal(1);assert(!l.active_fenced(1,1)&&l.final_fenced(1));assert(l.source_queue_barrier(1,2)==Result::quarantined&&h.executes==1);++n;}
 {Host h;Ledger l;assert(l.configure(h.api,h.pins,1)&&l.source_queue_barrier(1,1)==Result::waiting);h.passed=true;assert(!l.active_fenced(2,1)&&!l.active_fenced(1,0));assert(l.active_fenced(1,1));++n;}
 {Host h;h.pins.drivers[0].gl_completion=true;Ledger l;assert(l.configure(h.api,h.pins,1)&&l.source_queue_barrier(1,1)==Result::waiting);h.passed=true;assert(!l.active_fenced(1,1)&&h.observations==1);h.gl_observed=true;assert(l.active_fenced(1,1)&&h.disposes==0);++n;}
 {Host h;h.create_throw=true;Ledger l;assert(l.configure(h.api,h.pins,1)&&l.source_queue_barrier(1,1)==Result::quarantined);assert(!l.active_fenced(1,1)&&h.roots()==1&&h.executes==0);++n;}
 {Host h;h.execute_throw=true;Ledger l;assert(l.configure(h.api,h.pins,1)&&l.source_queue_barrier(1,1)==Result::waiting);assert(!l.last_dispatch_returned()&&h.roots()==1);h.passed=true;assert(l.active_fenced(1,1)&&!l.last_dispatch_returned());++n;}
 {Host h;h.null_hardware=true;h.passed=true;Ledger l;assert(l.configure(h.api,h.pins,1)&&l.source_queue_barrier(1,1)==Result::waiting);assert(!l.active_fenced(1,1)&&h.queries==0&&h.disposes==0);++n;}
 {Host h;Ledger l;start(l,h);assert(l.submit_returned(1,1,ctx)==Result::waiting&&l.submit_returned(1,1,ctx)==Result::waiting&&l.end_draw(1,1));assert(!l.active_fenced(1,1));h.passed=true;assert(l.active_fenced(1,1)&&h.queries==4&&h.disposes==0&&h.roots()==2);++n;}
 std::printf("GPU fence ledger: %d substantive cases passed\n",n);
}
