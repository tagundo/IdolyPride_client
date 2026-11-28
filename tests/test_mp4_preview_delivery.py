from __future__ import annotations
import copy
import hashlib
import io
import json
import re
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile, ZipInfo

import pytest

from tools import stage_mp4_preview as delivery

SOURCE = "a" * 40
PHOTOGRAPHY_HEADERS = {"client-presentation/native/" + name for name in (
    "mp4_photography_replay_factory.hpp", "mp4_photography_replay_profile.hpp",
    "mp4_camera_owner.hpp", "mp4_timeline_camera.hpp", "mp4_timeline_audio.hpp")}
OWNED_CLOCK_HEADERS = {"client-presentation/native/" + name for name in (
    "mp4_engine_clock.hpp", "mp4_playback_state.hpp", "mp4_stage_state.hpp",
    "mp4_actor_state.hpp", "mp4_actor_state_profile.hpp")}


@pytest.fixture
def native_source_receipt(tmp_path, monkeypatch):
    required = delivery.MP4_NATIVE | delivery.MP4_ANDROID_PROFILES | {
        "client-presentation/native/mp4_android_session.hpp"}
    values = {}
    for name in required:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(("compiled current native source: " + name).encode())
        values[name] = delivery.sha(path)
    monkeypatch.setattr(delivery, "ROOT", tmp_path)
    return tmp_path, values


@pytest.mark.parametrize("android", [False, True])
@pytest.mark.parametrize("missing", sorted(PHOTOGRAPHY_HEADERS | OWNED_CLOCK_HEADERS))
def test_both_platform_receipts_require_each_compiled_photography_replay_header(native_source_receipt, android, missing):
    _, values = native_source_receipt
    assert PHOTOGRAPHY_HEADERS | OWNED_CLOCK_HEADERS <= delivery.MP4_NATIVE
    assert all(Path(name).suffix in (".h", ".hpp") for name in delivery.MP4_NATIVE)
    delivery.mp4_native_sources(values, android=android)
    del values[missing]
    with pytest.raises(ValueError, match="source_closure_missing"):
        delivery.mp4_native_sources(values, android=android)


@pytest.mark.parametrize("android", [False, True])
@pytest.mark.parametrize("changed", sorted(PHOTOGRAPHY_HEADERS | OWNED_CLOCK_HEADERS))
def test_compiled_photography_replay_header_changes_after_build_are_rejected(native_source_receipt, android, changed):
    root, values = native_source_receipt
    (root / changed).write_text("different replay implementation after native compilation")
    with pytest.raises(ValueError, match="source_bytes_changed"):
        delivery.mp4_native_sources(values, android=android)


@pytest.mark.parametrize("profile", ["mp4_photography_replay_android_profile.json", "mp4_photography_replay_ios_profile.json", "mp4_camera_owner_profile.json",
                                    "mp4_engine_clock_profile.json", "mp4_playback_state_profile.json", "mp4_actor_state_profile.json"])
def test_android_requires_actual_builder_profile_json_pins_but_darwin_does_not(native_source_receipt, profile):
    root, values = native_source_receipt
    assert "client-presentation/native/" + profile in delivery.MP4_ANDROID_PROFILES
    headers_only = {name: digest for name, digest in values.items() if not name.endswith(".json")}
    delivery.mp4_native_sources(headers_only)  # Darwin does not emit JSON source hashes.
    with pytest.raises(ValueError, match="source_closure_missing"):
        delivery.mp4_native_sources(headers_only, android=True)
    selected = "client-presentation/native/" + profile
    missing = {name: digest for name, digest in values.items() if name != selected}
    with pytest.raises(ValueError, match="source_closure_missing"):
        delivery.mp4_native_sources(missing, android=True)
    (root / selected).write_text('{"changed_after_native_build":true}')
    with pytest.raises(ValueError, match="source_bytes_changed"):
        delivery.mp4_native_sources(values, android=True)


@pytest.mark.parametrize("missing", ["IdolyMP4Library.m", "IdolyMP4Library.h", "MP4CompletedFilePolicy.h"])
def test_ios_receipt_requires_each_compiled_completed_library_source(tmp_path, monkeypatch, missing):
    root=tmp_path / "repo";base=root / "ios-unified/native";values={}
    for name in delivery.MP4_IOS_HOST:
        path=base / name;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text("actual compiled source: " + name);values[name]=delivery.sha(path)
    monkeypatch.setattr(delivery,"ROOT",root)
    delivery.source_pins(values,base,delivery.MP4_IOS_HOST)
    del values[missing]
    with pytest.raises(ValueError,match="source_closure_missing"):
        delivery.source_pins(values,base,delivery.MP4_IOS_HOST)


@pytest.mark.parametrize("changed", ["IdolyMP4Library.m", "IdolyMP4Library.h", "MP4CompletedFilePolicy.h"])
def test_ios_receipt_rejects_library_bytes_changed_after_compile(tmp_path, monkeypatch, changed):
    root=tmp_path / "repo";base=root / "ios-unified/native";values={}
    for name in delivery.MP4_IOS_HOST:
        path=base / name;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text("actual compiled source: " + name);values[name]=delivery.sha(path)
    monkeypatch.setattr(delivery,"ROOT",root)
    (base / changed).write_text("different saved-output behavior after compile")
    with pytest.raises(ValueError,match="source_bytes_changed"):
        delivery.source_pins(values,base,delivery.MP4_IOS_HOST)


