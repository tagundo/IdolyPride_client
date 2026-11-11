"""Synthetic economy and authorization checks for the three pinned main lives."""
from concurrent.futures import ThreadPoolExecutor
import hashlib

import pytest

from idoly_local.main_live import MainLives
from idoly_local.rpc import RpcCode, RpcFailure
from idoly_local.state import State
from test_main_live import schema, game, call, current, change, dump, rewrite


START = '/api.Quest/Start'
QUESTS = ('qt-main-1-001-01', 'qt-main-1-001-02', 'qt-main-1-001-03')
NOW = 1794234000000


def clear_prefix(game, count):
    game.engine.score = 12000
    return [call(game, str(index + 1), questId=quest)
            for index, quest in enumerate(QUESTS[:count])]


def economy(snapshot):
    return (snapshot.user.SerializeToString(), snapshot.balance.SerializeToString(),
            snapshot.totalCount.SerializeToString(),
            tuple(row.SerializeToString() for row in snapshot.cards),
            tuple(row.SerializeToString() for row in snapshot.items),
            tuple(row.SerializeToString() for row in snapshot.points),
            tuple(row.SerializeToString() for row in snapshot.accessories))


def test_first_area_chain_uses_each_quests_rewards_xp_and_completion(game):
    game.engine.score = 12000
    expected_rewards = (
        [(1, 'item-card_enhance', 290, 100, 390), (8, '', 500, 7, 507),
         (15, '', 50, 100, 150), (3, 'ac-1-visual-02', 1, 0, 1)],
        [(1, 'item-card_enhance', 590, 390, 980), (8, '', 500, 507, 1007),
         (15, '', 50, 150, 200), (3, 'ac-1-vocal-02', 1, 0, 1)],
        [(1, 'item-card_enhance', 890, 980, 1870), (8, '', 500, 1007, 1507),
         (15, '', 50, 200, 250), (1, 'item-photo_shooting-01', 1, 0, 1)],
    )
    for index, (quest, rewards, manager_xp, card_xp, gain) in enumerate(zip(
            QUESTS, expected_rewards, (50, 115, 200), (40, 97, 171), (40, 57, 74)), 1):
        response = call(game, str(index), questId=quest)
        snapshot = current(game)
        assert response.questId == quest and response.result.cleared
        assert response.result.userInfos[0].userResult.score == 12000
        assert [(r.resourceType, r.resourceId, r.amountI64, r.beforeAmount, r.afterAmount)
                for r in response.reward.clearRewards] == rewards
        assert (snapshot.user.managerExp, snapshot.user.managerLevel) == (manager_xp, index + 1)
        assert all(card.totalExp == card_xp for card in snapshot.cards)
        assert len(response.reward.rewardCards) == 5
        assert all((row.exp, row.isExpTruncated) == (gain, False)
                   for row in response.reward.rewardCards)
        assert [(row.questId, row.lastClearedTime, row.dailyClearCount)
                for row in snapshot.quests] == [(key, NOW, 1) for key in QUESTS[:index]]
        assert snapshot.areas[0].clearQuestCount == snapshot.areas[0].dailyClearCount == index
        expected_owners = [f'char-{i}' for i in range(1, 6)] if index == 3 else []
        assert list(snapshot.user.questMainAreaLastClearCharacterIds) == expected_owners
    assert current(game).balance.paidBalance == 17
    assert current(game).totalCount.pointGoldAmount == 1508
    assert response.commonResponse.updatedData.user == current(game).user


@pytest.mark.parametrize('case', (
    '02-empty', '03-empty', '03-after01', '02-count-without-clear',
    '02-score-without-clear', '03-only02', '02-duplicate01', '02-aggregate-mismatch',
    '02-negative-clear-time', '02-future-clear-time',
))
def test_later_quests_require_real_consistent_predecessor_history(game, case):
    target = QUESTS[2] if case.startswith('03') else QUESTS[1]
    if case in ('03-after01', '02-duplicate01', '02-aggregate-mismatch',
                '02-negative-clear-time', '02-future-clear-time'):
        clear_prefix(game, 1)
    if case == '02-count-without-clear':
        change(game, lambda s: setattr(s.areas[0], 'clearQuestCount', 1))
    elif case == '02-score-without-clear':
        change(game, lambda s: s.quests.add(questId=QUESTS[0], highestScore=12000))
    elif case == '03-only02':
        def only_second(snapshot):
            snapshot.areas[0].clearQuestCount = 1
            snapshot.quests.add(questId=QUESTS[1], lastClearedTime=NOW - 1)
        change(game, only_second)
    elif case == '02-duplicate01':
        change(game, lambda s: s.quests.add(questId=QUESTS[0], lastClearedTime=NOW - 1))
    elif case == '02-aggregate-mismatch':
        change(game, lambda s: setattr(s.areas[0], 'clearQuestCount', 0))
    elif case in ('02-negative-clear-time', '02-future-clear-time'):
        change(game, lambda s: setattr(s.quests[0], 'lastClearedTime',
                                      -1 if case == '02-negative-clear-time' else NOW + 1))
    before, calls = dump(game), len(game.engine.calls)
    with pytest.raises(RpcFailure) as error:
        call(game, '10', questId=target)
    assert error.value.code == RpcCode.FAILED_PRECONDITION
    assert dump(game) == before and len(game.engine.calls) == calls
    assert game.state.main_live_attempt('player', '10') is None


