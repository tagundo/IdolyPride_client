"""Scope camera-component recovery to the verified selected timeline camera.

This is a managed-lifetime and typed API boundary fixture, not game execution.
The separate pinned metadata audit records the actual original lookup ABI.
"""
from pathlib import Path
import importlib.util
import json
import os
import shutil
import subprocess

import pytest

ROOT=Path(__file__).resolve().parents[1]
NATIVE=ROOT/'client-presentation/native'
SOURCE=r'''
#include "mp4_camera_owner.hpp"
#include <cassert>
#include <cstring>
#include <map>
#include <stdexcept>
#include <string>
#include <vector>
using namespace idoly_mp4_game;
struct Object {const char* type;bool live=true,marked=false,unity_alive=true;Object* related=nullptr;};
Object camera{"UnityEngine.Camera"},other_camera{"UnityEngine.Camera"},controller{"VL.Rendering.VLSRPCameraController"},type{"System.Type"},wrong{"Other.Type"};
std::vector<Object*> objects{&camera,&other_camera,&controller,&type,&wrong};
std::map<uint32_t,Object*> roots;uint32_t serial=0;int retain_calls=0,fail_retain=0,component_calls=0,camera_calls=0;
Object* returned=&controller;Object* output=&camera;bool throws=false,destroy_camera=false,destroy_controller=false;
void mark(Object* value){if(!value||value->marked||!value->live)return;value->marked=true;mark(value->related);}
void collect(){for(auto* o:objects)o->marked=false;for(const auto& r:roots)mark(r.second);for(auto* o:objects)if(!o->marked)o->live=false;}
bool is_type(void* p,const char* name){if(!p)return false;auto* o=static_cast<Object*>(p);return o->live&&!std::strcmp(o->type,name);}
bool alive(void* p){return p&&static_cast<Object*>(p)->live&&static_cast<Object*>(p)->unity_alive;}
uint32_t retain(void* p){++retain_calls;if(retain_calls==fail_retain)return 0;assert(p&&static_cast<Object*>(p)->live);roots[++serial]=static_cast<Object*>(p);return serial;}
void* target(uint32_t handle){auto it=roots.find(handle);return it==roots.end()?nullptr:it->second;}
void release(uint32_t handle){assert(roots.erase(handle)==1);}
void* component(void* c,void* t,const void* method){
    ++component_calls;assert(c==&camera&&t==&type&&!method);collect();assert(alive(c)&&alive(t));
    if(throws)throw std::runtime_error("original lookup failed");
    if(destroy_camera)camera.unity_alive=false;if(destroy_controller)controller.unity_alive=false;
    return returned;
}
void* controller_camera(void* c,const void* method){++camera_calls;assert(c==&controller&&!method);collect();assert(controller.live);return output;}
CameraOwnerCalls api(){return {is_type,alive,retain,target,release,component,controller_camera};}
int main(int argc,char** argv){assert(argc==2);std::string scenario=argv[1];
    camera.related=&controller;controller.related=&camera;
    auto calls=api();void* receiver=&camera;void* type_object=&type;
    if(scenario=="wrong_camera")receiver=&wrong;
    if(scenario=="dead_camera")camera.unity_alive=false;
    if(scenario=="null_camera")receiver=nullptr;
    if(scenario=="wrong_type")type_object=&wrong;
    if(scenario=="null_type")type_object=nullptr;
    if(scenario=="absent")returned=nullptr;
    if(scenario=="wrong_result"){camera.related=&wrong;returned=&wrong;}
    if(scenario=="mismatched_output")output=&other_camera;
    if(scenario=="lookup_throws")throws=true;
    if(scenario=="camera_destroyed")destroy_camera=true;
    if(scenario=="controller_destroyed")destroy_controller=true;
    if(scenario=="camera_handle_failed")fail_retain=1;
    if(scenario=="type_handle_failed")fail_retain=2;
    if(scenario=="result_handle_failed")fail_retain=3;
    if(scenario=="missing_api")calls.get_component=nullptr;
    auto result=recover_camera_controller(receiver,type_object,calls);
    if(scenario=="success"){
        assert(result.handle&&std::strcmp(result.error,"none")==0&&component_calls==1&&camera_calls==1);
        assert(roots.size()==1&&target(result.handle)==&controller);collect();assert(controller.live&&camera.live);
        // Adapter adoption happens while the recovery handle still owns the result.
        auto adopted=retain(target(result.handle));release(result.handle);collect();assert(controller.live&&camera.live);release(adopted);
    }else{
        assert(!result.handle&&std::strcmp(result.error,"none")!=0&&roots.empty());
        if(scenario=="wrong_camera"||scenario=="dead_camera"||scenario=="null_camera"||scenario=="wrong_type"||scenario=="null_type"||scenario=="missing_api"||scenario=="camera_handle_failed"||scenario=="type_handle_failed")assert(component_calls==0);
        else assert(component_calls==1);
        if(scenario=="mismatched_output")assert(!std::strcmp(result.error,"selected_camera_controller_camera_mismatch"));
    }
    assert(roots.empty());
}
'''

