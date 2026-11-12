"""Unsigned structural boundaries only; no real key, JNI build or installation."""
import hashlib
import importlib.util
from pathlib import Path
import struct
import sys
import time
from zipfile import ZipFile
import xml.etree.ElementTree as ET

import pytest


PATH = Path(__file__).resolve().parents[1] / "build_addon.py"
SPEC = importlib.util.spec_from_file_location("presentation_addon", PATH)
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)
ANDROID = "{http://schemas.android.com/apk/res/android}"


@pytest.mark.parametrize("profile", ["diagnostics", "resources"])
def test_feature_manifest_inherits_base_and_has_only_own_unexported_provider(profile):
    tree = ET.fromstring(tool.manifest(profile))
    assert tree.get("package") == tool.PROFILES[profile]["package"]
    assert tree.get("split") == "idoly_presentation" and tree.get(ANDROID + "isFeatureSplit") == "true"
    assert tree.get(ANDROID + "versionCode") == "414"
    assert tree.find("uses-sdk").attrib == {ANDROID + "minSdkVersion": "28", ANDROID + "targetSdkVersion": "34"}
    app = tree.find("application")
    assert app.attrib == {ANDROID + "hasCode": "true"}
    assert len(app) == 1 and app[0].tag == "provider" and app[0].get(ANDROID + "exported") == "false"
    assert app[0].get(ANDROID + "authorities") == tool.PROFILES[profile]["package"] + ".idoly.presentation"
    assert not list(tree.findall("uses-permission")) and not list(app.findall("activity"))


def test_base_zip_entry_hash_is_streamed_and_requires_one_bounded_member(tmp_path):
    path = tmp_path / "base.apk"
    with ZipFile(path, "w") as archive: archive.writestr(tool.BOOTSTRAP, b"synthetic native")
    with ZipFile(path) as archive:
        assert tool.member_hash(archive, tool.BOOTSTRAP) == hashlib.sha256(b"synthetic native").hexdigest()
        with pytest.raises(ValueError): tool.member_hash(archive, "missing")


def test_profile_requires_existing_diag_dependency_but_refuses_resources_dependency_collision(tmp_path, monkeypatch):
    native = b"synthetic native"
    monkeypatch.setattr(tool, "BOOTSTRAP_SHA256", hashlib.sha256(native).hexdigest())
    path = tmp_path / "base.apk"
    with ZipFile(path, "w") as archive: archive.writestr(tool.BOOTSTRAP, native)
    with ZipFile(path) as archive:
        tool.check_base_members(archive, "resources")
        with pytest.raises(ValueError): tool.check_base_members(archive, "diagnostics")
    with ZipFile(path, "a") as archive: archive.writestr(next(iter(tool.SHADOW_HASHES)), b"unexpected library")
    with ZipFile(path) as archive:
        with pytest.raises(ValueError, match="conflicting"): tool.check_base_members(archive, "resources")


def test_tool_output_and_silent_runtime_are_bounded_and_reaped():
    started = time.monotonic()
    with pytest.raises(ValueError, match="timed out"):
        tool._run([sys.executable, "-c", "import time;time.sleep(10)"], {}, timeout=.1)
    assert time.monotonic() - started < 2
    with pytest.raises(ValueError, match="output exceeded"):
        tool._run([sys.executable, "-c", "import sys;sys.stdout.write('x'*1100000)"], {}, timeout=3)


def test_existing_v3_base_is_verified_but_new_split_still_requires_v2(monkeypatch):
    certificate = tool.PROFILES["diagnostics"]["certificate"]
    output = ("Signer #1 certificate SHA-256 digest: " + certificate + "\n"
              + "Verified using v2 scheme (APK Signature Scheme v2): false\n"
              + "Verified using v3 scheme (APK Signature Scheme v3): true\n")
    monkeypatch.setattr(tool, "_run", lambda *a, **k: (output, 0))
    assert tool.signature([], Path("base.apk"), certificate, {}, existing_base=True) == output
    with pytest.raises(ValueError): tool.signature([], Path("new.apk"), certificate, {})
    with pytest.raises(ValueError): tool.signature([], Path("base.apk"), "f" * 64, {}, existing_base=True)


@pytest.mark.parametrize("alignment", [4096, 16384])
def test_native_arm64_load_alignment_boundary(tmp_path, alignment):
    raw = bytearray(120); raw[:6] = b"\x7fELF\x02\x01"
    struct.pack_into("<H", raw, 18, 183); struct.pack_into("<Q", raw, 32, 64)
    struct.pack_into("<HH", raw, 54, 56, 1)
    struct.pack_into("<II6Q", raw, 64, 1, 5, 0, 0, 0, len(raw), len(raw), alignment)
    path = tmp_path / "lib.so"; path.write_bytes(raw)
    if alignment == 4096:
        with pytest.raises(ValueError): tool.check_elf(path)
    else: assert tool.check_elf(path) == [16384]


def test_bundle_manifest_has_fixed_profile_assets_and_rejects_changed_identity():
    profile = tool.PROFILES["diagnostics"]
    report = {"profile": "diagnostics", "target_package": profile["package"], "base_version_code": 414,
        "certificate_sha256": profile["certificate"], "split_id": tool.SPLIT,
        "signature_and_alignment_verified": True, "addon_bytes": 8000, "addon_apk_sha256": "a" * 64,
        "required_base_members": tool.required_base_members("diagnostics")}
    manifest = tool.bundle_manifest([report])
    assert manifest["profiles"][0]["asset"] == "presentation/diagnostics.apk"
    for change in ({"target_package": "game.qualiarts.idolypride"}, {"addon_bytes": 1048577},
                   {"certificate_sha256": "b" * 64}, {"base_version_code": 415},
                   {"required_base_members": {}}, {"required_base_members": {tool.BOOTSTRAP: "f" * 64}}):
        with pytest.raises(ValueError): tool.bundle_manifest([{**report, **change}])
    with pytest.raises(ValueError): tool.bundle_manifest([report, report])


@pytest.mark.parametrize("profile", ["diagnostics", "resources"])
def test_static_runtime_notice_is_in_both_profiles_and_dependency_notices_are_pinned(profile):
    members = tool.license_members(profile)
    assert {name: hashlib.sha256(raw).hexdigest() for name, raw in members.items()} == tool.license_hashes(profile)
    notice = members[tool.LICENSE_PREFIX + tool.RUNTIME_NOTICE]
    assert all(value in notice for value in (b"Component: compiler-rt", b"Component: libc++abi", b"Component: libunwind",
        b"LLVM Exceptions to the Apache 2.0 License", b"Copyright (c) 2009-2019", b"Copyright (c) 2011-2019"))
    assert (tool.LICENSE_PREFIX + "SHADOWHOOK-LICENSE" in members) == (profile == "resources")
