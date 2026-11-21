"""Private same-UID IPC for offline MV audio preparation.

The caller supplies a trusted app-private root and the existing verified Octo
store. Requests carry only an exact logical music name and source-clip shape,
never URLs or filesystem paths. One worker prepares a uniquely named private
bundle; the original cache and game AudioClip remain unchanged.

Prepared files survive close: Unity may still be loading their predictable
names asynchronously. Only small response records expire. Payload cleanup
requires an explicit future quiescent lifecycle, so count/byte caps bound this
session's prepared files. A private directory is the capability boundary; peers
with that same UID must follow the atomic publication protocol.
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
from time import monotonic

from .mp4_audio_bundle import AudioBundleError, MAX_BUNDLE_BYTES, prepare_audio_bundle
from .shared_resource_store import SharedResourceError, SharedResourceStore

REQUEST = struct.Struct("<8sHBBQ16s16sHBBIQ")
RESPONSE = struct.Struct("<8sHBBQ16s16s")
ACTIVE = struct.Struct("<8sQ")
REQUEST_MAGIC, RESPONSE_MAGIC, ACTIVE_MAGIC = b"IDMPAUD1", b"IDMPARS1", b"IDMPACT1"
READY, NOT_FOUND, FAILED, CANCELLED, UNSUPPORTED = range(5)
MAX_REQUEST = 260
_CLIP = re.compile(r"sud_music_[a-z0-9][a-z0-9_-]{0,111}\Z")
_REQUEST_FILE = re.compile(r"([0-9a-f]{32})\.req\Z")


class AudioBrokerError(OSError):
    def __init__(self):
        super().__init__("Private MP4 audio preparation unavailable")


@dataclass(frozen=True)
class AudioRequest:
    platform: str
    epoch: int
    capability: bytes
    request_id: bytes
    clip_name: str
    channels: int
    sample_rate: int
    samples: int


def decode_request(raw, *, epoch, capability, request_id):
    if type(raw) is not bytes or not REQUEST.size < len(raw) <= MAX_REQUEST:
        raise AudioBrokerError()
    (magic, schema, platform, reserved, received_epoch, received_capability, received_id,
     length, channels, reserved2, rate, samples) = REQUEST.unpack_from(raw)
    if (magic != REQUEST_MAGIC or schema != 1 or platform not in (1, 2) or reserved != 0
            or reserved2 != 0 or received_epoch != epoch or not 1 <= received_epoch <= 2**53 - 1
            or type(capability) is not bytes or len(capability) != 16
            or not secrets.compare_digest(received_capability, capability)
            or type(request_id) is not bytes or len(request_id) != 16
            or received_id != request_id or request_id == bytes(16)
            or channels not in (1, 2) or rate not in (44100, 48000)
            or not 1 <= samples <= rate * 900 or not 1 <= length <= 192
            or len(raw) != REQUEST.size + length):
        raise AudioBrokerError()
    try:
        name = raw[REQUEST.size:].decode("ascii")
    except UnicodeError:
        raise AudioBrokerError() from None
    if _CLIP.fullmatch(name) is None:
        raise AudioBrokerError()
    return AudioRequest("android" if platform == 1 else "ios", epoch, capability,
                        request_id, name, channels, rate, samples)


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mode, info.st_uid,
            info.st_nlink, info.st_mtime_ns, info.st_ctime_ns)


def _owned_file(info):
    return info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_nlink


def _directory(info):
    return info.st_dev, info.st_ino, info.st_mode, info.st_uid


def _private(info):
    return (stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid()
            and stat.S_IMODE(info.st_mode) == 0o700)


class MP4AudioBroker:
    """One preparation worker, eight pending requests, immutable private clones."""

    def __init__(self, store, app_private_dir, *, max_pending=8, max_responses=64,
                 max_prepared=64, max_prepared_bytes=512 * 1024 * 1024,
                 poll_seconds=0.1):
        if type(store) is not SharedResourceStore:
            raise TypeError("A verified shared resource store is required")
        for value, maximum in ((max_pending, 8), (max_responses, 64), (max_prepared, 64)):
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError("Invalid MP4 audio preparation capacity")
        if (type(max_prepared_bytes) is not int or not 1 <= max_prepared_bytes <= 512 * 1024 * 1024
                or type(poll_seconds) not in (int, float) or not 0.005 <= poll_seconds <= 1):
            raise ValueError("Invalid MP4 audio preparation limits")
        supplied = Path(app_private_dir)
        if not supplied.is_absolute():
            raise ValueError("A trusted absolute app-private directory is required")
        self._private = supplied.resolve(strict=True)
        self._store, self._records = store, store._records
        self._platform = "android" if store._version == 205051 else "ios"
        self._lock, self._fs_lock, self._close_lock = threading.Lock(), threading.Lock(), threading.Lock()
        self._stop = threading.Event()
        self._queue = queue.Queue(maxsize=max_pending)
        self._pending, self._seen, self._responses = set(), OrderedDict(), {}
        self._selected, self._prepared = OrderedDict(), {}
        self._max_pending, self._max_responses = max_pending, max_responses
        self._max_prepared, self._max_prepared_bytes = max_prepared, max_prepared_bytes
        self._poll_seconds = poll_seconds
        self._received = self._ready = self._failed = self._rejected = self._prepared_bytes = 0
        self._epoch, self._capability = secrets.randbelow(2**53 - 1) + 1, secrets.token_bytes(16)
        self._fds, self._directories = {}, {}
        self._active_identity = self._reaper = None
        from .mp4_export_library import MP4ExportLibrary
        self._export_library = MP4ExportLibrary(self._private)
        try:
            self._create_session()
        except BaseException:
            self._export_library.close()
            raise
        self._worker_thread = threading.Thread(target=self._worker, name="idoly-mp4-audio", daemon=True)
        self._scanner_thread = threading.Thread(target=self._scan_loop, name="idoly-mp4-audio-ipc", daemon=True)
        try:
            self._worker_thread.start()
            self._scanner_thread.start()
        except RuntimeError:
            self.close()
            raise AudioBrokerError() from None

    def _create_session(self):
        parent = root = None
        try:
            parent = os.open(self._private, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            info = os.fstat(parent)
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid():
                raise AudioBrokerError()
            self._private_identity = _directory(info)
            for _ in range(8):
                self._name = ".idoly-mp4-audio-" + secrets.token_hex(16)
                try:
                    os.mkdir(self._name, 0o700, dir_fd=parent)
                    break
                except FileExistsError:
                    continue
            else:
                raise AudioBrokerError()
            self._root = self._private / self._name
            root = os.open(self._name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            self._fds["root"] = root
            root = None
            self._directories["root"] = _directory(os.fstat(self._fds["root"]))
            if not _private(os.fstat(self._fds["root"])):
                raise AudioBrokerError()
            for name in ("req", "rsp", "prepared", "exports", "tmp"):
                os.mkdir(name, 0o700, dir_fd=self._fds["root"])
                descriptor = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=self._fds["root"])
                self._fds[name] = descriptor
                info = os.fstat(descriptor)
                if not _private(info):
                    raise AudioBrokerError()
                self._directories[name] = _directory(info)
            self._active_identity = self._publish("root", "active", ACTIVE.pack(ACTIVE_MAGIC, self._epoch), 0o600)
            if self._active_identity is None:
                raise AudioBrokerError()
        except (OSError, ValueError):
            self._retire_active_unlocked()
            for name in ("tmp", "exports", "prepared", "rsp", "req"):
                try:
                    if _directory(os.stat(name, dir_fd=self._fds["root"], follow_symlinks=False)) == self._directories.get(name):
                        os.rmdir(name, dir_fd=self._fds["root"])
                except (OSError, KeyError):
                    pass
            if parent is not None and "root" in self._directories:
                try:
                    if _directory(os.stat(self._name, dir_fd=parent, follow_symlinks=False)) == self._directories["root"]:
                        os.rmdir(self._name, dir_fd=parent)
                except OSError:
                    pass
            for descriptor in self._fds.values():
                os.close(descriptor)
            self._fds.clear()
            raise AudioBrokerError() from None
        finally:
            for descriptor in (root, parent):
                if descriptor is not None:
                    os.close(descriptor)

    def _check(self, *, active=True):
        if self._stop.is_set():
            raise AudioBrokerError()
        if (_directory(self._private.stat()) != self._private_identity
                or _directory(self._root.lstat()) != self._directories["root"]):
            raise AudioBrokerError()
        for name, descriptor in self._fds.items():
            info = os.fstat(descriptor)
            if not _private(info) or _directory(info) != self._directories[name]:
                raise AudioBrokerError()
            if name != "root" and _directory(os.stat(name, dir_fd=self._fds["root"],
                    follow_symlinks=False)) != self._directories[name]:
                raise AudioBrokerError()
        if active and (self._active_identity is None or _identity(os.stat("active",
                dir_fd=self._fds["root"], follow_symlinks=False)) != self._active_identity):
            raise AudioBrokerError()

    def configuration(self):
        """Private native descriptor; capability and paths never enter status."""
        from .mp4_titles import title_catalog
        with self._fs_lock:
            self._check()
            return {"schema": 1, "available": True, "directory": str(self._root),
                    "epoch": self._epoch, "capability": self._capability.hex(),
                    "export_directory": str(self._root / "exports"),
                    "temporary_directory": str(self._root / "tmp"),
                    "title_catalog": title_catalog(),
                    **self._export_library.configuration()}

    def status(self):
        with self._lock:
            return {"schema": 1, "available": not self._stop.is_set(),
                "pending_requests": len(self._pending), "received_requests": self._received,
                "ready_requests": self._ready, "failed_requests": self._failed,
                "rejected_requests": self._rejected, "prepared_files": len(self._prepared),
                "prepared_bytes": self._prepared_bytes, "prepared_limit": self._max_prepared,
                "prepared_byte_limit": self._max_prepared_bytes}

    def _publish(self, directory, name, raw, mode):
        descriptor, owned = None, None
        temporary = ".audio-" + secrets.token_hex(16) + ".tmp"
        target = self._fds[directory]
        try:
            try:
                os.stat(name, dir_fd=target, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise AudioBrokerError()
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                 0o600, dir_fd=target)
            owned = _owned_file(os.fstat(descriptor))
            with os.fdopen(descriptor, "wb") as stream:
                descriptor = None
                stream.write(raw)
                stream.flush()
                os.fchmod(stream.fileno(), mode)
                owned = _owned_file(os.fstat(stream.fileno()))
                os.fsync(stream.fileno())
                before = os.fstat(stream.fileno())
                if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid()
                        or before.st_nlink != 1 or stat.S_IMODE(before.st_mode) != mode
                        or before.st_size != len(raw)):
                    raise AudioBrokerError()
                try:
                    os.stat(name, dir_fd=target, follow_symlinks=False)
                except FileNotFoundError:
                    pass
                else:
                    raise AudioBrokerError()
                if _identity(os.stat(temporary, dir_fd=target, follow_symlinks=False)) != _identity(before):
                    raise AudioBrokerError()
                os.rename(temporary, name, src_dir_fd=target, dst_dir_fd=target)
                try:
                    published = os.stat(name, dir_fd=target, follow_symlinks=False)
                except FileNotFoundError:
                    if directory == "rsp":
                        return None  # Native already consumed its tiny response.
                    raise
                if _identity(published) != _identity(os.fstat(stream.fileno())):
                    raise AudioBrokerError()
                return _identity(published)
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if owned is not None:
                try:
                    if _owned_file(os.stat(temporary, dir_fd=target, follow_symlinks=False)) == owned:
                        os.unlink(temporary, dir_fd=target)
                except FileNotFoundError:
                    pass

    def _take(self, name, request_id):
        descriptor = None
        try:
            descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self._fds["req"])
            before = os.fstat(descriptor)
            if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid()
                    or before.st_nlink != 1 or stat.S_IMODE(before.st_mode) != 0o600
                    or not REQUEST.size < before.st_size <= MAX_REQUEST):
                return None
            raw = os.read(descriptor, MAX_REQUEST + 1)
            if (len(raw) != before.st_size or _identity(os.fstat(descriptor)) != _identity(before)
                    or _identity(os.stat(name, dir_fd=self._fds["req"], follow_symlinks=False)) != _identity(before)):
                return None
            os.unlink(name, dir_fd=self._fds["req"])
            try:
                return decode_request(raw, epoch=self._epoch, capability=self._capability, request_id=request_id)
            except AudioBrokerError:
                with self._lock:
                    self._rejected += 1
                return None
        except OSError:
            return None
        finally:
            if descriptor is not None:
                os.close(descriptor)

    def _scan(self):
        self._check()
        with self._lock:
            self._prune_prepared_locked()
            for name, (identity, _created) in tuple(self._responses.items()):
                try:
                    info = os.stat(name, dir_fd=self._fds["rsp"], follow_symlinks=False)
                except FileNotFoundError:
                    del self._responses[name]
                    continue
                if _identity(info) != identity:
                    raise AudioBrokerError()
                # A suspended Unity owner may need this response hours later.
                # Keep both success and error replies until it consumes them
                # or this capability session retires. Capacity stays bounded
                # by max_responses, including requests still in preparation.
            if len(self._responses) + len(self._pending) >= self._max_responses:
                return
        with os.scandir(self._fds["req"]) as entries:
            for index, entry in enumerate(entries):
                if index >= 128 or self._stop.is_set():
                    return
                matched = _REQUEST_FILE.fullmatch(entry.name)
                if matched is None:
                    continue
                request_id = bytes.fromhex(matched[1])
                with self._lock:
                    if (request_id in self._pending or len(self._pending) >= self._max_pending
                            or len(self._responses) + len(self._pending) >= self._max_responses):
                        continue
                request = self._take(entry.name, request_id)
                if request is None:
                    continue
                with self._lock:
                    if request_id in self._seen:
                        self._rejected += 1
                        continue
                    self._pending.add(request_id)
                    self._seen[request_id] = None
                    while len(self._seen) > 4096:
                        self._seen.popitem(last=False)
                    self._received += 1
                self._queue.put_nowait(request)

    def _prune_prepared_locked(self):
        """Native may retire only its quiescent, already unloaded clone.

        Missing owned files release quota. Existing names with a different
        identity are a conflict, never permission to adopt/delete that file.
        The caller holds the state lock; this method never unlinks payloads.
        """
        for filename, identity in tuple(self._prepared.items()):
            try:
                info = os.stat(filename, dir_fd=self._fds["prepared"], follow_symlinks=False)
            except FileNotFoundError:
                del self._prepared[filename]
                self._prepared_bytes -= identity[2]
                continue
            if _identity(info) != identity:
                raise AudioBrokerError()

    def _scan_loop(self):
        while not self._stop.is_set():
            try:
                self._scan()
            except (OSError, ValueError, queue.Full):
                self.close()
                return
            self._stop.wait(self._poll_seconds)

    def _select(self, name):
        if name in self._selected:
            self._selected.move_to_end(name)
            return self._selected[name]
        candidates = {record.cache_key: record for record in self._records.values()
                      if record.kind == "assetbundle" and record.name == name}
        selected = next(iter(candidates.values())) if len(candidates) == 1 else None
        self._selected[name] = selected
        while len(self._selected) > 128:
            self._selected.popitem(last=False)
        return selected

    def _prepare(self, request):
        if request.platform != self._platform:
            return UNSUPPORTED
        record = self._select(request.clip_name)
        if record is None:
            return NOT_FOUND
        if not 0 < record.size <= MAX_BUNDLE_BYTES:
            return UNSUPPORTED
        with self._lock:
            self._prune_prepared_locked()
            if len(self._prepared) >= self._max_prepared:
                return FAILED
        route = f"/octo/{record.upload_version}/assetbundle/{record.object_name}/{record.generation}"
        try:
            self._store.prepare(route, expected_size=record.size, expected_md5=record.md5, cancel_event=self._stop)
            lease = self._store.acquire_cached(route, expected_size=record.size,
                expected_md5=record.md5, cancel_event=self._stop)
            if lease is None:
                return FAILED
            with lease, lease.reader() as stream:
                raw = stream.read(record.size + 1)
                if len(raw) != record.size or self._stop.is_set():
                    return CANCELLED if self._stop.is_set() else FAILED
                result = prepare_audio_bundle(raw, name=record.name, expected_size=record.size,
                    expected_md5=record.md5, expected_platform=request.platform)
            if result.channels != request.channels or result.frequency != request.sample_rate:
                return UNSUPPORTED
            if self._stop.is_set():
                return CANCELLED
            with self._lock:
                self._prune_prepared_locked()
                if self._prepared_bytes + len(result.bundle_bytes) > self._max_prepared_bytes:
                    return FAILED
            self._check()
            free = os.statvfs(self._root)
            if free.f_bavail * free.f_frsize < len(result.bundle_bytes) + 64 * 1024 * 1024:
                return FAILED
            filename = request.request_id.hex() + ".bundle"
            identity = self._publish("prepared", filename, result.bundle_bytes, 0o400)
            with self._lock:
                self._prepared[filename] = identity
                self._prepared_bytes += len(result.bundle_bytes)
            return READY
        except SharedResourceError as error:
            return (CANCELLED if error.code in ("cancelled", "store_closed") else
                    NOT_FOUND if error.code == "not_found" else FAILED)
        except AudioBundleError as error:
            return UNSUPPORTED if error.code.endswith("_unsupported") else FAILED

    def _respond(self, request, status):
        self._check()
        raw = RESPONSE.pack(RESPONSE_MAGIC, 1, status, 0, self._epoch,
                            self._capability, request.request_id)
        filename = request.request_id.hex() + ".rsp"
        identity = self._publish("rsp", filename, raw, 0o600)
        with self._lock:
            if identity is not None:
                self._responses[filename] = identity, monotonic()
            if status == READY:
                self._ready += 1
            else:
                self._failed += 1

    def _worker(self):
        while not self._stop.is_set():
            try:
                request = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                status = self._prepare(request)
                if not self._stop.is_set():
                    self._respond(request, status)
            except Exception:
                if not self._stop.is_set():
                    try:
                        self._respond(request, FAILED)
                    except Exception:
                        with self._lock:
                            self._failed += 1
            finally:
                with self._lock:
                    self._pending.discard(request.request_id)
                self._queue.task_done()

    def _retire_active_unlocked(self):
        root = self._fds.get("root")
        if root is not None and self._active_identity is not None:
            try:
                if _identity(os.stat("active", dir_fd=root, follow_symlinks=False)) == self._active_identity:
                    os.unlink("active", dir_fd=root)
            except OSError:
                pass

    def close(self):
        """Retire liveness immediately; prepared bundles and game files survive."""
        self._stop.set()
        with self._fs_lock:
            self._retire_active_unlocked()
        with self._close_lock:
            if self._reaper is None:
                self._reaper = threading.Thread(target=self._reap, name="idoly-mp4-audio-stop", daemon=True)
                self._reaper.start()

    def _reap(self):
        for thread in (self._scanner_thread, self._worker_thread):
            if thread.ident is not None:
                thread.join()
        with self._fs_lock:
            for descriptor in self._fds.values():
                os.close(descriptor)
            self._fds.clear()
            self._export_library.close()
        with self._lock:
            self._pending.clear()
