// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once
#ifndef IDOLY_DARWIN_BRIDGE
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <cstdlib>
#endif
#include "mp4_playback_state.hpp"
#include "mp4_actor_state_profile.hpp"

// The original ActorSwing solver advances by its own fixed step even when the
// AnimationStream delta is zero. This worker gate covers both the managed AOT
// ProcessAnimation body and the separate original Burst Execute callback. It
// does not establish ownership or complete Unity jobs: the main-thread owner
// must prove those boundaries before publishing/changing a grant or retiring.
namespace idoly_mp4_actor_placement { struct Address {void* value;}; }
inline void* operator new(size_t,idoly_mp4_actor_placement::Address a)noexcept{return a.value;}
inline void operator delete(void*,idoly_mp4_actor_placement::Address)noexcept{}
namespace idoly_mp4_actor {
constexpr size_t max_owned_jobs = 128;
constexpr size_t list_header_offsets[4] = {0x28, 0x38, 0x48, 0x98};
struct OwnershipKey {
    uintptr_t list_headers[4]{};
    bool valid() const {
        return list_headers[0] || list_headers[1]
            || list_headers[2] || list_headers[3];
    }
    bool operator==(const OwnershipKey& other) const {
        for (size_t i = 0; i < 4; ++i)
            if (list_headers[i] != other.list_headers[i]) return false;
        return true;
    }
};
// A typed original ActorSwingJob receiver is valid native job data. Workers
// read only its four opaque NativeList HEADER identities, never their buffers,
// a managed object header, IL2CPP metadata, or an arbitrary animation-job type.
inline OwnershipKey key_from_original_job(const void* job) {
    OwnershipKey key{};
    if (job) for (size_t i = 0; i < 4; ++i)
        ::memcpy(&key.list_headers[i],
            static_cast<const uint8_t*>(job) + list_header_offsets[i],
            sizeof(uintptr_t));
    return key;
}
enum class GateResult { ok, waiting, invalid, stale, busy };
struct GateStats {
    uint64_t owned_calls = 0, permitted_calls = 0, held_calls = 0,
        duplicate_calls = 0, forwarded_calls = 0;
    uint32_t readers = 0;
};
using ManagedProcess = void (*)(void*, const void*, const void*);
// Execute(ref ActorSwingJob, IntPtr stream, IntPtr methodIndex,
//         ref JobRanges, int jobIndex). The Burst body reads the first three
// arguments, but the hook forwards the original five-argument contract.
using BurstExecute = void (*)(void*, const void*, intptr_t, void*, int32_t);

class WorkerGate {
    static_assert(__atomic_always_lock_free(sizeof(uint64_t), nullptr),
        "Actor worker serials must be lock-free");
    static_assert(__atomic_always_lock_free(sizeof(uint32_t), nullptr),
        "Actor worker reader accounting must be lock-free");
    struct Entry {
        OwnershipKey key{};
        alignas(8) uint64_t consumed_serial = 0;
    };
    struct Registry {
        Entry entries[max_owned_jobs]{};
        size_t count = 0;
        uint64_t owner_epoch = 0;
    };
    Registry registry_{};
    Registry* published_ = nullptr;
    alignas(8) uint64_t grant_ = 0;
    alignas(4) uint32_t readers_ = 0;
    uint64_t owner_epoch_ = 0, last_serial_ = 0;
    bool retiring_ = false;
    alignas(8) uint64_t owned_calls_ = 0, permitted_calls_ = 0,
        held_calls_ = 0, duplicate_calls_ = 0, forwarded_calls_ = 0;

