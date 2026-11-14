"""Offline, SHA-pinned translation of serialized SolisText UI labels.

The 6.1.1 client also stores display text directly in prefabs, outside its
keyed I18n CSV. This build-only writer changes only the audited SolisText
``m_Text`` field. It never translates GameObject names, identifiers, script
strings, dynamic patterns, or text during a game frame. iOS combines these
objects and the existing I18n CSV in one streaming serialized-file rewrite.
"""
from __future__ import annotations

import bisect
import hashlib
import io
import json
from pathlib import Path
import struct


PROFILE_SHA256 = "7175b060b21334dbdc1604fdc2f873ee4e042b0af1a46e4d28cfddf66cc6c147"
PROFILE_PATH = Path(__file__).resolve().parents[2] / "client-presentation/translations/static-ui-v1.json"
POLICY = "prebuilt-static-solistext-v1"
SCRIPT_ID = "9121d42755a87215a893c380de4dbf0c"
TYPE_HASH = "cbd21103d83440b5b53d46c595501eba"
MAX_METADATA = 12 * 1024 * 1024
MAX_ASSET = 72 * 1024 * 1024
MAX_OBJECT = 1024 * 1024
CHUNK = 64 * 1024


def _need(condition, message):
    if not condition:
        raise ValueError(message)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _profile():
    _need(not PROFILE_PATH.is_symlink(), "Static UI profile must be a regular source file")
    with PROFILE_PATH.open("rb") as stream:
        raw = stream.read(768 * 1024 + 1)
    _need(len(raw) <= 768 * 1024 and _sha(raw) == PROFILE_SHA256,
          "Static UI profile differs from the audited source")
    result = json.loads(raw)
    _need(result["schema"] == 1 and result["policy"] == POLICY
          and result["script_id"] == SCRIPT_ID and result["type_hash"] == TYPE_HASH,
          "Static UI profile identity differs")
    return result


def _exact(stream, count):
    _need(0 <= count <= MAX_ASSET, "Static UI read exceeds its bound")
    value = bytearray()
    while len(value) < count:
        block = stream.read(min(CHUNK, count - len(value)))
        _need(isinstance(block, bytes) and bool(block), "Truncated static UI asset")
        value.extend(block)
    return bytes(value)


def _metadata(stream, profile):
    header = _exact(stream, 48)
    _need(struct.unpack_from(">4I", header) == (0, 0, 22, 0) and header[16:20] == b"\0" * 4,
          "Expected a little-endian v22 static UI asset")
    metadata_size, file_size, data_offset, unknown = struct.unpack_from(">IQQQ", header, 20)
    _need(unknown == 0 and file_size == profile["bytes"] <= MAX_ASSET
          and metadata_size == profile["metadata_bytes"]
          and data_offset == profile["data_offset"] <= MAX_METADATA,
          "Static UI serialized header differs")
    raw = header + _exact(stream, data_offset - 48)
    _need(_sha(raw) == profile["metadata_sha256"], "Static UI metadata fingerprint differs")
    at = raw.index(b"\0", 48) + 1 + 4
    _need(at < len(raw) and raw[at] == 0, "Static UI asset must retain stripped type trees")
    at += 1
    type_count = struct.unpack_from("<i", raw, at)[0]; at += 4
    _need(0 < type_count <= 16384, "Static UI serialized type count is invalid")
    types = []
    for _ in range(type_count):
        _need(at + 23 <= len(raw), "Truncated static UI serialized type")
        class_id, stripped, script_index = struct.unpack_from("<iBh", raw, at); at += 7
        script_id = None
        if class_id == 114:
            script_id = raw[at:at + 16].hex(); at += 16
        type_hash = raw[at:at + 16].hex(); at += 16
        types.append((class_id, script_index, script_id, type_hash))
    count_offset = at
    count = struct.unpack_from("<i", raw, at)[0]; at = (at + 7) & ~3
    _need(count == profile["object_count"] and count_offset == profile["count_offset"]
          and at == profile["table_offset"] and 0 < count <= 500000
          and at + 24 * count <= 48 + metadata_size,
          "Static UI object table differs")
    previous_path = 0
    spans = []
    for index in range(count):
        path, relative, size, type_id = struct.unpack_from("<qQIi", raw, at + 24 * index)
        _need(previous_path < path and 0 <= type_id < type_count
              and relative + size <= file_size - data_offset,
              "Static UI object identity or extent is invalid")
        previous_path = path
        if size:
            spans.append((relative, relative + size))
    spans.sort()
    _need(all(left[1] <= right[0] for left, right in zip(spans, spans[1:])),
          "Static UI object payloads overlap")
    return raw, types


