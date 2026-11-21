#!/usr/bin/env python3
"""Verify and publish one exact Actions iOS artifact on a remote Linux runner.

The publication proof contains metadata only. No game or native fixture is run.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import time
import zlib
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
REPO = "tagundo/IdolyPride_client"
IPA = "IdolyPride-6.1.1-Unified-iOS.ipa"
PACKAGE_REPORT = IPA.replace(".ipa", ".report.json")
MIB = 1024 * 1024
CHUNK = 128 * 1024
MAX_ARCHIVE = 768 * MIB
MAX_IPA = 600 * MIB
MAX_SMALL = 8 * MIB
MAX_METADATA = 32 * MIB
MAX_PROOF = 8 * MIB
PROOF_GENERATED_RESERVE = MIB
RESERVED_PROOF_NAMES = frozenset(("manifest.json","delivery-proof.json","publication.json",
                                 "proof-fetch.json","publish.log","README.md"))
LANGUAGE_PRODUCER_SOURCES = (
    "tools/build_ios_client_languages.py", "tools/fetch_korean_ui_images.py",
    "src/idoly_local/static_ui_assets.py", "src/idoly_local/static_ui_images.py",
    "src/idoly_local/static_ui_textures.py", "src/idoly_local/ui_assets.py",
    "src/idoly_local/cdn_image_translation.py",
    "client-presentation/images/korean-static-sprites-v1.json",
    "client-presentation/images/korean-static-sprites-v2.json",
    "client-presentation/images/korean-static-textures-v1.json",
    "client-presentation/images/korean-ios-direct-gpu-v1.json",
    "client-presentation/translations/static-ui-v1.json",
)
# Only the audited static UI catalog needs the larger source-file allowance.
SOURCE_FILE_LIMITS = {
    "data/latest-server-overlay.zip": 1024,
    "data/latest-server-data-pin.json": MIB,
    "data/korean-master-data-pin.json": MIB,
    "data/korean-master-overlay.zip": 64 * MIB,
    "data/love-server-data-pin.json": 512 * 1024,
    "client-presentation/translations/static-ui-v1.json": 768 * 1024,
}

DELIVERY_SOURCES = ("ios-unified/delivery.py", ".github/workflows/build-server-apps.yml",
                    "tools/publish_binary_bundle_lfs.py",
                    "ios-unified/delivery-pins/client-languages-real-v3.manifest.json",
                    "ios-unified/ci_build.py", "ios-unified/package_unified.py", "ios-unified/runtime_inputs.json",
                    "tools/build_startup_translation_receipt.py", "src/idoly_local/startup_receipt.py",
                    "tools/prepare_latest_server_data.py", "tools/latest_server_data_pin.py", "data/latest-server-data-pin.json",
                    "data/latest-server-overlay.zip", "data/love-server-data-pin.json", "data/love-reference.json", "data/love-adv-proof.json",
                    "tools/korean_server_data_pin.py", "tools/prepare_korean_master_data.py",
                    "data/korean-master-data-pin.json", "data/korean-master-overlay.zip",
                    "tools/refresh_korean_translation_bundle.py", "data/latest-korean-translations-pin.json",
                    "data/love-reference-NOTICE.txt", "src/idoly_local/love_catalog.py", "src/idoly_local/master_build.py",
                    "src/idoly_local/media_master_build.py", "src/idoly_local/master_translation_build.py",
                    "src/idoly_local/master_sort_build.py", "src/idoly_local/latest_cohort_pins.py",
                    "src/idoly_local/love_compatibility_pins.py", "src/idoly_local/public_cohort_support.py", "LICENSE",
                    *LANGUAGE_PRODUCER_SOURCES)

class DeliveryError(ValueError):
    """Fixed credential-free error codes."""

def need(value, code):
    if not value:
        raise DeliveryError(code)

def file_identity(info):
    return (info.st_dev,info.st_ino,info.st_mode,info.st_nlink,info.st_size,info.st_mtime_ns,info.st_ctime_ns)

def sha(path):
    with path.open("rb") as incoming:
        return hashlib.file_digest(incoming,"sha256").hexdigest()

def read(path):
    return small_json(path)

def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name,path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

PACKAGED_SERVER_DATA = {"pin":"../data/latest-server-data-pin.json","policy":"latest-cohort-overlay-v1"}
KOREAN_MASTER_REFRESH = {"pin":"../data/korean-master-data-pin.json","policy":"korean-master-refresh-v1"}


def _original_server_data_verifier():
    return load_module("delivery_latest_server_data_pin",ROOT/"tools/latest_server_data_pin.py")


def _packaged_server_data_verifier():
    return load_module("delivery_korean_server_data_pin",ROOT/"tools/korean_server_data_pin.py")


def _packaged_server_data_pin():
    try:
        manifest=small_json(HERE/"runtime_inputs.json")
        need(manifest.get("packaged_server_data")==PACKAGED_SERVER_DATA,"packaged_server_data_policy_differs")
        need(manifest.get("korean_master_refresh")==KOREAN_MASTER_REFRESH,"korean_master_refresh_policy_differs")
        original=_original_server_data_verifier()
        need(manifest["inputs"]["server_data"]==original.base_pin(),"packaged_server_data_base_differs")
        original.verify_source_pointer()
        verifier=_packaged_server_data_verifier()
        pin=verifier.output_pin()
        need(type(pin) is dict and set(pin)=={"bytes","sha256"} and type(pin["bytes"]) is int
            and 0<pin["bytes"]<=512*MIB and type(pin["sha256"]) is str
            and re.fullmatch(r"[0-9a-f]{64}",pin["sha256"]),"packaged_server_data_pin_invalid")
        return pin
    except DeliveryError:
        raise
    except Exception:
        raise DeliveryError("packaged_server_data_pin_unavailable") from None


def verify_server_data_provenance(members, package_report):
    final_pin=_packaged_server_data_pin()  # Both committed source pins are mandatory.
    try:
        original=_original_server_data_verifier()
        korean=_packaged_server_data_verifier()
        reported=package_report.get("server_data_provenance")
        proof=small_json(members/"server-data-upgrade.json")
        original_proof=original.verify_upgrade_proof(proof)
        korean_proof=korean.verify_refresh_proof(small_json(members/"server-data-korean-refresh.json"))
        need(korean_proof.get("base_payload")==original.output_pin()
             and korean_proof.get("output")==final_pin,"server_data_refresh_chain_differs")
        expected={"schema":1,"policy":KOREAN_MASTER_REFRESH["policy"],
                  "original_cohort":original_proof,"korean_master_refresh":korean_proof}
        need(expected==reported,"server_data_upgrade_proof_differs")
    except DeliveryError:
        raise
    except Exception:
        raise DeliveryError("server_data_upgrade_proof_invalid") from None


def _packaged_payload_pin_bytes():
    raw = (json.dumps(_packaged_server_data_verifier().payload_pin(), indent=2) + "\n").encode()
    need(0 < len(raw) <= 4096, "bundled_payload_pin_invalid")
    return raw


def verify_bundled_payload_pin(archive, prefix, package_report):
    """Bind the tiny installed-data identity to both source and actual IPA bytes."""
    name = prefix + "LocalServer/payload-pin.json"
    entries = [item for item in archive.infolist() if item.filename == name]
    need(len(entries) == 1 and not entries[0].is_dir()
         and not stat.S_ISLNK(entries[0].external_attr >> 16)
         and not entries[0].flag_bits & 1 and 0 < entries[0].file_size <= 4096,
         "bundled_payload_pin_invalid")
    with archive.open(entries[0]) as incoming:
        raw = incoming.read(4097)
        need(incoming.read(1) == b"", "bundled_payload_pin_invalid")
    expected = _packaged_payload_pin_bytes()
    need(len(raw) == entries[0].file_size and raw == expected
         and package_report.get("member_sha256", {}).get(name) == hashlib.sha256(raw).hexdigest(),
         "bundled_payload_pin_differs")


def _delivery_source_paths():
    names = set(DELIVERY_SOURCES)
    inventories = (_original_server_data_verifier().SOURCE_COMPONENTS,
                   _packaged_server_data_verifier().COMPONENTS)
    for components in inventories:
        need(type(components) is tuple and 0 < len(components) <= 128,
             "delivery_source_components_invalid")
        for name in components:
            need(type(name) is str and 0 < len(name) <= 256 and "\\" not in name and "\0" not in name,
                 "delivery_source_components_invalid")
            path = PurePosixPath(name)
            need(not path.is_absolute() and str(path) == name
                 and not any(part in ("", ".", "..") for part in path.parts),
                 "delivery_source_components_invalid")
            names.add(name)
    return tuple(sorted(names))


def delivery_source_pins(source):
    need(type(source) is str and re.fullmatch(r"[0-9a-f]{40}",source),"delivery_source_invalid")
    result = {}
    for name in _delivery_source_paths():
        path = ROOT/name
        need(path.is_file() and not path.is_symlink() and 0 < path.stat().st_size <= SOURCE_FILE_LIMITS.get(name, 256*1024),"delivery_source_file_bound")
        object_name = source+":"+name
        size = subprocess.check_output(["git","cat-file","-s",object_name],cwd=ROOT,timeout=30).strip()
        need(size.isdigit() and int(size) == path.stat().st_size,"delivery_committed_source_size_differs")
        committed = subprocess.check_output(["git","show",object_name],cwd=ROOT,timeout=30)
        digest = sha(path)
        need(len(committed) == int(size) and hashlib.sha256(committed).hexdigest() == digest,"delivery_committed_source_differs")
        result[name] = digest
    return result

def language_producer_source_pins():
    """Finite current writer/profile closure, never report-supplied paths."""
    result = {}
    for name in LANGUAGE_PRODUCER_SOURCES:
        path = ROOT / name
        need(path.is_file() and not path.is_symlink()
             and 0 < path.stat().st_size <= SOURCE_FILE_LIMITS.get(name, 256*1024),
             "language_producer_source_file_bound")
        result[name] = sha(path)
    return result


def validate_language_producer_report(report, source):
    need(type(source) is str and re.fullmatch(r"[0-9a-f]{40}", source)
         and type(report) is dict and report.get("source_commit") == source,
         "language_producer_commit_differs")
    pins = report.get("source_component_sha256")
    need(type(pins) is dict and set(pins) == set(LANGUAGE_PRODUCER_SOURCES),
         "language_producer_source_set_differs")
    expected = language_producer_source_pins()
    need(all(type(pins[name]) is str and re.fullmatch(r"[0-9a-f]{64}", pins[name])
             and pins[name] == expected[name] for name in LANGUAGE_PRODUCER_SOURCES),
         "language_producer_source_sha256_differs")



# Exact actual 23-object producer run, source 11f939c5 / Actions 43953232317.
# The legacy v2 pin remains immutable; only this finite v3 proof is deliverable.
LANGUAGE_MANIFEST_SHA256 = "5003fa1677b7b456d6c216da71d80a39190e786c1b5445e840a6da3a1f44eb32"
KOREAN_RESOURCES = {"bytes": 80641216,
    "sha256": "9b3f5bb680670f91d6c3e41c5968acf49d8b9484431d5dc4d9837c786f982020"}
KOREAN_GRAPH_CLASSES = {
    28: (418897, 418898, 418899, 418900, 418901, 418902, 418903, 418904, 418906, 418911),
    213: (542, 819, 875, 1007, 1029, 1076, 1161, 1342, 1344, 1576),
    224: (231861, 251370, 253735),
}
KOREAN_FIXED_TEXT = {
    "love_btn_achievement": 1344, "love_btn_fin": 1342, "love_btn_max": 1161,
    "love_btn_mission": 1029, "love_btn_playing": 819, "love_btn_present": 1007,
    "love_btn_setting": 1076, "love_btn_status": 875, "love_button_start": 542,
    "love_header_level_label": 1576,
}


def _canonical_sha(value):
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    except (TypeError, ValueError):
        raise DeliveryError("language_proof_json_invalid") from None
    return hashlib.sha256(raw).hexdigest()


def validate_language_manifest(language):
    path = HERE / "delivery-pins/client-languages-real-v3.manifest.json"
    need(path.is_file() and not path.is_symlink() and path.stat().st_size == 8674
         and sha(path) == LANGUAGE_MANIFEST_SHA256 and language == read(path),
         "language_manifest_pin_differs")
    # language_members is the producer's three-language count; the archive has
    # five overrides (JA/EN metadata + resources, and the refreshed KO resources).
    archived = {(code, name, row.get("member")) for code, rows in language["languages"].items()
                for name, row in rows.items() if row["source"] == "archive"}
    need(archived == {(code, name, code + "/" + name) for code in ("ja", "en")
             for name in ("Data/Managed/Metadata/global-metadata.dat", "Data/resources.assets")}
             | {("ko", "Data/resources.assets", "ko/Data/resources.assets")},
         "language_archive_member_set_differs")


def validate_refreshed_korean_resources(report, language):
    need(type(report) is dict and report.get("korean_resources_refreshed") is True
         and type(report.get("common_files")) is int and report["common_files"] == 44
         and type(report.get("language_members")) is int and report["language_members"] == 3,
         "korean_resources_refresh_missing")
    proofs = report.get("proofs")
    need(type(proofs) is dict and type(language) is dict, "korean_resources_proof_missing")
    proof = proofs.get("korean_resources")
    need(type(proof) is dict and proof.get("output") == KOREAN_RESOURCES
         and language.get("languages", {}).get("ko", {}).get("Data/resources.assets") ==
             {**KOREAN_RESOURCES, "source": "archive", "member": "ko/Data/resources.assets"},
         "korean_resources_output_differs")
    need(all(proof.get(key) is True for key in ("original_stock_rebuilt",
             "all_other_objects_byte_identical", "type_graph_and_external_references_unchanged"))
         and type(proof.get("unchanged_object_count")) is int
         and proof["unchanged_object_count"] == 418937, "korean_resources_graph_incomplete")
    differences = proof.get("declared_object_differences")
    need(type(differences) is list and len(differences) == 23
         and all(type(row) is dict and type(row.get("path_id")) is int
             and type(row.get("class_id")) is int and row.get("changed") is True
             and set(row) == {"path_id", "class_id", "before_sha256", "after_sha256", "changed"}
             and all(type(row.get(key)) is str and re.fullmatch(r"[0-9a-f]{64}", row[key])
                     for key in ("before_sha256", "after_sha256")) for row in differences),
         "korean_resources_graph_differs")
    graph = {row["path_id"]: row for row in differences}
    need(len(graph) == 23 and {key: tuple(sorted(row["path_id"] for row in differences
             if row["class_id"] == key)) for key in KOREAN_GRAPH_CLASSES} == KOREAN_GRAPH_CLASSES
         and _canonical_sha(sorted(differences, key=lambda row: row["path_id"])) ==
             "9b2c14c97048ae0e3ed05ef52c08ff4afd0d7d4ea1c3ea2be180e1222caa2511",
         "korean_resources_graph_differs")
    images = proof.get("static_images")
    need(type(images) is dict and images.get("schema") == 2
         and images.get("policy") == "korean-static-sprites-v2" and images.get("platform") == "ios"
         and images.get("fixed_text_layout_policy") == "original-rect-love-text-v1"
         and type(images.get("fixed_text_sprites")) is int and images["fixed_text_sprites"] == 10
         and type(images.get("translated_sprites")) is int and images["translated_sprites"] == 139
         and images.get("original_layout_preserved") is False
         and images.get("runtime_image_hooks") is False and images.get("atlas_pixels_modified") is False
         and images.get("original_sprite_IDs_preserved") is True
         and images.get("original_pivots_borders_pixels_per_unit_preserved") is True
         and images.get("texture_format") == "RGBA32" and images.get("lossy_recompression") is False,
         "korean_fixed_text_layout_differs")
    sprites = images.get("sprites")
    need(type(sprites) is list and len(sprites) == 139 and all(type(row) is dict
         and type(row.get("name")) is str and type(row.get("sprite_path_id")) is int for row in sprites)
         and len({row["sprite_path_id"] for row in sprites}) == 139,
         "korean_fixed_text_layout_differs")
    # Sprite names need not be unique: the proven iOS roster contains two Ka
    # objects. Bind the complete name/ID topology and require unique object IDs.
    roster = [{"name": row["name"], "sprite_path_id": row["sprite_path_id"]} for row in sprites]
    need(_canonical_sha(sorted(roster, key=lambda row: row["sprite_path_id"])) ==
         "c16dc3fe1374b16f30e6bea8ab19314ff16070df3a2593c34b9d3553edbb7385", "korean_fixed_text_layout_differs")
    fixed = [row for row in sprites if row.get("layout_policy") == "original-rect-love-text-v1"]
    need(len(fixed) == 10 and {row["name"]: row.get("sprite_path_id") for row in fixed} == KOREAN_FIXED_TEXT
         and all(row.get("readback_pixel_exact") is True
             and graph[row["sprite_path_id"]]["after_sha256"] == row.get("output_sha256")
             and row.get("private_texture_path_id") in KOREAN_GRAPH_CLASSES[28]
             and graph[row["private_texture_path_id"]]["after_sha256"] == row.get("texture_sha256")
             for row in fixed)
         and _canonical_sha(sorted(fixed, key=lambda row: row["name"])) ==
             "20986f9e392c20b5a3fc0e87a3c66ddac1a70acb249a85a9e8cd9a57c021f254",
         "korean_fixed_text_layout_differs")
    logo = images.get("logo_layout")
    need(type(logo) is dict and logo.get("policy") == "love-logo-whole-label-uniform-v1"
         and logo.get("platform") == "ios" and logo.get("uniform_scale") == 0.75
         and logo.get("original_frame") == [96.0, 32.0] and logo.get("content_size") == [94.5, 24.0]
         and logo.get("full_translated_glyphs_preserved") is True
         and logo.get("all_other_object_bytes_identical") is True,
         "korean_logo_layout_differs")
    transforms = logo.get("transforms")
    need(type(transforms) is list and len(transforms) == 3 and all(type(row) is dict
             and type(row.get("path_id")) is int and row["path_id"] in KOREAN_GRAPH_CLASSES[224]
             and type(row.get("class_id")) is int and row["class_id"] == 224
             and type(row.get("object_bytes")) is int and row["object_bytes"] == 108
             and row.get("only_position_and_size_changed") is True
             and graph[row["path_id"]]["before_sha256"] == row.get("input_sha256")
             and graph[row["path_id"]]["after_sha256"] == row.get("output_sha256") for row in transforms)
         and len({row["path_id"] for row in transforms}) == 3
         and _canonical_sha(logo) == "a47a9bb5fd670e17c4c1a9765be5a1bfa20344fd4a930441ae07bf60767eb910",
         "korean_logo_layout_differs")



def _startup_pin_json(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            need(key not in value, "startup_receipt_pin_invalid")
            value[key] = item
        return value
    need(type(raw) is bytes and 0 < len(raw) <= 4096, "startup_receipt_pin_invalid")
    try:
        pin = json.loads(raw, object_pairs_hook=pairs,
                         parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (TypeError, ValueError, UnicodeError):
        raise DeliveryError("startup_receipt_pin_invalid") from None
    need(type(pin) is dict and set(pin) == {"schema", "platform", "bytes", "sha256"}
         and type(pin["schema"]) is int and pin["schema"] == 1 and pin["platform"] == "ios"
         and type(pin["bytes"]) is int and 0 < pin["bytes"] <= 16*MIB
         and type(pin["sha256"]) is str and re.fullmatch(r"[0-9a-f]{64}", pin["sha256"]),
         "startup_receipt_pin_invalid")
    return pin


def verify_bundled_startup_receipt(archive, prefix, package_report, members, guard):
    """Require the current cohort's signed-app public receipt and actual bytes."""
    path = members / "startupTranslations.json"
    need(path.is_file() and not path.is_symlink() and 0 < path.stat().st_size <= 4096,
         "startup_receipt_public_pin_invalid")
    public_raw = path.read_bytes()
    pin = _startup_pin_json(public_raw)
    reported = package_report.get("startup_translations")
    need(type(reported) is dict and set(reported) == set(pin)
         and all(type(reported[key]) is type(value) and reported[key] == value
                 for key, value in pin.items()), "startup_receipt_report_differs")
    payloads = {}
    for relative, limit in (("LocalServer/startupTranslations.json", 4096),
                            ("LocalServer/startupTranslations.zip", 16*MIB)):
        name = prefix + relative
        entries = [item for item in archive.infolist() if item.filename == name]
        need(len(entries) == 1 and not entries[0].is_dir() and not entries[0].flag_bits & 1
             and stat.S_IFMT(entries[0].external_attr >> 16) in (0, stat.S_IFREG)
             and entries[0].compress_type in (ZIP_STORED, ZIP_DEFLATED)
             and 0 < entries[0].file_size <= limit, "startup_receipt_member_invalid")
        with archive.open(entries[0]) as incoming:
            chunks = []; count = 0; digest = hashlib.sha256()
            while block := incoming.read(CHUNK):
                guard.check(); count += len(block)
                need(count <= limit, "startup_receipt_member_invalid")
                digest.update(block); chunks.append(block)
        need(count == entries[0].file_size and package_report.get("member_sha256", {}).get(name) == digest.hexdigest(),
             "startup_receipt_member_sha256_differs")
        payloads[relative] = b"".join(chunks)
    need(payloads["LocalServer/startupTranslations.json"] == public_raw,
         "startup_receipt_public_pin_differs")
    raw = payloads["LocalServer/startupTranslations.zip"]
    need(len(raw) == pin["bytes"] and hashlib.sha256(raw).hexdigest() == pin["sha256"],
         "startup_receipt_archive_differs")
    verifier = load_module("delivery_startup_receipt", ROOT / "src/idoly_local/startup_receipt.py")
    result = verifier.inspect_startup_receipt(raw, expected_sha256=pin["sha256"],
                                            expected_bytes=pin["bytes"], platform="ios")
    need(type(result) is dict and type(result.get("schema")) is int and result["schema"] == 1
         and result.get("available") is True, "startup_receipt_envelope_invalid")
    # The envelope has already bounded the inner directory and index to 8192 bytes.
    # These finite public hash fields are sanity checks; each runtime lease still
    # verifies them against the actual original/legacy/current source bytes.
    import io
    with ZipFile(io.BytesIO(raw)) as receipt:
        need({row.filename for row in receipt.infolist()} == {"index.json", "ko/metadata.json",
             "ko/rebased.pb", "en/metadata.json", "en/rebased.pb"}, "startup_receipt_members_differ")
        index = json.loads(receipt.read("index.json"))
    need(type(index.get("schema")) is int and index["schema"] == 2,
         "startup_receipt_index_format_differs")
    for layer in index["layers"].values():
        is_sha = lambda value: type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value)
        need(type(layer) is dict and set(layer) == {"original_sha256", "legacy_sha256", "source_sha256"}
             and is_sha(layer["original_sha256"])
             and (layer["legacy_sha256"] is None or is_sha(layer["legacy_sha256"]))
             and type(layer["source_sha256"]) is list and len(layer["source_sha256"]) == 4
             and all(is_sha(value) for value in layer["source_sha256"][:3])
             and (layer["source_sha256"][3] is None or is_sha(layer["source_sha256"][3])),
             "startup_receipt_layer_binding_invalid")


