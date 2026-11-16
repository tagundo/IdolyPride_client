"""Publication trust-boundary checks; no build, network or release operations."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import stat
from zipfile import ZipInfo, ZIP_STORED, ZIP_LZMA

import pytest

SPEC = importlib.util.spec_from_file_location("optimized_release_publisher",
    Path(__file__).resolve().parents[1] / "tools/publish_optimized_release.py")
publisher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publisher)
SOURCE, RUN, HASH = "a" * 40, 123, "b" * 64
BENCH_SPEC = importlib.util.spec_from_file_location("diagnostics_benchmark_contract",
    Path(__file__).resolve().parents[1] / "tools/benchmark_diagnostics_polling.py")
benchmark_contract = importlib.util.module_from_spec(BENCH_SPEC)
BENCH_SPEC.loader.exec_module(benchmark_contract)
RELEASE_VERSION = "2026.11.16.1"


@pytest.fixture(autouse=True)
def calendar_release_identity(monkeypatch):
    monkeypatch.setattr(publisher, "RELEASE_VERSION", None)
    monkeypatch.setattr(publisher, "TAG", None)
    monkeypatch.setattr(publisher, "RELEASE_NAMES", {})
    monkeypatch.setattr(publisher, "EXPECTED_RELEASE_ASSETS", frozenset())
    publisher.configure_release(RELEASE_VERSION)


def metadata():
    build = {"id": RUN, "head_sha": SOURCE, "event": "workflow_dispatch",
             "repository": {"full_name": publisher.REPO},
             "path": ".github/workflows/release-all-platforms.yml"}
    jobs = {"total_count": len(publisher.JOBS) + 1, "jobs": [{"name": name, "conclusion": "success"} for name in publisher.JOBS]
             + [{"name": "publish", "conclusion": None}]}
    rows = [{"id": index + 1, "name": prefix + SOURCE, "expired": False,
             "workflow_run": {"id": RUN, "head_sha": SOURCE},
             "size_in_bytes": 100, "digest": "sha256:" + HASH}
            for index, prefix in enumerate(publisher.PREFIXES.values())]
    return build, jobs, {"total_count": len(rows), "artifacts": rows}


def test_same_run_all_platform_artifacts_require_all_successful_jobs():
    build, jobs, artifacts = metadata()
    result = publisher.validate_run(build, jobs, artifacts, SOURCE, RUN)
    assert set(result) == set(publisher.JOBS)
    assert all(row["source_commit"] == SOURCE and row["run_id"] == RUN
               and row["archive_sha256"] == HASH for row in result.values())


@pytest.mark.parametrize("case", ["wrong_source", "fork", "pull_request", "wrong_workflow", "unfinished_job",
    "missing_job", "duplicate_job", "truncated_jobs", "missing_artifact", "duplicate_artifact",
    "wrong_artifact_run", "wrong_artifact_source", "expired", "digest_missing", "bad_digest",
    "boolean_size", "oversize", "truncated_artifacts"])
def test_untrusted_or_partial_workflow_evidence_is_rejected(case):
    build, jobs, artifacts = metadata()
    if case == "wrong_source": build["head_sha"] = "c"*40
    elif case == "fork": build["repository"]["full_name"] = "another/repository"
    elif case == "pull_request": build["event"] = "pull_request"
    elif case == "wrong_workflow": build["path"] = ".github/workflows/unrelated.yml"
    elif case == "unfinished_job": jobs["jobs"][0]["conclusion"] = None
    elif case == "missing_job":
        jobs["jobs"].pop(0); jobs["total_count"] -= 1
    elif case == "duplicate_job":
        jobs["jobs"].append(deepcopy(jobs["jobs"][0])); jobs["total_count"] += 1
    elif case == "truncated_jobs": jobs["total_count"] += 1
    elif case == "missing_artifact":
        artifacts["artifacts"].pop(0); artifacts["total_count"] -= 1
    elif case == "duplicate_artifact":
        artifacts["artifacts"].append(deepcopy(artifacts["artifacts"][0])); artifacts["total_count"] += 1
    elif case == "wrong_artifact_run": artifacts["artifacts"][0]["workflow_run"]["id"] += 1
    elif case == "wrong_artifact_source": artifacts["artifacts"][0]["workflow_run"]["head_sha"] = "c"*40
    elif case == "expired": artifacts["artifacts"][0]["expired"] = True
    elif case == "digest_missing": artifacts["artifacts"][0]["digest"] = None
    elif case == "bad_digest": artifacts["artifacts"][0]["digest"] = "sha256:not-a-digest"
    elif case == "boolean_size": artifacts["artifacts"][0]["size_in_bytes"] = True
    elif case == "oversize": artifacts["artifacts"][0]["size_in_bytes"] = 2*1024**3
    elif case == "truncated_artifacts": artifacts["total_count"] += 1
    with pytest.raises(publisher.ReleaseError):
        publisher.validate_run(build, jobs, artifacts, SOURCE, RUN)


def test_only_owned_push_branch_is_allowed():
    build, jobs, artifacts = metadata()
    build.update(event="push", head_branch="feat/ios-unified-server")
    publisher.validate_run(build, jobs, artifacts, SOURCE, RUN)
    build["head_branch"] = "another-branch"
    with pytest.raises(publisher.ReleaseError):
        publisher.validate_run(build, jobs, artifacts, SOURCE, RUN)


class Inventory:
    def __init__(self, rows):
        self.rows = rows
    def infolist(self):
        return self.rows


def entry(name, size=1):
    row = ZipInfo(name)
    row.file_size, row.compress_type = size, ZIP_STORED
    row.external_attr = stat.S_IFREG << 16
    return row


def android_entries():
    return [entry(name) for name in ("platform-report.json", publisher.APK, publisher.QA_APK, "android-qa.json")]


def test_only_bounded_expected_platform_files_are_extracted():
    rows = android_entries()
    assert set(publisher.generic_members(Inventory(rows), "android")) == {row.filename for row in rows}


@pytest.mark.parametrize("name", ["../escape.json", "/absolute.json", "a/./b.json", "a\\b.json",
                                   "bad\0.json", "another.apk"])
def test_unsafe_or_unexpected_artifact_paths_are_rejected(name):
    with pytest.raises(publisher.ReleaseError):
        publisher.generic_members(Inventory(android_entries() + [entry(name)]), "android")


@pytest.mark.parametrize("kind", ["duplicate", "case_alias", "symlink", "encrypted", "compression", "oversize"])
def test_archive_aliases_unsafe_members_and_unbounded_entries_are_rejected(kind):
    rows = android_entries()
    value = entry("extra.json")
    if kind == "duplicate": rows.append(deepcopy(rows[0]))
    elif kind == "case_alias": rows.append(entry("PLATFORM-REPORT.JSON"))
    elif kind == "symlink": value.external_attr = stat.S_IFLNK << 16
    elif kind == "encrypted": value.flag_bits = 1
    elif kind == "compression": value.compress_type = ZIP_LZMA
    elif kind == "oversize": value.file_size = publisher.MAX_JSON + 1
    rows.append(value)
    with pytest.raises(publisher.ReleaseError):
        publisher.generic_members(Inventory(rows), "android")


def platform_report(platform):
    flags = publisher.COMMON_FLAGS + (publisher.ANDROID_FLAGS if platform == "android" else publisher.MAC_FLAGS)
    validation = {name: True for name in flags}
    if platform == "android":
        pass
    translations = publisher.TRANSLATION_PINS["android" if platform == "android" else "ios"]
    result = {"schema": 1, "status": "PASS", "platform": platform, "source_commit": SOURCE,
              "version": publisher.VERSION, "build_number": publisher.BUILD,
              "binary": {"name": publisher.APK if platform == "android" else publisher.MAC, "bytes": 1, "sha256": HASH},
              "source_sha256": {name: HASH for name in publisher.COMMON_SOURCES},
              "inputs": {"server_data": deepcopy(publisher.DATA_PIN),
                         "server_data_provenance": deepcopy(publisher.LOVE_SERVER_DATA.load_pin()["upgrade_proof"]),
                         "translations": {**translations, "platform": "android" if platform == "android" else "ios", "included": True}},
              "validation": validation,
              "execution": {"actual_macos_execution": platform == "macos",
                            "actual_android_arm64_execution": False, "physical_PlayCover_execution": False}}
    if platform == "android":
        result.update(application_id="game.qualiarts.idolypride.localserver", certificate_sha256=publisher.CERTIFICATE)
        result["qa_binary"] = {"name": publisher.QA_APK, "bytes": 1, "sha256": HASH}
        for key, abi in (("binary", "arm64-v8a"), ("qa_binary", "x86_64")):
            result[key].update(abi=abi, application_id="game.qualiarts.idolypride.localserver", version=publisher.VERSION,
                               build_number=publisher.BUILD, certificate_sha256=publisher.CERTIFICATE,
                               signature_verified=True, alignment_verified=True)
    return result


@pytest.mark.parametrize("platform", ["android", "macos"])
def test_exact_platform_identity_and_source_pin_evidence(monkeypatch, platform):
    monkeypatch.setattr(publisher, "blob_sha", lambda source, name: HASH)
    publisher.validate_platform(platform_report(platform), platform, SOURCE)


@pytest.mark.parametrize("case", ["version", "boolean_build", "schema_bool", "source_missing", "source_hash",
                                   "payload", "translations", "signature_number", "certificate", "physical_claim"])
def test_platform_mismatch_never_reaches_publication(monkeypatch, case):
    monkeypatch.setattr(publisher, "blob_sha", lambda source, name: HASH)
    value = platform_report("android")
    if case == "version": value["version"] = "0.3.31"
    elif case == "boolean_build": value["build_number"] = True
    elif case == "schema_bool": value["schema"] = True
    elif case == "source_missing": value["source_sha256"].pop(publisher.COMMON_SOURCES[0])
    elif case == "source_hash": value["source_sha256"][publisher.COMMON_SOURCES[0]] = "c"*64
    elif case == "payload": value["inputs"]["server_data"]["sha256"] = "c"*64
    elif case == "translations": value["inputs"]["translations"]["included"] = False
    elif case == "signature_number": value["validation"]["apk_signature_verified"] = 1
    elif case == "certificate": value["certificate_sha256"] = "c"*64
    elif case == "physical_claim": value["execution"]["actual_android_arm64_execution"] = True
    with pytest.raises(publisher.ReleaseError):
        publisher.validate_platform(value, "android", SOURCE)


@pytest.mark.parametrize("raw", [b'{"a":1,"a":2}', b'{"x":NaN}', b'{"x":Infinity}'])
def test_duplicate_or_nonfinite_json_is_rejected(raw):
    with pytest.raises(publisher.ReleaseError):
        publisher.decode(raw)


def test_metadata_copy_refuses_symlink_and_never_materializes_binaries(tmp_path):
    source, output = tmp_path/"source", tmp_path/"output"
    source.mkdir(); output.mkdir()
    (source/"valid.json").write_text('{"status":"PASS"}')
    (source/"binary.apk").write_bytes(b"not copied")
    result = publisher.copy_metadata({"android": source}, output)
    assert set(result) == {"android/valid.json"}
    assert not list(output.rglob("*.apk"))
    linked = source/"linked.json"
    linked.symlink_to(source/"valid.json")
    with pytest.raises(publisher.ReleaseError):
        publisher.copy_metadata({"another": source}, tmp_path/"other-output")


class TinyGuard:
    def __init__(self):
        self.samples = 0

    def check(self):
        self.samples += 1


@pytest.fixture
def source_release_binaries(tmp_path):
    import hashlib
    rows = []
    for index, name in enumerate((publisher.APK, publisher.IPA,
                                  *publisher.ANDROID_LANGUAGE_CLIENTS.values(),
                                  *(row["name"] for row in publisher.COMPANIONS))):
        path = tmp_path/name
        path.write_bytes(b"PK\x03\x04" + bytes([index])*8)
        rows.append({"name": name, "path": str(path), "bytes": path.stat().st_size,
                     "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    return rows


@pytest.fixture
def release_binaries(source_release_binaries, tmp_path):
    return publisher.stage_release_binaries(source_release_binaries, tmp_path/"release", TinyGuard())


def asset_metadata(wanted, index):
    return {"id": index + 100, "name": wanted["name"], "size": wanted["bytes"],
            "state": "uploaded", "digest": "sha256:" + wanted["sha256"],
            "browser_download_url": publisher.asset_download_url(wanted["name"])}


class FakeGitHub(publisher.GitHub):
    def __init__(self, *, existing=False, bad_tag=False, readback_failure=None, bad_inventory=False,
                 temporary_urls=False, final_temporary_urls=False):
        super().__init__("test-token", None)
        self.calls, self.existing, self.bad_tag = [], existing, bad_tag
        self.readback_failure, self.bad_inventory = readback_failure, bad_inventory
        self.uploaded, self.events = [], []
        self.temporary_urls, self.final_temporary_urls = temporary_urls, final_temporary_urls

    def api(self, path, *, method="GET", body=None, absent=False):
        self.calls.append((path, method, body))
        if method == "GET" and path.startswith("/releases/tags/"):
            return {"id": 1} if self.existing else None
        if method == "GET" and path == "/releases?per_page=100": return []
        if method == "GET" and path.startswith("/git/ref/"):
            if self.owned_release_id is None: return None
            return {"object": {"type": "commit", "sha": ("c"*40 if self.bad_tag else SOURCE)}}
        if method == "GET" and path == "/releases/77/assets?per_page=100":
            return self.uploaded[:-1] if self.bad_inventory else self.uploaded
        if method == "POST":
            return {"id": 77, "tag_name": publisher.TAG, "draft": True,
                    "prerelease": True, "target_commitish": SOURCE}
        if method == "PATCH" and body["draft"] is True:
            return {"id": 77, "draft": True}
        if method == "PATCH":
            assert body == {"draft": False, "tag_name": publisher.TAG, "target_commitish": SOURCE}
            self.events.append("promote")
            if not self.final_temporary_urls:
                for asset in self.uploaded:
                    asset["browser_download_url"] = publisher.asset_download_url(asset["name"])
            return {"id": 77, "tag_name": publisher.TAG, "draft": False, "prerelease": True,
                    "target_commitish": SOURCE, "published_at": "2026-11-15T00:00:00Z",
                    "html_url": "https://github.com/"+publisher.REPO+"/releases/tag/"+publisher.TAG}
        raise AssertionError("Unexpected API call")

    def upload_asset(self, release_id, wanted):
        assert release_id == 77
        row = asset_metadata(wanted, len(self.uploaded))
        if self.temporary_urls:
            row["browser_download_url"] = ("https://github.com/"+publisher.REPO
                +"/releases/download/untagged-19a339c5b788cf8128b3/"+wanted["name"])
        self.uploaded.append(row)
        self.events.append("upload")
        return row

    def verify_asset(self, asset, wanted, guard):
        import io
        self.events.append("readback")
        raw = Path(wanted["path"]).read_bytes()
        if len(self.uploaded) == self.readback_failure:
            raw = raw[:-1] + b"!"
        response = io.BytesIO(raw)
        response.status, response.headers = 200, {"Content-Length": str(len(raw))}
        publisher.verify_binary_stream(response, wanted, guard)


def test_existing_release_is_never_changed(release_binaries):
    github = FakeGitHub(existing=True)
    with pytest.raises(publisher.ReleaseError):
        github.publish(SOURCE, "release", release_binaries, TinyGuard())
    assert all(method == "GET" for _path, method, _body in github.calls)


def test_new_release_promotes_only_after_all_full_API_readbacks(release_binaries):
    github, saved = FakeGitHub(), []
    def before_promote():
        assert github.events == ["upload", "readback"]*len(release_binaries)
        github.events.append("latest_gates")
    result = github.publish(SOURCE, "release", release_binaries, TinyGuard(),
                            before_promote=before_promote,
                            save_assets=lambda rows:saved.append(deepcopy(rows)))
    assert result["draft"] is False and result["prerelease"] is True
    assert github.owned_release_id == 77
    assert github.events == ["upload", "readback"]*len(release_binaries) + ["latest_gates", "promote"]
    assert len(saved) == len(release_binaries) + 1
    assert len(github.asset_receipts) == len(release_binaries)
    assert all(row["full_API_download_SHA256_verified"] is True for row in github.asset_receipts)
    assert [body for _path, method, body in github.calls if method == "POST"] == [{
        "tag_name": publisher.TAG, "target_commitish": SOURCE,
        "name": publisher.release_title(), "body": "release",
        "draft": True, "prerelease": True, "make_latest": "false"}]


@pytest.mark.parametrize("failure", ["readback", "inventory", "latest_gates", "proof_write"])
def test_incomplete_asset_readbacks_or_gates_never_publish(failure, release_binaries):
    github = FakeGitHub(readback_failure=3 if failure == "readback" else None,
                        bad_inventory=failure == "inventory")
    def fail():
        raise publisher.ReleaseError("simulated_gate_failure")
    with pytest.raises(publisher.ReleaseError):
        github.publish(SOURCE, "release", release_binaries, TinyGuard(),
                       before_promote=fail if failure == "latest_gates" else None,
                       save_assets=(lambda rows:fail()) if failure == "proof_write" else None)
    assert "promote" not in github.events
    assert github.rollback_draft_restored is True
    assert not any(method == "PATCH" and body.get("draft") is False for _path, method, body in github.calls)


def test_failed_promotion_verification_restores_only_just_created_draft(release_binaries):
    github = FakeGitHub(bad_tag=True)
    with pytest.raises(publisher.ReleaseError):
        github.publish(SOURCE, "release", release_binaries, TinyGuard())
    assert github.rollback_draft_restored is True
    assert github.calls[-1] == ("/releases/77", "PATCH", {"draft": True})


@pytest.mark.parametrize("case", ["missing_client", "changed_bytes", "symlink"])
def test_unverified_binary_input_stops_before_draft_creation(case, release_binaries, tmp_path):
    github = FakeGitHub()
    if case == "missing_client": release_binaries.pop()
    elif case == "changed_bytes": Path(release_binaries[0]["path"]).write_bytes(b"modified")
    else:
        path = Path(release_binaries[0]["path"])
        path.rename(tmp_path/"actual-file")
        path.symlink_to(tmp_path/"actual-file")
    with pytest.raises(publisher.ReleaseError):
        github.publish(SOURCE, "release", release_binaries, TinyGuard())
    assert github.calls == []


def scope_proof():
    return {"original_master": {"version": "6b77" + "0"*60, "pack_count": 202},
            "love": {"events": 6, "episodes": 72},
            "semantic_controls": {"features": {
                "main_live": {"receipt": {"checks": {
                    "old_cards_unchanged": 503, "new_cards": 1,
                    "old_costumes_preserved": 994, "new_costumes": 17,
                    "old_hairs_preserved": 1186, "new_hairs": 45}}},
                "octo": {"receipt": {"required_card_images": 1, "platforms": {
                    key: {"revision": revision, "model_roots": 125, "missing_model_roots": 0,
                          "incomplete_dependency_closures": 0}
                    for key, revision in (("android", 1097), ("ios", 1169))}}}}}}


@pytest.mark.parametrize("change", ["missing", "boolean", "negative"])
def test_release_notes_never_invent_master_counts(change, monkeypatch):
    proof = scope_proof()
    checks = proof["semantic_controls"]["features"]["main_live"]["receipt"]["checks"]
    if change == "missing": checks.pop("new_cards")
    elif change == "boolean": checks["new_cards"] = True
    else: checks["new_cards"] = -1
    monkeypatch.setattr(publisher.LATEST_SERVER_DATA, "load_pin", lambda: {"upgrade_proof": proof})
    notes = "\n".join(publisher.release_scope_lines())
    assert proof["original_master"]["version"] in notes
    assert "카드 504" not in notes and "의상 1011" not in notes and "헤어 1231" not in notes


@pytest.mark.parametrize("field,value", [("revision", True), ("model_roots", -1),
                                          ("missing_model_roots", 1), ("incomplete_dependency_closures", 1)])
def test_release_notes_reject_unproven_resource_claims(field, value, monkeypatch):
    proof = scope_proof()
    proof["semantic_controls"]["features"]["octo"]["receipt"]["platforms"]["android"][field] = value
    monkeypatch.setattr(publisher.LATEST_SERVER_DATA, "load_pin", lambda: {"upgrade_proof": proof})
    with pytest.raises(publisher.ReleaseError, match="release_scope_proof_invalid"):
        publisher.release_scope_lines()


def test_release_body_uses_five_assets_and_labels_reused_client(monkeypatch):
    monkeypatch.setattr(publisher.LATEST_SERVER_DATA, "load_pin", lambda: {"upgrade_proof": scope_proof()})
    artifacts = [{"name": publisher.release_name(name), "source_name": name, "bytes": 1, "sha256": HASH}
                 for name in (publisher.APK, publisher.IPA)]
    body = publisher.release_body(SOURCE, RUN, {"commit": "c"*40}, artifacts,
                                  {"diagnostics": {}, "translation": {}},
                                  android_clients=[{"name": publisher.release_name(name), "source_name": name, "bytes": 1, "sha256": HASH}
                                                   for name in publisher.ANDROID_LANGUAGE_CLIENTS.values()])
    assert body.startswith("# 아이프라 로컬 " + RELEASE_VERSION)
    assert "서버 내부 버전 " + publisher.VERSION in body and publisher.IPA_VERSION in body
    for name in publisher.EXPECTED_RELEASE_ASSETS:
        assert publisher.asset_download_url(name) in body
    assert body.count("/releases/download/"+publisher.TAG+"/") == len(publisher.EXPECTED_RELEASE_ASSETS)
    assert body.count("/raw/"+"c"*40+"/") == 2
    assert "이번 릴리즈에서 재제작하지 않았습니다" in body
    assert "별도 Mac 서버와 동시에 실행하지 마세요" in body
    assert "통합 IPA는 게임 시작 전 한국어·일본어·영어" in body
    assert "원하는 언어판 하나로 교체 설치" in body
    assert "Mac / PlayCover: 같은 통합 IPA 하나" in body
    assert "5개 Assets" in body and "8개 테이블" in body
    assert "카드 504 / 의상 1011 / 헤어 1231" in body
    assert "Android revision 1097 / 모델 진입점 125" in body
    assert "iOS revision 1169 / 모델 진입점 125" in body
    assert "71편의 진행·감상" in body and "인계 실행 전에" in body
    assert "실제 공식 계정으로 인증·인계를 실행한 검증은 하지 않았습니다" in body
    assert publisher.MAC not in body and "Client-PlayCover-ko.ipa" not in body
    assert "실제 Android ARM64 기기" in body
    assert "Fix File Picker" in body and "실기기 ZIP 가져오기·진행 표시는 아직" in body
    assert "완전 오프라인 사용은 필요한 캐시를 준비한 뒤" in body


@pytest.mark.parametrize("case", ["digest", "size_bool", "state", "id_bool", "name", "url"])
def test_release_asset_API_metadata_requires_exact_uploaded_identity(case, release_binaries):
    wanted = release_binaries[0]
    actual = asset_metadata(wanted, 0)
    if case == "digest": actual["digest"] = "sha256:"+"0"*64
    elif case == "size_bool": actual["size"] = True
    elif case == "state": actual["state"] = "starter"
    elif case == "id_bool": actual["id"] = True
    elif case == "name": actual["name"] += ".zip"
    else: actual["browser_download_url"] = "https://example.com/file"
    with pytest.raises(publisher.ReleaseError):
        publisher.validate_release_asset(actual, wanted)


@pytest.mark.parametrize("case", ["missing", "extra", "duplicate", "new_id"])
def test_complete_release_inventory_rejects_missing_or_replaced_assets(case, release_binaries):
    actual = [asset_metadata(row, index) for index, row in enumerate(release_binaries)]
    receipts = [{"id": row["id"]} for row in actual]
    if case == "missing": actual.pop()
    elif case == "extra": actual.append(deepcopy(actual[0]))
    elif case == "duplicate": actual[0] = deepcopy(actual[1])
    else: actual[0]["id"] += 999
    with pytest.raises(publisher.ReleaseError):
        publisher.validate_release_inventory(actual, release_binaries, receipts)


@pytest.mark.parametrize("case", ["short", "long", "hash", "prefix", "status", "encoding"])
def test_full_binary_stream_cannot_be_replaced_by_metadata_only(case):
    import hashlib
    import io
    raw = b"PK\x03\x04payload"
    wanted = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    body, status, headers = raw, 200, {}
    if case == "short": body = raw[:-1]
    elif case == "long": body += b"!"
    elif case == "hash": wanted["sha256"] = "0"*64
    elif case == "prefix":
        body = b"NOPEpayload"
        wanted["sha256"] = hashlib.sha256(body).hexdigest()
    elif case == "status": status = 206
    else: headers["Content-Encoding"] = "gzip"
    response = io.BytesIO(body); response.status, response.headers = status, headers
    with pytest.raises(publisher.ReleaseError):
        publisher.verify_binary_stream(response, wanted, TinyGuard())


def test_asset_download_redirect_strips_API_credentials():
    import io
    from urllib.error import HTTPError
    class Opener:
        def __init__(self): self.requests = []
        def open(self, request, **_kwargs):
            self.requests.append(request)
            if len(self.requests) == 1:
                raise HTTPError(request.full_url, 302, "redirect",
                                {"Location":"https://release-assets.githubusercontent.com/temporary-object?signature=public-test"},
                                io.BytesIO())
            response = io.BytesIO(b"data"); response.status = 200; response.headers = {}
            return response
    opener = Opener()
    github = publisher.GitHub("private-test-token", opener)
    with github.binary_response("https://api.github.com/repos/"+publisher.REPO+"/releases/assets/77", asset_id=77):
        pass
    assert opener.requests[0].get_header("Authorization") == "Bearer private-test-token"
    assert opener.requests[1].get_header("Authorization") is None
    assert opener.requests[1].get_header("Accept-encoding") == "identity"


@pytest.mark.parametrize("url", ["http://release-assets.githubusercontent.com/file",
                                 "https://example.com/file", "https://user@release-assets.githubusercontent.com/file",
                                 "https://release-assets.githubusercontent.com/file#fragment"])
def test_asset_download_redirect_rejects_unapproved_origins(url):
    import io
    from urllib.error import HTTPError
    class Opener:
        def __init__(self): self.calls = 0
        def open(self, request, **_kwargs):
            self.calls += 1
            raise HTTPError(request.full_url, 302, "redirect", {"Location":url}, io.BytesIO())
    opener = Opener()
    with pytest.raises(publisher.ReleaseError):
        publisher.GitHub("test-token", opener).binary_response(
            "https://api.github.com/repos/"+publisher.REPO+"/releases/assets/77", asset_id=77)
    assert opener.calls == 1


def test_upload_streams_only_verified_owned_file_with_exact_length(release_binaries):
    import io
    import json
    wanted = release_binaries[0]
    class Opener:
        def open(self, request, **_kwargs):
            assert request.full_url == "https://uploads.github.com/repos/"+publisher.REPO+"/releases/77/assets?name="+wanted["name"]
            assert request.get_method() == "POST"
            assert request.get_header("Content-length") == str(wanted["bytes"])
            assert request.data.read() == Path(wanted["path"]).read_bytes()
            response = io.BytesIO(json.dumps(asset_metadata(wanted, 0)).encode())
            response.status, response.headers = 201, {}
            return response
    github = publisher.GitHub("test-token", Opener())
    github.owned_release_id = 77
    result = github.upload_asset(77, wanted)
    assert result["name"] == wanted["name"]


@pytest.mark.parametrize("failure", ["none", "pointer", "source", "qa", "hash"])
def test_companion_original_provenance_and_entire_download_are_required(failure, tmp_path):
    import hashlib
    import io
    import json
    raw = b"PK\x03\x04original-client"
    wanted = {**publisher.COMPANIONS[0], "bytes": len(raw), "sha256":hashlib.sha256(raw).hexdigest()}
    pointer = ("version https://git-lfs.github.com/spec/v1\noid sha256:"+wanted["sha256"]+"\nsize "+str(len(raw))+"\n").encode()
    provenance = {"source_commit":wanted["source_commit"],"version":wanted["version"],
        "artifacts":[{key:wanted[key] for key in ("name","bytes","sha256")}],
        "independent_QA":{"status":"PASS","source_commit":wanted["source_commit"],"bytes":len(raw),"sha256":wanted["sha256"]}}
    if failure == "pointer": pointer += b" "
    elif failure == "source": provenance["source_commit"] = "0"*40
    elif failure == "qa": provenance["independent_QA"]["status"] = "FAIL"
    class Opener:
        def __init__(self): self.calls = 0
        def open(self, request, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                assert request.full_url == "https://github.com/"+publisher.REPO+".git/info/lfs/objects/batch"
                result = {"objects":[{"oid":wanted["sha256"],"size":len(raw),"actions":{"download":{"href":"https://media.githubusercontent.com/test-object"}}}]}
                body = json.dumps(result).encode()
            else: body = raw[:-1] + b"!" if failure == "hash" else raw
            response = io.BytesIO(body); response.status, response.headers = 200, {}
            return response
    opener = Opener()
    class CompanionGitHub(publisher.GitHub):
        def git_file(self, commit, name, _maximum):
            assert commit == wanted["publication_commit"]
            return pointer if name == wanted["name"] else json.dumps(provenance).encode()
    github = CompanionGitHub("test-token", opener)
    if failure == "none":
        result = github.companion(wanted, tmp_path/wanted["name"], TinyGuard())
        assert result["full_download_SHA256_verified"] is True
        assert result["immutable_pointer_verified"] is True and result["fresh_source_build_claimed"] is False
        assert Path(result["path"]).read_bytes() == raw
    else:
        with pytest.raises(publisher.ReleaseError):
            github.companion(wanted, tmp_path/wanted["name"], TinyGuard())
        assert opener.calls == (2 if failure == "hash" else 0)


@pytest.mark.parametrize("failure", ["none", "truncated", "size", "sha"])
def test_git_blob_is_bound_to_immutable_tree_and_actual_blob_hash(failure):
    import base64
    import hashlib
    raw = b"pinned original metadata"
    blob_sha = hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()
    class BlobGitHub(publisher.GitHub):
        def api(self, path, **_kwargs):
            if path.startswith("/git/trees/"):
                return {"truncated": failure == "truncated", "tree":[{"path":"proof.json","type":"blob","size":len(raw),"sha":blob_sha}]}
            return {"sha":blob_sha,"encoding":"base64","size":len(raw)+(1 if failure == "size" else 0),
                    "content":base64.b64encode(raw+(b"!" if failure == "sha" else b"")).decode()}
    github = BlobGitHub("test-token", None)
    if failure == "none":
        assert github.git_file("a"*40, "proof.json", 4096) == raw
    else:
        with pytest.raises(publisher.ReleaseError):
            github.git_file("a"*40, "proof.json", 4096)


def diagnostics_benchmark():
    expected = {"baseline": {"poll": 1, "explicit_export": 2},
                "candidate": {"poll": 0, "explicit_export": 1}}
    hashes = {name: HASH for name in ("summary_sha256", "poll_sha256", "export_sha256")}
    full_outputs = {"baseline": {"poll_sha256": HASH, "export_sha256": HASH},
                    "candidate": {"poll_sha256": "c"*64, "export_sha256": "d"*64}}
    runs = {}
    for name, wall, cpu in (("baseline", 3.0, 2.0), ("candidate", 1.0, 1.0)):
        row = {"schema": 1, "role": name, "iterations": 1000, "source_root": "/trusted/"+name,
               "history_deepcopy_calls": expected[name], "synthetic_events": 200, "frames_per_event": 16,
               "poll_contains_events": False, "received_events": 200, "stored_events": 200, "default_full_events": 200,
               "exported_events": 200, **hashes, "wall_microseconds_per_poll": wall,
               "cpu_microseconds_per_poll": cpu, "tracemalloc_peak_bytes": 100000 if name == "baseline" else 1000,
               "comparison_scope": benchmark_contract.comparison_scope(),
               "management_contract": benchmark_contract.expected_management_evidence(name),
               "benchmark_sha256": HASH,
               **{"full_"+key: value for key, value in full_outputs[name].items()}}
        runs[name] = [deepcopy(row) for _ in range(3)]
    return {"schema": 1, "iterations": 1000, "repeats": 3, "tracemalloc_separate_pass": True,
            "expected_history_deepcopy_calls": expected, "identical_legacy_outputs": hashes, "runs": runs,
            "comparison_scope": benchmark_contract.comparison_scope(),
            "management_contract": benchmark_contract.management_contract(),
            "full_outputs": full_outputs, "benchmark_sha256": HASH,
            "source_sha256": {name: {"diagnostics.py": HASH, "app_runtime.py": HASH}
                              for name in ("baseline", "candidate")},
            "median": {"baseline": {"wall_microseconds_per_poll": 3.0, "cpu_microseconds_per_poll": 2.0},
                       "candidate": {"wall_microseconds_per_poll": 1.0, "cpu_microseconds_per_poll": 1.0}},
            "median_speedup": {"wall_microseconds_per_poll": 3.0, "cpu_microseconds_per_poll": 2.0}}


def test_diagnostics_benchmark_requires_real_copy_counts_and_recomputed_metrics(monkeypatch):
    monkeypatch.setattr(publisher, "blob_sha", lambda source, name: HASH)
    report = diagnostics_benchmark()
    publisher.validate_diagnostics_benchmark(report, SOURCE)
    report["median_speedup"]["wall_microseconds_per_poll"] = 999
    with pytest.raises(publisher.ReleaseError):
        publisher.validate_diagnostics_benchmark(report, SOURCE)


@pytest.mark.parametrize("case", ["dropped_export", "event_loss", "wrong_source", "unequal_semantics"])
def test_optimization_cannot_trade_away_diagnostic_export_or_output(monkeypatch, case):
    monkeypatch.setattr(publisher, "blob_sha", lambda source, name: HASH)
    report = diagnostics_benchmark()
    row = report["runs"]["candidate"][0]
    if case == "dropped_export": row["exported_events"] = 0
    elif case == "event_loss": row["stored_events"] = 199
    elif case == "wrong_source": report["source_sha256"]["candidate"]["diagnostics.py"] = "c"*64
    elif case == "unequal_semantics": row["poll_sha256"] = "c"*64
    with pytest.raises(publisher.ReleaseError):
        publisher.validate_diagnostics_benchmark(report, SOURCE)


@pytest.mark.parametrize("case", ["missing_scope", "extra_projection", "scope_bool", "missing_contract",
    "candidate_partial", "baseline_additions", "wrong_role", "contract_bool", "default_zero_bool",
    "copy_count_bool", "missing_full", "full_row_differs", "candidate_full_is_legacy", "benchmark_pin",
    "row_benchmark_pin", "trace_disabled", "trace_missing", "same_source_root", "old_identical_claim",
    "export_contract_partial", "event_bool", "worker_schema_bool"])
def test_diagnostics_management_extension_cannot_hide_other_changes_or_drop_provenance(monkeypatch, case):
    monkeypatch.setattr(publisher, "blob_sha", lambda source, name: HASH)
    report = diagnostics_benchmark()
    candidate = report["runs"]["candidate"][0]
    if case == "missing_scope": report.pop("comparison_scope")
    elif case == "extra_projection": report["comparison_scope"]["excluded_runtime_fields_after_validation"].append("client_diagnostics")
    elif case == "scope_bool": report["comparison_scope"]["schema"] = True
    elif case == "missing_contract": report.pop("management_contract")
    elif case == "candidate_partial": candidate["management_contract"]["poll"].pop("account_selection")
    elif case == "baseline_additions": report["runs"]["baseline"][0]["management_contract"]["poll"] = benchmark_contract.management_defaults()
    elif case == "wrong_role": candidate["role"] = "baseline"
    elif case == "contract_bool": candidate["management_contract"]["poll"]["durable_history"]["schema"] = True
    elif case == "default_zero_bool": candidate["management_contract"]["poll"]["account_selection"]["restart_required"] = 0
    elif case == "copy_count_bool": candidate["history_deepcopy_calls"]["explicit_export"] = True
    elif case == "missing_full": report.pop("full_outputs")
    elif case == "full_row_differs": candidate["full_poll_sha256"] = "e"*64
    elif case == "candidate_full_is_legacy": candidate["full_poll_sha256"] = candidate["poll_sha256"]
    elif case == "benchmark_pin": report["benchmark_sha256"] = "e"*64
    elif case == "row_benchmark_pin": candidate["benchmark_sha256"] = "e"*64
    elif case == "trace_disabled": report["tracemalloc_separate_pass"] = False
    elif case == "trace_missing": candidate.pop("tracemalloc_peak_bytes")
    elif case == "same_source_root":
        for row in report["runs"]["candidate"]: row["source_root"] = "/trusted/baseline"
    elif case == "old_identical_claim": report["identical_outputs"] = report["identical_legacy_outputs"]
    elif case == "export_contract_partial": candidate["management_contract"]["export_runtime"].pop("durable_history")
    elif case == "event_bool": candidate["received_events"] = True
    elif case == "worker_schema_bool": candidate["schema"] = True
    with pytest.raises(publisher.ReleaseError):
        publisher.validate_diagnostics_benchmark(report, SOURCE)


def translation_benchmark():
    semantics = {"coverage": {"ko": {"translated": 1}, "en": {"translated": 1}},
                 "original_manifest_sha256": HASH, "original_revision": 1159,
                 "sequence": [{"language": name, "manifest_sha256": HASH} for name in ("ja", "ko", "en", "ko")]}
    runs, medians = {}, {}
    for name, elapsed, validation, peak in (("baseline", 3.0, 2.0, 100), ("candidate", 4.0, 3.0, 110)):
        row = {"schema": 1, "status": "PASS", "protobuf": "python", "role": "measure",
               "semantics": deepcopy(semantics), "elapsed_seconds": elapsed, "validation_seconds": validation,
               "peak_rss_bytes": peak, "validation_peak_rss_bytes": peak}
        runs[name] = [deepcopy(row) for _ in range(3)]
        medians[name] = {key: row[key] for key in
                        ("elapsed_seconds", "validation_seconds", "peak_rss_bytes", "validation_peak_rss_bytes")}
    return {"schema": 1, "status": "PASS", "platform": "ios", "protobuf": "python", "same_semantics": True,
            "baseline_revision_expected": publisher.BASELINE, "sequence": ["ja", "ko", "en", "ko"],
            "runs_per_source": 3, "inputs": {"server_data": deepcopy(publisher.BASE_DATA_PIN),
                                            "translations": deepcopy(publisher.TRANSLATION_PINS["ios"])},
            "source_sha256": {name: {filename: HASH for filename in publisher.TRANSLATION_SOURCES}
                              for name in ("baseline", "candidate")},
            "runs": runs, "medians": medians, "median_peak_rss_saving_bytes": -10, "median_seconds_saved": -1.0}


def test_translation_benchmark_does_not_invent_a_positive_improvement(monkeypatch):
    monkeypatch.setattr(publisher, "blob_sha", lambda source, name: HASH)
    report = translation_benchmark()
    result = publisher.validate_translation_benchmark(report, SOURCE)
    assert result["median_peak_rss_saving_bytes"] == -10
    report["median_peak_rss_saving_bytes"] = 1000000
    with pytest.raises(publisher.ReleaseError):
        publisher.validate_translation_benchmark(report, SOURCE)


@pytest.mark.parametrize("case", ["changed_manifest", "wrong_source", "wrong_input", "truncated_runs", "not_python"])
def test_translation_benchmark_semantics_and_public_input_provenance_are_required(monkeypatch, case):
    monkeypatch.setattr(publisher, "blob_sha", lambda source, name: HASH)
    report = translation_benchmark()
    if case == "changed_manifest": report["runs"]["candidate"][0]["semantics"]["original_manifest_sha256"] = "c"*64
    elif case == "wrong_source": report["source_sha256"]["candidate"]["resource_translation_runtime.py"] = "c"*64
    elif case == "wrong_input": report["inputs"]["translations"]["sha256"] = "c"*64
    elif case == "truncated_runs": report["runs"]["candidate"].pop()
    elif case == "not_python": report["protobuf"] = "upb"
    with pytest.raises(publisher.ReleaseError):
        publisher.validate_translation_benchmark(report, SOURCE)


def test_android_language_client_job_and_artifact_are_mandatory():
    build, jobs, artifacts = metadata()
    jobs["jobs"] = [row for row in jobs["jobs"] if row["name"] != "android-clients"]
    jobs["total_count"] = len(jobs["jobs"])
    with pytest.raises(publisher.ReleaseError):
        publisher.validate_run(build, jobs, artifacts, SOURCE, RUN)
    build, jobs, artifacts = metadata()
    artifacts["artifacts"] = [row for row in artifacts["artifacts"]
                              if row["name"] != publisher.PREFIXES["android-clients"] + SOURCE]
    artifacts["total_count"] = len(artifacts["artifacts"])
    with pytest.raises(publisher.ReleaseError):
        publisher.validate_run(build, jobs, artifacts, SOURCE, RUN)


def client_report_fixture(directory):
    import hashlib
    import json
    reports = {}
    for name in publisher.ANDROID_CLIENT_REPORT_FILES:
        path = directory/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"schema":1}\n')
        reports[name] = {"bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    binaries = []
    for language, name in publisher.ANDROID_LANGUAGE_CLIENTS.items():
        path = directory/name
        path.write_bytes(b"PK\x03\x04" + language.encode()*4)
        binaries.append({"language": language, "name": name, "bytes": path.stat().st_size,
                         "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                         "application_id": "game.qualiarts.idolypride.local.diagnostics", "version_code": 414,
                         "certificate_sha256": publisher.ANDROID_CLIENT_CERTIFICATE})
    return {"schema": 1, "status": "PASS", "source_commit": SOURCE, "run_id": RUN,
            "languages": ["ja", "en"], "binaries": binaries,
            "inputs": {**deepcopy(publisher.ANDROID_CLIENT_INPUTS),
                "shadowhook": {"bytes": 461264, "sha256": "2cad01ff4d59542958775e19f281981a7e84b39670b5fae75905b8511e10c7cd"}},
            "source_sha256": {name: HASH for name in publisher.ANDROID_CLIENT_SOURCES},
            "validation": {**{name: True for name in publisher.ANDROID_CLIENT_FLAGS}, "runtime_device_tested": False},
            "report_files": reports}


@pytest.mark.parametrize("case", ["none", "source", "run", "bool_run", "languages", "missing_input",
    "input_digest", "shadowhook_bytes", "source_pin", "failed_qa", "numeric_qa", "device_claim",
    "missing_proof", "proof_digest", "missing_binary", "language_order", "certificate", "package",
    "version_bool", "binary_digest"])
def test_android_clients_require_pinned_inputs_identity_all_packaging_QA_and_raw_proofs(case, tmp_path, monkeypatch):
    import json
    report = client_report_fixture(tmp_path)
    def source_pins(values, source, *, required):
        publisher.need(source == SOURCE and required == publisher.ANDROID_CLIENT_SOURCES
                       and set(required) <= values.keys() and all(value == HASH for value in values.values()),
                       "mock_source_pin_differs")
    monkeypatch.setattr(publisher, "source_pins", source_pins)
    if case == "source": report["source_commit"] = "0"*40
    elif case == "run": report["run_id"] += 1
    elif case == "bool_run": report["run_id"] = True
    elif case == "languages": report["languages"] = ["ko", "en"]
    elif case == "missing_input": report["inputs"].pop("font")
    elif case == "input_digest": report["inputs"]["diagnostic_base"]["sha256"] = "0"*64
    elif case == "shadowhook_bytes": report["inputs"]["shadowhook"]["bytes"] += 1
    elif case == "source_pin": report["source_sha256"].pop(publisher.ANDROID_CLIENT_SOURCES[0])
    elif case == "failed_qa": report["validation"]["built_in_ui_language_verified"] = False
    elif case == "numeric_qa": report["validation"]["font_assets_verified"] = 1
    elif case == "device_claim": report["validation"]["runtime_device_tested"] = True
    elif case == "missing_proof": report["report_files"].pop(next(iter(publisher.ANDROID_CLIENT_REPORT_FILES)))
    elif case == "proof_digest":
        name = next(iter(publisher.ANDROID_CLIENT_REPORT_FILES))
        (tmp_path/name).write_text('{"changed":true}')
    elif case == "missing_binary": report["binaries"].pop()
    elif case == "language_order": report["binaries"].reverse()
    elif case == "certificate": report["binaries"][0]["certificate_sha256"] = "0"*64
    elif case == "package": report["binaries"][0]["application_id"] += ".other"
    elif case == "version_bool": report["binaries"][0]["version_code"] = True
    elif case == "binary_digest": (tmp_path/report["binaries"][0]["name"]).write_bytes(b"changed")
    (tmp_path/"android-clients-report.json").write_text(json.dumps(report))
    if case == "none":
        result = publisher.validate_android_clients(tmp_path, SOURCE, RUN)
        assert [row["language"] for row in result] == ["ja", "en"]
        assert all(Path(row["path"]).is_file() for row in result)
    else:
        with pytest.raises(publisher.ReleaseError):
            publisher.validate_android_clients(tmp_path, SOURCE, RUN)


@pytest.mark.parametrize("missing", [None, "android-clients-report.json",
                                    publisher.ANDROID_LANGUAGE_CLIENTS["ja"], "native/build-receipt.json"])
def test_client_artifact_safe_inventory_requires_both_APKs_and_all_raw_provenance(missing):
    names = {"android-clients-report.json", *publisher.ANDROID_LANGUAGE_CLIENTS.values(),
             *publisher.ANDROID_CLIENT_REPORT_FILES}
    if missing: names.remove(missing)
    class Archive:
        def infolist(self):
            result = []
            for name in names:
                row = ZipInfo(name)
                row.compress_type, row.file_size, row.external_attr = ZIP_STORED, 100, stat.S_IFREG << 16
                result.append(row)
            return result
    if missing:
        with pytest.raises(publisher.ReleaseError):
            publisher.generic_members(Archive(), "android-clients")
    else:
        assert set(publisher.generic_members(Archive(), "android-clients")) == names


def temporary_asset_url(name):
    return ("https://github.com/" + publisher.REPO
            + "/releases/download/untagged-19a339c5b788cf8128b3/" + name)


def test_github_draft_temporary_url_is_accepted_only_before_promotion(release_binaries):
    wanted = release_binaries[0]
    asset = asset_metadata(wanted, 0)
    asset["browser_download_url"] = temporary_asset_url(wanted["name"])
    with pytest.raises(publisher.ReleaseError):
        publisher.validate_release_asset(asset, wanted)
    assert publisher.validate_release_asset(asset, wanted, allow_draft_url=True) == asset


@pytest.mark.parametrize("case", ["repository", "file", "http", "query", "fragment", "short_tag",
                                 "uppercase_tag", "arbitrary_tag"])
def test_draft_URL_exception_is_limited_to_exact_repo_name_and_temporary_tag(case, release_binaries):
    wanted = release_binaries[0]
    asset = asset_metadata(wanted, 0)
    url = temporary_asset_url(wanted["name"])
    if case == "repository": url = url.replace(publisher.REPO, "another/repository")
    elif case == "file": url += ".other"
    elif case == "http": url = url.replace("https:", "http:")
    elif case == "query": url += "?download=1"
    elif case == "fragment": url += "#file"
    elif case == "short_tag": url = url.replace("19a339c5b788cf8128b3", "abc")
    elif case == "uppercase_tag": url = url.replace("19a339c5b788cf8128b3", "19A339C5B788CF8128B3")
    else: url = url.replace("untagged-19a339c5b788cf8128b3", "other-release")
    asset["browser_download_url"] = url
    with pytest.raises(publisher.ReleaseError):
        publisher.validate_release_asset(asset, wanted, allow_draft_url=True)


def test_draft_temporary_urls_keep_all_readbacks_then_update_final_canonical_receipts(release_binaries):
    github, snapshots = FakeGitHub(temporary_urls=True), []
    result = github.publish(SOURCE, "release", release_binaries, TinyGuard(),
                            save_assets=lambda rows:snapshots.append(deepcopy(rows)))
    assert result["draft"] is False
    assert github.events == ["upload", "readback"]*len(release_binaries) + ["promote"]
    assert len(github.asset_receipts) == len(publisher.EXPECTED_RELEASE_ASSETS)
    assert all(row["full_API_download_SHA256_verified"] is True for row in github.asset_receipts)
    assert all(row["download_url"] == publisher.asset_download_url(row["name"]) for row in github.asset_receipts)
    assert "untagged-" in snapshots[0][0]["download_url"]
    assert all(row["download_url"] == publisher.asset_download_url(row["name"]) for row in snapshots[-1])
    assert ("/releases/77", "PATCH", {"draft": False, "tag_name": publisher.TAG,
                                     "target_commitish": SOURCE}) in github.calls


def test_published_inventory_cannot_keep_draft_URLs(release_binaries):
    github = FakeGitHub(temporary_urls=True, final_temporary_urls=True)
    with pytest.raises(publisher.ReleaseError):
        github.publish(SOURCE, "release", release_binaries, TinyGuard())
    assert github.events.count("readback") == len(release_binaries)
    assert "promote" in github.events and github.rollback_draft_restored is True
    assert github.calls[-1] == ("/releases/77", "PATCH", {"draft": True})


def test_asset_upload_requires_the_new_owned_release(release_binaries):
    github = publisher.GitHub("test-token", None)
    with pytest.raises(publisher.ReleaseError, match="owned_draft_asset_upload_required"):
        github.upload_asset(77, release_binaries[0])
    github.owned_release_id = 77
    with pytest.raises(publisher.ReleaseError, match="owned_draft_asset_upload_required"):
        github.upload_asset(78, release_binaries[0])



def test_calendar_identity_is_required_and_frozen_before_release_actions(release_binaries, monkeypatch):
    assert publisher.TAG == "v" + RELEASE_VERSION
    assert publisher.configure_release(RELEASE_VERSION) == RELEASE_VERSION
    with pytest.raises(publisher.ReleaseError, match="release_identity_already_frozen"):
        publisher.configure_release("2026.11.16.2")
    assert publisher.RELEASE_VERSION == RELEASE_VERSION
    assert publisher.TAG == "v" + RELEASE_VERSION
    monkeypatch.setattr(publisher, "RELEASE_VERSION", None)
    github = FakeGitHub()
    with pytest.raises(publisher.ReleaseError, match="calendar_release_identity_required"):
        github.publish(SOURCE, "release", release_binaries, TinyGuard())
    assert github.calls == []


@pytest.mark.parametrize("version", ["0.3.36", "2026.02.30.1", "2026.11.16.0", "2026.11.16.01", "../2026.11.16.1"])
def test_invalid_calendar_version_stops_main_before_runner_or_network_work(version, tmp_path):
    with pytest.raises(publisher.ReleaseError, match="calendar_release_version_invalid"):
        publisher.main(["--release-version", version, "--source-commit", SOURCE, "--run-id", str(RUN),
                        "--work", str(tmp_path/"work"), "--output", str(tmp_path/"output")])
    assert list(tmp_path.iterdir()) == []


def test_release_version_argument_is_required_before_actions(tmp_path):
    with pytest.raises(SystemExit) as error:
        publisher.main(["--source-commit", SOURCE, "--run-id", str(RUN),
                        "--work", str(tmp_path/"work"), "--output", str(tmp_path/"output")])
    assert error.value.code == 2
    assert list(tmp_path.iterdir()) == []


def test_all_five_files_are_staged_with_exact_original_bytes_and_provenance(source_release_binaries, tmp_path):
    expected = {row["name"]: {**row, "body": Path(row["path"]).read_bytes()} for row in source_release_binaries}
    staged = publisher.stage_release_binaries(source_release_binaries, tmp_path/"public", TinyGuard())
    assert {row["name"] for row in staged} == publisher.EXPECTED_RELEASE_ASSETS
    assert len({row["name"] for row in staged}) == 5
    assert {row["source_name"] for row in staged} == publisher.INPUT_RELEASE_ASSETS
    for row in staged:
        original = expected[row["source_name"]]
        assert row["name"] == publisher.release_name(row["source_name"])
        assert RELEASE_VERSION in row["name"]
        assert Path(row["path"]).name == row["name"]
        assert Path(row["path"]).read_bytes() == original["body"]
        assert (row["bytes"], row["sha256"]) == (original["bytes"], original["sha256"])
        assert not Path(original["path"]).exists()
        assert original["name"] == row["source_name"]
        assert publisher.asset_download_url(row["name"]).endswith("/" + publisher.TAG + "/" + row["name"])


@pytest.mark.parametrize("case", ["unknown", "duplicate", "changed_bytes", "path_name", "source_name", "symlink", "existing_directory"])
def test_staging_validates_entire_inventory_before_moving_any_file(case, source_release_binaries, tmp_path):
    rows = deepcopy(source_release_binaries)
    destination = tmp_path/"public"
    if case == "unknown": rows[1]["name"] = "untracked.apk"
    elif case == "duplicate": rows[1] = dict(rows[0])
    elif case == "changed_bytes": Path(rows[1]["path"]).write_bytes(b"changed")
    elif case == "path_name": rows[1]["path"] = str(tmp_path/"other.apk")
    elif case == "source_name": rows[1]["source_name"] = "another-origin.apk"
    elif case == "symlink":
        original = Path(rows[1]["path"])
        original.rename(tmp_path/"original-input")
        original.symlink_to(tmp_path/"original-input")
    else: destination.mkdir()
    first = Path(rows[0]["path"])
    with pytest.raises(publisher.ReleaseError):
        publisher.stage_release_binaries(rows, destination, TinyGuard())
    assert first.is_file()
    assert not (destination/publisher.release_name(rows[0]["name"])).exists()


@pytest.mark.parametrize("case", ["old_name", "other_date", "swapped_source"])
def test_release_rejects_original_or_mixed_date_names_before_creating_draft(case, release_binaries):
    if case == "old_name": release_binaries[0]["name"] = release_binaries[0]["source_name"]
    elif case == "other_date":
        release_binaries[0]["name"] = release_binaries[0]["name"].replace(RELEASE_VERSION, "2026.11.16.2")
    else:
        release_binaries[0]["source_name"], release_binaries[1]["source_name"] = (
            release_binaries[1]["source_name"], release_binaries[0]["source_name"])
    github = FakeGitHub()
    with pytest.raises(publisher.ReleaseError):
        github.publish(SOURCE, "release", release_binaries, TinyGuard())
    assert github.calls == []


def test_public_download_urls_reject_unversioned_original_names():
    for name in publisher.INPUT_RELEASE_ASSETS:
        with pytest.raises(publisher.ReleaseError, match="release_asset_name_not_versioned"):
            publisher.asset_download_url(name)



def test_reused_companion_renaming_preserves_original_build_provenance(source_release_binaries, tmp_path):
    origin = publisher.COMPANIONS[0]
    row = next(row for row in source_release_binaries if row["name"] == origin["name"])
    row.update({key: origin[key] for key in ("version", "source_commit", "publication_commit")})
    row.update(reused_unchanged=True, fresh_source_build_claimed=False,
               original_provenance_sha256=HASH, immutable_pointer_verified=True,
               full_download_SHA256_verified=True)
    staged = publisher.stage_release_binaries([row], tmp_path/"companion-release", TinyGuard())[0]
    assert staged["name"] == publisher.release_name(origin["name"])
    assert staged["source_name"] == origin["name"]
    for key, value in row.items():
        if key not in ("name", "path"):
            assert staged[key] == value
    assert staged["version"] == "0.3.31" and staged["fresh_source_build_claimed"] is False


@pytest.mark.parametrize("platform", ["android", "macos"])
@pytest.mark.parametrize("case", ["missing", "changed-base", "changed-source", "extra-claim"])
def test_native_payload_requires_the_exact_source_bound_upgrade_proof(monkeypatch, platform, case):
    monkeypatch.setattr(publisher, "blob_sha", lambda source, name: HASH)
    report = platform_report(platform)
    proof = report["inputs"]["server_data_provenance"]
    if case == "missing": del report["inputs"]["server_data_provenance"]
    elif case == "changed-base": proof["base"]["sha256"] = "f"*64
    elif case == "changed-source": proof["component_sources_sha256"] = "f"*64
    else: proof["unverified_claim"] = True
    with pytest.raises(publisher.ReleaseError, match="preparation_provenance"):
        publisher.validate_platform(report, platform, SOURCE)


def test_native_publication_and_builder_require_the_same_latest_source_closure():
    builds = publisher.module("publication_latest_builder_contract",
        publisher.ROOT/"tools/release_platform_builds.py")
    assert publisher.LOVE_SERVER_DATA is publisher.LATEST_SERVER_DATA
    assert publisher.DATA_PIN == publisher.LATEST_SERVER_DATA.output_pin() == builds.SERVER_DATA
    assert publisher.DATA_PIN != publisher.BASE_DATA_PIN == builds.BASE_SERVER_DATA
    assert set(publisher.COMMON_SOURCES) == set(builds.COMMON_SOURCE_FILES)
    assert set(publisher.LATEST_SERVER_DATA.SOURCE_COMPONENTS) <= set(publisher.COMMON_SOURCES)
    assert {"data/latest-server-data-pin.json", "data/latest-server-overlay.zip",
        "src/idoly_local/public_payload_transaction.py",
        "src/idoly_local/latest_cohort_pins.py", "src/idoly_local/love_compatibility_pins.py"
    } <= set(publisher.COMMON_SOURCES)


def test_native_metadata_requires_all_resource_runtime_guards():
    assert {"src/idoly_local/resource_archive.py", "src/idoly_local/resource_library.py",
        "src/idoly_local/resource_translation.py", "src/idoly_local/resource_translation_runtime.py",
        "src/idoly_local/octo_runtime.py"} <= set(publisher.COMMON_SOURCES)


def test_current_release_has_exact_five_roles_and_excludes_standalone_mac():
    assert publisher.JOBS == ("portable", "performance", "android", "android-clients", "ios-unified")
    assert len(publisher.INPUT_RELEASE_ASSETS) == len(publisher.EXPECTED_RELEASE_ASSETS) == 5
    assert {row["name"] for row in publisher.COMPANIONS} == {
        "IdolyPride-Local-Graphics-Diagnostic-Android-arm64-ko.apk"}
    assert publisher.MAC not in publisher.INPUT_RELEASE_ASSETS
    for old_name in (publisher.MAC, "IdolyPride-6.1.1-Local-PlayCover-ko.ipa"):
        with pytest.raises(publisher.ReleaseError, match="release_source_name_invalid"):
            publisher.release_name(old_name)


@pytest.mark.parametrize("old_name", [publisher.MAC, "IdolyPride-6.1.1-Local-PlayCover-ko.ipa"])
def test_excluded_mac_asset_cannot_reenter_current_publication(old_name, source_release_binaries, tmp_path):
    rows = deepcopy(source_release_binaries)
    rows[0]["name"] = old_name
    with pytest.raises(publisher.ReleaseError, match="release_staging_input_names_invalid"):
        publisher.stage_release_binaries(rows, tmp_path/"forbidden", TinyGuard())
    assert all(Path(row["path"]).is_file() for row in source_release_binaries)
