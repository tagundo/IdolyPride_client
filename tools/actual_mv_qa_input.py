"""Bind a QA observer copy to the exact current unified producer and Git input.

This accepts the normal source-built unified client only. It does not relax the
older diagnostic-AES input profile or infer runtime success from provenance.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
from zipfile import ZipFile

if __package__:
    from . import package_android_unified as unified
else:
    import package_android_unified as unified

MAX_REPORT = 2 * 1024 * 1024
HEX40 = re.compile(r"[0-9a-f]{40}")
HEX64 = re.compile(r"[0-9a-f]{64}")
AES = "lib/arm64-v8a/libFastAES.so"
UNITY = "lib/arm64-v8a/libunity.so"
ORIGINAL_AES = "f8f64ab5424b6f692464e23cf47af9d399c4072b700c196e7b321e670b93fcc4"
ORIGINAL_UNITY = "c36ea39e5040fbcd0577f7c49d08e149e2e7dc62449d90aadce761118a816c85"


def need(value, code):
    if not value:
        raise ValueError(code)


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def report_metadata(report, commit, apk_sha, apk_bytes, source_blobs):
    """Pure report checks; the caller independently supplies current Git bytes."""
    need(type(commit) is str and HEX40.fullmatch(commit), "current_qa_source_commit_required")
    need(type(apk_sha) is str and HEX64.fullmatch(apk_sha), "current_qa_apk_digest_required")
    need(type(apk_bytes) is int and 0 < apk_bytes <= 1024 * 1024 * 1024, "current_qa_apk_size_invalid")
    need(type(report) is dict and type(report.get("schema")) is int and report.get("schema") == 1
         and report.get("prototype") is True and report.get("release_eligible") is False
         and report.get("source_commit") == commit and report.get("working_tree_snapshot") is False
         and report.get("compiled_source_unchanged_during_build") is True
         and report.get("public_apk_inputs_unchanged") is True
         and report.get("apk_sha256") == apk_sha and type(report.get("apk_bytes")) is int
         and report.get("apk_bytes") == apk_bytes,
         "current_qa_producer_identity_differs")
    need(report.get("inputs", {}).get("client_sha256") == unified.CLIENT_SHA256
         and report.get("inputs", {}).get("server_sha256") == unified.SERVER_SHA256
         and report.get("signed_certificate_sha256") == unified.CERTIFICATE,
         "current_qa_producer_inputs_differ")
    rows = report.get("source_files")
    need(type(rows) is list and len(rows) == len(source_blobs) and 1 <= len(rows) <= 1024,
         "current_qa_source_closure_differs")
    wanted = {name: {"path": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
              for name, raw in source_blobs.items()}
    seen = set()
    for row in rows:
        need(type(row) is dict and type(row.get("path")) is str and type(row.get("bytes")) is int
             and type(row.get("sha256")) is str and row["path"] not in seen
             and row == wanted.get(row["path"]), "current_qa_source_closure_differs")
        seen.add(row["path"])
    need(seen == wanted.keys(), "current_qa_source_closure_differs")
    preservation = report.get("preservation", {})
    need(preservation.get("original_dex_and_sdk_native_unchanged") is True
         and preservation.get("resources_arsc_unchanged") is True
         and preservation.get("owned_presentation_addon_replaced") is True,
         "current_qa_original_members_not_preserved")
    native = report.get("native_addon_build")
    need(type(native) is dict and native.get("source_commit") == commit
         and native.get("abi") == "arm64-v8a" and native.get("source_unchanged_during_build") is True
         and type(native.get("source_sha256")) is dict and 2 <= len(native["source_sha256"]) <= 64,
         "current_qa_native_receipt_differs")
    return native


def validate_current(source, report_path, commit, apk_sha, root):
    root, source, report_path = Path(root).resolve(), Path(source), Path(report_path)
    need(report_path.is_file() and not report_path.is_symlink()
         and 0 < report_path.stat().st_size <= MAX_REPORT, "current_qa_report_file_invalid")
    # The production builder fixes the complete compiled source set; do not
    # accept a caller-authored subset that happens to contain two familiar files.
    blobs, _, dirty = unified.source_snapshot(root, commit, False)
    need(dirty is False, "current_qa_dirty_source")
    actual = sha(source)
    need(actual == apk_sha, "current_qa_apk_digest_differs")
    report = json.loads(report_path.read_bytes())
    native = report_metadata(report, commit, actual, source.stat().st_size, blobs)
    expected_native = {p.relative_to(root).as_posix()
                       for p in (root / "client-presentation/native").iterdir()
                       if p.suffix in (".cpp", ".hpp", ".h", ".py", ".json")}
    expected_native.add("android-diagnostics/native/build_native.py")
    need(set(native["source_sha256"]) == expected_native, "current_qa_native_source_closure_differs")
    for name, digest in native["source_sha256"].items():
        need(type(digest) is str and HEX64.fullmatch(digest), "current_qa_native_source_digest_invalid")
        original = subprocess.check_output(["git", "-C", str(root), "show", commit + ":" + name], timeout=10)
        need(hashlib.sha256(original).hexdigest() == digest and sha(root / name) == digest,
             "current_qa_native_source_bytes_differ")
    with ZipFile(source) as archive:
        infos = unified.inventory(archive)
        need("assets/idoly-qa-ui.json" not in infos and "assets/idoly-qa-only-software-aes.json" not in infos
             and "lib/arm64-v8a/libidoly_qa_ui_bridge.so" not in infos, "current_qa_prior_observer_or_adaptation")
        need(unified.member_hash(archive, AES) == ORIGINAL_AES
             and unified.member_hash(archive, UNITY) == ORIGINAL_UNITY, "current_qa_original_aes_unity_differ")
        need(unified.member_hash(archive, unified.OWN_BRIDGE) == native.get("sha256")
             and infos[unified.OWN_BRIDGE].file_size == native.get("bytes"), "current_qa_native_addon_bytes_differ")
        marker = json.loads(unified.read(archive, unified.MARKER, 65536))
        need(marker == report.get("marker") and marker.get("package") == unified.PACKAGE
             and marker.get("process_mode") == "same" and marker.get("prototype") is True,
             "current_qa_unified_marker_differs")
    return {"source_commit": commit, "producer_report_sha256": sha(report_path),
            "input_certificate_sha256": unified.CERTIFICATE, "current_unified_apk_sha256": actual,
            "original_source_sha256": unified.CLIENT_SHA256, "original_aes_sha256": ORIGINAL_AES,
            "original_unity_sha256": ORIGINAL_UNITY, "native_addon_sha256": native["sha256"],
            "compiled_sources_verified": len(blobs), "native_sources_verified": len(expected_native),
            "sdk_aes_store_adaptations": False}
