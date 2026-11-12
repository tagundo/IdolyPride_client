#include "panorama_ui_edges.hpp"
#include <array>
#include <cassert>
#include <cmath>
#include <cstring>
#include <limits>
#include <map>
#include <string>

using namespace idoly::presentation;

struct Object {
    alignas(8) unsigned char bytes[512]{};
    const char *space;
    const char *name;
    bool alive = true, collected = false, active_ui = true;
    Object *parent = nullptr, *transform = nullptr;
    Vec3 position{}, scale{1, 1, 1};
    float angle = 0;
    Object(const char *space, const char *name) : space(space), name(name) { }
    void *pointer() { return bytes; }
};
static std::map<void *, Object *> objects;
static std::map<uint32_t, void *> handles;
static uint32_t sequence = 1;
static unsigned visibility_writes = 0, gameobject_reads = 0;
static unsigned viewport_point_reads = 0, parent_point_reads = 0;
static unsigned position_writes = 0;
static Object *throw_on = nullptr;
static bool write_before_throw = false;

static Object &object(void *pointer) { assert(objects.count(pointer)); return *objects.at(pointer); }
static uint32_t weak_new(void *pointer, bool pinned) {
    assert(!pinned); object(pointer); const uint32_t result = sequence++; handles[result] = pointer; return result;
}
static void *weak_get(uint32_t handle) {
    assert(handles.count(handle)); void *pointer = handles.at(handle);
    return object(pointer).collected ? nullptr : pointer;
}
static void weak_free(uint32_t handle) { assert(handles.erase(handle) == 1); }
static bool alive(void *pointer, const void *) { return object(pointer).alive; }
static bool matches(void *pointer, const char *space, const char *name) {
    const auto &value = object(pointer);
    return !std::strcmp(value.space, space) && (!std::strcmp(value.name, name)
        || (!std::strcmp(name, "SolisButton") && !std::strcmp(value.name, "TextButton")));
}
static void *component_transform(void *pointer, const void *) {
    auto &value = object(pointer); assert(std::strcmp(value.name, "GameObject"));
    return value.transform ? value.transform->pointer() : nullptr;
}
static void *gameobject_transform(void *pointer, const void *) {
    auto &value = object(pointer); assert(!std::strcmp(value.name, "GameObject")); ++gameobject_reads;
    return value.transform ? value.transform->pointer() : nullptr;
}
static void *parent(void *pointer, const void *) {
    auto &value = object(pointer); assert(value.alive);
    return value.parent ? value.parent->pointer() : nullptr;
}
static void position_get(void *pointer, Vec3 *result, const void *) {
    auto &value = object(pointer); assert(value.alive); *result = value.position;
}
static void position_set(void *pointer, const Vec3 *position, const void *) {
    auto &value = object(pointer); assert(value.alive);
    ++position_writes;
    if (&value == throw_on) {
        throw_on = nullptr;
        if (write_before_throw) value.position = *position;
        throw 7;
    }
    value.position = *position;
}
static Vec3 world_point(Object &value, Vec3 point) {
    const float c = std::cos(value.angle), s = std::sin(value.angle);
    Vec3 result{value.position.x + c * point.x * value.scale.x - s * point.y * value.scale.y,
                value.position.y + s * point.x * value.scale.x + c * point.y * value.scale.y,
                value.position.z + point.z * value.scale.z};
    return value.parent ? world_point(*value.parent, result) : result;
}
static Vec3 local_point(Object &value, Vec3 point) {
    if (value.parent) point = local_point(*value.parent, point);
    const float x = point.x - value.position.x, y = point.y - value.position.y;
    const float c = std::cos(value.angle), s = std::sin(value.angle);
    return {(c * x + s * y) / value.scale.x, (-s * x + c * y) / value.scale.y,
            (point.z - value.position.z) / value.scale.z};
}
static void transform_point(void *pointer, const Vec3 *point, Vec3 *result, const void *) {
    ++viewport_point_reads;
    *result = world_point(object(pointer), *point);
}
static void inverse_transform_point(void *pointer, const Vec3 *point, Vec3 *result, const void *) {
    ++parent_point_reads;
    *result = local_point(object(pointer), *point);
}
static bool ui_active_get(void *pointer, const void *) { return object(pointer).active_ui; }
static void ui_active_set(void *pointer, bool active, const void *) {
    ++visibility_writes; object(pointer).active_ui = active;
}
template<class T> static void field(Object &value, size_t offset, T contents) {
    std::memcpy(value.bytes + offset, &contents, sizeof contents);
}
static bool close(Vec3 left, Vec3 right) {
    return std::fabs(left.x - right.x) < .002f && std::fabs(left.y - right.y) < .002f
        && std::fabs(left.z - right.z) < .002f;
}

