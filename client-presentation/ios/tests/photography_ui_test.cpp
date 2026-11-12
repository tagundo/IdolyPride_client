#include <cassert>
#include <cstdint>
#include <cstddef>
#include <cstring>
#include <stdexcept>
#include "../photography_ui.hpp"
namespace p=idoly::presentation::ios_photography_ui;
struct Object { alignas(8) unsigned char bytes[112]{};int kind;bool ui=true; } owner{{},1}, model1{{},2},model2{{},2};
void *handles[32]{};uint32_t next_handle=1;int original_calls=0,set_calls=0,get_calls=0,free_calls=0;
bool original_throws=false,allocation_fails=false,readback_fails=false;
template<class T> void put(Object &o,size_t offset,T value) {std::memcpy(o.bytes+offset,&value,sizeof value);}
uint32_t weak_new(void *o,bool resurrect) {assert(!resurrect);if(allocation_fails)return 0;handles[next_handle]=o;return next_handle++;}
void *weak_get(uint32_t h) {return handles[h];}
void weak_free(uint32_t h) {assert(handles[h]);handles[h]=nullptr;++free_calls;}
bool matches(void *value,const char *space,const char *name) {
    assert(!std::strcmp(space,"Solis.Photography"));auto *o=static_cast<Object*>(value);
    return (o->kind==1 && !std::strcmp(name,"PhotographyPreviewContentPresenter"))
        || (o->kind==2 && !std::strcmp(name,"PhotographyPreviewContentModel"));
}
bool get(void *value,p::Method *) {++get_calls;return readback_fails || static_cast<Object*>(value)->ui;}
void set(void *value,bool on,p::Method *) {assert(original_calls>0);++set_calls;static_cast<Object*>(value)->ui=on;}
void original(void *value,p::Method *method) {
    assert(value==&owner && method==(void*)0x7780);++original_calls;
    if(original_throws)throw std::runtime_error("original");
}
int main() {
    p::DefaultHidden helper;helper.configure({weak_new,weak_get,weak_free,matches,get,set});assert(helper.ready());
    put(owner,0x40,(void*)&model1);put(model1,0x10,(void*)0x1230);put(model2,0x10,(void*)0x1240);
    helper.bind(&owner,(void*)0x7780,original,false);assert(model1.ui && set_calls==0);
    original_throws=true;try{helper.bind(&owner,(void*)0x7780,original,true);assert(false);}catch(const std::runtime_error&){}
    assert(set_calls==0 && next_handle==1);original_throws=false;
    helper.bind(&owner,(void*)0x7780,original,true);assert(!model1.ui && set_calls==1 && get_calls==1);
    model1.ui=true;helper.bind(&owner,(void*)0x7780,original,true);assert(model1.ui && set_calls==1); // User Show survives re-bind.
    put(owner,0x40,(void*)&model2);helper.bind(&owner,(void*)0x7780,original,true);
    assert(!model2.ui && set_calls==2 && free_calls==1);
    helper.clear();assert(free_calls==2);model2.ui=true;
    allocation_fails=true;helper.bind(&owner,(void*)0x7780,original,true);assert(model2.ui && set_calls==2);allocation_fails=false;
    owner.kind=3;helper.bind(&owner,(void*)0x7780,original,true);assert(model2.ui && set_calls==2);owner.kind=1;
    put(model2,0x18,true);helper.bind(&owner,(void*)0x7780,original,true);assert(set_calls==2);put(model2,0x18,false);
    put(model2,0x10,(void*)nullptr);helper.bind(&owner,(void*)0x7780,original,true);assert(set_calls==2);put(model2,0x10,(void*)0x1240);
    readback_fails=true;helper.bind(&owner,(void*)0x7780,original,true);assert(set_calls==3);readback_fails=false;
    helper.bind(&owner,(void*)0x7780,original,true);assert(set_calls==4 && !model2.ui);
    model2.ui=true;helper.bind(&owner,(void*)0x7780,original,true);assert(set_calls==4 && model2.ui);
    helper.clear();assert(free_calls==3);
}
