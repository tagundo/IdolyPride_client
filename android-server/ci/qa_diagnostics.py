#!/usr/bin/env python3
"""Verify the production own-PID diagnostics channel on an emulator only.

Runs a Java-only synthetic probe, not the game. Raw synthetic probe logcat is
retained as QA evidence; the server's structured state/UI/export must exclude
its fake secret, exception message, arguments and private file path.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
import time
from urllib.request import urlopen

from qa_emulator import ACTIVITY, PACKAGE, QA, wait_server
from idoly_local.schema import Schema


PROBE = "game.qualiarts.idolypride.local.diagnostics"
PROBE_ACTIVITY = PROBE + "/game.qualiarts.idolypride.diagnostics.ProbeActivity"
FRAME = "Solis.DiagnosticsProbe.SafeFrame"
PHASE = "actor_motion_wait"
PHASE_SUMMARY = "캐릭터 모션 로딩 단계"
FORBIDDEN = ("IDOLY_DIAGNOSTICS_FAKE_SECRET", "/FAKE_DIAGNOSTICS_PRIVATE/", "secret.cs:123",
             "System.String value=", "[0x00000]")


def clean(value):
    encoded = json.dumps(value, ensure_ascii=False)
    if any(marker in encoded for marker in FORBIDDEN):
        raise RuntimeError("Synthetic raw log content reached the server diagnostic surface")


def get_status(port):
    with urlopen("http://127.0.0.1:" + str(port) + "/diagnostics/status", timeout=3) as response:
        return json.loads(response.read())


def network_observation(status):
    """Validate the actual production provider's cumulative own-UID sample.

    The fixture emits logs only; neither it nor this QA script submits network
    events. Samples must arrive through the unchanged TrafficStats producer.
    """
    if status.get("network_unavailable") is True:
        raise RuntimeError("Production own-UID TrafficStats counters are unavailable")
    network = status.get("network")
    if network is None:
        return None
    fields = ("rx_bytes", "tx_bytes", "elapsed_ms")
    if (not isinstance(network, dict) or set(network) != set(fields)
            or any(type(network[field]) is not int or network[field] < 0 for field in fields)
            or network["elapsed_ms"] < 5000):
        raise RuntimeError("Production network sample is not nonnegative cumulative counters after five seconds")
    return {field: network[field] for field in fields}


def _tap_node(qa, node):
    """Tap bounds taken from the current UI hierarchy, never guessed pixels."""
    bounds = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", node.get("bounds", ""))
    if bounds is None or node.get("enabled") != "true":
        raise RuntimeError("Observed UI control has no enabled bounds")
    left, top, right, bottom = map(int, bounds.groups())
    if left >= right or top >= bottom:
        raise RuntimeError("Observed UI control has empty bounds")
    qa.adb("shell", "input", "tap", str((left + right) // 2), str((top + bottom) // 2))


def _picker_node(tree, *, texts=(), descriptions=()):
    for node in tree.iter("node"):
        if node.get("enabled") != "true":
            continue
        if node.get("text", "") in texts or node.get("content-desc", "") in descriptions:
            return node
    return None


def _tap_initial_start(qa, timeout=60):
    """Await native controls; dismiss only the observed emulator launcher ANR."""
    deadline = time.monotonic() + timeout
    attempt = 0
    actions = []
    capture_errors = []
    while time.monotonic() < deadline:
        try:
            tree = qa.capture("01-server-start-" + str(attempt))
        except RuntimeError as error:
            capture_errors.append(str(error))
            (qa.artifacts / "startup-capture-errors.txt").write_text("\n".join(capture_errors) + "\n")
        else:
            # API30 Google images can present a cold-launch Pixel Launcher ANR
            # over a ready server. Never dismiss our app's ANR or an unknown dialog.
            launcher_anr = any(node.get("package") == "android"
                               and node.get("resource-id") == "android:id/alertTitle"
                               and node.get("text") == "Pixel Launcher isn't responding"
                               for node in tree.iter("node"))
            if launcher_anr and not actions:
                close = next((node for node in tree.iter("node")
                              if node.get("package") == "android"
                              and node.get("resource-id") == "android:id/aerr_close"
                              and node.get("text") == "Close app"
                              and node.get("enabled") == "true"), None)
                if close is not None:
                    _tap_node(qa, close)
                    actions.append("Dismissed observed Pixel Launcher ANR using system Close app")
                    (qa.artifacts / "startup-system-dialog-actions.json").write_text(json.dumps(actions) + "\n")
                    qa.adb("shell", "am", "start", "-n", ACTIVITY)
            elif not launcher_anr:
                start = next((node for node in tree.iter("node")
                              if node.get("package") == PACKAGE and node.get("text") == "서버 시작"
                              and node.get("enabled") == "true"), None)
                if start is not None:
                    _tap_node(qa, start)
                    return actions
        attempt += 1
        time.sleep(0.5)
    raise RuntimeError("Native server Start control was not available within 60 seconds")


def _capture_picker(qa, stage, *, texts=(), timeout=20):
    """Wait through a cold DocumentsUI launch without repeating the UI tap."""
    deadline = time.monotonic() + timeout
    errors = []
    while time.monotonic() < deadline:
        try:
            tree = qa.capture(stage)
        except RuntimeError as error:
            errors.append(str(error))
            (qa.artifacts / (stage + "-capture-errors.txt")).write_text("\n".join(errors) + "\n")
        else:
            packages = {node.get("package", "") for node in tree.iter("node")}
            if any("documentsui" in package.lower() for package in packages):
                if not texts or _picker_node(tree, texts=texts) is not None:
                    return tree
        time.sleep(0.5)
    return None


def optional_export(qa):
    """Exercise real SAF UI; unavailable images remain explicitly unverified.

    Standard emulator images have DocumentsUI, while ATD images may omit it.
    Every picker action below uses a newly captured accessibility hierarchy.
    """
    resolver = qa.adb("shell", "cmd", "package", "resolve-activity", "--brief",
                      "-a", "android.intent.action.CREATE_DOCUMENT",
                      "-c", "android.intent.category.OPENABLE", "-t", "application/json", check=False)
    (qa.artifacts / "document-picker-resolver.txt").write_text(resolver, encoding="utf-8")
    # Resolver output varies across Android versions. Retain it as evidence,
    # then let the actual app intent and observed picker establish availability.
    qa.adb("shell", "rm", "-f", "/sdcard/Download/IdolyPride-diagnostics.json")
    qa.tap("진단 기록 내보내기", "export-open")
    tree = _capture_picker(qa, "export-picker")
    if tree is None:
        return {"checked": False, "reason": "document_picker_not_opened"}

    save = _picker_node(tree, texts=("SAVE", "Save", "저장", "保存"))
    if save is None:
        # Fresh standard images normally start in Downloads. Only navigate when
        # the observed picker has no enabled Save control in its current root.
        roots = _picker_node(tree, descriptions=("Show roots", "탐색 메뉴 표시", "ルートを表示"))
        if roots is None:
            roots = next((node for node in tree.iter("node")
                          if node.get("resource-id") == "android:id/home" and node.get("enabled") == "true"), None)
        if roots is None:
            return {"checked": False, "reason": "document_picker_save_unavailable"}
        _tap_node(qa, roots)
        tree = _capture_picker(qa, "export-roots", texts=("Downloads", "Download", "다운로드", "ダウンロード"))
        if tree is None:
            return {"checked": False, "reason": "document_picker_downloads_unavailable"}
        downloads = _picker_node(tree, texts=("Downloads", "Download", "다운로드", "ダウンロード"))
        if downloads is None:
            return {"checked": False, "reason": "document_picker_downloads_unavailable"}
        _tap_node(qa, downloads)
        tree = _capture_picker(qa, "export-downloads", texts=("SAVE", "Save", "저장", "保存"))
        if tree is None:
            return {"checked": False, "reason": "document_picker_save_unavailable"}
        save = _picker_node(tree, texts=("SAVE", "Save", "저장", "保存"))
        if save is None:
            return {"checked": False, "reason": "document_picker_save_unavailable"}
    _tap_node(qa, save)
    document_path = "/sdcard/Download/IdolyPride-diagnostics.json"
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        raw = qa.adb("shell", "cat", document_path, check=False)
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
        (qa.artifacts / "server-export-document-path.txt").write_text(document_path + "\n")
        qa.capture("export-saved")
        return {"checked": True, "safe": True, "document_path": document_path}
    return {"checked": False, "reason": "document_not_readable_from_selected_downloads"}


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
    parser.add_argument("--require-export", action="store_true", help="Fail unless real SAF export is verified")
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
        result["startup_system_dialog_actions"] = _tap_initial_start(qa)
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
        network_samples = []
        while time.monotonic() < deadline:
            try:
                latest = get_status(asset_port)
                clean(latest)
            except (OSError, ValueError):
                time.sleep(0.5)
                continue
            network = network_observation(latest)
            if network is not None and (not network_samples or network != network_samples[-1]):
                if network_samples and any(network[key] < network_samples[-1][key]
                                           for key in ("rx_bytes", "tx_bytes", "elapsed_ms")):
                    raise RuntimeError("Production own-UID network counters decreased within the collector session")
                network_samples.append(network)
            exception = latest.get("latest_exception") or {}
            phase = latest.get("phase") or {}
            if (latest.get("collector_started") is True and latest.get("logcat_running") is True
                    and latest.get("shader_warmup_wait") is True
                    and exception.get("type") == "NullReferenceException"
                    and FRAME in exception.get("frames", [])
                    and phase.get("code") == PHASE and phase.get("summary") == PHASE_SUMMARY
                    and len(network_samples) >= 2
                    and network_samples[-1]["elapsed_ms"] - network_samples[0]["elapsed_ms"] >= 5000):
                break
            time.sleep(0.5)
        else:
            raise RuntimeError("Production exception, phase and cumulative TrafficStats observations did not reach the server before timeout")
        (args.artifacts / "diagnostics-status.json").write_text(json.dumps(latest, ensure_ascii=False, indent=2) + "\n")
        (args.artifacts / "production-network-observations.json").write_text(
            json.dumps(network_samples, indent=2) + "\n")
        # Evidence must prove the raw input was actually emitted in the probe's
        # own PID. The raw QA log is deliberately separate from server exports.
        pid = qa.adb("shell", "pidof", "-s", PROBE).strip()
        raw_probe = qa.adb("logcat", "-d", "--pid=" + pid, "-v", "brief", "Unity:V", "*:S")
        if (FORBIDDEN[0] not in raw_probe or FORBIDDEN[1] not in raw_probe
                or raw_probe.count("IDOLY_PHASE:" + PHASE) < 2):
            raise RuntimeError("Synthetic exception and repeating fixed phase input were not observed in probe own-PID logcat")
        (args.artifacts / "synthetic-probe-logcat.txt").write_text(raw_probe, encoding="utf-8")
        qa.adb("shell", "am", "start", "-n", ACTIVITY)
        ui_deadline = time.monotonic() + 30
        while time.monotonic() < ui_deadline:
            tree = qa.capture("04-server-diagnostics")
            text = "\n".join(node.get("text", "") for node in tree.iter("node"))
            clean(text)
            if ("NullReferenceException" in text and PHASE_SUMMARY in text
                    and "게임 전체 네트워크 수신" in text and "송신" in text
                    and "초 누적" in text and "다운로드 진행률 아님" in text):
                break
            time.sleep(0.5)
        else:
            raise RuntimeError("Native server UI omitted the received exception, phase summary or cumulative network labels")
        (args.artifacts / "server-ui.txt").write_text(text, encoding="utf-8")
        server_pid = qa.adb("shell", "pidof", "-s", PACKAGE).strip()
        server_log = qa.adb("logcat", "-d", "--pid=" + server_pid, "-v", "brief")
        clean(server_log)
        (args.artifacts / "server-own-pid-logcat.txt").write_text(server_log, encoding="utf-8")
        result["export"] = optional_export(qa)
        if args.require_export and result["export"].get("checked") is not True:
            raise RuntimeError("Required SAF export was not verified: " + result["export"].get("reason", "unknown"))
        qa.adb("shell", "am", "start", "-n", ACTIVITY)
        qa.tap("서버 중지", "05-server-stop")
        wait_server(schema, grpc_port, expected=False, timeout=30)
        qa.capture("06-server-stopped")
        server_started = False
        result.update(ok=True, own_pid_events_verified=True, raw_values_absent=True,
                      production_provider_e2e=True, collector_started=True, logcat_running=True,
                      sanitized_exception=True, static_frame=True, shader_wait=True,
                      phase_code=PHASE, phase_summary_visible=True,
                      production_traffic_stats=True, cumulative_network_samples=len(network_samples),
                      cumulative_network_visible=True,
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
