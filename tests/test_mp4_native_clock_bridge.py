"""Execute extracted production bridge wrappers with synthetic Unity callbacks.

Host C++ tests cover call ownership and callback order. ARM64 registry getter
tests execute only the embedded original getter instructions. Profile/linkage
checks below are static evidence, not device or complete PlayerLoop execution.
"""
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "client-presentation/native"
CLOCK_PROFILES = json.loads((NATIVE / "mp4_engine_clock_profile.json").read_text())["platforms"]
EXPECTED = {
    "android": {"update": 0x622000, "get_manager": 0x6225E8, "registry": 0x1497840,
                "vtable": 0x14139C8, "registry_getter": 0x55756C, "caller": 0x64B608},
    "ios": {"update": 0xCAD01C, "get_manager": 0xCAD690, "registry": 0xA85A408,
            "vtable": 0x97EBB78, "registry_getter": 0xBE3C58, "caller": 0xCD5768},
}

HOST_HARNESS = r'''
#include "mp4_engine_clock.hpp"
#include <atomic>
#include <cassert>
#include <cstdio>
#include <string>
#include <type_traits>
#include <vector>
using Method=const void;
using VoidMethod=void(*)(void*,Method*);
std::atomic<bool> ready{true};
std::atomic<bool> mp4_native_clock_source_ready{true},mp4_native_clock_armed{false};
std::atomic<const char*> mp4_native_clock_error{"none"};
bool unity_thread=true,mp4_api_installed=true,observer_result=true,native_manager_verified=true,brain_permitted=true;
unsigned original_calls=0,brain_calls=0;
std::vector<int> order;
bool game_call(bool=false){return unity_thread;}
struct Manager {alignas(8) uint8_t bytes[0x200]{};};
Manager one,two;void* current_manager=&one;void* expected_manager=&one;double expected_wall=1000.1250000000001;
void* brain=reinterpret_cast<void*>(0x11223344);
Method* brain_method=reinterpret_cast<Method*>(0x55667788);
bool mp4_camera_permit_brain(void* value){assert(value==brain);return brain_permitted;}
template<class T>T get(void* p,size_t at){T value{};memcpy(&value,static_cast<uint8_t*>(p)+at,sizeof value);return value;}
template<class T>void put(void* p,size_t at,T value){memcpy(static_cast<uint8_t*>(p)+at,&value,sizeof value);}
uint64_t bits(double value){uint64_t result;memcpy(&result,&value,sizeof result);return result;}
bool manager_current(void* p){return p==current_manager;}
bool mp4_native_current_manager(void* p){return native_manager_verified&&manager_current(p);}
void native_original(void* manager,double wall){
    assert(manager==expected_manager&&bits(wall)==bits(expected_wall));
    ++original_calls;order.push_back(1);
    put(manager,0xc8,get<uint64_t>(manager,0xc8)+1);
    put(manager,0xd0,get<uint32_t>(manager,0xd0)+1);
    if(get<uint8_t>(manager,0xf8))return;
    put(manager,0x60,wall-940.);put(manager,0x70,wall-900.);
    put(manager,0x90,wall-940.);put(manager,0xa0,wall-900.);
    for(size_t at:{size_t(0x78),size_t(0x7c),size_t(0x80),size_t(0xa8),size_t(0xac),size_t(0xb0)})put(manager,at,9.f);
}
void alternate_original(void*,double){assert(false&&"rejected installation replaced the original");}
void brain_original(void* value,Method* method){
    assert(value==brain&&method==brain_method);++brain_calls;order.push_back(1);
}
void seed(Manager& manager){
    for(size_t at:{size_t(0x30),size_t(0x38),size_t(0x60),size_t(0x68),size_t(0x90),size_t(0x98)})put(&manager,at,60.);
    for(size_t at:{size_t(0x40),size_t(0x70),size_t(0xa0)})put(&manager,at,100.);
    put(&manager,0x48,.02f);put(&manager,0xfc,.5f);put(&manager,0xe0,940.);put(&manager,0xe8,900.);put(&manager,0xf0,-50.);
    put(&manager,0xc8,uint64_t(99));put(&manager,0xd0,uint32_t(17));
}
namespace idoly_mp4_runtime {
// ACTUAL_RUNTIME
struct FakeGame {
    bool original_camera_updated(void* value){
        assert(value==brain&&brain_calls==1&&order==std::vector<int>{1});
        order.push_back(2);return observer_result;
    }
} game;
}
// ORIGINAL_DECLARATION
// ACTUAL_HOOKS
static_assert(std::is_same<decltype(mp4_native_time_original),void(*)(void*,double)>::value,"native original double ABI differs");
static_assert(std::is_same<decltype(&mp4_native_time_hook),void(*)(void*,double)>::value,"native hook double ABI differs");
static_assert(std::is_same<decltype(mp4_brain_update_original),VoidMethod>::value,"ManualUpdate original ABI differs");
static_assert(std::is_same<decltype(&mp4_brain_update_hook),VoidMethod>::value,"ManualUpdate hook ABI differs");
int main(int argc,char** argv){
    assert(argc==2);std::string mode=argv[1];seed(one);seed(two);
    assert(bits(static_cast<double>(static_cast<float>(expected_wall)))!=bits(expected_wall));
    mp4_native_time_original=native_original;mp4_brain_update_original=brain_original;
    if(mode.rfind("brain_",0)==0){
        if(mode=="brain_not_ready")ready=false;
        if(mode=="brain_wrong_thread")unity_thread=false;
        if(mode=="brain_api_missing")mp4_api_installed=false;
        if(mode=="brain_observer_false")observer_result=false;
        if(mode=="brain_owned_update_blocked")brain_permitted=false;
        mp4_brain_update_hook(brain,brain_method);
        if(!brain_permitted){assert(!brain_calls&&!original_calls&&order.empty());return 0;}
        const bool observed=mode=="brain_ready"||mode=="brain_observer_false";
        assert(brain_calls==1&&original_calls==0);
        assert(order==(observed?std::vector<int>{1,2}:std::vector<int>{1}));return 0;
    }
    using namespace idoly_mp4_runtime;
    assert(!native_clock_available());
    if(mode=="invalid_install")assert(!install_native_clock({nullptr,native_original}));
    else if(mode!="not_installed")assert(install_native_clock({mp4_native_current_manager,native_original}));
    if(mode=="reinstall")assert(!install_native_clock({manager_current,alternate_original}));
    mp4_native_clock_armed.store(mode!="not_armed"&&mode!="first_verified");
    if(mode=="not_armed")native_manager_verified=false;
    if(mode=="source_unready")mp4_native_clock_source_ready=false;
    if(mode=="wrong_thread")unity_thread=false;
    if(mode=="native_before_ui_ready")ready=false;
    auto& scope=native_clock_scope();
    const bool active=mode=="active"||mode.rfind("runtime_false_",0)==0;
    if(active)assert(scope.acquire(&one,1000.,60)&&scope.held());
    const Manager before=one;
    const char* failure=nullptr;
    if(mode=="runtime_false_owner_replaced"){
        current_manager=&two;expected_manager=&two;failure="engine_clock_owner_replaced";
    }else if(mode=="runtime_false_paused"){
        put(&one,0xf8,uint8_t(1));failure="engine_clock_engine_paused";
    }else if(mode=="runtime_false_settings_changed"){
        put(&one,0xfc,.4f);failure="engine_clock_settings_changed";
    }else if(mode=="runtime_false_wall_reversed"){
        expected_wall=999.;failure="engine_clock_wall_timestamp_invalid";
    }else if(mode=="runtime_false_manager_unverified"){
        native_manager_verified=false;failure="engine_clock_owner_replaced";
    }
    mp4_native_time_hook(expected_manager,expected_wall);
    assert(original_calls==1&&brain_calls==0&&order==std::vector<int>{1});
    assert(get<uint64_t>(expected_manager,0xc8)==100&&get<uint32_t>(expected_manager,0xd0)==18);
    const bool direct=mode=="not_installed"||mode=="invalid_install"||mode=="not_armed"||mode=="wrong_thread"||mode=="source_unready";
    assert(scope.latest_manager()==(direct?nullptr:expected_manager));
    if(mode=="not_armed"||mode=="runtime_false_manager_unverified")assert(!strcmp(mp4_native_clock_error.load(),"native_clock_manager_unverified"));
    if(mode=="not_armed")assert(!mp4_native_clock_armed.load());
    if(mode=="first_verified")assert(mp4_native_clock_armed.load());
    if(failure)assert(!strcmp(scope.error(),failure));
    if(mode=="runtime_false_owner_replaced")assert(!memcmp(&one,&before,sizeof one)&&!scope.active());
    if(mode=="runtime_false_settings_changed"||mode=="runtime_false_manager_unverified")assert(!scope.active());
    if(mode=="active"||mode=="runtime_false_paused"||mode=="runtime_false_wall_reversed"){
        assert(scope.active()&&scope.held()&&!scope.have_tick());
        assert(get<double>(&one,0x60)==60.&&get<double>(&one,0x70)==100.);
        assert(get<float>(&one,0x7c)==0.f&&get<float>(&one,0xac)==0.f);
    }
    if(mode=="inactive"||mode=="reinstall"||mode=="native_before_ui_ready"||mode=="first_verified"){
        assert(!scope.active()&&scope.last_wall_timestamp()==expected_wall);
        assert(get<double>(&one,0x70)==expected_wall-900.);
    }
}
'''


