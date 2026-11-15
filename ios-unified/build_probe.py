#!/usr/bin/env python3
"""Build a real Simulator-only UIKit startup probe from a staged runtime app.

No original game or existing Simulator is used. The input remains unchanged.
Linux may validate paths/Mach-O inputs; Apple compilation/signing needs Xcode.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import plistlib
import shutil
import subprocess
import sys
from zipfile import ZipFile

from packaging_common import audit_frameworks, audit_macho, regular, require, safe_name, sha_file, stamp, stream_copy

HERE = Path(__file__).resolve().parent
BUNDLE_ID = "game.qualiarts.idolypride.iosprobe"
EXECUTABLE = "IdolyEmbeddedProbe"
LAYOUT = ("Frameworks", "python-stdlib", "LocalServer", "Data")
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
        if name == "Data" and not base.exists() and not base.is_symlink():
            require(not (prepared / "LocalServer/client-languages.zip").exists()
                    and not (prepared / "LocalServer/client-languages.json").exists(),
                    "Client-language probe requires the original nonexecutable Data tree")
            continue  # Legacy synthetic core-only fixtures have no game Data.
        require(base.is_dir() and not base.is_symlink(), "Prepared Simulator runtime layout missing")
        for root, directories, names in os.walk(base, followlinks=False):
            for directory in directories:
                require(not (Path(root) / directory).is_symlink(), "Prepared runtime cannot contain directory links")
            for filename in sorted(names):
                source = Path(root) / filename
                relative = source.relative_to(prepared).as_posix()
                safe_name(relative)
                info = regular(source)
                if name == "Data": require(not info.st_mode & 0o111, "Probe Data must be nonexecutable")
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
            "-DIDOLY_SMOKE_SIMULATOR=1",
            "-Wno-deprecated-declarations", "-I", str(HERE / "native"),
            "-F", str(Path(output) / "Frameworks"), "-framework", "IdolyEmbeddedServer",
            "-framework", "Foundation", "-framework", "UIKit", "-framework", "WebKit",
            "-framework", "CoreGraphics", "-Wl,-headerpad_max_install_names",
            "-Wl,-rpath,@executable_path/Frameworks", str(HERE / "probe/main.m"),
            "-o", str(Path(output) / EXECUTABLE)]


def info_plist():
    return {"CFBundleIdentifier": BUNDLE_ID, "CFBundleExecutable": EXECUTABLE,
            "CFBundleName": "Idoly Embedded Probe", "CFBundleDisplayName": "Idoly Embedded Probe",
            "CFBundlePackageType": "APPL", "CFBundleVersion": "1", "CFBundleShortVersionString": "1.0",
            "CFBundleSupportedPlatforms": ["iPhoneSimulator"], "MinimumOSVersion": "13.0",
            "LSRequiresIPhoneOS": True, "UIDeviceFamily": [1, 2], "UILaunchScreen": {},
            "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
            "IdolyUnifiedLoopbackOrigin": "http://127.0.0.1:8080"}


def derive_language_canaries(app, copied):
    """Derive smoke-only expectations without changing any signed Data/ZIP."""
    app = Path(app)
    package = app / "LocalServer/client-languages.zip"
    if not package.exists():
        return None  # Portable legacy staging fixtures do not execute this probe.
    descriptor = app / "LocalServer/client-languages.json"
    require(regular(descriptor).st_size <= 256 * 1024, "Language descriptor exceeds bound")
    pin = json.loads(descriptor.read_bytes())
    require(pin.get("schema") == 1 and pin.get("sha256") == copied.get("LocalServer/client-languages.zip")
            and pin.get("bytes") == regular(package).st_size, "Language package copy pin differs")
    spec = importlib.util.spec_from_file_location("idoly_probe_client_data", HERE.parent / "src/idoly_local/ios_client_data.py")
    validator = importlib.util.module_from_spec(spec); spec.loader.exec_module(validator)
    with ZipFile(package) as archive:
        info = archive.getinfo("manifest.json")
        require(0 < info.file_size <= validator.MAX_MANIFEST, "Language manifest exceeds bound")
        raw = archive.read(info)
        manifest = validator.validate_manifest(json.loads(raw))
    with ZipFile(app / "LocalServer/ServerData.zip") as archive:
        info = archive.getinfo("data/protocol/idolypride-6.1.1.pb")
        require(0 < info.file_size <= 16 * 1024 * 1024, "Protocol descriptor exceeds bound")
        protocol_sha = hashlib.sha256(archive.read(info)).hexdigest()
    paths = ("Data/resources.assets", "Data/Managed/Metadata/global-metadata.dat")
    return {"schema":1,"bundle_id":"local.idoly.client-data", "client_archive_sha256":pin["sha256"],
        "client_manifest_sha256":hashlib.sha256(raw).hexdigest(),"descriptor_sha256":protocol_sha,
        "languages":{language:{name:{"bytes":manifest["languages"][language][name]["bytes"],
            "sha256":manifest["languages"][language][name]["sha256"]} for name in paths}
            for language in ("ko","en","ja")}}


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
    source_inputs = [HERE / "probe/main.m", HERE / "native/IdolyEmbeddedServer.h",
                     HERE / "native/IdolyOctoBudget.h", HERE / "native/IdolyUnityHost.h", HERE / "native/OctoBudgetPolicy.h",
                     HERE / "native/tests/OctoBudgetFixture.h", Path(__file__).resolve()]
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
        canaries = derive_language_canaries(output, copied)
        canary_sha = None
        if canaries is not None:
            encoded = (json.dumps(canaries, sort_keys=True, separators=(",", ":")) + "\n").encode()
            require(len(encoded) <= 65536, "Derived language canaries exceed bound")
            with (output / "probe-language-canaries.json").open("xb") as stream:
                stream.write(encoded)
            canary_sha = hashlib.sha256(encoded).hexdigest()
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
                  "original_game_executable_used_or_modified": False,
                  "original_game_Data_copied_as_nonexecutable": any(name.startswith("Data/") for name in copied),
                  "phone_or_PlayCover_gameplay_verified": False,
                  "generated_language_canaries_sha256": canary_sha}
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
