"""Actual native queue/session/replay integration with fake Unity and codecs.

The Python audio broker and persistent journal execute unchanged. Original
router method callbacks are synthetic; this does not prove device rendering.
"""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from idoly_local.mp4_audio_broker import MP4AudioBroker
from test_mp4_audio_broker import make_store, eventually
from test_mp4_audio_bundle import NAME, bundle, masked
from test_mp4_session import PRELUDE, BASE, HARNESS

ROOT = Path(__file__).resolve().parents[1]
# Keep the independent session's actual broker/audio/codec boundary, replacing
# only its driver and the one-output observation-file naming convention.
SESSION = HARNESS.split("int main(int argc,char** argv){", 1)[0].replace(
    '(output_root+"/observed.pcm").c_str()', '(std::string(c->final_path)+".observed.pcm").c_str()')
QUEUE = r'''
namespace qm=idoly_mp4_queue;
namespace replay=idoly_mp4_replay;
Obj *router_scene=nullptr,*router_home=nullptr,*router_state=nullptr,*router_top=nullptr;
Obj *closing_presenter=nullptr,*closing_player=nullptr,*close_source=nullptr;
void* opening_param=nullptr;int close_ticks=0,open_ticks=0,opened=0,closed=0;
bool close_consumed=false,graphics_override=false;
qm::Graphics current_graphics{},effective_graphics{};
std::vector<float> applied_scales;std::vector<std::string> replayed_timelines,replayed_assets;
int reported_width=16;bool queue_source_valid=true;
unsigned selection_queries=0,selection_resumes=0;bool host_selection_only=false;
bool selection_type(void* value,const char* type){assert(!host_selection_only);++selection_queries;return istype(value,type);}
void selection_resume(void*,Method*){++selection_resumes;}
bool queue_source_geometry(void* controller,int32_t* width,int32_t* height){assert(!host_selection_only&&controller==ptr(camera_controller));++selection_queries;if(!queue_source_valid)return false;*width=16;*height=16;return true;}
template<class T>T get(void* p,size_t at){T value{};if(p)std::memcpy(&value,static_cast<uint8_t*>(p)+at,sizeof(value));return value;}
Obj* obj(void* p){return objects.at(p);}
void* rp_new(replay::Kind kind){switch(kind){case replay::Kind::out_game_param:return ptr(make("Solis.OutGame.OutGameLivePlayerParam"));case replay::Kind::actor_descriptor:return ptr(make("Solis.Common.SolisActorDescriptor"));case replay::Kind::transition_param:return ptr(make("Solis.OutGame.LivePlayerTransitionParam"));}return nullptr;}
void* rp_list(void* owner,const char* field){assert(!std::strcmp(field,"_assets"));auto* list=make("System.Collections.Generic.List`1");auto* backing=make("array");backing->array_kind=1;write(list,0x10,ptr(backing));write(list,0x18,int32_t(0));write(obj(owner),0x10,ptr(list));return ptr(list);}
bool rp_add(void* list,void* value){auto* backing=obj(get<void*>(list,0x10));backing->pointers.push_back(value);write(obj(list),0x18,static_cast<int32_t>(backing->pointers.size()));return true;}
bool rp_set_object(void* owner,const char* name,void* value){size_t at=0;if(!std::strcmp(name,"_assets"))at=0x10;else if(!std::strcmp(name,"_name")||!std::strcmp(name,"liveParam"))at=0x18;else if(!std::strcmp(name,"_gameObjects"))at=0x20;else return false;write(obj(owner),at,value);return true;}
bool rp_set_i32(void* owner,const char* name,int32_t value){size_t at=0;if(!std::strcmp(name,"stageMaxCapacity")||!std::strcmp(name,"_colliderType"))at=0x2c;else if(!std::strcmp(name,"_renderingLayerMaskBaseIndex"))at=0x34;else return false;write(obj(owner),at,value);return true;}
bool rp_set_bool(void* owner,const char* name,bool value){size_t at=0;if(!std::strcmp(name,"detachActorsOnPlayerDestroyed")||!std::strcmp(name,"_humanoid"))at=0x28;else if(!std::strcmp(name,"_colliderTrigger"))at=0x30;else if(!std::strcmp(name,"_autoBlinkDisabled"))at=0x31;else if(!std::strcmp(name,"_useADVSettings"))at=0x32;else if(!std::strcmp(name,"isDebugMode"))at=0x20;else return false;write(obj(owner),at,uint8_t(value));return true;}
void rp_param_ctor(void* param,void* stage,void* timeline,replay::Method*){write(obj(param),0x18,stage);write(obj(param),0x20,timeline);auto* list=make("System.Collections.Generic.List`1");auto* backing=make("array");backing->array_kind=1;write(list,0x10,ptr(backing));write(list,0x18,int32_t(0));write(obj(param),0x10,ptr(list));}
void rp_noop_ctor(void*,replay::Method*){}
void rp_param_actor(void* param,void* character,void* descriptor,int32_t audience,int32_t color,int32_t index,int32_t track,replay::Method*){auto* actor=make("SolisLiveActorParam");write(actor,0x10,character);write(actor,0x18,index);write(actor,0x1c,color);write(actor,0x20,track);write(actor,0x28,descriptor);write(actor,0x30,audience);assert(rp_add(get<void*>(param,0x10),ptr(actor)));}
void* make_selection(const char* label){void* param=rp_new(replay::Kind::out_game_param);std::string stage="stage_"+std::string(label),timeline="timeline_"+std::string(label),asset="body_"+std::string(label);rp_param_ctor(param,string_new(stage.c_str()),string_new(timeline.c_str()),nullptr);void* descriptor=rp_new(replay::Kind::actor_descriptor);void* assets=rp_list(descriptor,"_assets");rp_add(assets,string_new(asset.c_str()));rp_set_bool(descriptor,"_humanoid",true);rp_set_i32(descriptor,"_colliderType",1);rp_set_object(descriptor,"_name",string_new(label));rp_param_actor(param,string_new("rei"),descriptor,100,1,0,0,nullptr);return param;}
void select_param(void* param){connect_scene();router_top=presenter;write(player,0x70,uint8_t(1));session_core::observe_player_initializing(ptr(player),param);session_core::observe_presenter(ptr(presenter));session_core::observe_camera_controller(ptr(camera_controller));}
void* rp_scene(replay::Method*){return ptr(router_scene);}bool rp_busy(void*,replay::Method*){return open_ticks>0;}
void* rp_state(replay::Method*){return ptr(router_state);}void* rp_top(void*,replay::Method*){return ptr(router_top);}
void* rp_tree(void*,void* transition,replay::Method*){auto* tree=make("Qua.UI.WindowTree");write(tree,0x10,transition);return ptr(tree);}
void rp_open(void*,void* tree,void*,replay::Method*){assert(!open_ticks);void* transition=get<void*>(tree,0x10);opening_param=get<void*>(transition,0x18);assert(opening_param);open_ticks=4;++opened;}
replay::UniTask16 rp_end(void* old,replay::CancellationToken8,replay::Method*){assert(!close_ticks);closing_presenter=obj(old);closing_player=obj(get<void*>(old,0xe0));close_source=make("CloseTask");close_ticks=3;close_consumed=false;++closed;return {ptr(close_source),42};}
int32_t rp_task_status(replay::UniTask16* task,replay::Method*){assert(task->source==ptr(close_source)&&task->token_and_padding==42&&!close_consumed);return close_ticks?0:1;}
replay::UniTask16 rp_awaiter(replay::UniTask16* task,replay::Method*){return *task;}
void rp_result(replay::UniTask16* task,replay::Method*){assert(task->source==ptr(close_source)&&!close_consumed&&!close_ticks);close_consumed=true;router_top=router_home;objects.erase(ptr(closing_presenter));objects.erase(ptr(closing_player));}
bool rp_ready(void* value,replay::Method*){return alive(value)&&get<uint8_t>(value,0x70)!=0;}
replay::Api replay_api(){replay::Api a{};a.is_type=istype;a.alive=alive;a.retain=retain;a.retained=target;a.release=release;a.new_object=rp_new;a.new_string=string_new;a.new_field_list=rp_list;a.list_add=rp_add;a.set_object=rp_set_object;a.set_i32=rp_set_i32;a.set_bool=rp_set_bool;a.out_game_param_ctor=rp_param_ctor;a.actor_descriptor_ctor=rp_noop_ctor;a.transition_param_ctor=rp_noop_ctor;a.param_add_actor=rp_param_actor;a.scene_instance=rp_scene;a.scene_busy=rp_busy;a.live_state=rp_state;a.tree_with_param=rp_tree;a.open_tree=rp_open;a.top_screen=rp_top;a.presenter_end=rp_end;a.task_status=rp_task_status;a.task_get_awaiter=rp_awaiter;a.task_get_result=rp_result;a.player_ready=rp_ready;return a;}
bool queue_graphics_valid=true;
bool graphics_snapshot(qm::Graphics& out){if(!queue_graphics_valid)return false;out=current_graphics;return true;}
bool graphics_revision(int64_t& out){out=current_graphics.revision;return true;}
bool graphics_apply(const qm::Graphics* value){graphics_override=value!=nullptr;if(value){effective_graphics=*value;applied_scales.push_back(value->render_scale);}else effective_graphics=current_graphics;return true;}
int32_t pixel_width(void*,Method*){return reported_width;}int32_t pixel_height(void*,Method*){return 16;}
void pump(){
    if(close_ticks)--close_ticks;
    if(open_ticks&&!--open_ticks){
        void* param=opening_param;opening_param=nullptr;select_param(param);
        qm::Descriptor captured{};assert(session_core::selection.selected(ptr(player),captured)==Result::ok);
        replayed_timelines.push_back(captured.timeline_asset);replayed_assets.push_back(captured.actors[0].assets[0]);
    }
    if(router_top==presenter&&alive(ptr(presenter)))session_core::observe_presenter(ptr(presenter));
    session_core::on_unity_tick();
    if(session_core::job.stage==session_core::Stage::frame_wait&&!session_core::job.captured){auto* pass=make("VL.Rendering.VLCapturePass");auto* data=make("RenderingData");write(data,0x90,ptr(camera));write(data,0x158,uint8_t(1));session_core::capture_pass_did_execute(ptr(pass),ptr(data));session_core::camera_did_render(ptr(camera));}
}
void enqueue_current(){assert(IDMP4QueueEnqueue(30,1,1,16000000,192000)==0);pump();assert(!std::strcmp(session_core::queue_error,"none"));}
int main(int argc,char** argv){
    assert(argc==10);output_root=argv[4];scenario=argv[8];sample_rate=48000;fps=30;
    if(scenario=="cold") {
        qm::Queue seed;assert(seed.open(argv[9],idoly_mp4_game::android_original_sha256)==qm::Error::ok);
        qm::Descriptor descriptor{};std::snprintf(descriptor.stage_asset,sizeof(descriptor.stage_asset),"stage_A");std::snprintf(descriptor.timeline_asset,sizeof(descriptor.timeline_asset),"timeline_A");descriptor.actor_count=1;auto& actor=descriptor.actors[0];std::snprintf(actor.character_id,sizeof(actor.character_id),"rei");actor.asset_count=1;std::snprintf(actor.assets[0],sizeof(actor.assets[0]),"body_A");
        qm::Options options{};options.width=options.height=16;char first[33]{},second[33]{},claimed[33]{};
        assert(seed.enqueue(descriptor,options,first)==qm::Error::ok&&seed.enqueue(descriptor,options,second)==qm::Error::ok);
        assert(seed.claim_next(claimed)==qm::Error::ok&&!std::strcmp(first,claimed));const std::string recovered_output=seed.find(first)->output_id;seed.close();
        for(const char* suffix:{".pcm",".partial.mp4",".mp4"}){const std::string path=output_root+"/"+recovered_output+suffix;int fd=open(path.c_str(),O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW,0600);assert(fd>=0&&write(fd,"OWNED",5)==5);close(fd);}
        assert(!session_core::installed&&objects.empty());assert(IDMP4QueueConfigure(argv[9],argv[4])==0);
        assert(session_core::queue_store().find(first)->state==qm::State::interrupted);
        assert(access((output_root+"/"+recovered_output+".pcm").c_str(),F_OK)!=0&&access((output_root+"/"+recovered_output+".partial.mp4").c_str(),F_OK)!=0&&access((output_root+"/"+recovered_output+".mp4").c_str(),F_OK)==0);
        assert(IDMP4QueueRun()!=0&&IDMP4QueueResume()!=0);
        assert(IDMP4QueueCommand(IDMP4_QUEUE_RETRY,first,0)==0);
        assert(IDMP4QueueCommand(IDMP4_QUEUE_MOVE,second,0)==0);
        assert(IDMP4QueueCommand(IDMP4_QUEUE_CANCEL,first,0)==0);
        assert(IDMP4QueueCommand(IDMP4_QUEUE_REMOVE,first,0)==0);
        char status[16384]{};assert(IDMP4QueueStatus(status,sizeof(status)));
        assert(objects.empty()&&handles.empty()&&session_core::queue_store().count()==1);
        std::printf("{\"queue\":%s,\"recovered_interrupted\":true}\n",status);
        session_core::queue_store().close();if(session_core::queue_exports>=0)close(session_core::queue_exports);return 0;
    }
    router_scene=make("SceneSystem");router_home=make("HomeScreen");router_state=make("LiveState");
    connect_scene();Api selected=api();selected.director_get_duration=session_duration;selected.audio_clip_samples=session_samples;selected.audio_clip_frequency=session_rate;selected.timeline_get_tracks=session_tracks;selected.track_get_clips=session_clips;selected.bundle_load_file_async=session_load_bundle;selected.audio_clip_get_data=session_get_data;selected.bundle_unload=session_unload;selected.brain_manual_update=session_brain_update;selected.camera_clock_ok=session_camera_clock_ok;selected.camera_pixel_width=pixel_width;selected.camera_pixel_height=pixel_height;
    const bool selection_only=scenario.rfind("selection_only_",0)==0;
    if(scenario.rfind("capture_resume_",0)==0||selection_only)selected.source_geometry=queue_source_geometry;
    if(selection_only){selected.is_type=selection_type;selected.automatic_playback.director_resume=selection_resume;session_core::require_native_scene_pipeline();}
    session_core::install_game_api(selected,Layout{});
    session_core::install_queue_api(replay_api(),graphics_snapshot,graphics_apply,idoly_mp4_game::android_original_sha256,graphics_revision);
    assert(IDMP4SessionConfigure(argv[1],std::strtoull(argv[2],nullptr,10),argv[3],argv[4],1)==0);
    assert(IDMP4QueueConfigure(argv[9],argv[4])==0);
    // Paused/pending jobs are visible before any new original scene begins.
    char status[16384]{};assert(IDMP4QueueStatus(status,sizeof(status))&&std::strstr(status,"\"jobs\":[]"));
    if(selection_only){
        assert(session_core::installed&&session_core::native_scene_required&&!session_core::native_scene_installed);
        assert(IDMP4SessionSelectionReady()==0&&IDMP4SessionReady()==0);
        const bool observed=scenario!="selection_only_unobserved";
        const bool geometry=scenario!="selection_only_geometry_missing";
        if(observed)select_param(make_selection("A"));
        if(scenario=="selection_only_snapshot_failed")selected_duration=0;
        queue_source_valid=geometry;
        const double source_time=time_value;const int source_mode=mode;
        const float source_bgm=bgm_volume,source_voice=voice_volume,source_shader=shader;
        const int graph_before=graph_steps,actor_before=actor_steps,eval_before=evals,capture_before=raw_captures;
        // Execute the real idle observer. Offline admission is unavailable,
        // but a real initialized descriptor and original RT can be captured.
        for(int i=0;i<3;++i)pump();
        assert(session_core::unity_ticks==3&&IDMP4SessionReady()==0);
        assert((IDMP4SessionSelectionReady()==1)==observed);
        char native[8192]{};assert(IDMP4SessionStatus(native,sizeof native));
        assert(!session_core::busy_stage()&&!session_core::control_busy&&!session_core::start_pending);
        assert(graph_steps==graph_before&&actor_steps==actor_before&&evals==eval_before&&raw_captures==capture_before);
        assert(time_value==source_time&&mode==source_mode&&bgm_volume==source_bgm&&voice_volume==source_voice&&shader==source_shader);
        assert(selection_resumes==0&&!opened&&!closed&&!loads&&!data_calls&&!geometry_apply_calls);
        const unsigned queries_before=selection_queries;
        const uint64_t ticks_before=session_core::unity_ticks;
        // The server thread reads only cached recognition/options and commits
        // the real journal. A host Add must not resume or call back into Unity.
        host_selection_only=true;
        std::thread server([&]{
            assert(IDMP4QueueStatus(status,sizeof status));
            assert((std::strstr(status,"\"can_add\":true")!=nullptr)==(observed&&geometry));
            assert((IDMP4QueueEnqueue(60,1,2,32000000,192000)==0)==(observed&&geometry));
            assert(IDMP4QueueRun()!=0&&IDMP4QueueResume()!=0);
            assert(IDMP4SessionStart(60,1,2,32000000,192000)!=0);
            assert(IDMP4SessionStartV2(60,1,2,32000000,192000,2880,2160)!=0);
            assert(IDMP4SessionStatus(native,sizeof native)&&IDMP4QueueStatus(status,sizeof status));
            assert((IDMP4SessionSelectionReady()==1)==observed&&IDMP4SessionReady()==0);
        });server.join();host_selection_only=false;
        assert(selection_queries==queries_before&&session_core::unity_ticks==ticks_before&&selection_resumes==0);
        assert(!session_core::control_busy&&!session_core::start_pending&&!session_core::queue_running);
        assert(session_core::queue_request.kind==session_core::QueueCommandKind::none&&!opened&&!closed&&!loads&&!data_calls);
        assert(session_core::queue_store().count()==size_t(observed&&geometry));
        if(observed&&geometry){
            const auto* saved=session_core::queue_store().at(0);
            assert(!std::strcmp(saved->descriptor.timeline_asset,"timeline_A")&&!std::strcmp(saved->descriptor.actors[0].assets[0],"body_A"));
            assert(saved->options.width==16&&saved->options.height==16&&saved->options.fps_num==60&&saved->options.codec==2&&saved->options.video_bitrate==32000000);
        }
        std::printf("{\"queue\":%s,\"session\":%s,\"observed_ticks\":%llu,\"resume_calls\":%u,\"host_unity_calls\":%u}\n",status,native,static_cast<unsigned long long>(ticks_before),selection_resumes,selection_queries-queries_before);
        session_core::queue_replay().reset();session_core::selection.reset();session_core::game.reset_observations();assert(handles.empty());
        session_core::queue_store().close();if(session_core::queue_exports>=0)close(session_core::queue_exports);session_core::close_configuration(session_core::configured);return 0;
    }
    if(scenario.rfind("capture_resume_",0)==0){
        void* a=make_selection("A");select_param(a);
        if(scenario=="capture_resume_timeout")queue_source_valid=false;
        pump();
        char native[2048]{};assert(IDMP4SessionStatus(native,sizeof native));
        const int graph_before=graph_steps,actors_before=actor_steps,loads_before=loads,data_before=data_calls;const double time_before=time_value;
        IDMP4SessionSuspend(IDMP4_PAUSE_LIFECYCLE_BACKGROUND);queue_source_valid=false;
        // Mutate original input storage after the verified snapshot. Host Add
        // must use the captured values without waiting for another Unity tick.
        obj(get<void*>(a,0x20))->name="timeline_MUTATED";
        auto* original_actor=obj(obj(get<void*>(get<void*>(a,0x10),0x10))->pointers[0]);auto* original_descriptor=obj(get<void*>(ptr(original_actor),0x28));auto* original_assets=obj(get<void*>(get<void*>(ptr(original_descriptor),0x10),0x10));obj(original_assets->pointers[0])->name="body_MUTATED";
        if(scenario=="capture_resume_changed")select_param(make_selection("B"));
        if(scenario=="capture_resume_graphics_timeout")++current_graphics.revision;
        if(scenario=="capture_resume_graphics_restore")queue_graphics_valid=false;
        const bool accepted=scenario=="capture_resume_restore"||scenario=="capture_resume_graphics_restore";
        assert((IDMP4QueueEnqueue(60,1,2,32000000,192000)==0)==accepted);
        assert(session_core::queue_request.kind==session_core::QueueCommandKind::none);
        assert(graph_steps==graph_before&&actor_steps==actors_before&&loads==loads_before&&data_calls==data_before&&time_value==time_before);
        if(accepted){
            assert(session_core::queue_store().count()==1);const auto* saved=session_core::queue_store().at(0);
            assert(!std::strcmp(saved->descriptor.timeline_asset,"timeline_A")&&!std::strcmp(saved->descriptor.actors[0].assets[0],"body_A"));
            assert(saved->options.fps_num==60&&saved->options.fps_den==1&&saved->options.codec==2&&saved->options.video_bitrate==32000000&&saved->options.audio_bitrate==192000);
        }else assert(session_core::queue_store().count()==0);
        queue_source_valid=queue_graphics_valid=true;IDMP4SessionResume();pump();
        assert(IDMP4QueueStatus(status,sizeof status)&&IDMP4SessionStatus(native,sizeof native));
        std::printf("{\"queue\":%s,\"session\":%s,\"waiting_ticks\":0}\n",status,native);
        session_core::queue_replay().reset();session_core::selection.reset();session_core::game.reset_observations();assert(handles.empty());session_core::queue_store().close();if(session_core::queue_exports>=0)close(session_core::queue_exports);session_core::close_configuration(session_core::configured);return 0;
    }
    void* a=make_selection("A");select_param(a);current_graphics.render_scale=1.0f;current_graphics.quality=30;
    reported_width=scenario=="geometry"?32:16;pump();enqueue_current();std::string first=session_core::queue_last_added;
    obj(get<void*>(a,0x20))->name="timeline_MUTATED";
    void* b=make_selection("B");select_param(b);current_graphics.render_scale=1.5f;current_graphics.quality=40;reported_width=16;pump();enqueue_current();std::string second=session_core::queue_last_added;
    auto* bactor=obj(obj(get<void*>(get<void*>(b,0x10),0x10))->pointers[0]);auto* bd=obj(get<void*>(ptr(bactor),0x28));auto* bassets=obj(get<void*>(get<void*>(ptr(bd),0x10),0x10));obj(bassets->pointers[0])->name="body_MUTATED";
    void* c=make_selection("C");select_param(c);current_graphics.render_scale=.75f;current_graphics.quality=20;pump();
    assert(IDMP4QueueRun()==0);assert(IDMP4SessionStart(30,1,1,16000000,192000)!=0);
    if(scenario=="priority_pause"){
        // A host server-stop pause arrives before the queued Run's first Unity
        // tick. It must win without waiting for the occupied command slot.
        assert(IDMP4QueuePause()==0);
        assert(session_core::requested_pause_reason==IDMP4_PAUSE_USER&&session_core::queue_pause_pending);
        assert(session_core::queue_request.kind==session_core::QueueCommandKind::none);
        char pending_status[16384]{};assert(IDMP4QueueStatus(pending_status,sizeof pending_status));
        assert(std::strstr(pending_status,"\"command_pending\":true"));
        for(int i=0;i<4;++i)pump();
        assert(session_core::queue_paused&&!session_core::queue_running&&!opened&&!session_core::queue_active_id[0]);
        assert(session_core::queue_store().count()==2&&session_core::queue_store().at(0)->state==qm::State::pending);
        char status[16384]{};assert(IDMP4QueueStatus(status,sizeof status));
        std::printf("{\"queue\":%s,\"priority_pause\":true}\n",status);
        session_core::queue_replay().reset();session_core::selection.reset();session_core::game.reset_observations();assert(handles.empty());
        session_core::queue_store().close();if(session_core::queue_exports>=0)close(session_core::queue_exports);session_core::close_configuration(session_core::configured);return 0;
    }
    bool cancelled=false,paused=false,resumed=false,ownership_checked=false,storage_fault_verified=false;unsigned parked=0;int opening_at_cancel=0;
    if(scenario=="cancel_before_begin"||scenario=="session_cancel_before_begin"){
        // Queue starts its native session on one tick; cancellation happens
        // before begin_job can acquire any resources on the following tick.
        session_core::queue_tick();
    }
    uint64_t deadline=session_core::milliseconds()+15000;
    do {
        if(scenario=="cancel_before_begin"||scenario=="session_cancel_before_begin")session_core::queue_tick();
        if((scenario=="cancel_before_begin"||scenario=="session_cancel_before_begin")&&!cancelled&&session_core::start_pending&&second==session_core::queue_active_id){
            if(scenario=="session_cancel_before_begin")IDMP4SessionCancel();else assert(IDMP4QueueCommand(IDMP4_QUEUE_CANCEL,second.c_str(),0)==0);cancelled=true;
        }
        pump();
        if(!ownership_checked&&open_ticks){assert(IDMP4SessionStart(30,1,1,16000000,192000)!=0);ownership_checked=true;}
        if(scenario=="resume_opening"&&!paused&&open_ticks){assert(IDMP4QueuePause()==0);paused=true;}
        if(scenario=="cancel_opening"&&!cancelled&&open_ticks){opening_at_cancel=opened;assert(IDMP4QueueCommand(IDMP4_QUEUE_CANCEL,first.c_str(),0)==0);cancelled=true;}
        if((scenario=="pause"||scenario=="storage_fault")&&!paused&&session_core::job.stage==session_core::Stage::frame_wait){assert(IDMP4QueuePause()==0);paused=true;}
        if(paused&&!resumed&&session_core::queue_paused){
            const uint64_t frame=session_core::job.frame;const int opens=opened;
            if(scenario=="storage_fault"){
                const std::string journal=std::string(argv[9])+"/queue-v1.bin",backup=journal+".old";
                assert(rename(journal.c_str(),backup.c_str())==0);
                std::ifstream input(backup,std::ios::binary);std::ofstream replacement(journal,std::ios::binary);replacement<<input.rdbuf();replacement.close();input.close();assert(chmod(journal.c_str(),0600)==0);
                assert(IDMP4QueueResume()==0);pump();
                assert(session_core::queue_blocked&&session_core::queue_paused&&session_core::requested_pause_reason==IDMP4_PAUSE_USER);
                assert(!std::strcmp(session_core::queue_error,"queue_storage_changed"));
                assert(IDMP4QueueRun()!=0&&IDMP4QueueResume()!=0&&IDMP4QueueCommand(IDMP4_QUEUE_CANCEL,second.c_str(),0)!=0);
                for(int i=0;i<5;++i){pump();assert(session_core::job.frame==frame&&opened==opens&&!std::strcmp(session_core::queue_error,"queue_storage_changed"));}
                IDMP4SessionCancel();for(int i=0;i<100&&(session_core::control_busy||session_core::busy_stage());++i)pump();
                assert(!session_core::control_busy&&!session_core::busy_stage());pump();storage_fault_verified=true;break;
            }
            if(scenario=="resume_opening"){
                assert(open_ticks&&IDMP4QueueResume()==0);resumed=true;
            }else{
                const uint64_t generation=session_core::queue_store().generation();assert(IDMP4QueuePause()==0);pump();assert(session_core::queue_store().generation()==generation&&!std::strcmp(session_core::queue_error,"none"));
                for(int i=0;i<5;++i){pump();assert(session_core::job.frame==frame&&opened==opens&&session_core::queue_paused);++parked;}
                assert(IDMP4QueueResume()==0);resumed=true;
            }
        }
        timespec sleep{0,1000000};nanosleep(&sleep,nullptr);
        if(session_core::milliseconds()>deadline){std::fprintf(stderr,"Queue timeout phase=%s error=%s replay=%d active=%s\n",session_core::queue_phase,session_core::queue_error,int(session_core::queue_replay().phase()),session_core::queue_active_id);return 3;}
    }while(session_core::queue_running||session_core::queue_active_id[0]||session_core::control_busy||session_core::busy_stage()||session_core::queue_request.kind!=session_core::QueueCommandKind::none);
    if(scenario=="remove_completed"||scenario=="remove_journal_fault"||scenario=="remove_symlink"){
        const auto* completed=session_core::queue_store().find(first.c_str());assert(completed&&completed->state==qm::State::completed);
        const std::string final_path=output_root+"/"+completed->output_id+".mp4";assert(access(final_path.c_str(),F_OK)==0);
        assert(IDMP4QueueCommand(IDMP4_QUEUE_REMOVE,first.c_str(),0)==0);
        assert(!std::strcmp(session_core::queue_error,"completed_delete_confirmation_required")&&session_core::queue_store().count()==2&&access(final_path.c_str(),F_OK)==0);
        if(scenario=="remove_journal_fault"){
            const std::string journal=std::string(argv[9])+"/queue-v1.bin",backup=journal+".old";assert(rename(journal.c_str(),backup.c_str())==0);std::ifstream input(backup,std::ios::binary);std::ofstream replacement(journal,std::ios::binary);replacement<<input.rdbuf();replacement.close();input.close();assert(chmod(journal.c_str(),0600)==0);
        }else if(scenario=="remove_symlink"){
            const std::string original=final_path+".original";assert(rename(final_path.c_str(),original.c_str())==0&&symlink(original.c_str(),final_path.c_str())==0);
        }
        assert(IDMP4QueueCommand(IDMP4_QUEUE_REMOVE,first.c_str(),1)==0);
        if(scenario=="remove_completed")assert(session_core::queue_store().count()==1&&access(final_path.c_str(),F_OK)!=0);
        else {assert(session_core::queue_store().count()==2&&access(final_path.c_str(),F_OK)==0);assert(!std::strcmp(session_core::queue_error,scenario=="remove_symlink"?"queue_final_cleanup_deferred":"queue_storage_changed"));}
    }
    assert(IDMP4QueueStatus(status,sizeof(status)));
    if(scenario!="storage_fault"){
    std::vector<qm::Job> expected_jobs;for(size_t i=0;i<session_core::queue_store().count();++i)expected_jobs.push_back(*session_core::queue_store().at(i));session_core::queue_store().close();
    qm::Queue persisted;const auto persisted_result=persisted.open(argv[9],idoly_mp4_game::android_original_sha256);if(persisted_result!=qm::Error::ok)std::fprintf(stderr,"Persisted journal read failed: %s\n",qm::error_code(persisted_result));assert(persisted_result==qm::Error::ok);
    assert(persisted.count()==expected_jobs.size());
    for(size_t i=0;i<persisted.count();++i){const auto* disk=persisted.at(i);const auto& live=expected_jobs[i];assert(disk->state==live.state&&!std::strcmp(disk->id,live.id)&&!std::strcmp(disk->output_id,live.output_id));}
    persisted.close();}
    assert(!graphics_override&&effective_graphics.render_scale==.75f&&effective_graphics.quality==20);
    if(scenario=="pause")assert(paused&&resumed&&parked==5);
    if(scenario=="resume_opening")assert(paused&&resumed);
    if(scenario=="storage_fault")assert(storage_fault_verified&&opened==1);
    if(scenario=="cancel_opening")assert(cancelled&&opening_at_cancel==1);
    std::printf("{\"queue\":%s,\"opened\":%d,\"closed\":%d,\"loads\":%d,\"scales\":[",status,opened,closed,loads);
    for(size_t i=0;i<applied_scales.size();++i){std::printf("%s%g",i?",":"",applied_scales[i]);}std::printf("],\"timelines\":[");
    for(size_t i=0;i<replayed_timelines.size();++i){std::printf("%s\"%s\"",i?",":"",replayed_timelines[i].c_str());}std::printf("],\"assets\":[");
    for(size_t i=0;i<replayed_assets.size();++i){std::printf("%s\"%s\"",i?",":"",replayed_assets[i].c_str());}std::puts("]}");
    session_core::queue_replay().reset();session_core::selection.reset();session_core::game.reset_observations();assert(handles.empty());session_core::queue_store().close();if(session_core::queue_exports>=0)close(session_core::queue_exports);session_core::close_configuration(session_core::configured);
}
'''


