#pragma once
#ifndef IDOLY_DARWIN_BRIDGE
#include <cstddef>
#include <cstdint>
#include <cstring>
#endif

namespace idoly::presentation::sound_persistence {
using Method = const void;
using Bind = void (*)(void *, Method *);
enum class Field : unsigned { BgmVolume, BgmSoundable, SeVolume, SeSoundable, VoiceVolume, VoiceSoundable };
struct Calls {
    uint32_t (*weak_new)(void *, bool) = nullptr;
    void *(*weak_get)(uint32_t) = nullptr;
    void (*weak_free)(uint32_t) = nullptr;
    bool (*matches)(void *, const char *, const char *) = nullptr;
    bool (*alive)(void *, Method *) = nullptr;
    bool (*active)(void *, Method *) = nullptr;
    int64_t (*now_ms)() = nullptr;
    bool (*save)(void *) = nullptr;
};
struct Change {
    void *model = nullptr, *settings = nullptr;
    uint64_t generation = 0;
    uint32_t bits = 0;
    Field field = Field::BgmVolume;
    bool eligible = false;
};

// Main-thread only. Original UI setters still apply sound immediately; this
// tracks an actual preference change and coalesces its original local Save.
// Clean ticks inspect only dirty_, without clocks, handles, Unity or I/O.
class Tracker {
    Calls api_{};
    uint32_t presenter_ = 0, model_ = 0, settings_ = 0, pending_settings_ = 0;
    uint64_t generation_ = 0;
    unsigned binding_depth_ = 0;
    bool dirty_ = false;
    int64_t changed_ms_ = -1, retry_ms_ = -1;
    template<class T> static T field(void *object, size_t offset) {
        T value{}; ::memcpy(&value,static_cast<const char *>(object)+offset,sizeof value);return value;
    }
    static size_t offset(Field f) {
        switch (f) {
        case Field::BgmVolume:return 0x18; case Field::BgmSoundable:return 0x1c;
        case Field::SeVolume:return 0x20; case Field::SeSoundable:return 0x24;
        case Field::VoiceVolume:return 0x28; case Field::VoiceSoundable:return 0x2c;
        }
        return 0;
    }
    static bool volume(Field f) {
        return f==Field::BgmVolume || f==Field::SeVolume || f==Field::VoiceVolume;
    }
    static uint32_t bits(void *settings,Field f) {
        return volume(f)?field<uint32_t>(settings,offset(f)):field<uint8_t>(settings,offset(f));
    }
    static bool valid(void *settings,Field f) {
        if (!offset(f)) return false;
        if (!volume(f)) return field<uint8_t>(settings,offset(f))<=1;
        const float value=field<float>(settings,offset(f));
        return value>=0.f && value<=1.f; // Also rejects NaN/infinity.
    }
    void release(uint32_t &handle) {
        if (handle && api_.weak_free) api_.weak_free(handle);
        handle=0;
    }
    void clear_bound() { release(presenter_);release(model_);release(settings_); }
    void clear_pending() {
        release(pending_settings_);dirty_=false;changed_ms_=retry_ms_=-1;
    }
    bool is_settings(void *p) const {
        return p && api_.matches(p,"Solis.Common","GameSetting");
    }
    void arm(void *presenter) {
        clear_bound();
        if (!ready() || !presenter
                || !api_.matches(presenter,"Solis.OutGame","GameSettingTopScreenPresenter")
                || !api_.matches(presenter,"UnityEngine","Behaviour")
                || !api_.alive(presenter,nullptr)) return;
        void *model=field<void *>(presenter,0xe0);
        if (!model || !api_.matches(model,"Solis.OutGame","GameSettingTopScreenModel")) return;
        void *settings=field<void *>(model,0x18);
        if (!is_settings(settings)) return;
        // A changed model identity must never flush a stale settings object.
        if (dirty_ && api_.weak_get(pending_settings_)!=settings) clear_pending();
        presenter_=api_.weak_new(presenter,false);
        model_=api_.weak_new(model,false);settings_=api_.weak_new(settings,false);
        if (!presenter_ || !model_ || !settings_) clear_bound();
    }
    bool eligible(void *self) const {
        if (binding_depth_ || !self || !presenter_ || !model_ || !settings_
                || api_.weak_get(model_)!=self) return false;
        void *presenter=api_.weak_get(presenter_);
        if (!presenter || !api_.alive(presenter,nullptr) || !api_.active(presenter,nullptr)) return false;
        // Do not treat a released/replaced managed model as a Unity Object.
        void *settings=api_.weak_get(settings_);
        return settings && field<void *>(presenter,0xe0)==self
            && field<void *>(self,0x18)==settings && is_settings(settings);
    }
public:
    static constexpr int64_t QuietMs=400,RetryMs=2000;
    bool ready() const {
        return api_.weak_new && api_.weak_get && api_.weak_free && api_.matches
            && api_.alive && api_.active && api_.now_ms && api_.save;
    }
    void configure(const Calls &api) {
        clear_bound();clear_pending();api_=api;binding_depth_=0;++generation_;
    }
    bool pending() const { return dirty_; }
    void bind(void *self,Method *method,Bind original,bool enabled) {
        if (!original) return;
        if (!enabled || !ready()) { original(self,method);return; }
        struct Scope {
            Tracker &owner;bool completed=false;
            explicit Scope(Tracker &tracker):owner(tracker) {
                // Rebinding is initialization, never a pending user gesture.
                // The original close-save remains responsible for the prior screen.
                if (!owner.binding_depth_) owner.clear_pending();
                ++owner.binding_depth_;++owner.generation_;owner.clear_bound();
            }
            ~Scope() {
                if (!completed) { --owner.binding_depth_;owner.clear_bound(); }
            }
            void finish(void *presenter) {
                --owner.binding_depth_;completed=true;
                if (!owner.binding_depth_) owner.arm(presenter);
            }
        } scope(*this);
        original(self,method); // Initial subscription emissions remain suppressed.
        scope.finish(self);
    }
    Change before(void *self,Field f,bool enabled) const {
        Change result;
        if (!enabled || !ready() || !eligible(self) || !offset(f)) return result;
        void *settings=api_.weak_get(settings_);
        result.model=self;result.settings=settings;result.generation=generation_;
        result.bits=bits(settings,f);result.field=f;result.eligible=true;
        return result;
    }
    void after(void *self,const Change &before,bool enabled) {
        if (!before.eligible || !enabled || before.model!=self || before.generation!=generation_
                || !ready() || !eligible(self)) return;
        void *settings=api_.weak_get(settings_);
        if (settings!=before.settings || !valid(settings,before.field)
                || bits(settings,before.field)==before.bits) return;
        if (!pending_settings_ || api_.weak_get(pending_settings_)!=settings) {
            clear_pending();pending_settings_=api_.weak_new(settings,false);
            if (!pending_settings_) return;
        }
        dirty_=true;changed_ms_=api_.now_ms();retry_ms_=-1;
    }
    void observed_save(void *settings,bool enabled) {
        // Called only AFTER an original Save returned; this is not a disk ACK.
        if (enabled && dirty_ && settings && ready()
                && api_.weak_get(pending_settings_)==settings) clear_pending();
    }
    void tick(bool enabled) {
        if (!dirty_) return;
        if (!enabled || !ready()) return;
        const int64_t now=api_.now_ms();
        if (now<0) return;
        if (changed_ms_<0 || now<changed_ms_) { changed_ms_=now;retry_ms_=-1;return; }
        if (now-changed_ms_<QuietMs || (retry_ms_>=0 && now<retry_ms_)) return;
        void *settings=api_.weak_get(pending_settings_);
        void *model=model_?api_.weak_get(model_):nullptr;
        // The original close-save owns teardown. Never flush an older object
        // after direct replacement/destruction which did not re-run BindData.
        if (!is_settings(settings) || !eligible(model)
                || api_.weak_get(settings_)!=settings) { clear_pending();return; }
        // A new autosave failure is fail-open; the stock close-save stays intact.
        if (api_.save(settings)) clear_pending();
        else retry_ms_=now<=0x7fffffffffffffffLL-RetryMs?now+RetryMs:0x7fffffffffffffffLL;
    }
};
} // namespace idoly::presentation::sound_persistence
