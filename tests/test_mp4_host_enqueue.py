"""Commit frozen queue selections from a host thread without resuming Unity.

The journal, session and selection code are production headers. Every original
Unity/replay callback is synthetic and traps if invoked in the host-only phase.
No rendered MP4 or device execution is established by this fixture.
"""
import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from test_mp4_queue_runtime import PRELUDE, BASE, SESSION, QUEUE

ROOT = Path(__file__).resolve().parents[1]

HOST_PRELUDE = r'''
bool host_phase=false,invalidate_on_sync=false;
unsigned original_calls=0,revision_reads=0,sync_invalidations=0;
bool revision_available=true,invalidate_during_revision=false;
int host_journal_fsync(int);
#define fsync host_journal_fsync
'''

GUARDS = r'''
template<class>struct Guard;
template<class R,class...Args>struct Guard<R(*)(Args...)>{
    template<R(*Function)(Args...)>static R call(Args...args){
        assert(!host_phase&&"host Add must not invoke an original Unity/replay callback");
        ++original_calls;return Function(args...);
    }
};
bool host_graphics_snapshot(qm::Graphics& value){assert(!host_phase);++original_calls;return graphics_snapshot(value);}
bool host_graphics_apply(const qm::Graphics* value){assert(!host_phase);++original_calls;return graphics_apply(value);}
bool host_graphics_revision(int64_t& value){
    ++revision_reads;
    if(invalidate_during_revision){invalidate_during_revision=false;session_core::invalidate_queue_selection("selected_mv_ended");}
    value=current_graphics.revision;return revision_available;
}
int host_journal_fsync(int fd){
    struct stat info{};
    if(host_phase&&invalidate_on_sync&&fstat(fd,&info)==0&&S_ISREG(info.st_mode)){
        invalidate_on_sync=false;++sync_invalidations;session_core::invalidate_queue_selection("selected_mv_ended");
    }
    return ::fsync(fd);
}
bool host_photo_mode_is_mv(void*,Method*){return false;}
Api guarded_game_api(){
    Api selected=api();
    @@GAME_GUARDS@@
    selected.exact_type=&Guard<decltype(selected.exact_type)>::call<istype>;
    selected.photo_mode_is_mv=&Guard<decltype(selected.photo_mode_is_mv)>::call<host_photo_mode_is_mv>;
    return selected;
}
replay::Api guarded_replay_api(){
    replay::Api selected=replay_api();
    @@REPLAY_GUARDS@@
    return selected;
}
std::vector<Obj*> photo_id_sources;
void observe_photo_selection(void* param){
    auto* actor=obj(obj(get<void*>(get<void*>(param,0x10),0x10))->pointers[0]);
    void* descriptor=get<void*>(ptr(actor),0x28);void* character=get<void*>(ptr(actor),0x10);
    auto* data=make("Solis.Common.Photography.PhotographyLiveData");
    auto* descriptors=make("Solis.Common.SolisActorDescriptor[]");descriptors->array_kind=1;descriptors->pointers={descriptor};
    auto* characters=make("System.String[]");characters->array_kind=1;characters->pointers={character};
    write(data,0x10,get<void*>(param,0x18));write(data,0x18,get<void*>(param,0x20));write(data,0x20,ptr(descriptors));write(data,0x28,ptr(characters));
    auto* transition=make("Solis.Photography.Data.PhotographyLiveTransitionData");
    auto* stage=make("Solis.Common.Proto.Master.PhotoQuestStage");auto* music=make("Solis.Common.Proto.Master.PhotoQuestMusic");
    auto* costume=make("Solis.Common.Data.ActorCostume");auto* dress=make("Solis.Common.Proto.Master.Costume");auto* hair=make("Solis.Common.Proto.Master.Hair");
    for(const auto& value:std::vector<std::pair<Obj*,const char*>>{{stage,"photo-stage-A"},{music,"photo-music-A"},{dress,"costume-A"},{hair,"hair-A"}}){
        auto* id=obj(string_new(value.second));photo_id_sources.push_back(id);write(value.first,0x18,ptr(id));
    }
    write(costume,0x10,ptr(dress));write(costume,0x18,ptr(hair));
    auto* list=make("System.Collections.Generic.List`1");auto* items=make("array");items->array_kind=1;items->pointers={ptr(costume)};
    write(list,0x10,ptr(items));write(list,0x18,int32_t(1));write(transition,0x48,ptr(list));write(transition,0x68,ptr(stage));write(transition,0x70,ptr(music));write(transition,0x10,uint8_t(1));
    auto* mode=make("Solis.Photography.PhotographyLiveModePresenter");write(mode,0x20,ptr(player));write(mode,0x30,ptr(transition));
    presenter->type="Solis.Photography.PhotographyLivePresenter";player->type="Solis.Common.Photography.PhotographyLive3DPresenter";
    write(presenter,0x30,ptr(mode));write(player,0x70,uint8_t(1));
    session_core::observe_photography_initializing(ptr(player),ptr(data),ptr(descriptors));
    session_core::observe_presenter(ptr(presenter));session_core::observe_photography_transition(ptr(player),ptr(transition));
}
'''