@pytest.fixture(scope="module")
def queue_executable(tmp_path_factory):
    compiler = shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        pytest.skip("C++ compiler unavailable")
    root = tmp_path_factory.mktemp("mp4-queue-host")
    source, binary = root / "queue.cpp", root / "queue"
    source.write_text(PRELUDE + BASE + SESSION + QUEUE)
    result = subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-pthread",
        "-I", str(ROOT / "client-presentation/native"), str(source), "-o", str(binary)],
        capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    return binary


@pytest.fixture
def run_queue(tmp_path, queue_executable):
    resources = []
    def run(scenario="fifo"):
        body = masked(bundle(platform=13, audio_values={"frequency":48000,"length":2.0}), NAME)
        store, cache, record, calls, original = make_store(tmp_path, body, platform="android")
        broker = MP4AudioBroker(store, tmp_path)
        resources.append((broker, store, cache))
        config = broker.configuration()
        journal = tmp_path / "queue-journal"
        journal.mkdir(mode=0o700)
        result = subprocess.run([str(queue_executable), config["directory"], str(config["epoch"]),
            config["capability"], config["export_directory"], "1", "48000", "30", scenario, str(journal)],
            capture_output=True, text=True, timeout=20)
        assert result.returncode == 0, result.stderr
        output = json.loads(result.stdout)
        output["exports"] = Path(config["export_directory"])
        output["journal"] = journal
        output["broker"] = broker
        return output
    yield run
    for broker, store, cache in resources:
        broker.close(); store.close(); cache.close()
        eventually(lambda broker=broker: not broker._fds)


