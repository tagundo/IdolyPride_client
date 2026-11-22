// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once
#include "mp4_replay.hpp"
#include "mp4_queue_cleanup.hpp"
namespace idoly_mp4_runtime {
namespace queue_model=idoly_mp4_queue;
namespace replay_model=idoly_mp4_replay;
enum class QueueCommandKind {none,configure,enqueue,run,pause,resume,mutate};
struct QueueRequest {
    QueueCommandKind kind=QueueCommandKind::none;Options options{};
    char root[path_capacity]{},exports[path_capacity]{},id[33]{};
    int operation=0,position=0;uint64_t selection_identity=0;
};
static QueueRequest queue_request;
static pthread_mutex_t queue_owner_mutex=PTHREAD_MUTEX_INITIALIZER;
// Process-lifetime POD storage has no C++ atexit callback. Per-job reset still
// releases every managed root on Unity; process teardown must never call a
// managed GC API after its image/domain has already been unloaded.
struct QueueOwners { queue_model::Queue store{};replay_model::Replay replay{},immediate{}; };
alignas(QueueOwners) static uint8_t queue_owner_storage[sizeof(QueueOwners)]{};
static bool queue_owners_initialized=false;
inline QueueOwners& queue_owners(){
    if(!queue_owners_initialized){
#ifdef IDOLY_DARWIN_BRIDGE
        new(idoly_mp4_queue_placement::Address{queue_owner_storage})QueueOwners{};
#else
        new(queue_owner_storage)QueueOwners{};
#endif
        queue_owners_initialized=true;
    }
    return *reinterpret_cast<QueueOwners*>(queue_owner_storage);
}
inline queue_model::Queue& queue_store(){return queue_owners().store;}
inline replay_model::Replay& queue_replay(){return queue_owners().replay;}
inline replay_model::Replay& immediate_replay(){return queue_owners().immediate;}
static bool fresh_immediate_saved=false,fresh_immediate_started=false,fresh_immediate_failed=false;
static bool queue_available=false,queue_running=false,queue_paused=false,queue_replay_available=false,
    queue_export_started=false,queue_cancel_requested=false,queue_clock_was_paused=false;
static bool queue_fresh_origin_saved=false;
static bool queue_fresh_prepare_failed=false;
static bool queue_active_published=false;
static bool queue_can_run=false,queue_blocked=false;
static bool queue_pause_pending=false;
static int queue_exports=-1;
static char queue_root[path_capacity]{},queue_export_root[path_capacity]{},queue_active_id[33]{},queue_last_added[33]{};
static char queue_error[65]="none",queue_phase[32]="idle";
static char queue_published[16384]="{\"schema\":1,\"available\":false,\"command_pending\":false,\"error_code\":\"queue_not_configured\",\"last_added_job_id\":\"\",\"running\":false,\"paused\":false,\"phase\":\"idle\",\"capacity\":8,\"jobs\":[]}";
static queue_model::Descriptor queue_descriptor_work;
struct QueueCandidate {
    queue_model::Descriptor descriptor{};queue_model::Graphics graphics{};
    uint32_t width=0,height=0;
    uint64_t identity=0,generation=0,broker_epoch=0;bool valid=false;
};
// Frozen value storage, never a managed object or a render target. Host Add
// borrows it only while holding queue_owner_mutex through the journal commit.
static QueueCandidate queue_candidate;
static char queue_candidate_error[96]="selected_mv_snapshot_missing";
static uint64_t queue_observed_identity=0,queue_observed_generation=0;
static void* queue_observed_player=nullptr;
static void* queue_observed_presenter=nullptr;
static bool (*queue_graphics_snapshot)(queue_model::Graphics&)=nullptr;
static bool (*queue_graphics_revision)(int64_t&)=nullptr;
static bool (*queue_graphics_apply)(const queue_model::Graphics*)=nullptr;
#ifdef IDOLY_DARWIN_BRIDGE
static const char* queue_profile_sha=idoly_mp4_game::ios_original_sha256;
#else
static const char* queue_profile_sha=idoly_mp4_game::android_original_sha256;
#endif
inline void queue_process(const QueueRequest& request);

inline void queue_observe_selection(){
    void* player=game.selected_player();void* presenter=game.selected_presenter();
    const uint64_t identity=selection.identity(player);
    pthread_mutex_lock(&control_mutex);const uint64_t generation=queue_selection_generation;pthread_mutex_unlock(&control_mutex);
    if(player==queue_observed_player&&presenter==queue_observed_presenter
        &&identity==queue_observed_identity&&generation==queue_observed_generation)return;
    if(player&&identity&&selection.selected(player,queue_descriptor_work)==Result::ok
        &&queue_replay().observe(presenter,player,queue_descriptor_work,identity)){
        queue_observed_player=player;queue_observed_presenter=presenter;
        queue_observed_identity=identity;queue_observed_generation=generation;
    }
}
inline bool queue_same_graphics(const queue_model::Graphics&a,const queue_model::Graphics&b){
    return a.revision==b.revision&&a.custom_graphics==b.custom_graphics&&a.quality==b.quality&&a.target_fps==b.target_fps
        &&a.render_scale==b.render_scale&&a.max_buffer_pixel==b.max_buffer_pixel&&a.aa_mode==b.aa_mode
        &&a.shadow_resolution==b.shadow_resolution&&a.expand_photography==b.expand_photography;
}
// No Audio/Actor export programme, Rebuild, Pause, or private API is queried.
// The real ordinary initialization observer owns the immutable descriptor.
inline Result probe_selection_source(){
 pthread_mutex_lock(&control_mutex);const uint64_t generation=queue_selection_generation;pthread_mutex_unlock(&control_mutex);
 void*player=game.selected_player();const uint64_t identity=selection.identity(player);
 Result result=Result::waiting;const char*error="selected_mv_not_loaded";bool observed=false;
 int32_t width=0,height=0;
 if(player){
  result=selection.selected(player,queue_descriptor_work);
  if(result!=Result::ok)error=selection.error();
  else if(identity){
   observed=true;result=game.source_geometry(width,height);
   error=result==Result::ok?"none":result==Result::waiting?"selected_capture_geometry_not_ready":"selected_capture_geometry_unsupported";
  }
 }
 const bool current=player&&game.selected_player()==player&&identity&&selection.identity(player)==identity;
 pthread_mutex_lock(&control_mutex);
 if(generation!=queue_selection_generation||(player&&identity&&!current)){observed=false;result=Result::waiting;error="selected_mv_selection_changed";}
 selected_mv=observed;
 selected_source_width=observed&&result==Result::ok&&idoly_mp4_output::source_dimensions(width,height)?static_cast<uint32_t>(width):0;
 selected_source_height=selected_source_width?static_cast<uint32_t>(height):0;
 if(selected_source_width){published.source_width=selected_source_width;published.source_height=selected_source_height;}
 if(observed)selected_identity=identity;
 snprintf(selection_error,sizeof(selection_error),"%s",error);
 pthread_mutex_unlock(&control_mutex);return result;
}
inline void queue_refresh_candidate(Result readiness){
    // Called after the independent readonly selected-source probe on Unity.
    pthread_mutex_lock(&queue_owner_mutex);
    pthread_mutex_lock(&control_mutex);
    const uint64_t generation=queue_selection_generation,epoch=configured.epoch;
    const uint32_t width=selected_source_width,height=selected_source_height;
    const bool available=installed&&configured_valid&&!control_busy&&!start_pending;
    const bool parked=requested_pause_reason==IDMP4_PAUSE_LIFECYCLE_BACKGROUND
        ||requested_pause_reason==IDMP4_PAUSE_SURFACE_UNAVAILABLE;
    char reason[96]{};snprintf(reason,sizeof(reason),"%s",selection_error);
    pthread_mutex_unlock(&control_mutex);
    if(!available||!generation){pthread_mutex_unlock(&queue_owner_mutex);return;}
    if(readiness!=Result::ok){
        snprintf(queue_candidate_error,sizeof(queue_candidate_error),"%s",reason);
        // A server menu can release only the original render target while the
        // selected logical MV remains unchanged. Preserve that verified value.
        const bool target_lost=!strcmp(reason,"selected_capture_geometry_not_ready")
            ||!strcmp(reason,"selected_capture_geometry_unsupported")||!strcmp(reason,"selected_render_controller_missing")
            ||!strcmp(reason,"selected_camera_not_loaded")||!strcmp(reason,"selected_mv_camera_not_observed");
        if(!parked&&!target_lost&&queue_candidate.valid&&queue_candidate.generation==generation)
            invalidate_queue_selection("selected_mv_snapshot_not_ready");
        pthread_mutex_unlock(&queue_owner_mutex);return;
    }
    void* player=game.selected_player();const uint64_t identity=selection.identity(player);
    queue_model::Graphics graphics{};
    if(!identity||!idoly_mp4_output::source_dimensions(width,height)
        ||!queue_graphics_snapshot||!queue_graphics_snapshot(graphics)||!queue_model::detail::graphics(graphics)){
        snprintf(queue_candidate_error,sizeof(queue_candidate_error),"selected_graphics_snapshot_unavailable");
        if(queue_candidate.valid&&queue_candidate.generation==generation)
            invalidate_queue_selection("selected_graphics_snapshot_unavailable");
        pthread_mutex_unlock(&queue_owner_mutex);return;
    }
    const bool descriptor_changed=!queue_candidate.valid||queue_candidate.generation!=generation
        ||queue_candidate.identity!=identity||queue_candidate.broker_epoch!=epoch;
    if(descriptor_changed&&selection.selected(player,queue_descriptor_work)!=Result::ok){
        invalidate_queue_selection("selected_mv_snapshot_not_ready");pthread_mutex_unlock(&queue_owner_mutex);return;
    }
    // Host lifecycle invalidation may race the original Unity getters. Never
    // republish the old scope after a destroy/configuration generation change.
    pthread_mutex_lock(&control_mutex);
    const bool current=generation==queue_selection_generation&&epoch==configured.epoch&&configured_valid
        &&identity==selected_identity&&!control_busy&&!start_pending;
    if(current){
        if(descriptor_changed)queue_candidate.descriptor=queue_descriptor_work;
        if(descriptor_changed||queue_candidate.width!=width||queue_candidate.height!=height
            ||!queue_same_graphics(queue_candidate.graphics,graphics)){
            queue_candidate.graphics=graphics;queue_candidate.width=width;queue_candidate.height=height;
        }
        queue_candidate.identity=identity;queue_candidate.generation=generation;queue_candidate.broker_epoch=epoch;queue_candidate.valid=true;
        snprintf(queue_candidate_error,sizeof(queue_candidate_error),"none");
        snprintf(queue_selection_reason,sizeof(queue_selection_reason),"%s","none");
    }
    pthread_mutex_unlock(&control_mutex);pthread_mutex_unlock(&queue_owner_mutex);
}
inline void install_queue_api(const replay_model::Api& api,bool(*snapshot)(queue_model::Graphics&),
    bool(*apply)(const queue_model::Graphics*),const char* profile,bool(*revision)(int64_t&)=nullptr){
    pthread_mutex_lock(&queue_owner_mutex);
    if(queue_active_id[0]){pthread_mutex_unlock(&queue_owner_mutex);return;}
    invalidate_queue_selection("queue_profile_changed");
    queue_observed_identity=queue_observed_generation=0;queue_observed_player=queue_observed_presenter=nullptr;
    queue_replay_available=queue_replay().set_api(api)&&immediate_replay().set_api(api);queue_graphics_snapshot=snapshot;queue_graphics_revision=revision;
    queue_graphics_apply=apply;queue_profile_sha=profile;
    pthread_mutex_unlock(&queue_owner_mutex);
}
inline bool fresh_factory_receipt(FreshFactoryReceipt*out){
    if(out){*out={};}
    if(!out||!fresh_scene_installed.load(std::memory_order_acquire))return false;
    auto&replay=queue_active_id[0]?queue_replay():immediate_replay();
    if(!replay.fresh_ready()||replay.player()!=game.selected_player()
        ||replay.presenter()!=game.selected_presenter())return false;
    const uint64_t identity=selection.identity(replay.player());
    if(!identity||identity!=replay.ready_identity())return false;
    *out={replay.ready_load_serial(),identity,replay.presenter(),replay.player()};return out->serial!=0;
}
inline void fresh_release_start(){
    if(!queue_active_id[0]){(void)immediate_replay().reset();
        fresh_immediate_saved=fresh_immediate_started=fresh_immediate_failed=false;}
}
inline Result fresh_prepare_start(){
    if(!fresh_scene_installed.load(std::memory_order_acquire))return Result::ok;
    // Queue Run already saved the origin and completed this exact factory load.
    if(pending_queue_output[0]){FreshFactoryReceipt value{};return fresh_factory_receipt(&value)?Result::ok:Result::waiting;}
    auto&replay=immediate_replay();
    pthread_mutex_lock(&control_mutex);const bool cancelled=cancel_pending;pthread_mutex_unlock(&control_mutex);
    if(cancelled||fresh_immediate_failed){
        if(replay.active()){replay.cancel();replay.tick(milliseconds());if(replay.active())return Result::waiting;}
        if(!replay.settle_failure())return Result::waiting;
        if(fresh_immediate_saved){
            const Result restored=fresh_scene_api.finish(fresh_scene_api.context);
            if(restored==Result::waiting)return Result::waiting;
        }
        fresh_release_start();return Result::failed;
    }
    if(!fresh_immediate_saved){
        const Result saved=fresh_scene_api.save_origin(fresh_scene_api.context);
        if(saved!=Result::ok)return saved;
        fresh_immediate_saved=true;
    }
    void*player=game.selected_player(),*presenter=game.selected_presenter();
    const uint64_t identity=selection.identity(player);
    if(player&&presenter&&identity&&selection.selected(player,queue_descriptor_work)==Result::ok)
        (void)replay.observe(presenter,player,queue_descriptor_work,identity);
    if(!fresh_immediate_started){
        if(!player||!identity)return Result::waiting;
        if(selection.selected(player,queue_descriptor_work)!=Result::ok)return Result::waiting;
        if(!queue_replay_available||!replay.begin(queue_descriptor_work,milliseconds(),true)){
            fresh_immediate_failed=true;return Result::waiting;}
        fresh_immediate_started=true;
    }
    replay.tick(milliseconds());
    if(replay.phase()==replay_model::Phase::failed){fresh_immediate_failed=true;return Result::waiting;}
    FreshFactoryReceipt value{};return fresh_factory_receipt(&value)?Result::ok:Result::waiting;
}
inline void queue_set_error(const char* value){snprintf(queue_error,sizeof(queue_error),"%s",value?value:"queue_failed");}
inline void queue_set_storage_error(queue_model::Error result){
    if(result==queue_model::Error::io&&strcmp(queue_store().storage_stage(),"none"))
        snprintf(queue_error,sizeof(queue_error),"queue_%s_failed",queue_store().storage_stage());
    else queue_set_error(queue_model::error_code(result));
}
inline bool queue_cached_add(char*error,size_t capacity){
 const char*reason=nullptr;char selected_reason[96]{};
 pthread_mutex_lock(&control_mutex);
 if(!queue_available||queue_blocked)reason="queue_not_configured";
 else if(control_busy||start_pending||queue_active_published||queue_scene_owned||queue_request.kind!=QueueCommandKind::none)reason="queue_busy";
 else if(!queue_candidate.valid){const char*missing=selected_mv?queue_candidate_error:"selected_mv_snapshot_missing";
  if(!strcmp(missing,"none"))missing="selected_mv_snapshot_pending";
  snprintf(selected_reason,sizeof(selected_reason),"%s",missing);reason=selected_reason;}
 else if(!configured_valid||queue_candidate.generation!=queue_selection_generation||queue_candidate.broker_epoch!=configured.epoch
  ||!selected_identity||queue_candidate.identity!=selected_identity)reason="selected_mv_selection_changed";
 else if(!selected_mv)reason="selected_mv_snapshot_missing";
 pthread_mutex_unlock(&control_mutex);
 if(!reason){int64_t revision=-1;
  if(!queue_graphics_revision||!queue_graphics_revision(revision)||revision<0)reason="selected_graphics_revision_unavailable";
  else if(revision!=queue_candidate.graphics.revision)reason="selected_graphics_changed_before_enqueue";
 }
 if(!reason){pthread_mutex_lock(&control_mutex);
  if(!configured_valid||queue_candidate.generation!=queue_selection_generation||queue_candidate.broker_epoch!=configured.epoch
   ||control_busy||start_pending)reason="selected_mv_selection_changed";
  pthread_mutex_unlock(&control_mutex);}
 if(error&&capacity)snprintf(error,capacity,"%s",reason?reason:"none");
 return !reason;
}
inline void queue_publish(){
    char next[16384]{};size_t at=0;
    auto append=[&](const char* format,auto... values){if(at>=sizeof(next))return;const int n=snprintf(next+at,sizeof(next)-at,format,values...);if(n<0||static_cast<size_t>(n)>=sizeof(next)-at){at=sizeof(next);return;}at+=static_cast<size_t>(n);};
    pthread_mutex_lock(&control_mutex);const bool command_pending=queue_pause_pending||queue_request.kind!=QueueCommandKind::none;pthread_mutex_unlock(&control_mutex);
    char add_error[96]{};const bool can_add=queue_cached_add(add_error,sizeof add_error);
    append("{\"schema\":1,\"available\":%s,\"command_pending\":%s,\"error_code\":\"%s\",\"last_added_job_id\":\"%s\",\"running\":%s,\"paused\":%s,\"phase\":\"%s\",\"capacity\":8,\"current_job_id\":\"%s\",\"replay_available\":%s,\"can_run\":%s,\"can_add\":%s,\"add_error\":\"%s\",\"storage_stage\":\"%s\",\"storage_errno\":%d,\"jobs\":[",
        queue_available?"true":"false",command_pending?"true":"false",queue_error,queue_last_added,
        queue_running?"true":"false",queue_paused?"true":"false",queue_phase,queue_active_id,queue_replay_available?"true":"false",queue_can_run?"true":"false",can_add?"true":"false",add_error,queue_store().storage_stage(),queue_store().storage_errno());
    for(size_t i=0;i<queue_store().count();++i){const auto* queued=queue_store().at(i);if(!queued)continue;
        append("%s{\"job_id\":\"%s\",\"output_id\":\"%s\",\"timeline\":\"%s\",\"actor_count\":%u,\"width\":%u,\"height\":%u,\"source_width\":%u,\"source_height\":%u,\"fps_num\":%u,\"video_codec\":%u,\"video_bitrate\":%u,\"state\":\"%s\",\"error_code\":\"%s\"}",
            i?",":"",queued->id,queued->output_id,queued->descriptor.timeline_asset,queued->descriptor.actor_count,
            queued->options.output_width?queued->options.output_width:queued->options.width&~1U,
            queued->options.output_height?queued->options.output_height:queued->options.height&~1U,
            queued->options.width,queued->options.height,queued->options.fps_num,queued->options.codec,queued->options.video_bitrate,
            queue_model::state_name(queued->state),queued->error[0]?queued->error:"none");
    }append("%s","]}");
    if(at>=sizeof(next))snprintf(next,sizeof(next),"{\"schema\":1,\"available\":false,\"error_code\":\"queue_status_overflow\",\"jobs\":[]}");
    pthread_mutex_lock(&control_mutex);memcpy(queue_published,next,sizeof(next));queue_active_published=queue_active_id[0]!=0;queue_scene_owned=queue_active_published||queue_running;pthread_mutex_unlock(&control_mutex);
}
inline bool queue_configure(const char* root,const char* exports){
    if(!safe_root(root)||!safe_root(exports)||!strcmp(root,exports))return false;
    pthread_mutex_lock(&queue_owner_mutex);
    pthread_mutex_lock(&control_mutex);
    if((queue_available&&!queue_blocked&&!strcmp(root,queue_root)&&!strcmp(exports,queue_export_root))
        ||(queue_request.kind==QueueCommandKind::configure&&!strcmp(root,queue_request.root)&&!strcmp(exports,queue_request.exports))){pthread_mutex_unlock(&control_mutex);pthread_mutex_unlock(&queue_owner_mutex);return true;}
    if(queue_request.kind!=QueueCommandKind::none||queue_active_published){pthread_mutex_unlock(&control_mutex);pthread_mutex_unlock(&queue_owner_mutex);return false;}
    pthread_mutex_unlock(&control_mutex);
    invalidate_queue_selection("queue_configuration_changed");
    QueueRequest request{};request.kind=QueueCommandKind::configure;
    snprintf(request.root,sizeof(request.root),"%s",root);snprintf(request.exports,sizeof(request.exports),"%s",exports);
    // Journal inspection/recovery needs no Unity object or graphics API. The
    // host can populate its cold server menu before starting the game engine.
    queue_process(request);queue_publish();const bool ok=queue_available&&(!strcmp(queue_error,"none")||!strcmp(queue_error,"queue_temporary_cleanup_deferred"));
    pthread_mutex_unlock(&queue_owner_mutex);return ok;
}
inline bool queue_enqueue_candidate(const Options& requested){
    pthread_mutex_lock(&queue_owner_mutex);
    pthread_mutex_lock(&control_mutex);
    const char* error=nullptr;
    if(!queue_available||queue_blocked)error=strcmp(queue_error,"none")?queue_error:"queue_not_configured";
    else if(queue_request.kind!=QueueCommandKind::none||control_busy||start_pending||queue_active_published||queue_scene_owned)error="queue_busy";
    else if(!valid_options(requested))error="invalid_export_options";
    else if(!queue_candidate.valid)error="selected_mv_snapshot_missing";
    else if(!queue_selection_generation||queue_candidate.generation!=queue_selection_generation
        ||queue_candidate.broker_epoch!=configured.epoch||!configured_valid
        ||(selected_identity&&selected_identity!=queue_candidate.identity))
        error=strcmp(queue_selection_reason,"none")?queue_selection_reason:"selected_mv_selection_changed";
    else if(!selected_mv)error="selected_mv_snapshot_missing";
    char failure[65]{};if(error)snprintf(failure,sizeof(failure),"%s",error);
    pthread_mutex_unlock(&control_mutex);
    if(error){queue_set_error(failure);queue_publish();pthread_mutex_unlock(&queue_owner_mutex);return false;}
    // Only a pure host configuration revision is read here. Resolving effective
    // quality/FPS still belongs to the original Unity-thread snapshot above.
    int64_t revision=-1;
    if(!queue_graphics_revision||!queue_graphics_revision(revision)||revision<0)
        error="selected_graphics_revision_unavailable";
    else if(revision!=queue_candidate.graphics.revision)error="selected_graphics_changed_before_enqueue";
    pthread_mutex_lock(&control_mutex);
    if(!error&&(queue_candidate.generation!=queue_selection_generation||queue_candidate.broker_epoch!=configured.epoch
        ||!configured_valid||control_busy||start_pending))error="selected_mv_selection_changed";
    pthread_mutex_unlock(&control_mutex);
    if(error){queue_set_error(error);queue_publish();pthread_mutex_unlock(&queue_owner_mutex);return false;}
    queue_model::Options options{};options.fps_num=requested.fps_num;options.fps_den=requested.fps_den;
    options.codec=requested.codec;options.audio_bitrate=requested.audio_bitrate;
    options.width=queue_candidate.width;options.height=queue_candidate.height;options.graphics=queue_candidate.graphics;
    options.output_width=requested.output_width;options.output_height=requested.output_height;
    uint32_t width=0,height=0;
    if(!idoly_mp4_output::resolved_dimensions(options.width,options.height,options.output_width,options.output_height,width,height)){
        queue_set_error("invalid_export_options");queue_publish();pthread_mutex_unlock(&queue_owner_mutex);return false;
    }
    options.video_bitrate=idoly_mp4_output::resolved_bitrate(requested.bitrate,width,height,options.fps_num,options.codec);
    // Acceptance was linearized above. A later End can invalidate future Adds,
    // but cannot replace this immutable descriptor with another scene's data.
    const auto result=queue_store().enqueue(queue_candidate.descriptor,options,queue_last_added);
    if(result==queue_model::Error::ok){queue_set_error("none");if(!queue_active_id[0]&&!queue_running)snprintf(queue_phase,sizeof(queue_phase),"%s",queue_paused?"paused":"idle");}
    else queue_set_storage_error(result);
    queue_publish();pthread_mutex_unlock(&queue_owner_mutex);return result==queue_model::Error::ok;
}
inline bool queue_accept(QueueCommandKind kind,Options options={},int operation=0,const char* id=nullptr,int position=0){
    if(kind==QueueCommandKind::enqueue)return queue_enqueue_candidate(options);
    if(kind==QueueCommandKind::mutate&&(operation<IDMP4_QUEUE_CANCEL||operation>IDMP4_QUEUE_MOVE||!queue_model::detail::hex(id,32)||position<0))return false;
    pthread_mutex_lock(&control_mutex);
    if(kind==QueueCommandKind::pause){
        if(!queue_available||queue_blocked){pthread_mutex_unlock(&control_mutex);return false;}
        // A server stop must win over a previously accepted Run/Resume even
        // before Unity gets another tick. This is a host-only signal; managed
        // task cleanup and the persistent queue transition happen on Unity.
        queue_pause_pending=true;requested_pause_reason=IDMP4_PAUSE_USER;
        if(queue_request.kind==QueueCommandKind::run||queue_request.kind==QueueCommandKind::resume)
            queue_request.kind=QueueCommandKind::none;
        pthread_mutex_unlock(&control_mutex);return true;
    }
    if(!queue_available||queue_blocked||queue_request.kind!=QueueCommandKind::none
        ||((kind==QueueCommandKind::run||kind==QueueCommandKind::resume)&&!queue_can_run&&!queue_active_published)){pthread_mutex_unlock(&control_mutex);return false;}
    queue_request=QueueRequest{};queue_request.kind=kind;queue_request.options=options;
    queue_request.operation=operation;queue_request.position=position;queue_request.selection_identity=selected_identity;
    if(id)memcpy(queue_request.id,id,33);
    if(kind==QueueCommandKind::run||kind==QueueCommandKind::resume)queue_scene_owned=true;
    pthread_mutex_unlock(&control_mutex);return true;
}
inline size_t queue_status(char* buffer,size_t capacity){
    if(!buffer||!capacity)return 0;
    // Refresh only bounded host-owned values. This never resumes Unity or
    // calls selection/geometry getters while the server menu owns the UI.
    pthread_mutex_lock(&queue_owner_mutex);queue_publish();pthread_mutex_unlock(&queue_owner_mutex);
    pthread_mutex_lock(&control_mutex);
    const size_t n=strlen(queue_published);const bool pending=queue_pause_pending||queue_request.kind!=QueueCommandKind::none;
    if(n>=capacity){pthread_mutex_unlock(&control_mutex);return 0;}
    memcpy(buffer,queue_published,n+1);
    // Commands are accepted on host threads before the next Unity tick can
    // publish a full snapshot. Keep this one fixed-width field current.
    char* flag=strstr(buffer,"\"command_pending\":false");
    if(pending&&flag){const size_t offset=static_cast<size_t>(flag-buffer)+18;for(size_t i=offset+4;i<n;++i)buffer[i]=buffer[i+1];memcpy(buffer+offset,"true",4);pthread_mutex_unlock(&control_mutex);return n-1;}
    pthread_mutex_unlock(&control_mutex);return n;
}
inline bool queue_record(queue_model::Error result){
    if(result==queue_model::Error::ok)return true;
    queue_running=false;pthread_mutex_lock(&control_mutex);queue_blocked=true;pthread_mutex_unlock(&control_mutex);queue_set_storage_error(result);
    snprintf(queue_phase,sizeof(queue_phase),"failed");return false;
}
inline bool queue_has_pending(){
    for(size_t i=0;i<queue_store().count();++i){const auto*entry=queue_store().at(i);
        if(entry&&entry->state==queue_model::State::pending)return true;}
    return false;
}
inline void queue_process(const QueueRequest& request){
    if(queue_blocked&&request.kind!=QueueCommandKind::configure)return;
    queue_set_error("none");
    if(request.kind==QueueCommandKind::configure){
        if(queue_active_id[0]){queue_set_error("queue_busy");return;}
        if(!queue_profile_sha){queue_set_error("queue_api_unavailable");return;}
        int exports=open(request.exports,rd|directory|nofollow);
        if(!private_directory(exports)){if(exports>=0)close(exports);queue_set_error("unsafe_queue_storage");return;}
        const auto result=queue_store().open(request.root,queue_profile_sha);
        if(result!=queue_model::Error::ok){close(exports);pthread_mutex_lock(&control_mutex);queue_available=false;pthread_mutex_unlock(&control_mutex);queue_set_storage_error(result);return;}
        // Recovery converted only prior active jobs to interrupted while
        // holding the exclusive journal lock. Their exact opaque output IDs
        // authorize removal of private temporary artifacts, never final MP4s.
        for(size_t i=0;i<queue_store().count();++i){const auto* recovered=queue_store().at(i);
            if(recovered&&recovered->state==queue_model::State::interrupted&&recovered->output_id[0]
                &&idoly_mp4_queue_cleanup::clean(exports,recovered->output_id)!=idoly_mp4_queue_cleanup::Result::ok)
                queue_set_error("queue_temporary_cleanup_deferred");
        }
        if(queue_exports>=0)close(queue_exports);
        queue_exports=exports;queue_running=queue_paused=false;
        pthread_mutex_lock(&control_mutex);queue_blocked=false;snprintf(queue_root,sizeof(queue_root),"%s",request.root);snprintf(queue_export_root,sizeof(queue_export_root),"%s",request.exports);queue_available=true;pthread_mutex_unlock(&control_mutex);
        snprintf(queue_phase,sizeof(queue_phase),"idle");return;
    }
    if(request.kind==QueueCommandKind::enqueue){
        // Enqueue is a synchronous host admission, never a deferred Unity job.
        queue_set_error("enqueue_requires_verified_snapshot");return;
    }
    if(request.kind==QueueCommandKind::run||request.kind==QueueCommandKind::resume){
        if(native_scene_required&&!native_scene_installed&&!fresh_scene_available&&!queue_active_id[0]){queue_set_error("offline_pipeline_not_verified");return;}
        if(!queue_replay_available){queue_set_error("replay_api_unavailable");return;}
        if(fresh_scene_installed.load(std::memory_order_acquire)&&!queue_active_id[0]&&queue_has_pending()){
            const Result saved=fresh_scene_api.save_origin(fresh_scene_api.context);
            if(saved!=Result::ok&&saved!=Result::waiting){queue_set_error(fresh_scene_error("fresh_origin_not_ready"));return;}
            queue_fresh_origin_saved=saved==Result::ok;
        }
        if(queue_active_id[0]){const auto* active=queue_store().find(queue_active_id);if(active&&active->state==queue_model::State::paused&&!queue_record(queue_store().resume(queue_active_id)))return;}
        queue_running=true;queue_paused=false;resume();
        snprintf(queue_phase,sizeof(queue_phase),"waiting_for_scene");return;
    }
    if(request.kind==QueueCommandKind::pause){
        if(queue_paused)return;
        queue_running=false;queue_paused=true;suspend(IDMP4_PAUSE_USER);
        if(queue_active_id[0]){const auto* active=queue_store().find(queue_active_id);if(active&&active->state!=queue_model::State::paused&&!queue_record(queue_store().pause(queue_active_id,"user_paused")))return;}
        snprintf(queue_phase,sizeof(queue_phase),"paused");return;
    }
    if(request.kind==QueueCommandKind::mutate){
        queue_model::Error result=queue_model::Error::invalid_argument;
        idoly_mp4_queue_cleanup::FinalFile completed_output{};
        if(request.operation==IDMP4_QUEUE_REMOVE){
            const auto* target=queue_store().find(request.id);
            if(target&&target->state==queue_model::State::completed){
                if(request.position!=1){queue_set_error("completed_delete_confirmation_required");return;}
                if(idoly_mp4_queue_cleanup::prepare_final(queue_exports,target->output_id,completed_output)!=idoly_mp4_queue_cleanup::Result::ok){queue_set_error("queue_final_cleanup_deferred");return;}
            }else if(request.position!=0){queue_set_error("job_state_changed");return;}
        }
        if(request.operation==IDMP4_QUEUE_RETRY||request.operation==IDMP4_QUEUE_REMOVE){
            const auto* target=queue_store().find(request.id);
            if(target&&target->output_id[0]&&target->state!=queue_model::State::running&&target->state!=queue_model::State::paused
                &&idoly_mp4_queue_cleanup::clean(queue_exports,target->output_id)!=idoly_mp4_queue_cleanup::Result::ok){
                idoly_mp4_queue_cleanup::discard_final(completed_output);queue_set_error("queue_temporary_cleanup_deferred");return;
            }
        }
        if(request.operation==IDMP4_QUEUE_CANCEL){
            if(!strcmp(request.id,queue_active_id)){queue_cancel_requested=true;queue_replay().cancel();if(queue_export_started)cancel();return;}
            result=queue_store().cancel(request.id);
        }else if(request.operation==IDMP4_QUEUE_REMOVE)result=queue_store().remove(request.id);
        else if(request.operation==IDMP4_QUEUE_RETRY)result=queue_store().retry(request.id);
        else if(request.operation==IDMP4_QUEUE_MOVE)result=queue_store().move(request.id,static_cast<size_t>(request.position));
        if(result!=queue_model::Error::ok){idoly_mp4_queue_cleanup::discard_final(completed_output);queue_set_storage_error(result);}
        else if(request.operation==IDMP4_QUEUE_REMOVE&&request.position==1
            &&idoly_mp4_queue_cleanup::remove_final(queue_exports,completed_output)!=idoly_mp4_queue_cleanup::Result::ok)
            queue_set_error("queue_final_cleanup_deferred");
    }
}
inline void queue_release_attempt(){
    if(queue_graphics_apply)queue_graphics_apply(nullptr);
    queue_replay().reset();queue_active_id[0]=0;queue_export_started=queue_cancel_requested=false;
    queue_fresh_origin_saved=false;
    queue_fresh_prepare_failed=false;
    queue_observed_identity=queue_observed_generation=0;queue_observed_player=queue_observed_presenter=nullptr;
}
inline void queue_execute(){
    pthread_mutex_lock(&control_mutex);const bool suspended=requested_pause_reason!=IDMP4_PAUSE_NONE,session_busy=control_busy;pthread_mutex_unlock(&control_mutex);
    // Cancellation/codec retirement may settle while paused; starting a new
    // original screen or advancing an export remains gated below.
    if(queue_blocked){if(!busy_stage()&&!session_busy&&queue_graphics_apply)queue_graphics_apply(nullptr);return;}
    if(queue_fresh_prepare_failed&&queue_active_id[0]&&!queue_export_started){
        if(fresh_scene_api.finish(fresh_scene_api.context)==Result::waiting){
            snprintf(queue_phase,sizeof(queue_phase),"restoring_selection");return;}
        if(!queue_record(queue_store().fail(queue_active_id,"queued_mv_prepare_failed")))return;
        queue_release_attempt();queue_running=false;queue_set_error("queued_mv_prepare_failed");return;
    }
    if(queue_cancel_requested&&queue_active_id[0]&&!queue_export_started){
        queue_replay().tick(milliseconds());
        if(queue_replay().active()){snprintf(queue_phase,sizeof(queue_phase),"cancelling");return;}
        if(fresh_scene_installed.load(std::memory_order_acquire)&&fresh_scene_api.finish(fresh_scene_api.context)==Result::waiting){
            snprintf(queue_phase,sizeof(queue_phase),"restoring_selection");return;}
        if(!queue_record(queue_store().cancel(queue_active_id)))return;
        queue_release_attempt();
    }
    if(queue_clock_was_paused){queue_replay().resume_clock(milliseconds());queue_clock_was_paused=false;}
    if(queue_active_id[0]&&queue_export_started){
        if(busy_stage()||session_busy)return;
        queue_model::Error result=queue_model::Error::ok;
        const auto* active=queue_store().find(queue_active_id);
        if(queue_cancel_requested||!strcmp(job.status.phase,"cancelled"))result=queue_store().cancel(queue_active_id);
        else if(!active||strcmp(active->output_id,job.status.id)){queue_running=false;queue_set_error("queued_session_identity_mismatch");pthread_mutex_lock(&control_mutex);queue_blocked=true;pthread_mutex_unlock(&control_mutex);return;}
        else if(!strcmp(job.status.phase,"completed"))result=queue_store().finish(queue_active_id);
        else result=queue_store().fail(queue_active_id,job.status.error);
        if(!queue_record(result))return;
        queue_release_attempt();
    }
    if(suspended||queue_paused){queue_clock_was_paused=true;return;}
    if(queue_clock_was_paused){queue_replay().resume_clock(milliseconds());queue_clock_was_paused=false;}
    if(!queue_available||!queue_running||!queue_replay_available)return;
    if(!queue_active_id[0]){
        if(busy_stage()||session_busy){snprintf(queue_phase,sizeof(queue_phase),"waiting_for_scene");return;}
        if(fresh_scene_installed.load(std::memory_order_acquire)&&!queue_fresh_origin_saved&&queue_has_pending()){
            const Result saved=fresh_scene_api.save_origin(fresh_scene_api.context);
            if(saved==Result::waiting){snprintf(queue_phase,sizeof(queue_phase),"saving_selection");return;}
            if(saved!=Result::ok){queue_running=false;queue_set_error(fresh_scene_error("fresh_origin_not_ready"));return;}
            queue_fresh_origin_saved=true;
        }
        const auto result=queue_store().claim_next(queue_active_id);
        if(result==queue_model::Error::not_found){
            if(fresh_scene_installed.load(std::memory_order_acquire)&&queue_fresh_origin_saved){
                const auto restored=fresh_scene_api.finish(fresh_scene_api.context);
                if(restored==Result::waiting){snprintf(queue_phase,sizeof(queue_phase),"restoring_selection");return;}
                queue_fresh_origin_saved=false;
            }
            queue_running=false;snprintf(queue_phase,sizeof(queue_phase),"completed");return;}
        if(result!=queue_model::Error::ok){queue_running=false;queue_set_storage_error(result);return;}
        const auto* next=queue_store().find(queue_active_id);
        if(!next||!queue_graphics_apply||!queue_graphics_apply(&next->options.graphics)
            ||!queue_replay().begin(next->descriptor,milliseconds(),fresh_scene_installed.load(std::memory_order_acquire))){
            if(fresh_scene_installed.load(std::memory_order_acquire)){queue_fresh_prepare_failed=true;return;}
            if(!queue_record(queue_store().fail(queue_active_id,"queued_mv_prepare_failed")))return;
            queue_release_attempt();queue_running=false;queue_set_error("queued_mv_prepare_failed");return;
        }
    }
    queue_observe_selection();queue_replay().tick(milliseconds());
    if(queue_replay().phase()==replay_model::Phase::failed){
        if(!queue_replay().settle_failure()){snprintf(queue_phase,sizeof(queue_phase),"draining_navigation");return;}
        if(fresh_scene_installed.load(std::memory_order_acquire)&&fresh_scene_api.finish(fresh_scene_api.context)==Result::waiting){
            snprintf(queue_phase,sizeof(queue_phase),"restoring_selection");return;}
        if(!queue_record(queue_store().fail(queue_active_id,queue_replay().error())))return;
        queue_set_error(queue_replay().error());queue_release_attempt();queue_running=false;return;}
    if(queue_replay().phase()!=replay_model::Phase::ready){snprintf(queue_phase,sizeof(queue_phase),"replaying");return;}
    if(game.selected_player()!=queue_replay().player()){snprintf(queue_phase,sizeof(queue_phase),"waiting_for_scene");return;}
    Snapshot ready{};if(game.snapshot(ready)!=Result::ok){snprintf(queue_phase,sizeof(queue_phase),"waiting_for_scene");return;}
    const auto* next=queue_store().find(queue_active_id);if(!next){queue_set_error("job_not_found");queue_running=false;queue_release_attempt();return;}
    pthread_mutex_lock(&control_mutex);
    snprintf(pending_queue_output,sizeof(pending_queue_output),"%s",next->output_id);
    snprintf(pending_queue_exports,sizeof(pending_queue_exports),"%s",queue_export_root);
    pending_queue_exports_fd=queue_exports;pending_queue_width=next->options.width;pending_queue_height=next->options.height;
    pthread_mutex_unlock(&control_mutex);
    if(!start({next->options.fps_num,next->options.fps_den,next->options.codec,next->options.video_bitrate,next->options.audio_bitrate,next->options.output_width,next->options.output_height},true))return;
    queue_export_started=true;snprintf(queue_phase,sizeof(queue_phase),"rendering");
}
inline void queue_tick(){
    pthread_mutex_lock(&queue_owner_mutex);
    QueueRequest request{};pthread_mutex_lock(&control_mutex);request=queue_request;
    const bool priority_pause=queue_pause_pending;queue_pause_pending=false;pthread_mutex_unlock(&control_mutex);
    if(priority_pause){QueueRequest pause{};pause.kind=QueueCommandKind::pause;queue_process(pause);}
    pthread_mutex_lock(&control_mutex);queue_request.kind=QueueCommandKind::none;pthread_mutex_unlock(&control_mutex);
    if(request.kind!=QueueCommandKind::none)queue_process(request);
    pthread_mutex_lock(&control_mutex);const bool reset_clock=reset_watchdog_pending;pthread_mutex_unlock(&control_mutex);
    if(reset_clock)queue_replay().resume_clock(milliseconds());
    bool can_run=false;
    if(queue_replay_available&&!queue_blocked&&installed&&configured_valid){
        // Only original Unity callbacks inspect the router. Cold server menus
        // can read the last boolean without calling any managed method.
        if(fresh_scene_installed.load(std::memory_order_acquire))fresh_scene_available=fresh_scene_api.available(fresh_scene_api.context)
            &&queue_replay_available&&queue_replay().can_route();
        can_run=(!native_scene_required||native_scene_installed||fresh_scene_available)&&queue_replay().can_route();
    }
    pthread_mutex_lock(&control_mutex);queue_can_run=can_run;pthread_mutex_unlock(&control_mutex);
    queue_observe_selection();queue_execute();
    if(queue_available||request.kind!=QueueCommandKind::none)queue_publish();
    pthread_mutex_unlock(&queue_owner_mutex);
}
inline bool queue_command(int operation,const char* id,int position){
    if(operation<IDMP4_QUEUE_CANCEL||operation>IDMP4_QUEUE_MOVE||!queue_model::detail::hex(id,32)||position<0)return false;
    pthread_mutex_lock(&queue_owner_mutex);
    pthread_mutex_lock(&control_mutex);const bool available=queue_available&&!queue_blocked&&queue_request.kind==QueueCommandKind::none;pthread_mutex_unlock(&control_mutex);
    if(available&&strcmp(id,queue_active_id)){
        QueueRequest request{};request.kind=QueueCommandKind::mutate;request.operation=operation;request.position=position;memcpy(request.id,id,33);
        queue_process(request);queue_publish();pthread_mutex_unlock(&queue_owner_mutex);return true;
    }
    pthread_mutex_unlock(&queue_owner_mutex);
    return available&&queue_accept(QueueCommandKind::mutate,{},operation,id,position);
}
} // namespace idoly_mp4_runtime

