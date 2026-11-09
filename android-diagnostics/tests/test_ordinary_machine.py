"""Execute the compiled synthetic fixtures; this does not claim ShadowHook installs."""
import importlib.util
from pathlib import Path
import struct
import subprocess

import pytest

unicorn = pytest.importorskip("unicorn")
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE
from unicorn import arm64_const as reg

ROOT = Path(__file__).resolve().parents[2]
NATIVE = ROOT / "android-diagnostics/native"
NDK = ROOT.parent / ".setup/android-sdk/ndk/26.3.11579264"
AAR = ROOT.parent / "shared/artifacts/shadowhook-2.0.1/shadowhook-2.0.1.aar"
SPEC = importlib.util.spec_from_file_location("ordinary_native_builder", NATIVE / "build_native.py")
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)
BASE, STACK, IMPORTS, STOP = 0x10000000, 0x50000000, 0x60000000, 0x70000000
CASE_NAMES = ("add", "mov", "ldr", "ldp", "subsp", "strpre", "ldppost")


@pytest.fixture(scope="module")
def compiled(tmp_path_factory):
    if not NDK.is_dir() or not AAR.is_file():
        pytest.skip("Optional pinned local NDK/AAR are required for real ARM64 fixture execution")
    output = tmp_path_factory.mktemp("ordinary-native")
    # The complete local cache is supplied: tests never download dependencies.
    cache = output / "cache/shadowhook-2.0.1"
    cache.mkdir(parents=True)
    (cache / AAR.name).write_bytes(AAR.read_bytes())
    BUILDER.build_native(output / "build", ndk=NDK, cache_dir=cache.parent)
    return (output / "build/lib/arm64-v8a/libidoly_phase_probe.so").read_bytes()


def load(payload, failure_mode=None):
    machine = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    machine.mem_map(BASE, 0x20000)
    machine.mem_map(STACK, 0x20000)
    machine.mem_map(IMPORTS, 0x10000)
    machine.mem_map(STOP, 0x1000)
    phoff = struct.unpack_from("<Q", payload, 32)[0]
    phsize, phcount = struct.unpack_from("<HH", payload, 54)
    for i in range(phcount):
        kind, _, offset, address, _, length, _, _ = struct.unpack_from("<II6Q", payload, phoff + i * phsize)
        if kind == 1:
            machine.mem_write(BASE + address, payload[offset:offset + length])
    shoff = struct.unpack_from("<Q", payload, 40)[0]
    shsize, shcount = struct.unpack_from("<HH", payload, 58)
    sections = [struct.unpack_from("<II4QII2Q", payload, shoff + i * shsize) for i in range(shcount)]
    symbol_tables, symbols = {}, {}
    for index, row in enumerate(sections):
        if row[1] not in (2, 11):
            continue
        strings = sections[row[6]]
        strings = payload[strings[4]:strings[4] + strings[5]]
        table = []
        for offset in range(row[4], row[4] + row[5], row[9]):
            name, _, _, _, value, _ = struct.unpack_from("<IBBHQQ", payload, offset)
            name = strings[name:strings.index(b"\0", name)].decode()
            table.append((name, value))
            if value:
                symbols[name] = BASE + value
        symbol_tables[index] = table
    imports = {}
    for row in sections:
        if row[1] != 4:
            continue
        for offset in range(row[4], row[4] + row[5], row[9]):
            target, info, addend = struct.unpack_from("<QQq", payload, offset)
            kind = info & 0xffffffff
            if kind == 1027:
                machine.mem_write(BASE + target, struct.pack("<Q", BASE + addend))
            elif kind == 1026:
                name, _ = symbol_tables[row[6]][info >> 32]
                address = IMPORTS + len(imports) * 16
                imports[address] = name
                machine.mem_write(BASE + target, struct.pack("<Q", address))
            else:
                raise AssertionError("Unexpected test ELF relocation")
    calls = []

    def external(cpu, address, size, unused):
        if address not in imports:
            return
        name = imports[address]
        a, b, length = (cpu.reg_read(r) for r in (reg.UC_ARM64_REG_X0, reg.UC_ARM64_REG_X1, reg.UC_ARM64_REG_X2))
        if name == "memset":
            cpu.mem_write(a, bytes([b & 255]) * length)
        elif name == "memcpy":
            cpu.mem_write(a, bytes(cpu.mem_read(b, length)))
        elif name == "memcmp":
            left, right = bytes(cpu.mem_read(a, length)), bytes(cpu.mem_read(b, length))
            cpu.reg_write(reg.UC_ARM64_REG_X0, 0 if left == right else 1)
        elif name == "shadowhook_intercept_instr_addr":
            calls.append(a)
            if a and failure_mode:
                # Simulate an unavailable or incompletely removed library hook;
                # this validates our fail-closed code, not real interception.
                cpu.mem_write(a + 4, b"\0" * 4)
                if failure_mode == "unrestored":
                    cpu.mem_write(a, struct.pack("<I", 0x14000000))
                cpu.reg_write(reg.UC_ARM64_REG_X0, 1 if failure_mode == "unrestored" else 0)
            else:
                cpu.reg_write(reg.UC_ARM64_REG_X0, 0)  # Deliberately unavailable; no runtime claim.
        elif name == "shadowhook_unintercept":
            assert failure_mode == "unrestored"
            cpu.reg_write(reg.UC_ARM64_REG_X0, 0)  # A nominal success with wrong bytes must still fail.
        elif name == "shadowhook_get_errno":
            cpu.reg_write(reg.UC_ARM64_REG_X0, 35)
        else:
            raise AssertionError("Unexpected baseline import: " + name)
        cpu.reg_write(reg.UC_ARM64_REG_PC, cpu.reg_read(reg.UC_ARM64_REG_X30))

    machine.hook_add(UC_HOOK_CODE, external)
    return machine, symbols, calls


