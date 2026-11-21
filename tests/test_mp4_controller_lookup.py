"""Run the actual bridge controller lookup against owned, typed fake objects."""
from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "client-presentation/native/bridge.cpp"
PROFILE = ROOT / "client-presentation/native/mp4_controller_profile.hpp"


def _function(source: str, signature: str) -> str:
    """Keep the production body, including nested scopes, without copying it."""
    start = source.index(signature)
    begin = source.index("{", start)
    depth, state, index = 0, "code", begin
    while index < len(source):
        char = source[index]
        nxt = source[index + 1:index + 2]
        if state == "line":
            if char == "\n":
                state = "code"
        elif state == "block":
            if char == "*" and nxt == "/":
                state = "code"
                index += 1
        elif state in ("string", "char"):
            if char == "\\":
                index += 1
            elif char == ('"' if state == "string" else "'"):
                state = "code"
        elif char == "/" and nxt in ("/", "*"):
            state = "line" if nxt == "/" else "block"
            index += 1
        elif char in ('"', "'"):
            state = "string" if char == '"' else "char"
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
        index += 1
    raise AssertionError("Unclosed production function: " + signature)


def test_controller_profile_header_matches_original_proof():
    source = PROFILE.read_text()
    evidence = json.loads(PROFILE.with_suffix(".json").read_text())
    game = json.loads(PROFILE.with_name("mp4_game_profile.json").read_text())
    ios_game = json.loads(PROFILE.with_name("mp4_game_ios_profile.json").read_text())
    for platform, original in (("android", game), ("ios", ios_game)):
        proof = evidence["platforms"][platform]
        assert proof["native_sha256"] == original["sources"]["native_sha256"]
        assert proof["metadata_sha256"] == original["sources"]["metadata_sha256"]
        body = source.split(platform + "_controller_profile = {", 1)[1].split("};", 1)[0]
        bindings = re.findall(r"\{\s*(0x[0-9a-f]+),\s*\{([^}]+)\}\s*\}", body)
        assert len(bindings) == 3
        for (address, prefix), name in zip(bindings, ("has", "get", "resolve"), strict=True):
            assert int(address, 16) == int(proof["locations"][name], 16)
            assert bytes(int(x, 16) for x in re.findall(r"0x[0-9a-f]+", prefix)).hex() == proof["prefixes"][name]
        tail = body[body.rindex("}") + 1:]
        slots = [int(x, 16) for x in re.findall(r"0x[0-9a-f]+", tail)]
        assert len(slots) == 4
        assert slots[:2] == [int(proof["locations"][name], 16) for name in ("has_slot", "get_slot")]
        assert ("true" in tail) is (platform == "android")
        expected_cells = ([int(proof["slot_file_words"][name], 16) for name in ("has_slot", "get_slot")]
                          if platform == "android" else slots[:2])
        assert slots[2:] == expected_cells


