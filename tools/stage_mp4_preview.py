#!/usr/bin/env python3
"""Verify current-run MP4 candidates and stage a new draft; never publish.

Artifact IDs/digests come only from this workflow's successful producer jobs.
Drafts are found by bounded release enumeration and assets uploaded by checked
release ID, never by a tag lookup or an external upload URL.
"""
from __future__ import annotations
import argparse
from dataclasses import dataclass
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import plistlib
import re
import stat
import subprocess
import sys
import threading
import time
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
REPO = "tagundo/IdolyPride_client"
WORKFLOW = ".github/workflows/build-mp4-preview.yml"
CODEC_WORKFLOW = ".github/workflows/verify-mp4-codecs.yml"
BRANCH = "refs/heads/feat/ios-unified-server"
VERSION = "2026.11.21.10"
APK = "IdolyPride-Unified-" + VERSION + "-prototype.apk"
APK_REPORT = APK.removesuffix(".apk") + ".provenance.json"
VERIFICATION = "MP4-PREVIEW-VERIFICATION.json"
ANDROID_VERIFICATION = "ANDROID-MP4-PREVIEW-VERIFICATION.json"
MIB = 1024 * 1024
MAX_FILE = 768 * MIB
CODEC_WAIT = 2400
MP4_NATIVE = {"client-presentation/native/" + name for name in (
    "mp4_encoder_api.h", "mp4_android_encoder.hpp", "mp4_game_adapter.hpp", "mp4_game_bindings.hpp", "mp4_runtime.hpp",
    "mp4_session_api.h", "mp4_queue.hpp", "mp4_queue_runtime.hpp", "mp4_queue_cleanup.hpp", "mp4_selection_capture.hpp",
    "mp4_replay.hpp", "mp4_replay_profile.hpp", "mp4_replay_factories.hpp", "mp4_output_policy.hpp",
    "mp4_controller_profile.hpp", "mp4_type_descriptor.hpp",
    "mp4_photography_replay_factory.hpp", "mp4_photography_replay_profile.hpp",
    "mp4_camera_owner.hpp", "mp4_timeline_camera.hpp", "mp4_timeline_audio.hpp",
    "shared_cache_core.hpp", "shared_cache_hooks.hpp")}
# Android's actual builder hashes JSON generator evidence; Darwin's compiled
# source receipt includes headers only. Keep these profile pins out of MP4_NATIVE.
MP4_ANDROID_PROFILES = {"client-presentation/native/" + name for name in (
    "mp4_photography_replay_android_profile.json", "mp4_photography_replay_ios_profile.json", "mp4_camera_owner_profile.json")}
MP4_JAVA = {"android-server/app/src/main/java/game/qualiarts/idolypride/localserver/UnifiedMP4Export.java",
            "android-server/app/src/main/java/game/qualiarts/idolypride/localserver/MainActivity.java",
            "android-server/app/src/main/java/game/qualiarts/idolypride/localserver/ServerService.java",
            "android-server/app/src/main/java/game/qualiarts/idolypride/localserver/PreviousProcessExits.java",
            "android-server/app/src/main/java/game/qualiarts/idolypride/localserver/UnifiedMP4Background.java",
            "android-server/app/src/main/java/game/qualiarts/idolypride/localserver/UnifiedMP4Service.java",
            "android-server/app/src/main/java/game/qualiarts/idolypride/localserver/Mp4QueueUiState.java",
            "android-server/app/src/main/java/game/qualiarts/idolypride/localserver/Mp4TitleCatalog.java",
            "android-server/app/src/main/java/game/qualiarts/idolypride/localserver/Mp4ExportSettings.java",
            "android-server/app/src/main/python/android_server_runtime.py",
            "src/idoly_local/mp4_audio_broker.py", "src/idoly_local/mp4_audio_bundle.py", "src/idoly_local/mp4_export_library.py", "src/idoly_local/mp4_titles.py",
            "tools/refresh_korean_translation_bundle.py", "data/latest-korean-translations-pin.json",
            "tools/korean_server_data_pin.py", "data/korean-master-data-pin.json"}


def need(value, message):
    if not value:
        raise ValueError(message)


def source_sha(source):
    need(type(source) is str and re.fullmatch(r"[0-9a-f]{40}", source), "exact_source_required")
    return source


def tag(source, *, android_only=False, producer_identity=None):
    result = ("android-mp4-preview-" if android_only else "mp4-preview-") + VERSION + "-" + source_sha(source)[:7]
    if android_only:
        android_producer_marker(producer_identity)
        result += "-r" + str(producer_identity[0]) + "-a" + str(producer_identity[1])
    return result


def ipa_name(source):
    return "IdolyPride-Unified-" + VERSION + "-prototype-" + source_sha(source)[:12] + "-iOS.ipa"


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def regular(path, maximum=MAX_FILE):
    info = path.lstat()
    need(stat.S_ISREG(info.st_mode) and 0 < info.st_size <= maximum, "regular_file_bound")
    return info


def pairs(items):
    result = {}
    for key, value in items:
        need(key not in result, "duplicate_json_key")
        result[key] = value
    return result


def decode(raw):
    def reject(_):
        raise ValueError("nonfinite_json")
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=reject)


def read(path):
    regular(path, 8 * MIB)
    return decode(path.read_bytes())


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    spec.loader.exec_module(result)
    return result


