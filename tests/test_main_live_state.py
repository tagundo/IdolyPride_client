"""A live retry receipt and account settlement must commit exactly once."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import sqlite3

import pytest

from idoly_local.state import AttemptConflict, State

FP = 'test-schema'
SHA = hashlib.sha256(b'request').hexdigest()


@pytest.fixture
def state(tmp_path):
    state = State(tmp_path / 'state.db')
    state.save_snapshot('player', b'original\x80\x4b\x7b', FP, starter_version=4)
    state.save_snapshot('other', b'other', FP)
    return state


def invoke(state, callback, identity='1', **overrides):
    args = dict(profile='player', schema_sha256=FP, request_id=identity,
                request_sha256=SHA, path='/api.Quest/Start', master_version='master',
                ruleset='live-v5', callback=callback)
    args.update(overrides)
    return state.mutate_main_live_snapshot(**args)


def dump(state):
    with state.connect() as db:
        return tuple(db.iterdump())


def receipt(raw):
    return raw + b'+earned', b'exact-response\x80\x4b\x7b', (1 << 64) - 1, 1794234000000


def test_response_and_snapshot_survive_restart_and_retry_without_callback(state):
    calls = []
    def settle(raw):
        calls.append(raw)
        return receipt(raw)
    response = invoke(state, settle)
    assert state.snapshot('player')[0] == b'original\x80\x4b\x7b+earned'
    restarted = State(state.path)
    before = dump(restarted)
    assert invoke(restarted, lambda _: pytest.fail('retry recalculated')) == response
    assert dump(restarted) == before and len(calls) == 1
    saved = restarted.main_live_attempt('player', '1')
    assert saved['seed'] == str((1 << 64) - 1)
    assert saved['started_time'] == 1794234000000 and bytes(saved['response']) == response


def test_parallel_same_request_settles_once_but_distinct_requests_settle_each(state):
    calls = []
    def settle(raw):
        calls.append(raw)
        return receipt(raw)
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: invoke(state, settle), range(16)))
    assert len(calls) == 1 and len(set(results)) == 1
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(lambda i: invoke(state, settle, str(i)), range(2, 6)))
    assert len(calls) == 5 and state.snapshot('player')[0].count(b'+earned') == 5


def test_ordinary_later_actions_do_not_replace_original_retry_projection(state):
    original = invoke(state, receipt)
    state.mutate_snapshot('player', FP, lambda _: b'later-state')
    assert invoke(state, lambda _: pytest.fail('retry invoked')) == original
    assert state.snapshot('player') == (b'later-state', FP)


@pytest.mark.parametrize('change,exception', [
    ({'request_sha256': hashlib.sha256(b'different').hexdigest()}, AttemptConflict),
    ({'path': '/api.Other/Start'}, AttemptConflict),
    ({'schema_sha256': 'different'}, ValueError),
    ({'master_version': 'different'}, ValueError),
    ({'ruleset': 'different'}, ValueError),
])
def test_reused_identity_rejects_different_body_and_context_without_writes(state, change, exception):
    invoke(state, receipt)
    before = dump(state)
    with pytest.raises(exception):
        invoke(state, lambda _: pytest.fail('conflict recalculated'), **change)
    assert dump(state) == before


@pytest.mark.parametrize('identity', [None, '', '0', '01', '+1', '-1', ' 1', '1 ', '1.0', str(1 << 64), 1, True])
def test_identity_requires_positive_canonical_uint64(state, identity):
    before = dump(state)
    with pytest.raises(ValueError):
        invoke(state, receipt, identity)
    assert dump(state) == before


@pytest.mark.parametrize('result', [None, (b'a', b'b'), (b'a', 'b', 1, 1),
    (b'a', b'b', True, 1), (b'a', b'b', -1, 1), (b'a', b'b', 1 << 64, 1),
    (b'a', b'b', 1, 0), (b'a', b'b', 1, 1 << 63), (b'a', b'b', 1, True)])
def test_invalid_callback_output_and_exception_leave_no_receipt(state, result):
    before = dump(state)
    with pytest.raises(ValueError):
        invoke(state, lambda _: result)
    assert dump(state) == before
    def fail(_):
        raise RuntimeError('engine failed')
    with pytest.raises(RuntimeError, match='engine failed'):
        invoke(state, fail)
    assert dump(state) == before


def test_receipt_insert_failure_rolls_back_snapshot_update(state):
    with state.connect() as db:
        db.executescript("CREATE TRIGGER reject_attempt BEFORE INSERT ON main_live_attempts "
                         "BEGIN SELECT RAISE(ABORT,'cannot write receipt'); END;")
    before = dump(state)
    with pytest.raises(sqlite3.IntegrityError, match='cannot write receipt'):
        invoke(state, receipt)
    assert dump(state) == before


def test_settlement_preserves_other_tables_and_import_clears_only_its_receipts(state):
    token, identity = state.login('player')
    other_token, _ = state.login('other')
    state.mutate_snapshot('player', FP, lambda raw: raw, setting_info=b'settings-unknown')
    state.mutate_lesson_snapshot('player', FP, lambda raw, _: (raw, b'clock-unknown'))
    invoke(state, receipt)
    invoke(state, receipt, profile='other')
    assert state.profile('player') == identity and state.authenticated(token, 'player')
    assert state.settings('player') == (b'settings-unknown', FP)
    assert state.lesson_progress('player') == (b'clock-unknown', FP)
    assert state.starter_version('player') == 4
    other_receipt = state.main_live_attempt('other', '1')
    state.save_snapshot('player', b'imported', FP, public_id='new-account')
    assert state.main_live_attempt('player', '1') is None
    assert state.main_live_attempt('other', '1') == other_receipt
    assert state.authenticated(other_token, 'other')
    assert invoke(state, receipt) == b'exact-response\x80\x4b\x7b'
    assert state.snapshot('player')[0] == b'imported+earned'
