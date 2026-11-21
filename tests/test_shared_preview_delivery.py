from __future__ import annotations
import copy
import json
from pathlib import Path

import pytest

from tools import stage_shared_preview as delivery


def draft():
    return {"id": delivery.RELEASE, "draft": True, "prerelease": True,
            "tag_name": delivery.TAG, "target_commitish": delivery.SOURCE, "assets": []}


def mac():
    return {"id": delivery.MAC_RUN, "status": "completed", "conclusion": "success",
            "head_sha": delivery.SOURCE, "event": "workflow_dispatch",
            "path": ".github/workflows/build-server-apps.yml", "head_repository": {"full_name": delivery.REPO}}


def artifact():
    return {"id": 123, "name": delivery.ARTIFACT, "expired": False,
            "size_in_bytes": 42, "digest": "sha256:" + "a" * 64}


@pytest.mark.parametrize("field,value", [("draft", False), ("id", 9), ("tag_name", "latest"),
                                         ("target_commitish", "main"), ("prerelease", False)])
def test_never_stage_to_published_or_different_release(field, value):
    value_dict = draft()
    value_dict[field] = value
    with pytest.raises(ValueError, match="exact_draft"):
        delivery.release_gate(value_dict)


@pytest.mark.parametrize("field,value", [("status", "in_progress"), ("conclusion", "failure"),
    ("head_sha", "0" * 40), ("id", 99), ("event", "pull_request"), ("path", ".github/workflows/other.yml")])
def test_mac_must_be_exact_successful_producer(field, value):
    run = mac()
    run[field] = value
    with pytest.raises(ValueError, match="mac_producer"):
        delivery.mac_gate(run, [artifact()])


def test_artifact_requires_unique_name_lifetime_and_digest():
    assert delivery.mac_gate(mac(), [artifact()])["id"] == 123
    for rows in ([], [artifact(), artifact()], [dict(artifact(), expired=True)],
                 [dict(artifact(), digest=None)], [dict(artifact(), size_in_bytes=0)]):
        with pytest.raises((ValueError, TypeError)):
            delivery.mac_gate(mac(), rows)


def test_actions_waits_only_for_exact_pending_producer(monkeypatch):
    pending, complete = dict(mac(), status="in_progress", conclusion=None), mac()
    replies = iter([pending, complete])
    monkeypatch.setattr(delivery, "api", lambda _: next(replies))
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    sleeps = []
    monkeypatch.setattr(delivery.time, "sleep", sleeps.append)
    assert delivery.wait_mac() == complete
    assert sleeps == [30]
    monkeypatch.setattr(delivery, "api", lambda _: dict(pending, head_sha="0" * 40))
    with pytest.raises(ValueError, match="identity"):
        delivery.wait_mac()
    assert sleeps == [30]


def test_mac_failure_does_not_wait_or_retry(monkeypatch):
    failed = dict(mac(), conclusion="failure")
    monkeypatch.setattr(delivery, "api", lambda _: failed)
    monkeypatch.setattr(delivery.time, "sleep", lambda _: pytest.fail("must not wait after failure"))
    assert delivery.wait_mac() == failed


