#!/usr/bin/env python3
"""Exercise a real constructor-loaded Foundation dylib without launching Unity."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import re
import shutil
import struct
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
INSTALL_NAME = "@rpath/libIdolyUnityHostFixture.dylib"
SOURCES = (
    "IdolyUnityHost.h", "IdolyUnityHost.m", "UnityHostPolicy.h", "UnityHostProfile.h",
    "IdolyClientData.h", "IdolyClientData.m", "tests/UnityHostFoundationUIKit.h",
    "tests/unity_host_policy_test.c", "tests/unity_host_fake_uikit.m", "tests/unity_host_ctor.m",
    "tests/unity_host_foundation_test.m", "test_unity_host.py", "../../tests/test_ios_unified_unity_host.py",
)
COMMON_CHECKS = ("constructor_before_main", "registration_after_constructor", "smoke_table_copy",
                 "main_entry_intercepted", "start_before_capture_rejected")
MODE_CHECKS = {
    "cold": COMMON_CHECKS + (
        "selected_bundle_before_warmup", "first_warmup_canary_en", "single_embedded_start",
        "lifecycle_original_order", "no_active_replay", "queued_event_limit", "queued_event_order",
        "post_start_forwarding", "duplicate_start_rejected", "wrong_selected_root_rejected",
        "two_distinct_windows", "unity_window_adopted", "placeholder_retired",
        "normal_game_window", "game_root_controller"),
    "stale-cache": COMMON_CHECKS + ("stale_cached_ko_rejected", "runtime_not_started",
                                  "queued_events_not_delivered"),
    "pre-runtime": COMMON_CHECKS + ("runtime_before_capture_rejected", "application_main_not_entered",
                                  "runtime_not_started"),
}
COUNT_NAMES = ("original_run_main", "application_main", "original_embedded", "original_warmup",
               "run_count", "canary_reads", "setter_calls", "ready_observer", "restorations", "windows")
MODE_COUNTS = {
    "cold": (0, 1, 1, 1, 1, 1, 1, 1, 4, 2),
    "stale-cache": (0, 1, 0, 0, 0, 0, 1, 1, 0, 1),
    "pre-runtime": (0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_pins(native_dir):
    root = Path(native_dir).resolve()
    result = {}
    for name in SOURCES:
        path = root / name
        require(path.is_file() and not path.is_symlink(), "unity_host_source_missing: " + name)
        result[name] = sha(path)
    return result


def integer(value, expected):
    return type(value) is int and value == expected


def validate_run(result):
    require(type(result) is dict and integer(result.get("schema"), 1)
            and result.get("status") == "PASS", "unity_host_run_not_pass")
    mode = result.get("mode")
    require(mode in MODE_CHECKS, "unity_host_mode_invalid")
    for key in ("actual_macos_foundation_execution", "actual_dylib_constructor_execution",
                "constructor_before_main"):
        require(result.get(key) is True, "unity_host_run_true_required: " + key)
    for key in ("actualOriginalUnity", "physical_PlayCover_execution", "windows_or_simulators_created"):
        require(result.get(key) is False, "unity_host_run_false_required: " + key)
    checks = result.get("checks")
    require(type(checks) is dict and set(checks) == set(MODE_CHECKS[mode])
            and all(checks[key] is True for key in MODE_CHECKS[mode]), "unity_host_checks_incomplete")
    counts = result.get("counts")
    require(type(counts) is dict and set(counts) == set(COUNT_NAMES)
            and all(integer(counts[key], expected) for key, expected in zip(COUNT_NAMES, MODE_COUNTS[mode])),
            "unity_host_counters_invalid")
    constructor = result.get("constructor")
    require(type(constructor) is dict and integer(constructor.get("constructor_calls"), 1)
            and integer(constructor.get("ready_calls"), 0 if mode == "pre-runtime" else 1)
            and constructor.get("installed") is True and "error" in constructor
            and constructor["error"] is None, "unity_host_constructor_evidence_invalid")
    host = result.get("host")
    require(type(host) is dict and integer(host.get("schema"), 1)
            and host.get("strategy") == "unity-as-library", "unity_host_state_missing")
    flags = {"installed": True, "entry_captured": True, "host_ready": mode != "pre-runtime",
             "launching": False, "started": mode == "cold", "failed": mode == "pre-runtime",
             "bundle_match_before": mode == "cold", "bundle_match_after": mode == "cold",
             "first_warmup_bundle_match": mode == "cold", "unity_window_bound": mode == "cold"}
    for key, expected in flags.items():
        require(host.get(key) is expected, "unity_host_state_flag_invalid: " + key)
    counters = {"application_main_calls": 0 if mode == "pre-runtime" else 1,
                "runtime_start_calls": 1 if mode == "cold" else 0,
                "warmup_calls": 1 if mode == "cold" else 0,
                "queued_events": 8 if mode == "stale-cache" else 0,
                "delivered_events": 9 if mode == "cold" else 0,
                "lifecycle_forwarded": 1 if mode == "cold" else 0}
    for key, expected in counters.items():
        require(integer(host.get(key), expected), "unity_host_state_counter_invalid: " + key)
    require("consumed_bundle_language" in host and host["consumed_bundle_language"] == (
        "en" if mode == "cold" else None), "unity_host_language_invalid")
    errors = {"cold": "start_rejected", "stale-cache": "cached_bundle_root_mismatch",
              "pre-runtime": "runtime_initialized_before_host"}
    require(host.get("error") == errors[mode], "unity_host_expected_rejection_missing")
    require("canary" in result and result["canary"] == ("fixture-en-data" if mode == "cold" else None),
            "unity_host_canary_invalid")
    require(result.get("embedded_lifecycle") == (["finish", "foreground", "active"] if mode == "cold" else []),
            "unity_host_lifecycle_order_invalid")
    require(type(result.get("events")) is list and all(type(item) is int for item in result["events"])
            and result["events"] == (list(range(9)) if mode == "cold" else []),
            "unity_host_event_order_invalid")
    return result


def validate_report(report, native_dir):
    """Return complete current evidence, or raise ValueError."""
    require(type(report) is dict and integer(report.get("schema"), 1)
            and report.get("status") == "PASS", "unity_host_report_not_pass")
    for key in ("portable_c_execution", "actual_macos_foundation_execution", "actual_dylib_constructor_execution"):
        require(report.get(key) is True, "unity_host_report_true_required: " + key)
    for key in ("actualOriginalUnity", "physical_PlayCover_execution", "windows_or_simulators_created"):
        require(report.get(key) is False, "unity_host_report_false_required: " + key)
    require(report.get("source_sha256") == source_pins(native_dir), "unity_host_source_hash_mismatch")
    architecture = report.get("host_architecture")
    require(architecture in ("arm64", "x86_64"), "unity_host_architecture_invalid")
    images = report.get("compiled_native_images")
    require(type(images) is dict and set(images) == {"fixture_dylib", "fixture_executable"},
            "unity_host_native_images_missing")
    cpu = {"arm64": 0x100000C, "x86_64": 0x1000007}[architecture]
    for key, filetype in (("fixture_dylib", 6), ("fixture_executable", 2)):
        row = images[key]
        require(type(row) is dict and integer(row.get("cpu"), cpu) and integer(row.get("filetype"), filetype)
                and type(row.get("sha256")) is str and re.fullmatch("[0-9a-f]{64}", row["sha256"]),
                "unity_host_native_image_invalid: " + key)
    require(images["fixture_dylib"].get("constructor_section_present") is True
            and images["fixture_dylib"].get("install_name") == INSTALL_NAME
            and images["fixture_executable"].get("links_fixture_dylib") is True,
            "unity_host_dyld_constructor_proof_missing")
    runs = report.get("runs")
    require(type(runs) is list and len(runs) == 3, "unity_host_three_fresh_runs_required")
    for result in runs:
        validate_run(result)
    require([result["mode"] for result in runs] == ["cold", "stale-cache", "pre-runtime"],
            "unity_host_run_modes_or_order_invalid")
    return report


def run(command, timeout=45):
    result = subprocess.run([str(value) for value in command], check=True, capture_output=True, timeout=timeout)
    require(len(result.stdout) <= 65536 and len(result.stderr) <= 65536, "unity_host_process_output_bound")
    return result.stdout


def inspect_image(path, architecture):
    file_bytes = Path(path).stat().st_size
    require(32 <= file_bytes <= 32 * 1024 * 1024, "unity_host_fixture_image_size_invalid")
    with Path(path).open("rb") as stream:
        header = stream.read(32)
        require(len(header) == 32, "unity_host_native_header_short")
        magic, cpu, _, filetype, count, length, _, _ = struct.unpack("<8I", header)
        require(magic == 0xFEEDFACF and cpu == {"arm64": 0x100000C, "x86_64": 0x1000007}[architecture]
                and count <= 4096 and length <= 1024 * 1024
                and length <= file_bytes - 32, "unity_host_native_header_invalid")
        commands = stream.read(length)
    require(len(commands) == length, "unity_host_native_commands_short")
    offset, loads, install_name = 0, [], None
    candidates, instructions, versions = [], [], []
    image_base = None
    for _ in range(count):
        require(offset + 8 <= len(commands), "unity_host_native_command_truncated")
        code, size = struct.unpack_from("<II", commands, offset)
        require(size >= 8 and offset + size <= len(commands), "unity_host_native_command_invalid")
        if code == 0x19:
            require(size >= 72, "unity_host_segment_invalid")
            segment = commands[offset + 8:offset + 24].split(b"\0")[0].decode("ascii")
            vmaddr, vmsize, fileoff, filesize = struct.unpack_from("<4Q", commands, offset + 24)
            initprot = struct.unpack_from("<I", commands, offset + 60)[0]
            sections = struct.unpack_from("<I", commands, offset + 64)[0]
            require(sections <= (size - 72) // 80 and fileoff <= file_bytes
                    and filesize <= file_bytes - fileoff, "unity_host_sections_invalid")
            if segment == "__TEXT":
                require(image_base is None and fileoff == 0, "unity_host_text_base_invalid")
                image_base = vmaddr
            for index in range(sections):
                at = offset + 72 + 80 * index
                name = commands[at:at + 16].split(b"\0")[0].decode("ascii")
                section_segment = commands[at + 16:at + 32].split(b"\0")[0].decode("ascii")
                address, size_in_bytes = struct.unpack_from("<2Q", commands, at + 32)
                section_offset = struct.unpack_from("<I", commands, at + 48)[0]
                flags = struct.unpack_from("<I", commands, at + 64)[0]
                kind = flags & 0xFF
                require(section_segment == segment and vmaddr <= address
                        and address - vmaddr <= vmsize and size_in_bytes <= vmsize - (address - vmaddr),
                        "unity_host_section_mapping_invalid")
                if initprot & 4 and flags & 0x80000400 and size_in_bytes:
                    instructions.append((address, address + size_in_bytes))
                if kind in (9, 0x16) and size_in_bytes:
                    width = 8 if kind == 9 else 4
                    expected_name = "__mod_init_func" if kind == 9 else "__init_offsets"
                    allowed = ("__DATA", "__DATA_CONST", "__AUTH_CONST") if kind == 9 else ("__TEXT",)
                    require(segment in allowed and name == expected_name and size_in_bytes <= 65536
                            and size_in_bytes % width == 0 and section_offset <= file_bytes
                            and size_in_bytes <= file_bytes - section_offset,
                            "unity_host_constructor_section_invalid")
                    candidates.append({"segment": segment, "section": name, "flags": flags,
                                       "type": kind, "bytes": size_in_bytes, "entry_bytes": width,
                                       "entries": size_in_bytes // width,
                                       "format": "pointers64" if kind == 9 else "offsets32",
                                       "targets_verified": False, "file_offset": section_offset})
        if code == 0x32:
            require(size >= 24, "unity_host_build_version_invalid")
            platform_id, minimum, sdk_version, tools = struct.unpack_from("<4I", commands, offset + 8)
            require(tools <= 16 and 24 + 8 * tools <= size, "unity_host_build_tools_invalid")
            versions.append({"command": "LC_BUILD_VERSION", "platform": platform_id,
                             "minimum": minimum, "sdk": sdk_version,
                             "tools": [dict(zip(("tool", "version"), struct.unpack_from(
                                 "<2I", commands, offset + 24 + 8 * index))) for index in range(tools)]})
        if code == 0x24:
            require(size >= 16, "unity_host_minimum_version_invalid")
            minimum, sdk_version = struct.unpack_from("<2I", commands, offset + 8)
            versions.append({"command": "LC_VERSION_MIN_MACOSX", "platform": 1,
                             "minimum": minimum, "sdk": sdk_version, "tools": []})
        if code in (0xC, 0xD, 0x80000018, 0x8000001F):
            require(size >= 24, "unity_host_dylib_command_invalid")
            start = struct.unpack_from("<I", commands, offset + 8)[0]
            require(24 <= start < size, "unity_host_dylib_name_invalid")
            name = commands[offset + start:offset + size].split(b"\0")[0].decode()
            if code == 0xD:
                install_name = name
            else:
                loads.append(name)
        offset += size
    require(offset == len(commands) and image_base is not None, "unity_host_native_commands_size_invalid")
    require(len(candidates) <= 64, "unity_host_constructor_section_count_invalid")
    with Path(path).open("rb") as stream:
        for row in candidates:
            if row["type"] == 0x16:
                # Modern Apple ld stores 32-bit image-relative function offsets,
                # not dyld-rebased 64-bit pointers, in __TEXT,__init_offsets.
                stream.seek(row["file_offset"])
                values = stream.read(row["bytes"])
                require(len(values) == row["bytes"] and instructions,
                        "unity_host_constructor_offsets_truncated")
                for (relative,) in struct.iter_unpack("<I", values):
                    target = image_base + relative
                    require((architecture != "arm64" or target % 4 == 0)
                            and any(lo <= target < hi for lo, hi in instructions),
                            "unity_host_constructor_offset_outside_code")
                row["targets_verified"] = True
            # Legacy pointer values may use chained rebases. Actual execution of
            # the exact constructor before main remains mandatory in every mode.
            row.pop("file_offset")
    return {"sha256": sha(path), "cpu": cpu, "filetype": filetype,
            "constructor_section_present": bool(candidates), "constructor_sections": candidates,
            "build_versions": versions, "install_name": install_name,
            "links_fixture_dylib": INSTALL_NAME in loads}


def execute(native_dir):
    native_dir = Path(native_dir).resolve()
    pins = source_pins(native_dir)
    report = {"schema": 1, "status": "FAIL", "portable_c_execution": False,
              "actual_macos_foundation_execution": False, "actual_dylib_constructor_execution": False,
              "actualOriginalUnity": False, "physical_PlayCover_execution": False,
              "windows_or_simulators_created": False, "source_sha256": pins, "runs": []}
    try:
        compiler = shutil.which("cc") or shutil.which("clang")
        require(compiler is not None, "unity_host_C_compiler_required")
        with tempfile.TemporaryDirectory(prefix="idoly-unity-host-") as temporary:
            directory = Path(temporary)
            portable = directory / "unity_host_policy_test"
            run([compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic",
                 native_dir / "tests/unity_host_policy_test.c", "-o", portable])
            require(run([portable], timeout=10).startswith(b"PASS: Unity host policy;"), "unity_host_portable_failed")
            report["portable_c_execution"] = True
            require(sys.platform == "darwin", "macos_and_Xcode_required_no_Foundation_execution")
            architecture = {"aarch64": "arm64"}.get(platform.machine(), platform.machine())
            require(architecture in ("arm64", "x86_64"), "unity_host_host_architecture_unsupported")
            sdk = run(["xcrun", "--sdk", "macosx", "--show-sdk-path"], timeout=15).decode().strip()
            compiler = run(["xcrun", "--sdk", "macosx", "--find", "clang"], timeout=15).decode().strip()
            nm = run(["xcrun", "--sdk", "macosx", "--find", "nm"], timeout=15).decode().strip()
            require(all(path.startswith("/") for path in (sdk, compiler, nm)), "unity_host_Apple_tools_not_absolute")
            flags = [compiler, "-target", architecture + "-apple-macos13.0", "-isysroot", sdk,
                     "-DIDOLY_SMOKE_SIMULATOR=1", "-DIDOLY_UNITY_HOST_FOUNDATION_TESTING=1",
                     "-fobjc-arc", "-fblocks", "-O2", "-Wall", "-Wextra", "-Werror", "-framework", "Foundation"]
            dylib, binary = directory / "libIdolyUnityHostFixture.dylib", directory / "unity_host_foundation_test"
            run(flags + ["-dynamiclib", "-Wl,-install_name," + INSTALL_NAME,
                         native_dir / "IdolyUnityHost.m", native_dir / "IdolyClientData.m",
                         native_dir / "tests/unity_host_fake_uikit.m", native_dir / "tests/unity_host_ctor.m",
                         "-o", dylib])
            undefined = run([nm, "-u", dylib]).decode()
            require(not any(name in undefined for name in (
                "_UIApplicationMain", "_OBJC_CLASS_$_UnityFramework",
                "_OBJC_CLASS_$_IDUnityHostFixtureObserver")), "unity_host_reverse_executable_dependency")
            run(flags + [native_dir / "tests/unity_host_foundation_test.m", "-L", directory,
                         "-lIdolyUnityHostFixture", "-Wl,-rpath,@executable_path", "-o", binary])
            report.update(host_architecture=architecture, compiled_native_images={
                "fixture_dylib": inspect_image(dylib, architecture),
                "fixture_executable": inspect_image(binary, architecture)})
            for mode in ("cold", "stale-cache", "pre-runtime"):
                raw = run([binary, "--" + mode], timeout=20)
                require(0 < len(raw) <= 16384, "unity_host_native_result_bound")
                result = json.loads(raw)
                validate_run(result)
                report["runs"].append(result)
            require(pins == source_pins(native_dir), "unity_host_sources_changed_during_execution")
            report.update(status="PASS", actual_macos_foundation_execution=True,
                          actual_dylib_constructor_execution=True)
            validate_report(report, native_dir)
    except subprocess.CalledProcessError as error:
        command = error.cmd if isinstance(error.cmd, (list, tuple)) else []
        report.update(status="FAIL", error="native_fixture_command_failed",
                      failed_program=Path(str(command[0])).name if command else "unknown",
                      returncode=error.returncode,
                      diagnostic=(error.stderr or b"").decode("utf-8", errors="replace")[-8192:],
                      diagnostic_stdout=(error.stdout or b"").decode("utf-8", errors="replace")[-8192:])
    except Exception as error:
        report.update(status="FAIL", error=str(error) if isinstance(error, ValueError) else type(error).__name__)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    destination = args.report
    require(destination.is_absolute() and not destination.exists() and not destination.is_symlink(),
            "fresh_absolute_unity_host_report_required")
    report = execute(HERE)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"status": report["status"], "report": str(destination),
                      "actual_macos_foundation_execution": report["actual_macos_foundation_execution"]}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