struct Scene {
    Object owner{"Solis.Photography", "Photography360LiveContentPresenter"};
    Object content{"Solis.Photography", "Photography360LiveContentView"};
    Object control{"Solis.Photography", "Photography360LiveControlPresenter"};
    Object view{"Solis.Photography", "Photography360LiveView"};
    Object model{"Solis.Photography", "Photography360LiveContentModel"};
    Object reactive{"UniRx", "ReactiveProperty"};
    Object viewport{"UnityEngine", "RectTransform"};
    Object preview_parent{"UnityEngine", "RectTransform"};
    Object camera_parent{"UnityEngine", "RectTransform"};
    Object popup_parent{"UnityEngine", "RectTransform"};
    Object ui{"Solis.Common", "TextButton"}, end{"Solis.Common", "TextButton"};
    Object button{"Solis.Common", "SolisButton"}, balloon{"UnityEngine", "GameObject"};
    Object popup{"UnityEngine", "CanvasGroup"};
    std::array<Object, 5> rects{{{"UnityEngine", "RectTransform"}, {"UnityEngine", "RectTransform"},
        {"UnityEngine", "RectTransform"}, {"UnityEngine", "RectTransform"}, {"UnityEngine", "RectTransform"}}};
    std::array<Vec3, 5> baseline{};
    Scene() {
        Object *values[]{&owner, &content, &control, &view, &model, &reactive, &viewport,
            &preview_parent, &camera_parent, &popup_parent, &ui, &end, &button, &balloon, &popup};
        for (auto *value : values) objects[value->pointer()] = value;
        for (auto &value : rects) objects[value.pointer()] = &value;
        field(owner, 0x50, content.pointer()); field(owner, 0x38, control.pointer()); field(owner, 0x58, model.pointer());
        field(control, 0x20, view.pointer()); field(control, 0xa8, true);
        field(model, 0x10, reactive.pointer()); field(model, 0x18, false);
        field(content, 0x28, ui.pointer()); field(content, 0x30, end.pointer());
        field(view, 0xb0, button.pointer()); field(view, 0xa8, balloon.pointer()); field(view, 0x128, popup.pointer());
        ui.transform = &rects[0]; end.transform = &rects[1]; button.transform = &rects[2];
        balloon.transform = &rects[3]; popup.transform = &rects[4];
        rects[0].parent = rects[1].parent = &preview_parent;
        rects[2].parent = rects[3].parent = &camera_parent; rects[4].parent = &popup_parent;
        viewport.position = {31, -13, 9}; viewport.angle = .3f; viewport.scale = {.8f, 1.1f, 1};
        preview_parent.position = {12, -7, 4}; preview_parent.angle = -.2f; preview_parent.scale = {1.25f, .75f, 1};
        camera_parent.position = {-23, 41, 2}; camera_parent.angle = .7f; camera_parent.scale = {.9f, 1.1f, 1};
        popup_parent.position = {50, -39, 7}; popup_parent.angle = -.6f; popup_parent.scale = {1.1f, 1.3f, 1};
        preview_parent.parent = &viewport; camera_parent.parent = &preview_parent;
        for (unsigned i = 0; i < 5; ++i) {
            baseline[i] = {70.f + i * 10, -30.f + i * 20, 1}; rects[i].position = baseline[i];
        }
    }
    ~Scene() {
        assert(handles.empty()); objects.clear();
    }
};

static PanoramaEdgeApi api() {
    return {weak_new, weak_get, weak_free, alive, matches, component_transform, gameobject_transform, parent,
        position_get, position_set, transform_point, inverse_transform_point, ui_active_get, ui_active_set};
}
static const Rect old_frame{-960, -540, 1920, 1080};
static const Rect square{-960, -720, 1920, 1440};

