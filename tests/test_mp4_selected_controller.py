"""Run the production selected-controller block with real camera helpers.

The managed heap, Unity API and collector are synthetic. This proves exact
timeline-camera scope and the temporary-root handoff, not device rendering.
"""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "client-presentation/native"

HARNESS = r'''
#include "mp4_game_adapter.hpp"
#include "mp4_camera_owner.hpp"
#include <array>
#include <cassert>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>
namespace mp4game=idoly_mp4_game;
struct Object {
    alignas(16) std::array<uint8_t,256> fields{};std::string type;
    std::vector<void*> items,edges;bool native_alive=true,gc_alive=true,marked=false,active=true;
};
std::vector<std::unique_ptr<Object>> heap;std::map<void*,Object*> objects;
std::map<void*,void*> assets,tracks,bindings,outputs,controller_cameras;
std::map<uint32_t,void*> handles;std::vector<void*> external_roots;
uint32_t serial=0,mp4_controller_type_handle=0,temporary_result=0,adopted=0;
unsigned retain_calls=0,fail_retain=0,component_calls=0,singleton_calls=0,remember_calls=0,adoption_calls=0;
bool stress_gc=false,must_adopt=false,lookup_throws=false;void* component_result=nullptr;
void* selected_camera=nullptr;void* controller_type=nullptr;void* singleton=nullptr;
void* make(const char* type){auto o=std::make_unique<Object>();o->type=type;void* p=o->fields.data();objects[p]=o.get();heap.push_back(std::move(o));return p;}
template<class T>void write(void* p,size_t offset,T value){std::memcpy(static_cast<uint8_t*>(p)+offset,&value,sizeof value);}
template<class T>T read(void* p,size_t offset){T value{};if(p)std::memcpy(&value,static_cast<uint8_t*>(p)+offset,sizeof value);return value;}
void edge(void* owner,void* value){if(value)objects.at(owner)->edges.push_back(value);}
void mark(void* p){if(!p||!objects.count(p))return;auto* o=objects.at(p);if(!o->gc_alive||o->marked)return;o->marked=true;for(void* e:o->edges)mark(e);for(void* e:o->items)mark(e);}
void collect(){if(!stress_gc||!component_calls)return;for(auto& pair:objects)pair.second->marked=false;for(void* p:external_roots)mark(p);for(auto& h:handles)mark(h.second);for(auto& pair:objects)if(!pair.second->marked)pair.second->gc_alive=false;}
bool mp4_type_is(void* p,const char* type){return p&&objects.count(p)&&objects.at(p)->gc_alive&&objects.at(p)->type==type;}
bool mp4_alive(void* p){
    if(!p||!objects.count(p))return false;const auto& o=*objects.at(p);
    assert(o.type!="System.Type"&&o.type!="System.Collections.Generic.List`1"
        &&o.type!="Solis.Photography.Data.PhotographyLiveTransitionData");
    return o.gc_alive&&o.native_alive;
}
uint32_t mp4_retain(void* p){++retain_calls;if(retain_calls==fail_retain)return 0;assert(p&&objects.at(p)->gc_alive);handles[++serial]=p;
    if(component_calls&&p==component_result&&!temporary_result)temporary_result=serial;return serial;}
void* weak_get(uint32_t handle){auto found=handles.find(handle);return found==handles.end()?nullptr:found->second;}
void weak_free(uint32_t handle){
    if(handle==temporary_result&&must_adopt)assert(adopted&&adopted!=handle&&weak_get(adopted)==component_result);
    assert(handles.erase(handle)==1);
}
struct Weak {void* value=nullptr;void* get(bool native=false)const{return value&&(!native||mp4_alive(value))?value:nullptr;}};
Weak main_controller;std::array<Weak,4> controller_candidates{};
void* rt_camera(void* p,const void*){assert(mp4_type_is(p,"VL.Rendering.VLSRPCameraController"));collect();assert(objects.at(p)->gc_alive);return controller_cameras[p];}
void remember_controller(void* p){++remember_calls;assert(mp4_alive(p));controller_candidates[3].value=p;collect();assert(mp4_alive(p));}
void* mp4_original_current_controller(){++singleton_calls;return singleton;}
void* component(void* receiver,void* type,const void* method){
    ++component_calls;assert(receiver==selected_camera&&type==controller_type&&!method);
    // Model the original return being live until its immediate handle takes
    // over. Later collection must depend on the helper's result root.
    edge(receiver,component_result);collect();assert(mp4_alive(receiver)&&mp4_type_is(type,"System.Type"));
    if(component_result)objects.at(receiver)->edges.pop_back();
    if(lookup_throws)throw std::runtime_error("synthetic lookup exception");return component_result;
}
uintptr_t image_base=reinterpret_cast<uintptr_t>(&component);
struct OwnerProfile {struct{uintptr_t rva=0;}component_get_component;}mp4_camera_owner_profile;
namespace idoly_mp4_runtime {
struct Probe {std::string error="not_called",source="none";idoly_mp4_timeline_camera::Counters counts{};uint32_t candidates=0;}probe;
void observe_controller_discovery(const char* error,const char* source,const idoly_mp4_timeline_camera::Counters& counts,uint32_t candidates){probe={error,source,counts,candidates};}
void observe_camera_controller(void* p){
    ++adoption_calls;assert(temporary_result&&weak_get(temporary_result)==p);collect();assert(mp4_alive(p));
    adopted=mp4_retain(p);assert(adopted);collect();assert(mp4_alive(p));
}
}
size_t array_length(void* p){return objects.at(p)->items.size();}
void* array_data(void* p){return objects.at(p)->items.empty()?nullptr:objects.at(p)->items.data();}
void* get_asset(void* p,void*){return assets[p];}
void* get_tracks(void* p,void*){return tracks[p];}
void* binding(void* owner,void* track,void*){return bindings[owner]==track?outputs[track]:nullptr;}
unsigned camera_queries=0;bool change_camera=false;
void* camera_output(void* brain,void*){++camera_queries;return change_camera&&camera_queries>1?outputs[nullptr]:outputs[brain];}
bool active_enabled(void* p,void*){return objects.at(p)->active;}
unsigned mode_queries=0;
bool is_mv(void* mode,void*){++mode_queries;return read<uint8_t>(read<void*>(mode,0x30),0x28)!=0;}
mp4game::Api mp4_api;
void* array(const char* type,std::vector<void*> values){void* p=make(type);objects.at(p)->items=std::move(values);return p;}
void set_tracks(void* director,std::vector<void*> values){void* asset=make("UnityEngine.Timeline.TimelineAsset");assets[director]=asset;tracks[asset]=array("UnityEngine.Timeline.TrackAsset[]",std::move(values));edge(director,asset);edge(asset,tracks[asset]);}
@@PRODUCTION@@
int main(int argc,char** argv){
    assert(argc==2);std::string scenario=argv[1];
    void* root=make("Solis.Photography.PhotographyLivePresenter");void* mode=make("Solis.Photography.PhotographyLiveModePresenter");
    void* data=make("Solis.Photography.Data.PhotographyLiveTransitionData");void* player=make("Solis.Common.Photography.PhotographyLive3DPresenter");
    void* timeline=make("Solis.Common.Live.SolisLiveTimelineController");void* master=make("UnityEngine.Playables.PlayableDirector");
    void* child=make("UnityEngine.Playables.PlayableDirector");void* extra=make("UnityEngine.Playables.PlayableDirector");
    void* brain=make("Cinemachine.CinemachineBrain");selected_camera=make("UnityEngine.Camera");void* other_camera=make("UnityEngine.Camera");
    void* camera_track=make(".CinemachineTrack");outputs[brain]=selected_camera;outputs[camera_track]=brain;bindings[child]=camera_track;
    edge(child,brain);edge(brain,selected_camera);std::vector<void*> controls;for(unsigned i=0;i<9;++i)controls.push_back(make("UnityEngine.Timeline.ControlTrack"));
    set_tracks(master,controls);set_tracks(child,{camera_track});
    void* list=make("System.Collections.Generic.List`1");void* directors=array("UnityEngine.Playables.PlayableDirector[]",{master,child,master});
    write(list,0x10,directors);write(list,0x18,int32_t(3));write(timeline,0x20,master);write(timeline,0x28,list);
    edge(timeline,master);edge(timeline,list);edge(list,directors);write(root,0x30,mode);write(mode,0x20,player);write(mode,0x30,data);write(player,0x70,true);write(player,0x38,timeline);
    edge(root,mode);edge(mode,player);edge(mode,data);edge(player,timeline);external_roots={root};
    void* controller=make("VL.Rendering.VLSRPCameraController");void* wrong_controller=make("VL.Rendering.VLSRPCameraController");controller_cameras[controller]=selected_camera;controller_cameras[wrong_controller]=other_camera;
    edge(controller,selected_camera);edge(wrong_controller,other_camera);external_roots.push_back(wrong_controller);controller_type=make("System.Type");mp4_controller_type_handle=mp4_retain(controller_type);retain_calls=0;
    mp4_api.is_type=mp4_type_is;mp4_api.alive=mp4_alive;mp4_api.array_length=array_length;mp4_api.array_data=array_data;mp4_api.director_get_asset=get_asset;
    mp4_api.timeline_get_tracks=get_tracks;mp4_api.director_get_binding=binding;mp4_api.brain_output_camera=camera_output;mp4_api.active_enabled=active_enabled;mp4_api.photo_mode_is_mv=is_mv;
    main_controller.value=wrong_controller;controller_candidates[0].value=wrong_controller;singleton=wrong_controller;component_result=controller;
    if(scenario=="main"||scenario=="normal_main"){main_controller.value=controller;external_roots.push_back(controller);}
    if(scenario=="normal_main"){objects.at(root)->type="Solis.OutGame.LivePlayerScreenPresenter";objects.at(player)->type="Solis.Common.SolisLivePlayer";write(root,0xe0,player);edge(root,player);}
    if(scenario=="candidate"){controller_candidates[1].value=controller;external_roots.push_back(controller);}
    if(scenario=="singleton"){singleton=controller;external_roots.push_back(controller);}
    if(scenario=="empty_child"){assets[extra]=nullptr;objects.at(directors)->items.push_back(extra);write(list,0x18,int32_t(4));}
    if(scenario=="null_mode")write(root,0x30,static_cast<void*>(nullptr));
    if(scenario=="null_data")write(mode,0x30,static_cast<void*>(nullptr));
    if(scenario=="wrong_data")objects.at(data)->type="System.String";
    if(scenario=="video")write(data,0x28,uint8_t(1));
    if(scenario=="root_inactive")objects.at(root)->active=false;
    if(scenario=="mode_inactive")objects.at(mode)->active=false;
    if(scenario=="unbuilt")write(player,0x70,false);
    if(scenario=="360")objects.at(player)->type="Solis.Common.Photography.Photography360Live3DPresenter";
    if(scenario=="wrong_root")objects.at(root)->type="Other.Presenter";
    if(scenario=="dead_player")objects.at(player)->native_alive=false;
    if(scenario=="unowned_camera"){objects.at(directors)->items={master};write(list,0x18,int32_t(1));}
    if(scenario=="unbound_camera")bindings.erase(child);
    if(scenario=="wrong_camera")outputs[brain]=make("UnityEngine.GameObject");
    if(scenario=="multiple_brains"||scenario=="changing_camera"){
        void* track=make(".CinemachineTrack");void* other_brain=scenario=="changing_camera"?brain:make("Cinemachine.CinemachineBrain");
        set_tracks(extra,{track});bindings[extra]=track;outputs[track]=other_brain;outputs[other_brain]=selected_camera;edge(extra,other_brain);
        objects.at(directors)->items.push_back(extra);write(list,0x18,int32_t(4));change_camera=scenario=="changing_camera";outputs[nullptr]=other_camera;
    }
    if(scenario=="component_absent")component_result=nullptr;
    if(scenario=="component_wrong_type")objects.at(controller)->type="Other.Component";
    if(scenario=="component_wrong_camera")controller_cameras[controller]=other_camera;
    if(scenario=="lookup_throws")lookup_throws=true;
    if(scenario=="camera_handle_failed")fail_retain=1;
    if(scenario=="type_handle_failed")fail_retain=2;
    if(scenario=="result_handle_failed")fail_retain=3;
    if(scenario=="controller_type_missing"){weak_free(mp4_controller_type_handle);mp4_controller_type_handle=0;}
    const std::map<std::string,std::string> errors={
        {"null_mode","selected_photography_mode_not_loaded"},{"null_data","selected_photography_data_not_loaded"},{"wrong_data","selected_photography_data_not_loaded"},
        {"video","selected_video_mv_unsupported"},{"root_inactive","selected_presenter_inactive"},{"mode_inactive","selected_photography_mode_not_loaded"},
        {"unbuilt","selected_photography_3d_not_built"},{"360","selected_photography_3d_not_built"},{"wrong_root","selected_presenter_missing"},{"dead_player","selected_photography_3d_not_built"},
        {"unowned_camera","selected_camera_track_not_found"},{"unbound_camera","selected_camera_binding_not_ready"},{"wrong_camera","selected_output_camera_not_ready"},
        {"multiple_brains","ambiguous_selected_brains"},{"changing_camera","ambiguous_selected_cameras"},
        {"component_absent","selected_camera_controller_absent"},{"component_wrong_type","selected_camera_controller_wrong_type"},{"component_wrong_camera","selected_camera_controller_camera_mismatch"},
        {"lookup_throws","selected_camera_controller_lookup_exception"},{"camera_handle_failed","selected_camera_handle_failed"},{"type_handle_failed","selected_controller_type_handle_failed"},{"result_handle_failed","selected_camera_controller_handle_failed"},{"controller_type_missing","selected_controller_type_unavailable"}};
    const bool early=errors.count(scenario)&&scenario!="component_absent"&&scenario!="component_wrong_type"&&scenario!="component_wrong_camera"&&scenario!="lookup_throws"
        &&scenario!="camera_handle_failed"&&scenario!="type_handle_failed"&&scenario!="result_handle_failed"&&scenario!="controller_type_missing";
    stress_gc=!early&&scenario!="main"&&scenario!="normal_main"&&scenario!="candidate"&&scenario!="singleton";
    must_adopt=!errors.count(scenario)&&stress_gc;
    void* result=mp4_selected_controller(root);auto& probe=idoly_mp4_runtime::probe;
    if(errors.count(scenario)){
        assert(!result&&probe.error==errors.at(scenario)&&probe.source=="none"&&!adopted);
        if(early)assert(component_calls==0&&singleton_calls==0&&probe.candidates==0);
        if(scenario=="null_data"||scenario=="wrong_data")assert(!mode_queries);
    }else{
        assert(result==controller&&probe.error=="none");
        if(scenario=="main"||scenario=="normal_main")assert(probe.source=="observed"&&probe.candidates==1&&!singleton_calls&&!component_calls);
        else if(scenario=="candidate")assert(probe.source=="observed"&&probe.candidates==3&&!singleton_calls&&!component_calls);
        else if(scenario=="singleton")assert(probe.source=="singleton"&&probe.candidates==3&&singleton_calls==1&&!component_calls&&remember_calls==1);
        else {assert(probe.source=="camera_component"&&probe.candidates==3&&component_calls==1&&adoption_calls==1&&remember_calls==1);assert(adopted&&handles.size()==2);collect();assert(mp4_alive(controller));}
        assert(probe.counts.listed_directors==(scenario=="empty_child"?4U:3U)&&probe.counts.unique_directors==(scenario=="empty_child"?3U:2U));
        assert(probe.counts.assets==2&&probe.counts.output_tracks==10&&probe.counts.camera_tracks==1&&probe.counts.null_assets==(scenario=="empty_child"?1U:0U));
    }
    if(adopted){must_adopt=false;weak_free(adopted);}if(mp4_controller_type_handle)weak_free(mp4_controller_type_handle);assert(handles.empty());
}
'''


