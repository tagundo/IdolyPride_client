#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#ifdef IDOLY_DARWIN_BRIDGE
#include "../ios/darwin_compat.hpp"
#else
#include <jni.h>
#include <dlfcn.h>
#include <elf.h>
#include <link.h>
#include <pthread.h>
#include <atomic>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <ctime>
#include <limits.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <stdlib.h>

#include "shadowhook.h"

#endif
#include "presentation_math.hpp"
#include "presentation_scope.hpp"
#include "orientation.hpp"
#include "playback_config.hpp"
#include "panorama_ui_edges.hpp"
#include "photography_ui.hpp"
#include "sound_persistence.hpp"
#include "mp4_game_bindings.hpp"
#include "mp4_controller_profile.hpp"
#include "mp4_camera_owner.hpp"
#include "mp4_type_descriptor.hpp"
#include "mp4_graph_modes.hpp"
#include "mp4_camera_clock.hpp"
#include "mp4_engine_clock_profile.hpp"
#include "mp4_actor_state.hpp"
#include "mp4_actor_state_profile.hpp"
#include "mp4_replay_profile.hpp"
#include "mp4_replay_factories.hpp"
#include "mp4_photography_replay_profile.hpp"
#include "mp4_photography_replay_factory.hpp"
#ifndef IDOLY_DARWIN_BRIDGE
#include "mp4_android_encoder.hpp"
#endif
#include "mp4_runtime.hpp"
#ifndef IDOLY_DARWIN_BRIDGE
#include "mp4_android_session.hpp"
#endif
#include "media_policy.hpp"
#include "hangul_font.hpp"
#ifndef IDOLY_DARWIN_BRIDGE
#include "wardrobe_lifecycle.hpp"
#include "wardrobe_timing.hpp"
#include "bulk_checked_filter.hpp"
#include "local_resource_policy.hpp"
#endif
#ifdef IDOLY_DARWIN_BRIDGE
#include "ios_profile.hpp"
#include "../ios/live_ui.hpp"
#else
#include "profile.hpp"
#endif

