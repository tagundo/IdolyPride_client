"""Optional translation archives stay separate, pinned and capacity bounded."""
import hashlib
import importlib.util
from pathlib import Path
import sys
from zipfile import ZIP_STORED, ZipFile

import pytest

from tools import build_android_server_manual as tool
from test_android_server_capacity import inventory
from test_build_android_server_manual import synthetic_dex, synthetic_elf, zip_bytes
from test_bundled_translations import make_bundle


def test_android_config_requires_all_optional_pins_and_exposes_absence_explicitly():
    absent = tool.build_config("a" * 64).decode()
    assert 'BUNDLED_TRANSLATIONS_SHA256 = "";' in absent
    assert 'BUNDLED_TRANSLATIONS_BYTES = 0L;' in absent
    present = tool.build_config("a" * 64, "b" * 64, 123).decode()
    assert 'BUNDLED_TRANSLATIONS_SHA256 = "' + "b" * 64 + '";' in present
    assert 'BUNDLED_TRANSLATIONS_BYTES = 123L;' in present
    for sha, size in (("", 1), ("b" * 64, 0), ("invalid", 1), ("b" * 64, True),
                      ("b" * 64, tool.MAX_TRANSLATIONS + 1)):
        with pytest.raises(ValueError):
            tool.build_config("a" * 64, sha, size)


def test_optional_asset_capacity_includes_every_byte_without_enlarging_core_limits():
    core, translations = 190 * tool.MIB, 64 * tool.MIB
    baseline = tool.capacity_plan(inventory(), core)
    optional = tool.capacity_plan(inventory(), core, translations_bytes=translations)
    assert optional["payload_bytes"] == baseline["payload_bytes"] == core
    assert optional["expanded_bytes"] == baseline["expanded_bytes"] + translations
    assert optional["apk_bytes"] >= baseline["apk_bytes"] + translations
    assert optional["staging_bytes"] == optional["apk_bytes"] + tool.SERVER_APK_METADATA_STAGING
    assert tool.MAX_SERVER_APK == tool.MAX_SERVER_EXPANDED == 384 * tool.MIB
    with pytest.raises(ValueError, match="capacity bound"):
        tool.capacity_plan(inventory(), 256 * tool.MIB, translations_bytes=128 * tool.MIB)
    for size in (-1, True, tool.MAX_TRANSLATIONS + 1):
        with pytest.raises(ValueError):
            tool.capacity_plan(inventory(), core, translations_bytes=size)


def test_only_the_exact_pinned_optional_asset_may_be_added_and_audited(tmp_path, monkeypatch):
    dependencies = {f"Lcom/chaquo/python/Type{i};" for i in range(27)}
    own = {"L" + tool.PACKAGE.replace(".", "/") + "/MainActivity;"}
    files = {name: b"old mutable" for name in tool.MUTABLE_NAMES | tool.REMOVED_NAMES}
    files.update({name: synthetic_elf() for name in tool.NATIVE_NAMES})
    files["classes.dex"] = synthetic_dex(sorted(dependencies))
    files["assets/chaquopy/bootstrap.imy"] = b"unchanged runtime"
    baseline, candidate = tmp_path / "baseline.apk", tmp_path / "new.apk"
    baseline.write_bytes(zip_bytes(files))
    optional = tmp_path / "translations.zip"
    optional.write_bytes(b"already validated optional ZIP, streamed from disk")
    replacements = {name: b"new approved input" for name in tool.MUTABLE_NAMES}
    replacements["classes2.dex"] = synthetic_dex(sorted(own))
    replacements[tool.TRANSLATIONS_ASSET] = optional
    hashes = {name: hashlib.sha256(raw.read_bytes() if isinstance(raw, Path) else raw).hexdigest()
              for name, raw in replacements.items()}
    monkeypatch.setattr(ZipFile, "read", lambda *_args, **_kwargs: pytest.fail("Whole ZIP member read forbidden"))
    with ZipFile(baseline) as archive:
        infos = tool.pybundle._members(archive, tool.pybundle.MAX_EXPANDED)
        before = tool.pybundle._hash_members(archive, infos)
        tool.stream_apk(archive, infos, candidate, replacements)
        with pytest.raises(ValueError):
            tool.stream_apk(archive, infos, tmp_path / "bad.apk", {"assets/unapproved.zip": optional})
    report = tool.audit_apk(candidate, before, infos, hashes, dependencies, own)
    assert report["added_apk_members"] == [tool.TRANSLATIONS_ASSET]
    assert report["client_installer_code_absent"] and report["embedded_client_apks_absent"]
    with ZipFile(candidate) as archive:
        info = archive.getinfo(tool.TRANSLATIONS_ASSET)
        assert info.compress_type == ZIP_STORED and info.external_attr == 0o100600 << 16
        with archive.open(info) as stream:
            assert stream.read(4096) == optional.read_bytes()
    unapproved = dict(hashes); unapproved.pop(tool.TRANSLATIONS_ASSET)
    with pytest.raises(ValueError, match="inventory"):
        tool.audit_apk(candidate, before, infos, unapproved, dependencies, own)


