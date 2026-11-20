"""SDK-named symlink metadata never copies or hardlinks verified payloads."""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import stat
import threading

import pytest

from idoly_local.octo_cache import OctoCache
from idoly_local.shared_resource_store import SharedResourceStore
from idoly_local.shared_resource_views import SharedResourceViewError, SharedResourceViews
from idoly_local import shared_resource_views as module
from test_shared_resource_store import BUNDLE, RESOURCE, Response, catalog, route


@pytest.fixture
def setup(tmp_path):
    manifest, records, bodies = catalog()
    calls = []
    cache = OctoCache(tmp_path / "cache", fetcher=lambda url, **_: (calls.append(url), Response(bodies[url]))[1])
    store = SharedResourceStore(manifest, cache)
    for record in records.values():
        store.prepare(route(record))
    private = tmp_path / "app-private"
    private.mkdir(mode=0o755)  # Trusted app root need not itself be 0700.
    views = SharedResourceViews(private)
    try:
        yield views, store, cache, records, calls
    finally:
        store.close()
        cache.close()
        try:
            views.cleanup(quiescent=True)
        except SharedResourceViewError:
            pass  # Attack fixtures deliberately leave foreign metadata intact.


def sdk(record, extension=""):
    return ("A" if record.kind == "assetbundle" else "R") + record.object_name, record.md5 + extension


@pytest.mark.parametrize("name,extension,body", [("bundle", "", BUNDLE), ("resource", ".acb", RESOURCE),
    ("resource", ".mp4", RESOURCE), ("resource", ".abcdefghijklmnop", RESOURCE)])
def test_sdk_extension_view_follows_the_original_inode_without_data_copy_or_hardlink(setup, name, extension, body):
    views, store, cache, records, calls = setup
    record = records[name]
    with store.acquire_cached(route(record), expected_size=record.size, expected_md5=record.md5) as lease:
        original = lease.path_hint.stat()
        bucket, filename = sdk(record, extension)
        view = views.materialize(lease, bucket, filename)
        path = Path(view.path)
        assert path.name == filename and path.parent.name == bucket
        assert path.is_symlink() and os.readlink(path) == str(lease.path_hint)
        assert path.read_bytes() == body
        assert path.stat().st_ino == original.st_ino and path.stat().st_nlink == original.st_nlink == 1
        assert path.stat().st_blocks == original.st_blocks
        assert view.representation == "octo_raw_v1" and view.md5 == record.md5 and view.cache_key == record.cache_key
        assert stat.S_IMODE(views.root.stat().st_mode) == stat.S_IMODE(path.parent.stat().st_mode) == 0o700
        assert views.root.stat().st_uid == path.parent.stat().st_uid == os.geteuid()
        first = path.lstat().st_ino
        assert views.materialize(lease, bucket, filename) == view and path.lstat().st_ino == first
    assert len(calls) == 2 and len(list(cache.root.rglob("*.bin"))) == 2
    assert not any(stat.S_ISREG(path.lstat().st_mode) for path in views.root.rglob("*"))
    assert not any(path.name.startswith(".probe-") for path in views.root.iterdir())


def test_views_persist_after_lease_and_store_close_until_explicit_quiescent_cleanup(setup):
    views, store, cache, records, _ = setup
    record = records["resource"]
    lease = store.acquire_cached(route(record))
    target = lease.path_hint
    view = views.materialize(lease, *sdk(record, ".wav"))
    lease.close(); store.close()
    assert Path(view.path).read_bytes() == RESOURCE and target.exists()
    with pytest.raises(SharedResourceViewError) as refused:
        views.cleanup()
    assert refused.value.code == "not_quiescent" and Path(view.path).is_symlink()
    result = views.cleanup(quiescent=True)
    assert result == {"removed_links": 1, "removed_buckets": 1, "root_removed": True}
    assert not views.root.exists() and target.read_bytes() == RESOURCE and target.stat().st_nlink == 1
    assert len(list(cache.root.rglob("*.bin"))) == 2
    assert views.cleanup(quiescent=True)["removed_links"] == 0


@pytest.mark.parametrize("bucket,filename", [("RABC123", "GOOD.acb"), ("R../abc", "GOOD.acb"),
    ("rDEF456", "GOOD.acb"), ("RDEF456", "0" * 32 + ".acb"), ("RDEF456", "GOOD.ACB"),
    ("RDEF456", "GOOD.tar.gz"), ("RDEF456", "GOOD.abcdefghijklmnopq"),
    ("RDEF456", "../GOOD.acb"), ("RDEF456", "GOOD/acb"),
    ("RDEF456", "GOOD.\u202eacb"), (True, "GOOD.acb"), ("RDEF456", None)])