namespace {
using namespace idoly::presentation;
namespace pin = idoly::presentation::profile;
using Method = const void;
using VoidMethod = void (*)(void *, Method *);
using ObjectMethod = void *(*)(void *, Method *);

pthread_mutex_t config_mutex = PTHREAD_MUTEX_INITIALIZER;
Config pending;
bool mp4_queue_graphics_override=false;
Config mp4_queue_graphics;
bool configured = false;
std::atomic<bool> started{false}, ready{false};
uintptr_t image_base;
void *held_library;
// Set before hooks are published. PlayCover is identified by loaded AppKit;
// orientation waiting defaults to enabled on both desktop and phones.
#ifdef IDOLY_DARWIN_BRIDGE
bool desktop_host = false;
#endif
std::atomic<uintptr_t> game_thread_id{0};
pthread_mutex_t playback_mutex = PTHREAD_MUTEX_INITIALIZER;
PlaybackSettings playback_settings;
#ifndef IDOLY_DARWIN_BRIDGE
std::atomic<bool> android_multi_window{false};
#endif
pthread_mutex_t media_mutex = PTHREAD_MUTEX_INITIALIZER;
MediaPolicySettings media_settings;
bool accept_media_configuration(int schema,int64_t revision,bool use_master_order) {
    pthread_mutex_lock(&media_mutex);
    const bool accepted=media_settings.accept(schema,revision,use_master_order);
    pthread_mutex_unlock(&media_mutex); return accepted;
}
bool master_costume_order_enabled() {
    pthread_mutex_lock(&media_mutex); const bool enabled=media_settings.use_master_costume_order();
    pthread_mutex_unlock(&media_mutex); return enabled;
}
bool accept_playback_configuration(int schema,int64_t revision,bool wait) {
    pthread_mutex_lock(&playback_mutex);
    const bool accepted=playback_settings.accept(schema,revision,wait);
    pthread_mutex_unlock(&playback_mutex);return accepted;
}
bool playback_wait_for_orientation() {
    pthread_mutex_lock(&playback_mutex);
    const bool wait=playback_settings.wait();
    pthread_mutex_unlock(&playback_mutex);
#ifndef IDOLY_DARWIN_BRIDGE
    // Android keeps a split/freeform window's shape when the game requests a
    // physical turn. Use the existing bypass without changing the preference.
    return wait && !android_multi_window.load(std::memory_order_acquire);
#else
    return wait;
#endif
}
bool orientation_available() { return ready.load(std::memory_order_acquire); }
void playback_status_json(char *output,size_t size) {
    const bool supported=ready.load(std::memory_order_acquire);
    pthread_mutex_lock(&playback_mutex);
    const bool applied=supported && playback_settings.known();
    const bool wait=playback_settings.wait();
    const int64_t revision=playback_settings.revision();
    pthread_mutex_unlock(&playback_mutex);
    std::snprintf(output,size,"{\"schema\":1,\"bridge_version\":1,\"revision\":%lld,"
        "\"wait_for_orientation\":%s,\"supported\":%s,\"applied\":%s}",
        static_cast<long long>(revision),wait?"true":"false",supported?"true":"false",applied?"true":"false");
}

struct Status {
    int64_t revision = 0;
    const char *state = "waiting";
    bool fps = false, quality = false, resolution = false, aa = false, shadow = false, expanded = false;
    int screen_w = 0, screen_h = 0, render_w = 0, render_h = 0;
    float aspect = 0, base_fov = 0, fov = 0;
};
pthread_mutex_t status_mutex = PTHREAD_MUTEX_INITIALIZER;
Status state;

#ifndef IDOLY_DARWIN_BRIDGE
// BEGIN_READ_ONLY_RENDER_PROBE
// The tracker has no Unity calls. Its writer is the established game callback;
// JNI only formats a copied snapshot under render_probe_mutex.
struct RenderProbeSnapshot {
    const char *state = "waiting";
    int mode = -1, api = -1;
    int64_t tid = 0, observations = 0, sampled_ms = -1;
};
class RenderProbeTracker {
    RenderProbeSnapshot snapshot_;
    int64_t last_attempt_ms_ = -1;
public:
    static int64_t next_observation_count(int64_t count) {
        return count < INT64_MAX ? count + 1 : INT64_MAX;
    }
    bool begin_sample(int64_t now_ms) {
        if (now_ms < 0) return false;
        if (last_attempt_ms_ >= 0 && (now_ms < last_attempt_ms_
                || now_ms - last_attempt_ms_ < 2000)) return false;
        last_attempt_ms_ = now_ms;
        return true;
    }
    void initialization_failed() { snapshot_ = {}; snapshot_.state = "init_failed"; }
    void complete_sample(int64_t now_ms, int mode, int api, int64_t tid) {
        snapshot_.observations = next_observation_count(snapshot_.observations);
        snapshot_.sampled_ms = now_ms;
        snapshot_.api = api >= 0 && api <= 255 ? api : -1;
        snapshot_.tid = tid > 0 && tid <= INT32_MAX ? tid : 0;
        const bool valid = now_ms >= 0 && mode >= 0 && mode <= 5
            && snapshot_.api >= 0 && snapshot_.tid > 0;
        snapshot_.mode = valid ? mode : -1;
        snapshot_.state = valid ? "observed" : "unsupported";
    }
    RenderProbeSnapshot snapshot() const { return snapshot_; }
    static void write_json(const RenderProbeSnapshot &copy, int64_t now_ms,
            char *output, size_t capacity) {
        const bool sampled = copy.observations > 0;
        const bool has_age = sampled && copy.sampled_ms >= 0 && now_ms >= copy.sampled_ms;
        const bool observed = sampled && has_age && copy.mode >= 0 && copy.mode <= 5
            && copy.api >= 0 && copy.api <= 255 && copy.tid > 0 && copy.tid <= INT32_MAX;
        const char *status = sampled ? (observed ? "observed" : "unsupported") : copy.state;
        char mode[32], api[32], tid[32], age[32];
        auto number = [](char *buffer, int64_t value, bool present) -> const char * {
            if (!present) return "null";
            std::snprintf(buffer, 32, "%lld", static_cast<long long>(value)); return buffer;
        };
        std::snprintf(output, capacity,
            "{\"schema\":1,\"state\":\"%s\",\"actual_mode\":%s,\"graphics_api\":%s,"
            "\"callback_tid\":%s,\"observations\":%lld,\"sample_age_ms\":%s,"
            "\"cpu_frame_ms\":null,\"gpu_frame_ms\":null,\"timing_age_ms\":null}",
            status, number(mode, copy.mode, observed),
            number(api, copy.api, sampled && copy.api >= 0 && copy.api <= 255),
            number(tid, copy.tid, sampled && copy.tid > 0 && copy.tid <= INT32_MAX),
            static_cast<long long>(copy.observations),
            number(age, has_age ? now_ms - copy.sampled_ms : 0, has_age));
    }
};
// END_READ_ONLY_RENDER_PROBE
pthread_mutex_t render_probe_mutex = PTHREAD_MUTEX_INITIALIZER;
RenderProbeTracker render_probe;
int (*rendering_mode_get)(Method *), (*graphics_api_get)(Method *);
bool game_call(bool establish);
void cleanup_wardrobe();
int64_t render_probe_monotonic_ms() {
    timespec now{};
    if (clock_gettime(CLOCK_MONOTONIC, &now) || now.tv_sec < 0 || now.tv_nsec < 0
            || now.tv_nsec >= 1000000000 || now.tv_sec > (INT64_MAX - 999) / 1000) return -1;
    return static_cast<int64_t>(now.tv_sec) * 1000 + now.tv_nsec / 1000000;
}
void render_probe_init_failed() {
    pthread_mutex_lock(&render_probe_mutex); render_probe.initialization_failed();
    pthread_mutex_unlock(&render_probe_mutex);
}
void sample_render_probe() {
    if (!ready.load(std::memory_order_acquire) || !game_call(false) || !rendering_mode_get || !graphics_api_get) return;
    const int64_t now = render_probe_monotonic_ms();
    pthread_mutex_lock(&render_probe_mutex); const bool due = render_probe.begin_sample(now);
    pthread_mutex_unlock(&render_probe_mutex);
    if (!due) return;
    cleanup_wardrobe();
    int mode = -1, api = -1;
    try { mode = rendering_mode_get(nullptr); api = graphics_api_get(nullptr); }
    catch (...) { mode = -1; api = -1; }
    pthread_mutex_lock(&render_probe_mutex);
    render_probe.complete_sample(now, mode, api, static_cast<int64_t>(gettid()));
    pthread_mutex_unlock(&render_probe_mutex);
}
void render_probe_status_json(char *output, size_t capacity) {
    pthread_mutex_lock(&render_probe_mutex); const RenderProbeSnapshot copy = render_probe.snapshot();
    pthread_mutex_unlock(&render_probe_mutex);
    RenderProbeTracker::write_json(copy, render_probe_monotonic_ms(), output, capacity);
}
#endif

Config configuration(bool *has = nullptr) {
    pthread_mutex_lock(&config_mutex);
    Config result = mp4_queue_graphics_override?mp4_queue_graphics:pending;
    if (has) *has = configured||mp4_queue_graphics_override;
    pthread_mutex_unlock(&config_mutex);
    return result;
}
void set_state(const char *value) {
    pthread_mutex_lock(&status_mutex); state.state = value; pthread_mutex_unlock(&status_mutex);
#ifndef IDOLY_DARWIN_BRIDGE
    if (!std::strcmp(value, "unsupported") || !std::strcmp(value, "init_failed")) render_probe_init_failed();
#endif
}
bool game_call(bool establish = false) {
#ifdef IDOLY_DARWIN_BRIDGE
    const uintptr_t current = reinterpret_cast<uintptr_t>(pthread_self());
#else
    const uintptr_t current = static_cast<uintptr_t>(pthread_self());
#endif
    uintptr_t expected = 0;
    if (establish) game_thread_id.compare_exchange_strong(expected, current, std::memory_order_acq_rel);
    return game_thread_id.load(std::memory_order_acquire) == current;
}
#ifdef IDOLY_DARWIN_BRIDGE
bool desktop_enabled() { return ready.load(std::memory_order_acquire) && desktop_host; }
#endif
template<class T> T read(void *object, size_t offset) {
    T result{}; std::memcpy(&result, static_cast<char *>(object) + offset, sizeof result); return result;
}
template<class T> void write(void *object, size_t offset, T value) {
    std::memcpy(static_cast<char *>(object) + offset, &value, sizeof value);
}
template<class T> T function(const pin::Entry &entry) {
    return reinterpret_cast<T>(image_base + entry.rva);
}

#ifndef IDOLY_DARWIN_BRIDGE
// BEGIN_LOCAL_RESOURCE_REACHABILITY_HOOK
// Android's completed file request calls CanReach before its existing native
// error and MD5 processing, even after HTTP200. External network availability
// cannot decide whether the configured loopback object URL is usable. Only
// that URL class continues past this gate; every result check remains in the
// original executor. No Unity APIs, retained strings, allocation, or IO here.
bool (*resource_can_reach_original)(void *, Method *);
bool resource_can_reach_hook(void *self, Method *method) {
    if (ready.load(std::memory_order_acquire) && self && method) {
        // Verified original + packaged bootstrap constructor stores _url at
        // +0x10. IL2CPP System.String uses length +0x10 / UTF16 data +0x14.
        void *url = read<void *>(self, 0x10);
        if (url) {
            const int32_t length = read<int32_t>(url, 0x10);
            if (length > 0 && static_cast<size_t>(length) <= local_resources::max_url_units
                    && local_resources::object_url(reinterpret_cast<const uint16_t *>(
                        static_cast<const char *>(url) + 0x14), static_cast<size_t>(length)))
                return true;
        }
    }
    return resource_can_reach_original(self, method);
}
// END_LOCAL_RESOURCE_REACHABILITY_HOOK
#endif

uint32_t (*weak_new)(void *, bool);
void *(*weak_get)(uint32_t);
void (*weak_free)(uint32_t);
void *(*object_class)(void *);
const char *(*class_name)(void *);
const char *(*class_namespace)(void *);
void *(*class_parent)(void *);
bool (*object_alive)(void *, Method *);

// Korean fallback is independent of graphics preferences. All engine calls run
// after the original Awake, including startup callbacks before graphics ready.
VoidMethod font_awake_original;
void *(*font_name_get)(void *, Method *);
int32_t (*font_hide_get)(void *, Method *);
void (*font_hide_set)(void *, int32_t, Method *);
void (*font_multi)(void *, bool, Method *);
void (*font_clear)(void *, bool, Method *);
void *(*font_fallback)(void *, Method *);
uint32_t (*font_strong)(void *, bool);
const void *(*font_method)(void *, const char *, int32_t);
void *(*font_field)(void *, const char *);
const void *(*font_field_type)(void *);
void *(*font_class_type)(const void *);
void *(*font_new)(void *);
void (*font_fallback_set)(void *, void *, Method *);
hangul_font::Fallback korean_fallback;
hangul_font::ListFactory korean_list_factory;
pthread_mutex_t font_mutex=PTHREAD_MUTEX_INITIALIZER;
thread_local bool font_mutating=false;
struct FontListMethods {
    void *type=nullptr;
    const void *contains=nullptr, *insert=nullptr;
};
FontListMethods font_lists[4]{};
bool font_named(void *font,const char *expected) {
    void *name=font_name_get(font,nullptr);
    if (!name) return false;
    const int32_t length=read<int32_t>(name,0x10);
    if (length<0 || length>128 || static_cast<size_t>(length)!=std::strlen(expected)) return false;
    for (int32_t i=0;i<length;++i)
        if (read<uint16_t>(name,0x14+2*static_cast<size_t>(i))!=static_cast<unsigned char>(expected[i])) return false;
    return true;
}
bool font_insert_first(void *list,void *font) {
    void *type=object_class(list);
    if (!type) return false;
    FontListMethods *cached=nullptr;
    for (auto &entry:font_lists) if (entry.type==type) { cached=&entry;break; }
    if (!cached) for (auto &entry:font_lists) if (!entry.type) {
        const void *contains=font_method(type,"Contains",1);
        const void *insert=font_method(type,"Insert",2);
        if (!contains || !insert) return false;
        entry={type,contains,insert};cached=&entry;break;
    }
    if (!cached) return false;
    // IL2CPP MethodInfo begins with its executable methodPointer. Class/method
    // metadata is immutable; list and font objects are never cached here.
    using Contains=bool (*)(void *,void *,const void *);
    using Insert=void (*)(void *,int32_t,void *,const void *);
    auto contains=read<Contains>(const_cast<void *>(cached->contains),0);
    auto insert=read<Insert>(const_cast<void *>(cached->insert),0);
    if (!contains || !insert) return false;
    if (!contains(list,font,cached->contains)) insert(list,0,font,cached->insert);
    return true;
}
void *font_owner_class(void *font) {
    void *type=object_class(font);
    for (unsigned depth=0;type && depth<32;++depth,type=class_parent(type)) {
        const char *name=class_name(type), *space=class_namespace(type);
        if (name && space && !std::strcmp(name,"TMP_FontAsset") && !std::strcmp(space,"TMPro")) return type;
    }
    return nullptr;
}
void *font_ensure_fallbacks(void *font) { return korean_list_factory.ensure(font); }
void font_awake_hook(void *font,Method *method) {
    if (!font_awake_original) return;
    font_awake_original(font,method);
    if (font_mutating) return;
    struct MutationScope {
        MutationScope() { font_mutating=true;pthread_mutex_lock(&font_mutex); }
        ~MutationScope() { pthread_mutex_unlock(&font_mutex);font_mutating=false; }
    } scope;
    korean_fallback.after_original(font);
}

struct Weak {
    uint32_t handle = 0;
    void *get(bool unity_object = false) const {
        void *value = handle ? weak_get(handle) : nullptr;
        return value && (!unity_object || object_alive(value, nullptr)) ? value : nullptr;
    }
    void clear() { if (handle) weak_free(handle); handle = 0; }
    void set(void *value) {
        if (get() == value) return;
        clear(); if (value) handle = weak_new(value, false);
    }
};
// BEGIN_INVOCATION_RECT_TYPE_MEMO
// Only immutable class ancestry is reused, never object identity or liveness.
// Each post-original callback owns its stack entries; nested callbacks get an
// independent memo and restore the enclosing pointer even during unwinding.
struct RectTypeMemo {
    void *confirmed[4]{};
    bool contains(void *type) const {
        if (!type) return false;
        for (void *entry : confirmed) if (entry == type) return true;
        return false;
    }
    void remember(void *type) {
        if (!type) return;
        for (void *&entry : confirmed) {
            if (entry == type) return;
            if (!entry) { entry = type; return; }
        }
    }
};
thread_local RectTypeMemo *rect_type_memo = nullptr;
class RectTypeMemoScope {
    RectTypeMemo entries;
    RectTypeMemo *previous;
public:
    RectTypeMemoScope() : previous(rect_type_memo) { rect_type_memo = &entries; }
    ~RectTypeMemoScope() { rect_type_memo = previous; }
    RectTypeMemoScope(const RectTypeMemoScope &) = delete;
    RectTypeMemoScope &operator=(const RectTypeMemoScope &) = delete;
};
bool rect_transform(void *value) {
    if (!value || !object_alive(value, nullptr)) return false;
    void *type = object_class(value);
    void *initial_type = type;
    RectTypeMemo *memo = rect_type_memo;
    if (memo && memo->contains(type)) return true;
    for (unsigned depth = 0; type && depth != 12; ++depth, type = class_parent(type)) {
        const char *name = class_name(type), *space = class_namespace(type);
        if (name && space && !std::strcmp(name, "RectTransform") && !std::strcmp(space, "UnityEngine")) {
            if (memo) memo->remember(initial_type);
            return true;
        }
    }
    return false;
}
// END_INVOCATION_RECT_TYPE_MEMO

#ifdef IDOLY_DARWIN_BRIDGE
VoidMethod mv_ui_initialize_original;
void (*mv_ui_hide)(void *, bool, bool, Method *);
void mv_ui_initialize_hook(void *self, Method *method) {
    idoly_live_ui::initialize_default_off(self, method, mv_ui_initialize_original, mv_ui_hide,
        ready.load(std::memory_order_acquire) && desktop_host && game_call(true));
}
#endif
VoidMethod preview_ui_bind_original;
idoly::presentation::photography_ui::Calls preview_ui_calls;
idoly::presentation::photography_ui::DefaultHidden preview_ui;
void preview_ui_bind_hook(void *self, Method *method) {
#ifdef IDOLY_DARWIN_BRIDGE
    preview_ui.bind(self, method, preview_ui_bind_original,
        ready.load(std::memory_order_acquire) && desktop_host && game_call(true));
#else
    preview_ui.bind(self, method, preview_ui_bind_original,
        ready.load(std::memory_order_acquire) && game_call(true));
#endif
}

// BEGIN_ORIGINAL_COSTUME_SORT_DISPATCH
using CostumeListMethod = void *(*)(void *, void *, Method *);
CostumeListMethod costume_sorted_original, costume_order_sorted;
void *costume_sorted_hook(void *self, void *character_id, Method *method) {
    if (ready.load(std::memory_order_acquire) && game_call(false) && self && character_id
            && master_costume_order_enabled())
        return costume_order_sorted(self, character_id, nullptr);
    return costume_sorted_original(self, character_id, method);
}
// END_ORIGINAL_COSTUME_SORT_DISPATCH

#ifndef IDOLY_DARWIN_BRIDGE
namespace wardrobe = idoly::presentation::wardrobe;
wardrobe::Calls wardrobe_calls;
wardrobe::Lifecycle wardrobe_lifecycle;
wardrobe::Show wardrobe_show_original;
wardrobe::Move wardrobe_move_original;
wardrobe::Fail wardrobe_fail_original;
wardrobe::Wait wardrobe_wait_original;
pthread_mutex_t wardrobe_mutex = PTHREAD_MUTEX_INITIALIZER;
wardrobe::Tracker wardrobe_tracker;
namespace exit_timing = idoly::presentation::wardrobe_timing;
exit_timing::Tracker wardrobe_exit_tracker;
using ExitVoid = void (*)(void *, Method *);
using ExitTransition = void (*)(void *, void *, Method *);
using ExitTaskTransition = wardrobe::Task (*)(void *, void *, wardrobe::Token, Method *);
using ExitGC = void (*)(Method *);
using ExitUnload = void *(*)(Method *);
ExitVoid wardrobe_back_original, fitting_back_original, wardrobe_hide_move_original, wardrobe_disable_original;
ExitTransition character_list_open_in_original, character_list_close_in_original;
ExitTaskTransition wardrobe_preclose_original, character_details_close_in_original;
wardrobe::Show character_list_show_original;
ExitGC wardrobe_gc_collect_original;
ExitUnload wardrobe_unload_unused_original;
void wardrobe_event(const char *phase) {
    const int64_t now=render_probe_monotonic_ms();
    pthread_mutex_lock(&wardrobe_mutex); wardrobe_tracker.event(phase,now);
    pthread_mutex_unlock(&wardrobe_mutex);
}
void wardrobe_status_json(char *output,size_t capacity) {
    pthread_mutex_lock(&wardrobe_mutex); const wardrobe::Snapshot copy=wardrobe_tracker.snapshot();
    pthread_mutex_unlock(&wardrobe_mutex);
    const int64_t now=render_probe_monotonic_ms();
    char legacy[320], timing[1024];
    wardrobe::Tracker::json(copy,now,legacy,sizeof legacy);
    constexpr char prefix[]="{\"schema\":1";
    const size_t length=std::strlen(legacy);
    if (length && legacy[length-1]=='}' && !std::strncmp(legacy,prefix,sizeof prefix-1)
            && exit_timing::Tracker::json(wardrobe_exit_tracker.snapshot(now),timing,sizeof timing)) {
        legacy[length-1]='\0';
        const int written=std::snprintf(output,capacity,"{\"schema\":2%s,\"exit\":%s}",
            legacy+sizeof prefix-1,timing);
        if (written>=0 && static_cast<size_t>(written)<capacity) return;
        legacy[length-1]='}';
    }
    std::snprintf(output,capacity,"%s",legacy);
}
bool wardrobe_enabled() { return ready.load(std::memory_order_acquire) && game_call(false); }
namespace bulk_check = idoly::presentation::bulk_checked_filter;
bulk_check::Predicate bulk_costume_filter_original, bulk_hair_filter_original;
bulk_check::Checked bulk_costume_checked, bulk_hair_checked;
bool bulk_costume_filter_hook(void *self,void *row,Method *method) {
    return bulk_check::filter(self,row,method,bulk_costume_filter_original,bulk_costume_checked,wardrobe_enabled());
}
bool bulk_hair_filter_hook(void *self,void *row,Method *method) {
    return bulk_check::filter(self,row,method,bulk_hair_filter_original,bulk_hair_checked,wardrobe_enabled());
}
void wardrobe_back_hook(void *self,Method *method) {
    if (!wardrobe_enabled()) return wardrobe_back_original(self,method);
    wardrobe_exit_tracker.invoke_back(exit_timing::Room::CharacterCostume,wardrobe_back_original,self,method);
}
void fitting_back_hook(void *self,Method *method) {
    if (!wardrobe_enabled()) return fitting_back_original(self,method);
    wardrobe_exit_tracker.invoke_back(exit_timing::Room::FittingRoom,fitting_back_original,self,method);
}
wardrobe::Task wardrobe_preclose_hook(void *self,void *info,wardrobe::Token token,Method *method) {
    if (!wardrobe_enabled()) return wardrobe_preclose_original(self,info,token,method);
    return wardrobe_exit_tracker.invoke_close(exit_timing::Room::CharacterCostume,
        exit_timing::Stage::Preclose,wardrobe_preclose_original,self,info,token,method);
}
void wardrobe_hide_move_hook(void *self,Method *method) {
    if (!wardrobe_enabled()) return wardrobe_hide_move_original(self,method);
    wardrobe_exit_tracker.invoke(exit_timing::Stage::Hide,wardrobe_hide_move_original,self,method);
}
void wardrobe_disable_hook(void *self,Method *method) {
    if (!wardrobe_enabled()) return wardrobe_disable_original(self,method);
    wardrobe_exit_tracker.invoke(exit_timing::Stage::Disable,wardrobe_disable_original,self,method);
}
wardrobe::Task character_list_show_hook(void *self,wardrobe::Token token,Method *method) {
    if (!wardrobe_enabled()) return character_list_show_original(self,token,method);
    return wardrobe_exit_tracker.invoke(exit_timing::Stage::SelectionShow,character_list_show_original,self,token,method);
}
void character_list_open_in_hook(void *self,void *info,Method *method) {
    if (!wardrobe_enabled()) return character_list_open_in_original(self,info,method);
    wardrobe_exit_tracker.invoke(exit_timing::Stage::SelectionOpen,character_list_open_in_original,self,info,method);
    wardrobe_exit_tracker.complete();
}
void character_list_close_in_hook(void *self,void *info,Method *method) {
    if (!wardrobe_enabled()) return character_list_close_in_original(self,info,method);
    wardrobe_exit_tracker.invoke(exit_timing::Stage::SelectionOpen,character_list_close_in_original,self,info,method);
    wardrobe_exit_tracker.complete();
}
wardrobe::Task character_details_close_in_hook(void *self,void *info,wardrobe::Token token,Method *method) {
    if (!wardrobe_enabled()) return character_details_close_in_original(self,info,token,method);
    return wardrobe_exit_tracker.invoke(exit_timing::Stage::SelectionOpen,character_details_close_in_original,self,info,token,method);
}
void wardrobe_gc_collect_hook(Method *method) {
    if (!wardrobe_enabled() || !wardrobe_exit_tracker.active()) return wardrobe_gc_collect_original(method);
    wardrobe_exit_tracker.invoke(exit_timing::Stage::GC,wardrobe_gc_collect_original,method);
}
void *wardrobe_unload_unused_hook(Method *method) {
    if (!wardrobe_enabled() || !wardrobe_exit_tracker.active()) return wardrobe_unload_unused_original(method);
    return wardrobe_exit_tracker.invoke(exit_timing::Stage::Unload,wardrobe_unload_unused_original,method);
}
void cleanup_wardrobe() { if (wardrobe_enabled()) wardrobe_lifecycle.cleanup(); }
wardrobe::Task wardrobe_show_hook(void *self,wardrobe::Token token,Method *method) {
    return wardrobe_lifecycle.show(self,token,method,wardrobe_show_original,wardrobe_enabled());
}
void wardrobe_move_hook(void *self,Method *method) {
    wardrobe_lifecycle.move(self,method,wardrobe_move_original,wardrobe_enabled());
}
void wardrobe_fail_hook(void *self,void *exception,Method *method) {
    wardrobe_lifecycle.fail(self,exception,method,wardrobe_fail_original,wardrobe_enabled());
}
wardrobe::Task wardrobe_wait_hook(void *predicate,int timing,wardrobe::Token token,Method *method) {
    return wardrobe_lifecycle.wait(predicate,timing,token,method,wardrobe_wait_original,wardrobe_enabled());
}
#endif

VoidMethod quality_update_original, quality_init_original, quality_apply_original;
void (*quality_set_original)(void *, int, Method *);
int (*app_fps_get)(Method *);
void (*app_fps_set_original)(int, Method *);
void *(*quality_names)(Method *);
int (*screen_width)(Method *), (*screen_height)(Method *);
int (*max_texture)(Method *);
int (*rt_width)(void *, Method *), (*rt_height)(void *, Method *);
ObjectMethod rt_camera, rt_target, target_current, target_rect, parent_get;
void *(*target_to_texture)(void *, Method *);
void (*rt_original)(void *, int, int, bool, Method *);
VoidMethod rt_destroy;
uint64_t (*limited_original)(int, int, Vec2, int, float, bool, Method *);
float (*fov_get_original)(void *, Method *), (*aspect_get_original)(void *, Method *);
void (*fov_set_original)(void *, float, Method *);
float (*focal_get_original)(void *, Method *);
void (*focal_set_original)(void *, float, Method *);
void (*camera_aspect_set_original)(void *, float, Method *);
VoidMethod camera_aspect_reset;
void (*projection_get)(void *, ProjectionMatrix *, Method *);
bool (*physical_get)(void *, Method *);
int (*gate_get)(void *, Method *), (*projection_mode_get)(void *, Method *);
void (*sensor_get)(void *, Vec2 *, Method *), (*lens_get)(void *, Vec2 *, Method *);
void (*camera_rect_get)(void *, Rect *, Method *);
void (*transform_rect_get)(void *, Rect *, Method *);
void (*local_position)(void *, Vec3 *, Method *), (*local_scale)(void *, Vec3 *, Method *);
void (*local_rotation)(void *, Quaternion *, Method *);
void (*size_delta_get)(void *, Vec2 *, Method *), (*size_delta_set)(void *, const Vec2 *, Method *);
void (*local_position_set)(void *, const Vec3 *, Method *);
bool (*active_enabled)(void *, Method *);
bool (*orthographic)(void *, Method *);
void (*target_update_original)(void *, void *, Method *);
VoidMethod target_late_original, scene_main_update_original, scene_main_reset_original;
VoidMethod scene_pano_update_original, scene_pano_reset_original;
Rect (*uv_get)(void *, Method *);
void (*aa_original)(void *, void *, bool, void *, Method *);
bool (*shadow_original)(void *, void *, void **, int, Method *);

namespace rotation = idoly::presentation::orientation;
rotation::Calls orientation_calls;
PanoramaEdgeApi panorama_api;
PanoramaEdgeLayout panorama_ui;
bool class_matches(void *object, const char *space, const char *name) {
    if (!object) return false;
    void *type = object_class(object);
    for (unsigned depth = 0; type && depth != 32; ++depth, type = class_parent(type)) {
        const char *actual = class_name(type), *actual_space = class_namespace(type);
        if (actual && actual_space && !std::strcmp(actual, name) && !std::strcmp(actual_space, space)) return true;
    }
    return false;
}

int64_t sound_monotonic_ms() {
    timespec now{};
#ifdef IDOLY_DARWIN_BRIDGE
    constexpr unsigned clock_id=6;
#else
    constexpr clockid_t clock_id=CLOCK_MONOTONIC;
#endif
    if (clock_gettime(clock_id,&now) || now.tv_sec<0 || now.tv_nsec<0
            || now.tv_nsec>=1000000000 || now.tv_sec>(0x7fffffffffffffffLL-999)/1000) return -1;
    return static_cast<int64_t>(now.tv_sec)*1000+now.tv_nsec/1000000;
}

// BEGIN_SOUND_AUTOSAVE_HOOKS
namespace sound = idoly::presentation::sound_persistence;
sound::Tracker sound_tracker;
using SoundVolumeMethod = void (*)(void *,float,Method *);
using SoundToggleMethod = void (*)(void *,bool,Method *);
SoundVolumeMethod sound_bgm_volume_original,sound_se_volume_original,sound_voice_volume_original;
SoundToggleMethod sound_bgm_soundable_original,sound_se_soundable_original,sound_voice_soundable_original;
VoidMethod sound_bind_original,sound_save_original;
void sound_bind_hook(void *self,Method *method) {
    sound_tracker.bind(self,method,sound_bind_original,
        ready.load(std::memory_order_acquire) && game_call(false));
}
void sound_save_hook(void *self,Method *method) {
    sound_save_original(self,method);
    sound_tracker.observed_save(self,ready.load(std::memory_order_acquire) && game_call(false));
}
bool sound_save_auto(void *self) {
    // Only the added autosave catches its own failure. Stock Save exceptions
    // still propagate through sound_save_hook unchanged.
    try { sound_save_original(self,nullptr);return true; }
    catch (...) { return false; }
}
void sound_bgm_volume_hook(void *self,float value,Method *method) {
    const bool enabled=ready.load(std::memory_order_acquire) && game_call(false);
    const auto before=sound_tracker.before(self,sound::Field::BgmVolume,enabled);
    sound_bgm_volume_original(self,value,method);
    sound_tracker.after(self,before,enabled);
}
void sound_bgm_soundable_hook(void *self,bool value,Method *method) {
    const bool enabled=ready.load(std::memory_order_acquire) && game_call(false);
    const auto before=sound_tracker.before(self,sound::Field::BgmSoundable,enabled);
    sound_bgm_soundable_original(self,value,method);
    sound_tracker.after(self,before,enabled);
}
void sound_se_volume_hook(void *self,float value,Method *method) {
    const bool enabled=ready.load(std::memory_order_acquire) && game_call(false);
    const auto before=sound_tracker.before(self,sound::Field::SeVolume,enabled);
    sound_se_volume_original(self,value,method);
    sound_tracker.after(self,before,enabled);
}
void sound_se_soundable_hook(void *self,bool value,Method *method) {
    const bool enabled=ready.load(std::memory_order_acquire) && game_call(false);
    const auto before=sound_tracker.before(self,sound::Field::SeSoundable,enabled);
    sound_se_soundable_original(self,value,method);
    sound_tracker.after(self,before,enabled);
}
void sound_voice_volume_hook(void *self,float value,Method *method) {
    const bool enabled=ready.load(std::memory_order_acquire) && game_call(false);
    const auto before=sound_tracker.before(self,sound::Field::VoiceVolume,enabled);
    sound_voice_volume_original(self,value,method);
    sound_tracker.after(self,before,enabled);
}
void sound_voice_soundable_hook(void *self,bool value,Method *method) {
    const bool enabled=ready.load(std::memory_order_acquire) && game_call(false);
    const auto before=sound_tracker.before(self,sound::Field::VoiceSoundable,enabled);
    sound_voice_soundable_original(self,value,method);
    sound_tracker.after(self,before,enabled);
}
// END_SOUND_AUTOSAVE_HOOKS

Weak quality_manager, main_controller;
Weak controller_candidates[4];
unsigned candidate_cursor = 0;
int base_quality = 0, applied_quality = 0;
std::atomic<uint64_t> application_fps_baseline{0};
constexpr uint64_t FPS_KNOWN = uint64_t{1} << 63;
int64_t resolution_revision = -1;
Config rendered_configuration;
bool rendered_configuration_known = false;
int rendered_screen_width = 0, rendered_screen_height = 0;
Dimensions rendered_dimensions{};
int64_t aa_revision = -1, shadow_revision = -1;
bool aa_unavailable = false, shadow_unavailable = false;
thread_local void *resolution_scope;
struct ResolutionAttempt { bool computed = false; Dimensions expected{}; Config config{}; int width = 0, height = 0; };
thread_local ResolutionAttempt *resolution_attempt;
thread_local bool internal_camera = false;
thread_local bool scene_enter = false, scene_exit = false;

struct Photography {
    Weak owner, controller, camera, image, viewport_parent;
    bool active = false, geometry_known = false, base_known = false, expanded = false, target_expanded = false;
    bool geometry_confirmed = false;
    unsigned layout_ticks = 0;
    int64_t rejected_revision = -1;
    Dimensions rejected_viewport{};
    bool original_dynamic = false;
    Vec2 ratio{16, 9};
    Dimensions viewport{}, built_viewport{};
    Rect viewport_rect{};
    Rect original_image_frame{};
    bool original_image_frame_known = false;
    CameraState original{};
    Frustum original_frustum{};
    float original_focal = 0;
    bool physical = false;
    int gate = 0, projection_mode = 0;
    Vec2 sensor{}, lens{};
} photo;
struct ImageLayout {
    Weak rect;
    bool saved = false, changed = false;
    Vec2 original_delta{}, written_delta{};
    Vec3 original_position{}, written_position{};
};
ImageLayout image_layouts[4];
bool geometry_unsupported = false;

bool runtime_type(void *object, const char *name) {
    if (!object || !object_alive(object, nullptr)) return false;
    void *type = object_class(object);
    const char *actual = type ? class_name(type) : nullptr;
    const char *space = type ? class_namespace(type) : nullptr;
    return actual && space && !std::strcmp(actual, name) && !std::strcmp(space, "UnityEngine");
}
bool expansion_plan(CameraState base, Dimensions viewport, CameraState *output) {
    *output = expanded_camera(base, viewport, true);
    return dimensions_valid(viewport) && camera_valid(*output)
        && std::fabs(output->aspect - static_cast<float>(viewport.width) / viewport.height) < .0001f;
}

bool full_rect(Rect rect) {
    return std::fabs(rect.x) < .001f && std::fabs(rect.y) < .001f
        && std::fabs(rect.width - 1) < .001f && std::fabs(rect.height - 1) < .001f;
}
void remember_controller(void *controller) {
    for (auto &candidate : controller_candidates) if (candidate.get(true) == controller) return;
    for (auto &candidate : controller_candidates) if (!candidate.get(true)) { candidate.set(controller); return; }
    controller_candidates[candidate_cursor++ % 4].set(controller);
}
void identify_main_target(void *image, void *texture) {
    if (!image || !texture || read<int>(image, 0x20) != 0 || texture != target_current(image, nullptr)) return;
    for (auto &candidate : controller_candidates) {
        void *controller = candidate.get(true);
        if (controller && texture == target_to_texture(rt_target(controller, nullptr), nullptr)) {
            main_controller.set(controller); return;
        }
    }
}
void *graphics_camera() {
    void *controller = main_controller.get(true);
    void *camera = controller ? rt_camera(controller, nullptr) : nullptr;
    return camera && object_alive(camera, nullptr) ? camera : nullptr;
}
// BEGIN_MP4_ORIGINAL_GAME_BOUNDARY
namespace mp4game = idoly_mp4_game;
#ifdef IDOLY_DARWIN_BRIDGE
constexpr const auto &mp4_profile=mp4game::ios_game_profile;
constexpr const auto &mp4_runtime_profile=mp4game::ios_runtime_profile;
constexpr const auto &mp4_bindings=mp4game::ios_game_bindings;
constexpr const auto &mp4_controller_profile=mp4game::ios_controller_profile;
constexpr const auto &mp4_camera_owner_profile=mp4game::ios_camera_owner_profile;
constexpr const auto &mp4_type_metadata_profile=mp4game::ios_type_metadata_profile;
#else
constexpr const auto &mp4_profile=mp4game::android_game_profile;
constexpr const auto &mp4_runtime_profile=mp4game::android_runtime_profile;
constexpr const auto &mp4_bindings=mp4game::android_game_bindings;
constexpr const auto &mp4_controller_profile=mp4game::android_controller_profile;
constexpr const auto &mp4_camera_owner_profile=mp4game::android_camera_owner_profile;
constexpr const auto &mp4_type_metadata_profile=mp4game::android_type_metadata_profile;
#endif
mp4game::Api mp4_api;
pthread_mutex_t mp4_graph_mode_mutex=PTHREAD_MUTEX_INITIALIZER;
mp4game::GraphModes mp4_graph_modes;
thread_local bool mp4_owned_camera_scope=false;
thread_local mp4game::CameraGrant mp4_camera_grant;
void mp4_owned_brain_manual_update(void*,mp4game::Method*);
bool mp4_camera_clock_ok();
bool mp4_recorded_graph_mode(const mp4game::PlayableGraph*,int32_t*);
bool mp4_source_verified=false,mp4_api_installed=false;
bool mp4_replay_verified=false;
uint32_t mp4_controller_type_handle=0;
char mp4_binding_error[96]="original_mv_bindings_unverified";
// The game owns the controller and the texture. Exporting only scopes an
// original UpdateRenderTarget call, then restores the pre-export pixel size.
Weak mp4_geometry_controller;
Weak mp4_geometry_camera;
int32_t mp4_geometry_width=0,mp4_geometry_height=0;
int32_t mp4_geometry_previous_width=0,mp4_geometry_previous_height=0;
bool mp4_geometry_active=false;
struct Mp4Projection {
    bool saved=false,required_known=false;
    float reference_aspect=0,base_fov=0,base_focal=0,restore_fov=0,restore_focal=0;
    bool restore_physical=false;
    Frustum required{};
} mp4_projection;
idoly_mp4_replay_factories::Factory mp4_replay_factory;
// Match queue owners: bounded process-lifetime storage avoids managed calls
// from C++ atexit after IL2CPP/domain teardown. Rebuild/configure releases the
// previous tree on Unity; scoped Factory instances still use their destructor.
alignas(idoly_mp4_photography_replay::Factory) uint8_t mp4_photography_factory_storage[sizeof(idoly_mp4_photography_replay::Factory)]{};
bool mp4_photography_factory_initialized=false;
idoly_mp4_photography_replay::Factory& mp4_photography_factory(){
    if(!mp4_photography_factory_initialized){
#ifdef IDOLY_DARWIN_BRIDGE
        new(idoly_mp4_queue_placement::Address{mp4_photography_factory_storage})idoly_mp4_photography_replay::Factory{};
#else
        new(mp4_photography_factory_storage)idoly_mp4_photography_replay::Factory{};
#endif
        mp4_photography_factory_initialized=true;
    }
    return *reinterpret_cast<idoly_mp4_photography_replay::Factory*>(mp4_photography_factory_storage);
}
bool mp4_photography_verified=false;
struct Mp4PhotographyBoolTask {void* source;uint8_t result,padding;short token;uint8_t reserved[4];};
static_assert(sizeof(Mp4PhotographyBoolTask)==16&&__builtin_offsetof(Mp4PhotographyBoolTask,result)==8
    &&__builtin_offsetof(Mp4PhotographyBoolTask,token)==10,"Original Boolean UniTask ABI differs");
struct Mp4PhotographyNavigation {
    void* manager_class=nullptr;void* instance_field=nullptr;void* scene_field=nullptr;void* allow_field=nullptr;
    void(*static_get)(const void*,void*)=nullptr;
    void(*set_data)(void*,void*,Method*)=nullptr;void(*load_scene)(void*,int32_t,int32_t,Method*)=nullptr;
    void*(*download_targets)(void*,Method*)=nullptr;
    Mp4PhotographyBoolTask(*pre_download)(void*,idoly_mp4_replay::CancellationToken8,bool,Method*)=nullptr;
    int32_t(*task_status)(Mp4PhotographyBoolTask*,Method*)=nullptr;
    Mp4PhotographyBoolTask(*task_awaiter)(Mp4PhotographyBoolTask*,Method*)=nullptr;
    bool(*task_result)(Mp4PhotographyBoolTask*,Method*)=nullptr;
    Method* status_info=nullptr;Method* awaiter_info=nullptr;Method* result_info=nullptr;
    bool(*dispatch_paused)()=nullptr;
    Mp4PhotographyBoolTask task{};
    uint32_t manager_handle=0,transition_handle=0,targets_handle=0,source_handle=0;
    int32_t load_mode=0,phase=0;bool configured=false,pending=false,failed=false,cancel_requested=false,task_consumed=false;
    uint64_t generation=0,dispatch_generation=0;
    char error[96]="photography_navigation_unavailable";
} mp4_photography_navigation;
char mp4_photography_binding_error[96]="photography_bindings_unverified";
#ifdef IDOLY_DARWIN_BRIDGE
constexpr const auto& mp4_replay_profile=idoly_mp4_replay::ios_replay_profile;
constexpr const auto& mp4_replay_bindings=idoly_mp4_replay::ios_replay_bindings;
constexpr const auto& mp4_photography_profile=idoly_mp4_photography_replay::ios_profile;
constexpr const auto& mp4_photography_code_bindings=idoly_mp4_photography_replay::ios_code_bindings;
constexpr const auto& mp4_photography_type_bindings=idoly_mp4_photography_replay::ios_type_bindings;
#else
constexpr const auto& mp4_replay_profile=idoly_mp4_replay::android_replay_profile;
constexpr const auto& mp4_replay_bindings=idoly_mp4_replay::android_replay_bindings;
constexpr const auto& mp4_photography_profile=idoly_mp4_photography_replay::android_profile;
constexpr const auto& mp4_photography_code_bindings=idoly_mp4_photography_replay::android_code_bindings;
constexpr const auto& mp4_photography_type_bindings=idoly_mp4_photography_replay::android_type_bindings;
#endif
void *mp4_single_class=nullptr,*mp4_texture_class=nullptr;
uint32_t mp4_audio_type_handle=0;
void *(*mp4_array_new)(void*,uintptr_t);
void *(*mp4_string_new)(const char*);
void *(*mp4_type_get_object)(const void*);

bool mp4_mapped(uintptr_t address,size_t bytes,bool executable) {
    if(!image_base||address<image_base||!bytes)return false;
#ifdef IDOLY_DARWIN_BRIDGE
    const uint32_t commands=read<uint32_t>(reinterpret_cast<void*>(image_base),16);
    const uint32_t length=read<uint32_t>(reinterpret_cast<void*>(image_base),20);
    if(commands>128||length>65536)return false;
    size_t offset=32;
    for(unsigned i=0;i<commands;++i){
        if(offset+8>32+length)return false;
        const uint32_t command=read<uint32_t>(reinterpret_cast<void*>(image_base),offset);
        const uint32_t size=read<uint32_t>(reinterpret_cast<void*>(image_base),offset+4);
        if(size<8||offset+size>32+length)return false;
        if(command==0x19&&size>=72){
            const uintptr_t start=image_base+read<uint64_t>(reinterpret_cast<void*>(image_base),offset+24);
            const uintptr_t span=read<uint64_t>(reinterpret_cast<void*>(image_base),offset+32);
            const uint32_t protection=read<uint32_t>(reinterpret_cast<void*>(image_base),offset+60);
            const uint32_t needed=executable?5:1;
            if((protection&needed)==needed&&address>=start&&bytes<=span&&address-start<=span-bytes)return true;
        }
        offset+=size;
    }
#else
    const auto *header=reinterpret_cast<const ElfW(Ehdr)*>(image_base);
    if(header->e_phnum>128||header->e_phentsize!=sizeof(ElfW(Phdr))||header->e_phoff>65536)return false;
    const auto *segments=reinterpret_cast<const ElfW(Phdr)*>(image_base+header->e_phoff);
    for(size_t i=0;i<header->e_phnum;++i){
        const auto &segment=segments[i];const uintptr_t start=image_base+segment.p_vaddr;
        const unsigned needed=executable?(PF_R|PF_X):PF_R;
        if(segment.p_type==PT_LOAD&&(segment.p_flags&needed)==needed&&address>=start
            &&bytes<=segment.p_memsz&&address-start<=segment.p_memsz-bytes)return true;
    }
#endif
    return false;
}
bool mp4_prefix(const mp4game::Binding &binding,bool executable=true) {
    const uintptr_t address=image_base+binding.rva;
    return address>=image_base&&mp4_mapped(address,16,executable)
        &&!std::memcmp(reinterpret_cast<void*>(address),binding.prefix,16);
}
#ifdef IDOLY_DARWIN_BRIDGE
extern "C" {
extern unsigned int mach_task_self_;
int mach_vm_region(unsigned int,uint64_t*,uint64_t*,int,int*,unsigned int*,unsigned int*);
int mach_port_deallocate(unsigned int,unsigned int);
}
#endif
bool mp4_readable_memory(uintptr_t address,size_t bytes){
    if(!address||!bytes||bytes>64*1024*1024||address+bytes<address)return false;
    const uintptr_t end=address+bytes;uintptr_t cursor=address;
#ifdef IDOLY_DARWIN_BRIDGE
    // Public Mach VM query, including metadata mmap regions outside the image.
    // Only VM_PROT_READ is used from VM_REGION_BASIC_INFO_64 (flavor 9).
    for(unsigned attempt=0;attempt<64&&cursor<end;++attempt){
        uint64_t begin=cursor,span=0;int info[16]{};unsigned int count=16,object=0;
        const int result=mach_vm_region(mach_task_self_,&begin,&span,9,info,&count,&object);
        if(object)(void)mach_port_deallocate(mach_task_self_,object);
        if(result||count<1||!(info[0]&1)||begin>cursor||!span||begin+span<begin||begin+span<=cursor)return false;
        cursor=begin+span<end?begin+span:end;
    }
#else
    // Own-process maps are public on Android. Bound this one-time startup
    // scan; no profile paths or mapping contents leave the native validator.
    FILE* maps=fopen("/proc/self/maps","r");if(!maps)return false;
    char line[512]{};unsigned lines=0;
    while(cursor<end&&lines++<16384&&fgets(line,sizeof(line),maps)){
        unsigned long long begin=0,limit=0;char permissions[5]{};
        if(sscanf(line,"%llx-%llx %4s",&begin,&limit,permissions)!=3)continue;
        if(begin>cursor)break;
        if(limit<=cursor)continue;
        if(permissions[0]!='r')break;
        cursor=limit<end?static_cast<uintptr_t>(limit):end;
    }
    fclose(maps);
#endif
    return cursor==end;
}
// BEGIN_MP4_NATIVE_CLOCK_VALIDATION
namespace mp4clock=idoly_mp4_engine_clock;
#ifdef IDOLY_DARWIN_BRIDGE
constexpr const auto& mp4_native_profile=mp4clock::ios_profile;
constexpr uintptr_t mp4_native_registry_getter=0xbe3c58;
constexpr unsigned char mp4_native_registry_prefix[16]={0xa8,0xe3,0x04,0xf0,0x08,0x41,0x0f,0x91,0x00,0xd9,0x60,0xf8,0xc0,0x03,0x5f,0xd6};
#else
constexpr const auto& mp4_native_profile=mp4clock::android_profile;
constexpr uintptr_t mp4_native_registry_getter=0x55756c;
constexpr unsigned char mp4_native_registry_prefix[16]={0x08,0x7a,0x00,0x90,0x08,0x21,0x20,0x91,0x00,0xd9,0x60,0xf8,0xc0,0x03,0x5f,0xd6};
#endif
struct Mp4NativeSegment {uintptr_t begin=0,size=0;unsigned flags=0;};
Mp4NativeSegment mp4_native_segments[32]{};size_t mp4_native_segment_count=0;
uintptr_t mp4_native_base=0;
void* mp4_native_manager_cache=nullptr;
std::atomic<bool> mp4_native_clock_source_ready{false},mp4_native_clock_armed{false};
std::atomic<const char*> mp4_native_clock_error{"native_clock_not_installed"};
[[maybe_unused]] const char* mp4_native_clock_error_code(){return mp4_native_clock_error.load(std::memory_order_acquire);}
using Mp4NativeTime=void(*)(void*,double);
Mp4NativeTime mp4_native_time_original=nullptr;
bool mp4_native_mapped(uintptr_t address,size_t bytes,unsigned flags){
    if(!address||!bytes||address+bytes<address)return false;
    for(size_t i=0;i<mp4_native_segment_count;++i){const auto& segment=mp4_native_segments[i];
        if((segment.flags&flags)==flags&&address>=segment.begin&&bytes<=segment.size
            &&address-segment.begin<=segment.size-bytes)return true;}
    return false;
}
bool mp4_native_manager_writable(uintptr_t address){
    // This query runs once for a new registry receiver on the established
    // Unity thread, never from a worker job or once per exported frame.
    if(!address||address+0x108<address)return false;
    const uintptr_t end=address+0x108;uintptr_t cursor=address;
#ifdef IDOLY_DARWIN_BRIDGE
    for(unsigned attempt=0;attempt<8&&cursor<end;++attempt){
        uint64_t begin=cursor,span=0;int info[16]{};unsigned count=16,object=0;
        const int result=mach_vm_region(mach_task_self_,&begin,&span,9,info,&count,&object);
        if(object)(void)mach_port_deallocate(mach_task_self_,object);
        if(result||!count||(info[0]&3)!=3||begin>cursor||!span||begin+span<begin||begin+span<=cursor)return false;
        cursor=begin+span<end?begin+span:end;
    }
#else
    FILE* maps=fopen("/proc/self/maps","r");if(!maps)return false;
    char line[512]{};unsigned lines=0;
    while(cursor<end&&lines++<16384&&fgets(line,sizeof(line),maps)){
        unsigned long long begin=0,limit=0;char permissions[5]{};
        if(sscanf(line,"%llx-%llx %4s",&begin,&limit,permissions)!=3)continue;
        if(begin>cursor)break;
        if(limit<=cursor)continue;
        if(permissions[0]!='r'||permissions[1]!='w')break;
        cursor=limit<end?static_cast<uintptr_t>(limit):end;
    }
    fclose(maps);
#endif
    return cursor==end;
}
bool mp4_native_current_manager(void* manager){
    if(!mp4_native_clock_source_ready.load(std::memory_order_acquire)||!game_call()||!manager)return false;
    // The audited original getter is Registry[7]. Check its independently
    // pinned direct cell before reading any potentially retired receiver.
    const uintptr_t slot=mp4_native_base+mp4_native_profile.registry_slot;
    if(__atomic_load_n(reinterpret_cast<uintptr_t*>(slot),__ATOMIC_ACQUIRE)!=reinterpret_cast<uintptr_t>(manager))return false;
    using Getter=void*(*)();
    if(reinterpret_cast<Getter>(mp4_native_base+mp4_native_profile.get_manager.rva)()!=manager)return false;
    if(manager!=mp4_native_manager_cache){
        if(!mp4_native_manager_writable(reinterpret_cast<uintptr_t>(manager)))return false;
        mp4_native_manager_cache=manager;
    }
    const uintptr_t vtable=mp4_native_base+mp4_native_profile.manager_vtable;
    return read<uintptr_t>(manager,0)==vtable
        &&read<uintptr_t>(reinterpret_cast<void*>(vtable),0xc0)==mp4_native_base+mp4_native_profile.update.rva;
}
bool mp4_prepare_native_clock(uintptr_t base){
    mp4_native_clock_source_ready.store(false,std::memory_order_release);
    mp4_native_clock_error.store("native_clock_image_unverified",std::memory_order_release);mp4_native_segment_count=0;mp4_native_base=0;
    if(!base)return false;
#ifdef IDOLY_DARWIN_BRIDGE
    if(read<uint32_t>(reinterpret_cast<void*>(base),0)!=0xfeedfacf)return false;
    const uint32_t count=read<uint32_t>(reinterpret_cast<void*>(base),16),length=read<uint32_t>(reinterpret_cast<void*>(base),20);
    if(count>128||length>65536)return false;
    size_t offset=32;
    for(unsigned i=0;i<count;++i){
        if(offset+8>32+length)return false;
        const uint32_t command=read<uint32_t>(reinterpret_cast<void*>(base),offset),size=read<uint32_t>(reinterpret_cast<void*>(base),offset+4);
        if(size<8||offset+size>32+length)return false;
        if(command==0x19&&size>=72){
            const uintptr_t rva=read<uint64_t>(reinterpret_cast<void*>(base),offset+24),span=read<uint64_t>(reinterpret_cast<void*>(base),offset+32);
            const uint32_t protection=read<uint32_t>(reinterpret_cast<void*>(base),offset+60);
            if(mp4_native_segment_count==32||base+rva<base||base+rva+span<base+rva)return false;
            mp4_native_segments[mp4_native_segment_count++]={base+rva,span,((protection&1)?4u:0u)|(protection&2)|((protection&4)?1u:0u)};
        }
        offset+=size;
    }
    if(offset!=32+length)return false;
#else
    const auto* header=reinterpret_cast<const ElfW(Ehdr)*>(base);
    if(std::memcmp(header->e_ident,"\177ELF\2\1",6)||header->e_machine!=EM_AARCH64
        ||header->e_phnum>128||header->e_phentsize!=sizeof(ElfW(Phdr))||header->e_phoff>65536)return false;
    const auto* segments=reinterpret_cast<const ElfW(Phdr)*>(base+header->e_phoff);
    for(size_t i=0;i<header->e_phnum;++i){const auto& segment=segments[i];
        if(segment.p_type!=PT_LOAD)continue;
        if(mp4_native_segment_count==32||base+segment.p_vaddr<base
            ||base+segment.p_vaddr+segment.p_memsz<base+segment.p_vaddr)return false;
        mp4_native_segments[mp4_native_segment_count++]={base+segment.p_vaddr,segment.p_memsz,segment.p_flags};
    }
#endif
    const mp4clock::Binding* calls[]={&mp4_native_profile.get_manager,&mp4_native_profile.update,
        &mp4_native_profile.fixed_work,&mp4_native_profile.fixed_tick,&mp4_native_profile.fixed_cache_refresh,
        &mp4_native_profile.level_reset,&mp4_native_profile.realtime,&mp4_native_profile.monotonic_timestamp,
        &mp4_native_profile.application_fps_get,&mp4_native_profile.application_fps_set,
        &mp4_native_profile.quality_manager,&mp4_native_profile.vsync_set};
    for(const auto* call:calls){
        const uintptr_t address=base+call->rva;
        if(address<base||!mp4_native_mapped(address,16,5))return false;
#ifdef IDOLY_DARWIN_BRIDGE
        if(call==&mp4_native_profile.update){
            if(pin::mp4_native_time.rva!=call->rva||!pin::mp4_native_time.gateway||!pin::mp4_native_time.slot
                ||std::memcmp(pin::mp4_native_time.bytes,call->prefix,16))return false;
        }else
#endif
        if(std::memcmp(reinterpret_cast<void*>(address),call->prefix,16))return false;
    }
    if(!mp4_native_mapped(base+mp4_native_registry_getter,16,5)
        ||std::memcmp(reinterpret_cast<void*>(base+mp4_native_registry_getter),mp4_native_registry_prefix,16)
        ||!mp4_native_mapped(base+mp4_native_profile.registry_slot,8,6)
        ||!mp4_native_mapped(base+mp4_native_profile.manager_vtable,0xc8,4)
        ||read<uintptr_t>(reinterpret_cast<void*>(base+mp4_native_profile.manager_vtable),0xc0)!=base+mp4_native_profile.update.rva)return false;
    mp4_native_base=base;mp4_native_clock_error.store("none",std::memory_order_release);
    mp4_native_clock_source_ready.store(true,std::memory_order_release);return true;
}
bool mp4_install_native_clock_api(){
    if(!mp4_native_time_original||!mp4_native_clock_source_ready.load(std::memory_order_acquire))return false;
    if(!idoly_mp4_runtime::install_native_clock({mp4_native_current_manager,mp4_native_time_original})){
        mp4_native_clock_error.store("native_clock_runtime_install_failed",std::memory_order_release);return false;
    }
    return true;
}
// END_MP4_NATIVE_CLOCK_VALIDATION

// BEGIN_MP4_NATIVE_CLOCK_HOOKS
void mp4_native_time_hook(void* manager,double wall){
    if(!mp4_native_clock_source_ready.load(std::memory_order_acquire)||!game_call(true)
        ||!idoly_mp4_runtime::native_clock_available()){
        mp4_native_time_original(manager,wall);return;
    }
    const bool verified=mp4_native_current_manager(manager);
    if(!verified)mp4_native_clock_error.store("native_clock_manager_unverified",std::memory_order_release);
    else mp4_native_clock_error.store("none",std::memory_order_release);
    if(!mp4_native_clock_armed.load(std::memory_order_acquire)){
        if(!verified){mp4_native_time_original(manager,wall);return;}
        mp4_native_clock_armed.store(true,std::memory_order_release);
    }
    // Runtime owns the one native call, including false/error return paths.
    (void)idoly_mp4_runtime::native_clock_tick(manager,wall);
}
using Mp4BrainUpdate=void(*)(void*,Method*);
Mp4BrainUpdate mp4_brain_update_original=nullptr;
void mp4_brain_update_hook(void* brain,Method* method){
    mp4_brain_update_original(brain,method);
    if(ready.load(std::memory_order_acquire)&&game_call()&&mp4_api_installed)
        (void)idoly_mp4_runtime::game.original_camera_updated(brain);
}
// END_MP4_NATIVE_CLOCK_HOOKS

// BEGIN_MP4_SHADER_LEASE_HOST
using Mp4ShaderSet=void(*)(float,Method*);
using Mp4ShaderReset=void(*)(Method*);
Mp4ShaderSet mp4_shader_set_original=nullptr;
Mp4ShaderReset mp4_shader_reset_original=nullptr;
pthread_mutex_t mp4_shader_mutex=PTHREAD_MUTEX_INITIALIZER;
uint64_t mp4_shader_generation=1;
struct Mp4ShaderLease {void* context=nullptr;uint64_t generation=0;bool active=false,custom=false;float previous=0;} mp4_shader_lease;
struct Mp4ShaderLock {
    Mp4ShaderLock(){pthread_mutex_lock(&mp4_shader_mutex);}
    ~Mp4ShaderLock(){pthread_mutex_unlock(&mp4_shader_mutex);}
};
void mp4_shader_external_write(){
    if(mp4_shader_generation)mp4_shader_generation=mp4_shader_generation==~uint64_t(0)?0:mp4_shader_generation+1;
}
void mp4_shader_set_hook(float seconds,Method* method){
    // Both original setters contain only IL2CPP initialization and one static
    // float write. Their original .cctor also only initializes that float;
    // there is no callback/reentrant setter while this lock is held.
    Mp4ShaderLock lock;mp4_shader_external_write();mp4_shader_set_original(seconds,method);
}
void mp4_shader_reset_hook(Method* method){
    Mp4ShaderLock lock;mp4_shader_external_write();mp4_shader_reset_original(method);
}
bool mp4_shader_lease_begin(void* context){
    if(!context||!game_call()||!mp4_source_verified||!mp4_api_installed
        ||!mp4_shader_set_original||!mp4_shader_reset_original
        ||!mp4_api.shader_use_custom||!mp4_api.shader_current_time)return false;
    Mp4ShaderLock lock;
    if(mp4_shader_lease.active||!mp4_shader_generation)return false;
    const bool custom=mp4_api.shader_use_custom(nullptr);const float previous=mp4_api.shader_current_time(nullptr);
    if(!std::isfinite(previous))return false;
    mp4_shader_lease={context,mp4_shader_generation,true,custom,previous};return true;
}
bool mp4_shader_lease_set_time(void* context,float seconds){
    if(!std::isfinite(seconds)||seconds<0||seconds>900)return false;
    Mp4ShaderLock lock;
    if(!mp4_shader_lease.active||context!=mp4_shader_lease.context
        ||!mp4_shader_generation||mp4_shader_lease.generation!=mp4_shader_generation)return false;
    // Bypass our external-write hooks. Compare and raw apply are serialized
    // against every normal Set/Reset, including same-value external writes.
    mp4_shader_set_original(seconds,nullptr);return true;
}
void mp4_shader_lease_finish(void* context){
    Mp4ShaderLock lock;
    if(!mp4_shader_lease.active||context!=mp4_shader_lease.context)return;
    const auto saved=mp4_shader_lease;mp4_shader_lease={};
    if(saved.generation!=mp4_shader_generation||!mp4_shader_generation)return;
    // Global saved state only: safe after a selected MV was replaced. A new
    // external owner always wins, even if its value equals our last value.
    if(saved.custom)mp4_shader_set_original(saved.previous,nullptr);
    else mp4_shader_reset_original(nullptr);
}
[[maybe_unused]] idoly_mp4_playback::ShaderLeaseApi mp4_shader_lease_api(){
    return {mp4_shader_lease_begin,mp4_shader_lease_set_time,mp4_shader_lease_finish};
}
// END_MP4_SHADER_LEASE_HOST

#ifndef IDOLY_DARWIN_BRIDGE
// BEGIN_MP4_MANAGED_HOOK_RECEIPTS
struct Mp4ManagedHookReceipt {
    uintptr_t base=0,rva=0;unsigned char original_prefix[16]{},patched_prefix[16]{};
    void* stub=nullptr;void* trampoline=nullptr;void** original_location=nullptr;
};
Mp4ManagedHookReceipt mp4_managed_hook_receipts[128]{};size_t mp4_managed_hook_count=0;
std::atomic<bool> mp4_managed_hook_receipts_ready{false};
bool mp4_record_managed_hook(const pin::Entry* entry,void* stub,void** original){
    if(!entry||!stub||!original||!*original||mp4_managed_hook_count==128
        ||!mp4_mapped(image_base+entry->rva,16,true))return false;
    auto& receipt=mp4_managed_hook_receipts[mp4_managed_hook_count++];
    receipt.base=image_base;receipt.rva=entry->rva;receipt.stub=stub;receipt.trampoline=*original;receipt.original_location=original;
    std::memcpy(receipt.original_prefix,entry->bytes,16);
    std::memcpy(receipt.patched_prefix,reinterpret_cast<void*>(image_base+entry->rva),16);return true;
}
bool mp4_managed_hook_verified(const mp4game::Binding& binding){
    if(!mp4_managed_hook_receipts_ready.load(std::memory_order_acquire))return false;
    for(size_t i=0;i<mp4_managed_hook_count;++i){const auto& receipt=mp4_managed_hook_receipts[i];
        if(receipt.rva!=binding.rva)continue;
        return receipt.base==image_base&&receipt.stub&&receipt.original_location
            &&*receipt.original_location==receipt.trampoline&&receipt.trampoline
            &&!std::memcmp(receipt.original_prefix,binding.prefix,16)
            &&mp4_mapped(image_base+binding.rva,16,true)
            &&!std::memcmp(reinterpret_cast<void*>(image_base+binding.rva),receipt.patched_prefix,16);
    }
    return false;
}
// END_MP4_MANAGED_HOOK_RECEIPTS
#endif

bool mp4_hook_was_statically_verified(const mp4game::Binding &binding) {
#ifdef IDOLY_DARWIN_BRIDGE
    // verify_static_image checked all patched entry branches and gateways before
    // load_calls. The independent typed profile must attest the SAME originals.
    const pin::Entry *entry=nullptr;
    if(binding.rva==pin::mp4_presenter_update.rva)entry=&pin::mp4_presenter_update;
    else if(binding.rva==pin::mp4_player_initialize.rva)entry=&pin::mp4_player_initialize;
    else if(binding.rva==pin::mp4_photography_initialize.rva)entry=&pin::mp4_photography_initialize;
    else if(binding.rva==pin::mp4_photography_player_initialize.rva)entry=&pin::mp4_photography_player_initialize;
    else if(binding.rva==pin::mp4_photography_end.rva)entry=&pin::mp4_photography_end;
    else if(binding.rva==pin::mp4_capture_pass.rva)entry=&pin::mp4_capture_pass;
    else if(binding.rva==pin::mp4_end_camera.rva)entry=&pin::mp4_end_camera;
    else if(binding.rva==pin::mp4_graph_mode.rva)entry=&pin::mp4_graph_mode;
    else if(binding.rva==pin::mp4_brain_delta.rva)entry=&pin::mp4_brain_delta;
    else if(binding.rva==pin::mp4_brain_update.rva)entry=&pin::mp4_brain_update;
    else if(binding.rva==pin::mp4_shader_set.rva)entry=&pin::mp4_shader_set;
    else if(binding.rva==pin::mp4_shader_reset.rva)entry=&pin::mp4_shader_reset;
    else if(binding.rva==pin::mp4_actor_process.rva)entry=&pin::mp4_actor_process;
    else if(binding.rva==pin::mp4_actor_burst.rva)entry=&pin::mp4_actor_burst;
    else if(binding.rva==pin::mp4_core_camera.rva)entry=&pin::mp4_core_camera;
    return entry&&entry->gateway&&entry->slot&&!std::memcmp(entry->bytes,binding.prefix,16);
#else
    return mp4_managed_hook_verified(binding);
#endif
}
void mp4_verify_original_calls() {
    mp4_source_verified=false;mp4_replay_verified=false;
    auto fail=[](const char* group,uintptr_t rva){
        snprintf(mp4_binding_error,sizeof(mp4_binding_error),"%s_%llx",group,static_cast<unsigned long long>(rva));
        return false;
    };
    auto code=[&](const mp4game::Binding& binding){
        return mp4_prefix(binding)||mp4_hook_was_statically_verified(binding)
            ||fail("original_mv_code_prefix",binding.rva);
    };
    auto descriptor=[&](const auto& binding){
        const uintptr_t address=image_base+binding.rva;
        return (address>=image_base&&mp4_mapped(address,16,false)
                &&mp4game::type_descriptor_shape(binding,reinterpret_cast<const void*>(address)))
            ||fail("original_mv_type_shape",binding.rva);
    };
    for(const auto &binding:mp4_bindings)if(!code(binding))return;
    const auto &runtime=mp4_runtime_profile;
    for(const auto* binding:{&runtime.camera_status_try_get,&runtime.array_new,&runtime.string_new,&runtime.type_get_object})
        if(!code(*binding))return;
    // GlobalMetadata.Initialize rewrites every selected descriptor's data
    // index into a metadata-row pointer. Only its immutable tail is attested
    // on the installer thread. Exact resolved-row and class identity checks
    // run below on the original Unity thread before any API is installed.
    for(const auto* binding:{&runtime.single_type,&runtime.audio_clip_type,&runtime.texture2d_type})
        if(!descriptor(*binding))return;
    if(!code(mp4_camera_owner_profile.component_get_component)
        ||!descriptor(mp4_camera_owner_profile.controller_type))return;
    const auto& metadata=mp4_type_metadata_profile;
    if(!mp4_mapped(image_base+metadata.metadata_base_slot,sizeof(void*),false)
            ||!mp4_mapped(image_base+metadata.metadata_header_slot,sizeof(void*),false)){
        (void)fail("original_mv_metadata_slots",metadata.metadata_base_slot);return;
    }
    const auto& locator=mp4_controller_profile;
    if(!code(locator.has_instance)||!code(locator.instance)||!code(locator.metadata_initialize))return;
    for(uintptr_t rva:{locator.has_cell,locator.instance_cell,locator.has_slot,locator.instance_slot})
        if(!mp4_mapped(image_base+rva,sizeof(void*),false)){(void)fail("original_mv_controller_slot",rva);return;}
    if(locator.indirect_slots
            &&(read<uintptr_t>(reinterpret_cast<void*>(image_base+locator.has_slot),0)!=image_base+locator.has_cell
                ||read<uintptr_t>(reinterpret_cast<void*>(image_base+locator.instance_slot),0)!=image_base+locator.instance_cell)){
        (void)fail("original_mv_controller_link",locator.has_slot);return;
    }
    mp4_array_new=reinterpret_cast<decltype(mp4_array_new)>(image_base+runtime.array_new.rva);
    mp4_string_new=reinterpret_cast<decltype(mp4_string_new)>(image_base+runtime.string_new.rva);
    mp4_type_get_object=reinterpret_cast<decltype(mp4_type_get_object)>(image_base+runtime.type_get_object.rva);
    mp4_source_verified=true;
    snprintf(mp4_binding_error,sizeof(mp4_binding_error),"%s","none");
    mp4_replay_verified=true;
    for(const auto& binding:mp4_replay_bindings){
        const bool data=binding.rva==mp4_replay_profile.actor_descriptor_type.rva
            ||binding.rva==mp4_replay_profile.out_game_param_type.rva||binding.rva==mp4_replay_profile.transition_param_type.rva;
        if(data){if(!descriptor(binding))mp4_replay_verified=false;}
        else {
            const uintptr_t address=image_base+binding.rva;
            if(address<image_base||!mp4_mapped(address,16,true)
                    ||std::memcmp(reinterpret_cast<const void*>(address),binding.prefix,16)){
                (void)fail("original_mv_replay_code_prefix",binding.rva);mp4_replay_verified=false;
            }
        }
    }
}

void mp4_verify_photography_calls(){
    mp4_photography_verified=false;
    if(!mp4_source_verified||!mp4_replay_verified)return;
    for(const auto& binding:mp4_photography_code_bindings)if(!mp4_prefix(binding)){
        snprintf(mp4_photography_binding_error,sizeof(mp4_photography_binding_error),"photography_code_prefix_%llx",static_cast<unsigned long long>(binding.rva));return;
    }
    for(const auto& binding:mp4_photography_type_bindings){
        const uintptr_t address=image_base+binding.rva;
        if(address<image_base||!mp4_mapped(address,16,false)||!mp4game::type_descriptor_shape(binding,reinterpret_cast<const void*>(address))){
            snprintf(mp4_photography_binding_error,sizeof(mp4_photography_binding_error),"photography_type_shape_%llx",static_cast<unsigned long long>(binding.rva));return;
        }
    }
    mp4_photography_verified=true;
    snprintf(mp4_photography_binding_error,sizeof(mp4_photography_binding_error),"%s","none");
}

bool mp4_type_is(void *object,const char *qualified) {
    if(!object||!qualified)return false;
    const char *name=qualified;const char *separator=nullptr;
    for(const char *p=qualified;*p;++p)if(*p=='.')separator=p;
    char space[192]{};
    if(separator){
        const size_t bytes=static_cast<size_t>(separator-qualified);if(bytes>=sizeof space)return false;
        std::memcpy(space,qualified,bytes);name=separator+1;
    }
    return *name&&class_matches(object,space,name);
}
bool mp4_exact_type(void* object,const char* qualified){
    if(!object||!qualified)return false;
    const char* name=qualified;const char* separator=nullptr;
    for(const char* p=qualified;*p;++p)if(*p=='.')separator=p;
    char space[192]{};
    if(separator){const size_t bytes=static_cast<size_t>(separator-qualified);if(bytes>=sizeof space)return false;
        std::memcpy(space,qualified,bytes);name=separator+1;}
    void* klass=object_class(object);const char* actual_name=klass?class_name(klass):nullptr;
    const char* actual_space=klass?class_namespace(klass):nullptr;
    return *name&&actual_name&&actual_space&&!std::strcmp(actual_name,name)&&!std::strcmp(actual_space,space);
}

bool mp4_alive(void *object) { return object&&object_alive(object,nullptr); }
struct Mp4MetadataRange {uintptr_t base=0;uint32_t offset=0,bytes=0;};
Mp4MetadataRange mp4_metadata_readable;
template<class BindingType>
void* mp4_resolved_type_class(const BindingType& binding,const char* space,const char* name){
    auto fail=[&](const char* group){
        snprintf(mp4_binding_error,sizeof(mp4_binding_error),"%s_%llx",group,static_cast<unsigned long long>(binding.rva));
        return static_cast<void*>(nullptr);
    };
    if(!mp4_source_verified||!game_call())return fail("original_mv_type_thread");
    const auto& profile=mp4_type_metadata_profile;
    void* base=read<void*>(reinterpret_cast<void*>(image_base+profile.metadata_base_slot),0);
    void* header=read<void*>(reinterpret_cast<void*>(image_base+profile.metadata_header_slot),0);
    // Both originals publish this same mapped metadata image as base/header.
    if(!base||base!=header||(reinterpret_cast<uintptr_t>(base)&3))return fail("original_mv_metadata_not_ready");
    const uintptr_t first=reinterpret_cast<uintptr_t>(base);
    if(mp4_metadata_readable.base!=first&&!mp4_readable_memory(first,0xa8))return fail("original_mv_metadata_unreadable");
    const uint32_t offset=read<uint32_t>(header,0xa0),bytes=read<uint32_t>(header,0xa4);
    if(!mp4game::type_metadata_layout(profile,read<uint32_t>(header,0),read<uint32_t>(header,4),offset,bytes))
        return fail("original_mv_metadata_layout");
    const uintptr_t definitions=first+offset;
    if(definitions<first||definitions+bytes<definitions)return fail("original_mv_metadata_layout");
    if(mp4_metadata_readable.base!=first||mp4_metadata_readable.offset!=offset||mp4_metadata_readable.bytes!=bytes){
        if(!mp4_readable_memory(first,0xa8)||!mp4_readable_memory(definitions,bytes))return fail("original_mv_metadata_unreadable");
        mp4_metadata_readable={first,offset,bytes};
    }
    const uintptr_t address=image_base+binding.rva;
    if(address<image_base
            ||!mp4_mapped(address,16,false)
            ||!mp4game::resolved_type_descriptor(binding,reinterpret_cast<const void*>(address),definitions,bytes))
        return fail("original_mv_type_row");
    void* klass=font_class_type(reinterpret_cast<const void*>(address));
    const char* actual_name=klass?class_name(klass):nullptr;
    const char* actual_space=klass?class_namespace(klass):nullptr;
    if(!actual_name||!actual_space||std::strcmp(actual_name,name)||std::strcmp(actual_space,space))
        return fail("original_mv_type_identity");
    return klass;
}
void* mp4_original_current_controller(){
    if(!mp4_source_verified||!game_call())return nullptr;
    const auto& locator=mp4_controller_profile;
    using Initialize=void(*)(uintptr_t*);
    using HasInstance=bool(*)(const Method*);
    using Instance=void*(*)(const Method*);
    auto initialize=reinterpret_cast<Initialize>(image_base+locator.metadata_initialize.rva);
    auto* has_cell=reinterpret_cast<uintptr_t*>(image_base+locator.has_cell);
    auto* instance_cell=reinterpret_cast<uintptr_t*>(image_base+locator.instance_cell);
    initialize(has_cell);initialize(instance_cell);
    const uintptr_t has_info=*has_cell,instance_info=*instance_cell;
    // The encoded metadata-usage form is tagged. It may never be passed as a
    // MethodInfo pointer if original metadata initialization did not resolve it.
    if(!has_info||!instance_info||(has_info&1)||(instance_info&1))return nullptr;
    if(!reinterpret_cast<HasInstance>(image_base+locator.has_instance.rva)(reinterpret_cast<const Method*>(has_info)))return nullptr;
    void* controller=reinterpret_cast<Instance>(image_base+locator.instance.rva)(reinterpret_cast<const Method*>(instance_info));
    return mp4_type_is(controller,"VL.Rendering.VLSRPCameraController")&&mp4_alive(controller)?controller:nullptr;
}
uint32_t mp4_retain(void *object) { return object?font_strong(object,false):0; }
size_t mp4_array_length(void *array) { return array?read<uintptr_t>(array,0x18):0; }
void *mp4_array_data(void *array) { return array?static_cast<unsigned char*>(array)+0x20:nullptr; }
// BEGIN_MP4_ACTOR_HOST
namespace mp4actor=idoly_mp4_actor;
#ifdef IDOLY_DARWIN_BRIDGE
constexpr const auto& mp4_actor_profile=mp4actor::ios_actor_profile;
#else
constexpr const auto& mp4_actor_profile=mp4actor::android_actor_profile;
#endif
mp4actor::WorkerGate mp4_actor_gate;
mp4actor::ManagedProcess mp4_actor_process_original=nullptr;
mp4actor::BurstExecute mp4_actor_burst_original=nullptr;
std::atomic<bool> mp4_actor_managed_installed{false},mp4_actor_burst_installed{false};
std::atomic<const char*> mp4_actor_route_error{"actor_worker_routes_not_installed"};
bool mp4_actor_source_verified=false;
uint32_t mp4_actor_job_type_handle=0,mp4_actor_transform_type_handle=0;
struct Mp4ActorRange {uintptr_t begin=0,end=0;unsigned protection=0;};
Mp4ActorRange mp4_actor_ranges[4096]{};size_t mp4_actor_range_count=0;
struct Mp4ActorHost {
    mp4actor::Scope scope;mp4actor::Owner owners[32]{};size_t count=0;
    void* player=nullptr;void* presenter=nullptr;void* director=nullptr;
    uint32_t roots[3]{};uint64_t epoch=0;bool invalidated=false;
    const char* error="actor_host_not_configured";
} mp4_actor_host;
bool mp4_actor_graph_mode(mp4actor::Handle*,int32_t*);
bool mp4_actor_map_add(uintptr_t begin,uintptr_t end,unsigned protection){
    if(begin>=end)return false;
    if(mp4_actor_range_count){auto& last=mp4_actor_ranges[mp4_actor_range_count-1];
        if(begin<last.end)return false;
        if(begin==last.end&&last.protection==protection){last.end=end;return true;}}
    if(mp4_actor_range_count==4096)return false;
    mp4_actor_ranges[mp4_actor_range_count++]={begin,end,protection};return true;
}
bool mp4_actor_refresh_maps(){
    if(!game_call())return false;
    mp4_actor_range_count=0;
#ifdef IDOLY_DARWIN_BRIDGE
    uint64_t cursor=0;
    for(unsigned i=0;i<16384;++i){
        uint64_t begin=cursor,span=0;int info[16]{};unsigned count=16,object=0;
        const int result=mach_vm_region(mach_task_self_,&begin,&span,9,info,&count,&object);
        if(object)(void)mach_port_deallocate(mach_task_self_,object);
        if(result)return result==1&&mp4_actor_range_count;
        if(!count||!span||begin<cursor||begin+span<begin||!mp4_actor_map_add(begin,begin+span,static_cast<unsigned>(info[0])&3))return false;
        cursor=begin+span;
    }
    return false;
#else
    FILE* maps=fopen("/proc/self/maps","r");if(!maps)return false;
    char line[512]{};unsigned count=0;bool ok=true;
    while(count++<16384&&fgets(line,sizeof(line),maps)){
        unsigned long long begin=0,end=0;char permissions[5]{};
        if(sscanf(line,"%llx-%llx %4s",&begin,&end,permissions)!=3)continue;
        if(!mp4_actor_map_add(static_cast<uintptr_t>(begin),static_cast<uintptr_t>(end),
            (permissions[0]=='r'?1u:0u)|(permissions[1]=='w'?2u:0u))){ok=false;break;}
    }
    const bool finished=feof(maps);fclose(maps);return ok&&finished&&mp4_actor_range_count;
#endif
}
bool mp4_actor_mapped(const void* value,size_t bytes,bool writable){
    if(!game_call()||!value||!bytes||bytes>64*1024*1024)return false;
    const uintptr_t address=reinterpret_cast<uintptr_t>(value),end=address+bytes;if(end<address)return false;
    size_t low=0,high=mp4_actor_range_count;
    while(low<high){const size_t mid=low+(high-low)/2;if(mp4_actor_ranges[mid].begin<=address)low=mid+1;else high=mid;}
    if(!low)return false;
    const auto& range=mp4_actor_ranges[low-1];
    return end<=range.end&&(range.protection&(writable?3u:1u))==(writable?3u:1u);
}
template<class T> bool mp4_actor_field(void* object,size_t offset,T& result){
    if(!object||reinterpret_cast<uintptr_t>(object)+offset<reinterpret_cast<uintptr_t>(object)
        ||!mp4_actor_mapped(static_cast<unsigned char*>(object)+offset,sizeof(T),false))return false;
    std::memcpy(&result,static_cast<unsigned char*>(object)+offset,sizeof(T));return true;
}
bool mp4_actor_list(void* list,void*** values,size_t* count,size_t limit){
    if(!mp4_type_is(list,"System.Collections.Generic.List`1"))return false;
    void* array=nullptr;int32_t length=0;
    if(!mp4_actor_field(list,0x10,array)||!mp4_actor_field(list,0x18,length)||length<0||static_cast<size_t>(length)>limit
        ||!array||!mp4_type_is(array,"System.Array")||mp4_array_length(array)<static_cast<size_t>(length)
        ||(length&&!mp4_actor_mapped(mp4_array_data(array),static_cast<size_t>(length)*sizeof(void*),false)))return false;
    *values=static_cast<void**>(mp4_array_data(array));*count=static_cast<size_t>(length);return true;
}
bool mp4_actor_selected_source(void*){
    if(!game_call()||!mp4_api_installed||!mp4_actor_source_verified)return false;
    auto& host=mp4_actor_host;auto& game=idoly_mp4_runtime::game;
    if(host.epoch&&(host.invalidated||host.epoch!=game.owned_scene_generation()))return false;
    void* player=game.selected_player();void* presenter=game.selected_presenter();
    return player&&presenter&&(!host.epoch||(host.player==player&&host.presenter==presenter));
}
bool mp4_actor_owner(void*,const mp4actor::Owner& owner){
    if(!mp4_actor_selected_source(nullptr))return false;
    const auto& f=mp4_actor_profile.fields;auto& host=mp4_actor_host;
    void* binder=nullptr;void* actors=nullptr;void** values=nullptr;size_t count=0;
    if(!mp4_actor_field(host.player,mp4game::Layout{}.player_binder,binder)
        ||!mp4_type_is(binder,"Solis.Common.Live.SolisLiveBinder")
        ||!mp4_actor_field(binder,mp4game::Layout{}.binder_actors,actors)||!mp4_actor_list(actors,&values,&count,32))return false;
    bool member=false;for(size_t i=0;i<count;++i)member|=values[i]==owner.actor;if(!member)return false;
    void* animation=nullptr;void* animator=nullptr;void* extensions=nullptr;
    if(!mp4_actor_field(owner.actor,f.actor_player,animation)||!mp4_type_is(animation,"VL.VLAnimationClipPlayer")
        ||!mp4_actor_field(owner.actor,f.actor_animator,animator)||animator!=owner.animator
        ||!mp4_actor_field(owner.actor,f.actor_extensions,extensions)||!mp4_actor_list(extensions,&values,&count,64))return false;
    member=false;for(size_t i=0;i<count;++i)member|=values[i]==owner.extension;if(!member)return false;
    void* value=nullptr;mp4actor::Handle graph{},playable{},output{};
    return mp4_actor_field(owner.extension,f.extension_player,value)&&value==animation
        &&mp4_actor_field(owner.extension,f.extension_rig,value)&&value==owner.rig
        &&mp4_actor_field(owner.extension,f.extension_builder,value)&&value==owner.builder
        &&mp4_actor_field(owner.builder,f.builder_rig,value)&&value==owner.rig
        &&mp4_actor_field(animation,f.player_animator,value)&&value==owner.animator
        &&mp4_actor_field(animation,f.player_graph,graph)&&graph.handle==owner.graph.handle&&graph.version==owner.graph.version
        &&mp4_actor_field(owner.builder,f.builder_playable,playable)&&playable.handle==owner.playable.handle&&playable.version==owner.playable.version
        &&mp4_actor_field(owner.builder,f.builder_output,output)&&output.handle==owner.output.handle&&output.version==owner.output.version;
}
bool mp4_actor_clock_held(void*){return game_call()&&idoly_mp4_runtime::native_clock_scope().held();}
bool mp4_actor_routes(void*){return mp4_actor_source_verified
    &&mp4_actor_job_type_handle&&mp4_actor_transform_type_handle
    &&mp4_actor_managed_installed.load(std::memory_order_acquire)&&mp4_actor_burst_installed.load(std::memory_order_acquire);}
double mp4_actor_root_time(void*){
    if(!mp4_actor_selected_source(nullptr)||!mp4_actor_host.director)return -1;
    return mp4_api.director_get_time(mp4_actor_host.director,nullptr);
}
mp4actor::Result mp4_actor_zero_pose(void*){
    if(!mp4_actor_selected_source(nullptr)||!mp4_actor_host.director)return mp4actor::Result::stale;
    if(!mp4_actor_clock_held(nullptr))return mp4actor::Result::waiting;
    mp4_api.director_set_time(mp4_actor_host.director,0,nullptr);
    if(!mp4_actor_selected_source(nullptr))return mp4actor::Result::stale;
    mp4_api.director_evaluate(mp4_actor_host.director,nullptr);
    if(!mp4_actor_selected_source(nullptr))return mp4actor::Result::stale;
    const double time=mp4_actor_root_time(nullptr);
    return std::isfinite(time)&&std::fabs(time)<=.0001?mp4actor::Result::ok:mp4actor::Result::failed;
}
bool mp4_actor_job_type(void* type){return type&&mp4_actor_job_type_handle&&type==weak_get(mp4_actor_job_type_handle);}
void* mp4_actor_transforms(void* actor){
    if(!mp4_actor_source_verified||!game_call()||!mp4_actor_transform_type_handle)return nullptr;
    using GetObject=void*(*)(void*,Method*);using GetComponents=void*(*)(void*,void*,bool,bool,bool,bool,void*,Method*);
    void* object=reinterpret_cast<GetObject>(image_base+mp4_actor_profile.get_game_object.rva)(actor,nullptr);
    if(!mp4_type_is(object,"UnityEngine.GameObject")||!mp4_alive(object))return nullptr;
    void* array=reinterpret_cast<GetComponents>(image_base+mp4_actor_profile.get_components_internal.rva)(object,
        weak_get(mp4_actor_transform_type_handle),true,true,true,false,nullptr,nullptr);
    return mp4_type_is(array,"UnityEngine.Transform[]")?array:nullptr;
}
void mp4_actor_graph_set(mp4actor::Handle* graph,int32_t mode,mp4actor::Method* method){
    using Setter=void(*)(mp4actor::Handle*,int32_t,mp4actor::Method*);
    reinterpret_cast<Setter>(image_base+mp4_profile.graph_set_mode_injected.rva)(graph,mode,method);
}
mp4actor::StateApi mp4_actor_state_api(){
    mp4actor::StateApi api{};api.source_current=mp4_actor_owner;api.clock_held=mp4_actor_clock_held;api.routes_ready=mp4_actor_routes;
    api.prepare_zero_pose=mp4_actor_zero_pose;api.root_time=mp4_actor_root_time;api.mapped=mp4_actor_mapped;api.is_type=mp4_type_is;api.alive=mp4_alive;
    api.gc_new=font_strong;api.gc_target=weak_get;api.gc_free=weak_free;api.job_type_is_actor=mp4_actor_job_type;
    api.actor_transforms=mp4_actor_transforms;api.array_length=mp4_array_length;api.array_data=mp4_array_data;
#define MP4_ACTOR_CALL(target,name) api.target=reinterpret_cast<decltype(api.target)>(image_base+mp4_actor_profile.name.rva)
    MP4_ACTOR_CALL(output_target,output_target);MP4_ACTOR_CALL(job_type,get_job_type);MP4_ACTOR_CALL(job_data,get_job_data);
    MP4_ACTOR_CALL(animator_mode,animator_mode_get);MP4_ACTOR_CALL(animator_culling,animator_culling_get);MP4_ACTOR_CALL(job_complete,complete);
    MP4_ACTOR_CALL(rig_reset_dynamic,reset_dynamic);MP4_ACTOR_CALL(rig_reset_breast,reset_breast);
    MP4_ACTOR_CALL(graph_root_count,graph_root_count);MP4_ACTOR_CALL(graph_root,graph_root);MP4_ACTOR_CALL(playable_valid,playable_valid);
    MP4_ACTOR_CALL(playable_input_count,playable_input_count);MP4_ACTOR_CALL(playable_input,playable_input);MP4_ACTOR_CALL(playable_time,playable_time);
    MP4_ACTOR_CALL(root_transform,root_transform);MP4_ACTOR_CALL(transform_parent,parent);MP4_ACTOR_CALL(local_position,local_position);
    MP4_ACTOR_CALL(local_rotation,local_rotation);MP4_ACTOR_CALL(local_scale,local_scale);
    MP4_ACTOR_CALL(set_local_position_rotation,set_local_position_rotation);MP4_ACTOR_CALL(set_local_scale,set_local_scale);
#undef MP4_ACTOR_CALL
    api.graph_valid=reinterpret_cast<decltype(api.graph_valid)>(image_base+mp4_profile.graph_valid.rva);
    api.graph_mode=mp4_actor_graph_mode;api.graph_set_mode=mp4_actor_graph_set;
    api.graph_evaluate=reinterpret_cast<decltype(api.graph_evaluate)>(image_base+mp4_profile.graph_evaluate_injected.rva);return api;
}
void mp4_actor_drop_context(){
    for(auto& root:mp4_actor_host.roots){if(root)weak_free(root);root=0;}
    mp4_actor_host.player=mp4_actor_host.presenter=mp4_actor_host.director=nullptr;
    mp4_actor_host.epoch=0;mp4_actor_host.count=0;mp4_actor_host.invalidated=false;
}
bool mp4_actor_configure_context(){
    auto& host=mp4_actor_host;if(host.scope.active())return true;
    if(!mp4_actor_selected_source(nullptr)||!mp4_actor_routes(nullptr)||!mp4_actor_refresh_maps())return false;
    host.player=idoly_mp4_runtime::game.selected_player();host.presenter=idoly_mp4_runtime::game.selected_presenter();
    host.epoch=idoly_mp4_runtime::game.owned_scene_generation();host.invalidated=false;
    void* controller=nullptr;void* binder=nullptr;void* list=nullptr;void** actors=nullptr;size_t count=0;
    if(!mp4_actor_field(host.player,mp4game::Layout{}.player_director_controller,controller)
        ||!mp4_actor_field(controller,mp4game::Layout{}.controller_master,host.director)
        ||!mp4_actor_field(host.player,mp4game::Layout{}.player_binder,binder)
        ||!mp4_type_is(binder,"Solis.Common.Live.SolisLiveBinder")
        ||!mp4_actor_field(binder,mp4game::Layout{}.binder_actors,list)||!mp4_actor_list(list,&actors,&count,32)||!count)return false;
    for(size_t i=0;i<3;++i){void* value=i==0?host.player:i==1?host.presenter:host.director;
        if(!host.roots[i])host.roots[i]=mp4_retain(value);if(!host.roots[i]||weak_get(host.roots[i])!=value)return false;}
    const auto& f=mp4_actor_profile.fields;host.count=0;
    for(size_t i=0;i<count;++i){
        void* actor=actors[i];if(!mp4_type_is(actor,"VL.Core.VLActorController")||!mp4_alive(actor))return false;
        void* extensions=nullptr;void** values=nullptr;size_t length=0;
        if(!mp4_actor_field(actor,f.actor_extensions,extensions)||!mp4_actor_list(extensions,&values,&length,64))return false;
        mp4actor::Owner owner{};owner.actor=actor;
        for(size_t j=0;j<length;++j)if(mp4_type_is(values[j],"VL.VLActorActorSwing")){
            if(owner.extension)return false;owner.extension=values[j];}
        if(!owner.extension||!mp4_actor_field(owner.extension,f.extension_rig,owner.rig)
            ||!mp4_actor_field(owner.extension,f.extension_builder,owner.builder)
            ||!mp4_actor_field(actor,f.actor_animator,owner.animator)
            ||!mp4_actor_field(owner.builder,f.builder_playable,owner.playable)
            ||!mp4_actor_field(owner.builder,f.builder_output,owner.output))return false;
        void* animation=nullptr;if(!mp4_actor_field(actor,f.actor_player,animation)||!mp4_actor_field(animation,f.player_graph,owner.graph))return false;
        if(!mp4_actor_owner(nullptr,owner))return false;host.owners[host.count++]=owner;
    }
    if(!host.scope.configure(mp4_actor_state_api(),&mp4_actor_gate,host.owners,host.count,&host,host.epoch))return false;
    host.error="none";return true;
}
mp4actor::Result mp4_actor_quiesce(void*){
    if(!mp4_actor_configure_context()){
        mp4_actor_host.error="actor_host_source_not_ready";return mp4actor::Result::unsupported;}
    return mp4_actor_host.scope.quiesce();
}
mp4actor::Result mp4_actor_capture(void*){return mp4_actor_host.scope.capture();}
mp4actor::Result mp4_actor_prepare(void*){return mp4_actor_host.scope.prepare();}
mp4actor::Result mp4_actor_reset(void*){return mp4_actor_host.scope.reset();}
mp4actor::Result mp4_actor_restore(void*){return mp4_actor_host.scope.restore();}
mp4actor::Result mp4_actor_release(void*,bool owned){
    const auto result=mp4_actor_host.scope.release(owned);
    if(!mp4_actor_host.scope.active())mp4_actor_drop_context();return result;
}
const char* mp4_actor_error(void*){return mp4_actor_host.scope.active()?mp4_actor_host.scope.error():mp4_actor_host.error;}
[[maybe_unused]] mp4actor::Result mp4_actor_hold(void*){return mp4_actor_host.scope.hold_frame();}
[[maybe_unused]] mp4actor::Result mp4_actor_grant(void*,uint64_t simulation_tick){
    if(simulation_tick==~uint64_t(0))return mp4actor::Result::invalid;
    return mp4_actor_host.scope.grant(simulation_tick+1);
}
[[maybe_unused]] idoly_mp4_playback::Dependents mp4_actor_dependents(){
    return {mp4_actor_selected_source,mp4_actor_quiesce,mp4_actor_capture,mp4_actor_prepare,
        mp4_actor_reset,mp4_actor_restore,mp4_actor_release,mp4_actor_error};
}
[[maybe_unused]] void* mp4_actor_context(){return &mp4_actor_host;}
void mp4_actor_scene_will_change(void* value){
    // Called before original Initialize/End. No managed access, VM query or
    // Unity call is permitted at this lifecycle boundary.
    auto& host=mp4_actor_host;
    if(!host.epoch||!value||(value!=host.player&&value!=host.presenter))return;
    host.invalidated=true;(void)mp4_actor_gate.detach_stale(host.epoch);
}
void mp4_actor_process_hook(void* job,const void* stream,const void* method){
    mp4_actor_gate.invoke_managed(mp4_actor_process_original,job,stream,method);
}
void mp4_actor_burst_hook(void* job,const void* stream,intptr_t tag,void* ranges,int32_t index){
    mp4_actor_gate.invoke_burst(mp4_actor_burst_original,job,stream,tag,ranges,index);
}
bool mp4_actor_graph_mode(mp4actor::Handle* handle,int32_t* result){
    if(!handle||!result||!game_call()||!mp4_actor_source_verified)return false;
    using Valid=bool(*)(mp4actor::Handle*,mp4actor::Method*);
    if(!reinterpret_cast<Valid>(image_base+mp4_profile.graph_valid.rva)(handle,nullptr))return false;
    // Exact original native SetTimeUpdateMode dispatch validates this same
    // node and follows node+0x28 -> native graph+0x18. No getter/default is
    // invented, and querying the current mode never writes the graph.
    const auto& native=mp4_actor_profile.native_graph;
    if(!mp4_actor_mapped(reinterpret_cast<void*>(handle->handle),native.node_graph+sizeof(uintptr_t),false))return false;
    const uintptr_t graph=read<uintptr_t>(reinterpret_cast<void*>(handle->handle),native.node_graph);
    if(!graph||graph+native.graph_mode<graph
        ||!mp4_actor_mapped(reinterpret_cast<void*>(graph+native.graph_mode),sizeof(int32_t),false))return false;
    const int32_t mode=read<int32_t>(reinterpret_cast<void*>(graph),native.graph_mode);
    if(mode<0||mode>3)return false;
    *result=mode;return true;
}
void mp4_verify_actor_calls(){
    mp4_actor_source_verified=false;
    if(!mp4_source_verified||!mp4_native_clock_source_ready.load(std::memory_order_acquire))return;
    const mp4actor::ActorBinding* calls[]={&mp4_actor_profile.get_job_data,&mp4_actor_profile.get_job_type,
        &mp4_actor_profile.output_target,&mp4_actor_profile.complete,&mp4_actor_profile.reset_dynamic,&mp4_actor_profile.reset_breast,
        &mp4_actor_profile.animator_mode_get,&mp4_actor_profile.animator_mode_set,&mp4_actor_profile.animator_culling_get,
        &mp4_actor_profile.animator_culling_set,&mp4_actor_profile.graph_root_count,&mp4_actor_profile.graph_root,
        &mp4_actor_profile.playable_valid,&mp4_actor_profile.playable_time,&mp4_actor_profile.playable_input_count,
        &mp4_actor_profile.playable_input,&mp4_actor_profile.root_transform,&mp4_actor_profile.get_game_object,
        &mp4_actor_profile.get_components_internal,&mp4_actor_profile.parent,&mp4_actor_profile.local_position,
        &mp4_actor_profile.local_rotation,&mp4_actor_profile.local_scale,&mp4_actor_profile.set_local_position_rotation,
        &mp4_actor_profile.set_local_scale,&mp4_actor_profile.managed_process};
    for(const auto* call:calls){mp4game::Binding binding{};binding.rva=call->rva;std::memcpy(binding.prefix,call->prefix,16);
        if(!mp4_prefix(binding)&&!mp4_hook_was_statically_verified(binding))return;}
#ifdef IDOLY_DARWIN_BRIDGE
    mp4game::Binding burst{};burst.rva=mp4_actor_profile.burst_execute.rva;std::memcpy(burst.prefix,mp4_actor_profile.burst_execute.prefix,16);
    if(!mp4_prefix(burst)&&!mp4_hook_was_statically_verified(burst))return;
#endif
    for(const auto* type:{&mp4_actor_profile.actor_job_type,&mp4_actor_profile.transform_type}){
        const uintptr_t address=image_base+type->rva;
        if(address<image_base||!mp4_mapped(address,16,false)
            ||!mp4game::type_descriptor_shape(*type,reinterpret_cast<void*>(address)))return;
    }
    const auto& native=mp4_actor_profile.native_graph;
    if(std::strcmp(native.engine_sha256,mp4_native_profile.native_sha256))return;
    for(const auto* call:{&native.mode_icall,&native.mode_dispatch,&native.graph_validate,&native.mode_setter}){
        const uintptr_t address=mp4_native_base+call->rva;
        if(address<mp4_native_base||!mp4_native_mapped(address,16,5)||std::memcmp(reinterpret_cast<void*>(address),call->prefix,16))return;
    }
    mp4_actor_source_verified=true;
}
bool mp4_prepare_actor_types(){
    if(!mp4_actor_source_verified||!game_call())return false;
    const auto create=[](const auto& binding,const char* space,const char* name,uint32_t& handle){
        if(handle)return true;
        if(!mp4_resolved_type_class(binding,space,name))return false;
        void* type=mp4_type_get_object(reinterpret_cast<void*>(image_base+binding.rva));
        handle=mp4_retain(type);return handle&&weak_get(handle)==type;
    };
    return create(mp4_actor_profile.actor_job_type,"ActorSwing","ActorSwingJob",mp4_actor_job_type_handle)
        &&create(mp4_actor_profile.transform_type,"UnityEngine","Transform",mp4_actor_transform_type_handle);
}
// END_MP4_ACTOR_HOST
void *mp4_float_array(size_t count) {
    return mp4_single_class&&count&&count<=16384?mp4_array_new(mp4_single_class,count):nullptr;
}
void *mp4_new_texture() { return mp4_texture_class?font_new(mp4_texture_class):nullptr; }
size_t mp4_string_utf8(void *text,char *destination,size_t capacity) {
    if(!text||!destination||!capacity)return 0;
    const int32_t count=read<int32_t>(text,0x10);
    if(count<0||count>4096)return capacity;
    size_t written=0;
    for(int32_t i=0;i<count;++i){
        uint32_t code=read<uint16_t>(text,0x14+static_cast<size_t>(i)*2);
        if(code>=0xd800&&code<=0xdbff){
            if(i+1==count)return capacity;
            const uint32_t next=read<uint16_t>(text,0x14+static_cast<size_t>(++i)*2);
            if(next<0xdc00||next>0xdfff)return capacity;
            code=0x10000+((code-0xd800)<<10)+(next-0xdc00);
        }else if(code>=0xdc00&&code<=0xdfff)return capacity;
        const size_t units=code<0x80?1:code<0x800?2:code<0x10000?3:4;
        if(code==0||written+units>=capacity)return capacity;
        if(units==1)destination[written++]=static_cast<char>(code);
        else {
            destination[written++]=static_cast<char>((units==2?0xc0:units==3?0xe0:0xf0)|(code>>((units-1)*6)));
            for(size_t part=units-1;part>0;--part)destination[written++]=static_cast<char>(0x80|((code>>((part-1)*6))&0x3f));
        }
    }
    destination[written]=0;return written;
}
bool mp4_queue_snapshot_graphics(idoly_mp4_queue::Graphics& out){
    bool has_configuration=false;Config current=configuration(&has_configuration);
    if(has_configuration){
        // A menu may leave Unity ticking while a new host setting is pending.
        // Freeze only a revision acknowledged by the existing quality/FPS,
        // render-target and projection readbacks, never a merely desired one.
        pthread_mutex_lock(&status_mutex);
        const bool applied=state.revision==current.revision
            &&(!std::strcmp(state.state,"applied")||!std::strcmp(state.state,"disabled"));
        pthread_mutex_unlock(&status_mutex);
        if(!applied)return false;
    }
    void* manager=quality_manager.get(true);
    // Zero means follow the mutable original user preference. Freeze the
    // original manager's effective quality/FPS before serializing a queue job.
    if(!manager||!object_alive(manager,nullptr))return false;
    if(!current.custom_graphics||!current.quality)current.quality=read<int32_t>(manager,0x24);
    if(!current.custom_graphics||!current.target_fps){
        // Both pinned originals' FPS getter/setter access _targetFrameRate at
        // 0xa0. 0x20 is FrameChangeScale (usually near 1), not a frame rate.
        const float observed=read<float>(manager,0xa0);
        if(!std::isfinite(observed)||observed<0||observed>120||std::fabs(observed-std::round(observed))>.001f)return false;
        current.target_fps=static_cast<int>(observed);
    }
    current.custom_graphics=true;
    if(!config_valid(1,current)||!current.quality||!current.target_fps)return false;
    out.revision=current.revision;out.custom_graphics=1;out.quality=current.quality;out.target_fps=current.target_fps;
    out.render_scale=current.render_scale;out.max_buffer_pixel=current.max_buffer_pixel;out.aa_mode=current.aa_mode;
    out.shadow_resolution=current.shadow_resolution;out.expand_photography=current.expand_photography?1:0;return true;
}
bool mp4_queue_snapshot_revision(int64_t& revision){
    // Configuration is native POD under config_mutex. Host Add must never
    // query the live quality manager to resolve an unapplied user preference.
    revision=configuration().revision;return revision>=0;
}
bool mp4_actual_source_geometry(void* controller,int32_t* width,int32_t* height){
    if(!width||!height||!mp4_type_is(controller,"VL.Rendering.VLSRPCameraController")||!mp4_alive(controller))return false;
    // The controller's original target already includes the original URP
    // scale and our verified max-buffer rule. Screen/scaledPixel dimensions
    // can differ from this actual render texture on large desktop windows.
    void* wrapper=rt_target(controller,nullptr);
    if(!mp4_type_is(wrapper,"VL.VLRenderTexture"))return false;
    void* texture=target_to_texture(wrapper,nullptr);
    if(!mp4_type_is(texture,"UnityEngine.RenderTexture")||!mp4_alive(texture))return false;
    *width=rt_width(texture,nullptr);*height=rt_height(texture,nullptr);return true;
}
// BEGIN_MP4_OUTPUT_PROJECTION
bool mp4_output_geometry_owned(void* controller){
    return mp4_geometry_active&&controller&&mp4_geometry_controller.get(true)==controller
        &&idoly_mp4_runtime::game.owned_primary_scene_current();
}
bool mp4_output_projection_owned(void* camera){
    return camera&&mp4_geometry_camera.get(true)==camera&&mp4_projection.saved
        &&mp4_output_geometry_owned(mp4_geometry_controller.get(true));
}
void mp4_clear_output_geometry(){
    mp4_geometry_controller.clear();mp4_geometry_camera.clear();mp4_projection=Mp4Projection{};
    mp4_geometry_active=false;mp4_geometry_width=mp4_geometry_height=0;
    mp4_geometry_previous_width=mp4_geometry_previous_height=0;
}
bool mp4_projection_api_available(){
    return rt_original&&rt_camera&&camera_rect_get&&orthographic&&physical_get&&fov_get_original&&fov_set_original
        &&focal_get_original&&focal_set_original&&aspect_get_original&&camera_aspect_set_original&&camera_aspect_reset&&projection_get;
}
class Mp4DynamicTargetScope {
    void* controller_;void* camera_;bool previous_=false,active_=true;
public:
    explicit Mp4DynamicTargetScope(void* controller):controller_(controller),camera_(mp4_geometry_camera.get(true)){
        std::memcpy(&previous_,static_cast<unsigned char*>(controller_)+0x30,sizeof(previous_));
        const bool disabled=false;std::memcpy(static_cast<unsigned char*>(controller_)+0x30,&disabled,sizeof(disabled));
    }
    bool finish(){
        const bool owned=idoly_mp4_runtime::game.owned_primary_scene_current()
            &&mp4_geometry_controller.get(true)==controller_&&mp4_geometry_camera.get(true)==camera_
            &&camera_&&rt_camera(controller_,nullptr)==camera_;
        if(active_&&owned)std::memcpy(static_cast<unsigned char*>(controller_)+0x30,&previous_,sizeof(previous_));
        active_=false;return owned;
    }
    ~Mp4DynamicTargetScope(){if(active_)finish();}
};
bool mp4_remember_output_projection(void* controller,void* camera,int32_t width,int32_t height){
    if(!mp4_projection_api_available()||!camera||!mp4_alive(camera)||orthographic(camera,nullptr))return false;
    Rect rect{};camera_rect_get(camera,&rect,nullptr);
    ProjectionMatrix matrix{};Frustum measured{};projection_get(camera,&matrix,nullptr);
    const float aspect=aspect_get_original(camera,nullptr),expected=static_cast<float>(width)/height;
    const float raw=fov_get_original(camera,nullptr),focal=focal_get_original(camera,nullptr);
    if(!full_rect(rect)||!perspective_frustum(matrix,&measured)||std::fabs(frustum_aspect(measured)-expected)>.005f
        ||!std::isfinite(aspect)||std::fabs(aspect-expected)>.005f||!std::isfinite(raw)||raw<=0||raw>=179
        ||!std::isfinite(focal)||focal<=0)return false;
    mp4_geometry_camera.set(camera);if(mp4_geometry_camera.get(true)!=camera)return false;
    mp4_projection=Mp4Projection{};mp4_projection.saved=true;
    mp4_projection.reference_aspect=aspect;mp4_projection.base_fov=mp4_projection.restore_fov=raw;
    mp4_projection.base_focal=mp4_projection.restore_focal=focal;
    mp4_projection.restore_physical=physical_get(camera,nullptr);
    // Reuse the original unexpanded MV framing when this very camera already
    // participates in the game's verified expanded photography view.
    if(photo.expanded&&photo.base_known&&photo.controller.get(true)==controller&&photo.camera.get(true)==camera
        &&camera_valid(photo.original)&&frustum_valid(photo.original_frustum)){
        mp4_projection.reference_aspect=photo.original.aspect;
        mp4_projection.base_fov=photo.original.vertical_fov;mp4_projection.base_focal=photo.original_focal;
    }
    return std::isfinite(mp4_projection.reference_aspect)&&mp4_projection.reference_aspect>0
        &&mp4_projection.reference_aspect<=256&&std::isfinite(mp4_projection.base_focal)&&mp4_projection.base_focal>0;
}
bool mp4_verify_output_projection(void* controller){
    if(!mp4_output_geometry_owned(controller)||!mp4_projection.required_known||!mp4_projection_api_available())return false;
    void* camera=mp4_geometry_camera.get(true);
    if(!camera||!mp4_alive(camera)||rt_camera(controller,nullptr)!=camera||orthographic(camera,nullptr))return false;
    int32_t width=0,height=0;if(!mp4_actual_source_geometry(controller,&width,&height)
        ||width!=mp4_geometry_width||height!=mp4_geometry_height)return false;
    Rect rect{};camera_rect_get(camera,&rect,nullptr);
    ProjectionMatrix matrix{};Frustum actual{};projection_get(camera,&matrix,nullptr);
    const float aspect=static_cast<float>(width)/height;
    return full_rect(rect)&&std::fabs(aspect_get_original(camera,nullptr)-aspect)<.0001f
        &&perspective_frustum(matrix,&actual)&&frustum_contains(actual,mp4_projection.required)
        &&std::fabs(frustum_aspect(actual)-aspect)<.005f;
}
bool mp4_output_projection(void* controller,bool apply){
    if(!game_call()||!mp4_output_geometry_owned(controller)||!mp4_projection_api_available())return false;
    if(!apply)return mp4_verify_output_projection(controller);
    void* camera=mp4_geometry_camera.get(true);
    if(!camera||!mp4_alive(camera)||rt_camera(controller,nullptr)!=camera||orthographic(camera,nullptr))return false;
    int32_t width=0,height=0;if(!mp4_actual_source_geometry(controller,&width,&height)
        ||width!=mp4_geometry_width||height!=mp4_geometry_height)return false;
    Rect rect{};camera_rect_get(camera,&rect,nullptr);if(!full_rect(rect))return false;
    const float target_aspect=static_cast<float>(width)/height;
    // Prove that the original RT owns this aspect before borrowing a ratio.
    // A manual aspect that merely matched the old RT must fail without being
    // silently converted to automatic mode by ResetAspect.
    if(std::fabs(aspect_get_original(camera,nullptr)-target_aspect)>.0001f)return false;
    ScopedValue<bool> internal(internal_camera,true);
    // Cinemachine getters see these baseline values, and its setters update
    // them. Never measure last frame's expanded lens as a new original lens.
    if(physical_get(camera,nullptr))focal_set_original(camera,mp4_projection.base_focal,nullptr);
    else fov_set_original(camera,mp4_projection.base_fov,nullptr);
    const float raw=fov_get_original(camera,nullptr),focal=focal_get_original(camera,nullptr);
    if(!std::isfinite(raw)||raw<=0||raw>=179||!std::isfinite(focal)||focal<=0)return false;
    mp4_projection.base_fov=raw;mp4_projection.base_focal=focal;
    ProjectionMatrix matrix{};Frustum required{},fitted{};
    if(std::fabs(mp4_projection.reference_aspect-target_aspect)<.0001f)projection_get(camera,&matrix,nullptr);
    else {
        camera_aspect_set_original(camera,mp4_projection.reference_aspect,nullptr);
        projection_get(camera,&matrix,nullptr);
        camera_aspect_reset(camera,nullptr); // The actual RT remains the sole aspect owner.
    }
    if(!perspective_frustum(matrix,&required)
        ||std::fabs(frustum_aspect(required)-mp4_projection.reference_aspect)>.005f)return false;
    if(std::fabs(aspect_get_original(camera,nullptr)-target_aspect)>.0001f)return false;
    projection_get(camera,&matrix,nullptr);float expanded=0;
    if(!perspective_frustum(matrix,&fitted)||!expanded_raw_fov(required,fitted,raw,&expanded))return false;
    fov_set_original(camera,expanded,nullptr);
    mp4_projection.required=required;mp4_projection.required_known=true;
    return mp4_verify_output_projection(controller);
}
bool mp4_set_output_geometry(void* controller,int32_t width,int32_t height){
    if(!game_call())return false;
    const bool restore=width==0&&height==0;
    if(restore){
        // A lost or pooled scene invalidates ownership. Discard only our
        // bookkeeping and never write the next scene's reused objects.
        if(!controller){mp4_clear_output_geometry();return true;}
        if(!mp4_geometry_active&&!mp4_projection.saved){mp4_clear_output_geometry();return true;}
        if(!mp4_output_geometry_owned(controller)){mp4_clear_output_geometry();return false;}
        void* camera=mp4_geometry_camera.get(true);
        const int32_t previous_width=mp4_geometry_previous_width,previous_height=mp4_geometry_previous_height;
        bool good=camera&&mp4_alive(camera)&&rt_camera(controller,nullptr)==camera;
        mp4_geometry_active=false; // Original target callbacks must not reapply the export size while restoring.
        if(good){
            ScopedValue<bool> internal(internal_camera,true);
            Mp4DynamicTargetScope dynamic(controller);
            rt_original(controller,previous_width,previous_height,false,nullptr);
            // Original target-change callbacks can transition or reuse this
            // camera. Recheck after that call before any saved lens write.
            const bool same_dynamic_owner=dynamic.finish();
            if(!same_dynamic_owner||!idoly_mp4_runtime::game.owned_primary_scene_current()
                ||mp4_geometry_controller.get(true)!=controller||mp4_geometry_camera.get(true)!=camera
                ||rt_camera(controller,nullptr)!=camera){mp4_clear_output_geometry();return true;}
            if(mp4_projection.restore_physical)focal_set_original(camera,mp4_projection.restore_focal,nullptr);
            else fov_set_original(camera,mp4_projection.restore_fov,nullptr);
            int32_t actual_width=0,actual_height=0;
            good=mp4_actual_source_geometry(controller,&actual_width,&actual_height)
                &&actual_width==previous_width&&actual_height==previous_height;
        }
        mp4_clear_output_geometry();return good;
    }
    if(!idoly_mp4_runtime::game.owned_primary_scene_current()||!mp4_type_is(controller,"VL.Rendering.VLSRPCameraController")
        ||!mp4_alive(controller)||width<16||height<16||width>4096||height>4096||width%2||height%2)return false;
    if(mp4_geometry_active&&!mp4_geometry_controller.get(true))mp4_clear_output_geometry();
    if(mp4_geometry_active&&mp4_geometry_controller.get(true)!=controller)return false;
    if(!mp4_geometry_active){
        int32_t previous_width=0,previous_height=0;
        if(!mp4_actual_source_geometry(controller,&previous_width,&previous_height)
            ||previous_width<16||previous_height<16||previous_width>4096||previous_height>4096)return false;
        if(!mp4_remember_output_projection(controller,rt_camera(controller,nullptr),previous_width,previous_height)){
            mp4_clear_output_geometry();return false;
        }
        mp4_geometry_controller.set(controller);
        if(mp4_geometry_controller.get(true)!=controller){mp4_clear_output_geometry();return false;}
        mp4_geometry_previous_width=previous_width;mp4_geometry_previous_height=previous_height;
    }
    mp4_geometry_width=width;mp4_geometry_height=height;mp4_geometry_active=true;
    ScopedValue<bool> internal(internal_camera,true);
    Mp4DynamicTargetScope dynamic(controller);
    rt_original(controller,width,height,false,nullptr);
    if(!dynamic.finish()){mp4_clear_output_geometry();return false;}
    int32_t actual_width=0,actual_height=0;
    return mp4_actual_source_geometry(controller,&actual_width,&actual_height)&&actual_width==width&&actual_height==height;
}
// END_MP4_OUTPUT_PROJECTION
bool mp4_queue_apply_graphics(const idoly_mp4_queue::Graphics* value){
    Config next{};
    if(value){next.revision=value->revision;next.custom_graphics=value->custom_graphics!=0;next.quality=value->quality;next.target_fps=value->target_fps;
        next.render_scale=value->render_scale;next.max_buffer_pixel=value->max_buffer_pixel;next.aa_mode=value->aa_mode;
        next.shadow_resolution=value->shadow_resolution;next.expand_photography=value->expand_photography!=0;
        if(!config_valid(1,next))return false;}
    pthread_mutex_lock(&config_mutex);mp4_queue_graphics=next;mp4_queue_graphics_override=value!=nullptr;pthread_mutex_unlock(&config_mutex);return true;
}
void* mp4_replay_new_object(idoly_mp4_replay::Kind kind){return mp4_replay_factory.new_object(kind);}
void* mp4_replay_new_list(void* owner,const char* field){return mp4_replay_factory.new_field_list(owner,field);}
bool mp4_replay_add(void* list,void* value){return mp4_replay_factory.list_add(list,value);}
bool mp4_replay_set_object(void* owner,const char* field,void* value){return mp4_replay_factory.set_object(owner,field,value);}
bool mp4_replay_set_i32(void* owner,const char* field,int32_t value){return mp4_replay_factory.set_i32(owner,field,value);}
bool mp4_replay_set_bool(void* owner,const char* field,bool value){return mp4_replay_factory.set_bool(owner,field,value);}
bool mp4_photography_dispatch_paused(){
    pthread_mutex_lock(&idoly_mp4_runtime::control_mutex);
    const bool paused=idoly_mp4_runtime::requested_pause_reason!=IDMP4_PAUSE_NONE;
    pthread_mutex_unlock(&idoly_mp4_runtime::control_mutex);
    return paused||idoly_mp4_runtime::queue_paused||idoly_mp4_runtime::queue_blocked;
}
// BEGIN_MP4_PHOTOGRAPHY_NAVIGATION
bool mp4_photography_can_route(){
    auto& nav=mp4_photography_navigation;
    if(!mp4_photography_verified||!nav.configured||!mp4_api_installed||!game_call())return false;
    if(nav.pending||nav.failed)return false;
    void* manager=nullptr;uint8_t allow=0;int32_t scene=-1;
    try {
        nav.static_get(nav.instance_field,&manager);
        nav.static_get(nav.allow_field,&allow);nav.static_get(nav.scene_field,&scene);
    }catch(...){snprintf(nav.error,sizeof(nav.error),"%s","photography_navigation_probe_exception");return false;}
    // Read the closed Singleton<T> static field, never its creating getter.
    // SolisSceneManager's full original ancestry reaches UnityEngine.Object.
    if(!manager||object_class(manager)!=nav.manager_class||!mp4_alive(manager)){
        snprintf(nav.error,sizeof(nav.error),"%s","photography_scene_manager_not_ready");return false;
    }
    if(allow!=1||scene<0||scene>65535){snprintf(nav.error,sizeof(nav.error),"%s","photography_scene_loading_unavailable");return false;}
    return true;
}
void mp4_release_photography_navigation_inputs(){
    auto& nav=mp4_photography_navigation;
    for(auto* handle:{&nav.source_handle,&nav.targets_handle,&nav.transition_handle,&nav.manager_handle}){
        if(*handle){weak_free(*handle);}
        *handle=0;
    }
    nav.task=Mp4PhotographyBoolTask{};
}
void mp4_photography_cancel(){
    auto& nav=mp4_photography_navigation;
    if(nav.pending)nav.cancel_requested=true;
}
void mp4_advance_photography_navigation(){
    auto& nav=mp4_photography_navigation;
    if(!nav.pending||(nav.phase!=1&&nav.phase!=3)||!game_call())return;
    bool prepared=false;const char* failure=nullptr;
    if(nav.phase==1){
    try {
        if(nav.source_handle)nav.task.source=weak_get(nav.source_handle);
        const int32_t status=nav.task_status(&nav.task,nav.status_info);
        if(status==0)return;
        if(status<1||status>3)failure="photography_asset_task_status_invalid";
        else {
            auto awaiter=nav.task_awaiter(&nav.task,nav.awaiter_info);
            nav.task_consumed=true; // Mark before the original GetResult can throw.
            prepared=nav.task_result(&awaiter,nav.result_info);
            if(!prepared)failure="photography_asset_preparation_failed";
        }
    }catch(...){failure="photography_asset_preparation_exception";}
    if(nav.cancel_requested||failure){
        const bool cancelled=nav.cancel_requested;
        mp4_release_photography_navigation_inputs();nav.pending=false;nav.phase=0;nav.cancel_requested=false;
        snprintf(nav.error,sizeof(nav.error),"%s",cancelled?"none":failure);return;
    }
    // Prepared input survives pause without keeping a pooled source/targets.
    if(nav.source_handle){weak_free(nav.source_handle);}
    nav.source_handle=0;
    if(nav.targets_handle){weak_free(nav.targets_handle);}
    nav.targets_handle=0;
    nav.task=Mp4PhotographyBoolTask{};nav.phase=3;
    }
    if(nav.cancel_requested){
        mp4_release_photography_navigation_inputs();nav.pending=false;nav.phase=0;nav.cancel_requested=false;
        snprintf(nav.error,sizeof(nav.error),"%s","none");return;
    }
    if(nav.dispatch_paused&&nav.dispatch_paused())return;
    void* manager=weak_get(nav.manager_handle);void* current=nullptr;int32_t scene=-1;uint8_t allow=0;
    try {nav.static_get(nav.instance_field,&current);nav.static_get(nav.scene_field,&scene);nav.static_get(nav.allow_field,&allow);}
    catch(...){failure="photography_navigation_probe_exception";}
    if(failure||nav.generation!=nav.dispatch_generation||!manager||manager!=current||object_class(manager)!=nav.manager_class||!mp4_alive(manager)
        ||scene<0||scene>65535||allow!=1){
        mp4_release_photography_navigation_inputs();nav.pending=false;nav.phase=0;
        snprintf(nav.error,sizeof(nav.error),"%s",failure?failure:"photography_navigation_scope_changed");return;
    }
    void* transition=weak_get(nav.transition_handle);
    nav.dispatch_generation=nav.generation;nav.phase=2;
    try {
        nav.set_data(manager,transition,nullptr);
        // Original SceneManager reloads this scene with Single=0. It owns the
        // old coroutine's destroy token; never reenter Play on the old root.
        nav.load_scene(manager,scene,nav.load_mode,nullptr);
        mp4_release_photography_navigation_inputs();
        snprintf(nav.error,sizeof(nav.error),"%s","none");
    }catch(...){
        mp4_release_photography_navigation_inputs();nav.pending=false;nav.phase=0;nav.failed=true;
        snprintf(nav.error,sizeof(nav.error),"%s","photography_scene_load_exception");
    }
}
bool mp4_photography_open(const idoly_mp4_queue::PhotoSelection& photo){
    auto& nav=mp4_photography_navigation;
    if(!mp4_photography_can_route())return false;
    void* transition=mp4_photography_factory().build_transition(photo);
    if(!transition){snprintf(nav.error,sizeof(nav.error),"%s",mp4_photography_factory().error());return false;}
    void* manager=nullptr;
    try {nav.static_get(nav.instance_field,&manager);}
    catch(...){snprintf(nav.error,sizeof(nav.error),"%s","photography_navigation_probe_exception");return false;}
    if(!manager||object_class(manager)!=nav.manager_class||!mp4_alive(manager)){
        snprintf(nav.error,sizeof(nav.error),"%s","photography_navigation_scope_changed");return false;
    }
    nav.manager_handle=mp4_retain(manager);nav.transition_handle=mp4_retain(transition);
    if(!nav.manager_handle||!nav.transition_handle){
        mp4_release_photography_navigation_inputs();snprintf(nav.error,sizeof(nav.error),"%s","photography_navigation_handle_failed");return false;
    }
    try {
        void* targets=nav.download_targets(transition,nullptr);nav.targets_handle=mp4_retain(targets);
        if(!nav.targets_handle){mp4_release_photography_navigation_inputs();snprintf(nav.error,sizeof(nav.error),"%s","photography_asset_targets_unavailable");return false;}
        nav.pending=true;nav.phase=1;nav.dispatch_generation=nav.generation;nav.cancel_requested=nav.task_consumed=false;
        // Original dedicated overload: no confirm sheet, no input-block lease.
        nav.task=nav.pre_download(targets,idoly_mp4_replay::CancellationToken8{},false,nullptr);
        if(nav.task.source){nav.source_handle=mp4_retain(nav.task.source);if(!nav.source_handle){
            mp4_release_photography_navigation_inputs();nav.pending=false;nav.phase=0;nav.failed=true;
            snprintf(nav.error,sizeof(nav.error),"%s","photography_asset_task_handle_failed");return false;
        }}
        snprintf(nav.error,sizeof(nav.error),"%s","none");return true;
    }catch(...){
        mp4_release_photography_navigation_inputs();nav.pending=false;nav.phase=0;
        snprintf(nav.error,sizeof(nav.error),"%s","photography_asset_preparation_exception");return false;
    }
}
// END_MP4_PHOTOGRAPHY_NAVIGATION
const char* mp4_photography_error(){return !mp4_photography_verified?mp4_photography_binding_error:mp4_photography_navigation.error;}
bool mp4_photography_current(void* root,void* player){
    return idoly_mp4_runtime::game.scene_kind()==mp4game::SceneKind::photography
        &&idoly_mp4_runtime::game.selected_presenter()==root&&idoly_mp4_runtime::game.selected_player()==player;
}
const void* mp4_unique_class_method(void* klass,uintptr_t expected){
    if(!klass||!expected)return nullptr;
    using Enumerate=const void*(*)(void*,void**);
    auto enumerate=reinterpret_cast<Enumerate>(image_base+mp4_photography_profile.class_methods.rva);
    void* cursor=nullptr;const void* found=nullptr;
    for(unsigned count=0;count<512;++count){
        const void* method=enumerate(klass,&cursor);
        if(!method)return found;
        if(read<uintptr_t>(const_cast<void*>(method),0)==expected){if(found)return nullptr;found=method;}
    }
    return nullptr;
}
void mp4_configure_photography_factory(const idoly_mp4_replay_factories::Calls& managed){
    if(!mp4_photography_verified)return;
    namespace photo_replay=idoly_mp4_photography_replay;
    photo_replay::Classes classes{};
    classes.actor=mp4_resolved_type_class(mp4_photography_profile.actor_type,"Solis.Common.Data","ActorCostume");
    classes.transition=mp4_resolved_type_class(mp4_photography_profile.transition_type,"Solis.Photography.Data","PhotographyLiveTransitionData");
    classes.screen_transition=mp4_resolved_type_class(mp4_photography_profile.screen_transition_type,"Solis.Photography.Data","PhotographyLiveScreenTransitionData");
    if(!classes.actor||!classes.transition||!classes.screen_transition){
        snprintf(mp4_photography_binding_error,sizeof(mp4_photography_binding_error),"%s",mp4_binding_error);mp4_photography_verified=false;return;
    }
    photo_replay::Calls calls{};calls.managed=managed;calls.new_string=mp4_string_new;calls.string_utf8=mp4_string_utf8;
#define MP4_PHOTOGRAPHY_CALL(name) calls.name=reinterpret_cast<decltype(calls.name)>(image_base+mp4_photography_profile.name.rva)
    MP4_PHOTOGRAPHY_CALL(stage_master);MP4_PHOTOGRAPHY_CALL(music_master);MP4_PHOTOGRAPHY_CALL(costume_master);MP4_PHOTOGRAPHY_CALL(hair_master);
    MP4_PHOTOGRAPHY_CALL(stage_rows);MP4_PHOTOGRAPHY_CALL(music_rows);MP4_PHOTOGRAPHY_CALL(find_costume);MP4_PHOTOGRAPHY_CALL(find_hair);
    MP4_PHOTOGRAPHY_CALL(actor_ctor);MP4_PHOTOGRAPHY_CALL(actor_costume_id);MP4_PHOTOGRAPHY_CALL(actor_hair_id);
    MP4_PHOTOGRAPHY_CALL(transition_ctor);MP4_PHOTOGRAPHY_CALL(screen_transition_ctor);
#undef MP4_PHOTOGRAPHY_CALL
    calls.stage_sort=mp4_photography_profile.stage_sort;calls.music_sort=mp4_photography_profile.music_sort;
    calls.expected_list_ctor=image_base+mp4_photography_profile.list_ctor.rva;
    calls.expected_list_add=image_base+mp4_photography_profile.list_add.rva;
    if(!mp4_photography_factory().configure(calls,classes))return;
    try {
    auto& nav=mp4_photography_navigation;
    nav.manager_class=mp4_resolved_type_class(mp4_photography_profile.scene_manager_type,"Solis.Common","SolisSceneManager");
    void* define=mp4_resolved_type_class(mp4_photography_profile.scene_define_type,"","SceneDefine");
    void* unity=mp4_resolved_type_class(mp4_photography_profile.unity_scene_manager_type,"UnityEngine.SceneManagement","SceneManager");
    if(!nav.manager_class||!define||!unity){snprintf(nav.error,sizeof(nav.error),"%s",mp4_binding_error);return;}
    void* parent=class_parent(nav.manager_class);
    const char* parent_name=parent?class_name(parent):nullptr;
    const char* parent_space=parent?class_namespace(parent):nullptr;
    if(!parent_name||!parent_space||std::strcmp(parent_name,"Singleton`1")||std::strcmp(parent_space,"Qua.Utility"))return;
    nav.instance_field=font_field(parent,"_instance");nav.scene_field=font_field(define,"Photography");nav.allow_field=font_field(unity,"s_AllowLoadScene");
    if(!nav.instance_field||!nav.scene_field||!nav.allow_field)return;
    const void* instance_type=font_field_type(nav.instance_field);
    const void* scene_type=font_field_type(nav.scene_field);const void* allow_type=font_field_type(nav.allow_field);
    if(!instance_type||!scene_type||!allow_type||font_class_type(instance_type)!=nav.manager_class
        ||managed.type_get_type(scene_type)!=8||managed.type_get_type(allow_type)!=2)return;
    using ClassInit=void(*)(void*);
    auto initialize=reinterpret_cast<ClassInit>(image_base+mp4_photography_profile.runtime_class_init.rva);
    initialize(define);initialize(unity);
    nav.static_get=reinterpret_cast<decltype(nav.static_get)>(image_base+mp4_photography_profile.field_static_get.rva);
    nav.set_data=reinterpret_cast<decltype(nav.set_data)>(image_base+mp4_photography_profile.scene_set_data.rva);
    nav.load_scene=reinterpret_cast<decltype(nav.load_scene)>(image_base+mp4_photography_profile.scene_load.rva);
    nav.load_mode=mp4_photography_profile.load_mode;nav.dispatch_paused=mp4_photography_dispatch_paused;
    void* downloader=mp4_resolved_type_class(mp4_photography_profile.downloader_type,"Solis.Common.Octo","ResourceDownloader");
    const void* download_method=mp4_unique_class_method(downloader,image_base+mp4_photography_profile.pre_download.rva);
    if(!download_method||read<uintptr_t>(const_cast<void*>(download_method),0)!=image_base+mp4_photography_profile.pre_download.rva)return;
    using ReturnType=const void*(*)(const void*);
    auto method_return_type=reinterpret_cast<ReturnType>(image_base+mp4_photography_profile.method_return_type.rva);
    const void* task_type=method_return_type(download_method);
    void* task_class=task_type?font_class_type(task_type):nullptr;
    const char* task_name=task_class?class_name(task_class):nullptr;const char* task_space=task_class?class_namespace(task_class):nullptr;
    if(!task_name||!task_space||std::strcmp(task_name,"UniTask`1")||std::strcmp(task_space,"Cysharp.Threading.Tasks"))return;
    nav.status_info=font_method(task_class,"get_Status",0);nav.awaiter_info=font_method(task_class,"GetAwaiter",0);
    if(!nav.status_info||!nav.awaiter_info)return;
    const void* awaiter_type=method_return_type(nav.awaiter_info);
    void* awaiter_class=awaiter_type?font_class_type(awaiter_type):nullptr;
    const char* awaiter_name=awaiter_class?class_name(awaiter_class):nullptr;const char* awaiter_space=awaiter_class?class_namespace(awaiter_class):nullptr;
    if(!awaiter_name||!awaiter_space||std::strcmp(awaiter_name,"Awaiter")||std::strcmp(awaiter_space,""))return;
    nav.result_info=font_method(awaiter_class,"GetResult",0);
    if(!nav.result_info||read<uintptr_t>(const_cast<void*>(nav.status_info),0)!=image_base+mp4_photography_profile.bool_task_status.rva
        ||read<uintptr_t>(const_cast<void*>(nav.awaiter_info),0)!=image_base+mp4_photography_profile.bool_task_awaiter.rva
        ||read<uintptr_t>(const_cast<void*>(nav.result_info),0)!=image_base+mp4_photography_profile.bool_task_result.rva)return;
    nav.download_targets=reinterpret_cast<decltype(nav.download_targets)>(image_base+mp4_photography_profile.download_targets.rva);
    nav.pre_download=reinterpret_cast<decltype(nav.pre_download)>(image_base+mp4_photography_profile.pre_download.rva);
    nav.task_status=reinterpret_cast<decltype(nav.task_status)>(image_base+mp4_photography_profile.bool_task_status.rva);
    nav.task_awaiter=reinterpret_cast<decltype(nav.task_awaiter)>(image_base+mp4_photography_profile.bool_task_awaiter.rva);
    nav.task_result=reinterpret_cast<decltype(nav.task_result)>(image_base+mp4_photography_profile.bool_task_result.rva);
    nav.configured=true;
    snprintf(nav.error,sizeof(nav.error),"%s","none");
    }catch(...){snprintf(mp4_photography_navigation.error,sizeof(mp4_photography_navigation.error),"%s","photography_navigation_configuration_exception");}
}

void mp4_install_replay_runtime(){
    if(!mp4_replay_verified)return;
    namespace factories=idoly_mp4_replay_factories;
    factories::Calls calls{};calls.object_class=object_class;calls.class_name=class_name;calls.class_namespace=class_namespace;
    calls.class_parent=class_parent;calls.field=font_field;calls.field_type=font_field_type;calls.class_from_type=font_class_type;
    calls.object_new=font_new;calls.method=font_method;calls.strong_new=font_strong;calls.target=weak_get;calls.release=weak_free;
    calls.type_get_type=reinterpret_cast<decltype(calls.type_get_type)>(image_base+mp4_replay_profile.type_get_type.rva);
    calls.field_set_value=reinterpret_cast<decltype(calls.field_set_value)>(image_base+mp4_replay_profile.field_set_value.rva);
    factories::Classes classes{};
    classes.out_game_param=mp4_resolved_type_class(mp4_replay_profile.out_game_param_type,"Solis.OutGame","OutGameLivePlayerParam");
    classes.actor_descriptor=mp4_resolved_type_class(mp4_replay_profile.actor_descriptor_type,"Solis.Common","SolisActorDescriptor");
    classes.transition_param=mp4_resolved_type_class(mp4_replay_profile.transition_param_type,"Solis.OutGame","LivePlayerTransitionParam");
    if(!classes.out_game_param||!classes.actor_descriptor||!classes.transition_param)return;
    if(!mp4_replay_factory.configure(calls,classes))return;
    mp4_configure_photography_factory(calls);
    idoly_mp4_replay::Api api{};api.is_type=mp4_type_is;api.alive=mp4_alive;api.retain=mp4_retain;api.retained=weak_get;api.release=weak_free;
    api.new_object=mp4_replay_new_object;api.new_string=mp4_string_new;api.new_field_list=mp4_replay_new_list;api.list_add=mp4_replay_add;
    api.set_object=mp4_replay_set_object;api.set_i32=mp4_replay_set_i32;api.set_bool=mp4_replay_set_bool;
    api.photography_can_route=mp4_photography_can_route;api.photography_open=mp4_photography_open;api.photography_cancel=mp4_photography_cancel;api.photography_error=mp4_photography_error;api.photography_current=mp4_photography_current;
#define MP4_REPLAY_CALL(name) api.name=reinterpret_cast<decltype(api.name)>(image_base+mp4_replay_profile.name.rva)
    MP4_REPLAY_CALL(out_game_param_ctor);MP4_REPLAY_CALL(actor_descriptor_ctor);MP4_REPLAY_CALL(transition_param_ctor);MP4_REPLAY_CALL(param_add_actor);
    MP4_REPLAY_CALL(scene_instance);MP4_REPLAY_CALL(scene_busy);MP4_REPLAY_CALL(live_state);MP4_REPLAY_CALL(tree_with_param);MP4_REPLAY_CALL(open_tree);
    MP4_REPLAY_CALL(presenter_end);MP4_REPLAY_CALL(task_status);MP4_REPLAY_CALL(task_get_awaiter);MP4_REPLAY_CALL(task_get_result);MP4_REPLAY_CALL(top_screen);MP4_REPLAY_CALL(player_ready);
#undef MP4_REPLAY_CALL
    idoly_mp4_runtime::install_queue_api(api,mp4_queue_snapshot_graphics,mp4_queue_apply_graphics,
#ifdef IDOLY_DARWIN_BRIDGE
        mp4game::ios_original_sha256,
#else
        mp4game::android_original_sha256,
#endif
        mp4_queue_snapshot_revision);
}
bool mp4_prepare_runtime() {
    if(mp4_api_installed)return true;
    auto unavailable=[](const char* reason){
        pthread_mutex_lock(&idoly_mp4_runtime::control_mutex);
        idoly_mp4_runtime::published.ready=false;
        snprintf(idoly_mp4_runtime::readiness_error,sizeof(idoly_mp4_runtime::readiness_error),"%s",reason);
        pthread_mutex_unlock(&idoly_mp4_runtime::control_mutex);
        return false;
    };
    if(!mp4_source_verified)return unavailable(mp4_binding_error);
    if(!game_call())return false;
    mp4_single_class=mp4_resolved_type_class(mp4_runtime_profile.single_type,"System","Single");
    if(!mp4_single_class)return unavailable(mp4_binding_error);
    mp4_texture_class=mp4_resolved_type_class(mp4_runtime_profile.texture2d_type,"UnityEngine","Texture2D");
    if(!mp4_texture_class)return unavailable(mp4_binding_error);
    if(!mp4_controller_type_handle){
        if(!mp4_resolved_type_class(mp4_camera_owner_profile.controller_type,"VL.Rendering","VLSRPCameraController"))
            return unavailable(mp4_binding_error);
        void* controller_type=mp4_type_get_object(reinterpret_cast<const void*>(image_base+mp4_camera_owner_profile.controller_type.rva));
        if(!controller_type)return unavailable("selected_controller_type_not_ready");
        mp4_controller_type_handle=mp4_retain(controller_type);
        if(!mp4_controller_type_handle)return unavailable("selected_controller_type_handle_failed");
    }
    void *audio_class=mp4_resolved_type_class(mp4_runtime_profile.audio_clip_type,"UnityEngine","AudioClip");
    if(!audio_class)return unavailable(mp4_binding_error);
    void *audio_type=mp4_type_get_object(reinterpret_cast<const void*>(image_base+mp4_runtime_profile.audio_clip_type.rva));
    if(!audio_type)return unavailable("mv_audio_type_not_ready");
    mp4_audio_type_handle=mp4_retain(audio_type);if(!mp4_audio_type_handle)return unavailable("mv_audio_type_handle_failed");
    mp4game::Api helpers{};
    helpers.is_type=mp4_type_is;helpers.exact_type=mp4_exact_type;helpers.alive=mp4_alive;helpers.retain=mp4_retain;
    helpers.retained=weak_get;helpers.release=weak_free;helpers.new_string=mp4_string_new;
    helpers.string_utf8=mp4_string_utf8;helpers.array_length=mp4_array_length;helpers.array_data=mp4_array_data;
    helpers.new_float_array=mp4_float_array;helpers.new_texture2d=mp4_new_texture;
    helpers.audio_clip_type=weak_get(mp4_audio_type_handle);
    helpers.recorded_graph_mode=mp4_recorded_graph_mode;helpers.camera_clock_ok=mp4_camera_clock_ok;
    helpers.source_geometry=mp4_actual_source_geometry;
    helpers.output_geometry=mp4_set_output_geometry;
    helpers.output_projection=mp4_output_projection;
    mp4_api=mp4game::with_original_calls(helpers,mp4_profile,image_base);
    mp4_api.brain_manual_update=mp4_owned_brain_manual_update;
    // A new client must never select the former manual-seek exporter while
    // any native scene/dependent closure remains unverified.
    idoly_mp4_runtime::require_native_scene_pipeline();
    idoly_mp4_runtime::install_game_api(mp4_api,mp4game::Layout{});
    mp4_install_replay_runtime();
    mp4_api_installed=true;return true;
}
// BEGIN_MP4_SELECTED_CONTROLLER
void *mp4_selected_controller(void *presenter) {
    idoly_mp4_timeline_camera::Counters counts{};
    uint32_t candidates=0;
    const auto reject=[&](const char* reason)->void*{
        idoly_mp4_runtime::observe_controller_discovery(reason,"none",counts,candidates);return nullptr;
    };
    const auto accept=[&](void* controller,const char* source)->void*{
        idoly_mp4_runtime::observe_controller_discovery("none",source,counts,candidates);return controller;
    };
    void *player=nullptr;
    if(mp4_type_is(presenter,"Solis.OutGame.LivePlayerScreenPresenter")) {
        player=read<void*>(presenter,0xe0);
        if(!mp4_type_is(player,"Solis.Common.SolisLivePlayer"))return reject("selected_mv_not_loaded");
    } else if(mp4_type_is(presenter,"Solis.Photography.PhotographyLivePresenter")) {
        if(!mp4_alive(presenter)||!mp4_api.active_enabled(presenter,nullptr))return reject("selected_presenter_inactive");
        void* mode=read<void*>(presenter,0x30);
        if(!mp4_type_is(mode,"Solis.Photography.PhotographyLiveModePresenter")||!mp4_alive(mode)
            ||!mp4_api.active_enabled(mode,nullptr))return reject("selected_photography_mode_not_loaded");
        if(!mp4_type_is(read<void*>(mode,0x30),"Solis.Photography.Data.PhotographyLiveTransitionData"))
            return reject("selected_photography_data_not_loaded");
        if(mp4_api.photo_mode_is_mv(mode,nullptr))return reject("selected_video_mv_unsupported");
        player=read<void*>(mode,0x20);
        if(!mp4_type_is(player,"Solis.Common.Photography.PhotographyLive3DPresenter")
            ||!mp4_alive(player)||!mp4_api.active_enabled(player,nullptr)||!read<bool>(player,0x70))
            return reject("selected_photography_3d_not_built");
    } else return reject("selected_presenter_missing");
    if(!mp4_alive(player))return reject("selected_mv_not_loaded");
    void* timeline=read<void*>(player,0x38);
    const auto selected=idoly_mp4_timeline_camera::scan(timeline,mp4game::timeline_camera_api(mp4_api));
    counts=selected.counts;
    if(!selected.ok())return reject(selected.error);
    void* camera=selected.camera;
    void* main=main_controller.get(true);
    if(main){++candidates;if(rt_camera(main,nullptr)==camera)return accept(main,"observed");}
    for(const auto& candidate:controller_candidates){
        void* controller=candidate.get(true);
        if(controller){++candidates;if(rt_camera(controller,nullptr)==camera)return accept(controller,"observed");}
    }
    void* original=mp4_original_current_controller();
    if(original){++candidates;if(rt_camera(original,nullptr)==camera){remember_controller(original);return accept(original,"singleton");}}
    // GetComponent is scoped to the exact already-bound timeline camera. It
    // never searches a scene, creates a component or substitutes Camera.main.
    mp4game::CameraOwnerCalls owner{};
    owner.is_type=mp4_type_is;owner.alive=mp4_alive;owner.retain=mp4_retain;owner.retained=weak_get;owner.release=weak_free;
    owner.get_component=reinterpret_cast<decltype(owner.get_component)>(image_base+mp4_camera_owner_profile.component_get_component.rva);
    owner.controller_camera=rt_camera;
    const auto recovered=mp4game::recover_camera_controller(camera,weak_get(mp4_controller_type_handle),owner);
    if(!recovered.handle)return reject(recovered.error);
    void* controller=weak_get(recovered.handle);
    // Adopt while the helper's strong root is still held; a raw pointer alone
    // cannot bridge a subsequent handle allocation or managed collection.
    idoly_mp4_runtime::observe_camera_controller(controller);
    remember_controller(controller);
    weak_free(recovered.handle);
    return accept(controller,"camera_component");
}

// END_MP4_SELECTED_CONTROLLER
Weak mp4_photography_presenter;
void mp4_observe_photography_presenter() {
    void* presenter=mp4_photography_presenter.get(true);
    if(!mp4_type_is(presenter,"Solis.Photography.PhotographyLivePresenter")
        ||!mp4_api.active_enabled(presenter,nullptr))return;
    idoly_mp4_runtime::observe_presenter(presenter);
    if(void* player=idoly_mp4_runtime::game.selected_player()){
        void* mode=read<void*>(presenter,0x30);
        void* transition=read<void*>(mode,0x30);
        idoly_mp4_runtime::observe_photography_transition(player,transition);
        auto& nav=mp4_photography_navigation;
        if(((nav.pending&&nav.phase==2)||nav.failed)&&nav.generation>nav.dispatch_generation
            &&(mp4_exact_type(transition,"Solis.Photography.Data.PhotographyLiveTransitionData")
                ||mp4_exact_type(transition,"Solis.Photography.Data.PhotographyLiveScreenTransitionData"))){
            nav.pending=nav.failed=nav.cancel_requested=false;nav.phase=0;snprintf(nav.error,sizeof(nav.error),"%s","none");
        }
    }
    if(void* controller=mp4_selected_controller(presenter))idoly_mp4_runtime::observe_camera_controller(controller);
}
void mp4_unity_tick() {
    if(mp4_prepare_runtime()){
        (void)mp4_prepare_actor_types();
        mp4_observe_photography_presenter();
        idoly_mp4_runtime::on_unity_tick();
        // Observe this frame's cancel/pause commands before any scene handoff.
        mp4_advance_photography_navigation();
    }
}
// Original managed-call value aggregates. These are not P/Invoke marshaling
// structs; both original ARM64 clients pass/return the exact payload registers.
struct Mp4UniTask {void* source;short token;uint8_t padding[6];};
struct Mp4CancellationToken {void* source;};
static_assert(sizeof(Mp4UniTask)==16&&sizeof(Mp4CancellationToken)==8,"Original async ABI differs");
using Mp4PlayerInitialize=Mp4UniTask(*)(void*,void*,bool,Mp4CancellationToken,Method*);
Mp4PlayerInitialize mp4_player_initialize_original;
Mp4UniTask mp4_player_initialize_hook(void* self,void* param,bool auto_setup,Mp4CancellationToken token,Method* method){
    mp4_actor_scene_will_change(self);
    // The original actor loader mutates descriptor rendering masks. Capture
    // the caller's immutable selection before starting that original task.
    if(ready.load(std::memory_order_acquire)&&game_call(true)&&mp4_prepare_runtime())
        idoly_mp4_runtime::observe_player_initializing(self,param);
    return mp4_player_initialize_original(self,param,auto_setup,token,method);
}
// BEGIN_MP4_PHOTOGRAPHY_HOOKS
// A concrete FasterLinq.SelectList is the original photography producer. Freeze
// it once before the actor loader changes descriptor rendering-layer masks;
// never treat an arbitrary IEnumerable as a managed array or execute it twice.
void* mp4_normalize_photography_descriptors(void* data) {
    if(!mp4_source_verified||!mp4_replay_verified||!game_call()
        ||!mp4_type_is(data,"Solis.Common.Photography.PhotographyLiveData"))return nullptr;
    struct Roots {
        uint32_t values[3]{};unsigned count=0;
        ~Roots(){for(unsigned i=0;i<count;++i)if(values[i])weak_free(values[i]);}
        bool add(void* object){if(count>=3)return false;values[count]=mp4_retain(object);return values[count++]!=0;}
    } roots;
    if(!roots.add(data))return nullptr;
    void* characters=read<void*>(data,0x28);
    if(!mp4_type_is(characters,"System.String[]"))return nullptr;
    const size_t count=mp4_array_length(characters);
    if(!count||count>32)return nullptr;
    void* descriptors=read<void*>(data,0x20);
    auto valid=[&](void* array){
        if(!mp4_type_is(array,"Solis.Common.SolisActorDescriptor[]")||mp4_array_length(array)!=count)return false;
        auto** items=static_cast<void**>(mp4_array_data(array));
        for(size_t i=0;i<count;++i)if(!mp4_type_is(items[i],"Solis.Common.SolisActorDescriptor"))return false;
        return true;
    };
    if(valid(descriptors))return descriptors;
    if(!mp4_type_is(descriptors,".SelectList`2")||!roots.add(descriptors))return nullptr;
    void* source=read<void*>(descriptors,0x10);
    if(!mp4_type_is(source,"System.Collections.Generic.List`1")
        ||read<int32_t>(source,0x18)!=static_cast<int32_t>(count)||!read<void*>(descriptors,0x18))return nullptr;
    void* source_items=read<void*>(source,0x10);
    if(!source_items||mp4_array_length(source_items)<count||mp4_array_length(source_items)>1024)return nullptr;
    void* field=font_field(object_class(data),"<ActorDescriptors>k__BackingField");
    const void* method=font_method(object_class(descriptors),"ToArray",0);
    if(!field||!method)return nullptr;
    using ToArray=void*(*)(void*,const void*);
    auto to_array=read<ToArray>(const_cast<void*>(method),0);
    if(reinterpret_cast<uintptr_t>(to_array)!=image_base+mp4_profile.photo_select_to_array.rva)return nullptr;
    void* array=nullptr;
    try {array=to_array(descriptors,method);} catch (...) {return nullptr;}
    if(!valid(array)||!roots.add(array)||read<void*>(data,0x28)!=characters
        ||read<void*>(data,0x20)!=descriptors||read<void*>(descriptors,0x10)!=source
        ||read<int32_t>(source,0x18)!=static_cast<int32_t>(count))return nullptr;
    using SetField=void(*)(void*,void*,void*);
    auto set_field=reinterpret_cast<SetField>(image_base+mp4_replay_profile.field_set_value.rva);
    // The pinned IL2CPP reference-field dispatcher takes the managed object
    // itself. Passing &array would persist a native stack address in data.
    set_field(data,field,array); // Includes the original GC write barrier.
    return read<void*>(data,0x20)==array?array:nullptr;
}
using Mp4PhotographyInitialize=Mp4UniTask(*)(void*,void*,void*,Mp4CancellationToken,Method*);
using Mp4PhotographyPlayerInitialize=Mp4UniTask(*)(void*,void*,Mp4CancellationToken,Method*);
Mp4PhotographyInitialize mp4_photography_initialize_original;
Mp4PhotographyPlayerInitialize mp4_photography_player_initialize_original;
VoidMethod mp4_photography_end_original;
Mp4UniTask mp4_photography_initialize_hook(void* self,void* transition,void* capture,Mp4CancellationToken token,Method* method){
    mp4_actor_scene_will_change(self);
    if(ready.load(std::memory_order_acquire)&&game_call(true)&&mp4_prepare_runtime()
        &&mp4_type_is(self,"Solis.Photography.PhotographyLivePresenter")){
        mp4_photography_presenter.set(self);
        auto& nav=mp4_photography_navigation;
        if(nav.generation!=~uint64_t(0))++nav.generation;
        else {nav.failed=true;snprintf(nav.error,sizeof(nav.error),"%s","photography_generation_exhausted");}
    }
    return mp4_photography_initialize_original(self,transition,capture,token,method);
}
Mp4UniTask mp4_photography_player_initialize_hook(void* self,void* data,Mp4CancellationToken token,Method* method){
    mp4_actor_scene_will_change(self);
    if(ready.load(std::memory_order_acquire)&&game_call(true)&&mp4_prepare_runtime()) {
        void* descriptors=mp4_normalize_photography_descriptors(data);
        idoly_mp4_runtime::observe_photography_initializing(self,data,descriptors);
    }
    return mp4_photography_player_initialize_original(self,data,token,method);
}
void mp4_photography_end_hook(void* self,Method* method){
    mp4_actor_scene_will_change(self);
    if(ready.load(std::memory_order_acquire)&&game_call(true)) {
        if(mp4_photography_presenter.get()==self)mp4_photography_presenter.clear();
        // Original End leaves Built and active fields set. Invalidate the
        // selected scope explicitly before Stop so an ended MV cannot remain
        // ready or receive a later manual-export rollback.
        idoly_mp4_runtime::observe_presenter_ended(self);
    }
    mp4_photography_end_original(self,method);
}
// END_MP4_PHOTOGRAPHY_HOOKS
VoidMethod mp4_presenter_update_original;
struct Mp4RenderContext { void *pointer; };
static_assert(sizeof(Mp4RenderContext)==8,"Original ScriptableRenderContext ARM64 ABI differs");
using Mp4CapturePass=void(*)(void*,Mp4RenderContext,void*,Method*);
using Mp4EndCamera=void(*)(Mp4RenderContext,void*,Method*);
Mp4CapturePass mp4_capture_pass_original;
Mp4EndCamera mp4_end_camera_original;
void mp4_presenter_update_hook(void *self,Method *method) {
    mp4_presenter_update_original(self,method);
    if(!ready.load(std::memory_order_acquire)||!game_call(true)||!mp4_prepare_runtime())return;
    idoly_mp4_runtime::observe_presenter(self);
    if(void *controller=mp4_selected_controller(self))idoly_mp4_runtime::observe_camera_controller(controller);
}
void mp4_capture_pass_hook(void *self,Mp4RenderContext context,void *data,Method *method) {
    mp4_capture_pass_original(self,context,data,method);
    if(ready.load(std::memory_order_acquire)&&game_call()&&mp4_api_installed)
        idoly_mp4_runtime::capture_pass_did_execute(self,data);
}
void mp4_end_camera_hook(Mp4RenderContext context,void *camera,Method *method) {
    mp4_end_camera_original(context,camera,method);
    if(ready.load(std::memory_order_acquire)&&game_call()&&mp4_api_installed)
        idoly_mp4_runtime::camera_did_render(camera);
}

// BEGIN_MP4_OWNED_CLOCK_HOOKS
using Mp4GraphMode=void(*)(mp4game::PlayableGraph*,int32_t,Method*);
Mp4GraphMode mp4_graph_mode_original;
void mp4_graph_mode_hook(mp4game::PlayableGraph* graph,int32_t mode,Method* method){
    mp4_graph_mode_original(graph,mode,method);
    if(!graph)return;
    pthread_mutex_lock(&mp4_graph_mode_mutex);mp4_graph_modes.record(*graph,mode);pthread_mutex_unlock(&mp4_graph_mode_mutex);
}
bool mp4_recorded_graph_mode(const mp4game::PlayableGraph* graph,int32_t* mode){
    if(!graph)return false;
    if(mp4_actor_source_verified&&game_call()){
        if(!mp4_actor_range_count&&!mp4_actor_refresh_maps())return false;
        mp4actor::Handle handle{};std::memcpy(&handle,graph,sizeof(handle));
        return mp4_actor_graph_mode(&handle,mode);
    }
    pthread_mutex_lock(&mp4_graph_mode_mutex);const bool known=mp4_graph_modes.get(*graph,mode);pthread_mutex_unlock(&mp4_graph_mode_mutex);return known;
}
bool mp4_camera_clock_ok(){return mp4_camera_grant.ok();}
void mp4_owned_brain_manual_update(void* brain,mp4game::Method* method){
    if(mp4_owned_camera_scope){mp4_camera_grant.fail();return;}
    mp4_camera_grant.begin();
    ScopedValue<bool> scope(mp4_owned_camera_scope,true);
    using Manual=void(*)(void*,mp4game::Method*);
    reinterpret_cast<Manual>(image_base+mp4_profile.brain_manual_update.rva)(brain,method);
}
using Mp4BrainDelta=float(*)(void*,bool,Method*);
Mp4BrainDelta mp4_brain_delta_original;
float mp4_brain_delta_hook(void* brain,bool fixed,Method* method){
    float delta=0;
    if(ready.load(std::memory_order_acquire)&&game_call()&&mp4_api_installed
        &&idoly_mp4_runtime::camera_delta_override(brain,&delta))return delta;
    return mp4_brain_delta_original(brain,fixed,method);
}
using Mp4CoreCamera=void(*)(void*,void*,Vec3,float,Method*);
Mp4CoreCamera mp4_core_camera_original;
void* mp4_camera_update_status(void* core,void* camera){
    if(!mp4_type_is(core,"Cinemachine.CinemachineCore"))return nullptr;
    void* dictionary=read<void*>(core,0x30);
    if(!mp4_type_is(dictionary,"System.Collections.Generic.Dictionary`2"))return nullptr;
    const void* method=font_method(object_class(dictionary),"TryGetValue",2);
    if(!method)return nullptr;
    using Lookup=bool(*)(void*,void*,void**,const void*);
    auto lookup=read<Lookup>(const_cast<void*>(method),0);
    if(reinterpret_cast<uintptr_t>(lookup)!=image_base+mp4_runtime_profile.camera_status_try_get.rva)return nullptr;
    void* status=nullptr;
    if(!lookup(dictionary,camera,&status,method)||!mp4_type_is(status,".UpdateStatus"))return nullptr;
    return status;
}
void mp4_core_camera_hook(void* core,void* camera,Vec3 up,float delta,Method* method){
    if(!mp4_owned_camera_scope||!game_call()){mp4_core_camera_original(core,camera,up,delta,method);return;}
    const auto visit=mp4_camera_grant.visit(camera);
    if(visit==mp4game::CameraGrant::Visit::duplicate)return;
    if(visit==mp4game::CameraGrant::Visit::failed){mp4_core_camera_original(core,camera,up,-1,method);return;}
    if(delta<0){mp4_core_camera_original(core,camera,up,delta,method);return;}
    void* status=mp4_camera_update_status(core,camera);
    if(!status){
        // A newly activated vcam has no cached status. Reset that original
        // camera once, then re-read its real dictionary entry before advancing.
        mp4_core_camera_original(core,camera,up,-1,method);
        status=mp4_camera_update_status(core,camera);
    }
    const int32_t frame=orientation_calls.frame_count(nullptr);
    int32_t previous=0;
    if(!status||(read<int32_t>(core,0x38)&~8)!=1
        ||!mp4game::CameraGrant::rebase_late_frame(frame,&previous)){
        mp4_camera_grant.fail();return;
    }
    write<int32_t>(status,0x10,previous);
    mp4_core_camera_original(core,camera,up,delta,method);
}
// END_MP4_OWNED_CLOCK_HOOKS
// END_MP4_ORIGINAL_GAME_BOUNDARY

void update_camera_metrics(void *camera) {
    if (!camera) return;
    ProjectionMatrix matrix{}; Frustum frustum{};
    projection_get(camera, &matrix, nullptr);
    const float aspect = aspect_get_original(camera, nullptr);
    const float fov = perspective_frustum(matrix, &frustum) ? frustum_vertical_fov(frustum) : 0;
    pthread_mutex_lock(&status_mutex);
    state.aspect = aspect;
    state.fov = fov;
    state.base_fov = photo.base_known ? frustum_vertical_fov(photo.original_frustum) : state.fov;
    pthread_mutex_unlock(&status_mutex);
}
// BEGIN_VERIFIED_PROJECTION_REFRESH
bool projection_model_unchanged(void *camera) {
    if (physical_get(camera, nullptr) != photo.physical || projection_mode_get(camera, nullptr) != photo.projection_mode)
        return false;
    if (!photo.physical) return true;
    Vec2 sensor{}, lens{}; sensor_get(camera, &sensor, nullptr); lens_get(camera, &lens, nullptr);
    return gate_get(camera, nullptr) == photo.gate && std::isfinite(sensor.x) && std::isfinite(sensor.y)
        && std::isfinite(lens.x) && std::isfinite(lens.y)
        && std::fabs(sensor.x - photo.sensor.x) < .0001f && std::fabs(sensor.y - photo.sensor.y) < .0001f
        && std::fabs(lens.x - photo.lens.x) < .0001f && std::fabs(lens.y - photo.lens.y) < .0001f;
}
bool remember_projection_model(void *camera) {
    photo.physical = physical_get(camera, nullptr);
    photo.projection_mode = projection_mode_get(camera, nullptr);
    photo.gate = gate_get(camera, nullptr);
    sensor_get(camera, &photo.sensor, nullptr); lens_get(camera, &photo.lens, nullptr);
    return !photo.physical || (std::isfinite(photo.sensor.x) && photo.sensor.x > 0
        && std::isfinite(photo.sensor.y) && photo.sensor.y > 0
        && std::isfinite(photo.lens.x) && std::isfinite(photo.lens.y));
}
void reset_automatic_aspect(void *camera) { camera_aspect_reset(camera, nullptr); }
bool refresh_original_projection(void *camera, float target_aspect) {
    const float original_aspect = photo.ratio.x / photo.ratio.y;
    if (!camera_aspect_set_original || !camera_aspect_reset
            || !std::isfinite(original_aspect) || original_aspect <= 0 || original_aspect > 32
            || std::fabs(aspect_get_original(camera, nullptr) - target_aspect) > .0001f) return false;
    ScopedValue<bool> internal(internal_camera, true);
    // A new Cinemachine gate/sensor/shift must not cause a visible 16:9 RT
    // rebuild. Borrow the old projection ratio only during this synchronous
    // measurement, then restore the camera's proven automatic RT aspect.
    if (physical_get(camera, nullptr)) focal_set_original(camera, photo.original_focal, nullptr);
    else fov_set_original(camera, photo.original.vertical_fov, nullptr);
    ProjectionMatrix matrix{};
    {
        ScopedCleanup automatic(reset_automatic_aspect, camera);
        camera_aspect_set_original(camera, original_aspect, nullptr);
        projection_get(camera, &matrix, nullptr);
    }
    Frustum measured{};
    const float raw_fov = fov_get_original(camera, nullptr), focal = focal_get_original(camera, nullptr);
    if (std::fabs(aspect_get_original(camera, nullptr) - target_aspect) > .0001f
            || !perspective_frustum(matrix, &measured)
            || std::fabs(frustum_aspect(measured) - original_aspect) > .005f
            || !std::isfinite(raw_fov) || raw_fov <= 0 || raw_fov >= 179
            || !std::isfinite(focal) || focal <= 0 || !remember_projection_model(camera)) return false;
    photo.original_frustum = measured;
    photo.original.aspect = original_aspect;
    photo.original.vertical_fov = raw_fov;
    photo.original_focal = focal;
    return true;
}
void restore_base_lens(void *camera) {
    // Retain the exact focal length for physical lenses. Reconstructing it
    // from an already expanded fieldOfView would feed the override back into
    // Cinemachine's next frame.
    if (photo.physical) focal_set_original(camera, photo.original_focal, nullptr);
    else fov_set_original(camera, photo.original.vertical_fov, nullptr);
}
bool set_expanded_camera(void *camera) {
    void *controller = photo.controller.get(true);
    void *texture = controller ? target_to_texture(rt_target(controller, nullptr), nullptr) : nullptr;
    if (!runtime_type(texture, "RenderTexture")) return false;
    const Dimensions rendered{rt_width(texture, nullptr), rt_height(texture, nullptr)};
    if (!photo.base_known || !dimensions_valid(rendered)) return false;
    const float expected_aspect = static_cast<float>(rendered.width) / rendered.height;
    if (!projection_model_unchanged(camera)
            && !refresh_original_projection(camera, expected_aspect)) return false;
    // TargetTexture must drive the original automatic camera aspect. Setting
    // Camera.aspect ourselves would switch it to manual mode and could leak
    // the photo ratio into a later scene. Manual/custom viewports fail closed.
    Rect actual_rect{}; camera_rect_get(camera, &actual_rect, nullptr);
    if (std::fabs(aspect_get_original(camera, nullptr) - expected_aspect) > .0001f || !full_rect(actual_rect)) return false;
    ScopedValue<bool> internal(internal_camera, true);
    // Remember the first write even if the following readback fails, so the
    // caller's rollback can restore the saved lens instead of losing it.
    photo.expanded = true;
    restore_base_lens(camera);
    ProjectionMatrix matrix{}; Frustum fitted{};
    projection_get(camera, &matrix, nullptr);
    float desired = 0;
    if (!perspective_frustum(matrix, &fitted)
            || !expanded_raw_fov(photo.original_frustum, fitted, photo.original.vertical_fov, &desired)) return false;
    fov_set_original(camera, desired, nullptr);
    projection_get(camera, &matrix, nullptr);
    // A raw lens getter can read back our value while a physical-camera
    // focalLength or a custom projection still renders the old cropped view.
    // Acknowledge only the actual four projection edges and matching aspect.
    if (std::fabs(aspect_get_original(camera, nullptr) - expected_aspect) > .0001f
            || !perspective_frustum(matrix, &fitted) || !frustum_contains(fitted, photo.original_frustum)
            || std::fabs(frustum_aspect(fitted) - expected_aspect) > .005f) return false;
    update_camera_metrics(camera);
    return true;
}
// END_VERIFIED_PROJECTION_REFRESH
void restore_camera() {
    void *camera = photo.camera.get(true);
    if (photo.expanded && camera && photo.base_known) {
        ScopedValue<bool> internal(internal_camera, true);
        restore_base_lens(camera);
        update_camera_metrics(camera);
    }
    photo.expanded = false;
}
void acknowledge_resolution(void *controller, const ResolutionAttempt &attempt) {
    if (!attempt.computed || !dimensions_valid(attempt.expected)) return;
    void *texture = target_to_texture(rt_target(controller, nullptr), nullptr);
    if (!runtime_type(texture, "RenderTexture")) return;
    Dimensions actual{rt_width(texture, nullptr), rt_height(texture, nullptr)};
    if (actual.width != attempt.expected.width || actual.height != attempt.expected.height) return;
    resolution_revision = attempt.config.revision;
    rendered_configuration = attempt.config; rendered_configuration_known = true;
    rendered_dimensions = actual;
    rendered_screen_width = attempt.width; rendered_screen_height = attempt.height;
    pthread_mutex_lock(&status_mutex);
    state.render_w = actual.width; state.render_h = actual.height;
    pthread_mutex_unlock(&status_mutex);
}
void rebuild(void *controller) {
    if(mp4_output_geometry_owned(controller))return;
    // Only entered by game callbacks. Keep capture/explicit-size calls out.
#ifndef IDOLY_DARWIN_BRIDGE
    // Surface replacement while folding or resizing can briefly report no
    // drawable window. Keep the current target until a valid frame retries.
    if (!screen_width || !screen_height || screen_width(nullptr)<=0 || screen_height(nullptr)<=0) return;
#endif
    ResolutionAttempt attempt;
    ScopedValue<void *> scope(resolution_scope, controller);
    ScopedValue<ResolutionAttempt *> attempt_scope(resolution_attempt, &attempt);
    ScopedMemory<bool> dynamic(controller, 0x30, configuration().custom_graphics);
    dynamic.set(false);
    rt_destroy(controller, nullptr);
    rt_original(controller, -1, -1, false, nullptr);
    acknowledge_resolution(controller, attempt);
}
bool same(Vec2 a, Vec2 b) { return std::fabs(a.x - b.x) < .001f && std::fabs(a.y - b.y) < .001f; }
bool same(Vec3 a, Vec3 b) { return std::fabs(a.x - b.x) < .001f && std::fabs(a.y - b.y) < .001f && std::fabs(a.z - b.z) < .001f; }
void restore_image_layouts() {
    for (auto &layout : image_layouts) {
        void *rect = layout.rect.get(true);
        if (rect && layout.saved && layout.changed) {
            Vec2 delta{}; Vec3 position{};
            size_delta_get(rect, &delta, nullptr); local_position(rect, &position, nullptr);
            // A later original-game write takes precedence over our saved
            // baseline. Restore only properties still carrying our override.
            const bool own_delta = same(delta, layout.written_delta);
            const Vec3 restored_position = same(position, layout.written_position) ? layout.original_position : position;
            if (own_delta) size_delta_set(rect, &layout.original_delta, nullptr);
            local_position_set(rect, &restored_position, nullptr);
        }
        layout.rect.clear(); layout.saved = layout.changed = false;
    }
}
void capture_original_image_frame(void *rect, void *parent) {
    photo.original_image_frame_known = false;
    if (!rect_transform(rect) || !rect_transform(parent)) return;
    Vec2 delta{}; Vec3 position{}, scale{}; Quaternion rotation{}; Rect drawn{};
    size_delta_get(rect, &delta, nullptr); local_position(rect, &position, nullptr);
    local_scale(rect, &scale, nullptr); local_rotation(rect, &rotation, nullptr);
    transform_rect_get(rect, &drawn, nullptr);
    if (!plain_transform(position, scale, rotation)) return;
    Vec2 baseline_delta = delta;
    Vec3 baseline_position = position;
    for (const auto &layout : image_layouts) {
        if (layout.saved && layout.changed && layout.rect.get(true) == rect) {
            if (same(delta, layout.written_delta)) baseline_delta = layout.original_delta;
            if (same(position, layout.written_position)) baseline_position = layout.original_position;
            break;
        }
    }
    photo.original_image_frame_known = baseline_image_bounds(drawn, delta, baseline_delta,
        baseline_position, &photo.original_image_frame);
    if (photo.original_image_frame_known) photo.viewport_parent.set(parent);
}
bool fill_image_parent(void *rect, Rect available) {
    ImageLayout *selected = nullptr;
    for (auto &layout : image_layouts) {
        void *saved = layout.rect.get(true);
        if (saved == rect) { selected = &layout; break; }
        if (!saved && !selected) selected = &layout;
    }
    if (!selected) return false;
    ImageLayout &layout = *selected;
    Vec2 delta{}; Vec3 position{}, scale{}; Quaternion rotation{}; Rect drawn{};
    size_delta_get(rect, &delta, nullptr); local_position(rect, &position, nullptr);
    local_scale(rect, &scale, nullptr); local_rotation(rect, &rotation, nullptr);
    if (!plain_transform(position, scale, rotation)) return false;
    transform_rect_get(rect, &drawn, nullptr);
    if (!layout.saved || layout.rect.get(true) != rect) {
        layout.rect.set(rect); layout.saved = true; layout.changed = false;
        layout.original_delta = layout.written_delta = delta;
        layout.original_position = layout.written_position = position;
    } else if (layout.changed) {
        if (!same(delta, layout.written_delta)) layout.original_delta = delta;
        if (!same(position, layout.written_position)) layout.original_position = position;
    }
    Vec2 desired_delta{};
    if (!fill_size_delta(available, drawn, delta, &desired_delta)) return false;
    layout.changed = true; layout.written_delta = desired_delta;
    if (!same(delta, desired_delta)) size_delta_set(rect, &desired_delta, nullptr);
    size_delta_get(rect, &delta, nullptr);
    if (!same(delta, desired_delta)) return false;
    transform_rect_get(rect, &drawn, nullptr);
    Vec3 desired_position{};
    if (!center_position(available, drawn, position, &desired_position)) return false;
    layout.written_position = desired_position;
    if (!same(position, desired_position)) local_position_set(rect, &desired_position, nullptr);
    return true;
}
void restore_photography(bool rebuild_target) {
    panorama_ui.restore_layout();
    restore_image_layouts();
    void *controller = photo.controller.get(true);
    if (controller) {
        write(controller, 0x28, photo.ratio);
        if (rebuild_target) rebuild(controller);
    }
    restore_camera();
    photo.geometry_known = false;
    photo.base_known = false;
    photo.target_expanded = false; photo.geometry_confirmed = false; photo.layout_ticks = 0;
    photo.original_image_frame_known = false;
}
// BEGIN_PROJECTION_REJECTION_RETRY
void clear_projection_rejection() {
    photo.rejected_revision = -1; photo.rejected_viewport = {};
}
void clear_photography() {
    restore_photography(false);
    panorama_ui.restore();
    photo.owner.clear(); photo.controller.clear(); photo.camera.clear(); photo.image.clear();
    photo.viewport_parent.clear();
    photo.active = false; photo.base_known = false; photo.geometry_known = false;
    photo.viewport = {}; photo.built_viewport = {};
    clear_projection_rejection();
}
bool synchronize_photo_camera(void *controller, void *camera) {
    if (!controller) return false;
    void *next = rt_camera(controller, nullptr);
    if (!next || !object_alive(next, nullptr)) {
        // During teardown the managed wrapper may outlive its Unity camera.
        // Never turn that transient dead wrapper into a per-frame RT reset.
        if (photo.expanded || photo.target_expanded) restore_photography(false);
        // Even the same live camera may later be reattached to this controller.
        // Its first valid attachment then needs one original-target baseline.
        photo.camera.clear(); photo.built_viewport = {};
        return true;
    }
    if (next == camera) return false;
    // A genuinely new camera needs an original-ratio target for its first
    // baseline. Do this once before replacing the saved weak camera; otherwise
    // a still-wide RT can be mistaken for the new original lens forever.
    restore_photography(true);
    next = rt_camera(controller, nullptr);
    photo.camera.set(next && object_alive(next, nullptr) ? next : nullptr);
    photo.built_viewport = {};
    clear_projection_rejection();
    return true;
}
bool projection_rejected_for(const Config &config) {
    return photo.rejected_revision == config.revision && photo.rejected_viewport.width == photo.viewport.width
        && photo.rejected_viewport.height == photo.viewport.height;
}
void reject_current_projection() {
    const Config config = configuration();
    const Dimensions rejected = photo.viewport;
    restore_photography(true);
    // A projection that cannot be safely re-measured must not repeatedly
    // allocate a 16:9 target then expand it on the next frame. Retry only for
    // a new settings revision or a genuinely different viewport.
    photo.rejected_revision = config.revision;
    photo.rejected_viewport = rejected;
    pthread_mutex_lock(&status_mutex); state.state = "unsupported"; state.expanded = false; pthread_mutex_unlock(&status_mutex);
}
// END_PROJECTION_REJECTION_RETRY

bool image_fills_parent(void *rect, Rect available) {
    Rect drawn{}; transform_rect_get(rect, &drawn, nullptr);
    Vec3 position{}, scale{}; Quaternion rotation{};
    local_position(rect, &position, nullptr); local_scale(rect, &scale, nullptr);
    local_rotation(rect, &rotation, nullptr);
    return fills_parent(available, drawn, position, scale, rotation);
}
void observe_image(void *self, void *texture) {
    if (photo.image.get(true) == self) photo.geometry_known = false;
    if (!photo.active || !object_alive(self, nullptr) || !active_enabled(self, nullptr) || read<int>(self, 0x20) != 0) return;
    void *controller = photo.controller.get(true);
    if (!controller || !texture || texture != target_to_texture(rt_target(controller, nullptr), nullptr)) return;
    void *rect = target_rect(self, nullptr);
    if (!rect_transform(rect)) return;
    void *parent = parent_get(rect, nullptr);
    if (!rect_transform(parent)) return;
    Rect available{}; transform_rect_get(parent, &available, nullptr);
    if (!std::isfinite(available.width) || !std::isfinite(available.height)
            || available.width < 1 || available.height < 1 || available.width > 32768 || available.height > 32768) return;
    void *raw_image = read<void *>(self, 0x28);
    if (!raw_image || !object_alive(raw_image, nullptr) || !active_enabled(raw_image, nullptr)
            || !full_rect(uv_get(raw_image, nullptr))) return;
    // Read the unfitted parent, not the existing 16:9 fitted image or the
    // entire Screen. A portrait UI can contain a landscape render surface.
    Dimensions dimensions{static_cast<int>(std::lround(available.width)), static_cast<int>(std::lround(available.height))};
    void *previous_image = photo.image.get(true);
    if (previous_image && previous_image != self && photo.geometry_known
            && static_cast<int64_t>(dimensions.width) * dimensions.height
                < static_cast<int64_t>(photo.viewport.width) * photo.viewport.height) return;
    photo.viewport = dimensions; photo.viewport_rect = available;
    photo.image.set(self); photo.geometry_known = dimensions_valid(photo.viewport);
    capture_original_image_frame(rect, parent);
}

void update_panorama_ui() {
#ifdef IDOLY_DARWIN_BRIDGE
    if (!desktop_enabled() || !game_call()) return;
#else
    if (!ready.load(std::memory_order_acquire) || !game_call()) return;
#endif
    void *owner = photo.active ? photo.owner.get(true) : nullptr;
    if (!owner || !class_matches(owner, "Solis.Photography", "Photography360LiveContentPresenter")) {
        panorama_ui.restore(); return;
    }
    panorama_ui.begin_session(owner);
    if (!configuration().expand_photography || !photo.expanded || !photo.geometry_confirmed
            || !photo.original_image_frame_known) { panorama_ui.restore_layout(); return; }
    panorama_ui.update(owner, photo.viewport_parent.get(true), photo.viewport_rect, photo.original_image_frame);
}

uint64_t limited_hook(int width, int height, Vec2 ratio, int max_pixel, float scale, bool first, Method *method) {
    if (!ready.load(std::memory_order_acquire) || !resolution_scope || !first || !game_call())
        return limited_original(width, height, ratio, max_pixel, scale, first, method);
    Config config = configuration();
    uint64_t bits = limited_original(width, height, ratio, config.custom_graphics ? 0 : max_pixel,
                                    config.custom_graphics ? 1.f : scale, first, method);
    Dimensions original{static_cast<int32_t>(bits), static_cast<int32_t>(bits >> 32)};
    Dimensions result = config.custom_graphics
        ? scaled_dimensions(original, config.render_scale, config.max_buffer_pixel) : original;
    if (resolution_attempt && dimensions_valid(result))
        *resolution_attempt = {true, result, config, width, height};
    return static_cast<uint32_t>(result.width) | (static_cast<uint64_t>(static_cast<uint32_t>(result.height)) << 32);
}
void rt_hook(void *self, int width, int height, bool alpha, Method *method) {
    if (!ready.load(std::memory_order_acquire) || !self || !game_call()) {
        rt_original(self, width, height, alpha, method); return;
    }
    void *camera = rt_camera(self, nullptr);
    if (camera && object_alive(camera, nullptr)) remember_controller(self);
    auto observe_after=[self](){
        if(!mp4_type_is(self,"VL.Rendering.VLSRPCameraController")||!mp4_alive(self))return;
        void* updated=rt_camera(self,nullptr);
        if(updated&&object_alive(updated,nullptr))remember_controller(self);
    };
    if(mp4_output_geometry_owned(self)){
        Mp4DynamicTargetScope dynamic(self);
        rt_original(self,mp4_geometry_width,mp4_geometry_height,alpha,method);
        if(dynamic.finish())observe_after();
        return;
    }
    // A selected MV can create its original target with explicit dimensions.
    // Observe that owner too, while preserving the original explicit-size
    // call. Export selection still requires the timeline's bound output camera
    // to match this controller; arbitrary remembered cameras are ineligible.
    if (width > 0 && height > 0) {
        rt_original(self, width, height, alpha, method);observe_after();return;
    }
    Config config = configuration();
    bool primary = camera && object_alive(camera, nullptr) && (main_controller.get(true) == self || scene_enter);
    if (!primary) { rt_original(self, width, height, alpha, method);observe_after();return; }
    main_controller.set(self);
    if (scene_enter && !scene_exit) {
        void *previous_controller = photo.controller.get(true), *previous_camera = photo.camera.get(true);
        const bool changed = previous_controller != self || previous_camera != camera;
        if ((previous_controller && previous_controller != self) || (previous_camera && previous_camera != camera))
            restore_photography(false);
        if (changed) clear_projection_rejection();
        photo.controller.set(self); photo.camera.set(camera); photo.ratio = read<Vec2>(self, 0x28);
        photo.base_known = false;
    }
    ResolutionAttempt attempt;
    ScopedMemory<bool> dynamic(self, 0x30, config.custom_graphics); dynamic.set(false);
    ScopedValue<void *> scope(resolution_scope, self);
    ScopedValue<ResolutionAttempt *> attempt_scope(resolution_attempt, &attempt);
    rt_original(self, width, height, alpha, method);
    observe_after();
    acknowledge_resolution(self, attempt);
}
void target_update_hook(void *self, void *texture, Method *method) {
    target_update_original(self, texture, method);
    if (ready.load(std::memory_order_acquire) && game_call()) {
        RectTypeMemoScope type_memo;
        identify_main_target(self, texture); observe_image(self, texture);
    }
}
void target_late_hook(void *self, Method *method) {
    target_late_original(self, method);
    if (ready.load(std::memory_order_acquire) && game_call()) {
        RectTypeMemoScope type_memo;
        void *texture = target_current(self, nullptr);
        identify_main_target(self, texture); observe_image(self, texture);
        // Original scene layout writes may happen after QualityManager.Update.
        // Keep each visible original image fitted after its own LateUpdate,
        // but never enlarge a still-original 16:9 texture before the camera
        // and target have actually switched to this parent's ratio.
        Config config = configuration();
        if (config.expand_photography && photo.expanded && photo.geometry_known
                && photo.image.get(true) == self && !read<bool>(self, 0x24)
                && runtime_type(texture, "RenderTexture")) {
            const Dimensions rendered{rt_width(texture, nullptr), rt_height(texture, nullptr)};
            const float expected = static_cast<float>(photo.viewport.width) / photo.viewport.height;
            if (dimensions_valid(rendered) && std::fabs(static_cast<float>(rendered.width) / rendered.height - expected) < .005f
                    && !fill_image_parent(target_rect(self, nullptr), photo.viewport_rect)) {
                const Dimensions rejected = photo.viewport;
                restore_photography(true);
                photo.rejected_revision = config.revision; photo.rejected_viewport = rejected;
                pthread_mutex_lock(&status_mutex); state.state = "unsupported"; state.expanded = false; pthread_mutex_unlock(&status_mutex);
            }
        }
        update_panorama_ui();
    }
}

void photo_update(void *self, Method *method, VoidMethod original) {
    if (!ready.load(std::memory_order_acquire) || !game_call(true)) { original(self, method); return; }
    if (photo.owner.get() != self) clear_photography();
    else restore_photography(false); // Same target keeps a failed-projection cache across ordinary render updates.
    photo.owner.set(self); photo.active = true;
    ScopedValue<bool> enter(scene_enter, true); original(self, method);
}
void photo_reset(void *self, Method *method, VoidMethod original) {
    if (ready.load(std::memory_order_acquire) && game_call(true) && photo.owner.get() == self) {
        clear_photography(); ScopedValue<bool> exit(scene_exit, true); original(self, method);
    } else original(self, method);
}
void main_update_hook(void *self, Method *method) { photo_update(self, method, scene_main_update_original); }
void pano_update_hook(void *self, Method *method) {
    photo_update(self, method, scene_pano_update_original);
    if (ready.load(std::memory_order_acquire) && game_call()) update_panorama_ui();
}
void main_reset_hook(void *self, Method *method) { photo_reset(self, method, scene_main_reset_original); }
void pano_reset_hook(void *self, Method *method) { photo_reset(self, method, scene_pano_reset_original); }
bool remember_original_lens(void *camera) {
    const float raw_fov = fov_get_original(camera, nullptr), focal = focal_get_original(camera, nullptr);
    Frustum updated{};
    if (!rescale_frustum(photo.original_frustum, photo.original.vertical_fov, raw_fov, &updated)
            || !std::isfinite(focal) || focal <= 0) return false;
    photo.original.vertical_fov = raw_fov;
    photo.original_focal = focal;
    photo.original_frustum = updated;
    return true;
}
float fov_get_hook(void *camera, Method *method) {
    if (ready.load(std::memory_order_acquire) && game_call() && !internal_camera
            && mp4_output_projection_owned(camera)) return mp4_projection.base_fov;
    if (ready.load(std::memory_order_acquire) && game_call() && photo.expanded
            && photo.camera.get(true) == camera && !internal_camera) return photo.original.vertical_fov;
    return fov_get_original(camera, method);
}
void fov_set_hook(void *camera, float value, Method *method) {
    if (ready.load(std::memory_order_acquire) && game_call() && !internal_camera
            && mp4_output_projection_owned(camera) && value > 0 && value < 179 && std::isfinite(value)) {
        ScopedValue<bool> internal(internal_camera, true);
        fov_set_original(camera, value, method);
        mp4_projection.base_fov = fov_get_original(camera, nullptr);
        if (physical_get(camera, nullptr)) mp4_projection.base_focal = focal_get_original(camera, nullptr);
        mp4_projection.required_known = false;
        return;
    }
    if (ready.load(std::memory_order_acquire) && game_call() && photo.expanded
            && photo.camera.get(true) == camera && !internal_camera && value > 0 && value < 179 && std::isfinite(value)) {
        // Observe the original setter's actual clamping/physical conversion
        // before deriving a fresh baseline; never scale a previous override.
        ScopedValue<bool> internal(internal_camera, true);
        fov_set_original(camera, value, method);
        if (!remember_original_lens(camera) || !set_expanded_camera(camera)) reject_current_projection();
        return;
    }
    fov_set_original(camera, value, method);
}
float focal_get_hook(void *camera, Method *method) {
    if (ready.load(std::memory_order_acquire) && game_call() && !internal_camera
            && mp4_output_projection_owned(camera)) return mp4_projection.base_focal;
    if (ready.load(std::memory_order_acquire) && game_call() && photo.expanded
            && photo.camera.get(true) == camera && !internal_camera) return photo.original_focal;
    return focal_get_original(camera, method);
}
void focal_set_hook(void *camera, float value, Method *method) {
    if (ready.load(std::memory_order_acquire) && game_call() && !internal_camera
            && mp4_output_projection_owned(camera) && value > 0 && std::isfinite(value)) {
        ScopedValue<bool> internal(internal_camera, true);
        focal_set_original(camera, value, method);
        mp4_projection.base_focal = focal_get_original(camera, nullptr);
        if (physical_get(camera, nullptr)) mp4_projection.base_fov = fov_get_original(camera, nullptr);
        mp4_projection.required_known = false;
        return;
    }
    if (ready.load(std::memory_order_acquire) && game_call() && photo.expanded
            && photo.camera.get(true) == camera && !internal_camera && value > 0 && std::isfinite(value)) {
        // Cinemachine's physical branch writes focalLength in LateUpdate and
        // never calls Camera.set_fieldOfView. Reapply after that exact write.
        ScopedValue<bool> internal(internal_camera, true);
        focal_set_original(camera, value, method);
        if (!remember_original_lens(camera) || !set_expanded_camera(camera)) reject_current_projection();
        return;
    }
    focal_set_original(camera, value, method);
}
bool apply_photography(Config config) {
    geometry_unsupported = false;
    // The export owns this exact camera's framing until it restores the RT
    // and lens. Keep the surrounding photo state for the ordinary view.
    if (mp4_output_geometry_owned(photo.controller.get(true))) return true;
    if (!photo.active || !photo.owner.get()) {
        if (photo.active) clear_photography();
        return !config.expand_photography;
    }
    if (!config.expand_photography) {
        if (photo.expanded || photo.target_expanded) restore_photography(true);
        clear_projection_rejection();
        return true;
    }
    void *image = photo.image.get(true);
    if (image) observe_image(image, target_current(image, nullptr));
    else photo.geometry_known = false;
    void *controller = photo.controller.get(true), *camera = photo.camera.get(true);
    if (synchronize_photo_camera(controller, camera)) return false;
    if (!controller || !camera || !photo.geometry_known || orthographic(camera, nullptr)) {
        if (photo.expanded || photo.target_expanded) restore_photography(true);
        return false;
    }
    if (projection_rejected_for(config)) { geometry_unsupported = true; return false; }
    if (!photo.base_known) {
        ProjectionMatrix matrix{};
        projection_get(camera, &matrix, nullptr);
        if (!perspective_frustum(matrix, &photo.original_frustum)) { geometry_unsupported = true; return false; }
        photo.original.aspect = frustum_aspect(photo.original_frustum);
        photo.original.vertical_fov = fov_get_original(camera, nullptr);
        photo.original_focal = focal_get_original(camera, nullptr);
        if (!remember_projection_model(camera)) return false;
        camera_rect_get(camera, &photo.original.rect, nullptr);
        if (!camera_valid(photo.original) || !full_rect(photo.original.rect)
                || !std::isfinite(photo.original_focal) || photo.original_focal <= 0
                || std::fabs(photo.original.aspect - photo.ratio.x / photo.ratio.y) > .005f) return false;
        photo.base_known = true;
    }
    const float available_aspect = static_cast<float>(photo.viewport.width) / photo.viewport.height;
    const int width = screen_width(nullptr), height = screen_height(nullptr);
    const float window_aspect = width > 0 && height > 0 ? static_cast<float>(width > height ? width : height) / (width > height ? height : width) : 0;
    if (std::fabs(available_aspect - 16.f / 9.f) < .005f && window_aspect > 0
            && std::fabs(window_aspect - 16.f / 9.f) > .02f) {
        // A fixed 16:9 parent on a non-16:9 window is not proof of the true
        // scene viewport. Never guess a larger ancestor or ACK expansion.
        if (photo.expanded || photo.target_expanded) restore_photography(true);
        geometry_unsupported = true; return false;
    }
    CameraState plan;
    if (!expansion_plan(photo.original, photo.viewport, &plan)) { geometry_unsupported = true; return false; }
    if (photo.built_viewport.width != photo.viewport.width || photo.built_viewport.height != photo.viewport.height || !photo.expanded) {
        photo.target_expanded = true; photo.geometry_confirmed = false; photo.layout_ticks = 0;
        write(controller, 0x28, Vec2{static_cast<float>(photo.viewport.width), static_cast<float>(photo.viewport.height)});
        rebuild(controller); photo.built_viewport = photo.viewport;
    }
    if (!set_expanded_camera(camera)) {
        const Dimensions rejected = photo.viewport;
        restore_photography(true);
        photo.rejected_revision = config.revision; photo.rejected_viewport = rejected;
        geometry_unsupported = true; return false;
    }
    // An existing fitter or an already stretched original target must display
    // the full parent. Never ACK a stretched texture or UV-cropped image.
    image = photo.image.get(true);
    if (!image) { restore_photography(true); return false; }
    void *rect = target_rect(image, nullptr);
    // The original horizontal target is fixed 1920x1080, with its fitter
    // disabled. Resize only this main-target image within its verified direct
    // parent; anchors/pivot/rotation/UVs remain untouched. Keep bounded slots
    // because horizontal and vertical images can alternate during rotation.
    if (!read<bool>(image, 0x24) && !fill_image_parent(rect, photo.viewport_rect)) {
        const Dimensions rejected = photo.viewport;
        restore_photography(true);
        photo.rejected_revision = config.revision; photo.rejected_viewport = rejected;
        geometry_unsupported = true; return false;
    }
    Rect drawn{}; transform_rect_get(rect, &drawn, nullptr);
    void *texture = target_current(image, nullptr);
    if (!runtime_type(texture, "RenderTexture")) { restore_photography(true); return false; }
    const Dimensions actual{rt_width(texture, nullptr), rt_height(texture, nullptr)};
    if (!dimensions_valid(actual)) { restore_photography(true); return false; }
    const float target_aspect = static_cast<float>(photo.viewport.width) / photo.viewport.height;
    const bool verified = drawn.height > 0 && std::fabs(drawn.width / drawn.height - target_aspect) < .005f
        && std::fabs(static_cast<float>(actual.width) / actual.height - target_aspect) < .005f
        && image_fills_parent(rect, photo.viewport_rect);
    if (verified) { photo.geometry_confirmed = true; photo.layout_ticks = 0; return true; }
    // Unity's existing fitter may finish in LateUpdate/layout after this
    // Update. Permit that short transition without ACK, then fail closed.
    if (!photo.geometry_confirmed && ++photo.layout_ticks < 4) return false;
    const Dimensions rejected = photo.viewport;
    restore_photography(true);
    photo.rejected_revision = config.revision; photo.rejected_viewport = rejected;
    geometry_unsupported = true; return false;
}

void quality_track(void *self) {
    if (quality_manager.get() == self) return;
    quality_manager.set(self); base_quality = read<int>(self, 0x24);
    applied_quality = 0;
}
int original_fps() {
    uint64_t value = application_fps_baseline.load(std::memory_order_acquire);
    if (!(value & FPS_KNOWN)) {
        const uint64_t initial = FPS_KNOWN | static_cast<uint32_t>(app_fps_get(nullptr));
        uint64_t expected = 0;
        application_fps_baseline.compare_exchange_strong(expected, initial, std::memory_order_acq_rel);
        value = application_fps_baseline.load(std::memory_order_acquire);
    }
    return static_cast<int32_t>(value);
}
void quality_set_hook(void *self, int value, Method *method) {
    if (!ready.load(std::memory_order_acquire) || !game_call()) { quality_set_original(self, value, method); return; }
    quality_track(self); base_quality = value;
    Config config = configuration();
    int desired = config.custom_graphics && config.quality ? config.quality : value;
    if (desired == 100) {
        void *names = quality_names(nullptr);
        const uintptr_t count = names ? read<uintptr_t>(names, 0x18) : 0;
        if (!count || count > 1024) desired = value;
    }
    quality_set_original(self, desired, method);
    applied_quality = desired != value ? desired : 0;
}
void quality_apply_hook(void *self, Method *method) {
    Config config = configuration();
    int valid = 0; bool changed = false;
    if (ready.load(std::memory_order_acquire) && game_call() && config.custom_graphics && config.quality == 100) {
        void *names = quality_names(nullptr);
        uintptr_t count = names ? read<uintptr_t>(names, 0x18) : 0;
        if (count > 0 && count <= 1024) {
            const int saved = read<int>(self, 0x8c);
            valid = saved < 0 ? 0 : saved >= static_cast<int>(count) ? static_cast<int>(count) - 1 : saved;
            changed = true;
        }
    }
    ScopedMemory<int> level(self, 0x8c, changed); level.set(valid);
    quality_apply_original(self, method);
}
void quality_init_hook(void *self, Method *method) {
    quality_init_original(self, method);
    if (ready.load(std::memory_order_acquire) && game_call(true)) quality_track(self);
}
void quality_update_hook(void *self, Method *method) {
    if (!ready.load(std::memory_order_acquire) || !game_call(true)) { quality_update_original(self, method); return; }
    bool has = false; Config config = configuration(&has);
    if (!has) {
        quality_update_original(self, method);
    sound_tracker.tick(true);
        mp4_unity_tick();
#ifndef IDOLY_DARWIN_BRIDGE
        sample_render_probe();
#endif
        return;
    }
    quality_track(self);
    int actual = read<int>(self, 0x24);
    if (applied_quality && actual != applied_quality) base_quality = actual;
    int desired = config.custom_graphics && config.quality ? config.quality : base_quality;
    bool quality_unavailable = false;
    if (desired == 100) {
        void *names = quality_names(nullptr);
        const uintptr_t count = names ? read<uintptr_t>(names, 0x18) : 0;
        if (!count || count > 1024) { desired = base_quality; quality_unavailable = true; }
    }
    if (desired != actual) quality_set_original(self, desired, nullptr);
    applied_quality = config.custom_graphics && config.quality ? desired : 0;
    const int desired_fps = selected_fps(config, original_fps());
    if (app_fps_get(nullptr) != desired_fps) app_fps_set_original(desired_fps, nullptr);
    quality_update_original(self, method);
    sound_tracker.tick(true);
#ifndef IDOLY_DARWIN_BRIDGE
    sample_render_probe();
#endif
    RectTypeMemoScope type_memo;
    const bool quality_readback = read<int>(self, 0x24)
        == (config.custom_graphics && config.quality && !quality_unavailable ? config.quality : base_quality);
    const bool fps_readback = app_fps_get(nullptr) == selected_fps(config, original_fps());
    const int width = screen_width(nullptr), height = screen_height(nullptr);
    pthread_mutex_lock(&status_mutex);
    state.screen_w = width; state.screen_h = height;
    pthread_mutex_unlock(&status_mutex);
    void *controller = main_controller.get(true);
    const bool rt_changed = !rendered_configuration_known
        || rendered_configuration.custom_graphics != config.custom_graphics
        || (config.custom_graphics && (rendered_configuration.render_scale != config.render_scale
            || rendered_configuration.max_buffer_pixel != config.max_buffer_pixel))
        || rendered_screen_width != width || rendered_screen_height != height;
    if (controller && rt_changed && (config.custom_graphics
            || (rendered_configuration_known && rendered_configuration.custom_graphics))) rebuild(controller);
    else if (controller && rendered_configuration_known) {
        void *texture = target_to_texture(rt_target(controller, nullptr), nullptr);
        resolution_revision = runtime_type(texture, "RenderTexture")
            && rt_width(texture, nullptr) == rendered_dimensions.width
            && rt_height(texture, nullptr) == rendered_dimensions.height ? config.revision : -1;
    } else if (!controller) resolution_revision = -1;
    const bool rt_restore_pending = controller && !config.custom_graphics
        && rendered_configuration_known && rendered_configuration.custom_graphics;
    const bool geometry = apply_photography(config);
    update_panorama_ui();
    const bool aa_pending = config.custom_graphics && config.aa_mode >= 0 && aa_revision != config.revision;
    const bool shadow_pending = config.custom_graphics && config.shadow_resolution && shadow_revision != config.revision;
    const bool unavailable = geometry_unsupported || quality_unavailable
        || (config.custom_graphics && config.aa_mode >= 0 && aa_revision == config.revision && aa_unavailable)
        || (config.custom_graphics && config.shadow_resolution && shadow_revision == config.revision && shadow_unavailable);
    pthread_mutex_lock(&status_mutex);
    state.expanded = !geometry_unsupported;
    if (unavailable) state.state = "unsupported";
    else if (!geometry || !quality_readback || !fps_readback || aa_pending || shadow_pending || rt_restore_pending
            || (config.custom_graphics && resolution_revision != config.revision)) state.state = "waiting_for_scene";
    else {
        state.revision = config.revision;
        state.state = config.custom_graphics || config.expand_photography ? "applied" : "disabled";
    }
    pthread_mutex_unlock(&status_mutex);
    mp4_unity_tick();
}

void app_fps_set_hook(int value, Method *method) {
    if (!ready.load(std::memory_order_acquire)) { app_fps_set_original(value, method); return; }
    application_fps_baseline.store(FPS_KNOWN | static_cast<uint32_t>(value), std::memory_order_release);
    if (!game_call()) { app_fps_set_original(value, method); return; }
    Config config = configuration();
    app_fps_set_original(selected_fps(config, value), method);
}

void aa_hook(void *camera, void *additional, bool final, void *data, Method *method) {
    if (!ready.load(std::memory_order_acquire) || !game_call() || !additional) {
        aa_original(camera, additional, final, data, method); return;
    }
    Config config = configuration();
    const bool requested_main = config.custom_graphics && config.aa_mode >= 0 && camera && camera == graphics_camera()
        && read<int>(additional, 0x2c) == 0;
    const bool apply = requested_main && (config.aa_mode == 0 || read<bool>(additional, 0x4c));
    ScopedMemory<int> mode(additional, 0x50, apply), quality(additional, 0x54, apply);
    if (apply) {
        mode.set(config.aa_mode);
        if (config.aa_mode == 2) quality.set(2);
    }
    aa_original(camera, additional, final, data, method);
    if (requested_main) { aa_revision = config.revision; aa_unavailable = !apply; }
}
bool shadow_hook(void *self, void *data, void **settings, int resolution, Method *method) {
    bool requested = false; int64_t revision = -1;
    if (ready.load(std::memory_order_acquire) && game_call() && data) {
        Config config = configuration();
        // These are unboxed by-ref struct offsets, not boxed metadata offsets.
        void *camera = read<void *>(data, 0x10 + 0x80);
        if (config.custom_graphics && config.shadow_resolution && camera && camera == graphics_camera()) {
            requested = true; revision = config.revision;
            shadow_unavailable = config.shadow_resolution > max_texture(nullptr);
            if (!shadow_unavailable) resolution = config.shadow_resolution;
        }
    }
    const bool result = shadow_original(self, data, settings, resolution, method);
    if (requested) shadow_revision = result || shadow_unavailable ? revision : -1;
    return result;
}

#include "shared_cache_hooks.hpp"

#ifndef IDOLY_DARWIN_BRIDGE
// BEGIN_MP4_NATIVE_CLOCK_SOURCE_HASH
// A bounded, dependency-free SHA-256 reader for the immutable ORIGINAL Unity
// library. APK-installed libraries may be stored members instead of files.
struct Mp4SourceSha256 {
    uint32_t h[8]={0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19};
    uint8_t block[64]{};size_t used=0;uint64_t bytes=0;
    static uint32_t rotate(uint32_t x,unsigned n){return (x>>n)|(x<<(32-n));}
    void compress(){
        static constexpr uint32_t k[64]={0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
            0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
            0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
            0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
            0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
            0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
            0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
            0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2};
        uint32_t w[64]{};for(unsigned i=0;i<16;++i)for(unsigned j=0;j<4;++j)w[i]=(w[i]<<8)|block[4*i+j];
        for(unsigned i=16;i<64;++i){const uint32_t a=w[i-15],b=w[i-2];w[i]=w[i-16]+(rotate(a,7)^rotate(a,18)^(a>>3))+w[i-7]+(rotate(b,17)^rotate(b,19)^(b>>10));}
        uint32_t a=h[0],b=h[1],c=h[2],d=h[3],e=h[4],f=h[5],g=h[6],z=h[7];
        for(unsigned i=0;i<64;++i){const uint32_t first=z+(rotate(e,6)^rotate(e,11)^rotate(e,25))+((e&f)^(~e&g))+k[i]+w[i];
            const uint32_t second=(rotate(a,2)^rotate(a,13)^rotate(a,22))+((a&b)^(a&c)^(b&c));z=g;g=f;f=e;e=d+first;d=c;c=b;b=a;a=first+second;}
        h[0]+=a;h[1]+=b;h[2]+=c;h[3]+=d;h[4]+=e;h[5]+=f;h[6]+=g;h[7]+=z;
    }
    void append(const uint8_t* data,size_t count){bytes+=count;while(count){const size_t n=count<64-used?count:64-used;
        std::memcpy(block+used,data,n);used+=n;data+=n;count-=n;if(used==64){compress();used=0;}}}
    bool matches(const char* hex){const uint64_t bits=bytes*8;uint8_t tail[128]{};tail[0]=0x80;
        const size_t padding=used<56?56-used:120-used;append(tail,padding);
        for(unsigned i=0;i<8;++i)tail[i]=static_cast<uint8_t>(bits>>(56-8*i));
        append(tail,8);
        char actual[65]{};for(unsigned i=0;i<8;++i)std::snprintf(actual+8*i,9,"%08x",h[i]);return !std::strcmp(actual,hex);}
};
bool mp4_source_read(int fd,uint64_t offset,void* target,size_t bytes){
    auto* data=static_cast<uint8_t*>(target);while(bytes){const ssize_t n=pread(fd,data,bytes,static_cast<off_t>(offset));
        if(n<=0)return false;
        offset+=static_cast<size_t>(n);data+=n;bytes-=static_cast<size_t>(n);}return true;
}
uint16_t mp4_zip_u16(const uint8_t* p){return static_cast<uint16_t>(p[0])|(static_cast<uint16_t>(p[1])<<8);}
uint32_t mp4_zip_u32(const uint8_t* p){return static_cast<uint32_t>(mp4_zip_u16(p))|(static_cast<uint32_t>(mp4_zip_u16(p+2))<<16);}
bool mp4_source_stored_member(int fd,uint64_t size,const char* member,uint64_t* start,uint32_t expected_size){
    if(size<22)return false;
    const size_t tail_size=static_cast<size_t>(size<65557?size:65557);
    auto* tail=static_cast<uint8_t*>(malloc(tail_size));if(!tail)return false;
    const bool read_ok=mp4_source_read(fd,size-tail_size,tail,tail_size);size_t found=tail_size;
    if(read_ok)for(size_t i=tail_size-22+1;i-->0;)if(mp4_zip_u32(tail+i)==0x06054b50
        &&i+22+mp4_zip_u16(tail+i+20)==tail_size){found=i;break;}
    if(found==tail_size){free(tail);return false;}
    const uint8_t* eocd=tail+found;const uint16_t entries=mp4_zip_u16(eocd+10);
    const uint64_t cd=mp4_zip_u32(eocd+16),cd_size=mp4_zip_u32(eocd+12),eocd_offset=size-tail_size+found;
    const bool valid=!mp4_zip_u16(eocd+4)&&!mp4_zip_u16(eocd+6)&&entries&&entries!=65535
        &&mp4_zip_u16(eocd+8)==entries&&cd_size<=64*1024*1024&&cd<=eocd_offset&&cd_size<=eocd_offset-cd;
    free(tail);if(!valid)return false;
    uint64_t at=cd;bool matched=false;const size_t member_size=std::strlen(member);
    for(unsigned index=0;index<entries;++index){uint8_t header[46]{};
        if(at>cd+cd_size||sizeof(header)>cd+cd_size-at||!mp4_source_read(fd,at,header,sizeof(header))||mp4_zip_u32(header)!=0x02014b50)return false;
        const size_t name_size=mp4_zip_u16(header+28),extra=mp4_zip_u16(header+30),comment=mp4_zip_u16(header+32);
        const uint64_t next=at+46+name_size+extra+comment;if(next>cd+cd_size)return false;
        if(name_size==member_size){char name[64]{};if(name_size>=sizeof(name)||!mp4_source_read(fd,at+46,name,name_size))return false;
            if(!std::memcmp(name,member,name_size)){
                if(matched||mp4_zip_u16(header+8)&1||mp4_zip_u16(header+10)!=0||mp4_zip_u32(header+20)!=expected_size
                    ||mp4_zip_u32(header+24)!=expected_size||mp4_zip_u16(header+34))return false;
                const uint64_t local=mp4_zip_u32(header+42);uint8_t lh[30]{};
                if(local>cd||sizeof(lh)>cd-local||!mp4_source_read(fd,local,lh,sizeof(lh))||mp4_zip_u32(lh)!=0x04034b50
                    ||mp4_zip_u16(lh+6)&1||mp4_zip_u16(lh+8)!=0||mp4_zip_u16(lh+26)!=name_size)return false;
                const uint64_t payload=local+30+name_size+mp4_zip_u16(lh+28);
                if(payload>cd||expected_size>cd-payload||!mp4_source_read(fd,local+30,name,name_size)||std::memcmp(name,member,name_size))return false;
                *start=payload;matched=true;
            }}at=next;
    }
    return matched&&at==cd+cd_size;
}
bool mp4_library_source_matches(const char* image_name,uint32_t expected_size,const char* expected_sha,const char* member){
    char path[PATH_MAX]{};const char* separator=std::strstr(image_name,"!/");const size_t path_size=separator?static_cast<size_t>(separator-image_name):std::strlen(image_name);
    if(!path_size||path_size>=sizeof(path)||(separator&&std::strcmp(separator+2,member)))return false;
    std::memcpy(path,image_name,path_size);const int fd=open(path,O_RDONLY|O_CLOEXEC|O_NOFOLLOW);if(fd<0)return false;
    struct stat before{},after{};uint64_t offset=0;bool ok=!fstat(fd,&before)&&S_ISREG(before.st_mode)&&before.st_size>0&&static_cast<uint64_t>(before.st_size)<=8ull*1024*1024*1024;
    if(ok)ok=separator?mp4_source_stored_member(fd,static_cast<uint64_t>(before.st_size),separator+2,&offset,expected_size):before.st_size==expected_size;
    Mp4SourceSha256 hash;uint8_t buffer[16384]{};
    for(uint64_t done=0;ok&&done<expected_size;){const size_t n=expected_size-done<sizeof(buffer)?static_cast<size_t>(expected_size-done):sizeof(buffer);
        ok=mp4_source_read(fd,offset+done,buffer,n);if(ok)hash.append(buffer,n);done+=n;}
    if(ok)ok=hash.matches(expected_sha)&&!fstat(fd,&after)&&before.st_dev==after.st_dev
        &&before.st_ino==after.st_ino&&before.st_size==after.st_size&&before.st_mtim.tv_sec==after.st_mtim.tv_sec&&before.st_mtim.tv_nsec==after.st_mtim.tv_nsec;
    close(fd);return ok;
}
bool mp4_native_source_matches(const char* image_name){
    return mp4_library_source_matches(image_name,21427000,mp4_native_profile.native_sha256,"lib/arm64-v8a/libunity.so");
}
// END_MP4_NATIVE_CLOCK_SOURCE_HASH
struct Image { uintptr_t base = 0; const ElfW(Phdr) *headers = nullptr; size_t count = 0; char name[PATH_MAX]{}; bool unity = false; };
void* mp4_held_native_library=nullptr;
void* mp4_native_time_stub=nullptr;
int mp4_find_native_image(dl_phdr_info* info,size_t,void* opaque){
    const size_t size=std::strlen(info->dlpi_name);constexpr const char suffix[]="/libunity.so";
    auto* output=static_cast<Image*>(opaque);
    if(size<sizeof(suffix)-1||size>=sizeof(output->name)||std::strcmp(info->dlpi_name+size-(sizeof(suffix)-1),suffix))return 0;
    output->base=info->dlpi_addr;output->headers=info->dlpi_phdr;output->count=info->dlpi_phnum;
    std::memcpy(output->name,info->dlpi_name,size+1);return 0;
}
bool mp4_prepare_android_native_clock(){
    Image first;dl_iterate_phdr(mp4_find_native_image,&first);
    if(!first.base){mp4_native_clock_error.store("native_clock_module_missing",std::memory_order_release);return false;}
    mp4_held_native_library=dlopen(first.name,RTLD_NOW|RTLD_NOLOAD);
    Image held;if(mp4_held_native_library)dl_iterate_phdr(mp4_find_native_image,&held);
    if(!mp4_held_native_library||held.base!=first.base||std::strcmp(held.name,first.name)
        ||!mp4_native_source_matches(held.name)){
        mp4_native_clock_error.store("native_clock_original_source_unverified",std::memory_order_release);
        if(mp4_held_native_library){dlclose(mp4_held_native_library);mp4_held_native_library=nullptr;}return false;
    }
    if(!mp4_prepare_native_clock(held.base)){
        dlclose(mp4_held_native_library);mp4_held_native_library=nullptr;return false;
    }
    return true;
}
int find_image(dl_phdr_info *info, size_t, void *opaque) {
    auto *image = static_cast<Image *>(opaque);
    const size_t n = std::strlen(info->dlpi_name);
    const char *tail = "/libil2cpp.so";
    if (n >= 12 && !std::strcmp(info->dlpi_name + n - 12, "/libunity.so")) image->unity = true;
    if (n < std::strlen(tail) || n >= sizeof(image->name) || std::strcmp(info->dlpi_name + n - std::strlen(tail), tail)) return 0;
    image->base = info->dlpi_addr; image->headers = info->dlpi_phdr; image->count = info->dlpi_phnum;
    std::memcpy(image->name, info->dlpi_name, n + 1); return 0;
}
bool mapped(const Image &image, uintptr_t address, size_t size, unsigned flags) {
    if (address + size < address) return false;
    for (size_t i = 0; i < image.count; ++i) {
        const auto &h = image.headers[i]; const uintptr_t begin = image.base + h.p_vaddr;
        if (h.p_type == PT_LOAD && (h.p_flags & flags) == flags && address >= begin && address + size <= begin + h.p_filesz) return true;
    }
    return false;
}
// BEGIN_MP4_ACTOR_BURST_INSTALL
void pause_ms(long);
void* mp4_actor_burst_library=nullptr;void* mp4_actor_burst_stub=nullptr;
int mp4_find_burst_image(dl_phdr_info* info,size_t,void* opaque){
    constexpr const char suffix[]="/lib_burst_generated.so";auto* output=static_cast<Image*>(opaque);
    const size_t size=std::strlen(info->dlpi_name);
    if(size<sizeof(suffix)-1||size>=sizeof(output->name)||std::strcmp(info->dlpi_name+size-(sizeof(suffix)-1),suffix))return 0;
    output->base=info->dlpi_addr;output->headers=info->dlpi_phdr;output->count=info->dlpi_phnum;
    std::memcpy(output->name,info->dlpi_name,size+1);return 0;
}
void* mp4_install_actor_burst(void*){
    // Burst can be loaded on demand by the first ordinary animation job.
    // Keep graphics/normal playback available while this export route waits.
    Image found;
    for(unsigned i=0;i<900;++i){dl_iterate_phdr(mp4_find_burst_image,&found);if(found.base)break;pause_ms(200);}
    if(!found.base){mp4_actor_route_error.store("actor_burst_module_missing",std::memory_order_release);return nullptr;}
    mp4_actor_burst_library=dlopen(found.name,RTLD_NOW|RTLD_NOLOAD);
    Image held;if(mp4_actor_burst_library)dl_iterate_phdr(mp4_find_burst_image,&held);
    if(!mp4_actor_burst_library||held.base!=found.base||std::strcmp(held.name,found.name)
        ||!mp4_library_source_matches(held.name,514672,mp4_actor_profile.burst_native_sha256,"lib/arm64-v8a/lib_burst_generated.so")
        ||!mapped(held,held.base+mp4_actor_profile.burst_execute.rva,16,PF_R|PF_X)
        ||std::memcmp(reinterpret_cast<void*>(held.base+mp4_actor_profile.burst_execute.rva),mp4_actor_profile.burst_execute.prefix,16)
        ||dlsym(mp4_actor_burst_library,"efaef804e44554aa5845633afa905c07")!=reinterpret_cast<void*>(held.base+mp4_actor_profile.burst_execute.rva)){
        mp4_actor_route_error.store("actor_burst_source_unverified",std::memory_order_release);
        if(mp4_actor_burst_library){dlclose(mp4_actor_burst_library);mp4_actor_burst_library=nullptr;}return nullptr;
    }
    mp4_actor_burst_stub=shadowhook_hook_func_addr(reinterpret_cast<void*>(held.base+mp4_actor_profile.burst_execute.rva),
        reinterpret_cast<void*>(mp4_actor_burst_hook),reinterpret_cast<void**>(&mp4_actor_burst_original));
    if(!mp4_actor_burst_stub||!mp4_actor_burst_original){
        mp4_actor_route_error.store("actor_burst_hook_failed",std::memory_order_release);
        if(mp4_actor_burst_stub){shadowhook_unhook(mp4_actor_burst_stub);mp4_actor_burst_stub=nullptr;}
        dlclose(mp4_actor_burst_library);mp4_actor_burst_library=nullptr;return nullptr;
    }
    mp4_actor_burst_installed.store(true,std::memory_order_release);mp4_actor_route_error.store("none",std::memory_order_release);return nullptr;
}
// END_MP4_ACTOR_BURST_INSTALL
bool shared_patched_entry(uintptr_t rva) {
    return rva==pin::shared_setup.rva||rva==pin::shared_is_cached.rva||rva==pin::shared_file_path.rva
        ||rva==pin::shared_pre_download.rva||rva==pin::shared_downloader_update.rva;
}
bool matches(const Image &image) {
    bool build = false;
    for (size_t i = 0; i < image.count; ++i) {
        const auto &h = image.headers[i];
        if (h.p_type != PT_NOTE || !mapped(image, image.base + h.p_vaddr, h.p_filesz, PF_R)) continue;
        size_t offset = 0;
        while (offset + sizeof(ElfW(Nhdr)) <= h.p_filesz) {
            const auto *note = reinterpret_cast<const ElfW(Nhdr) *>(image.base + h.p_vaddr + offset);
            const size_t names = (static_cast<size_t>(note->n_namesz) + 3) & ~size_t{3};
            const size_t desc = (static_cast<size_t>(note->n_descsz) + 3) & ~size_t{3};
            const size_t left = h.p_filesz - offset - sizeof(*note);
            if (names > left || desc > left - names) return false;
            const auto *name = reinterpret_cast<const unsigned char *>(note + 1);
            if (note->n_type == NT_GNU_BUILD_ID && note->n_namesz == 4 && !std::memcmp(name, "GNU", 4)
                    && note->n_descsz == sizeof(pin::build_id)) build = !std::memcmp(name + names, pin::build_id, sizeof(pin::build_id));
            offset += sizeof(*note) + names + desc;
        }
    }
    if (!build) return false;
    for (const auto &entry : pin::all) {
        const uintptr_t address = image.base + entry.rva;
        // These five entries were checked before our own early, atomic hook
        // publication. Their executable prefixes now contain our detours.
        if (shared_hooks_ready.load(std::memory_order_acquire)&&image.base==shared_image_base
                &&shared_patched_entry(entry.rva)) continue;
        if (!mapped(image, address, 16, PF_R | PF_X) || std::memcmp(reinterpret_cast<void *>(address), entry.bytes, 16)) return false;
    }
    return true;
}

std::atomic<bool> shared_installing{false},shared_early_started{false};
void shared_install_cache_image(const Image &image) {
    if (!image.base||shared_hooks_ready.load(std::memory_order_acquire)||shared_installing.exchange(true)) return;
    if (!matches(image)) {shared_installing.store(false);return;}
    image_base=image.base;shared_cache_load_calls();
    struct EarlyHook {const pin::Entry *entry;void *replacement;void **original;void *stub;};
#define SHARED_HOOK(entry,replacement,original) {&pin::entry,reinterpret_cast<void *>(replacement),reinterpret_cast<void **>(&original),nullptr}
    EarlyHook hooks[]={
        SHARED_HOOK(shared_setup,shared_setup_hook,shared_setup_original),
        SHARED_HOOK(shared_is_cached,shared_is_cached_hook,shared_is_cached_original),
        SHARED_HOOK(shared_file_path,shared_file_path_hook,shared_file_path_original),
        SHARED_HOOK(shared_pre_download,shared_pre_download_hook,shared_pre_download_original),
        SHARED_HOOK(shared_downloader_update,shared_downloader_update_hook,shared_downloader_update_original),
    };
#undef SHARED_HOOK
    for (size_t i=0;i<sizeof hooks/sizeof hooks[0];++i) {
        hooks[i].stub=shadowhook_hook_func_addr(reinterpret_cast<void *>(image.base+hooks[i].entry->rva),hooks[i].replacement,hooks[i].original);
        if (!hooks[i].stub) {
            for (size_t j=i;j>0;--j) shadowhook_unhook(hooks[j-1].stub);
            shared_installing.store(false);return;
        }
    }
    shared_hooks_ready.store(true,std::memory_order_release);shared_installing.store(false);
}
void shared_dl_post(dl_phdr_info *info,size_t size,void *) {
    Image image;find_image(info,size,&image);
    // ShadowHook's documented post-init callback runs before the dlopen caller
    // can start managed SDK setup. No Unity calls or worker IO occur here.
    if (image.base) shared_install_cache_image(image);
}
void shared_start_early() {
    if (shared_early_started.exchange(true)) return;
    if (shadowhook_init(SHADOWHOOK_MODE_UNIQUE,false)) return;
    shadowhook_set_recordable(false);
    if (shadowhook_register_dl_init_callback(nullptr,shared_dl_post,nullptr)) return;
    Image image;dl_iterate_phdr(find_image,&image);
    if (image.base) shared_install_cache_image(image);
}
#endif
void pause_ms(long ms) { timespec t{ms / 1000, (ms % 1000) * 1000000}; nanosleep(&t, nullptr); }
void load_calls() {
#define CALL(variable, entry) variable = function<decltype(variable)>(pin::entry)
#ifndef IDOLY_DARWIN_BRIDGE
    CALL(rendering_mode_get, rendering_mode); CALL(graphics_api_get, graphics_api);
#endif
    CALL(weak_new, weak_new); CALL(weak_get, weak_get); CALL(weak_free, weak_free);
    CALL(object_class, object_class); CALL(class_name, class_name); CALL(class_namespace, class_namespace); CALL(class_parent, class_parent);
    CALL(object_alive, object_alive); CALL(app_fps_get, app_fps_get); CALL(quality_names, q_names);
    CALL(font_name_get,font_name); CALL(font_hide_get,font_hide_get); CALL(font_hide_set,font_hide_set);
    CALL(font_multi,font_multi); CALL(font_clear,font_clear); CALL(font_fallback,font_fallback);
    CALL(font_field,font_field); CALL(font_field_type,font_field_type);
    CALL(font_class_type,font_class_type); CALL(font_new,font_new);
    CALL(font_strong,font_strong); CALL(font_method,font_method);
    // The existing verified 16-byte getter prefix contains this complete
    // adjacent 8-byte setter. Original metadata independently verifies both
    // methods and their matching closed generic List<TMP_FontAsset> type.
    font_fallback_set=reinterpret_cast<decltype(font_fallback_set)>(image_base+pin::font_fallback.rva+8);
    hangul_font::FactoryCalls lists;
    lists.object_class=font_owner_class;lists.field=font_field;lists.field_type=font_field_type;
    lists.class_from_type=font_class_type;lists.object_new=font_new;lists.method=font_method;
    lists.strong_new=font_strong;lists.release=weak_free;lists.get=font_fallback;lists.set=font_fallback_set;
    korean_list_factory.configure(lists);
    hangul_font::Calls fonts;
    fonts.strong_new=font_strong;fonts.weak_new=weak_new;fonts.target=weak_get;fonts.release=weak_free;
    fonts.alive=object_alive;fonts.named=font_named;fonts.get_flags=font_hide_get;fonts.set_flags=font_hide_set;
    fonts.set_multi_atlas=font_multi;fonts.clear_data=font_clear;fonts.fallbacks=font_fallback;
    fonts.insert_first=font_insert_first;fonts.ensure_fallbacks=font_ensure_fallbacks;
    korean_fallback.configure(fonts);
    CALL(screen_width, screen_width); CALL(screen_height, screen_height);
    CALL(max_texture, max_texture);
    CALL(rt_width, rt_width); CALL(rt_height, rt_height);
    CALL(rt_camera, rt_camera); CALL(rt_target, rt_target); CALL(rt_destroy, rt_destroy); CALL(target_to_texture, target_to_texture);
    CALL(target_current, target_current); CALL(target_rect, target_rect); CALL(parent_get, parent_get);
    CALL(camera_rect_get, rect_get); CALL(aspect_get_original, aspect_get); CALL(transform_rect_get, transform_rect_get);
    CALL(local_position, local_position); CALL(local_scale, local_scale); CALL(local_rotation, local_rotation);
    CALL(size_delta_get, size_delta_get); CALL(size_delta_set, size_delta_set);
    CALL(local_position_set, local_position_set); CALL(active_enabled, active_enabled);
    sound::Calls sound_calls;
    sound_calls.weak_new=weak_new;sound_calls.weak_get=weak_get;sound_calls.weak_free=weak_free;
    sound_calls.matches=class_matches;sound_calls.alive=object_alive;sound_calls.active=active_enabled;
    sound_calls.now_ms=sound_monotonic_ms;sound_calls.save=sound_save_auto;
    sound_tracker.configure(sound_calls);

    CALL(orthographic, orthographic); CALL(uv_get, uv_get);
    CALL(projection_get, projection_get); CALL(physical_get, physical_get); CALL(gate_get, gate_get);
    CALL(sensor_get, sensor_get); CALL(lens_get, lens_get); CALL(projection_mode_get, projection_mode_get);
    CALL(camera_aspect_set_original, aspect_set); CALL(camera_aspect_reset, aspect_reset);
    CALL(costume_order_sorted, costume_order_sorted);
    CALL(orientation_calls.frame_count, orientation_frame_count);
    CALL(orientation_calls.token_cancelled, orientation_token_cancelled);
    CALL(orientation_calls.set_orientation_async, orientation_set_async);
    orientation_calls.available=orientation_available; orientation_calls.wait_for_orientation=playback_wait_for_orientation;
    orientation_calls.game_thread=game_call;
    orientation_calls.screen_width=screen_width; orientation_calls.screen_height=screen_height;
    rotation::configure(orientation_calls);
#ifdef IDOLY_DARWIN_BRIDGE
    CALL(mv_ui_hide, mv_ui_hide);
#endif
    preview_ui_calls.weak_new=weak_new; preview_ui_calls.weak_get=weak_get; preview_ui_calls.weak_free=weak_free;
    preview_ui_calls.matches=class_matches;
    CALL(preview_ui_calls.ui_get, preview_ui_get); CALL(preview_ui_calls.ui_set, preview_ui_set);
    preview_ui.configure(preview_ui_calls);
#ifndef IDOLY_DARWIN_BRIDGE
    wardrobe_calls.weak_new=weak_new; wardrobe_calls.weak_get=weak_get; wardrobe_calls.weak_free=weak_free;
    wardrobe_calls.alive=object_alive; wardrobe_calls.active=active_enabled; wardrobe_calls.matches=class_matches;
    CALL(wardrobe_calls.yield, wardrobe_yield);
    wardrobe_calls.hide_predicate=reinterpret_cast<void *>(image_base+pin::wardrobe_hide_predicate.rva);
    wardrobe_calls.event=wardrobe_event; wardrobe_lifecycle.configure(wardrobe_calls);
    wardrobe_exit_tracker.configure(render_probe_monotonic_ms);
    CALL(bulk_costume_checked, bulk_costume_checked);
    CALL(bulk_hair_checked, bulk_hair_checked);
#endif
    panorama_api.weak_new=weak_new; panorama_api.weak_get=weak_get; panorama_api.weak_free=weak_free;
    panorama_api.alive=object_alive; panorama_api.matches=class_matches;
    panorama_api.parent=parent_get; panorama_api.position_get=local_position; panorama_api.position_set=local_position_set;
    CALL(panorama_api.component_transform, ui_component_transform);
    CALL(panorama_api.gameobject_transform, ui_gameobject_transform);
    CALL(panorama_api.transform_point, ui_transform_point);
    CALL(panorama_api.inverse_transform_point, ui_inverse_transform_point);
    CALL(panorama_api.ui_active_get, pano_ui_get); CALL(panorama_api.ui_active_set, pano_ui_set);
    panorama_ui.configure(panorama_api);
    mp4_verify_original_calls();
    mp4_verify_photography_calls();
    mp4_verify_actor_calls();
#undef CALL
}
bool accept_configuration(int schema, const Config &value) {
    if (!config_valid(schema, value)) return false;
    pthread_mutex_lock(&config_mutex);
    if (configured && value.revision < pending.revision) { pthread_mutex_unlock(&config_mutex); return false; }
    if (configured && value.revision == pending.revision
            && (value.custom_graphics != pending.custom_graphics || value.quality != pending.quality
                || value.target_fps != pending.target_fps || value.render_scale != pending.render_scale
                || value.max_buffer_pixel != pending.max_buffer_pixel || value.aa_mode != pending.aa_mode
                || value.shadow_resolution != pending.shadow_resolution
                || value.expand_photography != pending.expand_photography)) {
        pthread_mutex_unlock(&config_mutex); return false;
    }
    pending = value; configured = true;
    pthread_mutex_unlock(&config_mutex);
    return true;
}
void status_json(char *json, size_t capacity) {
    pthread_mutex_lock(&status_mutex); Status copy = state; pthread_mutex_unlock(&status_mutex);
    if (!std::isfinite(copy.aspect)) copy.aspect = 0;
    if (!std::isfinite(copy.base_fov)) copy.base_fov = 0;
    if (!std::isfinite(copy.fov)) copy.fov = 0;
    const long long aspect = std::llround(std::clamp(copy.aspect, 0.f, 32.f) * 1000000.0);
    const long long base_fov = std::llround(std::clamp(copy.base_fov, 0.f, 179.f) * 1000000.0);
    const long long fov = std::llround(std::clamp(copy.fov, 0.f, 179.f) * 1000000.0);
    std::snprintf(json, capacity,
        "{\"schema\":1,\"bridge_version\":1,\"revision\":%lld,\"status\":\"%s\","
        "\"capabilities\":{\"fps\":%s,\"quality\":%s,\"resolution\":%s,\"anti_aliasing\":%s,\"shadow\":%s,\"expanded_photography\":%s},"
        "\"metrics\":{\"screen_width\":%d,\"screen_height\":%d,\"render_width\":%d,\"render_height\":%d,"
        "\"camera_aspect\":%lld.%06lld,\"base_vertical_fov\":%lld.%06lld,\"vertical_fov\":%lld.%06lld}}",
        static_cast<long long>(copy.revision), copy.state,
        copy.fps ? "true" : "false", copy.quality ? "true" : "false", copy.resolution ? "true" : "false",
        copy.aa ? "true" : "false", copy.shadow ? "true" : "false", copy.expanded ? "true" : "false",
        copy.screen_w, copy.screen_h, copy.render_w, copy.render_h,
        aspect / 1000000, aspect % 1000000, base_fov / 1000000, base_fov % 1000000, fov / 1000000, fov % 1000000);

}

#ifndef IDOLY_DARWIN_BRIDGE
struct Hook { const pin::Entry *entry; void *replacement; void **original; void *stub = nullptr; };
void *install(void *) {
    Image image;
    for (unsigned attempt = 0; attempt < 900; ++attempt) {
        image = {}; dl_iterate_phdr(find_image, &image);
        if (image.base && image.unity) break;
        pause_ms(200);
    }
    if (!image.base || !image.unity) { set_state("unsupported"); return nullptr; }
    held_library = dlopen(image.name, RTLD_NOW | RTLD_NOLOAD);
    Image held;
    if (held_library) dl_iterate_phdr(find_image, &held);
    if (!held_library || !held.base || std::strcmp(held.name, image.name) || !matches(held)) {
        if (held_library) { dlclose(held_library); held_library = nullptr; }
        set_state("unsupported"); return nullptr;
    }
    image = held;
    if(!mp4_prepare_android_native_clock()){set_state("unsupported");return nullptr;}
    image_base = image.base; load_calls();
    if (shadowhook_init(SHADOWHOOK_MODE_UNIQUE, false)) { set_state("init_failed"); return nullptr; }
    shadowhook_set_recordable(false);
    mp4_managed_hook_receipts_ready.store(false,std::memory_order_release);mp4_managed_hook_count=0;
#define HOOK(entry, replacement, original) {&pin::entry, reinterpret_cast<void *>(replacement), reinterpret_cast<void **>(&original), nullptr}
    Hook hooks[] = {
        HOOK(font_awake,font_awake_hook,font_awake_original),
        HOOK(resource_can_reach,resource_can_reach_hook,resource_can_reach_original),
        HOOK(sound_bgm_volume,sound_bgm_volume_hook,sound_bgm_volume_original),
        HOOK(sound_bgm_soundable,sound_bgm_soundable_hook,sound_bgm_soundable_original),
        HOOK(sound_se_volume,sound_se_volume_hook,sound_se_volume_original),
        HOOK(sound_se_soundable,sound_se_soundable_hook,sound_se_soundable_original),
        HOOK(sound_voice_volume,sound_voice_volume_hook,sound_voice_volume_original),
        HOOK(sound_voice_soundable,sound_voice_soundable_hook,sound_voice_soundable_original),
        HOOK(sound_bind,sound_bind_hook,sound_bind_original),
        HOOK(sound_save,sound_save_hook,sound_save_original),

        HOOK(q_set, quality_set_hook, quality_set_original), HOOK(q_apply, quality_apply_hook, quality_apply_original),
        HOOK(q_init, quality_init_hook, quality_init_original), HOOK(q_update, quality_update_hook, quality_update_original),
        HOOK(app_fps_set, app_fps_set_hook, app_fps_set_original),
        HOOK(rt_update, rt_hook, rt_original), HOOK(limited_resolution, limited_hook, limited_original),
        HOOK(scene_main_update, main_update_hook, scene_main_update_original), HOOK(scene_main_reset, main_reset_hook, scene_main_reset_original),
        HOOK(scene_pano_update, pano_update_hook, scene_pano_update_original), HOOK(scene_pano_reset, pano_reset_hook, scene_pano_reset_original),
        HOOK(target_update, target_update_hook, target_update_original), HOOK(target_late, target_late_hook, target_late_original),
        HOOK(fov_get, fov_get_hook, fov_get_original), HOOK(fov_set, fov_set_hook, fov_set_original),
        HOOK(focal_get, focal_get_hook, focal_get_original), HOOK(focal_set, focal_set_hook, focal_set_original),
        HOOK(aa_init, aa_hook, aa_original), HOOK(shadow_update, shadow_hook, shadow_original),
        HOOK(rotation_wait,rotation::wait_hook,rotation::original_wait),
        HOOK(rotation_wait_label,rotation::wait_label_hook,rotation::original_wait_label),
        HOOK(rotation_wait_simple,rotation::wait_simple_hook,rotation::original_wait_simple),
        HOOK(rotation_wait_preview,rotation::wait_preview_hook,rotation::original_wait_preview),
        HOOK(orientation_internal_move,rotation::internal_move_hook,rotation::original_internal_move),
        HOOK(orientation_starts_portrait_ready,rotation::starts_portrait_hook,rotation::original_starts_portrait),
        HOOK(orientation_starts_landscape_ready,rotation::starts_landscape_hook,rotation::original_starts_landscape),
        HOOK(orientation_fixed_portrait_ready,rotation::fixed_portrait_hook,rotation::original_fixed_portrait),
        HOOK(orientation_fixed_landscape_ready,rotation::fixed_landscape_hook,rotation::original_fixed_landscape),
        HOOK(orientation_after_ready,rotation::after_hook,rotation::original_after),
        HOOK(preview_ui_bind,preview_ui_bind_hook,preview_ui_bind_original),
        HOOK(costume_sorted,costume_sorted_hook,costume_sorted_original),
        HOOK(wardrobe_show,wardrobe_show_hook,wardrobe_show_original),
        HOOK(wardrobe_move,wardrobe_move_hook,wardrobe_move_original),
        HOOK(wardrobe_fail,wardrobe_fail_hook,wardrobe_fail_original),
        HOOK(wardrobe_wait,wardrobe_wait_hook,wardrobe_wait_original),
        HOOK(wardrobe_back,wardrobe_back_hook,wardrobe_back_original),
        HOOK(fitting_back,fitting_back_hook,fitting_back_original),
        HOOK(wardrobe_preclose,wardrobe_preclose_hook,wardrobe_preclose_original),
        HOOK(wardrobe_hide_move,wardrobe_hide_move_hook,wardrobe_hide_move_original),
        HOOK(wardrobe_disable,wardrobe_disable_hook,wardrobe_disable_original),
        HOOK(character_list_show,character_list_show_hook,character_list_show_original),
        HOOK(character_list_open_in,character_list_open_in_hook,character_list_open_in_original),
        HOOK(character_list_close_in,character_list_close_in_hook,character_list_close_in_original),
        HOOK(character_details_close_in,character_details_close_in_hook,character_details_close_in_original),
        HOOK(wardrobe_gc_collect,wardrobe_gc_collect_hook,wardrobe_gc_collect_original),
        HOOK(wardrobe_unload_unused,wardrobe_unload_unused_hook,wardrobe_unload_unused_original),
        HOOK(bulk_costume_filter,bulk_costume_filter_hook,bulk_costume_filter_original),
        HOOK(bulk_hair_filter,bulk_hair_filter_hook,bulk_hair_filter_original),
        HOOK(mp4_player_initialize,mp4_player_initialize_hook,mp4_player_initialize_original),
        HOOK(mp4_photography_initialize,mp4_photography_initialize_hook,mp4_photography_initialize_original),
        HOOK(mp4_photography_player_initialize,mp4_photography_player_initialize_hook,mp4_photography_player_initialize_original),
        HOOK(mp4_photography_end,mp4_photography_end_hook,mp4_photography_end_original),
        HOOK(mp4_presenter_update,mp4_presenter_update_hook,mp4_presenter_update_original),
        HOOK(mp4_capture_pass,mp4_capture_pass_hook,mp4_capture_pass_original),
        HOOK(mp4_end_camera,mp4_end_camera_hook,mp4_end_camera_original),
        HOOK(mp4_graph_mode,mp4_graph_mode_hook,mp4_graph_mode_original),
        HOOK(mp4_brain_delta,mp4_brain_delta_hook,mp4_brain_delta_original),
        HOOK(mp4_core_camera,mp4_core_camera_hook,mp4_core_camera_original),
        HOOK(mp4_brain_update,mp4_brain_update_hook,mp4_brain_update_original),
        HOOK(mp4_shader_set,mp4_shader_set_hook,mp4_shader_set_original),
        HOOK(mp4_shader_reset,mp4_shader_reset_hook,mp4_shader_reset_original),
        HOOK(mp4_actor_process,mp4_actor_process_hook,mp4_actor_process_original),
    };
#undef HOOK
    for (size_t i = 0; i < sizeof hooks / sizeof hooks[0]; ++i) {
        hooks[i].stub = shadowhook_hook_func_addr(reinterpret_cast<void *>(image_base + hooks[i].entry->rva), hooks[i].replacement, hooks[i].original);
        if (!hooks[i].stub) {
            for (size_t j = i; j > 0; --j) shadowhook_unhook(hooks[j - 1].stub);
            set_state("init_failed"); return nullptr;
        }
        if(!mp4_record_managed_hook(hooks[i].entry,hooks[i].stub,hooks[i].original)){
            for(size_t j=i+1;j>0;--j)shadowhook_unhook(hooks[j-1].stub);
            set_state("init_failed");return nullptr;
        }
        if (i==0) pause_ms(500); // Fonts are captured during the existing graphics readiness delay.
    }
    if (!rotation::ready_for_publish() || !preview_ui.ready() || !korean_fallback.ready() || !korean_list_factory.ready() || !wardrobe_lifecycle.ready()
            || !wardrobe_exit_tracker.ready() || !sound_tracker.ready()) {
        for (size_t i=sizeof hooks/sizeof hooks[0];i>0;--i) shadowhook_unhook(hooks[i-1].stub);
        set_state("init_failed");return nullptr;
    }
    mp4_native_time_stub=shadowhook_hook_func_addr(reinterpret_cast<void*>(mp4_native_base+mp4_native_profile.update.rva),
        reinterpret_cast<void*>(mp4_native_time_hook),reinterpret_cast<void**>(&mp4_native_time_original));
    if(!mp4_native_time_stub||!mp4_install_native_clock_api()){
        if(mp4_native_time_stub){shadowhook_unhook(mp4_native_time_stub);mp4_native_time_stub=nullptr;}
        for(size_t i=sizeof hooks/sizeof hooks[0];i>0;--i)shadowhook_unhook(hooks[i-1].stub);
        if(!mp4_native_time_original)mp4_native_clock_error.store("native_clock_native_hook_failed",std::memory_order_release);
        set_state("init_failed");return nullptr;
    }
    mp4_managed_hook_receipts_ready.store(true,std::memory_order_release);
    mp4_actor_managed_installed.store(true,std::memory_order_release);
    pthread_mutex_lock(&status_mutex);
    state.fps = state.quality = state.resolution = state.aa = state.shadow = state.expanded = true;
    pthread_mutex_unlock(&status_mutex);
    ready.store(true, std::memory_order_release);
    pthread_t actor_worker;
    if(!pthread_create(&actor_worker,nullptr,mp4_install_actor_burst,nullptr))pthread_detach(actor_worker);
    else mp4_actor_route_error.store("actor_burst_worker_failed",std::memory_order_release);
    return nullptr;
}
#else
#include "../ios/static_install.hpp"
#endif
}