def _records(metadata, profile):
    for index in range(profile["object_count"]):
        at = profile["table_offset"] + 24 * index
        yield index, at, struct.unpack_from("<qQIi", metadata, at)


def _translated_text(raw, target, text, platform):
    path, relative, size, type_id, digest, _ = target
    _need(len(raw) == size and _sha(raw) == digest,
          "Static UI SolisText payload differs from its audited object")
    _need(len(raw) >= 96 and struct.unpack_from("<i", raw, 28)[0] == 0
          and struct.unpack_from("<iq", raw, 16) == (1, 7023 if platform == "android" else 7002),
          "Static UI SolisText MonoScript or base-name layout differs")
    length = struct.unpack_from("<i", raw, 88)[0]
    before = text[0].encode("utf-8")
    _need(length == len(before) and raw[92:92 + length] == before,
          "Static UI m_Text must equal the complete audited source string")
    return raw[:88], (92 + length + 3) & ~3


def _first_pass(source, metadata, profile, wanted, accepted_hashes):
    """Verify the complete original before producing any output bytes."""
    digest = hashlib.sha256(metadata)
    position = len(metadata)
    originals = {}
    for path, (relative, size) in sorted(wanted.items(), key=lambda item: item[1][0]):
        absolute = profile["data_offset"] + relative
        _need(position <= absolute and 0 < size <= MAX_OBJECT, "Static UI target overlaps another target")
        while position < absolute:
            block = _exact(source, min(CHUNK, absolute - position))
            digest.update(block); position += len(block)
        value = _exact(source, size); digest.update(value); position += size
        originals[path] = value
    while position < profile["bytes"]:
        block = _exact(source, min(CHUNK, profile["bytes"] - position))
        digest.update(block); position += len(block)
    _need(source.read(1) == b"" and digest.hexdigest() in accepted_hashes,
          "Static UI asset differs from the original or declared composed input")
    return originals, digest.hexdigest()