def test_actual_android_native_builder_emits_all_new_compiled_and_profile_source_pins():
    builder = delivery.module("mp4_photography_android_build_contract", delivery.ROOT / "client-presentation/native/build_native.py")
    emitted = {path.relative_to(delivery.ROOT).as_posix() for path in builder.sources()}
    assert PHOTOGRAPHY_HEADERS | delivery.MP4_ANDROID_PROFILES <= emitted
    assert delivery.MP4_NATIVE <= emitted
    assert len(emitted) + 1 <= 64  # The package validator also counts its pinned dependency builder.


def test_complete_session_jni_contract_includes_invalidation_and_v2_apis():
    source = (Path(__file__).resolve().parents[1] / "android-server/app/src/main/java/game/qualiarts/idolypride/localserver/UnifiedMP4Export.java").read_text()
    prefix = "Java_game_qualiarts_idolypride_localserver_UnifiedMP4Export_"
    names = re.findall(r"\bstatic\s+native\s+[\w<>\[\]]+\s+(\w+)\s*\(", source)
    exports = [prefix + name for name in names]
    assert {"nativeInvalidateQueueSelection","nativeStartV2","nativeQueueEnqueueV2"} <= set(names)
    builder = delivery.module("mp4_session_jni_build_contract",Path(__file__).resolve().parents[1] / "client-presentation/native/build_native.py")
    assert builder.session_jni_exports() == set(exports)
    delivery.mp4_session_jni_exports(exports + ["JNI_OnLoad"],source)
    for name in ("nativeInvalidateQueueSelection","nativeStartV2","nativeQueueEnqueueV2"):
        with pytest.raises(ValueError,match="mp4_native_exports_differ"):
            delivery.mp4_session_jni_exports([value for value in exports if value != prefix + name],source)
    with pytest.raises(ValueError,match="mp4_native_exports_differ"):
        delivery.mp4_session_jni_exports(exports + [prefix + "nativeUndeclared"],source)


@pytest.mark.parametrize("platform", ["android", "ios"])
def test_new_translation_proof_requires_exact_source_output_and_image_preservation(platform):
    pin = json.loads((delivery.ROOT / "data/latest-korean-translations-pin.json").read_text())
    expected = pin["platforms"][platform]
    report = {"schema": 1, "platform": platform, "source": pin["source"],
              "source_archive": {key: pin["archive"][key] for key in ("bytes", "sha256")},
              **expected["output"], "coverage": {"translated": pin["adv_count"]},
              "image_count": expected["image_count"], "preserved_image_bytes_verified": True,
              "new_images_generated": False}
    assert delivery.korean_translation_proof(report, platform) == {
        key: expected["output"][key] for key in ("bytes", "sha256")}
    for key, value in (("schema", True), ("platform", "other"), ("source", {}),
                       ("source_archive", {}), ("sha256", "0" * 64), ("coverage", {}),
                       ("image_count", 0), ("preserved_image_bytes_verified", False),
                       ("new_images_generated", True)):
        with pytest.raises(ValueError, match="korean_translation_refresh_differs"):
            delivery.korean_translation_proof({**report, key: value}, platform)


def release(*, android_only=False):
    return {"id": 17, "tag_name": delivery.tag(SOURCE, android_only=android_only,
                                             producer_identity=(101, 1) if android_only else None), "target_commitish": SOURCE,
        "body": delivery.android_producer_marker((101, 1)) if android_only else "Combined preview",
        "draft": True, "prerelease": True, "published_at": None, "assets": [],
        "upload_url": "https://uploads.github.com/repos/" + delivery.REPO + "/releases/17/assets{?name,label}"}


def producer():
    return {"id": 101, "head_sha": SOURCE, "path": delivery.WORKFLOW, "head_branch": "feat/ios-unified-server",
        "event": "push", "head_repository": {"full_name": delivery.REPO}}


def artifact():
    return {"id": 23, "name": "mp4-android-preview-" + SOURCE + "-2", "expired": False,
        "size_in_bytes": 1024, "digest": "sha256:" + "b" * 64,
        "workflow_run": {"id": 101, "head_sha": SOURCE}}


def producer_gate(run=None, jobs=None, item=None):
    return delivery.producer_gate(run or producer(), jobs if jobs is not None else [
        {"name": "android-build", "status": "completed", "conclusion": "success", "run_attempt": 2}],
        item or artifact(), kind="android", source=SOURCE, run_id=101, attempt=2, artifact_id=23, digest="b" * 64)


def test_current_successful_producer_and_immutable_digest_are_required():
    assert producer_gate()["id"] == 23
    for key, value in (("head_sha", "c" * 40), ("path", ".github/workflows/build-shared-resource-preview.yml"),
                       ("id", 100), ("event", "pull_request"), ("head_branch", "main")):
        wrong = dict(producer(), **{key: value})
        with pytest.raises(ValueError):
            producer_gate(run=wrong)
    for key, value in (("id", 22), ("name", "mp4-android-preview-" + SOURCE + "-1"),
                       ("expired", True), ("digest", "sha256:" + "c" * 64),
                       ("workflow_run", {"id": 100, "head_sha": SOURCE})):
        wrong = dict(artifact(), **{key: value})
        with pytest.raises(ValueError):
            producer_gate(item=wrong)
    for job in ({"name": "android-build", "status": "completed", "conclusion": "failure", "run_attempt": 2},
                {"name": "android-build", "status": "completed", "conclusion": "success", "run_attempt": 1}):
        with pytest.raises(ValueError):
            producer_gate(jobs=[job])