#ifndef IDOLY_DARWIN_BRIDGE
extern "C" JNIEXPORT jint JNICALL JNI_OnLoad(JavaVM *, void *) { shared_start_early();return JNI_VERSION_1_6; }
extern "C" JNIEXPORT void JNICALL Java_game_qualiarts_idolypride_presentation_NativePresentation_start(JNIEnv *, jclass) {
    if (started.exchange(true)) return;
    pthread_t worker;
    if (!pthread_create(&worker, nullptr, install, nullptr)) pthread_detach(worker);
    else set_state("init_failed");
}
extern "C" JNIEXPORT jboolean JNICALL Java_game_qualiarts_idolypride_presentation_NativePresentation_configure(
        JNIEnv *, jclass, jint schema, jlong revision, jboolean custom, jint quality, jint fps, jfloat scale,
        jint max_pixel, jint aa, jint shadow, jboolean expand) {
    Config value{revision, custom != 0, quality, fps, scale, max_pixel, aa, shadow, expand != 0};
    return accept_configuration(schema, value) ? JNI_TRUE : JNI_FALSE;
}

extern "C" JNIEXPORT jstring JNICALL Java_game_qualiarts_idolypride_presentation_NativePresentation_status(JNIEnv *env, jclass) {
    char json[1024]; status_json(json, sizeof json);
    return env->NewStringUTF(json);
}