def source_pins(values, base, required):
    need(type(values) is dict and required <= values.keys() and len(values) <= 1024, "source_closure_missing")
    for name, digest in values.items():
        need(type(name) is str and "\\" not in name and "\0" not in name
             and not name.startswith("/") and type(digest) is str and re.fullmatch(r"[0-9a-f]{64}", digest), "source_pin_invalid")
        path = base / name
        need(path.resolve().is_relative_to(ROOT.resolve()), "source_pin_escapes_checkout")
        regular(path, 2 * MIB)
        need(sha(path) == digest, "source_bytes_changed")


def mp4_native_sources(values, *, android=False):
    required = MP4_NATIVE
    if android:
        required = required | MP4_ANDROID_PROFILES | {"client-presentation/native/mp4_android_session.hpp"}
    source_pins(values, ROOT, required)


def korean_translation_proof(report, platform):
    guard = module("mp4_preview_translation_guard", ROOT / "tools/refresh_korean_translation_bundle.py")
    pin = guard.pins()
    expected = pin["platforms"][platform]
    need(type(report) is dict and type(report.get("schema")) is int and report["schema"] == 1 and report.get("platform") == platform
         and report.get("source") == pin["source"]
         and report.get("source_archive") == {key: pin["archive"][key] for key in ("bytes", "sha256")}
         and {key: report.get(key) for key in ("bytes", "sha256", "manifest_sha256")} == expected["output"]
         and type(report.get("coverage")) is dict and report["coverage"].get("translated") == pin["adv_count"]
         and report.get("image_count") == expected["image_count"]
         and report.get("preserved_image_bytes_verified") is True and report.get("new_images_generated") is False,
         "korean_translation_refresh_differs")
    return {key: expected["output"][key] for key in ("bytes", "sha256")}


def android_files(folder, source):
    guard = module("mp4_preview_android_guard", ROOT / "tools/stage_android_windowing_preview.py")
    guard.APK, guard.REPORT = APK, APK_REPORT
    paths = guard.apk_files(folder, source)
    proof = read(paths[1])
    native = proof["native_addon_build"]
    mp4_native_sources(native.get("source_sha256"), android=True)
    exports = native.get("jni_exports", [])
    need(type(exports) is list and {"Java_game_qualiarts_idolypride_localserver_UnifiedMP4Export_native" + method
        for method in ("Configure", "Start", "Status", "Cancel", "Ready", "Suspend", "Resume",
                       "QueueConfigure", "QueueEnqueue", "QueueRun", "QueuePause", "QueueResume", "QueueCommand", "QueueStatus")} <= set(exports), "mp4_native_exports_missing")
    rows = {row["path"]: row["sha256"] for row in proof["source_files"]}
    need(MP4_JAVA <= rows.keys(), "mp4_app_sources_missing")
    source_pins({name: rows[name] for name in MP4_JAVA}, ROOT, MP4_JAVA)
    korean = module("mp4_preview_android_korean_guard", ROOT / "tools/korean_server_data_pin.py")
    korean.verify_refresh_proof(proof.get("korean_master_refresh"))
    translation = korean_translation_proof(proof.get("korean_translation_refresh"), "android")
    with ZipFile(paths[0]) as archive:
        raw = archive.read("lib/arm64-v8a/libidoly_presentation.so")
        need(hashlib.sha256(raw).hexdigest() == native["sha256"], "apk_native_bytes_differ")
        for name, expected in (("assets/ServerData.zip", korean.output_pin()),
                               ("assets/bundledTranslations.zip", translation)):
            need(proof.get("runtime_assets", {}).get(name) == expected
                 and archive.getinfo(name).file_size == expected["bytes"], "apk_korean_asset_pin_differs")
            with archive.open(name) as incoming:
                need(hashlib.file_digest(incoming, "sha256").hexdigest() == expected["sha256"],
                     "apk_korean_asset_bytes_differ")
    return paths, {"windowing": proof["windowing"], "languages": proof["marker"]["languages"],
        "same_process": True, "shared_cache_hooks": native["shared_cache_hooks"], "mp4_source_bound": True,
        "korean_translation_revision": korean.REVISION, "server_data_sha256": korean.output_pin()["sha256"],
        "translation_sha256": translation["sha256"]}


def android_checksums(folder, source):
    paths, _ = android_files(folder, source)
    raw = "".join(f"{sha(path)}  {path.name}\n" for path in sorted(paths))
    target = folder / "SHA256SUMS"
    if target.exists() or target.is_symlink():
        regular(target, 4096)
        need(target.read_text() == raw, "existing_android_checksums_differ")
    else:
        with target.open("x") as stream:
            stream.write(raw)


