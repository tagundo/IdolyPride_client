from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib
import io
import os
from pathlib import Path
import socket
import ssl
import sys
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request

import pytest

from idoly_local.octo_cache import (OctoCache, OctoCacheError, OctoCacheMiss,
                                    _CDNRedirects)
from idoly_local.octo_manifest import OctoObject
from idoly_local import octo_cache


BODY = b"original encrypted CDN object\x00\xff"


def record(body=BODY, name="object_01"):
    return OctoObject("assetbundle", 202050, name, 1234567, len(body),
                      hashlib.md5(body, usedforsecurity=False).hexdigest(), "bundle-name")


class Response(io.BytesIO):
    status = 200

    def __init__(self, body=BODY, *, headers=None, url=None):
        super().__init__(body)
        self.headers = {} if headers is None else headers
        self.url = url or record().upstream_url

    def geturl(self):
        return self.url


def destination(cache, item):
    return cache.root / item.cache_key[:2] / (item.cache_key + ".bin")


def read(cache, item):
    with cache.open_verified(item) as stream:
        assert stream.seekable()
        return stream.read()


def test_complete_bytes_are_verified_before_publish_and_cache_progress_is_separate(tmp_path):
    calls, events = [], []
    item = record()

    def fetch(url, *, timeout):
        calls.append((url, timeout))
        return Response(headers={"Content-Length": str(len(BODY))})

    def observe(event):
        events.append(event)
        assert destination(cache, item).exists() == (event["phase"] in ("verified", "cache_hit"))

    cache = OctoCache(tmp_path, fetcher=fetch, on_event=observe)
    assert read(cache, item) == BODY
    assert read(cache, item) == BODY
    assert calls == [(item.upstream_url, 30)]
    assert [e["phase"] for e in events] == ["started", "progress", "verified", "cache_hit"]
    assert events[-2]["received_bytes"] == len(BODY)
    assert events[-1]["received_bytes"] == 0
    assert all(e["cache_key"] == item.cache_key and e["total_bytes"] == len(BODY) for e in events)
    assert destination(cache, item).stat().st_mode & 0o777 == 0o400
    assert not list(tmp_path.rglob("*.part"))


def test_restart_checks_archived_file_without_network_or_a_download_event(tmp_path):
    item = record()
    cache = OctoCache(tmp_path, fetcher=lambda *a, **kw: Response())
    assert read(cache, item) == BODY
    events = []
    restarted = OctoCache(tmp_path, allow_download=False, on_event=events.append)
    assert read(restarted, item) == BODY
    assert [e["phase"] for e in events] == ["cache_hit"]
    assert events[0]["received_bytes"] == 0


@pytest.mark.parametrize("body,headers,status,url,code", [
    (BODY[:-1], {}, 200, None, "upstream_size"),
    (BODY + b"extra", {}, 200, None, "upstream_size"),
    (b"x" * len(BODY), {}, 200, None, "upstream_digest"),
    (BODY, {"Content-Length": str(len(BODY) + 1)}, 200, None, "upstream_size"),
    (BODY, {"Content-Length": "invalid"}, 200, None, "upstream_size"),
    (BODY, {"Content-Encoding": "gzip"}, 200, None, "upstream_encoding"),
    (BODY, {}, 206, None, "upstream_http"),
    (BODY, {}, 403, None, "upstream_http"),
    (BODY, {}, 200, "https://untrusted.invalid/object", "upstream_redirect"),
])
def test_partial_invalid_and_rejected_upstream_never_become_cache_files(
        tmp_path, body, headers, status, url, code):
    response = Response(body, headers=headers, url=url)
    response.status = status
    events = []
    cache = OctoCache(tmp_path, fetcher=lambda *a, **kw: response, on_event=events.append)
    with pytest.raises(OctoCacheError) as caught:
        read(cache, record())
    assert caught.value.code == code
    assert response.closed
    assert not destination(cache, record()).exists()
    assert not list(tmp_path.rglob("*.part"))
    assert [e["phase"] for e in events][-1] == "failed"
    assert not any(e["phase"] == "verified" for e in events)
    assert "untrusted.invalid" not in str(caught.value)


def test_stream_timeout_closes_response_and_removes_partial_file(tmp_path):
    class Slow(Response):
        def read(self, count=-1):
            time.sleep(0.04)
            return super().read(count)

    response = Slow()
    cache = OctoCache(tmp_path, fetcher=lambda *a, **kw: response, total_timeout=0.02)
    with pytest.raises(OctoCacheError) as caught:
        read(cache, record())
    assert caught.value.code == "upstream_timeout"
    assert response.closed
    assert not list(tmp_path.rglob("*.part"))
    assert not destination(cache, record()).exists()


