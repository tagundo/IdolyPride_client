"""Offline, version-pinned Hangul font repair for original Unity client assets.

UnityPy is loaded only by the build operation. No game/server request imports
it, downloads a font, reads an OS font directory, or rewrites user resources.
The original Japanese font bytes stay intact; its serialized fallback gains
one reference to the separately replaced SourceSansPro Font object.
"""
from __future__ import annotations

import bisect
import hashlib
import importlib.metadata
import json
from pathlib import Path
import stat
import struct

FONT_SHA256 = "7cd2b757bd8b8db79b4b87c3b402aa62aca666b55ff50ae0799e14ece1942314"
FONT_BYTES = 3781740
LICENSE_SHA256 = "82e9c8a4b203261f10ddba1296422d64914ff3d4b7bd8a12896d03f0f088d70a"
LICENSE_BYTES = 4816
FONT_NAME = "Pretendard JP SemiBold"
MAX_FONT_BYTES = 8 * 1024 * 1024
MAX_ASSET_BYTES = 64 * 1024 * 1024
SPLIT_BYTES = 1024 * 1024
ANDROID_ASSET = "assets/bin/Data/sharedassets0.assets"
IOS_ASSET = "Data/sharedassets0.assets"
MARKER_NAME = "IdolyFontSupport.json"
LICENSE_NAME = "OFL-Pretendard.txt"
FONT_PATH_ID, LEGACY_PATH_ID = 17, 18
FONT_DATA_OFFSET = 96
LEGACY_FALLBACK_OFFSET = 3591552
OLD_FONT_BYTES = 269108
OLD_FONT_SHA256 = "c9868de61ff2bab0b5a3a6d01c4b76f299459f08c6ae2f2c0383b4f9f6bedbf3"
FONT_OBJECT_INPUT_SHA256 = "8f44291449f24fb70e217bc3ea5a1fdc233aea35c4a96af2341cc9465e3ed922"
FONT_OBJECT_OUTPUT_SHA256 = "555870cf2536cec42ce247b637c3f1456304ccdb4dd67f559ff8973740156910"
LEGACY_OBJECT_INPUT_SHA256 = "f8d3037d45d46caaa46a0f02899ca176300d928aa9cbe05957415ac8608f1a6d"
LEGACY_OBJECT_OUTPUT_SHA256 = "9079bbf411bb8f079160e4e23e4b4761e860401cc96457aa7b86f7d954d9a737"
TMP_PATH_ID = 21
TMP_SOURCE_SHA256 = {
    "ios": "55a301be92b4dbc93e9dfe603e3b39c37b29f34cdcbb09fc91544ecaec0184b1",
    "android": "2fae65e7e9fb8ee7210ed1536c0ab6897d48bad476839bf4d5881662dcbfd009",
}
ASSETS = {
    "ios": {"bytes": 4572576, "sha256": "899ad32e8b6730252f84389cff657b6edb065a6716e32c52db258dca1a69ba62",
            "output_bytes": 8085216, "output_sha256": "104890b56122dbd3362b7b8801f9d6c3e6d0535e9c691d8dc4a660bc8bf35c69"},
    "android": {"bytes": 21490416, "sha256": "462bf4d9933c5dd3c74d7da6fd8ffe6059e4e4ba13f0ba7f8a6c5e846786943c",
                "output_bytes": 25003056, "output_sha256": "d8f4f9902eed6baa90160717367330243a6a7f83fd462dc93e1b3d1e226eba80"},
}


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _need(ok, message):
    if not ok:
        raise ValueError(message)


def _read_regular(path, maximum):
    path = Path(path)
    _need(not path.is_symlink() and stat.S_ISREG(path.stat().st_mode), "Expected a regular explicit font input")
    with path.open("rb") as stream:
        raw = stream.read(maximum + 1)
    _need(0 < len(raw) <= maximum, "Font input exceeds its bound")
    return raw


