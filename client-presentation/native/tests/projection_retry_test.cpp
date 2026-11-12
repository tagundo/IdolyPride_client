#include "presentation_math.hpp"
#include "presentation_scope.hpp"
#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <pthread.h>

using namespace idoly::presentation;
using Method = const void;
bool object_alive(void *, Method *);
struct WeakMock {
    void *value = nullptr;
    void *get(bool unity_object = false) const {
        return value && (!unity_object || object_alive(value, nullptr)) ? value : nullptr;
    }
    void set(void *next) { value = next; }
    void clear() { value = nullptr; }
};
struct CameraMock {
    bool alive = true, physical = true, manual_aspect = false, invalid_matrix = false, throw_matrix = false;
    float focal = 35, ordinary_fov = 50, automatic_aspect = 4.f / 3, aspect_override = 0;
    Vec2 sensor{36, 24}, lens{};
    int gate = 0, projection_mode = 1;
    unsigned aspect_resets = 0;
    Rect rect{0, 0, 1, 1};
};
struct TextureMock { int width = 1600, height = 1200; } texture;
struct ControllerMock { CameraMock *camera = nullptr; } controller;
struct PhotoMock {
    WeakMock owner, controller, camera, image, viewport_parent;
    bool active = true, geometry_known = true, base_known = true, expanded = true, target_expanded = true;
    Vec2 ratio{16, 9};
    Dimensions viewport{1600, 1200}, built_viewport{1600, 1200}, rejected_viewport{};
    int64_t rejected_revision = -1;
    CameraState original{};
    Frustum original_frustum{};
    float original_focal = 35;
    bool physical = true;
    int gate = 0, projection_mode = 1;
    Vec2 sensor{36, 24}, lens{};
} photo;
struct ReportState { const char *state = "applied"; bool expanded = true; } state;
pthread_mutex_t status_mutex = PTHREAD_MUTEX_INITIALIZER;
thread_local bool internal_camera = false;
Config config;
unsigned target_rebuilds = 0, rollback_calls = 0;
bool object_alive(void *self, Method *) {
    return self && (self == &controller || self == &texture || static_cast<CameraMock *>(self)->alive);
}

static float raw_fov(CameraMock &camera) {
    return camera.physical ? static_cast<float>(std::atan(camera.sensor.y / (2 * camera.focal)) * 360 / 3.14159265358979323846)
                           : camera.ordinary_fov;
}
static float aspect(void *self, Method *) {
    auto &camera = *static_cast<CameraMock *>(self);
    return camera.manual_aspect ? camera.aspect_override : camera.automatic_aspect;
}
static ProjectionMatrix camera_projection(CameraMock &camera, float ratio) {
    const float tangent = std::tan(raw_fov(camera) * 3.14159265358979323846 / 360);
    const float vertical = tangent * (camera.gate == 2 ? camera.sensor.x / camera.sensor.y / ratio : 1.f);
    ProjectionMatrix matrix{};
    matrix.values[0] = 1 / (vertical * ratio); matrix.values[5] = 1 / vertical;
    matrix.values[8] = camera.lens.x; matrix.values[9] = camera.lens.y;
    matrix.values[10] = -1.01f; matrix.values[11] = camera.invalid_matrix ? 0 : -1;
    matrix.values[14] = -.2f;
    return matrix;
}
static void get_projection(void *self, ProjectionMatrix *output, Method *) {
    auto &camera = *static_cast<CameraMock *>(self);
    if (camera.throw_matrix) throw 1;
    *output = camera_projection(camera, aspect(self, nullptr));
}
static void set_focal(void *self, float value, Method *) { static_cast<CameraMock *>(self)->focal = value; }
static void set_fov(void *self, float value, Method *) {
    auto &camera = *static_cast<CameraMock *>(self); camera.ordinary_fov = value;
    if (camera.physical) camera.focal = camera.sensor.y / (2 * std::tan(value * 3.14159265358979323846 / 360));
}
static void set_aspect(void *self, float value, Method *) {
    auto &camera = *static_cast<CameraMock *>(self); camera.manual_aspect = true; camera.aspect_override = value;
}
static void reset_aspect(void *self, Method *) {
    auto &camera = *static_cast<CameraMock *>(self); camera.manual_aspect = false; ++camera.aspect_resets;
}
static float get_fov(void *self, Method *) { return raw_fov(*static_cast<CameraMock *>(self)); }
static float get_focal(void *self, Method *) { return static_cast<CameraMock *>(self)->focal; }
static bool get_physical(void *self, Method *) { return static_cast<CameraMock *>(self)->physical; }
static int get_mode(void *self, Method *) { return static_cast<CameraMock *>(self)->projection_mode; }
static int get_gate(void *self, Method *) { return static_cast<CameraMock *>(self)->gate; }
static void get_sensor(void *self, Vec2 *output, Method *) { *output = static_cast<CameraMock *>(self)->sensor; }
static void get_lens(void *self, Vec2 *output, Method *) { *output = static_cast<CameraMock *>(self)->lens; }
static void get_rect(void *self, Rect *output, Method *) { *output = static_cast<CameraMock *>(self)->rect; }
static void *get_target(void *, Method *) { return &texture; }
static void *get_camera(void *self, Method *) { return static_cast<ControllerMock *>(self)->camera; }
static void *to_texture(void *self, Method *) { return self; }
static int get_width(void *self, Method *) { return static_cast<TextureMock *>(self)->width; }
static int get_height(void *self, Method *) { return static_cast<TextureMock *>(self)->height; }

