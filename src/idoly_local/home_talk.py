"""Read receipts for original Home conversations in an explicit gallery profile.

The client already owns the original HomeTalk master pack and builds its own
conversation choices from it and User.Get.homeTalks. Home.Enter has no talk-list
field in 6.1.1. This handler records a real selected talk instead of inventing
an empty conversation response. Official condition/reliability/mission reward
rules are not emulated: ordinary profiles continue to their existing handlers.
"""
from __future__ import annotations

import time

from google.protobuf.message import DecodeError

from .appearance import _owned
from .gameplay import _Catalog
from .rpc import RpcCode, RpcFailure


_USER = "/api.User/Get"
_READ = "/api.Home/ReadTalk"
_MAX_MS = 2**63 - 1


def _fail(detail, code=RpcCode.FAILED_PRECONDITION):
    raise RpcFailure(code, detail)


def _identity(value):
    return isinstance(value, str) and bool(value) and not any(ord(c) < 32 for c in value)


def _timestamp(value):
    if type(value) not in (int, str):
        _fail("The original HomeTalk release date is malformed")
    try:
        result = int(value)
    except (ValueError, OverflowError):
        _fail("The original HomeTalk release date is malformed")
    if not 0 <= result <= _MAX_MS or isinstance(value, str) and str(result) != value:
        _fail("The original HomeTalk release date is malformed")
    return result


class HomeTalks:
    """Gallery-only original talk selection and atomic, idempotent receipts.

    Gallery mode intentionally permits master-defined conversations without
    reproducing official condition or release-date acquisition rules. It still
    requires the real character and any associated card to be owned. Reading
    never grants reliability, missions, currency, cards, or resources.
    """

    def __init__(self, schema, state, profile, master_dir=None, *, media_mode=False, now_ms=None):
        if type(media_mode) is not bool:
            raise ValueError("HomeTalk gallery mode must be explicit")
        if now_ms is not None and not callable(now_ms):
            raise ValueError("The HomeTalk clock must be callable")
        self.schema, self.state, self.profile = schema, state, profile
        self.catalog = _Catalog(master_dir)
        self.media_mode = media_mode
        self._clock = now_ms if now_ms is not None else lambda: time.time_ns() // 1_000_000
        self._talks = None

    def _definitions(self):
        if self._talks is not None:
            return self._talks
        if not self.catalog.version():
            _fail("The original HomeTalk master version is unavailable")
        talks = {}
        characters = self.catalog.ids("Character", required=True)
        for row in self.catalog.rows("HomeTalk", required=True):
            identity, owner = row.get("homeTalkId"), row.get("characterId")
            if (not _identity(identity) or identity in talks or not _identity(owner)
                    or owner not in characters):
                _fail("The original HomeTalk identities are malformed")
            card, condition = row.get("cardId", ""), row.get("conditionId", "")
            if any(not isinstance(value, str) or value and not _identity(value) for value in (card, condition)):
                _fail("The original HomeTalk condition or card reference is malformed")
            _timestamp(row.get("releaseDate", 0))
            lines = row.get("characterTalks", [])
            if (not isinstance(lines, list) or not lines or any(not isinstance(line, dict)
                    or any(not isinstance(line.get(field, ""), str) for field in
                           ("text", "voiceAssetId", "motionAssetId", "additionMotionAssetId"))
                    for line in lines)):
                _fail("The original HomeTalk conversation definition is malformed")
            talks[identity] = row
        if not talks:
            _fail("The original HomeTalk catalog is empty")
        # Publish only the completely validated immutable catalog. A bad row
        # cannot leave an incomplete index usable by a later request.
        self._talks = talks
        return self._talks

    def handle(self, path, plain):
        if (not self.media_mode or path != _READ or path not in self.schema.methods
                or self.catalog.directory is None):
            return None
        try:
            request = self.schema.request_type(path).FromString(plain)
        except DecodeError:
            _fail("Malformed HomeTalk request", RpcCode.INVALID_ARGUMENT)
        if not _identity(request.homeTalkId):
            _fail("A nonempty homeTalkId is required", RpcCode.INVALID_ARGUMENT)
        master = self._definitions().get(request.homeTalkId)
        if master is None:
            _fail("The requested original HomeTalk does not exist", RpcCode.NOT_FOUND)
        owner = master["characterId"]
        if owner not in self.catalog.ids("Character", required=True):
            _fail("The original HomeTalk character reference is unavailable")
        result = self.schema.response_type(path)()
        # A gallery read is deliberately reward-free on both first call and
        # retries. Current complete rows acknowledge a lost earlier response.
        result.isReliabilityUp = False

        def read(raw):
            try:
                snapshot = self.schema.response_type(_USER).FromString(raw)
            except DecodeError:
                _fail("The local HomeTalk snapshot is malformed")
            if not snapshot.HasField("user"):
                _fail("The local HomeTalk profile has no user state")
            character = _owned(snapshot.characters, "characterId").get(owner)
            if character is None:
                _fail("The HomeTalk character is not owned", RpcCode.PERMISSION_DENIED)
            receipts = _owned(snapshot.homeTalks, "homeTalkId")
            receipt = receipts.get(request.homeTalkId)
            first_read = receipt is None
            if first_read:
                card = master.get("cardId", "")
                if card and card not in _owned(snapshot.cards, "cardId"):
                    _fail("The HomeTalk card is not owned")
                now = self._clock()
                if type(now) is not int or not 0 < now <= _MAX_MS:
                    _fail("The local HomeTalk timestamp is unavailable")
                receipt = snapshot.homeTalks.add(homeTalkId=request.homeTalkId)
                character.lastHomeTalkFirstReadTime = max(character.lastHomeTalkFirstReadTime, now)
            updated = result.commonResponse.updatedData
            updated.homeTalks.add().CopyFrom(receipt)
            updated.characters.add().CopyFrom(character)
            return snapshot.SerializeToString() if first_read else raw

        try:
            self.state.mutate_snapshot(self.profile, self.schema.fingerprint, read)
        except ValueError:
            _fail("The local HomeTalk profile cannot be updated with this schema")
        return result.SerializeToString()
