"""Non-main live catalog/history projections using independent and 6.1.1 schemas."""
import json

import pytest

from idoly_local.quest import Quest
from idoly_local.rpc import RpcCode, RpcFailure

from test_quest import database, game, schema, top, update


ROUTES = ("ListDaily", "ListContest", "ListTower", "TowerTop")


@pytest.fixture
def catalog_game(game):
    quest, state, directory, rows, token = game
    additions = [
        {"id": "daily-a", "type": 3, "order": 2, "questIds": ["daily-a-1", "daily-a-2"]},
        {"id": "daily-b", "type": 3, "order": 1, "questIds": ["daily-b-1"]},
        {"id": "daily-event", "type": 3, "order": 0, "questIds": ["daily-event-1"],
         "viewConditionId": "time-not-evaluated", "unlockConditionId": "time-not-evaluated"},
        {"id": "tower", "type": 4, "order": 1, "questIds": ["tower-1", "tower-2", "tower-3"]},
        {"id": "sub-a", "type": 5, "order": 2, "questIds": ["sub-a-1", "sub-a-2"]},
        {"id": "sub-event", "type": 5, "order": 1, "questIds": ["sub-event-1"],
         "viewConditionId": "another-time-not-evaluated"},
    ]
    rows["Area"].extend(additions)
    rows["Quest"].extend({"id": identity, "areaId": area["id"]}
                         for area in additions for identity in area["questIds"])
    for table in ("Area", "Quest"):
        (directory / (table + ".json")).write_text(json.dumps(rows[table]))
    return game


def listing(game, route):
    quest = game[0]
    path = "/api.Quest/" + route
    return quest.schema.response_type(path).FromString(quest.handle(path, b""))


def assert_inactive(area):
    assert area.areaId and not area.unlocked
    assert area.quests
    assert all(not row.isPlayable and not row.playableCount and not row.campaignDropRewardIds
               for row in area.quests)


def test_daily_contest_tower_and_subtower_catalogs_share_real_master_order_and_no_access(catalog_game):
    before = database(catalog_game[1])
    daily = listing(catalog_game, "ListDaily")
    assert [area.areaId for area in daily.areas] == ["daily-b", "daily-a"]
    assert [[row.questId for row in area.quests] for area in daily.areas] == [
        ["daily-b-1"], ["daily-a-1", "daily-a-2"]]
    assert not daily.bulkDailyInfos
    contest = listing(catalog_game, "ListContest")
    assert contest.area.areaId == "contest"
    tower = listing(catalog_game, "ListTower")
    assert tower.area.areaId == "tower"
    tower_top = listing(catalog_game, "TowerTop")
    assert tower_top.towerArea.area.SerializeToString() == tower.area.SerializeToString()
    assert tower_top.towerArea.currentTowerQuestId == ""
    assert [row.area.areaId for row in tower_top.subTowerAreas] == ["sub-a"]
    assert not tower_top.subTowerAreas[0].currentTowerQuestId
    assert tower_top.hierarchyNotiInfo.currentDetailGradeId == "grade-1"
    assert "commonResponse" not in tower_top.DESCRIPTOR.fields_by_name
    for result in (daily, contest, tower):
        assert result.HasField("commonResponse")
        assert not result.commonResponse.HasField("updatedData")
        assert not result.commonResponse.HasField("deletedData")
    for area in list(daily.areas) + [contest.area, tower.area] + [
            row.area for row in tower_top.subTowerAreas]:
        assert_inactive(area)
        assert not any(row.cleared or row.highestScore or row.rankType for row in area.quests)
    assert database(catalog_game[1]) == before


def test_top_catalog_bytes_match_lists_without_changing_main_frontier(catalog_game):
    result = top(catalog_game)
    assert [row.SerializeToString() for row in result.dailyAreas] == [
        row.SerializeToString() for row in listing(catalog_game, "ListDaily").areas]
    assert result.towerArea.SerializeToString() == listing(catalog_game, "ListTower").area.SerializeToString()
    assert result.contestArea.SerializeToString() == listing(catalog_game, "ListContest").area.SerializeToString()
    assert not result.currentTowerQuestId and not result.isTowerTopUnlocked and not result.isDailyPlayable
    assert result.mainAreaGroups[0].areas[0].quests[0].isPlayable
    assert not result.mainAreaGroups[0].areas[1].unlocked


