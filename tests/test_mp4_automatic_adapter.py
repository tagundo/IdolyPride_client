"""Run the production adapter's separate automatic entry and pending cleanup.

All native-Unity/dependent callbacks are synthetic; this verifies adapter and
protocol integration, not a completed physical camera/ActorSwing export.
"""
from pathlib import Path
import shutil
import subprocess

import pytest

from test_mp4_game_adapter import SOURCE

ROOT=Path(__file__).resolve().parents[1]
EXTRA=r'''
namespace playback=idoly_mp4_playback;
playback::ClockState fixed_clock{true,true};
int play_state=1,root_version=7,dependent_history=37,original_history=0,dep_release_calls=0;
bool dependency_owner=true,dep_fence=true,dep_restore_ready=true,dep_owned_release=true;
bool dep_release_ready=true;
unsigned pending_native_jobs=1,quiesce_calls=0;bool quiesce_ready=true;
bool shader_lease_live=false,shader_lease_custom=false;float shader_lease_saved=0;
unsigned shader_generation=1,shader_owned_generation=0,shader_finishes=0;
unsigned direct_sets=0,root_evaluates=0,projection_updates=0;
playback::ClockState clock_state(){return fixed_clock;}
int32_t original_state(void*,Method*){return play_state;}
void original_play(void*,Method*){play_state=1;}
void original_pause(void*,Method*){play_state=0;}
void original_resume(void*,Method*){play_state=1;}
void original_rebuild(void*,Method*){assert(!pending_native_jobs);++root_version;dependent_history=0;}
void original_graph(void*,PlayableGraph* value,Method*){*value={reinterpret_cast<void*>(0x1234),root_version,0};}
bool original_graph_valid(PlayableGraph* value,Method*){
    return value->handle==reinterpret_cast<void*>(0x1234)?value->version==root_version:value->handle==reinterpret_cast<void*>(0x2222);
}
void original_set_time(void*,double value,Method*){++direct_sets;time_value=value;}
void original_evaluate(void*,Method*){++root_evaluates;dependent_history=-200;pending_native_jobs=2;}
bool flag_playing(void* value,Method*){return static_cast<uint8_t*>(value)[0x71];}
bool flag_paused(void* value,Method*){return static_cast<uint8_t*>(value)[0x72];}
void flag_set_playing(void* value,bool flag,Method*){static_cast<uint8_t*>(value)[0x71]=flag;}
void flag_set_paused(void* value,bool flag,Method*){static_cast<uint8_t*>(value)[0x72]=flag;}
bool dep_owner(void* value){assert(value==&dependent_history);return dependency_owner;}
playback::Result dep_quiesce(void*){assert(fixed_clock.owned&&fixed_clock.held);++quiesce_calls;if(!quiesce_ready)return playback::Result::waiting;pending_native_jobs=0;return playback::Result::ok;}
playback::Result dep_capture(void*){assert(!pending_native_jobs);if(!dep_fence)return playback::Result::waiting;original_history=dependent_history;return playback::Result::ok;}
playback::Result dep_prepare(void*){assert(bgm_volume==0&&voice_volume==0);return playback::Result::ok;}
playback::Result dep_reset(void*){dependent_history=0;return playback::Result::ok;}
playback::Result dep_restore(void*){if(!dep_restore_ready)return playback::Result::waiting;auto quiet=dep_quiesce(nullptr);if(quiet!=playback::Result::ok)return quiet;dependent_history=original_history;return playback::Result::ok;}
playback::Result dep_release(void*,bool owned){++dep_release_calls;dep_owned_release=owned;return dep_release_ready?playback::Result::ok:playback::Result::waiting;}
const char* dep_error(void*){return "actor_fence_pending";}
bool tracked_projection(void* value,bool){assert(value==ptr(camera_controller));++projection_updates;return true;}
bool tracked_geometry(void* value,int32_t width,int32_t height){if(value)assert(!pending_native_jobs);return resize_output(value,width,height);}
bool lease_begin(void* context){assert(context==&dependent_history&&!shader_lease_live);shader_lease_live=true;shader_lease_custom=custom;shader_lease_saved=shader;shader_owned_generation=shader_generation;return true;}
bool lease_set(void* context,float value){assert(context==&dependent_history&&shader_lease_live);if(shader_owned_generation!=shader_generation)return false;shader=value;custom=true;return true;}
void lease_finish(void* context){assert(context==&dependent_history&&shader_lease_live);++shader_finishes;shader_lease_live=false;if(shader_owned_generation==shader_generation){shader=shader_lease_saved;custom=shader_lease_custom;}}
'''
DRIVER=r'''
int main(int argc,char**argv){
    assert(argc==2);const std::string scenario=argv[1];
    // SETUP
    selected_api.director_graph_injected=original_graph;selected_api.graph_valid=original_graph_valid;
    selected_api.director_set_time=original_set_time;selected_api.director_evaluate=original_evaluate;
    selected_api.output_projection=tracked_projection;
    selected_api.output_geometry=tracked_geometry;
    auto& p=selected_api.automatic_playback;
    p.director_state=original_state;p.director_play=original_play;p.director_pause=original_pause;
    p.director_resume=original_resume;p.director_rebuild=original_rebuild;
    p.player_playing=flag_playing;p.player_paused=flag_paused;p.player_set_playing=flag_set_playing;p.player_set_paused=flag_set_paused;
    selected_api.automatic_dependents={dep_owner,dep_quiesce,dep_capture,dep_prepare,dep_reset,dep_restore,dep_release,dep_error};
    selected_api.automatic_shader={lease_begin,lease_set,lease_finish};
    selected_api.automatic_context=&dependent_history;selected_api.automatic_clock_state=clock_state;
    write(player,0x71,uint8_t(1));write(player,0x72,uint8_t(scenario=="paused"));
    if(scenario=="paused")play_state=0;
    if(scenario=="missing_dependency")selected_api.automatic_dependents.capture=nullptr;
    if(scenario=="missing_quiesce")selected_api.automatic_dependents.quiesce=nullptr;
    if(scenario=="missing_original_call")selected_api.automatic_playback.director_rebuild=nullptr;
    if(scenario=="missing_shader_lease")selected_api.automatic_shader.finish=nullptr;
    if(scenario=="clock_wait")fixed_clock={true,false};
    if(scenario=="capture_wait")dep_fence=false;
    const auto original_api=selected_api.automatic_playback;const auto original_dependents=selected_api.automatic_dependents;
    const auto original_context=selected_api.automatic_context;const auto original_clock=selected_api.automatic_clock_state;
    const auto original_shader=selected_api.automatic_shader;selected_api.automatic_shader={};
    selected_api.automatic_playback={};selected_api.automatic_dependents={};
    selected_api.automatic_context=nullptr;selected_api.automatic_clock_state=nullptr;
    GameAdapter a(selected_api);a.observe_presenter(ptr(presenter));a.observe_camera_controller(ptr(camera_controller));
    Snapshot snapshot{};assert(a.snapshot(snapshot)==Result::ok);
    const auto observed_handles=handles.size();
    if(scenario=="late_install_private_audio"){
        assert(a.begin_private_audio("/private/held.bundle",snapshot.audio.clips[0])==Result::waiting);
        scalar_no_managed_calls=true;
        assert(!a.install_dependent_api(original_api,original_dependents,original_context,original_clock,original_shader));
        scalar_no_managed_calls=false;done=true;a.close_private_audio();assert(a.private_audio_quiescent());
        assert(handles.size()==observed_handles);
    }
    scalar_no_managed_calls=true;
    const bool installed=a.install_dependent_api(original_api,original_dependents,original_context,original_clock,original_shader);
    scalar_no_managed_calls=false;
    assert(installed==(scenario!="missing_dependency"&&scenario!="missing_quiesce"&&scenario!="missing_original_call"&&scenario!="missing_shader_lease"));
    assert(handles.size()==observed_handles);
    const auto initial_generation=a.owned_scene_generation();
    auto result=a.begin_automatic();
    if(scenario=="missing_dependency"||scenario=="missing_quiesce"||scenario=="missing_original_call"||scenario=="missing_shader_lease"){
        assert(result==Result::unsupported&&!a.manual()&&!a.automatic()&&time_value==13.25&&actor_steps==0);
        a.reset_observations();assert(handles.empty());return 0;
    }
    if(scenario=="clock_wait"){
        assert(result==Result::waiting&&!a.manual()&&bgm_volume==.6f);fixed_clock={true,true};result=a.begin_automatic();
    }
    if(scenario=="capture_wait"){
        assert(result==Result::waiting&&a.restoration_pending()&&bgm_volume==.6f&&play_state==1);
        dep_fence=true;result=a.begin_automatic();
    }
    assert(result==Result::ok&&a.manual()&&a.automatic()&&play_state==0&&bgm_volume==0&&voice_volume==0);
    scalar_no_managed_calls=true;
    assert(!a.install_dependent_api(original_api,original_dependents,original_context,original_clock,original_shader));
    scalar_no_managed_calls=false;
    const auto owned_generation=a.owned_scene_generation();assert(owned_generation>initial_generation);
    assert(a.set_output_geometry(16,16)==Result::ok);
    if(scenario=="adoption_wait"){
        write(animation_player,0x28,PlayableGraph{});assert(a.start_automatic()==Result::waiting);
        const auto version=root_version;const auto sets=direct_sets;
        write(animation_player,0x28,PlayableGraph{reinterpret_cast<void*>(0x2222),9,0});
        assert(a.start_automatic()==Result::ok&&root_version==version&&direct_sets==sets);
    }else assert(a.start_automatic()==Result::ok);
    assert(mode==1&&play_state==1&&time_value==0&&actor_mode==1);
    // Our intentional original RebuildGraph does not start another scene.
    assert(a.owned_scene_generation()==owned_generation);
    const unsigned set_before=direct_sets,evaluate_before=root_evaluates,project_before=projection_updates;
    for(unsigned frame=0;frame<120;++frame){
        const double target=frame/60.,previous_time=time_value;
        assert(a.prepare_automatic_frame(target)==Result::ok&&time_value==previous_time&&shader==static_cast<float>(target)&&custom);
        if(frame)assert(a.validate_automatic_frame(target)==Result::failed);
        time_value=target;assert(a.validate_automatic_frame(target)==Result::ok);
        assert(a.evaluate(time_value)==Result::ok);assert(a.original_camera_updated(ptr(brain))==Result::ok);
        pending_native_jobs=1;
    }
    assert(direct_sets==set_before&&root_evaluates==evaluate_before&&actor_steps==0&&graph_steps==0&&actor_resets==0);
    assert(camera_steps==0&&projection_updates==project_before+120);
    assert(a.prepare_automatic_frame(123)==Result::invalid);
    if(scenario=="shader_superseded"){
        // An external setter of exactly the same value revokes ownership.
        const float externally_set=shader;++shader_generation;custom=true;
        assert(a.prepare_automatic_frame(2)==Result::stale&&!std::strcmp(a.last_error(),"shader_lease_superseded"));
        assert(a.restore()==Result::ok&&!shader_lease_live&&shader_finishes==1&&custom&&shader==externally_set);
        a.reset_observations();assert(handles.empty());return 0;
    }
    if(scenario=="prepare_restore"){
        const auto geometry_before=geometry_calls.size();const auto sets_before=direct_sets;
        assert(pending_native_jobs&&a.prepare_restore()==Result::ok&&!pending_native_jobs);
        assert(geometry_calls.size()==geometry_before&&direct_sets==sets_before&&root_evaluates==evaluate_before);
        assert(mode==1&&play_state==1&&time_value==119/60.&&bgm_volume==0&&voice_volume==0);
    }
    if(scenario=="changed_owner"||scenario=="reinitialized"||scenario=="presenter_reinitialized"){
        if(scenario!="changed_owner"){
            // The same retained component, timeline, camera and root graph
            // can be reused. The explicit original-init boundary must retire
            // the old scope before writing this new logical scene's values.
            scalar_no_managed_calls=true;
            a.invalidate_owned_scene(nullptr);a.invalidate_owned_scene(reinterpret_cast<void*>(0x777));
            a.invalidate_owned_scene(ptr(brain));a.observe_player_initializing(ptr(presenter));
            assert(a.owned_scene_generation()==owned_generation);
            a.release_shader_lease_for_scene(reinterpret_cast<void*>(0x777));assert(shader_lease_live&&!shader_finishes);
            if(scenario=="reinitialized"){
                a.release_shader_lease_for_scene(ptr(player));
                assert(!shader_lease_live&&shader_finishes==1&&!custom);
            }
            if(scenario=="reinitialized")a.observe_player_initializing(ptr(player));
            else a.invalidate_owned_scene(ptr(presenter));
            assert(a.owned_scene_generation()==owned_generation+1);
            scalar_no_managed_calls=false;
            time_value=9;mode=2;bgm_volume=.3f;voice_volume=.7f;
        }else{take_over_scene();++shader_generation;dependency_owner=false;}
        const auto prior_geometry=geometry_calls.size();
        const auto prior_quiesce=quiesce_calls;
        assert(a.prepare_restore()==Result::stale&&quiesce_calls==prior_quiesce);
        if(scenario=="presenter_reinitialized"){
            dep_release_ready=false;assert(a.restore()==Result::waiting&&a.restoration_pending());
            assert(!shader_lease_live&&shader_finishes==1&&!custom);dep_release_ready=true;
        }
        assert(a.restore()==Result::stale&&!a.automatic()&&!a.restoration_pending()&&!dep_owned_release);
        assert(time_value==9&&mode==2&&bgm_volume==.3f&&voice_volume==.7f&&geometry_calls.size()==prior_geometry&&geometry_cleanup_calls==1);
        assert(quiesce_calls==prior_quiesce);
        a.reset_observations();assert(handles.empty());return 0;
    }
    if(scenario=="restore_clock_wait"){
        fixed_clock={true,false};const auto geometry_before=geometry_calls.size();
        assert(a.restore()==Result::waiting&&a.restoration_pending()&&geometry_calls.size()==geometry_before);
        assert(root_evaluates==evaluate_before&&mode==1&&bgm_volume==0&&voice_volume==0);
        fixed_clock={true,true};
    }
    if(scenario=="restore_quiesce_wait"){
        quiesce_ready=false;const auto geometry_before=geometry_calls.size();const auto quiesce_before=quiesce_calls;
        assert(a.restore()==Result::waiting&&a.restoration_pending()&&geometry_calls.size()==geometry_before);
        assert(pending_native_jobs&&quiesce_calls==quiesce_before+1&&root_evaluates==evaluate_before&&mode==1);
        quiesce_ready=true;
        assert(a.prepare_restore()==Result::ok&&!std::strcmp(a.last_error(),"none"));
    }
    if(scenario=="restore_wait"){
        dep_restore_ready=false;assert(a.restore()==Result::waiting&&a.restoration_pending());
        const auto retained=handles.size();a.reset_observations();assert(a.restoration_pending()&&handles.size()==retained);
        dep_restore_ready=true;
    }
    assert(a.restore()==Result::ok&&!a.automatic()&&!a.restoration_pending()&&!a.manual());
    assert(time_value==13.25&&mode==0&&play_state==(scenario=="paused"?0:1));
    assert(flag_playing(ptr(player),nullptr)&&flag_paused(ptr(player),nullptr)==(scenario=="paused"));
    assert(bgm_volume==.6f&&voice_volume==.4f&&dependent_history==37&&!custom&&actor_mode==1&&dep_release_calls==1&&dep_owned_release);
    assert(!shader_lease_live&&shader_finishes==1);
    assert(geometry_calls.back()[0]==0&&geometry_calls.back()[1]==0);
    const auto retired_generation=a.owned_scene_generation();scalar_no_managed_calls=true;
    a.invalidate_owned_scene(ptr(player));a.invalidate_owned_scene(ptr(presenter));
    assert(a.owned_scene_generation()==retired_generation);scalar_no_managed_calls=false;
    a.reset_observations();assert(handles.empty());
}
'''