def _rewrite(source, destination, profile, targets, texts, platform, language,
             *, csv_bytes=None, csv_proof=None, extra_replacements=None,
             append_objects=None, image_proof=None, accepted_hashes=None):
    _need(language in ("ja", "ko", "en"), "Unknown static UI language")
    source.seek(0)
    metadata, types = _metadata(source, profile)
    selected = []
    for target in targets:
        text = texts[target[5]]
        translated = text[1] if language == "ko" else text[2] if language == "en" else None
        if translated is not None and translated != text[0]:
            _need(isinstance(translated, str) and translated and "\0" not in translated
                  and len(translated.encode("utf-8")) <= 8192, "Invalid prebuilt static UI translation")
            selected.append((target, text, translated))
    extra_replacements = extra_replacements or {}
    append_objects = append_objects or []
    _need(isinstance(extra_replacements, dict) and len(extra_replacements) <= 16
          and isinstance(append_objects, list) and len(append_objects) <= 16,
          "Static UI extra object patch list exceeds its bound")
    by_path = {target[0]: target for target, _, _ in selected}
    _need(not by_path.keys() & extra_replacements.keys(), "Static UI and image target objects overlap")
    csv_target = None
    ui_report = None
    if csv_bytes is not None:
        _need(platform == "ios", "Combined CSV replacement is for the iOS resources asset")
        from . import ui_assets
        ui_report = ui_assets.validate_proof(csv_proof, csv_bytes, language)
        csv_target = ui_assets.ASSETS["ios"]
        _need(csv_target["target_path_id"] not in by_path
              and csv_target["target_path_id"] not in extra_replacements, "UI CSV object overlaps a static target")
    needed_ids = set(by_path) | set(extra_replacements)
    if csv_target:
        needed_ids.add(csv_target["target_path_id"])
    wanted = {}
    object_records = {}
    for index, at, record in _records(metadata, profile):
        path, relative, size, type_id = record
        if path in needed_ids:
            wanted[path] = (relative, size)
            object_records[path] = record
            if path in by_path:
                target = by_path[path]
                _need((path, relative, size, type_id) == tuple(target[:4])
                      and types[type_id][0] == 114 and types[type_id][2:] == (SCRIPT_ID, TYPE_HASH),
                      "Static UI target is not the pinned SolisText serialized type")
    _need(wanted.keys() == needed_ids, "A declared static UI target is absent")
    accepted_hashes = set(accepted_hashes or [profile["sha256"]])
    originals, input_digest = _first_pass(source, metadata, profile, wanted, accepted_hashes)
    replacements = {}
    changes = []
    for target, text, translated in selected:
        raw = originals[target[0]]
        prefix, end = _translated_text(raw, target, text, platform)
        encoded = translated.encode("utf-8")
        value = prefix + struct.pack("<i", len(encoded)) + encoded
        value += b"\0" * (-len(value) % 4) + raw[end:]
        replacements[target[0]] = value
        changes.append({"path_id": target[0], "source": text[0], "translation": translated,
                        "input_sha256": _sha(raw), "output_sha256": _sha(value)})
    if csv_target:
        raw = originals[csv_target["target_path_id"]]
        _need(_sha(raw) == csv_target["target_object_sha256"], "Original combined UI CSV object differs")
        # Japanese keeps the original encoded script, matching ui_assets' stock
        # path; its plaintext CSV input is only a build provenance reference.
        replacements[csv_target["target_path_id"]] = (raw if language == "ja"
            else ui_assets._replacement(raw, csv_bytes, csv_target))
    for path, item in extra_replacements.items():
        _need(isinstance(item, dict) and isinstance(item.get("raw"), bytes)
              and 0 < len(item["raw"]) <= MAX_OBJECT
              and _sha(originals[path]) == item.get("input_sha256"),
              "Extra static image object does not bind the exact original payload")
        _need(types[object_records[path][3]][0] == 213, "Extra replacement must target an existing Sprite")
        replacements[path] = item["raw"]
    last_path = struct.unpack_from("<q", metadata, profile["table_offset"] + 24 * (profile["object_count"] - 1))[0]
    for item in append_objects:
        _need(isinstance(item, dict) and type(item.get("path_id")) is int
              and item["path_id"] > last_path and type(item.get("type_id")) is int
              and 0 <= item["type_id"] < len(types) and types[item["type_id"]][0] == 28
              and isinstance(item.get("raw"), bytes) and 0 < len(item["raw"]) <= MAX_OBJECT,
              "Appended static image must be a new private Texture2D object")
        last_path = item["path_id"]
    ordered = sorted(replacements, key=lambda path: wanted[path][0])
    ends, cumulative = [], []
    total_delta = 0
    for path in ordered:
        relative, old_size = wanted[path]
        physical_delta = len(replacements[path]) - old_size
        physical_delta += -physical_delta % 8
        total_delta += physical_delta
        ends.append(relative + old_size); cumulative.append(total_delta)
    extra_records = bytearray()
    append_position = profile["bytes"] - profile["data_offset"] + total_delta
    append_padding = -append_position % 8 if append_objects else 0
    append_position += append_padding
    for item in append_objects:
        extra_records.extend(struct.pack("<qQIi", item["path_id"], append_position, len(item["raw"]), item["type_id"]))
        append_position += len(item["raw"]) + (-len(item["raw"]) % 8)
    patched = bytearray(metadata)
    shifted = 0
    for index, at, record in _records(metadata, profile):
        path, relative, size, type_id = record
        prior = bisect.bisect_right(ends, relative)
        delta = cumulative[prior - 1] if prior else 0
        if delta:
            struct.pack_into("<Q", patched, at + 8, relative + delta); shifted += 1
        if path in replacements:
            struct.pack_into("<I", patched, at + 16, len(replacements[path]))
    metadata_padding = -len(extra_records) % 16
    table_end = profile["table_offset"] + profile["object_count"] * 24
    if extra_records:
        patched[table_end:table_end] = extra_records
        patched.extend(b"\0" * metadata_padding)
        struct.pack_into("<i", patched, profile["count_offset"], profile["object_count"] + len(append_objects))
    new_data_offset = profile["data_offset"] + len(extra_records) + metadata_padding
    new_size = new_data_offset + append_position
    struct.pack_into(">IQQ", patched, 20, profile["metadata_bytes"] + len(extra_records), new_size, new_data_offset)
    output_digest = hashlib.sha256(); copied_digest = hashlib.sha256()
    def write(value):
        _need(destination.write(value) == len(value), "Incomplete static UI asset write")
        output_digest.update(value)
    source.seek(0)
    _need(_exact(source, len(metadata)) == metadata, "Static UI metadata changed between passes")
    source_digest = hashlib.sha256(metadata); position = len(metadata)
    write(patched)
    for path in ordered:
        relative, old_size = wanted[path]
        absolute = profile["data_offset"] + relative
        while position < absolute:
            block = _exact(source, min(CHUNK, absolute - position)); position += len(block)
            source_digest.update(block); copied_digest.update(block); write(block)
        old_raw = _exact(source, old_size); position += old_size
        _need(old_raw == originals[path], "Static UI object changed between passes")
        source_digest.update(old_raw)
        replacement = replacements[path]
        write(replacement)
        write(b"\0" * (-(len(replacement) - old_size) % 8))
    while position < profile["bytes"]:
        block = _exact(source, min(CHUNK, profile["bytes"] - position)); position += len(block)
        source_digest.update(block); copied_digest.update(block); write(block)
    _need(source.read(1) == b"" and source_digest.hexdigest() == input_digest,
          "Static UI source changed between streaming passes")
    write(b"\0" * append_padding)
    for item in append_objects:
        write(item["raw"]); write(b"\0" * (-len(item["raw"]) % 8))
    return {"schema": 1, "policy": POLICY, "platform": platform, "language": language,
            "input_asset_bytes": profile["bytes"], "input_asset_sha256": input_digest,
            "output_asset_bytes": new_size, "output_asset_sha256": output_digest.hexdigest(),
            "input_metadata_sha256": profile["metadata_sha256"], "output_metadata_sha256": _sha(patched),
            "source_profile_sha256": PROFILE_SHA256, "changed_static_texts": len(changes), "changes": changes,
            "source_object_count": profile["object_count"], "output_object_count": profile["object_count"] + len(append_objects),
            "image_object_replacements": len(extra_replacements), "appended_texture_objects": len(append_objects),
            "shifted_object_offsets": shifted, "original_other_payload_bytes_sha256": copied_digest.hexdigest(),
            "all_other_object_payloads_unchanged": True, "existing_type_and_external_metadata_unchanged": True,
            "runtime_translation_hooks_added": False, "ui_translation": ui_report, "images": image_proof,
            "device_playback_verified": False}


