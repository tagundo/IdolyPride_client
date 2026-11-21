"""Durable records preserve actual outcomes, never payloads or game-ready guesses."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
import threading
from unittest import mock

import pytest

from idoly_local import app_runtime
from idoly_local.runtime_history import FILE_NAME, MAX_BYTES, MAX_RECORDS, PersistentHistory, stored_status
from idoly_local.startup_checks import StartupChecks


def history(tmp_path):
    return PersistentHistory(tmp_path, debounce_seconds=3600)


def test_close_and_reopen_preserve_failure_run_and_bounded_later_successes(tmp_path):
    first = history(tmp_path)
    first.record_log("RPC /api.Photo/CheckExpressionShooting -> INVALID_ARGUMENT [private detail omitted]")
    failed = first.status()["last_failure"]
    for _ in range(MAX_RECORDS + 10):
        first.record_log("RPC /api.System/Check -> OK")
    assert first.close()
    assert (tmp_path / FILE_NAME).stat().st_size <= MAX_BYTES
    second = history(tmp_path)
    try:
        snapshot = second.status(full=True)
        assert snapshot["load_state"] == "loaded"
        assert snapshot["current_run"] != first.run_id
        assert snapshot["last_failure"] == failed
        assert failed["outcome"] == "INVALID_ARGUMENT" and failed["run_id"] == first.run_id
        assert len(snapshot["records"]) == MAX_RECORDS
        assert snapshot["total_records"] == MAX_RECORDS + 11
        assert "private detail" not in (tmp_path / FILE_NAME).read_text()
    finally:
        second.close()


def test_http_records_remove_authority_query_body_and_opaque_provider_names(tmp_path):
    record = history(tmp_path)
    record.http_failure({"path": "http://user:password@host/master/provider-private-name.db?token=query-secret#fragment",
        "method": "GET", "http_status": 404, "elapsed_ms": 12})
    record.record_log("Authorization: Bearer do-not-retain")
    record.record_log("/private/provider/private-path")
    record.record_log("Loaded local profile profile-private-name")
    record.close()
    raw = (tmp_path / FILE_NAME).read_text()
    assert all(secret not in raw for secret in (
        "password", "query-secret", "fragment", "provider-private-name", "do-not-retain",
        "private-path", "profile-private-name"))
    value = stored_status(tmp_path)
    assert value["last_failure"]["path"] == "/master/<file>"
    assert len(value["last_failure"]["route_fingerprint"]) == 16
    assert value["records"][-1]["code"] == "profile_loaded"


def test_normal_runtime_hook_records_failed_http_but_successful_polling_does_not_write(tmp_path):
    record = history(tmp_path)
    runtime = app_runtime.Runtime("sandbox", history=record)
    failure = {"request_id": 1, "method": "HEAD", "path": "/octo/102050/assetbundle/?secret=hidden",
        "http_status": 404, "phase": "failed", "elapsed_ms": 2}
    runtime._observe_http_request(failure)
    before = record.status(full=True)
    for identity in range(2, 20):
        runtime._observe_http_request({"request_id": identity, "method": "GET",
            "path": "/diagnostics/runtime", "http_status": 200, "phase": "completed", "elapsed_ms": 0})
        runtime.status()
    assert record.status(full=True) == before
    assert before["last_failure"]["path"] == "/octo/102050/assetbundle/<object>"
    assert record.close()


def test_polling_is_memory_only_and_snapshot_mutation_cannot_rewrite_saved_history(tmp_path):
    record = history(tmp_path)
    record.record_log("RPC /api.User/Get -> OK")
    with mock.patch("idoly_local.runtime_history.os.replace", side_effect=AssertionError("poll write")):
        for _ in range(30):
            value = record.status(full=True)
            value["records"][0]["method"] = "/api.Other/Changed"
        assert not (tmp_path / FILE_NAME).exists()
    assert record.status()["records"][0]["method"] == "/api.User/Get"
    assert record.close()


def test_concurrent_events_keep_unique_order_and_atomic_readable_document(tmp_path):
    record = history(tmp_path)
    with ThreadPoolExecutor(max_workers=8) as workers:
        list(workers.map(lambda _: record.record_log("RPC /api.System/Check -> OK"), range(400)))
    assert record.flush()
    value = json.loads((tmp_path / FILE_NAME).read_text())
    sequences = [row["sequence"] for row in value["records"]]
    assert len(sequences) == MAX_RECORDS
    assert sequences == sorted(set(sequences))
    assert value["total_records"] == 400
    assert record.close()


@pytest.mark.parametrize("raw", [b"{truncated", b'{"schema":1,"schema":1}', b"x" * (MAX_BYTES + 1)])
def test_corrupt_or_oversized_history_recovers_empty_and_new_write_remains_truthful(tmp_path, raw):
    (tmp_path / FILE_NAME).write_bytes(raw)
    record = history(tmp_path)
    assert record.status()["load_state"] == "recovered_invalid"
    assert [row["code"] for row in record.status()["records"]] == ["history_recovered"]
    record.record_log("RPC /api.System/Check -> OK")
    assert record.close()
    assert stored_status(tmp_path)["load_state"] == "loaded"
    assert stored_status(tmp_path)["records"][-1]["outcome"] == "OK"
    assert record.status()["load_state"] == "recovered_invalid"


def test_symlink_history_is_not_followed_or_overwritten(tmp_path):
    target = tmp_path / "private-source"
    target.write_text("do-not-change")
    (tmp_path / FILE_NAME).symlink_to(target)
    record = history(tmp_path)
    record.record_log("RPC /api.System/Check -> OK")
    assert record.flush() is False
    assert record.status()["last_write_error"] == "unsafe_history_file"
    assert target.read_text() == "do-not-change" and (tmp_path / FILE_NAME).is_symlink()
    record.close()


def test_failed_atomic_replace_preserves_previous_record_and_can_retry(tmp_path):
    record = history(tmp_path)
    record.record_log("RPC /api.System/Check -> OK")
    assert record.flush()
    before = (tmp_path / FILE_NAME).read_bytes()
    record.record_log("RPC /api.Master/Get -> UNAVAILABLE")
    with mock.patch("idoly_local.runtime_history.os.replace", side_effect=PermissionError("private provider")):
        assert record.flush() is False
    assert (tmp_path / FILE_NAME).read_bytes() == before
    assert record.status()["last_write_error"] == "history_io"
    assert record.flush()
    assert stored_status(tmp_path)["last_failure"]["outcome"] == "UNAVAILABLE"
    assert not list(tmp_path.glob("." + FILE_NAME + ".*.tmp"))
    record.close()


def test_slow_storage_keeps_one_timed_writer_instead_of_queueing_threads(tmp_path):
    record = PersistentHistory(tmp_path, debounce_seconds=.05)
    entered, release = threading.Event(), threading.Event()
    real_timer, real_replace = threading.Timer, os.replace
    timers = []
    def timer(delay, callback):
        result = real_timer(delay, callback)
        timers.append(result)
        return result
    def replace(source, target):
        entered.set()
        assert release.wait(3)
        return real_replace(source, target)
    try:
        with mock.patch("idoly_local.runtime_history.threading.Timer", side_effect=timer), \
             mock.patch("idoly_local.runtime_history.os.replace", side_effect=replace):
            record.record_log("RPC /api.System/Check -> OK")
            assert entered.wait(2)
            for _ in range(50):
                record.record_log("RPC /api.System/Check -> OK")
            assert len(timers) == 1
            release.set()
            timers[0].join(timeout=2)
            assert not timers[0].is_alive()
    finally:
        release.set()
        record.close()
    assert stored_status(tmp_path)["total_records"] == 51


def test_stopped_lookup_does_not_start_a_session_or_claim_previous_ready_is_current(tmp_path):
    record = history(tmp_path)
    checks = StartupChecks(record)
    checks.record("http", "ready", "listener_started", port=8080, protocol_exchange="not_checked")
    checks.state("ready")
    record.close()
    before = (tmp_path / FILE_NAME).read_bytes()
    with mock.patch("idoly_local.runtime_history.uuid.uuid4", side_effect=AssertionError("new session")):
        observed = app_runtime.server_settings_status(tmp_path)
    assert observed["startup_checks"]["scope"] == "previous_run"
    assert observed["startup_checks"]["gameplay_verified"] is False
    assert observed["durable_history"]["current_run"] is None
    assert (tmp_path / FILE_NAME).read_bytes() == before


def test_explicit_clear_removes_saved_failures_without_clearing_accounts(tmp_path):
    account = tmp_path / "state.db"
    account.write_bytes(b"unopened-account-sentinel")
    record = history(tmp_path)
    record.record_log("RPC /api.Photo/CheckExpressionShooting -> INVALID_ARGUMENT")
    record.close()
    cleared = app_runtime.clear_server_history(tmp_path)
    assert cleared["last_failure"] is None
    assert [row["code"] for row in cleared["records"]] == ["history_cleared"]
    assert account.read_bytes() == b"unopened-account-sentinel"


def test_storage_probe_runs_once_and_polling_never_probes_again(tmp_path):
    record = history(tmp_path)
    checks = StartupChecks(record)
    checks.storage(tmp_path, None)
    first = checks.status()
    assert next(row for row in first["checks"] if row["id"] == "storage")["free_bytes"] >= 0
    assert not list(tmp_path.glob(".idoly-startup-check-*"))
    with mock.patch("idoly_local.startup_checks.os.open", side_effect=AssertionError("poll probe")):
        for _ in range(20):
            assert checks.status() == first
    record.close()


def test_native_payload_failure_is_stored_without_opening_an_account(tmp_path):
    error = PermissionError("provider-and-credential-private-path")
    with mock.patch.object(app_runtime, "Runtime", side_effect=AssertionError("runtime constructed")):
        current = app_runtime.record_startup_failure(tmp_path / "new-data", error, stage="catalog")
    assert current["startup_checks"]["state"] == "blocked"
    assert current["durable_history"]["available"] is True
    previous = app_runtime.server_settings_status(tmp_path / "new-data")
    failure = previous["durable_history"]["last_failure"]
    assert failure["stage"] == "catalog" and failure["error_type"] == "PermissionError"
    assert failure["code"] == "permission_denied"
    assert previous["startup_checks"]["scope"] == "previous_run"
    assert not (tmp_path / "new-data" / "state.db").exists()
    assert "provider-and-credential" not in json.dumps(previous)


def test_native_payload_record_write_failure_returns_original_error_identity(tmp_path):
    original = FileNotFoundError("do-not-export-provider-path")
    with mock.patch("idoly_local.runtime_history.os.replace", side_effect=PermissionError("writer private path")):
        result = app_runtime.record_startup_failure(tmp_path, original, stage="resources")
    assert result["durable_history"]["available"] is False
    assert result["durable_history"]["last_write_error"] == "history_io"
    failure = result["durable_history"]["last_failure"]
    assert failure["error_type"] == "FileNotFoundError" and failure["stage"] == "resources"
    assert failure["code"] == "missing_input"
    assert "provider-path" not in json.dumps(result)


def test_native_payload_failure_with_no_writable_root_is_only_an_in_memory_observation(tmp_path):
    file_root = tmp_path / "not-a-directory"
    file_root.write_bytes(b"preserve")
    result = app_runtime.record_startup_failure(file_root, ValueError("private payload input"), stage="catalog")
    assert result["startup_checks"]["state"] == "blocked"
    assert result["startup_checks"]["gameplay_verified"] is False
    history = result["durable_history"]
    assert history["available"] is False and history["persistence"] == "unavailable"
    assert history["last_failure"]["error_type"] == "ValueError"
    assert history["last_failure"]["code"] == "invalid_input"
    assert file_root.read_bytes() == b"preserve"
    assert "private payload" not in json.dumps(result)
