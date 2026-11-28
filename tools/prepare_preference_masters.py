#!/usr/bin/env python3
"""Recover two source-bound public preference tables, without rewriting ServerData.

Run on a remote builder with the master extra installed. Only the pinned public
archive is opened; no network, game execution or account directory is involved.
The generated Python module contains data assignments, with JSON decoded lazily
by its consumer. Original SQL row order and every protobuf field are retained.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
SOURCE_BYTES = 191343014
SOURCE_SHA256 = "37dbf0fb9bac5d860991753d2e41ff0c269684bfca673ba41e1bcb897651c223"
SCHEMA_SHA256 = "c82cee62abdca7144d11e710a6f773211464a89d2ddede207999a0a5e7aec8ad"
MASTER_VERSION = "961e456499039e31248a818a911c8d95f92461f86aff4674ba07e29c32afcf60"
PACK_COUNT = 202
TABLES = ("CardImage", "Decoration")
POLICY = "public-preference-master-v1"
MAX_METADATA = 4 * 1024**2
MAX_PACK = 8 * 1024**2
MAX_JSON = 8 * 1024**2
MAX_ROWS = 16384
CHUNK = 65536


def need(ok, message):
    if not ok:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("ascii")


def file_hash(stream):
    stream.seek(0)
    result = hashlib.sha256()
    for block in iter(lambda: stream.read(CHUNK), b""):
        result.update(block)
    return result.hexdigest()


def identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        need(key not in value, "duplicate_json_key")
        value[key] = item
    return value


def json_value(raw):
    return json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object)


def runtime():
    # Keep tool discovery/import free of protobuf and SQLCipher initialization.
    sys.path.insert(0, str(ROOT / "src"))
    from idoly_local.schema import Schema
    from idoly_local.master_build import _sqlcipher_driver
    from idoly_local.master_translation_build import read_master_rows
    driver, version = _sqlcipher_driver()
    return Schema, driver, version, read_master_rows


def read_member(archive, members, name, limit):
    info = members.get(name)
    need(info is not None and 0 < info.file_size <= limit, "public_member_missing_or_oversized: " + name)
    with archive.open(info) as incoming:
        raw = incoming.read(limit + 1)
    need(len(raw) == info.file_size, "public_member_size_differs: " + name)
    return raw


def validate_rows(table, rows, card_ids):
    need(table in TABLES and type(rows) is list and 0 < len(rows) <= MAX_ROWS,
         "preference_table_count_differs")
    identities = set()
    for row in rows:
        need(type(row) is dict, "preference_row_is_not_an_object")
        if table == "CardImage":
            card, display, image = row.get("cardId"), row.get("displayType"), row.get("imageType")
            need(type(card) is str and card in card_ids
                 and type(display) is int and display in (1, 2, 3)
                 and type(image) is int and image in (1, 2, 3), "invalid_card_image_identity_or_enum")
            key = (card, display)
        else:
            key = row.get("id")
            need(type(key) is str and bool(key), "invalid_decoration_identity")
        need(key not in identities, "duplicate_preference_identity")
        identities.add(key)
    encoded = canonical(rows)
    need(len(encoded) <= MAX_JSON, "preference_json_exceeds_bound")
    return encoded


def validate_paths(source, work, outputs):
    paths = (source, work, *outputs)
    need(all(path.is_absolute() and not path.is_symlink() for path in paths),
         "absolute_non_symlink_paths_required")
    resolved = tuple(path.resolve(strict=False) for path in paths)
    need(len(set(resolved)) == len(resolved), "distinct_input_work_and_outputs_required")
    source, work, *outputs = resolved
    need(not work.exists() and all(not path.exists() for path in outputs), "fresh_work_and_outputs_required")
    for path in (work, *outputs):
        need(not path.is_relative_to(ROOT), "generated_files_must_be_outside_source_checkout")
        need(not source.is_relative_to(path), "generated_path_cannot_contain_source")
    need(not any(work.is_relative_to(path) for path in outputs), "output_cannot_contain_work")
    need(work.parent.is_dir() and shutil.disk_usage(work.parent).free >= 128 * 1024**2,
         "public_work_parent_needs_128_MiB_free")
    return source, work, outputs


def prepare(server_data, work, output_json, output_module, report_path):
    server_data, work, outputs = validate_paths(Path(server_data), Path(work),
        (Path(output_json), Path(output_module), Path(report_path)))
    output_json, output_module, report_path = outputs
    fd = os.open(server_data, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as source:
        before = os.fstat(source.fileno())
        need(stat.S_ISREG(before.st_mode) and before.st_size == SOURCE_BYTES, "source_size_differs")
        need(file_hash(source) == SOURCE_SHA256, "source_sha256_differs")
        with ZipFile(source) as archive:
            infos = archive.infolist()
            need(0 < len(infos) <= 1024 and len({row.filename for row in infos}) == len(infos),
                 "source_member_inventory_differs")
            sys.path.insert(0, str(ROOT / "src"))
            from idoly_local.public_payload import member_path
            for row in infos:
                need(not row.is_dir() and not row.flag_bits & 1 and not stat.S_ISLNK(row.external_attr >> 16),
                     "source_member_not_regular")
                member_path(row.filename)
            members = {row.filename: row for row in infos}
            base = "data/original-master/"
            descriptor = read_member(archive, members, "data/protocol/idolypride-6.1.1.pb", MAX_METADATA)
            need(sha(descriptor) == SCHEMA_SHA256, "descriptor_sha256_differs")
            tag_raw = read_member(archive, members, base + "master-tag.json", MAX_METADATA)
            response_raw = read_member(archive, members, base + "response.pb", MAX_METADATA)
            original_report = json_value(read_member(archive, members, base + "archive-report.json", MAX_METADATA))
            tag = json_value(tag_raw)
            need(type(tag) is dict and set(tag) == {"version", "masterTagPacks"}
                 and tag["version"] == MASTER_VERSION and type(tag["masterTagPacks"]) is list
                 and len(tag["masterTagPacks"]) == PACK_COUNT, "complete_original_master_tag_required")
            need(type(original_report) is dict and original_report.get("complete") is True
                 and original_report.get("master_version") == MASTER_VERSION
                 and original_report.get("expected_packs") == original_report.get("completed_packs") == PACK_COUNT
                 and type(original_report.get("packs")) is dict
                 and len(original_report["packs"]) == PACK_COUNT, "original_archive_report_differs")
            packs, filenames = {}, set()
            for pack in tag["masterTagPacks"]:
                need(type(pack) is dict, "original_master_pack_is_not_an_object")
                table, filename = pack.get("type"), pack.get("fileName")
                need(type(table) is str and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table)
                     and type(filename) is str and re.fullmatch(r"[A-Za-z0-9_.-]+", filename)
                     and filename not in (".", "..") and table not in packs and filename not in filenames,
                     "original_master_pack_identity_differs")
                packs[table] = pack
                filenames.add(filename)
            need(set(TABLES).issubset(packs), "preference_master_pack_missing")
            cards = json_value(read_member(archive, members, "data/master-json/Card.json", MAX_METADATA))
            need(type(cards) is list and cards and all(type(row) is dict for row in cards), "card_master_missing")
            card_keys = [row.get("id") for row in cards]
            need(all(type(key) is str and key for key in card_keys), "card_master_identity_differs")
            card_ids = set(card_keys)
            need(len(card_ids) == len(cards), "card_master_identity_differs")
            work.mkdir(mode=0o700)
            (work / ".idoly-public-preference-work.json").write_bytes(canonical({"schema": 1, "policy": POLICY}))
            descriptor_path = work / "schema.pb"
            descriptor_path.write_bytes(descriptor)
            Schema, driver, cipher_version, decode = runtime()
            schema = Schema.from_descriptor_set(descriptor_path)
            from google.protobuf.json_format import ParseDict
            response = schema.response_type("/api.Master/Get").FromString(response_raw)
            need(response.HasField("masterTag"), "original_response_master_tag_absent")
            expected = schema.response_type("/api.Master/Get")()
            ParseDict(tag, expected.masterTag)
            need(expected.masterTag == response.masterTag, "original_response_tag_differs")
            pack_proofs, tables, encoded = {}, {}, {}
            for table in TABLES:
                pack = packs[table]
                raw = read_member(archive, members, base + "assets/master/" + pack["fileName"], MAX_PACK)
                record = original_report["packs"].get(table, {})
                source_identity = [MASTER_VERSION, table, pack["fileName"], pack["fileSize"],
                                   pack["cryptoKey"], pack["downloadUrl"]]
                source_digest = sha(json.dumps(source_identity, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
                need(type(pack["fileSize"]) is int and len(raw) == pack["fileSize"]
                     and record.get("file_name") == pack["fileName"] and record.get("size") == len(raw)
                     and record.get("sha256") == sha(raw) and record.get("source_sha256") == source_digest,
                     "original_pack_provenance_differs: " + table)
                (work / pack["fileName"]).write_bytes(raw)
                rows = decode(schema, driver, work, pack)
                encoded[table] = validate_rows(table, rows, card_ids)
                tables[table] = rows
                pack_proofs[table] = {"file_name": pack["fileName"], "bytes": len(raw), "sha256": sha(raw),
                    "rows": len(rows), "json_bytes": len(encoded[table]), "json_sha256": sha(encoded[table])}
        need(identity(os.fstat(source.fileno())) == identity(before) and file_hash(source) == SOURCE_SHA256,
             "source_changed_during_preparation")
    provenance = {"schema": 1, "policy": POLICY, "master_version": MASTER_VERSION,
        "source": {"bytes": SOURCE_BYTES, "sha256": SOURCE_SHA256},
        "schema_sha256": SCHEMA_SHA256, "packs": pack_proofs}
    document = canonical(dict(provenance, tables=tables)) + b"\n"
    module = ("# Generated by tools/prepare_preference_masters.py from the pinned public archive.\n"
              "# Data only; consumers decode one selected table on demand.\n"
              + "MASTER_VERSION = " + repr(MASTER_VERSION) + "\n"
              + "SOURCE_BYTES = " + repr(SOURCE_BYTES) + "\n"
              + "SOURCE_SHA256 = " + repr(SOURCE_SHA256) + "\n"
              + "SCHEMA_SHA256 = " + repr(SCHEMA_SHA256) + "\n"
              + "PACKS = " + repr(pack_proofs) + "\n"
              + "ROWS_JSON = " + repr({key: value.decode("ascii") for key, value in encoded.items()}) + "\n").encode("ascii")
    need(len(document) <= 2 * MAX_JSON and len(module) <= 2 * MAX_JSON, "generated_output_exceeds_bound")
    result = dict(provenance, status="PASS", input_unchanged=True, sqlcipher_version=cipher_version,
        extraction_scope="descriptor, original tag/response/report, Card JSON, two explicit public packs",
        output={"json": {"bytes": len(document), "sha256": sha(document)},
                "module": {"bytes": len(module), "sha256": sha(module)}},
        source_sha256={name: sha((ROOT / name).read_bytes()) for name in (
            "tools/prepare_preference_masters.py", "src/idoly_local/master_translation_build.py",
            "src/idoly_local/master_build.py", "src/idoly_local/schema.py")})
    for path, raw in ((output_json, document), (output_module, module), (report_path, canonical(result) + b"\n")):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(raw)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("server-data", "work", "output-json", "output-module", "report"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        result = prepare(args.server_data, args.work, args.output_json, args.output_module, args.report)
    except Exception as error:
        print(json.dumps({"schema": 1, "status": "FAIL", "error_type": type(error).__name__,
                          "error": str(error)[:1024]}, ensure_ascii=True))
        return 1
    print(json.dumps({"status": result["status"], "report": str(args.report)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
