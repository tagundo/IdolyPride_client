#include "presentation_math.hpp"
#include "presentation_scope.hpp"
#include <cassert>
#include <cmath>
#include <limits>

using namespace idoly::presentation;

static double tangent(float degrees) { return std::tan(degrees * 3.14159265358979323846 / 360.0); }

int main() {
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