def test_upstream_timeout_exception_is_a_fixed_error_and_retry_can_succeed(tmp_path):
    calls = 0

    def fetch(url, *, timeout):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TimeoutError("sensitive-internal-detail")
        return Response()

    cache = OctoCache(tmp_path, fetcher=fetch)
    with pytest.raises(OctoCacheError) as caught:
        read(cache, record())
    assert caught.value.code == "upstream_timeout"
    assert "sensitive" not in str(caught.value)
    assert read(cache, record()) == BODY
    assert calls == 2


def test_unexpected_fetch_or_observer_errors_cannot_publish_bad_bytes(tmp_path):
    def broken_fetch(*args, **kwargs):
        raise RuntimeError("sensitive-internal-detail")

    cache = OctoCache(tmp_path, fetcher=broken_fetch)
    with pytest.raises(OctoCacheError) as caught:
        read(cache, record())
    assert "sensitive" not in str(caught.value)
    assert not list(tmp_path.rglob("*.part"))

    def broken_observer(event):
        raise RuntimeError("observer failure")

    cache = OctoCache(tmp_path, fetcher=lambda *a, **kw: Response(), on_event=broken_observer)
    assert read(cache, record()) == BODY


def test_exception_and_progress_codes_cannot_echo_adapter_details(tmp_path):
    events = []

    def failed_adapter(*args, **kwargs):
        raise OctoCacheError("sensitive-adapter-detail")

    cache = OctoCache(tmp_path, fetcher=failed_adapter, on_event=events.append)
    with pytest.raises(OctoCacheError) as caught:
        read(cache, record())
    assert caught.value.code == "cache_io"
    assert events[-1]["error_code"] == "cache_io"
    assert "sensitive" not in str(caught.value) + repr(events)


@pytest.mark.parametrize("reason,code", [
    (URLError(TimeoutError("sensitive timeout URL")), "upstream_timeout"),
    (URLError(socket.gaierror(-2, "sensitive DNS hostname")), "upstream_dns"),
    (URLError(ConnectionRefusedError("sensitive connection hostname")), "upstream_connect"),
    (URLError("sensitive transport description"), "upstream_connect"),
    (ConnectionResetError("sensitive response details"), "upstream_connect"),
    (URLError(ssl.SSLError("sensitive TLS transcript")), "upstream_tls"),
])
def test_transport_causes_have_distinct_fixed_codes_without_exception_details(tmp_path, reason, code):
    events = []
    def fetch(*args, **kwargs):
        raise reason
    cache = OctoCache(tmp_path, fetcher=fetch, on_event=events.append)
    with pytest.raises(OctoCacheError) as caught:
        read(cache, record())
    assert caught.value.code == code and events[-1]["error_code"] == code
    assert "sensitive" not in str(caught.value) + repr(events)
    assert not destination(cache, record()).exists() and not list(tmp_path.rglob("*.part"))


def test_certificate_verification_exports_only_its_bounded_numeric_code(tmp_path):
    reason = ssl.SSLCertVerificationError(1, "sensitive certificate names and URL")
    reason.verify_code = 20
    events = []
    def fetch(*args, **kwargs):
        raise URLError(reason)
    cache = OctoCache(tmp_path, fetcher=fetch, on_event=events.append)
    with pytest.raises(OctoCacheError) as caught:
        read(cache, record())
    assert caught.value.code == "upstream_tls" and caught.value.verify_code == 20
    assert events[-1]["verify_code"] == 20 and "http_status" not in events[-1]
    assert "sensitive" not in str(caught.value) + repr(events)


def test_actual_http_error_retains_status_closes_body_and_does_not_export_url(tmp_path):
    response = io.BytesIO(b"sensitive upstream error body")
    reason = HTTPError("https://private.invalid/?token=sensitive", 403,
                       "sensitive upstream message", {"Secret": "sensitive"}, response)
    events = []
    def fetch(*args, **kwargs):
        raise reason
    cache = OctoCache(tmp_path, fetcher=fetch, on_event=events.append)
    with pytest.raises(OctoCacheError) as caught:
        read(cache, record())
    assert caught.value.code == "upstream_http" and caught.value.http_status == 403
    assert events[-1]["http_status"] == 403 and response.closed
    assert "sensitive" not in str(caught.value) + repr(events)
    assert "private.invalid" not in str(caught.value) + repr(events)


@pytest.mark.parametrize("value", [True, "403", -1, 600, None])
def test_diagnostic_numeric_fields_do_not_accept_unbounded_or_wrong_type_data(value):
    assert OctoCacheError("upstream_http", http_status=value).http_status is None
    assert OctoCacheError("upstream_tls", verify_code="sensitive").verify_code is None
    assert OctoCacheError("cache_io", http_status=403, verify_code=20).http_status is None


