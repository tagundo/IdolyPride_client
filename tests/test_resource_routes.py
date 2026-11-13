"""The native frontends use bounded commands and an explicitly completed ZIP."""
from contextlib import contextmanager
from http.client import HTTPConnection
import json
import threading

import pytest

from idoly_local.assets import create_asset_server


class Library:
    def __init__(self):
        self.calls = []

    def status(self):
        return {"schema": 1, "catalogs": {}, "job": None}

    def catalog_summary(self, platform):
        self.calls.append(("preview", platform))

    def start_download(self, platform, kind="all", *, parallelism=None):
        self.calls.append(("download", platform, kind) if parallelism is None
                          else ("download", platform, kind, parallelism))
        return {"job_id": "job-1", "state": "running"}

    def cancel(self, identifier):
        self.calls.append(("cancel", identifier))
        return {"job_id": identifier, "state": "cancelling"}

    def prepare_export(self, platform, kind="all"):
        self.calls.append(("export", platform, kind))
        return {"job_id": "job-2", "filename": "resources-ios.zip"}

    def write_export(self, identifier, output):
        output.write(b"PK-complete-test-stream")
        return {"job_id": identifier, "archive_complete": True}


@contextmanager
def serve(tmp_path, library):
    server = create_asset_server("127.0.0.1", 0, tmp_path, resource_library=library)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)
        assert not thread.is_alive()


def request(server, path, method="GET", body=None, headers=None):
    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=3)
    try:
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def test_status_is_cheap_and_download_commands_are_typed(tmp_path):
    library = Library()
    with serve(tmp_path, library) as server:
        assert request(server, "/client/resources")[0] == 200
        assert library.calls == []
        assert request(server, "/client/resources?platform=ios")[0] == 200
        assert library.calls == [("preview", "ios")]
        status, _, raw = request(server, "/client/resources/download", "POST",
            json.dumps({"platform": "android", "kind": "all"}), {"Content-Type": "application/json"})
        assert status == 202 and json.loads(raw)["job_id"] == "job-1"
        assert library.calls[-1] == ("download", "android", "all")


@pytest.mark.parametrize("raw", [b'{"platform":"ios","platform":"android"}',
    b'{"platform":"ios","kind":"all","url":"https://elsewhere"}', b'{"platform":"ios","kind":null}',
    b'{"platform":false}', b'[]', b'{"platform":"ios","kind":NaN}'])
def test_bad_commands_never_start_network_or_jobs(tmp_path, raw):
    library = Library()
    with serve(tmp_path, library) as server:
        status, _, _ = request(server, "/client/resources/download", "POST", raw,
            {"Content-Type": "application/json"})
        assert status == 400 and library.calls == []


@pytest.mark.parametrize("parallelism", (1, 2, 4, 8))
def test_parallel_download_selection_reaches_the_job_without_affecting_other_commands(tmp_path, parallelism):
    library = Library()
    with serve(tmp_path, library) as server:
        status, _, _ = request(server, "/client/resources/download", "POST",
            json.dumps({"platform": "ios", "parallelism": parallelism}),
            {"Content-Type": "application/json"})
        assert status == 202 and library.calls == [("download", "ios", "all", parallelism)]
        status, _, _ = request(server, "/client/resources/export?platform=ios&parallelism=8")
        assert status == 400 and len(library.calls) == 1


@pytest.mark.parametrize("parallelism", (None, True, False, 0, 3, 9, 16, 4.0, "4", [], {}))
def test_invalid_parallelism_never_reaches_a_download_worker(tmp_path, parallelism):
    library = Library()
    with serve(tmp_path, library) as server:
        status, _, _ = request(server, "/client/resources/download", "POST",
            json.dumps({"platform": "android", "parallelism": parallelism}),
            {"Content-Type": "application/json"})
        assert status == 400 and library.calls == []


def test_http_parallelism_starts_real_overlapping_verified_downloads(tmp_path):
    from idoly_local.resource_library import ResourceLibrary
    from test_resource_library import AES, Response, catalog, complete

    manifest, bodies = catalog(tmp_path, count=4)
    first_wave = threading.Barrier(5)
    release = threading.Event()
    lock = threading.Lock()
    calls = []

    def fetch(url, *, timeout):
        with lock:
            calls.append(url)
            initial = len(calls) <= 4
        if initial:
            first_wave.wait(timeout=3)
            assert release.wait(3)
        return Response(bodies[url])

    library = ResourceLibrary(tmp_path, {"android": manifest}, fetcher=fetch,
                              aes_cbc=AES, resource_cache_dir=tmp_path / "Download" / "IdolyPride")
    try:
        with serve(tmp_path, library) as server:
            status, _, raw = request(server, "/client/resources/download", "POST",
                json.dumps({"platform": "android", "parallelism": 4}),
                {"Content-Type": "application/json"})
            assert status == 202 and json.loads(raw)["parallelism"] == 4
            first_wave.wait(timeout=3)  # Four real cache workers reached the transport together.
            assert len(calls) == 4
            release.set()
            job = complete(library)
            assert job["state"] == "completed" and job["failed_files"] == 0
            assert job["verified_files"] == len(manifest.objects)
            assert set(calls) == set(bodies)
    finally:
        release.set()
        library.close()


def test_stream_has_job_identity_no_false_length_and_head_never_exports(tmp_path):
    library = Library()
    with serve(tmp_path, library) as server:
        path = "/client/resources/export?platform=ios&kind=all"
        assert request(server, path, "HEAD")[0] == 404 and library.calls == []
        status, headers, body = request(server, path)
        assert status == 200 and body == b"PK-complete-test-stream"
        assert headers["X-Idoly-Resource-Job"] == "job-2"
        assert headers["Connection"] == "close" and "Content-Length" not in headers
        assert headers["Content-Type"] == "application/zip"
        assert library.calls == [("export", "ios", "all")]


@pytest.mark.parametrize("path", ["/client/resources?platform=ios&platform=android",
    "/client/resources/export?platform=elsewhere", "/client/resources/export?platform=ios&path=/tmp/a",
    "/client/%72esources/export?platform=ios"])
def test_unknown_and_encoded_selections_are_reserved(tmp_path, path):
    library = Library()
    with serve(tmp_path, library) as server:
        assert request(server, path)[0] in (400, 404)
        assert library.calls == []


def test_disconnect_while_sending_export_headers_releases_reserved_job():
    from types import SimpleNamespace
    from idoly_local import resource_routes
    library = Library()
    def disconnected(*_args):
        raise BrokenPipeError("closed native download")
    handler = SimpleNamespace(path="/client/resources/export?platform=ios", _loopback=lambda: True,
        connection=SimpleNamespace(gettimeout=lambda: None, settimeout=lambda _: None),
        send_response=disconnected)
    assert resource_routes.get(handler, library) is True
    assert library.calls == [("export", "ios", "all"), ("cancel", "job-2")]
