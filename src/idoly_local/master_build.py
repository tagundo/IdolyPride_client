"""Rebuild local SQLCipher master packs from strictly validated protobuf JSON.

The exact client descriptor's master.table/master.pk annotations own table and
key identity. This reconstructs the observed read contract; device consumption
of these generated archives still needs validation.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import tempfile

from google.protobuf import message_factory
from google.protobuf.descriptor import FieldDescriptor
from google.protobuf.json_format import ParseDict, ParseError

from .schema import (_MASTER_FIELD_ALIASES as _ALIASES,
                     normalize_master_row as _normalized_row)


BUILDER_VERSION = 2
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")



def _digest(contents: bytes) -> str:
    return hashlib.sha256(contents).hexdigest()


def _identifier(name: str) -> str:
    if not _NAME.fullmatch(name):
        raise ValueError("Unsupported SQL identifier in master schema")
    return '"' + name + '"'


def _sql_column_name(field_name: str) -> str:
    # Official 6.1.1 packs use generated C# property casing for primary keys.
    return field_name[:1].upper() + field_name[1:]


def _annotated_tables(schema):
    pool = schema.pool
    table_option = pool.FindExtensionByName("master.table")
    pk_option = pool.FindExtensionByName("master.pk")
    message_options = message_factory.GetMessageClass(pool.FindMessageTypeByName("google.protobuf.MessageOptions"))
    field_options = message_factory.GetMessageClass(pool.FindMessageTypeByName("google.protobuf.FieldOptions"))
    tables = {}
    for file in schema.files:
        if file.package != "master":
            continue
        for descriptor in file.message_types_by_name.values():
            options = message_options.FromString(descriptor.GetOptions().SerializeToString())
            if not options.Extensions[table_option]:
                continue
            keys = [field for field in descriptor.fields
                    if field_options.FromString(field.GetOptions().SerializeToString()).Extensions[pk_option]]
            if not keys:
                raise ValueError(f"Master table has no annotated primary key: {descriptor.name}")
            _identifier(descriptor.name)
            for field in keys:
                _identifier(field.name)
                if field.is_repeated or field.type not in (
                    FieldDescriptor.TYPE_STRING, FieldDescriptor.TYPE_INT32,
                    FieldDescriptor.TYPE_INT64, FieldDescriptor.TYPE_ENUM,
                ):
                    raise ValueError(f"Unsupported master primary key type: {descriptor.name}.{field.name}")
            if descriptor.name in tables:
                raise ValueError("Duplicate master table names in schema")
            tables[descriptor.name] = descriptor, keys
    if not tables:
        raise ValueError("Schema has no annotated master tables")
    return tables




def _sqlcipher_driver():
    try:
        from sqlcipher3 import dbapi2
    except ImportError:
        raise ValueError("Install master-pack support: uv sync --extra master") from None
    connection = dbapi2.connect(":memory:")
    try:
        result = connection.execute("PRAGMA cipher_version").fetchone()
    finally:
        connection.close()
    if not result or not str(result[0]).startswith("4."):
        raise ValueError("Master packs require a SQLCipher 4 driver")
    return dbapi2, result[0]


def build_master_packs(schema, master_dir: Path, output: Path, *, tables: list[str] | None = None) -> dict:
    """Build an offline archive in a new output directory, preserving the input.

    A full build requires exactly the tables marked master.table by the client.
    ``tables`` enables explicit small prototypes. Keys are local format keys,
    deterministically derived from the schema/source identity, not credentials.
    """
    master_dir, output = Path(master_dir), Path(output)
    if output.exists():
        raise ValueError("Master output already exists; choose a new output directory")
    inventory = _annotated_tables(schema)
    sources = {file.stem: file for file in master_dir.glob("*.json")}
    if tables is None:
        missing, extra = inventory.keys() - sources.keys(), sources.keys() - inventory.keys()
        if missing or extra:
            raise ValueError(f"Master JSON inventory does not match schema (missing {len(missing)}, extra {len(extra)})")
        selected = sorted(inventory)
    else:
        if not tables or len(tables) != len(set(tables)):
            raise ValueError("Prototype table selection must be nonempty and unique")
        selected = sorted(tables)
        if any(name not in inventory or name not in sources for name in selected):
            raise ValueError("A selected master table is missing from schema or JSON source")
    inputs = [{"table": name, "source_sha256": _digest(sources[name].read_bytes())} for name in selected]
    identity = {"builder_version": BUILDER_VERSION, "schema_sha256": schema.fingerprint, "tables": inputs}
    version_hash = _digest(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    version = "local-" + version_hash
    driver, cipher_version = _sqlcipher_driver()
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {"builder_version": BUILDER_VERSION, "version": version, "schema_sha256": schema.fingerprint,
              "cipher_version": cipher_version, "cipher_compatibility": 4,
              "source_version": (master_dir / "!version.txt").read_text().strip() if (master_dir / "!version.txt").is_file() else None,
              "table_count": len(selected), "row_count": 0, "alias_field_count": 0,
              "runtime_verified": False, "tables": []}
    tag = {"version": version, "masterTagPacks": []}
    with tempfile.TemporaryDirectory(prefix=".master-build-", dir=output.parent) as temporary:
        staging = Path(temporary) / "result"
        packs = staging / "assets" / "master"
        packs.mkdir(parents=True)
        for item in inputs:
            name, source_hash = item["table"], item["source_sha256"]
            raw = sources[name].read_bytes()
            if _digest(raw) != source_hash:
                raise ValueError("Master JSON changed during build")
            try:
                rows = json.loads(raw)
            except (ValueError, UnicodeDecodeError):
                raise ValueError(f"Invalid master JSON: {name}") from None
            if not isinstance(rows, list):
                raise ValueError(f"Master table must be a JSON array: {name}")
            descriptor, key_fields = inventory[name]
            message_type = message_factory.GetMessageClass(descriptor)
            filename = name + ".db"
            path = packs / filename
            key = hashlib.sha256(b"idoly-local-master-key-v1\0" + bytes.fromhex(version_hash) + name.encode()).hexdigest()
            # STRING has NUMERIC affinity in SQLite; official packs use it
            # even for protobuf string keys (some real IDs are stored as integers).
            columns = [f"{_identifier(_sql_column_name(field.name))} {'STRING' if field.type == FieldDescriptor.TYPE_STRING else 'INTEGER'}"
                       for field in key_fields]
            columns.append('"data" BLOB')
            columns.append("PRIMARY KEY (" + ", ".join(_identifier(_sql_column_name(field.name)) for field in key_fields) + ")")
            statement = (f"INSERT INTO {_identifier(name)} (" + ", ".join(_identifier(_sql_column_name(field.name)) for field in key_fields)
                         + ', "data") VALUES (' + ", ".join("?" for _ in range(len(key_fields) + 1)) + ")")
            connection = driver.connect(str(path))
            encoded_bytes = aliases = 0
            try:
                connection.execute(f'PRAGMA key = "x\'{key}\'"')
                connection.execute("PRAGMA cipher_compatibility = 4")
                connection.execute("PRAGMA journal_mode = DELETE")
                connection.execute(f"CREATE TABLE {_identifier(name)} (" + ", ".join(columns) + ")")
                for index, row in enumerate(rows):
                    normalized, changes = _normalized_row(name, row, descriptor)
                    try:
                        message = ParseDict(normalized, message_type())
                    except ParseError:
                        raise ValueError(f"Unknown or invalid fields in master table {name} row {index}") from None
                    blob = message.SerializeToString(deterministic=True)
                    try:
                        connection.execute(statement, [getattr(message, field.name) for field in key_fields] + [blob])
                    except driver.IntegrityError:
                        raise ValueError(f"Duplicate or invalid primary key in master table {name} row {index}") from None
                    encoded_bytes += len(blob)
                    aliases += changes
                connection.commit()
                if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                    raise ValueError(f"Generated SQLCipher table failed integrity verification: {name}")
            finally:
                connection.close()
            file_bytes = path.stat().st_size
            report["tables"].append({"table": name, "rows": len(rows), "primary_keys": [field.name for field in key_fields],
                                     "sql_primary_keys": [_sql_column_name(field.name) for field in key_fields],
                                     "source_sha256": source_hash, "encoded_bytes": encoded_bytes,
                                     "file_bytes": file_bytes, "file_sha256": _digest(path.read_bytes()),
                                     "alias_field_count": aliases})
            report["row_count"] += len(rows)
            report["alias_field_count"] += aliases
            tag["masterTagPacks"].append({"type": name, "fileName": filename, "fileSize": file_bytes,
                                          "cryptoKey": key, "downloadUrl": "http://127.0.0.1:8080/master/" + filename})
        (staging / "master-tag.json").write_text(json.dumps(tag, indent=2) + "\n", encoding="utf-8")
        (staging / "build-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        if output.exists():
            raise ValueError("Master output appeared during build; existing data was preserved")
        staging.rename(output)
    return report
