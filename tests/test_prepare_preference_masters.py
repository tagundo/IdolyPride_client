"""Source-bound preference supplements preserve original public input bytes.

Small fixtures use ordinary SQLite solely to exercise the shared read-only SQL
and protobuf decoder. Real encrypted SQLCipher verification belongs to the
remote invocation against the tool's hard-pinned public ServerData archive.
"""
from copy import deepcopy
import ast
import hashlib
import json
from pathlib import Path
import sqlite3
from zipfile import ZipFile

from google.protobuf import descriptor_pb2, message_factory
import pytest

from idoly_local.schema import Schema
from idoly_local.master_translation_build import read_master_rows
from tools import prepare_preference_masters as tool


VERSION = "1" * 64


def descriptor_bytes():
    master = descriptor_pb2.FileDescriptorProto(name="preferences-master.proto", package="master", syntax="proto3")
    image = master.message_type.add(name="CardImage")
    for number, name, kind in ((1, "cardId", 9), (2, "displayType", 5), (3, "imageType", 5), (4, "name", 9)):
        image.field.add(name=name, number=number, type=kind)
    decoration = master.message_type.add(name="Decoration")
    decoration.field.add(name="id", number=1, type=9)
    decoration.field.add(name="name", number=2, type=9)
    api = descriptor_pb2.FileDescriptorProto(name="preferences-api.proto", package="api", syntax="proto3")
    api.message_type.add(name="Empty")
    pack = api.message_type.add(name="Pack")
    for number, name, kind in ((1, "type", 9), (2, "fileName", 9), (3, "fileSize", 5),
                               (4, "cryptoKey", 9), (5, "downloadUrl", 9)):
        pack.field.add(name=name, number=number, type=kind)
    tag = api.message_type.add(name="Tag")
    tag.field.add(name="version", number=1, type=9)
    tag.field.add(name="masterTagPacks", number=2, type=11, label=3, type_name=".api.Pack")
    response = api.message_type.add(name="Response")
    response.field.add(name="masterTag", number=1, type=11, type_name=".api.Tag")
    api.service.add(name="Master").method.add(name="Get", input_type=".api.Empty", output_type=".api.Response")
    return descriptor_pb2.FileDescriptorSet(file=[master, api]).SerializeToString()


@pytest.fixture
def public(tmp_path, monkeypatch):
    raw = descriptor_bytes()
    descriptor = tmp_path / "source-schema.pb"
    descriptor.write_bytes(raw)
    schema = Schema.from_descriptor_set(descriptor)
    rows = {"CardImage": [{"cardId": "card-a", "displayType": 1, "imageType": 1, "name": "元の立ち絵"},
                           {"cardId": "card-a", "displayType": 2, "imageType": 2, "name": "元の画像"}],
            "Decoration": [{"id": "decoration-a", "name": "額縁"}]}
    files = {"data/protocol/idolypride-6.1.1.pb": raw,
             "data/master-json/Card.json": tool.canonical([{"id": "card-a"}])}
    tag = {"version": VERSION, "masterTagPacks": []}
    report = {"complete": True, "master_version": VERSION, "expected_packs": 2,
              "completed_packs": 2, "packs": {}}
    for table in tool.TABLES:
        path = tmp_path / (table + ".db")
        message = message_factory.GetMessageClass(schema.pool.FindMessageTypeByName("master." + table))
        with sqlite3.connect(path) as connection:
            connection.execute('CREATE TABLE "' + table + '" (data BLOB NOT NULL)')
            connection.executemany('INSERT INTO "' + table + '" VALUES (?)',
                [(message(**row).SerializeToString(),) for row in rows[table]])
        pack = {"type": table, "fileName": path.name, "fileSize": path.stat().st_size,
                "cryptoKey": "2" * 64, "downloadUrl": "https://example.invalid/" + path.name}
        tag["masterTagPacks"].append(pack)
        record_identity = [VERSION, table, path.name, pack["fileSize"], pack["cryptoKey"], pack["downloadUrl"]]
        report["packs"][table] = {"file_name": path.name, "size": pack["fileSize"],
            "sha256": tool.sha(path.read_bytes()),
            "source_sha256": tool.sha(json.dumps(record_identity, ensure_ascii=False, separators=(",", ":")).encode())}
        files["data/original-master/assets/master/" + path.name] = path.read_bytes()
    from google.protobuf.json_format import ParseDict
    response = schema.response_type("/api.Master/Get")()
    ParseDict(tag, response.masterTag)
    files.update({"data/original-master/master-tag.json": tool.canonical(tag),
                  "data/original-master/response.pb": response.SerializeToString(),
                  "data/original-master/archive-report.json": tool.canonical(report)})
    source = tmp_path / "PublicServerData.zip"

    def write():
        with ZipFile(source, "w") as archive:
            for name, content in files.items():
                archive.writestr(name, content)
        monkeypatch.setattr(tool, "SOURCE_BYTES", source.stat().st_size)
        monkeypatch.setattr(tool, "SOURCE_SHA256", tool.sha(source.read_bytes()))

    write()
    monkeypatch.setattr(tool, "SCHEMA_SHA256", tool.sha(raw))
    monkeypatch.setattr(tool, "MASTER_VERSION", VERSION)
    monkeypatch.setattr(tool, "PACK_COUNT", 2)
    monkeypatch.setattr(tool, "runtime", lambda: (Schema, sqlite3, "fixture-sqlite-not-encrypted", read_master_rows))
    return source, files, rows, write