DRIVER = r'''
#include <pthread.h>
#include <sys/resource.h>
bool small_stack_accepted=false;
void* add_on_small_stack(void*){
    small_stack_accepted=IDMP4QueueEnqueueV2(60,1,2,0,192000,1920,1080)==0;
    return nullptr;
}
void close_test(){
    host_phase=false;session_core::queue_replay().reset();session_core::selection.reset();session_core::game.reset_observations();assert(handles.empty());
    session_core::queue_store().close();if(session_core::queue_exports>=0)close(session_core::queue_exports);
    session_core::close_configuration(session_core::configured);
}
int main(int argc,char** argv){
    assert(argc==5);const std::string mode=argv[4];scenario="host-only";output_root=std::string(argv[1])+"/exports";
    router_scene=make("SceneSystem");router_home=make("HomeScreen");router_state=make("LiveState");
    connect_scene();assert(session_core::game.set_api(guarded_game_api()));
    session_core::install_game_api(guarded_game_api(),Layout{});
    session_core::install_queue_api(guarded_replay_api(),host_graphics_snapshot,host_graphics_apply,
        idoly_mp4_game::android_original_sha256,host_graphics_revision);
    assert(IDMP4SessionConfigure(argv[1],11,"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",output_root.c_str(),1)==0);
    if(mode!="not_configured")assert(IDMP4QueueConfigure(argv[2],argv[3])==0);
    current_graphics.revision=42;current_graphics.custom_graphics=1;current_graphics.quality=30;
    current_graphics.target_fps=60;current_graphics.render_scale=1.5f;current_graphics.max_buffer_pixel=3072;
    current_graphics.aa_mode=2;current_graphics.shadow_resolution=2048;current_graphics.expand_photography=1;
    void* a=nullptr;
    if(mode!="missing"){
        a=make_selection("A");select_param(a);
        if(mode=="photo"||mode=="end")observe_photo_selection(a);
        pump();
        assert(session_core::queue_candidate.valid&&session_core::queue_candidate.identity);
        assert(!std::strcmp(session_core::queue_candidate.descriptor.timeline_asset,"timeline_A"));
    }
    IDMP4SessionSuspend(IDMP4_PAUSE_LIFECYCLE_BACKGROUND);queue_source_valid=false;
    if(mode=="paused_tick"||mode=="surface_tick"){
        if(mode=="surface_tick")IDMP4SessionSuspend(IDMP4_PAUSE_SURFACE_UNAVAILABLE);
        pump();assert(session_core::queue_candidate.valid&&!session_core::published.ready);
    }
    if(a){
        obj(get<void*>(a,0x18))->name="stage_MUTATED";obj(get<void*>(a,0x20))->name="timeline_MUTATED";
        auto* actor=obj(obj(get<void*>(get<void*>(a,0x10),0x10))->pointers[0]);
        obj(get<void*>(ptr(actor),0x10))->name="character_MUTATED";
        auto* descriptor=obj(get<void*>(ptr(actor),0x28));auto* assets=obj(get<void*>(get<void*>(ptr(descriptor),0x10),0x10));
        obj(assets->pointers[0])->name="body_MUTATED";
    }
    // Frozen values must not alias these mutable fake source structures.
    current_graphics.render_scale=.75f;current_graphics.quality=10;
    for(auto* id:photo_id_sources)id->name="changed_after_snapshot";
    if(mode=="end")session_core::observe_presenter_ended(ptr(presenter));
    if(mode=="lifecycle")IDMP4QueueInvalidateSelection();
    if(mode=="reinitialize")session_core::observe_player_initializing(ptr(player),make_selection("B"));
    if(mode=="new_owner"){
        auto* other=make("Solis.OutGame.LivePlayerScreenPresenter");write(other,0xe0,ptr(player));session_core::observe_presenter(ptr(other));
    }
    if(mode=="configuration")assert(IDMP4SessionConfigure(argv[1],12,"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",output_root.c_str(),1)==0);
    if(mode=="same_configuration")assert(IDMP4SessionConfigure(argv[1],11,"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",output_root.c_str(),1)==0);
    if(mode=="profile")session_core::install_queue_api(guarded_replay_api(),host_graphics_snapshot,host_graphics_apply,
        idoly_mp4_game::android_original_sha256,host_graphics_revision);
    if(mode=="generation_exhausted"){
        pthread_mutex_lock(&session_core::control_mutex);session_core::queue_selection_generation=~uint64_t(0);pthread_mutex_unlock(&session_core::control_mutex);
        IDMP4QueueInvalidateSelection();
    }
    if(mode=="revision_changed")++current_graphics.revision;
    if(mode=="revision_unavailable")revision_available=false;
    if(mode=="revision_missing")session_core::queue_graphics_revision=nullptr;
    if(mode=="revision_negative")current_graphics.revision=-1;
    if(mode=="revision_race")invalidate_during_revision=true;
    if(mode=="end_after_accept")invalidate_on_sync=true;
    if(mode=="busy"){pthread_mutex_lock(&session_core::control_mutex);session_core::control_busy=true;pthread_mutex_unlock(&session_core::control_mutex);}
    const auto ticks=session_core::unity_ticks;const int calls=original_calls;
    const auto graphs=graph_steps,actors=actor_steps,audio_loads=loads,audio_reads=data_calls,was_opened=opened,was_closed=closed;
    const double old_time=time_value;host_phase=true;
    bool accepted=false;
    if(mode=="small_stack"){
        rlimit limit{0,0};assert(setrlimit(RLIMIT_CORE,&limit)==0);pthread_attr_t attr;assert(pthread_attr_init(&attr)==0);
        assert(pthread_attr_setstacksize(&attr,64*1024)==0);pthread_t worker;assert(pthread_create(&worker,&attr,add_on_small_stack,nullptr)==0);
        assert(pthread_attr_destroy(&attr)==0&&pthread_join(worker,nullptr)==0);accepted=small_stack_accepted;
    }else if(mode=="invalid_options")accepted=IDMP4QueueEnqueueV2(24,1,1,0,192000,0,0)==0;
    else if(mode=="numeric")accepted=IDMP4QueueEnqueue(30,1,1,12340000,192000)==0;
    else accepted=IDMP4QueueEnqueueV2(60,1,2,0,192000,1920,1080)==0;
    const std::map<std::string,std::string> rejected={
        {"missing","selected_mv_snapshot_missing"},{"not_configured","queue_not_configured"},
        {"end","selected_mv_ended"},{"lifecycle","selected_mv_snapshot_invalidated"},
        {"reinitialize","selected_mv_reinitializing"},{"new_owner","selected_mv_selection_changed"},
        {"configuration","server_configuration_changed"},{"profile","queue_profile_changed"},
        {"generation_exhausted","selection_generation_exhausted"},
        {"revision_changed","selected_graphics_changed_before_enqueue"},
        {"revision_unavailable","selected_graphics_revision_unavailable"},{"revision_negative","selected_graphics_revision_unavailable"},
        {"revision_missing","selected_graphics_revision_unavailable"},
        {"revision_race","selected_mv_selection_changed"},{"busy","queue_busy"},{"invalid_options","invalid_export_options"}};
    const auto expected=rejected.find(mode);
    if(expected!=rejected.end())assert(!accepted&&session_core::queue_store().count()==0&&!std::strcmp(session_core::queue_error,expected->second.c_str()));
    else{
        assert(accepted&&session_core::queue_store().count()==1);const auto* saved=session_core::queue_store().at(0);
        assert(!std::strcmp(saved->descriptor.stage_asset,"stage_A")&&!std::strcmp(saved->descriptor.timeline_asset,"timeline_A"));
        assert(!std::strcmp(saved->descriptor.actors[0].character_id,"rei")&&!std::strcmp(saved->descriptor.actors[0].assets[0],"body_A"));
        if(mode=="photo"){
            const auto& photo=saved->descriptor.photo;assert(photo.source_kind==1&&photo.is_preview==1&&!photo.is_original&&!photo.screen_transition&&photo.actor_count==1);
            assert(!std::strcmp(photo.stage_id,"photo-stage-A")&&!std::strcmp(photo.music_id,"photo-music-A")
                &&!std::strcmp(photo.actors[0].costume_id,"costume-A")&&!std::strcmp(photo.actors[0].hair_id,"hair-A"));
        }
        assert(saved->options.width==16&&saved->options.height==16&&saved->options.graphics.revision==42
            &&saved->options.graphics.render_scale==1.5f&&saved->options.graphics.quality==30&&saved->options.graphics.target_fps==60
            &&saved->options.graphics.custom_graphics==1&&saved->options.graphics.max_buffer_pixel==3072
            &&saved->options.graphics.aa_mode==2&&saved->options.graphics.shadow_resolution==2048&&saved->options.graphics.expand_photography==1);
        if(mode=="numeric")assert(saved->options.video_bitrate==12340000&&saved->options.output_width==0&&saved->options.output_height==0&&saved->options.fps_num==30);
        else assert(saved->options.video_bitrate==11200000&&saved->options.output_width==1920&&saved->options.output_height==1080&&saved->options.fps_num==60&&saved->options.codec==2);
        if(mode=="repeated"){
            assert(IDMP4QueueEnqueue(30,1,1,0,192000)==0&&session_core::queue_store().count()==2);
            assert(std::strcmp(session_core::queue_store().at(0)->id,session_core::queue_store().at(1)->id));
            assert(session_core::queue_store().at(1)->options.video_bitrate==250000);
        }
        if(mode=="end_after_accept"){
            assert(sync_invalidations==1&&!invalidate_on_sync);
            assert(IDMP4QueueEnqueue(30,1,1,16000000,192000)!=0&&session_core::queue_store().count()==1);
            assert(!std::strcmp(session_core::queue_error,"selected_mv_ended"));
        }
        // Observe a new decoded store, not only the host admission's in-memory
        // view. The accepted journal must already be durable without a tick.
        const size_t persisted_count=session_core::queue_store().count();
        session_core::queue_store().close();
        assert(session_core::queue_store().open(argv[2],idoly_mp4_game::android_original_sha256)==qm::Error::ok);
        assert(session_core::queue_store().count()==persisted_count);
        for(size_t i=0;i<persisted_count;++i){
            const auto* restored=session_core::queue_store().at(i);
            assert(restored->state==qm::State::pending&&!std::strcmp(restored->descriptor.timeline_asset,"timeline_A")
                &&restored->options.graphics.revision==42&&restored->options.graphics.render_scale==1.5f);
            if(mode=="photo")assert(restored->descriptor.photo.source_kind==1&&!std::strcmp(restored->descriptor.photo.actors[0].hair_id,"hair-A"));
        }
    }
    assert(session_core::queue_request.kind==session_core::QueueCommandKind::none);
    assert(original_calls==static_cast<unsigned>(calls)&&session_core::unity_ticks==ticks&&graph_steps==graphs&&actor_steps==actors
        &&loads==audio_loads&&data_calls==audio_reads&&opened==was_opened&&closed==was_closed&&time_value==old_time);
    char status[16384]{};assert(IDMP4QueueStatus(status,sizeof(status))&&!std::strstr(status,"\"command_pending\":true"));
    std::printf("{\"queue\":%s,\"accepted\":%s,\"revision_reads\":%u,\"unity_ticks_advanced\":0,\"original_callbacks\":0}\n",status,accepted?"true":"false",revision_reads);
    close_test();
}
'''


