"""Exercise bundled public data installation without an Android process."""
import hashlib
import importlib.util
import os
from pathlib import Path
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
                     "data/public-fixtures/state.db", "data/public-fixtures/responses/private.json"):
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

    def test_corrupt_hash_does_not_mutate_private_storage(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive, _ = self.write_zip(root)
            with self.assertRaises(ValueError):
                bridge.install_bundle(archive, root / "private", "0" * 64)
            self.assertFalse((root / "private").exists())


if __name__ == "__main__":
    unittest.main()
