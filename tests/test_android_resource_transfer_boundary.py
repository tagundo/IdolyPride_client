"""Host FD/lifecycle checks only; no Android provider, server or network runs."""
import importlib.util
import io
import json
import os
from pathlib import Path
import threading
import hashlib
import sys
from types import SimpleNamespace
from zipfile import ZipFile

import pytest


@pytest.fixture
def boundary():
    path = Path(__file__).resolve().parents[1] / "android-server/app/src/main/python/android_server_runtime.py"
    spec = importlib.util.spec_from_file_location("android_resource_boundary", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def resource_response(boundary, monkeypatch):
    """The real adapter with a controlled platform stream/Java method seam.

    The actual Java method's short-read and cancellation behavior is exercised
    by ResourceTransfersHostTest; this seam checks the Chaquopy call contract.
    """
    connections, chunks = [], []

    class Connection:
        def __init__(self, url, stream, headers):
            self.url, self.stream, self.response_headers = url, stream, headers
            self.properties, self.disconnections, self.stream_opens = {}, 0, 0
        def setInstanceFollowRedirects(self, value):
            self.redirects = value
        def setConnectTimeout(self, value):
            self.connect_timeout = value
        def setReadTimeout(self, value):
            self.read_timeout = value
        def setRequestProperty(self, key, value):
            self.properties[key] = value
        def getResponseCode(self):
            return 200
        def getHeaderField(self, key):
            return self.response_headers.get(key)
        def getURL(self):
            return SimpleNamespace(toString=lambda: self.url)
        def getInputStream(self):
            self.stream_opens += 1
            return self.stream
        def disconnect(self):
            self.disconnections += 1

    def create(body=b"bounded resource bytes", *, headers=None, reader=None, stream=None, url=None):
        selected_stream = io.BytesIO(body) if stream is None else stream
        selected_url = url or "https://d2ilil7yh5oi1v.cloudfront.net/test"
        connection = Connection(selected_url, selected_stream, {} if headers is None else headers)
        connections.append(connection)
        def read_chunk(source, buffer, limit):
            chunks.append((id(buffer), len(buffer), limit))
            if reader is not None:
                return reader(source, buffer, limit)
            block = source.read(limit)
            buffer[:len(block)] = block
            return len(block) if block else -1
        classes = {"java.net.URL": lambda url: SimpleNamespace(openConnection=lambda: connection),
                   "game.qualiarts.idolypride.localserver.ResourceTransfers":
                       SimpleNamespace(readResourceChunk=read_chunk)}
        monkeypatch.setitem(sys.modules, "java", SimpleNamespace(
            jclass=lambda name: classes[name], jarray=lambda kind: bytearray, jbyte=object()))
        return boundary._AndroidResourceResponse(selected_url, 30)
    create.connections, create.chunks = connections, chunks
    return create


def test_android_resource_reads_use_one_fixed_java_buffer_and_bounded_chunk_method(resource_response):
    body = bytes(range(256)) * 256 + b"tail!"
    with resource_response(body, headers={"Content-Length": str(len(body))}) as response:
        connection = resource_response.connections[-1]
        assert response.status == 200 and response.headers == {"Content-Length": str(len(body))}
        assert not connection.redirects
        assert connection.connect_timeout == connection.read_timeout == 30000
        assert connection.properties["Accept-Encoding"] == "identity"
        assert response.read(2**31 - 1) == body[:65536]
        assert response.read(5) == body[65536:]
        assert response.read(1) == b""
        assert connection.stream_opens == 1
    assert [value[2] for value in resource_response.chunks] == [65536, 5, 1]
    assert len({value[0] for value in resource_response.chunks}) == 1
    assert all(value[1] == 65536 for value in resource_response.chunks)
    assert connection.stream.closed and connection.disconnections == 1
    response.close()
    assert connection.disconnections == 1
    with pytest.raises(OSError):
        response.read(1)


@pytest.mark.parametrize("size", [None, -1, True, 1.5, "65536"])
def test_android_resource_reads_reject_unbounded_or_invalid_sizes_before_open(resource_response, size):
    with resource_response() as response:
        with pytest.raises(ValueError, match="bounded"):
            response.read(size)
        assert response.read(0) == b""
        assert resource_response.connections[-1].stream_opens == 0
        assert resource_response.chunks == []


@pytest.mark.parametrize("extra", [b"", b"!"])
def test_android_chunk_adapter_retains_complete_digest_and_one_byte_overlong_probe(resource_response, tmp_path, extra):
    from idoly_local.octo_cache import OctoCache, OctoCacheError
    from idoly_local.octo_manifest import OctoObject
    body = b"data"
    item = OctoObject("assetbundle", 202050, "bounded_chunk", 1234567, len(body),
                      hashlib.md5(body, usedforsecurity=False).hexdigest(), "bundle-name")
    cache = OctoCache(tmp_path, fetcher=lambda url, timeout: resource_response(body + extra, url=url))
    if extra:
        with pytest.raises(OctoCacheError) as error:
            with cache.open_verified(item):
                pytest.fail("Overlong platform bytes entered the cache")
        assert error.value.code == "upstream_size"
        assert not list(tmp_path.rglob("*.bin"))
        assert [value[2] for value in resource_response.chunks] == [len(body) + 1]
    else:
        with cache.open_verified(item) as source:
            assert source.read() == body
        assert [value[2] for value in resource_response.chunks] == [len(body) + 1, 1]
    assert not list(tmp_path.rglob("*.part"))
    assert resource_response.connections[-1].stream.closed
    cache.close()


def test_android_chunk_adapter_cancel_closes_blocked_stream_and_disconnects(resource_response):
    entered, closed = threading.Event(), threading.Event()
    failures = []
    class BlockingStream:
        def close(self):
            closed.set()
    def blocked_reader(stream, buffer, limit):
        entered.set()
        assert closed.wait(1), "Cancellation did not close the platform stream"
        raise OSError("closed")
    response = resource_response(stream=BlockingStream(), reader=blocked_reader)
    def read():
        try:
            response.read(65536)
        except BaseException as error:
            failures.append(error)
    worker = threading.Thread(target=read, daemon=True)
    worker.start()
    try:
        assert entered.wait(.5)
    finally:
        response.close()
    worker.join(timeout=1)
    assert not worker.is_alive() and len(failures) == 1 and isinstance(failures[0], OSError)
    assert closed.is_set() and resource_response.connections[-1].disconnections == 1


def test_seekable_fd_is_duplicated_closed_and_import_does_not_hold_lifecycle_lock(boundary, tmp_path):
    selected = tmp_path / "selected.zip"
    selected.write_bytes(b"selected archive bytes")
    lock_acquired = []

    class Library:
        def import_from(self, source, platform, kind):
            def probe():
                acquired = boundary._LOCK.acquire(timeout=.1)
                lock_acquired.append(acquired)
                if acquired:
                    boundary._LOCK.release()
            worker = threading.Thread(target=probe)
            worker.start(); worker.join(timeout=.2)
            assert platform == "ios" and kind == "all"
            assert source.seekable() and source.read() == b"selected archive bytes"
            self.copied = source.fileno()
            return {"state": "completed", "imported_files": 1}

    library = Library()
    boundary._RUNTIME = SimpleNamespace(_library=library)
    with selected.open("rb") as source:
        result = json.loads(boundary.import_resources_fd(source.fileno(), "ios"))
        assert result["state"] == "completed" and lock_acquired == [True]
        os.fstat(source.fileno())
        with pytest.raises(OSError):
            os.fstat(library.copied)
    assert selected.read_bytes() == b"selected archive bytes"


def test_unseekable_fd_fails_before_import_and_closes_only_duplicate(boundary, monkeypatch):
    class Library:
        def import_from(self, *args):
            pytest.fail("A pipe must not enter archive import")
    boundary._RUNTIME = SimpleNamespace(_library=Library())
    duplicates = []
    actual_dup = os.dup
    def duplicate(fd):
        result = actual_dup(fd)
        duplicates.append(result)
        return result
    monkeypatch.setattr(boundary.os, "dup", duplicate)
    read_fd, write_fd = os.pipe()
    try:
        with pytest.raises(OSError):
            boundary.import_resources_fd(read_fd, "android")
        os.fstat(read_fd)
        with pytest.raises(OSError):
            os.fstat(duplicates[0])
    finally:
        os.close(read_fd); os.close(write_fd)


def test_cancel_identifier_is_whitelisted_and_stopped_runtime_is_unavailable(boundary):
    calls = []
    class Library:
        def cancel(self, identifier):
            calls.append(identifier)
            return {"job_id": identifier, "state": "cancelling"}
    boundary._RUNTIME = SimpleNamespace(_library=Library())
    assert json.loads(boundary.cancel_resource_job("a" * 32))["state"] == "cancelling"
    for value in ("", "../other", "job;other", "x" * 65, None):
        with pytest.raises(ValueError):
            boundary.cancel_resource_job(value)
    assert calls == ["a" * 32]
    boundary._RUNTIME = None
    with pytest.raises(ValueError):
        boundary.cancel_resource_job("known-job")
    for descriptor, platform in ((True, "android"), (-1, "android"), (1, "other")):
        with pytest.raises(ValueError):
            boundary.import_resources_fd(descriptor, platform)


@pytest.mark.parametrize("platforms", [("public-octo",), ("public-octo", "public-octo-ios")])
def test_public_platform_catalog_install_and_marker_reopen_preserve_account(boundary, tmp_path, platforms):
    bundle = tmp_path / "bundle.zip"
    with ZipFile(bundle, "w") as archive:
        archive.writestr("data/protocol/idolypride-6.1.1.pb", b"public schema")
        archive.writestr("data/original-master/master-tag.json", b"public master")
        for platform in platforms:
            archive.writestr("data/" + platform + "/settings.json", b"public settings")
            archive.writestr("data/" + platform + "/manifest.pb", b"public manifest")
    files = tmp_path / "files"
    (files / "data").mkdir(parents=True)
    account = files / "data/state.db"
    account.write_bytes(b"preserve account")
    expected = hashlib.sha256(bundle.read_bytes()).hexdigest()
    for _ in range(2):
        root = boundary.install_bundle(bundle, files, expected)
        for platform in platforms:
            assert (root / platform / "manifest.pb").read_bytes() == b"public manifest"
    assert account.read_bytes() == b"preserve account"


def test_incomplete_secondary_catalog_fails_before_installing_any_files(boundary, tmp_path):
    bundle = tmp_path / "incomplete.zip"
    with ZipFile(bundle, "w") as archive:
        archive.writestr("data/protocol/idolypride-6.1.1.pb", b"public schema")
        archive.writestr("data/original-master/master-tag.json", b"public master")
        archive.writestr("data/public-octo-ios/settings.json", b"missing manifest")
    files = tmp_path / "files"
    with pytest.raises(ValueError, match="incomplete"):
        boundary.install_bundle(bundle, files, hashlib.sha256(bundle.read_bytes()).hexdigest())
    assert not files.exists()


@pytest.mark.parametrize("public", [False, True])
def test_start_passes_explicit_resource_root_without_moving_private_data(boundary, tmp_path, monkeypatch, public):
    import idoly_local.app_runtime as app_runtime
    root = str(tmp_path / "Downloads/IdolyPride") if public else None
    seen, copied, installed = [], [], []
    payload_sha256, payload_bytes = "b" * 64, 234567
    assets = object()
    fake = SimpleNamespace(status=lambda: {"running": True})
    def start(data, **options):
        seen.append((data, options))
        return fake
    monkeypatch.setattr(app_runtime, "start", start)
    def copy_asset(source, target, digest):
        copied.append((source, target, digest))
    def install_bundle(bundle, files, digest, size):
        installed.append((bundle, files, digest, size))
        return files / "data"
    monkeypatch.setattr(boundary, "_copy_asset", copy_asset)
    monkeypatch.setattr(boundary, "install_bundle", install_bundle)
    classes = {"game.qualiarts.idolypride.localserver.BuildConfig": SimpleNamespace(
                   SERVER_DATA_SHA256=payload_sha256, SERVER_DATA_BYTES=payload_bytes),
               "game.qualiarts.idolypride.localserver.CryptoBridge": SimpleNamespace(aesCbc=lambda *args: b"")}
    monkeypatch.setitem(sys.modules, "java", SimpleNamespace(jclass=lambda name: classes[name]))
    result = boundary.start(str(tmp_path), assets, SimpleNamespace(log=lambda message: None),
                            None, False, True, False, root)
    assert json.loads(result)["running"] is True
    bundle = tmp_path / "bundled-server-data.zip"
    assert copied == [(assets, bundle, payload_sha256)]
    assert installed == [(bundle, tmp_path, payload_sha256, payload_bytes)]
    assert type(installed[0][3]) is int
    assert seen[0][1]["resource_cache_dir"] == root
    assert seen[0][0] == tmp_path / "data"
    assert not (tmp_path / "Downloads").exists()


@pytest.mark.parametrize("value", ["relative", "", "bad\0path", 3, b"/bytes"])
def test_start_rejects_ambiguous_resource_root_before_install_or_java(boundary, value):
    with pytest.raises(ValueError, match="absolute"):
        boundary.start("unused", object(), object(), resource_cache_dir=value)
