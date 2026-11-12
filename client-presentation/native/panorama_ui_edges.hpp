#pragma once
#include "panorama_ui_math.hpp"
#ifndef IDOLY_DARWIN_BRIDGE
#include <cstddef>
#include <cstring>
#endif

namespace idoly::presentation {

// Unity calls and registered field reads run only on the established game
// thread. Each platform's callbacks come from its locked original profile.
struct PanoramaEdgeApi {
    using Method = const void;
    uint32_t (*weak_new)(void *, bool) = nullptr;
    void *(*weak_get)(uint32_t) = nullptr;
    void (*weak_free)(uint32_t) = nullptr;
    bool (*alive)(void *, Method *) = nullptr;
    // Accept the exact class or a subclass, using IL2CPP class ancestry.
    bool (*matches)(void *, const char *name_space, const char *name) = nullptr;
    void *(*component_transform)(void *, Method *) = nullptr;
    void *(*gameobject_transform)(void *, Method *) = nullptr;
    void *(*parent)(void *, Method *) = nullptr;
    void (*position_get)(void *, Vec3 *, Method *) = nullptr;
    void (*position_set)(void *, const Vec3 *, Method *) = nullptr;
    void (*transform_point)(void *, const Vec3 *, Vec3 *, Method *) = nullptr;
    void (*inverse_transform_point)(void *, const Vec3 *, Vec3 *, Method *) = nullptr;
    bool (*ui_active_get)(void *, Method *) = nullptr;
    void (*ui_active_set)(void *, bool, Method *) = nullptr;
};

class PanoramaEdgeLayout {
    struct Ref {
        uint32_t handle = 0;
        void *get(const PanoramaEdgeApi &api, bool unity = true) const {
            void *object = handle ? api.weak_get(handle) : nullptr;
            return object && (!unity || api.alive(object, nullptr)) ? object : nullptr;
        }
        void clear(const PanoramaEdgeApi &api) {
            if (handle) api.weak_free(handle);
            handle = 0;
        }
        bool set(const PanoramaEdgeApi &api, void *object) {
            if (get(api, false) == object) return true;
            clear(api);
            if (object) handle = api.weak_new(object, false);
            return object == nullptr || handle != 0;
        }
    };
    struct Entry {
        Ref rect, parent;
        Vec3 original{}, written{}, attempted{};
        bool saved = false, changed = false, writing = false;
    } entries_[5];
    PanoramaEdgeApi api_{};
    Ref owner_, visibility_model_;
    bool visibility_done_ = false;

    template<class T> static T field(void *object, size_t offset) {
        T result{}; std::memcpy(&result, static_cast<const char *>(object) + offset, sizeof result); return result;
    }
    bool basic_api() const {
        return api_.weak_new && api_.weak_get && api_.weak_free && api_.alive && api_.matches;
    }
    bool rect(void *object) const {
        return object && api_.alive(object, nullptr) && api_.matches(object, "UnityEngine", "RectTransform");
    }
    bool typed(void *object, const char *space, const char *name, bool unity = true) const {
        return object && (!unity || api_.alive(object, nullptr)) && api_.matches(object, space, name);
    }
    bool track_owner(void *owner) {
        if (!basic_api() || !typed(owner, "Solis.Photography", "Photography360LiveContentPresenter")) return false;
        if (owner_.get(api_) == owner) return true;
        restore();
        return owner_.set(api_, owner);
    }
    void restore_entry(Entry &entry) {
        void *target = entry.rect.get(api_), *parent = entry.parent.get(api_);
        if (entry.saved && entry.changed && rect(target) && rect(parent)
                && api_.parent(target, nullptr) == parent) {
            Vec3 current{}; api_.position_get(target, &current, nullptr);
            // A later original-game write or reparent owns the new value.
            if (panorama_ui_same_position(current, entry.written)
                    || (entry.writing && panorama_ui_same_position(current, entry.attempted)))
                api_.position_set(target, &entry.original, nullptr);
        }
        entry.rect.clear(api_); entry.parent.clear(api_);
        entry.saved = entry.changed = entry.writing = false;
    }
    bool resolve_rects(void *owner, void **targets) const {
        // Android and iOS6.1.1 registered offsets independently agree; each
        // platform's fields are matched to its own original level5
        // PPtrs. The camera popup has its OWN mask and a different parent from
        // the button/balloon; move all three by the same world-space delta.
        void *content = field<void *>(owner, 0x50);
        void *control = field<void *>(owner, 0x38);
        if (!typed(content, "Solis.Photography", "Photography360LiveContentView")
                || !typed(control, "Solis.Photography", "Photography360LiveControlPresenter")) return false;
        void *view = field<void *>(control, 0x20);
        if (!typed(view, "Solis.Photography", "Photography360LiveView")) return false;
        void *ui = field<void *>(content, 0x28), *end = field<void *>(content, 0x30);
        void *button = field<void *>(view, 0xb0), *balloon = field<void *>(view, 0xa8);
        void *panel = field<void *>(view, 0x128);
        if (!typed(ui, "Solis.Common", "SolisButton") || !typed(end, "Solis.Common", "SolisButton")
                || !typed(button, "Solis.Common", "SolisButton")
                || !typed(balloon, "UnityEngine", "GameObject")
                || !typed(panel, "UnityEngine", "CanvasGroup")) return false;
        targets[0] = api_.component_transform(ui, nullptr);
        targets[1] = api_.component_transform(end, nullptr);
        targets[2] = api_.component_transform(button, nullptr);
        targets[3] = api_.gameobject_transform(balloon, nullptr);
        targets[4] = api_.component_transform(panel, nullptr);
        for (unsigned i = 0; i < 5; ++i) {
            if (!rect(targets[i])) return false;
            for (unsigned j = 0; j < i; ++j) if (targets[i] == targets[j]) return false;
        }
        return true;
    }

public:
    PanoramaEdgeLayout() = default;
    PanoramaEdgeLayout(const PanoramaEdgeLayout &) = delete;
    PanoramaEdgeLayout &operator=(const PanoramaEdgeLayout &) = delete;
    // No implicit Unity calls during native process/global destruction.
    void configure(const PanoramaEdgeApi &api) { if (basic_api()) restore(); api_ = api; }

