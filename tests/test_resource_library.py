from __future__ import annotations

import hashlib
import io
import json
from contextlib import contextmanager
from pathlib import Path
import threading
import time
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from idoly_local.octo_cache import OctoCache
from idoly_local.octo_manifest import Database, OctoManifest
from idoly_local.resource_library import ResourceLibrary, ResourceLibraryError


URL = 'https://d2ilil7yh5oi1v.cloudfront.net/solis-{v}-{type}/{o}?generation={g}&alt=media'
AES = lambda encrypt, key, iv, raw: raw  # No encryption operation is needed by this metadata fixture.


def catalog(root, platform='android', count=3):
    ios = platform == 'ios'
    db = Database(revision=1159 if ios else 1087, urlFormat=URL)
    bodies = {}
    for kind, rows in [('assetbundle', db.assetBundleList), ('resources', db.resourceList)]:
        for index in range(count):
            body = f'original raw {platform} {kind} {index}'.encode()
            item = rows.add(id=index+1, name=f'{kind}_{index}', size=len(body), state=1,
                md5=hashlib.md5(body).hexdigest(), objectName=f'object_{kind}_{index}',
                generation=index+1000, uploadVersionId=101050 if ios else 202050)
            bodies[(kind, item.objectName)] = body
    raw = db.SerializeToString()
    directory = root / ('public-octo-ios' if ios else 'public-octo')
    directory.mkdir()
    settings = dict(schema=1, application_id=212, application_version=105051 if ios else 205051,
        revision=db.revision, manifest_sha256=hashlib.sha256(raw).hexdigest(),
        aes_key_hex='a'*64, client_key='synthetic-public-key')
    (directory/'settings.json').write_text(json.dumps(settings))
    (directory/'manifest.pb').write_bytes(raw)
    manifest = OctoManifest(raw, aes_key=bytes.fromhex(settings['aes_key_hex']),
        client_key=settings['client_key'], base_url='http://127.0.0.1:8080', aes_cbc=AES,
        application_version=settings['application_version'])
    payloads = {record.upstream_url:bodies[(record.kind, record.object_name)]
                for record in manifest.objects.values()}
    return manifest, payloads


class Response(io.BytesIO):
    status = 200
    def __init__(self, raw):
        super().__init__(raw)
        self.headers = {'Content-Length':str(len(raw))}


def complete(library):
    deadline = time.monotonic()+3
    while time.monotonic()<deadline:
        job = library.status()['job']
        if job['state'] in {'completed', 'partial', 'failed', 'cancelled'}:
            return job
        time.sleep(.005)
    raise AssertionError('Bounded test job did not finish')


@pytest.fixture
def library_case(tmp_path):
    manifest, payloads = catalog(tmp_path)
    calls=[]
    def fetch(url, *, timeout):
        calls.append(url)
        return Response(payloads[url])
    library = ResourceLibrary.from_data_dir(tmp_path, aes_cbc=AES, fetcher=fetch,
                                            active_gateway=SimpleNamespace(manifest=manifest))
    yield library, manifest, payloads, calls
    library.close()


def test_active_catalog_reused_lazy_other_platform_and_status_never_scans_cache(tmp_path, monkeypatch):
    import idoly_local.resource_library as module
    active, _ = catalog(tmp_path)
    catalog(tmp_path, 'ios')
    loaded=[]; original=module.load_octo_archive
    def load(directory, *, platform):
        loaded.append(platform)
        return original(directory, platform=platform)
    monkeypatch.setattr(module, 'load_octo_archive', load)
    library = ResourceLibrary.from_data_dir(tmp_path, aes_cbc=AES,
                                             active_gateway=SimpleNamespace(manifest=active))
    assert active.archive_sha256==hashlib.sha256((tmp_path/'public-octo/manifest.pb').read_bytes()).hexdigest()
    assert library._catalogs['android'].manifest is active
    monkeypatch.setattr(OctoCache, 'open_verified', lambda *a:pytest.fail('Status must not scan files'))
    for _ in range(4):
        value=library.status()['catalogs']
        assert value['android']['object_count']==6
        assert value['ios']['available'] and not value['ios']['loaded'] and value['ios']['object_count'] is None
    assert loaded==['android']
    assert library.catalog_summary('ios')['ios']['object_count']==6
    assert loaded==['android','ios']
    library.close()