HARNESS = r"""
#include <cassert>
#include <cstdint>
#include <cstring>
#include <string>
#include <unordered_map>
#include <vector>
#include <cstdio>
using Method=void;
struct Binding {uintptr_t rva=0;uint8_t prefix[16]{};};
struct ControllerProfile {Binding has_instance,instance,metadata_initialize;uintptr_t has_slot=0,instance_slot=0,has_cell=0,instance_cell=0;bool indirect_slots=false;};
struct RuntimeProfile {Binding camera_status_try_get,array_new,string_new,type_get_object,single_type,audio_clip_type,texture2d_type;};
struct ReplayProfile {Binding actor_descriptor_type,out_game_param_type,transition_param_type;};
uintptr_t image_base=0;
bool mp4_source_verified=false,mp4_replay_verified=false,on_unity=true,resolve_cells=true,has_existing=true;
uintptr_t has_cell=1,instance_cell=3,has_outer=0,instance_outer=0;
alignas(16) uint64_t has_info[2]{},instance_info[2]{};
int initialized=0,has_calls=0,instance_calls=0,cached=0;
std::vector<std::string> events;
uintptr_t rejected_mapping=0,rejected_binding=0;
ControllerProfile mp4_controller_profile;
RuntimeProfile mp4_runtime_profile;
ReplayProfile mp4_replay_profile;
Binding mp4_bindings[1];
alignas(16) unsigned char replay_bytes[16]{};
Binding mp4_replay_bindings[1];
void*(*mp4_array_new)(void*,uintptr_t)=nullptr;
void*(*mp4_string_new)(const char*)=nullptr;
void*(*mp4_type_get_object)(const void*)=nullptr;

bool game_call(){return on_unity;}
bool mp4_mapped(uintptr_t address,size_t,bool){return address!=rejected_mapping;}
bool mp4_prefix(const Binding& b,bool=true){return b.rva!=rejected_binding;}
bool mp4_hook_was_statically_verified(const Binding&){return false;}
template<class T>T read(void* p,size_t offset){T value{};if(p)std::memcpy(&value,static_cast<uint8_t*>(p)+offset,sizeof(value));return value;}
struct Object {alignas(16) uint8_t storage[512]{};};
struct Info {std::string type;bool alive=true;void* camera=nullptr;};
std::unordered_map<void*,Info> objects;
Object presenter,player,timeline,director,asset,track,track_other,brain,brain_other,camera,other_camera,controller,other_controller;
void* ptr(Object& object){return object.storage;}
void typed(Object& object,const char* type){objects[ptr(object)]={type,true,nullptr};}
template<class T>void field(Object& object,size_t offset,T value){std::memcpy(object.storage+offset,&value,sizeof(value));}
bool mp4_type_is(void* p,const char* type){auto it=objects.find(p);return it!=objects.end()&&it->second.type==type;}
bool mp4_alive(void* p){auto it=objects.find(p);return it!=objects.end()&&it->second.alive;}
void* existing_controller=nullptr;
void fake_initialize(uintptr_t* cell){
    assert(cell==&has_cell||cell==&instance_cell);++initialized;
    events.push_back(cell==&has_cell?"init_has":"init_instance");
    if(resolve_cells)*cell=reinterpret_cast<uintptr_t>(cell==&has_cell?has_info:instance_info);
}
bool fake_has(const Method* info){
    assert(info==reinterpret_cast<Method*>(has_info));
    assert(has_cell==reinterpret_cast<uintptr_t>(has_info)&&instance_cell==reinterpret_cast<uintptr_t>(instance_info));
    assert(events.size()>=2&&events[events.size()-2]=="init_has"&&events.back()=="init_instance");
    events.push_back("has");++has_calls;return has_existing;
}
void* fake_instance(const Method* info){
    assert(info==reinterpret_cast<Method*>(instance_info)&&has_existing);
    assert(!events.empty()&&events.back()=="has");events.push_back("instance");++instance_calls;return existing_controller;
}
struct Weak {void* value=nullptr;void* get(bool unity=false)const{return value&&(!unity||mp4_alive(value))?value:nullptr;}void set(void* p){value=p;}};
Weak main_controller,controller_candidates[4];
unsigned candidate_cursor=0;
void* rt_camera(void* p,Method*){return objects.at(p).camera;}
struct Array {std::vector<void*> entries;};
Array tracks;
size_t mp4_array_length(void* p){return p?static_cast<Array*>(p)->entries.size():0;}
void* mp4_array_data(void* p){return p?static_cast<Array*>(p)->entries.data():nullptr;}
void* get_asset(void* p,Method*){assert(p==ptr(director));return ptr(asset);}
void* get_tracks(void* p,Method*){assert(p==ptr(asset));return &tracks;}
void* get_binding(void* p,void* t,Method*){assert(p==ptr(director)&&mp4_type_is(t,".CinemachineTrack"));return t==ptr(track_other)?ptr(brain_other):ptr(brain);}
void* get_camera(void* p,Method*){assert(p==ptr(brain)||p==ptr(brain_other));return objects.at(p).camera;}
struct Api {void*(*director_get_asset)(void*,Method*);void*(*timeline_get_tracks)(void*,Method*);void*(*director_get_binding)(void*,void*,Method*);void*(*brain_output_camera)(void*,Method*);};
Api mp4_api{get_asset,get_tracks,get_binding,get_camera};

// Actual source functions are injected below this line.
@@PRODUCTION@@

void reset(bool indirect=true){
    events.clear();initialized=has_calls=instance_calls=cached=0;
    mp4_source_verified=true;mp4_replay_verified=false;on_unity=resolve_cells=has_existing=true;
    has_cell=1;instance_cell=3;rejected_mapping=rejected_binding=0;
    has_outer=reinterpret_cast<uintptr_t>(&has_cell);instance_outer=reinterpret_cast<uintptr_t>(&instance_cell);
    mp4_controller_profile={};
    mp4_controller_profile.has_instance.rva=reinterpret_cast<uintptr_t>(&fake_has);
    mp4_controller_profile.instance.rva=reinterpret_cast<uintptr_t>(&fake_instance);
    mp4_controller_profile.metadata_initialize.rva=reinterpret_cast<uintptr_t>(&fake_initialize);
    mp4_controller_profile.has_cell=reinterpret_cast<uintptr_t>(&has_cell);
    mp4_controller_profile.instance_cell=reinterpret_cast<uintptr_t>(&instance_cell);
    mp4_controller_profile.has_slot=reinterpret_cast<uintptr_t>(indirect?&has_outer:&has_cell);
    mp4_controller_profile.instance_slot=reinterpret_cast<uintptr_t>(indirect?&instance_outer:&instance_cell);
    mp4_controller_profile.indirect_slots=indirect;
    mp4_bindings[0].rva=7;
    mp4_runtime_profile={};
    Binding* bindings[]={&mp4_runtime_profile.camera_status_try_get,&mp4_runtime_profile.array_new,&mp4_runtime_profile.string_new,&mp4_runtime_profile.type_get_object,&mp4_runtime_profile.single_type,&mp4_runtime_profile.audio_clip_type,&mp4_runtime_profile.texture2d_type};
    for(size_t i=0;i<7;++i)bindings[i]->rva=10+i;
    mp4_replay_bindings[0].rva=reinterpret_cast<uintptr_t>(replay_bytes);
    mp4_replay_profile={};
    objects.clear();
    typed(presenter,"Solis.OutGame.LivePlayerScreenPresenter");typed(player,"Solis.Common.SolisLivePlayer");
    typed(timeline,"Solis.Common.Live.SolisLiveTimelineController");typed(director,"UnityEngine.Playables.PlayableDirector");
    typed(asset,"UnityEngine.Timeline.TimelineAsset");typed(track,".CinemachineTrack");typed(track_other,".CinemachineTrack");typed(brain,"Cinemachine.CinemachineBrain");typed(brain_other,"Cinemachine.CinemachineBrain");
    typed(camera,"UnityEngine.Camera");typed(other_camera,"UnityEngine.Camera");
    typed(controller,"VL.Rendering.VLSRPCameraController");typed(other_controller,"VL.Rendering.VLSRPCameraController");
    field(presenter,0xe0,ptr(player));field(player,0x38,ptr(timeline));field(timeline,0x20,ptr(director));
    objects.at(ptr(brain)).camera=ptr(camera);objects.at(ptr(brain_other)).camera=ptr(other_camera);objects.at(ptr(controller)).camera=ptr(camera);
    objects.at(ptr(other_controller)).camera=ptr(other_camera);existing_controller=ptr(controller);
    main_controller.value=nullptr;for(auto& candidate:controller_candidates)candidate.value=nullptr;candidate_cursor=0;
    tracks.entries={ptr(track)};
}
int main(int argc,char** argv){
    assert(argc==2);std::string test=argv[1];reset();
    if(test=="verified_existing"){
        assert(mp4_original_current_controller()==ptr(controller));assert(initialized==2&&has_calls==1&&instance_calls==1);
    }else if(test=="unverified"||test=="wrong_thread"){
        if(test=="unverified")mp4_source_verified=false;else on_unity=false;
        assert(mp4_original_current_controller()==nullptr&&initialized==0&&has_calls==0&&instance_calls==0);
    }else if(test=="unresolved"||test=="zero_has"||test=="zero_instance"||test=="tagged_has"||test=="tagged_instance"){
        resolve_cells=false;
        if(test=="zero_has"||test=="tagged_has"){has_cell=test=="zero_has"?0:1;instance_cell=reinterpret_cast<uintptr_t>(instance_info);}
        if(test=="zero_instance"||test=="tagged_instance"){instance_cell=test=="zero_instance"?0:3;has_cell=reinterpret_cast<uintptr_t>(has_info);}
        assert(mp4_original_current_controller()==nullptr&&initialized==2&&has_calls==0&&instance_calls==0);
    }else if(test=="has_false"){
        has_existing=false;assert(mp4_original_current_controller()==nullptr&&has_calls==1&&instance_calls==0);
    }else if(test=="wrong_class"||test=="dead"){
        if(test=="wrong_class")objects.at(ptr(controller)).type="Other.Controller";else objects.at(ptr(controller)).alive=false;
        assert(mp4_original_current_controller()==nullptr&&instance_calls==1);
    }else if(test=="cold_fallback"){
        assert(mp4_selected_controller(ptr(presenter))==ptr(controller));
        assert(initialized==2&&instance_calls==1&&controller_candidates[0].value==ptr(controller));
        assert(mp4_selected_controller(ptr(presenter))==ptr(controller)&&instance_calls==1);
    }else if(test=="main_current"||test=="candidate_current"){
        if(test=="main_current")main_controller.value=ptr(controller);else controller_candidates[2].value=ptr(controller);
        assert(mp4_selected_controller(ptr(presenter))==ptr(controller)&&initialized==0);
    }else if(test=="wrong_cached_camera"){
        main_controller.value=ptr(other_controller);controller_candidates[0].value=ptr(other_controller);
        assert(mp4_selected_controller(ptr(presenter))==ptr(controller)&&instance_calls==1);
        assert(controller_candidates[1].value==ptr(controller));
    }else if(test=="wrong_original_camera"){
        existing_controller=ptr(other_controller);
        assert(mp4_selected_controller(ptr(presenter))==nullptr&&instance_calls==1);
        for(auto& candidate:controller_candidates)assert(candidate.value==nullptr);
    }else if(test=="camera_changed_after_cache"){
        assert(mp4_selected_controller(ptr(presenter))==ptr(controller));
        objects.at(ptr(brain)).camera=ptr(other_camera);
        assert(mp4_selected_controller(ptr(presenter))==nullptr&&instance_calls==2);
    }else if(test=="ambiguous_timeline_cameras"){
        tracks.entries={ptr(track),ptr(track_other)};assert(mp4_selected_controller(ptr(presenter))==nullptr&&initialized==0);
    }else if(test=="no_camera_track"){
        tracks.entries.clear();assert(mp4_selected_controller(ptr(presenter))==nullptr&&initialized==0);
    }else if(test=="invalid_presenter"||test=="dead_player"||test=="invalid_timeline"||test=="dead_director"||test=="invalid_asset"||test=="dead_brain"||test=="dead_camera"){
        if(test=="invalid_presenter")objects.at(ptr(presenter)).type="Other.Presenter";
        if(test=="dead_player")objects.at(ptr(player)).alive=false;
        if(test=="invalid_timeline")objects.at(ptr(timeline)).type="Other.Timeline";
        if(test=="dead_director")objects.at(ptr(director)).alive=false;
        if(test=="invalid_asset")objects.at(ptr(asset)).type="Other.Asset";
        if(test=="dead_brain")objects.at(ptr(brain)).alive=false;
        if(test=="dead_camera")objects.at(ptr(camera)).alive=false;
        assert(mp4_selected_controller(ptr(presenter))==nullptr&&initialized==0);
    }else if(test=="android_outer_verified"||test=="ios_direct_verified"){
        if(test=="ios_direct_verified")reset(false);
        mp4_source_verified=false;mp4_verify_original_calls();assert(mp4_source_verified&&mp4_replay_verified);
        assert(mp4_original_current_controller()==ptr(controller));
    }else if(test=="wrong_outer_slot"){
        has_outer=reinterpret_cast<uintptr_t>(&instance_cell);
        mp4_verify_original_calls();assert(!mp4_source_verified&&initialized==0);
    }else if(test=="unmapped_cell"||test=="unmapped_slot"){
        rejected_mapping=test=="unmapped_cell"?mp4_controller_profile.has_cell:mp4_controller_profile.instance_slot;
        mp4_verify_original_calls();assert(!mp4_source_verified&&initialized==0);
    }else if(test=="unverified_getter"||test=="unverified_resolver"){
        rejected_binding=test=="unverified_getter"?mp4_controller_profile.instance.rva:mp4_controller_profile.metadata_initialize.rva;
        mp4_verify_original_calls();assert(!mp4_source_verified&&initialized==0);
    }else assert(false);
    std::puts("PASS");return 0;
}
"""


