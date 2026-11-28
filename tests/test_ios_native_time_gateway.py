"""Execute the packaged iOS time relay against the unchanged native kernel."""
import json
from pathlib import Path
import shutil
import struct
import subprocess

import pytest

from idoly_local import ios_presentation as presentation

unicorn = pytest.importorskip("unicorn")
from unicorn import arm64_const as registers


ROOT = Path(__file__).resolve().parents[1]
ENGINE = json.loads((ROOT / "client-presentation/native/mp4_engine_clock_profile.json").read_text())["platforms"]["ios"]
MANAGER, REPLACEMENT, STOP, STACK = 0x20000000, 0x22000000, 0x30000000, 0x40000000
RETURN = bytes.fromhex("c0035fd6")


def double_bits(value):
    return struct.unpack("<Q", struct.pack("<d", value))[0]


@pytest.fixture(scope="module")
def native_gate():
    return presentation.make_plan()["entries"]["mp4_native_time"]


class NativeTimeMachine:
    """Map only the original update, its constants, and the real planned relay."""

    def __init__(self, gate=None, replacement=None):
        self.machine = unicorn.Uc(unicorn.UC_ARCH_ARM64, unicorn.UC_MODE_ARM)
        self.machine.ctl_set_tcg_buffer_size(16 * 1024 * 1024)
        self.pages = set()
        self.gate = gate
        update = ENGINE["bindings"]["update"]
        self.original = int(update["rva"], 16)
        self.body = bytes.fromhex(update["body"])
        self.map(self.original, self.body)
        for constant in ENGINE["kernel_constants"]:
            self.map(int(constant["rva"], 16), bytes.fromhex(constant["bytes"]))
        self.map(MANAGER, bytes(0x1000))
        self.map(STACK, bytes(0x1000))
        self.map(STOP, RETURN)
        self.map(REPLACEMENT, RETURN)
        if gate is not None:
            self.map(gate["rva"], bytes.fromhex(gate["patched_entry"]))
            self.map(gate["gateway"], bytes.fromhex(gate["gateway_hex"]))
            for name in ("relay_in", "relay_out"):
                self.map(gate[name], bytes.fromhex(gate[name + "_hex"]))
            self.map(gate["slot"], struct.pack("<Q", REPLACEMENT if replacement else 0))
        if replacement == "original":
            # A replacement tail-calls the published original callable without
            # changing X0, D0, or the caller's LR. These are actual instructions.
            self.map(REPLACEMENT, bytes.fromhex("5000005800021fd6")
                     + struct.pack("<Q", gate["original_callable"]))
        self.seed()
        self.trace, self.arguments, self.counter_writes = [], {}, []
        self.kernel_trace = []
        self.machine.hook_add(unicorn.UC_HOOK_CODE, self.record_instruction)
        self.machine.hook_add(unicorn.UC_HOOK_MEM_WRITE, self.record_counter_write,
                              begin=MANAGER + 0xC8, end=MANAGER + 0xD3)

    def map(self, address, raw):
        for page in range(address & ~4095, (address + len(raw) + 4095) & ~4095, 4096):
            if page not in self.pages:
                self.machine.mem_map(page, 4096)
                self.pages.add(page)
        self.machine.mem_write(address, raw)

    def seed(self):
        # The independent native manager state needed by this 448-byte kernel.
        # Fixed, game and render clocks start at 60 scaled / 100 unscaled.
        for field, value in ((0x30, 59.98), (0x38, 59.96), (0x40, 99.98),
                             (0x60, 60.), (0x68, 59.98), (0x70, 100.),
                             (0x90, 60.), (0x98, 59.98), (0xA0, 100.),
                             (0xE0, 940.), (0xE8, 900.), (0xF0, -50.)):
            self.put(field, "d", value)
        for field, value in ((0x48, .02), (0x4C, .02), (0x50, .02), (0x58, 50.),
                             (0x78, .02), (0x7C, .02), (0x80, .02), (0x84, 1.),
                             (0x88, 50.), (0xA8, .02), (0xAC, .02), (0xB0, .02),
                             (0xB4, 1.), (0xB8, 50.), (0xFC, .5),
                             (0x100, .3333333), (0x104, .03)):
            self.put(field, "f", value)
        self.put(0xC8, "Q", 99)
        self.put(0xD0, "I", 17)

    def put(self, field, kind, value):
        self.machine.mem_write(MANAGER + field, struct.pack("<" + kind, value))

    def get(self, field, kind):
        raw = self.machine.mem_read(MANAGER + field, struct.calcsize(kind))
        return struct.unpack("<" + kind, raw)[0]

    def state(self):
        return bytes(self.machine.mem_read(MANAGER, 0x1000))

    def record_instruction(self, machine, address, _size, _data):
        if self.original <= address < self.original + len(self.body):
            self.kernel_trace.append(address)
        if self.gate is None:
            return
        landmarks = (self.original, self.gate["relay_in"], self.gate["gateway"],
                     self.gate["original_callable"], self.gate["relay_out"],
                     self.original + 4, REPLACEMENT)
        if address in landmarks:
            self.trace.append(address)
            self.arguments[address] = (machine.reg_read(registers.UC_ARM64_REG_X0),
                                       machine.reg_read(registers.UC_ARM64_REG_D0),
                                       machine.reg_read(registers.UC_ARM64_REG_X30),
                                       machine.reg_read(registers.UC_ARM64_REG_X8))

    def record_counter_write(self, _machine, _access, address, size, value, _data):
        self.counter_writes.append((address - MANAGER, size, value))

    def call(self, wall, start=None):
        self.machine.reg_write(registers.UC_ARM64_REG_X0, MANAGER)
        self.machine.reg_write(registers.UC_ARM64_REG_D0, double_bits(wall))
        self.machine.reg_write(registers.UC_ARM64_REG_X8, 0xFEDCBA9876543210)
        self.machine.reg_write(registers.UC_ARM64_REG_X30, STOP)
        self.machine.reg_write(registers.UC_ARM64_REG_SP, STACK + 0xF00)
        self.machine.emu_start(self.original if start is None else start, STOP, count=10000)
        assert self.machine.reg_read(registers.UC_ARM64_REG_PC) == STOP

    def assert_original_completed(self, reference, wall):
        assert self.state() == reference.state()
        assert self.counter_writes == [(0xC8, 8, 100), (0xD0, 4, 18)]
        assert self.get(0xC8, "Q") == 100 and self.get(0xD0, "I") == 18
        # Every instruction after the displaced load is the original kernel,
        # with exactly the same path and output as an unpatched invocation.
        assert [pc for pc in self.kernel_trace if pc != self.original] == reference.kernel_trace[1:]
        for address, values in self.arguments.items():
            assert values[:3] == (MANAGER, double_bits(wall), STOP), hex(address)
        for address in (self.gate["relay_out"], self.original + 4):
            assert self.arguments[address][3] == 99  # displaced LDR X8,[X0,#0xC8]


