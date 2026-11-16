#!/usr/bin/env python3
"""Run the integrated server's fake Unity host in one disposable iOS Simulator.

Actual execution requires macOS/Xcode. Portable tests mock simulator control;
they do not establish simulator, device, game, or PlayCover compatibility.
Only a UUID returned by this invocation's `simctl create` may be changed.
"""
from __future__ import annotations

import argparse
import hashlib
from http.client import HTTPConnection, HTTPException
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
from zipfile import BadZipFile, ZipFile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
PROBE_SOURCE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROBE_SOURCE_DIR))
from ui_test_driver import (ProbePromptCancelDriver, DriverError, ERROR_CODES as UI_DRIVER_ERRORS,
    DIAGNOSTIC_CHECKS as UI_DIAGNOSTIC_CHECKS, DIAGNOSTIC_TYPES as UI_DIAGNOSTIC_TYPES,
    DIAGNOSTIC_TOKEN_KINDS as UI_DIAGNOSTIC_TOKEN_KINDS)


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
MASTER_RPC_PATH = "/api.Master/Get"
MASTER_ORIGIN = "http://127.0.0.1:8080"
MAX_MASTER_FILE = 64 * 1024 * 1024
MAX_SDK_BYTES = 16 * 1024 * 1024
SDK_MANIFEST_PATH = "/v2/pub/a/212/v/105051/list/0"
SDK_URL_FORMAT = MASTER_ORIGIN + "/octo/{v}/{type}/{o}/{g}"
LANGUAGE_ORDER = ("ko", "en", "ja")
MATRIX_LANGUAGES = ("ko", "en", "ja", "en", "ko")
CANARY_PATHS = ("Data/resources.assets", "Data/Managed/Metadata/global-metadata.dat")
MAX_CANARY_BYTES = 128 * 1024 * 1024
HOST_TRUE_FIELDS = ("installed", "entry_captured", "host_ready", "started", "unity_window_bound",
    "bundle_match_before", "bundle_match_after", "first_warmup_bundle_match", "sigpipe_ignored_before_server")
HOST_FALSE_FIELDS = ("launching", "failed")
UNITY_HOST_ERROR_CODES = frozenset(("sigpipe_guard_failed", "warmup_order_or_bundle_mismatch", "entry_capture_rejected",
    "smoke_hooks_missing", "runtime_initialized_before_host", "host_main_repeated", "host_application_main_failed",
    "install_rejected", "unattested_unified_host", "framework_entry_abi_mismatch", "framework_entry_origin_mismatch",
    "start_rejected", "selected_bundle_mismatch", "runtime_initialized_before_selection", "cached_bundle_root_mismatch",
    "embedded_start_failed", "embedded_verification_failed"))
HOST_ONCE_FIELDS = ("application_main_calls", "runtime_start_calls", "warmup_calls")
HOST_EVENT_FIELDS = ("queued_events", "delivered_events", "lifecycle_forwarded")
HOST_PROBE_TRUE_FIELDS = ("constructor_installed_before_c_main", "host_hooks_registered", "host_delegate_owned",
    "cold_before_game_start", "canaries_match", "game_window_distinct", "game_window_key",
    "host_delegate_window_is_game", "placeholder_hidden", "prelaunch_server_healthy", "prelaunch_runtime_cold")
HOST_PROBE_COUNTS = ("application_main_adapter_calls", "original_run_main_calls",
    "runtime_count_before_game_start", "warmup_count_before_game_start")
LANGUAGE_CYCLE_FLAGS = ("acknowledged", "dom_language_matches", "native_title_matches",
    "native_game_button_matches", "native_status_label_matches", "native_server_button_matches",
    "game_select_unchanged", "persisted_game_language_unchanged")
LANGUAGE_SAVE_FLAGS = ("acknowledged", "options_fields_reenabled", "message_success", "form_feedback_saved",
    "request_observed", "ack_correlated", "server_status_received", "server_language_matches", "server_effective_matches")
LAUNCH_SETTINGS_FLAGS = ("cold_while_settings_flush_held", "game_button_disabled_during_flush",
    "settings_flush_called_once", "unsolicited_settings_ack_ignored", "settings_flush_released_before_forward")
SETTINGS_WEB_BOOL_FIELDS = ("web_found", "timed_out", "evaluation_succeeded", "ready", "forms_present",
    "scale_2_present", "buffer_4096_present", "no_horizontal_overflow", "document_complete",
    "options_fields_enabled", "presentation_fields_enabled", "bridge_reply_present", "error_is_wk_domain",
    "navigation_loading", "navigation_file_url", "web_attached", "evaluation_started", "evaluation_completed",
    "data_store_reused", "launcher_store_nonpersistent", "menu_store_nonpersistent", "web_view_recreated", "launcher_document_marker_absent")
SIGPIPE_PHASES = ("before_server", "before_game_worker")
SIGPIPE_FLAGS = ("sigaction_read", "sigpipe_ignored", "socketpair_created", "peer_closed", "write_epipe", "process_survived")
# A well-formed unknown protobuf varint makes empty requests exercise AES too.
PUBLIC_PROBE_FIELD = b"\xc0\xa3\x09\x01"  # field 19000, wire type 0, value 1
LAUNCHER_FAILURE_CODES = frozenset((
    "premature_launch_not_ignored", "server_left_ready_before_launch",
    "unity_started_before_launch_button", "ready_launcher_not_visible",
    "ready_launcher_flags_differ", "ready_launch_button_missing",
    "ready_launch_button_ambiguous", "ready_launch_button_disabled",
    "ready_launch_button_title_differs", "ready_launch_action_missing",
    "ready_launch_action_not_dispatched", "launch_settings_barrier_failed",
    "early_status_correlation_failed", "server_not_ready_before_capture", "ready_capture_restarted_server",
    "settings_menu_open_failed", "settings_menu_not_presented", "settings_menu_controls_or_layout_failed",
    "settings_web_readiness_or_layout_failed", "settings_return_action_failed", "settings_menu_not_dismissed",
    "final_report_write_failed",
    "keyboard_before_capture_failed", "keyboard_before_launch_failed",
    "keyboard_during_init_failed", "keyboard_after_init_failed",
    "keyboard_precreated_instance_not_reused",
    "native_header_layout_failed", "native_header_restore_failed",
    "settings_diagnostics_copy_failed", "settings_zip_import_picker_failed", "settings_zip_roundtrip_failed",
    "settings_account_management_failed", "settings_account_fixture_failed", "settings_official_prompt_failed",
    "host_constructor_not_installed", "host_hooks_registration_failed", "host_cold_start_failed",
    "unity_window_handoff_failed", "language_cache_identity_failed", "sigpipe_probe_failed",
    "sigpipe_before_server_failed", "sigpipe_before_game_failed",
    "unity_host_failed", "unity_host_probe_failed", "language_interface_cycle_failed", "language_save_failed",
    "language_canaries_invalid", "language_canaries_mismatch", "language_matrix_failed", "language_relaunch_mismatch",
    "octo_budget_registration_failed", "octo_budget_preinit_failed", "octo_budget_original_failed", "octo_budget_queued_work_failed",
))
NATIVE_CHECKPOINT_STAGES = frozenset((
    "delegate_entered", "window_ready", "server_starting", "server_ready",
    "unity_requests_captured", "premature_launch_checked", "launch_action_requested",
    "launch_action_dispatched", "unity_forwarded", "status_received", "crypto_received",
    "loopback_checked", "report_written", "settings_menu_requested", "settings_return_requested",
    "settings_return_observed", "settings_return_timeout", "settings_menu_dismissed",
    "keyboard_before_capture_checked", "keyboard_before_launch_checked",
    "keyboard_during_init_checked", "keyboard_after_init_checked",
    "native_header_checked",
    "settings_diagnostics_copied", "settings_web_observed", "settings_zip_import_cancelled", "settings_zip_roundtrip_checked", "settings_account_management_checked", "settings_official_prompt_checked",
    "sigpipe_before_game_checked", "c_main_entered", "host_hooks_registered", "host_ready", "host_entry_captured", "interface_language_cycle_checked", "language_saved",
    "octo_budget_original_observed", "octo_budget_first_queued_work_observed",
))
KEYBOARD_PHASES = ("before_capture", "before_launch", "during_init", "after_init")
KEYBOARD_BOOL_FIELDS = ("ready", "returned_nil", "returned_initialized_field", "returned_same_field")
KEYBOARD_INT_FIELDS = ("phase", "original_calls", "field_creation_count")
KEYBOARD_LIFECYCLE_COUNTERS = ("initialize_calls", "original_initialize_calls", "reused_existing_calls")
HEADER_PHASES = ("current", "wide", "ultrawide", "restored")
HEADER_BOOL_FIELDS = ("header_found", "actions_found", "title_found", "status_found", "hint_found",
                      "nav_bar_hidden", "header_inside", "controls_inside", "row_no_overlap", "button_titles_fit")
HEADER_FONT_FIELDS = ("button_min_font", "title_font", "status_font", "hint_font")
HEADER_NUMBER_FIELDS = ("root_width", "root_height", "header_width", "header_height", "actions_width",
                        "min_button_height", *HEADER_FONT_FIELDS)
HTTP_READINESS_URL = "http://127.0.0.1:8080/client/playback"
DIAGNOSTICS_COPY_BOOL_FIELDS = ("button_found", "enabled_before", "click_dispatched", "completed",
                                "feedback_success", "pasteboard_matches", "clipboard_seeded", "clipboard_cleared")
ZIP_IMPORT_PASS_BOOL_FIELDS = ("button_found", "enabled_before", "click_dispatched", "button_disabled_while_pending",
    "picker_presented", "single_selection", "delegate_is_settings", "cancel_delegate_invoked",
    "dismissed_programmatically", "picker_detached", "button_restored")
ZIP_IMPORT_SERVER_FLAGS = ("grpc_connected_after_cancel", "assets_connected_after_cancel")
ZIP_ROUNDTRIP_FLAGS = ("export_accepted", "export_ready", "export_archive_complete", "wk_import_dispatched",
    "picker_presented", "picker_import_mode", "picker_single_selection", "selection_delegate_invoked",
    "dismissed_programmatically", "picker_detached", "import_reply_accepted", "native_copy_queued",
    "copy_bytes_match", "owned_copy_found", "copy_source_distinct", "source_preserved", "source_copy_sha256_match",
    "backend_ready", "backend_success", "dom_completed", "button_restored", "upstream_requests_unchanged")
ZIP_ROUNDTRIP_COUNTS = ("source_bytes", "copied_bytes", "total_bytes", "exported_files", "imported_files", "failed_files")
OCTO_BUDGET_SECONDS = ("original_seconds", "effective_seconds", "cache_wait_seconds")
OCTO_BUDGET_PROBE_SECONDS = ("during_original_seconds", "first_queued_seconds", "last_snapshot")
OCTO_BUDGET_PROBE_BOOLS = ("apis_registered", "prepared_without_managed_callbacks", "during_original_configured",
    "configured_before_first_queued_work", "queued_work_on_main_thread", "class_initialized")
OCTO_BUDGET_PROBE_COUNTERS = ("initializations", "reads", "writes", "first_queued_snapshot_count",
                             "writes_before_initialization")
OCTO_BUDGET_ERROR_CODES = frozenset(("api_origin_mismatch", "not_prepared", "unattested_loopback",
    "wrong_thread", "incomplete_apis", "runtime_unavailable", "invalid_assemblies", "image_mismatch",
    "class_mismatch", "field_mismatch", "field_not_static", "type_mismatch", "unexpected_value", "readback_mismatch"))
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
    raw = (json.dumps(report, separators=(",", ":"), sort_keys=True, allow_nan=False) + "\n").encode()
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
    for path in (*RPC_PATHS, MASTER_RPC_PATH):
        schema.method(path)
    return schema, hashlib.sha256(raw).hexdigest()


def language_paths(language, run_index=None):
    require(type(language) is str and language in LANGUAGE_ORDER, "language_relaunch_mismatch")
    if run_index is None: run_index = MATRIX_LANGUAGES.index(language)
    require(type(run_index) is int and 0 <= run_index < len(MATRIX_LANGUAGES)
            and MATRIX_LANGUAGES[run_index] == language, "language_relaunch_mismatch")
    stem = ("embedded-probe", "embedded-language-en", "embedded-language-ja",
            "embedded-language-en-return", "embedded-language-ko-return")[run_index]
    return tuple(stem + suffix + ".json" for suffix in ("", "-status", "-checkpoint"))


def _hex_digest(value):
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _validate_language_evidence(host, probe, cycle, saved, language, run_index=None):
    require(type(language) is str and language in LANGUAGE_ORDER, "language_relaunch_mismatch")
    if run_index is None: run_index = MATRIX_LANGUAGES.index(language)
    require(type(run_index) is int and 0 <= run_index < len(MATRIX_LANGUAGES)
            and MATRIX_LANGUAGES[run_index] == language, "language_relaunch_mismatch")
    require(type(host) is dict and type(host.get("schema")) is int and host["schema"] == 1
            and host.get("strategy") == "unity-as-library"
            and all(host.get(key) is True for key in HOST_TRUE_FIELDS)
            and all(host.get(key) is False for key in HOST_FALSE_FIELDS)
            and all(type(host.get(key)) is int and host[key] == 1 for key in HOST_ONCE_FIELDS)
            and all(type(host.get(key)) is int and 0 <= host[key] <= 32 for key in HOST_EVENT_FIELDS)
            and host.get("consumed_bundle_language") == language
            and "error" in host and host["error"] is None, "unity_host_failed")
    require(type(probe) is dict and type(probe.get("schema")) is int and probe["schema"] == 1
            and type(probe.get("run_index")) is int and probe["run_index"] == run_index
            and probe.get("expected_language") == language and probe.get("consumed_bundle_language") == language
            and all(probe.get(key) is True for key in HOST_PROBE_TRUE_FIELDS)
            and all(type(probe.get(key)) is int and probe[key] == wanted for key,wanted in
                (("application_main_adapter_calls",1),("original_run_main_calls",0),
                 ("runtime_count_before_game_start",0),("warmup_count_before_game_start",0)))
            and _hex_digest(probe.get("canary_source_sha256")), "unity_host_probe_failed")
    sigpipe = probe.get("sigpipe")
    require(type(sigpipe) is dict and set(sigpipe) == set(SIGPIPE_PHASES), "sigpipe_probe_failed")
    for phase in SIGPIPE_PHASES:
        sample = sigpipe[phase]
        require(type(sample) is dict and type(sample.get("schema")) is int and sample["schema"] == 1
                and all(sample.get(key) is True for key in SIGPIPE_FLAGS)
                and sample.get("main_thread") is (phase == "before_server"), "sigpipe_probe_failed")
    require(probe.get("cache_return") is (run_index >= 3) and probe.get("cache_identity_recorded") is True
            and "cache_files_same_identity" in probe
            and probe["cache_files_same_identity"] is (True if run_index >= 3 else None),
            "language_cache_identity_failed")
    canaries = probe.get("canaries")
    require(type(canaries) is dict and set(canaries) == set(CANARY_PATHS), "unity_host_probe_failed")
    for path in CANARY_PATHS:
        row = canaries[path]
        require(type(row) is dict and _hex_digest(row.get("expected_sha256"))
                and row.get("actual_sha256") == row["expected_sha256"]
                and type(row.get("expected_bytes")) is int and 1 <= row["expected_bytes"] <= MAX_CANARY_BYTES
                and type(row.get("actual_bytes")) is int and row["actual_bytes"] == row["expected_bytes"],
                "unity_host_probe_failed")
    require(type(cycle) is list and len(cycle) == 3, "language_interface_cycle_failed")
    for row, wanted in zip(cycle,("ja","en","ko")):
        require(type(row) is dict and row.get("language") == wanted
                and type(row.get("ack_id")) is int and 1 <= row["ack_id"] <= 2**31-1
                and all(row.get(key) is True for key in LANGUAGE_CYCLE_FLAGS), "language_interface_cycle_failed")
    next_language = ("en","ja","en","ko","ko")[run_index]
    require(type(saved) is dict and saved.get("current_language") == language
            and saved.get("next_language") == next_language and saved.get("persisted_language") == next_language
            and saved.get("effective_language") == language and saved.get("save_trigger") == "change-autosave"
            and saved.get("feedback_source") == "options-save-feedback" and saved.get("feedback_state") == "saved"
            and saved.get("request_action") == "save_options" and saved.get("request_language") == next_language
            and saved.get("ack_language") == next_language and saved.get("ack_effective_language") == language
            and saved.get("timed_out") is False
            and type(saved.get("request_id")) is int and saved["request_id"] == saved.get("ack_id")
            and type(saved.get("ack_id")) is int and 1 <= saved["ack_id"] <= 2**31-1
            and all(saved.get(key) is True for key in LANGUAGE_SAVE_FLAGS), "language_save_failed")
    return {"language":language,"run_index":run_index,"unity_host":unity_host_observation(host),
        "unity_host_probe":unity_host_probe_observation(probe),
        "interface_language_cycle":interface_language_observation(cycle),"language_save":language_save_observation(saved)}