def unicode_coverage(raw):
    """Read bounded Unicode format-12 cmap groups without loading font outlines.

    The pinned OpenType font has identical Unicode and Windows format-12 maps.
    Glyph zero is missing and is never counted as support for a code point.
    """
    _need(isinstance(raw, bytes) and 12 <= len(raw) <= MAX_FONT_BYTES
          and raw[:4] in (b"OTTO", b"\0\1\0\0"), "Expected a bounded OpenType font")
    count = struct.unpack_from(">H", raw, 4)[0]
    _need(0 < count <= 128 and 12 + count * 16 <= len(raw), "Invalid OpenType table directory")
    tables = {}
    for index in range(count):
        tag, _checksum, offset, size = struct.unpack_from(">4sIII", raw, 12 + index * 16)
        _need(tag not in tables and offset >= 12 + count * 16 and 0 < size <= len(raw) - offset,
              "Invalid or duplicate OpenType table")
        tables[tag] = offset, size
    _need(b"cmap" in tables and b"maxp" in tables, "Font has no Unicode map or glyph count")
    maxp, maxp_size = tables[b"maxp"]
    _need(maxp_size >= 6, "Invalid glyph count table")
    glyphs = struct.unpack_from(">H", raw, maxp + 4)[0]
    base, size = tables[b"cmap"]
    _need(size >= 4, "Invalid Unicode cmap")
    version, records = struct.unpack_from(">HH", raw, base)
    _need(version == 0 and 0 < records <= 64 and 4 + records * 8 <= size, "Invalid Unicode cmap records")
    candidates = set()
    for index in range(records):
        platform, encoding, relative = struct.unpack_from(">HHI", raw, base + 4 + index * 8)
        _need(relative <= size - 2, "Unicode cmap offset is outside its table")
        if platform == 0 and encoding in (4, 6) or platform == 3 and encoding == 10:
            if struct.unpack_from(">H", raw, base + relative)[0] == 12:
                candidates.add(relative)
    _need(bool(candidates), "The font has no supported full Unicode cmap")
    maps = []
    for relative in sorted(candidates):
        offset = base + relative
        _need(relative + 16 <= size, "Truncated full Unicode cmap")
        fmt, reserved, length, _language, number = struct.unpack_from(">HHIII", raw, offset)
        _need(fmt == 12 and reserved == 0 and 16 <= length <= size - relative
              and number <= 100000 and 16 + number * 12 == length, "Malformed Unicode cmap group list")
        groups, previous = [], -1
        for index in range(number):
            first, last, start_glyph = struct.unpack_from(">III", raw, offset + 16 + index * 12)
            _need(previous < first <= last <= 0x10FFFF and start_glyph < glyphs
                  and start_glyph + last - first < glyphs, "Invalid Unicode glyph range")
            groups.append((first, last, start_glyph))
            previous = last
        maps.append(groups)
    _need(all(groups == maps[0] for groups in maps), "Unicode platform maps disagree")
    groups = maps[0]
    starts = [row[0] for row in groups]
    def present(codepoint):
        index = bisect.bisect_right(starts, codepoint) - 1
        return index >= 0 and codepoint <= groups[index][1] and groups[index][2] + codepoint - groups[index][0] != 0
    hangul = sum(present(value) for value in range(0xAC00, 0xD7A4))
    latin = sum(present(value) for value in range(0x20, 0x7F))
    return {"modern_hangul_syllables": hangul, "required_modern_hangul_syllables": 11172,
            "basic_latin_characters": latin, "required_basic_latin_characters": 95,
            "unicode_format": 12, "unicode_maps_agree": True}


def validate_font(raw):
    _need(isinstance(raw, bytes) and len(raw) == FONT_BYTES and _sha(raw) == FONT_SHA256,
          "Font bytes differ from the audited Pretendard JP input")
    coverage = unicode_coverage(raw)
    _need(coverage["modern_hangul_syllables"] == 11172 and coverage["basic_latin_characters"] == 95,
          "Font does not cover the required Korean and basic Latin characters")
    return {"family": FONT_NAME, "bytes": len(raw), "sha256": _sha(raw), **coverage,
            "font_bytes_modified": False, "license": "OFL-1.1"}


def read_font(path):
    raw = _read_regular(path, MAX_FONT_BYTES)
    return raw, validate_font(raw)


def read_license(path):
    raw = _read_regular(path, 16 * 1024)
    _need(len(raw) == LICENSE_BYTES and _sha(raw) == LICENSE_SHA256,
          "Font license differs from the audited upstream OFL text")
    return raw


def _metadata(asset):
    return {"unity_version": str(asset.unity_version), "target_platform": int(asset.target_platform),
            "type_tree": bool(asset._enable_type_tree),
            "externals": [(x.path, x.guid.hex() if x.guid else None, x.type, x.temp_empty) for x in asset.externals],
            "types": [(x.class_id, x.is_stripped_type, x.script_type_index,
                       x.script_id.hex() if x.script_id else None, x.old_type_hash.hex() if x.old_type_hash else None)
                      for x in asset.types]}


def _objects(environment):
    result = {}
    for obj in environment.objects:
        key = str(obj.path_id)
        _need(key not in result and obj.byte_size <= MAX_ASSET_BYTES, "Duplicate or oversized serialized object")
        raw = bytes(obj.get_raw_data())
        result[key] = {"class_id": int(obj.type), "bytes": len(raw), "sha256": _sha(raw)}
    return result


