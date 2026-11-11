"""Real runtime listener integration for SDK resources, persistence and Stop."""
from __future__ import annotations

from contextlib import closing
from http.client import HTTPConnection
import io
import json
import socket
import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import urlsplit

from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
import pytest

from idoly_local import app_runtime, assets
from idoly_local.octo_manifest import Database
from idoly_local.profiles import new_profile
from idoly_local.state import State
from test_app_runtime import _Application, _write_bundle
from test_octo_runtime import HEADERS, KEY, PAYLOAD, write_archive


@pytest.fixture
def runtime_data(tmp_path, monkeypatch):
    # Account bootstrap is a separate boundary. These tests exercise the real
    # runtime/listeners/gateway against an already-existing synthetic snapshot.
    schema = _write_bundle(tmp_path)
    state = State(tmp_path / 'state.db')
    new_profile(state, schema, 'sandbox', 'Preserved manager')
    monkeypatch.setitem(sys.modules, 'idoly_local.application', SimpleNamespace(Application=_Application))
    def not_seeded(*args):
        raise AssertionError('Existing account must not be seeded')
    monkeypatch.setitem(sys.modules, 'idoly_local.gameplay', SimpleNamespace(
        seed_starter_profile=not_seeded, repair_starter_roster=lambda *args: False,
        repair_starter_home_positions=lambda *args: False, repair_starter_inventory=lambda *args: False,
        repair_starter_card_level_mission=lambda *args: False))
    started = []
    def start(**kwargs):
        runtime = app_runtime.start(tmp_path, grpc_port=0, asset_port=0, **kwargs)
        started.append(runtime)
        return runtime
    yield tmp_path, start
    for runtime in started:
        runtime.stop()


def request(base, target, headers=None):
    parsed = urlsplit(base)
    with closing(HTTPConnection(parsed.hostname, parsed.port, timeout=3)) as connection:
        connection.request('GET', target, headers=headers or {})
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()


def eventually(predicate):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.01)
    raise AssertionError('Asynchronous transfer observation did not arrive')


class ResourceResponse(io.BytesIO):
    status = 200
    def __init__(self, url):
        super().__init__(PAYLOAD)
        self.url = url
        self.headers = {'Content-Length': str(len(PAYLOAD))}
    def geturl(self):
        return self.url


def test_bound_port_is_used_by_encrypted_manifest_and_verified_object_http(runtime_data):
    root, start = runtime_data
    _, original = write_archive(root / 'public-octo')
    before_database = (root / 'state.db').read_bytes()
    fetched = []
    def fetch(url, *, timeout):
        fetched.append(url)
        return ResourceResponse(url)
    runtime = start(resource_fetcher=fetch)
    origin = runtime.status()['asset_url']
    assert urlsplit(origin).port > 0
    code, headers, encrypted = request(origin, '/v2/pub/a/212/v/205051/list/0', HEADERS)
    assert code == 200 and headers['Content-Type'] == 'application/x-protobuf'
    # Decode independently from the server's Octo decryption helper.
    plain = unpad(AES.new(KEY, AES.MODE_CBC, encrypted[:16]).decrypt(encrypted[16:]), 16)
    decoded = Database.FromString(plain)
    expected = Database.FromString(original)
    expected.urlFormat = origin + '/octo/{v}/{type}/{o}/{g}'
    assert decoded == expected
    record = decoded.assetBundleList[0]
    target = urlsplit(decoded.urlFormat.format(v=record.uploadVersionId, type='assetbundle',
        o=record.objectName, g=record.generation)).path
    for _ in range(2):
        code, headers, body = request(origin, target)
        assert code == 200 and body == PAYLOAD
        assert headers['ETag'] == '"' + record.md5 + '"'
    assert len(fetched) == 1  # Second HTTP response comes from the verified file.
    status = eventually(lambda: (s if (s := runtime.status()['resource_transfer'])['session_served_bytes']
                                  == 2 * len(PAYLOAD) else None))
    assert status['available'] and status['allow_downloads']
    assert status['session_received_bytes'] == len(PAYLOAD)
    assert status['session_verified_files'] == 1
    assert status['session_manifest_bytes'] == len(encrypted)
    assert status['active_requests'] == 0
    assert runtime.status()['asset_transfer']['session_bytes_sent'] == 0
    assert (root / 'state.db').read_bytes() == before_database