def test_fifo_uses_frozen_mv_outfits_and_graphics(run_queue):
    result = run_queue()
    assert [job["state"] for job in result["queue"]["jobs"]] == ["completed", "completed"]
    assert result["timelines"] == ["timeline_A", "timeline_B"]
    assert result["assets"] == ["body_A", "body_B"]
    assert result["scales"] == [1, 1.5]
    assert result["opened"] == result["closed"] == 2
    assert len(list(result["exports"].glob("*.mp4"))) == 2
    assert len({job["output_id"] for job in result["queue"]["jobs"]}) == 2


def test_user_pause_preserves_current_job_and_fifo(run_queue):
    result = run_queue("pause")
    assert [job["state"] for job in result["queue"]["jobs"]] == ["completed", "completed"]
    assert result["timelines"] == ["timeline_A", "timeline_B"]


def test_changed_geometry_fails_without_publishing_wrong_sized_video(run_queue):
    result = run_queue("geometry")
    jobs = result["queue"]["jobs"]
    assert jobs[0]["state"] == "failed" and jobs[0]["error_code"] == "queued_capture_geometry_changed"
    assert not (result["exports"] / (jobs[0]["output_id"] + ".mp4")).exists()


def test_cancel_while_original_screen_is_opening_settles_before_next_job(run_queue):
    result = run_queue("cancel_opening")
    assert [job["state"] for job in result["queue"]["jobs"]] == ["cancelled", "completed"]
    assert result["timelines"] == ["timeline_A", "timeline_B"]
    assert len(list(result["exports"].glob("*.mp4"))) == 1


