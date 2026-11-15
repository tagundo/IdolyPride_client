#!/usr/bin/env python3
"""Publish one source-bound, fully verified optimization release on Actions.

This tool downloads binaries only on a remote Linux runner. Its output folder
contains bounded metadata only; it never replaces an existing release or tag.
"""
from __future__ import annotations

import argparse
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
from urllib.request import Request
from zipfile import ZipFile, ZIP_STORED, ZIP_DEFLATED
import zlib

ROOT = Path(__file__).resolve().parents[1]
REPO = "tagundo/IdolyPride_client"
VERSION, BUILD, IPA_VERSION = "0.3.34", 51, "156.9114"
TAG = "local-server-v" + VERSION
BASELINE = "50e349f4db6db0d3122bdc09c3b06307145f814f"
MIB, CHUNK = 1024 * 1024, 128 * 1024
MAX_JSON, MAX_PROOF = 8 * MIB, 8 * MIB
IPA = "IdolyPride-6.1.1-Unified-iOS.ipa"
APK = "IdolyPride-Local-Server-Android.apk"
QA_APK = "IdolyPride-Local-Server-Android-x86_64-QA.apk"
MAC = "IdolyPride-Local-Server-macOS-arm64.app.zip"
JOBS = ("portable", "performance", "android", "macos", "ios-unified")
PREFIXES = {name: "optimized-release-" + name + "-" for name in JOBS[:-1]}
PREFIXES["ios-unified"] = "ios-unified-prototype-"
ARCHIVE_LIMITS = {"portable": 32*MIB, "performance": 32*MIB,
                  "android": 900*MIB, "macos": 640*MIB, "ios-unified": 768*MIB}
BINARY_LIMITS = {APK: 384*MIB, QA_APK: 384*MIB, MAC: 600*MIB, IPA: 600*MIB}
COMMON_SOURCES = ("src/idoly_local/app_runtime.py", "src/idoly_local/diagnostics.py",
                  "src/idoly_local/resource_translation_runtime.py")
TRANSLATION_SOURCES = ("public_payload.py", "bundled_translations.py", "resource_translation.py",
                       "resource_translation_runtime.py", "octo_manifest.py", "octo_runtime.py")
DATA_PIN = {"bytes": 191343014, "sha256": "37dbf0fb9bac5d860991753d2e41ff0c269684bfca673ba41e1bcb897651c223"}
TRANSLATION_PINS = {
    "android": {"bytes": 125709184, "sha256": "22c166ffc3bbbc9e38739cea21fbfd7a87436a166ed56cdb7ee650acfc222dec"},
    "ios": {"bytes": 125717042, "sha256": "987fab065fbf791b37b9afe71c53979dc2186e711cde338c89ebe8e0ff905b72"},
}
CERTIFICATE = "ff5b25120ac58f5b82861320925448663a5ac3f812e93736cad1de6a6ac29e51"
COMMON_FLAGS = ("source_bound", "payload_sha256_verified", "translations_sha256_verified",
                "live_engine_included", "live_engine_source_built")
ANDROID_FLAGS = ("apk_signature_verified", "apk_alignment_verified", "package_version_verified",
                 "development_certificate_verified", "x86_emulator_runtime_passed")
