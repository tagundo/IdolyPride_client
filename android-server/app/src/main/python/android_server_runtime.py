"""Chaquopy boundary for asset installation, Java AES and server lifetime."""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath
import shutil
import sys
import tempfile
import threading
from zipfile import ZipFile

_LOCK = threading.RLock()
_RUNTIME = None
_LAST_STATUS = {"running": False, "message": "서버 대기"}
_LAST_DIAGNOSTICS = {"running": False}
_TRANSLATION_STATUS = {"state": "absent"}
_PUBLIC_FOLDERS = {"protocol", "original-master", "master-json"}
_LOVE_METADATA_FILES = frozenset({"data/love-reference.json", "data/love-adv-proof.json", "data/love-compatibility.json", "data/love-legacy-rules.json",
    "data/licenses/love-reference-NOTICE.txt", "data/licenses/love-reference-AGPL-3.0.txt"})
_TUTORIAL_FILES = {"data/public-tutorial/manifest.json", "data/public-tutorial/tutorial-short.pb",
                   "data/public-tutorial/tutorial-full.pb"}
_STORY_FILES = {"data/public-story/manifest.json", "data/public-story/story-list-event.pb",
                "data/public-story/story-list-extra.pb"}
_OCTO_ARCHIVES = ({"data/public-octo/settings.json", "data/public-octo/manifest.pb"},
                  {"data/public-octo-ios/settings.json", "data/public-octo-ios/manifest.pb"})
_LATEST_OCTO_FILES = {"data/public-octo/legacy-manifest.pb", "data/public-octo-ios/legacy-manifest.pb"}
_OCTO_FILES = set().union(*_OCTO_ARCHIVES) | _LATEST_OCTO_FILES


def _digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def install_bundle(bundle: Path, files: Path, expected_sha256: str, expected_bytes=None) -> Path:
    """Install only bundled public data, preserving profiles and local state.

    Files are replaced individually via temporary files. The completion marker
    is written last, so an interrupted first install is safely retried.
    """
    bundle, files = Path(bundle), Path(files)
    if _digest(bundle) != expected_sha256:
        raise ValueError("Bundled server data failed its SHA-256 check")
    data = files / "data"
    with ZipFile(bundle) as source_archive:
        if "data/payload-manifest.json" in source_archive.namelist():
            info = source_archive.getinfo("data/payload-manifest.json")
            if info.file_size > 2*1024*1024:
                raise ValueError("public_payload_invalid")
            try:
                manifest = json.loads(source_archive.read(info))
            except (ValueError, UnicodeError):
                manifest = {}
            overlay = manifest.get("source_overlay", {}) if type(manifest) is dict else {}
            operation = overlay.get("operation") if type(overlay) is dict else None
            if operation == "latest-cohort-overlay-v1":
                from idoly_local.public_payload import install_payload
                install_payload(bundle, data, expected_sha256=expected_sha256, expected_bytes=expected_bytes)
                return data
            if operation not in (None, "love-source-overlay-v1"):
                raise ValueError("public_payload_policy_unsupported")
    marker = files / ".server-data-sha256"
    if marker.is_file() and marker.read_text(encoding="ascii").strip() == expected_sha256:
        required = [data / "protocol/idolypride-6.1.1.pb", data / "original-master/master-tag.json"]
        with ZipFile(bundle) as archive:
            octo_files = _OCTO_FILES.intersection(archive.namelist())
        for group in _OCTO_ARCHIVES:
            if octo_files.intersection(group) and not group.issubset(octo_files):
                raise ValueError("Bundled game resource catalog is incomplete")
        required.extend(files / name for name in octo_files)
        if all(path.is_file() for path in required):
            return data
    with ZipFile(bundle) as archive:
        entries = []
        names = set()
        for info in archive.infolist():
            if info.is_dir():
                continue
            path = PurePosixPath(info.filename)
            public = (len(path.parts) >= 3 and path.parts[0] == "data" and path.parts[1] in _PUBLIC_FOLDERS)
            public = public or info.filename == "data/payload-manifest.json"
            public = public or info.filename in _LOVE_METADATA_FILES
            public = public or info.filename == "data/latest-semantic-controls.json"
            public = public or info.filename == "data/public-fixtures/manifest.json"
            public = public or info.filename in _TUTORIAL_FILES
            public = public or info.filename in _STORY_FILES
            public = public or info.filename in _OCTO_FILES
            public = public or (len(path.parts) == 4 and path.parts[:3] == ("data", "public-fixtures", "responses")
                                and path.suffix == ".pb")
            if (path.is_absolute() or ".." in path.parts or "\\" in info.filename
                    or not public or info.filename in names):
                raise ValueError("Bundled data contains a non-public or unsafe path")
            names.add(info.filename)
            destination = (files / Path(*path.parts)).resolve()
            if not destination.is_relative_to(files.resolve()):
                raise ValueError("Bundled data escaped the app's private storage")
            entries.append((info, destination))
        if not {"data/protocol/idolypride-6.1.1.pb", "data/original-master/master-tag.json"}.issubset(names):
            raise ValueError("Bundled data is missing the schema or master archive")
        for group in _OCTO_ARCHIVES:
            if names.intersection(group) and not group.issubset(names):
                raise ValueError("Bundled game resource catalog is incomplete")
        for info, destination in entries:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".server-data-", delete=False) as stream:
                temporary = Path(stream.name)
                try:
                    with archive.open(info) as incoming:
                        shutil.copyfileobj(incoming, stream, length=64 * 1024)
                except BaseException:
                    temporary.unlink(missing_ok=True)
                    raise
            try:
                os.replace(temporary, destination)
            finally:
                temporary.unlink(missing_ok=True)
    files.mkdir(parents=True, exist_ok=True)
    marker.write_text(expected_sha256 + "\n", encoding="ascii")
    return data


