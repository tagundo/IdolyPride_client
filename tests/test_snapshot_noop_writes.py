"""Idempotent acknowledgements retain their response without rewriting state."""
from concurrent.futures import ThreadPoolExecutor
import sqlite3

import pytest

from idoly_local.state import State


@pytest.fixture
def state(tmp_path):
    value = State(tmp_path / "state.db")
    value.save_snapshot("gallery", b"original\x00unknown-fields", "schema", starter_version=4)
    value.save_snapshot("other", b"another profile", "schema")
    with value.connect() as db:
        db.executescript("""
            CREATE TABLE observed_snapshot_updates (profile TEXT NOT NULL);
            CREATE TRIGGER observe_snapshot_update AFTER UPDATE ON snapshots
            BEGIN INSERT INTO observed_snapshot_updates VALUES (NEW.profile); END;
            CREATE TABLE observed_settings_writes (operation TEXT NOT NULL, profile TEXT NOT NULL);
            CREATE TRIGGER observe_settings_insert AFTER INSERT ON profile_settings
            BEGIN INSERT INTO observed_settings_writes VALUES ('insert', NEW.profile); END;
            CREATE TRIGGER observe_settings_update AFTER UPDATE ON profile_settings
            BEGIN INSERT INTO observed_settings_writes VALUES ('update', NEW.profile); END;
        """)
    return value


def writes(state):
    with state.connect() as db:
        return [row[0] for row in db.execute("SELECT profile FROM observed_snapshot_updates")]


def settings_writes(state):
    with state.connect() as db:
        return [tuple(row) for row in db.execute("SELECT operation,profile FROM observed_settings_writes")]


def test_identical_callback_results_do_not_execute_a_snapshot_update(state):
    token, identity = state.login("gallery")
    original = state.snapshot("gallery")[0]
    # A different bytes object with equal content is also an unchanged result.
    for callback in (lambda raw: raw, lambda raw: bytes(bytearray(raw))):
        assert state.mutate_snapshot("gallery", "schema", callback) == original
    assert writes(state) == []
    assert state.snapshot("gallery") == (original, "schema")
    assert state.snapshot("other") == (b"another profile", "schema")
    assert state.authenticated(token, "gallery")
    assert state.profile("gallery") == identity
    assert state.starter_version("gallery") == 4


def test_changed_snapshot_still_commits_once_and_its_retry_does_not_write(state):
    changed = b"updated\x00unknown-fields"
    assert state.mutate_snapshot("gallery", "schema", lambda _: changed) == changed
    assert writes(state) == ["gallery"]
    assert state.mutate_snapshot("gallery", "schema", lambda raw: raw) == changed
    assert writes(state) == ["gallery"]
    assert State(state.path).snapshot("gallery") == (changed, "schema")


def test_settings_commit_even_when_snapshot_result_is_identical(state):
    original = state.snapshot("gallery")[0]
    assert state.mutate_snapshot("gallery", "schema", lambda raw: raw,
                                 setting_info=b"new settings\x00") == original
    assert writes(state) == []
    assert State(state.path).settings("gallery") == (b"new settings\x00", "schema")


@pytest.mark.parametrize("settings", (b"", b"settings\x00unknown-fields"))
def test_settings_first_insert_and_changes_write_but_identical_retries_do_not(state, settings):
    original = state.snapshot("gallery")[0]
    token, _ = state.login("gallery")
    for _ in range(2):
        state.mutate_snapshot("gallery", "schema", lambda raw: raw,
                              setting_info=bytes(bytearray(settings)))
    assert settings_writes(state) == [("insert", "gallery")]
    assert state.settings("gallery") == (settings, "schema")
    assert state.snapshot("gallery") == (original, "schema")
    assert writes(state) == []

    changed = settings + b"\x01"
    for _ in range(2):
        state.mutate_snapshot("gallery", "schema", lambda raw: raw, setting_info=changed)
    assert settings_writes(state) == [("insert", "gallery"), ("update", "gallery")]
    assert State(state.path).settings("gallery") == (changed, "schema")
    assert state.authenticated(token, "gallery")
    assert state.snapshot("other") == (b"another profile", "schema")


