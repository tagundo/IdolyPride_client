"""Lesson earnings need the profile snapshot and clock to commit together."""
from concurrent.futures import ThreadPoolExecutor
import sqlite3

import pytest

from idoly_local.state import State


FINGERPRINT = "independent-test-schema"
SNAPSHOT = b"opaque-snapshot-with-unknown-fields\xf8\x7f\x01"


@pytest.fixture
def state(tmp_path):
    state = State(tmp_path / "profiles.sqlite")
    state.save_snapshot("player", SNAPSHOT, FINGERPRINT, starter_version=4)
    state.save_snapshot("other", b"other-profile", FINGERPRINT)
    return state


def database(state):
    with state.connect() as db:
        return tuple(db.iterdump())


def initialize(state, progress=b"local-clock"):
    return state.mutate_lesson_snapshot("player", FINGERPRINT, lambda raw, old: (raw, progress))


def test_first_clock_is_explicit_and_initialization_preserves_profile_state(state):
    token, identity = state.login("player")
    state.mutate_snapshot("player", FINGERPRINT, lambda raw: raw, setting_info=b"existing-settings")
    other = state.snapshot("other")
    observed = []

    def first(raw, progress):
        observed.append((raw, progress))
        return raw, b"new-local-clock"

    assert state.lesson_progress("player") is None
    assert state.mutate_lesson_snapshot("player", FINGERPRINT, first) == (SNAPSHOT, b"new-local-clock")
    assert observed == [(SNAPSHOT, None)]
    assert state.snapshot("player") == (SNAPSHOT, FINGERPRINT)
    assert state.lesson_progress("player") == (b"new-local-clock", FINGERPRINT)
    assert state.snapshot("other") == other and state.lesson_progress("other") is None
    assert state.profile("player") == identity and state.authenticated(token, "player")
    assert state.settings("player") == (b"existing-settings", FINGERPRINT)
    assert state.starter_version("player") == 4


def test_clock_and_reward_snapshot_survive_restart_together(state):
    initialize(state)
    token, _ = state.login("player")

    def reward(raw, progress):
        assert raw == SNAPSHOT and progress == b"local-clock"
        return raw + b"earned-delta", b"advanced-clock"

    assert state.mutate_lesson_snapshot("player", FINGERPRINT, reward) == (
        SNAPSHOT + b"earned-delta", b"advanced-clock")
    restarted = State(state.path)
    assert restarted.snapshot("player") == (SNAPSHOT + b"earned-delta", FINGERPRINT)
    assert restarted.lesson_progress("player") == (b"advanced-clock", FINGERPRINT)
    assert restarted.authenticated(token, "player")


def test_unchanged_view_does_not_rewrite_the_snapshot_or_initialized_clock(state):
    initialize(state)
    # Abort on any redundant UPDATE: logical equality alone would not prove
    # Home.Enter can initialize/project a clock without rewriting the snapshot.
    with state.connect() as db:
        db.executescript("""
            CREATE TRIGGER prevent_snapshot_rewrite BEFORE UPDATE ON snapshots
            BEGIN SELECT RAISE(ABORT,'snapshot was rewritten'); END;
            CREATE TRIGGER prevent_lesson_rewrite BEFORE UPDATE ON profile_lesson_progress
            BEGIN SELECT RAISE(ABORT,'lesson was rewritten'); END;
        """)
    before = database(state)
    assert state.mutate_lesson_snapshot("player", FINGERPRINT, lambda raw, progress: (raw, progress)) == (
        SNAPSHOT, b"local-clock")
    assert database(state) == before


def test_callback_error_rolls_back_existing_snapshot_and_clock(state):
    initialize(state)
    before = database(state)

    def fail(raw, progress):
        raise RuntimeError("calculation failed")

    with pytest.raises(RuntimeError, match="calculation failed"):
        state.mutate_lesson_snapshot("player", FINGERPRINT, fail)
    assert database(state) == before


def test_database_error_after_snapshot_update_rolls_back_both_rows(state):
    initialize(state)
    with state.connect() as db:
        db.executescript("""
            CREATE TRIGGER reject_lesson BEFORE UPDATE ON profile_lesson_progress
            BEGIN SELECT RAISE(ABORT,'synthetic clock write failure'); END;
        """)
    before = database(state)
    with pytest.raises(sqlite3.IntegrityError, match="clock write failure"):
        state.mutate_lesson_snapshot("player", FINGERPRINT, lambda raw, progress: (b"changed", b"advanced"))
    assert database(state) == before


def test_database_error_on_first_clock_insertion_does_not_apply_reward(state):
    with state.connect() as db:
        db.executescript("""
            CREATE TRIGGER reject_clock_insert BEFORE INSERT ON profile_lesson_progress
            BEGIN SELECT RAISE(ABORT,'synthetic first clock failure'); END;
        """)
    before = database(state)
    with pytest.raises(sqlite3.IntegrityError, match="first clock failure"):
        state.mutate_lesson_snapshot("player", FINGERPRINT, lambda raw, progress: (b"changed", b"new"))
    assert database(state) == before


@pytest.mark.parametrize("result", [None, (), (b"snapshot",), [b"snapshot", b"clock"],
    (b"snapshot", b"clock", b"extra"), ("not bytes", b"clock"), (b"snapshot", None),
    (b"snapshot", bytearray(b"clock"))])
def test_invalid_callback_result_leaves_every_table_unchanged(state, result):
    before = database(state)
    with pytest.raises(ValueError, match="return snapshot and progress bytes"):
        state.mutate_lesson_snapshot("player", FINGERPRINT, lambda *_: result)
    assert database(state) == before