@pytest.mark.parametrize("key,value", [("draft", False), ("prerelease", False), ("id", True),
    ("target_commitish", "main"), ("target_commitish", SOURCE[:7] + "b" * 33),
    ("tag_name", "android-windowing-preview-2026.11.20.1-aaaaaaa"), ("published_at", "2026-11-21"),
    ("upload_url", "https://uploads.github.com/repos/foreign/repo/releases/17/assets{?name,label}")])
def test_never_mutate_published_old_colliding_or_foreign_release(key, value):
    wrong = dict(release(), **{key: value})
    with pytest.raises(ValueError):
        delivery.release_gate(wrong, SOURCE, {delivery.APK})


def test_drafts_are_found_by_paginated_list_and_checked_id_never_by_tag(monkeypatch):
    calls = []
    def api(path, **kwargs):
        calls.append(path)
        if path == "releases?per_page=100&page=1":
            return [{"id": i + 100, "tag_name": "other-" + str(i)} for i in range(100)]
        if path == "releases?per_page=100&page=2":
            return [release()]
        assert path == "releases/17"
        return release()
    monkeypatch.setattr(delivery, "api", api)
    assert delivery.find_draft(SOURCE, {delivery.APK})["id"] == 17
    assert calls == ["releases?per_page=100&page=1", "releases?per_page=100&page=2", "releases/17"]
    monkeypatch.setattr(delivery, "api", lambda *args, **kwargs: [release(), release()])
    with pytest.raises(ValueError, match="duplicate_preview"):
        delivery.find_draft(SOURCE, {delivery.APK})


def test_unknown_assets_or_git_tag_source_cannot_be_reused(monkeypatch):
    wrong = dict(release(), assets=[{"id": 1, "name": "old.ipa"}])
    with pytest.raises(ValueError, match="unknown_or_duplicate"):
        delivery.release_gate(wrong, SOURCE, {delivery.APK})
    monkeypatch.setattr(delivery, "api", lambda *args, **kwargs: {"object": {"type": "commit", "sha": "b" * 40}})
    with pytest.raises(ValueError, match="tag_source"):
        delivery.tag_source_gate(SOURCE)


