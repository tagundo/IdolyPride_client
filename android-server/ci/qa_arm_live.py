#!/usr/bin/env python3
"""Focused native ARM64 live-engine proof on a fresh disposable emulator.

The broad server regression runs separately. This driver checks the new native
library, explicit opt-in, real encrypted results and stopped SQLite receipts.
It prepares its own synthetic tutorial profile through normal local RPCs and
never writes the private database or invokes a game callback.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import tempfile
import time

import grpc

import qa_emulator as native
from qa_target import verify_disposable_target
from idoly_local import main_live_qa, tutorial_qa


MODE_LABEL = "첫 메인 라이브 실험 기능 사용"
SCOPE = "first_main_live_native_integration"
DEFAULT_REQUEST_ID = "9000000000000000300"


def _pid(qa):
    value = qa.adb("shell", "pidof", "-s", native.PACKAGE, check=False).strip()
    if value and not re.fullmatch(r"[0-9]+", value):
        raise RuntimeError("Could not resolve the native server process")
    return value


def wait_started(qa, schema, port, *, initial_pid, timeout):
    """Wait for a live process; stop promptly after an observed process dies.

    System.Check is read-only. No mutation is retried here. In particular a
    native SIGILL must not turn into a ten-minute opaque startup timeout.
    """
    deadline = time.monotonic() + timeout
    next_progress = time.monotonic() + 15
    observed_pid, missing = initial_pid, 0
    while time.monotonic() < deadline:
        current_pid = _pid(qa)
        if current_pid:
            if observed_pid and current_pid != observed_pid:
                raise RuntimeError("Native server process changed during startup")
            observed_pid, missing = current_pid, 0
        elif observed_pid:
            missing += 1
            if missing >= 3:
                raise RuntimeError("Native server process exited during startup")
            time.sleep(0.5)
            continue
        else:
            # A forwarded port alone is not proof of this app's native process.
            time.sleep(0.5)
            continue
        try:
            check = native.rpc(schema, port, "/api.System/Check")
        except grpc.RpcError:
            pass
        else:
            if check.keepAliveTimeMilliseconds <= 0:
                raise RuntimeError("Native startup returned no valid System.Check")
            return
        if time.monotonic() >= next_progress:
            print("Waiting for the live ARM native server process to finish startup", flush=True)
            next_progress = time.monotonic() + 15
        time.sleep(0.5)
    raise RuntimeError("Live native server did not start before the timeout")


def check_mode(qa, expected, stage):
    hierarchy = qa.capture(stage)
    matches = [node for node in hierarchy.iter("node")
               if node.get("text") == MODE_LABEL and node.get("class") == "android.widget.CheckBox"]
    if len(matches) != 1 or matches[0].get("checked") != str(expected).lower():
        raise RuntimeError("Native experimental live checkbox did not retain the expected setting")


def launch(qa):
    qa.adb("shell", "am", "start", "-n", native.ACTIVITY)


def start(qa, schema, port, timeout, stage):
    initial_pid = _pid(qa)
    qa.tap("서버 시작", stage)
    wait_started(qa, schema, port, initial_pid=initial_pid, timeout=timeout)


def stop(qa, schema, port, stage):
    qa.tap("서버 중지", stage)
    native.wait_server(schema, port, expected=False, timeout=30)
    qa.adb("shell", "am", "force-stop", native.PACKAGE)


def preserved_database(qa):
    """Keep credentials and DB bytes in a private temporary directory only."""
    with tempfile.TemporaryDirectory(prefix="idoly-arm-protected-") as directory:
        path = native._copy_private_database(qa, directory)
        with sqlite3.connect(path) as db:
            native._checkpoint(db)
            preserved = native._preserved_tables(db)
            if any(not preserved[name] for name in native.PRESERVED_TABLES):
                raise RuntimeError("Focused native proof requires actual identity, session and saved settings rows")
            return preserved


def assert_default_off(schema, port, token):
    before = native.rpc(schema, port, "/api.User/Get", token).SerializeToString(deterministic=True)
    request = schema.request_type("/api.Quest/Start")(
        questId="qt-main-1-001-01", deckNumber=1, playCount=1)
    try:
        native.rpc(schema, port, "/api.Quest/Start", token, request, request_id=DEFAULT_REQUEST_ID)
    except grpc.RpcError as error:
        if error.code() != grpc.StatusCode.UNIMPLEMENTED:
            raise
    else:
        raise RuntimeError("Experimental main live was enabled by default")
    if native.rpc(schema, port, "/api.User/Get", token).SerializeToString(deterministic=True) != before:
        raise RuntimeError("Disabled main live changed the snapshot")


def exercise(qa, schema, grpc_port, master_dir, startup_timeout):
    """Use one original session across four real native process starts."""
    native.bind_starter_contract(qa, schema, master_dir)
    launch(qa)
    check_mode(qa, False, "01-default-mode")
    start(qa, schema, grpc_port, startup_timeout, "02-default-start")
    print("Checking the fresh native ARM profile and disabled live route", flush=True)
    check, login = native.bootstrap(schema, grpc_port)
    if check.keepAliveTimeMilliseconds <= 0 or not login.gameAuthToken:
        raise RuntimeError("Native ARM bootstrap did not produce a valid local session")
    token = login.gameAuthToken
    initial = native.rpc(schema, grpc_port, "/api.User/Get", token)
    native.assert_starter_roster(initial)
    native.assert_starter_home_positions(initial)
    inventory = native.assert_initial_inventory(initial, master_dir)
    assert_default_off(schema, grpc_port, token)

    home_request = schema.request_type("/api.Home/Login")()
    home_request.settingInfo.soundBgm = 37
    home_request.settingInfo.soundEffect = 29
    home_request.settingInfo.soundVoice = 61
    home_request.settingInfo.frameRate = 30
    home_request.settingInfo.nightMode = True
    native.rpc(schema, grpc_port, "/api.Home/Login", token, home_request)
    home = native.rpc(schema, grpc_port, "/api.Home/Enter", token)
    if not home.currentMainAreaId:
        raise RuntimeError("Native ARM Home.Enter did not resolve its starting area")
    native.rpc(schema, grpc_port, "/api.Home/SetReview", token)
    stop(qa, schema, grpc_port, "03-default-stop")
    preserved = preserved_database(qa)

    launch(qa)
    check_mode(qa, False, "04-opt-in-before")
    qa.tap(MODE_LABEL, "05-opt-in")
    check_mode(qa, True, "06-opt-in-checked")
    print("Loading the actual ARM native library through the app opt-in", flush=True)
    start(qa, schema, grpc_port, startup_timeout, "07-native-library-start")
    native.rpc(schema, grpc_port, "/api.Tutorial/Init", token,
               schema.request_type("/api.Tutorial/Init")(name="QAManager"))
    tutorial = tutorial_qa.run_tutorial_continuation(schema,
        lambda path, request: native.rpc(schema, grpc_port, path, token, request),
        master_dir, label="Android native")
    # The first normal home access after tutorial completion creates the local
    # lesson clock. It grants nothing and gives the live proof a clock to retain.
    native.rpc(schema, grpc_port, "/api.Home/Enter", token)
    stop(qa, schema, grpc_port, "08-tutorial-fixture-stop")
    native.verify_upgrade_database(qa, preserved)
    original_clock, attempts = native.verify_main_live_database(qa, schema)
    if attempts:
        raise RuntimeError("Fresh focused native profile already has main-live attempts")

    launch(qa)
    check_mode(qa, True, "09-mode-persisted")
    start(qa, schema, grpc_port, startup_timeout, "10-live-start")
    invoke = lambda path, request, identity: native.rpc(schema, grpc_port, path, token,
                                                       request, request_id=identity)
    print("Computing the ARM first main live and distinct request replay", flush=True)
    receipt = main_live_qa.run_main_live_checks(schema, invoke, master_dir, label="Android native")
    qa.capture("11-live-computed")
    stop(qa, schema, grpc_port, "12-live-stop")
    native.verify_upgrade_database(qa, preserved)
    clock, attempts = native.verify_main_live_database(qa, schema, receipt, expected_clock=original_clock)

    launch(qa)
    check_mode(qa, True, "13-restart-mode-persisted")
    start(qa, schema, grpc_port, startup_timeout, "14-cache-restart")
    print("Checking the original ARM responses after a native process restart", flush=True)
    main_live_qa.assert_main_live_retries(schema, invoke, master_dir, receipt)
    qa.capture("15-live-cached")
    stop(qa, schema, grpc_port, "16-final-stop")
    native.verify_upgrade_database(qa, preserved)
    native.verify_main_live_database(qa, schema, receipt, expected_clock=clock, expected_attempts=attempts)
    return {
        "qa_scope": SCOPE, "device_game_client_tested": False,
        "full_legacy_regression_tested": False,
        "target": ("Android ARM64-only native server on Cuttlefish"
                   if getattr(qa, "target_evidence", {}).get("kind") == "cuttlefish_arm64_only"
                   else "Android ARM64 native server under emulator translation"),
        "system_check": True, "local_auth": True, "starter_roster_complete": True,
        "home_positions_distinct": True, "initial_inventory_master_backed": True,
        "default_unit_complete": True, **inventory,
        "tutorial_prepared_through_rpc": True, "tutorial_fixture": tutorial,
        "protected_baseline_before_native_init": True,
        "native_go_init_verified": True, "mode_setting_persisted": True, "main_live": receipt,
        "main_live_first_quest": True, "main_live_mode_default_off": True,
        "main_live_opt_in": True, "main_live_persisted": True,
        "main_live_attempts_persisted": True, "main_live_clock_preserved": True,
        "main_live_identity_preserved": True, "main_live_sessions_preserved": True,
        "main_live_settings_preserved": True, "main_live_cached_no_grant": True,
        "final_stop": True,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apk", type=Path, required=True)
    parser.add_argument("--descriptor-set", type=Path, default=Path("data/protocol/idolypride-6.1.1.pb"))
    parser.add_argument("--master-dir", type=Path, default=Path("data/master-json"))
    parser.add_argument("--artifacts", type=Path, default=Path("data/android-server-qa/production-arm64"))
    parser.add_argument("--adb", default="adb")
    parser.add_argument("--serial", default="emulator-5554")
    parser.add_argument("--startup-timeout", type=float, default=600)
    args = parser.parse_args(argv)
    if args.startup_timeout <= 0:
        parser.error("--startup-timeout must be positive")
    qa = native.QA(args.adb, args.serial, args.artifacts)
    result = {"ok": False, "qa_scope": SCOPE, "device_game_client_tested": False,
              "full_legacy_regression_tested": False}
    verified_target = False
    try:
        result["target_evidence"] = verify_disposable_target(qa.adb, args.serial)
        qa.target_evidence = result["target_evidence"]
        apk = args.apk.resolve(strict=True)
        with apk.open("rb") as stream:
            result["apk_sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
        qa.adb("install", "-r", "-g", str(apk))
        if qa.adb("shell", "run-as", native.PACKAGE, "ls", native.PRIVATE_DATABASE, check=False).strip():
            raise RuntimeError("Focused native proof requires a freshly cleared disposable server app")
        package = qa.adb("shell", "dumpsys", "package", native.PACKAGE)
        (args.artifacts / "package.txt").write_text(package, encoding="utf-8")
        if not re.search(r"\bprimaryCpuAbi=arm64-v8a\b", package):
            raise RuntimeError("Focused native proof requires the installed production ARM64 APK")
        result["installed_primary_cpu_abi"] = "arm64-v8a"
        verified_target = True
        qa.adb("logcat", "-c")
        qa.adb("shell", "am", "force-stop", native.PACKAGE)
        port = qa.forward(50051)
        schema = native.Schema.from_descriptor_set(args.descriptor_set)
        result.update(exercise(qa, schema, port, args.master_dir, args.startup_timeout))
        result["ok"] = True
    except BaseException as error:
        result["error_type"], result["error"] = type(error).__name__, str(error)
        raise
    finally:
        try:
            if verified_target:
                try:
                    qa.capture("90-final")
                except Exception:
                    pass
                qa.close()
        finally:
            (args.artifacts / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