def guarded_fixture():
    api = re.search(r"Api api\(\)\{(.*?)return a;\}",BASE,re.S)
    replay_api = re.search(r"replay::Api replay_api\(\)\{(.*?)return a;\}",QUEUE,re.S)
    assert api and replay_api
    assignment = r"\ba\.([A-Za-z_]+)\s*=\s*([A-Za-z_][A-Za-z_0-9]*)\s*;"
    game = dict(re.findall(assignment,api.group(1)))
    # The only populated non-callable is an already resolved managed Type.
    assert set(re.findall(r"\ba\.([A-Za-z_]+)\s*=",api.group(1))) - game.keys() == {"audio_clip_type"}
    game.update(director_get_duration="session_duration",audio_clip_samples="session_samples",
        audio_clip_frequency="session_rate",timeline_get_tracks="session_tracks",track_get_clips="session_clips",
        bundle_load_file_async="session_load_bundle",audio_clip_get_data="session_get_data",bundle_unload="session_unload",
        brain_manual_update="session_brain_update",camera_clock_ok="session_camera_clock_ok",
        source_geometry="queue_source_geometry",camera_pixel_width="pixel_width",camera_pixel_height="pixel_height")
    replay = dict(re.findall(assignment,replay_api.group(1)))
    assert set(re.findall(r"\ba\.([A-Za-z_]+)\s*=",replay_api.group(1))) == replay.keys()
    def calls(values):
        return "\n".join(f"selected.{field}=&Guard<decltype(selected.{field})>::call<{function}>;" for field,function in values.items())
    guards = GUARDS.replace("@@GAME_GUARDS@@",calls(game)).replace("@@REPLAY_GUARDS@@",calls(replay))
    return PRELUDE + HOST_PRELUDE + BASE + "\n#undef fsync\n" + SESSION + QUEUE.split("int main(int argc,char** argv){",1)[0] + guards + DRIVER