def test_cancel_parked_start_is_not_recorded_as_previous_completion(run_queue):
    result = run_queue("cancel_before_begin")
    assert [job["state"] for job in result["queue"]["jobs"]] == ["completed", "cancelled"]
    assert len(list(result["exports"].glob("*.mp4"))) == 1


def test_cold_menu_recovers_and_mutates_journal_without_managed_calls(run_queue):
    result = run_queue("cold")
    assert result["recovered_interrupted"] is True
    assert result["queue"]["can_run"] is False
    assert result["queue"]["command_pending"] is False
    assert [job["state"] for job in result["queue"]["jobs"]] == ["pending"]


def test_resume_while_original_router_is_busy_preserves_owned_attempt(run_queue):
    result = run_queue("resume_opening")
    assert [job["state"] for job in result["queue"]["jobs"]] == ["completed", "completed"]


def test_changed_journal_inode_blocks_resume_and_further_dispatch(run_queue):
    result = run_queue("storage_fault")
    assert result["queue"]["error_code"] == "queue_storage_changed"
    assert result["opened"] == 1
    assert [job["state"] for job in result["queue"]["jobs"]] == ["paused", "pending"]
    assert not list(result["exports"].glob("*.mp4"))


def test_direct_session_cancel_of_parked_queue_start_preserves_job_identity(run_queue):
    result = run_queue("session_cancel_before_begin")
    assert [job["state"] for job in result["queue"]["jobs"]] == ["completed", "cancelled"]
    assert len(list(result["exports"].glob("*.mp4"))) == 1


