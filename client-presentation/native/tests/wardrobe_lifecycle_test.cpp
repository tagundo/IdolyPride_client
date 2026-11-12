#include "../wardrobe_lifecycle.hpp"
#include <cassert>
#include <map>
#include <stdexcept>
#include <string>
#include <vector>
using namespace idoly::presentation::wardrobe;
struct Object { alignas(8) unsigned char data[256]{}; bool alive=true, active=true; const char *type=""; };
struct State { alignas(8) unsigned char data[80]{}; };
template<class T> void put(void *p,size_t n,T v) { std::memcpy(static_cast<char *>(p)+n,&v,sizeof v); }
std::map<uint32_t,void *> handles;
uint32_t next_handle=0;
bool allocation_fails=false;
uint32_t weak_new(void *p,bool strong) { assert(!strong); if(allocation_fails)return 0;handles[++next_handle]=p;return next_handle; }
void *weak_get(uint32_t h) { return handles.count(h)?handles[h]:nullptr; }
void weak_free(uint32_t h) { assert(handles.erase(h)==1); }
bool alive(void *p,Method *) { return p && static_cast<Object *>(p)->alive; }
bool active(void *p,Method *) { return static_cast<Object *>(p)->active; }
bool matches(void *p,const char *space,const char *name) {
    const Object *o=static_cast<Object *>(p);
    return !std::strcmp(o->type,name) && (!std::strcmp(space,"Solis.OutGame") || !std::strcmp(space,"System"));
}
std::vector<std::string> events;
void event(const char *p) { events.emplace_back(p); }
int original_waits=0,yields=0,failures=0,shows=0,moves=0;
int actual_timing=0;Token actual_token{};Method *actual_method=nullptr;void *actual_predicate=nullptr;
Task original_task{reinterpret_cast<void *>(0x1111),23,{}};
Task yield_task{reinterpret_cast<void *>(0x2222),42,{}};
bool throw_yield=false,throw_original=false;
Task yield(int timing,Token token,Method *method) {
    ++yields; actual_timing=timing;actual_token=token;actual_method=method;
    if(throw_yield)throw std::runtime_error("cancelled original scheduler");
    return yield_task;
}
Task wait(void *p,int timing,Token token,Method *method) {
    ++original_waits;actual_predicate=p;actual_timing=timing;actual_token=token;actual_method=method;return original_task;
}
Task show(void *,Token token,Method *method) { ++shows;actual_token=token;actual_method=method;return original_task; }
void move_noop(void *,Method *) { ++moves;if(throw_original)throw std::runtime_error("original"); }
Lifecycle *helper=nullptr;
Object *target=nullptr;
Object *delegate=nullptr;
int runner=0,other_runner=0,exception=0;
Method *sent_method=reinterpret_cast<Method *>(0x7777);
Token sent_token{reinterpret_cast<void *>(0x8888)};
bool reentrant_wait=false;
void original_fail(void *p,void *e,Method *m) {
    ++failures;assert(e==&exception && m==sent_method);assert(p==&runner || p==&other_runner);
    if(reentrant_wait) {
        Task t=helper->wait(delegate,8,sent_token,sent_method,wait,true);
        assert(t.source==yield_task.source);
    }
}
void fail_move(void *p,Method *) {
    ++moves;put(p,0,-2);put<void *>(p,8,&runner);
    helper->fail(&runner,&exception,sent_method,original_fail,true);
}
void wrong_runner_move(void *p,Method *) {
    ++moves;put(p,0,-2);put<void *>(p,8,&runner);
    helper->fail(&other_runner,&exception,sent_method,original_fail,true);
}
void handled_inner_move(void *p,Method *) {
    ++moves;put(p,0,0);put<void *>(p,8,&runner);
    helper->fail(&runner,&exception,sent_method,original_fail,true);
}
void sync_failure(void *p,Method *) { ++moves;put(p,0,-2);put<void *>(p,16,&exception); }
void successful_move(void *p,Method *) { ++moves;put(p,0,-2);put(target,0x48,true); }
void *hide_identity=reinterpret_cast<void *>(0x4444);
void setup_owner(Object &owner,Object &view) {
    owner.type="CharacterCostumeScreenView";view.type="LoadingCharacter3DView";put<void *>(&owner,0x70,&view);
}
void setup_state(State &state,Object &view,int status=-1) { state={};put(&state,0,status);put<void *>(&state,0x18,&view); }
void setup_delegate(Object &p,Object &view) { p.type="Func`1";put(&p,0x10,hide_identity);put<void *>(&p,0x20,&view); }
void fresh_show(Lifecycle &h,Object &owner,Object &view,State &s) {
    h.show(&owner,sent_token,sent_method,show,true);setup_state(s,view);target=&view;
}
void original_pooled_failure(void *p,Method *) {
    fail_move(p,nullptr);
    // Simulate a runner's state immediately reused by an inline continuation.
    std::memset(p,0,80);
}
Lifecycle *nested_helper=nullptr;Object *nested_owner=nullptr,*nested_view=nullptr;State nested_state;
void new_show_during_old_callback(void *p,Method *) {
    nested_helper->show(nested_owner,sent_token,sent_method,show,true);
    put(p,0,-2);put<void *>(p,16,&exception); // Old generation cannot mark the new Show.
}
void nested_callback(void *p,Method *) {
    setup_state(nested_state,*nested_view);
    nested_helper->move(&nested_state,nullptr,move_noop,true);
    fail_move(p,nullptr); // TLS outer frame restored after nested MoveNext.
}
void new_loading_show_during_old_callback(void *p,Method *) {
    setup_state(nested_state,*target);
    helper->move(&nested_state,nullptr,move_noop,true);
    fail_move(p,nullptr); // Old outer frame must not mark the fresh Loading.Show.
}
int main() {
    Lifecycle h;helper=&h;
    Calls api{weak_new,weak_get,weak_free,alive,active,matches,yield,hide_identity,event};h.configure(api);assert(h.ready());
    Object owner,view,predicate;State state;setup_owner(owner,view);setup_delegate(predicate,view);delegate=&predicate;
    Task t=h.show(&owner,sent_token,sent_method,show,false);assert(t.source==original_task.source && handles.empty());
    // Unknown and pending Show do not bypass WaitUntil.
    h.wait(&predicate,8,sent_token,sent_method,wait,true);assert(yields==0 && original_waits==1);
    fresh_show(h,owner,view,state);h.move(&state,nullptr,move_noop,true);
    h.wait(&predicate,8,sent_token,sent_method,wait,true);assert(yields==0);
    // REAL outer failure is visible before original SetException resumes Hide.
    reentrant_wait=true;h.move(&state,nullptr,fail_move,true);reentrant_wait=false;
    assert(events.back()=="hide_wait_released" && yields==1 && failures==1);
    assert(actual_timing==8 && actual_token.source==sent_token.source && actual_method==nullptr);
    t=h.wait(&predicate,7,sent_token,sent_method,wait,true);assert(t.source==yield_task.source && t.token==42 && actual_timing==7);
    // Exact MethodInfo/arguments remain unchanged on all fallthrough paths.
    put(&predicate,0x10,reinterpret_cast<void *>(0x5555));
    h.wait(&predicate,8,sent_token,sent_method,wait,true);
    assert(actual_method==sent_method && actual_predicate==&predicate);put(&predicate,0x10,hide_identity);
    Object unrelated;setup_delegate(unrelated,owner);h.wait(&unrelated,8,sent_token,sent_method,wait,true);
    int prior=yields;h.wait(&predicate,8,sent_token,sent_method,wait,false);assert(yields==prior);
    // Genuine cancellation/error from original scheduler still propagates.
    throw_yield=true;try { h.wait(&predicate,8,sent_token,sent_method,wait,true);assert(false); } catch(const std::runtime_error &){}throw_yield=false;
    // A fresh Show, success, inner failure, or mismatched runner cannot release.
    fresh_show(h,owner,view,state);h.move(&state,nullptr,wrong_runner_move,true);prior=yields;
    h.wait(&predicate,8,sent_token,sent_method,wait,true);assert(yields==prior);
    fresh_show(h,owner,view,state);h.move(&state,nullptr,new_loading_show_during_old_callback,true);
    h.wait(&predicate,8,sent_token,sent_method,wait,true);assert(yields==prior);
    fresh_show(h,owner,view,state);h.move(&state,nullptr,handled_inner_move,true);
    h.wait(&predicate,8,sent_token,sent_method,wait,true);assert(yields==prior);
    fresh_show(h,owner,view,state);h.move(&state,nullptr,successful_move,true);
    h.wait(&predicate,8,sent_token,sent_method,wait,true);assert(yields==prior);
    // Synchronous exception in initial wrapper stack is observed, no task consumption.
    fresh_show(h,owner,view,state);put(&view,0x48,false);h.move(&state,nullptr,sync_failure,true);
    h.wait(&predicate,8,sent_token,sent_method,wait,true);assert(yields==prior+1);
    // Pooled resumed state may change immediately; no post-original state inspection needed.
    fresh_show(h,owner,view,state);h.move(&state,nullptr,move_noop,true);setup_state(state,view,0);
    h.move(&state,nullptr,original_pooled_failure,true);
    prior=yields;h.wait(&predicate,8,sent_token,sent_method,wait,true);assert(yields==prior+1);
    // New owner generation and nested callbacks preserve the exact TLS frame.
    nested_helper=&h;nested_owner=&owner;nested_view=&view;
    fresh_show(h,owner,view,state);h.move(&state,nullptr,new_show_during_old_callback,true);prior=yields;
    h.wait(&predicate,8,sent_token,sent_method,wait,true);assert(yields==prior);
    Object owner2,view2;setup_owner(owner2,view2);h.register_owner(&owner2);nested_view=&view2;
    fresh_show(h,owner,view,state);h.move(&state,nullptr,nested_callback,true);
    h.wait(&predicate,8,sent_token,sent_method,wait,true);assert(yields==prior+1);
    // Original MoveNext exceptions are neither swallowed nor followed by added work.
    fresh_show(h,owner,view,state);throw_original=true;size_t before=events.size();
    try { h.move(&state,nullptr,move_noop,true);assert(false); } catch(const std::runtime_error &){}throw_original=false;
    assert(events.size()==before+1); // Only show_begin, before the original callback.
    h.fail(&runner,&exception,sent_method,original_fail,true); // No leaked TLS frame.
    prior=yields;h.wait(&predicate,8,sent_token,sent_method,wait,true);assert(yields==prior);
    // Disabled/disposed/replaced owner releases weak roots and never changes other views.
    owner2.active=false;h.cleanup();assert(handles.size()==2);
    fresh_show(h,owner,view,state);h.move(&state,nullptr,fail_move,true);owner.active=false;h.cleanup();assert(handles.empty());
    h.wait(&predicate,8,sent_token,sent_method,wait,true);assert(yields==prior);owner.active=true;
    fresh_show(h,owner,view,state);view.alive=false;h.cleanup();assert(handles.empty());view.alive=true;
    fresh_show(h,owner,view,state);put<void *>(&owner,0x70,nullptr);h.cleanup();assert(handles.empty());put<void *>(&owner,0x70,&view);
    allocation_fails=true;fresh_show(h,owner,view,state);assert(handles.empty());allocation_fails=false;
    fresh_show(h,owner,view,state);
    for(auto &entry:handles)entry.second=nullptr;
    h.cleanup();assert(handles.empty());size_t closed_events=events.size();h.cleanup();assert(events.size()==closed_events);
    // Bounded two slots, oldest eviction frees its weak handles.
    Object owners[3],views[3];for(int i=0;i<3;++i){setup_owner(owners[i],views[i]);h.register_owner(&owners[i]);assert(handles.size()<=4);}
    h.configure(api);assert(handles.empty());
    Tracker tracker;char json[256];Tracker::json(tracker.snapshot(),1,json,sizeof json);
    assert(std::strstr(json,"\"phase\":\"idle\"") && std::strstr(json,"\"sample_age_ms\":null"));
    std::puts(json);
    tracker.event("show_begin",100);tracker.event("show_failed",200);tracker.event("hide_wait_released",300);
    Snapshot snap=tracker.snapshot();assert(snap.sequence==3 && snap.failures==1 && snap.releases==1);
    Tracker::json(snap,350,json,sizeof json);assert(std::strstr(json,"\"sample_age_ms\":50"));
    std::puts(json);
    tracker.event("unknown",400);assert(tracker.snapshot().sequence==3);
    tracker.event("owner_closed",400);assert(tracker.snapshot().sequence==4);
    Snapshot limit{"owner_closed",INT64_MAX,INT64_MAX,INT64_MAX,0};
    Tracker::json(limit,INT64_MAX,json,sizeof json);std::puts(json);
}
