"""Required observations from the real packaged Mac account-management smoke."""
from copy import deepcopy
import re

TABLES = ("profiles", "snapshots", "profile_settings", "starter_profiles",
          "profile_lesson_progress", "preference_receipts", "main_live_attempts", "profile_love_progress")
CHECKS = ("normal_account_created", "media_account_created", "mode_isolation",
    "clone_all_tables_preserved", "archive_full_sha256_verified",
    "new_import_all_tables_preserved", "new_import_has_no_sessions",
    "queued_selection_applied_after_restart", "selected_account_encrypted_rpc",
    "stale_replace_rejected", "replacement_restore_point_created",
    "replacement_target_sessions_invalidated", "restore_exact_snapshot_and_unknown_fields",
    "original_account_all_tables_preserved", "original_sessions_preserved",
    "selected_original_restored")


def validate(smoke):
    if type(smoke) is not dict or smoke.get("account_management_roundtrip") is not True:
        raise ValueError("account_management_smoke_not_passed")
    detail = smoke.get("account_management")
    if (type(detail) is not dict or set(detail) != {
            "schema", "snapshot_tables", "archive_bytes", "archive_sha256", "checks", "gameplay_tested"}
            or type(detail.get("schema")) is not int or detail["schema"] != 1
            or detail.get("snapshot_tables") != list(TABLES)
            or type(detail.get("archive_bytes")) is not int
            or not 0 < detail["archive_bytes"] <= 128*1024*1024
            or type(detail.get("archive_sha256")) is not str
            or re.fullmatch(r"[0-9a-f]{64}", detail["archive_sha256"]) is None
            or detail.get("gameplay_tested") is not False
            or type(detail.get("checks")) is not dict
            or set(detail["checks"]) != set(CHECKS)
            or any(detail["checks"][key] is not True for key in CHECKS)):
        raise ValueError("account_management_smoke_contract_differs")
    return deepcopy(detail)

ANDROID_CHECKS = ("account_native_create","account_native_clone","account_queued_selection_persisted","account_selected_encrypted_rpc","account_document_export_import","account_zip_whole_state_preserved","account_original_whole_state_preserved","account_import_sessions_excluded","account_selection_restored",)
ANDROID_SCOPE = "Android emulator native UI and real document provider"


def validate_android(report):
    if type(report) is not dict or any(report.get(key) is not True for key in ANDROID_CHECKS):
        raise ValueError("android_account_management_not_passed")
    detail = report.get("account_management")
    if (type(detail) is not dict or set(detail) != {"scope", "archive_filename_observed",
            "owned_tables", "imported_sessions", "physical_device_tested"}
            or detail.get("scope") != ANDROID_SCOPE
            or type(detail.get("archive_filename_observed")) is not str
            or re.fullmatch(r"IdolyPride-Account-[0-9a-f]{32}\.zip", detail["archive_filename_observed"]) is None
            or detail.get("owned_tables") != list(TABLES)
            or type(detail.get("imported_sessions")) is not int or detail["imported_sessions"] != 0
            or detail.get("physical_device_tested") is not False):
        raise ValueError("android_account_management_scope_differs")
    return deepcopy(detail)
