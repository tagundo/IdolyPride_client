"""Portable evidence validation; actual constructor execution requires macOS."""
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import struct
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
        "sigpipe_ignored_before_server": True, "sigpipe_plain_write_epipe": True,
        "other_signal_handlers_preserved": True,
        "constructor": {"constructor_calls": 1, "ready_calls": 0 if pre else 1,
                        "installed": True, "error": None, "sigpipe_default_before_install": True,
                        "sigpipe_ignored_after_install": True, "other_signal_handlers_preserved": True},
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
                 "sigpipe_ignored_before_server": True,
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
    if report["status"] != "PASS":
        pytest.fail(json.dumps(report, indent=2, sort_keys=True), pytrace=False)
    assert runner.validate_report(report, NATIVE) is report


def constructor_macho(tmp_path, *, legacy=False, offset=0x200, section_size=None, constructor_name=None):
    """Small synthetic Mach-O image with one constructor and one code section."""
    def section(name, segment_name, address, size, fileoff, alignment, flags):
        return struct.pack("<16s16sQQIIIIIIII", name.encode(), segment_name.encode(),
                           address, size, fileoff, alignment, 0, 0, flags, 0, 0, 0)

    def segment(name, address, vmsize, fileoff, filesize, protection, sections):
        return struct.pack("<II16sQQQQiiII", 0x19, 72 + 80 * len(sections), name.encode(),
                           address, vmsize, fileoff, filesize, protection, protection,
                           len(sections), 0) + b"".join(sections)

    code = section("__text", "__TEXT", 0x200, 0x40, 0x200, 2, 0x80000400)
    width = 8 if legacy else 4
    constructor_size = width if section_size is None else section_size
    name = constructor_name or ("__mod_init_func" if legacy else "__init_offsets")
    if legacy:
        constructors = section(name, "__DATA_CONST", 0x1000, constructor_size, 0x300, 3, 9)
        commands = [
            segment("__TEXT", 0, 0x1000, 0, 0x300, 5, [code]),
            segment("__DATA_CONST", 0x1000, 0x1000, 0x300, 0x100, 3, [constructors]),
        ]
    else:
        constructors = section(name, "__TEXT", 0x300, constructor_size, 0x300, 2, 0x16)
        commands = [segment("__TEXT", 0, 0x1000, 0, 0x400, 5, [code, constructors])]
    identifier = runner.INSTALL_NAME.encode() + b"\0"
    command_size = (24 + len(identifier) + 7) & ~7
    commands.append((struct.pack("<6I", 0xD, command_size, 24, 0, 0, 0) + identifier).ljust(command_size, b"\0"))
    commands.append(struct.pack("<6I", 0x32, 24, 1, 13 << 16, 14 << 16, 0))
    header = struct.pack("<8I", 0xFEEDFACF, 0x100000C, 0, 6, len(commands),
                         sum(map(len, commands)), 0, 0)
    image = bytearray((header + b"".join(commands)).ljust(0x400, b"\0"))
    assert len(header) + sum(map(len, commands)) <= 0x200
    image[0x200:0x204] = bytes.fromhex("c0035fd6")
    entry = struct.pack("<Q" if legacy else "<I", offset)
    image[0x300:0x300 + constructor_size] = entry.ljust(constructor_size, b"\0")[:constructor_size]
    path = tmp_path / ("legacy.dylib" if legacy else "offsets.dylib")
    path.write_bytes(image)
    return path


@pytest.mark.parametrize("legacy,section_type,width,name", [
    (True, 9, 8, "__mod_init_func"), (False, 0x16, 4, "__init_offsets"),
])
def test_macho_parser_accepts_both_darwin_constructor_formats(tmp_path, legacy, section_type, width, name):
    path = constructor_macho(tmp_path, legacy=legacy)
    image = runner.inspect_image(path, "arm64")
    assert image["constructor_section_present"] is True
    assert image["install_name"] == runner.INSTALL_NAME
    assert len(image["constructor_sections"]) == 1
    row = image["constructor_sections"][0]
    assert row["section"] == name and row["type"] == section_type
    assert row["bytes"] == row["entry_bytes"] == width and row["entries"] == 1
    assert isinstance(row["format"], str) and row["format"]
    assert row["targets_verified"] is (not legacy)
    assert image["build_versions"] == [{"command": "LC_BUILD_VERSION", "platform": 1, "minimum": 13 << 16,
                                        "sdk": 14 << 16, "tools": []}]


@pytest.mark.parametrize("offset", [0x202, 0x20, 0x300, 0x5000])
def test_macho_offset_constructors_require_aligned_targets_inside_instruction_sections(tmp_path, offset):
    path = constructor_macho(tmp_path, offset=offset)
    with pytest.raises(ValueError):
        runner.inspect_image(path, "arm64")


@pytest.mark.parametrize("legacy,size", [(False, 6), (True, 12)])
def test_macho_constructor_entry_size_must_match_its_format(tmp_path, legacy, size):
    path = constructor_macho(tmp_path, legacy=legacy, section_size=size)
    with pytest.raises(ValueError):
        runner.inspect_image(path, "arm64")


@pytest.mark.parametrize("legacy", [False, True])
def test_macho_constructor_type_requires_its_exact_section_name(tmp_path, legacy):
    path = constructor_macho(tmp_path, legacy=legacy, constructor_name="__wrong")
    with pytest.raises(ValueError):
        runner.inspect_image(path, "arm64")


def test_macho_constructor_section_cannot_extend_past_the_file(tmp_path):
    path = constructor_macho(tmp_path)
    path.write_bytes(path.read_bytes()[:0x302])
    with pytest.raises(ValueError):
        runner.inspect_image(path, "arm64")


@pytest.mark.parametrize("mode", ["cold", "stale-cache", "pre-runtime"])
@pytest.mark.parametrize("fault", [
    "default_not_forced", "ignore_not_installed", "other_signal_changed",
    "handler_not_ignored_before_server", "plain_write_not_epipe", "missing_epipe_count",
])
def test_every_fresh_mode_requires_process_sigpipe_ignore_and_plain_epipe_proof(mode, fault):
    report = synthetic_report()
    result = next(row for row in report["runs"] if row["mode"] == mode)
    if fault == "default_not_forced":
        result["constructor"]["sigpipe_default_before_install"] = False
    elif fault == "ignore_not_installed":
        result["constructor"]["sigpipe_ignored_after_install"] = False
    elif fault == "other_signal_changed":
        result["constructor"]["other_signal_handlers_preserved"] = False
    elif fault == "handler_not_ignored_before_server":
        result["host"]["sigpipe_ignored_before_server"] = False
    elif fault == "plain_write_not_epipe":
        result["sigpipe_plain_write_epipe"] = False
    else:
        result["counts"]["sigpipe_epipe_writes"] = 0
    with pytest.raises(ValueError):
        runner.validate_report(report, NATIVE)
