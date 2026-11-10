"""Opt-in settlement of one ordinary main live, using computed live-v5 results.

This deliberately implements no fan, music-mastery or mission rewards. It is
an experimental first-quest slice, not a replacement for all live modes.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import secrets
import time

from google.protobuf.message import DecodeError

from .card_progression import prepare_enhancement
from .gameplay import _Catalog
from .live_input import MAIN_QUEST_ID, RULESET, prepare_main_live
from .rpc import RpcCode, RpcFailure
from .state import AttemptConflict, State
from .tutorial_progression import TutorialProgression, _number

_PATH = '/api.Quest/Start'
_USER = '/api.User/Get'
_AREA = 'area-main-001'
_I32 = (1 << 31) - 1
_DAY = 86400000
_JST = 9 * 3600000
# This exact fixed reward is pinned to the supported 6.1.1 first quest.
_CLEAR_REWARDS = ((1, 'item-card_enhance', 290), (8, '', 500),
                  (15, '', 50), (3, 'ac-1-visual-02', 1))


def _fail(detail, code=RpcCode.FAILED_PRECONDITION):
    raise RpcFailure(code, 'Experimental main live: ' + detail)


def _single(rows, field, identity):
    matches = [row for row in rows if getattr(row, field) == identity]
    if len(matches) > 1:
        _fail('ambiguous local ' + field)
    return matches[0] if matches else None


def _same_day(a, b):
    return a > 0 and (a + _JST) // _DAY == (b + _JST) // _DAY


class MainLives:
    """Compute and atomically settle the explicitly enabled first main quest."""

    def __init__(self, schema, state, profile, master_dir, engine=None, enabled=False):
        self.schema, self.state, self.profile = schema, state, profile
        self.master_dir = Path(master_dir) if master_dir is not None else None
        self.catalog = _Catalog(self.master_dir)
        self.engine, self.enabled = engine, enabled

    def _definition(self):
        quest = self.catalog.ids('Quest', required=True).get(MAIN_QUEST_ID)
        area = self.catalog.ids('Area', required=True).get(_AREA)
        if (quest is None or area is None or quest.get('areaId') != _AREA or area.get('type') != 1
                or MAIN_QUEST_ID not in area.get('questIds', [])
                or len(set(area['questIds'])) != len(area['questIds'])):
            _fail('first-quest area references are invalid')
        if (_number(quest.get('clearScore'), 'clear score') != 3000
                or _number(quest.get('rewardManagerExp'), 'live manager experience') != 50
                or _number(quest.get('rewardCardExp'), 'live card experience') != 40
                or any(quest.get(key) for key in ('rankAdditionalRewardId', 'rankSRewardId',
                    'rankARewardId', 'rankBRewardId', 'rankCRewardId', 'rankDRewardId',
                    'achievedRankRewards'))):
            _fail('the first-quest reward or score definition differs from its pin')
        reward = self.catalog.ids('Reward', required=True).get(quest.get('clearRewardId'))
        resources = reward.get('resources') if reward else None
        if not isinstance(resources, list):
            _fail('first-clear reward is missing')
        actual = []
        for row in resources:
            if not isinstance(row, dict):
                _fail('invalid first-clear reward')
            actual.append((_number(row.get('resourceType'), 'resource type'), row.get('resourceId', ''),
                           _number(row.get('amount'), 'reward amount', positive=True)))
        if tuple(actual) != _CLEAR_REWARDS:
            _fail('the first-clear reward differs from its pin')
        if ('item-card_enhance' not in self.catalog.ids('Item', required=True)
                or 'ac-1-visual-02' not in self.catalog.ids('Accessory', required=True)):
            _fail('first-clear resource master references are missing')
        settings = self.catalog.rows('Setting', required=True)
        if len(settings) != 1:
            _fail('one Setting master row is required')
        return quest, area, settings[0]

    def _result(self, raw, snapshot, positions):
        if not isinstance(raw, bytes) or not raw:
            _fail('engine returned no protobuf result', RpcCode.INTERNAL)
        result = self.schema.response_type(_PATH)().result
        try:
            result.ParseFromString(raw)
        except DecodeError:
            _fail('engine returned malformed protobuf', RpcCode.INTERNAL)
        if len(result.userInfos) != 1 or not result.charts or not result.HasField('preChart'):
            _fail('engine result has no complete player timeline', RpcCode.INTERNAL)
        player = result.userInfos[0]
        expected = [(row.position, row.cardId) for row in positions]
        if (player.index != 1 or player.isNpc or player.userId != snapshot.userPublic.publicUserId
                or player.name != snapshot.user.name or not player.HasField('userResult')
                or [(row.index, row.cardId) for row in player.userDeck.cards] != expected):
            _fail('engine result does not match the local player and saved unit', RpcCode.INTERNAL)
        score = _number(player.userResult.score, 'computed score')
        card_results = player.userResult.cardResults
        if (len(card_results) != 5 or {row.cardId for row in card_results} != {row.cardId for row in positions}
                or any(row.totalScore < 0 for row in card_results)
                or sum(row.totalScore for row in card_results) != score
                or result.cleared != (score >= 3000)):
            _fail('engine clear status or card scores are inconsistent', RpcCode.INTERNAL)
        # No detail-log/replay service is implemented for these local attempts.
        result.detailLogId = ''
        result.isDisplayDetailAvailable = False
        return result, score

    def _card_xp(self, snapshot, positions, manager_level, amount):
        manager = [row for row in self.catalog.rows('ManagerLevel', required=True)
                   if row.get('level') == manager_level]
        if len(manager) != 1:
            _fail('manager card-level cap is ambiguous')
        manager_cap = _number(manager[0].get('maxCardLevel'), 'manager card-level cap', positive=True)
        levels = {}
        for row in self.catalog.rows('CardLevel', required=True):
            level = _number(row.get('level'), 'card level', positive=True)
            if level in levels:
                _fail('card experience thresholds are ambiguous')
            levels[level] = _number(row.get('requiredExp'), 'card experience threshold')
        rarities = self.catalog.rows('CardRarity', required=True)
        version = self.state.starter_version(self.profile)
        plans = []
        for position in positions:
            card = _single(snapshot.cards, 'cardId', position.cardId)
            if card is None:
                _fail('selected card is not owned')
            rarity = [row for row in rarities if row.get('rarity') == card.rarity]
            if len(rarity) != 1:
                _fail('card rarity cap is ambiguous')
            cap = min(manager_cap, _number(rarity[0].get('levelLimit'), 'rarity level cap', positive=True))
            if cap not in levels:
                _fail('card level cap has no experience threshold')
            old_exp = _number(card.totalExp, 'card experience')
            max_exp = levels[cap]
            if old_exp > max_exp:
                _fail('card experience exceeds its current cap')
            total = min(_number(old_exp + amount, 'card experience'), max_exp)
            target = max((level for level, threshold in levels.items() if level <= cap and threshold <= total), default=0)
            plan = prepare_enhancement(self.schema, self.master_dir, card, target,
                manager_level=manager_level,
                normalize_starter_rarity=version is not None and version >= 4 and card.rarity == 3)
            plan.card.totalExp = total
            plans.append((card, plan.card, total - old_exp, total - old_exp < amount))
        return plans

    def _reward(self, snapshot, response, setting):
        updated = response.commonResponse.updatedData
        for kind, identity, amount in _CLEAR_REWARDS:
            if kind == 1:
                matches = [row for row in snapshot.items if row.itemId == identity and row.expiredTime == 0]
                if len(matches) > 1:
                    _fail('permanent reward item rows are ambiguous')
                old = matches[0] if matches else None
                before = _number(old.amount if old is not None else 0, 'item amount')
                limit = _number(setting.get('itemLimit'), 'item limit', positive=True)
                after = _number(before + amount, 'item amount')
                if after > limit:
                    _fail('first-clear item exceeds the resource limit')
                row = old if old is not None else snapshot.items.add(itemId=identity)
                row.amount = after
                updated.items.add().CopyFrom(row)
            elif kind == 8:
                old = _single(snapshot.points, 'pointType', 1)
                before = _number(old.amount if old is not None else 0, 'gold amount')
                after = _number(before + amount, 'gold amount')
                if after > _number(setting.get('goldLimit'), 'gold limit', positive=True):
                    _fail('first-clear gold exceeds the resource limit')
                lifetime = _number(_number(snapshot.totalCount.pointGoldAmount, 'lifetime gold') + amount, 'lifetime gold')
                row = old if old is not None else snapshot.points.add(pointType=1)
                row.amount = after
                snapshot.totalCount.pointGoldAmount = lifetime
                updated.points.add().CopyFrom(row)
                updated.totalCount.CopyFrom(snapshot.totalCount)
            elif kind == 15:
                before = _number(snapshot.balance.freeBalance, 'free stone amount')
                after = _number(before + amount, 'free stone amount')
                if after > min(_I32, _number(setting.get('freeStoneLimit'), 'free stone limit', positive=True)):
                    _fail('first-clear stone exceeds the resource limit')
                snapshot.balance.freeBalance = after
                updated.balance.CopyFrom(snapshot.balance)
            else:
                old = _single(snapshot.accessories, 'accessoryId', identity)
                before = _number(old.amount if old is not None else 0, 'accessory amount')
                after = _number(before + amount, 'accessory amount')
                if after > _number(setting.get('accessoryLimit'), 'accessory limit', positive=True):
                    _fail('first-clear accessory exceeds the resource limit')
                row = old if old is not None else snapshot.accessories.add(accessoryId=identity)
                row.amount = after
                updated.accessories.add().CopyFrom(row)
            response.reward.clearRewards.add(resourceType=kind, resourceId=identity,
                amountI64=amount, beforeAmount=before, afterAmount=after, isNew=before == 0)

    def _settle(self, snapshot, request, response, score, now):
        _quest, area_master, setting = self._definition()
        old_quest = _single(snapshot.quests, 'questId', MAIN_QUEST_ID)
        old_area = _single(snapshot.areas, 'areaId', _AREA)
        high = _number(old_quest.highestScore if old_quest else 0, 'highest score')
        response.highestScore = high
        rank = _number(old_quest.highestRank if old_quest else 0, 'highest rank')
        if rank > _I32:
            _fail('saved highest rank exceeds the response range')
        response.highestRank = rank
        if not response.result.cleared:
            return
        for row in (old_quest, old_area):
            if row is not None and (_number(row.lastClearedTime, 'last-clear time') > now
                                    or row.dailyClearCount < 0):
                _fail('clear clock or counter is invalid')
        if old_quest is not None and _number(old_quest.highestScoreTime, 'highest score time') > now:
            _fail('highest-score clock is ahead of the local clock')
        known = {}
        for row in snapshot.quests:
            if row.questId in area_master['questIds']:
                if row.questId in known:
                    _fail('main-area quest progress is ambiguous')
                known[row.questId] = _number(row.lastClearedTime, 'quest clear time') > 0
        count = sum(known.values())
        if (old_area is None and count or old_area is not None and old_area.clearQuestCount != count):
            _fail('main-area clear count disagrees with its saved quest progress')
        first = old_quest is None or old_quest.lastClearedTime == 0
        # Mutations only affect the isolated protobuf copy; any later validation
        # or receipt-insert failure rolls back the complete SQLite transaction.
        if first:
            progression = TutorialProgression(self.schema, self.state, self.profile, self.master_dir)
            experience = _number(snapshot.user.managerExp, 'manager experience')
            if snapshot.user.managerLevel != progression._manager_level(experience):
                _fail('manager level and experience disagree')
            new_exp = _number(experience + 50, 'manager experience')
            new_level = progression._manager_level(new_exp)
            positions = sorted((row for row in snapshot.deckPositions if row.number == request.deckNumber), key=lambda row: row.position)
            plans = self._card_xp(snapshot, positions, new_level, 40)
            self._reward(snapshot, response, setting)
        updated = response.commonResponse.updatedData
        if first:
            snapshot.user.managerExp, snapshot.user.managerLevel = new_exp, new_level
            if count + 1 == len(area_master['questIds']):
                cards = self.catalog.ids('Card', required=True)
                owners = [cards.get(row.cardId, {}).get('characterId') for row in positions]
                if any(not isinstance(owner, str) or not owner for owner in owners):
                    _fail('cleared-area character references are missing')
                del snapshot.user.questMainAreaLastClearCharacterIds[:]
                snapshot.user.questMainAreaLastClearCharacterIds.extend(dict.fromkeys(owners))
            updated.user.CopyFrom(snapshot.user)
            for card, projected, gain, truncated in plans:
                card.CopyFrom(projected)
                updated.cards.add().CopyFrom(card)
                response.reward.rewardCards.add(cardId=card.cardId, exp=gain, isExpTruncated=truncated)
        quest = old_quest if old_quest is not None else snapshot.quests.add(questId=MAIN_QUEST_ID)
        area = old_area if old_area is not None else snapshot.areas.add(areaId=_AREA)
        for row in (quest, area):
            count_today = row.dailyClearCount if _same_day(row.lastClearedTime, now) else 0
            if count_today >= _I32:
                _fail('daily clear counter exceeds its limit')
            row.dailyClearCount, row.lastClearedTime = count_today + 1, now
        area.clearQuestCount = count + int(first)
        if score > high:
            quest.highestScore, quest.highestScoreTime = score, now
            quest.highestScoreRank = 0  # Main lives have no score-rank rewards.
        response.highestScore = quest.highestScore
        updated.quests.add().CopyFrom(quest)
        updated.areas.add().CopyFrom(area)

    def handle(self, path, plain, request_id=None):
        if path != _PATH or not self.enabled:
            return None
        try:
            State.live_request_id(request_id)
        except ValueError:
            _fail('a canonical positive uint64 x-app-request-id is required', RpcCode.INVALID_ARGUMENT)
        try:
            request = self.schema.request_type(path).FromString(plain)
        except DecodeError:
            _fail('malformed quest-start request', RpcCode.INVALID_ARGUMENT)
        if not request.questId or request.deckNumber <= 0 or request.playCount <= 0:
            _fail('quest, saved deck and positive play count are required', RpcCode.INVALID_ARGUMENT)
        if (request.questId != MAIN_QUEST_ID or request.playCount != 1 or request.useDailyTicket
                or request.isSkip or request.isAuto or request.userBuddyDeckPositions):
            _fail('only the first main quest with one ordinary saved-deck play is supported', RpcCode.UNIMPLEMENTED)
        version = self.catalog.version()
        if not version:
            _fail('a pinned master version is required')

        def attempt(raw):
            if self.engine is None or not callable(getattr(self.engine, 'simulate', None)):
                _fail('a compatible native live engine must be configured')
            try:
                snapshot = self.schema.response_type(_USER).FromString(raw)
            except DecodeError:
                _fail('local profile snapshot is malformed')
            if not snapshot.HasField('user') or not snapshot.HasField('userPublic'):
                _fail('local profile identity is missing')
            deck = _single(snapshot.decks, 'number', request.deckNumber)
            if deck is None:
                _fail('the selected saved deck does not exist', RpcCode.INVALID_ARGUMENT)
            if request.buddyDeckName and request.buddyDeckName != deck.name:
                _fail('borrowed deck names are not supported', RpcCode.UNIMPLEMENTED)
            positions = sorted((row for row in snapshot.deckPositions if row.number == request.deckNumber), key=lambda row: row.position)
            seed, now = secrets.randbits(64), time.time_ns() // 1000000
            self._definition()
            prepared = prepare_main_live(self.schema, self.master_dir, snapshot, request.questId, request.deckNumber, seed)
            live, score = self._result(self.engine.simulate(prepared), snapshot, positions)
            response = self.schema.response_type(path)(questId=request.questId)
            response.result.CopyFrom(live)
            response.reward.SetInParent()
            response.commonResponse.updatedData.SetInParent()
            response.commonResponse.deletedData.SetInParent()
            for rank, threshold in ((3, 3600), (2, 3000), (1, 0)):
                response.rankPatterns.add(rankType=rank, thresholdScore=threshold)
            self._settle(snapshot, request, response, score, now)
            return (snapshot.SerializeToString() if live.cleared else raw), response.SerializeToString(), seed, now

        try:
            return self.state.mutate_main_live_snapshot(self.profile, self.schema.fingerprint, request_id,
                hashlib.sha256(plain).hexdigest(), path, version, RULESET, attempt)
        except AttemptConflict:
            _fail('request identity was already used for different live input', RpcCode.INVALID_ARGUMENT)
        except ValueError:
            _fail('profile or cached attempt is incompatible with this schema, master or ruleset')
