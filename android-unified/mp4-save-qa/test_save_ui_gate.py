"""The actual-device result gate cannot turn build-only or incomplete UI evidence into a pass."""
import copy

import pytest

from tools import build_android_mp4_save_qa as qa


BUILT = {"source_commit": "d" * 40, "apk_sha256": "e" * 64,
         "source_snapshot_sha256": "a" * 64, "production_controller_sha256": "b" * 64}
CHALLENGE = "c" * 64
UID = 10123


def proof():
    initial = {"schema": 1, "package": qa.PACKAGE, "challenge": CHALLENGE,
               "scope": "synthetic_mp4_save_ui_only", "phase": "observing", "java_uid": UID, "java_pid": 111,
               "android_api": 35, "launch_mode": "fresh", "launches": 0, "results": 0, "cancelled": 0,
               "boots": 1, "creations": 1, "completed_outputs": 0, "can_save": False,
               "picker_or_copy_active": False, "source_exists": False, "source_bytes": 0, "source_sha256": None,
               "fixture_asset_sha256": qa.FIXTURE_SHA, "native_phase": "rendering", "document_launches": [], "configured_output_changed": False,
               "native": {"uid": UID, "euid": UID, "pid": 111, "selinux_context": "u:r:untrusted_app:s0:c1,c256,c512,c768",
                          "synthetic_native_fixture": True, "source_snapshot_sha256": BUILT["source_snapshot_sha256"],
                          "production_controller_sha256": BUILT["production_controller_sha256"]}}
    complete = copy.deepcopy(initial)
    complete.update(completed_outputs=1, can_save=True, source_exists=True, source_bytes=1559,
                    source_sha256=qa.FIXTURE_SHA, native_phase="completed")
    cancel1 = copy.deepcopy(complete); cancel1.update(launches=1, results=1, cancelled=1)
    recreated = copy.deepcopy(cancel1); recreated.update(creations=2, native_phase="idle")
    pending = copy.deepcopy(recreated); pending.update(creations=3, launches=2, picker_or_copy_active=True, can_save=False,
        pending_saved=1, pending_saved_launches=2, pending_recreated=1, pending_restored_active=True, pending_restored_launches=2)
    cancel2 = copy.deepcopy(pending); cancel2.update(results=2, cancelled=2, picker_or_copy_active=False, can_save=True)
    cold = copy.deepcopy(cancel2); cold.update(boots=2, creations=4, java_pid=222, launch_mode="cold", configured_output_changed=True); cold["native"]["pid"] = 222
    cancel3 = copy.deepcopy(cold); cancel3.update(launches=3, results=3, cancelled=3)
    terminal = copy.deepcopy(cancel3); terminal["phase"] = "completed"
    terminal["document_launches"] = [{"request": 50057, "action": "android.intent.action.CREATE_DOCUMENT", "mime": "video/mp4",
                                      "component": "com.google.android.documentsui/com.android.documentsui.files.FilesActivity"} for _ in range(3)]
    terminal["document_events"] = [{"request_code": 50057, "action": "android.intent.action.CREATE_DOCUMENT", "mime": "video/mp4", "origin": "mp4_save",
                                    "event": "launch" if index % 2 == 0 else "result",
                                    "result": "requested" if index % 2 == 0 else "cancelled"} for index in range(6)]
    return {"status": "PASS_ANDROID_SYNTHETIC_SAVE_UI_ONLY", "source_commit": BUILT["source_commit"],
            "apk_sha256": BUILT["apk_sha256"], "actual_android_save_ui_verified": True,
            "actual_game_mv_verified": False, "actual_codec_verified": False, "challenge": CHALLENGE, "package_uid": UID,
            "selinux_enforcement": {"source": "adb_shell_getenforce", "before": "Enforcing", "after": "Enforcing"},
            "observations": dict(initial=initial, completed=complete, cancel1=cancel1, recreated=recreated, pending_recreated=pending, cancel2=cancel2, cold=cold, cancel3=cancel3, terminal=terminal),
            "documents_ui_visits": 3, "ui_taps_from_fresh_bounds": True,
            "cases": [{"name": name, "required": True, "status": "passed"} for name in sorted(qa.REQUIRED)]}


def test_accept_only_complete_exact_source_android_ui_proof():
    value = proof()
    assert qa.validate_runtime_report(value, BUILT) == value


