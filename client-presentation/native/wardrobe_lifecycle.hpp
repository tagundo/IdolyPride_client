#pragma once
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <cstdio>
#include "orientation.hpp"

namespace idoly::presentation::wardrobe {
using Method = const void;
using Task = orientation::UniTask;
using Token = orientation::CancellationToken;
using Show = Task (*)(void *, Token, Method *);
using Move = void (*)(void *, Method *);
using Fail = void (*)(void *, void *, Method *);
using Wait = Task (*)(void *, int, Token, Method *);
using Yield = Task (*)(int, Token, Method *);
struct Calls {
    uint32_t (*weak_new)(void *, bool) = nullptr;
    void *(*weak_get)(uint32_t) = nullptr;
    void (*weak_free)(uint32_t) = nullptr;
    bool (*alive)(void *, Method *) = nullptr;
    bool (*active)(void *, Method *) = nullptr;
    bool (*matches)(void *, const char *, const char *) = nullptr;
    Yield yield = nullptr;
    void *hide_predicate = nullptr;
    void (*event)(const char *) = nullptr;
};
struct Snapshot {
    const char *phase="idle";
    int64_t failures=0, releases=0, sequence=0, sampled_ms=-1;
};
class Tracker {
    Snapshot state_{};
    static int64_t increment(int64_t value) { return value<INT64_MAX ? value+1 : INT64_MAX; }
public:
    void event(const char *phase, int64_t now) {
        if (!phase || now<0) return;
        const bool failed=!std::strcmp(phase,"show_failed"), released=!std::strcmp(phase,"hide_wait_released");
        if (!failed && !released && std::strcmp(phase,"show_begin") && std::strcmp(phase,"owner_closed")) return;
        state_.phase=phase; state_.sequence=increment(state_.sequence); state_.sampled_ms=now;
        if (failed) state_.failures=increment(state_.failures);
        if (released) state_.releases=increment(state_.releases);
    }
    Snapshot snapshot() const { return state_; }
    static void json(const Snapshot &state, int64_t now, char *output, size_t capacity) {
        char age[32]; const bool has_age=state.sequence>0 && state.sampled_ms>=0 && now>=state.sampled_ms;
        if (has_age) std::snprintf(age,sizeof age,"%lld",static_cast<long long>(now-state.sampled_ms));
        else std::snprintf(age,sizeof age,"null");
        std::snprintf(output,capacity,"{\"schema\":1,\"phase\":\"%s\",\"show_failures\":%lld,"
            "\"released_waits\":%lld,\"sequence\":%lld,\"sample_age_ms\":%s}",state.phase,
            static_cast<long long>(state.failures),static_cast<long long>(state.releases),
            static_cast<long long>(state.sequence),age);
    }
};

// No task is retained or consumed here. All slots are weak and only touched
// by the established Unity callback thread. Original task and exception paths
// stay intact; only an impossible wait after an observed outer Show failure
// is replaced by the original cancellable scheduler operation.
class Lifecycle {
    struct Slot { uint32_t owner=0, view=0; uint64_t generation=0; bool started=false, failed=false; };
    struct Frame {
        Lifecycle *helper; Frame *previous; void *state; uint64_t generation; size_t slot;
    };
    inline static thread_local Frame *frame_ = nullptr;
    Calls api_{};
    Slot slots_[2]{};
    uint64_t next_ = 0;
    template<class T> static T field(void *self, size_t offset) {
        T result{}; std::memcpy(&result, static_cast<const char *>(self)+offset, sizeof result); return result;
    }
    void event(const char *phase) { if (api_.event) api_.event(phase); }
    void clear(size_t index, bool closed) {
        Slot &slot=slots_[index]; const bool existed=slot.owner || slot.view;
        if (slot.owner) api_.weak_free(slot.owner);
        if (slot.view) api_.weak_free(slot.view);
        slot={}; if (closed && existed) event("owner_closed");
    }
    bool valid(size_t index) {
        Slot &slot=slots_[index];
        void *owner=slot.owner ? api_.weak_get(slot.owner) : nullptr;
        void *view=slot.view ? api_.weak_get(slot.view) : nullptr;
        if (!owner || !view || !api_.alive(owner,nullptr) || !api_.alive(view,nullptr)
                || !api_.active(owner,nullptr) || field<void *>(owner,0x70)!=view) {
            clear(index,true); return false;
        }
        return true;
    }
    bool current(const Frame &frame) {
        return frame.helper==this && slots_[frame.slot].generation==frame.generation && valid(frame.slot);
    }
    void failed(Frame &frame) {
        if (!current(frame) || !slots_[frame.slot].started || slots_[frame.slot].failed) return;
        slots_[frame.slot].failed=true; event("show_failed");
    }
    struct Scope {
        Frame frame;
        Scope(Lifecycle *helper, void *state, uint64_t generation, size_t slot)
            : frame{helper,frame_,state,generation,slot} { frame_=&frame; }
        ~Scope() { frame_=frame.previous; }
        Scope(const Scope &)=delete; Scope &operator=(const Scope &)=delete;
    };
public:
    bool ready() const { return api_.weak_new && api_.weak_get && api_.weak_free && api_.alive
        && api_.active && api_.matches && api_.yield && api_.hide_predicate; }
    void configure(const Calls &api) {
        for (size_t i=0;i<2;++i) if (slots_[i].owner || slots_[i].view) clear(i,false);
        api_=api;
    }
    void cleanup() { if (ready()) for (size_t i=0;i<2;++i) if (slots_[i].owner || slots_[i].view) valid(i); }
    void register_owner(void *self) {
        if (!ready() || !self || !api_.alive(self,nullptr)
                || !api_.matches(self,"Solis.OutGame","CharacterCostumeScreenView")) return;
        void *view=field<void *>(self,0x70);
        if (!view || !api_.alive(view,nullptr)
                || !api_.matches(view,"Solis.OutGame","LoadingCharacter3DView")) return;
        cleanup();
        size_t index=2;
        for (size_t i=0;i<2;++i) if (slots_[i].owner && api_.weak_get(slots_[i].owner)==self) { index=i; break; }
        if (index==2) for (size_t i=0;i<2;++i) if (!slots_[i].owner) { index=i; break; }
        if (index==2) index=slots_[0].generation<=slots_[1].generation ? 0 : 1;
        clear(index,false);
        if (next_==UINT64_MAX) { for (size_t i=0;i<2;++i) clear(i,false); next_=0; }
        Slot &slot=slots_[index];
        slot.owner=api_.weak_new(self,false); slot.view=api_.weak_new(view,false); slot.generation=++next_;
        if (!slot.owner || !slot.view) clear(index,false);
    }
    Task show(void *self, Token token, Method *method, Show original, bool enabled) {
        if (enabled) { try { register_owner(self); } catch (...) {} }
        return original(self,token,method);
    }
    void move(void *self, Method *method, Move original, bool enabled) {
        if (!enabled || !self || !ready()) { original(self,method); return; }
        cleanup(); void *view=field<void *>(self,0x18);
        for (size_t i=0;i<2;++i) {
            Slot &slot=slots_[i];
            if (!slot.view || api_.weak_get(slot.view)!=view) continue;
            const bool initial=field<int>(self,0)==-1;
            const bool local_initial=initial && !field<void *>(self,8);
            if (initial) {
                // A new Loading.Show can start within the same screen's
                // ShowAnimation lifetime. Invalidate the old TLS generation.
                if (next_==UINT64_MAX) {
                    for (size_t j=0;j<2;++j) clear(j,false);
                    next_=0; original(self,method); return;
                }
                slot.generation=++next_; slot.started=true; slot.failed=false; event("show_begin");
            }
            Scope scope(this,self,slot.generation,i);
            original(self,method);
            // Only the wrapper's initial stack state may be read after return.
            // Resumed pooled runner state can be recycled inline: never read it.
            if (local_initial && current(scope.frame) && field<int>(self,0)==-2
                    && !field<void *>(self,8) && field<void *>(self,16)) failed(scope.frame);
            return;
        }
        original(self,method);
    }
    void fail(void *self, void *exception, Method *method, Fail original, bool enabled) {
        Frame *frame=frame_;
        try {
            if (enabled && self && exception && frame && frame->helper==this && current(*frame)
                    && field<int>(frame->state,0)==-2 && field<void *>(frame->state,8)==self)
                failed(*frame); // Before original: it can synchronously resume Hide.
        } catch (...) {} // Added observation must not prevent original exception delivery.
        original(self,exception,method);
    }
    Task wait(void *predicate, int timing, Token token, Method *method, Wait original, bool enabled) {
        if (enabled && predicate && ready()
                && field<void *>(predicate,0x10)==api_.hide_predicate
                && api_.matches(predicate,"System","Func`1")) {
            cleanup(); void *view=field<void *>(predicate,0x20);
            for (size_t i=0;i<2;++i) {
                const Slot &slot=slots_[i];
                if (slot.view && api_.weak_get(slot.view)==view && slot.started && slot.failed
                        && !field<bool>(view,0x48)) {
                    // REAL original operation, same timing and token. It does
                    // not consume/synthesize the outer Show or Hide task.
                    Task result=api_.yield(timing,token,nullptr);
                    event("hide_wait_released"); return result;
                }
            }
        }
        return original(predicate,timing,token,method);
    }
};
} // namespace idoly::presentation::wardrobe