def test_source_upstream_preserves_default_transport_without_a_frozen_certificate_file(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    def forbidden():
        raise AssertionError("Source transport must retain its normal CA context")
    monkeypatch.setattr(octo_cache, "_frozen_tls_context", forbidden)
    calls = []
    class Opener:
        def open(self, request, *, timeout):
            calls.append((request.full_url, request.get_header("Accept-encoding"), timeout))
            return Response()
    monkeypatch.setattr(octo_cache, "build_opener", lambda *handlers: Opener())
    with octo_cache.open_upstream(record().upstream_url, timeout=5) as response:
        assert response.read() == BODY
    assert calls == [(record().upstream_url, "identity", 5)]


def test_platform_resource_adapter_does_not_open_python_tls_or_a_frozen_ca(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    def forbidden(*args, **kwargs):
        raise AssertionError("Custom platform adapter owns HTTPS trust")
    monkeypatch.setattr(octo_cache, "_frozen_tls_context", forbidden)
    monkeypatch.setattr(octo_cache, "open_upstream", forbidden)
    cache = OctoCache(tmp_path, fetcher=lambda *args, **kwargs: Response())
    assert read(cache, record()) == BODY


def test_concurrent_requests_share_one_complete_fetch_and_independent_streams(tmp_path):
    entered, release = threading.Event(), threading.Event()
    calls = 0
    guard = threading.Lock()

    class Held(Response):
        def read(self, count=-1):
            entered.set()
            assert release.wait(3)
            return super().read(count)

    def fetch(url, *, timeout):
        nonlocal calls
        with guard:
            calls += 1
        return Held()

    cache = OctoCache(tmp_path, fetcher=fetch)
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(read, cache, record()) for _ in range(8)]
        assert entered.wait(2)
        assert not destination(cache, record()).exists()
        release.set()
        assert [f.result(timeout=3) for f in futures] == [BODY] * 8
    assert calls == 1


def test_concurrent_failure_is_shared_with_waiting_requests(tmp_path):
    entered, release = threading.Event(), threading.Event()
    calls = 0

    class Held(Response):
        def read(self, count=-1):
            entered.set()
            assert release.wait(3)
            return super().read(count)

    def fetch(url, *, timeout):
        nonlocal calls
        calls += 1
        return Held(b"x" * len(BODY))

    cache = OctoCache(tmp_path, fetcher=fetch)
    with ThreadPoolExecutor(max_workers=6) as pool:
        first = pool.submit(read, cache, record())
        assert entered.wait(2)
        rest = [pool.submit(read, cache, record()) for _ in range(5)]
        # All requests run while the same upstream transfer is held open.
        deadline = time.monotonic() + 2
        while not all(f.running() for f in rest) and time.monotonic() < deadline:
            time.sleep(0.005)
        assert all(f.running() for f in rest)
        time.sleep(0.03)
        release.set()
        for future in [first, *rest]:
            with pytest.raises(OctoCacheError) as caught:
                future.result(timeout=3)
            assert caught.value.code == "upstream_digest"
    assert calls == 1
    assert not list(tmp_path.rglob("*.part"))


def test_different_objects_obey_parallel_download_limit(tmp_path):
    release, two_entered = threading.Event(), threading.Event()
    guard = threading.Lock()
    active = maximum = 0

    class Held(Response):
        def __enter__(self):
            nonlocal active, maximum
            with guard:
                active += 1
                maximum = max(maximum, active)
                if active == 2:
                    two_entered.set()
            assert release.wait(3)
            return self

        def __exit__(self, *args):
            nonlocal active
            with guard:
                active -= 1
            return super().__exit__(*args)

    cache = OctoCache(tmp_path, fetcher=lambda *a, **kw: Held(), max_parallel=2)
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(read, cache, record(name=f"object_{n}")) for n in range(6)]
        assert two_entered.wait(2)
        assert maximum == 2
        release.set()
        assert [f.result(timeout=3) for f in futures] == [BODY] * 6
    assert maximum == 2


def test_disk_corruption_with_restored_mtime_is_not_hidden_by_verification_memo(tmp_path):
    calls = 0

    def fetch(*args, **kwargs):
        nonlocal calls
        calls += 1
        return Response()

    item = record()
    cache = OctoCache(tmp_path, fetcher=fetch)
    assert read(cache, item) == BODY
    path = destination(cache, item)
    old = path.stat()
    path.chmod(0o600)
    path.write_bytes(b"x" * len(BODY))
    os.utime(path, ns=(old.st_atime_ns, old.st_mtime_ns))
    path.chmod(0o400)
    assert read(cache, item) == BODY
    assert calls == 2


def test_replacing_cache_path_does_not_change_an_already_open_verified_stream(tmp_path):
    cache = OctoCache(tmp_path, fetcher=lambda *a, **kw: Response())
    item = record()
    with cache.open_verified(item) as first:
        path = destination(cache, item)
        replacement = path.with_name("replacement")
        replacement.write_bytes(b"wrong")
        replacement.replace(path)
        assert read(cache, item) == BODY
        assert first.read() == BODY


