#include "../hangul_font.hpp"
#include <algorithm>
#include <cassert>
#include <map>
#include <stdexcept>
#include <string>
#include <vector>

using namespace idoly::presentation::hangul_font;
struct Font {
    unsigned char storage[0x200]{};
    std::string name;
    bool native=true, gc=true, table=true, throw_name=false;
    int flags=1, originals=0, clear=0, multi=0, inserts=0, flags_set=0;
    std::vector<void *> fallback;
    explicit Font(const char *name):name(name) {
        const int32_t dynamic=1;void *file=this;
        std::memcpy(storage+0x48,&dynamic,sizeof dynamic);std::memcpy(storage+0x40,&file,sizeof file);
    }
};
struct Handle { Font *font; bool weak; };
static std::map<uint32_t,Handle> handles;
static uint32_t next_handle=1;
static bool throw_original=false;
static const void *seen_method=nullptr;
static size_t strong_count=0, weak_count=0;
static uint32_t strong_new(void *font,bool pinned) {
    assert(!pinned);++strong_count;const uint32_t id=next_handle++;
    handles.emplace(id,Handle{static_cast<Font *>(font),false});return id;
}
static uint32_t weak_new(void *font,bool track_resurrection) {
    assert(!track_resurrection);++weak_count;const uint32_t id=next_handle++;
    handles.emplace(id,Handle{static_cast<Font *>(font),true});return id;
}
static void *target(uint32_t id) {
    const auto row=handles.find(id);assert(row!=handles.end());
    return row->second.weak && !row->second.font->gc ? nullptr : row->second.font;
}
static void release(uint32_t id) { assert(handles.erase(id)==1); }
static bool alive(void *font,const void *) { return static_cast<Font *>(font)->native; }
static bool named(void *value,const char *name) {
    Font &font=*static_cast<Font *>(value);assert(font.originals>0);
    if (font.throw_name) throw std::runtime_error("new fallback work");
    return font.name==name;
}
static int32_t get_flags(void *font,const void *) { return static_cast<Font *>(font)->flags; }
static void set_flags(void *font,int32_t flags,const void *) {
    Font &row=*static_cast<Font *>(font);row.flags=flags;++row.flags_set;
}
static void multi(void *font,bool enabled,const void *) {
    assert(enabled);++static_cast<Font *>(font)->multi;
}
static void clear(void *font,bool atlas_to_zero,const void *) {
    assert(!atlas_to_zero);++static_cast<Font *>(font)->clear;
}
static void *fallbacks(void *font,const void *) {
    Font &row=*static_cast<Font *>(font);return row.table ? &row.fallback : nullptr;
}
static bool insert(void *list,void *font) {
    auto &rows=*static_cast<std::vector<void *> *>(list);
    if (std::find(rows.begin(),rows.end(),font)==rows.end()) rows.insert(rows.begin(),font);
    return true;
}
static void original(void *font,const void *method) {
    seen_method=method;
    if (throw_original) throw std::runtime_error("original Awake");
    if (font) ++static_cast<Font *>(font)->originals;
}
static Calls calls() {
    return {strong_new,weak_new,target,release,alive,named,get_flags,set_flags,multi,clear,fallbacks,insert};
}
static void *restore_table(void *font) {
    auto &row=*static_cast<Font *>(font);assert(!row.table);row.table=true;return &row.fallback;
}
static void nullable_lists_are_created_without_another_awake() {
    Fallback helper;auto api=calls();api.ensure_fallbacks=restore_table;helper.configure(api);
    Font source("Pretendard JP SemiBold SDF"),solis("Solis-MK5 SDF"),pending("Story SDF");
    solis.table=pending.table=false;
    helper.awake(&pending,nullptr,original);helper.awake(&source,nullptr,original);helper.awake(&solis,nullptr,original);
    assert(helper.activated() && solis.table && pending.table);
    assert(solis.fallback==std::vector<void *>{&source} && pending.fallback==std::vector<void *>{&source});
    assert(pending.originals==1);helper.clear();assert(handles.empty());
}
static void run(bool source_first) {
    Fallback helper;helper.configure(calls());assert(helper.ready());
    Font source("Pretendard JP SemiBold SDF"),solis("Solis-MK5 SDF"),other("StoryTitle SDF"),existing("other fallback");
    std::fill(std::begin(source.storage),std::end(source.storage),0x11);
    std::fill(std::begin(solis.storage),std::end(solis.storage),0x55);
    const int32_t dynamic=1;void *file=&source;
    std::memcpy(source.storage+0x48,&dynamic,sizeof dynamic);std::memcpy(source.storage+0x40,&file,sizeof file);
    unsigned char expected[sizeof source.storage];std::memcpy(expected,source.storage,sizeof expected);
    other.fallback.push_back(&existing);
    const int marker=42;
    helper.awake(&other,&marker,original);assert(seen_method==&marker && !helper.activated());
    helper.awake(source_first ? &source : &solis,&marker,original);assert(!helper.activated());
    helper.awake(source_first ? &solis : &source,&marker,original);assert(helper.activated());
    assert(source.flags==33 && source.flags_set==1 && source.multi==1 && source.clear==1);
    for (size_t i=0;i<sizeof source.storage;++i)
        assert(source.storage[i]==(i>=0x68 && i<0xb0 ? 0x55 : expected[i]));
    assert(source.fallback.empty());
    assert(solis.fallback==std::vector<void *>{&source});
    assert(other.fallback==std::vector<void *>({&source,&existing}));
    const size_t applied=helper.applied();
    helper.awake(&other,&marker,original);helper.awake(&source,&marker,original);
    helper.awake(&solis,&marker,original);
    assert(helper.applied()==applied && source.flags_set==1 && source.clear==1);
    Font later("Subtitle SDF");helper.awake(&later,nullptr,original);
    assert(later.fallback==std::vector<void *>{&source});
    // A missing list remains intact and can be retried after its own Awake.
    Font pending("Pending SDF");pending.table=false;helper.awake(&pending,nullptr,original);
    assert(pending.fallback.empty());pending.table=true;helper.awake(&pending,nullptr,original);
    assert(pending.fallback==std::vector<void *>{&source});
    // Native destruction and managed collection are independent, and neither
    // is treated as a live font merely because its old handle still exists.
    other.native=false;later.gc=false;
    Font replacement("Next Scene SDF");helper.awake(&replacement,nullptr,original);
    assert(replacement.fallback==std::vector<void *>{&source});
    // An externally destroyed source must be re-rooted/rebuilt, never reused.
    source.native=false;
    Font source2("Pretendard JP SemiBold SDF");helper.awake(&source2,nullptr,original);
    assert(source2.flags==33 && source2.clear==1 && helper.activated());
    assert(replacement.fallback.front()==&source2);
    helper.clear();assert(handles.empty());
}
static void original_symbol_font_is_never_activated_or_cleared() {
    Fallback helper;helper.configure(calls());
    Font symbols("SourceSansPro-Regular SDF"),solis("Solis-MK5 SDF"),source("Pretendard JP SemiBold SDF");
    helper.awake(&symbols,nullptr,original);helper.awake(&solis,nullptr,original);
    assert(!helper.activated() && symbols.clear==0 && symbols.multi==0 && symbols.flags_set==0);
    helper.awake(&source,nullptr,original);
    assert(helper.activated() && source.clear==1);
    assert(symbols.clear==0 && symbols.multi==0 && symbols.flags_set==0);
    assert(symbols.fallback==std::vector<void *>{&source} && source.fallback.empty());
    helper.clear();assert(handles.empty());
}
static void exceptions() {
    Fallback helper;helper.configure(calls());Font font("Solis-MK5 SDF");
    throw_original=true;
    try { helper.awake(&font,nullptr,original);assert(false); }
    catch (const std::runtime_error &) {}
    throw_original=false;assert(font.originals==0 && handles.empty() && helper.observed()==0);
    font.throw_name=true;helper.awake(&font,nullptr,original);
    assert(font.originals==1 && helper.failed() && !helper.activated());
    helper.clear();assert(handles.empty());
    Calls incomplete=calls();incomplete.set_flags=nullptr;helper.configure(incomplete);
    helper.awake(&font,nullptr,original);assert(font.originals==2 && handles.empty() && !helper.ready());
}
static void bounded() {
    Fallback helper;helper.configure(calls());std::vector<Font *> fonts;
    for (int i=0;i<600;++i) {
        fonts.push_back(new Font("other font"));helper.awake(fonts.back(),nullptr,original);
    }
    assert(handles.size()==512);
    Font solis("Solis-MK5 SDF"),source("Pretendard JP SemiBold SDF");
    helper.awake(&solis,nullptr,original);helper.awake(&source,nullptr,original);
    assert(helper.activated() && handles.size()==514);
    assert(fonts.front()->fallback.front()==&source);
    helper.awake(fonts.back(),nullptr,original);assert(fonts.back()->fallback.front()==&source);
    helper.clear();assert(handles.empty());
    for (auto *font:fonts) delete font;
}
static void pending_until_registered() {
    Fallback helper;helper.configure(calls());
    Font solis("Solis-MK5 SDF"),source("Pretendard JP SemiBold SDF");
    solis.table=false;source.table=false;
    helper.awake(&source,nullptr,original);helper.awake(&solis,nullptr,original);
    assert(source.clear==1 && !helper.activated() && helper.applied()==0);
    Font pending("Pending SDF");helper.awake(&pending,nullptr,original);
    assert(helper.activated() && helper.applied()==1);
    helper.clear();assert(handles.empty());
}
static void missing_or_static_source_remains_pending() {
    Fallback helper;helper.configure(calls());
    Font solis("Solis-MK5 SDF"),source("Pretendard JP SemiBold SDF");
    int32_t mode=0;void *file=nullptr;
    std::memcpy(source.storage+0x48,&mode,sizeof mode);
    helper.awake(&solis,nullptr,original);helper.awake(&source,nullptr,original);
    assert(!helper.activated() && source.clear==0 && source.flags_set==0);
    mode=1;std::memcpy(source.storage+0x48,&mode,sizeof mode);
    std::memcpy(source.storage+0x40,&file,sizeof file);
    helper.awake(&source,nullptr,original);
    assert(!helper.activated() && source.clear==0 && source.flags_set==0);
    file=&source;std::memcpy(source.storage+0x40,&file,sizeof file);
    helper.awake(&source,nullptr,original);
    assert(helper.activated() && source.clear==1 && source.flags_set==1);
    helper.clear();assert(handles.empty());
}
int main() {
    run(false);run(true);exceptions();bounded();pending_until_registered();missing_or_static_source_remains_pending();
    assert(strong_count==7 && weak_count>=512);
    nullable_lists_are_created_without_another_awake();
    original_symbol_font_is_never_activated_or_cleared();
}
