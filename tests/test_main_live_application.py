"""Real encrypted HTTP/2 coverage for opt-in live settlement and retry headers."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json

import grpc
import pytest

from idoly_local import codec
from idoly_local.application import Application
from idoly_local.catalog import FixtureStore
from idoly_local.h2_server import create_server

from test_main_live import QUEST, START, USER, current, dump, game, schema


@contextmanager
def connected(game, directory, *, enabled=True):
    application = Application(game.schema, game.state, FixtureStore(directory, game.schema),
        profile='player', master_dir=game.master, experimental_main_live=enabled,
        live_engine=game.engine)
    server = create_server(application, port=0).start()
    try:
        with grpc.insecure_channel(f'127.0.0.1:{server.port}') as channel:
            grpc.channel_ready_future(channel).result(timeout=3)
            def invoke(path=START, *, raw=None, headers=(('x-app-request-id', '1'),), authenticated=True):
                if raw is None:
                    raw = game.schema.request_type(START)(questId=QUEST, deckNumber=1, playCount=1,
                        buddyDeckName='Saved unit').SerializeToString() if path == START else b''
                metadata = ((('x-auth-token', game.token),) if authenticated else ()) + tuple(headers)
                call = channel.unary_unary(path, request_serializer=codec.encode, response_deserializer=codec.decode)
                return call(raw, metadata=metadata, timeout=5)
            yield application, invoke
    finally:
        server.stop()


def test_default_off_keeps_ordinary_quest_unimplemented_without_loading_or_mutating(game, tmp_path, monkeypatch):
    from idoly_local import main_live
    monkeypatch.setattr(main_live, 'MainLives', lambda *a, **k: pytest.fail('default-off constructed provider'))
    before = dump(game)
    with connected(game, tmp_path / 'fixtures', enabled=False) as (application, invoke):
        assert application.main_lives is None
        # Old API calls remain compatible and need no new header.
        assert invoke(USER, headers=()) == game.state.snapshot('player')[0]
        response = game.schema.response_type('/api.System/Check').FromString(
            invoke('/api.System/Check', headers=(), authenticated=False))
        assert not response.maintenanceInfo.inMaintenance
        for headers in ((), (('x-app-request-id', '01'),), (('x-app-request-id', '1'), ('x-app-request-id', '1'))):
            with pytest.raises(grpc.RpcError) as error:
                invoke(headers=headers)
            assert error.value.code() == grpc.StatusCode.UNIMPLEMENTED
    assert dump(game) == before and not game.engine.calls


def test_authenticated_first_clear_cached_retry_new_attempt_and_restart_over_encrypted_h2(game, tmp_path):
    with connected(game, tmp_path / 'fixtures') as (_, invoke):
        first = invoke()
        response = game.schema.response_type(START).FromString(first)
        assert response.result.cleared and response.result.userInfos[0].userResult.score == 5000
        assert [(r.resourceType, r.amountI64) for r in response.reward.clearRewards] == [(1, 290), (8, 500), (15, 50), (3, 1)]
        assert all(r.exp == 40 and r.funAmount == 0 for r in response.reward.rewardCards)
        assert response.commonResponse.HasField('updatedData') and response.commonResponse.HasField('deletedData')
        assert invoke(USER, headers=()) == game.state.snapshot('player')[0]
        snapshot = current(game)
        assert snapshot.user.managerExp == 50 and snapshot.user.managerLevel == 2
        assert snapshot.balance.freeBalance == 150 and snapshot.balance.paidBalance == 17
        assert all(c.totalExp == 40 and c.level == 2 for c in snapshot.cards)
        after_first = dump(game)
        game.engine.score = 6000
        assert invoke() == first and dump(game) == after_first and len(game.engine.calls) == 1
        replay = game.schema.response_type(START).FromString(invoke(headers=(('x-app-request-id', '2'),)))
        assert replay.result.userInfos[0].userResult.score == replay.highestScore == 6000
        assert not replay.reward.clearRewards and not replay.reward.rewardCards
        assert current(game).user.managerExp == 50 and current(game).areas[0].clearQuestCount == 1
        after_replay = dump(game)
    # A new Application/server instance still returns the exact committed result.
    with connected(game, tmp_path / 'fixtures') as (_, invoke):
        assert invoke() == first and dump(game) == after_replay and len(game.engine.calls) == 2


def test_authentication_happens_before_request_identity_validation(game, tmp_path):
    before = dump(game)
    with connected(game, tmp_path / 'fixtures') as (_, invoke):
        for headers in ((), (('x-app-request-id', '1'),)):
            with pytest.raises(grpc.RpcError) as error:
                invoke(headers=headers, authenticated=False)
            assert error.value.code() == grpc.StatusCode.UNAUTHENTICATED
    assert dump(game) == before and not game.engine.calls


@pytest.mark.parametrize('headers', [(), (('x-app-request-id', ''),), (('x-app-request-id', '0'),),
    (('x-app-request-id', '01'),), (('x-app-request-id', '+1'),),
    (('x-app-request-id', str(1 << 64)),),
    (('x-app-request-id', '1'), ('x-app-request-id', '1')),
    (('x-app-request-id', '1'), ('x-app-request-id', '2'))])
def test_missing_duplicate_or_noncanonical_request_identity_cannot_settle(game, tmp_path, headers):
    before = dump(game)
    with connected(game, tmp_path / 'fixtures') as (_, invoke):
        with pytest.raises(grpc.RpcError) as error:
            invoke(headers=headers)
        assert error.value.code() == grpc.StatusCode.INVALID_ARGUMENT
    assert dump(game) == before and not game.engine.calls


def test_malformed_body_conflicting_retry_and_unsupported_mode_leave_atomic_receipt_unchanged(game, tmp_path):
    with connected(game, tmp_path / 'fixtures') as (_, invoke):
        before = dump(game)
        with pytest.raises(grpc.RpcError) as malformed:
            invoke(raw=b'\x0a\x80')
        assert malformed.value.code() == grpc.StatusCode.INVALID_ARGUMENT and dump(game) == before
        first = invoke()
        after = dump(game)
        changed = game.schema.request_type(START)(questId=QUEST, deckNumber=1, playCount=1).SerializeToString()
        with pytest.raises(grpc.RpcError) as conflict:
            invoke(raw=changed)
        assert conflict.value.code() == grpc.StatusCode.INVALID_ARGUMENT and dump(game) == after
        unsupported = game.schema.request_type(START)(questId=QUEST, deckNumber=1, playCount=1, isAuto=True).SerializeToString()
        with pytest.raises(grpc.RpcError) as not_implemented:
            invoke(raw=unsupported, headers=(('x-app-request-id', '2'),))
        assert not_implemented.value.code() == grpc.StatusCode.UNIMPLEMENTED
        assert dump(game) == after and invoke() == first and len(game.engine.calls) == 1


def test_resource_cap_failure_leaves_no_attempt_and_corrected_request_can_settle_once(game, tmp_path):
    game.rows['Setting'][0]['itemLimit'] = '100'
    (game.master / 'Setting.json').write_text(json.dumps(game.rows['Setting']))
    before = dump(game)
    with connected(game, tmp_path / 'fixtures') as (_, invoke):
        with pytest.raises(grpc.RpcError) as error:
            invoke()
        assert error.value.code() == grpc.StatusCode.FAILED_PRECONDITION
        assert dump(game) == before and game.state.main_live_attempt('player', '1') is None
    game.rows['Setting'][0]['itemLimit'] = '99999999999'
    (game.master / 'Setting.json').write_text(json.dumps(game.rows['Setting']))
    with connected(game, tmp_path / 'fixtures') as (_, invoke):
        response = game.schema.response_type(START).FromString(invoke())
        assert response.result.cleared and len(response.reward.clearRewards) == 4
        assert current(game).items[0].amount == 390


def test_parallel_encrypted_same_id_is_one_calculation_and_one_complete_response(game, tmp_path):
    with connected(game, tmp_path / 'fixtures') as (_, invoke):
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(lambda _: invoke(), range(8)))
    assert len(set(results)) == 1 and len(game.engine.calls) == 1
    assert current(game).user.managerExp == 50 and current(game).items[0].amount == 390


@pytest.mark.parametrize('value', [None, 0, 1, 'true', [], {}])
def test_application_requires_explicit_boolean_opt_in_before_other_work(game, tmp_path, value):
    before = dump(game)
    with pytest.raises(ValueError, match='explicit boolean'):
        Application(game.schema, game.state, FixtureStore(tmp_path / 'fixtures', game.schema),
            master_dir=game.master, experimental_main_live=value, live_engine=game.engine)
    assert dump(game) == before and not game.engine.calls
