#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>

namespace idoly::presentation {

struct Dimensions { int width = 0, height = 0; };
struct Vec2 { float x = 0, y = 0; };
struct Rect { float x = 0, y = 0, width = 1, height = 1; };
struct Vec3 { float x = 0, y = 0, z = 0; };
struct Quaternion { float x = 0, y = 0, z = 0, w = 1; };
struct CameraState { float aspect = 0, vertical_fov = 0; Rect rect{}; };

inline bool fill_size_delta(Rect parent, Rect child, Vec2 current, Vec2 *result) {
    const float values[] = {parent.width, parent.height, child.width, child.height, current.x, current.y};
    for (float value : values) if (!std::isfinite(value)) return false;
    if (parent.width <= 0 || parent.height <= 0 || child.width <= 0 || child.height <= 0) return false;
    *result = {current.x + parent.width - child.width, current.y + parent.height - child.height};
    return std::fabs(result->x) <= 65536 && std::fabs(result->y) <= 65536;
}

inline bool center_position(Rect parent, Rect resized_child, Vec3 current, Vec3 *result) {
    const float values[] = {parent.x, parent.y, parent.width, parent.height, resized_child.x,
        resized_child.y, resized_child.width, resized_child.height, current.z};
    for (float value : values) if (!std::isfinite(value)) return false;
    *result = {parent.x + parent.width / 2 - resized_child.x - resized_child.width / 2,
        parent.y + parent.height / 2 - resized_child.y - resized_child.height / 2, current.z};
    return std::fabs(result->x) <= 65536 && std::fabs(result->y) <= 65536;
}

inline bool dimensions_valid(Dimensions value) {
    return value.width > 0 && value.height > 0 && value.width <= 32768 && value.height <= 32768;
}

inline bool camera_valid(CameraState value) {
    return std::isfinite(value.aspect) && value.aspect > 0 && value.aspect <= 32
        && std::isfinite(value.vertical_fov) && value.vertical_fov > 0 && value.vertical_fov < 179
        && std::isfinite(value.rect.x) && std::isfinite(value.rect.y)
        && std::isfinite(value.rect.width) && value.rect.width > 0
        && std::isfinite(value.rect.height) && value.rect.height > 0;
}

inline CameraState expanded_camera(CameraState original, Dimensions viewport, bool enabled) {
    if (!enabled || !camera_valid(original) || !dimensions_valid(viewport)) return original;
    const double aspect = static_cast<double>(viewport.width) / viewport.height;
    const double radians = original.vertical_fov * 3.14159265358979323846 / 180.0;
    const double vertical = 2.0 * std::atan(std::tan(radians / 2.0)
        * std::max(1.0, static_cast<double>(original.aspect) / aspect)) * 180.0 / 3.14159265358979323846;
    if (!std::isfinite(vertical) || vertical >= 179.0) return original;
    return {static_cast<float>(aspect), static_cast<float>(vertical), {0, 0, 1, 1}};
}

inline Dimensions scaled_dimensions(Dimensions original, float scale, int max_dimension) {
    if (!dimensions_valid(original) || !std::isfinite(scale) || scale < .25f || scale > 2.f
            || max_dimension < 256 || max_dimension > 4096 || max_dimension % 2) return original;
    double factor = std::min(static_cast<double>(scale),
        static_cast<double>(max_dimension) / std::max(original.width, original.height));
    auto even = [factor, max_dimension](int value) {
        return std::clamp(static_cast<int>(std::round(value * factor / 2.0)) * 2, 2, max_dimension);
    };
    return {even(original.width), even(original.height)};
}

inline bool plain_transform(Vec3 position, Vec3 scale, Quaternion rotation) {
    const float values[] = {position.x, position.y, position.z, scale.x, scale.y,
        rotation.x, rotation.y, rotation.z, rotation.w};
    for (float value : values) if (!std::isfinite(value)) return false;
    return std::fabs(scale.x - 1) < .001f && std::fabs(scale.y - 1) < .001f
        && std::fabs(rotation.x) < .001f && std::fabs(rotation.y) < .001f && std::fabs(rotation.z) < .001f
        && std::fabs(std::fabs(rotation.w) - 1) < .001f;
}

inline bool fills_parent(Rect parent, Rect child, Vec3 position, Vec3 scale, Quaternion rotation) {
    const float values[] = {parent.x, parent.y, parent.width, parent.height,
        child.x, child.y, child.width, child.height, position.x, position.y,
        scale.x, scale.y, rotation.x, rotation.y, rotation.z, rotation.w};
    for (float value : values) if (!std::isfinite(value)) return false;
    return parent.width > 0 && parent.height > 0 && child.width > 0 && child.height > 0
        && plain_transform(position, scale, rotation)
        && std::fabs(child.width - parent.width) < 2.f && std::fabs(child.height - parent.height) < 2.f
        && std::fabs(child.x + position.x - parent.x) < 2.f
        && std::fabs(child.y + position.y - parent.y) < 2.f;
}

struct Config {
    std::int64_t revision = 0;
    bool custom_graphics = false;
    int quality = 0, target_fps = 0;
    float render_scale = 1;
    int max_buffer_pixel = 4096, aa_mode = -1, shadow_resolution = 0;
    bool expand_photography = false;
};

inline int selected_fps(const Config &config, int original) {
    return config.custom_graphics && config.target_fps ? config.target_fps : original;
}

inline bool config_valid(int schema, const Config &value) {
    const bool quality = value.quality == 0 || value.quality == 10 || value.quality == 20
        || value.quality == 30 || value.quality == 40 || value.quality == 100;
    const bool fps = value.target_fps == 0 || value.target_fps == 30 || value.target_fps == 60
        || value.target_fps == 90 || value.target_fps == 120;
    const bool shadow = value.shadow_resolution == 0 || value.shadow_resolution == 512
        || value.shadow_resolution == 1024 || value.shadow_resolution == 2048 || value.shadow_resolution == 4096;
    return schema == 1 && value.revision >= 0 && quality && fps && shadow
        && std::isfinite(value.render_scale) && value.render_scale >= .25f && value.render_scale <= 2.f
        && value.max_buffer_pixel >= 256 && value.max_buffer_pixel <= 4096 && !(value.max_buffer_pixel % 2)
        && value.aa_mode >= -1 && value.aa_mode <= 2;
}
}
