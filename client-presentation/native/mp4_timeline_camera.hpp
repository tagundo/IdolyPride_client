// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once
// Discover cameras only through the selected original timeline controller.
// Its master often contains ControlTracks; the camera track is on one of the
// original VLTimelineController._directors, not on the master itself.
#ifndef IDOLY_DARWIN_BRIDGE
#include <cstddef>
#include <cstdint>
#include <cstring>
#endif

namespace idoly_mp4_timeline_camera {
using Method = void;
struct PropertyName4 { int32_t id=0; };
static_assert(sizeof(PropertyName4)==4,"Original ARM64 PropertyName native value layout");
constexpr size_t max_directors = 128, max_tracks_per_director = 256;
struct Api {
    bool (*is_type)(void*, const char*) = nullptr;
    bool (*alive)(void*) = nullptr;
    size_t (*array_length)(void*) = nullptr;
    void* (*array_data)(void*) = nullptr;
    void* (*director_get_asset)(void*, Method*) = nullptr;
    void* (*timeline_get_tracks)(void*, Method*) = nullptr;
    void* (*director_get_binding)(void*, void*, Method*) = nullptr;
    void* (*brain_output_camera)(void*, Method*) = nullptr;
};
struct Layout { size_t master = 0x20, directors = 0x28; };
struct Counters {
    uint32_t listed_directors = 0, unique_directors = 0, assets = 0,
        output_tracks = 0, camera_tracks = 0, null_assets = 0;
};
struct Scan {
    void* brain = nullptr;
    void* camera = nullptr;
    void* camera_director = nullptr;
    void* camera_asset = nullptr;
    void* camera_track = nullptr;
    // Private process-local identity only. Never serialize pointer-derived
    // fingerprints into user diagnostics or a persistent queue descriptor.
    uint64_t identity = 0;
    Counters counts{};
    const char* error = "selected_camera_scan_not_run";
    bool ok() const { return error && !::strcmp(error, "none"); }
};
struct OwnedDirectors {
    void* values[max_directors + 1]{};
    size_t count = 0;
    Counters counts{};
    uint64_t identity = 0;
    const char* error = "selected_owned_directors_not_collected";
    bool ok() const { return error && !::strcmp(error, "none"); }
};
template<class T> inline T field(const void* object, size_t offset) {
    T value{};
    if (object) ::memcpy(&value, static_cast<const uint8_t*>(object) + offset, sizeof value);
    return value;
}
inline void mix_identity(uint64_t& identity, uintptr_t value) {
    for (size_t i = 0; i < sizeof value; ++i) {
        identity ^= static_cast<uint8_t>(value >> (i * 8));
        identity *= 1099511628211ULL;
    }
}
inline OwnedDirectors collect(void* timeline, const Api& api, Layout layout = {}) {
    OwnedDirectors result{};
    const auto fail = [&result](const char* reason) { result.error = reason; return result; };
    try {
    if (!api.is_type || !api.alive || !api.array_length || !api.array_data)
        return fail("selected_owned_directors_api_unavailable");
    const auto typed = [&api](void* value, const char* name) {
        return value && api.is_type(value, name);
    };
    const auto director = [&api, &typed](void* value) {
        return typed(value, "UnityEngine.Playables.PlayableDirector") && api.alive(value);
    };
    if (!typed(timeline, "Solis.Common.Live.SolisLiveTimelineController") || !api.alive(timeline))
        return fail("selected_timeline_not_loaded");
    void* master = field<void*>(timeline, layout.master);
    if (!director(master)) return fail("selected_director_not_loaded");
    void* list = field<void*>(timeline, layout.directors);
    // List<T> is managed, not a UnityEngine.Object. Its typed backing array
    // verifies the closed element type without a Unity alive call on the list.
    if (!typed(list, "System.Collections.Generic.List`1"))
        return fail("selected_owned_directors_list_invalid");
    const int32_t count = field<int32_t>(list, 0x18);
    if (count < 0 || static_cast<size_t>(count) > max_directors)
        return fail("selected_owned_directors_out_of_bounds");
    void* array = field<void*>(list, 0x10);
    if (!typed(array, "UnityEngine.Playables.PlayableDirector[]"))
        return fail("selected_owned_directors_array_invalid");
    const size_t capacity = api.array_length(array);
    if (capacity < static_cast<size_t>(count) || capacity > max_directors)
        return fail("selected_owned_directors_array_out_of_bounds");
    auto** entries = static_cast<void**>(api.array_data(array));
    if (count && !entries) return fail("selected_owned_directors_array_invalid");
    result.counts.listed_directors = static_cast<uint32_t>(count);
    result.identity = 14695981039346656037ULL;
    mix_identity(result.identity, reinterpret_cast<uintptr_t>(timeline));
    mix_identity(result.identity, reinterpret_cast<uintptr_t>(master));
    mix_identity(result.identity, reinterpret_cast<uintptr_t>(list));
    mix_identity(result.identity, reinterpret_cast<uintptr_t>(array));
    mix_identity(result.identity, static_cast<uint32_t>(field<int32_t>(list, 0x1c)));
    mix_identity(result.identity, static_cast<uint32_t>(count));
    result.count = 1;
    result.values[0] = master;
    for (int32_t i = 0; i < count; ++i) {
        void* value = entries[i];
        if (!director(value)) return fail("selected_owned_director_not_loaded");
        mix_identity(result.identity, reinterpret_cast<uintptr_t>(value));
        bool duplicate = false;
        for (size_t j = 0; j < result.count; ++j) if (result.values[j] == value) duplicate = true;
        if (!duplicate) result.values[result.count++] = value;
    }
    result.counts.unique_directors = static_cast<uint32_t>(result.count);
    result.error = "none";
    return result;
    } catch (...) { return fail("selected_owned_directors_query_exception"); }
}
inline Scan scan(void* timeline, const Api& api, Layout layout = {}) {
    Scan result{};
    const auto fail = [&result](const char* reason) { result.error = reason; return result; };
    try {
    if (!api.is_type || !api.alive || !api.director_get_asset || !api.timeline_get_tracks
        || !api.director_get_binding || !api.brain_output_camera)
        return fail("selected_camera_scan_api_unavailable");
    const auto typed = [&api](void* value, const char* name) {
        return value && api.is_type(value, name);
    };
    const auto owned = collect(timeline, api, layout);
    result.counts = owned.counts;
    if (!owned.ok()) return fail(owned.error);
    result.identity = owned.identity;
    for (size_t i = 0; i < owned.count; ++i) {
        void* owner = owned.values[i];
        void* asset = api.director_get_asset(owner, nullptr);
        mix_identity(result.identity, reinterpret_cast<uintptr_t>(owner));
        mix_identity(result.identity, reinterpret_cast<uintptr_t>(asset));
        if (!asset) {
            // Original VLTimelineController.Bind skips empty child directors.
            if (owner == owned.values[0]) return fail("selected_master_timeline_not_loaded");
            ++result.counts.null_assets;
            continue;
        }
        if (!typed(asset, "UnityEngine.Timeline.TimelineAsset") || !api.alive(asset))
            return fail("selected_owned_timeline_unsupported");
        ++result.counts.assets;
        void* tracks = api.timeline_get_tracks(asset, nullptr);
        if (!typed(tracks, "UnityEngine.Timeline.TrackAsset[]"))
            return fail("selected_owned_track_array_invalid");
        const size_t track_count = api.array_length(tracks);
        if (track_count > max_tracks_per_director)
            return fail("selected_owned_tracks_out_of_bounds");
        auto** values = static_cast<void**>(api.array_data(tracks));
        if (track_count && !values) return fail("selected_owned_track_array_invalid");
        result.counts.output_tracks += static_cast<uint32_t>(track_count);
        mix_identity(result.identity, static_cast<uintptr_t>(track_count));
        for (size_t j = 0; j < track_count; ++j) {
            void* track = values[j];
            mix_identity(result.identity, reinterpret_cast<uintptr_t>(track));
            if (!typed(track, ".CinemachineTrack")) continue;
            ++result.counts.camera_tracks;
            void* brain = api.director_get_binding(owner, track, nullptr);
            if (!typed(brain, "Cinemachine.CinemachineBrain") || !api.alive(brain))
                return fail("selected_camera_binding_not_ready");
            void* camera = api.brain_output_camera(brain, nullptr);
            if (!typed(camera, "UnityEngine.Camera") || !api.alive(camera))
                return fail("selected_output_camera_not_ready");
            if (result.brain && result.brain != brain) return fail("ambiguous_selected_brains");
            if (result.camera && result.camera != camera) return fail("ambiguous_selected_cameras");
            result.brain = brain;
            result.camera = camera;
            mix_identity(result.identity, reinterpret_cast<uintptr_t>(brain));
            mix_identity(result.identity, reinterpret_cast<uintptr_t>(camera));
            if (!result.camera_director) {
                result.camera_director = owner;
                result.camera_asset = asset;
                result.camera_track = track;
            }
        }
    }
    if (!result.brain || !result.camera) return fail("selected_camera_track_not_found");
    if (!result.identity) result.identity = 1;
    result.error = "none";
    return result;
    } catch (...) { return fail("selected_camera_scan_exception"); }
}
} // namespace idoly_mp4_timeline_camera
