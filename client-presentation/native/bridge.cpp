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

#include "shadowhook.h"

#endif
#include "presentation_math.hpp"
#include "presentation_scope.hpp"
#include "orientation.hpp"
#include "playback_config.hpp"
#include "panorama_ui_edges.hpp"
#ifdef IDOLY_DARWIN_BRIDGE
#include "ios_profile.hpp"
#include "../ios/live_ui.hpp"
#include "../ios/photography_ui.hpp"
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
bool accept_playback_configuration(int schema,int64_t revision,bool wait) {
    pthread_mutex_lock(&playback_mutex);
    const bool accepted=playback_settings.accept(schema,revision,wait);
    pthread_mutex_unlock(&playback_mutex);return accepted;
}
bool playback_wait_for_orientation() {
    pthread_mutex_lock(&playback_mutex);
    const bool wait=playback_settings.wait();
    pthread_mutex_unlock(&playback_mutex);return wait;
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
    Config result = pending;
    if (has) *has = configured;
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

uint32_t (*weak_new)(void *, bool);
void *(*weak_get)(uint32_t);
void (*weak_free)(uint32_t);
void *(*object_class)(void *);
const char *(*class_name)(void *);
const char *(*class_namespace)(void *);
void *(*class_parent)(void *);
bool (*object_alive)(void *, Method *);

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
VoidMethod preview_ui_bind_original;
idoly::presentation::ios_photography_ui::Calls preview_ui_calls;
idoly::presentation::ios_photography_ui::DefaultHidden preview_ui;
void preview_ui_bind_hook(void *self, Method *method) {
    preview_ui.bind(self, method, preview_ui_bind_original,
        ready.load(std::memory_order_acquire) && desktop_host && game_call(true));
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
    // Only entered by game callbacks. Keep capture/explicit-size calls out.
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
    if (!ready.load(std::memory_order_acquire) || !self || !game_call() || (width > 0 && height > 0)) {
        rt_original(self, width, height, alpha, method); return;
    }
    Config config = configuration();
    void *camera = rt_camera(self, nullptr);
    if (camera && object_alive(camera, nullptr)) remember_controller(self);
    bool primary = camera && object_alive(camera, nullptr) && (main_controller.get(true) == self || scene_enter);
    if (!primary) { rt_original(self, width, height, alpha, method); return; }
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
    if (ready.load(std::memory_order_acquire) && game_call() && photo.expanded
            && photo.camera.get(true) == camera && !internal_camera) return photo.original.vertical_fov;
    return fov_get_original(camera, method);
}
void fov_set_hook(void *camera, float value, Method *method) {
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
    if (ready.load(std::memory_order_acquire) && game_call() && photo.expanded
            && photo.camera.get(true) == camera && !internal_camera) return photo.original_focal;
    return focal_get_original(camera, method);
}
void focal_set_hook(void *camera, float value, Method *method) {
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

#ifndef IDOLY_DARWIN_BRIDGE
struct Image { uintptr_t base = 0; const ElfW(Phdr) *headers = nullptr; size_t count = 0; char name[PATH_MAX]{}; bool unity = false; };
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
        if (!mapped(image, address, 16, PF_R | PF_X) || std::memcmp(reinterpret_cast<void *>(address), entry.bytes, 16)) return false;
    }
    return true;
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
    CALL(screen_width, screen_width); CALL(screen_height, screen_height);
    CALL(max_texture, max_texture);
    CALL(rt_width, rt_width); CALL(rt_height, rt_height);
    CALL(rt_camera, rt_camera); CALL(rt_target, rt_target); CALL(rt_destroy, rt_destroy); CALL(target_to_texture, target_to_texture);
    CALL(target_current, target_current); CALL(target_rect, target_rect); CALL(parent_get, parent_get);
    CALL(camera_rect_get, rect_get); CALL(aspect_get_original, aspect_get); CALL(transform_rect_get, transform_rect_get);
    CALL(local_position, local_position); CALL(local_scale, local_scale); CALL(local_rotation, local_rotation);
    CALL(size_delta_get, size_delta_get); CALL(size_delta_set, size_delta_set);
    CALL(local_position_set, local_position_set); CALL(active_enabled, active_enabled);
    CALL(orthographic, orthographic); CALL(uv_get, uv_get);
    CALL(projection_get, projection_get); CALL(physical_get, physical_get); CALL(gate_get, gate_get);
    CALL(sensor_get, sensor_get); CALL(lens_get, lens_get); CALL(projection_mode_get, projection_mode_get);
    CALL(camera_aspect_set_original, aspect_set); CALL(camera_aspect_reset, aspect_reset);
    CALL(orientation_calls.frame_count, orientation_frame_count);
    CALL(orientation_calls.token_cancelled, orientation_token_cancelled);
    CALL(orientation_calls.set_orientation_async, orientation_set_async);
    orientation_calls.available=orientation_available; orientation_calls.wait_for_orientation=playback_wait_for_orientation;
    orientation_calls.game_thread=game_call;
    orientation_calls.screen_width=screen_width; orientation_calls.screen_height=screen_height;
    rotation::configure(orientation_calls);
#ifdef IDOLY_DARWIN_BRIDGE
    CALL(mv_ui_hide, mv_ui_hide);
    preview_ui_calls.weak_new=weak_new; preview_ui_calls.weak_get=weak_get; preview_ui_calls.weak_free=weak_free;
    preview_ui_calls.matches=class_matches;
    CALL(preview_ui_calls.ui_get, preview_ui_get); CALL(preview_ui_calls.ui_set, preview_ui_set);
    preview_ui.configure(preview_ui_calls);
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
    pause_ms(500);
    held_library = dlopen(image.name, RTLD_NOW | RTLD_NOLOAD);
    Image held;
    if (held_library) dl_iterate_phdr(find_image, &held);
    if (!held_library || !held.base || std::strcmp(held.name, image.name) || !matches(held)) {
        if (held_library) { dlclose(held_library); held_library = nullptr; }
        set_state("unsupported"); return nullptr;
    }
    image = held;
    image_base = image.base; load_calls();
    if (shadowhook_init(SHADOWHOOK_MODE_UNIQUE, false)) { set_state("init_failed"); return nullptr; }
    shadowhook_set_recordable(false);
#define HOOK(entry, replacement, original) {&pin::entry, reinterpret_cast<void *>(replacement), reinterpret_cast<void **>(&original), nullptr}
    Hook hooks[] = {
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
    };
#undef HOOK
    for (size_t i = 0; i < sizeof hooks / sizeof hooks[0]; ++i) {
        hooks[i].stub = shadowhook_hook_func_addr(reinterpret_cast<void *>(image_base + hooks[i].entry->rva), hooks[i].replacement, hooks[i].original);
        if (!hooks[i].stub) {
            for (size_t j = i; j > 0; --j) shadowhook_unhook(hooks[j - 1].stub);
            set_state("init_failed"); return nullptr;
        }
    }
    if (!rotation::ready_for_publish()) {
        for (size_t i=sizeof hooks/sizeof hooks[0];i>0;--i) shadowhook_unhook(hooks[i-1].stub);
        set_state("init_failed");return nullptr;
    }
    pthread_mutex_lock(&status_mutex);
    state.fps = state.quality = state.resolution = state.aa = state.shadow = state.expanded = true;
    pthread_mutex_unlock(&status_mutex);
    ready.store(true, std::memory_order_release); return nullptr;
}
#else
#include "../ios/static_install.hpp"
#endif
}

#ifndef IDOLY_DARWIN_BRIDGE
extern "C" JNIEXPORT jint JNICALL JNI_OnLoad(JavaVM *, void *) { return JNI_VERSION_1_6; }
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

#else
#include "../ios/transport.hpp"
#endif
