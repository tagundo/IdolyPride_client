"""Track one evidenced normal card-level achievement, without claiming rewards.

Original 6.1.1 captures show progress 1 -> 2 and 41 -> 42 alongside the
corresponding owned-card enhancement. The native Mission.List consumer accepts
a sparse list, but every returned currentThreshold must resolve exactly in the
mission master. This module never constructs the full active mission catalog.

At an unclaimed threshold this local implementation marks Progress as Clear;
that is an explicit local ready-to-claim policy, not verified official boundary
behavior. No tier advances, claims, rewards or recurring missions are supplied.
"""
from __future__ import annotations

from pathlib import Path

from google.protobuf.message import DecodeError

from .gameplay import _Catalog
from .rpc import RpcCode, RpcFailure


MISSION_ID = "ms-normal-card_level_achievement"
_USER = "/api.User/Get"
_LIST = "/api.Mission/List"
_MAX_I64 = (1 << 63) - 1


def _fail(reason):
    raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Local card-level mission: " + reason)


def _number(value, label, *, positive=False):
    if type(value) not in (int, str):
        _fail("invalid " + label)
    try:
        result = int(value)
    except (ValueError, OverflowError):
        _fail("invalid " + label)
    if (result < int(positive) or result > _MAX_I64
            or isinstance(value, str) and str(result) != value):
        _fail("invalid " + label)
    return result


def mission_master(catalog, *, optional=False):
    """An absent old-payload table disables this addition, not existing play."""
    source = catalog.directory / "Mission.json" if catalog.directory is not None else None
    if optional and (source is None or not source.is_file()):
        return None
    master = catalog.ids("Mission", required=True).get(MISSION_ID)
    if (master is None or type(master.get("categoryType")) is not int or master["categoryType"] != 3
            or type(master.get("missionType")) is not int or master["missionType"] != 13
            or master.get("targetIds", []) != [] or master.get("viewConditionId", "") != ""
            or master.get("eventMissionId", "") != "" or master.get("companyEnjoyCharacterId", "") != ""
            or master.get("companyEnjoyCharacterMissionCategoryType", 0) != 0
            or master.get("companyTrustMissionCategoryType", 0) != 0):
        _fail("unsupported master identity or eligibility")
    rows = master.get("progresses")
    if not isinstance(rows, list) or not rows:
        _fail("missing master thresholds")
    thresholds = []
    for row in rows:
        if not isinstance(row, dict):
            _fail("invalid master threshold")
        threshold = _number(row.get("threshold"), "master threshold", positive=True)
        # The original native resolver creates these inline rewards; no Reward
        # table row exists. Validate the UI reference without granting anything.
        reward = row.get("rewardSetId")
        parts = reward.split(";") if isinstance(reward, str) else []
        if len(parts) != 4 or parts[:3] != ["rd_auto", "stone", ""]:
            _fail("unsupported inline reward reference")
        if _number(parts[3], "inline reward amount", positive=True) > (1 << 31) - 1:
            _fail("inline reward amount exceeds native Int32")
        thresholds.append(threshold)
    if thresholds[0] != 5 or thresholds != sorted(set(thresholds)):
        _fail("ambiguous or unsupported master thresholds")
    return tuple(thresholds)


def owned_card_level(snapshot, catalog):
    """Read owned levels, never lower a recorded historical achievement."""
    cards = catalog.ids("Card", required=True)
    levels = set()
    for row in catalog.rows("CardLevel", required=True):
        level = _number(row.get("level"), "card master level", positive=True)
        if level in levels:
            _fail("ambiguous card master levels")
        levels.add(level)
    seen, highest = set(), 0
    for card in snapshot.cards:
        if not card.cardId or card.cardId in seen or card.cardId not in cards or card.level not in levels:
            _fail("invalid owned card identity or level")
        seen.add(card.cardId)
        highest = max(highest, card.level)
    if not highest:
        _fail("owned card state is missing")
    return highest


def saved_mission(snapshot, thresholds, *, required=False):
    if "missions" not in snapshot.DESCRIPTOR.fields_by_name:
        _fail("snapshot schema has no mission collection")
    matches = [row for row in snapshot.missions if row.missionId == MISSION_ID]
    if len(matches) > 1:
        _fail("duplicate saved achievement")
    if not matches:
        if required:
            _fail("saved achievement is unavailable; no active catalog is synthesized")
        return None
    row = matches[0]
    if (row.currentThreshold not in thresholds or row.statusType not in (1, 2, 3, 4)
            or row.progress < 0 or row.lastUpdateTime < 0
            or row.statusType in (2, 3, 4) and row.progress < row.currentThreshold):
        _fail("invalid saved threshold, progress or status")
    return row


def initialize_mission(snapshot, catalog, now):
    """Called only while creating/migrating an explicitly marked local starter."""
    if "missions" not in snapshot.DESCRIPTOR.fields_by_name:
        return False
    thresholds = mission_master(catalog, optional=True)
    if thresholds is None:
        return False
    if saved_mission(snapshot, thresholds) is not None:
        return False
    highest = owned_card_level(snapshot, catalog)
    snapshot.missions.add(missionId=MISSION_ID, currentThreshold=thresholds[0], progress=highest,
                          statusType=2 if highest >= thresholds[0] else 1,
                          lastUpdateTime=_number(now, "update time"))
    return True


def advance_mission(snapshot, catalog, now):
    """Run inside a real changed Card.Enhance transaction; never initialize."""
    if "missions" not in snapshot.DESCRIPTOR.fields_by_name:
        return None
    thresholds = mission_master(catalog, optional=True)
    if thresholds is None:
        return None
    row = saved_mission(snapshot, thresholds)
    if row is None:
        return None
    highest = owned_card_level(snapshot, catalog)
    if highest <= row.progress:
        return None
    row.progress = highest
    row.lastUpdateTime = max(row.lastUpdateTime, _number(now, "update time"))
    if row.statusType == 1 and highest >= row.currentThreshold:
        row.statusType = 2  # Explicit local boundary policy; not a tier receipt.
    return row


class CardLevelMissions:
    """Read only the validated, persisted supported achievement subset."""
    def __init__(self, schema, state, profile, master_dir: Path | None = None):
        self.schema, self.state, self.profile = schema, state, profile
        self.catalog = _Catalog(master_dir)

    def handle(self, path, plain):
        if path != _LIST or path not in self.schema.methods:
            return None
        try:
            self.schema.request_type(path).FromString(plain)
        except (DecodeError, UnicodeError):
            raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Malformed mission list request") from None
        thresholds = mission_master(self.catalog)
        saved = self.state.snapshot(self.profile)
        if saved is None or saved[1] != self.schema.fingerprint:
            _fail("snapshot is absent or uses a different schema")
        try:
            snapshot = self.schema.response_type(_USER).FromString(saved[0])
        except (DecodeError, UnicodeError):
            _fail("snapshot is malformed")
        if not snapshot.HasField("user"):
            _fail("snapshot has no user state")
        row = saved_mission(snapshot, thresholds, required=True)
        result = self.schema.response_type(path)()
        result.userMissions.add().CopyFrom(row)
        result.commonResponse.SetInParent()
        return result.SerializeToString()
