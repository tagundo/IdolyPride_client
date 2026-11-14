#!/usr/bin/env python3
"""Run the integrated server's fake Unity host in one disposable iOS Simulator.

Actual execution requires macOS/Xcode. Portable tests mock simulator control;
they do not establish simulator, device, game, or PlayCover compatibility.
Only a UUID returned by this invocation's `simctl create` may be changed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import plistlib
import re
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import time
import uuid
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

BUNDLE_ID = "game.qualiarts.idolypride.iosprobe"
# ServerData archives contain a data/ root; the installer removes that prefix
# when creating the writable core directory. The probe reads the archive itself.
DESCRIPTOR_MEMBER = "data/protocol/idolypride-6.1.1.pb"
MAX_JSON = 64 * 1024
MAX_DESCRIPTOR = 16 * 1024 * 1024
MAX_RESPONSE = 4 * 1024 * 1024
MAX_COMMAND_OUTPUT = 2 * 1024 * 1024
MAX_TOOL_DETAIL = 8 * 1024
RPC_PATHS = ("/api.System/Check", "/api.Auth/Login", "/api.Home/Enter")
# A well-formed unknown protobuf varint makes empty requests exercise AES too.
PUBLIC_PROBE_FIELD = b"\xc0\xa3\x09\x01"  # field 19000, wire type 0, value 1
LAUNCHER_FAILURE_CODES = frozenset((
    "premature_launch_not_ignored", "server_left_ready_before_launch",
    "unity_started_before_launch_button", "ready_launcher_not_visible",
    "ready_launcher_flags_differ", "ready_launch_button_missing",
    "ready_launch_button_ambiguous", "ready_launch_button_disabled",
    "ready_launch_button_title_differs", "ready_launch_action_missing",
    "ready_launch_action_not_dispatched",
    "early_status_correlation_failed", "server_not_ready_before_capture", "ready_capture_restarted_server",
    "settings_menu_open_failed", "settings_menu_not_presented", "settings_menu_controls_or_layout_failed",
    "settings_web_readiness_or_layout_failed", "settings_return_action_failed", "settings_menu_not_dismissed",
    "final_report_write_failed",
))
NATIVE_CHECKPOINT_STAGES = frozenset((
    "delegate_entered", "window_ready", "server_starting", "server_ready",
    "unity_requests_captured", "premature_launch_checked", "launch_action_requested",
    "launch_action_dispatched", "unity_forwarded", "status_received", "crypto_received",
    "loopback_checked", "report_written",
))
CHECKPOINT_READ_CODES = frozenset((
    "invalid_bounded_file", "file_changed_while_opening", "file_changed_while_reading",
    "json_size_bound", "duplicate_json_key", "nonfinite_json", "invalid_json", "json_object_required",
))


class ProbeError(ValueError):
    """A bounded, credential-free failure code suitable for the JSON audit."""


def require(value, code):
    if not value:
        raise ProbeError(code)


def read_bounded(path, maximum):
    path = Path(path)
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= maximum,
            "invalid_bounded_file")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        opened = os.fstat(fd)
        require(stat.S_ISREG(opened.st_mode) and 0 < opened.st_size <= maximum,
                "invalid_bounded_file")
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            error = ProbeError("file_changed_while_opening")
            error.regular_replacement = True
            raise error
        require((before.st_size, before.st_mtime_ns) == (opened.st_size, opened.st_mtime_ns),
                "file_changed_while_opening")
        with os.fdopen(fd, "rb", closefd=False) as incoming:
            raw = incoming.read(maximum + 1)
        after = os.fstat(fd)
        require(len(raw) == before.st_size and after.st_size == before.st_size
                and after.st_mtime_ns == before.st_mtime_ns,
                "file_changed_while_reading")
        return raw
    finally:
        os.close(fd)


def parse_json(raw, maximum=MAX_JSON):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate_json_key")
            result[key] = value
        return result
    def nonfinite(_value):
        raise ProbeError("nonfinite_json")
    require(0 < len(raw) <= maximum, "json_size_bound")
    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite)
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        raise ProbeError("invalid_json") from None
    require(type(value) is dict, "json_object_required")
    return value


def write_audit(path, report):
    raw = (json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    require(len(raw) <= MAX_JSON, "audit_size_bound")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    require(not path.exists() and not path.is_symlink(), "fresh_audit_path_required")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())


def _simctl_error(code, arguments, stdout=None, stderr=None):
    error = ProbeError(code)
    # Only installation/launch of this invocation's disposable public probe
    # can contribute tool diagnostics. Do not copy command arguments or
    # output from simulator discovery and unrelated host surfaces.
    if arguments and arguments[0] in ("install", "launch"):
        detail = {"action": arguments[0]}
        for name, value in (("stdout", stdout), ("stderr", stderr)):
            if type(value) is bytes:
                text = value[:MAX_TOOL_DETAIL].decode("utf-8", errors="replace")
                truncated = len(value) > MAX_TOOL_DETAIL
            elif type(value) is str:
                text, truncated = value[:MAX_TOOL_DETAIL], len(value) > MAX_TOOL_DETAIL
            else:
                text, truncated = "", False
            # Bound the escaped JSON too, including hostile control bytes or
            # invalid UTF-8; the entire detail remains below eight KiB.
            while len(json.dumps(text, ensure_ascii=True)) > MAX_TOOL_DETAIL // 2 - 256:
                text = text[:len(text) // 2]
                truncated = True
            detail[name] = text
            detail[name + "_truncated"] = truncated
        error.tool_detail = detail
    return error


def _simctl(arguments, timeout):
    try:
        result = subprocess.run(["/usr/bin/xcrun", "simctl", *arguments],
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as error:
        raise _simctl_error("simctl_timeout", arguments, error.stdout, error.stderr) from None
    if len(result.stdout) > MAX_COMMAND_OUTPUT or len(result.stderr) > MAX_COMMAND_OUTPUT:
        raise _simctl_error("simctl_output_bound", arguments, result.stdout, result.stderr)
    if result.returncode != 0:
        raise _simctl_error("simctl_failed", arguments, result.stdout, result.stderr)
    return result.stdout


def discover(device_type, runtime, remaining):
    types = parse_json(_simctl(["list", "devicetypes", "--json"], remaining()), MAX_COMMAND_OUTPUT)
    runtimes = parse_json(_simctl(["list", "runtimes", "--json"], remaining()), MAX_COMMAND_OUTPUT)
    choices = [item for item in runtimes.get("runtimes", [])
               if type(item) is dict and item.get("isAvailable") is True
               and str(item.get("identifier", "")).startswith("com.apple.CoreSimulator.SimRuntime.iOS-")]
    if runtime is not None:
        choices = [item for item in choices if item.get("identifier") == runtime]
    require(bool(choices), "available_ios_runtime_required")
    def version(item):
        value = str(item.get("version", ""))
        require(bool(re.fullmatch(r"\d+(?:\.\d+){0,3}", value)), "invalid_runtime_version")
        return tuple(map(int, value.split(".")))
    chosen_runtime = max(choices, key=version)
    numbers = version(chosen_runtime)
    require(len(numbers) <= 3 and all(0 <= number <= 255 for number in numbers), "invalid_runtime_version")
    numbers = (*numbers, *(0 for _ in range(3 - len(numbers))))
    runtime_version = (numbers[0] << 16) | (numbers[1] << 8) | numbers[2]
    def compatible(item):
        minimum, maximum = item.get("minRuntimeVersion", 0), item.get("maxRuntimeVersion", 0xFFFFFFFF)
        return (type(minimum) is int and type(maximum) is int
                and minimum <= runtime_version <= maximum)
    choices = [item for item in types.get("devicetypes", []) if type(item) is dict
               and str(item.get("identifier", "")).startswith(("com.apple.CoreSimulator.SimDeviceType.iPhone-",
                                                               "com.apple.CoreSimulator.SimDeviceType.iPad-"))
               and compatible(item)]
    if device_type is not None:
        choices = [item for item in choices if item.get("identifier") == device_type]
    else:
        choices = [item for item in choices if ".iPhone-" in item["identifier"]]
    require(bool(choices), "ios_device_type_required")
    preferred = ("iPhone-16-Pro", "iPhone-15-Pro", "iPhone-14-Pro")
    rank = lambda item: next((i for i, suffix in enumerate(preferred)
                             if item["identifier"].endswith("." + suffix)), len(preferred))
    chosen_type = min(choices, key=rank)
    return chosen_type["identifier"], chosen_runtime["identifier"]


def boot_created_simulator(created, remaining):
    _simctl(["boot", created], remaining())
    # A cold first boot can take longer than one bounded simctl invocation.
    # Timing out that observer does not cancel the owned Simulator's boot.
    while True:
        try:
            _simctl(["bootstatus", created, "-b"], remaining())
            return
        except ProbeError as error:
            if str(error) != "simctl_timeout":
                raise
            remaining()  # The original overall deadline remains authoritative.


def load_schema(app):
    from idoly_local.schema import Schema
    payload = Path(app) / "LocalServer" / "ServerData.zip"
    require(payload.is_file() and not payload.is_symlink(), "public_server_payload_required")
    with ZipFile(payload) as archive:
        members = [item for item in archive.infolist() if item.filename == DESCRIPTOR_MEMBER]
        require(len(members) == 1 and 0 < members[0].file_size <= MAX_DESCRIPTOR,
                "bounded_public_descriptor_required")
        with archive.open(members[0]) as incoming:
            raw = incoming.read(MAX_DESCRIPTOR + 1)
        require(len(raw) == members[0].file_size, "descriptor_extent_differs")
    with tempfile.TemporaryDirectory(prefix="idoly-ios-probe-schema-") as directory:
        target = Path(directory) / "public.pb"
        target.write_bytes(raw)
        schema = Schema.from_descriptor_set(target)
    for path in RPC_PATHS:
        schema.method(path)
    return schema, hashlib.sha256(raw).hexdigest()


def validate_report(value):
    require(type(value) is dict and type(value.get("schema")) is int and value["schema"] == 1,
            "probe_schema_differs")
    require(type(value.get("original_called")) is int and value["original_called"] == 1
            and value.get("main_thread") is True and value.get("application_argument_matches") is True
            and value.get("command_completion_main_thread") is True,
            "unity_original_gate_failed")
    status, ports, crypto = (value.get(key) for key in ("server_status", "ports", "commoncrypto"))
    require(all(type(item) is dict for item in (status, ports, crypto)), "probe_fields_missing")
    require(type(status.get("schema")) is int and status["schema"] == 1
            and type(status.get("phase")) is int and status["phase"] == 4
            and status.get("hook_installed") is True and status.get("python_initialized") is True
            and status.get("error") is None
            and all(type(status.get(key)) is int and status[key] == 1
                    for key in ("captured", "forwarded", "attempts")),
            "embedded_server_not_ready")
    data = status.get("client_data")
    require(type(data) is dict and data.get("selected") is True
            and data.get("language") in ("ko", "ja", "en")
            and data.get("bundle_identifier") == "local.idoly.client-data", "client_language_selection_failed")
    require(status.get("launch_requested") is True and status.get("launch_prepared") is True
            and status.get("launcher_visible") is False, "launcher_handoff_failed")
    launcher = value.get("launcher")
    require(type(launcher) is dict, "launcher_evidence_missing")
    require(type(launcher.get("premature_phase")) is int and launcher["premature_phase"] == 1
            and type(launcher.get("premature_original_called")) is int
            and launcher["premature_original_called"] == 0
            and launcher.get("premature_launch_requested") is False,
            "premature_launch_not_ignored")
    early = value.get("early_status")
    require(type(early) is dict and type(early.get("id")) is int and early["id"] == 2718
            and early.get("ok") is True and early.get("state") == "starting" and early.get("running") is False
            and type(early.get("phase")) is int and early["phase"] == 1
            and type(early.get("captured")) is int and early["captured"] == 0
            and early.get("completion_main_thread") is True, "early_status_correlation_failed")
    require(type(launcher.get("premature_captured")) is int and launcher["premature_captured"] == 0
            and launcher.get("server_ready_before_capture") is True
            and type(launcher.get("uncaptured_original_called")) is int and launcher["uncaptured_original_called"] == 0
            and type(launcher.get("uncaptured_attempts")) is int and launcher["uncaptured_attempts"] == 1
            and launcher.get("capture_after_ready_once") is True, "server_not_ready_before_capture")
    require(type(launcher.get("ready_phase")) is int and launcher["ready_phase"] == 2
            and type(launcher.get("ready_original_called")) is int and launcher["ready_original_called"] == 0
            and launcher.get("ready_launch_requested") is False
            and launcher.get("ready_launch_prepared") is False
            and type(launcher.get("ready_observations")) is int and launcher["ready_observations"] >= 2
            and type(launcher.get("ready_wait_seconds")) in (int, float)
            and 1.0 <= launcher["ready_wait_seconds"] <= 60.0,
            "unity_started_before_launch_button")
    require(launcher.get("ready_launcher_visible") is True and launcher.get("ready_button_found") is True
            and launcher.get("ready_button_enabled") is True
            and launcher.get("ready_button_title") in ("게임 시작", "ゲーム開始", "Start Game"), "ready_launch_control_failed")
    require(launcher.get("button_action_dispatched") is True
            and type(launcher.get("button_dispatch_count")) is int and launcher["button_dispatch_count"] == 1
            and launcher.get("duplicate_launch_called") is True
            and launcher.get("forwarded_after_button") is True, "explicit_launch_action_failed")
    corner = value.get("corner_gesture")
    require(type(corner) is dict and corner.get("game_window_key") is True
            and type(corner.get("matching_count")) is int and corner["matching_count"] == 1
            and corner.get("recognizer_name") == "idoly.server-menu-corner"
            and type(corner.get("one_finger_count")) is int and corner["one_finger_count"] == 1
            and type(corner.get("three_finger_count")) is int and corner["three_finger_count"] == 0
            and type(corner.get("minimum_press_seconds")) in (int, float) and corner["minimum_press_seconds"] == 2.0
            and type(corner.get("allowable_movement_points")) in (int, float) and corner["allowable_movement_points"] == 12.0
            and corner.get("delegate_present") is True and corner.get("delays_touches_began") is False
            and corner.get("delays_touches_ended") is False and corner.get("cancels_touches_in_view") is True,
            "corner_gesture_configuration_failed")
    require(type(ports.get("grpc")) is int and ports["grpc"] == 50051
            and type(ports.get("assets")) is int and ports["assets"] == 8080
            and ports.get("grpc_connect") is True and ports.get("assets_connect") is True,
            "embedded_listener_probe_failed")
    require(crypto.get("nist_aes128_cbc") is True and crypto.get("nist_aes256_cbc") is True,
            "commoncrypto_fixture_failed")
    native_crypto = value.get("native_crypto")
    require(value.get("crypto_completion_main_thread") is True and type(native_crypto) is dict
            and all(native_crypto.get(key) is True for key in
                    ("ok", "nist_encrypt", "nist_decrypt", "invalid_iv_rejected"))
            and native_crypto.get("worker_main_thread") is False,
            "python_commoncrypto_bridge_failed")
    host = value.get("host_status")
    require(type(host) is dict and host.get("ok") is True
            and type(host.get("id")) is int and host["id"] == 1, "native_status_command_failed")
    result = host.get("result")
    require(type(result) is dict and result.get("state") == "ready" and result.get("running") is True
            and result.get("last_error") is None, "python_host_not_ready")
    runtime = result.get("runtime")
    require(type(runtime) is dict and runtime.get("running") is True
            and runtime.get("grpc_address") == "127.0.0.1:50051"
            and runtime.get("asset_url") == "http://127.0.0.1:8080", "python_host_listeners_differ")
    menu = value.get("menu_lifetime")
    require(type(menu) is dict and all(menu.get(key) is True for key in (
        "opened_via_owned_menu_target", "full_screen", "frame_width_matches", "return_button_found",
        "server_control_found", "server_control_disabled_while_running",
        "return_action_dispatched", "dismissed", "game_window_key_after_close", "status_completion_main_thread",
        "grpc_connected_after_close", "assets_connected_after_close")), "settings_menu_lifetime_failed")
    width, window_width = menu.get("frame_width"), menu.get("window_width")
    require(all(type(v) in (int, float) and math.isfinite(v) and 0 < v <= 16384 for v in (width, window_width))
            and abs(width - window_width) <= 2, "settings_menu_width_failed")
    web = menu.get("web")
    require(type(web) is dict and all(web.get(key) is True for key in (
        "web_found", "evaluation_succeeded", "ready", "forms_present", "scale_2_present", "buffer_4096_present",
        "no_horizontal_overflow")) and web.get("timed_out") is False, "settings_web_readiness_or_layout_failed")
    viewport, content = web.get("viewport_width"), web.get("content_width")
    require(all(type(v) in (int, float) and math.isfinite(v) and 0 < v <= 16384 for v in (viewport, content))
            and content <= viewport + 2 and type(web.get("select_count")) is int and 4 <= web["select_count"] <= 100,
            "settings_web_metrics_failed")
    after = menu.get("host_status_after_close")
    after_result = after.get("result") if type(after) is dict else None
    after_runtime = after_result.get("runtime") if type(after_result) is dict else None
    require(type(after) is dict and type(after.get("id")) is int and after["id"] == 2 and after.get("ok") is True
            and type(after_result) is dict and after_result.get("state") == "ready"
            and after_result.get("running") is True and after_result.get("last_error") is None
            and type(after_runtime) is dict and after_runtime.get("running") is True
            and after_runtime.get("grpc_address") == "127.0.0.1:50051"
            and after_runtime.get("asset_url") == "http://127.0.0.1:8080", "server_stopped_after_menu_close")
    # Copy only public, explicitly checked fields into the audit.
    return {"schema": 1, "original_called": 1, "main_thread": True,
            "application_argument_matches": True, "command_completion_main_thread": True,
            "crypto_completion_main_thread": True,
            "native_crypto": {"ok": True, "nist_encrypt": True, "nist_decrypt": True,
                              "invalid_iv_rejected": True, "worker_main_thread": False},
            "early_status": {key: early[key] for key in (
                "id", "ok", "state", "running", "phase", "captured", "completion_main_thread")},
            "launcher": {key: launcher[key] for key in (
                "premature_phase", "premature_original_called", "premature_launch_requested", "premature_captured",
                "server_ready_before_capture", "uncaptured_original_called", "uncaptured_attempts", "capture_after_ready_once",
                "ready_phase", "ready_original_called", "ready_launch_requested", "ready_launch_prepared",
                "ready_observations", "ready_wait_seconds", "ready_launcher_visible", "ready_button_found",
                "ready_button_enabled", "ready_button_title", "button_action_dispatched",
                "button_dispatch_count", "duplicate_launch_called", "forwarded_after_button")},
            "corner_gesture": {key: corner[key] for key in (
                "game_window_key", "matching_count", "recognizer_name", "one_finger_count", "three_finger_count", "minimum_press_seconds",
                "allowable_movement_points", "delegate_present", "delays_touches_began",
                "delays_touches_ended", "cancels_touches_in_view")},
            "server_status": {**{key: status[key] for key in
                ("schema", "phase", "hook_installed", "python_initialized", "captured", "forwarded", "attempts",
                 "launch_requested", "launch_prepared", "launcher_visible")},
                 "client_data":{key: data[key] for key in ("selected", "language", "bundle_identifier")}},
            "menu_lifetime": {**{key: menu[key] for key in (
                "opened_via_owned_menu_target", "full_screen", "frame_width_matches", "return_button_found",
                "server_control_found", "server_control_disabled_while_running",
                "return_action_dispatched", "dismissed", "game_window_key_after_close", "status_completion_main_thread",
                "grpc_connected_after_close", "assets_connected_after_close", "frame_width", "window_width")},
                "web": {key: web[key] for key in ("web_found", "evaluation_succeeded", "ready", "forms_present",
                    "scale_2_present", "buffer_4096_present", "no_horizontal_overflow", "timed_out",
                    "viewport_width", "content_width", "select_count")},
                "host_status_after_close": {"id":2,"ok":True,"result":{"state":"ready","running":True,
                    "runtime":{key:after_runtime[key] for key in ("running","grpc_address","asset_url")}}}},
            "ports": {key: ports[key] for key in ("grpc", "assets", "grpc_connect", "assets_connect")},
            "commoncrypto": {"nist_aes128_cbc": True, "nist_aes256_cbc": True},
            "host_status": {"id": 1, "ok": True, "result": {"state": "ready", "running": True,
                "runtime": {key: runtime[key] for key in ("running", "grpc_address", "asset_url")}}}}


def wait_report(container, remaining):
    documents = Path(container) / "Documents"
    final, waiting = documents / "embedded-probe.json", documents / "embedded-probe-status.json"
    while True:
        remaining()
        try:
            observed = parse_json(read_bounded(final, MAX_JSON))
            try:
                return validate_report(observed)
            except ProbeError as error:
                crypto = observed.get("native_crypto")
                if type(crypto) is dict:
                    # Only fixed scalar test flags from the fresh probe; no
                    # credentials, server payloads or arbitrary exception text.
                    error.native_crypto = {k: v for k, v in crypto.items()
                                           if k in ("ok", "nist_encrypt", "nist_decrypt", "invalid_iv_rejected", "worker_main_thread")
                                           and type(v) in (bool, int)}
                corner = corner_observation(observed.get("corner_gesture"))
                if corner:
                    error.native_corner = corner
                raise
        except FileNotFoundError:
            pass
        try:
            waiting_value = parse_json(read_bounded(waiting, MAX_JSON))
            failure = waiting_value.get("probe_error")
            if failure is not None:
                require(type(failure) is str and failure in LAUNCHER_FAILURE_CODES,
                        "invalid_launcher_failure_code")
                raise ProbeError(failure)
            status = waiting_value.get("server_status")
            require(type(status) is dict, "invalid_waiting_status")
            if status.get("game_error") is not None:
                error = ProbeError("native_game_preparation_failed")
                detail = status.get("game_error")
                if isinstance(detail, str): error.native_detail = detail[:2000]
                raise error
            if status.get("phase") == 3 or status.get("error") is not None:
                error = ProbeError("native_startup_failed")
                # This fresh probe contains only the pinned public payload.
                # Preserve the bounded bootstrap error before deleting its
                # disposable Simulator, so missing modules can be diagnosed.
                detail = status.get("error")
                if isinstance(detail, str):
                    error.native_detail = detail[:2000]
                raise error
        except FileNotFoundError:
            pass
        except ProbeError as error:
            # NSDataWritingAtomic replaces this recurring checkpoint. Retry
            # only a verified regular, bounded inode replacement; in-place
            # mutation and all final-report checks remain strict.
            if str(error) != "file_changed_while_opening" or getattr(error, "regular_replacement", False) is not True:
                raise
        time.sleep(min(0.25, remaining()))


def corner_observation(value):
    """Retain only bounded scalar recognizer diagnostics, never arbitrary names."""
    if type(value) is not dict:
        return {}
    clean = {}
    for key in ("game_window_key", "delegate_present", "delays_touches_began",
                "delays_touches_ended", "cancels_touches_in_view"):
        if type(value.get(key)) in (bool, int) and value[key] in (False, True, 0, 1):
            clean[key] = value[key]
    for key in ("matching_count", "one_finger_count", "three_finger_count"):
        if type(value.get(key)) is int and 0 <= value[key] <= 4096:
            clean[key] = value[key]
    for key in ("minimum_press_seconds", "allowable_movement_points"):
        if type(value.get(key)) in (int, float) and 0 <= value[key] <= 1000000:
            clean[key] = value[key]
    name = value.get("recognizer_name")
    clean["recognizer_name"] = name if name is None or name == "idoly.server-menu-corner" else "unexpected_name"
    return clean


def failure_checkpoint(container):
    """Read only fixed scalar progress from this invocation's fresh container."""
    result = {"stage": "not_observed", "container_available": container is not None}
    if container is None:
        return result
    documents = Path(container) / "Documents"

    def scalars(value):
        if type(value) is not dict:
            return {}
        clean = {}
        phase = value.get("phase")
        if type(phase) is int and 0 <= phase <= 4:
            clean["phase"] = phase
        application_state = value.get("application_state")
        if type(application_state) is int and 0 <= application_state <= 2:
            clean["application_state"] = application_state
        count = value.get("original_called")
        if type(count) is int and 0 <= count <= 16:
            clean["original_called"] = count
        for key in ("launch_requested", "launch_prepared", "launcher_visible"):
            if type(value.get(key)) is bool:
                clean[key] = value[key]
        return clean

    for source, name in (("checkpoint", "embedded-probe-checkpoint.json"),
                         ("status", "embedded-probe-status.json"), ("report", "embedded-probe.json")):
        result[source + "_available"] = False
        try:
            observed = parse_json(read_bounded(documents / name, MAX_JSON))
        except FileNotFoundError:
            continue
        except ProbeError as error:
            code = str(error)
            result[source + "_read_error"] = code if code in CHECKPOINT_READ_CODES else "invalid_checkpoint"
            continue
        except OSError:
            result[source + "_read_error"] = "unreadable_checkpoint"
            continue
        result[source + "_available"] = True
        if source == "checkpoint":
            stage = observed.get("stage")
            if type(observed.get("schema")) is int and observed["schema"] == 1 \
                    and type(stage) is str and stage in NATIVE_CHECKPOINT_STAGES:
                result.update(scalars(observed), stage=stage)
            else:
                result["checkpoint_read_error"] = "invalid_checkpoint_stage"
        else:
            status = scalars(observed.get("server_status"))
            status.update({key: item for key, item in scalars(observed).items() if key == "original_called"})
            result.update({source + "_" + key: item for key, item in status.items()})
            if source == "report":
                corner = corner_observation(observed.get("corner_gesture"))
                result.update({"corner_" + key: item for key, item in corner.items()})
                try:
                    validate_report(observed)
                    result["report_valid"] = True
                except ProbeError:
                    result["report_valid"] = False
    return result


