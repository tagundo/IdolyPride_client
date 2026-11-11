"""First-live settlement tests use independent card fixtures and real 6.1.1 wire types.

A small fake calculator isolates transaction/economy assertions from scoring;
separate optional integration tests exercise the actual native calculator.
"""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from idoly_local import main_live as module
from idoly_local.rpc import RpcCode, RpcFailure
from idoly_local.schema import Schema
from idoly_local.state import State
from test_card_progression import synthetic_fixture

USER = '/api.User/Get'
START = '/api.Quest/Start'
QUEST = 'qt-main-1-001-01'
UNKNOWN = b'\x80\x4b\x7b'
NOW = 1794234000000


@pytest.fixture(scope='module')
def schema():
    path = Path(__file__).resolve().parents[1] / 'data/protocol/idolypride-6.1.1.pb'
    if not path.is_file():
        pytest.skip('Recovered 6.1.1 descriptor is not installed')
    return Schema.from_descriptor_set(path)


class Calculator:
    def __init__(self, schema):
        self.schema, self.score, self.calls = schema, 5000, []
        self.mutation = None

    def simulate(self, prepared):
        self.calls.append(prepared)
        result = self.schema.response_type(START)().result
        result.cleared = self.score >= prepared['clear_score']
        result.preChart.SetInParent()
        result.charts.add(number=1)
        player = result.userInfos.add(index=1, userId=prepared['public_id'], name=prepared['name'])
        for index, card_id in enumerate(prepared['cards'], 1):
            player.userDeck.cards.add(index=index, cardId=card_id)
            player.userResult.cardResults.add(cardId=card_id, totalScore=self.score // 5 + (self.score % 5 if index == 1 else 0))
        player.userResult.score = self.score
        if self.mutation:
            self.mutation(result)
        return result.SerializeToString()


@pytest.fixture
def game(schema, tmp_path, monkeypatch):
    _, master, rows, card = synthetic_fixture(tmp_path, schema)
    rows['Setting'][0].update(goldLimit='99999999999', itemLimit='99999999999',
                             freeStoneLimit='9999999', accessoryLimit='99999999')
    rows.update({
        'Quest': [{'id': QUEST, 'areaId': 'area-main-001', 'clearScore': '3000', 'liveSkipType': 2,
                   'rewardManagerExp': 50, 'rewardCardExp': 40, 'clearRewardId': 'rd-main-quest-001-01',
                   'musicId': 'music-hsm-006', 'musicChartPatternId': 'chart-hsm-006-002',
                   'stageId': 'stage-live-house-00-00'},
                  {'id': 'qt-main-1-001-02', 'areaId': 'area-main-001', 'clearScore': '5400', 'liveSkipType': 2,
                   'rewardManagerExp': 65, 'rewardCardExp': 57, 'clearRewardId': 'rd-main-quest-001-02',
                   'musicId': 'music-sun-001', 'musicChartPatternId': 'chart-sun-001-002',
                   'stageId': 'stage-live-house-00-00'},
                  {'id': 'qt-main-1-001-03', 'areaId': 'area-main-001', 'clearScore': '10000', 'liveSkipType': 2,
                   'rewardManagerExp': 85, 'rewardCardExp': 74, 'clearRewardId': 'rd-main-quest-001-03',
                   'musicId': 'music-moon-004', 'musicChartPatternId': 'chart-moon-004-002',
                   'stageId': 'stage-live-house-00-00'}],
        'Area': [{'id': 'area-main-001', 'type': 1,
                  'questIds': [QUEST, 'qt-main-1-001-02', 'qt-main-1-001-03']}],
        'Stage': [{'id': 'stage-live-house-00-00'}],
        'Music': [{'id': identity} for identity in ('music-hsm-006', 'music-sun-001', 'music-moon-004')],
        'Reward': [{'id': 'rd-main-quest-001-01', 'resources': [
            {'resourceType': 1, 'resourceId': 'item-card_enhance', 'amount': 290},
            {'resourceType': 8, 'amount': 500}, {'resourceType': 15, 'amount': 50},
            {'resourceType': 3, 'resourceId': 'ac-1-visual-02', 'amount': 1}]},
            {'id': 'rd-main-quest-001-02', 'resources': [
                {'resourceType': 1, 'resourceId': 'item-card_enhance', 'amount': 590},
                {'resourceType': 8, 'amount': 500}, {'resourceType': 15, 'amount': 50},
                {'resourceType': 3, 'resourceId': 'ac-1-vocal-02', 'amount': 1}]},
            {'id': 'rd-main-quest-001-03', 'resources': [
                {'resourceType': 1, 'resourceId': 'item-card_enhance', 'amount': 890},
                {'resourceType': 8, 'amount': 500}, {'resourceType': 15, 'amount': 50},
                {'resourceType': 1, 'resourceId': 'item-photo_shooting-01', 'amount': 1}]}],
        'Accessory': [{'id': 'ac-1-visual-02'}, {'id': 'ac-1-vocal-02'}],
    })
    rows['Item'].append({'id': 'item-photo_shooting-01'})
    rows['ManagerLevel'][2]['maxCardLevel'] = 12
    rows['ManagerLevel'].append({'level': 4, 'requiredExp': '200', 'maxCardLevel': 12})
    base = dict(rows['Card'][0])
    rows['Card'] = [{**base, 'id': f'card-{i}', 'characterId': f'char-{i}'} for i in range(1, 6)]
    for table, values in rows.items():
        (master / (table + '.json')).write_text(json.dumps(values))
    (master / '!version.txt').write_text('independent-master')
    state = State(tmp_path / 'state.db')
    identity = state.ensure_profile('player')
    snapshot = schema.response_type(USER)()
    snapshot.user.name, snapshot.user.managerLevel = 'Local manager', 1
    snapshot.user.cardSupportLevel = 7
    snapshot.userPublic.serverUserId, snapshot.userPublic.publicUserId = identity['server_id'], identity['public_id']
    snapshot.decks.add(number=1, name='Saved unit')
    for i in range(1, 6):
        owned = snapshot.cards.add()
        owned.CopyFrom(card)
        owned.cardId = f'card-{i}'
        owned.MergeFromString(UNKNOWN)
        snapshot.deckPositions.add(number=1, position=i, cardId=owned.cardId)
        snapshot.characters.add(characterId=f'char-{i}', lightFanAmount=100 + i)
    snapshot.items.add(itemId='item-card_enhance', amount=100)
    snapshot.items.add(itemId='unrelated', amount=42)
    snapshot.points.add(pointType=1, amount=7)
    snapshot.balance.freeBalance, snapshot.balance.paidBalance = 100, 17
    snapshot.totalCount.pointGoldAmount = 8
    snapshot.areas.add(areaId='area-main-001')
    snapshot.tutorials.add(tutorialType=1, step=150)
    snapshot.MergeFromString(UNKNOWN)
    state.save_snapshot('player', snapshot.SerializeToString(), schema.fingerprint, starter_version=4)
    state.save_snapshot('other', b'other-preserved', schema.fingerprint)
    state.mutate_snapshot('player', schema.fingerprint, lambda raw: raw, setting_info=b'opaque-settings')
    state.mutate_lesson_snapshot('player', schema.fingerprint, lambda raw, _: (raw, b'opaque-clock'))
    token, _ = state.login('player')
    calculator = Calculator(schema)
    def prepare(_schema, _master, current, quest_id, number, seed):
        positions = sorted((p for p in current.deckPositions if p.number == number), key=lambda p: p.position)
        if [p.position for p in positions] != list(range(1, 6)):
            raise RpcFailure(RpcCode.FAILED_PRECONDITION, 'incomplete unit')
        if any(p.photoIds or p.part1AccessoryId or p.part2AccessoryId for p in positions):
            raise RpcFailure(RpcCode.UNIMPLEMENTED, 'bonuses not supported')
        return {'public_id': current.userPublic.publicUserId, 'name': current.user.name,
                'cards': [p.cardId for p in positions], 'seed': seed,
                'clear_score': int(next(row for row in rows['Quest'] if row['id'] == quest_id)['clearScore'])}
    monkeypatch.setattr(module, 'prepare_main_live', prepare)
    monkeypatch.setattr(module.time, 'time_ns', lambda: NOW * 1000000)
    provider = module.MainLives(schema, state, 'player', master, calculator, enabled=True)
    return SimpleNamespace(provider=provider, state=state, schema=schema, master=master,
                           rows=rows, engine=calculator, token=token)


def call(game, identity='1', **kwargs):
    args = dict(questId=QUEST, deckNumber=1, playCount=1, buddyDeckName='Saved unit')
    args.update(kwargs)
    raw = game.schema.request_type(START)(**args).SerializeToString()
    return game.schema.response_type(START).FromString(game.provider.handle(START, raw, identity))


def current(game):
    return game.schema.response_type(USER).FromString(game.state.snapshot('player')[0])


def change(game, callback):
    def edit(raw):
        value = game.schema.response_type(USER).FromString(raw)
        callback(value)
        return value.SerializeToString()
    game.state.mutate_snapshot('player', game.schema.fingerprint, edit)


def dump(game):
    with game.state.connect() as db:
        return tuple(db.iterdump())


def rewrite(game, table):
    (game.master / (table + '.json')).write_text(json.dumps(game.rows[table]))
    game.provider.catalog.loaded.clear()


def test_first_clear_returns_computed_result_and_exact_local_deltas(game):
    before = current(game)
    response = call(game)
    snapshot = current(game)
    assert response.questId == QUEST and response.result.userInfos[0].userResult.score == 5000
    assert response.result.cleared and response.rankType == response.rankPlus == response.highestRank == 0
    assert [(r.rankType, r.thresholdScore) for r in response.rankPatterns] == [(3, 3600), (2, 3000), (1, 0)]
    assert [(r.resourceType, r.resourceId, r.amountI64, r.beforeAmount, r.afterAmount) for r in response.reward.clearRewards] == [
        (1, 'item-card_enhance', 290, 100, 390), (8, '', 500, 7, 507),
        (15, '', 50, 100, 150), (3, 'ac-1-visual-02', 1, 0, 1)]
    assert (snapshot.user.managerExp, snapshot.user.managerLevel) == (50, 2)
    assert snapshot.balance.freeBalance == 150 and snapshot.balance.paidBalance == 17
    assert snapshot.totalCount.pointGoldAmount == 508
    assert len(response.reward.rewardCards) == 5
    assert all((r.exp, r.funAmount, r.isExpTruncated) == (40, 0, False) for r in response.reward.rewardCards)
    assert all((c.level, c.totalExp, c.vocal, c.lastEnhanceTime) == (2, 40, 132, 456) for c in snapshot.cards)
    assert snapshot.quests[0].lastClearedTime == snapshot.areas[0].lastClearedTime == NOW
    assert snapshot.quests[0].highestScore == response.highestScore == 5000
    assert snapshot.areas[0].clearQuestCount == snapshot.areas[0].dailyClearCount == 1
    assert [c.SerializeToString() for c in snapshot.characters] == [c.SerializeToString() for c in before.characters]
    assert snapshot.tutorials == before.tutorials and snapshot.user.cardSupportLevel == 7
    assert UNKNOWN in game.state.snapshot('player')[0] and all(UNKNOWN in c.SerializeToString() for c in snapshot.cards)
    assert game.state.settings('player') == (b'opaque-settings', game.schema.fingerprint)
    assert game.state.lesson_progress('player') == (b'opaque-clock', game.schema.fingerprint)
    assert game.state.snapshot('other')[0] == b'other-preserved'
    assert game.state.authenticated(game.token, 'player')


def test_same_id_is_exact_cached_response_and_new_id_replay_has_no_rewards_or_xp(game):
    first = call(game).SerializeToString()
    after = dump(game)
    game.engine.score = 6000
    assert call(game).SerializeToString() == first and dump(game) == after and len(game.engine.calls) == 1
    replay = call(game, '2')
    snapshot = current(game)
    assert len(game.engine.calls) == 2 and replay.highestScore == 6000
    assert not replay.reward.clearRewards and not replay.reward.rewardCards
    assert snapshot.user.managerExp == 50 and all(c.totalExp == 40 for c in snapshot.cards)
    assert snapshot.balance.freeBalance == 150 and snapshot.items[0].amount == 390
    assert snapshot.areas[0].clearQuestCount == 1 and snapshot.areas[0].dailyClearCount == 2
    restarted = module.MainLives(game.schema, State(game.state.path), 'player', game.master, None, True)
    request = game.schema.request_type(START)(questId=QUEST, deckNumber=1, playCount=1, buddyDeckName='Saved unit')
    assert restarted.handle(START, request.SerializeToString(), '1') == first


def test_parallel_first_clear_new_ids_reward_once_and_same_id_calculates_once(game):
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda i: call(game, str(i)), (1, 1, 2, 3)))
    assert len(game.engine.calls) == 3
    assert sum(bool(r.reward.clearRewards) for r in [results[0], results[2], results[3]]) == 1
    assert current(game).user.managerExp == 50 and current(game).areas[0].clearQuestCount == 1


