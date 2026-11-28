"""Mac account IPC, native copy ownership and user-visible management contracts."""
from pathlib import Path
import hashlib
import json
import os
import sys
import threading
import time
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import engine


def wait_for(check):
    end = time.monotonic() + 5
    while time.monotonic() < end:
        if check():
            return
        time.sleep(.01)
    raise AssertionError("Account worker did not finish")


def controller(tmp_path):
    events = []
    protocol = tmp_path/"protocol"
    protocol.mkdir(exist_ok=True)
    (protocol/"idolypride-6.1.1.pb").write_bytes(b"owned test descriptor")
    value = engine.Controller(tmp_path, tmp_path/"ServerData.zip",
        emit_event=lambda event, **data: events.append((event, data)))
    return value, events


def mock_accounts(monkeypatch, callback):
    monkeypatch.setitem(sys.modules, "idoly_local.account_manager",
                        SimpleNamespace(account_command=callback))


def owned_export(tmp_path, body=b"PK\x03\x04account-archive"):
    folder = tmp_path/"account-management/exports"
    folder.mkdir(parents=True)
    name = "IdolyPride-Account-" + "a"*32 + ".zip"
    source = folder/name
    source.write_bytes(body)
    return {"path": str(source), "filename": name, "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest()}


def test_account_worker_keeps_ipc_responsive_and_rejects_overlapping_commands(tmp_path, monkeypatch):
    value, events = controller(tmp_path)
    entered, finish = threading.Event(), threading.Event()
    calls = []
    def command(root, action, payload):
        calls.append((root, action, payload)); entered.set()
        assert finish.wait(3)
        return {"schema": 1, "ok": True, "action": action, "status": {"accounts": []}}
    mock_accounts(monkeypatch, command)
    value.accounts("accounts_status", {"request_id": 1, "action": "accounts_status", "offset": 24})
    assert entered.wait(2)
    value.accounts("accounts_status", {"request_id": 2})
    assert events[-1] == ("account_error", {"request_id": 2, "action": "accounts_status",
                                            "code": "account_operation_busy"})
    assert value.status()["running"] is False
    finish.set()
    wait_for(lambda: value.account_worker is None)
    result = [data for event, data in events if event == "account_result"]
    assert result[0]["request_id"] == 1 and result[0]["action"] == "accounts_status"
    assert calls == [(tmp_path, "accounts_status", {"offset": 24})]
    assert value.status()["accounts"] == {"accounts": []}


@pytest.mark.parametrize("identifier", [None, True, "1", 0, -1, 2**31])
def test_account_request_ids_are_bounded_integers_before_any_work(tmp_path, monkeypatch, identifier):
    value, events = controller(tmp_path)
    mock_accounts(monkeypatch, lambda *args: pytest.fail("Account core must not run"))
    value.accounts("accounts_status", {"request_id": identifier})
    assert events[-1][0] == "account_error" and events[-1][1]["code"] == "account_request_invalid"
    assert value.account_worker is None


@pytest.mark.parametrize("action,payload", [
    ("accounts_restore", {"id": "point", "mode": "normal", "profile": "sandbox", "expected_revision": "a"*64}),
    ("accounts_import", {"token": "a"*32, "mode": "normal", "profile": "sandbox", "replace": True,
                         "expected_revision": "a"*64}),
])
def test_replacement_and_restore_require_stopped_server(tmp_path, monkeypatch, action, payload):
    value, events = controller(tmp_path)
    value.runtime = SimpleNamespace(status=lambda: {"running": True})
    mock_accounts(monkeypatch, lambda *args: pytest.fail("Active account must not be replaced"))
    value.accounts(action, {"request_id": 1, **payload})
    assert events[-1][1]["code"] == "account_server_running"
    assert value.account_worker is None


def test_selection_is_queued_without_stopping_or_switching_current_runtime(tmp_path, monkeypatch):
    value, events = controller(tmp_path)
    runtime = SimpleNamespace(status=lambda: {"running": True, "profile": "sandbox"}, stop=lambda: pytest.fail("No hot switch"))
    value.runtime = runtime
    calls = []
    def command(root, action, payload):
        calls.append(payload)
        return {"schema": 1, "ok": True, "action": action, "status": {"selected": {"normal": "second"}}}
    mock_accounts(monkeypatch, command)
    value.accounts("accounts_select", {"request_id": 7, "mode": "normal", "profile": "second",
                                       "expected_revision": "b"*64, "selection_revision": "c"*64})
    wait_for(lambda: value.account_worker is None)
    assert value.runtime is runtime and value.status()["profile"] == "sandbox"
    assert calls == [{"mode": "normal", "profile": "second", "expected_revision": "b"*64,
                      "selection_revision": "c"*64}]
    assert any(event == "account_result" and data["request_id"] == 7 for event, data in events)


def test_account_errors_do_not_expose_native_provider_paths(tmp_path, monkeypatch):
    value, events = controller(tmp_path)
    def command(*args):
        raise ValueError("/Users/private/provider/private-account.zip")
    mock_accounts(monkeypatch, command)
    value.accounts("accounts_preview", {"request_id": 3, "path": "/Users/private/provider/private-account.zip"})
    wait_for(lambda: value.account_worker is None)
    errors = [data for event, data in events if event == "account_error"]
    assert errors == [{"request_id": 3, "action": "accounts_preview", "code": "account_operation_failed"}]
    assert "private-account" not in json.dumps(events)


def test_export_copies_exact_owned_bytes_atomically_and_hides_internal_path(tmp_path, monkeypatch):
    value, events = controller(tmp_path)
    wanted = owned_export(tmp_path)
    destination = tmp_path/"chosen-backup.zip"
    destination.write_bytes(b"old chosen backup")
    mock_accounts(monkeypatch, lambda root, action, payload:
        {"schema": 1, "ok": True, "action": action, "status": {"accounts": []}, **wanted})
    value.accounts("accounts_export", {"request_id": 4, "mode": "normal", "profile": "sandbox",
                                       "expected_revision": "d"*64, "destination": str(destination)})
    wait_for(lambda: value.account_worker is None)
    assert destination.read_bytes() == Path(wanted["path"]).read_bytes()
    results = [data for event, data in events if event == "account_result"]
    assert len(results) == 1 and "path" not in results[0]["result"]
    assert results[0]["result"]["sha256"] == wanted["sha256"]
    assert not list(tmp_path.glob(".idoly-account-*.part"))
    assert any(event == "account_progress" and data.get("received_bytes") == wanted["bytes"]
               for event, data in events)


@pytest.mark.parametrize("case", ["source_symlink", "foreign_source", "destination_symlink",
                                 "digest", "extent", "hardlink_source", "filename"])
def test_account_export_rejects_path_aliases_and_fingerprint_changes_without_overwrite(tmp_path, case):
    wanted = owned_export(tmp_path)
    source = Path(wanted["path"])
    destination = tmp_path/"chosen.zip"
    destination.write_bytes(b"preserved")
    if case == "source_symlink":
        original = source.with_name("original.zip"); source.rename(original); source.symlink_to(original)
    elif case == "foreign_source":
        foreign = tmp_path/source.name; source.rename(foreign); wanted["path"] = str(foreign)
    elif case == "destination_symlink":
        actual = tmp_path/"actual.zip"; destination.rename(actual); destination.symlink_to(actual)
    elif case == "digest": wanted["sha256"] = "0"*64
    elif case == "extent": wanted["bytes"] += 1
    elif case == "hardlink_source": os.link(source, tmp_path/"alias.zip")
    else: wanted["filename"] = "other.zip"
    with pytest.raises((OSError, ValueError)):
        engine._account_export_copy(tmp_path, wanted, str(destination), lambda *args: None)
    assert destination.read_bytes() == b"preserved"
    assert not list(tmp_path.glob(".idoly-account-*.part"))


def test_fresh_account_operations_prepare_payload_in_background(tmp_path, monkeypatch):
    value, events = controller(tmp_path)
    calls = []
    (tmp_path/"protocol/idolypride-6.1.1.pb").unlink()
    def install(source, root, log):
        calls.append(("install", source, root))
        folder = root/"protocol"; folder.mkdir(exist_ok=True)
        (folder/"idolypride-6.1.1.pb").write_bytes(b"owned test descriptor")
    monkeypatch.setattr(engine, "install_payload", install)
    mock_accounts(monkeypatch, lambda root, action, payload:
        (calls.append(("command", action)) or {"schema": 1, "ok": True, "action": action, "status": {}}))
    value.accounts("accounts_create", {"request_id": 1, "mode": "normal", "profile": "new", "manager_name": "New"})
    wait_for(lambda: value.account_worker is None)
    assert [row[0] for row in calls] == ["install", "command"]
    assert any(event == "account_result" for event, _ in events)


def test_native_controls_use_picker_preview_and_stop_guard_without_duplicate_game_launch():
    source = (Path(__file__).resolve().parents[1]/"App.swift").read_text()
    assert 'GroupBox("유저 관리 · 계정 백업")' in source
    assert 'NSSavePanel()' in source and 'NSOpenPanel()' in source
    assert 'sendAccount("accounts_preview"' in source
    assert 'sendAccount("accounts_import"' in source
    assert 'sendAccount("accounts_restore"' in source
    assert '계정 ZIP에는 계정·진행·게임 설정' in source and '리소스 ZIP에는 계정이 없습니다' in source
    assert 'diagnosticStatus = state.filter { $0.key != "accounts" }' in source
    assert source.count('Button("PlayCover에서 열기")') == 1
    assert 'identifier == pendingAccountID' in source and 'event["action"] as? String == pendingAccountAction' in source
    assert 'offset: max(0, accountOffset - 24)' in source and 'restoreOffset: max(0, restoreOffset - 16)' in source

@pytest.mark.parametrize("action", [None, [], {}, "accounts_delete"])
def test_unknown_or_unhashable_account_actions_do_not_reach_core(tmp_path, monkeypatch, action):
    value, events = controller(tmp_path)
    mock_accounts(monkeypatch, lambda *args: pytest.fail("Unknown account action reached core"))
    value.accounts(action, {"request_id": 1})
    assert events[-1] == ("account_error", {"request_id": 1, "action": None, "code": "account_request_invalid"})


def test_server_start_waits_for_account_worker_without_starting_another_thread(tmp_path):
    value, events = controller(tmp_path)
    value.account_worker = SimpleNamespace(is_alive=lambda: True)
    value.start()
    assert value.worker is None and value.runtime is None
    assert events[-1][0] == "status"

