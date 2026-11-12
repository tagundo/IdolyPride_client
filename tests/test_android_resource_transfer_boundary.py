"""Host FD/lifecycle checks only; no Android provider, server or network runs."""
import importlib.util
import json
import os
from pathlib import Path
import threading
import hashlib
import sys
from types import SimpleNamespace
from zipfile import ZipFile

import pytest


@pytest.fixture
def boundary():
    path = Path(__file__).resolve().parents[1] / "android-server/app/src/main/python/android_server_runtime.py"
    spec = importlib.util.spec_from_file_location("android_resource_boundary", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_seekable_fd_is_duplicated_closed_and_import_does_not_hold_lifecycle_lock(boundary, tmp_path):
    selected = tmp_path / "selected.zip"
    selected.write_bytes(b"selected archive bytes")
    lock_acquired = []

    class Library:
        def import_from(self, source, platform, kind):
            def probe():
                acquired = boundary._LOCK.acquire(timeout=.1)
                lock_acquired.append(acquired)
                if acquired:
                    boundary._LOCK.release()
            worker = threading.Thread(target=probe)
            worker.start(); worker.join(timeout=.2)
            assert platform == "ios" and kind == "all"
            assert source.seekable() and source.read() == b"selected archive bytes"
            self.copied = source.fileno()
            return {"state": "completed", "imported_files": 1}

    library = Library()
    boundary._RUNTIME = SimpleNamespace(_library=library)
    with selected.open("rb") as source:
        result = json.loads(boundary.import_resources_fd(source.fileno(), "ios"))
        assert result["state"] == "completed" and lock_acquired == [True]
        os.fstat(source.fileno())
        with pytest.raises(OSError):
            os.fstat(library.copied)
    assert selected.read_bytes() == b"selected archive bytes"


def test_unseekable_fd_fails_before_import_and_closes_only_duplicate(boundary, monkeypatch):
    class Library:
        def import_from(self, *args):
            pytest.fail("A pipe must not enter archive import")
    boundary._RUNTIME = SimpleNamespace(_library=Library())
    duplicates = []
    actual_dup = os.dup
    def duplicate(fd):
        result = actual_dup(fd)
        duplicates.append(result)
        return result
    monkeypatch.setattr(boundary.os, "dup", duplicate)
    read_fd, write_fd = os.pipe()
    try:
        with pytest.raises(OSError):
            boundary.import_resources_fd(read_fd, "android")
        os.fstat(read_fd)
        with pytest.raises(OSError):
            os.fstat(duplicates[0])
    finally:
        os.close(read_fd); os.close(write_fd)


def test_cancel_identifier_is_whitelisted_and_stopped_runtime_is_unavailable(boundary):
    calls = []
    class Library:
        def cancel(self, identifier):
            calls.append(identifier)
            return {"job_id": identifier, "state": "cancelling"}
    boundary._RUNTIME = SimpleNamespace(_library=Library())
    assert json.loads(boundary.cancel_resource_job("a" * 32))["state"] == "cancelling"
    for value in ("", "../other", "job;other", "x" * 65, None):
        with pytest.raises(ValueError):
            boundary.cancel_resource_job(value)
    assert calls == ["a" * 32]
    boundary._RUNTIME = None
    with pytest.raises(ValueError):
        boundary.cancel_resource_job("known-job")
    for descriptor, platform in ((True, "android"), (-1, "android"), (1, "other")):
        with pytest.raises(ValueError):
            boundary.import_resources_fd(descriptor, platform)


@pytest.mark.parametrize("platforms", [("public-octo",), ("public-octo", "public-octo-ios")])
def test_public_platform_catalog_install_and_marker_reopen_preserve_account(boundary, tmp_path, platforms):
    bundle = tmp_path / "bundle.zip"
    with ZipFile(bundle, "w") as archive:
        archive.writestr("data/protocol/idolypride-6.1.1.pb", b"public schema")
        archive.writestr("data/original-master/master-tag.json", b"public master")
        for platform in platforms:
            archive.writestr("data/" + platform + "/settings.json", b"public settings")
            archive.writestr("data/" + platform + "/manifest.pb", b"public manifest")
    files = tmp_path / "files"
    (files / "data").mkdir(parents=True)
    account = files / "data/state.db"
    account.write_bytes(b"preserve account")
    expected = hashlib.sha256(bundle.read_bytes()).hexdigest()
    for _ in range(2):
        root = boundary.install_bundle(bundle, files, expected)
        for platform in platforms:
            assert (root / platform / "manifest.pb").read_bytes() == b"public manifest"
    assert account.read_bytes() == b"preserve account"


def test_incomplete_secondary_catalog_fails_before_installing_any_files(boundary, tmp_path):
    bundle = tmp_path / "incomplete.zip"
    with ZipFile(bundle, "w") as archive:
        archive.writestr("data/protocol/idolypride-6.1.1.pb", b"public schema")
        archive.writestr("data/original-master/master-tag.json", b"public master")
        archive.writestr("data/public-octo-ios/settings.json", b"missing manifest")
    files = tmp_path / "files"
    with pytest.raises(ValueError, match="incomplete"):
        boundary.install_bundle(bundle, files, hashlib.sha256(bundle.read_bytes()).hexdigest())
    assert not files.exists()


@pytest.mark.parametrize("public", [False, True])
def test_start_passes_explicit_resource_root_without_moving_private_data(boundary, tmp_path, monkeypatch, public):
    import idoly_local.app_runtime as app_runtime
    root = str(tmp_path / "Downloads/IdolyPride") if public else None
    seen = []
    fake = SimpleNamespace(status=lambda: {"running": True})
    def start(data, **options):
        seen.append((data, options))
        return fake
    monkeypatch.setattr(app_runtime, "start", start)
    monkeypatch.setattr(boundary, "_copy_asset", lambda *args: None)
    monkeypatch.setattr(boundary, "install_bundle", lambda bundle, files, digest: files / "data")
    classes = {"game.qualiarts.idolypride.localserver.BuildConfig": SimpleNamespace(SERVER_DATA_SHA256="public-test"),
               "game.qualiarts.idolypride.localserver.CryptoBridge": SimpleNamespace(aesCbc=lambda *args: b"")}
    monkeypatch.setitem(sys.modules, "java", SimpleNamespace(jclass=lambda name: classes[name]))
    result = boundary.start(str(tmp_path), object(), SimpleNamespace(log=lambda message: None),
                            None, False, True, False, root)
    assert json.loads(result)["running"] is True
    assert seen[0][1]["resource_cache_dir"] == root
    assert seen[0][0] == tmp_path / "data"
    assert not (tmp_path / "Downloads").exists()


@pytest.mark.parametrize("value", ["relative", "", "bad\0path", 3, b"/bytes"])
def test_start_rejects_ambiguous_resource_root_before_install_or_java(boundary, value):
    with pytest.raises(ValueError, match="absolute"):
        boundary.start("unused", object(), object(), resource_cache_dir=value)
