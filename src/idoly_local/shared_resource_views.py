"""Private, metadata-only SDK names for leased Octo raw objects.

The caller supplies a trusted app-private directory (native getFilesDir or
Library/Application Support), never the user-selected resource directory.
Only a fresh 0700 session directory is owned here. A symlink capability probe
checks the actual private filesystem; no filesystem-name guesses are needed.

Views survive lease/store close for asynchronous readers. Cleanup is explicit
and requires the native owner to know all readers are quiescent. This module
never deletes a target, copies payloads or creates hardlinks. A symlink is not
a promise against later canonical-file replacement: materialization checks
the current verified inode before returning, and cached data remains governed
by the store's immutable publication policy.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import secrets
import stat
import threading

from .shared_resource_store import (
    SharedFileIdentity, SharedResourceError, SharedResourceLease, _cancelled,
)


_SDK_ROUTE = re.compile(r"/octo/([1-9][0-9]{0,9})/(assetbundle|resources)/"
                        r"([A-Za-z0-9]{6})/([1-9][0-9]{0,19})\Z")
_BUCKET = re.compile(r"[AR][A-Za-z0-9]{6}\Z")
_FILE = re.compile(r"([0-9a-f]{32})(\.[a-z0-9]{1,16})?\Z")
_KEY = re.compile(r"[0-9a-f]{64}\Z")
_ERRORS = frozenset(("invalid_view", "view_unavailable", "view_conflict",
                    "view_closed", "lease_unavailable", "cancelled",
                    "capacity", "not_quiescent"))


class SharedResourceViewError(OSError):
    def __init__(self, code):
        self.code = code if type(code) is str and code in _ERRORS else "view_unavailable"
        super().__init__("Shared resource view unavailable: " + self.code)


@dataclass(frozen=True)
class SharedResourceView:
    path: str
    cache_key: str
    md5: str
    size: int
    sdk_bucket: str
    sdk_filename: str
    representation: str = "octo_raw_v1"


@dataclass(frozen=True)
class _OwnedLink:
    identity: tuple
    target: str


def _directory_identity(info):
    return info.st_dev, info.st_ino, info.st_mode, info.st_uid


def _link_identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_nlink, info.st_mtime_ns, info.st_ctime_ns)


def _directory(info, *, private):
    return (stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid()
            and (not private or stat.S_IMODE(info.st_mode) == 0o700))


def _check_cancel(event):
    if _cancelled(event):
        raise SharedResourceViewError("cancelled")


class SharedResourceViews:
    """One fresh private view session; existing unknown names are never adopted."""

    def __init__(self, app_private_dir, *, max_views=8192):
        if type(max_views) is not int or not 1 <= max_views <= 131072:
            raise ValueError("Invalid shared view limit")
        supplied = Path(app_private_dir)
        if not supplied.is_absolute():
            raise ValueError("A trusted absolute app-private directory is required")
        self._lock = threading.Lock()
        self._closed, self._max_views = False, max_views
        self._buckets, self._links = {}, {}
        private = root = None
        made = None
        try:
            # Resolve OS aliases once. All newly created children are checked
            # through pinned descriptors with no symlink traversal.
            self._private = supplied.resolve(strict=True)
            private = os.open(self._private, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            info = os.fstat(private)
            if not _directory(info, private=False):
                raise SharedResourceViewError("view_unavailable")
            self._private_identity = _directory_identity(info)
            for _ in range(8):
                name = ".idoly-resource-views-" + secrets.token_hex(16)
                try:
                    os.mkdir(name, 0o700, dir_fd=private)
                    made = name
                    break
                except FileExistsError:
                    continue
            if made is None:
                raise SharedResourceViewError("view_unavailable")
            self._name = made
            self._root = self._private / made
            made_info = os.stat(made, dir_fd=private, follow_symlinks=False)
            self._root_identity = _directory_identity(made_info)
            if not _directory(made_info, private=True):
                raise SharedResourceViewError("view_unavailable")
            root = os.open(made, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=private)
            info = os.fstat(root)
            if not _directory(info, private=True) or _directory_identity(info) != self._root_identity:
                raise SharedResourceViewError("view_unavailable")
            self._probe(root)
        except (OSError, ValueError):
            if made is not None and private is not None:
                try:
                    current = os.stat(made, dir_fd=private, follow_symlinks=False)
                    expected = getattr(self, "_root_identity", None)
                    if expected is not None and _directory_identity(current) == expected:
                        os.rmdir(made, dir_fd=private)
                except OSError:
                    pass
            raise SharedResourceViewError("view_unavailable") from None
        finally:
            for descriptor in (root, private):
                if descriptor is not None:
                    os.close(descriptor)

    @property
    def root(self):
        return self._root

    @staticmethod
    def _probe(root):
        target_name = ".probe-" + secrets.token_hex(16) + ".tmp"
        link_name = ".probe-" + secrets.token_hex(16) + ".link"
        descriptor = reader = None
        owned = {}
        try:
            descriptor = os.open(target_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                 0o400, dir_fd=root)
            os.fchmod(descriptor, 0o400)
            target = os.fstat(descriptor)
            owned[target_name] = _link_identity(target)
            if (not stat.S_ISREG(target.st_mode) or target.st_size != 0 or target.st_nlink != 1
                    or stat.S_IMODE(target.st_mode) != 0o400 or target.st_uid != os.geteuid()):
                raise SharedResourceViewError("view_unavailable")
            os.symlink(target_name, link_name, dir_fd=root)
            link = os.stat(link_name, dir_fd=root, follow_symlinks=False)
            owned[link_name] = _link_identity(link)
            if (not stat.S_ISLNK(link.st_mode) or link.st_uid != os.geteuid() or link.st_nlink != 1
                    or os.readlink(link_name, dir_fd=root) != target_name):
                raise SharedResourceViewError("view_unavailable")
            reader = os.open(link_name, os.O_RDONLY | os.O_NONBLOCK, dir_fd=root)
            following = os.fstat(reader)
            if (SharedFileIdentity.from_stat(following) != SharedFileIdentity.from_stat(target)
                    or SharedFileIdentity.from_stat(os.stat(link_name, dir_fd=root))
                    != SharedFileIdentity.from_stat(target)):
                raise SharedResourceViewError("view_unavailable")
        finally:
            for opened in (reader, descriptor):
                if opened is not None:
                    os.close(opened)
            for name in (link_name, target_name):
                try:
                    current = os.stat(name, dir_fd=root, follow_symlinks=False)
                    if _link_identity(current) == owned.get(name):
                        os.unlink(name, dir_fd=root)
                except OSError:
                    pass

    def _open_root(self):
        private = root = None
        try:
            private = os.open(self._private, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            if _directory_identity(os.fstat(private)) != self._private_identity:
                raise SharedResourceViewError("view_conflict")
            root = os.open(self._name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=private)
            if _directory_identity(os.fstat(root)) != self._root_identity:
                raise SharedResourceViewError("view_conflict")
            result, root = root, None
            return result
        finally:
            for opened in (root, private):
                if opened is not None:
                    os.close(opened)

    def _open_bucket(self, root, bucket):
        known = self._buckets.get(bucket)
        try:
            info = os.stat(bucket, dir_fd=root, follow_symlinks=False)
        except FileNotFoundError:
            if known is not None:
                raise SharedResourceViewError("view_conflict") from None
            os.mkdir(bucket, 0o700, dir_fd=root)
            descriptor = os.open(bucket, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)
            info = os.fstat(descriptor)
            if not _directory(info, private=True):
                os.close(descriptor)
                raise SharedResourceViewError("view_conflict")
            self._buckets[bucket] = _directory_identity(info)
            return descriptor, True
        if known is None or not _directory(info, private=True) or _directory_identity(info) != known:
            raise SharedResourceViewError("view_conflict")
        descriptor = os.open(bucket, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)
        if _directory_identity(os.fstat(descriptor)) != known:
            os.close(descriptor)
            raise SharedResourceViewError("view_conflict")
        return descriptor, False

    @staticmethod
    def _same_link(bucket, name, owned):
        info = os.stat(name, dir_fd=bucket, follow_symlinks=False)
        return (stat.S_ISLNK(info.st_mode) and info.st_uid == os.geteuid() and info.st_nlink == 1
                and _link_identity(info) == owned.identity
                and os.readlink(name, dir_fd=bucket) == owned.target)

    def _request(self, lease, bucket, filename):
        if type(lease) is not SharedResourceLease or type(bucket) is not str or type(filename) is not str:
            raise SharedResourceViewError("invalid_view")
        request = _SDK_ROUTE.fullmatch(lease.requested_route)
        name = _FILE.fullmatch(filename)
        receipt = lease.receipt
        if request is None or name is None or not _BUCKET.fullmatch(bucket):
            raise SharedResourceViewError("invalid_view")
        version, kind, alias, generation = request.groups()
        try:
            selected = lease._store._record(lease.requested_route, receipt.size, receipt.md5)
        except SharedResourceError:
            raise SharedResourceViewError("invalid_view") from None
        expected = ("A" if kind == "assetbundle" else "R") + alias
        if (bucket != expected or receipt.kind != kind or receipt.upload_version != int(version)
                or receipt.generation != int(generation) or name[1] != receipt.md5
                or selected.cache_key != receipt.cache_key
                or kind == "assetbundle" and name[2] is not None
                or not _KEY.fullmatch(receipt.cache_key)):
            raise SharedResourceViewError("invalid_view")
        target = lease.path_hint
        canonical = lease._store._root
        if (target != canonical / receipt.cache_key[:2] / (receipt.cache_key + ".bin")
                or not target.is_absolute() or self._root.is_relative_to(canonical)
                or canonical.is_relative_to(self._root)):
            raise SharedResourceViewError("invalid_view")
        return target

    def materialize(self, lease, sdk_bucket, sdk_filename, *, cancel_event=None):
        """Create/reuse only a previously owned metadata view of an active lease."""
        _check_cancel(cancel_event)
        target = self._request(lease, sdk_bucket, sdk_filename)
        root = bucket = source = following = check = None
        created_link = created_bucket = False
        key, owned = (sdk_bucket, sdk_filename), None
        with self._lock:
            if self._closed:
                raise SharedResourceViewError("view_closed")
            try:
                source = lease.open_descriptor()
                root = self._open_root()
                bucket, created_bucket = self._open_bucket(root, sdk_bucket)
                _check_cancel(cancel_event)
                known = self._links.get(key)
                try:
                    info = os.stat(sdk_filename, dir_fd=bucket, follow_symlinks=False)
                except FileNotFoundError:
                    if known is not None or len(self._links) >= self._max_views:
                        raise SharedResourceViewError("view_conflict" if known else "capacity") from None
                    os.symlink(str(target), sdk_filename, dir_fd=bucket)
                    info = os.stat(sdk_filename, dir_fd=bucket, follow_symlinks=False)
                    owned = _OwnedLink(_link_identity(info), str(target))
                    if not self._same_link(bucket, sdk_filename, owned):
                        owned = None
                        raise SharedResourceViewError("view_conflict")
                    self._links[key] = owned
                    created_link = True
                else:
                    if known is None or known.target != str(target):
                        raise SharedResourceViewError("view_conflict")
                    owned = known
                if not self._same_link(bucket, sdk_filename, owned):
                    raise SharedResourceViewError("view_conflict")
                following = os.open(sdk_filename, os.O_RDONLY | os.O_NONBLOCK, dir_fd=bucket)
                if SharedFileIdentity.from_stat(os.fstat(following)) != lease.receipt.identity:
                    raise SharedResourceViewError("view_conflict")
                check = lease.open_descriptor()
                if SharedFileIdentity.from_stat(os.fstat(check)) != lease.receipt.identity:
                    raise SharedResourceViewError("view_conflict")
                if not self._same_link(bucket, sdk_filename, owned):
                    raise SharedResourceViewError("view_conflict")
                if _directory_identity(os.stat(sdk_bucket, dir_fd=root, follow_symlinks=False)) != self._buckets[sdk_bucket]:
                    raise SharedResourceViewError("view_conflict")
                fresh = self._open_root()
                os.close(fresh)
                _check_cancel(cancel_event)
                return SharedResourceView(str(self._root / sdk_bucket / sdk_filename),
                    lease.receipt.cache_key, lease.receipt.md5, lease.receipt.size, sdk_bucket, sdk_filename)
            except BaseException as error:
                if created_link and bucket is not None and owned is not None:
                    try:
                        if self._same_link(bucket, sdk_filename, owned):
                            os.unlink(sdk_filename, dir_fd=bucket)
                            self._links.pop(key, None)
                    except OSError:
                        pass
                if created_bucket and root is not None:
                    try:
                        current = os.stat(sdk_bucket, dir_fd=root, follow_symlinks=False)
                        if _directory_identity(current) == self._buckets.get(sdk_bucket):
                            os.rmdir(sdk_bucket, dir_fd=root)
                            self._buckets.pop(sdk_bucket, None)
                    except OSError:
                        pass
                if isinstance(error, SharedResourceViewError):
                    raise
                if isinstance(error, SharedResourceError):
                    raise SharedResourceViewError("lease_unavailable") from None
                if isinstance(error, OSError):
                    raise SharedResourceViewError("view_unavailable") from None
                raise
            finally:
                for opened in (check, following, source, bucket, root):
                    if opened is not None:
                        os.close(opened)

    def cleanup(self, *, quiescent=False):
        """Remove this session's owned metadata only after all readers stop.

        The native coordinator supplies the quiescent lifecycle assertion.
        Unknown entries stop cleanup before anything is removed. This is not
        a recursive cache remover or recovery tool for foreign directories.
        """
        if type(quiescent) is not bool or not quiescent:
            raise SharedResourceViewError("not_quiescent")
        root = None
        buckets = {}
        with self._lock:
            if self._closed:
                return {"removed_links": 0, "removed_buckets": 0, "root_removed": True}
            try:
                root = self._open_root()
                if set(os.listdir(root)) != set(self._buckets):
                    raise SharedResourceViewError("view_conflict")
                for name in self._buckets:
                    descriptor, created = self._open_bucket(root, name)
                    buckets[name] = descriptor
                    if created:
                        raise SharedResourceViewError("view_conflict")
                    expected = {filename for bucket, filename in self._links if bucket == name}
                    if set(os.listdir(descriptor)) != expected:
                        raise SharedResourceViewError("view_conflict")
                    for filename in expected:
                        if not self._same_link(descriptor, filename, self._links[(name, filename)]):
                            raise SharedResourceViewError("view_conflict")
                removed_links = 0
                for (name, filename), owned in tuple(self._links.items()):
                    if not self._same_link(buckets[name], filename, owned):
                        raise SharedResourceViewError("view_conflict")
                    os.unlink(filename, dir_fd=buckets[name])
                    del self._links[(name, filename)]
                    removed_links += 1
                removed_buckets = 0
                for name in tuple(self._buckets):
                    if _directory_identity(os.stat(name, dir_fd=root, follow_symlinks=False)) != self._buckets[name]:
                        raise SharedResourceViewError("view_conflict")
                    os.rmdir(name, dir_fd=root)
                    del self._buckets[name]
                    removed_buckets += 1
                private = os.open(self._private, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                try:
                    if (_directory_identity(os.fstat(private)) != self._private_identity
                            or _directory_identity(os.stat(self._name, dir_fd=private, follow_symlinks=False))
                            != self._root_identity):
                        raise SharedResourceViewError("view_conflict")
                    os.rmdir(self._name, dir_fd=private)
                finally:
                    os.close(private)
                self._closed = True
                return {"removed_links": removed_links, "removed_buckets": removed_buckets, "root_removed": True}
            except SharedResourceViewError:
                raise
            except OSError:
                raise SharedResourceViewError("view_unavailable") from None
            finally:
                for opened in (*buckets.values(), root):
                    if opened is not None:
                        os.close(opened)

    def status(self):
        with self._lock:
            return {"closed": self._closed, "owned_views": len(self._links),
                    "owned_buckets": len(self._buckets), "representation": "octo_raw_v1"}
