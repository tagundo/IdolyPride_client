"""Read-only main-live progress for 6.1.1 Quest.Top and Quest.ListMain.

The wire schema comes from the public game client. Its LiveTop response reader
at Android RVA 0x5755020 requires pvpInfo and hierarchyNotiInfo; the former
explicitly permits an absent latestPvpSeason. No battles, clears, rewards,
competitive seasons, ticket refills or profile mutations are synthesized here.
"""
from __future__ import annotations

from pathlib import Path

from google.protobuf.message import DecodeError

from .gameplay import _Catalog
from .rpc import RpcCode, RpcFailure


_TOP = "/api.Quest/Top"
_LIST_MAIN = "/api.Quest/ListMain"
_USER_GET = "/api.User/Get"


def _invalid(message: str):
    raise RpcFailure(RpcCode.FAILED_PRECONDITION, message)


def _integer(value, description: str, *, maximum: int = (1 << 63) - 1) -> int:
    if type(value) not in (int, str):
        _invalid("Invalid local " + description)
    try:
        result = int(value)
    except (ValueError, OverflowError):
        _invalid("Invalid local " + description)
    if not 0 <= result <= maximum or isinstance(value, str) and str(result) != value:
        _invalid("Invalid local " + description)
    return result


class Quest:
    """Serve an explicit main-live catalog and persisted progress only."""

    def __init__(self, schema, state, profile: str, master_dir: Path | None = None):
        self.schema, self.state, self.profile = schema, state, profile
        self.catalog = _Catalog(master_dir)

    def _snapshot(self):
        saved = self.state.snapshot(self.profile)
        if saved is None:
            _invalid("The quest catalog needs a local profile snapshot")
        payload, fingerprint = saved
        if fingerprint != self.schema.fingerprint:
            _invalid("Local profile snapshot uses a different schema")
        try:
            snapshot = self.schema.response_type(_USER_GET).FromString(payload)
        except DecodeError:
            _invalid("Local profile snapshot is malformed")
        if not snapshot.HasField("user"):
            _invalid("Local profile has no user state")
        return snapshot

    @staticmethod
    def _progress(rows, key: str, label: str):
        result = {}
        for row in rows:
            identity = getattr(row, key)
            if not identity or identity in result:
                _invalid("Invalid local " + label + " identities")
            result[identity] = row
        return result

    @staticmethod
    def _tutorial_pending(snapshot):
        starts = [row for row in snapshot.tutorials if row.tutorialType == 1]
        if len(starts) > 1 or starts and starts[0].step < 0:
            _invalid("Invalid local GameStart tutorial state")
        return not starts or starts[0].step < 150

    def _main_catalog(self, *, tutorial_pending: bool):
        areas = self.catalog.ids("Area", required=True)
        quests = self.catalog.ids("Quest", required=True)
        groups = self.catalog.ids("AreaGroup", required=True)
        if any(type(row.get("type")) is not int for row in areas.values()):
            _invalid("Invalid local area type")
        normal = {key: row for key, row in areas.items() if row["type"] == 1}
        tutorial = {key: row for key, row in areas.items() if row["type"] == 101}
        if not normal:
            _invalid("The quest catalog needs main areas in the local master")
        if tutorial_pending and not tutorial:
            _invalid("The quest catalog needs the local tutorial area")
        main = normal | tutorial if tutorial_pending else normal
        ordered_groups = sorted(groups.values(), key=lambda row: (
            _integer(row.get("order", 0), "area group ordering"), row["id"]))
        ordered = []
        seen_areas, seen_quests = set(), set()
        for group in ordered_groups:
            area_ids = group.get("areaIds")
            if not isinstance(area_ids, list) or not area_ids:
                _invalid("Invalid local area group references")
            if any(not isinstance(key, str) or key not in areas for key in area_ids):
                _invalid("Invalid local area group references")
            # The actual table also has group999 containing type101. The
            # client explicitly searches it while GameStart is still pending.
            if not any(key in main for key in area_ids):
                continue
            group_areas = []
            for area_id in area_ids:
                if not isinstance(area_id, str) or area_id not in main or area_id in seen_areas:
                    _invalid("Invalid local area group references")
                area = main[area_id]
                if area.get("areaGroupId") != group["id"]:
                    _invalid("Local area does not belong to its group")
                seen_areas.add(area_id)
                quest_ids = area.get("questIds")
                if not isinstance(quest_ids, list) or not quest_ids:
                    _invalid("Invalid local main area quest references")
                area_quests = []
                for quest_id in quest_ids:
                    if (not isinstance(quest_id, str) or quest_id not in quests
                            or quest_id in seen_quests or quests[quest_id].get("areaId") != area_id):
                        _invalid("Invalid local main area quest references")
                    seen_quests.add(quest_id)
                    area_quests.append(quests[quest_id])
                group_areas.append((area, area_quests))
            ordered.append((group, group_areas))
        if seen_areas != set(main):
            _invalid("Local main area groups are incomplete")
        return areas, quests, ordered

    @staticmethod
    def _copy_result(info, row, rank_values):
        if row is None:
            return
        if min(row.lastClearedTime, row.highestScore, row.highestRank) < 0:
            _invalid("Local quest progress contains negative values")
        if row.highestScoreRank not in rank_values:
            _invalid("Local quest progress has an unknown result rank")
        info.cleared = bool(row.lastClearedTime)
        info.highestScore = row.highestScore
        info.highestRank = _integer(row.highestRank, "quest ranking", maximum=(1 << 31) - 1)
        info.rankType = row.highestScoreRank

    def _contest_catalog(self, result, areas, quests, progress, rank_values):
        # LiveTop.RequestLiveProgressAsync dereferences model.ContestArea
        # unconditionally at 0x5759ce8..0x5759cf4. Its quests are inspected for
        # campaign labels even when contest entry is locked. An absent optional
        # protobuf message therefore is not a valid inactive-state response.
        candidates = [row for row in areas.values() if row["type"] == 2]
        if len(candidates) != 1:
            _invalid("Quest.Top needs one local contest area")
        area = candidates[0]
        identities = area.get("questIds")
        if (not isinstance(identities, list) or not identities
                or any(not isinstance(key, str) or key not in quests for key in identities)
                or len(identities) != len(set(identities))):
            _invalid("Invalid local contest quest references")
        result.contestArea.areaId = area["id"]
        # This exposes the real catalog/history required by the menu, without
        # claiming that competitive battle entry or quotas are implemented.
        result.contestArea.unlocked = False
        for key in identities:
            if quests[key].get("areaId") != area["id"]:
                _invalid("Local contest quest does not belong to its area")
            info = result.contestArea.quests.add(questId=key)
            self._copy_result(info, progress.get(key), rank_values)
            info.isPlayable = False

    def handle(self, path: str, request_bytes: bytes) -> bytes | None:
        if path not in (_TOP, _LIST_MAIN):
            return None
        try:
            self.schema.request_type(path).FromString(request_bytes)
        except DecodeError:
            raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Malformed quest catalog protobuf request") from None
        snapshot = self._snapshot()
        areas, quests, groups = self._main_catalog(tutorial_pending=self._tutorial_pending(snapshot))
        area_progress = self._progress(snapshot.areas, "areaId", "area progress")
        quest_progress = self._progress(snapshot.quests, "questId", "quest progress")
        if any(key not in areas for key in area_progress) or any(key not in quests for key in quest_progress):
            _invalid("Local quest progress has unknown master references")
        result = self.schema.response_type(path)()
        result.commonResponse.SetInParent()
        if path == _TOP:
            # LiveTop.RequestLiveProgress unconditionally reads these objects
            # (0x57550b0 and 0x5755360). latestPvpSeason has a null fallback.
            result.pvpInfo.SetInParent()
            result.hierarchyNotiInfo.currentDetailGradeId = self.catalog.hierarchy_grade(
                snapshot.hierarchy.currentFixedPoint + snapshot.hierarchy.currentVariablePoint,
                snapshot.hierarchy.bestDetailGradeId)
        group_field = "mainAreaGroups" if path == _TOP else "areaGroups"
        output_groups = getattr(result, group_field)
        rank_values = self.schema.response_type(path).DESCRIPTOR.fields_by_name[
            group_field].message_type.fields_by_name["areas"].message_type.fields_by_name[
            "quests"].message_type.fields_by_name["rankType"].enum_type.values_by_number
        if path == _TOP:
            self._contest_catalog(result, areas, quests, quest_progress, rank_values)
        preceding_complete = True
        for group, group_areas in groups:
            output_group = output_groups.add(areaGroupId=group["id"])
            for area, area_quests in group_areas:
                if area["type"] == 101:
                    # FindCurrentAreaGroupInfo's GameStart branch requires a
                    # type101 area with a playable quest (0x575d4b0..0x575d5cc).
                    # Full/short are alternatives, not sequential live clears.
                    output_area = output_group.areas.add(areaId=area["id"], unlocked=True)
                    for quest in area_quests:
                        info = output_area.quests.add(questId=quest["id"], isPlayable=True)
                        self._copy_result(info, quest_progress.get(quest["id"]), rank_values)
                    continue
                progress = area_progress.get(area["id"])
                clear_count = _integer(progress.clearQuestCount if progress else 0,
                                       "main area clear count", maximum=len(area_quests))
                cleared = []
                for quest in area_quests:
                    row = quest_progress.get(quest["id"])
                    if row is not None and min(row.lastClearedTime, row.highestScore, row.highestRank) < 0:
                        _invalid("Local quest progress contains negative values")
                    cleared.append(bool(row and row.lastClearedTime))
                # Main areas/quests are sequential. Persisted progress can
                # establish availability, but an empty UserArea row cannot.
                unlocked = preceding_complete or clear_count > 0 or any(cleared)
                for name in ("viewConditionId", "unlockConditionId"):
                    condition = area.get(name, "")
                    if not isinstance(condition, str):
                        _invalid("Invalid local area condition")
                    if condition and not (clear_count > 0 or any(cleared)):
                        unlocked = False
                output_area = output_group.areas.add(areaId=area["id"], unlocked=unlocked)
                preceding_quest_complete = True
                for index, (quest, is_cleared) in enumerate(zip(area_quests, cleared)):
                    row = quest_progress.get(quest["id"])
                    info = output_area.quests.add(questId=quest["id"], cleared=is_cleared)
                    self._copy_result(info, row, rank_values)
                    # An unknown condition is not silently satisfied. Cleared
                    # quests remain browseable; battle entry is separate.
                    condition = quest.get("unlockConditionId", "")
                    if not isinstance(condition, str):
                        _invalid("Invalid local quest unlock condition")
                    # The stored aggregate also establishes the main-live
                    # frontier when individual historical UserQuest rows are
                    # absent. It does not manufacture their clear flags.
                    reached = index <= clear_count or preceding_quest_complete
                    info.isPlayable = unlocked and (is_cleared or reached) and not condition
                    preceding_quest_complete = preceding_quest_complete and is_cleared
                preceding_complete = clear_count == len(area_quests) or all(cleared)
        return result.SerializeToString()
