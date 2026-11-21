#!/usr/bin/env python3
"""Run cold/warm keyboard lifecycle fixtures against real macOS Foundation.

This compiles the shipping helper and starts two fresh command-line processes.
It launches no UIKit, Unity game, PlayCover, windows or Simulators.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import sys
import tempfile

import test_mac_menu as host

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report_path = args.report.absolute()
    host.require(not report_path.exists() and not report_path.is_symlink(), "fresh_keyboard_lifecycle_report_required")
    report = {"schema": 1, "status": "FAIL", "actual_macos_foundation_execution": False,
              "actual_iOS_Unity_execution": False, "physical_PlayCover_execution": False,
              "windows_or_simulators_created": False, "runs": []}
    try:
        host.require(sys.platform == "darwin", "macos_and_Xcode_required_no_Foundation_execution")
        architecture = {"aarch64": "arm64"}.get(platform.machine(), platform.machine())
        host.require(architecture in ("arm64", "x86_64"), "supported_host_architecture_required")
        sources = [HERE / "IdolyKeyboardLifecycle.h", HERE / "IdolyKeyboardLifecycle.m",
                   HERE / "tests/keyboard_lifecycle_test.m", Path(__file__).resolve(), HERE / "test_mac_menu.py"]
        pins = {str(path.relative_to(HERE)): host.sha(path) for path in sources}
        sdk = host.run(["xcrun", "--sdk", "macosx", "--show-sdk-path"]).decode().strip()
        compiler = host.run(["xcrun", "--sdk", "macosx", "--find", "clang"]).decode().strip()
        host.require(sdk.startswith("/") and compiler.startswith("/"), "absolute_Apple_tool_paths_required")
        with tempfile.TemporaryDirectory(prefix="idoly-keyboard-lifecycle-compile-") as scratch:
            binary = Path(scratch) / "keyboard_lifecycle_test"
            host.run([compiler, "-target", architecture + "-apple-macos13.0", "-isysroot", sdk,
                      "-fobjc-arc", "-fblocks", "-O2", "-Wall", "-Wextra", "-Werror",
                      "-framework", "Foundation", HERE / "IdolyKeyboardLifecycle.m",
                      HERE / "tests/keyboard_lifecycle_test.m", "-o", binary])
            image = host.inspect_host_binary(binary, architecture)
            checks = ("actual_macos_foundation_execution", "cold_or_warm_path_verified",
                      "singleton_and_field_preserved", "original_getter_unchanged", "invalid_abi_rejected",
                      "off_main_install_rejected", "idempotent_install_verified", "changed_method_rejected",
                      "foreign_singleton_not_reused", "other_receiver_not_reused",
                      "unrelated_exception_propagated", "no_destroy_or_reset")
            for mode in ("cold", "warm"):
                raw = host.run([binary, "--" + mode], timeout=30)
                host.require(0 < len(raw) <= 8192, "keyboard_lifecycle_result_bound")
                result = json.loads(raw)
                report["runs"].append(result)
                host.require(type(result) is dict and result.get("status") == "PASS"
                             and result.get("mode") == mode and all(result.get(key) is True for key in checks),
                             "keyboard_lifecycle_runtime_checks_failed")
                lifecycle = result.get("lifecycle", {})
                host.require(lifecycle.get("installed") is True and lifecycle.get("strategy") == "reuse-existing"
                             and lifecycle.get("initialize_calls") == 5
                             and lifecycle.get("original_initialize_calls") == (4 if mode == "cold" else 3)
                             and lifecycle.get("reused_existing_calls") == (1 if mode == "cold" else 2),
                             "keyboard_lifecycle_counters_failed")
            host.require(pins == {str(path.relative_to(HERE)): host.sha(path) for path in sources},
                         "keyboard_lifecycle_sources_changed_during_test")
            report.update(status="PASS", actual_macos_foundation_execution=True,
                          host_architecture=architecture, sdk=sdk, source_sha256=pins, executable=image)
    except Exception as error:
        report["error"] = str(error) if isinstance(error, ValueError) else type(error).__name__
    host.write_report(report_path, report)
    print(json.dumps({"status": report["status"], "report": str(report_path),
                      "actual_macos_foundation_execution": report["actual_macos_foundation_execution"]}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
