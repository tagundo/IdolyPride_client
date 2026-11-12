from __future__ import annotations

import hashlib
import io
import json
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
    library=ResourceLibrary(tmp_path, {'android':manifest}, fetcher=fetch)
    library.start_download('android')
    done=complete(library)
    assert peak<=2 and done['state']=='partial' and done['failed_files']==1
    assert done['error_code']=='upstream_digest' and done['verified_files']==15
    record=next(record for record in manifest.objects.values() if record.upstream_url==bad)
    assert not (tmp_path/'octo-cache'/record.cache_key[:2]/(record.cache_key+'.bin')).exists()
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
