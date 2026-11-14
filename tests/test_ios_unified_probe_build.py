"""Portable probe packaging checks; these do not compile Apple/UIKit code."""
import importlib.util
from pathlib import Path
import plistlib
import struct
import sys

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
