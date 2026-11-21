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
struct QueueOwners { queue_model::Queue store{};replay_model::Replay replay{}; };
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
static bool queue_available=false,queue_running=false,queue_paused=false,queue_replay_available=false,
    queue_export_started=false,queue_cancel_requested=false,queue_clock_was_paused=false;
static bool queue_active_published=false;
static bool queue_can_run=false,queue_blocked=false;
static int queue_exports=-1;
static char queue_root[path_capacity]{},queue_export_root[path_capacity]{},queue_active_id[33]{},queue_last_added[33]{};
static char queue_error[65]="none",queue_phase[32]="idle";
static char queue_published[16384]="{\"schema\":1,\"available\":false,\"command_pending\":false,\"error_code\":\"queue_not_configured\",\"last_added_job_id\":\"\",\"running\":false,\"paused\":false,\"phase\":\"idle\",\"capacity\":8,\"jobs\":[]}";
static queue_model::Descriptor queue_descriptor_work;
static bool (*queue_graphics_snapshot)(queue_model::Graphics&)=nullptr;
static bool (*queue_graphics_apply)(const queue_model::Graphics*)=nullptr;
#ifdef IDOLY_DARWIN_BRIDGE
static const char* queue_profile_sha=idoly_mp4_game::ios_original_sha256;
#else
static const char* queue_profile_sha=idoly_mp4_game::android_original_sha256;
#endif
inline void queue_process(const QueueRequest& request);

