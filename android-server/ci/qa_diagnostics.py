#!/usr/bin/env python3
"""Verify the production own-PID diagnostics channel on an emulator only.

Runs a Java-only synthetic probe, not the game. Raw synthetic probe logcat is
retained as QA evidence; the server's structured state/UI/export must exclude
its fake secret, exception message, arguments and private file path.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time
from urllib.request import urlopen

from qa_emulator import ACTIVITY, PACKAGE, QA, wait_server
from idoly_local.schema import Schema


PROBE = "game.qualiarts.idolypride.local.diagnostics"
PROBE_ACTIVITY = PROBE + "/game.qualiarts.idolypride.diagnostics.ProbeActivity"
FRAME = "Solis.DiagnosticsProbe.SafeFrame"
FORBIDDEN = ("IDOLY_DIAGNOSTICS_FAKE_SECRET", "/FAKE_DIAGNOSTICS_PRIVATE/", "secret.cs:123",
             "System.String value=", "[0x00000]")


def clean(value):
    encoded = json.dumps(value, ensure_ascii=False)
    if any(marker in encoded for marker in FORBIDDEN):
        raise RuntimeError("Synthetic raw log content reached the server diagnostic surface")


def get_status(port):
    with urlopen("http://127.0.0.1:" + str(port) + "/diagnostics/status", timeout=3) as response:
        return json.loads(response.read())


def optional_export(qa):
    """Use the system document picker when it exists in this emulator image."""
    try:
        qa.tap("진단 기록 내보내기", "export-open")
        tree = qa.capture("export-picker")
    except RuntimeError:
        return {"checked": False, "reason": "document_picker_unavailable"}
    labels = {node.get("text", "") for node in tree.iter("node")}
    save = next((label for label in ("SAVE", "Save", "저장") if label in labels), None)
    if save is None:
        qa.adb("shell", "input", "keyevent", "4")
        return {"checked": False, "reason": "document_picker_save_unavailable"}
    qa.tap(save, "export-save")
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        raw = qa.adb("shell", "cat", "/sdcard/Download/IdolyPride-diagnostics.json", check=False)
        try:
            exported = json.loads(raw)
        except ValueError:
            time.sleep(0.5)
            continue
        clean(exported)
        text = json.dumps(exported, ensure_ascii=False)
        if FRAME not in text or "NullReferenceException" not in text:
            raise RuntimeError("Saved diagnostic export omitted the synthetic exception")
        (qa.artifacts / "server-export.json").write_text(json.dumps(exported, ensure_ascii=False, indent=2) + "\n")
        qa.capture("export-saved")
        return {"checked": True, "safe": True}
    return {"checked": False, "reason": "document_not_readable_from_default_downloads"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server-apk", type=Path, required=True)
    parser.add_argument("--probe-apk", type=Path, required=True)
    parser.add_argument("--descriptor-set", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, default=Path("data/android-diagnostics-qa"))
    parser.add_argument("--adb", default="adb")
    parser.add_argument("--serial", default="emulator-5554")
    parser.add_argument("--startup-timeout", type=float, default=600)
    parser.add_argument("--timeout", type=float, default=120)
    args = parser.parse_args()
    if args.startup_timeout <= 0 or args.timeout <= 0:
        parser.error("Timeouts must be positive")
    qa = QA(args.adb, args.serial, args.artifacts)
    result = {"ok": False, "target": "disposable Android emulator", "actual_game_tested": False,
              "synthetic_probe": True, "production_provider_e2e": False}
    server_started = guarded = False
    try:
        if not args.serial.startswith("emulator-") or qa.adb("shell", "getprop", "ro.kernel.qemu").strip() != "1":
            raise RuntimeError("Diagnostics probe QA accepts a disposable emulator only")
        guarded = True
        qa.adb("install", "-r", "-g", str(args.server_apk.resolve()))
        qa.adb("install", "-r", "-g", str(args.probe_apk.resolve()))
        qa.adb("logcat", "-c")
        qa.adb("shell", "am", "force-stop", PROBE)
        qa.adb("shell", "am", "force-stop", PACKAGE)
        qa.adb("shell", "am", "start", "-n", ACTIVITY)
        grpc_port, asset_port = qa.forward(50051), qa.forward(8080)
        schema = Schema.from_descriptor_set(args.descriptor_set)
        qa.tap("서버 시작", "01-server-start")
        server_started = True
        wait_server(schema, grpc_port, timeout=args.startup_timeout)
        qa.capture("02-server-ready")
        launch = qa.adb("shell", "am", "start", "-W", "-n", PROBE_ACTIVITY)
        (args.artifacts / "probe-launch.txt").write_text(launch, encoding="utf-8")
        if "Error:" in launch or "Exception" in launch:
            raise RuntimeError("Synthetic probe activity did not launch")
        qa.capture("03-probe-running")
        deadline = time.monotonic() + args.timeout
        latest = {}
        while time.monotonic() < deadline:
            try:
                latest = get_status(asset_port)
                clean(latest)
            except (OSError, ValueError):
                time.sleep(0.5)
                continue
            exception = latest.get("latest_exception") or {}
            if (latest.get("collector_started") is True and latest.get("logcat_running") is True
                    and latest.get("shader_warmup_wait") is True
                    and exception.get("type") == "NullReferenceException"
                    and FRAME in exception.get("frames", [])):
                break
            time.sleep(0.5)
        else:
            raise RuntimeError("Production own-PID diagnostic events did not reach the server before timeout")
        (args.artifacts / "diagnostics-status.json").write_text(json.dumps(latest, ensure_ascii=False, indent=2) + "\n")
        # Evidence must prove the raw input was actually emitted in the probe's
        # own PID. The raw QA log is deliberately separate from server exports.
        pid = qa.adb("shell", "pidof", "-s", PROBE).strip()
        raw_probe = qa.adb("logcat", "-d", "--pid=" + pid, "-v", "brief", "Unity:V", "*:S")
        if FORBIDDEN[0] not in raw_probe or FORBIDDEN[1] not in raw_probe:
            raise RuntimeError("Synthetic raw exception input was not observed in probe logcat")
        (args.artifacts / "synthetic-probe-logcat.txt").write_text(raw_probe, encoding="utf-8")
        qa.adb("shell", "am", "start", "-n", ACTIVITY)
        tree = qa.capture("04-server-diagnostics")
        text = "\n".join(node.get("text", "") for node in tree.iter("node"))
        clean(text)
        if "NullReferenceException" not in text:
            raise RuntimeError("Native server UI omitted the received exception")
        (args.artifacts / "server-ui.txt").write_text(text, encoding="utf-8")
        server_pid = qa.adb("shell", "pidof", "-s", PACKAGE).strip()
        server_log = qa.adb("logcat", "-d", "--pid=" + server_pid, "-v", "brief")
        clean(server_log)
        (args.artifacts / "server-own-pid-logcat.txt").write_text(server_log, encoding="utf-8")
        result["export"] = optional_export(qa)
        qa.adb("shell", "am", "start", "-n", ACTIVITY)
        qa.tap("서버 중지", "05-server-stop")
        wait_server(schema, grpc_port, expected=False, timeout=30)
        qa.capture("06-server-stopped")
        server_started = False
        result.update(ok=True, own_pid_events_verified=True, raw_values_absent=True,
                      production_provider_e2e=True, collector_started=True, logcat_running=True,
                      sanitized_exception=True, static_frame=True, shader_wait=True,
                      server_status_safe=True, server_ui_safe=True, final_stop=True)
    except BaseException as error:
        result.update(error_type=type(error).__name__, error=str(error))
        raise
    finally:
        if guarded:
            if server_started:
                try:
                    qa.adb("shell", "am", "start", "-n", ACTIVITY)
                    qa.tap("서버 중지", "cleanup-server-stop")
                except Exception:
                    pass
            qa.adb("shell", "am", "force-stop", PROBE, check=False)
            try:
                qa.capture("07-final")
            except Exception:
                pass
            qa.close()
        (args.artifacts / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