    // Independent of expansion. Call after normal initialization/binding, once
    // per frame until this returns true. The original reactive setter keeps
    // the screen-tap UI-ON path intact. User changes after this are untouched.
    bool begin_session(void *owner) {
        if (!track_owner(owner) || !api_.ui_active_get || !api_.ui_active_set) return false;
        void *control = field<void *>(owner, 0x38);
        void *model = field<void *>(owner, 0x58);
        void *content = field<void *>(owner, 0x50);
        if (!typed(control, "Solis.Photography", "Photography360LiveControlPresenter")
                || !field<bool>(control, 0xa8)
                || !typed(content, "Solis.Photography", "Photography360LiveContentView")
                || !typed(field<void *>(control, 0x20), "Solis.Photography", "Photography360LiveView")
                || !typed(model, "Solis.Photography", "Photography360LiveContentModel", false)
                || !field<void *>(model, 0x10) || field<bool>(model, 0x18)) return false;
        if (visibility_model_.get(api_, false) != model) {
            visibility_done_ = false;
            if (!visibility_model_.set(api_, model)) return false;
        }
        if (visibility_done_) return true;
        api_.ui_active_set(model, false, nullptr);
        if (api_.ui_active_get(model, nullptr)) return false;
        visibility_done_ = true;
        return true;
    }