def test_failed_calculation_is_real_failure_without_state_reward_or_xp_and_can_retry_new_id(game):
    game.engine.score = 0
    before = game.state.snapshot('player')
    response = call(game)
    assert not response.result.cleared and not response.reward.clearRewards and not response.reward.rewardCards
    assert game.state.snapshot('player') == before and len(game.engine.calls) == 1
    game.engine.score = 5000
    assert not call(game).result.cleared and len(game.engine.calls) == 1
    assert call(game, '2').result.cleared and current(game).user.managerExp == 50


def test_failure_preserves_even_noncanonical_unknown_field_wire_order(game):
    game.state.mutate_snapshot('player', game.schema.fingerprint, lambda raw: UNKNOWN + raw)
    before = game.state.snapshot('player')
    game.engine.score = 0
    call(game)
    assert game.state.snapshot('player') == before


def test_completing_imported_area_updates_only_real_clear_character_references(game):
    def previously_cleared(snapshot):
        snapshot.areas[0].clearQuestCount = 2
        snapshot.quests.add(questId='qt-main-1-001-02', lastClearedTime=NOW - 1000)
        snapshot.quests.add(questId='qt-main-1-001-03', lastClearedTime=NOW - 1000)
    change(game, previously_cleared)
    response = call(game)
    assert current(game).areas[0].clearQuestCount == 3
    assert list(current(game).user.questMainAreaLastClearCharacterIds) == [f'char-{i}' for i in range(1, 6)]
    assert response.commonResponse.updatedData.user == current(game).user


