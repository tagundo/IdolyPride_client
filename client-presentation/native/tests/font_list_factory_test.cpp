#include "../hangul_font.hpp"
#include <cassert>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>
using namespace idoly::presentation::hangul_font;
struct List { bool initialized=false; };
struct Font { void *owner=nullptr; List *list=nullptr; };
struct Info { void (*pointer)(void *,Method *); int tag=712; };
static int field_token,type_token,closed_class,owner_tokens[5];
static std::map<uint32_t,void *> roots;
static std::vector<std::unique_ptr<List>> allocated;
static unsigned resolve_count=0,ctor_count=0,set_count=0;
static bool fail_field=false,fail_type=false,fail_class=false,fail_method=false;
static bool fail_new=false,fail_root=false,throw_ctor=false,throw_set=false,drop_set=false;
static void *owner(void *font) { return static_cast<Font *>(font)->owner; }
static void *field(void *,const char *name) { ++resolve_count;assert(std::string(name)=="m_FallbackFontAssetTable");return fail_field ? nullptr : &field_token; }
static const void *type(void *value) { assert(value==&field_token);return fail_type ? nullptr : &type_token; }
static void *klass(const void *value) { assert(value==&type_token);return fail_class ? nullptr : &closed_class; }
static void ctor(void *value,Method *method);
static Info info{ctor};
static Method *method(void *value,const char *name,int32_t count) {
    assert(value==&closed_class && std::string(name)==".ctor" && count==0);return fail_method ? nullptr : &info;
}
static void *create(void *value) {
    assert(value==&closed_class);if (fail_new) return nullptr;
    allocated.emplace_back(new List);return allocated.back().get();
}
static uint32_t strong(void *value,bool pinned) {
    assert(!pinned && roots.empty());if (fail_root) return 0;roots[1]=value;return 1;
}
static void release(uint32_t value) { assert(value==1 && roots.erase(value)==1); }
static void ctor(void *value,Method *metadata) {
    assert(metadata==&info && roots.size()==1 && roots[1]==value);++ctor_count;
    if (throw_ctor) throw std::runtime_error("managed constructor");
    static_cast<List *>(value)->initialized=true;
}
static void *get(void *font,Method *metadata) { assert(metadata==nullptr);return static_cast<Font *>(font)->list; }
static void set(void *font,void *value,Method *metadata) {
    assert(metadata==nullptr && roots.size()==1 && roots[1]==value && static_cast<List *>(value)->initialized);++set_count;
    if (throw_set) throw std::runtime_error("managed setter");
    if (!drop_set) static_cast<Font *>(font)->list=static_cast<List *>(value);
}
static FactoryCalls calls() { return {owner,field,type,klass,create,method,strong,release,get,set}; }
static void reset() {
    assert(roots.empty());resolve_count=ctor_count=set_count=0;
    fail_field=fail_type=fail_class=fail_method=fail_new=fail_root=throw_ctor=throw_set=drop_set=false;
}
int main() {
    ListFactory factory;factory.configure(calls());assert(factory.ready());
    Font a{&owner_tokens[0]},b{&owner_tokens[0]};
    void *created=factory.ensure(&a);assert(created && created==a.list && a.list->initialized && roots.empty());
    assert(resolve_count==1 && ctor_count==1 && set_count==1);
    assert(factory.ensure(&a)==created && resolve_count==1 && ctor_count==1);
    assert(factory.ensure(&b) && b.list!=a.list && resolve_count==1 && ctor_count==2 && roots.empty());
    for (bool *flag:{&throw_ctor,&throw_set}) {
        *flag=true;Font fresh{&owner_tokens[0]};
        try { factory.ensure(&fresh);assert(false); } catch (const std::runtime_error &) {}
        assert(roots.empty() && !fresh.list);*flag=false;
    }
    for (bool *flag:{&fail_field,&fail_type,&fail_class,&fail_method,&fail_new,&fail_root,&drop_set}) {
        reset();factory.configure(calls());*flag=true;Font fresh{&owner_tokens[0]};
        assert(!factory.ensure(&fresh) && !fresh.list && roots.empty());
    }
    reset();factory.configure(calls());
    for (unsigned i=0;i<5;++i) { Font fresh{&owner_tokens[i]};assert(bool(factory.ensure(&fresh))==(i<4)); }
    assert(resolve_count==4 && ctor_count==4 && roots.empty());
    auto incomplete=calls();incomplete.object_new=nullptr;factory.configure(incomplete);
    Font missing{&owner_tokens[0]};assert(!factory.ready() && !factory.ensure(&missing) && roots.empty());
    assert(!factory.ensure(nullptr));
}
