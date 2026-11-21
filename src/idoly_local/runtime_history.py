"""Bounded durable transport observations, independent of accounts and credentials.

Only explicitly structured observations are retained. Raw log text, request
payloads, authorities, query strings and user-selected provider paths never
enter this file. Timed writes are best effort; normal stop flushes synchronously.
"""
from __future__ import annotations

from collections import deque
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import threading
import uuid
from urllib.parse import urlsplit

MAX_RECORDS = 128
MAX_BYTES = 128 * 1024
MAX_COUNTER = 2**53 - 1
FILE_NAME = "server-observations.json"
_RPC = re.compile(r"RPC (/api\.[A-Za-z][A-Za-z0-9_]{0,47}/[A-Za-z][A-Za-z0-9_]{0,47}) -> ([A-Z_]+)(?: .*)?\Z")
_METHOD = re.compile(r"/api\.[A-Za-z][A-Za-z0-9_]{0,47}/[A-Za-z][A-Za-z0-9_]{0,47}\Z")
_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,127}\Z")
_RUN = re.compile(r"[0-9a-f]{32}\Z")
_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z\Z")
_RPC_CODES = frozenset(("OK", "CANCELLED", "UNKNOWN", "INVALID_ARGUMENT", "DEADLINE_EXCEEDED",
    "NOT_FOUND", "ALREADY_EXISTS", "PERMISSION_DENIED", "RESOURCE_EXHAUSTED",
    "FAILED_PRECONDITION", "ABORTED", "OUT_OF_RANGE", "UNIMPLEMENTED", "INTERNAL",
    "UNAVAILABLE", "DATA_LOSS", "UNAUTHENTICATED"))
_CHECK_IDS = frozenset(("account", "catalog", "protocol", "master", "storage", "http", "grpc", "resources"))
_CHECK_STATES = frozenset(("ready", "blocked", "missing", "attention", "not_checked", "stopped"))
_CHECK_CODES = frozenset(("selection_ready", "selection_invalid", "catalog_present", "descriptor_loaded",
    "tag_and_pack_sizes_checked", "storage_writable", "low_free_space", "http_json_ready", "listener_started",
    "listener_stopped", "resource_catalog_missing", "on_demand_enabled", "offline_cache_unverified",
    "permission_denied", "address_in_use", "missing_input", "invalid_input", "insufficient_space",
    "internal_error", "startup_failed", "not_checked"))
_CHECK_SCALARS = frozenset(("free_bytes", "pack_count", "pack_bytes", "port", "descriptor_bytes"))
_CHECK_TEXT = frozenset(("version", "fingerprint", "offline", "network", "protocol_exchange"))
_LIFECYCLE = {
    "Local server stopped": "server_stopped",
    "gRPC stopped": "grpc_stopped",
    "감상용 전체 해금 프로필을 준비했습니다.": "media_profile_prepared",
    "게임 리소스를 선택한 Downloads 보관 폴더에서 직접 제공합니다.": "selected_resource_storage",
    "감상 촬영용 의상 제한 해제 마스터를 제공합니다.": "media_master_prepared",
}
_LIFECYCLE_CODES = frozenset((*_LIFECYCLE.values(), "startup_requested", "server_ready",
    "profile_created", "profile_loaded", "cleanup_failed", "history_cleared", "history_recovered"))
_CLIENT_ROUTE = re.compile(r"/client/(?:presentation|playback|media|render-probe|wardrobe-probe)(?:/status)?\Z")
_OCTO_ROUTE = re.compile(r"/octo/([0-9]{1,10})/(assetbundle|resources?)(?:/.*)?\Z")


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate observation key")
        value[key] = item
    return value


def _integer(value):
    return type(value) is int and 0 <= value <= MAX_COUNTER


def _identity(value):
    return isinstance(value, str) and _RUN.fullmatch(value) is not None


def _when(value):
    return isinstance(value, str) and _TIME.fullmatch(value) is not None


