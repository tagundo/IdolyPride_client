"""Independent RPC transcript tests for the native first-main-live QA oracle."""
import json
from pathlib import Path
import sqlite3

import pytest

from idoly_local import main_live_qa as qa
from idoly_local.card_progression import prepare_enhancement
from idoly_local.rpc import RpcCode, RpcFailure
from idoly_local.schema import Schema
from test_card_progression import synthetic_fixture


START = "/api.Quest/Start"
USER = "/api.User/Get"
QUEST = "qt-main-1-001-01"
AREA = "area-main-001"
NOW = 1794234000000
UNKNOWN = b"\x80\x4b\x7b"


@pytest.fixture(scope="module")
def schema():
    descriptor = Path(__file__).resolve().parents[1] / "data/protocol/idolypride-6.1.1.pb"
    if not descriptor.is_file():
        pytest.skip("Optional recovered 6.1.1 descriptor is unavailable")
    return Schema.from_descriptor_set(descriptor)


def clone(message):
    return type(message).FromString(message.SerializeToString())


def timeline(schema, snapshot, chart_rows, score):
    """Construct an original simple all-beat score transcript, not server code."""
    result = schema.response_type(START)().result
    result.cleared = True
    player = result.userInfos.add(index=1, userId=snapshot.userPublic.publicUserId, name=snapshot.user.name)
    positions = sorted(snapshot.deckPositions, key=lambda row: row.position)
    totals = [0] * 5
    left = score % 855
    accumulated = 0
    result.preChart.userStatuses.add(userIndex=1)
    for index in range(1, 6):
        result.preChart.cardStatuses.add(cardIndex=index)
    for definition in chart_rows:
        if not definition["type"]:
            continue
        chart = result.charts.add(number=definition["number"], chartType=definition["type"])
        if chart.chartType == 3:
            chart.activatedSkill.isComboBreak = True  # Legitimate locked-SP zero-card sentinel.
        if chart.chartType == 1:
            for index in range(1, 6):
                amount = score // 855 + int(left > 0)
                left = max(0, left - 1)
                chart.beats.add(order=accumulated + 1, cardIndex=index, score=amount)
                totals[index - 1] += amount
                accumulated += amount
        chart.userStatuses.add(userIndex=1, totalScore=accumulated)
        for index in range(1, 6):
            chart.cardStatuses.add(cardIndex=index)
    player.userResult.score = score
    for index, position in enumerate(positions, 1):
        player.userDeck.cards.add(index=index, cardId=position.cardId)
        player.userResult.cardResults.add(cardId=position.cardId, totalScore=totals[index - 1])
    assert accumulated == score
    return result