extern "C" JNIEXPORT jboolean JNICALL Java_game_qualiarts_idolypride_presentation_NativePresentation_configurePlayback(
        JNIEnv *,jclass,jint schema,jlong revision,jboolean wait) {
    return accept_playback_configuration(schema,revision,wait!=0)?JNI_TRUE:JNI_FALSE;
}
extern "C" JNIEXPORT jstring JNICALL Java_game_qualiarts_idolypride_presentation_NativePresentation_playbackStatus(JNIEnv *env,jclass) {
    char json[256];playback_status_json(json,sizeof json);return env->NewStringUTF(json);
}
extern "C" JNIEXPORT jstring JNICALL Java_game_qualiarts_idolypride_presentation_NativePresentation_renderProbeStatus(JNIEnv *env,jclass) {
    char json[512];render_probe_status_json(json,sizeof json);return env->NewStringUTF(json);
}
extern "C" JNIEXPORT jboolean JNICALL Java_game_qualiarts_idolypride_presentation_NativePresentation_configureMedia(
        JNIEnv *,jclass,jint schema,jlong revision,jboolean use_master_order) {
    return accept_media_configuration(schema,revision,use_master_order!=0)?JNI_TRUE:JNI_FALSE;
}
extern "C" JNIEXPORT jstring JNICALL Java_game_qualiarts_idolypride_presentation_NativePresentation_wardrobeStatus(JNIEnv *env,jclass) {
    char json[1536];wardrobe_status_json(json,sizeof json);return env->NewStringUTF(json);
}
extern "C" JNIEXPORT jboolean JNICALL Java_game_qualiarts_idolypride_localserver_UnifiedSharedResources_configure(
        JNIEnv *env,jclass,jstring directory,jlong epoch) {
    if (!directory||epoch<=0) return JNI_FALSE;
    const char *path=env->GetStringUTFChars(directory,nullptr);if (!path) return JNI_FALSE;
    const bool result=shared_configure(path,static_cast<uint64_t>(epoch));env->ReleaseStringUTFChars(directory,path);
    return result?JNI_TRUE:JNI_FALSE;
}
extern "C" JNIEXPORT jstring JNICALL Java_game_qualiarts_idolypride_localserver_UnifiedSharedResources_status(JNIEnv *env,jclass) {
    char json[768];shared_status_json(json,sizeof json);return env->NewStringUTF(json);
}
extern "C" JNIEXPORT void JNICALL Java_game_qualiarts_idolypride_localserver_UnifiedWindowing_setMultiWindow(
        JNIEnv *,jclass,jboolean enabled) {
    android_multi_window.store(enabled!=0,std::memory_order_release);
}

#else
#include "../ios/transport.hpp"
extern "C" __attribute__((visibility("default"))) bool IdolySharedResourcesConfigure(const char *directory,uint64_t epoch) {
    return shared_configure(directory,epoch);
}
extern "C" __attribute__((visibility("default"))) size_t IdolySharedResourcesCopyStatus(char *output,size_t capacity) {
    return shared_status_json(output,capacity);
}
#endif
