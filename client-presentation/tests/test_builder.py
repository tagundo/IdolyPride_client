"""Unsigned structural boundaries only; no real key, JNI build or installation."""
import hashlib
import importlib.util
from pathlib import Path
import struct
import sys
import time
import json
from zipfile import ZipFile
import xml.etree.ElementTree as ET

import pytest


PATH = Path(__file__).resolve().parents[1] / "build_addon.py"
SPEC = importlib.util.spec_from_file_location("presentation_addon", PATH)
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)
ANDROID = "{http://schemas.android.com/apk/res/android}"


@pytest.fixture
def frozen_fixture(tmp_path, monkeypatch):
    root = tmp_path / "source"
    native = root / "client-presentation/native"
    java = root / "client-presentation/java"
    java.mkdir(parents=True); native.mkdir()
    for name in ("PresentationProvider", "PresentationClient", "NativePresentation"):
        (java / (name + ".java")).write_text("class " + name + " {}")
    (native / "bridge.cpp").write_text("#define HOOK(entry, x, y) x\nHOOK(one, a, b)\n")
    (native / "profile.json").write_text(json.dumps({"aliases": {"one": {}}}))
    (native / "profile.hpp").write_text("// pinned profile")
    (native / "orientation.hpp").write_text("// pinned transition")
    (native / "playback_config.hpp").write_text("// pinned setting")
    for name in ("client-presentation/build_addon.py", "client-presentation/AndroidManifest.template",
                 "client-presentation/licenses/" + tool.RUNTIME_NOTICE,
                 "android-diagnostics/native/SHADOWHOOK-LICENSE", "android-diagnostics/native/THIRD-PARTY-NOTICES.txt"):
        path = root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b"public source")
    blobs = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    commit = "a" * 40
    def git(where, action, ref, *, limit):
        assert where == root and action == "show" and ref.startswith(commit + ":")
        return blobs[ref.split(":", 1)[1]]
    monkeypatch.setattr(tool.pybundle, "_git", git)
    return root, commit


def test_frozen_inventory_covers_both_rotation_headers_and_rejects_drift(frozen_fixture):
    root, commit = frozen_fixture
    sources = tool.frozen_sources(commit, root=root)
    assert "client-presentation/native/orientation.hpp" in sources
    assert "client-presentation/native/playback_config.hpp" in sources
    (root / "client-presentation/native/orientation.hpp").write_text("changed")
    with pytest.raises(ValueError, match="frozen commit"):
        tool.frozen_sources(commit, root=root)


def test_native_receipt_requires_exact_commit_sources_artifact_and_profile(frozen_fixture, tmp_path, monkeypatch):
    root, commit = frozen_fixture
    sources = tool.frozen_sources(commit, root=root)
    path = tmp_path / "libidoly_presentation.so"; path.write_bytes(b"x" * 120)
    sha = tool.digest(path)
    receipt = {"source_commit": commit, "sha256": sha, "bytes": 120,
               "profile_prefix_count": 1, "profile_hook_count": 1,
               "source_unchanged_during_build": True,
               "source_sha256": {name: sources[name] for name in tool.native_source_paths(root)}}
    proof = path.with_name("build-receipt.json")
    proof.write_text(json.dumps(receipt))
    monkeypatch.setattr(tool, "check_elf", lambda path: [16384])
    monkeypatch.setattr(tool, "check_jni", lambda path, **kwargs: [])
    assert tool.verified_native(path, commit, sources, root=root)["sha256"] == sha
    for key, value in (("source_commit", "b" * 40), ("profile_hook_count", 2),
                       ("profile_prefix_count", 2), ("source_unchanged_during_build", False),
                       ("sha256", "0" * 64), ("bytes", 121), ("source_sha256", {})):
        proof.write_text(json.dumps({**receipt, key: value}))
        with pytest.raises(ValueError, match="frozen compile inputs"):
            tool.verified_native(path, commit, sources, root=root)
    proof.write_text(json.dumps(receipt)); path.write_bytes(b"y" * 120)
    with pytest.raises(ValueError, match="frozen compile inputs"):
        tool.verified_native(path, commit, sources, root=root)


def test_public_receipts_reject_duplicate_keys_links_and_oversize(tmp_path):
    path = tmp_path / "proof.json"; path.write_text('{"schema":1,"schema":2}')
    with pytest.raises(ValueError, match="Duplicate"): tool.read_public_json(path)
    link = tmp_path / "link"; link.symlink_to(path)
    with pytest.raises(ValueError, match="regular"): tool.read_public_json(link)
    path.write_bytes(b"x" * (256 * 1024 + 1))
    with pytest.raises(ValueError, match="bounded"): tool.read_public_json(path)