def test_explicit_bulk_download_raw_cache_and_resume_without_more_network(library_case):
    library, manifest, payloads, calls = library_case
    assert calls==[] and library.status()['job'] is None
    library.start_download('android')
    done=complete(library)
    assert done['state']=='completed' and done['verified_files']==done['downloaded_files']==6
    assert done['received_bytes']==sum(map(len,payloads.values())) and len(calls)==6
    assert done['resume_mode']=='verified_objects' and done['partial_byte_resume'] is False
    for record in manifest.objects.values():
        path=library.root/'octo-cache'/record.cache_key[:2]/(record.cache_key+'.bin')
        assert path.read_bytes()==payloads[record.upstream_url]
    library.start_download('android')
    again=complete(library)
    assert again['verified_files']==again['cache_hit_files']==6 and again['received_bytes']==0
    assert len(calls)==6 and not list(library.root.rglob('*.part'))


def test_two_worker_bound_and_failed_digest_never_published(tmp_path):
    manifest, payloads=catalog(tmp_path, count=8)
    lock=threading.Lock();active=peak=0
    class Measured(Response):
        def __init__(self, raw):
            nonlocal active,peak
            super().__init__(raw)
            with lock:active+=1;peak=max(peak,active)
        def read(self,count=-1):
            time.sleep(.003)
            return super().read(count)
        def close(self):
            nonlocal active
            if not self.closed:
                with lock:active-=1
            super().close()
    bad=next(iter(payloads))
    def fetch(url, *, timeout):return Measured(b'x'*len(payloads[url]) if url==bad else payloads[url])
    library=ResourceLibrary(tmp_path, {'android':manifest}, fetcher=fetch, max_workers=2)
    library.start_download('android')
    done=complete(library)
    assert peak<=2 and done['state']=='partial' and done['failed_files']==1
    assert done['error_code']=='upstream_digest' and done['verified_files']==15
    record=next(record for record in manifest.objects.values() if record.upstream_url==bad)
    assert not (tmp_path/'octo-cache'/record.cache_key[:2]/(record.cache_key+'.bin')).exists()
    library.close()


@pytest.mark.parametrize('parallelism', [1, 2, 4, 8])
def test_selected_parallel_downloads_really_overlap_and_remain_bounded(tmp_path, parallelism):
    manifest, payloads = catalog(tmp_path, count=8)
    lock, reached, release = threading.Lock(), threading.Event(), threading.Event()
    active = peak = 0
    calls = []

    class Blocked(Response):
        def __init__(self, raw):
            nonlocal active, peak
            super().__init__(raw)
            with lock:
                active += 1
                peak = max(peak, active)
                if active == parallelism:
                    reached.set()

        def read(self, count=-1):
            assert release.wait(2), 'Selected downloads did not get a release signal'
            return super().read(count)

        def close(self):
            nonlocal active
            if not self.closed:
                with lock:
                    active -= 1
            super().close()

    def fetch(url, *, timeout):
        with lock:
            calls.append(url)
        return Blocked(payloads[url])

    # A constructor value is a default, not a hidden cap on the explicit job.
    library = ResourceLibrary(tmp_path, {'android': manifest}, fetcher=fetch, max_workers=1)
    try:
        started = library.start_download('android', parallelism=parallelism)
        assert reached.wait(1), 'The selected number of independent CDN streams did not overlap'
        running = library.status()['job']
        assert running['parallelism'] == started['parallelism'] == parallelism
        assert running['active_files'] == parallelism
        with lock:
            assert active == peak == len(calls) == parallelism
        release.set()
        done = complete(library)
        assert done['state'] == 'completed'
        assert done['verified_files'] == done['downloaded_files'] == len(payloads)
        assert done['received_bytes'] == sum(map(len, payloads.values()))
        assert done['parallelism'] == parallelism and done['active_files'] == 0
        assert len(calls) == len(set(calls)) == len(payloads) and peak == parallelism
        assert active == 0
        # Verified objects resume without new CDN handles even at another speed.
        library.start_download('android', parallelism=8 if parallelism != 8 else 1)
        assert complete(library)['cache_hit_files'] == len(payloads)
        assert len(calls) == len(payloads)
    finally:
        release.set()
        library.close()