def test_completed_output_requires_confirmation_then_removes_record_and_video(run_queue):
    result = run_queue("remove_completed")
    assert [job["state"] for job in result["queue"]["jobs"]] == ["completed"]
    assert len(list(result["exports"].glob("*.mp4"))) == 1


def test_completed_remove_preserves_video_when_journal_commit_fails(run_queue):
    result = run_queue("remove_journal_fault")
    assert result["queue"]["error_code"] == "queue_storage_changed"
    assert len(result["queue"]["jobs"]) == len(list(result["exports"].glob("*.mp4"))) == 2


def test_completed_remove_rejects_symlink_without_removing_record(run_queue):
    result = run_queue("remove_symlink")
    assert result["queue"]["error_code"] == "queue_final_cleanup_deferred"
    assert len(result["queue"]["jobs"]) == 2
    assert sum(path.is_symlink() for path in result["exports"].glob("*.mp4")) == 1


def test_paused_enqueue_persists_without_unity_resume_and_preserves_selection_options(run_queue):
    result = run_queue("capture_resume_restore")
    assert result["waiting_ticks"] == 0
    assert result["queue"]["command_pending"] is False
    assert result["queue"]["error_code"] == "none"
    assert [(job["timeline"], job["fps_num"], job["video_codec"]) for job in result["queue"]["jobs"]] == [("timeline_A", 60, 2)]
    assert result["session"]["ready"] is True


