#!/usr/bin/env python3
"""Require actual Apple saved-output logic tests and UIKit SDK compilation.

This checks retained files, explicit Save ownership and settings UI logic.
It neither builds an APK/IPA nor proves game GPU rendering or Files-provider UI.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
TESTS = (
    "tests/test_ios_mp4_completed_library.py",
    "tests/test_ios_mp4_save_lifecycle.py",
    "tests/test_ios_mp4_queue_host.py",
    "tests/test_ios_mp4_completed_ui.py",
)
EXPECTED_TESTS = 49
SOURCES = TESTS + (
    ".github/workflows/verify-ios-mp4-save.yml",
    "tools/verify_ios_mp4_saved_outputs.py",
    "tests/test_ios_unified_web.py", "tests/test_ios_mp4_saved_outputs_ci.py",
    "tools/stage_mp4_preview.py", "tests/test_mp4_preview_delivery.py",
    "ios-unified/web/app.js", "ios-unified/web/index.html",
    "ios-unified/native/IdolyMP4Library.m", "ios-unified/native/IdolyMP4Library.h",
    "ios-unified/native/MP4CompletedFilePolicy.h",
    "ios-unified/native/IdolyMP4UI.m", "ios-unified/native/IdolyMP4UI.h",
    "ios-unified/native/IdolyEmbeddedServer.m", "ios-unified/native/IdolyEmbeddedServer.h",
    "ios-unified/native/IdolySettings.m", "ios-unified/native/IdolyNativeUI.h",
    "ios-unified/native/IdolyMacMenu.h", "ios-unified/native/CornerPolicy.h",
    "ios-unified/native/MP4LifecyclePolicy.h", "ios-unified/native/MP4FinalizationPolicy.h",
    "ios-unified/native/build_native.py", "ios-unified/native/test_mp4_ui_compile.py",
)


def need(value, code):
    if not value:
        raise ValueError(code)


def source_hashes():
    values = {}
    for name in SOURCES:
        path = ROOT / name
        need(path.is_file() and not path.is_symlink() and path.stat().st_size <= 8 * 1024 * 1024,
             "source_file_invalid")
        values[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return values


def junit_summary(path):
    need(path.is_file() and path.stat().st_size <= 1024 * 1024, "test_report_missing_or_large")
    document = ET.fromstring(path.read_bytes())
    cases = list(document.iter("testcase"))
    required = {Path(name).stem for name in TESTS}
    represented = {case.get("classname", "").split(".")[-1] for case in cases}
    skipped = sum(case.find("skipped") is not None for case in cases)
    errors = sum(case.find("error") is not None for case in cases)
    failures = sum(case.find("failure") is not None for case in cases)
    summary = {"tests": len(cases), "skipped": skipped, "errors": errors, "failures": failures}
    need(len(cases) == EXPECTED_TESTS and required <= represented, "required_test_cases_missing")
    need(not skipped and not errors and not failures, "required_apple_tests_did_not_pass")
    return summary


def validate_ui_receipt(receipt, hashes):
    need(type(receipt) is dict and receipt.get("schema") == 1
         and receipt.get("status") == "PASS_APPLE_UIKIT_COMPILE_ONLY"
         and receipt.get("actual_game_mv_verified") is False
         and receipt.get("actual_files_provider_verified") is False, "uikit_compile_report_invalid")
    commands, pins = receipt.get("commands"), receipt.get("source_sha256")
    need(type(commands) is list and len(commands) == 2 and type(pins) is dict, "uikit_targets_missing")
    for command, sdk, target in zip(commands, ("iPhoneOS", "iPhoneSimulator"),
                                    ("arm64-apple-ios13.0", "-apple-ios13.0-simulator")):
        need(type(command) is list and all(type(word) is str for word in command)
             and "-isysroot" in command and "-target" in command and "-fsyntax-only" in command,
             "uikit_actual_sdk_required")
        sdk_at = command.index("-isysroot") + 1
        target_at = command.index("-target") + 1
        need(sdk_at < len(command) and sdk in command[sdk_at]
             and target_at < len(command) and (command[target_at] == target if sdk == "iPhoneOS"
                 else command[target_at].endswith(target)), "uikit_target_differs")
        for name in ("IdolyMP4UI.m", "IdolySettings.m", "IdolyMP4Library.m"):
            need(str(ROOT / "ios-unified/native" / name) in command, "uikit_source_not_compiled")
    for name in ("IdolyMP4UI.m", "IdolyMP4UI.h", "IdolySettings.m", "IdolyMP4Library.m",
                 "IdolyMP4Library.h", "MP4CompletedFilePolicy.h"):
        need(pins.get(name) == hashes["ios-unified/native/" + name], "uikit_source_bytes_differ")


def git(*arguments):
    return subprocess.check_output(["git", *arguments], cwd=ROOT, text=True, timeout=15).strip()


def run_check(command, output):
    result = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=300,
                            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    # Synthetic test values only. Bound diagnostics rather than ever collecting
    # device logs, app containers or original account/resource data.
    text = result.stdout
    output.write_text(text[-65536:])
    need(result.returncode == 0, "required_check_failed")
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()
    need(re.fullmatch(r"[0-9a-f]{40}", args.source_commit), "exact_source_required")
    need(re.fullmatch(r"[1-9][0-9]{0,19}", args.run_id), "run_id_invalid")
    output = args.output_directory.resolve()
    need(not output.is_relative_to(ROOT), "output_must_be_outside_source")
    output.mkdir(parents=True, exist_ok=True)
    report = {"schema": 1, "status": "FAIL", "source_commit": args.source_commit,
              "run_id": args.run_id, "scope": "actual_apple_saved_output_logic_and_uikit_compile_only",
              "actual_game_mv_verified": False, "actual_files_provider_verified": False,
              "product_package_built": False}
    try:
        need(platform.system() == "Darwin" and shutil.which("xcrun") and shutil.which("node"),
             "actual_apple_sdk_and_node_required")
        need(git("rev-parse", "HEAD") == args.source_commit and not git("status", "--porcelain"),
             "committed_source_required")
        hashes = source_hashes()
        report["source_sha256"] = hashes
        run_check([sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider", *TESTS,
                   "--junitxml=" + str(output / "tests.xml")], output / "tests.log")
        report["tests"] = junit_summary(output / "tests.xml")
        ui = run_check([sys.executable, "-B", "ios-unified/native/test_mp4_ui_compile.py"], output / "uikit.log")
        receipt = json.loads(ui)
        validate_ui_receipt(receipt, hashes)
        (output / "uikit-compile.json").write_text(json.dumps(receipt, indent=2) + "\n")
        need(hashes == source_hashes() and not git("status", "--porcelain"), "source_changed_during_checks")
        report.update(status="PASS_ACTUAL_APPLE_SAVED_OUTPUT_LOGIC_AND_UIKIT_COMPILE_ONLY",
                      required_mac_tests_no_skips=True, source_unchanged_after_checks=True)
    except (ValueError, OSError, subprocess.SubprocessError, ET.ParseError, json.JSONDecodeError) as error:
        report["error_code"] = str(error) if type(error) is ValueError else type(error).__name__
    finally:
        (output / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: report[key] for key in ("schema", "status", "source_commit", "run_id")}))
    return 0 if report["status"].startswith("PASS_") else 1


if __name__ == "__main__":
    raise SystemExit(main())
