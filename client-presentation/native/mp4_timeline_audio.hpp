// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once
// Select offline audio only from the selected original timeline graph. A
// descendant director is not sufficient: its original ControlPlayableAsset
// must also prove how the master clock reaches that audio timeline.
#ifndef IDOLY_DARWIN_BRIDGE
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstring>
#endif
#include "mp4_timeline_camera.hpp"

namespace idoly_mp4_timeline_audio {
using Method = void;
using PropertyName4 = idoly_mp4_timeline_camera::PropertyName4;
constexpr size_t max_audio_tracks = 32, max_control_edges = 256,
    max_control_clips = 64;
struct Api {
    idoly_mp4_timeline_camera::Api owned{};
    void* (*track_get_clips)(void*, Method*) = nullptr;
    void* (*object_get_name)(void*, Method*) = nullptr;
    size_t (*string_utf8)(void*, char*, size_t) = nullptr;
    // PropertyName is the pinned original four-byte value type, not a string.
    void* (*director_get_reference)(void*, PropertyName4, bool*, Method*) = nullptr;
    void* (*component_game_object)(void*, Method*) = nullptr;
    bool (*track_muted_hierarchy)(void*, Method*) = nullptr;
    double (*director_get_duration)(void*, Method*) = nullptr;
    bool (*active_enabled)(void*, Method*) = nullptr;
};
struct Layout {
    idoly_mp4_timeline_camera::Layout owned{};
    size_t clip_start = 0x18, clip_in = 0x20, clip_asset = 0x28,
        clip_duration = 0x30, clip_scale = 0x38,
        clip_ease_in = 0x48, clip_ease_out = 0x50,
        clip_blend_in = 0x58, clip_blend_out = 0x60,
        control_exposed_name = 0x18, control_default = 0x20,
        control_prefab = 0x28, control_update_director = 0x38,
        control_search_hierarchy = 0x3a;
};
struct TrackRef {
    void* director = nullptr;
    void* track = nullptr;
    const char* name = nullptr;
};
struct Scan {
    TrackRef tracks[max_audio_tracks]{};
    size_t count = 0;
    uint32_t control_clips = 0, resolved_controls = 0;
    const char* error = "selected_audio_scan_not_run";
    bool ok() const { return error && !::strcmp(error, "none"); }
};
template<class T> inline T field(const void* object, size_t offset) {
    return idoly_mp4_timeline_camera::field<T>(object, offset);
}
inline Scan scan(void* timeline, double duration, const Api& api, Layout layout = {}) {
    Scan result{};
    const auto fail = [&result](const char* reason) { result.error = reason; return result; };
    if (!api.owned.is_type || !api.owned.alive || !api.owned.array_length
        || !api.owned.array_data || !api.owned.director_get_asset
        || !api.owned.timeline_get_tracks || !api.track_get_clips
        || !api.object_get_name || !api.string_utf8 || !api.director_get_reference
        || !api.component_game_object || !api.track_muted_hierarchy
        || !api.director_get_duration || !api.active_enabled)
        return fail("selected_audio_scan_api_unavailable");
    if (!std::isfinite(duration) || duration <= 0 || duration > 900)
        return fail("selected_audio_root_duration_unsupported");
    const auto typed = [&api](void* value, const char* name) {
        return value && api.owned.is_type(value, name);
    };
    try {
    const auto owned = idoly_mp4_timeline_camera::collect(timeline, api.owned, layout.owned);
    if (!owned.ok()) return fail(owned.error);
    void* game_objects[idoly_mp4_timeline_camera::max_directors + 1]{};
    struct Edge { size_t parent = 0, child = 0; const char* error = nullptr; };
    Edge edges[max_control_edges]{};
    size_t edge_count = 0;
    for (size_t i = 0; i < owned.count; ++i) {
        game_objects[i] = api.component_game_object(owned.values[i], nullptr);
        if (!typed(game_objects[i], "UnityEngine.GameObject") || !api.owned.alive(game_objects[i]))
            return fail("selected_audio_owner_game_object_invalid");
    }
    bool bgm_found = false;
    for (size_t i = 0; i < owned.count; ++i) {
        void* owner = owned.values[i];
        void* asset = api.owned.director_get_asset(owner, nullptr);
        if (!asset) {
            if (!i) return fail("selected_master_timeline_not_loaded");
            continue;
        }
        if (!typed(asset, "UnityEngine.Timeline.TimelineAsset") || !api.owned.alive(asset))
            return fail("selected_owned_timeline_unsupported");
        void* tracks = api.owned.timeline_get_tracks(asset, nullptr);
        if (!typed(tracks, "UnityEngine.Timeline.TrackAsset[]"))
            return fail("selected_owned_track_array_invalid");
        const size_t count = api.owned.array_length(tracks);
        if (count > idoly_mp4_timeline_camera::max_tracks_per_director)
            return fail("selected_owned_tracks_out_of_bounds");
        auto** values = static_cast<void**>(api.owned.array_data(tracks));
        if (count && !values) return fail("selected_owned_track_array_invalid");
        for (size_t j = 0; j < count; ++j) {
            void* track = values[j];
            if (typed(track, "UnityEngine.Timeline.AudioTrack")) {
                if (!api.owned.alive(track)) return fail("selected_audio_track_not_loaded");
                char name[32]{};
                const size_t length = api.string_utf8(api.object_get_name(track, nullptr), name, sizeof name);
                if (!length || length >= sizeof name) return fail("audio_track_name_out_of_bounds");
                const bool bgm = !::strcmp(name, "BGM"), voice = !::strcmp(name, "Voice");
                if (!bgm && !voice) continue;
                if (bgm && bgm_found) return fail("ambiguous_bgm_track");
                bgm_found = bgm_found || bgm;
                if (result.count == max_audio_tracks) return fail("too_many_audio_tracks");
                result.tracks[result.count++] = {owner, track, bgm ? "BGM" : "Voice"};
                continue;
            }
            if (!typed(track, "UnityEngine.Timeline.ControlTrack")) continue;
            if (!api.owned.alive(track)) return fail("audio_control_track_not_loaded");
            void* clips = api.track_get_clips(track, nullptr);
            if (!typed(clips, "UnityEngine.Timeline.TimelineClip[]"))
                return fail("audio_control_clip_array_invalid");
            const size_t clip_count = api.owned.array_length(clips);
            if (clip_count > max_control_clips || result.control_clips + clip_count > max_control_edges)
                return fail("audio_control_clips_out_of_bounds");
            result.control_clips += static_cast<uint32_t>(clip_count);
            auto** clip_values = static_cast<void**>(api.owned.array_data(clips));
            if (clip_count && !clip_values) return fail("audio_control_clip_array_invalid");
            for (size_t k = 0; k < clip_count; ++k) {
                void* clip = clip_values[k];
                if (!typed(clip, "UnityEngine.Timeline.TimelineClip"))
                    return fail("audio_control_clip_invalid");
                void* control = field<void*>(clip, layout.clip_asset);
                if (!typed(control, "UnityEngine.Timeline.ControlPlayableAsset") || !api.owned.alive(control))
                    return fail("audio_control_asset_invalid");
                // Match exactly the original exposed-reference contract. A
                // valid null reference does not select its default object.
                bool valid = false;
                void* source = api.director_get_reference(owner,
                    PropertyName4{field<int32_t>(control, layout.control_exposed_name)}, &valid, nullptr);
                if (!valid) source = field<void*>(control, layout.control_default);
                if (!source) continue;
                if (!typed(source, "UnityEngine.GameObject") || !api.owned.alive(source))
                    return fail("audio_control_source_game_object_invalid");
                size_t target = owned.count;
                for (size_t n = 0; n < owned.count; ++n) {
                    if (game_objects[n] != source) continue;
                    if (target != owned.count) return fail("ambiguous_audio_control_director");
                    target = n;
                }
                // Some other original controls refer to separate scene roots.
                // They do not establish a clock for any selected owned audio.
                if (target == owned.count) continue;
                ++result.resolved_controls;
                if (edge_count == max_control_edges) return fail("audio_control_edges_out_of_bounds");
                Edge edge{i, target, nullptr};
                if (api.track_muted_hierarchy(track, nullptr))
                    edge.error = "audio_control_track_muted";
                else if (field<void*>(control, layout.control_prefab)
                    || field<uint8_t>(control, layout.control_update_director) != 1
                    || field<uint8_t>(control, layout.control_search_hierarchy) != 0)
                    edge.error = "audio_control_mode_unsupported";
                const double start = field<double>(clip, layout.clip_start),
                    in = field<double>(clip, layout.clip_in),
                    scale = field<double>(clip, layout.clip_scale),
                    length = field<double>(clip, layout.clip_duration),
                    child_duration = api.director_get_duration(owned.values[target], nullptr);
                // The original local clock is (t-start)*scale+clipIn. This
                // first implementation accepts only the proven identity case,
                // covering the entire export and never reaching child wrap.
                if (!edge.error && (!std::isfinite(start) || std::fabs(start) > 1e-9
                    || !std::isfinite(in) || std::fabs(in) > 1e-9
                    || !std::isfinite(scale) || std::fabs(scale - 1) > 1e-9
                    || !std::isfinite(length) || length + 1e-6 < duration
                    || !std::isfinite(child_duration) || child_duration + 1e-6 < duration))
                    edge.error = "audio_control_clock_unsupported";
                const size_t fades[] = {layout.clip_ease_in, layout.clip_ease_out,
                    layout.clip_blend_in, layout.clip_blend_out};
                for (size_t offset : fades) {
                    const double value = field<double>(clip, offset);
                    if (!edge.error && (!std::isfinite(value) || value > 0))
                        edge.error = "audio_control_blend_unsupported";
                }
                edges[edge_count++] = edge;
            }
        }
    }
    if (!bgm_found || !result.count) return fail("selected_music_not_found");
    for (size_t i = 0; i < result.count; ++i) {
        size_t current = 0;
        while (current < owned.count && owned.values[current] != result.tracks[i].director) ++current;
        bool visited[idoly_mp4_timeline_camera::max_directors + 1]{};
        while (current) {
            if (current >= owned.count || visited[current]) return fail("audio_control_clock_cycle");
            visited[current] = true;
            // The original DirectorControlPlayable skips inactive/disabled
            // children before synchronizing time or evaluating their graphs.
            if (!api.active_enabled(owned.values[current], nullptr))
                return fail("audio_child_director_inactive");
            const Edge* incoming = nullptr;
            for (size_t n = 0; n < edge_count; ++n) {
                if (edges[n].child != current) continue;
                if (incoming) return fail("ambiguous_audio_control_clock");
                incoming = &edges[n];
            }
            if (!incoming) return fail("selected_audio_clock_not_owned");
            if (incoming->error) return fail(incoming->error);
            current = incoming->parent;
        }
    }
    result.error = "none";
    return result;
    } catch (...) {
        return fail("selected_audio_scan_exception");
    }
}
} // namespace idoly_mp4_timeline_audio