def test_imported_history_partitions_modes_and_preserves_snapshot_sessions_and_daily_counts(catalog_game):
    def imported(snapshot):
        snapshot.areas.add(areaId="daily-a", clearQuestCount=1, lastClearedTime=100)
        snapshot.areas.add(areaId="tower", clearQuestCount=1, lastClearedTime=200)
        snapshot.areas.add(areaId="sub-a", clearQuestCount=1, lastClearedTime=300)
        snapshot.quests.add(questId="daily-a-1", lastClearedTime=100, highestScore=12345,
                            highestScoreRank=4, highestRank=17)
        snapshot.quests.add(questId="tower-1", lastClearedTime=200, highestScore=23456,
                            highestScoreRank=5)
        snapshot.quests.add(questId="sub-a-1", lastClearedTime=300)
        if "dailyClearCount" in snapshot.areas[-3].DESCRIPTOR.fields_by_name:
            snapshot.areas[-3].dailyClearCount = 4
    update(catalog_game, imported)
    before = database(catalog_game[1])
    daily = listing(catalog_game, "ListDaily").areas[1]
    assert daily.quests[0].cleared and daily.quests[0].highestScore == 12345
    assert daily.quests[0].rankType == 4 and daily.quests[0].highestRank == 17
    assert not daily.quests[1].cleared
    assert_inactive(daily)
    tower_top = listing(catalog_game, "TowerTop")
    assert tower_top.towerArea.currentTowerQuestId == "tower-2"
    assert tower_top.subTowerAreas[0].currentTowerQuestId == "sub-a-2"
    assert tower_top.towerArea.area.quests[0].highestScore == 23456
    assert_inactive(tower_top.towerArea.area)
    result = top(catalog_game)
    assert result.currentTowerQuestId == "tower-2"
    assert result.mainAreaGroups[0].areas[0].quests[0].isPlayable
    assert not result.mainAreaGroups[0].areas[1].unlocked
    assert database(catalog_game[1]) == before
    assert catalog_game[1].authenticated(catalog_game[4], "player")


def test_conditional_catalog_rows_require_existing_results_not_empty_rows(catalog_game):
    update(catalog_game, lambda snapshot: snapshot.areas.add(areaId="daily-event"))
    assert [row.areaId for row in listing(catalog_game, "ListDaily").areas] == ["daily-b", "daily-a"]
    update(catalog_game, lambda snapshot: snapshot.quests.add(
        questId="daily-event-1", highestScore=100, highestScoreRank=3))
    before = database(catalog_game[1])
    daily = listing(catalog_game, "ListDaily")
    assert daily.areas[0].areaId == "daily-event"
    assert daily.areas[0].quests[0].highestScore == 100 and not daily.areas[0].quests[0].cleared
    assert_inactive(daily.areas[0])
    assert database(catalog_game[1]) == before
    update(catalog_game, lambda snapshot: snapshot.quests.add(questId="sub-event-1", lastClearedTime=123))
    before = database(catalog_game[1])
    result = listing(catalog_game, "TowerTop")
    assert [row.area.areaId for row in result.subTowerAreas] == ["sub-event", "sub-a"]
    assert result.subTowerAreas[0].currentTowerQuestId == "sub-event-1"
    assert database(catalog_game[1]) == before


@pytest.mark.parametrize("route", ROUTES)
def test_catalog_reads_are_repeatable_across_restart_and_preserve_unknown_fields(catalog_game, route):
    quest, state, directory = catalog_game[:3]
    before = state.snapshot("player")
    value = quest.handle("/api.Quest/" + route, b"")
    restarted = Quest(quest.schema, state, "player", directory)
    assert restarted.handle("/api.Quest/" + route, b"") == value
    assert state.snapshot("player") == before
    assert before[0].endswith(b"\xf8\x7f\x01")


@pytest.mark.parametrize("route", ROUTES)
def test_nonmain_catalogs_reject_malformed_request_without_writes(catalog_game, route):
    before = database(catalog_game[1])
    with pytest.raises(RpcFailure) as failure:
        catalog_game[0].handle("/api.Quest/" + route, b"\xff")
    assert failure.value.code == RpcCode.INVALID_ARGUMENT
    assert database(catalog_game[1]) == before


@pytest.mark.parametrize("route,area_id,change", [
    ("ListDaily", "daily-a", {"questIds": ["missing"]}),
    ("ListDaily", "daily-a", {"questIds": ["daily-a-1", "daily-a-1"]}),
    ("ListDaily", "daily-a", {"questIds": ["tower-1"]}),
    ("ListDaily", "daily-a", {"questIds": []}),
    ("ListDaily", "daily-a", {"questIds": "daily-a-1"}),
    ("ListDaily", "daily-a", {"unlockConditionId": 42}),
    ("ListDaily", "daily-a", {"viewConditionId": None}),
    ("ListDaily", "daily-a", {"order": -1}),
    ("ListDaily", "daily-event", {"questIds": [{}]}),
    ("ListDaily", "daily-event", {"questIds": ["missing"]}),
    ("ListDaily", "daily-event", {"unlockConditionId": None}),
    ("TowerTop", "sub-event", {"questIds": ["daily-a-1"]}),
    ("ListTower", "tower", {"questIds": ["daily-a-1"]}),
    ("TowerTop", "sub-a", {"questIds": ["daily-a-1"]}),
    ("ListContest", "contest", {"questIds": ["daily-a-1"]}),
])
def test_bad_selected_master_is_not_empty_success(catalog_game, route, area_id, change):
    rows = catalog_game[3]["Area"]
    next(row for row in rows if row["id"] == area_id).update(change)
    (catalog_game[2] / "Area.json").write_text(json.dumps(rows))
    before = database(catalog_game[1])
    with pytest.raises(RpcFailure) as failure:
        listing(catalog_game, route)
    assert failure.value.code == RpcCode.FAILED_PRECONDITION
    assert database(catalog_game[1]) == before


