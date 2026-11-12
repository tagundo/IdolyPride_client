"""Chaquopy boundary for asset installation, Java AES and server lifetime."""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath
import shutil
import tempfile
import threading
from zipfile import ZipFile

_LOCK = threading.RLock()
_RUNTIME = None
_LAST_STATUS = {"running": False, "message": "서버 대기"}
_LAST_DIAGNOSTICS = {"running": False}
_PUBLIC_FOLDERS = {"protocol", "original-master", "master-json"}
_TUTORIAL_FILES = {"data/public-tutorial/manifest.json", "data/public-tutorial/tutorial-short.pb",
                   "data/public-tutorial/tutorial-full.pb"}
_STORY_FILES = {"data/public-story/manifest.json", "data/public-story/story-list-event.pb",
                "data/public-story/story-list-extra.pb"}
_OCTO_ARCHIVES = ({"data/public-octo/settings.json", "data/public-octo/manifest.pb"},
                  {"data/public-octo-ios/settings.json", "data/public-octo-ios/manifest.pb"})
_OCTO_FILES = set().union(*_OCTO_ARCHIVES)


def _digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def install_bundle(bundle: Path, files: Path, expected_sha256: str) -> Path:
    """Install only bundled public data, preserving profiles and local state.

    Files are replaced individually via temporary files. The completion marker
    is written last, so an interrupted first install is safely retried.
    """
    bundle, files = Path(bundle), Path(files)
    if _digest(bundle) != expected_sha256:
        raise ValueError("Bundled server data failed its SHA-256 check")
    data = files / "data"
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
        if self._stream is None:
            self._stream = self._connection.getInputStream()
            if self._closed:
                try:
                    self._stream.close()
                finally:
                    self._connection.disconnect()
                raise OSError("Resource connection is closed")
        count = int(self._stream.read(self._buffer, 0, min(size, len(self._buffer))))
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
          download_missing_resources=True, media_mode=False, resource_cache_dir=None):
    """Start the embedded loopback runtime; called on the service worker."""
    global _RUNTIME, _LAST_STATUS
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

        try:
            log("서버 데이터 확인 중…")
            bundle = files / "bundled-server-data.zip"
            _copy_asset(assets, bundle, expected)
            data = install_bundle(bundle, files, expected)
            from idoly_local.app_runtime import start as start_runtime

            live_options = {}
            if experimental_main_live:
                if native_library_dir is None:
                    raise ValueError("Experimental live library directory is unavailable")
                live_options = {"experimental_main_live": True,
                                "live_engine_library": Path(str(native_library_dir)) / "libidoly_live.so"}
            _RUNTIME = start_runtime(data, profile="sandbox", log_callback=log, aes_cbc=aes_cbc,
                                     download_missing_resources=download_missing_resources,
                                     media_mode=media_mode,
                                     resource_cache_dir=resource_cache_dir,
                                     resource_fetcher=_fetch_resource, **live_options)
            _LAST_STATUS = _RUNTIME.status()
            return json.dumps(_LAST_STATUS, ensure_ascii=False)
        except BaseException as error:
            _LAST_STATUS = {"running": False, "message": "서버를 시작하지 못했습니다", "error_type": type(error).__name__}
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


def status_json():
    with _LOCK:
        value = _RUNTIME.status() if _RUNTIME is not None else _LAST_STATUS
        return json.dumps(value, ensure_ascii=False)


def diagnostics_json():
    """Return bounded diagnostic events only; never open profiles or state.db."""
    with _LOCK:
        value = _RUNTIME.diagnostics_snapshot() if _RUNTIME is not None else _LAST_DIAGNOSTICS
        return json.dumps(value, ensure_ascii=False)


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
