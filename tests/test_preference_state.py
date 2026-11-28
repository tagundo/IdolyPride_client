"""A retried toggle commits once without overwriting subsequent preferences."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import sqlite3

import pytest

from idoly_local.state import AttemptConflict, State

PATH = "/api.Photo/SwitchLock"
FP = "actual-profile-schema"
SHA = hashlib.sha256(b"photo-request").hexdigest()


@pytest.fixture
def state(tmp_path):
    value = State(tmp_path / "state.db")
    value.save_snapshot("player", b"original", FP)
    value.save_snapshot("other", b"other", FP)
    return value


def invoke(state, callback, identity="1", **changes):
    args = dict(profile="player", schema_sha256=FP, request_id=identity,
                request_sha256=SHA, path=PATH, callback=callback)
    args.update(changes)
    return state.mutate_preference_snapshot(**args)


def dump(state):
    with state.connect() as db:
        return tuple(db.iterdump())


def receipt(raw):
    return raw + b"+toggled", b"exact-response-with-unknown-fields"


def test_toggle_receipt_survives_later_actions_and_restart_without_retoggling(state):
    token, identity = state.login("player")
    first = invoke(state, receipt)
    state.mutate_snapshot("player", FP, lambda _: b"later-photo-and-profile-state")
    restarted = State(state.path)
    before = dump(restarted)
    assert invoke(restarted, lambda _: pytest.fail("toggle retried")) == first
    assert restarted.snapshot("player") == (b"later-photo-and-profile-state", FP)
    assert restarted.profile("player") == identity and restarted.authenticated(token, "player")
    assert dump(restarted) == before


def test_concurrent_same_identity_toggles_exactly_once_and_distinct_identities_toggle_each(state):
    calls = []
    def toggle(raw):
        calls.append(raw)
        return receipt(raw)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: invoke(state, toggle), range(16)))
    assert len(calls) == 1 and len(set(results)) == 1
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda value: invoke(state, toggle, str(value)), range(2, 6)))
    assert len(calls) == 5
    assert state.snapshot("player")[0] == b"original" + b"+toggled" * 5


def test_body_conflict_is_rejected_but_other_route_and_profile_are_independent(state):
    invoke(state, receipt)
    before = dump(state)
    with pytest.raises(AttemptConflict):
        invoke(state, lambda _: pytest.fail("conflicting callback"),
               request_sha256=hashlib.sha256(b"different").hexdigest())
    assert dump(state) == before
    invoke(state, receipt, path="/api.Photo/OtherToggle")
    invoke(state, receipt, profile="other")
    assert state.snapshot("player")[0].count(b"+toggled") == 2
    assert state.snapshot("other")[0].count(b"+toggled") == 1


def test_receipt_insert_failure_rolls_back_the_snapshot(state):
    before = state.snapshot("player")
    with state.connect() as db:
        db.execute("CREATE TRIGGER reject_preference BEFORE INSERT ON preference_receipts "
                   "BEGIN SELECT RAISE(ABORT,'receipt rejected'); END")
    with pytest.raises(sqlite3.IntegrityError):
        invoke(state, receipt)
    assert state.snapshot("player") == before
    with state.connect() as db:
        assert db.execute("SELECT count(*) FROM preference_receipts").fetchone()[0] == 0
        db.execute("DROP TRIGGER reject_preference")
    assert invoke(state, receipt) == b"exact-response-with-unknown-fields"


@pytest.mark.parametrize("result", [None, b"not-a-pair", (b"snapshot",), (b"snapshot", "text"),
                                    [b"snapshot", b"response"]])
def test_invalid_callback_results_change_neither_snapshot_nor_receipt(state, result):
    before = dump(state)
    with pytest.raises(ValueError):
        invoke(state, lambda _: result)
    assert dump(state) == before


def test_callback_failure_rolls_back_without_receipt(state):
    before = dump(state)
    def rejected(_):
        raise RuntimeError("invalid photo inventory")
    with pytest.raises(RuntimeError):
        invoke(state, rejected)
    assert dump(state) == before


@pytest.mark.parametrize("changes", [
    {"request_id": None}, {"request_id": "0"}, {"request_id": "01"},
    {"request_id": str(1 << 64)}, {"request_sha256": "not-a-hash"},
    {"path": ""}, {"path": "/unknown"}, {"schema_sha256": ""},
    {"schema_sha256": "another-schema"}, {"profile": "missing"},
])
def test_invalid_identity_and_context_never_run_the_toggle(state, changes):
    before = dump(state)
    with pytest.raises(ValueError):
        invoke(state, lambda _: pytest.fail("invalid callback invoked"), **changes)
    assert dump(state) == before


def test_snapshot_import_clears_own_receipts_and_preserves_other_account_receipts(state):
    invoke(state, receipt)
    invoke(state, receipt, profile="other")
    state.save_snapshot("player", b"replacement", FP)
    with state.connect() as db:
        assert [(row["profile"], row["request_id"]) for row in db.execute(
            "SELECT profile,request_id FROM preference_receipts")] == [("other", "1")]
    assert invoke(state, receipt) == b"exact-response-with-unknown-fields"
    assert state.snapshot("player")[0] == b"replacement+toggled"
    assert invoke(state, lambda _: pytest.fail("other receipt lost"), profile="other")


def test_cached_receipt_schema_corruption_fails_without_callback_or_state_change(state):
    invoke(state, receipt)
    with state.connect() as db:
        db.execute("UPDATE preference_receipts SET schema_sha256='wrong' WHERE profile='player'")
    before = dump(state)
    with pytest.raises(ValueError):
        invoke(state, lambda _: pytest.fail("corrupt receipt callback"))
    assert dump(state) == before
