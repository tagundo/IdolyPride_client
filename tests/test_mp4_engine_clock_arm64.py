"""Run the compiled clock Scope against unchanged original ARM64 time kernels."""
import importlib.util
import json
import os
from pathlib import Path
import struct
import subprocess

import pytest

unicorn = pytest.importorskip("unicorn")
from unicorn import arm64_const as regs

ROOT = Path(__file__).resolve().parents[1]
PROFILE = json.loads((ROOT / "client-presentation/native/mp4_engine_clock_profile.json").read_text())["platforms"]
MANAGER, SCOPE, STOP, STACK = 0x20000000, 0x21000000, 0x30000000, 0x40000000

WRAPPER = r'''
#include "mp4_engine_clock.hpp"
#include <new>
using namespace idoly_mp4_engine_clock;
extern "C" void* memcpy(void* target,const void* source,size_t count){auto*d=static_cast<volatile unsigned char*>(target);auto*s=static_cast<const volatile unsigned char*>(source);while(count--)*d++=*s++;return target;}
extern "C" void* memset(void* target,int value,size_t count){auto*d=static_cast<volatile unsigned char*>(target);while(count--)*d++=static_cast<unsigned char>(value);return target;}
extern "C" int strcmp(const char* left,const char* right){while(*left&&*left==*right){++left;++right;}return static_cast<unsigned char>(*left)-static_cast<unsigned char>(*right);}
bool valid(void* value){return reinterpret_cast<uintptr_t>(value)==0x20000000;}
extern "C" __attribute__((visibility("default"))) int construct(void* memory){auto* scope=new(memory)Scope;return scope->install({valid,reinterpret_cast<void(*)(void*,double)>(ORIGINAL_UPDATE)});}
extern "C" __attribute__((visibility("default"))) int acquire(void* memory,uint32_t hz,double wall){return static_cast<Scope*>(memory)->acquire(reinterpret_cast<void*>(0x20000000),wall,hz);}
extern "C" __attribute__((visibility("default"))) int held(void* memory){return static_cast<Scope*>(memory)->held();}
extern "C" __attribute__((visibility("default"))) int tick(void* memory,uint64_t index,uint32_t advance,double wall){return static_cast<Scope*>(memory)->native_tick(reinterpret_cast<void*>(0x20000000),wall,{advance!=0,index});}
extern "C" __attribute__((visibility("default"))) int restore(void* memory,uint32_t scene,double wall){return static_cast<Scope*>(memory)->restore(reinterpret_cast<void*>(0x20000000),wall,scene!=0);}
extern "C" __attribute__((visibility("default"))) int rebase(void* memory,uint32_t scene,double wall){return static_cast<Scope*>(memory)->rebase_for_restore(reinterpret_cast<void*>(0x20000000),wall,scene!=0);}
extern "C" __attribute__((visibility("default"))) int hold_boundary(void* memory,double wall){return static_cast<Scope*>(memory)->hold_for_boundary(reinterpret_cast<void*>(0x20000000),wall);}
extern "C" __attribute__((visibility("default"))) int quiescent(void* memory,uint32_t value){return static_cast<Scope*>(memory)->set_owned_loop_quiescent(value!=0);}
extern "C" __attribute__((visibility("default"))) int replaced(void* memory,double wall){return static_cast<Scope*>(memory)->native_tick(reinterpret_cast<void*>(0x20000800),wall);}
'''


def compiler_path():
    explicit = os.environ.get("IDOLY_MP4_NDK_CLANG")
    if explicit:
        return Path(explicit)
    base = Path(os.environ.get("ANDROID_NDK_HOME", "/workspace/.setup/android-sdk/ndk/26.3.11579264"))
    return base / "toolchains/llvm/prebuilt/linux-x86_64/bin/clang++"


