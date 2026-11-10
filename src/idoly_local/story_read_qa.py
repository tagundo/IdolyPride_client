"""Opt-in native QA for two public story reads on the disposable QA profile.

The oracle uses pinned public eligibility and bundled master relationships. It
does not import the server's story-read rules or copy captured account totals.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .lesson_qa import (_clock_digest, _home_progress, assert_ordinary_lesson_home,
                        assert_ordinary_lesson_progress)
from .story_qa import _baseline, _masters, _references, run_story_catalog_checks


_USER = "/api.User/Get"
_HOME = "/api.Home/Enter"
_READ = "/api.Story/Read"
_EVENT = "/api.Story/ReadEvent"
_EXTRA = "/api.Story/ReadExtra"
_STONE = "rd_auto;stone;;30"


def _require(condition, message):
    if not condition:
        raise RuntimeError("Story read QA: " + message)


def _bytes(value):
    return value.SerializeToString(deterministic=True)


def _digest(value):
    return hashlib.sha256(_bytes(value)).hexdigest()


def _oracle(schema, master_dir):
    directory = Path(master_dir)
    canonical, tables = _baseline(schema, directory), _masters(directory)
    _references(canonical["event"], canonical["extra"], tables)
    events, extras = [], []
    for info in canonical["event"].infos:
        definitions = {row["episode"]: row["storyId"] for row in tables["EventStory"][info.id]["episodes"]}
        for episode in info.episodes:
            _require(episode.unlocked, "the public event baseline includes a locked episode")
            events.append((info.id, episode.episode, definitions[episode.episode]))
    for part in canonical["extra"].infos:
        _require(part.unlocked, "the public extra baseline includes a locked part")
        for info in part.stories:
            _require(info.unlocked, "the public extra baseline includes a locked story")
            definitions = {row["episode"]: row["storyId"] for row in tables["ExtraStory"][info.id]["episodes"]}
            for episode in info.episodes:
                _require(episode.unlocked, "the public extra baseline includes a locked episode")
                extras.append((info.id, episode.episode, definitions[episode.episode]))
    identities = {row[2] for row in events + extras}
    no_reward = {identity for identity in identities if tables["Story"][identity].get("rewardId", "") == ""}
    rewarded = {identity for identity in identities if tables["Story"][identity].get("rewardId") == _STONE}
    _require((len(events), len(extras), len(identities), len(no_reward), len(rewarded)) == (272, 154, 425, 143, 282)
             and no_reward.isdisjoint(rewarded) and no_reward | rewarded == identities,
             "the independent public story/reward scope differs from 425/143/282")
    event = next((row for row in events if row[2] in rewarded), None)
    extra = next((row for row in extras if row[2] in no_reward), None)
    _require(event is not None and extra is not None and event[2] != extra[2],
             "the public baseline lacks distinct reward and no-reward QA cases")
    settings = json.loads((directory / "Setting.json").read_text(encoding="utf-8"))
    # Protobuf JSON represents this master's int64 limit as a decimal string.
    limit = settings[0].get("freeStoneLimit") if len(settings) == 1 else None
    if isinstance(limit, str) and limit.isascii() and limit.isdigit():
        limit = int(limit)
    _require(type(limit) is int and 30 <= limit <= (1 << 31) - 1,
             "the bundled free Stone limit is invalid")
    return event, extra, limit


def _rpc(schema, invoke, path, **fields):
    return invoke(path, schema.request_type(path)(**fields))


def _story(snapshot, identity):
    matches = [row for row in snapshot.stories if row.storyId == identity]
    _require(len(matches) == 1 and matches[0].statusType == 2,
             "the authoritative snapshot does not contain exactly one completed story")
    return matches[0]


def _response(schema, path, response, snapshot, identity, *, reward=False, before_free=None, amount=0):
    expected = schema.response_type(path)()
    expected.commonResponse.updatedData.stories.add().CopyFrom(_story(snapshot, identity))
    expected.commonResponse.deletedData.SetInParent()
    if reward:
        expected.commonResponse.updatedData.balance.CopyFrom(snapshot.balance)
    if amount:
        expected.rewards.add(resourceType=15, resourceId="", beforeAmount=before_free,
                             afterAmount=snapshot.balance.freeBalance, amountI64=amount)
    _require(_bytes(response) == _bytes(expected),
             "read response differs from the exact story, current wallet and earned-reward projection")


def _snapshot(schema, payload):
    return (schema.response_type(_USER).FromString(bytes(payload))
            if isinstance(payload, (bytes, bytearray, memoryview)) else payload)


def assert_story_read_snapshot(schema, payload, receipt):
    snapshot = _snapshot(schema, payload)
    _require(_digest(snapshot) == receipt["snapshot_sha256"], "restart or retry changed the read snapshot")
    _require(snapshot.balance.freeBalance == receipt["free_stone_after"]
             and snapshot.balance.paidBalance == receipt["paid_stone_before"]
             and len(snapshot.stories) == receipt["story_rows_after"],
             "restart changed story rows or local wallet totals")


def assert_story_read_progress(schema, payload, receipt):
    assert_ordinary_lesson_progress(schema, payload, receipt)


def assert_story_read_home(schema, response, receipt):
    assert_ordinary_lesson_home(schema, response, receipt)


def _retries(schema, invoke, expected, event, extra):
    for path, fields, identity, reward in (
            (_EVENT, {"eventStoryId": event[0], "episode": event[1], "isLast": True}, event[2], True),
            (_READ, {"storyId": event[2], "isLast": False}, event[2], True),
            (_EXTRA, {"extraStoryId": extra[0], "episode": extra[1], "isLast": False}, extra[2], False),
            (_READ, {"storyId": extra[2], "isLast": True}, extra[2], False)):
        response = _rpc(schema, invoke, path, **fields)
        _response(schema, path, response, expected, identity, reward=reward)
        _require(_bytes(_rpc(schema, invoke, _USER)) == _bytes(expected),
                 "a repeated or cross-route read changed the snapshot or paid twice")


def assert_story_read_retries(schema, invoke, master_dir, receipt):
    """Reuse the existing session after a runtime restart; no reward can recur."""
    event, extra, _limit = _oracle(schema, master_dir)
    expected = _rpc(schema, invoke, _USER)
    assert_story_read_snapshot(schema, expected, receipt)
    _retries(schema, invoke, expected, event, extra)
    assert_story_read_home(schema, _rpc(schema, invoke, _HOME, skipUpdate=True), receipt)
    assert_story_read_snapshot(schema, _rpc(schema, invoke, _USER), receipt)
    run_story_catalog_checks(schema, invoke, master_dir)
    assert_story_read_snapshot(schema, _rpc(schema, invoke, _USER), receipt)


def run_story_read_checks(schema, invoke, master_dir, *, label="native"):
    """Skip one reward event, finish one no-reward extra, then retry both."""
    event, extra, limit = _oracle(schema, master_dir)
    before = _rpc(schema, invoke, _USER)
    _require(before.HasField("balance") and 0 <= before.balance.freeBalance <= limit - 30,
             "the dedicated QA profile cannot accept the configured free Stone reward")
    _require(not any(row.storyId in (event[2], extra[2]) for row in before.stories),
             "requires unread public QA stories; existing progress must never be cleared")
    clock = _home_progress(_rpc(schema, invoke, _HOME, skipUpdate=True))
    _require(_bytes(_rpc(schema, invoke, _USER)) == _bytes(before), "Home.Enter changed the pre-read snapshot")
    expected = type(before)()
    expected.CopyFrom(before)
    expected.stories.add(storyId=event[2], statusType=2)
    expected.balance.freeBalance += 30
    response = _rpc(schema, invoke, _EVENT, eventStoryId=event[0], episode=event[1], isLast=False)
    _response(schema, _EVENT, response, expected, event[2], reward=True,
              before_free=before.balance.freeBalance, amount=30)
    _require(_bytes(_rpc(schema, invoke, _USER)) == _bytes(expected),
             "the first skipped event changed more than one Read2 row and free Stone30")
    for path, fields in ((_EVENT, {"eventStoryId": event[0], "episode": event[1], "isLast": True}),
                         (_READ, {"storyId": event[2], "isLast": False})):
        _response(schema, path, _rpc(schema, invoke, path, **fields), expected, event[2], reward=True)
        _require(_bytes(_rpc(schema, invoke, _USER)) == _bytes(expected), "event retry granted a second reward")
    expected.stories.add(storyId=extra[2], statusType=2)
    response = _rpc(schema, invoke, _EXTRA, extraStoryId=extra[0], episode=extra[1], isLast=True)
    _response(schema, _EXTRA, response, expected, extra[2])
    _require(_bytes(_rpc(schema, invoke, _USER)) == _bytes(expected),
             "the first completed extra changed more than its single Read2 row")
    _retries(schema, invoke, expected, event, extra)
    final_home = _home_progress(_rpc(schema, invoke, _HOME, skipUpdate=True))
    _require(_clock_digest(final_home) == _clock_digest(clock), "story reads changed the stored lesson clock")
    _require(_bytes(_rpc(schema, invoke, _USER)) == _bytes(expected), "post-read Home.Enter changed the snapshot")
    catalogs = run_story_catalog_checks(schema, invoke, master_dir)
    _require(catalogs["story_catalog_preserved_read_count"] >= 2,
             "read-only catalogs lost the newly completed Read2 stories")
    return {"platform": label, "audited_story_count": 425, "no_reward_story_count": 143,
            "free_stone_story_count": 282, "story_rows_added": 2, "free_stone_delta": 30,
            "event_skipped_reward_once": True, "extra_completed_without_reward": True,
            "retries_and_cross_route_no_grant": True, "authoritative_common": True,
            "exact_snapshot_projection": True, "lesson_clock_preserved": True,
            "catalog_eligibility_preserved": True,
            "snapshot_sha256": _digest(expected), "clock_sha256": _clock_digest(clock),
            "free_stone_after": expected.balance.freeBalance, "paid_stone_before": before.balance.paidBalance,
            "story_rows_after": len(expected.stories)}