@pytest.fixture(scope="module")
def bridge_binary(tmp_path_factory):
    compiler = shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")
    if compiler is None:
        pytest.skip("A host C++ compiler is required for extracted bridge execution")
    bridge = (NATIVE / "bridge.cpp").read_text()
    hooks = bridge.split("// BEGIN_MP4_NATIVE_CLOCK_HOOKS", 1)[1].split("// END_MP4_NATIVE_CLOCK_HOOKS", 1)[0]
    runtime = (NATIVE / "mp4_runtime.hpp").read_text()
    begin = runtime.index("static idoly_mp4_engine_clock::Scope native_engine_clock;")
    runtime = runtime[begin:runtime.index("using idoly_mp4_game::Api;", begin)]
    validation = bridge.split("// BEGIN_MP4_NATIVE_CLOCK_VALIDATION", 1)[1].split("// END_MP4_NATIVE_CLOCK_VALIDATION", 1)[0]
    original = re.search(r"using Mp4NativeTime=[^;]+;\s*Mp4NativeTime mp4_native_time_original[^;]*;", validation)
    assert original is not None, "The actual native-clock original typedef/declaration is required"
    source = HOST_HARNESS.replace("// ACTUAL_RUNTIME", runtime).replace("// ACTUAL_HOOKS", hooks).replace("// ORIGINAL_DECLARATION", original.group())
    directory = tmp_path_factory.mktemp("mp4-native-clock-bridge")
    path, binary = directory / "bridge.cpp", directory / "bridge"
    path.write_text(source)
    result = subprocess.run([compiler, "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror", "-I", str(NATIVE),
                             str(path), "-o", str(binary)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    return binary


@pytest.mark.parametrize("mode", ["not_installed", "invalid_install", "not_armed", "first_verified", "source_unready", "wrong_thread", "inactive",
                                  "native_before_ui_ready", "reinstall", "active", "runtime_false_owner_replaced",
                                  "runtime_false_paused", "runtime_false_settings_changed", "runtime_false_wall_reversed",
                                  "runtime_false_manager_unverified"])
def test_extracted_bridge_calls_the_typed_native_original_once_even_on_runtime_failure(bridge_binary, mode):
    result = subprocess.run([str(bridge_binary), mode], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("mode", ["brain_ready", "brain_not_ready", "brain_wrong_thread", "brain_api_missing", "brain_observer_false", "brain_owned_update_blocked"])
def test_extracted_manual_update_calls_original_before_camera_observation(bridge_binary, mode):
    result = subprocess.run([str(bridge_binary), mode], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("platform", ["android", "ios"])
def test_clock_profile_static_registry_vtable_and_timestamp_proof_scalars(platform):
    profile, expected = CLOCK_PROFILES[platform], EXPECTED[platform]
    assert profile["schema"] == 1 and profile["platform"] == platform
    assert profile["native_abi"] == "void(TimeManager*, double nativeWallTimestampInD0)"
    assert re.fullmatch(r"[0-9a-f]{64}", profile["source"]["native_sha256"])
    assert profile["source"]["native_bytes"] > 0
    assert int(profile["bindings"]["update"]["rva"], 16) == expected["update"]
    assert int(profile["bindings"]["get_manager"]["rva"], 16) == expected["get_manager"]
    assert int(profile["registry_slot_rva"], 16) == expected["registry"]
    assert int(profile["manager_vtable_rva"], 16) == expected["vtable"]
    assert profile["vtable_update_offset"] == 0xC0
    assert int(profile["registry_getter"]["rva"], 16) == expected["registry_getter"]
    assert int(profile["native_update_caller"]["rva"], 16) == expected["caller"]
    assert len(bytes.fromhex(profile["registry_getter"]["bytes"])) == 16
    caller = bytes.fromhex(profile["native_update_caller"]["bytes"])
    assert bytes.fromhex("016140f9") in caller  # LDR X1,[X8,#0xC0]
    assert caller.endswith(bytes.fromhex("20001fd6"))  # BR X1
    assert profile["bindings"]["update"]["body"].startswith(profile["bindings"]["update"]["prefix"])


@pytest.mark.parametrize("platform", ["android", "ios"])
def test_embedded_original_registry_getter_executes_the_exact_time_manager_slot(platform):
    unicorn = pytest.importorskip("unicorn")
    from unicorn import arm64_const as registers

    profile = CLOCK_PROFILES[platform]
    machine = unicorn.Uc(unicorn.UC_ARCH_ARM64, unicorn.UC_MODE_ARM)
    machine.ctl_set_tcg_buffer_size(16 * 1024 * 1024)
    pages = set()

    def write(address, raw):
        for page in range(address & ~4095, (address + len(raw) + 4095) & ~4095, 4096):
            if page not in pages:
                machine.mem_map(page, 4096)
                pages.add(page)
        machine.mem_write(address, raw)

    getter = profile["bindings"]["get_manager"]
    registry = int(profile["registry_slot_rva"], 16)
    manager, stop = 0x20000000, 0x30000000
    write(int(getter["rva"], 16), bytes.fromhex(getter["body"]))
    write(int(profile["registry_getter"]["rva"], 16), bytes.fromhex(profile["registry_getter"]["bytes"]))
    # Distinct neighboring registry values expose an incorrect manager index.
    write(registry - 7 * 8, struct.pack("<8Q", *range(0x11110000, 0x11110007), manager))
    write(stop, bytes.fromhex("c0035fd6"))
    reads = []

    def read_slot(_machine, _access, address, size, _value, _data):
        reads.append((address, size))

    machine.hook_add(unicorn.UC_HOOK_MEM_READ, read_slot)
    machine.reg_write(registers.UC_ARM64_REG_X0, 0xDEADBEEF)
    machine.reg_write(registers.UC_ARM64_REG_X30, stop)
    machine.emu_start(int(getter["rva"], 16), stop, count=20)
    assert machine.reg_read(registers.UC_ARM64_REG_PC) == stop
    assert machine.reg_read(registers.UC_ARM64_REG_X0) == manager
    assert reads == [(registry, 8)]


@pytest.mark.parametrize("platform", ["android", "ios"])
def test_hook_profiles_statically_link_the_exact_native_and_brain_originals(platform):
    path = NATIVE / "profile.json" if platform == "android" else ROOT / "client-presentation/ios/profile.json"
    aliases = json.loads(path.read_text())["aliases"]
    brain = aliases["mp4_brain_update"]
    original = CLOCK_PROFILES[platform]["bindings"]["update"]
    if platform == "ios":
        clock = aliases["mp4_native_time"]
        assert clock["rva"] == int(original["rva"], 16)
        assert clock["prefix16"] == original["prefix"]
        assert clock["native_abi"] == CLOCK_PROFILES[platform]["native_abi"]
        assert clock["native_parameter_registers"] == {"manager": "X0", "nativeWallTimestamp": "D0"}
    else:
        # The Android native TimeManager belongs to a separately retained
        # libunity image, never this managed libil2cpp alias/base table.
        assert "mp4_native_time" not in aliases
    game_name = "mp4_game_profile.json" if platform == "android" else "mp4_game_ios_profile.json"
    method = json.loads((NATIVE / game_name).read_text())["methods"]["brain_manual_update"]
    assert int(brain["rva"], 16) == int(method["rva"], 16) if platform == "android" else brain["rva"] == int(method["rva"], 16)
    assert brain["prefix16"] == method["prefix"]
    assert brain["name"] == "Cinemachine.CinemachineBrain.ManualUpdate"
    assert brain["parameter_count"] == 0 and brain["parameters"] == []
    assert brain["return_type"] == "System.Void" and not brain["method_flags"] & 0x10
    installer = (NATIVE / "bridge.cpp" if platform == "android" else ROOT / "client-presentation/ios/static_install.hpp").read_text()
    for name in (("mp4_native_time", "mp4_brain_update") if platform == "ios" else ("mp4_brain_update",)):
        assert re.search(r"\bHOOK\(\s*" + name + r"\s*,\s*" + name + r"_hook\s*,\s*" + name + r"_original\s*\)", installer)
    if platform == "android":
        assert 'mp4_native_source_matches(held.name)' in installer
        assert 'mp4_native_base+mp4_native_profile.update.rva' in installer
        assert 'mp4_held_native_library=dlopen(first.name,RTLD_NOW|RTLD_NOLOAD)' in installer
