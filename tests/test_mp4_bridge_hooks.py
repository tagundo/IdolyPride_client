"""Compile production hook wrappers to verify original-first render callbacks."""
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT=Path(__file__).resolve().parents[1]


def test_initialize_hook_copies_original_selection_before_loader_mutation_and_preserves_async_abi(tmp_path):
    compiler=shutil.which('g++') or shutil.which('clang++')
    if not compiler:pytest.skip('C++ compiler unavailable')
    source=(ROOT/'client-presentation/native/bridge.cpp').read_text()
    begin=source.index('struct Mp4UniTask {')
    end=source.index('// BEGIN_MP4_PHOTOGRAPHY_HOOKS',begin)
    wrappers=source[begin:end]
    fixture=r'''
#include <atomic>
#include <cassert>
#include <cstdint>
#include <cstring>
#include <vector>
using Method=const void;
std::atomic<bool> ready{true};bool unity=true,available=true;
std::vector<int> order;void* player=reinterpret_cast<void*>(7);void* param=reinterpret_cast<void*>(8);
bool game_call(bool=false){return unity;}bool mp4_prepare_runtime(){return available;}
struct {uint64_t epoch=1;void*player=reinterpret_cast<void*>(7);void*presenter=nullptr;}mp4_actor_host;
extern unsigned mp4_original_lifecycle_depth;
void mp4_scene_restore_globals_before_source_change(void*){assert(!mp4_original_lifecycle_depth);order.push_back(10);}
void mp4_scene_will_change(void*p){assert(p==player&&!mp4_original_lifecycle_depth);order.push_back(11);}
void mp4_actor_scene_will_change(void*p){assert(p==player&&!mp4_original_lifecycle_depth);order.push_back(12);}
namespace idoly_mp4_runtime {
void observe_player_initializing(void*p,void*q){assert(p==player&&q==param&&!mp4_original_lifecycle_depth);order.push_back(1);}
void observe_presenter_ended(void*){assert(false);}
void observe_source_handoff_failed(void*){assert(false);}
}
'''+wrappers+r'''
Mp4UniTask original(void*p,void*q,bool setup,Mp4CancellationToken ct,Method*m){
 assert(p==player&&q==param&&setup&&ct.source==reinterpret_cast<void*>(9)&&m==reinterpret_cast<void*>(10)&&mp4_original_lifecycle_depth==1);
 order.push_back(2);Mp4UniTask result{};result.source=reinterpret_cast<void*>(11);result.token=-13;
 for(unsigned i=0;i<6;++i){result.padding[i]=uint8_t(i+20);}return result;
}
int main(){
 mp4_player_initialize_original=original;
 for(unsigned test=0;test<4;++test){
  unity=test!=1;available=test!=2;ready.store(test!=3);order.clear();
  Mp4UniTask result=mp4_player_initialize_hook(player,param,true,{reinterpret_cast<void*>(9)},reinterpret_cast<void*>(10));
  assert(result.source==reinterpret_cast<void*>(11)&&result.token==-13);
  for(unsigned i=0;i<6;++i)assert(result.padding[i]==i+20);
  assert(!mp4_original_lifecycle_depth);
  assert(order==(test==0?std::vector<int>{10,11,12,1,2}:test==1?std::vector<int>{11,12,2}:std::vector<int>{10,11,12,2}));
 }
}
'''
    path=tmp_path/'initialize.cpp';path.write_text(fixture);binary=tmp_path/'initialize'
    subprocess.run([compiler,'-std=c++17','-Wall','-Wextra','-Werror',str(path),'-o',str(binary)],check=True,capture_output=True,text=True)
    subprocess.run([str(binary)],check=True,capture_output=True,text=True)

def test_typed_original_first_hooks_and_thread_guards(tmp_path):
    compiler=shutil.which('g++') or shutil.which('clang++')
    if not compiler:pytest.skip('C++ compiler unavailable')
    source=(ROOT/'client-presentation/native/bridge.cpp').read_text()
    # These wrappers no longer form one contiguous block. Extract their real
    # declarations and bodies without pulling in unrelated producer hosts.
    declarations = ('struct Mp4RenderContext ', 'VoidMethod mp4_presenter_update_original;',
        'using Mp4CapturePass=', 'using Mp4EndCamera=', 'Mp4CapturePass mp4_capture_pass_original;',
        'Mp4EndCamera mp4_end_camera_original;')
    wrappers = '\n'.join(next(line for line in source.splitlines() if line.startswith(prefix))
                         for prefix in declarations) + '\n'
    for name in ('mp4_presenter_update_hook', 'mp4_capture_pass_hook', 'mp4_end_camera_hook'):
        begin=source.index('void '+name+'(');opening=source.index('{',begin);depth=0
        for end in range(opening,len(source)):
            depth += (source[end]=='{')-(source[end]=='}')
            if not depth:
                wrappers+=source[begin:end+1]+'\n';break
        else:raise AssertionError('Unclosed shipping hook: '+name)
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