def test_default_parallelism_is_four_and_options_are_discoverable(tmp_path):
    manifest, payloads = catalog(tmp_path)
    library = ResourceLibrary.from_data_dir(tmp_path, aes_cbc=AES,
        fetcher=lambda url, **kw: Response(payloads[url]),
        active_gateway=SimpleNamespace(manifest=manifest))
    try:
        assert library.status()['download_options'] == {
            'default_parallelism': 4, 'supported_parallelism': [1, 2, 4, 8]}
        assert library.start_download('android')['parallelism'] == 4
        assert complete(library)['parallelism'] == 4
    finally:
        library.close()


@pytest.mark.parametrize('parallelism', [True, False, 0, -1, 3, 5, 9, 16, 2.0, '4', [], {}])
def test_invalid_parallelism_is_rejected_before_reserving_or_replacing_a_job(tmp_path, parallelism):
    manifest, payloads = catalog(tmp_path)
    library = ResourceLibrary(tmp_path, {'android': manifest},
        fetcher=lambda url, **kw: Response(payloads[url]))
    try:
        with pytest.raises(ResourceLibraryError, match='invalid_selection'):
            library.start_download('android', parallelism=parallelism)
        assert library.status()['job'] is None
        previous = library.start_download('android', parallelism=1)['job_id']
        complete(library)
        with pytest.raises(ResourceLibraryError, match='invalid_selection'):
            library.start_download('android', parallelism=parallelism)
        assert library.status()['job']['job_id'] == previous
    finally:
        library.close()


@pytest.mark.parametrize('workers', [True, False, 0, 3, 5, 9, 16, 2.0, '4'])
def test_invalid_constructor_parallelism_is_rejected(tmp_path, workers):
    with pytest.raises(ValueError, match='Resource workers'):
        ResourceLibrary(tmp_path, max_workers=workers)


def test_eight_parallel_downloads_cancel_without_publishing_or_holding_reservations(tmp_path):
    manifest, payloads = catalog(tmp_path, count=8)
    lock, reached, release = threading.Lock(), threading.Event(), threading.Event()
    opened = 0

    class Blocked(Response):
        def read(self, count=-1):
            release.wait(2)
            return b'' if self.closed else super().read(count)

    def fetch(url, *, timeout):
        nonlocal opened
        with lock:
            opened += 1
            if opened == 8:
                reached.set()
        return Blocked(payloads[url])

    library = ResourceLibrary(tmp_path, {'android': manifest}, fetcher=fetch)
    try:
        job = library.start_download('android', parallelism=8)
        assert reached.wait(1)
        assert library.status()['job']['active_files'] == 8
        before = time.monotonic()
        library.cancel(job['job_id'])
        assert time.monotonic() - before < .2
        release.set()
        done = complete(library)
        assert done['state'] == 'cancelled' and done['verified_files'] == 0
        assert done['pending_write_bytes'] == 0 and done['active_files'] == 0
        assert not list(tmp_path.rglob('*.bin')) and not list(tmp_path.rglob('*.part'))
    finally:
        release.set()
        library.close()


