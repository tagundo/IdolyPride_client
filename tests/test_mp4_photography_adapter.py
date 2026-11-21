"""Exercise the original Photography owner graph through the real adapter.

The layout/types come from both pinned clients' metadata. Unity callbacks and
managed storage here are synthetic; this does not establish device rendering.
"""
from pathlib import Path
import shutil
import subprocess

import pytest

from test_mp4_game_adapter import SOURCE

ROOT = Path(__file__).resolve().parents[1]
BASE, MAIN = SOURCE.split("int main(){", 1)
CONNECT = MAIN.split("Api selected_api=api();", 1)[0]

DRIVER = r'''
Obj *photo_root=nullptr,*photo_mode=nullptr,*photo_data=nullptr;
bool photo_video=false;unsigned mode_queries=0;
std::map<void*,bool> component_active;
bool unity_alive(void* value){
    if(!value)return false;
    const auto& type=objects.at(value)->type;
    // These are managed values, never UnityEngine.Object subclasses. Do not
    // let this synthetic heap conceal an invalid original native boundary.
    assert(type!="Solis.Photography.Data.PhotographyLiveTransitionData"
        &&type!="System.Collections.Generic.List`1"&&type!="System.String"
        &&type!="array"&&type!="UnityEngine.Timeline.TimelineClip"
        &&type!="UnityEngine.Timeline.AudioMixerProperties"&&type!="UnityEngine.Timeline.AudioClipProperties");
    return alive(value);
}
bool photo_is_video(void* value,Method*){assert(value==ptr(photo_mode));++mode_queries;return photo_video;}
bool photo_active(void* value,Method*){auto found=component_active.find(value);return found==component_active.end()||found->second;}
Obj* mode_with_player(Obj* selected_player,Obj* data){auto* value=make("Solis.Photography.PhotographyLiveModePresenter");write(value,0x20,ptr(selected_player));write(value,0x30,ptr(data));return value;}
void establish_photography(){
    player->type="Solis.Common.Photography.PhotographyLive3DPresenter";
    write(player,0x70,uint8_t(1));
    photo_data=make("Solis.Photography.Data.PhotographyLiveTransitionData");
    photo_mode=mode_with_player(player,photo_data);
    photo_root=make("Solis.Photography.PhotographyLivePresenter");write(photo_root,0x30,ptr(photo_mode));
}
void new_scene_state(){mode=2;time_value=9;bgm_volume=.3f;voice_volume=.7f;actor_mode=2;custom=true;shader=77;}
int main(int argc,char** argv){
    assert(argc==2);std::string scenario=argv[1];
    connect_scene();Api api_=api();api_.camera_pixel_width=logical_width;api_.camera_pixel_height=logical_height;
    api_.source_geometry=actual_source_geometry;api_.output_geometry=resize_output;api_.output_projection=project_output;
    api_.photo_mode_is_mv=photo_is_video;api_.active_enabled=photo_active;api_.alive=unity_alive;
    GameAdapter game(api_);clock_game=&game;
    if(scenario=="normal"){
        game.observe_presenter(ptr(presenter));game.observe_camera_controller(ptr(camera_controller));Snapshot snapshot{};
        assert(game.scene_kind()==SceneKind::out_game&&game.snapshot(snapshot)==Result::ok&&mode_queries==0);
        assert(game.selected_player()==ptr(player)&&game.begin_manual()==Result::ok&&game.evaluate(1)==Result::ok);
        assert(game.restore()==Result::ok&&mode==0&&time_value==13.25&&bgm_volume==.6f&&voice_volume==.4f);
        game.reset_observations();assert(handles.empty());return 0;
    }
    if(scenario=="missing_root"){
        Snapshot snapshot{};assert(game.snapshot(snapshot)==Result::waiting&&std::string(game.last_error())=="selected_presenter_missing");
        game.reset_observations();assert(handles.empty());return 0;
    }
    establish_photography();
    if(scenario=="360_root")photo_root->type="Solis.Photography.Photography360LiveContentPresenter";
    if(scenario=="360_player")player->type="Solis.Common.Photography.Photography360Live3DPresenter";
    if(scenario=="not_built")write(player,0x70,uint8_t(0));
    if(scenario=="root_inactive")component_active[ptr(photo_root)]=false;
    if(scenario=="mode_inactive")component_active[ptr(photo_mode)]=false;
    if(scenario=="player_inactive")component_active[ptr(player)]=false;
    if(scenario=="video")photo_video=true;
    if(scenario=="null_data")write(photo_mode,0x30,static_cast<void*>(nullptr));
    if(scenario=="wrong_data")write(photo_mode,0x30,ptr(make("System.String")));
    if(scenario=="null_mode")write(photo_root,0x30,static_cast<void*>(nullptr));
    if(scenario=="wrong_mode")write(photo_root,0x30,ptr(make("System.String")));
    if(scenario=="missing_mode_api"){api_.photo_mode_is_mv=nullptr;assert(game.set_api(api_));}
    if(scenario=="missing_active_api"){api_.active_enabled=nullptr;assert(game.set_api(api_));}
    if(scenario=="unrelated_camera")camera=make("UnityEngine.Camera");
    if(scenario=="portrait"){source_width=1080;source_height=1920;}
    game.observe_presenter(ptr(photo_root));if(scenario!="missing_controller")game.observe_camera_controller(ptr(camera_controller));Snapshot snapshot{};
    if(scenario=="ended_before_snapshot"){
        game.observe_presenter_ended(ptr(photo_root));assert(!game.selected_presenter()&&!game.selected_player());
        assert(game.scene_kind()==SceneKind::none&&game.snapshot(snapshot)==Result::waiting
            &&std::string(game.last_error())=="selected_presenter_missing");
        game.reset_observations();assert(handles.empty());return 0;
    }
    if(scenario=="360_root"){
        assert(game.scene_kind()==SceneKind::none&&!game.selected_presenter()&&!game.selected_player());
        assert(game.snapshot(snapshot)==Result::waiting&&mode_queries==0);game.reset_observations();assert(handles.empty());return 0;
    }
    assert(game.scene_kind()==SceneKind::photography);
    const std::map<std::string,std::string> rejected={
        {"360_player","selected_photography_3d_not_loaded"},{"not_built","selected_photography_3d_not_built"},
        {"root_inactive","selected_photography_3d_not_built"},{"mode_inactive","selected_photography_3d_not_built"},
        {"player_inactive","selected_photography_3d_not_built"},{"video","selected_video_mv_unsupported"},
        {"null_data","selected_photography_data_not_loaded"},{"wrong_data","selected_photography_data_not_loaded"},
        {"null_mode","selected_photography_mode_not_loaded"},{"wrong_mode","selected_photography_mode_not_loaded"},
        {"missing_mode_api","photography_scene_api_unavailable"},{"missing_active_api","photography_scene_api_unavailable"},
        {"missing_controller","selected_render_controller_missing"},{"unrelated_camera","selected_mv_camera_not_observed"}};
    if(auto reason=rejected.find(scenario);reason!=rejected.end()){
        assert(game.snapshot(snapshot)==Result::waiting&&game.last_error()==reason->second);
        if(scenario!="unrelated_camera"&&scenario!="missing_controller")assert(!game.selected_player());
        if(scenario=="null_data"||scenario=="wrong_data"||scenario=="null_mode"||scenario=="wrong_mode")assert(mode_queries==0);
        if(scenario=="not_built"){
            // Original initialization finishes asynchronously. The same rooted
            // owner becomes eligible without another screen-entry event.
            write(player,0x70,uint8_t(1));assert(game.snapshot(snapshot)==Result::ok&&game.selected_player()==ptr(player));
        }
        game.reset_observations();assert(handles.empty());return 0;
    }
    assert(game.snapshot(snapshot)==Result::ok&&game.selected_player()==ptr(player));
    assert(snapshot.duration_seconds==122&&snapshot.actor_graph_count==1&&snapshot.audio.count==1);
    if(scenario=="ended_before_manual"||scenario=="same_root_reinitialize"){
        game.observe_presenter_ended(ptr(photo_root));assert(!game.selected_presenter()&&!game.selected_player());
        assert(game.begin_manual()==Result::stale&&mode==0&&time_value==13.25&&bgm_volume==.6f&&voice_volume==.4f);
        assert(game.snapshot(snapshot)==Result::waiting&&std::string(game.last_error())=="selected_presenter_missing");
        if(scenario=="ended_before_manual"){game.reset_observations();assert(handles.empty());return 0;}
        game.observe_presenter(ptr(photo_root));assert(game.snapshot(snapshot)==Result::ok&&game.selected_player()==ptr(player));
    }
    if(scenario=="unrelated_ended"){
        game.observe_presenter_ended(ptr(make("Solis.Photography.PhotographyLivePresenter")));
        assert(game.selected_presenter()==ptr(photo_root)&&game.selected_player()==ptr(player));
    }
    int32_t observed_width=0,observed_height=0;assert(game.source_geometry(observed_width,observed_height)==Result::ok);
    if(scenario=="portrait")assert(observed_width==1080&&observed_height==1920);
    assert(game.begin_manual()==Result::ok&&mode==3&&bgm_volume==0&&voice_volume==0&&actor_mode==3);
    assert(game.evaluate(1)==Result::ok&&time_value==1&&camera_steps==1);
    if(scenario=="capture"){
        assert(game.request_capture()==Result::ok);int32_t width=0,height=0;size_t bytes=0;std::vector<uint8_t> pixels(1024);
        assert(game.capture_geometry(width,height)==Result::ok&&width==16&&height==16);
        auto* pass=make("VL.Rendering.VLCapturePass");auto* rendering=make("RenderingData");
        write(rendering,0x90,ptr(camera));write(rendering,0x158,uint8_t(1));
        game.observe_capture_pass(ptr(pass),ptr(rendering));assert(game.after_camera(ptr(camera)));
        assert(game.readback_rgba(pixels.data(),pixels.size(),bytes,width,height)==Result::ok&&bytes==1024&&pixels[0]==15&&pixels[15*64]==0);
    }
    if(scenario=="unrelated_ended"){
        game.observe_presenter_ended(ptr(make("Solis.Photography.PhotographyLivePresenter")));
        assert(game.owned_primary_scene_current()&&game.selected_player()==ptr(player));
    }
    if(scenario=="mode_changed"||scenario=="data_changed"||scenario=="video_changed"||scenario=="owner_changed"||scenario=="ended_during_manual"){
        assert(game.set_output_geometry(1920,1080)==Result::ok);const auto before_calls=geometry_calls.size();
        if(scenario=="mode_changed"){photo_mode=mode_with_player(player,photo_data);write(photo_root,0x30,ptr(photo_mode));}
        if(scenario=="data_changed"){photo_data=make("Solis.Photography.Data.PhotographyLiveTransitionData");write(photo_mode,0x30,ptr(photo_data));}
        if(scenario=="video_changed")photo_video=true;
        if(scenario=="owner_changed"){auto* next=make("Solis.Photography.PhotographyLivePresenter");write(next,0x30,ptr(photo_mode));game.observe_presenter(ptr(next));}
        if(scenario=="ended_during_manual")game.observe_presenter_ended(ptr(photo_root));
        new_scene_state();assert(!game.owned_primary_scene_current()&&game.evaluate(2)==Result::stale);
        assert(game.restore()==Result::ok&&geometry_calls.size()==before_calls&&geometry_cleanup_calls==1);
        assert(mode==2&&time_value==9&&bgm_volume==.3f&&voice_volume==.7f&&actor_mode==2&&custom&&shader==77);
    }else{
        if(scenario=="inactive_during_restore"){write(player,0x70,uint8_t(0));component_active[ptr(player)]=false;}
        if(scenario=="actor_rebuilt"){write(animation_player,0x28,PlayableGraph{reinterpret_cast<void*>(0x3333),10,0});actor_mode=2;}
        assert(game.owned_primary_scene_current());
        assert(game.restore()==Result::ok&&mode==0&&time_value==13.25&&bgm_volume==.6f&&voice_volume==.4f&&!custom);
        assert(actor_mode==(scenario=="actor_rebuilt"?2:1));
    }
    game.reset_observations();assert(handles.empty());
}
'''