def original_execution(wall):
    reference = NativeTimeMachine()
    reference.call(wall)
    return reference


def test_native_time_plan_binds_the_original_double_timestamp_kernel(native_gate):
    update = ENGINE["bindings"]["update"]
    assert native_gate["rva"] == int(update["rva"], 16) == 0xCAD01C
    assert update["bytes"] == len(bytes.fromhex(update["body"])) == 448
    assert native_gate["original16"] == update["prefix"]
    assert native_gate["gateway"] == 0x9788750
    assert native_gate["slot"] == 0xAB8DA78
    assert native_gate["relay_in"] == 0x8610A44
    assert native_gate["relay_out"] == 0x8610A48
    assert native_gate["original_callable"] == native_gate["gateway"] + 20
    assert bytes.fromhex(native_gate["gateway_hex"])[20:24] == bytes.fromhex("086440f9")


@pytest.mark.parametrize("wall", [1000.125, 1001.])
def test_nil_slot_relays_into_the_full_original_kernel_exactly_once(native_gate, wall):
    machine = NativeTimeMachine(native_gate)
    machine.call(wall)
    assert machine.trace == [native_gate[name] for name in
            ("rva", "relay_in", "gateway", "original_callable", "relay_out")] + [native_gate["rva"] + 4]
    machine.assert_original_completed(original_execution(wall), wall)