def test_new_day_replay_resets_daily_counts_and_preserves_first_clear_receipt(game, monkeypatch):
    call(game)
    monkeypatch.setattr(module.time, 'time_ns', lambda: (NOW + 86400000) * 1000000)
    response = call(game, '2')
    snapshot = current(game)
    assert snapshot.areas[0].dailyClearCount == snapshot.quests[0].dailyClearCount == 1
    assert snapshot.areas[0].clearQuestCount == 1 and snapshot.user.managerExp == 50
    assert not response.reward.clearRewards and not response.reward.rewardCards


def test_partial_card_xp_and_manager_cap_truncate_without_spending_items(game):
    change(game, lambda s: [setattr(c, 'totalExp', 15) for c in s.cards])
    response = call(game)
    assert all((c.level, c.totalExp) == (2, 55) for c in current(game).cards)
    assert all(r.exp == 40 and not r.isExpTruncated for r in response.reward.rewardCards)
    assert current(game).items[0].amount == 390


def test_card_experience_cap_uses_post_reward_manager_level(game):
    game.rows['ManagerLevel'][1]['maxCardLevel'] = 2
    rewrite(game, 'ManagerLevel')
    change(game, lambda s: [setattr(c, 'totalExp', 15) for c in s.cards])
    response = call(game)
    assert all((c.level, c.totalExp) == (2, 40) for c in current(game).cards)
    assert all(r.exp == 25 and r.isExpTruncated for r in response.reward.rewardCards)


