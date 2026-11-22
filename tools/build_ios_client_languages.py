#!/usr/bin/env python3
"""Build immutable language Data overlays from pinned, offline iOS clients.

The Japanese/English overlays and freshly rebuilt Korean resources are stored
before launch. Korean common fonts and metadata remain the verified signed base;
a strict object comparison preserves every undeclared Korean resource object.
No Unity code, SDK state, or game-time translation hook is rewritten.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
from pathlib import Path
import stat
import struct
import tempfile
import sys
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from idoly_local.ios_client_data import (BUNDLE_ID, CHUNK, MAX_FILE, MAX_PACKAGE,
                                        OVERLAYS, POLICY, validate_manifest)

STOCK_SHA256 = "33197938a0990b267af2d67c09e9d1123694e28695fc39d9650ca4f6aa661848"
BASE_SHA256 = "d872903da8d79bf4a255888f9d5a952198ff47268cfcf7c35e8ac437b56e72a1"
STOCK_BYTES = 146438450
BASE_BYTES = 150132823
APP = "Payload/IDOLY PRIDE.app/"
METADATA = "Data/Managed/Metadata/global-metadata.dat"
RESOURCES = "Data/resources.assets"
DIRECT_GPU_PIN = "client-presentation/images/korean-ios-direct-gpu-v1.json"
DIRECT_GPU_PIN_SHA256 = "5a15ccce17f043d4c56424e2b6318f83bdcbc7b0614f56b0207239298d190131"


def _renderer_asset_verifier():
    import importlib.util
    spec = importlib.util.spec_from_file_location("idoly_ios_renderer_assets", ROOT / "tools/audit_mp4_renderer_assets.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _need(value, message):
    if not value:
        raise ValueError(message)


def _hash(path):
    before = Path(path).lstat()
    _need(stat.S_ISREG(before.st_mode), "Expected a regular language input")
    with Path(path).open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    after = Path(path).lstat()
    _need((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
          == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns), "Language input changed")
    return digest, before.st_size


def _entry(name):
    info = ZipInfo(name, (1980, 1, 1, 0, 0, 0))
    info.create_system = 3; info.external_attr = 0o100644 << 16
    info.compress_type = ZIP_DEFLATED
    return info


def _stream(incoming, outgoing=None):
    digest, count = hashlib.sha256(), 0
    while block := incoming.read(CHUNK):
        count += len(block)
        _need(count <= MAX_FILE, "Language member exceeds its bound")
        digest.update(block)
        if outgoing is not None:
            _need(outgoing.write(block) == len(block), "Incomplete language member write")
    return {"bytes": count, "sha256": digest.hexdigest()}


def _metadata_variant(raw, language):
    from idoly_local.client_patch import patch_metadata
    from idoly_local.ios_patch import PROFILE_6_1_1, _patch_octo_origin
    from idoly_local.ui_display_literals import patch_bytes
    _need(hashlib.sha256(raw).hexdigest() == PROFILE_6_1_1.metadata_sha256,
          "Original language metadata differs")
    octo, _ = _patch_octo_origin(raw, PROFILE_6_1_1.octo_literal_index)
    local, routing = patch_metadata(octo, "http://127.0.0.1:50051")
    del octo
    result, proof = patch_bytes(local, "ios", language, expected_sha256=routing["output_sha256"])
    return result, proof


def _exact(source, count):
    _need(0 <= count <= MAX_FILE, "Serialized resource read exceeds its bound")
    raw = bytearray()
    while len(raw) < count:
        block = source.read(min(CHUNK, count - len(raw)))
        _need(bool(block), "Truncated serialized resource")
        raw.extend(block)
    return bytes(raw)


def _skip(source, count):
    _need(0 <= count <= MAX_FILE, "Serialized resource skip exceeds its bound")
    while count:
        block = _exact(source, min(CHUNK, count)); count -= len(block)


def _build_source_pins():
    names = ("tools/build_ios_client_languages.py", "tools/fetch_korean_ui_images.py",
             "tools/audit_mp4_renderer_assets.py",
             "src/idoly_local/static_ui_assets.py",
             "src/idoly_local/static_ui_images.py", "src/idoly_local/static_ui_textures.py",
             "src/idoly_local/ui_assets.py", "src/idoly_local/cdn_image_translation.py",
             "client-presentation/images/korean-static-sprites-v1.json",
             "client-presentation/images/korean-static-sprites-v2.json",
             "client-presentation/images/korean-static-textures-v1.json",
             "client-presentation/images/korean-ios-direct-gpu-v1.json",
             "client-presentation/translations/static-ui-v1.json")
    return {name: _hash(ROOT / name)[0] for name in names}


def _resource_index(source):
    """Read bounded original v22 metadata, retaining no bulk object payloads."""
    header = _exact(source, 48)
    _need(header[:20] == struct.pack(">4I", 0, 0, 22, 0) + b"\0" * 4,
          "Unexpected resource serialization header")
    metadata_size, size, offset, unknown = struct.unpack_from(">IQQQ", header, 20)
    _need(unknown == 0 and 48 + metadata_size <= offset <= 12 * 1024 * 1024
          and offset <= size <= MAX_FILE, "Resource metadata exceeds its bound")
    metadata = header + _exact(source, offset - 48)
    at = metadata.index(b"\0", 48, 80) + 1
    _need(metadata[48:at] == b"2022.3.57f1\0", "Resource Unity version differs")
    at += 4
    _need(metadata[at] == 0, "Expected stripped original resource type trees")
    count = struct.unpack_from("<i", metadata, at + 1)[0]; at += 5
    _need(0 < count <= 16384, "Resource type count exceeds its bound")
    types = []
    for _ in range(count):
        _need(at + 23 <= len(metadata), "Truncated resource type")
        cls = struct.unpack_from("<i", metadata, at)[0]
        length = 39 if cls == 114 else 23
        _need(at + length <= len(metadata), "Truncated resource script type")
        types.append((cls, metadata[at:at + length])); at += length
    count = struct.unpack_from("<i", metadata, at)[0]; at = (at + 7) & ~3
    _need(0 < count <= 500000 and at + 24 * count <= 48 + metadata_size,
          "Resource object table exceeds its bound")
    last, previous_end, physical_order = 0, 0, True
    for number in range(count):
        path, relative, length, kind = struct.unpack_from("<qQIi", metadata, at + number * 24)
        _need(last < path and 0 <= kind < len(types) and relative + length <= size - offset,
              "Invalid resource object extent")
        physical_order = physical_order and relative >= previous_end
        last, previous_end = path, relative + length
    order = None
    if not physical_order:
        from array import array
        # Keep only compact record indexes, not 419k Python object tuples.
        order = array("I", sorted(range(count), key=lambda n: struct.unpack_from("<Q", metadata, at + n * 24 + 8)[0]))
        previous_end = 0
        for number in order:
            _, relative, length, _ = struct.unpack_from("<qQIi", metadata, at + number * 24)
            _need(relative >= previous_end, "Resource objects overlap"); previous_end = relative + length
    return {"metadata": metadata, "table": at, "types": types, "count": count,
            "order": order, "offset": offset, "bytes": size}


def _resource_rows(index):
    order = index["order"] if index["order"] is not None else range(index["count"])
    for number in order:
        yield struct.unpack_from("<qQIi", index["metadata"], index["table"] + number * 24)


def _korean_csv(base):
    """Recover reviewed CSV bytes only from the exact pinned Korean donor."""
    from idoly_local.ui_assets import ASSETS, ORIGINAL_CSV_SHA256, validate_csv
    profile = ASSETS["ios"]
    with base.open(APP + RESOURCES) as incoming:
        index = _resource_index(incoming)
        row = next((r for r in _resource_rows(index) if r[0] == profile["target_path_id"]), None)
        _need(row is not None and index["types"][row[3]][0] == 49 and row[2] <= 1024 * 1024,
              "Korean donor UI TextAsset is missing")
        _skip(incoming, row[1])
        raw = _exact(incoming, row[2])
    name_size = struct.unpack_from("<I", raw)[0]
    _need(name_size == len(profile["target_name"]) and raw[4:4 + name_size] == profile["target_name"].encode(),
          "Korean donor TextAsset identity differs")
    at = (4 + name_size + 3) & ~3
    size = struct.unpack_from("<I", raw, at)[0]; at += 4
    _need(0 < size <= 1024 * 1024 and at + size <= len(raw), "Korean donor UI text exceeds its bound")
    csv = raw[at:at + size]; identity = validate_csv(csv)
    proof = {"language": "ko", "input_sha256": ORIGINAL_CSV_SHA256,
             "output_sha256": identity["sha256"], "bytes": len(csv), "source_ui_keys": 4199,
             "donor": {"base_ipa_sha256": BASE_SHA256, "member": APP + RESOURCES,
                       "path_id": row[0], "object_sha256": hashlib.sha256(raw).hexdigest()}}
    return csv, proof


def _compare_korean_resources(original, prepared, image_proof):
    """Permit the finite text Sprite/Texture pairs and three logo transforms."""
    from idoly_local.static_ui_images import (FIXED_LOVE_TEXT, TEXT_LAYOUT_POLICY,
        LOGO_LAYOUT_POLICY, LOGO_TRANSFORMS)
    changed = [row for row in image_proof["sprites"] if row["name"] in FIXED_LOVE_TEXT]
    _need(len(changed) == len(FIXED_LOVE_TEXT)
          and {row["name"] for row in changed} == set(FIXED_LOVE_TEXT)
          and all(row["layout_policy"] == TEXT_LAYOUT_POLICY and row["readback_pixel_exact"] is True
                  and row["layout_size"] == row["original_layout_size"] for row in changed),
          "Korean button geometry proof is incomplete")
    allowed = {row["sprite_path_id"]: 213 for row in changed}
    allowed.update({row["private_texture_path_id"]: 28 for row in changed})
    _need(len(allowed) == 2 * len(FIXED_LOVE_TEXT), "Korean button object IDs overlap")
    logo=image_proof.get("logo_layout",{})
    transforms=logo.get("transforms",[])
    _need(logo.get("policy")==LOGO_LAYOUT_POLICY and logo.get("platform")=="ios"
          and logo.get("uniform_scale")==0.75 and logo.get("content_size")==[94.5,24.0]
          and logo.get("full_translated_glyphs_preserved") is True
          and logo.get("all_other_object_bytes_identical") is True
          and len(transforms)==3 and {row["name"] for row in transforms}==set(LOGO_TRANSFORMS),
          "Korean whole-logo layout proof is incomplete")
    logo_hashes={}
    for row in transforms:
        target=LOGO_TRANSFORMS[row["name"]]; source=target["ios"]
        _need(row.get("path_id")==source["path_id"] and row.get("class_id")==224
              and row.get("input_sha256")==source["sha256"] and row.get("only_position_and_size_changed") is True
              and row.get("position")==[target["x"],0.0] and row.get("size")==[target["width"],24.0]
              and row.get("uniform_scale")==0.75 and row["path_id"] not in allowed,
              "Korean whole-logo target differs")
        allowed[row["path_id"]]=224; logo_hashes[row["path_id"]]=row
    before, after = _resource_index(original), _resource_index(prepared)
    _need(before["types"] == after["types"] and before["count"] == after["count"]
          and before["metadata"][:24] == after["metadata"][:24]
          and before["metadata"][32:before["table"]] == after["metadata"][32:after["table"]]
          and before["metadata"][before["table"] + 24 * before["count"]:]
              == after["metadata"][after["table"] + 24 * after["count"]:],
          "Korean resource graph outside the declared objects differs")
    positions = [before["offset"], after["offset"]]
    differences, preserved = [], 0
    for old, new in zip(_resource_rows(before), _resource_rows(after)):
        _need(old[0] == new[0] and old[3] == new[3], "Korean resource object order or type changed")
        path, _, _, kind = old
        hashes, payloads = [], []
        for number, (stream, index, row) in enumerate(((original, before, old), (prepared, after, new))):
            _skip(stream, index["offset"] + row[1] - positions[number])
            digest = hashlib.sha256(); remaining = row[2]
            captured=bytearray() if path in logo_hashes else None
            if captured is not None: _need(remaining==108,"Korean whole-logo object length differs")
            while remaining:
                block = _exact(stream, min(CHUNK, remaining)); digest.update(block); remaining -= len(block)
                if captured is not None: captured.extend(block)
            if captured is not None: payloads.append(bytes(captured))
            positions[number] = index["offset"] + row[1] + row[2]
            hashes.append(digest.hexdigest())
        if path in allowed:
            _need(before["types"][kind][0] == allowed[path], "Declared Korean object has a different class")
            if path in logo_hashes:
                row=logo_hashes[path]
                from idoly_local.static_ui_images import _logo_rect
                expected,_=_logo_rect(payloads[0],row["name"],"ios")
                _need(old[2]==new[2]==108 and hashes==[row["input_sha256"],row["output_sha256"]]
                      and payloads[1]==expected,"Korean whole-logo serialized bytes differ")
            differences.append({"path_id": path, "class_id": allowed[path], "before_sha256": hashes[0],
                                "after_sha256": hashes[1], "changed": hashes[0] != hashes[1]})
        else:
            _need(old[2] == new[2] and hashes[0] == hashes[1],
                  "An undeclared Korean UI, font, story or other resource object changed: "
                  f"path_id={path}, class_id={before['types'][kind][0]}, "
                  f"old_bytes={old[2]}, new_bytes={new[2]}, "
                  f"old_sha256={hashes[0]}, new_sha256={hashes[1]}")
            preserved += 1
    _need({row["path_id"] for row in differences} == set(allowed), "Declared Korean object is missing")
    return {"declared_object_differences": differences, "all_other_objects_byte_identical": True,
            "unchanged_object_count": preserved, "type_graph_and_external_references_unchanged": True}


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        _need(key not in result, "Duplicate canonical GPU pin key")
        result[key] = value
    return result


def _direct_gpu_catalog():
    """Bind only the fourteen already reviewed GPU objects to their PNG pixels."""
    from idoly_local.static_ui_textures import PROFILES, SOURCE
    path = ROOT / DIRECT_GPU_PIN
    _need(not path.is_symlink() and stat.S_ISREG(path.stat().st_mode)
          and 0 < path.stat().st_size <= 32 * 1024, "Canonical GPU pin exceeds its boundary")
    raw = path.read_bytes()
    _need(hashlib.sha256(raw).hexdigest() == DIRECT_GPU_PIN_SHA256,
          "Canonical GPU pin fingerprint differs")
    data = json.loads(raw, object_pairs_hook=_unique_pairs)
    _need(set(data) == {"schema", "policy", "source", "stock_ipa_sha256", "base_ipa_sha256", "textures"}
          and data["schema"] == 1 and data["policy"] == "korean-ios-direct-gpu-v1"
          and data["source"] == SOURCE and data["stock_ipa_sha256"] == STOCK_SHA256
          and data["base_ipa_sha256"] == BASE_SHA256, "Canonical GPU donor binding differs")
    rows = data["textures"]
    profiles = {profile["ios"]["path_id"]: profile for profile in PROFILES}
    _need(isinstance(rows, list) and len(rows) == len(profiles) == 14
          and {row["path_id"] for row in rows} == set(profiles)
          and len({row["name"] for row in rows}) == 14, "Canonical GPU object roster differs")
    row_keys = {"name", "path_id", "input_sha256", "output_sha256", "output_bytes", "png_sha256",
                "original_width", "original_height", "width", "height", "format_before", "format_after",
                "GPU_bytes_before", "GPU_bytes_after", "CPU_pixel_copy_retained",
                "original_shared_stream_unchanged", "unrelated_texture_fields_preserved", "PNG_resampled",
                "encoding", "source_RGBA_sha256", "decoded_RGBA_sha256", "rms_RGB", "quality", "threads",
                "GPU_bytes", "encoder_version"}
    for row in rows:
        _need(set(row) == row_keys, "Canonical GPU object fields differ")
        profile = profiles[row["path_id"]]; target = profile["ios"]
        _need(row["name"] == profile["name"] and row["png_sha256"] == profile["png_sha256"]
              and row["input_sha256"] == target["object_sha256"]
              and [row["original_width"], row["original_height"]] == [target["width"], target["height"]]
              and [row["width"], row["height"]] == profile["png_size"]
              and row["format_before"] == row["format_after"] == target["format"] == 50
              and row["quality"] == 60 and row["threads"] == 1
              and row["encoder_version"] == "0.1.12" and row["encoding"] == "ASTC6x6-medium"
              and row["CPU_pixel_copy_retained"] is False and row["PNG_resampled"] is False
              and row["original_shared_stream_unchanged"] is True
              and row["unrelated_texture_fields_preserved"] is True,
              "Canonical GPU source or layout differs")
    return profiles, {row["path_id"]: row for row in rows}


def _pinned_resource_objects(archive, pins):
    """Read a finite positive-ID set; no undeclared donor payload is retained."""
    result = {}
    with archive.open(APP + RESOURCES) as incoming:
        index = _resource_index(incoming); position = index["offset"]
        for path, relative, length, kind in _resource_rows(index):
            if path not in pins:
                continue
            expected = pins[path]
            _need(index["types"][kind][0] == 28 and length == expected["bytes"]
                  and 0 < length <= 1024 * 1024, "Canonical GPU object class or extent differs")
            _skip(incoming, index["offset"] + relative - position)
            raw = _exact(incoming, length); position = index["offset"] + relative + length
            _need(hashlib.sha256(raw).hexdigest() == expected["sha256"],
                  "Canonical GPU object fingerprint differs")
            result[path] = raw
    _need(result.keys() == pins.keys(), "Canonical GPU object is missing")
    return result


def _validate_direct_gpu(original, raw, profile, pin, image_dir):
    """Decode preserved bytes and source PNG; never recompress ASTC on this host."""
    target = profile["ios"]
    _need(len(original) == target["bytes"]
          and hashlib.sha256(original).hexdigest() == target["object_sha256"]
          and len(raw) == pin["output_bytes"]
          and hashlib.sha256(raw).hexdigest() == pin["output_sha256"],
          "Canonical GPU source or donor fingerprint differs")
    import attrs
    from io import BytesIO
    from idoly_local import static_ui_images as images
    _, Image = images._imports()
    png = images._png(image_dir, profile)
    with Image.open(BytesIO(png)) as image:
        _need(image.format == "PNG" and image.size == tuple(profile["png_size"]),
              "Canonical GPU source PNG layout differs")
        source = image.convert("RGBA")
    _need(hashlib.sha256(source.tobytes()).hexdigest() == pin["source_RGBA_sha256"],
          "Canonical GPU source pixels differ")
    _, reader = images._mini_asset(original, 28, 9); before = reader.read()
    _, reader = images._mini_asset(raw, 28, 9); after = reader.read()
    old_stream, stream = before.m_StreamData, after.m_StreamData
    _need(before.m_Name == profile["name"]
          and [before.m_Width, before.m_Height] == [target["width"], target["height"]]
          and int(before.m_TextureFormat) == target["format"] and before.m_MipCount == target["mips"]
          and {"path": old_stream.path, "offset": old_stream.offset, "size": old_stream.size} == target["stream_data"],
          "Canonical GPU original Texture2D layout differs")
    old_gpu = ((before.m_Width + 5) // 6) * ((before.m_Height + 5) // 6) * 16
    expected_gpu = ((source.width + 5) // 6) * ((source.height + 5) // 6) * 16
    _need(before.m_CompleteImageSize == old_gpu == pin["GPU_bytes_before"]
          and (old_stream.size == old_gpu and not before.image_data if old_stream.path
               else len(before.image_data) == old_gpu)
          and [after.m_Width, after.m_Height] == [source.width, source.height]
          and int(after.m_TextureFormat) == target["format"] and after.m_MipCount == 1
          and after.m_CompleteImageSize == len(after.image_data) == expected_gpu
          == pin["GPU_bytes_after"] == pin["GPU_bytes"]
          and not after.m_IsReadable and not stream.path and stream.offset == stream.size == 0,
          "Canonical GPU translated Texture2D allocation differs")
    mutable = {"image_data", "m_Width", "m_Height", "m_CompleteImageSize", "m_IsReadable", "m_StreamData"}
    _need({key: value for key, value in attrs.asdict(before).items() if key not in mutable}
          == {key: value for key, value in attrs.asdict(after).items() if key not in mutable},
          "Canonical GPU unrelated Texture2D fields differ")
    decoded = after.image.convert("RGBA")
    _need(decoded.size == source.size
          and hashlib.sha256(decoded.tobytes()).hexdigest() == pin["decoded_RGBA_sha256"],
          "Canonical GPU decoded pixels differ")


def _canonical_direct_textures(stock, base, image_dir):
    """Keep audited donor ASTC bytes stable across x86 and ARM build hosts."""
    from idoly_local.static_ui_textures import _proof
    profiles, pins = _direct_gpu_catalog()
    stock_pins = {path: {"bytes": profile["ios"]["bytes"], "sha256": profile["ios"]["object_sha256"]}
                  for path, profile in profiles.items()}
    donor_pins = {path: {"bytes": row["output_bytes"], "sha256": row["output_sha256"]}
                  for path, row in pins.items()}
    originals = _pinned_resource_objects(stock, stock_pins)
    canonical = _pinned_resource_objects(base, donor_pins)
    replacements = {}; rows = []
    for path, profile in profiles.items():
        pin = pins[path]; raw = canonical.pop(path)
        _validate_direct_gpu(originals.pop(path), raw, profile, pin, image_dir)
        replacements[path] = {"input_sha256": profile["ios"]["object_sha256"], "raw": raw}
        rows.append(dict(pin))
    proof = _proof("ios", "ko", rows)
    proof["GPU_byte_source"] = {"policy": "preserve-canonical-donor-astc-v1",
        "base_ipa_sha256": BASE_SHA256, "pin_sha256": DIRECT_GPU_PIN_SHA256,
        "object_count": 14, "host_reencoded": False, "source_and_decoded_pixels_verified": True}
    return replacements, proof


def _korean_resources(stock, base, destination, image_dir):
    from idoly_local.static_ui_assets import patch_ios_stream
    from idoly_local.static_ui_images import ios_patches
    csv, csv_proof = _korean_csv(base)
    replacements, appends, images = ios_patches(stock, language="ko", image_dir=image_dir)
    direct, direct_proof = _canonical_direct_textures(stock, base, image_dir)
    _need(not replacements.keys() & direct.keys(), "Korean sprite and direct texture targets overlap")
    replacements.update(direct); images["direct_textures"] = direct_proof
    with tempfile.TemporaryFile(mode="w+b") as staged:
        with stock.open(APP + RESOURCES) as incoming:
            proof = patch_ios_stream(incoming, staged, language="ko", ui_csv=csv, ui_proof=csv_proof,
                                     extra_replacements=replacements, append_objects=appends, image_proof=images)
        staged.seek(0)
        with base.open(APP + RESOURCES) as original:
            graph = _compare_korean_resources(original, staged, images)
        staged.seek(0); identity = _stream(staged, destination)
    _need(identity == {"bytes": proof["output_asset_bytes"], "sha256": proof["output_asset_sha256"]},
          "Korean prepared resource bytes differ")
    return identity, {"ui_translation": csv_proof, "static_images": images,
                      "output": identity, "original_stock_rebuilt": True, **graph}


def build_client_languages(stock_ipa, base_ipa, output, *, english_csv, english_proof, image_dir=None, report=None):
    from idoly_local.ui_assets import load_package_inputs
    from idoly_local.static_ui_assets import patch_ios_stream
    _need(image_dir is not None, "Fresh Korean resource generation requires explicit pinned image inputs")
    stock_ipa, base_ipa, output = map(Path, (stock_ipa, base_ipa, output))
    descriptor = output.with_suffix(".json")
    report = Path(report) if report else output.with_suffix(".report.json")
    _need(output.name == "client-languages.zip", "Use the fixed client-languages.zip output name")
    _need(not any(p.exists() or p.is_symlink() for p in (output, descriptor, report)), "Choose fresh language outputs")
    stock_identity, base_identity = _hash(stock_ipa), _hash(base_ipa)
    _need(stock_identity == (STOCK_SHA256, STOCK_BYTES) and base_identity == (BASE_SHA256, BASE_BYTES),
          "Stock or Korean base IPA differs from its pinned source")
    renderer_assets = _renderer_asset_verifier()
    program_inputs = {"stock": renderer_assets.verify_archive(stock_ipa, "ios"),
                      "base": renderer_assets.verify_archive(base_ipa, "ios")}
    csv, csv_proof = load_package_inputs("en", english_csv, english_proof)
    manifest = {"schema": 1, "policy": POLICY, "bundle_id": BUNDLE_ID,
                "common": {}, "languages": {language: {} for language in ("ja", "ko", "en")},
                "source": {"stock_ipa_sha256": STOCK_SHA256, "base_ipa_sha256": BASE_SHA256,
                           "english_ui_sha256": hashlib.sha256(csv).hexdigest()}}
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_suffix(".zip.part")
    _need(not partial.exists() and not partial.is_symlink(), "A prior language partial was preserved")
    proofs = {}
    build_sources = _build_source_pins()
    try:
        with ZipFile(stock_ipa) as stock, ZipFile(base_ipa) as base, ZipFile(partial, "x", compression=ZIP_DEFLATED, compresslevel=6) as archive:
            for source in (stock, base):
                infos = source.infolist()
                _need(len(infos) <= 8192 and len({i.filename for i in infos}) == len(infos), "Invalid IPA inventory")
            data_members = [i for i in base.infolist() if i.filename.startswith(APP + "Data/") and not i.is_dir()]
            _need(0 < len(data_members) <= 1024, "Invalid base Data inventory")
            for info in data_members:
                _need(not info.flag_bits & 1 and stat.S_IFMT(info.external_attr >> 16) in (0, stat.S_IFREG)
                      and info.file_size <= MAX_FILE, "Invalid base Data member")
                name = info.filename[len(APP):]
                with base.open(info) as incoming:
                    row = _stream(incoming)
                _need(row["bytes"] == info.file_size, "Truncated base Data member")
                if name in OVERLAYS:
                    manifest["languages"]["ko"][name] = {**row, "source": "base"}
                else:
                    manifest["common"][name] = row
            _need(manifest["languages"]["ko"].keys() == OVERLAYS, "Korean Data overlays missing")
            member = "ko/" + RESOURCES
            with archive.open(_entry(member), "w") as destination:
                row, korean_proof = _korean_resources(stock, base, destination, image_dir)
            manifest["languages"]["ko"][RESOURCES] = {**row, "source": "archive", "member": member}
            proofs["korean_resources"] = korean_proof
            for language in ("ja", "en"):
                member = language + "/" + RESOURCES
                with stock.open(APP + RESOURCES) as incoming, archive.open(_entry(member), "w") as destination:
                    if language == "ja":
                        row = _stream(incoming, destination)
                        from idoly_local.ui_assets import ASSETS
                        _need((row["sha256"], row["bytes"]) == (ASSETS["ios"]["source_sha256"], ASSETS["ios"]["source_bytes"]),
                              "Japanese original resources differ")
                    else:
                        proof = patch_ios_stream(incoming, destination, language="en", ui_csv=csv, ui_proof=csv_proof)
                        row = {"bytes": proof["output_asset_bytes"], "sha256": proof["output_asset_sha256"]}
                        proofs["english_resources"] = {k: v for k, v in proof.items() if k != "changes"}
                manifest["languages"][language][RESOURCES] = {**row, "source": "archive", "member": member}
                gc.collect()
                _need(stock.getinfo(APP + METADATA).file_size <= 32 * 1024 * 1024, "Metadata input exceeds bound")
                original_metadata = stock.read(APP + METADATA)
                metadata, proof = _metadata_variant(original_metadata, language)
                del original_metadata
                member = language + "/" + METADATA
                archive.writestr(_entry(member), metadata, compress_type=ZIP_DEFLATED, compresslevel=6)
                manifest["languages"][language][METADATA] = {
                    "bytes": len(metadata), "sha256": hashlib.sha256(metadata).hexdigest(), "source": "archive", "member": member}
                proofs[language + "_metadata"] = proof
                del metadata
                gc.collect()
            validate_manifest(manifest)
            archive.writestr(_entry("manifest.json"), (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode(),
                             compress_type=ZIP_DEFLATED, compresslevel=6)
        _need(partial.stat().st_size <= MAX_PACKAGE, "Language package exceeds its bound")
        with ZipFile(partial) as check:
            program_overlays = {code: renderer_assets.verify_asset_bytes(check.read(code + "/" + RESOURCES), "ios", "resources.assets")
                                for code in ("ja", "ko", "en")}
            _need(check.testzip() is None, "Language package CRC differs")
            _need(json.loads(check.read("manifest.json")) == manifest, "Language manifest roundtrip differs")
            for language in ("ja", "ko", "en"):
                for row in manifest["languages"][language].values():
                    if row["source"] != "archive":
                        continue
                    with check.open(row["member"]) as incoming:
                        identity = _stream(incoming)
                    _need(identity == {k: row[k] for k in ("bytes", "sha256")}, "Language output member differs")
        _need(_hash(stock_ipa) == stock_identity and _hash(base_ipa) == base_identity, "Language producer inputs changed")
        _need(_build_source_pins() == build_sources, "Language build sources changed")
        digest, size = _hash(partial)
        metadata = {"schema": 1, "bytes": size, "sha256": digest}
        receipt = {"schema": 1, "policy": POLICY, "source": manifest["source"], "package": metadata,
                   "common_files": len(manifest["common"]), "language_members": 3, "korean_resources_refreshed": True,
                   "signed_app_modified_at_runtime": False, "runtime_string_translation": False,
                   "manifest": manifest, "proofs": proofs, "renderer_program_assets": {"inputs": program_inputs, "overlays": program_overlays},
                   "source_component_sha256": build_sources,
                   "source_commit": os.environ.get("GITHUB_SHA")}
        _need(not any(p.exists() or p.is_symlink() for p in (output, descriptor, report)), "Language output appeared during build")
        # These files share a directory/filesystem. Publishing with a hard
        # link gives exclusive creation even if a destination appears late.
        os.link(partial, output)
        partial.unlink()
        with descriptor.open("x") as stream:
            json.dump(metadata, stream, sort_keys=True); stream.write("\n")
        with report.open("x") as stream:
            json.dump(receipt, stream, indent=2); stream.write("\n")
        return receipt
    finally:
        if partial.exists():
            partial.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stock-ipa", type=Path, required=True)
    parser.add_argument("--base-ipa", type=Path, required=True)
    parser.add_argument("--english-csv", type=Path, required=True)
    parser.add_argument("--english-proof", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--image-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    receipt = build_client_languages(args.stock_ipa, args.base_ipa, args.output,
                                    english_csv=args.english_csv, english_proof=args.english_proof, image_dir=args.image_dir, report=args.report)
    print(json.dumps({"status": "PASS_PREBUILT_CLIENT_LANGUAGES", "package": receipt["package"],
                      "common_files": receipt["common_files"]}))


if __name__ == "__main__":
    main()
