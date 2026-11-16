"""Reuse validated language metadata within one native server process.

The first complete constructors remain the authority. This cache owns no open
ZIP and no parsed protobuf; every consumer gets independent metadata and a new
verified ZIP handle. Installer hashes and request-time size/MD5 checks remain.
"""
from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import stat
import threading
from types import MappingProxyType
from zipfile import ZipFile, ZIP_STORED, ZIP_DEFLATED

_CACHE = OrderedDict()
_LOCK = threading.RLock()
_MAX_ENTRIES = 2
_MAX_METADATA_BYTES = 32 * 1024 * 1024


def _stamp(info):
    return (info.st_dev,info.st_ino,info.st_mode,info.st_nlink,info.st_size,info.st_mtime_ns,info.st_ctime_ns)


def _file(path,maximum,optional=False):
    try:info=path.lstat()
    except FileNotFoundError:
        if optional:return None
        raise ValueError("Prepared language cache input is missing") from None
    if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or not 0<info.st_size<=maximum:
        raise ValueError("Prepared language cache input is not a bounded regular file")
    return _stamp(info)


def _signature(directory,data_dir,platform):
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("Prepared language directory is unavailable")
    paths=[(directory/"manifest.json",8*1024*1024,False),
           (directory/"manifest.pb",8*1024*1024,False),
           (directory/"objects.zip",256*1024*1024,False)]
    if data_dir is not None:
        name="public-octo" if platform=="android" else "public-octo-ios"
        paths.append((Path(data_dir)/name/"legacy-manifest.pb",8*1024*1024,True))
    return tuple(_file(*row) for row in paths)



def _hashes(directory,data_dir,platform,expected,*,skip_archive=False):
    paths=[directory/"manifest.json",directory/"manifest.pb",directory/"objects.zip"]
    if data_dir is not None:
        name="public-octo" if platform=="android" else "public-octo-ios"
        paths.append(Path(data_dir)/name/"legacy-manifest.pb")
    result=[]
    for index,(path,stamp) in enumerate(zip(paths,expected)):
        if stamp is None or (skip_archive and index==2):
            result.append(None);continue
        descriptor=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        with os.fdopen(descriptor,"rb") as stream:
            if _stamp(os.fstat(stream.fileno()))!=stamp:
                raise ValueError("Prepared language cache input changed")
            value=hashlib.file_digest(stream,"sha256").digest()
            if _stamp(os.fstat(stream.fileno()))!=stamp:
                raise ValueError("Prepared language cache input changed")
        result.append(value)
    return tuple(result)


def _aliases(value):
    return {identity:record.cache_key for identity,record in value.items()}


def _snapshot(layer):
    from .resource_translation import ResourceTranslation, RebasedResourceTranslation
    if type(layer) not in (ResourceTranslation,RebasedResourceTranslation):return None
    base=layer._layer if type(layer) is RebasedResourceTranslation else layer
    value={"manifest":base.manifest,"report":deepcopy(base.report),
           "records":dict(base._records),"aliases":_aliases(base.object_aliases),"rebase":None}
    if type(layer) is RebasedResourceTranslation:
        value["rebase"]={"manifest":layer.manifest,
            "report_delta":deepcopy({key:item for key,item in layer.report.items()
                                      if key not in base.report or item!=base.report[key]}),
            "record_keys":tuple(layer._records),"aliases":_aliases(layer.object_aliases)}
    # Count raw immutable manifest bytes plus an exact serialized representation
    # of all retained public metadata (record/alias references are not repeated).
    records=[(key,record.kind,record.upload_version,record.object_name,record.generation,
              record.size,record.md5,record.name) for key,record in value["records"].items()]
    meta={"report":value["report"],"records":records,"aliases":list(value["aliases"].items()),
          "rebase":None if value["rebase"] is None else {
              key:(list(item.items()) if key=="aliases" else item)
              for key,item in value["rebase"].items() if key!="manifest"}}
    weight=len(value["manifest"])+len(json.dumps(meta,separators=(",",":"),ensure_ascii=False).encode())
    if value["rebase"] is not None:weight+=len(value["rebase"]["manifest"])
    return value,weight


