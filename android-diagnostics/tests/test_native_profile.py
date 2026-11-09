"""Pinned native profiles are checked without loading or modifying game code."""
import hashlib
import importlib.util
import json
from pathlib import Path
import struct

import pytest

ROOT = Path(__file__).resolve().parents[2]
NATIVE = ROOT / "android-diagnostics/native"
SPEC = importlib.util.spec_from_file_location("phase_native_builder", NATIVE / "build_native.py")
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)


def test_profile_contains_only_the_sixteen_approved_fixed_checkpoints(tmp_path):
    profile = json.loads((NATIVE / "phase-profile.json").read_text())
    expected = {"home_enter", "environment_begin", "background_begin", "background_load_returned",
        "shader_completion_flag", "home_open_begin", "loading_hide", "front_loading_finished",
        "actors_begin", "actor_motion_wait", "actor_cache_build", "actor_result_received",
        "actor_cache_wait", "buttons_begin", "home_show_in_returned", "shader_wait_begin"}
    assert {row["code"] for row in profile["sites"]} == expected
    assert len({int(row["rva"], 16) for row in profile["sites"]}) == len(expected)
    assert all(len(bytes.fromhex(row["expected16"])) == 16 for row in profile["sites"])
    output = tmp_path / "phase_sites.h"
    BUILDER.generate_header(profile, output)
    assert "#define PHASE_COUNT 16" in output.read_text()


def test_generated_profile_rejects_incomplete_or_duplicate_windows(tmp_path):
    profile = json.loads((NATIVE / "phase-profile.json").read_text())
    profile["sites"][0]["expected16"] = "00"
    with pytest.raises(ValueError, match="16-byte"):
        BUILDER.generate_header(profile, tmp_path / "header.h")


def test_16k_check_rejects_a_library_requiring_4k_pages(tmp_path):
    header = bytearray(120)
    header[:6] = b"\x7fELF\x02\x01"
    struct.pack_into("<H", header, 18, 183)
    struct.pack_into("<Q", header, 32, 64)
    struct.pack_into("<HH", header, 54, 56, 1)
    struct.pack_into("<II6Q", header, 64, 1, 5, 0, 0, 0, 120, 120, 4096)
    path = tmp_path / "library.so"
    path.write_bytes(header)
    with pytest.raises(ValueError, match="16 KiB"):
        BUILDER.check_arm64_16k(path)
    struct.pack_into("<Q", header, 112, 16384)
    path.write_bytes(header)
    BUILDER.check_arm64_16k(path)


def test_native_builder_rejects_an_unpinned_ndk_even_when_the_compiler_exists(tmp_path):
    compiler = tmp_path / "toolchains/llvm/prebuilt/linux-x86_64/bin/aarch64-linux-android28-clang"
    compiler.parent.mkdir(parents=True)
    compiler.touch()
    (tmp_path / "source.properties").write_text("Pkg.Revision = 27.0.0\n")
    with pytest.raises(ValueError, match="pinned NDK"):
        BUILDER.find_ndk(tmp_path)


def test_actual_local_bootstrap_windows_if_a_built_client_is_available():
    from zipfile import ZipFile

    profile = json.loads((NATIVE / "phase-profile.json").read_text())
    client = ROOT / "data/clients/IdolyPride-Local-Diagnostic-Android-arm64.apk"
    if not client.is_file():
        pytest.skip("Optional locally built original diagnostic client unavailable")
    with ZipFile(client) as archive:
        payload = archive.read("lib/arm64-v8a/libil2cpp.so")
    assert hashlib.sha256(payload).hexdigest() == profile["local_bootstrap_native_sha256"]
    offset = struct.unpack_from("<Q", payload, 32)[0]
    size, count = struct.unpack_from("<HH", payload, 54)
    segments = [struct.unpack_from("<II6Q", payload, offset + index * size) for index in range(count)]
    for site in profile["sites"]:
        address = int(site["rva"], 16)
        mapping = next(row for row in segments if row[0] == 1 and row[1] & 1
                       and row[3] <= address and address + 16 <= row[3] + row[5])
        position = mapping[2] + address - mapping[3]
        assert payload[position:position + 16] == bytes.fromhex(site["expected16"])