def _copy_asset(assets, destination: Path, expected_sha256: str) -> None:
    if destination.is_file() and _digest(destination) == expected_sha256:
        return
    from java import jarray, jbyte

    destination.parent.mkdir(parents=True, exist_ok=True)
    incoming = assets.open("ServerData.zip")
    with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".server-zip-", delete=False) as stream:
        temporary = Path(stream.name)
        try:
            buffer = jarray(jbyte)(64 * 1024)
            while True:
                count = incoming.read(buffer)
                if count < 0:
                    break
                if count:
                    stream.write(memoryview(buffer).cast("B")[:count])
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        finally:
            incoming.close()
    try:
        if _digest(temporary) != expected_sha256:
            raise ValueError("Bundled server ZIP failed its SHA-256 check")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _register_app_startup_receipt(assets, build_config):
    """Read fixed signed-APK assets into immutable bytes, never writable cache."""
    from idoly_local.startup_receipt import MAX_RECEIPT_BYTES, register_startup_receipt
    unavailable = {"schema": 1, "available": False}
    incoming = None
    try:
        expected = str(getattr(build_config,"STARTUP_TRANSLATIONS_SHA256",""))
        size = int(getattr(build_config,"STARTUP_TRANSLATIONS_BYTES",0))
        if not re.fullmatch(r"[0-9a-f]{64}",expected) or not 0 < size <= MAX_RECEIPT_BYTES:
            raise ValueError("Absent or invalid optional receipt pin")
        from java import jarray, jbyte
        incoming = assets.open("startupTranslations.zip")
        buffer, chunks, count = jarray(jbyte)(64*1024), [], 0
        while True:
            length = incoming.read(buffer)
            if length < 0: break
            if length:
                count += length
                if count > size: raise ValueError("Optional receipt asset exceeds pin")
                chunks.append(memoryview(buffer).cast("B")[:length].tobytes())
        raw = b"".join(chunks)
        if len(raw) != size: raise ValueError("Optional receipt asset is truncated")
        return register_startup_receipt(raw,expected_sha256=expected,expected_bytes=size,platform="android")
    except Exception:
        register_startup_receipt(b"",expected_sha256="",expected_bytes=0,platform="android")
        return unavailable
    finally:
        if incoming is not None:
            try: incoming.close()
            except Exception: pass


