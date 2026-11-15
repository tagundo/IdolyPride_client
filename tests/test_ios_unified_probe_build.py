"""Portable probe packaging checks; these do not compile Apple/UIKit code."""
import importlib.util
import hashlib
import json
from pathlib import Path
import plistlib
import struct
import sys
from zipfile import ZipFile

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "ios-unified"
sys.path.insert(0, str(TOOLS))
spec = importlib.util.spec_from_file_location("ios_probe_builder_test", TOOLS / "build_probe.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def native_image(name, *, platform=7, cpu=0x0100000C):
    version = struct.pack("<6I", 0x32, 24, platform, 13 << 16, 18 << 16, 0)
    identifier = ("@rpath/" + name + ".framework/" + name).encode() + b"\0"
    length = (24 + len(identifier) + 7) & ~7
    dylib = struct.pack("<6I", 0xD, length, 24, 0, 0, 0) + identifier
    dylib += b"\0" * (length - len(dylib))
    # Freshly built native staging is unsigned; probe signs its copied output.
    header = struct.pack("<8I", 0xFEEDFACF, cpu, 0, 6, 2, len(version) + len(dylib), 0, 0)
    return header + version + dylib


def prepared(tmp_path, *, platform=7, cpu=0x0100000C):
    app = tmp_path / "Prepared.app"
    for name in ("Python", "IdolyEmbeddedServer"):
        directory = app / "Frameworks" / (name + ".framework")
        directory.mkdir(parents=True)
        (directory / name).write_bytes(native_image(name, platform=platform, cpu=cpu))
        (directory / "Info.plist").write_bytes(plistlib.dumps({"CFBundleExecutable": name,
            "CFBundlePackageType": "FMWK", "CFBundleSupportedPlatforms": ["iPhoneSimulator"]}))
    (app / "python-stdlib").mkdir()
    (app / "python-stdlib/placeholder.py").write_text("# public fixture\n")
    package = app / "LocalServer/python/idoly_local"
    package.mkdir(parents=True)
    (package / "ios_host.py").write_text("# fixture only\n")
    for name in ("ServerData.zip", "bundledTranslations.zip", "bundledTranslations.json"):
        (app / "LocalServer" / name).write_bytes(b"fixture")
    return app


@pytest.mark.parametrize("value, expected", [("arm64", "arm64"), ("aarch64", "arm64"),
                                               ("x86_64", "x86_64"), ("AMD64", "x86_64")])
def test_only_supported_simulator_host_architectures(value, expected):
    assert builder.host_architecture(value) == expected
    with pytest.raises(ValueError, match="Simulator probe"):
        builder.host_architecture("i386")


def test_unsigned_simulator_staging_validates_without_apple_execution(tmp_path):
    app = prepared(tmp_path)
    files, size, frameworks = builder.validate_inputs(app, tmp_path / "Probe.app", "arm64")
    assert size == sum(row[2].st_size for row in files)
    assert set(frameworks) == {"Python", "IdolyEmbeddedServer"}
    assert all(row["target"] == "simulator" for row in frameworks.values())
    assert not (tmp_path / "Probe.app").exists()


def test_device_or_wrong_cpu_input_is_rejected_before_output_creation(tmp_path):
    app = prepared(tmp_path, platform=2)
    with pytest.raises(ValueError, match="platform differs"):
        builder.validate_inputs(app, tmp_path / "Probe.app", "arm64")
    assert not (tmp_path / "Probe.app").exists()


def test_host_arch_must_exist_in_every_framework(tmp_path):
    app = prepared(tmp_path)
    with pytest.raises(ValueError, match="lacks host Simulator architecture"):
        builder.validate_inputs(app, tmp_path / "Probe.app", "x86_64")


@pytest.mark.parametrize("directory_link", [False, True])
def test_prepared_tree_cannot_read_external_symlinks(tmp_path, directory_link):
    app = prepared(tmp_path)
    outside = tmp_path / "outside"
    if directory_link:
        outside.mkdir()
    else:
        outside.write_text("must not be copied")
    (app / "python-stdlib/external").symlink_to(outside, target_is_directory=directory_link)
    with pytest.raises(ValueError, match="link"):
        builder.collect_layout(app)


def test_existing_or_nested_output_is_preserved_and_rejected(tmp_path):
    app = prepared(tmp_path)
    output = tmp_path / "Existing.app"
    output.mkdir()
    (output / "keep").write_text("original")
    with pytest.raises(ValueError, match="Fresh absolute"):
        builder.validate_inputs(app, output, "arm64")
    assert (output / "keep").read_text() == "original"
    with pytest.raises(ValueError, match="must be separate"):
        builder.validate_inputs(app, app / "Nested.app", "arm64")
    with pytest.raises(ValueError, match="must be separate"):
        builder.validate_inputs(app, tmp_path / "Elsewhere/../Prepared.app/Nested.app", "arm64")


def test_report_cannot_modify_prepared_input(tmp_path, monkeypatch):
    app = prepared(tmp_path)
    monkeypatch.setattr(builder.sys, "platform", "darwin")
    with pytest.raises(ValueError, match="Fresh separate absolute report"):
        builder.build(app, tmp_path / "Probe.app", arch="arm64", report_path=app / "new-report.json")
    assert not (app / "new-report.json").exists()
    assert not (tmp_path / "Probe.app").exists()


def test_layout_copy_scope_excludes_any_prepared_root_executable(tmp_path):
    app = prepared(tmp_path)
    (app / "UnusedExecutable").write_bytes(b"must not enter probe")
    files, _ = builder.collect_layout(app)
    assert "UnusedExecutable" not in {row[0] for row in files}
    assert all(row[0].split("/")[0] in builder.LAYOUT for row in files)


def test_probe_target_is_explicitly_ios_simulator(tmp_path):
    for arch in ("arm64", "x86_64"):
        command = builder.clang_command("/SDK/clang", "/SDK/iPhoneSimulator.sdk", tmp_path / "Probe.app", arch)
        assert arch + "-apple-ios13.0-simulator" in command
        assert "-Wl,-rpath,@executable_path/Frameworks" in command
        assert "IdolyEmbeddedServer" in command
        assert not any("macabi" in item or "macos" in item for item in command)
    value = plistlib.loads(plistlib.dumps(builder.info_plist()))
    assert value["CFBundleIdentifier"] == "game.qualiarts.idolypride.iosprobe"
    assert value["CFBundleSupportedPlatforms"] == ["iPhoneSimulator"]


def test_linux_build_cannot_claim_an_apple_binary(tmp_path, monkeypatch):
    app = prepared(tmp_path)
    monkeypatch.setattr(builder.sys, "platform", "linux")
    with pytest.raises(ValueError, match="macOS/Xcode"):
        builder.build(app, tmp_path / "Probe.app", arch="arm64")
    assert not (tmp_path / "Probe.app").exists()


def test_language_probe_copies_original_data_as_nonexecutable_without_game_binary(tmp_path):
    app=prepared(tmp_path)
    for name in ('client-languages.zip','client-languages.json'):(app/'LocalServer'/name).write_bytes(b'fixture')
    path=app/'Data/Managed/Metadata/global-metadata.dat';path.parent.mkdir(parents=True);path.write_bytes(b'data only');path.chmod(0o644)
    files,_=builder.collect_layout(app)
    assert 'Data/Managed/Metadata/global-metadata.dat' in {row[0] for row in files}
    path.chmod(0o755)
    with pytest.raises(ValueError,match='nonexecutable'):builder.collect_layout(app)


def test_language_probe_rejects_missing_base_data_before_build(tmp_path):
    app=prepared(tmp_path)
    (app/'LocalServer/client-languages.zip').write_bytes(b'fixture')
    with pytest.raises(ValueError,match='requires the original nonexecutable Data tree'):
        builder.collect_layout(app)


def language_probe_input(tmp_path, *, mutate=None, manifest_bytes=None):
    """Small independently shaped prebuilt-client archive; no game executable."""
    app = prepared(tmp_path)
    paths = ("Data/resources.assets","Data/Managed/Metadata/global-metadata.dat")
    payloads = {(language,path):(language+":"+path).encode()
                for language in ("ko","en","ja") for path in paths}
    manifest = {"schema":1,"policy":"ios-prebuilt-client-data-v1","bundle_id":"local.idoly.client-data",
        "common":{"Data/boot.config":{"bytes":4,"sha256":hashlib.sha256(b"boot").hexdigest()}},
        "languages":{},"source":{key:hashlib.sha256(key.encode()).hexdigest()
            for key in ("stock_ipa_sha256","base_ipa_sha256","english_ui_sha256")}}
    for language in ("ko","en","ja"):
        manifest["languages"][language] = {}
        for path in paths:
            content = payloads[(language,path)]
            row = {"bytes":len(content),"sha256":hashlib.sha256(content).hexdigest(),
                   "source":"base" if language == "ko" else "archive"}
            if language != "ko": row["member"] = language+"/"+path
            manifest["languages"][language][path] = row
            if language == "ko":
                target = app/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(content)
    (app/"Data/boot.config").write_bytes(b"boot")
    if mutate is not None: mutate(manifest)
    raw = json.dumps(manifest,sort_keys=True).encode() if manifest_bytes is None else manifest_bytes
    package = app/"LocalServer/client-languages.zip"
    with ZipFile(package,"w") as archive:
        archive.writestr("manifest.json",raw)
        for (language,path),content in payloads.items():
            if language != "ko": archive.writestr(language+"/"+path,content)
    package_sha = hashlib.sha256(package.read_bytes()).hexdigest()
    pin = {"schema":1,"bytes":package.stat().st_size,"sha256":package_sha}
    (app/"LocalServer/client-languages.json").write_text(json.dumps(pin))
    with ZipFile(app/"LocalServer/ServerData.zip","w") as archive:
        archive.writestr("data/protocol/idolypride-6.1.1.pb",b"public-protocol-fixture")
    return app,{"LocalServer/client-languages.zip":package_sha},manifest,raw


def test_legacy_portable_staging_has_no_derived_language_canaries(tmp_path):
    app = prepared(tmp_path)
    assert builder.derive_language_canaries(app,{}) is None
    assert not (app/"probe-language-canaries.json").exists()


def test_derive_language_canaries_uses_verified_copy_pin_and_only_two_fixed_overlay_records(tmp_path):
    app,copied,manifest,raw = language_probe_input(tmp_path)
    watched = ("LocalServer/client-languages.zip","LocalServer/client-languages.json",
        "LocalServer/ServerData.zip","Data/resources.assets","Data/Managed/Metadata/global-metadata.dat")
    before = {name:(app/name).read_bytes() for name in watched}
    result = builder.derive_language_canaries(app,copied)
    assert result == {"schema":1,"bundle_id":"local.idoly.client-data",
        "client_archive_sha256":copied["LocalServer/client-languages.zip"],
        "client_manifest_sha256":hashlib.sha256(raw).hexdigest(),
        "descriptor_sha256":hashlib.sha256(b"public-protocol-fixture").hexdigest(),
        "languages":{language:{path:{"bytes":row["bytes"],"sha256":row["sha256"]}
            for path,row in manifest["languages"][language].items()} for language in ("ko","en","ja")}}
    assert all(set(rows) == {"Data/resources.assets","Data/Managed/Metadata/global-metadata.dat"}
               for rows in result["languages"].values())
    assert all(set(row) == {"bytes","sha256"} for rows in result["languages"].values() for row in rows.values())
    assert {name:(app/name).read_bytes() for name in watched} == before
    assert not (app/"probe-language-canaries.json").exists()  # Caller writes the returned derived artifact.


@pytest.mark.parametrize("mismatch", ("copied_sha","pin_size"))
def test_derive_language_canaries_rejects_unverified_archive_descriptor_pin(tmp_path, mismatch):
    app,copied,_,_ = language_probe_input(tmp_path)
    if mismatch == "copied_sha": copied["LocalServer/client-languages.zip"] = "0"*64
    else:
        descriptor = app/"LocalServer/client-languages.json"
        pin = json.loads(descriptor.read_text());pin["bytes"] += 1;descriptor.write_text(json.dumps(pin))
    with pytest.raises(ValueError,match="copy pin differs"):
        builder.derive_language_canaries(app,copied)
    assert not (app/"probe-language-canaries.json").exists()


def test_derive_language_canaries_requires_package_descriptor_file(tmp_path):
    app,copied,_,_ = language_probe_input(tmp_path)
    (app/"LocalServer/client-languages.json").unlink()
    with pytest.raises(FileNotFoundError): builder.derive_language_canaries(app,copied)
    assert not (app/"probe-language-canaries.json").exists()


def test_derive_language_canaries_rejects_missing_fixed_overlay_record(tmp_path):
    def missing(manifest): del manifest["languages"]["ko"]["Data/resources.assets"]
    app,copied,_,_ = language_probe_input(tmp_path,mutate=missing)
    with pytest.raises(ValueError,match="Missing client-data language files"):
        builder.derive_language_canaries(app,copied)


def test_derive_language_canaries_bounds_manifest_before_json_decode(tmp_path):
    app,copied,_,_ = language_probe_input(tmp_path,manifest_bytes=b" "*(256*1024+1))
    with pytest.raises(ValueError,match="manifest exceeds bound"):
        builder.derive_language_canaries(app,copied)


def test_derive_language_canaries_rejects_wrong_language_inventory(tmp_path):
    def wrong(manifest): manifest["languages"]["fr"] = manifest["languages"].pop("ja")
    app,copied,_,_ = language_probe_input(tmp_path,mutate=wrong)
    with pytest.raises(ValueError,match="Invalid client-data inventory"):
        builder.derive_language_canaries(app,copied)
