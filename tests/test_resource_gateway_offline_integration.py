"""Predownloaded server files must reach a fresh game's SDK over loopback offline."""
from __future__ import annotations

from contextlib import closing
import hashlib
from http.client import HTTPConnection
import io
import json
import time
from urllib.parse import urlsplit

from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
import pytest

from idoly_local.octo_manifest import Database
from idoly_local.resource_library import ResourceLibrary
from idoly_local.resource_translation_build import build_resource_overlay
from test_octo_app_runtime import runtime_data  # noqa: F401 - imported pytest fixture
from test_resource_translation_runtime import KEY, SOURCE, aes, database


def _request(origin, method, path, headers=None):
    address = urlsplit(origin)
    assert address.scheme == "http" and address.hostname == "127.0.0.1"
    with closing(HTTPConnection(address.hostname, address.port, timeout=3)) as connection:
        connection.request(method, path, headers=headers or {})
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()


def _prepare(root, platform, public):
    ios = platform == "ios"
    revision, version = (1159, 105051) if ios else (1087, 205051)
    original = database(); original.revision = revision
    bodies = {"assetbundle": b"offline stage 0123456789", "resources": b"[title title=original story]"}
    for kind, rows in (("assetbundle", original.assetBundleList), ("resources", original.resourceList)):
        for row in rows:
            row.uploadVersionId = 101050 if ios else 202050
            row.size = len(bodies[kind]); row.md5 = hashlib.md5(bodies[kind]).hexdigest()
    raw = original.SerializeToString()
    archive = root / ("public-octo-ios" if ios else "public-octo"); archive.mkdir()
    settings = {"schema": 1, "application_id": 212, "application_version": version,
        "revision": revision, "manifest_sha256": hashlib.sha256(raw).hexdigest(),
        "aes_key_hex": KEY.hex(), "client_key": "synthetic"}
    settings_raw = json.dumps(settings).encode()
    (archive / "manifest.pb").write_bytes(raw); (archive / "settings.json").write_bytes(settings_raw)
    calls = []
    class Response(io.BytesIO):
        status = 200
        def __init__(self, body):
            super().__init__(body); self.headers = {"Content-Length": str(len(body))}
    def fetch(url, *, timeout):
        calls.append(url)
        return Response(bodies["assetbundle" if "-assetbundle/" in url else "resources"])
    library = ResourceLibrary.from_data_dir(root, aes_cbc=aes, resource_cache_dir=public, fetcher=fetch)
    try:
        library.start_download(platform, parallelism=1)
        deadline = time.monotonic() + 3
        while (job := library.status()["job"])["state"] not in {"completed", "partial", "failed", "cancelled"}:
            assert time.monotonic() < deadline
            time.sleep(.005)
        assert job["state"] == "completed" and job["downloaded_files"] == 2 and len(calls) == 2
        assert job["received_bytes"] == sum(map(len, bodies.values()))
    finally:
        library.close()
    return original, raw, settings_raw, archive, bodies, version


def _language(root, language):
    (root / "client-language.json").write_text(json.dumps({"schema": 1, "language": language}))
    if language != "ja":
        source = root / "original-master/master-tag.json"
        destination = source.parent / "languages" / language / source.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())