def _install_bundled_translations(assets, build_config, files, data, resource_cache_dir, log):
    """Read the separate optional asset only during server startup."""
    from idoly_local.bundled_translations import MAX_BUNDLE, install_translation_bundle

    expected = str(getattr(build_config, "BUNDLED_TRANSLATIONS_SHA256", ""))
    size = int(getattr(build_config, "BUNDLED_TRANSLATIONS_BYTES", 0))
    if not expected and size == 0:
        return {"state": "absent"}
    if not re.fullmatch(r"[0-9a-f]{64}", expected) or not 0 < size <= MAX_BUNDLE:
        raise ValueError("Bundled translation identity is invalid")
    destination = files / ("bundled-translations-" + expected + ".zip")
    if destination.is_symlink() or (destination.exists() and not destination.is_file()):
        raise ValueError("Bundled translation cache is not a regular file")
    if not (destination.is_file() and destination.stat().st_size == size and _digest(destination) == expected):
        from java import jarray, jbyte

        destination.parent.mkdir(parents=True, exist_ok=True)
        incoming = assets.open("bundledTranslations.zip")
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".translations-zip-", delete=False) as output:
                temporary = Path(output.name)
                buffer, digest, count = jarray(jbyte)(64 * 1024), hashlib.sha256(), 0
                while True:
                    length = incoming.read(buffer)
                    if length < 0:
                        break
                    if length:
                        count += length
                        if count > size:
                            raise ValueError("Bundled translation asset exceeds its declared size")
                        chunk = memoryview(buffer).cast("B")[:length]
                        digest.update(chunk); output.write(chunk)
                output.flush(); os.fsync(output.fileno())
            if count != size or digest.hexdigest() != expected:
                raise ValueError("Bundled translation asset failed its digest check")
            os.replace(temporary, destination)
        finally:
            active_error = sys.exc_info()[0] is not None
            try:
                incoming.close()
            except BaseException:
                if not active_error:
                    raise
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
    selected_root = Path(resource_cache_dir) if resource_cache_dir is not None else data
    from idoly_local.resource_translation_runtime import validate_prepared_translations

    _register_app_startup_receipt(assets,build_config)
    return install_translation_bundle(destination, selected_root, expected_sha256=expected,
        expected_bytes=size, platform="android", log=log,
        validate_prepared=lambda prepared: validate_prepared_translations(prepared, data, platform="android"))


class _AndroidResourceResponse:
    """Normal platform HTTPS trust and streaming, with no redirect or TLS bypass."""

    def __init__(self, url, timeout):
        from java import jarray, jbyte, jclass

        self._connection = jclass("java.net.URL")(url).openConnection()
        self._connection.setInstanceFollowRedirects(False)
        milliseconds = max(1, min(30000, int(timeout * 1000)))
        self._connection.setConnectTimeout(milliseconds)
        self._connection.setReadTimeout(milliseconds)
        self._connection.setRequestProperty("Accept-Encoding", "identity")
        self._connection.setRequestProperty("User-Agent", "IdolyPride-Local-Resource-Cache")
        self._buffer = jarray(jbyte)(64 * 1024)
        self._read_chunk = jclass("game.qualiarts.idolypride.localserver.ResourceTransfers").readResourceChunk
        self._stream = None
        self._closed = False

    @property
    def status(self):
        if self._closed:
            raise OSError("Resource connection is closed")
        result = int(self._connection.getResponseCode())
        if self._closed:
            self._connection.disconnect()
            raise OSError("Resource connection is closed")
        return result

    @property
    def headers(self):
        if self._closed:
            raise OSError("Resource connection is closed")
        result = {}
        for name in ("Content-Length", "Content-Encoding"):
            value = self._connection.getHeaderField(name)
            if value is not None:
                result[name] = str(value)
        return result

    def geturl(self):
        if self._closed:
            raise OSError("Resource connection is closed")
        return str(self._connection.getURL().toString())

    def read(self, size):
        if self._closed:
            raise OSError("Resource connection is closed")
        if type(size) is not int or size < 0:
            raise ValueError("Resource reads require a bounded size")
        if size == 0:
            return b""
        if self._stream is None:
            self._stream = self._connection.getInputStream()
            if self._closed:
                try:
                    self._stream.close()
                finally:
                    self._connection.disconnect()
                raise OSError("Resource connection is closed")
        # TLS commonly returns only one record per InputStream.read. Fill a
        # bounded chunk in Java so each short read does not also pay Python
        # bridge, allocation, write, digest and quota-callback overhead.
        count = int(self._read_chunk(self._stream, self._buffer, min(size, len(self._buffer))))
        return b"" if count < 0 else memoryview(self._buffer).cast("B")[:count].tobytes()

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            if self._stream is not None:
                self._stream.close()
        finally:
            self._connection.disconnect()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def _fetch_resource(url, *, timeout):
    return _AndroidResourceResponse(url, timeout)


