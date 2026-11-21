"""Signed-app receipts accelerate exact public inputs; unknown data stays strict."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED,BadZipFile
from google.protobuf.message import DecodeError

import pytest

from idoly_local import resource_translation as translation
from idoly_local import resource_translation_cache as cache
from idoly_local import startup_receipt as receipt
from idoly_local.octo_manifest import Database
from idoly_local.resource_translation_build import build_resource_overlay
from test_resource_translation_rebase import prepared,record,SOURCE

SPEC=importlib.util.spec_from_file_location("startup_receipt_builder",Path(__file__).resolve().parents[1]/"tools/build_startup_translation_receipt.py")
builder=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(builder)


@pytest.fixture(autouse=True)
def caches():
    cache._CACHE.clear();receipt._RECEIPTS.clear()
    yield
    cache._CACHE.clear();receipt._RECEIPTS.clear()


@pytest.fixture
def sample(tmp_path,monkeypatch):
    old,current,target,body=prepared(tmp_path)
    root=tmp_path/"prepared";directory=root/"ko"/"android";directory.parent.mkdir(parents=True);target.rename(directory)
    build_resource_overlay(old,tmp_path/"source",root/"en"/"android",language="en",revision=1088,source=SOURCE)
    data=tmp_path/"data";data.mkdir()
    monkeypatch.setattr("idoly_local.octo_runtime.load_octo_archive",lambda *_args,**_kwargs:({},old))
    output=tmp_path/"startupTranslations.zip"
    pin=builder.build(root,data,output,platform="android")
    return old,current,directory,body,data,output,pin


def register(path,pin):
    return receipt.register_startup_receipt(path,expected_sha256=pin["sha256"],expected_bytes=pin["bytes"],platform=pin["platform"])


def test_generator_uses_strict_validators_and_receipt_avoids_reparse(sample,monkeypatch):
    old,_current,directory,body,data,path,pin=sample
    assert pin["bytes"]<=receipt.MAX_RECEIPT_BYTES
    with ZipFile(path) as archive:
        assert set(archive.namelist())=={"index.json","ko/metadata.json","ko/rebased.pb","en/metadata.json","en/rebased.pb"}
        assert json.loads(archive.read("index.json"))["schema"]==2
    assert not receipt._RECEIPTS and not cache._CACHE
    assert register(path,pin)=={"schema":1,"available":True}
    original=translation.ResourceTranslation.__init__;calls=[]
    def observe(self,*args,**kwargs):calls.append(1);return original(self,*args,**kwargs)
    monkeypatch.setattr(translation.ResourceTranslation,"__init__",observe)
    layer=translation.load_resource_translation(directory,old,language="ko",data_dir=data,platform="android")
    try:
        assert not calls and len(cache._CACHE)==1
        with layer.open_source(record(Database.FromString(layer.manifest).resourceList[0])) as stream:assert stream.read()==body
        expected=layer.manifest;expected_report=layer.report;expected_aliases=dict(layer.object_aliases)
    finally:layer.close()
    receipt._RECEIPTS.clear();cache._CACHE.clear()
    strict=translation.load_resource_translation(directory,old,language="ko",data_dir=data,platform="android")
    try:assert calls==[1] and strict.manifest==expected and strict.report==expected_report and dict(strict.object_aliases)==expected_aliases
    finally:strict.close()


@pytest.mark.parametrize("kind",["bytes","stream"])
def test_android_signed_asset_bytes_need_no_persisted_copy(sample,kind):
    _old,_current,_directory,_body,_data,path,pin=sample
    raw=path.read_bytes();source=raw if kind=="bytes" else io.BytesIO(raw)
    assert receipt.inspect_startup_receipt(source,expected_sha256=pin["sha256"],expected_bytes=pin["bytes"],platform="android")["available"]
    assert not receipt._RECEIPTS
    assert register(source,pin)["available"]
    assert type(receipt._RECEIPTS["android"][0]) is bytes


@pytest.mark.parametrize("damage",["changed","truncated","missing","symlink","hardlink"])
def test_corrupt_receipt_falls_back_to_original_constructor(sample,monkeypatch,tmp_path,damage):
    old,_current,directory,_body,data,path,pin=sample
    assert register(path,pin)["available"]
    if damage=="changed":
        before=path.stat();raw=path.read_bytes();path.write_bytes(raw[:-1]+bytes([raw[-1]^1]));os.utime(path,ns=(before.st_atime_ns,before.st_mtime_ns))
    elif damage=="truncated":path.write_bytes(path.read_bytes()[:20])
    elif damage=="missing":path.unlink()
    elif damage=="symlink":
        actual=tmp_path/"actual.zip";path.rename(actual);path.symlink_to(actual)
    else:os.link(path,tmp_path/"other.zip")
    original=translation.ResourceTranslation.__init__;calls=[]
    def observe(self,*args,**kwargs):calls.append(1);return original(self,*args,**kwargs)
    monkeypatch.setattr(translation.ResourceTranslation,"__init__",observe)
    layer=translation.load_resource_translation(directory,old,language="ko",data_dir=data,platform="android")
    layer.close();assert calls==[1]
    assert not register(path,pin)["available"] and not receipt._RECEIPTS


@pytest.mark.parametrize("change",["manifest.json","manifest.pb","objects.zip","original","platform","language"])
def test_receipt_requires_entire_current_source_and_selection_binding(sample,monkeypatch,change):
    old,_current,directory,_body,data,path,pin=sample
    assert register(path,pin)["available"]
    original=translation.ResourceTranslation.__init__;calls=[]
    def observe(self,*args,**kwargs):calls.append(1);return original(self,*args,**kwargs)
    monkeypatch.setattr(translation.ResourceTranslation,"__init__",observe)
    kwargs={"language":"ko","data_dir":data,"platform":"android"};raw=old
    if change in ("manifest.json","manifest.pb","objects.zip"):
        source=directory/change;before=source.stat();body=source.read_bytes()
        source.write_bytes(body+b" " if change=="manifest.json" else bytes([body[0]^1])+body[1:])
        os.utime(source,ns=(before.st_atime_ns,before.st_mtime_ns))
    elif change=="original":raw=old+b"\x38\x01"
    elif change=="platform":kwargs["platform"]="ios"
    else:kwargs["language"]="en"
    try:
        layer=translation.load_resource_translation(directory,raw,**kwargs)
    except (ValueError,DecodeError,BadZipFile):
        assert change in ("manifest.pb","objects.zip","original","language")
    else:layer.close()
    assert calls or change=="original"


def test_unknown_receipt_schema_and_extra_member_have_no_runtime_authority(sample,tmp_path):
    _old,_current,_directory,_body,_data,path,pin=sample
    with ZipFile(path) as archive:rows={name:archive.read(name) for name in archive.namelist()}
    index=json.loads(rows["index.json"]);index["schema"]=99;rows["index.json"]=json.dumps(index).encode()
    for extra in (False,True):
        target=tmp_path/("extra.zip" if extra else "unknown.zip")
        with ZipFile(target,"w",compression=ZIP_DEFLATED) as archive:
            for name,raw in rows.items():archive.writestr(name,raw)
            if extra:archive.writestr("private-account.json",b"{}")
        raw=target.read_bytes()
        assert not register(target,{**pin,"bytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest()})["available"]
    assert not receipt._RECEIPTS


def test_rebased_receipt_retains_unknown_wire_and_current_cohort_authority(sample,monkeypatch,tmp_path):
    import idoly_local.latest_cohort_pins as pins
    old,current,directory,_body,data,path,_pin=sample
    raw=current.SerializeToString()+b"\x38\x01";sha=hashlib.sha256(old).hexdigest()
    archive=data/"public-octo";archive.mkdir();(archive/"legacy-manifest.pb").write_bytes(old)
    monkeypatch.setattr(translation,"LEGACY_MANIFEST_SHA256",{"android":sha})
    approval={"application_version":205051,"revision":current.revision,"manifest_sha256":hashlib.sha256(raw).hexdigest(),"legacy_manifest_sha256":sha}
    monkeypatch.setattr(pins,"RESOURCE_ARCHIVES",{"android":approval})
    monkeypatch.setattr("idoly_local.octo_runtime.load_octo_archive",lambda *_args,**_kwargs:({},raw))
    output=tmp_path/"rebased.zip";pin=builder.build(directory.parents[1],data,output,platform="android")
    assert register(output,pin)["available"]
    original=translation.ResourceTranslation.__init__;calls=[]
    def observe(self,*args,**kwargs):calls.append(1);return original(self,*args,**kwargs)
    monkeypatch.setattr(translation.ResourceTranslation,"__init__",observe)
    layer=translation.load_resource_translation(directory,raw,language="ko",data_dir=data,platform="android")
    try:assert not calls and b"\x38\x01" in layer.manifest
    finally:layer.close()
    monkeypatch.setattr(pins,"RESOURCE_ARCHIVES",{})
    with pytest.raises(ValueError,match="not approved"):translation.load_resource_translation(directory,raw,language="ko",data_dir=data,platform="android")
    monkeypatch.setattr(pins,"RESOURCE_ARCHIVES",{"android":approval})
    (archive/"legacy-manifest.pb").write_bytes(old+b"\x38\x01")
    with pytest.raises(ValueError,match="legacy manifest differs"):translation.load_resource_translation(directory,raw,language="ko",data_dir=data,platform="android")


def test_unknown_receipt_reconstruction_uses_strict_factory_and_no_account_state(sample,tmp_path,monkeypatch):
    old,_current,directory,_body,data,path,pin=sample
    with ZipFile(path) as archive:rows={name:archive.read(name) for name in archive.namelist()}
    meta=json.loads(rows["ko/metadata.json"]);meta["report"]["objects"]={}
    rows["ko/metadata.json"]=json.dumps(meta).encode();target=tmp_path/"unknown-shape.zip"
    with ZipFile(target,"w",compression=ZIP_DEFLATED) as archive:
        for name,raw in rows.items():archive.writestr(name,raw)
    raw=target.read_bytes();assert register(target,{**pin,"bytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest()})["available"]
    account=data/"account-private.db";account.write_bytes(b"private-sentinel")
    original=translation.ResourceTranslation.__init__;calls=[]
    def observe(self,*args,**kwargs):calls.append(1);return original(self,*args,**kwargs)
    monkeypatch.setattr(translation.ResourceTranslation,"__init__",observe)
    translation.load_resource_translation(directory,old,language="ko",data_dir=data,platform="android").close()
    assert calls==[1] and account.read_bytes()==b"private-sentinel"
    assert not list(data.glob("client-resource-revision-*.json"))


def test_generator_rejects_invalid_prepared_input_without_publishing_receipt(sample,tmp_path):
    _old,_current,directory,_body,data,_path,_pin=sample
    (directory/"manifest.pb").write_bytes(b"invalid")
    output=tmp_path/"invalid.zip"
    with pytest.raises(ValueError):builder.build(directory.parents[1],data,output,platform="android")
    assert not output.exists() and not output.with_name(output.name+".part").exists()
    assert not list(data.glob("client-resource-revision-*.json"))


def test_receipt_base_wire_cannot_trust_coarse_timestamps(sample,monkeypatch):
    _old,_current,directory,_body,_data,_path,_pin=sample
    path=directory/"manifest.pb";raw=path.read_bytes();digest=hashlib.sha256(raw).hexdigest()
    original=receipt._stamp
    monkeypatch.setattr(receipt,"_stamp",lambda info:original(info)[:-2]+(0,0))
    signature=receipt._stamp(path.stat())
    path.write_bytes(bytes([raw[0]^1])+raw[1:])
    with pytest.raises(ValueError,match="manifest changed"):
        receipt._base_manifest(directory,signature,digest)
