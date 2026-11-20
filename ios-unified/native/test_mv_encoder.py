#!/usr/bin/env python3
"""Compile real Apple targets and independently decode two synthetic MP4 jobs.

Requires Xcode on macOS. This never claims actual Idoly MV rendering or device
runtime coverage: device/Simulator are compiled, the codec proof runs on macOS.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import time


FRAMEWORKS = ("Foundation", "AVFoundation", "AudioToolbox", "CoreMedia", "CoreVideo", "VideoToolbox")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command_output(command: list[str], *, timeout: int = 30) -> str:
    return subprocess.check_output(command, text=True, timeout=timeout).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-directory", type=Path, required=True, help="Fresh private directory for proof artifacts")
    args = parser.parse_args()
    xcrun = shutil.which("xcrun")
    if platform.system() != "Darwin" or not xcrun:
        parser.error("An actual macOS host with Xcode SDKs is required; Linux stubs cannot prove codecs")
    directory = args.output_directory.absolute()
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    os.chmod(directory, 0o700)
    here = Path(__file__).resolve().parent
    sources = (here / "IdolyMVEncoder.mm", here / "IdolyMVEncoderPolicy.h",
               here.parent.parent / "client-presentation/native/mp4_encoder_api.h",
               here / "tests/MVEncoderIntegration.mm", Path(__file__).resolve())
    hashes = {str(path.relative_to(here.parent.parent)): sha(path) for path in sources}
    common = ["-fobjc-arc", "-fblocks", "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror",
              "-Wno-deprecated-declarations", "-Wno-missing-field-initializers"]
    commands: list[list[str]] = []
    started = time.monotonic()
    architecture = "arm64" if platform.machine() == "arm64" else "x86_64"
    for sdk, target, name in (
        ("iphoneos", "arm64-apple-ios13.0", "device"),
        ("iphonesimulator", f"{architecture}-apple-ios13.0-simulator", "simulator"),
    ):
        compiler = command_output([xcrun, "--sdk", sdk, "--find", "clang++"])
        sdk_path = command_output([xcrun, "--sdk", sdk, "--show-sdk-path"])
        command = [compiler, "-target", target, "-isysroot", sdk_path, *common,
                   "-c", str(here / "IdolyMVEncoder.mm"), "-o", str(directory / f"{name}.o")]
        subprocess.run(command, check=True, timeout=90)
        commands.append(command)
    compiler = command_output([xcrun, "--sdk", "macosx", "--find", "clang++"])
    sdk_path = command_output([xcrun, "--sdk", "macosx", "--show-sdk-path"])
    executable = directory / "encoder-integration"
    command = [compiler, "-target", f"{architecture}-apple-macos11.0", "-isysroot", sdk_path,
               *common, "-DIDMV_ENCODER_DIAGNOSTICS=1", str(here / "IdolyMVEncoder.mm"), str(here / "tests/MVEncoderIntegration.mm")]
    for framework in FRAMEWORKS:
        command.extend(("-framework", framework))
    command.extend(("-o", str(executable)))
    subprocess.run(command, check=True, timeout=90)
    commands.append(command)
    result = subprocess.run([str(executable), str(directory)], check=False, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=240)
    (directory / "integration.stdout.txt").write_text(result.stdout, encoding="utf-8")
    (directory / "integration.stderr.txt").write_text(result.stderr, encoding="utf-8")
    report = {
        "schema": 1,
        "status": "PASS_SYNTHETIC_CODEC_ONLY" if result.returncode == 0 else "FAILED",
        "compiled_targets": ["arm64-apple-ios13.0", f"{architecture}-apple-ios13.0-simulator"],
        "runtime_target": f"{architecture}-apple-macos11.0",
        "independent_decoder": "AVAssetReader video + float32 AAC output",
        "actual_game_mv_verified": False,
        "actual_ios_device_runtime_verified": False,
        "codecs_required": ["h264", "hevc"],
        "commands": commands,
        "source_sha256": hashes,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "mp4_sha256": {path.name: sha(path) for path in sorted(directory.glob("*.mp4"))},
    }
    if hashes != {str(path.relative_to(here.parent.parent)): sha(path) for path in sources}:
        report["status"] = "FAILED_SOURCE_CHANGED"
    (directory / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    if report["status"] != "PASS_SYNTHETIC_CODEC_ONLY":
        raise SystemExit(result.returncode or 1)


if __name__ == "__main__":
    main()
