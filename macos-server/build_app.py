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
import subprocess
import sys
import tempfile
from zipfile import ZipFile

from payload import member_path

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
APP_NAME = "IdolyPrideLocalServer"


def run(arguments, **kwargs):
    subprocess.run([str(argument) for argument in arguments], check=True, **kwargs)


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def dump_native_failure(evidence: Path):
    for name in ("app-smoke.checkpoint.json", "app-smoke.json", "native-app-stdout.log", "native-app-stderr.log"):
        path = evidence / name
        if path.is_file():
            print(f"Native diagnostic {name}:\n{path.read_text(errors='replace')[-8000:]}", file=sys.stderr)


def smoke_native_app(app: Path, evidence: Path, data_dir: Path, timeout: float = 75):
    """Launch the actual bundle executable with owned output and process group."""
    executable = app / "Contents/MacOS" / APP_NAME
    command = [str(executable), "--app-smoke", "--smoke-report", str(evidence / "app-smoke.json"),
               "--data-dir", str(data_dir)]
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
    if not all(report.get(key) is True for key in ("gui_started", "window_visible", "server_started", "server_stopped")):
        dump_native_failure(evidence)
        raise ValueError("Native visible-window app did not complete its start/stop smoke check")
    return report


def build(server_data: Path, output: Path, archive: Path, evidence: Path, version: str, smoke: bool = True):
    if sys.platform != "darwin" or platform.machine() != "arm64":
        raise ValueError("Build on an Apple Silicon macOS runner (macos-15, uname -m = arm64)")
    if output.suffix != ".app" or output.exists() or archive.exists():
        raise ValueError("Choose new .app and .app.zip output paths")
    if not version or any(char not in "0123456789." for char in version):
        raise ValueError("Version must contain only digits and periods")
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
        run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--console",
             "--name", "IdolyServerEngine", "--target-arch", "arm64", "--codesign-identity", "-",
             "--paths", ROOT / "src", "--paths", HERE,
             "--distpath", temporary / "dist", "--workpath", temporary / "work",
             "--specpath", temporary / "spec", HERE / "engine.py"], cwd=ROOT, env=environment)
        contents = output / "Contents"
        resources = contents / "Resources"
        executable = contents / "MacOS" / APP_NAME
        executable.parent.mkdir(parents=True)
        resources.mkdir()
        shutil.copytree(temporary / "dist/IdolyServerEngine", resources / "runtime", symlinks=True)
        shutil.copy2(server_data, resources / "ServerData.zip")
        with (contents / "Info.plist").open("wb") as stream:
            plistlib.dump({
                "CFBundleExecutable": APP_NAME,
                "CFBundleIdentifier": "game.idolypride.localserver",
                "CFBundleName": "IdolyPride Local Server",
                "CFBundleDisplayName": "아이프라 로컬 서버",
                "CFBundlePackageType": "APPL",
                "CFBundleShortVersionString": version,
                "CFBundleVersion": "1",
                "LSMinimumSystemVersion": "13.0",
                "LSApplicationCategoryType": "public.app-category.games",
                "NSHighResolutionCapable": True,
                "NSPrincipalClass": "NSApplication",
            }, stream)
        run(["/usr/bin/xcrun", "swiftc", "-swift-version", "5", "-parse-as-library", "-O",
             "-target", "arm64-apple-macos13.0", "-framework", "SwiftUI", "-framework", "AppKit",
             HERE / "App.swift", "-o", executable], env=environment)
        source_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        provenance = {"version": version, "architecture": "arm64", "minimum_macos": "13.0",
            "source_commit": source_commit, "server_data_sha256": digest(server_data),
            "source_sha256": {name: digest(HERE / name) for name in ("App.swift", "engine.py", "payload.py")},
            "python": platform.python_version(),
            "pyinstaller": importlib.metadata.version("PyInstaller"),
            "signature": "ad-hoc", "notarized": False,
            "user_python_required": False, "user_terminal_required": False,
            "game_client_tested": False}
        write_json(resources / "bundle-provenance.json", provenance)
        run(["/usr/bin/codesign", "--force", "--deep", "--sign", "-", output])
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
                env=runtime_environment, timeout=90)
            engine_report = json.loads((evidence / "engine-smoke.json").read_text())
            if engine_report.get("frozen_runtime") is not True:
                raise ValueError("The bundled engine did not use its frozen Python runtime")
            moved = temporary / "이동한 앱" / "IdolyPride Local Server.app"
            moved.parent.mkdir()
            shutil.copytree(output, moved, symlinks=True)
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
    parser.add_argument("--version", default="0.2.5")
    parser.add_argument("--skip-smoke", action="store_true", help="Development only; release builds must run smoke checks")
    args = parser.parse_args(argv)
    try:
        build(args.server_data.resolve(), args.output.resolve(), args.archive.resolve(),
              args.evidence.resolve(), args.version, not args.skip_smoke)
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        parser.exit(1, f"macOS app build failed: {error}\n")
    print(args.archive)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
