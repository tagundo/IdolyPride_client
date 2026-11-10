from pathlib import Path
import json
import subprocess
import hashlib
import struct
import sys
from zipfile import ZipFile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_app


def live_dylib(*, architecture=0x0100000C, install_name="@rpath/libidoly_live.dylib", minimum=13 << 16):
    name = install_name.encode() + b"\0"
    size = (24 + len(name) + 7) // 8 * 8
    identity = struct.pack("<6I", 0xD, size, 24, 0, 0, 0) + name.ljust(size - 24, b"\0")
    target = struct.pack("<6I", 0x32, 24, 1, minimum, minimum, 0)
    commands = identity + target
    return struct.pack("<8I", 0xFEEDFACF, architecture, 0, 6, 2, len(commands), 0, 0) + commands


@pytest.mark.parametrize("kwargs,explanation", (
    ({"architecture": 0x01000007}, "ARM64"),
    ({"install_name": "/private/build/libidoly_live.dylib"}, "@rpath"),
    ({"minimum": 14 << 16}, "macOS 13"),
))
def test_optional_live_engine_rejects_wrong_architecture_install_name_or_os(tmp_path, kwargs, explanation):
    library = tmp_path / "libidoly_live.dylib"
    library.write_bytes(live_dylib(**kwargs))
    with pytest.raises(ValueError, match=explanation):
        build_app.validate_live_engine_library(library)


def test_optional_live_engine_requires_complete_macho_commands(tmp_path):
    library = tmp_path / "libidoly_live.dylib"
    library.write_bytes(live_dylib()[:-1])
    with pytest.raises(ValueError, match="load commands"):
        build_app.validate_live_engine_library(library)