def test_codec_gate_cannot_use_old_source_or_a_skipped_platform(monkeypatch):
    old = {"id": 1, "head_sha": "b" * 40, "path": delivery.CODEC_WORKFLOW,
           "status": "completed", "conclusion": "success", "head_repository": {"full_name": delivery.REPO}}
    monkeypatch.setattr(delivery, "api", lambda *args, **kwargs: {"workflow_runs": [old]})
    clock = [0.0]
    monkeypatch.setattr(delivery.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(delivery.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    with pytest.raises(ValueError, match="timeout"):
        delivery.wait_codecs(SOURCE)
    assert clock[0] == 2400
    current = dict(old, head_sha=SOURCE)
    monkeypatch.setattr(delivery, "api", lambda path, **kwargs: {"workflow_runs": [current]} if "head_sha=" in path else
                        {"jobs": [{"name": "apple-codecs", "status": "completed", "conclusion": "success"},
                                  {"name": "android-codecs", "status": "completed", "conclusion": "skipped"}]})
    with pytest.raises(ValueError, match="platform_not_successful"):
        delivery.wait_codecs(SOURCE)


def test_artifact_download_checks_complete_bytes_and_hash(tmp_path, monkeypatch):
    commands = []
    class Process:
        def __init__(self, *args, **kwargs):
            commands.append(args[0])
            self.stdout = io.BytesIO(b"correct")
        def wait(self, **kwargs): return 0
        def poll(self): return 0
        def kill(self): raise AssertionError("already exited")
    monkeypatch.setattr(delivery.subprocess, "Popen", Process)
    digest = hashlib.sha256(b"correct").hexdigest()
    delivery.download("actions/artifacts/23/zip", tmp_path / "good", size=7, digest=digest)
    assert commands[-1][-1] == "Accept: application/vnd.github+json"
    delivery.download("releases/assets/41", tmp_path / "release", size=7, digest=digest)
    assert commands[-1][-1] == "Accept: application/octet-stream"
    with pytest.raises(ValueError, match="endpoint_not_allowed"):
        delivery.download("https://foreign.invalid/archive", tmp_path / "foreign", size=7, digest=digest)
    for size, wanted in ((6, digest), (8, digest), (7, "0" * 64)):
        with pytest.raises(ValueError):
            delivery.download("actions/artifacts/23/zip", tmp_path / (str(size) + wanted[:1]), size=size, digest=wanted)


@pytest.mark.parametrize("name,symlink", [("../outside", False), ("/tmp/outside", False),
    ("nested/report.json", False), ("report.json", True)])
def test_artifact_paths_cannot_redirect_staging_files(tmp_path, name, symlink):
    archive = tmp_path / "artifact.zip"
    with ZipFile(archive, "w") as output:
        info = ZipInfo(name)
        if symlink:
            info.external_attr = 0o120777 << 16
        output.writestr(info, b"x")
    with pytest.raises(ValueError):
        delivery.extract_artifact(archive, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_upload_uses_validated_release_id_and_no_redirect_credentials(tmp_path, monkeypatch):
    path = tmp_path / delivery.APK; path.write_bytes(b"apk")
    monkeypatch.setenv("GH_TOKEN", "fixture-token")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    captured = []
    class Response:
        status = 201
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, maximum): return json.dumps({"id": 1, "name": path.name, "size": 3}).encode()
    class Opener:
        def open(self, request, **kwargs):
            captured.append(request)
            return Response()
    monkeypatch.setattr(delivery, "build_opener", lambda *args: Opener())
    delivery.upload(release(), path)
    assert captured[0].full_url.startswith("https://uploads.github.com/repos/" + delivery.REPO + "/releases/17/assets?name=")
    assert delivery.tag(SOURCE) not in captured[0].full_url and "fixture-token" not in captured[0].full_url
    assert captured[0].get_method() == "POST"
    assert delivery.NoRedirect().redirect_request(None, None, None, None, None, None) is None


def test_workflow_binds_both_builds_and_never_invokes_old_staging_or_standalone_mac_app():
    raw = (Path(__file__).resolve().parents[1] / delivery.WORKFLOW).read_text()
    scoped = raw.split("    paths:\n", 1)[1].split("  workflow_dispatch:", 1)[0]
    assert [line.strip()[2:] for line in scoped.splitlines() if line.strip()] == [delivery.WORKFLOW,
        "tools/stage_mp4_preview.py", "tests/test_mp4_preview_delivery.py",
        "tests/test_mp4_field_reference_abi.py", "tests/test_mp4_photography_bridge.py", "tests/test_mp4_replay_factories.py",
        "tests/test_mp4_small_stack.py",
        "tests/test_mp4_camera_owner.py",
        "tests/test_mp4_timeline_camera.py",
        "tests/test_mp4_timeline_audio.py",
        "tests/test_mp4_timeline_camera_adapter.py",
        "tests/test_mp4_timeline_audio_adapter.py",
        "tests/test_mp4_selected_controller.py",
        "tests/test_mp4_controller_diagnostics.py",
        "tests/test_mp4_graphics_snapshot.py",
        "tests/test_mp4_host_enqueue.py",
        "tests/test_mp4_transfer_io.py",
        "tests/test_mp4_queue_storage.py",
        "tools/package_android_unified.py", "tests/test_android_unified_badging.py", "tests/test_ios_mp4_queue_host.py", "tests/test_ios_mp4_diagnostics.py", "ios-unified/presentation_candidate.py", "tests/test_ios_shared_candidate.py",
        "tests/test_ios_probe_process_termination.py"]
    assert "SOURCE_SHA: ${{ github.sha }}" in raw and raw.count("ref: ${{ github.sha }}") == 4
    assert "needs: [android-build, ios-build]" in raw and "inputs.upload_draft" in raw
    assert "IDOLY_RELEASE_VERSION: " + delivery.VERSION in raw and delivery.APK in raw
    assert "ios-unified/native/test_mp4_ui_compile.py" in raw and "ios-unified/ci_build.py" in raw
    assert raw.index("test_mp4_ui_compile.py") < raw.index("ios-unified/ci_build.py")
    assert "stage_shared_preview.py fetch" in raw and "stage_shared_preview.py stage" not in raw
    assert "macos-server/build_app.py" not in raw and "gh release" not in raw
    assert "ANDROID_ARTIFACT_ID: ${{ needs.android-build.outputs.artifact_id }}" in raw
    assert "IOS_ARTIFACT_ID: ${{ needs.ios-build.outputs.artifact_id }}" in raw
    assert "continue-on-error" not in raw
    for producer in ("android-build", "ios-build"):
        tail = raw.split("  " + producer + ":\n", 1)[1]
        job = re.split(r"(?m)^  [A-Za-z][A-Za-z0-9_-]*:\s*$", tail, maxsplit=1)[0]
        # Each producer must reject the reference-store regression before it
        # can generate an installation file, including the early APK delivery.
        assert "unicorn==2.1.4" in job
        for regression in ("test_mp4_field_reference_abi.py", "test_mp4_photography_bridge.py", "test_mp4_replay_factories.py"):
            assert any("python -B -m pytest" in line and regression in line for line in job.splitlines())


def stage_fixture(monkeypatch, *, corrupt_readback=False, untagged_final=False, android_only=False,
                  producer_damage=None, release_damage=None, existing_attempt=None):
    archives = {}
    for kind in ("android", "ios"):
        buffer = io.BytesIO()
        with ZipFile(buffer, "w") as output:
            if kind == "android":
                output.writestr(delivery.APK, b"apk")
                output.writestr(delivery.APK_REPORT, b"{}")
            else:
                output.writestr(delivery.ipa_name(SOURCE), b"ipa")
                output.writestr(delivery.ipa_name(SOURCE).removesuffix(".ipa") + ".report.json", b"{}")
        archives[kind] = buffer.getvalue()
    state = {"release": None, "writes": [], "bytes": {}, "patches": [], "requests": []}
    if existing_attempt is not None:
        state["release"] = release(android_only=True)
        state["release"]["body"] = delivery.android_producer_marker((101, existing_attempt))
    monkeypatch.setattr(delivery, "context", lambda source, **kwargs: (101, 1))
    monkeypatch.setattr(delivery, "wait_codecs", lambda source: {"run_id": 301, "source_commit": source})
    for kind, identifier in (("android", 23), ("ios", 24)):
        monkeypatch.setenv(kind.upper() + "_ARTIFACT_ID", str(identifier))
        monkeypatch.setenv(kind.upper() + "_ARTIFACT_SHA", hashlib.sha256(archives[kind]).hexdigest())

    def api(path, *, body=None, method=None, absent=False):
        state["requests"].append(path)
        if path == "actions/runs/101":
            return dict(producer(), **(producer_damage or {}))
        if path == "actions/runs/101/jobs?per_page=100":
            return {"jobs": [{"name": kind + "-build", "status": "completed", "conclusion": "success", "run_attempt": 1}
                             for kind in (("android",) if android_only else ("android", "ios"))]}
        if path.startswith("actions/artifacts/"):
            identifier = int(path.rsplit("/", 1)[1]); kind = "android" if identifier == 23 else "ios"
            return dict(artifact(), id=identifier, name=f"mp4-{kind}-preview-{SOURCE}-1",
                        size_in_bytes=len(archives[kind]), digest="sha256:" + hashlib.sha256(archives[kind]).hexdigest())
        if path.startswith("git/ref/tags/"):
            return None
        if path == "releases?per_page=100&page=1":
            return [] if state["release"] is None else [copy.deepcopy(state["release"])]
        if path == "releases" and body is not None:
            assert body["draft"] is body["prerelease"] is True
            assert body["tag_name"] == delivery.tag(SOURCE, android_only=android_only,
                                                     producer_identity=(101, 1) if android_only else None) and body["target_commitish"] == SOURCE
            assert state["release"] is None
            state["writes"].append("create")
            state["release"] = dict(release(android_only=android_only), **(release_damage or {}))
            state["release"]["body"] = body["body"]
            state["release"]["html_url"] = "https://github.com/" + delivery.REPO + "/releases/tag/untagged-fixture"
        elif path == "releases/17" and method == "PATCH":
            assert body["draft"] is body["prerelease"] is True
            assert body["tag_name"] == delivery.tag(SOURCE, android_only=android_only,
                                                     producer_identity=(101, 1) if android_only else None) and body["target_commitish"] == SOURCE
            state["patches"].append(body)
            state["release"]["body"] = body["body"]
            slug = "untagged-fixture-token" if untagged_final else body["tag_name"]
            state["release"]["html_url"] = "https://github.com/" + delivery.REPO + "/releases/tag/" + slug
            for item in state["release"]["assets"]:
                item["browser_download_url"] = "https://github.com/" + delivery.REPO + "/releases/download/" + slug + "/" + item["name"]
        else:
            assert path == "releases/17" and body is None
        return copy.deepcopy(state["release"])

    def download(path, destination, *, size, digest):
        if path.startswith("actions/artifacts/"):
            kind = "android" if "/23/" in path else "ios"
            raw = archives[kind]
        else:
            raw = state["bytes"][int(path.rsplit("/", 1)[1])]
            if corrupt_readback:
                raw = b"x" + raw[1:]
        delivery.need(len(raw) == size and hashlib.sha256(raw).hexdigest() == digest, "readback differs")
        destination.write_bytes(raw)

    def upload(checked_release, path):
        assert checked_release["id"] == 17 and checked_release["target_commitish"] == SOURCE
        identifier = 1000 + len(state["release"]["assets"])
        state["writes"].append("upload:" + path.name)
        state["bytes"][identifier] = path.read_bytes()
        state["release"]["assets"].append({"id": identifier, "name": path.name, "size": path.stat().st_size,
            "digest": "sha256:" + delivery.sha(path), "state": "uploaded"})
    monkeypatch.setattr(delivery, "api", api)
    monkeypatch.setattr(delivery, "download", download)
    monkeypatch.setattr(delivery, "upload", upload)
    monkeypatch.setattr(delivery, "android_files", lambda folder, source: ([folder / delivery.APK, folder / delivery.APK_REPORT], {"same_process": True}))
    def ios_files(folder, source):
        assert not android_only, "Android-only staging must never inspect or require an IPA"
        return [folder / delivery.ipa_name(source), folder / delivery.ipa_name(source).replace(".ipa", ".report.json")], {"same_process": True}
    monkeypatch.setattr(delivery, "ios_files", ios_files)
    return state


def test_stage_reads_back_six_assets_and_keeps_tag_source_in_final_draft_patch(tmp_path, monkeypatch):
    state = stage_fixture(monkeypatch)
    proof = delivery.stage(SOURCE, tmp_path / "work")
    assert proof["stage"] == "verified_exact_draft" and proof["published"] is False
    assert len(proof["verified_assets"]) == 6 and all(row["complete_download_verified"] for row in proof["verified_assets"])
    assert proof["release_url"] == "https://github.com/" + delivery.REPO + "/releases/tag/" + delivery.tag(SOURCE)
    assert len(state["patches"]) == 1 and len([item for item in state["writes"] if item.startswith("upload:")]) == 6
    assert state["patches"][0]["tag_name"] == delivery.tag(SOURCE)
    assert state["patches"][0]["target_commitish"] == SOURCE


def test_valid_untagged_url_is_captured_after_last_patch_without_repair(tmp_path, monkeypatch):
    state = stage_fixture(monkeypatch, untagged_final=True)
    proof = delivery.stage(SOURCE, tmp_path / "work")
    assert proof["release_url"] == "https://github.com/" + delivery.REPO + "/releases/tag/untagged-fixture-token"
    assert len(state["patches"]) == 1
    assert all("/releases/download/untagged-fixture-token/" in row["browser_download_url"] for row in proof["verified_assets"])


@pytest.mark.parametrize("url", ["https://evil.example/releases/tag/untagged-fixture", "http://github.com/" + delivery.REPO + "/releases/tag/untagged-x",
    "https://github.com/foreign/repo/releases/tag/untagged-x", "https://github.com/" + delivery.REPO + "/releases/tag/untagged-x?token=secret",
    "https://github.com/" + delivery.REPO + "/releases/tag/other-preview"])
def test_final_draft_url_cannot_redirect_to_another_origin_repo_or_preview(url):
    with pytest.raises(ValueError):
        delivery.final_page_url(url, SOURCE)


def test_readback_failure_never_patches_publishes_or_uploads_later_assets(tmp_path, monkeypatch):
    state = stage_fixture(monkeypatch, corrupt_readback=True)
    with pytest.raises(ValueError, match="readback"):
        delivery.stage(SOURCE, tmp_path / "work")
    assert state["writes"] == ["create", "upload:" + delivery.APK]
    assert state["patches"] == [] and state["release"]["draft"] is True
    proof = json.loads((tmp_path / "work/draft-staging-proof.json").read_text())
    assert proof["stage"] == "stopped" and proof["published"] is False


def actions_context(monkeypatch, *, android_only):
    values = {"GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": delivery.REPO, "GITHUB_SHA": SOURCE,
              "GITHUB_REF": delivery.BRANCH, "GITHUB_WORKFLOW_REF": delivery.REPO + "/" + delivery.WORKFLOW + "@" + delivery.BRANCH,
              "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_RUN_ID": "101", "GITHUB_RUN_ATTEMPT": "2",
              "GITHUB_JOB": "android-draft-stage" if android_only else "draft-stage", "ANDROID_ARTIFACT_ID": "23"}
    for key, value in values.items():monkeypatch.setenv(key, value)
    monkeypatch.delenv("IOS_ARTIFACT_ID", raising=False)
    if not android_only:monkeypatch.setenv("IOS_ARTIFACT_ID", "24")


def test_android_context_accepts_only_the_dedicated_current_source_job_without_ipa(monkeypatch):
    actions_context(monkeypatch, android_only=True)
    assert delivery.context(SOURCE, android_only=True) == (101, 2)
    with pytest.raises(ValueError, match="staging_job_not_allowed"):
        delivery.context(SOURCE)
    for key, value in (("GITHUB_JOB", "draft-stage"), ("GITHUB_SHA", "b" * 40), ("GITHUB_REPOSITORY", "foreign/repo"),
                       ("GITHUB_EVENT_NAME", "pull_request"), ("GITHUB_REF", "refs/heads/main"),
                       ("GITHUB_RUN_ATTEMPT", "0"), ("ANDROID_ARTIFACT_ID", "")):
        with monkeypatch.context() as scoped:
            scoped.setenv(key, value)
            with pytest.raises(ValueError):delivery.context(SOURCE, android_only=True)
    actions_context(monkeypatch, android_only=False)
    assert delivery.context(SOURCE) == (101, 2)
    with pytest.raises(ValueError, match="staging_job_not_allowed"):
        delivery.context(SOURCE, android_only=True)


def test_android_only_producer_context_cannot_be_used_for_combined_or_recovery_delivery():
    android = delivery.ProducerContext(101, 2, (("android", 23, "b" * 64),))
    assert delivery.producer_context_gate(android, android_only=True) == android
    with pytest.raises(ValueError, match="explicit_artifact_context_required"):
        delivery.producer_context_gate(android)
    combined = delivery.ProducerContext(101, 2, (("android", 23, "b" * 64), ("ios", 24, "c" * 64)))
    assert delivery.producer_context_gate(combined) == combined
    with pytest.raises(ValueError, match="explicit_artifact_context_required"):
        delivery.producer_context_gate(combined, android_only=True)


@pytest.mark.parametrize("untagged", [False, True])
def test_android_first_stages_four_fully_read_back_assets_without_claiming_ipa_or_execution(tmp_path, monkeypatch, untagged):
    state = stage_fixture(monkeypatch, android_only=True, untagged_final=untagged)
    monkeypatch.delenv("IOS_ARTIFACT_ID", raising=False)
    monkeypatch.delenv("IOS_ARTIFACT_SHA", raising=False)
    proof = delivery.stage_android(SOURCE, tmp_path / "android-work")
    assert proof["tag"] == "android-mp4-preview-" + delivery.VERSION + "-" + SOURCE[:7] + "-r101-a1"
    assert proof["tag"] != delivery.tag(SOURCE)
    assert proof["stage"] == "verified_exact_draft" and proof["published"] is False
    assert proof["scope"] == "android-only"
    assert len(proof["verified_assets"]) == 4
    assert {row["name"] for row in proof["verified_assets"]} == {
        delivery.APK, delivery.APK_REPORT, delivery.ANDROID_VERIFICATION, "SHA256SUMS"}
    assert all(row["complete_download_verified"] is True for row in proof["verified_assets"])
    assert set(proof["artifacts"]) == {"android"}
    assert "actions/artifacts/24" not in state["requests"]
    assert len(state["patches"]) == 1
    assert state["patches"][0]["draft"] is state["patches"][0]["prerelease"] is True
    manifest = json.loads((tmp_path / "android-work" / delivery.ANDROID_VERIFICATION).read_text())
    assert manifest["scope"] == "android-only" and set(manifest["checks"]) == {"android"}
    for key in ("ios_package_verified", "core_runtime_execution_verified", "device_execution_verified", "actual_game_mv_verified"):
        assert manifest[key] is False
    assert manifest["producer_run_id"] == 101 and manifest["producer_run_attempt"] == 1
    assert manifest["codec_workflow"]["source_commit"] == SOURCE
    assert "ios" not in manifest["background"]
    assert (tmp_path / "android-work/android-draft-staging-proof.json").is_file()
    assert not (tmp_path / "android-work/draft-staging-proof.json").exists()
    assert (tmp_path / "android-work/SHA256SUMS").read_text() == "".join(
        f"{delivery.sha(tmp_path / 'android-work' / name) if name == delivery.ANDROID_VERIFICATION else delivery.sha(tmp_path / 'android-work/android' / name)}  {name}\n"
        for name in sorted((delivery.APK, delivery.APK_REPORT, delivery.ANDROID_VERIFICATION)))


@pytest.mark.parametrize("damage", [{"head_sha": "b" * 40}, {"head_repository": {"full_name": "foreign/repo"}},
                                    {"id": 100}, {"path": ".github/workflows/foreign.yml"}])
def test_android_first_rejects_foreign_or_stale_source_before_release_mutation(tmp_path, monkeypatch, damage):
    state = stage_fixture(monkeypatch, android_only=True, producer_damage=damage)
    with pytest.raises(ValueError, match="producer_run_source_differs"):
        delivery.stage_android(SOURCE, tmp_path / "work")
    assert state["writes"] == [] and state["patches"] == []


@pytest.mark.parametrize("damage", [{"draft": False}, {"published_at": "2026-11-21"}, {"target_commitish": "b" * 40},
                                    {"upload_url": "https://uploads.github.com/repos/foreign/repo/releases/17/assets{?name,label}"}])
def test_android_first_never_uploads_to_foreign_published_or_wrong_source_release(tmp_path, monkeypatch, damage):
    state = stage_fixture(monkeypatch, android_only=True, release_damage=damage)
    with pytest.raises(ValueError):delivery.stage_android(SOURCE, tmp_path / "work")
    assert state["writes"] == ["create"] and state["patches"] == []


def test_android_first_rejects_previous_attempt_draft_before_upload(tmp_path, monkeypatch):
    state = stage_fixture(monkeypatch, android_only=True, existing_attempt=2)
    with pytest.raises(ValueError, match="android_draft_producer_attempt_differs"):
        delivery.stage_android(SOURCE, tmp_path / "work")
    assert state["writes"] == [] and state["patches"] == []


def test_android_first_resumes_only_same_attempt_exact_asset_bytes(tmp_path, monkeypatch):
    state = stage_fixture(monkeypatch, android_only=True, existing_attempt=1)
    state["bytes"][999] = b"apk"
    state["release"]["assets"] = [{"id":999,"name":delivery.APK,"size":3,"state":"uploaded",
                                   "digest":"sha256:" + hashlib.sha256(b"apk").hexdigest()}]
    proof = delivery.stage_android(SOURCE, tmp_path / "work")
    assert proof["stage"] == "verified_exact_draft"
    assert len(proof["verified_assets"]) == 4
    assert len(state["writes"]) == 3 and "upload:" + delivery.APK not in state["writes"]


@pytest.mark.parametrize("damage", [{"id":22}, {"digest":"sha256:" + "f" * 64}, {"expired":True},
    {"name":"mp4-android-preview-" + SOURCE + "-2"}, {"workflow_run":{"id":100,"head_sha":SOURCE}},
    {"workflow_run":{"id":101,"head_sha":"b" * 40}}])
def test_android_first_checks_authoritative_artifact_id_digest_source_and_attempt(tmp_path, monkeypatch, damage):
    state = stage_fixture(monkeypatch, android_only=True)
    api = delivery.api
    def damaged(path, **kwargs):
        value = api(path, **kwargs)
        return {**value, **damage} if path == "actions/artifacts/23" else value
    monkeypatch.setattr(delivery, "api", damaged)
    with pytest.raises(ValueError, match="artifact_source_or_identity_differs"):
        delivery.stage_android(SOURCE, tmp_path / "work")
    assert state["writes"] == [] and state["patches"] == []


def test_android_first_rejects_failed_package_source_checks_before_any_release_api(tmp_path, monkeypatch):
    state = stage_fixture(monkeypatch, android_only=True)
    def invalid_package(folder, source):raise ValueError("source_bytes_changed")
    monkeypatch.setattr(delivery, "android_files", invalid_package)
    with pytest.raises(ValueError, match="source_bytes_changed"):
        delivery.stage_android(SOURCE, tmp_path / "work")
    assert state["writes"] == [] and not any(path.startswith("releases") for path in state["requests"])


def test_android_draft_cannot_absorb_combined_assets_or_combined_tag_urls():
    names = {delivery.APK, delivery.APK_REPORT, delivery.ANDROID_VERIFICATION, "SHA256SUMS"}
    wrong = release(android_only=True)
    wrong["assets"] = [{"id":42,"name":delivery.ipa_name(SOURCE)}]
    with pytest.raises(ValueError, match="draft_unknown_or_duplicate_assets"):
        delivery.release_gate(wrong, SOURCE, names, android_only=True, producer_identity=(101, 1))
    with pytest.raises(ValueError, match="final_draft_url_invalid"):
        delivery.final_page_url("https://github.com/" + delivery.REPO + "/releases/tag/" + delivery.tag(SOURCE),
                                SOURCE, android_only=True, producer_identity=(101, 1))
    with pytest.raises(ValueError, match="final_asset_url_invalid"):
        delivery.final_asset_url("https://github.com/" + delivery.REPO + "/releases/download/" + delivery.tag(SOURCE) + "/" + delivery.APK,
                                 SOURCE, delivery.APK, android_only=True, producer_identity=(101, 1))


def test_android_producer_tags_separate_same_source_attempts_and_independent_runs(monkeypatch):
    contexts = ((101, 1), (101, 2), (102, 1))
    tags = {identity:delivery.tag(SOURCE, android_only=True, producer_identity=identity) for identity in contexts}
    assert len(set(tags.values())) == 3
    assert delivery.tag(SOURCE) not in tags.values()
    assert tags[(101, 1)].endswith("-r101-a1") and tags[(101, 2)].endswith("-r101-a2")
    old = release(android_only=True)
    calls = []
    def api(path, **kwargs):
        calls.append(path)
        assert path == "releases?per_page=100&page=1", "A new producer must not fetch or reuse the old producer's release"
        return [old]
    monkeypatch.setattr(delivery, "api", api)
    for identity in contexts[1:]:
        assert delivery.find_draft(SOURCE, {delivery.APK}, android_only=True, producer_identity=identity) is None
        with pytest.raises(ValueError, match="exact_unpublished_draft_required"):
            delivery.release_gate(old, SOURCE, {delivery.APK}, android_only=True, producer_identity=identity)
    assert calls == ["releases?per_page=100&page=1"] * 2


@pytest.mark.parametrize("identity", [None, (101, True), (0, 1), [101, 1], (101,), ("101", 1)])
def test_android_namespace_requires_exact_positive_producer_identity_before_any_api(monkeypatch, identity):
    def forbidden(*args, **kwargs):raise AssertionError("Missing producer context must fail before API access")
    monkeypatch.setattr(delivery, "api", forbidden)
    for action in (lambda:delivery.tag(SOURCE, android_only=True, producer_identity=identity),
                   lambda:delivery.tag_source_gate(SOURCE, android_only=True, producer_identity=identity),
                   lambda:delivery.find_draft(SOURCE, {delivery.APK}, android_only=True, producer_identity=identity)):
        with pytest.raises(ValueError, match="android_producer_identity_required"):action()


def test_android_first_readback_failure_keeps_draft_and_stops_all_later_assets(tmp_path, monkeypatch):
    state = stage_fixture(monkeypatch, android_only=True, corrupt_readback=True)
    with pytest.raises(ValueError, match="readback"):
        delivery.stage_android(SOURCE, tmp_path / "work")
    assert state["writes"] == ["create", "upload:" + delivery.APK]
    assert state["patches"] == [] and state["release"]["draft"] is True
    proof = json.loads((tmp_path / "work/android-draft-staging-proof.json").read_text())
    assert proof["stage"] == "stopped" and proof["published"] is False


def test_android_first_waits_for_current_source_codec_gate_before_any_release_api(tmp_path, monkeypatch):
    state = stage_fixture(monkeypatch, android_only=True)
    def failed(source):
        assert source == SOURCE
        raise ValueError("current_source_codec_workflow_failed")
    monkeypatch.setattr(delivery, "wait_codecs", failed)
    with pytest.raises(ValueError, match="current_source_codec_workflow_failed"):
        delivery.stage_android(SOURCE, tmp_path / "work")
    assert state["requests"] == [] and state["writes"] == []


def test_android_first_job_has_only_android_dependency_and_distinct_proof_without_context_spoofing():
    raw = (delivery.ROOT / delivery.WORKFLOW).read_text()
    job = raw.split("  android-draft-stage:\n", 1)[1].split("  ios-build:\n", 1)[0]
    assert "needs: [android-build]" in job and "ios-build" not in job
    assert "github.event_name == 'workflow_dispatch' && inputs.upload_draft" in job
    assert "github.event_name == 'push' || inputs.upload_draft" not in raw
    assert "stage-android --source" in job
    assert "ANDROID_ARTIFACT_ID: ${{ needs.android-build.outputs.artifact_id }}" in job
    assert "ANDROID_ARTIFACT_SHA: ${{ needs.android-build.outputs.artifact_sha }}" in job
    assert "IOS_ARTIFACT_ID" not in job and "GITHUB_JOB:" not in job
    assert "mp4-android-draft-proof-${{ github.sha }}-${{ github.run_attempt }}" in job
    assert "android-draft-staging-proof.json" in job
    assert "contents: write" in job and "actions: read" in job
    assert "tests/test_mp4_runtime_type_validation.py" in raw