def invoke(machine, symbols, name):
    machine.reg_write(reg.UC_ARM64_REG_SP, STACK + 0x10000)
    machine.reg_write(reg.UC_ARM64_REG_X30, STOP)
    machine.emu_start(symbols[name], STOP, count=100000)
    assert machine.reg_read(reg.UC_ARM64_REG_PC) == STOP
    assert machine.reg_read(reg.UC_ARM64_REG_SP) == STACK + 0x10000
    return machine.reg_read(reg.UC_ARM64_REG_X0)


def test_all_seven_real_baselines_and_declined_hooks(compiled):
    machine, symbols, calls = load(compiled)
    assert invoke(machine, symbols, "idoly_phase_machine_check_ordinary") == 0
    address = invoke(machine, symbols, "idoly_phase_machine_ordinary_report")
    raw = bytes(machine.mem_read(address, 172))
    assert raw[:3] == b"\1\0\1"  # attempted, ok=false (no hook), invalid-address failure is safe.
    for i, name in enumerate(CASE_NAMES):
        case = raw[4 + i * 24:4 + (i + 1) * 24]
        assert case[0] == 1, name  # Actual compiled C++ inspect() accepted all CPU/effect baselines.
        assert case[1] == 0, name  # No fabricated install proof.
    assert calls == [0] + [symbols["idoly_machine_instruction_" + name] for name in CASE_NAMES]
    assert "idoly_machine_instruction_bl" not in symbols


@pytest.mark.parametrize("register,value", [(reg.UC_ARM64_REG_X12, 0xBAD),
    (reg.UC_ARM64_REG_Q31, 0), (reg.UC_ARM64_REG_NZCV, 0),
    (reg.UC_ARM64_REG_FPCR, 0), (reg.UC_ARM64_REG_FPSR, 0)])
def test_compiled_guard_rejects_corrupted_cpu_baseline_before_any_hook(compiled, register, value):
    machine, symbols, calls = load(compiled)

    def corrupt(cpu, address, size, unused):
        if address == symbols["idoly_machine_instruction_add"]:
            cpu.reg_write(register, value)

    machine.hook_add(UC_HOOK_CODE, corrupt)
    assert invoke(machine, symbols, "idoly_phase_machine_check_ordinary") == 0
    address = invoke(machine, symbols, "idoly_phase_machine_ordinary_report")
    raw = bytes(machine.mem_read(address, 172))
    assert raw[4] == 0  # ADD baseline fails.
    assert calls == []  # Even the invalid-address interceptor test is never attempted.


@pytest.mark.parametrize("failure_mode", ["declined_changed", "unrestored"])
def test_uncertain_synthetic_cleanup_prevents_any_following_install(compiled, failure_mode):
    machine, symbols, calls = load(compiled, failure_mode)
    assert invoke(machine, symbols, "idoly_phase_machine_check_ordinary") == 0
    assert calls == [0, symbols["idoly_machine_instruction_add"]]
    # The one-shot result cannot run another fixture after uncertain cleanup.
    assert invoke(machine, symbols, "idoly_phase_machine_check_ordinary") == 0
    assert len(calls) == 2
