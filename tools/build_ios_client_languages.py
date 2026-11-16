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
             "src/idoly_local/static_ui_assets.py",
             "src/idoly_local/static_ui_images.py", "src/idoly_local/static_ui_textures.py",
             "src/idoly_local/ui_assets.py", "src/idoly_local/cdn_image_translation.py",
             "client-presentation/images/korean-static-sprites-v1.json",
             "client-presentation/images/korean-static-sprites-v2.json",
             "client-presentation/images/korean-static-textures-v1.json",
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
    """Permit only the declared button Sprite/private-Texture pairs to change."""
    from idoly_local.static_ui_images import FIXED_LOVE_TEXT, TEXT_LAYOUT_POLICY
    changed = [row for row in image_proof["sprites"] if row["name"] in FIXED_LOVE_TEXT]
    _need(len(changed) == len(FIXED_LOVE_TEXT)
          and {row["name"] for row in changed} == set(FIXED_LOVE_TEXT)
          and all(row["layout_policy"] == TEXT_LAYOUT_POLICY and row["readback_pixel_exact"] is True
                  and row["layout_size"] == row["original_layout_size"] for row in changed),
          "Korean button geometry proof is incomplete")
    allowed = {row["sprite_path_id"]: 213 for row in changed}
    allowed.update({row["private_texture_path_id"]: 28 for row in changed})
    _need(len(allowed) == 2 * len(FIXED_LOVE_TEXT), "Korean button object IDs overlap")
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
        hashes = []
        for number, (stream, index, row) in enumerate(((original, before, old), (prepared, after, new))):
            _skip(stream, index["offset"] + row[1] - positions[number])
            digest = hashlib.sha256(); remaining = row[2]
            while remaining:
                block = _exact(stream, min(CHUNK, remaining)); digest.update(block); remaining -= len(block)
            positions[number] = index["offset"] + row[1] + row[2]
            hashes.append(digest.hexdigest())
        if path in allowed:
            _need(before["types"][kind][0] == allowed[path], "Declared Korean object has a different class")
            differences.append({"path_id": path, "class_id": allowed[path], "before_sha256": hashes[0],
                                "after_sha256": hashes[1], "changed": hashes[0] != hashes[1]})
        else:
            _need(old[2] == new[2] and hashes[0] == hashes[1],
                  "An undeclared Korean UI, font, story or other resource object changed")
            preserved += 1
    _need({row["path_id"] for row in differences} == set(allowed), "Declared Korean object is missing")
    return {"declared_object_differences": differences, "all_other_objects_byte_identical": True,
            "unchanged_object_count": preserved, "type_graph_and_external_references_unchanged": True}


def _korean_resources(stock, base, destination, image_dir):
    from idoly_local.static_ui_assets import patch_ios_stream
    from idoly_local.static_ui_images import ios_patches
    from idoly_local.static_ui_textures import ios_patches as direct_patches
    csv, csv_proof = _korean_csv(base)
    replacements, appends, images = ios_patches(stock, language="ko", image_dir=image_dir)
    direct, direct_proof = direct_patches(stock, language="ko", image_dir=image_dir)
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
                   "manifest": manifest, "proofs": proofs, "source_component_sha256": build_sources,
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
