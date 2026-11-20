#!/usr/bin/env python3
"""Build a device IPA and independently execute its core in a fresh Simulator."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
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


PACKAGED_SERVER_DATA = {"pin":"../data/latest-server-data-pin.json","policy":"latest-cohort-overlay-v1"}


def _tool_module(name):
    spec=importlib.util.spec_from_file_location("ios_ci_"+name,HERE.parent/"tools"/(name+".py"))
    module=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=module
    spec.loader.exec_module(module)
    return module


def prepare_server_data(inputs, work, output):
    """Upgrade the exact verified base, then require the independent static pin."""
    manifest=json.loads((HERE/"runtime_inputs.json").read_text())
    if manifest.get("packaged_server_data")!=PACKAGED_SERVER_DATA:
        raise ValueError("Pinned upgraded server data is required")
    verifier=_tool_module("latest_server_data_pin")
    if manifest["inputs"]["server_data"]!=verifier.base_pin():
        raise ValueError("Server data base pin differs")
    wanted=verifier.output_pin()  # Missing/unverified static pins never fall back.
    upgraded=work/"upgraded-ServerData.zip"
    proof_path=output/"server-data-upgrade.json"
    upgrader=_tool_module("prepare_latest_server_data")
    verifier.verify_source_pointer()
    overlay=work/"latest-server-overlay.zip"
    fetched=verifier.fetch_overlay(overlay)
    if {key:fetched[key] for key in ("bytes","sha256")}!=wanted:
        raise ValueError("Fetched server data source pin differs")
    verifier.verify_overlay(overlay)
    proof=upgrader.upgrade_server_data(inputs/"ServerData.zip",upgraded,report_path=proof_path,overlay_zip=overlay)
    verifier.verify_upgrade_proof(proof)
    verified=verifier.verify_payload(upgraded)
    if {key:verified[key] for key in ("bytes","sha256")}!=wanted:
        raise ValueError("Upgraded server data output pin differs")
    return upgraded,proof_path


def compatible_runtime(sdk, catalog):
    def version(value):
        if not isinstance(value, str) or not re.fullmatch(r"\d+(?:\.\d+){0,2}", value):
            raise ValueError("Invalid iOS SDK/runtime version")
        parts = tuple(map(int, value.split(".")))
        return parts + (0,) * (3 - len(parts))
    maximum = version(sdk)
    available = [r for r in catalog.get("runtimes", []) if isinstance(r, dict)
                 and r.get("isAvailable") is True
                 and str(r.get("identifier", "")).startswith("com.apple.CoreSimulator.SimRuntime.iOS-")
                 and version(r.get("version")) <= maximum]
    if not available:
        raise ValueError("Install an available iOS Simulator runtime compatible with the selected Xcode SDK")
    return max(available, key=lambda r: version(r["version"]))["identifier"]


def prepare_presentation_bridge(inputs, work, output):
    """Build this checkout's bridge and stock-derived static gateway plan."""
    from idoly_local.ios_presentation import prepare_presentation
    from presentation_candidate import validate_library
    folder = work / "presentation"
    folder.mkdir()
    plan, header = folder / "hook-plan.json", folder / "ios_profile.hpp"
    prepared = prepare_presentation(inputs / "stock.ipa", plan, header)
    clang = subprocess.check_output(["xcrun", "--sdk", "iphoneos", "--find", "clang++"], text=True).strip()
    linker = subprocess.check_output(["xcrun", "--sdk", "iphoneos", "--find", "ld"], text=True).strip()
    library = folder / "IdolyPresentation.dylib"
    run(sys.executable, "-B", HERE.parent / "client-presentation/ios/build_native.py",
        "--clang", clang, "--linker", linker, "--profile-header", header, "--output", library)
    verified = validate_library(library, prepared)
    (output / "presentation-native-build.json").write_bytes(library.with_suffix(".build.json").read_bytes())
    (output / "presentation-hook-plan.json").write_bytes(plan.read_bytes())
    (output / "presentation-verification.json").write_text(json.dumps(verified, indent=2) + "\n")
    return library, plan


