"""The shared aggregate for Photography and 360 LIVE in a media account.

6.1.1 FunctionLock type 16 uses cd-clear-area-main-002. Its ClearArea
condition compares UserArea.clearQuestCount with Master.Area.questIds.Count
(0x502ed20, 0x4db7c98); it reads neither a timestamp nor UserQuest results.
This opt-in helper creates no rewards, scores, individual clears or sessions.
360 LIVE uses FunctionLock 49 and cd-photo_panorama_music-start. Its first
OR setting requires the same area and a date after 2025-06-23 15:00 UTC.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from .gameplay import _Catalog
from .rpc import RpcCode, RpcFailure


MASTER_VERSION = "961e456499039e31248a818a911c8d95f92461f86aff4674ba07e29c32afcf60"
PHOTOGRAPHY_AREA_ID = "area-main-002"
PHOTOGRAPHY_CONDITION_ID = "cd-clear-area-main-002"


def _need(ok):
    if not ok:
        raise RpcFailure(RpcCode.FAILED_PRECONDITION,
                         "The media Photography prerequisite is unavailable or malformed")


def _identity(value):
    return isinstance(value, str) and bool(value)


def _projection(area, quests):
    return {"schema": 1, "area": {key: area.get(key) for key in ("id", "type", "questIds")},
        "quests": [{key: quests[identity].get(key) for key in ("id", "areaId")}
                   for identity in area["questIds"]]}


def _projection_sha256(area, quests):
    raw = json.dumps(_projection(area, quests), sort_keys=True, ensure_ascii=False,
                     separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _latest_pin(version):
    from . import latest_cohort_pins as pins
    values = getattr(pins, "PROJECTION_SHA256", None)
    digest = values.get("media_access") if type(values) is dict else None
    _need(version == pins.MASTER_VERSION and type(digest) is str and len(digest) == 64
          and all(character in "0123456789abcdef" for character in digest))
    return digest


@dataclass(frozen=True)
class MediaAccessPlan:
    master_version: str
    area_id: str
    quest_ids: tuple[str, ...]

    @property
    def required_clear_count(self):
        return len(self.quest_ids)


def prepare_media_access(master_dir):
    """Validate only the real target area and its real quest references.

    This does not evaluate other acquisition conditions or grant a broader
    progression prefix. The legacy condition keeps its original version; latest uses the separately
    approved semantic projection and exact public-file cohort.
    """
    catalog = _Catalog(master_dir)
    version = catalog.version()
    latest_pin = None
    if version != MASTER_VERSION:
        latest_pin = _latest_pin(version)
        from .public_cohort_support import require_master_cohort
        try:
            require_master_cohort(master_dir, "media_access")
        except (OSError, ValueError):
            _need(False)
    area = catalog.ids("Area", required=True).get(PHOTOGRAPHY_AREA_ID)
    _need(area is not None and type(area.get("type")) is int and area["type"] == 1)
    quest_ids = area.get("questIds")
    _need(isinstance(quest_ids, list) and 0 < len(quest_ids) <= (1 << 31) - 1
          and all(_identity(identity) for identity in quest_ids)
          and len(set(quest_ids)) == len(quest_ids))
    quests = catalog.ids("Quest", required=True)
    _need(all(identity in quests and quests[identity].get("areaId") == PHOTOGRAPHY_AREA_ID
              for identity in quest_ids))
    if latest_pin is not None:
        _need(_projection_sha256(area, quests) == latest_pin)
    return MediaAccessPlan(version, PHOTOGRAPHY_AREA_ID, tuple(quest_ids))


def apply_media_access(snapshot, plan):
    """Raise only the target aggregate in a caller-owned media snapshot.

    The caller must use its separate media database and persist this protobuf
    in its existing transaction. Existing rows, daily counters, timestamps,
    individual UserQuest results and unknown fields are preserved. No State,
    filesystem or clock is accessed. Returns whether this aggregate changed.

    This advances the ordinary Home main-area frontier; the media runtime must
    use its non-reward lesson view rather than ordinary area-001 lesson logic.
    """
    _need(isinstance(plan, MediaAccessPlan) and plan.area_id == PHOTOGRAPHY_AREA_ID
          and bool(plan.quest_ids))
    if plan.master_version != MASTER_VERSION:
        digest = _latest_pin(plan.master_version)
        _need(isinstance(plan.quest_ids, (tuple, list))
              and all(_identity(identity) for identity in plan.quest_ids)
              and len(set(plan.quest_ids)) == len(plan.quest_ids))
        area = {"id": plan.area_id, "type": 1, "questIds": list(plan.quest_ids)}
        quests = {identity: {"id": identity, "areaId": plan.area_id} for identity in plan.quest_ids}
        _need(_projection_sha256(area, quests) == digest)
    _need(getattr(getattr(snapshot, "DESCRIPTOR", None), "full_name", None) == "api.UserGetResponse"
          and snapshot.HasField("user"))
    seen, target = set(), None
    for row in snapshot.areas:
        _need(bool(row.areaId) and row.areaId not in seen)
        seen.add(row.areaId)
        if row.areaId == plan.area_id:
            _need(row.clearQuestCount >= 0)
            target = row
    if target is not None and target.clearQuestCount >= plan.required_clear_count:
        return False
    if target is None:
        target = snapshot.areas.add(areaId=plan.area_id)
    target.clearQuestCount = plan.required_clear_count
    return True
