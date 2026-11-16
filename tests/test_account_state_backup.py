"""Account capture and replacement use coherent SQLite transactions, not User.Get alone."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib

import pytest

from idoly_local.state import State

FP = hashlib.sha256(b"account-state-schema").hexdigest()


def seeded(tmp_path):
    state = State(tmp_path/"state.db")
    state.save_snapshot("source", b"0", FP, starter_version=4)
    state.save_snapshot("target", b"old", FP, starter_version=7)
    with state.connect() as db:
        db.execute("INSERT INTO profile_lesson_progress VALUES (?,?,?)", ("source", b"0", FP))
        db.execute("INSERT INTO profile_settings VALUES (?,?,?)", ("source", b"settings\x80\x4b\x7b", FP))
        db.execute("INSERT INTO preference_receipts VALUES (?,?,?,?,?,?)", (
            "source", "/api.Photograph/ToggleLock", "5", "a"*64, FP, b"preference\x80\x4b\x7b"))
        db.execute("INSERT INTO main_live_attempts VALUES (?,?,?,?,?,?,?,?,?,?)", (
            "source", "9", "b"*64, "/api.Quest/Start", FP, "master", "rules", "42", 1000, b"live\x80\x4b\x7b"))
    return state


def test_full_table_capture_is_consistent_while_lesson_transactions_commit(tmp_path):
    state = seeded(tmp_path)
    def writer():
        for n in range(1, 70):
            value = str(n).encode()
            state.mutate_lesson_snapshot("source", FP, lambda _snapshot, _clock: (value, value))
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(writer)
        for _ in range(35):
            bundle, revision = state.account_snapshot("source")
            assert bundle["tables"]["snapshots"][0]["response"] == bundle["tables"]["profile_lesson_progress"][0]["response"]
            assert revision == hashlib.sha256(State.account_bytes(bundle)).hexdigest()
            assert {key: len(rows) for key, rows in bundle["tables"].items()} == {
                "profiles": 1, "snapshots": 1, "profile_settings": 1, "starter_profiles": 1,
                "profile_lesson_progress": 1, "preference_receipts": 1, "main_live_attempts": 1}
        future.result()


def test_snapshot_clone_preserves_all_rows_but_never_copies_sessions(tmp_path):
    state = seeded(tmp_path)
    token, _ = state.login("source")
    bundle, original_revision = state.account_snapshot("source")
    state.replace_account("branch", bundle)
    restored, _ = state.account_snapshot("branch")
    assert state.account_snapshot("source") == (bundle, original_revision)
    for table, rows in bundle["tables"].items():
        key = "name" if table == "profiles" else "profile"
        assert restored["tables"][table] == [{**row, key: "branch"} for row in rows]
    assert state.authenticated(token, "source") and not state.authenticated(token, "branch")


def test_stale_revision_is_rejected_before_restore_point_callback(tmp_path):
    state = seeded(tmp_path); bundle, _ = state.account_snapshot("source")
    before = state.account_snapshot("target"); calls = []
    with pytest.raises(ValueError, match="revision_conflict"):
        state.replace_account("target", bundle, expected_revision="0"*64,
                              before_replace=lambda *_: calls.append(True))
    assert calls == [] and state.account_snapshot("target") == before


def test_backup_callback_failure_preserves_all_rows_and_live_sessions(tmp_path):
    state = seeded(tmp_path); bundle, _ = state.account_snapshot("source")
    before = state.account_snapshot("target"); token, _ = state.login("target")
    def failed(old, revision):
        assert (old, revision) == before
        raise OSError("backup could not be made durable")
    with pytest.raises(OSError):
        state.replace_account("target", bundle, expected_revision=before[1], before_replace=failed)
    assert state.account_snapshot("target") == before and state.authenticated(token, "target")


@pytest.mark.parametrize("mutation", ["sessions", "unknown_column", "duplicate_row", "wrong_profile", "wrong_type"])
def test_archive_records_cannot_introduce_sql_or_unrecognized_state(mutation, tmp_path):
    state = seeded(tmp_path); bundle, _ = state.account_snapshot("source")
    bad = deepcopy(bundle)
    if mutation == "sessions": bad["tables"]["sessions"] = []
    elif mutation == "unknown_column": bad["tables"]["profiles"][0]["sql"] = "DROP TABLE profiles"
    elif mutation == "duplicate_row": bad["tables"]["preference_receipts"] *= 2
    elif mutation == "wrong_profile": bad["tables"]["snapshots"][0]["profile"] = "target"
    else: bad["tables"]["snapshots"][0]["response"] = "not protobuf bytes"
    before = state.account_snapshot("target")
    with pytest.raises(ValueError):
        state.replace_account("target", bad, expected_revision=before[1])
    assert state.account_snapshot("target") == before
