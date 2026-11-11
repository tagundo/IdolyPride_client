"""Exercise bundled public data installation without an Android process."""
from array import array
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
from types import ModuleType, SimpleNamespace
import unittest
from zipfile import ZipFile

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "app/src/main/python/android_server_runtime.py"
spec = importlib.util.spec_from_file_location("android_server_runtime", SCRIPT)
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


class InstallationTests(unittest.TestCase):
    def test_import_does_not_change_the_host_protobuf_backend(self):
        code = ("import importlib.util,os; "
                f"spec=importlib.util.spec_from_file_location('bridge',{str(SCRIPT)!r}); "
                "module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module); "
                "assert os.environ['PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION']=='upb'")
        subprocess.run([sys.executable, "-c", code], check=True,
                       env=dict(os.environ, PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION="upb"))

    def write_zip(self, root, extra=None):
        archive = root / "bundle.zip"
        entries = {"data/protocol/idolypride-6.1.1.pb": b"schema", "data/original-master/master-tag.json": b"{}",
                   "data/original-master/assets/master/Card.db": b"public encrypted master",
                   "data/master-json/Character.json": b"[]"}
        entries.update(extra or {})
        with ZipFile(archive, "w") as zipped:
            for name, contents in entries.items():
                zipped.writestr(name, contents)
        return archive, hashlib.sha256(archive.read_bytes()).hexdigest()

    def test_installs_public_files_and_preserves_state_on_repeat(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive, digest = self.write_zip(root)
            files = root / "private"
            (files / "data").mkdir(parents=True)
            (files / "data/state.db").write_bytes(b"existing progress")
            data = bridge.install_bundle(archive, files, digest)
            self.assertEqual((data / "state.db").read_bytes(), b"existing progress")
            self.assertEqual((data / "master-json/Character.json").read_bytes(), b"[]")
            self.assertEqual(bridge.install_bundle(archive, files, digest), data)
            self.assertEqual((data / "state.db").read_bytes(), b"existing progress")

    def test_rejects_private_paths_and_traversal_before_writing(self):
        for name in ("data/state.db", "data/private/session.json", "../outside", "/tmp/outside", "data/../state.db",
                     "data/public-fixtures/state.db", "data/public-fixtures/responses/private.json",
                     "data/public-tutorial/state.db", "data/public-tutorial/private.archive",
                     "data/public-tutorial/responses/other.pb", "data/public-tutorial/other.pb",
                     "data/public-tutorial/../state.db", "data/public-tutorial/tutorial-short.pb/extra"):
            with self.subTest(path=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                archive, digest = self.write_zip(root, {name: b"do not install"})
                files = root / "private"
                with self.assertRaises(ValueError):
                    bridge.install_bundle(archive, files, digest)
                self.assertFalse(files.exists())

    def test_installs_the_public_title_text_namespace_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive, digest = self.write_zip(root, {
                "data/public-fixtures/manifest.json": b'{"schema_version":1,"responses":[]}',
                "data/public-fixtures/responses/rule.pb": b"public terms",
            })
            data = bridge.install_bundle(archive, root / "private", digest)
            self.assertEqual((data / "public-fixtures/responses/rule.pb").read_bytes(), b"public terms")

    def test_installs_only_the_fixed_public_tutorial_files_and_preserves_progress(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            contents = {"data/public-tutorial/manifest.json": b'{"fixed_demo":true}',
                        "data/public-tutorial/tutorial-short.pb": b"sanitized public short replay",
                        "data/public-tutorial/tutorial-full.pb": b"sanitized public full replay"}
            archive, digest = self.write_zip(root, contents)
            files = root / "private"
            (files / "data").mkdir(parents=True)
            (files / "data/state.db").write_bytes(b"existing progress")
            data = bridge.install_bundle(archive, files, digest)
            for name, expected in contents.items():
                self.assertEqual((files / name).read_bytes(), expected)
            self.assertEqual((data / "state.db").read_bytes(), b"existing progress")
            self.assertEqual(bridge.install_bundle(archive, files, digest), data)
            self.assertEqual((data / "state.db").read_bytes(), b"existing progress")

    def test_corrupt_hash_does_not_mutate_private_storage(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive, _ = self.write_zip(root)
            with self.assertRaises(ValueError):
                bridge.install_bundle(archive, root / "private", "0" * 64)
            self.assertFalse((root / "private").exists())

    def test_story_bundle_install_and_update_preserve_all_local_account_rows(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            files = root / "private"
            data = files / "data"
            data.mkdir(parents=True)
            database = data / "state.db"
            with sqlite3.connect(database) as db:
                db.executescript("""
                    CREATE TABLE profiles(name TEXT, public_id TEXT);
                    CREATE TABLE sessions(profile TEXT, token_hash TEXT);
                    CREATE TABLE profile_settings(profile TEXT, response BLOB);
                    CREATE TABLE snapshots(profile TEXT, response BLOB);
                    INSERT INTO profiles VALUES ('local-fixture', 'synthetic-public-id');
                    INSERT INTO sessions VALUES ('local-fixture', 'synthetic-session-hash');
                    INSERT INTO profile_settings VALUES ('local-fixture', X'000102');
                    INSERT INTO snapshots VALUES ('local-fixture', X'FF8001');
                """)
            db.close()
            preserved = database.read_bytes()
            original, original_digest = self.write_zip(root)
            bridge.install_bundle(original, files, original_digest)
            self.assertEqual(database.read_bytes(), preserved)
            for revision in (1, 2):
                contents = {"data/public-story/manifest.json": ('{"schema":1,"revision":%d}' % revision).encode(),
                            "data/public-story/story-list-event.pb": b"public event " + bytes([revision]),
                            "data/public-story/story-list-extra.pb": b"public extra " + bytes([revision])}
                archive, digest = self.write_zip(root, contents)
                self.assertEqual(bridge.install_bundle(archive, files, digest), data)
                for name, expected in contents.items():
                    self.assertEqual((files / name).read_bytes(), expected)
                self.assertEqual(database.read_bytes(), preserved)
                self.assertEqual((files / ".server-data-sha256").read_text().strip(), digest)
                self.assertEqual(bridge.install_bundle(archive, files, digest), data)
                self.assertEqual(database.read_bytes(), preserved)
            self.assertFalse(list(data.rglob(".server-data-*")))

    def test_public_story_rejects_nonfixed_paths_before_any_install_write(self):
        forbidden = ("data/public-story/other.pb", "data/public-story/state.db", "data/public-story/session.json",
                     "data/public-story/private.archive", "data/public-story/nested/story-list-event.pb",
                     "data/public-story/../state.db", "data/public-story/story-list-extra.pb/secret",
                     "data/public-story/story-list-extra.pb.bak", "data/public-story/manifest.json/private",
                     "data/public-story/story-list-event\\.pb", "data/public-story//story-list-event.pb",
                     "data/public-story/./story-list-event.pb")
        for name in forbidden:
            with self.subTest(path=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                files = root / "private"
                (files / "data").mkdir(parents=True)
                database = files / "data/state.db"
                database.write_bytes(b"existing local profile/session/settings")
                archive, digest = self.write_zip(root, {"data/public-story/manifest.json": b'{"schema":1}',
                                                       name: b"must not be installed"})
                with self.assertRaises(ValueError):
                    bridge.install_bundle(archive, files, digest)
                self.assertEqual(database.read_bytes(), b"existing local profile/session/settings")
                self.assertFalse((files / "data/public-story").exists())
                self.assertFalse((files / "data/protocol").exists())
                self.assertFalse((files / ".server-data-sha256").exists())

    def sqlite_progress(self, files):
        data = files / "data"
        data.mkdir(parents=True, exist_ok=True)
        database = data / "state.db"
        with sqlite3.connect(database) as db:
            db.executescript("""
                CREATE TABLE snapshots(profile TEXT PRIMARY KEY, response BLOB);
                INSERT INTO snapshots VALUES ('synthetic-player', X'0080FF0123');
            """)
        return database, database.read_bytes()

    def test_public_octo_pair_installs_and_repairs_missing_file_without_changing_sqlite(self):
        contents = {"data/public-octo/settings.json": b'{"schema":1,"public":true}',
                    "data/public-octo/manifest.pb": b"\x00\x80\xff public manifest"}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive, digest = self.write_zip(root, contents)
            files = root / "private"
            database, preserved = self.sqlite_progress(files)
            data = bridge.install_bundle(archive, files, digest)
            self.assertEqual(data, files / "data")
            for name, expected in contents.items():
                self.assertEqual((files / name).read_bytes(), expected)
            self.assertEqual(database.read_bytes(), preserved)
            for missing in contents:
                with self.subTest(missing=missing):
                    (files / missing).unlink()
                    self.assertEqual((files / ".server-data-sha256").read_text().strip(), digest)
                    self.assertEqual(bridge.install_bundle(archive, files, digest), data)
                    for name, expected in contents.items():
                        self.assertEqual((files / name).read_bytes(), expected)
                    self.assertEqual(database.read_bytes(), preserved)
                    with sqlite3.connect(database) as db:
                        self.assertEqual(db.execute("SELECT response FROM snapshots").fetchone()[0],
                                         b"\x00\x80\xff\x01\x23")
            self.assertFalse(list(data.rglob(".server-data-*")))

    def test_partial_public_octo_pair_rejects_before_any_install_write(self):
        for name in ("settings.json", "manifest.pb"):
            for marked in (False, True):
                with self.subTest(name=name, matching_marker=marked), tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    files = root / "private"
                    database, preserved = self.sqlite_progress(files)
                    if marked:
                        original, original_digest = self.write_zip(root)
                        bridge.install_bundle(original, files, original_digest)
                    archive, digest = self.write_zip(root, {"data/public-octo/" + name: b"partial"})
                    if marked:
                        (files / ".server-data-sha256").write_text(digest + "\n")
                    before = {str(p.relative_to(files)): p.read_bytes()
                              for p in files.rglob("*") if p.is_file()}
                    with self.assertRaisesRegex(ValueError, "incomplete"):
                        bridge.install_bundle(archive, files, digest)
                    after = {str(p.relative_to(files)): p.read_bytes()
                             for p in files.rglob("*") if p.is_file()}
                    self.assertEqual(after, before)
                    self.assertEqual(database.read_bytes(), preserved)
                    self.assertFalse((files / "data/public-octo").exists())

    def test_public_octo_private_or_extra_paths_reject_before_any_install_write(self):
        for name in ("state.db", "session.archive", "nested/manifest.pb", "manifest.pb.bak",
                     "settings.json/private"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                files = root / "private"
                database, preserved = self.sqlite_progress(files)
                contents = {"data/public-octo/settings.json": b"public settings",
                            "data/public-octo/manifest.pb": b"public manifest",
                            "data/public-octo/" + name: b"must not be installed"}
                archive, digest = self.write_zip(root, contents)
                with self.assertRaises(ValueError):
                    bridge.install_bundle(archive, files, digest)
                self.assertEqual(database.read_bytes(), preserved)
                self.assertFalse((files / "data/public-octo").exists())
                self.assertFalse((files / "data/protocol").exists())
                self.assertFalse((files / ".server-data-sha256").exists())


@pytest.mark.parametrize("options,expected", [({}, True), ({"download_missing_resources": True}, True),
                                             ({"download_missing_resources": False}, False)])
def test_start_forwards_explicit_or_default_resource_download_policy(monkeypatch, tmp_path, options, expected):
    java = ModuleType("java")
    classes = []
    def jclass(name):
        classes.append(name)
        if name.endswith(".BuildConfig"):
            return SimpleNamespace(SERVER_DATA_SHA256="a" * 64)
        if name.endswith(".CryptoBridge"):
            return SimpleNamespace(aesCbc=lambda encrypt, key, iv, payload: payload)
        raise AssertionError("Unexpected Java class")
    java.jclass = jclass
    monkeypatch.setitem(sys.modules, "java", java)
    monkeypatch.setenv("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "upb")
    monkeypatch.setattr(bridge, "_RUNTIME", None)
    monkeypatch.setattr(bridge, "_LAST_STATUS", {"running": False})
    monkeypatch.setattr(bridge, "_copy_asset", lambda *_args: None)
    monkeypatch.setattr(bridge, "install_bundle", lambda _bundle, files, _digest: files / "data")
    starts = []
    runtime = ModuleType("idoly_local.app_runtime")
    def start_runtime(data, **kwargs):
        starts.append((data, kwargs))
        return SimpleNamespace(status=lambda: {"running": True})
    runtime.start = start_runtime
    monkeypatch.setitem(sys.modules, "idoly_local.app_runtime", runtime)
    logs = []
    result = bridge.start(str(tmp_path), object(), SimpleNamespace(log=logs.append), **options)
    assert json.loads(result)["running"] is True
    assert len(starts) == 1
    data, kwargs = starts[0]
    assert data == tmp_path / "data" and kwargs["profile"] == "sandbox"
    assert kwargs["download_missing_resources"] is expected
    assert kwargs["resource_fetcher"] is bridge._fetch_resource
    assert kwargs["aes_cbc"](True, b"key", b"iv", b"\x00\x80\xff") == b"\x00\x80\xff"
    assert classes == ["game.qualiarts.idolypride.localserver.BuildConfig",
                       "game.qualiarts.idolypride.localserver.CryptoBridge"]


@pytest.mark.parametrize("value", [None, 0, 1, "false"])
def test_start_rejects_non_boolean_resource_policy_before_platform_or_storage_work(monkeypatch, tmp_path, value):
    monkeypatch.setattr(bridge, "_RUNTIME", None)
    monkeypatch.setattr(bridge, "_copy_asset", lambda *_args: pytest.fail("must not touch assets"))
    with pytest.raises(ValueError, match="explicit boolean"):
        bridge.start(str(tmp_path), object(), SimpleNamespace(log=lambda _: None),
                     download_missing_resources=value)
    assert not list(tmp_path.iterdir())


class _ResourceStream:
    def __init__(self, body):
        self.body, self.offset = body, 0
        self.read_calls = self.close_calls = 0
        self.read_error = self.close_error = None

    def read(self, buffer, offset, count):
        self.read_calls += 1
        if self.read_error is not None:
            raise self.read_error
        if self.offset == len(self.body):
            return -1
        chunk = self.body[self.offset:self.offset + count]
        self.offset += len(chunk)
        for index, value in enumerate(chunk, offset):
            buffer[index] = value if value < 128 else value - 256
        return len(chunk)

    def close(self):
        self.close_calls += 1
        if self.close_error is not None:
            raise self.close_error


class _ResourceConnection:
    def __init__(self, body=b"\x00\x7f\x80\xfe\xff", status=200):
        self.stream = _ResourceStream(body)
        self.response_status = status
        self.properties = {}
        self.follow_redirects = None
        self.connect_timeout = self.read_timeout = None
        self.open_calls = self.disconnect_calls = 0
        self.open_error = self.disconnect_error = None
        self.url = "https://d2ilil7yh5oi1v.cloudfront.net/synthetic-resource"

    def setInstanceFollowRedirects(self, value): self.follow_redirects = value
    def setConnectTimeout(self, value): self.connect_timeout = value
    def setReadTimeout(self, value): self.read_timeout = value
    def setRequestProperty(self, name, value): self.properties[name] = value
    def getResponseCode(self): return self.response_status
    def getHeaderField(self, name):
        return {"Content-Length": str(len(self.stream.body)), "Content-Encoding": "identity"}.get(name)
    def getURL(self): return SimpleNamespace(toString=lambda: self.url)
    def getInputStream(self):
        self.open_calls += 1
        if self.open_error is not None:
            raise self.open_error
        return self.stream
    def disconnect(self):
        self.disconnect_calls += 1
        if self.disconnect_error is not None:
            raise self.disconnect_error


def _java_resource(monkeypatch, connection):
    java = ModuleType("java")
    requested_classes, opened_urls = [], []
    java.jbyte = object()
    def jarray(kind):
        assert kind is java.jbyte
        return lambda size: array("b", [0]) * size
    def jclass(name):
        requested_classes.append(name)
        assert name == "java.net.URL", "must use normal URL trust, not a replacement TLS verifier"
        def url(value):
            opened_urls.append(value)
            return SimpleNamespace(openConnection=lambda: connection)
        return url
    java.jarray, java.jclass = jarray, jclass
    monkeypatch.setitem(sys.modules, "java", java)
    return requested_classes, opened_urls


@pytest.mark.parametrize("timeout,milliseconds", [(0, 1), (1.234, 1234), (60, 30000)])
def test_android_resource_binary_stream_uses_platform_url_identity_encoding_and_no_redirects(
        monkeypatch, timeout, milliseconds):
    connection = _ResourceConnection()
    classes, urls = _java_resource(monkeypatch, connection)
    with bridge._fetch_resource(connection.url, timeout=timeout) as response:
        assert classes == ["java.net.URL"] and urls == [connection.url]
        assert connection.follow_redirects is False
        assert connection.connect_timeout == connection.read_timeout == milliseconds
        assert connection.properties == {"Accept-Encoding": "identity",
                                          "User-Agent": "IdolyPride-Local-Resource-Cache"}
        assert response.status == 200
        assert response.headers == {"Content-Length": "5", "Content-Encoding": "identity"}
        assert response.geturl() == connection.url
        assert response.read(2) == b"\x00\x7f"
        assert response.read(8) == b"\x80\xfe\xff"
        assert response.read(8) == b""
    response.close()
    assert connection.stream.close_calls == connection.disconnect_calls == 1
    for accessor in (lambda: response.status, lambda: response.headers, response.geturl,
                     lambda: response.read(1)):
        with pytest.raises(OSError, match="closed"):
            accessor()
    assert connection.open_calls == 1


def test_android_resource_redirect_status_is_returned_without_enabling_following(monkeypatch):
    connection = _ResourceConnection(status=302)
    _java_resource(monkeypatch, connection)
    with bridge._fetch_resource(connection.url, timeout=1) as response:
        assert response.status == 302 and connection.follow_redirects is False
    assert connection.open_calls == 0 and connection.disconnect_calls == 1


@pytest.mark.parametrize("failure", ["open", "read"])
def test_android_resource_network_read_errors_still_close_and_disconnect(monkeypatch, failure):
    connection = _ResourceConnection()
    _java_resource(monkeypatch, connection)
    if failure == "open": connection.open_error = OSError("open failed")
    else: connection.stream.read_error = OSError("read failed")
    with pytest.raises(OSError, match="failed"):
        with bridge._fetch_resource(connection.url, timeout=1) as response:
            response.read(4)
    response.close()
    assert connection.disconnect_calls == 1
    assert connection.stream.close_calls == (0 if failure == "open" else 1)


@pytest.mark.parametrize("failure", ["stream", "disconnect"])
def test_android_resource_close_is_idempotent_even_when_platform_cleanup_raises(monkeypatch, failure):
    connection = _ResourceConnection()
    _java_resource(monkeypatch, connection)
    response = bridge._fetch_resource(connection.url, timeout=1)
    assert response.read(1) == b"\x00"
    if failure == "stream": connection.stream.close_error = OSError("cleanup failed")
    else: connection.disconnect_error = OSError("cleanup failed")
    with pytest.raises(OSError, match="cleanup failed"):
        response.close()
    response.close()
    assert connection.stream.close_calls == connection.disconnect_calls == 1
    with pytest.raises(OSError, match="closed"):
        response.read(1)


def test_android_resource_close_while_opening_closes_late_stream_without_reading(monkeypatch):
    connection = _ResourceConnection()
    _java_resource(monkeypatch, connection)
    response = bridge._fetch_resource(connection.url, timeout=1)
    opening, release, closed = threading.Event(), threading.Event(), threading.Event()
    read_errors, read_values, close_errors = [], [], []
    def blocked_open():
        opening.set()
        if not release.wait(3):
            raise OSError("test release timed out")
        return connection.stream
    connection.getInputStream = blocked_open
    def read():
        try: read_values.append(response.read(4))
        except Exception as error: read_errors.append(error)
    def close():
        try: response.close()
        except Exception as error: close_errors.append(error)
        finally: closed.set()
    reader = threading.Thread(target=read, daemon=True)
    closer = threading.Thread(target=close, daemon=True)
    reader.start()
    try:
        assert opening.wait(2)
        closer.start()
        close_finished_while_open_blocked = closed.wait(2)
    finally:
        release.set()
        reader.join(3)
        if closer.ident is not None: closer.join(3)
    assert close_finished_while_open_blocked, "close must not wait for blocked stream acquisition"
    assert not reader.is_alive() and not closer.is_alive()
    assert not close_errors and not read_values
    assert len(read_errors) == 1 and isinstance(read_errors[0], OSError)
    assert "closed" in str(read_errors[0]).lower()
    assert connection.stream.close_calls == 1 and connection.stream.read_calls == 0
    assert connection.disconnect_calls >= 1
    before = connection.disconnect_calls
    response.close()
    assert connection.disconnect_calls == before


if __name__ == "__main__":
    unittest.main()