@pytest.fixture(scope="module")
def host_enqueue_binary(tmp_path_factory):
    compiler = shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        pytest.skip("C++ compiler required")
    folder = tmp_path_factory.mktemp("mp4-host-enqueue")
    source,binary = folder / "host.cpp",folder / "host"
    source.write_text(guarded_fixture())
    predefined = subprocess.run([compiler,"-dM","-E","-x","c++","-"],input="",capture_output=True,text=True,timeout=10)
    assert predefined.returncode == 0, predefined.stderr
    macros = {line.split()[1] for line in predefined.stdout.splitlines() if line.startswith("#define ")}
    # The existing queue error projection intentionally bounds a larger native
    # reason. GCC diagnoses that inlined snprintf; Clang has no such option.
    warnings = ["-Wno-format-truncation"] if "__GNUC__" in macros and "__clang__" not in macros else []
    result = subprocess.run([compiler,"-std=c++17","-O1","-Wall","-Wextra","-Werror",*warnings,"-pthread",
        "-I",str(ROOT / "client-presentation/native"),str(source),"-o",str(binary)],capture_output=True,text=True,timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    return binary


def host_run(host_enqueue_binary,tmp_path,scenario):
    broker,queue,completed = tmp_path / "broker",tmp_path / "queue",tmp_path / "completed"
    for path in (broker,queue,completed):
        path.mkdir(mode=0o700)
    for child in ("exports","req","rsp","prepared"):
        (broker / child).mkdir(mode=0o700)
    result = subprocess.run([str(host_enqueue_binary),str(broker),str(queue),str(completed),scenario],
                            capture_output=True,text=True,timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize("scenario",["frozen","photo","numeric","repeated","same_configuration","small_stack","end_after_accept","paused_tick","surface_tick"])
def test_paused_host_add_commits_frozen_job_without_any_unity_callback(host_enqueue_binary,tmp_path,scenario):
    value = host_run(host_enqueue_binary,tmp_path,scenario)
    assert value["accepted"] is True
    assert value["original_callbacks"] == value["unity_ticks_advanced"] == 0
    assert value["queue"]["command_pending"] is False
    assert value["queue"]["can_run"] is True
    assert len(value["queue"]["jobs"]) == (2 if scenario == "repeated" else 1)
    assert all(job["timeline"] == "timeline_A" for job in value["queue"]["jobs"])


@pytest.mark.parametrize("scenario",["missing","not_configured","end","lifecycle","reinitialize","new_owner",
    "configuration","profile","generation_exhausted","revision_changed","revision_unavailable","revision_negative","revision_missing",
    "revision_race","busy","invalid_options"])
def test_host_rejection_is_immediate_and_never_defers_a_unity_command(host_enqueue_binary,tmp_path,scenario):
    value = host_run(host_enqueue_binary,tmp_path,scenario)
    assert value["accepted"] is False and value["queue"]["jobs"] == []
    assert value["queue"]["command_pending"] is False
    assert value["original_callbacks"] == value["unity_ticks_advanced"] == 0
