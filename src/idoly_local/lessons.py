"""Persistent base-only ordinary lesson accrual for the initial main area.

Public 6.1.1 fresh Home.Enter captures establish area-main-001's 5 gold,
8 manager XP and 3 lesson pieces per ten seconds, with a twelve-hour window.
The unexplained extra XP in those captures is deliberately not reproduced:
this explicit local policy has no campaigns, drops, boosts or area repricing.
Tutorial.ReceiveLessonReward is a separate fixed one-time transaction.
"""
from __future__ import annotations

from pathlib import Path
import time

from google.protobuf import message_factory
from google.protobuf.message import DecodeError

from .gameplay import Gameplay, _Catalog
from .rpc import RpcCode, RpcFailure
from .tutorial_progression import TutorialProgression, _number


_RECEIVE = "/api.Activity/ReceiveLessonReward"
_USER = "/api.User/Get"
_AREA = "area-main-001"
_PIECES = "item-card_enhance"
_WINDOW_MS = 12 * 60 * 60 * 1000
_STEP_MS = 10000
_MAX_INT32 = (1 << 31) - 1
_RATES = (5, 8, 3)
_RATE_FIELDS = ("stepRewardGold", "stepRewardManagerExp", "stepRewardCardEnhanceItem")
_AMOUNT_FIELDS = ("rewardGoldAmount", "rewardManagerExpAmount", "rewardCardEnhanceItemAmount")


def _now_ms():
    return time.time_ns() // 1000000


def _fail(message):
    raise RpcFailure(RpcCode.FAILED_PRECONDITION, message)


class _TutorialPreview(Exception):
    """Roll back the State transaction before returning an unsaved preview."""