def test_existing_symlink_and_hardlink_never_modify_external_file(tmp_path):
    outside = tmp_path / "outside"
    outside.write_bytes(BODY)
    original_mode = outside.stat().st_mode
    cache = OctoCache(tmp_path / "cache", fetcher=lambda *a, **kw: Response())
    item = record()
    path = destination(cache, item)
    path.parent.mkdir()
    path.symlink_to(outside)
    assert read(cache, item) == BODY
    assert outside.stat().st_mode == original_mode
    path.unlink()
    os.link(outside, path)
    assert read(cache, item) == BODY
    assert outside.read_bytes() == BODY
    assert outside.stat().st_mode == original_mode
    assert path.stat().st_ino != outside.stat().st_ino


def test_shard_symlink_fails_before_any_upstream_or_external_write(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    calls = []
    cache = OctoCache(tmp_path / "cache", fetcher=lambda *a, **kw: calls.append(a))
    (cache.root / record().cache_key[:2]).symlink_to(outside, target_is_directory=True)
    with pytest.raises(OctoCacheError) as caught:
        read(cache, record())
    assert caught.value.code == "cache_io"
    assert not calls and not list(outside.iterdir())


@pytest.mark.parametrize("changes", [
    {"kind": "ab"}, {"object_name": "../outside"}, {"object_name": "https://evil.invalid"},
    {"object_name": "encoded%2Fname"}, {"upload_version": True}, {"generation": 0},
    {"size": 0}, {"size": 513 * 1024 * 1024}, {"md5": "not-a-hash"},
])
def test_invalid_records_cannot_choose_paths_or_upstream_urls(tmp_path, changes):
    calls = []
    cache = OctoCache(tmp_path, fetcher=lambda *a, **kw: calls.append(a))
    with pytest.raises(ValueError, match="metadata"):
        read(cache, replace(record(), **changes))
    assert not calls and not list(tmp_path.iterdir())


def test_download_disabled_and_lifetime_allowance_are_honest_misses(tmp_path):
    cache = OctoCache(tmp_path, allow_download=False)
    with pytest.raises(OctoCacheMiss):
        read(cache, record())
    cache = OctoCache(tmp_path, max_download_bytes=len(BODY), fetcher=lambda *a, **kw: Response())
    assert read(cache, record()) == BODY
    assert read(cache, record()) == BODY  # Cached reads spend no upstream allowance.
    with pytest.raises(OctoCacheError) as caught:
        read(cache, record(name="another_object"))
    assert caught.value.code == "budget_exceeded"
    assert not destination(cache, record(name="another_object")).exists()


@pytest.mark.parametrize("url", [
    "http://d2ilil7yh5oi1v.cloudfront.net/path", "https://elsewhere.invalid/path",
    "https://user@d2ilil7yh5oi1v.cloudfront.net/path",
    "https://d2ilil7yh5oi1v.cloudfront.net:444/path",
])
def test_default_redirect_handler_rejects_other_tls_origins(url):
    with pytest.raises(OctoCacheError) as caught:
        _CDNRedirects().redirect_request(Request(record().upstream_url), None, 302, "redirect", {}, url)
    assert caught.value.code == "upstream_redirect"


def test_default_redirect_handler_keeps_https_verification_and_same_origin():
    url = "https://d2ilil7yh5oi1v.cloudfront.net/another-object"
    request = _CDNRedirects().redirect_request(Request(record().upstream_url), None, 302, "redirect", {}, url)
    assert request.full_url == url


def test_close_rejects_new_downloads_and_already_verified_cache_hits(tmp_path):
    cache = OctoCache(tmp_path, fetcher=lambda *a, **kw: Response())
    assert read(cache, record()) == BODY
    cache.close()
    cache.close()
    for item in (record(), record(name="new_object")):
        with pytest.raises(OctoCacheError) as caught:
            read(cache, item)
        assert caught.value.code == "cache_closed"


def test_close_interrupts_active_response_and_releases_coalesced_waiters(tmp_path):
    entered, interrupted = threading.Event(), threading.Event()
    events = []

    class Blocking(Response):
        close_calls = 0

        def read(self, count=-1):
            entered.set()
            assert interrupted.wait(3)
            raise OSError("transport aborted")

        def close(self):
            self.close_calls += 1
            interrupted.set()
            return super().close()

    response = Blocking()
    cache = OctoCache(tmp_path, fetcher=lambda *a, **kw: response, on_event=events.append)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(read, cache, record())
        assert entered.wait(2)
        second = pool.submit(read, cache, record())
        cache.close()
        for future in (first, second):
            with pytest.raises(OctoCacheError) as caught:
                future.result(timeout=1)
            assert caught.value.code == "cache_closed"
    count = response.close_calls
    cache.close()
    assert response.close_calls == count
    assert response.closed and not destination(cache, record()).exists()
    assert not list(tmp_path.rglob("*.part"))
    assert not any(event["phase"] == "verified" for event in events)
    assert events[-1]["phase"] == "failed" and events[-1]["error_code"] == "cache_closed"


def test_close_while_opening_headers_discards_late_response_without_reading(tmp_path):
    opening, release = threading.Event(), threading.Event()

    class Unread(Response):
        read_calls = 0

        def read(self, count=-1):
            self.read_calls += 1
            return super().read(count)

    response = Unread()

    def fetch(*args, **kwargs):
        opening.set()
        assert release.wait(3)
        return response

    cache = OctoCache(tmp_path, fetcher=fetch)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(read, cache, record())
        assert opening.wait(2)
        waiting = pool.submit(read, cache, record())
        cache.close()  # No response handle exists yet; this need not wait for DNS/headers.
        with pytest.raises(OctoCacheError) as caught:
            waiting.result(timeout=1)
        assert caught.value.code == "cache_closed"
        assert not destination(cache, record()).exists()
        release.set()
        with pytest.raises(OctoCacheError) as caught:
            first.result(timeout=1)
        assert caught.value.code == "cache_closed"
    assert response.closed and response.read_calls == 0
    assert not list(tmp_path.rglob("*.part"))


def test_cancelled_read_still_counts_bytes_returned_before_discard(tmp_path):
    entered, interrupted = threading.Event(), threading.Event()
    events = []

    class LateBody(Response):
        def read(self, count=-1):
            entered.set()
            assert interrupted.wait(3)
            return BODY  # The transport returns a buffered chunk during cancellation.

        def close(self):
            interrupted.set()
            return super().close()

    cache = OctoCache(tmp_path, fetcher=lambda *a, **kw: LateBody(), on_event=events.append)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(read, cache, record())
        assert entered.wait(2)
        cache.close()
        with pytest.raises(OctoCacheError) as caught:
            future.result(timeout=1)
        assert caught.value.code == "cache_closed"
    assert events[-1]["phase"] == "failed" and events[-1]["received_bytes"] == len(BODY)
    assert not destination(cache, record()).exists()
    assert not list(tmp_path.rglob("*.part"))


def test_close_before_atomic_publication_leaves_no_verified_or_partial_file(tmp_path, monkeypatch):
    import idoly_local.octo_cache as module
    flushing, release = threading.Event(), threading.Event()
    original_fsync = module.os.fsync

    def held_fsync(descriptor):
        flushing.set()
        assert release.wait(3)
        return original_fsync(descriptor)

    monkeypatch.setattr(module.os, "fsync", held_fsync)
    events = []
    cache = OctoCache(tmp_path, fetcher=lambda *a, **kw: Response(), on_event=events.append)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(read, cache, record())
        assert flushing.wait(2)
        cache.close()
        release.set()
        with pytest.raises(OctoCacheError) as caught:
            future.result(timeout=1)
        assert caught.value.code == "cache_closed"
    assert not destination(cache, record()).exists()
    assert not list(tmp_path.rglob("*.part"))
    assert not any(e["phase"] == "verified" for e in events)


def test_close_cancels_an_object_waiting_for_download_capacity(tmp_path):
    entered, interrupted = threading.Event(), threading.Event()
    calls = []

    class Blocking(Response):
        def read(self, count=-1):
            entered.set()
            assert interrupted.wait(3)
            raise OSError("transport aborted")

        def close(self):
            interrupted.set()
            return super().close()

    def fetch(url, *, timeout):
        calls.append(url)
        return Blocking()

    cache = OctoCache(tmp_path, fetcher=fetch, max_parallel=1)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(read, cache, record())
        assert entered.wait(2)
        waiting = pool.submit(read, cache, record(name="another_object"))
        cache.close()
        for future in (first, waiting):
            with pytest.raises(OctoCacheError) as caught:
                future.result(timeout=1)
            assert caught.value.code == "cache_closed"
    assert len(calls) == 1
    assert not list(tmp_path.rglob("*.part"))


def seed_file(root, item, body=BODY):
    path = root / item.cache_key[:2] / (item.cache_key + ".bin")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return path


def no_upstream(*args, **kwargs):
    pytest.fail("A valid legacy cache object must not contact the CDN")


def test_seed_copy_works_offline_preserves_legacy_and_reports_zero_upstream_bytes(tmp_path):
    item = record()
    legacy = tmp_path / "legacy"
    source = seed_file(legacy, item)
    before = octo_cache._stamp(source.stat())
    events = []
    cache = OctoCache(tmp_path / "public", seed_dirs=(legacy,), allow_download=False,
                      fetcher=no_upstream, on_event=events.append)
    assert read(cache, item) == BODY
    assert read(cache, item) == BODY
    assert source.read_bytes() == BODY and octo_cache._stamp(source.stat()) == before
    assert source.stat().st_ino != destination(cache, item).stat().st_ino
    assert destination(cache, item).stat().st_mode & 0o777 == 0o400
    assert [event["phase"] for event in events] == ["cache_hit", "cache_hit"]
    assert all(event["received_bytes"] == 0 for event in events)
    assert cache._allowance_spent == 0 and not list(cache.root.rglob("*.part"))


@pytest.mark.parametrize("body", [BODY[:-1], b"x" * len(BODY)])
def test_invalid_seed_size_or_digest_is_preserved_and_remains_an_offline_miss(tmp_path, body):
    item = record()
    legacy = tmp_path / "legacy"
    source = seed_file(legacy, item, body)
    before = octo_cache._stamp(source.stat())
    events = []
    cache = OctoCache(tmp_path / "public", seed_dirs=(legacy,), allow_download=False,
                      fetcher=no_upstream, on_event=events.append)
    with pytest.raises(OctoCacheMiss):
        read(cache, item)
    assert source.read_bytes() == body and octo_cache._stamp(source.stat()) == before
    assert not destination(cache, item).exists() and not list(cache.root.rglob("*.part"))
    assert events == []


def test_first_bad_seed_can_fall_back_to_second_verified_seed_without_deleting_either(tmp_path):
    item = record()
    first, second = tmp_path / "first", tmp_path / "second"
    bad = seed_file(first, item, b"x" * len(BODY))
    good = seed_file(second, item)
    cache = OctoCache(tmp_path / "public", seed_dirs=[first, second], allow_download=False,
                      fetcher=no_upstream)
    assert read(cache, item) == BODY
    assert bad.read_bytes() == b"x" * len(BODY) and good.read_bytes() == BODY


@pytest.mark.parametrize("kind", ["file-symlink", "shard-symlink", "hardlink", "fifo"])
def test_seed_special_files_and_directory_symlinks_are_never_followed_or_modified(tmp_path, kind):
    item = record()
    legacy, outside = tmp_path / "legacy", tmp_path / "outside"
    legacy.mkdir()
    outside.mkdir()
    external = outside / (item.cache_key + ".bin")
    external.write_bytes(BODY)
    before = octo_cache._stamp(external.stat())
    shard = legacy / item.cache_key[:2]
    if kind == "shard-symlink":
        shard.symlink_to(outside, target_is_directory=True)
    else:
        shard.mkdir()
        source = shard / external.name
        if kind == "file-symlink":
            source.symlink_to(external)
        elif kind == "hardlink":
            os.link(external, source)
            before = octo_cache._stamp(external.stat())
        else:
            os.mkfifo(source)
    cache = OctoCache(tmp_path / "public", seed_dirs=(legacy,), allow_download=False,
                      fetcher=no_upstream)
    with pytest.raises(OctoCacheMiss):
        read(cache, item)
    assert external.read_bytes() == BODY and octo_cache._stamp(external.stat()) == before
    assert shard.is_symlink() if kind == "shard-symlink" else os.path.lexists(source)
    assert not destination(cache, item).exists() and not list(cache.root.rglob("*.part"))


@pytest.mark.parametrize("kind", ["missing", "file", "symlink", "duplicate", "too-many", "string", "generator"])
def test_seed_roots_are_explicit_existing_distinct_nonsymlink_directories(tmp_path, kind):
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    invalid = tmp_path / "invalid"
    if kind == "file":
        invalid.write_bytes(b"x")
    elif kind == "symlink":
        invalid.symlink_to(legacy, target_is_directory=True)
    roots = ((invalid,) if kind in ("missing", "file", "symlink") else
             (legacy, legacy) if kind == "duplicate" else
             (legacy, legacy, legacy) if kind == "too-many" else
             str(legacy) if kind == "string" else (path for path in (legacy,)))
    with pytest.raises(ValueError, match="seed"):
        OctoCache(tmp_path / "public", seed_dirs=roots)
    assert not invalid.exists() if kind == "missing" else legacy.is_dir()


def test_changed_seed_root_identity_cannot_redirect_reads(tmp_path):
    item = record()
    legacy = tmp_path / "legacy"
    source = seed_file(legacy, item)
    cache = OctoCache(tmp_path / "public", seed_dirs=(legacy,), allow_download=False,
                      fetcher=no_upstream)
    legacy.rename(tmp_path / "retained")
    substituted = seed_file(legacy, item)
    with pytest.raises(OctoCacheMiss):
        read(cache, item)
    assert substituted.read_bytes() == BODY
    assert (tmp_path / "retained" / source.relative_to(legacy)).read_bytes() == BODY


def test_seed_copy_never_spends_the_upstream_lifetime_allowance(tmp_path):
    item = record()
    legacy = tmp_path / "legacy"
    seed_file(legacy, item)
    calls = []

    def fetch(url, *, timeout):
        calls.append(url)
        return Response(url=url)

    cache = OctoCache(tmp_path / "public", seed_dirs=(legacy,), max_download_bytes=len(BODY), fetcher=fetch)
    assert read(cache, item) == BODY and cache._allowance_spent == 0
    other = record(name="uncached_object")
    assert read(cache, other) == BODY
    assert calls == [other.upstream_url] and cache._allowance_spent == len(BODY)


def test_two_cache_instances_publish_independent_verified_seed_copies_atomically(tmp_path, monkeypatch):
    item = record()
    legacy = tmp_path / "legacy"
    source = seed_file(legacy, item)
    caches = [OctoCache(tmp_path / "public", seed_dirs=(legacy,), allow_download=False,
                        fetcher=no_upstream) for _ in range(2)]
    barrier, original_replace = threading.Barrier(2), octo_cache.os.replace

    def simultaneous_replace(src, dst, **kwargs):
        barrier.wait(timeout=2)
        return original_replace(src, dst, **kwargs)

    monkeypatch.setattr(octo_cache.os, "replace", simultaneous_replace)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(read, cache, item) for cache in caches]
        assert [future.result(timeout=3) for future in futures] == [BODY, BODY]
    assert source.read_bytes() == BODY and destination(caches[0], item).read_bytes() == BODY
    assert not list(caches[0].root.rglob("*.part"))


