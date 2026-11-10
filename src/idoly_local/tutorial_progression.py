"""Transactional opening-tutorial rewards and ordinary early card lessons.

The recovered 6.1.1 response 00034 advances GameStart from 100 to 110 while
granting the Setting-defined ten-minute lesson reward. That same checkpoint
is the receipt marker; captured absolute account totals are never imported.
Card parameter/cost projection lives in the pure card_progression module.
"""
from __future__ import annotations

from pathlib import Path
import time

from google.protobuf.message import DecodeError

from .gameplay import _Catalog
from .rpc import RpcCode, RpcFailure


_USER = "/api.User/Get"
_LESSON = "/api.Tutorial/ReceiveLessonReward"
_ENHANCE = "/api.Card/Enhance"
_PIECES = "item-card_enhance"
_MAX_INT64 = (1 << 63) - 1


def _invalid(message):
    raise RpcFailure(RpcCode.FAILED_PRECONDITION, message)


def _number(value, description, *, positive=False):
    if type(value) is not int and not isinstance(value, str):
        _invalid("Invalid local " + description)
    try:
        result = int(value)
    except (ValueError, OverflowError):
        _invalid("Invalid local " + description)
    if (result < int(positive) or result > _MAX_INT64
            or isinstance(value, str) and str(result) != value):
        _invalid("Invalid local " + description)
    return result