@pytest.mark.parametrize('kwargs,code', [
    ({'questId': ''}, RpcCode.INVALID_ARGUMENT), ({'deckNumber': 0}, RpcCode.INVALID_ARGUMENT),
    ({'playCount': 0}, RpcCode.INVALID_ARGUMENT), ({'questId': 'other'}, RpcCode.UNIMPLEMENTED),
    ({'playCount': 2}, RpcCode.UNIMPLEMENTED),
    ({'isAuto': True}, RpcCode.UNIMPLEMENTED), ({'useDailyTicket': True}, RpcCode.UNIMPLEMENTED),
    ({'userBuddyDeckPositions': [{'cardId': 'borrowed'}]}, RpcCode.UNIMPLEMENTED),
    ({'buddyDeckName': 'Borrowed'}, RpcCode.UNIMPLEMENTED),
])
@pytest.mark.parametrize('is_skip', [False, True])
def test_unsupported_requests_never_calculate_or_write(game, kwargs, code, is_skip):
    before = dump(game)
    with pytest.raises(RpcFailure) as error:
        call(game, isSkip=is_skip, **kwargs)
    assert error.value.code == code and dump(game) == before and not game.engine.calls


@pytest.mark.parametrize('mutation', ['item-limit', 'gold-limit', 'stone-limit', 'accessory-limit',
    'reward-pin', 'bad-manager', 'ambiguous-item', 'area-count', 'release-boundary', 'negative-xp', 'clock-rollback'])