def validate_language_relaunch_report(native, expected_language, *, run_index=None):
    checked = validate_report(native)
    return _validate_language_evidence(checked["server_status"]["unity_host"], checked["unity_host_probe"],
        checked["interface_language_cycle"], checked["language_save"], expected_language, run_index)


def validate_language_matrix_report(value):
    require(type(value) is dict and type(value.get("schema")) is int and value["schema"] == 2
            and value.get("order") == list(MATRIX_LANGUAGES) and value.get("preserved_app_container") is True
            and type(value.get("reports")) is list and len(value["reports"]) == 5, "language_matrix_failed")
    reports = []
    for run_index,(row,language) in enumerate(zip(value["reports"],MATRIX_LANGUAGES)):
        require(type(row) is dict and row.get("language") == language
                and type(row.get("run_index")) is int and row["run_index"] == run_index, "language_matrix_failed")
        reports.append(_validate_language_evidence(row.get("unity_host"),row.get("unity_host_probe"),
            row.get("interface_language_cycle"),row.get("language_save"),language,run_index))
    return {"schema":2,"order":list(MATRIX_LANGUAGES),"preserved_app_container":True,"reports":reports}


def load_language_canaries(app, descriptor_sha256):
    raw = read_bounded(Path(app)/"probe-language-canaries.json",MAX_JSON)
    value = parse_json(raw)
    require(type(value.get("schema")) is int and value["schema"] == 1
            and value.get("bundle_id") == "local.idoly.client-data"
            and all(_hex_digest(value.get(key)) for key in
                    ("client_archive_sha256","client_manifest_sha256","descriptor_sha256"))
            and value["descriptor_sha256"] == descriptor_sha256, "language_canaries_invalid")
    languages = value.get("languages")
    require(type(languages) is dict and set(languages) == set(LANGUAGE_ORDER), "language_canaries_invalid")
    clean = {key:value[key] for key in ("schema","bundle_id","client_archive_sha256",
                                       "client_manifest_sha256","descriptor_sha256")}
    clean["languages"] = {}
    for language in LANGUAGE_ORDER:
        rows = languages[language]
        require(type(rows) is dict and set(rows) == set(CANARY_PATHS), "language_canaries_invalid")
        clean["languages"][language] = {}
        for path in CANARY_PATHS:
            row = rows[path]
            require(type(row) is dict and type(row.get("bytes")) is int and 1 <= row["bytes"] <= MAX_CANARY_BYTES
                    and _hex_digest(row.get("sha256")), "language_canaries_invalid")
            clean["languages"][language][path] = {"bytes":row["bytes"],"sha256":row["sha256"]}
    return clean,hashlib.sha256(raw).hexdigest()


def compare_language_canaries(summary, expected_language, canaries, source_sha256):
    require(summary.get("language") == expected_language
            and summary["unity_host_probe"]["canary_source_sha256"] == source_sha256,
            "language_canaries_mismatch")
    for path in CANARY_PATHS:
        row = summary["unity_host_probe"]["canaries"][path]
        expected = canaries["languages"][expected_language][path]
        require(row["expected_sha256"] == expected["sha256"] and row["expected_bytes"] == expected["bytes"],
                "language_canaries_mismatch")


def unity_host_observation(value):
    if type(value) is not dict: return {}
    clean = {key:value[key] for key in (*HOST_TRUE_FIELDS,*HOST_FALSE_FIELDS) if type(value.get(key)) is bool}
    for key in (*HOST_ONCE_FIELDS,*HOST_EVENT_FIELDS):
        if type(value.get(key)) is int and 0 <= value[key] <= 32: clean[key] = value[key]
    if type(value.get("schema")) is int and value["schema"] == 1: clean["schema"] = 1
    if value.get("strategy") == "unity-as-library": clean["strategy"] = "unity-as-library"
    if value.get("consumed_bundle_language") in LANGUAGE_ORDER:
        clean["consumed_bundle_language"] = value["consumed_bundle_language"]
    if "error" in value and value["error"] is None: clean["error"] = None
    elif type(value.get("error")) is str and value["error"] in UNITY_HOST_ERROR_CODES: clean["error"] = value["error"]
    return clean


def sigpipe_observation(value):
    if type(value) is not dict: return {}
    clean = {}
    for phase in SIGPIPE_PHASES:
        row = value.get(phase)
        if type(row) is not dict: continue
        sample = {key:row[key] for key in (*SIGPIPE_FLAGS,"main_thread") if type(row.get(key)) is bool}
        if type(row.get("schema")) is int and row["schema"] == 1: sample["schema"] = 1
        if sample: clean[phase] = sample
    return clean


def unity_host_probe_observation(value):
    if type(value) is not dict: return {}
    clean = {key:value[key] for key in HOST_PROBE_TRUE_FIELDS if type(value.get(key)) is bool}
    for key in HOST_PROBE_COUNTS:
        if type(value.get(key)) is int and 0 <= value[key] <= 32: clean[key] = value[key]
    if type(value.get("run_index")) is int and 0 <= value["run_index"] <= 4: clean["run_index"] = value["run_index"]
    for key in ("cache_return", "cache_identity_recorded"):
        if type(value.get(key)) is bool: clean[key] = value[key]
    if "cache_files_same_identity" in value and (type(value["cache_files_same_identity"]) is bool
            or value["cache_files_same_identity"] is None):
        clean["cache_files_same_identity"] = value["cache_files_same_identity"]
    if type(value.get("schema")) is int and value["schema"] == 1: clean["schema"] = 1
    for key in ("expected_language","consumed_bundle_language"):
        if value.get(key) in LANGUAGE_ORDER: clean[key] = value[key]
    if _hex_digest(value.get("canary_source_sha256")): clean["canary_source_sha256"] = value["canary_source_sha256"]
    pipe = sigpipe_observation(value.get("sigpipe"))
    if pipe: clean["sigpipe"] = pipe
    raw = value.get("canaries")
    if type(raw) is dict:
        rows = {}
        for path in CANARY_PATHS:
            row = raw.get(path)
            if type(row) is not dict: continue
            sample = {key:row[key] for key in ("expected_sha256","actual_sha256") if _hex_digest(row.get(key))}
            for key in ("expected_bytes","actual_bytes"):
                if type(row.get(key)) is int and 0 <= row[key] <= MAX_CANARY_BYTES: sample[key] = row[key]
            if sample: rows[path] = sample
        if rows: clean["canaries"] = rows
    return clean


def interface_language_observation(value):
    if type(value) is not list: return []
    clean = []
    for row in value[:3]:
        if type(row) is not dict: continue
        sample = {key:row[key] for key in LANGUAGE_CYCLE_FLAGS if type(row.get(key)) is bool}
        if row.get("language") in LANGUAGE_ORDER: sample["language"] = row["language"]
        if type(row.get("ack_id")) is int and 1 <= row["ack_id"] <= 2**31-1: sample["ack_id"] = row["ack_id"]
        if sample: clean.append(sample)
    return clean


def language_save_observation(value):
    if type(value) is not dict: return {}
    clean = {key:value[key] for key in LANGUAGE_SAVE_FLAGS if type(value.get(key)) is bool}
    if value.get("save_trigger") == "change-autosave": clean["save_trigger"] = "change-autosave"
    if value.get("feedback_source") == "options-save-feedback": clean["feedback_source"] = "options-save-feedback"
    if value.get("feedback_state") in ("ready","pending","saving","saved","invalid","failed","unknown"):
        clean["feedback_state"] = value["feedback_state"]
    if value.get("request_action") in ("save_options","unknown"): clean["request_action"] = value["request_action"]
    if type(value.get("timed_out")) is bool: clean["timed_out"] = value["timed_out"]
    for key in ("current_language","next_language","persisted_language","effective_language","request_language","ack_language","ack_effective_language"):
        if value.get(key) in (*LANGUAGE_ORDER,"unknown"): clean[key] = value[key]
    for key in ("request_id","ack_id"):
        if type(value.get(key)) is int and 1 <= value[key] <= 2**31-1: clean[key] = value[key]
    return clean


def language_observation(value):
    if type(value) is not dict: return {}
    status = value.get("server_status")
    host = value.get("unity_host")
    if type(host) is not dict and type(status) is dict: host = status.get("unity_host")
    clean = {}
    for key,raw,project in (("unity_host",host,unity_host_observation),
            ("unity_host_probe",value.get("unity_host_probe"),unity_host_probe_observation),
            ("interface_language_cycle",value.get("interface_language_cycle"),interface_language_observation),
            ("language_save",value.get("language_save"),language_save_observation)):
        sample = project(raw)
        if sample: clean[key] = sample
    return clean



