"""Offline, version-pinned Hangul font repair for original Unity client assets.

UnityPy is loaded only by the build operation. No game/server request imports
it, downloads a font, reads an OS font directory, or rewrites user resources.
Original Japanese and SourceSansPro fonts, including the original long-dash
TMP asset and atlas, stay intact. Korean uses a separate Font/TMP/material/
atlas graph, so clearing its dynamic atlas cannot erase stock punctuation.
"""
from __future__ import annotations

import bisect
import copy
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
KOREAN_FONT_PATH_ID, KOREAN_TMP_PATH_ID = 22, 23
KOREAN_ATLAS_PATH_ID, KOREAN_MATERIAL_PATH_ID = 24, 25
KOREAN_ATLAS_SIZE = 1024
KOREAN_TMP_NAME = "Pretendard JP SemiBold SDF"
POLICY = "hangul-font-v2-original-dashes"
FONT_DATA_OFFSET = 96
LEGACY_FALLBACK_OFFSET = 3591552
OLD_FONT_BYTES = 269108
OLD_FONT_SHA256 = "c9868de61ff2bab0b5a3a6d01c4b76f299459f08c6ae2f2c0383b4f9f6bedbf3"
FONT_OBJECT_INPUT_SHA256 = "8f44291449f24fb70e217bc3ea5a1fdc233aea35c4a96af2341cc9465e3ed922"
LEGACY_OBJECT_INPUT_SHA256 = "f8d3037d45d46caaa46a0f02899ca176300d928aa9cbe05957415ac8608f1a6d"
TMP_PATH_ID = 21
TMP_SOURCE_SHA256 = {
    "ios": "55a301be92b4dbc93e9dfe603e3b39c37b29f34cdcbb09fc91544ecaec0184b1",
    "android": "2fae65e7e9fb8ee7210ed1536c0ab6897d48bad476839bf4d5881662dcbfd009",
}
SOLIS_SOURCE_SHA256 = {
    "ios": "5a7ff93731061e781e1a36a96500909dd6edb8b6af893421bf272badb469d9f1",
    "android": "a8a862cbe5211c07da4107f656ba7246313ac8be4a458f590f6e95f9aaaf2ceb",
}
SOLIS_FALLBACK_OFFSET = 613848
ATLAS_SOURCE_SHA256 = "cd14c7a999509a84225972f1de577290fbbbba735fd35bd8296379a7f2e2d463"
MATERIAL_SOURCE_SHA256 = "d6a6a0cd8b7fe8ea4e67c2e4f4645129f949367537902d081cc714a910d70d22"
ASSETS = {
    "ios": {"bytes": 4572576, "sha256": "899ad32e8b6730252f84389cff657b6edb065a6716e32c52db258dca1a69ba62",
            "output_bytes": 9405944, "output_sha256": "174f23e290028dd19a9623dae9b6d2520e3f55276878d6679c0fbd822c9d8e82"},
    "android": {"bytes": 21490416, "sha256": "462bf4d9933c5dd3c74d7da6fd8ffe6059e4e4ba13f0ba7f8a6c5e846786943c",
                "output_bytes": 26323784, "output_sha256": "746db222387ad0b567bff91fcb88ce47baaf3b99cb86b27efa2381f92f73e087"},
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


def _unicode_groups(raw):
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
    return maps[0]


def unicode_glyphs(raw, codepoints):
    """Return real glyph IDs for explicit Unicode points, including punctuation."""
    groups = _unicode_groups(raw)
    starts = [row[0] for row in groups]
    result = {}
    for codepoint in codepoints:
        _need(type(codepoint) is int and 0 <= codepoint <= 0x10FFFF, "Invalid Unicode code point")
        index = bisect.bisect_right(starts, codepoint) - 1
        result[codepoint] = (groups[index][2] + codepoint - groups[index][0]
                             if index >= 0 and codepoint <= groups[index][1] else 0)
    return result


def unicode_coverage(raw):
    glyphs = unicode_glyphs(raw, (*range(0x20, 0x7F), *range(0xAC00, 0xD7A4)))
    hangul = sum(glyphs[value] != 0 for value in range(0xAC00, 0xD7A4))
    latin = sum(glyphs[value] != 0 for value in range(0x20, 0x7F))
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
    pinned object and its referenced original Font both stay unchanged.
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


def _replace_string(raw, position, expected, replacement):
    encoded, new = expected.encode("utf-8"), replacement.encode("utf-8")
    _need(struct.unpack_from("<i", raw, position)[0] == len(encoded)
          and raw[position + 4:position + 4 + len(encoded)] == encoded,
          "Pinned serialized string differs")
    end = (position + 4 + len(encoded) + 3) & ~3
    _need(not any(raw[position + 4 + len(encoded):end]), "Serialized string alignment differs")
    return raw[:position] + struct.pack("<i", len(new)) + new + b"\0" * (-len(new) % 4) + raw[end:]


def _tmp_hash(text):
    value = 0
    for char in text:
        value = ((value << 5) + value) ^ ord(char)
        value &= 0xFFFFFFFF
    return value


def _korean_tmp(raw, platform):
    """Clone the dedicated stock dash TMP into an independent empty font asset."""
    _source_tmp(raw, platform)
    _need(struct.unpack_from("<iq", raw, 64) == (0, 2)
          and struct.unpack_from("<I", raw, 252)[0] == 2
          and struct.unpack_from("<I", raw, 360)[0] == 2
          and [struct.unpack_from("<IIIf", raw, 364 + 16 * i)[1:3] for i in range(2)]
              == [(0x2E3A, 1127), (0x2E3B, 1128)]
          and struct.unpack_from("<iiq", raw, 396) == (1, 0, 8)
          and struct.unpack_from("<I", raw, 424)[0] == 2
          and struct.unpack_from("<I", raw, 460)[0] == 3
          and struct.unpack_from("<ii", raw, 608) == (128, 64)
          and struct.unpack_from("<ii", raw, 700) == (128, 64),
          "Original dedicated long-dash TMP tables or atlas references differ")
    mutable = bytearray(raw)
    struct.pack_into("<IiqI", mutable, 60, _tmp_hash(KOREAN_TMP_NAME), 0,
                     KOREAN_MATERIAL_PATH_ID, _tmp_hash(KOREAN_TMP_NAME + " Atlas Material"))
    struct.pack_into("<iq", mutable, 128, 0, KOREAN_FONT_PATH_ID)
    struct.pack_into("<iq", mutable, 400, 0, KOREAN_ATLAS_PATH_ID)
    struct.pack_into("<ii", mutable, 608, KOREAN_ATLAS_SIZE, KOREAN_ATLAS_SIZE)
    struct.pack_into("<ii", mutable, 700, KOREAN_ATLAS_SIZE, KOREAN_ATLAS_SIZE)
    # Empty character/glyph tables and one full free rectangle. Never retain
    # SourceSans glyph indices in a TMP asset backed by a different font.
    mutable[424:512] = struct.pack("<iiiiii", 0, 1, 0, 0,
                                  KOREAN_ATLAS_SIZE - 1, KOREAN_ATLAS_SIZE - 1)
    mutable[252:396] = struct.pack("<ii", 0, 0)
    result = _replace_string(bytes(mutable), 28, "SourceSansPro-Regular SDF", KOREAN_TMP_NAME)
    result = _replace_string(result, 148, "Source Sans Pro", "Pretendard JP")
    result = _replace_string(result, 168, "Regular", "SemiBold")
    # Creation GUID/character sequence are build metadata, but distinct values
    # also avoid claiming that the new object is the stock dash font asset.
    for old, new in ((b"43fa2ca56150741f682409d5e57bbc2b", FONT_SHA256[:32].encode()),
                     (b"ad7a71ee6bd7e467d9bd41506fada03a", FONT_SHA256[32:].encode())):
        _need(result.count(old) in (1, 2), "Original TMP creation GUID differs")
        result = result.replace(old, new)
    old_sequence = struct.pack("<i", 9) + b"2E3A-2E3B" + b"\0" * 3
    new_sequence = b"0020-007E,AC00-D7A3"
    _need(result.count(old_sequence) == 1, "Original long-dash creation sequence differs")
    return result.replace(old_sequence, struct.pack("<i", len(new_sequence)) + new_sequence
                          + b"\0" * (-len(new_sequence) % 4))


def _fallback_array(raw, offset, old_ids, new_ids):
    expected = struct.pack("<i", len(old_ids)) + b"".join(struct.pack("<iq", 0, pid) for pid in old_ids)
    _need(raw[offset:offset + len(expected)] == expected, "Original fallback array differs")
    replacement = struct.pack("<i", len(new_ids)) + b"".join(struct.pack("<iq", 0, pid) for pid in new_ids)
    return raw[:offset] + replacement + raw[offset + len(expected):]


def _clone_object(source, template, path_id, raw):
    _need(path_id not in source.objects, "Added font object path ID already exists")
    cloned = copy.copy(template)
    cloned.path_id = path_id
    cloned.byte_size = len(raw)
    cloned.set_raw_data(raw)
    source.objects[path_id] = cloned


def _korean_atlas(raw):
    """Create one private readable Alpha8 atlas with consistent pixel bounds."""
    _need(len(raw) == 8340 and _sha(raw) == ATLAS_SOURCE_SHA256
          and struct.unpack_from("<iii", raw, 44) == (128, 64, 8192)
          and struct.unpack_from("<I", raw, 60)[0] == 1
          and struct.unpack_from("<I", raw, 128)[0] == 8192
          and not any(raw[8324:]), "Original atlas pixel layout differs")
    prefix = bytearray(raw[:132])
    pixels = KOREAN_ATLAS_SIZE * KOREAN_ATLAS_SIZE  # Alpha8: one byte per pixel.
    struct.pack_into("<iii", prefix, 44, KOREAN_ATLAS_SIZE, KOREAN_ATLAS_SIZE, pixels)
    struct.pack_into("<I", prefix, 128, pixels)
    return _replace_string(bytes(prefix) + b"\0" * pixels + raw[8324:], 0,
                           "SourceSansPro-Regular SDF Atlas", FONT_NAME + " SDF Atlas")


def _korean_material(raw):
    """Bind the private atlas and keep shader texel metrics in the same units."""
    _need(len(raw) == 1764 and _sha(raw) == MATERIAL_SOURCE_SHA256
          and struct.unpack_from("<iq", raw, 216) == (0, 8)
          and raw[204:216] == struct.pack("<i", 8) + b"_MainTex"
          and raw[1160:1180] == struct.pack("<i", 14) + b"_TextureHeight\0\0"
          and raw[1184:1204] == struct.pack("<i", 13) + b"_TextureWidth\0\0\0"
          and struct.unpack_from("<f", raw, 1180)[0] == 64.
          and struct.unpack_from("<f", raw, 1204)[0] == 128.,
          "Original material atlas reference or shader metrics differ")
    material = bytearray(raw)
    struct.pack_into("<iq", material, 216, 0, KOREAN_ATLAS_PATH_ID)
    struct.pack_into("<f", material, 1180, float(KOREAN_ATLAS_SIZE))
    struct.pack_into("<f", material, 1204, float(KOREAN_ATLAS_SIZE))
    return _replace_string(bytes(material), 0, "SourceSansPro-Regular Atlas Material",
                           KOREAN_TMP_NAME + " Atlas Material")


def patch_bytes(asset_bytes, font, platform):
    """Add a private Korean graph while preserving every stock punctuation glyph."""
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
    _need(set(old_objects) == {str(i) for i in range(1, 22)}, "Original shared asset object roster differs")
    objects = {obj.path_id: obj for obj in env.objects}
    raw = {pid: bytes(objects[pid].get_raw_data()) for pid in (2, 8, 17, 18, 20, 21)}
    tmp_report = _source_tmp(raw[21], platform)
    _need(_sha(raw[17]) == FONT_OBJECT_INPUT_SHA256 and _sha(raw[18]) == LEGACY_OBJECT_INPUT_SHA256
          and _sha(raw[20]) == SOLIS_SOURCE_SHA256[platform]
          and _sha(raw[8]) == ATLAS_SOURCE_SHA256 and _sha(raw[2]) == MATERIAL_SOURCE_SHA256,
          "Original Font, Solis TMP, atlas or material payload differs")
    old_font = raw[17][FONT_DATA_OFFSET:FONT_DATA_OFFSET + OLD_FONT_BYTES]
    _need(struct.unpack_from("<I", raw[17], FONT_DATA_OFFSET - 4)[0] == OLD_FONT_BYTES
          and _sha(old_font) == OLD_FONT_SHA256, "Original Font data identity or offset differs")
    long_dashes = unicode_glyphs(old_font, (0x2E3A, 0x2E3B))
    _need(all(long_dashes.values()), "Original font lacks its required long-dash glyphs")
    end = (FONT_DATA_OFFSET + OLD_FONT_BYTES + 3) & ~3
    korean_font = (raw[17][:FONT_DATA_OFFSET - 4] + struct.pack("<I", len(font)) + font
                   + b"\0" * (-len(font) % 4) + raw[17][end:])
    korean_font = _replace_string(korean_font, 0, "SourceSansPro-Regular", FONT_NAME)
    korean_tmp = _korean_tmp(raw[21], platform)
    korean_atlas = _korean_atlas(raw[8])
    korean_material = _korean_material(raw[2])
    objects[18].set_raw_data(_fallback_array(raw[18], LEGACY_FALLBACK_OFFSET, (), (KOREAN_FONT_PATH_ID,)))
    objects[20].set_raw_data(_fallback_array(raw[20], SOLIS_FALLBACK_OFFSET, (19, 21), (19, 21, KOREAN_TMP_PATH_ID)))
    additions = ((KOREAN_FONT_PATH_ID, 17, korean_font), (KOREAN_TMP_PATH_ID, 21, korean_tmp),
                 (KOREAN_ATLAS_PATH_ID, 8, korean_atlas), (KOREAN_MATERIAL_PATH_ID, 2, korean_material))
    for path_id, template_id, value in additions:
        _clone_object(source, objects[template_id], path_id, value)
    saved = source.save()
    _need(len(saved) == profile["output_bytes"] and _sha(saved) == profile["output_sha256"],
          "Serialized Font asset output differs from the audited writer")
    checked = UnityPy.load(saved)
    _need(len(checked.files) == 1 and _metadata(next(iter(checked.files.values()))) == old_meta,
          "Shared asset metadata or external references changed")
    new_objects = _objects(checked)
    _need(set(new_objects) == {str(i) for i in range(1, 26)}
          and all(new_objects[key] == value for key, value in old_objects.items() if key not in ("18", "20")),
          "An unrelated shared asset object changed")
    checked_objects = {obj.path_id: obj for obj in checked.objects}
    _need(all(bytes(checked_objects[pid].get_raw_data()) == value for pid, _, value in additions),
          "An added font graph object did not survive serialization")
    new_font_raw = bytes(checked_objects[KOREAN_FONT_PATH_ID].get_raw_data())
    legacy_raw = bytes(checked_objects[LEGACY_PATH_ID].get_raw_data())
    _need(new_font_raw[FONT_DATA_OFFSET:FONT_DATA_OFFSET + len(font)] == font
          and legacy_raw == _fallback_array(raw[18], LEGACY_FALLBACK_OFFSET, (), (KOREAN_FONT_PATH_ID,)),
          "Korean Font payload or acyclic legacy fallback did not survive serialization")
    return saved, {"schema": 2, "policy": POLICY, "platform": platform,
        "input_asset_sha256": profile["sha256"], "input_asset_bytes": profile["bytes"],
        "output_asset_sha256": profile["output_sha256"], "output_asset_bytes": len(saved), "font": font_report,
        "Font_path_id": KOREAN_FONT_PATH_ID, "legacy_Font_path_id": LEGACY_PATH_ID,
        "TMP_FontAsset": {"path_id": KOREAN_TMP_PATH_ID, "name": KOREAN_TMP_NAME,
            "source_Font_reference": {"file_id": 0, "path_id": KOREAN_FONT_PATH_ID},
            "atlas_population_mode": 1, "atlas_population_mode_name": "Dynamic",
            "initial_glyph_and_character_tables_empty": True, "fallback_FontAsset_references": [],
            "atlas_width": KOREAN_ATLAS_SIZE, "atlas_height": KOREAN_ATLAS_SIZE,
            "creation_atlas_width": KOREAN_ATLAS_SIZE, "creation_atlas_height": KOREAN_ATLAS_SIZE,
            "atlas_path_id": KOREAN_ATLAS_PATH_ID, "material_path_id": KOREAN_MATERIAL_PATH_ID},
        "original_TMP_FontAsset": tmp_report,
        "original_long_dash_font_retained": True, "original_TMP_long_dash_asset_retained": True,
        "original_long_dash_glyphs": {f"U+{cp:04X}": glyph for cp, glyph in long_dashes.items()},
        "independent_atlas_and_material": True,
        "atlas_format": "Alpha8", "atlas_pixel_bytes": KOREAN_ATLAS_SIZE ** 2,
        "material_texture_width": KOREAN_ATLAS_SIZE, "material_texture_height": KOREAN_ATLAS_SIZE,
        "Solis_fallback_references": [{"file_id": 0, "path_id": pid} for pid in (19, 21, KOREAN_TMP_PATH_ID)],
        "legacy_fallback_references": [{"file_id": 0, "path_id": KOREAN_FONT_PATH_ID}],
        "legacy_Japanese_font_data_unchanged": True, "acyclic_fallback_graph": True,
        "object_count": 25, "original_object_count": 21, "other_object_count": 19,
        "all_other_objects_byte_identical": True, "original_atlas_and_material_byte_identical": True,
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
    _need(len(parts) == 26, "Patched Android font split count differs")
    report["input_members"] = names
    report["output_members"] = {name: {"bytes": len(value), "sha256": _sha(value)} for name, value in parts.items()}
    report["split_bytes"] = SPLIT_BYTES
    return parts, report


def package_notices(report, license_bytes):
    _need(isinstance(report, dict) and report.get("policy") == POLICY
          and len(license_bytes) == LICENSE_BYTES and _sha(license_bytes) == LICENSE_SHA256,
          "Font package notices do not match the audited inputs")
    marker = {key: value for key, value in report.items()
              if not key.startswith("object_sha256_") and key != "notice_members"}
    marker["license"] = {"name": LICENSE_NAME, "bytes": LICENSE_BYTES, "sha256": LICENSE_SHA256,
                         "license": "OFL-1.1", "reserved_font_names_retained": True}
    return {MARKER_NAME: (json.dumps(marker, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(),
            LICENSE_NAME: license_bytes}