def ios_files(folder, source):
    ipa = folder / ipa_name(source)
    proof_path = ipa.with_suffix(".report.json")
    proof = read(proof_path)
    need(proof.get("source_commit") == source and proof.get("runtime_target") == "device"
         and proof.get("original_SDK_members_unchanged") is True
         and proof.get("Unity_patch", {}).get("all_other_Unity_bytes_equal") is True
         and proof.get("fresh_presentation_source_build", {}).get("fresh_source_build") is True,
         "ipa_source_or_preservation_differs")
    regular(ipa)
    need(proof.get("output_bytes") == ipa.stat().st_size and proof.get("output_sha256") == sha(ipa), "ipa_bytes_differ")
    regular(folder / "SHA256SUMS", 4096)
    need((folder / "SHA256SUMS").read_text() == sha(ipa) + "  " + ipa.name + "\n", "ipa_checksums_differ")
    environment = read(folder / "build-environment.json")
    need(environment.get("source_commit") == source and environment.get("server_runs_in_process") is True,
         "ipa_same_process_build_proof_differs")
    language_build = read(folder / "client-languages-build.json")
    language_runtime = read(folder / "client-language-runtime-check.json")
    need(language_build.get("source_commit") == source
         and set(proof.get("client_languages", {}).get("manifest", {}).get("languages", {})) == {"ko", "ja", "en"}
         and language_runtime.get("status") == "PASS"
         and language_runtime.get("all_source_and_output_hashes_verified_by_runtime") is True
         and {row.get("language") for row in language_runtime.get("languages", [])} == {"ko", "ja", "en"}
         and all(row.get("resource_only_bundle") is True for row in language_runtime["languages"]),
         "ipa_three_language_data_proof_differs")
    data_pin = module("mp4_preview_payload_guard", ROOT / "tools/latest_server_data_pin.py")
    korean = module("mp4_preview_ios_korean_guard", ROOT / "tools/korean_server_data_pin.py")
    provenance = proof.get("server_data_provenance")
    need(type(provenance) is dict and set(provenance) == {
        "schema", "policy", "original_cohort", "korean_master_refresh"}
        and type(provenance.get("schema")) is int and provenance["schema"] == 1 and provenance.get("policy") == korean.POLICY,
        "ipa_korean_provenance_differs")
    data_pin.verify_upgrade_proof(provenance["original_cohort"])
    korean.verify_refresh_proof(provenance["korean_master_refresh"])
    translation = korean_translation_proof(read(folder / "korean-translation-refresh.json"), "ios")
    native = read(folder / "device-native-build.json")
    need(native.get("codesign_strict_verified") is True and native.get("smoke_probe_only") is False
         and native.get("MachO", {}).get("platform") == 2, "ios_native_target_differs")
    source_pins(native.get("source_sha256"), ROOT / "ios-unified/native", {
        "IdolyMP4UI.h", "IdolyMP4UI.m", "IdolyMVEncoder.mm", "IdolyEmbeddedServer.m", "IdolySettings.m", "MP4LifecyclePolicy.h", "MP4FinalizationPolicy.h",
        "../../client-presentation/native/mp4_encoder_api.h"})
    presentation = read(folder / "presentation-native-build.json")
    mp4_native_sources(presentation.get("source_sha256"))
    runtime = read(folder / "device-runtime-report.json")
    need(runtime.get("target") == "device" and runtime.get("frameworks_codesign_verify_passed") is True,
         "ios_runtime_target_differs")
    for name in ("idoly_local.mp4_audio_bundle", "idoly_local.mp4_audio_broker", "idoly_local.mp4_export_library", "idoly_local.mp4_titles",
                 "idoly_local.ios_host", "idoly_local.resource_translation_runtime"):
        need(runtime.get("source_sha256", {}).get(name) == sha(ROOT / "src" / (name.replace(".", "/") + ".py")), "mp4_python_source_differs")
    ui, codec = read(folder / "mp4-ui-compile.json"), read(folder / "mp4-codec-report.json")
    need(ui.get("status") == "PASS_APPLE_UIKIT_COMPILE_ONLY" and codec.get("status") == "PASS_SYNTHETIC_CODEC_ONLY"
         and codec.get("exit_code") == 0 and codec.get("codecs_required") == ["h264", "hevc"], "mp4_apple_preflight_failed")
    source_pins(ui.get("source_sha256"), ROOT / "ios-unified/native", {"IdolyMP4UI.h", "IdolyMP4UI.m"})
    source_pins(codec.get("source_sha256"), ROOT, {"ios-unified/native/IdolyMVEncoder.mm", "client-presentation/native/mp4_encoder_api.h"})
    smoke = read(folder / "simulator-smoke.json")
    need(smoke.get("status") == "PASS" and smoke.get("fresh_local_state_before_launch") is True
         and smoke.get("cleanup", {}).get("shutdown") is True and smoke.get("cleanup", {}).get("delete") is True,
         "simulator_probe_not_complete")
    probe = module("mp4_preview_simulator_guard", ROOT / "ios-unified/probe/smoke_probe.py")
    matrix = probe.validate_language_matrix_report(smoke.get("language_matrix"))
    probe.validate_report(smoke["native_probe"])
    need([row.get("path") for row in smoke.get("rpcs", [])] == ["/api.System/Check", "/api.Auth/Login", "/api.Home/Enter"]
         and all(row.get("grpc_status") == 0 and row.get("request_encrypted") is True and row.get("response_encrypted") is True
                 for row in smoke["rpcs"]), "simulator_rpc_proof_differs")
    members = proof.get("member_sha256")
    need(type(members) is dict and 1 <= len(members) <= 12000, "ipa_member_proof_missing")
    with ZipFile(ipa) as archive:
        infos = archive.infolist()
        need(len(infos) == len(members) and len({row.filename for row in infos}) == len(infos)
             and {row.filename for row in infos} == set(members) and sum(row.file_size for row in infos) <= 1536 * MIB,
             "ipa_member_inventory_differs")
        for row in infos:
            path = PurePosixPath(row.filename)
            need(not path.is_absolute() and ".." not in path.parts and "\\" not in row.filename
                 and not row.flag_bits & 1 and not stat.S_ISLNK(row.external_attr >> 16), "ipa_member_invalid")
            with archive.open(row) as incoming:
                need(hashlib.file_digest(incoming, "sha256").hexdigest() == members[row.filename], "ipa_member_bytes_differ")
        app = "Payload/IDOLY PRIDE.app/"
        info = plistlib.loads(archive.read(app + "Info.plist"))
        need(info.get("CFBundleVersion") == "2026.1121.10", "ipa_preview_version_differs")
        need(members[app + "Frameworks/IdolyEmbeddedServer.framework/IdolyEmbeddedServer"] == native["post_sign_binary_sha256"]
             and members[app + "Frameworks/IdolyPresentation.dylib"] == presentation["sha256"], "ipa_native_source_binding_differs")
        need(members[app + "LocalServer/ServerData.zip"] == korean.output_pin()["sha256"], "ipa_server_data_pin_differs")
        need(members[app + "LocalServer/bundledTranslations.zip"] == translation["sha256"], "ipa_translation_pin_differs")
    return [ipa, proof_path], {"same_process": True, "language_order": matrix["order"],
        "five_cold_processes_verified": True, "mp4_source_bound": True, "actual_game_mv_verified": False,
        "korean_translation_revision": korean.REVISION, "server_data_sha256": korean.output_pin()["sha256"],
        "translation_sha256": translation["sha256"]}


