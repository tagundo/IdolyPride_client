"""Idempotent acknowledgements retain their response without rewriting state."""
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
        """)
    return value


def writes(state):
    with state.connect() as db:
        return [row[0] for row in db.execute("SELECT profile FROM observed_snapshot_updates")]


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