def start(files_dir, assets, callback, native_library_dir=None, experimental_main_live=False,
          download_missing_resources=True, media_mode=False, resource_cache_dir=None,
          shared_resource_dir=None):
    """Start the embedded loopback runtime; called on the service worker."""
    global _RUNTIME, _LAST_STATUS, _TRANSLATION_STATUS
    if type(download_missing_resources) is not bool:
        raise ValueError("Resource downloads must be an explicit boolean")
    if type(media_mode) is not bool:
        raise ValueError("Media mode must be an explicit boolean")
    if resource_cache_dir is not None and (not isinstance(resource_cache_dir, str)
            or not resource_cache_dir or "\0" in resource_cache_dir or not Path(resource_cache_dir).is_absolute()):
        raise ValueError("Resource storage must be an explicit absolute directory or private None")
    # Select the universal wheel's implementation before importing the engine.
    # Merely importing the asset installer must not change a host test process.
    os.environ["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"] = "python"
    with _LOCK:
        if _RUNTIME is not None and _RUNTIME.status().get("running"):
            return status_json()
        from java import jclass

        build_config = jclass("game.qualiarts.idolypride.localserver.BuildConfig")
        crypto = jclass("game.qualiarts.idolypride.localserver.CryptoBridge")
        files = Path(str(files_dir))
        expected = str(build_config.SERVER_DATA_SHA256)

        def log(message):
            callback.log(str(message))

        def aes_cbc(encrypt, key, iv, payload):
            result = crypto.aesCbc(bool(encrypt), key, iv, payload)
            return memoryview(result).cast("B").tobytes()

        runtime_entered = False
        preparation_stage = "catalog"
        try:
            log("서버 데이터 확인 중…")
            bundle = files / "bundled-server-data.zip"
            _copy_asset(assets, bundle, expected)
            data = install_bundle(bundle, files, expected, int(getattr(build_config, "SERVER_DATA_BYTES", 0)))
            preparation_stage = "resources"
            try:
                _TRANSLATION_STATUS = _install_bundled_translations(
                    assets, build_config, files, data, resource_cache_dir, log)
            except (OSError, ValueError) as translation_error:
                _record_pre_runtime_failure(files / "data", translation_error, "resources")
                _TRANSLATION_STATUS = {"state": "failed", "installed": False,
                                       "previous_files_preserved": True}
                log("번역 패키지를 설치하지 못했습니다. 기존 번역과 원본 자료는 변경하지 않았습니다.")
            preparation_stage = "catalog"
            from idoly_local.app_runtime import start as start_runtime

            live_options = {}
            if experimental_main_live:
                if native_library_dir is None:
                    raise ValueError("Experimental live library directory is unavailable")
                live_options = {"experimental_main_live": True,
                                "live_engine_library": Path(str(native_library_dir)) / "libidoly_live.so"}
            runtime_entered = True
            _RUNTIME = start_runtime(data, profile="sandbox", log_callback=log, aes_cbc=aes_cbc,
                                     download_missing_resources=download_missing_resources,
                                     media_mode=media_mode,
                                     resource_cache_dir=resource_cache_dir,
                                     shared_resource_dir=shared_resource_dir,
                                     resource_fetcher=_fetch_resource, **live_options)
            _LAST_STATUS = _RUNTIME.status()
            if _TRANSLATION_STATUS.get("state") != "absent":
                _LAST_STATUS["bundled_translations"] = dict(_TRANSLATION_STATUS)
            return json.dumps(_LAST_STATUS, ensure_ascii=False)
        except BaseException as error:
            _LAST_STATUS = {"running": False, "message": "서버를 시작하지 못했습니다", "error_type": type(error).__name__}
            if not runtime_entered:
                _LAST_STATUS.update(_record_pre_runtime_failure(files / "data", error, preparation_stage))
            log("서버 시작 오류: " + type(error).__name__)
            raise


def stop():
    global _RUNTIME, _LAST_STATUS, _LAST_DIAGNOSTICS
    with _LOCK:
        if _RUNTIME is not None:
            _RUNTIME.stop()
            _LAST_DIAGNOSTICS = _RUNTIME.diagnostics_snapshot()
            _LAST_STATUS = _RUNTIME.status()
            _RUNTIME = None
        _LAST_STATUS = dict(_LAST_STATUS, running=False)
        return json.dumps(_LAST_STATUS, ensure_ascii=False)


def shared_resources_json():
    """Private same-UID unified-game configuration; never an HTTP/UI export."""
    with _LOCK:
        configuration = (_RUNTIME.shared_resources_configuration() if _RUNTIME is not None
                         else {"schema": 1, "available": False})
        return json.dumps(configuration, ensure_ascii=False)


