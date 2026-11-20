"""Compile production hook wrappers to verify original-first render callbacks."""
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT=Path(__file__).resolve().parents[1]

def test_typed_original_first_hooks_and_thread_guards(tmp_path):
    compiler=shutil.which('g++') or shutil.which('clang++')
    if not compiler:pytest.skip('C++ compiler unavailable')
    source=(ROOT/'client-presentation/native/bridge.cpp').read_text()
    begin=source.index('VoidMethod mp4_presenter_update_original;')
    end=source.index('// BEGIN_MP4_OWNED_CLOCK_HOOKS',begin)
    wrappers=source[begin:end]
    fixture=r'''
#include <atomic>
#include <cassert>
#include <cstdint>
#include <vector>
using Method=const void;using VoidMethod=void(*)(void*,Method*);
std::atomic<bool> ready{true};bool unity_thread=true,api_available=true,mp4_api_installed=true;
std::vector<int> calls;void* selected=reinterpret_cast<void*>(7);
bool game_call(bool=false){return unity_thread;}
bool mp4_prepare_runtime(){return api_available;}
void* mp4_selected_controller(void*){return selected;}
namespace idoly_mp4_runtime {
void observe_presenter(void*){calls.push_back(2);}
void observe_camera_controller(void*){calls.push_back(3);}
void capture_pass_did_execute(void*,const void*){calls.push_back(5);}
void camera_did_render(void*){calls.push_back(7);}
}
'''+wrappers+r'''
void presenter_original(void*,Method*){calls.push_back(1);}
void pass_original(void* self,Mp4RenderContext context,void* data,Method* method){assert(self==reinterpret_cast<void*>(11)&&context.pointer==reinterpret_cast<void*>(12)&&data==reinterpret_cast<void*>(13)&&method==reinterpret_cast<void*>(14));calls.push_back(4);}
void camera_original(Mp4RenderContext context,void* camera,Method* method){assert(context.pointer==reinterpret_cast<void*>(12)&&camera==reinterpret_cast<void*>(15)&&method==reinterpret_cast<void*>(14));calls.push_back(6);}
int main(){
mp4_presenter_update_original=presenter_original;mp4_capture_pass_original=pass_original;mp4_end_camera_original=camera_original;
mp4_presenter_update_hook(nullptr,nullptr);assert((calls==std::vector<int>{1,2,3}));calls.clear();
mp4_capture_pass_hook(reinterpret_cast<void*>(11),{reinterpret_cast<void*>(12)},reinterpret_cast<void*>(13),reinterpret_cast<void*>(14));
mp4_end_camera_hook({reinterpret_cast<void*>(12)},reinterpret_cast<void*>(15),reinterpret_cast<void*>(14));assert((calls==std::vector<int>{4,5,6,7}));calls.clear();
unity_thread=false;mp4_presenter_update_hook(nullptr,nullptr);mp4_capture_pass_hook(reinterpret_cast<void*>(11),{reinterpret_cast<void*>(12)},reinterpret_cast<void*>(13),reinterpret_cast<void*>(14));mp4_end_camera_hook({reinterpret_cast<void*>(12)},reinterpret_cast<void*>(15),reinterpret_cast<void*>(14));assert((calls==std::vector<int>{1,4,6}));calls.clear();
unity_thread=true;ready=false;mp4_presenter_update_hook(nullptr,nullptr);assert((calls==std::vector<int>{1}));calls.clear();
ready=true;selected=nullptr;mp4_presenter_update_hook(nullptr,nullptr);assert((calls==std::vector<int>{1,2}));calls.clear();
api_available=false;mp4_presenter_update_hook(nullptr,nullptr);assert((calls==std::vector<int>{1}));
}
'''
    path=tmp_path/'hooks.cpp';path.write_text(fixture);binary=tmp_path/'hooks'
    subprocess.run([compiler,'-std=c++17','-Wall','-Wextra','-Werror',str(path),'-o',str(binary)],check=True,capture_output=True,text=True)
    subprocess.run([str(binary)],check=True,capture_output=True,text=True)