def _check_snapshot(value):
    if value is None:
        return None
    if (not isinstance(value, dict) or set(value) != {"schema", "scope", "run_id", "started_at",
            "updated_at", "state", "gameplay_verified", "checks"} or type(value["schema"]) is not int or value["schema"] != 1
            or value["scope"] != "current_run" or not _identity(value["run_id"])
            or not _when(value["started_at"]) or not _when(value["updated_at"])
            or value["state"] not in ("checking", "ready", "blocked", "stopped")
            or value["gameplay_verified"] is not False or not isinstance(value["checks"], list)
            or len(value["checks"]) > len(_CHECK_IDS)):
        raise ValueError("Invalid saved startup checks")
    seen = set()
    for row in value["checks"]:
        if (not isinstance(row, dict) or not {"id", "state", "code"} <= set(row)
                or set(row) - {"id", "state", "code"} - _CHECK_SCALARS - _CHECK_TEXT
                or row["id"] not in _CHECK_IDS or row["id"] in seen
                or row["state"] not in _CHECK_STATES or row["code"] not in _CHECK_CODES):
            raise ValueError("Invalid saved check row")
        seen.add(row["id"])
        if any(not _integer(row[key]) for key in set(row) & _CHECK_SCALARS):
            raise ValueError("Invalid saved check counter")
        if any(not isinstance(row[key], str) or len(row[key]) > 160
               or re.fullmatch(r"[A-Za-z0-9_.-]+", row[key]) is None
               for key in set(row) & _CHECK_TEXT):
            raise ValueError("Invalid saved check identity")
    return deepcopy(value)


def _record(value):
    base = {"sequence", "timestamp", "run_id", "kind", "code"}
    if (not isinstance(value, dict) or not base <= set(value)
            or not _integer(value["sequence"]) or value["sequence"] < 1
            or not _when(value["timestamp"]) or not _identity(value["run_id"])):
        raise ValueError("Invalid saved observation")
    kind = value["kind"]
    if kind == "rpc":
        valid = (set(value) == base | {"method", "outcome"} and value["code"] == "rpc_completed"
            and isinstance(value["method"], str) and _METHOD.fullmatch(value["method"]) is not None
            and value["outcome"] in _RPC_CODES)
    elif kind == "http_failure":
        valid = (set(value) == base | {"method", "path", "route_fingerprint", "http_status", "elapsed_ms"}
            and value["code"] == "http_request_failed" and value["method"] in ("GET", "HEAD", "POST")
            and isinstance(value["path"], str) and safe_route(value["path"])[0] == value["path"]
            and isinstance(value["route_fingerprint"], str)
            and re.fullmatch(r"[0-9a-f]{16}", value["route_fingerprint"]) is not None
            and type(value["http_status"]) is int and (value["http_status"] == 0 or 100 <= value["http_status"] <= 599)
            and _integer(value["elapsed_ms"]))
    elif kind == "startup_failure":
        valid = (set(value) == base | {"stage", "error_type"} and value["code"] in _CHECK_CODES
            and value["stage"] in _CHECK_IDS | {"startup"}
            and isinstance(value["error_type"], str) and _TOKEN.fullmatch(value["error_type"]) is not None)
    elif kind == "lifecycle":
        valid = set(value) == base and value["code"] in _LIFECYCLE_CODES
    else:
        valid = False
    if not valid:
        raise ValueError("Invalid saved observation fields")
    return dict(value)


def safe_route(target):
    """Identify a route family without retaining opaque filenames or providers."""
    try:
        path = urlsplit(target).path[:1024] if isinstance(target, str) else ""
    except ValueError:
        path = ""
    if path in ("/diagnostics/runtime", "/diagnostics/status", "/diagnostics/client") or _CLIENT_ROUTE.fullmatch(path):
        public = path
    elif path.startswith("/master/"):
        public = "/master/<file>"
    else:
        match = _OCTO_ROUTE.fullmatch(path)
        public = ("/octo/" + match[1] + "/" + match[2] + "/<object>") if match else "/<other>"
    return public, hashlib.sha256(path.encode("utf-8", "replace")).hexdigest()[:16]


def _empty():
    return {"schema": 1, "total_records": 0, "records": [], "last_failure": None, "last_startup": None}