@pytest.fixture(scope='module')
def camera_binary(tmp_path_factory):
    compiler=shutil.which('g++') or shutil.which('clang++')
    if not compiler:pytest.skip('C++ compiler unavailable')
    build=tmp_path_factory.mktemp('mp4-camera-owner');source=build/'camera.cpp';source.write_text(SOURCE);exe=build/'camera'
    run=subprocess.run([compiler,'-std=c++17','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-I',str(NATIVE),str(source),'-o',str(exe)],capture_output=True,text=True)
    assert run.returncode==0,run.stdout+run.stderr
    return exe

@pytest.mark.parametrize('scenario',['success','wrong_camera','dead_camera','null_camera','wrong_type','null_type','absent','wrong_result','mismatched_output','lookup_throws','camera_destroyed','controller_destroyed','camera_handle_failed','type_handle_failed','result_handle_failed','missing_api'])
def test_exact_camera_recovery_and_managed_lifetimes(camera_binary,scenario):
    run=subprocess.run([str(camera_binary),scenario],capture_output=True,text=True)
    assert run.returncode==0,run.stdout+run.stderr


def _audit():
    import sys
    sys.path.insert(0,str(ROOT/'tools'))
    spec=importlib.util.spec_from_file_location('audit_mp4_camera_owner',ROOT/'tools/audit_mp4_camera_owner.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_camera_owner_profile_header_matches_pinned_proof():
    audit=_audit();proof=json.loads((NATIVE/'mp4_camera_owner_profile.json').read_text())
    expected=audit.render_header(proof['platforms'])
    actual=(NATIVE/'mp4_controller_profile.hpp').read_text()
    assert actual.split(audit.START,1)[1].split(audit.END,1)[0]==expected.split(audit.START,1)[1].split(audit.END,1)[0]
    for platform,profile in proof['platforms'].items():
        game=json.loads((NATIVE/('mp4_game_profile.json' if platform=='android' else 'mp4_game_ios_profile.json')).read_text())
        assert profile['sources']==game['sources']
        assert profile['component_get_component']['parameters'][0]['type']=='System.Type'
        assert profile['component_get_component']['return']=='UnityEngine.Component'
        assert profile['fields']['timeline_output_tracks']['type']=='UnityEngine.Timeline.TrackAsset[]'
        assert profile['scope']['game_executed'] is False


def test_camera_owner_profile_reproduces_actual_originals():
    directory=os.environ.get('IDOLY_MP4_ORIGINALS_DIR')
    if not directory:pytest.skip('Set IDOLY_MP4_ORIGINALS_DIR to audit actual original inputs')
    directory=Path(directory);audit=_audit();expected=json.loads((NATIVE/'mp4_camera_owner_profile.json').read_text())['platforms']
    for platform,constructor,metadata,native in [('android',audit.OriginalAndroid,'android-metadata.dat','android-native.so'),('ios',audit.Original,'ios-metadata.dat','ios-native.bin')]:
        original=constructor((directory/metadata).read_bytes(),(directory/native).read_bytes())
        assert audit.build_profile(original,platform)==expected[platform]