@pytest.mark.parametrize("field,value", [
    ("status", "BUILT_NOT_RUNTIME_VALIDATED"), ("actual_android_save_ui_verified", False),
    ("source_commit", "0" * 40), ("apk_sha256", "0" * 64), ("actual_game_mv_verified", True),
    ("actual_codec_verified", True), ("documents_ui_visits", 0), ("ui_taps_from_fresh_bounds", False),
    ("package_uid", 2000), ("challenge", "f" * 64),
])
def test_reject_failed_build_only_stale_or_overclaimed_result(field, value):
    evidence = proof(); evidence[field] = value
    with pytest.raises(ValueError): qa.validate_runtime_report(evidence, BUILT)


@pytest.mark.parametrize("phase", ["initial", "completed", "cancel1", "recreated", "pending_recreated", "cancel2", "cold", "cancel3", "terminal"])
@pytest.mark.parametrize("field,value", [("java_uid", 0), ("java_pid", 0), ("fixture_asset_sha256", "0" * 64)])
def test_every_phase_needs_ordinary_app_and_source_identity(phase, field, value):
    evidence = proof(); evidence["observations"][phase][field] = value
    with pytest.raises(ValueError): qa.validate_runtime_report(evidence, BUILT)


@pytest.mark.parametrize("field,value", [
    ("selinux_context", "u:r:shell:s0"), ("uid", 2000), ("euid", 0),
    ("synthetic_native_fixture", False), ("production_controller_sha256", "0" * 64),
    ("source_snapshot_sha256", "0" * 64),
])
def test_native_receipt_cannot_be_replaced_by_shell_or_other_sources(field, value):
    evidence = proof(); evidence["observations"]["terminal"]["native"][field] = value
    with pytest.raises(ValueError): qa.validate_runtime_report(evidence, BUILT)


@pytest.mark.parametrize("phase,field,value", [
    ("completed", "launches", 1), ("completed", "source_exists", False), ("completed", "can_save", False),
    ("cancel1", "picker_or_copy_active", True), ("cancel1", "cancelled", 0),
    ("recreated", "source_sha256", "0" * 64), ("recreated", "creations", 1),
    ("cold", "java_pid", 111), ("cold", "native_phase", "completed"), ("cold", "boots", 1),
    ("cold", "launch_mode", "fresh"), ("cold", "launches", 3), ("cold", "completed_outputs", 0),
    ("cold", "configured_output_changed", False),
    ("cancel3", "source_bytes", 0), ("cancel3", "results", 2), ("terminal", "phase", "observing"),
])
def test_no_automatic_picker_and_real_recreation_recovery_are_required(phase, field, value):
    evidence = proof(); evidence["observations"][phase][field] = value
    if phase == "cold" and field == "java_pid": evidence["observations"][phase]["native"]["pid"] = value
    with pytest.raises(ValueError): qa.validate_runtime_report(evidence, BUILT)


@pytest.mark.parametrize("field,value", [("before", "Permissive"), ("after", "Permissive"), ("before", None), ("after", None)])
def test_enforcing_attestation_must_bracket_the_actual_ui_run(field, value):
    evidence = proof(); evidence["selinux_enforcement"][field] = value
    with pytest.raises(ValueError): qa.validate_runtime_report(evidence, BUILT)


@pytest.mark.parametrize("field,value", [("pending_saved", 0), ("pending_saved_launches", 1),
    ("pending_recreated", 0), ("pending_restored_active", False), ("pending_restored_launches", 1),
    ("picker_or_copy_active", False), ("creations", 2), ("source_exists", False)])
def test_actual_pending_picker_bundle_recreation_is_mandatory(field, value):
    evidence = proof(); evidence["observations"]["pending_recreated"][field] = value
    with pytest.raises(ValueError): qa.validate_runtime_report(evidence, BUILT)


@pytest.mark.parametrize("mutation", ["missing_observation", "missing_case", "duplicate_case", "unsupported_case", "wrong_component", "wrong_mime", "wrong_history"])
def test_actual_required_ui_steps_and_production_document_history_cannot_be_skipped(mutation):
    evidence = proof(); terminal = evidence["observations"]["terminal"]
    if mutation == "missing_observation": del evidence["observations"]["cold"]
    elif mutation == "missing_case": evidence["cases"].pop()
    elif mutation == "duplicate_case": evidence["cases"][-1] = evidence["cases"][0]
    elif mutation == "unsupported_case": evidence["cases"][0]["status"] = "unsupported"
    elif mutation == "wrong_component": terminal["document_launches"][0]["component"] = "other.app/.Picker"
    elif mutation == "wrong_mime": terminal["document_launches"][0]["mime"] = "application/zip"
    else: terminal["document_events"][0]["origin"] = "diagnostics_export"
    with pytest.raises(ValueError): qa.validate_runtime_report(evidence, BUILT)