    // old_frame MUST be the pre-expansion image bounds expressed in the
    // viewport's local coordinate system, not the image's own Rect coordinates.
    bool update(void *owner, void *viewport, Rect full_viewport, Rect old_frame) {
        if (!track_owner(owner) || !api_.component_transform || !api_.gameobject_transform || !api_.parent
                || !api_.position_get || !api_.position_set || !api_.transform_point || !api_.inverse_transform_point
                || !rect(viewport) || !ui_rect_valid(old_frame) || !ui_rect_valid(full_viewport)
                || std::fabs(old_frame.width / old_frame.height - 16.f / 9.f) > .01f) {
            restore_layout(); return false;
        }
        if (old_frame.x == full_viewport.x && old_frame.y == full_viewport.y
                && old_frame.width == full_viewport.width && old_frame.height == full_viewport.height) {
            restore_layout(); return true;
        }
        void *targets[5]{};
        if (!resolve_rects(owner, targets)) { restore_layout(); return false; }
        Vec3 desired[5]{}, world_origin{}, world_edges[3]{};
        bool have_world_origin = false, have_world_edge[3]{};
        struct ParentPoints {
            void *parent = nullptr;
            Vec3 origin{}, moved[3]{};
            bool have_origin = false, have_moved[3]{};
        } parent_points[5];
        unsigned parent_count = 0;
        for (unsigned i = 0; i < 5; ++i) {
            if (targets[i] == viewport) { restore_layout(); return false; }
            void *parent = api_.parent(targets[i], nullptr);
            if (!rect(parent)) { restore_layout(); return false; }
            Entry &entry = entries_[i];
            if (entry.rect.get(api_) != targets[i] || entry.parent.get(api_) != parent) {
                const bool may_restore_position = entry.saved && entry.changed;
                restore_entry(entry);
                // A replaced target could have become an ancestor of the
                // viewport. Do not reuse points across a possible restore.
                if (may_restore_position) {
                    have_world_origin = false;
                    for (bool &ready : have_world_edge) ready = false;
                    parent_count = 0;
                }
            }
            Vec3 current{}; api_.position_get(targets[i], &current, nullptr);
            if (!ui_position_valid(current)) { restore_layout(); return false; }
            if (!entry.saved) {
                if (!entry.rect.set(api_, targets[i]) || !entry.parent.set(api_, parent)) { restore_layout(); return false; }
                entry.original = entry.written = current; entry.saved = true;
            } else if (entry.changed && !panorama_ui_same_position(current, entry.written)) {
                entry.original = current;
            }
            const unsigned edge_index = i < 2 ? i : 2;
            if (!have_world_edge[edge_index]) {
                Vec3 delta{};
                const PanoramaUiEdge edge = i == 0 ? PanoramaUiEdge::TopLeft
                    : i == 1 ? PanoramaUiEdge::BottomLeft : PanoramaUiEdge::BottomRight;
                if (!panorama_ui_edge_delta(old_frame, full_viewport, edge, &delta)) { restore_layout(); return false; }
                if (!have_world_origin) {
                    const Vec3 origin{};
                    api_.transform_point(viewport, &origin, &world_origin, nullptr);
                    if (!ui_position_valid(world_origin)) { restore_layout(); return false; }
                    have_world_origin = true;
                }
                api_.transform_point(viewport, &delta, &world_edges[edge_index], nullptr);
                if (!ui_position_valid(world_edges[edge_index])) { restore_layout(); return false; }
                have_world_edge[edge_index] = true;
            }
            // Borrowed parent identities and converted points live only for
            // this update. A distinct popup parent must never share a point.
            unsigned parent_index = 0;
            while (parent_index < parent_count && parent_points[parent_index].parent != parent) ++parent_index;
            ParentPoints &points = parent_points[parent_index];
            if (parent_index == parent_count) {
                points = {}; points.parent = parent; ++parent_count;
            }
            if (!points.have_origin) {
                api_.inverse_transform_point(parent, &world_origin, &points.origin, nullptr);
                if (!ui_position_valid(points.origin)) { restore_layout(); return false; }
                points.have_origin = true;
            }
            if (!points.have_moved[edge_index]) {
                api_.inverse_transform_point(parent, &world_edges[edge_index], &points.moved[edge_index], nullptr);
                if (!ui_position_valid(points.moved[edge_index])) { restore_layout(); return false; }
                points.have_moved[edge_index] = true;
            }
            if (!panorama_ui_local_position(entry.original, points.origin, points.moved[edge_index], &desired[i])) {
                restore_layout(); return false;
            }
        }
        struct Rollback {
            PanoramaEdgeLayout *layout; bool committed = false;
            ~Rollback() { if (!committed) layout->restore_layout(); }
        } rollback{this};
        for (unsigned i = 0; i < 5; ++i) {
            Entry &entry = entries_[i];
            Vec3 current{}; api_.position_get(targets[i], &current, nullptr);
            entry.changed = entry.writing = true; entry.attempted = desired[i];
            if (!panorama_ui_same_position(current, desired[i])) api_.position_set(targets[i], &desired[i], nullptr);
            api_.position_get(targets[i], &current, nullptr);
            if (!panorama_ui_same_position(current, desired[i])) return false;
            entry.written = desired[i]; entry.writing = false;
        }
        rollback.committed = true; return true;
    }

    // Disable/unsupported geometry restores layout without resetting the
    // one-time default; UI-ON selected by the user remains their choice.
    void restore_layout() {
        if (!basic_api()) return;
        for (auto &entry : entries_) restore_entry(entry);
    }
    // Scene exit, reset or owner change: restore positions and forget session.
    void restore() {
        if (!basic_api()) return;
        restore_layout(); owner_.clear(api_); visibility_model_.clear(api_); visibility_done_ = false;
    }
};
}
