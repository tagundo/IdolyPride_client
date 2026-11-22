"""Actual source certificates and bounded self-read; hook backend is modeled."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def source_host(tmp_path_factory):
    bridge = (ROOT / "client-presentation/native/bridge.cpp").read_text()
    core = bridge.split("// BEGIN_MP4_HOOK_BOOTSTRAP_CORE", 1)[1].split("// END_MP4_HOOK_BOOTSTRAP_CORE", 1)[0]
    actual = bridge.split("// BEGIN_MP4_ANDROID_HOOK_SOURCE_HOST", 1)[1].split("// END_MP4_ANDROID_HOOK_SOURCE_HOST", 1)[0]
    prefix = r'''
#define _GNU_SOURCE 1
#include "profile.hpp"
#include <cstdint>
#include <cstddef>
#include <atomic>
#include <cstring>
#include <cassert>
#include <string>
#include <thread>
#include <pthread.h>
#include <unistd.h>
#include <sys/uio.h>
#include <fcntl.h>
#include <cstdlib>
namespace pin=idoly::presentation::profile;
// CORE
uintptr_t image_base=0x1000,mp4_native_base=0x2000;
void*held_library=reinterpret_cast<void*>(11);void*mp4_held_native_library=reinterpret_cast<void*>(12);
std::atomic<bool>mp4_native_clock_source_ready{true};
bool(*mp4_managed_hook_backend_current)(uintptr_t)=nullptr;
struct Image{uintptr_t base=0;bool accepted=true;};bool matches(const Image&i){return i.accepted;}
bool shadowhook_get_recordable(){return false;}void shadowhook_set_recordable(bool){}
void*shadowhook_hook_func_addr_2(void*,void*,void**,uint32_t,...){return nullptr;}
char*shadowhook_get_records(uint32_t){return nullptr;}
// HOST
int main(int argc,char**argv){assert(argc==2);const std::string mode=argv[1];
 if(mode=="code_read"){uint8_t input[32]{},output[32]{};for(unsigned i=0;i<32;++i)input[i]=i*7;
  assert(mp4_android_hook_code(nullptr,reinterpret_cast<uintptr_t>(input),output,32));assert(!memcmp(input,output,32));
  assert(!mp4_android_hook_code(nullptr,1,output,32));assert(!mp4_android_hook_code(nullptr,~uintptr_t(0)-1,output,32));
  assert(!mp4_android_hook_code(nullptr,reinterpret_cast<uintptr_t>(input),output,193));
  assert(!mp4_android_hook_code(nullptr,reinterpret_cast<uintptr_t>(input),nullptr,32));return 0;}
 Image image{image_base,true};
 if(mode=="bad_cohort")image.accepted=false;
 if(mode=="wrong_base")image.base+=4;
 if(mode=="no_game_hold")held_library=nullptr;
 if(mode=="no_native_hold")mp4_held_native_library=nullptr;
 if(mode=="native_unverified")mp4_native_clock_source_ready.store(false);
 const bool valid=mode!="bad_cohort"&&mode!="wrong_base"&&mode!="no_game_hold"&&mode!="no_native_hold"&&mode!="native_unverified";
 assert(mp4_android_managed_source_prepare(image)==valid);
 if(!valid){assert(!mp4_android_hook_source_state.active.load()&&!mp4_managed_hook_backend_current);return 0;}
 mp4_bootstrap::Source game{},native{};auto&ctx=mp4_android_hook_source_state;
 assert(mp4_android_hook_source(&ctx,mp4_bootstrap::BootstrapImage::game,&game));
 assert(mp4_android_hook_source(&ctx,mp4_bootstrap::BootstrapImage::engine,&native));
 assert(game.base==image_base&&native.base==mp4_native_base&&game.load&&native.load&&game.load!=native.load&&game.cohort!=native.cohort);
 assert(!mp4_android_managed_source_prepare(image));assert(mp4_android_hook_installer(&ctx));
 if(mode=="foreign_installer"){std::thread thread([&]{assert(!mp4_android_hook_installer(&ctx));});thread.join();return 0;}
 if(mode=="replaced_game_hold")held_library=reinterpret_cast<void*>(19);
 if(mode=="replaced_native_hold")mp4_held_native_library=reinterpret_cast<void*>(20);
 if(mode=="changed_native_base")++mp4_native_base;
 if(mode=="withdrawn")ctx.active.store(false);
 const bool current=mode=="valid";assert(mp4_android_hook_source(&ctx,mp4_bootstrap::BootstrapImage::game,&game)==current);
 if(!current)assert(!game.base&&!game.load&&!game.cohort);
 assert(!mp4_managed_source_current(1));
}
'''
    folder = tmp_path_factory.mktemp("android-hook-source-host")
    source, binary = folder / "test.cpp", folder / "test"
    source.write_text(prefix.replace("// CORE", core).replace("// HOST", actual))
    result = subprocess.run([shutil.which("g++") or "clang++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-g", "-O1", "-pthread", "-fsanitize=address,undefined", "-fno-pie", "-no-pie", "-I", str(ROOT / "client-presentation/native"), str(source), "-o", str(binary)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    return binary


@pytest.mark.parametrize("mode", ["valid", "code_read", "bad_cohort", "wrong_base", "no_game_hold", "no_native_hold", "native_unverified", "foreign_installer", "replaced_game_hold", "replaced_native_hold", "changed_native_base", "withdrawn"])
def test_retained_loader_certificate_and_real_self_code_read(source_host, mode):
    result = subprocess.run([str(source_host), mode], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