class OrdinaryLessons:
    """Keep Home previews and claims on one per-profile, atomic lesson clock."""

    def __init__(self, schema, state, profile, master_dir: Path | None = None):
        self.schema, self.state, self.profile = schema, state, profile
        self.master_dir = Path(master_dir) if master_dir is not None else None
        self.catalog = _Catalog(self.master_dir)
        self._manager = TutorialProgression(schema, state, profile, self.master_dir)

    def _progress_type(self):
        field = self.schema.response_type(_RECEIVE).DESCRIPTOR.fields_by_name["progress"]
        return message_factory.GetMessageClass(field.message_type)

    def _snapshot(self, raw):
        try:
            snapshot = self.schema.response_type(_USER).FromString(raw)
        except DecodeError:
            _fail("Local profile snapshot is malformed")
        if not snapshot.HasField("user"):
            _fail("Local profile has no user state")
        return snapshot

    @staticmethod
    def _finished(snapshot):
        rows = [row for row in snapshot.tutorials if row.tutorialType == 1]
        if len(rows) > 1:
            _fail("Local opening tutorial state is ambiguous")
        return len(rows) == 1 and rows[0].step >= 150

    def _area(self, identity):
        if identity != _AREA:
            _fail("Ordinary lessons currently support only the initial main area")
        areas = self.catalog.main_areas()
        if not areas or areas[0]["id"] != _AREA:
            _fail("Local lesson catalog has no supported initial main area")
        settings = self.catalog.rows("Setting", required=True)
        if len(settings) != 1 or settings[0].get("secondsPerActivityLessonStep") != 10:
            _fail("Local ordinary lesson step duration is unsupported")
        return settings[0]

    def _new(self, now, area):
        progress = self._progress_type()()
        progress.lastReceiveTime = _number(now, "lesson timestamp", positive=True)
        progress.maxRewardTime = _number(now + _WINDOW_MS, "lesson window", positive=True)
        progress.currentAreaId = area
        for name, value in zip(_RATE_FIELDS, _RATES):
            setattr(progress, name, value)
        return progress

    def _clock(self, raw, now, area):
        if raw is None:
            return self._new(now, area)
        try:
            progress = self._progress_type().FromString(raw)
        except DecodeError:
            _fail("Stored local lesson clock is malformed")
        anchor = _number(progress.lastReceiveTime, "lesson timestamp", positive=True)
        maximum = _number(progress.maxRewardTime, "lesson window", positive=True)
        if (progress.currentAreaId != area or maximum != anchor + _WINDOW_MS
                or tuple(getattr(progress, name) for name in _RATE_FIELDS) != _RATES
                or any(getattr(progress, name) for name in _AMOUNT_FIELDS)
                or progress.dailyPromoteCount):
            _fail("Stored local lesson clock uses an unsupported policy")
        return progress

    @staticmethod
    def _pending(progress, now):
        # A wall-clock rollback never moves the anchor backwards or creates XP.
        elapsed = max(0, min(now, progress.maxRewardTime) - progress.lastReceiveTime)
        steps = elapsed // _STEP_MS
        result = type(progress)()
        result.CopyFrom(progress)
        for name, rate in zip(_AMOUNT_FIELDS, _RATES):
            amount = steps * rate
            if amount > _MAX_INT32:
                _fail("Local lesson reward exceeds the protocol amount range")
            setattr(result, name, amount)
        return result, steps

    def _mutate(self, callback):
        try:
            return self.state.mutate_lesson_snapshot(self.profile, self.schema.fingerprint, callback)
        except ValueError:
            _fail("Local lesson state cannot be updated with this schema")

    def progress(self, current_area_id):
        """Return pending rewards without granting them or resetting the clock.

        Before the opening tutorial finishes, the displayed zero-reward clock
        is not saved. The first post-tutorial access starts at local now, so an
        upgrade or imported last-login timestamp never creates a backfill.
        """
        self._area(current_area_id)
        now = _number(_now_ms(), "lesson timestamp", positive=True)
        result = None

        def update(snapshot_raw, lesson_raw):
            nonlocal result
            snapshot = self._snapshot(snapshot_raw)
            if not self._finished(snapshot):
                raise _TutorialPreview()
            actual_area = Gameplay._current_area(self, snapshot)
            self._area(actual_area)
            if actual_area != current_area_id:
                _fail("Local lesson and home area disagree")
            clock = self._clock(lesson_raw, now, current_area_id)
            result, _ = self._pending(clock, now)
            return snapshot_raw, clock.SerializeToString()

        try:
            self._mutate(update)
        except _TutorialPreview:
            return self._new(now, current_area_id)
        return result

    @staticmethod
    def _resources(snapshot):
        points = [row for row in snapshot.points if row.pointType == 1]
        items = [row for row in snapshot.items if row.itemId == _PIECES and row.expiredTime == 0]
        if len(points) > 1 or len(items) > 1:
            _fail("Local lesson resource rows are ambiguous")
        point, item = points[0] if points else None, items[0] if items else None
        if point is not None:
            _number(point.amount, "gold amount")
        if item is not None:
            _number(item.amount, "enhancement item amount")
        return point, item

    @staticmethod
    def _common(result, snapshot, point, item):
        # Retry replies echo today's authoritative values, not the first claim's
        # cached totals. This also repairs a client that lost that first reply.
        common = result.commonResponse
        common.SetInParent()
        updated = common.updatedData
        updated.user.CopyFrom(snapshot.user)
        updated.totalCount.CopyFrom(snapshot.totalCount)
        if point is not None:
            updated.points.add().CopyFrom(point)
        if item is not None:
            updated.items.add().CopyFrom(item)

    def _grant(self, snapshot, pending, setting, point, item):
        amounts = tuple(getattr(pending, name) for name in _AMOUNT_FIELDS)
        gold, experience, pieces = amounts
        if _PIECES not in self.catalog.ids("Item", required=True):
            _fail("Local lesson enhancement item is missing")
        gold_total = _number((point.amount if point is not None else 0) + gold, "gold amount")
        piece_total = _number((item.amount if item is not None else 0) + pieces, "enhancement item amount")
        if (gold_total > _number(setting.get("goldLimit"), "gold limit", positive=True)
                or piece_total > _number(setting.get("itemLimit"), "item limit", positive=True)):
            _fail("Ordinary lesson reward would exceed the local resource limit")
        old_exp = _number(snapshot.user.managerExp, "manager experience")
        if snapshot.user.managerLevel != self._manager._manager_level(old_exp):
            _fail("Local manager level and experience disagree")
        new_exp = _number(old_exp + experience, "manager experience")
        new_level = self._manager._manager_level(new_exp)
        lifetime = _number(_number(snapshot.totalCount.pointGoldAmount, "lifetime gold amount") + gold,
                           "lifetime gold amount")
        # Nothing is changed until every catalog and amount check has passed.
        if point is None:
            point = snapshot.points.add(pointType=1)
        if item is None:
            item = snapshot.items.add(itemId=_PIECES, expiredTime=0)
        point.amount, item.amount = gold_total, piece_total
        snapshot.user.managerExp, snapshot.user.managerLevel = new_exp, new_level
        snapshot.totalCount.pointGoldAmount = lifetime
        return point, item

    def handle(self, path, plain):
        if path != _RECEIVE or self.master_dir is None:
            return None
        try:
            self.schema.request_type(path).FromString(plain)
        except DecodeError:
            raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Malformed ordinary lesson request") from None
        now = _number(_now_ms(), "lesson timestamp", positive=True)
        result = self.schema.response_type(path)()

        def update(snapshot_raw, lesson_raw):
            snapshot = self._snapshot(snapshot_raw)
            if not self._finished(snapshot):
                _fail("Finish the opening tutorial before receiving ordinary lesson rewards")
            area = Gameplay._current_area(self, snapshot)
            setting = self._area(area)
            clock = self._clock(lesson_raw, now, area)
            pending, steps = self._pending(clock, now)
            point, item = self._resources(snapshot)
            if steps:
                point, item = self._grant(snapshot, pending, setting, point, item)
                for kind, identity, field in ((8, "", _AMOUNT_FIELDS[0]), (14, "", _AMOUNT_FIELDS[1]),
                                               (1, _PIECES, _AMOUNT_FIELDS[2])):
                    result.rewards.add(resourceType=kind, resourceId=identity, amount=getattr(pending, field))
                # Advance against all elapsed time, not only the paid window.
                # Excess idle time is discarded; only the sub-step remainder
                # survives, preventing repeated claims from bypassing the cap.
                elapsed_steps = max(0, now - clock.lastReceiveTime) // _STEP_MS
                clock.lastReceiveTime = _number(clock.lastReceiveTime + elapsed_steps * _STEP_MS,
                                               "lesson timestamp", positive=True)
                clock.maxRewardTime = _number(clock.lastReceiveTime + _WINDOW_MS,
                                             "lesson window", positive=True)
                snapshot_raw = snapshot.SerializeToString()
            result.progress.CopyFrom(clock)
            self._common(result, snapshot, point, item)
            return snapshot_raw, clock.SerializeToString()

        self._mutate(update)
        return result.SerializeToString()