def invoke(tmp_path, public, suffix="one"):
    source = public[0]
    return tool.prepare(source, tmp_path / ("work-" + suffix), tmp_path / ("tables-" + suffix + ".json"),
                        tmp_path / ("module-" + suffix + ".py"), tmp_path / ("report-" + suffix + ".json"))


def test_default_authority_is_exact_public_release_and_only_two_tables():
    assert tool.SOURCE_BYTES == 191343014
    assert tool.SOURCE_SHA256 == "37dbf0fb9bac5d860991753d2e41ff0c269684bfca673ba41e1bcb897651c223"
    assert tool.SCHEMA_SHA256 == "c82cee62abdca7144d11e710a6f773211464a89d2ddede207999a0a5e7aec8ad"
    assert tool.TABLES == ("CardImage", "Decoration") and tool.PACK_COUNT == 202


def test_real_read_only_sql_protobuf_roundtrip_and_deterministic_data_only_module(tmp_path, public, monkeypatch):
    before = public[0].read_bytes()
    statements, opened = [], []

    class Driver:
        @staticmethod
        def connect(target, **kwargs):
            assert kwargs == {"uri": True}
            assert target.endswith("?mode=ro")
            opened.append(target)
            connection = sqlite3.connect(target, uri=True)
            connection.set_trace_callback(statements.append)
            return connection

    monkeypatch.setattr(tool, "runtime", lambda: (Schema, Driver, "fixture-sqlite-not-encrypted", read_master_rows))
    one = invoke(tmp_path, public)
    two = invoke(tmp_path, public, "two")
    assert one == two and one["status"] == "PASS" and one["input_unchanged"] is True
    assert public[0].read_bytes() == before
    assert len(opened) == 4 and sum(sql == "PRAGMA query_only=ON" for sql in statements) == 4
    assert sum(sql == "PRAGMA integrity_check" for sql in statements) == 4
    assert not any(sql.startswith(("INSERT", "UPDATE", "CREATE", "DELETE")) for sql in statements)
    document = json.loads((tmp_path / "tables-one.json").read_bytes())
    assert document["tables"] == public[2]
    assert (tmp_path / "tables-one.json").read_bytes() == (tmp_path / "tables-two.json").read_bytes()
    module = (tmp_path / "module-one.py").read_bytes()
    assert module == (tmp_path / "module-two.py").read_bytes()
    parsed = ast.parse(module)
    assert all(isinstance(node, ast.Assign) for node in parsed.body)
    namespace = {"__builtins__": {}}
    exec(compile(parsed, "generated-preference-data", "exec"), namespace)
    assert set(namespace) == {"__builtins__", "MASTER_VERSION", "SOURCE_BYTES", "SOURCE_SHA256",
                              "SCHEMA_SHA256", "PACKS", "ROWS_JSON"}
    assert {table: json.loads(raw) for table, raw in namespace["ROWS_JSON"].items()} == public[2]
    for table, proof in one["packs"].items():
        assert proof["rows"] == len(public[2][table])
        assert proof["json_sha256"] == tool.sha(namespace["ROWS_JSON"][table].encode("ascii"))
    assert one["output"]["module"] == {"bytes": len(module), "sha256": tool.sha(module)}
    assert json.loads((tmp_path / "report-one.json").read_bytes()) == one
    assert {path.name for path in (tmp_path / "work-one").iterdir()} == {
        ".idoly-public-preference-work.json", "schema.pb", "CardImage.db", "Decoration.db"}


