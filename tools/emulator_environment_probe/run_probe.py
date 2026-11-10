#!/usr/bin/env python3
"""Run the standalone environment probe; never install or drive the game."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time

PACKAGE = "org.idolypride.environmentprobe"
ACTIVITY = PACKAGE + "/.ProbeActivity"


def scoped_crash_log(text, pid):
    """Keep only the synthetic process and its explicitly identified tombstone."""
    line_pattern = re.compile(r"^\S+\s+\S+\s+(\d+)\s+\d+\s+[A-Z]\s+(\S+)\s*:\s?(.*)$")
    blocks, current, dumper = [], [], None
    own = []
    for line in text.splitlines():
        match = line_pattern.match(line)
        if not match:
            continue
        line_pid, tag, message = match.groups()
        if pid and line_pid == pid.split()[0]:
            own.append(line)
        if tag == "DEBUG" and message.startswith("*** ***"):
            if current:
                blocks.append(current)
            current, dumper = [line], line_pid
        elif current and tag == "DEBUG" and line_pid == dumper:
            current.append(line)
    if current:
        blocks.append(current)
    for block in blocks:
        joined = "\n".join(block)
        if ">>> " + PACKAGE + " <<<" in joined and (not pid or
                re.search(r"\bpid:\s*" + re.escape(pid.split()[0]) + r"\b", joined)):
            own.extend(block)
    return "\n".join(own) + ("\n" if own else "")


def validate_report(report):
    if not isinstance(report, dict) or report.get("schema") != 1 or report.get("synthetic_only") is not True:
        return False
    graphics, conversion = report.get("graphics", {}), report.get("conversion", {})
    if not isinstance(graphics, dict) or not isinstance(conversion, dict):
        return False
    if report.get("stage") != "complete" or conversion.get("ok") is not True or graphics.get("ok") is not True:
        return False
    return all(isinstance(graphics.get(key), dict) and
               graphics[key].get("link") is True and
               graphics[key].get("active_vec4_array_size") == 300
               for key in ("vertex_vec4_300", "fragment_vec4_300"))


def run(adb, serial, apk, output, timeout=60, record_root=False):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    base = [str(adb)] + (["-s", serial] if serial else [])

    def call(*args, limit=20, check=True):
        result = subprocess.run(base + list(args), capture_output=True, text=True,
                                timeout=limit, check=False)
        if check and result.returncode:
            raise RuntimeError("adb operation failed: " + args[0])
        return result.stdout

    if record_root:
        root = subprocess.run(base + ["root"], capture_output=True, text=True,
                              timeout=20, check=False)
        subprocess.run(base + ["wait-for-device"], capture_output=True,
                       timeout=30, check=False)
        identity = call("shell", "whoami", check=False).strip()
        root_report = {"requested": True, "command_returncode": root.returncode,
                       "reported_root": identity == "root", "whoami": identity[:128],
                       "adb_root_result": (root.stdout + root.stderr)[:1024]}
        (output / "root-capability.json").write_text(json.dumps(root_report, indent=2) + "\n")
    # Dedicated synthetic APK only; no account data, network permission, or game code.
    call("install", "-r", str(apk), limit=120)
    call("shell", "am", "force-stop", PACKAGE)
    # A failed removal must abort: a previous successful report cannot qualify this run.
    call("shell", "run-as", PACKAGE, "rm", "-f", "files/report.json")
    properties = {}
    for key in ("ro.build.version.sdk", "ro.product.cpu.abilist", "ro.dalvik.vm.native.bridge",
                "ro.hardware.egl", "ro.boot.qemu.avd_name", "ro.build.version.incremental"):
        properties[key] = call("shell", "getprop", key).strip()
    bridge_hash = call("shell", "sha256sum", "/system/lib64/libndk_translation.so", check=False).split()
    if bridge_hash and len(bridge_hash[0]) == 64 and all(c in "0123456789abcdef" for c in bridge_hash[0]):
        properties["libndk_translation_sha256"] = bridge_hash[0]
    call("shell", "am", "start", "-W", "-n", ACTIVITY)
    report = None
    first_pid = None
    last_pid = None
    failure = "timeout"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pid = call("shell", "pidof", PACKAGE, check=False).strip()
        if pid and first_pid is None:
            first_pid = pid
        last_pid = pid
        content = call("shell", "run-as", PACKAGE, "cat", "files/report.json", check=False)
        if content:
            try:
                parsed = json.loads(content)
            except ValueError:
                parsed = None
            if isinstance(parsed, dict):
                report = parsed
                if parsed.get("stage") == "complete":
                    failure = None
                    break
        if first_pid and not pid:
            failure = "probe_process_exited"
            break
        time.sleep(0.5)
    if report is not None:
        (output / "probe-report.json").write_text(json.dumps(report, indent=2) + "\n")
    # Scope logs to this synthetic process, including its identified tombstone.
    if first_pid:
        own = call("logcat", "-d", "--pid=" + first_pid.split()[0],
                   "IdolyEnvironmentProbe:I", "ndk_translation:E", "libc:F", "AndroidRuntime:E", "*:S", check=False)
        (output / "probe-own-logcat.txt").write_text(own)
    crash = call("logcat", "-d", "-b", "crash", check=False)
    (output / "probe-crash-logcat.txt").write_text(scoped_crash_log(crash, first_pid))
    screenshot = subprocess.run(base + ["exec-out", "screencap", "-p"],
                                capture_output=True, timeout=20, check=False)
    if screenshot.returncode == 0:
        (output / "probe.png").write_bytes(screenshot.stdout)
    summary = {"schema": 1, "synthetic_only": True, "runtime_attempted": True,
               "environment_compatible": validate_report(report), "failure": failure,
               "first_pid": first_pid, "last_pid": last_pid, "properties": properties,
               "game_installed_or_launched": False,
               "driver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary))
    return summary["environment_compatible"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apk", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--adb", default="adb")
    parser.add_argument("--serial")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--record-root", action="store_true",
                        help="Record adb root/whoami support on the dedicated test emulator; not a pass requirement")
    args = parser.parse_args()
    raise SystemExit(0 if run(args.adb, args.serial, args.apk, args.output, args.timeout, args.record_root) else 1)


if __name__ == "__main__":
    main()
