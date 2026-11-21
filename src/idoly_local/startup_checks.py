"""One-start observations, never a claim of complete game or offline playback."""
from __future__ import annotations

from copy import deepcopy
import errno
import http.client
import json
import os
from pathlib import Path
import re
import threading
import uuid
from urllib.parse import urlsplit

from .runtime_history import MAX_COUNTER, timestamp

_ORDER = ("account", "catalog", "protocol", "master", "storage", "http", "grpc", "resources")


def failure_code(error):
    if isinstance(error, PermissionError):
        return "permission_denied"
    if isinstance(error, FileNotFoundError):
        return "missing_input"
    if isinstance(error, OSError):
        if error.errno == errno.EADDRINUSE:
            return "address_in_use"
        if error.errno == errno.ENOSPC:
            return "insufficient_space"
    if isinstance(error, ValueError):
        return "invalid_input"
    return "internal_error"


def _public_version(value):
    return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,160}", value) else "unrecognized"


def no_checks():
    return {"schema": 1, "scope": "not_run", "run_id": None, "started_at": None,
            "updated_at": None, "state": "not_run", "gameplay_verified": False, "checks": []}


class StartupChecks:
    """Cache real startup outcomes. status() performs no I/O or new probes."""
    def __init__(self, history):
        self._lock = threading.Lock()
        self._callback = history.set_startup
        when = timestamp()
        self._value = {"schema": 1, "scope": "current_run", "run_id": history.run_id,
            "started_at": when, "updated_at": when, "state": "checking",
            "gameplay_verified": False, "checks": []}
        self._callback(self.status())

    def status(self):
        with self._lock:
            return deepcopy(self._value)

    def record(self, identity, state, code, **facts):
        with self._lock:
            rows = {row["id"]: row for row in self._value["checks"]}
            rows[identity] = {"id": identity, "state": state, "code": code, **facts}
            self._value["checks"] = [rows[key] for key in _ORDER if key in rows]
            self._value["updated_at"] = timestamp()
            value = deepcopy(self._value)
        self._callback(value)

    def state(self, state):
        with self._lock:
            self._value["state"], self._value["updated_at"] = state, timestamp()
            value = deepcopy(self._value)
        self._callback(value)

    def failed(self, stage, error):
        identity = stage if stage in _ORDER else "protocol"
        self.record(identity, "blocked", failure_code(error))
        self.state("blocked")

    def protocol(self, schema, path):
        # This resolves the actual loaded descriptors, rather than inferring
        # readiness from a filename or an open port.
        for method in ("/api.System/Check", "/api.Master/Get", "/api.User/Get"):
            schema.request_type(method)
            schema.response_type(method)
        self.record("protocol", "ready", "descriptor_loaded",
                    descriptor_bytes=min(MAX_COUNTER, Path(path).stat().st_size),
                    fingerprint=schema.fingerprint, version="6.1.1")

    def master(self, schema, payload):
        response = schema.response_type("/api.Master/Get").FromString(payload)
        tag = response.masterTag
        # prepare_master_tag has already checked names, pack presence and sizes.
        self.record("master", "ready", "tag_and_pack_sizes_checked",
            version=_public_version(tag.version), pack_count=len(tag.masterTagPacks),
            pack_bytes=min(MAX_COUNTER, sum(pack.fileSize for pack in tag.masterTagPacks)))

    def storage(self, root, selected_cache):
        from .octo_runtime import resource_cache_root
        directory = resource_cache_root(root, selected_cache)
        free = None
        for path in dict.fromkeys((Path(root), directory)):
            temporary = path / (".idoly-startup-check-" + uuid.uuid4().hex)
            descriptor = None
            try:
                descriptor = os.open(temporary, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                os.write(descriptor, b"check")
                os.lseek(descriptor, 0, os.SEEK_SET)
                if os.read(descriptor, 5) != b"check":
                    raise OSError("Storage probe mismatch")
                info = os.statvfs(path)
                current = max(0, min(MAX_COUNTER, info.f_bavail * info.f_frsize))
                free = current if free is None else min(free, current)
            finally:
                if descriptor is not None:
                    os.close(descriptor)
                    try:
                        temporary.unlink()
                    except FileNotFoundError:
                        pass
        # An actual tiny write proves access. Free space is an observation, not
        # an estimate that every unrequested game resource will fit.
        limited = free < 16 * 1024 * 1024
        self.record("storage", "attention" if limited else "ready",
                    "low_free_space" if limited else "storage_writable", free_bytes=free)

    def http_listener(self, runtime, asset_port):
        if not runtime._asset_started or not runtime._asset_thread.is_alive():
            raise RuntimeError("HTTP serving thread is not running")
        # Direct HTTPConnection deliberately ignores host proxy environment.
        # Observe the owned HTTP handler, with no credentials or game payload.
        target = urlsplit(runtime._asset_url)
        connection = http.client.HTTPConnection(target.hostname, target.port, timeout=2)
        try:
            connection.request("GET", "/client/playback")
            response = connection.getresponse()
            body = response.read(4097)
            if response.status != 200 or not 0 < len(body) <= 4096:
                raise ValueError("Local HTTP readiness response is invalid")
            value = json.loads(body.decode("utf-8"))
            if not isinstance(value, dict) or type(value.get("schema")) is not int or value["schema"] != 1:
                raise ValueError("Local HTTP readiness JSON is invalid")
        finally:
            connection.close()
        self.record("http", "ready", "http_json_ready", port=asset_port,
                    protocol_exchange="json_response")

    def grpc_listener(self, runtime):
        if not runtime._grpc.running:
            raise RuntimeError("gRPC listener is not running")
        self.record("grpc", "ready", "listener_started", port=runtime._grpc.address[1],
                    protocol_exchange="not_checked")

    def resources(self, resources, allow_downloads):
        available = resources is not None and resources.status().get("available") is True
        self.record("resources", "ready" if available and allow_downloads else
                    "attention" if available else "missing",
                    "on_demand_enabled" if available and allow_downloads else
                    "offline_cache_unverified" if available else "resource_catalog_missing",
                    offline="not_checked", network="not_probed")

    def stopped(self):
        current = self.status()
        if current["state"] != "blocked":
            for row in current["checks"]:
                if row["id"] in ("http", "grpc"):
                    self.record(row["id"], "stopped", "listener_stopped",
                                port=row["port"], protocol_exchange="not_checked")
            self.state("stopped")