@pytest.mark.parametrize("scenario,error", [("changed", "selected_mv_selection_changed"), ("timeout", "selected_mv_snapshot_missing"), ("graphics_timeout", "selected_graphics_changed_before_enqueue")])
def test_paused_enqueue_rejects_changed_or_unverified_snapshot_without_waiting(run_queue, scenario, error):
    result = run_queue("capture_resume_" + scenario)
    assert result["queue"]["jobs"] == []
    assert result["queue"]["command_pending"] is False
    assert result["queue"]["error_code"] == error


def test_paused_mv_uses_frozen_effective_graphics_without_managed_snapshot_calls(run_queue):
    result = run_queue("capture_resume_graphics_restore")
    assert result["queue"]["command_pending"] is False
    assert result["queue"]["error_code"] == "none"
    assert len(result["queue"]["jobs"]) == 1
    assert result["session"]["ready"] is True


def test_host_pause_wins_over_pending_run_before_unity_tick(run_queue):
    result = run_queue("priority_pause")
    assert result["priority_pause"] is True
    assert result["queue"]["paused"] is True
    assert result["queue"]["running"] is False
    assert result["queue"]["command_pending"] is False
    assert [job["state"] for job in result["queue"]["jobs"]] == ["pending", "pending"]


@pytest.mark.parametrize("scenario,readiness_error", [
    ("native_unbound", "offline_pipeline_not_verified"),
    ("snapshot_failed", "unsupported_selected_duration"),
])
def test_readonly_selection_and_host_add_survive_unbound_offline_pipeline(run_queue, scenario, readiness_error):
    result = run_queue("selection_only_" + scenario)
    assert result["observed_ticks"] == 3
    assert result["resume_calls"] == result["host_unity_calls"] == 0
    assert result["session"]["selected_mv"] is True
    assert result["session"]["selection_error"] == "none"
    assert result["session"]["ready"] is False
    assert result["session"]["readiness_error"] == readiness_error
    assert result["session"]["source_width"] == result["session"]["source_height"] == 16
    assert result["queue"]["can_add"] is True
    assert result["queue"]["can_run"] is False
    assert result["queue"]["command_pending"] is False
    assert [(job["timeline"], job["state"]) for job in result["queue"]["jobs"]] == [("timeline_A", "pending")]


@pytest.mark.parametrize("scenario,selected,error", [
    ("geometry_missing", True, "selected_capture_geometry_not_ready"),
    ("unobserved", False, "selected_mv_snapshot_missing"),
])
def test_readonly_selection_does_not_fabricate_add_geometry_or_initialization(run_queue, scenario, selected, error):
    result = run_queue("selection_only_" + scenario)
    assert result["session"]["selected_mv"] is selected
    assert result["session"]["ready"] is False
    assert result["queue"]["can_add"] is False
    assert result["queue"]["add_error"] == error
    assert result["queue"]["can_run"] is False
    assert result["queue"]["jobs"] == []
    assert result["resume_calls"] == result["host_unity_calls"] == 0