@pytest.fixture(scope="module")
def photography_adapter_executable(tmp_path_factory):
    compiler = shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        pytest.skip("C++ compiler required")
    root = tmp_path_factory.mktemp("mp4-photography-adapter")
    source, binary = root / "photography.cpp", root / "photography"
    source.write_text(BASE + "\nvoid connect_scene(){\n" + CONNECT + "\n}\n" + DRIVER)
    result = subprocess.run([compiler,"-std=c++17","-Wall","-Wextra","-Werror","-I",
        str(ROOT / "client-presentation/native"),str(source),"-o",str(binary)],capture_output=True,text=True,timeout=30)
    assert result.returncode == 0, result.stderr
    return binary


@pytest.mark.parametrize("scenario", ["normal","snapshot","portrait","capture","missing_root","missing_controller","360_root","360_player","not_built",
    "root_inactive","mode_inactive","player_inactive","video","null_data","wrong_data","null_mode","wrong_mode","missing_mode_api","missing_active_api",
    "unrelated_camera","mode_changed","data_changed","video_changed","owner_changed","inactive_during_restore","actor_rebuilt",
    "ended_before_snapshot","ended_before_manual","ended_during_manual","unrelated_ended","same_root_reinitialize"])
def test_original_photography_graph_admission_and_strict_ownership(photography_adapter_executable,scenario):
    result=subprocess.run([str(photography_adapter_executable),scenario],capture_output=True,text=True,timeout=5)
    assert result.returncode == 0, result.stderr
