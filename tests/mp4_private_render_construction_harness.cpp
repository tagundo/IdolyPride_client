#include <cstddef>
#include <cstdint>
#include <cstring>
#include <cassert>
#include <cstdio>
#include <map>
#include <vector>
#include <memory>
#include <stdexcept>
#include "mp4-private-render-construction.hpp.inc"
using namespace idoly_mp4_private_render_construction;
struct Object {enum Kind{array,root,library,material,shader}kind;int32_t values[7]{};bool native=false;void* slots[13]{};};
struct Fixture {
    std::vector<std::unique_ptr<Object>> heap;std::map<uint32_t,void*> roots;uint32_t next=1;
    void* old[2]{},*current_arrays[2]{};void* source_material=nullptr,*shader=nullptr,*lib=nullptr,*root=nullptr;
    uint64_t epoch=7;bool thread=true,current=true,routes=true,admitted=true,fenced=true,complete=true,wrong_values=false,old_mutate=false,handoff=false;
    int throw_after=-1,throw_before=-1,material_target=13,deny_retain=-1,retains=0,static_fail=0,destroy_fail=0;
    int created=0,destroyed=0,constructor_calls=0,static_sets=0;Factory factory;static Fixture* active;
    Fixture(){active=this;shader=make(Object::shader);source_material=make(Object::material);obj(source_material)->native=true;
        for(int i=0;i<2;++i){old[i]=make(Object::array);current_arrays[i]=old[i];for(int j=0;j<7;++j)obj(old[i])->values[j]=i*100+j*3+11;}}
    Object* make(Object::Kind k){heap.emplace_back(new Object{});heap.back()->kind=k;return heap.back().get();}
    Object* obj(void* p){for(auto& value:heap)if(value.get()==p)return value.get();return nullptr;}
    static Fixture& get(void* p){return *static_cast<Fixture*>(p);}
    static bool owner(){return active->thread;}
    static bool is_current(void* p,uint64_t epoch){auto&f=get(p);return f.current&&f.epoch==epoch;}
    static bool verified(void* p){return get(p).routes;}
    static bool admission(void* p){return get(p).admitted;}
    static uint32_t retain(void* p){auto&f=*active;++f.retains;if(f.retains==f.deny_retain)return 0;f.roots[f.next]=p;return f.next++;}
    static void* target(uint32_t root){auto&f=*active;auto i=f.roots.find(root);return i==f.roots.end()?nullptr:i->second;}
    static void release(uint32_t root){active->roots.erase(root);}
    static bool mapped(const void* p,size_t n,bool){auto&f=*active;for(auto& o:f.heap){auto a=reinterpret_cast<uintptr_t>(p),b=reinterpret_cast<uintptr_t>(o.get());if(a>=b&&a-b<=sizeof(Object)&&n<=sizeof(Object)-(a-b))return true;}return false;}
    static bool array7(void* p,void** data){auto*o=active->obj(p);if(!o||o->kind!=Object::array)return false;*data=o->values;return true;}
    static void* sget(void* p,unsigned i){return get(p).current_arrays[i];}
    static void sset(void* p,unsigned i,void* object){auto&f=get(p);++f.static_sets;if(f.static_fail&&i==1){--f.static_fail;throw std::runtime_error("static retry");}f.current_arrays[i]=object;}
    static bool root_type(void* p,void* o){auto*value=get(p).obj(o);return value&&value->kind==Object::root;}
    static void* allocate(void* p){auto&f=get(p);f.root=f.make(Object::root);return f.root;}
    static bool material_receiver(void* p,void* receiver,void* shader){auto&f=get(p);auto*o=f.obj(receiver);return o&&o->kind==Object::material&&!o->native&&shader==f.shader;}
    static bool library_receiver(void* p,void* receiver){auto&f=get(p);auto*o=f.obj(receiver);if(!o||o->kind!=Object::library)return false;for(void* v:o->slots)if(v)return false;return true;}
    static bool alive(void* p){auto*o=active->obj(p);return o&&o->kind==Object::material&&o->native;}
    static void destroy(void* p){auto&f=*active;assert(p!=f.source_material);auto*o=f.obj(p);assert(o&&o->native);o->native=false;++f.destroyed;if(f.destroy_fail){--f.destroy_fail;throw std::runtime_error("destroy retry");}}
    static bool cleanup(void* p){return get(p).fenced;}
    static bool ctor(void* p,void* root){auto&f=get(p);++f.constructor_calls;
        f.lib=f.make(Object::library);if(!f.factory.library_before(f.lib))return false;
        if(f.old_mutate)f.obj(f.old[0])->values[3]=999;
        for(unsigned i=0;i<2;++i){void* array=f.make(Object::array);for(int j=0;j<7;++j)f.obj(array)->values[j]=i*100+j*3+11;f.current_arrays[i]=array;}
        if(f.wrong_values)f.obj(f.current_arrays[1])->values[6]=7;
        for(int i=0;i<f.material_target;++i){void* mat=f.make(Object::material);
            // Exact receiver observer runs before native creation, including
            // the final material not assigned into Library/Pass fields yet.
            if(!f.factory.material_before(mat,f.shader))return false;
            if(i==f.throw_before)throw std::runtime_error("before native");
            f.obj(mat)->native=true;++f.created;
            if(f.handoff&&i==3){assert(f.factory.restore_static());++f.epoch;f.current=false;for(unsigned k=0;k<2;++k)f.current_arrays[k]=f.make(Object::array);throw std::runtime_error("scene handoff");}
            if(i==f.throw_after)throw std::runtime_error("after native before assignment");
            if(i<13)f.obj(f.lib)->slots[i]=mat;
        }
        f.obj(root)->slots[0]=f.lib;return true;}
    static bool finished(void* p,void* root){auto&f=get(p);return f.complete&&f.obj(root)->slots[0]==f.lib;}
    Api api(){return{this,owner,is_current,verified,admission,retain,target,release,mapped,array7,sget,sset,root_type,allocate,ctor,finished,material_receiver,library_receiver,alive,destroy,cleanup};}
    void originals_restored(){for(unsigned i=0;i<2;++i){assert(current_arrays[i]==old[i]);for(int j=0;j<7;++j)assert(obj(old[i])->values[j]==int(i)*100+j*3+11);}assert(obj(source_material)->native);}
};
Fixture* Fixture::active=nullptr;
int main(){unsigned scenarios=0;
    {Fixture f;assert(f.factory.begin(f.api(),7,13));assert(f.factory.construct());f.originals_restored();assert(f.created==13&&f.factory.library_count()==1&&f.factory.material_count()==13);assert(f.factory.publish());assert(f.factory.release());assert(f.destroyed==13&&f.roots.empty());f.originals_restored();++scenarios;}
    for(int point=0;point<13;++point){Fixture f;f.throw_after=point;assert(f.factory.begin(f.api(),7,13));assert(!f.factory.construct());assert(!f.obj(f.root)->slots[0]);f.originals_restored();assert(f.factory.release());assert(f.created==point+1&&f.destroyed==f.created&&f.roots.empty());++scenarios;}
    for(int point=0;point<13;++point){Fixture f;f.throw_before=point;assert(f.factory.begin(f.api(),7,13));assert(!f.factory.construct());f.originals_restored();assert(f.factory.release());assert(f.created==point&&f.destroyed==f.created&&f.roots.empty());++scenarios;}
    {Fixture f;f.old_mutate=true;assert(f.factory.begin(f.api(),7,13));assert(f.factory.construct());f.originals_restored();assert(f.factory.release());++scenarios;}
    {Fixture f;f.wrong_values=true;assert(f.factory.begin(f.api(),7,13));assert(!f.factory.construct());f.originals_restored();assert(f.factory.release());assert(f.destroyed==13&&f.roots.empty());++scenarios;}
    {Fixture f;f.material_target=14;assert(f.factory.begin(f.api(),7,13));assert(!f.factory.construct());assert(f.created==13);f.originals_restored();assert(f.factory.release());assert(f.destroyed==13&&f.roots.empty());++scenarios;}
    {Fixture f;f.static_fail=1;assert(f.factory.begin(f.api(),7,13));assert(!f.factory.construct());assert(f.factory.release());f.originals_restored();assert(f.destroyed==13&&f.roots.empty());++scenarios;}
    {Fixture f;assert(f.factory.begin(f.api(),7,13));assert(f.factory.construct());assert(f.factory.publish());f.fenced=false;assert(!f.factory.release());assert(!f.destroyed&&!f.roots.empty());f.fenced=true;assert(f.factory.release());assert(f.destroyed==13&&f.roots.empty());++scenarios;}
    {Fixture f;f.destroy_fail=1;assert(f.factory.begin(f.api(),7,13));assert(f.factory.construct());assert(!f.factory.release());assert(f.destroyed==1);assert(f.factory.release());assert(f.destroyed==13&&f.roots.empty());++scenarios;}
    {Fixture f;f.handoff=true;assert(f.factory.begin(f.api(),7,13));assert(!f.factory.construct());void* fresh0=f.current_arrays[0];void* fresh1=f.current_arrays[1];assert(f.factory.release());assert(f.current_arrays[0]==fresh0&&f.current_arrays[1]==fresh1&&f.destroyed==4&&f.roots.empty());++scenarios;}
    {Fixture f;assert(f.factory.begin(f.api(),7,13));f.current_arrays[0]=f.make(Object::array);f.current_arrays[1]=f.make(Object::array);f.static_fail=1;assert(!f.factory.restore_static());const int sets=f.static_sets;f.thread=false;f.factory.abandon_static_before_source_change();assert(f.static_sets==sets);f.thread=true;void* fresh0=f.make(Object::array);void* fresh1=f.make(Object::array);f.current_arrays[0]=fresh0;f.current_arrays[1]=fresh1;assert(!f.factory.restore_static()&&!f.factory.static_restored());f.fenced=false;assert(!f.factory.release()&&!f.roots.empty());f.fenced=true;assert(f.factory.release());assert(f.current_arrays[0]==fresh0&&f.current_arrays[1]==fresh1&&f.roots.empty());++scenarios;}
    for(int fail=1;fail<=6;++fail){Fixture f;f.deny_retain=fail;bool begun=f.factory.begin(f.api(),7,13);if(begun)assert(!f.factory.construct());assert(f.factory.release());assert(f.created==f.destroyed&&f.roots.empty());++scenarios;}
    for(int failure=0;failure<3;++failure){Fixture f;if(failure==0)f.admitted=false;if(failure==1)f.routes=false;if(failure==2)f.thread=false;assert(!f.factory.begin(f.api(),7,13)&&!f.constructor_calls&&!f.created);f.routes=f.thread=true;assert(f.factory.release());f.originals_restored();++scenarios;}
    std::printf("%u bounded private constructor scenarios passed; no GPU/full-renderer claim\n",scenarios);
}