def test_invalid_settlement_rolls_back_snapshot_and_attempt_receipt(game, mutation):
    if mutation.endswith('-limit'):
        field = {'item-limit': 'itemLimit', 'gold-limit': 'goldLimit', 'stone-limit': 'freeStoneLimit',
                 'accessory-limit': 'accessoryLimit'}[mutation]
        game.rows['Setting'][0][field] = '1'
        rewrite(game, 'Setting')
        if mutation == 'accessory-limit':
            change(game, lambda s: s.accessories.add(accessoryId='ac-1-visual-02', amount=1))
    elif mutation == 'reward-pin':
        game.rows['Reward'][0]['resources'][0]['amount'] = 291
        rewrite(game, 'Reward')
    elif mutation == 'bad-manager':
        change(game, lambda s: setattr(s.user, 'managerLevel', 3))
    elif mutation == 'ambiguous-item':
        change(game, lambda s: s.items.add(itemId='item-card_enhance', amount=1))
    elif mutation == 'area-count':
        change(game, lambda s: setattr(s.areas[0], 'clearQuestCount', 1))
    elif mutation == 'release-boundary':
        game.rows['CardLevelRelease'][1]['level'] = 2
        rewrite(game, 'CardLevelRelease')
    elif mutation == 'negative-xp':
        change(game, lambda s: setattr(s.cards[0], 'totalExp', -1))
    else:
        change(game, lambda s: setattr(s.areas[0], 'lastClearedTime', NOW + 1))
    before = dump(game)
    with pytest.raises(RpcFailure):
        call(game)
    assert dump(game) == before and game.state.main_live_attempt('player', '1') is None


@pytest.mark.parametrize('mutation', [
    lambda r: setattr(r, 'cleared', False),
    lambda r: setattr(r.userInfos[0], 'userId', 'foreign'),
    lambda r: setattr(r.userInfos[0].userResult.cardResults[0], 'totalScore', 999),
    lambda r: r.ClearField('charts'),
    lambda r: r.ClearField('preChart'),
])
def test_inconsistent_engine_result_is_not_settled(game, mutation):
    game.engine.mutation = mutation
    before = dump(game)
    with pytest.raises(RpcFailure) as error:
        call(game)
    assert error.value.code == RpcCode.INTERNAL and dump(game) == before


def test_default_disabled_and_missing_engine_do_not_fake_a_live(game):
    disabled = module.MainLives(game.schema, game.state, 'player', game.master)
    before = dump(game)
    assert disabled.handle(START, b'bad', None) is None
    assert game.provider.handle('/api.Tutorial/StartQuest', b'', '1') is None
    game.provider.engine = None
    with pytest.raises(RpcFailure) as error:
        call(game)
    assert error.value.code == RpcCode.FAILED_PRECONDITION and dump(game) == before


def test_request_id_body_conflict_and_malformed_request_are_atomic(game):
    call(game)
    before = dump(game)
    with pytest.raises(RpcFailure) as error:
        call(game, buddyDeckName='')
    assert error.value.code == RpcCode.INVALID_ARGUMENT and dump(game) == before
    for identity, raw in [('01', b''), ('2', b'\x0a\x04x')]:
        with pytest.raises(RpcFailure) as error:
            game.provider.handle(START, raw, identity)
        assert error.value.code == RpcCode.INVALID_ARGUMENT and dump(game) == before
