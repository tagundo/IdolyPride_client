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
inline Scan scan(void* timeline, double duration, const Api& api, Layout layout = {},
                 bool require_complete_audio = false) {
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
                if (!bgm && !voice) {
                    if (require_complete_audio) return fail("selected_audio_track_unsupported");
                    continue;
                }
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

// BEGIN_MP4_FRESH_AUDIO_LISTENER
// Original static AudioListener.volume only. This lease silences Unity's final
// listener output; it neither reads DSP/voice memory nor changes AudioClip PCM.
// Capture the authored PCM programme and its gains BEFORE acquiring it. Keep
// the lease through the disposable MV's original teardown, then finish it on
// Unity's owner thread even if that MV has been replaced.
struct ListenerBinding {
    uintptr_t rva;
    uint8_t prefix[16];
    uintptr_t registration_pointer_slot;
    uint32_t metadata_method_index;
};
struct ListenerProfile {
    const char* native_sha256;
    const char* metadata_sha256;
    ListenerBinding get_volume, set_volume;
};
// Exact methods from the pinned original 6.1.1 AudioModule metadata/codegen
// tables. ABIs: float(const MethodInfo*), void(float,const MethodInfo*).
inline constexpr ListenerProfile android_listener_profile = {
    "68d4706d14b33d07647b9752124632a44b6a5901c82723beb569d9123df676b3",
    "f03b65e71c07648215ae18d6bb787462f2b049c45212f379eaa9ea05f8ba874e",
    {0x8f301c0,{0xfe,0x4f,0xbf,0xa9,0x33,0x8a,0x00,0xd0,0x60,0x62,0x41,0xf9,0xa0,0x00,0x00,0xb5},0xa018338,218167},
    {0x8f301e8,{0xe8,0x0f,0x1e,0xfc,0xfe,0x4f,0x01,0xa9,0x33,0x8a,0x00,0xd0,0x60,0x66,0x41,0xf9},0xa018340,218168}
};
inline constexpr ListenerProfile ios_listener_profile = {
    "b03bee7ede0f8e74c84b3e171f79bc3596e074281b42640eb70bd106474ff5bf",
    "d11a50fd75d1e6744ae10f2a6e7081ea87bcca267a42ba0a72fe497057cd2bda",
    {0x77e07e0,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0xd3,0x89,0x01,0xb0},0xa782238,218714},
    {0x77e0820,{0xe9,0x23,0xbd,0x6d,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91},0xa782240,218715}
};
struct SourcePcmProfile {
    ListenerBinding pitch, mute, loop, spatial_blend, pan_stereo, output_mixer, clip;
};
inline constexpr SourcePcmProfile android_source_pcm_profile = {
    {0x8f30844,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x34,0x8a,0x00,0xd0,0x81,0x7e,0x41,0xf9},0xa0183f0,218190}, // get_pitch
    {0x8f31a28,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x34,0x8a,0x00,0xb0,0x81,0x6e,0x42,0xf9},0xa0185c8,218249}, // get_mute
    {0x8f311b4,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x34,0x8a,0x00,0xb0,0x81,0xee,0x41,0xf9},0xa0184b8,218215}, // get_loop
    {0x8f314bc,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x34,0x8a,0x00,0xb0,0x81,0x1e,0x42,0xf9},0xa018518,218227}, // get_spatialBlend
    {0x8f31434,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x34,0x8a,0x00,0xb0,0x81,0x16,0x42,0xf9},0xa018508,218225}, // get_panStereo
    {0x8f30a54,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x34,0x8a,0x00,0xd0,0x81,0xc6,0x41,0xf9},0xa018430,218198}, // get_outputAudioMixerGroup
    {0x8f309d4,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x34,0x8a,0x00,0xd0,0x81,0xbe,0x41,0xf9},0xa018420,218196}, // get_clip
};
inline constexpr SourcePcmProfile ios_source_pcm_profile = {
    {0x77e1088,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0xd3,0x89,0x01,0x90},0xa7822f0,218737}, // get_pitch
    {0x77e2820,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0xb3,0x89,0x01,0xf0},0xa7824c8,218796}, // get_mute
    {0x77e1c74,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0xd3,0x89,0x01,0x90},0xa7823b8,218762}, // get_loop
    {0x77e20ac,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0xb3,0x89,0x01,0xf0},0xa782418,218774}, // get_spatialBlend
    {0x77e1ff8,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0xb3,0x89,0x01,0xf0},0xa782408,218772}, // get_panStereo
    {0x77e1358,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0xd3,0x89,0x01,0x90},0xa782330,218745}, // get_outputAudioMixerGroup
    {0x77e12a4,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0xd3,0x89,0x01,0x90},0xa782320,218743}, // get_clip
};
enum class ListenerResult { ok, waiting, stale, failed, invalid };
// Read-only admission for the supported direct, two-dimensional Timeline mix.
// Source volume is captured separately in AudioProgram before output muting.
// SetupLiveBinder assigns the actual DefaultMixer BGM/Voice groups after the
// scene's serialized AudioSources load. Both original DefaultMixer assets have
// one Master -> SE/Voice/BGM hierarchy, unity pitch and no effects/sidechains.
// The similarly named ADV BGMAudioMixer/VoiceAudioMixer have effects and are
// deliberately outside this contract. Identity comes from these actual typed
// original getters; a group name is never sufficient.
struct DefaultMixerProfile {
    ListenerBinding mixer, bgm, voice, get_float, group_mixer, volume_from_db;
};
// BEGIN_MP4_FRESH_DEFAULT_MIXER_PINS
inline constexpr DefaultMixerProfile android_default_mixer_profile = {
    {0x87a394c,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x73,0xc6,0x00,0xb0,0x94,0x8a,0x00,0x90},0x9fbb4c8,217211}, // mixer
    {0x87a3e98,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x73,0xc6,0x00,0xb0,0x94,0x8a,0x00,0x90},0x9fbb4e8,217215}, // bgm
    {0x87a4090,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x73,0xc6,0x00,0x90,0x74,0x8a,0x00,0xf0},0x9fbb500,217218}, // voice
    {0x8f332d0,{0xfe,0x0f,0x1d,0xf8,0xf6,0x57,0x01,0xa9,0xf4,0x4f,0x02,0xa9,0x16,0x8a,0x00,0xf0},0xa0187b8,218311}, // get_float
    {0x8f3337c,{0xfe,0x0f,0x1e,0xf8,0xf4,0x4f,0x01,0xa9,0x14,0x8a,0x00,0xf0,0x81,0x02,0x43,0xf9},0xa0187c8,218313}, // group_mixer
    {0x87a4290,{0xe8,0x0f,0x1e,0xfc,0xfe,0x4f,0x01,0xa9,0x73,0xc5,0x00,0x90,0x68,0x06,0x68,0x39},0x9fbb790,217300}, // volume_from_db
};
inline constexpr DefaultMixerProfile ios_default_mixer_profile = {
    {0x6eddae8,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91},0xa725610,217955}, // mixer
    {0x6ede2f8,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0xb4,0xd1,0x01,0xd0},0xa725630,217959}, // bgm
    {0x6ede6d8,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0xb4,0xd1,0x01,0xd0},0xa725648,217962}, // voice
    {0x77e4bb0,{0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91},0xa7826b8,218858}, // get_float
    {0x77e4ca4,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0xb3,0x89,0x01,0xb0},0xa7826c8,218860}, // group_mixer
    {0x6edeb58,{0xe9,0x23,0xbd,0x6d,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91},0xa7258d8,218044}, // volume_from_db
};
// END_MP4_FRESH_DEFAULT_MIXER_PINS
struct DefaultMixerApi {
    void* context = nullptr;
    bool (*current)(void*) = nullptr;
    void* (*mixer)(void*) = nullptr;
    void* (*bgm)(void*) = nullptr;
    void* (*voice)(void*) = nullptr;
    void* (*group_mixer)(void*,void*) = nullptr;
    bool (*get_float)(void*,void*,const char*,float*) = nullptr;
    // Original Qua.Sound.Utility.VolumeUtility.LoudnessToVolume: original
    // mute-floor convention, otherwise 10^(dB/20). No private DSP model.
    float (*volume_from_db)(void*,float) = nullptr;
    bool valid() const {
        return current&&mixer&&bgm&&voice&&group_mixer&&get_float&&volume_from_db;
    }
};
inline const char* default_mixer_gain(const DefaultMixerApi& api,void* group,float* gain) noexcept {
    if(!group||!gain||!api.valid())return "fresh_audio_source_mixer_api_unavailable";
    try {
        if(!api.current(api.context))return "fresh_audio_source_mixer_unavailable";
        void* mixer=api.mixer(api.context);
        void* bgm=api.bgm(api.context);void* voice=api.voice(api.context);
        if(!mixer||!bgm||!voice||bgm==voice||api.group_mixer(api.context,group)!=mixer)
            return "fresh_audio_source_mixer_unsupported";
        const char* parameter=group==bgm?"BGM_Volume":group==voice?"Voice_Volume":nullptr;
        if(!parameter)return "fresh_audio_source_mixer_unsupported";
        float master=0,bus=0;
        if(!api.get_float(api.context,mixer,"Master_Volume",&master)
            ||!api.get_float(api.context,mixer,parameter,&bus))
            return "fresh_audio_source_mixer_parameter_unavailable";
        // Actual game setters clamp public settings to <= 1, represented as
        // [-80,0] dB. Reject unsupported gain changes instead of clipping PCM.
        if(!std::isfinite(master)||master < -80||master>0
            ||!std::isfinite(bus)||bus < -80||bus>0)
            return "fresh_audio_source_mixer_gain_unsupported";
        const float master_gain=api.volume_from_db(api.context,master);
        const float bus_gain=api.volume_from_db(api.context,bus);
        if(!std::isfinite(master_gain)||master_gain<0||master_gain>1
            ||!std::isfinite(bus_gain)||bus_gain<0||bus_gain>1)
            return "fresh_audio_source_mixer_gain_unsupported";
        float master_after=0,bus_after=0;
        if(!api.current(api.context)||api.mixer(api.context)!=mixer
            ||api.bgm(api.context)!=bgm||api.voice(api.context)!=voice
            ||api.group_mixer(api.context,group)!=mixer
            ||!api.get_float(api.context,mixer,"Master_Volume",&master_after)
            ||!api.get_float(api.context,mixer,parameter,&bus_after)
            ||master_after!=master||bus_after!=bus)
            return "fresh_audio_source_mixer_changed";
        *gain=master_gain*bus_gain;
        return nullptr;
    } catch(...) {return "fresh_audio_source_mixer_probe_exception";}
}
// A custom mixer, pitch/pan/spatialisation, direct clip or muted/disabled source
// cannot silently become a different soundtrack in the private PCM mix.
struct SourcePcmApi {
    void* context = nullptr;
    bool (*current)(void*,void*) = nullptr;
    float (*pitch)(void*,void*) = nullptr;
    bool (*mute)(void*,void*) = nullptr;
    bool (*loop)(void*,void*) = nullptr;
    float (*spatial_blend)(void*,void*) = nullptr;
    float (*pan_stereo)(void*,void*) = nullptr;
    void* (*output_mixer)(void*,void*) = nullptr;
    void* (*clip)(void*,void*) = nullptr;
    bool (*enabled)(void*,void*) = nullptr;
    // Optional only for direct (null-group) output. A nonnull route requires
    // exact supported group identity plus its actual live gain.
    const char* (*mixer_gain)(void*,void*,float*) = nullptr;
    bool valid() const {
        return current&&pitch&&mute&&loop&&spatial_blend&&pan_stereo&&output_mixer&&clip&&enabled;
    }
};
inline const char* source_pcm_error(const SourcePcmApi& api,void* source,float* mixer_gain=nullptr) noexcept {
    if (!source || !api.valid()) return "fresh_audio_source_api_unavailable";
    try {
        if (!api.current(api.context,source)) return "fresh_audio_source_unavailable";
        if (!api.enabled(api.context,source)) return "fresh_audio_source_disabled";
        if (api.clip(api.context,source)) return "fresh_audio_source_direct_clip_unsupported";
        void* group=api.output_mixer(api.context,source);
        float route_gain=group?-1.f:1.f;
        if(group){
            if(!api.mixer_gain)return "fresh_audio_source_mixer_unsupported";
            if(const char* error=api.mixer_gain(api.context,group,&route_gain))return error;
            if(!std::isfinite(route_gain)||route_gain<0||route_gain>1)
                return "fresh_audio_source_mixer_gain_unsupported";
        }
        if (api.mute(api.context,source)) return "fresh_audio_source_muted_unsupported";
        if (api.loop(api.context,source)) return "fresh_audio_source_loop_unsupported";
        const float pitch=api.pitch(api.context,source);
        if (!std::isfinite(pitch) || pitch!=1) return "fresh_audio_source_pitch_unsupported";
        const float spatial=api.spatial_blend(api.context,source);
        if (!std::isfinite(spatial) || spatial!=0) return "fresh_audio_source_spatial_unsupported";
        const float pan=api.pan_stereo(api.context,source);
        if (!std::isfinite(pan) || pan!=0) return "fresh_audio_source_pan_unsupported";
        if(!api.current(api.context,source)||api.output_mixer(api.context,source)!=group)
            return "fresh_audio_source_changed";
        if(mixer_gain)*mixer_gain=route_gain;
        return nullptr;
    } catch (...) { return "fresh_audio_source_probe_exception"; }
}
struct ListenerApi {
    void* context = nullptr;
    // Source/method verification and owner-thread availability. This must not
    // require the disposable scene to remain alive: final cleanup is global.
    bool (*current)(void*) = nullptr;
    float (*get_volume)(void*) = nullptr;
    void (*set_volume)(void*,float) = nullptr;
    bool valid() const { return current && get_volume && set_volume; }
};
class ListenerLease {
    ListenerApi api_{};
    uint64_t token_ = 0;
    float saved_ = 0;
    bool active_ = false, restoring_ = false;
    const char* error_ = "none";
    ListenerResult fail(ListenerResult result,const char* error) {
        error_ = error;
        return result;
    }
    void clear() { api_={};token_=0;saved_=0;active_=restoring_=false; }
    static bool volume(float value) { return std::isfinite(value) && value >= 0 && value <= 1; }
public:
    ListenerLease() = default;
    ListenerLease(const ListenerLease&) = delete;
    ListenerLease& operator=(const ListenerLease&) = delete;
    bool active() const { return active_; }
    uint64_t token() const { return token_; }
    const char* error() const { return error_; }
    ListenerResult begin(ListenerApi api,uint64_t token) noexcept {
        if (active_) return token && token==token_ ? verify(token)
            : fail(ListenerResult::invalid,"fresh_audio_lease_already_owned");
        if (!token || !api.valid()) return fail(ListenerResult::invalid,"fresh_audio_api_unavailable");
        try {
            if (!api.current(api.context)) return fail(ListenerResult::waiting,"fresh_audio_bindings_unavailable");
            const float saved=api.get_volume(api.context);
            if (!volume(saved)) return fail(ListenerResult::failed,"fresh_audio_listener_volume_invalid");
            if (!api.current(api.context)) return fail(ListenerResult::waiting,"fresh_audio_bindings_unavailable");
            api_=api;token_=token;saved_=saved;active_=true;
            // Publish our cleanup duty before an original setter that may
            // throw after applying its write.
            api_.set_volume(api_.context,0);
            return verify(token);
        } catch (...) { return fail(ListenerResult::failed,"fresh_audio_mute_exception"); }
    }
    ListenerResult verify(uint64_t token) noexcept {
        if (!active_ || !token || token!=token_ || restoring_)
            return fail(ListenerResult::invalid,"fresh_audio_lease_not_held");
        try {
            if (!api_.current(api_.context)) return fail(ListenerResult::waiting,"fresh_audio_bindings_unavailable");
            const float actual=api_.get_volume(api_.context);
            if (!volume(actual) || actual!=0)
                return fail(ListenerResult::stale,"fresh_audio_listener_mute_lost");
            if (!api_.current(api_.context)) return fail(ListenerResult::waiting,"fresh_audio_bindings_unavailable");
            error_="none";return ListenerResult::ok;
        } catch (...) { return fail(ListenerResult::failed,"fresh_audio_verify_exception"); }
    }
    ListenerResult finish(uint64_t token) noexcept {
        if (!active_) return ListenerResult::ok;
        if (!token || token!=token_) return fail(ListenerResult::invalid,"fresh_audio_lease_not_owned");
        try {
            if (!api_.current(api_.context)) return fail(ListenerResult::waiting,"fresh_audio_bindings_unavailable");
            const float actual=api_.get_volume(api_.context);
            if (restoring_ && actual==saved_) { clear();error_="none";return ListenerResult::ok; }
            // A different global writer supersedes our zero. Never overwrite
            // its new value while retiring an old disposable scene. Public
            // get/set cannot distinguish another writer assigning zero too;
            // this lease does not attest complete writer exclusion.
            if (!volume(actual) || actual!=0) {
                clear();return fail(ListenerResult::stale,"fresh_audio_listener_lease_superseded");
            }
            if (!api_.current(api_.context)) return fail(ListenerResult::waiting,"fresh_audio_bindings_unavailable");
            restoring_=true;
            api_.set_volume(api_.context,saved_);
            const float restored=api_.get_volume(api_.context);
            if (restored!=saved_ || !volume(restored))
                return fail(ListenerResult::failed,"fresh_audio_listener_restore_failed");
            if (!api_.current(api_.context)) return fail(ListenerResult::waiting,"fresh_audio_bindings_unavailable");
            clear();error_="none";return ListenerResult::ok;
        } catch (...) { return fail(ListenerResult::failed,"fresh_audio_restore_exception"); }
    }
};
// END_MP4_FRESH_AUDIO_LISTENER
} // namespace idoly_mp4_timeline_audio