def check_proof_budget(report_bytes, existing_generated_bytes):
    need(type(report_bytes) is int and report_bytes >= 0
         and type(existing_generated_bytes) is int and existing_generated_bytes >= 0
         and report_bytes+existing_generated_bytes+PROOF_GENERATED_RESERVE <= MAX_PROOF,
         "publication_proof_preflight_bound")

PROBE_SOURCES = ("probe/main.m","native/IdolyEmbeddedServer.h","native/IdolyOctoBudget.h",
                 "native/IdolyUnityHost.h","native/OctoBudgetPolicy.h",
                 "native/tests/OctoBudgetFixture.h","build_probe.py")

def validate_probe_build_sources(built):
    pins = built.get("source_sha256")
    need(type(pins) is dict and set(pins) == set(PROBE_SOURCES),"probe_source_set_differs")
    for name in PROBE_SOURCES:
        path = HERE/name
        need(path.is_file() and not path.is_symlink() and 0 < path.stat().st_size <= 256*1024
             and type(pins[name]) is str and re.fullmatch(r"[0-9a-f]{64}",pins[name])
             and sha(path) == pins[name],"probe_source_sha256_differs")

def verify_language_proofs(smoke, members, native, probe, language, descriptor):
    need(smoke["native_probe"]["server_status"]["unity_host"]["unity_window_bound"] is True,
         "unity_host_window_not_bound")
    need(smoke["native_probe"]["server_status"]["unity_host"]["sigpipe_ignored_before_server"] is True,
         "sigpipe_not_ignored_before_server")
    host = load_module("delivery_unity_host_native_test",HERE/"native/test_unity_host.py")
    report = small_json(members/"unity-host-native-test.json")
    host.validate_report(report,HERE/"native")
    for name in ("IdolyUnityHost.h","IdolyUnityHost.m","UnityHostPolicy.h","UnityHostProfile.h",
                 "IdolyClientData.h","IdolyClientData.m"):
        need(native["source_sha256"][name] == report["source_sha256"][name],"unity_host_native_source_differs")
    probe.validate_language_matrix_report(smoke["language_matrix"])
    need(all(row["unity_host"]["sigpipe_ignored_before_server"] is True
             for row in smoke["language_matrix"]["reports"]),"matrix_sigpipe_not_ignored_before_server")
    built = small_json(members/"probe-build.json")
    validate_probe_build_sources(built)
    copied = built.get("copied_input_sha256")
    need(type(copied) is dict and copied.get("LocalServer/client-languages.zip") == descriptor["sha256"]
         and copied.get("LocalServer/ServerData.zip") == _packaged_server_data_pin()["sha256"]
         and copied.get("LocalServer/payload-pin.json") == hashlib.sha256(_packaged_payload_pin_bytes()).hexdigest(),
         "probe_copied_language_inputs_differ")
    canaries = built.get("generated_language_canaries_sha256")
    need(type(canaries) is str and re.fullmatch(r"[0-9a-f]{64}",canaries),"generated_canary_digest_invalid")
    observations = [smoke["native_probe"]["unity_host_probe"],
                    *(row["unity_host_probe"] for row in smoke["language_matrix"]["reports"])]
    need(all(row.get("canary_source_sha256") == canaries for row in observations),"generated_canary_source_differs")
    per_language = [("ko",observations[0]),
                    *((row["language"],row["unity_host_probe"]) for row in smoke["language_matrix"]["reports"])]
    for selected,observation in per_language:
        for path in ("Data/resources.assets","Data/Managed/Metadata/global-metadata.dat"):
            expected = language["languages"][selected][path]
            row = observation["canaries"][path]
            need(row["expected_sha256"] == row["actual_sha256"] == expected["sha256"]
                 and type(row["expected_bytes"]) is int and row["expected_bytes"] == row["actual_bytes"] == expected["bytes"],
                 "known_language_canary_differs")