@pytest.fixture
def game(schema, tmp_path):
    _schema, master, tables, original = synthetic_fixture(tmp_path, schema)
    card_definition = dict(tables["Card"][0])
    tables["Card"] = [{**card_definition, "id": "card-" + str(i), "characterId": "char-" + str(i)} for i in range(1, 6)]
    tables.update({
        "Quest": [{"id": QUEST, "areaId": AREA, "clearScore": "3000", "rewardManagerExp": 50,
                   "rewardCardExp": 40, "clearRewardId": "first-clear", "musicChartPatternId": "chart-fixture"}],
        "Area": [{"id": AREA, "type": 1, "questIds": [QUEST, "quest-2", "quest-3"]}],
        "Reward": [{"id": "first-clear", "resources": [
            {"resourceType": 1, "resourceId": "item-card_enhance", "amount": 290},
            {"resourceType": 8, "amount": 500}, {"resourceType": 15, "amount": 50},
            {"resourceType": 3, "resourceId": "ac-1-visual-02", "amount": 1}]}],
        "Accessory": [{"id": "ac-1-visual-02"}],
        "MusicChartPattern": [{"id": "chart-fixture", "number": i,
            "type": 1 if i <= 171 else 2 if i <= 182 else 3 if i == 183 else 0} for i in range(1, 285)],
    })
    for name, rows in tables.items():
        (master / (name + ".json")).write_text(json.dumps(rows))
    (master / "!version.txt").write_text("original-qa-master")
    before = schema.response_type(USER)()
    before.user.name, before.user.managerLevel, before.user.cardSupportLevel = "Local QA manager", 1, 7
    before.userPublic.publicUserId, before.userPublic.serverUserId = "qa-public", "qa-server"
    before.decks.add(number=1, name="Saved original unit")
    before.balance.freeBalance, before.balance.paidBalance = 100, 17
    before.points.add(pointType=1, amount=7)
    before.totalCount.pointGoldAmount = 8
    before.items.add(itemId="item-card_enhance", amount=100)
    before.items.add(itemId="unrelated-item", amount=42)
    before.areas.add(areaId=AREA)
    before.stories.add(storyId="preserved-read", statusType=2)
    for i in range(1, 6):
        card = before.cards.add()
        card.CopyFrom(original)
        card.cardId = "card-" + str(i)
        card.MergeFromString(UNKNOWN)
        before.deckPositions.add(number=1, position=i, cardId=card.cardId)
        before.characters.add(characterId="char-" + str(i), lightFanAmount=100 + i)
    before.MergeFromString(UNKNOWN)
    first_after = clone(before)
    first_after.user.managerExp, first_after.user.managerLevel = 50, 2
    for card in first_after.cards:
        card.CopyFrom(prepare_enhancement(schema, master, card, 2, manager_level=2).card)
    first_after.items[0].amount = 390
    first_after.points[0].amount = 507
    first_after.totalCount.pointGoldAmount = 508
    first_after.balance.freeBalance = 150
    first_after.accessories.add(accessoryId="ac-1-visual-02", amount=1)
    first_after.areas[0].clearQuestCount = first_after.areas[0].dailyClearCount = 1
    first_after.areas[0].lastClearedTime = NOW
    first_after.quests.add(questId=QUEST, dailyClearCount=1, lastClearedTime=NOW,
        highestScore=5000, highestScoreTime=NOW)
    second_after = clone(first_after)
    second_after.areas[0].dailyClearCount = second_after.quests[0].dailyClearCount = 2
    second_after.areas[0].lastClearedTime = second_after.quests[0].lastClearedTime = NOW + 1
    second_after.quests[0].highestScore, second_after.quests[0].highestScoreTime = 6000, NOW + 1
    def response(snapshot, score, first):
        result = schema.response_type(START)(questId=QUEST, highestScore=score)
        result.result.CopyFrom(timeline(schema, before, tables["MusicChartPattern"], score))
        result.reward.SetInParent()
        updated = result.commonResponse.updatedData
        updated.SetInParent()
        result.commonResponse.deletedData.SetInParent()
        for rank, goal in ((3, 3600), (2, 3000), (1, 0)):
            result.rankPatterns.add(rankType=rank, thresholdScore=goal)
        if first:
            updated.user.CopyFrom(snapshot.user)
            updated.cards.extend(snapshot.cards)
            updated.items.add().CopyFrom(snapshot.items[0])
            updated.points.add().CopyFrom(snapshot.points[0])
            updated.totalCount.CopyFrom(snapshot.totalCount)
            updated.balance.CopyFrom(snapshot.balance)
            updated.accessories.extend(snapshot.accessories)
            for kind, identity, amount, previous, after in ((1, "item-card_enhance", 290, 100, 390),
                    (8, "", 500, 7, 507), (15, "", 50, 100, 150), (3, "ac-1-visual-02", 1, 0, 1)):
                result.reward.clearRewards.add(resourceType=kind, resourceId=identity, amountI64=amount,
                    beforeAmount=previous, afterAmount=after, isNew=previous == 0)
            for card in snapshot.cards:
                result.reward.rewardCards.add(cardId=card.cardId, exp=40)
        updated.quests.extend(snapshot.quests)
        updated.areas.extend(snapshot.areas)
        return result
    first_response, second_response = response(first_after, 5000, True), response(second_after, 6000, False)
    class Transport:
        current = clone(before)
        cache = {}
        calculations = 0
        fault = None
        calls = []
        is_skip = False
        cache_requests = {}
        def invoke(self, path, request, request_id):
            self.calls.append((path, request_id))
            if path == USER:
                assert request_id is None
                return clone(self.current)
            assert path == START and request.questId == QUEST and request.deckNumber == request.playCount == 1
            assert request.buddyDeckName == before.decks[0].name and not request.isAuto
            if request_id in self.cache:
                if request.SerializeToString() != self.cache_requests[request_id]:
                    if self.fault != "cross-mode-accepted":
                        code = RpcCode.UNIMPLEMENTED if self.fault == "wrong-cross-mode-status" else RpcCode.INVALID_ARGUMENT
                        raise RpcFailure(code, "request identity conflict")
                result = schema.response_type(START).FromString(self.cache[request_id])
                if self.fault == "rerolled-cache":
                    result.result.charts[0].beats[0].score += 1
                return result
            assert request.isSkip == self.is_skip
            self.calculations += 1
            first = request_id == qa._IDS[0]
            self.current = clone(first_after if first else second_after)
            result = clone(first_response if first else second_response)
            if self.fault == "paid": self.current.balance.paidBalance += 1
            if self.fault == "story": self.current.stories[0].statusType = 0
            if self.fault == "fan": self.current.characters[0].lightFanAmount += 1
            if self.fault == "deck": self.current.decks[0].name = "Changed unit"
            if self.fault == "enhance-time": self.current.cards[0].lastEnhanceTime += 1
            if self.fault == "unknown": self.current.DiscardUnknownFields()
            if self.fault == "repeat-xp" and not first: self.current.user.managerExp += 50
            if self.fault == "repeat-item" and not first: self.current.items[0].amount += 290
            if self.fault == "wrong-card-xp": self.current.cards[0].totalExp += 1
            if self.fault == "extra-reward" and not first: result.reward.clearRewards.add(resourceType=15, amountI64=50)
            if self.fault == "missing-deleted": result.commonResponse.ClearField("deletedData")
            if self.fault == "extra-common": result.commonResponse.updatedData.characters.add().CopyFrom(self.current.characters[0])
            if self.fault == "trace-score": result.result.charts[0].beats[0].score += 1
            if self.fault == "unattributed-zero-skill":
                result.result.charts[-1].activatedSkill.isComboBreak = False
            if self.fault == "unattributed-passive":
                result.result.activatedPassiveSkills.add(isComboBreak=True)
            if self.fault == "unattributed-active":
                result.result.charts[-1].activatedSkill.activated = True
            if self.fault == "identity": result.result.userInfos[0].userId = "other-player"
            if self.fault == "chart": del result.result.charts[-1]
            if self.fault == "clear-count": self.current.areas[0].clearQuestCount += 1
            self.cache[request_id] = result.SerializeToString()
            self.cache_requests[request_id] = request.SerializeToString()
            return result
    return schema, master, tables, before, first_after, second_after, Transport()