def test_identical_settings_with_a_different_stored_schema_are_corrected_once(state):
    with state.connect() as db:
        db.execute("INSERT INTO profile_settings VALUES (?,?,?)",
                   ("gallery", b"settings\x00", "previous-schema"))
    for _ in range(2):
        state.mutate_snapshot("gallery", "schema", lambda raw: raw, setting_info=b"settings\x00")
    assert settings_writes(state) == [("insert", "gallery"), ("update", "gallery")]
    assert State(state.path).settings("gallery") == (b"settings\x00", "schema")
    assert writes(state) == []


def test_unchanged_settings_do_not_prevent_a_changed_snapshot_from_committing(state):
    state.mutate_snapshot("gallery", "schema", lambda raw: raw, setting_info=b"kept")
    state.mutate_snapshot("gallery", "schema", lambda _: b"new snapshot", setting_info=b"kept")
    assert writes(state) == ["gallery"]
    assert settings_writes(state) == [("insert", "gallery")]
    assert state.snapshot("gallery") == (b"new snapshot", "schema")
    assert state.settings("gallery") == (b"kept", "schema")


def test_failed_callback_cannot_replace_existing_settings(state):
    state.mutate_snapshot("gallery", "schema", lambda raw: raw, setting_info=b"kept")
    original = state.snapshot("gallery")
    token, _ = state.login("gallery")

    def fail(_):
        raise RuntimeError("synthetic callback failure")

    with pytest.raises(RuntimeError, match="synthetic callback failure"):
        state.mutate_snapshot("gallery", "schema", fail, setting_info=b"must not be stored")
    assert state.snapshot("gallery") == original
    assert state.settings("gallery") == (b"kept", "schema")
    assert settings_writes(state) == [("insert", "gallery")]
    assert writes(state) == []
    assert state.authenticated(token, "gallery")


@pytest.mark.parametrize("settings", (bytearray(b""), "settings", memoryview(b"settings")))
def test_nonbytes_settings_are_rejected_before_callback_and_never_write(state, settings):
    called = []
    original = state.snapshot("gallery")
    with pytest.raises(ValueError, match="Settings must be protobuf bytes"):
        state.mutate_snapshot("gallery", "schema", lambda raw: called.append(raw), setting_info=settings)
    assert called == []
    assert state.snapshot("gallery") == original
    assert state.settings("gallery") is None
    assert settings_writes(state) == [] and writes(state) == []


def test_concurrent_snapshot_updates_with_same_settings_are_not_lost(state):
    state.mutate_snapshot("gallery", "schema", lambda _: b"0")
    with state.connect() as db:
        db.execute("DELETE FROM observed_snapshot_updates")
    token, _ = state.login("gallery")

    def update(_):
        state.mutate_snapshot("gallery", "schema", lambda raw: str(int(raw) + 1).encode(),
                              setting_info=b"same settings")

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(update, range(20)))
    assert state.snapshot("gallery") == (b"20", "schema")
    assert writes(state) == ["gallery"] * 20
    assert settings_writes(state) == [("insert", "gallery")]
    assert state.settings("gallery") == (b"same settings", "schema")
    assert state.authenticated(token, "gallery")
    assert state.snapshot("other") == (b"another profile", "schema")


def test_failed_settings_write_still_rolls_back_a_changed_snapshot(state):
    original = state.snapshot("gallery")[0]
    with state.connect() as db:
        db.executescript("""
            CREATE TRIGGER reject_settings BEFORE INSERT ON profile_settings
            BEGIN SELECT RAISE(ABORT, 'synthetic settings rejection'); END;
        """)
    with pytest.raises(sqlite3.IntegrityError, match="synthetic settings rejection"):
        state.mutate_snapshot("gallery", "schema", lambda _: b"must roll back",
                              setting_info=b"rejected")
    assert state.snapshot("gallery") == (original, "schema")
    assert state.settings("gallery") is None
    assert writes(state) == []


def test_invalid_callback_result_keeps_snapshot_settings_and_sessions(state):
    token, _ = state.login("gallery")
    original = state.snapshot("gallery")[0]
    with pytest.raises(ValueError, match="protobuf bytes"):
        state.mutate_snapshot("gallery", "schema", lambda _: bytearray(b"invalid"),
                              setting_info=b"must not be stored")
    assert state.snapshot("gallery") == (original, "schema")
    assert state.settings("gallery") is None
    assert state.authenticated(token, "gallery")
    assert writes(state) == []
