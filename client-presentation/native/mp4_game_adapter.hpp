#pragma once
// Original Idoly 6.1.1 / Unity 2022.3 ARM64 adapter. All methods except the
// immutable descriptor accessors are called on the Unity thread. The caller
// owns encoder backpressure, rational frame grants, paths and scene lifetime.
#ifndef IDOLY_DARWIN_BRIDGE
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <cmath>
#endif
#include "mp4_timeline_camera.hpp"
#include "mp4_timeline_audio.hpp"
#include "mp4_playback_state.hpp"

namespace idoly_mp4_game {
using Method = void;
enum class Result : int { ok=0, waiting=1, unsupported=-1, invalid=-2, failed=-3, stale=-4 };
enum class SceneKind : uint8_t { none=0,out_game=1,photography=2 };
constexpr size_t max_audio_clips=32, max_name_bytes=192;
struct AudioClipProgram {
    char clip_name[max_name_bytes]{};
    char track_name[16]{};
    double start_seconds=0, duration_seconds=0, clip_in_seconds=0, time_scale=1;
    float track_gain=1, clip_gain=1, source_gain=1, stereo_pan=0, spatial_blend=0;
    int32_t samples=0, channels=0, sample_rate=0;
    bool loop=false, muted=false;
};
struct AudioProgram { AudioClipProgram clips[max_audio_clips]{}; size_t count=0; };
struct Snapshot {
    double duration_seconds=0, previous_time_seconds=0;
    int32_t previous_update_mode=0, width=0, height=0;
    size_t actor_graph_count=0;
    bool procedural_physics_determinism_proven=false;
    AudioProgram audio{};
};
struct Rect { float x,y,width,height; };
struct SceneWitness {
    void* presenter=nullptr;void* player=nullptr;void* director=nullptr;
    void* controller=nullptr;void* camera=nullptr;void* brain=nullptr;
    void* bgm=nullptr;void* voice=nullptr;void* environment=nullptr;
    void* camera_director=nullptr;void* camera_asset=nullptr;void* camera_track=nullptr;
    uint64_t generation=0;
};
using PropertyName4=idoly_mp4_timeline_camera::PropertyName4;
struct PlayableGraph { void* handle=nullptr; int32_t version=0; int32_t padding=0; };
static_assert(sizeof(PlayableGraph)==16,"Original ARM64 PlayableGraph layout");
struct Layout {
    size_t brain_update_mode=0x30,brain_blend_update_mode=0x34,
        player_binder=0x58,binder_actors=0x40,actor_animation_player=0x20,animation_player_graph=0x28,
        presenter_player=0xe0, player_director_controller=0x38,
        photo_root_mode=0x30,photo_mode_player=0x20,photo_mode_data=0x30,player_built=0x70,
        player_duration=0x20, player_bgm_source=0x28, player_voice_source=0x30,
        controller_master=0x20, controller_directors=0x28, camera_main=0x50, camera_captured=0xa0,
        wrapper_texture=0x10, wrapper_identifier=0x18, pass_identifier=0x88,
        rendering_camera=0x90, rendering_final_target=0x158,
        track_muted=0x29, audio_track_properties=0xa0,
        clip_start=0x18, clip_in=0x20, clip_asset=0x28, clip_duration=0x30,
        clip_scale=0x38, clip_ease_in=0x48, clip_ease_out=0x50,
        clip_blend_in=0x58, clip_blend_out=0x60,
        audio_asset_clip=0x18, audio_asset_loop=0x20,
        audio_asset_properties=0x28, properties_gain=0x10,
        mixer_pan=0x14, mixer_spatial=0x18;
};
struct Api {
    bool (*is_type)(void*,const char*)=nullptr;
    bool (*exact_type)(void*,const char*)=nullptr;
    bool (*alive)(void*)=nullptr;
    uint32_t (*retain)(void*)=nullptr;
    void* (*retained)(uint32_t)=nullptr;
    void (*release)(uint32_t)=nullptr;
    void* (*new_string)(const char*)=nullptr;
    size_t (*string_utf8)(void*,char*,size_t)=nullptr;
    size_t (*array_length)(void*)=nullptr;
    void* (*array_data)(void*)=nullptr;
    void* (*new_float_array)(size_t)=nullptr;
    void* (*new_texture2d)()=nullptr;
    void* audio_clip_type=nullptr;
    void* (*object_get_name)(void*,Method*)=nullptr;
    void* (*director_get_binding)(void*,void*,Method*)=nullptr;
    void* (*director_get_reference)(void*,PropertyName4,bool*,Method*)=nullptr;
    void* (*component_game_object)(void*,Method*)=nullptr;
    bool (*track_muted_hierarchy)(void*,Method*)=nullptr;
    void (*brain_manual_update)(void*,Method*)=nullptr;
    bool (*camera_clock_ok)()=nullptr;
    void* (*brain_output_camera)(void*,Method*)=nullptr;
    int32_t (*camera_pixel_width)(void*,Method*)=nullptr;
    int32_t (*camera_pixel_height)(void*,Method*)=nullptr;
    bool (*source_geometry)(void*,int32_t*,int32_t*)=nullptr;
    // Original controller target resize. A zero pair restores the target
    // dimensions captured by the host; only the owned manual scene may set it.
    bool (*output_geometry)(void*,int32_t,int32_t)=nullptr;
    // Apply after the original manual Cinemachine update; verify without
    // writes after rendering. A custom output never falls back to pixel scaling.
    bool (*output_projection)(void*,bool)=nullptr;
    // Verified PhotographyLiveModePresenter discriminator: true selects its
    // prerecorded VideoPlayer branch, false selects the separate 3D player.
    bool (*photo_mode_is_mv)(void*,Method*)=nullptr;
    bool (*active_enabled)(void*,Method*)=nullptr;
    void* (*director_get_asset)(void*,Method*)=nullptr;
    double (*director_get_time)(void*,Method*)=nullptr;
    double (*director_get_duration)(void*,Method*)=nullptr;
    int32_t (*director_get_mode)(void*,Method*)=nullptr;
    void (*director_set_mode)(void*,int32_t,Method*)=nullptr;
    void (*director_set_time)(void*,double,Method*)=nullptr;
    void (*director_evaluate)(void*,Method*)=nullptr;
    void (*director_graph_injected)(void*,PlayableGraph*,Method*)=nullptr;
    void (*graph_evaluate_injected)(PlayableGraph*,float,Method*)=nullptr;
    void (*graph_set_mode_injected)(PlayableGraph*,int32_t,Method*)=nullptr;
    bool (*graph_valid)(PlayableGraph*,Method*)=nullptr;
    bool (*recorded_graph_mode)(const PlayableGraph*,int32_t*)=nullptr;
    void (*player_set_time)(void*,float,Method*)=nullptr;
    void* (*timeline_get_tracks)(void*,Method*)=nullptr;
    void* (*track_get_clips)(void*,Method*)=nullptr;
    float (*audio_source_get_volume)(void*,Method*)=nullptr;
    void (*audio_source_set_volume)(void*,float,Method*)=nullptr;
    int32_t (*audio_clip_samples)(void*,Method*)=nullptr;
    int32_t (*audio_clip_channels)(void*,Method*)=nullptr;
    int32_t (*audio_clip_frequency)(void*,Method*)=nullptr;
    int32_t (*audio_clip_load_state)(void*,Method*)=nullptr;
    int32_t (*audio_clip_load_type)(void*,Method*)=nullptr;
    bool (*audio_clip_load_data)(void*,Method*)=nullptr;
    bool (*audio_clip_get_data)(void*,void*,int32_t,Method*)=nullptr;
    void* (*bundle_load_file_async)(void*,Method*)=nullptr;
    bool (*async_done)(void*,Method*)=nullptr;
    void* (*bundle_request_get_bundle)(void*,Method*)=nullptr;
    void* (*bundle_load_asset)(void*,void*,void*,Method*)=nullptr;
    void (*bundle_unload)(void*,bool,Method*)=nullptr;
    void (*camera_capture_request)(void*,Method*)=nullptr;
    int32_t (*texture_graphics_format)(void*,Method*)=nullptr;
    bool (*texture_srgb)(void*,Method*)=nullptr;
    int32_t (*texture_width)(void*,Method*)=nullptr;
    int32_t (*texture_height)(void*,Method*)=nullptr;
    void* (*rt_active_get)(Method*)=nullptr;
    void (*rt_active_set)(void*,Method*)=nullptr;
    void (*texture2d_ctor_rgba)(void*,int32_t,int32_t,int32_t,bool,bool,Method*)=nullptr;
    void (*texture2d_read_pixels_injected)(void*,const Rect*,int32_t,int32_t,bool,Method*)=nullptr;
    void* (*texture2d_raw_data)(void*,Method*)=nullptr;
    void (*object_destroy)(void*,Method*)=nullptr;
    bool (*shader_use_custom)(Method*)=nullptr;
    float (*shader_current_time)(Method*)=nullptr;
    void (*shader_set_custom)(float,Method*)=nullptr;
    void (*shader_reset_custom)(Method*)=nullptr;
    // Automatic playback is opt-in and fail closed. The bridge supplies only
    // verified original state calls, a held native-clock observation and a
    // proven actor/job-state snapshot/reset/restore implementation.
    idoly_mp4_playback::OriginalApi<PlayableGraph> automatic_playback{};
    idoly_mp4_playback::Dependents automatic_dependents{};
    idoly_mp4_playback::ShaderLeaseApi automatic_shader{};
    void* automatic_context=nullptr;
    idoly_mp4_playback::ClockState (*automatic_clock_state)()=nullptr;
};
inline idoly_mp4_timeline_camera::Api timeline_camera_api(const Api& api) {
    return {api.is_type,api.alive,api.array_length,api.array_data,
        api.director_get_asset,api.timeline_get_tracks,api.director_get_binding,api.brain_output_camera};
}
inline idoly_mp4_timeline_audio::Api timeline_audio_api(const Api& api) {
    return {timeline_camera_api(api),api.track_get_clips,api.object_get_name,api.string_utf8,
        api.director_get_reference,api.component_game_object,api.track_muted_hierarchy,
        api.director_get_duration,api.active_enabled};
}
inline idoly_mp4_timeline_audio::Layout timeline_audio_layout(const Layout& layout) {
    idoly_mp4_timeline_audio::Layout output{};
    output.owned={layout.controller_master,layout.controller_directors};
    output.clip_start=layout.clip_start;output.clip_in=layout.clip_in;output.clip_asset=layout.clip_asset;
    output.clip_duration=layout.clip_duration;output.clip_scale=layout.clip_scale;
    output.clip_ease_in=layout.clip_ease_in;output.clip_ease_out=layout.clip_ease_out;
    output.clip_blend_in=layout.clip_blend_in;output.clip_blend_out=layout.clip_blend_out;
    return output;
}
class GameAdapter {
public:
    explicit GameAdapter(Api api={},Layout layout={}) : api_(api), layout_(layout) {}
    GameAdapter(const GameAdapter&)=delete;
    GameAdapter& operator=(const GameAdapter&)=delete;
    bool set_api(Api api) { if(manual_||audio_request_||audio_bundle_||audio_clip_)return false;api_=api;return true; }
    bool set_api(Api api,Layout layout) { if(!set_api(api))return false;layout_=layout;return true; }
    bool install_dependent_api(idoly_mp4_playback::OriginalApi<PlayableGraph> original,
        idoly_mp4_playback::Dependents dependents,void* context,idoly_mp4_playback::ClockState(*clock)(),
        idoly_mp4_playback::ShaderLeaseApi shader){
        // Late verified installation leaves ordinary MV observations intact.
        // It must not replace callbacks while any native/decoder scope owns
        // their cleanup responsibility, and invokes no managed/game callback.
        if(manual_||automatic_||automatic_scope_.active()||audio_request_||audio_bundle_||audio_clip_||audio_array_
            ||audio_cancel_pending_||!context||!clock||!original.director_state||!original.director_play
            ||!original.director_pause||!original.director_resume||!original.director_rebuild
            ||!original.player_playing||!original.player_paused||!original.player_set_playing||!original.player_set_paused
            ||!dependents.owner_current||!dependents.quiesce||!dependents.capture||!dependents.prepare
            ||!dependents.reset||!dependents.restore||!dependents.release||!dependents.verify_source_restored
            ||!shader.begin||!shader.set_time||!shader.finish)return false;
        api_.automatic_playback=original;api_.automatic_dependents=dependents;
        api_.automatic_context=context;api_.automatic_clock_state=clock;api_.automatic_shader=shader;return true;
    }
    void observe_presenter(void* presenter);
    void observe_presenter_ended(void* presenter);
    void observe_player_initializing(void* player);
    // Unity lifecycle observers call this before an owned player's original
    // Initialize/Dispose, or its presenter's original Initialize/End. It only
    // compares cached raw anchors and updates scalar ownership; no Unity/GC
    // API or managed dereference is permitted here. Worker jobs instead use
    // their independently published atomic generation, never this adapter.
    void invalidate_owned_scene(void* player_or_presenter);
    void release_shader_lease_for_scene(void* player_or_presenter){
        if(manual_&&player_or_presenter&&(player_or_presenter==owned_player_anchor_||player_or_presenter==owned_presenter_anchor_))
            release_shader_lease();
    }
    uint64_t owned_scene_generation()const{return owned_generation_;}
    void observe_camera_controller(void* controller);
    Result snapshot(Snapshot& output);
    Result begin_manual();
    Result begin_automatic();
    Result start_automatic();
    Result prepare_automatic_frame(double timeline_seconds);
    Result validate_automatic_frame(double timeline_seconds);
    Result original_camera_updated(void* brain);
    // Main-thread pure completion/validation boundary before the coordinator
    // rebases source clock state. It does not rebuild/evaluate or resize.
    Result prepare_restore();
    Result set_output_geometry(uint32_t width,uint32_t height);
    Result evaluate(double timeline_seconds);
    Result request_capture();
    void discard_capture(){capture_pending_=capture_pass_seen_=capture_submitted_=false;}
    Result capture_geometry(int32_t& width,int32_t& height) const;
    void maintenance();
    void observe_capture_pass(void* pass,const void* rendering_data);
    bool after_camera(void* camera);
    Result readback_rgba(uint8_t* destination,size_t capacity,size_t& bytes,int32_t& width,int32_t& height);
    Result begin_private_audio(const char* bundle_path,const AudioClipProgram& expected);
    Result poll_private_audio();
    Result read_audio_chunk(int32_t offset_frames,int32_t frame_count,float* destination,size_t sample_capacity);
    void close_private_audio();
    bool camera_delta_override(void* brain,float* output) const { if(!manual_||!camera_evaluating_||brain!=get(brain_)||!output)return false;*output=camera_step_delta_;return true; }
    bool private_audio_quiescent() const { return !audio_request_&&!audio_bundle_&&!audio_clip_; }
    Result restore_logical();
    void detach_restore_globals(){release_shader_lease();}
    Result restore();
    Result abandon_automatic(const char* reason="original_engine_clock_lost");
    void reset_observations();
    const Snapshot& description() const { return snapshot_; }
    const char* last_error() const { return error_; }
    bool manual() const { return manual_; }
    bool automatic()const{return automatic_;}
    // Native completion predicates must suppress only this cached source's
    // automatic UI exit. No Unity, GC, graph or aggregate owner query belongs
    // in this predicate; pre-initialize invalidation also covers pointer reuse.
    bool owns_automatic_source_raw(void* receiver)const{
        return receiver&&automatic_&&manual_&&!owner_replaced_&&owned_generation_
            &&automatic_scope_.owns_source_completion()
            &&(receiver==owned_player_anchor_||receiver==owned_presenter_anchor_);
    }
    bool source_handoff_failed(void* source)noexcept{
        if(!manual_||!source||(source!=owned_player_anchor_&&source!=owned_presenter_anchor_))return false;
        invalidate_owned_scene(source);
        // A before-init restoration callback already failed. Retire scalar
        // ownership so no later finally/cleanup writes the former baseline
        // into the replacement scene or invokes the failed finish callback.
        shader_lease_active_=false;shader_lease_superseded_=true;
        error_="source_handoff_failed";return true;
    }
    idoly_mp4_playback::Phase automatic_rebuild_phase()const{return automatic_scope_.phase();}
    bool automatic_rebuild_in_progress()const{return automatic_scope_.rebuilding();}
    bool restoration_pending()const{return automatic_&&automatic_scope_.active();}
    bool has_source_geometry_probe()const{return api_.source_geometry!=nullptr;}
    bool owned_scene_current()const{return manual_&&identities_current();}
    bool owned_primary_scene_current()const{return manual_&&primary_scene_current()
        &&(!automatic_||automatic_scope_.restorable_owner_current());}
    bool restoration_source_current()const{return manual_&&primary_scene_current();}
    SceneKind scene_kind()const{return scene_kind_;}
    void* selected_presenter()const {void* value=get(presenter_);return value&&live(value)?value:nullptr;}
    void* selected_player()const {return resolve_selected_player(true);}
    // Exact selected AudioTrack bindings, not an isPlaying/clip heuristic.
    // Timeline AudioPlayableOutput may legitimately leave AudioSource.clip
    // null while its graph owns the audible clip position.
    bool selected_audio_output(void* source)const{
        if(!source||!source_identity_current()||!api_.director_get_binding)return false;
        if(source!=get(bgm_source_)&&source!=get(voice_source_))return false;
        for(size_t i=0;i<audio_scope_count_;++i){const auto& track=audio_scope_[i];
            void* director=get(track.director);void* asset=get(track.asset);void* key=get(track.track);
            if(!director||!asset||!key||api_.director_get_asset(director,nullptr)!=asset)return false;
            if(api_.director_get_binding(director,key,nullptr)==source)return source_identity_current();
        }
        return false;
    }
    // Read the retained logical program captured by snapshot(), not a newly
    // guessed binding while native output callbacks are being classified.
    // Callers take their own roots before allocating or retaining this tuple.
    size_t selected_audio_track_count()const noexcept{return audio_scope_count_;}
    bool selected_audio_track(size_t index,void*& director,void*& asset,void*& track,void*& source)const{
        director=asset=track=source=nullptr;
        if(index>=audio_scope_count_)return false;
        const auto& entry=audio_scope_[index];
        void* d=get(entry.director),*a=get(entry.asset),*t=get(entry.track),*s=get(entry.source);
        if(!d||!a||!t||(entry.source&&!s))return false;
        director=d;asset=a;track=t;source=s;return true;
    }
    // Exact objects already retained by snapshot(). The source host must take
    // its own roots before retaining this witness beyond the current call.
    bool selected_scene_witness(SceneWitness& output)const{
        output={};
        // The aggregate uses this inside its own owner predicate. Consulting
        // automatic_scope_.owned_graph_current() here would recurse back
        // through that aggregate. This is a source identity witness only.
        if(snapshot_.duration_seconds<=0||!source_identity_current())return false;
        SceneWitness value{};
        value.presenter=get(presenter_);value.player=get(player_);value.director=get(director_);
        value.controller=get(camera_controller_);value.camera=get(camera_);value.brain=get(brain_);
        value.bgm=get(bgm_source_);value.voice=get(voice_source_);value.generation=owned_generation_;
        value.camera_director=get(camera_timeline_director_);value.camera_asset=get(camera_timeline_asset_);
        value.camera_track=get(camera_timeline_track_);
        if(!value.presenter||!value.player||!value.director||!value.controller||!value.camera||!value.brain||!value.bgm
            ||!value.generation)return false;
        // The exact field is also verified by the selected stage profile.
        value.environment=field<void*>(value.player,0x40);
        output=value;return true;
    }
    bool observe_source(double& seconds,bool& paused)const{
        seconds=0;paused=false;
        if(!api_.automatic_playback.player_paused||!api_.director_get_time||!source_identity_current())return false;
        void* player=get(player_);void* director=get(director_);
        if(!player||!director)return false;
        const double value=api_.director_get_time(director,nullptr);
        const bool flag=api_.automatic_playback.player_paused(player,nullptr);
        if(!std::isfinite(value)||value<0||value>snapshot_.duration_seconds||!source_identity_current())return false;
        seconds=value;paused=flag;return true;
    }
    Result source_geometry(int32_t& width,int32_t& height)const {
        if(api_.source_geometry){
            void* controller=get(camera_controller_);
            if(!controller||!live(controller)||!api_.source_geometry(controller,&width,&height))return Result::waiting;
            // These are source RGBA pixels, not an encoder configuration.
            // Original mobile aspect ratios may legitimately produce an odd
            // edge; the output stage separately chooses even codec dimensions.
            return width>=16&&height>=16&&width<=4096&&height<=4096?Result::ok:Result::unsupported;
        }
        void* camera=get(camera_);if(!camera||!live(camera)||!api_.camera_pixel_width||!api_.camera_pixel_height)return Result::waiting;
        width=api_.camera_pixel_width(camera,nullptr);height=api_.camera_pixel_height(camera,nullptr);
        return width>=16&&height>=16&&width<=4096&&height<=4096?Result::ok:Result::unsupported;
    }
private:
    template<class T> static T field(const void* p,size_t offset) { T value{};if(p)std::memcpy(&value,static_cast<const uint8_t*>(p)+offset,sizeof(T));return value; }
    bool type(void* p,const char* name) const { return p&&api_.is_type&&api_.is_type(p,name); }
    bool live(void* p) const { return p&&api_.alive&&api_.alive(p); }
    void* get(uint32_t h) const { return h&&api_.retained?api_.retained(h):nullptr; }
    bool keep(uint32_t& h,void* p) { if(!p||!api_.retain)return false;uint32_t next=api_.retain(p);if(!next)return false;drop(h);h=next;return true; }
    void drop(uint32_t& h) { if(h&&api_.release)api_.release(h);h=0; }
    Result fail(Result code,const char* message) { error_=message;return code; }
    bool valid_api() const;
    Result snapshot_selected(Snapshot& output);
    Result append_track(void* track,const char* track_name,AudioProgram& output);
    Result collect_audio_tracks(void* timeline,double duration,AudioProgram& output);
    void drop_audio_scope();
    bool audio_scope_current(void* timeline) const;
    bool identities_current() const;
    bool source_identity_current()const{return primary_scene_current()&&actor_graphs_current();}
    bool primary_scene_current() const;
    bool begin_owned_generation();
    void release_shader_lease(){
        if(shader_lease_active_){shader_lease_active_=false;api_.automatic_shader.finish(api_.automatic_context);}
    }
    void clear_owned_anchors(){owned_player_anchor_=owned_presenter_anchor_=nullptr;}
    bool camera_scope_current(void* timeline) const;
    void* resolve_selected_player(bool require_ready,void** mode=nullptr,void** data=nullptr,const char** error=nullptr) const;
    bool update_camera(float delta);
    static bool automatic_owner(void* context);
    static idoly_mp4_playback::Result automatic_quiesce(void* context);
    static idoly_mp4_playback::Result automatic_capture(void* context);
    static idoly_mp4_playback::Result automatic_prepare(void* context);
    static idoly_mp4_playback::Result automatic_reset(void* context);
    static idoly_mp4_playback::Result automatic_restore(void* context);
    static idoly_mp4_playback::Result automatic_release(void* context,bool owned);
    static idoly_mp4_playback::Result automatic_verify_source_restored(void* context);
    static const char* automatic_error(void* context);
    Result automatic_result(idoly_mp4_playback::Result value){error_=automatic_scope_.error();return static_cast<Result>(value);}
    Result restore_impl(bool release_resources);
    Result collect_actor_graphs(void* player);
    bool actor_graphs_current() const;
    void drop_actor_graphs();
    struct ActorGraph { uint32_t player=0;PlayableGraph graph{};int32_t previous_mode=0; };
    ActorGraph actor_graphs_[32]{};size_t actor_graph_count_=0;
    Api api_{}; Layout layout_{}; Snapshot snapshot_{};
    uint32_t presenter_=0,photo_mode_=0,photo_data_=0,camera_controller_=0,player_=0,director_=0,timeline_asset_=0,brain_=0,bgm_source_=0,voice_source_=0,
        camera_=0,captured_texture_=0,cpu_texture_=0,
        audio_request_=0,audio_bundle_=0,audio_clip_=0,audio_array_=0;
    AudioClipProgram expected_audio_{};
    uint32_t camera_timeline_director_=0,camera_timeline_asset_=0,camera_timeline_track_=0;
    uint64_t camera_scope_identity_=0;
    struct AudioScope {uint32_t director=0,asset=0,track=0,source=0;const char* name=nullptr;};
    AudioScope audio_scope_[idoly_mp4_timeline_audio::max_audio_tracks]{};
    size_t audio_scope_count_=0;double audio_scope_duration_=0;
    struct SnapshotAttempt {
        GameAdapter& owner;bool committed=false;
        ~SnapshotAttempt(){if(!committed)owner.drop_audio_scope();}
    };
    PlayableGraph graph_{};
    double evaluated_time_=0;
    bool evaluation_failed_=false,camera_evaluating_=false;
    float camera_step_delta_=0;int32_t previous_brain_update_=0,previous_brain_blend_=0;
    bool manual_=false,output_geometry_applied_=false,shader_was_custom_=false,capture_pending_=false,
        capture_pass_seen_=false,capture_submitted_=false;
    SceneKind scene_kind_=SceneKind::none;
    bool owner_replaced_=false;
    void* owned_player_anchor_=nullptr;
    void* owned_presenter_anchor_=nullptr;
    // Zero is a permanently exhausted generation, not a reusable epoch.
    uint64_t owned_generation_=1;
    bool audio_cancel_pending_=false,audio_failed_=false;
    bool automatic_=false,automatic_geometry_restored_=true;
    bool shader_lease_active_=false;
    bool shader_lease_superseded_=false;
    idoly_mp4_playback::Scope<PlayableGraph> automatic_scope_;
    float previous_shader_time_=0, previous_bgm_volume_=0, previous_voice_volume_=0;
    const char* error_="none";
    const char* camera_update_error_="camera_clock_cache_rebase_failed";
};
} // namespace idoly_mp4_game

