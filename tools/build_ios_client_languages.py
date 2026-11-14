#!/usr/bin/env python3
"""Build immutable language Data overlays from pinned, offline iOS clients.

Only the two language-dependent Data members are stored for Japanese/English.
The Korean client's common files and Korean overlays remain the signed base.
No Unity code, fonts, SDK state, or game-time translation hook is rewritten.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
from pathlib import Path
import stat
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


def build_client_languages(stock_ipa, base_ipa, output, *, english_csv, english_proof, report=None):
    from idoly_local.ui_assets import load_package_inputs
    from idoly_local.static_ui_assets import patch_ios_stream
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
            for language in ("ja", "en"):
                for row in manifest["languages"][language].values():
                    with check.open(row["member"]) as incoming:
                        identity = _stream(incoming)
                    _need(identity == {k: row[k] for k in ("bytes", "sha256")}, "Language output member differs")
        _need(_hash(stock_ipa) == stock_identity and _hash(base_ipa) == base_identity, "Language producer inputs changed")
        digest, size = _hash(partial)
        metadata = {"schema": 1, "bytes": size, "sha256": digest}
        receipt = {"schema": 1, "policy": POLICY, "source": manifest["source"], "package": metadata,
                   "common_files": len(manifest["common"]), "language_members": 2,
                   "signed_app_modified_at_runtime": False, "runtime_string_translation": False,
                   "manifest": manifest, "proofs": proofs}
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
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    receipt = build_client_languages(args.stock_ipa, args.base_ipa, args.output,
                                    english_csv=args.english_csv, english_proof=args.english_proof, report=args.report)
    print(json.dumps({"status": "PASS_PREBUILT_CLIENT_LANGUAGES", "package": receipt["package"],
                      "common_files": receipt["common_files"]}))


if __name__ == "__main__":
    main()