class TutorialProgression:
    """Apply verified local deltas under State's existing write transaction."""

    def __init__(self, schema, state, profile, master_dir: Path | None = None):
        self.schema, self.state, self.profile = schema, state, profile
        self.master_dir = Path(master_dir) if master_dir is not None else None
        self.catalog = _Catalog(self.master_dir)

    def _snapshot(self, payload):
        try:
            snapshot = self.schema.response_type(_USER).FromString(payload)
        except DecodeError:
            _invalid("Local profile snapshot is malformed")
        if not snapshot.HasField("user"):
            _invalid("Local profile has no user state")
        return snapshot

    def _setting(self):
        rows = self.catalog.rows("Setting", required=True)
        if len(rows) != 1:
            _invalid("Local progression needs one Setting master row")
        return rows[0]

    def _manager_level(self, experience):
        experience = _number(experience, "manager experience")
        levels, thresholds = {}, set()
        for row in self.catalog.rows("ManagerLevel", required=True):
            level = _number(row.get("level"), "manager level", positive=True)
            threshold = _number(row.get("requiredExp"), "manager experience threshold")
            if level > (1 << 31) - 1 or level in levels or threshold in thresholds:
                _invalid("Ambiguous local manager level definition")
            levels[level] = threshold
            thresholds.add(threshold)
        ordered = sorted(levels.items())
        if (not ordered or ordered[0] != (1, 0)
                or any(a[1] >= b[1] for a, b in zip(ordered, ordered[1:]))):
            _invalid("Invalid local manager level definition")
        return max(level for level, threshold in ordered if threshold <= experience)

    @staticmethod
    def _permanent_item(snapshot):
        rows = [row for row in snapshot.items if row.itemId == _PIECES and row.expiredTime == 0]
        if len(rows) > 1:
            _invalid("Local enhancement item rows are ambiguous")
        if rows:
            _number(rows[0].amount, "enhancement item amount")
        return rows[0] if rows else None

    @staticmethod
    def _lesson_common(result, snapshot, tutorial):
        result.commonResponse.SetInParent()
        updated = result.commonResponse.updatedData
        updated.user.CopyFrom(snapshot.user)
        updated.totalCount.CopyFrom(snapshot.totalCount)
        updated.tutorials.add().CopyFrom(tutorial)
        for row in snapshot.items:
            if row.itemId == _PIECES and row.expiredTime == 0:
                updated.items.add().CopyFrom(row)
        for row in snapshot.points:
            if row.pointType == 1:
                updated.points.add().CopyFrom(row)

    def _lesson(self, snapshot, result):
        tutorials = [row for row in snapshot.tutorials if row.tutorialType == 1]
        if len(tutorials) != 1 or tutorials[0].step < 100:
            _invalid("The opening live must finish before receiving its lesson reward")
        tutorial = tutorials[0]
        if tutorial.step >= 110:
            # Re-project current state, rather than a stale cached first reply.
            self._lesson_common(result, snapshot, tutorial)
            return
        if tutorial.step != 100:
            _invalid("The local tutorial is not at the lesson reward checkpoint")
        setting = self._setting()
        minutes = _number(setting.get("tutorialActivityLessonPromoteMinutes"), "tutorial lesson minutes", positive=True)
        rewards = tuple(_number(minutes * _number(setting.get(name), "tutorial lesson reward", positive=True),
                                "tutorial lesson reward", positive=True) for name in (
            "tutorialActivityLessonRewardGoldPerMinute",
            "tutorialActivityLessonRewardManagerExpPerMinute",
            "tutorialActivityLessonRewardCardEnhanceItemPerMinute"))
        gold, experience, pieces = rewards
        if _PIECES not in self.catalog.ids("Item", required=True):
            _invalid("Local tutorial enhancement item is missing")
        points = [row for row in snapshot.points if row.pointType == 1]
        if len(points) > 1:
            _invalid("Local gold point rows are ambiguous")
        item = self._permanent_item(snapshot)
        old_gold = _number(points[0].amount if points else 0, "gold amount")
        gold_total = _number(old_gold + gold, "gold amount")
        piece_total = _number((item.amount if item is not None else 0) + pieces, "enhancement item amount")
        if (gold_total > _number(setting.get("goldLimit"), "gold limit", positive=True)
                or piece_total > _number(setting.get("itemLimit"), "item limit", positive=True)):
            _invalid("Tutorial reward would exceed the local resource limit")
        old_experience = _number(snapshot.user.managerExp, "manager experience")
        if snapshot.user.managerLevel != self._manager_level(old_experience):
            _invalid("Local manager level and experience disagree")
        new_experience = _number(old_experience + experience, "manager experience")
        new_level = self._manager_level(new_experience)
        lifetime_gold = _number(_number(snapshot.totalCount.pointGoldAmount, "lifetime gold amount") + gold,
                                "lifetime gold amount")
        # All master, ownership, amount and range checks precede mutation.
        (points[0] if points else snapshot.points.add(pointType=1)).amount = gold_total
        (item if item is not None else snapshot.items.add(itemId=_PIECES)).amount = piece_total
        snapshot.user.managerExp, snapshot.user.managerLevel = new_experience, new_level
        snapshot.totalCount.pointGoldAmount = lifetime_gold
        tutorial.step = 110
        for kind, identity, amount in ((8, "", gold), (14, "", experience), (1, _PIECES, pieces)):
            result.rewards.add(resourceType=kind, resourceId=identity, amount=amount)
        self._lesson_common(result, snapshot, tutorial)

    def _enhance(self, snapshot, request, result):
        if not request.cardId or request.level <= 0:
            raise RpcFailure(RpcCode.INVALID_ARGUMENT, "A card identity and positive target level are required")
        matches = [row for row in snapshot.cards if row.cardId == request.cardId]
        if not matches:
            raise RpcFailure(RpcCode.INVALID_ARGUMENT, "The requested card is not owned")
        if len(matches) != 1:
            _invalid("Local owned card rows are ambiguous")
        card = matches[0]
        if request.level < card.level:
            raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Card enhancement cannot lower its level")
        if snapshot.user.managerLevel != self._manager_level(snapshot.user.managerExp):
            _invalid("Local manager level and experience disagree")
        from .card_progression import prepare_enhancement

        version = self.state.starter_version(self.profile)
        plan = prepare_enhancement(self.schema, self.master_dir, card, request.level,
                                   manager_level=snapshot.user.managerLevel,
                                   normalize_starter_rarity=version is not None and version >= 4 and card.rarity == 3)
        item = self._permanent_item(snapshot)
        available = item.amount if item is not None else 0
        if available < plan.required_pieces:
            _invalid("Not enough enhancement items")
        if plan.changed:
            plan.card.lastEnhanceTime = max(card.lastEnhanceTime, time.time_ns() // 1000000)
            card.CopyFrom(plan.card)
            if plan.required_pieces:
                item.amount -= plan.required_pieces
        result.commonResponse.SetInParent()
        result.commonResponse.updatedData.cards.add().CopyFrom(card)
        if item is not None:
            result.commonResponse.updatedData.items.add().CopyFrom(item)

    def handle(self, path, plain):
        if path not in (_LESSON, _ENHANCE) or self.master_dir is None:
            return None
        try:
            request = self.schema.request_type(path).FromString(plain)
        except DecodeError:
            raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Malformed local progression request") from None
        result = self.schema.response_type(path)()

        def update(payload):
            snapshot = self._snapshot(payload)
            if path == _LESSON:
                self._lesson(snapshot, result)
            else:
                self._enhance(snapshot, request, result)
            return snapshot.SerializeToString()

        try:
            self.state.mutate_snapshot(self.profile, self.schema.fingerprint, update)
        except ValueError:
            _invalid("Local profile cannot be updated with this schema")
        return result.SerializeToString()
