#include "presentation_math.hpp"
#include "presentation_scope.hpp"
#include <cassert>
#include <cmath>
#include <limits>

using namespace idoly::presentation;

static double tangent(float degrees) { return std::tan(degrees * 3.14159265358979323846 / 360.0); }

static ProjectionMatrix lens_projection(float raw_fov, float aspect, bool horizontal_gate, float shift = 0) {
    const float vertical = static_cast<float>(tangent(raw_fov)) * (horizontal_gate ? 1.5f / aspect : 1.f);
    ProjectionMatrix matrix{};
    matrix.values[0] = 1.f / (vertical * aspect);
    matrix.values[5] = 1.f / vertical;
    matrix.values[8] = shift;
    matrix.values[9] = -shift / 2;
    matrix.values[10] = -1.01f;
    matrix.values[11] = -1;
    matrix.values[14] = -.2f;
    return matrix;
}

int main() {
    // A physical lens can be driven by focalLength in Cinemachine LateUpdate,
    // after the ordinary fieldOfView override. The raw FOV readback alone is
    // insufficient: an unchanged Vertical-gate 4:3 projection clips both of
    // the original 16:9 horizontal edge rays.
    for (bool horizontal_gate : {false, true}) {
        for (float shift : {0.f, .2f}) {
            Frustum baseline{};
            assert(perspective_frustum(lens_projection(50, 16.f / 9, horizontal_gate, shift), &baseline));
            for (float aspect : {16.f / 9, 4.f / 3, 21.f / 9}) {
                Frustum before{}, after{};
                assert(perspective_frustum(lens_projection(50, aspect, horizontal_gate, shift), &before));
                if (!horizontal_gate && aspect < 16.f / 9) assert(!frustum_contains(before, baseline));
                float desired = 0;
                assert(expanded_raw_fov(baseline, before, 50, &desired));
                assert(perspective_frustum(lens_projection(desired, aspect, horizontal_gate, shift), &after));
                assert(frustum_contains(after, baseline));
                assert(std::fabs(frustum_aspect(after) - aspect) < .00001f);
                if (aspect < 16.f / 9) {
                    // Preserve the old left and right edges; only top and
                    // bottom grow. A Horizontal gate already does that, so
                    // applying the plain vertical-gate formula twice would
                    // unnecessarily zoom out.
                    assert(std::fabs(after.left - baseline.left) < .00001f);
                    assert(std::fabs(after.right - baseline.right) < .00001f);
                    assert(after.bottom > baseline.bottom && after.top > baseline.top);
                    assert(horizontal_gate ? std::fabs(desired - 50) < .00001f : desired > 50);
                }
                if (aspect > 16.f / 9) {
                    assert(std::fabs(after.bottom - baseline.bottom) < .00001f);
                    assert(std::fabs(after.top - baseline.top) < .00001f);
                    assert(after.left > baseline.left && after.right > baseline.right);
                }
                // A subsequent original focalLength change describes a new
                // baseline lens, not the expanded value from the prior frame.
                Frustum updated{}, expected{};
                assert(rescale_frustum(baseline, 50, 65, &updated));
                assert(perspective_frustum(lens_projection(65, 16.f / 9, horizontal_gate, shift), &expected));
                assert(std::fabs(updated.left - expected.left) < .00001f);
                assert(std::fabs(updated.bottom - expected.bottom) < .00001f);
            }
        }
    }
    ProjectionMatrix invalid_projection = lens_projection(50, 16.f / 9, false);
    Frustum invalid_frustum{};
    invalid_projection.values[11] = 0; // Orthographic/custom projection must not be guessed.
    assert(!perspective_frustum(invalid_projection, &invalid_frustum));
    invalid_projection = lens_projection(50, 16.f / 9, false);
    invalid_projection.values[1] = .1f; // A sheared projection is unsupported.
    assert(!perspective_frustum(invalid_projection, &invalid_frustum));
    invalid_projection.values[1] = 0;
    invalid_projection.values[12] = .1f; // Depth-dependent clip translation is unsupported.
    assert(!perspective_frustum(invalid_projection, &invalid_frustum));
    invalid_projection.values[12] = 0;
    invalid_projection.values[5] = std::numeric_limits<float>::quiet_NaN();
    assert(!perspective_frustum(invalid_projection, &invalid_frustum));
    float invalid_fov = 0;
    assert(!expanded_raw_fov({}, {}, 50, &invalid_fov));
    CameraState original{16.f / 9.f, 50.f, {.1f, .2f, .8f, .7f}};
    for (Dimensions viewport : {Dimensions{1920, 1080}, {2520, 1080}, {1440, 1080}}) {
        CameraState result = expanded_camera(original, viewport, true);
        assert(result.rect.x == 0 && result.rect.y == 0 && result.rect.width == 1 && result.rect.height == 1);
        // Compare center-frame rays: all original corner rays remain inside
        // the new frustum. This verifies additional world coverage, without a
        // crop, a zoomed texture, or a change in camera position.
        assert(tangent(result.vertical_fov) + 1e-6 >= tangent(original.vertical_fov));
        assert(tangent(result.vertical_fov) * result.aspect + 1e-6 >= tangent(original.vertical_fov) * original.aspect);
        if (viewport.width >= 1920) assert(std::abs(result.vertical_fov - original.vertical_fov) < 1e-4);
        else assert(result.vertical_fov > original.vertical_fov);
        Rect parent{-viewport.width / 2.f, -viewport.height / 2.f,
            static_cast<float>(viewport.width), static_cast<float>(viewport.height)};
        Rect child{parent.x, 0, parent.width, parent.height};
        assert(fills_parent(parent, child, {0, parent.y, 0}, {1, 1, 1}, {}));
        assert(!fills_parent(parent, child, {5, parent.y, 0}, {1, 1, 1}, {}));
        assert(!fills_parent(parent, child, {0, parent.y, 0}, {.5f, .5f, 1}, {}));
        assert(!fills_parent(parent, child, {0, parent.y, 0}, {1, 1, 1}, {0, 0, .7f, .7f}));
        Rect small{child.x / 2, 0, child.width / 2, child.height / 2};
        assert(!fills_parent(parent, small, {0, parent.y, 0}, {1, 1, 1}, {}));
        CameraState restored = expanded_camera(original, viewport, false);
        assert(restored.aspect == original.aspect && restored.vertical_fov == original.vertical_fov);
        assert(restored.rect.x == original.rect.x && restored.rect.width == original.rect.width);
    }
    for (Dimensions invalid : {Dimensions{0, 1080}, {-1, 0}, {40000, 100}}) {
        CameraState unchanged = expanded_camera(original, invalid, true);
        assert(unchanged.aspect == original.aspect && unchanged.vertical_fov == original.vertical_fov);
    }
    CameraState invalid = original;
    invalid.vertical_fov = std::numeric_limits<float>::quiet_NaN();
    assert(std::isnan(expanded_camera(invalid, {1440, 1080}, true).vertical_fov));
    // Original level4/5 contains both a fixed 1920x1080 target and a stretched
    // target, with applyAspectRatio=false. Only the latter proves a complete
    // 4:3 viewport without adding a fitter or changing RectTransform layout.
    const Rect folded_parent{-1000, -750, 2000, 1500};
    assert(!fills_parent(folded_parent, {-960, -540, 1920, 1080}, {}, {1, 1, 1}, {}));
    assert(fills_parent(folded_parent, folded_parent, {}, {1, 1, 1}, {}));
    // The active horizontal original target has pivot(.5,0), centered X and
    // bottom localPosition=-540. SizeDelta growth must preserve that pivot;
    // the separate position calculation centers the new full-height image.
    for (Rect parent : {folded_parent, Rect{-1260, -540, 2520, 1080}, Rect{-540, -1170, 1080, 2340}}) {
        const Vec2 original_delta{1920, 1080};
        const Vec3 original_position{0, -540, 7};
        const Rect fixed_child{-960, 0, 1920, 1080};
        Vec2 resized{};
        assert(fill_size_delta(parent, fixed_child, original_delta, &resized));
        assert(resized.x == parent.width && resized.y == parent.height);
        const Rect resized_child{-resized.x / 2, 0, resized.x, resized.y};
        Vec3 centered{};
        assert(center_position(parent, resized_child, original_position, &centered));
        assert(centered.z == original_position.z);
        assert(fills_parent(parent, resized_child, centered, {1, 1, 1}, {}));
        // Restoring exact saved sizeDelta/localPosition reconstructs the
        // original horizontal rectangle rather than leaving the full frame.
        assert(original_delta.x == 1920 && original_delta.y == 1080 && original_position.y == -540);
    }
    Vec2 invalid_delta{}; Vec3 invalid_position{};
    assert(!fill_size_delta({0, 0, 0, 1080}, folded_parent, {}, &invalid_delta));
    assert(!fill_size_delta(folded_parent, {0, 0, std::numeric_limits<float>::quiet_NaN(), 1080}, {}, &invalid_delta));
    assert(!center_position(folded_parent, folded_parent, {0, 0, std::numeric_limits<float>::infinity()}, &invalid_position));
    for (Dimensions size : {Dimensions{1920, 1080}, {2520, 1080}, {1440, 1080}}) {
        Dimensions scaled = scaled_dimensions(size, 1.5f, 2048);
        assert(scaled.width <= 2048 && scaled.height <= 2048 && !(scaled.width % 2) && !(scaled.height % 2));
        assert(std::abs(static_cast<double>(scaled.width) / scaled.height
            - static_cast<double>(size.width) / size.height) < .005);
    }
    assert(scaled_dimensions({0, 0}, 1, 4096).width == 0);
    const Dimensions rounded = scaled_dimensions({1080, 2340}, .75f, 4096);
    assert(rounded.width == 810 && rounded.height == 1756);
    const CameraState rounded_camera = expanded_camera(original, rounded, true);
    assert(std::abs(rounded_camera.aspect - static_cast<float>(rounded.width) / rounded.height) < .00001f);
    assert(tangent(rounded_camera.vertical_fov) * rounded_camera.aspect + 1e-6
        >= tangent(original.vertical_fov) * original.aspect);
    Config config;
    assert(config_valid(1, config));
    config.expand_photography = true;
    assert(config_valid(1, config)); // Independent from custom graphics.
    config.max_buffer_pixel = 1023;
    assert(!config_valid(1, config));
    config.max_buffer_pixel = 4096;
    config.render_scale = std::numeric_limits<float>::infinity();
    assert(!config_valid(1, config));
    config.render_scale = 1;
    config.target_fps = 144;
    assert(!config_valid(1, config));
    config.target_fps = 0;
    assert(!config_valid(2, config));
    config.target_fps = 120;
    config.custom_graphics = false;
    assert(selected_fps(config, 30) == 30 && selected_fps(config, -1) == -1);
    config.custom_graphics = true;
    assert(selected_fps(config, 30) == 120);
    config.target_fps = 0;
    assert(selected_fps(config, 60) == 60);
    bool scoped = false;
    int field = 7;
    try {
        ScopedValue<bool> flag(scoped, true);
        ScopedMemory<int> saved(&field, 0, true);
        saved.set(11);
        assert(scoped && field == 11);
        throw 1;
    } catch (int) { }
    assert(!scoped && field == 7);
}