@pytest.fixture(scope="module")
def controller_harness(tmp_path_factory):
    compiler = shutil.which("c++") or shutil.which("clang++") or shutil.which("g++")
    if compiler is None:
        pytest.skip("C++17 compiler unavailable")
    source = BRIDGE.read_text()
    functions = "\n\n".join(_function(source, signature) for signature in (
        "void mp4_verify_original_calls()", "void* mp4_original_current_controller()",
        "void remember_controller(void *controller)", "void *mp4_selected_controller(void *presenter)",
    ))
    work = tmp_path_factory.mktemp("mp4-controller-lookup")
    cpp, binary = work / "lookup.cpp", work / "lookup"
    cpp.write_text(HARNESS.replace("@@PRODUCTION@@", functions))
    compile_result = subprocess.run([compiler, "-std=c++17", "-O1", "-Wall", "-Wextra", "-Werror",
                                     str(cpp), "-o", str(binary)], capture_output=True, text=True, timeout=45)
    assert compile_result.returncode == 0, compile_result.stdout + compile_result.stderr
    return binary


@pytest.mark.parametrize("scenario", (
    "verified_existing", "unverified", "wrong_thread", "unresolved", "zero_has", "zero_instance",
    "tagged_has", "tagged_instance", "has_false", "wrong_class", "dead", "cold_fallback", "main_current", "candidate_current",
    "wrong_cached_camera", "wrong_original_camera", "camera_changed_after_cache", "ambiguous_timeline_cameras", "no_camera_track",
    "invalid_presenter", "dead_player", "invalid_timeline", "dead_director", "invalid_asset", "dead_brain", "dead_camera",
    "android_outer_verified", "ios_direct_verified", "wrong_outer_slot", "unmapped_cell", "unmapped_slot",
    "unverified_getter", "unverified_resolver",
))
def test_actual_controller_lookup_guards(controller_harness, scenario):
    result = subprocess.run([str(controller_harness), scenario], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "PASS"