def _read(path):
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not 0 < info.st_size <= MAX_BYTES:
                raise ValueError("Unsafe history file")
            raw = os.read(descriptor, MAX_BYTES + 1)
        finally:
            os.close(descriptor)
        if not 0 < len(raw) <= MAX_BYTES:
            raise ValueError("History size")
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_object)
        if (not isinstance(value, dict) or set(value) != set(_empty()) or type(value["schema"]) is not int or value["schema"] != 1
                or not _integer(value["total_records"]) or not isinstance(value["records"], list)
                or len(value["records"]) > MAX_RECORDS):
            raise ValueError("Invalid observation document")
        records = [_record(row) for row in value["records"]]
        if any(row["sequence"] > value["total_records"] for row in records):
            raise ValueError("Invalid observation sequence")
        if any(a["sequence"] >= b["sequence"] for a, b in zip(records, records[1:])):
            raise ValueError("Observation sequence is not increasing")
        failure = _record(value["last_failure"]) if value["last_failure"] is not None else None
        if failure is not None and (failure["sequence"] > value["total_records"] or not _is_failure(failure)):
            raise ValueError("Invalid last failure")
        return {**value, "records": records, "last_failure": failure,
                "last_startup": _check_snapshot(value["last_startup"])}, "loaded"
    except FileNotFoundError:
        return _empty(), "new"
    except OSError:
        return _empty(), "unavailable"
    except (ValueError, TypeError, UnicodeError, RecursionError, KeyError):
        return _empty(), "recovered_invalid"


def _is_failure(row):
    return (row["kind"] in ("http_failure", "startup_failure")
            or row["kind"] == "rpc" and row["outcome"] != "OK"
            or row["kind"] == "lifecycle" and row["code"] == "cleanup_failed")


def _snapshot(value, load_state, *, current_run=None, error=None, limit=20):
    startup = deepcopy(value["last_startup"])
    if startup is not None and startup["run_id"] != current_run:
        startup["scope"] = "previous_run"
    return {"schema": 1, "available": error is None and load_state != "unavailable", "load_state": load_state,
        "persistence": "unavailable" if error or load_state == "unavailable"
            or not current_run and load_state == "recovered_invalid" else "debounced" if current_run else "stored",
        "last_write_error": error, "current_run": current_run,
        "retained_records": len(value["records"]), "total_records": value["total_records"],
        "records": deepcopy(value["records"][-limit:]), "last_failure": deepcopy(value["last_failure"]),
        "last_startup": startup}


def stored_status(data_dir):
    value, loaded = _read(Path(data_dir) / FILE_NAME)
    return _snapshot(value, loaded, limit=MAX_RECORDS)


