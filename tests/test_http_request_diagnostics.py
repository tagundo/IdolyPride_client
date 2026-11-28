"""Observe real HTTP arrivals independently of successful master downloads."""
from concurrent.futures import ThreadPoolExecutor
import json
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from idoly_local.app_runtime import Runtime
from idoly_local.assets import _public_http_path, create_asset_server


@pytest.fixture
def http_server(tmp_path):
    root = tmp_path / "assets"
    (root / "master").mkdir(parents=True)
    (root / "master/file.db").write_bytes(b"public master bytes")
    runtime = Runtime("http-observer-fixture")
    transfers = []
    server = create_asset_server("127.0.0.1", 0, root, transfer_callback=transfers.append,
                                 http_request_callback=runtime._observe_http_request)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", runtime, transfers
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
        assert not worker.is_alive()


def settled(runtime, count):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        status = runtime.status()["http_requests"]
        if status["total_requests"] == count and status["active_requests"] == 0:
            return status
        time.sleep(.005)
    raise AssertionError("HTTP observations did not finish")


def test_404_head_and_post_arrivals_are_visible_without_leaking_request_secrets(http_server):
    base, runtime, transfers = http_server
    for method, path, expected in (
            ("GET", "/master/file.db?token=query-secret", 200),
            ("HEAD", "/missing?token=query-secret", 404),
            ("POST", "/not-a-command?token=query-secret", 404),
            ("HEAD", "/master/file.db", 200)):
        request = Request(base + path, method=method,
            data=b"body-secret" if method == "POST" else None,
            headers={"Authorization": "Bearer header-secret", "Cookie": "session=cookie-secret"})
        try:
            response = urlopen(request, timeout=2)
        except HTTPError as error:
            response = error
        with response:
            assert response.status == expected
            response.read()
    status = settled(runtime, 4)
    assert status["completed_requests"] == 2 and status["failed_requests"] == 2
    assert [(row["method"], row["path"], row["http_status"], row["phase"])
            for row in status["recent_requests"]] == [
        ("GET", "/master/file.db", 200, "completed"),
        ("HEAD", "/missing", 404, "failed"),
        ("POST", "/not-a-command", 404, "failed"),
        ("HEAD", "/master/file.db", 200, "completed")]
    text = json.dumps(status)
    assert all(secret not in text for secret in ("query-secret", "body-secret", "header-secret", "cookie-secret"))
    # The old master-transfer hook keeps its successful-body semantics:
    # neither failed routes nor HEAD add fictitious byte transfers.
    assert [row["phase"] for row in transfers] == ["started", "completed"]
    assert transfers[-1]["sent_bytes"] == len(b"public master bytes")


def test_concurrent_requests_have_bounded_recent_history_and_independent_snapshots(http_server):
    base, runtime, _transfers = http_server
    def request(_index):
        with urlopen(Request(base + "/master/file.db", method="HEAD"), timeout=2) as response:
            assert response.status == 200
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(request, range(16)))
    status = settled(runtime, 16)
    assert status["completed_requests"] == 16 and status["failed_requests"] == 0
    assert len(status["recent_requests"]) == 10
    assert len({row["request_id"] for row in status["recent_requests"]}) == 10
    status["last_request"]["path"] = "/mutated-snapshot"
    status["recent_requests"][0]["path"] = "/mutated-history"
    assert runtime.status()["http_requests"]["last_request"]["path"] == "/master/file.db"
    assert all(row["path"] == "/master/file.db" for row in runtime.status()["http_requests"]["recent_requests"])


def test_last_failed_request_survives_later_successful_polling_and_history_eviction(http_server):
    base, runtime, _transfers = http_server
    with pytest.raises(HTTPError) as caught:
        urlopen(base + "/early-missing?token=query-secret", timeout=2)
    caught.value.close()
    first = settled(runtime, 1)["last_failed_request"]
    assert first["path"] == "/early-missing" and first["http_status"] == 404
    for _ in range(12):
        with urlopen(base + "/master/file.db", timeout=2) as response:
            assert response.status == 200
            response.read()
    status = settled(runtime, 13)
    assert status["last_request"]["http_status"] == 200
    assert len(status["recent_requests"]) == 10
    assert all(row["http_status"] == 200 for row in status["recent_requests"])
    assert status["last_failed_request"] == first
    assert status["failed_requests"] == 1 and status["completed_requests"] == 12
    assert "query-secret" not in json.dumps(status)
    status["last_failed_request"]["path"] = "/changed"
    assert runtime.status()["http_requests"]["last_failed_request"]["path"] == "/early-missing"


def test_public_path_drops_authority_queries_fragments_and_bounds_control_characters():
    value = _public_http_path("http://user:authority-secret@host/a\x00b?query-secret#fragment-secret")
    assert value == "/a_b"
    assert len(_public_http_path("/" + "x" * 1000)) == 256
    assert _public_http_path("http://[broken:authority-secret?q=secret") == "/<invalid-path>"


def test_observer_failure_cannot_interrupt_real_file_delivery(tmp_path):
    (tmp_path / "file.bin").write_bytes(b"still served")
    def broken(_event):
        raise RuntimeError("observer failure")
    server = create_asset_server("127.0.0.1", 0, tmp_path, http_request_callback=broken)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        with urlopen(f"http://127.0.0.1:{server.server_port}/file.bin", timeout=2) as response:
            assert response.read() == b"still served"
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