def test_parallel_disk_reservations_stop_overcommit_before_another_cdn_handle(tmp_path, monkeypatch):
    import idoly_local.resource_library as module
    manifest, payloads = catalog(tmp_path, count=4)
    records = list(manifest.objects.values())
    # There is room for each object alone, but not for two outstanding writes.
    # A per-file-only free-space test would open all eight CDN handles here.
    available = module._RESERVE_BYTES + max(row.size for row in records)
    monkeypatch.setattr(module.shutil, 'disk_usage', lambda path: SimpleNamespace(free=available))
    entered, release = threading.Event(), threading.Event()
    calls = []

    class Blocked(Response):
        def read(self, count=-1):
            release.wait(2)
            return b'' if self.closed else super().read(count)

    def fetch(url, *, timeout):
        calls.append(url)
        entered.set()
        return Blocked(payloads[url])

    library = ResourceLibrary(tmp_path, {'android': manifest}, fetcher=fetch)
    exhausted = threading.Event()
    close_cache = library._close_cache
    def observed_close(job):
        close_cache(job)
        if job.fatal == 'insufficient_space':
            exhausted.set()
    monkeypatch.setattr(library, '_close_cache', observed_close)
    try:
        library.start_download('android', parallelism=8)
        assert exhausted.wait(1), 'An overcommitting second transfer was not rejected'
        release.set()
        done = complete(library)
        assert done['state'] == 'failed' and done['error_code'] == 'insufficient_space'
        # Cancellation can win before the first reserved writer opens its
        # network handle; neither ordering may open a second handle.
        assert len(calls) <= 1 and done['pending_write_bytes'] == 0
        assert not list(tmp_path.rglob('*.part'))
    finally:
        release.set()
        library.close()


def test_written_progress_is_not_counted_twice_against_current_free_space(tmp_path, monkeypatch):
    import idoly_local.resource_library as module
    manifest, payloads = catalog(tmp_path, count=1)
    records = sorted(manifest.objects.values(), key=lambda row: row.cache_key)
    first_written, second_opened = threading.Event(), threading.Event()
    written = 0
    calls = []
    total_size = sum(row.size for row in records)
    monkeypatch.setattr(module.shutil, 'disk_usage',
        lambda path: SimpleNamespace(free=module._RESERVE_BYTES + total_size - written))
    original_open = OctoCache.open_verified

    @contextmanager
    def ordered_open(cache, record):
        if record.cache_key != records[0].cache_key:
            assert first_written.wait(1)
        with original_open(cache, record) as stream:
            yield stream

    monkeypatch.setattr(OctoCache, 'open_verified', ordered_open)

    class FirstResponse(Response):
        def close(self):
            nonlocal written
            if not self.closed:
                # EOF is reached after the full body was written and its
                # progress was reported, but before the final file rehash.
                written = records[0].size
                first_written.set()
                assert second_opened.wait(1), 'Written bytes were reserved a second time'
            super().close()

    def fetch(url, *, timeout):
        calls.append(url)
        if url == records[0].upstream_url:
            return FirstResponse(payloads[url])
        second_opened.set()
        return Response(payloads[url])

    library = ResourceLibrary(tmp_path, {'android': manifest}, fetcher=fetch)
    try:
        library.start_download('android', parallelism=2)
        done = complete(library)
        assert done['state'] == 'completed' and done['verified_files'] == 2
        assert done['pending_write_bytes'] == 0 and len(calls) == 2
    finally:
        second_opened.set()
        library.close()


def test_completed_writes_release_reservations_before_the_next_download(tmp_path, monkeypatch):
    import idoly_local.resource_library as module
    manifest, payloads = catalog(tmp_path, count=4)
    available = module._RESERVE_BYTES + max(row.size for row in manifest.objects.values())
    monkeypatch.setattr(module.shutil, 'disk_usage', lambda path: SimpleNamespace(free=available))
    calls = []
    def fetch(url, *, timeout):
        calls.append(url)
        return Response(payloads[url])
    library = ResourceLibrary(tmp_path, {'android': manifest}, fetcher=fetch)
    try:
        library.start_download('android', parallelism=1)
        done = complete(library)
        assert done['state'] == 'completed' and done['verified_files'] == len(payloads)
        assert done['pending_write_bytes'] == 0 and len(calls) == len(payloads)
    finally:
        library.close()