@pytest.mark.parametrize("wall", [1000.125, 1001.])
def test_replacement_slot_tail_call_preserves_manager_timestamp_and_caller_lr(native_gate, wall):
    machine = NativeTimeMachine(native_gate, replacement="return")
    before = machine.state()
    machine.call(wall)
    assert machine.trace == [native_gate["rva"], native_gate["relay_in"], native_gate["gateway"], REPLACEMENT]
    assert machine.arguments[REPLACEMENT][:3] == (MANAGER, double_bits(wall), STOP)
    assert machine.counter_writes == [] and machine.state() == before
    assert machine.kernel_trace == [native_gate["rva"]]


@pytest.mark.parametrize("wall", [1000.125, 1001.])
def test_published_original_callable_bypasses_the_replacement_and_runs_full_kernel(native_gate, wall):
    machine = NativeTimeMachine(native_gate, replacement="return")
    machine.call(wall, start=native_gate["original_callable"])
    assert machine.trace == [native_gate["original_callable"], native_gate["relay_out"], native_gate["rva"] + 4]
    machine.assert_original_completed(original_execution(wall), wall)


@pytest.mark.parametrize("wall", [1000.125, 1001.])
def test_replacement_can_tail_call_the_published_original_without_double_update(native_gate, wall):
    machine = NativeTimeMachine(native_gate, replacement="original")
    machine.call(wall)
    assert machine.trace == [native_gate["rva"], native_gate["relay_in"], native_gate["gateway"],
                             REPLACEMENT, native_gate["original_callable"], native_gate["relay_out"],
                             native_gate["rva"] + 4]
    machine.assert_original_completed(original_execution(wall), wall)