def unary_h2(path, request, *, token=None, port=50051, timeout=15):
    """One real encrypted unary h2c RPC, restricted to IPv4 loopback."""
    from h2.config import H2Configuration
    from h2.connection import H2Connection
    from h2.events import (ConnectionTerminated, DataReceived, ResponseReceived,
                           StreamEnded, StreamReset, TrailersReceived)
    from idoly_local import codec
    require(path in RPC_PATHS and type(port) is int and 0 < port <= 65535,
            "invalid_probe_rpc")
    require(type(request) is bytes and len(request) <= MAX_JSON, "rpc_request_bound")
    encrypted = codec.encode(request + PUBLIC_PROBE_FIELD)
    require(bool(encrypted), "rpc_request_not_encrypted")
    frame = b"\0" + struct.pack("!I", len(encrypted)) + encrypted
    peer = H2Connection(H2Configuration(client_side=True, header_encoding="utf-8"))
    peer.initiate_connection()
    headers = [(":method", "POST"), (":scheme", "http"), (":authority", f"127.0.0.1:{port}"),
               (":path", path), ("content-type", "application/grpc"), ("te", "trailers"),
               ("grpc-timeout", f"{max(1, min(99999999, int(timeout * 1000)))}m")]
    if token is not None:
        require(type(token) is str and 0 < len(token) <= 4096 and token.isascii()
                and not any(ord(c) < 33 or ord(c) > 126 for c in token), "invalid_local_auth_token")
        headers.append(("x-auth-token", token))
    peer.send_headers(1, headers)
    peer.send_data(1, frame, end_stream=True)
    response, metadata, ended = bytearray(), {}, False
    deadline = time.monotonic() + timeout
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout) as connection:
            connection.sendall(peer.data_to_send())
            while not ended:
                left = deadline - time.monotonic()
                require(left > 0, "rpc_deadline_exceeded")
                connection.settimeout(left)
                raw = connection.recv(64 * 1024)
                require(bool(raw), "rpc_closed_before_trailers")
                for event in peer.receive_data(raw):
                    if isinstance(event, (ResponseReceived, TrailersReceived)):
                        require(event.stream_id == 1, "unexpected_rpc_stream")
                        for key, value in event.headers:
                            require(key not in metadata and len(key) + len(value) <= 8192,
                                    "invalid_rpc_headers")
                            metadata[key] = value
                        require(sum(len(k) + len(v) for k, v in metadata.items()) <= 16 * 1024,
                                "rpc_headers_bound")
                    elif isinstance(event, DataReceived):
                        require(event.stream_id == 1 and len(response) + len(event.data) <= MAX_RESPONSE,
                                "rpc_response_bound")
                        response.extend(event.data)
                        peer.acknowledge_received_data(event.flow_controlled_length, event.stream_id)
                    elif isinstance(event, StreamEnded):
                        require(event.stream_id == 1, "unexpected_rpc_stream")
                        ended = True
                    elif isinstance(event, (ConnectionTerminated, StreamReset)):
                        raise ProbeError("rpc_stream_terminated")
                pending = peer.data_to_send()
                if pending:
                    connection.sendall(pending)
    except OSError:
        raise ProbeError("rpc_loopback_transport_failed") from None
    require(metadata.get(":status") == "200" and metadata.get("grpc-status") == "0"
            and metadata.get("content-type", "").startswith("application/grpc"), "rpc_status_failed")
    require(len(response) >= 5 and response[0] == 0
            and len(response) == 5 + struct.unpack_from("!I", response, 1)[0], "invalid_unary_rpc_frame")
    require(len(response) > 5, "rpc_response_not_encrypted")
    plain = codec.decode(bytes(response[5:]))
    return plain, {"path": path, "grpc_status": 0, "request_encrypted": True,
                   "response_encrypted": True, "response_bytes": len(plain),
                   "response_sha256": hashlib.sha256(plain).hexdigest()}


