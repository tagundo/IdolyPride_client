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
namespace idoly_mp4_runtime {
enum class Result {ok=0,waiting=1,unsupported=-1,invalid=-2};
struct Snapshot {};
struct FakeGame {
    Result result=Result::waiting,geometry=Result::ok;
    const char* error="selected_render_controller_missing";
    bool geometry_probe=true;int32_t width=1920,height=1080;
    Result snapshot(Snapshot&){return result;}
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
        "struct PublicStatus", "struct ControllerDiscovery"))
    functions = "\n".join(runtime_function(source, signature) for signature in (
        "inline void observe_controller_discovery(", "inline const char* pause_reason_name(",
        "inline Result probe_readiness(", "inline size_t status("))
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
