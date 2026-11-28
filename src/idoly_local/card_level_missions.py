"""List persisted master-valid missions and track one card-level achievement.

Original 6.1.1 captures show progress 1 -> 2 and 41 -> 42 alongside the
corresponding owned-card enhancement. The native Mission.List consumer accepts
a sparse list, but every returned currentThreshold must resolve exactly in the
mission master. List projects actual saved daily/weekly/normal memberships;
it never constructs an active catalog, calculates new eligibility or pays rewards.

At an unclaimed threshold this local implementation marks Progress as Clear;
that is an explicit local ready-to-claim policy, not verified official boundary
behavior. No tier advances, claims, rewards or recurring missions are supplied.
"""
from __future__ import annotations

from pathlib import Path
import re

from google.protobuf.message import DecodeError

from .gameplay import _Catalog
from .rpc import RpcCode, RpcFailure


MISSION_ID = "ms-normal-card_level_achievement"
_USER = "/api.User/Get"
_LIST = "/api.Mission/List"
_MAX_I64 = (1 << 63) - 1


def _fail(reason):
    raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Local mission: " + reason)


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


def _resource_types(schema):
    """Use the client enum for inline reward names, not guessed numeric types."""
    enums = [enum for file in schema.files for enum in file.enum_types_by_name.values()
             if enum.name == "ResourceType"]
    if not enums:
        # The original supported minimal schema predates reward enum exposure.
        return {"stone": 15}
    if len(enums) != 1:
        _fail("ambiguous resource enum")
    def snake(name):
        name = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
        return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name).lower()
    result = {}
    enum = enums[0]
    for value in enum.values:
        if value.number <= 0:
            continue
        # Recovered protobuf descriptors retain names such as ResourceType_Item.
        # Native C# reflection sees the member Item; strip only this exact enum
        # prefix before applying its CamelToLowerSnakeCase display-key mapping.
        key = snake(value.name.removeprefix(enum.name + "_"))
        if not key or key in result:
            _fail("ambiguous resource display identity")
        result[key] = value.number
    return result


def _display_reward(catalog, key, resource_types):
    """Require the same nonnull reward reference read by the native detail UI."""
    if not isinstance(key, str) or not key:
        _fail("saved mission has no display reward")
    parts = key.split(";")
    if parts[0] == "rd_auto":
        if (len(parts) != 4 or parts[1].strip() not in resource_types
                or _number(parts[3].strip(), "inline reward amount", positive=True) > (1 << 31) - 1):
            _fail("saved mission has an invalid inline display reward")
        return
    reward = catalog.ids("Reward", required=True).get(key)
    resources = reward.get("resources") if reward is not None else None
    if not isinstance(resources, list) or not resources:
        _fail("saved mission has an unresolved display reward")
    valid_types = set(resource_types.values())
    for resource in resources:
        if (not isinstance(resource, dict) or type(resource.get("resourceType")) is not int
                or resource["resourceType"] not in valid_types
                or not isinstance(resource.get("resourceId", ""), str)
                or _number(resource.get("amount"), "display reward amount", positive=True) > (1 << 31) - 1):
            _fail("saved mission has an invalid display reward resource")


def listed_missions(snapshot, catalog, schema):
    """Return ordinary saved rows that the client can resolve; never repair a save.

    Unknown historical identities remain byte-for-byte in the saved snapshot but
    cannot be sent to the native consumer, whose Master.Mission lookup throws.
    Any malformed known row fails the whole read before returning a partial list.
    """
    if "missions" not in snapshot.DESCRIPTOR.fields_by_name:
        _fail("snapshot schema has no mission collection")
    masters = catalog.ids("Mission", required=True)
    seen, selected, resolved = set(), [], 0
    resource_types = _resource_types(schema)
    for row in snapshot.missions:
        if not row.missionId or row.missionId in seen:
            _fail("empty or duplicate saved mission identity")
        seen.add(row.missionId)
        master = masters.get(row.missionId)
        if master is None:
            continue
        resolved += 1
        # MissionTop sends every category-3 row straight to its Normal tab.
        # Scoped event/company missions have separate screens; saved membership
        # does not authorize moving them into the ordinary mission menu.
        if (master.get("categoryType") not in (1, 2, 3)
                or master.get("eventMissionId", "")
                or master.get("companyEnjoyCharacterId", "")
                or master.get("companyEnjoyCharacterMissionCategoryType", 0)
                or master.get("companyTrustMissionCategoryType", 0)):
            continue
        progresses = master.get("progresses")
        if not isinstance(progresses, list) or not progresses:
            _fail("saved mission has no master thresholds")
        thresholds = {}
        for progress in progresses:
            if not isinstance(progress, dict):
                _fail("saved mission has an invalid master threshold")
            threshold = _number(progress.get("threshold"), "master threshold", positive=True)
            if threshold in thresholds:
                _fail("saved mission has ambiguous master thresholds")
            thresholds[threshold] = progress
        if (row.currentThreshold not in thresholds or row.statusType not in (1, 2, 3, 4)
                or row.progress < 0 or row.lastUpdateTime < 0
                or row.missionId == MISSION_ID and row.statusType in (2, 3, 4)
                and row.progress < row.currentThreshold):
            _fail("invalid saved mission threshold, progress or status")
        _display_reward(catalog, thresholds[row.currentThreshold].get("rewardSetId"), resource_types)
        selected.append(row)
    if snapshot.missions and not resolved:
        _fail("no master-resolvable saved missions; no active catalog is synthesized")
    return selected


class CardLevelMissions:
    """Project ordinary saved missions; only card-level progress is advanced."""
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
        saved = self.state.snapshot(self.profile)
        if saved is None or saved[1] != self.schema.fingerprint:
            _fail("snapshot is absent or uses a different schema")
        try:
            snapshot = self.schema.response_type(_USER).FromString(saved[0])
        except (DecodeError, UnicodeError):
            _fail("snapshot is malformed")
        if not snapshot.HasField("user"):
            _fail("snapshot has no user state")
        rows = listed_missions(snapshot, self.catalog, self.schema)
        result = self.schema.response_type(path)()
        for row in rows:
            result.userMissions.add().CopyFrom(row)
        result.commonResponse.SetInParent()
        return result.SerializeToString()
