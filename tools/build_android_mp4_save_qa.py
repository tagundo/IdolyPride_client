#!/usr/bin/env python3
"""Build/run actual Android Save/cancel/recreation UI using a complete synthetic MP4.

The production Java save controller is unchanged. A tiny JNI producer supplies
fixture status only. This is not game MV rendering, encoding or codec proof.
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
    from tools import build_android_queue_qa as storage
except ModuleNotFoundError:
    import build_android_mp4_qa as common
    import build_android_queue_qa as storage

ROOT = Path(__file__).resolve().parents[1]
BASE = "android-unified/mp4-save-qa"
PRODUCTION = "android-server/app/src/main/java/game/qualiarts/idolypride/localserver"
PRODUCTION_JAVA = ("UnifiedMP4Export.java", "Mp4CompletedExports.java", "Mp4ExportSettings.java",
                   "Mp4TitleCatalog.java", "Mp4QueueUiState.java", "DocumentPickerHistory.java")
PRODUCTION_RES = tuple("android-server/app/src/main/res/values-en/" + name for name in ("strings_mp4.xml", "strings_mp4_queue.xml"))
CONTROLLER = PRODUCTION + "/UnifiedMP4Export.java"
MANIFEST = BASE + "/AndroidManifest.xml"
FIXTURE = BASE + "/assets/fixture.mp4"
FIXTURE_SHA = "46e09ba150168f3ec6e548414b773d9a435310e3b4df65c8dd9ed4b93b22520b"
PACKAGE = "game.qualiarts.idolypride.mp4saveqa"
JAVA_PACKAGE = "game.qualiarts.idolypride.localserver"
ACTIVITY = PACKAGE + "/" + JAVA_PACKAGE + ".SaveProbeActivity"
APK_NAME = "Idoly-MP4-Save-UI-QA.apk"
MIB = 1024 * 1024
need, regular, sha = common.need, common.regular, common.sha
REQUIRED = {"no_automatic_picker", "explicit_save_cancel", "activity_recreation", "pending_picker_recreation", "second_explicit_save",
            "new_process_restore", "third_explicit_save"}


def sources(root=ROOT):
    paths = [MANIFEST, FIXTURE, BASE + "/native/save_fixture.cpp", "tools/build_android_mp4_save_qa.py",
             "tools/build_android_mp4_qa.py", "tools/build_android_queue_qa.py", *PRODUCTION_RES]
    paths += [PRODUCTION + "/" + name for name in PRODUCTION_JAVA]
    paths += [path.relative_to(root).as_posix() for folder in ("src", "res") for path in sorted((root / BASE / folder).rglob("*")) if path.is_file()]
    rows = {name: {"bytes": regular(root / name, MIB).stat().st_size, "sha256": sha(root / name)} for name in paths}
    need(len(rows) == len(paths) and rows[FIXTURE]["sha256"] == FIXTURE_SHA and rows[FIXTURE]["bytes"] == 1559, "Complete MP4 fixture/source identity differs")
    manifest = ET.fromstring((root / MANIFEST).read_bytes()); android = "{http://schemas.android.com/apk/res/android}"
    need(manifest.get("package") == PACKAGE and not manifest.findall("uses-permission") and not manifest.findall("instrumentation"), "Unexpected standalone manifest scope")
    queries = manifest.findall("queries/intent")
    need(len(queries) == 1 and len(list(queries[0])) == 3
         and queries[0].find("action").get(android + "name") == "android.intent.action.CREATE_DOCUMENT"
         and queries[0].find("category").get(android + "name") == "android.intent.category.OPENABLE"
         and queries[0].find("data").get(android + "mimeType") == "video/mp4", "Only narrow MP4 DocumentsUI visibility query allowed")
    sdk, app = manifest.find("uses-sdk"), manifest.find("application")
    need(sdk is not None and sdk.get(android + "minSdkVersion") == "30" and sdk.get(android + "targetSdkVersion") == "35", "Unexpected SDK bounds")
    need(app is not None and app.get(android + "debuggable") == "true" and app.get(android + "allowBackup") == "false" and len(list(app)) == 1, "Unexpected QA app scope")
    activity = app.find("activity")
    need(activity is not None and activity.get(android + "name") == JAVA_PACKAGE + ".SaveProbeActivity" and activity.get(android + "exported") == "true", "Unexpected QA Activity")
    return rows


def snapshot(rows):
    return hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def verify_fixture(root=ROOT):
    ffprobe = shutil.which("ffprobe"); need(ffprobe, "FFprobe required to verify the tiny complete fixture")
    value = json.loads(subprocess.check_output([ffprobe, "-v", "error", "-show_entries", "format=format_name,duration,size",
        "-show_entries", "stream=codec_name,width,height,nb_frames", "-of", "json", str(root / FIXTURE)], timeout=15))
    streams = value.get("streams", []); fmt = value.get("format", {})
    need(len(streams) == 1 and streams[0].get("codec_name") == "h264" and streams[0].get("width") == 32
         and streams[0].get("height") == 32 and streams[0].get("nb_frames") == "1"
         and fmt.get("duration") == "1.000000" and fmt.get("size") == "1559" and "mp4" in fmt.get("format_name", ""), "Fixture is not the expected complete synthetic MP4")
    return value


def verify_native_dependencies(dynamic_table):
    dependencies = re.findall(r"\(NEEDED\)\s+Shared library: \[([^\]]+)\]", dynamic_table)
    # This fixture packages one JNI DSO per ABI. Its entire runtime dependency
    # closure must be Android system libraries, not an omitted C++ shared DSO.
    need(dependencies and len(dependencies) == len(set(dependencies))
         and "libc.so" in dependencies and set(dependencies) <= {"libc.so", "libm.so", "libdl.so"},
         "QA JNI library has an unpackaged runtime dependency")
    return sorted(dependencies)


def build(directory, sdk, *, root=ROOT, require_committed=False):
    need(not directory.exists() and not directory.is_symlink(), "Fresh output directory required")
    directory.mkdir(mode=0o700, parents=True); log = directory / "build.log"
    before, fixture = sources(root), verify_fixture(root)
    sdk = sdk.resolve(strict=True); tools = sdk / "build-tools/34.0.0"; android = regular(sdk / "platforms/android-34/android.jar")
    ndk = sdk / "ndk" / storage.NDK
    need(re.search(r"^Pkg.Revision\s*=\s*" + re.escape(storage.NDK) + r"\s*$", (ndk / "source.properties").read_text(), re.M), "Pinned NDK required")
    toolchain = ndk / "toolchains/llvm/prebuilt/linux-x86_64/bin"
    java_home = Path(os.environ["JAVA_HOME"]) / "bin" if os.environ.get("JAVA_HOME") else None
    java = (java_home / "java" if java_home else Path(shutil.which("java") or "")).resolve(strict=True)
    javac = (java_home / "javac" if java_home else Path(shutil.which("javac") or "")).resolve(strict=True)
    commit = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    need(re.fullmatch(r"[0-9a-f]{40}", commit), "Exact checkout commit required")
    committed = True
    for name, row in before.items():
        stored = subprocess.run(["git", "-C", str(root), "show", commit + ":" + name], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=15)
        if stored.returncode or hashlib.sha256(stored.stdout).hexdigest() != row["sha256"]: committed = False
    need(committed or not require_committed, "CI requires committed source identical to HEAD")
    run = lambda args: common.run_logged(args, log)
    with tempfile.TemporaryDirectory(prefix="build-", dir=directory) as temporary:
        work = Path(temporary); classes, dex, generated, resources = (work / name for name in ("classes", "dex", "generated", "res"))
        for path in (classes, dex, generated, resources): path.mkdir()
        shutil.copytree(root / BASE / "res", resources, dirs_exist_ok=True)
        for name in PRODUCTION_RES: shutil.copyfile(root / name, resources / "values" / Path(name).name)
        compiled_res, unsigned, aligned = work / "resources.zip", work / "unsigned.apk", work / "aligned.apk"
        run([tools / "aapt2", "compile", "--dir", resources, "-o", compiled_res])
        run([tools / "aapt2", "link", "--manifest", root / MANIFEST, "-I", android, compiled_res,
             "--java", generated, "--custom-package", JAVA_PACKAGE, "--min-sdk-version", "30", "--target-sdk-version", "35", "-o", unsigned])
        libraries, native_dependencies = {}, {}
        for abi, triple in (("x86_64", "x86_64-linux-android"), ("arm64-v8a", "aarch64-linux-android")):
            compiler = toolchain / (triple + "30-clang++"); need(compiler.is_file(), "NDK compiler unavailable")
            library = work / abi / "libidoly_presentation.so"; library.parent.mkdir()
            run([compiler, "-std=c++17", "-O2", "-fPIC", "-shared", "-static-libstdc++", "-fvisibility=hidden", "-Wall", "-Wextra", "-Werror",
                 "-Wl,-z,relro,-z,now,-z,noexecstack", '-DIDOLY_SAVE_SOURCE_SHA256="' + snapshot(before) + '"',
                 '-DIDOLY_SAVE_CONTROLLER_SHA256="' + before[CONTROLLER]["sha256"] + '"', root / BASE / "native/save_fixture.cpp", "-o", library])
            regular(library, MIB); libraries[abi] = library
            dynamic_table = subprocess.check_output([str(toolchain / "llvm-readelf"), "--dynamic", str(library)], text=True, timeout=15)
            native_dependencies[abi] = verify_native_dependencies(dynamic_table)
        java_files = sorted((root / BASE / "src").rglob("*.java")) + [root / PRODUCTION / name for name in PRODUCTION_JAVA] + sorted(generated.rglob("*.java"))
        run([javac, *["-J" + flag for flag in common.JAVA_FLAGS], "--release", "17", "-encoding", "UTF-8", "-classpath", android, "-d", classes, *java_files])
        class_files = sorted(classes.rglob("*.class")); need(class_files, "No compiled QA classes")
        run([java, *common.JAVA_FLAGS, "-cp", tools / "lib/d8.jar", "com.android.tools.r8.D8", "--release", "--min-api", "30", "--lib", android, "--output", dex, *class_files])
        need({p.name for p in dex.iterdir()} == {"classes.dex"}, "Unexpected DEX inventory")
        with ZipFile(unsigned, "a", compression=ZIP_DEFLATED) as archive:
            need(not any(n.startswith(("lib/", "assets/")) or n == "classes.dex" for n in archive.namelist()), "Unexpected APK payload")
            archive.write(dex / "classes.dex", "classes.dex"); archive.write(root / FIXTURE, "assets/fixture.mp4")
            for abi, library in libraries.items(): archive.write(library, "lib/" + abi + "/" + library.name)
        run([tools / "zipalign", "-f", "4", unsigned, aligned])
        password = work / "public-development-password.txt"; password.write_text("android\n"); password.chmod(0o600)
        run([java, *common.JAVA_FLAGS, "-jar", tools / "lib/apksigner.jar", "sign", "--ks", root / "android-diagnostics/local-diagnostics-development.keystore",
             "--ks-key-alias", "idoly-diagnostics-public", "--ks-pass", "file:" + str(password), "--v4-signing-enabled", "false", aligned])
        signature = subprocess.check_output([str(java), *common.JAVA_FLAGS, "-jar", str(tools / "lib/apksigner.jar"), "verify", "--verbose", "--print-certs", str(aligned)],
                                            env=common.clean_java_environment(), text=True, timeout=90)
        need("Signer #1 certificate SHA-256 digest: " + common.CERT in signature, "Unexpected QA signature")
        (directory / "signature.txt").write_text(signature); run([tools / "zipalign", "-c", "4", aligned])
        need(sources(root) == before, "Source changed during build")
        apk = directory / APK_NAME; need(aligned.stat().st_size <= 4 * MIB, "APK bound exceeded"); os.link(aligned, apk)
        native_hashes = {abi: sha(path) for abi, path in libraries.items()}
    report = {"schema": 1, "status": "BUILT_NOT_RUNTIME_VALIDATED", "package": PACKAGE, "source_commit": commit,
              "source_sha256": before, "source_snapshot_sha256": snapshot(before), "production_controller_sha256": before[CONTROLLER]["sha256"],
              "working_tree_snapshot": not committed, "source_unchanged_during_build": True, "ndk_revision": storage.NDK,
              "certificate_sha256": common.CERT, "apk_sha256": sha(apk), "apk_bytes": apk.stat().st_size,
              "native_library_sha256": native_hashes, "native_required_libraries": native_dependencies,
              "fixture": fixture, "scope": "synthetic_mp4_save_ui_only",
              "actual_android_save_ui_verified": False, "actual_game_mv_verified": False, "actual_codec_verified": False}
    (directory / "build-report.json").write_text(json.dumps(report, indent=2) + "\n"); print(json.dumps(report, indent=2))


def validate_observation(value, built, challenge, app_uid):
    need(type(value) is dict and value.get("schema") == 1 and value.get("package") == PACKAGE
         and value.get("challenge") == challenge and value.get("scope") == "synthetic_mp4_save_ui_only"
         and value.get("phase") in ("observing", "completed") and not value.get("error"), "App fixture report failed or stale")
    native = value.get("native", {}); need(type(native) is dict and not native.get("error"), "Missing native receipt")
    need(type(app_uid) is int and 10000 <= app_uid % 100000 < 20000 and value.get("java_uid") == app_uid
         and native.get("uid") == app_uid and native.get("euid") == app_uid and type(value.get("java_pid")) is int
         and value["java_pid"] > 1 and value["java_pid"] == native.get("pid")
         and type(value.get("android_api")) is int and value["android_api"] >= 30, "Ordinary app execution required")
    need(re.fullmatch(r"u:r:untrusted_app(?:_[0-9]+)?:s0(?::c[0-9]+(?:,c[0-9]+)*)?", native.get("selinux_context", ""))
         and native.get("synthetic_native_fixture") is True and native.get("source_snapshot_sha256") == built["source_snapshot_sha256"]
         and native.get("production_controller_sha256") == built["production_controller_sha256"], "Compiled source/app-domain receipt differs")
    need(value.get("fixture_asset_sha256") == FIXTURE_SHA, "Complete fixture identity differs")
    for key in ("launches", "results", "cancelled", "boots", "creations", "completed_outputs"):
        need(type(value.get(key)) is int and 0 <= value[key] <= 16, "Missing bounded lifecycle counter")
    return value


def validate_runtime_report(value, built):
    need(type(value) is dict and value.get("status") == "PASS_ANDROID_SYNTHETIC_SAVE_UI_ONLY"
         and value.get("actual_android_save_ui_verified") is True and value.get("source_commit") == built["source_commit"]
         and value.get("apk_sha256") == built["apk_sha256"] and value.get("actual_game_mv_verified") is False
         and value.get("actual_codec_verified") is False, "Missing current-source synthetic Save UI gate")
    enforcement = value.get("selinux_enforcement", {})
    need(enforcement == {"source": "adb_shell_getenforce", "before": "Enforcing", "after": "Enforcing"}, "Enforcing SELinux required before and after")
    observations = value.get("observations", {}); need(type(observations) is dict and set(observations) == {"initial", "completed", "cancel1", "recreated", "pending_recreated", "cancel2", "cold", "cancel3", "terminal"}, "Missing required lifecycle observations")
    for observation in observations.values(): validate_observation(observation, built, value.get("challenge"), value.get("package_uid"))
    initial, complete, cold, terminal = (observations[key] for key in ("initial", "completed", "cold", "terminal"))
    need(initial["launches"] == 0 and initial["completed_outputs"] == 0 and initial.get("can_save") is False
         and initial.get("source_exists") is False and initial.get("picker_or_copy_active") is False
         and initial.get("native_phase") == "rendering" and initial.get("launch_mode") == "fresh" and complete["launches"] == 0
         and complete["completed_outputs"] == 1 and complete.get("can_save") is True, "Completion must never launch a picker")
    need(cold["java_pid"] != initial["java_pid"] and cold["boots"] >= 2 and cold.get("launch_mode") == "cold"
         and cold["native_phase"] == "idle" and cold["launches"] == 2 and cold.get("configured_output_changed") is True,
         "Cold restore must execute in a new process/new native output root without automatic picker")
    for key in ("completed", "cancel1", "recreated", "cancel2", "cold", "cancel3", "terminal"):
        observation = observations[key]
        need(observation.get("source_exists") is True and observation.get("source_sha256") == FIXTURE_SHA and observation.get("source_bytes") == 1559
             and observation["completed_outputs"] == 1 and observation.get("can_save") is True
             and observation.get("picker_or_copy_active") is False, "Completed source and explicit Save must survive every return/recreation")
    for number, key in ((1, "cancel1"), (2, "cancel2"), (3, "cancel3")):
        observation = observations[key]
        need(observation["launches"] == number and observation["results"] == number and observation["cancelled"] == number, "One real picker and cancellation required per explicit Save")
    need(observations["recreated"]["creations"] > initial["creations"] and observations["recreated"]["java_pid"] == initial["java_pid"], "Activity recreation must preserve its process")
    pending = observations["pending_recreated"]
    need(pending["creations"] > observations["recreated"]["creations"] and pending["java_pid"] == initial["java_pid"]
         and type(pending.get("pending_saved")) is int and pending["pending_saved"] > 0
         and pending.get("pending_saved_launches") == 2 and type(pending.get("pending_recreated")) is int and pending["pending_recreated"] > 0
         and pending.get("pending_restored_active") is True and pending.get("pending_restored_launches") == 2
         and pending.get("picker_or_copy_active") is True and pending["launches"] == 2 and pending["results"] == 1
         and pending.get("source_sha256") == FIXTURE_SHA and pending.get("source_exists") is True
         and pending["completed_outputs"] == 1, "Actual pending-picker Bundle save/recreation/restore required before cancellation")
    need(terminal.get("phase") == "completed" and terminal["launches"] == 3 and terminal["results"] == 3, "Missing terminal real UI completion")
    launches = terminal.get("document_launches")
    need(type(launches) is list and len(launches) == 3, "Missing actual Activity document launch records")
    for launch in launches:
        need(launch.get("request") == 50057 and launch.get("action") == "android.intent.action.CREATE_DOCUMENT"
             and launch.get("mime") == "video/mp4" and re.fullmatch(r"com\.(?:google\.android|android)\.documentsui/[^\s]{1,200}", launch.get("component", "")), "Actual launch must resolve to Android DocumentsUI for MP4")
    events = terminal.get("document_events")
    need(type(events) is list and len(events) == 6, "Production document diagnostics must retain all three launch/result pairs")
    for index, event in enumerate(events):
        need(event.get("request_code") == 50057 and event.get("action") == "android.intent.action.CREATE_DOCUMENT"
             and event.get("mime") == "video/mp4" and event.get("origin") == "mp4_save"
             and event.get("event") == ("launch" if index % 2 == 0 else "result")
             and event.get("result") == ("requested" if index % 2 == 0 else "cancelled"), "Production diagnostics must attribute only the actual user MP4 Save/cancel flow")
    cases = value.get("cases", [])
    need(type(cases) is list and len(cases) == len(REQUIRED) and {row.get("name") for row in cases} == REQUIRED
         and all(row.get("status") == "passed" and row.get("required") is True for row in cases), "Missing or skipped real UI case")
    need(value.get("documents_ui_visits") == 3 and value.get("ui_taps_from_fresh_bounds") is True, "Actual DocumentsUI visits and UI-tree-derived taps required")
    return value


def run_device(directory, sdk, serial, timeout, *, root=ROOT, require_committed=False):
    need(re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", serial) and 1 <= timeout <= 300, "Bounded target required")
    built = json.loads(regular(directory / "build-report.json", MIB).read_text()); apk = regular(directory / APK_NAME, 4 * MIB)
    need(built.get("status") == "BUILT_NOT_RUNTIME_VALIDATED" and built.get("package") == PACKAGE and built.get("source_sha256") == sources(root)
         and built.get("source_snapshot_sha256") == snapshot(sources(root)) and built.get("apk_sha256") == sha(apk)
         and built.get("apk_bytes") == apk.stat().st_size and built.get("certificate_sha256") == common.CERT
         and built.get("ndk_revision") == storage.NDK, "Built source/APK receipt differs")
    need(not require_committed or built.get("working_tree_snapshot") is False, "Committed source required")
    need(not (directory / "runtime-report.json").exists(), "Fresh runtime report required")
    adb = regular(sdk / "platform-tools/adb" if sdk else Path(shutil.which("adb") or "")); base = [str(adb), "-s", serial]
    challenge = secrets.token_hex(32); deadline = time.monotonic() + timeout; visits = 0
    proof = {"schema": 1, "status": "FAILED", "source_commit": built["source_commit"], "apk_sha256": built["apk_sha256"],
             "package": PACKAGE, "challenge": challenge, "actual_android_save_ui_verified": False, "actual_game_mv_verified": False,
             "actual_codec_verified": False, "observations": {}, "cases": [], "selinux_enforcement": {"source": "adb_shell_getenforce", "before": None, "after": None}}
    error = None
    def command(*args, maximum=MIB, limit=20, allow_false=False):
        process = subprocess.run([*base, *map(str, args)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=limit)
        need(len(process.stdout) <= maximum and len(process.stderr) <= maximum, "ADB evidence bound exceeded")
        need(process.returncode == 0 or allow_false and process.returncode == 1, "ADB " + str(args[0]) + " failed: " + process.stderr.decode(errors="replace")[:256])
        return process if allow_false else process.stdout
    def report(predicate):
        while time.monotonic() < deadline:
            process = command("shell", "run-as", PACKAGE, "cat", "files/save-qa/report.json", maximum=32768, allow_false=True, limit=5)
            try: value = json.loads(process.stdout)
            except (ValueError, UnicodeError): value = None
            if type(value) is dict:
                (directory / "last-app-report.json").write_text(json.dumps(value, indent=2) + "\n")
                validate_observation(value, built, challenge, proof["package_uid"])
                if predicate(value): return value
            time.sleep(0.25)
        raise ValueError("Required Android UI observation timed out")
    def tree(step, *, documents=False):
        temporary = "/data/local/tmp/idoly-save-ui-" + challenge + "-" + step + ".xml"; owned = False
        try:
            for flag in ("-e", "-L"):
                need(command("shell", "test", flag, temporary, maximum=128, allow_false=True, limit=3).returncode == 1, "Fresh XML path required")
            owned = True; command("shell", "uiautomator", "dump", temporary, maximum=4096, limit=20)
            raw = command("exec-out", "cat", temporary, maximum=256 * 1024, limit=5); hierarchy = ET.fromstring(raw)
            packages = {node.get("package") for node in hierarchy.iter("node") if node.get("package")}
            expected = any(re.fullmatch(r"com\.(?:google\.android|android)\.documentsui", package) for package in packages) if documents else PACKAGE in packages
            need(expected, "Expected DocumentsUI" if documents else "QA Activity is not visible")
            (directory / ("ui-" + step + ".xml")).write_bytes(raw)
            png = command("exec-out", "screencap", "-p", maximum=8 * MIB, limit=10); need(png.startswith(b"\x89PNG\r\n\x1a\n"), "PNG evidence required")
            (directory / (step + ".png")).write_bytes(png); return hierarchy
        finally:
            if owned: command("shell", "rm", "-f", "--", temporary, maximum=128, limit=3)
    def tap(description, step):
        hierarchy = tree(step)
        matches = [node for node in hierarchy.iter("node") if node.get("package") == PACKAGE and node.get("content-desc") == description
                   and node.get("enabled") == "true" and node.get("clickable") == "true"]
        if not matches:
            scrollable = next((node for node in hierarchy.iter("node") if node.get("scrollable") == "true"), None)
            if scrollable is not None:
                bounds = list(map(int, re.fullmatch(r"\[([0-9]+),([0-9]+)\]\[([0-9]+),([0-9]+)\]", scrollable.get("bounds", "")).groups()))
                command("shell", "input", "swipe", (bounds[0] + bounds[2]) // 2, bounds[3] - 30, (bounds[0] + bounds[2]) // 2, bounds[1] + 30, 300)
                hierarchy = tree(step + "-scrolled"); matches = [node for node in hierarchy.iter("node") if node.get("package") == PACKAGE and node.get("content-desc") == description and node.get("enabled") == "true" and node.get("clickable") == "true"]
        need(len(matches) == 1, "Missing unique actionable QA control: " + description)
        match = re.fullmatch(r"\[([0-9]+),([0-9]+)\]\[([0-9]+),([0-9]+)\]", matches[0].get("bounds", "")); need(match, "Fresh UI bounds required")
        left, top, right, bottom = map(int, match.groups()); need(right > left and bottom > top, "Nonempty UI bounds required")
        command("shell", "input", "tap", (left + right) // 2, (top + bottom) // 2)
    def save_cancel(number):
        nonlocal visits
        tap("qa_production_save", "save" + str(number))
        report(lambda row: row["launches"] == number and row.get("picker_or_copy_active") is True)
        tree("documents" + str(number), documents=True); visits += 1
        if number == 2:
            proof["observations"]["pending_recreated"] = report(lambda row: row.get("pending_recreated", 0) >= 1
                and row.get("pending_restored_active") is True and row.get("picker_or_copy_active") is True)
            tree("documents2-recreated", documents=True)
        command("shell", "input", "keyevent", "4")
        value = report(lambda row: row["cancelled"] == number and row.get("can_save") is True and row.get("picker_or_copy_active") is False)
        tree("cancel" + str(number)); proof["observations"]["cancel" + str(number)] = value
    try:
        proof["selinux_enforcement"]["before"] = command("shell", "getenforce").decode().strip(); need(proof["selinux_enforcement"]["before"] == "Enforcing", "Enforcing SELinux required")
        command("install", "-r", apk, limit=90); command("shell", "am", "force-stop", PACKAGE)
        need(command("shell", "pm", "clear", PACKAGE).strip() == b"Success", "Fresh QA app data required")
        identity = command("shell", "cmd", "package", "list", "packages", "-U", PACKAGE).decode().strip(); match = re.fullmatch(r"package:" + re.escape(PACKAGE) + r" uid:([0-9]+)", identity); need(match, "Package UID required"); proof["package_uid"] = int(match[1])
        command("shell", "am", "start", "-W", "-n", ACTIVITY, "--es", "challenge", challenge, "--es", "mode", "fresh")
        proof["observations"]["initial"] = report(lambda row: row["completed_outputs"] == 0 and row["launches"] == 0)
        tap("qa_complete", "initial")
        report(lambda row: row["completed_outputs"] == 1 and row.get("can_save") is True); time.sleep(0.8)
        proof["observations"]["completed"] = report(lambda row: row["completed_outputs"] == 1 and row.get("can_save") is True)
        tree("completed"); save_cancel(1)
        old_creations = proof["observations"]["cancel1"]["creations"]; tap("qa_recreate", "before-recreate")
        proof["observations"]["recreated"] = report(lambda row: row["creations"] > old_creations and row.get("can_save") is True)
        tree("recreated"); save_cancel(2)
        command("shell", "am", "force-stop", PACKAGE)
        command("shell", "am", "start", "-W", "-n", ACTIVITY, "--es", "challenge", challenge, "--es", "mode", "cold")
        proof["observations"]["cold"] = report(lambda row: row["boots"] >= 2 and row.get("can_save") is True and row.get("launch_mode") == "cold")
        tree("cold"); save_cancel(3); tap("qa_finish", "before-finish")
        proof["observations"]["terminal"] = report(lambda row: row.get("phase") == "completed")
        tree("terminal"); proof["selinux_enforcement"]["after"] = command("shell", "getenforce").decode().strip()
        need(sources(root) == built["source_sha256"], "Source changed during actual UI QA")
        proof.update(status="PASS_ANDROID_SYNTHETIC_SAVE_UI_ONLY", actual_android_save_ui_verified=True,
                     documents_ui_visits=visits, ui_taps_from_fresh_bounds=True,
                     cases=[{"name": name, "required": True, "status": "passed"} for name in sorted(REQUIRED)])
        validate_runtime_report(proof, built)
    except Exception as problem:
        error = problem; proof.update(status="FAILED", actual_android_save_ui_verified=False, error_type=type(problem).__name__, error=str(problem)[:2000])
    finally:
        try:
            pid = command("shell", "pidof", "-s", PACKAGE, maximum=128, limit=3).strip().decode(); need(re.fullmatch(r"[0-9]+", pid), "Own PID required")
            log = command("logcat", "-d", "--pid", pid, "-t", "200", maximum=256 * 1024, limit=5); (directory / "own-pid-logcat.txt").write_bytes(log)
        except Exception as problem: proof["logcat_error_type"] = type(problem).__name__
        try: command("shell", "am", "force-stop", PACKAGE, limit=5)
        except Exception as problem: proof["stop_error_type"] = type(problem).__name__
        (directory / "runtime-report.json").write_text(json.dumps(proof, indent=2) + "\n")
    print(json.dumps(proof, indent=2))
    if error is not None: raise ValueError("Actual Android synthetic Save UI QA failed; see retained report and UI evidence") from None


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--android-sdk", type=Path); parser.add_argument("--run-device", action="store_true"); parser.add_argument("--require-committed", action="store_true")
    parser.add_argument("--serial", default="emulator-5554"); parser.add_argument("--timeout", type=int, default=240); args = parser.parse_args()
    sdk = args.android_sdk or (Path(os.environ["ANDROID_HOME"]) if os.environ.get("ANDROID_HOME") else None)
    if args.run_device: run_device(args.output_directory.absolute(), sdk, args.serial, args.timeout, require_committed=args.require_committed)
    else:
        need(sdk is not None, "Android SDK required"); build(args.output_directory.absolute(), sdk, require_committed=args.require_committed)


if __name__ == "__main__": main()