def test_new_feature_accepts_only_exact_source_bound_members(frozen_fixture, tmp_path, monkeypatch):
    root, commit = frozen_fixture
    sources = tool.frozen_sources(commit, root=root)
    native = b"new rotation-aware native"
    sha = hashlib.sha256(native).hexdigest()
    monkeypatch.setattr(tool, "license_hashes", lambda profile: {})
    marker = tool.feature_marker("diagnostics", sha)
    path = tmp_path / "diagnostics.apk"
    members = {"classes.dex": b"new own Java DEX", "AndroidManifest.xml": b"own feature manifest",
               tool.LIBRARY: native, tool.MARKER: json.dumps(marker).encode()}
    with ZipFile(path, "w") as archive:
        for name, raw in members.items(): archive.writestr(name, raw)
    proof = {**marker, "source_commit": commit, "source_sha256": sources,
             "addon_apk_sha256": tool.digest(path), "addon_bytes": path.stat().st_size,
             "signature_and_alignment_verified": True, "base_unchanged": True,
             "member_sha256": {name: hashlib.sha256(raw).hexdigest() for name, raw in members.items()},
             "native_input": {"source_commit": commit, "sha256": sha, "bytes": len(native),
                 "source_sha256": {name: sources[name] for name in tool.native_source_paths(root)},
                 "profile_prefix_count": 1, "profile_hook_count": 1}}
    receipt = path.with_suffix(".provenance.json")
    receipt.write_text(json.dumps(proof))
    assert tool.verified_feature(path, commit, sources, root=root) == proof
    for key, value in (("source_commit", "b" * 40), ("source_sha256", {}),
                       ("signature_and_alignment_verified", False), ("member_sha256", {})):
        receipt.write_text(json.dumps({**proof, key: value}))
        with pytest.raises(ValueError): tool.verified_feature(path, commit, sources, root=root)
    receipt.write_text(json.dumps(proof))
    with ZipFile(path, "a") as archive: archive.writestr("classes2.dex", b"unexpected SDK")
    with pytest.raises(ValueError): tool.verified_feature(path, commit, sources, root=root)


def test_exact_jni_symbols_do_not_confuse_configure_with_configure_playback(tmp_path):
    prefix = 'Java_game_qualiarts_idolypride_presentation_NativePresentation_'
    names = ['JNI_OnLoad', prefix+'configurePlayback']
    strings = bytearray(b'\0'); symbols = bytearray(24)
    for name in names:
        symbols.extend(struct.pack('<IBBHQQ',len(strings),0x12,0,1,0,0))
        strings.extend(name.encode()+b'\0')
    raw = bytearray(64+3*64);raw[:6]=b'\x7fELF\x02\x01'
    struct.pack_into('<Q',raw,40,64);struct.pack_into('<HH',raw,58,64,3)
    struct.pack_into('<II4QII2Q',raw,128,0,3,0,0,len(raw),len(strings),0,0,1,0)
    symbol_start=len(raw)+len(strings)
    struct.pack_into('<II4QII2Q',raw,192,0,11,0,0,symbol_start,len(symbols),1,0,8,24)
    raw.extend(strings);raw.extend(symbols)
    library=tmp_path/'native.so';library.write_bytes(raw)
    assert tool.native_jni_exports(library)==set(names)
    java=tmp_path/'client-presentation/java/game/qualiarts/idolypride/presentation/NativePresentation.java'
    java.parent.mkdir(parents=True);java.write_text('public static native boolean configure();\npublic static native boolean configurePlayback();')
    with pytest.raises(ValueError,match='exactly'):tool.check_jni(library,root=tmp_path)
    java.write_text('public static native boolean configurePlayback();')
    assert tool.check_jni(library,root=tmp_path)==sorted(names)


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
        "supported_installation_modes": list(tool.SUPPORTED_INSTALLATION_MODES),
        "required_base_members": tool.required_base_members("diagnostics")}
    manifest = tool.bundle_manifest([report])
    assert manifest["profiles"][0]["asset"] == "presentation/diagnostics.apk"
    for change in ({"target_package": "game.qualiarts.idolypride"}, {"addon_bytes": 1048577},
                   {"certificate_sha256": "b" * 64}, {"base_version_code": 415},
                   {"supported_installation_modes": ["MODE_INHERIT_EXISTING", "MODE_FULL_INSTALL"]},
                   {"supported_installation_modes": ["MODE_FULL_INSTALL"]},
                   {"supported_installation_modes": "MODE_FULL_INSTALL"},
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
