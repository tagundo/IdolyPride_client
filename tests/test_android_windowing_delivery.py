from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import stage_android_windowing_preview as delivery

SOURCE = "a" * 40


def provenance(apk):
    return {"schema": 1, "source_commit": SOURCE, "working_tree_snapshot": False,
        "prototype": True, "release_eligible": False,
        "compiled_source_unchanged_during_build": True, "public_apk_inputs_unchanged": True,
        "apk_bytes": apk.stat().st_size, "apk_sha256": delivery.sha(apk),
        "signed_certificate_sha256": delivery.CERTIFICATE,
        "marker": {"languages": ["ko", "ja", "en"], "process_mode": "same", "min_sdk": 30},
        "preservation": {"original_dex_and_sdk_native_unchanged": True, "resources_arsc_unchanged": True,
            "owned_presentation_addon_replaced": True,
            "changed_original_members": ["AndroidManifest.xml", "lib/arm64-v8a/libidoly_presentation.so"]},
        "native_addon_build": {"abi": "arm64-v8a", "source_commit": SOURCE,
            "shared_cache_hooks": 5, "runtime_symbols_hidden": True,
            "source_unchanged_during_build": True, "sha256": "b" * 64, "bytes": 123},
        "windowing": {"application_resizable": True, "game_resizable": True, "menu_resizable": True,
            "game_config_changes": sorted(delivery.REQUIRED_CHANGES), "game_orientation": "fullUser",
            "menu_configuration_handling": "recreate_with_saved_state", "aspect_ratio_restricted": False},
        "inputs": {"client_sha256": delivery.CLIENTS["ko"]["sha256"],
            "language_clients": delivery.CLIENTS, "server_sha256": delivery.SERVER_SHA,
            "chaquopy_jar_sha256": delivery.CHAQUOPY_SHA}, "tools": {"editor": delivery.EDITOR_SHA},
        "source_files": [{"path": name, "bytes": 1, "sha256": "c" * 64}
                         for name in sorted(delivery.REQUIRED_SOURCES)]}


@pytest.fixture
def candidate(tmp_path):
    folder = tmp_path / "output"
    folder.mkdir()
    apk = folder / delivery.APK
    apk.write_bytes(b"candidate-apk")
    value = provenance(apk)
    (folder / delivery.REPORT).write_text(json.dumps(value))
    return folder, value


@pytest.fixture
def context(monkeypatch):
    values = {"GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": delivery.REPO,
        "GITHUB_SHA": SOURCE, "GITHUB_REF": delivery.BRANCH,
        "GITHUB_WORKFLOW_REF": delivery.REPO + "/" + delivery.WORKFLOW + "@" + delivery.BRANCH,
        "GITHUB_EVENT_NAME": "push", "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1",
        "BUILD_ARTIFACT_URL": "https://github.com/" + delivery.REPO + "/actions/runs/123/artifacts/456"}
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    return values


def draft():
    return {"id": 77, "draft": True, "prerelease": True, "tag_name": delivery.tag(SOURCE),
        "target_commitish": SOURCE, "assets": [], "html_url": "https://github.com/" + delivery.REPO + "/releases/tag/" + delivery.tag(SOURCE)}


def fake_github(monkeypatch, *, existing=None, readback_change=False):
    state = {"release": copy.deepcopy(existing), "writes": [], "bytes": {}, "created": None}

    def api(path, *, body=None, absent=False):
        if path.startswith("git/ref/tags/"):
            return None
        if path == "releases" and body is not None:
            assert state["release"] is None
            state["writes"].append("create")
            state["created"] = copy.deepcopy(body)
            state["release"] = draft()
        elif path.startswith("releases/tags/"):
            assert absent is True
        else:
            assert path == "releases/77" and body is None
        return copy.deepcopy(state["release"])

    def upload(args, **kwargs):
        assert args[:4] == ["gh", "release", "upload", delivery.tag(SOURCE)]
        assert "--clobber" not in args and args[-2:] == ["--repo", delivery.REPO]
        path = Path(args[4])
        data = path.read_bytes()
        asset_id = 100 + len(state["release"]["assets"])
        state["writes"].append("upload:" + path.name)
        state["bytes"][asset_id] = data
        state["release"]["assets"].append({"id": asset_id, "name": path.name,
            "state": "uploaded", "size": len(data), "digest": "sha256:" + delivery.sha(path)})
        return SimpleNamespace(returncode=0)

    def download(path, target):
        assert path.startswith("releases/assets/")
        value = state["bytes"][int(path.rsplit("/", 1)[1])]
        target.write_bytes((b"x" + value[1:]) if readback_change else value)

    monkeypatch.setattr(delivery, "api", api)
    monkeypatch.setattr(delivery.subprocess, "run", upload)
    monkeypatch.setattr(delivery, "download_api", download)
    return state


