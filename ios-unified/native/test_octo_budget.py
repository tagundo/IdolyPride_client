#!/usr/bin/env python3
"""Run the Octo policy and macOS Foundation fixtures without launching a game."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import platform
import shutil
import struct
import subprocess
import sys
import tempfile


HERE = Path(__file__).resolve().parent
SOURCES = (
    "IdolyOctoBudget.h", "IdolyOctoBudget.m", "OctoBudgetPolicy.h", "OctoBudgetProfile.h",
    "tests/OctoBudgetFixture.h", "tests/octo_budget_policy_test.c",
    "tests/octo_budget_foundation_test.m", "test_octo_budget.py", "../../tests/test_octo_budget.py",
)
CHECKS = (
    "prepare_without_managed_access", "initialization_before_write", "first_snapshot_330",
    "idempotent_configuration", "unattested_rejected", "wrong_thread_rejected",
    "incomplete_api_rejected", "invalid_identity_rejected", "invalid_type_rejected",
    "nonstatic_rejected", "unexpected_default_rejected", "readback_failure_rejected",
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def source_pins(native_dir):
    root = Path(native_dir).resolve()
    pins = {}
    for name in SOURCES:
        path = root / name
        require(path.is_file() and not path.is_symlink(), "octo_budget_source_missing: " + name)
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(65536), b""):
                digest.update(chunk)
        pins[name] = digest.hexdigest()
    return pins


def _number(value, expected):
    return type(value) in (int, float) and math.isfinite(value) and value == expected


def validate_report(report, native_dir):
    """Reject incomplete evidence or stale source hashes; return valid evidence."""
    require(type(report) is dict and type(report.get("schema")) is int
            and report["schema"] == 1 and report.get("status") == "PASS", "octo_budget_report_not_pass")
    for key in ("portable_c_execution", "actual_macos_foundation_execution", "initialized"):
        require(report.get(key) is True, "octo_budget_true_required: " + key)
    for key in ("actual_iOS_Unity_execution", "physical_PlayCover_execution", "windows_or_simulators_created"):
        require(report.get(key) is False, "octo_budget_false_required: " + key)
    for key, expected in (("original_seconds", 10), ("effective_seconds", 330),
                          ("cache_wait_seconds", 300), ("value", 330), ("last_snapshot", 330)):
        require(_number(report.get(key), expected), "octo_budget_value_invalid: " + key)
    require(report.get("scope") == "unified-loopback", "octo_budget_scope_invalid")
    for key, expected in (("initializations", 1), ("reads", 3), ("writes", 1)):
        require(type(report.get(key)) is int and report[key] == expected, "octo_budget_counter_invalid: " + key)
    checks = report.get("checks")
    require(type(checks) is dict and set(checks) == set(CHECKS)
            and all(checks[key] is True for key in CHECKS), "octo_budget_checks_incomplete")
    budget = report.get("budget")
    require(type(budget) is dict and type(budget.get("schema")) is int and budget["schema"] == 1
            and budget.get("status") == "configured" and budget.get("prepared") is True
            and budget.get("configured") is True and "error" in budget and budget["error"] is None
            and budget.get("scope") == "unified-loopback", "octo_budget_state_invalid")
    for key, expected in (("original_seconds", 10), ("effective_seconds", 330), ("cache_wait_seconds", 300)):
        require(_number(budget.get(key), expected), "octo_budget_state_value_invalid: " + key)
    require(report.get("source_sha256") == source_pins(native_dir), "octo_budget_source_hash_mismatch")
    return report


def run(command, *, timeout=45):
    result = subprocess.run([str(value) for value in command], check=True, capture_output=True,
                            timeout=timeout)
    require(len(result.stdout) <= 65536 and len(result.stderr) <= 65536, "octo_budget_process_output_bound")
    return result.stdout


def execute(native_dir):
    native_dir = Path(native_dir).resolve()
    pins = source_pins(native_dir)
    report = {"schema": 1, "status": "FAIL", "portable_c_execution": False,
              "actual_macos_foundation_execution": False, "actual_iOS_Unity_execution": False,
              "physical_PlayCover_execution": False, "windows_or_simulators_created": False,
              "source_sha256": pins}
    try:
        compiler = shutil.which("cc") or shutil.which("clang")
        require(compiler is not None, "octo_budget_C_compiler_required")
        with tempfile.TemporaryDirectory(prefix="idoly-octo-budget-") as temporary:
            portable = Path(temporary) / "octo_budget_policy_test"
            run([compiler, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                 native_dir / "tests/octo_budget_policy_test.c", "-o", portable])
            raw = run([portable], timeout=10)
            require(raw.startswith(b"PASS: Octo named static-field budget policy;"), "octo_budget_portable_failed")
            report["portable_c_execution"] = True
            require(sys.platform == "darwin", "macos_and_Xcode_required_no_Foundation_execution")
            architecture = {"aarch64": "arm64"}.get(platform.machine(), platform.machine())
            require(architecture in ("arm64", "x86_64"), "octo_budget_host_architecture_unsupported")
            sdk = run(["xcrun", "--sdk", "macosx", "--show-sdk-path"], timeout=15).decode().strip()
            compiler = run(["xcrun", "--sdk", "macosx", "--find", "clang"], timeout=15).decode().strip()
            require(sdk.startswith("/") and compiler.startswith("/"), "octo_budget_Apple_tools_not_absolute")
            binary = Path(temporary) / "octo_budget_foundation_test"
            run([compiler, "-target", architecture + "-apple-macos13.0", "-isysroot", sdk,
                 "-DIDOLY_SMOKE_SIMULATOR=1", "-fobjc-arc", "-fblocks", "-O2", "-Wall", "-Wextra", "-Werror",
                 "-framework", "Foundation", native_dir / "IdolyOctoBudget.m",
                 native_dir / "tests/octo_budget_foundation_test.m", "-o", binary])
            with binary.open("rb") as stream:
                header = stream.read(32)
            require(len(header) == 32 and struct.unpack_from("<I", header)[0] == 0xFEEDFACF
                    and struct.unpack_from("<I", header, 4)[0] == {"arm64": 0x100000C, "x86_64": 0x1000007}[architecture]
                    and struct.unpack_from("<I", header, 12)[0] == 2, "octo_budget_host_executable_invalid")
            raw = run([binary], timeout=15)
            require(0 < len(raw) <= 8192, "octo_budget_native_result_bound")
            native = json.loads(raw)
            require(type(native) is dict, "octo_budget_native_result_invalid")
            report.update(native)
            report.update(portable_c_execution=True, physical_PlayCover_execution=False,
                          windows_or_simulators_created=False, source_sha256=pins)
            require(pins == source_pins(native_dir), "octo_budget_sources_changed_during_execution")
            validate_report(report, native_dir)
    except Exception as error:
        report.update(status="FAIL", error=str(error) if isinstance(error, ValueError) else type(error).__name__)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    report_path = args.report
    require(report_path.is_absolute() and not report_path.exists() and not report_path.is_symlink(),
            "fresh_absolute_octo_budget_report_required")
    report = execute(HERE)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"status": report["status"], "report": str(report_path),
                      "actual_macos_foundation_execution": report["actual_macos_foundation_execution"]}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
