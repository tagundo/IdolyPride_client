"""A prior draft or git tag must prevent every release/upload mutation."""
import importlib.util
import io
import json
from pathlib import Path
from urllib.error import HTTPError

import pytest


@pytest.fixture
def stager():
    path = Path(__file__).resolve().parents[1] / "tools/stage_event_preserver.py"
    spec = importlib.util.spec_from_file_location("event_stager_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fake_api(module, *, releases, tag_exists, calls):
    class Opener:
        def open(self, request, timeout):
            calls.append((request.method, request.full_url))
            assert request.method == "GET", "release mutation occurred before all guards"
            url = request.full_url
            if "/actions/runs/" in url:
                value = {"head_sha": module.SOURCE, "status": "completed", "conclusion": "success",
                         "event": "workflow_dispatch", "path": ".github/workflows/build-event-preserver.yml"}
            elif "/actions/artifacts/" in url:
                value = {"workflow_run": {"id": module.RUN, "head_sha": module.SOURCE}, "expired": False,
                         "name": "IdolyPride-Event-Preserver-Mac-arm64-candidate",
                         "digest": "sha256:df74c796a9e0d0a695fa35edf5679b459294d8f3d0a3f3ddae7dabf2c5bd01e5"}
            elif "/releases?" in url:
                page = int(url.rsplit("=", 1)[-1])
                value = releases.get(page, [])
            elif "/git/ref/tags/" in url:
                if not tag_exists:
                    raise HTTPError(url, 404, "missing", {}, None)
                value = {"object": {"sha": "different-commit"}}
            else:
                pytest.fail("Unexpected endpoint")
            return io.BytesIO(json.dumps(value).encode())
    return Opener()


@pytest.mark.parametrize("case", ["draft", "published", "second-page-draft", "existing-tag"])
def test_prior_release_or_tag_prevents_every_mutation(stager, monkeypatch, tmp_path, case):
    monkeypatch.setattr(stager, "verify_candidate", lambda _: {})
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_REPOSITORY", stager.REPO)
    monkeypatch.setenv("GH_TOKEN", "synthetic-token")
    releases = {}
    if case in ("draft", "published"):
        releases[1] = [{"tag_name": stager.TAG, "draft": case == "draft"}]
    elif case == "second-page-draft":
        releases = {1: [{"tag_name": "unrelated"}] * 100, 2: [{"tag_name": stager.TAG, "draft": True}]}
    calls = []
    monkeypatch.setattr(stager, "build_opener", lambda _: fake_api(stager, releases=releases,
                        tag_exists=case == "existing-tag", calls=calls))
    with pytest.raises(ValueError, match="release_(already_exists|tag_differs)"):
        stager.stage(tmp_path, tmp_path / "receipt.json")
    assert calls and all(method == "GET" for method, _ in calls)
    assert not (tmp_path / "receipt.json").exists()