@pytest.fixture
def app_build(tmp_path, monkeypatch):
    payload = tmp_path / "ServerData.zip"
    with ZipFile(payload, "w") as archive:
        archive.writestr("data/protocol/idolypride-6.1.1.pb", b"schema")
        archive.writestr("data/original-master/master-tag.json", b"{}")
    output, archive, evidence = tmp_path / "Server.app", tmp_path / "Server.app.zip", tmp_path / "evidence"
    commands = []

    def run(arguments, **kwargs):
        values = [str(argument) for argument in arguments]
        commands.append(values)
        if "PyInstaller" in values:
            destination = Path(values[values.index("--distpath") + 1]) / "IdolyServerEngine"
            destination.mkdir(parents=True)
            (destination / "IdolyServerEngine").write_bytes(b"frozen engine")
            if "--add-binary" in values:
                argument = values[values.index("--add-binary") + 1]
                source, target = argument.rsplit(":", 1)
                assert target == "." and Path(source).name == "libidoly_live.dylib"
                (destination / "_internal").mkdir()
                # Relocation is allowed to change bytes; input SHA must never
                # masquerade as the final packaged/signed library digest.
                (destination / "_internal/libidoly_live.dylib").write_bytes(Path(source).read_bytes() + b"relocated")
        elif "swiftc" in values:
            Path(values[values.index("-o") + 1]).write_bytes(b"native GUI")
        elif values[0] == "/usr/bin/codesign" and "--force" in values and "--deep" in values:
            library = Path(values[-1]) / "Contents/Resources/runtime/_internal/libidoly_live.dylib"
            if library.exists():
                library.write_bytes(library.read_bytes() + b"signed")
        elif values[0] == "/usr/bin/ditto":
            Path(values[-1]).write_bytes(b"deliverable archive")

    monkeypatch.setattr(build_app.sys, "platform", "darwin")
    monkeypatch.setattr(build_app.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(build_app.importlib.metadata, "version", lambda name: "6.16.0")
    monkeypatch.setattr(build_app.subprocess, "check_output", lambda *args, **kwargs: "a" * 40 + "\n")
    monkeypatch.setattr(build_app, "run", run)
    return payload, output, archive, evidence, commands


def test_default_app_build_does_not_include_or_require_live_engine(app_build):
    payload, output, archive, evidence, commands = app_build
    report = build_app.build(payload, output, archive, evidence, "0.2.16", smoke=False)
    assert report["live_engine"] == {"included": False}
    assert "--add-binary" not in next(command for command in commands if "PyInstaller" in command)
    assert not (output / "Contents/Resources/licenses").exists()
    assert not (output / "Contents/Resources/runtime/_internal/libidoly_live.dylib").exists()


def test_optional_live_engine_records_post_relocation_and_signing_sha_with_notices(app_build, tmp_path):
    payload, output, archive, evidence, commands = app_build
    original = tmp_path / "input-custom-name.dylib"
    original.write_bytes(live_dylib())
    report = build_app.build(payload, output, archive, evidence, "0.2.16", smoke=False,
                             live_engine_library=original)
    live = report["live_engine"]
    embedded = output / "Contents/Resources/runtime/_internal/libidoly_live.dylib"
    actual = hashlib.sha256(embedded.read_bytes()).hexdigest()
    assert live["included"] is True and live["default_enabled"] is False
    assert live["input_sha256"] == hashlib.sha256(original.read_bytes()).hexdigest()
    assert live["embedded_sha256"] == actual != live["input_sha256"]
    assert live["embedded_bytes"] == embedded.stat().st_size
    assert live["ad_hoc_codesign_verified"] is True
    assert live["embedded_relative_path"] == "runtime/_internal/libidoly_live.dylib"
    resources = output / "Contents/Resources"
    for relative in build_app.LIVE_ENGINE_LICENSE_FILES:
        installed = resources / live["license_directory"] / relative
        assert installed.read_bytes() == (build_app.ROOT / "native-live-engine" / relative).read_bytes()
        assert live["license_sha256"][relative] == hashlib.sha256(installed.read_bytes()).hexdigest()
    assert len(live["license_sha256"]) == 6
    provenance = json.loads((resources / "bundle-provenance.json").read_text())
    assert provenance["live_engine"] == live
    codesign = [command for command in commands if command[0] == "/usr/bin/codesign"]
    signed = [command for command in codesign if "--force" in command]
    assert len(signed) == 2 and "--deep" in signed[0] and "--deep" not in signed[1]
    assert not list((resources / "licenses").rglob("*.go"))


def test_native_smoke_launches_bundle_executable_and_requires_visible_window(tmp_path, monkeypatch):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    report = {"gui_started": True, "window_visible": False, "server_started": True, "server_stopped": True}
    (evidence / "app-smoke.json").write_text(json.dumps(report))
    app = tmp_path / "이동한 앱/Local Server.app"
    calls = []

    class Process:
        def __init__(self, command, **options):
            calls.append((command, options))

        def wait(self, timeout):
            return 0

    monkeypatch.setattr(build_app.subprocess, "Popen", Process)
    with pytest.raises(ValueError, match="visible-window"):
        build_app.smoke_native_app(app, evidence, tmp_path / "data")
    command, options = calls[0]
    assert command[0] == str(app / "Contents/MacOS/IdolyPrideLocalServer")
    assert options["start_new_session"] is True
    assert "--app-smoke" in command
    report["window_visible"] = True
    (evidence / "app-smoke.json").write_text(json.dumps(report))
    assert build_app.smoke_native_app(app, evidence, tmp_path / "data") == report


def test_native_smoke_timeout_terminates_only_its_owned_process_group_and_reports_phase(tmp_path, monkeypatch):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "app-smoke.checkpoint.json").write_text(json.dumps({"phase": "model_initialized"}))
    terminated = []

    class Process:
        pid = 123456

        def __init__(self, *args, **kwargs):
            self.waits = 0

        def wait(self, timeout):
            self.waits += 1
            if self.waits == 1:
                raise subprocess.TimeoutExpired("owned-native-app", timeout)
            return -15

    monkeypatch.setattr(build_app.subprocess, "Popen", Process)
    monkeypatch.setattr(build_app.os, "killpg", lambda pid, signal: terminated.append((pid, signal)))
    with pytest.raises(ValueError, match="model_initialized"):
        build_app.smoke_native_app(tmp_path / "Local.app", evidence, tmp_path / "data", timeout=0.1)
    assert terminated == [(123456, build_app.signal.SIGTERM)]
