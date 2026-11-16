"""Strict source-frozen latest public cohort verification, without data upgrades.

The compiled source blob and final payload have separate roles and identical
bytes. Only explicit CI fetching performs network I/O. No old-cohort fallback,
runtime mutation, source generation, LFS upload, or reference publication exists
in this module.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import struct
import sys
import tempfile
from zipfile import BadZipFile, ZIP_DEFLATED, ZIP_STORED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
PIN_PATH = ROOT / "data/latest-server-data-pin.json"
OVERLAY_PATH = "data/latest-server-overlay.zip"
POLICY = "latest-cohort-overlay-v1"
BASE_BYTES = 191343014
BASE_SHA256 = "37dbf0fb9bac5d860991753d2e41ff0c269684bfca673ba41e1bcb897651c223"
MASTER_VERSION = "6b77e0d8a64b26d5bebd09a7c19a47f2dfad2af914c5160418aa2e7292e13a11"
DESCRIPTOR_SHA256 = "c82cee62abdca7144d11e710a6f773211464a89d2ddede207999a0a5e7aec8ad"
SCHEMA_SHA256 = "0fcf90596261dcd9bbed165bd93859dc30127e2a494e6529bafbd8885675edf3"
SOURCE_COMPONENTS = (
    'tools/prepare_latest_server_data.py',
    'tools/build_server_payload.py',
    'tools/audit_public_master_freshness.py',
    'src/idoly_local/__init__.py',
    'src/idoly_local/schema.py',
    'src/idoly_local/master_build.py',
    'src/idoly_local/collect.py',
    'src/idoly_local/codec.py',
    'src/idoly_local/catalog.py',
    'pyproject.toml',
    'uv.lock',
    'src/idoly_local/media_master_build.py',
    'src/idoly_local/media_outfit_policy.py',
    'src/idoly_local/master_translation_build.py',
    'src/idoly_local/master_sort_build.py',
    'src/idoly_local/master_sort.py',
    'src/idoly_local/media_settings.py',
    'src/idoly_local/love_catalog.py',
    'src/idoly_local/tutorial_replay.py',
    'src/idoly_local/story_catalog.py',
    'src/idoly_local/story_read_rules.py',
    'src/idoly_local/gameplay.py',
    'src/idoly_local/live_assets.py',
    'src/idoly_local/rpc.py',
    'src/idoly_local/octo_manifest.py',
    'src/idoly_local/panorama_rules.py',
    'src/idoly_local/dream.py',
    'src/idoly_local/dream_capture.py',
    'src/idoly_local/live_input.py',
    'src/idoly_local/card_progression.py',
    'src/idoly_local/live_accessories.py',
    'src/idoly_local/cli.py',
    '.github/workflows/prepare-latest-server-data.yml',
    'data/love-reference.json',
    'data/love-adv-proof.json',
    'data/love-reference-NOTICE.txt',
    'LICENSE',
)
SOURCE_FILES = SOURCE_COMPONENTS  # Compatibility alias; no component count is an API.
MIB = 1024*1024
MAX_PIN, MAX_PROOF, MAX_MANIFEST = MIB, 512*1024, 2*MIB
MAX_PAYLOAD, MAX_EXPANDED, MAX_MEMBERS = 512*MIB, 1024*MIB, 2048
MANIFEST = "data/payload-manifest.json"
CHUNK = 64*1024
_DERIVATION = {"kind": "complete-public-member-replacement", "native_apply": "verified-copy",
               "sqlcipher_bytes_frozen": True, "raw_compile_repeat_byte_identity_claim": False}


class LatestServerDataPinError(ValueError):
    """Fixed safe codes only."""


def _need(value, code):
    if not value:
        raise LatestServerDataPinError(code)


def _sha(value):
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _int(value, low=0, high=2**63-1):
    return type(value) is int and low <= value <= high


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        _need(key not in result, "latest_data_json_duplicate")
        result[key] = value
    return result


def _json(raw):
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (UnicodeError, ValueError, RecursionError) as error:
        if isinstance(error, LatestServerDataPinError):
            raise
        raise LatestServerDataPinError("latest_data_json_invalid") from None


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
            and not any(part in ("", ".", "..") for part in path.parts)
            and not any(ord(c) < 32 or c in "\\:" for c in value)
            and not value.endswith("/"))


def _public_name(value):
    if not _name(value):
        return False
    exact = {
        MANIFEST, "data/master-json/!version.txt", "data/protocol/idolypride-6.1.1.pb",
        "data/love-reference.json", "data/love-adv-proof.json",
        "data/love-compatibility.json", "data/love-legacy-rules.json",
        "data/latest-semantic-controls.json",
        "data/licenses/love-reference-AGPL-3.0.txt", "data/licenses/love-reference-NOTICE.txt",
        "data/public-fixtures/manifest.json", "data/public-octo/manifest.pb",
        "data/public-octo/settings.json", "data/public-octo/legacy-manifest.pb",
        "data/public-octo-ios/legacy-manifest.pb", "data/public-octo-ios/manifest.pb",
        "data/public-octo-ios/settings.json", "data/public-story/manifest.json",
        "data/public-story/story-list-event.pb", "data/public-story/story-list-extra.pb",
        "data/public-tutorial/manifest.json", "data/public-tutorial/tutorial-full.pb",
        "data/public-tutorial/tutorial-short.pb"}
    return value in exact or any(re.fullmatch(pattern, value) is not None for pattern in (
        r"data/master-json/[A-Za-z][A-Za-z0-9_]{0,63}\.json",
        r"data/original-master/assets/master/[A-Za-z0-9._-]{1,160}",
        r"data/original-master/(?:master-tag|media-master-tag|archive-report|master-sort|media-master-sort)\.json",
        r"data/original-master/response\.pb",
        r"data/original-master/languages/(?:ko|en)/(?:master-tag|media-master-tag|coverage|media-coverage|master-sort|media-master-sort)\.json",
        r"data/public-fixtures/responses/api\.Master-(?:Rule|GetHelpCategory)-[0-9a-f]{64}\.pb"))


def _names(value):
    return (type(value) is list and len(value) <= MAX_MEMBERS
            and all(_public_name(name) for name in value) and value == sorted(set(value))
            and len({name.casefold() for name in value}) == len(value))


def _regular(path):
    stream = None
    try:
        candidate = Path(path)
        fd = os.open(candidate, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                     | getattr(os, "O_NONBLOCK", 0))
        stream = os.fdopen(fd, "rb")
        before, outer = os.fstat(stream.fileno()), candidate.lstat()
        _need(stat.S_ISREG(before.st_mode) and not stat.S_ISLNK(outer.st_mode)
              and (before.st_dev, before.st_ino) == (outer.st_dev, outer.st_ino),
              "latest_data_file_invalid")
        return stream, before
    except (OSError, TypeError, ValueError):
        if stream is not None:
            stream.close()
        raise LatestServerDataPinError("latest_data_file_invalid") from None


def _unchanged(stream, before):
    after = os.fstat(stream.fileno())
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    _need(all(getattr(before, key) == getattr(after, key) for key in fields), "latest_data_file_changed")


def _digest(stream, size):
    value, count = hashlib.sha256(), 0
    while block := stream.read(CHUNK):
        count += len(block)
        _need(count <= size, "latest_data_file_changed")
        value.update(block)
    _need(count == size, "latest_data_file_changed")
    return value.hexdigest()


def _read(path, bound):
    stream, before = _regular(path)
    with stream:
        _need(0 < before.st_size <= bound, "latest_data_file_bound")
        value = stream.read(bound+1)
        _need(len(value) == before.st_size, "latest_data_file_changed")
        _unchanged(stream, before)
    return value


def _source_hashes():
    result = {}
    for name in SOURCE_COMPONENTS:
        stream, before = _regular(ROOT/name)
        with stream:
            _need(0 < before.st_size <= 4*MIB, "latest_data_source_bound")
            result[name] = _digest(stream, before.st_size)
            _unchanged(stream, before)
    return result


def base_pin():
    return {"bytes": BASE_BYTES, "sha256": BASE_SHA256}


def _row(value):
    return (type(value) is dict and set(value) == {"path", "bytes", "sha256"}
            and _public_name(value["path"]) and _int(value["bytes"], 1, MAX_EXPANDED)
            and _sha(value["sha256"]))


def _output(value):
    keys = {"bytes", "sha256", "entries", "master_json_tables", "payload_manifest_sha256",
            "member_inventory_sha256", "member_names", "master_json_table_names", "members"}
    _need(type(value) is dict and set(value) == keys and _int(value["bytes"], 22, MAX_PAYLOAD)
          and all(_sha(value[key]) for key in ("sha256", "payload_manifest_sha256", "member_inventory_sha256"))
          and _int(value["entries"], 1, MAX_MEMBERS) and _names(value["member_names"])
          and len(value["member_names"]) == value["entries"] and MANIFEST in value["member_names"],
          "latest_data_output_invalid")
    rows = value["members"]
    _need(type(rows) is list and all(_row(row) and row["path"] != MANIFEST for row in rows)
          and [row["path"] for row in rows] == [name for name in value["member_names"] if name != MANIFEST]
          and sum(row["bytes"] for row in rows) <= MAX_EXPANDED
          and hashlib.sha256(_canonical(rows)).hexdigest() == value["member_inventory_sha256"],
          "latest_data_inventory_invalid")
    tables = sorted(name[len("data/master-json/"):-5] for name in value["member_names"]
                    if name.startswith("data/master-json/") and name.endswith(".json"))
    _need(type(value["master_json_tables"]) is int and value["master_json_tables"] == 64
          and len(tables) == 64 and "LoveCatalog" in tables
          and tables == value["master_json_table_names"], "latest_data_tables_differ")


def _pack_rows(value, output):
    _need(type(value) is list and len(value) == 202, "latest_data_master_inventory_invalid")
    types, files = [], set()
    inventory = {row["path"]: row for row in output["members"]}
    for row in value:
        _need(type(row) is dict and set(row) == {"type", "file_name", "bytes", "sha256"}
              and type(row["type"]) is str and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", row["type"])
              and type(row["file_name"]) is str and re.fullmatch(r"[A-Za-z0-9._-]{1,160}", row["file_name"])
              and row["file_name"] not in (".", "..") and row["file_name"] not in files
              and _int(row["bytes"], 1, 64*MIB) and _sha(row["sha256"]),
              "latest_data_master_inventory_invalid")
        actual = inventory.get("data/original-master/assets/master/"+row["file_name"])
        _need(actual is not None and actual["bytes"] == row["bytes"]
              and actual["sha256"] == row["sha256"], "latest_data_master_pack_differs")
        types.append(row["type"]); files.add(row["file_name"])
    _need(types == sorted(set(types)), "latest_data_master_inventory_invalid")


def _base_names():
    raw = _read(ROOT/"data/love-server-data-pin.json", 512*1024)
    _need(len(raw) == 123507 and hashlib.sha256(raw).hexdigest()
          == "f5aa25505e3adbb27497b47f27a96be3eac7b6fc2b006f9ba9652e64c16aba90",
          "latest_data_historical_pin_differs")
    legacy = _json(raw)
    names = set(legacy["output"]["member_names"])
    names.difference_update(row["path"] for row in legacy["upgrade_proof"]["added_members"])
    _need(len(names) == 555 and MANIFEST in names, "latest_data_historical_pin_differs")
    return names


def _controls(value):
    keys = {"story_reads", "media_access", "panorama", "dream", "main_live", "octo"}
    _need(type(value) is dict and set(value) == {"schema", "master_version", "features"}
          and type(value["schema"]) is int and value["schema"] == 1
          and value["master_version"] == MASTER_VERSION and type(value["features"]) is dict
          and set(value["features"]) == keys, "latest_data_semantic_controls_invalid")
    for key, envelope in value["features"].items():
        _need(type(envelope) is dict and set(envelope) == {"status", "scope", "master_version",
                  "schema_sha256", "receipt", "receipt_sha256"}
              and envelope["status"] == "PASS" and envelope["scope"] == key
              and envelope["master_version"] == MASTER_VERSION and envelope["schema_sha256"] == SCHEMA_SHA256
              and type(envelope["receipt"]) is dict and _sha(envelope["receipt_sha256"])
              and len(_canonical(envelope["receipt"])) <= MAX_PROOF
              and hashlib.sha256(_canonical(envelope["receipt"])).hexdigest() == envelope["receipt_sha256"],
              "latest_data_semantic_controls_invalid")


def _proof(report, sources, output):
    keys = {"schema", "status", "operation", "base", "component_sources", "component_sources_sha256",
            "source_blob", "output", "original_master", "love", "locales", "preservation", "derivation", "semantic_controls"}
    _need(type(report) is dict and set(report) == keys and type(report["schema"]) is int
          and report["schema"] == 1 and report["status"] == "PASS" and report["operation"] == POLICY
          and report["component_sources"] == sources
          and report["component_sources_sha256"] == hashlib.sha256(_canonical(sources)).hexdigest()
          and report["output"] == output, "latest_data_proof_invalid")
    _output(output)
    _controls(report["semantic_controls"])
    _need(report["base"] == {**base_pin(), "entries": 555, "master_json_tables": 55}
          and type(report["base"].get("bytes")) is int
          and type(report["base"].get("entries")) is int
          and type(report["base"].get("master_json_tables")) is int, "latest_data_base_differs")
    blob = report["source_blob"]
    _need(type(blob) is dict and set(blob) == {"path", "bytes", "sha256"}
          and type(blob.get("bytes")) is int
          and blob == {"path": OVERLAY_PATH, "bytes": output["bytes"], "sha256": output["sha256"]},
          "latest_data_blob_differs")
    master = report["original_master"]
    _need(type(master) is dict and set(master) == {"version", "schema_sha256", "descriptor_sha256",
              "tag_sha256", "archive_report_sha256", "pack_count", "packs"}
          and master["version"] == MASTER_VERSION and master["schema_sha256"] == SCHEMA_SHA256
          and master["descriptor_sha256"] == DESCRIPTOR_SHA256
          and _sha(master["tag_sha256"]) and _sha(master["archive_report_sha256"])
          and type(master["pack_count"]) is int and master["pack_count"] == 202,
          "latest_data_master_differs")
    _pack_rows(master["packs"], output)
    love = report["love"]
    _need(type(love) is dict and set(love) == {"master_version", "schema_sha256", "ruleset_sha256",
              "events", "episodes", "compatibility"} and love["master_version"] == MASTER_VERSION
          and love["schema_sha256"] == SCHEMA_SHA256 and _sha(love["ruleset_sha256"])
          and type(love["events"]) is int and love["events"] == 6
          and type(love["episodes"]) is int and love["episodes"] == 72, "latest_data_love_invalid")
    compat = love["compatibility"]
    _need(type(compat) is dict and set(compat) == {"path", "sha256", "legacy_ruleset_sha256",
              "legacy_rules_path", "legacy_rules_sha256"}
          and compat["path"] == "data/love-compatibility.json"
          and compat["legacy_rules_path"] == "data/love-legacy-rules.json"
          and all(_sha(compat[key]) for key in ("sha256", "legacy_ruleset_sha256", "legacy_rules_sha256")),
          "latest_data_compatibility_invalid")
    inventory = {row["path"]: row for row in output["members"]}
    controls_path = "data/latest-semantic-controls.json"
    _need(controls_path in inventory and inventory[controls_path]["sha256"]
          == hashlib.sha256(_canonical(report["semantic_controls"])+b"\n").hexdigest(),
          "latest_data_semantic_controls_file_differs")
    for path, wanted in (("data/original-master/master-tag.json", master["tag_sha256"]),
                         ("data/original-master/archive-report.json", master["archive_report_sha256"]),
                         ("data/protocol/idolypride-6.1.1.pb", DESCRIPTOR_SHA256),
                         (compat["path"], compat["sha256"]),
                         (compat["legacy_rules_path"], compat["legacy_rules_sha256"])):
        _need(path in inventory and inventory[path]["sha256"] == wanted, "latest_data_metadata_differs")
    locales = report["locales"]
    _need(type(locales) is dict and set(locales) == {"ja", "ko", "en"}, "latest_data_locales_invalid")
    expected_types = [row["type"] for row in master["packs"]]
    for language, modes in locales.items():
        _need(type(modes) is dict and set(modes) == {"normal", "media"}, "latest_data_locales_invalid")
        prefix = "data/original-master/" + ("" if language == "ja" else "languages/"+language+"/")
        for mode, proof in modes.items():
            _need(type(proof) is dict and set(proof) == {"tag_version", "tag_sha256", "pack_count",
                      "table_names", "sort_manifest_sha256"} and type(proof["tag_version"]) is str
                  and 0 < len(proof["tag_version"]) <= 256 and all(32 <= ord(c) < 127 for c in proof["tag_version"])
                  and _sha(proof["tag_sha256"]) and _sha(proof["sort_manifest_sha256"])
                  and type(proof["pack_count"]) is int and proof["pack_count"] == 202
                  and proof["table_names"] == expected_types, "latest_data_locales_invalid")
            stem = "" if mode == "normal" else "media-"
            for path, digest in ((prefix+stem+"master-tag.json", proof["tag_sha256"]),
                                 (prefix+stem+"master-sort.json", proof["sort_manifest_sha256"])):
                _need(path in inventory and inventory[path]["sha256"] == digest, "latest_data_locale_differs")
    _need(locales["ja"]["normal"]["tag_version"] == MASTER_VERSION
          and locales["ja"]["normal"]["tag_sha256"] == master["tag_sha256"], "latest_data_locale_differs")
    preserve = report["preservation"]
    _need(type(preserve) is dict and set(preserve) == {"unchanged_paths", "replaced_paths", "removed_paths", "added_paths"}
          and all(_names(rows) for rows in preserve.values()), "latest_data_preservation_invalid")
    sets = {key: set(value) for key, value in preserve.items()}
    keys = list(sets)
    old_names, new_names = _base_names(), set(output["member_names"])
    _need(all(not sets[key] & sets[other] for index, key in enumerate(keys) for other in keys[index+1:])
          and sets["unchanged_paths"] | sets["replaced_paths"] == old_names & new_names
          and sets["removed_paths"] == old_names-new_names and sets["added_paths"] == new_names-old_names
          and MANIFEST in sets["replaced_paths"], "latest_data_preservation_invalid")
    derivation = report["derivation"]
    _need(type(derivation) is dict and derivation == _DERIVATION
          and type(derivation["sqlcipher_bytes_frozen"]) is bool
          and type(derivation["raw_compile_repeat_byte_identity_claim"]) is bool, "latest_data_derivation_invalid")


def _pointer(pin):
    row = pin["source_blob"]
    return ("version https://git-lfs.github.com/spec/v1\noid sha256:"+row["sha256"]
            +"\nsize "+str(row["bytes"])+"\n").encode("ascii")


def load_pin():
    _need(PIN_PATH.exists(), "latest_data_pin_missing")
    pin = _json(_read(PIN_PATH, MAX_PIN))
    keys = {"schema", "policy", "base_payload", "component_sources", "output", "preparation", "upgrade_proof", "source_blob"}
    _need(type(pin) is dict and set(pin) == keys and type(pin["schema"]) is int and pin["schema"] == 1
          and pin["policy"] == POLICY and pin["base_payload"] == base_pin()
          and type(pin["base_payload"].get("bytes")) is int, "latest_data_pin_invalid")
    sources = pin["component_sources"]
    _need(type(sources) is dict and set(sources) == set(SOURCE_COMPONENTS)
          and all(_sha(value) for value in sources.values()) and sources == _source_hashes(),
          "latest_data_source_differs")
    _proof(pin["upgrade_proof"], sources, pin["output"])
    _need(pin["source_blob"] == pin["upgrade_proof"]["source_blob"], "latest_data_blob_differs")
    _need(len(_canonical(pin["upgrade_proof"])) <= MAX_PROOF
          and pin["source_blob"] == pin["upgrade_proof"]["source_blob"], "latest_data_proof_bound")
    prep = pin["preparation"]
    _need(type(prep) is dict and set(prep) == {"source_commit", "run_id", "report_sha256"}
          and type(prep["source_commit"]) is str and re.fullmatch(r"[0-9a-f]{40}", prep["source_commit"])
          and _int(prep["run_id"], 1) and _sha(prep["report_sha256"])
          and prep["report_sha256"] == hashlib.sha256(_canonical(pin["upgrade_proof"])+b"\n").hexdigest(),
          "latest_data_preparation_invalid")
    _need(_read(ROOT/OVERLAY_PATH, 256) == _pointer(pin), "latest_data_source_pointer_differs")
    return deepcopy(pin)


def output_pin():
    output = load_pin()["output"]
    return {"bytes": output["bytes"], "sha256": output["sha256"]}


def payload_pin():
    pin = load_pin()
    output = pin["output"]
    return {"schema": 1, "policy": POLICY, "bytes": output["bytes"], "sha256": output["sha256"],
            "manifest_sha256": output["payload_manifest_sha256"],
            "master_version": pin["upgrade_proof"]["original_master"]["version"]}


def overlay_pin():
    blob = load_pin()["source_blob"]
    return {"bytes": blob["bytes"], "sha256": blob["sha256"]}


def verify_source_pointer():
    """Return the source-blob identity after canonical checked-in pointer checks."""
    return overlay_pin()


def verify_upgrade_proof(report):
    try:
        _need(type(report) is dict and len(_canonical(report)) <= MAX_PROOF, "latest_data_proof_bound")
    except (TypeError, ValueError, RecursionError) as error:
        if isinstance(error, LatestServerDataPinError):
            raise
        raise LatestServerDataPinError("latest_data_proof_invalid") from None
    pin = load_pin()
    _proof(report, pin["component_sources"], pin["output"])
    _need(report == pin["upgrade_proof"], "latest_data_proof_differs")
    return deepcopy(report)


def _directory(stream, size):
    width = min(size, 22+65535); stream.seek(size-width); tail = stream.read(width)
    at = tail.rfind(b"PK\x05\x06")
    _need(at >= 0 and at+22 <= len(tail), "latest_data_zip_invalid")
    _, disk, start, count_disk, count, directory_bytes, offset, comment = struct.unpack_from("<4s4H2LH", tail, at)
    end = size-width+at
    _need(disk == start == 0 and count_disk == count and 0 < count <= MAX_MEMBERS
          and at+22+comment == len(tail) and count*46 <= directory_bytes <= 2*MIB
          and offset+directory_bytes == end, "latest_data_zip_bound")
    stream.seek(offset); seen = 0
    while stream.tell() < end:
        fixed = stream.read(46)
        _need(len(fixed) == 46 and fixed[:4] == b"PK\x01\x02", "latest_data_zip_invalid")
        name_width, extra_width, comment_width, item_disk = struct.unpack_from("<4H", fixed, 28)
        seen += 1
        _need(seen <= count and item_disk == 0 and 0 < name_width <= 240
              and stream.tell()+name_width+extra_width+comment_width <= end, "latest_data_zip_bound")
        stream.seek(name_width+extra_width+comment_width, os.SEEK_CUR)
    _need(seen == count and stream.tell() == end, "latest_data_zip_bound")
    return count


def _member(archive, name, maximum=MAX_MANIFEST):
    info = archive.getinfo(name)
    _need(0 < info.file_size <= maximum, "latest_data_metadata_bound")
    return _json(archive.read(info))


def _tag(archive, name, expected, inventory):
    tag = _member(archive, name)
    _need(type(tag) is dict and set(tag) == {"version", "masterTagPacks"}
          and tag.get("version") == expected["tag_version"]
          and type(tag.get("masterTagPacks")) is list and len(tag["masterTagPacks"]) == 202,
          "latest_data_tag_invalid")
    observed, files = [], set()
    for pack in tag["masterTagPacks"]:
        _need(type(pack) is dict and set(pack) == {"type", "fileName", "fileSize", "cryptoKey", "downloadUrl"}
              and type(pack.get("type")) is str and type(pack.get("fileName")) is str
              and type(pack.get("cryptoKey")) is str and 0 < len(pack["cryptoKey"]) <= 256
              and type(pack.get("downloadUrl")) is str and len(pack["downloadUrl"]) <= 2048
              and _int(pack.get("fileSize"), 1, 64*MIB),
              "latest_data_tag_invalid")
        path = "data/original-master/assets/master/"+pack["fileName"]
        row = inventory.get(path)
        _need(row is not None and row["bytes"] == pack["fileSize"] and pack["fileName"] not in files,
              "latest_data_tag_pack_differs")
        observed.append(pack["type"]); files.add(pack["fileName"])
    _need(sorted(observed) == expected["table_names"] and len(set(observed)) == 202,
          "latest_data_tag_inventory_differs")


def verify_payload(path):
    """Verify the complete frozen payload, CRCs, metadata and public inventory."""
    pin = load_pin(); expected = pin["output"]; proof = pin["upgrade_proof"]
    stream, before = _regular(path)
    try:
        with stream:
            _need(before.st_size == expected["bytes"], "latest_data_payload_size_differs")
            _need(_digest(stream, before.st_size) == expected["sha256"], "latest_data_payload_sha256_differs")
            _need(_directory(stream, before.st_size) == expected["entries"], "latest_data_member_count_differs")
            stream.seek(0)
            with ZipFile(stream) as archive:
                infos = archive.infolist()
                _need(sorted(info.filename for info in infos) == expected["member_names"]
                      and len({info.filename.casefold() for info in infos}) == len(infos), "latest_data_members_differ")
                rows, manifest_raw, expanded = [], None, 0
                for info in sorted(infos, key=lambda item: item.filename):
                    mode = info.external_attr >> 16 & 0o170000
                    _need(info.filename == info.orig_filename and _public_name(info.filename)
                          and not info.is_dir() and mode in (0, stat.S_IFREG) and not info.flag_bits & 1
                          and info.compress_type in (ZIP_STORED, ZIP_DEFLATED)
                          and _int(info.file_size, 1, MAX_EXPANDED), "latest_data_zip_member_invalid")
                    expanded += info.file_size
                    _need(expanded <= MAX_EXPANDED, "latest_data_expanded_bound")
                    value, count = hashlib.sha256(), 0
                    capture = bytearray() if info.filename == MANIFEST else None
                    with archive.open(info) as member:
                        while block := member.read(CHUNK):
                            count += len(block)
                            _need(count <= info.file_size, "latest_data_member_changed")
                            value.update(block)
                            if capture is not None:
                                _need(count <= MAX_MANIFEST, "latest_data_manifest_bound"); capture.extend(block)
                    _need(count == info.file_size, "latest_data_member_changed")
                    if capture is not None:
                        manifest_raw = bytes(capture)
                        _need(value.hexdigest() == expected["payload_manifest_sha256"], "latest_data_manifest_differs")
                    else:
                        rows.append({"path": info.filename, "bytes": count, "sha256": value.hexdigest()})
                _need(rows == expected["members"], "latest_data_inventory_differs")
                manifest = _json(manifest_raw)
                _need(type(manifest) is dict and type(manifest.get("schema")) is int
                      and manifest["schema"] == 1 and manifest.get("master_version") == MASTER_VERSION
                      and manifest.get("files") == rows, "latest_data_manifest_inventory_differs")
                overlay = {"schema": 1, "operation": POLICY, "derivation": "complete-public-member-replacement",
                    "base_sha256": BASE_SHA256, "base_bytes": BASE_BYTES, "master_version": MASTER_VERSION,
                    "component_sources": pin["component_sources"],
                    "component_sources_sha256": proof["component_sources_sha256"]}
                _need(manifest.get("source_overlay") == overlay, "latest_data_manifest_source_differs")
                _need(manifest.get("semantic_controls") == proof["semantic_controls"],
                      "latest_data_manifest_semantic_controls_differ")
                _need(type(manifest.get("tables")) is dict
                      and sorted(manifest["tables"]) == [name for name in expected["master_json_table_names"] if name != "LoveCatalog"],
                      "latest_data_manifest_tables_differ")
                inventory = {row["path"]: row for row in rows}
                version = archive.read("data/master-json/!version.txt").decode("utf-8").strip()
                _need(version == MASTER_VERSION, "latest_data_master_version_differs")
                original = _member(archive, "data/original-master/archive-report.json")
                _need(original.get("complete") is True and original.get("master_version") == MASTER_VERSION
                      and original.get("expected_packs") == original.get("completed_packs") == 202,
                      "latest_data_original_archive_invalid")
                packs = original.get("packs")
                _need(type(packs) is dict and sorted(packs) == [row["type"] for row in proof["original_master"]["packs"]],
                      "latest_data_original_archive_invalid")
                for row in proof["original_master"]["packs"]:
                    item = packs[row["type"]]
                    _need(type(item) is dict and item.get("file_name") == row["file_name"]
                          and item.get("size") == row["bytes"] and item.get("sha256") == row["sha256"],
                          "latest_data_original_archive_differs")
                for language, modes in proof["locales"].items():
                    prefix = "data/original-master/" + ("" if language == "ja" else "languages/"+language+"/")
                    for mode, wanted in modes.items():
                        _tag(archive, prefix+("" if mode == "normal" else "media-")+"master-tag.json", wanted, inventory)
                catalog = _member(archive, "data/master-json/LoveCatalog.json")
                _need(catalog.get("master_version") == MASTER_VERSION and catalog.get("schema_sha256") == SCHEMA_SHA256
                      and catalog.get("ruleset_sha256") == proof["love"]["ruleset_sha256"],
                      "latest_data_love_catalog_differs")
                events = catalog.get("events")
                _need(type(events) is dict and len(events) == proof["love"]["events"]
                      and all(type(event) is dict and type(event.get("episodes")) is dict for event in events.values())
                      and sum(len(event["episodes"]) for event in events.values()) == proof["love"]["episodes"],
                      "latest_data_love_catalog_counts_differ")
                unsigned = dict(catalog); claimed = unsigned.pop("ruleset_sha256", None)
                _need(hashlib.sha256(_canonical(unsigned)).hexdigest() == claimed, "latest_data_love_catalog_digest_differs")
                compat = proof["love"]["compatibility"]
                compatibility = _member(archive, compat["path"])
                legacy = _member(archive, compat["legacy_rules_path"])
                _need(type(compatibility) is dict and type(legacy) is dict, "latest_data_compatibility_invalid")
            _unchanged(stream, before)
    except LatestServerDataPinError:
        raise
    except (OSError, ValueError, KeyError, TypeError, BadZipFile, RuntimeError, UnicodeError):
        raise LatestServerDataPinError("latest_data_payload_invalid") from None
    return deepcopy(expected)


def verify_overlay(path):
    """The complete-member compiled source blob is the final public payload."""
    return verify_payload(path)


def _download_overlay(row, destination):
    spec = importlib.util.spec_from_file_location("latest_public_input_fetch", ROOT/"ios-unified/fetch_inputs.py")
    fetch = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = fetch
    spec.loader.exec_module(fetch)
    fetch.lfs_download(row, destination)


def fetch_overlay(path):
    """Explicit CI-only read from the repository's exact LFS object."""
    _need(os.environ.get("GITHUB_ACTIONS") == "true"
          and re.fullmatch(r"[1-9][0-9]*", os.environ.get("GITHUB_RUN_ID", "")) is not None,
          "latest_data_remote_ci_required")
    destination = Path(path)
    _need(not destination.exists() and not destination.is_symlink(), "latest_data_fresh_path_required")
    parent = destination.parent.resolve(strict=True)
    temporary_value = os.environ.get("RUNNER_TEMP", "")
    _need(bool(temporary_value) and Path(temporary_value).is_absolute(), "latest_data_owned_destination_required")
    temporary_root = Path(temporary_value).resolve(strict=True)
    _need(parent.is_relative_to(temporary_root) and parent != ROOT, "latest_data_owned_destination_required")
    pin = overlay_pin()
    owned = Path(tempfile.mkdtemp(prefix=".latest-cohort-", dir=parent))
    try:
        staged = owned/"compiled-source.zip"
        _download_overlay(pin, staged)
        result = verify_overlay(staged)
        _need(not destination.exists() and not destination.is_symlink(), "latest_data_fresh_path_required")
        os.link(staged, destination, follow_symlinks=False)
        return result
    except LatestServerDataPinError:
        raise
    except (OSError, ValueError, KeyError, TypeError):
        raise LatestServerDataPinError("latest_data_fetch_failed") from None
    finally:
        shutil.rmtree(owned)
