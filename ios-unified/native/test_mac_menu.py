#!/usr/bin/env python3
"""Compile and run the shared menu helper against real macOS AppKit.

This creates no application windows or Simulators. Linux may inspect this script
but cannot establish AppKit, PlayCover or keyboard-event execution success.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import stat
import struct
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
MAX_OUTPUT = 64 * 1024


def require(value, code):
    if not value:
        raise ValueError(code)


def sha(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def run(arguments, timeout=60):
    result = subprocess.run(list(map(str, arguments)), stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            timeout=timeout, check=False)
    require(len(result.stdout) <= MAX_OUTPUT and len(result.stderr) <= MAX_OUTPUT,
            "mac_menu_tool_output_bound")
    if result.returncode:
        # Only our public source/compiler diagnostics; no environment dump.
        sys.stderr.write(result.stderr.decode("utf-8", "replace")[-16384:])
        raise ValueError("mac_menu_tool_failed")
    return result.stdout


def inspect_host_binary(path, architecture):
    info = Path(path).lstat()
    require(stat.S_ISREG(info.st_mode) and 32 <= info.st_size <= 8 * 1024**2,
            "bounded_macos_executable_required")
    with Path(path).open("rb") as source:
        header = source.read(32)
        magic, cpu, _sub, kind, count, size, _flags, _reserved = struct.unpack("<8I", header)
        require(magic == 0xFEEDFACF and cpu == {"arm64": 0x100000C, "x86_64": 0x1000007}[architecture]
                and kind == 2 and 0 < count < 512 and 0 < size <= 128 * 1024,
                "actual_host_macho_required")
        commands = source.read(size)
    require(len(commands) == size, "truncated_host_load_commands")
    at = 0
    platforms = []
    for _ in range(count):
        require(at + 8 <= size, "truncated_host_load_command")
        command, amount = struct.unpack_from("<II", commands, at)
        require(amount >= 8 and amount % 8 == 0 and at + amount <= size,
                "invalid_host_load_command")
        if command == 0x32:
            require(amount >= 24, "truncated_host_build_version")
            platforms.append(struct.unpack_from("<I", commands, at + 8)[0])
        at += amount
    require(at == size and platforms == [1], "actual_macos_platform_required")
    return {"platform": 1, "architecture": architecture, "bytes": info.st_size, "sha256": sha(path)}


def write_report(path, report):
    path = Path(path)
    raw = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode()
    require(len(raw) <= MAX_OUTPUT, "mac_menu_report_bound")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(raw)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report_path = args.report.absolute()
    require(not report_path.exists() and not report_path.is_symlink(), "fresh_mac_menu_report_required")
    report = {"schema": 1, "status": "FAIL", "actual_macos_appkit_execution": False,
              "physical_PlayCover_execution": False, "windows_or_simulators_created": False}
    try:
        require(sys.platform == "darwin", "macos_and_Xcode_required_no_AppKit_execution")
        architecture = {"aarch64": "arm64"}.get(platform.machine(), platform.machine())
        require(architecture in ("arm64", "x86_64"), "supported_host_architecture_required")
        sources = [HERE / "IdolyMacMenu.h", HERE / "IdolyMacMenu.m", HERE / "tests/mac_menu_test.m",
                   Path(__file__).resolve()]
        pins = {str(p.relative_to(HERE)): sha(p) for p in sources}
        sdk = run(["xcrun", "--sdk", "macosx", "--show-sdk-path"]).decode().strip()
        compiler = run(["xcrun", "--sdk", "macosx", "--find", "clang"]).decode().strip()
        require(sdk.startswith("/") and compiler.startswith("/"), "absolute_Apple_tool_paths_required")
        with tempfile.TemporaryDirectory(prefix="idoly-mac-menu-test-") as scratch:
            binary = Path(scratch) / "mac_menu_test"
            command = [compiler, "-target", architecture + "-apple-macos13.0", "-isysroot", sdk,
                       "-fobjc-arc", "-fblocks", "-O2", "-Wall", "-Wextra", "-Werror",
                       "-framework", "Foundation", "-framework", "AppKit",
                       HERE / "IdolyMacMenu.m", HERE / "tests/mac_menu_test.m", "-o", binary]
            run(command)
            image = inspect_host_binary(binary, architecture)
            raw = run([binary], timeout=30)
            require(0 < len(raw) <= 8192, "mac_menu_result_bound")
            result = json.loads(raw)
            require(type(result) is dict and result.get("status") == "PASS"
                    and result.get("actual_macos_appkit_execution") is True
                    and all(result.get(key) is True for key in
                            ("menu_install", "idempotence", "before_quit", "removed_item_reattachment", "target_action_dispatch",
                             "callbacks_on_main_thread", "main_menu_replacement", "off_main_rejected",
                             "shortcut_metadata_verified", "shortcut_dispatch_verified")), "mac_menu_runtime_checks_failed")
            require(pins == {str(p.relative_to(HERE)): sha(p) for p in sources},
                    "mac_menu_sources_changed_during_test")
            report.update(status="PASS", actual_macos_appkit_execution=True,
                          host_architecture=architecture, sdk=sdk, source_sha256=pins,
                          executable=image, checks=result)
    except Exception as error:
        report["error"] = str(error) if isinstance(error, ValueError) else type(error).__name__
    write_report(report_path, report)
    print(json.dumps({"status": report["status"], "report": str(report_path),
                      "actual_macos_appkit_execution": report["actual_macos_appkit_execution"]}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