@pytest.mark.parametrize("change", ("source-hash", "schema-hash", "incomplete", "response-tag", "pack-hash", "pack-source", "duplicate-pack", "missing-pack", "private-member"))
def test_invalid_authority_or_archive_is_rejected_before_outputs(tmp_path, public, monkeypatch, change):
    source, files, _rows, write = public
    report_name = "data/original-master/archive-report.json"
    tag_name = "data/original-master/master-tag.json"
    if change in ("incomplete", "pack-hash", "pack-source"):
        report = json.loads(files[report_name])
        if change == "incomplete":
            report["complete"] = False
        else:
            report["packs"]["CardImage"]["sha256" if change == "pack-hash" else "source_sha256"] = "0" * 64
        files[report_name] = tool.canonical(report)
    elif change in ("response-tag", "duplicate-pack"):
        tag = json.loads(files[tag_name])
        if change == "response-tag":
            tag["masterTagPacks"][0]["cryptoKey"] = "3" * 64
        else:
            tag["masterTagPacks"][1] = deepcopy(tag["masterTagPacks"][0])
        files[tag_name] = tool.canonical(tag)
    elif change == "missing-pack":
        files.pop("data/original-master/assets/master/Decoration.db")
    elif change == "private-member":
        files["data/state.db"] = b"synthetic-private-neighbor-not-allowed"
    write()
    if change == "source-hash":
        monkeypatch.setattr(tool, "SOURCE_SHA256", "0" * 64)
    if change == "schema-hash":
        monkeypatch.setattr(tool, "SCHEMA_SHA256", "0" * 64)
    before = source.read_bytes()
    with pytest.raises(ValueError):
        invoke(tmp_path, public)
    assert source.read_bytes() == before
    assert not any((tmp_path / name).exists() for name in ("tables-one.json", "module-one.py", "report-one.json"))


@pytest.mark.parametrize("table,rows", (
    ("CardImage", [{"cardId": "missing", "displayType": 1, "imageType": 1}]),
    ("CardImage", [{"cardId": "card-a", "displayType": 0, "imageType": 1}]),
    ("CardImage", [{"cardId": "card-a", "displayType": True, "imageType": 1}]),
    ("CardImage", [{"cardId": "card-a", "displayType": 1, "imageType": 4}]),
    ("CardImage", [{"cardId": "card-a", "displayType": 1, "imageType": 1}] * 2),
    ("Decoration", [{"id": ""}]), ("Decoration", [{"id": "same"}] * 2),
    ("Card", [{"id": "card-a"}]), ("Decoration", [])))
def test_rows_require_actual_unique_master_keys_and_known_enums(table, rows):
    with pytest.raises(ValueError):
        tool.validate_rows(table, rows, {"card-a"})


def test_source_change_during_decode_has_no_generated_outputs(tmp_path, public, monkeypatch):
    def decode(schema, driver, root, pack):
        rows = read_master_rows(schema, driver, root, pack)
        if pack["type"] == "Decoration":
            with public[0].open("r+b") as stream:
                stream.seek(-1, 2)
                stream.write(b"X")
        return rows
    monkeypatch.setattr(tool, "runtime", lambda: (Schema, sqlite3, "fixture-only", decode))
    with pytest.raises(ValueError, match="source_changed"):
        invoke(tmp_path, public)
    assert not (tmp_path / "tables-one.json").exists()
    assert not (tmp_path / "module-one.py").exists()
    assert not (tmp_path / "report-one.json").exists()


def test_existing_outputs_and_symlink_ancestor_cannot_write_source_checkout(tmp_path, public, monkeypatch):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(checkout, target_is_directory=True)
    monkeypatch.setattr(tool, "ROOT", checkout)
    with pytest.raises(ValueError, match="outside_source_checkout"):
        tool.prepare(public[0], alias / "work", tmp_path / "tables.json", tmp_path / "module.py", tmp_path / "report.json")
    assert not list(checkout.iterdir())
    existing = tmp_path / "existing.py"
    existing.write_bytes(b"owned-existing-source")
    with pytest.raises(ValueError, match="fresh_work_and_outputs"):
        tool.prepare(public[0], tmp_path / "work", tmp_path / "tables.json", existing, tmp_path / "report.json")
    assert existing.read_bytes() == b"owned-existing-source"