def test_sdk_bucket_md5_and_single_lowercase_extension_are_checked_before_io(setup, monkeypatch, bucket, filename):
    views, store, _, records, _ = setup
    record = records["resource"]
    if isinstance(filename, str): filename = filename.replace("GOOD", record.md5)
    lease = store.acquire_cached(route(record))
    monkeypatch.setattr(views, "_open_root", lambda: pytest.fail("invalid SDK names must not touch view storage"))
    with pytest.raises(SharedResourceViewError) as error:
        views.materialize(lease, bucket, filename)
    assert error.value.code == "invalid_view" and views.status()["owned_views"] == 0
    assert not list(views.root.iterdir())


def test_asset_bundles_cannot_request_a_media_extension(setup):
    views, store, _, records, _ = setup
    record = records["bundle"]
    with store.acquire_cached(route(record)) as lease:
        with pytest.raises(SharedResourceViewError) as error:
            views.materialize(lease, *sdk(record, ".unity3d"))
        assert error.value.code == "invalid_view"


def test_requested_sdk_alias_is_validated_separately_from_the_long_canonical_name(tmp_path):
    manifest, records, bodies = catalog(translated=True)
    cache = OctoCache(tmp_path / "cache", local_source=lambda item: Response(bodies[item.upstream_url]))
    store = SharedResourceStore(manifest, cache)
    private = tmp_path / "private"; private.mkdir()
    views = SharedResourceViews(private)
    record = records["bundle"]
    try:
        request = route(record, object_name="ABC123")
        store.prepare(request)
        with store.acquire_cached(request) as lease:
            assert lease.receipt.object_name == "local_ko_123"
            view = views.materialize(lease, "AABC123", record.md5)
            assert Path(view.path).read_bytes() == BUNDLE
            assert os.readlink(view.path) == str(lease.path_hint)
        with store.acquire_cached(route(record)) as canonical:
            with pytest.raises(SharedResourceViewError) as error:
                views.materialize(canonical, "AABC123", record.md5)
            assert error.value.code == "invalid_view"
    finally:
        views.cleanup(quiescent=True); store.close(); cache.close()


def test_foreign_alias_cannot_be_claimed_by_a_stale_request_identity(setup):
    views, store, _, records, _ = setup
    record = records["resource"]
    with store.acquire_cached(route(record)) as lease:
        # Even a broken trusted coordinator cannot turn an unknown SDK alias
        # into a valid view merely by supplying a syntactically valid bucket.
        lease._requested_route = route(record, object_name="ZZZ999")
        with pytest.raises(SharedResourceViewError) as error:
            views.materialize(lease, "RZZZ999", record.md5 + ".mp4")
        assert error.value.code == "invalid_view"


@pytest.mark.parametrize("foreign", ["file", "same-target-link", "outside-link", "directory"])
def test_existing_unowned_entries_are_never_adopted_overwritten_or_cleaned(setup, tmp_path, foreign):
    views, store, _, records, _ = setup
    record = records["resource"]
    lease = store.acquire_cached(route(record))
    good = views.materialize(lease, *sdk(record, ".wav"))
    entry = Path(good.path).with_suffix(".mp4")
    outside = tmp_path / "outside"; outside.write_bytes(b"foreign payload")
    if foreign == "file": entry.write_bytes(b"foreign entry")
    elif foreign == "same-target-link": entry.symlink_to(lease.path_hint)
    elif foreign == "outside-link": entry.symlink_to(outside)
    else:
        entry.mkdir(); (entry / "marker").write_bytes(b"foreign entry")
    identity = entry.lstat()
    with pytest.raises(SharedResourceViewError) as error:
        views.materialize(lease, *sdk(record, ".mp4"))
    assert error.value.code == "view_conflict" and entry.lstat().st_ino == identity.st_ino
    with pytest.raises(SharedResourceViewError) as error: views.cleanup(quiescent=True)
    assert error.value.code == "view_conflict" and Path(good.path).is_symlink()
    assert outside.read_bytes() == b"foreign payload" and entry.lstat().st_ino == identity.st_ino
    if foreign == "file": assert entry.read_bytes() == b"foreign entry"
    if foreign == "directory": assert (entry / "marker").read_bytes() == b"foreign entry"


