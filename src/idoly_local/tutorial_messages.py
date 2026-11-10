"""Persist the opening tutorial's single, reward-free message conversation.

The 6.1.1 client needs ListGroup's populated latestTimelineInfo, then Timeline,
Save, Tutorial.Progress(140), and Finish. Only Setting.tutorialMessageId's
two-detail conversation is supported. All account rows and timestamps come
from the local snapshot; public captures are never loaded by this service.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import time

from google.protobuf.message import DecodeError

from .gameplay import _Catalog
from .rpc import RpcCode, RpcFailure


_USER = "/api.User/Get"
_PREFIX = "/api.Message/"
_ROUTES = {_PREFIX + name for name in ("ListGroup", "Timeline", "Save", "Finish", "Receive")}
_RECEIVED, _FINISHED = 3, 4


def _bad(detail):
    raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Invalid local tutorial message: " + detail)


def _now_ms():
    return time.time_ns() // 1_000_000


@dataclass(frozen=True)
class _Plan:
    message_id: str
    group_id: str
    character_id: str
    incoming_id: str
    reply_id: str


def _plan(catalog):
    settings = catalog.rows("Setting", required=True)
    if len(settings) != 1:
        _bad("one Setting row is required")
    message_id = settings[0].get("tutorialMessageId")
    if not isinstance(message_id, str) or not message_id:
        _bad("missing tutorial message setting")
    row = catalog.ids("Message", required=True).get(message_id)
    if row is None or row.get("type") != 1:
        _bad("unknown opening conversation")
    group_id, character_id = row.get("messageGroupId"), row.get("characterId")
    group = catalog.ids("MessageGroup", required=True).get(group_id) if isinstance(group_id, str) else None
    if (group is None or not isinstance(character_id, str) or not character_id
            or character_id not in catalog.ids("Character", required=True)
            or not isinstance(group.get("characterIds"), list)
            or character_id not in group["characterIds"]):
        _bad("message group or character reference")
    details = row.get("details")
    if not isinstance(details, list) or len(details) != 2 or any(not isinstance(item, dict) for item in details):
        _bad("only the two-detail opening conversation is supported")
    indexed = {}
    for item in details:
        key, following = item.get("messageDetailId"), item.get("nextMessageDetailIds")
        if (not isinstance(key, str) or not key or key in indexed
                or not isinstance(following, list)
                or any(not isinstance(value, str) or not value for value in following)
                or item.get("characterId", "") not in ("", character_id)
                or not isinstance(item.get("choiceText", ""), str)
                or item.get("telephoneId", "")
                or any(type(item.get(name, 0)) is not int or item.get(name, 0) != 0
                       for name in ("reliability", "delayMinutes", "readMinutes"))):
            _bad("unsupported tutorial detail or reward")
        indexed[key] = item
    incoming = [item for item in details if not item.get("choiceText")]
    replies = [item for item in details if item.get("choiceText")]
    if (len(incoming) != 1 or len(replies) != 1
            or incoming[0]["nextMessageDetailIds"] != [replies[0]["messageDetailId"]]
            or replies[0]["nextMessageDetailIds"]
            or incoming[0].get("characterId") != character_id):
        _bad("unsupported opening conversation path")
    return _Plan(message_id, group_id, character_id,
                 incoming[0]["messageDetailId"], replies[0]["messageDetailId"])


class TutorialMessages:
    """A finite local tutorial conversation, with snapshot transactions only."""

    def __init__(self, schema, state, profile, master_dir=None):
        self.schema, self.state, self.profile = schema, state, profile
        self.catalog = _Catalog(master_dir)
        self._loaded = None

    def _master(self):
        if self._loaded is None:
            self._loaded = _plan(self.catalog)
        return self._loaded

    def _timeline_id(self, plan, arrived_time):
        # A single fixed conversation needs identity, not a globally ordered ID.
        # Hashing also avoids multiplying Unix milliseconds beyond int64.
        identity = ("idoly-local-tutorial-message\0" + self.profile + "\0" + plan.message_id
                    + "\0" + str(arrived_time)).encode("utf-8")
        return (int.from_bytes(hashlib.sha256(identity).digest()[:8], "big") & ((1 << 63) - 1)) or 1

    def _parse(self, raw):
        try:
            snapshot = self.schema.response_type(_USER).FromString(raw)
        except DecodeError:
            _bad("malformed profile snapshot")
        if not snapshot.HasField("user"):
            _bad("missing user state")
        return snapshot

    @staticmethod
    def _step(snapshot):
        rows = [row for row in snapshot.tutorials if row.tutorialType == 1]
        if len(rows) > 1 or rows and rows[0].step < 0:
            _bad("ambiguous GameStart progress")
        return rows[0].step if rows else 0

    @staticmethod
    def _rows(snapshot, plan):
        messages = [row for row in snapshot.messages if row.messageId == plan.message_id]
        schedules = [row for row in snapshot.messageSchedules if row.messageId == plan.message_id]
        if len(messages) > 1 or len(schedules) > 1:
            _bad("duplicate tutorial message or schedule")
        return (messages[0] if messages else None), (schedules[0] if schedules else None)

    @staticmethod
    def _selection(message, plan):
        selected = tuple(message.selectMessageDetailIds)
        if selected not in ((), (plan.reply_id,)):
            _bad("stored tutorial choices do not match the master")
        return selected

    def _ensure(self, snapshot, plan):
        message, schedule = self._rows(snapshot, plan)
        changed = set()
        if message is None:
            if plan.character_id not in {row.characterId for row in snapshot.characters}:
                _bad("the tutorial character is not owned")
            arrived = _now_ms()
            if not 0 < arrived < (1 << 63):
                _bad("invalid local arrival time")
            message = snapshot.messages.add(messageId=plan.message_id,
                messageStatusType=_RECEIVED, arrivedTime=arrived)
            changed.add("messages")
        elif message.messageStatusType in (1, 2):
            # A pre-existing due tutorial schedule may also be received by the
            # client's scheduler before opening the conversation UI.
            now = _now_ms()
            if schedule is not None and schedule.scheduledTime > now:
                _bad("the scheduled tutorial message is not due")
            if not message.arrivedTime:
                message.arrivedTime = now
            message.messageStatusType = _RECEIVED
            changed.add("messages")
        if message.messageStatusType not in (_RECEIVED, _FINISHED) or message.arrivedTime <= 0:
            _bad("invalid received tutorial message")
        self._selection(message, plan)
        if message.messageStatusType == _RECEIVED and schedule is None:
            snapshot.messageSchedules.add(messageId=plan.message_id, scheduledTime=message.arrivedTime)
            changed.add("messageSchedules")
        return message, changed

    def _info(self, target, message, plan):
        target.messageGroupId = plan.group_id
        target.timelineId = self._timeline_id(plan, message.arrivedTime)
        target.messageId = plan.message_id
        target.arrivedTime = message.arrivedTime
        target.selectMessageDetailIds.extend(message.selectMessageDetailIds)
        target.finished = message.messageStatusType == _FINISHED
        if message.selectMessageDetailIds:
            target.lastMessageDetailId = message.selectMessageDetailIds[-1]
        # UserMessage has no durable read timestamp. Leave this optional time
        # unspecified rather than reusing an unrelated timestamp or account ID.

    def handle(self, path, plain):
        if path not in _ROUTES or self.catalog.directory is None:
            return None
        try:
            request = self.schema.request_type(path).FromString(plain)
        except DecodeError:
            raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Malformed tutorial message request") from None
        plan = self._master()
        action = path.removeprefix(_PREFIX)
        selected = ()
        if action in ("Timeline", "Save", "Finish"):
            if request.messageGroupId != plan.group_id:
                raise RpcFailure(RpcCode.UNIMPLEMENTED, "Only the opening tutorial message group is available locally")
            if request.timelineId < 0 or action != "Timeline" and request.timelineId == 0:
                raise RpcFailure(RpcCode.INVALID_ARGUMENT, "A valid local message timeline is required")
        if action in ("Save", "Finish"):
            selected = tuple(request.selectMessageDetailIds)
            expected = ((plan.reply_id,) if action == "Finish" or request.messageDetailId == plan.reply_id else ())
            if (action == "Save" and request.messageDetailId not in (plan.incoming_id, plan.reply_id)
                    or selected != expected):
                raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Tutorial message choices do not follow the master path")
        if action == "Receive" and list(request.messageIds) != [plan.message_id]:
            raise RpcFailure(RpcCode.UNIMPLEMENTED, "Only the opening tutorial message can be received locally")
        result = self.schema.response_type(path)()
        result.commonResponse.SetInParent()

        def mutate(raw):
            snapshot = self._parse(raw)
            if self._step(snapshot) < 130:
                if action not in ("ListGroup", "Timeline"):
                    _bad("the opening message tutorial has not started")
                return raw
            message, changed = self._ensure(snapshot, plan)
            identity = self._timeline_id(plan, message.arrivedTime)
            deleted = False
            if action == "ListGroup":
                group = result.infos.add(messageGroupId=plan.group_id)
                self._info(group.latestTimelineInfo, message, plan)
            elif action == "Timeline":
                if request.timelineId == 0 or identity < request.timelineId:
                    self._info(result.infos.add(), message, plan)
            elif action in ("Save", "Finish"):
                if request.timelineId != identity:
                    raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Unknown local tutorial message timeline")
                previous = self._selection(message, plan)
                if len(selected) < len(previous):
                    raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Tutorial message progress cannot be rewound")
                if tuple(message.selectMessageDetailIds) != selected:
                    del message.selectMessageDetailIds[:]
                    message.selectMessageDetailIds.extend(selected)
                    changed.add("messages")
                if action == "Finish":
                    if message.messageStatusType != _FINISHED:
                        message.messageStatusType = _FINISHED
                        changed.add("messages")
                    kept = [row for row in snapshot.messageSchedules if row.messageId != plan.message_id]
                    if len(kept) != len(snapshot.messageSchedules):
                        del snapshot.messageSchedules[:]
                        snapshot.messageSchedules.extend(kept)
                        changed.discard("messageSchedules")
                        deleted = True
            for name in sorted(changed):
                collection = getattr(result.commonResponse.updatedData, name)
                collection.extend(row for row in getattr(snapshot, name) if row.messageId == plan.message_id)
            if deleted:
                result.commonResponse.deletedData.messageSchedules.add(messageId=plan.message_id)
            return snapshot.SerializeToString() if changed or deleted else raw

        try:
            self.state.mutate_snapshot(self.profile, self.schema.fingerprint, mutate)
        except ValueError:
            _bad("profile snapshot is missing or uses another schema")
        return result.SerializeToString()