def status_json():
    with _LOCK:
        value = _RUNTIME.status() if _RUNTIME is not None else _LAST_STATUS
        if _TRANSLATION_STATUS.get("state") != "absent":
            value = dict(value, bundled_translations=dict(_TRANSLATION_STATUS))
        return json.dumps(dict(value, official_import=_official_public_status()), ensure_ascii=False)


def diagnostics_json():
    """Return bounded diagnostic events only; never open profiles or state.db."""
    with _LOCK:
        value = _RUNTIME.diagnostics_snapshot() if _RUNTIME is not None else _LAST_DIAGNOSTICS
        if _TRANSLATION_STATUS.get("state") != "absent":
            value = dict(value, bundled_translations=dict(_TRANSLATION_STATUS))
        return json.dumps(dict(value, official_import=_official_public_status()), ensure_ascii=False)


def _resource_library_reference():
    # Hold the lifecycle lock only to acquire the current object. Long archive
    # I/O must not prevent status, cancellation or stop from reaching the runtime.
    with _LOCK:
        library = getattr(_RUNTIME, "_library", None) if _RUNTIME is not None else None
        if library is None:
            raise ValueError("Resource server is not running")
        return library


def import_resources_fd(descriptor, platform):
    """Import one user-selected seekable PFD, retaining no Android activity/URI."""
    if type(descriptor) is not int or descriptor < 0 or platform not in ("android", "ios"):
        raise ValueError("Invalid resource import selection")
    library = _resource_library_reference()
    copied = os.dup(descriptor)
    try:
        os.lseek(copied, 0, os.SEEK_CUR)
        with os.fdopen(copied, "rb") as source:
            copied = -1
            source.seek(0)
            result = library.import_from(source, platform, kind="all")
        return json.dumps(result, ensure_ascii=False)
    finally:
        if copied >= 0:
            os.close(copied)


def cancel_resource_job(identifier):
    if not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", identifier):
        raise ValueError("Invalid resource cancellation")
    return json.dumps(_resource_library_reference().cancel(identifier), ensure_ascii=False)

# Native account management never shares the public loopback HTTP routes.
_MANAGEMENT_ACTIONS = frozenset({
    "accounts_status", "accounts_create", "accounts_clone", "accounts_select",
    "accounts_export", "accounts_preview", "accounts_import", "accounts_restore",
    "server_settings_status", "server_history_clear", "events_status", "events_save",
})


def _management_root(files_dir):
    if type(files_dir) is not str or not files_dir or "\0" in files_dir:
        raise ValueError("account_storage_invalid")
    files = Path(files_dir)
    if not files.is_absolute() or files.is_symlink() or not files.is_dir():
        raise ValueError("account_storage_invalid")
    root = files.resolve(strict=True) / "data"
    if root.is_symlink():
        raise ValueError("account_storage_invalid")
    return root


def _approved_account_input(root, value):
    import stat
    if type(value) is not str or "\0" in value:
        raise ValueError("account_import_path_invalid")
    path = Path(value)
    inbox = root / "account-management" / "inbox"
    if (not path.is_absolute() or path.is_symlink()
            or re.fullmatch(r"account-import-[0-9a-f]{32}\.zip", path.name) is None):
        raise ValueError("account_import_path_invalid")
    try:
        info = path.lstat()
        approved = inbox.resolve(strict=True)
        if ((root / "account-management").is_symlink() or inbox.is_symlink()
                or path.parent.resolve(strict=True) != approved or not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1 or not 0 < info.st_size <= 128 * 1024 * 1024):
            raise ValueError("account_import_path_invalid")
    except OSError:
        raise ValueError("account_import_path_invalid") from None
    return str(path)



def _record_pre_runtime_failure(root, error, stage):
    try:
        from idoly_local.app_runtime import record_startup_failure
        return record_startup_failure(root, error, stage=stage)
    except Exception:
        # Reporting cannot hide the original preparation failure.
        return {}


