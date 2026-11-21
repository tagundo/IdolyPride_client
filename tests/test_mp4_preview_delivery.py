from __future__ import annotations
import copy
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile, ZipInfo

import pytest

from tools import stage_mp4_preview as delivery

SOURCE = "a" * 40


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


def release():
    return {"id": 17, "tag_name": delivery.tag(SOURCE), "target_commitish": SOURCE,
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
        "tools/package_android_unified.py", "tests/test_android_unified_badging.py", "tests/test_ios_mp4_queue_host.py"]
    assert "SOURCE_SHA: ${{ github.sha }}" in raw and raw.count("ref: ${{ github.sha }}") == 3
    assert "needs: [android-build, ios-build]" in raw and "inputs.upload_draft" in raw
    assert "IDOLY_RELEASE_VERSION: 2026.11.21.4" in raw and delivery.APK in raw
    assert "ios-unified/native/test_mp4_ui_compile.py" in raw and "ios-unified/ci_build.py" in raw
    assert raw.index("test_mp4_ui_compile.py") < raw.index("ios-unified/ci_build.py")
    assert "stage_shared_preview.py fetch" in raw and "stage_shared_preview.py stage" not in raw
    assert "macos-server/build_app.py" not in raw and "gh release" not in raw
    assert "ANDROID_ARTIFACT_ID: ${{ needs.android-build.outputs.artifact_id }}" in raw
    assert "IOS_ARTIFACT_ID: ${{ needs.ios-build.outputs.artifact_id }}" in raw
    assert "continue-on-error" not in raw


def stage_fixture(monkeypatch, *, corrupt_readback=False, untagged_final=False):
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
    state = {"release": None, "writes": [], "bytes": {}, "patches": []}
    monkeypatch.setattr(delivery, "context", lambda source: (101, 1))
    monkeypatch.setattr(delivery, "wait_codecs", lambda source: {"run_id": 301, "source_commit": source})
    for kind, identifier in (("android", 23), ("ios", 24)):
        monkeypatch.setenv(kind.upper() + "_ARTIFACT_ID", str(identifier))
        monkeypatch.setenv(kind.upper() + "_ARTIFACT_SHA", hashlib.sha256(archives[kind]).hexdigest())

    def api(path, *, body=None, method=None, absent=False):
        if path == "actions/runs/101":
            return producer()
        if path == "actions/runs/101/jobs?per_page=100":
            return {"jobs": [{"name": kind + "-build", "status": "completed", "conclusion": "success", "run_attempt": 1}
                             for kind in ("android", "ios")]}
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
            assert body["tag_name"] == delivery.tag(SOURCE) and body["target_commitish"] == SOURCE
            assert state["release"] is None
            state["writes"].append("create")
            state["release"] = release()
            state["release"]["html_url"] = "https://github.com/" + delivery.REPO + "/releases/tag/untagged-fixture"
        elif path == "releases/17" and method == "PATCH":
            assert body["draft"] is body["prerelease"] is True
            assert body["tag_name"] == delivery.tag(SOURCE) and body["target_commitish"] == SOURCE
            state["patches"].append(body)
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
    monkeypatch.setattr(delivery, "ios_files", lambda folder, source: ([folder / delivery.ipa_name(source), folder / delivery.ipa_name(source).replace(".ipa", ".report.json")], {"same_process": True}))
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
