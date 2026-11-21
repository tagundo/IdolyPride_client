// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once
#ifndef IDOLY_DARWIN_BRIDGE
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <cstdlib>
#endif
#include "mp4_playback_state.hpp"

// The original ActorSwing solver advances by its own fixed step even when the
// AnimationStream delta is zero. This worker gate covers both the managed AOT
// ProcessAnimation body and the separate original Burst Execute callback. It
// does not establish ownership or complete Unity jobs: the main-thread owner
// must prove those boundaries before publishing/changing a grant or retiring.
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
        bool mode_changed = false, captured = false;
        uint32_t transforms_root = 0;
        void* transforms_array = nullptr;
        void* root_transform = nullptr;
        PoseEntry* poses = nullptr;
        size_t pose_count = 0;
        TimeEntry* times = nullptr;
        size_t time_count = 0;
    };
    StateApi api_{};
    StateLayout layout_{};
    WorkerGate* gate_ = nullptr;
    Actor actors_[max_owned_jobs]{};
    size_t count_ = 0, bytes_ = 0, warmed_ = 0;
    void* context_ = nullptr;
    uint64_t epoch_ = 0, serial_ = 0, simulation_serial_ = 0;
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
            && api_.set_local_position_rotation && api_.set_local_scale;
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
        const Result result = fence_all(); if (result != Result::ok) return result;
        if (gate_->stats().readers)
            return fail(Result::waiting, "actor_state_gate_readers_pending");
        if (published_ && gate_->hold(epoch_, true) != GateResult::ok)
            return fail(Result::stale, "actor_state_gate_changed");
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
            actor = Actor{};
        }
        count_ = bytes_ = warmed_ = 0; context_ = nullptr; epoch_ = serial_ = simulation_serial_ = 0;
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
    bool configure(StateApi api, WorkerGate* gate, const Owner* owners, size_t count,
            void* context, uint64_t epoch, StateLayout layout = {}) {
        if (configured_ || !gate || !owners || !count || count > max_owned_jobs || !context || !epoch) return false;
        api_ = api; layout_ = layout;
        if (!complete_api()) { error_ = "actor_state_api_unavailable"; return false; }
        gate_ = gate; context_ = context; epoch_ = epoch; count_ = count;
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
            status = api_.prepare_zero_pose(context_); if (status != Result::ok) return status;
            if (!owner_current()) return fail(Result::stale, "actor_state_owner_changed");
            zero_pose_prepared_ = true;
        }
        if (!__builtin_isfinite(api_.root_time(context_)) || __builtin_fabs(api_.root_time(context_)) > 0.000001)
            return fail(Result::unsupported, "actor_state_warmup_root_not_zero");
        if (!reset_started_) {
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
        simulation_serial_ = simulation_serial; error_ = "none"; return Result::ok;
    }
    Result restore() {
        Result status = ensure_held(); if (status != Result::ok) return status;
        if (restored_) return Result::ok;
        status = hold_gate(); if (status != Result::ok) return status;
        // Validate the entire selected set before any raw history/pose write.
        for (size_t i = 0; i < count_; ++i) if (changed_native_ && actors_[i].captured) {
            status = inspect_job(actors_[i], false); if (status != Result::ok) return status;
            if (!pose_current(actors_[i])) return fail(Result::stale, "actor_state_pose_owner_changed");
        }
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
        free_storage(); error_ = "none"; return Result::ok;
    }
};
} // namespace idoly_mp4_actor