inline void queue_observe_selection(){
    void* player=game.selected_player();
    if(player&&selection.selected(player,queue_descriptor_work)==Result::ok)
        queue_replay().observe(game.selected_presenter(),player,queue_descriptor_work);
}
inline void install_queue_api(const replay_model::Api& api,bool(*snapshot)(queue_model::Graphics&),
    bool(*apply)(const queue_model::Graphics*),const char* profile){
    pthread_mutex_lock(&queue_owner_mutex);
    if(queue_active_id[0]){pthread_mutex_unlock(&queue_owner_mutex);return;}
    queue_replay_available=queue_replay().set_api(api);queue_graphics_snapshot=snapshot;queue_graphics_apply=apply;queue_profile_sha=profile;
    pthread_mutex_unlock(&queue_owner_mutex);
}
inline void queue_set_error(const char* value){snprintf(queue_error,sizeof(queue_error),"%s",value?value:"queue_failed");}
inline void queue_publish(){
    char next[16384]{};size_t at=0;
    auto append=[&](const char* format,auto... values){if(at>=sizeof(next))return;const int n=snprintf(next+at,sizeof(next)-at,format,values...);if(n<0||static_cast<size_t>(n)>=sizeof(next)-at){at=sizeof(next);return;}at+=static_cast<size_t>(n);};
    pthread_mutex_lock(&control_mutex);const bool command_pending=queue_request.kind!=QueueCommandKind::none;pthread_mutex_unlock(&control_mutex);
    append("{\"schema\":1,\"available\":%s,\"command_pending\":%s,\"error_code\":\"%s\",\"last_added_job_id\":\"%s\",\"running\":%s,\"paused\":%s,\"phase\":\"%s\",\"capacity\":8,\"current_job_id\":\"%s\",\"replay_available\":%s,\"can_run\":%s,\"jobs\":[",
        queue_available?"true":"false",command_pending?"true":"false",queue_error,queue_last_added,
        queue_running?"true":"false",queue_paused?"true":"false",queue_phase,queue_active_id,queue_replay_available?"true":"false",queue_can_run?"true":"false");
    for(size_t i=0;i<queue_store().count();++i){const auto* queued=queue_store().at(i);if(!queued)continue;
        append("%s{\"job_id\":\"%s\",\"output_id\":\"%s\",\"timeline\":\"%s\",\"actor_count\":%u,\"width\":%u,\"height\":%u,\"fps_num\":%u,\"video_codec\":%u,\"state\":\"%s\",\"error_code\":\"%s\"}",
            i?",":"",queued->id,queued->output_id,queued->descriptor.timeline_asset,queued->descriptor.actor_count,
            queued->options.width,queued->options.height,queued->options.fps_num,queued->options.codec,
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
    QueueRequest request{};request.kind=QueueCommandKind::configure;
    snprintf(request.root,sizeof(request.root),"%s",root);snprintf(request.exports,sizeof(request.exports),"%s",exports);
    // Journal inspection/recovery needs no Unity object or graphics API. The
    // host can populate its cold server menu before starting the game engine.
    queue_process(request);queue_publish();const bool ok=queue_available&&(!strcmp(queue_error,"none")||!strcmp(queue_error,"queue_temporary_cleanup_deferred"));
    pthread_mutex_unlock(&queue_owner_mutex);return ok;
}
inline bool queue_accept(QueueCommandKind kind,Options options={},int operation=0,const char* id=nullptr,int position=0){
    if(kind==QueueCommandKind::enqueue&&!valid_options(options))return false;
    if(kind==QueueCommandKind::mutate&&(operation<IDMP4_QUEUE_CANCEL||operation>IDMP4_QUEUE_MOVE||!queue_model::detail::hex(id,32)||position<0))return false;
    pthread_mutex_lock(&control_mutex);
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
    pthread_mutex_lock(&control_mutex);
    const size_t n=strlen(queue_published);const bool pending=queue_request.kind!=QueueCommandKind::none;
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
    queue_running=false;pthread_mutex_lock(&control_mutex);queue_blocked=true;pthread_mutex_unlock(&control_mutex);queue_set_error(queue_model::error_code(result));
    snprintf(queue_phase,sizeof(queue_phase),"failed");return false;
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
        if(result!=queue_model::Error::ok){close(exports);pthread_mutex_lock(&control_mutex);queue_available=false;pthread_mutex_unlock(&control_mutex);queue_set_error(queue_model::error_code(result));return;}
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
        void* player=game.selected_player();
        if(!request.selection_identity||request.selection_identity!=selection.identity(player)){queue_set_error("selection_changed_before_enqueue");return;}
        if(selection.selected(player,queue_descriptor_work)!=Result::ok){queue_set_error(selection.error());return;}
        int32_t width=0,height=0;if(game.source_geometry(width,height)!=Result::ok){queue_set_error("selected_capture_geometry_unsupported");return;}
        queue_model::Options options{};options.fps_num=request.options.fps_num;options.fps_den=request.options.fps_den;options.codec=request.options.codec;
        options.video_bitrate=request.options.bitrate;options.audio_bitrate=request.options.audio_bitrate;options.width=static_cast<uint32_t>(width);options.height=static_cast<uint32_t>(height);
        if(!queue_graphics_snapshot||!queue_graphics_snapshot(options.graphics)){queue_set_error("selected_graphics_unavailable");return;}
        const auto result=queue_store().enqueue(queue_descriptor_work,options,queue_last_added);
        if(result!=queue_model::Error::ok)queue_set_error(queue_model::error_code(result));
        return;
    }
    if(request.kind==QueueCommandKind::run||request.kind==QueueCommandKind::resume){
        if(!queue_replay_available){queue_set_error("replay_api_unavailable");return;}
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
        if(result!=queue_model::Error::ok){idoly_mp4_queue_cleanup::discard_final(completed_output);queue_set_error(queue_model::error_code(result));}
        else if(request.operation==IDMP4_QUEUE_REMOVE&&request.position==1
            &&idoly_mp4_queue_cleanup::remove_final(queue_exports,completed_output)!=idoly_mp4_queue_cleanup::Result::ok)
            queue_set_error("queue_final_cleanup_deferred");
    }
}
inline void queue_release_attempt(){
    if(queue_graphics_apply)queue_graphics_apply(nullptr);
    queue_replay().reset();queue_active_id[0]=0;queue_export_started=queue_cancel_requested=false;
}
inline void queue_execute(){
    pthread_mutex_lock(&control_mutex);const bool suspended=requested_pause_reason!=IDMP4_PAUSE_NONE,session_busy=control_busy;pthread_mutex_unlock(&control_mutex);
    // Cancellation/codec retirement may settle while paused; starting a new
    // original screen or advancing an export remains gated below.
    if(queue_blocked){if(!busy_stage()&&!session_busy&&queue_graphics_apply)queue_graphics_apply(nullptr);return;}
    if(queue_cancel_requested&&queue_active_id[0]&&!queue_export_started){
        queue_replay().tick(milliseconds());
        if(queue_replay().active()){snprintf(queue_phase,sizeof(queue_phase),"cancelling");return;}
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
        const auto result=queue_store().claim_next(queue_active_id);
        if(result==queue_model::Error::not_found){queue_running=false;snprintf(queue_phase,sizeof(queue_phase),"completed");return;}
        if(result!=queue_model::Error::ok){queue_running=false;queue_set_error(queue_model::error_code(result));return;}
        const auto* next=queue_store().find(queue_active_id);
        if(!next||!queue_graphics_apply||!queue_graphics_apply(&next->options.graphics)||!queue_replay().begin(next->descriptor,milliseconds())){
            if(!queue_record(queue_store().fail(queue_active_id,"queued_mv_prepare_failed")))return;
            queue_release_attempt();queue_running=false;queue_set_error("queued_mv_prepare_failed");return;
        }
    }
    queue_observe_selection();queue_replay().tick(milliseconds());
    if(queue_replay().phase()==replay_model::Phase::failed){if(!queue_record(queue_store().fail(queue_active_id,queue_replay().error())))return;queue_set_error(queue_replay().error());queue_release_attempt();queue_running=false;return;}
    if(queue_replay().phase()!=replay_model::Phase::ready){snprintf(queue_phase,sizeof(queue_phase),"replaying");return;}
    if(game.selected_player()!=queue_replay().player()){snprintf(queue_phase,sizeof(queue_phase),"waiting_for_scene");return;}
    Snapshot ready{};if(game.snapshot(ready)!=Result::ok){snprintf(queue_phase,sizeof(queue_phase),"waiting_for_scene");return;}
    const auto* next=queue_store().find(queue_active_id);if(!next){queue_set_error("job_not_found");queue_running=false;queue_release_attempt();return;}
    pthread_mutex_lock(&control_mutex);
    snprintf(pending_queue_output,sizeof(pending_queue_output),"%s",next->output_id);
    snprintf(pending_queue_exports,sizeof(pending_queue_exports),"%s",queue_export_root);
    pending_queue_exports_fd=queue_exports;pending_queue_width=next->options.width;pending_queue_height=next->options.height;
    pthread_mutex_unlock(&control_mutex);
    if(!start({next->options.fps_num,next->options.fps_den,next->options.codec,next->options.video_bitrate,next->options.audio_bitrate},true))return;
    queue_export_started=true;snprintf(queue_phase,sizeof(queue_phase),"rendering");
}
inline void queue_tick(){
    pthread_mutex_lock(&queue_owner_mutex);
    QueueRequest request{};pthread_mutex_lock(&control_mutex);request=queue_request;queue_request.kind=QueueCommandKind::none;pthread_mutex_unlock(&control_mutex);
    if(request.kind!=QueueCommandKind::none)queue_process(request);
    pthread_mutex_lock(&control_mutex);const bool reset_clock=reset_watchdog_pending;pthread_mutex_unlock(&control_mutex);
    if(reset_clock)queue_replay().resume_clock(milliseconds());
    bool can_run=false;
    if(queue_replay_available&&!queue_blocked&&installed&&configured_valid){
        // Only original Unity callbacks inspect the router. Cold server menus
        // can read the last boolean without calling any managed method.
        can_run=queue_replay().can_route();
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
extern "C" IDMP4_SESSION_API int IDMP4QueueRun(){return idoly_mp4_runtime::queue_accept(idoly_mp4_runtime::QueueCommandKind::run)?0:-1;}
extern "C" IDMP4_SESSION_API int IDMP4QueuePause(){return idoly_mp4_runtime::queue_accept(idoly_mp4_runtime::QueueCommandKind::pause)?0:-1;}
extern "C" IDMP4_SESSION_API int IDMP4QueueResume(){return idoly_mp4_runtime::queue_accept(idoly_mp4_runtime::QueueCommandKind::resume)?0:-1;}
extern "C" IDMP4_SESSION_API int IDMP4QueueCommand(int o,const char*i,int p){return idoly_mp4_runtime::queue_command(o,i,p)?0:-1;}
extern "C" IDMP4_SESSION_API size_t IDMP4QueueStatus(char*b,size_t c){return idoly_mp4_runtime::queue_status(b,c);}
