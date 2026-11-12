#!/usr/bin/env python3
"""Stage the five independently reviewed v0.3.19 binaries; publish only on request.

This entry point accepts no repository, URL, filename, release, or manifest arguments.
It uses a GitHub Actions token to promote existing SHA-pinned LFS objects, never
builds binaries, and never replaces an asset. No signed URLs or credentials are logged.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import ssl
import stat
import subprocess
import tempfile
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "tagundo/IdolyPride_client"
TAG = "local-server-v0.3.19"
RELEASE_ID = 443423317
TARGET = "227fc76708ecda43f9a6ef1726ab38380b02d315"
MANIFEST = ".github/release-delivery/v0.3.19.json"
REVIEW = ".github/release-delivery/v0.3.19-review.json"
SOURCES = {
    "IdolyPride-Local-Server-Android.apk": "c532c45f830a7231b256bb5d0c9ceef39e81dfcb",
    "IdolyPride-Local-Graphics-Diagnostic-Android-arm64.apk": TARGET,
    "IdolyPride-Local-Server-macOS-arm64.app.zip": TARGET,
    "IdolyPride-6.1.1-Local-PlayCover.ipa": TARGET,
    "IdolyPride-ServerData-v0.3.19.zip": "b1564719b678bb3276e6e0b2a6ef99f198ec1ac5",
}
API = "https://api.github.com/repos/" + REPOSITORY
BATCH = "https://github.com/" + REPOSITORY + ".git/info/lfs/objects/batch"
LFS_HOSTS = {"github.com", "lfs.github.com", "github-cloud.githubusercontent.com", "media.githubusercontent.com",
             "objects.githubusercontent.com", "github-cloud.s3.amazonaws.com"}
ASSET_HOSTS = {"release-assets.githubusercontent.com", "objects.githubusercontent.com"}
MAX_JSON = 128 * 1024
MAX_ASSET = 2 * 1024**3
CHUNK = 64 * 1024


class Refused(Exception):
    """Closed, public failure codes, without remote error text or signed URLs."""


def need(condition, code):
    if not condition:
        raise Refused(code)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def is_sha(value, length=64):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{%d}" % length, value) is not None


def exact(value, keys):
    return isinstance(value, dict) and set(value) == set(keys)


def object_pairs(pairs):
    result = {}
    for key, value in pairs:
        need(key not in result, "duplicate_json_key")
        result[key] = value
    return result


def decode_json(raw):
    need(len(raw) <= MAX_JSON, "json_too_large")
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=object_pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(Refused("invalid_json")))
    except (UnicodeError, ValueError) as error:
        raise Refused("invalid_json") from None


def read_public(path):
    info = path.lstat()
    need(stat.S_ISREG(info.st_mode) and 0 < info.st_size <= MAX_JSON, "invalid_public_input")
    with path.open("rb") as stream:
        raw = stream.read(MAX_JSON + 1)
    need(len(raw) == info.st_size, "public_input_changed")
    return raw


def identity(value):
    need(value.get("schema") == 1 and type(value.get("schema")) is int
         and value.get("repository") == REPOSITORY and value.get("tag") == TAG
         and type(value.get("release_id")) is int and value["release_id"] == RELEASE_ID
         and value.get("target_commit") == TARGET, "delivery_identity_differs")


def records(value, *, reviewed=False):
    need(isinstance(value, list) and len(value) == 5, "exactly_five_artifacts_required")
    result = {}
    keys = {"name", "bytes", "sha256", "source_commit"}
    for row in value:
        need(exact(row, keys | ({"qa_status", "qa_receipt_sha256"} if reviewed else set())),
             "artifact_fields_differ")
        name = row["name"]
        need(isinstance(name, str) and name in SOURCES and name not in result, "artifact_name_differs")
        need(type(row["bytes"]) is int and 0 < row["bytes"] <= MAX_ASSET
             and is_sha(row["sha256"]) and row["source_commit"] == SOURCES[name], "artifact_pin_differs")
        if reviewed:
            need(row["qa_status"] == "PASS" and is_sha(row["qa_receipt_sha256"]), "independent_review_missing")
        result[name] = dict(row)
    need(set(result) == set(SOURCES), "artifact_set_differs")
    need(sum(row["bytes"] for row in result.values()) <= 4 * 1024**3, "delivery_size_exceeded")
    return result


def load_delivery(root=ROOT):
    raw = read_public(root / MANIFEST)
    manifest = decode_json(raw)
    need(exact(manifest, {"schema", "repository", "tag", "release_id", "target_commit", "review", "artifacts"}),
         "manifest_fields_differ")
    identity(manifest)
    need(exact(manifest["review"], {"path", "sha256"}) and manifest["review"]["path"] == REVIEW
         and is_sha(manifest["review"]["sha256"]), "review_pin_differs")
    review_raw = read_public(root / REVIEW)
    need(digest(review_raw) == manifest["review"]["sha256"], "review_hash_differs")
    review = decode_json(review_raw)
    need(exact(review, {"schema", "repository", "tag", "release_id", "target_commit", "status", "artifacts"}),
         "review_fields_differ")
    identity(review)
    need(review["status"] == "PASS", "independent_review_missing")
    assets = records(manifest["artifacts"])
    reviewed = records(review["artifacts"], reviewed=True)
    for name, row in assets.items():
        need(all(reviewed[name][key] == val for key, val in row.items()), "review_artifact_differs")
    verification = {
        "schema": 1, "repository": REPOSITORY, "tag": TAG, "release_id": RELEASE_ID,
        "target_commit": TARGET, "delivery_manifest_sha256": digest(raw),
        "independent_review_envelope_sha256": digest(review_raw),
        "artifacts": [reviewed[name] for name in sorted(reviewed)],
        "verification_scope": "Five prebuilt binaries matched independent review pins; LFS and uploaded release bytes fully SHA-256 verified before publication. No new device execution is asserted.",
    }
    proof = (json.dumps(verification, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode()
    # Six entries: five binaries and the deterministic proof. SHA256SUMS excludes itself.
    sums = {name: row["sha256"] for name, row in assets.items()}
    sums["RELEASE-VERIFICATION.json"] = digest(proof)
    checksum = "".join(sums[name] + "  " + name + "\n" for name in sorted(sums)).encode()
    metadata = {"RELEASE-VERIFICATION.json": proof, "SHA256SUMS": checksum}
    expected = {name: dict(row) for name, row in assets.items()}
    expected.update({name: {"name": name, "bytes": len(data), "sha256": digest(data)}
                     for name, data in metadata.items()})
    return expected, metadata


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def approved_url(url, hosts):
    need(isinstance(url, str) and len(url) <= 16384 and not any(ord(c) < 33 or ord(c) == 127 for c in url),
         "download_url_refused")
    try:
        parsed = urlsplit(url)
        ok = (parsed.scheme == "https" and parsed.hostname in hosts and parsed.port in (None, 443)
              and parsed.username is None and parsed.password is None and not parsed.fragment)
    except ValueError:
        ok = False
    need(ok, "download_url_refused")
    return url


def stream_verified(response, expected, destination=None):
    need(response.status == 200, "download_status_differs")
    need(response.headers.get("Content-Encoding", "identity").lower() == "identity", "encoded_download_refused")
    length = response.headers.get("Content-Length")
    need(length is None or length == str(expected["bytes"]), "download_length_differs")
    total = 0
    sha = hashlib.sha256()
    while True:
        block = response.read(CHUNK)
        if not block:
            break
        total += len(block)
        need(total <= expected["bytes"], "overlong_download")
        sha.update(block)
        if destination is not None:
            destination.write(block)
    need(total == expected["bytes"] and sha.hexdigest() == expected["sha256"], "download_hash_or_size_differs")


class GitHub:
    def __init__(self, token, directory):
        self.token, self.directory = token, directory
        self.opener = build_opener(NoRedirect(), HTTPSHandler(context=ssl.create_default_context()))

    def api(self, path, *, method="GET", body=None, absent=False):
        need(path.startswith("/") and not path.startswith("//"), "api_path_refused")
        request = Request(API + path, method=method,
                          data=None if body is None else json.dumps(body).encode(), headers={
            "Authorization": "Bearer " + self.token, "Accept": "application/vnd.github+json",
            "Content-Type": "application/json", "X-GitHub-Api-Version": "2022-11-28"})
        try:
            with self.opener.open(request, timeout=60) as response:
                return decode_json(response.read(MAX_JSON + 1))
        except HTTPError as error:
            if absent and error.code == 404:
                return None
            raise Refused("github_api_http_" + str(error.code)) from None

    def release(self, *, published=False):
        release = self.api("/releases/" + str(RELEASE_ID))
        need(isinstance(release, dict) and release.get("id") == RELEASE_ID
             and release.get("tag_name") == TAG and release.get("target_commitish") == TARGET
             and release.get("draft") is (not published), "release_identity_or_draft_differs")
        tag = self.api("/git/ref/tags/" + TAG, absent=True)
        if tag is not None:
            obj = tag.get("object", {})
            for _ in range(3):
                if obj.get("type") == "commit":
                    break
                need(obj.get("type") == "tag" and is_sha(obj.get("sha"), 40), "tag_identity_differs")
                obj = self.api("/git/tags/" + obj["sha"]).get("object", {})
            need(obj.get("type") == "commit" and obj.get("sha") == TARGET, "tag_identity_differs")
        else:
            need(not published, "published_tag_missing")
        assets = self.api("/releases/" + str(RELEASE_ID) + "/assets?per_page=100")
        need(isinstance(assets, list) and len(assets) <= 7, "release_asset_inventory_differs")
        return assets

    def lfs_download(self, row, path):
        basic = base64.b64encode(("x-access-token:" + self.token).encode()).decode()
        payload = json.dumps({"operation": "download", "transfers": ["basic"],
                              "objects": [{"oid": row["sha256"], "size": row["bytes"]}]}).encode()
        request = Request(BATCH, data=payload, headers={"Authorization": "Basic " + basic,
            "Content-Type": "application/vnd.git-lfs+json", "Accept": "application/vnd.git-lfs+json"})
        with self.opener.open(request, timeout=60) as response:
            result = decode_json(response.read(MAX_JSON + 1))
        objects = result.get("objects")
        need(isinstance(objects, list) and len(objects) == 1, "lfs_object_differs")
        obj = objects[0]
        need(obj.get("oid") == row["sha256"] and type(obj.get("size")) is int
             and obj["size"] == row["bytes"] and not obj.get("error"), "lfs_object_differs")
        action = obj.get("actions", {}).get("download", {})
        href = approved_url(action.get("href"), LFS_HOSTS)
        need(self.token not in href, "credential_forwarding_refused")
        headers = action.get("header", {})
        need(isinstance(headers, dict) and len(headers) <= 16, "lfs_headers_refused")
        for key, val in headers.items():
            need(isinstance(key, str) and re.fullmatch(r"[A-Za-z0-9-]{1,64}", key)
                 and key.lower() not in {"host", "cookie", "proxy-authorization"}
                 and isinstance(val, str) and len(val) <= 4096 and self.token not in val
                 and not any(ord(c) < 32 or ord(c) == 127 for c in val), "lfs_headers_refused")
        with self.opener.open(Request(href, headers={**headers, "Accept-Encoding": "identity"}), timeout=60) as response:
            with path.open("xb") as destination:
                stream_verified(response, row, destination)
                destination.flush()
                os.fsync(destination.fileno())

    def verify_uploaded(self, asset, row):
        path = "/releases/assets/" + str(asset["id"])
        request = Request(API + path, headers={"Authorization": "Bearer " + self.token,
            "Accept": "application/octet-stream", "Accept-Encoding": "identity",
            "X-GitHub-Api-Version": "2022-11-28"})
        try:
            response = self.opener.open(request, timeout=60)
        except HTTPError as error:
            need(error.code in (301, 302, 303, 307, 308), "asset_api_download_refused")
            location = approved_url(error.headers.get("Location"), ASSET_HOSTS)
            need(self.token not in location, "credential_forwarding_refused")
            # No repository token or action headers cross this origin boundary.
            response = self.opener.open(Request(location, headers={"Accept-Encoding": "identity"}), timeout=60)
        with response:
            stream_verified(response, row)

    def upload(self, path):
        env = {key: value for key, value in os.environ.items()
               if key not in {"GH_DEBUG", "GIT_CURL_VERBOSE", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN"}
               and not key.startswith("GIT_TRACE")}
        config = self.directory / "gh-config"
        config.mkdir(exist_ok=True)
        env.update(GH_TOKEN=self.token, GH_HOST="github.com", GH_PROMPT_DISABLED="1", GH_CONFIG_DIR=str(config))
        try:
            result = subprocess.run(["gh", "release", "upload", TAG, str(path), "--repo", REPOSITORY],
                                    env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1200)
        except subprocess.TimeoutExpired:
            raise Refused("asset_upload_timeout") from None
        need(result.returncode == 0, "asset_upload_failed")

    def publish(self):
        self.api("/releases/" + str(RELEASE_ID), method="PATCH", body={"draft": False})


def inventory(rows, expected, prior=None):
    need(isinstance(rows, list) and len(rows) <= 7, "release_asset_inventory_differs")
    actual = {}
    for asset in rows:
        need(isinstance(asset, dict), "release_asset_inventory_differs")
        name = asset.get("name")
        need(isinstance(name, str) and name in expected and name not in actual, "unknown_or_duplicate_asset")
        pin = expected[name]
        need(type(asset.get("id")) is int and asset["id"] > 0 and asset.get("state") == "uploaded"
             and type(asset.get("size")) is int and asset["size"] == pin["bytes"]
             and asset.get("digest") in (None, "sha256:" + pin["sha256"]), "existing_asset_differs")
        actual[name] = asset
    need(len({a["id"] for a in actual.values()}) == len(actual), "duplicate_asset_id")
    if prior is not None:
        need(all(name in actual and actual[name]["id"] == asset["id"] for name, asset in prior.items()),
             "concurrent_asset_replacement")
    return actual


def file_identity(path):
    info = path.lstat()
    need(stat.S_ISREG(info.st_mode), "upload_file_not_regular")
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def verify_file(path, row):
    before = file_identity(path)
    need(before[2] == row["bytes"], "local_file_size_differs")
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(CHUNK):
            sha.update(block)
    need(sha.hexdigest() == row["sha256"] and file_identity(path) == before, "local_file_hash_or_identity_differs")
    return before


def stage(github, expected, metadata, directory, *, publish=False):
    actual = inventory(github.release(), expected)
    verified = {}
    # Binaries first, then proof, then checksum; uploads never overwrite an existing asset.
    names = sorted(SOURCES) + ["RELEASE-VERIFICATION.json", "SHA256SUMS"]
    for name in names:
        actual = inventory(github.release(), expected, actual)
        row = expected[name]
        if name not in actual:
            path = directory / name
            if name in metadata:
                with path.open("xb") as stream:
                    stream.write(metadata[name])
            else:
                github.lfs_download(row, path)
            before = verify_file(path, row)
            # Guard again after a potentially long LFS transfer.
            actual = inventory(github.release(), expected, actual)
            need(name not in actual, "concurrent_asset_addition")
            github.upload(path)
            need(file_identity(path) == before, "upload_file_changed")
            path.unlink()
            actual = inventory(github.release(), expected, actual)
            need(name in actual, "uploaded_asset_missing")
        github.verify_uploaded(actual[name], row)
        verified[name] = actual[name]["id"]
        print(json.dumps({"verified_asset": name, "bytes": row["bytes"], "sha256": row["sha256"]}), flush=True)
    actual = inventory(github.release(), expected, actual)
    need(set(actual) == set(expected) and all(actual[name]["id"] == verified[name] for name in expected),
         "complete_verified_asset_set_required")
    if publish:
        # Freshly download every asset again after the complete inventory is frozen.
        for name in sorted(expected):
            github.verify_uploaded(actual[name], expected[name])
        current = inventory(github.release(), expected, actual)
        need(set(current) == set(expected), "complete_verified_asset_set_required")
        github.publish()
        after = inventory(github.release(published=True), expected, current)
        need(set(after) == set(expected), "published_asset_inventory_differs")
    return {"schema": 1, "repository": REPOSITORY, "tag": TAG, "release_id": RELEASE_ID,
            "target_commit": TARGET, "published": publish,
            "uploader_source_commit": os.environ.get("GITHUB_SHA"),
            "assets": [{"name": name, "id": verified[name], "bytes": expected[name]["bytes"],
                        "sha256": expected[name]["sha256"]} for name in sorted(expected)],
            "full_uploaded_download_verified": True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publish", action="store_true", help="Publish the fixed draft only after all seven assets verify")
    args = parser.parse_args(argv)
    os.umask(0o077)
    report = None
    try:
        expected, metadata = load_delivery()
        need(os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("GITHUB_REPOSITORY") == REPOSITORY
             and os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch", "fixed_actions_runner_required")
        token = os.environ.get("GH_TOKEN", "")
        need(bool(token) and "\n" not in token and "\r" not in token, "runner_token_required")
        temporary = Path(os.environ.get("RUNNER_TEMP", ""))
        need(temporary.is_absolute() and temporary.is_dir(), "runner_temp_required")
        report = temporary / "idoly-prebuilt-publication-report.json"
        need(not report.exists(), "publication_report_already_exists")
        with tempfile.TemporaryDirectory(prefix="idoly-v0319-", dir=temporary) as task:
            directory = Path(task)
            result = stage(GitHub(token, directory), expected, metadata, directory, publish=args.publish)
        report.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps({"status": "PASS", "published": args.publish, "asset_count": 7}), flush=True)
    except Exception as error:
        # Never print arbitrary exception strings: urllib/gh errors can contain signed URLs.
        code = str(error) if isinstance(error, Refused) else "publication_io_failure"
        if report is not None and not report.exists():
            report.write_text(json.dumps({"schema": 1, "status": "STOPPED", "code": code,
                                          "release_id": RELEASE_ID}) + "\n")
        raise SystemExit("Publication stopped: " + code) from None


if __name__ == "__main__":
    main()
