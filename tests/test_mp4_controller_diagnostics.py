"""Run the production controller-discovery observer and status projection.

Only the game readiness callbacks are synthetic. This checks the native JSON
boundary and error precedence, not Unity object discovery or device rendering.
"""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from test_mp4_controller_lookup import _function

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "client-presentation/native/mp4_runtime.hpp"

HARNESS = r'''
#include "mp4_timeline_camera.hpp"
#include "mp4_output_policy.hpp"
#include "mp4_session_api.h"
#include <array>
#include <cassert>
#include <cstdio>
#include <cstring>
#include <pthread.h>
#include <string>
#include <stdexcept>
namespace idoly_mp4_runtime {
enum class Result {ok=0,waiting=1,unsupported=-1,invalid=-2};
struct Snapshot {};
struct FakeGame {
    Result result=Result::waiting,geometry=Result::ok;
    const char* error="selected_render_controller_missing";
    bool geometry_probe=true;int32_t width=1920,height=1080;
    unsigned snapshots=0;
    Result snapshot(Snapshot&){++snapshots;return result;}
    const char* last_error()const{return error;}
    bool has_source_geometry_probe()const{return geometry_probe;}
    Result source_geometry(int32_t& w,int32_t& h){w=width;h=height;return geometry;}
} game;
pthread_mutex_t control_mutex=PTHREAD_MUTEX_INITIALIZER;
@@STRUCTS@@
PublicStatus published;
ControllerDiscovery controller_discovery;
char readiness_error[96]="open_selected_mv_first";
uint64_t unity_ticks=13,capture_acks=7;
bool control_busy=false,pause_acknowledged=false;
int requested_pause_reason=IDMP4_PAUSE_NONE;
NativeObservation native_observation;
NativeSceneDiagnostics native_diagnostics;
NativeSceneDiagnosticProbe native_diagnostic_probe=nullptr;
void* native_diagnostic_context=nullptr;
bool native_scene_required=false,native_scene_installed=false,last_admission_verified=false;
uint64_t queue_selection_generation=1,selected_identity=17,now=1000;
uint64_t native_entries=19;
uint64_t milliseconds(){return now;}
unsigned diagnostic_calls=0;
bool diagnostic_throw=false;
void diagnostic_probe(void* context,NativeSceneDiagnostics* output){
    assert(context==reinterpret_cast<void*>(17));++diagnostic_calls;
    if(diagnostic_throw)throw std::runtime_error("original fixture");
    output->available=true;
    for(unsigned i=0;i<4;++i){output->parts[i].result=static_cast<int32_t>(i)-2;
        std::snprintf(output->parts[i].error,sizeof output->parts[i].error,"part_%u_unclosed",i);}
}
unsigned admissions=0;
Result admitted=Result::ok;
Result admit(void*){++admissions;return admitted;}
struct {Result(*admit)(void*)=idoly_mp4_runtime::admit;} native_scene_control;
void* native_scene_context=nullptr;
const char* native_scene_error(const char*){return "actual_admission_rejected";}
@@PRODUCTION@@
}
int main(int argc,char** argv){
    assert(argc==2);const std::string scenario=argv[1];using namespace idoly_mp4_runtime;
    const idoly_mp4_timeline_camera::Counters counts{7,6,5,4,3,2};
    Snapshot snapshot{};
    if(scenario=="default"){}
    else if(scenario=="observed"||scenario=="singleton"||scenario=="camera_component"){
        observe_controller_discovery("none",scenario.c_str(),counts,11);game.result=Result::ok;
        assert(probe_readiness(snapshot)==Result::ok);
    }else if(scenario=="failure"){
        observe_controller_discovery("selected_camera_binding_not_ready","none",counts,11);
        assert(probe_readiness(snapshot)==Result::waiting);
    }else if(scenario=="unrelated_error"){
        observe_controller_discovery("selected_camera_binding_not_ready","none",counts,11);
        game.error="selected_mv_not_loaded";assert(probe_readiness(snapshot)==Result::waiting);
    }else if(scenario=="ready_with_old_discovery_error"){
        observe_controller_discovery("selected_camera_binding_not_ready","none",counts,11);
        game.result=Result::ok;assert(probe_readiness(snapshot)==Result::ok);
    }else if(scenario=="none_reason"){
        observe_controller_discovery("none","camera_component",counts,11);
        assert(probe_readiness(snapshot)==Result::waiting);
    }else if(scenario=="clear"){
        observe_controller_discovery("selected_camera_binding_not_ready","singleton",counts,11);
        observe_controller_discovery("none","none");
        assert(probe_readiness(snapshot)==Result::waiting);
    }else if(scenario=="bounded_strings"){
        const std::string reason(180,'a'),source(80,'b');
        observe_controller_discovery(reason.c_str(),source.c_str(),counts,11);
        assert(std::strlen(controller_discovery.reason)==95&&std::strlen(controller_discovery.source)==23);
        assert(probe_readiness(snapshot)==Result::waiting);
    }else if(scenario=="geometry_waiting"||scenario=="geometry_unsupported"){
        observe_controller_discovery("selected_camera_binding_not_ready","none",counts,11);
        game.result=Result::ok;game.geometry=scenario=="geometry_waiting"?Result::waiting:Result::unsupported;
        assert(probe_readiness(snapshot)==game.geometry);
    }else if(scenario=="geometry_without_probe"){
        observe_controller_discovery("none","observed",counts,11);game.result=Result::ok;
        game.geometry_probe=false;game.width=1101;game.height=2201;
        assert(probe_readiness(snapshot)==Result::ok);
    }else if(scenario=="admission_sampling"){
        game.result=Result::ok;native_scene_installed=true;
        assert(probe_readiness(snapshot,false)==Result::ok&&admissions==1);
        for(unsigned i=0;i<100;++i)assert(probe_readiness(snapshot,false)==Result::ok);
        assert(admissions==1&&game.snapshots==101); // Ordinary selection/geometry observations stay fresh.
        admitted=Result::unsupported;now+=250;
        assert(probe_readiness(snapshot,false)==Result::unsupported&&admissions==2);
        assert(!std::strcmp(readiness_error,"actual_admission_rejected")&&!last_admission_verified);
        admitted=Result::ok;
        assert(probe_readiness(snapshot)==Result::ok&&admissions==3); // A start never reuses a cached rejection/positive.
        assert(probe_readiness(snapshot)==Result::ok&&admissions==4);
        ++queue_selection_generation;
        assert(probe_readiness(snapshot,false)==Result::ok&&admissions==5);
        ++selected_identity;
        assert(probe_readiness(snapshot,false)==Result::ok&&admissions==6);
        game.result=Result::waiting;assert(probe_readiness(snapshot,false)==Result::waiting);
        game.result=Result::ok;assert(probe_readiness(snapshot,false)==Result::ok&&admissions==7);
        --now;assert(probe_readiness(snapshot,false)==Result::ok&&admissions==8);
    }else if(scenario=="diagnostic_sampling"){
        assert(!install_native_scene_diagnostic_probe(nullptr,diagnostic_probe));
        assert(install_native_scene_diagnostic_probe(reinterpret_cast<void*>(17),diagnostic_probe));
        assert(install_native_scene_diagnostic_probe(reinterpret_cast<void*>(17),diagnostic_probe));
        assert(!install_native_scene_diagnostic_probe(reinterpret_cast<void*>(18),diagnostic_probe));
        refresh_native_diagnostics(true,17,false);assert(diagnostic_calls==1);
        for(unsigned i=0;i<100;++i)refresh_native_diagnostics(true,17,false);
        assert(diagnostic_calls==1&&!published.ready&&!native_scene_installed);
        now+=250;refresh_native_diagnostics(true,17,true);assert(diagnostic_calls==1); // Captured exports never probe again.
        refresh_native_diagnostics(true,17,false);assert(diagnostic_calls==2);
        ++queue_selection_generation;refresh_native_diagnostics(true,17,false);assert(diagnostic_calls==3);
        ++native_entries;refresh_native_diagnostics(true,18,false);assert(diagnostic_calls==4);
        --now;refresh_native_diagnostics(true,18,false);assert(diagnostic_calls==5);
    }else if(scenario=="diagnostic_exception"){
        assert(install_native_scene_diagnostic_probe(reinterpret_cast<void*>(17),diagnostic_probe));diagnostic_throw=true;
        refresh_native_diagnostics(true,17,false);assert(diagnostic_calls==1&&!native_diagnostics.available);
    }else if(scenario=="diagnostic_no_source"){
        assert(install_native_scene_diagnostic_probe(reinterpret_cast<void*>(17),diagnostic_probe));
        refresh_native_diagnostics(false,17,false);assert(diagnostic_calls==0&&!native_diagnostics.available);
    }else if(scenario=="diagnostic_no_probe"){
        refresh_native_diagnostics(true,17,false);assert(diagnostic_calls==0&&!native_diagnostics.available);
    }else if(scenario=="bounded_status"){
        observe_controller_discovery("none","camera_component",counts,11);
        std::array<unsigned char,4096> bytes{};bytes.fill(0xa5);
        assert(status(nullptr,bytes.size())==0&&status(reinterpret_cast<char*>(bytes.data()),0)==0);
        assert(bytes[0]==0xa5);
        assert(status(reinterpret_cast<char*>(bytes.data()),1)==0&&bytes[0]==0&&bytes[1]==0xa5);
        bytes.fill(0xa5);assert(status(reinterpret_cast<char*>(bytes.data()),128)==0);
        assert(bytes[127]==0&&bytes[128]==0xa5&&bytes.back()==0xa5);
        const size_t required=status(reinterpret_cast<char*>(bytes.data()),bytes.size());assert(required>128);
        bytes.fill(0xa5);assert(status(reinterpret_cast<char*>(bytes.data()),required)==0);
        assert(bytes[required-1]==0&&bytes[required]==0xa5);
        bytes.fill(0xa5);assert(status(reinterpret_cast<char*>(bytes.data()),required+1)==required);
        assert(bytes[required]==0&&bytes[required+1]==0xa5);
    }else assert(false);
    char output[4096]{};const size_t length=status(output,sizeof(output));
    assert(length&&length==std::strlen(output));std::puts(output);
}
'''