@pytest.fixture(scope="module")
def automatic_adapter_binary(tmp_path_factory):
    compiler=shutil.which("c++")or shutil.which("g++")or shutil.which("clang++")
    if not compiler:pytest.skip("C++ compiler required")
    prefix,main=SOURCE.split("int main(){",1)
    setup=main.split("    GameAdapter a(selected_api);",1)[0]
    setup=setup[setup.index("    setup();"):]
    # A lifecycle generation change must be safe even before the original
    # initializer starts replacing or disposing managed/native state. Reject
    # any attempted GC-handle, type or Unity-alive observation in that scope.
    for signature in ("bool istype(void* p,const char* type){", "bool alive(void* p){",
                      "uint32_t retain(void* p){", "void* target(uint32_t h){", "void release(uint32_t h){"):
        assert signature in prefix
        prefix=prefix.replace(signature,signature+"assert(!scalar_no_managed_calls);",1)
    source="bool scalar_no_managed_calls=false;\n"+prefix+EXTRA+DRIVER.replace("    // SETUP",setup)
    directory=tmp_path_factory.mktemp("mp4-automatic-adapter");path=directory/"adapter.cpp";binary=directory/"adapter"
    path.write_text(source)
    built=subprocess.run([compiler,"-std=c++17","-O2","-Wall","-Wextra","-Werror","-I",str(ROOT/"client-presentation/native"),str(path),"-o",str(binary)],capture_output=True,text=True,timeout=30)
    assert built.returncode==0,built.stdout+built.stderr
    return binary


@pytest.mark.parametrize("scenario",["playing","paused","clock_wait","capture_wait","missing_dependency","missing_quiesce","missing_original_call","missing_shader_lease","shader_superseded","late_install_private_audio","adoption_wait","prepare_restore","restore_clock_wait","restore_quiesce_wait","restore_wait","changed_owner","reinitialized","presenter_reinitialized"])
def test_automatic_adapter_preserves_original_paused_state_and_never_manual_steps(automatic_adapter_binary,scenario):
    ran=subprocess.run([str(automatic_adapter_binary),scenario],capture_output=True,text=True,timeout=5)
    assert ran.returncode==0,ran.stdout+ran.stderr
