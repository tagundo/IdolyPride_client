"""Bounded process-local reuse of an exact validated startup schema.

Bytes are securely read every time. No marker, filename, timestamp or account
state can authorize a cache hit. Only the full descriptor content digest and
parser implementation identify the single retained descriptor pool.
"""
from __future__ import annotations

from collections import OrderedDict
from copy import copy
import hashlib
import os
from pathlib import Path
import stat
import threading

_MAX_DESCRIPTOR = 4 * 1024 * 1024
_SCHEMA_CACHE = OrderedDict()
_LOCK = threading.RLock()


def _stamp(info):
    return (info.st_dev,info.st_ino,info.st_mode,info.st_nlink,info.st_size,info.st_mtime_ns,info.st_ctime_ns)


def _descriptor_bytes(path):
    descriptor=os.open(Path(path),os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(descriptor,"rb") as stream:
        before=os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or not 0<before.st_size<=_MAX_DESCRIPTOR:
            raise ValueError("Startup descriptor is not a bounded regular file")
        raw=stream.read(_MAX_DESCRIPTOR+1)
        if len(raw)!=before.st_size or _stamp(before)!=_stamp(os.fstat(stream.fileno())):
            raise ValueError("Startup descriptor changed during verification")
        return raw


class _BytesSource:
    def __init__(self,raw):
        self._raw=raw

    def read_bytes(self):
        return self._raw


def load_startup_schema(path):
    """Return isolated metadata sharing a pool built from these exact bytes."""
    from .schema import Schema
    raw=_descriptor_bytes(path)
    parser=Schema.from_descriptor_set
    key=(Schema,getattr(parser,"__func__",parser),hashlib.sha256(raw).digest())
    with _LOCK:
        template=_SCHEMA_CACHE.get(key)
        if template is None:
            # Use the captured bytes, avoiding a second pathname read between
            # digesting and parsing. The original parser validates everything.
            template=parser(_BytesSource(raw))
            _SCHEMA_CACHE.clear()
            _SCHEMA_CACHE[key]=template
        result=copy(template)
        result.files=list(template.files)
        result.methods=dict(template.methods)
        result._message_types=dict(template._message_types)
        return result