def test_existing_verification_never_chmods_or_changes_a_valid_public_file(tmp_path, monkeypatch):
    item = record()
    cache = OctoCache(tmp_path / "public", allow_download=False, fetcher=no_upstream)
    path = seed_file(cache.root, item)
    path.chmod(0o600)
    before = octo_cache._stamp(path.stat())
    monkeypatch.setattr(octo_cache.os, "fchmod", lambda *args: pytest.fail("A verifier must not mutate an existing inode"))
    assert read(cache, item) == BODY
    assert octo_cache._stamp(path.stat()) == before


def test_bad_opened_inode_cannot_delete_another_caches_valid_replacement(tmp_path, monkeypatch):
    item = record()
    cache = OctoCache(tmp_path / "public", allow_download=False, fetcher=no_upstream)
    path = seed_file(cache.root, item, b"x" * len(BODY))
    old_inode = path.stat().st_ino
    replacement = path.with_name("other-verified-writer")
    replacement.write_bytes(BODY)
    replacement.chmod(0o400)
    new_inode = replacement.stat().st_ino
    original_fdopen = octo_cache.os.fdopen

    class ReplacedRead:
        def __init__(self, stream):
            self.stream, self.replaced = stream, False

        def __getattr__(self, name):
            return getattr(self.stream, name)

        def read(self, count):
            block = self.stream.read(count)
            if not block and not self.replaced:
                replacement.replace(path)
                self.replaced = True
            return block

    def replaced_fdopen(descriptor, mode, *args, **kwargs):
        stream = original_fdopen(descriptor, mode, *args, **kwargs)
        if mode == "rb" and os.fstat(stream.fileno()).st_ino == old_inode:
            return ReplacedRead(stream)
        return stream

    monkeypatch.setattr(octo_cache.os, "fdopen", replaced_fdopen)
    assert read(cache, item) == BODY
    assert path.stat().st_ino == new_inode and path.read_bytes() == BODY
    assert not list(cache.root.rglob("*.part"))


