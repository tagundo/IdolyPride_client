from __future__ import annotations

import copy
import os
from pathlib import Path

import pytest

from tools import recover_mp4_preview_3c0156f as recovery

delivery = recovery.delivery
DELIVERY_SOURCE = "b" * 40
RECOVERY_RUN = 701


def metadata():
    codec = {"id": recovery.CODEC_RUN, "run_attempt": 1, "head_sha": recovery.APP_SOURCE,
        "path": delivery.CODEC_WORKFLOW, "head_repository": {"full_name": delivery.REPO},
        "head_branch": "feat/ios-unified-server", "status": "completed", "conclusion": "success"}
    result = {
        f"actions/runs/{RECOVERY_RUN}": {"id": RECOVERY_RUN, "run_attempt": 1, "head_sha": DELIVERY_SOURCE,
            "path": recovery.WORKFLOW, "head_branch": "feat/ios-unified-server", "event": "push",
            "head_repository": {"full_name": delivery.REPO}},
        f"actions/runs/{recovery.PRODUCER_RUN}": {"id": recovery.PRODUCER_RUN, "run_attempt": 1,
            "head_sha": recovery.APP_SOURCE, "path": delivery.WORKFLOW, "status": "completed",
            "conclusion": "failure", "head_branch": "feat/ios-unified-server", "event": "push",
            "head_repository": {"full_name": delivery.REPO}},
        f"actions/runs/{recovery.PRODUCER_RUN}/jobs?per_page=100": {"jobs": [
            {"name": kind + "-build", "status": "completed", "conclusion": "success", "run_attempt": 1}
            for kind in ("android", "ios")] + [
            {"name": "draft-stage", "status": "completed", "conclusion": "failure", "run_attempt": 1}]},
        f"actions/runs/{recovery.CODEC_RUN}": codec,
        f"actions/runs/{recovery.CODEC_RUN}/jobs?per_page=100": {"jobs": [
            {"name": kind + "-codecs", "status": "completed", "conclusion": "success", "run_attempt": 1}
            for kind in ("apple", "android")]},
    }
    for kind, identifier, digest in recovery.ARTIFACTS:
        result[f"actions/artifacts/{identifier}"] = {"id": identifier,
            "name": f"mp4-{kind}-preview-{recovery.APP_SOURCE}-1", "expired": False,
            "size_in_bytes": 1024, "digest": "sha256:" + digest,
            "workflow_run": {"id": recovery.PRODUCER_RUN, "head_sha": recovery.APP_SOURCE}}
    return result


def install_metadata(monkeypatch, values):
    def api(path, **kwargs):
        assert not kwargs, "Recovery metadata preflight must be read-only"
        return copy.deepcopy(values[path])
    monkeypatch.setattr(delivery, "api", api)


def test_recovery_accepts_only_successful_build_jobs_and_preserves_failed_delivery_history(monkeypatch):
    values = metadata()
    install_metadata(monkeypatch, values)
    proof = recovery.recovery_gate(DELIVERY_SOURCE, RECOVERY_RUN, 1)
    assert proof.run_id == recovery.PRODUCER_RUN and proof.attempt == 1
    assert proof.artifacts == recovery.ARTIFACTS and proof.codec_run_id == recovery.CODEC_RUN
    assert proof.delivery_source_commit == DELIVERY_SOURCE and proof.delivery_run_id == RECOVERY_RUN
    assert values[f"actions/runs/{recovery.PRODUCER_RUN}"]["conclusion"] == "failure"
    assert delivery.producer_context_gate(proof) is proof


@pytest.mark.parametrize("case", ["delivery_source", "delivery_workflow", "producer_source", "producer_attempt",
    "failed_build", "stale_build_attempt", "artifact_digest", "artifact_source", "expired_artifact", "codec_source", "skipped_codec"])