@pytest.mark.parametrize("is_skip", (False, True))
def test_main_live_oracle_settles_once_new_id_recomputes_and_restart_replays_exact_old_responses(game, is_skip):
    schema, master, _tables, before, _first, final, transport = game
    transport.is_skip = is_skip
    receipt = qa.run_main_live_checks(schema, transport.invoke, master, label="unit", is_skip=is_skip)
    assert receipt["is_skip"] is is_skip
    expected_request = schema.request_type(START)(questId=QUEST, deckNumber=1, playCount=1,
        buddyDeckName=before.decks[0].name, isSkip=is_skip)
    assert receipt["request_sha256"] == qa._digest(expected_request)
    assert receipt["card_exp_deltas"] == [40] * 5
    assert (receipt["chart_count"], receipt["beat_count"], receipt["first_score"], receipt["replay_score"]) == (183, 855, 5000, 6000)
    assert receipt["started_times"] == [NOW, NOW + 1] and transport.calculations == 2
    assert receipt["clear_reward_once"] and receipt["new_id_no_reward_exp"] and receipt["same_id_cached_exact"]
    assert transport.current == final and before.balance.paidBalance == final.balance.paidBalance == 17
    assert UNKNOWN in final.SerializeToString() and final.cards[0].lastEnhanceTime == before.cards[0].lastEnhanceTime
    qa.assert_main_live_snapshot(schema, memoryview(final.SerializeToString()), receipt)
    qa.assert_main_live_retries(schema, transport.invoke, master, receipt)
    qa.assert_main_live_mode_conflicts(schema, transport.invoke, master, receipt)
    assert transport.calculations == 2 and transport.current == final
    assert "qa-public" not in json.dumps(receipt) and "Saved original unit" not in json.dumps(receipt)


