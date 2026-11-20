"""Verified read leases over the existing Octo object store, without file copies.

Preparation may download/hash on a worker. ``acquire_cached`` only consults a
prepared receipt and opens/stats its existing file; it never fills, seeds or
hashes a cache. The representation is explicitly the unchanged Octo payload,
not a claim that a particular game SDK can consume those bytes directly.

A pathname is only a hint. Consumers must receive an owned descriptor or open
with O_NOFOLLOW and compare the receipt's identity before reading. Descriptors
already handed to a consumer remain that consumer's responsibility, including
after a lease or store closes. No TTL can close an in-flight native read.
"""
from __future__ import annotations

from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import re
import secrets
import stat
import threading

from .octo_cache import OctoCache, OctoCacheError
from .octo_manifest import OctoManifest, OctoRequestError


_PLATFORMS = {205051: "android", 105051: "ios"}
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_MD5 = re.compile(r"[0-9a-f]{32}\Z")
_TOKEN = re.compile(r"[0-9a-f]{32}\Z")
_REPRESENTATION = "octo_raw_v1"
_ERRORS = frozenset(("store_closed", "cancelled", "not_found", "capacity",
                    "cache_unavailable", "file_changed", "file_not_immutable",
                    "store_unavailable", "lease_closed"))


class SharedResourceError(OSError):
    """Fixed diagnostics without filesystem paths, request data or CDN details."""

    def __init__(self, code):
        self.code = code if type(code) is str and code in _ERRORS else "store_unavailable"
        super().__init__("Shared resource unavailable: " + self.code)


@dataclass(frozen=True)
class SharedFileIdentity:
    device: int
    inode: int
    size: int
    mtime_ns: int
    ctime_ns: int
    mode: int
    links: int

    @classmethod
    def from_stat(cls, info):
        return cls(info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
                   info.st_ctime_ns, info.st_mode, info.st_nlink)


@dataclass(frozen=True)
class SharedResourceReceipt:
    platform: str
    application_version: int
    manifest_revision: int
    manifest_sha256: str
    cache_key: str
    kind: str
    upload_version: int
    object_name: str
    generation: int
    size: int
    md5: str
    identity: SharedFileIdentity
    representation: str = _REPRESENTATION


def _cancelled(event):
    if event is not None and not isinstance(event, threading.Event):
        raise TypeError("Cancellation must be a threading.Event")
    return event is not None and event.is_set()


def _immutable(info, size):
    return (stat.S_ISREG(info.st_mode) and info.st_nlink == 1
            and info.st_size == size and not info.st_mode & 0o222)


