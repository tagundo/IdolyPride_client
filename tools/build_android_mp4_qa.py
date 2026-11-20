#!/usr/bin/env python3
"""Build/run an isolated Android encoder probe; never load the game or its JNI.

The APK uses only current production Java codec sources and synthetic media.
Successful packaging is not a codec pass. --run-device requires decoded media,
exact timing, AAC impulse/edit-list checks and terminal ownership tests.
"""
from __future__ import annotations

import argparse
from array import array
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import xml.etree.ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "game.qualiarts.idolypride.mp4qa"
ACTIVITY = PACKAGE + "/.CodecProbeActivity"
APK_NAME = "Idoly-MP4-Codec-QA.apk"
CERT = "aa4e9346ff9e542b263b70254df3e25b79211df16161208a3b509c4f113facfc"
MANIFEST = "android-unified/mp4-qa/AndroidManifest.xml"
JAVA = "android-unified/src/main/java/game/qualiarts/idolypride/localserver/mp4"
PROBE = "android-unified/mp4-qa/src/game/qualiarts/idolypride/mp4qa/CodecProbeActivity.java"
ANDROID = "{http://schemas.android.com/apk/res/android}"
REQUIRED = {"avc30", "avc60000_1001", "cancel", "no_overwrite"}
MIB = 1024 * 1024
JAVA_FLAGS = ("-Xmx512m", "-XX:MaxMetaspaceSize=256m", "-XX:ReservedCodeCacheSize=64m",
              "-XX:+UseSerialGC", "-XX:ActiveProcessorCount=1")


def need(value, message):
    if not value:
        raise ValueError(message)


