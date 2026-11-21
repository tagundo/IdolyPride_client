"""Verify the reproducible Love overlay against a source-frozen public pin.

The old donor is a base input, never proof of the newly packaged payload. This
module is import-safe and uses only the standard library. No absent-pin or
caller-supplied-digest fallback is allowed in production entry points.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import struct
from zipfile import BadZipFile, ZIP_DEFLATED, ZIP_STORED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
PIN_PATH = ROOT / "data/love-server-data-pin.json"
BASE_BYTES = 191343014
BASE_SHA256 = "37dbf0fb9bac5d860991753d2e41ff0c269684bfca673ba41e1bcb897651c223"
POLICY = "love-source-overlay-v1"
MANIFEST = "data/payload-manifest.json"
SOURCE_FILES = (
    "LICENSE", "data/love-adv-proof.json", "data/love-reference-NOTICE.txt",
    "data/love-reference.json", "src/idoly_local/love_catalog.py",
    "tools/build_server_payload.py", "tools/prepare_love_server_data.py",
)
OVERLAY_MEMBERS = frozenset({
    "data/master-json/" + name + ".json" for name in
    ("LoveStoryEpisode", "LoveLevel", "LoveHomeAction", "LoveColor", "Condition", "EventMission", "LoveCatalog")
} | {"data/love-reference.json", "data/love-adv-proof.json",
     "data/licenses/love-reference-NOTICE.txt", "data/licenses/love-reference-AGPL-3.0.txt"})
MIB = 1024 * 1024
MAX_PIN, MAX_MANIFEST = 512 * 1024, 2 * MIB
MAX_PAYLOAD, MAX_EXPANDED, MAX_MEMBERS = 256 * MIB, 512 * MIB, 1024
MAX_OVERLAY = 32 * MIB
OVERLAY_PATH = "data/love-server-overlay.zip"
CHUNK = 64 * 1024


class LoveServerDataPinError(ValueError):
    """Fixed failure codes; no source paths or untrusted exception text."""


def _need(condition, code):
    if not condition:
        raise LoveServerDataPinError(code)


def _sha(value):
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _integer(value, maximum, minimum=0):
    return type(value) is int and minimum <= value <= maximum


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _object(pairs):
    result = {}
    for key, value in pairs:
        _need(key not in result, "love_server_data_json_duplicate")
        result[key] = value
    return result


def _json(raw):
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_object,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (UnicodeError, ValueError, RecursionError) as error:
        if isinstance(error, LoveServerDataPinError):
            raise
        raise LoveServerDataPinError("love_server_data_json_invalid") from None


def _name(value):
    if type(value) is not str:
        return False
    try:
        if not 0 < len(value.encode("utf-8")) <= 240:
            return False
    except UnicodeError:
        return False
    path = PurePosixPath(value)
    return (not path.is_absolute() and str(path) == value
            and all(part not in ("", ".", "..") for part in path.parts)
            and not any(ord(char) < 32 or char in "\\:" for char in value)
            and not value.endswith("/"))


def _regular(path):
    try:
        candidate = Path(path)
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        descriptor = os.open(candidate, flags)
        stream = os.fdopen(descriptor, "rb")
        before = os.fstat(stream.fileno())
        outer = candidate.lstat()
        _need(stat.S_ISREG(before.st_mode) and not stat.S_ISLNK(outer.st_mode)
              and (outer.st_dev, outer.st_ino) == (before.st_dev, before.st_ino),
              "love_server_data_file_invalid")
        return stream, before
    except (OSError, TypeError, ValueError):
        if "stream" in locals():
            stream.close()
        raise LoveServerDataPinError("love_server_data_file_invalid") from None


def _unchanged(stream, before):
    after = os.fstat(stream.fileno())
    _need((after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
          == (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns),
          "love_server_data_file_changed")


def _digest_stream(stream, size):
    digest, count = hashlib.sha256(), 0
    while block := stream.read(CHUNK):
        count += len(block)
        _need(count <= size, "love_server_data_file_changed")
        digest.update(block)
    _need(count == size, "love_server_data_file_changed")
    return digest.hexdigest()


def _source_hashes():
    result = {}
    for name in SOURCE_FILES:
        stream, before = _regular(ROOT / name)
        with stream:
            _need(0 < before.st_size <= 2 * MIB, "love_server_data_source_bound")
            result[name] = _digest_stream(stream, before.st_size)
            _unchanged(stream, before)
    return result


def base_pin():
    """Return the unchanged donor-input identity, even before pin preparation."""
    return {"bytes": BASE_BYTES, "sha256": BASE_SHA256}


def _base(value):
    return (type(value) is dict and set(value) == {"bytes", "sha256"}
            and type(value["bytes"]) is int and value == base_pin())


def _row(row):
    return (type(row) is dict and set(row) == {"path", "bytes", "sha256"}
            and _name(row["path"]) and _integer(row["bytes"], MAX_EXPANDED)
            and _sha(row["sha256"]))


def _names(value):
    return (type(value) is list and 0 < len(value) <= MAX_MEMBERS
            and all(_name(name) for name in value) and value == sorted(set(value)))


def _output(value):
    keys = {"bytes", "sha256", "entries", "master_json_tables",
            "payload_manifest_sha256", "member_inventory_sha256", "member_names",
            "master_json_table_names"}
    _need(type(value) is dict and set(value) == keys
          and _integer(value["bytes"], MAX_PAYLOAD, 22) and _sha(value["sha256"])
          and _sha(value["payload_manifest_sha256"]) and _sha(value["member_inventory_sha256"])
          and _names(value["member_names"]) and MANIFEST in value["member_names"]
          and OVERLAY_MEMBERS <= set(value["member_names"])
          and _integer(value["entries"], MAX_MEMBERS, 1)
          and value["entries"] == len(value["member_names"])
          and type(value["master_json_table_names"]) is list
          and all(type(name) is str and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", name)
                  for name in value["master_json_table_names"])
          and value["master_json_table_names"] == sorted(set(value["master_json_table_names"]))
          and _integer(value["master_json_tables"], 128, 1)
          and value["master_json_tables"] == len(value["master_json_table_names"]),
          "love_server_data_output_invalid")
    names = sorted(name[len("data/master-json/"):-5] for name in value["member_names"]
                   if name.startswith("data/master-json/") and name.endswith(".json"))
    _need(names == value["master_json_table_names"], "love_server_data_tables_differ")


def _overlay(value):
    _need(type(value) is dict and set(value) == {"bytes", "sha256", "members"}
          and _integer(value["bytes"], MAX_OVERLAY, 22) and _sha(value["sha256"])
          and type(value["members"]) is list and len(value["members"]) == len(OVERLAY_MEMBERS)
          and all(_row(row) for row in value["members"])
          and [row["path"] for row in value["members"]] == sorted(OVERLAY_MEMBERS)
          and sum(row["bytes"] for row in value["members"]) < value["bytes"],
          "love_server_data_overlay_invalid")


def _proof(report, sources, output):
    keys = {"schema", "status", "operation", "base", "output", "component_sources",
            "component_sources_sha256", "unchanged_old_entries", "added_members",
            "replaced_members", "love_catalog", "determinism", "prepared_overlay"}
    _need(type(report) is dict and set(report) == keys and type(report["schema"]) is int
          and report["schema"] == 1 and report["status"] == "PASS"
          and report["operation"] == POLICY and report["component_sources"] == sources
          and report["component_sources_sha256"] == hashlib.sha256(_canonical(sources)).hexdigest()
          and report["output"] == output, "love_server_data_proof_invalid")
    _output(report["output"])
    _overlay(report["prepared_overlay"])
    overlay_rows = {row["path"]: row for row in report["prepared_overlay"]["members"]}
    base = report["base"]
    _need(type(base) is dict and set(base) == {"bytes", "sha256", "entries", "master_json_tables"}
          and _base({key: base[key] for key in ("bytes", "sha256")})
          and _integer(base["entries"], MAX_MEMBERS, 1)
          and _integer(base["master_json_tables"], 128, 1), "love_server_data_base_differs")
    preserved = report["unchanged_old_entries"]
    _need(type(preserved) is dict and set(preserved) == {"count", "content_manifest_sha256",
              "local_record_prefix_bytes", "local_record_prefix_sha256", "verified"}
          and type(preserved["verified"]) is bool and preserved["verified"]
          and _integer(preserved["count"], MAX_MEMBERS)
          and preserved["count"] == base["entries"] - 1
          and _sha(preserved["content_manifest_sha256"])
          and _integer(preserved["local_record_prefix_bytes"], BASE_BYTES, 1)
          and _sha(preserved["local_record_prefix_sha256"]), "love_server_data_preservation_invalid")
    additions = report["added_members"]
    _need(type(additions) is list and 0 < len(additions) <= 32
          and all(_row(row) for row in additions)
          and [row["path"] for row in additions] == sorted({row["path"] for row in additions})
          and all(row["path"] in output["member_names"] and row["path"] in OVERLAY_MEMBERS
                  and row == overlay_rows[row["path"]] for row in additions)
          and output["entries"] == base["entries"] + len(additions)
          and output["master_json_tables"] == base["master_json_tables"] + sum(
              row["path"].startswith("data/master-json/") for row in additions)
          and report["replaced_members"] == [MANIFEST], "love_server_data_additions_invalid")
    deterministic = {"format": "zip-stored-append-v1", "new_entry_timestamp": "2000-01-01T00:00:00",
                     "old_compressed_records_preserved": True}
    _need(type(report["determinism"]) is dict and report["determinism"] == deterministic
          and type(report["determinism"]["old_compressed_records_preserved"]) is bool,
          "love_server_data_determinism_invalid")
    catalog = report["love_catalog"]
    catalog_keys = {"ruleset_sha256", "master_version", "schema_sha256", "events", "episodes",
                    "unique_adv_assets", "observed_adv_assets", "missing_adv_assets"}
    _need(type(catalog) is dict and set(catalog) == catalog_keys
          and all(_sha(catalog[key]) for key in ("ruleset_sha256", "master_version", "schema_sha256"))
          and catalog["events"] == 6 and type(catalog["events"]) is int
          and catalog["episodes"] == 72 and type(catalog["episodes"]) is int
          and _integer(catalog["unique_adv_assets"], 128, 1)
          and _integer(catalog["observed_adv_assets"], catalog["unique_adv_assets"])
          and type(catalog["missing_adv_assets"]) is list
          and len(catalog["missing_adv_assets"]) == catalog["unique_adv_assets"] - catalog["observed_adv_assets"]
          and all(type(name) is str and re.fullmatch(r"love_[A-Za-z0-9_-]+", name)
                  for name in catalog["missing_adv_assets"]), "love_server_data_catalog_invalid")


def load_pin():
    """Load and validate the checked-in pin and its exact current component bytes."""
    if not PIN_PATH.exists():
        raise LoveServerDataPinError("love_server_data_pin_missing")
    stream, before = _regular(PIN_PATH)
    with stream:
        _need(0 < before.st_size <= MAX_PIN, "love_server_data_pin_bound")
        raw = stream.read(MAX_PIN + 1)
        _need(len(raw) == before.st_size, "love_server_data_file_changed")
        _unchanged(stream, before)
    pin = _json(raw)
    keys = {"schema", "policy", "base_payload", "component_sources", "output", "preparation", "upgrade_proof", "prepared_overlay"}
    _need(type(pin) is dict and set(pin) == keys and type(pin["schema"]) is int
          and pin["schema"] == 1 and pin["policy"] == POLICY
          and _base(pin["base_payload"]), "love_server_data_pin_invalid")
    sources = pin["component_sources"]
    _need(type(sources) is dict and set(sources) == set(SOURCE_FILES)
          and all(_sha(value) for value in sources.values())
          and sources == _source_hashes(), "love_server_data_source_differs")
    _output(pin["output"])
    prep = pin["preparation"]
    _need(type(prep) is dict and set(prep) == {"source_commit", "run_id", "report_sha256"}
          and type(prep["source_commit"]) is str and re.fullmatch(r"[0-9a-f]{40}", prep["source_commit"])
          and _integer(prep["run_id"], 2**63 - 1, 1) and _sha(prep["report_sha256"]),
          "love_server_data_preparation_invalid")
    _proof(pin["upgrade_proof"], sources, pin["output"])
    overlay = pin["prepared_overlay"]
    _need(type(overlay) is dict and set(overlay) == {"path", "bytes", "sha256", "members"}
          and overlay["path"] == OVERLAY_PATH
          and {key: overlay[key] for key in ("bytes", "sha256", "members")} == pin["upgrade_proof"]["prepared_overlay"],
          "love_server_data_overlay_pin_differs")
    _overlay({key: overlay[key] for key in ("bytes", "sha256", "members")})
    # The producer writes precisely canonical UTF-8 JSON plus one newline.
    # Bind the first-preparation receipt without requiring later jobs to reuse
    # that preparation's source-commit or run identifier.
    _need(prep["report_sha256"] == hashlib.sha256(_canonical(pin["upgrade_proof"]) + b"\n").hexdigest(),
          "love_server_data_preparation_receipt_differs")
    return deepcopy(pin)


def output_pin():
    """The only default packaged ServerData identity; never the donor identity."""
    output = load_pin()["output"]
    return {"bytes": output["bytes"], "sha256": output["sha256"]}


def overlay_pin():
    """The prepared public overlay identity, separate from source-component pins."""
    overlay = load_pin()["prepared_overlay"]
    return {"bytes": overlay["bytes"], "sha256": overlay["sha256"]}


def verify_upgrade_proof(report):
    """Verify a fresh deterministic build receipt, independent of CI run identity."""
    try:
        _need(len(_canonical(report)) <= MAX_PIN, "love_server_data_proof_bound")
    except (TypeError, ValueError, RecursionError):
        raise LoveServerDataPinError("love_server_data_proof_invalid") from None
    pin = load_pin()
    _proof(report, pin["component_sources"], pin["output"])
    _need(report == pin["upgrade_proof"], "love_server_data_proof_differs")
    return deepcopy(report)


def _directory(stream, size):
    length = min(size, 22 + 65535)
    stream.seek(size - length)
    tail = stream.read(length)
    position = tail.rfind(b"PK\x05\x06")
    _need(position >= 0 and position + 22 <= len(tail), "love_server_data_zip_invalid")
    (_signature, disk, start_disk, disk_count, count, width, offset,
     comment) = struct.unpack_from("<4s4H2LH", tail, position)
    end = size - length + position
    _need(not disk and not start_disk and disk_count == count
          and position + 22 + comment == len(tail) and 0 < count <= MAX_MEMBERS
          and count * 46 <= width <= 2 * MIB and offset + width == end,
          "love_server_data_zip_bound")
    stream.seek(offset)
    seen = 0
    while stream.tell() < end:
        fixed = stream.read(46)
        _need(len(fixed) == 46 and fixed[:4] == b"PK\x01\x02", "love_server_data_zip_invalid")
        name_width, extra_width, comment_width, disk = struct.unpack_from("<4H", fixed, 28)
        seen += 1
        _need(seen <= count and not disk and 0 < name_width <= 240
              and stream.tell() + name_width + extra_width + comment_width <= end,
              "love_server_data_zip_bound")
        stream.seek(name_width + extra_width + comment_width, os.SEEK_CUR)
    _need(seen == count and stream.tell() == end, "love_server_data_zip_bound")
    return count


def verify_overlay(path):
    """Verify the checked-in finite public overlay before stdlib-only application."""
    pin = load_pin()
    expected = pin["upgrade_proof"]["prepared_overlay"]
    stream, before = _regular(path)
    try:
        with stream:
            _need(before.st_size == expected["bytes"], "love_server_data_overlay_size_differs")
            _need(_digest_stream(stream, before.st_size) == expected["sha256"],
                  "love_server_data_overlay_sha256_differs")
            _need(_directory(stream, before.st_size) == len(OVERLAY_MEMBERS),
                  "love_server_data_overlay_members_differ")
            stream.seek(0)
            with ZipFile(stream) as archive:
                infos = archive.infolist()
                names = [info.filename for info in infos]
                _need(not archive.comment and len(names) == len(set(names)) and sorted(names) == sorted(OVERLAY_MEMBERS),
                      "love_server_data_overlay_members_differ")
                rows, expanded = [], 0
                for info in sorted(infos, key=lambda value: value.filename):
                    _need(not info.is_dir() and info.compress_type == ZIP_STORED
                          and info.date_time == (2000, 1, 1, 0, 0, 0) and info.create_system == 3
                          and info.external_attr >> 16 == 0o100644 and not info.extra and not info.comment
                          and not info.flag_bits & 1
                          and _integer(info.file_size, MAX_OVERLAY), "love_server_data_overlay_member_invalid")
                    expanded += info.file_size
                    _need(expanded <= MAX_OVERLAY, "love_server_data_overlay_expanded_bound")
                    digest, count = hashlib.sha256(), 0
                    with archive.open(info) as incoming:
                        while block := incoming.read(CHUNK):
                            count += len(block)
                            _need(count <= info.file_size, "love_server_data_member_size_differs")
                            digest.update(block)
                    _need(count == info.file_size, "love_server_data_member_size_differs")
                    rows.append({"path": info.filename, "bytes": count, "sha256": digest.hexdigest()})
                _need(rows == expected["members"], "love_server_data_overlay_inventory_differs")
            _unchanged(stream, before)
    except (OSError, BadZipFile, RuntimeError, EOFError, struct.error):
        raise LoveServerDataPinError("love_server_data_overlay_zip_invalid") from None
    return deepcopy(expected)


def verify_payload(path):
    """Stream-verify the final ZIP, member inventory and internal manifest."""
    pin = load_pin()
    expected = pin["output"]
    stream, before = _regular(path)
    try:
        with stream:
            _need(before.st_size == expected["bytes"], "love_server_data_payload_size_differs")
            _need(_digest_stream(stream, before.st_size) == expected["sha256"],
                  "love_server_data_payload_sha256_differs")
            _need(_directory(stream, before.st_size) == expected["entries"],
                  "love_server_data_member_count_differs")
            preserved = pin["upgrade_proof"]["unchanged_old_entries"]
            remaining, prefix = preserved["local_record_prefix_bytes"], hashlib.sha256()
            _need(remaining < before.st_size, "love_server_data_prefix_bound")
            stream.seek(0)
            while remaining:
                block = stream.read(min(CHUNK, remaining))
                _need(bool(block), "love_server_data_file_changed")
                remaining -= len(block)
                prefix.update(block)
            _need(prefix.hexdigest() == preserved["local_record_prefix_sha256"],
                  "love_server_data_preserved_prefix_differs")
            stream.seek(0)
            with ZipFile(stream) as archive:
                infos = archive.infolist()
                names = [info.filename for info in infos]
                _need(len(names) == len(set(names)) and sorted(names) == expected["member_names"],
                      "love_server_data_members_differ")
                expanded = 0
                rows, manifest_raw, old_rows = [], None, {}
                additions = {row["path"]: row for row in pin["upgrade_proof"]["added_members"]}
                overlay_rows = {row["path"]: row for row in pin["prepared_overlay"]["members"]}
                for info in sorted(infos, key=lambda item: item.filename):
                    mode = info.external_attr >> 16
                    _need(_name(info.filename) and not info.is_dir()
                          and not stat.S_ISLNK(mode) and stat.S_IFMT(mode) in (0, stat.S_IFREG)
                          and not info.flag_bits & 1 and info.compress_type in (ZIP_STORED, ZIP_DEFLATED)
                          and _integer(info.file_size, MAX_EXPANDED), "love_server_data_member_invalid")
                    if info.filename == MANIFEST or info.filename in additions:
                        _need(info.compress_type == ZIP_STORED and info.date_time == (2000, 1, 1, 0, 0, 0)
                              and info.create_system == 3 and mode == 0o100644 and not info.extra and not info.comment,
                              "love_server_data_new_metadata_differs")
                    expanded += info.file_size
                    _need(expanded <= MAX_EXPANDED, "love_server_data_expanded_bound")
                    digest, count = hashlib.sha256(), 0
                    chunks = [] if info.filename == MANIFEST else None
                    with archive.open(info) as incoming:
                        while block := incoming.read(CHUNK):
                            count += len(block)
                            _need(count <= info.file_size, "love_server_data_member_size_differs")
                            digest.update(block)
                            if chunks is not None:
                                _need(count <= MAX_MANIFEST, "love_server_data_manifest_bound")
                                chunks.append(block)
                    _need(count == info.file_size, "love_server_data_member_size_differs")
                    if chunks is not None:
                        manifest_raw = b"".join(chunks)
                        _need(digest.hexdigest() == expected["payload_manifest_sha256"],
                              "love_server_data_manifest_sha256_differs")
                    else:
                        row = {"path": info.filename, "bytes": count, "sha256": digest.hexdigest()}
                        rows.append(row)
                        if info.filename in overlay_rows:
                            _need(row == overlay_rows[info.filename], "love_server_data_overlay_payload_differs")
                        if info.filename in additions:
                            _need(row == additions[info.filename], "love_server_data_added_member_differs")
                        else:
                            old_rows[info.filename] = {"bytes": count, "sha256": digest.hexdigest(),
                                                       "compress_type": info.compress_type, "crc32": info.CRC}
                _need(len(old_rows) == preserved["count"]
                      and hashlib.sha256(_canonical(old_rows)).hexdigest() == preserved["content_manifest_sha256"],
                      "love_server_data_preserved_inventory_differs")
                _need(hashlib.sha256(_canonical(rows)).hexdigest() == expected["member_inventory_sha256"],
                      "love_server_data_inventory_differs")
                manifest = _json(manifest_raw)
                _need(type(manifest) is dict and type(manifest.get("files")) is list
                      and len(manifest["files"]) == len(rows) and all(_row(row) for row in manifest["files"])
                      and sorted(manifest["files"], key=lambda row: row["path"]) == rows,
                      "love_server_data_manifest_files_differ")
                # LoveCatalog is a derived object, rather than a raw master
                # row array. The ZIP inventory counts it; manifest.tables does not.
                raw_tables = [name for name in expected["master_json_table_names"] if name != "LoveCatalog"]
                _need(type(manifest.get("tables")) is dict
                      and sorted(manifest["tables"]) == raw_tables
                      and all(_integer(count, 1000000) for count in manifest["tables"].values()),
                      "love_server_data_manifest_tables_differ")
                overlay = {"schema": 1, "operation": POLICY, "base_sha256": BASE_SHA256,
                           "base_bytes": BASE_BYTES, "component_sources": pin["component_sources"],
                           "component_sources_sha256": pin["upgrade_proof"]["component_sources_sha256"]}
                _need(manifest.get("source_overlay") == overlay
                      and manifest.get("love_catalog") == pin["upgrade_proof"]["love_catalog"],
                      "love_server_data_manifest_provenance_differs")
            _unchanged(stream, before)
    except (OSError, BadZipFile, RuntimeError, EOFError, struct.error):
        raise LoveServerDataPinError("love_server_data_zip_invalid") from None
    return deepcopy(expected)
