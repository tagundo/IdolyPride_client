"""Local event selection only: no account, reward, reset, restart or clock edits."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import tempfile
import threading
import time

FILENAME = "server-events.json"
MEDIA_FILENAME = "server-events-media.json"
MAX_SAFE_INTEGER = 2**53 - 1
MAX_WINDOW_MS = 366 * 24 * 60 * 60 * 1000  # Explicit local policy, not an official duration.
MAX_EVENTS = 64
MAX_BYTES = 32768
DEFAULTS = {"schema": 1, "revision": 0, "love_events": []}
ERROR_CODES = frozenset(("event_settings_invalid", "event_settings_revision_conflict",
    "event_settings_catalog_unavailable", "event_settings_unsupported", "event_settings_storage_invalid",
    "event_settings_storage_unavailable", "event_settings_busy", "event_settings_io",
    "event_settings_revision_exhausted", "event_settings_command_invalid"))
_LOCK = threading.RLock()
_ID = re.compile(r"[A-Za-z0-9_-]{1,96}")


class EventSettingsError(ValueError):
    def __init__(self, code):
        self.code = code if type(code) is str and code in ERROR_CODES else "event_settings_io"
        super().__init__(self.code)


def _need(condition, code="event_settings_invalid"):
    if not condition:
        raise EventSettingsError(code)


def _object(pairs):
    value = {}
    for key, item in pairs:
        _need(key not in value)
        value[key] = item
    return value


def validate_settings(value, *, catalog=None, require_supported=False, media_mode=False):
    """Canonicalize IDs; periods are caller-chosen local milliseconds only."""
    _need(type(media_mode) is bool)
    _need(type(value) is dict and set(value) == {"schema", "revision", "love_events"})
    _need(type(value["schema"]) is int and value["schema"] == 1)
    _need(type(value["revision"]) is int and 0 <= value["revision"] <= MAX_SAFE_INTEGER)
    entries = value["love_events"]
    _need(type(entries) is list and len(entries) <= MAX_EVENTS)
    result, identities = [], set()
    for row in entries:
        _need(type(row) is dict and set(row) == {"event_id", "start_time_ms", "end_time_ms"})
        identity, start, end = row["event_id"], row["start_time_ms"], row["end_time_ms"]
        _need(type(identity) is str and _ID.fullmatch(identity) is not None and identity not in identities)
        _need(type(start) is int and type(end) is int)
        if media_mode:
            _need(start == 0 and end == 0)  # Gallery choices have no artificial local expiry.
        else:
            _need(0 <= start < end <= MAX_SAFE_INTEGER and end - start <= MAX_WINDOW_MS)
        identities.add(identity)
        result.append(dict(row))
    if require_supported and result:
        _need(type(catalog) is dict and catalog.get("available") is True,
              "event_settings_catalog_unavailable")
        supported = {row["id"] for row in catalog.get("events", ())
                     if type(row) is dict and type(row.get("id")) is str and row.get("supported") is True}
        _need(identities <= supported, "event_settings_unsupported")
    return {"schema": 1, "revision": value["revision"],
            "love_events": sorted(result, key=lambda row: row["event_id"])}


def _decode(raw, *, media_mode=False):
    _need(type(raw) is bytes and 0 < len(raw) <= MAX_BYTES)
    try:
        return validate_settings(json.loads(raw.decode("utf-8"), object_pairs_hook=_object), media_mode=media_mode)
    except (UnicodeError, RecursionError, json.JSONDecodeError):
        raise EventSettingsError("event_settings_invalid") from None


def _read(path, *, media_mode=False):
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    try:
        info = os.fstat(descriptor)
        _need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and 0 < info.st_size <= MAX_BYTES,
              "event_settings_storage_invalid")
        raw = os.read(descriptor, MAX_BYTES + 1)
        _need(len(raw) == info.st_size, "event_settings_storage_invalid")
    finally:
        os.close(descriptor)
    return _decode(raw, media_mode=media_mode)


_EVENT_TITLES = {
    "love-23-0514": ("이치노세 레이", "Rei Ichinose"),
    "love-23-1114": ("이부키 나기사", "Nagisa Ibuki"),
    "love-24-0517": ("하야사카 메이", "Mei Hayasaka"),
    "love-24-1114": ("스즈무라 유우", "Yu Suzumura"),
    "love-26-0313": ("칸자키 리오", "Rio Kanzaki"),
}


def _titles(identity, original):
    """UI labels only; original IDs, story text and captured titles stay intact."""
    names = _EVENT_TITLES.get(identity)
    if names is not None:
        return {"ko": "만약 당신과 사랑에 빠진다면 · " + names[0] + " 편",
                "ja": original, "en": "If I Fell in Love with You · " + names[1]}
    if identity == "love-extra-25-0426":
        return {"ko": "사큐×마호 ~KISS AND MAGIC!~", "ja": original,
                "en": "Succu × Magic ~KISS AND MAGIC!~"}
    return {language: original for language in ("ko", "ja", "en")}


def _catalog(data_dir, override=None):
    unavailable = {"schema": 1, "available": False, "events": [], "ruleset_sha256": None,
                   "reason_code": "event_catalog_unavailable"}
    try:
        if override is None:
            from .love_catalog import event_catalog
            value = event_catalog(data_dir)
        else:
            value = override
        _need(type(value) is dict and type(value.get("schema")) is int and value["schema"] == 1 and type(value.get("available")) is bool
              and type(value.get("events")) is list and len(value["events"]) <= MAX_EVENTS)
        if not value["available"]:
            return unavailable
        rows, seen = [], set()
        for row in value["events"]:
            _need(type(row) is dict and type(row.get("id")) is str and _ID.fullmatch(row["id"]) is not None
                  and row["id"] not in seen and type(row.get("title")) is str
                  and 0 < len(row["title"].encode("utf-8")) <= 1024 and row["title"].isprintable()
                  and type(row.get("supported")) is bool)
            seen.add(row["id"])
            safe = {"id": row["id"], "title": row["title"],
                    "titles": _titles(row["id"], row["title"]), "supported": row["supported"],
                    "source_grade": "original_master_and_reference_capture_claim",
                    "inference_status": "reference_routes_inferred",
                    "original_start_time_ms": None, "original_end_time_ms": None,
                    "original_duration_ms": None}
            _need(row.get("source_grade") == safe["source_grade"]
                  and row.get("inference_status") == safe["inference_status"])
            start = row.get("original_start_time_ms")
            if start is not None:
                _need(type(start) is int and 0 <= start <= MAX_SAFE_INTEGER)
                safe["original_start_time_ms"] = start
            _need(row.get("original_end_time_ms") is None and row.get("original_duration_ms") is None)
            rows.append(safe)
        ruleset = value.get("ruleset_sha256")
        _need(type(ruleset) is str and re.fullmatch(r"[0-9a-f]{64}", ruleset) is not None)
        result = {"schema": 1, "available": True, "events": sorted(rows, key=lambda row: row["id"]),
                  "ruleset_sha256": ruleset}
        _need(len(json.dumps(result, ensure_ascii=False).encode("utf-8")) <= 16384)
        return result
    except (ImportError, OSError, ValueError, TypeError, KeyError, UnicodeError):
        return unavailable


def _storage_error(error):
    if isinstance(error, sqlite3.Error) and getattr(error, "sqlite_errorcode", None) in (
            sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
        return EventSettingsError("event_settings_busy")
    if isinstance(error, PermissionError):
        return EventSettingsError("event_settings_storage_unavailable")
    return EventSettingsError("event_settings_io")


@contextmanager
def _save_lock(root):
    # This separate mutex never opens the account State DB. SQLite is available
    # on all embedded platforms; file locking modules are not equally portable.
    with _LOCK:
        root.mkdir(parents=True, exist_ok=True)
        path = root / "server-events-lock.db"
        if path.exists() or path.is_symlink():
            info = path.lstat()
            _need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
                  "event_settings_storage_invalid")
        connection = sqlite3.connect(path, timeout=5, isolation_level=None)
        outcome = {"committed": False}
        def release(function):
            try:
                function()
            except (OSError, sqlite3.Error):
                if not outcome["committed"]:
                    raise
        try:
            os.chmod(path, 0o600)
            connection.execute("CREATE TABLE IF NOT EXISTS settings_lock(id INTEGER PRIMARY KEY)")
            connection.execute("BEGIN IMMEDIATE")
            yield outcome
            # A mutex release cannot undo an already replaced preference file.
            release(connection.commit)
        finally:
            release(connection.close)


class EventSettingsState:
    """Read saved choices independently; Runtime passes a frozen effective copy."""
    def __init__(self, data_dir, *, catalog=None, media_mode=False):
        _need(type(media_mode) is bool)
        self.root = Path(data_dir).resolve()
        self.media_mode = media_mode
        self.path = self.root / (MEDIA_FILENAME if media_mode else FILENAME)
        self._catalog_override = deepcopy(catalog)
        self._settings = deepcopy(DEFAULTS)
        self._invalid_file = False
        self._last_save_default_all = False
        self._lock = threading.RLock()

    def _defaults(self, catalog=None):
        value = deepcopy(DEFAULTS)
        if self.media_mode:
            catalog = catalog if catalog is not None else _catalog(self.root, self._catalog_override)
            value["love_events"] = [{"event_id": row["id"], "start_time_ms": 0, "end_time_ms": 0}
                                    for row in catalog.get("events", ()) if row.get("supported") is True]
        return value

    def settings(self, *, _catalog_value=None):
        try:
            value = _read(self.path, media_mode=self.media_mode)
        except FileNotFoundError:
            value = self._defaults(_catalog_value)
        except (OSError, ValueError):
            with self._lock:
                self._invalid_file = True
                return deepcopy(self._settings)
        with self._lock:
            self._settings, self._invalid_file = value, False
            return deepcopy(value)

    def status(self, *, effective=None, _saved=None, _default_all=None):
        catalog = _catalog(self.root, self._catalog_override)
        # A command acknowledgement describes its own committed snapshot, not
        # a different writer's newer file observed after our mutex is released.
        saved = (self.settings(_catalog_value=catalog) if _saved is None else
                 validate_settings(_saved, media_mode=self.media_mode))
        active = validate_settings(effective, media_mode=self.media_mode) if effective is not None else None
        with self._lock:
            invalid = self._invalid_file if _saved is None else False
        default_all = (self.media_mode and not os.path.lexists(self.path)
                       if _default_all is None else _default_all)
        return {"schema": 1, "saved": saved, "effective": active,
                "restart_required": active is not None and saved["love_events"] != active["love_events"],
                "catalog": catalog, "invalid_settings_file": invalid,
                "media_mode": self.media_mode,
                "media_default_all": default_all,
                "media_all_supported": self.media_mode and catalog.get("available") is True
                    and {row["event_id"] for row in saved["love_events"]}
                    == {row["id"] for row in catalog["events"] if row["supported"]}}

    def save(self, settings, *, expected_revision):
        _need(type(expected_revision) is int and 0 <= expected_revision <= MAX_SAFE_INTEGER)
        catalog = _catalog(self.root, self._catalog_override)
        value = validate_settings(settings, catalog=catalog, require_supported=True, media_mode=self.media_mode)
        _need(value["revision"] == expected_revision, "event_settings_revision_conflict")
        temporary = None
        try:
            with _save_lock(self.root) as outcome:
                try:
                    current = _read(self.path, media_mode=self.media_mode)
                except FileNotFoundError:
                    current = self._defaults(catalog)
                _need(current["revision"] == expected_revision, "event_settings_revision_conflict")
                self._last_save_default_all = self.media_mode and not os.path.lexists(self.path)
                if current["love_events"] == value["love_events"]:
                    return current  # No-op autosaves never reset or advance a period.
                _need(current["revision"] < MAX_SAFE_INTEGER, "event_settings_revision_exhausted")
                value["revision"] = max(current["revision"] + 1, min(time.time_ns() // 1_000_000, MAX_SAFE_INTEGER))
                raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                _need(len(raw) <= MAX_BYTES)
                fd, name = tempfile.mkstemp(prefix=".server-events-", suffix=".tmp", dir=self.root)
                temporary = Path(name)
                with os.fdopen(fd, "wb") as output:
                    output.write(raw)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temporary, self.path)
                outcome["committed"] = True
                self._last_save_default_all = False
                temporary = None
            with self._lock:
                self._settings, self._invalid_file = deepcopy(value), False
            return deepcopy(value)
        except EventSettingsError:
            raise
        except (OSError, sqlite3.Error) as error:
            raise _storage_error(error) from None
        finally:
            if temporary is not None:
                try:
                    temporary.unlink()
                except OSError:
                    pass


def event_settings_status(data_dir, *, effective=None, media_mode=False):
    return EventSettingsState(data_dir, media_mode=media_mode).status(effective=effective)


def event_settings_command(data_dir, action, payload, *, effective=None, media_mode=False):
    _need(type(action) is str and type(payload) is dict and type(media_mode) is bool,
          "event_settings_command_invalid")
    payload = dict(payload)
    mode = payload.pop("mode", "media" if media_mode else "normal")
    _need(type(mode) is str and mode in ("normal", "media"), "event_settings_command_invalid")
    media_mode = mode == "media"
    state = EventSettingsState(data_dir, media_mode=media_mode)
    saved = None
    if action == "events_status":
        _need(not payload, "event_settings_command_invalid")
    elif action == "events_save":
        _need(set(payload) == {"settings", "expected_revision"}, "event_settings_command_invalid")
        saved = state.save(payload["settings"], expected_revision=payload["expected_revision"])
    else:
        raise EventSettingsError("event_settings_command_invalid")
    return state.status(effective=effective, _saved=saved,
                        _default_all=state._last_save_default_all if saved is not None else None)


def freeze_event_settings(data_dir, *, media_mode=False):
    state = EventSettingsState(data_dir, media_mode=media_mode)
    value = state.settings()
    _need(not state._invalid_file)
    if not value["love_events"]:
        return value  # Disabled defaults do not require any event data/module.
    return validate_settings(value, catalog=_catalog(state.root), require_supported=True, media_mode=media_mode)