class SharedResourceLease:
    """One pinned source descriptor and independently opened consumer readers."""

    def __init__(self, store, token, receipt, descriptor, requested_route):
        self._store, self.token, self.receipt = store, token, receipt
        self._descriptor = descriptor
        self._requested_route = requested_route
        self._lock = threading.Lock()

    @property
    def requested_route(self):
        """The exact manifest-validated request, including any SDK alias."""
        return self._requested_route

    @property
    def path_hint(self):
        """This name can change; use open_descriptor/detach_descriptor to read."""
        return self._store._path(self.receipt.cache_key)

    def open_descriptor(self):
        """Return a caller-owned FD with its own seek position, or fail closed."""
        descriptor = None
        with self._lock:
            if self._descriptor is None:
                raise SharedResourceError("lease_closed")
            self._store._check()
            self._store._check_lease(self.token, self)
            try:
                if SharedFileIdentity.from_stat(os.fstat(self._descriptor)) != self.receipt.identity:
                    raise SharedResourceError("file_changed")
                descriptor = self._store._open_pinned(self.receipt)
                self._store._check()
                result, descriptor = descriptor, None
                return result
            finally:
                if descriptor is not None:
                    os.close(descriptor)

    def detach_descriptor(self):
        """Transfer the pinned FD once; the native consumer must close it.

        This releases the Python lease. The descriptor is not revoked by a
        later store close and must live until that native asynchronous read
        completes. A transferred descriptor is never shared with another
        reader supplied by this component.
        """
        with self._lock:
            if self._descriptor is None:
                raise SharedResourceError("lease_closed")
            self._store._check()
            self._store._check_lease(self.token, self)
            info = os.fstat(self._descriptor)
            if (SharedFileIdentity.from_stat(info) != self.receipt.identity
                    or not _immutable(info, self.receipt.size)):
                raise SharedResourceError("file_changed")
            descriptor, self._descriptor = self._descriptor, None
        self._store._release(self.token, self)
        return descriptor

    @contextmanager
    def reader(self):
        stream = os.fdopen(self.open_descriptor(), "rb")
        try:
            yield stream
        finally:
            stream.close()

    def close(self):
        with self._lock:
            descriptor, self._descriptor = self._descriptor, None
        if descriptor is not None:
            try:
                os.close(descriptor)
            finally:
                self._store._release(self.token, self)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class SharedResourceStore:
    """Manifest-selected raw objects with worker preparation and fast reads.

    The supplied cache remains owned by its gateway/library. Cancellation and
    close refuse a handoff, but do not abort a fill another cache user needs.
    Existing verified files, account data, cache policy and file names are
    never changed or removed. Only receipt metadata is evicted from the LRU.
    """

    def __init__(self, manifest, cache, *, max_leases=64, max_prepared=4096,
                 max_preparations=16):
        if not isinstance(manifest, OctoManifest) or not isinstance(cache, OctoCache):
            raise TypeError("A validated manifest and Octo cache are required")
        for value, maximum in ((max_leases, 4096), (max_prepared, 100000), (max_preparations, 64)):
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError("Invalid shared resource limits")
        if (type(manifest.application_version) is not int
                or manifest.application_version not in _PLATFORMS
                or type(manifest.revision) is not int or not 1 <= manifest.revision <= 2**31 - 1
                or not isinstance(manifest.archive_sha256, str)
                or not _HEX64.fullmatch(manifest.archive_sha256)):
            raise ValueError("Invalid shared resource manifest")
        self._manifest, self._cache = manifest, cache
        # OctoManifest exposes an immutable mapping of frozen records. Retain
        # that validated snapshot instead of hashing/indexing the full catalog
        # again on every app start; only requested files need a cache key.
        self._records = manifest.objects
        self._version, self._revision = manifest.application_version, manifest.revision
        self._manifest_sha256 = manifest.archive_sha256
        self._root = Path(cache.root)
        descriptor = None
        try:
            descriptor = os.open(self._root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            root = os.fstat(descriptor)
            self._root_identity = root.st_dev, root.st_ino
        except OSError:
            raise ValueError("Shared resource directory is unavailable") from None
        finally:
            if descriptor is not None:
                os.close(descriptor)
        self._max_leases, self._max_prepared = max_leases, max_prepared
        self._max_preparations = max_preparations
        self._lock = threading.Lock()
        self._closed, self._preparing, self._acquiring = False, 0, 0
        self._ready, self._leases = OrderedDict(), {}

    def _check(self, cancel_event=None):
        if _cancelled(cancel_event):
            raise SharedResourceError("cancelled")
        with self._lock:
            if self._closed:
                raise SharedResourceError("store_closed")

    def _record(self, route, expected_size=None, expected_md5=None):
        if type(route) is not str or len(route) > 256:
            raise SharedResourceError("not_found")
        checked = expected_size is not None or expected_md5 is not None
        if checked and (type(expected_size) is not int or not 1 <= expected_size <= 2**31 - 1
                        or type(expected_md5) is not str or not _MD5.fullmatch(expected_md5)):
            raise SharedResourceError("not_found")
        try:
            record = self._manifest.lookup_object(route)
        except OctoRequestError:
            raise SharedResourceError("not_found") from None
        if self._records.get(record.identity) != record:
            raise SharedResourceError("not_found")
        if checked and (record.size != expected_size or record.md5 != expected_md5):
            raise SharedResourceError("not_found")
        return record

    def _path(self, key):
        return self._root / key[:2] / (key + ".bin")

    def _open_pinned(self, receipt):
        root = shard = descriptor = None
        try:
            root = os.open(self._root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            info = os.fstat(root)
            if (info.st_dev, info.st_ino) != self._root_identity:
                raise SharedResourceError("store_unavailable")
            shard = os.open(receipt.cache_key[:2], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=root)
            descriptor = os.open(receipt.cache_key + ".bin", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                                 dir_fd=shard)
            info = os.fstat(descriptor)
            if (not _immutable(info, receipt.size)
                    or SharedFileIdentity.from_stat(info) != receipt.identity):
                raise SharedResourceError("file_changed")
            result, descriptor = descriptor, None
            return result
        except OSError as error:
            if isinstance(error, SharedResourceError):
                raise
            raise SharedResourceError("file_changed") from None
        finally:
            for opened in (descriptor, shard, root):
                if opened is not None:
                    os.close(opened)

    def prepare(self, route, *, cancel_event=None, expected_size=None, expected_md5=None):
        """Fill/verify on a worker, then retain a bounded read-only receipt.

        A cancelled request may leave a valid shared cache fill for another
        user. It never publishes a ready receipt or hands out a descriptor.
        """
        self._check(cancel_event)
        record = self._record(route, expected_size, expected_md5)
        with self._lock:
            if self._closed:
                raise SharedResourceError("store_closed")
            if self._preparing >= self._max_preparations:
                raise SharedResourceError("capacity")
            self._preparing += 1
        try:
            try:
                with self._cache.open_verified(record) as source:
                    self._check(cancel_event)
                    info = os.fstat(source.fileno())
                    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                            or info.st_size != record.size):
                        raise SharedResourceError("file_changed")
                    if info.st_mode & 0o222:
                        raise SharedResourceError("file_not_immutable")
                    receipt = SharedResourceReceipt(
                        _PLATFORMS[self._version], self._version, self._revision, self._manifest_sha256,
                        record.cache_key, record.kind, record.upload_version, record.object_name,
                        record.generation, record.size, record.md5, SharedFileIdentity.from_stat(info))
                    descriptor = self._open_pinned(receipt)
                    os.close(descriptor)
                    if SharedFileIdentity.from_stat(os.fstat(source.fileno())) != receipt.identity:
                        raise SharedResourceError("file_changed")
                self._check(cancel_event)
                with self._lock:
                    if self._closed:
                        raise SharedResourceError("store_closed")
                    if _cancelled(cancel_event):
                        raise SharedResourceError("cancelled")
                    self._ready[record.cache_key] = receipt
                    self._ready.move_to_end(record.cache_key)
                    while len(self._ready) > self._max_prepared:
                        self._ready.popitem(last=False)
                return receipt
            except OctoCacheError:
                raise SharedResourceError("cache_unavailable") from None
        finally:
            with self._lock:
                self._preparing -= 1

    def acquire_cached(self, route, *, cancel_event=None, expected_size=None, expected_md5=None):
        """Lease only a prepared unchanged file, without any network or hash.

        A missing, replaced or changed file is a cache miss, never a request
        to download on the caller's thread. Preparation belongs on a worker.
        """
        self._check(cancel_event)
        record = self._record(route, expected_size, expected_md5)
        with self._lock:
            if self._closed:
                raise SharedResourceError("store_closed")
            receipt = self._ready.get(record.cache_key)
            if receipt is None:
                return None
            if len(self._leases) + self._acquiring >= self._max_leases:
                raise SharedResourceError("capacity")
            self._acquiring += 1
        descriptor = None
        try:
            try:
                descriptor = self._open_pinned(receipt)
            except SharedResourceError as error:
                if error.code != "file_changed":
                    raise
                with self._lock:
                    if self._ready.get(record.cache_key) is receipt:
                        del self._ready[record.cache_key]
                return None
            self._check(cancel_event)
            with self._lock:
                if self._closed:
                    raise SharedResourceError("store_closed")
                if _cancelled(cancel_event):
                    raise SharedResourceError("cancelled")
                if self._ready.get(record.cache_key) is not receipt:
                    return None
                token = secrets.token_hex(16)
                if token in self._leases:
                    raise SharedResourceError("capacity")
                lease = SharedResourceLease(self, token, receipt, descriptor, route)
                self._leases[token] = lease
                self._ready.move_to_end(record.cache_key)
                descriptor = None
                return lease
        finally:
            if descriptor is not None:
                os.close(descriptor)
            with self._lock:
                self._acquiring -= 1

    def _release(self, token, lease):
        with self._lock:
            if self._leases.get(token) is lease:
                del self._leases[token]

    def _check_lease(self, token, lease):
        with self._lock:
            if self._leases.get(token) is not lease:
                raise SharedResourceError("lease_closed")

    def release(self, token):
        if type(token) is not str or not _TOKEN.fullmatch(token):
            return False
        with self._lock:
            lease = self._leases.get(token)
        if lease is None:
            return False
        lease.close()
        return True

    def protected_cache_keys(self):
        with self._lock:
            return frozenset(row.receipt.cache_key for row in self._leases.values())

    def status(self):
        with self._lock:
            return {"representation": _REPRESENTATION, "closed": self._closed,
                    "prepared_files": len(self._ready), "active_leases": len(self._leases),
                    "pending_preparations": self._preparing, "pending_acquisitions": self._acquiring}

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            leases = list(self._leases.values())
            self._leases.clear()
            self._ready.clear()
        for lease in leases:
            lease.close()