@pytest.mark.parametrize("symlink", [False, True])
def test_unowned_or_symlink_bucket_parent_is_rejected(setup, tmp_path, symlink):
    views, store, _, records, _ = setup
    record = records["resource"]
    outside = tmp_path / "outside"; outside.mkdir()
    marker = outside / "marker"; marker.write_bytes(b"outside")
    bucket, filename = sdk(record, ".acb")
    parent = views.root / bucket
    if symlink: parent.symlink_to(outside, target_is_directory=True)
    else: parent.mkdir(mode=0o700)
    with store.acquire_cached(route(record)) as lease:
        with pytest.raises(SharedResourceViewError) as error:
            views.materialize(lease, bucket, filename)
        assert error.value.code == "view_conflict"
    assert marker.read_bytes() == b"outside" and not (outside / filename).exists()
    assert parent.exists() and parent.is_symlink() is symlink


def test_replaced_owned_symlink_is_not_silently_reclaimed(setup):
    views, store, _, records, _ = setup
    record = records["resource"]
    with store.acquire_cached(route(record)) as lease:
        first = views.materialize(lease, *sdk(record, ".acb"))
        path = Path(first.path)
        path.unlink(); path.symlink_to(lease.path_hint)
        replacement = path.lstat().st_ino
        with pytest.raises(SharedResourceViewError) as error: views.materialize(lease, *sdk(record, ".acb"))
        assert error.value.code == "view_conflict" and path.lstat().st_ino == replacement
        assert path.read_bytes() == RESOURCE


def test_replaced_owned_bucket_symlink_cannot_redirect_new_views(setup, tmp_path):
    views, store, _, records, _ = setup
    record = records["resource"]
    with store.acquire_cached(route(record)) as lease:
        first = views.materialize(lease, *sdk(record, ".acb"))
        parent = Path(first.path).parent
        saved = tmp_path / "saved-bucket"; parent.rename(saved)
        parent.symlink_to(saved, target_is_directory=True)
        with pytest.raises(SharedResourceViewError) as error: views.materialize(lease, *sdk(record, ".wav"))
        assert error.value.code == "view_conflict" and parent.is_symlink()
        assert not (saved / (record.md5 + ".wav")).exists()


def test_unsupported_symlink_filesystem_probe_removes_only_owned_zero_byte_metadata(tmp_path, monkeypatch):
    private = tmp_path / "private"; private.mkdir()
    outside = tmp_path / "payload"; outside.write_bytes(b"not a probe")
    def unsupported(*_args, **_kwargs): raise OSError("no symlink support")
    monkeypatch.setattr(module.os, "symlink", unsupported)
    with pytest.raises(SharedResourceViewError) as error: SharedResourceViews(private)
    assert error.value.code == "view_unavailable"
    assert not list(private.iterdir()) and outside.read_bytes() == b"not a probe"


def test_trusted_private_os_alias_resolves_once_while_children_remain_private(tmp_path):
    private = tmp_path / "real-private"; private.mkdir(mode=0o755)
    alias = tmp_path / "os-alias"; alias.symlink_to(private, target_is_directory=True)
    views = SharedResourceViews(alias)
    assert views.root.parent == private.resolve() and stat.S_IMODE(views.root.stat().st_mode) == 0o700
    assert not list(views.root.iterdir())
    views.cleanup(quiescent=True)
    assert alias.is_symlink() and private.is_dir()


@pytest.mark.parametrize("mode", [0o755, 0o777])
def test_changed_session_permissions_are_not_accepted_as_private(setup, mode):
    views, store, _, records, _ = setup
    record = records["resource"]
    views.root.chmod(mode)
    try:
        with store.acquire_cached(route(record)) as lease:
            with pytest.raises(SharedResourceViewError) as error:
                views.materialize(lease, *sdk(record, ".mp4"))
            assert error.value.code == "view_conflict"
        assert not list(views.root.iterdir())
    finally:
        views.root.chmod(0o700)


