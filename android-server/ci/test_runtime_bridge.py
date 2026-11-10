"""Exercise bundled public data installation without an Android process."""
import hashlib
import importlib.util
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from zipfile import ZipFile


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


if __name__ == "__main__":
    unittest.main()