def api(path, *, body=None, method=None, absent=False):
    args = ["gh", "api", "repos/" + REPO + "/" + path]
    data = None
    if body is not None:
        args += ["--method", method or "POST", "--input", "-"]
        data = json.dumps(body).encode()
    result = subprocess.run(args, input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    need(len(result.stdout) <= 8 * MIB, "github_metadata_bound")
    if result.returncode:
        if absent and b"(HTTP 404)" in result.stderr:
            return None
        raise ValueError("github_metadata_request_failed")
    return decode(result.stdout)


def context(source, *, android_only=False):
    source_sha(source)
    need(os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("GITHUB_REPOSITORY") == REPO
         and os.environ.get("GITHUB_SHA") == source and os.environ.get("GITHUB_REF") == BRANCH
         and os.environ.get("GITHUB_WORKFLOW_REF") == REPO + "/" + WORKFLOW + "@" + BRANCH
         and os.environ.get("GITHUB_EVENT_NAME") in ("push", "workflow_dispatch"), "exact_actions_context_required")
    need(os.environ.get("GITHUB_JOB") == ("android-draft-stage" if android_only else "draft-stage"),
         "staging_job_not_allowed")
    identifiers = ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "ANDROID_ARTIFACT_ID")
    for key in identifiers + (() if android_only else ("IOS_ARTIFACT_ID",)):
        need(re.fullmatch(r"[1-9][0-9]*", os.environ.get(key, "")), "current_run_identifier_required")
    return int(os.environ["GITHUB_RUN_ID"]), int(os.environ["GITHUB_RUN_ATTEMPT"])


def canonical_sha(value):
    need(type(value) is str, "artifact_digest_required")
    value = value.removeprefix("sha256:")
    need(re.fullmatch(r"[0-9a-f]{64}", value), "artifact_digest_required")
    return value


def producer_gate(run, jobs, artifact, *, kind, source, run_id, attempt, artifact_id, digest):
    need(type(run.get("id")) is int and run.get("id") == run_id and run.get("head_sha") == source and run.get("path") == WORKFLOW
         and run.get("head_branch") == BRANCH.removeprefix("refs/heads/")
         and run.get("event") in ("push", "workflow_dispatch")
         and run.get("head_repository", {}).get("full_name") == REPO, "producer_run_source_differs")
    selected = [job for job in jobs if job.get("name") == kind + "-build"]
    need(len(selected) == 1 and selected[0].get("status") == "completed" and selected[0].get("conclusion") == "success"
         and selected[0].get("run_attempt") == attempt, "producer_job_not_successful_current_attempt")
    need(type(artifact.get("id")) is int and artifact.get("id") == artifact_id and artifact.get("name") == f"mp4-{kind}-preview-{source}-{attempt}"
         and artifact.get("expired") is False and type(artifact.get("size_in_bytes")) is int
         and 0 < artifact["size_in_bytes"] <= 1024 * MIB
         and canonical_sha(artifact.get("digest")) == canonical_sha(digest)
         and artifact.get("workflow_run", {}).get("id") == run_id
         and artifact.get("workflow_run", {}).get("head_sha") == source, "artifact_source_or_identity_differs")
    return artifact


def wait_codecs(source):
    deadline = time.monotonic() + CODEC_WAIT
    while True:
        runs = api("actions/runs?head_sha=" + source + "&per_page=100").get("workflow_runs", [])
        need(type(runs) is list and len(runs) <= 100, "codec_run_catalog_bound")
        runs = [row for row in runs if row.get("head_sha") == source and row.get("path") == CODEC_WORKFLOW
                and row.get("head_repository", {}).get("full_name") == REPO]
        passed = [row for row in runs if row.get("status") == "completed" and row.get("conclusion") == "success"]
        if passed:
            selected = max(passed, key=lambda row: row["id"])
            jobs = api("actions/runs/" + str(selected["id"]) + "/jobs?per_page=100").get("jobs", [])
            need(type(jobs) is list and len(jobs) <= 100, "codec_job_catalog_bound")
            for name in ("apple-codecs", "android-codecs"):
                matches = [job for job in jobs if job.get("name") == name]
                need(len(matches) == 1 and matches[0].get("status") == "completed"
                     and matches[0].get("conclusion") == "success", "codec_platform_not_successful")
            return {"run_id": selected["id"], "source_commit": source,
                    "url": "https://github.com/" + REPO + "/actions/runs/" + str(selected["id"])}
        pending = any(row.get("status") != "completed" for row in runs)
        need(not runs or pending, "current_source_codec_workflow_failed")
        need(time.monotonic() < deadline, "current_source_codec_workflow_timeout")
        print("Waiting for both actual codec jobs at exact source " + source, flush=True)
        time.sleep(30)