namespace idoly_mp4_game {
inline bool GameAdapter::valid_api() const {
    return api_.is_type&&api_.alive&&api_.retain&&api_.retained&&api_.release
        &&api_.array_length&&api_.array_data&&api_.string_utf8&&api_.object_get_name
        &&api_.director_get_asset&&api_.director_get_time&&api_.director_get_duration
        &&api_.director_get_mode&&api_.director_set_mode&&api_.director_set_time
        &&api_.director_evaluate&&api_.brain_manual_update&&api_.camera_clock_ok&&api_.graph_set_mode_injected&&api_.graph_valid&&api_.recorded_graph_mode&&api_.player_set_time&&api_.director_get_binding&&api_.brain_output_camera&&api_.timeline_get_tracks&&api_.track_get_clips
        &&api_.audio_clip_samples&&api_.audio_clip_channels&&api_.audio_clip_frequency
        &&api_.audio_source_get_volume&&api_.audio_source_set_volume;
}
inline void GameAdapter::observe_presenter(void* value) {
    const SceneKind kind=type(value,"Solis.OutGame.LivePlayerScreenPresenter")?SceneKind::out_game
        :type(value,"Solis.Photography.PhotographyLivePresenter")?SceneKind::photography:SceneKind::none;
    if(!value||kind==SceneKind::none)return;
    if(manual_&&(get(presenter_)!=value||scene_kind_!=kind)){
        release_shader_lease();
        invalidate_owned_scene(owned_presenter_anchor_);owner_replaced_=true;error_="selected_scene_changed";return;
    }
    if(get(presenter_)!=value)keep(presenter_,value);
    if(!manual_){scene_kind_=kind;owner_replaced_=false;}
}
inline void GameAdapter::observe_presenter_ended(void* value) {
    // Original PhotographyLivePresenter.End stops playback but deliberately
    // retains its Built player, transition and enabled component hierarchy.
    // A retained wrapper is therefore not evidence that its MV is still open.
    if(!value||get(presenter_)!=value)return;
    const bool photography=scene_kind_==SceneKind::photography&&type(value,"Solis.Photography.PhotographyLivePresenter");
    const bool ordinary=scene_kind_==SceneKind::out_game&&type(value,"Solis.OutGame.LivePlayerScreenPresenter");
    if(!photography&&!ordinary)return;
    invalidate_owned_scene(value);
    owner_replaced_=true;error_="selected_scene_changed";
    drop(presenter_);drop(photo_mode_);drop(photo_data_);
    scene_kind_=SceneKind::none;
}
inline void GameAdapter::observe_player_initializing(void* value){
    // Original Initialize reuses this managed component but replaces its
    // actor/native graph generation. A retained object pointer is not export
    // ownership of the newly initialized MV. This is not Director.RebuildGraph.
    if(value==owned_player_anchor_)invalidate_owned_scene(value);
}
inline bool GameAdapter::begin_owned_generation(){
    if(!owned_generation_)return false;
    owned_generation_=owned_generation_==~uint64_t(0)?0:owned_generation_+1;
    if(!owned_generation_)return false;
    owned_player_anchor_=get(player_);owned_presenter_anchor_=get(presenter_);
    return owned_player_anchor_&&owned_presenter_anchor_;
}
inline void GameAdapter::invalidate_owned_scene(void* value){
    if(!manual_||!value||(value!=owned_player_anchor_&&value!=owned_presenter_anchor_))return;
    if(owned_generation_)owned_generation_=owned_generation_==~uint64_t(0)?0:owned_generation_+1;
    owner_replaced_=true;
    error_=owned_generation_?"selected_scene_reinitializing":"selected_scene_generation_exhausted";
}
inline void GameAdapter::observe_camera_controller(void* value) {
    if(!value||!type(value,"VL.Rendering.VLSRPCameraController"))return;
    if(manual_&&get(camera_controller_)!=value){
        release_shader_lease();
        invalidate_owned_scene(owned_player_anchor_);owner_replaced_=true;error_="selected_camera_changed";return;
    }
    if(get(camera_controller_)!=value)keep(camera_controller_,value);
}
inline void* GameAdapter::resolve_selected_player(bool require_ready,void** mode,void** data,const char** error) const {
    const auto reject=[error](const char* reason)->void*{if(error)*error=reason;return nullptr;};
    void* owner=get(presenter_);if(!owner||!live(owner))return reject("selected_presenter_missing");
    if(scene_kind_==SceneKind::out_game){
        if(!type(owner,"Solis.OutGame.LivePlayerScreenPresenter"))return reject("selected_scene_changed");
        void* player=field<void*>(owner,layout_.presenter_player);
        return type(player,"Solis.Common.SolisLivePlayer")&&live(player)?player:reject("selected_mv_not_loaded");
    }
    if(scene_kind_!=SceneKind::photography||!type(owner,"Solis.Photography.PhotographyLivePresenter"))
        return reject("selected_presenter_missing");
    void* selected_mode=field<void*>(owner,layout_.photo_root_mode);
    if(!type(selected_mode,"Solis.Photography.PhotographyLiveModePresenter")||!live(selected_mode))
        return reject("selected_photography_mode_not_loaded");
    void* selected_data=field<void*>(selected_mode,layout_.photo_mode_data);
    // The original getter returns false for null data as well. Typed nonnull
    // transition ownership must be established before interpreting that bool.
    // This transition derives from System.Object, not UnityEngine.Object.
    // Typed field provenance and its GC handle establish ownership; passing it
    // to Unity's object-alive predicate would read the wrong native layout.
    if(!type(selected_data,"Solis.Photography.Data.PhotographyLiveTransitionData"))
        return reject("selected_photography_data_not_loaded");
    if(!api_.photo_mode_is_mv||!api_.active_enabled)return reject("photography_scene_api_unavailable");
    if(api_.photo_mode_is_mv(selected_mode,nullptr))return reject("selected_video_mv_unsupported");
    void* player=field<void*>(selected_mode,layout_.photo_mode_player);
    if(!type(player,"Solis.Common.Photography.PhotographyLive3DPresenter")||!live(player))
        return reject("selected_photography_3d_not_loaded");
    if(require_ready&&(field<uint8_t>(player,layout_.player_built)!=1||!api_.active_enabled(owner,nullptr)
        ||!api_.active_enabled(selected_mode,nullptr)||!api_.active_enabled(player,nullptr)))
        return reject("selected_photography_3d_not_built");
    if(mode)*mode=selected_mode;
    if(data)*data=selected_data;
    return player;
}
inline Result GameAdapter::append_track(void* track,const char* track_name,AudioProgram& output) {
    void* props=field<void*>(track,layout_.audio_track_properties);
    if(!type(props,"UnityEngine.Timeline.AudioMixerProperties"))return fail(Result::invalid,"invalid_audio_track_properties");
    const float gain=field<float>(props,layout_.properties_gain);
    const float pan=field<float>(props,layout_.mixer_pan), spatial=field<float>(props,layout_.mixer_spatial);
    if(!std::isfinite(gain)||gain<0||gain>16||!std::isfinite(pan)||!std::isfinite(spatial))
        return fail(Result::unsupported,"unsupported_audio_mixer_values");
    const bool muted=api_.track_muted_hierarchy?api_.track_muted_hierarchy(track,nullptr):field<uint8_t>(track,layout_.track_muted)!=0;
    void* source=get(std::strcmp(track_name,"BGM")==0?bgm_source_:voice_source_);
    const float source_gain=source?api_.audio_source_get_volume(source,nullptr):0;
    if(!std::isfinite(source_gain)||source_gain<0||source_gain>1)return fail(Result::invalid,"invalid_source_gain");
    // A verified silent track contributes no samples. Its clip may be an
    // unloaded placeholder or live in a different original bundle; exporting
    // zero must not wait for or privately decode that unused resource.
    if(muted||gain==0||source_gain==0)return Result::ok;
    void* clips=api_.track_get_clips(track,nullptr);
    if(!type(clips,"UnityEngine.Timeline.TimelineClip[]"))return fail(Result::invalid,"audio_track_has_no_clip_array");
    const size_t count=api_.array_length(clips);
    if(count>max_audio_clips-output.count)return fail(Result::unsupported,"too_many_audio_clips");
    auto** data=static_cast<void**>(api_.array_data(clips));
    if(count&&!data)return fail(Result::invalid,"invalid_audio_clip_array");
    for(size_t i=0;i<count;++i){
        void* clip=data[i];
        if(!type(clip,"UnityEngine.Timeline.TimelineClip"))return fail(Result::invalid,"invalid_timeline_clip");
        void* asset=field<void*>(clip,layout_.clip_asset);
        if(!type(asset,"UnityEngine.Timeline.AudioPlayableAsset"))return fail(Result::unsupported,"unsupported_audio_playable");
        void* clip_props=field<void*>(asset,layout_.audio_asset_properties);
        if(!type(clip_props,"UnityEngine.Timeline.AudioClipProperties"))return fail(Result::invalid,"invalid_audio_clip_properties");
        const float clip_gain=field<float>(clip_props,layout_.properties_gain);
        if(!std::isfinite(clip_gain)||clip_gain<0||clip_gain>16)return fail(Result::unsupported,"unsupported_audio_timing_or_mix");
        if(clip_gain==0)continue;
        void* audio=field<void*>(asset,layout_.audio_asset_clip);
        if(!type(audio,"UnityEngine.AudioClip")||!live(audio))return fail(Result::waiting,"selected_audio_not_loaded");
        AudioClipProgram entry{};
        void* name=api_.object_get_name(audio,nullptr);
        const size_t name_length=api_.string_utf8(name,entry.clip_name,sizeof(entry.clip_name));
        if(!name_length||name_length>=sizeof(entry.clip_name))return fail(Result::unsupported,"audio_clip_name_out_of_bounds");
        const size_t track_name_length=std::strlen(track_name);
        if(track_name_length>=sizeof(entry.track_name))return fail(Result::invalid,"track_name_out_of_bounds");
        std::memcpy(entry.track_name,track_name,track_name_length+1);
        entry.start_seconds=field<double>(clip,layout_.clip_start);
        entry.duration_seconds=field<double>(clip,layout_.clip_duration);
        entry.clip_in_seconds=field<double>(clip,layout_.clip_in);
        entry.time_scale=field<double>(clip,layout_.clip_scale);
        const double ease_in=field<double>(clip,layout_.clip_ease_in),ease_out=field<double>(clip,layout_.clip_ease_out),
            blend_in=field<double>(clip,layout_.clip_blend_in),blend_out=field<double>(clip,layout_.clip_blend_out);
        entry.loop=field<uint8_t>(asset,layout_.audio_asset_loop)!=0;
        entry.muted=muted;
        entry.track_gain=gain;entry.source_gain=source_gain;entry.stereo_pan=pan;entry.spatial_blend=spatial;
        entry.clip_gain=clip_gain;
        entry.samples=api_.audio_clip_samples(audio,nullptr);
        entry.channels=api_.audio_clip_channels(audio,nullptr);
        entry.sample_rate=api_.audio_clip_frequency(audio,nullptr);
        if(!std::isfinite(entry.start_seconds)||entry.start_seconds<0
            ||!std::isfinite(entry.duration_seconds)||entry.duration_seconds<=0||entry.duration_seconds>3600
            ||!std::isfinite(entry.clip_in_seconds)||entry.clip_in_seconds<0
            ||!std::isfinite(entry.time_scale)||std::fabs(entry.time_scale-1)>1e-9
            ||!std::isfinite(ease_in)||!std::isfinite(ease_out)||!std::isfinite(blend_in)||!std::isfinite(blend_out)
            ||ease_in>0||ease_out>0||blend_in>0||blend_out>0||entry.loop
            ||std::fabs(pan)>1e-6f||std::fabs(spatial)>1e-6f
            ||!std::isfinite(entry.clip_gain)||entry.clip_gain<0||entry.clip_gain>16
            ||entry.samples<=0||entry.channels<1||entry.channels>2
            ||(entry.sample_rate!=44100&&entry.sample_rate!=48000))
            return fail(Result::unsupported,"unsupported_audio_timing_or_mix");
        output.clips[output.count++]=entry;
    }
    return Result::ok;
}
inline void GameAdapter::drop_actor_graphs() {
    for(size_t i=0;i<actor_graph_count_;++i)drop(actor_graphs_[i].player);
    actor_graph_count_=0;
}
inline bool GameAdapter::actor_graphs_current() const {
    for(size_t i=0;i<actor_graph_count_;++i){
        const ActorGraph& entry=actor_graphs_[i];void* player=get(entry.player);
        if(!live(player))return false;
        PlayableGraph graph=field<PlayableGraph>(player,layout_.animation_player_graph);
        if(graph.handle!=entry.graph.handle||graph.version!=entry.graph.version
            ||!api_.graph_valid||!api_.graph_valid(&graph,nullptr))return false;
    }
    return actor_graph_count_>0;
}
inline Result GameAdapter::collect_actor_graphs(void* player) {
    drop_actor_graphs();
    void* binder=field<void*>(player,layout_.player_binder);
    if(!type(binder,"Solis.Common.Live.SolisLiveBinder"))return fail(Result::waiting,"actor_bindings_not_ready");
    void* actors=field<void*>(binder,layout_.binder_actors);
    if(!type(actors,"System.Collections.Generic.List`1"))return fail(Result::invalid,"actor_binding_list_invalid");
    const int32_t count=field<int32_t>(actors,0x18);void* items=field<void*>(actors,0x10);
    if(count<=0||count>32||!items||api_.array_length(items)<static_cast<size_t>(count))
        return fail(Result::unsupported,"owned_actor_count_out_of_bounds");
    auto** entries=static_cast<void**>(api_.array_data(items));
    if(!entries)return fail(Result::invalid,"actor_binding_array_invalid");
    for(int32_t i=0;i<count;++i){
        // Virtual actors are held separately by binder.VirtualActors. Never
        // apply the concrete controller layout to an unrelated wrapper.
        if(!type(entries[i],"VL.Core.VLActorController")||!live(entries[i]))return fail(Result::unsupported,"unsupported_owned_actor_controller");
        void* animation=field<void*>(entries[i],layout_.actor_animation_player);
        if(!type(animation,"VL.VLAnimationClipPlayer")||!live(animation))return fail(Result::waiting,"actor_animation_not_ready");
        const PlayableGraph graph=field<PlayableGraph>(animation,layout_.animation_player_graph);
        if(!graph.handle)return fail(Result::waiting,"actor_graph_not_ready");
        bool duplicate=false;
        for(size_t j=0;j<actor_graph_count_;++j)if(actor_graphs_[j].graph.handle==graph.handle&&actor_graphs_[j].graph.version==graph.version)duplicate=true;
        if(duplicate)continue;
        int32_t mode=-1;
        if(!api_.recorded_graph_mode(&graph,&mode)||mode<0||mode>3)return fail(Result::waiting,"actor_graph_mode_not_observed");
        ActorGraph& entry=actor_graphs_[actor_graph_count_];
        if(!keep(entry.player,animation))return fail(Result::failed,"actor_graph_handle_failed");
        entry.graph=graph;entry.previous_mode=mode;++actor_graph_count_;
    }
    return Result::ok;
}
inline void GameAdapter::drop_audio_scope() {
    for(size_t i=0;i<audio_scope_count_;++i){
        drop(audio_scope_[i].director);drop(audio_scope_[i].asset);drop(audio_scope_[i].track);
        drop(audio_scope_[i].source);
        audio_scope_[i].name=nullptr;
    }
    audio_scope_count_=0;audio_scope_duration_=0;
}
inline Result GameAdapter::collect_audio_tracks(void* timeline,double duration,AudioProgram& output) {
    const auto selected=idoly_mp4_timeline_audio::scan(timeline,duration,timeline_audio_api(api_),timeline_audio_layout(layout_));
    if(!selected.ok())return fail(Result::unsupported,selected.error);
    audio_scope_duration_=duration;
    for(size_t i=0;i<selected.count;++i){
        const auto& ref=selected.tracks[i];auto& scope=audio_scope_[i];
        audio_scope_count_=i+1;scope.name=ref.name;
        void* asset=api_.director_get_asset(ref.director,nullptr);
        if(!type(asset,"UnityEngine.Timeline.TimelineAsset")||!live(asset))return fail(Result::waiting,"selected_audio_timeline_not_loaded");
        if(!keep(scope.director,ref.director)||!keep(scope.asset,asset)||!keep(scope.track,ref.track))
            return fail(Result::failed,"selected_audio_scope_handle_failed");
        void* source=api_.director_get_binding(ref.director,ref.track,nullptr);
        if(source&&(!type(source,"UnityEngine.AudioSource")||!live(source)))
            return fail(Result::unsupported,"selected_audio_binding_not_source");
        if(source){if(!keep(scope.source,source))return fail(Result::failed,"selected_audio_scope_handle_failed");}
        else drop(scope.source); // Explicitly unbound is different from a lost retained source.
        if(api_.director_get_binding(ref.director,ref.track,nullptr)!=source)
            return fail(Result::stale,"selected_audio_binding_changed");
        const Result appended=append_track(ref.track,ref.name,output);
        if(appended!=Result::ok)return appended;
    }
    return output.count?Result::ok:fail(Result::unsupported,"selected_music_not_found");
}
inline bool GameAdapter::audio_scope_current(void* timeline) const {
    if(!audio_scope_count_||audio_scope_duration_<=0)return false;
    const auto current=idoly_mp4_timeline_audio::scan(timeline,audio_scope_duration_,timeline_audio_api(api_),timeline_audio_layout(layout_));
    if(!current.ok()||current.count!=audio_scope_count_)return false;
    for(size_t i=0;i<current.count;++i){
        const auto& ref=current.tracks[i];const auto& scope=audio_scope_[i];
        if(ref.director!=get(scope.director)||ref.track!=get(scope.track)
            ||api_.director_get_asset(ref.director,nullptr)!=get(scope.asset)
            ||api_.director_get_binding(ref.director,ref.track,nullptr)!=get(scope.source)
            ||(scope.source&&(!get(scope.source)||!live(get(scope.source))))
            ||!scope.name||std::strcmp(ref.name,scope.name))return false;
    }
    return true;
}
inline Result GameAdapter::snapshot(Snapshot& output) {
    if(manual_)return fail(Result::invalid,"export_already_owns_scene");
    camera_scope_identity_=0;
    drop_audio_scope();SnapshotAttempt attempt{*this};
    const Result result=snapshot_selected(output);attempt.committed=result==Result::ok;return result;
}
inline Result GameAdapter::snapshot_selected(Snapshot& output) {
    if(!valid_api())return fail(Result::unsupported,"game_api_unavailable");
    void* presenter=get(presenter_), *controller=get(camera_controller_);
    if(!presenter||!live(presenter))return fail(Result::waiting,"selected_presenter_missing");
    void* selected_mode=nullptr,*selected_data=nullptr;const char* selection_error="selected_mv_not_loaded";
    void* player=resolve_selected_player(true,&selected_mode,&selected_data,&selection_error);
    if(!player)return fail(Result::waiting,selection_error);
    if(!controller||!live(controller))return fail(Result::waiting,"selected_render_controller_missing");
    void* timeline=field<void*>(player,layout_.player_director_controller);
    if(!type(timeline,"Solis.Common.Live.SolisLiveTimelineController")||!live(timeline))return fail(Result::waiting,"selected_timeline_not_loaded");
    void* director=field<void*>(timeline,layout_.controller_master);
    if(!type(director,"UnityEngine.Playables.PlayableDirector")||!live(director))return fail(Result::waiting,"selected_director_not_loaded");
    void* camera=field<void*>(controller,layout_.camera_main);
    if(!type(camera,"UnityEngine.Camera")||!live(camera))return fail(Result::waiting,"selected_camera_not_loaded");
    void* asset=api_.director_get_asset(director,nullptr);
    if(!type(asset,"UnityEngine.Timeline.TimelineAsset")||!live(asset))return fail(Result::unsupported,"unsupported_selected_timeline");
    Snapshot next{};
    next.duration_seconds=api_.director_get_duration(director,nullptr);
    next.previous_time_seconds=api_.director_get_time(director,nullptr);
    next.previous_update_mode=api_.director_get_mode(director,nullptr);
    if(!std::isfinite(next.duration_seconds)||next.duration_seconds<=0||next.duration_seconds>900
        ||!std::isfinite(next.previous_time_seconds)||next.previous_time_seconds<0
        ||next.previous_update_mode<0||next.previous_update_mode>3)
        return fail(Result::unsupported,"unsupported_selected_duration");
    void* bgm=field<void*>(player,layout_.player_bgm_source), *voice=field<void*>(player,layout_.player_voice_source);
    if(!type(bgm,"UnityEngine.AudioSource")||!live(bgm))return fail(Result::waiting,"bgm_source_not_ready");
    if(voice&&(!type(voice,"UnityEngine.AudioSource")||!live(voice)))return fail(Result::invalid,"invalid_voice_source");
    if(!keep(player_,player)||!keep(director_,director)||!keep(timeline_asset_,asset)||!keep(camera_,camera)||!keep(bgm_source_,bgm)
        ||(voice&&!keep(voice_source_,voice)))return fail(Result::failed,"managed_handle_allocation_failed");
    if(!voice)drop(voice_source_);
    if(scene_kind_==SceneKind::photography){
        if(!keep(photo_mode_,selected_mode)||!keep(photo_data_,selected_data))return fail(Result::failed,"managed_handle_allocation_failed");
    }else{drop(photo_mode_);drop(photo_data_);}
    const auto selected_camera=idoly_mp4_timeline_camera::scan(timeline,timeline_camera_api(api_),
        {layout_.controller_master,layout_.controller_directors});
    if(!selected_camera.ok())return fail(Result::waiting,selected_camera.error);
    if(selected_camera.camera!=camera)return fail(Result::waiting,"selected_mv_camera_not_observed");
    if(!keep(brain_,selected_camera.brain)
        ||!keep(camera_timeline_director_,selected_camera.camera_director)
        ||!keep(camera_timeline_asset_,selected_camera.camera_asset)
        ||!keep(camera_timeline_track_,selected_camera.camera_track))
        return fail(Result::failed,"camera_brain_handle_failed");
    const Result audio_ready=collect_audio_tracks(timeline,next.duration_seconds,next.audio);
    if(audio_ready!=Result::ok)return audio_ready;
    const Result actors_ready=collect_actor_graphs(player);if(actors_ready!=Result::ok)return actors_ready;
    next.actor_graph_count=actor_graph_count_;
    camera_scope_identity_=selected_camera.identity;
    snapshot_=next;output=next;error_="none";return Result::ok;
}
inline bool GameAdapter::primary_scene_current() const {
    void* presenter=get(presenter_),*player=get(player_),*director=get(director_),*controller=get(camera_controller_);
    if(owner_replaced_||!presenter||!live(player)||!live(director)||!live(controller))return false;
    void* mode=nullptr,*data=nullptr;
    if(resolve_selected_player(false,&mode,&data)!=player)return false;
    if(scene_kind_==SceneKind::photography&&(mode!=get(photo_mode_)||data!=get(photo_data_)))return false;
    void* timeline=field<void*>(player,layout_.player_director_controller);
    return timeline&&field<void*>(timeline,layout_.controller_master)==director
        &&api_.director_get_asset(director,nullptr)==get(timeline_asset_)
        &&field<void*>(controller,layout_.camera_main)==get(camera_)
        &&live(get(brain_))&&api_.brain_output_camera(get(brain_),nullptr)==get(camera_)
        &&camera_scope_current(timeline)&&audio_scope_current(timeline);
}
inline bool GameAdapter::camera_scope_current(void* timeline) const {
    if(!camera_scope_identity_||!live(get(camera_timeline_director_))
        ||!live(get(camera_timeline_asset_))||!live(get(camera_timeline_track_)))return false;
    const auto current=idoly_mp4_timeline_camera::scan(timeline,timeline_camera_api(api_),
        {layout_.controller_master,layout_.controller_directors});
    return current.ok()&&current.identity==camera_scope_identity_
        &&current.camera_director==get(camera_timeline_director_)
        &&current.camera_asset==get(camera_timeline_asset_)
        &&current.camera_track==get(camera_timeline_track_)
        &&current.brain==get(brain_)&&current.camera==get(camera_);
}
inline bool GameAdapter::identities_current() const {
    return primary_scene_current()&&actor_graphs_current()
        &&(!automatic_||!automatic_scope_.playing()||automatic_scope_.owned_graph_current());
}
inline bool GameAdapter::update_camera(float delta) {
    struct Scope { bool& active;Scope(bool& value):active(value){active=true;}~Scope(){active=false;} } scope(camera_evaluating_);
    camera_step_delta_=delta;api_.brain_manual_update(get(brain_),nullptr);
    camera_update_error_="camera_clock_cache_rebase_failed";
    if(!api_.camera_clock_ok())return false;
    if(output_geometry_applied_&&(!api_.output_projection||!api_.output_projection(get(camera_controller_),true))){
        camera_update_error_="output_projection_failed";return false;
    }
    return true;
}
inline bool GameAdapter::automatic_owner(void* context){
    auto* self=static_cast<GameAdapter*>(context);
    return self&&self->primary_scene_current()&&self->api_.automatic_dependents.owner_current
        &&self->api_.automatic_dependents.owner_current(self->api_.automatic_context);
}
inline idoly_mp4_playback::Result GameAdapter::automatic_capture(void* context){
    auto* self=static_cast<GameAdapter*>(context);
    return self->api_.automatic_dependents.capture(self->api_.automatic_context);
}
inline idoly_mp4_playback::Result GameAdapter::automatic_quiesce(void* context){
    auto* self=static_cast<GameAdapter*>(context);
    return self->api_.automatic_dependents.quiesce(self->api_.automatic_context);
}
inline idoly_mp4_playback::Result GameAdapter::automatic_prepare(void* context){
    using P=idoly_mp4_playback::Result;auto* self=static_cast<GameAdapter*>(context);
    if(!automatic_owner(context))return P::stale;
    // The mandatory selected camera/audio scope owns the complete source
    // state. A second volume-only state machine would conflict with it.
    const P prepared=self->api_.automatic_dependents.prepare(self->api_.automatic_context);
    if(prepared!=P::ok)return prepared;
    if(!automatic_owner(context))return P::stale;
    if(!self->shader_lease_active_||!self->api_.automatic_shader.set_time(self->api_.automatic_context,0)){
        self->shader_lease_superseded_=true;return P::stale;
    }
    return automatic_owner(context)?P::ok:P::stale;
}
inline idoly_mp4_playback::Result GameAdapter::automatic_reset(void* context){
    auto* self=static_cast<GameAdapter*>(context);
    return self->api_.automatic_dependents.reset(self->api_.automatic_context);
}
inline idoly_mp4_playback::Result GameAdapter::automatic_restore(void* context){
    using P=idoly_mp4_playback::Result;auto* self=static_cast<GameAdapter*>(context);
    const P result=self->api_.automatic_dependents.restore(self->api_.automatic_context);
    if(result!=P::ok)return result;
    if(!automatic_owner(context))return P::stale;
    self->release_shader_lease();
    return automatic_owner(context)?P::ok:P::stale;
}
inline idoly_mp4_playback::Result GameAdapter::automatic_release(void* context,bool owned){
    auto* self=static_cast<GameAdapter*>(context);
    // The global lease must end even when the selected scene was replaced or
    // actor/resource cleanup has to wait. It is not an old-scene native write.
    self->release_shader_lease();
    return self->api_.automatic_dependents.release(self->api_.automatic_context,owned);
}
inline idoly_mp4_playback::Result GameAdapter::automatic_verify_source_restored(void* context){
    auto* self=static_cast<GameAdapter*>(context);
    return self->api_.automatic_dependents.verify_source_restored(self->api_.automatic_context);
}
inline const char* GameAdapter::automatic_error(void* context){
    auto* self=static_cast<GameAdapter*>(context);
    if(self->shader_lease_superseded_)return "shader_lease_superseded";
    return self->api_.automatic_dependents.error?self->api_.automatic_dependents.error(self->api_.automatic_context):nullptr;
}
inline Result GameAdapter::begin_automatic(){
    namespace p=idoly_mp4_playback;
    if(manual_&&!automatic_)return fail(Result::invalid,"export_already_owns_scene");
    const auto& dependencies=api_.automatic_dependents;
    if(!api_.automatic_clock_state||!api_.automatic_context||!dependencies.owner_current||!dependencies.quiesce
        ||!dependencies.capture||!dependencies.prepare||!dependencies.reset||!dependencies.restore||!dependencies.release||!dependencies.verify_source_restored
        ||!api_.automatic_shader.begin||!api_.automatic_shader.set_time||!api_.automatic_shader.finish)
        return fail(Result::unsupported,"original_dependent_state_unavailable");
    const p::ClockState clock=api_.automatic_clock_state();
    if(!clock.owned||!clock.held)return fail(Result::waiting,"original_engine_clock_not_held");
    if(!automatic_){
        if(!identities_current()||snapshot_.duration_seconds<=0||!snapshot_.audio.count)
            return fail(Result::stale,"selected_scene_changed");
        const int32_t brain_mode=field<int32_t>(get(brain_),layout_.brain_update_mode);
        // Original Late/Smart use the native loop. Manual mode has no proven
        // automatic trigger; Fixed mode is incompatible with the fixed-world
        // isolation required by the verified export domain.
        if(brain_mode!=1&&brain_mode!=2)
            return fail(Result::unsupported,brain_mode==3?"original_camera_manual_trigger_unclosed":"original_camera_fixed_update_unsupported");
        auto original=api_.automatic_playback;
        original.director_mode=api_.director_get_mode;original.director_set_mode=api_.director_set_mode;
        original.director_time=api_.director_get_time;original.director_set_time=api_.director_set_time;
        original.director_evaluate=api_.director_evaluate;original.director_graph=api_.director_graph_injected;
        original.graph_valid=api_.graph_valid;
        const p::Dependents enclosed={automatic_owner,automatic_quiesce,automatic_capture,automatic_prepare,automatic_reset,
            automatic_restore,automatic_release,automatic_error,automatic_verify_source_restored};
        if(!automatic_scope_.install(original,enclosed))return fail(Result::invalid,"export_already_owns_scene");
        if(!begin_owned_generation())return fail(Result::failed,"selected_scene_generation_unavailable");
        manual_=automatic_=true;automatic_geometry_restored_=true;
        shader_lease_superseded_=false;
        if(!api_.automatic_shader.begin(api_.automatic_context)){
            manual_=automatic_=false;clear_owned_anchors();return fail(Result::unsupported,"shader_lease_unavailable");
        }
        shader_lease_active_=true;
    }
    const p::Result acquired=automatic_scope_.acquire(get(player_),get(director_),this,clock);
    if(acquired==p::Result::ok){
        snapshot_.previous_time_seconds=automatic_scope_.snapshot().time;
        snapshot_.previous_update_mode=automatic_scope_.snapshot().mode;
    }
    if(!automatic_scope_.active()){release_shader_lease();manual_=automatic_=false;clear_owned_anchors();}
    return automatic_result(acquired);
}
inline Result GameAdapter::start_automatic(){
    if(!automatic_||!api_.automatic_clock_state)return fail(Result::invalid,"original_playback_not_held");
    const auto clock=api_.automatic_clock_state();
    if(!clock.owned||!clock.held)return fail(Result::waiting,"original_engine_clock_not_held");
    // Adoption of freshly rebuilt actor graphs can itself wait. Once the
    // source has started at zero under a held clock, retry adoption only;
    // never rebuild/play that source a second time.
    const auto result=automatic_scope_.playing()?automatic_scope_.validate_frame(0):automatic_scope_.start(clock);
    if(result!=idoly_mp4_playback::Result::ok)return automatic_result(result);
    // RebuildGraph intentionally replaces the selected director's graph and
    // can rebuild actor graphs. Adopt only this same retained player's exact
    // actor graph set after dependent reset has established its ownership.
    const Result actors=collect_actor_graphs(get(player_));
    if(actors!=Result::ok)return actors;
    snapshot_.actor_graph_count=actor_graph_count_;evaluated_time_=0;evaluation_failed_=false;
    return automatic_result(result);
}
inline Result GameAdapter::validate_automatic_frame(double seconds){
    if(!automatic_)return fail(Result::invalid,"original_playback_not_running");
    if(!identities_current())return fail(Result::stale,"selected_scene_changed");
    return automatic_result(automatic_scope_.validate_frame(seconds));
}
inline Result GameAdapter::prepare_automatic_frame(double seconds){
    if(!automatic_||!api_.automatic_clock_state)return fail(Result::invalid,"original_playback_not_running");
    if(!std::isfinite(seconds)||seconds<0||seconds>snapshot_.duration_seconds)
        return fail(Result::invalid,"frame_time_out_of_bounds");
    if(!api_.automatic_clock_state().owned)return fail(Result::waiting,"original_engine_clock_not_owned");
    if(!identities_current())return fail(Result::stale,"selected_scene_changed");
    const auto ready=automatic_scope_.validate_owner_state();
    if(ready!=idoly_mp4_playback::Result::ok)return automatic_result(ready);
    // This runs before the original Director/animation update. Its current
    // timeline is intentionally still the previous frame. Only the owned
    // shader clock is prepared; post-render validation checks actual time.
    if(!shader_lease_active_||!api_.automatic_shader.set_time(api_.automatic_context,static_cast<float>(seconds)))
        return fail(Result::stale,"shader_lease_superseded");
    if(!identities_current())return fail(Result::stale,"selected_scene_changed");
    return automatic_result(automatic_scope_.validate_owner_state());
}
inline Result GameAdapter::original_camera_updated(void* brain){
    if(!automatic_||!automatic_scope_.playing()||brain!=get(brain_))return Result::waiting;
    if(!identities_current())return fail(Result::stale,"selected_scene_changed");
    if(output_geometry_applied_&&(!api_.output_projection||!api_.output_projection(get(camera_controller_),true)))
        return fail(Result::unsupported,"output_projection_failed");
    return Result::ok;
}
inline Result GameAdapter::prepare_restore(){
    if(!automatic_||!api_.automatic_clock_state)return fail(Result::invalid,"original_playback_not_held");
    return automatic_result(automatic_scope_.prepare_restore(api_.automatic_clock_state()));
}
inline Result GameAdapter::begin_manual() {
    if(manual_)return fail(Result::invalid,"export_already_owns_scene");
    if(!identities_current()||snapshot_.duration_seconds<=0||!snapshot_.audio.count)return fail(Result::stale,"selected_scene_changed");
    if(!api_.shader_use_custom||!api_.shader_current_time||!api_.shader_set_custom||!api_.shader_reset_custom
        ||!api_.director_graph_injected||!api_.graph_evaluate_injected)
        return fail(Result::unsupported,"shader_clock_api_unavailable");
    void* director=get(director_);snapshot_.previous_time_seconds=api_.director_get_time(director,nullptr);
    snapshot_.previous_update_mode=api_.director_get_mode(director,nullptr);
    previous_brain_update_=field<int32_t>(get(brain_),layout_.brain_update_mode);
    previous_brain_blend_=field<int32_t>(get(brain_),layout_.brain_blend_update_mode);
    if(previous_brain_update_<0||previous_brain_update_>3||previous_brain_blend_<0||previous_brain_blend_>1)
        return fail(Result::unsupported,"unsupported_camera_update_mode");
    previous_bgm_volume_=api_.audio_source_get_volume(get(bgm_source_),nullptr);
    previous_voice_volume_=get(voice_source_)?api_.audio_source_get_volume(get(voice_source_),nullptr):0;
    shader_was_custom_=api_.shader_use_custom(nullptr);previous_shader_time_=api_.shader_current_time(nullptr);
    for(size_t i=0;i<actor_graph_count_;++i){
        int32_t observed=-1;auto& entry=actor_graphs_[i];
        if(!api_.recorded_graph_mode(&entry.graph,&observed)||observed<0||observed>3)return fail(Result::waiting,"actor_graph_mode_not_observed");
        entry.previous_mode=observed;
    }
    if(!begin_owned_generation())return fail(Result::failed,"selected_scene_generation_unavailable");
    manual_=true;api_.director_set_mode(director,3,nullptr);
    const int32_t manual_mode=3,late_blend=1;
    std::memcpy(static_cast<uint8_t*>(get(brain_))+layout_.brain_update_mode,&manual_mode,sizeof(manual_mode));
    std::memcpy(static_cast<uint8_t*>(get(brain_))+layout_.brain_blend_update_mode,&late_blend,sizeof(late_blend));
    for(size_t i=0;i<actor_graph_count_;++i)api_.graph_set_mode_injected(&actor_graphs_[i].graph,3,nullptr);
    api_.audio_source_set_volume(get(bgm_source_),0,nullptr);
    if(get(voice_source_))api_.audio_source_set_volume(get(voice_source_),0,nullptr);
    api_.player_set_time(get(player_),0,nullptr);
    if(!actor_graphs_current()){restore();return fail(Result::unsupported,"actor_graph_rebuilt_during_reset");}
    for(size_t i=0;i<actor_graph_count_;++i)api_.graph_evaluate_injected(&actor_graphs_[i].graph,0,nullptr);
    api_.shader_set_custom(0,nullptr);
    graph_={};api_.director_graph_injected(director,&graph_,nullptr);
    evaluated_time_=0;evaluation_failed_=false;
    if(!update_camera(-1)){restore();return fail(Result::unsupported,camera_update_error_);}
    if(!graph_.handle||std::fabs(api_.director_get_time(director,nullptr))>1e-4){
        restore();return fail(Result::unsupported,"manual_graph_initialization_failed");
    }
    return Result::ok;
}
inline Result GameAdapter::evaluate(double seconds) {
    if(automatic_)return validate_automatic_frame(seconds);
    if(!manual_||!identities_current())return fail(Result::stale,"selected_scene_changed");
    if(evaluation_failed_)return fail(Result::failed,"manual_graph_previously_failed");
    if(!std::isfinite(seconds)||seconds<0||seconds>snapshot_.duration_seconds
        ||seconds<evaluated_time_-1e-9)return fail(Result::invalid,"frame_time_out_of_bounds");
    // The encoder may retry one frame under backpressure. Never advance the
    // animation graph or its ActorSwing jobs twice for that frame.
    if(std::fabs(seconds-evaluated_time_)<=1e-9)return Result::ok;
    PlayableGraph current{};api_.director_graph_injected(get(director_),&current,nullptr);
    if(!current.handle||current.handle!=graph_.handle||current.version!=graph_.version){
        evaluation_failed_=true;return fail(Result::stale,"selected_graph_changed");
    }
    const float delta=static_cast<float>(seconds-evaluated_time_);
    if(!std::isfinite(delta)||delta<=0)return fail(Result::invalid,"frame_delta_out_of_bounds");
    api_.graph_evaluate_injected(&current,delta,nullptr);
    double observed=api_.director_get_time(get(director_),nullptr);
    if(!std::isfinite(observed)){evaluation_failed_=true;return fail(Result::unsupported,"manual_graph_time_invalid");}
    if(std::fabs(observed-seconds)>1e-4){
        // Some Unity versions keep the Director's separate manual-time field
        // unchanged when the underlying playable graph advances. Synchronize
        // that field only; a second Evaluate would double-step animation jobs.
        if(std::fabs(observed-evaluated_time_)>1e-4){
            evaluation_failed_=true;return fail(Result::unsupported,"manual_graph_time_drift");
        }
        api_.director_set_time(get(director_),seconds,nullptr);
        observed=api_.director_get_time(get(director_),nullptr);
        if(!std::isfinite(observed)||std::fabs(observed-seconds)>1e-4){
            evaluation_failed_=true;return fail(Result::unsupported,"manual_director_sync_failed");
        }
    }
    for(size_t i=0;i<actor_graph_count_;++i)api_.graph_evaluate_injected(&actor_graphs_[i].graph,delta,nullptr);
    if(!update_camera(delta)){evaluation_failed_=true;return fail(Result::unsupported,camera_update_error_);}
    evaluated_time_=seconds;
    api_.shader_set_custom(static_cast<float>(seconds),nullptr);
    return Result::ok;
}
inline Result GameAdapter::set_output_geometry(uint32_t width,uint32_t height) {
    if(!manual_||!identities_current())return fail(Result::stale,"selected_scene_changed");
    if(width<16||height<16||width>4096||height>4096||width%2||height%2)
        return fail(Result::invalid,"output_geometry_invalid");
    if(!api_.output_geometry||!api_.output_projection)
        return fail(Result::unsupported,"output_render_projection_unavailable");
    // The original resize can fail after it has released the previous target.
    // Always retain restoration responsibility once the callback is entered.
    output_geometry_applied_=true;
    if(!api_.output_geometry(get(camera_controller_),static_cast<int32_t>(width),static_cast<int32_t>(height)))
        return fail(Result::failed,"output_render_geometry_failed");
    if(!api_.output_projection(get(camera_controller_),true))
        return fail(Result::failed,"output_projection_failed");
    return Result::ok;
}
inline Result GameAdapter::capture_geometry(int32_t& width,int32_t& height) const {
    width=snapshot_.width;height=snapshot_.height;
    return width>0&&height>0?Result::ok:Result::waiting;
}
inline Result GameAdapter::request_capture() {
    if(!manual_||!identities_current())return fail(Result::stale,"selected_scene_changed");
    if(capture_pending_)return fail(Result::invalid,"capture_already_pending");
    if(output_geometry_applied_&&(!api_.output_projection||!api_.output_projection(get(camera_controller_),true)))
        return fail(Result::unsupported,"output_projection_failed");
    if(!api_.camera_capture_request||!api_.texture_width||!api_.texture_height)
        return fail(Result::unsupported,"capture_api_unavailable");
    api_.camera_capture_request(get(camera_controller_),nullptr);
    void* wrapper=field<void*>(get(camera_controller_),layout_.camera_captured);
    void* texture=field<void*>(wrapper,layout_.wrapper_texture);
    if(!live(texture)||!keep(captured_texture_,texture))return fail(Result::waiting,"capture_texture_not_ready");
    int32_t width=api_.texture_width(texture,nullptr),height=api_.texture_height(texture,nullptr);
    if(width<16||height<16||width>4096||height>4096)
        return fail(Result::unsupported,"capture_geometry_not_supported");
    snapshot_.width=width;snapshot_.height=height;
    capture_pending_=true;capture_pass_seen_=capture_submitted_=false;return Result::ok;
}
inline void GameAdapter::observe_capture_pass(void* pass,const void* data) {
    if(!manual_||!capture_pending_||!pass||!data||!identities_current())return;
    if(field<void*>(data,layout_.rendering_camera)!=get(camera_)
        ||!field<uint8_t>(data,layout_.rendering_final_target))return;
    void* wrapper=field<void*>(get(camera_controller_),layout_.camera_captured);
    if(!wrapper||field<void*>(wrapper,layout_.wrapper_texture)!=get(captured_texture_))return;
    if(!std::memcmp(static_cast<uint8_t*>(pass)+layout_.pass_identifier,
        static_cast<uint8_t*>(wrapper)+layout_.wrapper_identifier,40))capture_pass_seen_=true;
}
inline bool GameAdapter::after_camera(void* camera) {
    if(manual_&&capture_pending_&&capture_pass_seen_&&camera==get(camera_)&&identities_current()){
        capture_submitted_=true;return true;
    }
    return false;
}
inline Result GameAdapter::readback_rgba(uint8_t* dst,size_t capacity,size_t& bytes,int32_t& width,int32_t& height) {
    bytes=0;width=height=0;
    if(!manual_||!identities_current())return fail(Result::stale,"selected_scene_changed");
    if(!capture_pending_||!capture_submitted_)return Result::waiting;
    if(output_geometry_applied_&&(!api_.output_projection||!api_.output_projection(get(camera_controller_),false)))
        return fail(Result::unsupported,"output_projection_verification_failed");
    if(!dst||!api_.rt_active_get||!api_.rt_active_set||!api_.new_texture2d||!api_.texture2d_ctor_rgba
        ||!api_.texture2d_read_pixels_injected||!api_.texture2d_raw_data||!api_.object_destroy
        ||!api_.texture_graphics_format||!api_.texture_srgb)
        return fail(Result::unsupported,"readback_api_unavailable");
    const size_t row=static_cast<size_t>(snapshot_.width)*4,total=row*static_cast<size_t>(snapshot_.height);
    if(capacity<total)return fail(Result::invalid,"frame_buffer_too_small");
    void* texture=get(captured_texture_);
    if(!live(texture)||api_.texture_width(texture,nullptr)!=snapshot_.width
        ||api_.texture_height(texture,nullptr)!=snapshot_.height)return fail(Result::stale,"capture_geometry_changed");
    if(api_.texture_graphics_format(texture,nullptr)!=4||!api_.texture_srgb(texture,nullptr))
        return fail(Result::unsupported,"capture_is_not_rgba8_srgb");
    void* cpu=get(cpu_texture_);
    if(cpu&&(api_.texture_width(cpu,nullptr)!=snapshot_.width||api_.texture_height(cpu,nullptr)!=snapshot_.height)){
        api_.object_destroy(cpu,nullptr);drop(cpu_texture_);cpu=nullptr;
    }
    if(!cpu){cpu=api_.new_texture2d();if(!cpu||!keep(cpu_texture_,cpu))return fail(Result::failed,"readback_texture_allocation_failed");
        api_.texture2d_ctor_rgba(cpu,snapshot_.width,snapshot_.height,4,false,false,nullptr);}
    void* previous=api_.rt_active_get(nullptr);uint32_t previous_handle=0;
    if(previous&&!keep(previous_handle,previous))return fail(Result::failed,"active_texture_handle_failed");
    struct ActiveTarget {
        GameAdapter& game;void* expected=nullptr;uint32_t& previous;bool armed=false;
        bool finish(){
            if(!armed)return true;
            // A synchronous external setter may supersede our temporary RT.
            // Its value survives; ownership is not recovered by overwriting it.
            if(game.api_.rt_active_get(nullptr)!=expected){armed=false;return false;}
            void* before=game.get(previous);
            if(previous&&(!before||!game.live(before)))before=nullptr;
            game.api_.rt_active_set(before,nullptr);
            const bool restored=game.api_.rt_active_get(nullptr)==before;armed=false;return restored;
        }
        ~ActiveTarget(){
            try{(void)finish();}catch(...){/* Original failure still propagates. */}
            game.drop(previous);
        }
    } target{*this,texture,previous_handle};
    // The setter can mutate and then throw. Restoration duty precedes it.
    target.armed=true;api_.rt_active_set(texture,nullptr);
    const Rect rect{0,0,static_cast<float>(snapshot_.width),static_cast<float>(snapshot_.height)};
    api_.texture2d_read_pixels_injected(cpu,&rect,0,0,false,nullptr);
    if(!target.finish())return fail(Result::failed,"capture_active_texture_superseded");
    void* raw=api_.texture2d_raw_data(cpu,nullptr);
    if(!raw||api_.array_length(raw)!=total||!api_.array_data(raw))return fail(Result::failed,"unexpected_rgba_readback_size");
    const auto* source=static_cast<const uint8_t*>(api_.array_data(raw));
    // Unity ReadPixels starts at lower left; encoder contract is top down.
    for(int32_t y=0;y<snapshot_.height;++y){
        uint8_t* output=dst+row*static_cast<size_t>(y);
        std::memcpy(output,source+row*static_cast<size_t>(snapshot_.height-1-y),row);
        for(int32_t x=0;x<snapshot_.width;++x)output[static_cast<size_t>(x)*4+3]=255;
    }
    bytes=total;width=snapshot_.width;height=snapshot_.height;
    capture_pending_=capture_pass_seen_=capture_submitted_=false;return Result::ok;
}
inline Result GameAdapter::begin_private_audio(const char* path,const AudioClipProgram& expected) {
    if(audio_request_||audio_bundle_||audio_clip_)return fail(Result::invalid,"private_audio_already_open");
    if(!path||!path[0]||std::strlen(path)>4096||!expected.clip_name[0]||expected.clip_name[sizeof(expected.clip_name)-1]
        ||!api_.new_string||!api_.bundle_load_file_async||!api_.async_done||!api_.bundle_request_get_bundle
        ||!api_.bundle_load_asset||!api_.audio_clip_type||!api_.audio_clip_load_data
        ||!api_.audio_clip_load_state||!api_.audio_clip_load_type||!api_.bundle_unload)
        return fail(Result::unsupported,"private_audio_api_unavailable");
    void* request=api_.bundle_load_file_async(api_.new_string(path),nullptr);
    if(!request||!keep(audio_request_,request))return fail(Result::failed,"private_bundle_open_failed");
    expected_audio_=expected;audio_cancel_pending_=false;audio_failed_=false;return Result::waiting;
}
inline Result GameAdapter::poll_private_audio() {
    if(audio_failed_)return Result::failed;
    if(audio_cancel_pending_){close_private_audio();return audio_request_?Result::waiting:fail(Result::failed,"private_audio_cancelled");}
    if(audio_clip_){const int32_t state=api_.audio_clip_load_state(get(audio_clip_),nullptr);
        if(state<0||state>3||state==3){audio_failed_=true;return fail(Result::failed,"private_audio_decode_failed");}
        return state==2?Result::ok:Result::waiting;}
    if(!audio_request_)return fail(Result::invalid,"private_audio_not_open");
    if(!api_.async_done(get(audio_request_),nullptr))return Result::waiting;
    void* bundle=api_.bundle_request_get_bundle(get(audio_request_),nullptr);
    if(!bundle||!live(bundle)||!keep(audio_bundle_,bundle)){audio_failed_=true;return fail(Result::failed,"private_bundle_load_failed");}
    void* clip=api_.bundle_load_asset(bundle,api_.new_string(expected_audio_.clip_name),api_.audio_clip_type,nullptr);
    if(!type(clip,"UnityEngine.AudioClip")||!live(clip)||!keep(audio_clip_,clip)){audio_failed_=true;return fail(Result::failed,"private_audio_clip_missing");}
    char actual_name[max_name_bytes]{};
    const size_t actual_length=api_.string_utf8(api_.object_get_name(clip,nullptr),actual_name,sizeof(actual_name));
    if(!actual_length||actual_length>=sizeof(actual_name)||std::strcmp(actual_name,expected_audio_.clip_name)
        ||api_.audio_clip_samples(clip,nullptr)!=expected_audio_.samples
        ||api_.audio_clip_frequency(clip,nullptr)!=expected_audio_.sample_rate
        ||api_.audio_clip_channels(clip,nullptr)!=expected_audio_.channels
        ||api_.audio_clip_load_type(clip,nullptr)!=0){audio_failed_=true;return fail(Result::failed,"private_audio_identity_mismatch");}
    drop(audio_request_);
    // PreloadAudioData may already have completed while LoadAsset ran. Do not
    // request a second load or treat that redundant request's false as failure.
    const int32_t state=api_.audio_clip_load_state(clip,nullptr);
    if(state==0&&!api_.audio_clip_load_data(clip,nullptr)){
        const int32_t after=api_.audio_clip_load_state(clip,nullptr);
        if(after!=1&&after!=2){audio_failed_=true;return fail(Result::failed,"private_audio_decode_rejected");}
    }
    return poll_private_audio();
}
inline Result GameAdapter::read_audio_chunk(int32_t offset,int32_t frames,float* dst,size_t capacity) {
    const Result ready=poll_private_audio();if(ready!=Result::ok)return ready;
    if(offset<0||frames<=0||frames>8192||offset>expected_audio_.samples-frames||!dst
        ||!api_.new_float_array||!api_.audio_clip_get_data)return fail(Result::invalid,"audio_chunk_out_of_bounds");
    const size_t samples=static_cast<size_t>(frames)*static_cast<size_t>(expected_audio_.channels);
    if(capacity<samples)return fail(Result::invalid,"audio_buffer_too_small");
    if(!audio_array_||api_.array_length(get(audio_array_))!=samples){drop(audio_array_);
        if(!keep(audio_array_,api_.new_float_array(samples)))return fail(Result::failed,"audio_array_allocation_failed");}
    if(!api_.audio_clip_get_data(get(audio_clip_),get(audio_array_),offset,nullptr))return fail(Result::failed,"audio_get_data_rejected");
    const auto* data=static_cast<const float*>(api_.array_data(get(audio_array_)));
    if(!data)return fail(Result::failed,"audio_array_data_missing");
    for(size_t i=0;i<samples;++i)if(!std::isfinite(data[i]))return fail(Result::failed,"audio_decode_nonfinite");
    std::memcpy(dst,data,samples*sizeof(float));return Result::ok;
}
inline void GameAdapter::maintenance() { if(audio_cancel_pending_)close_private_audio(); }
inline void GameAdapter::close_private_audio() {
    if(audio_request_){
        if(!api_.async_done(get(audio_request_),nullptr)){audio_cancel_pending_=true;return;}
        if(!audio_bundle_){void* bundle=api_.bundle_request_get_bundle(get(audio_request_),nullptr);if(bundle)keep(audio_bundle_,bundle);}
    }
    drop(audio_array_);drop(audio_clip_);
    if(void* bundle=get(audio_bundle_))if(api_.bundle_unload)api_.bundle_unload(bundle,true,nullptr);
    drop(audio_bundle_);drop(audio_request_);expected_audio_={};audio_cancel_pending_=false;audio_failed_=false;
}
inline Result GameAdapter::restore_logical(){
    if(!automatic_)return fail(Result::invalid,"original_playback_not_owned");
    return restore_impl(false);
}
inline Result GameAdapter::restore(){return restore_impl(true);}
inline Result GameAdapter::restore_impl(bool release_resources) {
    capture_pending_=capture_pass_seen_=capture_submitted_=false;
    close_private_audio();
    if(automatic_){
        const auto clock=api_.automatic_clock_state?api_.automatic_clock_state():idoly_mp4_playback::ClockState{};
        // Lens/target restoration belongs to the same held-clock boundary as
        // graph and actor restoration. Scene loss may still discard our CPU
        // bookkeeping immediately, without changing the replacement scene.
        if(!automatic_scope_.logical_restored()){
            const auto quiet=automatic_scope_.prepare_restore(clock);
            if(quiet!=idoly_mp4_playback::Result::ok&&quiet!=idoly_mp4_playback::Result::stale)
                return automatic_result(quiet);
        }
        if(output_geometry_applied_){
            if(api_.output_geometry)automatic_geometry_restored_=api_.output_geometry(
                owned_primary_scene_current()?get(camera_controller_):nullptr,0,0);
            else automatic_geometry_restored_=false;
            output_geometry_applied_=false;
        }
        const auto result=automatic_scope_.restore(clock,release_resources);
        if(!release_resources){
            if(result==idoly_mp4_playback::Result::ok&&!automatic_geometry_restored_)
                return fail(Result::failed,"output_restore_failed");
            return automatic_result(result);
        }
        if(automatic_scope_.active())return automatic_result(result);
        release_shader_lease();
        manual_=automatic_=false;clear_owned_anchors();graph_={};evaluated_time_=0;evaluation_failed_=false;
        if(void* cpu=get(cpu_texture_))if(api_.object_destroy)api_.object_destroy(cpu,nullptr);
        drop(cpu_texture_);drop(captured_texture_);
        if(result==idoly_mp4_playback::Result::ok&&!automatic_geometry_restored_)
            return fail(Result::failed,"output_restore_failed");
        return automatic_result(result);
    }
    const auto owned=[this](){return manual_&&primary_scene_current();};
    const auto actor_current=[this](const ActorGraph& entry){
        void* animation=get(entry.player);
        const PlayableGraph current=animation&&live(animation)?field<PlayableGraph>(animation,layout_.animation_player_graph):PlayableGraph{};
        return current.handle==entry.graph.handle&&current.version==entry.graph.version;
    };
    bool geometry_restored=true;
    if(output_geometry_applied_){
        // A pooled controller/camera may already belong to another scene.
        // A null owner clears bridge bookkeeping without any Unity writes.
        if(api_.output_geometry)geometry_restored=api_.output_geometry(owned()?get(camera_controller_):nullptr,0,0);
        output_geometry_applied_=false;
    }
    if(owned()){
        if(void* director=get(director_))if(live(director)){
            api_.director_set_time(director,snapshot_.previous_time_seconds,nullptr);
            if(owned())api_.director_evaluate(director,nullptr);
            for(size_t i=0;i<actor_graph_count_&&owned();++i)
                if(actor_current(actor_graphs_[i])&&api_.graph_valid(&actor_graphs_[i].graph,nullptr))
                    api_.graph_evaluate_injected(&actor_graphs_[i].graph,0,nullptr);
            if(owned())api_.director_set_mode(director,snapshot_.previous_update_mode,nullptr);
        }
        if(owned()&&live(get(brain_))){
            (void)update_camera(-1);
            if(owned()){
                std::memcpy(static_cast<uint8_t*>(get(brain_))+layout_.brain_update_mode,&previous_brain_update_,sizeof(previous_brain_update_));
                std::memcpy(static_cast<uint8_t*>(get(brain_))+layout_.brain_blend_update_mode,&previous_brain_blend_,sizeof(previous_brain_blend_));
            }
        }
        for(size_t i=0;i<actor_graph_count_&&owned();++i)
            if(actor_current(actor_graphs_[i])&&api_.graph_valid(&actor_graphs_[i].graph,nullptr))
                api_.graph_set_mode_injected(&actor_graphs_[i].graph,actor_graphs_[i].previous_mode,nullptr);
        if(owned())if(void* source=get(bgm_source_))if(live(source))api_.audio_source_set_volume(source,previous_bgm_volume_,nullptr);
        if(owned())if(void* source=get(voice_source_))if(live(source))api_.audio_source_set_volume(source,previous_voice_volume_,nullptr);
        if(owned()){
            if(shader_was_custom_)api_.shader_set_custom(previous_shader_time_,nullptr);else api_.shader_reset_custom(nullptr);
        }
    }
    manual_=false;clear_owned_anchors();graph_={};evaluated_time_=0;evaluation_failed_=false;
    if(void* cpu=get(cpu_texture_))if(api_.object_destroy)api_.object_destroy(cpu,nullptr);
    drop(cpu_texture_);drop(captured_texture_);
    return geometry_restored?Result::ok:fail(Result::failed,"output_restore_failed");
}
inline Result GameAdapter::abandon_automatic(const char* reason){
    if(!automatic_)return Result::ok;
    capture_pending_=capture_pass_seen_=capture_submitted_=false;
    close_private_audio();release_shader_lease();
    if(output_geometry_applied_){
        // Null is the bridge's cleanup-only command. It cannot restore the
        // previous camera/target after clock ownership was relinquished.
        if(api_.output_geometry)(void)api_.output_geometry(nullptr,0,0);
        output_geometry_applied_=false;
    }
    const auto result=automatic_scope_.abandon();
    if(automatic_scope_.active())return automatic_result(result);
    manual_=automatic_=false;clear_owned_anchors();graph_={};evaluated_time_=0;evaluation_failed_=false;
    if(void* cpu=get(cpu_texture_))if(api_.object_destroy)api_.object_destroy(cpu,nullptr);
    drop(cpu_texture_);drop(captured_texture_);
    return fail(static_cast<Result>(result),reason?reason:"original_engine_clock_lost");
}
inline void GameAdapter::reset_observations() {
    restore();if(restoration_pending())return;
    drop(presenter_);drop(photo_mode_);drop(photo_data_);drop(camera_controller_);drop(player_);drop(director_);drop(timeline_asset_);drop(camera_);
    drop(bgm_source_);drop(voice_source_);drop(brain_);drop_actor_graphs();drop_audio_scope();snapshot_={};error_="none";
    drop(camera_timeline_director_);drop(camera_timeline_asset_);drop(camera_timeline_track_);camera_scope_identity_=0;
    scene_kind_=SceneKind::none;owner_replaced_=false;
}
} // namespace idoly_mp4_game
