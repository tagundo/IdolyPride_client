#!/usr/bin/env python3
"""Observe the published local client unchanged against the current host core.

This is a local-bootstrap baseline, not an untouched-original baseline. It adds
no diagnostics, UI bridge, native hooks, software AES, store or graphics patch.
Only the exact Android-owned fullscreen onboarding hint may be acknowledged.
Fresh private server state and input archives remain outside uploaded artifacts.
"""
from __future__ import annotations

import argparse
from collections import Counter, deque
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import threading
import time
from zipfile import ZipFile

from run_original_android_baseline import (
    adb, command, decoded, dismiss_fullscreen_hint, dump_ui, fullscreen_hint,
    optional_adb, write_json,
)

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "game.qualiarts.idolypride.local"
APK_ASSET = 726978000
APK_SHA = "28ecc6a617867d0842a5e88eac3d5736199809a49d4d433ce47816d6a40ba77b"
APK_SIZE = 159483201
CERT_SHA = "86fbcf5674eb086f74a95756d68a8db52e203b418d3874b440ecabdf259d6a81"
PAYLOAD_ASSET = 730745727
PAYLOAD_SHA = "23c91e44c02e9326cb001410e70e437e8e2790218961094afc424672399a48e0"
PAYLOAD_SIZE = 80707080
METADATA = "assets/bin/Data/Managed/Metadata/global-metadata.dat"
PINNED_MEMBERS = {
    "lib/arm64-v8a/libil2cpp.so": "4517381b0dbeae559d79832797f0c57c78ba6f37cf7d3544a58d0f31f2b8def3",
    "lib/arm64-v8a/libFastAES.so": "f8f64ab5424b6f692464e23cf47af9d399c4072b700c196e7b321e670b93fcc4",
    METADATA: "681390058fdfbb1f54d3d0f09b9d66ad03312696e07caee4890d3cb1e1a898c0",
}
BOOTSTRAP_METHODS = {
    "SeedWrapper.IsInitialized", "SeedWrapper.SeedId", "SeedWrapper.InitializeAsync",
    "SeedWrapper.RefreshSeedIdAsync", "AccountManager.IsCreatedUser",
    "AccountManager.GetFirebaseIdTokenAsync",
}
PUBLIC_ROOTS = {"protocol", "original-master", "master-json", "public-fixtures", "public-tutorial", "public-story"}
REQUIRED_FILES = {
    "data/protocol/idolypride-6.1.1.pb", "data/original-master/master-tag.json",
    "data/public-fixtures/manifest.json", "data/public-tutorial/manifest.json",
    "data/public-tutorial/tutorial-short.pb", "data/public-tutorial/tutorial-full.pb",
    "data/public-story/manifest.json", "data/public-story/story-list-event.pb",
    "data/public-story/story-list-extra.pb", "data/master-json/!version.txt",
    *("data/master-json/" + name + ".json" for name in (
        "HierarchyDetailGrade", "HierarchyGrade", "Setting", "Tutorial", "Card",
        "ManagerLevel", "CardLevel", "Consumption", "Message", "MessageGroup",
        "EventStory", "ExtraStoryPart", "ExtraStory", "Story")),
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def file_digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_payload(payload: Path) -> dict:
    require(payload.stat().st_size == PAYLOAD_SIZE and file_digest(payload) == PAYLOAD_SHA,
            "Published v0.2.16 payload size or SHA-256 mismatch")
    with ZipFile(payload) as archive:
        require(archive.testzip() is None, "Published payload ZIP CRC failed")
        names = set()
        for item in archive.infolist():
            path = PurePosixPath(item.filename)
            require(not path.is_absolute() and ".." not in path.parts and "\\" not in item.filename
                    and "\x00" not in item.filename and path.parts and path.parts[0] == "data"
                    and str(path) == item.filename.rstrip("/")
                    and not stat.S_ISLNK(item.external_attr >> 16) and item.filename not in names,
                    "Published payload has an unsafe or duplicate ZIP path")
            if not item.is_dir():
                require((len(path.parts) >= 3 and path.parts[1] in PUBLIC_ROOTS)
                        or item.filename == "data/payload-manifest.json",
                        "Published payload contains a non-public file")
            names.add(item.filename)
        manifest = json.loads(archive.read("data/payload-manifest.json"))
        require(isinstance(manifest, dict) and manifest.get("schema") == 1,
                "Published payload has an unsupported manifest")
        records = manifest.get("files")
        require(isinstance(records, list) and all(isinstance(row, dict) for row in records),
                "Published payload file manifest is malformed")
        paths = [row.get("path") for row in records]
        require(all(isinstance(path, str) for path in paths) and len(set(paths)) == len(paths),
                "Published payload file manifest has duplicate or malformed paths")
        actual = {item.filename for item in archive.infolist() if not item.is_dir()}
        require(set(paths) | {"data/payload-manifest.json"} == actual,
                "Published payload manifest does not describe its exact file set")
        require(REQUIRED_FILES.issubset(actual), "Published payload lacks continuation tables or public fixtures")
        for row in records:
            content = archive.read(row["path"])
            require(type(row.get("bytes")) is int and len(content) == row["bytes"]
                    and hashlib.sha256(content).hexdigest() == row.get("sha256"),
                    "Published payload member size or SHA-256 mismatch")
    return {"asset_id": PAYLOAD_ASSET, "release": "local-server-v0.2.16", "bytes": PAYLOAD_SIZE,
            "sha256": PAYLOAD_SHA, "zip_crc_verified": True, "safe_paths_verified": True,
            "exact_manifest_verified": True, "public_files": len(records)}


def verify_apk(apk: Path, output: Path) -> dict:
    require(apk.stat().st_size == APK_SIZE and file_digest(apk) == APK_SHA,
            "Published normal local APK size or SHA-256 mismatch")
    build_tools = Path(os.environ["ANDROID_HOME"]) / "build-tools/35.0.0"
    signature = decoded(command([str(build_tools / "apksigner"), "verify", "--verbose", "--print-certs", str(apk)]))
    require(re.findall(r"Signer #\d+ certificate SHA-256 digest: ([0-9a-f]+)", signature) == [CERT_SHA],
            "Published normal local APK signing certificate mismatch")
    badging = decoded(command([str(build_tools / "aapt2"), "dump", "badging", str(apk)]))
    require("name='" + PACKAGE + "'" in badging.splitlines()[0]
            and "versionCode='414'" in badging.splitlines()[0], "Unexpected local package or version")
    with ZipFile(apk) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)), "Published local APK contains duplicate members")
        require(not any(name.startswith("assets/idoly-qa") or "libidoly_" in name for name in names),
                "Published local APK unexpectedly includes a QA marker or native probe")
        for name, expected in PINNED_MEMBERS.items():
            require(hashlib.sha256(archive.read(name)).hexdigest() == expected,
                    "Published local APK native or metadata provenance mismatch")
        marker = json.loads(archive.read("assets/idoly-local.json"))
        patches = marker.get("native_bootstrap", {}).get("patches", [])
        require(marker.get("package") == PACKAGE and marker.get("endpoint") == "http://127.0.0.1:50051"
                and len(patches) == 6 and {row.get("method") for row in patches} == BOOTSTRAP_METHODS,
                "Published local APK is not the six-hook local bootstrap")
    (output / "published-local-apk-signature.txt").write_text(signature)
    (output / "published-local-apk-badging.txt").write_text(badging)
    return {"asset_id": APK_ASSET, "release": "local-client-v0.1.0", "bytes": APK_SIZE,
            "sha256": APK_SHA, "certificate_sha256": CERT_SHA, "package": PACKAGE,
            "published_bytes_unchanged": True, "untouched_original_client": False,
            "local_bootstrap_methods": sorted(BOOTSTRAP_METHODS), "member_sha256": PINNED_MEMBERS,
            "ui_bridge_added": False, "phase_hooks_added": False, "software_aes_added": False,
            "store_patch_added": False, "graphics_patch_added": False}


