"""Native-only account administration; portable archives never include sessions.

Every replacement captures all owned target rows under the same SQLite write
lock before changing them. Resource archives and account archives are distinct.
"""
from __future__ import annotations

import base64
import errno
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import struct
import threading
import time
import uuid
from zipfile import ZipFile, ZIP_DEFLATED, ZIP_STORED, BadZipFile

from .state import State, _ACCOUNT_TABLES, _ACCOUNT_TABLES_V1

MAX_ARCHIVE = 128 * 1024 * 1024
MAX_ACCOUNT_JSON = 96 * 1024 * 1024
KIND = "idoly-local-account"
_MODES = ("normal", "media")
_HEX = re.compile(r"[0-9a-f]{64}")
_TOKEN = re.compile(r"[0-9a-f]{32}")
_LOCK = threading.RLock()
_SCHEMA_CACHE = {}


class AccountError(ValueError):
    """Credential-free errors suitable for native settings screens."""


def _need(value, code):
    if not value:
        raise AccountError(code)


def _io_error(error, fallback="account_storage_io"):
    if isinstance(error, PermissionError) or getattr(error, "errno", None) in (errno.EACCES, errno.EPERM):
        return AccountError("account_permission_denied")
    if getattr(error, "errno", None) in (errno.ENOSPC, getattr(errno, "EDQUOT", -1)):
        return AccountError("account_insufficient_space")
    if isinstance(error, sqlite3.Error):
        code = getattr(error, "sqlite_errorcode", 0) & 255
        if code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
            return AccountError("account_storage_busy")
        if code == sqlite3.SQLITE_FULL:
            return AccountError("account_insufficient_space")
        if code in (sqlite3.SQLITE_PERM, sqlite3.SQLITE_AUTH):
            return AccountError("account_permission_denied")
        if isinstance(error, sqlite3.IntegrityError):
            return AccountError("account_state_rejected")
        return AccountError("account_storage_invalid")
    return AccountError(fallback)


def _profile(value):
    _need(type(value) is str and 0 < len(value.encode("utf-8")) <= 64 and value == value.strip()
          and value not in (".", "..") and all(ch.isprintable() and ch not in "/\\" for ch in value),
          "account_profile_invalid")
    return value


def _mode(value):
    _need(type(value) is str and value in _MODES, "account_mode_invalid")
    return value


def _revision(value):
    _need(type(value) is str and _HEX.fullmatch(value) is not None, "account_revision_required")
    return value


def _pairs(items):
    result = {}
    for key, value in items:
        _need(key not in result, "account_duplicate_json_key")
        result[key] = value
    return result


def _decode(raw):
    try:
        return json.loads(raw, object_pairs_hook=_pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(AccountError("account_json_nonfinite")))
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        raise AccountError("account_json_invalid") from None


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def _file(path, maximum):
    """Open one regular, unlinked-to file without following its final component."""
    path = Path(path)
    try:
        before = path.lstat()
        _need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and 0 < before.st_size <= maximum,
              "account_file_invalid")
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        after = os.fstat(fd)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
                after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
            os.close(fd)
            raise AccountError("account_file_changed")
        return os.fdopen(fd, "rb"), before
    except OSError as error:
        raise _io_error(error, "account_file_unavailable") from None


def _read(path, maximum):
    stream, before = _file(path, maximum)
    with stream:
        raw = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
    _need(len(raw) == before.st_size and len(raw) <= maximum
          and (before.st_size, before.st_mtime_ns, before.st_ctime_ns) == (
              after.st_size, after.st_mtime_ns, after.st_ctime_ns), "account_file_changed")
    return raw


def _hash_file(path, maximum):
    stream, before = _file(path, maximum)
    value, count = hashlib.sha256(), 0
    with stream:
        while True:
            block = stream.read(65536)
            if not block:
                break
            count += len(block)
            _need(count <= before.st_size, "account_file_changed")
            value.update(block)
        after = os.fstat(stream.fileno())
    _need(count == before.st_size and (before.st_size, before.st_mtime_ns, before.st_ctime_ns) == (
          after.st_size, after.st_mtime_ns, after.st_ctime_ns), "account_file_changed")
    return value.hexdigest()