def runtime_function(source, signature):
    """Ignore default-argument braces before locating the original body."""
    start = source.index(signature)
    at = source.index("(", start)
    depth = 0
    while at < len(source):
        if source[at] == "(":
            depth += 1
        elif source[at] == ")":
            depth -= 1
            if not depth:
                break
        at += 1
    body = source.index("{", at)
    return source[start:body] + _function(source[body:], "{")


@pytest.fixture(scope="module")
def diagnostics_binary(tmp_path_factory):
    compiler = shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        pytest.skip("C++ compiler required")
    source = RUNTIME.read_text()
    structures = "\n".join(_function(source, signature) + ";" for signature in (
        "struct PublicStatus", "struct ControllerDiscovery", "struct NativeObservation",
        "struct NativeSceneDiagnosticPart", "struct NativeSceneDiagnostics"))
    structures += "\nusing NativeSceneDiagnosticProbe=void(*)(void*,NativeSceneDiagnostics*);\n"
    functions = "\n".join(runtime_function(source, signature) for signature in (
        "inline void observe_controller_discovery(", "inline const char* pause_reason_name(",
        "inline Result probe_readiness(", "inline size_t status(",
        "inline bool install_native_scene_diagnostic_probe(", "inline void refresh_native_diagnostics("))
    folder = tmp_path_factory.mktemp("mp4-controller-diagnostics")
    cpp, binary = folder / "diagnostics.cpp", folder / "diagnostics"
    cpp.write_text(HARNESS.replace("@@STRUCTS@@", structures).replace("@@PRODUCTION@@", functions))
    result = subprocess.run([compiler,"-std=c++17","-O1","-Wall","-Wextra","-Werror","-pthread",
        "-I",str(ROOT / "client-presentation/native"),str(cpp),"-o",str(binary)],capture_output=True,text=True,timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
    return binary


def run(diagnostics_binary, scenario):
    result = subprocess.run([str(diagnostics_binary),scenario],capture_output=True,text=True,timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def test_readonly_scene_probe_is_cached_and_cannot_enable_export(diagnostics_binary):
    value = run(diagnostics_binary, "diagnostic_sampling")
    diagnostics = value["scene_diagnostics"]
    assert diagnostics["available"] is True
    assert diagnostics["source_identity"] == "0000000000000012"
    assert diagnostics["playerloop_frame"] == 20
    assert diagnostics["actor"] == {"result": -2, "error": "part_0_unclosed"}
    assert diagnostics["world"] == {"result": 1, "error": "part_3_unclosed"}
    assert value["ready"] is False
    assert value["observation"]["world_admission"] == "unverified"


@pytest.mark.parametrize("scenario,error", [
    ("diagnostic_exception", "diagnostic_observer_exception"),
    ("diagnostic_no_source", "selected_source_not_ready"),
    ("diagnostic_no_probe", "diagnostic_probe_unavailable"),
])
def test_unavailable_scene_probe_preserves_bounded_reason(diagnostics_binary, scenario, error):
    value = run(diagnostics_binary, scenario)
    diagnostics = value["scene_diagnostics"]
    assert diagnostics["available"] is False
    assert all(diagnostics[part] == {"result": -1, "error": error}
               for part in ("actor", "camera", "stage", "world"))
    assert value["ready"] is False


COUNTERS = dict(listed_directors=7,unique_directors=6,assets=5,output_tracks=4,
                camera_tracks=3,null_assets=2,candidate_controllers=11)


@pytest.mark.parametrize("source", ["observed", "singleton", "camera_component"])
def test_actual_observer_serializes_source_and_each_counter(diagnostics_binary, source):
    value = run(diagnostics_binary, source)
    assert value["controller_discovery"] == dict(reason="none",source=source,**COUNTERS)
    assert value["readiness_error"] == "none" and value["ready"] is True
    assert (value["source_width"],value["source_height"]) == (1920,1080)
    assert (value["unity_ticks"],value["capture_acks"]) == (13,7)


@pytest.mark.parametrize("scenario,error,ready", [
    ("default","open_selected_mv_first",False),
    ("failure","selected_camera_binding_not_ready",False),
    ("unrelated_error","selected_mv_not_loaded",False),
    ("ready_with_old_discovery_error","none",True),
    ("none_reason","selected_render_controller_missing",False),
    ("geometry_waiting","selected_capture_geometry_not_ready",False),
    ("geometry_unsupported","selected_capture_geometry_unsupported",False),
])
def test_specific_discovery_error_only_overrides_missing_controller(diagnostics_binary,scenario,error,ready):
    value = run(diagnostics_binary,scenario)
    assert value["readiness_error"] == error and value["ready"] is ready
    if scenario == "default":
        assert value["controller_discovery"] == dict(reason="selected_render_controller_missing",source="none",**dict.fromkeys(COUNTERS,0))
    if not ready:
        assert (value["source_width"],value["source_height"]) == (0,0)


def test_new_observation_clears_old_counts_and_reason(diagnostics_binary):
    value = run(diagnostics_binary,"clear")
    assert value["controller_discovery"] == dict(reason="none",source="none",**dict.fromkeys(COUNTERS,0))
    assert value["readiness_error"] == "selected_render_controller_missing"


def test_diagnostic_strings_and_json_status_are_bounded(diagnostics_binary):
    value = run(diagnostics_binary,"bounded_strings")
    assert value["controller_discovery"]["reason"] == "a" * 95
    assert value["controller_discovery"]["source"] == "b" * 23
    assert value["readiness_error"] == "a" * 95
    assert run(diagnostics_binary,"bounded_status")["controller_discovery"]["source"] == "camera_component"


def test_observed_source_geometry_does_not_depend_on_probe_or_orientation(diagnostics_binary):
    value = run(diagnostics_binary,"geometry_without_probe")
    assert value["ready"] is True and value["readiness_error"] == "none"
    assert (value["source_width"],value["source_height"]) == (1101,2201)


def test_idle_admission_is_sampled_but_starts_and_source_changes_are_fresh(diagnostics_binary):
    value = run(diagnostics_binary,"admission_sampling")
    assert value["ready"] is True and value["readiness_error"] == "none"
