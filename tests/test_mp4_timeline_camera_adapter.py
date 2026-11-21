"""Exercise the nested original camera ownership through the full adapter."""
from pathlib import Path
import shutil
import subprocess

import pytest

from test_mp4_game_adapter import SOURCE

ROOT = Path(__file__).resolve().parents[1]
BASE, MAIN = SOURCE.split("int main(){", 1)
CONNECT = MAIN.split("Api selected_api=api();", 1)[0]


def _nested_source():
    source = BASE
    replacements = {
        "void* asset(void*,Method*){return ptr(timeline);}":
            "Obj *camera_director=nullptr,*camera_timeline=nullptr;\n"
            "void* asset(void* owner,Method*){return owner==ptr(camera_director)?ptr(camera_timeline):"
            "owner==ptr(director)?ptr(timeline):nullptr;}",
        "void* binding(void*,void*,Method*){return ptr(brain);}":
            "void* binding(void* owner,void* track_,Method*){return owner==ptr(camera_director)"
            "&&track_==ptr(camera_track)?ptr(brain):nullptr;}",
        'void* tracks(void*,Method*){auto* a=make("UnityEngine.Timeline.TrackAsset[]");a->array_kind=1;a->pointers={ptr(track),ptr(camera_track)};return ptr(a);}':
            'void* tracks(void* asset_,Method*){auto* a=make("UnityEngine.Timeline.TrackAsset[]");'
            'a->array_kind=1;a->pointers=asset_==ptr(camera_timeline)?std::vector<void*>{ptr(camera_track)}:'
            'std::vector<void*>{ptr(track)};return ptr(a);}',
    }
    for old, new in replacements.items():
        assert source.count(old) == 1
        source = source.replace(old, new)
    return source + "\nvoid connect_scene(){\n" + CONNECT + r'''
    camera_director=make("UnityEngine.Playables.PlayableDirector");
    camera_timeline=make("UnityEngine.Timeline.TimelineAsset");
}
bool photo_not_video(void*,Method*){return false;}
bool photo_active(void*,Method*){return true;}
int main(int argc,char** argv){
    assert(argc==2);std::string scenario=argv[1];connect_scene();
    auto* list=objects.at(*reinterpret_cast<void**>(controller->mem.data()+0x28));
    auto* items=objects.at(*reinterpret_cast<void**>(list->mem.data()+0x10));
    if(scenario!="unowned"){
        items->pointers.push_back(ptr(camera_director));write(list,0x18,int32_t(2));
    }
    if(scenario=="unrelated_child_changed"){
        items->pointers.push_back(ptr(make("UnityEngine.Playables.PlayableDirector")));
        write(list,0x18,int32_t(3));
    }
    Api api_=api();api_.photo_mode_is_mv=photo_not_video;api_.active_enabled=photo_active;
    if(scenario=="photography"){
        player->type="Solis.Common.Photography.PhotographyLive3DPresenter";write(player,0x70,uint8_t(1));
        auto* data=make("Solis.Photography.Data.PhotographyLiveTransitionData");
        auto* mode_=make("Solis.Photography.PhotographyLiveModePresenter");
        write(mode_,0x20,ptr(player));write(mode_,0x30,ptr(data));
        presenter=make("Solis.Photography.PhotographyLivePresenter");write(presenter,0x30,ptr(mode_));
    }
    GameAdapter game(api_);clock_game=&game;
    game.observe_presenter(ptr(presenter));game.observe_camera_controller(ptr(camera_controller));
    Snapshot snapshot{};const auto result=game.snapshot(snapshot);
    if(scenario=="unowned"){
        assert(result==Result::waiting&&!std::strcmp(game.last_error(),"selected_camera_track_not_found"));
    }else{
        assert(result==Result::ok&&snapshot.audio.count==1&&snapshot.duration_seconds==122);
        if(scenario=="list_version_changed")write(list,0x1c,int32_t(1));
        if(scenario=="list_array_changed"){
            auto* replacement=make("UnityEngine.Playables.PlayableDirector[]");
            replacement->array_kind=1;replacement->pointers=items->pointers;
            write(list,0x10,ptr(replacement));
        }
        if(scenario=="camera_director_changed"){
            camera_director=make("UnityEngine.Playables.PlayableDirector");
            items->pointers[1]=ptr(camera_director);
        }
        if(scenario=="camera_asset_changed")camera_timeline=make("UnityEngine.Timeline.TimelineAsset");
        if(scenario=="camera_track_changed")camera_track=make(".CinemachineTrack");
        if(scenario=="brain_changed")brain=make("Cinemachine.CinemachineBrain");
        if(scenario=="unrelated_child_changed")items->pointers[2]=ptr(make("UnityEngine.Playables.PlayableDirector"));
        if(scenario=="failed_snapshot"){
            camera_track->type="Cinemachine.CinemachineTrack";
            assert(game.snapshot(snapshot)==Result::waiting);
            camera_track->type=".CinemachineTrack";
        }
        const bool changed=scenario=="list_version_changed"||scenario=="list_array_changed"
            ||scenario=="camera_director_changed"||scenario=="camera_asset_changed"
            ||scenario=="camera_track_changed"||scenario=="brain_changed"
            ||scenario=="unrelated_child_changed"||scenario=="failed_snapshot";
        if(changed){
            assert(game.begin_manual()==Result::stale&&mode==0&&time_value==13.25);
            assert(bgm_volume==.6f&&voice_volume==.4f);
            game.reset_observations();assert(handles.empty());return 0;
        }
        assert(game.begin_manual()==Result::ok&&game.evaluate(2)==Result::ok);
        if(scenario=="camera_child_reused_during_manual"){
            camera_timeline=make("UnityEngine.Timeline.TimelineAsset");
            time_value=7;mode=2;bgm_volume=.2f;voice_volume=.8f;
            assert(game.restore()==Result::ok&&time_value==7&&mode==2);
            assert(bgm_volume==.2f&&voice_volume==.8f);
        }else assert(game.restore()==Result::ok&&time_value==13.25&&mode==0);
    }
    game.reset_observations();assert(handles.empty());
}
'''


@pytest.fixture(scope="module")
def nested_adapter(tmp_path_factory):
    compiler = shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        pytest.skip("C++ compiler unavailable")
    root = tmp_path_factory.mktemp("mp4-nested-camera-adapter")
    source, binary = root / "adapter.cpp", root / "adapter"
    source.write_text(_nested_source())
    compile_ = subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
        "-I", str(ROOT / "client-presentation/native"), str(source), "-o", str(binary)],
        capture_output=True, text=True, timeout=30)
    assert compile_.returncode == 0, compile_.stderr
    return binary


@pytest.mark.parametrize("scenario", ["out_game", "photography", "unowned",
    "list_version_changed", "list_array_changed", "camera_director_changed",
    "camera_asset_changed", "camera_track_changed", "brain_changed",
    "unrelated_child_changed", "failed_snapshot", "camera_child_reused_during_manual"])
def test_nested_camera_adapter(nested_adapter, scenario):
    result = subprocess.run([str(nested_adapter), scenario], capture_output=True,
        text=True, timeout=10)
    assert result.returncode == 0, result.stderr
