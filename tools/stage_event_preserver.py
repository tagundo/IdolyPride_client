"""Stage only the verified Mac event-preserver candidate into a new draft."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler
from zipfile import ZipFile

REPO = "tagundo/IdolyPride_client"
SOURCE = "11759580f423b616f368c38ac3d02c5022bd3b10"
RUN = 42941660798
ARTIFACT = 13820254198
TAG = "event-preserver-v0.1.0"
APP = "IdolyPride-Event-Preserver-Mac-arm64.zip"
QA = "IdolyPride-Event-Preserver-Mac-arm64-QA.zip"
PINS = {APP: (17413193, "faff8310c6ed5a8f4bb9d29179b8378519f1392039d8f06c5ef29504e391fd0c"),
        QA: (3295, "8e0d0753fe70ce0f121740a07f4b6122d597515dca66857854137599aa840e2f")}
REPORTS = {"source-provenance.json", "worker-self-test.json", "frozen-offline-inspection.json",
           "app-smoke.json", "relocated-app-smoke.json", "build-summary.json",
           "public-tls-handshake.json", "synthetic-test-summary.json"}


def need(value, code):
    if not value:
        raise ValueError(code)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def verify_candidate(directory):
    directory = Path(directory)
    need(directory.is_dir() and not directory.is_symlink(), "candidate_directory_invalid")
    need({p.name for p in directory.iterdir()} == set(PINS), "candidate_files_differ")
    blobs = {}
    for name, (size, digest) in PINS.items():
        path = directory / name
        need(path.is_file() and not path.is_symlink() and path.stat().st_size == size, "candidate_size_differs")
        with path.open("rb") as stream:
            raw = stream.read(size + 1)
        need(len(raw) == size and sha(raw) == digest, "candidate_hash_differs")
        blobs[name] = raw
    with ZipFile(directory / QA) as archive:
        need(set(archive.namelist()) == REPORTS and len(archive.namelist()) == len(REPORTS), "qa_files_differ")
        need(all(info.file_size < 65536 for info in archive.infolist()), "qa_size_invalid")
        reports = {name: json.loads(archive.read(name)) for name in REPORTS}
    provenance = reports["source-provenance.json"]
    need(provenance["source_commit"] == SOURCE and provenance["architecture"] == "arm64"
         and provenance["bundled_user_credentials"] is False
         and provenance["official_account_login_tested"] is False
         and provenance["game_client_tested"] is False, "qa_source_differs")
    need(reports["build-summary.json"]["sha256"] == PINS[APP][1], "qa_app_hash_differs")
    for name in ("app-smoke.json", "relocated-app-smoke.json"):
        need(all(reports[name].get(key) is True for key in
                 ("ok", "gui_started", "window_visible", "offline_inspection_completed", "no_network_capture_called"))
             and reports[name].get("real_account_tested") is False, "qa_gui_failed")
    summary = reports["synthetic-test-summary.json"]
    need(summary["tests"] == 150 and all(summary[k] == 0 for k in ("failures", "errors", "skipped")), "qa_tests_failed")
    need(reports["worker-self-test.json"]["ok"] is True
         and reports["public-tls-handshake.json"]["certificate_verified"] is True
         and reports["public-tls-handshake.json"]["application_bytes_sent"] == 0, "qa_worker_tls_failed")
    return blobs


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("api_redirect_rejected")


def stage(directory, evidence):
    blobs = verify_candidate(directory)
    need(os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("GITHUB_REPOSITORY") == REPO,
         "github_actions_required")
    token = os.environ.get("GH_TOKEN", "")
    need(bool(token), "github_token_required")
    opener = build_opener(NoRedirect())
    def request(method, path, body=None, *, upload=False, content_type="application/json"):
        host = "https://uploads.github.com" if upload else "https://api.github.com"
        headers = {"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
                   "Content-Type": content_type, "X-GitHub-Api-Version": "2022-11-28",
                   "User-Agent": "IdolyPride-verified-event-preserver-stager"}
        if isinstance(body, dict):
            body = json.dumps(body, ensure_ascii=False).encode()
        with opener.open(Request(host + path, data=body, headers=headers, method=method), timeout=120) as response:
            raw = response.read(4 * 1024 * 1024 + 1)
            need(len(raw) <= 4 * 1024 * 1024, "api_response_too_large")
            return json.loads(raw)
    prefix = "/repos/" + REPO
    run = request("GET", prefix + "/actions/runs/" + str(RUN))
    need(run["head_sha"] == SOURCE and run["status"] == "completed" and run["conclusion"] == "success"
         and run["event"] == "workflow_dispatch" and run["path"] == ".github/workflows/build-event-preserver.yml",
         "build_run_differs")
    artifact = request("GET", prefix + "/actions/artifacts/" + str(ARTIFACT))
    need(artifact["workflow_run"]["id"] == RUN and artifact["workflow_run"]["head_sha"] == SOURCE
         and artifact["expired"] is False
         and artifact["name"] == "IdolyPride-Event-Preserver-Mac-arm64-candidate"
         and artifact["digest"] == "sha256:df74c796a9e0d0a695fa35edf5679b459294d8f3d0a3f3ddae7dabf2c5bd01e5",
         "build_artifact_differs")
    # The tag endpoint can omit unpublished drafts. Inspect all visible releases
    # before creating anything, including a draft whose git tag does not exist.
    for page in range(1, 11):
        releases = request("GET", prefix + "/releases?per_page=100&page=" + str(page))
        need(isinstance(releases, list), "release_lookup_failed")
        need(all(row.get("tag_name") != TAG for row in releases), "release_already_exists")
        if len(releases) < 100:
            break
    else:
        raise ValueError("release_lookup_limit")
    try:
        request("GET", prefix + "/git/ref/tags/" + TAG)
    except HTTPError as error:
        need(error.code == 404, "release_lookup_failed")
    else:
        raise ValueError("release_tag_already_exists")
    body = """로그인된 PlayCover의 기존 계정으로 이미지 트레이닝·VENUS 메뉴 응답을 Mac에 보관하는 별도 앱입니다. Apple Silicon macOS 13 이상이며 Python 설치가 필요 없습니다.