int main() {
    Vec3 delta{}, position{};
    assert(panorama_ui_edge_delta(old_frame, square, PanoramaUiEdge::TopLeft, &delta) && close(delta, {0, 180, 0}));
    assert(panorama_ui_edge_delta(old_frame, square, PanoramaUiEdge::BottomLeft, &delta) && close(delta, {0, -180, 0}));
    assert(panorama_ui_edge_delta(old_frame, {-1280, -540, 2560, 1080}, PanoramaUiEdge::BottomRight, &delta)
        && close(delta, {320, 0, 0}));
    assert(!panorama_ui_edge_delta(old_frame, {-700, -540, 1400, 1080}, PanoramaUiEdge::TopLeft, &delta));
    assert(!panorama_ui_edge_delta(old_frame, {0, 0, std::numeric_limits<float>::quiet_NaN(), 100}, PanoramaUiEdge::TopLeft, &delta));
    assert(!panorama_ui_local_position({}, {}, {0, 0, 1}, &position));

    {
        Scene scene; PanoramaEdgeLayout layout; layout.configure(api());
        field(scene.control, 0xa8, false);
        const unsigned before = visibility_writes;
        assert(!layout.begin_session(scene.owner.pointer()) && visibility_writes == before);
        field(scene.control, 0xa8, true);
        assert(layout.begin_session(scene.owner.pointer()) && !scene.model.active_ui && visibility_writes == before + 1);
        ui_active_set(scene.model.pointer(), true, nullptr); // Original UI-ON user interaction.
        for (unsigned frame = 0; frame < 120; ++frame) assert(layout.begin_session(scene.owner.pointer()));
        assert(scene.model.active_ui && visibility_writes == before + 2);
        std::array<Vec3, 5> old_world{};
        for (unsigned i = 0; i < 5; ++i) old_world[i] = world_point(scene.rects[i], {});
        assert(layout.update(scene.owner.pointer(), scene.viewport.pointer(), square, old_frame));
        for (unsigned i = 0; i < 5; ++i) {
            const Vec3 local_delta{0, i == 0 ? 180.f : -180.f, 0};
            const Vec3 origin = world_point(scene.viewport, {}), moved = world_point(scene.viewport, local_delta);
            const Vec3 current = world_point(scene.rects[i], {});
            assert(close({current.x - old_world[i].x, current.y - old_world[i].y, current.z - old_world[i].z},
                         {moved.x - origin.x, moved.y - origin.y, moved.z - origin.z}));
        }
        const Vec3 popup_after = scene.rects[4].position;
        const unsigned stable_writes = position_writes;
        for (unsigned frame = 0; frame < 120; ++frame)
            assert(layout.update(scene.owner.pointer(), scene.viewport.pointer(), square, old_frame));
        assert(close(scene.rects[4].position, popup_after));
        assert(position_writes == stable_writes);
        layout.restore_layout();
        for (unsigned i = 0; i < 5; ++i) assert(close(scene.rects[i].position, scene.baseline[i]));
        assert(scene.model.active_ui && layout.begin_session(scene.owner.pointer()));
        assert(scene.model.active_ui && visibility_writes == before + 2);
        layout.restore(); assert(handles.empty());
        assert(layout.begin_session(scene.owner.pointer()) && !scene.model.active_ui && visibility_writes == before + 3);
        layout.restore();
    }
    {
        Scene scene; PanoramaEdgeLayout layout; layout.configure(api());
        const unsigned points_before = viewport_point_reads, parents_before = parent_point_reads;
        assert(layout.update(scene.owner.pointer(), scene.viewport.pointer(), square, old_frame));
        assert(viewport_point_reads == points_before + 4 && parent_point_reads == parents_before + 7);
        // A later call must read the changed viewport AND each changed parent;
        // no world point or parent conversion may survive across updates.
        scene.viewport.angle += .27f; scene.viewport.scale = {1.2f, .65f, 1};
        scene.camera_parent.angle -= .13f; scene.popup_parent.scale = {.7f, 1.4f, 1};
        const Rect wider{-1280, -720, 2560, 1440};
        assert(layout.update(scene.owner.pointer(), scene.viewport.pointer(), wider, old_frame));
        assert(viewport_point_reads == points_before + 8 && parent_point_reads == parents_before + 14);
        for (unsigned i = 0; i < 5; ++i) {
            const Vec3 corner_delta{i < 2 ? -320.f : 320.f, i == 0 ? 180.f : -180.f, 0};
            const Vec3 origin = local_point(*scene.rects[i].parent, world_point(scene.viewport, {}));
            const Vec3 moved = local_point(*scene.rects[i].parent, world_point(scene.viewport, corner_delta));
            assert(close(scene.rects[i].position, {scene.baseline[i].x + moved.x - origin.x,
                scene.baseline[i].y + moved.y - origin.y, scene.baseline[i].z}));
        }
        layout.restore();
        for (unsigned i = 0; i < 5; ++i) assert(close(scene.rects[i].position, scene.baseline[i]));
    }
    {
        Scene scene; Object replacement{"UnityEngine", "RectTransform"};
        objects[replacement.pointer()] = &replacement;
        replacement.parent = &scene.popup_parent; replacement.position = {41, 42, 1};
        PanoramaEdgeLayout layout; layout.configure(api());
        assert(layout.update(scene.owner.pointer(), scene.viewport.pointer(), square, old_frame));
        // Even an old target reparented above the viewport cannot leave stale
        // points after the binding replacement restores its original position.
        scene.viewport.parent = &scene.rects[4]; scene.popup.transform = &replacement;
        const unsigned points_before = viewport_point_reads, parents_before = parent_point_reads;
        assert(layout.update(scene.owner.pointer(), scene.viewport.pointer(), square, old_frame));
        assert(close(scene.rects[4].position, scene.baseline[4]));
        assert(viewport_point_reads == points_before + 6 && parent_point_reads == parents_before + 7);
        const Vec3 origin = local_point(scene.popup_parent, world_point(scene.viewport, {}));
        const Vec3 moved = local_point(scene.popup_parent, world_point(scene.viewport, {0, -180, 0}));
        assert(close(replacement.position, {41 + moved.x - origin.x, 42 + moved.y - origin.y, 1}));
        layout.restore(); assert(close(replacement.position, {41, 42, 1}));
    }
    {
        Scene scene; PanoramaEdgeLayout layout; layout.configure(api());
        for (auto &value : scene.rects) value.parent = &scene.preview_parent;
        const unsigned points_before = viewport_point_reads, parents_before = parent_point_reads;
        const Rect wider{-1280, -720, 2560, 1440};
        assert(layout.update(scene.owner.pointer(), scene.viewport.pointer(), wider, old_frame));
        // Shared parent still has three distinct edge points; only the three
        // right-hand controls share the exact same parent+edge conversion.
        assert(viewport_point_reads == points_before + 4 && parent_point_reads == parents_before + 4);
        for (unsigned i = 0; i < 5; ++i) {
            const Vec3 delta{i < 2 ? -320.f : 320.f, i == 0 ? 180.f : -180.f, 0};
            const Vec3 origin = local_point(scene.preview_parent, world_point(scene.viewport, {}));
            const Vec3 moved = local_point(scene.preview_parent, world_point(scene.viewport, delta));
            assert(close(scene.rects[i].position, {scene.baseline[i].x + moved.x - origin.x,
                scene.baseline[i].y + moved.y - origin.y, scene.baseline[i].z}));
        }
        const unsigned stable_writes = position_writes;
        assert(layout.update(scene.owner.pointer(), scene.viewport.pointer(), wider, old_frame));
        assert(position_writes == stable_writes);
        assert(viewport_point_reads == points_before + 8 && parent_point_reads == parents_before + 8);
        layout.restore();
    }
    {
        Scene scene; PanoramaEdgeLayout layout; layout.configure(api());
        assert(layout.begin_session(scene.owner.pointer()));
        ui_active_set(scene.model.pointer(), true, nullptr);
        const unsigned points_before = viewport_point_reads, parents_before = parent_point_reads;
        assert(layout.update(scene.owner.pointer(), scene.viewport.pointer(), old_frame, old_frame));
        assert(viewport_point_reads == points_before && parent_point_reads == parents_before);
        assert(layout.update(scene.owner.pointer(), scene.viewport.pointer(), square, old_frame));
        const Vec3 later_game_position{333, 444, 1}; scene.rects[0].position = later_game_position;
        scene.rects[4].parent = &scene.camera_parent; scene.rects[4].position = {91, 92, 1};
        const unsigned expanded_points = viewport_point_reads, expanded_parents = parent_point_reads;
        assert(layout.update(scene.owner.pointer(), scene.viewport.pointer(), old_frame, old_frame));
        assert(viewport_point_reads == expanded_points && parent_point_reads == expanded_parents);
        assert(close(scene.rects[0].position, later_game_position));
        assert(close(scene.rects[4].position, {91, 92, 1}));
        for (unsigned i : {1u, 2u, 3u}) assert(close(scene.rects[i].position, scene.baseline[i]));
        assert(layout.begin_session(scene.owner.pointer()) && scene.model.active_ui);
        layout.restore();
    }
    {
        Scene scene; PanoramaEdgeLayout layout; layout.configure(api());
        assert(layout.update(scene.owner.pointer(), scene.viewport.pointer(), square, old_frame));
        const Vec3 later_game_position{333, 444, 1}; scene.rects[0].position = later_game_position;
        assert(layout.update(scene.owner.pointer(), scene.viewport.pointer(), square, old_frame));
        layout.restore(); assert(close(scene.rects[0].position, later_game_position));
        // A changed parent and the original game's new local position win.
        assert(layout.update(scene.owner.pointer(), scene.viewport.pointer(), square, old_frame));
        scene.rects[4].parent = &scene.camera_parent; scene.rects[4].position = {91, 92, 1};
        layout.restore(); assert(close(scene.rects[4].position, {91, 92, 1}));
    }
    {
        Scene scene; PanoramaEdgeLayout layout; layout.configure(api());
        assert(layout.update(scene.owner.pointer(), scene.viewport.pointer(), square, old_frame));
        field(scene.view, 0x128, static_cast<void *>(nullptr)); // Missing whole popup mask: rollback every control.
        assert(!layout.update(scene.owner.pointer(), scene.viewport.pointer(), square, old_frame));
        for (unsigned i = 0; i < 5; ++i) assert(close(scene.rects[i].position, scene.baseline[i]));
        layout.restore();
    }
    {
        Scene scene; PanoramaEdgeLayout layout; layout.configure(api());
        assert(layout.begin_session(scene.owner.pointer()));
        Object replacement{"Solis.Photography", "Photography360LiveContentModel"};
        objects[replacement.pointer()] = &replacement;
        field(replacement, 0x10, scene.reactive.pointer()); field(replacement, 0x18, false);
        field(scene.owner, 0x58, replacement.pointer());
        assert(layout.begin_session(scene.owner.pointer()) && !replacement.active_ui);
        layout.restore();
    }
    {
        Scene first; PanoramaEdgeLayout layout; layout.configure(api());
        assert(layout.begin_session(first.owner.pointer()));
        assert(layout.update(first.owner.pointer(), first.viewport.pointer(), square, old_frame));
        Scene second;
        assert(layout.begin_session(second.owner.pointer()) && !second.model.active_ui);
        for (unsigned i = 0; i < 5; ++i) assert(close(first.rects[i].position, first.baseline[i]));
        layout.restore();
    }
    for (bool after_write : {false, true}) {
        Scene scene; PanoramaEdgeLayout layout; layout.configure(api());
        assert(layout.update(scene.owner.pointer(), scene.viewport.pointer(), square, old_frame));
        throw_on = &scene.rects[3]; write_before_throw = after_write;
        try {
            layout.update(scene.owner.pointer(), scene.viewport.pointer(), {-1280, -720, 2560, 1440}, old_frame);
            assert(false);
        } catch (int value) { assert(value == 7); }
        for (unsigned i = 0; i < 5; ++i) assert(close(scene.rects[i].position, scene.baseline[i]));
        layout.restore();
    }
    {
        Scene scene; PanoramaEdgeLayout layout; layout.configure(api());
        assert(layout.update(scene.owner.pointer(), scene.viewport.pointer(), square, old_frame));
        scene.rects[2].alive = false; // Destroyed Unity object must not be called while restoring.
        layout.restore();
        for (unsigned i : {0u, 1u, 3u, 4u}) assert(close(scene.rects[i].position, scene.baseline[i]));
    }
    assert(handles.empty() && gameobject_reads > 0);
}