def _source_tmp(raw, platform):
    """Check the original TMP asset's source Font and existing Dynamic mode.

    Both metadata registrations verify the declared TMP_FontAsset field order.
    Its serialized base MonoBehaviour/name, TMP_Asset hash/material/hash and
    version/GUID strings precede the PPtr and AtlasPopulationMode enum. The
    pinned object stays unchanged; only its referenced Font receives new data.
    """
    _need(len(raw) == 1056 and _sha(raw) == TMP_SOURCE_SHA256[platform],
          "Original SourceSansPro TMP asset differs")
    def string_at(position):
        _need(position + 4 <= len(raw), "Truncated TMP string")
        length = struct.unpack_from("<i", raw, position)[0]
        _need(0 <= length <= len(raw) - position - 4, "Invalid TMP string bound")
        return raw[position + 4:position + 4 + length].decode("utf-8"), (position + 4 + length + 3) & ~3
    name, position = string_at(28)
    _need(name == "SourceSansPro-Regular SDF", "Original SourceSansPro TMP name differs")
    position += 4 + 12 + 4  # TMP_Asset hashCode, material PPtr, materialHashCode.
    version, position = string_at(position)
    guid, position = string_at(position)
    _need(version == "1.1.0" and len(guid) == 32 and all(ch in "0123456789abcdef" for ch in guid),
          "Original TMP serialized version or source GUID differs")
    source = struct.unpack_from("<iq", raw, position)
    mode = struct.unpack_from("<i", raw, position + 12)[0]
    _need(source == (0, FONT_PATH_ID) and mode == 1,
          "SourceSansPro TMP must already reference Font17 in Dynamic mode")
    return {"path_id": TMP_PATH_ID, "bytes": len(raw), "sha256": _sha(raw),
            "source_Font_reference": {"file_id": source[0], "path_id": source[1]},
            "atlas_population_mode": mode, "atlas_population_mode_name": "Dynamic",
            "source_reference_offset": position, "population_mode_offset": position + 12,
            "all_serialized_bytes_unchanged": True}


