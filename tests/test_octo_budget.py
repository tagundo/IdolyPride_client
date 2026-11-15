"""Compile and execute the shipping pure-C budget policy with a fake runtime."""
from pathlib import Path
import copy
import importlib.util
import json
import platform
import shutil
import subprocess
import sys

import pytest


NATIVE = Path(__file__).resolve().parents[1] / "ios-unified/native"
spec = importlib.util.spec_from_file_location("idoly_octo_budget_native_runner", NATIVE / "test_octo_budget.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def test_static_budget_configuration_precedes_watchdog_snapshot(tmp_path):
    compiler = shutil.which("cc") or shutil.which("clang")
    if compiler is None:
        pytest.skip("a C compiler is required for the portable policy fixture")
    binary = tmp_path / "octo_budget_policy_test"
    subprocess.run([compiler, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                    str(NATIVE / "tests/octo_budget_policy_test.c"), "-o", str(binary)],
                   check=True, capture_output=True, text=True, timeout=30)
    result = subprocess.run([str(binary)], check=True, capture_output=True, text=True, timeout=10)
    assert result.stdout.startswith("PASS: Octo named static-field budget policy;")


def valid_report():
    return {"schema": 1, "status": "PASS", "portable_c_execution": True,
            "actual_macos_foundation_execution": True, "actual_iOS_Unity_execution": False,
            "physical_PlayCover_execution": False, "windows_or_simulators_created": False,
            "initialized": True, "initializations": 1, "reads": 3, "writes": 1,
            "original_seconds": 10, "effective_seconds": 330, "cache_wait_seconds": 300,
            "scope": "unified-loopback", "value": 330, "last_snapshot": 330,
            "checks": dict.fromkeys(runner.CHECKS, True),
            "budget": {"schema": 1, "status": "configured", "prepared": True, "configured": True,
                       "original_seconds": 10, "effective_seconds": 330, "cache_wait_seconds": 300,
                       "scope": "unified-loopback", "error": None},
            "source_sha256": runner.source_pins(NATIVE)}


def test_report_validation_requires_all_current_source_hashes():
    report = valid_report()
    assert runner.validate_report(report, NATIVE) is report


@pytest.mark.parametrize("key,value", [
    ("status", "FAIL"), ("schema", True), ("portable_c_execution", False),
    ("actual_macos_foundation_execution", False), ("actual_iOS_Unity_execution", True),
    ("physical_PlayCover_execution", True), ("windows_or_simulators_created", True),
    ("initialized", 1), ("initializations", True), ("reads", 2), ("writes", 2),
    ("original_seconds", float("nan")), ("effective_seconds", float("inf")),
    ("cache_wait_seconds", True), ("scope", "all-clients"), ("last_snapshot", 10),
])
def test_report_rejects_unproved_execution_and_wrong_runtime_values(key, value):
    report = valid_report()
    report[key] = value
    with pytest.raises(ValueError):
        runner.validate_report(report, NATIVE)


@pytest.mark.parametrize("change", ["missing_check", "integer_check", "missing_source", "stale_source",
                                    "extra_source", "unprepared", "failed_budget", "wrong_budget_value",
                                    "missing_budget_error"])
def test_report_rejects_missing_checks_stale_sources_and_failed_wrapper_state(change):
    report = copy.deepcopy(valid_report())
    if change == "missing_check":
        report["checks"].pop(runner.CHECKS[0])
    elif change == "integer_check":
        report["checks"][runner.CHECKS[0]] = 1
    elif change == "missing_source":
        report["source_sha256"].pop("IdolyOctoBudget.m")
    elif change == "stale_source":
        report["source_sha256"]["OctoBudgetPolicy.h"] = "0" * 64
    elif change == "extra_source":
        report["source_sha256"]["../untrusted-file"] = "0" * 64
    elif change == "unprepared":
        report["budget"]["prepared"] = False
    elif change == "failed_budget":
        report["budget"]["error"] = "unexpected_value"
    elif change == "missing_budget_error":
        report["budget"].pop("error")
    else:
        report["budget"]["effective_seconds"] = 10
    with pytest.raises(ValueError):
        runner.validate_report(report, NATIVE)


@pytest.mark.skipif(sys.platform == "darwin", reason="this verifies the explicit non-Apple failure report")
def test_linux_runner_records_portable_success_without_claiming_foundation_execution(tmp_path):
    report_path = tmp_path / "octo-budget-native-test.json"
    result = subprocess.run([sys.executable, str(NATIVE / "test_octo_budget.py"), "--report", str(report_path)],
                            capture_output=True, text=True, timeout=45)
    assert result.returncode == 1
    report = json.loads(report_path.read_text())
    assert report["status"] == "FAIL" and report["portable_c_execution"] is True
    assert report["actual_macos_foundation_execution"] is False
    assert report["actual_iOS_Unity_execution"] is report["physical_PlayCover_execution"] is False
    assert report["error"] == "macos_and_Xcode_required_no_Foundation_execution"
    assert report["source_sha256"] == runner.source_pins(NATIVE)


@pytest.mark.skipif(sys.platform != "darwin", reason="Foundation execution requires macOS/Xcode")
def test_foundation_wrapper_uses_smoke_only_runtime_provider(tmp_path):
    architecture = {"aarch64": "arm64"}.get(platform.machine(), platform.machine())
    if architecture not in ("arm64", "x86_64"):
        pytest.skip("unsupported macOS test architecture")
    sdk = subprocess.run(["xcrun", "--sdk", "macosx", "--show-sdk-path"], check=True,
                         capture_output=True, text=True, timeout=15).stdout.strip()
    compiler = subprocess.run(["xcrun", "--sdk", "macosx", "--find", "clang"], check=True,
                              capture_output=True, text=True, timeout=15).stdout.strip()
    assert sdk.startswith("/") and compiler.startswith("/")
    binary = tmp_path / "octo_budget_foundation_test"
    subprocess.run([compiler, "-target", architecture + "-apple-macos13.0", "-isysroot", sdk,
                    "-DIDOLY_SMOKE_SIMULATOR=1", "-fobjc-arc", "-fblocks", "-O2", "-Wall",
                    "-Wextra", "-Werror", "-framework", "Foundation",
                    str(NATIVE / "IdolyOctoBudget.m"),
                    str(NATIVE / "tests/octo_budget_foundation_test.m"), "-o", str(binary)],
                   check=True, capture_output=True, text=True, timeout=45)
    raw = subprocess.run([str(binary)], check=True, capture_output=True, text=True, timeout=10).stdout
    assert 0 < len(raw) <= 8192
    result = json.loads(raw)
    assert result["status"] == "PASS" and result["actual_macos_foundation_execution"] is True
    assert result["actual_iOS_Unity_execution"] is False
    assert result["initialized"] is True and result["initializations"] == result["writes"] == 1
    assert result["value"] == result["last_snapshot"] == 330
    assert result["schema"] == 1 and result["original_seconds"] == 10
    assert result["effective_seconds"] == 330 and result["cache_wait_seconds"] == 300
    assert result["scope"] == "unified-loopback"
    assert len(result["checks"]) == 12 and all(value is True for value in result["checks"].values())
