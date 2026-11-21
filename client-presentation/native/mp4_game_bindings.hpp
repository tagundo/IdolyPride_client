#pragma once
#include "mp4_game_adapter.hpp"
#include "mp4_game_profile.hpp"
namespace idoly_mp4_game {
// Call only after verifying the original platform source/profile and prefixes.
// Runtime IL2CPP class, string, array and GC helpers remain caller supplied.
inline Api with_original_calls(Api api,const GameProfile& profile,uintptr_t image_base) {
#define IDMP4_GAME_CALL(name) api.name=reinterpret_cast<decltype(api.name)>(image_base+profile.name.rva)
    IDMP4_GAME_CALL(object_get_name);
    IDMP4_GAME_CALL(director_get_asset);
    IDMP4_GAME_CALL(director_get_binding);
    IDMP4_GAME_CALL(brain_output_camera);
    IDMP4_GAME_CALL(camera_pixel_width);
    IDMP4_GAME_CALL(camera_pixel_height);
    IDMP4_GAME_CALL(brain_manual_update);
    IDMP4_GAME_CALL(director_get_time);
    IDMP4_GAME_CALL(director_get_duration);
    IDMP4_GAME_CALL(director_get_mode);
    IDMP4_GAME_CALL(director_set_mode);
    IDMP4_GAME_CALL(director_set_time);
    IDMP4_GAME_CALL(director_evaluate);
    IDMP4_GAME_CALL(director_graph_injected);
    IDMP4_GAME_CALL(graph_evaluate_injected);
    IDMP4_GAME_CALL(graph_set_mode_injected);
    IDMP4_GAME_CALL(graph_valid);
    IDMP4_GAME_CALL(player_set_time);
    IDMP4_GAME_CALL(timeline_get_tracks);
    IDMP4_GAME_CALL(track_get_clips);
    IDMP4_GAME_CALL(audio_source_get_volume);
    IDMP4_GAME_CALL(audio_source_set_volume);
    IDMP4_GAME_CALL(audio_clip_samples);
    IDMP4_GAME_CALL(audio_clip_channels);
    IDMP4_GAME_CALL(audio_clip_frequency);
    IDMP4_GAME_CALL(audio_clip_load_state);
    IDMP4_GAME_CALL(audio_clip_load_type);
    IDMP4_GAME_CALL(audio_clip_load_data);
    IDMP4_GAME_CALL(audio_clip_get_data);
    IDMP4_GAME_CALL(bundle_load_file_async);
    IDMP4_GAME_CALL(async_done);
    IDMP4_GAME_CALL(bundle_request_get_bundle);
    IDMP4_GAME_CALL(bundle_load_asset);
    IDMP4_GAME_CALL(bundle_unload);
    IDMP4_GAME_CALL(camera_capture_request);
    IDMP4_GAME_CALL(texture_width);
    IDMP4_GAME_CALL(texture_height);
    IDMP4_GAME_CALL(texture_graphics_format);
    IDMP4_GAME_CALL(texture_srgb);
    IDMP4_GAME_CALL(rt_active_get);
    IDMP4_GAME_CALL(rt_active_set);
    IDMP4_GAME_CALL(texture2d_ctor_rgba);
    IDMP4_GAME_CALL(texture2d_read_pixels_injected);
    IDMP4_GAME_CALL(texture2d_raw_data);
    IDMP4_GAME_CALL(object_destroy);
    IDMP4_GAME_CALL(shader_use_custom);
    IDMP4_GAME_CALL(shader_current_time);
    IDMP4_GAME_CALL(shader_set_custom);
    IDMP4_GAME_CALL(shader_reset_custom);
#undef IDMP4_GAME_CALL
    return api;
}
} // namespace idoly_mp4_game
