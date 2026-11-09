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
          "fpcr", "fpsr", "callback_context", "callback_hits", "hook_failure_fail_open", "unintercept")


def validate_report(report):
    if (not isinstance(report, dict) or report.get("schema") != 1 or report.get("ok") is not True
            or report.get("synthetic_only") is not True or report.get("abi") != "arm64-v8a"
            or report.get("shadowhook_version") != "2.0.1"
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
    if "arm64-v8a" not in execute("shell", "getprop", "ro.product.cpu.abilist").strip().split(","):
        raise ValueError("Self-test requires an ARM64-capable emulator (native or native bridge)")
    primary_abi = execute("shell", "getprop", "ro.product.cpu.abi").strip()
    mode = "native_arm64" if primary_abi == "arm64-v8a" else (
        "native_bridge" if primary_abi in ("x86_64", "x86") else "unknown")
    (artifacts / "environment.json").write_text(json.dumps(
        {"disposable_emulator": True, "arm64_execution_mode": mode}, indent=2) + "\n")
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
        # A freshly installed fixture can receive a reused UID. Scope logcat to
        # both its exact UID and a device timestamp from immediately pre-launch.
        try:
            if uid is not None and since is not None:
                raw = execute("logcat", "-b", "all", "-d", "-v", "threadtime", "--uid=" + uid,
                              "-T", since, "*:V", check=False)
                (artifacts / "failure-own-uid-logcat.txt").write_text(bounded(raw))
            elif pid is not None:
                raw = execute("logcat", "-b", "all", "-d", "-v", "threadtime", "--pid=" + pid,
                              "*:V", check=False)
                (artifacts / "failure-own-pid-logcat.txt").write_text(bounded(raw))
        except (OSError, RuntimeError, subprocess.TimeoutExpired):
            (artifacts / "failure-logcat-unavailable.txt").write_text("Fixture-scoped logcat unavailable.\n")
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