class PersistentHistory:
    def __init__(self, data_dir, *, debounce_seconds=0.5):
        self.path = Path(data_dir) / FILE_NAME
        self.run_id = uuid.uuid4().hex
        value, self._load_state = _read(self.path)
        self._records = deque(value["records"], maxlen=MAX_RECORDS)
        self._total = value["total_records"]
        self._last_failure = value["last_failure"]
        self._last_startup = value["last_startup"]
        self._lock = threading.Lock()
        self._io_lock = threading.Lock()
        self._timer = None
        self._closed = False
        self._dirty = False
        self._revision = 0
        self._error = None
        self._delay = max(0.05, float(debounce_seconds))
        if self._load_state == "recovered_invalid":
            self.record("lifecycle", "history_recovered")

    def _schedule_locked(self):
        if self._timer is None and not self._closed:
            self._timer = threading.Timer(self._delay, self._write_later)
            self._timer.daemon = True
            try:
                self._timer.start()
            except RuntimeError:
                self._timer = None
                self._error = "history_io"

    def _write_later(self):
        with self._lock:
            revision = self._revision
        self.flush()
        with self._lock:
            # Keep one timed writer, including while slow storage is writing.
            # An idle permission failure waits for a new observation or Stop;
            # it does not retry and wake the device indefinitely.
            self._timer = None
            if self._dirty and self._revision != revision:
                self._schedule_locked()

    def record(self, kind, code, **fields):
        with self._lock:
            if self._closed or self._total >= MAX_COUNTER:
                return
            row = _record({"sequence": self._total + 1, "timestamp": timestamp(),
                "run_id": self.run_id, "kind": kind, "code": code, **fields})
            self._records.append(row)
            self._total += 1
            if _is_failure(row):
                self._last_failure = row
            self._dirty = True
            self._revision += 1
            self._schedule_locked()

    def record_log(self, line):
        match = _RPC.fullmatch(line)
        if match and match[2] in _RPC_CODES:
            self.record("rpc", "rpc_completed", method=match[1], outcome=match[2])
        elif line in _LIFECYCLE:
            self.record("lifecycle", _LIFECYCLE[line])
        elif line.startswith("Created local profile "):
            self.record("lifecycle", "profile_created")
        elif line.startswith("Loaded local profile "):
            self.record("lifecycle", "profile_loaded")
        elif line == "Server cleanup failed; retry Stop":
            self.record("lifecycle", "cleanup_failed")
        # Other text is intentionally not persisted; it may contain a filename,
        # a third-party error message or a user-defined profile name.

    def http_failure(self, row):
        path, fingerprint = safe_route(row["path"])
        self.record("http_failure", "http_request_failed", method=row["method"], path=path,
            route_fingerprint=fingerprint, http_status=row["http_status"], elapsed_ms=row["elapsed_ms"])

    def startup_failure(self, stage, error, code="startup_failed"):
        name = type(error).__name__
        self.record("startup_failure", code, stage=stage,
                    error_type=name if _TOKEN.fullmatch(name) else "Exception")

    def set_startup(self, value):
        snapshot = _check_snapshot(value)
        with self._lock:
            if self._closed:
                return
            self._last_startup = snapshot
            self._dirty = True
            self._revision += 1
            self._schedule_locked()

    def _value_locked(self):
        return {"schema": 1, "total_records": self._total, "records": list(self._records),
            "last_failure": self._last_failure, "last_startup": self._last_startup}

    def status(self, *, full=False):
        with self._lock:
            value = _snapshot(self._value_locked(), self._load_state, current_run=self.run_id,
                error=self._error, limit=MAX_RECORDS if full else 20)
            if self._closed and not self._dirty and self._error is None:
                value["persistence"] = "stored"
            return value

    def flush(self):
        """Serialize outside the observation lock; this never raises to a server."""
        with self._io_lock:
            with self._lock:
                if not self._dirty:
                    return self._error is None
                value, revision = deepcopy(self._value_locked()), self._revision
            temporary = None
            try:
                raw = (json.dumps(value, ensure_ascii=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
                if len(raw) > MAX_BYTES:
                    raise ValueError("History size limit")
                try:
                    info = self.path.lstat()
                except FileNotFoundError:
                    pass
                else:
                    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                        with self._lock:
                            self._error = "unsafe_history_file"
                        return False
                temporary = self.path.with_name("." + FILE_NAME + "." + uuid.uuid4().hex + ".tmp")
                descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                try:
                    with os.fdopen(descriptor, "wb") as stream:
                        stream.write(raw)
                        stream.flush()
                        os.fsync(stream.fileno())
                except BaseException:
                    raise
                os.replace(temporary, self.path)
                temporary = None
                with self._lock:
                    self._error = None
                    if self._load_state == "unavailable":
                        self._load_state = "loaded"
                    if self._revision == revision:
                        self._dirty = False
                return True
            except (OSError, ValueError, TypeError):
                with self._lock:
                    self._error = "history_io"
                return False
            finally:
                if temporary is not None:
                    try:
                        temporary.unlink()
                    except OSError:
                        pass

    def clear(self):
        with self._lock:
            self._records.clear()
            self._last_failure = None
            self._total = 0
            self._load_state = "cleared"
            self._dirty = True
            self._revision += 1
        self.record("lifecycle", "history_cleared")
        self.flush()
        return self.status(full=True)

    def close(self):
        with self._lock:
            self._closed = True
            timer, self._timer = self._timer, None
        if timer is not None:
            timer.cancel()
        return self.flush()
