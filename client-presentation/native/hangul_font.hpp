#pragma once
#ifndef IDOLY_DARWIN_BRIDGE
#include <cstddef>
#include <cstdint>
#include <cstring>
#endif

namespace idoly::presentation::hangul_font {
using Method = const void;
using Awake = void (*)(void *, Method *);
struct FactoryCalls {
    void *(*object_class)(void *) = nullptr;
    void *(*field)(void *, const char *) = nullptr;
    const void *(*field_type)(void *) = nullptr;
    void *(*class_from_type)(const void *) = nullptr;
    void *(*object_new)(void *) = nullptr;
    Method *(*method)(void *, const char *, int32_t) = nullptr;
    uint32_t (*strong_new)(void *, bool) = nullptr;
    void (*release)(uint32_t) = nullptr;
    void *(*get)(void *, Method *) = nullptr;
    void (*set)(void *, void *, Method *) = nullptr;
};

// Resolve the actual closed List<TMP_FontAsset> field type, not a guessed
// generic class or an uninitialized native buffer. Only immutable metadata is
// cached. A new managed list stays strongly rooted through its constructor and
// setter, including an exception from either operation.
class ListFactory {
    using Constructor = void (*)(void *, Method *);
    struct Entry { void *owner=nullptr, *type=nullptr; Method *ctor=nullptr; Constructor call=nullptr; };
    FactoryCalls api_{};
    Entry entries_[4]{};
public:
    void configure(const FactoryCalls &api) { api_=api;for (auto &entry:entries_) entry={}; }
    bool ready() const {
        return api_.object_class && api_.field && api_.field_type && api_.class_from_type
            && api_.object_new && api_.method && api_.strong_new && api_.release && api_.get && api_.set;
    }
    void *ensure(void *font) {
        if (!font || !ready()) return nullptr;
        if (void *present=api_.get(font,nullptr)) return present;
        void *owner=api_.object_class(font);
        if (!owner) return nullptr;
        Entry *cached=nullptr;
        for (auto &entry:entries_) if (entry.owner==owner) { cached=&entry;break; }
        if (!cached) for (auto &entry:entries_) if (!entry.owner) {
            void *field=api_.field(owner,"m_FallbackFontAssetTable");
            const void *field_type=field ? api_.field_type(field) : nullptr;
            void *type=field_type ? api_.class_from_type(field_type) : nullptr;
            Method *ctor=type ? api_.method(type,".ctor",0) : nullptr;
            Constructor call=nullptr;
            if (ctor) ::memcpy(&call,ctor,sizeof call);
            if (!call) return nullptr;
            entry={owner,type,ctor,call};cached=&entry;break;
        }
        if (!cached) return nullptr;
        void *list=api_.object_new(cached->type);
        if (!list) return nullptr;
        const uint32_t handle=api_.strong_new(list,false);
        if (!handle) return nullptr;
        struct Root {
            uint32_t handle; void (*release)(uint32_t);
            ~Root() { release(handle); }
        } root{handle,api_.release};
        cached->call(list,cached->ctor);
        api_.set(font,list,nullptr);
        return api_.get(font,nullptr)==list ? list : nullptr;
    }
};

struct Calls {
    uint32_t (*strong_new)(void *, bool) = nullptr;
    uint32_t (*weak_new)(void *, bool) = nullptr;
    void *(*target)(uint32_t) = nullptr;
    void (*release)(uint32_t) = nullptr;
    bool (*alive)(void *, Method *) = nullptr;
    bool (*named)(void *, const char *) = nullptr;
    int32_t (*get_flags)(void *, Method *) = nullptr;
    void (*set_flags)(void *, int32_t, Method *) = nullptr;
    void (*set_multi_atlas)(void *, bool, Method *) = nullptr;
    void (*clear_data)(void *, bool, Method *) = nullptr;
    void *(*fallbacks)(void *, Method *) = nullptr;
    // Must preserve existing entries, suppress duplicates, and insert first.
    bool (*insert_first)(void *, void *) = nullptr;
    void *(*ensure_fallbacks)(void *) = nullptr;
};

// Called only after the original TMP_FontAsset.Awake on its Unity callback
// thread. No frame callback, resource scan, font-file IO or translation lookup
// is involved. One protected source font is strong-rooted; other assets use
// bounded weak identities so unloading an asset cannot leave a native pointer.
class Fallback {
    struct Slot { uint32_t handle=0; uint64_t generation=0; };
    static constexpr size_t capacity_=512;
    static constexpr size_t face_=0x50, numeric_=0x18, numeric_size_=0x48;
    static constexpr int32_t dont_unload_=32;
    Calls api_{};
    Slot slots_[capacity_]{};
    uint32_t source_=0, reference_=0;
    uint64_t generation_=0;
    size_t observed_=0, applied_=0;
    bool active_=false, inside_=false, failed_=false;
    void release(uint32_t &handle) {
        if (handle && api_.release) api_.release(handle);
        handle=0;
    }
    void *live(uint32_t handle) const {
        void *value=handle && api_.target ? api_.target(handle) : nullptr;
        return value && api_.alive && api_.alive(value,nullptr) ? value : nullptr;
    }
    size_t track(void *font) {
        size_t free=capacity_;
        for (size_t i=0;i<capacity_;++i) {
            void *current=live(slots_[i].handle);
            if (current==font) return i;
            if (!current) {
                release(slots_[i].handle); slots_[i].generation=0;
                if (free==capacity_) free=i;
            }
        }
        if (free==capacity_) return free;
        slots_[free].handle=api_.weak_new(font,false);
        if (!slots_[free].handle) return capacity_;
        ++observed_;return free;
    }
    void inject(void *font, Slot *slot) {
        void *source=live(source_);
        if (!active_ || !source || !font || font==source
                || (slot && slot->generation==generation_)) return;
        void *list=api_.fallbacks(font,nullptr);
        if (!list && api_.ensure_fallbacks) list=api_.ensure_fallbacks(font);
        if (!list || !api_.insert_first(list,source)) return;
        if (slot) slot->generation=generation_;
        ++applied_;
    }
    void activate() {
        void *source=live(source_), *reference=live(reference_);
        if (active_ || !source || !reference) return;
        // Both offsets are independently registered in the original Android
        // and iOS metadata. A missing/static source remains pending, never
        // receives a misleading successful activation or a dynamic clear.
        int32_t mode=0;void *source_font=nullptr;
        ::memcpy(&mode,static_cast<const char *>(source)+0x48,sizeof mode);
        ::memcpy(&source_font,static_cast<const char *>(source)+0x40,sizeof source_font);
        if (mode!=1 || !source_font) return;
        // Preserve every other HideFlags bit. A managed GC root alone does
        // not promise retention by Unity's UnloadUnusedAssets sweep.
        const int32_t flags=api_.get_flags(source,nullptr);
        api_.set_flags(source,flags|dont_unload_,nullptr);
        // Preserve the source's managed family/style references. Only the
        // version-verified numeric FaceInfo range is copied from Solis.
        ::memcpy(static_cast<char *>(source)+face_+numeric_,
                 static_cast<const char *>(reference)+face_+numeric_,numeric_size_);
        api_.set_multi_atlas(source,true,nullptr);
        api_.clear_data(source,false,nullptr);
        active_=true;
        for (size_t i=0;i<capacity_;++i) inject(live(slots_[i].handle),&slots_[i]);
    }
    void observe(void *font) {
        if (!font || !ready() || inside_ || !api_.alive(font,nullptr)) return;
        struct Scope { bool &value; Scope(bool &value):value(value){value=true;} ~Scope(){value=false;} } scope(inside_);
        if (source_ && !live(source_)) { release(source_);active_=false; }
        const size_t index=track(font);
        // The original SourceSansPro asset contains the game's two/three-em
        // dash glyphs. Only the separate Korean asset may be cleared.
        if (api_.named(font,"Pretendard JP SemiBold SDF") && live(source_)!=font) {
            release(source_);source_=api_.strong_new(font,false);active_=false;
            if (++generation_==0) {
                generation_=1;
                for (auto &slot:slots_) slot.generation=0;
            }
        } else if (api_.named(font,"Solis-MK5 SDF") && live(reference_)!=font) {
            release(reference_);reference_=api_.weak_new(font,false);
        }
        activate();
        if (active_) inject(font,index<capacity_ ? &slots_[index] : nullptr);
    }
public:
    void clear() {
        for (auto &slot:slots_) { release(slot.handle);slot.generation=0; }
        release(source_);release(reference_);
        generation_=0;observed_=applied_=0;active_=inside_=failed_=false;
    }
    void configure(const Calls &api) { clear();api_=api; }
    bool ready() const {
        return api_.strong_new && api_.weak_new && api_.target && api_.release
            && api_.alive && api_.named && api_.get_flags && api_.set_flags
            && api_.set_multi_atlas && api_.clear_data && api_.fallbacks && api_.insert_first;
    }
    void after_original(void *font) {
        try { observe(font); }
        catch (...) { active_=false;failed_=true; } // Added fallback work must fail open.
    }
    void awake(void *font, Method *method, Awake original) {
        if (!original) return;
        original(font,method); // Original arguments, exceptions and side effects remain first.
        after_original(font);
    }
    // Hook installation alone is not evidence that a Korean fallback is usable.
    bool activated() const { return active_ && applied_>0; }
    bool failed() const { return failed_; }
    size_t applied() const { return applied_; }
    size_t observed() const { return observed_; }
};
} // namespace idoly::presentation::hangul_font