def server_gate_observation(value):
    """Preserve small gate scalar types while excluding raw native errors."""
    if type(value) is not dict:
        return {}
    clean = {}
    for key in ("hook_installed", "python_initialized"):
        item = value.get(key)
        if type(item) is bool or (type(item) is int and item in (0,1)):
            clean[key] = item
    for key in ("captured", "forwarded", "attempts"):
        item = value.get(key)
        if type(item) is int and 0 <= item <= 16:
            clean[key] = item
    if "error" in value:
        clean["error"] = None if value["error"] is None else "non_null"
    return clean


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
    budget, budget_probe = status.get("octo_budget"), value.get("octo_budget_probe")
    require(type(budget_probe) is dict and budget_probe.get("prepared_without_managed_callbacks") is True,
            "octo_budget_preinit_failed")
    require(budget_probe.get("apis_registered") is True, "octo_budget_registration_failed")
    require(type(budget_probe.get("during_original_seconds")) in (int,float)
            and math.isfinite(budget_probe["during_original_seconds"])
            and budget_probe["during_original_seconds"] == 10
            and budget_probe.get("during_original_configured") is False, "octo_budget_original_failed")
    require(all(budget_probe.get(key) is True for key in
                ("configured_before_first_queued_work", "queued_work_on_main_thread", "class_initialized"))
            and all(type(budget_probe.get(key)) in (int,float) and math.isfinite(budget_probe[key])
                    and budget_probe[key] == 330 for key in ("first_queued_seconds", "last_snapshot"))
            and all(type(budget_probe.get(key)) is int and budget_probe[key] == wanted for key,wanted in
                (("initializations",1),("reads",2),("writes",1),("first_queued_snapshot_count",1),
                 ("writes_before_initialization",0))),
            "octo_budget_queued_work_failed")
    require(type(budget) is dict and type(budget.get("schema")) is int and budget["schema"] == 1
            and budget.get("status") == "configured" and budget.get("prepared") is True
            and budget.get("configured") is True and budget.get("scope") == "unified-loopback"
            and "error" in budget and budget["error"] is None
            and all(type(budget.get(key)) in (int,float) and math.isfinite(budget[key]) and budget[key] == wanted
                    for key,wanted in (("original_seconds",10),("effective_seconds",330),("cache_wait_seconds",300))),
            "octo_budget_queued_work_failed")
    http = status.get("http_readiness")
    require(type(http) is dict and type(http.get("schema")) is int and http["schema"] == 1
            and http.get("ok") is True and http.get("transport") == "NSURLSession"
            and http.get("url") == HTTP_READINESS_URL
            and type(http.get("http_status")) is int and http["http_status"] == 200
            and http.get("error_code") == "none" and http.get("body_is_json") is True
            and type(http.get("received_bytes")) is int and 1 <= http["received_bytes"] <= 16384
            and http.get("worker_main_thread") is False
            and "ns_error_domain" in http and http["ns_error_domain"] is None
            and "ns_error_code" in http and http["ns_error_code"] is None,
            "native_http_readiness_failed")
    header = value.get("native_header")
    require(type(header) is dict and header.get("owned_root_only") is True, "native_header_layout_failed")
    require(header.get("restore_succeeded") is True, "native_header_restore_failed")
    for name in HEADER_PHASES:
        sample = header.get(name)
        require(type(sample) is dict and all(sample.get(key) is True for key in HEADER_BOOL_FIELDS)
                and type(sample.get("button_count")) is int and sample["button_count"] == 2
                and all(type(sample.get(key)) in (int, float) and 0 < sample[key] <= 16384
                        and math.isfinite(sample[key]) for key in HEADER_NUMBER_FIELDS), "native_header_layout_failed")
        require(sample["header_width"] <= sample["root_width"]
                and sample["actions_width"] <= sample["header_width"]
                and sample["header_height"] <= sample["root_height"]
                and sample["min_button_height"] >= 44, "native_header_layout_failed")
        if name in ("current", "restored"):
            require(all(sample[key] >= floor for key, floor in zip(HEADER_FONT_FIELDS, (16, 20, 16, 12))),
                    "native_header_layout_failed")
    current, wide, ultra, restored = (header[name] for name in HEADER_PHASES)
    require(wide["root_width"] == 1920 and wide["root_height"] == 1080
            and wide["button_min_font"] >= 20 and wide["status_font"] >= 20
            and ultra["root_width"] == 3840 and ultra["root_height"] == 2160
            and ultra["button_min_font"] >= 40 and ultra["status_font"] >= 40
            and all(wide[key] > current[key] and ultra[key] > wide[key] for key in HEADER_FONT_FIELDS),
            "native_header_layout_failed")
    require(all(abs(restored[key] - current[key]) <= 0.1
                for key in ("root_width", "root_height", *HEADER_FONT_FIELDS)), "native_header_restore_failed")
    expected_lifecycle = {"installed":True, "strategy":"reuse-existing", "initialize_calls":1,
                          "original_initialize_calls":0, "reused_existing_calls":1}
    lifecycle = status.get("keyboard_lifecycle")
    require(status.get("keyboard_ready") is True and type(lifecycle) is dict
            and all(type(lifecycle.get(key)) is type(wanted) and lifecycle[key] == wanted
                    for key, wanted in expected_lifecycle.items()), "keyboard_after_init_failed")
    keyboard = value.get("keyboard")
    require(type(keyboard) is dict, "keyboard_evidence_missing")
    expected_keyboard = {
        "before_capture": {"ready":False, "phase":2, "returned_nil":False,
                           "returned_initialized_field":True, "returned_same_field":True,
                           "original_calls":1, "field_creation_count":1},
        "before_launch": {"ready":False, "phase":2, "returned_nil":False,
                          "returned_initialized_field":True, "returned_same_field":True,
                          "original_calls":2, "field_creation_count":1},
        "during_init": {"ready":False, "phase":4, "returned_nil":False,
                        "returned_initialized_field":True, "returned_same_field":True,
                        "original_calls":3, "field_creation_count":1},
        "after_init": {"ready":True, "phase":4, "returned_nil":False,
                       "returned_initialized_field":True, "returned_same_field":True,
                       "original_calls":4, "field_creation_count":1},
    }
    for name, expected in expected_keyboard.items():
        observed = keyboard.get(name)
        require(type(observed) is dict and all(type(observed.get(key)) is type(wanted)
                and observed[key] == wanted for key, wanted in expected.items()),
                "keyboard_" + name + "_failed")
        expected = dict(expected_lifecycle)
        if name in ("before_capture", "before_launch"):
            expected.update(installed=False, initialize_calls=0, reused_existing_calls=0)
        seen_lifecycle = observed.get("lifecycle")
        require(type(seen_lifecycle) is dict and all(type(seen_lifecycle.get(key)) is type(wanted)
                and seen_lifecycle[key] == wanted for key, wanted in expected.items()),
                "keyboard_" + name + "_failed")
    host_probe = value.get("unity_host_probe")
    expected_language = host_probe.get("expected_language") if type(host_probe) is dict else None
    language_summary = _validate_language_evidence(status.get("unity_host"), host_probe,
        value.get("interface_language_cycle"), value.get("language_save"), expected_language,
        host_probe.get("run_index") if type(host_probe) is dict else None)
    data = status.get("client_data")
    require(type(data) is dict and data.get("selected") is True
            and data.get("language") == expected_language
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
            and type(early.get("captured")) is int and early["captured"] == 1
            and early.get("completion_main_thread") is True, "early_status_correlation_failed")
    require(type(launcher.get("startup_evidence_version")) is int and launcher["startup_evidence_version"] == 2
            and type(launcher.get("premature_captured")) is int and launcher["premature_captured"] == 1
            and launcher.get("server_ready_before_runtime") is True
            and type(launcher.get("cold_original_called")) is int and launcher["cold_original_called"] == 0
            and type(launcher.get("cold_attempts")) is int and launcher["cold_attempts"] == 1
            and launcher.get("host_capture_once") is True, "server_not_ready_before_capture")
    require(type(launcher.get("ready_phase")) is int and launcher["ready_phase"] == 2
            and type(launcher.get("ready_captured")) is int and launcher["ready_captured"] == 1
            and type(launcher.get("ready_original_called")) is int and launcher["ready_original_called"] == 0
            and launcher.get("ready_launch_requested") is False
            and launcher.get("ready_launch_prepared") is False
            and type(launcher.get("ready_observations")) is int and launcher["ready_observations"] >= 2
            and type(launcher.get("ready_wait_seconds")) in (int, float)
            and 5.0 <= launcher["ready_wait_seconds"] <= 60.0,
            "unity_started_before_launch_button")
    require(launcher.get("ready_launcher_visible") is True and launcher.get("ready_button_found") is True
            and launcher.get("ready_button_enabled") is True
            and launcher.get("ready_button_kind") == "UIButton"
            and launcher.get("ready_button_title") in ("게임 시작", "ゲーム開始", "Start Game"), "ready_launch_control_failed")
    require(all(launcher.get(key) is True for key in LAUNCH_SETTINGS_FLAGS), "launch_settings_barrier_failed")
    require(launcher.get("button_action_dispatched") is True
            and launcher.get("button_control_event") == "touch-up-inside"
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
        "return_action_dispatched", "dismissed", "menu_view_detached_after_close", "game_window_key_after_close", "status_completion_main_thread",
        "grpc_connected_after_close", "assets_connected_after_close")), "settings_menu_lifetime_failed")
    require(menu.get("return_button_kind") == "UIButton" and menu.get("server_button_kind") == "UIButton"
            and menu.get("return_control_event") == "touch-up-inside", "settings_menu_lifetime_failed")
    copied = menu.get("diagnostics_copy")
    require(type(copied) is dict and all(copied.get(key) is True for key in DIAGNOSTICS_COPY_BOOL_FIELDS)
            and copied.get("timed_out") is False and type(copied.get("text_bytes")) is int
            and 1 <= copied["text_bytes"] <= 32768, "settings_diagnostics_copy_failed")
    zipped = menu.get("zip_import_picker")
    require(type(zipped) is dict and zipped.get("scope") == "stock-simulator"
            and zipped.get("cancel_trigger") == "delegate-callback" and zipped.get("timed_out") is False
            and all(zipped.get(key) is True for key in ZIP_IMPORT_SERVER_FLAGS)
            and type(zipped.get("observations")) is int and 1 <= zipped["observations"] <= 200
            and type(zipped.get("elapsed_seconds")) in (int, float)
            and math.isfinite(zipped["elapsed_seconds"]) and 0 <= zipped["elapsed_seconds"] <= 60
            and type(zipped.get("passes")) is list and len(zipped["passes"]) == 2
            and all(type(sample) is dict and all(sample.get(key) is True for key in ZIP_IMPORT_PASS_BOOL_FIELDS)
                    and type(sample.get("document_picker_mode")) is int and sample["document_picker_mode"] == 0
                    for sample in zipped["passes"]), "settings_zip_import_picker_failed")
    roundtrip = validate_zip_roundtrip(menu.get("zip_roundtrip"), language_summary["run_index"])
    accounts = validate_account_management(menu.get("account_management"), language_summary["run_index"])
    official_prompt = validate_official_prompt(menu.get("official_prompt"), language_summary["run_index"])
    width, window_width = menu.get("frame_width"), menu.get("window_width")
    require(all(type(v) in (int, float) and math.isfinite(v) and 0 < v <= 16384 for v in (width, window_width))
            and abs(width - window_width) <= 2, "settings_menu_width_failed")
    dismissal = menu_close_observation(menu.get("dismiss_observation"))
    require(all(dismissal.get(key) is False for key in (
        "presented_controller_remaining", "settings_controller_still_presented", "settings_view_attached", "timed_out"))
        and dismissal.get("game_window_key") is True and dismissal.get("observations", 0) >= 1
        and "wait_seconds" in dismissal, "settings_menu_dismissal_evidence_failed")
    web = menu.get("web")
    require(type(web) is dict and all(web.get(key) is True for key in (
        "web_found", "evaluation_succeeded", "ready", "forms_present", "scale_2_present", "buffer_4096_present",
        "no_horizontal_overflow", "navigation_file_url", "web_attached", "evaluation_started", "evaluation_completed",
        "data_store_reused", "launcher_store_nonpersistent", "menu_store_nonpersistent", "web_view_recreated", "launcher_document_marker_absent"))
        and web.get("navigation_loading") is False and type(web.get("navigation_progress")) in (int,float)
        and web["navigation_progress"] == 1.0 and web.get("timed_out") is False, "settings_web_readiness_or_layout_failed")
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
            "keyboard": keyboard_observation(keyboard),
            "octo_budget_probe": octo_budget_probe_observation(budget_probe),
            "unity_host_probe":language_summary["unity_host_probe"],
            "interface_language_cycle":language_summary["interface_language_cycle"],
            "language_save":language_summary["language_save"],
            "native_header": header_observation(header),
            "early_status": {key: early[key] for key in (
                "id", "ok", "state", "running", "phase", "captured", "completion_main_thread")},
            "launcher": {key: launcher[key] for key in (
                "premature_phase", "premature_original_called", "premature_launch_requested", "premature_captured",
                "startup_evidence_version", "server_ready_before_runtime", "cold_original_called", "cold_attempts", "host_capture_once",
                "ready_phase", "ready_captured", "ready_original_called", "ready_launch_requested", "ready_launch_prepared",
                "ready_observations", "ready_wait_seconds", "ready_launcher_visible", "ready_button_found",
                "ready_button_enabled", "ready_button_title", "ready_button_kind", "button_action_dispatched",
                "button_control_event", "button_dispatch_count", "duplicate_launch_called", "forwarded_after_button", *LAUNCH_SETTINGS_FLAGS)},
            "corner_gesture": {key: corner[key] for key in (
                "game_window_key", "matching_count", "recognizer_name", "one_finger_count", "three_finger_count", "minimum_press_seconds",
                "allowable_movement_points", "delegate_present", "delays_touches_began",
                "delays_touches_ended", "cancels_touches_in_view")},
            "server_status": {**{key: status[key] for key in
                ("schema", "phase", "hook_installed", "python_initialized", "captured", "forwarded", "attempts",
                 "launch_requested", "launch_prepared", "launcher_visible")},
                 "keyboard_lifecycle":keyboard_lifecycle_observation(lifecycle), "keyboard_ready":True,
                 "http_readiness":http_readiness_observation(http),
                 "octo_budget":octo_budget_observation(budget),
                 "unity_host":language_summary["unity_host"],
                 "client_data":{key: data[key] for key in ("selected", "language", "bundle_identifier")}},
            "menu_lifetime": {**{key: menu[key] for key in (
                "opened_via_owned_menu_target", "full_screen", "frame_width_matches", "return_button_found",
                "server_control_found", "server_control_disabled_while_running",
                "return_button_kind", "server_button_kind", "return_control_event",
                "return_action_dispatched", "dismissed", "menu_view_detached_after_close", "game_window_key_after_close", "status_completion_main_thread",
                "grpc_connected_after_close", "assets_connected_after_close", "frame_width", "window_width")},
                "dismiss_observation":dismissal, "diagnostics_copy":diagnostics_copy_observation(copied),
                "zip_import_picker":zip_import_observation(zipped), "zip_roundtrip":roundtrip, "account_management":accounts, "official_prompt":official_prompt,
                "web": {key: web[key] for key in ("web_found", "evaluation_succeeded", "ready", "forms_present",
                    "scale_2_present", "buffer_4096_present", "no_horizontal_overflow", "timed_out",
                    "viewport_width", "content_width", "select_count", "navigation_loading", "navigation_file_url",
                    "web_attached", "navigation_progress", "evaluation_started", "evaluation_completed", "data_store_reused",
                    "launcher_store_nonpersistent", "menu_store_nonpersistent", "web_view_recreated", "launcher_document_marker_absent")},
                "host_status_after_close": {"id":2,"ok":True,"result":{"state":"ready","running":True,
                    "runtime":{key:after_runtime[key] for key in ("running","grpc_address","asset_url")}}}},
            "ports": {key: ports[key] for key in ("grpc", "assets", "grpc_connect", "assets_connect")},
            "commoncrypto": {"nist_aes128_cbc": True, "nist_aes256_cbc": True},
            "host_status": {"id": 1, "ok": True, "result": {"state": "ready", "running": True,
                "runtime": {key: runtime[key] for key in ("running", "grpc_address", "asset_url")}}}}



UI_TEST_SOURCE_PATHS = ("ui_test_driver.py", "ui-tests/CancelDriverHost.swift", "ui-tests/OfficialPromptCancelTests.swift",
    "ui-tests/IdolyProbeCancelUITests.xcodeproj/project.pbxproj",
    "ui-tests/IdolyProbeCancelUITests.xcodeproj/xcshareddata/xcschemes/IdolyProbeCancelUITests.xcscheme")
UI_TEST_IDENTIFIER = "IdolyProbeCancelUITests/OfficialPromptCancelTests/testCancelExistingProbePrompt"


def official_ui_source_pins():
    try:
        return {name:hashlib.sha256(read_bounded(PROBE_SOURCE_DIR/name,256*1024)).hexdigest() for name in UI_TEST_SOURCE_PATHS}
    except (OSError,ProbeError):
        raise ProbeError("official_ui_test_sources_unavailable") from None


