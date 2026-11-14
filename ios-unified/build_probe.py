#!/usr/bin/env python3
"""Build a real Simulator-only UIKit startup probe from a staged runtime app.

No original game or existing Simulator is used. The input remains unchanged.
Linux may validate paths/Mach-O inputs; Apple compilation/signing needs Xcode.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import plistlib
import shutil
import subprocess
import sys

from packaging_common import audit_frameworks, audit_macho, regular, require, safe_name, sha_file, stamp, stream_copy

HERE = Path(__file__).resolve().parent
BUNDLE_ID = "game.qualiarts.idolypride.iosprobe"
EXECUTABLE = "IdolyEmbeddedProbe"
LAYOUT = ("Frameworks", "python-stdlib", "LocalServer")
MAX_TOTAL = 1024 * 1024**2
MAX_FILE = 256 * 1024**2
MAX_FILES = 30000


def host_architecture(value=None):
    value = platform.machine() if value is None else value
    value = {"aarch64": "arm64", "AMD64": "x86_64"}.get(value, value)
    require(value in ("arm64", "x86_64"), "Simulator probe requires arm64 or x86_64")
    return value


def collect_layout(prepared):
    prepared = Path(prepared)
    require(prepared.is_absolute() and prepared.is_dir() and not prepared.is_symlink(),
            "Absolute real prepared app directory required")
    files = []
    total = 0
    for name in LAYOUT:
        base = prepared / name
        require(base.is_dir() and not base.is_symlink(), "Prepared Simulator runtime layout missing")
        for root, directories, names in os.walk(base, followlinks=False):
            for directory in directories:
                require(not (Path(root) / directory).is_symlink(), "Prepared runtime cannot contain directory links")
            for filename in sorted(names):
                source = Path(root) / filename
                relative = source.relative_to(prepared).as_posix()
                safe_name(relative)
                info = regular(source)
                require(info.st_size <= MAX_FILE, "Prepared runtime member exceeds bound")
                total += info.st_size
                require(total <= MAX_TOTAL and len(files) < MAX_FILES, "Prepared runtime exceeds its bound")
                files.append((relative, source, info))
    names = {row[0] for row in files}
    require("LocalServer/ServerData.zip" in names and "LocalServer/bundledTranslations.zip" in names
            and "LocalServer/bundledTranslations.json" in names
            and "LocalServer/python/idoly_local/ios_host.py" in names,
            "Prepared public payload, translations or Python host missing")
    return sorted(files), total


def validate_inputs(prepared, output, arch):
    prepared, output = Path(prepared), Path(output)
    require(arch in ("arm64", "x86_64"), "Invalid Simulator architecture")
    require(output.is_absolute() and output.suffix == ".app" and not output.exists() and not output.is_symlink(),
            "Fresh absolute .app output required")
    input_location, output_location = prepared.resolve(strict=True), output.resolve(strict=False)
    require(not output_location.is_relative_to(input_location) and not input_location.is_relative_to(output_location),
            "Prepared input and probe output must be separate")
    files, total = collect_layout(prepared)
    # The freshly compiled Embedded framework is deliberately unsigned staging;
    # every copied framework and the completed app are signed below.
    frameworks = audit_frameworks(prepared / "Frameworks", "simulator", require_signature=False)
    require("IdolyEmbeddedServer" in frameworks, "Embedded server framework missing")
    require(all(any(row["architecture"] == arch for row in report["slices"])
                for report in frameworks.values()), "Prepared framework lacks host Simulator architecture")
    return files, total, frameworks


def clang_command(compiler, sdk, output, arch):
    return [str(compiler), "-target", arch + "-apple-ios13.0-simulator", "-isysroot", str(sdk),
            "-fobjc-arc", "-fblocks", "-O2", "-Wall", "-Wextra", "-Werror",
            "-Wno-deprecated-declarations", "-I", str(HERE / "native"),
            "-F", str(Path(output) / "Frameworks"), "-framework", "IdolyEmbeddedServer",
            "-framework", "Foundation", "-framework", "UIKit", "-Wl,-headerpad_max_install_names",
            "-Wl,-rpath,@executable_path/Frameworks", str(HERE / "probe/main.m"),
            "-o", str(Path(output) / EXECUTABLE)]


def info_plist():
    return {"CFBundleIdentifier": BUNDLE_ID, "CFBundleExecutable": EXECUTABLE,
            "CFBundleName": "Idoly Embedded Probe", "CFBundleDisplayName": "Idoly Embedded Probe",
            "CFBundlePackageType": "APPL", "CFBundleVersion": "1", "CFBundleShortVersionString": "1.0",
            "CFBundleSupportedPlatforms": ["iPhoneSimulator"], "MinimumOSVersion": "13.0",
            "LSRequiresIPhoneOS": True, "UIDeviceFamily": [1, 2], "UILaunchScreen": {},
            "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True}}


def build(prepared, output, *, arch, report_path=None):
    require(sys.platform == "darwin", "Actual Simulator probe compilation requires macOS/Xcode")
    files, total, framework_inputs = validate_inputs(prepared, output, arch)
    output = Path(output)
    report_path = Path(report_path) if report_path else output.with_suffix(".build.json")
    require(report_path.is_absolute() and not report_path.exists() and not report_path.is_symlink()
            and not report_path.resolve(strict=False).is_relative_to(output.resolve(strict=False))
            and not report_path.resolve(strict=False).is_relative_to(Path(prepared).resolve(strict=True)),
            "Fresh separate absolute report required")
    xcrun, codesign = shutil.which("xcrun"), shutil.which("codesign")
    require(xcrun and codesign, "Xcode xcrun and codesign are required")
    sdk = subprocess.check_output([xcrun, "--sdk", "iphonesimulator", "--show-sdk-path"], text=True).strip()
    compiler = subprocess.check_output([xcrun, "--sdk", "iphonesimulator", "--find", "clang"], text=True).strip()
    require(Path(sdk).is_dir() and Path(compiler).is_file(), "Simulator SDK/compiler unavailable")
    source_inputs = [HERE / "probe/main.m", HERE / "native/IdolyEmbeddedServer.h", Path(__file__).resolve()]
    source_pins = {str(path.relative_to(HERE)): sha_file(path) for path in source_inputs}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir(mode=0o700)
    try:
        copied = {}
        for relative, source, before in files:
            target = output / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            require(stamp(regular(source)) == stamp(before), "Prepared input changed before copying")
            descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
            with os.fdopen(descriptor, "rb") as incoming, target.open("xb") as outgoing:
                require(stamp(os.fstat(incoming.fileno())) == stamp(before), "Prepared input changed while opening")
                copied[relative] = stream_copy(incoming, outgoing, before.st_size)
            require(stamp(regular(source)) == stamp(before), "Prepared input changed while copying")
            target.chmod(0o755 if before.st_mode & 0o111 else 0o644)
        with (output / "Info.plist").open("xb") as stream:
            plistlib.dump(info_plist(), stream, fmt=plistlib.FMT_BINARY)
        command = clang_command(compiler, sdk, output, arch)
        subprocess.run(command, check=True)
        for framework in sorted((output / "Frameworks").glob("*.framework")):
            subprocess.run([codesign, "--force", "--sign", "-", "--timestamp=none", str(framework)], check=True)
        subprocess.run([codesign, "--force", "--sign", "-", "--timestamp=none", str(output)], check=True)
        subprocess.run([codesign, "--verify", "--strict", "--deep", str(output)], check=True)
        executable = audit_macho(output / EXECUTABLE, "simulator", require_signature=True)
        require([row["architecture"] for row in executable["slices"]] == [arch], "Probe architecture differs")
        framework_outputs = audit_frameworks(output / "Frameworks", "simulator", require_signature=True)
        require(source_pins == {str(path.relative_to(HERE)): sha_file(path) for path in source_inputs},
                "Probe source changed during compilation")
        result = {"schema": 1, "status": "BUILT_REAL_SIMULATOR_APP_REQUIRES_SMOKE_RUN",
                  "bundle_id": BUNDLE_ID, "architecture": arch, "prepared_bytes": total,
                  "source_sha256": source_pins, "copied_input_sha256": copied,
                  "framework_inputs": framework_inputs, "framework_outputs": framework_outputs,
                  "executable": executable, "clang_command": command,
                  "original_game_used_or_modified": False, "phone_or_PlayCover_gameplay_verified": False}
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with report_path.open("x") as stream:
            json.dump(result, stream, indent=2); stream.write("\n")
    except BaseException:
        # Only this invocation's newly created output is removed on failure.
        shutil.rmtree(output)
        raise
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared-app", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--arch", choices=("arm64", "x86_64"))
    parser.add_argument("--report", type=Path)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args(argv)
    arch = args.arch or host_architecture()
    if args.validate_only:
        files, total, frameworks = validate_inputs(args.prepared_app, args.output, arch)
        print(json.dumps({"status": "INPUTS_VALIDATED_NO_APPLE_BUILD", "files": len(files),
                          "bytes": total, "architecture": arch, "framework_count": len(frameworks)}))
        return
    result = build(args.prepared_app, args.output, arch=arch, report_path=args.report)
    print(json.dumps({"status": result["status"], "bundle_id": BUNDLE_ID, "app": str(args.output)}))


if __name__ == "__main__":
    main()