def _open_archive(path,expected,expected_sha256,entries):
    descriptor=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    stream=os.fdopen(descriptor,"rb")
    try:
        if _stamp(os.fstat(stream.fileno()))!=expected:
            raise ValueError("Prepared language cache input changed")
        # Hash this same held descriptor before parsing its ZIP metadata. The
        # lease never switches to a pathname or trusts coarse storage clocks.
        if hashlib.file_digest(stream,"sha256").digest()!=expected_sha256:
            raise ValueError("Prepared language cache input changed")
        if _stamp(os.fstat(stream.fileno()))!=expected:
            raise ValueError("Prepared language cache input changed")
        stream.seek(0)
        archive=ZipFile(stream)
        # Transfer the already checked descriptor to ZipFile's normal owned-file
        # reference counting. Open member streams retain it after close(), just
        # as they do with ZipFile(path); no descriptor is leaked by a cache hit.
        archive._filePassed=0
        try:
            infos=archive.infolist()
            if (len(infos)!=len(entries) or len({row.filename for row in infos})!=len(infos)
                    or {row.filename for row in infos}!=set(entries)):
                raise ValueError("Prepared language object index differs")
            for row in infos:
                if (row.file_size!=entries[row.filename]["bytes"] or row.flag_bits&1
                        or row.compress_type not in (ZIP_STORED,ZIP_DEFLATED)
                        or stat.S_IFMT(row.external_attr>>16) not in (0,stat.S_IFREG)):
                    raise ValueError("Prepared language object entry differs")
            if _stamp(os.fstat(archive.fp.fileno()))!=expected:
                raise ValueError("Prepared language cache input changed")
            return archive
        except BaseException:
            archive.close();raise
    except BaseException:
        stream.close();raise


def _clone(template,directory,language,signature,digests):
    from .resource_translation import ResourceTranslation, RebasedResourceTranslation
    base=object.__new__(ResourceTranslation)
    base._lock=threading.Lock();base._archive=None;base.language=language
    base._records=dict(template["records"]);base.report=deepcopy(template["report"])
    base._entries=dict(base.report["objects"]);base.manifest=template["manifest"]
    base.object_aliases=MappingProxyType({key:base._records[value] for key,value in template["aliases"].items()})
    base._archive=_open_archive(directory/"objects.zip",signature[2],digests[2],base._entries)
    top=template["rebase"]
    if top is None:return base
    try:
        result=object.__new__(RebasedResourceTranslation)
        result._layer=base;result.language=language
        result._records={key:base._records[key] for key in top["record_keys"]}
        result.manifest=top["manifest"];result.report=dict(base.report)
        result.report.update(deepcopy(top["report_delta"]))
        result.object_aliases=MappingProxyType({key:base._records[value] for key,value in top["aliases"].items()})
        return result
    except BaseException:
        base.close();raise


def validated_layer(directory,original_manifest,*,language,data_dir,platform,authorize,build):
    """Reuse only exact inputs authorized again by the original source policy."""
    if type(original_manifest) is not bytes or language not in ("ko","en") or platform not in ("android","ios"):
        return build(authorize())
    from .resource_translation import ResourceTranslation, RebasedResourceTranslation
    directory=Path(directory)
    before=_signature(directory,data_dir,platform)
    # Full byte fingerprints remain mandatory even on external storage where
    # mtime/ctime resolution may be coarse. Metadata alone cannot authorize reuse.
    digests=_hashes(directory,data_dir,platform,before)
    legacy=authorize()
    if _signature(directory,data_dir,platform)!=before:
        raise ValueError("Prepared language cache input changed")
    key=(str(directory.absolute()),language,platform,hashlib.sha256(original_manifest).digest(),
         None if legacy is None else hashlib.sha256(legacy).digest(),before,digests,
         ResourceTranslation,ResourceTranslation.__init__,RebasedResourceTranslation,RebasedResourceTranslation.__init__)
    with _LOCK:
        hit=_CACHE.get(key)
        if hit is not None:_CACHE.move_to_end(key)
    if hit is not None:
        result=_clone(hit[0],directory,language,before,digests)
        try:
            checked=_hashes(directory,data_dir,platform,before,skip_archive=True)
            if (_signature(directory,data_dir,platform)!=before
                    or any(value!=digests[index] for index,value in enumerate(checked) if index!=2)):
                raise ValueError("Prepared language cache input changed")
            return result
        except BaseException:
            result.close();raise
    result=build(legacy)
    try:
        if (_signature(directory,data_dir,platform)!=before
                or _hashes(directory,data_dir,platform,before)!=digests):
            raise ValueError("Prepared language cache input changed")
        cached=_snapshot(result)
        if cached is not None and cached[1]<=_MAX_METADATA_BYTES:
            with _LOCK:
                _CACHE[key]=cached;_CACHE.move_to_end(key)
                while len(_CACHE)>_MAX_ENTRIES or sum(item[1] for item in _CACHE.values())>_MAX_METADATA_BYTES:
                    _CACHE.popitem(last=False)
        return result
    except BaseException:
        result.close();raise