    class Reader {
        WorkerGate& gate_;
    public:
        Registry* registry;
        explicit Reader(WorkerGate& gate) : gate_(gate), registry(nullptr) {
            // Increment BEFORE loading the pointer. Together with the
            // publisher's detach-then-reader-zero sequence, seq_cst prevents
            // an unowned worker from retaining a registry during overwrite.
            __atomic_fetch_add(&gate_.readers_, 1u, __ATOMIC_SEQ_CST);
            registry = __atomic_load_n(&gate_.published_, __ATOMIC_SEQ_CST);
        }
        ~Reader() {
            __atomic_fetch_sub(&gate_.readers_, 1u, __ATOMIC_SEQ_CST);
        }
        Reader(const Reader&) = delete;
        Reader& operator=(const Reader&) = delete;
    };
    bool permit(Registry* registry, const void* typed_job) {
        if (!registry || !typed_job) return true;
        const auto key = key_from_original_job(typed_job);
        Entry* entry = nullptr;
        for (size_t i = 0; i < registry->count; ++i)
            if (registry->entries[i].key == key) {
                entry = &registry->entries[i];
                break;
            }
        if (!entry) return true;
        __atomic_fetch_add(&owned_calls_, uint64_t{1}, __ATOMIC_RELAXED);
        const uint64_t serial = __atomic_load_n(&grant_, __ATOMIC_SEQ_CST);
        if (!serial) {
            __atomic_fetch_add(&held_calls_, uint64_t{1}, __ATOMIC_RELAXED);
            return false;
        }
        uint64_t consumed = __atomic_load_n(&entry->consumed_serial, __ATOMIC_ACQUIRE);
        while (consumed < serial) {
            if (__atomic_compare_exchange_n(&entry->consumed_serial, &consumed,
                    serial, false, __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) {
                __atomic_fetch_add(&permitted_calls_, uint64_t{1}, __ATOMIC_RELAXED);
                return true;
            }
        }
        __atomic_fetch_add(&duplicate_calls_, uint64_t{1}, __ATOMIC_RELAXED);
        return false;
    }
    void forwarded() {
        __atomic_fetch_add(&forwarded_calls_, uint64_t{1}, __ATOMIC_RELAXED);
    }
public:
    WorkerGate() = default;
    WorkerGate(const WorkerGate&) = delete;
    WorkerGate& operator=(const WorkerGate&) = delete;
    // Keep this gate alive for the lifetime of the installed hooks. Registry
    // retirement is explicit and never frees memory beneath a worker reader.

    GateResult publish(const OwnershipKey* keys, size_t count,
            uint64_t owner_epoch, bool original_jobs_fenced) {
        if (!original_jobs_fenced) return GateResult::waiting;
        if (!owner_epoch || !keys || !count || count > max_owned_jobs)
            return GateResult::invalid;
        if (owner_epoch_ || retiring_
            || __atomic_load_n(&published_, __ATOMIC_SEQ_CST))
            return GateResult::busy;
        if (__atomic_load_n(&readers_, __ATOMIC_SEQ_CST)) return GateResult::waiting;
        for (size_t i = 0; i < count; ++i) {
            if (!keys[i].valid()) return GateResult::invalid;
            for (size_t j = 0; j < i; ++j)
                if (keys[i] == keys[j]) return GateResult::invalid;
        }
        for (size_t i = 0; i < count; ++i) {
            registry_.entries[i].key = keys[i];
            __atomic_store_n(&registry_.entries[i].consumed_serial,
                uint64_t{0}, __ATOMIC_RELAXED);
        }
        registry_.count = count;
        registry_.owner_epoch = owner_epoch;
        owner_epoch_ = owner_epoch;
        last_serial_ = 0;
        __atomic_store_n(&grant_, uint64_t{0}, __ATOMIC_SEQ_CST);
        __atomic_store_n(&published_, &registry_, __ATOMIC_SEQ_CST);
        return GateResult::ok;
    }
    GateResult grant(uint64_t serial, uint64_t owner_epoch,
            bool original_jobs_fenced) {
        if (!owner_epoch_ || owner_epoch != owner_epoch_ || retiring_)
            return GateResult::stale;
        if (!original_jobs_fenced) return GateResult::waiting;
        if (!serial || serial <= last_serial_) return GateResult::invalid;
        last_serial_ = serial;
        __atomic_store_n(&grant_, serial, __ATOMIC_SEQ_CST);
        return GateResult::ok;
    }
    // Pure revocation of future worker entry. This is not a job fence and
    // deliberately leaves registry ownership/in-flight retirement duty intact.
    GateResult revoke(uint64_t owner_epoch) {
        if(!owner_epoch_||owner_epoch!=owner_epoch_)return GateResult::stale;
        __atomic_store_n(&grant_,uint64_t{0},__ATOMIC_SEQ_CST);return GateResult::ok;
    }
    // Pure publication observation; callers still need the actual original
    // Animator/job fence. Closed future entry is not worker completion.
    bool held(uint64_t owner_epoch)const{
        const Registry* registry=__atomic_load_n(&published_,__ATOMIC_SEQ_CST);
        return owner_epoch&&owner_epoch==owner_epoch_&&!retiring_&&registry&&registry->owner_epoch==owner_epoch
            &&!__atomic_load_n(&grant_,__ATOMIC_SEQ_CST)&&!__atomic_load_n(&readers_,__ATOMIC_SEQ_CST);
    }
    GateResult hold(uint64_t owner_epoch, bool original_jobs_fenced) {
        if (!owner_epoch_ || owner_epoch != owner_epoch_ || retiring_)
            return GateResult::stale;
        if (!original_jobs_fenced) return GateResult::waiting;
        __atomic_store_n(&grant_, uint64_t{0}, __ATOMIC_SEQ_CST);
        return GateResult::ok;
    }
    GateResult retire(uint64_t owner_epoch, bool original_jobs_fenced) {
        if (!owner_epoch_ || owner_epoch != owner_epoch_) return GateResult::stale;
        if (!original_jobs_fenced) return GateResult::waiting;
        __atomic_store_n(&grant_, uint64_t{0}, __ATOMIC_SEQ_CST);
        __atomic_store_n(&published_, static_cast<Registry*>(nullptr), __ATOMIC_SEQ_CST);
        retiring_ = true;
        if (__atomic_load_n(&readers_, __ATOMIC_SEQ_CST)) return GateResult::waiting;
        registry_.count = 0;
        registry_.owner_epoch = 0;
        owner_epoch_ = last_serial_ = 0;
        retiring_ = false;
        return GateResult::ok;
    }
    // Held ownership is not ordinary playback. After the source becomes stale,
    // detach prevents future callbacks from being suppressed, but the previous
    // epoch remains unreusable until retire(..., true) confirms its own fence.
    // This path touches our publication atomics only; it never touches a scene.
    GateResult detach_stale(uint64_t owner_epoch) {
        if (!owner_epoch_ || owner_epoch != owner_epoch_) return GateResult::stale;
        __atomic_store_n(&grant_, uint64_t{0}, __ATOMIC_SEQ_CST);
        __atomic_store_n(&published_, static_cast<Registry*>(nullptr), __ATOMIC_SEQ_CST);
        retiring_ = true;
        return GateResult::waiting;
    }
    void invoke_managed(ManagedProcess original, void* job,
            const void* stream, const void* method) {
        Reader reader(*this);
        if (original && permit(reader.registry, job)) {
            forwarded();
            original(job, stream, method);
        }
    }
    void invoke_burst(BurstExecute original, void* job, const void* stream,
            intptr_t method_index, void* ranges, int32_t job_index) {
        Reader reader(*this);
        // RootMotion (0) is the original no-op body. Unknown tags must retain
        // the original behavior; neither route reads another job's layout.
        if (original && (static_cast<uint32_t>(method_index) != 1 || permit(reader.registry, job))) {
            forwarded();
            original(job, stream, method_index, ranges, job_index);
        }
    }
    // Main-thread observation after the actual Animator fence. It neither
    // grants a worker nor treats registry publication as completion.
    bool consumed(const OwnershipKey& key,uint64_t epoch,uint64_t serial)const{
        if(!epoch||epoch!=owner_epoch_||!serial)return false;
        const Registry* registry=__atomic_load_n(&published_,__ATOMIC_SEQ_CST);
        if(!registry||registry->owner_epoch!=epoch)return false;
        for(size_t i=0;i<registry->count;++i)if(registry->entries[i].key==key)
            return __atomic_load_n(&registry->entries[i].consumed_serial,__ATOMIC_ACQUIRE)==serial;
        return false;
    }
    GateStats stats() const {
        return {__atomic_load_n(&owned_calls_, __ATOMIC_RELAXED),
            __atomic_load_n(&permitted_calls_, __ATOMIC_RELAXED),
            __atomic_load_n(&held_calls_, __ATOMIC_RELAXED),
            __atomic_load_n(&duplicate_calls_, __ATOMIC_RELAXED),
            __atomic_load_n(&forwarded_calls_, __ATOMIC_RELAXED),
            __atomic_load_n(&readers_, __ATOMIC_SEQ_CST)};
    }
    // Main-thread recovery token. A stale source can release CPU/GC storage,
    // while this persistent gate retains the old epoch's fence duty. A new
    // epoch's fence must never be used to retire it.
    uint64_t pending_retirement_epoch() const { return retiring_ ? owner_epoch_ : 0; }
};

using Result = idoly_mp4_playback::Result;
using Method = void;
struct Handle {
    uintptr_t handle = 0;
    uint32_t version = 0, padding = 0;
};
static_assert(sizeof(Handle) == 16, "Original playable handle ABI");
struct Vector3 { float x = 0, y = 0, z = 0; };
struct Quaternion { float x = 0, y = 0, z = 0, w = 0; };
struct LocalPose { Vector3 position{}; Quaternion rotation{}; Vector3 scale{}; };
struct Owner {
    void* actor = nullptr;
    void* extension = nullptr;
    void* rig = nullptr;
    void* builder = nullptr;
    void* animator = nullptr;
    Handle graph{}, playable{}, output{};
};
// Exact owned Mono callbacks are a different scheduling domain from Animator
// jobs: Time.deltaTime == 0 does not make these original callbacks pure.
enum class MonoPhase : uint8_t { actor_update, actor_late, eye_late, face_late, foot_apply };
using MonoCallback = void (*)(void*, Method*);
struct RandomState { uint32_t words[4]{}; };
struct RandomSuspension { RandomState private_state{};uint64_t epoch=0;uint32_t depth=0;bool active=false; };
struct MonoReceiver { void* object=nullptr; MonoPhase phase=MonoPhase::actor_update; };
// Scalar evidence for a currently entered saved original; ambient RNG isolation
// and a published receiver registry alone are not an invocation receipt.
struct MonoInvocation {
    uint64_t epoch=0,serial=0,invocation=0;void* receiver=nullptr;
    MonoCallback callback=nullptr;MonoPhase phase=MonoPhase::actor_update;uint32_t random_depth=0;
};
constexpr size_t max_mono_receivers=512;
constexpr size_t presentation_max_snapshot_bytes=64u*1024u*1024u;
struct MonoApi {
    bool (*current)(void*)=nullptr;
    bool (*owner_thread)()=nullptr;
    void (*random_get)(RandomState*,Method*)=nullptr;
    void (*random_set)(const RandomState*,Method*)=nullptr;
};
class MonoGate {
    struct Entry { MonoReceiver receiver{};uint64_t consumed=0;MonoCallback nested[3]{};uint8_t nested_count=0; };
    Entry entries_[max_mono_receivers]{};size_t count_=0;
    MonoApi api_{};void* context_=nullptr;uint64_t epoch_=0,serial_=0,last_serial_=0;
    RandomState private_random_{};bool poisoned_=false;uint32_t random_depth_=0;
    RandomState lease_ambient_{};bool rng_active_=false,rng_released_=false;uint32_t rng_suspended_=0;
    struct RenderRandom {uintptr_t key=0;uint64_t serial=0;RandomState seed{};};
    RenderRandom render_random_[8]{};size_t render_random_count_=0;
    void* active_receiver_=nullptr;MonoCallback active_callback_=nullptr;MonoPhase active_phase_=MonoPhase::actor_update;
    uint64_t invocation_sequence_=0,active_invocation_=0;
    const char* error_="none";
public:
    // No current(), owner callback, Unity call, RNG access, or mutation. The host
    // separately checks the owner thread before using this scalar observation.
    bool callbacks_unwound()const noexcept{return !random_depth_&&!active_invocation_&&!active_receiver_&&!active_callback_&&!rng_suspended_;}
    bool invocation(MonoInvocation& value)const{
        value={};
        if(!epoch_||!serial_||serial_!=last_serial_||poisoned_||!active_invocation_
            ||!active_receiver_||!active_callback_||!random_depth_||!rng_active_
            ||rng_released_||rng_suspended_)return false;
        value={epoch_,serial_,active_invocation_,active_receiver_,active_callback_,active_phase_,random_depth_};return true;
    }
    bool publish(MonoApi api,void* context,uint64_t epoch,const MonoReceiver* values,size_t count) {
        if(epoch_||random_depth_||!context||!epoch||!values||!count||count>max_mono_receivers
            ||!api.current||!api.owner_thread||!api.random_get||!api.random_set
            ||!api.owner_thread()||!api.current(context))return false;
        for(size_t i=0;i<count;++i){
            if(!values[i].object)return false;
            for(size_t j=0;j<i;++j)if(values[i].object==values[j].object&&values[i].phase==values[j].phase)return false;
        }
        api_=api;context_=context;epoch_=epoch;count_=count;
        for(size_t i=0;i<count;++i){entries_[i]={};entries_[i].receiver=values[i];}
        api_.random_get(&private_random_,nullptr);
        serial_=last_serial_=0;poisoned_=false;render_random_count_=0;rng_active_=rng_released_=false;rng_suspended_=0;error_="none";return true;
    }
    // Main-thread scalar close only: no owner callback, Unity call or fence.
    bool revoke(uint64_t epoch){if(!epoch_||epoch!=epoch_)return false;serial_=0;return true;}
    bool closed(uint64_t epoch)const{return epoch&&epoch==epoch_&&!serial_&&!active_receiver_;}
    bool hold(uint64_t epoch){
        if(!epoch_||epoch!=epoch_||!api_.owner_thread())return false;
        serial_=0;return true;
    }
    bool grant(uint64_t epoch,uint64_t serial){
        if(!epoch_||epoch!=epoch_||!serial||serial<=last_serial_||poisoned_
            ||!api_.owner_thread()||!api_.current(context_))return false;
        serial_=last_serial_=serial;render_random_count_=0;return true;
    }
    bool current()const{return epoch_&&!poisoned_&&api_.owner_thread()&&api_.current(context_);}
    const char* error()const{return error_;}
    void release(uint64_t epoch){
        if(epoch_==epoch){count_=0;epoch_=serial_=last_serial_=0;context_=nullptr;poisoned_=false;render_random_count_=0;if(!random_depth_){rng_active_=rng_released_=false;rng_suspended_=0;}}
    }
    // Invalidating a source only detaches our scalar registry. It neither calls
    // Unity nor writes the former objects; subsequent normal playback forwards.
    void invalidate(uint64_t epoch){release(epoch);}
    // Before an original selected-scene replacement, return the global RNG
    // lease immediately. The new scene may consume ambient RNG; the old scope
    // must not rewind those new draws when its stack later unwinds.
    void restore_rng_before_source_change(){
        if(rng_active_&&!rng_released_){if(!rng_suspended_)api_.random_set(&lease_ambient_,nullptr);rng_released_=true;}
    }
    // Observer failure fallback: no Unity/current/thread/RNG call is permitted
    // here. Future entry closes, and the old callback finally must never rewind
    // RNG after the original new-scene initializer has been forwarded.
    void abandon_rng_before_source_change(){
        rng_released_=true;poisoned_=true;serial_=0;error_="actor_rng_handoff_abandoned";
    }
    // A nested unrelated camera uses the real ambient stream. The outer lease
    // adopts its advanced state, rather than rewinding unrelated Random draws.
    // Tokens are LIFO; a source handoff withdraws their duty without Unity calls.
    bool suspend_rng_for_unowned(RandomSuspension& token){
        if(token.active)return false;
        token={};
        if(!rng_active_||rng_released_)return true;
        if(!current()){abandon_rng_before_source_change();return false;}
        token.epoch=epoch_;token.depth=rng_suspended_+1;
        if(!rng_suspended_){api_.random_get(&token.private_state,nullptr);api_.random_set(&lease_ambient_,nullptr);}
        ++rng_suspended_;token.active=true;return true;
    }
    bool resume_rng_after_unowned(RandomSuspension& token){
        if(!token.active)return true;
        if(rng_released_||!rng_active_||token.epoch!=epoch_){token.active=false;return false;}
        if(token.depth!=rng_suspended_){abandon_rng_before_source_change();token.active=false;return false;}
        if(!current()){abandon_rng_before_source_change();token.active=false;return false;}
        if(rng_suspended_==1){
            api_.random_get(&lease_ambient_,nullptr);
            api_.random_set(&token.private_state,nullptr);
        }
        --rng_suspended_;token.active=false;return true;
    }
    // The same private stream covers controlled selected RootRebuild /
    // zero-time Evaluate. Nesting within an already isolated owned callback
    // keeps its in-flight state rather than resetting to the previous seed.
    template<class Action> bool isolate(Action action) {
        if(!current()||rng_suspended_){poisoned_=true;serial_=0;error_="actor_mono_owner_changed";return false;}
        if(random_depth_){action();return current();}
        RandomState ambient{};api_.random_get(&ambient,nullptr);
        lease_ambient_=ambient;rng_active_=true;rng_released_=false;
        api_.random_set(&private_random_,nullptr);++random_depth_;
        try {action();if(rng_suspended_)abandon_rng_before_source_change();if(!rng_released_)api_.random_get(&private_random_,nullptr);}
        catch(...) {--random_depth_;if(rng_suspended_)abandon_rng_before_source_change();if(!rng_released_)api_.random_set(&lease_ambient_,nullptr);rng_active_=false;poisoned_=true;serial_=0;error_="actor_mono_callback_exception";throw;}
        --random_depth_;if(!rng_released_)api_.random_set(&lease_ambient_,nullptr);rng_active_=false;
        if(!current()||rng_released_){poisoned_=true;serial_=0;error_="actor_mono_owner_changed";return false;}
        return true;
    }
    template<class Action> bool isolate_preview(Action action){
        if(random_depth_){error_="actor_rng_preview_nested";return false;}
        const RandomState before=private_random_;
        try{const bool ok=isolate(action);private_random_=before;return ok;}
        catch(...){private_random_=before;throw;}
    }
    // The draw gate still permits only one selected render per accepted tick.
    // This seed cache is defense for repeated calls, not permission to advance
    // renderer histories during held retries. Pre-frame-zero draws are preview.
    template<class Action> bool isolate_render(uintptr_t key,Action action){
        if(!current()||!key||rng_suspended_){poisoned_=true;serial_=0;error_="actor_render_rng_owner_changed";return false;}
        RandomState ambient{};api_.random_get(&ambient,nullptr);const bool nested=random_depth_!=0;
        const bool accepted=last_serial_!=0;RenderRandom* record=nullptr;
        if(accepted)for(size_t i=0;i<render_random_count_;++i)if(render_random_[i].key==key&&render_random_[i].serial==last_serial_){record=&render_random_[i];break;}
        const bool fresh=accepted&&!record;
        if(fresh){if(render_random_count_==8){poisoned_=true;serial_=0;error_="actor_render_rng_key_limit";return false;}record=&render_random_[render_random_count_++];record->key=key;record->serial=last_serial_;record->seed=nested?ambient:private_random_;}
        const RandomState seed=record?record->seed:(nested?ambient:private_random_);
        if(!nested){lease_ambient_=ambient;rng_active_=true;rng_released_=false;}
        api_.random_set(&seed,nullptr);++random_depth_;RandomState after{};
        try{action();if(rng_suspended_)abandon_rng_before_source_change();if(!rng_released_)api_.random_get(&after,nullptr);}
        catch(...){--random_depth_;if(rng_suspended_)abandon_rng_before_source_change();if(!rng_released_)api_.random_set(nested?&ambient:&lease_ambient_,nullptr);if(!nested)rng_active_=false;poisoned_=true;serial_=0;error_="actor_render_rng_exception";throw;}
        --random_depth_;
        if(!rng_released_){
            if(fresh){if(!nested){private_random_=after;api_.random_set(&lease_ambient_,nullptr);}}
            else api_.random_set(nested?&ambient:&lease_ambient_,nullptr);
        }
        if(!nested)rng_active_=false;
        if(!current()||rng_released_){poisoned_=true;serial_=0;error_="actor_render_rng_owner_changed";return false;}
        return true;
    }
    void invoke(MonoPhase phase,MonoCallback original,void* receiver,Method* method) {
        if(!original)return;
        Entry* found=nullptr;
        if(epoch_)for(size_t i=0;i<count_;++i)
            if(entries_[i].receiver.object==receiver&&entries_[i].receiver.phase==phase){found=&entries_[i];break;}
        if(!found){
            const uint64_t previous_invocation=active_invocation_;active_invocation_=0;
            try{original(receiver,method);}catch(...){active_invocation_=previous_invocation;throw;}
            active_invocation_=previous_invocation;return;
        }
        if(!api_.owner_thread()||!api_.current(context_)){
            poisoned_=true;serial_=0;error_="actor_mono_owner_changed";return;
        }
        if(!serial_||poisoned_)return;
        if(found->consumed==serial_){
            // The verified derived LateUpdate calls the separately hooked
            // base body. Forward that exact nested route once inside the
            // active root call; a later duplicate remains suppressed.
            if(random_depth_&&active_receiver_==receiver&&active_phase_==phase&&active_callback_!=original){
                bool seen=false;for(size_t i=0;i<found->nested_count;++i)seen|=found->nested[i]==original;
                if(!seen&&found->nested_count<3&&invocation_sequence_!=~uint64_t(0)){
                    found->nested[found->nested_count++]=original;
                    const auto previous_callback=active_callback_;const uint64_t previous_invocation=active_invocation_;
                    active_callback_=original;active_invocation_=++invocation_sequence_;
                    try{original(receiver,method);}catch(...){active_callback_=previous_callback;active_invocation_=previous_invocation;throw;}
                    active_callback_=previous_callback;active_invocation_=previous_invocation;
                }
            }
            return;
        }
        found->consumed=serial_;found->nested_count=0;
        void* previous_receiver=active_receiver_;const auto previous_callback=active_callback_;const auto previous_phase=active_phase_;
        const uint64_t previous_invocation=active_invocation_;
        active_receiver_=receiver;active_callback_=original;active_phase_=phase;active_invocation_=0;
        try {isolate([&]{
            if(invocation_sequence_==~uint64_t(0)){poisoned_=true;serial_=0;error_="actor_mono_invocation_limit";return;}
            active_invocation_=++invocation_sequence_;
            try{original(receiver,method);}catch(...){active_invocation_=0;throw;}
            active_invocation_=0;
        });}
        catch(...){active_receiver_=previous_receiver;active_callback_=previous_callback;active_phase_=previous_phase;active_invocation_=previous_invocation;throw;}
        active_receiver_=previous_receiver;active_callback_=previous_callback;active_phase_=previous_phase;active_invocation_=previous_invocation;
    }
};

struct TalkJobSnapshotApi {
    bool (*mapped)(const void*,size_t,bool)=nullptr;
    bool (*job_current)(void*,const void*)=nullptr;
    bool (*held_fenced)(void*,const void*)=nullptr;
};
class TalkJobSnapshot {
    static constexpr size_t job_bytes=96,identity_bytes=80,max_rows=8192;
    struct List {uintptr_t header=0,data=0;int32_t length=0,capacity=0;size_t stride=0;uint8_t* saved=nullptr;};
    TalkJobSnapshotApi api_{};void* context_=nullptr;void* job_=nullptr;
    uint8_t identity_[identity_bytes]{},tail_[16]{};List lists_[2]{};
    bool captured_=false,restored_=false;const char* error_="none";
    Result fail(Result value,const char* code){error_=code;return value;}
    template<class T>bool read(const void* p,size_t at,T& value)const{
        if(!p||!api_.mapped(static_cast<const uint8_t*>(p)+at,sizeof(T),false))return false;
        ::memcpy(&value,static_cast<const uint8_t*>(p)+at,sizeof(T));return true;
    }
    bool current()const{return api_.job_current&&api_.job_current(context_,job_);}
    Result boundary(){
        if(!job_||!api_.mapped||!api_.job_current||!api_.held_fenced)
            return fail(Result::invalid,"talk_state_api_incomplete");
        if(!current())return fail(Result::stale,"talk_state_owner_changed");
        if(!api_.held_fenced(context_,job_))return fail(Result::waiting,"talk_state_fence_pending");
        if(!current())return fail(Result::stale,"talk_state_owner_changed");
        if(!api_.mapped(job_,job_bytes,true))return fail(Result::stale,"talk_state_job_unmapped");
        return Result::ok;
    }
    bool list_now(size_t kind,List& value)const{
        value.stride=kind?20:24;
        if(!read(job_,kind*16,value.header)||!value.header)return false;
        const void* header=reinterpret_cast<void*>(value.header);
        if(!read(header,0,value.data)||!read(header,8,value.length)||!read(header,12,value.capacity)
            ||value.length<0||value.capacity<value.length||static_cast<size_t>(value.capacity)>max_rows)return false;
        const size_t bytes=static_cast<size_t>(value.length)*value.stride;
        return !bytes||(value.data&&api_.mapped(reinterpret_cast<void*>(value.data),bytes,true));
    }
    static bool same(const uint8_t* a,const uint8_t* b,size_t at,size_t n){return !::memcmp(a+at,b+at,n);}
    static bool row_identity(size_t kind,const uint8_t* saved,const uint8_t* live){
        // PropertyStreamHandle's version0 and resolved valueArrayIndex8 are
        // legitimate caches. Only handleIndex4 and bindType12 are binding ID.
        return kind?(same(saved,live,4,4)&&same(saved,live,12,8))
            :(same(saved,live,4,4)&&same(saved,live,12,4));
    }
    static bool finite_float(const uint8_t* p){float value=0;::memcpy(&value,p,4);return __builtin_isfinite(value);}
public:
    TalkJobSnapshot()=default;
    TalkJobSnapshot(const TalkJobSnapshot&)=delete;
    TalkJobSnapshot& operator=(const TalkJobSnapshot&)=delete;
    ~TalkJobSnapshot(){clear();}
    const char* error()const{return error_;}
    bool captured()const{return captured_;}
    bool restored()const{return restored_;}
    Result capture(TalkJobSnapshotApi api,void* context,void* typed_live_job){
        if(captured_)return fail(Result::invalid,"talk_state_already_captured");
        clear();api_=api;context_=context;job_=typed_live_job;
        Result status=boundary();if(status!=Result::ok)return status;
        ::memcpy(identity_,job_,identity_bytes);
        ::memcpy(tail_,static_cast<const uint8_t*>(job_)+identity_bytes,sizeof tail_);
        if(!finite_float(tail_)||!finite_float(tail_+12)||tail_[8]>1)
            return fail(Result::invalid,"talk_state_scalars_invalid");
        for(size_t kind=0;kind<2;++kind){
            List value{};if(!list_now(kind,value))return fail(Result::stale,"talk_state_list_invalid");
            const size_t bytes=static_cast<size_t>(value.length)*value.stride;
            if(bytes){value.saved=static_cast<uint8_t*>(::malloc(bytes));if(!value.saved)return fail(Result::failed,"talk_state_allocation_failed");
                ::memcpy(value.saved,reinterpret_cast<void*>(value.data),bytes);}
            lists_[kind]=value;
            for(int32_t row=0;row<value.length;++row){const auto* p=value.saved+static_cast<size_t>(row)*value.stride;
                if(!finite_float(p+(kind?0:16))||!finite_float(p+(kind?8:20)))
                    return fail(Result::invalid,"talk_state_rows_invalid");}
        }
        if(!current())return fail(Result::stale,"talk_state_owner_changed");
        captured_=true;restored_=false;error_="none";return Result::ok;
    }
    Result validate(){
        if(!captured_)return fail(Result::invalid,"talk_state_not_captured");
        Result status=boundary();if(status!=Result::ok)return status;
        if(::memcmp(identity_,job_,identity_bytes))return fail(Result::stale,"talk_state_job_identity_changed");
        for(size_t kind=0;kind<2;++kind){
            List value{};const auto& saved=lists_[kind];
            if(!list_now(kind,value)||value.header!=saved.header||value.data!=saved.data
                ||value.length!=saved.length||value.capacity!=saved.capacity)
                return fail(Result::stale,"talk_state_list_identity_changed");
            for(int32_t row=0;row<saved.length;++row){const size_t at=static_cast<size_t>(row)*saved.stride;
                if(!row_identity(kind,saved.saved+at,reinterpret_cast<const uint8_t*>(saved.data)+at))
                    return fail(Result::stale,"talk_state_row_identity_changed");}
        }
        if(!current())return fail(Result::stale,"talk_state_owner_changed");
        error_="none";return Result::ok;
    }
    Result reset_time(){
        Result status=validate();if(status!=Result::ok)return status;
        const float zero=0;::memcpy(static_cast<uint8_t*>(job_)+92,&zero,4);return Result::ok;
    }
    Result restore(){
        Result status=validate();if(status!=Result::ok)return status;
        if(restored_)return Result::ok;
        // All owners/ranges/identities have been validated before any write.
        // There are no callbacks between this last witness and the memcpy set.
        if(!current())return fail(Result::stale,"talk_state_owner_changed");
        ::memcpy(static_cast<uint8_t*>(job_)+identity_bytes,tail_,sizeof tail_);
        for(size_t kind=0;kind<2;++kind){const auto& list=lists_[kind];
            for(int32_t row=0;row<list.length;++row){const size_t at=static_cast<size_t>(row)*list.stride;
                auto* live=reinterpret_cast<uint8_t*>(list.data)+at;const auto* saved=list.saved+at;
                if(kind){::memcpy(live,saved,4);::memcpy(live+8,saved+8,4);}
                else ::memcpy(live+16,saved+16,8);
            }
        }
        restored_=true;error_="none";return Result::ok;
    }
    void clear(){
        for(auto& list:lists_){::free(list.saved);list=List{};}
        api_=TalkJobSnapshotApi{};context_=job_=nullptr;captured_=restored_=false;error_="none";
    }
};

struct FixedJobOwner {void* component=nullptr;void* job=nullptr;const ActorFixedJobSchema* schema=nullptr;Handle playable{},graph{};void* animator=nullptr;};
struct FixedJobApi {
    bool (*mapped)(const void*,size_t,bool)=nullptr;
    bool (*current)(void*,const FixedJobOwner&)=nullptr;
    bool (*held_fenced)(void*,const FixedJobOwner&)=nullptr;
};
class FixedJobSnapshot {
    struct Buffer {uint8_t descriptor[16]{};uintptr_t header=0;void* data=nullptr;int32_t length=0,capacity=0;uint8_t* saved=nullptr;uint8_t* mask=nullptr;};
    FixedJobApi api_{};void* context_=nullptr;FixedJobOwner owner_{};
    uint8_t* saved_=nullptr;uint8_t* mask_=nullptr;Buffer buffers_[16]{};
    size_t bytes_=0,limit_=0;bool captured_=false,restored_=false;
    const char* error_="none";
    Result fail(Result value,const char* why){error_=why;return value;}
    bool allocate(size_t bytes,uint8_t** value){if(!bytes||bytes>limit_-bytes_)return false;*value=static_cast<uint8_t*>(::malloc(bytes));if(!*value)return false;bytes_+=bytes;return true;}
    template<class T>bool read(const void* object,size_t at,T& value)const{if(!object||!api_.mapped(static_cast<const uint8_t*>(object)+at,sizeof(T),false))return false;::memcpy(&value,static_cast<const uint8_t*>(object)+at,sizeof(T));return true;}
    bool mask(uint8_t* data,size_t bytes,const ActorValueRange* ranges,size_t count){
        for(size_t i=0;i<count;++i){if(!ranges[i].bytes||ranges[i].offset>bytes||ranges[i].bytes>bytes-ranges[i].offset)return false;::memset(data+ranges[i].offset,1,ranges[i].bytes);}return true;
    }
    static bool equal(const uint8_t* a,const uint8_t* b,const uint8_t* mask,size_t bytes){
        size_t at=0;while(at<bytes){while(at<bytes&&mask[at])++at;const size_t begin=at;while(at<bytes&&!mask[at])++at;if(at>begin&&::memcmp(a+begin,b+begin,at-begin))return false;}return true;
    }
    Result boundary(){
        if(!owner_.component||!owner_.job||!owner_.schema||!api_.mapped||!api_.current||!api_.held_fenced)return fail(Result::invalid,"actor_fixed_job_api_unavailable");
        if(!api_.current(context_,owner_))return fail(Result::stale,"actor_fixed_job_owner_changed");
        if(!api_.held_fenced(context_,owner_))return fail(Result::waiting,"actor_fixed_job_fence_pending");
        if(!api_.current(context_,owner_)||!api_.mapped(owner_.job,owner_.schema->bytes,true))return fail(Result::stale,"actor_fixed_job_unmapped");
        return Result::ok;
    }
    bool inspect(size_t index,Buffer& b){const auto& c=owner_.schema->containers[index];
        if(!api_.mapped(static_cast<uint8_t*>(owner_.job)+c.offset,16,false)
            ||!api_.mapped(static_cast<uint8_t*>(owner_.component)+c.component_offset,16,false))return false;
        ::memcpy(b.descriptor,static_cast<uint8_t*>(owner_.job)+c.offset,16);
        if(::memcmp(b.descriptor,static_cast<uint8_t*>(owner_.component)+c.component_offset,16))return false;
        if(c.list){
            ::memcpy(&b.header,b.descriptor,8);
            if(!b.header||!read(reinterpret_cast<void*>(b.header),0,b.data)||!read(reinterpret_cast<void*>(b.header),8,b.length)||!read(reinterpret_cast<void*>(b.header),12,b.capacity))return false;
        }else{::memcpy(&b.data,b.descriptor,8);::memcpy(&b.length,b.descriptor+8,4);b.capacity=b.length;}
        if(!c.stride||c.stride>4096||b.length<0||b.capacity<b.length||b.capacity>8192)return false;
        return !b.length||(b.data&&api_.mapped(b.data,static_cast<size_t>(b.length)*c.stride,true));
    }
public:
    FixedJobSnapshot()=default;FixedJobSnapshot(const FixedJobSnapshot&)=delete;FixedJobSnapshot& operator=(const FixedJobSnapshot&)=delete;
    ~FixedJobSnapshot(){clear();}
    const char* error()const{return error_;}bool captured()const{return captured_;}size_t bytes()const{return bytes_;}
    const FixedJobOwner& owner()const{return owner_;}
    Result capture(FixedJobApi api,void* context,FixedJobOwner owner,size_t limit=64u*1024u*1024u){
        if(captured_)return fail(Result::invalid,"actor_fixed_job_already_captured");
        clear();api_=api;context_=context;owner_=owner;limit_=limit;
        Result result=boundary();if(result!=Result::ok)return result;const auto& s=*owner_.schema;
        if(!s.bytes||s.bytes>4096||s.container_count>16||s.cache_count>512||s.scratch_count>128||s.history_count>128)return fail(Result::unsupported,"actor_fixed_job_schema_invalid");
        if(!allocate(s.bytes,&saved_)||!allocate(s.bytes,&mask_))return fail(Result::failed,"actor_fixed_job_allocation_failed");
        ::memcpy(saved_,owner_.job,s.bytes);::memset(mask_,0,s.bytes);
        if(!mask(mask_,s.bytes,s.caches,s.cache_count)||!mask(mask_,s.bytes,s.scratch,s.scratch_count)||!mask(mask_,s.bytes,s.history,s.history_count))return fail(Result::unsupported,"actor_fixed_job_schema_invalid");
        for(size_t i=0;i<s.container_count;++i){auto& b=buffers_[i];if(!inspect(i,b))return fail(Result::unsupported,"actor_fixed_job_container_invalid");const auto& c=s.containers[i];
            if(!allocate(c.stride,&b.mask)){return fail(Result::failed,"actor_fixed_job_allocation_failed");}
            ::memset(b.mask,0,c.stride);
            if(!mask(b.mask,c.stride,c.caches,c.cache_count))return fail(Result::unsupported,"actor_fixed_job_schema_invalid");
            if(b.length){const size_t bytes=static_cast<size_t>(b.length)*c.stride;if(!allocate(bytes,&b.saved))return fail(Result::failed,"actor_fixed_job_allocation_failed");::memcpy(b.saved,b.data,bytes);}
        }
        captured_=true;restored_=false;error_="none";return Result::ok;
    }
    Result validate(){
        if(!captured_){return fail(Result::invalid,"actor_fixed_job_snapshot_missing");}
        Result result=boundary();if(result!=Result::ok)return result;const auto& s=*owner_.schema;
        if(!equal(saved_,static_cast<const uint8_t*>(owner_.job),mask_,s.bytes))return fail(Result::stale,"actor_fixed_job_configuration_changed");
        for(size_t i=0;i<s.container_count;++i){Buffer now{};const auto& b=buffers_[i];const auto& c=s.containers[i];
            if(!inspect(i,now)||::memcmp(b.descriptor,now.descriptor,16)||b.header!=now.header||b.data!=now.data||b.length!=now.length||b.capacity!=now.capacity)return fail(Result::stale,"actor_fixed_job_container_changed");
            for(int32_t row=0;row<b.length;++row){const size_t at=static_cast<size_t>(row)*c.stride;
                if(!equal(b.saved+at,static_cast<const uint8_t*>(b.data)+at,b.mask,c.stride))return fail(Result::stale,"actor_fixed_job_row_configuration_changed");}
        }
        return api_.current(context_,owner_)?Result::ok:fail(Result::stale,"actor_fixed_job_owner_changed");
    }
    Result reset_history(){Result result=validate();if(result!=Result::ok)return result;const auto& s=*owner_.schema;
        // Only original first-evaluation zero-sentinel float caches. Scratch is
        // overwritten before use by the original job and needs no fake reset.
        for(size_t i=0;i<s.history_count;++i)::memset(static_cast<uint8_t*>(owner_.job)+s.history[i].offset,0,s.history[i].bytes);
        return Result::ok;
    }
    Result restore(){Result result=validate();if(result!=Result::ok)return result;if(restored_)return Result::ok;const auto& s=*owner_.schema;
        for(size_t i=0;i<s.scratch_count;++i)::memcpy(static_cast<uint8_t*>(owner_.job)+s.scratch[i].offset,saved_+s.scratch[i].offset,s.scratch[i].bytes);
        for(size_t i=0;i<s.history_count;++i)::memcpy(static_cast<uint8_t*>(owner_.job)+s.history[i].offset,saved_+s.history[i].offset,s.history[i].bytes);
        restored_=true;return Result::ok;
    }
    void clear(){::free(saved_);::free(mask_);saved_=mask_=nullptr;for(auto& b:buffers_){::free(b.saved);::free(b.mask);b={};}api_={};context_=nullptr;owner_={};bytes_=limit_=0;captured_=restored_=false;error_="none";}
};

struct Vector2 {float x=0,y=0;};
struct Bounds {Vector3 center{},extents{};};
// Logical local-bounds authority and the two actual native caches. A Skinned
// setter also changes its mesh cache/dirty flag; equal public Bounds alone do
// not preserve automatic-vs-explicit authority.
struct RendererBoundsImage {
    uintptr_t native=0,vtable=0;int32_t instance_id=0;
    Bounds base{},skin{};bool skinned=false,explicit_local=false,offscreen=false;
};
struct PropertyBlockOwner {void* renderer=nullptr;void* original=nullptr;int32_t index=-1;};
struct NativeImagesApi {
    // The host uses exact original Material(Shader), then CopyProperties.
    // CopyProperties is independently pinned through native property/keyword /
    // renderQueue copy bodies; it intentionally preserves the shader identity.
    void* (*material_shader)(void*,Method*)=nullptr;
    void* (*material_new)(void* shader)=nullptr;
    void (*material_copy)(void*,void*,Method*)=nullptr;
    void (*material_destroy)(void*)=nullptr;
    void* (*block_new)()=nullptr;bool (*block_valid)(void*)=nullptr;
    bool (*block_empty)(void*,Method*)=nullptr;
    void (*block_get)(void*,void*,int32_t,Method*)=nullptr;
    void (*block_set)(void*,void*,int32_t,Method*)=nullptr;
    void (*renderer_bounds_get)(void*,Bounds*,Method*)=nullptr;
    void (*renderer_bounds_set)(void*,const Bounds*,Method*)=nullptr;
    void (*mesh_bounds_get)(void*,Bounds*,Method*)=nullptr;
    void (*mesh_bounds_set)(void*,const Bounds*,Method*)=nullptr;
    void* (*mesh_vertices_get)(void*,Method*)=nullptr;
    void (*mesh_vertices_set)(void*,void*,Method*)=nullptr;
    void (*block_dispose)(void*,Method*)=nullptr;
    bool (*renderer_bounds_capture)(void*,RendererBoundsImage*)=nullptr;
    bool (*renderer_bounds_current)(void*,const RendererBoundsImage*)=nullptr;
    bool (*renderer_bounds_restore)(void*,const RendererBoundsImage*)=nullptr;
    bool (*renderer_bounds_verify)(void*,const RendererBoundsImage*)=nullptr;
};

struct PresentationNode {void* object=nullptr;const ActorPresentationSchema* schema=nullptr;};
struct PresentationInventory {
    PresentationNode nodes[256]{};size_t node_count=0;
    void* arrays[256]{};size_t array_count=0;
    void* materials[128]{};size_t material_count=0;
    void* renderers[128]{};size_t renderer_count=0;
    MonoReceiver callbacks[max_mono_receivers]{};size_t callback_count=0;
    void* talk_jobs[32]{};size_t talk_job_count=0;
    FixedJobOwner fixed_jobs[256]{};size_t fixed_job_count=0;
    void* full_materials[256]{};size_t full_material_count=0;
    PropertyBlockOwner blocks[512]{};size_t block_count=0;
    void* bounds_renderers[256]{};size_t bounds_renderer_count=0;
    void* shadow_meshes[32]{};size_t shadow_mesh_count=0;
};
struct PresentationApi {
    bool (*current)(void*)=nullptr;bool (*held)(void*)=nullptr;
    bool (*mapped)(const void*,size_t,bool)=nullptr;
    bool (*is_type)(void*,const char*)=nullptr;bool (*alive)(void*)=nullptr;
    void* (*class_of)(void*)=nullptr;
    bool (*schema_matches)(void*,const ActorPresentationSchema&)=nullptr;
    uint32_t (*retain)(void*)=nullptr;void* (*target)(uint32_t)=nullptr;void (*release)(uint32_t)=nullptr;
    // This is a read-only selected-cast inventory. It must include exact known
    // extension families and reject unknown mutable components before capture.
    bool (*inventory)(void*,PresentationInventory&)=nullptr;
    size_t (*array_length)(void*)=nullptr;void* (*array_data)(void*)=nullptr;
    void* (*blend_mesh)(void*,Method*)=nullptr;int32_t (*blend_count)(void*,Method*)=nullptr;
    float (*blend_get)(void*,int32_t,Method*)=nullptr;void (*blend_set)(void*,int32_t,float,Method*)=nullptr;
    float (*material_float_get)(void*)=nullptr;void (*material_float_set)(void*,float)=nullptr;
    Vector2 (*material_offset_get)(void*,Method*)=nullptr;void (*material_offset_set)(void*,Vector2,Method*)=nullptr;
    void (*initialize_constraints)(void*,Method*)=nullptr;
    MonoApi mono{};
    TalkJobSnapshotApi talk{};
    NativeImagesApi images{};
    void (*aux_complete)(void*,Method*)=nullptr;
    void (*foot_apply_raw)(void*,Method*)=nullptr;
    int32_t (*color_dirty_offset)(void*)=nullptr;
    FixedJobApi fixed{};
};
// Field-level finite snapshot: a scalar field is admitted only by the generated
// original schema. Managed references/native headers are identity witnesses and
// never restored as bytes. Primitive FFT arrays exclude their managed headers.
class PresentationScope {
    struct Field {void* object=nullptr;void* klass=nullptr;const ActorPresentationSchema* schema=nullptr;
        uint32_t root=0;uint8_t* saved=nullptr;size_t bytes=0;};
    struct Array {void* object=nullptr;void* data=nullptr;uint32_t root=0;size_t length=0,stride=4;uint8_t* saved=nullptr;};
    struct Material {void* object=nullptr;uint32_t root=0;float highlight=0;Vector2 offset{};};
    struct Blend {void* object=nullptr;void* mesh=nullptr;uint32_t root=0,mesh_root=0;int32_t count=0;float* weights=nullptr;};
    PresentationApi api_{};MonoGate* gate_=nullptr;void* context_=nullptr;uint64_t epoch_=0;
    PresentationInventory inventory_{};
    Field fields_[256]{};Array arrays_[256]{};Material materials_[128]{};Blend blends_[128]{};
    TalkJobSnapshot talk_[32]{};size_t talk_count_=0;
    FixedJobSnapshot fixed_[256]{};size_t fixed_count_=0;
    struct MaterialCopy {void* source=nullptr;void* shader=nullptr;void* snapshot=nullptr;uint32_t roots[3]{};};
    struct BlockCopy {PropertyBlockOwner source{};void* snapshot=nullptr;void* cpu_snapshot=nullptr;uint32_t roots[4]{};bool empty=true,slot_displaced=false;};
    struct RendererBounds {void* object=nullptr;uint32_t root=0;RendererBoundsImage image{};};
    struct MeshImage {void* object=nullptr;void* vertices=nullptr;uint32_t roots[2]{};Bounds bounds{};size_t length=0;};
    MaterialCopy material_copies_[256]{};BlockCopy block_copies_[512]{};
    RendererBounds renderer_bounds_[256]{};MeshImage mesh_images_[32]{};
    size_t material_copy_count_=0,block_copy_count_=0,renderer_bounds_count_=0,mesh_image_count_=0;
    struct NativeBuffer {void* owner=nullptr;uint16_t offset=0,stride=0;uint8_t header[16]{};void* data=nullptr;size_t length=0;uint8_t* saved=nullptr;};
    NativeBuffer native_buffers_[256]{};size_t native_buffer_count_=0;
    struct DirtyFlag {void* object=nullptr;void* klass=nullptr;uint32_t offset=0;uint8_t value=0;};
    DirtyFlag dirty_flags_[32]{};size_t dirty_flag_count_=0;
    size_t fields_count_=0,arrays_count_=0,materials_count_=0,blends_count_=0,bytes_=0;
    bool configured_=false,captured_=false,restored_=false,initialized_=false,source_flushed_=false,runtime_history_reset_=false;
    const char* error_="none";
    Result fail(Result value,const char* why){error_=why;return value;}
    static bool finite(float v){return __builtin_isfinite(v);}
    bool root_current(uint32_t root,void* value)const{return root&&api_.target(root)==value;}
    bool alloc(size_t count,uint8_t** out){
        if(!count||count>presentation_max_snapshot_bytes-bytes_)return false;
        *out=static_cast<uint8_t*>(::malloc(count));if(!*out)return false;bytes_+=count;return true;
    }
    bool same_inventory(const PresentationInventory& b)const {
        const auto& a=inventory_;
        if(a.node_count!=b.node_count||a.array_count!=b.array_count||a.material_count!=b.material_count
            ||a.renderer_count!=b.renderer_count||a.callback_count!=b.callback_count||a.talk_job_count!=b.talk_job_count
            ||a.full_material_count!=b.full_material_count||a.block_count!=b.block_count
            ||a.bounds_renderer_count!=b.bounds_renderer_count||a.shadow_mesh_count!=b.shadow_mesh_count||a.fixed_job_count!=b.fixed_job_count)return false;
        for(size_t i=0;i<a.node_count;++i)if(a.nodes[i].object!=b.nodes[i].object||a.nodes[i].schema!=b.nodes[i].schema)return false;
        for(size_t i=0;i<a.array_count;++i)if(a.arrays[i]!=b.arrays[i])return false;
        for(size_t i=0;i<a.material_count;++i)if(a.materials[i]!=b.materials[i])return false;
        for(size_t i=0;i<a.renderer_count;++i)if(a.renderers[i]!=b.renderers[i])return false;
        for(size_t i=0;i<a.fixed_job_count;++i)if(a.fixed_jobs[i].component!=b.fixed_jobs[i].component||a.fixed_jobs[i].job!=b.fixed_jobs[i].job||a.fixed_jobs[i].schema!=b.fixed_jobs[i].schema||a.fixed_jobs[i].playable.handle!=b.fixed_jobs[i].playable.handle||a.fixed_jobs[i].playable.version!=b.fixed_jobs[i].playable.version||a.fixed_jobs[i].graph.handle!=b.fixed_jobs[i].graph.handle||a.fixed_jobs[i].graph.version!=b.fixed_jobs[i].graph.version||a.fixed_jobs[i].animator!=b.fixed_jobs[i].animator)return false;
        for(size_t i=0;i<a.full_material_count;++i)if(a.full_materials[i]!=b.full_materials[i])return false;
        for(size_t i=0;i<a.block_count;++i)if(a.blocks[i].renderer!=b.blocks[i].renderer||a.blocks[i].original!=b.blocks[i].original||a.blocks[i].index!=b.blocks[i].index)return false;
        for(size_t i=0;i<a.bounds_renderer_count;++i)if(a.bounds_renderers[i]!=b.bounds_renderers[i])return false;
        for(size_t i=0;i<a.shadow_mesh_count;++i)if(a.shadow_meshes[i]!=b.shadow_meshes[i])return false;
        for(size_t i=0;i<a.talk_job_count;++i)if(a.talk_jobs[i]!=b.talk_jobs[i])return false;
        for(size_t i=0;i<a.callback_count;++i)if(a.callbacks[i].object!=b.callbacks[i].object||a.callbacks[i].phase!=b.callbacks[i].phase)return false;
        return true;
    }
    bool rollback_block(BlockCopy& b){
        if(!b.slot_displaced)return true;
        if(!api_.current(context_)||!api_.held(context_)||!root_current(b.roots[0],b.source.renderer)
            ||!root_current(b.roots[2],b.snapshot)||!api_.alive(b.source.renderer)||!api_.images.block_valid(b.snapshot))return false;
        api_.images.block_set(b.source.renderer,b.empty?nullptr:b.snapshot,b.source.index,nullptr);
        b.slot_displaced=false;return api_.current(context_);
    }
    bool copy_cpu_block(BlockCopy& b,void* from,void* to){
        if(!api_.current(context_))return false;
        // Public Get/Set perform the original deep native assignment. Borrow
        // the owned renderer slot only on this held Unity-thread stack, then
        // restore it immediately. CPU scratch contents need not equal the
        // renderer slot (unapplied keys and shared scratch blocks are valid).
        b.slot_displaced=true; // Persistent rollback duty precedes first Set.
        try {
            api_.images.block_set(b.source.renderer,from,b.source.index,nullptr);
            if(!api_.current(context_))return false;
            api_.images.block_get(b.source.renderer,to,b.source.index,nullptr);
        } catch(...) {
            rollback_block(b);throw;
        }
        if(!api_.current(context_))return false;
        return rollback_block(b);
    }
    Result auxiliary_fence(){
        for(size_t i=0;i<fields_count_;++i){void* object=fields_[i].object;
            if(!api_.is_type(object,"VL.Core.VLActorController")&&!api_.is_type(object,"VL.VLActorFootShadow"))continue;
            auto* handle=static_cast<uint8_t*>(object)+184;
            if(!api_.aux_complete||!api_.mapped(handle,16,true))return fail(Result::unsupported,"actor_aux_job_unmapped");
            api_.aux_complete(handle,nullptr);uint64_t group=0;int32_t version=0;
            ::memcpy(&group,handle,8);::memcpy(&version,handle+8,4);
            if(group||version)return fail(Result::waiting,"actor_aux_job_pending");
            if(api_.is_type(object,"VL.VLActorFootShadow")){
                auto* scheduled=static_cast<uint8_t*>(object)+180;
                if(!api_.foot_apply_raw||!api_.mapped(scheduled,1,true)||*scheduled>1)return fail(Result::unsupported,"actor_shadow_pending_state_invalid");
                // Drain the exact already scheduled source/export work. Any
                // old queued PreCull delegate then sees false and is a no-op;
                // unrelated camera callbacks are neither cleared nor removed.
                if(*scheduled)api_.foot_apply_raw(object,nullptr);
                if(*scheduled)return fail(Result::waiting,"actor_shadow_apply_pending");
            }
            if(!api_.current(context_))return fail(Result::stale,"actor_aux_owner_changed");
        }
        return Result::ok;
    }
    Result capture_native(void* owner,uint16_t offset,uint16_t stride){
        if(native_buffer_count_==256)return fail(Result::unsupported,"actor_aux_buffer_limit");
        NativeBuffer b{};b.owner=owner;b.offset=offset;b.stride=stride;
        if(!api_.mapped(static_cast<uint8_t*>(owner)+offset,16,false))return fail(Result::unsupported,"actor_aux_array_unmapped");
        ::memcpy(b.header,static_cast<uint8_t*>(owner)+offset,16);int32_t length=0;
        ::memcpy(&b.data,b.header,8);::memcpy(&length,b.header+8,4);
        if(length<0||length>65536)return fail(Result::unsupported,"actor_aux_array_limit");
        b.length=static_cast<size_t>(length);
        if(b.length&&(!b.data||!api_.mapped(b.data,b.length*stride,true)||!alloc(b.length*stride,&b.saved)))return fail(Result::unsupported,"actor_aux_array_invalid");
        if(b.length)::memcpy(b.saved,b.data,b.length*stride);
        native_buffers_[native_buffer_count_++]=b;return Result::ok;
    }
    bool complete()const{
        return api_.current&&api_.held&&api_.mapped&&api_.is_type&&api_.alive&&api_.class_of&&api_.schema_matches
            &&api_.retain&&api_.target&&api_.release&&api_.inventory&&api_.array_length&&api_.array_data
            &&api_.blend_mesh&&api_.blend_count&&api_.blend_get&&api_.blend_set&&api_.material_float_get
            &&api_.material_float_set&&api_.material_offset_get&&api_.material_offset_set&&api_.initialize_constraints;
    }
public:
    const char* error()const{return error_;}
    bool active()const{return configured_;}
    bool captured()const{return captured_;}
    bool transient_slots_unwound()const noexcept{if(block_copy_count_>512)return false;for(size_t i=0;i<block_copy_count_;++i)if(block_copies_[i].slot_displaced)return false;return true;}
    // Cheap callback/step witness, including the original DSP admission. This
    // performs no inventory allocation or scene mutation. A bound ADV voice
    // source must never run inside the private offline frame/RNG domain.
    bool scalar_owner_current()const {
        if(!api_.current||!api_.current(context_))return false;
        for(size_t i=0;i<fields_count_;++i){const auto& f=fields_[i];
            if(!root_current(f.root,f.object)||api_.class_of(f.object)!=f.klass)return false;
            size_t at=0;for(size_t j=0;j<f.schema->count;++j){const auto& span=f.schema->fields[j];
                auto* value=static_cast<uint8_t*>(f.object)+span.offset;
                if(!api_.mapped(value,span.bytes,!span.identity)||(captured_&&span.identity&&::memcmp(value,f.saved+at,span.bytes)))return false;
                at+=span.bytes;}
            if(api_.is_type(f.object,"VL.VLActorTalkFFT")){
                void* source=nullptr;if(!api_.mapped(static_cast<uint8_t*>(f.object)+80,8,false))return false;
                ::memcpy(&source,static_cast<uint8_t*>(f.object)+80,8);if(source)return false;
            }
        }
        return true;
    }
    bool configure(PresentationApi api,MonoGate* gate,void* context,uint64_t epoch){
        if(configured_||!gate||!context||!epoch)return false;
        inventory_={};
        api_=api;gate_=gate;context_=context;epoch_=epoch;
        if(!complete()||!api_.current(context_)||!api_.held(context_)){error_="actor_presentation_api_unavailable";return false;}
        if(!api_.inventory(context_,inventory_)||!inventory_.node_count||inventory_.node_count>256||inventory_.array_count>256
            ||inventory_.material_count>128||inventory_.renderer_count>128||inventory_.talk_job_count>32
            ||inventory_.fixed_job_count>256||inventory_.full_material_count>256||inventory_.block_count>512||inventory_.bounds_renderer_count>256||inventory_.shadow_mesh_count>32||!inventory_.callback_count||inventory_.callback_count>max_mono_receivers){error_="actor_presentation_inventory_unsupported";return false;}
        // Retain receivers before publishing callback ownership. This stops a
        // pooled/new object at the same address from inheriting an old grant.
        for(size_t i=0;i<inventory_.node_count;++i){
            auto& f=fields_[fields_count_++];f.object=inventory_.nodes[i].object;f.schema=inventory_.nodes[i].schema;
            if(!f.object||!f.schema||!api_.schema_matches(f.object,*f.schema)||!api_.is_type(f.object,f.schema->type)
                ||!(f.klass=api_.class_of(f.object))||!(f.root=api_.retain(f.object))||!root_current(f.root,f.object)){
                error_="actor_presentation_node_invalid";release(false);return false;}
        }
        for(size_t i=0;i<inventory_.callback_count;++i){bool retained=false;
            for(size_t j=0;j<fields_count_;++j)retained|=fields_[j].object==inventory_.callbacks[i].object;
            if(!retained){error_="actor_presentation_receiver_unretained";release(false);return false;}}
        if(inventory_.fixed_job_count&&(!api_.fixed.mapped||!api_.fixed.current||!api_.fixed.held_fenced)){error_="actor_fixed_job_api_unavailable";release(false);return false;}
        if(inventory_.talk_job_count&&(!api_.talk.mapped||!api_.talk.job_current||!api_.talk.held_fenced)){error_="actor_presentation_talk_api_unavailable";release(false);return false;}
        if(!scalar_owner_current()){error_="actor_talk_dsp_source_unsupported";release(false);return false;}
        const auto& images=api_.images;
        if((inventory_.full_material_count&&(!images.material_shader||!images.material_new||!images.material_copy||!images.material_destroy))
            ||(inventory_.block_count&&(!images.block_new||!images.block_valid||!images.block_empty||!images.block_get||!images.block_set||!images.block_dispose))
            ||(inventory_.bounds_renderer_count&&(!images.renderer_bounds_capture||!images.renderer_bounds_current
                ||!images.renderer_bounds_restore||!images.renderer_bounds_verify))
            ||(inventory_.shadow_mesh_count&&(!images.mesh_bounds_get||!images.mesh_bounds_set||!images.mesh_vertices_get||!images.mesh_vertices_set))){
            error_="actor_presentation_native_image_api_unavailable";release(false);return false;}
        if(!gate_->publish(api_.mono,context_,epoch_,inventory_.callbacks,inventory_.callback_count)){
            error_="actor_presentation_gate_unavailable";release(false);return false;}
        configured_=true;error_="none";return true;
    }
    void revoke_grants(){if(gate_&&epoch_)gate_->revoke(epoch_);}
    Result hold(){
        if(!configured_||!scalar_owner_current())return fail(Result::stale,"actor_presentation_owner_changed");
        if(!gate_->hold(epoch_))return fail(Result::stale,"actor_presentation_gate_changed");
        return auxiliary_fence();
    }
    Result grant(uint64_t serial){
        if(!captured_||!initialized_||!gate_->grant(epoch_,serial))return fail(Result::stale,"actor_presentation_grant_failed");
        return Result::ok;
    }
    Result capture(){
        if(!configured_||!api_.current(context_)||!api_.held(context_))return fail(Result::stale,"actor_presentation_not_held");
        if(captured_)return Result::ok;
        {const Result fence=auxiliary_fence();if(fence!=Result::ok)return fence;}
        for(size_t i=0;i<fields_count_;++i){auto& f=fields_[i];if(f.saved)continue;
            for(size_t j=0;j<f.schema->count;++j){const auto& span=f.schema->fields[j];
                if(span.offset<16||!span.bytes||span.bytes>64||f.bytes>size_t{4096}-span.bytes
                    ||!api_.mapped(static_cast<uint8_t*>(f.object)+span.offset,span.bytes,!span.identity))return fail(Result::unsupported,"actor_presentation_field_unmapped");
                f.bytes+=span.bytes;}
            if(!alloc(f.bytes,&f.saved))return fail(Result::failed,"actor_presentation_allocation_failed");
            size_t at=0;for(size_t j=0;j<f.schema->count;++j){const auto& span=f.schema->fields[j];
                ::memcpy(f.saved+at,static_cast<uint8_t*>(f.object)+span.offset,span.bytes);at+=span.bytes;}
        }
        for(size_t i=arrays_count_;i<inventory_.array_count;++i){auto& a=arrays_[arrays_count_++];a.object=inventory_.arrays[i];
            if(!a.object||(!api_.is_type(a.object,"System.Single[]")&&!api_.is_type(a.object,"System.Int32[]")&&!api_.is_type(a.object,"UnityEngine.Vector3[]")&&!api_.is_type(a.object,"UnityEngine.Vector2[]"))
                ||!(a.root=api_.retain(a.object))||!root_current(a.root,a.object))return fail(Result::unsupported,"actor_presentation_array_invalid");
            a.stride=api_.is_type(a.object,"UnityEngine.Vector3[]")?12:api_.is_type(a.object,"UnityEngine.Vector2[]")?8:4;
            a.length=api_.array_length(a.object);a.data=api_.array_data(a.object);
            if(a.length>65536||(a.length&&(!a.data||!api_.mapped(a.data,a.length*a.stride,true)||!alloc(a.length*a.stride,&a.saved))))return fail(Result::unsupported,"actor_presentation_array_invalid");
            if(a.length)::memcpy(a.saved,a.data,a.length*a.stride);
        }
        for(size_t i=materials_count_;i<inventory_.material_count;++i){auto& m=materials_[materials_count_++];m.object=inventory_.materials[i];
            if(!api_.is_type(m.object,"UnityEngine.Material")||!api_.alive(m.object)||!(m.root=api_.retain(m.object)))return fail(Result::unsupported,"actor_presentation_material_invalid");
            m.highlight=api_.material_float_get(m.object);m.offset=api_.material_offset_get(m.object,nullptr);
            if(!finite(m.highlight)||!finite(m.offset.x)||!finite(m.offset.y))return fail(Result::unsupported,"actor_presentation_material_nonfinite");
        }
        for(size_t i=blends_count_;i<inventory_.renderer_count;++i){auto& b=blends_[blends_count_++];b.object=inventory_.renderers[i];
            if(!api_.is_type(b.object,"UnityEngine.SkinnedMeshRenderer")||!api_.alive(b.object)||!(b.root=api_.retain(b.object))
                ||!(b.mesh=api_.blend_mesh(b.object,nullptr))||!api_.is_type(b.mesh,"UnityEngine.Mesh")||!api_.alive(b.mesh)
                ||!(b.mesh_root=api_.retain(b.mesh)))return fail(Result::unsupported,"actor_presentation_mesh_invalid");
            b.count=api_.blend_count(b.mesh,nullptr);uint8_t* memory=nullptr;
            if(b.count<0||b.count>4096||(b.count&&!alloc(static_cast<size_t>(b.count)*sizeof(float),&memory)))return fail(Result::unsupported,"actor_presentation_blend_limit");
            b.weights=reinterpret_cast<float*>(memory);
            for(int32_t j=0;j<b.count;++j)if(!finite(b.weights[j]=api_.blend_get(b.object,j,nullptr)))return fail(Result::unsupported,"actor_presentation_blend_nonfinite");
        }
        if(!dirty_flag_count_)for(size_t i=0;i<fields_count_;++i){void* object=fields_[i].object;
            if(!api_.is_type(object,"VL.VLDefaultActorController`3"))continue;
            if(dirty_flag_count_==32||!api_.color_dirty_offset)return fail(Result::unsupported,"actor_color_dirty_api_unavailable");
            const int32_t offset=api_.color_dirty_offset(object);
            if(offset<16||offset>65535||!api_.mapped(static_cast<uint8_t*>(object)+offset,1,true))return fail(Result::unsupported,"actor_color_dirty_field_invalid");
            const uint8_t value=*(static_cast<uint8_t*>(object)+offset);if(value>1)return fail(Result::unsupported,"actor_color_dirty_state_invalid");
            dirty_flags_[dirty_flag_count_++]={object,api_.class_of(object),static_cast<uint32_t>(offset),value};
        }
        if(!native_buffer_count_)for(size_t i=0;i<fields_count_;++i){const auto& f=fields_[i];Result result=Result::ok;
            if(api_.is_type(f.object,"VL.Core.VLActorController")){
                result=capture_native(f.object,144,212);if(result!=Result::ok)return result;
                result=capture_native(f.object,168,12);if(result!=Result::ok)return result;
            }else if(api_.is_type(f.object,"VL.VLActorFootShadow")){
                result=capture_native(f.object,96,20);if(result!=Result::ok)return result;
                result=capture_native(f.object,120,12);if(result!=Result::ok)return result;
                result=capture_native(f.object,136,24);if(result!=Result::ok)return result;
            }
        }
        for(size_t i=material_copy_count_;i<inventory_.full_material_count;++i){auto& m=material_copies_[material_copy_count_++];m.source=inventory_.full_materials[i];
            if(!api_.is_type(m.source,"UnityEngine.Material")||!api_.alive(m.source)||!(m.roots[0]=api_.retain(m.source))
                ||!(m.shader=api_.images.material_shader(m.source,nullptr))||!api_.is_type(m.shader,"UnityEngine.Shader")||!api_.alive(m.shader)
                ||!(m.roots[1]=api_.retain(m.shader))||!(m.snapshot=api_.images.material_new(m.shader))
                ||!api_.is_type(m.snapshot,"UnityEngine.Material")||!api_.alive(m.snapshot)||!(m.roots[2]=api_.retain(m.snapshot))
                ||api_.images.material_shader(m.snapshot,nullptr)!=m.shader)return fail(Result::unsupported,"actor_material_snapshot_failed");
            api_.images.material_copy(m.snapshot,m.source,nullptr);
        }
        for(size_t i=block_copy_count_;i<inventory_.block_count;++i){auto& b=block_copies_[block_copy_count_++];b.source=inventory_.blocks[i];
            if(b.source.index<0||b.source.index>255||!api_.is_type(b.source.renderer,"UnityEngine.Renderer")||!api_.alive(b.source.renderer)
                ||!(b.roots[0]=api_.retain(b.source.renderer))||(b.source.original&&(!api_.is_type(b.source.original,"UnityEngine.MaterialPropertyBlock")
                    ||!api_.images.block_valid(b.source.original)||!(b.roots[1]=api_.retain(b.source.original))))
                ||!(b.snapshot=api_.images.block_new())||!api_.is_type(b.snapshot,"UnityEngine.MaterialPropertyBlock")
                ||!api_.images.block_valid(b.snapshot)||!(b.roots[2]=api_.retain(b.snapshot)))return fail(Result::unsupported,"actor_block_snapshot_failed");
            api_.images.block_get(b.source.renderer,b.snapshot,b.source.index,nullptr);b.empty=api_.images.block_empty(b.snapshot,nullptr);
            if(b.source.original){
                b.cpu_snapshot=api_.images.block_new();
                if(!b.cpu_snapshot||!api_.is_type(b.cpu_snapshot,"UnityEngine.MaterialPropertyBlock")||!api_.images.block_valid(b.cpu_snapshot)
                    ||!(b.roots[3]=api_.retain(b.cpu_snapshot)))return fail(Result::unsupported,"actor_cpu_block_snapshot_failed");
                if(!copy_cpu_block(b,b.source.original,b.cpu_snapshot))return fail(Result::stale,"actor_cpu_block_owner_changed");
            }
        }
        for(size_t i=renderer_bounds_count_;i<inventory_.bounds_renderer_count;++i){auto& b=renderer_bounds_[renderer_bounds_count_++];b.object=inventory_.bounds_renderers[i];
            if(!api_.is_type(b.object,"UnityEngine.Renderer")||!api_.alive(b.object)||!(b.root=api_.retain(b.object)))return fail(Result::unsupported,"actor_renderer_bounds_invalid");
            if(!api_.images.renderer_bounds_capture(b.object,&b.image))return fail(Result::unsupported,"actor_renderer_bounds_authority_unavailable");
        }
        for(size_t i=mesh_image_count_;i<inventory_.shadow_mesh_count;++i){auto& m=mesh_images_[mesh_image_count_++];m.object=inventory_.shadow_meshes[i];
            if(!api_.is_type(m.object,"UnityEngine.Mesh")||!api_.alive(m.object)||!(m.roots[0]=api_.retain(m.object))
                ||!(m.vertices=api_.images.mesh_vertices_get(m.object,nullptr))||!api_.is_type(m.vertices,"UnityEngine.Vector3[]")
                ||!(m.roots[1]=api_.retain(m.vertices)))return fail(Result::unsupported,"actor_shadow_mesh_invalid");
            m.length=api_.array_length(m.vertices);if(m.length>65536)return fail(Result::unsupported,"actor_shadow_mesh_too_large");
            api_.images.mesh_bounds_get(m.object,&m.bounds,nullptr);
        }
        for(size_t i=0;i<inventory_.talk_job_count;++i){if(talk_[i].captured())continue;
            talk_count_=i+1;const Result result=talk_[i].capture(api_.talk,context_,inventory_.talk_jobs[i]);
            if(result!=Result::ok)return fail(result,talk_[i].error());}
        for(size_t i=0;i<inventory_.fixed_job_count;++i){if(fixed_[i].captured())continue;fixed_count_=i+1;
            const Result result=fixed_[i].capture(api_.fixed,context_,inventory_.fixed_jobs[i],presentation_max_snapshot_bytes-bytes_);
            if(result!=Result::ok){return fail(result,fixed_[i].error());}
            bytes_+=fixed_[i].bytes();}
        captured_=true;restored_=false;error_="none";return Result::ok;
    }
    Result validate(){
        if(!configured_||!scalar_owner_current()||!api_.held(context_)||!gate_->current())return fail(Result::stale,"actor_presentation_owner_changed");
        {const Result fence=auxiliary_fence();if(fence!=Result::ok)return fence;}
        PresentationInventory now{};if(!api_.inventory(context_,now)||!same_inventory(now))return fail(Result::stale,"actor_presentation_inventory_changed");
        for(size_t i=0;i<fields_count_;++i){const auto& f=fields_[i];
            if(!root_current(f.root,f.object)||api_.class_of(f.object)!=f.klass||!api_.schema_matches(f.object,*f.schema))return fail(Result::stale,"actor_presentation_class_changed");
            size_t at=0;for(size_t j=0;j<f.schema->count;++j){const auto& span=f.schema->fields[j];auto* value=static_cast<uint8_t*>(f.object)+span.offset;
                if(!api_.mapped(value,span.bytes,!span.identity)||(captured_&&span.identity&&::memcmp(f.saved+at,value,span.bytes)))return fail(Result::stale,"actor_presentation_identity_changed");
                at+=span.bytes;}
        }
        for(size_t i=0;i<arrays_count_;++i){const auto& a=arrays_[i];if(!root_current(a.root,a.object)||api_.array_length(a.object)!=a.length
            ||api_.array_data(a.object)!=a.data||(a.length&&!api_.mapped(a.data,a.length*a.stride,true)))return fail(Result::stale,"actor_presentation_array_changed");}
        for(size_t i=0;i<materials_count_;++i){const auto& m=materials_[i];if(!root_current(m.root,m.object)||!api_.alive(m.object))return fail(Result::stale,"actor_presentation_material_changed");}
        for(size_t i=0;i<blends_count_;++i){const auto& b=blends_[i];if(!root_current(b.root,b.object)||!root_current(b.mesh_root,b.mesh)
            ||!api_.alive(b.object)||!api_.alive(b.mesh)||api_.blend_mesh(b.object,nullptr)!=b.mesh||api_.blend_count(b.mesh,nullptr)!=b.count)return fail(Result::stale,"actor_presentation_mesh_changed");}
        for(size_t i=0;i<dirty_flag_count_;++i){const auto& d=dirty_flags_[i];
            if(api_.class_of(d.object)!=d.klass||api_.color_dirty_offset(d.object)!=static_cast<int32_t>(d.offset)
                ||!api_.mapped(static_cast<uint8_t*>(d.object)+d.offset,1,true))return fail(Result::stale,"actor_color_dirty_owner_changed");}
        for(size_t i=0;i<native_buffer_count_;++i){const auto& b=native_buffers_[i];
            if(!api_.mapped(static_cast<uint8_t*>(b.owner)+b.offset,16,false)||::memcmp(static_cast<uint8_t*>(b.owner)+b.offset,b.header,16)
                ||(b.length&&!api_.mapped(b.data,b.length*b.stride,true)))return fail(Result::stale,"actor_aux_array_changed");}
        for(size_t i=0;i<material_copy_count_;++i){const auto& m=material_copies_[i];
            if(!root_current(m.roots[0],m.source)||!root_current(m.roots[1],m.shader)||!root_current(m.roots[2],m.snapshot)
                ||!api_.alive(m.source)||!api_.alive(m.snapshot)||!api_.alive(m.shader)
                ||api_.images.material_shader(m.source,nullptr)!=m.shader||api_.images.material_shader(m.snapshot,nullptr)!=m.shader)
                return fail(Result::stale,"actor_material_owner_changed");}
        for(size_t i=0;i<block_copy_count_;++i){const auto& b=block_copies_[i];
            if(!root_current(b.roots[0],b.source.renderer)||!root_current(b.roots[2],b.snapshot)||!api_.alive(b.source.renderer)||!api_.images.block_valid(b.snapshot)
                ||(b.source.original&&(!root_current(b.roots[1],b.source.original)||!api_.images.block_valid(b.source.original)
                    ||!root_current(b.roots[3],b.cpu_snapshot)||!api_.images.block_valid(b.cpu_snapshot))))return fail(Result::stale,"actor_block_owner_changed");}
        for(size_t i=0;i<renderer_bounds_count_;++i)if(!root_current(renderer_bounds_[i].root,renderer_bounds_[i].object)||!api_.alive(renderer_bounds_[i].object)
            ||!api_.images.renderer_bounds_current(renderer_bounds_[i].object,&renderer_bounds_[i].image))return fail(Result::stale,"actor_renderer_bounds_changed");
        for(size_t i=0;i<mesh_image_count_;++i){const auto& m=mesh_images_[i];
            if(!root_current(m.roots[0],m.object)||!root_current(m.roots[1],m.vertices)||!api_.alive(m.object)||api_.array_length(m.vertices)!=m.length)return fail(Result::stale,"actor_shadow_mesh_changed");}
        for(size_t i=0;i<talk_count_;++i){const Result result=talk_[i].validate();if(result!=Result::ok)return fail(result,talk_[i].error());}
        for(size_t i=0;i<fixed_count_;++i){const Result result=fixed_[i].validate();if(result!=Result::ok)return fail(result,fixed_[i].error());}
        return Result::ok;
    }
    Result reset_runtime_history(){
        Result result=validate();if(result!=Result::ok)return result;
        if(runtime_history_reset_)return Result::ok;
        // Preserve authored settings/references. Only these private runtime
        // scalars start from the original managed-allocation/constructor state;
        // the subsequent original root zero Evaluate applies authored time-zero
        // values before the first accepted frame. No DSP input is fabricated.
        const uint32_t zero=0;const float unset=-1.0f;
        for(size_t i=0;i<fields_count_;++i){void* object=fields_[i].object;
            if(api_.is_type(object,"VL.VLActorFacialSystem")){
                constexpr size_t offsets[]={88,96,104};
                for(size_t at:offsets)::memcpy(static_cast<uint8_t*>(object)+at,&zero,4);
                *(static_cast<uint8_t*>(object)+92)=0;*(static_cast<uint8_t*>(object)+108)=0;
                ::memcpy(static_cast<uint8_t*>(object)+100,&unset,4);
            }else if(api_.is_type(object,"VL.VLActorTalk")){
                constexpr size_t offsets[]={128,132,136,144,152,156};
                for(size_t at:offsets)::memcpy(static_cast<uint8_t*>(object)+at,&zero,4);
                *(static_cast<uint8_t*>(object)+148)=0;
            }
        }
        for(size_t i=0;i<talk_count_;++i){result=talk_[i].reset_time();if(result!=Result::ok)return fail(result,talk_[i].error());}
        for(size_t i=0;i<fixed_count_;++i){result=fixed_[i].reset_history();if(result!=Result::ok)return fail(result,fixed_[i].error());}
        runtime_history_reset_=true;return Result::ok;
    }
    Result flush_source(const Owner* owners,size_t count){
        Result result=validate();if(result!=Result::ok)return result;
        if(source_flushed_)return Result::ok;
        for(size_t i=0;i<count;++i){api_.initialize_constraints(owners[i].rig,nullptr);if(!api_.current(context_))return fail(Result::stale,"actor_presentation_owner_changed");}
        source_flushed_=true;return Result::ok;
    }
    Result initialize(const Owner* owners,size_t count){
        Result result=validate();if(result!=Result::ok)return result;
        if(initialized_)return Result::ok;
        // Original zero-pose evaluation changes collider transforms. Refresh
        // the verified live rig constraints exactly once before solver warmup.
        for(size_t i=0;i<count;++i){api_.initialize_constraints(owners[i].rig,nullptr);if(!api_.current(context_))return fail(Result::stale,"actor_presentation_owner_changed");}
        initialized_=true;return Result::ok;
    }
    Result restore(){
        if(restored_)return Result::ok;
        Result result=validate();if(result!=Result::ok)return result;
        if(!captured_)return fail(Result::invalid,"actor_presentation_snapshot_missing");
        // Validate every node and native leaf before the first restoration.
        for(size_t i=0;i<native_buffer_count_;++i){const auto& b=native_buffers_[i];if(b.length)::memcpy(b.data,b.saved,b.length*b.stride);}
        for(size_t i=0;i<talk_count_;++i){result=talk_[i].restore();if(result!=Result::ok)return fail(result,talk_[i].error());}
        for(size_t i=0;i<fixed_count_;++i){result=fixed_[i].restore();if(result!=Result::ok)return fail(result,fixed_[i].error());}
        for(size_t i=0;i<fields_count_;++i){const auto& f=fields_[i];size_t at=0;
            for(size_t j=0;j<f.schema->count;++j){const auto& span=f.schema->fields[j];
                if(!span.identity){::memcpy(static_cast<uint8_t*>(f.object)+span.offset,f.saved+at,span.bytes);}
                at+=span.bytes;}}
        for(size_t i=0;i<arrays_count_;++i)if(arrays_[i].length)::memcpy(arrays_[i].data,arrays_[i].saved,arrays_[i].length*arrays_[i].stride);
        for(size_t i=0;i<materials_count_;++i){const auto& m=materials_[i];api_.material_float_set(m.object,m.highlight);api_.material_offset_set(m.object,m.offset,nullptr);}
        for(size_t i=0;i<blends_count_;++i){const auto& b=blends_[i];for(int32_t j=0;j<b.count;++j)api_.blend_set(b.object,j,b.weights[j],nullptr);}
        for(size_t i=0;i<material_copy_count_;++i){const auto& m=material_copies_[i];api_.images.material_copy(m.source,m.snapshot,nullptr);}
        for(size_t i=0;i<block_copy_count_;++i){auto& b=block_copies_[i];
            if(b.source.original){
                if(!copy_cpu_block(b,b.cpu_snapshot,b.source.original))return fail(Result::stale,"actor_cpu_block_owner_changed");
            }else api_.images.block_set(b.source.renderer,b.empty?nullptr:b.snapshot,b.source.index,nullptr);
        }
        for(size_t i=0;i<renderer_bounds_count_;++i){const auto& b=renderer_bounds_[i];
            if(!api_.images.renderer_bounds_restore(b.object,&b.image))return fail(Result::stale,"actor_renderer_bounds_restore_interrupted");}
        for(size_t i=0;i<mesh_image_count_;++i){const auto& m=mesh_images_[i];api_.images.mesh_vertices_set(m.object,m.vertices,nullptr);api_.images.mesh_bounds_set(m.object,&m.bounds,nullptr);}
        for(size_t i=0;i<dirty_flag_count_;++i){const auto& d=dirty_flags_[i];*(static_cast<uint8_t*>(d.object)+d.offset)=d.value;}
        for(size_t i=0;i<fields_count_;++i){const auto& f=fields_[i];size_t at=0;
            for(size_t j=0;j<f.schema->count;++j){const auto& span=f.schema->fields[j];
                if(::memcmp(static_cast<uint8_t*>(f.object)+span.offset,f.saved+at,span.bytes)){return fail(Result::failed,"actor_presentation_field_restore_failed");}
                at+=span.bytes;}}
        for(size_t i=0;i<arrays_count_;++i)if(arrays_[i].length&&::memcmp(arrays_[i].data,arrays_[i].saved,arrays_[i].length*arrays_[i].stride))return fail(Result::failed,"actor_presentation_array_restore_failed");
        for(size_t i=0;i<materials_count_;++i){const auto& m=materials_[i];const auto offset=api_.material_offset_get(m.object,nullptr);
            if(api_.material_float_get(m.object)!=m.highlight||offset.x!=m.offset.x||offset.y!=m.offset.y)return fail(Result::failed,"actor_presentation_material_restore_failed");}
        for(size_t i=0;i<blends_count_;++i){const auto& b=blends_[i];for(int32_t j=0;j<b.count;++j)if(api_.blend_get(b.object,j,nullptr)!=b.weights[j])return fail(Result::failed,"actor_presentation_blend_restore_failed");}
        for(size_t i=0;i<renderer_bounds_count_;++i){const auto& b=renderer_bounds_[i];
            if(!api_.images.renderer_bounds_verify(b.object,&b.image))return fail(Result::failed,"actor_renderer_bounds_restore_failed");}
        restored_=true;error_="none";return Result::ok;
    }
    Result release(bool owned){
        if(owned)for(size_t i=0;i<block_copy_count_;++i)if(!rollback_block(block_copies_[i]))return fail(Result::stale,"actor_cpu_block_rollback_unavailable");
        if(owned&&captured_&&!restored_){const Result result=restore();if(result!=Result::ok)return result;}
        if(gate_)gate_->release(epoch_);
        for(size_t i=0;i<fields_count_;++i){if(fields_[i].root)api_.release(fields_[i].root);::free(fields_[i].saved);fields_[i]={};}
        for(size_t i=0;i<arrays_count_;++i){if(arrays_[i].root)api_.release(arrays_[i].root);::free(arrays_[i].saved);arrays_[i]={};}
        for(size_t i=0;i<materials_count_;++i){if(materials_[i].root)api_.release(materials_[i].root);materials_[i]={};}
        for(size_t i=0;i<blends_count_;++i){if(blends_[i].root)api_.release(blends_[i].root);if(blends_[i].mesh_root)api_.release(blends_[i].mesh_root);::free(blends_[i].weights);blends_[i]={};}
        for(size_t i=0;i<material_copy_count_;++i){auto& m=material_copies_[i];
            if(m.snapshot&&api_.images.material_destroy)api_.images.material_destroy(m.snapshot);
            for(auto root:m.roots){if(root)api_.release(root);}
            m={};}
        for(size_t i=0;i<block_copy_count_;++i){auto& b=block_copies_[i];
            if(b.snapshot&&api_.images.block_dispose)api_.images.block_dispose(b.snapshot,nullptr);
            if(b.cpu_snapshot&&api_.images.block_dispose)api_.images.block_dispose(b.cpu_snapshot,nullptr);
            for(auto root:b.roots){if(root)api_.release(root);}
            b={};}
        for(size_t i=0;i<renderer_bounds_count_;++i){if(renderer_bounds_[i].root)api_.release(renderer_bounds_[i].root);renderer_bounds_[i]={};}
        for(size_t i=0;i<mesh_image_count_;++i){for(auto root:mesh_images_[i].roots)if(root)api_.release(root);mesh_images_[i]={};}
        material_copy_count_=block_copy_count_=renderer_bounds_count_=mesh_image_count_=0;
        for(size_t i=0;i<native_buffer_count_;++i){::free(native_buffers_[i].saved);native_buffers_[i]={};}
        native_buffer_count_=0;dirty_flag_count_=0;
        for(size_t i=0;i<talk_count_;++i){talk_[i].clear();}
        talk_count_=0;
        for(size_t i=0;i<fixed_count_;++i){fixed_[i].clear();}
        fixed_count_=0;
        fields_count_=arrays_count_=materials_count_=blends_count_=bytes_=0;inventory_={};
        configured_=captured_=restored_=initialized_=source_flushed_=runtime_history_reset_=false;epoch_=0;context_=nullptr;return Result::ok;
    }
};

enum class MixerKind:uint8_t {parameter,timeline};
struct MixerOwner {void* actor=nullptr;void* player=nullptr;void* instance=nullptr;Handle graph{},playable{};MixerKind kind=MixerKind::parameter;uint16_t index=0xffff;};
struct ManagedMixerApi {
    bool (*mapped)(const void*,size_t,bool)=nullptr;bool (*is_type)(void*,const char*)=nullptr;
    uint32_t (*retain)(void*)=nullptr;void* (*target)(uint32_t)=nullptr;void (*release)(uint32_t)=nullptr;
    size_t (*array_length)(void*)=nullptr;void* (*array_data)(void*)=nullptr;
    bool (*held_fenced)(void*,const MixerOwner&)=nullptr;
    // Resolve only this original ActorPlayer's exact base/layer/timeline slot.
    // New timeline instances require an authorized original Root rebuild token.
    bool (*resolve)(void*,const MixerOwner&,MixerOwner&)=nullptr;
    bool (*allow_rebuilt)(void*,const MixerOwner&,const MixerOwner&)=nullptr;
    bool (*callbacks_safe)(void*,const MixerOwner&)=nullptr;
};
// Factory-clean persistent default/layer ParamMixers are supported. Keeping
// their empty native layer records preserves every handle lifetime. A previous
// home/ADV clip queue needs a separate logical clone/remap and is rejected here
// before any export mutation; ResetParam destroys twelve handles, so it is not
// an acceptable scalar rewind. TimelineMixer is rebuilt by its real producer.
class ManagedMixerSnapshot {
    ManagedMixerApi api_{};void* context_=nullptr;MixerOwner source_{};uint32_t roots_[3]{};
    void* layers_=nullptr;Handle layer_{};void* delegates_[2]{};
    uint8_t scalars_[40]{};int32_t timeline_inputs_=0,timeline_index_=0;double timeline_delay_=0;
    bool captured_=false,restored_=false;const char* error_="none";
    static bool same(Handle a,Handle b){return a.handle==b.handle&&a.version==b.version;}
    Result fail(Result r,const char* code){error_=code;return r;}
    template<class T>bool read(const void* p,size_t at,T& value)const{if(!p||!api_.mapped(static_cast<const uint8_t*>(p)+at,sizeof(T),false))return false;::memcpy(&value,static_cast<const uint8_t*>(p)+at,sizeof(T));return true;}
    bool shape(MixerOwner& now){
        if(!roots_[2]||api_.target(roots_[2])!=source_.player)return false;
        if(!api_.resolve(context_,source_,now)||now.actor!=source_.actor||now.player!=source_.player||now.kind!=source_.kind||now.index!=source_.index||!same(now.graph,source_.graph))return false;
        const char* type=now.kind==MixerKind::parameter?"VL.Playables.VLAnimationClipParamMixerPlayable":"VL.Timeline.VLAnimationClipPlayerTimelineMixerPlayable";
        if(!now.instance||!api_.is_type(now.instance,type)||!api_.held_fenced(context_,now))return false;
        if(now.instance!=source_.instance||!same(now.playable,source_.playable))return now.kind==MixerKind::timeline&&api_.allow_rebuilt(context_,source_,now);
        return roots_[0]&&api_.target(roots_[0])==source_.instance;
    }
    bool clean(void* p,bool compare){
        void *array=nullptr,*pass=nullptr,*param=nullptr,*layer_param=nullptr,*previous=nullptr;int32_t count=0;Handle layer{};void* delegates[2]{};
        if(!read(p,24,layer)||!read(p,40,array)||!read(p,48,count)||!read(p,56,pass)||!read(p,72,param)||!read(p,80,layer_param)||!read(p,88,previous)
            ||!read(p,112,delegates[0])||!read(p,120,delegates[1])||count||pass||param||layer_param||previous
            ||!array||!api_.is_type(array,"System.Array")||api_.array_length(array)!=4)return false;
        void* data=api_.array_data(array);if(!data||!api_.mapped(data,4*48,false))return false;
        for(size_t i=0;i<4*48;++i)if(static_cast<const uint8_t*>(data)[i])return false;
        if(compare&&(array!=layers_||!same(layer,layer_)||delegates[0]!=delegates_[0]||delegates[1]!=delegates_[1]||!roots_[1]||api_.target(roots_[1])!=array))return false;
        if(!compare){layers_=array;layer_=layer;delegates_[0]=delegates[0];delegates_[1]=delegates[1];}
        return true;
    }
    void scalar_copy(void* object,bool restore){
        constexpr uint16_t offsets[]={16,20,48,64,96,100,104};constexpr uint16_t bytes[]={4,1,4,4,4,4,1};size_t at=0;
        for(size_t i=0;i<7;++i){if(restore)::memcpy(static_cast<uint8_t*>(object)+offsets[i],scalars_+at,bytes[i]);else ::memcpy(scalars_+at,static_cast<uint8_t*>(object)+offsets[i],bytes[i]);at+=bytes[i];}
    }
public:
    ManagedMixerSnapshot()=default;ManagedMixerSnapshot(const ManagedMixerSnapshot&)=delete;ManagedMixerSnapshot& operator=(const ManagedMixerSnapshot&)=delete;
    const char* error()const{return error_;}bool captured()const{return captured_;}
    Result capture(ManagedMixerApi api,void* context,MixerOwner owner){
        if(captured_){return fail(Result::invalid,"actor_mixer_already_captured");}
        clear();api_=api;context_=context;source_=owner;
        if(!api_.mapped||!api_.is_type||!api_.retain||!api_.target||!api_.release||!api_.array_length||!api_.array_data||!api_.held_fenced||!api_.resolve||!api_.allow_rebuilt||!api_.callbacks_safe||!owner.actor||!owner.player||!owner.instance||!owner.graph.handle||!owner.playable.handle)
            return fail(Result::invalid,"actor_mixer_api_unavailable");
        roots_[0]=api_.retain(owner.instance);roots_[2]=api_.retain(owner.player);MixerOwner now{};
        if(!roots_[0]||!roots_[2]||api_.target(roots_[2])!=owner.player||!shape(now)||now.instance!=owner.instance)return fail(Result::stale,"actor_mixer_owner_changed");
        if(owner.kind==MixerKind::parameter){
            if(!clean(owner.instance,false)||!api_.callbacks_safe(context_,owner))return fail(Result::unsupported,"actor_mixer_existing_default_queue_unsupported");
            roots_[1]=api_.retain(layers_);if(!roots_[1]||api_.target(roots_[1])!=layers_||!api_.mapped(owner.instance,128,true))return fail(Result::stale,"actor_mixer_state_unmapped");
            scalar_copy(owner.instance,false);
        }else{
            if(!read(owner.instance,16,timeline_delay_)||!read(owner.instance,24,timeline_inputs_)||!read(owner.instance,48,timeline_index_)
                ||!__builtin_isfinite(timeline_delay_)||timeline_inputs_<0||timeline_inputs_>4096||timeline_index_<0||timeline_index_>timeline_inputs_)
                return fail(Result::unsupported,"actor_timeline_mixer_layout_invalid");
        }
        captured_=true;restored_=false;return Result::ok;
    }
    Result validate(){if(!captured_)return fail(Result::invalid,"actor_mixer_snapshot_missing");MixerOwner now{};
        if(!shape(now))return fail(Result::stale,"actor_mixer_owner_changed");
        if(now.kind==MixerKind::parameter&&(!clean(now.instance,true)||!api_.callbacks_safe(context_,now)))return fail(Result::stale,"actor_mixer_default_queue_changed");
        if(now.kind==MixerKind::timeline){int32_t inputs=0,index=0;if(!read(now.instance,24,inputs)||!read(now.instance,48,index)||inputs!=timeline_inputs_||index!=timeline_index_)
            {return fail(Result::stale,"actor_timeline_mixer_factory_differs");}}
        return Result::ok;
    }
    Result reset(){Result r=validate();if(r!=Result::ok)return r;MixerOwner now{};if(!shape(now))return fail(Result::stale,"actor_mixer_owner_changed");
        if(now.kind==MixerKind::parameter){constexpr size_t offsets[]={16,48,64,96,100};const uint32_t zero=0;for(size_t at:offsets)::memcpy(static_cast<uint8_t*>(now.instance)+at,&zero,4);*(static_cast<uint8_t*>(now.instance)+104)=0;}
        else{const double zero=0;::memcpy(static_cast<uint8_t*>(now.instance)+16,&zero,8);}return Result::ok;
    }
    Result restore(){Result r=validate();if(r!=Result::ok)return r;if(restored_)return Result::ok;MixerOwner now{};if(!shape(now))return fail(Result::stale,"actor_mixer_owner_changed");
        if(now.kind==MixerKind::parameter)scalar_copy(now.instance,true);
        else ::memcpy(static_cast<uint8_t*>(now.instance)+16,&timeline_delay_,8);
        restored_=true;return Result::ok;
    }
    void clear(){for(auto root:roots_)if(root&&api_.release)api_.release(root);for(auto& root:roots_)root=0;api_={};context_=nullptr;source_={};layers_=nullptr;layer_={};delegates_[0]=delegates_[1]=nullptr;captured_=restored_=false;error_="none";}
};

namespace temporal = idoly_mp4_native_temporal;
struct TemporalBinding {
    temporal::Api api{};const temporal::Layout* layouts=nullptr;size_t layout_count=0;
    temporal::Input nodes[512]{};size_t node_count=0;
    ManagedMixerApi mixer_api{};MixerOwner mixers[16]{};size_t mixer_count=0;
    int32_t (*input_count)(Handle*,Method*)=nullptr;
    void (*input)(Handle*,int32_t,Handle*,Method*)=nullptr;
    float (*weight_get)(Handle*,int32_t,Method*)=nullptr;
    void (*weight_set)(Handle*,int32_t,float,Method*)=nullptr;
};
// All nodes include zero-weight/default branches. The checkpoint restores exact
// surviving node histories, authorized producer remaps and original edge weights;
// it never rewrites native graph links or copies former Playable handles.
class GraphTemporalScope {
    struct Edge {uint16_t parent=0,index=0,child=0xffff;float weight=0;};
    struct Image {
        TemporalBinding binding{};temporal::SourceTemporalSnapshot<512> native;
        ManagedMixerSnapshot mixers[16]{};size_t mixer_count=0;
        Edge edges[4096]{};size_t edge_count=0;uint64_t epoch=0;temporal::Handle graph{};
        Image(const TemporalBinding& b,uint64_t e,Handle g):binding(b),native(b.api,b.layouts,b.layout_count),epoch(e),graph{g.handle,g.version,0}{}
    };
    Image* image_=nullptr;bool captured_=false,restored_=false;const char* error_="none";
    static Handle actor_handle(temporal::Handle h){return {h.slot,h.version,h.padding};}
    static temporal::Handle native_handle(Handle h){return {h.handle,h.version,h.padding};}
    Result fail(Result r,const char* code){error_=code;return r;}
    bool ready(const TemporalBinding& b)const{return b.layouts&&b.layout_count==5&&b.node_count&&b.node_count<=512
        &&b.mixer_count<=16&&b.input_count&&b.input&&b.weight_get&&b.weight_set&&b.api.begin_fence&&b.api.fence_held&&b.api.end_fence
        &&b.api.source_current&&b.api.inventory_exact&&b.api.remap&&b.api.manager_quiescent;}
    bool boundary(const temporal::Lease& lease)const{
        const auto& a=image_->binding.api;
        return lease.epoch==image_->epoch&&lease.ticket&&a.fence_held(a.context,lease)
            &&a.source_current(a.context,image_->epoch)&&a.manager_quiescent(a.context,lease);
    }
    struct Fence {
        const temporal::Api& a;temporal::Lease lease{};bool acquired=false;
        Fence(const temporal::Api& api,uint64_t epoch):a(api){acquired=a.begin_fence(a.context,epoch,lease);}
        ~Fence(){if(lease.ticket)a.end_fence(a.context,lease);}
    };
    bool resolve(temporal::Input* targets){
        const auto& b=image_->binding;
        for(size_t i=0;i<b.node_count;++i){targets[i]=b.nodes[i];
            if(b.nodes[i].lifetime==temporal::Lifetime::rebuilt_logical){
                temporal::Input now{};
                if(!b.api.remap(b.api.context,image_->epoch,b.nodes[i],now)||now.kind!=b.nodes[i].kind
                    ||now.lifetime!=b.nodes[i].lifetime||!temporal::same(now.logical,b.nodes[i].logical))return false;
                targets[i]=now;
            }
            for(size_t j=0;j<i;++j){if(temporal::same(targets[j].handle,targets[i].handle))return false;}
        }
        return b.api.inventory_exact(b.api.context,image_->graph,targets,b.node_count);
    }
    bool edges_current(temporal::Input* targets){
        const auto& b=image_->binding;size_t edge=0;
        for(size_t i=0;i<b.node_count;++i){Handle parent=actor_handle(targets[i].handle);const int32_t count=b.input_count(&parent,nullptr);
            if(count<0||count>128)return false;
            for(int32_t j=0;j<count;++j){
                if(edge==image_->edge_count)return false;
                const auto& expected=image_->edges[edge++];Handle child{};b.input(&parent,j,&child,nullptr);
                if(expected.parent!=i||expected.index!=j)return false;
                if(expected.child==0xffff){if(child.handle)return false;}
                else if(expected.child>=b.node_count||!temporal::same(native_handle(child),targets[expected.child].handle))return false;
            }
        }
        return edge==image_->edge_count;
    }
public:
    GraphTemporalScope()=default;GraphTemporalScope(const GraphTemporalScope&)=delete;GraphTemporalScope& operator=(const GraphTemporalScope&)=delete;
    ~GraphTemporalScope(){clear();}
    const char* error()const{return error_;}bool captured()const{return captured_;}
    size_t bytes()const{return image_?sizeof(Image):0;}
    Result capture(TemporalBinding binding,uint64_t epoch,Handle graph,size_t budget){
        if(captured_)return Result::ok;
        if(image_||!epoch||!graph.handle||!ready(binding))return fail(Result::unsupported,"actor_temporal_binding_unavailable");
        if(sizeof(Image)>budget)return fail(Result::unsupported,"actor_temporal_snapshot_too_large");
        void* memory=::malloc(sizeof(Image));if(!memory)return fail(Result::failed,"actor_temporal_allocation_failed");
        image_=new(idoly_mp4_actor_placement::Address{memory})Image(binding,epoch,graph);
        Fence fence(binding.api,epoch);if(!fence.acquired||!boundary(fence.lease))return fail(Result::stale,"actor_temporal_fence_unavailable");
        for(size_t i=0;i<binding.mixer_count;++i){image_->mixer_count=i+1;
            const Result result=image_->mixers[i].capture(binding.mixer_api,binding.api.context,binding.mixers[i]);
            if(result!=Result::ok)return fail(result,image_->mixers[i].error());}
        for(size_t i=0;i<binding.node_count;++i){Handle parent=actor_handle(binding.nodes[i].handle);const int32_t count=binding.input_count(&parent,nullptr);
            if(count<0||count>128)return fail(Result::unsupported,"actor_temporal_edge_limit");
            for(int32_t j=0;j<count;++j){
                if(image_->edge_count==4096)return fail(Result::unsupported,"actor_temporal_edge_limit");
                Handle child{};binding.input(&parent,j,&child,nullptr);uint16_t child_index=0xffff;
                if(child.handle){for(size_t k=0;k<binding.node_count;++k){if(temporal::same(native_handle(child),binding.nodes[k].handle))child_index=static_cast<uint16_t>(k);}
                    if(child_index==0xffff)return fail(Result::unsupported,"actor_temporal_incomplete_graph");}
                const float weight=binding.weight_get(&parent,j,nullptr);
                if(!__builtin_isfinite(weight))return fail(Result::unsupported,"actor_temporal_weight_nonfinite");
                image_->edges[image_->edge_count++]={static_cast<uint16_t>(i),static_cast<uint16_t>(j),child_index,weight};
            }
        }
        if(!boundary(fence.lease)||!image_->native.capture(epoch,image_->graph,binding.nodes,binding.node_count)||!image_->native.component_closed())
            return fail(Result::unsupported,"actor_temporal_native_capture_failed");
        captured_=true;restored_=false;return Result::ok;
    }
    Result reset_runtime_history(){
        if(!captured_||!image_)return fail(Result::invalid,"actor_temporal_snapshot_missing");
        auto& b=image_->binding;Fence fence(b.api,image_->epoch);
        if(!fence.acquired||!boundary(fence.lease))return fail(Result::stale,"actor_temporal_fence_unavailable");
        for(size_t i=0;i<image_->mixer_count;++i){const Result result=image_->mixers[i].validate();if(result!=Result::ok)return fail(result,image_->mixers[i].error());}
        for(size_t i=0;i<image_->mixer_count;++i){const Result result=image_->mixers[i].reset();if(result!=Result::ok)return fail(result,image_->mixers[i].error());}
        return Result::ok;
    }
    Result preflight_restore(){
        if(!captured_||!image_)return fail(Result::invalid,"actor_temporal_snapshot_missing");
        auto& b=image_->binding;Fence fence(b.api,image_->epoch);temporal::Input targets[512]{};
        if(!fence.acquired||!boundary(fence.lease)||!resolve(targets)||!edges_current(targets))return fail(Result::stale,"actor_temporal_graph_changed");
        for(size_t i=0;i<image_->mixer_count;++i){const Result result=image_->mixers[i].validate();if(result!=Result::ok)return fail(result,image_->mixers[i].error());}
        if(!image_->native.validate_scalar_component())return fail(Result::stale,"actor_temporal_native_admission_failed");
        return boundary(fence.lease)?Result::ok:fail(Result::stale,"actor_temporal_owner_changed");
    }
    Result restore(){
        if(!captured_||!image_)return fail(Result::invalid,"actor_temporal_snapshot_missing");
        if(restored_)return Result::ok;
        auto& b=image_->binding;Fence fence(b.api,image_->epoch);temporal::Input targets[512]{};
        if(!fence.acquired||!boundary(fence.lease)||!resolve(targets)||!edges_current(targets))return fail(Result::stale,"actor_temporal_graph_changed");
        for(size_t i=0;i<image_->mixer_count;++i){const Result result=image_->mixers[i].validate();if(result!=Result::ok)return fail(result,image_->mixers[i].error());}
        if(!image_->native.validate_scalar_component())return fail(Result::stale,"actor_temporal_native_admission_failed");
        for(size_t i=0;i<image_->mixer_count;++i){const Result result=image_->mixers[i].restore();if(result!=Result::ok)return fail(result,image_->mixers[i].error());}
        // All edge targets are preflighted before native cleanup/scalar writes.
        // The helper separately preflights every native node/clip binding.
        if(!image_->native.restore_scalar_component())return fail(Result::failed,"actor_temporal_native_restore_failed");
        if(!boundary(fence.lease))return fail(Result::stale,"actor_temporal_owner_changed");
        for(size_t i=0;i<image_->edge_count;++i){const auto& e=image_->edges[i];Handle parent=actor_handle(targets[e.parent].handle);
            if(!boundary(fence.lease))return fail(Result::stale,"actor_temporal_owner_changed");
            b.weight_set(&parent,e.index,e.weight,nullptr);
            if(!boundary(fence.lease)||b.weight_get(&parent,e.index,nullptr)!=e.weight)return fail(Result::failed,"actor_temporal_weight_restore_failed");
        }
        restored_=true;return Result::ok;
    }
    bool component_closed()const{return captured_&&image_&&image_->native.component_closed();}
    void clear(){if(image_){image_->~Image();::free(image_);}image_=nullptr;captured_=restored_=false;error_="none";}
};

struct StateApi {
    // These contextual callbacks prove the selected source, original installed
    // routes, held native clock, and root pose. They are mandatory, not no-op
    // dependent-state fallbacks.
    bool (*source_current)(void*, const Owner&) = nullptr;
    bool (*clock_held)(void*) = nullptr;
    bool (*routes_ready)(void*) = nullptr;
    Result (*prepare_zero_pose)(void*) = nullptr;
    double (*root_time)(void*) = nullptr;
    bool (*mapped)(const void*, size_t, bool writable) = nullptr;
    bool (*is_type)(void*, const char*) = nullptr;
    bool (*alive)(void*) = nullptr;
    uint32_t (*gc_new)(void*, bool) = nullptr;
    void* (*gc_target)(uint32_t) = nullptr;
    void (*gc_free)(uint32_t) = nullptr;
    void* (*output_target)(Handle*, Method*) = nullptr;
    void* (*job_type)(Handle*, Method*) = nullptr;
    bool (*job_type_is_actor)(void*) = nullptr;
    void* (*job_data)(Handle*, Method*) = nullptr;
    int32_t (*animator_mode)(void*, Method*) = nullptr;
    int32_t (*animator_culling)(void*, Method*) = nullptr;
    void (*job_complete)(void*, Method*) = nullptr;
    void (*rig_reset_dynamic)(void*, Method*) = nullptr;
    void (*rig_reset_breast)(void*, Method*) = nullptr;
    bool (*graph_valid)(Handle*, Method*) = nullptr;
    bool (*graph_mode)(Handle*, int32_t*) = nullptr;
    void (*graph_set_mode)(Handle*, int32_t, Method*) = nullptr;
    void (*graph_evaluate)(Handle*, float, Method*) = nullptr;
    int32_t (*graph_root_count)(Handle*, Method*) = nullptr;
    void (*graph_root)(Handle*, int32_t, Handle*, Method*) = nullptr;
    bool (*playable_valid)(Handle*, Method*) = nullptr;
    int32_t (*playable_input_count)(Handle*, Method*) = nullptr;
    void (*playable_input)(Handle*, int32_t, Handle*, Method*) = nullptr;
    double (*playable_time)(Handle*, Method*) = nullptr;
    void* (*root_transform)(void*, Method*) = nullptr;
    // Original GameObject.GetComponentsInternal(TypeTransform, true, true,
    // true, false, null), returning an actual typed Transform[] array.
    void* (*actor_transforms)(void*) = nullptr;
    size_t (*array_length)(void*) = nullptr;
    void* (*array_data)(void*) = nullptr;
    void* (*transform_parent)(void*, Method*) = nullptr;
    void (*local_position)(void*, Vector3*, Method*) = nullptr;
    void (*local_rotation)(void*, Quaternion*, Method*) = nullptr;
    void (*local_scale)(void*, Vector3*, Method*) = nullptr;
    void (*set_local_position_rotation)(void*, const Vector3*, const Quaternion*, Method*) = nullptr;
    void (*set_local_scale)(void*, const Vector3*, Method*) = nullptr;
    // Exact current owned native clock has consumed logical_serial-1. This
    // publication witness is checked after the native kernel, when its deltas
    // are nonzero; a held-clock predicate is deliberately insufficient.
    bool (*clock_granted)(void*, uint64_t logical_serial) = nullptr;
    bool (*node_supported)(void*, const Owner&, Handle) = nullptr;
    bool (*graph_playing)(Handle*,Method*) = nullptr;
    void (*graph_play)(Handle*,Method*) = nullptr;
    void (*graph_stop)(Handle*,Method*) = nullptr;
    // -1 unverified, 0 legitimately inactive/output-weight-zero, 1 an active
    // AlwaysAnimate target whose installed owned job must consume this step.
    int32_t (*job_expected)(void*,const Owner&) = nullptr;
    bool (*temporal_binding)(void*,const Owner&,TemporalBinding&) = nullptr;
};
struct StateLayout {
    size_t cached_ptr = 0x10, native_animator_job = 0x238;
    size_t rig_job = 0x50, rig_initialized = 0x58;
};
constexpr size_t actor_job_bytes = 0x168, actor_job_time = 0x164;
constexpr size_t row_strides[4] = {0x338, 0x84, 0x13c, 0x7c};
constexpr size_t max_rows = 8192, max_transforms = 4096, max_playables = 512;
constexpr size_t max_snapshot_bytes = 64u * 1024u * 1024u;
constexpr size_t warmup_steps = 180, warmup_steps_per_call = 6;

// This scope owns only selected actors. The enclosing playback scope owns root
// director/camera/audio/particle preparation and applies the previous root time
// before restore(). A changed actor graph is rejected even after an intentional
// root reconstruction: old native stream/property handles are not transferable.
class Scope {
    struct Buffer {
        uintptr_t header = 0, data = 0;
        int32_t length = 0, capacity = 0;
        size_t bytes = 0;
        uint8_t* saved = nullptr;
    };
    struct PoseEntry { void* transform = nullptr; void* parent = nullptr; LocalPose pose{}; };
    struct TimeEntry { Handle playable{}; double time = 0; };
    struct Actor {
        Owner source{};
        uint32_t roots[5]{};
        uintptr_t native_animator = 0;
        void* live_job = nullptr;
        OwnershipKey key{};
        Buffer buffers[4]{};
        uint8_t saved_job[actor_job_bytes]{};
        int32_t previous_mode = -1;
        bool previous_playing=false,playing_captured=false;
        bool mode_changed = false, captured = false;
        uint32_t transforms_root = 0;
        void* transforms_array = nullptr;
        void* root_transform = nullptr;
        PoseEntry* poses = nullptr;
        size_t pose_count = 0;
        GraphTemporalScope temporal;
        TimeEntry* times = nullptr;
        size_t time_count = 0;
    };
    StateApi api_{};
    StateLayout layout_{};
    WorkerGate* gate_ = nullptr;
    PresentationScope* presentation_ = nullptr;
    Actor actors_[max_owned_jobs]{};
    size_t count_ = 0, bytes_ = 0, warmed_ = 0;
    void* context_ = nullptr;
    uint64_t epoch_ = 0, serial_ = 0, simulation_serial_ = 0, prepared_serial_ = 0, checked_simulation_serial_ = 0;
    uint32_t expected_jobs_=0,completed_jobs_=0;bool step_failed_=false;
    uint32_t simulation_hz_=60;
    bool configured_ = false, published_ = false, reset_started_ = false,
        reset_done_ = false, changed_native_ = false, restored_ = false,
        zero_pose_prepared_ = false, witness_captured_ = false;
    const char* error_ = "none";
    static bool same(Handle a, Handle b) { return a.handle == b.handle && a.version == b.version; }
    static bool finite(float value) { return __builtin_isfinite(value); }
    static bool finite(LocalPose pose) {
        return finite(pose.position.x) && finite(pose.position.y) && finite(pose.position.z)
            && finite(pose.rotation.x) && finite(pose.rotation.y) && finite(pose.rotation.z)
            && finite(pose.rotation.w) && finite(pose.scale.x) && finite(pose.scale.y) && finite(pose.scale.z);
    }
    template<class T> bool read(const void* source, size_t offset, T& result) const {
        if (!source || !api_.mapped(static_cast<const uint8_t*>(source) + offset, sizeof(T), false)) return false;
        ::memcpy(&result, static_cast<const uint8_t*>(source) + offset, sizeof(T));
        return true;
    }
    Result fail(Result result, const char* error) { error_ = error; return result; }
    bool complete_api() const {
        return api_.source_current && api_.clock_held && api_.routes_ready && api_.prepare_zero_pose
            && api_.root_time && api_.mapped && api_.is_type && api_.alive && api_.gc_new
            && api_.gc_target && api_.gc_free && api_.output_target && api_.job_type
            && api_.job_type_is_actor && api_.job_data && api_.animator_mode && api_.animator_culling
            && api_.job_complete && api_.rig_reset_dynamic && api_.rig_reset_breast
            && api_.graph_valid && api_.graph_mode && api_.graph_set_mode && api_.graph_evaluate
            && api_.graph_root_count && api_.graph_root && api_.playable_valid
            && api_.playable_input_count && api_.playable_input && api_.playable_time
            && api_.root_transform && api_.actor_transforms && api_.array_length && api_.array_data
            && api_.transform_parent && api_.local_position && api_.local_rotation && api_.local_scale
            && api_.set_local_position_rotation && api_.set_local_scale && api_.clock_granted;
    }
    bool roots_current(const Actor& actor) const {
        void* values[5] = {actor.source.actor, actor.source.extension, actor.source.rig,
            actor.source.builder, actor.source.animator};
        for (size_t i = 0; i < 5; ++i)
            if (actor.roots[i] && api_.gc_target(actor.roots[i]) != values[i]) return false;
        return true;
    }
    bool owner_current(Actor& actor) const {
        return api_.source_current(context_, actor.source) && roots_current(actor)
            && api_.graph_valid(&actor.source.graph, nullptr)
            && api_.playable_valid(&actor.source.playable, nullptr)
            && api_.alive(actor.source.actor) && api_.alive(actor.source.rig)
            && api_.alive(actor.source.animator)
            && api_.output_target(&actor.source.output, nullptr) == actor.source.animator;
    }
    Result retain(Actor& actor) {
        void* values[5] = {actor.source.actor, actor.source.extension, actor.source.rig,
            actor.source.builder, actor.source.animator};
        const char* types[5] = {"VL.Core.VLActorController", "VL.VLActorActorSwing",
            "ActorSwing.ActorSwingRig", "ActorSwing.ActorSwingBuilder", "UnityEngine.Animator"};
        for (size_t i = 0; i < 5; ++i) {
            if (!values[i] || !api_.is_type(values[i], types[i]))
                return fail(Result::unsupported, "actor_state_owner_type_differs");
            if (!actor.roots[i]) {
                actor.roots[i] = api_.gc_new(values[i], false);
                if (!actor.roots[i] || api_.gc_target(actor.roots[i]) != values[i])
                    return fail(Result::failed, "actor_state_root_failed");
            }
        }
        if (!owner_current(actor)) return fail(Result::stale, "actor_state_owner_changed");
        if (api_.animator_mode(actor.source.animator, nullptr) != 0
            || api_.animator_culling(actor.source.animator, nullptr) != 0)
            return fail(Result::unsupported, "actor_state_animator_mode_unsupported");
        uint8_t initialized = 0; void* boxed = nullptr;
        if (!read(actor.source.rig, layout_.rig_initialized, initialized) || initialized != 1
            || !read(actor.source.rig, layout_.rig_job, boxed)
            || !boxed || !api_.is_type(boxed, "ActorSwing.ActorSwingJob"))
            return fail(Result::unsupported, "actor_state_rig_not_initialized");
        uintptr_t native = 0;
        if (!read(actor.source.animator, layout_.cached_ptr, native) || !native
            || !api_.mapped(reinterpret_cast<void*>(native + layout_.native_animator_job), 16, true))
            return fail(Result::unsupported, "actor_state_animator_native_unavailable");
        if (actor.native_animator && native != actor.native_animator)
            return fail(Result::stale, "actor_state_animator_native_changed");
        actor.native_animator = native;
        if (!api_.job_type_is_actor(api_.job_type(&actor.source.playable, nullptr)))
            return fail(Result::unsupported, "actor_state_job_type_differs");
        return Result::ok;
    }
    Result fence(Actor& actor) {
        if (!owner_current(actor)) return fail(Result::stale, "actor_state_owner_changed");
        uintptr_t native = 0;
        if (!read(actor.source.animator, layout_.cached_ptr, native)
            || native != actor.native_animator || !native)
            return fail(Result::stale, "actor_state_animator_native_changed");
        void* handle = reinterpret_cast<void*>(native + layout_.native_animator_job);
        if (!api_.mapped(handle, 16, true)) return fail(Result::stale, "actor_state_fence_unmapped");
        // The exact original prepare callback completes this ACTUAL field;
        // completing a copy would leave a stale owner handle behind.
        api_.job_complete(handle, nullptr);
        uint64_t group = 0; int32_t version = 0;
        if (!read(handle, 0, group) || !read(handle, 8, version))
            return fail(Result::stale, "actor_state_fence_unmapped");
        if (group || version) return fail(Result::waiting, "actor_state_fence_pending");
        if (!owner_current(actor)) return fail(Result::stale, "actor_state_owner_changed");
        return Result::ok;
    }
    Result prepared_fence_current(Actor& actor) {
        // Preparation already completed the actual stored handle. Native
        // TimeManager.Update contains no actor evaluation. Do not execute a
        // new Complete after its clock grant: an unexpected new job means the
        // publication window changed and the step must be aborted.
        if (!owner_current(actor)) return fail(Result::stale, "actor_state_owner_changed");
        uintptr_t native = 0;
        if (!read(actor.source.animator, layout_.cached_ptr, native)
            || native != actor.native_animator || !native)
            return fail(Result::stale, "actor_state_animator_native_changed");
        void* handle = reinterpret_cast<void*>(native + layout_.native_animator_job);
        uint64_t group = 0; int32_t version = 0;
        if (!api_.mapped(handle, 16, true) || !read(handle, 0, group) || !read(handle, 8, version))
            return fail(Result::stale, "actor_state_fence_unmapped");
        if (group || version) return fail(Result::stale, "actor_state_fence_changed_after_prepare");
        return Result::ok;
    }
    Result inspect_job(Actor& actor, bool initial) {
        if (!api_.job_type_is_actor(api_.job_type(&actor.source.playable, nullptr)))
            return fail(Result::unsupported, "actor_state_job_type_differs");
        void* job = api_.job_data(&actor.source.playable, nullptr);
        if (!job || !api_.mapped(job, actor_job_bytes, true))
            return fail(Result::unsupported, "actor_state_job_unmapped");
        if (!initial && job != actor.live_job) return fail(Result::stale, "actor_state_job_generation_changed");
        // ProcessAnimation changes only the trailing scalar _time in the job
        // value. NativeArrays, the map and stream/property handles in the
        // prefix must retain their exact captured identities before a raw
        // restore; four shared NativeLists alone do not establish that.
        if (!initial && actor.captured && ::memcmp(actor.saved_job, job, actor_job_time))
            return fail(Result::stale, "actor_state_job_configuration_changed");
        const auto key = key_from_original_job(job);
        if (!key.valid() || (!initial && !(key == actor.key)))
            return fail(Result::stale, "actor_state_job_buffers_changed");
        void* boxed = nullptr;
        if (!read(actor.source.rig, layout_.rig_job, boxed) || !boxed
            || !api_.is_type(boxed, "ActorSwing.ActorSwingJob")
            || !api_.mapped(static_cast<const uint8_t*>(boxed) + 16, actor_job_bytes, false)
            || !(key_from_original_job(static_cast<const uint8_t*>(boxed) + 16) == key))
            return fail(Result::stale, "actor_state_rig_job_buffers_changed");
        for (size_t i = 0; i < 4; ++i) {
            Buffer found{}; found.header = key.list_headers[i];
            if (!found.header || !read(reinterpret_cast<void*>(found.header), 0, found.data)
                || !read(reinterpret_cast<void*>(found.header), 8, found.length)
                || !read(reinterpret_cast<void*>(found.header), 12, found.capacity)
                || found.length < 0 || found.capacity < found.length
                || static_cast<size_t>(found.capacity) > max_rows)
                return fail(Result::unsupported, "actor_state_native_list_invalid");
            found.bytes = static_cast<size_t>(found.length) * row_strides[i];
            if (found.bytes && (!found.data || !api_.mapped(reinterpret_cast<void*>(found.data), found.bytes, true)))
                return fail(Result::unsupported, "actor_state_native_list_unmapped");
            if (!initial) {
                const auto& prior = actor.buffers[i];
                if (found.header != prior.header || found.data != prior.data
                    || found.length != prior.length || found.capacity != prior.capacity)
                    return fail(Result::stale, "actor_state_native_list_changed");
                if (actor.captured && prior.saved) {
                    for (int32_t row = 0; row < found.length; ++row) {
                        const size_t at = static_cast<size_t>(row) * row_strides[i];
                        if (!row_binding_identity(i, prior.saved + at,
                                reinterpret_cast<uint8_t*>(found.data) + at))
                            return fail(Result::stale, "actor_state_row_binding_changed");
                    }
                }
            } else actor.buffers[i] = found;
        }
        // Both original managed and Burst dynamic/breast solvers integrate
        // their authored 0.01667 step even when stream delta is 1/120 (or 0).
        // A 120 Hz clock/encoder does not authorize twice as many solver steps.
        // Reject before publishing a grant or changing/resetting source state.
        if (simulation_hz_==120 && (actor.buffers[0].length || actor.buffers[2].length))
            return fail(Result::unsupported, "actor_state_fixed_step_120hz_unsupported");
        if (initial) { actor.live_job = job; actor.key = key; }
        return Result::ok;
    }
    static bool identity(const uint8_t* old, const uint8_t* now, size_t offset, size_t bytes) {
        return !::memcmp(old + offset, now + offset, bytes);
    }
    static bool stream_identity(const uint8_t* old, const uint8_t* now, size_t at) {
        // Native Resolve changes version0/skeletonIndex8 in-place. The
        // registered stream handleIndex4 identifies the original binding.
        return identity(old, now, at + 4, 4);
    }
    static bool readonly_identity(const uint8_t* old, const uint8_t* now, size_t at) {
        return stream_identity(old, now, at)
            && identity(old, now, at + 16, 4) // Scene definition index.
            && identity(old, now, at + 20, 1); // Original stream/scene choice.
    }
    static bool row_binding_identity(size_t kind, const uint8_t* old, const uint8_t* now) {
        if (kind == 0) {
            if (!stream_identity(old, now, 0x100) || !readonly_identity(old, now, 0x10c)) return false;
            for (size_t at = 0x134; at < 0x304; at += 16)
                if (!identity(old, now, at + 4, 4) || !identity(old, now, at + 12, 4)) return false;
            return true;
        }
        if (kind == 1) return readonly_identity(old, now, 0x54) && readonly_identity(old, now, 0x6c);
        if (kind == 2) return stream_identity(old, now, 0x54) && readonly_identity(old, now, 0x60)
            && stream_identity(old, now, 0xcc) && readonly_identity(old, now, 0xd8)
            && readonly_identity(old, now, 0xf0);
        return identity(old, now, 0x70, 12); // Original chain topology indices.
    }
    static void restore_buffer(size_t kind, const Buffer& buffer) {
        if (!buffer.bytes) return;
        if (kind == 3) { ::memcpy(reinterpret_cast<void*>(buffer.data), buffer.saved, buffer.bytes); return; }
        const size_t starts[3][2] = {{0x100, 0x134}, {0x54, 0}, {0x54, 0xcc}};
        const size_t sizes[3][2] = {{0x24, 0x1d0}, {0x30, 0}, {0x24, 0x3c}};
        for (int32_t row = 0; row < buffer.length; ++row) {
            const auto* old = buffer.saved + static_cast<size_t>(row) * row_strides[kind];
            auto* now = reinterpret_cast<uint8_t*>(buffer.data) + static_cast<size_t>(row) * row_strides[kind];
            size_t copied = 0;
            for (size_t part = 0; part < 2; ++part) if (sizes[kind][part]) {
                const size_t start = starts[kind][part];
                if (start > copied) ::memcpy(now + copied, old + copied, start - copied);
                copied = start + sizes[kind][part];
            }
            if (copied < row_strides[kind]) ::memcpy(now + copied, old + copied, row_strides[kind] - copied);
        }
    }
    Result capture_pose(Actor& actor) {
        actor.root_transform = api_.root_transform(actor.source.actor, nullptr);
        void* array = api_.actor_transforms(actor.source.actor);
        if (!actor.root_transform || !api_.is_type(actor.root_transform, "UnityEngine.Transform")
            || !api_.alive(actor.root_transform) || !array || !api_.is_type(array, "UnityEngine.Transform[]"))
            return fail(Result::unsupported, "actor_state_pose_owner_unavailable");
        actor.transforms_root = api_.gc_new(array, false);
        if (!actor.transforms_root || api_.gc_target(actor.transforms_root) != array)
            return fail(Result::failed, "actor_state_pose_root_failed");
        actor.transforms_array = array;
        const size_t count = api_.array_length(array);
        void* data = api_.array_data(array);
        if (!count || count > max_transforms || !data
            || !api_.mapped(data, count * sizeof(void*), false))
            return fail(Result::unsupported, "actor_state_pose_array_invalid");
        if (count * sizeof(PoseEntry) > max_snapshot_bytes - bytes_)
            return fail(Result::unsupported, "actor_state_snapshot_too_large");
        actor.poses = static_cast<PoseEntry*>(::malloc(count * sizeof(PoseEntry)));
        if (!actor.poses) return fail(Result::failed, "actor_state_snapshot_allocation_failed");
        bytes_ += count * sizeof(PoseEntry); actor.pose_count = count;
        bool have_root = false;
        for (size_t i = 0; i < count; ++i) {
            PoseEntry entry{}; ::memcpy(&entry.transform, static_cast<uint8_t*>(data) + i * sizeof(void*), sizeof(void*));
            if (!entry.transform || !api_.is_type(entry.transform, "UnityEngine.Transform") || !api_.alive(entry.transform))
                return fail(Result::unsupported, "actor_state_pose_transform_invalid");
            for (size_t j = 0; j < i; ++j) if (actor.poses[j].transform == entry.transform)
                return fail(Result::unsupported, "actor_state_pose_transform_duplicate");
            entry.parent = api_.transform_parent(entry.transform, nullptr);
            if (entry.transform == actor.root_transform) have_root = true;
            else {
                void* parent = entry.parent; size_t depth = 0;
                while (parent && parent != actor.root_transform && depth++ < 128) {
                    if (!api_.is_type(parent, "UnityEngine.Transform") || !api_.alive(parent)) break;
                    parent = api_.transform_parent(parent, nullptr);
                }
                if (parent != actor.root_transform)
                    return fail(Result::unsupported, "actor_state_pose_outside_owner");
            }
            api_.local_position(entry.transform, &entry.pose.position, nullptr);
            api_.local_rotation(entry.transform, &entry.pose.rotation, nullptr);
            api_.local_scale(entry.transform, &entry.pose.scale, nullptr);
            if (!finite(entry.pose)) return fail(Result::unsupported, "actor_state_pose_nonfinite");
            actor.poses[i] = entry;
        }
        return have_root ? Result::ok : fail(Result::unsupported, "actor_state_pose_root_missing");
    }
    bool pose_current(const Actor& actor) const {
        if (!actor.transforms_root || api_.gc_target(actor.transforms_root) != actor.transforms_array
            || api_.array_length(actor.transforms_array) != actor.pose_count
            || api_.root_transform(actor.source.actor, nullptr) != actor.root_transform) return false;
        void* data = api_.array_data(actor.transforms_array);
        if (!data || !api_.mapped(data, actor.pose_count * sizeof(void*), false)) return false;
        for (size_t i = 0; i < actor.pose_count; ++i) {
            void* transform = nullptr; ::memcpy(&transform, static_cast<uint8_t*>(data) + i * sizeof(void*), sizeof(void*));
            if (transform != actor.poses[i].transform || !api_.alive(transform)
                || api_.transform_parent(transform, nullptr) != actor.poses[i].parent) return false;
        }
        return true;
    }
    Result add_time(Actor& actor, Handle playable) {
        if (!playable.handle || !api_.playable_valid(&playable, nullptr))
            return fail(Result::unsupported, "actor_state_playable_invalid");
        for (size_t i = 0; i < actor.time_count; ++i)
            if (same(actor.times[i].playable, playable)) return Result::ok;
        if (actor.time_count == max_playables) return fail(Result::unsupported, "actor_state_playable_limit");
        if(presentation_&&(!api_.node_supported||!api_.node_supported(context_,actor.source,playable)))
            return fail(Result::unsupported,"actor_state_graph_job_unsupported");
        const double time = api_.playable_time(&playable, nullptr);
        if (!__builtin_isfinite(time) || __builtin_fabs(time) > 36000)
            return fail(Result::unsupported, "actor_state_playable_time_invalid");
        actor.times[actor.time_count++] = {playable, time}; return Result::ok;
    }
    Result capture_times(Actor& actor) {
        if (!actor.times) {
            if (max_playables * sizeof(TimeEntry) > max_snapshot_bytes - bytes_)
                return fail(Result::unsupported, "actor_state_snapshot_too_large");
            actor.times = static_cast<TimeEntry*>(::malloc(max_playables * sizeof(TimeEntry)));
            if (!actor.times) return fail(Result::failed, "actor_state_snapshot_allocation_failed");
            bytes_ += max_playables * sizeof(TimeEntry);
        }
        actor.time_count = 0;
        const int32_t roots = api_.graph_root_count(&actor.source.graph, nullptr);
        if (roots < 1 || roots > 128) return fail(Result::unsupported, "actor_state_graph_roots_invalid");
        for (int32_t i = 0; i < roots; ++i) {
            Handle playable{}; api_.graph_root(&actor.source.graph, i, &playable, nullptr);
            const Result result = add_time(actor, playable); if (result != Result::ok) return result;
        }
        for (size_t i = 0; i < actor.time_count; ++i) {
            const int32_t inputs = api_.playable_input_count(&actor.times[i].playable, nullptr);
            if (inputs < 0 || inputs > 128) return fail(Result::unsupported, "actor_state_playable_inputs_invalid");
            for (int32_t j = 0; j < inputs; ++j) {
                Handle playable{}; api_.playable_input(&actor.times[i].playable, j, &playable, nullptr);
                // Original mixers can reserve disconnected input slots.
                if (!playable.handle) continue;
                const Result result = add_time(actor, playable); if (result != Result::ok) return result;
            }
        }
        return Result::ok;
    }
    Result times_unchanged(Actor& actor) {
        for (size_t i = 0; i < actor.time_count; ++i) {
            if (!api_.playable_valid(&actor.times[i].playable, nullptr))
                return fail(Result::stale, "actor_state_playable_generation_changed");
            const double now = api_.playable_time(&actor.times[i].playable, nullptr);
            if (!__builtin_isfinite(now) || __builtin_fabs(now - actor.times[i].time) > 0.000001)
                return fail(Result::unsupported, "actor_state_warmup_advanced_clip");
        }
        return Result::ok;
    }
    Result fence_all() {
        for (size_t i = 0; i < count_; ++i) {
            if (!actors_[i].native_animator) continue;
            const Result result = fence(actors_[i]); if (result != Result::ok) return result;
        }
        return Result::ok;
    }
    Result ensure_held() {
        if (!configured_) return fail(Result::invalid, "actor_state_not_configured");
        if (!api_.clock_held(context_)) return fail(Result::waiting, "actor_state_clock_not_held");
        if (!owner_current()) return fail(Result::stale, "actor_state_owner_changed");
        return Result::ok;
    }
    Result mode_current() {
        if (!reset_done_ || restored_) return Result::ok;
        for (size_t i = 0; i < count_; ++i) {
            int32_t mode = -1;
            if (!api_.graph_mode(&actors_[i].source.graph, &mode) || mode != 1)
                return fail(Result::stale, "actor_state_graph_mode_changed");
        }
        return Result::ok;
    }
    Result hold_gate() {
        if (presentation_) {const Result p=presentation_->hold();if(p!=Result::ok)return fail(p,presentation_->error());}
        const Result result = fence_all(); if (result != Result::ok) return result;
        if (gate_->stats().readers)
            return fail(Result::waiting, "actor_state_gate_readers_pending");
        if (published_ && gate_->hold(epoch_, true) != GateResult::ok)
            return fail(Result::stale, "actor_state_gate_changed");
        prepared_serial_ = 0;
        if(reset_done_&&simulation_serial_>checked_simulation_serial_&&!step_failed_&&api_.job_expected){
            uint32_t expected=0,completed=0;
            for(size_t i=0;i<count_;++i){const auto& actor=actors_[i];
                const int32_t active=api_.job_expected(context_,actor.source);
                if(active<0||active>1){step_failed_=true;return fail(Result::unsupported,"actor_state_job_expectation_unverified");}
                if(active){++expected;if(gate_->consumed(actor.key,epoch_,serial_))++completed;}
            }
            expected_jobs_=expected;completed_jobs_=completed;
            if(completed!=expected){step_failed_=true;return fail(Result::failed,"actor_state_job_step_missing");}
            checked_simulation_serial_=simulation_serial_;
        }
        return Result::ok;
    }
    void free_storage() {
        for (size_t i = 0; i < count_; ++i) {
            auto& actor = actors_[i];
            for (auto& buffer : actor.buffers) { ::free(buffer.saved); buffer.saved = nullptr; }
            ::free(actor.poses); actor.poses = nullptr;
            ::free(actor.times); actor.times = nullptr;
            if (actor.transforms_root) api_.gc_free(actor.transforms_root);
            for (auto root : actor.roots) if (root) api_.gc_free(root);
            actor.~Actor();
            new(idoly_mp4_actor_placement::Address{&actor})Actor{};
        }
        count_ = bytes_ = warmed_ = 0; context_ = nullptr; presentation_ = nullptr;
        epoch_ = serial_ = simulation_serial_ = prepared_serial_ = checked_simulation_serial_ = 0;
        expected_jobs_=completed_jobs_=0;step_failed_=false;
        simulation_hz_=60;
        configured_ = published_ = reset_started_ = reset_done_ = changed_native_ = restored_
            = zero_pose_prepared_ = witness_captured_ = false;
    }
public:
    Scope() = default;
    Scope(const Scope&) = delete;
    Scope& operator=(const Scope&) = delete;
    const char* error() const { return error_; }
    size_t warmed_steps() const { return warmed_; }
    bool active() const { return configured_; }
    bool bind_presentation(PresentationScope* presentation) {
        if (!configured_ || published_ || !presentation || !presentation->active() || presentation_ || !api_.node_supported || !api_.graph_playing || !api_.graph_play || !api_.graph_stop || !api_.job_expected || !api_.temporal_binding) return false;
        presentation_ = presentation;return true;
    }
    bool presentation_bound() const { return presentation_ && presentation_->active(); }
    uint64_t completed_simulation_serial()const{return checked_simulation_serial_;}
    uint32_t expected_actor_jobs()const{return expected_jobs_;}
    uint32_t completed_actor_jobs()const{return completed_jobs_;}
    bool actor_step_failed()const{return step_failed_;}
    Result verify_completed_step(){return hold_frame();}
    // Aborting a partial multi-owner grant must close future entrants even
    // after the selected scene witness is stale. This touches our storage only.
    void revoke_grants() {
        prepared_serial_=0;
        if(gate_&&epoch_)gate_->revoke(epoch_);
        if(presentation_)presentation_->revoke_grants();
    }
    bool configure(StateApi api, WorkerGate* gate, const Owner* owners, size_t count,
            void* context, uint64_t epoch, StateLayout layout = {}, uint32_t simulation_hz=60) {
        if (configured_ || !gate || !owners || !count || count > max_owned_jobs || !context || !epoch) return false;
        if (simulation_hz!=60 && simulation_hz!=120) { error_="actor_state_simulation_hz_unsupported";return false; }
        api_ = api; layout_ = layout;
        if (!complete_api()) { error_ = "actor_state_api_unavailable"; return false; }
        gate_ = gate; context_ = context; epoch_ = epoch; count_ = count;simulation_hz_=simulation_hz;
        for (size_t i = 0; i < count; ++i) actors_[i].source = owners[i];
        configured_ = true; error_ = "none"; return true;
    }
    bool owner_current() {
        if (!configured_ || !complete_api()) return false;
        for (size_t i = 0; i < count_; ++i) if (!owner_current(actors_[i])) return false;
        return true;
    }
    Result quiesce() {
        if (!configured_) return fail(Result::invalid, "actor_state_not_configured");
        if (!api_.clock_held(context_)) return fail(Result::waiting, "actor_state_clock_not_held");
        if (!api_.routes_ready(context_)) return fail(Result::waiting, "actor_state_worker_routes_not_ready");
        for (size_t i = 0; i < count_; ++i) {
            auto& actor = actors_[i];
            const Result held = retain(actor); if (held != Result::ok) return held;
            int32_t mode = -1;
            if (!api_.graph_mode(&actor.source.graph, &mode) || mode < 0 || mode > 3)
                return fail(Result::unsupported, "actor_state_graph_mode_unavailable");
            if (actor.previous_mode == -1) actor.previous_mode = mode;
            if(api_.graph_playing&&!actor.playing_captured){actor.previous_playing=api_.graph_playing(&actor.source.graph,nullptr);actor.playing_captured=true;}
            if(presentation_){const Result graph=capture_times(actor);if(graph!=Result::ok)return graph;}
        }
        const Result mode = mode_current(); if (mode != Result::ok) return mode;
        const Result held = hold_gate(); if (held != Result::ok) return held;
        if (!published_) {
            OwnershipKey keys[max_owned_jobs]{};
            for (size_t i = 0; i < count_; ++i) {
                const Result inspected = inspect_job(actors_[i], true); if (inspected != Result::ok) return inspected;
                keys[i] = actors_[i].key;
            }
            const auto status = gate_->publish(keys, count_, epoch_, true);
            if (status == GateResult::waiting) return fail(Result::waiting, "actor_state_gate_readers_pending");
            if (status != GateResult::ok) return fail(Result::unsupported, "actor_state_gate_ownership_invalid");
            published_ = true;
        }
        error_ = "none"; return Result::ok;
    }
    Result capture() {
        Result status = ensure_held(); if (status != Result::ok) return status;
        if (!published_) return fail(Result::invalid, "actor_state_not_quiesced");
        status = hold_gate(); if (status != Result::ok) return status;
        if (presentation_) {
            Owner owners[max_owned_jobs]{};for(size_t i=0;i<count_;++i)owners[i]=actors_[i].source;
            status=presentation_->flush_source(owners,count_);if(status!=Result::ok)return fail(status,presentation_->error());
            status=presentation_->capture();if(status!=Result::ok)return fail(status,presentation_->error());
        }
        for (size_t i = 0; i < count_; ++i) {
            auto& actor = actors_[i]; if (actor.captured) continue;
            status = inspect_job(actor, false); if (status != Result::ok) return status;
            ::memcpy(actor.saved_job, actor.live_job, actor_job_bytes);
            for (auto& buffer : actor.buffers) {
                if (!buffer.bytes || buffer.saved) continue;
                if (buffer.bytes > max_snapshot_bytes - bytes_)
                    return fail(Result::unsupported, "actor_state_snapshot_too_large");
                buffer.saved = static_cast<uint8_t*>(::malloc(buffer.bytes));
                if (!buffer.saved) return fail(Result::failed, "actor_state_snapshot_allocation_failed");
                bytes_ += buffer.bytes;
                ::memcpy(buffer.saved, reinterpret_cast<void*>(buffer.data), buffer.bytes);
            }
            if(presentation_&&!actor.temporal.captured()){
                TemporalBinding binding{};
                if(!api_.temporal_binding(context_,actor.source,binding))return fail(Result::unsupported,"actor_temporal_binding_unavailable");
                status=actor.temporal.capture(binding,epoch_,actor.source.graph,max_snapshot_bytes-bytes_);
                if(status!=Result::ok)return fail(status,actor.temporal.error());
                bytes_+=actor.temporal.bytes();
            }
            status = capture_pose(actor); if (status != Result::ok) return status;
            actor.captured = true;
        }
        error_ = "none"; return Result::ok;
    }
    Result prepare() {
        Result held = ensure_held(); if (held != Result::ok) return held;
        for (size_t i = 0; i < count_; ++i) if (!actors_[i].captured)
            return fail(Result::invalid, "actor_state_snapshot_missing");
        if (!reset_done_) {
            held = hold_gate(); if (held != Result::ok) return held;
            for (size_t i = 0; i < count_; ++i) {
                auto& actor = actors_[i]; actor.mode_changed = true;
                api_.graph_set_mode(&actor.source.graph, 3, nullptr);
                int32_t mode = -1;
                if (!api_.graph_mode(&actor.source.graph, &mode) || mode != 3)
                    return fail(Result::failed, "actor_state_graph_hold_failed");
            }
        }
        error_ = "none"; return Result::ok;
    }
    Result hold_frame() {
        const Result held = ensure_held(); if (held != Result::ok) return held;
        const Result mode = mode_current(); if (mode != Result::ok) return mode;
        return hold_gate();
    }
    Result reset() {
        Result status = prepare(); if (status != Result::ok) return status;
        if (reset_done_) return Result::ok;
        status = hold_gate(); if (status != Result::ok) return status;
        if (!zero_pose_prepared_) {
            // Root preparation can change visible transforms even while the
            // selected spring solver is gated. Keep pose restoration duty
            // before entering that original callback.
            changed_native_ = true;
            if(presentation_){status=presentation_->reset_runtime_history();if(status!=Result::ok)return fail(status,presentation_->error());}
            if(presentation_)for(size_t i=0;i<count_;++i){status=actors_[i].temporal.reset_runtime_history();if(status!=Result::ok)return fail(status,actors_[i].temporal.error());}
            status = api_.prepare_zero_pose(context_); if (status != Result::ok) return status;
            if (!owner_current()) return fail(Result::stale, "actor_state_owner_changed");
            zero_pose_prepared_ = true;
        }
        if (!__builtin_isfinite(api_.root_time(context_)) || __builtin_fabs(api_.root_time(context_)) > 0.000001)
            return fail(Result::unsupported, "actor_state_warmup_root_not_zero");
        if (!reset_started_) {
            status=hold_gate();if(status!=Result::ok)return status;
            if (presentation_) {
                Owner owners[max_owned_jobs]{};for(size_t i=0;i<count_;++i)owners[i]=actors_[i].source;
                status=presentation_->initialize(owners,count_);if(status!=Result::ok)return fail(status,presentation_->error());
            }
            for (size_t i = 0; i < count_; ++i) {
                auto& actor = actors_[i];
                status = inspect_job(actor, false); if (status != Result::ok) return status;
                changed_native_ = true;
                api_.rig_reset_dynamic(actor.source.rig, nullptr);
                if (!owner_current()) return fail(Result::stale, "actor_state_owner_changed");
                api_.rig_reset_breast(actor.source.rig, nullptr);
                status = inspect_job(actor, false); if (status != Result::ok) return status;
                const float zero = 0;
                ::memcpy(static_cast<uint8_t*>(actor.live_job) + actor_job_time, &zero, sizeof zero);
                for (int32_t row = 0; row < actor.buffers[0].length; ++row)
                    ::memset(reinterpret_cast<uint8_t*>(actor.buffers[0].data) + static_cast<size_t>(row) * row_strides[0] + 0xf4, 0, 12);
                for (int32_t row = 0; row < actor.buffers[2].length; ++row) {
                    auto* bone = reinterpret_cast<uint8_t*>(actor.buffers[2].data) + static_cast<size_t>(row) * row_strides[2];
                    ::memset(bone + 0x48, 0, 12); ::memset(bone + 0xc0, 0, 12);
                }
            }
            reset_started_ = true;
        }
        if (!witness_captured_) {
            for (size_t i = 0; i < count_; ++i) {
                status = capture_times(actors_[i]); if (status != Result::ok) return status;
            }
            witness_captured_ = true;
        }
        for (size_t step = 0; step < warmup_steps_per_call && warmed_ < warmup_steps; ++step) {
            status = hold_gate(); if (status != Result::ok) return status;
            if (gate_->grant(++serial_, epoch_, true) != GateResult::ok)
                return fail(Result::stale, "actor_state_gate_changed");
            for (size_t i = 0; i < count_; ++i) {
                if (!owner_current()) return fail(Result::stale, "actor_state_owner_changed");
                api_.graph_evaluate(&actors_[i].source.graph, 0, nullptr);
            }
            status = hold_gate(); if (status != Result::ok) return status;
            for (size_t i = 0; i < count_; ++i) {
                status = inspect_job(actors_[i], false); if (status != Result::ok) return status;
                status = times_unchanged(actors_[i]); if (status != Result::ok) return status;
                float time = 0;
                if (!read(actors_[i].live_job, actor_job_time, time) || !finite(time) || __builtin_fabsf(time) > 0.000001f)
                    return fail(Result::unsupported, "actor_state_warmup_advanced_job_clock");
            }
            if (!__builtin_isfinite(api_.root_time(context_)) || __builtin_fabs(api_.root_time(context_)) > 0.000001)
                return fail(Result::unsupported, "actor_state_warmup_advanced_root");
            ++warmed_;
        }
        if (warmed_ != warmup_steps) return fail(Result::waiting, "actor_state_warmup_pending");
        for (size_t i = 0; i < count_; ++i) {
            if(api_.graph_playing&&!api_.graph_playing(&actors_[i].source.graph,nullptr)){
                api_.graph_play(&actors_[i].source.graph,nullptr);
                if(!owner_current()||!api_.graph_playing(&actors_[i].source.graph,nullptr))return fail(Result::failed,"actor_state_private_graph_start_failed");
            }
            api_.graph_set_mode(&actors_[i].source.graph, 1, nullptr);
            int32_t mode = -1;
            if (!api_.graph_mode(&actors_[i].source.graph, &mode) || mode != 1)
                return fail(Result::failed, "actor_state_graph_game_time_failed");
        }
        reset_done_ = true; error_ = "none"; return Result::ok;
    }
    Result grant(uint64_t simulation_serial) {
        Result status = ensure_held(); if (status != Result::ok) return status;
        if (!reset_done_ || !simulation_serial || simulation_serial <= simulation_serial_)
            return fail(Result::invalid, "actor_state_simulation_grant_invalid");
        status = hold_gate(); if (status != Result::ok) return status;
        for (size_t i = 0; i < count_; ++i) {
            status = inspect_job(actors_[i], false); if (status != Result::ok) return status;
            int32_t mode = -1;
            if (!api_.graph_mode(&actors_[i].source.graph, &mode) || mode != 1)
                return fail(Result::stale, "actor_state_graph_mode_changed");
        }
        if (gate_->grant(++serial_, epoch_, true) != GateResult::ok)
            return fail(Result::stale, "actor_state_gate_changed");
        if(presentation_){status=presentation_->grant(simulation_serial);if(status!=Result::ok){gate_->revoke(epoch_);return fail(status,presentation_->error());}}
        simulation_serial_ = simulation_serial; error_ = "none"; return Result::ok;
    }
    Result prepare_grant(uint64_t simulation_serial) {
        if(step_failed_)return fail(Result::failed,"actor_state_prior_job_step_missing");
        Result status = ensure_held(); if (status != Result::ok) return status;
        if (!reset_done_ || !published_ || !simulation_serial
            || simulation_serial_ == ~uint64_t(0) || simulation_serial != simulation_serial_ + 1
            || serial_ == ~uint64_t(0))
            return fail(Result::invalid, "actor_state_simulation_grant_invalid");
        status = hold_gate(); if (status != Result::ok) return status;
        for (size_t i = 0; i < count_; ++i) {
            status = inspect_job(actors_[i], false); if (status != Result::ok) return status;
            int32_t mode = -1;
            if (!api_.graph_mode(&actors_[i].source.graph, &mode) || mode != 1)
                return fail(Result::stale, "actor_state_graph_mode_changed");
        }
        // Nothing is published and neither logical nor worker serial is
        // consumed. A native F8 rejection can safely prepare this same step.
        prepared_serial_ = simulation_serial; error_ = "none"; return Result::ok;
    }
    Result commit_grant(uint64_t simulation_serial) {
        if(step_failed_)return fail(Result::failed,"actor_state_prior_job_step_missing");
        if (!configured_ || !reset_done_ || !published_ || !simulation_serial
            || prepared_serial_ != simulation_serial || simulation_serial_ == ~uint64_t(0)
            || simulation_serial != simulation_serial_ + 1 || serial_ == ~uint64_t(0))
            return fail(Result::invalid, "actor_state_simulation_grant_not_prepared");
        if (!owner_current() || !api_.routes_ready(context_))
            return fail(Result::stale, "actor_state_owner_changed");
        if (!api_.clock_granted(context_, simulation_serial))
            return fail(Result::waiting, "actor_state_clock_grant_not_consumed");
        if (gate_->stats().readers)
            return fail(Result::stale, "actor_state_readers_changed_after_prepare");
        for (size_t i = 0; i < count_; ++i) {
            Result status = prepared_fence_current(actors_[i]); if (status != Result::ok) return status;
            status = inspect_job(actors_[i], false); if (status != Result::ok) return status;
            int32_t mode = -1;
            if (!api_.graph_mode(&actors_[i].source.graph, &mode) || mode != 1)
                return fail(Result::stale, "actor_state_graph_mode_changed");
        }
        if (!owner_current() || !api_.clock_granted(context_, simulation_serial))
            return fail(Result::stale, "actor_state_clock_grant_changed");
        const uint64_t worker_serial = serial_ + 1;
        if (gate_->grant(worker_serial, epoch_, true) != GateResult::ok)
            return fail(Result::stale, "actor_state_gate_changed");
        if(presentation_){const Result p=presentation_->grant(simulation_serial);if(p!=Result::ok){gate_->revoke(epoch_);return fail(p,presentation_->error());}}
        serial_ = worker_serial; simulation_serial_ = simulation_serial; prepared_serial_ = 0;
        error_ = "none"; return Result::ok;
    }
    Result restore() {
        Result status = ensure_held(); if (status != Result::ok) return status;
        if (restored_) return Result::ok;
        status = hold_gate(); if (status != Result::ok) return status;
        if(presentation_&&presentation_->captured()){status=presentation_->validate();if(status!=Result::ok)return fail(status,presentation_->error());}
        // Restore stopped/playing ownership before temporal/managed/physical
        // history. Stop is a source lifecycle mutation here, never a fence.
        for(size_t i=0;i<count_;++i){auto& actor=actors_[i];
            if(actor.playing_captured&&api_.graph_playing(&actor.source.graph,nullptr)!=actor.previous_playing){
                if(actor.previous_playing)api_.graph_play(&actor.source.graph,nullptr);else api_.graph_stop(&actor.source.graph,nullptr);
                if(!owner_current()||api_.graph_playing(&actor.source.graph,nullptr)!=actor.previous_playing)return fail(Result::failed,"actor_state_source_graph_playstate_restore_failed");
            }
        }
        if(presentation_)for(size_t i=0;i<count_;++i){auto& actor=actors_[i];
            if(actor.mode_changed){api_.graph_set_mode(&actor.source.graph,3,nullptr);int32_t mode=-1;
                if(!api_.graph_mode(&actor.source.graph,&mode)||mode!=3)return fail(Result::failed,"actor_state_graph_hold_failed");}
        }
        // Validate the entire selected set before any raw history/pose write.
        for (size_t i = 0; i < count_; ++i) if (changed_native_ && actors_[i].captured) {
            status = inspect_job(actors_[i], false); if (status != Result::ok) return status;
            if (!pose_current(actors_[i])) return fail(Result::stale, "actor_state_pose_owner_changed");
        }
        if(presentation_)for(size_t i=0;i<count_;++i)if(actors_[i].temporal.captured()){
            status=actors_[i].temporal.preflight_restore();if(status!=Result::ok)return fail(status,actors_[i].temporal.error());}
        if(presentation_)for(size_t i=0;i<count_;++i)if(actors_[i].temporal.captured()){
            status=actors_[i].temporal.restore();if(status!=Result::ok)return fail(status,actors_[i].temporal.error());}
        for (size_t i = 0; i < count_; ++i) {
            auto& actor = actors_[i];
            if (actor.mode_changed) {
                // Restoration is a separate fenced mutation. Ordinary
                // quiesce()/backpressure holds never change graph modes.
                api_.graph_set_mode(&actor.source.graph, 3, nullptr);
                int32_t mode = -1;
                if (!api_.graph_mode(&actor.source.graph, &mode) || mode != 3)
                    return fail(Result::failed, "actor_state_graph_hold_failed");
            }
            if (changed_native_ && actor.captured) {
                status = inspect_job(actor, false); if (status != Result::ok) return status;
                if (!pose_current(actor)) return fail(Result::stale, "actor_state_pose_owner_changed");
                // The job prefix has immutable identity. Row stream/property
                // handles can legitimately resolve in-place; preserve their
                // current caches while restoring all captured history bytes.
                ::memcpy(actor.live_job, actor.saved_job, actor_job_bytes);
                for (size_t kind = 0; kind < 4; ++kind) restore_buffer(kind, actor.buffers[kind]);
                for (size_t j = 0; j < actor.pose_count; ++j) {
                    const auto& pose = actor.poses[j];
                    api_.set_local_position_rotation(pose.transform, &pose.pose.position, &pose.pose.rotation, nullptr);
                    api_.set_local_scale(pose.transform, &pose.pose.scale, nullptr);
                }
            }
            if (actor.mode_changed) {
                api_.graph_set_mode(&actor.source.graph, actor.previous_mode, nullptr);
                int32_t mode = -1;
                if (!api_.graph_mode(&actor.source.graph, &mode) || mode != actor.previous_mode)
                    return fail(Result::failed, "actor_state_graph_restore_failed");
            }
        }
        if(presentation_&&presentation_->captured()){status=presentation_->restore();if(status!=Result::ok)return fail(status,presentation_->error());}
        restored_ = true; error_ = "none"; return Result::ok;
    }
    Result release(bool scene_owned) {
        if (!configured_) return Result::ok;
        if (scene_owned) {
            const Result restored = restore(); if (restored != Result::ok) return restored;
            if (published_) {
                const auto result = gate_->retire(epoch_, true);
                if (result == GateResult::waiting) return fail(Result::waiting, "actor_state_gate_readers_pending");
                if (result != GateResult::ok) return fail(Result::stale, "actor_state_gate_changed");
            }
        } else if (published_) {
            // No dereference of a stale scene, native job, or former Animator.
            gate_->detach_stale(epoch_);
            if (gate_->stats().readers) return fail(Result::waiting, "actor_state_gate_readers_pending");
        }
        if(presentation_){const Result p=presentation_->release(scene_owned);if(p!=Result::ok)return fail(p,presentation_->error());}
        free_storage(); error_ = "none"; return Result::ok;
    }
};
} // namespace idoly_mp4_actor

// BEGIN_MP4_SRP_CONTROLLER_STATE

// VLSRPCameraController's original common SRP subscriber owns a lazy List of
// pre-cull actions and a first-camera flag. These are source state, even though
// the delegate list is empty after most ordinary frames. This finite lease is
// separate from renderer capability and from an owned GPU draw receipt.
namespace idoly_mp4_srp {
constexpr size_t max_actions=128,max_capacity=256,max_roots=512;
struct Image {
    void* controller=nullptr;void* camera=nullptr;void* queue=nullptr;void* array=nullptr;
    uint32_t version=0;size_t count=0,capacity=0;bool first=false;
    void* items[max_capacity]{};
    // Two pipeline anchors followed by the six actual SRP delegate roots.
    void* subscribers[8]{};
};
struct FramePlan {bool clears_first=false;size_t selected_invocations=0;};
enum class Operation : uint8_t {add,invoke,frame};
struct Token {uint64_t id=0;Operation operation=Operation::add;};
struct Api {
    bool (*current)(void*,void*,void*)=nullptr;
    bool (*held_fenced)(void*)=nullptr;
    bool (*read)(void*,Image&)=nullptr;
    uint32_t (*retain)(void*)=nullptr;
    void* (*target)(uint32_t)=nullptr;
    void (*release)(uint32_t)=nullptr;
    // This callback observes actual typed hook entry, not an ambient owner bit.
    // Add requires the entered Actor original/Root operation; Invoke requires
    // the entered selected Frame original. Frame additionally joins the actual
    // SRP callback and pure current render intent before a draw ticket exists.
    bool (*entered)(void*,Operation,void*,void*)=nullptr;
    bool (*frame_plan)(void*,void*,FramePlan&)=nullptr;
    bool (*action_owned)(void*,void*)=nullptr;
    // Host uses verified original IL2CPP reference barriers plus exact scalar
    // slots, after all current managed ranges/roots have been prevalidated.
    bool (*restore_image)(void*,const Image&)=nullptr;
};
class ControllerLease {
    Api api_{};void* context_=nullptr;Image saved_{},latest_{};
    struct Root {void* object=nullptr;uint32_t handle=0;};Root roots_[max_roots]{};size_t root_count_=0;
    uint64_t sequence_=0;Token frame_{},mutation_{};Image before_{};
    FramePlan plan_{};size_t invoked_=0;void* addition_=nullptr;
    bool captured_=false,poisoned_=false,restored_=false;const char* error_="none";
    bool fail(const char* error){error_=error;poisoned_=true;return false;}
    bool root(void* object){
        if(!object)return true;
        for(size_t i=0;i<root_count_;++i)if(roots_[i].object==object)return api_.target(roots_[i].handle)==object;
        if(root_count_==max_roots)return false;
        const uint32_t handle=api_.retain(object);if(!handle)return false;
        if(api_.target(handle)!=object){api_.release(handle);return false;}
        roots_[root_count_++]={object,handle};return true;
    }
    bool keep(const Image& value){
        if(!root(value.controller)||!root(value.camera)||!root(value.queue)||!root(value.array))return false;
        for(size_t i=0;i<value.count;++i)if(!root(value.items[i]))return false;
        for(void* value_root:value.subscribers)if(!root(value_root))return false;
        return true;
    }
    bool roots_current()const{for(size_t i=0;i<root_count_;++i)if(api_.target(roots_[i].handle)!=roots_[i].object)return false;return true;}
    bool owner()const{return captured_&&!poisoned_&&api_.current(context_,saved_.controller,saved_.camera)&&roots_current();}
    static bool valid(const Image& value){
        if(!value.controller||!value.camera||value.count>max_actions||value.capacity>max_capacity||value.count>value.capacity)return false;
        if(!value.queue)return !value.array&&!value.count&&!value.capacity&&!value.version;
        if(!value.array)return false;
        for(size_t i=0;i<value.capacity;++i)if((i<value.count)!=(value.items[i]!=nullptr))return false;
        return true;
    }
    static bool same(const Image& a,const Image& b,bool first=true){
        if(a.controller!=b.controller||a.camera!=b.camera||a.queue!=b.queue||a.array!=b.array
            ||a.version!=b.version||a.count!=b.count||a.capacity!=b.capacity||(first&&a.first!=b.first))return false;
        for(size_t i=0;i<a.capacity;++i)if(a.items[i]!=b.items[i])return false;
        for(size_t i=0;i<8;++i)if(a.subscribers[i]!=b.subscribers[i])return false;
        return true;
    }
    static bool same_subscribers(const Image& a,const Image& b){
        for(size_t i=0;i<8;++i)if(a.subscribers[i]!=b.subscribers[i])return false;
        return true;
    }
    bool read(Image& value){
        value={};if(!owner()||!api_.read(context_,value)||!valid(value)
            ||value.controller!=saved_.controller||value.camera!=saved_.camera||!owner())return false;
        return true;
    }
    bool observe(Image& value,bool in_frame=false){
        if(!read(value)||!same(value,latest_,!in_frame))return false;
        // The original flag can only transition true -> false. While inside a
        // typed Frame callback that transition may precede its nested Invoke.
        if(in_frame&&value.first!=latest_.first&&(!latest_.first||value.first||!plan_.clears_first))return false;
        latest_.first=value.first;return true;
    }
    bool next(Token& token,Operation operation){
        if(sequence_==~uint64_t(0))return fail("srp_invocation_limit");
        token={++sequence_,operation};return true;
    }
    bool finish_image(const Image& value){
        if(!keep(value))return fail("srp_root_failed");
        Image after{};if(!read(after)||!same(value,after))return fail("srp_mutation_changed");
        latest_=value;return true;
    }
public:
    ControllerLease()=default;ControllerLease(const ControllerLease&)=delete;ControllerLease&operator=(const ControllerLease&)=delete;
    ~ControllerLease(){clear();}
    bool captured()const{return captured_;}
    bool poisoned()const{return poisoned_;}
    bool open()const{return frame_.id||mutation_.id;}
    const char* error()const{return error_;}
    bool capture(Api api,void* context){
        if(captured_||!context||!api.current||!api.held_fenced||!api.read||!api.retain||!api.target||!api.release
            ||!api.entered||!api.frame_plan||!api.action_owned||!api.restore_image)return false;
        clear();api_=api;context_=context;
        if(!api_.held_fenced(context_)||!api_.read(context_,saved_)||!valid(saved_)
            ||!api_.current(context_,saved_.controller,saved_.camera)||!keep(saved_)){clear();return false;}
        captured_=true;Image after{};
        if(!read(after)||!same(saved_,after)){clear();return false;}
        latest_=saved_;return true;
    }
    bool begin_add(void* controller,void* action,Token& token){
        token={};Image value{};
        if(!captured_)return false;
        if(open()||restored_||controller!=saved_.controller||!action||!observe(value)||value.count==max_actions
            ||!api_.entered(context_,Operation::add,controller,action)||!api_.action_owned(context_,action)||!root(action))
            return fail("srp_add_entry_unclosed");
        before_=value;addition_=action;
        if(!next(mutation_,Operation::add))return false;
        token=mutation_;return true;
    }
    bool end_add(Token token){
        if(!captured_||token.id!=mutation_.id||!token.id||token.operation!=Operation::add||mutation_.operation!=Operation::add)
            return fail("srp_add_token_stale");
        Image value{};if(!read(value))return fail("srp_add_result_unreadable");
        const size_t expected_capacity=before_.count<before_.capacity?before_.capacity:(before_.capacity?before_.capacity*2:4);
        if(!same_subscribers(value,before_)||value.first!=before_.first||!value.queue||(before_.queue&&value.queue!=before_.queue)
            ||value.count!=before_.count+1||value.version!=before_.version+1u||value.capacity!=expected_capacity
            ||(before_.count<before_.capacity?value.array!=before_.array:value.array==before_.array)
            ||value.items[before_.count]!=addition_)return fail("srp_add_result_unclosed");
        for(size_t i=0;i<before_.count;++i)if(value.items[i]!=before_.items[i])return fail("srp_add_prefix_changed");
        if(!finish_image(value))return false;
        mutation_={};addition_=nullptr;return true;
    }
    bool begin_frame(void* controller,void* cameras,Token& token){
        token={};Image value{};
        if(!captured_)return false;
        if(open()||restored_||controller!=saved_.controller||!cameras||!observe(value)
            ||!api_.entered(context_,Operation::frame,controller,cameras)||!api_.frame_plan(context_,cameras,plan_)
            ||plan_.selected_invocations>1024)return fail("srp_frame_entry_unclosed");
        before_=value;saved_frame_first_=value.first;invoked_=0;
        if(!next(frame_,Operation::frame))return false;
        token=frame_;return true;
    }
    bool begin_invoke(void* controller,Token& token){
        token={};Image value{};
        if(!captured_)return false;
        if(!frame_.id||mutation_.id||controller!=saved_.controller||invoked_>=plan_.selected_invocations
            ||!observe(value,true)||!api_.entered(context_,Operation::invoke,controller,nullptr))return fail("srp_invoke_entry_unclosed");
        // Keep the frame's original first flag separately; this mutation owns
        // only queue clear/version, never the enclosing first-camera change.
        before_=value;
        if(!next(mutation_,Operation::invoke))return false;
        token=mutation_;return true;
    }
    bool end_invoke(Token token){
        if(!captured_||token.id!=mutation_.id||!token.id||token.operation!=Operation::invoke||mutation_.operation!=Operation::invoke)
            return fail("srp_invoke_token_stale");
        Image value{};if(!read(value))return fail("srp_invoke_result_unreadable");
        if(!same_subscribers(value,before_)||value.first!=before_.first||value.queue!=before_.queue||value.array!=before_.array||value.capacity!=before_.capacity
            ||value.count||(before_.queue?value.version!=before_.version+1u:value.version!=before_.version))
            return fail("srp_invoke_result_unclosed");
        if(!finish_image(value))return false;
        mutation_={};++invoked_;return true;
    }
    bool end_frame(Token token){
        if(!captured_||token.id!=frame_.id||!token.id||token.operation!=Operation::frame||mutation_.id)
            return fail("srp_frame_token_stale");
        Image value{};
        if(!observe(value,true)||invoked_!=plan_.selected_invocations||value.first!=(saved_frame_first_&&!plan_.clears_first))
            return fail("srp_frame_result_unclosed");
        latest_=value;frame_={};return true;
    }
    // Call on every exception or unknown mutation of the selected controller.
    // Original ordinary playback is still forwarded by the host exactly once.
    void reject(){if(captured_)fail("srp_original_callback_unclosed");}
    bool restore(){
        Image value{};
        if(!captured_||open()||!api_.held_fenced(context_)||!observe(value)||!owner())return fail("srp_restore_unclosed");
        if(restored_)return true;
        if(!api_.restore_image(context_,saved_))return fail("srp_restore_write_failed");
        Image restored{};
        if(!read(restored)||!same(restored,saved_))return fail("srp_restore_verify_failed");
        latest_=saved_;restored_=true;return true;
    }
    // Source replacement withdraws the lease; it never writes the old scene.
    void clear(){
        for(size_t i=0;i<root_count_;++i)if(roots_[i].handle&&api_.release)api_.release(roots_[i].handle);
        root_count_=0;api_={};context_=nullptr;saved_={};latest_={};before_={};frame_={};mutation_={};
        plan_={};invoked_=0;addition_=nullptr;captured_=poisoned_=restored_=false;saved_frame_first_=false;error_="none";
    }
private:
    bool saved_frame_first_=false;
};
} // namespace idoly_mp4_srp

// END_MP4_SRP_CONTROLLER_STATE

// BEGIN_MP4_SHADER_LINEAGE_STATE
namespace idoly_mp4_shader_lineage {
struct Digest {uint8_t bytes[32]{};};
inline bool equal(const Digest&a,const Digest&b){uint8_t difference=0;for(size_t i=0;i<32;++i)difference|=a.bytes[i]^b.bytes[i];return difference==0;}
class Sha256 {
 uint32_t state_[8]={0x6a09e667u,0xbb67ae85u,0x3c6ef372u,0xa54ff53au,0x510e527fu,0x9b05688cu,0x1f83d9abu,0x5be0cd19u};
 uint8_t block_[64]{};size_t used_=0;uint64_t bytes_=0;
 static uint32_t rotate(uint32_t x,unsigned n){return (x>>n)|(x<<(32-n));}
 void transform(){
  static constexpr uint32_t k[64]={0x428a2f98u,0x71374491u,0xb5c0fbcfu,0xe9b5dba5u,0x3956c25bu,0x59f111f1u,0x923f82a4u,0xab1c5ed5u,0xd807aa98u,0x12835b01u,0x243185beu,0x550c7dc3u,0x72be5d74u,0x80deb1feu,0x9bdc06a7u,0xc19bf174u,0xe49b69c1u,0xefbe4786u,0x0fc19dc6u,0x240ca1ccu,0x2de92c6fu,0x4a7484aau,0x5cb0a9dcu,0x76f988dau,0x983e5152u,0xa831c66du,0xb00327c8u,0xbf597fc7u,0xc6e00bf3u,0xd5a79147u,0x06ca6351u,0x14292967u,0x27b70a85u,0x2e1b2138u,0x4d2c6dfcu,0x53380d13u,0x650a7354u,0x766a0abbu,0x81c2c92eu,0x92722c85u,0xa2bfe8a1u,0xa81a664bu,0xc24b8b70u,0xc76c51a3u,0xd192e819u,0xd6990624u,0xf40e3585u,0x106aa070u,0x19a4c116u,0x1e376c08u,0x2748774cu,0x34b0bcb5u,0x391c0cb3u,0x4ed8aa4au,0x5b9cca4fu,0x682e6ff3u,0x748f82eeu,0x78a5636fu,0x84c87814u,0x8cc70208u,0x90befffau,0xa4506cebu,0xbef9a3f7u,0xc67178f2u};
  uint32_t w[64]{};for(size_t i=0;i<16;++i)w[i]=(uint32_t(block_[i*4])<<24)|(uint32_t(block_[i*4+1])<<16)|(uint32_t(block_[i*4+2])<<8)|block_[i*4+3];
  for(size_t i=16;i<64;++i){const uint32_t a=w[i-15],b=w[i-2];w[i]=w[i-16]+(rotate(a,7)^rotate(a,18)^(a>>3))+w[i-7]+(rotate(b,17)^rotate(b,19)^(b>>10));}
  uint32_t a=state_[0],b=state_[1],c=state_[2],d=state_[3],e=state_[4],f=state_[5],g=state_[6],h=state_[7];
  for(size_t i=0;i<64;++i){const uint32_t t1=h+(rotate(e,6)^rotate(e,11)^rotate(e,25))+((e&f)^(~e&g))+k[i]+w[i];const uint32_t t2=(rotate(a,2)^rotate(a,13)^rotate(a,22))+((a&b)^(a&c)^(b&c));h=g;g=f;f=e;e=d+t1;d=c;c=b;b=a;a=t1+t2;}
  state_[0]+=a;state_[1]+=b;state_[2]+=c;state_[3]+=d;state_[4]+=e;state_[5]+=f;state_[6]+=g;state_[7]+=h;
 }
public:
 bool append(const void*data,size_t size){
  if((size&&!data)||size>~uint64_t(0)-bytes_)return false;
  const auto*p=static_cast<const uint8_t*>(data);bytes_+=size;
  while(size){const size_t n=size<64-used_?size:64-used_;::memcpy(block_+used_,p,n);used_+=n;p+=n;size-=n;if(used_==64){transform();used_=0;}}
  return true;
 }
 Digest finish(){
  const uint64_t bits=bytes_*8;block_[used_++]=0x80;
  if(used_>56){while(used_<64)block_[used_++]=0;transform();used_=0;}
  while(used_<56)block_[used_++]=0;
  for(unsigned i=0;i<8;++i)block_[63-i]=uint8_t(bits>>(i*8));
  transform();Digest value{};
  for(size_t i=0;i<8;++i)for(unsigned n=0;n<4;++n)value.bytes[i*4+n]=uint8_t(state_[i]>>(24-n*8));
  return value;
 }
};
struct KnownBundle {size_t bytes=0,shaders=0;Digest digest{};};
enum class Kind:uint8_t{request,bundle,shader};
struct Identity {uintptr_t native=0;int32_t instance=0;};
inline bool same(Identity a,Identity b){return a.native==b.native&&a.instance==b.instance;}
struct Api {
 bool(*thread)()=nullptr;
 bool(*identity)(void*,Kind,Identity&)=nullptr;
 uint32_t(*retain)(void*)=nullptr;void*(*target)(uint32_t)=nullptr;void(*release)(uint32_t)=nullptr;
 // Exact pinned original LoadAllAssets<Shader> result, not a caller-authored
 // descriptor list. On success the host transfers one strong-root handle for
 // the exact returned managed array. Registry retains it through all identity,
 // per-Shader retain, and publication calls, then releases it on every path.
 bool(*all_shaders)(void*,void**,size_t,size_t&,uint32_t&)=nullptr;
};
class Registry {
 struct Root {void*object=nullptr;Identity identity{};uint32_t handle=0;uint16_t source=0;};
 struct Pending {Root request{};uint16_t source=0;};
 Api api_{};const KnownBundle*known_=nullptr;size_t known_count_=0;
 Root bundles_[8]{},shaders_[128]{};Pending pending_[16]{};size_t bundle_count_=0,shader_count_=0;
 bool poisoned_=false,publishing_=false;
 bool rooted(Root&r,void*object,Kind kind,uint16_t source){Identity identity{};
  if(!object||!api_.identity(object,kind,identity)||!identity.native)return false;
  const uint32_t handle=api_.retain(object);if(!handle)return false;
  if(api_.target(handle)!=object){api_.release(handle);return false;}
  r={object,identity,handle,source};return true;
 }
 bool current(const Root&r,Kind kind)const{Identity identity{};return r.object&&r.handle&&api_.target(r.handle)==r.object&&api_.identity(r.object,kind,identity)&&same(identity,r.identity);}
 void drop(Root&r){if(r.handle)api_.release(r.handle);r={};}
 bool bundle(void*object,uint16_t source){
  if(!source||source>known_count_||poisoned_||publishing_||!api_.thread())return false;
  struct Publication{bool&active;explicit Publication(bool&v):active(v){active=true;}~Publication(){active=false;}} publication(publishing_);
  for(size_t i=0;i<bundle_count_;++i)if(bundles_[i].object==object)return bundles_[i].source==source&&current(bundles_[i],Kind::bundle);
  if(bundle_count_==8)return false;
  Root candidate{};if(!rooted(candidate,object,Kind::bundle,source))return false;
  void*values[64]{};size_t count=0;
  uint32_t actual_array=0;
  struct ArrayRoot{Api*api;uint32_t*handle;~ArrayRoot(){if(*handle)api->release(*handle);}}array_root{&api_,&actual_array};
  bool loaded=false;
  try{loaded=api_.all_shaders(object,values,64,count,actual_array);}catch(...){drop(candidate);throw;}
  if(!loaded||!actual_array||!api_.target(actual_array)||count!=known_[source-1].shaders||count>64||!current(candidate,Kind::bundle)){drop(candidate);return false;}
  // Validate the entire actual return array before publishing any provenance.
  Identity identities[64]{};size_t fresh=0;
  for(size_t i=0;i<count;++i){if(!values[i]||!api_.identity(values[i],Kind::shader,identities[i])||!identities[i].native){drop(candidate);return false;}
   for(size_t j=0;j<i;++j)if(values[i]==values[j]){drop(candidate);return false;}
   bool found=false;for(size_t j=0;j<shader_count_;++j)if(shaders_[j].object==values[i]){if(!current(shaders_[j],Kind::shader)){drop(candidate);return false;}found=true;break;}
   if(!found)++fresh;
  }
  if(fresh>128-shader_count_){drop(candidate);return false;}
  const size_t before=shader_count_;
  for(size_t i=0;i<count;++i){bool found=false;for(size_t j=0;j<shader_count_;++j)found|=shaders_[j].object==values[i];
   if(!found){if(!rooted(shaders_[shader_count_],values[i],Kind::shader,source)){while(shader_count_>before)drop(shaders_[--shader_count_]);drop(candidate);return false;}++shader_count_;}
  }
  if(!current(candidate,Kind::bundle)){while(shader_count_>before)drop(shaders_[--shader_count_]);drop(candidate);return false;}
  for(size_t i=before;i<shader_count_;++i)if(!current(shaders_[i],Kind::shader)){while(shader_count_>before)drop(shaders_[--shader_count_]);drop(candidate);return false;}
  bundles_[bundle_count_++]=candidate;return true;
 }
public:
 Registry()=default;Registry(const Registry&)=delete;Registry&operator=(const Registry&)=delete;
 bool configure(Api api,const KnownBundle*known,size_t count){
  if(known_||!known||!count||count>8||!api.thread||!api.identity||!api.retain||!api.target||!api.release||!api.all_shaders||!api.thread())return false;
  for(size_t i=0;i<count;++i)if(!known[i].bytes||known[i].bytes>16u*1024u*1024u||!known[i].shaders||known[i].shaders>64)return false;
  api_=api;known_=known;known_count_=count;return true;
 }
 uint16_t identify(size_t bytes,const Digest&digest)const{
  if(!known_||poisoned_)return 0;
  for(size_t i=0;i<known_count_;++i)if(known_[i].bytes==bytes&&equal(known_[i].digest,digest))return uint16_t(i+1);
  return 0;
 }
 // The host calls these only with actual saved-original return values. Input
 // identity is rehashed after the call; an unknown/changed input grants none.
 bool sync_result(void*actual_bundle,uint16_t before,uint16_t after){return before&&before==after&&bundle(actual_bundle,before);}
 bool async_result(void*actual_request,uint16_t before,uint16_t after){
  if(!known_||poisoned_||!api_.thread()||!before||before!=after||before>known_count_)return false;
  for(auto&slot:pending_)if(slot.request.object==actual_request)return slot.source==before&&current(slot.request,Kind::request);
  for(auto&slot:pending_)if(!slot.request.object){if(!rooted(slot.request,actual_request,Kind::request,before))return false;slot.source=before;return true;}
  return false;
 }
 void forget_request(void*request){
  if(!known_||!api_.thread())return;
  for(auto&slot:pending_)if(slot.request.object==request){drop(slot.request);slot={};return;}
 }
 bool bundle_result(void*actual_request,void*actual_bundle){
  if(!known_||poisoned_||!api_.thread()||!actual_request||!actual_bundle)return false;
  for(auto&slot:pending_)if(slot.request.object==actual_request){
   if(!current(slot.request,Kind::request)){drop(slot.request);slot={};return false;}
   const bool result=bundle(actual_bundle,slot.source);drop(slot.request);slot={};return result;
  }
  return false;
 }
 bool admits(void*actual_shader)const{
  if(!known_||poisoned_||!api_.thread()||!actual_shader)return false;
  for(size_t i=0;i<shader_count_;++i)if(shaders_[i].object==actual_shader)return current(shaders_[i],Kind::shader);
  return false;
 }
 void poison(){poisoned_=true;}
 // Ordinary Unity-thread retirement only; never the no-GC source observer.
 void clear(){for(auto&p:pending_){drop(p.request);p={};}for(size_t i=0;i<bundle_count_;++i)drop(bundles_[i]);for(size_t i=0;i<shader_count_;++i)drop(shaders_[i]);bundle_count_=shader_count_=0;known_=nullptr;known_count_=0;api_={};poisoned_=false;}
};
} // namespace idoly_mp4_shader_lineage
// END_MP4_SHADER_LINEAGE_STATE