def android_members(archive, language="ja", *, existing_replacements=None):
    """Return translated prefab members; compose only the known story fade repair."""
    _need(language in ("ja", "ko", "en"), "Unknown static UI language")
    profile = _profile(); replacements = {}; reports = []
    existing_replacements = existing_replacements or {}
    if language == "ja":
        return {}, {"policy": POLICY, "language": language, "changed_static_texts": 0,
                    "changed_members": 0, "source_profile_sha256": PROFILE_SHA256, "assets": []}
    for asset in profile["android"]:
        if not any(profile["texts"][t[5]][1 if language == "ko" else 2] is not None for t in asset["targets"]):
            continue
        member = asset["member"]
        _need(archive.namelist().count(member) == 1 and archive.getinfo(member).file_size == asset["bytes"],
              "Expected one pinned static UI Android member")
        accepted = [asset["sha256"]]
        if member in existing_replacements:
            from . import story_loading_prefab
            _need(member == story_loading_prefab.MEMBER,
                  "Only the pinned story radio repair may precede static UI translation")
            accepted.append(story_loading_prefab.OUTPUT_SHA256)
            source = io.BytesIO(existing_replacements[member])
        else:
            source = archive.open(member)
        result = io.BytesIO()
        with source:
            report = _rewrite(source, result, asset, asset["targets"], profile["texts"], "android", language,
                              accepted_hashes=accepted)
        replacements[member] = result.getvalue()
        reports.append({"member": member, **report})
    return replacements, {"policy": POLICY, "language": language, "source_profile_sha256": PROFILE_SHA256,
                          "changed_members": len(reports), "changed_static_texts": sum(r["changed_static_texts"] for r in reports),
                          "assets": reports, "runtime_translation_hooks_added": False}


def patch_ios_stream(source, destination, language="ja", *, ui_csv=None, ui_proof=None,
                     extra_replacements=None, append_objects=None, image_proof=None):
    """Combine fixed UI CSV, static labels, and declared selected-badge sprites."""
    profile = _profile(); asset = profile["ios"][0]
    return _rewrite(source, destination, asset, asset["targets"], profile["texts"], "ios", language,
                    csv_bytes=ui_csv, csv_proof=ui_proof, extra_replacements=extra_replacements,
                    append_objects=append_objects, image_proof=image_proof)