@pytest.fixture(scope="module")
def selected_controller_binary(tmp_path_factory):
    compiler = shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        pytest.skip("C++ compiler required")
    source = (NATIVE / "bridge.cpp").read_text()
    production = source.split("// BEGIN_MP4_SELECTED_CONTROLLER",1)[1].split("// END_MP4_SELECTED_CONTROLLER",1)[0]
    work = tmp_path_factory.mktemp("mp4-selected-controller")
    cpp,binary = work / "selected.cpp",work / "selected"
    cpp.write_text(HARNESS.replace("@@PRODUCTION@@",production))
    run = subprocess.run([compiler,"-std=c++17","-O2","-Wall","-Wextra","-Werror","-Wno-misleading-indentation",
        "-I",str(NATIVE),str(cpp),"-o",str(binary)],capture_output=True,text=True,timeout=45)
    assert run.returncode == 0,run.stderr
    return binary


@pytest.mark.parametrize("scenario", ["main","normal_main","candidate","singleton","component","empty_child",
    "null_mode","null_data","wrong_data","video","root_inactive","mode_inactive","unbuilt","360","wrong_root","dead_player",
    "unowned_camera","unbound_camera","wrong_camera","multiple_brains","changing_camera","component_absent","component_wrong_type",
    "component_wrong_camera","lookup_throws","camera_handle_failed","type_handle_failed","result_handle_failed","controller_type_missing"])
def test_production_selected_controller_ownership_lifetimes_and_probe(selected_controller_binary,scenario):
    run = subprocess.run([str(selected_controller_binary),scenario],capture_output=True,text=True,timeout=5)
    assert run.returncode == 0,run.stderr
