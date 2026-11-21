"""Preparation failures are durable once; runtime failures keep their original record."""
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import engine


def controller(tmp_path):
    return engine.Controller(tmp_path, tmp_path/"ServerData.zip", emit_event=lambda *args, **kwargs: None)


def test_payload_failure_is_observed_before_runtime_entry(tmp_path, monkeypatch):
    from idoly_local import app_runtime
    value = controller(tmp_path)
    seen = []
    error = FileNotFoundError("private provider path")
    def install(*args, **kwargs):
        raise error
    monkeypatch.setattr(engine, "install_payload", install)
    monkeypatch.setattr(app_runtime, "record_startup_failure",
        lambda root, failure, stage="catalog": seen.append((root, failure, stage)))
    value._start()
    assert seen == [(tmp_path, error, "catalog")]
    assert value.runtime is None


def test_runtime_failure_is_not_observed_twice_by_native_wrapper(tmp_path, monkeypatch):
    from idoly_local import app_runtime
    value = controller(tmp_path)
    seen = []
    monkeypatch.setattr(engine, "install_payload", lambda *args: None)
    monkeypatch.setattr(engine, "install_bundled_translations", lambda *args, **kwargs: {"state": "absent"})
    def fail(*args, **kwargs):
        raise ValueError("already observed by shared runtime")
    monkeypatch.setattr(app_runtime, "start", fail)
    monkeypatch.setattr(app_runtime, "record_startup_failure",
        lambda *args, **kwargs: seen.append((args, kwargs)))
    value._start()
    assert seen == []


def test_account_first_install_failure_uses_same_preparation_observer(tmp_path, monkeypatch):
    from idoly_local import app_runtime
    value = controller(tmp_path)
    seen = []
    def install(*args, **kwargs):
        raise PermissionError("private destination")
    monkeypatch.setattr(engine, "install_payload", install)
    monkeypatch.setattr(app_runtime, "record_startup_failure",
        lambda root, failure, stage="catalog": seen.append((root, type(failure), stage)))
    value._account_operation(1, "accounts_create", {"mode": "normal", "profile": "new", "manager_name": "Manager"}, None)
    assert seen == [(tmp_path, PermissionError, "catalog")]