def patch_bytes(asset_bytes, font, platform):
    """Patch exactly two original Font objects and independently read them back."""
    _need(isinstance(platform, str) and platform in ASSETS and isinstance(asset_bytes, bytes),
          "Unknown font asset platform")
    profile = ASSETS[platform]
    _need(len(asset_bytes) == profile["bytes"] and _sha(asset_bytes) == profile["sha256"],
          "Original sharedassets0 Font asset differs from the audited game")
    font_report = validate_font(font)
    _need(importlib.metadata.version("UnityPy") == "1.25.4", "Use the audited UnityPy 1.25.4 asset writer")
    import UnityPy
    env = UnityPy.load(asset_bytes)
    _need(len(env.files) == 1, "Expected one serialized shared asset file")
    source = next(iter(env.files.values()))
    old_meta, old_objects = _metadata(source), _objects(env)
    _need(len(old_objects) == 21, "Original shared asset object count differs")
    objects = {obj.path_id: obj for obj in env.objects}
    tmp = objects.get(TMP_PATH_ID)
    _need(tmp is not None and int(tmp.type) == 114, "Expected the original SourceSansPro TMP asset")
    tmp_report = _source_tmp(bytes(tmp.get_raw_data()), platform)
    target, legacy = objects.get(FONT_PATH_ID), objects.get(LEGACY_PATH_ID)
    _need(target is not None and legacy is not None and target.type.name == legacy.type.name == "Font",
          "Expected the original Font object IDs")
    target_data, legacy_data = target.read(), legacy.read()
    _need(target_data.m_Name == "SourceSansPro-Regular" and legacy_data.m_Name == "FOT-UDKakugo_LargePro-DB"
          and not target_data.m_FallbackFonts and not legacy_data.m_FallbackFonts,
          "Original Font names or fallback graph differ")
    raw = bytes(target.get_raw_data())
    legacy_raw = bytes(legacy.get_raw_data())
    old_font = bytes(target_data.m_FontData)
    _need(_sha(raw) == FONT_OBJECT_INPUT_SHA256 and _sha(legacy_raw) == LEGACY_OBJECT_INPUT_SHA256
          and len(old_font) == OLD_FONT_BYTES and _sha(old_font) == OLD_FONT_SHA256,
          "Original Font payload identity differs")
    offset = FONT_DATA_OFFSET
    _need(struct.unpack_from("<I", raw, offset - 4)[0] == len(old_font)
          and raw[offset:offset + len(old_font)] == old_font,
          "Original Font data field offset differs")
    end = (offset + len(old_font) + 3) & ~3
    _need(not any(raw[offset + len(old_font):end]), "Font data alignment differs")
    replacement = raw[:offset - 4] + struct.pack("<I", len(font)) + font + b"\0" * (-len(font) % 4) + raw[end:]
    fallback = LEGACY_FALLBACK_OFFSET
    _need(struct.unpack_from("<i", legacy_raw, fallback)[0] == 0, "Legacy Font fallback array differs")
    legacy_replacement = legacy_raw[:fallback] + struct.pack("<iiq", 1, 0, FONT_PATH_ID) + legacy_raw[fallback + 4:]
    _need(_sha(replacement) == FONT_OBJECT_OUTPUT_SHA256 and _sha(legacy_replacement) == LEGACY_OBJECT_OUTPUT_SHA256,
          "Font object patch output differs")
    target.set_raw_data(replacement)
    legacy.set_raw_data(legacy_replacement)
    saved = source.save()
    _need(len(saved) == profile["output_bytes"] and _sha(saved) == profile["output_sha256"],
          "Serialized Font asset output differs from the audited writer")
    checked = UnityPy.load(saved)
    _need(len(checked.files) == 1 and _metadata(next(iter(checked.files.values()))) == old_meta,
          "Shared asset metadata or external references changed")
    new_objects = _objects(checked)
    _need(new_objects.keys() == old_objects.keys() and all(new_objects[key] == value for key, value in old_objects.items()
          if key not in (str(FONT_PATH_ID), str(LEGACY_PATH_ID))), "An unrelated shared asset object changed")
    checked_objects = {obj.path_id: obj for obj in checked.objects}
    new_target, new_legacy = checked_objects[FONT_PATH_ID].read(), checked_objects[LEGACY_PATH_ID].read()
    _need(bytes(new_target.m_FontData) == font and not new_target.m_FallbackFonts
          and bytes(new_legacy.m_FontData) == bytes(legacy_data.m_FontData)
          and [(x.m_FileID, x.m_PathID) for x in new_legacy.m_FallbackFonts] == [(0, FONT_PATH_ID)],
          "Font payload or acyclic legacy fallback did not survive serialization")
    return saved, {"schema": 1, "policy": "hangul-font-v1", "platform": platform,
        "input_asset_sha256": profile["sha256"], "input_asset_bytes": profile["bytes"],
        "output_asset_sha256": profile["output_sha256"], "output_asset_bytes": len(saved), "font": font_report,
        "Font_path_id": FONT_PATH_ID, "legacy_Font_path_id": LEGACY_PATH_ID,
        "TMP_FontAsset": tmp_report,
        "legacy_fallback_references": [{"file_id": 0, "path_id": FONT_PATH_ID}],
        "legacy_Japanese_font_data_unchanged": True, "acyclic_fallback_graph": True,
        "other_object_count": 19, "all_other_objects_byte_identical": True,
        "type_and_external_reference_metadata_unchanged": True,
        "object_sha256_before": old_objects, "object_sha256_after": new_objects,
        "UnityPy": "1.25.4", "physical_device_verified": False}


def android_members(archive, font):
    names = [ANDROID_ASSET + ".split" + str(i) for i in range(21)]
    present = [name for name in archive.namelist() if name == ANDROID_ASSET or name.startswith(ANDROID_ASSET + ".split")]
    _need(set(present) == set(names) and len(present) == len(names), "Android shared asset split roster differs")
    infos = [archive.getinfo(name) for name in names]
    _need(all(row.file_size == SPLIT_BYTES for row in infos[:-1]) and infos[-1].file_size == 518896,
          "Android shared asset part sizes differ")
    raw = b"".join(archive.read(row) for row in infos)
    patched, report = patch_bytes(raw, font, "android")
    parts = {ANDROID_ASSET + ".split" + str(i // SPLIT_BYTES): patched[i:i + SPLIT_BYTES]
             for i in range(0, len(patched), SPLIT_BYTES)}
    _need(len(parts) == 24, "Patched Android font split count differs")
    report["input_members"] = names
    report["output_members"] = {name: {"bytes": len(value), "sha256": _sha(value)} for name, value in parts.items()}
    report["split_bytes"] = SPLIT_BYTES
    return parts, report


def package_notices(report, license_bytes):
    _need(isinstance(report, dict) and report.get("policy") == "hangul-font-v1"
          and len(license_bytes) == LICENSE_BYTES and _sha(license_bytes) == LICENSE_SHA256,
          "Font package notices do not match the audited inputs")
    marker = {key: value for key, value in report.items()
              if not key.startswith("object_sha256_") and key != "notice_members"}
    marker["license"] = {"name": LICENSE_NAME, "bytes": LICENSE_BYTES, "sha256": LICENSE_SHA256,
                         "license": "OFL-1.1", "reserved_font_names_retained": True}
    return {MARKER_NAME: (json.dumps(marker, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(),
            LICENSE_NAME: license_bytes}