def test_failed_fetch_releases_disk_reservation_for_later_objects(tmp_path, monkeypatch):
    import idoly_local.resource_library as module
    manifest, payloads = catalog(tmp_path)
    available = module._RESERVE_BYTES + max(row.size for row in manifest.objects.values())
    monkeypatch.setattr(module.shutil, 'disk_usage', lambda path: SimpleNamespace(free=available))
    calls = []
    def fetch(url, *, timeout):
        calls.append(url)
        raise OSError('synthetic connection failure')
    library = ResourceLibrary(tmp_path, {'android': manifest}, fetcher=fetch)
    try:
        library.start_download('android', parallelism=1)
        done = complete(library)
        assert done['state'] == 'failed' and done['error_code'] != 'insufficient_space'
        assert done['failed_files'] == len(calls) == len(payloads)
        assert done['pending_write_bytes'] == 0
    finally:
        library.close()


def test_worker_start_failure_cancels_started_workers_without_leaking_pending_writes(tmp_path, monkeypatch):
    manifest, payloads = catalog(tmp_path, count=8)
    release = threading.Event()
    original_start = threading.Thread.start
    attempts = 0

    class Blocked(Response):
        def read(self, count=-1):
            release.wait(2)
            return b'' if self.closed else super().read(count)

    def start(thread):
        nonlocal attempts
        if thread.name == 'IdolyResourceDownload':
            attempts += 1
            if attempts == 4:
                raise RuntimeError('synthetic worker exhaustion')
        return original_start(thread)

    library = ResourceLibrary(tmp_path, {'android': manifest},
        fetcher=lambda url, **kw: Blocked(payloads[url]))
    monkeypatch.setattr(threading.Thread, 'start', start)
    try:
        with pytest.raises(ResourceLibraryError, match='cache_io'):
            library.start_download('android', parallelism=8)
        release.set()
        done = complete(library)
        assert attempts == 4 and done['state'] == 'failed' and done['error_code'] == 'cache_io'
        assert done['pending_write_bytes'] == done['active_files'] == done['verified_files'] == 0
        assert not list(tmp_path.rglob('*.part'))
    finally:
        release.set()
        library.close()


def test_mixed_legacy_seed_and_cdn_share_pending_disk_budget(tmp_path, monkeypatch):
    import idoly_local.resource_library as module
    manifest, payloads = catalog(tmp_path, count=1)
    records = sorted(manifest.objects.values(), key=lambda row: row.cache_key)
    selected = tmp_path / 'Downloads' / 'IdolyPride'
    selected.mkdir(parents=True)
    seed = tmp_path / 'octo-cache' / records[0].cache_key[:2] / (records[0].cache_key + '.bin')
    seed.parent.mkdir(parents=True)
    seed.write_bytes(payloads[records[0].upstream_url])
    seed_reserved, release, exhausted = threading.Event(), threading.Event(), threading.Event()
    available = module._RESERVE_BYTES + max(row.size for row in records)
    monkeypatch.setattr(module.shutil, 'disk_usage', lambda path: SimpleNamespace(free=available))
    original_guard, original_open = OctoCache._write_guard, OctoCache.open_verified

    def held_guard(cache, record, phase, written=0):
        original_guard(cache, record, phase, written)
        if record.cache_key == records[0].cache_key and phase == 'start':
            seed_reserved.set()
            release.wait(2)

    @contextmanager
    def ordered_open(cache, record):
        if record.cache_key != records[0].cache_key:
            assert seed_reserved.wait(1)
        with original_open(cache, record) as stream:
            yield stream

    monkeypatch.setattr(OctoCache, '_write_guard', held_guard)
    monkeypatch.setattr(OctoCache, 'open_verified', ordered_open)
    calls = []
    def fetch(url, *, timeout):
        calls.append(url)
        return Response(payloads[url])
    library = ResourceLibrary(tmp_path, {'android': manifest}, fetcher=fetch,
                              resource_cache_dir=selected)
    close_cache = library._close_cache
    def observed_close(job):
        close_cache(job)
        if job.fatal == 'insufficient_space':
            exhausted.set()
    monkeypatch.setattr(library, '_close_cache', observed_close)
    try:
        library.start_download('android', parallelism=2)
        assert seed_reserved.wait(1) and exhausted.wait(1)
        release.set()
        done = complete(library)
        assert done['state'] == 'failed' and done['error_code'] == 'insufficient_space'
        assert done['pending_write_bytes'] == 0 and calls == []
        assert seed.read_bytes() == payloads[records[0].upstream_url]
        assert not list(selected.rglob('*.bin')) and not list(selected.rglob('*.part'))
    finally:
        release.set()
        library.close()


