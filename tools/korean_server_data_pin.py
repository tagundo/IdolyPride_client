"""Verify and apply the frozen Korean master-only refresh with the stdlib.

The original latest cohort pin remains authoritative for every original member.
Only six Korean metadata files, their generated packs and the payload manifest
may change. SQLCipher is a compilation dependency, never an application one.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import tempfile
import zlib
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
POLICY = "korean-master-refresh-v1"
PIN_PATH = ROOT / "data/korean-master-data-pin.json"
OVERLAY_PATH = ROOT / "data/korean-master-overlay.zip"
REVISION = "11ecceb451833b81c614f666a3667be0d08e0281"
REPOSITORY = "https://github.com/Project-Hoshimi/ipr-translation-data-ko"
SOURCE_ARCHIVE = {"bytes": 160873732, "sha256": "9a52f6a05c460f7fd22146ebd5076a20b43c7a992edf9143e5ab70c3a7eb95ea"}
MANIFEST = "data/payload-manifest.json"
PREFIX = "data/original-master/languages/ko/"
METADATA = frozenset(PREFIX + name for name in (
    "master-tag.json", "media-master-tag.json", "coverage.json", "media-coverage.json",
    "master-sort.json", "media-master-sort.json"))
COMPONENTS = (
    "tools/prepare_korean_master_data.py", "tools/korean_server_data_pin.py",
    "src/idoly_local/master_translation_build.py", "src/idoly_local/master_sort_build.py",
    "src/idoly_local/master_sort.py", "src/idoly_local/master_build.py",
    "src/idoly_local/schema.py", "pyproject.toml", "uv.lock")
MIB = 1024 * 1024
STAMP = (2000, 1, 1, 0, 0, 0)


class KoreanMasterDataError(ValueError):
    pass


def need(value, code):
    if not value:
        raise KoreanMasterDataError(code)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def latest():
    spec = importlib.util.spec_from_file_location("korean_original_latest_pin", ROOT / "tools/latest_server_data_pin.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def file_pin(path):
    path = Path(path)
    need(path.is_file() and not path.is_symlink(), "korean_regular_file_required")
    return {"bytes": path.stat().st_size, "sha256": digest(path)}


def source_hashes():
    return {name: digest(ROOT / name) for name in sorted(COMPONENTS)}


def allowed_overlay(name):
    return name in METADATA or bool(re.fullmatch(
        r"data/original-master/assets/master/(?:local-language-ko-[0-9a-f]{24}-[A-Za-z][A-Za-z0-9_]*|menu-sort-v1-ko-(?:normal|media)-(?:Costume|PhotoQuestMusic)-(?:original|recent|old|title|id)-[0-9a-f]{24})\.db", name))


def archive_rows(archive, *, overlay=False):
    """Stream every bounded regular member, rejecting ambiguous ZIP names."""
    helper = latest()
    infos = archive.infolist()
    need(0 < len(infos) <= 2048, "korean_zip_member_bound")
    names = [info.filename for info in infos]
    need(len(set(name.casefold() for name in names)) == len(names), "korean_zip_duplicate_member")
    rows, total = [], 0
    for info in sorted(infos, key=lambda item: item.filename):
        name = info.filename
        need(name == info.orig_filename and helper._public_name(name)
             and (not overlay or allowed_overlay(name)) and not info.is_dir()
             and stat.S_IFMT(info.external_attr >> 16) in (0, stat.S_IFREG)
             and not info.flag_bits & 1 and info.compress_type in (0, 8), "korean_zip_member_invalid")
        total += info.file_size
        need(0 <= info.file_size <= 64*MIB and total <= 1024*MIB
             and (info.file_size or name == helper.EMPTY_PUBLIC_RESPONSE), "korean_zip_extent")
        value, count = hashlib.sha256(), 0
        with archive.open(info) as stream:
            while block := stream.read(65536):
                count += len(block)
                need(count <= info.file_size, "korean_zip_member_changed")
                value.update(block)
        need(count == info.file_size, "korean_zip_member_changed")
        rows.append({"path": name, "bytes": count, "sha256": value.hexdigest()})
    return rows


def preservation(base_rows, rows):
    old = {row["path"]: row for row in base_rows}
    new = {row["path"]: row for row in rows}
    need(old.keys() <= new.keys(), "korean_original_member_removed")
    changed = sorted(name for name in old if old[name] != new[name])
    added = sorted(new.keys() - old.keys())
    need(set(changed) == METADATA and all(allowed_overlay(name) and name not in METADATA for name in added),
         "korean_preservation_allowlist_differs")
    unchanged = sorted(name for name in old if old[name] == new[name])
    return {"replaced_paths": changed, "added_paths": added, "removed_paths": [],
            "unchanged_members": len(unchanged),
            "unchanged_inventory_sha256": hashlib.sha256(canonical([old[name] for name in unchanged])).hexdigest()}


def load_pin():
    helper = latest()
    original = helper.load_pin()
    pin = helper._json(helper._read(PIN_PATH, 2*MIB))
    need(type(pin) is dict and set(pin) == {"schema", "policy", "base_payload", "source", "source_components",
         "overlay", "output", "preservation", "semantic_proof", "locales"}
         and type(pin["schema"]) is int and pin["schema"] == 1 and pin["policy"] == POLICY,
         "korean_pin_invalid")
    need(pin["base_payload"] == helper.output_pin(), "korean_original_pin_differs")
    need(pin["source_components"] == source_hashes(), "korean_source_component_differs")
    source = pin["source"]
    need(type(source) is dict and source.get("repository") == REPOSITORY and source.get("revision") == REVISION
         and source.get("archive") == SOURCE_ARCHIVE and type(source.get("files")) is dict
         and len(source["files"]) == 90, "korean_translation_source_differs")
    for name, row in source["files"].items():
        need(bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*\.json", name)) and type(row) is dict
             and set(row) == {"bytes", "sha256", "git_blob_sha1"} and type(row["bytes"]) is int
             and 0 < row["bytes"] <= 8*MIB and helper._sha(row["sha256"])
             and bool(re.fullmatch(r"[0-9a-f]{40}", row["git_blob_sha1"])), "korean_source_file_invalid")
    output = pin["output"]
    helper._output(output)
    need(pin["preservation"] == preservation(original["output"]["members"], output["members"]),
         "korean_preservation_differs")
    overlay = pin["overlay"]
    expected_rows = [row for row in output["members"] if row["path"] in
                     set(pin["preservation"]["replaced_paths"] + pin["preservation"]["added_paths"])]
    need(type(overlay) is dict and set(overlay) == {"bytes", "sha256", "members"}
         and type(overlay["bytes"]) is int and 0 < overlay["bytes"] <= 64*MIB
         and helper._sha(overlay["sha256"]) and overlay["members"] == expected_rows,
         "korean_overlay_pin_invalid")
    proof = pin["semantic_proof"]
    need(type(proof) is dict and proof.get("status") == "PASS"
         and proof.get("schema_sha256") == helper.SCHEMA_SHA256
         and proof.get("master_version") == helper.MASTER_VERSION
         and proof.get("raw_compile_repeat_byte_identity_claim") is False
         and proof.get("sqlcipher_bytes_frozen") is True
         and set(proof.get("modes", {})) == {"normal", "media"}
         and set(pin["locales"]) == {"normal", "media"}, "korean_semantic_proof_invalid")
    for mode, evidence in proof["modes"].items():
        need(evidence.get("readback_verified") is True and evidence.get("untranslated_pack_entries_preserved") is True
             and evidence.get("translated_tables") == len(evidence.get("tables", {})) > 0
             and evidence.get("sort_variants") == 9 and len(evidence.get("sorts", {})) == 9,
             "korean_semantic_mode_invalid")
        for row in [*evidence["tables"].values(), *evidence["sorts"].values()]:
            need(row.get("expected_rows_sha256") == row.get("readback_rows_sha256")
                 and helper._sha(row.get("readback_rows_sha256")) and type(row.get("rows")) is int
                 and row["rows"] > 0, "korean_semantic_readback_differs")
    return deepcopy(pin)


def output_pin():
    row = load_pin()["output"]
    return {key: row[key] for key in ("bytes", "sha256")}


def refresh_proof(pin=None):
    pin = load_pin() if pin is None else pin
    return {"schema": 1, "status": "PASS", "policy": POLICY, "base_payload": pin["base_payload"],
            "output": {key: pin["output"][key] for key in ("bytes", "sha256")},
            "source_revision": REVISION, "preservation": pin["preservation"],
            "semantic_proof_sha256": hashlib.sha256(canonical(pin["semantic_proof"])).hexdigest()}


def verify_refresh_proof(proof):
    need(proof == refresh_proof(), "korean_refresh_proof_differs")
    return deepcopy(proof)


def payload_pin():
    pin = load_pin()
    return {"schema": 1, "policy": POLICY, **output_pin(),
            "manifest_sha256": pin["output"]["payload_manifest_sha256"],
            "master_version": latest().MASTER_VERSION}


def verify_overlay(path=OVERLAY_PATH):
    pin = load_pin()["overlay"]
    need(file_pin(path) == {key: pin[key] for key in ("bytes", "sha256")}, "korean_overlay_hash_differs")
    with ZipFile(path) as archive:
        need(archive_rows(archive, overlay=True) == pin["members"], "korean_overlay_members_differ")
    return deepcopy(pin)


def validate_metadata(archive, pin):
    helper = latest()
    manifest = helper._member(archive, MANIFEST)
    original = helper.load_pin()
    need(manifest.get("files") == pin["output"]["members"] and manifest.get("master_version") == helper.MASTER_VERSION,
         "korean_manifest_inventory_differs")
    need(manifest.get("korean_master_refresh") == {"schema": 1, "policy": POLICY, "source": pin["source"],
         "base_payload": pin["base_payload"], "preservation": pin["preservation"],
         "semantic_proof_sha256": hashlib.sha256(canonical(pin["semantic_proof"])).hexdigest()},
         "korean_manifest_refresh_differs")
    need(manifest.get("semantic_controls") == original["upgrade_proof"]["semantic_controls"],
         "korean_original_semantics_differs")
    original_manifest = deepcopy(manifest)
    del original_manifest["korean_master_refresh"]
    original_manifest["files"] = original["output"]["members"]
    original_manifest["locales"]["ko"] = original["upgrade_proof"]["locales"]["ko"]
    need(hashlib.sha256(canonical(original_manifest) + b"\n").hexdigest()
         == original["output"]["payload_manifest_sha256"], "korean_original_manifest_changed")
    inventory = {row["path"]: row for row in pin["output"]["members"]}
    for mode, locale in pin["locales"].items():
        stem = "" if mode == "normal" else "media-"
        helper._tag(archive, PREFIX + stem + "master-tag.json", locale, inventory)
        coverage = helper._member(archive, PREFIX + ("coverage.json" if mode == "normal" else "media-coverage.json"))
        need(coverage.get("source", {}).get("revision") == REVISION
             and coverage.get("source", {}).get("repository") == REPOSITORY
             and coverage.get("source_files") == pin["source"]["files"]
             and coverage.get("version") == locale["tag_version"], "korean_coverage_differs")
        sort = helper._member(archive, PREFIX + stem + "master-sort.json")
        need(sort.get("language") == "ko" and sort.get("source") == mode
             and sort.get("base_version") == locale["tag_version"], "korean_sort_base_differs")
        need(set(sort.get("variants", {})) == {"PhotoQuestMusic", "Costume"}
             and set(sort["variants"]["PhotoQuestMusic"]) == {"recent", "old", "title", "id"}
             and set(sort["variants"]["Costume"]) == {"original", "recent", "old", "title", "id"},
             "korean_sort_inventory_differs")
        for table, choices in sort.get("variants", {}).items():
            for choice, variant in choices.items():
                row = inventory.get("data/original-master/assets/master/" + variant["pack"]["fileName"])
                need(row is not None and row["sha256"] == variant["sha256"]
                     and row["bytes"] == variant["pack"]["fileSize"], "korean_sort_pack_differs")


def verify_payload(path):
    pin = load_pin()
    expected = pin["output"]
    need(file_pin(path) == {key: expected[key] for key in ("bytes", "sha256")}, "korean_payload_hash_differs")
    with ZipFile(path) as archive:
        rows = archive_rows(archive)
        need([row for row in rows if row["path"] != MANIFEST] == expected["members"]
             and [row["path"] for row in rows] == expected["member_names"], "korean_payload_members_differ")
        need(next(row["sha256"] for row in rows if row["path"] == MANIFEST) == expected["payload_manifest_sha256"],
             "korean_payload_manifest_differs")
        validate_metadata(archive, pin)
    return deepcopy(expected)


def write_zip(destination, names, read):
    """Fixed ZIP envelope; encrypted source members are copied byte for byte."""
    with ZipFile(destination, "x", compression=ZIP_DEFLATED, compresslevel=6) as archive:
        for name in sorted(names):
            info = ZipInfo(name, STAMP)
            info.compress_type, info.create_system, info.external_attr = ZIP_DEFLATED, 3, 0o100644 << 16
            archive.writestr(info, read(name), compress_type=ZIP_DEFLATED, compresslevel=6)


def write_composed_payload(destination, names, base, overlay, manifest):
    """Copy frozen compressed streams; perform no native recompression at all.

    Fixed, ordinary ZIP32 records avoid a zlib-version dependency in the final
    payload identity. Only the small new manifest is stored without compression.
    All encrypted and compressed master bytes come directly from frozen inputs.
    """
    names = sorted(names)
    need(len(names) <= 2048 and len(set(names)) == len(names), "korean_zip_member_bound")
    overlay_names = set(overlay.namelist())
    central = []
    date = ((2000 - 1980) << 9) | (1 << 5) | 1
    with Path(destination).open("xb") as outgoing:
        for name in names:
            need(latest()._public_name(name), "korean_zip_member_invalid")
            encoded = name.encode("ascii")
            offset = outgoing.tell()
            if name == MANIFEST:
                method, crc, compressed, size = 0, zlib.crc32(manifest), len(manifest), len(manifest)
                source = None
            else:
                archive = overlay if name in overlay_names else base
                info = archive.getinfo(name)
                source = archive.fp
                source.seek(info.header_offset)
                header = source.read(30)
                need(len(header) == 30, "korean_compressed_source_invalid")
                values = struct.unpack("<4s5H3I2H", header)
                need(values[0] == b"PK\x03\x04" and not values[2] & 1
                     and values[3] == info.compress_type and source.read(values[-2]) == encoded,
                     "korean_compressed_source_invalid")
                source.seek(values[-1], 1)
                method, crc, compressed, size = info.compress_type, info.CRC, info.compress_size, info.file_size
            need(method in (0, 8) and 0 <= compressed <= 64*MIB and 0 <= size <= 64*MIB
                 and offset < 512*MIB, "korean_zip_extent")
            outgoing.write(struct.pack("<4s5H3I2H", b"PK\x03\x04", 20, 0, method, 0, date,
                                       crc, compressed, size, len(encoded), 0))
            outgoing.write(encoded)
            if source is None:
                outgoing.write(manifest)
            else:
                remaining = compressed
                while remaining:
                    block = source.read(min(65536, remaining))
                    need(block, "korean_compressed_source_truncated")
                    outgoing.write(block)
                    remaining -= len(block)
            central.append(struct.pack("<4s6H3I5H2I", b"PK\x01\x02", 20 | 3 << 8, 20, 0, method,
                                       0, date, crc, compressed, size, len(encoded), 0, 0, 0, 0,
                                       0o100644 << 16, offset) + encoded)
        start = outgoing.tell()
        for row in central:
            outgoing.write(row)
        length = outgoing.tell() - start
        outgoing.write(struct.pack("<4s4H2IH", b"PK\x05\x06", 0, 0, len(names), len(names), length, start, 0))
        need(outgoing.tell() <= 512*MIB, "korean_zip_extent")


def refreshed_manifest(base_manifest, pin):
    manifest = deepcopy(base_manifest)
    manifest["files"] = pin["output"]["members"]
    manifest["locales"]["ko"] = pin["locales"]
    manifest["korean_master_refresh"] = {"schema": 1, "policy": POLICY, "source": pin["source"],
        "base_payload": pin["base_payload"], "preservation": pin["preservation"],
        "semantic_proof_sha256": hashlib.sha256(canonical(pin["semantic_proof"])).hexdigest()}
    return canonical(manifest) + b"\n"


def refresh_server_data(input_latest_zip, output_fresh_zip):
    """Strict original validation, bounded KO-only replacement, final full check."""
    helper = latest()
    helper.verify_payload(input_latest_zip)
    pin = load_pin()
    verify_overlay()
    output = Path(output_fresh_zip)
    need(not output.exists() and not output.is_symlink(), "korean_fresh_output_required")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".korean-master-", dir=output.parent) as temporary:
        stage = Path(temporary) / "ServerData.zip"
        with ZipFile(input_latest_zip) as base, ZipFile(OVERLAY_PATH) as overlay:
            manifest = refreshed_manifest(helper._member(base, MANIFEST), pin)
            write_composed_payload(stage, pin["output"]["member_names"], base, overlay, manifest)
        verify_payload(stage)
        need(not output.exists() and not output.is_symlink(), "korean_fresh_output_required")
        os.link(stage, output)
    return refresh_proof(pin)
