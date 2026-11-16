"""Required observations from the real packaged Mac account-management smoke."""
from copy import deepcopy
import re

TABLES = ("profiles", "snapshots", "profile_settings", "starter_profiles",
          "profile_lesson_progress", "preference_receipts", "main_live_attempts")
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
