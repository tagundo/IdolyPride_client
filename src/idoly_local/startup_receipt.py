"""Optional build-validated public translation metadata from a signed app.

A complete receipt SHA is supplied by the native app's bundled resource pin.
Receipts never come from writable account/cache metadata. Current source byte
hashes and latest-cohort authorization remain the authority for every lease.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import struct
import threading
import zlib
from zipfile import BadZipFile, ZipFile

MAX_RECEIPT_BYTES = 16 * 1024 * 1024
_MAX_METADATA = 16 * 1024 * 1024
_MAX_MANIFEST = 8 * 1024 * 1024
_MAX_TOTAL = 48 * 1024 * 1024
_SCHEMA = 1
_FORMAT = 2
_RECEIPTS = {}
_LOCK = threading.Lock()
_HEX = re.compile(r"[0-9a-f]{64}\Z")


def _stamp(info):
    return (info.st_dev,info.st_ino,info.st_mode,info.st_nlink,info.st_size,info.st_mtime_ns,info.st_ctime_ns)


def _pairs(items):
    result={}
    for key,value in items:
        if key in result:raise ValueError("Duplicate startup receipt field")
        result[key]=value
    return result


@contextmanager
def _source(pin):
    source,digest,size=pin
    if type(source) is bytes:
        if len(source)!=size or hashlib.sha256(source).hexdigest()!=digest:
            raise ValueError("Startup receipt identity differs")
        with io.BytesIO(source) as stream:yield stream
        return
    descriptor=os.open(source,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(descriptor,"rb") as stream:
        before=os.fstat(stream.fileno())
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or before.st_size!=size
                or hashlib.file_digest(stream,"sha256").hexdigest()!=digest
                or _stamp(before)!=_stamp(os.fstat(stream.fileno()))):
            raise ValueError("Startup receipt identity differs")
        stream.seek(0)
        yield stream
        if _stamp(before)!=_stamp(os.fstat(stream.fileno())):
            raise ValueError("Startup receipt changed")


@contextmanager
def _archive(pin):
    with _source(pin) as stream:
        # Bound the central directory before ZipFile allocates member objects.
        stream.seek(0,os.SEEK_END);size=stream.tell()
        stream.seek(max(0,size-65557));tail=stream.read(65557);at=tail.rfind(b"PK\x05\x06")
        if at<0 or at+22>len(tail):raise ValueError("Startup receipt directory is missing")
        _magic,disk,start_disk,on_disk,count,length,offset,comment=struct.unpack_from("<4s4H2IH",tail,at)
        if (disk or start_disk or on_disk!=5 or count!=5 or not 0<length<=4096
                or offset+length!=size-len(tail)+at or at+22+comment!=len(tail)):
            raise ValueError("Startup receipt directory exceeds its boundary")
        stream.seek(0)
        with ZipFile(stream) as archive:
            infos=archive.infolist();expected={"index.json"}
            for language in ("ko","en"):
                expected.update(language+"/"+name for name in ("metadata.json","rebased.pb"))
            if (len(infos)!=len(expected) or {row.filename for row in infos}!=expected
                    or sum(row.file_size for row in infos)>_MAX_TOTAL):
                raise ValueError("Startup receipt members differ")
            for row in infos:
                limit=8192 if row.filename=="index.json" else (_MAX_METADATA if row.filename.endswith("metadata.json") else _MAX_MANIFEST)
                if (not 0<row.file_size<=limit or row.flag_bits&1
                        or row.compress_type not in (0,8)
                        or stat.S_IFMT(row.external_attr>>16) not in (0,stat.S_IFREG)):
                    raise ValueError("Startup receipt member exceeds its boundary")
            yield archive


def _pin(source,expected_sha256,expected_bytes,platform):
    if (platform not in ("android","ios") or type(expected_sha256) is not str
            or not _HEX.fullmatch(expected_sha256) or type(expected_bytes) is not int
            or not 0<expected_bytes<=MAX_RECEIPT_BYTES):return None
    if type(source) is io.BytesIO:source=source.getvalue()
    if type(source) is bytes:
        if len(source)!=expected_bytes:return None
    else:source=Path(source)
    return source,expected_sha256,expected_bytes


def inspect_startup_receipt(source,*,expected_sha256,expected_bytes,platform):
    """Check the signed-app resource envelope without changing runtime state."""
    result={"schema":_SCHEMA,"available":False}
    try:
        pin=_pin(source,expected_sha256,expected_bytes,platform)
        if pin is None:return result
        with _archive(pin) as archive:
            index=json.loads(archive.read("index.json"),object_pairs_hook=_pairs)
            if (type(index) is not dict or set(index)!={"schema","platform","layers"}
                    or type(index["schema"]) is not int or index["schema"]!=_FORMAT
                    or index["platform"]!=platform or type(index["layers"]) is not dict
                    or set(index["layers"])!={"ko","en"}):return result
        result["available"]=True
    except (OSError,ValueError,TypeError,KeyError,UnicodeError,BadZipFile,zlib.error,RecursionError):pass
    return result


def register_startup_receipt(source,*,expected_sha256,expected_bytes,platform):
    """Register an explicit app pin; never persist receipt or private user data."""
    result=inspect_startup_receipt(source,expected_sha256=expected_sha256,
                                  expected_bytes=expected_bytes,platform=platform)
    if platform not in ("android","ios"):return result
    with _LOCK:
        if result["available"]:_RECEIPTS[platform]=_pin(source,expected_sha256,expected_bytes,platform)
        else:_RECEIPTS.pop(platform,None)
    return result


def binding(original_manifest,legacy,digests):
    return {"original_sha256":hashlib.sha256(original_manifest).hexdigest(),
            "legacy_sha256":None if legacy is None else hashlib.sha256(legacy).hexdigest(),
            "source_sha256":[None if item is None else item.hex() for item in digests]}


def encode_snapshot(snapshot):
    """Build-only conversion; finite public fields, no executable serialization."""
    value,_weight=snapshot
    records=[[key,row.kind,row.upload_version,row.object_name,row.generation,row.size,row.md5,row.name]
             for key,row in value["records"].items()]
    aliases=[[list(key),item] for key,item in value["aliases"].items()]
    top=value["rebase"]
    meta={"report":value["report"],"records":records,"aliases":aliases,"rebase":None}
    if top is not None:
        meta["rebase"]={"report_delta":top["report_delta"],"record_keys":list(top["record_keys"]),
                        "aliases":[[list(key),item] for key,item in top["aliases"].items()]}
    return (json.dumps(meta,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode(),
            value["manifest"] if top is None else top["manifest"])


def _aliases(rows,records):
    result={}
    if type(rows) is not list or len(rows)>8192:raise ValueError("Startup receipt alias bound differs")
    for row in rows:
        if (type(row) is not list or len(row)!=2 or type(row[0]) is not list or len(row[0])!=4
                or type(row[0][0]) is not str or type(row[0][1]) is not int
                or type(row[0][2]) is not str or type(row[0][3]) is not int
                or type(row[1]) is not str or row[1] not in records):
            raise ValueError("Startup receipt alias differs")
        key=tuple(row[0])
        if key in result:raise ValueError("Duplicate startup receipt alias")
        result[key]=row[1]
    return result


def _base_manifest(directory,signature,digest):
    path=Path(directory)/"manifest.pb"
    descriptor=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(descriptor,"rb") as stream:
        before=os.fstat(stream.fileno())
        if _stamp(before)!=signature:raise ValueError("Prepared manifest changed")
        raw=stream.read(_MAX_MANIFEST+1)
        if (not 0<len(raw)<=_MAX_MANIFEST or len(raw)!=before.st_size
                or hashlib.sha256(raw).hexdigest()!=digest or _stamp(os.fstat(stream.fileno()))!=signature):
            raise ValueError("Prepared manifest changed")
        return raw


def load_snapshot(platform,language,expected,*,directory,signature):
    """Return exact build-validated bytes only for every currently hashed input."""
    with _LOCK:pin=_RECEIPTS.get(platform)
    if pin is None or language not in ("ko","en"):return None
    try:
        with _archive(pin) as archive:
            index=json.loads(archive.read("index.json"),object_pairs_hook=_pairs)
            if (type(index) is not dict or set(index)!={"schema","platform","layers"}
                    or type(index["schema"]) is not int or index["schema"]!=_FORMAT
                    or index["platform"]!=platform or type(index["layers"]) is not dict
                    or set(index["layers"])!={"ko","en"}
                    or index["layers"][language]!=expected):return None
            prefix=language+"/"
            meta=json.loads(archive.read(prefix+"metadata.json"),object_pairs_hook=_pairs)
            rebased=archive.read(prefix+"rebased.pb")
        # The base wire already exists as a prepared source. Read/hash its own
        # held descriptor instead of duplicating it in the signed-app receipt.
        base=_base_manifest(directory,signature[1],expected["source_sha256"][1])
        from .resource_translation_cache import _plain_metadata
        from .octo_manifest import OctoObject
        if (not _plain_metadata(meta) or type(meta) is not dict
                or set(meta)!={"report","records","aliases","rebase"}
                or type(meta["report"]) is not dict or meta["report"].get("language")!=language
                or type(meta["report"].get("objects")) is not dict or len(meta["report"]["objects"])>8192
                or type(meta["records"]) is not list
                or len(meta["records"])>8192):raise ValueError("Startup receipt metadata differs")
        records={}
        for row in meta["records"]:
            if (type(row) is not list or len(row)!=8 or any(type(row[i]) is not str for i in (0,1,3,6,7))
                    or any(type(row[i]) is not int for i in (2,4,5))):
                raise ValueError("Startup receipt record differs")
            record=OctoObject(*row[1:])
            if row[0]!=record.cache_key or row[0] in records:raise ValueError("Startup receipt record identity differs")
            records[row[0]]=record
        value={"manifest":base,"report":meta["report"],"records":records,
               "aliases":_aliases(meta["aliases"],records),"rebase":None}
        top=meta["rebase"]
        if top is not None:
            if (type(top) is not dict or set(top)!={"report_delta","record_keys","aliases"}
                    or type(top["report_delta"]) is not dict or type(top["record_keys"]) is not list
                    or len(top["record_keys"])>8192
                    or any(type(key) is not str or key not in records for key in top["record_keys"])
                    or len(set(top["record_keys"]))!=len(top["record_keys"])):
                raise ValueError("Startup receipt rebased metadata differs")
            value["rebase"]={**top,"manifest":rebased,"record_keys":tuple(top["record_keys"]),
                             "aliases":_aliases(top["aliases"],records)}
        elif rebased!=base:raise ValueError("Startup receipt original manifest differs")
        # Match the existing shared cache's serialized accounting exactly.
        # The generated metadata omits the same immutable record references.
        weight=len(base)+(len(rebased) if top is not None else 0)+len(json.dumps({
            "report":meta["report"],"records":[tuple(row) for row in meta["records"]],
            "aliases":[(tuple(key),item) for key,item in meta["aliases"]],
            "rebase":None if top is None else {"report_delta":top["report_delta"],
                "record_keys":tuple(top["record_keys"]),"aliases":[(tuple(key),item) for key,item in top["aliases"]]}
            },separators=(",",":"),ensure_ascii=False).encode())
        return value,weight
    except (OSError,ValueError,TypeError,KeyError,UnicodeError,BadZipFile,zlib.error,RecursionError):
        return None