def test_mac_shared_input_validator_checks_platform_and_actual_coverage(tmp_path):
    source = Path(__file__).resolve().parents[1] / "macos-server/payload.py"
    spec = importlib.util.spec_from_file_location("optional_translation_mac_payload", source)
    payload = importlib.util.module_from_spec(spec); spec.loader.exec_module(payload)
    assert payload.translation_bundle_input() == (None, {"included": False})
    archive, pins = make_bundle(tmp_path, platform="ios")
    selected, report = payload.translation_bundle_input(archive, pins["expected_sha256"], pins["expected_bytes"])
    assert selected == archive and report["included"] and report["platform"] == "ios"
    assert report["coverage"]["ko"] == {"adv_resources": 3, "translated": 1, "missing": 1, "unchanged_original": 1}
    assert report["sources"]["en"]["terms"] == "NOASSERTION"
    with pytest.raises(ValueError):
        payload.translation_bundle_input(archive, None, pins["expected_bytes"])
    android, pins = make_bundle(tmp_path, platform="android", name="android.zip")
    with pytest.raises(ValueError):
        payload.translation_bundle_input(android, pins["expected_sha256"], pins["expected_bytes"])


@pytest.mark.parametrize("native", (False, True), ids=("cross", "native"))
def test_both_mac_producer_interfaces_forward_optional_pin_trio(tmp_path, monkeypatch, native):
    root = Path(__file__).resolve().parents[1]
    directory = root / "macos-server" if native else root / "macos-server/cross"
    monkeypatch.syspath_prepend(str(root / "macos-server"))
    monkeypatch.syspath_prepend(str(directory))
    spec = importlib.util.spec_from_file_location("optional_mac_native" if native else "optional_mac_cross", directory / "build_app.py")
    builder = importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)
    captured = []
    monkeypatch.setattr(builder, "build", lambda *a, **k: captured.append((a, k)))
    asset = tmp_path / "translations.zip"
    args = ["--translations", str(asset), "--translations-sha256", "a" * 64, "--translations-bytes", "123"]
    if native:
        args += ["--server-data", str(tmp_path / "data.zip"), "--output", str(tmp_path / "new.app"),
                 "--archive", str(tmp_path / "new.zip"), "--evidence", str(tmp_path / "evidence")]
        builder.main(args)
        assert captured[0][1]["translations"] == asset
        assert captured[0][1]["translations_sha256"] == "a" * 64
        assert captured[0][1]["translations_bytes"] == 123
    else:
        for name in ("runtime", "payload", "llvm", "rcodesign", "app", "archive", "evidence"):
            args.extend(["--" + name, str(tmp_path / name)])
        args += ["--source-commit", "b" * 40]
        monkeypatch.setattr(sys, "argv", [str(directory / "build_app.py"), *args])
        builder.main()
        parsed = captured[0][0][0]
        assert parsed.translations == asset and parsed.translations_sha256 == "a" * 64 and parsed.translations_bytes == 123