def test_failed_partial_seed_releases_budget_before_cdn_fallback_and_cache_hit_needs_no_space(
        tmp_path, monkeypatch):
    import idoly_local.resource_library as module
    manifest, payloads = catalog(tmp_path, count=1)
    record = next(row for row in manifest.objects.values() if row.kind == 'assetbundle')
    selected = tmp_path / 'Downloads' / 'IdolyPride'
    selected.mkdir(parents=True)
    seed = tmp_path / 'octo-cache' / record.cache_key[:2] / (record.cache_key + '.bin')
    seed.parent.mkdir(parents=True)
    seed.write_bytes(payloads[record.upstream_url])
    available = module._RESERVE_BYTES + record.size
    monkeypatch.setattr(module.shutil, 'disk_usage', lambda path: SimpleNamespace(free=available))
    original_seed = OctoCache._seed_file

    class BrokenSeed:
        def __init__(self, stream):
            self.stream, self.once = stream, False
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.stream.close()
        def fileno(self):
            return self.stream.fileno()
        def read(self, count):
            if self.once:
                raise OSError('synthetic seed read failure after a partial copy')
            self.once = True
            return self.stream.read(1)

    def broken_source(root, identity, row):
        source = original_seed(root, identity, row)
        return (BrokenSeed(source[0]), source[1]) if source is not None else None
    monkeypatch.setattr(OctoCache, '_seed_file', staticmethod(broken_source))
    calls = []
    def fetch(url, *, timeout):
        calls.append(url)
        return Response(payloads[url])
    library = ResourceLibrary(tmp_path, {'android': manifest}, fetcher=fetch,
                              resource_cache_dir=selected)
    try:
        library.start_download('android', kind='assetbundle', parallelism=8)
        done = complete(library)
        assert done['state'] == 'completed' and done['downloaded_files'] == 1
        assert done['pending_write_bytes'] == 0 and calls == [record.upstream_url]
        assert seed.read_bytes() == payloads[record.upstream_url]
        available = 0
        library.start_download('android', kind='assetbundle', parallelism=8)
        resumed = complete(library)
        assert resumed['state'] == 'completed' and resumed['cache_hit_files'] == 1
        assert resumed['pending_write_bytes'] == 0 and calls == [record.upstream_url]
    finally:
        library.close()


def test_close_is_bounded_even_when_transport_close_and_read_block(tmp_path):
    manifest,payloads=catalog(tmp_path,count=1)
    entered=threading.Event();release=threading.Event();closing=threading.Event()
    class Blocked(Response):
        def read(self,count=-1):
            entered.set();release.wait(2)
            return super().read(count) if not self.closed else b''
        def close(self):
            closing.set();release.wait(2);super().close()
    def fetch(url, *, timeout):return Blocked(payloads[url])
    library=ResourceLibrary(tmp_path, {'android':manifest}, fetcher=fetch)
    library.start_download('android')
    assert entered.wait(1)
    before=time.monotonic();library.close()
    assert time.monotonic()-before<.2 and closing.wait(1)
    frozen=library.status()['job']['received_bytes']
    assert all(t.daemon for t in threading.enumerate() if t.name.startswith('IdolyResource'))
    release.set()
    assert complete(library)['state']=='cancelled'
    assert library.status()['job']['received_bytes']==frozen
    assert not list(tmp_path.rglob('*.bin'))
    with pytest.raises(ResourceLibraryError,match='closed'):library.start_download('android')


