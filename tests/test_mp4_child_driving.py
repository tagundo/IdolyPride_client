"""Shipping RuntimeClip driving/actual AAPCS64 continuation, with explicit leaves.

Service fixtures model native ownership; ARM test executes the compiled shipping
lowered thunk and an explicitly modeled original tail callee. No device or MP4
completion is claimed by these tests.
"""
from pathlib import Path
import importlib.util
import shutil
import struct
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / 'client-presentation/native'
FIX = ROOT / 'tests/fixtures'


def marker(text, name):
    return text.split('// BEGIN_' + name + '\n', 1)[1].split('// END_' + name, 1)[0]


def namespace(text, anchor, name):
    suffix = text.split(anchor, 1)[1]
    return 'namespace ' + name + ' {' + suffix.split('namespace ' + name + ' {', 1)[1].split('} // namespace ' + name, 1)[0] + '} // namespace ' + name


@pytest.fixture(scope='module')
def driving_binaries(tmp_path_factory):
    compiler = shutil.which('c++')
    if not compiler:
        pytest.skip('A host C++ compiler is required')
    text = (NATIVE / 'bridge.cpp').read_text()
    folder = tmp_path_factory.mktemp('shipping-child-driving')
    headers = {
        'pending-journal.hpp': marker(text, 'MP4_DIRECTOR_MAINTENANCE_CORE'),
        'birth-scope.hpp': namespace(text, '// Shared-only: real native allocation/registration', 'mp4_director_birth'),
        'source-origin.hpp': namespace(text, '// Concrete original entry contract.', 'mp4_director_birth'),
        'child-scope.hpp': namespace(text, '// Shared-only. Logical child Director restoration', 'mp4_child_source'),
        'director-node-scope.hpp': namespace(text, '// Logical DirectorControl state only.', 'idoly_mp4_director_nodes'),
        'driving-scope.hpp': marker(text, 'MP4_CHILD_DRIVING_STATE'),
    }
    for name, body in headers.items():
        (folder / name).write_text('#pragma once\n' + body)
    host = marker(text, 'MP4_CHILD_DRIVING_HOST')
    runtime = 'bool mp4_child_driving_runtime_active' + host.split('bool mp4_child_driving_runtime_active', 1)[1].split('bool mp4_child_driving_role_emit', 1)[0]
    binaries = {}
    for kind, name in [('scope', 'mp4_child_driving_model.cpp.inc'), ('active', 'mp4_child_active_role_model.cpp.inc')]:
        source = (FIX / name).read_text().replace('// ACTUAL_RUNTIME_ACTIVE', runtime)
        path, binary = folder / (kind + '.cpp'), folder / kind
        path.write_text(source)
        result = subprocess.run([compiler, '-std=c++17', '-O1', '-g', '-Wall', '-Wextra', '-Werror', '-Wno-misleading-indentation', '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-I', str(folder), '-I', str(NATIVE), str(path), '-o', str(binary)], capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, result.stderr
        binaries[kind] = binary
    prefix = (FIX / 'mp4_child_driving_model.cpp.inc').read_text().split('int main(int argc,char**argv)', 1)[0]
    front = (FIX / 'mp4_child_driving_frontend_model.cpp.inc').read_text().replace('// ACTUAL_DRIVING_PINS', marker(text, 'MP4_CHILD_DRIVING_PINS')).replace('// ACTUAL_DRIVING_HOOKS', marker(text, 'MP4_CHILD_DRIVING_HOOKS'))
    path, binary = folder / 'frontend.cpp', folder / 'frontend'
    path.write_text(prefix + front)
    result = subprocess.run([compiler, '-std=c++17', '-O1', '-g', '-Wall', '-Wextra', '-Werror', '-Wno-misleading-indentation', '-Wno-unused-function', '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-I', str(folder), '-I', str(NATIVE), str(path), '-o', str(binary)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    binaries['frontend'] = binary
    from test_mp4_native_phase_journal_host import PREFIX, MIDDLE, function
    native_prefix = PREFIX + '#include "pending-journal.hpp"\n'
    raw = 'struct Mp4RawOriginalOperation' + text.split('struct Mp4RawOriginalOperation', 1)[1].split('struct Mp4OriginalEvaluationScope', 1)[0]
    native_prefix += raw + function(text, '[[maybe_unused]] bool mp4_director_actual_operation(') + MIDDLE + marker(text, 'MP4_NATIVE_PHASE_JOURNAL_HOST')
    front_native = front.split('int main(int argc,char**argv)', 1)[0].replace('bool owner=true,descriptor=true,schema=true;', 'bool descriptor=true,schema=true;').replace('bool game_call(){return owner;}','')
    origin = function(text, 'bool mp4_child_driving_origin(')
    native_source = native_prefix + prefix + front_native + 'bool mp4_actor_clock_held(void*){return model&&model->held;}\nbool mp4_child_invoked_operation(const dm::Call&){return false;}\n' + origin + (FIX / 'mp4_child_driving_native_phase_model.cpp.inc').read_text()
    path, binary = folder / 'native-phase.cpp', folder / 'native-phase'
    path.write_text(native_source)
    result = subprocess.run([compiler, '-std=c++17', '-O1', '-g', '-Wall', '-Wextra', '-Werror', '-Wno-misleading-indentation', '-Wno-unused-function', '-Wno-unused-variable', '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-I', str(folder), '-I', str(NATIVE), str(path), '-o', str(binary)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    binaries['native-phase'] = binary
    return binaries


@pytest.mark.parametrize('mode', list(range(37)) + [43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53])
def test_shipping_entered_driving_and_frame_completion(driving_binaries, mode):
    result = subprocess.run([str(driving_binaries['scope']), str(mode)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('mode', range(20))
def test_shipping_actual_runtime_clip_active_set(driving_binaries, mode):
    result = subprocess.run([str(driving_binaries['active']), str(mode)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('mode', [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 13, 14, 15, 16, 17])
def test_shipping_actual_callback_frontends(driving_binaries, mode):
    result = subprocess.run([str(driving_binaries['frontend']), str(mode)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('mode', range(4))
def test_shipping_driving_inside_actual_native_phase_journal(driving_binaries, mode):
    result = subprocess.run([str(driving_binaries['native-phase']), str(mode)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr


@pytest.fixture(scope='module')
def lowered_elf(tmp_path_factory):
    if importlib.util.find_spec('unicorn') is None:
        pytest.skip('Unicorn is required to execute actual compiled ARM64')
    compiler = Path('/workspace/.setup/android-sdk/ndk/26.3.11579264/toolchains/llvm/prebuilt/linux-x86_64/bin/aarch64-linux-android28-clang++')
    if not compiler.exists():
        pytest.skip('The ARM64 NDK compiler is required')
    text = marker((NATIVE / 'bridge.cpp').read_text(), 'MP4_CHILD_DRIVING_HOOKS')
    frame = 'struct Mp4ChildDrivingFrameData {' + text.split('struct Mp4ChildDrivingFrameData {', 1)[1].split('using Mp4ChildDrivingFrameOriginal', 1)[0]
    thunk = '__attribute__((noinline)) void mp4_child_driving_prepare_thunk' + text.split('__attribute__((noinline)) void mp4_child_driving_prepare_thunk', 1)[1].split('#else', 1)[0]
    source = '#include <stdint.h>\nnamespace mp4actor {struct Handle{uintptr_t handle=0;uint32_t version=0,padding=0;};}\nusing Method=const void;\n' + frame
    source += '\nusing Lowered=void(*)(void*,mp4actor::Handle,const Mp4ChildDrivingFrameData*,Method*);\nextern "C" void original_prepare(void*,mp4actor::Handle,const Mp4ChildDrivingFrameData*,Method*);\nextern "C" {Lowered mp4_child_driving_prepare_lowered=original_prepare;uintptr_t original_return=0;uintptr_t observed[14]{};}\nextern "C" __attribute__((noinline)) void mp4_child_driving_record_return(void*,uintptr_t pc)noexcept{original_return=pc;}\nextern "C" ' + thunk
    folder = tmp_path_factory.mktemp('shipping-child-driving-arm64')
    path, asm, binary = folder / 'thunk.cpp', folder / 'target.S', folder / 'thunk.elf'
    path.write_text(source)
    shutil.copyfile(FIX / 'mp4_child_driving_tail_target.S', asm)
    result = subprocess.run([str(compiler), '-std=c++17', '-O2', '-fno-exceptions', '-fno-rtti', '-fno-stack-protector', '-nostdlib', '-static', '-fno-pie', '-Wl,-Ttext=0x100000', '-Wl,-e,mp4_child_driving_prepare_thunk', str(path), str(asm), '-o', str(binary)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    return binary.read_bytes()


def elf_sections_symbols_segments(raw):
    sections = []
    shoff = struct.unpack_from('<Q', raw, 40)[0]
    shsize, shnum = struct.unpack_from('<HH', raw, 58)
    for i in range(shnum):
        sections.append(struct.unpack_from('<IIQQQQIIQQ', raw, shoff + i * shsize))
    symbols = {}
    for section in sections:
        if section[1] != 2:
            continue
        strings = sections[section[6]]
        names = raw[strings[4]:strings[4] + strings[5]]
        for at in range(section[4], section[4] + section[5], section[9]):
            name, _, _, _, value, _ = struct.unpack_from('<IBBHQQ', raw, at)
            if name:
                symbols[names[name:names.index(0, name)].decode()] = value
    segments = []
    phoff = struct.unpack_from('<Q', raw, 32)[0]
    phsize, phnum = struct.unpack_from('<HH', raw, 54)
    for i in range(phnum):
        typ, _, off, va, _, size, memory, _ = struct.unpack_from('<IIQQQQQQ', raw, phoff + i * phsize)
        if typ == 1:
            segments.append((va, off, size, memory))
    return symbols, segments


@pytest.mark.parametrize('case', range(8))
def test_shipping_lowered_frame64_thunk_preserves_real_tail_return(lowered_elf, case):
    from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM
    from unicorn.arm64_const import UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_X3, UC_ARM64_REG_X4, UC_ARM64_REG_X30, UC_ARM64_REG_SP
    symbols, segments = elf_sections_symbols_segments(lowered_elf)
    lo = min(va for va, _, _, _ in segments) & ~4095
    hi = (max(va + memory for va, _, _, memory in segments) + 4095) & ~4095
    emulator = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    emulator.mem_map(lo, hi - lo)
    for va, off, size, _ in segments:
        emulator.mem_write(va, lowered_elf[off:off + size])
    emulator.mem_map(0x600000, 0x10000)
    emulator.mem_map(0x900000, 0x1000)
    pointer = 0x600100 + case * 8
    frame = bytes((i + 17 * case) & 255 for i in range(64))
    emulator.mem_write(pointer, frame)
    values = [0x123000 + case, 0x234000 + case, (20 + case) | (0xaabbccdd << 32), pointer, 0x345000 + case]
    for register, value in zip([UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_X3, UC_ARM64_REG_X4], values):
        emulator.reg_write(register, value)
    emulator.reg_write(UC_ARM64_REG_X30, 0x900000)
    emulator.reg_write(UC_ARM64_REG_SP, 0x60f000)
    emulator.emu_start(symbols['mp4_child_driving_prepare_thunk'], 0x900000, count=1000)
    observed = bytes(emulator.mem_read(symbols['observed'], 112))
    assert struct.unpack_from('<5Q', observed) == tuple(values)
    assert observed[40:104] == frame
    assert struct.unpack_from('<Q', observed, 104)[0] == 0x900000
    assert struct.unpack('<Q', emulator.mem_read(symbols['original_return'], 8))[0] == 0x900000
    assert emulator.reg_read(UC_ARM64_REG_SP) == 0x60f000
