"""Real HTTP checks for the optional original-format Octo gateway."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import hashlib
import http.client
import io
import json
from pathlib import Path
import threading
import time
import urllib.error
import urllib.request

from Crypto.Cipher import AES
import pytest

from idoly_local.assets import create_asset_server
from idoly_local.octo_cache import OctoCache
from idoly_local.octo_http import OctoGateway
from idoly_local.octo_manifest import Database, OctoManifest, decrypt_manifest


APP_KEY = "synthetic-octo-http-key"
AES_KEY = bytes(range(32))
ORIGINAL_URL = "https://d2ilil7yh5oi1v.cloudfront.net/solis-{v}-{type}/{o}?generation={g}&alt=media"
LIST = "/v2/pub/a/212/v/205051/list/"
HEADERS = {"Accept": "application/x-protobuf,x-octo-app/212", "X-OCTO-KEY": APP_KEY}


def aes(encrypt, key, iv, data):
    cipher = AES.new(key, AES.MODE_CBC, iv)
    return cipher.encrypt(data) if encrypt else cipher.decrypt(data)


class Upstream(io.BytesIO):
    def __init__(self, body, url, *, advertised=None):
        super().__init__(body)
        self.status = 200
        self.headers = {"Content-Length": str(len(body) if advertised is None else advertised)}
        self.url = url

    def geturl(self):
        return self.url


class Diagnostics:
    def status(self):
        return {"summary": "fixture-status"}

    def receive(self, raw):
        return {"accepted": bool(json.loads(raw))}


class ObservedEvents(list):
    """Client reads can finish before the serving thread records its observer."""
    def __init__(self):
        super().__init__()
        self.changed = threading.Condition()

    def append(self, event):
        with self.changed:
            super().append(event)
            self.changed.notify_all()

    def wait_completed(self, count):
        with self.changed:
            assert self.changed.wait_for(
                lambda: sum(event["phase"] == "completed" for event in self) >= count, timeout=3)


@pytest.fixture
def gateway(tmp_path):
    original = Database(revision=1087, urlFormat=ORIGINAL_URL, tagname=["first-download"])
    content = {"assetbundle": b"0123456789", "resources": b"sound00"}
    for identity, (kind, target) in enumerate((("assetbundle", original.assetBundleList),
                                              ("resources", original.resourceList)), 1):
        raw = content[kind]
        target.add(id=identity, name="fixture-" + kind, size=len(raw), crc=123,
                   objectName="object_" + kind, generation=1234567890, uploadVersionId=202050,
                   md5=hashlib.md5(raw).hexdigest(), state=1)
    manifest = OctoManifest(original.SerializeToString(), aes_key=AES_KEY, client_key=APP_KEY,
                            base_url="http://127.0.0.1:8080", aes_cbc=aes)
    urls = {record.upstream_url: content[record.kind] for record in manifest.objects.values()}
    objects = {record.kind: record for record in manifest.objects.values()}
    state = {"calls": [], "delay": 0, "replace": None, "advertised": None}
    lock = threading.Lock()

    def fetcher(url, *, timeout):
        assert timeout > 0
        with lock:
            state["calls"].append(url)
        if state["delay"]:
            time.sleep(state["delay"])
        raw = urls[url] if state["replace"] is None else state["replace"]
        return Upstream(raw, url, advertised=state["advertised"])

    upstream_events, local_events, master_events = [], ObservedEvents(), []
    cache = OctoCache(tmp_path / "cache", fetcher=fetcher, on_event=upstream_events.append)
    api = OctoGateway(manifest, cache, transfer_callback=local_events.append)
    public = tmp_path / "public"
    (public / "master").mkdir(parents=True)
    (public / "master" / "table.db").write_bytes(b"master-fixture")
    server = create_asset_server("127.0.0.1", 0, public, diagnostics=Diagnostics(),
                                 transfer_callback=master_events.append, octo=api)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    class Fixture:
        base = f"http://127.0.0.1:{server.server_port}"

        def request(self, path, *, method="GET", headers=None, body=None):
            return urllib.request.urlopen(urllib.request.Request(
                self.base + path, method=method, headers=headers or {}, data=body), timeout=5)

        def path(self, kind="assetbundle"):
            record = objects[kind]
            return f"/octo/{record.upload_version}/{record.kind}/{record.object_name}/{record.generation}"

    fixture = Fixture()
    fixture.manifest, fixture.original = manifest, original
    fixture.objects, fixture.content, fixture.state = objects, content, state
    fixture.api, fixture.cache, fixture.root = api, cache, tmp_path
    fixture.upstream_events, fixture.local_events, fixture.master_events = upstream_events, local_events, master_events
    fixture.server = server
    try:
        yield fixture
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def response_error(gateway, path, status, **kwargs):
    with pytest.raises(urllib.error.HTTPError) as raised:
        gateway.request(path, **kwargs)
    assert raised.value.code == status
    return raised.value


def test_full_and_same_revision_manifest_keep_original_object_metadata(gateway):
    with gateway.request(LIST + "0", headers=HEADERS) as response:
        assert response.status == 200
        assert response.headers["Content-Type"] == "application/x-protobuf"
        wire = response.read()
        assert int(response.headers["Content-Length"]) == len(wire)
    full = Database.FromString(decrypt_manifest(wire, aes_key=AES_KEY, aes_cbc=aes))
    assert full.urlFormat == "http://127.0.0.1:8080/octo/{v}/{type}/{o}/{g}"
    assert full.assetBundleList == gateway.original.assetBundleList
    assert full.resourceList == gateway.original.resourceList
    with gateway.request(LIST + "1087", headers=HEADERS) as response:
        warm = Database.FromString(decrypt_manifest(response.read(), aes_key=AES_KEY, aes_cbc=aes))
    assert warm.revision == 1087 and warm.urlFormat == full.urlFormat
    assert not warm.assetBundleList and not warm.resourceList
    assert not gateway.state["calls"] and not gateway.master_events
    assert all(event["kind"] == "manifest" and event["source"] == "octo" for event in gateway.local_events)


def test_manifest_head_has_actual_cipher_length_and_no_response_transfer(gateway):
    with gateway.request(LIST + "0", method="HEAD", headers=HEADERS) as response:
        assert response.read() == b""
        length = int(response.headers["Content-Length"])
        assert length >= 32 and (length - 16) % 16 == 0
    assert not gateway.local_events and not gateway.state["calls"]


@pytest.mark.parametrize("path,headers,status", [
    (LIST + "0", {}, 403),
    (LIST + "0", {**HEADERS, "X-OCTO-KEY": "wrong-fixture-key"}, 403),
    (LIST + "0", {**HEADERS, "Accept": "application/x-protobuf"}, 403),
    (LIST + "1", HEADERS, 409),
    (LIST + "1088", HEADERS, 409),
    (LIST + "00", HEADERS, 404),
    (LIST.replace("212", "999") + "0", HEADERS, 404),
    (LIST + "0?private-query", HEADERS, 404),
])
def test_manifest_rejects_unsupported_requests_without_cache_work(gateway, path, headers, status):
    error = response_error(gateway, path, status, headers=headers)
    assert APP_KEY.encode() not in error.read()
    assert not gateway.state["calls"] and not gateway.master_events


def test_duplicate_application_key_is_rejected(gateway):
    connection = http.client.HTTPConnection("127.0.0.1", gateway.server.server_port, timeout=5)
    try:
        connection.putrequest("GET", LIST + "0")
        connection.putheader("Accept", HEADERS["Accept"])
        connection.putheader("X-OCTO-KEY", APP_KEY)
        connection.putheader("X-OCTO-KEY", "other")
        connection.endheaders()
        response = connection.getresponse()
        assert response.status == 403
        response.read()
    finally:
        connection.close()
    assert not gateway.state["calls"]


def test_object_get_head_ranges_and_progress_are_separate_from_master(gateway):
    path = gateway.path()
    with gateway.request(path, method="HEAD") as response:
        assert response.status == 200 and response.read() == b""
        assert response.headers["Content-Length"] == "10"
    assert gateway.state["calls"] == [gateway.objects["assetbundle"].upstream_url]
    assert not gateway.local_events and not gateway.master_events
    with gateway.request(path) as response:
        assert response.read() == gateway.content["assetbundle"]
        assert response.headers["ETag"] == '"' + gateway.objects["assetbundle"].md5 + '"'
    for header, expected, content_range in [("bytes=2-4", b"234", "bytes 2-4/10"),
                                            ("bytes=8-", b"89", "bytes 8-9/10"),
                                            ("bytes=-3", b"789", "bytes 7-9/10")]:
        with gateway.request(path, headers={"Range": header}) as response:
            assert response.status == 206 and response.read() == expected
            assert response.headers["Content-Range"] == content_range
    assert len(gateway.state["calls"]) == 1 and not gateway.master_events
    gateway.local_events.wait_completed(4)
    complete = [event for event in gateway.local_events if event["phase"] == "completed"]
    assert sorted(event["sent_bytes"] for event in complete) == [2, 3, 3, 10]
    assert all(event["object_bytes"] == 10 and event["source"] == "octo" for event in complete)
    assert gateway.upstream_events  # Cache verification is observed independently.


@pytest.mark.parametrize("value", ["bytes=10-20", "bytes=4-2", "bytes=-0", "bytes=0-1,4-5", "other=0-1"])
def test_impossible_range_is_rejected_before_fetch(gateway, value):
    error = response_error(gateway, gateway.path(), 416, headers={"Range": value})
    assert error.headers["Content-Range"] == "bytes */10"
    assert not gateway.state["calls"]


@pytest.mark.parametrize("suffix", ["?origin=https://other.invalid/", "/../private", "/extra"])
def test_unknown_or_noncanonical_object_cannot_fetch_or_fall_through(gateway, suffix):
    response_error(gateway, gateway.path() + suffix, 404)
    response_error(gateway, gateway.path().replace("/octo/", "/%6fcto/"), 404)
    response_error(gateway, "/octo/http://169.254.169.254/latest", 404)
    assert not gateway.state["calls"]


@pytest.mark.parametrize("bad", [b"wrongbytes", b"short"])
def test_invalid_upstream_bytes_never_become_successful_object_response(gateway, bad):
    gateway.state["replace"] = bad
    gateway.state["advertised"] = 10
    error = response_error(gateway, gateway.path(), 502)
    assert json.loads(error.read()) == {"error": "octo_resource_unavailable"}
    assert not gateway.master_events
    assert len(gateway.local_events) == 1
    assert gateway.local_events[0]["phase"] == "failed"
    assert gateway.local_events[0]["sent_bytes"] == 0
    assert gateway.local_events[0]["http_status"] == 502


def test_cache_only_mode_miss_is_503_without_fetch(gateway):
    gateway.api.cache = OctoCache(gateway.root / "offline-cache", allow_download=False)
    response_error(gateway, gateway.path(), 503)
    assert not gateway.state["calls"]
    assert len(gateway.local_events) == 1
    assert gateway.local_events[0]["phase"] == "failed" and gateway.local_events[0]["sent_bytes"] == 0
    assert gateway.local_events[0]["http_status"] == 503


def test_simultaneous_http_misses_share_verified_download(gateway):
    gateway.state["delay"] = 0.15
    barrier = threading.Barrier(4)

    def request(index):
        barrier.wait(timeout=3)
        with gateway.request(gateway.path(), headers={"Range": f"bytes={index}-{index}"}) as response:
            assert response.status == 206
            return response.read()

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(request, range(4))) == [b"0", b"1", b"2", b"3"]
    assert len(gateway.state["calls"]) == 1
    gateway.local_events.wait_completed(4)
    assert len([event for event in gateway.local_events if event["phase"] == "completed"]) == 4


def test_observer_failure_does_not_break_valid_download(gateway):
    def failing(_event):
        raise RuntimeError("synthetic observer failure")
    gateway.api.transfer_callback = failing
    with gateway.request(gateway.path("resources")) as response:
        assert response.read() == gateway.content["resources"]


def test_master_and_diagnostic_routes_keep_existing_behavior(gateway):
    with gateway.request("/master/table.db") as response:
        assert response.read() == b"master-fixture"
    with gateway.request("/diagnostics/status") as response:
        assert json.load(response) == {"summary": "fixture-status"}
    with gateway.request("/diagnostics/client", method="POST", headers={"Content-Type": "application/json"},
                         body=b'{"fixture":true}') as response:
        assert json.load(response) == {"accepted": True}
    assert gateway.master_events and all(event["path"] == "/master/table.db" for event in gateway.master_events)
    assert not gateway.state["calls"] and not gateway.local_events


def test_manifest_crypto_failure_is_fixed_error_without_key_disclosure(gateway):
    def failed(*_args):
        raise RuntimeError(APP_KEY)
    gateway.manifest._aes = failed
    error = response_error(gateway, LIST + "0", 502, headers=HEADERS)
    assert json.loads(error.read()) == {"error": "octo_manifest_unavailable"}
    assert not gateway.state["calls"]


def test_gateway_can_be_attached_after_port_zero_bind_before_serving(gateway, tmp_path):
    public = tmp_path / "late-public"
    public.mkdir()
    server = create_asset_server("127.0.0.1", 0, public)
    assert server.octo_gateway is None
    origin = f"http://127.0.0.1:{server.server_port}"
    manifest = OctoManifest(gateway.original.SerializeToString(), aes_key=AES_KEY,
                            client_key=APP_KEY, base_url=origin, aes_cbc=aes)
    server.octo_gateway = OctoGateway(manifest, gateway.cache)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(urllib.request.Request(origin + LIST + "0", headers=HEADERS), timeout=5) as response:
            decoded = Database.FromString(decrypt_manifest(response.read(), aes_key=AES_KEY, aes_cbc=aes))
        assert decoded.urlFormat == origin + "/octo/{v}/{type}/{o}/{g}"
        record = next(iter(manifest.objects.values()))
        url = decoded.urlFormat.format(v=record.upload_version, type=record.kind,
                                       o=record.object_name, g=record.generation)
        with urllib.request.urlopen(url, timeout=5) as response:
            assert response.read() == gateway.content[record.kind]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_stream_close_error_cannot_append_an_error_to_committed_response(gateway):
    cache = gateway.cache

    class CloseFailure:
        @contextmanager
        def open_verified(self, record):
            with cache.open_verified(record) as stream:
                yield stream
            raise OSError("synthetic read-only close failure")

    gateway.api.cache = CloseFailure()
    with gateway.request(gateway.path()) as response:
        assert response.status == 200 and response.read() == gateway.content["assetbundle"]
    gateway.local_events.wait_completed(1)
    assert [event["phase"] for event in gateway.local_events] == ["started", "completed"]


def test_gateway_close_is_idempotent_and_stops_new_manifest_or_object_work(gateway):
    gateway.api.close()
    gateway.api.close()
    response_error(gateway, LIST + "0", 503, headers=HEADERS)
    response_error(gateway, gateway.path(), 503)
    assert not gateway.state["calls"] and not gateway.local_events
    # Shutdown of the optional gateway does not own the existing master route.
    with gateway.request("/master/table.db") as response:
        assert response.read() == b"master-fixture"