def test_checksum_is_idempotent_but_never_replaces_conflicting_file(candidate):
    folder, _ = candidate
    paths = delivery.checksums(folder, SOURCE)
    assert [p.name for p in paths] == [delivery.APK, delivery.REPORT, "SHA256SUMS"]
    assert delivery.checksums(folder, SOURCE) == paths
    assert (folder / delivery.SUMS).read_text().count("\n") == 2
    (folder / delivery.SUMS).write_text("old checksum\n")
    with pytest.raises(ValueError, match="existing_checksums"):
        delivery.checksums(folder, SOURCE)
    assert (folder / delivery.SUMS).read_text() == "old checksum\n"


@pytest.mark.parametrize("section,key,value", [
    (None, "source_commit", "d" * 40), (None, "working_tree_snapshot", True),
    (None, "compiled_source_unchanged_during_build", False), (None, "public_apk_inputs_unchanged", False),
    (None, "prototype", False), (None, "release_eligible", True),
    ("windowing", "application_resizable", False), ("windowing", "game_resizable", False),
    ("windowing", "menu_resizable", False), ("windowing", "menu_resizable", 1),
    ("windowing", "game_config_changes", ["orientation", "screenSize"]),
    ("windowing", "game_config_changes", sorted(delivery.REQUIRED_CHANGES) + ["density"]),
    ("windowing", "game_orientation", "portrait"), ("windowing", "aspect_ratio_restricted", True),
    ("windowing", "menu_configuration_handling", "ignore"),
    ("marker", "languages", ["ko"]), ("marker", "process_mode", "separate"), ("marker", "min_sdk", 28),
    ("native_addon_build", "source_commit", "0" * 40), ("native_addon_build", "shared_cache_hooks", 0),
    ("native_addon_build", "runtime_symbols_hidden", False), ("native_addon_build", "source_unchanged_during_build", False),
    ("native_addon_build", "abi", "x86_64"),
    ("preservation", "resources_arsc_unchanged", False),
    ("preservation", "original_dex_and_sdk_native_unchanged", False),
    ("preservation", "changed_original_members", ["AndroidManifest.xml", "classes.dex"]),
    (None, "signed_certificate_sha256", "0" * 64), ("inputs", "server_sha256", "0" * 64),
    ("inputs", "language_clients", {}), ("tools", "editor", "0" * 64), (None, "source_files", []),
])
def test_provenance_guards_before_any_delivery(candidate, section, key, value):
    folder, proof = candidate
    (proof if section is None else proof[section])[key] = value
    (folder / delivery.REPORT).write_text(json.dumps(proof))
    with pytest.raises(ValueError):
        delivery.apk_files(folder, SOURCE)


def test_apk_byte_change_and_report_symlink_are_rejected(candidate, tmp_path):
    folder, _ = candidate
    (folder / delivery.APK).write_bytes(b"changed")
    with pytest.raises(ValueError, match="apk_bytes"):
        delivery.apk_files(folder, SOURCE)
    report = folder / delivery.REPORT
    report.rename(tmp_path / "report.json")
    report.symlink_to(tmp_path / "report.json")
    with pytest.raises(ValueError, match="regular_bounded"):
        delivery.apk_files(folder, SOURCE)


def test_json_duplicates_and_nonfinite_constants_fail():
    for raw in (b'{"source_commit":"a","source_commit":"b"}', b'{"schema":NaN}'):
        with pytest.raises(ValueError):
            delivery.json_value(raw)


@pytest.mark.parametrize("key,value", [("GITHUB_ACTIONS", "false"), ("GITHUB_REPOSITORY", "fork/repo"),
    ("GITHUB_SHA", "b" * 40), ("GITHUB_REF", "refs/heads/main"),
    ("GITHUB_EVENT_NAME", "pull_request"), ("GITHUB_WORKFLOW_REF", "other workflow"),
    ("GITHUB_RUN_ID", "0"), ("GITHUB_RUN_ATTEMPT", "x"),
    ("BUILD_ARTIFACT_URL", "https://github.com/" + delivery.REPO + "/actions/runs/999/artifacts/456")])