def validate_official_ui_proof(value, *, expected_simulator=None):
    fail="official_ui_test_evidence_failed"
    require(type(value) is dict and type(value.get("schema")) is int and value["schema"]==1
        and value.get("status")=="PASS" and value.get("execution")=="public_xctest"
        and value.get("test_identifier")==UI_TEST_IDENTIFIER
        and type(value.get("tests")) is int and value["tests"]==1
        and type(value.get("failures")) is int and value["failures"]==0
        and type(value.get("skipped")) is int and value["skipped"]==0
        and value.get("actual_cancel_tap") is True and value.get("ready_marker_observed") is True,fail)
    identifier=value.get("simulator_udid")
    require(type(identifier) is str and re.fullmatch(r"[0-9A-F]{8}(?:-[0-9A-F]{4}){3}-[0-9A-F]{12}",identifier)
        and (expected_simulator is None or identifier==expected_simulator),fail)
    pins=official_ui_source_pins()
    source_hash=hashlib.sha256(json.dumps(pins,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    require(type(value.get("source_pins")) is dict and value["source_pins"]==pins and value.get("source_sha256")==source_hash
        and all(_hex_digest(value.get(key)) for key in ("xctestrun_sha256","xcresult_summary_sha256","xcresult_tests_sha256")),fail)
    return {key:value[key] for key in ("schema","status","execution","simulator_udid","test_identifier","tests","failures",
        "skipped","actual_cancel_tap","ready_marker_observed","source_pins","source_sha256","xctestrun_sha256",
        "xcresult_summary_sha256","xcresult_tests_sha256")}


def _poll_official_ui_driver(driver):
    try:
        state=driver.poll()
    except DriverError as error:
        raise ProbeError(error.code if error.code in UI_DRIVER_ERRORS else "official_ui_test_driver_failed") from None
    require(type(state) is dict and state.get("phase") in ("building","running","passed","failed")
        and type(state.get("ready")) is bool,"official_ui_test_driver_failed")
    if state["phase"]=="failed":
        code=state.get("error_code")
        raise ProbeError(code if type(code) is str and code in UI_DRIVER_ERRORS else "official_ui_test_driver_failed")
    return state


def official_ui_build_metadata(value):
    """Project only fixed pre-input schema metadata, never paths or plist values."""
    fail="official_ui_metadata_invalid"
    require(type(value) is dict and type(value.get("schema")) is int and value["schema"]==1
        and value.get("scope")=="pre-input-generated-xctestrun" and type(value.get("check")) is str and value["check"] in UI_DIAGNOSTIC_CHECKS,fail)
    clean={key:value[key] for key in ("schema","scope","check")}
    for key in ("all_xctestrun_count","candidate_count","configuration_count","target_count"):
        if key in value:
            require(type(value[key]) is int and 0<=value[key]<=129,fail);clean[key]=value[key]
    if "plist_bytes" in value:
        require(type(value["plist_bytes"]) is int and 1<=value["plist_bytes"]<=262144,fail);clean["plist_bytes"]=value["plist_bytes"]
    if "plist_sha256" in value:
        require(_hex_digest(value["plist_sha256"]),fail);clean["plist_sha256"]=value["plist_sha256"]
    if "format_version_type" in value:
        require(type(value["format_version_type"]) is str and value["format_version_type"] in UI_DIAGNOSTIC_TYPES,fail);clean["format_version_type"]=value["format_version_type"]
    if "format_version" in value:
        observed=value["format_version"];require(observed is None or (type(observed) is int and observed in (1,2)),fail);clean["format_version"]=observed
    for key in ("blueprint_matches","is_ui_test_bundle"):
        if key in value:
            require(type(value[key]) is bool,fail);clean[key]=value[key]
    for group,names in (("paths",("test_host","test_bundle","dummy_app")),("bundles",("runner","dummy"))):
        if group not in value:continue
        require(type(value[group]) is dict,fail);clean[group]={}
        for name in names:
            if name not in value[group]:continue
            row=value[group][name];require(type(row) is dict,fail)
            if group=="paths":
                require(type(row.get("type")) is str and row["type"] in UI_DIAGNOSTIC_TYPES
                    and type(row.get("token_kind")) is str and row["token_kind"] in UI_DIAGNOSTIC_TOKEN_KINDS
                    and type(row.get("owned")) is bool and "exists" in row and (row["exists"] is None or type(row["exists"]) is bool),fail)
                clean[group][name]={key:row[key] for key in ("type","token_kind","owned","exists")}
            else:
                require(type(row.get("bundle_matches")) is bool and type(row.get("platforms_type")) is str and row["platforms_type"] in UI_DIAGNOSTIC_TYPES
                    and type(row.get("platforms_exact")) is bool,fail)
                clean[group][name]={key:row[key] for key in ("bundle_matches","platforms_type","platforms_exact")}
    require(len(json.dumps(clean,separators=(",",":"),sort_keys=True).encode())<=8192,fail)
    return clean


OFFICIAL_PROMPT_FLAGS = ("button_found", "enabled_before", "click_dispatched", "empty_web_payload", "prompt_presented",
    "field_count_two", "secure_password_field", "platform_actions_present", "cancel_action_present", "synthetic_inputs_set",
    "cancel_ack_observed", "fields_cleared", "web_reply_cancelled", "prompt_detached", "official_job_absent_before",
    "official_job_absent_after", "account_data_unchanged", "runtime_identity_unchanged", "completed")


def official_prompt_observation(value):
    if type(value) is not dict: return {}
    clean = {key:value[key] for key in (*OFFICIAL_PROMPT_FLAGS, "performed", "timed_out", "credential_submission_performed")
             if type(value.get(key)) is bool}
    for key, expected in (("scope","stock-simulator"),("ui_trigger","dom-click"),
                          ("cancel_trigger","public-xctest-tap"),("reason","first-cold-run-only")):
        if value.get(key) == expected: clean[key] = expected
    seconds = value.get("elapsed_seconds")
    if type(seconds) in (int,float) and math.isfinite(seconds) and 0 <= seconds <= 30: clean["elapsed_seconds"] = seconds
    if type(value.get("ui_test")) is dict:
        try: clean["ui_test"]=validate_official_ui_proof(value["ui_test"])
        except ProbeError: pass
    return clean


def validate_official_prompt(value, run_index):
    fail = "settings_official_prompt_failed"
    require(type(value) is dict,fail)
    if run_index != 0:
        require(value == {"performed":False,"reason":"first-cold-run-only"} and type(value.get("performed")) is bool,fail)
        return dict(value)
    require(value.get("performed") is True and value.get("scope") == "stock-simulator"
        and value.get("ui_trigger") == "dom-click" and value.get("cancel_trigger") == "public-xctest-tap"
        and value.get("timed_out") is False and value.get("credential_submission_performed") is False
        and all(value.get(key) is True for key in OFFICIAL_PROMPT_FLAGS)
        and type(value.get("elapsed_seconds")) in (int,float) and math.isfinite(value["elapsed_seconds"])
        and 0 <= value["elapsed_seconds"] <= 30,fail)
    validate_official_ui_proof(value.get("ui_test"))
    return official_prompt_observation(value)


ACCOUNT_TABLES = ("profiles", "snapshots", "profile_settings", "starter_profiles",
                  "profile_lesson_progress", "preference_receipts", "main_live_attempts")
ACCOUNT_BLOB_TABLES = ("snapshots", "profile_settings", "profile_lesson_progress",
                       "preference_receipts", "main_live_attempts")
ACCOUNT_UI_FLAGS = ("management_controls_ready", "inactive_clone_created", "export_reply_correlated",
    "active_account_replace_rejected", "new_import_completed", "automatic_restore_point_created",
    "inactive_replace_completed", "restore_revision_matches", "next_start_selection_saved",
    "original_selection_saved", "feedback_present", "fields_reenabled", "native_copy_queued",
    "native_copy_bytes_match")
ACCOUNT_NATIVE_FLAGS = ("export_picker_presented", "export_picker_cancelled", "archive_copy_sha256_verified",
    "next_selection_pending_only", "original_runtime_preserved", "listeners_survived")
ACCOUNT_STATE_FLAGS = ("all_seven_tables_nonempty", "archive_all_tables_exact", "new_import_all_tables_exact",
    "restored_all_tables_exact", "unknown_response_blobs_exact", "source_account_preserved",
    "original_account_preserved", "original_sessions_preserved", "source_session_preserved",
    "target_session_invalidated", "original_selection_restored")
ACCOUNT_UI_ACTIONS = ("accounts_status", "accounts_clone", "accounts_status", "accounts_export",
    "accounts_preview", "accounts_import", "accounts_import", "accounts_status",
    "accounts_preview", "accounts_import", "accounts_restore", "accounts_select", "accounts_select")


def _normalized_account(bundle):
    from copy import deepcopy
    from idoly_local.state import State
    value = deepcopy(bundle)
    value["profile"] = "normalized"
    for table, rows in value["tables"].items():
        for row in rows:
            row["name" if table == "profiles" else "profile"] = "normalized"
    return State.account_bytes(value)


class AccountFixtureHarness:
    """Two explicit fixtures in inactive profiles of this invocation's owned Simulator.

    This is test-only SQLite fixture production, never a product server command
    and never evidence of actual game progression or Files row interaction.
    """
    def __init__(self, container, schema, *, descriptor_sha256, nonce=None):
        candidate=Path(container)
        require(candidate.is_absolute() and candidate.is_dir() and not candidate.is_symlink(),"settings_account_fixture_failed")
        self.container = candidate.resolve(strict=True)
        self.documents = self.container/"Documents"
        self.documents.mkdir(exist_ok=True)
        require(self.documents.is_dir() and not self.documents.is_symlink(),"settings_account_fixture_failed")
        self.root = self.container/"Library/Application Support/IdolyPrideLocal"
        self.schema = schema
        # Package bytes and the canonical descriptor identity are separate:
        # Schema sorts FileDescriptorSet entries for its account fingerprint.
        require(_hex_digest(descriptor_sha256), "settings_account_fixture_failed")
        self.descriptor_sha256 = descriptor_sha256
        self.nonce = nonce if nonce is not None else uuid.uuid4().hex
        require(type(self.nonce) is str and re.fullmatch(r"[0-9a-f]{32}", self.nonce), "settings_account_fixture_failed")
        self.source = "probe-acct-" + self.nonce[:12] + "-clone"
        self.target = "probe-acct-" + self.nonce[:12] + "-import"
        self.input = self.documents/"probe-account-fixture.json"
        self.request = self.documents/"embedded-probe-account-seed.json"
        self.ack = self.documents/"embedded-probe-account-seed-ack.json"
        self.archive = self.documents/("probe-account-" + self.nonce + ".zip")
        for path in (self.input, self.request, self.ack, self.archive):
            require(not path.exists() and not path.is_symlink(), "settings_account_fixture_failed")
        self._write(self.input, {"schema": 1, "nonce": self.nonce})
        self.created_ns = self.input.stat().st_mtime_ns
        self.done, self.mode = {}, None
        self.source_bundle = self.target_bundle = self.original_bundle = None
        self.original_sessions = None
        self.source_token = self.target_token = None
        self.import_exact = False

    @staticmethod
    def _write(path, value):
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        require(len(raw) <= 8192 and not path.is_symlink(), "settings_account_fixture_failed")
        temporary = path.with_name("." + path.name + "." + uuid.uuid4().hex + ".tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
            require(not path.is_symlink(), "settings_account_fixture_failed")
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def _state(self, mode):
        from idoly_local.state import State
        path = self.root/("media-state.db" if mode == "media" else "state.db")
        require(path.is_file() and not path.is_symlink() and path.stat().st_nlink == 1,
                "settings_account_fixture_failed")
        return State(path)

    @staticmethod
    def _sessions(state, profile):
        with state.connect() as db:
            return [tuple(row) for row in db.execute(
                "SELECT token_hash,profile,expires_at FROM sessions WHERE profile=? ORDER BY token_hash", (profile,))]

    def _fixture(self, state, profile, phase):
        from copy import deepcopy
        from idoly_local.state import State
        from google.protobuf import message_factory
        found = state.account_snapshot(profile)
        require(found is not None, "settings_account_fixture_failed")
        bundle, revision = found
        bundle = deepcopy(bundle)
        tables = bundle["tables"]
        require(set(tables) == set(ACCOUNT_TABLES)
                and all(row["schema_sha256"] == self.schema.fingerprint
                    for rows in tables.values() for row in rows if "schema_sha256" in row),
                "settings_account_fixture_failed")
        suffix = PUBLIC_PROBE_FIELD if phase == "source" else PUBLIC_PROBE_FIELD[:-1] + b"\x02"
        require(19000 not in self.schema.response_type("/api.User/Get").DESCRIPTOR.fields_by_number,
                "settings_account_fixture_failed")
        response = self.schema.response_type("/api.User/Get").FromString(tables["snapshots"][0]["response"])
        if phase == "target": response.user.name = "ProbeB"
        tables["snapshots"][0]["response"] = response.SerializeToString() + suffix
        if not tables["starter_profiles"]:
            tables["starter_profiles"] = [{"profile": profile, "version": 0}]
        descriptors = {
            "profile_settings": self.schema.request_type("/api.Home/Login").DESCRIPTOR.fields_by_name["settingInfo"].message_type,
            "profile_lesson_progress": self.schema.response_type("/api.Activity/ReceiveLessonReward").DESCRIPTOR.fields_by_name["progress"].message_type,
        }
        for table, descriptor in descriptors.items():
            require(19000 not in descriptor.fields_by_number, "settings_account_fixture_failed")
            message = message_factory.GetMessageClass(descriptor)
            raw = tables[table][0]["response"] if tables[table] else message().SerializeToString()
            message.FromString(raw + suffix)
            tables[table] = [{"profile": profile, "response": raw + suffix, "schema_sha256": self.schema.fingerprint}]
        request_base = 8800000000000000001 if phase == "source" else 8800000000000000003
        for table, path, index in (("preference_receipts", "/api.Photo/SwitchLock", 0),
                                   ("main_live_attempts", "/api.Quest/Start", 1)):
            message = self.schema.response_type(path)
            require(19000 not in message.DESCRIPTOR.fields_by_number, "settings_account_fixture_failed")
            row = {"profile": profile, "path": path, "request_id": str(request_base + index),
                "request_sha256": hashlib.sha256((self.nonce + phase + table).encode()).hexdigest(),
                "schema_sha256": self.schema.fingerprint, "response": message().SerializeToString() + suffix}
            if table == "main_live_attempts":
                row.update(master_version="probe-owned-account-fixture", ruleset="probe-account-state-v1",
                           seed="17", started_time=1700000000000)
            tables[table].append(row)
            columns = ("profile", "path", "request_id") if table == "preference_receipts" else ("profile", "request_id")
            tables[table].sort(key=lambda item: tuple(item[key] for key in columns))
        State.validate_account(bundle)
        require(all(tables[table] for table in ACCOUNT_TABLES), "settings_account_fixture_failed")
        state.replace_account(profile, bundle, expected_revision=revision)
        actual = state.account_snapshot(profile)
        require(actual[0] == bundle, "settings_account_fixture_failed")
        return actual

    def process(self):
        from idoly_local.account_manager import selection_status
        try:
            info = self.request.lstat()
        except FileNotFoundError:
            return
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and 0 < info.st_size <= 8192
                and info.st_mtime_ns >= self.created_ns, "settings_account_fixture_failed")
        raw = read_bounded(self.request, 8192)
        request = parse_json(raw, 8192)
        phase = request.get("phase")
        require(phase in ("source", "target"), "settings_account_fixture_failed")
        fingerprint = hashlib.sha256(raw).hexdigest()
        if phase in self.done:
            require(self.done[phase] == fingerprint, "settings_account_fixture_failed")
            return
        require(phase == ("source" if not self.done else "target"), "settings_account_fixture_failed")
        require(set(request) == {"schema", "run_index", "nonce", "phase", "mode", "profile", "active_profile"}
                and type(request.get("schema")) is int and request["schema"] == 1
                and type(request.get("run_index")) is int and request["run_index"] == 0
                and request.get("nonce") == hashlib.sha256((self.nonce + ":" + phase).encode()).hexdigest()[:32]
                and request.get("mode") in ("normal", "media")
                and request.get("profile") == (self.source if phase == "source" else self.target)
                and request.get("active_profile") == "sandbox", "settings_account_fixture_failed")
        mode = request["mode"]
        require(self.mode in (None, mode) and self.root.is_dir() and not self.root.is_symlink()
                and hashlib.sha256(read_bounded(self.root/"protocol/idolypride-6.1.1.pb", MAX_DESCRIPTOR)).hexdigest()
                    == self.descriptor_sha256
                and selection_status(self.root)["selected"][mode] == "sandbox", "settings_account_fixture_failed")
        require(not self.ack.exists() and not self.ack.is_symlink(), "settings_account_fixture_failed")
        self.mode = mode
        state = self._state(mode)
        current = state.account_snapshot("sandbox")
        require(current is not None, "settings_account_fixture_failed")
        if phase == "source":
            self.original_bundle = current
            self.original_sessions = self._sessions(state, "sandbox")
            self.source_bundle = self._fixture(state, self.source, phase)
            self.source_token, _identity = state.login(self.source)
            bundle, revision = self.source_bundle
        else:
            require(state.account_snapshot("sandbox") == self.original_bundle, "settings_account_fixture_failed")
            imported = state.account_snapshot(self.target)
            self.import_exact = imported is not None and _normalized_account(imported[0]) == _normalized_account(self.source_bundle[0])
            require(self.import_exact and self._sessions(state, self.target) == [], "settings_account_fixture_failed")
            self.target_bundle = self._fixture(state, self.target, phase)
            self.target_token, _identity = state.login(self.target)
            bundle, revision = self.target_bundle
        require(not self.ack.exists() and not self.ack.is_symlink(), "settings_account_fixture_failed")
        ack = {"schema": 1, "ready": True, "phase": phase, "nonce": request["nonce"], "profile": request["profile"],
            "mode": mode, "request_sha256": fingerprint, "bundle_revision": revision,
            "normalized_sha256": hashlib.sha256(_normalized_account(bundle)).hexdigest(),
            "table_rows": {table: len(bundle["tables"][table]) for table in ACCOUNT_TABLES},
            "unknown_tables": list(ACCOUNT_BLOB_TABLES)}
        self._write(self.ack, ack)
        self.done[phase] = fingerprint

    def verify_persisted(self):
        from idoly_local.account_manager import selection_status
        require(set(self.done) == {"source", "target"}, "settings_account_fixture_failed")
        state = self._state(self.mode)
        source, target = state.account_snapshot(self.source), state.account_snapshot(self.target)
        checks = {"source_all_tables_persisted": source == self.source_bundle,
            "restored_all_tables_persisted": target == self.target_bundle,
            "source_session_preserved": state.authenticated(self.source_token,self.source),
            "target_session_invalidated": not state.authenticated(self.target_token,self.target),
            "original_selection_preserved": selection_status(self.root)["selected"][self.mode] == "sandbox"}
        require(all(type(value) is bool and value is True for value in checks.values()), "settings_account_fixture_failed")
        return {"schema":1,"observer":"runner-sqlite-after-five-cold-runs","seed_fixture_used":True,
            "gameplay_tested":False,"checks":checks,"normalized_source_sha256":hashlib.sha256(_normalized_account(source[0])).hexdigest(),
            "normalized_restored_sha256":hashlib.sha256(_normalized_account(target[0])).hexdigest()}

    def verify(self, native):
        import base64
        from idoly_local.account_manager import selection_status
        from idoly_local.state import State
        require(set(self.done) == {"source", "target"} and self.mode is not None,
                "settings_account_fixture_failed")
        info = self.archive.lstat()
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and 0 < info.st_size <= 128*1024**2,
                "settings_account_fixture_failed")
        fd = os.open(self.archive, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            before = os.fstat(stream.fileno())
            sha = hashlib.file_digest(stream, "sha256").hexdigest()
            stream.seek(0)
            with ZipFile(stream) as archive:
                members = archive.infolist()
                require(len(members) == 2 and {row.filename for row in members} == {"manifest.json", "account.json"}
                        and all(0 < row.file_size <= (16384 if row.filename == "manifest.json" else 96*1024**2)
                                for row in members), "settings_account_fixture_failed")
                manifest = parse_json(archive.read("manifest.json"), 16384)
                account_bytes = archive.read("account.json")
            after = os.fstat(stream.fileno())
            require((before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns) ==
                    (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns),
                    "settings_account_fixture_failed")
        require(sha == native.get("archive_sha256") and before.st_size == native.get("archive_bytes")
                and manifest.get("kind") == "idoly-local-account" and manifest.get("mode") == self.mode
                and manifest.get("profile") == self.source and manifest.get("account_bytes") == len(account_bytes)
                and manifest.get("account_sha256") == hashlib.sha256(account_bytes).hexdigest(),
                "settings_account_fixture_failed")
        def unpack(value):
            if type(value) is dict and set(value) == {"$bytes"}:
                return base64.b64decode(value["$bytes"], validate=True)
            return value
        archived = json.loads(account_bytes, object_hook=unpack)
        State.validate_account(archived)
        state = self._state(self.mode)
        source, target = state.account_snapshot(self.source), state.account_snapshot(self.target)
        require(source is not None and target is not None, "settings_account_fixture_failed")
        checks = {
            "all_seven_tables_nonempty": all(self.source_bundle[0]["tables"][table] for table in ACCOUNT_TABLES),
            "archive_all_tables_exact": archived == self.source_bundle[0],
            "new_import_all_tables_exact": self.import_exact,
            "restored_all_tables_exact": target == self.target_bundle,
            "unknown_response_blobs_exact": all(
                target[0]["tables"][table] == self.target_bundle[0]["tables"][table] for table in ACCOUNT_BLOB_TABLES),
            "source_account_preserved": source == self.source_bundle,
            "original_account_preserved": state.account_snapshot("sandbox") == self.original_bundle,
            "original_sessions_preserved": self._sessions(state,"sandbox") == self.original_sessions,
            "source_session_preserved": state.authenticated(self.source_token, self.source),
            "target_session_invalidated": not state.authenticated(self.target_token, self.target),
            "original_selection_restored": selection_status(self.root)["selected"][self.mode] == "sandbox",
        }
        # A positive row-count expression must become a true JSON boolean, not a list.
        checks["all_seven_tables_nonempty"] = bool(checks["all_seven_tables_nonempty"])
        require(all(type(value) is bool and value is True for value in checks.values()),
                "settings_account_fixture_failed")
        return {"observer": "runner-sqlite-and-archive", "seed_fixture_used": True, "gameplay_tested": False,
            "checks": checks, "table_rows": {table: len(target[0]["tables"][table]) for table in ACCOUNT_TABLES},
            "normalized_source_sha256": hashlib.sha256(_normalized_account(source[0])).hexdigest(),
            "normalized_restored_sha256": hashlib.sha256(_normalized_account(target[0])).hexdigest(),
            "archive_sha256": sha, "archive_bytes": before.st_size}


def wait_report(container, remaining, *, expected_language="ko", run_index=None, account_fixture=None, ui_driver=None, simulator_udid=None):
    documents = Path(container) / "Documents"
    final_name, waiting_name, _checkpoint_name = language_paths(expected_language,run_index)
    final, waiting = documents / final_name, documents / waiting_name
    last_keyboard = {}
    last_header = {}
    last_http = {}
    last_copy = {}
    last_budget = {}
    last_budget_probe = {}
    last_language = {}
    last_server_gate = {}
    last_settings_web = {}
    def checked_remaining():
        try:
            return remaining()
        except ProbeError as error:
            if last_keyboard:
                error.native_keyboard = dict(last_keyboard)
            if last_header:
                error.native_header = dict(last_header)
            if last_http:
                error.native_http = dict(last_http)
            if last_copy:
                error.native_diagnostics_copy = dict(last_copy)
            if last_budget:
                error.native_octo_budget = dict(last_budget)
            if last_budget_probe:
                error.native_octo_budget_probe = dict(last_budget_probe)
            if last_language:
                error.native_language = dict(last_language)
            if last_server_gate:
                error.native_server_gate = dict(last_server_gate)
            if last_settings_web:
                error.native_settings_web = dict(last_settings_web)
            raise
    while True:
        checked_remaining()
        if ui_driver is not None:
            _poll_official_ui_driver(ui_driver)
        if account_fixture is not None:
            account_fixture.process()
        try:
            observed = parse_json(read_bounded(final, MAX_JSON))
            if account_fixture is not None:
                menu = observed.get("menu_lifetime")
                detail = menu.get("account_management") if type(menu) is dict else None
                if type(detail) is dict:
                    detail["state_observation"] = account_fixture.verify(detail)
            if ui_driver is not None:
                try:
                    proof=validate_official_ui_proof(ui_driver.finish(),expected_simulator=simulator_udid)
                except DriverError as error:
                    raise ProbeError(error.code if error.code in UI_DRIVER_ERRORS else "official_ui_test_driver_failed") from None
                menu=observed.get("menu_lifetime")
                require(type(menu) is dict and type(menu.get("official_prompt")) is dict,"official_ui_test_evidence_failed")
                menu["official_prompt"]["ui_test"]=proof
            try:
                checked = validate_report(observed)
                expected_index = MATRIX_LANGUAGES.index(expected_language) if run_index is None else run_index
                require(checked["unity_host_probe"]["expected_language"] == expected_language
                        and checked["unity_host_probe"]["run_index"] == expected_index, "language_relaunch_mismatch")
                return checked
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
                keyboard = keyboard_observation(observed.get("keyboard"))
                if keyboard:
                    error.native_keyboard = keyboard
                header = header_observation(observed.get("native_header"))
                if header:
                    error.native_header = header
                observed_status = observed.get("server_status")
                gate = server_gate_observation(observed_status)
                if gate: error.native_server_gate = gate
                settings_web = settings_web_from_observation(observed)
                if settings_web: error.native_settings_web = settings_web
                http = http_readiness_observation(observed_status.get("http_readiness")) if type(observed_status) is dict else {}
                if http:
                    error.native_http = http
                copied = diagnostics_copy_from_observation(observed)
                if copied:
                    error.native_diagnostics_copy = copied
                attach_octo_budget_observation(error, observed)
                evidence = language_observation(observed)
                if evidence: error.native_language = evidence
                raise
        except FileNotFoundError:
            pass
        waiting_value = None
        try:
            waiting_value = parse_json(read_bounded(waiting, MAX_JSON))
            last_keyboard.update(keyboard_observation(waiting_value.get("keyboard")))
            last_header.update(header_observation(waiting_value.get("native_header")))
            observed_status = waiting_value.get("server_status")
            if type(observed_status) is dict:
                last_server_gate.clear()
                last_server_gate.update(server_gate_observation(observed_status))
            if type(observed_status) is dict and type(observed_status.get("http_readiness")) is dict:
                last_http.clear()
                last_http.update(http_readiness_observation(observed_status.get("http_readiness")))
            copied = diagnostics_copy_from_observation(waiting_value)
            if copied:
                last_copy.clear()
                last_copy.update(copied)
            budget = octo_budget_from_observation(waiting_value)
            if type(waiting_value.get("octo_budget")) is dict or (type(observed_status) is dict
                    and type(observed_status.get("octo_budget")) is dict):
                last_budget.clear()
                last_budget.update(budget)
            budget_probe = octo_budget_probe_observation(waiting_value.get("octo_budget_probe"))
            if type(waiting_value.get("octo_budget_probe")) is dict:
                last_budget_probe.clear()
                last_budget_probe.update(budget_probe)
            settings_web = settings_web_from_observation(waiting_value)
            menu = waiting_value.get("menu_lifetime")
            if "settings_web" in waiting_value or (type(menu) is dict and "web" in menu):
                last_settings_web.clear()
                last_settings_web.update(settings_web)
            observed_language = language_observation(waiting_value)
            if any(key in waiting_value for key in ("unity_host", "unity_host_probe", "interface_language_cycle", "language_save")) \
                    or (type(observed_status) is dict and "unity_host" in observed_status):
                last_language.clear()
                last_language.update(observed_language)
            failure = waiting_value.get("probe_error")
            if failure is not None:
                require(type(failure) is str and failure in LAUNCHER_FAILURE_CODES,
                        "invalid_launcher_failure_code")
                error = ProbeError(failure)
                error.native_menu = menu_close_observation(waiting_value.get("menu_close"))
                raise error
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
                if type(waiting_value) is dict:
                    keyboard = keyboard_observation(waiting_value.get("keyboard"))
                    if keyboard:
                        error.native_keyboard = keyboard
                    header = header_observation(waiting_value.get("native_header"))
                    if header:
                        error.native_header = header
                    observed_status = waiting_value.get("server_status")
                    gate = server_gate_observation(observed_status)
                    if gate: error.native_server_gate = gate
                    settings_web = settings_web_from_observation(waiting_value)
                    if settings_web: error.native_settings_web = settings_web
                    http = http_readiness_observation(observed_status.get("http_readiness")) if type(observed_status) is dict else {}
                    if http:
                        error.native_http = http
                    copied = diagnostics_copy_from_observation(waiting_value)
                    if copied:
                        error.native_diagnostics_copy = copied
                    attach_octo_budget_observation(error, waiting_value)
                    evidence = language_observation(waiting_value)
                    if evidence: error.native_language = evidence
                raise
        time.sleep(min(0.25, checked_remaining()))


SETTINGS_OVERFLOW_IDS = ('interface_language', 'refresh', 'options-fields', 'presentation-fields', 'accounts-fields', 'accounts-current', 'accounts-summary', 'accounts-user-detail', 'accounts-select', 'accounts-export', 'accounts-clone', 'accounts-new-profile', 'accounts-manager-name', 'accounts-restore-point', 'accounts-feedback', 'accounts-refresh', 'diagnostics', 'message')
SETTINGS_OVERFLOW_TAGS = ('MAIN', 'SECTION', 'HEADER', 'DIV', 'LABEL', 'SPAN', 'BUTTON', 'SELECT', 'INPUT', 'FIELDSET', 'P', 'DETAILS', 'SUMMARY', 'PRE', 'OTHER')


def settings_web_observation(value):
    """Export only bounded DOM readiness scalars, never script/error text."""
    if type(value) is not dict: return {}
    clean = {key:value[key] for key in SETTINGS_WEB_BOOL_FIELDS if type(value.get(key)) is bool}
    for key,maximum in (("viewport_width",16384),("content_width",16384),("elapsed_seconds",600),("navigation_progress",1)):
        number = value.get(key)
        if type(number) in (int,float) and math.isfinite(number) and 0 <= number <= maximum: clean[key] = number
    for key,low,high in (("select_count",0,256),("observations",1,256),("evaluation_error_code",-100,100)):
        number = value.get(key)
        if type(number) is int and low <= number <= high: clean[key] = number
    if type(value.get("overflow_elements")) is list:
        clean["overflow_elements"] = []
        for row in value["overflow_elements"][:8]:
            if type(row) is not dict: continue
            geometry = {key:row.get(key) for key in ("right","width","scroll_width")}
            if not all(type(number) in (int,float) and math.isfinite(number) for number in geometry.values()): continue
            if not (-16384 <= geometry["right"] <= 16384 and 0 < geometry["width"] <= 16384
                    and 0 <= geometry["scroll_width"] <= 16384): continue
            clean["overflow_elements"].append({"tag":row.get("tag") if row.get("tag") in SETTINGS_OVERFLOW_TAGS else "OTHER",
                "id":row.get("id") if row.get("id") in SETTINGS_OVERFLOW_IDS else "", **geometry})
    return clean


def settings_web_from_observation(value):
    if type(value) is not dict: return {}
    raw = value.get("settings_web")
    if type(raw) is not dict and type(value.get("menu_lifetime")) is dict:
        raw = value["menu_lifetime"].get("web")
    return settings_web_observation(raw)


def octo_budget_observation(value):
    """Keep fixed policy labels and bounded scalar state, never raw errors."""
    if type(value) is not dict:
        return {}
    clean = {key:value[key] for key in ("prepared", "configured") if type(value.get(key)) is bool}
    if type(value.get("schema")) is int and value["schema"] == 1:
        clean["schema"] = 1
    if value.get("status") in ("idle", "prepared", "failed", "configured"):
        clean["status"] = value["status"]
    if value.get("scope") == "unified-loopback":
        clean["scope"] = "unified-loopback"
    if "error" in value and value["error"] is None:
        clean["error"] = None
    elif type(value.get("error")) is str and value["error"] in OCTO_BUDGET_ERROR_CODES:
        clean["error"] = value["error"]
    for key in OCTO_BUDGET_SECONDS:
        number = value.get(key)
        if type(number) in (int,float) and math.isfinite(number) and 0 <= number <= 3600:
            clean[key] = number
    return clean


def octo_budget_probe_observation(value):
    if type(value) is not dict:
        return {}
    clean = {key:value[key] for key in OCTO_BUDGET_PROBE_BOOLS if type(value.get(key)) is bool}
    for key in OCTO_BUDGET_PROBE_SECONDS:
        number = value.get(key)
        if type(number) in (int,float) and math.isfinite(number) and 0 <= number <= 3600:
            clean[key] = number
    for key in OCTO_BUDGET_PROBE_COUNTERS:
        count = value.get(key)
        if type(count) is int and 0 <= count <= 16:
            clean[key] = count
    return clean


def octo_budget_from_observation(value):
    if type(value) is not dict:
        return {}
    raw = value.get("octo_budget")
    if type(raw) is not dict and type(value.get("server_status")) is dict:
        raw = value["server_status"].get("octo_budget")
    return octo_budget_observation(raw)


def attach_octo_budget_observation(error, value):
    budget = octo_budget_from_observation(value)
    if budget:
        error.native_octo_budget = budget
    policy_probe = octo_budget_probe_observation(value.get("octo_budget_probe")) if type(value) is dict else {}
    if policy_probe:
        error.native_octo_budget_probe = policy_probe



def account_management_observation(value):
    """Bounded test observations only: never profile keys, nonces, tokens or provider paths."""
    if type(value) is not dict:
        return {}
    if value == {"performed": False, "reason": "first-cold-run-only"} and type(value.get("performed")) is bool:
        return dict(value)
    clean = {key: value[key] for key in ("performed", "seed_fixture_used", "gameplay_tested", "timed_out", "completed",
        *ACCOUNT_NATIVE_FLAGS) if type(value.get(key)) is bool}
    for key, expected in (("scope","stock-simulator"),("ui_trigger","dom-click"),("selection_trigger","delegate-callback")):
        if value.get(key) == expected: clean[key] = expected
    for key in ("archive_bytes","preview_picker_count"):
        if type(value.get(key)) is int and 0 <= value[key] <= 128*1024**2: clean[key] = value[key]
    if _hex_digest(value.get("archive_sha256")): clean["archive_sha256"] = value["archive_sha256"]
    elapsed = value.get("elapsed_seconds")
    if type(elapsed) in (int,float) and math.isfinite(elapsed) and 0 <= elapsed <= 600: clean["elapsed_seconds"] = elapsed
    if type(value.get("ui_flags")) is dict:
        clean["ui_flags"] = {key:value["ui_flags"][key] for key in ACCOUNT_UI_FLAGS if type(value["ui_flags"].get(key)) is bool}
    if type(value.get("ui_actions")) is list:
        clean["ui_actions"] = [item for item in value["ui_actions"][:32] if item in ACCOUNT_UI_ACTIONS]
    if type(value.get("preview_copies")) is list:
        clean["preview_copies"] = [{key:row[key] for key in ("queued","copied_bytes","total_bytes")
            if type(row.get(key)) is (bool if key=="queued" else int)}
            for row in value["preview_copies"][:2] if type(row) is dict]
    for phase in ("source","target"):
        raw=value.get("fixture_"+phase)
        if type(raw) is dict:
            row={key:raw[key] for key in ("schema",) if type(raw.get(key)) is int}
            if type(raw.get("ready")) is bool: row["ready"]=raw["ready"]
            if raw.get("phase")==phase: row["phase"]=phase
            for key in ("request_sha256","bundle_revision","normalized_sha256"):
                if _hex_digest(raw.get(key)): row[key]=raw[key]
            if type(raw.get("table_rows")) is dict:
                row["table_rows"]={key:raw["table_rows"][key] for key in ACCOUNT_TABLES
                    if type(raw["table_rows"].get(key)) is int and 0<=raw["table_rows"][key]<=20000}
            if raw.get("unknown_tables")==list(ACCOUNT_BLOB_TABLES): row["unknown_tables"]=list(ACCOUNT_BLOB_TABLES)
            clean["fixture_"+phase]=row
    raw=value.get("state_observation")
    if type(raw) is dict:
        row={}
        if raw.get("observer")=="runner-sqlite-and-archive": row["observer"]=raw["observer"]
        for key in ("seed_fixture_used","gameplay_tested"):
            if type(raw.get(key)) is bool: row[key]=raw[key]
        if type(raw.get("checks")) is dict:
            row["checks"]={key:raw["checks"][key] for key in ACCOUNT_STATE_FLAGS if type(raw["checks"].get(key)) is bool}
        if type(raw.get("table_rows")) is dict:
            row["table_rows"]={key:raw["table_rows"][key] for key in ACCOUNT_TABLES if type(raw["table_rows"].get(key)) is int}
        for key in ("normalized_source_sha256","normalized_restored_sha256","archive_sha256"):
            if _hex_digest(raw.get(key)): row[key]=raw[key]
        if type(raw.get("archive_bytes")) is int: row["archive_bytes"]=raw["archive_bytes"]
        clean["state_observation"]=row
    code=value.get("error_code")
    if type(code) is str and re.fullmatch(r"account_ui_[a-z_]{1,64}",code): clean["error_code"]=code
    return clean


def validate_account_management(value, run_index):
    fail="settings_account_management_failed"
    require(type(value) is dict,fail)
    if run_index!=0:
        require(value=={"performed":False,"reason":"first-cold-run-only"} and type(value.get("performed")) is bool,fail)
        return dict(value)
    require(value.get("performed") is True and value.get("scope")=="stock-simulator"
        and value.get("ui_trigger")=="dom-click" and value.get("selection_trigger")=="delegate-callback"
        and value.get("seed_fixture_used") is True and value.get("gameplay_tested") is False
        and value.get("timed_out") is False and value.get("completed") is True
        and all(value.get(key) is True for key in ACCOUNT_NATIVE_FLAGS)
        and type(value.get("ui_flags")) is dict and all(value["ui_flags"].get(key) is True for key in ACCOUNT_UI_FLAGS)
        and value.get("ui_actions")==list(ACCOUNT_UI_ACTIONS)
        and type(value.get("preview_picker_count")) is int and value["preview_picker_count"]==2
        and type(value.get("archive_bytes")) is int and 0<value["archive_bytes"]<=128*1024**2
        and _hex_digest(value.get("archive_sha256"))
        and type(value.get("elapsed_seconds")) in (int,float) and math.isfinite(value["elapsed_seconds"])
        and 0<=value["elapsed_seconds"]<=120,fail)
    copies=value.get("preview_copies")
    require(type(copies) is list and len(copies)==2 and all(type(row) is dict and row.get("queued") is True
        and all(type(row.get(key)) is int and row[key]==value["archive_bytes"] for key in ("copied_bytes","total_bytes"))
        for row in copies),fail)
    for phase in ("source","target"):
        fixture=value.get("fixture_"+phase)
        require(type(fixture) is dict and type(fixture.get("schema")) is int and fixture["schema"]==1
            and fixture.get("ready") is True and fixture.get("phase")==phase
            and all(_hex_digest(fixture.get(key)) for key in ("request_sha256","bundle_revision","normalized_sha256"))
            and type(fixture.get("table_rows")) is dict and set(fixture["table_rows"])==set(ACCOUNT_TABLES)
            and all(type(count) is int and 1<=count<=20000 for count in fixture["table_rows"].values())
            and fixture.get("unknown_tables")==list(ACCOUNT_BLOB_TABLES),fail)
    require(value["fixture_source"]["normalized_sha256"]!=value["fixture_target"]["normalized_sha256"]
        and value["fixture_source"]["request_sha256"]!=value["fixture_target"]["request_sha256"],fail)
    observed=value.get("state_observation")
    require(type(observed) is dict and observed.get("observer")=="runner-sqlite-and-archive"
        and observed.get("seed_fixture_used") is True and observed.get("gameplay_tested") is False
        and type(observed.get("checks")) is dict and all(observed["checks"].get(key) is True for key in ACCOUNT_STATE_FLAGS)
        and type(observed.get("table_rows")) is dict and set(observed["table_rows"])==set(ACCOUNT_TABLES)
        and all(type(count) is int for count in observed["table_rows"].values())
        and observed["table_rows"]==value["fixture_target"]["table_rows"]
        and observed.get("normalized_source_sha256")==value["fixture_source"]["normalized_sha256"]
        and observed.get("normalized_restored_sha256")==value["fixture_target"]["normalized_sha256"]
        and observed.get("archive_sha256")==value["archive_sha256"]
        and type(observed.get("archive_bytes")) is int and observed["archive_bytes"]==value["archive_bytes"],fail)
    return account_management_observation(value)



ACCOUNT_PERSIST_FLAGS = ("source_all_tables_persisted", "restored_all_tables_persisted",
    "source_session_preserved", "target_session_invalidated", "original_selection_preserved")


def validate_account_management_after_relaunch(value, first_account_summary):
    """Recheck runner observations against the first complete account proof."""
    fail = "settings_account_management_failed"
    first = first_account_summary
    source = first.get("fixture_source") if type(first) is dict else None
    target = first.get("fixture_target") if type(first) is dict else None
    require(type(first) is dict and first.get("performed") is True and first.get("scope") == "stock-simulator"
        and first.get("seed_fixture_used") is True and first.get("gameplay_tested") is False
        and type(source) is dict and type(target) is dict
        and _hex_digest(source.get("normalized_sha256")) and _hex_digest(target.get("normalized_sha256"))
        and type(value) is dict and type(value.get("schema")) is int and value["schema"] == 1
        and value.get("observer") == "runner-sqlite-after-five-cold-runs"
        and value.get("seed_fixture_used") is True and value.get("gameplay_tested") is False
        and type(value.get("checks")) is dict and set(value["checks"]) == set(ACCOUNT_PERSIST_FLAGS)
        and all(value["checks"].get(key) is True for key in ACCOUNT_PERSIST_FLAGS)
        and value.get("normalized_source_sha256") == source["normalized_sha256"]
        and value.get("normalized_restored_sha256") == target["normalized_sha256"], fail)
    return {"schema": 1, "observer": value["observer"], "seed_fixture_used": True, "gameplay_tested": False,
        "checks": {key: value["checks"][key] for key in ACCOUNT_PERSIST_FLAGS},
        "normalized_source_sha256": value["normalized_source_sha256"],
        "normalized_restored_sha256": value["normalized_restored_sha256"]}


def zip_roundtrip_observation(value):
    if type(value) is not dict:
        return {}
    clean = {key:value[key] for key in (*ZIP_ROUNDTRIP_FLAGS, "performed", "timed_out") if type(value.get(key)) is bool}
    for key, expected in (("scope", "stock-simulator"), ("selection_trigger", "delegate-callback"),
                          ("reason", "first-cold-run-only")):
        if value.get(key) == expected:
            clean[key] = expected
    for key in ZIP_ROUNDTRIP_COUNTS:
        if type(value.get(key)) is int and 0 <= value[key] <= 128*1024*1024:
            clean[key] = value[key]
    for key in ("source_sha256", "copied_sha256"):
        if type(value.get(key)) is str and re.fullmatch(r"[0-9a-f]{64}", value[key]):
            clean[key] = value[key]
    seconds = value.get("elapsed_seconds")
    if type(seconds) in (int,float) and math.isfinite(seconds) and 0 <= seconds <= 600:
        clean["elapsed_seconds"] = seconds
    return clean


def validate_zip_roundtrip(value, run_index):
    require(type(value) is dict, "settings_zip_roundtrip_failed")
    if run_index != 0:
        require(value == {"performed":False,"reason":"first-cold-run-only"}
                and type(value.get("performed")) is bool, "settings_zip_roundtrip_failed")
        return {"performed":False,"reason":"first-cold-run-only"}
    require(value.get("performed") is True and value.get("scope") == "stock-simulator"
            and value.get("selection_trigger") == "delegate-callback" and value.get("timed_out") is False
            and all(value.get(key) is True for key in ZIP_ROUNDTRIP_FLAGS)
            and all(type(value.get(key)) is int and 0 <= value[key] <= 128*1024*1024 for key in ZIP_ROUNDTRIP_COUNTS)
            and value["source_bytes"] > 0 and value["source_bytes"] == value["copied_bytes"] == value["total_bytes"]
            and value["failed_files"] == 0 and value["exported_files"] == value["imported_files"]
            and all(type(value.get(key)) is str and re.fullmatch(r"[0-9a-f]{64}",value[key])
                    for key in ("source_sha256", "copied_sha256"))
            and value["source_sha256"] == value["copied_sha256"]
            and type(value.get("elapsed_seconds")) in (int,float) and math.isfinite(value["elapsed_seconds"])
            and 0 <= value["elapsed_seconds"] <= 120, "settings_zip_roundtrip_failed")
    return zip_roundtrip_observation(value)


def zip_import_observation(value):
    """Keep stock UIKit mode/cancel evidence; never filenames or provider data."""
    if type(value) is not dict:
        return {}
    clean = {key:value[key] for key in (*ZIP_IMPORT_SERVER_FLAGS, "timed_out") if type(value.get(key)) is bool}
    for key, expected in (("scope", "stock-simulator"), ("cancel_trigger", "delegate-callback")):
        if value.get(key) == expected:
            clean[key] = expected
    observations, elapsed = value.get("observations"), value.get("elapsed_seconds")
    if type(observations) is int and 0 <= observations <= 200:
        clean["observations"] = observations
    if type(elapsed) in (int, float) and math.isfinite(elapsed) and 0 <= elapsed <= 600:
        clean["elapsed_seconds"] = elapsed
    if type(value.get("passes")) is list:
        clean["passes"] = []
        for sample in value["passes"][:2]:
            if type(sample) is not dict:
                continue
            observed = {key:sample[key] for key in ZIP_IMPORT_PASS_BOOL_FIELDS if type(sample.get(key)) is bool}
            mode = sample.get("document_picker_mode")
            if type(mode) is int and 0 <= mode <= 3:
                observed["document_picker_mode"] = mode
            clean["passes"].append(observed)
    return clean


def zip_import_from_observation(value):
    if type(value) is not dict:
        return {}
    raw = value.get("zip_import_picker")
    if type(raw) is not dict and type(value.get("menu_lifetime")) is dict:
        raw = value["menu_lifetime"].get("zip_import_picker")
    return zip_import_observation(raw)


def diagnostics_copy_observation(value):
    """Export copy-flow flags and size; never clipboard or diagnostic text."""
    if type(value) is not dict:
        return {}
    clean = {key:value[key] for key in (*DIAGNOSTICS_COPY_BOOL_FIELDS, "timed_out")
             if type(value.get(key)) is bool}
    count = value.get("text_bytes")
    if type(count) is int and 0 <= count <= 32768:
        clean["text_bytes"] = count
    return clean


def diagnostics_copy_from_observation(value):
    if type(value) is not dict:
        return {}
    raw = value.get("diagnostics_copy")
    if type(raw) is not dict and type(value.get("menu_lifetime")) is dict:
        raw = value["menu_lifetime"].get("diagnostics_copy")
    return diagnostics_copy_observation(raw)


def header_observation(value):
    """Project fixed header phases and finite geometry/font scalars only."""
    if type(value) is not dict:
        return {}
    clean = {key:value[key] for key in ("restore_succeeded", "owned_root_only") if type(value.get(key)) is bool}
    for name in HEADER_PHASES:
        sample = value.get(name)
        if type(sample) is not dict:
            continue
        metrics = {key:sample[key] for key in HEADER_BOOL_FIELDS if type(sample.get(key)) is bool}
        count = sample.get("button_count")
        if type(count) is int and 0 <= count <= 16:
            metrics["button_count"] = count
        for key in HEADER_NUMBER_FIELDS:
            number = sample.get(key)
            if type(number) in (int, float) and 0 <= number <= 16384 and math.isfinite(number):
                metrics[key] = number
        if metrics:
            clean[name] = metrics
    return clean


def http_readiness_observation(value):
    """Keep only loopback NSURLSession evidence and fixed, public error labels."""
    if type(value) is not dict:
        return {}
    clean = {}
    if type(value.get("schema")) is int and value["schema"] == 1:
        clean["schema"] = 1
    for key in ("ok", "body_is_json", "worker_main_thread"):
        if type(value.get(key)) is bool:
            clean[key] = value[key]
    for key, maximum in (("http_status",599), ("received_bytes",16384)):
        number = value.get(key)
        if type(number) is int and 0 <= number <= maximum:
            clean[key] = number
    for key, expected in (("transport","NSURLSession"), ("url",HTTP_READINESS_URL),
                          ("error_code","none")):
        if type(value.get(key)) is str and value[key] == expected:
            clean[key] = value[key]
    for key in ("ns_error_domain", "ns_error_code"):
        if key in value and value[key] is None:
            clean[key] = None
    return clean


def keyboard_lifecycle_observation(value):
    """Keep the fixed reuse strategy and bounded initialization counters only."""
    if type(value) is not dict:
        return {}
    clean = {}
    if type(value.get("installed")) is bool:
        clean["installed"] = value["installed"]
    if type(value.get("strategy")) is str and value["strategy"] == "reuse-existing":
        clean["strategy"] = value["strategy"]
    for key in KEYBOARD_LIFECYCLE_COUNTERS:
        item = value.get(key)
        if type(item) is int and 0 <= item <= 16:
            clean[key] = item
    return clean


def keyboard_observation(value):
    """Keep only fixed phases, bounded public getter state and lifecycle info."""
    if type(value) is not dict:
        return {}
    clean = {}
    for name in KEYBOARD_PHASES:
        observation = value.get(name)
        if type(observation) is not dict:
            continue
        scalars = {key: observation[key] for key in KEYBOARD_BOOL_FIELDS
                   if type(observation.get(key)) is bool}
        for key in KEYBOARD_INT_FIELDS:
            item = observation.get(key)
            if type(item) is int and 0 <= item <= (4 if key == "phase" else 16):
                scalars[key] = item
        lifecycle = keyboard_lifecycle_observation(observation.get("lifecycle"))
        if lifecycle:
            scalars["lifecycle"] = lifecycle
        if scalars:
            clean[name] = scalars
    return clean


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


def menu_close_observation(value):
    """Retain public UIKit transition state, never view names or arbitrary text."""
    if type(value) is not dict:
        return {}
    clean = {key: value[key] for key in (
        "presented_controller_remaining", "settings_controller_still_presented", "settings_view_attached",
        "settings_is_being_dismissed", "game_window_key", "timed_out") if type(value.get(key)) is bool}
    for key, maximum in (("application_state", 2), ("observations", 10000)):
        item = value.get(key)
        if type(item) is int and 0 <= item <= maximum:
            clean[key] = item
    seconds = value.get("wait_seconds")
    if type(seconds) in (int, float) and math.isfinite(seconds) and 0 <= seconds <= 600:
        clean["wait_seconds"] = seconds
    return clean


def failure_checkpoint(container, expected_language="ko", run_index=None):
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
        for key in ("launch_requested", "launch_prepared", "launcher_visible", "keyboard_ready"):
            if type(value.get(key)) is bool:
                clean[key] = value[key]
        lifecycle = keyboard_lifecycle_observation(value.get("keyboard_lifecycle"))
        if lifecycle:
            clean["keyboard_lifecycle"] = lifecycle
        http = http_readiness_observation(value.get("http_readiness"))
        if http:
            clean["http_readiness"] = http
        return clean

    final_name, status_name, checkpoint_name = language_paths(expected_language,run_index)
    for source, name in (("checkpoint", checkpoint_name), ("status", status_name), ("report", final_name)):
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
        gate = server_gate_observation(observed.get("server_status") if type(observed.get("server_status")) is dict else observed)
        if gate: result["server_gate"] = gate
        settings_web = settings_web_from_observation(observed)
        if settings_web: result["settings_web"] = settings_web
        language = language_observation(observed)
        if language: result["language_observation"] = language
        menu = menu_close_observation(observed.get("menu_close"))
        if menu:
            result["menu_close"] = menu
        keyboard = keyboard_observation(observed.get("keyboard"))
        if keyboard:
            result.setdefault("keyboard", {}).update(keyboard)
        header = header_observation(observed.get("native_header"))
        if header:
            result.setdefault("native_header", {}).update(header)
        copied = diagnostics_copy_from_observation(observed)
        if copied:
            result["diagnostics_copy"] = copied
        zipped = zip_import_from_observation(observed)
        if zipped:
            result["zip_import_picker"] = zipped
        roundtrip_raw = observed.get("zip_roundtrip")
        if type(roundtrip_raw) is not dict and type(observed.get("menu_lifetime")) is dict:
            roundtrip_raw = observed["menu_lifetime"].get("zip_roundtrip")
        roundtrip = zip_roundtrip_observation(roundtrip_raw)
        if roundtrip:
            result["zip_roundtrip"] = roundtrip
        account_raw=observed.get("account_management")
        if type(account_raw) is not dict and type(observed.get("menu_lifetime")) is dict:
            account_raw=observed["menu_lifetime"].get("account_management")
        account=account_management_observation(account_raw)
        if account: result["account_management"]=account
        prompt_raw=observed.get("official_prompt")
        if type(prompt_raw) is not dict and type(observed.get("menu_lifetime")) is dict:
            prompt_raw=observed["menu_lifetime"].get("official_prompt")
        prompt=official_prompt_observation(prompt_raw)
        if prompt: result["official_prompt"]=prompt
        budget = octo_budget_from_observation(observed)
        if budget:
            result["octo_budget"] = budget
        budget_probe = octo_budget_probe_observation(observed.get("octo_budget_probe"))
        if budget_probe:
            result["octo_budget_probe"] = budget_probe
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
    require(path in (*RPC_PATHS, MASTER_RPC_PATH) and type(port) is int and 0 < port <= 65535,
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


def validate_master_file_report(value):
    """Validate and project only the bounded public master-file transfer proof."""
    require(type(value) is dict and type(value.get("schema")) is int and value["schema"] == 1,
            "master_file_schema_differs")
    for key, path in (("auth_rpc", RPC_PATHS[1]), ("master_rpc", MASTER_RPC_PATH)):
        row = value.get(key)
        require(type(row) is dict and row.get("path") == path
                and type(row.get("grpc_status")) is int and row["grpc_status"] == 0
                and row.get("request_encrypted") is True and row.get("response_encrypted") is True,
                "master_file_rpc_failed")
    size, count = value.get("file_bytes"), value.get("sample_bytes")
    require(value.get("transport") == "http.client" and value.get("origin") == MASTER_ORIGIN
            and value.get("expected_source") == "bundled-master-prefix"
            and type(size) is int and 0 < size <= MAX_MASTER_FILE
            and type(count) is int and count == min(64, size)
            and type(value.get("path_sha256")) is str and re.fullmatch(r"[0-9a-f]{64}", value["path_sha256"]),
            "master_file_metadata_failed")
    require(type(value.get("head_status")) is int and value["head_status"] == 200
            and type(value.get("head_content_length")) is int and value["head_content_length"] == size,
            "master_file_head_failed")
    require(type(value.get("range_status")) is int and value["range_status"] == 206
            and type(value.get("range_content_length")) is int and value["range_content_length"] == count
            and value.get("content_range") == f"bytes 0-{count - 1}/{size}",
            "master_file_range_failed")
    require(all(type(value.get(key)) is str and re.fullmatch(r"[0-9a-f]{64}", value[key])
                for key in ("expected_sample_sha256", "received_sample_sha256"))
            and value["expected_sample_sha256"] == value["received_sample_sha256"]
            and value.get("sample_matches_bundle") is True, "master_file_sample_differs")
    result = {key:value[key] for key in ("schema", "transport", "origin", "expected_source", "path_sha256",
        "file_bytes", "sample_bytes", "head_status", "head_content_length", "range_status",
        "range_content_length", "content_range", "expected_sample_sha256", "received_sample_sha256",
        "sample_matches_bundle")}
    for key in ("auth_rpc", "master_rpc"):
        result[key] = {field:value[key][field] for field in
                       ("path", "grpc_status", "request_encrypted", "response_encrypted")}
    return result


def _master_http(method, path, count, timeout):
    # The published URL is validated separately. Never pass it to a redirecting
    # opener, environment proxy, or arbitrary network authority.
    connection = HTTPConnection("127.0.0.1", 8080, timeout=timeout)
    try:
        headers = {"Connection":"close"}
        if method == "GET": headers["Range"] = f"bytes=0-{count - 1}"
        connection.request(method, path, headers=headers)
        response = connection.getresponse()
        require(response.getheader("Content-Type") == "application/octet-stream",
                "master_file_head_failed" if method == "HEAD" else "master_file_range_failed")
        length = response.getheader("Content-Length")
        require(type(length) is str and bool(re.fullmatch(r"[0-9]{1,10}", length)),
                "master_file_head_failed" if method == "HEAD" else "master_file_range_failed")
        body = response.read(1 if method == "HEAD" else count + 1)
        return response.status, int(length), response.getheader("Content-Range"), body
    except (OSError, HTTPException):
        raise ProbeError("master_head_transport_failed" if method == "HEAD" else "master_range_transport_failed") from None
    finally:
        connection.close()


def probe_master_file(schema, app, *, port=50051, timeout=15):
    """Authenticate, obtain one published master, and read its real file route."""
    require(type(timeout) in (int, float) and 0 < timeout <= 15, "invalid_master_probe_timeout")
    deadline = time.monotonic() + timeout
    def remaining():
        left = deadline - time.monotonic()
        require(left > 0, "master_probe_deadline_exceeded")
        return left
    request = schema.request_type(RPC_PATHS[1])().SerializeToString()
    plain, auth = unary_h2(RPC_PATHS[1], request, port=port, timeout=remaining())
    login = schema.response_type(RPC_PATHS[1]).FromString(plain)
    require(bool(login.gameAuthToken) and bool(login.userPublic.serverUserId)
            and bool(login.userPublic.publicUserId), "fresh_local_login_failed")
    request = schema.request_type(MASTER_RPC_PATH)().SerializeToString()
    plain, master = unary_h2(MASTER_RPC_PATH, request, token=login.gameAuthToken, port=port, timeout=remaining())
    catalog = schema.response_type(MASTER_RPC_PATH).FromString(plain)
    packs = catalog.masterTag.masterTagPacks
    require(0 < len(packs) <= 4096, "master_catalog_invalid")
    pack = packs[0]
    name, size = pack.fileName, pack.fileSize
    require(type(name) is str and bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,255}", name))
            and type(size) is int and 0 < size <= MAX_MASTER_FILE, "master_catalog_invalid")
    path = "/master/" + name
    require(pack.downloadUrl == MASTER_ORIGIN + path, "master_file_url_invalid")
    archive_path = Path(app) / "LocalServer" / "ServerData.zip"
    require(archive_path.is_file() and not archive_path.is_symlink(), "master_bundle_file_invalid")
    try:
        with ZipFile(archive_path) as archive:
            entries = [item for item in archive.infolist()
                       if item.filename == "data/original-master/assets/master/" + name]
            require(len(entries) == 1 and not entries[0].is_dir() and entries[0].file_size == size
                    and not stat.S_ISLNK(entries[0].external_attr >> 16), "master_bundle_file_invalid")
            with archive.open(entries[0]) as incoming:
                expected = incoming.read(min(64, size))
        require(len(expected) == min(64, size), "master_bundle_file_invalid")
    except (OSError, BadZipFile, RuntimeError):
        raise ProbeError("master_bundle_read_failed") from None
    head_status, head_length, _unused, head_body = _master_http("HEAD", path, len(expected), remaining())
    require(head_status == 200 and head_length == size and head_body == b"", "master_file_head_failed")
    status, length, content_range, received = _master_http("GET", path, len(expected), remaining())
    require(status == 206 and length == len(expected) and content_range == f"bytes 0-{len(expected)-1}/{size}"
            and len(received) == len(expected), "master_file_range_failed")
    require(received == expected, "master_file_sample_differs")
    return validate_master_file_report({"schema":1,"transport":"http.client","origin":MASTER_ORIGIN,
        "expected_source":"bundled-master-prefix","path_sha256":hashlib.sha256(path.encode("ascii")).hexdigest(),
        "file_bytes":size,"sample_bytes":len(expected),"head_status":head_status,"head_content_length":head_length,
        "range_status":status,"range_content_length":length,"content_range":content_range,
        "expected_sample_sha256":hashlib.sha256(expected).hexdigest(),
        "received_sample_sha256":hashlib.sha256(received).hexdigest(),"sample_matches_bundle":True,
        "auth_rpc":auth,"master_rpc":master})


def validate_sdk_resource_report(value):
    """Project public SDK wire-identity and one complete translated-file proof."""
    require(type(value) is dict, "sdk_resource_schema_differs")
    fixed = {"schema":1,"transport":"http.client","origin":MASTER_ORIGIN,"application_id":212,
        "application_version":105051,"manifest_path":SDK_MANIFEST_PATH,"manifest_http_status":200,
        "manifest_encrypted":True,"manifest_decrypted":True,"wire_rowset_matches_original":True,
        "all_active_object_names_six_base62":True,"selection":"smallest-translated-image",
        "selected_kind":"assetbundle","object_http_status":200,"object_mime":"application/octet-stream",
        "etag_matches_md5":True}
    require(all(type(value.get(key)) is type(expected) and value[key] == expected
                for key, expected in fixed.items()), "sdk_resource_metadata_failed")
    bounds = {"manifest_ciphertext_bytes":(32,MAX_SDK_BYTES+32),"manifest_plaintext_bytes":(1,MAX_SDK_BYTES),
        "manifest_rows":(2,100000),"active_rows":(1,100000),"translated_image_count":(1,100000),
        "object_bytes":(1,MAX_SDK_BYTES),"received_bytes":(1,MAX_SDK_BYTES),
        "original_revision":(1,2**31-1),"manifest_revision":(1,2**31-1)}
    require(all(type(value.get(key)) is int and low <= value[key] <= high
                for key, (low,high) in bounds.items())
            and (value["manifest_ciphertext_bytes"]-16) % 16 == 0
            and value["active_rows"] <= value["manifest_rows"]
            and value["translated_image_count"] <= value["active_rows"]
            and value["manifest_revision"] > value["original_revision"], "sdk_resource_manifest_failed")
    require(all(type(value.get(key)) is str and re.fullmatch(r"[0-9a-f]{64}",value[key])
                for key in ("original_manifest_sha256","object_path_sha256")), "sdk_resource_metadata_failed")
    require(value["received_bytes"] == value["object_bytes"]
            and all(type(value.get(key)) is str and re.fullmatch(r"[0-9a-f]{32}",value[key])
                    for key in ("expected_md5","received_md5"))
            and value["expected_md5"] == value["received_md5"], "sdk_resource_digest_failed")
    return {key:value[key] for key in (*fixed,*bounds,"original_manifest_sha256","object_path_sha256",
                                      "expected_md5","received_md5")}


def _sdk_source(app):
    from idoly_local.octo_manifest import Database
    with ZipFile(Path(app)/"LocalServer"/"ServerData.zip") as archive:
        result = {}
        for name, maximum in (("settings.json",MAX_JSON),("manifest.pb",MAX_SDK_BYTES)):
            entries = [entry for entry in archive.infolist()
                       if entry.filename == "data/public-octo-ios/"+name]
            require(len(entries) == 1 and not entries[0].is_dir() and 0 < entries[0].file_size <= maximum
                    and not stat.S_ISLNK(entries[0].external_attr >> 16), "sdk_archive_invalid")
            with archive.open(entries[0]) as incoming: raw = incoming.read(maximum+1)
            require(len(raw) == entries[0].file_size, "sdk_archive_invalid")
            result[name] = raw
    settings = parse_json(result["settings.json"])
    require(all(type(settings.get(key)) is int and settings[key] == expected
                for key,expected in (("schema",1),("application_id",212),("application_version",105051)))
            and all(type(settings.get(key)) is str and re.fullmatch(r"[0-9a-f]{64}",settings[key])
                    for key in ("manifest_sha256","aes_key_hex"))
            and type(settings.get("client_key")) is str and 1 <= len(settings["client_key"]) <= 256
            and settings["client_key"].isascii() and all(33 <= ord(c) <= 126 for c in settings["client_key"]),
            "sdk_settings_invalid")
    require(hashlib.sha256(result["manifest.pb"]).hexdigest() == settings["manifest_sha256"],
            "sdk_archive_digest_failed")
    original = Database.FromString(result["manifest.pb"])
    require(type(settings.get("revision")) is int and original.revision == settings["revision"]
            and original.revision > 0 and original.assetBundleList and original.resourceList, "sdk_archive_invalid")
    return settings, original


def probe_sdk_resource(app, *, timeout=30):
    """Check the real SDK-facing catalog and stream one prepared image locally."""
    from idoly_local.octo_manifest import Database, decrypt_manifest
    from idoly_local.octo_runtime import _desktop_aes_backend
    require(type(timeout) in (int,float) and 0 < timeout <= 30, "invalid_sdk_probe_timeout")
    deadline = time.monotonic()+timeout
    def remaining():
        left = deadline-time.monotonic()
        require(left > 0, "sdk_probe_deadline_exceeded")
        return left
    settings, original = _sdk_source(app)
    connection = HTTPConnection("127.0.0.1",8080,timeout=remaining())
    try:
        connection.request("GET",SDK_MANIFEST_PATH,headers={"Connection":"close",
            "Accept":"application/x-protobuf,x-octo-app/212","X-OCTO-KEY":settings["client_key"]})
        response = connection.getresponse()
        length = response.getheader("Content-Length")
        require(response.status == 200 and response.getheader("Content-Type") == "application/x-protobuf"
                and type(length) is str and re.fullmatch(r"[0-9]{1,9}",length)
                and 32 <= int(length) <= MAX_SDK_BYTES+32, "sdk_manifest_http_failed")
        encrypted = response.read(MAX_SDK_BYTES+33)
        require(len(encrypted) == int(length), "sdk_manifest_http_failed")
    except (OSError,HTTPException):
        raise ProbeError("sdk_manifest_transport_failed") from None
    finally: connection.close()
    try:
        plain = decrypt_manifest(encrypted,aes_key=bytes.fromhex(settings["aes_key_hex"]),
                                 aes_cbc=_desktop_aes_backend())
        wire = Database.FromString(plain)
    except Exception:
        raise ProbeError("sdk_manifest_decryption_failed") from None
    require(wire.urlFormat == SDK_URL_FORMAT and wire.revision > original.revision, "sdk_manifest_invalid")
    originals = {(kind,row.id):row for kind,rows in (("assetbundle",original.assetBundleList),
                  ("resources",original.resourceList)) for row in rows}
    rows = [(kind,row) for kind,group in (("assetbundle",wire.assetBundleList),("resources",wire.resourceList))
            for row in group]
    require(2 <= len(rows) <= 100000 and len(originals) == len(rows)
            and {(kind,row.id) for kind,row in rows} == set(originals), "sdk_manifest_rowset_failed")
    active = [(kind,row) for kind,row in rows if row.state != 4]
    require(active and all(row.state in (1,2,3) and re.fullmatch(r"[A-Za-z0-9]{6}",row.objectName)
            and 0 < row.size <= 2**31-1 and 0 < row.uploadVersionId <= 2**31-1
            and 0 < row.generation <= 2**64-1 and re.fullmatch(r"[0-9a-fA-F]{32}",row.md5)
            for kind,row in active), "sdk_wire_identity_failed")
    changed = [row for kind,row in active if kind == "assetbundle"
        and row.md5.lower() != originals[(kind,row.id)].md5.lower()
        and row.generation != originals[(kind,row.id)].generation]
    candidates = [row for row in changed if row.size <= MAX_SDK_BYTES]
    require(candidates, "sdk_translated_image_missing")
    selected = min(candidates,key=lambda row:(row.size,row.id))
    path = f"/octo/{selected.uploadVersionId}/assetbundle/{selected.objectName}/{selected.generation}"
    expected_md5 = selected.md5.lower()
    connection = HTTPConnection("127.0.0.1",8080,timeout=remaining())
    digest, received = hashlib.md5(), 0
    try:
        connection.request("GET",path,headers={"Connection":"close"})
        response = connection.getresponse()
        require(response.status == 200 and response.getheader("Content-Type") == "application/octet-stream"
                and response.getheader("Content-Length") == str(selected.size)
                and response.getheader("ETag") == '"'+expected_md5+'"', "sdk_object_http_failed")
        while True:
            block = response.read(min(64*1024,selected.size-received+1))
            if not block: break
            received += len(block)
            require(received <= selected.size, "sdk_object_size_failed")
            digest.update(block); remaining()
    except (OSError,HTTPException):
        raise ProbeError("sdk_object_transport_failed") from None
    finally: connection.close()
    require(received == selected.size and digest.hexdigest() == expected_md5, "sdk_object_digest_failed")
    return validate_sdk_resource_report({"schema":1,"transport":"http.client","origin":MASTER_ORIGIN,
        "application_id":212,"application_version":105051,"manifest_path":SDK_MANIFEST_PATH,
        "manifest_http_status":200,"manifest_encrypted":True,"manifest_decrypted":True,
        "manifest_ciphertext_bytes":len(encrypted),"manifest_plaintext_bytes":len(plain),
        "original_manifest_sha256":settings["manifest_sha256"],"manifest_rows":len(rows),"active_rows":len(active),
        "wire_rowset_matches_original":True,"all_active_object_names_six_base62":True,
        "translated_image_count":len(changed),"selection":"smallest-translated-image","selected_kind":"assetbundle",
        "object_path_sha256":hashlib.sha256(path.encode("ascii")).hexdigest(),"object_http_status":200,
        "object_mime":"application/octet-stream","object_bytes":selected.size,"received_bytes":received,
        "expected_md5":expected_md5,"received_md5":digest.hexdigest(),"etag_matches_md5":True,
        "original_revision":original.revision,"manifest_revision":wire.revision})


def run_probe(app, audit, *, device_type=None, runtime=None, timeout=900):
    audit = Path(audit)
    require(not audit.exists() and not audit.is_symlink(), "fresh_audit_path_required")
    report = {"schema": 1, "status": "FAIL", "execution": "ios_simulator",
              "gameplay_tested": False, "device_tested": False, "playcover_tested": False,
              "simulator_created": False, "launch_ack_timeout": False,
              "cleanup": {"shutdown": False, "delete": False}}
    created = None
    container = None
    account_harness = None
    ui_driver = None
    current_language = "ko"
    current_run_index = 0
    start = time.monotonic()
    stage = "platform"
    def remaining(cap=60):
        value = timeout - (time.monotonic() - start)
        require(value > 0, "probe_deadline_exceeded")
        return min(cap, value)
    try:
        require(sys.platform == "darwin", "macos_required_no_simulator_execution")
        require(type(timeout) in (int, float) and 5 <= timeout <= 900, "invalid_probe_timeout")
        app = Path(app).resolve(strict=True)
        require(app.is_dir() and app.suffix == ".app", "simulator_app_required")
        info = plistlib.loads(read_bounded(app / "Info.plist", MAX_JSON))
        require(info.get("CFBundleIdentifier") == BUNDLE_ID
                and info.get("CFBundleSupportedPlatforms") == ["iPhoneSimulator"], "fake_unity_probe_app_required")
        report["bundle_id"] = BUNDLE_ID
        stage = "public_schema"
        schema, report["descriptor_sha256"] = load_schema(app)
        stage = "language_canaries"
        canaries, report["language_canaries_sha256"] = load_language_canaries(app,report["descriptor_sha256"])
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
                         "Documents/embedded-probe-checkpoint.json", "Documents/probe-cache-identities.json"):
            path = candidate / relative
            require(not path.exists() and not path.is_symlink(), "preexisting_probe_state_rejected")
        for run_index,language in enumerate(MATRIX_LANGUAGES):
            for name in language_paths(language,run_index):
                path = candidate/"Documents"/name
                require(not path.exists() and not path.is_symlink(), "preexisting_probe_state_rejected")
        container = candidate
        account_harness = AccountFixtureHarness(container, schema, descriptor_sha256=report["descriptor_sha256"])
        report["fresh_local_state_before_launch"] = True
        stage = "official_ui_test_build_and_start"
        try:
            ui_driver = ProbePromptCancelDriver(created,remaining=remaining)
            ui_driver.start()
        except DriverError as error:
            raise ProbeError(error.code if error.code in UI_DRIVER_ERRORS else "official_ui_test_driver_failed") from None
        while not _poll_official_ui_driver(ui_driver)["ready"]:
            remaining()
            time.sleep(min(0.1,remaining()))
        stage = "app_launch"
        try:
            _simctl(["launch", created, BUNDLE_ID, "--idoly-probe-language=ko", "--idoly-probe-run-index=0"], remaining(180))
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
        report["native_probe"] = wait_report(container, remaining, expected_language="ko", run_index=0, account_fixture=account_harness, ui_driver=ui_driver, simulator_udid=created)
        report["official_prompt_ui_test"] = report["native_probe"]["menu_lifetime"]["official_prompt"]["ui_test"]
        summaries = [validate_language_relaunch_report(report["native_probe"],"ko",run_index=0)]
        compare_language_canaries(summaries[0],"ko",canaries,report["language_canaries_sha256"])
        stage = "asset_listener"
        with socket.create_connection(("127.0.0.1", 8080), timeout=min(5, remaining())):
            pass
        report["host_asset_loopback_connected"] = True
        stage = "encrypted_rpc"
        report["rpcs"] = probe_rpcs(schema, timeout=min(15, remaining()))
        stage = "master_file"
        report["master_file"] = probe_master_file(schema, app, timeout=min(15, remaining()))
        stage = "sdk_resource"
        report["sdk_resource"] = probe_sdk_resource(app, timeout=min(30, remaining()))
        for run_index,language in enumerate(MATRIX_LANGUAGES[1:],1):
            stage = "language_terminate_" + language
            _simctl(["terminate",created,BUNDLE_ID],remaining(30))
            for name in language_paths(language,run_index):
                path = container/"Documents"/name
                require(not path.exists() and not path.is_symlink(), "preexisting_language_report_rejected")
            current_language = language
            current_run_index = run_index
            stage = "language_launch_" + language
            try:
                _simctl(["launch",created,BUNDLE_ID,"--idoly-probe-language="+language,
                    "--idoly-probe-run-index="+str(run_index)],remaining(30))
            except ProbeError as error:
                if str(error) != "simctl_timeout": raise
                report.setdefault("language_launch_ack_timeouts",[]).append(language)
            stage = "language_report_" + language
            native = wait_report(container,remaining,expected_language=language,run_index=run_index)
            summary = validate_language_relaunch_report(native,language,run_index=run_index)
            compare_language_canaries(summary,language,canaries,report["language_canaries_sha256"])
            summaries.append(summary)
        stage = "language_matrix"
        report["language_matrix"] = validate_language_matrix_report({"schema":2,"order":list(MATRIX_LANGUAGES),
            "preserved_app_container":True,"reports":summaries})
        report["account_management_after_relaunch"] = validate_account_management_after_relaunch(
            account_harness.verify_persisted(), report["native_probe"]["menu_lifetime"]["account_management"])
        report["status"] = "PASS"
    except BaseException as error:
        report.update(status="FAIL", failed_stage=stage, failed_run_index=current_run_index,
                      error=(str(error) if isinstance(error, ProbeError) else type(error).__name__))
        report["native_checkpoint"] = failure_checkpoint(container,current_language,current_run_index)
        if ui_driver is not None and callable(getattr(ui_driver,"build_failure_log",None)):
            try:
                raw=ui_driver.build_failure_log()
                if type(raw) is bytes and raw:
                    raw=raw[-16384:]
                    diagnostic={"schema":1,"scope":"pre-input-xctest-build","tail_bytes":len(raw),
                        "sha256":hashlib.sha256(raw).hexdigest(),"text":raw.decode("utf-8","replace")}
                    # Keep escaped JSON below the same audit cap even if a
                    # compiler emits control bytes or malformed UTF-8.
                    while len(json.dumps(diagnostic,separators=(",",":"),sort_keys=True).encode())+1>MAX_JSON:
                        raw=raw[-max(1,len(raw)//2):]
                        diagnostic.update(tail_bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),text=raw.decode("utf-8","replace"))
                    diagnostic_path=audit.with_name(audit.stem+"-xctest-build.json")
                    write_audit(diagnostic_path,diagnostic)
                    report["xctest_build_diagnostic"]={key:diagnostic[key] for key in ("scope","tail_bytes","sha256")}
                    report["xctest_build_diagnostic"]["file_name"]=diagnostic_path.name
            except (OSError,ProbeError,DriverError):
                report["xctest_build_diagnostic"]={"available":False}
        if ui_driver is not None and callable(getattr(ui_driver,"build_metadata_diagnostic",None)):
            try:
                observed=ui_driver.build_metadata_diagnostic()
                if observed is not None:
                    diagnostic=official_ui_build_metadata(observed)
                    diagnostic_path=audit.with_name(audit.stem+"-xctest-metadata.json")
                    write_audit(diagnostic_path,diagnostic)
                    encoded=(json.dumps(diagnostic,separators=(",",":"),sort_keys=True)+"\n").encode()
                    report["xctest_build_metadata"]={"scope":diagnostic["scope"],"bytes":len(encoded),
                        "sha256":hashlib.sha256(encoded).hexdigest(),"file_name":diagnostic_path.name}
            except (OSError,ProbeError,DriverError):
                report["xctest_build_metadata"]={"available":False}
        if isinstance(error, ProbeError) and isinstance(getattr(error, "native_detail", None), str):
            report["native_startup_error"] = error.native_detail
        if isinstance(error, ProbeError) and type(getattr(error, "native_crypto", None)) is dict:
            report["native_crypto_observed"] = error.native_crypto
        if isinstance(error, ProbeError) and type(getattr(error, "native_corner", None)) is dict:
            report["native_corner_observed"] = error.native_corner
        if isinstance(error, ProbeError) and type(getattr(error, "native_menu", None)) is dict and error.native_menu:
            report["native_menu_close_observed"] = error.native_menu
        if isinstance(error, ProbeError) and type(getattr(error, "native_keyboard", None)) is dict and error.native_keyboard:
            report["native_keyboard_observed"] = keyboard_observation(error.native_keyboard)
        if isinstance(error, ProbeError) and type(getattr(error, "native_header", None)) is dict and error.native_header:
            report["native_header_observed"] = header_observation(error.native_header)
        if isinstance(error, ProbeError) and type(getattr(error, "native_http", None)) is dict and error.native_http:
            report["native_http_readiness_observed"] = http_readiness_observation(error.native_http)
        if isinstance(error, ProbeError) and type(getattr(error, "native_diagnostics_copy", None)) is dict and error.native_diagnostics_copy:
            report["native_diagnostics_copy_observed"] = diagnostics_copy_observation(error.native_diagnostics_copy)
        if isinstance(error, ProbeError) and type(getattr(error, "native_octo_budget", None)) is dict and error.native_octo_budget:
            report["native_octo_budget_observed"] = octo_budget_observation(error.native_octo_budget)
        if isinstance(error, ProbeError) and type(getattr(error, "native_octo_budget_probe", None)) is dict and error.native_octo_budget_probe:
            report["native_octo_budget_probe_observed"] = octo_budget_probe_observation(error.native_octo_budget_probe)
        gate = server_gate_observation(getattr(error,"native_server_gate",None))
        if not gate:
            gate = server_gate_observation(report["native_checkpoint"].get("server_gate"))
        if gate: report["native_server_gate_observed"] = gate
        settings_web = settings_web_observation(getattr(error,"native_settings_web",None))
        if not settings_web:
            settings_web = settings_web_observation(report["native_checkpoint"].get("settings_web"))
        if settings_web: report["native_settings_web_observed"] = settings_web
        evidence = language_observation(getattr(error,"native_language",None))
        if not evidence:
            evidence = language_observation(report["native_checkpoint"].get("language_observation"))
        if evidence: report["native_language_observed"] = evidence
        if isinstance(error, ProbeError) and type(getattr(error, "tool_detail", None)) is dict:
            report["simctl_failure"] = error.tool_detail
    finally:
        # Capture before deleting the owned container, including when an
        # otherwise passing run subsequently encounters a cleanup failure.
        checkpoint = report.get("native_checkpoint") or failure_checkpoint(container,current_language,current_run_index)
        if ui_driver is not None:
            try:
                ui_driver.close()
                report["ui_test_driver_cleanup"] = True
            except BaseException:
                report["ui_test_driver_cleanup"] = False
                report.update(status="FAIL",cleanup_complete=False)
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
    parser.add_argument("--timeout", type=float, default=900,
                        help="Shared deadline for boot, install and all five cold app processes (5..900 seconds)")
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
