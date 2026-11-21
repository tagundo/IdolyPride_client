"""Exercise the actual serialized global shader lease with synthetic setters."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / 'client-presentation/native'
HARNESS = r'''
#include "mp4_playback_state.hpp"
#include <pthread.h>
#include <cassert>
#include <condition_variable>
#include <mutex>
#include <thread>
#include <chrono>
#include <atomic>
#include <string>
using Method=const void;
bool mp4_source_verified=true,mp4_api_installed=true,unity_thread=true;
float global_time=-1;unsigned sets=0,resets=0;
bool game_call(){return unity_thread;}
bool custom(void*){return global_time>=0;}
float current(void*){return global_time>=0?global_time:123.f;}
struct Api{bool(*shader_use_custom)(void*)=custom;float(*shader_current_time)(void*)=current;}mp4_api;
std::mutex barrier;std::condition_variable cv;bool block_raw=false,entered=false,allow=false;
void raw_set(float value,Method*){
    if(block_raw){std::unique_lock<std::mutex> lock(barrier);entered=true;cv.notify_all();cv.wait(lock,[]{return allow;});}
    ++sets;global_time=value;
}
void raw_reset(Method*){++resets;global_time=-1;}
// ACTUAL_HOST
int main(int argc,char** argv){
    assert(argc==2);const std::string mode=argv[1];int owner=0,other=0;
    mp4_shader_set_original=raw_set;mp4_shader_reset_original=raw_reset;
    if(mode=="custom")global_time=2.5f;
    if(mode=="source_unverified")mp4_source_verified=false;
    if(mode=="wrong_thread")unity_thread=false;
    if(mode=="exhausted")mp4_shader_generation=0;
    if(mode=="source_unverified"||mode=="wrong_thread"||mode=="exhausted"){
        assert(!mp4_shader_lease_begin(&owner));assert(!mp4_shader_lease.active&&!sets&&!resets);return 0;
    }
    assert(mp4_shader_lease_begin(&owner));assert(!mp4_shader_lease_begin(&other));
    assert(!mp4_shader_lease_set_time(&other,0));mp4_shader_lease_finish(&other);assert(mp4_shader_lease.active);
    assert(!mp4_shader_lease_set_time(&owner,-1)&&!mp4_shader_lease_set_time(&owner,901));
    assert(mp4_shader_lease_set_time(&owner,0)&&sets==1&&mp4_shader_generation==1&&global_time==0);
    if(mode=="external_same"||mode=="external_reset"||mode=="external_other"){
        if(mode=="external_reset")mp4_shader_reset_hook(nullptr);
        else mp4_shader_set_hook(mode=="external_same"?0:7,nullptr);
        const auto before=global_time;const auto writes=sets+resets;
        assert(mp4_shader_generation==2&&!mp4_shader_lease_set_time(&owner,1));
        mp4_shader_lease_finish(&owner);assert(global_time==before&&sets+resets==writes&&!mp4_shader_lease.active);return 0;
    }
    if(mode=="concurrent_external"){
        block_raw=true;
        std::thread own([&]{assert(mp4_shader_lease_set_time(&owner,1));});
        {std::unique_lock<std::mutex> lock(barrier);cv.wait(lock,[]{return entered;});}
        std::atomic<bool> started{false},finished{false};
        std::thread external([&]{started=true;mp4_shader_set_hook(7,nullptr);finished=true;});
        while(!started.load())std::this_thread::yield();
        // External normal write cannot cross our token check/raw-apply lock.
        std::this_thread::sleep_for(std::chrono::milliseconds(10));assert(!finished.load());
        {std::lock_guard<std::mutex> lock(barrier);allow=true;cv.notify_all();}
        own.join();external.join();assert(finished&&global_time==7&&mp4_shader_generation==2);
        const auto writes=sets+resets;mp4_shader_lease_finish(&owner);assert(global_time==7&&sets+resets==writes);return 0;
    }
    if(mode=="new_scene"){
        // Finish is independent of retired selected scenes and their APIs.
        unity_thread=false;mp4_source_verified=false;mp4_api_installed=false;
        mp4_api.shader_current_time=nullptr;mp4_api.shader_use_custom=nullptr;
    }
    mp4_shader_lease_finish(&owner);assert(!mp4_shader_lease.active&&mp4_shader_generation==1);
    assert(mode=="custom"?(global_time==2.5f&&sets==2&&resets==0):(global_time==-1&&sets==1&&resets==1));
    const auto writes=sets+resets;mp4_shader_lease_finish(&owner);assert(sets+resets==writes);
}
'''


@pytest.fixture(scope='module')
def lease_binary(tmp_path_factory):
    compiler = shutil.which('c++')
    if not compiler:
        pytest.skip('A host C++ compiler is required')
    bridge = (NATIVE / 'bridge.cpp').read_text()
    host = bridge.split('// BEGIN_MP4_SHADER_LEASE_HOST\n', 1)[1].split('// END_MP4_SHADER_LEASE_HOST', 1)[0]
    folder = tmp_path_factory.mktemp('shader-lease-host')
    source, binary = folder / 'lease.cpp', folder / 'lease'
    source.write_text(HARNESS.replace('// ACTUAL_HOST', host))
    result = subprocess.run([compiler, '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', '-pthread', '-I', str(NATIVE), str(source), '-o', str(binary)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    return binary


@pytest.mark.parametrize('mode', ['default', 'custom', 'source_unverified', 'wrong_thread', 'exhausted',
                                  'external_same', 'external_reset', 'external_other', 'concurrent_external', 'new_scene'])
def test_serialized_real_host_preserves_external_owners_and_finishes_without_scene_reads(lease_binary, mode):
    result = subprocess.run([str(lease_binary), mode], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('platform', ['android', 'ios'])
def test_original_shader_abi_and_hook_profiles_are_exact_static_float_and_void(platform):
    profile = json.loads((ROOT / 'client-presentation' / ('native' if platform == 'android' else 'ios') / 'profile.json').read_text())
    game = json.loads((NATIVE / ('mp4_game_profile.json' if platform == 'android' else 'mp4_game_ios_profile.json')).read_text())
    for alias, method in [('mp4_shader_set', 'shader_set_custom'), ('mp4_shader_reset', 'shader_reset_custom')]:
        row, original = profile['aliases'][alias], game['methods'][method]
        rva = int(row['rva'], 16) if isinstance(row['rva'], str) else row['rva']
        assert rva == int(original['rva'], 16) and row['prefix16'] == original['prefix']
        assert row['metadata_method_index'] == original['metadata_method_index']
        assert row['method_flags'] & 16 and row['return_type'] == 'System.Void'
        assert row['parameter_count'] == (1 if alias == 'mp4_shader_set' else 0)
        assert row['native_abi'] == ('void(float,const MethodInfo*)' if alias == 'mp4_shader_set' else 'void(const MethodInfo*)')
