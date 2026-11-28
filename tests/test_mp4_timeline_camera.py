"""Find cameras in the original owned multi-director timeline graph.

The cached tri-004 asset has nine master ControlTracks and a separate camera
director. These fixtures reproduce that ownership shape without claiming game
or GPU execution, and reject other scene cameras and malformed ownership lists.
"""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = r'''
#include "mp4_timeline_camera.hpp"
#include <array>
#include <cassert>
#include <cstring>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>
using namespace idoly_mp4_timeline_camera;
struct Object {
    alignas(16) std::array<uint8_t,256> fields{};
    std::string type;
    std::vector<void*> elements;
    bool alive=true;
};
std::vector<std::unique_ptr<Object>> heap;
std::map<void*,Object*> objects;
std::map<void*,void*> assets,tracks,bindings,outputs;
std::map<void*,unsigned> asset_queries;
bool throw_length=false,throw_asset=false,throw_binding=false;
void* make(const char* type){
    auto object=std::make_unique<Object>();object->type=type;
    void* value=object->fields.data();objects[value]=object.get();heap.push_back(std::move(object));return value;
}
template<class T>void write(void* object,size_t offset,T value){std::memcpy(static_cast<uint8_t*>(object)+offset,&value,sizeof value);}
bool typed(void* value,const char* type){return value&&objects.count(value)&&objects.at(value)->type==type;}
bool alive(void* value){
    assert(!typed(value,"System.Collections.Generic.List`1"));
    return value&&objects.count(value)&&objects.at(value)->alive;
}
size_t length(void* value){if(throw_length)throw std::runtime_error("synthetic");return objects.at(value)->elements.size();}
void* data(void* value){return objects.at(value)->elements.empty()?nullptr:objects.at(value)->elements.data();}
void* asset(void* value,Method*){if(throw_asset)throw std::runtime_error("synthetic");++asset_queries[value];return assets[value];}
void* get_tracks(void* value,Method*){return tracks[value];}
void* binding(void* director,void* track,Method*){
    if(throw_binding)throw std::runtime_error("synthetic");
    // Both key and owning director must be correct. Looking up child tracks
    // against the master cannot accidentally succeed in this fixture.
    return bindings.count(director)&&bindings.at(director)==track?outputs[track]:nullptr;
}
void* camera(void* brain,Method*){return outputs[brain];}
void* array(const char* type,std::vector<void*> values){void* result=make(type);objects[result]->elements=std::move(values);return result;}
void set_tracks(void* director,std::vector<void*> values){
    void* timeline=make("UnityEngine.Timeline.TimelineAsset");assets[director]=timeline;
    tracks[timeline]=array("UnityEngine.Timeline.TrackAsset[]",std::move(values));
}
int main(int argc,char**argv){
    assert(argc==2);const std::string scenario=argv[1];
    void* owner=make("Solis.Common.Live.SolisLiveTimelineController");
    void* master=make("UnityEngine.Playables.PlayableDirector");
    void* child=make("UnityEngine.Playables.PlayableDirector");
    void* extra=make("UnityEngine.Playables.PlayableDirector");
    void* brain=make("Cinemachine.CinemachineBrain");void* output=make("UnityEngine.Camera");
    void* camera_track=make(".CinemachineTrack");outputs[brain]=output;
    std::vector<void*> controls;for(unsigned i=0;i<9;++i)controls.push_back(make("UnityEngine.Timeline.ControlTrack"));
    set_tracks(master,controls);set_tracks(child,{camera_track});bindings[child]=camera_track;outputs[camera_track]=brain;
    void* list=make("System.Collections.Generic.List`1");
    void* items=array("UnityEngine.Playables.PlayableDirector[]",{master,child,master});
    write(list,0x10,items);write(list,0x18,int32_t(3));write(owner,0x20,master);write(owner,0x28,list);
    Api api{typed,alive,length,data,asset,get_tracks,binding,camera};
    const auto append=[&](void* value){objects[items]->elements.push_back(value);write(list,0x18,int32_t(objects[items]->elements.size()));};
    if(scenario=="master_only"){set_tracks(master,{camera_track});bindings[master]=camera_track;objects[items]->elements={};write(list,0x18,int32_t(0));}
    if(scenario=="empty_child"){assets[extra]=nullptr;append(extra);}
    if(scenario=="same_brain_multiple_directors"){set_tracks(extra,{camera_track});bindings[extra]=camera_track;append(extra);}
    if(scenario=="unowned_camera"){objects[items]->elements={master};write(list,0x18,int32_t(1));}
    if(scenario=="wrong_namespace")objects[camera_track]->type="Cinemachine.CinemachineTrack";
    if(scenario=="null_list")write(owner,0x28,static_cast<void*>(nullptr));
    if(scenario=="wrong_list")objects[list]->type="System.Collections.Generic.Dictionary`2";
    if(scenario=="wrong_backing_array")objects[items]->type="System.Object[]";
    if(scenario=="negative_count")write(list,0x18,int32_t(-1));
    if(scenario=="too_many_directors")write(list,0x18,int32_t(max_directors+1));
    if(scenario=="short_backing_array")write(list,0x18,int32_t(4));
    if(scenario=="huge_backing_array")objects[items]->elements.resize(max_directors+1,nullptr);
    if(scenario=="null_director")objects[items]->elements[1]=nullptr;
    if(scenario=="wrong_director")objects[child]->type="UnityEngine.Camera";
    if(scenario=="destroyed_director")objects[child]->alive=false;
    if(scenario=="null_master")write(owner,0x20,static_cast<void*>(nullptr));
    if(scenario=="null_master_asset")assets[master]=nullptr;
    if(scenario=="unsupported_child_asset")objects[assets[child]]->type="UnityEngine.AnimationClip";
    if(scenario=="wrong_track_array")objects[tracks[assets[child]]]->type="System.Object[]";
    if(scenario=="too_many_tracks")objects[tracks[assets[child]]]->elements.resize(max_tracks_per_director+1,camera_track);
    if(scenario=="missing_binding")bindings.erase(child);
    if(scenario=="game_object_binding")outputs[camera_track]=make("UnityEngine.GameObject");
    if(scenario=="dead_brain")objects[brain]->alive=false;
    if(scenario=="missing_output")outputs[brain]=nullptr;
    if(scenario=="wrong_output")outputs[brain]=make("UnityEngine.GameObject");
    if(scenario=="ambiguous_brains"){
        void* other_track=make(".CinemachineTrack");void* other_brain=make("Cinemachine.CinemachineBrain");
        set_tracks(extra,{other_track});bindings[extra]=other_track;outputs[other_track]=other_brain;outputs[other_brain]=output;append(extra);
    }
    throw_length=scenario=="throw_owned_query";
    throw_asset=scenario=="throw_asset_query";
    throw_binding=scenario=="throw_binding_query";
    const std::map<std::string,std::string> errors={
        {"unowned_camera","selected_camera_track_not_found"},{"wrong_namespace","selected_camera_track_not_found"},
        {"null_list","selected_owned_directors_list_invalid"},{"wrong_list","selected_owned_directors_list_invalid"},
        {"wrong_backing_array","selected_owned_directors_array_invalid"},{"negative_count","selected_owned_directors_out_of_bounds"},
        {"too_many_directors","selected_owned_directors_out_of_bounds"},{"short_backing_array","selected_owned_directors_array_out_of_bounds"},
        {"huge_backing_array","selected_owned_directors_array_out_of_bounds"},{"null_director","selected_owned_director_not_loaded"},
        {"wrong_director","selected_owned_director_not_loaded"},{"destroyed_director","selected_owned_director_not_loaded"},
        {"null_master","selected_director_not_loaded"},{"null_master_asset","selected_master_timeline_not_loaded"},
        {"unsupported_child_asset","selected_owned_timeline_unsupported"},{"wrong_track_array","selected_owned_track_array_invalid"},
        {"too_many_tracks","selected_owned_tracks_out_of_bounds"},{"missing_binding","selected_camera_binding_not_ready"},
        {"game_object_binding","selected_camera_binding_not_ready"},{"dead_brain","selected_camera_binding_not_ready"},
        {"missing_output","selected_output_camera_not_ready"},{"wrong_output","selected_output_camera_not_ready"},
        {"ambiguous_brains","ambiguous_selected_brains"},
        {"throw_owned_query","selected_owned_directors_query_exception"},
        {"throw_asset_query","selected_camera_scan_exception"},
        {"throw_binding_query","selected_camera_scan_exception"}};
    const auto result=scan(owner,api);
    if(auto expected=errors.find(scenario);expected!=errors.end()){
        assert(!result.ok()&&result.error==expected->second);return 0;
    }
    assert(result.ok()&&result.camera==output&&result.brain==brain);
    assert(result.camera_director==(scenario=="master_only"?master:child));
    assert(asset_queries[master]==1); // Master appearing twice in the list is deduplicated.
    if(scenario=="nested")assert(result.counts.unique_directors==2&&result.counts.output_tracks==10&&result.counts.camera_tracks==1);
    if(scenario=="empty_child")assert(result.counts.null_assets==1);
    if(scenario=="same_brain_multiple_directors")assert(result.counts.camera_tracks==2);
}
'''


