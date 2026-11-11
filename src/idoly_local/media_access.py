"""The one aggregate prerequisite for Photography in a separate media account.

6.1.1 FunctionLock type 16 uses cd-clear-area-main-002. Its ClearArea
condition compares UserArea.clearQuestCount with Master.Area.questIds.Count
(0x502ed20, 0x4db7c98); it reads neither a timestamp nor UserQuest results.
This opt-in helper creates no rewards, scores, individual clears or sessions.
"""
from __future__ import annotations

from dataclasses import dataclass

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
    progression prefix. The fixed condition is pinned to this master version.
    """
    catalog = _Catalog(master_dir)
    _need(catalog.version() == MASTER_VERSION)
    area = catalog.ids("Area", required=True).get(PHOTOGRAPHY_AREA_ID)
    _need(area is not None and type(area.get("type")) is int and area["type"] == 1)
    quest_ids = area.get("questIds")
    _need(isinstance(quest_ids, list) and 0 < len(quest_ids) <= (1 << 31) - 1
          and all(_identity(identity) for identity in quest_ids)
          and len(set(quest_ids)) == len(quest_ids))
    quests = catalog.ids("Quest", required=True)
    _need(all(identity in quests and quests[identity].get("areaId") == PHOTOGRAPHY_AREA_ID
              for identity in quest_ids))
    return MediaAccessPlan(MASTER_VERSION, PHOTOGRAPHY_AREA_ID, tuple(quest_ids))


def apply_media_access(snapshot, plan):
    """Raise only the target aggregate in a caller-owned media snapshot.

    The caller must use its separate media database and persist this protobuf
    in its existing transaction. Existing rows, daily counters, timestamps,
    individual UserQuest results and unknown fields are preserved. No State,
    filesystem or clock is accessed. Returns whether this aggregate changed.

    This advances the ordinary Home main-area frontier; the media runtime must
    use its non-reward lesson view rather than ordinary area-001 lesson logic.
    """
    _need(isinstance(plan, MediaAccessPlan) and plan.master_version == MASTER_VERSION
          and plan.area_id == PHOTOGRAPHY_AREA_ID and bool(plan.quest_ids))
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
