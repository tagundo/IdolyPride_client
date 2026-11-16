"""Signed app receipt handoff; normal source validation remains authoritative."""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from idoly_local import ios_host, startup_receipt
from test_ios_unified_packaging import package, package_fixture


@pytest.fixture(autouse=True)
def isolated_registry(monkeypatch):
    monkeypatch.setattr(startup_receipt,"_RECEIPTS",{})


def receipt_bytes(platform):
    output=io.BytesIO()
    with ZipFile(output,"w") as archive:
        archive.writestr("index.json",json.dumps({"schema":1,"platform":platform,"layers":{"ko":{},"en":{}}}))
        for language in ("ko","en"):
            archive.writestr(language+"/metadata.json","{}")
            archive.writestr(language+"/base.pb",b"public-original")
            archive.writestr(language+"/rebased.pb",b"public-original")
    return output.getvalue()


def app_receipt(root, platform="ios"):
    root.mkdir(parents=True,exist_ok=True)
    raw=receipt_bytes(platform);archive=root/"startupTranslations.zip";archive.write_bytes(raw)
    metadata={"schema":1,"platform":platform,"bytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest()}
    pin=root/"startupTranslations.json";pin.write_text(json.dumps(metadata))
    return archive,pin,metadata


@pytest.mark.parametrize("target",("device","simulator"))
def test_packaging_carries_exact_immutable_receipt_and_runtime_consumes_its_pin(tmp_path,target):
    runtime,native,data,translations,source,replacement,manifest,web=package_fixture(tmp_path,target)
    archive,pin,metadata=app_receipt(tmp_path/"receipt")
    files,generated,proof=package.bundle_files(runtime,native,data,translations,target,manifest,web,
        startup_translations=archive,startup_translations_metadata=pin)
    assert files["LocalServer/startupTranslations.zip"]==archive
    assert generated["LocalServer/startupTranslations.json"]==pin.read_bytes()
    assert proof["startup_translations"]==metadata
    assert startup_receipt._RECEIPTS=={},"Packaging inspection cannot register runtime state"
    signed=tmp_path/"Signed.app/LocalServer";signed.mkdir(parents=True)
    (signed/"startupTranslations.zip").write_bytes(archive.read_bytes())
    (signed/"startupTranslations.json").write_bytes(generated["LocalServer/startupTranslations.json"])
    assert ios_host._register_app_startup_receipt(signed)=={"schema":1,"available":True}
    assert startup_receipt._RECEIPTS["ios"][0]==signed/"startupTranslations.zip"


@pytest.mark.parametrize("damage",("missing-pair","platform","sha","bytes","bool-bytes","extra","corrupt","symlink"))
def test_packager_rejects_a_provided_unbound_or_corrupt_receipt(tmp_path,damage):
    archive,pin,metadata=app_receipt(tmp_path)
    if damage=="missing-pair":
        with pytest.raises(ValueError):package.startup_translation_files(archive,None)
        return
    if damage=="platform":metadata["platform"]="android"
    elif damage=="sha":metadata["sha256"]="0"*64
    elif damage=="bytes":metadata["bytes"]+=1
    elif damage=="bool-bytes":metadata["bytes"]=True
    elif damage=="extra":metadata["path"]="/private/account.db"
    elif damage=="corrupt":archive.write_bytes(b"invalid public receipt")
    elif damage=="symlink":
        original=tmp_path/"actual.zip";archive.rename(original);archive.symlink_to(original)
    pin.write_text(json.dumps(metadata))
    with pytest.raises(ValueError):package.startup_translation_files(archive,pin)


def test_omitting_package_receipt_retains_legacy_full_validation_path():
    assert package.startup_translation_files(None,None)==({},{},None)


@pytest.mark.parametrize("damage",("missing","platform","sha","bytes","bool-bytes","extra-path","corrupt","metadata-symlink","receipt-symlink"))
def test_ios_invalid_optional_receipt_falls_back_without_reading_writable_state(tmp_path,damage):
    signed=tmp_path/"Signed.app/LocalServer";archive,pin,metadata=app_receipt(signed)
    assert ios_host._register_app_startup_receipt(signed)["available"]
    private=tmp_path/"Documents/state.db";private.parent.mkdir();private.write_bytes(b"private-state-canary")
    if damage=="missing":pin.unlink()
    elif damage=="platform":metadata["platform"]="android"
    elif damage=="sha":metadata["sha256"]="0"*64
    elif damage=="bytes":metadata["bytes"]+=1
    elif damage=="bool-bytes":metadata["bytes"]=True
    elif damage=="extra-path":metadata["path"]=str(private)
    elif damage=="corrupt":archive.write_bytes(b"invalid")
    elif damage=="metadata-symlink":
        outside=tmp_path/"outside.json";pin.rename(outside);pin.symlink_to(outside)
    elif damage=="receipt-symlink":
        outside=tmp_path/"outside.zip";archive.rename(outside);archive.symlink_to(outside)
    if damage not in ("missing","metadata-symlink"):pin.write_text(json.dumps(metadata))
    assert ios_host._register_app_startup_receipt(signed)=={"schema":1,"available":False}
    assert "ios" not in startup_receipt._RECEIPTS
    assert private.read_bytes()==b"private-state-canary"


def android_boundary():
    path=Path(__file__).resolve().parents[1]/"android-server/app/src/main/python/android_server_runtime.py"
    spec=importlib.util.spec_from_file_location("startup_android_boundary",path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def java_receipt(monkeypatch,raw):
    class Asset:
        def __init__(self):self.offset=0;self.closed=0
        def read(self,target):
            if self.offset==len(raw):return -1
            length=min(37,len(target),len(raw)-self.offset)
            target[:length]=raw[self.offset:self.offset+length];self.offset+=length;return length
        def close(self):self.closed+=1
    stream=Asset();opened=[]
    def open_asset(name):
        opened.append(name);assert name=="startupTranslations.zip";return stream
    monkeypatch.setitem(sys.modules,"java",SimpleNamespace(jarray=lambda _:lambda size:bytearray(size),jbyte=object()))
    return SimpleNamespace(open=open_asset),stream,opened


@pytest.mark.parametrize("damage",("none","sha","truncated","oversize","wrong-platform"))
def test_android_reads_only_fixed_signed_asset_and_keeps_it_immutable_in_memory(tmp_path,monkeypatch,damage):
    raw=receipt_bytes("ios" if damage=="wrong-platform" else "android")
    size=len(raw);expected=hashlib.sha256(raw).hexdigest()
    if damage=="sha":expected="0"*64
    elif damage=="truncated":raw=raw[:-1]
    elif damage=="oversize":raw+=b"x"
    assets,stream,opened=java_receipt(monkeypatch,raw)
    private=tmp_path/"state.db";private.write_bytes(b"private-state-canary")
    config=SimpleNamespace(STARTUP_TRANSLATIONS_SHA256=expected,STARTUP_TRANSLATIONS_BYTES=size)
    observed=android_boundary()._register_app_startup_receipt(assets,config)
    assert observed["available"] is (damage=="none")
    assert opened==["startupTranslations.zip"] and stream.closed==1
    if damage=="none":assert type(startup_receipt._RECEIPTS["android"][0]) is bytes
    else:assert "android" not in startup_receipt._RECEIPTS
    assert private.read_bytes()==b"private-state-canary" and set(path.name for path in tmp_path.iterdir())=={"state.db"}


def test_android_absent_receipt_never_opens_an_asset_or_a_writable_path():
    def reject(name):raise AssertionError("No optional receipt asset expected")
    assert android_boundary()._register_app_startup_receipt(SimpleNamespace(open=reject),SimpleNamespace())=={"schema":1,"available":False}
