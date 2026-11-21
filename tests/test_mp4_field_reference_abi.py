"""Execute pinned original IL2CPP field setters, independently of C++ test doubles.

Unity 2022.3's basic setter uses a mixed ABI: direct managed pointers for
reference fields, addresses of native values for primitive fields. Passing
``&object`` corrupts the field with a native stack address. The separate
``field_set_value_object`` export is also pinned so the two cannot be confused.

Only the generic-class resolver is stubbed, returning an exact reference class;
the export branches, type dispatch/table and reference write are original ARM64.
Set IDOLY_MP4_ORIGINALS_DIR to compare every snippet and the whole native hash
with the pinned original inputs. No game code outside these small paths runs.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import struct

import pytest
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm64_const import (
    UC_ARM64_REG_LR, UC_ARM64_REG_PC, UC_ARM64_REG_SP,
    UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2,
)

ROOT = Path(__file__).resolve().parents[1]
# These ranges were read from the SHA-pinned original exports and implementations.
ORIGINAL = {'android': {'filename': 'android-native.so',
             'native_sha256': '68d4706d14b33d07647b9752124632a44b6a5901c82723beb569d9123df676b3',
             'set_value': 68805020,
             'set_object': 68805024,
             'generic_class_resolver': 69012252,
             'reference_write': 68622240,
             'regions': {68805020: {'offset': 68788636, 'hex': '81f30014cef3001485f30014b1f30014'},
                         69054368: {'offset': 69037984,
                                    'hex': '291880b9280440f9e3031f2a0100098be00308aa31feff17'},
                         69054680: {'offset': 69038296, 'hex': '281880b9e10302aa0000088baf59fe17'},
                         69052536: {'offset': 69036152,
                                    'hex': 'fe5fbda9f65701a9f44f02a9080840b9f40302aaf30301aa8806e837372cfff0f503032af60300aaf7b20291085d1053080900511f6d0071a805005489000010ea6a683829090a8b20011fd6c82a4039083d10531f41447121050054e00316aaa2e9ff97c0040036e00316aa26e9ff975893fd970820009104000014c00240f989d8ff9708a00091080140b9e8ffff1755000036940240f9e00313aae10314aaf44f42a9f65741a9fe5fc3a89f5bfe17140400b4880240f91f000014140400b4880240391f000014140400b4880240791f000014d40400b4880240b92500001455000036940240f9740200f9f44f42a9f65741a9fe5fc3a8c0035fd621008052e00316aa9591fd97e1031faa0a95fd97027c4093e00313aa140300b4e10314aaf44f42a9f65741a9fe5fc3a827264415e8031faa680200f9edffff17e8031f2a68020039eaffff17e8031f2a68020079e7ffff17d40100b4800240bd0d000014d40100b4800240fd0d000014e8031f2a680200b9deffff17f44f42a9f65741a9e1031f2afe5fc3a814264415e003271e600200bdd6ffff17e003679e600200fdd3ffff17'},
                         41291948: {'offset': 41291948,
                                    'hex': '1c1f1c1c1f1f222219194245112528001128110c2828191928251111'},
                         68622240: {'offset': 68605856, 'hex': '010000f9c0035fd6'}},
             'regions_sha256': 'b9d7b1ac4d7526d377b733211a78d3a0d7902a68c74d457729184c11816e29e3'},
 'ios': {'filename': 'ios-native.bin',
         'native_sha256': 'b03bee7ede0f8e74c84b3e171f79bc3596e074281b42640eb70bd106474ff5bf',
         'set_value': 136226456,
         'set_object': 136226460,
         'generic_class_resolver': 136574640,
         'reference_write': 13837760,
         'regions': {136226456: {'offset': 136226456, 'hex': 'b1700114fe700114b5700114e0700114'},
                     136603996: {'offset': 136603996,
                                 'hex': '281880b90800088b200440f9e10308aa03008052e8fdff17'},
                     136604308: {'offset': 136604308, 'hex': '281880b90000088be10302aac8ae2b16'},
                     136601872: {'offset': 136601872,
                                 'hex': 'f85fbca9f65701a9f44f02a9fd7b03a9fdc30091f40302aaf30301aa080840b9a806e837f50303aaf60300aa177a00f0f76a0791085d1053080900511f6d0071c805005489000010ea6a683829090a8b20011fd6c82a4039083d10531f41447161050054e00316aaa2f6ff9700050034e00316aa1ff6ff97261000940820009104000014c00240f946e5ff9708a00091080140b9e8ffff1755000034940240f9e00313aae10314aafd7b43a9f44f42a9f65741a9f85fc4a8feb02b16540400b4880240f921000014540400b48802403921000014540400b48802407921000014140500b4880240b92700001455000034940240f9740200f9fd7b43a9f44f42a9f65741a9f85fc4a8c0035fd6e00316aa21008052a50e0094010080d2f0110094027c4093e00313aa340300b4e10314aafd7b43a9f44f42a9f65741a9f85fc4a8a8060114080080d2680200f9ebffff170800805268020039e8ffff170800805268020079e5ffff17940100b4800240bd0b000014940100b4800240fd0b00001408008052680200b9dcffff17e10302aad6030194d9ffff17e003271e600200bdd6ffff17e003679e600200fdd3ffff17'},
                     152605146: {'offset': 152605146,
                                 'hex': '1d201d1d202023231a1a4548112629001129110c29291a1a29261111'},
                     13837760: {'offset': 13837760, 'hex': '010000f9c0035fd6'}},
         'regions_sha256': 'a231e896fbe42f604c3fa2ccd5d78290ef8d7b3f4ffb0a0d389b9f834a5211be'}}


def _execute(platform: str, kind: int, convention: str, object_export: bool = False):
    profile = ORIGINAL[platform]
    engine = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    # A few hundred instructions need little TCG space. Do not use its large
    # default translation buffer for this bounded regression.
    engine.ctl_set_tcg_buffer_size(1024 * 1024)
    regions = {int(a): bytes.fromhex(row["hex"]) for a, row in profile["regions"].items()}
    pages = {profile["generic_class_resolver"] & ~4095}
    for address, code in regions.items():
        pages.update(range(address & ~4095, (address + len(code) + 4095) & ~4095, 4096))
    for address in sorted(pages):
        engine.mem_map(address, 4096)
    for address, code in regions.items():
        engine.mem_write(address, code)
    engine.mem_map(0x10000000, 0x10000)
    engine.mem_map(0x20000000, 0x10000)
    engine.mem_map(0x30000000, 4096)
    owner, field, field_type, managed, reference_slot, generic, klass, primitive = (
        0x10000000 + i * 256 for i in range(8)
    )
    def qword(address, value):
        engine.mem_write(address, struct.pack("<Q", value))
    def word(address, value):
        engine.mem_write(address, struct.pack("<I", value))
    qword(field + 8, field_type)
    word(field + 0x18, 0x20)
    qword(field_type, generic)
    word(field_type + 8, kind << 16)
    # The original GenericInst path resolves its definition, then dispatches
    # again using klass.byval_arg's class/reference kind (0x12).
    word(klass + 0x28, 18 << 16)
    qword(reference_slot, managed)
    word(primitive, 1 if kind == 2 else 0x12345678)
    if convention == "address_of_primitive":
        argument = primitive
    elif convention == "address_of_reference":
        argument = reference_slot
    elif convention == "direct_null":
        argument = 0
    else:
        assert convention == "direct_reference"
        argument = managed
    for register, value in (
        (UC_ARM64_REG_X0, owner), (UC_ARM64_REG_X1, field),
        (UC_ARM64_REG_X2, argument), (UC_ARM64_REG_SP, 0x2000f000),
        (UC_ARM64_REG_LR, 0x30000000),
    ):
        engine.reg_write(register, value)
    observations = []
    instruction_count = 0
    def observe(cpu, address, size, user):
        nonlocal instruction_count
        instruction_count += 1
        if address == profile["generic_class_resolver"]:
            assert kind == 21 and cpu.reg_read(UC_ARM64_REG_X0) == generic
            observations.append("generic_reference_resolved")
            cpu.reg_write(UC_ARM64_REG_X0, klass)
            cpu.reg_write(UC_ARM64_REG_PC, cpu.reg_read(UC_ARM64_REG_LR))
        elif address == profile["reference_write"]:
            observations.append("original_reference_write")
        elif address == 0x30000000:
            cpu.emu_stop()
    hook = engine.hook_add(UC_HOOK_CODE, observe)
    try:
        engine.emu_start(profile["set_object" if object_export else "set_value"],
                         0x30000004, count=256)
        assert engine.reg_read(UC_ARM64_REG_PC) == 0x30000000
        assert instruction_count < 256
        width = 1 if kind == 2 else 4 if kind == 8 else 8
        stored = int.from_bytes(engine.mem_read(owner + 0x20, width), "little")
        return stored, argument, managed, observations
    finally:
        engine.hook_del(hook)


@pytest.mark.parametrize("platform", ORIGINAL)
@pytest.mark.parametrize("object_export", [False, True])
@pytest.mark.parametrize("kind", [14, 18, 21, 29])
@pytest.mark.parametrize("convention", ["direct_reference", "address_of_reference", "direct_null"])
def test_original_reference_setters_store_direct_pointer(platform, object_export, kind, convention):
    stored, argument, managed, observed = _execute(platform, kind, convention, object_export)
    assert stored == argument
    assert "original_reference_write" in observed
    if convention == "address_of_reference":
        # This is the actual 21.7 bug, not a successful reference assignment.
        assert stored != managed
    else:
        assert stored == (0 if convention == "direct_null" else managed)
    if kind == 21 and not object_export:
        assert "generic_reference_resolved" in observed


@pytest.mark.parametrize("platform", ORIGINAL)
@pytest.mark.parametrize("kind,expected", [(2, 1), (8, 0x12345678)])
def test_original_primitive_setter_reads_native_value_address(platform, kind, expected):
    stored, argument, managed, observed = _execute(platform, kind, "address_of_primitive")
    assert stored == expected and stored != argument
    assert "original_reference_write" not in observed


@pytest.mark.parametrize("platform", ORIGINAL)
def test_profile_names_the_basic_export_and_keeps_original_bytes(platform):
    profile = ORIGINAL[platform]
    binding = json.loads((ROOT / "client-presentation/native" /
                         f"mp4_replay_{platform}_profile.json").read_text())["exports"]["field_set_value"]
    assert binding["export"] == "il2cpp_field_set_value"
    assert int(binding["rva"], 16) == profile["set_value"]
    assert binding["prefix"] == profile["regions"][profile["set_value"]]["hex"][:32]
    assert profile["set_object"] != profile["set_value"]
    digest = hashlib.sha256()
    for address, region in sorted(profile["regions"].items()):
        digest.update(struct.pack("<Q", address))
        digest.update(bytes.fromhex(region["hex"]))
    assert digest.hexdigest() == profile["regions_sha256"]


@pytest.mark.parametrize("platform", ORIGINAL)
def test_optional_whole_original_matches_every_executed_instruction(platform):
    root = os.environ.get("IDOLY_MP4_ORIGINALS_DIR")
    if not root:
        pytest.skip("set IDOLY_MP4_ORIGINALS_DIR for whole-original byte comparison")
    profile = ORIGINAL[platform]
    path = Path(root) / profile["filename"]
    digest = hashlib.sha256()
    with path.open("rb") as original:
        while chunk := original.read(1024 * 1024):
            digest.update(chunk)
        assert digest.hexdigest() == profile["native_sha256"]
        for address, region in profile["regions"].items():
            expected = bytes.fromhex(region["hex"])
            original.seek(region["offset"])
            assert original.read(len(expected)) == expected, hex(address)
