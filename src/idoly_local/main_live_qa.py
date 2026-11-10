"""Opt-in first-main-live QA over a native caller's authenticated transport.

The oracle reads public reward/chart/experience tables and uses only the
separately verified pure card projection. It never imports the live provider,
edits a private database, grants test resources, or chooses an engine seed.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from google.protobuf.message import DecodeError

from .card_progression import prepare_enhancement


_USER = "/api.User/Get"
_START = "/api.Quest/Start"
_QUEST = "qt-main-1-001-01"
_AREA = "area-main-001"
_IDS = ("9000000000000000301", "9000000000000000302")
_REWARDS = ((1, "item-card_enhance", 290), (8, "", 500), (15, "", 50), (3, "ac-1-visual-02", 1))


def _require(condition, message):
    if not condition:
        raise RuntimeError("Main live QA: " + message)


def _bytes(value):
    return value.SerializeToString(deterministic=True)


def _digest(value):
    return hashlib.sha256(_bytes(value)).hexdigest()


def _number(value):
    _require(type(value) is int or isinstance(value, str) and value.isascii() and value.isdigit(),
             "public numeric value is invalid")
    number = int(value)
    _require(number >= 0, "negative public numeric value")
    return number


def _one(rows, field, identity, *, required=True):
    matches = [row for row in rows if getattr(row, field) == identity]
    _require(len(matches) <= 1 and (not required or len(matches) == 1), "ambiguous or missing " + field)
    return matches[0] if matches else None


def _oracle(master_dir):
    directory = Path(master_dir)
    tables = {}
    for name in ("Quest", "Area", "Reward", "Card", "Item", "Accessory", "ManagerLevel", "CardLevel", "CardRarity", "MusicChartPattern"):
        rows = json.loads((directory / (name + ".json")).read_text(encoding="utf-8"))
        _require(isinstance(rows, list) and all(isinstance(row, dict) for row in rows), "invalid public " + name)
        tables[name] = rows
    def by_id(name, identity):
        selected = [row for row in tables[name] if row.get("id") == identity]
        _require(len(selected) == 1, "public " + name + " reference is ambiguous or missing")
        return selected[0]
    quest, area = by_id("Quest", _QUEST), by_id("Area", _AREA)
    _require(quest.get("areaId") == _AREA and area.get("type") == 1 and _QUEST in area.get("questIds", [])
             and len(set(area["questIds"])) == len(area["questIds"]), "first-main quest/area references differ")
    resources = by_id("Reward", quest.get("clearRewardId")).get("resources", [])
    rewards = tuple((_number(row.get("resourceType")), row.get("resourceId", ""), _number(row.get("amount")))
                    for row in resources)
    _require(rewards == _REWARDS and _number(quest.get("clearScore")) == 3000
             and _number(quest.get("rewardManagerExp")) == 50 and _number(quest.get("rewardCardExp")) == 40,
             "independent first-clear reward/experience/goal oracle differs")
    by_id("Item", "item-card_enhance")
    by_id("Accessory", "ac-1-visual-02")
    _require(not any(quest.get(key) for key in ("rankAdditionalRewardId", "rankSRewardId", "rankARewardId",
                 "rankBRewardId", "rankCRewardId", "rankDRewardId", "achievedRankRewards")),
             "first quest unexpectedly defines unsupported rank rewards")
    chart_rows = [row for row in tables["MusicChartPattern"] if row.get("id") == quest.get("musicChartPatternId")]
    _require(len({row.get("number") for row in chart_rows}) == len(chart_rows), "ambiguous chart numbers")
    charts = sorted(((_number(row["number"]), _number(row.get("type"))) for row in chart_rows if row.get("type")))
    _require(len(charts) == 183 and sum(kind == 1 for _, kind in charts) * 5 == 855,
             "public first-main chart/beat oracle differs from 183/855")
    tables.update(quest=quest, area=area, rewards=rewards, charts=charts)
    return tables


def _deck(snapshot, tables):
    _require(snapshot.HasField("user") and snapshot.HasField("userPublic")
             and bool(snapshot.userPublic.publicUserId), "local user identity is absent")
    deck = _one(snapshot.decks, "number", 1)
    positions = sorted((row for row in snapshot.deckPositions if row.number == 1), key=lambda row: row.position)
    _require([row.position for row in positions] == [1, 2, 3, 4, 5]
             and len({row.cardId for row in positions}) == 5, "requires the original saved five-card unit1")
    owners = []
    for row in positions:
        _require(not row.photoIds and not row.part1AccessoryId and not row.part2AccessoryId,
                 "native QA requires the original unit without unsupported photo/accessory extras")
        card = _one(snapshot.cards, "cardId", row.cardId)
        master = [value for value in tables["Card"] if value.get("id") == card.cardId]
        _require(len(master) == 1 and not card.supported, "selected card does not resolve to an ordinary owned card")
        owner = master[0].get("characterId")
        _one(snapshot.characters, "characterId", owner)
        owners.append(owner)
    _require(len(set(owners)) == 5, "the saved initial unit must contain five different characters")
    return deck, positions


def _request(schema, snapshot, tables):
    deck, positions = _deck(snapshot, tables)
    return schema.request_type(_START)(questId=_QUEST, deckNumber=1, playCount=1, buddyDeckName=deck.name), positions


def _result(response, before, positions, tables):
    result = response.result
    _require(response.HasField("result") and len(result.userInfos) == 1 and result.HasField("preChart"),
             "calculation omitted the complete one-user timeline")
    player = result.userInfos[0]
    card_ids = [row.cardId for row in positions]
    _require(player.index == 1 and not player.isNpc and player.userId == before.userPublic.publicUserId
             and player.name == before.user.name and player.HasField("userResult")
             and [(row.index, row.cardId) for row in player.userDeck.cards] == list(enumerate(card_ids, 1)),
             "computed result does not identify the local user and saved unit")
    _require([(row.number, row.chartType) for row in result.charts] == tables["charts"],
             "computed chart sequence differs from the public first-main master")
    trace = 0
    per_card = dict.fromkeys(range(1, 6), 0)
    def earned(entry, *, failed_active=False):
        # A locked/ineligible skill has a real zero-score failure sentinel,
        # with no selected card. It is not a beat or an unattributed reward.
        if (failed_active and entry.cardIndex == 0 and entry.score == 0 and not entry.activated
                and (entry.isComboBreak or entry.failures)):
            return 0
        _require(entry.cardIndex in per_card and entry.score >= 0, "timeline has an invalid card index/score")
        per_card[entry.cardIndex] += entry.score
        return entry.score
    for skill in result.activatedPassiveSkills:
        trace += earned(skill)
    for chart in [result.preChart, *result.charts]:
        _require([row.cardIndex for row in chart.cardStatuses] == [1, 2, 3, 4, 5]
                 and len(chart.userStatuses) == 1 and chart.userStatuses[0].userIndex == 1,
                 "timeline status rows do not cover exactly the five saved cards and local player")
    for chart in result.charts:
        _require([row.cardIndex for row in chart.beats] == ([1, 2, 3, 4, 5] if chart.chartType == 1 else []),
                 "beat frame does not cover the five local cards")
        trace += sum(earned(row) for row in chart.beats)
        if chart.HasField("activatedSkill"):
            trace += earned(chart.activatedSkill, failed_active=True)
        trace += sum(earned(row) for row in chart.activatedPassiveSkills)
    score = player.userResult.score
    _require(len(result.charts) == 183 and sum(len(row.beats) for row in result.charts) == 855
             and result.cleared and score >= _number(tables["quest"]["clearScore"]),
             "the default unit did not produce a complete valid first-main clear")
    _require([(row.cardId, row.totalScore) for row in player.userResult.cardResults]
             == [(identity, per_card[index]) for index, identity in enumerate(card_ids, 1)]
             and trace == score == result.charts[-1].userStatuses[0].totalScore,
             "beat/active/passive, per-card and final cumulative scores are not conserved")
    _require(not result.detailLogId and not result.isDisplayDetailAvailable,
             "experimental main live advertised an unavailable detail-log service")
    clean = type(result)()
    clean.CopyFrom(result)
    clean.DiscardUnknownFields()
    _require(_bytes(clean) == _bytes(result), "computed 6.1.1 timeline contains unknown wire fields")
    return score


def _manager_level(tables, experience):
    eligible = [_number(row["level"]) for row in tables["ManagerLevel"] if _number(row["requiredExp"]) <= experience]
    _require(bool(eligible), "manager experience has no public level")
    return max(eligible)


def _clear_projection(schema, before, response, positions, tables, master_dir, *, first):
    score = _result(response, before, positions, tables)
    expected = type(before)()
    expected.CopyFrom(before)
    answer = schema.response_type(_START)(questId=_QUEST)
    answer.result.CopyFrom(response.result)
    answer.reward.SetInParent()
    answer.commonResponse.updatedData.SetInParent()
    answer.commonResponse.deletedData.SetInParent()
    for rank, goal in ((3, 3600), (2, 3000), (1, 0)):
        answer.rankPatterns.add(rankType=rank, thresholdScore=goal)
    updated = answer.commonResponse.updatedData
    if first:
        _require(before.user.managerLevel == _manager_level(tables, before.user.managerExp),
                 "pre-clear manager level/experience disagree")
        expected.user.managerExp += _number(tables["quest"]["rewardManagerExp"])
        expected.user.managerLevel = _manager_level(tables, expected.user.managerExp)
        updated.user.CopyFrom(expected.user)
        manager = [row for row in tables["ManagerLevel"] if row["level"] == expected.user.managerLevel]
        _require(len(manager) == 1, "post-clear manager card cap is ambiguous")
        levels = {_number(row["level"]): _number(row["requiredExp"]) for row in tables["CardLevel"]}
        _require(len(levels) == len(tables["CardLevel"]), "ambiguous public card level thresholds")
        for position in positions:
            card = _one(expected.cards, "cardId", position.cardId)
            rarity = [row for row in tables["CardRarity"] if row.get("rarity") == card.rarity]
            _require(len(rarity) == 1, "card rarity cap is ambiguous")
            cap = min(_number(manager[0]["maxCardLevel"]), _number(rarity[0]["levelLimit"]))
            _require(cap in levels and card.totalExp <= levels[cap], "card experience exceeds its public cap")
            total = min(card.totalExp + _number(tables["quest"]["rewardCardExp"]), levels[cap])
            target = max(level for level, threshold in levels.items() if level <= cap and threshold <= total)
            plan = prepare_enhancement(schema, Path(master_dir), card, target,
                manager_level=expected.user.managerLevel, normalize_starter_rarity=card.rarity == 3)
            gain = total - card.totalExp
            projected = plan.card
            projected.totalExp = total
            card.CopyFrom(projected)
            updated.cards.add().CopyFrom(card)
            answer.reward.rewardCards.add(cardId=card.cardId, exp=gain,
                isExpTruncated=gain < _number(tables["quest"]["rewardCardExp"]))
        for kind, identity, amount in tables["rewards"]:
            if kind == 1:
                selected = [row for row in expected.items if row.itemId == identity and not row.expiredTime]
                _require(len(selected) <= 1, "ambiguous permanent reward item")
                row = selected[0] if selected else expected.items.add(itemId=identity)
                previous = row.amount
                row.amount += amount
                updated.items.add().CopyFrom(row)
            elif kind == 8:
                row = _one(expected.points, "pointType", 1, required=False)
                row = row if row is not None else expected.points.add(pointType=1)
                previous = row.amount
                row.amount += amount
                expected.totalCount.pointGoldAmount += amount
                updated.points.add().CopyFrom(row)
                updated.totalCount.CopyFrom(expected.totalCount)
            elif kind == 15:
                previous = expected.balance.freeBalance
                expected.balance.freeBalance += amount
                row = expected.balance
                updated.balance.CopyFrom(row)
            else:
                row = _one(expected.accessories, "accessoryId", identity, required=False)
                row = row if row is not None else expected.accessories.add(accessoryId=identity)
                previous = row.amount
                row.amount += amount
                updated.accessories.add().CopyFrom(row)
            after_amount = row.freeBalance if kind == 15 else row.amount
            answer.reward.clearRewards.add(resourceType=kind, resourceId=identity, amountI64=amount,
                beforeAmount=previous, afterAmount=after_amount, isNew=previous == 0)
    quest = _one(expected.quests, "questId", _QUEST, required=False)
    area = _one(expected.areas, "areaId", _AREA, required=False)
    _require(not first or quest is None or not quest.lastClearedTime, "requires a dedicated profile before its first main clear")
    if quest is None:
        quest = expected.quests.add(questId=_QUEST)
    if area is None:
        area = expected.areas.add(areaId=_AREA)
    time_rows = [row for row in response.commonResponse.updatedData.quests if row.questId == _QUEST]
    _require(len(time_rows) == 1, "clear omitted its authoritative quest timestamp")
    now = time_rows[0].lastClearedTime
    _require(now > 0 and now >= max(quest.lastClearedTime, area.lastClearedTime, quest.highestScoreTime),
             "clear timestamp is invalid or moved backwards")
    for row in (quest, area):
        same_day = row.lastClearedTime > 0 and (row.lastClearedTime + 32400000) // 86400000 == (now + 32400000) // 86400000
        row.dailyClearCount = (row.dailyClearCount if same_day else 0) + 1
        row.lastClearedTime = now
    area.clearQuestCount += int(first)
    if score > quest.highestScore:
        quest.highestScore, quest.highestScoreTime, quest.highestScoreRank = score, now, 0
    answer.highestScore = quest.highestScore
    updated.quests.add().CopyFrom(quest)
    updated.areas.add().CopyFrom(area)
    _require(_bytes(response) == _bytes(answer), "clear response differs from the exact master-backed reward/Common projection")
    return expected, now, score, [row.exp for row in answer.reward.rewardCards]


def _user(schema, invoke):
    return invoke(_USER, schema.request_type(_USER)(), None)


def assert_main_live_snapshot(schema, payload, receipt):
    snapshot = (schema.response_type(_USER).FromString(bytes(payload))
                if isinstance(payload, (bytes, bytearray, memoryview)) else payload)
    _require(_digest(snapshot) == receipt["snapshot_sha256"], "restart or retry changed the settled main-live snapshot")


def assert_main_live_attempt_rows(schema, rows, receipt):
    """Check two opaque SQLite attempt receipts without loading the engine."""
    records = [dict(row) for row in rows]
    columns = {"profile", "request_id", "request_sha256", "path", "schema_sha256", "master_version",
               "ruleset", "seed", "started_time", "response"}
    identities = receipt["request_ids"]
    _require(len(records) == len(identities) == len(receipt["started_times"]) == 2
             and len(set(identities)) == 2 and all(type(identity) is str for identity in identities)
             and {row.get("request_id") for row in records} == set(identities),
             "stored attempts must contain exactly the two requested IDs")
    expected = dict(zip(identities, zip(receipt["started_times"],
                    (receipt["first_response_sha256"], receipt["replay_response_sha256"]))))
    _require(schema.fingerprint == receipt["schema_sha256"], "attempt receipt uses a different schema")
    for row in records:
        _require(set(row) == columns and row["profile"] == "sandbox"
                 and row["request_sha256"] == receipt["request_sha256"] and row["path"] == _START
                 and row["schema_sha256"] == schema.fingerprint
                 and row["master_version"] == receipt["master_version"] and row["ruleset"] == receipt["ruleset"] == "live-v5",
                 "stored attempt context differs from its native QA receipt")
        seed = row["seed"]
        _require(type(seed) is str and 1 <= len(seed) <= 20 and seed.isascii() and seed.isdigit()
                 and str(int(seed)) == seed and 0 <= int(seed) < 1 << 64,
                 "stored attempt seed is not canonical uint64 TEXT")
        started, digest = expected[row["request_id"]]
        _require(type(row["started_time"]) is int and row["started_time"] == started and started > 0,
                 "stored attempt timestamp differs from its completed response")
        body = row["response"]
        _require(isinstance(body, (bytes, bytearray, memoryview)) and bool(body),
                 "stored attempt response is absent or not a protobuf BLOB")
        try:
            response = schema.response_type(_START).FromString(bytes(body))
        except DecodeError as error:
            raise RuntimeError("Main live QA: stored attempt response is not a valid 6.1.1 protobuf") from error
        _require(_digest(response) == digest, "stored attempt response differs from its exact cached result")


def _cached(schema, invoke, request, expected, ids, hashes):
    for identity, digest in zip(ids, hashes):
        response = invoke(_START, request, identity)
        _require(_digest(response) == digest, "same request ID lost its exact cached result or rerolled the engine")
        _require(_bytes(_user(schema, invoke)) == _bytes(expected), "cached attempt changed settlement or paid/advanced twice")


def assert_main_live_retries(schema, invoke, master_dir, receipt):
    expected = _user(schema, invoke)
    assert_main_live_snapshot(schema, expected, receipt)
    request, _positions = _request(schema, expected, _oracle(master_dir))
    _require(_digest(request) == receipt["request_sha256"], "saved main-live request changed after restart")
    _cached(schema, invoke, request, expected, receipt["request_ids"],
            (receipt["first_response_sha256"], receipt["replay_response_sha256"]))
    assert_main_live_snapshot(schema, _user(schema, invoke), receipt)


def run_main_live_checks(schema, invoke, master_dir, label="native"):
    tables = _oracle(master_dir)
    before = _user(schema, invoke)
    request, positions = _request(schema, before, tables)
    _require(not any(row.lastClearedTime for row in before.quests if row.questId in tables["area"]["questIds"])
             and all(not row.clearQuestCount for row in before.areas if row.areaId == _AREA),
             "requires the dedicated QA profile before any ordinary main clear")
    first = invoke(_START, request, _IDS[0])
    earned, first_time, first_score, gains = _clear_projection(schema, before, first, positions, tables, master_dir, first=True)
    _require(_bytes(_user(schema, invoke)) == _bytes(earned), "first clear changed unauthorized snapshot fields or resource/EXP deltas")
    _cached(schema, invoke, request, earned, _IDS[:1], (_digest(first),))
    replay = invoke(_START, request, _IDS[1])
    final, replay_time, replay_score, replay_gains = _clear_projection(schema, earned, replay, positions, tables, master_dir, first=False)
    _require(not replay_gains and _bytes(_user(schema, invoke)) == _bytes(final),
             "new request ID paid rewards/EXP again or changed unrelated progress")
    hashes = (_digest(first), _digest(replay))
    _cached(schema, invoke, request, final, _IDS, hashes)
    return {"platform": label, "quest_id": _QUEST, "deck_number": 1, "request_ids": list(_IDS),
            "request_sha256": _digest(request), "first_response_sha256": hashes[0], "replay_response_sha256": hashes[1],
            "started_times": [first_time, replay_time], "master_version": (Path(master_dir) / "!version.txt").read_text().strip(),
            "schema_sha256": schema.fingerprint, "ruleset": "live-v5", "snapshot_sha256": _digest(final),
            "first_score": first_score, "replay_score": replay_score, "chart_count": 183, "beat_count": 855,
            "clear_reward_once": True, "manager_exp_once": True, "card_exp_once": True,
            "new_id_no_reward_exp": True, "same_id_cached_exact": True, "exact_snapshot_projection": True,
            "score_trace_conserved": True, "local_identity_saved_unit": True, "no_unsupported_rewards": True,
            "original_deck_preserved": True, "enhance_item_delta": 290, "gold_delta": 500,
            "free_stone_delta": 50, "accessory_delta": 1, "manager_exp_delta": 50, "card_exp_deltas": gains}