def test_empty_progress_is_valid_opaque_protobuf_and_not_treated_as_missing(state):
    assert initialize(state, b"") == (SNAPSHOT, b"")
    assert state.lesson_progress("player") == (b"", FINGERPRINT)
    observed = []
    state.mutate_lesson_snapshot("player", FINGERPRINT,
        lambda raw, progress: (observed.append(progress) or raw, progress))
    assert observed == [b""]


@pytest.mark.parametrize("profile,fingerprint", [("missing", FINGERPRINT), ("player", "wrong-schema")])
def test_missing_or_incompatible_snapshot_never_calls_calculator(state, profile, fingerprint):
    before = database(state)
    with pytest.raises(ValueError):
        state.mutate_lesson_snapshot(profile, fingerprint, lambda *_: pytest.fail("Must not calculate"))
    assert database(state) == before
    assert state.profile("missing") is None


def test_mismatched_clock_schema_is_not_silently_reset_or_passed_to_calculator(state):
    initialize(state)
    with state.connect() as db:
        db.execute("UPDATE profile_lesson_progress SET schema_sha256='other-schema' WHERE profile='player'")
    before = database(state)
    with pytest.raises(ValueError, match="lesson progress uses a different schema"):
        state.mutate_lesson_snapshot("player", FINGERPRINT, lambda *_: pytest.fail("Must not calculate"))
    assert database(state) == before


def test_concurrent_claims_see_each_preceding_reward_and_clock_atomically(state):
    state.save_snapshot("player", b"0", FINGERPRINT)
    initialize(state, b"0")

    def claim(_):
        def advance(raw, progress):
            assert raw == progress
            next_value = str(int(raw) + 1).encode()
            return next_value, next_value
        return State(state.path).mutate_lesson_snapshot("player", FINGERPRINT, advance)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(claim, range(24)))
    assert {int(raw) for raw, progress in results if raw == progress} == set(range(1, 25))
    assert state.snapshot("player") == (b"24", FINGERPRINT)
    assert state.lesson_progress("player") == (b"24", FINGERPRINT)


def test_explicit_replacement_resets_only_target_clock_and_session(state):
    initialize(state)
    state.mutate_lesson_snapshot("other", FINGERPRINT, lambda raw, old: (raw, b"other-clock"))
    state.mutate_snapshot("player", FINGERPRINT, lambda raw: raw, setting_info=b"keep-settings")
    token, _ = state.login("player")
    other_token, _ = state.login("other")
    state.save_snapshot("player", b"imported-account", FINGERPRINT,
                        server_id="imported-server", public_id="imported-public")
    assert state.snapshot("player") == (b"imported-account", FINGERPRINT)
    assert state.lesson_progress("player") is None
    assert not state.authenticated(token, "player")
    assert state.lesson_progress("other") == (b"other-clock", FINGERPRINT)
    assert state.authenticated(other_token, "other")
    assert state.settings("player") == (b"keep-settings", FINGERPRINT)
    observed = []
    state.mutate_lesson_snapshot("player", FINGERPRINT,
        lambda raw, old: (observed.append(old) or raw, b"new-account-anchor"))
    assert observed == [None]


def test_replacement_failure_rolls_back_clock_snapshot_and_session_reset(state):
    initialize(state)
    token, _ = state.login("player")
    with state.connect() as db:
        db.executescript("""
            CREATE TRIGGER prevent_clock_reset BEFORE DELETE ON profile_lesson_progress
            BEGIN SELECT RAISE(ABORT,'synthetic reset failure'); END;
        """)
    before = database(state)
    with pytest.raises(sqlite3.IntegrityError, match="reset failure"):
        state.save_snapshot("player", b"replacement", FINGERPRINT, server_id="changed-identity")
    assert database(state) == before
    assert state.authenticated(token, "player")


def test_ordinary_actions_and_starter_migrations_preserve_the_clock(state):
    initialize(state)
    token, _ = state.login("player")
    state.mutate_snapshot("player", FINGERPRINT, lambda raw: raw + b"ordinary-action")
    state.mutate_starter_snapshot("player", FINGERPRINT, lambda raw, version: (raw + b"migration", 5))
    assert state.lesson_progress("player") == (b"local-clock", FINGERPRINT)
    assert state.starter_version("player") == 5 and state.authenticated(token, "player")


def test_existing_database_gets_an_empty_clock_table_without_backfilling_account_time(tmp_path):
    path = tmp_path / "legacy.sqlite"
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE profiles(name TEXT PRIMARY KEY,server_id TEXT NOT NULL,public_id TEXT NOT NULL);
            CREATE TABLE snapshots(profile TEXT PRIMARY KEY REFERENCES profiles(name),response BLOB NOT NULL,schema_sha256 TEXT NOT NULL);
            INSERT INTO profiles VALUES('legacy','existing-server','existing-public');
        """)
        db.execute("INSERT INTO snapshots VALUES(?,?,?)", ("legacy", SNAPSHOT, FINGERPRINT))
    state = State(path)
    assert state.snapshot("legacy") == (SNAPSHOT, FINGERPRINT)
    assert state.lesson_progress("legacy") is None
    assert state.profile("legacy")["server_id"] == "existing-server"


@pytest.mark.parametrize("fingerprint,callback", [("", lambda *_: (b"", b"")), (None, lambda *_: (b"", b"")),
                                                  (FINGERPRINT, None)])
def test_invalid_mutation_contract_fails_before_touching_state(state, fingerprint, callback):
    before = database(state)
    with pytest.raises(ValueError):
        state.mutate_lesson_snapshot("player", fingerprint, callback)
    assert database(state) == before