@pytest.mark.parametrize('quest,predecessors,threshold', ((QUESTS[1], 1, 5400), (QUESTS[2], 2, 10000)))
def test_selected_clear_threshold_failure_is_cached_and_new_id_can_retry(game, quest, predecessors, threshold):
    clear_prefix(game, predecessors)
    before = game.state.snapshot('player')
    game.engine.score = threshold - 1
    failed = call(game, '10', questId=quest).SerializeToString()
    response = game.schema.response_type(START).FromString(failed)
    assert not response.result.cleared
    assert not response.reward.clearRewards and not response.reward.rewardCards
    assert game.state.snapshot('player') == before
    calls, after = len(game.engine.calls), dump(game)
    game.engine.score = threshold
    assert call(game, '10', questId=quest).SerializeToString() == failed
    assert len(game.engine.calls) == calls and dump(game) == after
    cleared = call(game, '11', questId=quest)
    assert cleared.result.cleared and cleared.result.userInfos[0].userResult.score == threshold
    assert current(game).areas[0].clearQuestCount == predecessors + 1


@pytest.mark.parametrize('damage', (
    'reward-type22', 'reward-amount', 'score', 'manager-xp', 'card-xp',
    'music', 'chart', 'quest-condition', 'rank-reward', 'area-order',
    'quest-area', 'area-condition', 'area-extra-quest',
))
def test_second_quest_master_changes_fail_closed_before_calculation(game, damage):
    clear_prefix(game, 1)
    quest = next(row for row in game.rows['Quest'] if row['id'] == QUESTS[1])
    reward = next(row for row in game.rows['Reward'] if row['id'] == 'rd-main-quest-001-02')
    table = 'Quest'
    if damage == 'reward-type22':
        reward['resources'][-1] = {'resourceType': 22, 'resourceId': '', 'amount': 1}
        table = 'Reward'
    elif damage == 'reward-amount':
        reward['resources'][0]['amount'] = 591
        table = 'Reward'
    elif damage == 'score':
        quest['clearScore'] = '3000'
    elif damage == 'manager-xp':
        quest['rewardManagerExp'] = 50
    elif damage == 'card-xp':
        quest['rewardCardExp'] = 40
    elif damage == 'music':
        quest['musicId'] = 'music-hsm-006'
    elif damage == 'chart':
        quest['musicChartPatternId'] = 'chart-hsm-006-002'
    elif damage == 'quest-condition':
        quest['unlockConditionId'] = 'unverified-condition'
    elif damage == 'rank-reward':
        quest['rankAdditionalRewardId'] = 'unverified-reward'
    elif damage == 'quest-area':
        quest['areaId'] = 'area-main-002'
    else:
        table = 'Area'
        if damage == 'area-order':
            game.rows['Area'][0]['questIds'] = [QUESTS[1], QUESTS[0], QUESTS[2]]
        elif damage == 'area-condition':
            game.rows['Area'][0]['unlockConditionId'] = 'unverified-condition'
        else:
            game.rows['Area'][0]['questIds'].append('qt-main-1-002-01')
    rewrite(game, table)
    before, calls = dump(game), len(game.engine.calls)
    with pytest.raises(RpcFailure):
        call(game, '10', questId=QUESTS[1])
    assert dump(game) == before and len(game.engine.calls) == calls
    assert game.state.main_live_attempt('player', '10') is None
    assert all(row.accessoryId for row in current(game).accessories)


def test_real_next_area_quest_remains_outside_the_supported_scope(game):
    before = dump(game)
    with pytest.raises(RpcFailure) as error:
        call(game, questId='qt-main-1-002-01')
    assert error.value.code == RpcCode.UNIMPLEMENTED
    assert dump(game) == before and not game.engine.calls