extern "C" IDMP4_SESSION_API int IDMP4QueueConfigure(const char*r,const char*e){return idoly_mp4_runtime::queue_configure(r,e)?0:-1;}
extern "C" IDMP4_SESSION_API int IDMP4QueueEnqueue(uint32_t n,uint32_t d,uint32_t c,uint32_t v,uint32_t a){return idoly_mp4_runtime::queue_accept(idoly_mp4_runtime::QueueCommandKind::enqueue,{n,d,c,v,a})?0:-1;}
extern "C" IDMP4_SESSION_API int IDMP4QueueEnqueueV2(uint32_t n,uint32_t d,uint32_t c,uint32_t v,uint32_t a,uint32_t w,uint32_t h){return idoly_mp4_runtime::queue_accept(idoly_mp4_runtime::QueueCommandKind::enqueue,{n,d,c,v,a,w,h})?0:-1;}
extern "C" IDMP4_SESSION_API void IDMP4QueueInvalidateSelection(){idoly_mp4_runtime::invalidate_queue_selection();}
extern "C" IDMP4_SESSION_API int IDMP4QueueRun(){return idoly_mp4_runtime::queue_accept(idoly_mp4_runtime::QueueCommandKind::run)?0:-1;}
extern "C" IDMP4_SESSION_API int IDMP4QueuePause(){return idoly_mp4_runtime::queue_accept(idoly_mp4_runtime::QueueCommandKind::pause)?0:-1;}
extern "C" IDMP4_SESSION_API int IDMP4QueueResume(){return idoly_mp4_runtime::queue_accept(idoly_mp4_runtime::QueueCommandKind::resume)?0:-1;}
extern "C" IDMP4_SESSION_API int IDMP4QueueCommand(int o,const char*i,int p){return idoly_mp4_runtime::queue_command(o,i,p)?0:-1;}
extern "C" IDMP4_SESSION_API size_t IDMP4QueueStatus(char*b,size_t c){return idoly_mp4_runtime::queue_status(b,c);}
