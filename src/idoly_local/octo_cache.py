"""Verified, on-demand copies of original Octo CDN objects.

Only immutable records from the manifest whitelist enter this boundary. A
requested URL is never an upstream address. The cache publishes a file only
after its complete size and original MD5 agree; HTTP response/range progress
belongs to the caller and is separate from these upstream observations.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import math
import os
from pathlib import Path
import re
import secrets
import stat
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .octo_manifest import OctoObject


_HOST = "d2ilil7yh5oi1v.cloudfront.net"
_NAME = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_MD5 = re.compile(r"[0-9a-f]{32}\Z")
_CHUNK = 64 * 1024
_ERROR_CODES = frozenset(("cache_io", "cache_closed", "download_disabled", "budget_exceeded",
                          "upstream_redirect", "upstream_http", "upstream_timeout", "upstream_size",
                          "upstream_encoding", "upstream_data", "upstream_digest", "conflicting_metadata"))


class OctoCacheError(OSError):
    """A fixed error code without upstream headers, URLs, or account data."""

    def __init__(self, code="cache_io"):
        self.code = code if isinstance(code, str) and code in _ERROR_CODES else "cache_io"
        super().__init__("Octo object unavailable: " + self.code)


class OctoCacheMiss(OctoCacheError):
    def __init__(self):
        super().__init__("download_disabled")


def _cdn_origin(url):
    try:
        parsed = urlsplit(url)
        return (parsed.scheme == "https" and parsed.hostname == _HOST
                and parsed.port in (None, 443) and parsed.username is None
                and parsed.password is None and not parsed.fragment)
    except (TypeError, ValueError):
        return False


class _CDNRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        if not _cdn_origin(newurl):
            raise OctoCacheError("upstream_redirect")
        return super().redirect_request(request, fp, code, message, headers, newurl)


def open_upstream(url, *, timeout):
    """Use inherited proxy/CA trust and retain normal HTTPS verification."""
    if not _cdn_origin(url):
        raise OctoCacheError("upstream_redirect")
    request = Request(url, headers={"Accept-Encoding": "identity", "User-Agent": "IdolyLocalAssets/0.1"})
    return build_opener(_CDNRedirects()).open(request, timeout=timeout)


@dataclass
class _Flight:
    signature: tuple
    done: threading.Event = field(default_factory=threading.Event)
    error: str | None = None


def _stamp(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
            info.st_ctime_ns, info.st_mode, info.st_nlink)


class OctoCache:
    """A bounded cache for manifest-selected, unchanged upstream bytes.

    ``fetcher(url, timeout=seconds)`` returns a context-managed binary response
    with status 200, read(), optional headers, and optional geturl(). Platform
    adapters must retain HTTPS verification and the fixed CDN origin. The
    default adapter also rejects redirects to other origins.

    ``max_download_bytes`` is an optional lifetime allowance: each upstream
    attempt reserves the manifest's complete size, including failed attempts.
    It is not a claim about bytes already transferred. Events report actual
    upstream bytes, and cache hits report zero newly received bytes.

    ``close()`` rejects new work and prevents subsequent writes/publication. It
    closes available response handles outside the cache lock. Opening DNS or
    response headers has no handle to close yet and remains bounded by the
    configured transport timeout; an arriving response is then discarded.
    """

    def __init__(self, root, *, fetcher=None, on_event=None,
                 max_object_bytes=512 * 1024 * 1024, max_parallel=2,
                 timeout=30, total_timeout=300, allow_download=True,
                 max_download_bytes=None):
        if (type(max_object_bytes) is not int or not 1 <= max_object_bytes <= 2**31-1
                or type(max_parallel) is not int or not 1 <= max_parallel <= 16
                or type(allow_download) is not bool
                or (max_download_bytes is not None and
                    (type(max_download_bytes) is not int or max_download_bytes < 1))):
            raise ValueError("Invalid Octo cache limits")
        for value in (timeout, total_timeout):
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError("Invalid Octo cache timeout")
        if (fetcher is not None and not callable(fetcher)) or (on_event is not None and not callable(on_event)):
            raise ValueError("Invalid Octo cache callback")
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not self.root.is_dir():
            raise ValueError("Octo cache root is not a directory")
        root_info = self.root.stat()
        self._root_identity = root_info.st_dev, root_info.st_ino
        self.fetcher, self.on_event = fetcher or open_upstream, on_event
        self.max_object_bytes, self.timeout, self.total_timeout = max_object_bytes, timeout, total_timeout
        self.allow_download, self.max_download_bytes = allow_download, max_download_bytes
        self._allowance_spent = 0
        self._parallel = threading.BoundedSemaphore(max_parallel)
        self._lock = threading.Lock()
        self._commit_lock = threading.Lock()
        self._closed = threading.Event()
        self._responses = {}
        self._flights, self._verified = {}, {}

    def _require_open(self):
        if self._closed.is_set():
            raise OctoCacheError("cache_closed")

    def close(self):
        """Cancel available transports without holding a lock during close()."""
        with self._commit_lock:
            if self._closed.is_set():
                return
            self._closed.set()
        with self._lock:
            responses = list(self._responses.values())
            for flight in self._flights.values():
                flight.error = "cache_closed"
                flight.done.set()
        for response in responses:
            try:
                response.close()
            except Exception:
                # The closed-state barrier still prevents publication, even
                # when a platform transport cannot interrupt a pending read.
                pass

    def _record(self, record):
        if (not isinstance(record, OctoObject) or record.kind not in ("assetbundle", "resources")
                or type(record.upload_version) is not int or not 1 <= record.upload_version <= 2**31-1
                or type(record.generation) is not int or not 1 <= record.generation <= 2**64-1
                or type(record.size) is not int or not 1 <= record.size <= self.max_object_bytes
                or not isinstance(record.object_name, str) or not _NAME.fullmatch(record.object_name)
                or not isinstance(record.md5, str) or not _MD5.fullmatch(record.md5)):
            raise ValueError("Invalid Octo object metadata")
        # Snapshot a frozen backend record rather than retain a request object.
        return OctoObject(record.kind, record.upload_version, record.object_name,
                          record.generation, record.size, record.md5, record.name)

    def _notify(self, record, phase, received=0, code=None):
        if self.on_event is None:
            return
        event = {"phase": phase, "cache_key": record.cache_key,
                 "received_bytes": received, "total_bytes": record.size}
        if code is not None:
            event["error_code"] = code
        try:
            self.on_event(event)
        except Exception:
            pass  # An observer cannot own a transfer or falsify its result.

    @contextmanager
    def _directory(self, key):
        root_fd = shard_fd = None
        try:
            root_fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            info = os.fstat(root_fd)
            if (info.st_dev, info.st_ino) != self._root_identity:
                raise OctoCacheError("cache_io")
            try:
                os.mkdir(key[:2], mode=0o700, dir_fd=root_fd)
            except FileExistsError:
                pass
            shard_fd = os.open(key[:2], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
            yield shard_fd
        except OSError as error:
            if isinstance(error, OctoCacheError):
                raise
            raise OctoCacheError("cache_io") from None
        finally:
            if shard_fd is not None:
                os.close(shard_fd)
            if root_fd is not None:
                os.close(root_fd)

    def _existing(self, record, directory):
        name = record.cache_key + ".bin"
        stream = None
        try:
            descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        except FileNotFoundError:
            return None
        except OSError:
            # In particular, never follow a file symlink out of this cache.
            self._discard(record, directory)
            return None
        try:
            stream = os.fdopen(descriptor, "rb")
            descriptor = None
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size != record.size:
                raise ValueError()
            signature = record.size, record.md5
            with self._lock:
                trusted = self._verified.get(record.cache_key) == (signature, _stamp(info))
            if not trusted:
                digest = hashlib.md5(usedforsecurity=False)
                count = 0
                while True:
                    self._require_open()
                    block = stream.read(min(_CHUNK, record.size - count + 1))
                    if not block:
                        break
                    count += len(block)
                    if count > record.size:
                        raise ValueError()
                    digest.update(block)
                after = os.fstat(stream.fileno())
                if (count != record.size or digest.hexdigest() != record.md5
                        or _stamp(info) != _stamp(after)):
                    raise ValueError()
                # Cache contents are replaced, never edited in place. This
                # makes a verified inode/stat stamp safe to reuse on ranges.
                os.fchmod(stream.fileno(), 0o400)
                info = os.fstat(stream.fileno())
                with self._lock:
                    self._verified[record.cache_key] = signature, _stamp(info)
            stream.seek(0)
            return stream
        except (OSError, ValueError) as error:
            if stream is not None:
                stream.close()
            elif descriptor is not None:
                os.close(descriptor)
            if isinstance(error, OctoCacheError) and error.code == "cache_closed":
                raise
            self._discard(record, directory)
            return None

    def _discard(self, record, directory):
        with self._lock:
            self._verified.pop(record.cache_key, None)
        try:
            os.unlink(record.cache_key + ".bin", dir_fd=directory)
        except FileNotFoundError:
            pass

    @staticmethod
    def _response(response, expected, url):
        if getattr(response, "status", None) != 200:
            raise OctoCacheError("upstream_http")
        final_url = response.geturl() if callable(getattr(response, "geturl", None)) else url
        if not _cdn_origin(final_url):
            raise OctoCacheError("upstream_redirect")
        headers = getattr(response, "headers", {})
        length = headers.get("Content-Length")
        if length is not None and (not isinstance(length, str)
                or not re.fullmatch(r"[0-9]{1,12}", length.strip()) or int(length) != expected):
            raise OctoCacheError("upstream_size")
        encoding = headers.get("Content-Encoding")
        if encoding is not None and (not isinstance(encoding, str) or encoding.strip().lower() != "identity"):
            raise OctoCacheError("upstream_encoding")

    def _download(self, record, directory, deadline):
        self._require_open()
        if not self.allow_download:
            raise OctoCacheMiss()
        while True:
            self._require_open()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise OctoCacheError("upstream_timeout")
            if self._parallel.acquire(timeout=min(remaining, 0.1)):
                break
        temporary, received = None, 0
        started = False
        try:
            with self._lock:
                self._require_open()
                if (self.max_download_bytes is not None
                        and self._allowance_spent + record.size > self.max_download_bytes):
                    raise OctoCacheError("budget_exceeded")
                self._allowance_spent += record.size
            self._notify(record, "started")
            started = True
            self._require_open()
            temporary = ".octo-" + secrets.token_hex(12) + ".part"
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                 0o600, dir_fd=directory)
            digest = hashlib.md5(usedforsecurity=False)
            last_event = time.monotonic()
            remaining = deadline - last_event
            if remaining <= 0:
                os.close(descriptor)
                raise OctoCacheError("upstream_timeout")
            # Unbuffered writes keep close()'s barrier meaningful: unwinding
            # a cancelled buffered writer must not flush new bytes later.
            with os.fdopen(descriptor, "wb", buffering=0) as output:
                with self.fetcher(record.upstream_url, timeout=min(self.timeout, remaining)) as response:
                    with self._lock:
                        self._require_open()
                        self._responses[id(response)] = response
                    try:
                        self._response(response, record.size, record.upstream_url)
                        while True:
                            self._require_open()
                            if time.monotonic() >= deadline:
                                raise OctoCacheError("upstream_timeout")
                            block = response.read(min(_CHUNK, record.size - received + 1))
                            if not isinstance(block, (bytes, bytearray, memoryview)):
                                raise OctoCacheError("upstream_data")
                            received += len(block)
                            # Count bytes already returned by the transport
                            # even when close() prevents storing that chunk.
                            self._require_open()
                            if not block:
                                break
                            if received > record.size:
                                raise OctoCacheError("upstream_size")
                            with self._commit_lock:
                                self._require_open()
                                view = memoryview(block)
                                while view:
                                    written = output.write(view)
                                    if not written:
                                        raise OctoCacheError("cache_io")
                                    view = view[written:]
                            digest.update(block)
                            now = time.monotonic()
                            if now - last_event >= 0.5 or received == record.size:
                                self._notify(record, "progress", received)
                                last_event = now
                    finally:
                        with self._lock:
                            self._responses.pop(id(response), None)
                if received != record.size:
                    raise OctoCacheError("upstream_size")
                if digest.hexdigest() != record.md5:
                    raise OctoCacheError("upstream_digest")
                output.flush()
                os.fchmod(output.fileno(), 0o400)
                os.fsync(output.fileno())
            final_name = record.cache_key + ".bin"
            with self._commit_lock:
                self._require_open()
                os.replace(temporary, final_name, src_dir_fd=directory, dst_dir_fd=directory)
                temporary = None
            info = os.stat(final_name, dir_fd=directory, follow_symlinks=False)
            with self._lock:
                self._verified[record.cache_key] = (record.size, record.md5), _stamp(info)
            stream = self._existing(record, directory)
            if stream is None:
                raise OctoCacheError("cache_io")
            try:
                self._require_open()
                self._notify(record, "verified", received)
                return stream
            except BaseException:
                stream.close()
                raise
        except BaseException as error:
            if self._closed.is_set():
                failure = OctoCacheError("cache_closed")
            elif isinstance(error, OctoCacheError):
                failure = error
            elif isinstance(error, TimeoutError) or (isinstance(error, URLError)
                    and isinstance(error.reason, TimeoutError)):
                failure = OctoCacheError("upstream_timeout")
            elif isinstance(error, (HTTPError, URLError)):
                failure = OctoCacheError("upstream_http")
            else:
                failure = OctoCacheError("cache_io")
            if started:
                self._notify(record, "failed", received, failure.code)
            if not isinstance(error, Exception):
                raise
            raise failure from None
        finally:
            try:
                if temporary is not None:
                    try:
                        os.unlink(temporary, dir_fd=directory)
                    except FileNotFoundError:
                        pass
            finally:
                self._parallel.release()

    def _obtain(self, record):
        key, signature = record.cache_key, (record.identity, record.size, record.md5)
        deadline = time.monotonic() + self.total_timeout
        with self._lock:
            self._require_open()
            flight = self._flights.get(key)
            leader = flight is None
            if leader:
                flight = self._flights[key] = _Flight(signature)
            elif flight.signature != signature:
                raise OctoCacheError("conflicting_metadata")
        if not leader:
            if not flight.done.wait(max(0, deadline - time.monotonic())):
                raise OctoCacheError("upstream_timeout")
            self._require_open()
            if flight.error is not None:
                if flight.error == "download_disabled":
                    raise OctoCacheMiss()
                raise OctoCacheError(flight.error)
            with self._directory(key) as directory:
                stream = self._existing(record, directory)
            if stream is None:
                raise OctoCacheError("cache_io")
            self._notify(record, "cache_hit")
            return stream
        try:
            with self._directory(key) as directory:
                stream = self._existing(record, directory)
                if stream is None:
                    return self._download(record, directory, deadline)
            self._notify(record, "cache_hit")
            return stream
        except BaseException as error:
            flight.error = ("cache_closed" if self._closed.is_set() else
                            error.code if isinstance(error, OctoCacheError) else "cache_io")
            raise
        finally:
            with self._lock:
                if self._flights.get(key) is flight:
                    del self._flights[key]
                flight.done.set()

    @contextmanager
    def open_verified(self, record):
        """Yield an independent binary descriptor for verified immutable bytes."""
        record = self._record(record)
        self._require_open()
        stream = self._obtain(record)
        try:
            self._require_open()
            yield stream
        finally:
            stream.close()
