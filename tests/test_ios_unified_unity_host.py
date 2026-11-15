"""Portable evidence validation; actual constructor execution requires macOS."""
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

NATIVE = Path(__file__).resolve().parents[1] / "ios-unified/native"
spec = importlib.util.spec_from_file_location("idoly_unity_host_runner", NATIVE / "test_unity_host.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def synthetic_run(mode):
    """Synthetic validator input only; it is never published as native evidence."""
    cold = mode == "cold"
    pre = mode == "pre-runtime"
    return {
        "schema": 1, "status": "PASS", "mode": mode,
        "actual_macos_foundation_execution": True, "actual_dylib_constructor_execution": True,
        "actualOriginalUnity": False, "physical_PlayCover_execution": False,
        "windows_or_simulators_created": False, "constructor_before_main": True,
        "constructor": {"constructor_calls": 1, "ready_calls": 0 if pre else 1,
                        "installed": True, "error": None},
        "checks": dict.fromkeys(runner.MODE_CHECKS[mode], True),
        "counts": dict(zip(runner.COUNT_NAMES, runner.MODE_COUNTS[mode])),
        "canary": "fixture-en-data" if cold else None,
        "embedded_lifecycle": ["finish", "foreground", "active"] if cold else [],
        "events": list(range(9)) if cold else [],
        "host": {"schema": 1, "strategy": "unity-as-library", "installed": True,
                 "entry_captured": True, "host_ready": not pre, "launching": False,
                 "started": cold, "failed": pre, "application_main_calls": 0 if pre else 1,
                 "runtime_start_calls": 1 if cold else 0, "warmup_calls": 1 if cold else 0,
                 "bundle_match_before": cold, "bundle_match_after": cold,
                 "first_warmup_bundle_match": cold, "unity_window_bound": cold,
                 "consumed_bundle_language": "en" if cold else None,
                 "queued_events": 8 if mode == "stale-cache" else 0,
                 "delivered_events": 9 if cold else 0, "lifecycle_forwarded": 1 if cold else 0,
                 "error": {"cold": "start_rejected", "stale-cache": "cached_bundle_root_mismatch",
                           "pre-runtime": "runtime_initialized_before_host"}[mode]},
    }


def synthetic_report():
    return {
        "schema": 1, "status": "PASS", "portable_c_execution": True,
        "actual_macos_foundation_execution": True, "actual_dylib_constructor_execution": True,
        "actualOriginalUnity": False, "physical_PlayCover_execution": False,
        "windows_or_simulators_created": False, "host_architecture": "arm64",
        "source_sha256": runner.source_pins(NATIVE),
        "compiled_native_images": {
            "fixture_dylib": {"sha256": "1" * 64, "cpu": 0x100000C, "filetype": 6,
                              "constructor_section_present": True, "install_name": runner.INSTALL_NAME},
            "fixture_executable": {"sha256": "2" * 64, "cpu": 0x100000C, "filetype": 2,
                                   "links_fixture_dylib": True}},
        "runs": [synthetic_run(mode) for mode in ("cold", "stale-cache", "pre-runtime")],
    }


def test_portable_host_policy_enforces_cold_start_once_and_event_budget(tmp_path):
    compiler = shutil.which("cc") or shutil.which("clang")
    if not compiler:
        pytest.skip("C compiler required for portable host policy")
    binary = tmp_path / "unity_host_policy_test"
    subprocess.run([compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic",
                    str(NATIVE / "tests/unity_host_policy_test.c"), "-o", str(binary)],
                   check=True, capture_output=True, timeout=30)
    result = subprocess.run([str(binary)], check=True, capture_output=True, text=True, timeout=10)
    assert result.stdout.startswith("PASS: Unity host policy;")


def test_complete_current_report_passes_validation():
    report = synthetic_report()
    assert runner.validate_report(report, NATIVE) is report


@pytest.mark.parametrize("key,value", [
    ("schema", True), ("status", "FAIL"), ("portable_c_execution", False),
    ("actual_macos_foundation_execution", False), ("actual_dylib_constructor_execution", 1),
    ("actualOriginalUnity", True), ("physical_PlayCover_execution", True),
    ("windows_or_simulators_created", True), ("host_architecture", "unknown"),
])
def test_report_rejects_unproved_native_execution(key, value):
    report = synthetic_report()
    report[key] = value
    with pytest.raises(ValueError):
        runner.validate_report(report, NATIVE)


@pytest.mark.parametrize("fault", [
    "stale_pin", "missing_pin", "extra_pin", "missing_run", "repeated_mode", "no_dylib_constructor",
    "no_dylib_dependency", "wrong_binary_kind", "wrong_binary_cpu", "invalid_binary_hash",
])
def test_report_rejects_missing_provenance_and_dyld_evidence(fault):
    report = synthetic_report()
    if fault == "stale_pin":
        report["source_sha256"]["IdolyUnityHost.m"] = "0" * 64
    elif fault == "missing_pin":
        report["source_sha256"].pop("IdolyClientData.m")
    elif fault == "extra_pin":
        report["source_sha256"]["../untrusted"] = "0" * 64
    elif fault == "missing_run":
        report["runs"].pop()
    elif fault == "repeated_mode":
        report["runs"][2] = copy.deepcopy(report["runs"][1])
    elif fault == "no_dylib_constructor":
        report["compiled_native_images"]["fixture_dylib"]["constructor_section_present"] = False
    elif fault == "no_dylib_dependency":
        report["compiled_native_images"]["fixture_executable"]["links_fixture_dylib"] = False
    elif fault == "wrong_binary_kind":
        report["compiled_native_images"]["fixture_dylib"]["filetype"] = 2
    elif fault == "wrong_binary_cpu":
        report["compiled_native_images"]["fixture_executable"]["cpu"] = 0x1000007
    else:
        report["compiled_native_images"]["fixture_executable"]["sha256"] = "missing"
    with pytest.raises(ValueError):
        runner.validate_report(report, NATIVE)


@pytest.mark.parametrize("fault", [
    "constructor_after_main", "constructor_twice", "missing_constructor_error", "runtime_twice",
    "wrong_canary", "wrong_lifecycle", "replayed_active", "wrong_event_order", "event_bool",
    "window_not_adopted", "only_one_window", "missing_window_guard", "missing_root_controller",
    "wrong_normal_window", "check_integer", "stale_ko_started", "pre_runtime_entered_uikit",
])
def test_report_rejects_routing_window_and_lifecycle_regressions(fault):
    report = synthetic_report()
    cold, stale, pre = report["runs"]
    if fault == "constructor_after_main":
        cold["constructor_before_main"] = False
    elif fault == "constructor_twice":
        cold["constructor"]["constructor_calls"] = 2
    elif fault == "missing_constructor_error":
        cold["constructor"].pop("error")
    elif fault == "runtime_twice":
        cold["counts"]["original_embedded"] = 2
    elif fault == "wrong_canary":
        cold["canary"] = "fixture-ko-data"
    elif fault == "wrong_lifecycle":
        cold["embedded_lifecycle"] = ["finish", "active", "foreground"]
    elif fault == "replayed_active":
        cold["host"]["lifecycle_forwarded"] = 2
    elif fault == "wrong_event_order":
        cold["events"] = list(reversed(range(9)))
    elif fault == "event_bool":
        cold["events"][0] = False
    elif fault == "window_not_adopted":
        cold["host"]["unity_window_bound"] = False
    elif fault == "only_one_window":
        cold["counts"]["windows"] = 1
    elif fault == "missing_window_guard":
        cold["checks"].pop("placeholder_retired")
    elif fault == "missing_root_controller":
        cold["checks"]["game_root_controller"] = False
    elif fault == "wrong_normal_window":
        cold["checks"]["normal_game_window"] = False
    elif fault == "check_integer":
        cold["checks"]["main_entry_intercepted"] = 1
    elif fault == "stale_ko_started":
        stale["host"]["runtime_start_calls"] = 1
    else:
        pre["counts"]["application_main"] = 1
    with pytest.raises(ValueError):
        runner.validate_report(report, NATIVE)


@pytest.mark.skipif(sys.platform == "darwin", reason="this asserts the non-Apple failure path")
def test_linux_producer_cannot_claim_foundation_or_ctor_execution(tmp_path):
    report_path = tmp_path / "unity-host-native-test.json"
    result = subprocess.run([sys.executable, str(NATIVE / "test_unity_host.py"),
                             "--report", str(report_path)], capture_output=True, text=True, timeout=45)
    assert result.returncode == 1
    report = json.loads(report_path.read_text())
    assert report["status"] == "FAIL" and report["portable_c_execution"] is True
    assert report["actual_macos_foundation_execution"] is report["actual_dylib_constructor_execution"] is False
    assert report["actualOriginalUnity"] is report["physical_PlayCover_execution"] is False
    assert report["error"] == "macos_and_Xcode_required_no_Foundation_execution"


@pytest.mark.skipif(sys.platform != "darwin", reason="actual dyld/Foundation execution requires macOS/Xcode")
def test_actual_constructor_loaded_dylib_and_three_fresh_runtime_modes():
    report = runner.execute(NATIVE)
    assert report["status"] == "PASS", report
    assert runner.validate_report(report, NATIVE) is report
