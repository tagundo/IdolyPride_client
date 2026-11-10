"""Opt-in synthetic-profile QA for ordinary lesson accrual over native RPCs.

The server never invokes this flow for a player's profile. Unlike unit tests,
native callers use the real monotonic clock and wait for a complete ten-second
interval before claiming the base-only local reward.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time


_USER = "/api.User/Get"
_HOME = "/api.Home/Enter"
_RECEIVE = "/api.Activity/ReceiveLessonReward"
_AMOUNTS = ("rewardGoldAmount", "rewardManagerExpAmount", "rewardCardEnhanceItemAmount")
_RATES = ("stepRewardGold", "stepRewardManagerExp", "stepRewardCardEnhanceItem")
_ITEM = "item-card_enhance"
_AREA = "area-main-001"
_STEP_MS = 10000
_WINDOW_MS = 12 * 60 * 60 * 1000


def _require(condition, message):
    if not condition:
        raise RuntimeError("Ordinary lesson QA: " + message)


def _digest(message):
    return hashlib.sha256(message.SerializeToString(deterministic=True)).hexdigest()


def _user(schema, payload):
    return (schema.response_type(_USER).FromString(bytes(payload))
            if isinstance(payload, (bytes, bytearray, memoryview)) else payload)


def _progress(schema, payload):
    return (type(schema.response_type(_RECEIVE)().progress).FromString(bytes(payload))
            if isinstance(payload, (bytes, bytearray, memoryview)) else payload)


def _clock_digest(progress):
    clock = type(progress)()
    clock.CopyFrom(progress)
    for field in _AMOUNTS:
        clock.ClearField(field)
    return _digest(clock)


def _policy(progress):
    _require(progress.currentAreaId == _AREA and progress.lastReceiveTime > 0,
             "clock does not belong to the initial main area")
    _require(progress.maxRewardTime - progress.lastReceiveTime == _WINDOW_MS,
             "clock does not preserve the twelve-hour window")
    _require(tuple(getattr(progress, field) for field in _RATES) == (5, 8, 3)
             and not progress.dailyPromoteCount, "base reward rates or promotion state differ")
    amounts = tuple(getattr(progress, field) for field in _AMOUNTS)
    _require(all(value >= 0 for value in amounts) and amounts[0] % 5 == 0
             and amounts == (amounts[0], amounts[0] // 5 * 8, amounts[0] // 5 * 3),
             "pending amounts do not represent complete 5/8/3 base steps")


def _resources(snapshot):
    points = [row for row in snapshot.points if row.pointType == 1]
    pieces = [row for row in snapshot.items if row.itemId == _ITEM and not row.expiredTime]
    _require(len(points) == len(pieces) == 1, "synthetic post-tutorial resource rows are ambiguous or absent")
    return points[0], pieces[0]


def _totals(snapshot):
    point, pieces = _resources(snapshot)
    return {"gold": point.amount, "manager_exp": snapshot.user.managerExp,
            "manager_level": snapshot.user.managerLevel, "enhance_items": pieces.amount,
            "lifetime_gold": snapshot.totalCount.pointGoldAmount}


def _home_progress(response):
    _require(response.HasField("lessonProgress") and response.HasField("lessonInfo")
             and response.lessonInfo.HasField("lessonProgress"), "Home.Enter omitted a lesson clock")
    _require(response.lessonProgress == response.lessonInfo.lessonProgress,
             "Home.Enter exposes two different lesson clocks")
    _policy(response.lessonProgress)
    return response.lessonProgress


def assert_ordinary_lesson_snapshot(schema, payload, receipt):
    snapshot = _user(schema, payload)
    _require(_digest(snapshot) == receipt["snapshot_sha256"], "restart changed the claimed snapshot")
    _require(_totals(snapshot) == receipt["resource_totals"], "restart changed claimed resource totals")
    starts = [row for row in snapshot.tutorials if row.tutorialType == 1]
    _require(len(starts) == 1 and starts[0].step == 150 and snapshot.user.tutorialClearedTime > 0,
             "ordinary claim changed the completed opening tutorial")


def assert_ordinary_lesson_progress(schema, payload, receipt):
    progress = _progress(schema, payload)
    _policy(progress)
    _require(_clock_digest(progress) == receipt["clock_sha256"],
             "restart or Home.Enter reset the persistent lesson clock")


def assert_ordinary_lesson_home(schema, response, receipt):
    assert_ordinary_lesson_progress(schema, _home_progress(response), receipt)


def run_ordinary_lesson_claim(schema, invoke, master_dir, *, label="native"):
    """Wait for a real interval, claim once, and immediately retry via RPC."""
    def rpc(path):
        return invoke(path, schema.request_type(path)())

    before = rpc(_USER)
    starts = [row for row in before.tutorials if row.tutorialType == 1]
    _require(len(starts) == 1 and starts[0].step == 150 and before.user.tutorialClearedTime > 0,
             "requires the dedicated completed synthetic QA profile")
    _resources(before)
    first = _home_progress(rpc(_HOME))
    _require(not any(getattr(first, field) for field in _AMOUNTS),
             "requires a fresh post-tutorial ordinary lesson clock without historical backfill")
    _require(_digest(rpc(_USER)) == _digest(before), "initial Home.Enter granted resources")

    began = time.monotonic()
    time.sleep(10.1)
    waited_ms = int((time.monotonic() - began) * 1000)
    _require(waited_ms >= _STEP_MS, "a complete real ten-second interval was not observed")
    preview = _home_progress(rpc(_HOME))
    _require(_clock_digest(preview) == _clock_digest(first), "Home.Enter reset the accrual anchor")
    _require(preview.rewardGoldAmount >= 5, "elapsed interval did not produce a pending base step")
    _require(_digest(rpc(_USER)) == _digest(before), "pending Home.Enter granted resources")

    claimed = rpc(_RECEIVE)
    retry_began = time.monotonic()
    retry = rpc(_RECEIVE)  # Deliberately no other request between claim/retry.
    _require(time.monotonic() - retry_began < 10, "retry was not within the same lesson interval")
    for response in (claimed, retry):
        _require(response.HasField("progress") and response.HasField("commonResponse"),
                 "claim omitted authoritative clock or common response")
        _policy(response.progress)
        _require(not response.campaignEffects and not response.campaignDropRewards,
                 "ordinary local claim fabricated campaigns or drops")
        _require(not any(getattr(response.progress, field) for field in _AMOUNTS),
                 "claim returned unpaid pending amounts")
    advance = claimed.progress.lastReceiveTime - first.lastReceiveTime
    _require(advance >= _STEP_MS and advance % _STEP_MS == 0,
             "claim did not advance the original anchor by complete ten-second steps")
    steps = advance // _STEP_MS
    deltas = (steps * 5, steps * 8, steps * 3)
    _require([(row.resourceType, row.resourceId, row.amount) for row in claimed.rewards]
             == [(8, "", deltas[0]), (14, "", deltas[1]), (1, _ITEM, deltas[2])],
             "claim reward differs from the independent 5/8/3 base-step oracle")
    _require(not retry.rewards and retry.progress == claimed.progress
             and retry.commonResponse == claimed.commonResponse,
             "immediate retry paid twice, changed the clock, or echoed stale resource totals")

    after = rpc(_USER)
    expected = type(before)()
    expected.CopyFrom(before)
    point, pieces = _resources(expected)
    point.amount += deltas[0]
    pieces.amount += deltas[2]
    expected.user.managerExp += deltas[1]
    levels = json.loads((Path(master_dir) / "ManagerLevel.json").read_text(encoding="utf-8"))
    eligible = [int(row["level"]) for row in levels if int(row["requiredExp"]) <= expected.user.managerExp]
    _require(bool(eligible), "manager EXP does not resolve through the bundled public level table")
    expected.user.managerLevel = max(eligible)
    expected.totalCount.pointGoldAmount += deltas[0]
    _require(_digest(after) == _digest(expected), "claim changed unrelated state or applied incorrect resource deltas")
    actual_point, actual_pieces = _resources(after)
    updated = retry.commonResponse.updatedData
    _require(updated.user == after.user and updated.totalCount == after.totalCount
             and list(updated.points) == [actual_point] and list(updated.items) == [actual_pieces],
             "retry common response does not echo the authoritative claimed resources")
    final_home = _home_progress(rpc(_HOME))
    _require(_clock_digest(final_home) == _clock_digest(claimed.progress),
             "Home.Enter and Activity.ReceiveLessonReward do not share the same stored clock")
    _require(_digest(rpc(_USER)) == _digest(after), "post-claim Home.Enter changed resources")
    return {"platform": label, "waited_milliseconds": waited_ms, "elapsed_steps": steps,
            "gold_delta": deltas[0], "manager_exp_delta": deltas[1], "enhance_item_delta": deltas[2],
            "immediate_retry_no_grant": True, "home_shared_clock": True,
            "home_previews_preserve_snapshot": True, "unrelated_snapshot_preserved": True,
            "snapshot_sha256": _digest(after), "clock_sha256": _clock_digest(claimed.progress),
            "resource_totals": _totals(after)}
