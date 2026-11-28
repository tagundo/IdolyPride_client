"""Real cache files are leased, not copied or treated as SDK-compatible bytes."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import FrozenInstanceError
import hashlib
import io
import os
from pathlib import Path
import threading
import time

import pytest

from idoly_local.octo_cache import OctoCache
from idoly_local.octo_manifest import Database, OctoManifest, OctoObject
from idoly_local.shared_resource_store import SharedResourceError, SharedResourceStore


def test_store_startup_reuses_validated_immutable_catalog_without_hashing_every_cache_key(tmp_path, monkeypatch):
    manifest, _records, _bodies = catalog()
    cache = OctoCache(tmp_path / "cache")
    monkeypatch.setattr(OctoObject, "cache_key", property(lambda _self: pytest.fail("Startup must not hash all catalog keys")))
    store = SharedResourceStore(manifest, cache)
    try:
        assert store._records is manifest.objects
        assert store.status()["prepared_files"] == 0 and store.status()["pending_preparations"] == 0
    finally:
        store.close(); cache.close()


def test_manifest_attribute_replacement_does_not_expand_the_stores_validated_snapshot(setup):
    from types import MappingProxyType
    store, _, records, calls = setup
    original = store._manifest.objects
    record = records["bundle"]
    replacement = OctoObject(record.kind, record.upload_version, "NEW999", record.generation,
        record.size, record.md5, "untrusted")
    store._manifest.objects = MappingProxyType({replacement.identity: replacement})
    try:
        with pytest.raises(SharedResourceError) as refused:
            store.prepare(route(replacement))
        assert refused.value.code == "not_found" and calls == []
        assert store._records is original
    finally:
        store._manifest.objects = original



ORIGIN = "https://d2ilil7yh5oi1v.cloudfront.net/solis-{v}-{type}/{o}?generation={g}&alt=media"
BUNDLE = b"original encrypted bundle\x00\xff"
RESOURCE = b"original ordinary resource\x00"


class Response(io.BytesIO):
    status = 200

    def __init__(self, body):
        super().__init__(body)
        self.headers = {"Content-Length": str(len(body))}


def catalog(platform="android", *, translated=False):
    version = 205051 if platform == "android" else 105051
    upload = 202050 if platform == "android" else 102050
    db = Database(revision=7, urlFormat=ORIGIN)
    for field, name, object_name, body in (
        ("assetBundleList", "bundle", "local_ko_123" if translated else "ABC123", BUNDLE),
        ("resourceList", "resource", "DEF456", RESOURCE),
    ):
        getattr(db, field).add(id=1, name=name, objectName=object_name, size=len(body),
                              md5=hashlib.md5(body, usedforsecurity=False).hexdigest(),
                              state=3, generation=11, uploadVersionId=upload)
    aliases = None
    if translated:
        target = OctoObject("assetbundle", upload, "local_ko_123", 11, len(BUNDLE),
                            hashlib.md5(BUNDLE, usedforsecurity=False).hexdigest(), "bundle")
        aliases = {("assetbundle", upload, "ABC123", 11): target}
    manifest = OctoManifest(db.SerializeToString(), aes_key=b"k" * 32, client_key="test-key",
        base_url="http://127.0.0.1:8080", aes_cbc=lambda _encrypt, _key, _iv, raw: raw,
        application_version=version, object_aliases=aliases)
    records = {row.name: row for row in manifest.objects.values()}
    bodies = {records["bundle"].upstream_url: BUNDLE, records["resource"].upstream_url: RESOURCE}
    return manifest, records, bodies


def route(record, *, object_name=None):
    return f"/octo/{record.upload_version}/{record.kind}/{object_name or record.object_name}/{record.generation}"


@pytest.fixture
def setup(tmp_path):
    manifest, records, bodies = catalog()
    calls = []
    def fetch(url, *, timeout):
        calls.append(url)
        return Response(bodies[url])
    cache = OctoCache(tmp_path / "cache", fetcher=fetch)
    store = SharedResourceStore(manifest, cache)
    try:
        yield store, cache, records, calls
    finally:
        store.close()
        cache.close()


@pytest.mark.parametrize("platform", ["android", "ios"])
def test_prepare_and_readers_share_the_one_original_inode_and_export_exact_provenance(tmp_path, platform):
    manifest, records, bodies = catalog(platform)
    calls = []
    cache = OctoCache(tmp_path / "cache", fetcher=lambda url, **_: (calls.append(url), Response(bodies[url]))[1])
    store = SharedResourceStore(manifest, cache)
    record = records["bundle"]
    try:
        assert store.acquire_cached(route(record)) is None and calls == []
        receipt = store.prepare(route(record))
        before = [(file, file.stat()) for file in cache.root.rglob("*.bin")]
        assert len(before) == 1 and len(calls) == 1
        assert receipt.platform == platform and receipt.manifest_revision == 7
        assert receipt.application_version == (205051 if platform == "android" else 105051)
        assert receipt.manifest_sha256 == manifest.archive_sha256
        assert receipt.md5 == record.md5 and receipt.size == record.size and receipt.generation == 11
        assert receipt.object_name == record.object_name and receipt.kind == "assetbundle"
        assert receipt.representation == "octo_raw_v1"
        with pytest.raises(FrozenInstanceError):
            receipt.size = 0
        with store.acquire_cached(route(record)) as lease:
            assert lease.receipt == receipt and lease.path_hint == before[0][0]
            first, second = lease.open_descriptor(), lease.open_descriptor()
            try:
                assert os.fstat(first).st_ino == os.fstat(second).st_ino == before[0][1].st_ino
                assert os.fstat(first).st_nlink == 1
                assert os.read(first, 3) == BUNDLE[:3]
                assert os.read(second, len(BUNDLE)) == BUNDLE
                assert os.read(first, len(BUNDLE)) == BUNDLE[3:]
            finally:
                os.close(first)
                os.close(second)
        after = list(cache.root.rglob("*.bin"))
        assert after == [before[0][0]] and after[0].stat().st_ino == before[0][1].st_ino
        assert after[0].stat().st_blocks == before[0][1].st_blocks and after[0].stat().st_nlink == 1
        assert calls == [record.upstream_url]
        assert store.status()["active_leases"] == 0 and not store.protected_cache_keys()
    finally:
        store.close()
        cache.close()


def test_cache_only_never_calls_cache_fill_or_hash_even_with_downloads_enabled(setup, monkeypatch):
    store, cache, records, calls = setup
    record = records["bundle"]
    store.prepare(route(record))
    monkeypatch.setattr(cache, "open_verified", lambda *_: pytest.fail("cache-only cannot fill or hash"))
    with store.acquire_cached(route(record)) as lease:
        with lease.reader() as reader:
            assert reader.read() == BUNDLE
    assert len(calls) == 1
    assert store.acquire_cached(route(records["resource"])) is None


@pytest.mark.parametrize("candidate", ["https://example.test/file", "file:///tmp/x", "../../secret",
    "/octo/202050/assetbundle/ABC123/11?x=1", "/octo/202050/assetbundle/%2e%2e/11",
    "/octo/202050/assetbundle/ABC123/12", "/octo/1/resources/ABC123/11", True, None])
def test_only_the_manifest_whitelist_can_select_a_file(setup, candidate):
    store, _, _, calls = setup
    for operation in (store.prepare, store.acquire_cached):
        with pytest.raises(SharedResourceError) as error:
            operation(candidate)
        assert error.value.code == "not_found"
        assert "example" not in str(error.value) and "secret" not in str(error.value)
    assert calls == []


def test_sdk_translation_alias_and_bulk_canonical_identity_use_one_file(tmp_path):
    manifest, records, bodies = catalog(translated=True)
    calls, local = [], []
    def prepared_source(record):
        local.append(record.cache_key)
        return io.BytesIO(bodies[record.upstream_url])
    cache = OctoCache(tmp_path / "cache", local_source=prepared_source,
        fetcher=lambda url, **_: (calls.append(url), Response(bodies[url]))[1])
    store = SharedResourceStore(manifest, cache)
    record = records["bundle"]
    try:
        first = store.prepare(route(record, object_name="ABC123"))
        second = store.prepare(route(record))
        assert first == second and first.object_name == "local_ko_123"
        assert calls == [] and local == [record.cache_key]
        assert len(list(cache.root.rglob("*.bin"))) == 1
        with store.acquire_cached(route(record, object_name="ABC123")) as lease:
            assert lease.requested_route == route(record, object_name="ABC123")
            assert lease.receipt.object_name == "local_ko_123"
            with lease.reader() as reader:
                assert reader.read() == BUNDLE
    finally:
        store.close()
        cache.close()


@pytest.mark.parametrize("damage", ["replace", "write", "unlink", "symlink", "hardlink", "writable"])
def test_a_changed_file_becomes_a_miss_without_fetch_or_cleanup(setup, tmp_path, damage):
    store, cache, records, calls = setup
    record = records["bundle"]
    store.prepare(route(record))
    path = cache.root / record.cache_key[:2] / (record.cache_key + ".bin")
    outside = tmp_path / "outside"
    outside.write_bytes(BUNDLE)
    if damage == "replace":
        replacement = tmp_path / "replacement"
        replacement.write_bytes(BUNDLE)
        replacement.chmod(0o400)
        os.replace(replacement, path)
    elif damage == "write":
        path.chmod(0o600)
        path.write_bytes(b"x" * len(BUNDLE))
        path.chmod(0o400)
    elif damage == "unlink": path.unlink()
    elif damage == "symlink":
        path.unlink()
        path.symlink_to(outside)
    elif damage == "hardlink": os.link(path, tmp_path / "second-name")
    elif damage == "writable": path.chmod(0o600)
    outside_before = outside.read_bytes(), outside.stat()
    assert store.acquire_cached(route(record)) is None
    assert store.acquire_cached(route(record)) is None
    assert len(calls) == 1 and store.status()["prepared_files"] == 0
    assert outside.read_bytes() == outside_before[0] and outside.stat().st_ino == outside_before[1].st_ino
    if damage != "unlink": assert path.exists()
    if damage == "symlink": assert path.is_symlink()


def test_replaced_shard_is_not_followed_or_removed(setup, tmp_path):
    store, cache, records, calls = setup
    record = records["bundle"]
    store.prepare(route(record))
    shard = cache.root / record.cache_key[:2]
    saved = tmp_path / "old-shard"
    shard.rename(saved)
    shard.symlink_to(saved, target_is_directory=True)
    assert store.acquire_cached(route(record)) is None
    assert shard.is_symlink() and (saved / (record.cache_key + ".bin")).read_bytes() == BUNDLE
    assert len(calls) == 1


def test_replaced_root_fails_closed_without_touching_its_replacement(setup, tmp_path):
    store, cache, records, calls = setup
    record = records["bundle"]
    store.prepare(route(record))
    saved = tmp_path / "original-root"
    cache.root.rename(saved)
    cache.root.mkdir()
    marker = cache.root / "do-not-touch"
    marker.write_bytes(b"replacement root")
    with pytest.raises(SharedResourceError) as error:
        store.acquire_cached(route(record))
    assert error.value.code == "store_unavailable"
    assert marker.read_bytes() == b"replacement root" and len(calls) == 1


def test_preparation_does_not_chmod_a_writable_legacy_file(setup):
    store, cache, records, _ = setup
    record = records["bundle"]
    with cache.open_verified(record): pass
    path = cache.root / record.cache_key[:2] / (record.cache_key + ".bin")
    path.chmod(0o600)
    before = path.stat()
    with pytest.raises(SharedResourceError) as error:
        store.prepare(route(record))
    assert error.value.code == "file_not_immutable"
    assert path.stat().st_mode == before.st_mode and path.stat().st_ino == before.st_ino
    assert store.acquire_cached(route(record)) is None


def test_atomic_replacement_after_acquisition_never_redirects_a_reader_to_new_bytes(setup, tmp_path):
    store, cache, records, _ = setup
    record = records["bundle"]
    store.prepare(route(record))
    lease = store.acquire_cached(route(record))
    native = lease.open_descriptor()
    replacement = tmp_path / "replacement"
    replacement.write_bytes(b"x" * len(BUNDLE))
    replacement.chmod(0o400)
    os.replace(replacement, lease.path_hint)
    try:
        with pytest.raises(SharedResourceError) as error:
            lease.open_descriptor()
        assert error.value.code == "file_changed"
        assert os.read(native, len(BUNDLE)) == BUNDLE
    finally:
        lease.close()
        os.close(native)


def test_detached_native_reader_outlives_store_close_and_is_transferred_once(setup):
    store, cache, records, _ = setup
    record = records["bundle"]
    store.prepare(route(record))
    lease = store.acquire_cached(route(record))
    token, path = lease.token, lease.path_hint
    descriptor = lease.detach_descriptor()
    assert not store.release(token) and not store.protected_cache_keys()
    store.close()
    try:
        assert os.read(descriptor, len(BUNDLE)) == BUNDLE
        with pytest.raises(SharedResourceError) as error:
            lease.detach_descriptor()
        assert error.value.code == "lease_closed"
        assert path.exists()
        with cache.open_verified(record) as stream:
            assert stream.read() == BUNDLE
    finally:
        os.close(descriptor)


def test_store_close_releases_its_leases_but_does_not_own_open_consumer_descriptors(setup):
    store, _, records, _ = setup
    record = records["bundle"]
    store.prepare(route(record))
    lease = store.acquire_cached(route(record))
    descriptor = lease.open_descriptor()
    store.close()
    try:
        assert os.read(descriptor, len(BUNDLE)) == BUNDLE
        assert store.status()["active_leases"] == 0
        with pytest.raises(SharedResourceError): lease.open_descriptor()
        with pytest.raises(SharedResourceError): store.prepare(route(record))
        with pytest.raises(SharedResourceError): store.acquire_cached(route(record))
    finally:
        os.close(descriptor)


def test_lru_and_lease_limits_discard_only_receipts_not_files(setup):
    _, cache, records, calls = setup
    manifest, _, _ = catalog()
    store = SharedResourceStore(manifest, cache, max_prepared=1, max_leases=1)
    a, b = records["bundle"], records["resource"]
    try:
        store.prepare(route(a))
        first = store.acquire_cached(route(a))
        store.prepare(route(b))
        assert store.acquire_cached(route(a)) is None
        assert store.protected_cache_keys() == frozenset((a.cache_key,))
        with pytest.raises(SharedResourceError) as error: store.acquire_cached(route(b))
        assert error.value.code == "capacity"
        with first.reader() as reader: assert reader.read() == BUNDLE
        assert store.release(first.token) and not store.release(first.token)
        with store.acquire_cached(route(b)) as lease:
            with lease.reader() as reader: assert reader.read() == RESOURCE
        assert len(list(cache.root.rglob("*.bin"))) == 2 and len(calls) == 2
    finally:
        store.close()


@pytest.mark.parametrize("cancel", [False, True])
def test_close_or_cancel_during_shared_fill_refuses_handoff_but_keeps_verified_file(tmp_path, cancel):
    manifest, records, bodies = catalog()
    entered, proceed, event = threading.Event(), threading.Event(), threading.Event()
    calls = []
    def fetch(url, **_):
        calls.append(url)
        entered.set()
        assert proceed.wait(3)
        return Response(bodies[url])
    cache = OctoCache(tmp_path / "cache", fetcher=fetch)
    store = SharedResourceStore(manifest, cache, max_preparations=1)
    record = records["bundle"]
    try:
        with ThreadPoolExecutor(max_workers=1) as workers:
            result = workers.submit(store.prepare, route(record), cancel_event=event)
            assert entered.wait(3)
            with pytest.raises(SharedResourceError) as full:
                store.prepare(route(records["resource"]))
            assert full.value.code == "capacity"
            if cancel: event.set()
            else: store.close()
            proceed.set()
            with pytest.raises(SharedResourceError) as failed: result.result(timeout=3)
            assert failed.value.code == ("cancelled" if cancel else "store_closed")
        assert store.status()["prepared_files"] == store.status()["pending_preparations"] == 0
        assert len(list(cache.root.rglob("*.bin"))) == 1
        with cache.open_verified(record) as source: assert source.read() == BUNDLE
        assert len(calls) == 1
    finally:
        proceed.set()
        store.close()
        cache.close()


def test_pre_cancelled_requests_and_invalid_cancellation_do_not_touch_network(setup):
    store, _, records, calls = setup
    event = threading.Event(); event.set()
    for operation in (store.prepare, store.acquire_cached):
        with pytest.raises(SharedResourceError) as error:
            operation(route(records["bundle"]), cancel_event=event)
        assert error.value.code == "cancelled"
        with pytest.raises(TypeError): operation(route(records["bundle"]), cancel_event=True)
    assert calls == []


@pytest.mark.parametrize("size,md5", [(None, "0" * 32), (len(BUNDLE), None),
    (True, "0" * 32), (0, "0" * 32), (len(BUNDLE) + 1, "0" * 32),
    (len(BUNDLE), "0" * 32), (len(BUNDLE), "A" * 32), (len(BUNDLE), b"x" * 16)])
def test_sdk_expectation_pair_must_match_before_any_preparation_or_cached_file_io(setup, monkeypatch, size, md5):
    store, _, records, calls = setup
    record = records["bundle"]
    store.prepare(route(record))
    monkeypatch.setattr(store, "_open_pinned", lambda *_: pytest.fail("stale SDK metadata must not open a file"))
    for operation in (store.prepare, store.acquire_cached):
        with pytest.raises(SharedResourceError) as error:
            operation(route(record), expected_size=size, expected_md5=md5)
        assert error.value.code == "not_found"
    assert len(calls) == 1


def test_matching_sdk_expectations_keep_the_same_raw_canonical_file(setup):
    store, _, records, calls = setup
    record = records["bundle"]
    receipt = store.prepare(route(record), expected_size=record.size, expected_md5=record.md5)
    with store.acquire_cached(route(record), expected_size=record.size, expected_md5=record.md5) as lease:
        assert lease.receipt == receipt
        with lease.reader() as reader:
            assert reader.read() == BUNDLE
    assert len(calls) == 1


def test_simultaneous_preparation_and_parallel_readers_download_and_store_only_once(tmp_path):
    manifest, records, bodies = catalog()
    entered, proceed = threading.Event(), threading.Event()
    calls = []
    def fetch(url, **_):
        calls.append(url)
        entered.set()
        assert proceed.wait(3)
        return Response(bodies[url])
    cache = OctoCache(tmp_path / "cache", fetcher=fetch)
    store = SharedResourceStore(manifest, cache)
    record = records["bundle"]
    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            first = workers.submit(store.prepare, route(record))
            assert entered.wait(3)
            second = workers.submit(store.prepare, route(record))
            deadline = time.monotonic() + 3
            while store.status()["pending_preparations"] != 2 and time.monotonic() < deadline:
                time.sleep(0.005)
            assert store.status()["pending_preparations"] == 2
            proceed.set()
            assert first.result(timeout=3) == second.result(timeout=3)
        def consume(_):
            with store.acquire_cached(route(record)) as lease:
                with lease.reader() as reader:
                    return lease.receipt.identity.inode, reader.read()
        with ThreadPoolExecutor(max_workers=8) as workers:
            results = list(workers.map(consume, range(16)))
        assert len({inode for inode, _ in results}) == 1
        assert all(body == BUNDLE for _, body in results)
        assert calls == [record.upstream_url]
        assert len(list(cache.root.rglob("*.bin"))) == 1
        assert store.status()["active_leases"] == store.status()["pending_acquisitions"] == 0
    finally:
        proceed.set()
        store.close(); cache.close()


@pytest.mark.parametrize("cancel", [False, True])
def test_close_or_cancel_during_file_open_cannot_publish_or_leak_a_lease(setup, monkeypatch, cancel):
    store, _, records, _ = setup
    record = records["bundle"]
    store.prepare(route(record))
    original = store._open_pinned
    entered, proceed, event = threading.Event(), threading.Event(), threading.Event()
    descriptors = []
    def held(receipt):
        descriptor = original(receipt)
        descriptors.append(descriptor)
        entered.set()
        assert proceed.wait(3)
        return descriptor
    monkeypatch.setattr(store, "_open_pinned", held)
    with ThreadPoolExecutor(max_workers=1) as workers:
        result = workers.submit(store.acquire_cached, route(record), cancel_event=event)
        try:
            assert entered.wait(3)
            if cancel: event.set()
            else: store.close()
        finally:
            proceed.set()
        with pytest.raises(SharedResourceError) as error: result.result(timeout=3)
        assert error.value.code == ("cancelled" if cancel else "store_closed")
    assert len(descriptors) == 1
    with pytest.raises(OSError): os.fstat(descriptors[0])
    assert store.status()["active_leases"] == store.status()["pending_acquisitions"] == 0


def test_pending_file_acquisition_reserves_the_lease_limit_before_handoff(setup, monkeypatch):
    _, cache, records, _ = setup
    manifest, _, _ = catalog()
    store = SharedResourceStore(manifest, cache, max_leases=1)
    record = records["bundle"]
    store.prepare(route(record))
    original = store._open_pinned
    entered, proceed = threading.Event(), threading.Event()
    def held(receipt):
        descriptor = original(receipt)
        entered.set()
        assert proceed.wait(3)
        return descriptor
    monkeypatch.setattr(store, "_open_pinned", held)
    try:
        with ThreadPoolExecutor(max_workers=1) as workers:
            first = workers.submit(store.acquire_cached, route(record))
            try:
                assert entered.wait(3)
                with pytest.raises(SharedResourceError) as error: store.acquire_cached(route(record))
                assert error.value.code == "capacity"
            finally:
                proceed.set()
            lease = first.result(timeout=3)
        assert store.status()["active_leases"] == 1
        lease.close()
        assert store.status()["active_leases"] == store.status()["pending_acquisitions"] == 0
    finally:
        proceed.set(); store.close()


def test_bad_upstream_bytes_never_create_a_prepared_receipt_or_lease(tmp_path):
    manifest, records, _ = catalog()
    cache = OctoCache(tmp_path / "cache", fetcher=lambda *_args, **_kw: Response(b"x" * len(BUNDLE)))
    store = SharedResourceStore(manifest, cache)
    try:
        with pytest.raises(SharedResourceError) as error:
            store.prepare(route(records["bundle"]))
        assert error.value.code == "cache_unavailable"
        assert store.acquire_cached(route(records["bundle"])) is None
        assert not list(cache.root.rglob("*.bin")) and not list(cache.root.rglob("*.part"))
        assert store.status()["pending_preparations"] == 0
    finally:
        store.close(); cache.close()


def test_preparation_detects_atomic_replacement_during_verified_handoff(setup, tmp_path, monkeypatch):
    store, cache, records, _ = setup
    record = records["bundle"]
    original = cache.open_verified
    @contextmanager
    def swapped(item):
        with original(item) as stream:
            replacement = tmp_path / "replacement"
            replacement.write_bytes(BUNDLE)
            replacement.chmod(0o400)
            os.replace(replacement, cache.root / item.cache_key[:2] / (item.cache_key + ".bin"))
            yield stream
    monkeypatch.setattr(cache, "open_verified", swapped)
    with pytest.raises(SharedResourceError) as error: store.prepare(route(record))
    assert error.value.code == "file_changed"
    assert store.acquire_cached(route(record)) is None and store.status()["prepared_files"] == 0


@pytest.mark.parametrize("limits", [{"max_leases": True}, {"max_leases": 0}, {"max_prepared": 100001},
    {"max_preparations": 65}, {"max_prepared": "10"}])
def test_invalid_limits_are_rejected_before_work(setup, limits):
    _, cache, _, calls = setup
    manifest, _, _ = catalog()
    with pytest.raises(ValueError): SharedResourceStore(manifest, cache, **limits)
    assert calls == []
