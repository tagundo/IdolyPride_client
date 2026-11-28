import importlib.util
from pathlib import Path
import struct

import pytest


path = Path(__file__).resolve().parents[1] / "ios-unified/patch_load.py"
spec = importlib.util.spec_from_file_location("ios_unified_load", path)
load = importlib.util.module_from_spec(spec)
spec.loader.exec_module(load)


def fixture(*, platform=2, encrypted=False, first=4096):
    def name_command(command, name):
        prefix = 12 if command == 0x8000001C else 24
        raw = name.encode() + b"\0"
        length = (prefix + len(raw) + 7) & ~7
        head = struct.pack("<III", command, length, prefix)
        head += b"\0" * (prefix - len(head))
        return (head + raw).ljust(length, b"\0")
    segment = bytearray(152)
    struct.pack_into("<II", segment, 0, 0x19, len(segment))
    struct.pack_into("<I", segment, 64, 1)
    struct.pack_into("<Q", segment, 72 + 40, 1024)
    struct.pack_into("<I", segment, 72 + 48, first)
    commands = [bytes(segment), struct.pack("<6I", 0x32, 24, platform, 0xD0000, 0x1A0400, 0),
        name_command(0xC, load.PRESENTATION),
        name_command(0x8000001C, "@executable_path/Frameworks"),
        struct.pack("<6I", 0x2C, 24, first, 1024, int(encrypted), 0)]
    header = struct.pack("<8I", 0xFEEDFACF, 0x100000C, 0, 6, len(commands),
                         sum(map(len, commands)), 0, 0)
    body = bytearray((header + b"".join(commands)).ljust(8192, b"\0"))
    body[first:first + 1024] = bytes(range(256)) * 4
    return bytes(body)


def test_appends_dependency_only_in_reserved_header_preserving_every_code_byte():
    original = fixture()
    result, proof = load.patched_header(original, len(original))
    start, count = proof["offset"], proof["bytes"]
    assert result[:16] == original[:16]
    assert result[24:start] == original[24:start]
    assert result[start + count:] == original[start + count:]
    assert result[4096:5120] == bytes(range(256)) * 4
    assert struct.unpack_from("<II", result, 16) == (6, start - 32 + count)
    assert struct.unpack_from("<6I", result, start) == (0xC, count, 24, 0, 0, 0)
    assert load.DEPENDENCY.encode() + b"\0" in result[start:start + count]
    assert proof["original_code_and_file_offsets_preserved"] is True


@pytest.mark.parametrize("platform", [1, 6, 7, 0])
def test_rejects_mac_catalyst_simulator_and_undeclared_platform(platform):
    original = fixture(platform=platform)
    with pytest.raises(ValueError, match="actual iOS device"):
        load.patched_header(original, len(original))


def test_rejects_encrypted_input_and_x86_cpu():
    original = fixture(encrypted=True)
    with pytest.raises(ValueError, match="Encrypted"):
        load.patched_header(original, len(original))
    original = bytearray(fixture())
    struct.pack_into("<I", original, 4, 0x1000007)
    with pytest.raises(ValueError, match="arm64"):
        load.patched_header(bytes(original), len(original))


def test_refuses_nonempty_padding_and_original_code_collision():
    original = bytearray(fixture())
    end = 32 + struct.unpack_from("<I", original, 20)[0]
    original[end + 10] = 7
    with pytest.raises(ValueError, match="not empty"):
        load.patched_header(bytes(original), len(original))
    original = fixture(first=end + 8)
    with pytest.raises(ValueError, match="reservation"):
        load.patched_header(original, len(original))


def test_rejects_second_integration_and_malformed_command_table():
    original = fixture()
    once, _ = load.patched_header(original, len(original))
    with pytest.raises(ValueError, match="previous integrated"):
        load.patched_header(once, len(once))
    bad = bytearray(original)
    struct.pack_into("<I", bad, 36, 0xFFFFFFF8)
    with pytest.raises(ValueError, match="extent"):
        load.patched_header(bytes(bad), len(bad))


def test_requires_original_presentation_and_valid_original_rpath():
    original = fixture().replace(load.PRESENTATION.encode(), b"x" * len(load.PRESENTATION))
    with pytest.raises(ValueError, match="existing presentation"):
        load.patched_header(original, len(original))
    original = fixture().replace(b"@executable_path/Frameworks", b"x" * 27)
    with pytest.raises(ValueError, match="rpath"):
        load.patched_header(original, len(original))
