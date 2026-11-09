"""Chaquopy boundary for asset installation, Java AES and server lifetime."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import tempfile
import threading
from zipfile import ZipFile

# Chaquopy receives the universal protobuf wheel, which needs no native module.
os.environ["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"] = "python"

_LOCK = threading.RLock()
_RUNTIME = None
_LAST_STATUS = {"running": False, "message": "서버 대기"}
_PUBLIC_FOLDERS = {"protocol", "original-master", "master-json"}


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


def start(files_dir, assets, callback):
    """Start the embedded loopback runtime; called on the service worker."""
    global _RUNTIME, _LAST_STATUS
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

            _RUNTIME = start_runtime(data, profile="sandbox", log_callback=log, aes_cbc=aes_cbc)
            _LAST_STATUS = _RUNTIME.status()
            return json.dumps(_LAST_STATUS, ensure_ascii=False)
        except BaseException as error:
            _LAST_STATUS = {"running": False, "message": "서버를 시작하지 못했습니다", "error_type": type(error).__name__}
            log("서버 시작 오류: " + type(error).__name__)
            raise


def stop():
    global _RUNTIME, _LAST_STATUS
    with _LOCK:
        if _RUNTIME is not None:
            _RUNTIME.stop()
            _LAST_STATUS = _RUNTIME.status()
            _RUNTIME = None
        _LAST_STATUS = dict(_LAST_STATUS, running=False)
        return json.dumps(_LAST_STATUS, ensure_ascii=False)


def status_json():
    with _LOCK:
        value = _RUNTIME.status() if _RUNTIME is not None else _LAST_STATUS
        return json.dumps(value, ensure_ascii=False)
