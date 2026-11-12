"""Verify pinned function identities with bounded reads of the original ELF."""
import json
import mmap
import os
from pathlib import Path
import struct

import pytest


def test_pinned_profile_matches_original_function_bytes():
    profile = json.loads((Path(__file__).resolve().parents[1] / "profile.json").read_text())
    original = Path(os.environ.get("IDOLY_PRESENTATION_ORIGINAL_IL2CPP",
        "/workspace/shared/artifacts/client-6.1.1/config.arm64_v8a/lib/arm64-v8a/libil2cpp.so"))
    if not original.is_file():
        pytest.skip("The original public 6.1.1 native library is unavailable")
    assert profile["target"]["gnu_build_id"] == "b094bb4a4f4acdffb41e1c6a8e8d77cffbd689fd"
    with original.open("rb") as source, mmap.mmap(source.fileno(), 0, access=mmap.ACCESS_READ) as data:
        assert data[:6] == b"\x7fELF\x02\x01" and struct.unpack_from("<H", data, 18)[0] == 183
        offset = struct.unpack_from("<Q", data, 32)[0]
        entry_size, count = struct.unpack_from("<HH", data, 54)
        segments = [struct.unpack_from("<II6Q", data, offset + i * entry_size) for i in range(count)]
        aliases = profile["aliases"]
        assert len(aliases) == 55
        for alias, entry in aliases.items():
            rva = int(entry["rva"], 16)
            expected = bytes.fromhex(entry["prefix16"])
            assert len(expected) == 16
            matching = [segment for segment in segments if segment[0] == 1 and segment[1] & 5 == 5
                        and segment[3] <= rva and rva + 16 <= segment[3] + segment[5]]
            assert len(matching) == 1, alias
            segment = matching[0]
            file_offset = segment[2] + rva - segment[3]
            assert data[file_offset:file_offset + 16] == expected, alias
