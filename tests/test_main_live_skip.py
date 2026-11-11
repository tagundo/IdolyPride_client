"""Presentation skip uses actual live calculation and the existing atomic economy."""
from contextlib import closing
from copy import copy
import sqlite3

import pytest

from idoly_local import main_live as module
from idoly_local.rpc import RpcCode, RpcFailure
from idoly_local.state import State
from test_main_live import Calculator, START, call, current, dump, game, rewrite, schema


def test_skip_and_visible_play_have_identical_calculation_and_settlement(game, tmp_path, monkeypatch):
    # Clone the complete pre-play DB so only the request's presentation bit
    # differs. This calculator isolates settlement; separate native integration
    # tests check the real computed success and failure for both modes.
    clone_path = tmp_path / 'skip.db'
    with game.state.connect() as source, closing(sqlite3.connect(clone_path)) as target:
        source.backup(target)
    skipped = copy(game)
    skipped.state, skipped.engine = State(clone_path), Calculator(game.schema)
    skipped.provider = module.MainLives(game.schema, skipped.state, 'player', game.master,
                                       skipped.engine, enabled=True)
    monkeypatch.setattr(module.secrets, 'randbits', lambda _: 123456)
    visible = call(game)
    hidden = call(skipped, isSkip=True)
    assert game.engine.calls == skipped.engine.calls and len(skipped.engine.calls) == 1
    assert hidden.SerializeToString() == visible.SerializeToString()
    assert skipped.state.snapshot('player') == game.state.snapshot('player')
    assert skipped.state.settings('player') == game.state.settings('player')
    assert skipped.state.lesson_progress('player') == game.state.lesson_progress('player')
    # Presentation is still part of request identity; a changed request must
    # never reuse a cached result under the same request ID.
    assert skipped.state.main_live_attempt('player', '1')['request_sha256'] != \
        game.state.main_live_attempt('player', '1')['request_sha256']


def test_skip_retry_restart_and_changed_mode_do_not_duplicate_rewards(game):
    first = call(game, isSkip=True).SerializeToString()
    after = dump(game)
    assert call(game, isSkip=True).SerializeToString() == first
    assert dump(game) == after and len(game.engine.calls) == 1
    with pytest.raises(RpcFailure) as conflict:
        call(game, isSkip=False)
    assert conflict.value.code == RpcCode.INVALID_ARGUMENT and dump(game) == after
    repeated = call(game, '2', isSkip=False)
    assert len(game.engine.calls) == 2 and not repeated.reward.clearRewards and not repeated.reward.rewardCards
    assert current(game).user.managerExp == 50 and all(row.totalExp == 40 for row in current(game).cards)
    restarted = module.MainLives(game.schema, State(game.state.path), 'player', game.master, enabled=True)
    request = game.schema.request_type(START)(questId=module.MAIN_QUEST_ID, deckNumber=1,
        playCount=1, buddyDeckName='Saved unit', isSkip=True)
    assert restarted.handle(START, request.SerializeToString(), '1') == first


def test_skip_retains_a_calculated_failure_without_granting_rewards(game):
    game.engine.score = 0
    before = game.state.snapshot('player')
    response = call(game, isSkip=True)
    assert len(game.engine.calls) == 1 and not response.result.cleared
    assert response.result.userInfos[0].userResult.score == 0
    assert not response.reward.clearRewards and not response.reward.rewardCards
    assert game.state.snapshot('player') == before


@pytest.mark.parametrize('skip_type', [None, 0, 1, 3, 4, '2', 2.0])
def test_skip_requires_the_pinned_first_quest_skip_definition_before_calculation(game, skip_type):
    game.rows['Quest'][0]['liveSkipType'] = skip_type
    rewrite(game, 'Quest')
    before = dump(game)
    with pytest.raises(RpcFailure) as failure:
        call(game, isSkip=True)
    assert failure.value.code == RpcCode.FAILED_PRECONDITION
    assert not game.engine.calls and dump(game) == before
