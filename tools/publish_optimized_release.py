#!/usr/bin/env python3
"""Publish one source-bound, fully verified optimization release on Actions.

This tool downloads binaries only on a remote Linux runner. Its output folder
contains bounded metadata only; it never replaces an existing release or tag.
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
import plistlib
import re
import shutil
import stat
import statistics
import subprocess
import sys
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request
from zipfile import ZipFile, ZIP_STORED, ZIP_DEFLATED
import zlib

ROOT = Path(__file__).resolve().parents[1]
REPO = "tagundo/IdolyPride_client"
VERSION, BUILD, IPA_VERSION = "0.3.36", 53, "156.9116"
RELEASE_VERSION, TAG = None, None
RELEASE_NAMES = {}
BASELINE = "50e349f4db6db0d3122bdc09c3b06307145f814f"
MIB, CHUNK = 1024 * 1024, 128 * 1024
MAX_JSON, MAX_PROOF = 8 * MIB, 8 * MIB
IPA = "IdolyPride-6.1.1-Unified-iOS.ipa"
APK = "IdolyPride-Local-Server-Android.apk"
QA_APK = "IdolyPride-Local-Server-Android-x86_64-QA.apk"
MAC = "IdolyPride-Local-Server-macOS-arm64.app.zip"
JOBS = ("portable", "performance", "android", "android-clients", "ios-unified")
PREFIXES = {name: "optimized-release-" + name + "-" for name in JOBS[:-1]}
PREFIXES["ios-unified"] = "ios-unified-prototype-"
ARCHIVE_LIMITS = {"portable": 32*MIB, "performance": 32*MIB,
                  "android": 900*MIB, "macos": 640*MIB, "ios-unified": 768*MIB}
BINARY_LIMITS = {APK: 384*MIB, QA_APK: 384*MIB, MAC: 600*MIB, IPA: 600*MIB}
COMMON_SOURCES = tuple(["src/idoly_local/app_runtime.py","src/idoly_local/diagnostics.py","src/idoly_local/resource_translation_runtime.py","src/idoly_local/account_manager.py","src/idoly_local/state.py","src/idoly_local/runtime_history.py","src/idoly_local/startup_checks.py","src/idoly_local/profile_directory.py","src/idoly_local/love_catalog.py","tools/release_account_contract.py","tools/release_event_contract.py","tools/build_server_payload.py","LICENSE","tools/prepare_love_server_data.py","tools/love_server_data_pin.py","data/love-server-data-pin.json","data/love-server-overlay.zip","data/love-reference.json","data/love-adv-proof.json","data/love-reference-NOTICE.txt"])
TRANSLATION_SOURCES = ("public_payload.py", "bundled_translations.py", "resource_translation.py",
                       "resource_translation_runtime.py", "octo_manifest.py", "octo_runtime.py")
BASE_DATA_PIN = {"bytes": 191343014, "sha256": "37dbf0fb9bac5d860991753d2e41ff0c269684bfca673ba41e1bcb897651c223"}
TRANSLATION_PINS = {
    "android": {"bytes": 125709184, "sha256": "22c166ffc3bbbc9e38739cea21fbfd7a87436a166ed56cdb7ee650acfc222dec"},
    "ios": {"bytes": 125717042, "sha256": "987fab065fbf791b37b9afe71c53979dc2186e711cde338c89ebe8e0ff905b72"},
}
CERTIFICATE = "ff5b25120ac58f5b82861320925448663a5ac3f812e93736cad1de6a6ac29e51"
COMMON_FLAGS = ("source_bound", "payload_sha256_verified", "translations_sha256_verified",
                "live_engine_included", "live_engine_source_built")
ANDROID_FLAGS = ("apk_signature_verified", "apk_alignment_verified", "package_version_verified",
                 "development_certificate_verified", "x86_emulator_runtime_passed", "account_management_roundtrip")
MAC_FLAGS = ("codesign_strict_verified", "bundled_engine_tested", "native_gui_start_stop_tested", "account_management_roundtrip")
COMPANIONS = (
    {"name": "IdolyPride-Local-Graphics-Diagnostic-Android-arm64-ko.apk", "bytes": 165128829,
     "sha256": "44f233290128a97f78940e3167c9486dbe39550090efcb90f7dc403430e94b9e",
     "source_commit": "cba4b5a272d4e7033ec5a18223f737c37a749d8f",
     "publication_commit": "3b2c73b51931bb7be031c37c9d55297505fb88e1", "version": "0.3.31"},
)

ANDROID_LANGUAGE_CLIENTS = {
    "ja": "IdolyPride-Local-Graphics-Diagnostic-Android-arm64-ja.apk",
    "en": "IdolyPride-Local-Graphics-Diagnostic-Android-arm64-en.apk",
}
INPUT_RELEASE_ASSETS = frozenset((APK, IPA, *ANDROID_LANGUAGE_CLIENTS.values(),
                                  *(row["name"] for row in COMPANIONS)))
EXPECTED_RELEASE_ASSETS = frozenset()

ARCHIVE_LIMITS["android-clients"] = 900*MIB
BINARY_LIMITS.update({name: 384*MIB for name in ANDROID_LANGUAGE_CLIENTS.values()})
ANDROID_CLIENT_CERTIFICATE = "aa4e9346ff9e542b263b70254df3e25b79211df16161208a3b509c4f113facfc"
ANDROID_CLIENT_INPUTS = {
    "diagnostic_base": {"bytes": 159549324, "sha256": "f5be0c0e19c2a17ea28ffa0c3205a49f5ab004f013e2e67e319aa192ca1995df"},
    "apkeditor": {"bytes": 7126009, "sha256": "4a98ae6a755264357603f1906b92e62e757d59229014e33395f4e03ff019fda8"},
    "font": {"bytes": 3781740, "sha256": "7cd2b757bd8b8db79b4b87c3b402aa62aca666b55ff50ae0799e14ece1942314"},
    "english_ui": {"bytes": 227781, "sha256": "b30f48cdcbc0ddfc267a0a7d265ec717a7057342bdc55c9f0d16fe3ea06fc702"},
    "english_ui_proof": {"bytes": 348, "sha256": "298138bcadd69249a4b064b1b96ada4c15e6da2c42327d1d97e27a2b6c69cb62"},
}
ANDROID_CLIENT_FLAGS = ("pinned_inputs_verified", "source_bound_native_and_feature_verified",
    "signature_v2_v3_verified", "zipalign_16384_verified", "same_update_identity_verified",
    "declared_member_inventory_verified", "local_resource_output_fields_verified",
    "built_in_ui_language_verified", "font_assets_verified", "original_inputs_unchanged")
ANDROID_CLIENT_SOURCES = ("tools/release_android_clients.py", "client-presentation/build_addon.py",
    "client-presentation/build_full_client.py", "client-presentation/native/bridge.cpp",
    "client-presentation/native/profile.json", "src/idoly_local/ui_assets.py",
    "src/idoly_local/font_assets.py", "src/idoly_local/static_ui_assets.py",
    "src/idoly_local/ui_display_literals.py", "src/idoly_local/story_loading_prefab.py",
    "ios-unified/client-language-inputs/en.csv", "ios-unified/client-language-inputs/en-report.json")
ANDROID_CLIENT_REPORT_FILES = frozenset((
    *(name.replace(".apk", ".provenance.json") for name in ANDROID_LANGUAGE_CLIENTS.values()),
    "native/build-receipt.json", "diagnostics-feature.provenance.json"))


class ReleaseError(ValueError):
    """Only fixed, credential-free error codes escape publication."""


def need(value, code):
    if not value:
        raise ReleaseError(code)


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def is_sha(value, length=64):
    return type(value) is str and re.fullmatch("[0-9a-f]{" + str(length) + "}", value) is not None


def pairs(items):
    result = {}
    for key, value in items:
        need(key not in result, "duplicate_json_key")
        result[key] = value
    return result


def decode(raw):
    def invalid_constant(_value):
        raise ReleaseError("nonfinite_json")
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid_constant)


def read_json(path, maximum=MAX_JSON):
    info = Path(path).lstat()
    need(stat.S_ISREG(info.st_mode) and 0 < info.st_size <= maximum, "json_file_bound")
    with Path(path).open("rb") as stream:
        raw = stream.read(maximum + 1)
    need(len(raw) == info.st_size, "json_file_changed")
    value = decode(raw)
    need(type(value) is dict, "json_object_required")
    return value


def write_json(path, value):
    raw = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
    need(len(raw) <= MAX_JSON, "generated_json_bound")
    Path(path).write_bytes(raw)


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    spec.loader.exec_module(result)
    return result


LATEST_SERVER_DATA = module("published_latest_server_data_pin", ROOT/"tools/latest_server_data_pin.py")
LOVE_SERVER_DATA = LATEST_SERVER_DATA  # Compatibility for verified provenance consumers.
COMMON_SOURCES = tuple(sorted(set(COMMON_SOURCES) | set(LATEST_SERVER_DATA.SOURCE_COMPONENTS) | {
    'src/idoly_local/public_payload.py',
    'src/idoly_local/public_payload_transaction.py',
    'src/idoly_local/public_cohort_support.py',
    'src/idoly_local/latest_cohort_pins.py',
    'src/idoly_local/love_compatibility_pins.py',
    'src/idoly_local/resource_library.py',
    'src/idoly_local/resource_archive.py',
    'src/idoly_local/octo_runtime.py',
    'src/idoly_local/resource_translation.py',
    'tools/prepare_latest_server_data.py',
    'tools/latest_server_data_pin.py',
    'data/latest-server-data-pin.json',
    'data/latest-server-overlay.zip',
}))
DATA_PIN = LATEST_SERVER_DATA.output_pin()


def configure_release(value):
    """Freeze a calendar release identity separately from platform build versions."""
    global RELEASE_VERSION, TAG, RELEASE_NAMES, EXPECTED_RELEASE_ASSETS
    identity = module("idoly_release_identity", ROOT/"tools/release_identity.py")
    try:
        version = identity.resolve_release_version(value)
        names = {name: identity.asset_name(name, version) for name in INPUT_RELEASE_ASSETS}
        tag = identity.release_tag(version)
        expected = frozenset(names.values())
    except ValueError:
        raise ReleaseError("calendar_release_version_invalid") from None
    need(RELEASE_VERSION is None or RELEASE_VERSION == version, "release_identity_already_frozen")
    need(len(names) == len(expected) == 5 and frozenset(names.values()) == expected,
         "release_name_mapping_differs")
    if RELEASE_VERSION is None:
        RELEASE_VERSION, TAG, RELEASE_NAMES, EXPECTED_RELEASE_ASSETS = version, tag, names, expected
    return version


def require_release():
    need(type(RELEASE_VERSION) is str and TAG == "v" + RELEASE_VERSION
         and len(RELEASE_NAMES) == len(EXPECTED_RELEASE_ASSETS) == 5,
         "calendar_release_identity_required")


def release_name(source_name):
    require_release()
    need(source_name in RELEASE_NAMES, "release_source_name_invalid")
    return RELEASE_NAMES[source_name]


def stage_release_binaries(rows, directory, guard):
    """Move verified inputs to fresh date-versioned names without changing bytes."""
    require_release()
    need(type(rows) is list and 0 < len(rows) <= len(INPUT_RELEASE_ASSETS)
         and all(type(row) is dict for row in rows), "release_staging_inventory_invalid")
    names = [row.get("name") for row in rows]
    need(all(type(name) is str and name in INPUT_RELEASE_ASSETS for name in names)
         and len(set(names)) == len(names), "release_staging_input_names_invalid")
    directory = Path(directory)
    need(not directory.exists() and not directory.is_symlink(), "fresh_release_staging_directory_required")
    checked = []
    for row in rows:
        guard.check()
        need(type(row.get("path")) is str and Path(row["path"]).name == row["name"]
             and row.get("source_name", row["name"]) == row["name"], "release_staging_source_path_differs")
        path = verified_file(Path(row["path"]).parent,
                             {key: row[key] for key in ("name", "bytes", "sha256")}, name=row["name"])
        checked.append((row, path))
    directory.mkdir(mode=0o700)
    result = []
    for row, path in checked:
        guard.check()
        name = release_name(row["name"])
        target = directory/name
        need(not target.exists() and not target.is_symlink(), "release_staging_target_exists")
        path.rename(target)
        verified_file(directory, {"name": name, "bytes": row["bytes"], "sha256": row["sha256"]})
        result.append({**row, "source_name": row["name"], "name": name, "path": str(target)})
        guard.check()
    return result


def blob_sha(source, name):
    raw = subprocess.check_output(["git", "show", source + ":" + name], cwd=ROOT, timeout=30)
    return hashlib.sha256(raw).hexdigest()


def safe_relative(name):
    need(type(name) is str and 0 < len(name) <= 256, "artifact_path_invalid")
    path = PurePosixPath(name)
    need(bool(path.parts) and not path.is_absolute() and ".." not in path.parts and str(path) == name
         and "\\" not in name and "\0" not in name
         and all(re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", part) for part in path.parts),
         "artifact_path_invalid")
    return path


def source_pins(values, source, *, required=COMMON_SOURCES):
    need(type(values) is dict and 0 < len(values) <= 1024 and set(required) <= values.keys(),
         "source_pin_set_invalid")
    for name, wanted in values.items():
        safe_relative(name)
        need(is_sha(wanted) and blob_sha(source, name) == wanted, "source_pin_differs")
    return values


def number(value, maximum, *, positive=False):
    return (type(value) in (int, float) and math.isfinite(value)
            and (value > 0 if positive else value >= 0) and value <= maximum)


def record(value, *, name=None, maximum=600*MIB):
    need(type(value) is dict and set(value) == {"name", "bytes", "sha256"}, "file_record_invalid")
    safe_relative(value["name"])
    need("/" not in value["name"] and (name is None or value["name"] == name)
         and type(value["bytes"]) is int and 0 < value["bytes"] <= maximum
         and is_sha(value["sha256"]), "file_record_invalid")
    return value


def verified_file(directory, row, *, name=None, maximum=600*MIB):
    row = record(row, name=name, maximum=maximum)
    path = directory / row["name"]
    info = path.lstat()
    need(stat.S_ISREG(info.st_mode) and info.st_size == row["bytes"] and digest(path) == row["sha256"],
         "file_record_binding_differs")
    return path


def validate_run(build, jobs, artifacts, source, run):
    need(type(build) is dict and type(build.get("id")) is int and build["id"] == run
         and build.get("head_sha") == source and build.get("event") in ("workflow_dispatch", "push")
         and build.get("repository", {}).get("full_name") == REPO
         and build.get("path") == ".github/workflows/release-all-platforms.yml",
         "run_source_binding_differs")
    if build["event"] == "push":
        need(build.get("head_branch") == "feat/ios-unified-server", "push_branch_differs")
    rows = jobs.get("jobs")
    need(type(rows) is list and type(jobs.get("total_count")) is int
         and len(rows) == jobs["total_count"] <= 100, "job_inventory_bound")
    for name in JOBS:
        found = [row for row in rows if row.get("name") == name]
        need(len(found) == 1 and found[0].get("conclusion") == "success", "required_job_not_passed")
    rows = artifacts.get("artifacts")
    need(type(rows) is list and type(artifacts.get("total_count")) is int
         and len(rows) == artifacts["total_count"] <= 100, "artifact_inventory_bound")
    result = {}
    for role, prefix in PREFIXES.items():
        found = [row for row in rows if row.get("name") == prefix + source]
        need(len(found) == 1, "required_artifact_missing_or_duplicate")
        item = found[0]
        need(type(item.get("id")) is int and item["id"] > 0 and item.get("expired") is False
             and item.get("workflow_run", {}).get("id") == run
             and item.get("workflow_run", {}).get("head_sha") == source
             and type(item.get("size_in_bytes")) is int
             and 0 < item["size_in_bytes"] <= ARCHIVE_LIMITS[role]
             and type(item.get("digest")) is str and re.fullmatch(r"sha256:[0-9a-f]{64}", item["digest"]),
             "artifact_source_binding_differs")
        result[role] = {"source_commit": source, "run_id": run, "artifact_id": item["id"],
                        "archive_bytes": item["size_in_bytes"], "archive_sha256": item["digest"][7:]}
    return result


def generic_members(archive, role):
    rows = archive.infolist()
    need(0 < len(rows) <= 1024 and len({row.filename for row in rows}) == len(rows),
         "zip_inventory_bound_or_duplicate")
    result, total, folded = {}, 0, set()
    binaries = ({APK, QA_APK} if role == "android" else {MAC} if role == "macos" else
                set(ANDROID_LANGUAGE_CLIENTS.values()) if role == "android-clients" else set())
    for row in rows:
        name = row.filename.rstrip("/")
        path = safe_relative(name)
        need(row.orig_filename == row.filename and name.casefold() not in folded, "zip_path_alias")
        folded.add(name.casefold())
        mode = row.external_attr >> 16 & 0o170000
        need(mode in (0, stat.S_IFREG, stat.S_IFDIR) and not row.flag_bits & 1
             and row.compress_type in (ZIP_STORED, ZIP_DEFLATED), "zip_member_type_rejected")
        if row.is_dir():
            continue
        if name in binaries:
            need(0 < row.file_size <= BINARY_LIMITS[name], "binary_member_bound")
        else:
            need(path.suffix in (".json", ".xml", ".txt", ".log", ".png")
                 and 0 < row.file_size <= MAX_JSON, "metadata_member_bound")
            total += row.file_size
            need(total <= 64*MIB, "metadata_total_bound")
        result[name] = row
    required = ({"platform-report.json", APK, QA_APK, "android-qa.json"} if role == "android" else
                {"platform-report.json", MAC, "engine-smoke.json"} if role == "macos" else
                {"android-clients-report.json", *ANDROID_LANGUAGE_CLIENTS.values(), *ANDROID_CLIENT_REPORT_FILES}
                if role == "android-clients" else {"portable-report.json"} if role == "portable" else
                {"performance-report.json", "diagnostics-polling.json", "translation-startup.json"})
    need(required <= result.keys(), "artifact_required_members_missing")
    return result


def extract_generic(archive_path, output, role, guard):
    output.mkdir(mode=0o700)
    inventory = {}
    with ZipFile(archive_path) as archive:
        for name, row in generic_members(archive, role).items():
            target = output.joinpath(*PurePosixPath(name).parts)
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            digest_value, count, crc = hashlib.sha256(), 0, 0
            descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(descriptor, "wb") as outgoing, archive.open(row) as incoming:
                while block := incoming.read(CHUNK):
                    guard.check()
                    count += len(block)
                    need(count <= row.file_size, "member_extent_exceeded")
                    digest_value.update(block)
                    crc = zlib.crc32(block, crc)
                    need(outgoing.write(block) == len(block), "member_short_write")
                outgoing.flush()
                os.fsync(outgoing.fileno())
            need(count == row.file_size and crc & 0xffffffff == row.CRC, "member_crc_or_size_differs")
            inventory[name] = {"bytes": count, "sha256": digest_value.hexdigest()}
    return inventory


def pin(row, wanted):
    need(type(row) is dict and all(type(row.get(key)) is type(value) and row[key] == value
                                   for key, value in wanted.items()), "public_input_pin_differs")


def platform_binary(value, platform, *, qa=False):
    need(type(value) is dict, "platform_binary_record_invalid")
    name = QA_APK if qa else APK if platform == "android" else MAC
    plain = {key: value.get(key) for key in ("name", "bytes", "sha256")}
    record(plain, name=name, maximum=BINARY_LIMITS[name])
    if platform == "android":
        expected = {"abi": "x86_64" if qa else "arm64-v8a",
                    "application_id": "game.qualiarts.idolypride.localserver", "version": VERSION,
                    "build_number": BUILD, "certificate_sha256": CERTIFICATE,
                    "signature_verified": True, "alignment_verified": True}
        need(set(value) == set(plain) | set(expected)
             and all(type(value.get(key)) is type(wanted) and value[key] == wanted
                     for key, wanted in expected.items()), "android_binary_identity_differs")
    else:
        need(set(value) == set(plain), "mac_binary_record_invalid")
    return plain


def validate_platform(report, platform, source):
    need(type(report) is dict and report.get("schema") == 1 and type(report.get("schema")) is int
         and report.get("status") == "PASS" and report.get("platform") == platform
         and report.get("source_commit") == source and report.get("version") == VERSION
         and type(report.get("build_number")) is int and report["build_number"] == BUILD,
         "platform_identity_differs")
    platform_binary(report.get("binary"), platform)
    source_pins(report.get("source_sha256"), source)
    inputs = report.get("inputs", {})
    pin(inputs.get("server_data"), DATA_PIN)
    try:
        LOVE_SERVER_DATA.verify_upgrade_proof(inputs.get("server_data_provenance"))
    except ValueError:
        raise ReleaseError("server_data_preparation_provenance_differs") from None
    translations = inputs.get("translations")
    target = "android" if platform == "android" else "ios"
    pin(translations, {**TRANSLATION_PINS[target], "platform": target, "included": True})
    flags = COMMON_FLAGS + (ANDROID_FLAGS if platform == "android" else MAC_FLAGS)
    validation = report.get("validation", {})
    need(type(validation) is dict and all(validation.get(name) is True for name in flags),
         "platform_validation_not_passed")
    execution = report.get("execution", {})
    need(type(execution) is dict
         and execution.get("actual_macos_execution") is (platform == "macos")
         and execution.get("actual_android_arm64_execution") is False
         and execution.get("physical_PlayCover_execution") is False,
         "platform_execution_scope_differs")
    if platform == "android":
        need(report.get("application_id") == "game.qualiarts.idolypride.localserver"
             and report.get("certificate_sha256") == CERTIFICATE, "android_identity_differs")
        platform_binary(report.get("qa_binary"), platform, qa=True)
    return report


def validate_portable(report, source, directory):
    need(type(report) is dict and type(report.get("schema")) is int and report["schema"] == 1
         and report.get("status") == "PASS" and report.get("source_commit") == source,
         "portable_identity_differs")
    validation = report.get("validation", {})
    need(type(validation) is dict and validation.get("pytest_passed") is True
         and validation.get("compileall_passed") is True
         and validation.get("actual_preference_master_contracts_passed") is True,
         "portable_checks_not_passed")
    contracts = report.get("preference_master_contracts")
    need(type(contracts) is dict, "preference_contracts_missing")
    pin(contracts.get("input"), BASE_DATA_PIN)
    need(contracts.get("master_version") == "961e456499039e31248a818a911c8d95f92461f86aff4674ba07e29c32afcf60"
         and contracts.get("selected_counts") == {"CardImage": 611, "Decoration": 361},
         "preference_contract_catalog_differs")
    for key, relative in (("module_sha256", "src/idoly_local/preference_master_data.py"),
                          ("supplement_report_sha256", "docs/preference-master-data.json")):
        path = ROOT / relative
        need(path.is_file() and not path.is_symlink() and contracts.get(key) == digest(path),
             "preference_contract_source_differs")
    counts = contracts.get("tests")
    need(type(counts) is dict and type(counts.get("count")) is int and counts["count"] >= 3
         and all(type(counts.get(key)) is int and counts[key] == 0
                 for key in ("failures", "errors", "skipped")),
         "preference_contract_tests_not_passed")
    record = contracts.get("junit")
    need(type(record) is dict and record.get("name") == "preference-contracts.xml",
         "preference_contract_junit_missing")
    path = Path(directory) / record["name"]
    need(path.is_file() and not path.is_symlink() and 0 < path.stat().st_size <= MAX_JSON
         and record.get("bytes") == path.stat().st_size and record.get("sha256") == digest(path),
         "preference_contract_junit_digest_differs")
    import xml.etree.ElementTree as ET
    try:
        cases = ET.fromstring(path.read_bytes()).findall(".//testcase")
    except ET.ParseError:
        raise ReleaseError("preference_contract_junit_invalid") from None
    names = {"test_generated_preference_supplement_matches_recorded_original_tables",
             "test_actual_pinned_supplement_fallback_updates_owned_card_and_decoration",
             "test_actual_pinned_media_inventory_includes_all_verified_decorations"}
    need(len(cases) == counts["count"] and names <= {row.get("name") for row in cases}
         and not any(row.find(tag) is not None for row in cases for tag in ("failure", "error", "skipped")),
         "preference_contract_required_cases_not_passed")


def validate_diagnostics_benchmark(report, source):
    need(type(report) is dict and type(report.get("schema")) is int and report["schema"] == 1
         and type(report.get("repeats")) is int and 3 <= report["repeats"] <= 10
         and type(report.get("iterations")) is int and 100 <= report["iterations"] <= 100000,
         "diagnostics_benchmark_bounds")
    contract = module("published_diagnostics_comparison_contract", ROOT/"tools/benchmark_diagnostics_polling.py")
    need(contract.strict_equal(report.get("comparison_scope"), contract.comparison_scope())
         and contract.strict_equal(report.get("management_contract"), contract.management_contract())
         and report.get("tracemalloc_separate_pass") is True,
         "diagnostics_comparison_contract_differs")
    script_sha = report.get("benchmark_sha256")
    need(is_sha(script_sha) and blob_sha(source, "tools/benchmark_diagnostics_polling.py") == script_sha,
         "diagnostics_benchmark_script_pin_differs")
    expected = {"baseline": {"poll": 1, "explicit_export": 2},
                "candidate": {"poll": 0, "explicit_export": 1}}
    need(contract.strict_equal(report.get("expected_history_deepcopy_calls"), expected),
         "diagnostics_copy_policy_differs")
    hashes = report.get("identical_legacy_outputs")
    need(type(hashes) is dict and set(hashes) == {"summary_sha256", "poll_sha256", "export_sha256"}
         and all(is_sha(value) for value in hashes.values()) and "identical_outputs" not in report,
         "diagnostics_semantics_missing")
    full = report.get("full_outputs")
    need(type(full) is dict and set(full) == {"baseline", "candidate"}
         and all(type(value) is dict and set(value) == {"poll_sha256", "export_sha256"}
                 and all(is_sha(digest) for digest in value.values()) for value in full.values()),
         "diagnostics_full_output_provenance_missing")
    runs = report.get("runs")
    need(type(runs) is dict and set(runs) == {"baseline", "candidate"}, "diagnostics_run_set")
    roots = {}
    for name, group in runs.items():
        need(type(group) is list and len(group) == report["repeats"], "diagnostics_run_count")
        for row in group:
            try:
                contract.validate_worker_comparison(row, name)
            except (ValueError, TypeError, KeyError):
                raise ReleaseError("diagnostics_run_comparison_contract_differs") from None
            need(type(row.get("schema")) is int and row["schema"] == 1
                 and type(row.get("iterations")) is int and row["iterations"] == report["iterations"]
                 and row.get("benchmark_sha256") == script_sha
                 and contract.strict_equal(row.get("history_deepcopy_calls"), expected[name])
                 and all(type(row.get(key)) is int and row[key] == wanted for key, wanted in (
                     ("synthetic_events", 200), ("frames_per_event", 16), ("received_events", 200),
                     ("stored_events", 200), ("default_full_events", 200), ("exported_events", 200)))
                 and row.get("poll_contains_events") is False
                 and all(row.get(key) == value for key, value in hashes.items())
                 and all(row.get("full_" + key) == value for key, value in full[name].items())
                 and type(row.get("tracemalloc_peak_bytes")) is int and 0 < row["tracemalloc_peak_bytes"] <= 10**12
                 and all(number(row.get(key), 10**12, positive=True) for key in
                         ("wall_microseconds_per_poll", "cpu_microseconds_per_poll")),
                 "diagnostics_run_semantics_differs")
            root = row.get("source_root")
            need(type(root) is str and len(root) <= 4096 and PurePosixPath(root).is_absolute()
                 and ".." not in PurePosixPath(root).parts and roots.get(name, root) == root,
                 "diagnostics_run_source_root_differs")
            roots[name] = root
    need(roots["baseline"] != roots["candidate"]
         and not PurePosixPath(roots["baseline"]).is_relative_to(PurePosixPath(roots["candidate"]))
         and not PurePosixPath(roots["candidate"]).is_relative_to(PurePosixPath(roots["baseline"])),
         "diagnostics_run_source_roots_overlap")
    pins = report.get("source_sha256")
    need(type(pins) is dict and set(pins) == {"baseline", "candidate"}, "benchmark_source_pins_missing")
    for name, revision in (("baseline", BASELINE), ("candidate", source)):
        values = pins[name]
        need(type(values) is dict and set(values) == {"diagnostics.py", "app_runtime.py"},
             "diagnostics_source_pins_missing")
        for filename, wanted in values.items():
            need(re.fullmatch(r"[a-z_]+[.]py", filename) and is_sha(wanted)
                 and blob_sha(revision, "src/idoly_local/" + filename) == wanted,
                 "benchmark_source_pin_differs")
    expected_medians = {name: {key: statistics.median(row[key] for row in group)
                               for key in ("wall_microseconds_per_poll", "cpu_microseconds_per_poll")}
                        for name, group in runs.items()}
    expected_speedup = {key: expected_medians["baseline"][key] / expected_medians["candidate"][key]
                        for key in expected_medians["baseline"]}
    need(report.get("median") == expected_medians and report.get("median_speedup") == expected_speedup,
         "diagnostics_derived_metrics_differ")
    return {key: report[key] for key in ("median", "median_speedup", "expected_history_deepcopy_calls",
        "comparison_scope", "management_contract", "identical_legacy_outputs", "full_outputs", "benchmark_sha256")}


def validate_translation_benchmark(report, source):
    need(type(report) is dict and type(report.get("schema")) is int and report["schema"] == 1 and report.get("status") == "PASS"
         and report.get("same_semantics") is True and report.get("protobuf") == "python"
         and report.get("platform") == "ios" and report.get("sequence") == ["ja", "ko", "en", "ko"]
         and report.get("baseline_revision_expected") == BASELINE
         and type(report.get("runs_per_source")) is int and 3 <= report["runs_per_source"] <= 5,
         "translation_benchmark_identity")
    inputs = report.get("inputs", {})
    pin(inputs.get("server_data"), BASE_DATA_PIN)
    pin(inputs.get("translations"), TRANSLATION_PINS["ios"])
    runs, expected_semantics = report.get("runs"), None
    need(type(runs) is dict and set(runs) == {"baseline", "candidate"}, "translation_run_set")
    for group in runs.values():
        need(type(group) is list and len(group) == report["runs_per_source"], "translation_run_count")
        for row in group:
            semantics = row.get("semantics")
            need(type(row.get("schema")) is int and row["schema"] == 1 and row.get("status") == "PASS"
                 and row.get("protobuf") == "python" and row.get("role") == "measure"
                 and type(semantics) is dict and bool(semantics), "translation_semantics_missing")
            if expected_semantics is None:
                expected_semantics = semantics
            need(semantics == expected_semantics and all(number(row.get(key), 10**12, positive=True)
                 for key in ("elapsed_seconds", "validation_seconds", "peak_rss_bytes", "validation_peak_rss_bytes")),
                 "translation_semantics_differs")
    pins = report.get("source_sha256")
    need(type(pins) is dict and set(pins) == {"baseline", "candidate"}, "benchmark_source_pins_missing")
    for name, revision in (("baseline", BASELINE), ("candidate", source)):
        need(type(pins[name]) is dict and set(pins[name]) == set(TRANSLATION_SOURCES),
             "translation_source_pins_missing")
        for filename, wanted in pins[name].items():
            need(re.fullmatch(r"[a-z_]+[.]py", filename) and is_sha(wanted)
                 and blob_sha(revision, "src/idoly_local/" + filename) == wanted, "benchmark_source_pin_differs")
    expected_medians = {name: {key: statistics.median(row[key] for row in group) for key in
                               ("elapsed_seconds", "validation_seconds", "peak_rss_bytes", "validation_peak_rss_bytes")}
                        for name, group in runs.items()}
    need(report.get("medians") == expected_medians
         and report.get("median_peak_rss_saving_bytes") ==
             expected_medians["baseline"]["peak_rss_bytes"] - expected_medians["candidate"]["peak_rss_bytes"]
         and report.get("median_seconds_saved") ==
             expected_medians["baseline"]["elapsed_seconds"] - expected_medians["candidate"]["elapsed_seconds"],
         "translation_derived_metrics_differ")
    return {key: report[key] for key in ("medians", "median_peak_rss_saving_bytes", "median_seconds_saved")}


def validate_performance(directory, source):
    report = read_json(directory / "performance-report.json")
    need(type(report.get("schema")) is int and report["schema"] == 1 and report.get("status") == "PASS"
         and report.get("source_commit") == source and report.get("baseline_commit") == BASELINE,
         "performance_identity_differs")
    entries = report.get("benchmarks")
    need(type(entries) is dict and set(entries) == {"diagnostics", "translation"}, "benchmark_set_differs")
    diagnostics = read_json(verified_file(directory, entries["diagnostics"], name="diagnostics-polling.json", maximum=MAX_JSON))
    translation = read_json(verified_file(directory, entries["translation"], name="translation-startup.json", maximum=MAX_JSON))
    return {"diagnostics": validate_diagnostics_benchmark(diagnostics, source),
            "translation": validate_translation_benchmark(translation, source)}


def archive_member_hash(path, member, wanted, guard):
    with ZipFile(path) as archive:
        matches = [row for row in archive.infolist() if row.filename == member]
        need(len(matches) == 1 and matches[0].file_size == wanted["bytes"], "embedded_input_extent_differs")
        value, count = hashlib.sha256(), 0
        with archive.open(matches[0]) as stream:
            while block := stream.read(CHUNK):
                guard.check()
                count += len(block)
                need(count <= wanted["bytes"], "embedded_input_extent_differs")
                value.update(block)
        need(count == wanted["bytes"] and value.hexdigest() == wanted["sha256"], "embedded_input_sha256_differs")


def validate_platform_files(directory, report, guard):
    platform = report["platform"]
    binary = verified_file(directory, platform_binary(report["binary"], platform))
    if platform == "android":
        verified_file(directory, platform_binary(report["qa_binary"], platform, qa=True), name=QA_APK, maximum=BINARY_LIMITS[QA_APK])
        for name in (APK, QA_APK):
            archive_member_hash(directory/name, "assets/ServerData.zip", DATA_PIN, guard)
            archive_member_hash(directory/name, "assets/bundledTranslations.zip", TRANSLATION_PINS["android"], guard)
        qa = read_json(directory / "android-qa.json")
        need(qa.get("ok") is True and qa.get("target") == "Android emulator"
             and qa.get("device_game_client_tested") is False and qa.get("final_stop") is True
             and "error" not in qa
             and all(qa.get(name) is True for name in (
                 "system_check", "local_auth", "home_rpcs", "restart_session_preserved", "gameplay_change_preserved",
                 "port_rebound", "upgrade_identity_preserved", "upgrade_sessions_preserved", "upgrade_settings_preserved",
                 "starter_inventory_persisted", "main_live_first_quest", "main_live_mode_default_off", "main_live_opt_in",
                 "main_live_persisted", "main_live_attempts_persisted", "main_live_clock_preserved",
                 "main_live_identity_preserved", "main_live_sessions_preserved", "main_live_settings_preserved",
                 "main_live_cached_no_grant",'account_native_create','account_native_clone','account_queued_selection_persisted','account_selected_encrypted_rpc','account_document_export_import','account_zip_whole_state_preserved','account_original_whole_state_preserved','account_import_sessions_excluded','account_selection_restored','native_event_settings_autosave','native_event_settings_restart_preserved')), "android_runtime_qa_not_passed")
        try:
            detail = module("published_android_account_contract", ROOT/"tools/release_account_contract.py").validate_android(qa)
        except ValueError:
            raise ReleaseError("android_account_management_not_passed") from None
        need(detail == report.get("account_management"), "android_account_management_report_differs")
        try:
            event_detail = module("published_android_event_contract", ROOT/"tools/release_event_contract.py").validate_android(qa)
        except ValueError:
            raise ReleaseError("android_native_event_settings_not_passed") from None
        need(event_detail == report.get("native_event_settings"), "android_native_event_settings_report_differs")
    else:
        smoke_path = verified_file(directory, report.get("account_smoke"), name="engine-smoke.json", maximum=MAX_JSON)
        try:
            account_detail = module("published_account_contract", ROOT/"tools/release_account_contract.py").validate(read_json(smoke_path))
        except ValueError:
            raise ReleaseError("mac_account_management_smoke_not_passed") from None
        need(account_detail == report.get("account_management"), "mac_account_management_report_differs")
        with ZipFile(binary) as archive:
            entries = [row for row in archive.infolist() if row.filename.endswith(".app/Contents/Info.plist")]
            need(len(entries) == 1 and 0 < entries[0].file_size <= 65536, "mac_plist_inventory")
            info = plistlib.loads(archive.read(entries[0]))
            need(info.get("CFBundleIdentifier") == "game.idolypride.localserver"
                 and info.get("CFBundleShortVersionString") == VERSION
                 and info.get("CFBundleVersion") == str(BUILD), "mac_plist_identity_differs")
        base = entries[0].filename.removesuffix("Info.plist")
        archive_member_hash(binary, base + "Resources/ServerData.zip", DATA_PIN, guard)
        archive_member_hash(binary, base + "Resources/bundledTranslations.zip", TRANSLATION_PINS["ios"], guard)
    return {"path": str(binary), **platform_binary(report["binary"], platform)}



def validate_android_clients(directory, source, run):
    report = read_json(directory/"android-clients-report.json")
    need(type(report.get("schema")) is int and report["schema"] == 1 and report.get("status") == "PASS"
         and report.get("source_commit") == source and type(report.get("run_id")) is int and report["run_id"] == run
         and report.get("languages") == ["ja", "en"], "android_clients_source_or_language_differs")
    source_pins(report.get("source_sha256"), source, required=ANDROID_CLIENT_SOURCES)
    inputs = report.get("inputs")
    need(type(inputs) is dict and set(inputs) == {*ANDROID_CLIENT_INPUTS, "shadowhook"},
         "android_clients_input_inventory_differs")
    for name, expected in ANDROID_CLIENT_INPUTS.items():
        need(type(inputs[name]) is dict and set(inputs[name]) == set(expected)
             and all(type(inputs[name].get(key)) is type(value) and inputs[name][key] == value
                     for key, value in expected.items()), "android_clients_input_pin_differs")
    shadowhook = inputs["shadowhook"]
    need(type(shadowhook) is dict and set(shadowhook) == {"bytes", "sha256"}
         and type(shadowhook.get("bytes")) is int and shadowhook["bytes"] == 461264
         and shadowhook.get("sha256") == "2cad01ff4d59542958775e19f281981a7e84b39670b5fae75905b8511e10c7cd",
         "android_clients_shadowhook_pin_differs")
    checks = report.get("validation")
    need(type(checks) is dict and set(checks) == {*ANDROID_CLIENT_FLAGS, "runtime_device_tested"}
         and all(checks.get(name) is True for name in ANDROID_CLIENT_FLAGS)
         and checks.get("runtime_device_tested") is False, "android_clients_packaging_qa_failed")
    files = report.get("report_files")
    need(type(files) is dict and set(files) == ANDROID_CLIENT_REPORT_FILES,
         "android_clients_report_inventory_differs")
    for name, expected in files.items():
        safe_relative(name)
        need(type(expected) is dict and set(expected) == {"bytes", "sha256"}
             and type(expected.get("bytes")) is int and 0 < expected["bytes"] <= MAX_JSON
             and is_sha(expected.get("sha256")), "android_clients_report_record_invalid")
        path = directory.joinpath(*PurePosixPath(name).parts)
        info = path.lstat()
        need(stat.S_ISREG(info.st_mode) and info.st_size == expected["bytes"] and digest(path) == expected["sha256"],
             "android_clients_report_digest_differs")
        read_json(path)
    rows = report.get("binaries")
    need(type(rows) is list and len(rows) == len(ANDROID_LANGUAGE_CLIENTS)
         and all(type(row) is dict for row in rows)
         and [row.get("language") for row in rows] == ["ja", "en"], "android_clients_binary_set_differs")
    result = []
    for row in rows:
        language = row["language"]
        need(set(row) == {"language", "name", "bytes", "sha256", "application_id", "version_code", "certificate_sha256"}
             and row.get("name") == ANDROID_LANGUAGE_CLIENTS[language]
             and row.get("application_id") == "game.qualiarts.idolypride.local.diagnostics"
             and type(row.get("version_code")) is int and row["version_code"] == 414
             and row.get("certificate_sha256") == ANDROID_CLIENT_CERTIFICATE,
             "android_clients_update_identity_differs")
        wanted = {key: row[key] for key in ("name", "bytes", "sha256")}
        path = verified_file(directory, wanted, name=ANDROID_LANGUAGE_CLIENTS[language],
                             maximum=BINARY_LIMITS[wanted["name"]])
        result.append({**row, "path": str(path)})
    return result


def asset_download_url(name):
    require_release()
    need(name in EXPECTED_RELEASE_ASSETS, "release_asset_name_not_versioned")
    safe_relative(name)
    need("/" not in name, "release_asset_name_invalid")
    return "https://github.com/" + REPO + "/releases/download/" + TAG + "/" + name


def verify_binary_stream(response, wanted, guard, outgoing=None):
    need(response.status == 200 and response.headers.get("Content-Encoding", "identity") == "identity"
         and response.headers.get("Content-Length") in (None, str(wanted["bytes"])), "binary_http_response_differs")
    value, count, prefix = hashlib.sha256(), 0, b""
    while True:
        guard.check()
        block = response.read(CHUNK)
        if not block:
            break
        count += len(block)
        need(count <= wanted["bytes"], "binary_download_extent_exceeded")
        if len(prefix) < 4:
            prefix = (prefix + block)[:4]
        value.update(block)
        if outgoing is not None:
            need(outgoing.write(block) == len(block), "binary_download_short_write")
    need(count == wanted["bytes"] and value.hexdigest() == wanted["sha256"],
         "binary_download_sha256_differs")
    need(prefix == b"PK\x03\x04", "binary_zip_prefix_differs")


def validate_release_asset(asset, wanted, *, allow_draft_url=False):
    need(type(allow_draft_url) is bool, "release_asset_phase_invalid")
    url = asset.get("browser_download_url") if type(asset) is dict else None
    # GitHub assigns an untagged URL while a new release is still a draft.
    # Only this exact temporary form is accepted before promotion; final
    # inventory verification always requires the canonical release tag.
    temporary = (allow_draft_url and type(url) is str and re.fullmatch(
        re.escape("https://github.com/" + REPO + "/releases/download/")
        + r"untagged-[0-9a-f]{20}/" + re.escape(wanted["name"]), url) is not None)
    need(type(asset) is dict and type(asset.get("id")) is int and asset["id"] > 0
         and asset.get("name") == wanted["name"] and asset.get("state") == "uploaded"
         and type(asset.get("size")) is int and asset["size"] == wanted["bytes"]
         and asset.get("digest") == "sha256:" + wanted["sha256"]
         and (url == asset_download_url(wanted["name"]) or temporary),
         "release_asset_identity_differs")
    return asset


def validate_release_inventory(assets, binaries, receipts, *, allow_draft_urls=False):
    require_release()
    names = EXPECTED_RELEASE_ASSETS
    need(type(assets) is list and len(assets) == len(binaries) == len(receipts) == len(names)
         and all(type(row) is dict for row in assets)
         and {row.get("name") for row in assets} == {row["name"] for row in binaries} == names
         and len({row.get("id") for row in assets}) == len(names)
         and {row.get("id") for row in assets} == {row["id"] for row in receipts},
         "release_asset_inventory_differs")
    for wanted in binaries:
        validate_release_asset(next(row for row in assets if row["name"] == wanted["name"]), wanted,
                               allow_draft_url=allow_draft_urls)


class GitHub:
    def __init__(self, token, opener):
        self.token, self.opener = token, opener
        self.owned_release_id, self.rollback_draft_restored = None, None
        self.asset_receipts = []

    def api(self, path, *, method="GET", body=None, absent=False):
        need(path.startswith("/") and "\n" not in path and "\r" not in path, "github_api_path")
        raw = json.dumps(body, separators=(",", ":")).encode() if body is not None else None
        request = Request("https://api.github.com/repos/" + REPO + path, data=raw, method=method,
                          headers={"Authorization": "Bearer " + self.token, "Accept": "application/vnd.github+json",
                                   "Content-Type": "application/json", "X-GitHub-Api-Version": "2022-11-28",
                                   "User-Agent": "idoly-verified-optimization-release"})
        try:
            response = self.opener.open(request, timeout=30)
        except HTTPError as error:
            if absent and error.code == 404:
                error.close()
                return None
            error.close()
            raise ReleaseError("github_api_request_failed") from None
        with response:
            raw = response.read(2*MIB + 1)
            need(response.status in (200, 201) and len(raw) <= 2*MIB, "github_api_response_bound")
        return decode(raw)

    def binary_response(self, target, *, headers=None, asset_id=None):
        parsed = urlsplit(target)
        hosts = {"github.com", "lfs.github.com", "media.githubusercontent.com",
                 "github-cloud.githubusercontent.com", "objects.githubusercontent.com",
                 "release-assets.githubusercontent.com", "github-cloud.s3.amazonaws.com"}
        need(parsed.scheme == "https" and parsed.port in (None, 443) and not parsed.username
             and not parsed.password and not parsed.fragment, "binary_download_url_invalid")
        request_headers = {"Accept-Encoding": "identity", "User-Agent": "idoly-verified-release", **(headers or {})}
        if asset_id is not None:
            need(type(asset_id) is int and asset_id > 0 and target == "https://api.github.com/repos/" + REPO
                 + "/releases/assets/" + str(asset_id) and headers is None, "asset_api_url_invalid")
            request_headers.update(Authorization="Bearer " + self.token, Accept="application/octet-stream")
            request_headers["X-GitHub-Api-Version"] = "2022-11-28"
        else:
            need(parsed.hostname in hosts and self.token not in target, "binary_download_host_invalid")
        for _ in range(4):
            try:
                return self.opener.open(Request(target, headers=request_headers), timeout=90)
            except HTTPError as error:
                location, status = error.headers.get("Location", ""), error.code
                error.close()
                need(status in (301, 302, 303, 307, 308), "binary_download_http_failed")
                redirected = urlsplit(location)
                need(redirected.scheme == "https" and redirected.port in (None, 443)
                     and not redirected.username and not redirected.password and not redirected.fragment
                     and redirected.hostname in hosts and self.token not in location,
                     "binary_download_redirect_invalid")
                target = location
                # API and LFS credentials must never follow a redirect.
                request_headers = {"Accept-Encoding": "identity", "User-Agent": "idoly-verified-release"}
        raise ReleaseError("binary_download_redirect_limit")

    def git_file(self, commit, name, maximum):
        need(is_sha(commit, 40) and "/" not in name, "companion_git_path_invalid")
        tree = self.api("/git/trees/" + commit)
        rows = tree.get("tree")
        need(tree.get("truncated") is False and type(rows) is list and len(rows) <= 100,
             "companion_git_tree_invalid")
        matches = [row for row in rows if row.get("path") == name]
        need(len(matches) == 1 and matches[0].get("type") == "blob"
             and type(matches[0].get("size")) is int and 0 < matches[0]["size"] <= maximum
             and is_sha(matches[0].get("sha"), 40), "companion_git_blob_invalid")
        wanted = matches[0]
        blob = self.api("/git/blobs/" + wanted["sha"])
        need(blob.get("sha") == wanted["sha"] and blob.get("encoding") == "base64"
             and blob.get("size") == wanted["size"] and type(blob.get("content")) is str
             and len(blob["content"]) <= 2*maximum, "companion_git_blob_invalid")
        raw = base64.b64decode("".join(blob["content"].split()), validate=True)
        need(len(raw) == wanted["size"] and hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest() == wanted["sha"],
             "companion_git_blob_sha_differs")
        return raw

    def companion(self, wanted, destination, guard):
        need(not destination.exists() and not destination.is_symlink(), "fresh_companion_path_required")
        pointer = self.git_file(wanted["publication_commit"], wanted["name"], 256)
        expected = ("version https://git-lfs.github.com/spec/v1\noid sha256:" + wanted["sha256"]
                    + "\nsize " + str(wanted["bytes"]) + "\n").encode()
        need(pointer == expected, "companion_immutable_pointer_differs")
        provenance_raw = self.git_file(wanted["publication_commit"], "RELEASE-VERIFICATION.json", 128*1024)
        provenance = decode(provenance_raw)
        record_keys = ("name", "bytes", "sha256")
        independent = provenance.get("independent_QA", {})
        need(provenance.get("source_commit") == wanted["source_commit"] and provenance.get("version") == wanted["version"]
             and provenance.get("artifacts") == [{key: wanted[key] for key in record_keys}]
             and independent.get("status") == "PASS" and independent.get("source_commit") == wanted["source_commit"]
             and all(independent.get(key) == wanted[key] for key in ("bytes", "sha256")),
             "companion_original_provenance_differs")
        body = json.dumps({"operation": "download", "transfers": ["basic"],
                          "objects": [{"oid": wanted["sha256"], "size": wanted["bytes"]}]}).encode()
        authorization = "Basic " + base64.b64encode(("x-access-token:" + self.token).encode()).decode()
        request = Request("https://github.com/" + REPO + ".git/info/lfs/objects/batch", data=body, method="POST",
                          headers={"Authorization": authorization, "Accept": "application/vnd.git-lfs+json",
                                   "Content-Type": "application/vnd.git-lfs+json"})
        with self.opener.open(request, timeout=60) as response:
            raw = response.read(MIB + 1)
            need(response.status == 200 and len(raw) <= MIB, "companion_lfs_batch_bound")
        objects = decode(raw).get("objects")
        need(type(objects) is list and len(objects) == 1 and objects[0].get("oid") == wanted["sha256"]
             and objects[0].get("size") == wanted["bytes"] and not objects[0].get("error"),
             "companion_lfs_object_differs")
        action = objects[0].get("actions", {}).get("download", {})
        headers = action.get("header", {})
        need(type(headers) is dict and len(headers) <= 16, "companion_lfs_headers_invalid")
        for key, value in headers.items():
            need(type(key) is str and re.fullmatch(r"[A-Za-z0-9-]{1,64}", key)
                 and key.lower() not in {"host", "cookie", "proxy-authorization"}
                 and type(value) is str and len(value) <= 4096 and self.token not in value
                 and all(32 <= ord(char) < 127 for char in value), "companion_lfs_headers_invalid")
        target = action.get("href")
        need(type(target) is str and 0 < len(target) <= 16000, "companion_lfs_url_invalid")
        with self.binary_response(target, headers=headers) as response, destination.open("xb") as outgoing:
            verify_binary_stream(response, wanted, guard, outgoing)
        need(digest(destination) == wanted["sha256"] and destination.stat().st_size == wanted["bytes"],
             "companion_file_sha256_differs")
        return {**wanted, "reused_unchanged": True, "new_download_verification_this_release": True,
                "original_provenance_sha256": hashlib.sha256(provenance_raw).hexdigest(),
                "immutable_pointer_verified": True, "full_download_SHA256_verified": True,
                "fresh_source_build_claimed": False, "path": str(destination)}

    def require_fresh(self):
        require_release()
        need(self.api("/releases/tags/" + TAG, absent=True) is None
             and self.api("/git/ref/tags/" + TAG, absent=True) is None, "release_or_tag_already_exists")
        releases = self.api("/releases?per_page=100")
        need(type(releases) is list and len(releases) <= 100
             and not any(row.get("tag_name") == TAG for row in releases), "release_already_exists")

    def upload_asset(self, release_id, wanted):
        need(type(release_id) is int and release_id == self.owned_release_id,
             "owned_draft_asset_upload_required")
        path = verified_file(Path(wanted["path"]).parent, {key: wanted[key] for key in ("name", "bytes", "sha256")})
        with path.open("rb") as incoming:
            request = Request("https://uploads.github.com/repos/" + REPO + "/releases/" + str(release_id)
                              + "/assets?name=" + wanted["name"], data=incoming, method="POST",
                              headers={"Authorization": "Bearer " + self.token, "Accept": "application/vnd.github+json",
                                       "Content-Type": "application/octet-stream", "Content-Length": str(wanted["bytes"]),
                                       "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "idoly-verified-release"})
            try:
                response = self.opener.open(request, timeout=120)
            except HTTPError as error:
                error.close()
                raise ReleaseError("release_asset_upload_failed") from None
            with response:
                raw = response.read(MIB + 1)
                need(response.status == 201 and len(raw) <= MIB, "release_asset_upload_response_bound")
        return validate_release_asset(decode(raw), wanted, allow_draft_url=True)

    def verify_asset(self, asset, wanted, guard):
        url = "https://api.github.com/repos/" + REPO + "/releases/assets/" + str(asset["id"])
        with self.binary_response(url, asset_id=asset["id"]) as response:
            verify_binary_stream(response, wanted, guard)

    def publish(self, source, body, binaries, guard, *, save_assets=None, before_promote=None):
        require_release()
        need(type(binaries) is list and len(binaries) == len(EXPECTED_RELEASE_ASSETS)
             and {row["name"] for row in binaries} == EXPECTED_RELEASE_ASSETS,
             "release_binary_set_differs")
        need({row.get("source_name") for row in binaries} == INPUT_RELEASE_ASSETS
             and all(release_name(row["source_name"]) == row["name"] for row in binaries),
             "release_source_name_mapping_differs")
        for row in binaries:
            verified_file(Path(row["path"]).parent, {key: row[key] for key in ("name", "bytes", "sha256")})
        self.require_fresh()
        created = self.api("/releases", method="POST", body={
            "tag_name": TAG, "target_commitish": source,
            "name": release_title(),
            "body": body, "draft": True, "prerelease": True, "make_latest": "false"})
        need(type(created) is dict and type(created.get("id")) is int and created["id"] > 0
             and created.get("tag_name") == TAG and created.get("draft") is True
             and created.get("prerelease") is True and created.get("target_commitish") == source,
             "new_draft_identity_differs")
        self.owned_release_id = created["id"]
        try:
            for row in binaries:
                guard.check()
                asset = self.upload_asset(created["id"], row)
                validate_release_asset(asset, row, allow_draft_url=True)
                self.verify_asset(asset, row, guard)
                self.asset_receipts.append({"id": asset["id"], "name": row["name"], "source_name": row["source_name"], "bytes": row["bytes"],
                    "sha256": row["sha256"], "API_digest": asset["digest"],
                    "download_url": asset["browser_download_url"], "full_API_download_SHA256_verified": True})
                if save_assets is not None:
                    save_assets(self.asset_receipts)
            validate_release_inventory(self.api("/releases/" + str(created["id"]) + "/assets?per_page=100"),
                                       binaries, self.asset_receipts, allow_draft_urls=True)
            if before_promote is not None:
                before_promote()
            guard.check()
            result = self.api("/releases/" + str(created["id"]), method="PATCH",
                              body={"draft": False, "tag_name": TAG, "target_commitish": source})
            need(result.get("id") == created["id"] and result.get("tag_name") == TAG
                 and result.get("draft") is False and result.get("prerelease") is True
                 and result.get("target_commitish") == source
                 and type(result.get("published_at")) is str
                 and result.get("html_url") == "https://github.com/" + REPO + "/releases/tag/" + TAG,
                 "published_release_identity_differs")
            tag = self.api("/git/ref/tags/" + TAG)
            need(tag.get("object", {}).get("type") == "commit"
                 and tag["object"].get("sha") == source, "published_tag_source_differs")
            final_assets = self.api("/releases/" + str(created["id"]) + "/assets?per_page=100")
            validate_release_inventory(final_assets, binaries, self.asset_receipts)
            final_by_id = {asset["id"]: asset for asset in final_assets}
            for receipt in self.asset_receipts:
                receipt["download_url"] = final_by_id[receipt["id"]]["browser_download_url"]
            if save_assets is not None:
                save_assets(self.asset_receipts)
            return {key: result[key] for key in ("id", "tag_name", "html_url", "published_at", "draft", "prerelease")}
        except BaseException:
            # Restore only this call's validated newly-created release.
            try:
                restored = self.api("/releases/" + str(created["id"]), method="PATCH", body={"draft": True})
                self.rollback_draft_restored = (restored.get("id") == created["id"]
                                                and restored.get("draft") is True)
            except BaseException:
                self.rollback_draft_restored = False
            raise


def release_title():
    require_release()
    return "아이프라 로컬 " + RELEASE_VERSION + " · 최신 데이터·계정·모시코이 복구"


def release_scope_lines():
    """Describe measured cohort facts only after the static proof is verified."""
    proof = LATEST_SERVER_DATA.load_pin()["upgrade_proof"]
    master, love = proof["original_master"], proof["love"]
    features = proof["semantic_controls"]["features"]
    checks = features["main_live"]["receipt"].get("checks", {})
    totals = []
    for before, added in (("old_cards_unchanged", "new_cards"),
                          ("old_costumes_preserved", "new_costumes"),
                          ("old_hairs_preserved", "new_hairs")):
        values = [checks.get(before), checks.get(added)] if type(checks) is dict else []
        if len(values) != 2 or not all(type(value) is int and 0 <= value <= 1000000 for value in values):
            totals = []
            break
        totals.append(sum(values))
    inventory = (" · 카드 " + str(totals[0]) + " / 의상 " + str(totals[1]) + " / 헤어 " + str(totals[2])) if totals else ""
    octo = features["octo"]["receipt"]
    platforms = octo.get("platforms", {})
    need(type(platforms) is dict and set(platforms) == {"android", "ios"}, "release_scope_proof_invalid")
    platform_text = []
    for key, label in (("android", "Android"), ("ios", "iOS")):
        row = platforms[key]
        need(type(row) is dict and all(type(row.get(name)) is int and 0 <= row[name] <= 1000000
             for name in ("revision", "model_roots", "missing_model_roots", "incomplete_dependency_closures"))
             and row["missing_model_roots"] == row["incomplete_dependency_closures"] == 0,
             "release_scope_proof_invalid")
        platform_text.append(label + " revision " + str(row["revision"]) + " / 모델 진입점 " + str(row["model_roots"]))
    images = octo.get("required_card_images")
    need(type(images) is int and 0 <= images <= 1000000, "release_scope_proof_invalid")
    adv = read_json(ROOT/"data/love-adv-proof.json")
    need(type(adv.get("story_count")) is int and adv["story_count"] == love["episodes"]
         and adv.get("missing_asset_ids") == ["love_2411_04_02"], "release_scope_proof_invalid")
    return [
        "- 최신 원본 마스터 " + master["version"] + inventory + "를 포함합니다. 원본 팩 " + str(master["pack_count"]) + "개와 한국어·영어·일본어의 일반/감상용 데이터를 같은 코호트로 검증했습니다.",
        "- 리소스 목록은 " + " · ".join(platform_text) + "입니다. 신규 카드 이미지 계열 " + str(images) + "개와 모델 의존성의 메타데이터를 대조했습니다. 이는 Unity에서 실제 모델·MV 재생을 확인했다는 의미가 아닙니다.",
        "- 모시코이(もしも君と恋をしたら) " + str(love["events"]) + "개 이벤트와 " + str(love["episodes"]) + "편의 목록·진행을 복구했습니다. 원본 ADV 자료가 없는 1편은 실행할 수 없어 나머지 " + str(love["episodes"]-1) + "편의 진행·감상 경로를 제공합니다. 서버 설정에서 이벤트별 기간을 지정하며, 설정 변경은 저장된 진행을 초기화하지 않습니다. 일반 모드와 감상 모드의 진행·재화는 분리합니다. 일부 분기 가중치는 추론 자료이며 확인되지 않은 보너스 보상은 지급하지 않습니다.",
    ]


def release_body(source, run, publication, artifacts, metrics, android_clients=(), companions=None):
    require_release()
    if companions is None:
        companions = [{**row, "source_name": row["name"], "name": release_name(row["name"])} for row in COMPANIONS]
    lines = ["# " + release_title(), "",
             "릴리즈 버전 " + RELEASE_VERSION + " · 서버 내부 버전 " + VERSION + " / build " + str(BUILD)
             + " · 통합 IPA 내부 빌드 " + IPA_VERSION, "",
             "최신 데이터, 로컬 계정 관리와 모시코이 진행을 통합한 릴리즈입니다. Android 서버·KO/JA/EN 게임 클라이언트와 통합 IPA, 총 5종을 제공합니다. Mac에서는 통합 IPA를 PlayCover로 사용합니다.", "",
             "이번 변경", "", *release_scope_lines(),
             "- 서버 설정에서 일반/감상용 계정의 생성·복제·다음 시작 계정 선택, ZIP 미리보기·가져오기·내보내기·복원점을 제공합니다. 계정의 8개 상태 테이블과 원본 프로토콜 바이트를 함께 보존하며, 교체는 대상 버전을 확인한 뒤 자동 복원점을 만듭니다. 다른 계정과 세션은 유지하고 교체 대상의 세션만 무효화합니다.",
             "- 일본판 인계 ID·인계 비밀번호 가져오기는 익명 마스터 호환 검사를 비밀번호 확인과 인계 실행 전에 수행합니다. 인증 정보는 메모리에만 두고 보관 ZIP·진단·로그에 저장하지 않습니다. 실제 공식 계정으로 인증·인계를 실행한 검증은 하지 않았습니다.",
             "- 기존 리소스 ZIP은 원본 파일의 동일성이 확인된 항목만 최신 목록에 연결합니다. 공개 데이터 교체는 중단·복구 가능한 트랜잭션으로 수행하며 로컬 계정·설정·게임 리소스 캐시는 보존합니다.",
             "- Android 실행 버튼을 상단 하나로 통일하고 진단·서버 기록을 하나로 내보냅니다. 그래픽·촬영 설정은 펼친 상태로 표시합니다. 통합 IPA도 설정을 자동 저장하고 저장이 끝난 뒤 게임을 시작합니다. 서버 인터페이스 언어는 즉시 반영하며 게임 언어 데이터는 완전 재실행 때 선택합니다.",
             "- ZIP 가져오기 사본 모드와 복사 진행·용량 표시, 파일 경로 별칭 처리를 보완했습니다. 포즈의 정원 검사는 회색 비활성 칸을 제외한 실제 활성 인원으로 계산하며 전체 명단의 ID·보유 검사는 유지합니다. 이 항목은 서버 검증 로직의 변경이며 실기기 해당 화면 재현 성공을 뜻하지 않습니다.", "",
             "| 파일 | 용도 | 다운로드 |", "| --- | --- | --- |"]
    kinds = {APK: "Android ARM64 서버 v" + VERSION, IPA: "iPhone·iPad / PlayCover 통합 서버·게임 " + IPA_VERSION,
             COMPANIONS[0]["name"]: "한국어 Android 게임 · v0.3.31 동일 바이트",
             ANDROID_LANGUAGE_CLIENTS["ja"]: "일본어 Android 게임 · 새 빌드",
             ANDROID_LANGUAGE_CLIENTS["en"]: "영어 Android 게임 · 새 빌드"}
    for row in [*artifacts, *android_clients, *companions]:
        lines.append("| " + row["name"] + " | " + kinds[row["source_name"]] + " | [받기](" + asset_download_url(row["name"]) + ") |")
    lines += ["", "설치와 시작", "",
              "- Android ARM64(Android 9 이상): 서버 APK와 원하는 게임 언어의 APK 한 개(KO/JA/EN)를 설치합니다. 서버 앱의 게임 언어도 맞춘 뒤 서버 시작 → 아이프라 실행을 누르세요.",
              "- iPhone·iPad: Unified-iOS.ipa 하나를 개인 서명해 설치합니다. 서버 메뉴에서 준비가 끝나면 게임 시작을 누르세요.",
              "- Mac / PlayCover: 같은 통합 IPA 하나를 설치합니다. 별도 Mac 서버 앱은 이번 배포에 포함하지 않습니다.",
              "통합 IPA는 자체 서버를 포함하므로 기존 별도 Mac 서버와 동시에 실행하지 마세요.", "",
              "통합 IPA는 게임 시작 전 한국어·일본어·영어 데이터를 선택합니다. Android의 KO/JA/EN 게임 APK는 같은 앱 ID·업데이트 서명을 사용하므로 동시에 설치하는 대신 원하는 언어판 하나로 교체 설치합니다. 교체 전에 게임을 완전히 종료하고 서버의 게임 언어도 맞춰 주세요. 번역 자료가 없는 문구·이미지는 원본을 유지합니다.",
              "게임 중 안전 영역 오른쪽 위를 한 손가락으로 2초 누르면 넓어진 영역에서 서버 메뉴가 열립니다. 받은 리소스가 없으면 인터넷으로 자동 다운로드하며, 완전 오프라인 사용은 필요한 캐시를 준비한 뒤 가능합니다.",
              "동일 설치판 업데이트는 기존 계정·설정·받은 자료를 유지합니다. Sideloadly와 LiveContainer는 서로 다른 컨테이너이므로 자료를 자동 공유하지 않습니다.", "",
              "사용자는 Sideloadly 설치판의 ZIP 가져오기와 LiveContainer에서 Fix File Picker를 켠 파일 선택을 확인했습니다. LiveContainer의 이 설정은 파일 선택 문제의 직접 우회이며, 최신 " + IPA_VERSION + "의 실기기 ZIP 가져오기·진행 표시는 아직 재확인이 필요합니다.",
              "Simulator의 파일 선택기 표시·취소와 ZIP 내보내기→가져오기 검사는 실제 Files 앱 탭 조작, LiveContainer 제공자의 실제 파일 복사 성공, Unity 게임 렌더링 검사를 대신하지 않습니다.", "",
              "검증 범위", "",
              "게시 파이프라인은 전체 코드 검사와 성능 검사, Android x86_64 에뮬레이터 서버 UI·암호화 통신, JA/EN APK 패키징, Apple SDK 통합 IPA 빌드를 필수로 판정합니다. iOS는 같은 저장소의 KO→EN→JA→EN→KO 재실행, ZIP 왕복과 계정 8개 테이블의 보존·복원도 검사합니다.",
              "새 JA/EN APK는 서명·16KiB 정렬·내장 UI 언어·폰트·멤버 목록의 패키징 검사를 포함합니다. 실제 Android ARM64 기기 및 이번 IPA의 PlayCover·iPhone·iPad 게임 재확인은 별도 대상입니다.",
              "원본 Actions ZIP 전체 SHA-256과 새 서버 APK·통합 IPA 2파일의 LFS 전체 재다운로드 SHA-256을 확인합니다. 재사용하는 한국어 APK도 고정된 원래 게시 커밋의 출처·전체 SHA-256을 다시 대조합니다. 공개 전 이 릴리즈의 5개 Assets를 각각 GitHub API에서 전체 다운로드해 SHA-256과 파일 목록을 확인해야 합니다.",
              "[Actions 검증](https://github.com/" + REPO + "/actions/runs/" + str(run) + ") · 서버·통합 IPA·JA/EN APK 빌드 소스 " + source,
              "개별 Where 예외의 원인과 NPC의 MV 출연은 이번 배포의 해결 범위로 주장하지 않습니다.", "",
              "한국어 Android 게임 APK는 검증된 v0.3.31 파일을 그대로 재사용합니다:"]
    for row in companions:
        lines.append("- " + row["name"] + " · 원래 파일 " + row["source_name"] + " · v" + row["version"] + " · 소스 " + row["source_commit"]
                     + " · 원래 게시 " + row["publication_commit"] + " · 이번 릴리즈에서 재제작하지 않았습니다.")
    lines += ["", "새 서버 APK·통합 IPA 2파일의 불변 LFS 대체 주소:"]
    for row in artifacts:
        lines.append("- [" + row["name"] + "](https://github.com/" + REPO + "/raw/" + publication["commit"] + "/" + row["name"] + ")")
    lines += ["", "기존 서버 최적화 측정 범위를 유지합니다. 진단 수치는 합성 기록이 있는 상태 조회이며 전체 게임 FPS·기기 시작 시간 수치가 아닙니다.",
              "", "진단 조회 측정: " + json.dumps(metrics["diagnostics"], ensure_ascii=False, sort_keys=True),
              "", "공개 번역 자료 시작 검사: " + json.dumps(metrics["translation"], ensure_ascii=False, sort_keys=True),
              "", "SHA-256:"]
    for row in [*artifacts, *android_clients, *companions]:
        lines.append("- " + row["sha256"] + "  " + row["name"] + " · " + str(row["bytes"]) + " bytes")
    return "\n".join(lines) + "\n"


def copy_metadata(directories, output):
    inventory, total = {}, 0
    for role, directory in directories.items():
        paths = list(directory.rglob("*.json"))
        junit = directory / "preference-contracts.xml"
        if role == "portable" and junit.exists():
            paths.append(junit)
        for path in sorted(paths):
            need(path.is_file() and not path.is_symlink() and 0 < path.stat().st_size <= MAX_JSON,
                 "proof_metadata_file_bound")
            total += path.stat().st_size
            need(total <= MAX_PROOF-MIB, "proof_bundle_bound")
            target = output / role / path.relative_to(directory)
            target.parent.mkdir(parents=True, exist_ok=True)
            with path.open("rb") as incoming, target.open("xb") as outgoing:
                shutil.copyfileobj(incoming, outgoing, CHUNK)
            inventory[str(target.relative_to(output))] = {"bytes": target.stat().st_size, "sha256": digest(target)}
    return inventory


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-version", required=True, help="YYYY.MM.DD.N calendar release version")
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    configure_release(args.release_version)
    os.umask(0o077)
    need(is_sha(args.source_commit, 40) and type(args.run_id) is int and args.run_id > 0
         and args.source_commit == os.environ.get("GITHUB_SHA")
         and str(args.run_id) == os.environ.get("GITHUB_RUN_ID")
         and sys.platform.startswith("linux") and __debug__, "remote_run_identity_required")
    need(subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip() == args.source_commit,
         "checkout_source_differs")
    need(subprocess.run(["git", "diff", "--quiet"], cwd=ROOT).returncode == 0, "checkout_dirty")
    runner = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)
    for path in (args.work, args.output):
        need(path.is_absolute() and path.parent.resolve(strict=True) == runner
             and not path.exists() and not path.is_symlink(), "fresh_owned_runner_directory_required")
    need(args.work != args.output, "publication_directories_overlap")
    delivery = module("optimized_release_ios_delivery", ROOT/"ios-unified/delivery.py")
    guard = delivery.Guard()
    need(shutil.disk_usage(runner).free >= 6*1024*MIB, "publication_entry_disk_floor")
    args.work.mkdir(mode=0o700)
    args.output.mkdir(mode=0o700)
    state = {"schema": 1, "status": "RUNNING", "source_commit": args.source_commit, "run_id": args.run_id,
             "version": RELEASE_VERSION, "release_version": RELEASE_VERSION, "server_version": VERSION,
             "build_number": BUILD, "ipa_version": IPA_VERSION, "tag": TAG,
             "release_name_mapping": dict(RELEASE_NAMES),
             "all_qa_passed": False, "release_published": False, "release_assets_uploaded": False}
    state_path = args.output/"release-proof.json"
    write_json(state_path, state)
    try:
        token = os.environ["GH_TOKEN"]
        github = GitHub(token, delivery.OPENER)
        github.require_fresh()
        build = github.api("/actions/runs/" + str(args.run_id))
        jobs = github.api("/actions/runs/" + str(args.run_id) + "/jobs?filter=latest&per_page=100")
        artifacts = github.api("/actions/runs/" + str(args.run_id) + "/artifacts?per_page=100")
        bindings = validate_run(build, jobs, artifacts, args.source_commit, args.run_id)
        state["input_artifacts"] = bindings
        write_json(state_path, state)
        directories, inventories = {}, {}
        for role, binding in bindings.items():
            guard.check()
            archive = args.work/(role + ".zip")
            delivery.fetch_archive(binding, token, archive, guard)
            directory = args.work/role
            if role == "ios-unified":
                directory.mkdir(mode=0o700)
                inventory = delivery.extract_archive(archive, directory, binding, guard)
            else:
                inventory = extract_generic(archive, directory, role, guard)
            archive.unlink()
            directories[role], inventories[role] = directory, inventory
        validate_portable(read_json(directories["portable"]/"portable-report.json"), args.source_commit, directories["portable"])
        metrics = validate_performance(directories["performance"], args.source_commit)
        binaries = []
        for platform in ("android",):
            report = validate_platform(read_json(directories[platform]/"platform-report.json"), platform, args.source_commit)
            binaries.append(validate_platform_files(directories[platform], report, guard))
        ios_proof = args.work/"ios-verified"
        ios_proof.mkdir(mode=0o700)
        ipa_binding = bindings["ios-unified"]
        ipa_manifest, _identity = delivery.verify_members(directories["ios-unified"], ios_proof, args.source_commit,
                                                         args.run_id, ipa_binding["artifact_id"], guard)
        binaries += ipa_manifest["artifacts"]
        android_client_binaries = validate_android_clients(directories["android-clients"], args.source_commit, args.run_id)
        need({row["name"] for row in binaries} == {APK, IPA} and len(binaries) == 2, "primary_binary_set_differs")
        for row in binaries:
            verified_file(Path(row["path"]).parent, {key: row[key] for key in ("name", "bytes", "sha256")})
        binaries = stage_release_binaries(binaries, args.work/"release-platforms", guard)
        android_client_binaries = stage_release_binaries(android_client_binaries, args.work/"release-android-clients", guard)
        manifest = {"schema": 1, "source_commit": args.source_commit, "artifacts": binaries,
                    "release_version": RELEASE_VERSION, "server_version": VERSION, "ipa_version": IPA_VERSION,
                    "validation": {"Actions_run": args.run_id, "all_qa_passed": True,
                                   "Android_ARM64_physical": "NOT_TESTED", "PlayCover_and_iPhone_iPad": "NOT_TESTED"}}
        manifest_path = args.work/"manifest.json"
        write_json(manifest_path, manifest)
        pre_readme = args.work/"README.md"
        pre_readme.write_text("아이프라 로컬 " + RELEASE_VERSION + "\n\nSource: " + args.source_commit
                              + "\nActions: https://github.com/" + REPO + "/actions/runs/" + str(args.run_id)
                              + "\nTwo verified native binaries. Physical Android ARM64 and IPA gameplay retesting pending.\n",
                              encoding="utf-8")
        state.update(all_qa_passed=True, whole_API_archive_digests_verified=True, performance=metrics,
                     artifacts=[{key: row[key] for key in ("name", "source_name", "bytes", "sha256")} for row in binaries],
                     android_clients=[{key: value for key, value in row.items() if key != "path"}
                                      for row in android_client_binaries],
                     android_clients_packaging_QA_verified=True, android_clients_runtime_device_tested=False,
                     companions=[{**row, "source_name": row["name"], "name": release_name(row["name"]),
                                  "reused_unchanged": True, "new_download_verification_this_release": False}
                                 for row in COMPANIONS])
        write_json(state_path, state)
        branch = "downloads/optimized-v" + RELEASE_VERSION + "-source-" + args.source_commit
        publish_dir = args.work/"lfs-publication"
        publish_dir.mkdir(mode=0o700)
        publication = delivery.publish(manifest_path, pre_readme, branch, publish_dir, guard)
        need(publication.get("branch") == branch and publication.get("source_commit") == args.source_commit
             and is_sha(publication.get("commit"), 40), "lfs_publication_identity_differs")
        receipts = publication.get("artifacts")
        need(type(receipts) is list and len(receipts) == 2 and {row.get("name") for row in receipts} == {release_name(name) for name in (APK, IPA)},
             "lfs_receipt_set_differs")
        for row in state["artifacts"]:
            matched = [item for item in receipts if item.get("name") == row["name"]]
            need(len(matched) == 1 and matched[0].get("complete_download_verified") is True
                 and all(type(matched[0].get(key)) is type(row[key]) and matched[0][key] == row[key]
                         for key in ("name", "bytes", "sha256")),
                 "full_remote_binary_sha256_not_verified")
        write_json(args.output/"publication.json", publication)
        companion_directory = args.work/"companions"
        companion_directory.mkdir(mode=0o700)
        companion_binaries = []
        for wanted in COMPANIONS:
            guard.check()
            companion_binaries.append(github.companion(wanted, companion_directory/wanted["name"], guard))
        companion_binaries = stage_release_binaries(companion_binaries, args.work/"release-companions", guard)
        state["companions"] = [{key: value for key, value in row.items() if key != "path"}
                               for row in companion_binaries]
        state["all_companion_source_and_download_SHA256_verified"] = True
        write_json(args.output/"companion-provenance.json", {"schema": 1, "companions": state["companions"]})
        write_json(state_path, state)
        body = release_body(args.source_commit, args.run_id, publication, state["artifacts"], metrics,
                            android_clients=state["android_clients"], companions=state["companions"])
        (args.output/"RELEASE.md").write_text(body, encoding="utf-8")
        metadata_files = copy_metadata(directories, args.output)
        state.update(status="READY_TO_PUBLISH", branch=branch, publication_commit=publication["commit"],
                     full_remote_download_SHA256_verified=True, report_files=metadata_files,
                     resources=guard.report())
        write_json(state_path, state)
        # Reserve bounded room for only the final release identity and URLs.
        need(sum(path.stat().st_size for path in args.output.rglob("*") if path.is_file()) + 128*1024 <= MAX_PROOF,
             "proof_prepublication_bundle_bound")
        guard.check()
        # Re-read latest attempt's successful job gates immediately before publishing.
        validate_run(github.api("/actions/runs/" + str(args.run_id)),
                     github.api("/actions/runs/" + str(args.run_id) + "/jobs?filter=latest&per_page=100"),
                     github.api("/actions/runs/" + str(args.run_id) + "/artifacts?per_page=100"),
                     args.source_commit, args.run_id)
        def save_assets(receipts):
            state["release_asset_receipts"] = [dict(row) for row in receipts]
            state["release_assets_uploaded"] = len(receipts) == len(EXPECTED_RELEASE_ASSETS)
            write_json(state_path, state)

        def before_promote():
            validate_run(github.api("/actions/runs/" + str(args.run_id)),
                         github.api("/actions/runs/" + str(args.run_id) + "/jobs?filter=latest&per_page=100"),
                         github.api("/actions/runs/" + str(args.run_id) + "/artifacts?per_page=100"),
                         args.source_commit, args.run_id)

        release = github.publish(args.source_commit, body, binaries + android_client_binaries + companion_binaries, guard,
                                 save_assets=save_assets, before_promote=before_promote)
        state.update(status="PASS_PUBLISHED", release_published=True, release=release,
                     branch=branch, publication_commit=publication["commit"],
                     full_remote_download_SHA256_verified=True, report_files=metadata_files,
                     full_release_asset_API_SHA256_verified=True, release_assets_uploaded=True,
                     release_asset_receipts=github.asset_receipts, resources=guard.report())
        for row in state["artifacts"]:
            row["immutable_download_url"] = "https://github.com/" + REPO + "/raw/" + publication["commit"] + "/" + row["name"]
            row["download_url"] = asset_download_url(row["name"])
        for row in state["companions"]:
            row["download_url"] = asset_download_url(row["name"])
        for row in state["android_clients"]:
            row["download_url"] = asset_download_url(row["name"])
        write_json(state_path, state)
        print(json.dumps({"status": state["status"], "release": release["html_url"],
                          "artifacts": state["artifacts"], "companions": state["companions"],
                          "android_clients": state["android_clients"],
                          "release_asset_receipts": state["release_asset_receipts"]}, sort_keys=True))
        return 0
    except BaseException as error:
        state.update(status="FAIL", error_type=type(error).__name__, resources=guard.report())
        if "github" in locals() and github.owned_release_id is not None:
            if github.rollback_draft_restored is None:
                # A failure writing the final small receipt is also fail-closed.
                try:
                    restored = github.api("/releases/" + str(github.owned_release_id),
                                          method="PATCH", body={"draft": True})
                    github.rollback_draft_restored = (restored.get("id") == github.owned_release_id
                                                       and restored.get("draft") is True)
                except BaseException:
                    github.rollback_draft_restored = False
            state["owned_release_id"] = github.owned_release_id
            state["rollback_draft_restored"] = github.rollback_draft_restored
            state["release_published"] = False if github.rollback_draft_restored is True else None
        if isinstance(error, ReleaseError):
            state["error_code"] = str(error)
        write_json(state_path, state)
        raise SystemExit("Optimization release stopped; sanitized proof saved") from None


if __name__ == "__main__":
    raise SystemExit(main())