@pytest.mark.parametrize("change", [
    lambda snapshot: snapshot.areas.add(areaId="missing"),
    lambda snapshot: snapshot.quests.add(questId="missing"),
    lambda snapshot: snapshot.areas.add(areaId="tower", clearQuestCount=4),
    lambda snapshot: snapshot.areas.add(areaId="tower", clearQuestCount=-1),
    lambda snapshot: snapshot.quests.add(questId="tower-1", highestScore=-1),
    lambda snapshot: snapshot.quests.add(questId="tower-1", highestRank=1 << 35),
    lambda snapshot: snapshot.quests.add(questId="tower-1", highestScoreRank=99),
    lambda snapshot: snapshot.areas.add(areaId="tower", lastClearedTime=-1),
    lambda snapshot: snapshot.quests.add(questId="tower-1", lastClearedTime=-1),
])
def test_bad_saved_references_or_result_values_fail_without_mutation(catalog_game, change):
    update(catalog_game, change)
    before = database(catalog_game[1])
    with pytest.raises(RpcFailure) as failure:
        listing(catalog_game, "ListTower")
    assert failure.value.code == RpcCode.FAILED_PRECONDITION
    assert database(catalog_game[1]) == before


@pytest.mark.parametrize("route,area_type", [("ListTower", 4), ("TowerTop", 4), ("ListContest", 2)])
@pytest.mark.parametrize("ambiguous", (False, True))
def test_missing_or_ambiguous_required_catalog_is_not_empty_success(catalog_game, route, area_type, ambiguous):
    rows = catalog_game[3]["Area"]
    area = next(row for row in rows if row["type"] == area_type)
    if ambiguous:
        rows.append(dict(area, id="extra-" + area["id"]))
    else:
        rows.remove(area)
    (catalog_game[2] / "Area.json").write_text(json.dumps(rows))
    with pytest.raises(RpcFailure) as failure:
        listing(catalog_game, route)
    assert failure.value.code == RpcCode.FAILED_PRECONDITION


def test_empty_daily_catalog_is_legitimate_and_does_not_require_main_groups(catalog_game):
    rows = [row for row in catalog_game[3]["Area"] if row["type"] != 3]
    (catalog_game[2] / "Area.json").write_text(json.dumps(rows))
    (catalog_game[2] / "AreaGroup.json").unlink()
    before = database(catalog_game[1])
    result = listing(catalog_game, "ListDaily")
    assert not result.areas and not result.bulkDailyInfos
    assert result.HasField("commonResponse")
    assert database(catalog_game[1]) == before


@pytest.mark.parametrize("count,timestamp", [(-1, 0), (0, -1), (2, 0)])
def test_hidden_conditional_area_cannot_conceal_invalid_saved_state(catalog_game, count, timestamp):
    update(catalog_game, lambda snapshot: snapshot.areas.add(
        areaId="daily-event", clearQuestCount=count, lastClearedTime=timestamp))
    before = database(catalog_game[1])
    with pytest.raises(RpcFailure) as failure:
        listing(catalog_game, "ListDaily")
    assert failure.value.code == RpcCode.FAILED_PRECONDITION
    assert database(catalog_game[1]) == before


@pytest.mark.parametrize("values", [
    {"highestScore": -1}, {"lastClearedTime": -1}, {"highestRank": -1},
    {"highestScoreRank": 99}, {"highestRank": 1 << 35},
])
@pytest.mark.parametrize("route,quest_id", [
    ("ListDaily", "daily-event-1"), ("TowerTop", "sub-event-1"),
])
def test_hidden_conditional_quest_cannot_conceal_invalid_result(catalog_game, values, route, quest_id):
    update(catalog_game, lambda snapshot: snapshot.quests.add(questId=quest_id, **values))
    before = database(catalog_game[1])
    with pytest.raises(RpcFailure) as failure:
        listing(catalog_game, route)
    assert failure.value.code == RpcCode.FAILED_PRECONDITION
    assert database(catalog_game[1]) == before
