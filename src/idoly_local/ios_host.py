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


def _regular(path, *, maximum=MAX_ARCHIVE_BYTES):
    info = Path(path).lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not 0 < info.st_size <= maximum:
        raise ValueError("A bounded regular file is required")
    return info


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
        observed["logs"] = [str(x)[:512] for x in observed.get("logs", [])[-20:]]
        restart = effective is not None and any(options.get(key) != effective.get(key)
            for key in ("media_mode", "download_missing_resources", "language"))
        media = observed.get("media_options", {})
        if media.get("effective_settings") is not None and media.get("settings") != media["effective_settings"]:
            restart = True
        result = {"state": state, "running": state == "ready" and observed.get("running") is True,
            "options": options, "effective_options": effective, "restart_required": restart,
            "invalid_options_file": invalid, "runtime": observed, "last_error": error,
            "resource_operation": operation, "paths": None}
        if paths is not None:
            result["paths"] = {"imports": str(paths[1] / "imports"), "exports": str(paths[1] / "tmp/exports")}
        # Diagnostic histories may be large; public settings stay available.
        try:
            _json(result)
        except ValueError:
            result["runtime"] = _thin_observation(observed, ("running", "grpc_address", "asset_url")) or {}
            result["runtime"].update(_thin_transfers(observed))
            result["diagnostics_truncated"] = True
            # Retaining an unbounded language/renderer report here would make
            # the fallback overflow too, hiding the counters again. Prefer the
            # complete field when it fits, then its validated control settings.
            for key in ("presentation", "playback", "media_options", "language"):
                if key not in observed:
                    continue
                value = observed[key]
                settings = ({k: v for k, v in value.items() if k in (
                    "settings", "effective_settings", "invalid_settings_file", "effective_language")}
                    if isinstance(value, dict) else {})
                for candidate in (value, settings):
                    result["runtime"][key] = candidate
                    try:
                        _json(result)
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
            self._installer(bundle / "ServerData.zip", data, self._log)
            self._translations(bundle / "ServerData.zip", resources, self._log, data_dir=data)
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
            return {"state": result["state"], "running": result["running"],
                    "effective_options": result["effective_options"], "client_data": prepared}

    def readiness(self):
        result = self.status()
        return {"state": result["state"], "running": result["running"]}

    def close(self):
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

    def _dispatch(self, value):
        action = value.get("action")
        fields = {"status": set(), "save_options": {"media_mode", "download_missing_resources", "language", "interface_language"},
            "save_presentation": {"settings"}, "save_playback": {"settings"}, "save_media": {"settings"},
            "resources_preview": set(), "resources_download": {"parallelism"}, "resources_cancel": {"job_id"},
            "resources_import": {"path"}, "resources_export": set()}
        if action not in fields or value.keys() - {"id", "action"} - fields[action]:
            raise ValueError("Unknown command or fields")
        if action == "status":
            return self.status()
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
                if not path.is_absolute() or path.suffix.lower() != ".zip" or path.parent != approved:
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
            return _json({"id": identifier, "ok": False, "error": {"code": code, "message": "The local server command could not be completed"}})


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