def _prepare_management_payload(root, assets):
    """Prepare only SHA-bound public inputs; never starts listeners or creates a user."""
    if assets is None or ((root / "protocol" / "idolypride-6.1.1.pb").is_file()
                          and (root / "master-json").is_dir()):
        return
    from java import jclass
    build_config = jclass("game.qualiarts.idolypride.localserver.BuildConfig")
    expected = str(build_config.SERVER_DATA_SHA256)
    if re.fullmatch(r"[0-9a-f]{64}", expected) is None:
        raise ValueError("account_payload_identity_invalid")
    files = root.parent
    bundle = files / "bundled-server-data.zip"
    try:
        _copy_asset(assets, bundle, expected)
        prepared = install_bundle(bundle, files, expected, int(getattr(build_config, "SERVER_DATA_BYTES", 0)))
        if prepared.resolve() != root.resolve():
            raise ValueError("account_storage_invalid")
    except BaseException as error:
        _record_pre_runtime_failure(root, error, "catalog")
        raise

def _event_settings_native(root, action, payload, active):
    """Save only configuration; never touches account progress or server lifecycle."""
    from idoly_local.event_settings import event_settings_command, EventSettingsError, ERROR_CODES
    effective = None
    running_settings = active.get("event_settings")
    requested_media = payload.get("mode", "normal") == "media"
    active_media = (running_settings.get("media_mode", active.get("media_mode") is True)
                    if type(running_settings) is dict else active.get("media_mode") is True)
    if (active.get("running") is True and type(running_settings) is dict
            and active_media is requested_media):
        effective = running_settings.get("effective")
    try:
        observed = event_settings_command(root, action, payload, effective=effective)
    except EventSettingsError as error:
        code = getattr(error, "code", None)
        raise ValueError(code if code in ERROR_CODES else "event_settings_command_invalid") from None
    except Exception:
        raise ValueError("event_settings_io") from None
    if (type(observed) is not dict or observed.get("schema") != 1
            or type(observed.get("saved")) is not dict or type(observed.get("catalog")) is not dict):
        raise ValueError("event_settings_response_invalid")
    return {"schema": 1, "ok": True, "action": action, "event_settings": observed}


def management_command_json(files_dir, action, payload_json="{}", assets=None):
    """Trusted Android bridge. A selected account applies on the next startup."""
    try:
        if (type(action) is not str or action not in _MANAGEMENT_ACTIONS
                or type(payload_json) is not str
                or len(payload_json.encode("utf-8")) > (65536 if action == "events_save" else 8192)):
            raise ValueError("account_request_invalid")
        try:
            payload = json.loads(payload_json)
        except ValueError:
            raise ValueError("account_request_invalid") from None
        if type(payload) is not dict:
            raise ValueError("account_request_invalid")
        root = _management_root(files_dir)
        with _LOCK:
            if action.startswith("accounts_") and action != "accounts_status":
                _prepare_management_payload(root, assets)
            active = _RUNTIME.status() if _RUNTIME is not None else {"running": False}
            active_account = {"running": active.get("running") is True,
                              "mode": "media" if active.get("media_mode") is True else "normal",
                              "profile": active.get("profile")}
            if action in ("events_status", "events_save"):
                result = _event_settings_native(root, action, payload, active)
            elif action in ("server_settings_status", "server_history_clear"):
                if payload:
                    raise ValueError("account_request_invalid")
                from idoly_local.app_runtime import server_settings_status, clear_server_history
                if action == "server_history_clear":
                    if _RUNTIME is not None:
                        _RUNTIME.clear_history()
                    else:
                        clear_server_history(root)
                observed = _RUNTIME.status() if _RUNTIME is not None else server_settings_status(root)
                result = {"schema": 1, "ok": True, "action": action,
                          "settings": {key: observed.get(key) for key in ("durable_history", "startup_checks")}}
            else:
                if action == "accounts_preview":
                    payload = dict(payload, path=_approved_account_input(root, payload.get("path")))
                replaces = action == "accounts_restore" or (
                    action == "accounts_import" and payload.get("replace") is True)
                if (replaces and active_account["running"]
                        and payload.get("mode") == active_account["mode"]
                        and payload.get("profile") == active_account["profile"]):
                    raise ValueError("account_active_restart_required")
                os.environ["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"] = "python"
                from idoly_local.account_manager import account_command
                result = account_command(root, action, payload)
                if type(result) is not dict or result.get("ok") is not True:
                    raise ValueError("account_response_invalid")
                if action == "accounts_status":
                    from idoly_local.app_runtime import server_settings_status
                    observed = _RUNTIME.status() if _RUNTIME is not None else server_settings_status(root)
                    result = dict(result, settings={key: observed.get(key) for key in ("durable_history", "startup_checks")})
            result = dict(result, active=active_account)
            encoded = json.dumps(result, ensure_ascii=False, allow_nan=False)
            if len(encoded.encode("utf-8")) > 2 * 1024 * 1024:
                raise ValueError("account_response_invalid")
            return encoded
    except (ValueError, OSError) as error:
        code = str(error)
        if re.fullmatch(r"[a-z][a-z0-9_]{0,95}", code) is None:
            code = "account_operation_failed"
        return json.dumps({"schema": 1, "ok": False, "error": code}, ensure_ascii=False)
    except Exception:
        return json.dumps({"schema": 1, "ok": False, "error": "account_operation_failed"})


