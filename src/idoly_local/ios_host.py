"""In-process iOS host: worker-thread startup and a bounded local UI bridge.

The native host owns interpreter, trusted WebKit content and app lifecycle.
This module owns no process signals, stdin, child process or admin HTTP route.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import importlib
import json
import os
from pathlib import Path
import stat
import tempfile
import threading
import time
import uuid

from .public_payload import install_payload, install_bundled_translations

MAX_JSON_BYTES = 64 * 1024
MAX_SETTINGS_BYTES = 8192
MAX_ARCHIVE_BYTES = 512 * 1024**3
MAX_EXPORT_FILES = 4
DEFAULT_OPTIONS = {"schema": 1, "media_mode": True, "download_missing_resources": True,
                   "interface_language": "system"}


STARTUP_FAILURE_FILE = "ios-startup-failure.json"
STARTUP_FAILURE_MAX = 16 * 1024
STARTUP_FAILURE_STAGES = frozenset(("catalog", "resources", "storage", "runtime"))
STARTUP_FAILURE_CODES = frozenset(("permission_denied", "missing_input", "address_in_use", "insufficient_space", "invalid_input", "internal_error"))
STARTUP_FAILURE_TYPES = frozenset(("PermissionError", "FileNotFoundError", "OSError", "ValueError", "RuntimeError", "TypeError", "AttributeError", "ImportError", "ModuleNotFoundError", "KeyError", "IndexError", "LookupError", "UnicodeError", "UnicodeDecodeError", "OperationalError", "DatabaseError", "RpcFailure", "OtherError"))
STARTUP_FAILURE_FILES = frozenset(('__init__.py', 'account_manager.py', 'app_runtime.py', 'appearance.py', 'application.py', 'assets.py', 'bundled_translations.py', 'card_level_missions.py', 'card_progression.py', 'catalog.py', 'codec.py', 'company.py', 'diagnostics.py', 'dream.py', 'dream_capture.py', 'event_settings.py', 'excursion.py', 'gameplay.py', 'h2_server.py', 'home_talk.py', 'initial_inventory.py', 'ios_client_data.py', 'ios_host.py', 'language_settings.py', 'latest_cohort_pins.py', 'lessons.py', 'live_accessories.py', 'live_assets.py', 'live_engine.py', 'live_input.py', 'live_rejection_diagnostics.py', 'love.py', 'love_catalog.py', 'love_compatibility_pins.py', 'main_live.py', 'master_sort.py', 'media_access.py', 'media_outfit_policy.py', 'media_panorama.py', 'media_profile.py', 'media_runtime.py', 'media_scenes.py', 'media_settings.py', 'media_stories.py', 'octo_cache.py', 'octo_http.py', 'octo_manifest.py', 'octo_runtime.py', 'official_account.py', 'official_account_config.py', 'official_import.py', 'official_roots.py', 'official_transport.py', 'panorama_rules.py', 'photo_names.py', 'photo_preferences.py', 'photo_shooting.py', 'playback.py', 'preference_master_data.py', 'presentation.py', 'profile_directory.py', 'profile_emblems.py', 'profile_favorites.py', 'profile_layout.py', 'profile_messages.py', 'profile_names.py', 'profile_preferences.py', 'profile_top.py', 'public_cohort_support.py', 'public_payload.py', 'public_payload_transaction.py', 'pvp.py', 'quest.py', 'render_probe.py', 'resource_archive.py', 'resource_library.py', 'resource_routes.py', 'resource_translation.py', 'resource_translation_cache.py', 'resource_translation_runtime.py', 'rpc.py', 'runtime_history.py', 'schema.py', 'social.py', 'startup_cache.py', 'startup_receipt.py', 'startup_checks.py', 'state.py', 'story_catalog.py', 'story_read_rules.py', 'story_reads.py', 'tutorial_messages.py', 'tutorial_progression.py', 'tutorial_replay.py', 'wardrobe_diagnostics.py'))


def _startup_function(value):
    return type(value) is str and len(value) <= 80 and value.isascii() and (value.isidentifier() or value in ("<module>", "<listcomp>", "<dictcomp>", "<setcomp>", "<genexpr>", "<lambda>"))


def _startup_failure(error, stage):
    """Retain source coordinates only, never exception text, arguments or locals."""
    from .startup_checks import failure_code
    kind = type(error).__name__
    result = {"schema": 1, "scope": "ios-startup-failure", "stage": stage if stage in STARTUP_FAILURE_STAGES else "runtime",
              "error_code": failure_code(error), "error_type": kind if kind in STARTUP_FAILURE_TYPES else "OtherError", "frames": []}
    number = getattr(error, "errno", None) if isinstance(error, OSError) else None
    if type(number) is int and 0 <= number <= 4096:
        result["errno"] = number
    source_root = Path(__file__).parent
    trace, visited = error.__traceback__, 0
    while trace is not None and visited < 64:
        code = trace.tb_frame.f_code
        filename = code.co_filename
        if type(filename) is str and len(filename) <= 4096:
            path = Path(filename)
            if (path.parent == source_root and path.name in STARTUP_FAILURE_FILES
                    and _startup_function(code.co_name) and type(trace.tb_lineno) is int and 1 <= trace.tb_lineno <= 1000000):
                result["frames"].append({"file": path.name, "function": code.co_name, "line": trace.tb_lineno})
                result["frames"] = result["frames"][-8:]
        trace, visited = trace.tb_next, visited + 1
    return result


@dataclass(frozen=True)
class PortParams:
    """Production uses fixed loopback ports; tests may request ephemeral ports."""
    grpc_port: int = 50051
    asset_port: int = 8080

    def __post_init__(self):
        if any(type(v) is not int or not 0 <= v <= 65535 for v in (self.grpc_port, self.asset_port)):
            raise ValueError("Invalid listener port")
        if self.grpc_port and self.grpc_port == self.asset_port:
            raise ValueError("Listeners require distinct ports")


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate command field")
        result[key] = value
    return result


def _invalid_constant(_value):
    raise ValueError("Nonfinite JSON value")


def _decode(raw, maximum=MAX_JSON_BYTES):
    if type(raw) is not str or not 0 < len(raw.encode("utf-8")) <= maximum:
        raise ValueError("Invalid JSON size")
    value = json.loads(raw, object_pairs_hook=_object, parse_constant=_invalid_constant)
    pending = [(value, 0)]
    while pending:
        current, depth = pending.pop()
        if depth > 16:
            raise ValueError("JSON nesting exceeds its bound")
        if isinstance(current, dict):
            pending.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            pending.extend((item, depth + 1) for item in current)
    return value


def _json(value):
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    if len(raw.encode("utf-8")) > MAX_JSON_BYTES:
        raise ValueError("JSON response exceeds its bound")
    return raw


def _official_job(value, *, private=False, errors=()):
    """A second bounded boundary between the service and native/Web diagnostics."""
    value = value if isinstance(value, dict) else {}
    states = ("idle", "checking", "verified", "fetching", "ready", "completed", "failed", "cancelled")
    stages = ("idle", "applying", "preparing", "checking", "verifying", "verified", "transferring", "firebase", "login",
              "master", "account", "collected", "fetching", "catalog_check", "staging", "ready", "completed", "cancelled", "failed")
    identifier, code = value.get("job_id"), value.get("error_code")
    def counts(raw):
        return {key: raw[key] for key in ("cards", "items", "photos")
            if isinstance(raw, dict) and type(raw.get(key)) is int and 0 <= raw[key] <= 2**31 - 1}
    result = {"schema": 1, "state": value.get("state") if value.get("state") in states else "failed",
        "job_id": identifier if type(identifier) is str and len(identifier) == 32
            and all(character in "0123456789abcdef" for character in identifier) else None,
        "progress": value.get("progress") if value.get("progress") in stages else "preparing",
        "busy": value.get("busy") is True, "counts": counts(value.get("counts")),
        "error_code": code if type(code) is str and code in errors else None,
        "expires_in_seconds": value.get("expires_in_seconds") if type(value.get("expires_in_seconds")) is int
            and 0 <= value["expires_in_seconds"] <= 600 else 0}
    preview = value.get("preview")
    if private and isinstance(preview, dict):
        safe = {"inventory": counts(preview.get("inventory"))}
        for key in ("public_id", "server_id", "manager_name"):
            text = preview.get(key)
            try:
                if type(text) is str and text.isprintable() and 0 < len(text.encode("utf-8")) <= 256:
                    safe[key] = text
            except UnicodeError:
                pass
        level = preview.get("manager_level")
        if type(level) is int and 0 <= level <= 2**31 - 1:
            safe["manager_level"] = level
        result["preview"] = safe
    return result


def _status_budget(value):
    # Native adds gate/progress observations after this reply. Reserve room so
    # a full account page cannot turn an otherwise valid status into an error.
    raw = _json(value)
    if len(raw.encode("utf-8")) > MAX_JSON_BYTES - 8192:
        raise ValueError("Status exceeds its native-envelope budget")
    return raw


def _regular(path, *, maximum=MAX_ARCHIVE_BYTES):
    info = Path(path).lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not 0 < info.st_size <= maximum:
        raise ValueError("A bounded regular file is required")
    return info


def _bundled_payload_pin(bundle):
    """Read only the small package-generated public-data identity."""
    path = Path(bundle) / "payload-pin.json"
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return {}  # Older bundles retain the legacy missing-only installer.
    with os.fdopen(descriptor, "rb") as incoming:
        before = os.fstat(incoming.fileno())
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or not 0 < before.st_size <= 4096):
            raise ValueError("Bundled public payload pin is invalid")
        raw = incoming.read(4097)
        after = os.fstat(incoming.fileno())
        identity = lambda row: (row.st_dev, row.st_ino, row.st_size, row.st_mtime_ns, row.st_ctime_ns)
        if len(raw) != before.st_size or identity(before) != identity(after):
            raise ValueError("Bundled public payload pin changed")
    pin = _decode(raw.decode("utf-8"), maximum=4096)
    keys = {"schema", "policy", "bytes", "sha256", "manifest_sha256", "master_version"}
    if (type(pin) is not dict or set(pin) != keys or type(pin.get("schema")) is not int
            or pin["schema"] != 1 or pin.get("policy") != "latest-cohort-overlay-v1"
            or type(pin.get("bytes")) is not int or not 0 < pin["bytes"] <= 512 * 1024**2
            or any(type(pin.get(key)) is not str or len(pin[key]) != 64
                or any(character not in "0123456789abcdef" for character in pin[key])
                for key in ("sha256", "manifest_sha256", "master_version"))):
        raise ValueError("Bundled public payload pin is invalid")
    return {"expected_sha256": pin["sha256"], "expected_bytes": pin["bytes"]}


def _register_app_startup_receipt(bundle):
    """An optional public optimization read only from fixed signed-app files."""
    from .startup_receipt import register_startup_receipt
    unavailable = {"schema": 1, "available": False}
    try:
        path = Path(bundle) / "startupTranslations.json"
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor,"rb") as incoming:
            before = os.fstat(incoming.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or not 0 < before.st_size <= 4096:
                raise ValueError("Invalid optional receipt pin")
            raw = incoming.read(4097); after = os.fstat(incoming.fileno())
            identity = lambda row:(row.st_dev,row.st_ino,row.st_size,row.st_mtime_ns,row.st_ctime_ns)
            if len(raw) != before.st_size or identity(before) != identity(after):
                raise ValueError("Changed optional receipt pin")
        metadata = _decode(raw.decode("utf-8"),maximum=4096)
        if (type(metadata) is not dict or set(metadata) != {"schema","platform","sha256","bytes"}
                or type(metadata["schema"]) is not int or metadata["schema"] != 1 or metadata["platform"] != "ios"):
            raise ValueError("Invalid optional receipt pin")
        return register_startup_receipt(Path(bundle)/"startupTranslations.zip",
            expected_sha256=metadata["sha256"],expected_bytes=metadata["bytes"],platform="ios")
    except (OSError,ValueError,TypeError,UnicodeError,RecursionError):
        # Clear an earlier registration before the ordinary full-validation path.
        register_startup_receipt(b"",expected_sha256="",expected_bytes=0,platform="ios")
        return unavailable


def _atomic_json(path, value, *, only_missing=False):
    raw = _json(value).encode("utf-8")
    if len(raw) > MAX_SETTINGS_BYTES:
        raise ValueError("Preference file exceeds its bound")
    path = Path(path)
    try:
        _regular(path, maximum=MAX_SETTINGS_BYTES)
    except FileNotFoundError:
        pass
    else:
        if only_missing:
            return
    fd, temporary = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(raw); out.flush(); os.fsync(out.fileno())
        if only_missing:
            try:
                os.link(temporary, path)
            except FileExistsError:
                pass
        else:
            os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _directory(value, *, create=False):
    path = Path(value)
    if not path.is_absolute() or path.is_symlink():
        raise ValueError("An absolute app-owned directory is required")
    if create:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not path.is_dir():
        raise ValueError("An app-owned directory is required")
    return path.resolve(strict=True)


_HTTP_ROW_KEYS = ("request_id", "method", "path", "http_status", "phase", "elapsed_ms")
_RESOURCE_ROW_KEYS = ("request_id", "method", "kind", "route_fingerprint", "phase", "http_status",
    "cache_result", "object_name", "cache_key", "error_code", "cause_code", "application_version",
    "requested_revision", "served_revision", "response_mode", "elapsed_ms")


def _thin_observation(value, keys):
    """Keep bounded public scalars when the complete runtime snapshot is large."""
    if not isinstance(value, dict):
        return None
    result = {}
    for key in keys:
        item = value.get(key)
        if key not in value:
            continue
        if item is None or type(item) is bool:
            result[key] = item
        elif type(item) is int:
            result[key] = min(2**53 - 1, max(0, item))
        elif isinstance(item, str):
            if key == "path":
                from .assets import _public_http_path
                result[key] = _public_http_path(item)
            else:
                result[key] = "".join("_" if ord(c) < 32 or ord(c) == 127 else c for c in item[:256])
        if key in result and len(_json(result).encode("utf-8")) > 2048:
            del result[key]
    return result


def _thin_transfers(runtime):
    asset = _thin_observation(runtime.get("asset_transfer"), ("active_requests", "path", "sent_bytes",
        "total_bytes", "status", "http_status", "completed_requests", "failed_requests", "session_bytes_sent"))
    resource = _thin_observation(runtime.get("resource_transfer"), ("available", "allow_downloads", "status",
        "active_requests", "session_received_bytes", "session_verified_files", "session_served_bytes",
        "session_manifest_bytes", "last_received_bytes", "last_total_bytes", "session_http_requests",
        "session_http_failures", "session_cache_hits", "session_cache_misses", "measurement_limited"))
    http = _thin_observation(runtime.get("http_requests"), ("total_requests", "active_requests",
        "completed_requests", "failed_requests"))
    for name, target, row_keys, histories, count in (
            ("resource_transfer", resource, _RESOURCE_ROW_KEYS, ("recent_requests", "active_http_requests"), 3),
            ("http_requests", http, _HTTP_ROW_KEYS, ("recent_requests",), 10)):
        source = runtime.get(name)
        if target is None or not isinstance(source, dict):
            continue
        for key in ("last_request", "last_failed_request"):
            if key in source:
                target[key] = _thin_observation(source[key], row_keys)
        for key in histories:
            if isinstance(source.get(key), list):
                target[key] = [row for item in source[key][-count:]
                               if (row := _thin_observation(item, row_keys)) is not None]
    return {key: value for key, value in (("asset_transfer", asset), ("resource_transfer", resource),
                                         ("http_requests", http)) if key in runtime}


class _LimitedOutput:
    def __init__(self, stream, maximum):
        self.stream, self.maximum = stream, maximum

    def write(self, value):
        if self.stream.tell() + len(value) > self.maximum:
            raise ValueError("Export exceeds its prepared catalog bound")
        return self.stream.write(value)

    def __getattr__(self, name):
        return getattr(self.stream, name)


class _Host:
    def __init__(self, *, bridge=None, runtime_factory=None, installer=None, translation_installer=None):
        self._condition = threading.Condition(threading.RLock())
        self._commands = threading.RLock()
        self._bridge = bridge
        self._factory = runtime_factory
        self._installer = installer or install_payload
        self._translations = translation_installer or install_bundled_translations
        self._runtime = None
        self._paths = None
        self._ports = PortParams()
        self._state = "idle"
        self._closed = False
        self._generation = 0
        self._effective = None
        self._error = None
        self._logs = deque(maxlen=100)
        self._archive_worker = None
        self._archive_result = None
        self._account_status = None
        self._game_prepared = False
        self._prepared_account = None
        self._startup_observations = None
        self._startup_failure = None
        self._official_import = None
        self._official_errors = ()

    def _native(self):
        if self._bridge is None:
            self._bridge = importlib.import_module("_idoly_ios")
        for name in ("aes_cbc", "open_url", "post_event"):
            if not callable(getattr(self._bridge, name, None)):
                raise ValueError("Incomplete native iOS bridge")
        return self._bridge

    def _event(self, name, **values):
        try:
            self._native().post_event(_json({"event": name, **values}))
        except Exception:
            # A settings window or event consumer cannot own serving threads.
            pass

    def _log(self, message):
        line = str(message).replace("\r", " ").replace("\n", " ")[:512]
        with self._condition:
            self._logs.append(line)
        self._event("log", message=line)

    def _options(self):
        from .language_settings import LanguageSettingsState, validate_settings
        if self._paths is None:
            return {**DEFAULT_OPTIONS, "language": "ko"}
        data = self._paths[1]
        try:
            path = data / "ios-host.json"
            _regular(path, maximum=MAX_SETTINGS_BYTES)
            value = _decode(path.read_text("utf-8"), MAX_SETTINGS_BYTES)
            required = {"schema", "media_mode", "download_missing_resources"}
            if (not isinstance(value, dict) or not required <= value.keys()
                    or value.keys() - required - {"language", "interface_language"}
                    or type(value["schema"]) is not int or value["schema"] != 1):
                raise ValueError("Invalid host preferences")
            if any(type(value[k]) is not bool for k in ("media_mode", "download_missing_resources")):
                raise ValueError("Invalid host preferences")
        except FileNotFoundError:
            value = dict(DEFAULT_OPTIONS)
        value.setdefault("interface_language", "system")
        if value["interface_language"] not in ("system", "ko", "ja", "en"):
            raise ValueError("Invalid interface language")
        if "language" in value:
            validate_settings({"schema": 1, "language": value["language"]})
            return value
        return {**value, "language": LanguageSettingsState(data / "client-language.json").settings()["language"]}

    @staticmethod
    def _listeners_ready(runtime):
        return (runtime.status().get("running") is True
                and getattr(getattr(runtime, "_grpc", None), "running", False) is True
                and bool(getattr(runtime, "_asset_thread", None))
                and runtime._asset_thread.is_alive())

    def status(self):
        with self._condition:
            runtime = self._runtime
            state, effective, error, paths = self._state, self._effective, self._error, self._paths
            operation = self._archive_result
        # Never hold the host lock while entering runtime/library locks or I/O.
        try:
            options = self._options()
        except (OSError, ValueError, UnicodeError, RecursionError):
            options = dict(effective or {**DEFAULT_OPTIONS, "language": "ko"}); invalid = True
        else:
            invalid = False
        observed = dict(runtime.status() if runtime is not None else {"running": False})
        if runtime is None and paths is not None:
            from .app_runtime import server_settings_status
            observed.update(self._startup_observations or server_settings_status(paths[1]))
        event_mode = options.get("media_mode") is True
        event_status = observed.get("event_settings")
        if paths is not None and (not isinstance(event_status, dict)
                or event_status.get("media_mode", False) is not event_mode):
            from .event_settings import event_settings_status
            observed["event_settings"] = event_settings_status(paths[1], media_mode=event_mode)
        observed["logs"] = [str(x)[:512] for x in observed.get("logs", [])[-20:]]
        restart = effective is not None and any(options.get(key) != effective.get(key)
            for key in ("media_mode", "download_missing_resources", "language"))
        events = observed.get("event_settings", {})
        if isinstance(events, dict) and events.get("restart_required") is True:
            restart = True
        media = observed.get("media_options", {})
        if media.get("effective_settings") is not None and media.get("settings") != media["effective_settings"]:
            restart = True
        if isinstance(self._account_status, dict) and effective is not None:
            mode = "media" if effective.get("media_mode") else "normal"
            selected = self._account_status.get("selected", {}).get(mode)
            if isinstance(selected, str) and observed.get("profile") and selected != observed["profile"]:
                restart = True
        result = {"state": state, "running": state == "ready" and observed.get("running") is True,
            "options": options, "effective_options": effective, "restart_required": restart,
            "invalid_options_file": invalid, "runtime": observed, "last_error": error,
            "resource_operation": operation, "paths": None,
            "account_management_available": paths is not None, "accounts": self._account_status,
            "official_import_available": paths is not None,
            "official_import": _official_job(self._official_import.status(public=True), errors=self._official_errors) if self._official_import is not None else None}
        if paths is not None:
            result["paths"] = {"imports": str(paths[1] / "imports"), "exports": str(paths[1] / "tmp/exports")}
        if self._startup_failure is not None:
            result["startup_failure"] = self._startup_failure
        # Diagnostic histories may be large; public settings stay available.
        try:
            _status_budget(result)
        except ValueError:
            result["runtime"] = _thin_observation(observed, ("running", "profile", "media_mode", "grpc_address", "asset_url")) or {}
            result["runtime"].update(_thin_transfers(observed))
            result["diagnostics_truncated"] = True
            # Retaining an unbounded language/renderer report here would make
            # the fallback overflow too, hiding the counters again. Prefer the
            # complete field when it fits, then its validated control settings.
            for key in ("presentation", "playback", "media_options", "language", "event_settings"):
                if key not in observed:
                    continue
                value = observed[key]
                settings = ({k: v for k, v in value.items() if k in (
                    "settings", "effective_settings", "invalid_settings_file", "effective_language",
                    "schema", "saved", "effective", "restart_required", "catalog",
                    "media_mode", "media_default_all", "media_all_supported")}
                    if isinstance(value, dict) else {})
                for candidate in (value, settings):
                    result["runtime"][key] = candidate
                    try:
                        _status_budget(result)
                    except (ValueError, TypeError, RecursionError):
                        del result["runtime"][key]
                    else:
                        break
        for key in ("startup_checks", "durable_history"):
            if key in observed and key not in result["runtime"]:
                value = observed[key]
                candidates = [value]
                if key == "durable_history" and isinstance(value, dict):
                    summary = {name: value[name] for name in ("schema", "available", "load_state", "persistence",
                        "last_write_error", "current_run", "retained_records", "total_records", "last_failure") if name in value}
                    records = value.get("records") if isinstance(value.get("records"), list) else []
                    candidates += [{**summary, "records": records[-3:], "records_truncated": len(records) > 3},
                                   {**summary, "records": [], "records_truncated": bool(records)}]
                for candidate in candidates:
                    result["runtime"][key] = candidate
                    try:
                        _status_budget(result)
                    except (ValueError, TypeError, RecursionError):
                        del result["runtime"][key]
                    else:
                        break
        return result

    def start(self, bundle_dir, data_dir, resource_dir, *, ports=None):
        with self._condition:
            while self._state == "starting" and not self._closed:
                self._condition.wait()
            already_started = self._closed or self._state == "ready"
            if not already_started:
                self._state = "starting"; self._error = None
                self._generation += 1
            generation = self._generation
            previous = self._runtime if not already_started else None
        if already_started:
            return self.status()
        candidate = None
        factory_entered = False
        wrapper_stage = "catalog"
        with self._condition:
            self._startup_observations = None
            self._startup_failure = None
        try:
            if previous is not None:
                previous.stop()
                with self._condition:
                    if self._runtime is previous:
                        self._runtime = None
            bundle = _directory(bundle_dir)
            data, resources = Path(data_dir), Path(resource_dir)
            if not data.is_absolute() or not resources.is_absolute() or data.is_symlink() or resources.is_symlink():
                raise ValueError("Absolute app-owned storage is required")
            data, resources = data.resolve(), resources.resolve()
            if (data == resources or data in resources.parents or resources in data.parents
                    or bundle == data or bundle in data.parents or bundle == resources or bundle in resources.parents):
                raise ValueError("Writable data must be separate from the bundled sources")
            data = _directory(data, create=True); resources = _directory(resources, create=True)
            selected_ports = ports or PortParams()
            if not isinstance(selected_ports, PortParams):
                raise ValueError("Invalid listener configuration")
            with self._condition:
                self._paths = (bundle, data, resources); self._ports = selected_ports
            native = self._native()
            payload_pin = _bundled_payload_pin(bundle)
            self._installer(bundle / "ServerData.zip", data, self._log, **payload_pin)
            wrapper_stage = "resources"
            _register_app_startup_receipt(bundle)
            self._translations(bundle / "ServerData.zip", resources, self._log, data_dir=data)
            wrapper_stage = "storage"
            _atomic_json(data / "ios-host.json", DEFAULT_OPTIONS, only_missing=True)
            _atomic_json(data / "client-language.json", {"schema": 1, "language": "ko"}, only_missing=True)
            _directory(data / "imports", create=True); _directory(data / "tmp/exports", create=True)
            options = self._options()
            # One atomic host record commits pending profile/language choices.
            # Activate its language file only before a fresh runtime starts.
            from .language_settings import LanguageSettingsState
            language_path = data / "client-language.json"
            if LanguageSettingsState(language_path).settings()["language"] != options["language"]:
                _atomic_json(language_path, {"schema": 1, "language": options["language"]})
            with self._condition:
                cancelled = self._closed or generation != self._generation
            if cancelled:
                return self.status()
            if self._factory is None:
                from .app_runtime import start as factory
            else:
                factory = self._factory
            factory_entered = True
            candidate = factory(data, profile="sandbox", log_callback=self._log,
                grpc_host="127.0.0.1", grpc_port=selected_ports.grpc_port,
                asset_host="127.0.0.1", asset_port=selected_ports.asset_port,
                resource_platform="ios", resource_cache_dir=resources,
                aes_cbc=native.aes_cbc, resource_fetcher=native.open_url,
                media_mode=options["media_mode"], download_missing_resources=options["download_missing_resources"])
            if not self._listeners_ready(candidate):
                raise RuntimeError("Both loopback listeners must be ready")
            with self._condition:
                cancelled = self._closed or generation != self._generation
                if not cancelled:
                    self._runtime = candidate; candidate = None
                    self._effective = dict(options); self._state = "ready"
            if cancelled:
                candidate.stop(); candidate = None
                return self.status()
            result = self.status(); self._event("ready", status=result)
            return result
        except Exception as error:
            failure_stage = "runtime" if factory_entered else wrapper_stage
            try:
                diagnostic = _startup_failure(error, failure_stage)
            except Exception:
                diagnostic = {"schema": 1, "scope": "ios-startup-failure", "stage": failure_stage,
                              "error_code": "internal_error", "error_type": "OtherError", "frames": []}
            try:
                if self._paths is None:
                    raise OSError()
                _atomic_json(self._paths[1] / STARTUP_FAILURE_FILE, diagnostic)
            except Exception:
                persistence = "unavailable"
            else:
                persistence = "stored"
            with self._condition:
                self._startup_failure = {**diagnostic, "persistence": persistence}
            if not factory_entered and self._paths is not None:
                try:
                    from .app_runtime import record_startup_failure
                    observation = record_startup_failure(self._paths[1], error, stage=wrapper_stage)
                    with self._condition:
                        self._startup_observations = observation
                except Exception:
                    pass
            if candidate is not None:
                try:
                    candidate.stop()
                except Exception:
                    with self._condition:
                        self._runtime = candidate
            with self._condition:
                if not self._closed:
                    self._state = "failed"
                    self._error = {"code": "startup_failed", "message": "Local server startup failed", "type": type(error).__name__}
            result = self.status(); self._event("error", status=result)
            return result
        finally:
            with self._condition:
                self._condition.notify_all()

    def foreground(self):
        with self._condition:
            runtime = self._runtime
            available = not self._closed and self._state == "ready" and runtime is not None
            paths, ports = self._paths, self._ports
        if not available or self._listeners_ready(runtime):
            return self.status()
        pending = self.status()["restart_required"]
        if pending:
            with self._condition:
                self._state = "failed"
                self._error = {"code": "restart_required", "message": "Restart the game to apply saved settings and recover the server"}
            result = self.status(); self._event("error", status=result); return result
        try:
            runtime.stop()
        except Exception:
            with self._condition:
                self._state = "failed"; self._error = {"code": "cleanup_failed", "message": "Server cleanup must complete before retry"}
            return self.status()
        with self._condition:
            cancelled = self._closed
            if not cancelled:
                self._runtime = None; self._state = "idle"
        if cancelled:
            return self.status()
        return self.start(*paths, ports=ports)

    def prepare_game_start(self):
        """Apply pending game options and prepare immutable data before Unity init."""
        with self._commands:
            status = self.status()
            if status["state"] != "ready" or not status["running"]:
                raise RuntimeError("The local server must be ready before starting the game")
            if self._official_import is not None and self._official_import.status(public=True).get("busy") is True:
                raise RuntimeError("Finish or cancel the official account operation before starting the game")
            runtime = status.get("runtime", {})
            job = runtime.get("resource_library", {}).get("job")
            operation = status.get("resource_operation")
            if ((isinstance(job, dict) and job.get("state") in
                    ("preparing", "running", "export_ready", "cancelling"))
                    or (isinstance(operation, dict) and operation.get("accepted") is True
                        and operation.get("ready") is not True)):
                raise RuntimeError("Finish or cancel the resource operation before starting the game")
            with self._condition:
                paths, ports, current = self._paths, self._ports, self._runtime
            if status["restart_required"]:
                try:
                    current.stop()
                except Exception:
                    with self._condition:
                        self._state = "failed"
                        self._error = {"code": "cleanup_failed", "message": "Server cleanup must complete before retry"}
                    raise
                with self._condition:
                    self._runtime = None
                    self._state = "idle"
                status = self.start(*paths, ports=ports)
                if not status["running"]:
                    raise RuntimeError("The local server could not apply the selected game options")
            from .ios_client_data import prepare_client_data
            selected = self._options()["language"]
            prepared = prepare_client_data(paths[0].parent, paths[1], selected)
            result = self.status()
            profile = result.get("runtime", {}).get("profile")
            prepared_account = (("media" if result.get("effective_options", {}).get("media_mode") else "normal"), profile) if isinstance(profile, str) else None
            with self._condition:
                self._prepared_account = prepared_account
                self._game_prepared = True
            return {"state": result["state"], "running": result["running"],
                    "effective_options": result["effective_options"], "client_data": prepared}

    def readiness(self):
        result = self.status()
        return {"state": result["state"], "running": result["running"]}

    def close(self):
        if self._official_import is not None:
            try:
                self._official_import.close()
            except Exception:
                pass  # Never export a credential-bearing shutdown exception.
        with self._condition:
            self._closed = True; self._generation += 1; self._state = "closed"
            runtime = self._runtime; self._condition.notify_all()
        if runtime is not None:
            try:
                runtime.stop()
            except Exception:
                with self._condition:
                    self._error = {"code": "cleanup_failed", "message": "Server cleanup can be retried"}
            else:
                with self._condition:
                    if self._runtime is runtime:
                        self._runtime = None
        self._event("closed", status=self.status())

    def _ready_runtime(self):
        with self._condition:
            if self._closed or self._state != "ready" or self._runtime is None:
                raise ValueError("Server is not ready")
            return self._runtime

    def _save(self, action, settings):
        from . import presentation, playback, media_settings
        data = self._paths[1]
        module, filename = {"save_presentation": (presentation, "client-presentation.json"),
            "save_playback": (playback, "client-playback.json"), "save_media": (media_settings, "client-media.json")}[action]
        value = module.validate_settings(settings)
        path = data / filename
        if path.exists() or path.is_symlink():
            _regular(path, maximum=MAX_SETTINGS_BYTES)
            current = module.validate_settings(_decode(path.read_text("utf-8"), MAX_SETTINGS_BYTES))
            value["revision"] = max(value["revision"], current["revision"])
        if value["revision"] >= 2**63 - 1:
            raise ValueError("Preference revision exhausted")
        if action == "save_media":
            module.save_settings(path, value)
        else:
            value["revision"] = max(value["revision"] + 1, time.time_ns() // 1_000_000)
            _atomic_json(path, module.validate_settings(value))

    def _archive(self, library, action, source=None):
        with self._condition:
            if self._archive_worker is not None and self._archive_worker.is_alive():
                raise ValueError("An archive operation is already active")
            exports = self._paths[1] / "tmp/exports"
            if action == "resources_export":
                if sum(1 for _, _p in zip(range(MAX_EXPORT_FILES), exports.iterdir())) >= MAX_EXPORT_FILES:
                    raise ValueError("Native export cleanup is required before another export")
                job = library.prepare_export("ios")
                output = exports / ("IdolyPride-Resources-ios-" + uuid.uuid4().hex + ".zip")
            else:
                job, output = None, None
            initial = {"accepted": True, "ready": False, "output_path": str(output) if output else None, "job": job}
            self._archive_result = initial
            def work():
                temporary = None
                try:
                    if action == "resources_export":
                        fd, temporary = tempfile.mkstemp(prefix=".export-", suffix=".part", dir=exports)
                        with os.fdopen(fd, "wb") as out:
                            maximum = min(MAX_ARCHIVE_BYTES, int(job.get("total_bytes", 0)) + 40 * 1024**2 + MAX_JSON_BYTES)
                            result = library.write_export(job["job_id"], _LimitedOutput(out, maximum))
                            out.flush(); os.fsync(out.fileno())
                        if result.get("state") not in ("completed", "partial") or result.get("archive_complete") is not True or result.get("failed_files") != 0:
                            raise ValueError("Export did not complete")
                        os.replace(temporary, output); temporary = None
                    else:
                        with source as incoming:
                            result = library.import_from(incoming, "ios")
                        if result.get("state") not in ("completed", "partial") or result.get("failed_files", 0) or result.get("error_code") is not None:
                            raise ValueError("Import did not complete")
                    response = {"accepted": True, "ready": True, "output_path": str(output) if output else None, "job": result}
                except Exception as error:
                    if job is not None:
                        try:
                            library.cancel(job["job_id"])
                        except Exception:
                            pass
                    response = {"accepted": False, "ready": False, "output_path": None,
                        "error": {"code": "archive_failed", "message": "Resource archive operation failed", "type": type(error).__name__}}
                    if job is not None:
                        response["job"] = job
                finally:
                    if temporary is not None:
                        try:
                            Path(temporary).unlink(missing_ok=True)
                        except OSError:
                            pass
                with self._condition:
                    self._archive_result = response
                self._event("resource_result", **response)
            self._archive_worker = threading.Thread(target=work, name="idoly-ios-resource-archive", daemon=True)
            self._archive_worker.start()
            return initial


    def _guard_prepared_account(self, mode, profile):
        with self._condition:
            prepared, identity = self._game_prepared, self._prepared_account
        if prepared and (identity is None or identity == (mode, profile)):
            raise ValueError("account_restart_required")

    def _restart_after_official_apply(self, paths, ports, *, committed):
        try:
            refreshed = self.start(*paths, ports=ports)
            if isinstance(refreshed, dict) and refreshed.get("running") is True:
                return True
        except Exception:
            pass  # Never overwrite the operation's result with a restart error.
        with self._condition:
            if not self._closed:
                self._state = "failed"
                self._error = {"code": "official_server_restart_required", "message":
                    "계정 저장은 완료됐지만 서버를 다시 시작하지 못했습니다. ‘서버 시작’을 다시 누르고, 계속 실패하면 앱을 다시 열어 주세요."
                    if committed else "서버를 다시 시작하지 못했습니다. 서버 상태를 확인해 주세요."}
        return False

    def _official_command(self, action, value):
        """Explicit native commands; credentials never enter status or events."""
        if self._paths is None or self._closed:
            raise ValueError("official_storage_unavailable")
        payload = {key: item for key, item in value.items() if key not in ("id", "action")}
        replacing = action == "official_apply" and payload.get("replace") is True
        if replacing:
            self._guard_prepared_account("normal", payload.get("profile"))
        if self._official_import is None:
            from .official_import import OfficialImportManager, ERROR_CODES
            self._official_errors = frozenset(ERROR_CODES)
            self._official_import = OfficialImportManager(self._paths[1])
        with self._condition:
            runtime, paths, ports = self._runtime, self._paths, self._ports
        observed = runtime.status() if runtime is not None else {}
        replaces_active = (replacing and observed.get("running") is True
            and observed.get("media_mode") is not True and observed.get("profile") == payload.get("profile"))
        if replaces_active:
            operation = self.status().get("resource_operation")
            job = observed.get("resource_library", {}).get("job")
            if (isinstance(operation, dict) and operation.get("accepted") is True and operation.get("ready") is not True
                    or isinstance(job, dict) and job.get("state") in ("preparing", "running", "export_ready", "cancelling")):
                raise ValueError("account_operation_busy")
            runtime.stop()
            with self._condition:
                self._runtime = None
                self._state = "idle"
        try:
            result = self._official_import.command(action, payload)
            if (not isinstance(result, dict) or not isinstance(result.get("job"), dict)
                    or result.get("action") != action):
                raise ValueError("official_response_invalid")
            safe = {"action": action, "job": _official_job(result["job"], private=True, errors=self._official_errors)}
            if action == "official_apply":
                if safe["job"]["state"] != "completed":
                    raise ValueError("official_response_invalid")
                if isinstance(result.get("status"), dict):
                    with self._condition:
                        self._account_status = result["status"]
                    safe["status"] = result["status"]
                elif result.get("status_refresh_required") is True:
                    with self._condition:
                        self._account_status = None
                if isinstance(result.get("account"), dict):
                    safe["account"] = result["account"]
                warnings = result.get("warning_codes")
                if type(warnings) in (list, tuple):
                    allowed = ("account_temporary_cleanup_pending", "account_status_refresh_required")
                    safe["warning_codes"] = list(dict.fromkeys(code for code in warnings[:8]
                        if type(code) is str and code in allowed))
                if result.get("status_refresh_required") is True:
                    safe["status_refresh_required"] = True
        except Exception:
            if replaces_active:
                self._restart_after_official_apply(paths, ports, committed=False)
            raise
        if replaces_active and not self._restart_after_official_apply(paths, ports,
                committed=safe["job"]["state"] == "completed"):
            # The canonical DB result is already committed. A later serving
            # failure must not invite another transfer/apply or reset the job.
            safe.setdefault("warning_codes", []).append("official_server_restart_required")
        return safe

    def _account_command(self, action, value):
        """Trusted native account operations; paths never come from the web page."""
        from .account_manager import account_command
        if self._paths is None:
            raise ValueError("account_storage_unavailable")
        with self._condition:
            if self._closed:
                raise ValueError("account_host_closed")
        root = self._paths[1]
        payload = {key: item for key, item in value.items() if key not in ("id", "action")}
        if action == "accounts_restore":
            payload["id"] = payload.pop("restore_id", None)
        approved_import = None
        approved_identity = None
        if action == "accounts_export":
            exports = root / "tmp" / "exports"
            if sum(1 for _, _path in zip(range(MAX_EXPORT_FILES), exports.iterdir())) >= MAX_EXPORT_FILES:
                raise ValueError("account_export_cleanup_required")
        if action == "accounts_preview":
            approved_import = Path(payload.get("path", ""))
            if (not approved_import.is_absolute() or approved_import.suffix.lower() != ".zip"
                    or _directory(approved_import.parent) != root / "imports"):
                raise ValueError("account_import_path_invalid")
            info = _regular(approved_import, maximum=128 * 1024**2)
            approved_identity = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
        with self._condition:
            runtime, paths, ports = self._runtime, self._paths, self._ports
            prepared = self._game_prepared
        observed = runtime.status() if runtime is not None else {}
        active_mode = "media" if observed.get("media_mode") else "normal"
        replacing = (action == "accounts_restore"
            or action == "accounts_import" and payload.get("replace") is True)
        if replacing:
            self._guard_prepared_account(payload.get("mode"), payload.get("profile"))
        replaces_active = (replacing and observed.get("running") is True
            and payload.get("mode") == active_mode and payload.get("profile") == observed.get("profile"))
        if replaces_active and prepared:
            raise ValueError("account_restart_required")
        if replaces_active:
            operation = self.status().get("resource_operation")
            job = observed.get("resource_library", {}).get("job")
            if (isinstance(operation, dict) and operation.get("accepted") is True and operation.get("ready") is not True
                    or isinstance(job, dict) and job.get("state") in ("preparing", "running", "export_ready", "cancelling")):
                raise ValueError("account_operation_busy")
            runtime.stop()
            with self._condition:
                self._runtime = None
                self._state = "idle"
        try:
            result = account_command(root, action, payload)
        finally:
            if approved_import is not None:
                try:
                    info = _regular(approved_import, maximum=128 * 1024**2)
                    if (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) == approved_identity:
                        approved_import.unlink()
                except (OSError, ValueError):
                    pass
            if replaces_active:
                refreshed = self.start(*paths, ports=ports)
                if not refreshed.get("running"):
                    raise RuntimeError("Account operation completed but server restart failed")
        if not isinstance(result, dict) or not isinstance(result.get("status"), dict):
            raise ValueError("account_response_invalid")
        if action == "accounts_export":
            import hashlib
            import re
            filename = result.get("filename")
            if not isinstance(filename, str) or re.fullmatch(r"IdolyPride-Account-[0-9a-f]{32}\.zip", filename) is None:
                raise ValueError("account_export_name_invalid")
            source = Path(result.get("path", ""))
            owned = root / "account-management" / "exports"
            if source.name != filename or _directory(source.parent) != _directory(owned):
                raise ValueError("account_export_path_invalid")
            before = _regular(source, maximum=128 * 1024**2)
            exports = root / "tmp" / "exports"
            if sum(1 for _, _path in zip(range(MAX_EXPORT_FILES), exports.iterdir())) >= MAX_EXPORT_FILES:
                raise ValueError("account_export_cleanup_required")
            target = exports / filename
            if target.exists() or target.is_symlink():
                raise ValueError("account_export_target_exists")
            incoming_fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            try:
                with os.fdopen(incoming_fd, "rb") as incoming, target.open("xb") as outgoing:
                    after = os.fstat(incoming.fileno())
                    if ((before.st_dev, before.st_ino, before.st_size) != (after.st_dev, after.st_ino, after.st_size)
                            or not stat.S_ISREG(after.st_mode) or after.st_nlink != 1):
                        raise ValueError("account_export_source_changed")
                    digest, count = hashlib.sha256(), 0
                    while block := incoming.read(65536):
                        count += len(block)
                        if count > 128 * 1024**2:
                            raise ValueError("account_export_too_large")
                        digest.update(block)
                        outgoing.write(block)
                    outgoing.flush()
                    os.fsync(outgoing.fileno())
                if count != result.get("bytes") or digest.hexdigest() != result.get("sha256"):
                    raise ValueError("account_export_digest_differs")
            except BaseException:
                target.unlink(missing_ok=True)
                raise
            source.unlink()
            result = {key: item for key, item in result.items() if key != "path"}
            result.update(ready=True, output_path=str(target))
        with self._condition:
            self._account_status = result["status"]
        return result

    def _dispatch(self, value):
        action = value.get("action")
        fields = {"status": set(), "save_interface_language": {"interface_language"},
            "save_options": {"media_mode", "download_missing_resources", "language", "interface_language"},
            "save_presentation": {"settings"}, "save_playback": {"settings"}, "save_media": {"settings"},
            "resources_preview": set(), "resources_download": {"parallelism"}, "resources_cancel": {"job_id"},
            "resources_import": {"path"}, "resources_export": set(),
            "accounts_status": {"offset", "restore_offset"},
            "accounts_create": {"mode", "profile", "manager_name"},
            "accounts_clone": {"mode", "source_profile", "profile", "expected_revision"},
            "accounts_select": {"mode", "profile", "expected_revision", "selection_revision"},
            "accounts_export": {"mode", "profile", "expected_revision"},
            "accounts_preview": {"path"},
            "accounts_import": {"token", "mode", "profile", "replace", "expected_revision"},
            "accounts_restore": {"restore_id", "mode", "profile", "expected_revision"},
            "diagnostics_clear": set(),
            "official_inspect": {"user_id", "password", "platform"},
            "official_fetch": {"job_id"}, "official_apply": {"job_id", "profile", "replace", "expected_revision"},
            "official_cancel": {"job_id"}, "official_status": set(),
            "events_status": {"mode"}, "events_save": {"mode", "settings", "expected_revision"}}
        if action not in fields or value.keys() - {"id", "action"} - fields[action]:
            raise ValueError("Unknown command or fields")
        if action == "status":
            return self.status()
        if action == "save_interface_language":
            if (value.keys() != {"id", "action", "interface_language"}
                    or value["interface_language"] not in ("system", "ko", "ja", "en")):
                raise ValueError("Invalid interface language command")
            if self._paths is None:
                raise ValueError("Server preference storage is unavailable")
            options = self._options()
            options["interface_language"] = value["interface_language"]
            _atomic_json(self._paths[1] / "ios-host.json", options)
            return {"interface_language": options["interface_language"]}
        if action == "diagnostics_clear":
            if self._paths is None:
                raise ValueError("Server history storage is unavailable")
            if self._runtime is not None:
                self._runtime.clear_history()
            else:
                from .app_runtime import clear_server_history
                clear_server_history(self._paths[1])
            with self._condition:
                self._startup_observations = None
            return self.status()
        if action in ("events_status", "events_save"):
            if self._paths is None:
                raise ValueError("Event preference storage is unavailable")
            from .event_settings import event_settings_command
            runtime = self._runtime
            observed = runtime.status() if runtime is not None else {}
            event_status = observed.get("event_settings", {})
            requested_media = value.get("mode", "normal") == "media"
            active_media = (event_status.get("media_mode", observed.get("media_mode") is True)
                            if isinstance(event_status, dict) else observed.get("media_mode") is True)
            effective = (event_status.get("effective") if isinstance(event_status, dict)
                         and active_media is requested_media else None)
            result = event_settings_command(self._paths[1], action,
                {key: item for key, item in value.items() if key not in ("id", "action")}, effective=effective)
            if action == "events_status":
                return result
            response = self.status()
            # The receipt belongs to the requested mode even if the user changed
            # the next-start mode while the queued preference write completed.
            response["runtime"]["event_settings"] = result
            response["restart_required"] = response["restart_required"] or result["restart_required"]
            self._event("status", status=response)
            return response
        if action.startswith("accounts_"):
            return self._account_command(action, value)
        if action.startswith("official_"):
            return self._official_command(action, value)
        runtime = self._ready_runtime()
        if action == "save_options":
            options = self._options()
            for name in ("media_mode", "download_missing_resources"):
                if name in value:
                    if type(value[name]) is not bool:
                        raise ValueError("Invalid option switch")
                    options[name] = value[name]
            if "language" in value:
                from .language_settings import validate_settings
                validate_settings({"schema": 1, "language": value["language"]})
                options["language"] = value["language"]
            if "interface_language" in value:
                if value["interface_language"] not in ("system", "ko", "ja", "en"):
                    raise ValueError("Invalid interface language")
                options["interface_language"] = value["interface_language"]
            _atomic_json(self._paths[1] / "ios-host.json", options)
        elif action.startswith("save_"):
            self._save(action, value.get("settings"))
        else:
            library = runtime._library
            if action == "resources_preview":
                return library.catalog_summary("ios")
            if action == "resources_download":
                parallelism = value.get("parallelism", 4)
                if type(parallelism) is not int or parallelism not in (1, 2, 4, 8):
                    raise ValueError("Invalid download parallelism")
                return library.start_download("ios", parallelism=parallelism)
            if action == "resources_cancel":
                identifier = value.get("job_id")
                if not isinstance(identifier, str) or not 1 <= len(identifier) <= 64:
                    raise ValueError("Invalid resource job identifier")
                return library.cancel(identifier)
            if action == "resources_import":
                path = Path(value.get("path", ""))
                approved = self._paths[1] / "imports"
                if not path.is_absolute() or path.suffix.lower() != ".zip":
                    raise ValueError("Import path was not approved by the native host")
                # Native container paths can retain ancestor aliases such as
                # /var while startup canonicalizes data to /private/var. Resolve
                # only the owned parent; never follow the selected file itself.
                if _directory(path.parent) != approved:
                    raise ValueError("Import path was not approved by the native host")
                directory = os.open(approved, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                try:
                    fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
                finally:
                    os.close(directory)
                incoming = os.fdopen(fd, "rb")
                try:
                    info = os.fstat(incoming.fileno())
                    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not 0 < info.st_size <= MAX_ARCHIVE_BYTES:
                        raise ValueError("Import source differs")
                    return self._archive(library, action, incoming)
                except Exception:
                    incoming.close()
                    raise
            return self._archive(library, action)
        result = self.status(); self._event("status", status=result); return result

    def command(self, raw_json):
        identifier = None
        value = None
        try:
            value = _decode(raw_json)
            if not isinstance(value, dict):
                raise ValueError("A command object is required")
            identifier = value.get("id")
            supplied_identifier = identifier
            identifier = None
            if supplied_identifier is not None and not (type(supplied_identifier) is int and 0 <= supplied_identifier <= 2**53 - 1 or type(supplied_identifier) is str and 0 < len(supplied_identifier.encode("utf-8")) <= 64):
                raise ValueError("Invalid command identifier")
            identifier = supplied_identifier
            with self._commands:
                result = self._dispatch(value)
            return _json({"id": identifier, "ok": True, "result": result})
        except Exception as error:
            code = "invalid_command" if isinstance(error, (ValueError, TypeError, KeyError, UnicodeError, RecursionError)) else "operation_failed"
            message = "The local server command could not be completed"
            if isinstance(value, dict) and str(value.get("action", "")).startswith(("accounts_", "official_")):
                import re
                if isinstance(error, ValueError) and re.fullmatch(r"account_[a-z0-9_]{1,64}", str(error)):
                    code = str(error)
                if str(value.get("action", "")).startswith("official_"):
                    # A password can itself resemble a diagnostic code. Export
                    # only service constants, never arbitrary exception text.
                    try:
                        from .official_import import ERROR_CODES
                    except ImportError:
                        ERROR_CODES = ()
                    safe = set(ERROR_CODES) | {"official_storage_unavailable", "official_response_invalid", "account_restart_required", "account_operation_busy"}
                    candidate = getattr(error, "code", None)
                    code = candidate if isinstance(candidate, str) and candidate in safe else str(error) if type(error) is ValueError and str(error) in safe else "operation_failed"
                message = ("게임을 완전히 종료하고 다시 연 뒤 게임 시작 전에 계정을 복원해 주세요."
                    if code == "account_restart_required" else "공식 계정 작업을 마치지 못했습니다. 상태를 확인해 주세요."
                    if str(value.get("action", "")).startswith("official_") else "계정 작업을 마치지 못했습니다. 목록을 새로 불러와 확인해 주세요.")
            if isinstance(value, dict) and value.get("action") in ("events_status", "events_save"):
                from .event_settings import ERROR_CODES
                candidate = getattr(error, "code", None)
                code = candidate if type(candidate) is str and candidate in ERROR_CODES else "operation_failed"
                message = "이벤트 설정을 저장하지 못했습니다. 저장 상태와 지원 목록을 확인해 주세요."
            return _json({"id": identifier, "ok": False, "error": {"code": code, "message": message}})


_HOST = _Host()


def start(bundle_dir, data_dir, resource_dir, *, ports=None):
    return _HOST.start(bundle_dir, data_dir, resource_dir, ports=ports)


def command(raw_json):
    return _HOST.command(raw_json)


def foreground():
    return _HOST.foreground()


def prepare_game_start():
    return _HOST.prepare_game_start()


def readiness():
    return _HOST.readiness()


def close():
    _HOST.close()
