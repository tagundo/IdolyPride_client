"""Host-only publication policy checks. No GitHub, LFS, gh, or binary build calls."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
from urllib.error import HTTPError

import pytest


@pytest.fixture
def uploader():
    path = Path(__file__).resolve().parents[1] / "tools/publish_prebuilt_release.py"
    spec = importlib.util.spec_from_file_location("prebuilt_publication_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_inputs(u, root):
    identity = {"schema": 1, "repository": u.REPOSITORY, "tag": u.TAG,
                "release_id": u.RELEASE_ID, "target_commit": u.TARGET}
    rows = [{"name": name, "bytes": len(name), "sha256": hashlib.sha256(name.encode()).hexdigest(),
             "source_commit": source} for name, source in u.SOURCES.items()]
    review = {**identity, "status": "PASS", "artifacts": [
        {**row, "qa_status": "PASS", "qa_receipt_sha256": "a" * 64} for row in rows]}
    path = root / u.REVIEW
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(review))
    manifest = {**identity, "review": {"path": u.REVIEW, "sha256": u.digest(path.read_bytes())},
                "artifacts": rows}
    (root / u.MANIFEST).write_text(json.dumps(manifest))
    return manifest, review


def test_deterministic_proof_and_non_circular_checksums(uploader, tmp_path):
    u = uploader
    write_inputs(u, tmp_path)
    expected, data = u.load_delivery(tmp_path)
    assert (expected, data) == u.load_delivery(tmp_path)
    assert len(expected) == 7
    proof = json.loads(data["RELEASE-VERIFICATION.json"])
    assert len(proof["artifacts"]) == 5
    assert proof["artifacts"] == sorted(proof["artifacts"], key=lambda row: row["name"])
    lines = data["SHA256SUMS"].decode().splitlines()
    assert len(lines) == 6
    assert not any(line.endswith("  SHA256SUMS") for line in lines)
    assert u.digest(data["RELEASE-VERIFICATION.json"]) + "  RELEASE-VERIFICATION.json" in lines
    assert str(tmp_path) not in data["RELEASE-VERIFICATION.json"].decode()


@pytest.mark.parametrize("field,value", [
    ("repository", "other/repo"), ("tag", "local-server-v0.3.18"),
    ("release_id", 1), ("target_commit", "a" * 40), ("schema", True),
])
def test_manifest_identity_fails_before_network(uploader, tmp_path, field, value):
    u = uploader
    manifest, _ = write_inputs(u, tmp_path)
    manifest[field] = value
    (tmp_path / u.MANIFEST).write_text(json.dumps(manifest))
    with pytest.raises(u.Refused, match="delivery_identity_differs"):
        u.load_delivery(tmp_path)


@pytest.mark.parametrize("mutation", ["name", "source", "bool_size", "duplicate", "review_path", "review_hash"])
def test_unreviewed_or_arbitrary_artifacts_refused(uploader, tmp_path, mutation):
    u = uploader
    manifest, _ = write_inputs(u, tmp_path)
    if mutation == "name":
        manifest["artifacts"][0]["name"] = "../escape.apk"
    elif mutation == "source":
        manifest["artifacts"][0]["source_commit"] = u.TARGET
    elif mutation == "bool_size":
        manifest["artifacts"][0]["bytes"] = True
    elif mutation == "duplicate":
        manifest["artifacts"][-1] = manifest["artifacts"][0]
    elif mutation == "review_path":
        manifest["review"]["path"] = "../../outside.json"
    else:
        manifest["review"]["sha256"] = "b" * 64
    (tmp_path / u.MANIFEST).write_text(json.dumps(manifest))
    with pytest.raises(u.Refused):
        u.load_delivery(tmp_path)


def test_review_crossmatch_and_qa_receipt_required(uploader, tmp_path):
    u = uploader
    manifest, review = write_inputs(u, tmp_path)
    review["artifacts"][0]["bytes"] += 1
    (tmp_path / u.REVIEW).write_text(json.dumps(review))
    manifest["review"]["sha256"] = u.digest((tmp_path / u.REVIEW).read_bytes())
    (tmp_path / u.MANIFEST).write_text(json.dumps(manifest))
    with pytest.raises(u.Refused, match="review_artifact_differs"):
        u.load_delivery(tmp_path)
    review["artifacts"][0]["qa_receipt_sha256"] = "not-a-sha"
    (tmp_path / u.REVIEW).write_text(json.dumps(review))
    manifest["review"]["sha256"] = u.digest((tmp_path / u.REVIEW).read_bytes())
    (tmp_path / u.MANIFEST).write_text(json.dumps(manifest))
    with pytest.raises(u.Refused, match="independent_review_missing"):
        u.load_delivery(tmp_path)


def test_duplicate_json_and_symlink_inputs_refused(uploader, tmp_path):
    u = uploader
    with pytest.raises(u.Refused, match="duplicate_json_key"):
        u.decode_json(b'{"schema":1,"schema":1}')
    with pytest.raises(u.Refused, match="invalid_json"):
        u.decode_json(b'{"schema":NaN}')
    target = tmp_path / "file"
    target.write_bytes(b"{}")
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(u.Refused, match="invalid_public_input"):
        u.read_public(link)


class Response(io.BytesIO):
    status = 200

    def __init__(self, data, headers=None):
        super().__init__(data)
        self.headers = headers or {}
        self.read_sizes = []

    def read(self, size=-1):
        self.read_sizes.append(size)
        return super().read(size)


def test_stream_full_hash_exact_size_and_64k_reads(uploader):
    u = uploader
    data = b"streaming" * 20000
    expected = {"bytes": len(data), "sha256": u.digest(data)}
    response, destination = Response(data), io.BytesIO()
    u.stream_verified(response, expected, destination)
    assert destination.getvalue() == data
    assert set(response.read_sizes) == {65536}


@pytest.mark.parametrize("variant", ["truncated", "overlong", "hash", "encoded", "length"])
def test_stream_rejects_invalid_bytes(uploader, variant):
    u = uploader
    expected = {"bytes": 3, "sha256": u.digest(b"abc")}
    data, headers = b"abc", {}
    if variant == "truncated":
        data = b"ab"
    elif variant == "overlong":
        data = b"abcd"
    elif variant == "hash":
        data = b"xyz"
    elif variant == "encoded":
        headers = {"Content-Encoding": "gzip"}
    else:
        headers = {"Content-Length": "4"}
    with pytest.raises(u.Refused):
        u.stream_verified(Response(data, headers), expected)


@pytest.mark.parametrize("url", [
    "http://github.com/object", "https://github.com.evil.example/object",
    "https://evil.example/object", "https://github.com:444/object",
    "https://user:secret@github.com/object", "https://github.com/object#fragment",
    "https://github.com/object\nheader", "https://unrelated.s3.amazonaws.com/object",
])
def test_signed_url_host_boundary(uploader, url):
    with pytest.raises(uploader.Refused, match="download_url_refused"):
        uploader.approved_url(url, uploader.LFS_HOSTS)


def test_retained_github_lfs_download_host_is_explicitly_allowed(uploader):
    url = "https://github-cloud.githubusercontent.com/alambic/media/object?signature=synthetic"
    assert uploader.approved_url(url, uploader.LFS_HOSTS) == url


def test_release_download_never_forwards_auth_to_signed_url(uploader, tmp_path):
    u = uploader
    github = u.GitHub("synthetic-token", tmp_path)
    calls = []

    class Opener:
        def open(self, request, timeout):
            calls.append(request)
            if len(calls) == 1:
                raise HTTPError(request.full_url, 302, "redirect", {
                    "Location": "https://release-assets.githubusercontent.com/asset?signature=private"}, None)
            return Response(b"abc")
    github.opener = Opener()
    github.verify_uploaded({"id": 42}, {"bytes": 3, "sha256": u.digest(b"abc")})
    assert calls[0].get_header("Authorization") == "Bearer synthetic-token"
    assert calls[1].get_header("Authorization") is None
    assert calls[0].full_url == u.API + "/releases/assets/42"


def test_lfs_batch_is_fixed_and_object_pinned(uploader, tmp_path):
    u = uploader
    github = u.GitHub("synthetic-token", tmp_path)
    row = {"bytes": 3, "sha256": u.digest(b"abc")}
    calls = []

    class Opener:
        def open(self, request, timeout):
            calls.append(request)
            if len(calls) == 1:
                assert request.full_url == u.BATCH
                assert json.loads(request.data)["objects"] == [{"oid": row["sha256"], "size": 3}]
                return Response(json.dumps({"objects": [{"oid": row["sha256"], "size": 3,
                    "actions": {"download": {"href": "https://github-cloud.s3.amazonaws.com/object?signature=hidden"}}}]}).encode())
            assert request.get_header("Authorization") is None
            return Response(b"abc")
    github.opener = Opener()
    output = tmp_path / "artifact.apk"
    github.lfs_download(row, output)
    assert output.read_bytes() == b"abc"


def test_fresh_release_identity_and_tag_guards(uploader, tmp_path):
    u = uploader
    github = u.GitHub("synthetic-token", tmp_path)
    release = {"id": u.RELEASE_ID, "tag_name": u.TAG, "target_commitish": u.TARGET, "draft": True}
    obj = {"type": "commit", "sha": u.TARGET}

    def api(path, **kwargs):
        if path.endswith("?per_page=100"):
            return []
        if path.startswith("/git/ref"):
            return {"object": obj}
        return release
    github.api = api
    assert github.release() == []
    obj["sha"] = "a" * 40
    with pytest.raises(u.Refused, match="tag_identity_differs"):
        github.release()
    obj["sha"] = u.TARGET
    release["draft"] = False
    with pytest.raises(u.Refused, match="release_identity_or_draft_differs"):
        github.release()


class FakeGitHub:
    def __init__(self, u, expected, metadata):
        self.u, self.expected = u, expected
        self.data = {name: name.encode() for name in u.SOURCES}
        self.data.update(metadata)
        self.assets = {}
        self.uploads, self.downloads, self.verifies = [], [], []
        self.published = False
        self.corrupt_at_verify = None

    def release(self, *, published=False):
        assert self.published == published
        return [dict(row) for row in self.assets.values()]

    def add(self, name):
        row = self.expected[name]
        self.assets[name] = {"name": name, "id": len(self.assets) + 1, "size": row["bytes"],
                             "digest": "sha256:" + row["sha256"], "state": "uploaded"}

    def lfs_download(self, row, path):
        self.downloads.append(row["name"])
        path.write_bytes(self.data[row["name"]])

    def upload(self, path):
        assert path.name not in self.assets
        assert path.read_bytes() == self.data[path.name]
        self.uploads.append(path.name)
        self.add(path.name)

    def verify_uploaded(self, asset, row):
        self.verifies.append(asset["name"])
        if len(self.verifies) == self.corrupt_at_verify:
            raise self.u.Refused("download_hash_or_size_differs")
        assert self.u.digest(self.data[asset["name"]]) == row["sha256"]

    def publish(self):
        assert len(self.assets) == 7 and len(self.verifies) == 14
        self.published = True


def prepared(u, tmp_path):
    write_inputs(u, tmp_path)
    expected, metadata = u.load_delivery(tmp_path)
    return expected, metadata, FakeGitHub(u, expected, metadata)


def test_stage_only_and_verified_resume_without_clobber(uploader, tmp_path):
    u = uploader
    expected, metadata, github = prepared(u, tmp_path)
    first = next(iter(u.SOURCES))
    github.add(first)
    result = u.stage(github, expected, metadata, tmp_path)
    assert result["published"] is False and not github.published
    assert first not in github.uploads and first not in github.downloads
    assert len(github.uploads) == 6 and len(github.verifies) == 7
    github.uploads.clear()
    u.stage(github, expected, metadata, tmp_path)
    assert github.uploads == [] and len(github.verifies) == 14


def test_publish_only_after_seven_full_downloads_and_fresh_second_pass(uploader, tmp_path):
    u = uploader
    expected, metadata, github = prepared(u, tmp_path)
    result = u.stage(github, expected, metadata, tmp_path, publish=True)
    assert result["published"] is True and github.published
    assert len(github.verifies) == 14 and len(github.uploads) == 7


@pytest.mark.parametrize("failure", ["unexpected", "wrong_size", "wrong_digest", "duplicate", "final_hash"])
def test_any_conflict_or_verification_failure_keeps_draft(uploader, tmp_path, failure):
    u = uploader
    expected, metadata, github = prepared(u, tmp_path)
    first = next(iter(u.SOURCES))
    github.add(first)
    if failure == "unexpected":
        github.assets[first]["name"] = "unexpected.apk"
    elif failure == "wrong_size":
        github.assets[first]["size"] += 1
    elif failure == "wrong_digest":
        github.assets[first]["digest"] = "sha256:" + "b" * 64
    elif failure == "duplicate":
        github.release = lambda **_: [dict(github.assets[first]), dict(github.assets[first])]
    else:
        github.corrupt_at_verify = 8
    with pytest.raises(u.Refused):
        u.stage(github, expected, metadata, tmp_path, publish=True)
    assert not github.published
    if failure != "final_hash":
        assert not github.uploads


def test_concurrent_replacement_and_symlink_upload_refused(uploader, tmp_path):
    u = uploader
    expected, metadata, github = prepared(u, tmp_path)
    name = next(iter(u.SOURCES))
    github.add(name)
    original = u.inventory(github.release(), expected)
    github.assets[name]["id"] += 10
    with pytest.raises(u.Refused, match="concurrent_asset_replacement"):
        u.inventory(github.release(), expected, original)
    target = tmp_path / "real"
    target.write_bytes(b"abc")
    link = tmp_path / "symlink"
    link.symlink_to(target)
    with pytest.raises(u.Refused, match="upload_file_not_regular"):
        u.verify_file(link, {"bytes": 3, "sha256": u.digest(b"abc")})


def test_gh_upload_uses_only_fixed_identity_and_no_clobber_or_debug(uploader, tmp_path, monkeypatch):
    u = uploader
    github = u.GitHub("runner-secret", tmp_path)
    captured = {}
    monkeypatch.setenv("GH_DEBUG", "api")
    monkeypatch.setenv("GIT_TRACE_CURL", "1")

    def run(args, **kwargs):
        captured.update(args=args, **kwargs)
        return type("Result", (), {"returncode": 0})()
    monkeypatch.setattr(u.subprocess, "run", run)
    path = tmp_path / next(iter(u.SOURCES))
    github.upload(path)
    assert captured["args"] == ["gh", "release", "upload", u.TAG, str(path), "--repo", u.REPOSITORY]
    assert "--clobber" not in captured["args"] and "runner-secret" not in captured["args"]
    assert captured["env"]["GH_TOKEN"] == "runner-secret"
    assert "GH_DEBUG" not in captured["env"] and "GIT_TRACE_CURL" not in captured["env"]
    assert captured["stdout"] == u.subprocess.DEVNULL and captured["stderr"] == u.subprocess.DEVNULL


def test_cli_defaults_to_stage_and_redacts_arbitrary_errors(uploader, tmp_path, monkeypatch, capsys):
    u = uploader
    monkeypatch.setattr(u, "load_delivery", lambda: ({}, {}))
    for key, val in {"GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": u.REPOSITORY,
                     "GITHUB_EVENT_NAME": "workflow_dispatch", "GH_TOKEN": "secret",
                     "RUNNER_TEMP": str(tmp_path)}.items():
        monkeypatch.setenv(key, val)
    monkeypatch.setattr(u, "GitHub", lambda *args: None)
    seen = []
    monkeypatch.setattr(u, "stage", lambda *args, **kwargs: seen.append(kwargs["publish"]) or {"published": False})
    u.main([])
    assert seen == [False]
    (tmp_path / "idoly-prebuilt-publication-report.json").unlink()

    def fail(*args, **kwargs):
        raise OSError("https://secret.invalid/?signed=credential")
    monkeypatch.setattr(u, "stage", fail)
    with pytest.raises(SystemExit) as error:
        u.main(["--publish"])
    assert str(error.value) == "Publication stopped: publication_io_failure"
    report = (tmp_path / "idoly-prebuilt-publication-report.json").read_text()
    assert "credential" not in report and "secret.invalid" not in report


def test_workflow_dispatch_only_and_write_permission_scoped():
    path = Path(__file__).resolve().parents[1] / ".github/workflows/publish-prebuilt-v0319.yml"
    text = path.read_text()
    assert "workflow_dispatch:" in text and "pull_request:" not in text and "push:" not in text
    assert "default: false" in text and "persist-credentials: false" in text
    assert "cancel-in-progress: false" in text and "contents: write" in text
    assert 'if [[ "$IDOLY_PUBLISH" == "true" ]]' in text
    assert "--clobber" not in text and "inputs.publish }}" in text