def verify_members(members, proof, source, run, artifact, guard):
    need(__debug__,"optimized_python_forbidden")
    SOURCE,RUN,ARTIFACT,STAGE = source,run,artifact,proof
    report=read(members/IPA.replace('.ipa','.report.json'));smoke=read(members/'simulator-smoke.json');runtime=read(members/'device-runtime-report.json');native=read(members/'device-native-build.json')
    verify_server_data_provenance(members,report)
    assert report['source_commit']==SOURCE and report['base_ipa_sha256']=='d872903da8d79bf4a255888f9d5a952198ff47268cfcf7c35e8ac437b56e72a1'
    assert report['original_SDK_members_unchanged'] is True and report['Unity_patch']['all_other_Unity_bytes_equal'] is True
    assert smoke['status']=='PASS' and smoke['fresh_local_state_before_launch'] is True and all(smoke['cleanup'][k] is True for k in ('shutdown','delete'))
    probe_spec=importlib.util.spec_from_file_location('delivery_launcher_probe',ROOT/'ios-unified/probe/smoke_probe.py')
    probe=importlib.util.module_from_spec(probe_spec);sys.modules[probe_spec.name]=probe;probe_spec.loader.exec_module(probe)
    probe.validate_report(smoke['native_probe'])
    probe.validate_account_management_after_relaunch(
        smoke.get('account_management_after_relaunch'),
        smoke['native_probe']['menu_lifetime'].get('account_management'))
    probe.validate_master_file_report(smoke['master_file'])
    probe.validate_sdk_resource_report(smoke['sdk_resource'])
    assert smoke['native_probe']['server_status']['keyboard_ready'] is True
    expected_keyboard_lifecycle={'installed':True,'strategy':'reuse-existing','initialize_calls':1,'original_initialize_calls':0,'reused_existing_calls':1}
    observed_keyboard_lifecycle=smoke['native_probe']['server_status']['keyboard_lifecycle']
    assert all(type(observed_keyboard_lifecycle.get(key)) is type(value) and observed_keyboard_lifecycle[key]==value for key,value in expected_keyboard_lifecycle.items())
    assert [r['path'] for r in smoke['rpcs']]==['/api.System/Check','/api.Auth/Login','/api.Home/Enter']
    assert all(r['grpc_status']==0 and r['request_encrypted'] is True and r['response_encrypted'] is True for r in smoke['rpcs'])
    assert native['codesign_strict_verified'] is True and native['MachO']['platform']==2 and native['smoke_probe_only'] is False
    mac=read(members/'mac-menu-test.json');assert mac['status']=='PASS' and mac['actual_macos_appkit_execution'] is True
    assert mac['checks']['shortcut_dispatch_verified'] is True and mac['checks']['target_action_dispatch'] is True
    assert mac['checks']['removed_item_reattachment'] is True and mac['checks']['main_menu_replacement'] is True
    for name,digest in mac['source_sha256'].items():assert sha(ROOT/'ios-unified/native'/name)==digest
    assert native['source_sha256']['IdolyMacMenu.m']==mac['source_sha256']['IdolyMacMenu.m']
    foundation=read(members/'client-data-native-test.json')
    assert foundation['status']=='PASS' and foundation['actual_macos_foundation_execution'] is True
    assert foundation['actual_iOS_Unity_execution'] is False and foundation['physical_PlayCover_execution'] is False
    assert len(foundation['runs'])==2
    foundation_checks=('actual_macos_foundation_execution','fixed_identifier_scope_verified','typed_unity_setter_verified','invalid_paths_and_metadata_rejected','symlinks_rejected','ancestor_alias_root_accepted','off_main_rejected','different_language_after_selection_rejected')
    for forced,result in zip((False,True),foundation['runs']):
     assert result['status']=='PASS' and result['forced_registration_failure'] is forced and all(result[k] is True for k in foundation_checks)
     selection=result['selection'];assert selection['selected'] is True and selection['language']=='ko' and selection['bundle_identifier']=='local.idoly.client-data'
     if forced:assert selection['fixed_identifier_fallback'] is True
    for name,digest in foundation['source_sha256'].items():assert sha(ROOT/'ios-unified/native'/name)==digest
    assert native['source_sha256']['IdolyClientData.m']==foundation['source_sha256']['IdolyClientData.m']
    keyboard_native=read(members/'keyboard-lifecycle-native-test.json')
    assert keyboard_native['status']=='PASS' and keyboard_native['actual_macos_foundation_execution'] is True
    assert keyboard_native['actual_iOS_Unity_execution'] is False and keyboard_native['physical_PlayCover_execution'] is False and keyboard_native['windows_or_simulators_created'] is False
    assert len(keyboard_native['runs'])==2
    keyboard_checks=('actual_macos_foundation_execution','cold_or_warm_path_verified','singleton_and_field_preserved','original_getter_unchanged','invalid_abi_rejected','off_main_install_rejected','idempotent_install_verified','changed_method_rejected','foreign_singleton_not_reused','other_receiver_not_reused','unrelated_exception_propagated','no_destroy_or_reset')
    for mode,result in zip(('cold','warm'),keyboard_native['runs']):
     assert result['status']=='PASS' and result['mode']==mode and all(result[key] is True for key in keyboard_checks)
     lifecycle=result['lifecycle'];expected={'installed':True,'strategy':'reuse-existing','initialize_calls':5,'original_initialize_calls':4 if mode=='cold' else 3,'reused_existing_calls':1 if mode=='cold' else 2}
     assert all(type(lifecycle.get(key)) is type(value) and lifecycle[key]==value for key,value in expected.items())
    for name,digest in keyboard_native['source_sha256'].items():assert sha(ROOT/'ios-unified/native'/name)==digest
    for name in ('IdolyKeyboardLifecycle.h','IdolyKeyboardLifecycle.m'):assert native['source_sha256'][name]==keyboard_native['source_sha256'][name]
    octo_budget_native=read(members/'octo-budget-native-test.json')
    octo_budget_spec=importlib.util.spec_from_file_location('delivery_octo_budget_native_test',ROOT/'ios-unified/native/test_octo_budget.py')
    octo_budget_test=importlib.util.module_from_spec(octo_budget_spec);sys.modules[octo_budget_spec.name]=octo_budget_test;octo_budget_spec.loader.exec_module(octo_budget_test)
    octo_budget_test.validate_report(octo_budget_native,ROOT/'ios-unified/native')
    for name in ('IdolyOctoBudget.h','IdolyOctoBudget.m','OctoBudgetPolicy.h','OctoBudgetProfile.h'):assert native['source_sha256'][name]==octo_budget_native['source_sha256'][name]
    local_http=read(members/'local-http-native-test.json')
    assert local_http['status']=='PASS' and local_http['actual_macos_foundation_execution'] is True
    assert local_http['actual_iOS_Unity_execution'] is False and local_http['physical_PlayCover_execution'] is False and local_http['windows_or_simulators_created'] is False
    assert all(local_http[key] is True for key in ('fixed_loopback_path_verified','redirects_not_followed','invalid_inputs_made_no_requests','body_and_deadline_bounded'))
    validation=local_http['validation'];assert validation['status']=='PASS' and all(validation[key] is True for key in ('actual_macos_foundation_execution','main_thread_rejected','invalid_ports_rejected','invalid_timeout_rejected'))
    # The timeout fixture intentionally sends no response bytes or headers before waiting.
    fixtures=(('json','none',200),('not_found','http_status',404),('invalid_json','invalid_json',200),('array','invalid_json',200),('oversized','response_too_large',200),('timeout','timeout',0),('redirect_not_followed','redirect',302),('closed_loopback_port','connection',0))
    assert len(local_http['runs'])==len(fixtures)
    readiness_keys={'schema','ok','transport','url','http_status','error_code','body_is_json','received_bytes','worker_main_thread','ns_error_domain','ns_error_code'}
    for (fixture,error_code,http_status),result in zip(fixtures,local_http['runs']):
     assert result['fixture']==fixture and result['status']=='PASS' and result['actual_macos_foundation_execution'] is True
     readiness=result['readiness'];assert set(readiness)==readiness_keys
     assert type(readiness['schema']) is int and readiness['schema']==1 and readiness['transport']=='NSURLSession' and readiness['worker_main_thread'] is False
     assert type(readiness['received_bytes']) is int and 0<=readiness['received_bytes']<=16384
     assert type(readiness['url']) is str and re.fullmatch(r'http://127\.0\.0\.1:[0-9]{1,5}/client/playback',readiness['url']) and 1<=int(readiness['url'].split(':')[2].split('/')[0])<=65535
     assert readiness['error_code']==error_code and type(readiness['http_status']) is int and readiness['http_status']==http_status
     assert readiness['ok'] is (fixture=='json') and readiness['body_is_json'] is (fixture=='json')
     assert readiness['ns_error_domain'] is None or readiness['ns_error_domain'] in ('NSURLErrorDomain','NSPOSIXErrorDomain','NSCocoaErrorDomain','NSOSStatusErrorDomain','Other')
     assert readiness['ns_error_code'] is None or type(readiness['ns_error_code']) is int
     assert type(result['elapsed_seconds']) in (int,float) and math.isfinite(result['elapsed_seconds']) and 0<=result['elapsed_seconds']<=(3 if fixture=='timeout' else 4)
    for name,digest in local_http['source_sha256'].items():assert sha(ROOT/'ios-unified/native'/name)==digest
    for name in ('IdolyLocalHTTP.h','IdolyLocalHTTP.m'):assert native['source_sha256'][name]==local_http['source_sha256'][name]
    language_build=read(members/'client-languages-build.json');language_runtime=read(members/'client-language-runtime-check.json')
    validate_language_producer_report(language_build, SOURCE)
    descriptor=read(members/'client-languages.json')
    assert set(descriptor)=={'schema','bytes','sha256'} and type(descriptor['schema']) is int and descriptor['schema']==1
    assert type(descriptor['bytes']) is int and 0<descriptor['bytes']<=128*MIB
    assert type(descriptor['sha256']) is str and len(descriptor['sha256'])==64 and all(c in '0123456789abcdef' for c in descriptor['sha256'])
    source_pins={'stock_ipa_sha256':'33197938a0990b267af2d67c09e9d1123694e28695fc39d9650ca4f6aa661848','base_ipa_sha256':'d872903da8d79bf4a255888f9d5a952198ff47268cfcf7c35e8ac437b56e72a1','english_ui_sha256':'b30f48cdcbc0ddfc267a0a7d265ec717a7057342bdc55c9f0d16fe3ea06fc702'}
    assert read(members/'client-languages.json')==descriptor and language_build['package']==descriptor and report['client_languages']['descriptor']==descriptor
    language=report['client_languages']['manifest'];assert language==language_build['manifest'] and language['source']==source_pins and language_build['source']==source_pins
    validate_language_manifest(language)
    validate_refreshed_korean_resources(language_build, language)
    language_spec=importlib.util.spec_from_file_location('delivery_client_data',ROOT/'src/idoly_local/ios_client_data.py')
    language_module=importlib.util.module_from_spec(language_spec);sys.modules[language_spec.name]=language_module;language_spec.loader.exec_module(language_module)
    language_module.validate_manifest(language)
    verify_language_proofs(smoke,members,native,probe,language,descriptor)
    assert language_build['signed_app_modified_at_runtime'] is False and language_build['runtime_string_translation'] is False
    assert language_build['common_files']==44 and language_build['language_members']==3 and set(language['languages'])=={'ja','ko','en'}
    english_proof=read(ROOT/'ios-unified/client-language-inputs/en-report.json')
    assert sha(ROOT/'ios-unified/client-language-inputs/en.csv')==source_pins['english_ui_sha256'] and english_proof['missing_keys']==17
    assert language_build['proofs']['english_resources']['ui_translation']==english_proof
    assert language_runtime['status']=='PASS' and language_runtime['execution']=='offline_client_data_reconstruction' and language_runtime['source']==source_pins
    assert language_runtime['all_source_and_output_hashes_verified_by_runtime'] is True and language_runtime['signed_app_modified'] is False
    assert language_runtime['Unity_executed'] is False and language_runtime['physical_PlayCover_execution'] is False
    assert len(language_runtime['languages'])==3 and {row['language'] for row in language_runtime['languages']}=={'ja','ko','en'}
    for row in language_runtime['languages']:
     assert row['first_reused'] is False and row['second_reused'] is True and row['resource_only_bundle'] is True
     assert row['bundle_id']=='local.idoly.client-data' and row['files']==len(language['common'])+len(language['languages'][row['language']])==46
    runtime_inputs=read(ROOT/'ios-unified/runtime_inputs.json')
    assert set(runtime['source_sha256'])==set(runtime_inputs['project_modules']) and 'idoly_local.ios_client_data' in runtime['source_sha256']
    assert not any('AppKit.framework' in name for name in native['MachO']['dependencies'])
    for name,digest in native['source_sha256'].items():assert sha(ROOT/'ios-unified/native'/name)==digest
    for module,digest in runtime['source_sha256'].items():
     p=ROOT/'src'/Path(*module.split('.'))
     p=p/'__init__.py' if module=='idoly_local' else p.with_suffix('.py')
     assert sha(p)==digest
    prefix='Payload/IDOLY PRIDE.app/'
    for rel,wanted in [('LocalServer/ServerData.zip',_packaged_server_data_pin()['sha256']),('LocalServer/bundledTranslations.zip',runtime_inputs['inputs']['translations']['sha256']),('Frameworks/IdolyPresentation.dylib','85a445f71ac59473522aa15e15919efbc351cbbc9d2d5829062a9a22416c9cb5')]:assert report['member_sha256'][prefix+rel]==wanted
    assert report['member_sha256'][prefix+'Frameworks/IdolyEmbeddedServer.framework/IdolyEmbeddedServer']==native['post_sign_binary_sha256']
    assert report['member_sha256'][prefix+'LocalServer/client-languages.zip']==descriptor['sha256']
    assert report['original_members_preserved_except_Unity_header_and_Info'] is True
    for name,digest in report['original_member_sha256'].items():
     if name not in (prefix+'Info.plist',prefix+'Frameworks/UnityFramework.framework/UnityFramework'):assert report['member_sha256'][name]==digest
    assert report['member_sha256'][prefix+'Data/globalgamemanagers']=='1c49cb988699c2344f0c1e186ad8cd1ba59984fe200cf243a7c524d07ba1644c'
    path=members/IPA;identity=file_identity(path.lstat())
    import plistlib
    from zipfile import ZipFile
    with ZipFile(path) as z:
     app_info=plistlib.loads(z.read(prefix+'Info.plist'))
     assert app_info['CFBundleVersion']=='156.9117'
     assert app_info['IdolyUnifiedLoopbackOrigin']=='http://127.0.0.1:8080'
     assert json.loads(z.read(prefix+'LocalServer/client-languages.json'))==descriptor
     verify_bundled_payload_pin(z,prefix,report)
     verify_bundled_startup_receipt(z,prefix,report,members,guard)
     zipped=z.getinfo(prefix+'LocalServer/client-languages.zip');assert zipped.file_size==descriptor['bytes']
     with z.open(zipped) as incoming:
      digest=hashlib.sha256()
      while block:=incoming.read(128*1024):guard.check();digest.update(block)
      assert digest.hexdigest()==descriptor['sha256']
    manifest={'schema':1,'source_commit':SOURCE,'artifacts':[{'path':str(path),'name':IPA,'bytes':report['output_bytes'],'sha256':report['output_sha256']}], 'validation':{'Actions_run':RUN,'Simulator_core':'PASS','physical_gameplay':'NOT_TESTED','PlayCover':'NOT_TESTED'}}
    (STAGE/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    (STAGE/'README.md').write_text('아이프라 통합 IPA 내부 검증 빌드 (156.9117)\n\n공개 릴리즈가 아닙니다. 서버 설정·계정 관리와 관련 게임 API를 구현하고 검증하는 소스의 빌드입니다.\n\n일본어·한국어·영어 게임 데이터를 선택하고 서버 준비 후 게임 시작을 누릅니다. 서버 화면 언어는 즉시 적용하며 게임 시작 뒤 바꾼 언어와 계정은 앱을 완전히 종료·재실행해 적용합니다. 개인 서명이 필요합니다. 게임 중 오른쪽 위 128×128 안전 영역을 2초 누르거나 Mac의 로컬 서버 설정… / ⌘⇧,로 메뉴를 엽니다.\n\n실제 시작 검사와 이전 실행의 실패 기록, 일반·감상 계정 목록·생성·복제·다음 시작 선택, 계정 ZIP 내보내기·미리보기·가져오기·자동 복구 지점을 제공합니다. 복제는 게임 내 ID를 보존하는 같은 계정의 저장 분기입니다. 계정 ZIP은 Love 진행을 포함한 8개 계정 테이블을 보존하며 로그인 세션·리소스·앱 전역 설정은 포함하지 않습니다. 계정 ZIP과 리소스 ZIP은 별개입니다. 미리보기 뒤 자료가 바뀌면 덮어쓰기를 중단합니다.\n\n기존 설정 자동 저장, 게임 시작 전 저장 대기, 리소스 ZIP 사본·진행 표시, 언어 Data 캐시·SIGPIPE 처리·그래픽/촬영 설정을 유지합니다. LiveContainer는 Fix File Picker 설정도 확인합니다.\n\n선택된 로컬 계정 조회와 미등록 생일 등록 외에 모시코이 Love API 17개를 연결합니다. 서버 설정에서 이벤트와 로컬 기간을 선택하며, 일반·감상 진행을 분리하고 감상에서는 스토리 비용을 건너뜁니다. 기존 한국어·영어 번역을 적용합니다. 원본 미확보 유우 분기 한 개와 별도 미션 보상은 지원하지 않습니다. 일본판 인계 ID·인계 비밀번호의 확인·다운로드·로컬 저장 흐름도 제공하지만 실제 공식 계정 인증은 검증하지 않았습니다. Firebase 가입·삭제·재가입이나 생일 이벤트·외부 보상 복구로 표시하지 않습니다.\n\n실제 Apple SDK 및 동일 Simulator KO→EN→JA→EN→KO 다섯 재실행 검사를 유지합니다. 계정 검사는 검사용 고정 자료와 실제 저장소의 바이트·세션·백업·복구 흐름을 대조합니다. Simulator Unity 진입점은 검사용이며 실제 게임 렌더링·전체 콘텐츠 플레이를 확인한 것이 아닙니다. 실제 PlayCover·iPhone·iPad 및 LiveContainer·SideStore Files 공급자의 기기 검사는 별도입니다.\n')
    return manifest,identity

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        return None

OPENER = build_opener(NoRedirect())

class Guard:
    """A remote runner uses its own OOM baseline, never another host's count."""
    def __init__(self):
        self.samples = 0
        self.minimum_headroom = None
        self.minimum_disk = None
        self.oom_baseline = None
        self.check(1024*MIB)
        need(shutil.disk_usage(os.environ["RUNNER_TEMP"]).free >= 3*1024*MIB,"remote_disk_entry_floor")

    def check(self, floor=512*MIB):
        root = Path("/sys/fs/cgroup")
        maximum = (root/"memory.max").read_text().strip() if (root/"memory.max").is_file() else "max"
        if maximum.isdigit():
            headroom = int(maximum)-int((root/"memory.current").read_text())
        else:
            memory = dict(line.split(":",1) for line in Path("/proc/meminfo").read_text().splitlines())
            headroom = int(memory["MemAvailable"].split()[0])*1024
        if (root/"memory.events").is_file():
            events = dict(line.split() for line in (root/"memory.events").read_text().splitlines())
            observed = int(events["oom_kill"])
            if self.oom_baseline is None:self.oom_baseline = observed
            need(observed == self.oom_baseline,"remote_oom_baseline_changed")
        free = shutil.disk_usage(os.environ["RUNNER_TEMP"]).free
        need(headroom >= floor,"remote_memory_floor")
        need(free >= 150*MIB,"remote_disk_floor")
        self.samples += 1
        self.minimum_headroom = headroom if self.minimum_headroom is None else min(headroom,self.minimum_headroom)
        self.minimum_disk = free if self.minimum_disk is None else min(free,self.minimum_disk)

    def report(self):
        return {"entry_floor_bytes":1024*MIB,"ongoing_floor_bytes":512*MIB,
                "root_floor_bytes":150*MIB,"oom_kill_baseline":self.oom_baseline,
                "minimum_headroom":self.minimum_headroom,"minimum_disk":self.minimum_disk,"samples":self.samples}

def api(path, token):
    request = Request("https://api.github.com/repos/"+REPO+path,headers={
        "Authorization":"Bearer "+token,"Accept":"application/vnd.github+json",
        "X-GitHub-Api-Version":"2022-11-28","User-Agent":"idoly-verified-ios-delivery"})
    with OPENER.open(request,timeout=30) as response:
        raw = response.read(2*MIB+1)
        need(response.status == 200 and len(raw) <= 2*MIB,"artifact_api_bound")
    value = json.loads(raw)
    need(type(value) is dict,"artifact_api_object")
    return value

def artifact_metadata(source, run, artifact, expected_digest, token):
    result = api("/actions/artifacts/"+str(artifact),token)
    build = api("/actions/runs/"+str(run),token)
    jobs = api("/actions/runs/"+str(run)+"/jobs?filter=latest&per_page=100",token)
    need(build.get("id") == run and build.get("head_sha") == source
         and build.get("event") == "workflow_dispatch"
         and build.get("repository",{}).get("full_name") == REPO,"run_source_binding")
    matches = [job for job in jobs.get("jobs",[]) if job.get("name") == "ios-unified"]
    need(len(matches) == 1 and matches[0].get("conclusion") == "success","ios_build_job_not_passed")
    need(type(result.get("id")) is int and result["id"] == artifact
         and result.get("name") == "ios-unified-prototype-"+source and result.get("expired") is False
         and result.get("workflow_run",{}).get("id") == run
         and result.get("workflow_run",{}).get("head_sha") == source,"artifact_source_binding")
    digest = result.get("digest")
    need(type(digest) is str and re.fullmatch(r"sha256:[0-9a-f]{64}",digest)
         and digest == "sha256:"+expected_digest,"artifact_api_sha256_required")
    size = result.get("size_in_bytes")
    need(type(size) is int and 0 < size <= MAX_ARCHIVE,"archive_size_bound")
    return {"source_commit":source,"run_id":run,"artifact_id":artifact,
            "archive_bytes":size,"archive_sha256":expected_digest}

def archive_url(artifact, token):
    request = Request("https://api.github.com/repos/"+REPO+"/actions/artifacts/"+str(artifact)+"/zip",
        headers={"Authorization":"Bearer "+token,"Accept":"application/vnd.github+json",
                 "User-Agent":"idoly-verified-ios-delivery"})
    try:
        response = OPENER.open(request,timeout=30)
    except HTTPError as error:
        need(error.code == 302,"archive_api_redirect_required")
        target = error.headers.get("Location")
        error.close()
    else:
        response.close()
        raise DeliveryError("archive_api_redirect_required")
    need(type(target) is str and 0 < len(target) <= 16000,"invalid_archive_url")
    parsed = urlsplit(target)
    host = parsed.hostname or ""
    need(parsed.scheme == "https" and parsed.port in (None,443) and not parsed.username
         and not parsed.password and not parsed.fragment
         and (host.endswith(".blob.core.windows.net") or host.endswith(".actions.githubusercontent.com")
              or host in {"github-cloud.githubusercontent.com","objects.githubusercontent.com","release-assets.githubusercontent.com"}),
         "unapproved_archive_origin")
    return target

def fetch_archive(metadata, token, destination, guard):
    download_verified_url(metadata,archive_url(metadata["artifact_id"],token),destination,guard)

def download_verified_url(metadata, target, destination, guard, *, allow_file_reference=False):
    need(type(target) is str and 0 < len(target) <= 16000,"invalid_archive_url")
    parsed = urlsplit(target)
    host = parsed.hostname or ""
    need(type(allow_file_reference) is bool,"invalid_file_reference_mode")
    if allow_file_reference:
        need(type(metadata.get("archive_bytes")) is int and 0 < metadata["archive_bytes"] <= MAX_PROOF+MIB
             and type(metadata.get("archive_sha256")) is str and re.fullmatch(r"[0-9a-f]{64}",metadata["archive_sha256"]),
             "file_reference_proof_bound")
    approved = (host.endswith(".blob.core.windows.net") or host.endswith(".actions.githubusercontent.com")
                or host in {"github-cloud.githubusercontent.com","objects.githubusercontent.com","release-assets.githubusercontent.com"})
    file_reference = (allow_file_reference and host.endswith(".oaiusercontent.com")
                      and re.fullmatch(r"/files/[A-Za-z0-9_-]{1,256}/raw",parsed.path))
    need(parsed.scheme == "https" and parsed.port in (None,443) and not parsed.username
         and not parsed.password and not parsed.fragment and (approved or file_reference),
         "unapproved_archive_origin")
    request = Request(target,headers={"Accept-Encoding":"identity","User-Agent":"idoly-verified-ios-delivery"})
    digest,count = hashlib.sha256(),0
    with OPENER.open(request,timeout=60) as response, destination.open("xb") as outgoing:
        need(response.status == 200 and response.headers.get("Content-Encoding", "identity") == "identity","archive_http_failed")
        while True:
            guard.check()
            block = response.read(CHUNK)
            if not block:break
            count += len(block)
            need(count <= metadata["archive_bytes"],"archive_extent_exceeded")
            digest.update(block)
            need(outgoing.write(block) == len(block),"archive_short_write")
        outgoing.flush();os.fsync(outgoing.fileno())
    target = None
    need(count == metadata["archive_bytes"] and digest.hexdigest() == metadata["archive_sha256"],"whole_archive_api_sha256_differs")

def extract_archive(archive_path, output, metadata, guard):
    inventory = {}
    with ZipFile(archive_path) as archive:
        files = selected_members(archive)
        for name in sorted(files):
            if name != IPA:inventory[name] = extract_member(archive,files[name],output,guard)
        report = small_json(output/PACKAGE_REPORT)
        wanted = report.get("output_sha256")
        need(type(wanted) is str and re.fullmatch(r"[0-9a-f]{64}",wanted)
             and report.get("source_commit") == metadata["source_commit"]
             and report.get("runtime_target") == "device"
             and type(report.get("output_bytes")) is int and report["output_bytes"] == files[IPA].file_size,
             "package_report_binding_differs")
        need((output/"SHA256SUMS").read_text() == wanted+"  "+IPA+"\n","checksum_file_differs")
        inventory[IPA] = extract_member(archive,files[IPA],output,guard,expected_sha=wanted)
    return inventory

def publish(manifest, readme, branch, proof, guard):
    env = {key:value for key,value in os.environ.items()
           if key not in ("GH_DEBUG","GIT_CURL_VERBOSE") and not key.startswith("GIT_TRACE")}
    token = env["GH_TOKEN"]
    remote = "https://github.com/"+REPO+".git"
    number = int(env.get("GIT_CONFIG_COUNT","0"))
    env["GIT_CONFIG_COUNT"] = str(number+1)
    env["GIT_CONFIG_KEY_"+str(number)] = "http."+remote+".extraheader"
    env["GIT_CONFIG_VALUE_"+str(number)] = "Authorization: Basic "+base64.b64encode(("x-access-token:"+token).encode()).decode()
    env.update(GIT_AUTHOR_NAME="github-actions[bot]",GIT_COMMITTER_NAME="github-actions[bot]",
               GIT_AUTHOR_EMAIL="41898282+github-actions[bot]@users.noreply.github.com",
               GIT_COMMITTER_EMAIL="41898282+github-actions[bot]@users.noreply.github.com")
    with (proof/"publish.log").open("xb") as log:
        child = subprocess.Popen([sys.executable,"-B",str(ROOT/"tools/publish_binary_bundle_lfs.py"),
            "--manifest",str(manifest),"--readme",str(readme),"--branch",branch,"--evidence",str(proof/"publication")],
            cwd=ROOT,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT)
        try:
            while child.poll() is None:guard.check();time.sleep(.5)
            need(child.returncode == 0,"publication_failed")
        except BaseException:
            if child.poll() is None:child.terminate();child.wait(timeout=10)
            raise
    result = small_json(proof/"publication/publication.json")
    need(result.get("published") is True and result.get("source_commit") == json.loads(manifest.read_text())["source_commit"],"publication_binding_differs")
    return result

def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-commit",required=True)
    parser.add_argument("--run-id",required=True,type=int)
    parser.add_argument("--artifact-id",required=True,type=int)
    parser.add_argument("--artifact-sha256",required=True)
    parser.add_argument("--work",required=True,type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--publish",action="store_true")
    mode.add_argument("--fetch-proof",action="store_true")
    args = parser.parse_args()
    if args.fetch_proof:
        try:
            return fetch_proof(args)
        except BaseException:
            raise SystemExit("Proof fetch stopped; no signed URL or credentials logged") from None
    need(os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("GITHUB_REPOSITORY") == REPO,"remote_github_runner_required")
    need(re.fullmatch(r"[0-9a-f]{40}",args.source_commit) and args.source_commit == os.environ.get("GITHUB_SHA")
         and args.run_id > 0 and args.artifact_id > 0 and str(args.run_id) == os.environ.get("GITHUB_RUN_ID")
         and re.fullmatch(r"[0-9a-f]{64}",args.artifact_sha256),"source_run_arguments_invalid")
    need(subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip() == args.source_commit,"checkout_source_differs")
    runner = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)
    work = args.work.absolute()
    need(work.parent.resolve(strict=True) == runner and not work.exists() and not work.is_symlink(),"fresh_owned_runner_work_required")
    guard = Guard()
    source_pins = delivery_source_pins(args.source_commit)
    work.mkdir(mode=0o700)
    proof = work/"proof";proof.mkdir(mode=0o700)
    members = work/"members";members.mkdir(mode=0o700)
    state = {"schema":1,"status":"RUNNING","source_commit":args.source_commit,"run_id":args.run_id,"artifact_id":args.artifact_id,"version":"156.9117","source_sha256":source_pins}
    def save():
        (proof/"delivery-proof.json").write_text(json.dumps(state,indent=2)+"\n")
    save()
    try:
        token = os.environ["GH_TOKEN"]
        metadata = artifact_metadata(args.source_commit,args.run_id,args.artifact_id,args.artifact_sha256,token)
        archive = work/"artifact.zip"
        fetch_archive(metadata,token,archive,guard)
        inventory = extract_archive(archive,members,metadata,guard)
        archive.unlink()
        manifest,owned = verify_members(members,proof,args.source_commit,args.run_id,args.artifact_id,guard)
        reports = [path for path in members.iterdir() if path.name != IPA]
        for path in reports:
            need(path.is_file() and not path.is_symlink() and path.stat().st_size <= MAX_SMALL
                 and path.name.casefold() not in {name.casefold() for name in RESERVED_PROOF_NAMES},"proof_member_invalid")
        check_proof_budget(sum(path.stat().st_size for path in reports),
                           sum(path.stat().st_size for path in proof.rglob("*") if path.is_file()))
        for path in reports:
            destination = proof/path.name
            need(not destination.exists() and not destination.is_symlink(),"proof_destination_exists")
            with path.open("rb") as incoming, destination.open("xb") as outgoing:
                shutil.copyfileobj(incoming,outgoing,CHUNK)
        state.update(status="QA_PASS",archive=metadata,ipa=manifest["artifacts"][0],all_prior_and_language_gates=True,
                     whole_archive_API_digest_verified=True)
        save()
        branch = "downloads/ios-unified-prototype-source-"+args.source_commit
        result = publish(proof/"manifest.json",proof/"README.md",branch,proof,guard)
        receipt = result["artifacts"][0]
        need(len(result["artifacts"]) == 1 and receipt.get("complete_download_verified") is True
             and receipt.get("sha256") == manifest["artifacts"][0]["sha256"]
             and receipt.get("bytes") == manifest["artifacts"][0]["bytes"],"full_remote_ipa_sha256_not_verified")
        ipa = members/IPA
        need(file_identity(ipa.lstat()) == owned,"owned_ipa_identity_changed")
        ipa.unlink()
        state.update(status="PASS_DELIVERED",branch=branch,publication_commit=result["commit"],
            download_url="https://github.com/"+REPO+"/raw/"+result["commit"]+"/"+IPA,
            retired_only_owned_verified_public_IPA=True,full_remote_download_SHA256_verified=True,resources=guard.report(),
            report_files={name:value for name,value in inventory.items() if name != IPA})
        state["ipa"] = {key:value for key,value in state["ipa"].items() if key != "path"}
        save()
        total = sum(path.stat().st_size for path in proof.rglob("*") if path.is_file())
        need(total <= MAX_PROOF,"publication_proof_bundle_bound")
        print(json.dumps({key:state[key] for key in ("status","source_commit","branch","publication_commit","download_url","ipa")}))
    except BaseException as error:
        state.update(status="FAIL",error_type=type(error).__name__,resources=guard.report())
        if isinstance(error,DeliveryError):state["error_code"] = str(error)
        save()
        raise SystemExit("Delivery stopped; sanitized proof saved") from None


def selected_members(archive):
    entries = archive.infolist()
    need(0 < len(entries) <= 128 and len({i.filename for i in entries}) == len(entries), "zip_inventory_bound_or_duplicate")
    files = {}
    metadata = 0
    for item in entries:
        name = item.filename.rstrip("/")
        path = PurePosixPath(name)
        need(item.orig_filename == item.filename and name and not path.is_absolute() and ".." not in path.parts and "\\" not in name
             and "\0" not in name and str(path) == name and len(name) <= 256, "unsafe_zip_name")
        mode = item.external_attr >> 16 & 0o170000
        need(mode in (0, stat.S_IFREG, stat.S_IFDIR) and not item.flag_bits & 1, "zip_link_or_encryption_rejected")
        if item.is_dir():
            continue
        base = path.name
        need(base.casefold() not in {name.casefold() for name in RESERVED_PROOF_NAMES},"reserved_proof_member")
        need(re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", base) and base not in files, "zip_basename_differs_or_duplicate")
        need(item.compress_type in (ZIP_STORED, ZIP_DEFLATED), "unsupported_zip_compression")
        if base == IPA:
            need(0 < item.file_size <= MAX_IPA, "ipa_member_size_bound")
        else:
            need(base.endswith(".json") or base in ("SHA256SUMS", "README.txt"), "unexpected_artifact_member")
            need(0 < item.file_size <= MAX_SMALL, "small_member_size_bound")
            metadata += item.file_size
            need(metadata <= MAX_METADATA, "metadata_total_bound")
        files[base] = item
    need({IPA, PACKAGE_REPORT, "SHA256SUMS", "README.txt", "simulator-smoke.json", "keyboard-lifecycle-native-test.json", "local-http-native-test.json", "octo-budget-native-test.json", "unity-host-native-test.json", "probe-build.json", "server-data-upgrade.json", "server-data-korean-refresh.json", "startupTranslations.json"} <= files.keys(), "required_artifact_members_missing")
    return files


def extract_member(archive, item, output, guard, *, expected_sha=None):
    target = output / PurePosixPath(item.filename).name
    partial = target.with_name(target.name + ".partial")
    need(not target.exists() and not target.is_symlink() and not partial.exists(), "fresh_member_output_required")
    descriptor = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    owned = os.fstat(descriptor)
    digest = hashlib.sha256()
    count, crc = 0, 0
    try:
        with os.fdopen(descriptor, "wb") as outgoing, archive.open(item) as incoming:
            while True:
                guard.check()
                raw = incoming.read(CHUNK)
                if not raw:
                    break
                count += len(raw)
                need(count <= item.file_size, "member_extent_exceeded")
                digest.update(raw); crc = zlib.crc32(raw, crc)
                need(outgoing.write(raw) == len(raw), "short_member_write")
                guard.check()
            outgoing.flush(); os.fsync(outgoing.fileno())
        need(count == item.file_size and crc & 0xFFFFFFFF == item.CRC, "member_crc_or_size_differs")
        need(expected_sha is None or digest.hexdigest() == expected_sha, "member_sha256_differs")
        guard.check()
        need(not target.exists() and not target.is_symlink(), "member_destination_changed")
        os.link(partial, target)  # Atomic no-overwrite publication in owned RAM.
        partial.unlink()
        return {"bytes": count, "sha256": digest.hexdigest(), "CRC32": f"{crc & 0xffffffff:08x}"}
    except BaseException:
        try:
            current = partial.lstat()
            if (current.st_dev, current.st_ino) == (owned.st_dev, owned.st_ino):
                partial.unlink()
        except FileNotFoundError:
            pass
        raise


def small_json(path, maximum=MAX_SMALL):
    path = Path(path)
    info = path.lstat()
    need(stat.S_ISREG(info.st_mode) and 0 < info.st_size <= maximum,"json_file_bound")
    with path.open("rb") as incoming:raw = incoming.read(maximum+1)
    need(len(raw) == info.st_size,"json_file_bound")
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError):
        raise DeliveryError("json_file_invalid") from None
    need(type(value) is dict, "json_object_required")
    return value




class TinyProofGuard:
    """Read only a bounded metadata archive in the shared Linux tiny tier."""
    def __init__(self):
        self.check(96*MIB)
    def check(self,floor=64*MIB):
        import resource
        root = Path("/sys/fs/cgroup")
        maximum = (root/"memory.max").read_text().strip()
        need(maximum.isdigit(),"finite_local_cgroup_required")
        events = dict(line.split() for line in (root/"memory.events").read_text().splitlines())
        memory = dict(line.split() for line in (root/"memory.stat").read_text().splitlines())
        need(int(maximum)-int((root/"memory.current").read_text()) >= floor,"local_tiny_memory_floor")
        need(int(memory["inactive_file"]) >= 1024*MIB,"local_inactive_file_floor")
        need(int(events["oom_kill"]) == 2,"local_oom_baseline_changed")
        need(shutil.disk_usage("/").free >= 150*MIB,"local_root_disk_floor")
        need(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss <= 40*1024,"local_tiny_rss_floor")

def selected_proof_members(archive):
    entries = archive.infolist()
    need(0 < len(entries) <= 128 and len({item.filename for item in entries}) == len(entries),"proof_inventory_invalid")
    files,total = {},0
    for item in entries:
        name = item.filename.rstrip("/")
        path = PurePosixPath(name)
        need(item.orig_filename == item.filename and name and not path.is_absolute()
             and ".." not in path.parts and "\\" not in name and "\0" not in name
             and str(path) == name and len(name) <= 256,"unsafe_proof_name")
        mode = item.external_attr >> 16 & 0o170000
        need(mode in (0,stat.S_IFREG,stat.S_IFDIR) and not item.flag_bits & 1,"proof_link_or_encryption")
        if item.is_dir():continue
        base = path.name
        need(re.fullmatch(r"[A-Za-z0-9_.-]{1,128}",base) and base not in files
             and (base.endswith(".json") or base in ("README.md","README.txt","SHA256SUMS","publish.log")),"unexpected_proof_member")
        need(item.compress_type in (ZIP_STORED,ZIP_DEFLATED) and 0 < item.file_size <= MAX_PROOF,"proof_member_bound")
        total += item.file_size
        need(total <= MAX_PROOF,"proof_total_bound")
        files[base] = item
    need({"delivery-proof.json","publication.json","manifest.json",PACKAGE_REPORT} <= files.keys(),"proof_required_members_missing")
    return files

def fetch_proof(args):
    # Reviewed API metadata and a signed URL arrive only on stdin, never argv.
    need(re.fullmatch(r"[0-9a-f]{40}",args.source_commit) and args.run_id > 0 and args.artifact_id > 0
         and re.fullmatch(r"[0-9a-f]{64}",args.artifact_sha256),"proof_arguments_invalid")
    guard = TinyProofGuard()
    need(sys.platform.startswith("linux"),"linux_tiny_proof_host_required")
    owned = Path("/dev/shm/idoly-ios-unified-work").resolve(strict=True)
    work = args.work.absolute()
    need(work.parent.resolve(strict=True) == owned and not work.exists() and not work.is_symlink(),"fresh_owned_proof_work_required")
    source_pins = delivery_source_pins(args.source_commit)
    raw = sys.stdin.readline(65537)
    need(len(raw) <= 65536,"proof_handoff_bound")
    handoff = json.loads(raw)
    raw = None
    need(type(handoff) is dict and set(handoff) == {"artifact","url"},"proof_handoff_invalid")
    artifact = handoff["artifact"]
    need(type(artifact) is dict and type(artifact.get("id")) is int and artifact["id"] == args.artifact_id
         and artifact.get("name") == "ios-unified-publication-proof-"+args.source_commit
         and artifact.get("expired") is False and artifact.get("workflow_run",{}).get("id") == args.run_id
         and artifact.get("workflow_run",{}).get("head_sha") == args.source_commit
         and artifact.get("digest") == "sha256:"+args.artifact_sha256
         and type(artifact.get("size_in_bytes")) is int and 0 < artifact["size_in_bytes"] <= MAX_PROOF+MIB,
         "proof_api_binding_differs")
    metadata = {"archive_bytes":artifact["size_in_bytes"],"archive_sha256":args.artifact_sha256}
    work.mkdir(mode=0o700)
    archive = work/"proof.zip"
    download_verified_url(metadata,handoff["url"],archive,guard,allow_file_reference=True)
    handoff = None
    with ZipFile(archive) as incoming:
        for item in selected_proof_members(incoming).values():extract_member(incoming,item,work,guard)
    archive.unlink()
    proof = small_json(work/"delivery-proof.json",128*1024)
    publication = small_json(work/"publication.json",64*1024)
    manifest = small_json(work/"manifest.json",64*1024)
    records = proof.get("report_files")
    raw_files = {path.name:path for path in work.iterdir() if path.name not in RESERVED_PROOF_NAMES}
    need(type(records) is dict and set(records) == set(raw_files),"proof_report_inventory_differs")
    for name,path in raw_files.items():
        guard.check()
        record = records[name]
        need(type(record) is dict and type(record.get("bytes")) is int and record["bytes"] == path.stat().st_size
             and type(record.get("sha256")) is str and re.fullmatch(r"[0-9a-f]{64}",record["sha256"])
             and sha(path) == record["sha256"],"proof_report_hash_differs")
    need(proof.get("source_sha256") == source_pins,"proof_delivery_source_differs")
    original = proof.get("archive")
    need(type(original) is dict and set(original) == {"source_commit","run_id","artifact_id","archive_bytes","archive_sha256"}
         and original["source_commit"] == args.source_commit and original["run_id"] == args.run_id
         and type(original["artifact_id"]) is int and original["artifact_id"] > 0
         and original["artifact_id"] == proof.get("artifact_id")
         and type(original["archive_bytes"]) is int and 0 < original["archive_bytes"] <= MAX_ARCHIVE
         and type(original["archive_sha256"]) is str and re.fullmatch(r"[0-9a-f]{64}",original["archive_sha256"])
         and proof.get("whole_archive_API_digest_verified") is True,"proof_original_artifact_binding_differs")
    branch = "downloads/ios-unified-prototype-source-"+args.source_commit
    need(proof.get("status") == "PASS_DELIVERED" and proof.get("source_commit") == args.source_commit
         and proof.get("run_id") == args.run_id and proof.get("branch") == branch
         and proof.get("full_remote_download_SHA256_verified") is True
         and proof.get("all_prior_and_language_gates") is True
         and publication.get("published") is True and publication.get("source_commit") == args.source_commit
         and publication.get("branch") == branch and publication.get("commit") == proof.get("publication_commit")
         and type(publication.get("commit")) is str and re.fullmatch(r"[0-9a-f]{40}",publication["commit"]),"publication_proof_failed")
    need(proof.get("version") == "156.9117" and manifest.get("source_commit") == args.source_commit
         and manifest.get("validation",{}).get("Actions_run") == args.run_id
         and len(manifest.get("artifacts",[])) == 1
         and len(publication.get("artifacts",[])) == 1,"proof_artifact_count_differs")
    wanted,receipt = manifest["artifacts"][0],publication["artifacts"][0]
    need(all(proof["ipa"].get(key) == wanted.get(key) == receipt.get(key) for key in ("name","bytes","sha256"))
         and wanted.get("name") == IPA and type(wanted.get("bytes")) is int and 0 < wanted["bytes"] <= MAX_IPA
         and type(wanted.get("sha256")) is str and re.fullmatch(r"[0-9a-f]{64}",wanted["sha256"])
         and receipt.get("complete_download_verified") is True
         and PACKAGE_REPORT in records,"proof_ipa_binding_differs")
    result = {"schema":1,"status":"PASS_VERIFIED_REMOTE_PUBLICATION_PROOF","source_commit":args.source_commit,
              "run_id":args.run_id,"proof_artifact_id":args.artifact_id,"archive_sha256":args.artifact_sha256,
              "original_ipa_artifact":original,"source_sha256":proof["source_sha256"],
              "IPA_materialized_locally":False,"publication_commit":publication["commit"],"branch":branch,
              "download_url":"https://github.com/"+REPO+"/raw/"+publication["commit"]+"/"+IPA,"ipa":proof["ipa"]}
    guard.check()
    (work/"proof-fetch.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result))

if __name__ == "__main__":
    main()
