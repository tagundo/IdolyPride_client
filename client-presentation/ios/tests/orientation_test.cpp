#include <cassert>
#include <cstdint>
#include <cstring>
#include "../orientation.hpp"
namespace o=idoly::presentation::ios_orientation;
bool available=false,wait=true,on_thread=true,cancelled=false;
bool start_inside=false,change_during_entry=false;
int frame=10,width=1920,height=1080,original_calls=0,set_calls=0,move_calls=0,predicate_calls=0;
int last_description=0;bool last_option=false;void *last_label=nullptr,*last_source=nullptr;
o::Method *last_method=nullptr;
o::UniTask sentinel(void *source,signed short token) { return {source,token,{0,0,0,0,0,0}}; }
bool enabled() { return available; }
bool preference() { return wait; }
bool thread(bool) { return on_thread; }
int frames(o::Method *) { return frame; }
int w(o::Method *) { return width; }
int h(o::Method *) { return height; }
bool token_cancelled(o::CancellationToken *token,o::Method *) { last_source=token->source;return cancelled; }
void synchronous_start() {
    if(change_during_entry)wait=!wait;
    if(start_inside){int state=-1;o::internal_move_hook(&state,nullptr);}
}
o::UniTask setter(int type,o::Method *method) { assert(type==3 && method==nullptr);++set_calls;synchronous_start();return sentinel((void*)0x2220,91); }
o::UniTask original(int desc,o::CancellationToken token,o::Method *method) {
    ++original_calls;last_description=desc;last_source=token.source;last_method=method;synchronous_start();return sentinel((void*)0x1110,37);
}
o::UniTask label(int desc,void *value,o::CancellationToken token,o::Method *method) { last_label=value;return original(desc,token,method); }
o::UniTask option(int desc,bool value,o::CancellationToken token,o::Method *method) { last_option=value;return original(desc,token,method); }
void move(void *,o::Method *) { ++move_calls; }
bool predicate(void *,o::Method *) { ++predicate_calls;return true; }
int main() {
    o::configure({enabled,preference,thread,frames,w,h,token_cancelled,setter});
    o::original_wait=original;o::original_wait_label=label;
    o::original_wait_simple=option;o::original_wait_preview=option;o::original_internal_move=move;
    o::original_starts_portrait=predicate;o::original_starts_landscape=predicate;
    o::original_fixed_portrait=predicate;o::original_fixed_landscape=predicate;o::original_after=predicate;
    assert(o::ready_for_publish());
    o::CancellationToken token{(void*)0x4440};o::Method *method=(void*)0x5550;
    auto a=o::wait_hook(4,token,method);
    assert(a.source==(void*)0x1110 && a.token==37 && original_calls==1 && set_calls==0);
    assert(last_description==4 && last_source==token.source && last_method==method);
    o::wait_label_hook(3,(void*)0x7770,token,method);assert(last_label==(void*)0x7770);
    o::wait_simple_hook(2,true,token,method);assert(last_option);
    o::wait_preview_hook(1,false,token,method);assert(!last_option && original_calls==4);
    available=true;wait=false;cancelled=true;
    o::wait_hook(4,token,method);o::wait_label_hook(4,nullptr,token,method);
    o::wait_simple_hook(4,false,token,method);o::wait_preview_hook(4,true,token,method);
    assert(original_calls==8 && set_calls==0 && last_source==token.source);
    cancelled=false;
    a=o::wait_hook(4,token,method);assert(a.source==(void*)0x2220 && a.token==91);
    o::wait_label_hook(4,nullptr,token,method);o::wait_simple_hook(4,false,token,method);o::wait_preview_hook(4,true,token,method);
    assert(set_calls==4 && original_calls==8);
    on_thread=false;o::wait_hook(9,token,method);assert(original_calls==9 && last_description==9);on_thread=true;
    assert(o::after_hook(nullptr,nullptr)); // No observed original start: fail open.
    int state=-1;frame=100;o::internal_move_hook(&state,method);
    assert(state==-1 && move_calls==1 && o::begin_seen && o::begin_frame==100);
    assert(!o::starts_portrait_hook(nullptr,nullptr));
    assert(!o::starts_landscape_hook(nullptr,nullptr));
    frame=101;assert(!o::fixed_portrait_hook(nullptr,nullptr));
    assert(!o::fixed_landscape_hook(nullptr,nullptr));assert(!o::after_hook(nullptr,nullptr));
    frame=102;assert(o::starts_portrait_hook(nullptr,nullptr));assert(o::starts_landscape_hook(nullptr,nullptr));
    assert(o::fixed_portrait_hook(nullptr,nullptr));assert(o::fixed_landscape_hook(nullptr,nullptr));assert(o::after_hook(nullptr,nullptr));
    state=0;frame=103;o::internal_move_hook(&state,method);assert(o::begin_frame==100 && state==0 && move_calls==2);
    width=0;assert(!o::after_hook(nullptr,nullptr));width=1920;height=0;assert(!o::after_hook(nullptr,nullptr));height=1080;
    available=false;assert(o::fixed_portrait_hook(nullptr,nullptr));available=true;
    on_thread=false;assert(o::fixed_landscape_hook(nullptr,nullptr));on_thread=true;
    assert(predicate_calls==3);
    frame=-2;state=-1;o::internal_move_hook(&state,method);frame=0;assert(o::after_hook(nullptr,nullptr));
    // A polling preference change cannot alter an already-started transition.
    wait=true;frame=1;assert(o::after_hook(nullptr,nullptr));
    state=0;o::internal_move_hook(&state,method);assert(o::begin_bypass);
    state=-1;o::internal_move_hook(&state,method);assert(!o::begin_bypass);
    const int before_predicate=predicate_calls;
    frame=2;assert(o::after_hook(nullptr,nullptr));assert(predicate_calls==before_predicate+1);
    wait=false;assert(o::after_hook(nullptr,nullptr));assert(predicate_calls==before_predicate+2);
    // Wrapper snapshot wins even when polling changes during original startup.
    start_inside=true;change_during_entry=true;frame=200;
    o::wait_hook(4,token,method);assert(wait && o::begin_bypass && o::begin_frame==200);
    assert(!o::after_hook(nullptr,nullptr));frame=202;assert(o::after_hook(nullptr,nullptr));
    o::wait_label_hook(4,nullptr,token,method);assert(!wait && !o::begin_bypass);
    assert(o::after_hook(nullptr,nullptr));
    // Pre-cancelled callers keep original behavior even with bypass configured.
    cancelled=true;change_during_entry=false;o::wait_preview_hook(1,true,token,method);
    assert(!o::begin_bypass && !o::entry_selection_known);
    assert(o::after_hook(nullptr,nullptr));
    o::original_after=nullptr;assert(!o::ready_for_publish());
}
