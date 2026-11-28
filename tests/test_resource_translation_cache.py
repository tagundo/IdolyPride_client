"""Prepared-layer reuse keeps full source/approval and request integrity."""
import hashlib
import json
import os
from pathlib import Path
import shutil
from zipfile import ZipFile

import pytest

from idoly_local import resource_translation as translation
from idoly_local import resource_translation_cache as cache
from idoly_local.octo_cache import OctoCache, OctoCacheError
from idoly_local.octo_manifest import Database
from test_resource_translation_rebase import prepared, record


@pytest.fixture(autouse=True)
def process_cache():
    cache._CACHE.clear()
    yield
    cache._CACHE.clear()


@pytest.fixture
def original(tmp_path,monkeypatch):
    old,current,directory,body=prepared(tmp_path)
    init=translation.ResourceTranslation.__init__;calls=[]
    def count(self,*args,**kwargs):
        calls.append(1);init(self,*args,**kwargs)
    monkeypatch.setattr(translation.ResourceTranslation,"__init__",count)
    def load(*,path=directory,raw=old,language="ko",platform="android",data=tmp_path):
        return translation.load_resource_translation(path,raw,language=language,data_dir=data,platform=platform)
    return old,current,directory,body,calls,load


def test_validation_reuse_returns_independent_metadata_and_fresh_owned_archive(original):
    old,_current,directory,body,calls,load=original
    first=load();wire=first.manifest;aliases=dict(first.object_aliases)
    first.report["coverage"]["translated"]=999;first._records.clear();first.manifest=b"changed wrapper"
    first.close()
    second=load()
    try:
        assert len(calls)==1 and second.manifest==wire and dict(second.object_aliases)==aliases
        assert second.report["coverage"]["translated"]==1
        item=record(Database.FromString(second.manifest).resourceList[0])
        stream=second.open_source(item);owned=second._archive.fp
        second.close()
        assert not owned.closed and stream.read()==body
        stream.close();assert owned.closed
    finally:second.close()


@pytest.mark.parametrize("filename",["manifest.json","manifest.pb","objects.zip"])
def test_cached_layer_requires_every_current_regular_source(original,filename):
    _old,_current,directory,_body,calls,load=original
    load().close();(directory/filename).unlink()
    with pytest.raises(ValueError,match="missing"):load()
    assert len(calls)==1


@pytest.mark.parametrize("filename",["manifest.json","manifest.pb"])
def test_tampered_metadata_with_restored_mtime_is_not_cached(original,filename):
    _old,_current,directory,_body,calls,load=original
    load().close();path=directory/filename;before=path.stat()
    path.write_bytes(b"{}" if filename.endswith("json") else b"invalid protobuf")
    os.utime(path,ns=(before.st_atime_ns,before.st_mtime_ns))
    with pytest.raises(ValueError):load()


@pytest.mark.parametrize("damage",["symlink","hardlink"])
def test_cached_language_files_cannot_be_redirected(original,tmp_path,damage):
    _old,_current,directory,_body,_calls,load=original
    load().close();path=directory/"objects.zip"
    if damage=="symlink":
        actual=tmp_path/"actual.zip";path.rename(actual);path.symlink_to(actual)
    else:os.link(path,tmp_path/"other.zip")
    with pytest.raises(ValueError,match="regular"):load()


def test_replaced_archive_revalidates_and_request_md5_still_rejects_bad_content(original,tmp_path):
    _old,_current,directory,body,calls,load=original
    first=load();first.close()
    path=directory/"objects.zip";old=path.stat()
    with ZipFile(path) as z:items=[(info.filename,z.read(info)) for info in z.infolist()]
    replacement=tmp_path/"replacement.zip"
    with ZipFile(replacement,"w") as z:
        for name,raw in items:z.writestr(name,b"x"*len(raw))
    os.replace(replacement,path);os.utime(path,ns=(old.st_atime_ns,old.st_mtime_ns))
    layer=load();assert len(calls)==2
    item=record(Database.FromString(layer.manifest).resourceList[0]);network=[]
    checked=OctoCache(tmp_path/"verified",allow_download=False,local_source=layer.open_source,
                      fetcher=lambda *args,**kwargs:network.append(args))
    try:
        with pytest.raises(OctoCacheError):
            with checked.open_verified(item):pass
        assert not network and not list((tmp_path/"verified").rglob("*.bin"))
    finally:checked.close();layer.close()


def test_cache_keys_include_language_platform_directory_and_entire_original(original,tmp_path):
    old,_current,directory,_body,calls,load=original
    load().close()
    with pytest.raises(ValueError):load(language="en")
    load(platform="ios").close()
    copied=tmp_path/"copy";shutil.copytree(directory,copied)
    load(path=copied).close()
    with pytest.raises(ValueError,match="not approved"):load(raw=old+b"\x38\x01")
    assert len(calls)==4


def test_rebased_cached_bytes_keep_unknowns_and_recheck_latest_authority(original,tmp_path,monkeypatch):
    import idoly_local.latest_cohort_pins as pins
    old,current,directory,body,calls,load=original
    raw=current.SerializeToString()+b"\x38\x01"
    archive=tmp_path/"public-octo";archive.mkdir();legacy=archive/"legacy-manifest.pb";legacy.write_bytes(old)
    sha=hashlib.sha256(old).hexdigest()
    monkeypatch.setattr(translation,"LEGACY_MANIFEST_SHA256",{"android":sha})
    approved={"application_version":205051,"revision":current.revision,
              "manifest_sha256":hashlib.sha256(raw).hexdigest(),"legacy_manifest_sha256":sha}
    monkeypatch.setattr(pins,"RESOURCE_ARCHIVES",{"android":approved})
    first=load(raw=raw);wire=first.manifest;aliases=dict(first.object_aliases);first.close()
    second=load(raw=raw)
    try:
        assert len(calls)==1 and second.manifest==wire and dict(second.object_aliases)==aliases
        assert Database.FromString(wire).tagname==current.tagname and b"\x38\x01" in wire
        with second.open_source(record(Database.FromString(wire).resourceList[0])) as stream:assert stream.read()==body
    finally:second.close()
    monkeypatch.setattr(pins,"RESOURCE_ARCHIVES",{})
    with pytest.raises(ValueError,match="not approved"):load(raw=raw)
    monkeypatch.setattr(pins,"RESOURCE_ARCHIVES",{"android":approved})
    legacy.write_bytes(old+b"\x38\x01")
    with pytest.raises(ValueError,match="legacy manifest differs"):load(raw=raw)


def test_metadata_cache_has_entry_and_serialized_byte_budgets(original,tmp_path,monkeypatch):
    _old,_current,directory,_body,calls,load=original
    for number in range(4):
        target=tmp_path/("copy"+str(number));shutil.copytree(directory,target);load(path=target).close()
        assert len(cache._CACHE)<=2 and sum(row[1] for row in cache._CACHE.values())<=32*1024*1024
    cache._CACHE.clear();monkeypatch.setattr(cache,"_MAX_METADATA_BYTES",1)
    before=len(calls);load().close();load().close()
    assert not cache._CACHE and len(calls)==before+2


def test_coarse_storage_timestamps_cannot_authorize_changed_manifest_bytes(original,monkeypatch):
    _old,_current,directory,_body,calls,load=original
    real=cache._stamp
    monkeypatch.setattr(cache,"_stamp",lambda info:real(info)[:-2]+(0,0))
    load().close();source=directory/"manifest.pb";raw=source.read_bytes()
    source.write_bytes(bytes([raw[0]^1])+raw[1:])
    with pytest.raises(ValueError):load()
    assert len(calls)==2
