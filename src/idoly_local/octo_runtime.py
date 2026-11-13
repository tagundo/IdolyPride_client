"""Load a pinned public resource archive and observe its two transfer links.

The archive contains application-wide settings, never a player session. Cache
events measure upstream bytes; gateway events measure local response bytes.
Neither counter proves that Unity has loaded a resource or finished a category.
"""
from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import threading
import time


MAX_SETTINGS_BYTES = 16 * 1024
MAX_ARCHIVE_BYTES = 8 * 1024 * 1024
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_MAX_COUNTER = 2**63 - 1
_MAX_ACTIVE = 1024
_MAX_VERIFIED = 100000
_MAX_LOG_RECEIPTS = 200
_MAX_OBSERVED_REQUESTS = 64
_MAX_REQUEST_HISTORY = 32
_REQUEST_PHASES = frozenset(("received", "resolving", "waiting_cache", "sending", "completed", "failed"))
_REQUEST_ERRORS = frozenset(("octo_gateway_closed", "octo_invalid_request", "octo_forbidden",
    "octo_not_found", "octo_revision_unavailable", "octo_manifest_unavailable", "octo_invalid_range",
    "octo_cache_invalid", "octo_cache_miss", "octo_resource_unavailable", "client_disconnected", "request_aborted"))
_REQUEST_CAUSES = frozenset(("cache_closed", "download_disabled"))
PLATFORM_ARCHIVES = {
    "android": ("public-octo", "octo-cache", 205051, 1087),
    "ios": ("public-octo-ios", "octo-cache-ios", 105051, 1159),
}


def _platform_archive(platform):
    if not isinstance(platform, str) or platform not in PLATFORM_ARCHIVES:
        raise ValueError("Unsupported game resource platform")
    return PLATFORM_ARCHIVES[platform]


def resource_cache_root(data_dir, resource_cache_dir=None):
    """Choose resource storage only; catalogs, profiles and state stay private."""
    try:
        private = Path(data_dir).resolve(strict=True)
        if not private.is_dir():
            raise ValueError("Game resource data directory is unavailable")
        if resource_cache_dir is None:
            return private
        public = Path(resource_cache_dir)
        if not public.is_absolute() or public.is_symlink():
            raise ValueError("Game resource storage must be an absolute directory")
        public.mkdir(parents=True, exist_ok=True, mode=0o700)
        if public.is_symlink() or not public.is_dir():
            raise ValueError("Game resource storage directory is invalid")
        return public.resolve(strict=True)
    except OSError:
        raise ValueError("Game resource storage directory is unavailable") from None


def resource_cache_paths(data_dir, cache_root, platform):
    """Return the primary platform cache and optional read-only legacy seed."""
    _archive, name, _version, _revision = _platform_archive(platform)
    try:
        private, selected = Path(data_dir).resolve(strict=True), Path(cache_root).resolve(strict=True)
        primary, legacy = selected / name, private / name
        if primary.is_symlink():
            raise ValueError("Game resource cache directory is invalid")
        seeds = ()
        if selected != private and legacy.is_dir() and not legacy.is_symlink():
            seeds = (legacy,)
        return primary, seeds
    except OSError:
        raise ValueError("Game resource cache directory is unavailable") from None


_SETTINGS = frozenset(("schema", "application_id", "application_version", "revision",
                       "manifest_sha256", "aes_key_hex", "client_key"))
_FAILURE_CODES = frozenset(("cache_io", "upstream_redirect", "upstream_http",
    "upstream_size", "upstream_encoding", "upstream_timeout", "upstream_data",
    "upstream_digest", "budget_exceeded", "download_disabled", "conflicting_metadata",
    "upstream_tls", "upstream_dns", "upstream_connect"))


def _integer(value):
    return type(value) is int and 0 <= value <= _MAX_COUNTER


def _add(left, right):
    return min(_MAX_COUNTER, left + right)


def _unique_pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate resource settings key")
        value[key] = item
    return value