def probe_rpcs(schema, *, port=50051, timeout=15):
    rows = []
    token = None
    deadline = time.monotonic() + timeout
    for path in RPC_PATHS:
        remaining = deadline - time.monotonic()
        require(remaining > 0, "rpc_deadline_exceeded")
        request = schema.request_type(path)().SerializeToString()
        plain, row = unary_h2(path, request, token=token, port=port, timeout=remaining)
        result = schema.response_type(path).FromString(plain)
        if path == RPC_PATHS[0]:
            require(result.keepAliveTimeMilliseconds == 60000, "system_check_fixture_differs")
        elif path == RPC_PATHS[1]:
            token = result.gameAuthToken
            require(bool(token) and bool(result.userPublic.serverUserId)
                    and bool(result.userPublic.publicUserId), "fresh_local_login_failed")
        else:
            require(bool(result.currentMainAreaId), "fresh_local_home_failed")
        rows.append(row)
    return rows


def run_probe(app, audit, *, device_type=None, runtime=None, timeout=240):
    audit = Path(audit)
    require(not audit.exists() and not audit.is_symlink(), "fresh_audit_path_required")
    report = {"schema": 1, "status": "FAIL", "execution": "ios_simulator",
              "gameplay_tested": False, "device_tested": False, "playcover_tested": False,
              "simulator_created": False, "launch_ack_timeout": False,
              "cleanup": {"shutdown": False, "delete": False}}
    created = None
    container = None
    start = time.monotonic()
    stage = "platform"
    def remaining(cap=60):
        value = timeout - (time.monotonic() - start)
        require(value > 0, "probe_deadline_exceeded")
        return min(cap, value)
    try:
        require(sys.platform == "darwin", "macos_required_no_simulator_execution")
        require(type(timeout) in (int, float) and 5 <= timeout <= 600, "invalid_probe_timeout")
        app = Path(app).resolve(strict=True)
        require(app.is_dir() and app.suffix == ".app", "simulator_app_required")
        info = plistlib.loads(read_bounded(app / "Info.plist", MAX_JSON))
        require(info.get("CFBundleIdentifier") == BUNDLE_ID
                and info.get("CFBundleSupportedPlatforms") == ["iPhoneSimulator"], "fake_unity_probe_app_required")
        report["bundle_id"] = BUNDLE_ID
        stage = "public_schema"
        schema, report["descriptor_sha256"] = load_schema(app)
        stage = "simulator_discovery"
        chosen_type, chosen_runtime = discover(device_type, runtime, remaining)
        report.update(device_type=chosen_type, runtime=chosen_runtime)
        stage = "simulator_create"
        raw = _simctl(["create", "IdolyEmbeddedProbe-" + uuid.uuid4().hex, chosen_type, chosen_runtime], remaining())
        value = raw.decode("ascii").strip()
        require(bool(re.fullmatch(r"[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}", value)),
                "invalid_created_simulator_uuid")
        created = str(uuid.UUID(value)).upper()
        report.update(simulator_created=True, simulator_uuid=created)
        stage = "simulator_boot"
        stage_start = time.monotonic()
        boot_created_simulator(created, remaining)
        report["simulator_boot_seconds"] = round(time.monotonic() - stage_start, 3)
        stage = "app_install"
        stage_start = time.monotonic()
        _simctl(["install", created, str(app)], remaining(180))
        report["app_install_seconds"] = round(time.monotonic() - stage_start, 3)
        stage = "fresh_container"
        raw = _simctl(["get_app_container", created, BUNDLE_ID, "data"], remaining())
        candidate = Path(raw.decode("utf-8").strip())
        require(candidate.is_absolute() and candidate.is_dir() and not candidate.is_symlink(),
                "invalid_fresh_app_container")
        for relative in ("Library/Application Support/IdolyPrideLocal/state.db",
                         "Library/Application Support/IdolyPrideLocal/media-state.db",
                         "Documents/embedded-probe.json", "Documents/embedded-probe-status.json",
                         "Documents/embedded-probe-checkpoint.json"):
            path = candidate / relative
            require(not path.exists() and not path.is_symlink(), "preexisting_probe_state_rejected")
        container = candidate
        report["fresh_local_state_before_launch"] = True
        stage = "app_launch"
        try:
            _simctl(["launch", created, BUNDLE_ID], remaining(180))
        except ProbeError as error:
            if str(error) != "simctl_timeout":
                raise
            # A launch acknowledgement can time out while the app keeps
            # running. Do not launch twice: the full native/RPC report must
            # still pass under the original overall deadline.
            report["launch_ack_timeout"] = True
            if type(getattr(error, "tool_detail", None)) is dict:
                report["launch_ack_diagnostic"] = error.tool_detail
            report["launch_ack_checkpoint"] = failure_checkpoint(container)
        stage = "startup_gate_report"
        report["native_probe"] = wait_report(container, remaining)
        stage = "asset_listener"
        with socket.create_connection(("127.0.0.1", 8080), timeout=min(5, remaining())):
            pass
        report["host_asset_loopback_connected"] = True
        stage = "encrypted_rpc"
        report["rpcs"] = probe_rpcs(schema, timeout=min(15, remaining()))
        report["status"] = "PASS"
    except BaseException as error:
        report.update(status="FAIL", failed_stage=stage,
                      error=(str(error) if isinstance(error, ProbeError) else type(error).__name__))
        report["native_checkpoint"] = failure_checkpoint(container)
        if isinstance(error, ProbeError) and isinstance(getattr(error, "native_detail", None), str):
            report["native_startup_error"] = error.native_detail
        if isinstance(error, ProbeError) and type(getattr(error, "native_crypto", None)) is dict:
            report["native_crypto_observed"] = error.native_crypto
        if isinstance(error, ProbeError) and type(getattr(error, "native_corner", None)) is dict:
            report["native_corner_observed"] = error.native_corner
        if isinstance(error, ProbeError) and type(getattr(error, "tool_detail", None)) is dict:
            report["simctl_failure"] = error.tool_detail
    finally:
        # Capture before deleting the owned container, including when an
        # otherwise passing run subsequently encounters a cleanup failure.
        checkpoint = report.get("native_checkpoint") or failure_checkpoint(container)
        if created is not None:
            for action in ("shutdown", "delete"):
                try:
                    _simctl([action, created], 30)
                    report["cleanup"][action] = True
                except BaseException as error:
                    report["cleanup"][action + "_error"] = type(error).__name__
            if not all(report["cleanup"][key] for key in ("shutdown", "delete")):
                report.update(status="FAIL", cleanup_complete=False)
                report["native_checkpoint"] = checkpoint
        report["seconds"] = round(time.monotonic() - start, 3)
        write_audit(audit, report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--device-type")
    parser.add_argument("--runtime")
    parser.add_argument("--timeout", type=float, default=240)
    args = parser.parse_args(argv)
    try:
        result = run_probe(args.app, args.audit, device_type=args.device_type,
                           runtime=args.runtime, timeout=args.timeout)
    except (ProbeError, OSError) as error:
        print(json.dumps({"status": "FAIL", "error": str(error) if isinstance(error, ProbeError)
                          else type(error).__name__}))
        return 1
    print(json.dumps({"status": result["status"], "audit": str(args.audit)}))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