MAC_FLAGS = ("codesign_strict_verified", "bundled_engine_tested", "native_gui_start_stop_tested")
COMPANIONS = (
    {"name": "IdolyPride-Local-Graphics-Diagnostic-Android-arm64-ko.apk", "bytes": 165128829,
     "sha256": "44f233290128a97f78940e3167c9486dbe39550090efcb90f7dc403430e94b9e",
     "source_commit": "cba4b5a272d4e7033ec5a18223f737c37a749d8f",
     "publication_commit": "3b2c73b51931bb7be031c37c9d55297505fb88e1", "version": "0.3.31"},
    {"name": "IdolyPride-6.1.1-Local-PlayCover-ko.ipa", "bytes": 150132823,
     "sha256": "d872903da8d79bf4a255888f9d5a952198ff47268cfcf7c35e8ac437b56e72a1",
     "source_commit": "cba4b5a272d4e7033ec5a18223f737c37a749d8f",
     "publication_commit": "7fcc9f8661b5158cf66d93e9c307607db2c2ee43", "version": "0.3.31"},
)


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
    binaries = {APK, QA_APK} if role == "android" else {MAC} if role == "macos" else set()
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
                {"platform-report.json", MAC} if role == "macos" else
                {"portable-report.json"} if role == "portable" else
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
    pin(contracts.get("input"), DATA_PIN)
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
    expected = {"baseline": {"poll": 1, "explicit_export": 2},
                "candidate": {"poll": 0, "explicit_export": 1}}
    need(report.get("expected_history_deepcopy_calls") == expected, "diagnostics_copy_policy_differs")
    hashes = report.get("identical_outputs")
    need(type(hashes) is dict and set(hashes) == {"summary_sha256", "poll_sha256", "export_sha256"}
         and all(is_sha(value) for value in hashes.values()), "diagnostics_semantics_missing")
    runs = report.get("runs")
    need(type(runs) is dict and set(runs) == {"baseline", "candidate"}, "diagnostics_run_set")
    for name, group in runs.items():
        need(type(group) is list and len(group) == report["repeats"], "diagnostics_run_count")
        for row in group:
            need(type(row) is dict and row.get("history_deepcopy_calls") == expected[name]
                 and row.get("synthetic_events") == 200 and row.get("frames_per_event") == 16
                 and row.get("poll_contains_events") is False
                 and row.get("stored_events") == row.get("default_full_events") == row.get("exported_events") == 200
                 and all(row.get(key) == value for key, value in hashes.items())
                 and all(number(row.get(key), 10**12, positive=True) for key in
                         ("wall_microseconds_per_poll", "cpu_microseconds_per_poll")),
                 "diagnostics_run_semantics_differs")
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
    return {key: report[key] for key in ("median", "median_speedup", "expected_history_deepcopy_calls")}


def validate_translation_benchmark(report, source):
    need(type(report) is dict and type(report.get("schema")) is int and report["schema"] == 1 and report.get("status") == "PASS"
         and report.get("same_semantics") is True and report.get("protobuf") == "python"
         and report.get("platform") == "ios" and report.get("sequence") == ["ja", "ko", "en", "ko"]
         and report.get("baseline_revision_expected") == BASELINE
         and type(report.get("runs_per_source")) is int and 3 <= report["runs_per_source"] <= 5,
         "translation_benchmark_identity")
    inputs = report.get("inputs", {})
    pin(inputs.get("server_data"), DATA_PIN)
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
                 "main_live_cached_no_grant")), "android_runtime_qa_not_passed")
    else:
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


class GitHub:
    def __init__(self, token, opener):
        self.token, self.opener = token, opener
        self.owned_release_id, self.rollback_draft_restored = None, None

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
            raise ReleaseError("github_api_request_failed") from None
        with response:
            raw = response.read(2*MIB + 1)
            need(response.status in (200, 201) and len(raw) <= 2*MIB, "github_api_response_bound")
        return decode(raw)

    def require_fresh(self):
        need(self.api("/releases/tags/" + TAG, absent=True) is None
             and self.api("/git/ref/tags/" + TAG, absent=True) is None, "release_or_tag_already_exists")
        releases = self.api("/releases?per_page=100")
        need(type(releases) is list and len(releases) <= 100
             and not any(row.get("tag_name") == TAG for row in releases), "release_already_exists")

    def publish(self, source, body):
        self.require_fresh()
        created = self.api("/releases", method="POST", body={
            "tag_name": TAG, "target_commitish": source, "name": "아이프라 로컬 v" + VERSION + " · 프로필·포토 편집과 목록 복구",
            "body": body, "draft": True, "prerelease": True, "make_latest": "false"})
        need(type(created) is dict and type(created.get("id")) is int and created["id"] > 0
             and created.get("tag_name") == TAG and created.get("draft") is True
             and created.get("prerelease") is True and created.get("target_commitish") == source,
             "new_draft_identity_differs")
        self.owned_release_id = created["id"]
        try:
            result = self.api("/releases/" + str(created["id"]), method="PATCH", body={"draft": False})
            need(result.get("id") == created["id"] and result.get("tag_name") == TAG
                 and result.get("draft") is False and result.get("prerelease") is True
                 and result.get("target_commitish") == source
                 and type(result.get("published_at")) is str
                 and result.get("html_url") == "https://github.com/" + REPO + "/releases/tag/" + TAG,
                 "published_release_identity_differs")
            tag = self.api("/git/ref/tags/" + TAG)
            need(tag.get("object", {}).get("type") == "commit"
                 and tag["object"].get("sha") == source, "published_tag_source_differs")
            return {key: result[key] for key in ("id", "tag_name", "html_url", "published_at", "draft", "prerelease")}
        except BaseException:
            # Only this call's validated, newly-created release can be restored.
            # Never edit a pre-existing release or move any existing tag.
            try:
                restored = self.api("/releases/" + str(created["id"]), method="PATCH", body={"draft": True})
                self.rollback_draft_restored = (restored.get("id") == created["id"]
                                                and restored.get("draft") is True)
            except BaseException:
                self.rollback_draft_restored = False
            raise