float (*aspect_get_original)(void *, Method *) = aspect;
float (*fov_get_original)(void *, Method *) = get_fov;
float (*focal_get_original)(void *, Method *) = get_focal;
void (*fov_set_original)(void *, float, Method *) = set_fov;
void (*focal_set_original)(void *, float, Method *) = set_focal;
void (*camera_aspect_set_original)(void *, float, Method *) = set_aspect;
void (*camera_aspect_reset)(void *, Method *) = reset_aspect;
void (*projection_get)(void *, ProjectionMatrix *, Method *) = get_projection;
bool (*physical_get)(void *, Method *) = get_physical;
int (*projection_mode_get)(void *, Method *) = get_mode;
int (*gate_get)(void *, Method *) = get_gate;
void (*sensor_get)(void *, Vec2 *, Method *) = get_sensor;
void (*lens_get)(void *, Vec2 *, Method *) = get_lens;
void (*camera_rect_get)(void *, Rect *, Method *) = get_rect;
void *(*rt_target)(void *, Method *) = get_target;
void *(*rt_camera)(void *, Method *) = get_camera;
void *(*target_to_texture)(void *, Method *) = to_texture;
int (*rt_width)(void *, Method *) = get_width;
int (*rt_height)(void *, Method *) = get_height;
bool runtime_type(void *self, const char *name) { return self == &texture && !std::strcmp(name, "RenderTexture"); }
bool full_rect(Rect rect) { return rect.x == 0 && rect.y == 0 && rect.width == 1 && rect.height == 1; }
void update_camera_metrics(void *) {}

#include "verified_projection_refresh.hpp"

Config configuration() { return config; }
struct PanoramaUiMock { void restore() {} } panorama_ui;
void restore_photography(bool rebuild) {
    ++rollback_calls;
    if (rebuild) {
        ++target_rebuilds;
        controller.camera->automatic_aspect = 16.f / 9;
        texture = {1600, 900};
    }
    photo.expanded = photo.target_expanded = photo.base_known = photo.geometry_known = false;
}
#include "projection_rejection_retry.hpp"

static void seed(CameraMock &camera) {
    photo = {}; config.revision = 10; texture = {1600, 1200}; controller.camera = &camera;
    photo.controller.set(&controller); photo.camera.set(&camera); photo.owner.set(&camera);
    photo.original_focal = camera.focal; photo.original.vertical_fov = raw_fov(camera);
    photo.original.aspect = 16.f / 9;
    assert(perspective_frustum(camera_projection(camera, 16.f / 9), &photo.original_frustum));
    assert(remember_projection_model(&camera));
    target_rebuilds = rollback_calls = 0;
}