def test_two_cache_instances_publish_independent_verified_cdn_copies_atomically(tmp_path, monkeypatch):
    item, calls = record(), []

    def fetch(url, *, timeout):
        calls.append(url)
        return Response(url=url)

    caches = [OctoCache(tmp_path / "public", fetcher=fetch) for _ in range(2)]
    barrier, original_replace = threading.Barrier(2), octo_cache.os.replace

    def simultaneous_replace(src, dst, **kwargs):
        barrier.wait(timeout=2)
        return original_replace(src, dst, **kwargs)

    monkeypatch.setattr(octo_cache.os, "replace", simultaneous_replace)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(read, cache, item) for cache in caches]
        assert [future.result(timeout=3) for future in futures] == [BODY, BODY]
    assert calls == [item.upstream_url, item.upstream_url]
    assert destination(caches[0], item).read_bytes() == BODY
    assert [read(cache, item) for cache in caches] == [BODY, BODY]
    assert len(calls) == 2 and not list(caches[0].root.rglob("*.part"))


def test_seed_copy_close_before_publication_cleans_primary_and_preserves_legacy(tmp_path, monkeypatch):
    item = record()
    legacy = tmp_path / "legacy"
    source = seed_file(legacy, item)
    flushing, release = threading.Event(), threading.Event()
    events, original_fsync = [], octo_cache.os.fsync

    def held_fsync(descriptor):
        flushing.set()
        assert release.wait(2)
        return original_fsync(descriptor)

    monkeypatch.setattr(octo_cache.os, "fsync", held_fsync)
    cache = OctoCache(tmp_path / "public", seed_dirs=(legacy,), allow_download=False,
                      fetcher=no_upstream, on_event=events.append)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(read, cache, item)
        assert flushing.wait(2)
        cache.close()
        release.set()
        with pytest.raises(OctoCacheError) as caught:
            future.result(timeout=2)
        assert caught.value.code == "cache_closed"
    assert source.read_bytes() == BODY and not destination(cache, item).exists()
    assert events == [] and not list(cache.root.rglob("*.part"))


