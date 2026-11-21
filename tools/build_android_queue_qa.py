#!/usr/bin/env python3
"""Build/run production Queue storage in an ordinary Android app, without the game.

Building is not a runtime pass. Device mode requires enforcing untrusted_app
SELinux, a fresh challenge, matching compiled production sources and every case.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

try:
    from tools import build_android_mp4_qa as common
except ModuleNotFoundError:
    import build_android_mp4_qa as common

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "game.qualiarts.idolypride.queueqa"
ACTIVITY = PACKAGE + "/.QueueProbeActivity"
APK_NAME = "Idoly-Queue-Storage-QA.apk"
NDK = "26.3.11579264"
MIB = 1024 * 1024
MANIFEST = "android-unified/queue-qa/AndroidManifest.xml"
JAVA = "android-unified/queue-qa/src/game/qualiarts/idolypride/queueqa/QueueProbeActivity.java"
NATIVE = "android-unified/queue-qa/native/queue_probe.cpp"
FILES = "android-unified/queue-qa/native/queue_probe_files.hpp"
QUEUE = "client-presentation/native/mp4_queue.hpp"
SOURCE_PATHS = (MANIFEST, JAVA, NATIVE, FILES, QUEUE, "client-presentation/native/mp4_output_policy.hpp",
                "tools/build_android_queue_qa.py", "tools/build_android_mp4_qa.py")
REQUIRED = {"legacy_hardlink_denied", "install_new_no_clobber", "queue_roundtrip",
            "queue_existing_target_rejected", "journal_symlink_rejected", "lock_symlink_rejected", "journal_tamper_rejected"}
need, regular, sha = common.need, common.regular, common.sha


def sources(root=ROOT):
    rows = {name: {"bytes": regular(root / name, MIB).stat().st_size, "sha256": sha(root / name)}
            for name in SOURCE_PATHS}
    manifest = ET.fromstring((root / MANIFEST).read_bytes())
    android = "{http://schemas.android.com/apk/res/android}"
    need(manifest.tag == "manifest" and manifest.get("package") == PACKAGE
         and not manifest.findall("uses-permission") and not manifest.findall("instrumentation"), "Unexpected probe manifest")
    sdk, app = manifest.find("uses-sdk"), manifest.find("application")
    need(sdk is not None and sdk.get(android + "minSdkVersion") == "30" and sdk.get(android + "targetSdkVersion") == "35",
         "Unexpected probe SDK bounds")
    need(app is not None and app.get(android + "debuggable") == "true" and app.get(android + "allowBackup") == "false"
         and app.get(android + "extractNativeLibs") == "true" and len(list(app)) == 1, "Unexpected app scope")
    activity = app.find("activity")
    need(activity is not None and activity.get(android + "name") == ".QueueProbeActivity"
         and activity.get(android + "exported") == "true", "Unexpected probe activity")
    return rows


def snapshot(rows):
    return hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def build(directory, sdk, *, root=ROOT, require_committed=False):
    need(not directory.exists() and not directory.is_symlink(), "Fresh output directory required")
    directory.mkdir(mode=0o700, parents=True)
    log = directory / "build.log"
    before = sources(root)
    sdk = sdk.resolve(strict=True)
    tools = sdk / "build-tools/34.0.0"
    android = regular(sdk / "platforms/android-34/android.jar")
    ndk = sdk / "ndk" / NDK
    need(re.search(r"^Pkg.Revision\s*=\s*" + re.escape(NDK) + r"\s*$", (ndk / "source.properties").read_text(), re.M),
         "Pinned NDK revision required")
    toolchain = ndk / "toolchains/llvm/prebuilt/linux-x86_64/bin"
    java_home = Path(os.environ["JAVA_HOME"]) / "bin" if os.environ.get("JAVA_HOME") else None
    java = (java_home / "java" if java_home else Path(shutil.which("java") or "")).resolve(strict=True)
    javac = (java_home / "javac" if java_home else Path(shutil.which("javac") or "")).resolve(strict=True)
    for tool in (java, javac, tools / "aapt2", tools / "zipalign", tools / "lib/d8.jar", tools / "lib/apksigner.jar"):
        regular(tool, 128 * MIB)
    commit = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    need(re.fullmatch(r"[0-9a-f]{40}", commit), "Exact checkout source required")
    committed = True
    for name, row in before.items():
        stored = subprocess.run(["git", "-C", str(root), "show", commit + ":" + name],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=15)
        if stored.returncode or hashlib.sha256(stored.stdout).hexdigest() != row["sha256"]:
            committed = False
    need(committed or not require_committed, "CI requires committed source identical to HEAD")
    run = lambda args: common.run_logged(args, log)
    with tempfile.TemporaryDirectory(prefix="build-", dir=directory) as temporary:
        work = Path(temporary)
        classes, dex = work / "classes", work / "dex"
        classes.mkdir(); dex.mkdir()
        libraries = {}
        for abi, triple in (("x86_64", "x86_64-linux-android"), ("arm64-v8a", "aarch64-linux-android")):
            compiler = toolchain / (triple + "30-clang++")
            need(compiler.is_file() and os.access(compiler, os.X_OK), "NDK compiler unavailable")
            library = work / abi / "libidoly_queue_qa.so"; library.parent.mkdir()
            run([compiler, "-std=c++17", "-O2", "-fPIC", "-shared", "-static-libstdc++", "-fvisibility=hidden",
                 "-Wall", "-Wextra", "-Werror", "-Wl,-z,relro,-z,now,-z,noexecstack", "-Wl,--build-id=sha1",
                 '-DIDOLY_QUEUE_SOURCE_SHA256="' + before[QUEUE]["sha256"] + '"',
                 '-DIDOLY_QUEUE_SNAPSHOT_SHA256="' + snapshot(before) + '"',
                 "-I", root / "client-presentation/native", root / NATIVE, "-o", library])
            regular(library, 4 * MIB); libraries[abi] = library
        run([javac, *["-J" + flag for flag in common.JAVA_FLAGS], "--release", "17", "-encoding", "UTF-8",
             "-classpath", android, "-d", classes, root / JAVA])
        class_files = sorted(classes.rglob("*.class"))
        need(class_files and all(p.relative_to(classes).as_posix().startswith(PACKAGE.replace(".", "/") + "/")
             for p in class_files), "Unexpected Java classes")
        run([java, *common.JAVA_FLAGS, "-cp", tools / "lib/d8.jar", "com.android.tools.r8.D8", "--release",
             "--min-api", "30", "--lib", android, "--output", dex, *class_files])
        need({p.name for p in dex.iterdir()} == {"classes.dex"}, "Unexpected DEX inventory")
        unsigned, aligned = work / "unsigned.apk", work / "aligned.apk"
        run([tools / "aapt2", "link", "--manifest", root / MANIFEST, "-I", android,
             "--min-sdk-version", "30", "--target-sdk-version", "35", "-o", unsigned])
        with ZipFile(unsigned, "a", compression=ZIP_DEFLATED) as archive:
            need(not any(n.startswith(("lib/", "assets/")) or n == "classes.dex" for n in archive.namelist()), "Unexpected APK contents")
            archive.write(dex / "classes.dex", "classes.dex")
            for abi, library in libraries.items(): archive.write(library, "lib/" + abi + "/" + library.name)
        run([tools / "zipalign", "-f", "4", unsigned, aligned])
        password = work / "public-development-password.txt"; password.write_text("android\n"); password.chmod(0o600)
        run([java, *common.JAVA_FLAGS, "-jar", tools / "lib/apksigner.jar", "sign", "--ks",
             regular(root / "android-diagnostics/local-diagnostics-development.keystore", MIB),
             "--ks-key-alias", "idoly-diagnostics-public", "--ks-pass", "file:" + str(password),
             "--v4-signing-enabled", "false", aligned])
        verification = subprocess.check_output([str(java), *common.JAVA_FLAGS, "-jar", str(tools / "lib/apksigner.jar"),
            "verify", "--verbose", "--print-certs", str(aligned)], env=common.clean_java_environment(), text=True, timeout=90)
        need("Signer #1 certificate SHA-256 digest: " + common.CERT in verification, "Unexpected signing certificate")
        (directory / "signature.txt").write_text(verification)
        run([tools / "zipalign", "-c", "4", aligned])
        need(sources(root) == before, "Sources changed during build")
        apk = directory / APK_NAME; need(aligned.stat().st_size <= 8 * MIB, "Probe APK bound exceeded"); os.link(aligned, apk)
        native_hashes = {abi: sha(library) for abi, library in libraries.items()}
    report = {"schema": 1, "status": "BUILT_NOT_RUNTIME_VALIDATED", "source_commit": commit,
              "working_tree_snapshot": not committed, "package": PACKAGE, "source_sha256": before,
              "source_snapshot_sha256": snapshot(before), "production_queue_sha256": before[QUEUE]["sha256"],
              "source_unchanged_during_build": True, "ndk_revision": NDK, "certificate_sha256": common.CERT,
              "apk_bytes": apk.stat().st_size, "apk_sha256": sha(apk), "native_library_sha256": native_hashes,
              "actual_android_app_storage_verified": False, "actual_game_mv_verified": False}
    (directory / "build-report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


def validate_runtime_report(value, built, challenge, app_uid, host_enforcement):
    need(type(challenge) is str and re.fullmatch(r"[0-9a-f]{64}", challenge), "Fresh bounded challenge required")
    need(type(host_enforcement) is dict and host_enforcement.get("source") == "adb_shell_getenforce"
         and host_enforcement.get("before") == "Enforcing" and host_enforcement.get("after") == "Enforcing",
         "Independent host SELinux Enforcing attestations required both before and after")
    need(type(value) is dict and value.get("schema") == 1 and value.get("package") == PACKAGE
         and value.get("phase") == "completed" and value.get("passed") is True and not value.get("error")
         and value.get("challenge") == challenge, "Probe did not complete with the fresh challenge")
    native = value.get("native", {})
    need(type(native) is dict and not native.get("error"), "Missing native process proof")
    need(type(app_uid) is int and 10000 <= app_uid % 100000 < 20000
         and type(value.get("java_uid")) is int and value["java_uid"] == app_uid
         and native.get("uid") == app_uid and native.get("euid") == app_uid
         and type(native.get("uid")) is int and type(native.get("euid")) is int
         and type(value.get("java_pid")) is int and value["java_pid"] > 1 and native.get("pid") == value["java_pid"]
         and type(value.get("android_api")) is int and value["android_api"] >= 30, "Ordinary app execution proof differs")
    need(native.get("challenge") == challenge
         and re.fullmatch(r"u:r:untrusted_app(?:_[0-9]+)?:s0(?::c[0-9]+(?:,c[0-9]+)*)?", native.get("selinux_context", ""))
         and native.get("private_storage_owner_mode") is True, "untrusted_app/private storage attestation required")
    read_errno = native.get("selinux_enforce_read_errno")
    need(native.get("selinux_enforcement_source") == "app_selinuxfs_enforce" and type(read_errno) is int
         and "selinux_enforcing" in native
         and ((native.get("selinux_enforce_read_status") == "read" and read_errno == 0 and native["selinux_enforcing"] is True)
              or (native.get("selinux_enforce_read_status") == "unavailable" and read_errno in (1, 13)
                  and native["selinux_enforcing"] is None)), "Native SELinux read result must be exact; never synthesize enforcing")
    need(native.get("production_queue_sha256") == built.get("production_queue_sha256")
         and native.get("source_snapshot_sha256") == built.get("source_snapshot_sha256")
         and re.fullmatch(r"[0-9a-f]{64}", native.get("production_queue_sha256", ""))
         and re.fullmatch(r"[0-9a-f]{64}", native.get("source_snapshot_sha256", "")), "Compiled production source identity differs")
    cases = native.get("cases")
    need(type(cases) is list and all(type(row) is dict and type(row.get("name")) is str for row in cases), "Missing native cases")
    rows = {row["name"]: row for row in cases}
    need(len(rows) == len(cases) and set(rows) == REQUIRED, "Unexpected, missing or duplicate native cases")
    for name, row in rows.items():
        need(row.get("required") is True and row.get("status") == "passed" and not row.get("error"), "Required storage case failed/unsupported")
        if name == "legacy_hardlink_denied":
            need(type(row.get("return")) is int and row["return"] == -1 and type(row.get("errno")) is int
                 and row["errno"] in (1, 13) and row.get("source_preserved_target_absent") is True,
                 "Legacy linkat policy denial (EPERM/EACCES) proof differs")
        elif name == "install_new_no_clobber":
            need(all(type(row.get(key)) is int for key in ("existing_return", "existing_errno", "fresh_return", "fresh_errno"))
                 and row.get("existing_return") == -1 and row.get("existing_errno") == 17
                 and row.get("fresh_return") == 0 and row.get("fresh_errno") == 0
                 and row.get("both_existing_files_preserved") is True and row.get("fresh_single_link_install") is True,
                 "Production no-replace syscall contract differs")
        else:
            need(type(row.get("storage_errno")) is int and 0 <= row["storage_errno"] <= 4095
                 and re.fullmatch(r"[a-z_]{1,40}", row.get("storage_stage", "")), "Missing bounded storage diagnostics")
            if name == "queue_roundtrip":
                need(row.get("queue_error") == "none" and row.get("storage_stage") == "none" and row["storage_errno"] == 0
                     and row.get("reopened_count") == 2 and row.get("generation") == 2
                     and all(row.get(key) is True for key in ("descriptor_preserved", "private_single_link_journal",
                         "private_zero_byte_single_link_lock_preserved", "temporary_files_absent")),
                     "Production Queue commit/reopen proof differs")
            elif name == "queue_existing_target_rejected":
                need(row.get("queue_error") == "queue_storage_changed" and row.get("sentinel_preserved") is True
                     and row.get("state_unmodified") is True, "Existing Queue journal was not preserved")
            elif name in ("journal_symlink_rejected", "lock_symlink_rejected"):
                need(row.get("queue_error") == "unsafe_queue_storage" and row.get("symlink_and_sentinel_preserved") is True,
                     "Symlink rejection proof differs")
            elif name == "journal_tamper_rejected":
                need(row.get("queue_error") == "queue_storage_changed" and row.get("reopen_error") == "queue_corrupt"
                     and row.get("tampered_bytes_preserved") is True and row.get("state_unmodified") is True,
                     "Live and reopen tamper rejection proof differs")
    return value


def collect_optional_evidence(directory, base, challenge):
    """Capture only this visible Activity and its current process; never gate pass."""
    evidence = {}
    def raw_result(*args, maximum=MIB, timeout=5):
        process = subprocess.run([*base, *map(str, args)], stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, timeout=timeout)
        need(len(process.stdout) <= maximum and len(process.stderr) <= maximum, "Optional evidence oversized")
        return process
    def raw(*args, **kwargs):
        process = raw_result(*args, **kwargs)
        need(process.returncode == 0, "Optional evidence command unavailable")
        return process.stdout
    def absent_test(flag, path):
        result = raw_result("shell", "test", flag, path, maximum=128, timeout=3)
        need(result.returncode in (0, 1), "Optional path inspection failed")
        return result.returncode == 1
    try:
        pid_text = raw("shell", "pidof", "-s", PACKAGE, maximum=128).strip().decode("ascii")
        need(re.fullmatch(r"[0-9]{1,10}", pid_text) and int(pid_text) > 1, "Probe PID unavailable")
        log = raw("logcat", "-d", "--pid", pid_text, "-t", "200", maximum=256 * 1024)
        with (directory / "own-pid-logcat.txt").open("xb") as output: output.write(log)
        evidence.update(logcat="own-pid-logcat.txt", logcat_pid=int(pid_text), logcat_bytes=len(log))
    except Exception as error:
        evidence["logcat_error_type"] = type(error).__name__
    temporary, owns_temporary = None, False
    try:
        need(re.fullmatch(r"[0-9a-f]{64}", challenge), "Optional capture challenge differs")
        temporary = "/data/local/tmp/idoly-queue-storage-" + challenge + ".xml"
        need(absent_test("-e", temporary) and absent_test("-L", temporary), "Optional XML path already exists")
        owns_temporary = True
        raw("shell", "uiautomator", "dump", temporary, maximum=4096, timeout=20)
        need(absent_test("-L", temporary), "Optional XML path is a symlink")
        raw("shell", "test", "-f", temporary, maximum=128, timeout=3)
        dump = raw("exec-out", "cat", temporary, maximum=256 * 1024)
        start, end = dump.find(b"<?xml"), dump.rfind(b"</hierarchy>")
        need(start >= 0 and end >= start, "UI hierarchy unavailable")
        tree = dump[start:end + len(b"</hierarchy>")]
        hierarchy = ET.fromstring(tree)
        packages = {node.get("package") for node in hierarchy.iter("node") if node.get("package")}
        need(PACKAGE in packages and packages <= {PACKAGE, "android", "com.android.systemui"},
             "Probe Activity is not the visible UI; omit capture")
        with (directory / "ui-tree.xml").open("xb") as output: output.write(tree)
        evidence["ui_tree"] = "ui-tree.xml"
        screenshot = raw("exec-out", "screencap", "-p", maximum=8 * MIB, timeout=10)
        need(screenshot.startswith(b"\x89PNG\r\n\x1a\n"), "Screenshot is not PNG")
        with (directory / "activity.png").open("xb") as output: output.write(screenshot)
        evidence.update(screenshot="activity.png", screenshot_bytes=len(screenshot))
    except Exception as error:
        evidence["ui_error_type"] = type(error).__name__
    finally:
        if owns_temporary:
            try:
                raw("shell", "rm", "-f", "--", temporary, maximum=128, timeout=3)
            except Exception as error:
                evidence["ui_cleanup_error_type"] = type(error).__name__
    return evidence


def run_device(directory, sdk, serial, timeout, *, root=ROOT, require_committed=False):
    need(re.fullmatch(r"[a-zA-Z0-9_.:-]{1,100}", serial) and 1 <= timeout <= 180, "Bounded device probe required")
    built = json.loads(regular(directory / "build-report.json", MIB).read_bytes())
    apk = regular(directory / APK_NAME, 8 * MIB)
    need(built.get("schema") == 1 and built.get("status") == "BUILT_NOT_RUNTIME_VALIDATED" and built.get("package") == PACKAGE
         and built.get("certificate_sha256") == common.CERT and built.get("ndk_revision") == NDK
         and built.get("apk_bytes") == apk.stat().st_size and built.get("apk_sha256") == sha(apk)
         and built.get("source_sha256") == sources(root) and built.get("source_snapshot_sha256") == snapshot(sources(root))
         and built.get("production_queue_sha256") == sources(root)[QUEUE]["sha256"]
         and built.get("source_unchanged_during_build") is True, "Built APK/source identity differs")
    need(not require_committed or built.get("working_tree_snapshot") is False, "Committed source required for CI")
    need(not (directory / "runtime-report.json").exists() and not (directory / "terminal-report.json").exists(), "Fresh runtime output required")
    adb = regular(sdk / "platform-tools/adb" if sdk else Path(shutil.which("adb") or ""))
    base = [str(adb), "-s", serial]
    challenge = secrets.token_hex(32)
    proof = {"schema": 1, "status": "FAILED", "package": PACKAGE, "serial": serial, "challenge": challenge,
             "apk_sha256": built["apk_sha256"], "source_commit": built["source_commit"],
             "actual_android_app_storage_verified": False, "actual_game_mv_verified": False,
             "selinux_enforcement": {"source": "adb_shell_getenforce", "before": None, "after": None}}
    terminal, failure = None, None
    def command(*args, limit=30):
        result = subprocess.run([*base, *map(str, args)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=limit)
        need(len(result.stdout) <= MIB and result.returncode == 0, "ADB command failed")
        return result.stdout.decode("utf-8", "strict")
    try:
        proof["selinux_enforcement"]["before"] = command("shell", "getenforce").strip()
        need(proof["selinux_enforcement"]["before"] == "Enforcing", "SELinux enforcing is required; never disable it")
        command("install", "-r", apk, limit=90)
        command("shell", "am", "force-stop", PACKAGE)
        need(command("shell", "pm", "clear", PACKAGE).strip() == "Success", "Fresh private app storage required")
        identity = command("shell", "cmd", "package", "list", "packages", "-U", PACKAGE).strip()
        match = re.fullmatch(r"package:" + re.escape(PACKAGE) + r" uid:([0-9]+)", identity)
        need(match is not None, "Package UID not attested")
        app_uid = int(match[1]); proof["package_uid"] = app_uid
        launch = command("shell", "am", "start", "-W", "-n", ACTIVITY, "--es", "challenge", challenge)
        (directory / "launch.txt").write_text(launch)
        need("Status: ok" in launch and "Error:" not in launch, "Probe activity failed to launch")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = subprocess.run([*base, "shell", "run-as", PACKAGE, "cat", "files/queue-qa/report.json"],
                                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10)
            need(len(result.stdout) <= 32768, "Device report bound exceeded")
            if result.returncode == 0:
                try: terminal = json.loads(result.stdout)
                except (ValueError, UnicodeError): terminal = None
                if type(terminal) is dict and terminal.get("phase") in ("completed", "failed"): break
            time.sleep(1)
        need(terminal is not None, "Missing terminal ordinary-app storage report")
        (directory / "terminal-report.json").write_text(json.dumps(terminal, indent=2) + "\n")
        proof["selinux_enforcement"]["after"] = command("shell", "getenforce").strip()
        validate_runtime_report(terminal, built, challenge, app_uid, proof["selinux_enforcement"])
        need(sources(root) == built["source_sha256"], "Production source changed during runtime QA")
        proof.update(status="PASS_ANDROID_APP_QUEUE_STORAGE_ONLY", actual_android_app_storage_verified=True, result=terminal)
    except Exception as error:
        failure = error; proof["error_type"] = type(error).__name__; proof["error"] = str(error)[:2000]
    finally:
        if terminal is not None and not (directory / "terminal-report.json").exists():
            (directory / "terminal-report.json").write_text(json.dumps(terminal, indent=2) + "\n")
        proof["optional_evidence"] = collect_optional_evidence(directory, base, challenge)
        try:
            command("shell", "am", "force-stop", PACKAGE)
        except Exception as error:
            proof["stop_error_type"] = type(error).__name__
            if failure is None:
                failure = error
                proof.update(status="FAILED", actual_android_app_storage_verified=False, error="Could not stop standalone QA app")
        (directory / "runtime-report.json").write_text(json.dumps(proof, indent=2) + "\n")
    print(json.dumps(proof, indent=2))
    if failure is not None: raise ValueError("Android queue storage QA failed; see runtime-report.json") from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--android-sdk", type=Path)
    parser.add_argument("--run-device", action="store_true")
    parser.add_argument("--require-committed", action="store_true")
    parser.add_argument("--serial", default="emulator-5554")
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()
    sdk = args.android_sdk or (Path(os.environ["ANDROID_HOME"]) if os.environ.get("ANDROID_HOME") else None)
    if args.run_device: run_device(args.output_directory.absolute(), sdk, args.serial, args.timeout, require_committed=args.require_committed)
    else:
        need(sdk is not None, "Android SDK required")
        build(args.output_directory.absolute(), sdk, require_committed=args.require_committed)


if __name__ == "__main__":
    main()
