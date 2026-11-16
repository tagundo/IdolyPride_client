"""Native-only official-account inspection, preview and explicit local import.

Credentials and official sessions stay in one bounded RAM job. Only exact,
validated User.Get data enters ordinary account staging. No request, auth
response or metadata is written to a fixture, diagnostic, log or account ZIP.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from pathlib import Path
import re
import sqlite3
import threading
import time
import uuid

from .account_manager import AccountManager, AccountError, _read, _decode, _profile, _io_error
from .official_account import (OfficialAccountClient, OfficialAccountError,
                               ERROR_CODES as CLIENT_ERROR_CODES, STAGES as CLIENT_STAGES)

_TTL = 600
STAGES = frozenset((*CLIENT_STAGES, "idle", "fetching", "catalog_check", "staging", "ready",
                    "applying", "completed", "cancelled", "failed"))
_ACCOUNT_ERRORS = frozenset(("account_revision_conflict", "account_target_exists", "account_target_missing",
    "account_profile_invalid", "account_protocol_schema_differs", "account_restore_point_limit",
    "account_permission_denied", "account_insufficient_space", "account_storage_busy", "account_storage_io",
    "account_state_rejected", "account_storage_invalid", "account_file_unavailable", "account_file_invalid",
    "account_preview_changed", "account_preview_receipt_invalid", "account_import_token_invalid",
    "account_operation_failed", "account_identity_mismatch", "account_snapshot_required",
    "account_revision_required", "account_blob_invalid", "account_protobuf_invalid", "account_user_invalid",
    "account_temporary_storage_bound", "account_file_changed", "account_archive_invalid"))
_RETRYABLE_ACCOUNT_ERRORS = frozenset(("account_revision_conflict", "account_target_exists", "account_target_missing",
    "account_permission_denied", "account_insufficient_space", "account_storage_busy", "account_storage_io",
    "account_state_rejected", "account_restore_point_limit", "account_profile_invalid", "account_revision_required"))
WARNING_CODES = frozenset(("account_temporary_cleanup_pending", "account_status_refresh_required"))
ERROR_CODES = frozenset((*CLIENT_ERROR_CODES, *_ACCOUNT_ERRORS, "official_command_invalid", "official_job_missing",
    "official_job_mismatch", "official_job_busy", "official_invalid_state", "official_session_expired",
    "official_closed", "official_apply_in_progress", "official_operation_failed", "official_protocol_changed",
    "official_catalog_unavailable", "official_master_mismatch", "official_catalog_changed",
    "official_catalog_reference_missing", "official_snapshot_invalid"))


class OfficialImportError(ValueError):
    def __init__(self, code):
        self.code = code if code in ERROR_CODES else "official_operation_failed"
        super().__init__(self.code)


def _need(value, code):
    if not value: raise OfficialImportError(code)


def _error(error):
    try:
        code = error.code if isinstance(error, (OfficialImportError, OfficialAccountError)) else (
            str(_io_error(error)) if isinstance(error, (OSError, sqlite3.Error)) else
            str(error) if isinstance(error, ValueError) else None)
    except BaseException:
        code = None
    return code if type(code) is str and code in ERROR_CODES else "official_operation_failed"


def _close(value):
    try:
        if value is not None: value.close()
    except BaseException:
        pass


@dataclass(repr=False)
class _Job:
    job_id: str
    platform: str
    created_at: float
    expires_at: float
    state: str = "checking"
    progress: str = "preparing"
    busy: bool = True
    error_code: str | None = None
    cancel: object = field(default_factory=threading.Event, repr=False)
    verification: object = field(default=None, repr=False)
    client: object = field(default=None, repr=False)
    preview: dict | None = field(default=None, repr=False)
    counts: dict = field(default_factory=lambda: {"cards": 0, "items": 0, "photos": 0})
    schema_fingerprint: str | None = None
    catalog_pins: dict = field(default_factory=dict, repr=False)
    master_version: str | None = None
    stage_token: str | None = field(default=None, repr=False)
    operation: str = "inspect"
    timer: object = field(default=None, repr=False)
    timer_generation: int = 0
    expired: bool = False


class OfficialImportManager:
    def __init__(self, root, *, client_factory=None, accounts=None, now=None, timer_factory=None):
        self.root = Path(root).resolve()
        self.accounts = accounts if accounts is not None else AccountManager(self.root)
        self._factory = client_factory if client_factory is not None else OfficialAccountClient
        self._now = now if now is not None else time.time
        self._timer_factory = timer_factory if timer_factory is not None else threading.Timer
        self._lock, self._job, self._thread, self._closed = threading.RLock(), None, None, False

    def __repr__(self):
        return "<OfficialImportManager RAM-only official session; private preview omitted>"

    @staticmethod
    def _cancel_timer(job):
        timer, job.timer = job.timer, None
        job.timer_generation += 1
        if timer is not None: timer.cancel()

    def _schedule_expiry(self, job):
        self._cancel_timer(job)
        timer = self._timer_factory(max(0, job.expires_at-self._now()), self._timeout, args=(job, job.timer_generation))
        timer.daemon = True
        job.timer = timer
        timer.start()

    def _timeout(self, job, generation):
        # A daemon timer only releases RAM and expendable local copies. It never
        # authenticates, retries, refreshes, or interrupts an atomic local commit.
        with self._lock:
            if self._job is job and job.timer_generation == generation:
                job.expired = True
                self._expire(force=True)

    def _expire(self, *, force=False):
        job = self._job
        if job is None or (job.busy and job.operation == "apply"): return
        if job.state in ("checking", "verified", "fetching", "ready") and (force or job.expired or self._now() >= job.expires_at):
            self._cancel_timer(job)
            job.cancel.set(); _close(job.verification); job.verification = None
            job.state, job.progress, job.error_code = "failed", "failed", "official_session_expired"
            job.preview = None
            if not job.busy:
                _close(job.client); job.client = None
                self._drop_stage(job)

    def status(self, public=True):
        _need(type(public) is bool, "official_command_invalid")
        with self._lock:
            self._expire()
            job = self._job
            if job is None:
                return {"schema": 1, "state": "idle", "job_id": None, "progress": "idle", "error_code": None,
                        "counts": {"cards": 0, "items": 0, "photos": 0}, "busy": False, "expires_in_seconds": 0}
            result = {"schema": 1, "state": job.state, "job_id": job.job_id,
                      "progress": job.progress if job.progress in STAGES else job.state,
                      "error_code": job.error_code if job.error_code in ERROR_CODES else None,
                      "counts": dict(job.counts), "busy": bool(job.busy),
                      "expires_in_seconds": 0 if job.expired else max(0, min(_TTL, int(job.expires_at-self._now())))}
            if not public and job.preview is not None:
                result["preview"] = {**job.preview, "inventory": dict(job.counts)}
            return result

    def _current(self, job):
        return self._job is job and not self._closed and not job.cancel.is_set() and not job.expired and self._now() < job.expires_at

    def _progress(self, job, value):
        with self._lock:
            if self._current(job) and value in STAGES: job.progress = value

    def _drop_stage(self, job):
        token, job.stage_token = job.stage_token, None
        if token is not None:
            try: self.accounts.discard_preview_token(token)
            except BaseException: pass  # Expendable private copies also have bounded age/count cleanup.

    def _retire(self, job):
        if job is None: return
        self._cancel_timer(job)
        job.cancel.set(); _close(job.verification); job.verification = None
        if not job.busy:
            _close(job.client); job.client = None
            self._drop_stage(job)

    def _finish_failure(self, job, error):
        with self._lock:
            if self._job is job and job.state not in ("cancelled", "completed", "failed"):
                job.state, job.progress, job.error_code = "failed", "failed", _error(error)
                job.preview = None
            job.busy, job.client, job.verification = False, None, None
            self._cancel_timer(job)
        self._drop_stage(job)

    @staticmethod
    def _verified_preview(value):
        _need(type(value.public_id) is str and 0 < len(value.public_id) <= 256
              and type(value.manager_name) is str and 0 < len(value.manager_name.encode("utf-8")) <= 128
              and type(value.manager_level) is int and 1 <= value.manager_level <= 2147483647,
              "official_snapshot_invalid")
        return {"source": "official-jp", "mode": "normal", "public_id": value.public_id,
                "server_id": value.server_id, "manager_name": value.manager_name, "manager_level": value.manager_level}

    def _inspect(self, job, credentials):
        client, verification, keep = None, None, False
        try:
            schema = self.accounts._schema()
            client = self._factory(schema, platform=job.platform)
            with self._lock:
                _need(self._current(job), "official_session_expired")
                job.client, job.schema_fingerprint = client, schema.fingerprint
            verification = client.inspect(credentials["user_id"], credentials["password"], cancel=job.cancel,
                                          progress=lambda stage: self._progress(job, stage))
            credentials.clear()
            preview = self._verified_preview(verification)
            with self._lock:
                _need(self._current(job), "official_session_expired")
                job.expires_at = min(job.expires_at, float(verification.expires_at))
                _need(self._now() < job.expires_at, "official_session_expired")
                job.verification, job.preview = verification, preview
                self._schedule_expiry(job)
                job.state, job.progress, job.busy, keep = "verified", "verified", False, True
        except BaseException as error:
            _close(verification); _close(client)
            self._finish_failure(job, error)
        finally:
            credentials.clear()
            if not keep: _close(verification); _close(client)

    def _catalog_file(self, relative, pins, maximum=64*1024*1024):
        try: raw = _read(self.root/relative, maximum)
        except BaseException:
            raise OfficialImportError("official_catalog_unavailable") from None
        pins[relative] = hashlib.sha256(raw).hexdigest()
        return raw

    def _check_catalog(self, schema, collected):
        pins = {}
        try:
            tag = _decode(self._catalog_file("original-master/master-tag.json", pins, 16*1024*1024))
            version = self._catalog_file("master-json/!version.txt", pins, 4096).decode("utf-8").strip()
            master = schema.response_type("/api.Master/Get").FromString(collected.master_get)
            _need(type(tag) is dict and type(tag.get("version")) is str and bool(version), "official_catalog_unavailable")
            _need(master.masterTag.version == collected.master_version == tag["version"] == version, "official_master_mismatch")
            snapshot = schema.response_type("/api.User/Get").FromString(collected.user_get)
            _need(snapshot.HasField("user") and snapshot.HasField("userPublic")
                  and snapshot.userPublic.serverUserId == collected.server_id
                  and snapshot.userPublic.publicUserId == collected.public_id, "official_snapshot_invalid")
            relations = (("cards", "cardId", "Card"), ("characters", "characterId", "Character"),
                ("costumes", "costumeId", "Costume"), ("hairs", "hairId", "Hair"),
                ("items", "itemId", "Item"), ("accessories", "accessoryId", "Accessory"),
                ("musics", "musicId", "Music"), ("areas", "areaId", "Area"), ("quests", "questId", "Quest"))
            for collection, identity_field, table in relations:
                rows = getattr(snapshot, collection, ())
                if not rows: continue
                values = _decode(self._catalog_file("master-json/"+table+".json", pins))
                _need(type(values) is list and len(values) <= 200000 and all(type(row) is dict for row in values),
                      "official_catalog_unavailable")
                ids = {row.get("id") for row in values if type(row.get("id")) is str and row["id"]}
                _need(len(ids) == len(values), "official_catalog_unavailable")
                _need(all(getattr(row, identity_field) in ids for row in rows), "official_catalog_reference_missing")
            counts = {name: len(getattr(snapshot, name, ())) for name in ("cards", "items", "photos")}
            preview = {"source": "official-jp", "mode": "normal", "public_id": collected.public_id,
                       "server_id": collected.server_id, "manager_name": snapshot.user.name,
                       "manager_level": snapshot.user.managerLevel, "master_version": collected.master_version}
            return preview, counts, pins
        except OfficialImportError: raise
        except BaseException:
            raise OfficialImportError("official_catalog_unavailable") from None

    def _recheck_source(self, job):
        _need(self.accounts._schema().fingerprint == job.schema_fingerprint, "official_protocol_changed")
        try:
            for relative, expected in job.catalog_pins.items():
                _need(hashlib.sha256(_read(self.root/relative, 64*1024*1024)).hexdigest() == expected,
                      "official_catalog_changed")
        except OfficialImportError: raise
        except BaseException:
            raise OfficialImportError("official_catalog_changed") from None

    def _fetch(self, job):
        collected, staged = None, None
        try:
            client, verification = job.client, job.verification
            collected = client.fetch(verification, cancel=job.cancel, progress=lambda stage: self._progress(job, stage))
            _close(verification)
            with self._lock:
                job.verification = None
                _need(self._current(job), "official_session_expired")
            schema = self.accounts._schema()
            _need(schema.fingerprint == job.schema_fingerprint, "official_protocol_changed")
            self._progress(job, "catalog_check")
            preview, counts, pins = self._check_catalog(schema, collected)
            self._progress(job, "staging")
            staged = self.accounts.stage_snapshot(collected.user_get, server_id=collected.server_id,
                public_id=collected.public_id, schema_sha256=job.schema_fingerprint)
            _close(collected); collected = None
            _close(client)
            with self._lock:
                _need(self._current(job), "official_session_expired")
                job.stage_token = staged["token"]
                job.preview, job.counts, job.catalog_pins = preview, counts, pins
                job.master_version, job.client = preview["master_version"], None
                job.state, job.progress, job.busy = "ready", "ready", False
        except BaseException as error:
            if staged is not None:
                try: self.accounts.discard_preview_token(staged["token"])
                except BaseException: pass
            _close(collected); _close(job.verification); job.verification = None; _close(job.client); job.client = None
            self._finish_failure(job, error)

    def _spawn(self, job, operation, function, *args):
        job.operation, job.busy = operation, True
        thread = threading.Thread(target=function, args=(job, *args), name="idoly-official-import", daemon=True)
        self._thread = thread
        thread.start()

    def command(self, action, payload):
        fields = {"official_status": set(), "official_inspect": {"user_id", "password", "platform"},
                  "official_fetch": {"job_id"}, "official_cancel": {"job_id"},
                  "official_apply": {"job_id", "profile", "replace", "expected_revision"}}
        _need(type(action) is str and action in fields and type(payload) is dict
              and set(payload) == fields[action], "official_command_invalid")
        if action == "official_status": return {"action": action, "job": self.status(public=False)}
        if action == "official_inspect":
            user, password, platform = payload["user_id"], payload["password"], payload["platform"]
            _need(type(user) is str and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", user) is not None,
                  "transfer_id_invalid")
            _need(type(password) is str and 0 < len(password) <= 128 and password == password.strip()
                  and all(32 <= ord(char) < 127 for char in password), "transfer_password_invalid")
            _need(platform in ("ios", "android") and type(platform) is str, "platform_invalid")
            with self._lock:
                _need(not self._closed, "official_closed")
                _need(self._job is None or not self._job.busy, "official_job_busy")
                previous = self._job
                job = _Job(uuid.uuid4().hex, platform, self._now(), self._now()+_TTL)
                self._job = job
                self._retire(previous)
                self._schedule_expiry(job)
                self._spawn(job, "inspect", self._inspect, {"user_id": user, "password": password})
            password = None
            return {"action": action, "job": self.status(public=False)}
        with self._lock:
            self._expire()
            job = self._job
            _need(job is not None, "official_job_missing")
            _need(payload["job_id"] == job.job_id, "official_job_mismatch")
            if action == "official_cancel":
                _need(not (job.busy and job.operation == "apply"), "official_apply_in_progress")
                _need(job.state != "completed", "official_invalid_state")
                self._cancel_timer(job)
                job.cancel.set(); _close(job.verification); job.verification = None
                job.state, job.progress, job.error_code, job.preview = "cancelled", "cancelled", None, None
                if not job.busy: _close(job.client); job.client = None; self._drop_stage(job)
                return {"action": action, "job": self.status(public=False)}
            _need(not self._closed, "official_closed")
            _need(not job.busy, "official_job_busy")
            if action == "official_fetch":
                _need(job.state == "verified" and job.verification is not None, "official_invalid_state")
                job.state, job.progress, job.error_code = "fetching", "fetching", None
                self._spawn(job, "fetch", self._fetch)
                return {"action": action, "job": self.status(public=False)}
            _need(job.state == "ready" and job.stage_token is not None, "official_invalid_state")
            _need(type(payload["replace"]) is bool, "official_command_invalid")
            try: _profile(payload["profile"])
            except AccountError:
                raise OfficialImportError("account_profile_invalid") from None
            job.busy, job.operation, job.progress, job.error_code = True, "apply", "applying", None
        try:
            self._recheck_source(job)
            result = self.accounts.command("accounts_import", {"token": job.stage_token, "mode": "normal",
                "profile": payload["profile"], "replace": payload["replace"], "expected_revision": payload["expected_revision"]})
            with self._lock:
                job.state, job.progress, job.busy, job.stage_token = "completed", "completed", False, None
                self._cancel_timer(job)
            response = {"action": action, "job": self.status(public=False), "account": result["account"],
                        "status": result["status"]}
            if result.get("status_refresh_required") is True: response["status_refresh_required"] = True
            warnings = result.get("warning_codes", ())
            if type(warnings) is list:
                response["warning_codes"] = [code for code in warnings if type(code) is str and code in WARNING_CODES]
            return response
        except BaseException as error:
            code = _error(error)
            with self._lock:
                job.busy, job.error_code = False, code
                if code in _RETRYABLE_ACCOUNT_ERRORS:
                    job.state, job.progress = "ready", "ready"
                    self._expire()
                else:
                    self._cancel_timer(job)
                    job.state, job.progress, job.preview = "failed", "failed", None
            if code not in _RETRYABLE_ACCOUNT_ERRORS: self._drop_stage(job)
            raise OfficialImportError(code) from None

    action = command

    def close(self):
        with self._lock:
            self._closed = True
            job = self._job
            if job is None: return
            self._cancel_timer(job)
            if job.busy and job.operation == "apply": return
            job.cancel.set(); _close(job.verification); job.verification = None
            job.state, job.progress, job.preview = "cancelled", "cancelled", None
            if not job.busy: _close(job.client); job.client = None; self._drop_stage(job)