def test_seed_copy_deadline_is_checked_after_each_bounded_read(tmp_path, monkeypatch):
    item = record()
    legacy = tmp_path / "legacy"
    source = seed_file(legacy, item)
    clock = [0.0]
    monkeypatch.setattr(octo_cache.time, "monotonic", lambda: clock[0])
    cache = OctoCache(tmp_path / "public", seed_dirs=(legacy,), allow_download=False,
                      fetcher=no_upstream, total_timeout=1)
    original_open = cache._seed_file

    class SlowRead:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.stream.close()

        def fileno(self):
            return self.stream.fileno()

        def read(self, count):
            assert 0 < count <= octo_cache._CHUNK
            result = self.stream.read(count)
            clock[0] += 2
            return result

    def slow_open(*args):
        stream, info = original_open(*args)
        return SlowRead(stream), info

    monkeypatch.setattr(cache, "_seed_file", slow_open)
    with pytest.raises(OctoCacheError) as caught:
        read(cache, item)
    assert caught.value.code == "upstream_timeout"
    assert source.read_bytes() == BODY and not destination(cache, item).exists()
    assert not list(cache.root.rglob("*.part"))


def test_seed_modified_during_bounded_copy_is_not_published_or_deleted(tmp_path, monkeypatch):
    body = b"original" * 20_000
    item = record(body)
    legacy = tmp_path / "legacy"
    source = seed_file(legacy, item, body)
    cache = OctoCache(tmp_path / "public", seed_dirs=(legacy,), allow_download=False,
                      fetcher=no_upstream)
    original_open = cache._seed_file

    class MutatedRead:
        def __init__(self, stream):
            self.stream, self.changed = stream, False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.stream.close()

        def fileno(self):
            return self.stream.fileno()

        def read(self, count):
            assert 0 < count <= 64 * 1024
            block = self.stream.read(count)
            if not block and not self.changed:
                # Mutation happens after matching original bytes were copied;
                # checking the original file's stable stamp is still required.
                source.write_bytes(b"x" * len(body))
                self.changed = True
            return block

    def mutated_open(*args):
        stream, info = original_open(*args)
        return MutatedRead(stream), info

    monkeypatch.setattr(cache, "_seed_file", mutated_open)
    with pytest.raises(OctoCacheMiss):
        read(cache, item)
    assert source.read_bytes() == b"x" * len(body)
    assert not destination(cache, item).exists() and not list(cache.root.rglob("*.part"))