# Transfer credentials stay on this direct native boundary, never in management
# request logs, saved preferences, generic status, diagnostics, or public routes.
_OFFICIAL_MANAGER = None
_OFFICIAL_ROOT = None
_OFFICIAL_ACTIONS = frozenset({"official_inspect", "official_fetch", "official_apply", "official_cancel", "official_status"})
_OFFICIAL_STATES = frozenset({"idle", "checking", "verified", "fetching", "ready", "completed", "failed", "cancelled"})
_OFFICIAL_STAGES = frozenset({"idle", "preparing", "checking", "verifying", "verified", "transferring", "firebase", "login", "master", "account", "collected", "fetching", "catalog_check", "staging", "ready", "applying", "completed", "cancelled", "failed"})
_OFFICIAL_HOST_ERRORS = frozenset({"official_request_invalid", "official_active_restart_required", "official_response_invalid",
                                 "official_operation_failed", "official_status_failed", "official_job_missing", "official_storage_changed"})


def _official_idle():
    return {"schema": 1, "state": "idle", "job_id": None, "progress": "idle", "error_code": None,
            "counts": {"cards": 0, "items": 0, "photos": 0}, "busy": False, "expires_in_seconds": 0}


def _official_error_code(error):
    # Never echo an arbitrary exception string: it may contain a credential.
    value = str(error)
    if value in _OFFICIAL_HOST_ERRORS:
        return value
    try:
        from idoly_local.official_import import ERROR_CODES
        if value in ERROR_CODES:
            return value
    except (ImportError, AttributeError, TypeError):
        pass
    return "official_operation_failed"


def _official_public_status():
    if _OFFICIAL_MANAGER is None:
        return _official_idle()
    try:
        raw = _OFFICIAL_MANAGER.status(public=True)
        if type(raw) is not dict or raw.get("state") not in _OFFICIAL_STATES:
            raise ValueError("official_response_invalid")
        result = _official_idle()
        result["state"] = raw["state"]
        identifier = raw.get("job_id")
        if identifier is not None and (type(identifier) is not str or re.fullmatch(r"[0-9a-f]{32}", identifier) is None):
            raise ValueError("official_response_invalid")
        result["job_id"] = identifier
        progress = raw.get("progress")
        if type(progress) is str and progress in _OFFICIAL_STAGES:
            result["progress"] = progress
        code = raw.get("error_code")
        if code is not None:
            result["error_code"] = _official_error_code(ValueError(code))
        counts = raw.get("counts")
        if type(counts) is dict:
            for name in ("cards", "items", "photos"):
                count = counts.get(name, 0)
                if type(count) is int and 0 <= count <= 1000000000:
                    result["counts"][name] = count
        result["busy"] = raw.get("busy") is True
        expiry = raw.get("expires_in_seconds", 0)
        result["expires_in_seconds"] = expiry if type(expiry) is int and 0 <= expiry <= 600 else 0
        return result
    except Exception:
        return {"schema": 1, "state": "unavailable", "error_code": "official_status_failed", "busy": False}


def _configure_official_codec():
    from java import jclass
    from idoly_local import codec
    crypto = jclass("game.qualiarts.idolypride.localserver.CryptoBridge")

    def aes_cbc(encrypt, key, iv, payload):
        result = crypto.aesCbc(bool(encrypt), key, iv, payload)
        return memoryview(result).cast("B").tobytes()

    codec.configure_aes(aes_cbc)


def _official_result_warnings(action, result):
    """Committed success stays success; forward only fixed local follow-up notices."""
    output = dict(result)
    warnings = output.pop("warning_codes", None)
    refresh = output.pop("status_refresh_required", None)
    if action == "official_apply":
        allowed = {"account_temporary_cleanup_pending", "account_status_refresh_required"}
        if warnings is not None:
            output["warning_codes"] = list(dict.fromkeys(code for code in warnings[:8]
                if type(code) is str and code in allowed)) if type(warnings) in (list, tuple) else []
        if refresh is not None:
            output["status_refresh_required"] = refresh is True
    return output


