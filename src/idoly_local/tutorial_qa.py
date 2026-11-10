"""Shared synthetic-profile checks for installed Android and macOS engines.

This is an opt-in QA flow. The server never runs it on a player's profile.
The callback performs the platform's real encrypted RPC exchange.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def _require(value, explanation):
    if not value:
        raise RuntimeError("Tutorial continuation QA: " + explanation)


def _digest(user):
    return hashlib.sha256(user.SerializeToString(deterministic=True)).hexdigest()


def _mission_payloads(value):
    if "missions" not in value.DESCRIPTOR.fields_by_name:
        return ()
    return tuple(row.SerializeToString(deterministic=True) for row in value.missions)


def _assert_enhancement_missions(before, after, response, master_dir, card_id):
    """Validate the one supported high-water delta, preserving all other bytes."""
    identity = "ms-normal-card_level_achievement"
    expected = type(before).FromString(before.SerializeToString())
    saved = [row for row in getattr(expected, "missions", ()) if row.missionId == identity]
    _require(len(saved) <= 1, "card-level achievement is duplicated")
    source = Path(master_dir) / "Mission.json"
    changed = None
    # Old payloads and imported snapshots without this achievement do not gain
    # an active mission catalog merely by running the continuation.
    if source.is_file() and saved:
        masters = [row for row in json.loads(source.read_text(encoding="utf-8")) if row["id"] == identity]
        _require(len(masters) == 1, "card-level achievement master is ambiguous")
        thresholds = [int(row["threshold"]) for row in masters[0]["progresses"]]
        row = saved[0]
        _require(row.currentThreshold in thresholds and row.statusType in (1, 2, 3, 4)
                 and row.progress >= 0 and row.lastUpdateTime >= 0
                 and (row.statusType == 1 or row.progress >= row.currentThreshold),
                 "saved card-level achievement is invalid")
        highest = max((card.level for card in after.cards), default=0)
        _require(highest > 0, "enhancement has no owned-card level")
        if highest > row.progress:
            cards = [card for card in after.cards if card.cardId == card_id]
            _require(len(cards) == 1 and cards[0].lastEnhanceTime > 0,
                     "enhancement has no bounded mission update time")
            row.progress = highest
            row.lastUpdateTime = max(row.lastUpdateTime, cards[0].lastEnhanceTime)
            if row.statusType == 1 and highest >= row.currentThreshold:
                row.statusType = 2
            changed = row
    _require(_mission_payloads(after) == _mission_payloads(expected),
             "enhancement changed unexpected mission state")
    delta = _mission_payloads(response.commonResponse.updatedData)
    wanted = () if changed is None else (changed.SerializeToString(deterministic=True),)
    _require(delta == wanted, "enhancement mission response delta differs")


def assert_tutorial_continuation_snapshot(schema, payload, receipt):
    user = schema.response_type("/api.User/Get").FromString(payload) if isinstance(payload, bytes) else payload
    _require(_digest(user) == receipt["snapshot_sha256"], "restart changed the completed snapshot")
    _require(next(row.step for row in user.tutorials if row.tutorialType == 1) == 150,
             "completion checkpoint did not persist")
    _require(user.user.tutorialClearedTime > 0, "completion time did not persist")


def run_tutorial_continuation(schema, invoke, master_dir, *, label="native"):
    """Exercise checkpoints 100..150 through the actual platform transport."""
    directory = Path(master_dir)

    def rows(name):
        return json.loads((directory / (name + ".json")).read_text(encoding="utf-8"))

    def rpc(path, **fields):
        return invoke(path, schema.request_type(path)(**fields))

    def user():
        return rpc("/api.User/Get")

    def stage(value):
        rpc("/api.Tutorial/Progress", type=1, step=value)

    def point(value):
        return sum(row.amount for row in value.points if row.pointType == 1)

    def pieces(value):
        return sum(row.amount for row in value.items if row.itemId == "item-card_enhance" and not row.expiredTime)

    before = user()
    _require(max((row.step for row in before.tutorials if row.tutorialType == 1), default=0) <= 100,
             "requires the dedicated uncompleted synthetic QA profile")
    settings = rows("Setting")
    _require(len(settings) == 1, "Setting must have one row")
    setting = settings[0]
    minutes = setting["tutorialActivityLessonPromoteMinutes"]
    gold = minutes * setting["tutorialActivityLessonRewardGoldPerMinute"]
    exp = minutes * setting["tutorialActivityLessonRewardManagerExpPerMinute"]
    item_amount = minutes * setting["tutorialActivityLessonRewardCardEnhanceItemPerMinute"]
    stage(100)
    reward = rpc("/api.Tutorial/ReceiveLessonReward")
    _require([(r.resourceType, r.resourceId, r.amount) for r in reward.rewards]
             == [(8, "", gold), (14, "", exp), (1, "item-card_enhance", item_amount)], "lesson reward definitions differ")
    rewarded = user()
    _require(_mission_payloads(rewarded) == _mission_payloads(before), "lesson changed mission state")
    _require(point(rewarded) == point(before) + gold, "gold delta differs")
    _require(pieces(rewarded) == pieces(before) + item_amount, "lesson piece delta differs")
    _require(rewarded.user.managerExp == before.user.managerExp + exp, "manager EXP delta differs")
    _require(rewarded.totalCount.pointGoldAmount == before.totalCount.pointGoldAmount + gold,
             "lifetime earned gold delta differs")
    _require(next(r.step for r in rewarded.tutorials if r.tutorialType == 1) == 110,
             "lesson receipt checkpoint is not 110")
    rpc("/api.Tutorial/ReceiveLessonReward")
    _require(_digest(user()) == _digest(rewarded), "retry granted the lesson twice")

    stage(120)
    card = next((row for row in rewarded.cards if row.cardId == "card-ktn-03-schl-00"), None)
    _require(card is not None and card.baseLevel == 1 and not card.supported, "missing initial Kotono card")
    levels = {row["level"]: int(row["requiredExp"]) for row in rows("CardLevel")}
    cost = levels[2] - card.totalExp
    enhancement = rpc("/api.Card/Enhance", cardId=card.cardId, level=2)
    enhanced = user()
    updated = next(row for row in enhanced.cards if row.cardId == card.cardId)
    _require(updated.level == updated.baseLevel == 2 and updated.totalExp == levels[2], "card did not reach level two")
    _require((updated.vocal, updated.dance, updated.visual, updated.stamina) == (132, 105, 92, 937),
             "card parameters differ from the independent official level-two oracle")
    _require(updated.obtainedTime == card.obtainedTime, "enhancement changed original obtained time")
    _require(pieces(enhanced) == pieces(rewarded) - cost and point(enhanced) == point(rewarded),
             "enhancement consumption differs")
    _assert_enhancement_missions(rewarded, enhanced, enhancement, directory, card.cardId)
    retry = rpc("/api.Card/Enhance", cardId=card.cardId, level=2)
    _require(not _mission_payloads(retry.commonResponse.updatedData), "same-level retry emitted a mission delta")
    _require(_digest(user()) == _digest(enhanced), "same-level retry consumed resources or changed the card")

    stage(130)
    old_sequence = enhanced.user.deckSequence
    first_deck = next(row for row in enhanced.decks if row.number == 1)
    first_positions = [row for row in enhanced.deckPositions if row.number == 1]
    _require(len(first_positions) == 5, "requires the original five-slot starter unit")
    rpc("/api.Deck/Save", number=0, name="QA tutorial unit", deckEditType=2,
        userDeckPositions=[{"position": row.position, "cardId": row.cardId} for row in first_positions])
    decked = user()
    allocated = max(old_sequence, *(row.number for row in enhanced.decks)) + 1
    _require(decked.user.deckSequence == allocated and len(decked.decks) == len(enhanced.decks) + 1,
             "Number=0 did not allocate one new unit")
    _require(next(row for row in decked.decks if row.number == 1) == first_deck
             and [row for row in decked.deckPositions if row.number == 1] == first_positions,
             "new unit changed the original unit")
    _require([(r.position, r.cardId) for r in decked.deckPositions if r.number == allocated]
             == [(r.position, r.cardId) for r in first_positions], "client-selected Auto unit differs")

    message = next(row for row in rows("Message") if row["id"] == setting["tutorialMessageId"])
    group = message["messageGroupId"]
    listing = rpc("/api.Message/ListGroup")
    info = next((row for row in listing.infos if row.messageGroupId == group), None)
    _require(info is not None and info.HasField("latestTimelineInfo"), "tutorial message group is absent")
    timeline_id = info.latestTimelineInfo.timelineId
    # Timeline uses an exclusive older-than cursor; zero requests the newest
    # page (Android 6.1.1 0x58dff98), rather than looking up the latest ID.
    timeline = rpc("/api.Message/Timeline", messageGroupId=group, timelineId=0)
    _require(len(timeline.infos) == 1 and timeline.infos[0].messageId == message["id"], "tutorial timeline is absent")
    arrival = timeline.infos[0].arrivedTime
    _require(timeline_id > 0 and arrival > 0, "message has no local identity/time")
    arrived_snapshot = user()
    rpc("/api.Message/ListGroup")
    _require(_digest(user()) == _digest(arrived_snapshot), "message read changed state")
    details = {r["messageDetailId"]: r for r in message["details"]}
    current = message["details"][0]
    choices = []
    visited = set()
    while True:
        key = current["messageDetailId"]
        _require(key not in visited, "tutorial message graph has a cycle")
        visited.add(key)
        if current.get("choiceText"):
            choices.append(key)
        following = current.get("nextMessageDetailIds", [])
        if not following:
            break
        _require(len(following) == 1, "QA tutorial needs an unambiguous message path")
        current = details[following[0]]
    rpc("/api.Message/Save", messageGroupId=group, timelineId=timeline_id,
        messageDetailId=current["messageDetailId"], selectMessageDetailIds=choices)
    stage(140)
    rpc("/api.Message/Finish", messageGroupId=group, timelineId=timeline_id, selectMessageDetailIds=choices)
    finished = user()
    row = next(row for row in finished.messages if row.messageId == message["id"])
    status = row.DESCRIPTOR.fields_by_name["messageStatusType"].enum_type.values_by_number[row.messageStatusType].name
    _require(status.endswith("Finished") and row.arrivedTime == arrival and list(row.selectMessageDetailIds) == choices,
             "finished message state differs")
    _require(not any(r.messageId == message["id"] for r in finished.messageSchedules), "finished schedule remains")
    rpc("/api.Message/Finish", messageGroupId=group, timelineId=timeline_id, selectMessageDetailIds=choices)
    _require(_digest(user()) == _digest(finished), "finish retry changed state")
    stage(150)
    final = user()
    _require(final.user.tutorialClearedTime > 0 and next(r.step for r in final.tutorials if r.tutorialType == 1) == 150,
             "explicit completion did not persist")
    stage(150)
    _require(_digest(user()) == _digest(final), "completion retry changed the completion time")
    _require(final.userPublic == before.userPublic and final.user.name == before.user.name,
             "continuation changed local display/identity")
    _require(_mission_payloads(final) == _mission_payloads(enhanced),
             "post-enhancement continuation changed mission state")
    # Compare every unrelated top-level container, including its unknown fields.
    allowed = {"user", "totalCount", "tutorials", "items", "points", "cards", "decks", "deckPositions", "messages", "messageSchedules"}
    unchanged_before = type(before).FromString(before.SerializeToString())
    unchanged_after = type(final).FromString(final.SerializeToString())
    # The complete ordered mission collection was compared above against the
    # independently projected enhancement delta, including unknown row fields.
    if "missions" in unchanged_before.DESCRIPTOR.fields_by_name:
        unchanged_before.ClearField("missions")
        unchanged_after.ClearField("missions")
    for field in allowed:
        unchanged_before.ClearField(field)
        unchanged_after.ClearField(field)
    _require(unchanged_before == unchanged_after, "unrelated snapshot containers changed")
    return {
        "platform": label, "lesson_reward_once": True, "enhancement_cost": cost,
        "enhancement_master_projection": True, "deck_number_allocated": allocated,
        "original_deck_preserved": True, "tutorial_message_saved_finished": True,
        "unrelated_snapshot_preserved": True, "completed_step": 150,
        "snapshot_sha256": _digest(final),
    }
