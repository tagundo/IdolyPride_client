#!/usr/bin/env python3
"""Private frozen server engine controlled by the native app over JSON lines."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import signal
import socket
import sqlite3
import sys
import stat
import tempfile
import threading
import time
import uuid

from payload import install_bundled_translations, install_payload

_OUTPUT_LOCK = threading.Lock()
_TUTORIAL_PINS = {
    "short": ("719068e48099082fad71760d65a88047182be8b858a3586f33f87b812103fba7", 158, 8813),
    "full": ("29ecb24412bd6a2034a8b31803fcb34a8cd6b6632c2f0a96fe0319c15236d562", 156, 10717),
}


def emit(event: str, **values):
    with _OUTPUT_LOCK:
        print(json.dumps({"event": event, **values}, ensure_ascii=False), flush=True)


_ACCOUNT_ACTIONS = frozenset(("accounts_status", "accounts_create", "accounts_clone", "accounts_select",
    "accounts_export", "accounts_preview", "accounts_import", "accounts_restore", "settings_clear_history"))
_ACCOUNT_ARCHIVE_LIMIT = 128 * 1024 * 1024


_EVENT_ACTIONS = frozenset(("events_status", "events_save"))

_OFFICIAL_ACTIONS = frozenset(("official_inspect", "official_fetch", "official_apply", "official_cancel", "official_status"))
_OFFICIAL_STATES = frozenset(("idle", "checking", "verified", "fetching", "ready", "completed", "failed", "cancelled"))
_OFFICIAL_STAGES = frozenset(("preparing", "checking", "verifying", "verified", "transferring", "firebase", "login",
    "master", "account", "collected", "idle", "fetching", "catalog_check", "staging", "ready", "applying", "completed", "cancelled", "failed"))
_OFFICIAL_WARNINGS = frozenset(("account_temporary_cleanup_pending", "account_status_refresh_required"))
_OFFICIAL_HOST_ERRORS = frozenset(("official_request_invalid", "official_operation_busy", "official_server_starting",
    "official_server_running", "official_operation_failed", "official_response_invalid"))


def _event_payload(action, payload):
    """Expand this Mac-only compact stdin wire; common JSON stays unchanged."""
    if type(action) is not str or action not in _EVENT_ACTIONS or type(payload) is not dict:
        raise ValueError("event_settings_command_invalid")
    if action == "events_status":
        if payload: raise ValueError("event_settings_command_invalid")
        return {}
    if set(payload) != {"settings", "expected_revision"}:
        raise ValueError("event_settings_command_invalid")
    settings, expected = payload["settings"], payload["expected_revision"]
    if (type(settings) is not dict or set(settings) != {"schema", "revision", "love_events"}
            or type(settings["schema"]) is not int or settings["schema"] != 1
            or type(settings["revision"]) is not int or not 0 <= settings["revision"] <= 2**53-1
            or type(expected) is not int or not 0 <= expected <= 2**53-1
            or type(settings["love_events"]) is not list or len(settings["love_events"]) > 64):
        raise ValueError("event_settings_command_invalid")
    rows, seen = [], set()
    for row in settings["love_events"]:
        if (type(row) is not list or len(row) != 3 or type(row[0]) is not str
                or re.fullmatch(r"[A-Za-z0-9_-]{1,96}", row[0]) is None or row[0] in seen
                or type(row[1]) is not int or type(row[2]) is not int):
            raise ValueError("event_settings_command_invalid")
        seen.add(row[0])
        rows.append({"event_id": row[0], "start_time_ms": row[1], "end_time_ms": row[2]})
    return {"settings": {"schema": 1, "revision": settings["revision"], "love_events": rows},
            "expected_revision": expected}


def _official_job(value, *, private=False, errors=()):
    """Project a bounded job; transfer credentials/tickets never enter IPC output."""
    if type(value) is not dict or type(value.get("state")) is not str or value["state"] not in _OFFICIAL_STATES:
        return {"schema": 1, "state": "failed", "job_id": None, "busy": False,
                "progress": "failed", "error_code": "official_response_invalid", "counts": {}, "expires_in_seconds": 0}
    job = {"schema": 1, "state": value["state"], "busy": value.get("busy") is True,
        "job_id": value.get("job_id") if type(value.get("job_id")) is str
            and re.fullmatch(r"[0-9a-f]{32}", value["job_id"]) else None,
        "progress": value.get("progress") if type(value.get("progress")) is str and value["progress"] in _OFFICIAL_STAGES else "preparing",
        "error_code": value.get("error_code") if value.get("error_code") in (*_OFFICIAL_HOST_ERRORS, *errors) else None,
        "counts": {}, "expires_in_seconds": 0}
    expires = value.get("expires_in_seconds")
    if type(expires) is int and 0 <= expires <= 600:
        job["expires_in_seconds"] = expires
    def counts(raw):
        return {key: raw[key] for key in ("cards", "items", "photos")
            if type(raw) is dict and type(raw.get(key)) is int and 0 <= raw[key] <= 2**31-1}
    job["counts"] = counts(value.get("counts"))
    preview = value.get("preview")
    if private and type(preview) is dict:
        safe = {"inventory": counts(preview.get("inventory"))}
        for key in ("public_id", "server_id", "manager_name"):
            text = preview.get(key)
            if type(text) is str and 0 < len(text) <= 128 and text.isprintable():
                safe[key] = text
        level = preview.get("manager_level")
        if type(level) is int and 0 <= level <= 2**31-1:
            safe["manager_level"] = level
        job["preview"] = safe
    return job


def _official_payload(action, payload):
    required = {"official_inspect": {"user_id", "password", "platform"}, "official_fetch": {"job_id"},
        "official_apply": {"job_id", "profile", "replace", "expected_revision"},
        "official_cancel": {"job_id"}, "official_status": set()}[action]
    if set(payload) != required:
        raise ValueError("official_request_invalid")
    if action == "official_inspect":
        name, password = payload["user_id"], payload["password"]
        if (type(name) is not str or re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name) is None
                or type(password) is not str or not 1 <= len(password) <= 128 or password.strip() != password
                or not all(32 <= ord(character) < 127 for character in password)
                or payload["platform"] not in ("ios", "android")):
            raise ValueError("official_request_invalid")
    if "job_id" in payload and (type(payload["job_id"]) is not str
            or re.fullmatch(r"[0-9a-f]{32}", payload["job_id"]) is None):
        raise ValueError("official_request_invalid")
    if action == "official_apply":
        profile = payload["profile"]
        try:
            valid = (type(profile) is str and profile.strip() == profile and 0 < len(profile.encode("utf-8")) <= 64
                and profile.isprintable() and "/" not in profile and "\\" not in profile)
        except UnicodeError:
            valid = False
        revision = payload["expected_revision"]
        if (not valid or type(payload["replace"]) is not bool
                or (payload["replace"] and (type(revision) is not str or re.fullmatch(r"[0-9a-f]{64}", revision) is None))
                or (not payload["replace"] and revision is not None)):
            raise ValueError("official_request_invalid")


def _account_export_copy(data_dir, result, destination, progress):
    """Copy only a verified owned account ZIP to an explicitly chosen native destination."""
    name, value = result.get("filename"), result.get("path")
    expected_size, expected_sha = result.get("bytes"), result.get("sha256")
    if (type(name) is not str or re.fullmatch(r"IdolyPride-Account-[0-9a-f]{32}\.zip", name) is None
            or type(value) is not str or type(expected_size) is not int
            or not 0 < expected_size <= _ACCOUNT_ARCHIVE_LIMIT
            or type(expected_sha) is not str or re.fullmatch(r"[0-9a-f]{64}", expected_sha) is None):
        raise ValueError("account_export_identity_invalid")
    source = Path(value)
    exports = Path(data_dir) / "account-management" / "exports"
    if source.name != name or exports.is_symlink() or source.parent.resolve(strict=True) != exports.resolve(strict=True):
        raise ValueError("account_export_path_invalid")
    if (type(destination) is not str or not 0 < len(destination) <= 4096 or "\0" in destination):
        raise ValueError("account_destination_invalid")
    chosen = Path(destination)
    if not chosen.is_absolute() or chosen.suffix.lower() != ".zip" or chosen.is_symlink():
        raise ValueError("account_destination_invalid")
    parent = chosen.parent.resolve(strict=True)
    target = parent / chosen.name
    if not parent.is_dir() or source.resolve(strict=True) == target:
        raise ValueError("account_destination_invalid")
    def check_target():
        if target.exists() or target.is_symlink():
            info = target.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError("account_destination_invalid")
    check_target()
    temporary = None
    count, checksum, last_progress = 0, hashlib.sha256(), 0.0
    try:
        source_fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(source_fd, "rb") as incoming:
            before = os.fstat(incoming.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size != expected_size:
                raise ValueError("account_export_identity_invalid")
            fd, temporary = tempfile.mkstemp(prefix=".idoly-account-", suffix=".part", dir=parent)
            with os.fdopen(fd, "wb") as outgoing:
                while True:
                    block = incoming.read(64 * 1024)
                    if not block:
                        break
                    count += len(block)
                    if count > expected_size or outgoing.write(block) != len(block):
                        raise ValueError("account_export_copy_failed")
                    checksum.update(block)
                    now = time.monotonic()
                    if now - last_progress >= .25:
                        progress(count, expected_size)
                        last_progress = now
                outgoing.flush()
                os.fsync(outgoing.fileno())
            after = os.fstat(incoming.fileno())
            if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                    != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                    or count != expected_size or checksum.hexdigest() != expected_sha):
                raise ValueError("account_export_copy_failed")
        check_target()
        os.replace(temporary, target)
        temporary = None
        progress(count, expected_size)
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except OSError:
                pass


class Controller:
    def __init__(self, data_dir, server_data, profile="sandbox", emit_event=emit):
        self.data_dir, self.server_data = Path(data_dir), Path(server_data)
        self.profile, self.emit = profile, emit_event
        self.lock = threading.RLock()
        self.runtime = self.worker = None
        self.cancelled = False
        self.closed = False
        self.resource_worker = None
        self.account_worker = None
        self.account_status = None
        self.official_manager = None
        self.official_worker = None
        self.events_worker = None
        self.official_error_codes = _OFFICIAL_HOST_ERRORS
        self.translation_status = {"state": "absent"}

    def log(self, message):
        self.emit("log", message=str(message))

    def status(self):
        with self.lock:
            runtime = self.runtime
            starting = bool(self.worker and self.worker.is_alive() and runtime is None and not self.cancelled)
            status = runtime.status() if runtime else {
                "running": False, "profile": self.profile,
                "grpc_address": "127.0.0.1:50051", "asset_url": "http://127.0.0.1:8080"}
            status = {key: value for key, value in status.items() if key != "logs"}
            status["starting"] = starting
            status["can_stop"] = runtime is not None or starting
            if self.account_status is not None:
                status["accounts"] = self.account_status
            if self.official_manager is not None:
                status["official_import"] = _official_job(self.official_manager.status(public=True), errors=self.official_error_codes)
            if self.translation_status.get("state") != "absent":
                status["bundled_translations"] = dict(self.translation_status)
        if runtime is None:
            try:
                from idoly_local.app_runtime import server_settings_status
                status.update(server_settings_status(self.data_dir))
            except (ImportError, OSError, ValueError):
                pass
        if "event_settings" not in status:
            try:
                from idoly_local.event_settings import event_settings_status
                status["event_settings"] = event_settings_status(self.data_dir)
            except (ImportError, OSError, ValueError):
                pass
        self.emit("status", status=status)
        return status

    def start(self, experimental_main_live=False, media_mode=False, download_missing_resources=True,
              resource_cache_dir=None):
        if type(experimental_main_live) is not bool:
            raise ValueError("Experimental live must be an explicit boolean")
        if type(media_mode) is not bool:
            raise ValueError("Media mode must be an explicit boolean")
        if type(download_missing_resources) is not bool:
            raise ValueError("Resource downloads must be an explicit boolean")
        if resource_cache_dir is not None and (not isinstance(resource_cache_dir, str)
                or not 0 < len(resource_cache_dir) <= 4096 or "\0" in resource_cache_dir
                or not Path(resource_cache_dir).is_absolute()):
            raise ValueError("Resource cache directory must be an absolute folder")
        with self.lock:
            if (self.closed or self.runtime or (self.worker and self.worker.is_alive())
                    or (self.account_worker and self.account_worker.is_alive())
                    or (self.official_worker and self.official_worker.is_alive())
                    or (self.events_worker and self.events_worker.is_alive())
                    or (self.official_manager and self.official_manager.status(public=True).get("busy") is True)):
                return self.status()
            self.cancelled = False
            self.worker = threading.Thread(target=self._start, args=(experimental_main_live, media_mode,
                download_missing_resources, resource_cache_dir), name="local-server-start", daemon=False)
            self.worker.start()
        self.status()

    def resources(self, action, command):
        """Reserve work quickly; archive I/O must never occupy the IPC reader."""
        with self.lock:
            runtime = self.runtime
            library = getattr(runtime, "_library", None) if runtime is not None else None
            if self.closed or library is None or not runtime.status().get("running"):
                self.emit("resource_error", message="먼저 서버를 시작해 주세요.")
                return
        try:
            if action == "resources_cancel":
                identifier = command.get("job_id")
                if not isinstance(identifier, str) or not 1 <= len(identifier) <= 64:
                    raise ValueError("Invalid job identifier")
                library.cancel(identifier)
                self.status()
                return
            platform = command.get("platform")
            if platform not in ("android", "ios"):
                raise ValueError("Invalid resource platform")
            if action == "resources_preview":
                library.catalog_summary(platform)
                self.status()
                return
            if action == "resources_download":
                if "parallelism" in command:
                    parallelism = command["parallelism"]
                    if type(parallelism) is not int or parallelism not in (1, 2, 4, 8):
                        raise ValueError("Invalid download parallelism")
                    library.start_download(platform, parallelism=parallelism)
                else:
                    library.start_download(platform)
                self.status()
                return
            value = command.get("path")
            if not isinstance(value, str) or not 1 <= len(value) <= 4096 or "\0" in value:
                raise ValueError("Invalid archive path")
            path = Path(value)
            if not path.is_absolute() or path.suffix.lower() != ".zip" or path.is_symlink():
                raise ValueError("Invalid archive path")
            with self.lock:
                if self.resource_worker is not None and self.resource_worker.is_alive():
                    self.emit("resource_error", message="진행 중인 보관 작업을 먼저 마치거나 취소해 주세요.")
                    return
                self.resource_worker = threading.Thread(
                    target=self._resource_archive, args=(library, action, platform, path),
                    name="local-resource-archive", daemon=True)
                self.resource_worker.start()
        except (OSError, ValueError, RuntimeError):
            self.emit("resource_error", message="리소스 요청을 처리하지 못했습니다. 진행 중인 작업과 플랫폼을 확인해 주세요.")

    def _resource_archive(self, library, action, platform, path):
        temporary = None
        job = None
        try:
            if action == "resources_export":
                job = library.prepare_export(platform)
                fd, temporary = tempfile.mkstemp(prefix=".idoly-resource-", suffix=".part", dir=path.parent)
                with os.fdopen(fd, "wb") as output:
                    result = library.write_export(job["job_id"], output)
                    output.flush()
                    os.fsync(output.fileno())
                if (result.get("state") not in ("completed", "partial")
                        or result.get("archive_complete") is not True or result.get("failed_files") != 0):
                    raise ValueError("Archive export did not complete")
                if path.is_symlink():
                    raise ValueError("Archive destination changed")
                os.replace(temporary, path)
                temporary = None
                missing = result.get("missing_files", 0)
                message = f"보관 ZIP을 저장했습니다. 미보관 파일 {missing}개는 포함되지 않았습니다."
            elif action == "resources_import":
                fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                with os.fdopen(fd, "rb") as source:
                    if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                        raise ValueError("A regular archive is required")
                    result = library.import_from(source, platform)
                if result.get("state") not in ("completed", "partial"):
                    raise ValueError("Archive import did not complete")
                imported, failed = result.get("imported_files", 0), result.get("failed_files", 0)
                if failed or result.get("error_code") is not None:
                    self.emit("resource_error", message=f"일부 파일을 가져오지 못했습니다. 확인 완료 {imported}개 · 실패 {failed}개. 확인된 캐시는 유지됩니다.")
                    return
                message = f"원본 크기·MD5를 확인한 파일 {imported}개를 서버 캐시에 가져왔습니다."
            else:
                raise ValueError("Unsupported archive action")
            self.emit("resource_result", message=message)
        except (OSError, ValueError, RuntimeError):
            if job is not None:
                library.cancel(job["job_id"])
            self.emit("resource_error", message="보관 ZIP 작업이 중단되었습니다. 완료 파일과 기존 캐시는 유지됩니다.")
        finally:
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass
            self.status()


    def accounts(self, action, command):
        """The native app owns picker approval; no account mutation is exposed over HTTP."""
        identifier = command.get("request_id")
        if type(action) is not str or action not in _ACCOUNT_ACTIONS or type(identifier) is not int or not 1 <= identifier <= 2**31 - 1:
            self.emit("account_error", request_id=identifier if type(identifier) is int else None,
                      action=action if type(action) is str and action in _ACCOUNT_ACTIONS else None,
                      code="account_request_invalid")
            return
        payload = {key: value for key, value in command.items()
                   if key not in ("action", "request_id", "destination")}
        with self.lock:
            if self.closed:
                return
            if ((self.account_worker is not None and self.account_worker.is_alive())
                    or (self.official_worker is not None and self.official_worker.is_alive())):
                self.emit("account_error", request_id=identifier, action=action, code="account_operation_busy")
                return
            if self.worker is not None and self.worker.is_alive():
                self.emit("account_error", request_id=identifier, action=action, code="account_server_starting")
                return
            # Replacement is deliberately stopped-server only, even if the game
            # currently looks idle. Selecting an account merely queues a restart.
            if action == "accounts_restore" or (action == "accounts_import" and payload.get("replace") is True):
                if self.runtime is not None:
                    self.emit("account_error", request_id=identifier, action=action, code="account_server_running")
                    return
            self.account_worker = threading.Thread(target=self._account_operation,
                args=(identifier, action, payload, command.get("destination")),
                name="local-account-operation", daemon=True)
            self.account_worker.start()

    def _account_operation(self, identifier, action, payload, destination):
        self.emit("account_progress", request_id=identifier, action=action, stage="preparing")
        preparing_catalog = False
        try:
            if action == "settings_clear_history":
                if payload:
                    raise ValueError("account_request_invalid")
                from idoly_local import app_runtime
                with self.lock:
                    runtime = self.runtime
                if runtime is not None:
                    settings = runtime.clear_history()
                else:
                    settings = app_runtime.clear_server_history(self.data_dir)
                result = {"schema": 1, "ok": True, "action": action, "settings": settings}
            else:
                if action != "accounts_status" and not (self.data_dir / "protocol/idolypride-6.1.1.pb").is_file():
                    preparing_catalog = True
                    install_payload(self.server_data, self.data_dir, self.log)
                    preparing_catalog = False
                from idoly_local.account_manager import account_command
                result = account_command(self.data_dir, action, payload)
                if type(result) is not dict or result.get("ok") is not True or result.get("action") != action:
                    raise ValueError("account_response_invalid")
                if action == "accounts_export":
                    _account_export_copy(self.data_dir, result, destination,
                        lambda received, total: self.emit("account_progress", request_id=identifier,
                            action=action, stage="copying", received_bytes=received, total_bytes=total))
                    # Native picker paths are private command inputs, not log/UI payload.
                    result = {key: value for key, value in result.items() if key != "path"}
                with self.lock:
                    if isinstance(result.get("status"), dict):
                        self.account_status = result["status"]
            with self.lock:
                closed = self.closed
            if not closed:
                self.emit("account_result", request_id=identifier, action=action, result=result)
        except Exception as error:
            if preparing_catalog:
                from idoly_local.app_runtime import record_startup_failure
                record_startup_failure(self.data_dir, error, stage="catalog")
            value = str(error)
            code = value if re.fullmatch(r"[a-z][a-z0-9_]{1,79}", value) else "account_operation_failed"
            with self.lock:
                closed = self.closed
            if not closed:
                self.emit("account_error", request_id=identifier, action=action, code=code)
        finally:
            with self.lock:
                self.account_worker = None
                closed = self.closed
            if not closed:
                self.status()


    def events(self, action, command):
        identifier = command.get("request_id")
        payload = {key: value for key, value in command.items() if key not in ("action", "request_id")}
        valid = type(action) is str and action in _EVENT_ACTIONS
        try:
            if not valid or type(identifier) is not int or not 1 <= identifier <= 2**31-1:
                raise ValueError("event_settings_command_invalid")
            if len(json.dumps(command, separators=(",", ":"), ensure_ascii=True).encode("utf-8")) + 1 > 512:
                raise ValueError("event_settings_command_invalid")
            payload = _event_payload(action, payload)
        except (ValueError, TypeError, RecursionError):
            self.emit("events_error", request_id=identifier if type(identifier) is int else None,
                action=action if valid else None, code="event_settings_command_invalid")
            return
        with self.lock:
            if self.closed: return
            if self.events_worker and self.events_worker.is_alive():
                self.emit("events_error", request_id=identifier, action=action, code="event_settings_busy")
                return
            self.events_worker = threading.Thread(target=self._events_operation,
                args=(identifier, action, payload), name="local-event-settings-command", daemon=True)
            self.events_worker.start()

    def _events_operation(self, identifier, action, payload):
        errors = frozenset()
        try:
            from idoly_local.event_settings import event_settings_command, ERROR_CODES
            errors = ERROR_CODES
            with self.lock: runtime = self.runtime
            effective = None
            if runtime is not None:
                effective = runtime.status().get("event_settings", {}).get("effective")
            result = event_settings_command(self.data_dir, action, payload, effective=effective)
            with self.lock: closed = self.closed
            if not closed:
                self.emit("events_result", request_id=identifier, action=action, result=result)
        except Exception as error:
            code = getattr(error, "code", None)
            if type(code) is not str or code not in errors: code = "event_settings_io"
            with self.lock: closed = self.closed
            if not closed: self.emit("events_error", request_id=identifier, action=action, code=code)
        finally:
            with self.lock:
                self.events_worker = None
                closed = self.closed
            if not closed: self.status()

    def official(self, action, command):
        identifier = command.get("request_id")
        payload = {key: value for key, value in command.items() if key not in ("action", "request_id")}
        # Do not leave credentials in the stdin parser's last-command object.
        command.pop("password", None); command.pop("user_id", None)
        valid = type(action) is str and action in _OFFICIAL_ACTIONS
        if not valid or type(identifier) is not int or not 1 <= identifier <= 2**31-1:
            payload.clear()
            self.emit("official_error", request_id=identifier if type(identifier) is int else None,
                action=action if valid else None, code="official_request_invalid")
            return
        try:
            _official_payload(action, payload)
        except (ValueError, TypeError):
            payload.clear()
            self.emit("official_error", request_id=identifier, action=action, code="official_request_invalid")
            return
        with self.lock:
            code = None
            if self.closed:
                payload.clear(); return
            if ((self.official_worker and self.official_worker.is_alive())
                    or (self.account_worker and self.account_worker.is_alive())):
                code = "official_operation_busy"
            elif self.worker and self.worker.is_alive():
                code = "official_server_starting"
            elif action == "official_apply" and self.runtime is not None:
                code = "official_server_running"
            if code:
                payload.clear()
                self.emit("official_error", request_id=identifier, action=action, code=code)
                return
            self.official_worker = threading.Thread(target=self._official_operation,
                args=(identifier, action, payload), name="local-official-import-command", daemon=True)
            self.official_worker.start()

    def _official_operation(self, identifier, action, payload):
        try:
            if action in ("official_inspect", "official_fetch", "official_apply") and not (self.data_dir/"protocol/idolypride-6.1.1.pb").is_file():
                install_payload(self.server_data, self.data_dir, self.log)
            with self.lock:
                if self.closed: return
                if self.official_manager is None:
                    from idoly_local.official_import import OfficialImportManager, ERROR_CODES
                    self.official_error_codes = frozenset(ERROR_CODES) | _OFFICIAL_HOST_ERRORS
                    self.official_manager = OfficialImportManager(self.data_dir)
                manager = self.official_manager
            result = manager.command(action, payload)
            payload.clear()
            if type(result) is not dict or result.get("action") != action or type(result.get("job")) is not dict:
                raise ValueError("official_response_invalid")
            safe = {"action": action, "job": _official_job(result["job"], private=True, errors=self.official_error_codes)}
            if action == "official_apply":
                if type(result.get("status")) is dict:
                    safe["status"] = result["status"]
                    with self.lock: self.account_status = result["status"]
                if type(result.get("account")) is dict:
                    safe["account"] = result["account"]
                if safe["job"]["state"] == "completed":
                    warnings = result.get("warning_codes")
                    if type(warnings) is list:
                        safe["warning_codes"] = sorted({code for code in warnings
                            if type(code) is str and code in _OFFICIAL_WARNINGS})
                    if type(result.get("status_refresh_required")) is bool:
                        safe["status_refresh_required"] = result["status_refresh_required"]
            with self.lock: closed = self.closed
            if not closed:
                self.emit("official_result", request_id=identifier, action=action, result=safe)
        except Exception as error:
            code = getattr(error, "code", None)
            if code not in self.official_error_codes:
                code = "official_response_invalid" if str(error) == "official_response_invalid" else "official_operation_failed"
            with self.lock: closed = self.closed
            if not closed:
                self.emit("official_error", request_id=identifier, action=action, code=code)
        finally:
            payload.clear()
            with self.lock:
                self.official_worker = None
                closed = self.closed
            if not closed: self.status()

    def _start(self, experimental_main_live=False, media_mode=False, download_missing_resources=True,
               resource_cache_dir=None):
        runtime = None
        runtime_entered = False
        try:
            self.log("서버 데이터를 준비하고 있습니다.")
            install_payload(self.server_data, self.data_dir, self.log)
            try:
                selected_root = Path(resource_cache_dir) if resource_cache_dir is not None else self.data_dir
                self.translation_status = install_bundled_translations(
                    self.server_data, selected_root, self.log, data_dir=self.data_dir)
            except (OSError, ValueError) as error:
                from idoly_local.app_runtime import record_startup_failure
                record_startup_failure(self.data_dir, error, stage="catalog")
                self.translation_status = {"state": "failed", "installed": False,
                                           "previous_files_preserved": True}
                self.log("번역 패키지를 설치하지 못했습니다. 기존 번역과 원본 자료는 변경하지 않았습니다.")
            from idoly_local import app_runtime
            with self.lock:
                if self.cancelled or self.closed:
                    return
            live_options = {"experimental_main_live": True} if experimental_main_live else {}
            runtime_entered = True
            runtime = app_runtime.start(self.data_dir, profile=self.profile, log_callback=self.log,
                                       media_mode=media_mode, download_missing_resources=download_missing_resources,
                                       resource_platform="ios", resource_cache_dir=resource_cache_dir, **live_options)
            with self.lock:
                self.runtime = runtime
                cancelled = self.cancelled or self.closed
            if cancelled:
                self.stop()
            else:
                self.log("로컬 서버가 시작되었습니다.")
        except Exception as error:
            if not runtime_entered:
                from idoly_local.app_runtime import record_startup_failure
                record_startup_failure(self.data_dir, error, stage="catalog")
            if runtime is not None:
                with self.lock:
                    self.runtime = runtime
                self.stop()
            self.log("서버 시작 실패: " + type(error).__name__)
            self.emit("error", message="서버를 시작하지 못했습니다. 데이터와 포트 사용 상태를 확인해 주세요.")
        finally:
            # This worker is about to finish; avoid reporting a stale starting state.
            with self.lock:
                self.worker = None
            self.status()

    def stop(self):
        with self.lock:
            self.cancelled = True
            runtime = self.runtime
        if runtime is not None:
            try:
                runtime.stop()
            except Exception as error:
                self.log("서버 중지 실패: " + type(error).__name__)
                self.emit("error", message="서버를 완전히 중지하지 못했습니다. 중지를 다시 눌러 주세요.")
            else:
                with self.lock:
                    if self.runtime is runtime:
                        self.runtime = None
                self.log("로컬 서버가 중지되었습니다.")
        return self.status()

    def close(self):
        with self.lock:
            self.closed = True
            worker = self.worker
            account_worker = self.account_worker
            official_worker = self.official_worker
            events_worker = self.events_worker
            official_manager = self.official_manager
        if official_manager is not None:
            official_manager.close()
        self.stop()
        if worker and worker is not threading.current_thread():
            worker.join(timeout=20)
        if account_worker and account_worker is not threading.current_thread():
            account_worker.join(timeout=20)
        if official_worker and official_worker is not threading.current_thread():
            official_worker.join(timeout=20)
        if events_worker and events_worker is not threading.current_thread():
            events_worker.join(timeout=20)
        self.stop()


def _rpc(address, schema, method, request=None, token=None, *, expected_status="0", request_id=None, timeout=5):
    """Exercise the frozen pure-Python HTTP/2 stack without importing grpcio."""
    from h2.config import H2Configuration
    from h2.connection import H2Connection
    from h2.events import DataReceived, ResponseReceived, StreamEnded, TrailersReceived
    from idoly_local import codec

    if request is None:
        request = schema.request_type(method)()
    payload = codec.encode(request.SerializeToString())
    host, port = address.rsplit(":", 1)
    client = H2Connection(H2Configuration(client_side=True, header_encoding="utf-8"))
    client.initiate_connection()
    headers = [(":method", "POST"), (":scheme", "http"), (":authority", address),
        (":path", method), ("content-type", "application/grpc+proto"), ("te", "trailers")]
    if token is not None:
        headers.append(("x-auth-token", token))
    if request_id is not None:
        headers.append(("x-app-request-id", str(request_id)))
    client.send_headers(1, headers)
    client.send_data(1, b"\0" + len(payload).to_bytes(4, "big") + payload, end_stream=True)
    body, status, ended = bytearray(), None, False
    with socket.create_connection((host, int(port)), timeout=timeout) as stream:
        stream.sendall(client.data_to_send())
        while not ended:
            data = stream.recv(65535)
            if not data:
                raise RuntimeError("HTTP/2 RPC ended before its trailers")
            for event in client.receive_data(data):
                if isinstance(event, DataReceived):
                    body.extend(event.data)
                    client.acknowledge_received_data(event.flow_controlled_length, event.stream_id)
                elif isinstance(event, (ResponseReceived, TrailersReceived)):
                    status = dict(event.headers).get("grpc-status", status)
                elif isinstance(event, StreamEnded):
                    ended = True
            pending = client.data_to_send()
            if pending:
                stream.sendall(pending)
    if status != expected_status:
        raise RuntimeError("Local RPC returned an unexpected gRPC status: " + method)
    if expected_status != "0":
        if body:
            raise RuntimeError("Rejected local RPC unexpectedly returned a message: " + method)
        return None
    if len(body) < 5 or body[0] != 0 or int.from_bytes(body[1:5], "big") != len(body) - 5:
        raise RuntimeError("Local RPC returned an invalid gRPC response: " + method)
    return schema.response_type(method).FromString(codec.decode(bytes(body[5:])))


def _home_hierarchy_reference(home, data_dir):
    grade_id = home.hierarchyNotiInfo.currentDetailGradeId
    if not grade_id:
        return False
    master_dir = Path(data_dir) / "master-json"
    details = json.loads((master_dir / "HierarchyDetailGrade.json").read_text())
    grades = json.loads((master_dir / "HierarchyGrade.json").read_text())
    matches = [row for row in details if row.get("id") == grade_id]
    if len(matches) != 1:
        return False
    parent_id = matches[0].get("hierarchyGradeId")
    return bool(parent_id) and sum(row.get("id") == parent_id for row in grades) == 1


def _home_positions_distinct(user):
    positions = list(user.homePositions)
    assigned = {row.characterId for row in positions}
    owned = {row.characterId for row in user.characters}
    return (len(positions) == 4 and {row.homePositionType for row in positions} == {1, 2, 3, 4}
            and len(assigned) == 4 and assigned.issubset(owned)
            and all(not row.isCharacterRandom and not row.isCostumeRandom for row in positions)
            and next(row.characterId for row in positions if row.homePositionType == 1) == "char-ktn")


def _initial_inventory_reference(user, data_dir):
    """Check bootstrap inventory directly against public tables, not seeding code."""
    master = Path(data_dir) / "master-json"
    tables = {name: json.loads((master / (name + ".json")).read_text()) for name in
              ("Reward", "Item", "Card", "CardParameter", "CardRarity", "CardLevelRelease", "Skill",
               "Setting", "Character", "Costume", "Hair")}

    def one(name, predicate):
        matches = [row for row in tables[name] if predicate(row)]
        if len(matches) != 1:
            raise RuntimeError("Initial inventory needs one matching public " + name + " row")
        return matches[0]

    def indexed(name):
        values = tables[name]
        result = {row["id"]: row for row in values}
        if len(result) != len(values):
            raise RuntimeError("Initial inventory has duplicate public " + name + " identities")
        return result

    reward = one("Reward", lambda row: row.get("id") == "initial_user_reward")
    resources = reward["resources"]
    if any(row.get("resourceType") not in (1, 2, 4) for row in resources):
        raise RuntimeError("Initial reward contains unsupported resources")
    grants = {kind: [row for row in resources if row["resourceType"] == kind] for kind in (1, 2, 4)}
    card_ids = [row["resourceId"] for row in grants[2]]
    character_ids = [row["resourceId"] for row in grants[4]]
    item_amounts = {row["resourceId"]: int(row["amount"]) for row in grants[1]}
    if (len(card_ids) != 17 or len(set(card_ids)) != 17
            or len(character_ids) != 17 or len(set(character_ids)) != 17
            or len(grants[1]) != 2 or len(item_amounts) != 2
            or any(int(row["amount"]) != 1 for kind in (2, 4) for row in grants[kind])):
        raise RuntimeError("Canonical initial reward must contain 17 unique cards/characters and two items")
    cards, skills, items = indexed("Card"), indexed("Skill"), indexed("Item")
    characters, costumes, hairs = indexed("Character"), indexed("Costume"), indexed("Hair")
    if (not set(character_ids).issubset(characters) or not set(item_amounts).issubset(items)
            or not set(character_ids).issubset(row.characterId for row in user.characters)):
        raise RuntimeError("Initial reward resources do not resolve to public character/item tables")
    if (len(user.cards) != 17 or {row.cardId for row in user.cards} != set(card_ids)
            or len(user.items) != 2 or {row.itemId: row.amount for row in user.items} != item_amounts
            or any(row.expiredTime for row in user.items) or user.balance.SerializeToString()):
        raise RuntimeError("User.Get does not contain exactly the canonical initial cards/items without premium currency")
    setting = one("Setting", lambda _row: True)
    owners = set()
    for observed in user.cards:
        card = cards.get(observed.cardId)
        if card is None or card.get("characterId") not in character_ids or card["characterId"] in owners:
            raise RuntimeError("Initial cards must resolve to distinct canonical reward characters")
        owners.add(card["characterId"])
        rarity = one("CardRarity", lambda row: row.get("rarity") == card["initialRarity"])
        parameter = one("CardParameter", lambda row: row.get("id") == card["cardParameterId"] and row.get("level") == 1)
        release = one("CardLevelRelease", lambda row: row.get("id") == card["cardLevelReleaseId"] and row.get("level") == 1)
        expected = type(observed)(cardId=observed.cardId, level=1, baseLevel=1, rarity=card["initialRarity"],
                                  mental=setting["cardDefaultMental"], technique=setting["cardDefaultTechnique"], displayType=1)
        for name in ("vocal", "dance", "visual", "stamina"):
            base = int(parameter["staminaValue"] if name == "stamina" else parameter["value"])
            # Both integer floors are observable in the client parameter calculation.
            value = (base * int(card[name + "RatioPermil"]) // 1000) * int(rarity["parameterBonusPermil"]) // 1000
            setattr(expected, name, value)
            setattr(expected, "base" + name.capitalize(), value)
        targets = release["targets"]
        if any(row["type"] not in (1, 4, 7) for row in targets):
            raise RuntimeError("Initial level-one release contains unsupported skill/ability targets")
        unlocked = {row["number"] for row in targets if row["type"] == 1}
        if 1 not in unlocked or not unlocked.issubset({1, 2, 3, 4}):
            raise RuntimeError("Initial card release does not define a valid first learned skill")
        expected.photoEquipableCount = expected.basePhotoEquipableCount = sum(
            row["number"] for row in targets if row["type"] == 7)
        for position in unlocked:
            skill_id = card["skillId" + str(position)]
            skill = skills.get(skill_id)
            first = [row for row in skill.get("levels", []) if row.get("level") == 1] if skill else []
            if len(first) != 1 or int(first[0].get("requiredCardLevel", 0)) > 1:
                raise RuntimeError("Initial learned skill does not resolve to a usable first skill level")
            for prefix in ("skillId", "baseSkillId"):
                setattr(expected, prefix + str(position), skill_id)
            for prefix in ("skillLevel", "baseSkillLevel"):
                setattr(expected, prefix + str(position), 1)
        actual = type(observed)()
        actual.CopyFrom(observed)
        actual.ClearField("obtainedTime")
        if (observed.obtainedTime <= 0
                or actual.SerializeToString(deterministic=True) != expected.SerializeToString(deterministic=True)):
            raise RuntimeError("Initial UserCard fields differ from public level-one parameters/releases/skills")
    if owners != set(character_ids):
        raise RuntimeError("Initial cards do not cover the canonical reward characters")
    if (len(user.decks) != 1 or user.decks[0].number != 1 or user.user.deckSequence != 1
            or len(user.deckPositions) != 5 or {row.number for row in user.deckPositions} != {1}
            or {row.position for row in user.deckPositions} != {1, 2, 3, 4, 5}
            or len({row.cardId for row in user.deckPositions}) != 5):
        raise RuntimeError("Default unit must contain five distinct owned cards in deck-one slots 1..5")
    owned_cards = {row.cardId for row in user.cards}
    owned_costumes = {row.costumeId for row in user.costumes}
    owned_hairs = {row.hairId for row in user.hairs}
    unit_characters = set()
    for position in user.deckPositions:
        card = cards.get(position.cardId)
        owner = card.get("characterId") if card else None
        costume, hair = costumes.get(position.costumeId), hairs.get(position.hairId)
        if (position.cardId not in owned_cards or owner in unit_characters
                or position.costumeId not in owned_costumes or position.hairId not in owned_hairs
                or costume is None or hair is None
                or costume.get("characterId") != owner or hair.get("characterId") != owner
                or (hair.get("wearableCostumeIds") is not None and position.costumeId not in hair["wearableCostumeIds"])
                or position.part1AccessoryId or position.part2AccessoryId or position.photoIds):
            raise RuntimeError("Default unit has an unowned, repeated or mismatched card/appearance reference")
        unit_characters.add(owner)
    return {"initial_card_count": len(user.cards), "initial_item_count": len(user.items), "default_unit_slot_count": 5}


def _quest_tutorial_pending(user):
    starts = [row for row in user.tutorials if row.tutorialType == 1]
    if len(starts) > 1 or starts and starts[0].step < 0:
        raise RuntimeError("Quest smoke check needs an unambiguous GameStart tutorial state")
    return not starts or starts[0].step < 150


def _quest_list_asset_reference(response, user, data_dir, tutorial=None):
    """Verify the seeded explicit unit against owned state and public tables.

    This smoke fixture has explicit compatible costume/hair IDs in every slot;
    sparse-deck fallback behavior is tested by the server's own request tests.
    """
    def indexed(values, key, description):
        result = {}
        for row in values:
            identity = row.get(key) if isinstance(row, dict) else getattr(row, key)
            if not isinstance(identity, str) or not identity or identity in result:
                raise RuntimeError("Live asset check needs unique " + description + " identities")
            result[identity] = row
        return result

    master = Path(data_dir) / "master-json"
    tables = {}
    for name in ("Card", "Character", "Costume", "Hair"):
        rows = json.loads((master / (name + ".json")).read_text())
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise RuntimeError("Live asset check needs a public " + name + " table")
        tables[name] = indexed(rows, "id", "public " + name)
    owned = {name: indexed(getattr(user, name), key, "owned " + name)
             for name, key in (("cards", "cardId"), ("characters", "characterId"),
                               ("costumes", "costumeId"), ("hairs", "hairId"))}
    decks = [row for row in user.decks if row.number == 1]
    positions = sorted((row for row in user.deckPositions if row.number == 1), key=lambda row: row.position)
    if (len(decks) != 1 or len(positions) != 5
            or [row.position for row in positions] != [1, 2, 3, 4, 5]):
        raise RuntimeError("Live asset check needs a complete five-slot deck one")
    expected = type(response)()
    expected.commonResponse.SetInParent()
    seen_characters = set()
    for position in positions:
        card = tables["Card"].get(position.cardId)
        character_id = card.get("characterId") if card else None
        costume = tables["Costume"].get(position.costumeId)
        hair = tables["Hair"].get(position.hairId)
        allowed = (hair.get("wearableCostumeIds") or []) if hair else []
        denied = (hair.get("notWearableCostumeIds") or []) if hair else []
        wearable = (not allowed and not denied) or position.costumeId in allowed or (
            bool(denied) and position.costumeId not in denied)
        if (position.cardId not in owned["cards"] or character_id not in owned["characters"]
                or character_id not in tables["Character"] or character_id in seen_characters
                or position.costumeId not in owned["costumes"] or position.hairId not in owned["hairs"]
                or costume is None or hair is None or costume.get("characterId") != character_id
                or hair.get("characterId") != character_id or not wearable):
            raise RuntimeError("Live asset unit has an unowned or incompatible card/character/appearance")
        seen_characters.add(character_id)
        expected.characterAssets.add(characterId=character_id, costumeId=position.costumeId, hairId=position.hairId)
    if tutorial is not None:
        seen = {(row.characterId, row.costumeId, row.hairId) for row in expected.characterAssets}
        for triple in _tutorial_appearances(tutorial):
            if triple not in seen:
                expected.characterAssets.add(characterId=triple[0], costumeId=triple[1], hairId=triple[2])
                seen.add(triple)
    if response.SerializeToString(deterministic=True) != expected.SerializeToString(deterministic=True):
        raise RuntimeError("Quest.ListAsset must return ordered owned appearances, required recorded extras and an empty common response")
    return len(expected.characterAssets)


def _tutorial_fixture(response_type, data_dir, kind):
    raw = (Path(data_dir) / "public-tutorial" / ("tutorial-" + kind + ".pb")).read_bytes()
    if hashlib.sha256(raw).hexdigest() != _TUTORIAL_PINS[kind][0]:
        raise RuntimeError("Public tutorial fixture does not match the pinned sanitized official capture")
    return response_type.FromString(raw)


def _tutorial_appearances(replay):
    if len(replay.result.userInfos) != 1:
        raise RuntimeError("Tutorial replay must retain the single captured demonstration user")
    deck = replay.result.userInfos[0].userDeck
    if ([row.index for row in deck.cards] != [1, 2, 3, 4, 5]
            or len(deck.extraCharacterInfos) != 1 or deck.extraCharacterInfos[0].position != 6):
        raise RuntimeError("Tutorial replay needs the five recorded cards and its sixth appearance")
    return [(row.displayCharacterId, row.displayCostumeId, row.displayHairId) for row in deck.cards] + [
        (row.characterId, row.costumeId, row.hairId) for row in deck.extraCharacterInfos]


def _tutorial_replay_reference(response, user, data_dir, kind):
    """Compare the complete official recording after the three local identity fields."""
    canonical = _tutorial_fixture(type(response), data_dir, kind)
    master = Path(data_dir) / "master-json"

    def rows(name):
        values = json.loads((master / (name + ".json")).read_text())
        if not isinstance(values, list) or not values or any(not isinstance(row, dict) for row in values):
            raise RuntimeError("Tutorial replay needs a public " + name + " table")
        return values

    def indexed(name):
        values = rows(name)
        result = {row.get("id"): row for row in values}
        if len(result) != len(values) or any(not isinstance(key, str) or not key for key in result):
            raise RuntimeError("Tutorial replay needs unique public " + name + " identities")
        return result

    tables = {name: indexed(name) for name in ("Quest", "Area", "Music", "Stage", "Emblem", "Card",
              "Character", "Costume", "Hair", "Skill", "SkillEfficacy", "SkillTrigger", "SkillTarget")}
    settings = rows("Setting")
    field = "tutorial" + kind.capitalize() + "QuestId"
    quest_id = settings[0].get(field) if len(settings) == 1 else None
    quest = tables["Quest"].get(quest_id)
    if (quest_id != "qt-tutorial-" + kind or quest is None
            or quest.get("areaId") not in tables["Area"]
            or tables["Area"][quest["areaId"]].get("type") != 101
            or quest.get("musicId") not in tables["Music"] or quest.get("stageId") not in tables["Stage"]):
        raise RuntimeError("Tutorial quest/music/stage does not resolve through the bundled master")
    chart_keys = {(row.get("number"), row.get("type")) for row in rows("MusicChartPattern")
                  if row.get("id") == quest.get("musicChartPatternId")}
    if not chart_keys or any((row.number, row.chartType) not in chart_keys for row in canonical.result.charts):
        raise RuntimeError("Recorded tutorial charts do not resolve through the quest music pattern")
    for character, costume, hair in _tutorial_appearances(canonical):
        costume_row, hair_row = tables["Costume"].get(costume), tables["Hair"].get(hair)
        allowed = (hair_row.get("wearableCostumeIds") or []) if hair_row else []
        denied = (hair_row.get("notWearableCostumeIds") or []) if hair_row else []
        wearable = (not allowed and not denied) or costume in allowed or (bool(denied) and costume not in denied)
        if (character not in tables["Character"] or costume_row is None or hair_row is None
                or costume_row.get("characterId") != character or hair_row.get("characterId") != character or not wearable):
            raise RuntimeError("Recorded tutorial appearance does not resolve through the bundled master")
    owned_cards = {row.cardId: row for row in user.cards}
    for card in canonical.result.userInfos[0].userDeck.cards:
        public = tables["Card"].get(card.cardId)
        if public is None or public.get("characterId") != card.displayCharacterId:
            raise RuntimeError("Recorded tutorial card does not resolve to its displayed character")
        owned_card = owned_cards.get(card.cardId)
        parameters = ("level", "rarity", "vocal", "dance", "visual", "stamina", "mental", "technique",
                      "skillLevel1", "skillLevel2", "skillLevel3", "skillLevel4")
        # smoke() has independently checked every initial UserCard against
        # public CardParameter/Rarity's two integer floors and skill releases.
        if (owned_card is None or card.startStamina != card.stamina
                or any(getattr(card, field) != getattr(owned_card, field) for field in parameters)):
            raise RuntimeError("Recorded tutorial parameters differ from the master-verified initial owned card")
        for skill in card.skills:
            public_skill = tables["Skill"].get(skill.skillId)
            levels = [row for row in public_skill.get("levels", []) if row.get("level") == skill.skillLevel] if public_skill else []
            if skill.skillId not in {public.get("skillId" + str(i)) for i in range(1, 5)} or len(levels) != 1:
                raise RuntimeError("Recorded tutorial skill does not resolve through its public card/level")
            level = levels[0]
            if level.get("triggerId") and level["triggerId"] not in tables["SkillTrigger"]:
                raise RuntimeError("Recorded tutorial skill trigger is absent from the public master")
            for detail in level.get("skillDetails", []):
                efficacy = tables["SkillEfficacy"].get(detail.get("efficacyId"))
                if (efficacy is None
                        or (efficacy.get("skillTargetId") and efficacy["skillTargetId"] not in tables["SkillTarget"])
                        or (detail.get("triggerId") and detail["triggerId"] not in tables["SkillTrigger"])):
                    raise RuntimeError("Recorded tutorial skill detail does not resolve through the public master")
    if not user.userPublic.publicUserId:
        raise RuntimeError("Tutorial replay smoke needs the local public user ID")
    expected = type(response)()
    expected.CopyFrom(canonical)
    info = expected.result.userInfos[0]
    info.userId, info.name = user.userPublic.publicUserId, user.user.name
    if user.user.emblemId in tables["Emblem"]:
        info.emblemId = user.user.emblemId
    if info.emblemId not in tables["Emblem"]:
        raise RuntimeError("Tutorial replay emblem does not resolve through the bundled master")
    if response.SerializeToString(deterministic=True) != expected.SerializeToString(deterministic=True):
        raise RuntimeError("Tutorial replay differs from the pinned official result/ranks beyond local identity")
    chart_count, score = len(response.result.charts), response.result.userInfos[0].userResult.score
    if (chart_count, score) != _TUTORIAL_PINS[kind][1:]:
        raise RuntimeError("Tutorial replay changed its official chart count or score")
    return {"tutorial_replay_" + kind + "_charts": chart_count, "tutorial_replay_" + kind + "_score": score}


def _whole_database_state(data_dir):
    """Keep a logical all-table snapshot in memory; never export account rows."""
    path = (Path(data_dir) / "state.db").resolve()
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as connection:
        return tuple(connection.iterdump())


def _preserved_database_state(data_dir):
    """Keep identity/session/settings/upgrade rows in memory during progression."""
    path = (Path(data_dir) / "state.db").resolve()
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as connection:
        return {name: connection.execute("SELECT * FROM " + name + " ORDER BY 1").fetchall()
                for name in ("profiles", "sessions", "profile_settings", "starter_profiles")}


def _quest_catalog_reference(top, main, data_dir, user):
    """Check encrypted responses against the bundled public table references."""
    if ([group.SerializeToString() for group in top.mainAreaGroups]
            != [group.SerializeToString() for group in main.areaGroups]):
        raise RuntimeError("Quest.Top and Quest.ListMain returned different main area groups")
    if (not top.HasField("pvpInfo") or top.pvpInfo.HasField("latestPvpSeason")
            or not top.HasField("hierarchyNotiInfo") or not _home_hierarchy_reference(top, data_dir)):
        raise RuntimeError("Quest.Top omitted required local PvP/hierarchy references")
    master_dir = Path(data_dir) / "master-json"

    def rows(name):
        values = json.loads((master_dir / (name + ".json")).read_text())
        identities = [row.get("id") for row in values]
        if not values or any(not isinstance(key, str) or not key for key in identities) or len(set(identities)) != len(values):
            raise RuntimeError("Quest smoke check needs unique bundled " + name + " identities")
        return {row["id"]: row for row in values}

    groups, areas, quests = rows("AreaGroup"), rows("Area"), rows("Quest")
    tutorial_pending = _quest_tutorial_pending(user)
    normal_ids = {key for key, row in areas.items() if row.get("type") == 1}
    tutorial_ids = {key for key, row in areas.items() if row.get("type") == 101}
    main_ids = normal_ids | tutorial_ids if tutorial_pending else normal_ids
    if tutorial_pending and (tutorial_ids != {"area-tutorial"}
            or areas["area-tutorial"].get("areaGroupId") != "area-main-group-999"
            or areas["area-tutorial"].get("questIds") != ["qt-tutorial-full", "qt-tutorial-short"]):
        raise RuntimeError("Pending GameStart needs the real tutorial group and full/short quest alternatives")
    ordered_groups = sorted(groups.values(), key=lambda row: (int(row.get("order", 0)), row["id"]))
    expected_groups = []
    for group in ordered_groups:
        area_ids = group.get("areaIds")
        if not isinstance(area_ids, list) or not area_ids or any(key not in areas for key in area_ids):
            raise RuntimeError("Bundled AreaGroup references an absent area")
        if any(key in main_ids for key in area_ids):
            expected_groups.append(group)
    if [group.areaGroupId for group in top.mainAreaGroups] != [group["id"] for group in expected_groups]:
        raise RuntimeError("Quest group identities/order do not match the bundled AreaGroup catalog")
    seen_areas, seen_quests = set(), set()
    for output_group, group in zip(top.mainAreaGroups, expected_groups):
        if [area.areaId for area in output_group.areas] != group["areaIds"]:
            raise RuntimeError("Quest area identities/order do not match bundled AreaGroup references")
        for output_area in output_group.areas:
            area_id = output_area.areaId
            area = areas[area_id]
            if (area_id not in main_ids or area_id in seen_areas
                    or area.get("areaGroupId") != group["id"]):
                raise RuntimeError("Quest area does not belong to its bundled main group")
            seen_areas.add(area_id)
            quest_ids = area.get("questIds")
            if not quest_ids or [quest.questId for quest in output_area.quests] != quest_ids:
                raise RuntimeError("Quest identities/order do not match bundled Area references")
            for output_quest in output_area.quests:
                quest_id = output_quest.questId
                if (quest_id in seen_quests or quest_id not in quests
                        or quests[quest_id].get("areaId") != area_id):
                    raise RuntimeError("Quest does not belong to its bundled main area")
                if output_quest.campaignDropRewardIds:
                    raise RuntimeError("Local quest catalog advertised an unsupported campaign")
                seen_quests.add(quest_id)
            if area_id in tutorial_ids and (not output_area.unlocked
                    or not all(quest.isPlayable for quest in output_area.quests)):
                raise RuntimeError("Pending tutorial full/short alternatives must be available")
    if not normal_ids or seen_areas != main_ids or not seen_quests:
        raise RuntimeError("Quest responses did not cover the bundled main catalog")
    contest_rows = [row for row in areas.values() if row.get("type") == 2]
    if len(contest_rows) != 1 or contest_rows[0]["id"] != "area-contest-001":
        raise RuntimeError("Quest.Top needs the real type-2 contest area")
    contest = contest_rows[0]
    contest_ids = contest.get("questIds")
    if (not isinstance(contest_ids, list) or len(contest_ids) != 23 or len(set(contest_ids)) != 23
            or any(key not in quests or quests[key].get("areaId") != contest["id"] for key in contest_ids)):
        raise RuntimeError("Bundled contest area must reference its 23 real quests")
    if (not top.HasField("contestArea") or top.contestArea.areaId != contest["id"]
            or [quest.questId for quest in top.contestArea.quests] != contest_ids
            or top.contestArea.unlocked
            or any(quest.isPlayable or quest.playableCount or quest.campaignDropRewardIds for quest in top.contestArea.quests)):
        raise RuntimeError("Quest.Top contest catalog must be complete, locked, unplayable and campaign-free")
    first_area = next(area for group in top.mainAreaGroups for area in group.areas if area.areaId in normal_ids)
    first_quest = first_area.quests[0]
    if not first_area.unlocked or not first_quest.isPlayable or first_quest.cleared:
        raise RuntimeError("Fresh starter's first main quest must be playable and uncleared")
    return first_quest.questId



def _main_live_database(data_dir, schema, receipt, expected_clock, expected_attempts=None):
    from idoly_local.main_live_qa import assert_main_live_attempt_rows, assert_main_live_snapshot
    with sqlite3.connect(Path(data_dir) / "state.db") as db:
        db.row_factory = sqlite3.Row
        snapshot = db.execute("SELECT response,schema_sha256 FROM snapshots WHERE profile='sandbox'").fetchone()
        clock = db.execute("SELECT response,schema_sha256 FROM profile_lesson_progress WHERE profile='sandbox'").fetchone()
        rows = db.execute("SELECT * FROM main_live_attempts WHERE profile='sandbox' ORDER BY request_id").fetchall()
        if (snapshot is None or snapshot[1] != schema.fingerprint or clock is None
                or tuple(clock) != expected_clock):
            raise RuntimeError("Main-live snapshot/schema or raw lesson clock was not preserved")
        assert_main_live_snapshot(schema, snapshot[0], receipt)
        assert_main_live_attempt_rows(schema, rows, receipt)
        attempts = tuple(tuple(row) for row in rows)
        if expected_attempts is not None and attempts != expected_attempts:
            raise RuntimeError("Cached main-live seeds, timestamps or exact responses changed")
        return attempts



def _account_roundtrip_reference(data_dir, schema, original_token):
    """Exercise portable account state and real encrypted RPCs on owned smoke data."""
    from copy import deepcopy
    from idoly_local import app_runtime
    from idoly_local.account_manager import account_command, selected_profile
    from idoly_local.state import State

    root = Path(data_dir)
    state = State(root / "state.db")
    media_state = State(root / "media-state.db")
    # Explicit QA-only local progress proves the eighth table's JSON bytes,
    # whitespace and context survive clone/export/import/replace/restore.
    love_id, love_ruleset = "love-23-0514", "d" * 64
    love_fixture = json.dumps({"schema": 1, "love_id": love_id, "player_name": "QA",
        "registered_ms": 1, "exp": 0, "lesson_anchor_ms": 1, "last_play_ms": 1,
        "path": ["love-event-story-love-23-0514-001"], "choices": {}, "past_choices": {},
        "current": None, "saves": [], "promotion_day": "2026-11-16", "promotion_used": 0},
        ensure_ascii=False, sort_keys=True, indent=1).encode("utf-8") + b"\n"
    state.mutate_love_snapshot("sandbox", schema.fingerprint, love_id, love_ruleset,
                              lambda original, previous: (original, love_fixture))
    original = state.account_snapshot("sandbox")
    if original is None:
        raise RuntimeError("Account smoke needs the seeded original profile")
    original_bundle, original_revision = original
    tables = ["profiles", "snapshots", "profile_settings", "starter_profiles",
              "profile_lesson_progress", "preference_receipts", "main_live_attempts", "profile_love_progress"]
    if (original_bundle["schema"] != 2 or len(original_bundle["tables"]["profile_love_progress"]) != 1
            or original_bundle["tables"]["profile_love_progress"][0]["response"] != love_fixture):
        raise RuntimeError("Account smoke must seed exact Love JSON bytes in the schema-2 eighth table")
    if set(original_bundle["tables"]) != set(tables):
        raise RuntimeError("Account smoke table inventory differs")
    def normalized(bundle):
        value = deepcopy(bundle)
        value["profile"] = "normalized"
        for table, rows in value["tables"].items():
            for row in rows:
                row["name" if table == "profiles" else "profile"] = "normalized"
        return State.account_bytes(value)
    def sessions(profile):
        with state.connect() as db:
            return [tuple(row) for row in db.execute(
                "SELECT token_hash,profile,expires_at FROM sessions WHERE profile=? ORDER BY token_hash",
                (profile,))]
    def invoke(action, payload):
        result = account_command(root, action, payload)
        if type(result) is not dict or result.get("ok") is not True or result.get("action") != action:
            raise RuntimeError("Account smoke command response differs")
        return result

    source_sessions = sessions("sandbox")
    nonce = uuid.uuid4().hex[:12]
    created_name, media_name = "smoke-new-" + nonce, "smoke-media-" + nonce
    copy_name, restored_name = "smoke-copy-" + nonce, "smoke-import-" + nonce
    checks = {}
    invoke("accounts_create", {"mode": "normal", "profile": created_name, "manager_name": "MacQA"})
    invoke("accounts_create", {"mode": "media", "profile": media_name, "manager_name": "MediaQA"})
    checks["normal_account_created"] = (state.snapshot(created_name) is not None
        and state.account_snapshot(created_name)[0]["tables"]["profile_love_progress"] == [])
    checks["media_account_created"] = (media_state.snapshot(media_name) is not None
        and media_state.account_snapshot(media_name)[0]["tables"]["profile_love_progress"] == [])
    checks["mode_isolation"] = state.snapshot(media_name) is None and media_state.snapshot(created_name) is None
    invoke("accounts_clone", {"mode": "normal", "source_profile": "sandbox", "profile": copy_name,
                             "expected_revision": original_revision})
    copied = state.account_snapshot(copy_name)
    checks["clone_all_tables_preserved"] = copied is not None and normalized(copied[0]) == normalized(original_bundle)

    archive = invoke("accounts_export", {"mode": "normal", "profile": copy_name,
                                        "expected_revision": copied[1]})
    destination = root / ("smoke-account-" + nonce + ".zip")
    _account_export_copy(root, archive, str(destination), lambda received, total: None)
    with destination.open("rb") as stream:
        copied_sha = hashlib.file_digest(stream, "sha256").hexdigest()
    checks["archive_full_sha256_verified"] = (
        destination.stat().st_size == archive["bytes"] and copied_sha == archive["sha256"])
    preview = invoke("accounts_preview", {"path": str(destination)})
    invoke("accounts_import", {"token": preview["token"], "mode": "normal", "profile": restored_name,
                              "replace": False, "expected_revision": None})
    imported = state.account_snapshot(restored_name)
    checks["new_import_all_tables_preserved"] = imported is not None and normalized(imported[0]) == normalized(original_bundle)
    checks["new_import_has_no_sessions"] = sessions(restored_name) == []

    invoke("accounts_select", {"mode": "normal", "profile": copy_name, "expected_revision": copied[1]})
    runtime = app_runtime.start(root, grpc_port=0, asset_port=0, resource_platform="ios")
    try:
        checks["queued_selection_applied_after_restart"] = (
            selected_profile(root, False, "sandbox") == copy_name
            and runtime.profile == copy_name and runtime.status()["profile"] == copy_name)
        address = runtime.status()["grpc_address"]
        check = _rpc(address, schema, "/api.System/Check")
        login = _rpc(address, schema, "/api.Auth/Login")
        user = _rpc(address, schema, "/api.User/Get", token=login.gameAuthToken)
        original_user = schema.response_type("/api.User/Get").FromString(state.snapshot(copy_name)[0])
        rejected = _rpc(address, schema, "/api.User/Get", token=original_token, expected_status="16")
        checks["selected_account_encrypted_rpc"] = (
            check.keepAliveTimeMilliseconds > 0 and bool(login.gameAuthToken)
            and user.user.name == original_user.user.name and rejected is None)
    finally:
        runtime.stop()
    current_original = state.account_snapshot("sandbox")
    invoke("accounts_select", {"mode": "normal", "profile": "sandbox",
                              "expected_revision": current_original[1]})
    checks["selected_original_restored"] = selected_profile(root, False, "sandbox") == "sandbox"

    target_token, _ = state.login(restored_name)
    before_canary = state.account_snapshot(restored_name)
    response_type = schema.response_type("/api.User/Get")
    def canary(raw):
        response = response_type.FromString(raw)
        response.user.name = "Mac restore QA"
        # A real unknown top-level protobuf field must survive backup and restore.
        return response.SerializeToString() + b"\xf8\x7f\x01"
    state.mutate_snapshot(restored_name, schema.fingerprint, canary)
    state.mutate_love_snapshot(restored_name, schema.fingerprint, love_id, love_ruleset,
        lambda user, previous: (user, love_fixture.replace(b'"QA"', b'"Mac restore QA"')))
    saved_canary, canary_revision = state.account_snapshot(restored_name)
    canary_snapshot = state.snapshot(restored_name)[0]
    stale_preview = invoke("accounts_preview", {"path": str(destination)})
    try:
        invoke("accounts_import", {"token": stale_preview["token"], "mode": "normal",
            "profile": restored_name, "replace": True, "expected_revision": before_canary[1]})
    except ValueError as error:
        checks["stale_replace_rejected"] = (
            str(error) == "account_revision_conflict"
            and state.account_snapshot(restored_name)[1] == canary_revision)
    else:
        checks["stale_replace_rejected"] = False
    replacement_preview = invoke("accounts_preview", {"path": str(destination)})
    replacement = invoke("accounts_import", {"token": replacement_preview["token"], "mode": "normal",
        "profile": restored_name, "replace": True, "expected_revision": canary_revision})
    points = [row for row in replacement["status"]["restore_points"]
              if row["mode"] == "normal" and row["profile"] == restored_name
              and row["revision"] == canary_revision]
    checks["replacement_restore_point_created"] = len(points) == 1
    checks["replacement_target_sessions_invalidated"] = not state.authenticated(target_token, restored_name)
    if not points:
        raise RuntimeError("Account smoke automatic restore point missing")
    invoke("accounts_restore", {"id": points[0]["id"], "mode": "normal", "profile": restored_name,
                               "expected_revision": state.account_snapshot(restored_name)[1]})
    checks["restore_exact_snapshot_and_unknown_fields"] = (
        state.account_snapshot(restored_name)[0] == saved_canary
        and state.snapshot(restored_name)[0] == canary_snapshot
        and state.snapshot(restored_name)[0].endswith(b"\xf8\x7f\x01"))
    checks["original_account_all_tables_preserved"] = state.account_snapshot("sandbox") == original
    checks["original_sessions_preserved"] = sessions("sandbox") == source_sessions
    if not all(type(value) is bool and value is True for value in checks.values()):
        raise RuntimeError("Account management roundtrip failed")
    return {"schema": 1, "snapshot_tables": tables, "archive_bytes": archive["bytes"],
            "archive_sha256": copied_sha, "checks": checks, "gameplay_tested": False}


def smoke(data_dir, server_data, report_path, live_engine_library=None):
    from http.client import HTTPConnection
    from urllib.parse import quote, urlsplit
    from idoly_local import app_runtime
    from idoly_local.schema import Schema
    from idoly_local.state import State

    install_payload(server_data, data_dir)
    runtime = app_runtime.start(data_dir, grpc_port=0, asset_port=0)
    if live_engine_library is None and getattr(sys, "frozen", False):
        candidate = Path(sys._MEIPASS) / "libidoly_live.dylib"
        if candidate.is_file():
            live_engine_library = candidate
    report = {"frozen_runtime": bool(getattr(sys, "frozen", False)), "server_started": False,
              "encrypted_system_check": False, "anonymous_refund_term": False, "anonymous_public_text": False,
              "local_auth": False, "home_login": False, "home_enter": False,
              "home_hierarchy_reference": False, "home_fish_heaven_absent": False,
              "starter_roster_complete": False, "home_positions_distinct": False,
              "story_catalog_event": False, "story_catalog_extra": False,
              "story_catalog_home_consistent": False, "story_catalog_readonly": False,
              "quest_top_list_main": False, "quest_catalog_readonly": False,
              "quest_contest_area_locked": False, "quest_tutorial_context": False,
              "quest_list_asset": False, "quest_list_asset_tutorial_full": False,
              "quest_list_asset_tutorial_short": False, "quest_list_asset_ordinary_buddy_name": False,
              "quest_list_asset_rental_rejected": False, "quest_list_asset_readonly": False,
              "tutorial_replay_short": False, "tutorial_replay_full": False,
              "tutorial_replay_canonical": False, "tutorial_replay_master_references": False,
              "tutorial_replay_readonly": False, "tutorial_replay_assets_covered": False,
              "initial_inventory_master_backed": False, "default_unit_complete": False,
              "initial_inventory_readonly": False, "starter_inventory_persisted": False,
              "tutorial_continuation_persisted": False, "tutorial_continuation_identity_preserved": False,
              "tutorial_continuation_sessions_preserved": False, "tutorial_continuation_settings_preserved": False,
              "ordinary_lesson_persisted": False, "ordinary_lesson_clock_persisted": False,
              "ordinary_lesson_resources_persisted": False, "ordinary_lesson_identity_preserved": False,
              "ordinary_lesson_sessions_preserved": False, "ordinary_lesson_settings_preserved": False,
              "story_read_persisted": False, "story_read_clock_persisted": False,
              "story_read_resources_preserved": False, "story_read_identity_preserved": False,
              "story_read_sessions_preserved": False, "story_read_settings_preserved": False,
              "story_read_restart_no_grant": False,
              "appearance_persisted": False, "appearance_clock_preserved": False,
              "appearance_resources_preserved": False, "appearance_identity_preserved": False,
              "appearance_sessions_preserved": False, "appearance_settings_preserved": False,
              "appearance_restart_no_change": False,
              "settings_persisted": False, "profile_persisted": False,
              "asset_range": False, "server_stopped": False, "game_client_tested": False}
    engine_label = "macOS frozen" if report["frozen_runtime"] else "source engine"
    try:
        status = runtime.status()
        report["server_started"] = bool(status["running"])
        schema = Schema.from_descriptor_set(Path(data_dir) / "protocol/idolypride-6.1.1.pb")
        address = status["grpc_address"]
        check = _rpc(address, schema, "/api.System/Check")
        report["encrypted_system_check"] = check.keepAliveTimeMilliseconds > 0
        refund = _rpc(address, schema, "/api.Refund/GetTerm")
        report["anonymous_refund_term"] = (
            refund.endDatetime, refund.startDatetime, refund.shopInvalidStartDatetime
        ) == (4102444800000, 4102444800000, 0)
        if not report["anonymous_refund_term"]:
            raise RuntimeError("Local refund period must be inactive and the unsupported financial shop closed")
        # These title-screen calls must succeed before any local Auth.Login.
        rule_request = schema.request_type("/api.Master/Rule")(ruleType=1)
        rule = _rpc(address, schema, "/api.Master/Rule", rule_request)
        help_request = schema.request_type("/api.Master/GetHelpCategory")(helpType=1)
        help_response = _rpc(address, schema, "/api.Master/GetHelpCategory", help_request)
        report["anonymous_public_text"] = bool(rule.text and help_response.helpCategories)
        login = _rpc(address, schema, "/api.Auth/Login")
        token = login.gameAuthToken
        if not token:
            raise RuntimeError("Local Auth.Login did not issue a local session")
        report["local_auth"] = True
        before = _rpc(address, schema, "/api.User/Get", token=token)
        # HomeOfficeActors selects from the master's unlocked normal roster,
        # then requires a matching UserCharacter with owned favorite/live
        # appearances. Checking the actual RPC catches the former five-row
        # seed even if initialization and Home.Enter themselves succeed.
        required_characters = {"char-ai", "char-aoi", "char-chs", "char-hrk", "char-kkr", "char-ktn",
            "char-mei", "char-ngs", "char-rei", "char-rio", "char-rui", "char-ski", "char-skr",
            "char-smr", "char-suz", "char-szk", "char-yu"}
        characters = {row.characterId: row for row in before.characters}
        costumes = {row.costumeId for row in before.costumes if row.costumeId}
        hairs = {row.hairId for row in before.hairs if row.hairId}
        report["starter_roster_complete"] = required_characters.issubset(characters) and all(
            characters[key].favoriteCostumeId in costumes and characters[key].liveCostumeId in costumes
            and characters[key].favoriteHairId in hairs and characters[key].liveHairId in hairs
            for key in required_characters)
        if not report["starter_roster_complete"]:
            raise RuntimeError("User.Get must contain all 17 starter characters and their owned favorite/live appearances")
        report["home_positions_distinct"] = _home_positions_distinct(before)
        if not report["home_positions_distinct"]:
            raise RuntimeError("User.Get must assign four distinct owned home characters and preserve Home1 char-ktn")
        report.update(_initial_inventory_reference(before, data_dir))
        report["initial_inventory_master_backed"] = report["default_unit_complete"] = True
        from idoly_local.story_qa import run_story_catalog_checks
        story_database_before = _whole_database_state(data_dir)
        report.update(run_story_catalog_checks(schema,
            lambda path, request: _rpc(address, schema, path, request, token), Path(data_dir) / "master-json"))
        if _whole_database_state(data_dir) != story_database_before:
            raise RuntimeError("Read-only story catalogs changed the whole local database")
        saved_before_quests = State(Path(data_dir) / "state.db").snapshot("sandbox")
        top = _rpc(address, schema, "/api.Quest/Top", token=token)
        main = _rpc(address, schema, "/api.Quest/ListMain", token=token)
        report["quest_catalog_first_quest"] = _quest_catalog_reference(top, main, data_dir, before)
        report["quest_catalog_group_count"] = len(top.mainAreaGroups)
        report["quest_catalog_area_count"] = sum(len(group.areas) for group in top.mainAreaGroups)
        report["quest_catalog_quest_count"] = sum(len(area.quests) for group in top.mainAreaGroups for area in group.areas)
        report["quest_contest_quest_count"] = len(top.contestArea.quests)
        report["quest_tutorial_pending"] = _quest_tutorial_pending(before)
        report["quest_contest_area_locked"] = report["quest_tutorial_context"] = True
        report["quest_top_list_main"] = True
        after_quests = _rpc(address, schema, "/api.User/Get", token=token)
        report["quest_catalog_readonly"] = (
            State(Path(data_dir) / "state.db").snapshot("sandbox") == saved_before_quests
            and after_quests.SerializeToString() == before.SerializeToString())
        if not report["quest_catalog_readonly"]:
            raise RuntimeError("Read-only Quest.Top/ListMain changed the local snapshot")
        report["initial_inventory_readonly"] = True
        saved_before_assets = State(Path(data_dir) / "state.db").snapshot("sandbox")
        whole_before_replays = _whole_database_state(data_dir)
        deck = next(row for row in before.decks if row.number == 1)
        if not deck.name:
            raise RuntimeError("Live asset smoke needs the saved ordinary nonempty deck name")
        for quest_id, flag in (("qt-tutorial-full", "quest_list_asset_tutorial_full"),
                               ("qt-tutorial-short", "quest_list_asset_tutorial_short"),
                               (report["quest_catalog_first_quest"], "quest_list_asset_ordinary_buddy_name")):
            request = schema.request_type("/api.Quest/ListAsset")(
                questId=quest_id, deckNumber=1, buddyDeckName=deck.name)
            assets = _rpc(address, schema, "/api.Quest/ListAsset", request, token)
            kind = quest_id.removeprefix("qt-tutorial-") if quest_id.startswith("qt-tutorial-") else None
            canonical = _tutorial_fixture(schema.response_type("/api.Tutorial/StartQuest"), data_dir, kind) if kind else None
            count = _quest_list_asset_reference(assets, before, data_dir, canonical)
            report["quest_list_asset_tutorial_" + kind + "_count" if kind else "quest_list_asset_count"] = count
            report[flag] = True
        if (report["quest_list_asset_tutorial_short_count"], report["quest_list_asset_tutorial_full_count"]) != (8, 9):
            raise RuntimeError("Tutorial ListAsset did not include the selected unit plus the six recorded appearances")
        report["tutorial_replay_assets_covered"] = True
        rental = schema.request_type("/api.Quest/ListAsset")(
            questId=report["quest_catalog_first_quest"], deckNumber=1, buddyDeckName=deck.name)
        position = next(row for row in before.deckPositions if row.number == 1 and row.position == 1)
        rental.userBuddyDeckPositions.add(position=1, cardId=position.cardId,
            costumeId=position.costumeId, hairId=position.hairId, buddyUserId="unsupported-local-rental")
        _rpc(address, schema, "/api.Quest/ListAsset", rental, token, expected_status="12")
        report["quest_list_asset_rental_rejected"] = True
        settings = json.loads((Path(data_dir) / "master-json/Setting.json").read_text())
        if len(settings) != 1:
            raise RuntimeError("Tutorial replay smoke needs the single public Setting row")
        for kind in ("short", "full"):
            request = schema.request_type("/api.Tutorial/StartQuest")(
                questId=settings[0]["tutorial" + kind.capitalize() + "QuestId"])
            replay = _rpc(address, schema, "/api.Tutorial/StartQuest", request, token)
            report.update(_tutorial_replay_reference(replay, before, data_dir, kind))
            report["tutorial_replay_" + kind] = True
        report["tutorial_replay_canonical"] = report["tutorial_replay_master_references"] = True
        after_assets = _rpc(address, schema, "/api.User/Get", token=token)
        report["quest_list_asset_readonly"] = (
            State(Path(data_dir) / "state.db").snapshot("sandbox") == saved_before_assets
            and after_assets.SerializeToString(deterministic=True) == before.SerializeToString(deterministic=True))
        report["tutorial_replay_readonly"] = report["quest_list_asset_readonly"] and (
            _whole_database_state(data_dir) == whole_before_replays)
        if not report["tutorial_replay_readonly"]:
            raise RuntimeError("Tutorial/asset replay requests changed the local snapshot or another database table")
        report["quest_list_asset"] = True
        home_request = schema.request_type("/api.Home/Login")()
        home_request.settingInfo.soundBgm = 37
        home_request.settingInfo.soundEffect = 29
        home_request.settingInfo.soundVoice = 61
        home_request.settingInfo.frameRate = 30
        home_request.settingInfo.nightMode = True
        expected_settings = home_request.settingInfo.SerializeToString()
        home_login = _rpc(address, schema, "/api.Home/Login", home_request, token)
        report["home_login"] = home_login.HasField("commonResponse")
        home = _rpc(address, schema, "/api.Home/Enter", token=token)
        report["home_enter"] = bool(home.currentMainAreaId and home.HasField("lessonProgress"))
        report["home_fish_heaven_absent"] = not home.HasField("homeFishHeavenInfo")
        if not report["home_fish_heaven_absent"]:
            raise RuntimeError("Home.Enter advertised an inactive fish-heaven event and may suppress LoadingManager.Hide")
        report["home_hierarchy_reference"] = _home_hierarchy_reference(home, data_dir)
        if not report["home_hierarchy_reference"]:
            raise RuntimeError("Home.Enter hierarchy grade does not resolve through the bundled master tables")
        _rpc(address, schema, "/api.Home/SetReview", token=token)
        changed = _rpc(address, schema, "/api.User/Get", token=token)
        if changed.user.name != before.user.name or not changed.user.isReviewed or changed.user.lastLoginTime <= 0:
            raise RuntimeError("Home calls did not preserve and update the local user")
        # All canonical replay and whole-database read-only assertions above
        # have completed before the following intentional gameplay mutations.
        from idoly_local.tutorial_qa import (assert_tutorial_continuation_snapshot,
                                           run_tutorial_continuation)
        preserved = _preserved_database_state(data_dir)
        continuation = run_tutorial_continuation(schema,
            lambda path, request: _rpc(address, schema, path, request, token),
            Path(data_dir) / "master-json", label=engine_label)
        report["tutorial_continuation"] = continuation
        changed = _rpc(address, schema, "/api.User/Get", token=token)
        saved_user = changed.SerializeToString()
        tag = json.loads((Path(data_dir) / "original-master/master-tag.json").read_text())
        filename = tag["masterTagPacks"][0]["fileName"]
        expected = (Path(data_dir) / "original-master/assets/master" / filename).read_bytes()[:64]
        url = urlsplit(status["asset_url"])
        connection = HTTPConnection(url.hostname, url.port, timeout=5)
        try:
            connection.request("GET", "/master/" + quote(filename, safe=""), headers={"Range": "bytes=0-63"})
            result = connection.getresponse()
            report["asset_range"] = result.status == 206 and result.read() == expected
        finally:
            connection.close()
        runtime.stop()
        # Reopen both listeners and SQLite state, then reuse the previous local
        # session to prove mutations survived a fresh runtime instance.
        runtime = app_runtime.start(data_dir, grpc_port=0, asset_port=0)
        restored = _rpc(runtime.status()["grpc_address"], schema, "/api.User/Get", token=token)
        assert_tutorial_continuation_snapshot(schema, restored, continuation)
        if _preserved_database_state(data_dir) != preserved:
            raise RuntimeError("Tutorial continuation changed identity, sessions, settings or the starter marker")
        report.update(tutorial_continuation_persisted=True, tutorial_continuation_identity_preserved=True,
                      tutorial_continuation_sessions_preserved=True, tutorial_continuation_settings_preserved=True)
        report["profile_persisted"] = restored.SerializeToString() == saved_user
        report["starter_inventory_persisted"] = report["profile_persisted"]
        settings = State(Path(data_dir) / "state.db").settings("sandbox")
        report["settings_persisted"] = settings == (expected_settings, schema.fingerprint)
        # The tutorial receipt above is checked before this separate mutation;
        # its snapshot hash must never be reused after claiming ordinary XP.
        from idoly_local.lesson_qa import (assert_ordinary_lesson_home, assert_ordinary_lesson_progress,
                                         assert_ordinary_lesson_snapshot, run_ordinary_lesson_claim)
        ordinary = run_ordinary_lesson_claim(schema,
            lambda path, request: _rpc(runtime.status()["grpc_address"], schema, path, request, token),
            Path(data_dir) / "master-json", label=engine_label)
        report["ordinary_lesson"] = ordinary
        runtime.stop()
        runtime = app_runtime.start(data_dir, grpc_port=0, asset_port=0)
        address = runtime.status()["grpc_address"]
        assert_ordinary_lesson_snapshot(schema, _rpc(address, schema, "/api.User/Get", token=token), ordinary)
        lesson = State(Path(data_dir) / "state.db").lesson_progress("sandbox")
        if lesson is None or lesson[1] != schema.fingerprint:
            raise RuntimeError("Ordinary lesson clock/schema did not survive a fresh runtime")
        assert_ordinary_lesson_progress(schema, lesson[0], ordinary)
        assert_ordinary_lesson_home(schema, _rpc(address, schema, "/api.Home/Enter", token=token), ordinary)
        assert_ordinary_lesson_snapshot(schema, _rpc(address, schema, "/api.User/Get", token=token), ordinary)
        if State(Path(data_dir) / "state.db").lesson_progress("sandbox") != lesson:
            raise RuntimeError("Post-restart Home.Enter changed the stored ordinary lesson clock")
        if _preserved_database_state(data_dir) != preserved:
            raise RuntimeError("Ordinary lesson claim changed identity, sessions, settings or the starter marker")
        report.update(ordinary_lesson_persisted=True, ordinary_lesson_clock_persisted=True,
                      ordinary_lesson_resources_persisted=True, ordinary_lesson_identity_preserved=True,
                      ordinary_lesson_sessions_preserved=True, ordinary_lesson_settings_preserved=True)
        # Ordinary lesson's receipt has been checked above. Story reads create
        # a new snapshot receipt; never compare that mutated state to old hashes.
        from idoly_local.story_read_qa import (assert_story_read_progress, assert_story_read_retries,
                                              run_story_read_checks)
        story_read = run_story_read_checks(schema,
            lambda path, request: _rpc(address, schema, path, request, token),
            Path(data_dir) / "master-json", label=engine_label)
        report["story_read"] = story_read
        if State(Path(data_dir) / "state.db").lesson_progress("sandbox") != lesson:
            raise RuntimeError("Story reads changed the raw persistent lesson clock")
        runtime.stop()
        runtime = app_runtime.start(data_dir, grpc_port=0, asset_port=0)
        address = runtime.status()["grpc_address"]
        assert_story_read_retries(schema,
            lambda path, request: _rpc(address, schema, path, request, token),
            Path(data_dir) / "master-json", story_read)
        stored_lesson = State(Path(data_dir) / "state.db").lesson_progress("sandbox")
        if stored_lesson != lesson:
            raise RuntimeError("Story read restart or repeated requests changed the raw lesson clock")
        assert_story_read_progress(schema, stored_lesson[0], story_read)
        if _preserved_database_state(data_dir) != preserved:
            raise RuntimeError("Story reads changed identity, sessions, settings or the starter marker")
        report.update(story_read_persisted=True, story_read_clock_persisted=True,
                      story_read_resources_preserved=True, story_read_identity_preserved=True,
                      story_read_sessions_preserved=True, story_read_settings_preserved=True,
                      story_read_restart_no_grant=True)
        from idoly_local.appearance_qa import assert_appearance_retries, run_appearance_checks
        appearance = run_appearance_checks(schema,
            lambda path, request: _rpc(address, schema, path, request, token),
            Path(data_dir) / "master-json", label=engine_label)
        report["appearance"] = appearance
        if State(Path(data_dir) / "state.db").lesson_progress("sandbox") != lesson:
            raise RuntimeError("Appearance requests changed the raw persistent lesson clock")
        runtime.stop()
        runtime = app_runtime.start(data_dir, grpc_port=0, asset_port=0)
        address = runtime.status()["grpc_address"]
        assert_appearance_retries(schema,
            lambda path, request: _rpc(address, schema, path, request, token),
            Path(data_dir) / "master-json", appearance)
        if State(Path(data_dir) / "state.db").lesson_progress("sandbox") != lesson:
            raise RuntimeError("Appearance restart or retries changed the raw lesson clock")
        if _preserved_database_state(data_dir) != preserved:
            raise RuntimeError("Appearance requests changed identity, sessions, settings or the starter marker")
        report.update(appearance_persisted=True, appearance_clock_preserved=True,
                      appearance_resources_preserved=True, appearance_identity_preserved=True,
                      appearance_sessions_preserved=True, appearance_settings_preserved=True,
                      appearance_restart_no_change=True)
        report["main_live_included"] = live_engine_library is not None
        if live_engine_library is not None:
            from idoly_local.main_live_qa import assert_main_live_retries, run_main_live_checks
            disabled_before = _rpc(address, schema, "/api.User/Get", token=token).SerializeToString(deterministic=True)
            request = schema.request_type("/api.Quest/Start")(questId="qt-main-1-001-01", deckNumber=1, playCount=1)
            _rpc(address, schema, "/api.Quest/Start", request, token,
                 expected_status="12", request_id="9000000000000000300", timeout=60)
            if _rpc(address, schema, "/api.User/Get", token=token).SerializeToString(deterministic=True) != disabled_before:
                raise RuntimeError("Disabled experimental main live changed the snapshot")
            runtime.stop()
            runtime = app_runtime.start(data_dir, grpc_port=0, asset_port=0,
                experimental_main_live=True, live_engine_library=live_engine_library)
            address = runtime.status()["grpc_address"]
            if runtime.status().get("experimental_main_live") is not True:
                raise RuntimeError("Native main live did not enable the explicit opt-in setting")
            invoke = lambda path, request, identity: _rpc(address, schema, path, request, token,
                                                         request_id=identity, timeout=60)
            main_live = run_main_live_checks(schema, invoke, Path(data_dir) / "master-json", label=engine_label)
            report["main_live"] = main_live
            runtime.stop()
            attempts = _main_live_database(data_dir, schema, main_live, lesson)
            runtime = app_runtime.start(data_dir, grpc_port=0, asset_port=0,
                experimental_main_live=True, live_engine_library=live_engine_library)
            address = runtime.status()["grpc_address"]
            assert_main_live_retries(schema, invoke, Path(data_dir) / "master-json", main_live)
            _main_live_database(data_dir, schema, main_live, lesson, attempts)
            if _preserved_database_state(data_dir) != preserved:
                raise RuntimeError("Main live changed identity, sessions, settings or the starter marker")
            report.update(main_live_first_quest=True, main_live_mode_default_off=True, main_live_opt_in=True,
                          main_live_persisted=True, main_live_attempts_persisted=True, main_live_clock_preserved=True,
                          main_live_identity_preserved=True, main_live_sessions_preserved=True,
                          main_live_settings_preserved=True, main_live_cached_no_grant=True)
    finally:
        runtime.stop()
        report["server_stopped"] = runtime.status()["running"] is False
    report["account_management"] = _account_roundtrip_reference(data_dir, schema, token)
    report["account_management_roundtrip"] = all(report["account_management"]["checks"].values())
    report_path = Path(report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    required = ("server_started", "encrypted_system_check", "anonymous_refund_term", "anonymous_public_text", "local_auth", "home_login",
                "home_enter", "home_hierarchy_reference", "home_fish_heaven_absent", "starter_roster_complete", "home_positions_distinct",
                "story_catalog_event", "story_catalog_extra", "story_catalog_home_consistent", "story_catalog_readonly",
                "quest_top_list_main", "quest_catalog_readonly", "quest_contest_area_locked", "quest_tutorial_context",
                "quest_list_asset", "quest_list_asset_tutorial_full", "quest_list_asset_tutorial_short",
                "quest_list_asset_ordinary_buddy_name", "quest_list_asset_rental_rejected", "quest_list_asset_readonly",
                "tutorial_replay_short", "tutorial_replay_full", "tutorial_replay_canonical",
                "tutorial_replay_master_references", "tutorial_replay_readonly", "tutorial_replay_assets_covered",
                "initial_inventory_master_backed", "default_unit_complete", "initial_inventory_readonly", "starter_inventory_persisted",
                "tutorial_continuation_persisted", "tutorial_continuation_identity_preserved",
                "tutorial_continuation_sessions_preserved", "tutorial_continuation_settings_preserved",
                "ordinary_lesson_persisted", "ordinary_lesson_clock_persisted", "ordinary_lesson_resources_persisted",
                "ordinary_lesson_identity_preserved", "ordinary_lesson_sessions_preserved", "ordinary_lesson_settings_preserved",
                "story_read_persisted", "story_read_clock_persisted", "story_read_resources_preserved",
                "story_read_identity_preserved", "story_read_sessions_preserved", "story_read_settings_preserved",
                "story_read_restart_no_grant",
                "appearance_persisted", "appearance_clock_preserved", "appearance_resources_preserved",
                "appearance_identity_preserved", "appearance_sessions_preserved", "appearance_settings_preserved",
                "appearance_restart_no_change",
                "settings_persisted", "profile_persisted", "asset_range", "server_stopped", "account_management_roundtrip")
    if report.get("main_live_included"):
        required += ("main_live_first_quest", "main_live_mode_default_off", "main_live_opt_in",
                     "main_live_persisted", "main_live_attempts_persisted", "main_live_clock_preserved",
                     "main_live_identity_preserved", "main_live_sessions_preserved", "main_live_settings_preserved",
                     "main_live_cached_no_grant")
    if not all(report[key] for key in required):
        raise RuntimeError("Bundled engine smoke check failed")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--server-data", required=True, type=Path)
    parser.add_argument("--json-control", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--live-engine-library", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    if args.smoke:
        if args.report is None:
            parser.error("--smoke requires --report")
        smoke(args.data_dir, args.server_data, args.report, args.live_engine_library)
        return 0
    controller = Controller(args.data_dir, args.server_data)

    def stop_signal(_signum, _frame):
        controller.close()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop_signal)
    signal.signal(signal.SIGINT, stop_signal)
    controller.status()
    try:
        for line in sys.stdin:
            try:
                command = json.loads(line)
                line = ""
            except (ValueError, TypeError):
                line = ""
                emit("error", message="앱 제어 요청을 읽지 못했습니다.")
                continue
            action = command.get("action") if isinstance(command, dict) else None
            if action == "start":
                experimental_live = command.get("experimental_main_live", False)
                if type(experimental_live) is not bool:
                    emit("error", message="실험 라이브 설정을 읽지 못했습니다.")
                    continue
                media_mode = command.get("media_mode", False)
                if type(media_mode) is not bool:
                    emit("error", message="감상용 설정을 읽지 못했습니다.")
                    continue
                download_missing = command.get("download_missing_resources", True)
                if type(download_missing) is not bool:
                    emit("error", message="게임 리소스 내려받기 설정을 읽지 못했습니다.")
                    continue
                resource_cache_dir = command.get("resource_cache_dir")
                if resource_cache_dir is not None and (not isinstance(resource_cache_dir, str)
                        or not 0 < len(resource_cache_dir) <= 4096 or "\0" in resource_cache_dir
                        or not Path(resource_cache_dir).is_absolute()):
                    emit("error", message="리소스 보관 폴더를 읽지 못했습니다.")
                    continue
                controller.start(experimental_live, media_mode, download_missing, resource_cache_dir)
            elif action == "stop":
                controller.stop()
            elif action == "status":
                controller.status()
            elif action in ("resources_preview", "resources_download", "resources_cancel",
                            "resources_export", "resources_import"):
                controller.resources(action, command)
            elif type(action) is str and action in _ACCOUNT_ACTIONS:
                controller.accounts(action, command)
            elif type(action) is str and action in _EVENT_ACTIONS:
                controller.events(action, command)
            elif type(action) is str and action in _OFFICIAL_ACTIONS:
                controller.official(action, command)
                command.clear()
            elif action == "quit":
                break
            else:
                emit("error", message="지원하지 않는 앱 제어 요청입니다.")
    finally:
        controller.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