def sha(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def regular(path, maximum=64 * MIB):
    path = Path(path)
    info = path.lstat()
    need(stat.S_ISREG(info.st_mode) and 0 < info.st_size <= maximum, "Expected a bounded regular file")
    return path


def validate_manifest(raw):
    manifest = ET.fromstring(raw)
    need(manifest.tag == "manifest" and manifest.get("package") == PACKAGE, "Unexpected QA package")
    need(not manifest.findall("uses-permission") and not manifest.findall("instrumentation"), "QA must not request permissions or instrumentation")
    sdk = manifest.find("uses-sdk")
    need(sdk is not None and sdk.get(ANDROID + "minSdkVersion") == "30"
         and sdk.get(ANDROID + "targetSdkVersion") == "35", "Unexpected QA SDK bounds")
    applications = manifest.findall("application")
    need(len(applications) == 1, "Expected one QA application")
    app = applications[0]
    need(app.get(ANDROID + "debuggable") == "true" and app.get(ANDROID + "allowBackup") == "false"
         and len(list(app)) == 1 and list(app)[0].tag == "activity", "Unexpected QA app scope")
    activity = app.find("activity")
    need(activity.get(ANDROID + "name") == ".CodecProbeActivity" and activity.get(ANDROID + "exported") == "true",
         "Unexpected QA activity")
    actions = [item.get(ANDROID + "name") for item in activity.findall("intent-filter/action")]
    categories = [item.get(ANDROID + "name") for item in activity.findall("intent-filter/category")]
    need(actions == ["android.intent.action.MAIN"] and categories == ["android.intent.category.LAUNCHER"], "Unexpected QA launcher")


def sources(root):
    source_paths = sorted((root / JAVA).glob("*.java")) + [root / PROBE, root / MANIFEST,
                                                                root / "tools/build_android_mp4_qa.py"]
    need(4 <= len(source_paths) <= 32 and any(p.name == "OfflineMp4Encoder.java" for p in source_paths), "Production codec sources missing")
    rows = {p.relative_to(root).as_posix(): {"bytes": regular(p, MIB).stat().st_size, "sha256": sha(p)} for p in source_paths}
    need(sum(row["bytes"] for row in rows.values()) <= 8 * MIB, "QA source inventory exceeds bound")
    validate_manifest((root / MANIFEST).read_bytes())
    return source_paths, rows


def clean_java_environment():
    env = dict(os.environ)
    for name in ("JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "JDK_JAVA_OPTIONS", "CLASSPATH", "JAVA_OPTS", "GRADLE_OPTS"):
        env.pop(name, None)
    return env


def run_logged(command, log, *, timeout=120):
    with log.open("ab") as output:
        output.write(("\nCOMMAND: " + str(command[0]) + "\n").encode())
        result = subprocess.run(list(map(str, command)), stdin=subprocess.DEVNULL, stdout=output,
                                stderr=subprocess.STDOUT, env=clean_java_environment(), timeout=timeout)
    need(log.stat().st_size <= 4 * MIB, "Build log exceeded its bound")
    need(result.returncode == 0, "Build tool failed; see build.log")


def build(directory, sdk, root=ROOT):
    directory = directory.absolute()
    need(not directory.exists() and not directory.is_symlink(), "Use a fresh QA output directory")
    directory.mkdir(mode=0o700, parents=True)
    log = directory / "build.log"
    files, before = sources(root)
    sdk = sdk.resolve(strict=True)
    tools = sdk / "build-tools/34.0.0"
    android = regular(sdk / "platforms/android-34/android.jar")
    java_home = Path(os.environ["JAVA_HOME"]) / "bin" if os.environ.get("JAVA_HOME") else None
    java = (java_home / "java" if java_home else Path(shutil.which("java") or "")).resolve(strict=True)
    javac = (java_home / "javac" if java_home else Path(shutil.which("javac") or "")).resolve(strict=True)
    for tool in (java, javac, tools / "aapt2", tools / "zipalign", tools / "lib/d8.jar", tools / "lib/apksigner.jar"):
        regular(tool, 128 * MIB)
    key = regular(root / "android-diagnostics/local-diagnostics-development.keystore", MIB)
    commit = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    need(re.fullmatch(r"[0-9a-f]{40}", commit), "Exact checkout source required")
    committed = True
    for name, row in before.items():
        result = subprocess.run(["git", "-C", str(root), "show", commit + ":" + name],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=15)
        if result.returncode or hashlib.sha256(result.stdout).hexdigest() != row["sha256"]:
            committed = False
    with tempfile.TemporaryDirectory(prefix="build-", dir=directory) as temporary:
        work = Path(temporary)
        classes, dex = work / "classes", work / "dex"
        classes.mkdir(); dex.mkdir()
        java_files = [p for p in files if p.suffix == ".java"]
        run_logged([javac, *["-J" + flag for flag in JAVA_FLAGS], "--release", "17", "-encoding", "UTF-8",
                    "-classpath", android, "-d", classes, *java_files], log)
        class_files = sorted(classes.rglob("*.class"))
        need(class_files and all(p.relative_to(classes).as_posix().startswith((PACKAGE.replace(".", "/") + "/",
             "game/qualiarts/idolypride/localserver/mp4/")) for p in class_files), "Unexpected compiled QA class namespace")
        run_logged([java, *JAVA_FLAGS, "-cp", tools / "lib/d8.jar", "com.android.tools.r8.D8", "--release",
                    "--min-api", "30", "--lib", android, "--output", dex, *class_files], log)
        need({p.name for p in dex.iterdir()} == {"classes.dex"}, "Unexpected QA DEX inventory")
        unsigned, aligned = work / "unsigned.apk", work / "aligned.apk"
        run_logged([tools / "aapt2", "link", "--manifest", root / MANIFEST, "-I", android,
                    "--min-sdk-version", "30", "--target-sdk-version", "35", "-o", unsigned], log)
        with ZipFile(unsigned, "a", compression=ZIP_DEFLATED) as archive:
            need("classes.dex" not in archive.namelist() and not any(n.startswith(("lib/", "assets/")) for n in archive.namelist()),
                 "Standalone probe unexpectedly includes game/native/assets")
            archive.write(dex / "classes.dex", "classes.dex")
        run_logged([tools / "zipalign", "-f", "4", unsigned, aligned], log)
        password = work / "public-development-password.txt"
        password.write_text("android\n"); password.chmod(0o600)
        run_logged([java, *JAVA_FLAGS, "-jar", tools / "lib/apksigner.jar", "sign", "--ks", key,
                    "--ks-key-alias", "idoly-diagnostics-public", "--ks-pass", "file:" + str(password),
                    "--v4-signing-enabled", "false", aligned], log)
        verification = subprocess.check_output([str(java), *JAVA_FLAGS, "-jar", str(tools / "lib/apksigner.jar"),
            "verify", "--verbose", "--print-certs", str(aligned)], env=clean_java_environment(), timeout=90, text=True)
        need("Signer #1 certificate SHA-256 digest: " + CERT in verification, "QA development certificate differs")
        (directory / "signature.txt").write_text(verification)
        run_logged([tools / "zipalign", "-c", "4", aligned], log)
        badging = subprocess.check_output([str(tools / "aapt2"), "dump", "badging", str(aligned)], text=True, timeout=30)
        need("package: name='" + PACKAGE + "'" in badging and "sdkVersion:'30'" in badging
             and "targetSdkVersion:'35'" in badging and "application-debuggable" in badging
             and "launchable-activity: name='" + PACKAGE + ".CodecProbeActivity'" in badging, "Signed QA manifest identity differs")
        (directory / "badging.txt").write_text(badging)
        need(sources(root)[1] == before, "QA sources changed during build")
        apk = directory / APK_NAME
        need(aligned.stat().st_size <= 8 * MIB, "Standalone QA APK exceeded bound")
        os.link(aligned, apk)
    report = {"schema": 1, "status": "BUILT_NOT_RUNTIME_VALIDATED", "source_commit": commit,
        "working_tree_snapshot": not committed,
        "package": PACKAGE, "source_sha256": before, "source_unchanged_during_build": True,
        "certificate_sha256": CERT, "apk_bytes": apk.stat().st_size, "apk_sha256": sha(apk),
        "codec_sources": "current production Java offline encoder", "game_or_JNI_loaded": False,
        "actual_game_mv_verified": False, "actual_device_codec_verified": False}
    (directory / "build-report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


def validate_runtime_report(value):
    need(type(value) is dict and value.get("schema") == 1 and value.get("package") == PACKAGE
         and value.get("phase") == "completed" and value.get("passed") is True and not value.get("error"), "Android codec probe did not complete successfully")
    cases = value.get("cases")
    need(type(cases) is list and all(type(case) is dict and type(case.get("name")) is str for case in cases), "Missing codec cases")
    by_name = {case["name"]: case for case in cases}
    need(len(by_name) == len(cases) and set(by_name) == REQUIRED | {"hevc30"}, "Unexpected, duplicate or missing codec cases")
    for name, case in by_name.items():
        need(case.get("required") is (name in REQUIRED), "Codec case requirement changed")
        if name == "hevc30" and case.get("status") == "unsupported":
            need(case.get("capability_checked") is True and case.get("reason") == "device_has_no_supported_hevc_encoder",
                 "HEVC was skipped without a capability result")
            continue
        need(case.get("status") == "passed", "A required or supported codec case failed")
        if name in ("avc30", "avc60000_1001", "hevc30"):
            frames = 60 if name == "avc60000_1001" else 30
            numerator, denominator = (60000, 1001) if name == "avc60000_1001" else (30, 1)
            need(type(case.get("frames")) is int and case["frames"] == frames
                 and type(case.get("decoded_video_frames")) is int and case["decoded_video_frames"] == frames
                 and case.get("fps_numerator") == numerator
                 and case.get("fps_denominator") == denominator and case.get("ordered_video_pts") is True
                 and case.get("corner_pixels_verified") is True and case.get("source_preserved") is True
                 and case.get("file") == name + "/complete.mp4", "Decoded video/PTS/pixel/source proof differs")
            audio, encoder = case.get("audio", {}), case.get("encoder", {})
            need(type(audio) is dict and type(encoder) is dict and encoder.get("phase") == "completed"
                 and type(audio.get("aac_packets")) is int and audio["aac_packets"] > 0
                 and type(audio.get("priming_samples")) is int and audio["priming_samples"] >= 0
                 and audio.get("raw_decoded_frames") == audio["aac_packets"] * 1024
                 and audio["raw_decoded_frames"] >= 48000 + audio["priming_samples"]
                 and audio.get("logical_frames") == 48000 and audio.get("impulses_verified") is True
                 and audio.get("edit_list_exact") is True and encoder.get("aac_priming_samples") == audio["priming_samples"]
                 and encoder.get("audio_packets") == audio["aac_packets"], "Decoded AAC clocks, impulses or exact edit list differs")
        elif name == "cancel":
            need(all(case.get(key) is True for key in ("terminal_cleanup", "source_preserved", "output_absent")), "Cancellation ownership proof differs")
        elif name == "no_overwrite":
            need(case.get("sentinel_preserved") is True and case.get("partial_absent") is True, "Existing output ownership proof differs")
    return value


def extract_archive(archive, destination):
    regular(archive, 64 * MIB)
    need(not destination.exists() and not destination.is_symlink(), "Fresh device evidence directory required")
    with tarfile.open(archive, "r:") as source:
        members = source.getmembers()
        need(len(members) <= 128 and len({m.name for m in members}) == len(members), "Unexpected evidence archive inventory")
        total = 0
        for member in members:
            path = PurePosixPath(member.name)
            need(not path.is_absolute() and path.parts and path.parts[0] == "mp4-qa" and ".." not in path.parts
                 and "\\" not in member.name and (member.isfile() or member.isdir())
                 and 0 <= member.size <= 16 * MIB, "Unsafe codec evidence member")
            total += member.size
        need(total <= 64 * MIB, "Codec evidence archive exceeds bound")
        destination.mkdir()
        for member in members:
            target = destination.joinpath(*PurePosixPath(member.name).parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.extractfile(member) as incoming, target.open("xb") as output:
                    shutil.copyfileobj(incoming, output, 64 * 1024)


def validate_audio_presentation(metadata):
    streams = metadata.get("streams", [])
    need(len(streams) == 1, "Expected one independent AAC stream")
    stream = streams[0]
    need(type(stream.get("index")) is int and stream["index"] >= 0
         and stream.get("codec_name") == "aac" and stream.get("sample_rate") == "48000"
         and stream.get("channels") == 2 and stream.get("time_base") == "1/48000"
         and type(stream.get("start_pts")) is int and stream["start_pts"] == 0
         and type(stream.get("duration_ts")) is int and stream["duration_ts"] == 48000,
         "Independent AAC format or exact presentation interval differs")
    packets = metadata.get("packets", [])
    need(1 <= len(packets) <= 64, "Independent AAC packet count exceeds the bounded clip")
    previous_end = None
    priming = None
    for index, packet in enumerate(packets):
        need(type(packet.get("stream_index")) is int and packet["stream_index"] == stream["index"]
             and all(type(packet.get(key)) is int for key in ("pts", "dts", "duration")),
             "Independent AAC packet timing is missing")
        pts, dts, duration = (packet[key] for key in ("pts", "dts", "duration"))
        need(pts == dts and 0 < duration <= 1024
             and (previous_end is None or dts == previous_end),
             "Independent AAC packet clock has a gap, overlap or composition offset")
        if index < len(packets) - 1:
            need(duration == 1024, "Independent AAC contains a shortened interior packet")
        side = packet.get("side_data_list", [])
        if index == 0:
            need(-8192 <= dts <= 0, "Independent AAC priming is outside the supported range")
            priming = -dts
            if priming:
                need(len(side) == 1 and side[0].get("side_data_type") == "Skip Samples"
                     and side[0].get("skip_samples") == priming and side[0].get("discard_padding") == 0,
                     "Independent AAC edit priming differs from the packet clock")
            else:
                need(not side, "Unexpected zero-origin AAC edit data")
        else:
            need(not side, "Unexpected extra AAC edit or discard data")
        previous_end = dts + duration
    need(previous_end == 48000, "Independent AAC last packet does not end at the exact presentation boundary")
    return {"presentation_verified": True, "time_base": "1/48000", "start_pts": 0,
            "duration_ts": 48000, "last_packet_end": previous_end,
            "packet_count": len(packets), "priming_samples": priming}


def validate_independent_pcm(raw, presentation=None):
    need(len(raw) % 8 == 0, "Independent AAC decoder returned an incomplete stereo sample frame")
    raw_frames = len(raw) // 8
    if presentation is None:
        need(raw_frames == 48000, "Independent AAC decoder did not present exactly 48000 stereo sample frames")
    else:
        need(presentation.get("presentation_verified") is True and presentation.get("duration_ts") == 48000
             and presentation.get("last_packet_end") == 48000, "Verify the container end before applying decoder padding")
        # AAC decoders emit complete 1024-sample blocks. The MP4 presentation
        # ends inside its last block; only that independently verified tail is
        # excluded. Missing samples or another full decoded block still fail.
        need(48000 <= raw_frames <= 48000 + 1023, "Independent AAC decoder has missing samples or extra AAC blocks")
    data = array("f")
    data.frombytes(raw)
    if sys.byteorder != "little":
        data.byteswap()
    need(all(math.isfinite(value) for value in data), "Independent AAC decoder returned nonfinite samples")
    peaks = []
    for channel in range(2):
        positive = max(range(48000), key=lambda index: data[index * 2 + channel])
        negative = min(range(48000), key=lambda index: data[index * 2 + channel])
        need(abs(positive - 8000) <= 1 and abs(negative - 32000) <= 1
             and data[positive * 2 + channel] > 0.03 and data[negative * 2 + channel] < -0.03,
             "Independent AAC impulse timing, polarity or channel content differs")
        peaks.append({"positive_sample": positive, "negative_sample": negative})
    return {"presented_sample_frames": 48000, "raw_decoded_frames": raw_frames,
            "discarded_tail_frames": raw_frames - 48000, "channels": 2, "sample_rate": 48000,
            "impulses_verified": True, "channel_peaks": peaks}


def independent_audio(mp4, directory):
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    need(ffmpeg and ffprobe, "FFmpeg and ffprobe are required for independent AAC presentation checks")
    metadata_path = directory / (mp4.parent.name + "-ffprobe-audio.json")
    need(not metadata_path.exists(), "Fresh independent metadata output required")
    with metadata_path.open("xb") as output:
        subprocess.run([ffprobe, "-v", "error", "-select_streams", "a", "-show_streams", "-show_packets",
            "-of", "json", str(mp4)], stdout=output, stderr=subprocess.DEVNULL, check=True, timeout=30)
    regular(metadata_path, MIB)
    presentation = validate_audio_presentation(json.loads(metadata_path.read_text()))
    destination = directory / (mp4.parent.name + "-ffmpeg-decoded.f32")
    need(not destination.exists(), "Fresh independent PCM output required")
    subprocess.run([ffmpeg, "-nostdin", "-v", "error", "-i", str(mp4), "-map", "0:a:0", "-vn",
        "-f", "f32le", "-acodec", "pcm_f32le", str(destination)], check=True, timeout=60,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    regular(destination, MIB)
    raw = destination.read_bytes()
    return {**validate_independent_pcm(raw, presentation),
            "verified_container_duration": presentation,
            "decoder": "FFmpeg raw AAC; logical samples use the verified MP4 presentation end, without resampling or remixing",
            "decoded_sha256": sha(destination), "metadata_sha256": sha(metadata_path),
            "presented_pcm_sha256": hashlib.sha256(raw[:48000 * 8]).hexdigest()}


def run_device(directory, sdk, serial, timeout, root=ROOT):
    need(re.fullmatch(r"emulator-[0-9]+", serial) and 1 <= timeout <= 900, "Bounded emulator probe required")
    regular(directory / "build-report.json", MIB)
    build_report = json.loads((directory / "build-report.json").read_bytes())
    apk = regular(directory / APK_NAME, 8 * MIB)
    need(build_report.get("schema") == 1 and build_report.get("status") == "BUILT_NOT_RUNTIME_VALIDATED"
         and build_report.get("package") == PACKAGE and build_report.get("certificate_sha256") == CERT
         and build_report.get("apk_bytes") == apk.stat().st_size and build_report.get("apk_sha256") == sha(apk)
         and build_report.get("source_sha256") == sources(root)[1], "Built QA APK/source identity differs")
    report_file = directory / "runtime-report.json"
    need(not report_file.exists() and not (directory / "device-output").exists(), "Use fresh runtime evidence paths")
    adb = sdk / "platform-tools/adb" if sdk else Path(shutil.which("adb") or "")
    regular(adb)
    need(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg and ffprobe are required for cross-decoder QA")
    base = [str(adb), "-s", serial]
    proof = {"schema": 1, "status": "FAILED", "source_commit": build_report["source_commit"],
             "apk_sha256": build_report["apk_sha256"], "package": PACKAGE, "serial": serial,
             "actual_game_mv_verified": False, "actual_android_emulator_codec_verified": False}
    error = None
    terminal = None
    try:
        def command(*args, limit=30):
            result = subprocess.run([*base, *args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=limit)
            need(len(result.stdout) <= MIB and result.returncode == 0, "ADB probe command failed")
            return result.stdout
        command("install", "-r", str(apk), limit=90)
        command("shell", "am", "force-stop", PACKAGE)
        need(command("shell", "pm", "clear", PACKAGE).strip() == b"Success", "QA app data was not reset")
        launch = command("shell", "am", "start", "-W", "-n", ACTIVITY)
        (directory / "launch.txt").write_bytes(launch)
        need(b"Status: ok" in launch and b"Error:" not in launch, "QA activity did not launch")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = subprocess.run([*base, "shell", "run-as", PACKAGE, "cat", "files/mp4-qa/report.json"],
                                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10)
            need(len(result.stdout) <= MIB, "Android codec report exceeded bound")
            if result.returncode == 0:
                try:
                    value = json.loads(result.stdout)
                except (ValueError, UnicodeError):
                    value = None
                if type(value) is dict and value.get("phase") in ("completed", "failed"):
                    terminal = value
                    break
            time.sleep(1)
        need(terminal is not None, "Android codec probe did not finish before deadline")
        validate_runtime_report(terminal)
    except Exception as problem:
        error = problem
        proof["error_type"] = type(problem).__name__
        proof["error"] = str(problem)[:2000]
    finally:
        if terminal is not None:
            (directory / "terminal-report.json").write_text(json.dumps(terminal, indent=2) + "\n")
        try:
            with (directory / "logcat.txt").open("xb") as log:
                subprocess.run([*base, "logcat", "-d", "-t", "600"], stdout=log, stderr=subprocess.DEVNULL, timeout=20, check=False)
        except Exception as problem:
            proof["logcat_error_type"] = type(problem).__name__
        try:
            archive = directory / "device-output.tar"
            with archive.open("xb") as output:
                subprocess.run([*base, "exec-out", "run-as", PACKAGE, "tar", "-C", "files", "-cf", "-", "mp4-qa"],
                               stdout=output, stderr=subprocess.DEVNULL, check=True, timeout=45)
            extract_archive(archive, directory / "device-output")
            copied = json.loads((directory / "device-output/mp4-qa/report.json").read_bytes())
            need(copied == terminal, "Collected report differs from the observed terminal result")
            if error is None:
                validate_runtime_report(copied)
                outputs = {}
                for case in copied["cases"]:
                    if case["status"] == "passed" and case["name"] in ("avc30", "avc60000_1001", "hevc30"):
                        path = regular(directory / "device-output/mp4-qa" / case["file"], 16 * MIB)
                        outputs[case["file"]] = {"bytes": path.stat().st_size, "sha256": sha(path)}
                        outputs[case["file"]]["independent_audio"] = independent_audio(path, directory)
                proof.update(status="PASS_SYNTHETIC_CODEC_ONLY", actual_android_emulator_codec_verified=True,
                             result=copied, mp4_sha256=outputs)
        except Exception as problem:
            proof["collection_error_type"] = type(problem).__name__
            proof["collection_error"] = str(problem)[:2048]
            if error is None:
                error = problem
        try:
            subprocess.run([*base, "shell", "am", "force-stop", PACKAGE], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15, check=False)
        except Exception as problem:
            proof["stop_error_type"] = type(problem).__name__
        report_file.write_text(json.dumps(proof, indent=2) + "\n")
    print(json.dumps(proof, indent=2))
    if error is not None:
        raise ValueError("Android codec QA failed; see runtime-report.json and retained evidence") from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--android-sdk", type=Path)
    parser.add_argument("--run-device", action="store_true")
    parser.add_argument("--serial", default="emulator-5554")
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()
    sdk = args.android_sdk or (Path(os.environ["ANDROID_HOME"]) if os.environ.get("ANDROID_HOME") else None)
    if args.run_device:
        run_device(args.output_directory.absolute(), sdk, args.serial, args.timeout)
    else:
        need(sdk is not None, "Android SDK path required")
        build(args.output_directory, sdk)


if __name__ == "__main__":
    main()
