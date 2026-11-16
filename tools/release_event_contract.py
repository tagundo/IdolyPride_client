"""Strict observations from the actual native Android local-event settings flow."""
from copy import deepcopy
import re

CHECKS = ("native_event_settings_autosave", "native_event_settings_restart_preserved")
SCOPE = "Android emulator native event settings and encrypted Home RPC"
EVENT_IDS = ("love-23-0514", "love-23-1114", "love-24-0517", "love-24-1114", "love-26-0313", "love-extra-25-0426")
TRUE_FIELDS = ("saved_file_verified", "effective_match", "home_event_verified", "progress_preserved", "selection_restored")
FIELDS = {"scope", "event_id", "settings_revision", "start_time_ms", "end_time_ms", "ruleset_sha256",
          *TRUE_FIELDS, "physical_device_tested", "gameplay_tested"}
MAX_SAFE = 2**53-1


def validate_android(report):
    if type(report) is not dict or any(report.get(name) is not True for name in CHECKS):
        raise ValueError("android_native_event_settings_not_passed")
    detail = report.get("native_event_settings")
    if (type(detail) is not dict or set(detail) != FIELDS or detail.get("scope") != SCOPE
            or detail.get("event_id") not in EVENT_IDS
            or type(detail.get("settings_revision")) is not int or not 1 <= detail["settings_revision"] <= MAX_SAFE
            or type(detail.get("start_time_ms")) is not int or type(detail.get("end_time_ms")) is not int
            or not 0 <= detail["start_time_ms"] < detail["end_time_ms"] <= MAX_SAFE
            or detail["end_time_ms"]-detail["start_time_ms"] != 30*24*60*60*1000
            or type(detail.get("ruleset_sha256")) is not str or re.fullmatch(r"[0-9a-f]{64}", detail["ruleset_sha256"]) is None
            or any(detail.get(name) is not True for name in TRUE_FIELDS)
            or detail.get("physical_device_tested") is not False or detail.get("gameplay_tested") is not False):
        raise ValueError("android_native_event_settings_scope_differs")
    return deepcopy(detail)