@pytest.mark.parametrize("platform", ["ios", "android"])
@pytest.mark.parametrize("language", ["ja", "ko", "en", "pinned-ja"])
def test_bulk_download_then_fresh_runtime_serves_sdk_manifest_head_range_and_objects_offline(
        runtime_data, platform, language):
    root, start = runtime_data
    public = root / "selected-resources"
    original, raw, settings, archive, bodies, version = _prepare(root, platform, public)
    before_account = (root / "state.db").read_bytes()
    translated = {"ko": "[title title=로컬 번역]".encode(), "en": b"[title title=local translation]"}
    for locale in ("ko", "en"):
        source = root / ("source-" + locale); source.mkdir()
        (source / "adv_bond_ai_01_01.txt").write_bytes(translated[locale])
        build_resource_overlay(raw, source, public / "translations" / locale / platform,
            language=locale, revision=original.revision + 1, source=SOURCE)
    offline_calls = []
    def forbidden(*args, **kwargs):
        offline_calls.append(args)
        raise AssertionError("Offline gameplay must never request a CDN resource")
    if language == "pinned-ja":
        _language(root, "ko")
        previous = start(resource_platform=platform, resource_cache_dir=public, aes_cbc=aes,
            resource_fetcher=forbidden, download_missing_resources=True)
        previous_revision = previous._asset.octo_gateway.manifest.revision
        previous.stop()
        selected_language = "ja"
    else:
        selected_language = language
    _language(root, selected_language)
    runtime = start(resource_platform=platform, resource_cache_dir=public, aes_cbc=aes,
        resource_fetcher=forbidden, download_missing_resources=True)
    try:
        origin = runtime.status()["asset_url"]
        code, headers, encrypted = _request(origin, "GET", f"/v2/pub/a/212/v/{version}/list/0",
            {"Accept": "application/x-protobuf,x-octo-app/212", "X-OCTO-KEY": "synthetic"})
        assert code == 200 and headers["Content-Type"] == "application/x-protobuf"
        plain = unpad(AES.new(KEY, AES.MODE_CBC, encrypted[:16]).decrypt(encrypted[16:]), 16)
        manifest = Database.FromString(plain)
        assert manifest.urlFormat == origin + "/octo/{v}/{type}/{o}/{g}"
        if language == "pinned-ja":
            assert manifest.revision > previous_revision > original.revision
        elif selected_language != "ja":
            assert manifest.revision > original.revision
        runtime._library.catalog_summary(platform)
        assert runtime._library._catalogs[platform].raw == raw
        assert runtime._library._catalogs[platform].manifest.revision == original.revision
        assert runtime._asset.octo_gateway.cache.root == public / (
            "octo-cache-ios" if platform == "ios" else "octo-cache")
        expected_served = 0
        for kind, rows in (("assetbundle", manifest.assetBundleList), ("resources", manifest.resourceList)):
            row = rows[0]
            expected = translated[selected_language] if kind == "resources" and selected_language != "ja" else bodies[kind]
            assert row.size == len(expected) and row.md5 == hashlib.md5(expected).hexdigest()
            target = urlsplit(manifest.urlFormat.format(v=row.uploadVersionId, type=kind,
                o=row.objectName, g=row.generation)).path
            status, response_headers, body = _request(origin, "HEAD", target)
            assert status == 200 and body == b"" and int(response_headers["Content-Length"]) == len(expected)
            assert response_headers["ETag"] == '"' + row.md5 + '"'
            status, response_headers, body = _request(origin, "GET", target, {"Range": "bytes=0-1"})
            assert status == 206 and body == expected[:2]
            assert response_headers["Content-Range"] == f"bytes 0-1/{len(expected)}"
            status, _, body = _request(origin, "GET", target)
            assert status == 200 and body == expected
            expected_served += len(expected) + 2
        deadline = time.monotonic() + 2
        while ((status := runtime.status()["resource_transfer"])["session_served_bytes"] != expected_served
               or status["session_manifest_bytes"] != len(encrypted)) and time.monotonic() < deadline:
            time.sleep(.005)
        assert status["session_served_bytes"] == expected_served
        assert status["session_manifest_bytes"] == len(encrypted)
        assert status["session_received_bytes"] == 0 and not offline_calls
        assert (archive / "manifest.pb").read_bytes() == raw
        assert (archive / "settings.json").read_bytes() == settings
        assert (root / "state.db").read_bytes() == before_account
    finally:
        runtime.stop()


@pytest.mark.parametrize("wrong_selection", ["other-root", "platform-subdirectory"])
def test_offline_game_reports_cache_miss_if_selected_folder_is_not_the_download_root(runtime_data, wrong_selection):
    root, start = runtime_data
    public = root / "downloaded-resources"
    _, _, _, _, _, version = _prepare(root, "ios", public)
    selected = root / "empty-resources" if wrong_selection == "other-root" else public / "octo-cache-ios"
    calls = []
    def forbidden(*args, **kwargs):
        calls.append(args); raise AssertionError("Offline cache miss must not contact the CDN")
    runtime = start(resource_platform="ios", resource_cache_dir=selected, aes_cbc=aes,
        resource_fetcher=forbidden, download_missing_resources=False)
    try:
        origin = runtime.status()["asset_url"]
        code, _, encrypted = _request(origin, "GET", f"/v2/pub/a/212/v/{version}/list/0",
            {"Accept": "application/x-protobuf,x-octo-app/212", "X-OCTO-KEY": "synthetic"})
        assert code == 200
        plain = unpad(AES.new(KEY, AES.MODE_CBC, encrypted[:16]).decrypt(encrypted[16:]), 16)
        manifest = Database.FromString(plain); row = manifest.assetBundleList[0]
        target = urlsplit(manifest.urlFormat.format(v=row.uploadVersionId, type="assetbundle",
            o=row.objectName, g=row.generation)).path
        status, _, body = _request(origin, "GET", target)
        assert status == 503 and json.loads(body)["error"] == "octo_cache_miss"
        assert not calls and runtime.status()["resource_transfer"]["session_received_bytes"] == 0
        assert len(list((public / "octo-cache-ios").rglob("*.bin"))) == 2
    finally:
        runtime.stop()
