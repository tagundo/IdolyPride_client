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

#include "shadowhook.h"

#endif
#include "presentation_math.hpp"
#include "presentation_scope.hpp"
#ifdef IDOLY_DARWIN_BRIDGE
#include "ios_profile.hpp"
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
std::atomic<uintptr_t> game_thread_id{0};

struct Status {
    int64_t revision = 0;
    const char *state = "waiting";
    bool fps = false, quality = false, resolution = false, aa = false, shadow = false, expanded = false;
    int screen_w = 0, screen_h = 0, render_w = 0, render_h = 0;
    float aspect = 0, base_fov = 0, fov = 0;
};
pthread_mutex_t status_mutex = PTHREAD_MUTEX_INITIALIZER;
Status state;

Config configuration(bool *has = nullptr) {
    pthread_mutex_lock(&config_mutex);
    Config result = pending;
    if (has) *has = configured;
    pthread_mutex_unlock(&config_mutex);
    return result;
}
void set_state(const char *value) {
    pthread_mutex_lock(&status_mutex); state.state = value; pthread_mutex_unlock(&status_mutex);
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
bool rect_transform(void *value) {
    if (!value || !object_alive(value, nullptr)) return false;
    void *type = object_class(value);
    for (unsigned depth = 0; type && depth != 12; ++depth, type = class_parent(type)) {
        const char *name = class_name(type), *space = class_namespace(type);
        if (name && space && !std::strcmp(name, "RectTransform") && !std::strcmp(space, "UnityEngine")) return true;
    }
    return false;
}

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
    Weak owner, controller, camera, image;
    bool active = false, geometry_known = false, base_known = false, expanded = false, target_expanded = false;
    bool geometry_confirmed = false;
    unsigned layout_ticks = 0;
    int64_t rejected_revision = -1;
    Dimensions rejected_viewport{};
    bool original_dynamic = false;
    Vec2 ratio{16, 9};
    Dimensions viewport{}, built_viewport{};
    Rect viewport_rect{};
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
    if (!photo.base_known || !dimensions_valid(rendered) || !projection_model_unchanged(camera)) return false;
    const float expected_aspect = static_cast<float>(rendered.width) / rendered.height;
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
}
void clear_photography() {
    restore_photography(false);
    photo.owner.clear(); photo.controller.clear(); photo.camera.clear(); photo.image.clear();
    photo.active = false; photo.base_known = false; photo.geometry_known = false;
    photo.viewport = {}; photo.built_viewport = {};
    photo.rejected_revision = -1; photo.rejected_viewport = {};
}

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
        if (photo.controller.get(true) && photo.controller.get(true) != self) restore_photography(false);
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
    if (ready.load(std::memory_order_acquire) && game_call()) { identify_main_target(self, texture); observe_image(self, texture); }
}
void target_late_hook(void *self, Method *method) {
    target_late_original(self, method);
    if (ready.load(std::memory_order_acquire) && game_call()) {
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
    }
}

void photo_update(void *self, Method *method, VoidMethod original) {
    if (!ready.load(std::memory_order_acquire) || !game_call(true)) { original(self, method); return; }
    if (photo.owner.get() != self) clear_photography();
    else restore_photography(false);
    photo.owner.set(self); photo.active = true;
    ScopedValue<bool> enter(scene_enter, true); original(self, method);
}
void photo_reset(void *self, Method *method, VoidMethod original) {
    if (ready.load(std::memory_order_acquire) && game_call(true) && photo.owner.get() == self) {
        clear_photography(); ScopedValue<bool> exit(scene_exit, true); original(self, method);
    } else original(self, method);
}
void main_update_hook(void *self, Method *method) { photo_update(self, method, scene_main_update_original); }
void pano_update_hook(void *self, Method *method) { photo_update(self, method, scene_pano_update_original); }
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
        if (!remember_original_lens(camera) || !set_expanded_camera(camera)) restore_photography(true);
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
        if (!remember_original_lens(camera) || !set_expanded_camera(camera)) restore_photography(true);
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
        photo.rejected_revision = -1;
        return true;
    }
    void *image = photo.image.get(true);
    if (image) observe_image(image, target_current(image, nullptr));
    else photo.geometry_known = false;
    void *controller = photo.controller.get(true), *camera = photo.camera.get(true);
    if (controller && rt_camera(controller, nullptr) != camera) {
        restore_camera(); photo.camera.set(rt_camera(controller, nullptr));
        photo.base_known = false; photo.built_viewport = {};
        photo.rejected_revision = -1; return false;
    }
    if (!controller || !camera || !photo.geometry_known || orthographic(camera, nullptr)) {
        if (photo.expanded || photo.target_expanded) restore_photography(true);
        return false;
    }
    if (photo.rejected_revision == config.revision && photo.rejected_viewport.width == photo.viewport.width
            && photo.rejected_viewport.height == photo.viewport.height) { geometry_unsupported = true; return false; }
    if (photo.base_known && !projection_model_unchanged(camera)) {
        // The original game may change the physical gate/sensor between live
        // timeline and free-camera views. Re-measure the new model with the
        // original target on the following frame instead of retaining stale
        // projection assumptions or overwriting the game's new lens model.
        restore_photography(true);
        return false;
    }
    if (!photo.base_known) {
        ProjectionMatrix matrix{};
        projection_get(camera, &matrix, nullptr);
        if (!perspective_frustum(matrix, &photo.original_frustum)) { geometry_unsupported = true; return false; }
        photo.original.aspect = frustum_aspect(photo.original_frustum);
        photo.original.vertical_fov = fov_get_original(camera, nullptr);
        photo.original_focal = focal_get_original(camera, nullptr);
        photo.physical = physical_get(camera, nullptr);
        photo.projection_mode = projection_mode_get(camera, nullptr);
        photo.gate = gate_get(camera, nullptr);
        sensor_get(camera, &photo.sensor, nullptr); lens_get(camera, &photo.lens, nullptr);
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
    if (!has) { quality_update_original(self, method); return; }
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
    };
#undef HOOK
    for (size_t i = 0; i < sizeof hooks / sizeof hooks[0]; ++i) {
        hooks[i].stub = shadowhook_hook_func_addr(reinterpret_cast<void *>(image_base + hooks[i].entry->rva), hooks[i].replacement, hooks[i].original);
        if (!hooks[i].stub) {
            for (size_t j = i; j > 0; --j) shadowhook_unhook(hooks[j - 1].stub);
            set_state("init_failed"); return nullptr;
        }
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

#else
#include "../ios/transport.hpp"
#endif