앱 실행 → 오프라인 점검 → 보존 위치 선택 → 기존 계정 로그인·메뉴 조회 체크 → 보존 시작 순서로 사용합니다. 자료와 인증값은 업로드하지 않으며 보존 폴더는 Mac에 보관해 주세요. 정상 로그인·메뉴 조회에 따른 세션·월간 상태 갱신은 발생할 수 있습니다.

macOS 실제 빌드·서명·GUI 실행·이동 후 실행·TLS 인증서 확인과 모의 검사 150개를 통과했습니다. 사용자 계정의 실제 로그인 성공은 아직 검증하지 못했습니다. 이 앱은 서버 APK 업데이트가 아니며 포토 촬영·지역 생성·대전 시작은 자동 실행하지 않습니다. ad-hoc 서명이며 Apple 공증은 되어 있지 않습니다.
"""
    release = request("POST", prefix + "/releases", {"tag_name": TAG, "target_commitish": SOURCE,
        "name": "아이프라 이벤트 보존 도구 v0.1.0 (Mac)", "body": body, "draft": True, "prerelease": True})
    need(release["draft"] is True and release["tag_name"] == TAG, "draft_creation_differs")
    rid = release["id"]
    sums = "".join(f"{PINS[name][1]}  {name}\n" for name in sorted(PINS)).encode()
    blobs["SHA256SUMS"] = sums
    assets = []
    for name, blob in blobs.items():
        asset = request("POST", prefix + "/releases/" + str(rid) + "/assets?" + urlencode({"name": name}),
                        blob, upload=True, content_type="application/octet-stream")
        need(asset["name"] == name and asset["state"] == "uploaded" and asset["size"] == len(blob)
             and asset["digest"] == "sha256:" + sha(blob), "uploaded_asset_differs")
        assets.append({k: asset[k] for k in ("id", "name", "size", "digest", "browser_download_url")})
    record = {"schema": 1, "draft": True, "published": False, "release_id": rid, "tag": TAG,
              "source_commit": SOURCE, "build_run": RUN, "assets": assets}
    Path(evidence).write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(record, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    try:
        stage(args.candidate, args.evidence)
    except Exception as error:
        # Fixed API paths contain only this repository's public build/release
        # identity. Never print response bodies, headers or credentials.
        details = {"ok": False, "error_class": type(error).__name__}
        if isinstance(error, HTTPError):
            details["http_status"] = error.code
            details["api_path"] = error.url.split(".github.com", 1)[-1]
        print(json.dumps(details), file=sys.stderr)
        raise SystemExit(1) from None
