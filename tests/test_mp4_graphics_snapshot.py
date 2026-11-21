"""Exercise the production queue graphics snapshot and pinned original FPS accessors.

The managed heap is synthetic. The original ARM64 getter/setter and optional
whole-original audit independently distinguish FPS from FrameChangeScale.
"""
from pathlib import Path
import hashlib
import os
import shutil
import struct
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "client-presentation/native"

HARNESS = r'''
#include "presentation_math.hpp"
#include "mp4_queue.hpp"
#include <array>
#include <cassert>
#include <cmath>
#include <cstring>
#include <pthread.h>
#include <string>
using namespace idoly::presentation;
Config current_config{};
bool has_configuration=true;
pthread_mutex_t status_mutex=PTHREAD_MUTEX_INITIALIZER;
struct Status {int64_t revision=123;const char* state="applied";}state;
std::array<uint8_t,256> manager{};
bool present=true,live=true;
struct Weak {void* get(bool)const{return present?manager.data():nullptr;}}quality_manager;
Config configuration(bool* has=nullptr){if(has)*has=has_configuration;return current_config;}
bool object_alive(void*,const void*){return live;}
template<class T>T read(void* p,size_t offset){T value{};std::memcpy(&value,static_cast<uint8_t*>(p)+offset,sizeof value);return value;}
template<class T>void put(size_t offset,T value){std::memcpy(manager.data()+offset,&value,sizeof value);}
// PRODUCTION
int main(int argc,char**argv){
    assert(argc==2);std::string scenario=argv[1];
    put(0x20,1.0f);put(0xa0,60.0f);put(0x24,int32_t(30));
    current_config.render_scale=1.5f;current_config.max_buffer_pixel=3072;
    current_config.aa_mode=2;current_config.shadow_resolution=2048;
    current_config.expand_photography=true;current_config.revision=123;
    bool ok=true;int fps=60,quality=30;
    if(scenario=="revision_pending"){state.revision=122;ok=false;}
    if(scenario=="revision_waiting"){state.state="waiting_for_scene";ok=false;}
    if(scenario=="revision_unsupported"){state.state="unsupported";ok=false;}
    if(scenario=="revision_disabled")state.state="disabled";
    if(scenario=="unconfigured_original"){has_configuration=false;state.state="waiting";state.revision=0;}
    if(scenario=="scale_half")put(0x20,.5f);
    if(scenario=="scale_nan")put(0x20,__builtin_nanf(""));
    if(scenario=="fps30"){put(0xa0,30.0f);fps=30;}
    if(scenario=="fps120"){put(0xa0,120.0f);fps=120;}
    if(scenario=="explicit_fps"){
        current_config.custom_graphics=true;current_config.target_fps=90;
        put(0xa0,__builtin_nanf(""));fps=90;
    }
    if(scenario=="explicit_quality"){
        current_config.custom_graphics=true;current_config.quality=100;
        put(0x24,int32_t(0));quality=100;
    }
    if(scenario=="disabled_overrides"){
        current_config.quality=100;current_config.target_fps=120;
    }
    if(scenario=="absent"){present=false;ok=false;}
    if(scenario=="dead"){live=false;ok=false;}
    if(scenario=="fps_nan"){put(0xa0,__builtin_nanf(""));ok=false;}
    if(scenario=="fps_fraction"){put(0xa0,59.5f);ok=false;}
    if(scenario=="fps_zero"){put(0xa0,0.0f);ok=false;}
    if(scenario=="fps_negative"){put(0xa0,-1.0f);ok=false;}
    if(scenario=="fps_unsupported"){put(0xa0,50.0f);ok=false;}
    if(scenario=="scale_not_fps"){put(0x20,60.0f);put(0xa0,1.0f);ok=false;}
    if(scenario=="invalid_quality"){put(0x24,int32_t(1));ok=false;}
    if(scenario=="zero_quality"){put(0x24,int32_t(0));ok=false;}
    const Config before=current_config;const auto bytes=manager;
    idoly_mp4_queue::Graphics out{};assert(mp4_queue_snapshot_graphics(out)==ok);
    assert(std::memcmp(&before,&current_config,sizeof before)==0&&manager==bytes);
    if(ok){
        assert(out.custom_graphics==1&&out.quality==quality&&out.target_fps==fps);
        assert(out.revision==123&&out.render_scale==1.5f&&out.max_buffer_pixel==3072);
        assert(out.aa_mode==2&&out.shadow_resolution==2048&&out.expand_photography==1);
    }
}
'''