def release_body(source, run, publication, artifacts, metrics):
    lines = ["# 아이프라 로컬 v" + VERSION, "",
             "Android 서버 APK, iPhone·iPad 통합 IPA, Apple Silicon Mac 서버 앱을 같은 소스로 제작했습니다.",
             "보유 버디 카드·프로필 장식·기본/포토/카드 배경·카드 이미지 선택과 포토 잠금/해제를 복구했습니다.",
             "같은 포토 전환 요청은 재시도·재시작·동시 요청에도 한 번만 반영합니다. 저장된 일일·주간·일반 미션과 일일·콘테스트·타워의 목록/이력을 조회하며 새 미션·보상·일일/타워 전투는 생성하지 않습니다.",
             "개별 Where 예외의 원인 해결 여부는 재현 기록으로 확인해야 합니다. NPC의 MV 출연은 별도 조사 단계입니다.",
             "계정·설정·받은 리소스는 기존 저장소를 유지합니다. 실제 게임 FPS 향상을 측정한 릴리즈는 아닙니다.", "",
             "| 파일 | 용도 | 다운로드 |", "| --- | --- | --- |"]
    kinds = {APK: "Android ARM64 서버", IPA: "iPhone·iPad 통합 서버·게임", MAC: "Apple Silicon Mac 서버"}
    for row in artifacts:
        url = "https://github.com/" + REPO + "/raw/" + publication["commit"] + "/" + row["name"]
        lines.append("| " + row["name"] + " | " + kinds[row["name"]] + " | [받기](" + url + ") |")
    lines += ["", "Android는 서버 APK와 아래 게임 APK를 함께 사용합니다. Mac 서버 앱은 아래 별도 PlayCover IPA와 사용합니다.",
              "통합 IPA는 자체 서버를 포함하므로 별도 Mac 서버와 동시에 실행하지 마세요.", ""]
    for row in COMPANIONS:
        url = "https://github.com/" + REPO + "/raw/" + row["publication_commit"] + "/" + row["name"]
        lines.append("- [기존 한국어 게임 " + row["name"] + "](" + url + ") · v" + row["version"]
                     + " · 기존 소스 " + row["source_commit"] + " · 이번 릴리즈에서 재제작하지 않았습니다.")
    lines += ["", "검증: 전체 코드 검사, Android x86_64 에뮬레이터 서버 UI·암호화 통신, 실제 Mac 앱의 시작·중지와 코드 서명,",
              "실제 Apple SDK IPA 빌드와 같은 저장소의 KO→EN→JA→EN→KO 재실행·파일 해시·연결 중단 검사를 통과했습니다.",
              "실제 Android ARM64 기기 및 이번 IPA의 PlayCover·iPhone·iPad 게임 재확인은 별도 대상입니다.",
              "", "원본 Actions ZIP 전체 SHA-256과 게시한 파일 전체 재다운로드 SHA-256을 검증했습니다.",
              "[Actions 검증](https://github.com/" + REPO + "/actions/runs/" + str(run) + ") · 소스 " + source,
              "", "측정 수치와 범위는 아래 벤치마크 결과를 따릅니다. 진단 수치는 합성 기록이 있는 서버 상태 조회이며 전체 게임 성능 수치가 아닙니다.",
              "", "진단 조회 측정: " + json.dumps(metrics["diagnostics"], ensure_ascii=False, sort_keys=True),
              "", "공개 번역 자료 시작 검사: " + json.dumps(metrics["translation"], ensure_ascii=False, sort_keys=True),
              "", "SHA-256:"]
    for row in artifacts:
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
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
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
             "version": VERSION, "ipa_version": IPA_VERSION, "tag": TAG,
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
        for platform in ("android", "macos"):
            report = validate_platform(read_json(directories[platform]/"platform-report.json"), platform, args.source_commit)
            binaries.append(validate_platform_files(directories[platform], report, guard))
        ios_proof = args.work/"ios-verified"
        ios_proof.mkdir(mode=0o700)
        ipa_binding = bindings["ios-unified"]
        ipa_manifest, _identity = delivery.verify_members(directories["ios-unified"], ios_proof, args.source_commit,
                                                         args.run_id, ipa_binding["artifact_id"], guard)
        binaries += ipa_manifest["artifacts"]
        need({row["name"] for row in binaries} == {APK, MAC, IPA} and len(binaries) == 3, "primary_binary_set_differs")
        for row in binaries:
            verified_file(Path(row["path"]).parent, {key: row[key] for key in ("name", "bytes", "sha256")})
        manifest = {"schema": 1, "source_commit": args.source_commit, "artifacts": binaries,
                    "validation": {"Actions_run": args.run_id, "all_qa_passed": True,
                                   "Android_ARM64_physical": "NOT_TESTED", "PlayCover_and_iPhone_iPad": "NOT_TESTED"}}
        manifest_path = args.work/"manifest.json"
        write_json(manifest_path, manifest)
        pre_readme = args.work/"README.md"
        pre_readme.write_text("아이프라 로컬 v" + VERSION + "\n\nSource: " + args.source_commit
                              + "\nActions: https://github.com/" + REPO + "/actions/runs/" + str(args.run_id)
                              + "\nThree verified platform binaries. Physical Android ARM64 and IPA gameplay retesting pending.\n",
                              encoding="utf-8")
        state.update(all_qa_passed=True, whole_API_archive_digests_verified=True, performance=metrics,
                     artifacts=[{key: row[key] for key in ("name", "bytes", "sha256")} for row in binaries],
                     companions=[{**row, "reused_unchanged": True, "new_download_verification_this_release": False}
                                 for row in COMPANIONS])
        write_json(state_path, state)
        branch = "downloads/optimized-v" + VERSION + "-source-" + args.source_commit
        publish_dir = args.work/"lfs-publication"
        publish_dir.mkdir(mode=0o700)
        publication = delivery.publish(manifest_path, pre_readme, branch, publish_dir, guard)
        need(publication.get("branch") == branch and publication.get("source_commit") == args.source_commit
             and is_sha(publication.get("commit"), 40), "lfs_publication_identity_differs")
        receipts = publication.get("artifacts")
        need(type(receipts) is list and len(receipts) == 3 and {row.get("name") for row in receipts} == {APK, MAC, IPA},
             "lfs_receipt_set_differs")
        for row in state["artifacts"]:
            matched = [item for item in receipts if item.get("name") == row["name"]]
            need(len(matched) == 1 and matched[0].get("complete_download_verified") is True
                 and all(type(matched[0].get(key)) is type(value) and matched[0][key] == value for key, value in row.items()),
                 "full_remote_binary_sha256_not_verified")
        write_json(args.output/"publication.json", publication)
        body = release_body(args.source_commit, args.run_id, publication, state["artifacts"], metrics)
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
        release = github.publish(args.source_commit, body)
        state.update(status="PASS_PUBLISHED", release_published=True, release=release,
                     branch=branch, publication_commit=publication["commit"],
                     full_remote_download_SHA256_verified=True, report_files=metadata_files,
                     resources=guard.report())
        for row in state["artifacts"]:
            row["download_url"] = "https://github.com/" + REPO + "/raw/" + publication["commit"] + "/" + row["name"]
        write_json(state_path, state)
        print(json.dumps({"status": state["status"], "release": release["html_url"],
                          "artifacts": state["artifacts"]}, sort_keys=True))
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