def test_last_photo_reward_overflow_rolls_back_all_third_clear_deltas_and_receipt(game):
    clear_prefix(game, 2)
    change(game, lambda s: s.items.add(itemId='item-photo_shooting-01', amount=2000))
    game.rows['Setting'][0]['itemLimit'] = '2000'
    rewrite(game, 'Setting')
    before, calls = dump(game), len(game.engine.calls)
    with pytest.raises(RpcFailure):
        call(game, '3', questId=QUESTS[2])
    assert len(game.engine.calls) == calls + 1
    assert dump(game) == before and game.state.main_live_attempt('player', '3') is None
    assert current(game).areas[0].clearQuestCount == 2
    assert current(game).user.managerExp == 115
    game.rows['Setting'][0]['itemLimit'] = '2001'
    rewrite(game, 'Setting')
    assert call(game, '3', questId=QUESTS[2]).result.cleared
    snapshot = current(game)
    assert snapshot.user.managerExp == 200 and snapshot.areas[0].clearQuestCount == 3
    assert next(row.amount for row in snapshot.items if row.itemId == 'item-photo_shooting-01') == 2001


def test_repeats_and_restarted_receipts_preserve_first_clear_economy_and_old01_response(game):
    originals = [response.SerializeToString() for response in clear_prefix(game, 3)]
    assert game.state.main_live_attempt('player', '1')['ruleset'] == 'live-v5'
    before = economy(current(game))
    game.engine.score = 15000
    for identity, quest in (('4', QUESTS[1]), ('5', QUESTS[2])):
        response = call(game, identity, questId=quest)
        assert not response.reward.clearRewards and not response.reward.rewardCards
        assert response.highestScore == 15000 and economy(current(game)) == before
    snapshot = current(game)
    assert snapshot.areas[0].clearQuestCount == 3 and snapshot.areas[0].dailyClearCount == 5
    assert [(row.questId, row.dailyClearCount) for row in snapshot.quests] == [
        (QUESTS[0], 1), (QUESTS[1], 2), (QUESTS[2], 2)]
    game.provider = MainLives(game.schema, State(game.state.path), 'player', game.master, None, True)
    after = dump(game)
    for index, (quest, original) in enumerate(zip(QUESTS, originals), 1):
        assert call(game, str(index), questId=quest).SerializeToString() == original
    assert dump(game) == after


def test_request_identity_cannot_be_reused_for_a_different_supported_quest(game):
    clear_prefix(game, 1)
    before, calls = dump(game), len(game.engine.calls)
    with pytest.raises(RpcFailure) as error:
        call(game, '1', questId=QUESTS[1])
    assert error.value.code == RpcCode.INVALID_ARGUMENT
    assert dump(game) == before and len(game.engine.calls) == calls


def test_existing_live_v5_first_quest_receipt_returns_exact_bytes_without_new_validation(game):
    # Seed an opaque previous-version receipt directly, independently of this
    # provider's current definition/result builder. A retry must not interpret
    # the new stage contract or require an engine to reproduce its old bytes.
    request = game.schema.request_type(START)(questId=QUESTS[0], deckNumber=1,
        playCount=1, buddyDeckName='Saved unit').SerializeToString()
    response = game.schema.response_type(START)(questId=QUESTS[0], highestScore=4321)
    expected = response.SerializeToString() + b'\x80\x4b\x7b'
    game.state.mutate_main_live_snapshot('player', game.schema.fingerprint, '99',
        hashlib.sha256(request).hexdigest(), START, 'independent-master', 'live-v5',
        lambda raw: (raw, expected, 123456, NOW))
    game.rows['Quest'][0]['musicId'] = 'not-currently-supported'
    rewrite(game, 'Quest')
    restarted = MainLives(game.schema, State(game.state.path), 'player', game.master, None, True)
    before = dump(game)
    assert restarted.handle(START, request, '99') == expected
    assert dump(game) == before and not game.engine.calls


def test_concurrent_third_clears_reward_once_and_duplicate_identity_calculates_once(game):
    clear_prefix(game, 2)
    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(lambda identity: call(game, identity, questId=QUESTS[2]), ('3', '3', '4')))
    assert results[0].SerializeToString() == results[1].SerializeToString()
    assert len(game.engine.calls) == 4
    assert sum(bool(result.reward.clearRewards) for result in (results[0], results[2])) == 1
    snapshot = current(game)
    assert snapshot.user.managerExp == 200 and snapshot.areas[0].clearQuestCount == 3
    assert snapshot.areas[0].dailyClearCount == 4
    assert all(card.totalExp == 171 for card in snapshot.cards)