def test_recovery_refuses_stale_foreign_or_unsuccessful_evidence_before_staging(monkeypatch, case):
    values = metadata()
    current = values[f"actions/runs/{RECOVERY_RUN}"]
    producer = values[f"actions/runs/{recovery.PRODUCER_RUN}"]
    build = values[f"actions/runs/{recovery.PRODUCER_RUN}/jobs?per_page=100"]["jobs"][0]
    artifact = values[f"actions/artifacts/{recovery.ARTIFACTS[0][1]}"]
    codec = values[f"actions/runs/{recovery.CODEC_RUN}"]
    if case == "delivery_source": current["head_sha"] = "c" * 40
    elif case == "delivery_workflow": current["path"] = delivery.WORKFLOW
    elif case == "producer_source": producer["head_sha"] = DELIVERY_SOURCE
    elif case == "producer_attempt": producer["run_attempt"] = 2
    elif case == "failed_build": build["conclusion"] = "failure"
    elif case == "stale_build_attempt": build["run_attempt"] = 2
    elif case == "artifact_digest": artifact["digest"] = "sha256:" + "0" * 64
    elif case == "artifact_source": artifact["workflow_run"]["head_sha"] = DELIVERY_SOURCE
    elif case == "expired_artifact": artifact["expired"] = True
    elif case == "codec_source": codec["head_sha"] = DELIVERY_SOURCE
    elif case == "skipped_codec":
        values[f"actions/runs/{recovery.CODEC_RUN}/jobs?per_page=100"]["jobs"][1]["conclusion"] = "skipped"
    install_metadata(monkeypatch, values)
    with pytest.raises(ValueError):
        recovery.recovery_gate(DELIVERY_SOURCE, RECOVERY_RUN, 1)


def actions_environment(monkeypatch):
    for key, value in {"GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": delivery.REPO,
        "GITHUB_SHA": DELIVERY_SOURCE, "GITHUB_REF": delivery.BRANCH,
        "GITHUB_WORKFLOW_REF": delivery.REPO + "/" + recovery.WORKFLOW + "@" + delivery.BRANCH,
        "GITHUB_EVENT_NAME": "push", "GITHUB_RUN_ID": str(RECOVERY_RUN), "GITHUB_RUN_ATTEMPT": "1"}.items():
        monkeypatch.setenv(key, value)


def test_recovery_keeps_delivery_context_real_and_app_source_separate(tmp_path, monkeypatch):
    actions_environment(monkeypatch)
    before = dict(os.environ)
    app, tool = tmp_path / "app-source", tmp_path / "delivery-source"
    monkeypatch.setattr(recovery, "DELIVERY_ROOT", tool)
    monkeypatch.setattr(delivery, "__file__", str(tool / "tools/stage_mp4_preview.py"))
    monkeypatch.setattr(recovery, "checkout_gate", lambda path, source: path)
    producer = delivery.ProducerContext(recovery.PRODUCER_RUN, 1, recovery.ARTIFACTS,
        recovery.CODEC_RUN, DELIVERY_SOURCE, RECOVERY_RUN, recovery.WORKFLOW)
    monkeypatch.setattr(recovery, "recovery_gate", lambda *args: producer)
    monkeypatch.setattr(delivery, "ROOT", tool)
    def stage(source, work, *, producer):
        assert source == recovery.APP_SOURCE and delivery.ROOT == app
        assert producer.delivery_source_commit == DELIVERY_SOURCE
        assert dict(os.environ) == before
        return {"source_commit": source, "delivery_source_commit": producer.delivery_source_commit}
    monkeypatch.setattr(delivery, "stage_from_producer", stage)
    assert recovery.recover(app, tmp_path / "work") == {
        "source_commit": recovery.APP_SOURCE, "delivery_source_commit": DELIVERY_SOURCE}
    assert dict(os.environ) == before
    monkeypatch.setenv("GITHUB_WORKFLOW_REF", delivery.REPO + "/" + delivery.WORKFLOW + "@" + delivery.BRANCH)
    with pytest.raises(ValueError, match="exact_recovery_actions_context"):
        recovery.context()


def test_recovery_workflow_has_two_fixed_checkouts_and_no_build_or_publish():
    raw = (Path(__file__).resolve().parents[1] / recovery.WORKFLOW).read_text()
    scoped = raw.split("    paths:\n", 1)[1].split("  workflow_dispatch:", 1)[0]
    assert [line.strip()[2:] for line in scoped.splitlines() if line.strip()] == [recovery.WORKFLOW,
        "tools/recover_mp4_preview_3c0156f.py", "tests/test_mp4_preview_recovery.py"]
    assert "ref: ${{ github.sha }}" in raw and "ref: " + recovery.APP_SOURCE in raw
    assert "path: delivery-source" in raw and "path: app-source" in raw
    assert "recover_mp4_preview_3c0156f.py" in raw and "contents: write" in raw
    for forbidden in ("ci_build.py", "package_android_unified.py", "gh release", "continue-on-error", "GITHUB_SHA:"):
        assert forbidden not in raw
