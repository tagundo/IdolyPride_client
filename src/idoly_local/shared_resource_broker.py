"""Private, bounded file IPC for native Octo workers in a unified application.

Only trusted native code supplies the app-private directory. The fresh session
contains 0700 req/rsp/views directories; 0600 requests and responses are
published atomically. No HTTP endpoint accepts this descriptor. The native
consumer owns response removal, and this broker removes only requests it read
through an unchanged, regular, single-link, same-UID descriptor.

Token16 is a random request correlation identifier, not an authentication
secret. A fresh positive session epoch prevents replay between server starts.
The private directory is the capability. Other code running as the same UID
must follow this protocol: POSIX rename cannot provide an atomic portable
no-replace operation against a malicious peer with the same directory access.

Payloads remain in OctoCache. Views contain symlinks only and persist when the
broker stops, because SDK asynchronous readers can still be using their names.
Explicit quiescent cleanup removes owned metadata, never resource bytes.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import os
from pathlib import Path
import queue
import re
import secrets
import stat
import struct
import threading
from time import monotonic as _monotonic

from .shared_resource_store import SharedResourceError, SharedResourceStore
from .shared_resource_views import SharedResourceViewError, SharedResourceViews


REQUEST = struct.Struct("<8sHBB16sQ I Q Q 6s H 16s")
RESPONSE = struct.Struct("<8sHBB16sQ16sQQQqqIIHH")
REQUEST_MAGIC, RESPONSE_MAGIC = b"IDRSREQ1", b"IDRSRSP1"
ACTIVE_MAGIC = b"IDRSACT1"
MAX_FILENAME, MAX_PATH = 64, 2048
READY, NOT_FOUND, CANCELLED, FAILED, UNSUPPORTED = range(5)
_NAME = re.compile(r"([0-9a-f]{32})\.req\Z")
_OBJECT = re.compile(rb"[A-Za-z0-9]{6}\Z")
_FILENAME = re.compile(r"([0-9a-f]{32})(\.[a-z0-9]{1,16})?\Z")
_PLATFORMS, _KINDS = {1: "android", 2: "ios"}, {1: "assetbundle", 2: "resources"}


class SharedResourceBrokerError(OSError):
    def __init__(self):
        super().__init__("Private shared resource broker unavailable")


@dataclass(frozen=True)
class SharedResourceRequest:
    platform: str
    kind: str
    token: bytes
    epoch: int
    upload_version: int
    generation: int
    size: int
    object_name: str
    filename: str
    md5: str

    @property
    def route(self):
        return f"/octo/{self.upload_version}/{self.kind}/{self.object_name}/{self.generation}"

    @property
    def bucket(self):
        return ("A" if self.kind == "assetbundle" else "R") + self.object_name


def decode_request(raw, *, epoch, token):
    """Validate the complete finite wire record before reconstructing a route."""
    if (type(raw) is not bytes or not REQUEST.size < len(raw) <= REQUEST.size + MAX_FILENAME
            or type(token) is not bytes or len(token) != 16):
        raise ValueError("Invalid shared resource request")
    (magic, schema, platform, kind, requested_token, requested_epoch, upload,
     generation, size, object_name, length, digest) = REQUEST.unpack_from(raw)
    if (magic != REQUEST_MAGIC or schema != 1 or platform not in _PLATFORMS
            or kind not in _KINDS or requested_token != token or token == bytes(16)
            or requested_epoch != epoch or not 1 <= requested_epoch <= 2**53 - 1
            or not 1 <= upload <= 2**31 - 1 or not 1 <= generation <= 2**64 - 1
            or not 1 <= size <= 2**31 - 1 or not _OBJECT.fullmatch(object_name)
            or not 1 <= length <= MAX_FILENAME or len(raw) != REQUEST.size + length):
        raise ValueError("Invalid shared resource request")
    try:
        filename = raw[REQUEST.size:].decode("ascii")
    except UnicodeError:
        raise ValueError("Invalid shared resource filename") from None
    matched = _FILENAME.fullmatch(filename)
    if (matched is None or matched[1] != digest.hex()
            or kind == 1 and matched[2] is not None):
        raise ValueError("Invalid shared resource filename")
    return SharedResourceRequest(_PLATFORMS[platform], _KINDS[kind], token, epoch,
        upload, generation, size, object_name.decode("ascii"), filename, digest.hex())


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mode, info.st_uid,
            info.st_nlink, info.st_mtime_ns, info.st_ctime_ns)


def _owned_file(info):
    return info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_nlink


def _private_directory(info):
    return (stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid()
            and stat.S_IMODE(info.st_mode) == 0o700)


def _directory_identity(info):
    return info.st_dev, info.st_ino, info.st_mode, info.st_uid


class SharedResourceBroker:
    """A finite worker queue; scanner/native threads never hash/download assets."""

    def __init__(self, store, app_private_dir, *, workers=4, max_pending=64,
                 max_responses=256, poll_seconds=0.025, response_ttl_seconds=600):
        if type(store) is not SharedResourceStore:
            raise TypeError("A verified shared resource store is required")
        for value, maximum in ((workers, 16), (max_pending, 1024), (max_responses, 4096)):
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError("Invalid shared broker capacity")
        if type(poll_seconds) not in (float, int) or not 0.005 <= poll_seconds <= 1:
            raise ValueError("Invalid shared broker poll interval")
        if type(response_ttl_seconds) not in (float, int) or not 600 <= response_ttl_seconds <= 3600:
            raise ValueError("Invalid shared broker response lifetime")
        self._store = store
        self._lock = threading.Lock()
        self._fs_lock, self._close_lock = threading.Lock(), threading.Lock()
        self._reaper = None
        self._stop = threading.Event()
        self._queue = queue.Queue(maxsize=max_pending)
        self._pending, self._seen, self._responses = set(), OrderedDict(), {}
        self._max_pending, self._max_responses = max_pending, max_responses
        self._poll_seconds = poll_seconds
        # Native waits at most five minutes. Only abandoned tiny response
        # records expire, after at least ten minutes; view names and reader
        # descriptors never expire while the SDK may still be using them.
        self._response_ttl = response_ttl_seconds
        self._received = self._ready = self._failed = self._rejected = self._ready_bytes = 0
        self._threads, self._fds, self._dir_identities = [], {}, {}
        self._active_identity = None
        self._epoch = secrets.randbelow(2**53 - 1) + 1
        supplied = Path(app_private_dir)
        if not supplied.is_absolute():
            raise ValueError("A trusted absolute app-private directory is required")
        self._private = supplied.resolve(strict=True)
        parent = root = None
        created = {}
        try:
            parent = os.open(self._private, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            info = os.fstat(parent)
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid():
                raise SharedResourceBrokerError()
            self._private_identity = _directory_identity(info)
            self._name = ".idoly-resource-ipc-" + secrets.token_hex(16)
            os.mkdir(self._name, 0o700, dir_fd=parent)
            self._root = self._private / self._name
            root = os.open(self._name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            created["root"] = _directory_identity(os.fstat(root))
            if not _private_directory(os.fstat(root)):
                raise SharedResourceBrokerError()
            self._dir_identities["root"] = _directory_identity(os.fstat(root))
            for name in ("req", "rsp", "views"):
                os.mkdir(name, 0o700, dir_fd=root)
                descriptor = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)
                self._fds[name] = descriptor
                created[name] = _directory_identity(os.fstat(descriptor))
                info = os.fstat(descriptor)
                if not _private_directory(info):
                    raise SharedResourceBrokerError()
                self._dir_identities[name] = _directory_identity(info)
            self._views = SharedResourceViews(self._root / "views")
            self._create_active(root)
            self._fds["root"] = root
            root = None
        except (OSError, ValueError):
            # Constructor failures can leave only the empty directories just
            # created here. Refuse foreign/replaced children; never rmtree.
            cleanup_root = root if root is not None else self._fds.get("root")
            if cleanup_root is not None:
                self._remove_active_from(cleanup_root)
                for name in ("views", "rsp", "req"):
                    try:
                        if _directory_identity(os.stat(name, dir_fd=cleanup_root,
                                follow_symlinks=False)) == created.get(name):
                            os.rmdir(name, dir_fd=cleanup_root)
                    except OSError:
                        pass
            if parent is not None and "root" in created:
                try:
                    if _directory_identity(os.stat(self._name, dir_fd=parent,
                            follow_symlinks=False)) == created["root"]:
                        os.rmdir(self._name, dir_fd=parent)
                except OSError:
                    pass
            for descriptor in self._fds.values():
                os.close(descriptor)
            self._fds.clear()
            raise SharedResourceBrokerError() from None
        finally:
            for descriptor in (root, parent):
                if descriptor is not None:
                    os.close(descriptor)
        for index in range(workers):
            self._threads.append(threading.Thread(target=self._worker,
                name=f"idoly-shared-resource-{index}", daemon=True))
        self._scanner = threading.Thread(target=self._scan_loop, name="idoly-shared-resource-ipc", daemon=True)
        for thread in (*self._threads, self._scanner):
            thread.start()

    def _create_active(self, root):
        """Publish a tiny private liveness record before native configuration."""
        temporary = ".active-" + secrets.token_hex(16) + ".tmp"
        descriptor, owned = None, None
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600, dir_fd=root)
            owned = _owned_file(os.fstat(descriptor))
            os.fchmod(descriptor, 0o600)
            owned = _owned_file(os.fstat(descriptor))
            with os.fdopen(descriptor, "wb") as stream:
                descriptor = None
                stream.write(ACTIVE_MAGIC + struct.pack("<Q", self._epoch))
                stream.flush()
                os.fsync(stream.fileno())
            os.rename(temporary, "active", src_dir_fd=root, dst_dir_fd=root)
            self._active_identity = _identity(os.stat("active", dir_fd=root, follow_symlinks=False))
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if owned is not None:
                try:
                    if _owned_file(os.stat(temporary, dir_fd=root, follow_symlinks=False)) == owned:
                        os.unlink(temporary, dir_fd=root)
                except FileNotFoundError:
                    pass

    def _remove_active_from(self, root):
        if self._active_identity is not None:
            try:
                info = os.stat("active", dir_fd=root, follow_symlinks=False)
                if _identity(info) == self._active_identity:
                    os.unlink("active", dir_fd=root)
            except OSError:
                pass

    def _remove_active(self):
        with self._fs_lock:
            root = self._fds.get("root")
            if root is not None:
                self._remove_active_from(root)

    def _check_directories(self):
        if self._stop.is_set():
            raise SharedResourceBrokerError()
        if (_directory_identity(self._private.stat()) != self._private_identity
                or _directory_identity(self._root.lstat()) != self._dir_identities["root"]):
            raise SharedResourceBrokerError()
        for name, descriptor in self._fds.items():
            info = os.fstat(descriptor)
            if not _private_directory(info) or _directory_identity(info) != self._dir_identities[name]:
                raise SharedResourceBrokerError()
            if name != "root" and _directory_identity(os.stat(name, dir_fd=self._fds["root"],
                    follow_symlinks=False)) != self._dir_identities[name]:
                raise SharedResourceBrokerError()
        if (self._active_identity is None
                or _identity(os.stat("active", dir_fd=self._fds["root"], follow_symlinks=False))
                != self._active_identity):
            raise SharedResourceBrokerError()

    def configuration(self):
        """Private native-only descriptor, excluded from exported diagnostics."""
        with self._fs_lock:
            self._check_directories()
            return {"schema": 1, "available": True, "directory": str(self._root),
                    "epoch": self._epoch, "representation": "octo_raw_v1"}

    def status(self):
        with self._lock:
            return {"schema": 1, "available": not self._stop.is_set(),
                "representation": "octo_raw_v1", "pending_requests": len(self._pending),
                "received_requests": self._received, "ready_requests": self._ready,
                "ready_bytes": self._ready_bytes,
                "failed_requests": self._failed, "rejected_requests": self._rejected}

    def _take_request(self, name, token):
        descriptor = None
        try:
            descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self._fds["req"])
            before = os.fstat(descriptor)
            if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid()
                    or before.st_nlink != 1 or stat.S_IMODE(before.st_mode) != 0o600
                    or not REQUEST.size < before.st_size <= REQUEST.size + MAX_FILENAME):
                return None
            raw = os.read(descriptor, REQUEST.size + MAX_FILENAME + 1)
            if (len(raw) != before.st_size or _identity(os.fstat(descriptor)) != _identity(before)
                    or _identity(os.stat(name, dir_fd=self._fds["req"], follow_symlinks=False))
                    != _identity(before)):
                return None
            os.unlink(name, dir_fd=self._fds["req"])
            try:
                return decode_request(raw, epoch=self._epoch, token=token)
            except ValueError:
                with self._lock:
                    self._rejected += 1
                return None
        except OSError:
            return None
        finally:
            if descriptor is not None:
                os.close(descriptor)

    def _scan(self):
        self._check_directories()
        with self._lock:
            for name, (identity, created) in tuple(self._responses.items()):
                try:
                    info = os.stat(name, dir_fd=self._fds["rsp"], follow_symlinks=False)
                except FileNotFoundError:
                    del self._responses[name]
                    continue
                if _identity(info) != identity:
                    raise SharedResourceBrokerError()
                if _monotonic() - created >= self._response_ttl:
                    try:
                        os.unlink(name, dir_fd=self._fds["rsp"])
                    except FileNotFoundError:
                        pass
                    del self._responses[name]
            if len(self._responses) + len(self._pending) >= self._max_responses:
                return
        with os.scandir(self._fds["req"]) as entries:
            for index, entry in enumerate(entries):
                if index >= 128 or self._stop.is_set():
                    break
                matched = _NAME.fullmatch(entry.name)
                if matched is None:
                    continue
                token = bytes.fromhex(matched[1])
                with self._lock:
                    if (token in self._pending or token in self._seen
                            or len(self._pending) >= self._max_pending
                            or len(self._responses) + len(self._pending) >= self._max_responses):
                        continue
                request = self._take_request(entry.name, token)
                if request is None:
                    continue
                with self._lock:
                    self._pending.add(token)
                    self._seen[token] = None
                    while len(self._seen) > 32768:
                        self._seen.popitem(last=False)
                    self._received += 1
                self._queue.put_nowait(request)

    def _scan_loop(self):
        while not self._stop.is_set():
            try:
                self._scan()
            except (OSError, ValueError, queue.Full):
                self.close()
                break
            self._stop.wait(self._poll_seconds)

    def _resolve(self, request):
        if self._stop.is_set():
            return CANCELLED, None, None
        if request.platform != (
                "android" if self._store._manifest.application_version == 205051 else "ios"):
            return UNSUPPORTED, None, None
        try:
            self._store.prepare(request.route, expected_size=request.size,
                expected_md5=request.md5, cancel_event=self._stop)
            lease = self._store.acquire_cached(request.route, expected_size=request.size,
                expected_md5=request.md5, cancel_event=self._stop)
            if lease is None:
                return NOT_FOUND, None, None
            with lease:
                view = self._views.materialize(lease, request.bucket, request.filename, cancel_event=self._stop)
                path = view.path.encode("utf-8")
                if not 1 <= len(path) <= MAX_PATH or not view.path.startswith(str(self._root / "views") + "/"):
                    return FAILED, None, None
                return READY, lease.receipt, path
        except SharedResourceError as error:
            return (CANCELLED if error.code in ("cancelled", "store_closed") else
                    NOT_FOUND if error.code in ("not_found", "cache_unavailable") else FAILED), None, None
        except SharedResourceViewError as error:
            return (CANCELLED if error.code == "cancelled" else FAILED), None, None

    def _publish(self, request, status, receipt, path):
        self._check_directories()
        if receipt is None:
            digest, size, device, inode, mtime, ctime, mode, links = bytes(16), 0, 0, 0, 0, 0, 0, 0
            path = b""
        else:
            stamp = receipt.identity
            digest, size = bytes.fromhex(receipt.md5), receipt.size
            device, inode, mtime, ctime, mode, links = (stamp.device, stamp.inode,
                stamp.mtime_ns, stamp.ctime_ns, stamp.mode, stamp.links)
        raw = RESPONSE.pack(RESPONSE_MAGIC, 1, status, 1, request.token, self._epoch,
            digest, size, device, inode, mtime, ctime, mode, links, len(path), 0) + path
        name = request.token.hex() + ".rsp"
        temporary = ".response-" + secrets.token_hex(16) + ".tmp"
        descriptor, owned = None, None
        try:
            try:
                os.stat(name, dir_fd=self._fds["rsp"], follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise SharedResourceBrokerError()
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600, dir_fd=self._fds["rsp"])
            owned = _owned_file(os.fstat(descriptor))
            os.fchmod(descriptor, 0o600)
            owned = _owned_file(os.fstat(descriptor))
            with os.fdopen(descriptor, "wb") as stream:
                descriptor = None
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            self._check_directories()
            os.rename(temporary, name, src_dir_fd=self._fds["rsp"], dst_dir_fd=self._fds["rsp"])
            with self._lock:
                self._responses[name] = (_identity(os.stat(name, dir_fd=self._fds["rsp"],
                    follow_symlinks=False)), _monotonic())
                if status == READY:
                    self._ready = min(2**53 - 1, self._ready + 1)
                    self._ready_bytes = min(2**53 - 1, self._ready_bytes + receipt.size)
                else:
                    self._failed += 1
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if owned is not None:
                try:
                    if _owned_file(os.stat(temporary, dir_fd=self._fds["rsp"], follow_symlinks=False)) == owned:
                        os.unlink(temporary, dir_fd=self._fds["rsp"])
                except FileNotFoundError:
                    pass

    def _worker(self):
        while not self._stop.is_set():
            try:
                request = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                status, receipt, path = self._resolve(request)
                if not self._stop.is_set():
                    self._publish(request, status, receipt, path)
            except (OSError, ValueError, OverflowError, struct.error):
                with self._lock:
                    self._failed += 1
            finally:
                with self._lock:
                    self._pending.discard(request.token)
                self._queue.task_done()

    def close(self):
        """Stop work/handoffs; active SDK view names and cache bytes remain."""
        with self._close_lock:
            self._stop.set()
            self._remove_active()
            if threading.current_thread() is not self._scanner:
                self._scanner.join(timeout=1)
            if self._reaper is None:
                self._reaper = threading.Thread(target=self._release_after_workers,
                    name="idoly-shared-resource-stop", daemon=True)
                self._reaper.start()

    def _release_after_workers(self):
        self._scanner.join()
        for thread in self._threads:
            thread.join()
        with self._fs_lock:
            for descriptor in self._fds.values():
                os.close(descriptor)
            self._fds.clear()
        with self._lock:
            self._pending.clear()

    def _restore_cleanup_descriptors(self):
        if self._fds:
            return
        parent = root = None
        opened = {}
        try:
            parent = os.open(self._private, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            if _directory_identity(os.fstat(parent)) != self._private_identity:
                raise SharedResourceBrokerError()
            root = os.open(self._name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            if _directory_identity(os.fstat(root)) != self._dir_identities["root"]:
                raise SharedResourceBrokerError()
            opened["root"], root = root, None
            for name in ("req", "rsp", "views"):
                descriptor = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=opened["root"])
                opened[name] = descriptor
                if _directory_identity(os.fstat(descriptor)) != self._dir_identities[name]:
                    raise SharedResourceBrokerError()
            self._fds.update(opened)
            opened.clear()
        finally:
            for descriptor in (*opened.values(), root, parent):
                if descriptor is not None:
                    os.close(descriptor)

    def cleanup(self, *, quiescent=False):
        if quiescent is not True:
            raise SharedResourceBrokerError()
        self.close()
        if self._scanner.is_alive() or any(thread.is_alive() for thread in self._threads):
            raise SharedResourceBrokerError()
        if not self._root.exists():
            return
        with self._fs_lock:
            self._restore_cleanup_descriptors()
            try:
                self._cleanup_metadata()
            finally:
                for descriptor in self._fds.values():
                    os.close(descriptor)
                self._fds.clear()

    def _cleanup_metadata(self):
        # No blanket recursive deletion. Caller may retry after consuming its
        # response files; foreign or pending request files are preserved.
        if os.listdir(self._fds["req"]):
            raise SharedResourceBrokerError()
        for name, (expected, _created) in tuple(self._responses.items()):
            try:
                info = os.stat(name, dir_fd=self._fds["rsp"], follow_symlinks=False)
            except FileNotFoundError:
                continue
            if _identity(info) != expected:
                raise SharedResourceBrokerError()
        if set(os.listdir(self._fds["rsp"])) - self._responses.keys():
            raise SharedResourceBrokerError()
        self._views.cleanup(quiescent=True)
        for name, (expected, _created) in tuple(self._responses.items()):
            try:
                info = os.stat(name, dir_fd=self._fds["rsp"], follow_symlinks=False)
            except FileNotFoundError:
                continue
            if _identity(info) == expected:
                os.unlink(name, dir_fd=self._fds["rsp"])
        for name in ("req", "rsp", "views"):
            os.rmdir(name, dir_fd=self._fds["root"])
        os.rmdir(self._root)