def test_cancel_missing_response_handle_remains_bounded_and_cache_survives(tmp_path):
    manifest,payloads=catalog(tmp_path,count=1)
    entered=threading.Event();release=threading.Event()
    def fetch(url, *, timeout):
        entered.set();release.wait(2);return Response(payloads[url])
    library=ResourceLibrary(tmp_path, {'android':manifest}, fetcher=fetch)
    first=library.start_download('android')
    assert entered.wait(1)
    with pytest.raises(ResourceLibraryError,match='busy'):library.start_download('android')
    before=time.monotonic();library.cancel(first['job_id']);assert time.monotonic()-before<.2
    release.set();assert complete(library)['state']=='cancelled'
    # A separate game gateway cache was never closed by the bulk cancel.
    game=OctoCache(tmp_path/'octo-cache',fetcher=lambda url,**kw:Response(payloads[url]))
    with game.open_verified(next(iter(manifest.objects.values()))) as stream:assert stream.read()
    game.close();library.close()


def test_missing_invalid_catalog_selection_and_symlink_cache_are_fixed_errors(tmp_path):
    library=ResourceLibrary.from_data_dir(tmp_path,aes_cbc=AES)
    assert not library.status()['catalogs']['android']['available']
    with pytest.raises(ResourceLibraryError,match='catalog_unavailable'):library.start_download('android')
    for platform,kind in [('private','all'),('android',[]),('android','arbitrary')]:
        with pytest.raises(ResourceLibraryError,match='invalid_selection'):library.start_download(platform,kind)
    library.close()
    manifest,_=catalog(tmp_path)
    (tmp_path/'octo-cache').symlink_to(tmp_path/'public-octo',target_is_directory=True)
    library=ResourceLibrary(tmp_path,{'android':manifest},fetcher=lambda *a,**kw:pytest.fail('No network'))
    with pytest.raises(ResourceLibraryError,match='cache_io'):library.start_download('android')
    library.close()


def test_insufficient_space_stops_without_connecting(tmp_path,monkeypatch):
    import idoly_local.resource_library as module
    manifest,_=catalog(tmp_path)
    library=ResourceLibrary(tmp_path,{'android':manifest},fetcher=lambda *a,**kw:pytest.fail('No network'))
    monkeypatch.setattr(module.shutil,'disk_usage',lambda path:SimpleNamespace(free=0))
    library.start_download('android')
    assert complete(library)['error_code']=='insufficient_space'
    assert library.status()['job']['state']=='failed' and not list(tmp_path.rglob('*.bin'))
    library.close()


def test_streamed_export_import_is_portable_and_never_fetches_or_copies_profiles(library_case,tmp_path):
    library, manifest, payloads, calls=library_case
    (tmp_path/'state.db').write_bytes(b'private account data')
    library.start_download('android');assert complete(library)['state']=='completed'
    class Output(io.BytesIO):
        def seek(self,*args):raise OSError('nonseekable document output')
    output=Output()
    prepared=library.prepare_export('android')
    assert prepared['filename'].endswith('.zip') and prepared['state']=='export_ready'
    exported=library.write_export(prepared['job_id'],output)
    assert exported['state']=='completed' and exported['exported_files']==6 and len(calls)==6
    assert exported['archive_complete']
    assert not output.closed
    raw=output.getvalue()
    with ZipFile(io.BytesIO(raw)) as archive:
        names=archive.namelist()
        assert 'public-octo/manifest.pb' in names and 'portable-manifest.json' in names
        assert not any(name.endswith('settings.json') or name.endswith('state.db') for name in names)
        assert all('octo-cache/' in name for name in names if name.endswith('.bin'))
    restored=tmp_path/'restored';restored.mkdir()
    target_manifest,_=catalog(restored)
    target=ResourceLibrary(restored,{'android':target_manifest},fetcher=lambda *a,**kw:pytest.fail('Import must stay offline'))
    result=target.import_from(io.BytesIO(raw),'android')
    assert result['state']=='completed' and result['imported_files']==6 and result['received_bytes']==0
    assert result['downloaded_files']==0
    for record in manifest.objects.values():
        assert (restored/'octo-cache'/record.cache_key[:2]/(record.cache_key+'.bin')).read_bytes()==payloads[record.upstream_url]
    repeated=target.import_from(io.BytesIO(raw),'android')
    assert repeated['state']=='completed' and repeated['cache_hit_files']==6
    assert (tmp_path/'state.db').read_bytes()==b'private account data'
    target.close()


