"""Android official-import native boundary with a synthetic, network-free backend.

These tests execute the production Python boundary against a recording manager.
No real official account, credentials, API call, or server listener is used.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "android-server/app/src/main/python/android_server_runtime.py"
SYNTHETIC_USER = "1000000000000"
SYNTHETIC_PASSWORD = "fakecanarypass"
JOB = "a" * 32
REVISION = "b" * 64
PRIVATE_NAME = "Synthetic private manager"


@pytest.fixture
def official_native(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("android_official_boundary", BRIDGE)
    boundary = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(boundary)
    files = tmp_path / "files"
    (files / "data").mkdir(parents=True)
    calls, managers = [], []

    class Manager:
        def __init__(self, root):
            self.root = root
            self.result_override = None
            self.failure = None
            self.public_override = None
            self.received_ref = None
            self.phase = "verified"
            managers.append(self)
        def command(self, action, payload):
            self.received_ref = payload
            calls.append(("command", self.root, action, dict(payload)))
            if self.failure is not None:
                raise self.failure
            if self.result_override is not None:
                return self.result_override
            if action == "official_cancel":
                self.phase = "cancelled"
            if action == "official_status":
                return {"action": action, "job": self.status(public=False)}
            result = {"action": action, "job": self.status(public=False)}
            if action == "official_apply":
                result.update(account={"mode": "normal", "profile": payload["profile"]},
                              status={"accounts": [], "selected": {"normal": "original", "media": "viewing"}})
            return result
        def status(self, *, public=False):
            calls.append(("status", public))
            if self.failure is not None:
                raise self.failure
            if public and self.public_override is not None:
                return self.public_override
            job = {"schema": 1, "job_id": JOB, "state": self.phase, "progress": self.phase,
                   "error_code": None, "counts": {"cards": 3, "items": 4, "photos": 5},
                   "busy": self.phase in ("checking", "fetching"), "expires_in_seconds": 300}
            if not public:
                job["preview"] = {"manager_name": PRIVATE_NAME, "manager_level": 2,
                                  "public_id": SYNTHETIC_USER,
                                  "inventory": {"cards": 3, "items": 4, "photos": 5}}
            return job

    monkeypatch.setitem(sys.modules, "idoly_local.official_import", SimpleNamespace(
        OfficialImportManager=Manager, OfficialImportError=ValueError, OfficialError=ValueError,
        ERROR_CODES=frozenset({"official_bad_credentials"}),
        STAGES=frozenset({"idle", "checking", "verified", "fetching", "ready", "completed", "cancelled"})))
    monkeypatch.setattr(boundary, "_configure_official_codec", lambda: None)
    monkeypatch.setattr(boundary, "start", lambda *a, **k: pytest.fail("Official commands must not auto-start the game"))
    monkeypatch.setattr(boundary, "stop", lambda *a, **k: pytest.fail("Official commands must not silently stop an active game"))
    def invoke(action, payload=None):
        return json.loads(boundary.official_command_json(str(files), action, json.dumps(payload or {})))
    return boundary, files, calls, managers, invoke


class Active:
    def __init__(self, *, mode="normal", profile="active", running=True):
        self.mode, self.profile, self.running = mode, profile, running
    def status(self):
        return {"running": self.running, "profile": self.profile, "media_mode": self.mode == "media"}
    def diagnostics_snapshot(self):
        return {"runtime": self.status(), "logs": ["synthetic retained event"]}


def test_inspect_forwards_synthetic_credentials_once_without_retaining_in_generic_observations(official_native):
    boundary, files, calls, managers, invoke = official_native
    request = {"user_id": SYNTHETIC_USER, "password": SYNTHETIC_PASSWORD, "platform": "ios"}
    result = invoke("official_inspect", request)
    assert result["ok"] is True and result["schema"] == 1 and result["action"] == "official_inspect"
    assert len(managers) == 1
    assert calls[0] == ("command", files/"data", "official_inspect", request)
    assert "user_id" not in managers[0].received_ref and "password" not in managers[0].received_ref
    generic = (boundary.status_json(), boundary.diagnostics_json())
    assert calls[-2:] == [("status", True), ("status", True)]
    for value in (*generic, json.dumps(boundary._LAST_STATUS), json.dumps(boundary._LAST_DIAGNOSTICS)):
        assert SYNTHETIC_USER not in value and SYNTHETIC_PASSWORD not in value and PRIVATE_NAME not in value
    assert all(not isinstance(value, str) or SYNTHETIC_PASSWORD not in value
               for key, value in vars(boundary).items() if not key.startswith("__"))
    assert list((files/"data").iterdir()) == []


def test_explicit_status_keeps_preview_separate_from_public_poll_and_reuses_same_job_manager(official_native):
    boundary, files, calls, managers, invoke = official_native
    invoke("official_inspect", {"user_id": SYNTHETIC_USER, "password": SYNTHETIC_PASSWORD, "platform": "android"})
    result = invoke("official_status")
    assert result["job"]["preview"]["manager_name"] == PRIVATE_NAME
    assert result["job"]["preview"]["public_id"] == SYNTHETIC_USER
    assert len(managers) == 1
    assert json.loads(boundary.status_json())["official_import"]["state"] == "verified"
    assert PRIVATE_NAME not in boundary.diagnostics_json()
    assert calls[-2:] == [("status", True), ("status", True)]


@pytest.mark.parametrize("mode,profile", [("normal", "target"), ("normal", "other"), ("media", "target")])
def test_any_running_server_blocks_official_replace_before_backend_mutation(official_native, mode, profile):
    boundary, files, calls, managers, invoke = official_native
    invoke("official_inspect", {"user_id": SYNTHETIC_USER, "password": SYNTHETIC_PASSWORD, "platform": "ios"})
    calls.clear()
    boundary._RUNTIME = Active(mode=mode, profile=profile)
    result = invoke("official_apply", {"job_id": JOB, "profile": "target", "replace": True,
                                       "expected_revision": REVISION})
    assert result == {"schema": 1, "ok": False, "error": "official_active_restart_required"}
    assert not any(call[0] == "command" for call in calls)
    assert boundary._RUNTIME.profile == profile and boundary._RUNTIME.running


def test_new_slot_apply_is_allowed_while_an_unrelated_game_runs_and_does_not_select_or_change_mode(official_native):
    boundary, files, calls, managers, invoke = official_native
    invoke("official_inspect", {"user_id": SYNTHETIC_USER, "password": SYNTHETIC_PASSWORD, "platform": "ios"})
    calls.clear()
    active = Active(mode="media", profile="viewing")
    boundary._RUNTIME = active
    request = {"job_id": JOB, "profile": "new-normal", "replace": False, "expected_revision": None}
    result = invoke("official_apply", request)
    assert result["ok"] is True
    assert result["account"] == {"mode": "normal", "profile": "new-normal"}
    assert result["status"]["selected"] == {"normal": "original", "media": "viewing"}
    assert result["active"] == {"running": True, "mode": "media", "profile": "viewing"}
    assert boundary._RUNTIME is active and active.mode == "media" and active.profile == "viewing"
    commands = [call for call in calls if call[0] == "command"]
    assert commands == [("command", files/"data", "official_apply", request)]
    assert list((files/"data").iterdir()) == []


def test_stopped_replace_preserves_cas_and_cancellation_uses_only_opaque_job_id(official_native):
    boundary, files, calls, managers, invoke = official_native
    invoke("official_inspect", {"user_id": SYNTHETIC_USER, "password": SYNTHETIC_PASSWORD, "platform": "ios"})
    calls.clear()
    boundary._RUNTIME = Active(running=False)
    request = {"job_id": JOB, "profile": "target", "replace": True, "expected_revision": REVISION}
    assert invoke("official_apply", request)["ok"] is True
    assert invoke("official_cancel", {"job_id": JOB})["job"]["state"] == "cancelled"
    commands = [call for call in calls if call[0] == "command"]
    assert commands == [("command", files/"data", "official_apply", request),
                        ("command", files/"data", "official_cancel", {"job_id": JOB})]
    assert len(managers) == 1


@pytest.mark.parametrize("action,encoded", [
    ("official_delete", "{}"), ("official_status", "[]"), ("official_status", "not json"),
    ("official_status", '"' + "x"*8193 + '"'), (None, "{}"),
])
def test_invalid_or_oversized_native_requests_never_reach_the_official_backend(official_native, action, encoded):
    boundary, files, calls, managers, invoke = official_native
    result = json.loads(boundary.official_command_json(str(files), action, encoded))
    assert result == {"schema": 1, "ok": False, "error": "official_request_invalid"}
    assert calls == [] and managers == []


@pytest.mark.parametrize("error", [ValueError("private/path password="+SYNTHETIC_PASSWORD),
                                   ValueError(SYNTHETIC_PASSWORD),
                                   RuntimeError("private/path password="+SYNTHETIC_PASSWORD)])
def test_backend_exception_details_cannot_echo_credentials_paths_or_raw_messages(official_native, error):
    boundary, files, calls, managers, invoke = official_native
    invoke("official_inspect", {"user_id": SYNTHETIC_USER, "password": SYNTHETIC_PASSWORD, "platform": "ios"})
    managers[0].failure = error
    result = invoke("official_fetch", {"job_id": JOB})
    assert result == {"schema": 1, "ok": False, "error": "official_operation_failed"}
    assert SYNTHETIC_PASSWORD not in boundary.status_json()
    assert SYNTHETIC_PASSWORD not in boundary.diagnostics_json()
    assert json.loads(boundary.status_json())["official_import"] == {"schema": 1, "state": "unavailable", "error_code": "official_status_failed", "busy": False}


@pytest.mark.parametrize("bad", [[], "bad", {"job": "bad"}, {"action": "official_status", "job": {"state": "ready", "oversize": "x"*(2*1024*1024)}}])
def test_invalid_backend_response_is_bounded_and_not_exposed_as_a_success(official_native, bad):
    boundary, files, calls, managers, invoke = official_native
    invoke("official_inspect", {"user_id": SYNTHETIC_USER, "password": SYNTHETIC_PASSWORD, "platform": "ios"})
    managers[0].result_override = bad
    result = invoke("official_status")
    assert result == {"schema": 1, "ok": False, "error": "official_response_invalid"}


def test_idle_public_status_does_not_create_an_official_job_or_credentials_prompt(official_native):
    boundary, files, calls, managers, invoke = official_native
    expected = {"schema": 1, "state": "idle", "job_id": None, "progress": "idle", "error_code": None,
                "counts": {"cards": 0, "items": 0, "photos": 0}, "busy": False, "expires_in_seconds": 0}
    assert json.loads(boundary.status_json())["official_import"] == expected
    assert json.loads(boundary.diagnostics_json())["official_import"] == expected
    assert calls == [] and managers == []


@pytest.mark.parametrize("action", ["official_fetch", "official_apply", "official_cancel"])
def test_missing_job_cannot_start_a_transfer_or_create_a_manager(official_native, action):
    boundary, files, calls, managers, invoke = official_native
    payload = {"job_id": JOB}
    if action == "official_apply":
        payload.update(profile="target", replace=False, expected_revision=None)
    assert invoke(action, payload) == {"schema": 1, "ok": False, "error": "official_job_missing"}
    assert calls == [] and managers == []


def test_public_poll_failure_never_replaces_the_game_runtime_or_retained_observations(official_native):
    boundary, files, calls, managers, invoke = official_native
    invoke("official_inspect", {"user_id": SYNTHETIC_USER, "password": SYNTHETIC_PASSWORD, "platform": "ios"})
    active = Active(mode="media", profile="viewing")
    boundary._RUNTIME = active
    old_status, old_diagnostics = dict(boundary._LAST_STATUS), dict(boundary._LAST_DIAGNOSTICS)
    managers[0].failure = ValueError(SYNTHETIC_PASSWORD)
    status, diagnostics = json.loads(boundary.status_json()), json.loads(boundary.diagnostics_json())
    assert status["running"] is True and status["profile"] == "viewing"
    assert diagnostics["runtime"]["profile"] == "viewing"
    assert status["official_import"] == {"schema": 1, "state": "unavailable", "error_code": "official_status_failed", "busy": False}
    assert boundary._RUNTIME is active and boundary._LAST_STATUS == old_status and boundary._LAST_DIAGNOSTICS == old_diagnostics


def test_explicit_inspect_configures_codec_before_authentication_backend_is_called(official_native, monkeypatch):
    boundary, files, calls, managers, invoke = official_native
    monkeypatch.setattr(boundary, "_configure_official_codec", lambda: calls.append(("codec",)))
    invoke("official_inspect", {"user_id": SYNTHETIC_USER, "password": SYNTHETIC_PASSWORD, "platform": "android"})
    first_command = next(index for index, call in enumerate(calls) if call[0] == "command")
    assert ("codec",) in calls[:first_command]


def test_status_and_cancel_do_not_require_crypto_or_real_java_bridge(official_native, monkeypatch):
    boundary, files, calls, managers, invoke = official_native
    invoke("official_inspect", {"user_id": SYNTHETIC_USER, "password": SYNTHETIC_PASSWORD, "platform": "android"})
    monkeypatch.setattr(boundary, "_configure_official_codec", lambda: pytest.fail("Status/cancel require no AES setup"))
    assert invoke("official_status")["ok"] is True
    assert invoke("official_cancel", {"job_id": JOB})["job"]["state"] == "cancelled"


def test_public_job_projection_rejects_secret_like_codes_progress_and_unknown_fields(official_native):
    boundary, files, calls, managers, invoke = official_native
    invoke("official_inspect", {"user_id": SYNTHETIC_USER, "password": SYNTHETIC_PASSWORD, "platform": "ios"})
    managers[0].public_override = {"state": "verified", "job_id": JOB,
        "password": SYNTHETIC_PASSWORD, "user_id": SYNTHETIC_USER,
        "preview": {"manager_name": PRIVATE_NAME}, "progress": SYNTHETIC_PASSWORD,
        "error_code": SYNTHETIC_PASSWORD, "counts": {"cards": True, "items": -1, "photos": 8},
        "busy": True, "expires_in_seconds": 601}
    public = json.loads(boundary.status_json())["official_import"]
    assert set(public) == {"schema", "state", "job_id", "progress", "error_code", "counts", "busy", "expires_in_seconds"}
    assert public["progress"] == "idle" and public["error_code"] == "official_operation_failed"
    assert public["counts"] == {"cards": 0, "items": 0, "photos": 8} and public["expires_in_seconds"] == 0
    assert all(secret not in json.dumps(public) for secret in (SYNTHETIC_PASSWORD, SYNTHETIC_USER, PRIVATE_NAME))


def test_only_a_fixed_exported_backend_error_code_survives_error_mapping(official_native):
    boundary, files, calls, managers, invoke = official_native
    invoke("official_inspect", {"user_id": SYNTHETIC_USER, "password": SYNTHETIC_PASSWORD, "platform": "ios"})
    managers[0].failure = ValueError("official_bad_credentials")
    assert invoke("official_fetch", {"job_id": JOB}) == {"schema": 1, "ok": False, "error": "official_bad_credentials"}


def test_job_manager_cannot_cross_into_another_storage_root(official_native, tmp_path):
    boundary, files, calls, managers, invoke = official_native
    invoke("official_inspect", {"user_id": SYNTHETIC_USER, "password": SYNTHETIC_PASSWORD, "platform": "ios"})
    calls.clear()
    other = tmp_path / "other-files"
    (other/"data").mkdir(parents=True)
    result = json.loads(boundary.official_command_json(str(other), "official_status", "{}"))
    assert result == {"schema": 1, "ok": False, "error": "official_storage_changed"}
    assert calls == [] and len(managers) == 1


@pytest.mark.parametrize("action,payload", [
    ("official_status", {"password": SYNTHETIC_PASSWORD}),
    ("official_inspect", {"user_id": "bad id", "password": SYNTHETIC_PASSWORD, "platform": "android"}),
    ("official_inspect", {"user_id": SYNTHETIC_USER, "password": " space", "platform": "android"}),
    ("official_inspect", {"user_id": SYNTHETIC_USER, "password": "space ", "platform": "ios"}),
    ("official_inspect", {"user_id": SYNTHETIC_USER, "password": SYNTHETIC_PASSWORD, "platform": "Android"}),
    ("official_fetch", {"job_id": "not-a-job"}),
    ("official_apply", {"job_id": JOB, "profile": "normal", "replace": 1, "expected_revision": REVISION}),
    ("official_apply", {"job_id": JOB, "profile": "normal", "replace": True, "expected_revision": None}),
    ("official_apply", {"job_id": JOB, "profile": "wrong/path", "replace": False, "expected_revision": None}),
])
def test_native_payload_schema_and_credential_bounds_reject_before_manager_creation(official_native, action, payload):
    boundary, files, calls, managers, invoke = official_native
    assert invoke(action, payload) == {"schema": 1, "ok": False, "error": "official_request_invalid"}
    assert calls == [] and managers == []


def test_native_credential_validation_preserves_case_and_internal_spaces(official_native):
    boundary, files, calls, managers, invoke = official_native
    request = {"user_id": "Synthetic_ID-42", "password": "Case Sensitive 42", "platform": "android"}
    assert invoke("official_inspect", request)["ok"] is True
    assert calls[0] == ("command", files/"data", "official_inspect", request)


def test_postcommit_warnings_preserve_completed_account_and_allow_only_local_followup_codes(official_native):
    boundary, files, calls, managers, invoke = official_native
    invoke("official_inspect", {"user_id": SYNTHETIC_USER, "password": SYNTHETIC_PASSWORD, "platform": "android"})
    account = {"mode": "normal", "profile": "committed-normal", "revision": REVISION}
    managers[0].phase = "completed"
    managers[0].result_override = {"action": "official_apply", "job": {
        "state": "completed", "progress": "completed", "job_id": JOB, "busy": False},
        "account": account, "warning_codes": ["account_temporary_cleanup_pending", SYNTHETIC_PASSWORD,
            "account_status_refresh_required", "account_temporary_cleanup_pending"],
        "status_refresh_required": True}
    result = invoke("official_apply", {"job_id": JOB, "profile": account["profile"], "replace": False,
                                        "expected_revision": None})
    assert result["ok"] is True and result["job"]["state"] == "completed" and result["account"] == account
    assert result["warning_codes"] == ["account_temporary_cleanup_pending", "account_status_refresh_required"]
    assert result["status_refresh_required"] is True and "status" not in result
    assert SYNTHETIC_PASSWORD not in json.dumps(result)
    assert json.loads(boundary.status_json())["official_import"]["state"] == "completed"
    assert not any(call[0] == "command" and call[2] == "official_fetch" for call in calls)


@pytest.mark.parametrize("warnings", [SYNTHETIC_PASSWORD, [SYNTHETIC_PASSWORD], {"secret": SYNTHETIC_PASSWORD}])
def test_arbitrary_warning_data_is_not_forwarded_or_converted_into_an_import_failure(official_native, warnings):
    boundary, files, calls, managers, invoke = official_native
    invoke("official_inspect", {"user_id": SYNTHETIC_USER, "password": SYNTHETIC_PASSWORD, "platform": "android"})
    managers[0].result_override = {"action": "official_apply", "job": {"state": "completed"},
        "account": {"mode": "normal", "profile": "committed", "revision": REVISION},
        "warning_codes": warnings, "status_refresh_required": SYNTHETIC_PASSWORD}
    result = invoke("official_apply", {"job_id": JOB, "profile": "committed", "replace": False,
                                        "expected_revision": None})
    assert result["ok"] is True and result["job"]["state"] == "completed"
    assert result["warning_codes"] == [] and result["status_refresh_required"] is False
    assert result["account"]["revision"] == REVISION and SYNTHETIC_PASSWORD not in json.dumps(result)


def test_applying_is_a_fixed_public_stage_and_is_not_mistaken_for_idle(official_native):
    boundary, files, calls, managers, invoke = official_native
    invoke("official_inspect", {"user_id": SYNTHETIC_USER, "password": SYNTHETIC_PASSWORD, "platform": "android"})
    managers[0].public_override = {"state": "ready", "progress": "applying", "job_id": JOB, "busy": True}
    result = json.loads(boundary.status_json())["official_import"]
    assert result["state"] == "ready" and result["progress"] == "applying" and result["busy"] is True