def download(path, destination, *, size, digest):
    need(not destination.exists() and not destination.is_symlink(), "fresh_download_path_required")
    # Actions archive downloads negotiate a JSON API redirect. The octet-stream
    # media type is supported by release assets, but returns HTTP 415 here.
    if re.fullmatch(r"actions/artifacts/[1-9][0-9]*/zip", path):
        accept = "application/vnd.github+json"
    else:
        need(re.fullmatch(r"releases/assets/[1-9][0-9]*", path), "download_endpoint_not_allowed")
        accept = "application/octet-stream"
    process = subprocess.Popen(["gh", "api", "repos/" + REPO + "/" + path,
        "--header", "Accept: " + accept], stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    timer = threading.Timer(600, process.kill)
    timer.start()
    used = 0; actual = hashlib.sha256()
    try:
        with destination.open("xb") as output:
            while block := process.stdout.read(128 * 1024):
                used += len(block)
                need(used <= size, "remote_bytes_exceed_expected_size")
                actual.update(block); output.write(block)
        status = process.wait(timeout=30)
        need(status == 0 and used == size and actual.hexdigest() == digest,
             f"remote_complete_readback_differs: exit={status}, bytes={used}/{size}, sha256={actual.hexdigest()}/{digest}")
    finally:
        timer.cancel()
        if process.poll() is None:
            process.kill(); process.wait(timeout=30)
        process.stdout.close()


def extract_artifact(archive, destination):
    need(not destination.exists(), "fresh_artifact_directory_required")
    with ZipFile(archive) as source:
        rows = source.infolist()
        need(1 <= len(rows) <= 128 and len({row.filename for row in rows}) == len(rows)
             and sum(row.file_size for row in rows) <= 1024 * MIB, "artifact_inventory_bound")
        for row in rows:
            name = PurePosixPath(row.filename)
            need(len(name.parts) == 1 and not name.is_absolute() and ".." not in name.parts
                 and "\\" not in row.filename and not row.flag_bits & 1
                 and not stat.S_ISLNK(row.external_attr >> 16) and not row.is_dir()
                 and 0 < row.file_size <= MAX_FILE, "artifact_member_invalid")
        destination.mkdir()
        for row in rows:
            with source.open(row) as incoming, (destination / row.filename).open("xb") as output:
                while block := incoming.read(128 * 1024):
                    output.write(block)


def android_producer_marker(identity):
    need(type(identity) is tuple and len(identity) == 2
         and all(type(value) is int and value > 0 for value in identity), "android_producer_identity_required")
    return "<!-- android-mp4-producer:" + str(identity[0]) + "/" + str(identity[1]) + " -->"


def release_gate(value, source, names, release_id=None, *, android_only=False, producer_identity=None):
    need(type(value) is dict and type(value.get("id")) is int and value["id"] > 0
         and (release_id is None or value["id"] == release_id)
         and value.get("tag_name") == tag(source, android_only=android_only, producer_identity=producer_identity)
         and value.get("target_commitish") == source and value.get("draft") is True
         and value.get("prerelease") is True and value.get("published_at") is None, "exact_unpublished_draft_required")
    if android_only:
        marker = android_producer_marker(producer_identity)
        need(type(value.get("body")) is str and value["body"].count(marker) == 1
             and re.findall(r"<!-- android-mp4-producer:[1-9][0-9]*/[1-9][0-9]* -->", value["body"]) == [marker],
             "android_draft_producer_attempt_differs")
    expected_upload = "https://uploads.github.com/repos/" + REPO + "/releases/" + str(value["id"]) + "/assets{?name,label}"
    need(value.get("upload_url") == expected_upload, "draft_upload_identity_differs")
    assets = value.get("assets")
    need(type(assets) is list and all(type(row) is dict and type(row.get("id")) is int and row["id"] > 0
         and type(row.get("name")) is str for row in assets), "draft_asset_metadata_invalid")
    need(len({row["name"] for row in assets}) == len(assets) and len({row["id"] for row in assets}) == len(assets)
         and {row["name"] for row in assets} <= set(names), "draft_unknown_or_duplicate_assets")
    return value


def final_page_url(value, source, *, android_only=False, producer_identity=None):
    prefix = "https://github.com/" + REPO + "/releases/tag/"
    need(type(value) is str and re.fullmatch(re.escape(prefix) + "(?:" + re.escape(tag(source, android_only=android_only, producer_identity=producer_identity))
         + r"|untagged-[A-Za-z0-9-]+)", value), "final_draft_url_invalid")
    return value


def final_asset_url(value, source, name, *, android_only=False, producer_identity=None):
    prefix = "https://github.com/" + REPO + "/releases/download/"
    need(type(value) is str and re.fullmatch(re.escape(prefix) + "(?:" + re.escape(tag(source, android_only=android_only, producer_identity=producer_identity))
         + r"|untagged-[A-Za-z0-9-]+)/" + re.escape(quote(name, safe="")), value), "final_asset_url_invalid")
    return value


def find_draft(source, names, *, android_only=False, producer_identity=None):
    expected_tag = tag(source, android_only=android_only, producer_identity=producer_identity)
    matches = []
    for page in range(1, 11):
        rows = api(f"releases?per_page=100&page={page}")
        need(type(rows) is list and len(rows) <= 100, "release_catalog_bound")
        matches.extend(row for row in rows if row.get("tag_name") == expected_tag)
        if len(rows) < 100:
            break
    else:
        raise ValueError("release_catalog_pagination_bound")
    need(len(matches) <= 1, "duplicate_preview_drafts_rejected")
    if not matches:
        return None
    return release_gate(api("releases/" + str(matches[0]["id"])), source, names, matches[0]["id"],
                        android_only=android_only, producer_identity=producer_identity)


def tag_source_gate(source, *, android_only=False, producer_identity=None):
    value = api("git/ref/tags/" + tag(source, android_only=android_only, producer_identity=producer_identity), absent=True)
    if value is None:
        return
    obj = value.get("object", {})
    for _ in range(3):
        if obj.get("type") == "commit":
            break
        need(obj.get("type") == "tag" and re.fullmatch(r"[0-9a-f]{40}", obj.get("sha", "")), "preview_git_tag_invalid")
        obj = api("git/tags/" + obj["sha"]).get("object", {})
    need(obj.get("type") == "commit" and obj.get("sha") == source, "preview_git_tag_source_differs")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def upload(release, path):
    regular(path)
    token = os.environ.get("GH_TOKEN", "")
    need(token and os.environ.get("GITHUB_ACTIONS") == "true", "actions_upload_token_required")
    url = "https://uploads.github.com/repos/" + REPO + "/releases/" + str(release["id"]) + "/assets?name=" + quote(path.name, safe="")
    with path.open("rb") as incoming:
        request = Request(url, data=incoming, method="POST", headers={"Authorization": "Bearer " + token,
            "Content-Type": "application/octet-stream", "Content-Length": str(path.stat().st_size),
            "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
        try:
            with build_opener(NoRedirect()).open(request, timeout=600) as response:
                need(response.status == 201, "asset_upload_status_differs")
                body = response.read(2 * MIB + 1)
        except Exception as error:
            raise ValueError("asset_upload_failed_" + type(error).__name__) from None
    need(len(body) <= 2 * MIB, "asset_upload_metadata_bound")
    value = decode(body)
    need(value.get("name") == path.name and value.get("size") == path.stat().st_size, "uploaded_asset_identity_differs")
    return value


def verify_asset(asset, path, work):
    digest = sha(path)
    need(type(asset.get("id")) is int and asset["id"] > 0 and asset.get("state") == "uploaded"
         and type(asset.get("size")) is int and asset["size"] == path.stat().st_size
         and asset.get("digest") in (None, "sha256:" + digest), "asset_metadata_differs")
    target = work / ("readback-" + str(asset["id"]))
    download("releases/assets/" + str(asset["id"]), target, size=path.stat().st_size, digest=digest)
    target.unlink()  # Only this helper's newly verified private download.
    return {"name": path.name, "asset_id": asset["id"], "bytes": path.stat().st_size,
            "sha256": digest, "complete_download_verified": True}


@dataclass(frozen=True)
class ProducerContext:
    """Explicit producer identity; recovery callers must validate their own workflow."""
    run_id: int
    attempt: int
    artifacts: tuple[tuple[str, int, str], ...]
    codec_run_id: int | None = None
    delivery_source_commit: str | None = None
    delivery_run_id: int | None = None
    delivery_workflow: str | None = None


def producer_context_gate(value, *, android_only=False):
    need(type(value) is ProducerContext and type(value.run_id) is int and value.run_id > 0
         and type(value.attempt) is int and value.attempt > 0, "explicit_producer_context_required")
    kinds = {"android"} if android_only else {"android", "ios"}
    need(type(value.artifacts) is tuple and len(value.artifacts) == len(kinds)
         and {row[0] for row in value.artifacts} == kinds, "explicit_artifact_context_required")
    for kind, identifier, digest in value.artifacts:
        need(type(identifier) is int and identifier > 0 and canonical_sha(digest) == digest,
             "explicit_artifact_context_required")
    need(value.codec_run_id is None or type(value.codec_run_id) is int and value.codec_run_id > 0,
         "explicit_codec_context_invalid")
    delivery = (value.delivery_source_commit, value.delivery_run_id, value.delivery_workflow)
    need(all(item is None for item in delivery) or all(item is not None for item in delivery),
         "delivery_context_incomplete")
    if value.delivery_source_commit is not None:
        source_sha(value.delivery_source_commit)
        need(type(value.delivery_run_id) is int and value.delivery_run_id > 0
             and type(value.delivery_workflow) is str
             and re.fullmatch(r"\.github/workflows/[a-z0-9-]+\.yml", value.delivery_workflow), "delivery_context_invalid")
    return value


def pinned_codec_proof(source, run_id):
    run = api("actions/runs/" + str(run_id))
    need(run.get("id") == run_id and run.get("head_sha") == source and run.get("path") == CODEC_WORKFLOW
         and run.get("head_repository", {}).get("full_name") == REPO
         and run.get("head_branch") == BRANCH.removeprefix("refs/heads/")
         and run.get("status") == "completed" and run.get("conclusion") == "success", "pinned_codec_run_differs")
    jobs = api("actions/runs/" + str(run_id) + "/jobs?per_page=100").get("jobs", [])
    need(type(jobs) is list and len(jobs) <= 100, "codec_job_catalog_bound")
    for name in ("apple-codecs", "android-codecs"):
        selected = [job for job in jobs if job.get("name") == name]
        need(len(selected) == 1 and selected[0].get("status") == "completed"
             and selected[0].get("conclusion") == "success"
             and selected[0].get("run_attempt") == run.get("run_attempt"), "pinned_codec_platform_differs")
    return {"run_id": run_id, "source_commit": source,
            "url": "https://github.com/" + REPO + "/actions/runs/" + str(run_id)}


def stage(source, work):
    run_id, attempt = context(source)
    producer = ProducerContext(run_id, attempt, tuple((kind,
        int(os.environ[kind.upper() + "_ARTIFACT_ID"]), canonical_sha(os.environ[kind.upper() + "_ARTIFACT_SHA"]))
        for kind in ("android", "ios")))
    return stage_from_producer(source, work, producer=producer)


def stage_android(source, work):
    """Stage only the current Android producer from its dedicated Actions job."""
    run_id, attempt = context(source, android_only=True)
    producer = ProducerContext(run_id, attempt, (("android", int(os.environ["ANDROID_ARTIFACT_ID"]),
        canonical_sha(os.environ["ANDROID_ARTIFACT_SHA"])),))
    return stage_from_producer(source, work, producer=producer, android_only=True)


def stage_from_producer(source, work, *, producer, android_only=False):
    """Reuse every package/release gate with an explicitly validated producer.

    The ordinary CLI always obtains this identity from context(). The one-time
    recovery entry point separately validates its workflow and immutable pins;
    it never changes GITHUB_* variables to impersonate the producer workflow.
    """
    source_sha(source)
    producer_context_gate(producer, android_only=android_only)
    need(not android_only or producer.delivery_source_commit is None, "android_delivery_context_not_allowed")
    run_id, attempt = producer.run_id, producer.attempt
    producer_identity = (run_id, attempt) if android_only else None
    inputs = {kind: (identifier, digest) for kind, identifier, digest in producer.artifacts}
    need(not work.exists() and not work.is_symlink(), "fresh_staging_directory_required")
    work.mkdir(mode=0o700, parents=True)
    receipt = work / ("android-draft-staging-proof.json" if android_only else "draft-staging-proof.json")
    scope = {"scope": "android-only", "ios_package_verified": False,
             "core_runtime_execution_verified": False, "device_execution_verified": False} if android_only else {}
    proof = {"schema": 1, "source_commit": source,
             "tag": tag(source, android_only=android_only, producer_identity=producer_identity), "draft": True, **scope,
             "published": False, "stage": "preflight", "verified_assets": []}
    if android_only:
        proof.update(producer_run_id=run_id, producer_run_attempt=attempt)
    delivery = {} if producer.delivery_source_commit is None else {
        "delivery_source_commit": producer.delivery_source_commit,
        "delivery_run_id": producer.delivery_run_id, "delivery_workflow": producer.delivery_workflow}
    proof.update(delivery)
    def save():
        receipt.write_text(json.dumps(proof, indent=2) + "\n")
    save()
    try:
        codec = wait_codecs(source) if producer.codec_run_id is None else pinned_codec_proof(source, producer.codec_run_id)
        run = api("actions/runs/" + str(run_id))
        jobs = api("actions/runs/" + str(run_id) + "/jobs?per_page=100").get("jobs", [])
        need(type(jobs) is list and len(jobs) <= 100, "producer_job_catalog_bound")
        built = {}; paths = []; details = {}
        for kind in (("android",) if android_only else ("android", "ios")):
            artifact_id, digest = inputs[kind]
            artifact = producer_gate(run, jobs, api("actions/artifacts/" + str(artifact_id)), kind=kind,
                source=source, run_id=run_id, attempt=attempt, artifact_id=artifact_id, digest=digest)
            archive = work / (kind + ".zip")
            download("actions/artifacts/" + str(artifact_id) + "/zip", archive, size=artifact["size_in_bytes"], digest=digest)
            folder = work / kind
            extract_artifact(archive, folder)
            files, summary = android_files(folder, source) if kind == "android" else ios_files(folder, source)
            paths.extend(files); details[kind] = summary
            built[kind] = {"artifact_id": artifact_id, "artifact_sha256": digest,
                "url": f"https://github.com/{REPO}/actions/runs/{run_id}/artifacts/{artifact_id}"}
        manifest = work / (ANDROID_VERIFICATION if android_only else VERIFICATION)
        manifest.write_text(json.dumps({"schema": 1, "source_commit": source, "version": VERSION, **delivery, **scope,
            "producer_run_id": run_id, "producer_run_attempt": attempt, "artifacts": built,
            "codec_workflow": codec, "checks": details, "actual_game_mv_verified": False,
            "queue": {"persistent": True, "actual_game_sequential_mv_verified": False},
            "background": ({"android": "experimental_opt_in", "android_device_verified": False} if android_only else
                           {"android": "experimental_opt_in", "android_device_verified": False,
                            "ios": "pause_and_resume", "ios_background_rendering": False}),
            "files": [{"name": path.name, "bytes": path.stat().st_size, "sha256": sha(path)} for path in paths]}, indent=2) + "\n")
        paths.append(manifest)
        sums = work / "SHA256SUMS"
        sums.write_text("".join(f"{sha(path)}  {path.name}\n" for path in sorted(paths)))
        paths.append(sums)
        names = {path.name for path in paths}
        need(len(names) == (4 if android_only else 6), "preview_asset_set_differs")
        tag_source_gate(source, android_only=android_only, producer_identity=producer_identity)
        release = find_draft(source, names, android_only=android_only, producer_identity=producer_identity)
        if release is None:
            release = api("releases", body={"tag_name": tag(source, android_only=android_only, producer_identity=producer_identity), "target_commitish": source,
                "name": ("Android MP4 preview " if android_only else "Unified APK and IPA preview ") + VERSION + " (" + source[:7] + ")",
                "body": ((android_producer_marker(producer_identity) + "\nAndroid-only prototype. ") if android_only else "APK and IPA prototype. ") + "Source " + source + ". Actual game MV export/device validation remains pending.",
                "draft": True, "prerelease": True, "make_latest": "false"})
        release = release_gate(release, source, names, android_only=android_only, producer_identity=producer_identity)
        release_id = release["id"]
        proof.update(stage="upload_and_readback", release_id=release_id, artifacts=built, codec_workflow=codec)
        save()
        local = {path.name: path for path in paths}
        for asset in release["assets"]:
            verify_asset(asset, local[asset["name"]], work)
        for path in paths:
            release = release_gate(api("releases/" + str(release_id)), source, names, release_id,
                                   android_only=android_only, producer_identity=producer_identity)
            matches = [asset for asset in release["assets"] if asset["name"] == path.name]
            if not matches:
                upload(release, path)
                release = release_gate(api("releases/" + str(release_id)), source, names, release_id,
                                       android_only=android_only, producer_identity=producer_identity)
                matches = [asset for asset in release["assets"] if asset["name"] == path.name]
            need(len(matches) == 1, "uploaded_asset_missing_or_duplicate")
            proof["verified_assets"].append(verify_asset(matches[0], path, work)); save()
        body = ("Offline MP4 APK and IPA preview built from `" + source + "`.\n\n"
                "Persistent MV export queue with reordering, retry and per-job saving. Android background rendering is experimental and off by default; iOS pauses and resumes when returning.\n\n"
                "Export frame rate, codec, bitrate mode and output size are saved automatically. Bitrate supports a numeric recommendation and custom Mbps; width and height can be entered separately. Existing queue jobs keep the options captured when registered.\n\n"
                "MV target discovery includes explicit-size and already-created targets; odd source sizes are normalized for the encoder. Paused Android MVs are revalidated after returning to the game. Korean ADV, display text and master translations retain the pinned 11ecceb source; untranslated event banners retain their originals.\n\n"
                "Both current-source codec jobs passed. The IPA also passed its five-process language/core Simulator checks.\n"
                "Actual game MV rendering, device export fidelity and PlayCover execution remain unverified.\n\n"
                "Every asset was downloaded in full and SHA-256 verified. See MP4-PREVIEW-VERIFICATION.json and SHA256SUMS.\n")
        if android_only:
            body = (android_producer_marker(producer_identity) + "\n\nAndroid-only MP4 preview built from `" + source + "`.\n\n"
                    "APK signatures, current-source preservation/provenance and pinned Korean data were verified. "
                    "Both current-source synthetic codec jobs passed. The IPA is not part of this draft.\n\n"
                    "Core runtime/device execution and actual game MV export have not been verified by this staging job.\n\n"
                    "Every asset was downloaded in full and SHA-256 verified. "
                    "See ANDROID-MP4-PREVIEW-VERIFICATION.json and SHA256SUMS.\n")
        # Keep identity explicit during this final notes update. GitHub may
        # assign an untagged draft URL even when tag_name is correct. Capture
        # the last API URL; do not attempt further edits to repair its spelling.
        final = api("releases/" + str(release_id), method="PATCH",
            body={"tag_name": tag(source, android_only=android_only, producer_identity=producer_identity),
            "target_commitish": source, "draft": True, "prerelease": True,
            "make_latest": "false", "body": body})
        release_gate(final, source, names, release_id, android_only=android_only, producer_identity=producer_identity)
        final = release_gate(api("releases/" + str(release_id)), source, names, release_id,
                             android_only=android_only, producer_identity=producer_identity)
        url = final_page_url(final.get("html_url"), source, android_only=android_only, producer_identity=producer_identity)
        need({row["name"] for row in final["assets"]} == names, "final_draft_assets_differ")
        final_assets = {row["name"]: row for row in final["assets"]}
        for verified in proof["verified_assets"]:
            row = final_assets[verified["name"]]
            need(row["id"] == verified["asset_id"] and row.get("size") == verified["bytes"]
                 and row.get("digest") in (None, "sha256:" + verified["sha256"]), "final_asset_identity_changed")
            verified["browser_download_url"] = final_asset_url(row.get("browser_download_url"), source, row["name"],
                android_only=android_only, producer_identity=producer_identity)
        proof.update(stage="verified_exact_draft", release_url=url); save()
        print(json.dumps(proof, indent=2))
        return proof
    except Exception as error:
        proof.update(stage="stopped", error_type=type(error).__name__); save()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check-android", "stage", "stage-android"))
    parser.add_argument("--source", required=True)
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--work", type=Path)
    args = parser.parse_args()
    if args.action == "check-android":
        need(args.directory is not None, "android_directory_required")
        android_checksums(args.directory, args.source)
    else:
        need(args.work is not None, "staging_work_directory_required")
        (stage_android if args.action == "stage-android" else stage)(args.source, args.work)


if __name__ == "__main__":
    main()
