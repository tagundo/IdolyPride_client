"""Exercise reconstructed packs through the SQL/protobuf read boundaries."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace

from google.protobuf import descriptor_pb2, descriptor_pool, message_factory

from idoly_local.master_build import build_master_packs
from idoly_local.schema import Schema

try:
    from sqlcipher3 import dbapi2 as sqlcipher
except ImportError:
    sqlcipher = None


_DESCRIPTOR = Path(__file__).resolve().parents[1] / "data/protocol/idolypride-6.1.1.pb"


def _synthetic_schema():
    """Keep annotated-schema pack tests runnable without downloaded game data."""
    pool = descriptor_pool.DescriptorPool()
    pool.AddSerializedFile(descriptor_pb2.DESCRIPTOR.serialized_pb)
    options = descriptor_pb2.FileDescriptorProto(
        name="test_master_options.proto", package="master", syntax="proto3")
    options.dependency.append("google/protobuf/descriptor.proto")
    options.extension.add(name="table", number=50007, type=8, label=1,
                          extendee=".google.protobuf.MessageOptions")
    options.extension.add(name="pk", number=50008, type=8, label=1,
                          extendee=".google.protobuf.FieldOptions")
    options_file = pool.AddSerializedFile(options.SerializeToString())
    message_options = message_factory.GetMessageClass(
        pool.FindMessageTypeByName("google.protobuf.MessageOptions"))
    field_options = message_factory.GetMessageClass(
        pool.FindMessageTypeByName("google.protobuf.FieldOptions"))
    table_extension = pool.FindExtensionByName("master.table")
    pk_extension = pool.FindExtensionByName("master.pk")
    master = descriptor_pb2.FileDescriptorProto(
        name="test_master_tables.proto", package="master", syntax="proto3")
    master.dependency.append(options.name)
    definitions = {
        "MusicChartPattern": [("id", 1, 9, True), ("number", 2, 5, True),
                              ("position", 3, 5, False)],
        "AppCapacityLimit": [("appCapacityLimitKey", 1, 5, True),
                             ("isDataExist", 2, 8, False)],
        "Music": [("id", 1, 9, True), ("is3dAvailable", 10, 8, False)],
    }
    for name, fields in definitions.items():
        message = master.message_type.add(name=name)
        annotation = message_options()
        annotation.Extensions[table_extension] = True
        message.options.ParseFromString(annotation.SerializeToString())
        for field_name, number, kind, primary in fields:
            field = message.field.add(name=field_name, number=number, type=kind, label=1)
            if primary:
                annotation = field_options()
                annotation.Extensions[pk_extension] = True
                field.options.ParseFromString(annotation.SerializeToString())
    master_file = pool.AddSerializedFile(master.SerializeToString())
    return SimpleNamespace(pool=pool, files=[options_file, master_file],
                           fingerprint=hashlib.sha256(master.SerializeToString()).hexdigest())


class MasterPackChecks:
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source"
        self.source.mkdir()
        (self.source / "!version.txt").write_text("fixture-source-version", encoding="utf-8")
        self.output = self.root / "built"

    def table(self, name, rows):
        (self.source / (name + ".json")).write_text(json.dumps(rows), encoding="utf-8")

    def build(self, tables):
        report = build_master_packs(self.schema, self.source, self.output, tables=tables)
        tag = json.loads((self.output / "master-tag.json").read_text(encoding="utf-8"))
        return report, tag

    def connect_pack(self, pack):
        path = self.output / "assets" / "master" / pack["fileName"]
        connection = sqlcipher.connect(str(path))
        self.addCleanup(connection.close)
        connection.execute('PRAGMA key = "x\'' + pack["cryptoKey"] + '\'"')
        return connection

    def proto(self, table, blob):
        descriptor = self.schema.pool.FindMessageTypeByName("master." + table)
        return message_factory.GetMessageClass(descriptor).FromString(blob)

    def test_composite_key_pack_roundtrips_client_select_and_preserves_source_order(self):
        rows = [{"id": "chart-local", "number": 2, "position": 3},
                {"id": "chart-local", "number": 1, "position": 4}]
        self.table("MusicChartPattern", rows)
        report, tag = self.build(["MusicChartPattern"])
        self.assertTrue(tag["version"].startswith("local-"))
        self.assertEqual(len(tag["masterTagPacks"]), 1)
        pack = tag["masterTagPacks"][0]
        self.assertEqual(pack["type"], "MusicChartPattern")
        self.assertEqual(pack["downloadUrl"], "http://127.0.0.1:8080/master/MusicChartPattern.db")
        self.assertEqual(len(bytes.fromhex(pack["cryptoKey"])), 32)
        path = self.output / "assets" / "master" / pack["fileName"]
        self.assertEqual(path.stat().st_size, pack["fileSize"])
        connection = self.connect_pack(pack)
        result = connection.execute('SELECT id, number, data FROM "MusicChartPattern" '
                                    'WHERE id = ? ORDER BY number', ("chart-local",)).fetchall()
        self.assertEqual([(identifier, number) for identifier, number, _ in result],
                         [("chart-local", 1), ("chart-local", 2)])
        self.assertEqual([self.proto("MusicChartPattern", blob).position for _, _, blob in result], [4, 3])
        self.assertEqual([row[0] for row in connection.execute(
            'SELECT number FROM "MusicChartPattern" ORDER BY rowid')], [2, 1])
        info = connection.execute('PRAGMA table_info("MusicChartPattern")').fetchall()
        self.assertEqual([(row[1], row[2], row[5]) for row in info],
                         [("Id", "STRING", 1), ("Number", "INTEGER", 2), ("data", "BLOB", 0)])
        self.assertTrue(all(row[3] == 0 for row in info))
        written_report = (self.output / "build-report.json").read_text(encoding="utf-8")
        self.assertNotIn(pack["cryptoKey"], written_report)
        self.assertNotIn(pack["cryptoKey"], json.dumps(report))

    def test_integer_primary_key_includes_zero_and_encryption_rejects_sqlite_or_wrong_key(self):
        self.table("AppCapacityLimit", [{"appCapacityLimitKey": 0, "isDataExist": True},
                                        {"appCapacityLimitKey": 6, "isDataExist": True}])
        _, tag = self.build(["AppCapacityLimit"])
        pack = tag["masterTagPacks"][0]
        connection = self.connect_pack(pack)
        result = connection.execute('SELECT appCapacityLimitKey, data FROM "AppCapacityLimit" '
                                    'ORDER BY appCapacityLimitKey').fetchall()
        self.assertEqual([number for number, _ in result], [0, 6])
        self.assertTrue(all(self.proto("AppCapacityLimit", blob).isDataExist for _, blob in result))
        path = self.output / "assets" / "master" / pack["fileName"]
        self.assertNotEqual(path.read_bytes()[:16], b"SQLite format 3\x00")
        plain = sqlite3.connect(str(path))
        self.addCleanup(plain.close)
        with self.assertRaises(sqlite3.DatabaseError):
            plain.execute("SELECT name FROM sqlite_master").fetchall()
        wrong = sqlcipher.connect(str(path))
        self.addCleanup(wrong.close)
        wrong.execute('PRAGMA key = "x\'' + "00" * 32 + '\'"')
        with self.assertRaises(sqlcipher.DatabaseError):
            wrong.execute("SELECT name FROM sqlite_master").fetchall()

    def test_verified_field_alias_roundtrips_with_exact_descriptor(self):
        self.table("Music", [{"id": "music-local", "is3DAvailable": True}])
        _, tag = self.build(["Music"])
        connection = self.connect_pack(tag["masterTagPacks"][0])
        blob = connection.execute('SELECT data FROM "Music" WHERE id = ?', ("music-local",)).fetchone()[0]
        self.assertTrue(self.proto("Music", blob).is3dAvailable)

    def test_numeric_looking_string_id_uses_observed_numeric_affinity(self):
        # STRING is SQLite NUMERIC affinity in original master packs. The SQL
        # lookup key may coerce, while the protobuf preserves its original ID.
        self.table("Music", [{"id": "001"}])
        _, tag = self.build(["Music"])
        connection = self.connect_pack(tag["masterTagPacks"][0])
        row = connection.execute('SELECT id, typeof(id), data FROM "Music" WHERE id = ?',
                                 ("1",)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[:2], (1, "integer"))
        self.assertEqual(self.proto("Music", row[2]).id, "001")

    def test_unknown_field_fails_without_publishing_partial_output(self):
        self.table("AppCapacityLimit", [{"appCapacityLimitKey": 1, "isDataExist": True},
                                        {"appCapacityLimitKey": 2, "notARealField": True}])
        with self.assertRaises(ValueError):
            self.build(["AppCapacityLimit"])
        self.assertFalse(self.output.exists())

    def test_alias_and_exact_name_conflict_fails_without_publishing(self):
        self.table("Music", [{"id": "music-local", "is3DAvailable": True, "is3dAvailable": False}])
        with self.assertRaises(ValueError):
            self.build(["Music"])
        self.assertFalse(self.output.exists())

    def test_duplicate_composite_key_fails_without_publishing(self):
        self.table("MusicChartPattern", [{"id": "same", "number": 1}, {"id": "same", "number": 1}])
        with self.assertRaises(ValueError):
            self.build(["MusicChartPattern"])
        self.assertFalse(self.output.exists())

    def test_existing_output_is_preserved(self):
        self.table("AppCapacityLimit", [{"appCapacityLimitKey": 1}])
        self.output.mkdir()
        sentinel = self.output / "preserved.txt"
        sentinel.write_text("keep existing archive", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.build(["AppCapacityLimit"])
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep existing archive")
        self.assertEqual(list(self.output.iterdir()), [sentinel])

    def test_full_build_requires_complete_table_inventory(self):
        self.table("AppCapacityLimit", [{"appCapacityLimitKey": 1}])
        with self.assertRaises(ValueError):
            build_master_packs(self.schema, self.source, self.output)
        self.assertFalse(self.output.exists())


@unittest.skipUnless(sqlcipher is not None and _DESCRIPTOR.is_file(),
                     "SQLCipher and the actual 6.1.1 descriptor set are required")
class MasterPackTests(MasterPackChecks, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = Schema.from_descriptor_set(_DESCRIPTOR)


@unittest.skipUnless(sqlcipher is not None, "SQLCipher driver is required")
class SyntheticMasterPackTests(MasterPackChecks, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = _synthetic_schema()


if __name__ == "__main__":
    unittest.main()