def _read_archive_file(path, limit):
    descriptor = None
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or not 1 <= before.st_size <= limit:
            raise ValueError()
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = None
            raw = stream.read(limit + 1)
            after = os.fstat(stream.fileno())
        if (len(raw) != before.st_size
                or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
            raise ValueError()
        return raw
    except (OSError, ValueError):
        raise ValueError("Game resource archive file is unavailable or exceeds its limit") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def load_octo_archive(directory, *, platform="android"):
    """Return validated ``(settings, protobuf)`` or None for an absent archive.

    ``directory`` is the public-octo directory itself. This helper creates no
    files, imports no AES backend, and opens no network connection. Complete
    protobuf/object validation belongs to OctoManifest in the gateway factory.
    """
    _, _, version, revision = _platform_archive(platform)
    directory = Path(directory)
    if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
        raise ValueError("Game resource archive directory is invalid")
    settings_path, manifest_path = directory / "settings.json", directory / "manifest.pb"
    present = tuple(os.path.lexists(path) for path in (settings_path, manifest_path))
    if not any(present):
        return None
    if not all(present):
        raise ValueError("Game resource archive is incomplete")
    encoded = _read_archive_file(settings_path, MAX_SETTINGS_BYTES)
    try:
        settings = json.loads(encoded.decode("utf-8"), object_pairs_hook=_unique_pairs)
    except (ValueError, UnicodeError, RecursionError):
        raise ValueError("Game resource settings are invalid") from None
    if not isinstance(settings, dict) or set(settings) != _SETTINGS:
        raise ValueError("Game resource settings fields differ")
    for key, expected in (("schema", 1), ("application_id", 212),
                          ("application_version", version), ("revision", revision)):
        if type(settings[key]) is not int or settings[key] != expected:
            raise ValueError("Game resource settings version differs")
    if any(not isinstance(settings[key], str) or not _HEX64.fullmatch(settings[key])
           for key in ("manifest_sha256", "aes_key_hex")):
        raise ValueError("Game resource settings digest or AES key is invalid")
    key = settings["client_key"]
    if (not isinstance(key, str) or not 1 <= len(key) <= 256 or not key.isascii()
            or any(ord(char) < 33 or ord(char) > 126 for char in key)):
        raise ValueError("Game resource application key is invalid")
    raw = _read_archive_file(manifest_path, MAX_ARCHIVE_BYTES)
    if hashlib.sha256(raw).hexdigest() != settings["manifest_sha256"]:
        raise ValueError("Game resource manifest digest differs")
    return settings, raw


class OctoResourceTracker:
    """Bounded, thread-safe session measurements from trusted internal events."""

    def __init__(self, *, available=False, allow_downloads=True, log_callback=None):
        if type(available) is not bool or type(allow_downloads) is not bool:
            raise ValueError("Resource availability and download choice must be booleans")
        if log_callback is not None and not callable(log_callback):
            raise ValueError("Resource log observer must be callable")
        self._lock = threading.Lock()
        self._available, self._allow_downloads = available, allow_downloads
        self._callback = log_callback
        self._fetches, self._responses = {}, {}
        self._verified, self._log_receipts = set(), OrderedDict()
        self._received = self._served = self._manifest_served = 0
        self._last_received = self._last_total = 0
        self._last_status = "idle"
        self._limited = False
        self._request_active = OrderedDict()
        self._request_history = []
        self._last_request = self._last_failed_request = None
        self._http_requests = self._http_failures = self._cache_hits = self._cache_misses = 0

    def status(self):
        with self._lock:
            result = {"available": self._available, "allow_downloads": self._allow_downloads,
                "status": "downloading" if self._fetches else self._last_status,
                "active_requests": len(self._fetches),
                "session_received_bytes": self._received,
                "session_verified_files": len(self._verified),
                "session_served_bytes": self._served,
                "session_manifest_bytes": self._manifest_served,
                "last_received_bytes": self._last_received,
                "last_total_bytes": self._last_total,
                "session_http_requests": self._http_requests,
                "session_http_failures": self._http_failures,
                "session_cache_hits": self._cache_hits,
                "session_cache_misses": self._cache_misses,
                "active_http_requests": [self._public_request(row) for row in self._request_active.values()],
                "last_request": self._public_request(self._last_request),
                "last_failed_request": self._public_request(self._last_failed_request),
                "recent_requests": [self._public_request(row) for row in self._request_history],
                "measurement_limited": self._limited}
            if len(self._fetches) == 1:
                result["last_received_bytes"], result["last_total_bytes"] = next(iter(self._fetches.values()))
            return deepcopy(result)

    @staticmethod
    def _public_request(row):
        if row is None:
            return None
        value = {key: item for key, item in row.items() if not key.startswith("_")}
        value["elapsed_ms"] = max(0, min(_MAX_COUNTER,
            int((row.get("_finished", time.monotonic()) - row["_started"]) * 1000)))
        return value

    def on_http_request(self, event):
        """Observe bounded request outcomes, without counting JSON error bodies.

        This observer is independent of the existing body-transfer callbacks.
        No raw URL, query, headers, application key or account state is retained.
        """
        try:
            self._http_request(event)
        except Exception:
            pass  # Diagnostics can neither delay nor own an HTTP response.

    def _http_request(self, event):
        if not isinstance(event, dict) or event.get("source") != "octo_request":
            return
        identity, phase = event.get("request_id"), event.get("phase")
        method, kind, status = event.get("method"), event.get("kind"), event.get("http_status")
        fingerprint = event.get("route_fingerprint")
        name, key = event.get("object_name"), event.get("cache_key")
        error, cause = event.get("error_code"), event.get("cause_code")
        if (type(identity) is not int or not 1 <= identity <= _MAX_COUNTER or phase not in _REQUEST_PHASES
                or method not in ("GET", "HEAD") or kind not in ("manifest", "object")
                or type(status) is not int or status != 0 and not 100 <= status <= 599
                or not isinstance(fingerprint, str) or re.fullmatch(r"[0-9a-f]{16}", fingerprint) is None
                or name is not None and (not isinstance(name, str) or len(name) > 160 or not name.isprintable())
                or key is not None and (not isinstance(key, str) or not _HEX64.fullmatch(key))
                or error is not None and error not in _REQUEST_ERRORS
                or cause is not None and cause not in _FAILURE_CODES | _REQUEST_CAUSES
                or phase == "failed" and error is None
                or phase == "completed" and (status not in (200, 206) or error is not None)):
            return
        now = time.monotonic()
        with self._lock:
            if phase == "received":
                if identity in self._request_active:
                    return
                self._http_requests = _add(self._http_requests, 1)
                if len(self._request_active) >= _MAX_OBSERVED_REQUESTS:
                    self._limited = True
                    return
                row = {"request_id": identity, "method": method, "kind": kind,
                       "route_fingerprint": fingerprint, "cache_result": "pending",
                       "_thread_id": threading.get_ident(), "_started": now}
                self._request_active[identity] = row
            else:
                row = self._request_active.get(identity)
                if (row is None or row["method"] != method or row["kind"] != kind
                        or row["route_fingerprint"] != fingerprint):
                    return
            row.update(phase=phase, http_status=status, object_name=name, cache_key=key,
                       error_code=error, cause_code=cause)
            self._last_request = row
            if phase in ("completed", "failed"):
                row["_finished"] = now
                del self._request_active[identity]
                if row["cache_result"] == "pending":
                    row["cache_result"] = "unknown"
                if phase == "failed":
                    self._http_failures = _add(self._http_failures, 1)
                    self._last_failed_request = row
                    if error == "octo_cache_miss":
                        self._cache_misses = _add(self._cache_misses, 1)
                        row["cache_result"] = "cache_miss"
                self._request_history.append(row)
                if len(self._request_history) > _MAX_REQUEST_HISTORY:
                    del self._request_history[0]

    def _log(self, receipt, message):
        with self._lock:
            if receipt in self._log_receipts:
                return
            self._log_receipts[receipt] = None
            while len(self._log_receipts) > _MAX_LOG_RECEIPTS:
                self._log_receipts.popitem(last=False)
        if self._callback is not None:
            try:
                self._callback(message)
            except Exception:
                pass  # A display observer cannot own a resource transfer.

    def on_cache_event(self, event):
        """Count actual upstream deltas, retaining failed-attempt bytes."""
        try:
            self._cache_event(event)
        except Exception:
            pass  # Cache correctness must not depend on this observer.

    def _cache_event(self, event):
        if not isinstance(event, dict):
            return
        phase, key = event.get("phase"), event.get("cache_key")
        received, total = event.get("received_bytes"), event.get("total_bytes")
        if (phase not in ("started", "progress", "verified", "failed", "cache_hit")
                or not isinstance(key, str) or not _HEX64.fullmatch(key)
                or not _integer(received) or not _integer(total) or total == 0):
            return
        message = None
        with self._lock:
            if phase == "cache_hit":
                if received != 0:
                    return
                self._cache_hits = _add(self._cache_hits, 1)
                self._request_cache_result(key, "cache_hit")
                self._last_status = "ready"
                return
            if phase == "started":
                if received != 0:
                    return
                self._request_cache_result(key, "upstream")
                if key not in self._fetches:
                    if len(self._fetches) >= _MAX_ACTIVE:
                        self._limited = True
                        return
                    self._fetches[key] = (0, total)
                return
            current = self._fetches.get(key)
            if current is None or current[1] != total:
                return
            last, _ = current
            if received < last or (phase == "verified" and received != total):
                return
            self._received = _add(self._received, received - last)
            self._fetches[key] = (received, total)
            self._last_received, self._last_total = received, total
            if phase in ("verified", "failed"):
                del self._fetches[key]
                self._last_status = "ready" if phase == "verified" else "failed"
                if phase == "verified":
                    if key not in self._verified:
                        if len(self._verified) < _MAX_VERIFIED:
                            self._verified.add(key)
                        else:
                            self._limited = True
                    message = ("verified:" + key, f"게임 리소스 보관 완료 · {received} 바이트")
                else:
                    code = event.get("error_code")
                    code = code if isinstance(code, str) and code in _FAILURE_CODES else "download_failed"
                    status, verify = event.get("http_status"), event.get("verify_code")
                    status = status if code == "upstream_http" and type(status) is int and 100 <= status <= 599 else None
                    verify = verify if code == "upstream_tls" and type(verify) is int and 0 <= verify <= 2**31 - 1 else None
                    detail = (f" · HTTP {status}" if status is not None else "")
                    detail += (f" · 인증서 코드 {verify}" if verify is not None else "")
                    detail += " · 파일 " + key[:12]
                    message = (f"failed:{key}:{code}:{status}:{verify}",
                               "게임 리소스 내려받기 중단 · " + code + detail)
        if message is not None:
            self._log(*message)

    def _request_cache_result(self, key, result):
        """Called under our lock; cache callbacks run on their HTTP worker.

        Key alone cannot associate concurrent requests or a different worker's
        upstream event with this request. Keep both identity checks explicit.
        """
        thread = threading.get_ident()
        for row in self._request_active.values():
            if row["_thread_id"] == thread and row.get("cache_key") == key:
                row["cache_result"] = result

    def on_http_transfer(self, event):
        """Count actual local object response deltas; manifests stay separate."""
        try:
            self._http_transfer(event)
        except Exception:
            pass  # HTTP delivery must survive a broken status observer.

    def _http_transfer(self, event):
        if not isinstance(event, dict) or event.get("source") != "octo":
            return
        kind, phase, identity = event.get("kind"), event.get("phase"), event.get("transfer_id")
        sent, total = event.get("sent_bytes"), event.get("total_bytes")
        if (kind not in ("object", "manifest") or phase not in ("started", "progress", "completed", "failed")
                or type(identity) is not int or not 0 <= identity <= 2**64-1
                or not _integer(sent) or not _integer(total) or sent > total
                or (phase == "completed" and sent != total)):
            return
        failure = None
        with self._lock:
            if phase == "started":
                if sent != 0:
                    return
                if identity not in self._responses:
                    if len(self._responses) >= _MAX_ACTIVE:
                        self._limited = True
                        return
                    self._responses[identity] = (kind, 0, total)
                return
            previous = self._responses.get(identity)
            if previous is None:
                if phase == "failed" and kind == "object" and sent == 0:
                    self._last_status = "failed"
                    failure = identity
            elif previous[0] == kind and previous[2] == total and sent >= previous[1]:
                delta = sent - previous[1]
                if kind == "object":
                    self._served = _add(self._served, delta)
                else:
                    self._manifest_served = _add(self._manifest_served, delta)
                self._responses[identity] = (kind, sent, total)
                if phase in ("completed", "failed"):
                    del self._responses[identity]
                    if kind == "object":
                        self._last_status = "ready" if phase == "completed" else "failed"
                        if phase == "failed":
                            failure = identity
        if failure is not None:
            status = event.get("http_status")
            status = status if type(status) is int and 400 <= status <= 599 else 0
            self._log("http:" + str(failure) + ":" + str(status),
                      "게임 리소스 전송 중단" + (f" · HTTP {status}" if status else ""))


def _desktop_aes_backend():
    try:
        from Crypto.Cipher import AES
    except ImportError:
        raise ValueError("Game resources require an AES backend") from None

    def aes_cbc(encrypt, key, iv, data):
        cipher = AES.new(key, AES.MODE_CBC, iv)
        return cipher.encrypt(data) if encrypt else cipher.decrypt(data)
    return aes_cbc


def create_octo_gateway(data_dir, base_url, *, aes_cbc=None, fetcher=None,
                        allow_downloads=True, log_callback=None, platform="android",
                        resource_cache_dir=None, language="ja"):
    """Create an optional gateway without changing legacy server bundles."""
    if type(allow_downloads) is not bool:
        raise TypeError("Resource download choice must be a boolean")
    if aes_cbc is not None and not callable(aes_cbc):
        raise ValueError("Resource AES backend must be callable")
    if fetcher is not None and not callable(fetcher):
        raise ValueError("Resource fetcher must be callable")
    archive_name, cache_name, _, _ = _platform_archive(platform)
    tracker = OctoResourceTracker(allow_downloads=allow_downloads, log_callback=log_callback)
    root = Path(data_dir)
    selected_cache_root = resource_cache_root(root, resource_cache_dir)
    archive = load_octo_archive(root / archive_name, platform=platform)
    if archive is None:
        return None, tracker
    settings, raw = archive
    from .resource_translation_runtime import select_resource_translation
    raw, translation_layer, compatible_revision = select_resource_translation(
        raw, root, selected_cache_root, language=language, platform=platform)
    from .octo_manifest import OctoManifest
    from .octo_cache import OctoCache
    from .octo_http import OctoGateway
    try:
        manifest = OctoManifest(raw, aes_key=bytes.fromhex(settings["aes_key_hex"]),
            client_key=settings["client_key"], base_url=base_url,
            aes_cbc=aes_cbc if aes_cbc is not None else _desktop_aes_backend(),
            application_version=settings["application_version"],
            allow_previous_revisions=compatible_revision)
        if not compatible_revision and manifest.revision != settings["revision"]:
            raise ValueError("Game resource manifest revision differs")
        tracker = OctoResourceTracker(available=True, allow_downloads=allow_downloads, log_callback=log_callback)
        cache_path, seed_dirs = resource_cache_paths(root, selected_cache_root, platform)
        cache = OctoCache(cache_path, fetcher=fetcher, seed_dirs=seed_dirs,
            on_event=tracker.on_cache_event, allow_download=allow_downloads,
            local_source=translation_layer.open_source if translation_layer is not None else None)
        return OctoGateway(manifest, cache, transfer_callback=tracker.on_http_transfer,
                           request_callback=tracker.on_http_request,
                           translation_layer=translation_layer), tracker
    except BaseException:
        if translation_layer is not None:
            translation_layer.close()
        raise
