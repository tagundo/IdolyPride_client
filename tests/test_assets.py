from __future__ import annotations

import json
import mimetypes
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock
import urllib.error
import urllib.request

from google.protobuf import descriptor_pb2, descriptor_pool, message_factory

from idoly_local.assets import create_asset_server, prepare_master_tag


def schema():
    file = descriptor_pb2.FileDescriptorProto(name="test-assets.proto", package="assettest", syntax="proto3")
    pack = file.message_type.add(name="Pack")
    for number, name, kind in [(1, "type", 9), (2, "fileName", 9), (3, "fileSize", 5),
                               (4, "cryptoKey", 9), (5, "downloadUrl", 9)]:
        pack.field.add(name=name, number=number, type=kind)
    tag = file.message_type.add(name="Tag")
    tag.field.add(name="version", number=1, type=9)
    tag.field.add(name="masterTagPacks", number=2, type=11, label=3, type_name=".assettest.Pack")
    response = file.message_type.add(name="Response")
    response.field.add(name="masterTag", number=1, type=11, type_name=".assettest.Tag")
    pool = descriptor_pool.DescriptorPool()
    pool.Add(file)
    cls = message_factory.GetMessageClass(pool.FindMessageTypeByName("assettest.Response"))

    class Schema:
        def response_type(self, method):
            assert method == "/api.Master/Get"
            return cls
    return Schema()


class MasterArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pack = self.root / "table file.db"
        self.pack.write_bytes(b"database")
        self.tag_path = self.root / "tag.json"
        self.value = {"version": "release-v", "masterTagPacks": [{"type": "Card", "fileName": self.pack.name,
                      "fileSize": 8, "cryptoKey": "example-key", "downloadUrl": "https://official.invalid/pack"}]}
        self.schema = schema()

    def prepare(self, base_url="http://127.0.0.1:8080"):
        self.tag_path.write_text(json.dumps(self.value))
        return self.schema.response_type("/api.Master/Get").FromString(
            prepare_master_tag(self.schema, self.tag_path, self.root, base_url))

    def test_rewrites_url_preserving_version_key_and_bytes(self):
        original = self.pack.read_bytes()
        result = self.prepare()
        self.assertEqual(result.masterTag.version, "release-v")
        pack = result.masterTag.masterTagPacks[0]
        self.assertEqual(pack.cryptoKey, "example-key")
        self.assertEqual(pack.downloadUrl, "http://127.0.0.1:8080/master/table%20file.db")
        self.assertEqual(self.pack.read_bytes(), original)
        self.assertEqual(json.loads(self.tag_path.read_text()), self.value)

    def test_missing_or_wrong_size_fails(self):
        self.value["masterTagPacks"][0]["fileSize"] = 9
        with self.assertRaisesRegex(ValueError, "size"):
            self.prepare()
        self.pack.unlink()
        with self.assertRaisesRegex(ValueError, "missing"):
            self.prepare()

    def test_unsafe_and_duplicate_names_fail(self):
        for name in ["../table.db", "folder/table.db", "folder\\table.db", "..", ""]:
            with self.subTest(name=name):
                self.value["masterTagPacks"][0]["fileName"] = name
                with self.assertRaisesRegex(ValueError, "filenames"):
                    self.prepare()
        self.value["masterTagPacks"][0]["fileName"] = self.pack.name
        self.value["masterTagPacks"].append(dict(self.value["masterTagPacks"][0]))
        with self.assertRaisesRegex(ValueError, "unique"):
            self.prepare()

    def test_unknown_fields_fail_without_echoing_supplied_values(self):
        self.value["unknown"] = "private-value"
        with self.assertRaisesRegex(ValueError, "Invalid MasterTag JSON") as caught:
            self.prepare()
        self.assertNotIn("private-value", str(caught.exception))

    def test_invalid_tag_and_base_url_fail(self):
        self.value["version"] = ""
        with self.assertRaisesRegex(ValueError, "version"):
            self.prepare()
        for base in ["file:///tmp", "https://name:password@example.com", "http://example.com/base",
                     "http://example.com/?key=value"]:
            with self.subTest(base=base), self.assertRaisesRegex(ValueError, "origin"):
                self.prepare(base)


class AssetHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.parent = Path(self.temp.name)
        self.root = self.parent / "public"
        self.root.mkdir()
        (self.root / "master").mkdir()
        (self.root / "master" / "table.db").write_bytes(b"0123456789")
        (self.parent / "private.txt").write_bytes(b"private")
        (self.root / "escape.txt").symlink_to(self.parent / "private.txt")
        (self.root / "empty.bin").write_bytes(b"")
        self.server = create_asset_server("127.0.0.1", 0, self.root)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.cleanup_server)
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def cleanup_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, path, method="GET", headers=None):
        req = urllib.request.Request(self.base + path, method=method, headers=headers or {})
        return urllib.request.urlopen(req, timeout=2)

    def test_get_head_and_empty(self):
        with self.request("/master/table.db?ignored=value") as r:
            self.assertEqual(r.read(), b"0123456789")
            self.assertEqual(r.headers["Content-Length"], "10")
        with self.request("/master/table.db", method="HEAD") as r:
            self.assertEqual(r.read(), b"")
            self.assertEqual(r.headers["Content-Length"], "10")
        with self.request("/empty.bin") as r:
            self.assertEqual(r.read(), b"")
            self.assertEqual(r.headers["Content-Length"], "0")

    def test_ranges(self):
        for value, expected, content_range in [("bytes=2-4", b"234", "bytes 2-4/10"),
                                               ("bytes=8-", b"89", "bytes 8-9/10"),
                                               ("bytes=-3", b"789", "bytes 7-9/10")]:
            with self.subTest(value=value), self.request("/master/table.db", headers={"Range": value}) as r:
                self.assertEqual(r.status, 206)
                self.assertEqual(r.read(), expected)
                self.assertEqual(r.headers["Content-Range"], content_range)
        for value in ["bytes=10-20", "bytes=5-2", "bytes=0-1,4-5", "bytes=-0", "other=0-1"]:
            with self.subTest(value=value), self.assertRaises(urllib.error.HTTPError) as caught:
                self.request("/master/table.db", headers={"Range": value})
            self.assertEqual(caught.exception.code, 416)
            self.assertEqual(caught.exception.headers["Content-Range"], "bytes */10")

    def test_files_serve_when_host_mime_database_is_sandbox_denied(self):
        # Match PlayCover: the host MIME database exists, but opening it is
        # denied. A fresh stdlib guess_type() really fails in this condition.
        blocked = self.parent / "host-mime.types"
        blocked.write_text("image/png png\n")
        self.assertTrue(blocked.is_file())
        payloads = {
            "picture.PNG": (b"\x89PNG\r\n\x1a\n", "image/png"),
            "picture.jpeg": (b"\xff\xd8\xff\xd9", "image/jpeg"),
            "config.json": (b'{"enabled":true}', "application/json"),
            "archive.pack": (b"\x00\xff\x80\x01", "application/octet-stream"),
            "opaque.unknown": (b"\x00\xfe\x80", "application/octet-stream"),
        }
        for name, (body, _) in payloads.items():
            (self.root / name).write_bytes(body)
        with mock.patch.object(mimetypes, "knownfiles", [str(blocked)]), \
                mock.patch.object(mimetypes, "inited", False), \
                mock.patch.object(mimetypes, "_db", None), \
                mock.patch.object(mimetypes, "open", create=True,
                    side_effect=PermissionError(1, "Operation not permitted", str(blocked))) as mime_open:
            with self.assertRaises(PermissionError):
                mimetypes.guess_type("table.db")
            mime_open.assert_called_once()
            self.assertEqual(mime_open.call_args.args, (str(blocked),))
            # Neither global entry point may be used by any file response.
            with mock.patch.object(mimetypes, "init", side_effect=AssertionError("host MIME lookup")) as init, \
                    mock.patch.object(mimetypes, "guess_type", side_effect=AssertionError("host MIME lookup")) as guess:
                with self.request("/master/table.db") as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual(response.read(), b"0123456789")
                    self.assertEqual(response.headers["Content-Type"], "application/octet-stream")
                with self.request("/master/table.db", method="HEAD") as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual(response.headers["Content-Length"], "10")
                    self.assertEqual(response.read(), b"")
                with self.request("/master/table.db", headers={"Range": "bytes=2-4"}) as response:
                    self.assertEqual(response.status, 206)
                    self.assertEqual(response.headers["Content-Range"], "bytes 2-4/10")
                    self.assertEqual(response.read(), b"234")
                for name, (body, mime_type) in payloads.items():
                    with self.subTest(name=name), self.request("/" + name) as response:
                        self.assertEqual(response.status, 200)
                        self.assertEqual(response.headers["Content-Type"], mime_type)
                        self.assertEqual(response.read(), body)
                init.assert_not_called()
                guess.assert_not_called()
            self.assertEqual(mime_open.call_count, 1)

    def test_missing_directories_traversal_and_symlink_escape(self):
        for path in ["/", "/master", "/missing", "/../private.txt", "/%2e%2e/private.txt",
                     "/master/%2e%2e/%2e%2e/private.txt", "/escape.txt", "/%5c..%5cprivate.txt"]:
            with self.subTest(path=path), self.assertRaises(urllib.error.HTTPError) as caught:
                self.request(path)
            self.assertEqual(caught.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
