#!/usr/bin/env python3
"""Check the real UIKit MP4 interface for iOS and Simulator, without fake SDKs.

This is compilation evidence only; no game scene or Files provider is exercised.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess


def main() -> None:
    xcrun = shutil.which("xcrun")
    if platform.system() != "Darwin" or not xcrun:
        raise SystemExit("Actual macOS Xcode SDKs required for UIKit compilation")
    here = Path(__file__).resolve().parent
    paths = [here / name for name in ("IdolyMP4UI.m", "IdolyMP4UI.h", "IdolySettings.m",
                                     "IdolyEmbeddedServer.h", "IdolyNativeUI.h", "MP4FinalizationPolicy.h",
                                     "IdolyMP4Library.h", "IdolyMP4Library.m", "MP4CompletedFilePolicy.h")]
    source_hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    architecture = "arm64" if platform.machine() == "arm64" else "x86_64"
    commands = []
    for sdk, target in (("iphoneos", "arm64-apple-ios13.0"),
                        ("iphonesimulator", architecture + "-apple-ios13.0-simulator")):
        compiler = subprocess.check_output([xcrun, "--sdk", sdk, "--find", "clang"], text=True).strip()
        sdk_path = subprocess.check_output([xcrun, "--sdk", sdk, "--show-sdk-path"], text=True).strip()
        command = [compiler, "-target", target, "-isysroot", sdk_path, "-fobjc-arc", "-fblocks",
                   "-Wall", "-Wextra", "-Werror", "-Wno-deprecated-declarations",
                   "-Wno-missing-field-initializers", "-fsyntax-only", str(here / "IdolyMP4UI.m"),
                   str(here / "IdolySettings.m"),str(here / "IdolyMP4Library.m")]
        subprocess.run(command, check=True, timeout=90); commands.append(command)
    if source_hashes != {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}:
        raise SystemExit("UIKit sources changed during compilation")
    print(json.dumps({"schema":1,"status":"PASS_APPLE_UIKIT_COMPILE_ONLY", "commands":commands,
                      "source_sha256":source_hashes,"actual_game_mv_verified":False,
                      "actual_files_provider_verified":False}, indent=2))


if __name__ == "__main__":
    main()