def candidate_filename(source_commit):
    if not re.fullmatch("[0-9a-f]{40}", source_commit):
        raise ValueError("Exact candidate source commit required")
    date = subprocess.check_output(["git", "-C", str(HERE.parent), "show", "-s", "--format=%cs", source_commit],
                                   text=True).strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise ValueError("Candidate source date is invalid")
    return "IdolyPride-Unified-" + date.replace("-", ".") + "-prototype-" + source_commit[:12] + "-iOS.ipa"


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
    server_data,server_data_proof=prepare_server_data(inputs,work,output)
    runtime_inputs=json.loads((HERE/"runtime_inputs.json").read_text())
    payload_pin=_tool_module("latest_server_data_pin").output_pin()
    translation_pin=runtime_inputs["inputs"]["translations"]
    startup_translations=work/"startupTranslations.zip"
    startup_descriptor=work/"startupTranslations.json"
    run(python,"-B",HERE.parent/"tools/build_startup_translation_receipt.py",
        "--payload",server_data,"--payload-sha256",payload_pin["sha256"],"--payload-bytes",payload_pin["bytes"],
        "--translations",inputs/"bundledTranslations.zip","--translations-sha256",translation_pin["sha256"],
        "--translations-bytes",translation_pin["bytes"],"--platform","ios",
        "--output",startup_translations,"--receipt",startup_descriptor)
    (output/"startupTranslations.json").write_bytes(startup_descriptor.read_bytes())
    native = HERE / "native/build_native.py"
    support = inputs / "Python-3.13-iOS-support.b18.tar.gz"
    env = {"schema": 1, "source_commit": args.source_commit, "host_arch": platform.machine(),
           "xcode": subprocess.check_output(["xcodebuild", "-version"], text=True),
           "server_runs_in_process": True, "actual_phone_or_PlayCover_execution": False}
    sdk = subprocess.check_output(["xcrun", "--sdk", "iphonesimulator", "--show-sdk-version"], text=True).strip()
    raw_catalog = subprocess.check_output(["xcrun", "simctl", "list", "runtimes", "--json"])
    if len(raw_catalog) > 2 * 1024**2:
        raise ValueError("Simulator runtime catalog exceeds bound")
    selected_runtime = compatible_runtime(sdk, json.loads(raw_catalog))
    env.update(simulator_sdk=sdk, selected_simulator_runtime=selected_runtime)
    (output / "build-environment.json").write_text(json.dumps(env, indent=2) + "\n")
    run(python, "-B", HERE / "native/test_mac_menu.py", "--report", output / "mac-menu-test.json")
    run(python, "-B", HERE / "native/test_client_data.py", "--report", output / "client-data-native-test.json")
    run(python, "-B", HERE / "native/test_keyboard_lifecycle.py", "--report", output / "keyboard-lifecycle-native-test.json")
    run(python, "-B", HERE / "native/test_local_http.py", "--report", output / "local-http-native-test.json")
    run(python, "-B", HERE / "native/test_octo_budget.py", "--report", output / "octo-budget-native-test.json")
    run(python, "-B", HERE / "native/test_unity_host.py", "--report", output / "unity-host-native-test.json")
    korean_images = work / "ko-images"
    run(python, "-B", HERE.parent / "tools/fetch_korean_ui_images.py",
        "--output", korean_images, "--report", output / "korean-image-inputs.json")
    client_languages = work / "client-languages.zip"
    run(python, "-B", HERE.parent / "tools/build_ios_client_languages.py",
        "--stock-ipa", inputs / "stock.ipa", "--base-ipa", inputs / "base.ipa",
        "--english-csv", inputs / "en.csv", "--english-proof", inputs / "en-report.json",
        "--image-dir", korean_images,
        "--output", client_languages, "--report", output / "client-languages-build.json")
    client_descriptor = client_languages.with_suffix(".json")
    (output / "client-languages.json").write_bytes(client_descriptor.read_bytes())
    presentation_library, presentation_plan = prepare_presentation_bridge(inputs, work, output)

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
                 ["--presentation-library", presentation_library])
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
    from presentation_candidate import compose
    compose(inputs / "stock.ipa", presentation_plan, unity)
    ipa = output / candidate_filename(args.source_commit)
    common = ["--server-data", server_data, "--server-data-upgrade-proof", server_data_proof,
              "--translations", inputs / "bundledTranslations.zip",
              "--client-languages", client_languages, "--client-languages-metadata", client_descriptor,
              "--startup-translations",startup_translations,"--startup-translations-metadata",startup_descriptor]
    run(python, "-B", HERE / "package_unified.py", "--runtime-root", runtime,
        "--native-framework", framework, *common, "--output", ipa,
        "--base-ipa", inputs / "base.ipa", "--patched-unity", unity, "--source-commit", args.source_commit,
        "--stock-ipa", inputs / "stock.ipa", "--presentation-library", presentation_library,
        "--presentation-plan", presentation_plan)
    (output / "Unity-load-patch.json").write_bytes(unity.with_suffix(".json").read_bytes())

    arch = {"aarch64": "arm64"}.get(platform.machine(), platform.machine())
    if arch not in ("arm64", "x86_64"):
        raise ValueError("Unsupported real Simulator host architecture")
    simruntime = prepare("simulator", arch)
    simframework = compile_native(simruntime, "simulator", arch)
    prepared, probe = work / "Prepared.app", work / "Probe.app"
    run(python, "-B", HERE / "package_unified.py", "--stage-only", "--target", "simulator",
        "--runtime-root", simruntime, "--native-framework", simframework, *common,
        "--base-ipa", inputs / "base.ipa", "--output", prepared)
    run(python, "-B", HERE / "verify_client_languages.py", "--prepared-app", prepared,
        "--work", work / "client-language-check", "--report", output / "client-language-runtime-check.json")
    run(python, "-B", HERE / "build_probe.py", "--prepared-app", prepared, "--output", probe, "--arch", arch,
        "--report", output / "probe-build.json")
    # One deadline includes a cold Simulator boot/install and five full app
    # processes. Each launch and functional check retains its own smaller cap.
    run(python, "-B", HERE / "probe/smoke_probe.py", "--app", probe,
        "--runtime", selected_runtime, "--timeout", "900", "--audit", output / "simulator-smoke.json")
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
        "The app opens the server menu first. Start the server, choose the game language, then press 게임 시작.\n"
        "Japanese, Korean and English client Data is prepared before Unity starts; no per-frame text replacement.\n"
        "Unity initialization reuses a keyboard that was already created.\n"
        "Before game startup, the app checks its loopback HTTP endpoint with NSURLSession.\n"
        "The server menu adapts its native header to the window and supports copying diagnostics.\n"
        "Missing translations and untranslated images retain the original content.\n"
        "While playing, hold the upper-right corner for two seconds to reopen the server menu.\n"
        "Mac/PlayCover: app menu > 로컬 서버 설정… (Command+Shift+,).\n"
        "Resource files: Files > On My iPhone/iPad > 아이프라 로컬 > IdolyPride.\n"
        "The current-source bridge and static Unity gateways replace the older bridge in the translated base IPA.\n"
        "Shared resource reads use the verified server object store; device symlink and media playback validation is pending.\n"
        "The real iOS server framework compiled and a disposable Simulator core probe passed.\n"
        "Physical iPhone/iPad game playback and PlayCover execution remain unverified.\n"
        "The Simulator probe is excluded from the device IPA.\n"
    )
    print("PASS_DEVICE_IPA_BUILD_AND_SIMULATOR_CORE_PROBE")


if __name__ == "__main__":
    main()
