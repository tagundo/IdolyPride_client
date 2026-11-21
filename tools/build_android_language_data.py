#!/usr/bin/env python3
"""Build deduplicated Unity Data/static assets for an internal unified APK.

Unity's native VFS reads getPackageCodePath(), not ResourcesLoader assets. The
runtime therefore assembles one selected Data ZIP from these compressed spans.
This is packaging evidence, not proof of an Android device launch.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import re
import struct
from zipfile import ZipFile, ZipInfo, ZIP_STORED, ZIP_DEFLATED
import zlib

LANGUAGES = ("ko", "ja", "en")
PREFIX = "assets/bin/Data/"
INDEX = "assets/idoly-unified/game-data.json"
OBJECTS = "assets/idoly-unified/game-data/"
STRATEGY = "selected-data-zip-v1"
# These exact original assets may be opened through Unity's StreamingAssets ZIP
# path. Java AssetManager still uses the installed APK. Compiled audience-network
# DEX and dexopt profiles are deliberately excluded from the native Data carrier.
STATIC_ASSETS = (
    "assets/UnityServicesProjectConfiguration.json", "assets/WebView/Inquiry.html",
    "assets/WebView/Scripts/Common.js", "assets/WebView/Scripts/Inquiry.js",
    "assets/WebView/Scripts/ResponsiveZoom.js", "assets/WebView/Styles/Common.css",
    "assets/WebView/Styles/Inquiry.css", "assets/WebView/Svg/Pencil.svg",
    "assets/ad-viewer/155.3702126d.js", "assets/ad-viewer/245.b30b6372.js",
    "assets/ad-viewer/44.348bc690.js", "assets/ad-viewer/ad-viewer-vendors.d9d1c22a.js",
    "assets/ad-viewer/ad-viewer.v1.32.14-ad-viewer.html", "assets/ad-viewer/adViewer.375b5d46.js",
    "assets/ad-viewer/config.ad-viewer.json", "assets/ad-viewer/da_DK.b28daa43.js",
    "assets/ad-viewer/de.217602b4.js", "assets/ad-viewer/es.9d1bca2b.js",
    "assets/ad-viewer/fi.e8ed832a.js", "assets/ad-viewer/fr.c27766d8.js",
    "assets/ad-viewer/is.7b423306.js", "assets/ad-viewer/it.944d3766.js",
    "assets/ad-viewer/ja.4a7c2a26.js", "assets/ad-viewer/ko.48e4bc29.js",
    "assets/ad-viewer/lt.2d96e2c4.js", "assets/ad-viewer/mraid.0.0.4.js",
    "assets/ad-viewer/nb.36dbde1f.js", "assets/ad-viewer/omid-session-client-v1.js",
    "assets/ad-viewer/omsdk-v1.js", "assets/ad-viewer/pt.87216b1c.js",
    "assets/ad-viewer/pt_BR.f97205cf.js", "assets/ad-viewer/ro.5e220f49.js",
    "assets/ad-viewer/ru.51df9ac7.js", "assets/ad-viewer/sv.c8af148a.js",
    "assets/ad-viewer/tr.909011ff.js", "assets/ad-viewer/zh_Hans.0320c043.js",
    "assets/ad-viewer/zh_Hant.e7c3056e.js", "assets/google-services-desktop.json",
    "assets/idoly-diagnostics-licenses/ShadowHook-MIT.txt", "assets/idoly-diagnostics-licenses/ShadowHook-third-party.txt",
    "assets/idoly-diagnostics-native.json", "assets/idoly-fonts/IdolyFontSupport.json",
    "assets/idoly-fonts/OFL-Pretendard.txt", "assets/idoly-local.json",
    "assets/idoly-presentation-licenses/NDK-RUNTIME-NOTICES.txt", "assets/idoly-presentation-standalone.json",
)
MAX_INDEX = 8 * 1024 * 1024
MAX_DATA = 1024 * 1024 * 1024
MAX_ENTRIES = 16000
PINS = {
    "ko": {"bytes": 165128829, "sha256": "f2b4555f2b56f5f388104a2e13a8cf0d50e3ffef3fca05d85281658d5a7366ae"},
    "ja": {"bytes": 164276861, "sha256": "3cffdcdf99b48eb5819b8639b3a31bfa43f4ae5cc1c092bb5dbd984a6c080543"},
    "en": {"bytes": 164260477, "sha256": "2bd373fbee1435c45000088fbf7996cbea8d577bf6015085e8c1101d82130baf"},
}


def need(condition, code):
    if not condition:
        raise ValueError(code)


def record(path):
    path = Path(path)
    with path.open("rb") as stream:
        return {"bytes": path.stat().st_size, "sha256": hashlib.file_digest(stream, "sha256").hexdigest()}


def json_bytes(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")


def safe_name(name):
    return (isinstance(name, str) and name.isascii() and all(32 <= ord(char) <= 126 for char in name)
            and 0 < len(name) < 1024
            and "\\" not in name and not name.startswith("/")
            and all(part not in ("", ".", "..") for part in name.split("/")))


def carrier_member(name):
    return name.startswith(PREFIX) or name in STATIC_ASSETS


def members(archive):
    result = {}
    for info in archive.infolist():
        if info.is_dir():
            continue
        need(safe_name(info.filename) and info.filename not in result, "language_zip_member_invalid")
        need(info.compress_type in (ZIP_STORED, ZIP_DEFLATED) and not info.flag_bits & 1,
             "language_zip_encoding_invalid")
        need(0 <= info.file_size <= MAX_DATA and 0 <= info.compress_size <= MAX_DATA,
             "language_zip_member_bound")
        result[info.filename] = info
    need(len(result) <= MAX_ENTRIES, "language_zip_entry_bound")
    return result


def encoded(archive, info):
    """Read the original compressed bytes, after matching the local ZIP header."""
    stream = archive.fp
    stream.seek(info.header_offset)
    raw = stream.read(30)
    need(len(raw) == 30 and raw[:4] == b"PK\x03\x04", "language_local_header_invalid")
    _, _, flags, method, _, _, crc, size, plain, name_len, extra_len = struct.unpack("<4s5H3I2H", raw)
    name = stream.read(name_len)
    need(name == info.filename.encode("ascii") and method == info.compress_type
         and flags == info.flag_bits and not flags & 1, "language_local_header_differs")
    if not flags & 8:
        need((crc, size, plain) == (info.CRC, info.compress_size, info.file_size),
             "language_local_size_differs")
    stream.seek(extra_len, 1)
    data = stream.read(info.compress_size)
    need(len(data) == info.compress_size, "language_compressed_span_truncated")
    return data


def identity(archive, info):
    data = encoded(archive, info)
    plain = data if info.compress_type == ZIP_STORED else zlib.decompress(data, -15)
    need(len(plain) == info.file_size and zlib.crc32(plain) == info.CRC,
         "language_plain_integrity_differs")
    return {"name": info.filename, "bytes": info.file_size,
            "sha256": hashlib.sha256(plain).hexdigest(), "crc32": info.CRC,
            "method": info.compress_type, "compressed_bytes": len(data),
            "compressed_sha256": hashlib.sha256(data).hexdigest()}


def zip_headers(entry, offset):
    """Canonical ZIP32, 4-byte aligned uncompressed entries, no descriptors."""
    name = entry["name"].encode("ascii")
    pad = (-(offset + 30 + len(name) + 4)) % 4 if entry["method"] == 0 else 0
    extra = struct.pack("<HH", 0xD935, pad) + bytes(pad) if entry["method"] == 0 else b""
    args = (20, 0, entry["method"], 0, 33, entry["crc32"],
            entry["compressed_bytes"], entry["bytes"], len(name), len(extra))
    local = struct.pack("<I5H3I2H", 0x04034B50, *args) + name + extra
    central = struct.pack("<I6H3I5H2I", 0x02014B50, 20, 20, 0, entry["method"], 0, 33,
                          entry["crc32"], entry["compressed_bytes"], entry["bytes"],
                          len(name), 0, 0, 0, 0, 0, offset) + name
    return local, central


def carrier(entries, read_span, write):
    offset = 0
    directory = []
    for entry in entries:
        local, central = zip_headers(entry, offset)
        data = read_span(entry)
        need(len(data) == entry["compressed_bytes"]
             and hashlib.sha256(data).hexdigest() == entry["compressed_sha256"],
             "language_source_span_differs")
        write(local)
        write(data)
        offset += len(local) + len(data)
        directory.append(central)
    start = offset
    for central in directory:
        write(central)
        offset += len(central)
    need(offset < MAX_DATA and len(entries) < 65535, "language_carrier_bound")
    write(struct.pack("<I4H2IH", 0x06054B50, 0, 0, len(entries), len(entries), offset - start, start, 0))


def build_archive(inputs, output, *, pins=PINS):
    """Pinned original clients; output contains JSON and stored spans, no APK code."""
    inputs = {key: Path(value) for key, value in inputs.items()}
    need(set(inputs) == set(LANGUAGES) and set(pins) == set(LANGUAGES), "language_inputs_incomplete")
    sources = {lang: record(path) for lang, path in inputs.items()}
    need(sources == pins, "language_input_pin_differs")
    output = Path(output)
    need(not output.exists() and all(output.resolve() != path.resolve() for path in inputs.values()),
         "language_output_exists")
    temporary = output.with_name(output.name + ".partial")
    need(not temporary.exists(), "language_partial_exists")
    try:
        with ExitStack() as stack:
            archives = {lang: stack.enter_context(ZipFile(path)) for lang, path in inputs.items()}
            tables = {lang: members(value) for lang, value in archives.items()}
            names = set(tables["ko"])
            need(all(set(value) == names for value in tables.values()), "language_member_sets_differ")
            need(set(STATIC_ASSETS) <= names, "language_static_assets_missing")
            base_rows = {name: identity(archives["ko"], tables["ko"][name]) for name in sorted(names)}
            by_content = {(row["sha256"], row["method"]): dict(row, source={"kind": "base", "member": name})
                          for name, row in base_rows.items() if carrier_member(name)}
            blobs = {}
            language_rows = {}
            for lang in LANGUAGES:
                entries = []
                for name in sorted(names):
                    row = base_rows[name] if lang == "ko" else identity(archives[lang], tables[lang][name])
                    if not name.startswith(PREFIX):
                        need(row["sha256"] == base_rows[name]["sha256"], "language_non_data_member_differs")
                    if not carrier_member(name):
                        continue
                    content_key = (row["sha256"], row["method"])
                    known = by_content.get(content_key)
                    if known is None:
                        member = OBJECTS + row["compressed_sha256"] + ".bin"
                        known = dict(row, source={"kind": "object", "member": member})
                        by_content[content_key] = known
                        blobs[member] = (lang, name, row)
                    entry = dict(known, name=name)
                    entries.append(entry)
                need(any(row["name"] == PREFIX + "Managed/Metadata/global-metadata.dat" for row in entries)
                     and any(row["name"] == PREFIX + "unity_app_guid" for row in entries),
                     "language_required_data_missing")
                digest = hashlib.sha256()
                size = 0
                def write(data):
                    nonlocal size
                    size += len(data)
                    digest.update(data)
                def read(row):
                    source = row["source"]
                    origin, member = ("ko", source["member"]) if source["kind"] == "base" else blobs[source["member"]][:2]
                    return encoded(archives[origin], tables[origin][member])
                carrier(entries, read, write)
                language_rows[lang] = {"entries": entries, "carrier": {"bytes": size, "sha256": digest.hexdigest()}}
            boot = PREFIX + "boot.config"
            need(boot in names, "language_boot_config_missing")
            need(all(identity(archives[lang], tables[lang][boot])["sha256"] == base_rows[boot]["sha256"]
                     for lang in LANGUAGES), "language_boot_config_differs")
            guid = PREFIX + "unity_app_guid"
            need(len({next(row["sha256"] for row in language_rows[lang]["entries"] if row["name"] == guid)
                      for lang in LANGUAGES}) == len(LANGUAGES), "language_extraction_guids_not_distinct")
            index = {"schema": 1, "strategy": STRATEGY, "base_language": "ko", "sources": sources,
                     "static_assets": list(STATIC_ASSETS),
                     "boot_config_sha256": base_rows[boot]["sha256"], "languages": language_rows}
            raw = json_bytes(index)
            need(len(raw) <= MAX_INDEX, "language_index_bound")
            with ZipFile(temporary, "x", compression=ZIP_STORED, allowZip64=False) as target:
                for member in [INDEX] + sorted(blobs):
                    value = raw if member == INDEX else encoded(archives[blobs[member][0]], tables[blobs[member][0]][blobs[member][1]])
                    info = ZipInfo(member, (1980, 1, 1, 0, 0, 0))
                    info.compress_type = ZIP_STORED
                    target.writestr(info, value)
        validate_data_archive(temporary, inputs["ko"])
        temporary.replace(output)
        return descriptor(index, raw)
    finally:
        temporary.unlink(missing_ok=True)


def descriptor(index, raw):
    return {"asset": INDEX.removeprefix("assets/"), "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(), "strategy": STRATEGY,
            "languages": list(LANGUAGES),
            "runtime_carriers": {lang: row["carrier"] for lang, row in index["languages"].items()}}


def validate_data_archive(path, base_apk, *, embedded=False):
    """Reject code, forged rows, missing spans and ZIP aliases before APK merger."""
    with ZipFile(path) as archive, ZipFile(base_apk) as base:
        table, base_table = members(archive), members(base)
        need(INDEX in table and table[INDEX].file_size <= MAX_INDEX, "language_index_missing")
        raw = archive.read(INDEX)
        index = json.loads(raw)
        need(json_bytes(index) == raw and index.get("schema") == 1 and index.get("strategy") == STRATEGY
             and index.get("base_language") == "ko" and set(index.get("languages", {})) == set(LANGUAGES),
             "language_index_invalid")
        need(index.get("static_assets") == list(STATIC_ASSETS), "language_static_assets_invalid")
        need(index.get("sources", {}).get("ko") == record(base_apk), "language_base_identity_differs")
        expected = {INDEX}
        source_archive = archive if embedded else base
        source_table = table if embedded else base_table
        if embedded:
            need({name for name in table if carrier_member(name)}
                 == {name for name in base_table if carrier_member(name)}, "language_embedded_base_inventory_differs")
        checked = {}
        for lang, data in index["languages"].items():
            entries = data.get("entries", [])
            need(0 < len(entries) <= MAX_ENTRIES and [row["name"] for row in entries] == sorted(set(row["name"] for row in entries)),
                 "language_entry_inventory_invalid")
            def read(row):
                name, source = row["name"], row["source"]
                need(safe_name(name) and carrier_member(name) and row["method"] in (0, 8)
                     and re.fullmatch("[0-9a-f]{64}", row["sha256"]) is not None,
                     "language_entry_invalid")
                kind, member = source["kind"], source["member"]
                need(kind in ("base", "object"), "language_source_invalid")
                if kind == "base":
                    need(member in source_table and carrier_member(member), "language_base_member_invalid")
                    original = source_table[member]
                    need((original.file_size, original.compress_size, original.compress_type, original.CRC)
                         == (row["bytes"], row["compressed_bytes"], row["method"], row["crc32"]),
                         "language_base_encoding_differs")
                    span = encoded(source_archive, original)
                else:
                    need(member == OBJECTS + row["compressed_sha256"] + ".bin"
                         and member in table and table[member].compress_type == ZIP_STORED,
                         "language_object_invalid")
                    expected.add(member)
                    span = archive.read(member)
                fingerprint = (row["compressed_sha256"], row["method"], row["sha256"], row["bytes"], row["crc32"])
                if fingerprint not in checked:
                    plain = span if row["method"] == 0 else zlib.decompress(span, -15)
                    need(len(plain) == row["bytes"] and zlib.crc32(plain) == row["crc32"]
                         and hashlib.sha256(plain).hexdigest() == row["sha256"], "language_object_integrity_differs")
                    checked[fingerprint] = True
                return span
            digest, size = hashlib.sha256(), [0]
            def write(value):
                digest.update(value)
                size[0] += len(value)
            carrier(entries, read, write)
            need(data["carrier"] == {"bytes": size[0], "sha256": digest.hexdigest()}, "language_carrier_identity_differs")
            need({row["name"] for row in entries} == {name for name in base_table if carrier_member(name)},
                 "language_data_inventory_differs")
        guid = PREFIX + "unity_app_guid"
        need(len({next(row["sha256"] for row in index["languages"][lang]["entries"] if row["name"] == guid)
                  for lang in LANGUAGES}) == len(LANGUAGES), "language_extraction_guids_not_distinct")
        admitted = {name for name in table if name == INDEX or name.startswith(OBJECTS)} if embedded else set(table)
        need(admitted == expected, "language_archive_has_unreferenced_members")
        return descriptor(index, raw)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for lang in LANGUAGES:
        parser.add_argument("--" + lang, type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build_archive({lang: getattr(args, lang) for lang in LANGUAGES}, args.output), indent=2))


if __name__ == "__main__":
    main()
