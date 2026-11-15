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


def metadata():
    build = {"id": RUN, "head_sha": SOURCE, "event": "workflow_dispatch",
             "repository": {"full_name": publisher.REPO},
             "path": ".github/workflows/release-all-platforms.yml"}
    jobs = {"total_count": 6, "jobs": [{"name": name, "conclusion": "success"} for name in publisher.JOBS]
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


class FakeGitHub(publisher.GitHub):
    def __init__(self, *, existing=False, bad_tag=False):
        super().__init__("test-token", None)
        self.calls, self.existing, self.bad_tag = [], existing, bad_tag

    def api(self, path, *, method="GET", body=None, absent=False):
        self.calls.append((path, method, body))
        if method == "GET" and path.startswith("/releases/tags/"):
            return {"id": 1} if self.existing else None
        if method == "GET" and path == "/releases?per_page=100": return []
        if method == "GET" and path.startswith("/git/ref/"):
            if self.owned_release_id is None: return None
            return {"object": {"type": "commit", "sha": ("c"*40 if self.bad_tag else SOURCE)}}
        if method == "POST":
            return {"id": 77, "tag_name": publisher.TAG, "draft": True,
                    "prerelease": True, "target_commitish": SOURCE}
        if method == "PATCH" and body["draft"] is True:
            return {"id": 77, "draft": True}
        if method == "PATCH":
            return {"id": 77, "tag_name": publisher.TAG, "draft": False, "prerelease": True,
                    "target_commitish": SOURCE, "published_at": "2026-11-15T00:00:00Z",
                    "html_url": "https://github.com/"+publisher.REPO+"/releases/tag/"+publisher.TAG}
        raise AssertionError("Unexpected API call")


def test_existing_release_is_never_changed():
    github = FakeGitHub(existing=True)
    with pytest.raises(publisher.ReleaseError):
        github.publish(SOURCE, "release")
    assert all(method == "GET" for _path, method, _body in github.calls)


def test_new_release_promotes_only_source_bound_owned_draft():
    github = FakeGitHub()
    result = github.publish(SOURCE, "release")
    assert result["draft"] is False and result["prerelease"] is True
    assert github.owned_release_id == 77
    assert [body for _path, method, body in github.calls if method == "POST"] == [{
        "tag_name": publisher.TAG, "target_commitish": SOURCE,
        "name": "아이프라 로컬 v"+publisher.VERSION+" · 서버 기록·프로필 복구", "body": "release",
        "draft": True, "prerelease": True, "make_latest": "false"}]


def test_failed_promotion_verification_restores_only_just_created_draft():
    github = FakeGitHub(bad_tag=True)
    with pytest.raises(publisher.ReleaseError):
        github.publish(SOURCE, "release")
    assert github.rollback_draft_restored is True
    assert github.calls[-1] == ("/releases/77", "PATCH", {"draft": True})


def test_release_body_uses_fixed_new_downloads_and_labels_reused_clients():
    artifacts = [{"name": name, "bytes": 1, "sha256": HASH} for name in (publisher.APK, publisher.MAC, publisher.IPA)]
    body = publisher.release_body(SOURCE, RUN, {"commit": "c"*40}, artifacts,
                                  {"diagnostics": {}, "translation": {}})
    assert body.count("/raw/"+"c"*40+"/") == 3
    assert "이번 릴리즈에서 재제작하지 않았습니다" in body
    assert "별도 Mac 서버와 동시에 실행하지 마세요" in body
    assert "실제 Android ARM64 기기" in body


def diagnostics_benchmark():
    expected = {"baseline": {"poll": 1, "explicit_export": 2},
                "candidate": {"poll": 0, "explicit_export": 1}}
    hashes = {name: HASH for name in ("summary_sha256", "poll_sha256", "export_sha256")}
    runs = {}
    for name, wall, cpu in (("baseline", 3.0, 2.0), ("candidate", 1.0, 1.0)):
        row = {"history_deepcopy_calls": expected[name], "synthetic_events": 200, "frames_per_event": 16,
               "poll_contains_events": False, "stored_events": 200, "default_full_events": 200,
               "exported_events": 200, **hashes, "wall_microseconds_per_poll": wall,
               "cpu_microseconds_per_poll": cpu}
        runs[name] = [deepcopy(row) for _ in range(3)]
    return {"schema": 1, "iterations": 1000, "repeats": 3,
            "expected_history_deepcopy_calls": expected, "identical_outputs": hashes, "runs": runs,
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
            "runs_per_source": 3, "inputs": {"server_data": deepcopy(publisher.DATA_PIN),
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