def test_export_partial_cached_selection_stays_importable(library_case,tmp_path):
    library,_,_,calls=library_case
    library.start_download('android','resources');assert complete(library)['verified_files']==3
    output=io.BytesIO();prepared=library.prepare_export('android')
    result=library.write_export(prepared['job_id'],output)
    assert result['state']=='partial' and result['missing_files']==3 and len(calls)==3
    assert result['archive_complete'] and result['failed_files']==0
    target_root=tmp_path/'restored';target_root.mkdir();manifest,_=catalog(target_root)
    target=ResourceLibrary(target_root,{'android':manifest},fetcher=lambda *a,**kw:pytest.fail('No CDN import'))
    imported=target.import_from(io.BytesIO(output.getvalue()),'android')
    assert imported['imported_files']==3 and imported['state']=='completed'
    target.close()


def test_prepared_export_cancel_and_wrong_platform_import_are_safe(library_case,tmp_path):
    library,_,_,calls=library_case
    prepared=library.prepare_export('android')
    assert library.cancel(prepared['job_id'])['state']=='cancelled'
    with pytest.raises(ResourceLibraryError,match='not_prepared'):library.write_export(prepared['job_id'],io.BytesIO())
    assert calls==[]
    library.start_download('android');complete(library)
    output=io.BytesIO();prepared=library.prepare_export('android');library.write_export(prepared['job_id'],output)
    target_root=tmp_path/'target';target_root.mkdir();manifest,_=catalog(target_root,'ios')
    target=ResourceLibrary(target_root,{'ios':manifest})
    with pytest.raises(ResourceLibraryError,match='import_failed'):target.import_from(io.BytesIO(output.getvalue()),'ios')
    assert not list(target_root.rglob('*.bin'))
    target.close()


@pytest.mark.parametrize('kind',['resources','assetbundle'])
def test_kind_filtered_export_import_roundtrip_uses_full_current_catalog(library_case,tmp_path,kind):
    library,_,_,calls=library_case
    library.start_download('android',kind);complete(library)
    output=io.BytesIO();prepared=library.prepare_export('android',kind)
    assert '-'+kind+'-' in prepared['filename']
    result=library.write_export(prepared['job_id'],output)
    assert result['state']=='completed' and result['exported_files']==3 and result['missing_files']==0
    target_root=tmp_path/'target';target_root.mkdir();manifest,_=catalog(target_root)
    target=ResourceLibrary(target_root,{'android':manifest})
    imported=target.import_from(io.BytesIO(output.getvalue()),'android')
    assert imported['state']=='completed' and imported['imported_files']==3
    target.close()


def test_empty_cache_export_is_a_complete_partial_archive(library_case):
    library,_,_,calls=library_case
    output=io.BytesIO();prepared=library.prepare_export('android')
    result=library.write_export(prepared['job_id'],output)
    assert result['state']=='partial' and result['exported_files']==0 and result['missing_files']==6
    assert calls==[]
    with ZipFile(io.BytesIO(output.getvalue())) as archive:
        assert set(archive.namelist())=={'public-octo/manifest.pb','portable-manifest.json'}


def test_midstream_export_failure_never_sets_archive_complete(library_case):
    library,_,_,calls=library_case
    library.start_download('android');complete(library)
    class Broken(io.BytesIO):
        def write(self, value):
            if self.tell()>300:raise OSError('sensitive provider error')
            return super().write(value)
    prepared=library.prepare_export('android')
    with pytest.raises(ResourceLibraryError,match='export_failed'):
        library.write_export(prepared['job_id'],Broken())
    job=library.status()['job']
    assert not job['archive_complete'] and job['failed_files']==1 and job['state'] in {'failed','partial'}
    assert 'sensitive' not in json.dumps(job) and len(calls)==6