def _validate_official_payload(action, payload):
    fields = {"official_inspect": {"user_id", "password", "platform"}, "official_fetch": {"job_id"},
              "official_apply": {"job_id", "profile", "replace", "expected_revision"},
              "official_cancel": {"job_id"}, "official_status": set()}
    if set(payload) != fields[action]:
        raise ValueError("official_request_invalid")
    if action == "official_inspect":
        user, password = payload.get("user_id"), payload.get("password")
        if (type(user) is not str or re.fullmatch(r"[A-Za-z0-9_-]{1,64}", user) is None
                or type(password) is not str or not 1 <= len(password) <= 128
                or password != password.strip(" ") or any(ord(char) < 32 or ord(char) > 126 for char in password)
                or payload.get("platform") not in ("android", "ios")):
            raise ValueError("official_request_invalid")
    elif action != "official_status":
        identifier = payload.get("job_id")
        if type(identifier) is not str or re.fullmatch(r"[0-9a-f]{32}", identifier) is None:
            raise ValueError("official_request_invalid")
    if action == "official_apply":
        profile, revision = payload.get("profile"), payload.get("expected_revision")
        if (type(profile) is not str or not profile or not profile.isprintable() or "/" in profile or "\\" in profile
                or len(profile.encode("utf-8")) > 64 or type(payload.get("replace")) is not bool
                or (payload["replace"] is True and (type(revision) is not str or re.fullmatch(r"[0-9a-f]{64}", revision) is None))
                or (payload["replace"] is False and revision is not None)):
            raise ValueError("official_request_invalid")


def official_command_json(files_dir, action, payload_json="{}", assets=None):
    """Direct native transfer wizard. No credentials enter generic snapshots."""
    global _OFFICIAL_MANAGER, _OFFICIAL_ROOT
    payload = None
    try:
        if (type(action) is not str or action not in _OFFICIAL_ACTIONS or type(payload_json) is not str
                or len(payload_json.encode("utf-8")) > 8192):
            raise ValueError("official_request_invalid")
        try:
            payload = json.loads(payload_json)
        except ValueError:
            raise ValueError("official_request_invalid") from None
        if type(payload) is not dict:
            raise ValueError("official_request_invalid")
        _validate_official_payload(action, payload)
        root = _management_root(files_dir)
        with _LOCK:
            if _OFFICIAL_MANAGER is not None and _OFFICIAL_ROOT != root:
                raise ValueError("official_storage_changed")
            active = _RUNTIME.status() if _RUNTIME is not None else {"running": False}
            if action == "official_apply" and payload.get("replace") is True and active.get("running") is True:
                raise ValueError("official_active_restart_required")
            if action == "official_status" and _OFFICIAL_MANAGER is None:
                if payload:
                    raise ValueError("official_request_invalid")
                result = {"action": action, "job": _official_idle()}
            else:
                if _OFFICIAL_MANAGER is None:
                    if action != "official_inspect":
                        raise ValueError("official_job_missing")
                    _prepare_management_payload(root, assets)
                    os.environ["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"] = "python"
                    _configure_official_codec()
                    from idoly_local.official_import import OfficialImportManager
                    _OFFICIAL_MANAGER = OfficialImportManager(root)
                    _OFFICIAL_ROOT = root
                elif action in ("official_inspect", "official_fetch", "official_apply"):
                    _configure_official_codec()
                result = _OFFICIAL_MANAGER.command(action, payload)
            if type(result) is not dict or type(result.get("job")) is not dict or result.get("action") != action:
                raise ValueError("official_response_invalid")
            result = dict(_official_result_warnings(action, result), schema=1, ok=True, active={"running": active.get("running") is True,
                          "mode": "media" if active.get("media_mode") is True else "normal", "profile": active.get("profile")})
            encoded = json.dumps(result, ensure_ascii=False, allow_nan=False)
            if len(encoded.encode("utf-8")) > 2 * 1024 * 1024:
                raise ValueError("official_response_invalid")
            return encoded
    except Exception as error:
        return json.dumps({"schema": 1, "ok": False, "error": _official_error_code(error)}, ensure_ascii=False)
    finally:
        if type(payload) is dict:
            payload.pop("password", None)
            payload.pop("user_id", None)
        payload_json = None