def test_seed_copies_obey_parallel_limit_and_close_cancels_waiting_copy(tmp_path, monkeypatch):
    first_item, next_item = record(), record(name="second_seed")
    legacy = tmp_path / "legacy"
    sources = [seed_file(legacy, item) for item in (first_item, next_item)]
    cache = OctoCache(tmp_path / "public", seed_dirs=(legacy,), allow_download=False,
                      fetcher=no_upstream, max_parallel=1)
    flushing, release = threading.Event(), threading.Event()
    opened, original_open, original_fsync = [], cache._seed_file, octo_cache.os.fsync

    def counted_open(*args):
        opened.append(args[-1].cache_key)
        return original_open(*args)

    def held_fsync(descriptor):
        flushing.set()
        assert release.wait(2)
        return original_fsync(descriptor)

    monkeypatch.setattr(cache, "_seed_file", counted_open)
    monkeypatch.setattr(octo_cache.os, "fsync", held_fsync)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(read, cache, first_item)
        assert flushing.wait(2)
        waiting = pool.submit(read, cache, next_item)
        cache.close()
        release.set()
        for future in (first, waiting):
            with pytest.raises(OctoCacheError) as caught:
                future.result(timeout=2)
            assert caught.value.code == "cache_closed"
    assert opened == [first_item.cache_key]
    assert all(path.read_bytes() == BODY for path in sources)
    assert not list(cache.root.rglob("*.bin")) and not list(cache.root.rglob("*.part"))


def test_seed_lookup_cannot_bypass_manifest_object_size_limit(tmp_path):
    item = record()
    legacy = tmp_path / "legacy"
    source = seed_file(legacy, item)
    cache = OctoCache(tmp_path / "public", seed_dirs=(legacy,), allow_download=False,
                      fetcher=no_upstream, max_object_bytes=len(BODY) - 1)
    with pytest.raises(ValueError, match="metadata"):
        read(cache, item)
    assert source.read_bytes() == BODY and not list(cache.root.iterdir())