@pytest.fixture(scope="module")
def snapshot_binary(tmp_path_factory):
    compiler = shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        pytest.skip("C++ compiler unavailable")
    production = (NATIVE / "bridge.cpp").read_text()
    production = production.split("bool mp4_queue_snapshot_graphics(", 1)[1].split("bool mp4_actual_source_geometry(", 1)[0]
    production = "bool mp4_queue_snapshot_graphics(" + production
    build = tmp_path_factory.mktemp("mp4-graphics-snapshot")
    source = build / "snapshot.cpp"
    source.write_text(HARNESS.replace("// PRODUCTION", production))
    executable = build / "snapshot"
    result = subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                             "-Wno-misleading-indentation", "-I", str(NATIVE), str(source),
                             "-o", str(executable)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    return executable


@pytest.mark.parametrize("scenario", [
    "default", "scale_half", "scale_nan", "fps30", "fps120", "explicit_fps",
    "explicit_quality", "disabled_overrides", "absent", "dead", "fps_nan",
    "fps_fraction", "fps_zero", "fps_negative", "fps_unsupported", "scale_not_fps",
    "invalid_quality", "zero_quality",
    "revision_pending", "revision_waiting", "revision_unsupported", "revision_disabled",
    "unconfigured_original",
])
def test_queue_captures_actual_original_fps_without_mutating_preferences(snapshot_binary, scenario):
    result = subprocess.run([str(snapshot_binary), scenario], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


ORIGINALS = {
    "android": ("android-native.so", "68d4706d14b33d07647b9752124632a44b6a5901c82723beb569d9123df676b3",
                0x8854788, 142935944, 0x8854790, 142935952, 0x8854758, 142935896),
    "ios": ("ios-native.bin", "b03bee7ede0f8e74c84b3e171f79bc3596e074281b42640eb70bd106474ff5bf",
            0x6fad2e8, 117101288, 0x6fad2f0, 117101296, 0x6fad2b8, 117101240),
}
GET_FPS = bytes.fromhex("00a040bdc0035fd6")
SET_FPS = bytes.fromhex("00a000bdc0035fd6")
GET_SCALE = bytes.fromhex("002040bdc0035fd6")


@pytest.mark.parametrize("platform", ORIGINALS)
def test_original_arm64_getter_and_setter_use_fps_field_not_frame_scale(platform):
    from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM
    from unicorn.arm64_const import UC_ARM64_REG_LR, UC_ARM64_REG_X0, UC_ARM64_REG_S0
    # The exact getter/setter instructions are identical in both pinned games.
    assert ORIGINALS[platform][2] != ORIGINALS[platform][6]
    machine = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    machine.mem_map(0x1000, 0x1000)
    machine.mem_map(0x4000, 0x1000)
    machine.mem_write(0x4000 + 0x20, struct.pack("<f", .5))
    machine.mem_write(0x4000 + 0xa0, struct.pack("<f", 60))
    machine.reg_write(UC_ARM64_REG_X0, 0x4000)
    machine.reg_write(UC_ARM64_REG_LR, 0x1800)
    for code, expected in [(GET_FPS, 60), (GET_SCALE, .5)]:
        machine.mem_write(0x1000, code)
        machine.ctl_remove_cache(0x1000, 0x1008)
        machine.emu_start(0x1000, 0x1800, count=4)
        assert struct.unpack("<f", struct.pack("<I", machine.reg_read(UC_ARM64_REG_S0)))[0] == expected
    machine.mem_write(0x1000, SET_FPS)
    machine.ctl_remove_cache(0x1000, 0x1008)
    machine.reg_write(UC_ARM64_REG_S0, struct.unpack("<I", struct.pack("<f", 120))[0])
    machine.emu_start(0x1000, 0x1800, count=4)
    assert struct.unpack("<f", machine.mem_read(0x4000 + 0xa0, 4))[0] == 120
    assert struct.unpack("<f", machine.mem_read(0x4000 + 0x20, 4))[0] == .5


@pytest.mark.parametrize("platform", ORIGINALS)
def test_fps_accessor_bytes_match_complete_pinned_original(platform):
    directory = os.environ.get("IDOLY_MP4_ORIGINALS_DIR")
    if not directory:
        pytest.skip("Set IDOLY_MP4_ORIGINALS_DIR for whole-original comparison")
    filename, sha, _, get_offset, _, set_offset, _, scale_offset = ORIGINALS[platform]
    native = (Path(directory) / filename).read_bytes()
    assert hashlib.sha256(native).hexdigest() == sha
    for offset, code in [(get_offset, GET_FPS), (set_offset, SET_FPS), (scale_offset, GET_SCALE)]:
        assert native[offset:offset + len(code)] == code