def test_mac_pending_outside_actions_never_sleeps(monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr(delivery, "api", lambda _: dict(mac(), status="in_progress", conclusion=None))
    monkeypatch.setattr(delivery.time, "sleep", lambda _: pytest.fail("local staging must not wait"))
    with pytest.raises(ValueError, match="still_pending"):
        delivery.wait_mac()


def test_actions_mac_wait_stops_at_exact_35_minute_boundary(monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr(delivery, "api", lambda _: dict(mac(), status="in_progress", conclusion=None))
    clock, sleeps = [100.0], []
    monkeypatch.setattr(delivery.time, "monotonic", lambda: clock[0])
    def advance(seconds):
        sleeps.append(seconds)
        clock[0] += seconds
    monkeypatch.setattr(delivery.time, "sleep", advance)
    with pytest.raises(ValueError, match="still_pending"):
        delivery.wait_mac()
    assert delivery.MAC_WAIT_SECONDS == 2100
    assert sum(sleeps) == 2100 and sleeps == [30] * 70


def test_existing_asset_requires_full_hash_readback(tmp_path, monkeypatch):
    path = tmp_path / "candidate.apk"
    path.write_bytes(b"correct")
    asset = {"id": 1, "size": 7, "state": "uploaded", "digest": None}
    monkeypatch.setattr(delivery, "download_api", lambda _, destination: destination.write_bytes(b"changed"))
    with pytest.raises(ValueError, match="readback"):
        delivery.verify_remote(asset, path)
    monkeypatch.setattr(delivery, "download_api", lambda _, destination: destination.write_bytes(b"correct"))
    delivery.verify_remote(asset, path)


def test_mac_gate_failure_makes_no_release_write(tmp_path, monkeypatch):
    apk = tmp_path / "app.apk"
    apk.write_bytes(b"app")
    monkeypatch.setattr(delivery, "api", lambda _: draft())
    monkeypatch.setattr(delivery, "apk_files", lambda _: [apk])
    def fail(_): raise ValueError("mac not complete")
    monkeypatch.setattr(delivery, "fetch_ipa", fail)
    calls = []
    monkeypatch.setattr(delivery.subprocess, "run", lambda *args, **kw: calls.append(args))
    with pytest.raises(ValueError, match="mac not complete"):
        delivery.stage(tmp_path, tmp_path / "stage")
    assert calls == []


def test_apk_requires_clean_frozen_provenance_and_readback(tmp_path):
    apk = tmp_path / delivery.APK
    apk.write_bytes(b"candidate")
    proof = {"source_commit": delivery.SOURCE, "working_tree_snapshot": False, "prototype": True,
        "release_eligible": False, "compiled_source_unchanged_during_build": True,
        "public_apk_inputs_unchanged": True, "apk_bytes": apk.stat().st_size, "apk_sha256": delivery.sha(apk),
        "marker": {"languages": ["ko", "ja", "en"], "process_mode": "same", "min_sdk": 30},
        "preservation": {"original_dex_and_sdk_native_unchanged": True, "resources_arsc_unchanged": True,
                         "owned_presentation_addon_replaced": True},
        "native_addon_build": {"source_commit": delivery.SOURCE, "shared_cache_hooks": 5,
                               "runtime_symbols_hidden": True, "source_unchanged_during_build": True}}
    report = apk.with_suffix(".provenance.json")
    report.write_text(json.dumps(proof))
    assert delivery.apk_files(tmp_path) == [apk, report]
    apk.write_bytes(b"different")
    with pytest.raises(ValueError, match="apk_bytes"):
        delivery.apk_files(tmp_path)
    proof["working_tree_snapshot"] = True
    report.write_text(json.dumps(proof))
    with pytest.raises(ValueError, match="apk_source"):
        delivery.apk_files(tmp_path)


def test_apk_feature_proof_rejects_optional_native_omission_and_partial_language(tmp_path):
    apk = tmp_path / delivery.APK
    apk.write_bytes(b"candidate")
    proof = {"source_commit": delivery.SOURCE, "working_tree_snapshot": False, "prototype": True,
        "release_eligible": False, "compiled_source_unchanged_during_build": True,
        "public_apk_inputs_unchanged": True, "apk_bytes": apk.stat().st_size, "apk_sha256": delivery.sha(apk),
        "marker": {"languages": ["ko", "ja", "en"], "process_mode": "same", "min_sdk": 30},
        "preservation": {"original_dex_and_sdk_native_unchanged": True, "resources_arsc_unchanged": True,
                         "owned_presentation_addon_replaced": True},
        "native_addon_build": {"source_commit": delivery.SOURCE, "shared_cache_hooks": 5,
                               "runtime_symbols_hidden": True, "source_unchanged_during_build": True}}
    report = apk.with_suffix(".provenance.json")
    for section, field, replacement in (("marker", "languages", ["ko"]), ("marker", "min_sdk", 28),
            ("preservation", "owned_presentation_addon_replaced", False),
            ("preservation", "original_dex_and_sdk_native_unchanged", False),
            ("native_addon_build", "source_commit", "0" * 40),
            ("native_addon_build", "shared_cache_hooks", 0), ("native_addon_build", "runtime_symbols_hidden", False)):
        changed = copy.deepcopy(proof)
        changed[section][field] = replacement
        report.write_text(json.dumps(changed))
        with pytest.raises(ValueError, match="apk_shared_feature"):
            delivery.apk_files(tmp_path)
