"""Offline, streaming UI TextAsset replacement for the two pinned 6.1.1 clients.

Only build tools call this module. It uses no Unity runtime hook, UnityPy,
network access, font rewrite, or game/server request-time translation.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
import stat
import struct

MAX_CSV_BYTES = 8 * 1024 * 1024
MAX_PROOF_BYTES = 64 * 1024
MAX_METADATA_BYTES = 12 * 1024 * 1024
COPY_BYTES = 64 * 1024
ORIGINAL_CSV_SHA256 = "16cf848f7f677f85262b7ff10d787fc8444c2358a5d81d46dc67d0ff573be8c3"
ORIGINAL_SCRIPT_SHA256 = "069541fc013bec1676fc777fbbd6df3ae4b88f7a8ac5b5ceef0b2471b85b6fad"
ORIGINAL_SCRIPT_BYTES = 244416
ORIGINAL_KEYS_SHA256 = "4e9221a7958a7f5c768585900a43db2f610ff1323b1a57727001e4f85c4f3a37"
ANDROID_MEMBER = "assets/bin/Data/dc5a3280fad6542929a0daf3a3736d29"
# These are original serialized-file/object pins, not caller-controlled offsets.
ASSETS = {
    "android": {
        "source_bytes": 244584,
        "source_sha256": "6c522891fb2ed310c9a6669871c76550e4d144e9aa538b5074b064ef7ecb020e",
        "metadata_sha256": "7325b68f2144df21f547dcdf86051e7406a469ad9ed5ce97d5015b2ab159a52a",
        "metadata_bytes": 85, "data_offset": 144, "table_offset": 96,
        "object_count": 1, "object_count_offset": 92, "type_count": 1, "target_index": 0, "target_path_id": 1,
        "target_relative_offset": 0, "target_bytes": 244440, "target_type_id": 0,
        "target_name": "af07872d088f944f",
        "target_object_sha256": "367c482a83d052fdc80ca8197ca1654e082cb955370f9651d9774e81907493cb",
    },
    "ios": {
        "source_bytes": 65784784,
        "source_sha256": "decc41f679e31e4ff9708bea2f66b9bcbd53ff560aeeaa4c38092550c356a38b",
        "metadata_sha256": "4ba38495615f9bfd9a3534dc08235bf4a61f4693c1dd77147a4667062ef96d6e",
        "metadata_bytes": 10240478, "data_offset": 10240528, "table_offset": 145068,
        "object_count": 418821, "object_count_offset": 145062, "type_count": 3735, "target_index": 376, "target_path_id": 377,
        "target_relative_offset": 1491320, "target_bytes": 244440, "target_type_id": 4,
        "target_name": "dff207ce641814b0",
        "target_object_sha256": "505c80895e4e5504c06fd37d73b0aff3772a2bc7d3034174a88ed8113ffb7d37",
    },
}


def _need(ok, message):
    if not ok:
        raise ValueError(message)


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _regular(path, maximum):
    path = Path(path)
    _need(not path.is_symlink() and stat.S_ISREG(path.stat().st_mode), "Expected an explicit regular UI input")
    with path.open("rb") as stream:
        value = stream.read(maximum + 1)
    _need(0 < len(value) <= maximum, "UI input exceeds its bound")
    return value


def read_ui_csv(path):
    value = _regular(path, MAX_CSV_BYTES)
    validate_csv(value)
    return value


def validate_csv(value):
    """Check the stock parser's accepted header and unsafe literal newlines.

    The original reader accepts plaintext only when its bytes start KEY,.
    CsvParser supports quoted commas/doubled quotes but its ParseLine does not
    safely retain literal newlines inside quoted values. The offline compiler
    writes those as backslash+n, which I18nHelper converts after parsing.
    """
    _need(isinstance(value, bytes) and 0 < len(value) <= MAX_CSV_BYTES
          and value.startswith(b"KEY,") and b"\0" not in value,
          "Expected bounded, BOM-free plaintext UI CSV beginning KEY,")
    try:
        text = value.decode("utf-8")
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        _need(next(reader, None) == ["KEY", "Japanese"], "Preserve the original Japanese UI column name")
        keys = set()
        for row in reader:
            _need(all("\n" not in field and "\r" not in field for field in row),
                  "UI CSV fields must encode line breaks as backslash+n")
            if not row or not row[0].strip() or row[0].lstrip().startswith("//"):
                continue
            _need(len(row) >= 2 and row[0] not in keys, "Missing value column or duplicate UI key")
            keys.add(row[0])
    except (UnicodeError, csv.Error) as exc:
        raise ValueError("Malformed UTF-8 UI CSV") from exc
    _need(len(keys) == 4199, "The original UI key roster must contain 4199 keys")
    keys_sha256 = _sha(b"\0".join(key.encode("utf-8") for key in sorted(keys)))
    _need(keys_sha256 == ORIGINAL_KEYS_SHA256, "The original UI key identities changed")
    return {"bytes": len(value), "sha256": _sha(value), "ui_keys": len(keys), "key_roster_sha256": keys_sha256,
            "plaintext_stock_reader_supported": True, "literal_field_newlines": False}


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        _need(key not in result, "Duplicate UI proof field")
        result[key] = value
    return result


def validate_proof(proof, value, language):
    _need(language in ("ja", "ko", "en"), "Unknown fixed UI language")
    csv_report = validate_csv(value)
    if language == "ja":
        _need(csv_report["sha256"] == ORIGINAL_CSV_SHA256, "Japanese UI must preserve the original CSV")
        if proof is None:
            return {"language": "ja", "input_sha256": ORIGINAL_CSV_SHA256,
                    "output_sha256": ORIGINAL_CSV_SHA256, "bytes": len(value),
                    "source_ui_keys": 4199, "changed_keys_count": 0}
    _need(isinstance(proof, dict), "A translated UI CSV requires its explicit build proof")
    _need(proof.get("language") == language and proof.get("input_sha256") == ORIGINAL_CSV_SHA256
          and proof.get("output_sha256") == csv_report["sha256"]
          and type(proof.get("bytes")) is int and proof["bytes"] == len(value)
          and type(proof.get("source_ui_keys")) is int and proof["source_ui_keys"] == 4199,
          "UI translation proof does not bind this language and original/output CSV")
    for name in ("matching_keys", "changed_keys_count", "missing_keys"):
        if name in proof:
            _need(type(proof[name]) is int and 0 <= proof[name] <= 4199, "Invalid UI translation coverage")
    return dict(proof)


def read_ui_proof(path, value, language):
    raw = _regular(path, MAX_PROOF_BYTES)
    try:
        proof = json.loads(raw, object_pairs_hook=_pairs)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Malformed UI build proof") from exc
    return validate_proof(proof, value, language)


def load_package_inputs(language="ja", csv_file=None, proof_file=None):
    """Explicit locale pairing shared by APK and IPA build CLIs.

    Legacy Japanese builds may omit UI inputs. Translated variants must never
    silently fall back to an untranslated client when an input was omitted.
    """
    _need(language in ("ja", "ko", "en"), "Unknown fixed UI language")
    if csv_file is None:
        _need(language == "ja" and proof_file is None, "A fixed translated UI language requires CSV and proof inputs")
        return None, None
    value = read_ui_csv(csv_file)
    proof = read_ui_proof(proof_file, value, language) if proof_file is not None else validate_proof(None, value, language)
    return value, proof


def _exact(stream, size):
    output = bytearray()
    while len(output) < size:
        block = stream.read(min(COPY_BYTES, size - len(output)))
        _need(isinstance(block, bytes) and bool(block), "Truncated original UI asset")
        output.extend(block)
    return bytes(output)


def _write(stream, value, digest):
    written = stream.write(value)
    _need(written == len(value), "Incomplete UI asset write")
    digest.update(value)


def _metadata(source, profile):
    header = _exact(source, 48)
    _need(struct.unpack_from(">4I", header) == (0, 0, 22, 0) and header[16:20] == b"\0" * 4,
          "Expected the original little-endian v22 serialized file")
    metadata_size, file_size, data_offset, unknown = struct.unpack_from(">IQQQ", header, 20)
    _need((metadata_size, file_size, data_offset, unknown) == (
        profile["metadata_bytes"], profile["source_bytes"], profile["data_offset"], 0)
        and 48 + metadata_size <= data_offset <= MAX_METADATA_BYTES,
        "Original UI serialized header differs")
    metadata = header + _exact(source, data_offset - 48)
    _need(_sha(metadata) == profile["metadata_sha256"], "Original UI metadata differs")
    table, count = profile["table_offset"], profile["object_count"]
    _need(48 <= table and table + count * 24 <= 48 + metadata_size
          and struct.unpack_from("<i", metadata, profile["object_count_offset"])[0] == count,
          "Original UI object table differs")
    matches = 0
    start, length = profile["target_relative_offset"], profile["target_bytes"]
    for index in range(count):
        path_id, relative, size, type_id = struct.unpack_from("<qQIi", metadata, table + index * 24)
        _need(0 <= type_id < profile["type_count"] and relative + size <= file_size - data_offset,
              "UI object record exceeds its serialized file")
        if path_id == profile["target_path_id"]:
            matches += 1
            _need((index, relative, size, type_id) == (profile["target_index"], start, length, profile["target_type_id"]),
                  "Original UI TextAsset record differs")
        else:
            _need(relative + size <= start or relative >= start + length, "UI TextAsset overlaps another object")
    _need(matches == 1, "Expected one original UI TextAsset")
    return metadata


def _first_pass(source, metadata, profile):
    digest = hashlib.sha256(metadata)
    position = len(metadata)
    start = profile["data_offset"] + profile["target_relative_offset"]
    end = start + profile["target_bytes"]
    target = bytearray()
    while position < profile["source_bytes"]:
        block = source.read(min(COPY_BYTES, profile["source_bytes"] - position))
        _need(isinstance(block, bytes) and bool(block), "Truncated original UI asset data")
        digest.update(block)
        low, high = max(position, start), min(position + len(block), end)
        if high > low:
            target.extend(block[low - position:high - position])
        position += len(block)
    _need(source.read(1) == b"" and digest.hexdigest() == profile["source_sha256"],
          "Original UI asset full fingerprint differs")
    target = bytes(target)
    _need(len(target) == profile["target_bytes"] and _sha(target) == profile["target_object_sha256"],
          "Original UI TextAsset payload differs")
    return target


def _replacement(target, csv_bytes, profile):
    name_size = struct.unpack_from("<I", target)[0]
    _need(name_size <= 128 and target[4:4 + name_size].decode("utf-8") == profile["target_name"],
          "Original UI TextAsset name differs")
    size_offset = (4 + name_size + 3) & ~3
    _need(size_offset == 20 and struct.unpack_from("<I", target, size_offset)[0] == ORIGINAL_SCRIPT_BYTES
          and len(target) == size_offset + 4 + ORIGINAL_SCRIPT_BYTES
          and _sha(target[size_offset + 4:]) == ORIGINAL_SCRIPT_SHA256,
          "Original UI TextAsset script field differs")
    result = target[:size_offset] + struct.pack("<I", len(csv_bytes)) + csv_bytes
    return result + b"\0" * (-len(result) % 4)


def patch_asset_stream(source, destination, csv_bytes, platform, *, language="ja", translation_proof=None):
    """Verify before output, then stream one TextAsset replacement in two passes.

    Source must support seek(0), as ZipExtFile does. Destination may be a
    forward-only ZipWriteFile. At most the 10MiB metadata and small target/script
    are retained; the complete 65MiB iOS resource file is never materialized.
    """
    _need(platform in ASSETS, "Unknown UI asset platform")
    translation = validate_proof(translation_proof, csv_bytes, language)
    profile = ASSETS[platform]
    source.seek(0)
    metadata = _metadata(source, profile)
    target = _first_pass(source, metadata, profile)  # Full original verified before any output write.
    replacement = target if language == "ja" else _replacement(target, csv_bytes, profile)
    # Keep every existing object's eight-byte placement aligned, including any
    # original inter-object padding; only the target receives new zero padding.
    extra_padding = -(len(replacement) - len(target)) % 8
    delta = len(replacement) + extra_padding - len(target)
    patched = bytearray(metadata)
    new_size = profile["source_bytes"] + delta
    _need(new_size > profile["data_offset"] and len(replacement) < 2**32, "UI asset size exceeds its format")
    struct.pack_into(">Q", patched, 24, new_size)
    table, start, length = profile["table_offset"], profile["target_relative_offset"], len(target)
    shifted = 0
    for index in range(profile["object_count"]):
        at = table + index * 24
        path_id, relative, size, type_id = struct.unpack_from("<qQIi", metadata, at)
        if path_id == profile["target_path_id"]:
            struct.pack_into("<I", patched, at + 16, len(replacement))
        elif delta and relative >= start + length:
            struct.pack_into("<Q", patched, at + 8, relative + delta)
            shifted += 1
    source.seek(0)
    _need(_exact(source, len(metadata)) == metadata, "UI metadata changed between streaming passes")
    source_digest, output_digest = hashlib.sha256(metadata), hashlib.sha256()
    _write(destination, patched, output_digest)
    # Input bytes outside the target remain verbatim, including all unknown
    # types, references, script IDs, object payloads and original padding.
    copied_digest = hashlib.sha256()
    before = start
    remaining = before
    while remaining:
        block = _exact(source, min(COPY_BYTES, remaining));remaining -= len(block)
        source_digest.update(block);copied_digest.update(block);_write(destination, block, output_digest)
    second_target = _exact(source, length)
    _need(second_target == target, "UI TextAsset changed between streaming passes")
    source_digest.update(second_target)
    _write(destination, replacement + b"\0" * extra_padding, output_digest)
    remaining = profile["source_bytes"] - len(metadata) - before - length
    while remaining:
        block = _exact(source, min(COPY_BYTES, remaining));remaining -= len(block)
        source_digest.update(block);copied_digest.update(block);_write(destination, block, output_digest)
    _need(source.read(1) == b"" and source_digest.hexdigest() == profile["source_sha256"],
          "Original UI asset changed during streaming replacement")
    return {"schema": 1, "policy": "fixed-ui-textasset-v1", "platform": platform, "language": language,
            "input_asset_bytes": profile["source_bytes"], "input_asset_sha256": profile["source_sha256"],
            "output_asset_bytes": new_size, "output_asset_sha256": output_digest.hexdigest(),
            "input_metadata_sha256": profile["metadata_sha256"], "output_metadata_sha256": _sha(patched),
            "target_path_id": profile["target_path_id"], "target_name": profile["target_name"],
            "input_object_sha256": _sha(target), "output_object_sha256": _sha(replacement),
            "input_script_bytes": ORIGINAL_SCRIPT_BYTES, "input_script_sha256": ORIGINAL_SCRIPT_SHA256,
            "output_script_bytes": ORIGINAL_SCRIPT_BYTES if language == "ja" else len(csv_bytes),
            "output_script_sha256": ORIGINAL_SCRIPT_SHA256 if language == "ja" else _sha(csv_bytes),
            "compiled_csv_sha256": _sha(csv_bytes), "ui_asset_byte_identical": language == "ja",
            "object_count": profile["object_count"], "other_object_count": profile["object_count"] - 1,
            "all_other_objects_byte_identical": True,
            "shifted_object_offsets": shifted, "physical_size_delta": delta,
            "new_inter_object_zero_padding": extra_padding, "original_other_payload_bytes_sha256": copied_digest.hexdigest(),
            "only_declared_metadata_and_target_changed": True, "type_and_external_metadata_unchanged": True,
            "runtime_translation_hooks_added": False, "font_assets_modified": False,
            "translation": translation, "physical_device_verified": False}


def android_members(archive, csv_bytes, *, language="ja", translation_proof=None):
    names = archive.namelist()
    _need(names.count(ANDROID_MEMBER) == 1, "Expected one isolated Android UI asset member")
    _need(archive.getinfo(ANDROID_MEMBER).file_size == ASSETS["android"]["source_bytes"], "Android UI member size differs")
    result = io.BytesIO()
    with archive.open(ANDROID_MEMBER) as source:
        report = patch_asset_stream(source, result, csv_bytes, "android", language=language,
                                    translation_proof=translation_proof)
    return {ANDROID_MEMBER: result.getvalue()}, report


def patch_ios_member(archive, member_name, destination, csv_bytes, *, language="ja", translation_proof=None):
    _need(isinstance(member_name, str) and member_name.startswith("Payload/")
          and member_name.endswith(".app/Data/resources.assets") and archive.namelist().count(member_name) == 1,
          "Expected the original iOS resources.assets member")
    _need(archive.getinfo(member_name).file_size == ASSETS["ios"]["source_bytes"], "iOS UI member size differs")
    with archive.open(member_name) as source:
        return patch_asset_stream(source, destination, csv_bytes, "ios", language=language,
                                  translation_proof=translation_proof)
