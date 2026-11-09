#!/usr/bin/env python3
"""Run only the synthetic ARM64 fixture on an explicitly selected emulator."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import time


PACKAGE = "game.qualiarts.idolypride.phase_selftest"
ACTIVITY = PACKAGE + "/.SelfTestActivity"
CHECKS = ("baseline", "initialized", "installed", "original_instruction", "gpr", "simd", "sp", "nzcv",
          "fpcr", "fpsr", "callback_context", "callback_hits", "hook_failure_fail_open", "unintercept",
          "bl_baseline", "bl_installed", "bl_original_instruction", "bl_original_lr",
          "bl_callback_context", "bl_callback_hits", "bl_unintercept")


def validate_report(report):
    if (not isinstance(report, dict) or report.get("schema") != 1 or report.get("ok") is not True
            or report.get("synthetic_only") is not True or report.get("abi") != "arm64-v8a"
            or report.get("shadowhook_version") != "2.0.1"
            or any(type(report.get(name)) is not int or report[name] != 0
                   for name in ("init_result", "init_errno", "install_errno", "bl_install_errno",
                                "add_unintercept_result", "bl_unintercept_result"))
            or any(report.get(name) is not True for name in CHECKS)):
        raise ValueError("Synthetic ARM64 instruction preservation check failed")


def run(apk, *, adb, serial, artifacts):
    artifacts = Path(artifacts).resolve()
    artifacts.mkdir(parents=True, exist_ok=True)
    command = [str(adb), "-s", serial]

    def execute(*arguments, check=True):
        result = subprocess.run(command + list(arguments), capture_output=True, text=True, timeout=40)
        if check and result.returncode:
            raise RuntimeError("Self-test adb command failed: " + " ".join(arguments[:3]))
        return result.stdout

    if not serial.startswith("emulator-") or execute("shell", "getprop", "ro.kernel.qemu").strip() != "1":
        raise ValueError("Self-test accepts a disposable emulator only")
    available_abis = execute("shell", "getprop", "ro.product.cpu.abilist").strip().split(",")
    if "arm64-v8a" not in available_abis:
        raise ValueError("Self-test requires an ARM64-capable emulator (native or native bridge)")
    primary_abi = execute("shell", "getprop", "ro.product.cpu.abi").strip()
    mode = "native_arm64" if primary_abi == "arm64-v8a" else (
        "native_bridge" if primary_abi in ("x86_64", "x86") else "unknown")
    raw_bridge = execute("shell", "getprop", "ro.dalvik.vm.native.bridge").strip()
    bridge = raw_bridge if raw_bridge in ("libndk_translation.so", "libhoudini.so") else (
        "none" if raw_bridge in ("", "0", "none") else "other")
    standard_abis = ("arm64-v8a", "armeabi-v7a", "armeabi", "x86_64", "x86", "riscv64")
    (artifacts / "environment.json").write_text(json.dumps(
        {"disposable_emulator": True, "arm64_execution_mode": mode, "native_bridge": bridge,
         "primary_abi": primary_abi if primary_abi in standard_abis else "other",
         "abilist": [abi for abi in available_abis if abi in standard_abis]}, indent=2) + "\n")
    # Only this fixture's throwaway install is replaced; no other app is touched.
    execute("uninstall", PACKAGE, check=False)
    execute("install", str(Path(apk).resolve()))
    uid = None
    pid = None
    since = None

    def bounded(raw):
        encoded = raw.encode("utf-8", "replace")
        if len(encoded) > 131072:
            return "[earlier fixture output omitted]\n" + encoded[-131072:].decode("utf-8", "replace")
        return raw

    def capture_failure():
        nonlocal pid
        try:
            current_pid = execute("shell", "pidof", "-s", PACKAGE, check=False).strip()
            if current_pid.isdigit():
                pid = current_pid
        except (OSError, RuntimeError, subprocess.TimeoutExpired):
            pass
        # A freshly installed fixture can receive a reused UID. Scope logcat to
        # both its exact UID and a device timestamp from immediately pre-launch.
        uid_output = ""
        try:
            if uid is not None and since is not None:
                uid_output = execute("logcat", "-b", "all", "-d", "-v", "threadtime", "--uid=" + uid,
                                     "-T", since, "*:V", check=False)
                (artifacts / "failure-own-uid-logcat.txt").write_text(bounded(uid_output))
        except (OSError, RuntimeError, subprocess.TimeoutExpired):
            (artifacts / "failure-logcat-unavailable.txt").write_text("Fixture-scoped logcat unavailable.\n")
        if not uid_output.strip() and pid is not None and uid is not None:
            try:
                # A timestamp/zone mismatch must not hide the native init log.
                # Keep both known fixture PID and UID filters without -T; never
                # fall back to an unfiltered all-app log dump. If the PID was
                # reused by another UID, discard it before requesting logs.
                status = execute("shell", "cat", "/proc/" + pid + "/status", check=False)
                uid_lines = [line.split()[1:] for line in status.splitlines() if line.startswith("Uid:")]
                if uid_lines and any(value != uid for value in uid_lines[0]):
                    (artifacts / "failure-pid-reused.txt").write_text("Fixture PID now belongs to another UID; capture skipped.\n")
                else:
                    raw = execute("logcat", "-b", "all", "-d", "-v", "threadtime", "--pid=" + pid,
                                  "--uid=" + uid, "*:V", check=False)
                    (artifacts / "failure-own-pid-logcat.txt").write_text(bounded(raw))
            except (OSError, RuntimeError, subprocess.TimeoutExpired):
                (artifacts / "failure-pid-logcat-unavailable.txt").write_text("Fixture PID logcat unavailable.\n")
        try:
            raw = execute("shell", "dumpsys", "activity", "exit-info", PACKAGE, check=False)
            (artifacts / "failure-fixture-exit-info.txt").write_text(bounded(raw))
        except (OSError, RuntimeError, subprocess.TimeoutExpired):
            (artifacts / "failure-exit-info-unavailable.txt").write_text("Fixture exit information unavailable.\n")

    try:
        listed = execute("shell", "cmd", "package", "list", "packages", "-U", PACKAGE)
        expression = re.compile(r"package:" + re.escape(PACKAGE) + r"\s+uid:([0-9]+)")
        matches = [match.group(1) for line in listed.splitlines()
                   if (match := expression.fullmatch(line.strip()))]
        if len(matches) != 1:
            raise RuntimeError("Could not resolve the exact synthetic fixture UID")
        uid = matches[0]
        timestamp = execute("shell", "date", "+%m-%dT%H:%M:%S.000").strip()
        if not re.fullmatch(r"[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.000", timestamp):
            raise RuntimeError("Could not establish a device timestamp for fixture-only logs")
        since = timestamp.replace("T", " ")
        existing_pid = execute("shell", "pidof", "-s", PACKAGE, check=False).strip()
        if existing_pid.isdigit():
            pid = existing_pid
        execute("shell", "am", "start", "-W", "-n", ACTIVITY)
        launched_pid = execute("shell", "pidof", "-s", PACKAGE, check=False).strip()
        if launched_pid.isdigit():
            pid = launched_pid
        deadline = time.monotonic() + 45
        report = None
        while time.monotonic() < deadline:
            raw = execute("shell", "run-as", PACKAGE, "cat", "files/selftest.json", check=False).strip()
            try:
                candidate = json.loads(raw)
            except (ValueError, TypeError):
                time.sleep(0.5)
                continue
            report = candidate
            break
        if report is None:
            raise RuntimeError("Timed out waiting for synthetic ARM64 report")
        (artifacts / "selftest.json").write_text(json.dumps(report, indent=2) + "\n")
        validate_report(report)
        return report
    except Exception:
        capture_failure()
        raise
    finally:
        try:
            current_pid = execute("shell", "pidof", "-s", PACKAGE, check=False).strip()
            if current_pid.isdigit():
                pid = current_pid
            if pid is not None:
                log = execute("logcat", "-d", "--pid=" + pid, "-v", "brief", "IDOLY_SELFTEST:I", "*:S", check=False)
                (artifacts / "selftest-logcat.txt").write_text(bounded(log))
        except (OSError, RuntimeError, subprocess.TimeoutExpired):
            pass
        try:
            execute("shell", "am", "force-stop", PACKAGE, check=False)
        except (OSError, RuntimeError, subprocess.TimeoutExpired):
            pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apk", type=Path, required=True)
    parser.add_argument("--adb", default="adb")
    parser.add_argument("--serial", required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.apk, adb=args.adb, serial=args.serial, artifacts=args.artifacts), indent=2))


if __name__ == "__main__":
    main()