def prepare(apk: Path, payload: Path, output: Path) -> dict:
    result = {"apk": verify_apk(apk, output), "payload": verify_payload(payload)}
    write_json(output / "inputs.json", result)
    return result


def collect_game_logs(output: Path, pids: set[str]) -> None:
    sensitive = re.compile(r"token|password|authorization|firebase|api.?key|advertising.?id|eyJ[\w-]+\.[\w-]+\.[\w-]+", re.I)
    lines = decoded(optional_adb("logcat", "-d", "-v", "threadtime", timeout=30)).splitlines()
    kept = []
    for line in lines:
        fields = line.split()
        owned = len(fields) > 2 and fields[2] in pids
        relevant = PACKAGE in line or bool(re.search(
            r"FATAL EXCEPTION|Fatal signal|libndk_translation|UnsatisfiedLinkError", line))
        if (owned or relevant) and not sensitive.search(line):
            kept.append(re.sub(r"(https?://[^\s?]+)\?\S+", r"\1?[query omitted]", line)[:4096])
    (output / "game-filtered-logcat.txt").write_text("\n".join(kept)[-2097152:] + "\n")
    crash = decoded(optional_adb("logcat", "-b", "crash", "-d", "-v", "threadtime"))
    (output / "crash-filtered.txt").write_text("\n".join(line[:4096] for line in crash.splitlines()
        if not sensitive.search(line))[-1048576:] + "\n")


