"""Read-only live progress and saved-unit appearances for the 6.1.1 client.

The wire schema comes from the public game client. Its LiveTop response reader
at Android RVA 0x5755020 requires pvpInfo and hierarchyNotiInfo, and its
post-await code also requires contestArea (0x5759ce8). PvP explicitly permits
an absent latestPvpSeason. No battles, clears, rewards,
competitive seasons, ticket refills or profile mutations are synthesized here.
"""
from __future__ import annotations

from pathlib import Path

from google.protobuf.message import DecodeError

from .gameplay import _Catalog
from .rpc import RpcCode, RpcFailure


_TOP = "/api.Quest/Top"
_LIST_MAIN = "/api.Quest/ListMain"
_LIST_ASSET = "/api.Quest/ListAsset"
_LIST_DAILY = "/api.Quest/ListDaily"
_LIST_CONTEST = "/api.Quest/ListContest"
_LIST_TOWER = "/api.Quest/ListTower"
_TOWER_TOP = "/api.Quest/TowerTop"
_READ_CATALOGS = (_LIST_DAILY, _LIST_CONTEST, _LIST_TOWER, _TOWER_TOP)
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
    """Serve live catalogs/history and saved-unit resource references without battles."""

    def __init__(self, schema, state, profile: str, master_dir: Path | None = None, *, tutorial_replays=None,
                 pvp=None):
        self.schema, self.state, self.profile = schema, state, profile
        self.catalog = _Catalog(master_dir)
        self.tutorial_replays = tutorial_replays
        self.pvp = pvp

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
    def _validate_result(row, rank_values):
        if row is None:
            return
        if min(row.lastClearedTime, row.highestScore, row.highestRank) < 0:
            _invalid("Local quest progress contains negative values")
        if row.highestScoreRank not in rank_values:
            _invalid("Local quest progress has an unknown result rank")
        _integer(row.highestRank, "quest ranking", maximum=(1 << 31) - 1)
        if hasattr(row, "dailyClearCount"):
            _integer(row.dailyClearCount, "daily quest clear count")

    @classmethod
    def _copy_result(cls, info, row, rank_values):
        if row is None:
            return
        cls._validate_result(row, rank_values)
        info.cleared = bool(row.lastClearedTime)
        info.highestScore = row.highestScore
        info.highestRank = row.highestRank
        info.rankType = row.highestScoreRank

    def _progress_maps(self, snapshot, areas, quests):
        area_progress = self._progress(snapshot.areas, "areaId", "area progress")
        quest_progress = self._progress(snapshot.quests, "questId", "quest progress")
        if any(key not in areas for key in area_progress) or any(key not in quests for key in quest_progress):
            _invalid("Local quest progress has unknown master references")
        return area_progress, quest_progress

    @staticmethod
    def _ordered_areas(areas, area_type):
        return sorted((row for row in areas.values() if row["type"] == area_type),
                      key=lambda row: (_integer(row.get("order", 0), "area ordering"), row["id"]))

    @staticmethod
    def _area_references(area, quests, area_progress):
        identities = area.get("questIds")
        if (not isinstance(identities, list) or not identities
                or any(not isinstance(key, str) or key not in quests for key in identities)
                or len(identities) != len(set(identities))):
            _invalid("Invalid local archived area quest references")
        if any(quests[key].get("areaId") != area["id"] for key in identities):
            _invalid("Local archived quest does not belong to its area")
        for name in ("viewConditionId", "unlockConditionId"):
            if not isinstance(area.get(name, ""), str):
                _invalid("Invalid local archived area condition")
        saved = area_progress.get(area["id"])
        if saved is not None:
            _integer(saved.clearQuestCount, "area clear count", maximum=len(identities))
            _integer(saved.lastClearedTime, "area clear timestamp")
            # Real UserArea has this counter; the older independent fixture
            # omits it. Reads never roll it over or allocate challenge passes.
            if hasattr(saved, "dailyClearCount"):
                _integer(saved.dailyClearCount, "daily area clear count")
        return identities

    def _visible_archive_area(self, area, quests, area_progress, quest_progress, rank_values):
        # Validate hidden rows too: an unsupported schedule must not conceal
        # corrupt master references or invalid persisted counters.
        identities = self._area_references(area, quests, area_progress)
        for key in identities:
            self._validate_result(quest_progress.get(key), rank_values)
        # Do not turn past/future event schedules into active daily/EX towers.
        # Conditional areas are archived only when this account has a result.
        if not area.get("viewConditionId", ""):
            return True
        saved = area_progress.get(area["id"])
        if saved is not None and (saved.clearQuestCount > 0 or saved.lastClearedTime > 0):
            return True
        return any(row is not None and (row.lastClearedTime > 0 or row.highestScore > 0)
                   for row in (quest_progress.get(key) for key in identities))

    def _inactive_area(self, info, area, quests, area_progress, quest_progress, rank_values):
        identities = self._area_references(area, quests, area_progress)
        info.areaId = area["id"]
        info.unlocked = False
        for key in identities:
            row = info.quests.add(questId=key)
            self._copy_result(row, quest_progress.get(key), rank_values)
            row.isPlayable = False
        return identities

    @staticmethod
    def _rank_values(area_info):
        descriptor = area_info if hasattr(area_info, "fields_by_name") else area_info.DESCRIPTOR
        return descriptor.fields_by_name["quests"].message_type.fields_by_name[
            "rankType"].enum_type.values_by_number

    @staticmethod
    def _tower_position(identities, area, area_progress, quest_progress):
        # A catalog identity is not permission to enter a tower. Only derive
        # its saved frontier when real progress exists, without persisting it.
        saved = area_progress.get(area["id"])
        count = saved.clearQuestCount if saved is not None else 0
        has_result = any(row is not None and row.lastClearedTime > 0
                         for row in (quest_progress.get(key) for key in identities))
        if not count and not has_result:
            return ""
        for index, key in enumerate(identities):
            row = quest_progress.get(key)
            if index >= count and not (row is not None and row.lastClearedTime > 0):
                return key
        return identities[-1]

    def _contest_catalog(self, result, areas, quests, progress, rank_values, area_progress=None):
        # The original LiveTop post-await reader requires contestArea even
        # when battle entry is inactive (0x5759ce8..0x5759cf4).
        candidates = self._ordered_areas(areas, 2)
        if len(candidates) != 1:
            _invalid("Quest catalog needs one local contest area")
        self._inactive_area(result.contestArea, candidates[0], quests,
                            area_progress or {}, progress, rank_values)

    def _other_top_catalogs(self, result, areas, quests, area_progress, quest_progress):
        fields = result.DESCRIPTOR.fields_by_name
        if "dailyAreas" in fields:
            rank_values = self._rank_values(fields["dailyAreas"].message_type)
            for area in self._ordered_areas(areas, 3):
                if self._visible_archive_area(area, quests, area_progress, quest_progress, rank_values):
                    info = result.dailyAreas.add()
                    self._inactive_area(info, area, quests, area_progress, quest_progress,
                                        self._rank_values(info))
        towers = self._ordered_areas(areas, 4)
        if len(towers) > 1:
            _invalid("Quest catalog has ambiguous main tower areas")
        if towers and "towerArea" in fields:
            area = towers[0]
            identities = self._inactive_area(result.towerArea, area, quests, area_progress,
                                             quest_progress, self._rank_values(result.towerArea))
            if "currentTowerQuestId" in fields:
                result.currentTowerQuestId = self._tower_position(
                    identities, area, area_progress, quest_progress)
        # isDailyPlayable and isTowerTopUnlocked stay false: the new read
        # surfaces do not implement paid/free attempts or tower battle entry.

    def _read_catalog(self, path, snapshot):
        areas = self.catalog.ids("Area", required=True)
        quests = self.catalog.ids("Quest", required=True)
        if any(type(row.get("type")) is not int for row in areas.values()):
            _invalid("Invalid local area type")
        area_progress, quest_progress = self._progress_maps(snapshot, areas, quests)
        result = self.schema.response_type(path)()
        if "commonResponse" in result.DESCRIPTOR.fields_by_name:
            result.commonResponse.SetInParent()
        if path == _LIST_DAILY:
            rank_values = self._rank_values(result.DESCRIPTOR.fields_by_name["areas"].message_type)
            for area in self._ordered_areas(areas, 3):
                if self._visible_archive_area(area, quests, area_progress, quest_progress, rank_values):
                    info = result.areas.add()
                    self._inactive_area(info, area, quests, area_progress, quest_progress,
                                        self._rank_values(info))
            # No guessed bulk formations, challenge allowances or rewards.
            return result.SerializeToString()
        area_type = 2 if path == _LIST_CONTEST else 4
        candidates = self._ordered_areas(areas, area_type)
        if len(candidates) != 1:
            _invalid("Quest catalog needs one local " + ("contest" if area_type == 2 else "tower") + " area")
        area = candidates[0]
        target = result.towerArea.area if path == _TOWER_TOP else result.area
        identities = self._inactive_area(target, area, quests, area_progress,
                                         quest_progress, self._rank_values(target))
        if path == _TOWER_TOP:
            result.towerArea.currentTowerQuestId = self._tower_position(
                identities, area, area_progress, quest_progress)
            rank_values = self._rank_values(result.DESCRIPTOR.fields_by_name[
                "subTowerAreas"].message_type.fields_by_name["area"].message_type)
            for subarea in self._ordered_areas(areas, 5):
                if not self._visible_archive_area(subarea, quests, area_progress, quest_progress, rank_values):
                    continue
                info = result.subTowerAreas.add()
                subidentities = self._inactive_area(info.area, subarea, quests, area_progress,
                                                    quest_progress, self._rank_values(info.area))
                info.currentTowerQuestId = self._tower_position(
                    subidentities, subarea, area_progress, quest_progress)
            result.hierarchyNotiInfo.currentDetailGradeId = self.catalog.hierarchy_grade(
                snapshot.hierarchy.currentFixedPoint + snapshot.hierarchy.currentVariablePoint,
                snapshot.hierarchy.bestDetailGradeId)
        return result.SerializeToString()

    def handle(self, path: str, request_bytes: bytes) -> bytes | None:
        if path not in (_TOP, _LIST_MAIN, _LIST_ASSET) + _READ_CATALOGS:
            return None
        try:
            request = self.schema.request_type(path).FromString(request_bytes)
        except DecodeError:
            raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Malformed quest catalog protobuf request") from None
        snapshot = self._snapshot()
        if path in _READ_CATALOGS:
            return self._read_catalog(path, snapshot)
        if path == _LIST_ASSET:
            from .live_assets import project_live_assets
            result = project_live_assets(self.schema, snapshot, request, self.catalog)
            if self.tutorial_replays is not None:
                self.tutorial_replays.append_assets(result, snapshot, request.questId)
            return result.SerializeToString()
        areas, quests, groups = self._main_catalog(tutorial_pending=self._tutorial_pending(snapshot))
        area_progress, quest_progress = self._progress_maps(snapshot, areas, quests)
        result = self.schema.response_type(path)()
        result.commonResponse.SetInParent()
        if path == _TOP:
            # LiveTop.RequestLiveProgress unconditionally reads these objects
            # (0x57550b0 and 0x5755360). latestPvpSeason has a null fallback.
            result.pvpInfo.SetInParent()
            if self.pvp is not None:
                info = self.pvp.quest_top_info(snapshot)
                if info is not None:
                    result.pvpInfo.CopyFrom(info)
            result.hierarchyNotiInfo.currentDetailGradeId = self.catalog.hierarchy_grade(
                snapshot.hierarchy.currentFixedPoint + snapshot.hierarchy.currentVariablePoint,
                snapshot.hierarchy.bestDetailGradeId)
        group_field = "mainAreaGroups" if path == _TOP else "areaGroups"
        output_groups = getattr(result, group_field)
        rank_values = self.schema.response_type(path).DESCRIPTOR.fields_by_name[
            group_field].message_type.fields_by_name["areas"].message_type.fields_by_name[
            "quests"].message_type.fields_by_name["rankType"].enum_type.values_by_number
        if path == _TOP:
            self._contest_catalog(result, areas, quests, quest_progress, rank_values, area_progress)
            self._other_top_catalogs(result, areas, quests, area_progress, quest_progress)
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
