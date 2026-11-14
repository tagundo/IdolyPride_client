#!/usr/bin/env python3
"""Build a device IPA and independently execute its core in a fresh Simulator."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys

HERE = Path(__file__).resolve().parent


def run(*args):
    subprocess.run(list(map(str, args)), check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    if sys.platform != "darwin" or not re.fullmatch("[0-9a-f]{40}", args.source_commit):
        raise ValueError("Real macOS Xcode host and exact source commit required")
    inputs, work, output = (p.absolute() for p in (args.inputs, args.work, args.output))
    if not inputs.is_dir() or work.exists() or output.exists():
        raise ValueError("Existing verified inputs and fresh owned output directories required")
    work.mkdir(parents=True)
    output.mkdir(parents=True)
    python = sys.executable
    native = HERE / "native/build_native.py"
    support = inputs / "Python-3.13-iOS-support.b18.tar.gz"
    env = {"schema": 1, "source_commit": args.source_commit, "host_arch": platform.machine(),
           "xcode": subprocess.check_output(["xcodebuild", "-version"], text=True),
           "server_runs_in_process": True, "actual_phone_or_PlayCover_execution": False}
    (output / "build-environment.json").write_text(json.dumps(env, indent=2) + "\n")

    def prepare(target, architecture):
        runtime = work / (target + "-runtime")
        run(python, "-B", HERE / "prepare_runtime.py", "--support", support,
            "--wheel-dir", inputs / "wheels", "--output", runtime,
            "--target", target, "--architecture", architecture, "--project-root", HERE.parent)
        return runtime

    def compile_native(runtime, target, architecture):
        framework = work / target / "IdolyEmbeddedServer.framework"
        framework.parent.mkdir()
        flags = (["--smoke-simulator"] if target == "simulator" else
                 ["--presentation-library", inputs / "IdolyPresentation.dylib"])
        run(python, "-B", native, "--sdk", "iphonesimulator" if target == "simulator" else "iphoneos",
            "--arch", architecture, "--python-framework", runtime / "Frameworks/Python.framework",
            "--output", framework, *flags)
        run("/usr/bin/codesign", "--force", "--sign", "-", "--timestamp=none", framework)
        run("/usr/bin/codesign", "--verify", "--strict", framework)
        report = json.loads(framework.with_suffix(".build.json").read_text())
        binary = framework / "IdolyEmbeddedServer"
        report["post_sign_binary_sha256"] = hashlib.sha256(binary.read_bytes()).hexdigest()
        report["post_sign_binary_bytes"] = binary.stat().st_size
        report["codesign_strict_verified"] = True
        (output / (target + "-native-build.json")).write_text(json.dumps(report, indent=2) + "\n")
        (output / (target + "-runtime-report.json")).write_bytes((runtime / "runtime-report.json").read_bytes())
        return framework

    runtime = prepare("device", "arm64")
    framework = compile_native(runtime, "device", "arm64")
    unity = work / "UnityFramework"
    run(python, "-B", HERE / "patch_load.py", "--source-ipa", inputs / "base.ipa", "--output", unity)
    ipa = output / "IdolyPride-6.1.1-Unified-iOS-ko.ipa"
    common = ["--server-data", inputs / "ServerData.zip", "--translations", inputs / "bundledTranslations.zip"]
    run(python, "-B", HERE / "package_unified.py", "--runtime-root", runtime,
        "--native-framework", framework, *common, "--output", ipa,
        "--base-ipa", inputs / "base.ipa", "--patched-unity", unity, "--source-commit", args.source_commit)
    (output / "Unity-load-patch.json").write_bytes(unity.with_suffix(".json").read_bytes())

    arch = {"aarch64": "arm64"}.get(platform.machine(), platform.machine())
    if arch not in ("arm64", "x86_64"):
        raise ValueError("Unsupported real Simulator host architecture")
    simruntime = prepare("simulator", arch)
    simframework = compile_native(simruntime, "simulator", arch)
    prepared, probe = work / "Prepared.app", work / "Probe.app"
    run(python, "-B", HERE / "package_unified.py", "--stage-only", "--target", "simulator",
        "--runtime-root", simruntime, "--native-framework", simframework, *common, "--output", prepared)
    run(python, "-B", HERE / "build_probe.py", "--prepared-app", prepared, "--output", probe, "--arch", arch)
    run(python, "-B", HERE / "probe/smoke_probe.py", "--app", probe, "--audit", output / "simulator-smoke.json")
    # The device artifact and the disposable Simulator probe are deliberately
    # separate: a successful core probe does not imply physical game playback.
    digest = hashlib.sha256()
    with ipa.open("rb") as source:
        for block in iter(lambda: source.read(128 * 1024), b""):
            digest.update(block)
    (output / "SHA256SUMS").write_text(digest.hexdigest() + "  " + ipa.name + "\n")
    (output / "README.txt").write_text(
        "IdolyPride integrated iPhone/iPad IPA (prototype)\n"
        "Sign this IPA with your iOS sideloading method before installing.\n"
        "The local server starts inside the game; no separate server app is needed.\n"
        "Hold three fingers on the game for one second to open server settings.\n"
        "Resource files: Files > On My iPhone/iPad > 아이프라 로컬 > IdolyPride.\n"
        "The real iOS server framework compiled and a disposable Simulator core probe passed.\n"
        "Physical iPhone/iPad game playback and PlayCover execution remain unverified.\n"
        "The Simulator probe is excluded from the device IPA.\n"
    )
    print("PASS_DEVICE_IPA_BUILD_AND_SIMULATOR_CORE_PROBE")


if __name__ == "__main__":
    main()