int main() {
    CameraMock camera; seed(camera);
    for (unsigned frame = 0; frame < 120; ++frame) {
        camera.gate = frame % 2 ? 0 : 2;
        camera.sensor = {36.f + frame * .001f, 24.f + frame * .002f};
        camera.lens = {.2f * static_cast<float>(std::sin(frame * .07)), 0};
        photo.original_focal = 35.f + 3.f * static_cast<float>(std::sin(frame * .1));
        set_focal(&camera, photo.original_focal, nullptr); // An original Cinemachine write.
        assert(set_expanded_camera(&camera));
        assert(!camera.manual_aspect && std::fabs(aspect(&camera, nullptr) - 4.f / 3) < .00001f);
        assert(projection_model_unchanged(&camera));
        Frustum actual{};
        assert(perspective_frustum(camera_projection(camera, aspect(&camera, nullptr)), &actual));
        assert(frustum_contains(actual, photo.original_frustum));
        assert(target_rebuilds == 0 && rollback_calls == 0);
    }
    assert(camera.aspect_resets == 120);
    camera.lens.x += .01f; camera.throw_matrix = true;
    try { set_expanded_camera(&camera); assert(false); } catch (int) {}
    assert(!camera.manual_aspect && camera.aspect_resets == 121 && !internal_camera);

    camera = {}; seed(camera); camera.lens.x = .1f; camera.invalid_matrix = true;
    unsigned attempts = 0;
    for (unsigned frame = 0; frame < 120; ++frame) {
        if (!projection_rejected_for(config)) {
            ++attempts;
            if (!set_expanded_camera(&camera)) reject_current_projection();
        }
    }
    assert(attempts == 1 && target_rebuilds == 1 && rollback_calls == 1);
    assert(!camera.manual_aspect && !std::strcmp(state.state, "unsupported") && !state.expanded);
    assert(projection_rejected_for(config));
    ++config.revision; assert(!projection_rejected_for(config)); --config.revision;
    ++photo.viewport.width; assert(!projection_rejected_for(config)); --photo.viewport.width;
    assert(projection_rejected_for(config));
    clear_photography(); assert(!projection_rejected_for(config));
    assert(!photo.owner.get() && !photo.camera.get() && !photo.controller.get());

    // A new camera behind the same controller gets one original-ratio reset,
    // not a permanently wide first baseline or repeated per-frame rebuild.
    camera = {}; seed(camera); CameraMock replacement;
    controller.camera = &replacement;
    photo.rejected_revision = config.revision; photo.rejected_viewport = photo.viewport;
    assert(synchronize_photo_camera(&controller, &camera));
    assert(target_rebuilds == 1 && photo.camera.get() == &replacement && !photo.base_known);
    assert(!projection_rejected_for(config) && replacement.automatic_aspect == 16.f / 9);
    for (unsigned frame = 0; frame < 120; ++frame)
        assert(!synchronize_photo_camera(&controller, photo.camera.get()));
    assert(target_rebuilds == 1);

    camera = {}; seed(camera); camera.alive = false;
    assert(photo.camera.get(true) == nullptr && controller.camera == &camera);
    for (unsigned frame = 0; frame < 120; ++frame)
        assert(synchronize_photo_camera(&controller, photo.camera.get(true)));
    assert(target_rebuilds == 0 && rollback_calls == 1);
    controller.camera = nullptr;
    assert(synchronize_photo_camera(&controller, photo.camera.get(true)));
    assert(target_rebuilds == 0 && rollback_calls == 1);

    camera = {}; seed(camera); controller.camera = nullptr;
    assert(synchronize_photo_camera(&controller, photo.camera.get(true)));
    assert(photo.camera.get() == nullptr && target_rebuilds == 0);
    controller.camera = &camera;
    assert(synchronize_photo_camera(&controller, photo.camera.get(true)));
    assert(photo.camera.get(true) == &camera && target_rebuilds == 1);
    assert(!synchronize_photo_camera(&controller, photo.camera.get(true)) && target_rebuilds == 1);

    // A preexisting manual camera policy is not replaced with a fabricated
    // automatic aspect merely to make expansion succeed.
    camera = {}; seed(camera); camera.manual_aspect = true; camera.aspect_override = 2;
    camera.lens.x = .1f;
    assert(!set_expanded_camera(&camera));
    assert(camera.manual_aspect && camera.aspect_resets == 0);
}