def observe(apk: Path, payload: Path, output: Path, api_level: int, duration: int) -> None:
    report = {"workflow_sha": os.environ.get("GITHUB_SHA"), "run_id": os.environ.get("GITHUB_RUN_ID"),
              "untouched_original_client": False, "published_local_client_bytes_unchanged": True,
              "local_bootstrap": True, "ui_bridge_added": False, "phase_hooks_added": False,
              "software_aes_added": False, "store_patch_added": False, "graphics_patch_added": False,
              "native_live_engine_loaded": False, "experimental_main_live": False,
              "UI_input_performed": False, "system_UI_input_performed": False, "system_UI_actions": [],
              "gameplay_UI_input_performed": False, "account_UI_input_performed": False,
              "account_credentials_supplied": False, "gameplay_verified": False,
              "observation_seconds_requested": duration, "api_level_requested": api_level, "samples": []}
    runtime = None
    pids: set[str] = set()
    server_lines, rpc_counts = deque(maxlen=2000), Counter()
    log_lock = threading.Lock()

    def server_log(line):
        # Only fixed transport results and known startup strings are exported.
        # Request bodies, headers, tokens, snapshots and private DBs are excluded.
        rpc = re.fullmatch(r"RPC (/[A-Za-z0-9_.]+/[A-Za-z0-9_]+) -> ([A-Z_]+)", line)
        allowed = rpc or line.startswith(("gRPC listening on 127.0.0.1:",
            "Local gRPC server ready at 127.0.0.1:", "Local assets ready at http://127.0.0.1:"))
        allowed = allowed or line in ("Created local profile qa-stock-local", "Local server stopped")
        if allowed:
            with log_lock:
                server_lines.append(line)
                if rpc:
                    rpc_counts[(rpc[1], rpc[2])] += 1

    try:
        # Revalidate the inputs after emulator boot, not just in the prior step.
        prepare(apk, payload, output)
        image = Path(os.environ["ANDROID_HOME"]) / f"system-images/android-{api_level}/google_apis_playstore/x86_64"
        source_properties = (image / "source.properties").read_text()
        (output / "image-source.properties").write_text(source_properties)
        expected_revision = {35: 9, 36: 7}[api_level]
        require(bool(re.search(rf"^Pkg.Revision\s*=\s*{expected_revision}\s*$", source_properties, re.M)),
                "Unexpected official Google Play image revision")
        properties = ("ro.build.version.sdk", "ro.build.fingerprint", "ro.product.cpu.abi",
                      "ro.product.cpu.abilist", "ro.dalvik.vm.native.bridge", "ro.hardware.egl")
        report["image_properties"] = {key: decoded(adb("shell", "getprop", key)).strip() for key in properties}
        require(report["image_properties"]["ro.build.version.sdk"] == str(api_level), "Wrong running image API level")
        require(report["image_properties"]["ro.product.cpu.abi"] == "x86_64"
                and "arm64-v8a" in report["image_properties"]["ro.product.cpu.abilist"].split(",")
                and report["image_properties"]["ro.dalvik.vm.native.bridge"] == "libndk_translation.so",
                "Stock Google ARM64 app translation is not available")
        (output / "surfaceflinger-before.txt").write_text(decoded(adb("shell", "dumpsys", "SurfaceFlinger"))[:131072])
        (output / "native-bridge-files.txt").write_text(decoded(adb("shell", "ls", "-l",
            "/system/lib64/libndk_translation.so", "/system/lib64/libhoudini.so", check=False)))
        private = Path(os.environ["RUNNER_TEMP"]) / "idoly-stock-local-private"
        require(not private.exists(), "A fresh private runtime directory is required")
        require(not private.resolve().is_relative_to(output.resolve())
                and not output.resolve().is_relative_to(private.resolve()),
                "Private runtime must stay separate from uploaded artifacts")
        spec = importlib.util.spec_from_file_location("idoly_stock_payload", ROOT / "macos-server/payload.py")
        require(spec is not None and spec.loader is not None, "Public payload installer is unavailable")
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        report["public_installation"] = installer.install_payload(payload, private)
        from idoly_local import app_runtime
        runtime = app_runtime.start(private, profile="qa-stock-local", log_callback=server_log)
        require(runtime.status()["running"] and not runtime.status().get("experimental_main_live", False),
                "Current host core did not start with ordinary live disabled")
        report["host_runtime_started"] = True
        for port in (50051, 8080):
            adb("reverse", f"tcp:{port}", f"tcp:{port}")
        (output / "adb-reverse.txt").write_text(decoded(adb("reverse", "--list")))
        installed = optional_adb("install", str(apk), timeout=180)
        (output / "install.txt").write_text(decoded(installed))
        report["install_returncode"] = installed.returncode
        require(installed.returncode == 0 and "Success" in decoded(installed), "Published local APK installation failed")
        report["published_local_installed"] = True
        (output / "installed-package.txt").write_text(decoded(adb("shell", "dumpsys", "package", PACKAGE))[:131072])
        activity = decoded(adb("shell", "cmd", "package", "resolve-activity", "--brief", PACKAGE)).strip().splitlines()[-1]
        require(activity == PACKAGE + "/com.google.firebase.MessagingUnityPlayerActivity", "Unexpected local launch activity")
        report["launch_activity"] = activity
        adb("logcat", "-c")
        started = optional_adb("shell", "am", "start", "-W", "-n", activity, timeout=60)
        (output / "start.txt").write_text(decoded(started))
        report["activity_start_returncode"] = started.returncode
        require(started.returncode == 0 and "Error:" not in decoded(started), "Published local activity start failed")
        epoch = time.monotonic()
        for target in (0, 15, 30, 60, 120, duration):
            remaining = epoch + target - time.monotonic()
            if remaining > 0:
                time.sleep(remaining)
            current = decoded(adb("shell", "pidof", PACKAGE, check=False)).strip().split()
            pids.update(value for value in current if value.isdecimal())
            sample = {"elapsed_seconds": round(time.monotonic() - epoch, 1), "pids": current}
            screenshot = optional_adb("exec-out", "screencap", "-p", timeout=30)
            if screenshot.returncode == 0 and screenshot.stdout.startswith(b"\x89PNG"):
                (output / f"screen-{target:03d}.png").write_bytes(screenshot.stdout)
                sample["screenshot"] = True
            xml = dump_ui(output, f"ui-{target:03d}.xml")
            sample["ui_dump_succeeded"] = xml is not None
            if not report["system_UI_actions"] and fullscreen_hint(xml or b"") is not None:
                dismiss_fullscreen_hint(output, report)
            status = runtime.status()
            sample["server_running"] = status["running"]
            sample["asset_transfer"] = status["asset_transfer"]
            report["samples"].append(sample)
            write_json(output / "result.json", report)
        report["observed_game_pids"] = sorted(pids)
        report["process_alive_at_end"] = bool(report["samples"][-1]["pids"])
        report["outcome"] = ("process remained alive; gameplay requires visual review"
            if report["process_alive_at_end"] else "game process exited during baseline observation")
        report["baseline_observation_completed"] = True
    except Exception as error:
        report["error_type"] = type(error).__name__
        report["error"] = str(error)[:2048]
        raise
    finally:
        try:
            collect_game_logs(output, pids)
        except Exception as error:
            report["log_collection_error_type"] = type(error).__name__
        if runtime is not None:
            report["host_runtime_running_at_end"] = runtime.status()["running"]
            try:
                runtime.stop()
                report["host_runtime_stopped"] = True
            except Exception as error:
                report["runtime_cleanup_error_type"] = type(error).__name__
        with log_lock:
            (output / "server-fixed-log.txt").write_text("\n".join(server_lines) + "\n")
            report["rpc_results"] = [{"path": path, "status": status, "count": count}
                for (path, status), count in sorted(rpc_counts.items())]
        report["rpc_observed"] = bool(report["rpc_results"])
        write_json(output / "result.json", report)
        print(json.dumps({key: report.get(key) for key in ("published_local_installed", "host_runtime_started",
            "process_alive_at_end", "baseline_observation_completed", "rpc_observed", "gameplay_verified", "error")}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--apk", type=Path, required=True)
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--api-level", type=int, choices=(35, 36), default=35)
    parser.add_argument("--observe-seconds", type=int, choices=(180,), default=180)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.prepare:
        prepare(args.apk, args.payload, args.output)
    else:
        observe(args.apk, args.payload, args.output, args.api_level, args.observe_seconds)


if __name__ == "__main__":
    main()