def test_stage_requires_exact_actions_producer(context, monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    with pytest.raises(ValueError):
        delivery.actions_context(SOURCE)


@pytest.mark.parametrize("key,value", [("draft", False), ("prerelease", False), ("id", True),
    ("target_commitish", "main"), ("target_commitish", "b" * 40), ("tag_name", "shared-resources-preview-2026.11.20-old")])
def test_reject_published_old_or_unbound_release(key, value):
    release = draft()
    release[key] = value
    with pytest.raises(ValueError, match="exact_draft"):
        delivery.release_gate(release, SOURCE, names=[delivery.APK, delivery.REPORT, delivery.SUMS])


def test_asset_inventory_rejects_ipa_unknown_name_and_duplicates():
    for assets in ([{"id": 1, "name": "old.ipa"}], [{"id": 1, "name": delivery.APK}] * 2):
        release = dict(draft(), assets=assets)
        with pytest.raises(ValueError, match="unreviewed_or_duplicate"):
            delivery.release_gate(release, SOURCE, names=[delivery.APK, delivery.REPORT, delivery.SUMS])


def test_create_only_new_draft_and_read_back_all_three_assets(candidate, context, monkeypatch, tmp_path):
    state = fake_github(monkeypatch)
    proof = delivery.stage(candidate[0], tmp_path / "staging", SOURCE)
    assert state["created"]["draft"] is state["created"]["prerelease"] is True
    assert state["created"]["target_commitish"] == SOURCE
    assert state["created"]["tag_name"] == "android-windowing-preview-2026.11.20.1-aaaaaaa"
    assert state["created"]["make_latest"] == "false"
    assert proof["stage"] == "verified_exact_draft" and proof["published"] is False
    assert proof["release_id"] == 77 and len(proof["verified_assets"]) == 3
    assert all(row["complete_download_verified"] is True for row in proof["verified_assets"])
    assert proof["android_producer"]["build_artifact_url"] == context["BUILD_ARTIFACT_URL"]
    assert not any(".ipa" in write for write in state["writes"])
    assert state["writes"] == ["create", "upload:" + delivery.APK, "upload:" + delivery.REPORT, "upload:SHA256SUMS"]
    # A retry reads matching assets without replacing or re-uploading anything.
    state["writes"].clear()
    again = delivery.stage(candidate[0], tmp_path / "retry", SOURCE)
    assert again["verified_assets"] == proof["verified_assets"] and state["writes"] == []


def test_wrong_existing_release_causes_no_writes(candidate, context, monkeypatch, tmp_path):
    state = fake_github(monkeypatch, existing=dict(draft(), draft=False))
    with pytest.raises(ValueError, match="exact_draft"):
        delivery.stage(candidate[0], tmp_path / "staging", SOURCE)
    assert state["writes"] == []


def test_existing_asset_full_hash_conflict_prevents_any_other_upload(candidate, context, monkeypatch, tmp_path):
    folder, _ = candidate
    existing = dict(draft(), assets=[{"id": 12, "name": delivery.APK, "state": "uploaded",
                                    "size": (folder / delivery.APK).stat().st_size, "digest": None}])
    state = fake_github(monkeypatch, existing=existing)
    state["bytes"][12] = b"wrong-content"
    with pytest.raises(ValueError, match="readback"):
        delivery.stage(folder, tmp_path / "staging", SOURCE)
    assert state["writes"] == []


def test_new_upload_readback_failure_stops_and_keeps_sanitized_receipt(candidate, context, monkeypatch, tmp_path):
    state = fake_github(monkeypatch, readback_change=True)
    with pytest.raises(ValueError, match="readback"):
        delivery.stage(candidate[0], tmp_path / "staging", SOURCE)
    assert state["writes"] == ["create", "upload:" + delivery.APK]
    proof = json.loads((tmp_path / "staging/draft-staging-proof.json").read_text())
    assert proof["stage"] == "stopped" and proof["error_type"] == "ValueError"
    assert proof["verified_assets"] == [] and proof["published"] is False


def test_existing_git_tag_cannot_redirect_source(monkeypatch):
    monkeypatch.setattr(delivery, "api", lambda *args, **kwargs: {"object": {"type": "commit", "sha": "b" * 40}})
    with pytest.raises(ValueError, match="tag_source"):
        delivery.existing_tag_gate(SOURCE)


def test_workflow_scope_source_and_apk_only_delivery_are_fixed():
    root = Path(__file__).resolve().parents[1]
    raw = (root / delivery.WORKFLOW).read_text()
    scoped = raw.split("    paths:\n", 1)[1].split("  workflow_dispatch:", 1)[0]
    assert [line.removeprefix("      - ") for line in scoped.splitlines() if line.strip()] == [
        delivery.WORKFLOW, "tools/stage_android_windowing_preview.py", "tests/test_android_windowing_delivery.py"]
    assert "SOURCE_SHA: ${{ github.sha }}" in raw and "ref: ${{ github.sha }}" in raw
    assert delivery.APK in raw and "stage_shared_preview.py fetch" in raw
    assert "stage_shared_preview.py stage" not in raw and ".ipa" not in raw and "macos-" not in raw
    assert "--native-bridge" in raw and "--native-receipt" in raw and "--client-ja-apk" in raw and "--client-en-apk" in raw
    assert "if: always()" in raw and "steps.apk_artifact.outputs.artifact-url" in raw
    assert "release publish" not in raw and "--clobber" not in raw