def _sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        _need(stat.S_ISDIR(os.fstat(descriptor).st_mode), "account_storage_invalid")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic(path, value):
    path = Path(path)
    temporary = path.parent/("." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("xb") as outgoing:
            os.chmod(temporary, 0o600)
            outgoing.write(_json(value)); outgoing.flush(); os.fsync(outgoing.fileno())
        os.replace(temporary, path)
        _sync_directory(path.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


def _registry(root):
    base = Path(root)/"account-management"
    _need(not base.is_symlink() and (not base.exists() or base.is_dir()), "account_storage_invalid")
    path = base/"registry.json"
    if not path.exists() and not path.is_symlink():
        return {"schema": 1, "selected": {mode: None for mode in _MODES}}
    value = _decode(_read(path, 4096))
    _need(type(value) is dict and set(value) == {"schema", "selected"}
          and type(value["schema"]) is int and value["schema"] == 1
          and type(value["selected"]) is dict and set(value["selected"]) == set(_MODES),
          "account_selection_invalid")
    for profile in value["selected"].values():
        if profile is not None:
            _profile(profile)
    return value


def selection_status(data_dir, fallback="sandbox"):
    """Read bounded selection metadata only; no State creation or account SQL."""
    _profile(fallback)
    try:
        value = _registry(data_dir)
        return {"selected": {mode: value["selected"][mode] or fallback for mode in _MODES},
                "selection_revision": hashlib.sha256(_json(value)).hexdigest(), "invalid_registry": False}
    except (AccountError, OSError, ValueError):
        return {"selected": {mode: fallback for mode in _MODES},
                "selection_revision": None, "invalid_registry": True}


def selected_profile(data_dir, media_mode, fallback="sandbox"):
    _need(type(media_mode) is bool, "account_mode_invalid")
    _profile(fallback)
    mode = "media" if media_mode else "normal"
    value = _registry(data_dir)
    profile = value["selected"][mode]
    if profile is None:
        return fallback
    path = Path(data_dir)/("media-state.db" if media_mode else "state.db")
    _need(path.is_file() and not path.is_symlink(), "selected_account_missing")
    state = State(path)
    _need(state.profile(profile) is not None and state.snapshot(profile) is not None, "selected_account_missing")
    return profile


def _zip_directory_bound(stream, size):
    """Bound central-directory allocation before ZipFile creates member objects."""
    stream.seek(max(0, size-65557))
    tail = stream.read(65557)
    offset = tail.rfind(b"PK\x05\x06")
    _need(offset >= 0 and offset+22 <= len(tail), "account_archive_directory_invalid")
    fields = struct.unpack("<4s4H2LH", tail[offset:offset+22])
    _signature, disk, directory_disk, disk_entries, entries, extent, start, comment = fields
    _need(disk == directory_disk == 0 and disk_entries == entries == 2
          and 0 < extent <= 16384 and start+extent <= size
          and offset+22+comment == len(tail), "account_archive_directory_invalid")
    stream.seek(0)
    _need(stream.read(4) == b"PK\x03\x04", "account_archive_directory_invalid")
    stream.seek(0)


@contextmanager
def _bounded_zip(stream, size):
    _zip_directory_bound(stream, size)
    with ZipFile(stream) as archive:
        yield archive


def _unpack(raw):
    value = _decode(raw)
    _need(type(value) is dict and type(value.get("tables")) is dict, "account_bundle_schema_invalid")
    _need(type(value.get("schema")) is int and value["schema"] in (1, 2), "account_bundle_schema_invalid")
    for table, _columns, _primary in (_ACCOUNT_TABLES_V1 if value["schema"] == 1 else _ACCOUNT_TABLES):
        rows = value["tables"].get(table)
        _need(type(rows) is list and len(rows) <= 20000, "account_rows_bound")
        for row in rows:
            _need(type(row) is dict, "account_columns_invalid")
            if "response" in row:
                wrapper = row["response"]
                _need(type(wrapper) is dict and set(wrapper) == {"$bytes"}
                      and type(wrapper["$bytes"]) is str and len(wrapper["$bytes"]) <= (174764 if table == "profile_love_progress" else 45*1024*1024),
                      "account_blob_invalid")
                try:
                    row["response"] = base64.b64decode(wrapper["$bytes"], validate=True)
                except ValueError:
                    raise AccountError("account_blob_invalid") from None
    State.validate_account(value)
    _need(State.account_bytes(value) == raw, "account_bundle_not_canonical")
    return value


class AccountManager:
    def __init__(self, root, default_profile="sandbox", *, schema=None):
        self.root = Path(root).resolve()
        root_created = not self.root.exists()
        self.root.mkdir(parents=True, exist_ok=True)
        if root_created:
            _sync_directory(self.root.parent)
        self.default_profile = _profile(default_profile)
        self.base = self.root/"account-management"
        base_created = not self.base.exists() and not self.base.is_symlink()
        self.base.mkdir(mode=0o700, exist_ok=True)
        _need(self.base.is_dir() and not self.base.is_symlink(), "account_storage_invalid")
        if base_created:
            _sync_directory(self.root)
        self._schema_override = schema

    def _directory(self, name):
        _need(name in ("exports", "imports", "restore-points", "create-work"), "account_storage_invalid")
        path = self.base/name
        created = not path.exists() and not path.is_symlink()
        path.mkdir(mode=0o700, exist_ok=True)
        _need(path.is_dir() and not path.is_symlink(), "account_storage_invalid")
        if created:
            _sync_directory(self.base)
        return path

    def _temporary_directory(self, name):
        """Keep at most eight owned temporary copies; durable backups never rotate."""
        _need(name in ("imports", "exports"), "account_storage_invalid")
        directory = self._directory(name)
        pattern = r"[0-9a-f]{32}\.zip" if name == "imports" else r"IdolyPride-Account-[0-9a-f]{32}\.zip"
        copies = []
        for path in directory.iterdir():
            if re.fullmatch(pattern, path.name):
                info = path.lstat()
                _need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "account_storage_invalid")
                copies.append((info.st_mtime_ns, path))
                _need(len(copies) <= 128, "account_temporary_storage_bound")
        copies.sort(key=lambda entry: (entry[0], entry[1].name))
        keep = copies[-7:]
        cutoff = time.time_ns()-24*60*60*1_000_000_000
        for modified, path in copies:
            if (modified, path) not in keep or modified < cutoff:
                if name == "imports":
                    for suffix in (".json", ".consumed.json"):
                        receipt = path.with_suffix(suffix)
                        if receipt.exists() or receipt.is_symlink():
                            info = receipt.lstat()
                            _need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "account_storage_invalid")
                            receipt.unlink()
                path.unlink()
        return directory

    @contextmanager
    def _locked(self):
        with _LOCK:
            lock = self.base/"manager-lock.db"
            _need(not lock.is_symlink(), "account_storage_invalid")
            db = sqlite3.connect(lock, timeout=10, isolation_level=None)
            outcome = {}
            def release(function):
                try:
                    function()
                except (OSError, sqlite3.Error):
                    response = outcome.get("committed_response")
                    if response is None: raise
                    response["status_refresh_required"] = True
                    response["status"] = {**response["status"], "stale": True}
                    warnings = response.setdefault("warning_codes", [])
                    if "account_status_refresh_required" not in warnings:
                        warnings.append("account_status_refresh_required")
            try:
                os.chmod(lock, 0o600)
                db.execute("CREATE TABLE IF NOT EXISTS operation_lock (id INTEGER PRIMARY KEY)")
                db.execute("BEGIN IMMEDIATE")
                yield outcome
                # This database is a mutex, with no logical writes in its
                # transaction. Its release cannot undo a separate State commit.
                release(db.commit)
            finally:
                release(db.close)

    def _state(self, mode, *, existing=False):
        _mode(mode)
        path = self.root/("media-state.db" if mode == "media" else "state.db")
        _need(not path.is_symlink(), "account_state_invalid")
        if path.exists():
            info = path.lstat()
            _need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "account_state_invalid")
        if existing and not path.exists():
            return None
        return State(path)

    def _schema(self):
        if self._schema_override is not None:
            return self._schema_override
        path = self.root/"protocol"/"idolypride-6.1.1.pb"
        info = path.stat()
        key = (str(path), info.st_ino, info.st_size, info.st_mtime_ns)
        if key not in _SCHEMA_CACHE:
            from .schema import Schema
            _SCHEMA_CACHE.clear()
            _SCHEMA_CACHE[key] = Schema.from_descriptor_set(path)
        return _SCHEMA_CACHE[key]

    def _validate(self, bundle):
        bundle = State.upgrade_account(bundle)
        _profile(bundle["profile"])
        schema = self._schema()
        tables = bundle["tables"]
        _need(len(tables["snapshots"]) == 1, "account_snapshot_required")
        for rows in tables.values():
            for row in rows:
                if "schema_sha256" in row:
                    _need(row["schema_sha256"] == schema.fingerprint, "account_protocol_schema_differs")
        try:
            response = schema.response_type("/api.User/Get").FromString(tables["snapshots"][0]["response"])
            _need(response.HasField("user") and response.user.name.strip()
                  and len(response.user.name.encode("utf-8")) <= 128, "account_user_invalid")
            if "userPublic" in response.DESCRIPTOR.fields_by_name and response.HasField("userPublic"):
                identity = tables["profiles"][0]
                for field, column in (("serverUserId", "server_id"), ("publicUserId", "public_id")):
                    value = getattr(response.userPublic, field, "")
                    _need(not value or value == identity[column], "account_identity_mismatch")
            from google.protobuf import message_factory
            if tables["profile_settings"]:
                descriptor = schema.request_type("/api.Home/Login").DESCRIPTOR.fields_by_name["settingInfo"].message_type
                message_factory.GetMessageClass(descriptor).FromString(tables["profile_settings"][0]["response"])
            if tables["profile_lesson_progress"]:
                descriptor = schema.response_type("/api.Activity/ReceiveLessonReward").DESCRIPTOR.fields_by_name["progress"].message_type
                message_factory.GetMessageClass(descriptor).FromString(tables["profile_lesson_progress"][0]["response"])
            if tables["profile_love_progress"]:
                from .love import validate_progress
                for row in tables["profile_love_progress"]:
                    validate_progress(row["response"], row["love_id"])
            for table in ("preference_receipts", "main_live_attempts"):
                for row in tables[table]:
                    State.live_request_id(row["request_id"])
                    schema.response_type(row["path"]).FromString(row["response"])
                    if table == "main_live_attempts":
                        seed = row["seed"]
                        _need(re.fullmatch(r"0|[1-9][0-9]{0,19}", seed) is not None
                              and int(seed) <= (1<<64)-1 and row["started_time"] > 0,
                              "account_live_receipt_invalid")
        except AccountError:
            raise
        except Exception:
            raise AccountError("account_protobuf_invalid") from None

    def _summary(self, mode, bundle, revision):
        identity = bundle["tables"]["profiles"][0]
        result = {"mode": mode, "profile": bundle["profile"], "revision": revision,
                  "server_id": identity["server_id"], "public_id": identity["public_id"],
                  "has_snapshot": bool(bundle["tables"]["snapshots"]),
                  "counts": {name: len(rows) for name, rows in bundle["tables"].items()}}
        if bundle["tables"]["snapshots"]:
            try:
                protocol = self._schema()
                snapshot = bundle["tables"]["snapshots"][0]
                if snapshot["schema_sha256"] == protocol.fingerprint:
                    response = protocol.response_type("/api.User/Get").FromString(snapshot["response"])
                    if response.HasField("user") and len(response.user.name.encode("utf-8")) <= 128:
                        result["manager_name"] = response.user.name
                        result["inventory"] = {name: len(getattr(response, name, ())) for name in ("cards", "items", "photos")}
            except Exception:
                # Status remains available before payload/schema installation.
                pass
        return result

    def _index(self):
        path = self.base/"restore-index.json"
        if not path.exists() and not path.is_symlink():
            return []
        value = _decode(_read(path, 512 * 1024))
        _need(type(value) is list and len(value) <= 1000, "account_restore_index_invalid")
        seen = set()
        for row in value:
            _need(type(row) is dict and set(row) == {"id", "mode", "profile", "created_at", "revision"}
                  and type(row["id"]) is str and _TOKEN.fullmatch(row["id"]) is not None
                  and row["id"] not in seen and type(row["created_at"]) is int and row["created_at"] > 0,
                  "account_restore_index_invalid")
            _mode(row["mode"]); _profile(row["profile"]); _revision(row["revision"])
            seen.add(row["id"])
        return value

    def status(self, *, offset=0, restore_offset=0):
        _need(type(offset) is int and 0 <= offset <= 100000 and type(restore_offset) is int
              and 0 <= restore_offset <= 1000, "account_page_invalid")
        accounts, total = [], 0
        for mode in _MODES:
            state = self._state(mode, existing=True)
            if state is None:
                continue
            count, _ = state.account_profiles(limit=1)
            local_offset = max(0, offset-total)
            remaining = 24-len(accounts)
            if remaining and offset < total+count:
                _count, names = state.account_profiles(offset=local_offset, limit=remaining)
                for name in names:
                    bundle, revision = state.account_snapshot(name)
                    accounts.append(self._summary(mode, bundle, revision))
            total += count
        points = sorted(self._index(), key=lambda row: (row["created_at"], row["id"]), reverse=True)
        selection = selection_status(self.root, self.default_profile)
        return {"schema": 1, "accounts": accounts, "accounts_total": total, "offset": offset,
                "next_offset": offset+len(accounts) if offset+len(accounts) < total else None,
                "restore_points": points[restore_offset:restore_offset+16], "restore_points_total": len(points),
                "restore_offset": restore_offset,
                "next_restore_offset": restore_offset+16 if restore_offset+16 < len(points) else None, **selection}

    def _account(self, mode, profile, expected=None):
        state = self._state(_mode(mode), existing=True)
        found = state.account_snapshot(_profile(profile)) if state is not None else None
        _need(found is not None, "account_missing")
        bundle, revision = found
        if expected is not None:
            _need(_revision(expected) == revision, "account_revision_conflict")
        self._validate(bundle)
        return state, bundle, revision

    def _write_archive(self, path, mode, bundle, revision):
        bundle = State.upgrade_account(bundle)
        self._validate(bundle)
        _need(revision == State.account_revision(bundle), "account_archive_binding_invalid")
        raw = State.account_bytes(bundle)
        _need(len(raw) <= MAX_ACCOUNT_JSON, "account_archive_extent")
        manifest = {"kind": KIND, "schema": 2, "mode": mode, "profile": bundle["profile"],
                    "schema_sha256": self._schema().fingerprint, "account_bytes": len(raw),
                    "account_sha256": hashlib.sha256(raw).hexdigest(), "revision": revision,
                    "created_at": time.time_ns()//1_000_000}
        try:
            with Path(path).open("xb") as outgoing:
                os.chmod(path, 0o600)
                with ZipFile(outgoing, "w", compression=ZIP_DEFLATED, compresslevel=6) as archive:
                    archive.writestr("manifest.json", _json(manifest))
                    archive.writestr("account.json", raw)
                outgoing.flush(); os.fsync(outgoing.fileno())
            _sync_directory(Path(path).parent)
            size = Path(path).stat().st_size
            _need(0 < size <= MAX_ARCHIVE, "account_archive_extent")
            return {"path": str(path), "filename": Path(path).name, "bytes": size,
                    "sha256": _hash_file(path, MAX_ARCHIVE)}
        except BaseException:
            if Path(path).exists() and not Path(path).is_symlink():
                Path(path).unlink()
            raise

    def _archive(self, path, *, expected=None):
        stream, before = _file(path, MAX_ARCHIVE)
        try:
            with stream, _bounded_zip(stream, before.st_size) as archive:
                if expected is not None:
                    _need(before.st_size == expected["bytes"], "account_preview_changed")
                    stream.seek(0)
                    value, received = hashlib.sha256(), 0
                    while True:
                        block = stream.read(65536)
                        if not block:
                            break
                        received += len(block)
                        _need(received <= before.st_size, "account_preview_changed")
                        value.update(block)
                    _need(received == before.st_size and value.hexdigest() == expected["sha256"], "account_preview_changed")
                members = archive.infolist()
                _need(len(members) == 2 and {row.filename for row in members} == {"manifest.json", "account.json"},
                      "account_archive_kind_invalid")
                for row in members:
                    mode = (row.external_attr >> 16) & 0xffff
                    _need(not row.is_dir() and stat.S_IFMT(mode) in (0, stat.S_IFREG)
                          and not row.flag_bits & 1 and row.compress_type in (ZIP_STORED, ZIP_DEFLATED)
                          and 0 < row.file_size <= (16384 if row.filename == "manifest.json" else MAX_ACCOUNT_JSON),
                          "account_archive_member_invalid")
                raw_manifest = archive.read("manifest.json")
                manifest = _decode(raw_manifest)
                _need(type(manifest) is dict and set(manifest) == {"kind", "schema", "mode", "profile", "schema_sha256",
                      "account_bytes", "account_sha256", "revision", "created_at"}
                      and manifest["kind"] == KIND and type(manifest["schema"]) is int and manifest["schema"] in (1, 2),
                      "account_archive_kind_invalid")
                _mode(manifest["mode"]); _profile(manifest["profile"])
                _need(type(manifest["account_bytes"]) is int and 0 < manifest["account_bytes"] <= MAX_ACCOUNT_JSON
                      and type(manifest["created_at"]) is int and manifest["created_at"] > 0,
                      "account_archive_manifest_invalid")
                _revision(manifest["account_sha256"]); _revision(manifest["revision"])
                _need(manifest["schema_sha256"] == self._schema().fingerprint, "account_protocol_schema_differs")
                raw = archive.read("account.json")
                _need(len(raw) == manifest["account_bytes"] and hashlib.sha256(raw).hexdigest() == manifest["account_sha256"],
                      "account_archive_hash_differs")
                bundle = _unpack(raw)
                State.validate_account(bundle)
                _need(bundle["schema"] == manifest["schema"] and bundle["profile"] == manifest["profile"]
                      and State.account_revision(bundle) == manifest["revision"], "account_archive_binding_invalid")
                # Validate the original version/hash first; the old seven-table
                # bytes remain the receipt/index identity, while local installs
                # explicitly start with no Love progress missing from v1.
                bundle = State.upgrade_account(bundle)
                self._validate(bundle)
                after = os.fstat(stream.fileno())
                _need((before.st_size, before.st_mtime_ns, before.st_ctime_ns) == (
                    after.st_size, after.st_mtime_ns, after.st_ctime_ns), "account_file_changed")
        except OSError as error:
            raise _io_error(error) from None
        except (BadZipFile, RuntimeError, EOFError):
            raise AccountError("account_archive_invalid") from None
        return manifest, bundle

    def _backup(self, mode, bundle, revision):
        points = self._index()
        _need(len(points) < 1000, "account_restore_point_limit")
        token = uuid.uuid4().hex
        path = self._directory("restore-points")/(token + ".zip")
        self._write_archive(path, mode, bundle, revision)
        row = {"id": token, "mode": mode, "profile": bundle["profile"],
               "created_at": time.time_ns()//1_000_000, "revision": revision}
        _atomic(self.base/"restore-index.json", points+[row])
        return row

    def _seed(self, state, schema, profile, mode, manager_name):
        from .gameplay import seed_starter_profile
        seed_starter_profile(state, schema, profile, self.root/"master-json", manager_name=manager_name)
        if mode == "media":
            from .media_runtime import prepare_media_profile
            prepare_media_profile(state, schema, profile, self.root/"master-json")

    def _preview_result(self, token, path, mode, bundle, revision):
        receipt = {"schema": 1, "token": token, "mode": mode, "profile": bundle["profile"],
                   "revision": revision, "bytes": path.stat().st_size,
                   "sha256": _hash_file(path, MAX_ARCHIVE), "created_at": time.time_ns()//1_000_000}
        _atomic(path.with_suffix(".json"), receipt)
        return {"token": token, "archive": {**self._summary(mode, bundle, revision),
                "bytes": receipt["bytes"], "sha256": receipt["sha256"]}}

    def stage_snapshot(self, payload, *, server_id, public_id, schema_sha256):
        """Stage exact official User.Get bytes, without touching any account slot.

        Local settings, earning clocks and retry receipts are absent in an
        official snapshot; they must never be inherited from the target slot.
        Explicit import origin zero prevents normal starter migrations.
        """
        _need(type(payload) is bytes and 0 < len(payload) <= 32*1024*1024, "account_blob_invalid")
        _need(schema_sha256 == self._schema().fingerprint, "account_protocol_schema_differs")
        token = uuid.uuid4().hex
        profile = "official-source-" + token[:16]
        bundle = {"schema": 2, "profile": profile, "tables": {table: [] for table, _columns, _keys in _ACCOUNT_TABLES}}
        bundle["tables"]["profiles"] = [{"name": profile, "server_id": server_id, "public_id": public_id}]
        bundle["tables"]["snapshots"] = [{"profile": profile, "response": payload, "schema_sha256": schema_sha256}]
        bundle["tables"]["starter_profiles"] = [{"profile": profile, "version": 0}]
        self._validate(bundle)
        revision = State.account_revision(bundle)
        with self._locked():
            path = self._temporary_directory("imports")/(token+".zip")
            try:
                self._write_archive(path, "normal", bundle, revision)
                return self._preview_result(token, path, "normal", bundle, revision)
            except BaseException:
                for item in (path, path.with_suffix(".json")):
                    if item.exists() and not item.is_symlink(): item.unlink()
                raise

    def discard_preview_token(self, token):
        """Delete only this manager's expendable preview copy, never account data."""
        _need(type(token) is str and _TOKEN.fullmatch(token) is not None, "account_import_token_invalid")
        with self._locked():
            directory = self.base/"imports"
            if not directory.exists(): return
            _need(directory.is_dir() and not directory.is_symlink(), "account_storage_invalid")
            for path in (directory/(token+".json"), directory/(token+".consumed.json"), directory/(token+".zip")):
                if path.exists() or path.is_symlink():
                    info = path.lstat()
                    _need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "account_storage_invalid")
                    path.unlink()

    def command(self, action, payload):
        _need(type(action) is str and type(payload) is dict, "account_command_invalid")
        allowed = {
            "accounts_status": {"offset", "restore_offset"}, "accounts_create": {"mode", "profile", "manager_name"},
            "accounts_clone": {"mode", "source_profile", "profile", "expected_revision"},
            "accounts_select": {"mode", "profile", "expected_revision", "selection_revision"},
            "accounts_export": {"mode", "profile", "expected_revision"}, "accounts_preview": {"path"},
            "accounts_import": {"token", "mode", "profile", "replace", "expected_revision"},
            "accounts_restore": {"id", "mode", "profile", "expected_revision"},
        }
        _need(action in allowed and set(payload) <= allowed[action], "account_command_fields_invalid")
        with self._locked() as lock_outcome:
            result, committed_status, warnings = {}, None, []
            if action == "accounts_status":
                return {"schema": 1, "ok": True, "action": action, "status": self.status(**payload)}
            if action == "accounts_preview":
                source = Path(payload.get("path", ""))
                _need(source.is_absolute() and source.suffix.lower() == ".zip", "account_import_path_invalid")
                token = uuid.uuid4().hex
                target = self._temporary_directory("imports")/(token+".zip")
                stream, before = _file(source, MAX_ARCHIVE)
                try:
                    with stream, target.open("xb") as outgoing:
                        os.chmod(target, 0o600)
                        copied = 0
                        while True:
                            block = stream.read(65536)
                            if not block:
                                break
                            copied += len(block)
                            _need(copied <= before.st_size, "account_file_changed")
                            outgoing.write(block)
                        after = os.fstat(stream.fileno())
                        _need(copied == before.st_size and (before.st_size, before.st_mtime_ns, before.st_ctime_ns) == (
                            after.st_size, after.st_mtime_ns, after.st_ctime_ns), "account_file_changed")
                        outgoing.flush(); os.fsync(outgoing.fileno())
                    manifest, bundle = self._archive(target)
                except BaseException:
                    if target.exists(): target.unlink()
                    raise
                result = self._preview_result(token, target, manifest["mode"], bundle, manifest["revision"])
            else:
                mode, profile = _mode(payload.get("mode")), _profile(payload.get("profile"))
                if action == "accounts_create":
                    name = payload.get("manager_name")
                    from .profile_names import _blank
                    try:
                        valid_name = (type(name) is str and not _blank(name) and not any(ch in name for ch in "\r\n\t")
                                      and len(name.encode("utf-16-le"))//2 <= 10)
                    except UnicodeError:
                        valid_name = False
                    _need(valid_name, "account_manager_name_invalid")
                    state = self._state(mode)
                    _need(state.profile(profile) is None, "account_target_exists")
                    work = self._directory("create-work")/uuid.uuid4().hex
                    work.mkdir(mode=0o700)
                    try:
                        temporary = State(work/"account.db")
                        self._seed(temporary, self._schema(), profile, mode, name)
                        bundle, _source_revision = temporary.account_snapshot(profile)
                        self._validate(bundle)
                        revision = state.replace_account(profile, bundle)
                    finally:
                        shutil.rmtree(work)
                    result = {"account": self._summary(mode, bundle, revision)}
                elif action == "accounts_clone":
                    _revision(payload.get("expected_revision"))
                    state, bundle, _ = self._account(mode, payload.get("source_profile"), payload["expected_revision"])
                    _need(state.profile(profile) is None, "account_target_exists")
                    revision = state.replace_account(profile, bundle)
                    cloned, _ = state.account_snapshot(profile)
                    result = {"account": self._summary(mode, cloned, revision)}
                elif action == "accounts_select":
                    _revision(payload.get("expected_revision"))
                    self._account(mode, profile, payload["expected_revision"])
                    selection = selection_status(self.root, self.default_profile)
                    _need(not selection["invalid_registry"], "account_selection_invalid")
                    if payload.get("selection_revision") is not None:
                        _need(_revision(payload["selection_revision"]) == selection["selection_revision"],
                              "account_selection_conflict")
                    registry = _registry(self.root)
                    registry["selected"][mode] = profile
                    _atomic(self.base/"registry.json", registry)
                    result = {"restart_required": True}
                elif action == "accounts_export":
                    _state, bundle, revision = self._account(mode, profile, payload.get("expected_revision"))
                    path = self._temporary_directory("exports")/("IdolyPride-Account-" + uuid.uuid4().hex + ".zip")
                    result = self._write_archive(path, mode, bundle, revision)
                elif action in ("accounts_import", "accounts_restore"):
                    token = payload.get("token" if action == "accounts_import" else "id")
                    _need(type(token) is str and _TOKEN.fullmatch(token) is not None, "account_import_token_invalid")
                    if action == "accounts_import":
                        _need(type(payload.get("replace")) is bool, "account_replace_flag_required")
                        replace = payload["replace"]
                        path = self._directory("imports")/(token+".zip")
                        receipt = _decode(_read(path.with_suffix(".json"), 4096))
                        _need(type(receipt) is dict and set(receipt) == {"schema", "token", "mode", "profile", "revision",
                              "bytes", "sha256", "created_at"} and type(receipt["schema"]) is int and receipt["schema"] == 1
                              and receipt["token"] == token and type(receipt["bytes"]) is int
                              and 0 < receipt["bytes"] <= MAX_ARCHIVE and type(receipt["created_at"]) is int
                              and receipt["created_at"] > 0, "account_preview_receipt_invalid")
                        _mode(receipt["mode"]); _profile(receipt["profile"])
                        _revision(receipt["revision"]); _revision(receipt["sha256"])
                    else:
                        replace = True
                        point = next((row for row in self._index() if row["id"] == token), None)
                        _need(point is not None and point["mode"] == mode and point["profile"] == profile,
                              "account_restore_point_invalid")
                        path = self._directory("restore-points")/(token+".zip")
                    manifest, bundle = self._archive(path, expected=receipt if action == "accounts_import" else None)
                    if action == "accounts_import":
                        _need(all(manifest[key] == receipt[key] for key in ("mode", "profile", "revision")),
                              "account_preview_changed")
                    else:
                        _need(manifest["profile"] == point["profile"] and manifest["revision"] == point["revision"],
                              "account_restore_point_changed")
                    _need(manifest["mode"] == mode, "account_import_mode_differs")
                    state = self._state(mode)
                    existing = state.profile(profile)
                    if replace:
                        _need(existing is not None, "account_target_missing")
                        expected = _revision(payload.get("expected_revision"))
                    else:
                        _need(existing is None and payload.get("expected_revision") is None, "account_target_exists")
                        expected = None
                    # Complete all fallible reads before commit. The installed
                    # projection follows State.replace_account's fixed table/key
                    # mapping and preserves every original protobuf byte.
                    installed = {"schema": bundle["schema"], "profile": profile, "tables": {}}
                    for table, _columns, _keys in _ACCOUNT_TABLES:
                        key = "name" if table == "profiles" else "profile"
                        installed["tables"][table] = [{**row, key: profile} for row in bundle["tables"][table]]
                    summary = self._summary(mode, installed, State.account_revision(installed))
                    before_status = self.status()
                    backup, committed_revision, consumed = [], [], None
                    if action == "accounts_import":
                        receipt_path, consumed_path = path.with_suffix(".json"), path.with_suffix(".consumed.json")
                        _need(not consumed_path.exists() and not consumed_path.is_symlink(), "account_preview_changed")
                        # Removing the usable receipt before SQL makes this token
                        # unrepeatable even if post-commit cleanup is denied.
                        os.replace(receipt_path, consumed_path)
                        consumed = consumed_path
                    try:
                        if consumed is not None: _sync_directory(path.parent)
                        revision = state.replace_account(profile, bundle, expected_revision=expected,
                            before_replace=lambda old, old_revision: backup.append(self._backup(mode, old, old_revision)),
                            after_commit=lambda value: committed_revision.append(value))
                    except BaseException as error:
                        if isinstance(error, (OSError, sqlite3.Error)) and committed_revision:
                            revision = committed_revision[0]
                            warnings.append("account_status_refresh_required")
                        else:
                            if consumed is not None:
                                try:
                                    os.replace(consumed, receipt_path)
                                    _sync_directory(path.parent)
                                except OSError:
                                    raise AccountError("account_preview_changed") from None
                            raise
                    # State returned only after the SQLite transaction committed.
                    # Expendable-copy cleanup/status refresh cannot turn that
                    # success into a retry of an already-applied replacement.
                    committed_status = before_status
                    summary["revision"] = revision
                    result = {"account": summary, "restore_point": backup[0] if backup else None,
                              "restart_required": True}
                    if consumed is not None:
                        try:
                            consumed.unlink()
                            path.unlink()
                        except OSError:
                            warnings.append("account_temporary_cleanup_pending")
                else:
                    raise AccountError("account_command_unknown")
            try:
                status = self.status()
            except (OSError, sqlite3.Error, AccountError):
                if committed_status is None: raise
                status = {**committed_status, "stale": True}
                result["status_refresh_required"] = True
                warnings.append("account_status_refresh_required")
            if "account_status_refresh_required" in warnings:
                result["status_refresh_required"] = True
                status = {**status, "stale": True}
            if warnings: result["warning_codes"] = list(dict.fromkeys(warnings))
            response = {"schema": 1, "ok": True, "action": action, "status": status, **result}
            if committed_status is not None: lock_outcome["committed_response"] = response
            return response


def account_command(data_dir, action, payload):
    try:
        return AccountManager(data_dir).command(action, payload)
    except AccountError:
        raise
    except ValueError as error:
        code = str(error)
        raise AccountError(code if re.fullmatch(r"account_[a-z_]{1,64}", code) else "account_operation_failed") from None
    except (OSError, sqlite3.Error) as error:
        raise _io_error(error) from None
    except (KeyError, TypeError):
        raise AccountError("account_command_invalid") from None