@pytest.fixture(scope="module", params=["android", "ios"])
def compiled_scope(request, tmp_path_factory):
    compiler = compiler_path()
    if not compiler.is_file():
        pytest.skip("ARM64 NDK compiler unavailable; host clock protocol tests remain independent")
    profile = PROFILE[request.param]
    folder = tmp_path_factory.mktemp("mp4-clock-arm64-" + request.param)
    source, binary = folder / "scope.cpp", folder / "scope.so"
    source.write_text(WRAPPER)
    result = subprocess.run([str(compiler), "--target=aarch64-linux-android26", "-std=c++17", "-O2",
        "-fPIC", "-fno-exceptions", "-fno-rtti", "-ffreestanding", "-fno-builtin", "-fvisibility=hidden",
        "-nostdlib", "-shared", "-Wl,-Bsymbolic", "-Wl,--no-undefined", "-Wl,-Ttext=0x10000000",
        "-DORIGINAL_UPDATE=" + profile["bindings"]["update"]["rva"],
        "-I", str(ROOT / "client-presentation/native"), str(source), "-o", str(binary)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return profile, binary.read_bytes()


class Engine:
    def __init__(self, profile, binary):
        self.profile = profile
        self.machine = unicorn.Uc(unicorn.UC_ARCH_ARM64, unicorn.UC_MODE_ARM)
        self.pages = set()
        assert binary[:6] == b"\x7fELF\x02\x01"
        phoff = struct.unpack_from("<Q", binary, 32)[0]
        phsize, phcount = struct.unpack_from("<HH", binary, 54)
        for index in range(phcount):
            kind, _, offset, address, _, size, memory, _ = struct.unpack_from("<II6Q", binary, phoff + index * phsize)
            if kind == 1:
                self.map(address, binary[offset:offset + size], memory)
        shoff = struct.unpack_from("<Q", binary, 40)[0]
        shsize, shcount = struct.unpack_from("<HH", binary, 58)
        sections = [struct.unpack_from("<II4QII2Q", binary, shoff + index * shsize) for index in range(shcount)]
        self.symbols = {}
        for section in sections:
            if section[1] != 2:
                continue
            strings = sections[section[6]]
            names = binary[strings[4]:strings[4] + strings[5]]
            for offset in range(section[4], section[4] + section[5], section[9]):
                name, _, _, defined, value, _ = struct.unpack_from("<IBBHQQ", binary, offset)
                if defined:
                    self.symbols[names[name:].split(b"\0", 1)[0].decode()] = value
        for entry in profile["bindings"].values():
            self.map(int(entry["rva"], 16), bytes.fromhex(entry["body"]))
        for entry in profile["kernel_constants"]:
            self.map(int(entry["rva"], 16), bytes.fromhex(entry["bytes"]))
        self.map(MANAGER, bytes(0x1000))
        self.map(SCOPE, bytes(0x1000))
        self.map(STOP, bytes.fromhex("c0035fd6"))
        self.map(STACK, bytes(0x10000))
        self.kernel_calls = 0

        def entered(machine, address, size, user):
            self.kernel_calls += 1

        address = int(profile["bindings"]["update"]["rva"], 16)
        self.machine.hook_add(unicorn.UC_HOOK_CODE, entered, begin=address, end=address)
        self.seed()

    def map(self, address, raw, size=None):
        size = max(len(raw), size or 0)
        for page in range(address & ~4095, (address + size + 4095) & ~4095, 4096):
            if page not in self.pages:
                self.machine.mem_map(page, 4096)
                self.pages.add(page)
        self.machine.mem_write(address, raw)

    def seed(self):
        for field, value in [(0x30, 59.98), (0x38, 59.96), (0x40, 99.98),
                (0x60, 60.), (0x68, 59.98), (0x70, 100.), (0x90, 60.), (0x98, 59.98),
                (0xa0, 100.), (0xe0, 940.), (0xe8, 900.), (0xf0, -50.)]:
            self.put(field, "d", value)
        for field, value in [(0x48, .02), (0x4c, .02), (0x50, .02), (0x58, 50.),
                (0x78, .02), (0x7c, .02), (0x80, .02), (0x84, 1.), (0x88, 50.),
                (0xa8, .02), (0xac, .02), (0xb0, .02), (0xb4, 1.), (0xb8, 50.),
                (0xfc, .5), (0x100, .3333333), (0x104, .03)]:
            self.put(field, "f", value)
        self.put(0xc8, "Q", 99)
        self.put(0xd0, "I", 17)
        assert self.call("construct", SCOPE) == 1

    def put(self, field, kind, value):
        self.machine.mem_write(MANAGER + field, struct.pack("<" + kind, value))

    def get(self, field, kind):
        return struct.unpack("<" + kind, self.machine.mem_read(MANAGER + field, struct.calcsize(kind)))[0]

    def call(self, method, *arguments, wall=0.):
        for index, value in enumerate(arguments):
            self.machine.reg_write(regs.UC_ARM64_REG_X0 + index, value)
        self.machine.reg_write(regs.UC_ARM64_REG_D0, struct.unpack("<Q", struct.pack("<d", wall))[0])
        self.machine.reg_write(regs.UC_ARM64_REG_X30, STOP)
        self.machine.reg_write(regs.UC_ARM64_REG_SP, STACK + 0xff00)
        address = self.symbols[method] if isinstance(method, str) else method
        self.machine.emu_start(address, STOP, count=50000)
        return self.machine.reg_read(regs.UC_ARM64_REG_X0)


@pytest.mark.parametrize("hz", [60, 120])
def test_compiled_scope_drives_original_native_kernel_and_restores_wall_clock(compiled_scope, hz):
    engine = Engine(*compiled_scope)
    assert engine.call("acquire", SCOPE, hz, wall=1000.) == 1
    for index, advance, wall in [(0, 0, 1000.01), (0, 1, 1000.2), (1, 1, 1003.),
            (1, 0, 1005.), (1, 0, 1010.), (2, 1, 1012.)]:
        assert engine.call("tick", SCOPE, index, advance, wall=wall) == 1
        assert engine.get(0x60, "d") == pytest.approx(60. + index / hz, abs=1e-12)
        assert engine.get(0x70, "d") == pytest.approx(100. + index / hz, abs=1e-12)
        delta = 1 / hz if advance and index else 0
        for offset in [0x78, 0x7c, 0x80, 0xa8, 0xac, 0xb0]:
            assert engine.get(offset, "f") == pytest.approx(delta, abs=1e-8)
    assert engine.kernel_calls == 6
    assert engine.get(0xc8, "Q") == 105 and engine.get(0xd0, "I") == 23
    assert engine.call("restore", SCOPE, 1, wall=1012.) == 1
    assert engine.get(0xc8, "Q") == 105
    assert engine.get(0xe0, "d") == 952 and engine.get(0xe8, "d") == 912
    assert engine.get(0xf0, "d") == -50 and engine.get(0xd8, "f") == 0
    assert engine.get(0xfc, "f") == .5
    assert engine.call("tick", SCOPE, 0, 0, wall=1012.01) == 1
    assert engine.kernel_calls == 7 and engine.get(0xc8, "Q") == 106
    assert engine.get(0x60, "d") == pytest.approx(60.005, abs=1e-7)
    assert engine.get(0x70, "d") == pytest.approx(100.01, abs=1e-7)


def test_compiled_acquire_zeroes_all_delta_before_first_native_tick(compiled_scope):
    engine = Engine(*compiled_scope)
    assert engine.call("acquire", SCOPE, 60, wall=1000.) == 1
    assert engine.call("held", SCOPE) == 1
    assert engine.kernel_calls == 0 and engine.get(0xc8, "Q") == 99
    for offset in [0x78, 0x7c, 0x80, 0xa8, 0xac, 0xb0]:
        assert engine.get(offset, "f") == 0
    engine.put(0xac, "f", .1)
    assert engine.call("held", SCOPE) == 0
    engine.put(0xac, "f", 0.)
    assert engine.call("held", SCOPE) == 1
    assert engine.call("tick", SCOPE, 0, 1, wall=1001.) == 1
    assert engine.kernel_calls == 1 and engine.get(0xc8, "Q") == 100


def test_compiled_scope_no_grant_leaves_original_fixed_loop_no_extra_work(compiled_scope):
    engine = Engine(*compiled_scope)
    assert engine.call("acquire", SCOPE, 60, wall=1000.) == 1
    assert engine.call("tick", SCOPE, 0, 1, wall=1000.1) == 1
    assert engine.call("tick", SCOPE, 1, 1, wall=1009.) == 1
    work = int(engine.profile["bindings"]["fixed_work"]["rva"], 16)
    tick = int(engine.profile["bindings"]["fixed_tick"]["rva"], 16)
    assert engine.call(work, MANAGER) == 1 and engine.call(tick, MANAGER) == 1
    assert engine.call(work, MANAGER) == 0
    # The original fixed loop's terminating false call restores the normal
    # rendered clock after its temporary fixed-step clock and clears F9.
    assert engine.call(tick, MANAGER) == 0
    assert engine.get(0xf9, "B") == 0
    assert engine.get(0xa8, "f") == pytest.approx(1 / 60)
    for wall in [1010., 1015.]:
        assert engine.call("tick", SCOPE, 1, 0, wall=wall) == 1
        assert engine.call(work, MANAGER) == 0
        assert engine.call(tick, MANAGER) == 0
        assert engine.get(0xa8, "f") == 0 and engine.get(0xac, "f") == 0
    assert engine.get(0x48, "f") == pytest.approx(.02)


def test_compiled_scope_new_scene_preserves_its_time_origin(compiled_scope):
    engine = Engine(*compiled_scope)
    assert engine.call("acquire", SCOPE, 60, wall=1000.) == 1
    assert engine.call("quiescent", SCOPE, 1) == 1
    assert engine.call("tick", SCOPE, 0, 1, wall=1000.1) == 1
    assert engine.call("tick", SCOPE, 1, 1, wall=1005.) == 1
    virtual = engine.get(0x60, "d")
    reset = int(engine.profile["bindings"]["level_reset"]["rva"], 16)
    engine.call(reset, MANAGER)
    assert engine.get(0xf0, "d") == -virtual
    # A replacement initializer can run before old-job cleanup completes. Its
    # time origin and frame receipt must survive cleanup-only release, rather
    # than being combined with the old scene's saved epoch/counters.
    source_frame = engine.get(0xc8, "Q")
    assert engine.call("hold_boundary", SCOPE, wall=1007.) == 0
    assert engine.get(0x60, "d") == virtual and engine.get(0xc8, "Q") == source_frame
    assert engine.call("restore", SCOPE, 0, wall=1010.) == 1
    assert engine.get(0x60, "d") + engine.get(0xf0, "d") == 0
    assert engine.get(0xe0, "d") == pytest.approx(1010. - virtual)
    assert engine.get(0xc8, "Q") == source_frame
    assert engine.call("tick", SCOPE, 0, 0, wall=1010.01) == 1
    # Original level_reset's one-shot deliberately holds the first scaled
    # sample; the next sample accounts for the elapsed time at source scale.
    assert engine.get(0x60, "d") + engine.get(0xf0, "d") == 0
    assert engine.get(0xc8, "Q") == source_frame + 1
    assert engine.call("tick", SCOPE, 0, 0, wall=1010.02) == 1
    assert engine.get(0x60, "d") + engine.get(0xf0, "d") == pytest.approx(.01, abs=1e-7)
    assert engine.get(0xc8, "Q") == source_frame + 2


def test_compiled_scope_native_pause_preserves_counters_without_consuming_grant(compiled_scope):
    engine = Engine(*compiled_scope)
    assert engine.call("acquire", SCOPE, 60, wall=1000.) == 1
    assert engine.call("tick", SCOPE, 0, 1, wall=1000.1) == 1
    engine.put(0xf8, "B", 1)
    assert engine.call("tick", SCOPE, 1, 1, wall=1009.) == 0
    assert engine.get(0xc8, "Q") == 101 and engine.kernel_calls == 2
    assert engine.get(0x60, "d") == 60 and engine.get(0x70, "d") == 100
    assert engine.get(0xa8, "f") == 0 and engine.get(0xb0, "f") == 0
    engine.put(0xf8, "B", 0)
    assert engine.call("tick", SCOPE, 1, 1, wall=1010.) == 1
    assert engine.get(0x60, "d") == pytest.approx(60 + 1 / 60)
    assert engine.get(0xc8, "Q") == 102 and engine.kernel_calls == 3


def test_original_fixed_cache_refresh_writes_float32_fields_not_doubles(compiled_scope):
    engine = Engine(*compiled_scope)
    engine.put(0x50, "Q", 0x1122334455667788)
    engine.put(0x58, "Q", 0x1234567890ABCDEF)
    method = int(engine.profile["bindings"]["fixed_cache_refresh"]["rva"], 16)
    engine.call(method, MANAGER)
    assert engine.get(0x50, "f") == pytest.approx(.02)
    assert engine.get(0x58, "f") == pytest.approx(50.)
    assert engine.get(0x54, "I") == 0x11223344
    assert engine.get(0x5c, "I") == 0x12345678


def test_compiled_scope_rebases_held_source_epoch_before_graph_restore(compiled_scope):
    engine = Engine(*compiled_scope)
    assert engine.call("acquire", SCOPE, 60, wall=1000.) == 1
    assert engine.call("tick", SCOPE, 0, 1, wall=1000.1) == 1
    assert engine.call("tick", SCOPE, 1, 1, wall=1003.) == 1
    assert engine.call("rebase", SCOPE, 1, wall=1003.) == 0  # Not held yet.
    assert engine.call("tick", SCOPE, 1, 0, wall=1009.) == 1
    count = engine.kernel_calls
    assert engine.call("rebase", SCOPE, 1, wall=1009.) == 1
    assert engine.kernel_calls == count and engine.call("held", SCOPE) == 1
    assert engine.get(0x60, "d") == 60 and engine.get(0x70, "d") == 100
    assert engine.get(0xd8, "f") == pytest.approx(1 / 60) and engine.get(0xfc, "f") == 1
    assert engine.call("tick", SCOPE, 1, 0, wall=1010.) == 1
    assert engine.get(0x60, "d") == 60 and engine.get(0xb0, "f") == 0
    assert engine.call("restore", SCOPE, 1, wall=1012.) == 1
    assert engine.get(0x60, "d") == 60 and engine.get(0xa8, "f") == 0
    assert engine.call("tick", SCOPE, 0, 0, wall=1012.01) == 1
    assert engine.get(0x60, "d") == pytest.approx(60.005, abs=1e-7)


def test_explicit_owned_quiescence_holds_native_counters_and_restores_normal_ticks(compiled_scope):
    engine = Engine(*compiled_scope)
    assert engine.call("acquire", SCOPE, 60, wall=1000.) == 1
    assert engine.call("quiescent", SCOPE, 1) == 1
    engine.put(0xc1, "B", 1)
    assert engine.call("tick", SCOPE, 0, 0, wall=1001.) == 1
    assert engine.kernel_calls == 0 and engine.get(0xc8, "Q") == 99 and engine.get(0xc1, "B") == 1
    assert engine.call("tick", SCOPE, 0, 1, wall=1002.) == 1
    assert engine.kernel_calls == 1 and engine.get(0xc1, "B") == 0
    assert engine.call("tick", SCOPE, 1, 1, wall=1003.) == 1
    assert engine.call("hold_boundary", SCOPE, wall=1004.) == 1
    assert engine.kernel_calls == 2 and engine.call("held", SCOPE) == 1
    engine.put(0xf8, "B", 1)
    assert engine.call("tick", SCOPE, 2, 1, wall=1005.) == 0
    assert engine.kernel_calls == 2 and engine.get(0xc8, "Q") == 101
    engine.put(0xf8, "B", 0)
    assert engine.call("tick", SCOPE, 2, 1, wall=1006.) == 1
    assert engine.get(0x60, "d") == pytest.approx(60 + 2 / 60)
    assert engine.call("hold_boundary", SCOPE, wall=1007.) == 1
    assert engine.call("rebase", SCOPE, 1, wall=1007.) == 1
    assert engine.call("tick", SCOPE, 2, 0, wall=1010.) == 1
    assert engine.kernel_calls == 3 and engine.get(0xc8, "Q") == 102
    assert engine.call("restore", SCOPE, 1, wall=1012.) == 1
    assert engine.call("tick", SCOPE, 0, 0, wall=1012.01) == 1
    assert engine.kernel_calls == 4 and engine.get(0xc8, "Q") == 103
    assert engine.get(0x60, "d") == pytest.approx(60.005, abs=1e-7)


def test_passive_preparation_does_not_hold_native_frame_progress(compiled_scope):
    engine = Engine(*compiled_scope)
    assert engine.call("quiescent", SCOPE, 1) == 0  # No acquired owner.
    assert engine.call("tick", SCOPE, 0, 0, wall=1000.1) == 1
    assert engine.call("tick", SCOPE, 0, 0, wall=1000.2) == 1
    assert engine.kernel_calls == 2 and engine.get(0xc8, "Q") == 101


def test_manager_replacement_releases_quiescent_policy_before_forwarding(compiled_scope):
    engine = Engine(*compiled_scope)
    initial = bytes(engine.machine.mem_read(MANAGER, 0x500))
    engine.machine.mem_write(MANAGER + 0x800, initial)
    assert engine.call("acquire", SCOPE, 60, wall=1000.) == 1
    assert engine.call("quiescent", SCOPE, 1) == 1
    owned = bytes(engine.machine.mem_read(MANAGER, 0x500))
    assert engine.call("replaced", SCOPE, wall=1001.) == 0
    assert bytes(engine.machine.mem_read(MANAGER, 0x500)) == owned
    assert engine.get(0x800 + 0xc8, "Q") == 100 and engine.kernel_calls == 1
    assert engine.call("replaced", SCOPE, wall=1001.1) == 1
    assert engine.get(0x800 + 0xc8, "Q") == 101 and engine.kernel_calls == 2


def test_engine_profile_header_matches_generated_original_bindings():
    path = ROOT / "tools/audit_mp4_engine_clock.py"
    spec = importlib.util.spec_from_file_location("clock_audit", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.render_scope_header(PROFILE) == (ROOT / "client-presentation/native/mp4_engine_clock.hpp").read_text()
    for profile in PROFILE.values():
        assert profile["layout"]["capture_delta"] == {"offset": 216, "kind": "float"}
        assert profile["preserve"]["native_frame_counter"]["offset"] == 0xc8
        assert profile["layout"]["level_offset"]["offset"] == 0xf0


def test_whole_original_engines_and_embedded_instruction_regions_when_available():
    directory = os.environ.get("IDOLY_MP4_ORIGINALS_DIR")
    if not directory:
        pytest.skip("Whole-original archive cache not supplied; embedded unchanged kernels execute above")
    import sys
    sys.path.insert(0, str(ROOT / "tools"))
    from audit_mp4_engine_clock import build_profile
    for platform, metadata, native in [("android", "android-metadata.dat", "mp4-android-analysis/libunity.so"), ("ios", "ios-metadata.dat", "ios-native.bin")]:
        directory_path = Path(directory)
        assert build_profile((directory_path / metadata).read_bytes(), (directory_path / native).read_bytes(), platform) == PROFILE[platform]
