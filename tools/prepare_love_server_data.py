#!/usr/bin/env python3
"""Reproducible finite Love overlay on the exact immutable public server ZIP.

The parent is stdlib-only. Original SQLCipher decoding runs in an isolated
builder process. No endpoint override, account data, mutable Git HEAD or clock
is used to create output bytes. No release or official authentication occurs.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import time
from zipfile import ZipFile, ZipInfo, ZIP_STORED

ROOT = Path(__file__).resolve().parents[1]
BASE_BYTES = 191343014
BASE_SHA256 = "37dbf0fb9bac5d860991753d2e41ff0c269684bfca673ba41e1bcb897651c223"
MANIFEST = "data/payload-manifest.json"
NEW_TABLES = ("LoveHomeAction", "LoveLevel", "LoveStoryEpisode", "LoveColor", "Condition", "EventMission")
RELATED_TABLES = ("LoveHomeAction", "LoveLevel", "LoveStoryEpisode", "LoveColor", "Story", "Setting", "Item",
                  "Character", "Costume", "Area", "Condition", "EventMission")
ADDITIONS = frozenset(["data/master-json/" + name + ".json" for name in NEW_TABLES] + [
    "data/master-json/LoveCatalog.json", "data/love-reference.json", "data/love-adv-proof.json",
    "data/licenses/love-reference-NOTICE.txt", "data/licenses/love-reference-AGPL-3.0.txt"])
SOURCE_FILES = ("tools/prepare_love_server_data.py", "tools/build_server_payload.py", "src/idoly_local/love_catalog.py",
    "data/love-reference.json", "data/love-adv-proof.json", "data/love-reference-NOTICE.txt", "LICENSE")
CHUNK = 65536
MAX_ENTRY = 64 * 1024 * 1024
MAX_TOTAL = 512 * 1024 * 1024
MAX_PROOF = 512 * 1024
MAX_OVERLAY = 32 * 1024 * 1024
STAMP = (2000, 1, 1, 0, 0, 0)


class PreparationError(ValueError):
    pass


def need(value, code):
    if not value:
        raise PreparationError(code)


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def pairs(items):
    result = {}
    for key, value in items:
        need(key not in result, "love_payload_duplicate_json_key")
        result[key] = value
    return result


def decode(raw):
    try:
        return json.loads(raw, object_pairs_hook=pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(PreparationError("love_payload_nonfinite_json")))
    except PreparationError:
        raise
    except Exception:
        raise PreparationError("love_payload_json_invalid") from None


def digest(path, maximum=None):
    value, received = hashlib.sha256(), 0
    with Path(path).open("rb") as stream:
        while block := stream.read(CHUNK):
            received += len(block)
            need(maximum is None or received <= maximum, "love_payload_extent")
            value.update(block)
    return value.hexdigest()


def prefix_digest(path, length):
    value, received = hashlib.sha256(), 0
    with Path(path).open("rb") as stream:
        while received < length:
            block = stream.read(min(CHUNK, length-received))
            need(bool(block), "love_payload_prefix_truncated")
            value.update(block); received += len(block)
    return value.hexdigest()


def inventory(archive):
    rows, total, seen = [], 0, set()
    infos = archive.infolist()
    need(0 < len(infos) <= 1024, "love_payload_inventory_bound")
    for info in infos:
        name = info.filename
        path = PurePosixPath(name)
        mode = (info.external_attr >> 16) & 0xffff
        need(type(name) is str and name.startswith("data/") and "\\" not in name and "\x00" not in name
             and not path.is_absolute() and ".." not in path.parts and str(path) == name.rstrip("/")
             and name not in seen and not info.flag_bits & 1 and stat.S_IFMT(mode) in (0, stat.S_IFREG, stat.S_IFDIR),
             "love_payload_member_rejected")
        seen.add(name)
        need(info.is_dir() == (stat.S_IFMT(mode) == stat.S_IFDIR) or stat.S_IFMT(mode) == 0,
             "love_payload_member_type_differs")
        if info.is_dir():
            need(info.file_size == 0, "love_payload_directory_invalid")
            continue
        total += info.file_size
        need(0 <= info.file_size <= MAX_ENTRY and total <= MAX_TOTAL, "love_payload_inventory_bound")
        value, size = hashlib.sha256(), 0
        with archive.open(info) as stream:
            while block := stream.read(CHUNK):
                size += len(block); need(size <= info.file_size, "love_payload_member_extent")
                value.update(block)
        need(size == info.file_size, "love_payload_member_extent")
        rows.append({"path": name, "bytes": size, "sha256": value.hexdigest()})
    return sorted(rows, key=lambda row: row["path"])


def extract_public(archive, destination):
    prefixes = ("data/protocol/", "data/original-master/", "data/public-tutorial/", "data/public-story/",
                "data/public-octo/", "data/public-octo-ios/", "data/master-json/")
    for info in archive.infolist():
        if info.is_dir() or not info.filename.startswith(prefixes):
            continue
        target = destination / PurePosixPath(info.filename).relative_to("data")
        target.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(info) as incoming, target.open("xb") as outgoing:
            shutil.copyfileobj(incoming, outgoing, CHUNK)


def table_rows(path):
    """Strict incremental JSON-array parser with a finite per-row buffer."""
    decoder = json.JSONDecoder(object_pairs_hook=pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(PreparationError("love_payload_nonfinite_json")))
    with Path(path).open(encoding="utf-8") as stream:
        buffer, eof = "", False
        def fill():
            nonlocal buffer, eof
            block = stream.read(CHUNK)
            eof = not block
            buffer += block
            need(len(buffer) <= 2 * 1024 * 1024, "love_payload_json_row_bound")
        def whitespace():
            nonlocal buffer
            while True:
                buffer = buffer.lstrip()
                if buffer or eof:
                    return
                fill()
        whitespace()
        need(buffer.startswith("["), "love_payload_table_invalid")
        buffer = buffer[1:]
        count, after_comma = 0, False
        while True:
            whitespace()
            if buffer.startswith("]"):
                need(not after_comma, "love_payload_table_invalid")
                buffer = buffer[1:]
                whitespace()
                need(eof and not buffer, "love_payload_table_trailing_data")
                return
            while True:
                try:
                    row, end = decoder.raw_decode(buffer)
                    break
                except json.JSONDecodeError:
                    need(not eof, "love_payload_table_incomplete")
                    fill()
            need(type(row) is dict, "love_payload_table_invalid")
            count += 1
            need(count <= 100000, "love_payload_table_bound")
            yield row
            buffer = buffer[end:]
            whitespace()
            need(buffer.startswith((",", "]")), "love_payload_table_invalid")
            after_comma = buffer.startswith(",")
            if after_comma:
                buffer = buffer[1:]


def semantic_rows(path):
    """Row-wise digest; retained old tables need not change whitespace."""
    value, count = hashlib.sha256(), 0
    for row in table_rows(path):
        raw = canonical(row)
        value.update(struct.pack(">I", len(raw))); value.update(raw)
        count += 1
    return count, value.hexdigest()


def canonical_table(source, target):
    with Path(target).open("xb") as stream:
        stream.write(b"[")
        for index, row in enumerate(table_rows(source)):
            if index:
                stream.write(b",")
            stream.write(canonical(row))
        stream.write(b"]")


def blob_row(name, value):
    if isinstance(value, Path):
        return {"path": name, "bytes": value.stat().st_size, "sha256": digest(value, MAX_ENTRY)}
    return {"path": name, "bytes": len(value), "sha256": hashlib.sha256(value).hexdigest()}


def run_builder(data, output):
    args = [sys.executable, "-B", str(ROOT / "tools/build_server_payload.py"), "--data-dir", str(data), "--output", str(output)]
    for flag, folder in (("--octo-data", "public-octo"), ("--ios-octo-data", "public-octo-ios")):
        if (data / folder / "settings.json").is_file() and (data / folder / "manifest.pb").is_file():
            args.extend((flag, str(data / folder)))
    log = output.with_suffix(".builder.log")
    with log.open("xb") as stream:
        process = subprocess.Popen(args, stdout=stream, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        deadline = time.monotonic() + 600
        try:
            while process.poll() is None:
                need(time.monotonic() < deadline and log.stat().st_size <= 2 * 1024 * 1024, "love_payload_builder_bound")
                time.sleep(0.1)
            if process.returncode != 0:
                # All inputs are public app data, before any credential prompt.
                with log.open("rb") as incoming:
                    incoming.seek(max(0, log.stat().st_size - 16384))
                    sys.stderr.write(incoming.read(16384).decode("utf-8", errors="replace"))
                raise PreparationError("love_payload_builder_failed")
        finally:
            if process.poll() is None:
                process.kill(); process.wait(timeout=5)


def component_sources():
    return {name: digest(ROOT / name, MAX_ENTRY) for name in sorted(SOURCE_FILES)}


def write_stored(archive, name, raw):
    info = ZipInfo(name, STAMP)
    info.compress_type = ZIP_STORED
    info.create_system, info.create_version, info.extract_version = 3, 20, 20
    info.external_attr, info.internal_attr = 0o100644 << 16, 0
    info.extra = info.comment = b""
    if isinstance(raw, Path):
        info.file_size = raw.stat().st_size
        with raw.open("rb") as incoming, archive.open(info, "w") as outgoing:
            shutil.copyfileobj(incoming, outgoing, CHUNK)
    else:
        archive.writestr(info, raw, compress_type=ZIP_STORED)


def verify_prepared_overlay(path):
    """The native apply path accepts only the checked-in, source-frozen pin."""
    spec = importlib.util.spec_from_file_location("idoly_love_payload_pin", ROOT / "tools/love_server_data_pin.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.verify_overlay(path)


def compile_overlay(old, stage, output):
    """Explicit Linux preparation only; never executed by a native build."""
    data = stage / "data"
    data.mkdir()
    extract_public(old, data)
    generated = stage / "fresh-ServerData.zip"
    run_builder(data, generated)
    values = {}
    with ZipFile(generated) as fresh:
        fresh_catalog = decode(fresh.read("data/master-json/LoveCatalog.json"))
        for table in RELATED_TABLES:
            name = "data/master-json/" + table + ".json"
            fresh_path = stage / ("fresh-" + table + ".json")
            with fresh.open(name) as incoming, fresh_path.open("xb") as outgoing:
                shutil.copyfileobj(incoming, outgoing, CHUNK)
            retained = data / "master-json" / (table + ".json")
            if retained.exists():
                need(semantic_rows(retained) == semantic_rows(fresh_path), "love_payload_original_table_differs")
            else:
                need(table in NEW_TABLES, "love_payload_original_prerequisite_missing")
                canonical_table(fresh_path, retained)
            if table in NEW_TABLES:
                values[name] = retained
        # Bind to exact preserved base table bytes, not incidental JSON layout
        # from the isolated decoder or mutable temporary filesystem metadata.
        fresh_catalog["source_files"] = {table + ".json": digest(data / "master-json" / (table + ".json")) for table in RELATED_TABLES}
        fresh_catalog.pop("ruleset_sha256", None)
        fresh_catalog["ruleset_sha256"] = hashlib.sha256(canonical(fresh_catalog)).hexdigest()
        values["data/master-json/LoveCatalog.json"] = canonical(fresh_catalog)
        for name in sorted(ADDITIONS):
            if not name.startswith("data/master-json/"):
                values[name] = fresh.read(name)
    need(set(values) == ADDITIONS, "love_payload_overlay_scope")
    created = False
    try:
        with ZipFile(output, "x") as archive:
            created = True
            for name, value in sorted(values.items()):
                write_stored(archive, name, value)
        need(Path(output).stat().st_size <= MAX_OVERLAY, "love_payload_overlay_bound")
    except BaseException:
        if created and Path(output).is_file() and not Path(output).is_symlink():
            Path(output).unlink()
        raise


def read_overlay(path, stage, old_map):
    need(Path(path).is_file() and not Path(path).is_symlink() and
         Path(path).stat().st_size <= MAX_OVERLAY, "love_payload_overlay_bound")
    values = {}
    with ZipFile(path) as archive:
        rows = inventory(archive)
        need({row["path"] for row in rows} == ADDITIONS and len(archive.infolist()) == len(ADDITIONS)
             and sum(row["bytes"] for row in rows) <= MAX_OVERLAY, "love_payload_overlay_scope")
        for info in archive.infolist():
            need(info.compress_type == ZIP_STORED and info.date_time == STAMP and not info.extra and not info.comment
                 and info.create_system == 3 and info.external_attr == 0o100644 << 16,
                 "love_payload_overlay_format_differs")
            target = stage / "overlay" / PurePosixPath(info.filename)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as incoming, target.open("xb") as outgoing:
                shutil.copyfileobj(incoming, outgoing, CHUNK)
            values[info.filename] = target
    catalog_path = values["data/master-json/LoveCatalog.json"]
    need(catalog_path.stat().st_size <= MAX_PROOF, "love_payload_catalog_bound")
    catalog = decode(catalog_path.read_bytes())
    unsigned = dict(catalog); claimed = unsigned.pop("ruleset_sha256", None)
    need(claimed == hashlib.sha256(canonical(unsigned)).hexdigest(), "love_payload_catalog_digest_differs")
    sources = catalog.get("source_files", {})
    need(set(sources) == {name + ".json" for name in RELATED_TABLES}, "love_payload_catalog_sources_differs")
    overlay_rows = {row["path"]: row for row in rows}
    for name, expected in sources.items():
        member = "data/master-json/" + name
        actual = old_map.get(member, overlay_rows.get(member))
        need(actual is not None and actual["sha256"] == expected, "love_payload_catalog_sources_differs")
    prepared = {"bytes": Path(path).stat().st_size, "sha256": digest(path, MAX_OVERLAY), "members": rows}
    return values, catalog, prepared


def upgrade_server_data(base_zip, output_zip, *, report_path=None, overlay_zip=None, prepare_overlay=None):
    base_zip, output_zip = Path(base_zip), Path(output_zip)
    need((overlay_zip is None) != (prepare_overlay is None), "love_payload_overlay_mode_required")
    if overlay_zip is not None:
        expected_overlay = verify_prepared_overlay(Path(overlay_zip))
    else:
        need(not Path(prepare_overlay).exists() and not Path(prepare_overlay).is_symlink(),
             "love_payload_fresh_overlay_required")
    need(base_zip.is_file() and not base_zip.is_symlink() and base_zip.stat().st_size == BASE_BYTES
         and digest(base_zip) == BASE_SHA256, "love_payload_base_pin_differs")
    need(not output_zip.exists() and not output_zip.is_symlink()
         and (report_path is None or not Path(report_path).exists()), "love_payload_fresh_output_required")
    source_pins = component_sources()
    source_sha = hashlib.sha256(canonical(source_pins)).hexdigest()
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    created_output, created_report, created_overlay = False, False, False
    try:
        with tempfile.TemporaryDirectory(prefix=".love-payload-", dir=output_zip.parent) as temporary:
            stage = Path(temporary)
            with ZipFile(base_zip) as old:
                old_rows = inventory(old)
                old_map = {row["path"]: row for row in old_rows}
                need(MANIFEST in old_map, "love_payload_manifest_missing")
                manifest = decode(old.read(MANIFEST))
                need(type(manifest) is dict and type(manifest.get("schema")) is int and manifest["schema"] == 1,
                     "love_payload_manifest_invalid")
                declared = set()
                for row in manifest.get("files", []):
                    need(type(row) is dict and row.get("path") in old_map and row["path"] not in declared
                         and old_map[row["path"]]["bytes"] == row.get("bytes")
                         and old_map[row["path"]]["sha256"] == row.get("sha256"), "love_payload_old_manifest_differs")
                    declared.add(row["path"])
                need(bool(declared), "love_payload_old_manifest_invalid")
                old_prefix_bytes = old.start_dir
                old_meta = {i.filename: (i.CRC, i.compress_type, i.file_size, i.compress_size, i.header_offset,
                                        i.date_time, i.external_attr, i.extra, i.comment) for i in old.infolist() if i.filename != MANIFEST}
                if prepare_overlay is not None:
                    compile_overlay(old, stage, Path(prepare_overlay))
                    created_overlay = True
                    selected_overlay = Path(prepare_overlay)
                else:
                    selected_overlay = Path(overlay_zip)
            additions, fresh_catalog, prepared_overlay = read_overlay(selected_overlay, stage, old_map)
            if overlay_zip is not None:
                need(prepared_overlay == expected_overlay, "love_payload_overlay_pin_differs")
            for name in list(additions):
                if name in old_map:
                    need(old_map[name] == blob_row(name, additions[name]),
                         "love_payload_old_entry_would_change")
                    del additions[name]
            unchanged = {row["path"]: {"bytes": row["bytes"], "sha256": row["sha256"],
                "compress_type": old_meta[row["path"]][1], "crc32": old_meta[row["path"]][0]}
                for row in old_rows if row["path"] != MANIFEST}
            files = {row["path"]: row for row in old_rows if row["path"] != MANIFEST}
            files.update({name: blob_row(name, raw) for name, raw in additions.items()})
            manifest["files"] = [files[name] for name in sorted(files)]
            tables = dict(manifest.get("tables", {}))
            for table in NEW_TABLES:
                tables[table] = semantic_rows(stage / "overlay/data/master-json" / (table + ".json"))[0]
            manifest["tables"] = tables
            episodes = [episode for event in fresh_catalog["events"].values() for episode in event["episodes"].values()]
            assets = {episode["storyAssetId"] for episode in episodes}
            observed = {episode["storyAssetId"] for episode in episodes if episode["advEvidence"]["available"] is True}
            missing = sorted(assets - observed)
            need((len(fresh_catalog["events"]), len(episodes), len(assets), len(observed), missing) ==
                 (6, 72, 69, 68, ["love_2411_04_02"]), "love_payload_catalog_extent_differs")
            love = {"master_version": fresh_catalog["master_version"], "schema_sha256": fresh_catalog["schema_sha256"],
                "ruleset_sha256": fresh_catalog["ruleset_sha256"], "events": len(fresh_catalog["events"]), "episodes": len(episodes),
                "unique_adv_assets": len(assets), "observed_adv_assets": len(observed), "missing_adv_assets": missing}
            manifest["love_catalog"] = love
            manifest["source_overlay"] = {"schema": 1, "operation": "love-source-overlay-v1",
                "base_sha256": BASE_SHA256, "base_bytes": BASE_BYTES, "component_sources": source_pins,
                "component_sources_sha256": source_sha}
            manifest_raw = canonical(manifest)
            need(len(manifest_raw) <= MAX_PROOF, "love_payload_manifest_bound")
            with base_zip.open("rb") as incoming, output_zip.open("xb") as outgoing:
                created_output = True
                shutil.copyfileobj(incoming, outgoing, CHUNK)
            with ZipFile(output_zip, "a") as target:
                target.filelist = [row for row in target.filelist if row.filename != MANIFEST]
                target.NameToInfo = {row.filename: row for row in target.filelist}
                for name, raw in sorted({**additions, MANIFEST: manifest_raw}.items()):
                    write_stored(target, name, raw)
            old_prefix_sha = prefix_digest(base_zip, old_prefix_bytes)
            need(prefix_digest(output_zip, old_prefix_bytes) == old_prefix_sha, "love_payload_old_compressed_records_changed")
            with ZipFile(output_zip) as result:
                rows = inventory(result); by_name = {row["path"]: row for row in rows}
                need(len(result.namelist()) == len(set(result.namelist())), "love_payload_duplicate_output")
                for name, meta in old_meta.items():
                    info = result.getinfo(name)
                    need((info.CRC, info.compress_type, info.file_size, info.compress_size, info.header_offset,
                          info.date_time, info.external_attr, info.extra, info.comment) == meta, "love_payload_old_metadata_changed")
                need(all(by_name[name] == old_map[name] for name in unchanged), "love_payload_old_bytes_changed")
                names = sorted(result.namelist())
            need(component_sources() == source_pins and base_zip.stat().st_size == BASE_BYTES and digest(base_zip) == BASE_SHA256,
                 "love_payload_source_changed")
            def table_names(member_names):
                return sorted(PurePosixPath(name).stem for name in member_names
                    if name.startswith("data/master-json/") and name.endswith(".json") and name.count("/") == 2)
            new_tables, old_tables = table_names(names), table_names(old_map)
            member_rows = [row for row in rows if row["path"] != MANIFEST]
            report = {"schema": 1, "status": "PASS", "operation": "love-source-overlay-v1",
                "base": {"bytes": BASE_BYTES, "sha256": BASE_SHA256, "entries": len(old_meta)+1, "master_json_tables": len(old_tables)},
                "output": {"bytes": output_zip.stat().st_size, "sha256": digest(output_zip), "entries": len(names),
                    "master_json_tables": len(new_tables), "payload_manifest_sha256": hashlib.sha256(manifest_raw).hexdigest(),
                    "member_inventory_sha256": hashlib.sha256(canonical(member_rows)).hexdigest(),
                    "member_names": names, "master_json_table_names": new_tables},
                "component_sources": source_pins, "component_sources_sha256": source_sha,
                "prepared_overlay": prepared_overlay,
                "unchanged_old_entries": {"count": len(unchanged), "content_manifest_sha256": hashlib.sha256(canonical(unchanged)).hexdigest(),
                    "local_record_prefix_bytes": old_prefix_bytes, "local_record_prefix_sha256": old_prefix_sha, "verified": True},
                "added_members": [files[name] for name in sorted(additions)], "replaced_members": [MANIFEST], "love_catalog": love,
                "determinism": {"format": "zip-stored-append-v1", "new_entry_timestamp": "2000-01-01T00:00:00",
                                "old_compressed_records_preserved": True}}
            raw_report = canonical(report)
            need(len(raw_report) <= MAX_PROOF, "love_payload_proof_bound")
            if report_path is not None:
                with Path(report_path).open("xb") as stream:
                    created_report = True
                    stream.write(raw_report + b"\n")
            return report
    except BaseException:
        if created_output and output_zip.exists() and not output_zip.is_symlink():
            output_zip.unlink()
        if created_report and Path(report_path).exists() and not Path(report_path).is_symlink():
            Path(report_path).unlink()
        if created_overlay and Path(prepare_overlay).exists() and not Path(prepare_overlay).is_symlink():
            Path(prepare_overlay).unlink()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-zip", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--overlay-zip", type=Path, help="Apply the exact checked-in, statically pinned public overlay")
    mode.add_argument("--prepare-overlay", type=Path, help="Explicit Linux data preparation output; requires original master decoder")
    args = parser.parse_args()
    report = upgrade_server_data(args.base_zip, args.output, report_path=args.report,
        overlay_zip=args.overlay_zip, prepare_overlay=args.prepare_overlay)
    print(json.dumps({"status": "PASS", "bytes": report["output"]["bytes"], "sha256": report["output"]["sha256"],
        "events": report["love_catalog"]["events"], "episodes": report["love_catalog"]["episodes"],
        "unchanged_old_entries": report["unchanged_old_entries"]["count"]}))


if __name__ == "__main__":
    main()
