#pragma once
#include "presentation_math.hpp"

namespace idoly::presentation {

enum class PanoramaUiEdge { TopLeft, BottomLeft, BottomRight };

inline bool ui_rect_valid(Rect value) {
    return std::isfinite(value.x) && std::isfinite(value.y)
        && std::isfinite(value.width) && std::isfinite(value.height)
        && value.width > 0 && value.height > 0 && value.width <= 65536 && value.height <= 65536
        && std::fabs(value.x) <= 65536 && std::fabs(value.y) <= 65536;
}

inline bool ui_position_valid(Vec3 value) {
    return std::isfinite(value.x) && std::isfinite(value.y) && std::isfinite(value.z)
        && std::fabs(value.x) <= 65536 && std::fabs(value.y) <= 65536 && std::fabs(value.z) <= 65536;
}

// Both rectangles are actual measurements in the SAME viewport transform's
// local coordinates. Their origins need not be centered or equal to zero.
inline bool panorama_ui_edge_delta(Rect old_frame, Rect full_viewport, PanoramaUiEdge edge, Vec3 *delta) {
    if (!delta || !ui_rect_valid(old_frame) || !ui_rect_valid(full_viewport)) return false;
    const float left = full_viewport.x - old_frame.x;
    const float right = full_viewport.x + full_viewport.width - old_frame.x - old_frame.width;
    const float bottom = full_viewport.y - old_frame.y;
    const float top = full_viewport.y + full_viewport.height - old_frame.y - old_frame.height;
    // This feature extends the old frame. An unexplained crop/offset must not
    // move controls towards a guessed screen boundary.
    if (left > 2 || right < -2 || bottom > 2 || top < -2) return false;
    *delta = {edge == PanoramaUiEdge::BottomRight ? right : left,
              edge == PanoramaUiEdge::TopLeft ? top : bottom, 0};
    return ui_position_valid(*delta);
}

inline bool panorama_ui_local_position(Vec3 original, Vec3 origin_in_parent,
                                      Vec3 moved_origin_in_parent, Vec3 *position) {
    if (!position || !ui_position_valid(original) || !ui_position_valid(origin_in_parent)
            || !ui_position_valid(moved_origin_in_parent)
            || std::fabs(moved_origin_in_parent.z - origin_in_parent.z) > .01f) return false;
    *position = {original.x + moved_origin_in_parent.x - origin_in_parent.x,
                 original.y + moved_origin_in_parent.y - origin_in_parent.y, original.z};
    return ui_position_valid(*position);
}

inline bool panorama_ui_same_position(Vec3 left, Vec3 right) {
    return ui_position_valid(left) && ui_position_valid(right)
        && std::fabs(left.x - right.x) < .001f && std::fabs(left.y - right.y) < .001f
        && std::fabs(left.z - right.z) < .001f;
}
}
