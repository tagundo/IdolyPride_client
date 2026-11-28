#!/usr/bin/env python3
"""Run resource-only NSBundle selection fixtures against real macOS Foundation.

No UIKit, Simulator or Unity game is launched. A second fresh process injects a
registration miss to test the fixed-identifier fallback without shipping that
injection in the device framework.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import sys
import tempfile

# Reuse the bounded Apple-tool runner and actual host Mach-O inspector. Importing
# this module creates no AppKit application; only its own main() runs menu tests.
import test_mac_menu as host

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report_path = args.report.absolute()
    host.require(not report_path.exists() and not report_path.is_symlink(), "fresh_client_data_report_required")
    report = {"schema": 1, "status": "FAIL", "actual_macos_foundation_execution": False,
              "actual_iOS_Unity_execution": False, "physical_PlayCover_execution": False,
              "windows_or_simulators_created": False, "runs": []}
    try:
        host.require(sys.platform == "darwin", "macos_and_Xcode_required_no_Foundation_execution")
        architecture = {"aarch64": "arm64"}.get(platform.machine(), platform.machine())
        host.require(architecture in ("arm64", "x86_64"), "supported_host_architecture_required")
        sources = [HERE / "IdolyClientData.h", HERE / "IdolyClientData.m", HERE / "tests/client_data_test.m",
                   Path(__file__).resolve(), HERE / "test_mac_menu.py"]
        pins = {str(path.relative_to(HERE)): host.sha(path) for path in sources}
        sdk = host.run(["xcrun", "--sdk", "macosx", "--show-sdk-path"]).decode().strip()
        compiler = host.run(["xcrun", "--sdk", "macosx", "--find", "clang"]).decode().strip()
        host.require(sdk.startswith("/") and compiler.startswith("/"), "absolute_Apple_tool_paths_required")
        with tempfile.TemporaryDirectory(prefix="idoly-client-data-compile-") as scratch:
            binary = Path(scratch) / "client_data_test"
            command = [compiler, "-target", architecture + "-apple-macos13.0", "-isysroot", sdk,
                       "-fobjc-arc", "-fblocks", "-O2", "-Wall", "-Wextra", "-Werror",
                       "-DIDOLY_CLIENT_DATA_TESTING=1", "-framework", "Foundation",
                       HERE / "IdolyClientData.m", HERE / "tests/client_data_test.m", "-o", binary]
            host.run(command)
            image = host.inspect_host_binary(binary, architecture)
            for forced in (False, True):
                raw = host.run([binary] + (["--force-fallback"] if forced else []), timeout=30)
                host.require(0 < len(raw) <= 8192, "client_data_result_bound")
                result = json.loads(raw)
                report["runs"].append(result)
                checks = ("actual_macos_foundation_execution", "fixed_identifier_scope_verified",
                          "typed_unity_setter_verified", "invalid_paths_and_metadata_rejected", "symlinks_rejected",
                          "ancestor_alias_root_accepted", "off_main_rejected", "different_language_after_selection_rejected")
                host.require(type(result) is dict and result.get("status") == "PASS"
                             and result.get("forced_registration_failure") is forced
                             and all(result.get(key) is True for key in checks), "client_data_runtime_checks_failed")
                selection = result.get("selection", {})
                host.require(selection.get("selected") is True and selection.get("language") == "ko"
                             and selection.get("bundle_identifier") == "local.idoly.client-data",
                             "client_data_selection_metadata_failed")
                if forced:
                    host.require(selection.get("fixed_identifier_fallback") is True,
                                 "client_data_forced_fallback_not_exercised")
            host.require(pins == {str(path.relative_to(HERE)): host.sha(path) for path in sources},
                         "client_data_sources_changed_during_test")
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