@pytest.mark.parametrize("is_skip", (None, 0, 1, "true"))
def test_skip_mode_requires_an_explicit_boolean_before_any_rpc(game, is_skip):
    schema, master, _tables, _before, _first, _final, transport = game
    with pytest.raises(RuntimeError, match="explicit boolean"):
        qa.run_main_live_checks(schema, transport.invoke, master, is_skip=is_skip)
    assert not transport.calls


def test_normal_mode_receipts_remain_backward_compatible(game):
    schema, master, _tables, _before, _first, _final, transport = game
    receipt = qa.run_main_live_checks(schema, transport.invoke, master)
    assert receipt.pop("is_skip") is False
    qa.assert_main_live_retries(schema, transport.invoke, master, receipt)


@pytest.mark.parametrize("fault", ("cross-mode-accepted", "wrong-cross-mode-status"))
def test_cross_mode_request_id_reuse_requires_rejection_without_mutation(game, fault):
    schema, master, _tables, _before, _first, _final, transport = game
    receipt = qa.run_main_live_checks(schema, transport.invoke, master)
    transport.fault = fault
    with pytest.raises(RuntimeError, match="opposite-mode"):
        qa.assert_main_live_mode_conflicts(schema, transport.invoke, master, receipt)


def test_skip_receipt_binds_the_exact_wire_request_and_rejects_mode_tampering(game):
    schema, master, _tables, _before, _first, _final, transport = game
    transport.is_skip = True
    receipt = qa.run_main_live_checks(schema, transport.invoke, master, is_skip=True)
    qa.assert_main_live_attempt_rows(schema, attempt_rows(transport, receipt), receipt)
    receipt["is_skip"] = False
    with pytest.raises(RuntimeError, match="request changed"):
        qa.assert_main_live_retries(schema, transport.invoke, master, receipt)


def test_request_can_bind_a_complete_alternate_saved_deck_without_changing_it(game):
    schema, master, _tables, before, _first, _final, _transport = game
    alternate = clone(before)
    alternate.decks.add(number=7, name="Existing complete alternate")
    for row in list(alternate.deckPositions):
        copy = alternate.deckPositions.add(); copy.CopyFrom(row); copy.number = 7
    del alternate.deckPositions[0]
    original = alternate.SerializeToString()
    request, positions = qa._request(schema, alternate, qa._oracle(master), is_skip=True, deck_number=7)
    assert request.deckNumber == 7 and request.buddyDeckName == "Existing complete alternate" and request.isSkip
    assert [row.position for row in positions] == [1, 2, 3, 4, 5]
    assert alternate.SerializeToString() == original


@pytest.mark.parametrize("number", (False, 0, -1, "1"))
def test_request_rejects_invalid_saved_deck_numbers(game, number):
    schema, master, _tables, before, _first, _final, _transport = game
    with pytest.raises(RuntimeError, match="positive integer"):
        qa._request(schema, before, qa._oracle(master), deck_number=number)