def test_canonical_replacement_during_materialization_fails_without_publishing_a_view(setup, tmp_path, monkeypatch):
    views, store, _, records, calls = setup
    record = records["resource"]
    lease = store.acquire_cached(route(record))
    original = module.os.symlink
    def replaced(target, name, **kwargs):
        original(target, name, **kwargs)
        replacement = tmp_path / "replacement"; replacement.write_bytes(RESOURCE); replacement.chmod(0o400)
        os.replace(replacement, lease.path_hint)
    monkeypatch.setattr(module.os, "symlink", replaced)
    with pytest.raises(SharedResourceViewError) as error:
        views.materialize(lease, *sdk(record, ".mp4"))
    assert error.value.code in ("view_conflict", "lease_unavailable")
    assert views.status()["owned_views"] == views.status()["owned_buckets"] == 0
    assert not list(views.root.iterdir()) and lease.path_hint.read_bytes() == RESOURCE
    assert len(calls) == 2


def test_pre_cancelled_and_mid_creation_cancel_leave_no_new_view_or_payload_changes(setup, monkeypatch):
    views, store, _, records, calls = setup
    record = records["resource"]
    lease = store.acquire_cached(route(record))
    event = threading.Event(); event.set()
    with pytest.raises(SharedResourceViewError) as error:
        views.materialize(lease, *sdk(record, ".mp4"), cancel_event=event)
    assert error.value.code == "cancelled" and not list(views.root.iterdir())
    event.clear()
    original = module.os.symlink
    def cancel_after_create(*args, **kwargs):
        original(*args, **kwargs); event.set()
    monkeypatch.setattr(module.os, "symlink", cancel_after_create)
    with pytest.raises(SharedResourceViewError) as error:
        views.materialize(lease, *sdk(record, ".mp4"), cancel_event=event)
    assert error.value.code == "cancelled" and not list(views.root.iterdir())
    assert views.status()["owned_views"] == views.status()["owned_buckets"] == 0
    assert lease.path_hint.read_bytes() == RESOURCE and len(calls) == 2


def test_cancelled_reuse_does_not_remove_an_existing_async_reader_path(setup):
    views, store, _, records, _ = setup
    record = records["resource"]
    with store.acquire_cached(route(record)) as lease:
        view = views.materialize(lease, *sdk(record, ".mp4"))
        event = threading.Event(); event.set()
        with pytest.raises(SharedResourceViewError): views.materialize(lease, *sdk(record, ".mp4"), cancel_event=event)
        assert Path(view.path).read_bytes() == RESOURCE and views.status()["owned_views"] == 1


def test_concurrent_materialization_has_one_metadata_link_and_one_payload(setup):
    views, store, cache, records, calls = setup
    record = records["resource"]
    with store.acquire_cached(route(record)) as lease:
        def one(_): return views.materialize(lease, *sdk(record, ".ogg"))
        with ThreadPoolExecutor(max_workers=8) as workers:
            results = list(workers.map(one, range(24)))
        assert len({view.path for view in results}) == 1 and views.status()["owned_views"] == 1
        path = Path(results[0].path)
        assert path.stat().st_nlink == 1 and path.read_bytes() == RESOURCE
        assert len(list(cache.root.rglob("*.bin"))) == 2 and len(calls) == 2


def test_view_limit_does_not_remove_or_redirect_a_previous_view(setup, tmp_path):
    _, store, _, records, _ = setup
    private = tmp_path / "limited-private"; private.mkdir()
    views = SharedResourceViews(private, max_views=1)
    record = records["resource"]
    try:
        with store.acquire_cached(route(record)) as lease:
            first = views.materialize(lease, *sdk(record, ".wav"))
            with pytest.raises(SharedResourceViewError) as error: views.materialize(lease, *sdk(record, ".mp4"))
            assert error.value.code == "capacity" and Path(first.path).read_bytes() == RESOURCE
            assert not Path(first.path).with_suffix(".mp4").exists()
    finally:
        views.cleanup(quiescent=True)


def test_new_sessions_do_not_adopt_each_others_existing_metadata(setup):
    views, _, _, _, _ = setup
    other = SharedResourceViews(views.root.parent)
    assert other.root != views.root and views.root.exists()
    other.cleanup(quiescent=True)
    assert views.root.exists()


@pytest.mark.parametrize("assertion", [False, None, 1, "yes"])
def test_cleanup_requires_an_explicit_boolean_quiescent_lifecycle_assertion(setup, assertion):
    views, _, _, _, _ = setup
    with pytest.raises(SharedResourceViewError) as error: views.cleanup(quiescent=assertion)
    assert error.value.code == "not_quiescent" and views.root.exists()
