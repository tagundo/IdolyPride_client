#!/usr/bin/env python3
"""Build an Apple Silicon SwiftUI app with its own frozen local-server engine."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import plistlib
import signal
import shutil
import struct
import subprocess
import sys
import tempfile
from zipfile import ZipFile

from payload import member_path
from certificate_bundle import install_certificate_bundle

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
APP_NAME = "IdolyPrideLocalServer"
LIVE_ENGINE_NAME = "libidoly_live.dylib"
LIVE_ENGINE_LICENSE_FILES = (
    "LICENSE", "NOTICE", "third-party-licenses/Go-LICENSE", "third-party-licenses/Protobuf-LICENSE",
    "third-party-licenses/YAML-LICENSE", "third-party-licenses/YAML-NOTICE",
)


def run(arguments, **kwargs):
    subprocess.run([str(argument) for argument in arguments], check=True, **kwargs)


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def validate_live_engine_library(path: Path) -> dict:
    """Require the relocatable, thin ARM64 macOS 13 dylib produced by our builder."""
    raw = path.read_bytes()
    if (len(raw) < 32 or raw[:4] != b"\xcf\xfa\xed\xfe"
            or struct.unpack_from("<I", raw, 4)[0] != 0x0100000C
            or struct.unpack_from("<I", raw, 12)[0] != 6):
        raise ValueError("The optional live engine must be a thin ARM64 Mach-O dynamic library")
    count, commands_size = struct.unpack_from("<II", raw, 16)
    end = 32 + commands_size
    if end > len(raw):
        raise ValueError("The optional live engine has invalid Mach-O load commands")
    position, install_name, deployment_target = 32, None, None
    try:
        for _ in range(count):
            command, length = struct.unpack_from("<II", raw, position)
            if length < 8 or position + length > end:
                raise ValueError("The optional live engine has invalid Mach-O load commands")
            if command == 0xD:  # LC_ID_DYLIB
                if length < 24 or install_name is not None:
                    raise ValueError("The optional live engine must have one valid dylib install name")
                offset = struct.unpack_from("<I", raw, position + 8)[0]
                if offset < 24 or offset >= length:
                    raise ValueError("The optional live engine has an invalid dylib install name")
                name_end = raw.index(b"\0", position + offset, position + length)
                install_name = raw[position + offset:name_end].decode("utf-8")
            elif command == 0x32:  # LC_BUILD_VERSION
                if length < 24 or deployment_target is not None:
                    raise ValueError("The optional live engine must have one valid macOS deployment target")
                target, minimum = struct.unpack_from("<II", raw, position + 8)
                if target != 1:
                    raise ValueError("The optional live engine must target macOS")
                deployment_target = minimum
            elif command == 0x24:  # LC_VERSION_MIN_MACOSX
                if length < 16 or deployment_target is not None:
                    raise ValueError("The optional live engine must have one valid macOS deployment target")
                deployment_target = struct.unpack_from("<I", raw, position + 8)[0]
            position += length
    except (struct.error, UnicodeDecodeError) as error:
        raise ValueError("The optional live engine has malformed Mach-O load commands") from error
    if position != end or install_name != "@rpath/" + LIVE_ENGINE_NAME or deployment_target != 13 << 16:
        raise ValueError("The optional live engine must use macOS 13.0 and @rpath/libidoly_live.dylib")
    return {"architecture": "arm64", "macos_deployment_target": "13.0", "install_name": install_name}


def copy_live_engine_licenses(resources: Path) -> dict:
    """Copy attribution texts only, keeping all Go sources out of the app assets."""
    destination = resources / "licenses/native-live-engine"
    hashes = {}
    for relative in LIVE_ENGINE_LICENSE_FILES:
        source = ROOT / "native-live-engine" / relative
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        hashes[relative] = digest(target)
    return {"license_directory": "licenses/native-live-engine", "license_sha256": hashes}


def dump_native_failure(evidence: Path):
    for name in ("app-smoke.checkpoint.json", "app-smoke.json", "native-app-stdout.log", "native-app-stderr.log"):
        path = evidence / name
        if path.is_file():
            print(f"Native diagnostic {name}:\n{path.read_text(errors='replace')[-8000:]}", file=sys.stderr)


def smoke_native_app(app: Path, evidence: Path, data_dir: Path, timeout: float = 75, *, experimental_main_live=False):
    """Launch the actual bundle executable with owned output and process group."""
    executable = app / "Contents/MacOS" / APP_NAME
    command = [str(executable), "--app-smoke", "--smoke-report", str(evidence / "app-smoke.json"),
               "--data-dir", str(data_dir)]
    if experimental_main_live:
        command.append("--experimental-main-live")
    with (evidence / "native-app-stdout.log").open("w") as stdout, (evidence / "native-app-stderr.log").open("w") as stderr:
        process = subprocess.Popen(command, stdout=stdout, stderr=stderr, start_new_session=True)
        try:
            returncode = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
            dump_native_failure(evidence)
            checkpoint = evidence / "app-smoke.checkpoint.json"
            phase = json.loads(checkpoint.read_text()).get("phase", "unknown") if checkpoint.is_file() else "no-launch-checkpoint"
            raise ValueError("Native app smoke timed out at phase: " + phase) from None
    if returncode != 0:
        dump_native_failure(evidence)
        details = (evidence / "native-app-stderr.log").read_text(errors="replace")[-6000:]
        raise ValueError(f"Native app exited with status {returncode}: {details}")
    report_path = evidence / "app-smoke.json"
    if not report_path.is_file():
        dump_native_failure(evidence)
        raise ValueError("Native app did not write its visible-window smoke report")
    report = json.loads(report_path.read_text())
    if experimental_main_live and (report.get("experimental_main_live_requested") is not True
                                  or report.get("experimental_main_live_observed") is not True):
        raise ValueError("Native app did not apply the explicit experimental live setting")
    if not all(report.get(key) is True for key in ("gui_started", "window_visible", "server_started", "server_stopped")):
        dump_native_failure(evidence)
        raise ValueError("Native visible-window app did not complete its start/stop smoke check")
    return report


def build(server_data: Path, output: Path, archive: Path, evidence: Path, version: str, smoke: bool = True,
          live_engine_library: Path | None = None, *, build_number: str = "41"):
    if sys.platform != "darwin" or platform.machine() != "arm64":
        raise ValueError("Build on an Apple Silicon macOS runner (macos-15, uname -m = arm64)")
    if output.suffix != ".app" or output.exists() or archive.exists():
        raise ValueError("Choose new .app and .app.zip output paths")
    if not version or any(char not in "0123456789." for char in version):
        raise ValueError("Version must contain only digits and periods")
    if not build_number or any(char not in "0123456789" for char in build_number) or int(build_number) <= 0:
        raise ValueError("Build number must be a positive decimal integer")
    live_engine = {"included": False}
    if live_engine_library is not None:
        live_engine_library = live_engine_library.expanduser().resolve(strict=True)
        live_engine = {"included": True, "default_enabled": False,
                       **validate_live_engine_library(live_engine_library),
                       "input_sha256": digest(live_engine_library),
                       "input_bytes": live_engine_library.stat().st_size}
    with ZipFile(server_data) as zipped:
        names = [member_path(info.filename) for info in zipped.infolist() if not info.is_dir()]
        if "protocol/idolypride-6.1.1.pb" not in names or "original-master/master-tag.json" not in names:
            raise ValueError("ServerData.zip does not contain the exact schema and master archive")
        if zipped.testzip() is not None:
            raise ValueError("ServerData.zip failed its CRC validation")
    evidence.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ, MACOSX_DEPLOYMENT_TARGET="13.0", PYTHONDONTWRITEBYTECODE="1")
    with (evidence / "architecture.txt").open("w") as stream:
        run(["/usr/bin/uname", "-m"], stdout=stream)
    with tempfile.TemporaryDirectory(prefix="idoly-macos-build-") as directory:
        temporary = Path(directory)
        pyinstaller = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--console",
             "--name", "IdolyServerEngine", "--target-arch", "arm64", "--codesign-identity", "-",
             "--paths", ROOT / "src", "--paths", HERE,
             "--distpath", temporary / "dist", "--workpath", temporary / "work",
             "--specpath", temporary / "spec"]
        if live_engine_library is not None:
            # A fixed basename makes ctypes lookup independent of the input
            # filename. PyInstaller places this in sys._MEIPASS, the onedir
            # runtime's _internal directory, and processes/signs its Mach-O.
            staging = temporary / "live-engine"
            staging.mkdir()
            shutil.copy2(live_engine_library, staging / LIVE_ENGINE_NAME)
            pyinstaller.extend(["--add-binary", str(staging / LIVE_ENGINE_NAME) + ":."])
        pyinstaller.append(HERE / "engine.py")
        run(pyinstaller, cwd=ROOT, env=environment)
        contents = output / "Contents"
        resources = contents / "Resources"
        executable = contents / "MacOS" / APP_NAME
        executable.parent.mkdir(parents=True)
        resources.mkdir()
        shutil.copytree(temporary / "dist/IdolyServerEngine", resources / "runtime", symlinks=True)
        shutil.copy2(server_data, resources / "ServerData.zip")
        public_tls_trust = install_certificate_bundle(resources / "runtime/_internal", resources / "licenses/tls")
        embedded_live_engine = resources / "runtime/_internal" / LIVE_ENGINE_NAME
        if live_engine_library is not None:
            if not embedded_live_engine.is_file() or embedded_live_engine.is_symlink():
                raise ValueError("PyInstaller did not include the live engine at sys._MEIPASS/libidoly_live.dylib")
            validate_live_engine_library(embedded_live_engine)
            live_engine.update(copy_live_engine_licenses(resources))
            live_engine["embedded_relative_path"] = "runtime/_internal/" + LIVE_ENGINE_NAME
        with (contents / "Info.plist").open("wb") as stream:
            plistlib.dump({
                "CFBundleExecutable": APP_NAME,
                "CFBundleIdentifier": "game.idolypride.localserver",
                "CFBundleName": "IdolyPride Local Server",
                "CFBundleDisplayName": "아이프라 로컬 서버",
                "CFBundlePackageType": "APPL",
                "CFBundleShortVersionString": version,
                "CFBundleVersion": build_number,
                "LSMinimumSystemVersion": "13.0",
                "LSApplicationCategoryType": "public.app-category.games",
                "NSHighResolutionCapable": True,
                "NSDownloadsFolderUsageDescription": "게임 리소스를 Downloads/IdolyPride에 보관하고 게임에 제공합니다.",
                "NSPrincipalClass": "NSApplication",
            }, stream)
        run(["/usr/bin/xcrun", "swiftc", "-swift-version", "5", "-parse-as-library", "-O",
             "-target", "arm64-apple-macos13.0", "-framework", "SwiftUI", "-framework", "AppKit",
             HERE / "App.swift", HERE / "PresentationSettings.swift", "-o", executable], env=environment)
        source_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        provenance = {"version": version, "build_number": build_number, "architecture": "arm64", "minimum_macos": "13.0",
            "source_commit": source_commit, "server_data_sha256": digest(server_data),
            "source_sha256": {name: digest(HERE / name) for name in ("App.swift", "PresentationSettings.swift", "engine.py", "payload.py")},
            "python": platform.python_version(),
            "pyinstaller": importlib.metadata.version("PyInstaller"),
            "signature": "ad-hoc", "notarized": False,
            "user_python_required": False, "user_terminal_required": False,
            "game_client_tested": False, "live_engine": live_engine, "public_tls_trust": public_tls_trust}
        write_json(resources / "bundle-provenance.json", provenance)
        run(["/usr/bin/codesign", "--force", "--deep", "--sign", "-", output])
        if live_engine_library is not None:
            run(["/usr/bin/codesign", "--verify", "--strict", embedded_live_engine])
            # PyInstaller may relocate Mach-O commands and deep signing may
            # replace its signature. Record those final app bytes separately
            # from the input digest, then reseal only the outer app resource.
            live_engine.update(embedded_sha256=digest(embedded_live_engine),
                               embedded_bytes=embedded_live_engine.stat().st_size,
                               ad_hoc_codesign_verified=True)
            write_json(resources / "bundle-provenance.json", provenance)
            run(["/usr/bin/codesign", "--force", "--sign", "-", output])
            if digest(embedded_live_engine) != live_engine["embedded_sha256"]:
                raise ValueError("The outer app signing unexpectedly changed the embedded live engine")
        run(["/usr/bin/codesign", "--verify", "--deep", "--strict", output])
        if smoke:
            runtime_environment = dict(environment)
            for key in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "CONDA_PREFIX", "DYLD_LIBRARY_PATH", "DYLD_FALLBACK_LIBRARY_PATH"):
                runtime_environment.pop(key, None)
            runtime_environment["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin"
            runtime_environment["PYTHONNOUSERSITE"] = "1"
            engine = resources / "runtime/IdolyServerEngine"
            run([engine, "--smoke", "--data-dir", temporary / "engine-smoke-data",
                 "--server-data", resources / "ServerData.zip", "--report", evidence / "engine-smoke.json"],
                env=runtime_environment, timeout=120)
            engine_report = json.loads((evidence / "engine-smoke.json").read_text())
            if engine_report.get("frozen_runtime") is not True:
                raise ValueError("The bundled engine did not use its frozen Python runtime")
            if engine_report.get("home_fish_heaven_absent") is not True:
                raise ValueError("The bundled engine did not verify the inactive home fish-heaven event is absent")
            if not all(engine_report.get(key) is True for key in
                       ("home_positions_distinct", "quest_top_list_main", "quest_catalog_readonly",
                        "quest_contest_area_locked", "quest_tutorial_context", "initial_inventory_master_backed",
                        "default_unit_complete", "initial_inventory_readonly", "starter_inventory_persisted",
                        "quest_list_asset", "quest_list_asset_tutorial_full", "quest_list_asset_tutorial_short",
                        "quest_list_asset_ordinary_buddy_name", "quest_list_asset_rental_rejected", "quest_list_asset_readonly",
                        "tutorial_replay_short", "tutorial_replay_full", "tutorial_replay_canonical",
                        "tutorial_replay_master_references", "tutorial_replay_readonly", "tutorial_replay_assets_covered")):
                raise ValueError("The bundled engine did not verify the local starter inventory, formation and read-only main-live catalog")
            if tuple(engine_report.get(key) for key in
                     ("initial_card_count", "initial_item_count", "default_unit_slot_count")) != (17, 2, 5):
                raise ValueError("The bundled engine did not verify the canonical initial inventory and five-slot unit")
            if engine_report.get("quest_list_asset_count") != 5:
                raise ValueError("The bundled engine did not verify exactly five ordered live character assets")
            expected_replay_counts = {"quest_list_asset_tutorial_short_count": 8, "quest_list_asset_tutorial_full_count": 9,
                "tutorial_replay_short_charts": 158, "tutorial_replay_full_charts": 156,
                "tutorial_replay_short_score": 8813, "tutorial_replay_full_score": 10717}
            if any(type(engine_report.get(key)) is not int or engine_report[key] != value
                   for key, value in expected_replay_counts.items()):
                raise ValueError("The bundled engine did not verify the fixed official tutorial recordings and their appearance coverage")
            if live_engine_library is not None:
                main_flags = ("main_live_included", "main_live_first_quest", "main_live_mode_default_off",
                    "main_live_opt_in", "main_live_persisted", "main_live_attempts_persisted",
                    "main_live_clock_preserved", "main_live_identity_preserved", "main_live_sessions_preserved",
                    "main_live_settings_preserved", "main_live_cached_no_grant")
                if not all(engine_report.get(key) is True for key in main_flags):
                    raise ValueError("The bundled engine did not verify opt-in main-live settlement and exact persistent retries")
            moved = temporary / "이동한 앱" / "IdolyPride Local Server.app"
            moved.parent.mkdir()
            shutil.copytree(output, moved, symlinks=True)
            if live_engine_library is not None:
                smoke_native_app(moved, evidence, temporary / "gui-smoke-data", experimental_main_live=True)
            else:
                smoke_native_app(moved, evidence, temporary / "gui-smoke-data")
            run(["/usr/bin/codesign", "--verify", "--deep", "--strict", moved])
        run(["/usr/bin/codesign", "--verify", "--deep", "--strict", output])
        archive.parent.mkdir(parents=True, exist_ok=True)
        run(["/usr/bin/ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", output, archive])
        provenance.update(archive_sha256=digest(archive), archive_bytes=archive.stat().st_size,
                          bundled_engine_tested=smoke, native_gui_start_stop_tested=smoke)
        write_json(evidence / "build-report.json", provenance)
    return provenance


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server-data", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path, help="New IdolyPrideLocalServer.app path")
    parser.add_argument("--archive", required=True, type=Path, help="New deliverable .app.zip path")
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--version", default="0.3.22")
    parser.add_argument("--build-number", default="41")
    parser.add_argument("--skip-smoke", action="store_true", help="Development only; release builds must run smoke checks")
    parser.add_argument("--live-engine-library", type=Path,
                        help="Optional ARM64 macOS 13 libidoly_live.dylib; experimental engine remains off by default")
    args = parser.parse_args(argv)
    try:
        build(args.server_data.resolve(), args.output.resolve(), args.archive.resolve(),
              args.evidence.resolve(), args.version, not args.skip_smoke,
              live_engine_library=args.live_engine_library, build_number=args.build_number)
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        parser.exit(1, f"macOS app build failed: {error}\n")
    print(args.archive)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