@pytest.fixture(scope="module")
def camera_scan(tmp_path_factory):
    compiler = shutil.which("c++") or shutil.which("g++")
    if not compiler:
        pytest.skip("C++ compiler required")
    root = tmp_path_factory.mktemp("mp4-timeline-camera")
    source, binary = root / "scan.cpp", root / "scan"
    source.write_text(SOURCE)
    subprocess.run([compiler, "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror",
                    "-I", str(ROOT / "client-presentation/native"), str(source), "-o", str(binary)], check=True)
    return binary


@pytest.mark.parametrize("scenario", [
    "nested", "master_only", "empty_child", "same_brain_multiple_directors",
    "unowned_camera", "wrong_namespace", "null_list", "wrong_list", "wrong_backing_array",
    "negative_count", "too_many_directors", "short_backing_array", "huge_backing_array",
    "null_director", "wrong_director", "destroyed_director", "null_master", "null_master_asset",
    "unsupported_child_asset", "wrong_track_array", "too_many_tracks", "missing_binding",
    "game_object_binding", "dead_brain", "missing_output", "wrong_output", "ambiguous_brains",
    "throw_owned_query", "throw_asset_query", "throw_binding_query",
])
def test_only_original_owned_directors_can_supply_the_unique_camera(camera_scan, scenario):
    subprocess.run([str(camera_scan), scenario], check=True)