@pytest.fixture(scope="module")
def host_static_verifier(tmp_path_factory):
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("A host C++ compiler is unavailable for the static verifier")
    profile, plan = presentation.load_profile(), presentation.make_plan()
    text, data = profile["segments"]["__TEXT"], profile["segments"]["__DATA"]
    relay, gate = profile["native_relay_region"], plan["entries"]["mp4_native_time"]
    uuid = struct.pack("<II", 0x1B, 24) + bytes.fromhex(profile["target"]["uuid"])
    text_command = bytearray(72 + 2 * 80)
    struct.pack_into("<II16sQQQQIIII", text_command, 0, 0x19, len(text_command), b"__TEXT",
                     0, text["vmsize"], 0, text["filesize"], 5, 5, 2, 0)
    for index, (name, start, end) in enumerate((
            (relay["after_section"], 0, relay["gap_begin"]),
            (relay["before_section"], relay["gap_end"], text["section_end"]))):
        struct.pack_into("<16s16sQQ", text_command, 72 + index * 80,
                         name.encode(), b"__TEXT", start, end - start)
    data_command = struct.pack("<II16sQQQQIIII", 0x19, 72, b"__DATA", data["rva"],
                               data["vmsize"], data["fileoff"], data["filesize"], 3, 3, 0, 0)
    commands = uuid + text_command + data_command
    header = struct.pack("<8I", 0xFEEDFACF, 0x0100000C, 0, 6, 3, len(commands), 0, 0) + commands
    patches = [(0, header)]
    patches += [(row["rva"], bytes.fromhex(row["prefix16"])) for row in profile["aliases"].values()]
    for row in plan["entries"].values():
        patches += [(row["rva"], bytes.fromhex(row["patched_entry"])),
                    (row["gateway"], bytes.fromhex(row["gateway_hex"]))]
        if "relay_in" in row:
            patches += [(row[name], bytes.fromhex(row[name + "_hex"])) for name in ("relay_in", "relay_out")]
    initializers = "\n".join("    patch(" + str(offset) + ", \"" + raw.hex() + "\");"
                               for offset, raw in patches)
    # Compile the actual verifier before its unrelated dyld/installation code.
    verifier = (presentation.PROFILE.parent / "static_install.hpp").read_text().split("struct Hook {", 1)[0]
    text_offset = 32 + len(uuid)
    first_section = text_offset + 72
    mutations = {
        "relay_in": f"image[{gate['relay_in']}] ^= 1;",
        "relay_out": f"image[{gate['relay_out']}] ^= 1;",
        "entry_branch": f"image[{gate['rva']}] ^= 1;",
        "gateway_continuation": f"image[{gate['gateway'] + 24}] ^= 1;",
        "displaced_load": f"image[{gate['original_callable']}] ^= 1;",
        "occupied_slot": f"put<uint64_t>({gate['slot']}, 1);",
        "relay_inside_section": f"put<uint64_t>({first_section + 40}, {gate['relay_out'] + 4});",
        "too_many_sections": f"put<uint32_t>({text_offset + 64}, 129);",
        "truncated_sections": f"put<uint32_t>({text_offset + 64}, 3);",
        "section_outside_text": f"put<uint64_t>({first_section + 40}, {text['vmsize'] + 1});",
    }
    mutation_code = "\n".join("    else if (!std::strcmp(argv[1], \"" + name + "\")) { " + code + " }"
                               for name, code in mutations.items())
    source = f'''#include <cstdint>
#include <cstdio>
#include <cstring>
#include <sys/mman.h>
#include "{presentation.PROFILE.parent / 'ios_profile.hpp'}"
namespace pin = idoly::presentation::profile;
uintptr_t image_base = 0;
unsigned char* image = nullptr;
template<class T> T read(void* object, size_t offset) {{
    T value; std::memcpy(&value, static_cast<unsigned char*>(object)+offset, sizeof value); return value;
}}
template<class T> void put(size_t offset, T value) {{ std::memcpy(image+offset, &value, sizeof value); }}
void patch(size_t offset, const char* hex) {{
    for (size_t index=0; hex[index*2]; ++index) {{
        unsigned byte=0; std::sscanf(hex+index*2, "%2x", &byte); image[offset+index]=byte;
    }}
}}
{verifier}
int main(int argc, char** argv) {{
    if (argc!=2) return 2;
    constexpr size_t length = {data['rva'] + data['vmsize']};
    image=static_cast<unsigned char*>(mmap(nullptr,length,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0));
    if (image==MAP_FAILED) return 3;
    image_base=reinterpret_cast<uintptr_t>(image);
{initializers}
    if (!std::strcmp(argv[1], "valid")) {{}}
{mutation_code}
    else return 4;
    std::printf("%d\\n", verify_static_image(image));
    munmap(image,length);
}}
'''
    directory = tmp_path_factory.mktemp("ios-native-time-static-verifier")
    source_path, binary_path = directory / "verifier.cpp", directory / "verifier"
    source_path.write_text(source)
    result = subprocess.run([compiler, "-std=c++17", "-O2", str(source_path), "-o", str(binary_path)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    return binary_path


@pytest.mark.parametrize("damage", ["valid", "relay_in", "relay_out", "entry_branch", "gateway_continuation",
                                    "displaced_load", "occupied_slot", "relay_inside_section", "too_many_sections",
                                    "truncated_sections", "section_outside_text"])
def test_static_verifier_accepts_the_real_plan_and_rejects_native_relay_tampering(host_static_verifier, damage):
    result = subprocess.run([str(host_static_verifier), damage], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr
    assert result.stdout == ("1\n" if damage == "valid" else "0\n")