@pytest.mark.parametrize("fault", ("paid", "story", "fan", "deck", "enhance-time", "unknown", "repeat-xp",
    "repeat-item", "wrong-card-xp", "extra-reward", "missing-deleted", "extra-common", "trace-score",
    "unattributed-zero-skill", "unattributed-passive", "unattributed-active", "identity", "chart", "clear-count", "rerolled-cache"))
def test_main_live_qa_rejects_incorrect_projection_trace_or_lost_exact_cache(game, fault):
    schema, master, _tables, _before, _first, _final, transport = game
    transport.fault = fault
    with pytest.raises(RuntimeError):
        qa.run_main_live_checks(schema, transport.invoke, master)


def test_restart_loss_of_cache_or_progress_cannot_produce_success(game):
    schema, master, _tables, _before, _first, _final, transport = game
    receipt = qa.run_main_live_checks(schema, transport.invoke, master)
    transport.cache = {}
    with pytest.raises(RuntimeError, match="cached attempt changed"):
        qa.assert_main_live_retries(schema, transport.invoke, master, receipt)


def test_oracle_rejects_changed_reward_master_before_any_rpc(game):
    schema, master, tables, _before, _first, _final, transport = game
    tables["Reward"][0]["resources"][0]["amount"] = 291
    (master / "Reward.json").write_text(json.dumps(tables["Reward"]))
    with pytest.raises(RuntimeError, match="oracle"):
        qa.run_main_live_checks(schema, transport.invoke, master)
    assert not transport.calls


def attempt_rows(transport, receipt):
    return [{"profile": "sandbox", "request_id": identity, "request_sha256": receipt["request_sha256"],
             "path": START, "schema_sha256": receipt["schema_sha256"], "master_version": receipt["master_version"],
             "ruleset": receipt["ruleset"], "seed": str(index), "started_time": started,
             "response": transport.cache[identity]}
            for index, (identity, started) in enumerate(zip(receipt["request_ids"], receipt["started_times"]))]


def test_attempt_oracle_accepts_exact_dict_or_sqlite_rows_in_either_order(game):
    schema, master, _tables, _before, _first, _final, transport = game
    receipt = qa.run_main_live_checks(schema, transport.invoke, master)
    rows = attempt_rows(transport, receipt)
    qa.assert_main_live_attempt_rows(schema, rows[::-1], receipt)
    with sqlite3.connect(":memory:") as db:
        db.row_factory = sqlite3.Row
        db.execute("CREATE TABLE attempts(profile,request_id,request_sha256,path,schema_sha256,master_version,ruleset,seed,started_time,response)")
        for row in rows:
            db.execute("INSERT INTO attempts VALUES(?,?,?,?,?,?,?,?,?,?)", tuple(row.values()))
        qa.assert_main_live_attempt_rows(schema, db.execute("SELECT * FROM attempts").fetchall(), receipt)


@pytest.mark.parametrize("field,value", (("profile", "other"), ("request_id", "different"),
    ("request_sha256", "0" * 64), ("path", "/api.Tutorial/StartQuest"), ("schema_sha256", "wrong"),
    ("master_version", "wrong"), ("ruleset", "wrong"), ("seed", "01"), ("seed", 1),
    ("seed", str(1 << 64)), ("started_time", NOW + 1), ("response", b"malformed")))
def test_attempt_oracle_rejects_tampered_context_seed_time_or_cached_response(game, field, value):
    schema, master, _tables, _before, _first, _final, transport = game
    receipt = qa.run_main_live_checks(schema, transport.invoke, master)
    rows = attempt_rows(transport, receipt)
    rows[0][field] = value
    with pytest.raises(RuntimeError):
        qa.assert_main_live_attempt_rows(schema, rows, receipt)
    with pytest.raises(RuntimeError, match="exactly the two"):
        qa.assert_main_live_attempt_rows(schema, rows + [dict(rows[1])], receipt)