def test_legacy_bundle_remains_available_without_resource_catalog_or_fetch(runtime_data):
    root, start = runtime_data
    fetch = Mock(side_effect=AssertionError('Legacy data must not fetch resources'))
    runtime = start(resource_fetcher=fetch, download_missing_resources=False)
    assert runtime.status()['resource_transfer']['available'] is False
    assert runtime.status()['resource_transfer']['allow_downloads'] is False
    assert request(runtime.status()['asset_url'], '/master/tiny.pack')[2] == b'archived-pack'
    assert request(runtime.status()['asset_url'], '/octo/202050/resources/unknown/1')[0] == 404
    fetch.assert_not_called()
    assert not (root / 'octo-cache').exists()


def test_resource_download_setting_keeps_catalog_but_does_not_fetch_missing_object(runtime_data):
    root, start = runtime_data
    write_archive(root / 'public-octo')
    fetch = Mock(side_effect=AssertionError('Disabled resource downloads must not reach upstream'))
    runtime = start(resource_fetcher=fetch, download_missing_resources=False)
    assert runtime.status()['resource_transfer']['available'] is True
    assert runtime.status()['resource_transfer']['allow_downloads'] is False
    code, _, manifest = request(runtime.status()['asset_url'], '/v2/pub/a/212/v/205051/list/0', HEADERS)
    assert code == 200 and manifest
    code, _, body = request(runtime.status()['asset_url'],
        '/octo/202050/assetbundle/object_assetbundle/12345')
    assert code == 503 and json.loads(body)['error'] == 'octo_cache_miss'
    fetch.assert_not_called()
    assert runtime.status()['resource_transfer']['session_received_bytes'] == 0
    assert not list((root / 'octo-cache').rglob('*.bin'))


def test_invalid_resource_archive_releases_bound_listener_and_preserves_existing_database(runtime_data, monkeypatch):
    root, _ = runtime_data
    write_archive(root / 'public-octo')
    (root / 'public-octo/manifest.pb').write_bytes(b'wrong original manifest')
    before_database = (root / 'state.db').read_bytes()
    bound = []
    original_create = assets.create_asset_server
    def capture(*args, **kwargs):
        server = original_create(*args, **kwargs)
        bound.append((server, server.server_address[1]))
        return server
    monkeypatch.setattr(assets, 'create_asset_server', capture)
    with pytest.raises(ValueError):
        app_runtime.start(root, grpc_port=0, asset_port=0)
    assert len(bound) == 1 and bound[0][0].socket.fileno() == -1
    with socket.socket() as reusable:
        reusable.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        reusable.bind(('127.0.0.1', bound[0][1]))
    assert (root / 'state.db').read_bytes() == before_database
    assert not (root / 'octo-cache').exists()


def test_stop_cancels_active_upstream_and_never_publishes_partial_object(runtime_data):
    root, start = runtime_data
    write_archive(root / 'public-octo')
    entered, closed = threading.Event(), threading.Event()
    class BlockedResponse(ResourceResponse):
        def read(self, count):
            entered.set()
            assert closed.wait(3), 'Stop did not close active transport'
            # A transport may return a late chunk after cancellation. The
            # cache still must not store or publish that chunk.
            return PAYLOAD
        def close(self):
            closed.set()
            super().close()
    runtime = start(resource_fetcher=lambda url, **kwargs: BlockedResponse(url))
    gateway = runtime._asset.octo_gateway
    close_gateway = Mock(wraps=gateway.close)
    gateway.close = close_gateway
    result = []
    def fetch_local():
        try:
            result.append(request(runtime.status()['asset_url'],
                '/octo/202050/assetbundle/object_assetbundle/12345'))
        except OSError as error:
            result.append(type(error).__name__)
    client = threading.Thread(target=fetch_local, daemon=True)
    client.start()
    try:
        assert entered.wait(2), 'HTTP request did not reach upstream'
        runtime.stop()
        runtime.stop()
    finally:
        closed.set()
        client.join(timeout=3)
    assert not client.is_alive()
    close_gateway.assert_called_once_with()
    assert closed.is_set() and runtime.status()['running'] is False
    assert result and (isinstance(result[0], str) or result[0][0] != 200)
    assert not list((root / 'octo-cache').rglob('*.bin'))
    assert not list((root / 'octo-cache').rglob('*.part'))
    status = runtime.status()['resource_transfer']
    assert status['session_verified_files'] == 0 and status['session_served_bytes'] == 0
