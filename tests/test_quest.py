"""Quest.Top progress projection, using independent and real client schemas."""
import json
from pathlib import Path

from google.protobuf import descriptor_pb2
import pytest

from idoly_local.quest import Quest
from idoly_local.rpc import RpcCode, RpcFailure
from idoly_local.schema import Schema
from idoly_local.state import State


def minimal_schema(path):
    file = descriptor_pb2.FileDescriptorProto(name="quest-test.proto", package="api", syntax="proto3")
    rank = file.enum_type.add(name="Rank")
    for value in range(7):
        rank.value.add(name="Rank" + str(value), number=value)

    def message(name, fields):
        target = file.message_type.add(name=name)
        for number, (name, kind, repeated) in enumerate(fields, 1):
            field = target.field.add(name=name, number=number, label=3 if repeated else 1)
            if isinstance(kind, int):
                field.type = kind
            else:
                field.type = 14 if kind == "Rank" else 11
                field.type_name = ".api." + kind

    def fields(*entries):
        return [(name, kind, False) for name, kind in entries]

    message("Empty", [])
    message("Manager", fields(("name", 9)))
    message("UserArea", fields(("areaId", 9), ("clearQuestCount", 5), ("lastClearedTime", 3)))
    message("UserQuest", fields(("questId", 9), ("lastClearedTime", 3), ("highestScore", 3),
                                ("highestRank", 3), ("highestScoreRank", "Rank")))
    message("Hierarchy", fields(("currentFixedPoint", 3), ("currentVariablePoint", 3), ("bestDetailGradeId", 9)))
    message("TutorialState", fields(("tutorialType", 5), ("step", 5)))
    message("UserGetResponse", fields(("user", "Manager"), ("hierarchy", "Hierarchy"))
            + [("areas", "UserArea", True), ("quests", "UserQuest", True), ("tutorials", "TutorialState", True)])
    message("QuestInfo", fields(("questId", 9), ("cleared", 8), ("highestScore", 3),
                                ("rankType", "Rank"), ("plus", 5), ("highestRank", 5),
                                ("isPlayable", 8), ("playableCount", 5))
            + [("campaignDropRewardIds", 9, True)])
    message("AreaInfo", fields(("areaId", 9), ("unlocked", 8)) + [("quests", "QuestInfo", True)])
    message("AreaGroupInfo", fields(("areaGroupId", 9)) + [("areas", "AreaInfo", True)])
    message("TowerAreaInfo", fields(("area", "AreaInfo"), ("currentTowerQuestId", 9)))
    message("PvpInfo", fields(("rank", 5), ("remainingChallengeCount", 5), ("latestPvpSeason", "Empty")))
    message("HierarchyInfo", fields(("currentDetailGradeId", 9), ("currentRank", 5)))
    message("CommonResponse", fields(("updatedData", "Empty"), ("deletedData", "Empty")))
    message("QuestTopResponse", [("mainAreaGroups", "AreaGroupInfo", True)]
            + fields(("pvpInfo", "PvpInfo"), ("hierarchyNotiInfo", "HierarchyInfo"),
                     ("towerArea", "AreaInfo"), ("contestArea", "AreaInfo"), ("gvgInfo", "Empty"),
                     ("isDailyPlayable", 8), ("currentTowerQuestId", 9), ("isTowerTopUnlocked", 8),
                     ("commonResponse", "CommonResponse")) + [("dailyAreas", "AreaInfo", True)])
    message("QuestListMainResponse", [("areaGroups", "AreaGroupInfo", True)]
            + fields(("commonResponse", "CommonResponse")))
    for service_name, response in [("User", "UserGetResponse"), ("Quest", "QuestTopResponse")]:
        service = file.service.add(name=service_name)
        service.method.add(name="Get" if service_name == "User" else "Top",
                           input_type=".api.Empty", output_type=".api." + response)
    file.service.add(name="System").method.add(name="Check", input_type=".api.Empty", output_type=".api.Empty")
    quest_service = next(service for service in file.service if service.name == "Quest")
    quest_service.method.add(name="ListMain", input_type=".api.Empty", output_type=".api.QuestListMainResponse")
    message("QuestListDailyResponse", [("areas", "AreaInfo", True), ("bulkDailyInfos", "Empty", True)]
            + fields(("commonResponse", "CommonResponse")))
    for name in ("QuestListContestResponse", "QuestListTowerResponse"):
        message(name, fields(("area", "AreaInfo"), ("commonResponse", "CommonResponse")))
    message("QuestTowerTopResponse", fields(("towerArea", "TowerAreaInfo"),
                                            ("hierarchyNotiInfo", "HierarchyInfo"))
            + [("subTowerAreas", "TowerAreaInfo", True)])
    for route in ("ListDaily", "ListContest", "ListTower", "TowerTop"):
        quest_service.method.add(name=route, input_type=".api.Empty",
                                 output_type=".api.Quest" + route + "Response")
    descriptors = descriptor_pb2.FileDescriptorSet()
    descriptors.file.add().CopyFrom(file)
    path.write_bytes(descriptors.SerializeToString())
    return Schema.from_descriptor_set(path)


@pytest.fixture(scope="module", params=("minimal", "client-6.1.1"))
def schema(request, tmp_path_factory):
    if request.param == "minimal":
        return minimal_schema(tmp_path_factory.mktemp("quest-schema") / "schema.pb")
    path = Path(__file__).resolve().parents[1] / "data/protocol/idolypride-6.1.1.pb"
    if not path.is_file():
        pytest.skip("Optional recovered client descriptor is unavailable")
    return Schema.from_descriptor_set(path)


@pytest.fixture
def game(schema, tmp_path):
    directory = tmp_path / "master"
    directory.mkdir()
    rows = {
        "AreaGroup": [{"id": "group-2", "order": 2, "areaIds": ["area-3"]},
                      {"id": "group-1", "order": 1, "areaIds": ["area-1", "area-2"]},
                      {"id": "tutorial-group", "order": 999, "areaIds": ["tutorial"]}],
        "Area": [{"id": "area-" + str(i), "type": 1, "order": i,
                  "areaGroupId": "group-1" if i < 3 else "group-2",
                  "questIds": ["quest-" + str(i) + "-1", "quest-" + str(i) + "-2"]}
                 for i in (1, 2, 3)] + [{"id": "tutorial", "type": 101, "areaGroupId": "tutorial-group",
                                        "questIds": ["tutorial-full", "tutorial-short"]},
                                       {"id": "contest", "type": 2, "questIds": ["contest-quest"]}],
        "Quest": [{"id": "quest-" + str(i) + "-" + str(j), "areaId": "area-" + str(i),
                   "order": j, "clearScore": "1000"} for i in (1, 2, 3) for j in (1, 2)]
                 + [{"id": "contest-quest", "areaId": "contest"},
                    {"id": "tutorial-full", "areaId": "tutorial", "order": 1},
                    {"id": "tutorial-short", "areaId": "tutorial", "order": 1}],
        "HierarchyGrade": [{"id": "grade"}],
        "HierarchyDetailGrade": [{"id": "grade-1", "hierarchyGradeId": "grade",
                                  "requiredHierarchyPoint": "0", "requiredHierarchyRank": 0}],
    }
    for table, data in rows.items():
        (directory / (table + ".json")).write_text(json.dumps(data))
    state = State(tmp_path / "profiles.sqlite")
    snapshot = schema.response_type("/api.User/Get")()
    snapshot.user.name = "Existing manager"
    snapshot.hierarchy.bestDetailGradeId = "grade-1"
    snapshot.areas.add(areaId="area-1")
    snapshot.tutorials.add(tutorialType=1, step=150)
    # Preserve an unknown protobuf field as well as all known account data.
    payload = snapshot.SerializeToString() + b"\xf8\x7f\x01"
    state.save_snapshot("player", payload, schema.fingerprint)
    token, _ = state.login("player")
    return Quest(schema, state, "player", directory), state, directory, rows, token


def top(game):
    quest = game[0]
    return quest.schema.response_type("/api.Quest/Top").FromString(quest.handle("/api.Quest/Top", b""))


def update(game, callback):
    quest, state = game[:2]
    def mutate(raw):
        snapshot = quest.schema.response_type("/api.User/Get").FromString(raw)
        callback(snapshot)
        return snapshot.SerializeToString()
    state.mutate_snapshot("player", quest.schema.fingerprint, mutate)


def database(state):
    with state.connect() as db:
        return list(db.iterdump())


def test_main_catalog_is_real_ordered_and_only_first_main_quest_available(game):
    result = top(game)
    assert [group.areaGroupId for group in result.mainAreaGroups] == ["group-1", "group-2"]
    areas = [area for group in result.mainAreaGroups for area in group.areas]
    assert [area.areaId for area in areas] == ["area-1", "area-2", "area-3"]
    assert [area.unlocked for area in areas] == [True, False, False]
    assert [quest.isPlayable for area in areas for quest in area.quests] == [True, False, False, False, False, False]
    assert not any(quest.cleared or quest.highestScore or quest.rankType for area in areas for quest in area.quests)
    assert result.HasField("pvpInfo") and not result.pvpInfo.HasField("latestPvpSeason")
    assert result.pvpInfo.rank == result.pvpInfo.remainingChallengeCount == 0
    assert result.hierarchyNotiInfo.currentDetailGradeId == "grade-1"
    assert result.HasField("contestArea")
    assert result.contestArea.areaId == "contest"
    assert [row.questId for row in result.contestArea.quests] == ["contest-quest"]
    assert not result.contestArea.unlocked
    assert not any(row.isPlayable or row.cleared or row.highestScore or row.campaignDropRewardIds
                   for row in result.contestArea.quests)
    assert not any(result.HasField(name) for name in ("towerArea", "gvgInfo"))
    assert not result.isDailyPlayable
    assert result.HasField("commonResponse")
    assert not result.commonResponse.HasField("updatedData")


def test_partial_and_completed_main_progress_project_without_writes(game):
    def progress(snapshot):
        snapshot.areas[0].clearQuestCount = 1
        snapshot.quests.add(questId="quest-1-1", lastClearedTime=123, highestScore=4567,
                            highestRank=12, highestScoreRank=4)
    update(game, progress)
    before = database(game[1])
    result = top(game)
    first, second = result.mainAreaGroups[0].areas
    assert first.quests[0].cleared and first.quests[0].highestScore == 4567
    assert first.quests[0].highestRank == 12 and first.quests[0].rankType == 4
    assert first.quests[1].isPlayable and not first.quests[1].cleared
    assert not second.unlocked
    assert database(game[1]) == before
    assert game[1].authenticated(game[4], "player")

    def complete(snapshot):
        snapshot.areas[0].clearQuestCount = 2
        snapshot.quests.add(questId="quest-1-2", lastClearedTime=456)
    update(game, complete)
    result = top(game)
    assert result.mainAreaGroups[0].areas[1].unlocked
    assert result.mainAreaGroups[0].areas[1].quests[0].isPlayable
    assert not result.mainAreaGroups[1].areas[0].unlocked


def test_score_alone_is_not_a_fabricated_clear_or_reward(game):
    update(game, lambda snapshot: snapshot.quests.add(questId="quest-1-1", highestScore=99999, highestScoreRank=5))
    result = top(game)
    first = result.mainAreaGroups[0].areas[0]
    assert first.quests[0].highestScore == 99999
    assert not first.quests[0].cleared and not first.quests[1].isPlayable
    assert not result.mainAreaGroups[0].areas[1].unlocked


def test_stored_area_count_establishes_frontier_without_inventing_individual_clears(game):
    update(game, lambda snapshot: setattr(snapshot.areas[0], "clearQuestCount", 1))
    result = top(game)
    first = result.mainAreaGroups[0].areas[0]
    assert all(quest.isPlayable for quest in first.quests)
    assert not any(quest.cleared or quest.highestScore for quest in first.quests)
    assert not result.mainAreaGroups[0].areas[1].unlocked


def test_unknown_unlock_condition_is_not_silently_satisfied(game):
    game[3]["Quest"][0]["unlockConditionId"] = "unsupported-condition"
    (game[2] / "Quest.json").write_text(json.dumps(game[3]["Quest"]))
    assert not top(game).mainAreaGroups[0].areas[0].quests[0].isPlayable


def test_area_conditions_are_not_satisfied_by_only_completing_previous_area(game):
    game[3]["Area"][1]["unlockConditionId"] = "manager-level-not-evaluated"
    (game[2] / "Area.json").write_text(json.dumps(game[3]["Area"]))
    update(game, lambda snapshot: setattr(snapshot.areas[0], "clearQuestCount", 2))
    assert not top(game).mainAreaGroups[0].areas[1].unlocked


def test_list_main_shares_validated_top_progress_and_preserves_database(game):
    update(game, lambda snapshot: snapshot.quests.add(questId="quest-1-1", lastClearedTime=123,
                                                      highestScore=4567, highestScoreRank=4))
    before = database(game[1])
    expected = top(game)
    quest = game[0]
    response = quest.schema.response_type("/api.Quest/ListMain").FromString(
        quest.handle("/api.Quest/ListMain", b""))
    assert [row.SerializeToString() for row in response.areaGroups] == [
        row.SerializeToString() for row in expected.mainAreaGroups]
    assert response.HasField("commonResponse")
    assert not response.commonResponse.HasField("updatedData")
    assert database(game[1]) == before


def test_required_contest_catalog_projects_existing_history_without_enabling_battles(game):
    update(game, lambda snapshot: snapshot.quests.add(questId="contest-quest", lastClearedTime=123,
                                                      highestScore=45678, highestRank=345, highestScoreRank=5))
    before = database(game[1])
    result = top(game)
    # Regression for LiveTop's unconditional model.ContestArea.quests read at
    # 0x5759ce8..0x5759cf4, after the callback itself has accepted null.
    assert result.HasField("contestArea")
    row = result.contestArea.quests[0]
    assert (row.questId, row.cleared, row.highestScore, row.highestRank, row.rankType) == (
        "contest-quest", True, 45678, 345, 5)
    assert not result.contestArea.unlocked and not row.isPlayable and row.playableCount == 0
    assert database(game[1]) == before


@pytest.mark.parametrize("change", [
    lambda rows: rows.pop(),
    lambda rows: rows.append({"id": "second-contest", "type": 2, "questIds": ["contest-quest"]}),
    lambda rows: rows[-1].update(questIds=[]),
    lambda rows: rows[-1].update(questIds=["quest-1-1"]),
])
def test_missing_ambiguous_or_invalid_contest_catalog_is_not_empty_success(game, change):
    change(game[3]["Area"])
    (game[2] / "Area.json").write_text(json.dumps(game[3]["Area"]))
    before = database(game[1])
    with pytest.raises(RpcFailure) as caught:
        top(game)
    assert caught.value.code == RpcCode.FAILED_PRECONDITION
    assert database(game[1]) == before


@pytest.mark.parametrize("step", [150, 1000000])
def test_finished_game_start_omits_dedicated_tutorial_group(game, step):
    update(game, lambda snapshot: setattr(snapshot.tutorials[0], "step", step))
    assert [row.areaGroupId for row in top(game).mainAreaGroups] == ["group-1", "group-2"]


@pytest.mark.parametrize("step", [None, 0, 10, 100, 149])
def test_pending_game_start_exposes_real_playable_alternates_without_progress_writes(game, step):
    def progress(snapshot):
        if step is None:
            del snapshot.tutorials[:]
        else:
            snapshot.tutorials[0].step = step
    update(game, progress)
    before = database(game[1])
    result = top(game)
    tutorial = result.mainAreaGroups[-1]
    assert tutorial.areaGroupId == "tutorial-group"
    assert tutorial.areas[0].areaId == "tutorial" and tutorial.areas[0].unlocked
    assert [(row.questId, row.isPlayable, row.cleared) for row in tutorial.areas[0].quests] == [
        ("tutorial-full", True, False), ("tutorial-short", True, False)]
    assert database(game[1]) == before
    listing = game[0].schema.response_type("/api.Quest/ListMain").FromString(
        game[0].handle("/api.Quest/ListMain", b""))
    assert listing.areaGroups[-1].SerializeToString() == tutorial.SerializeToString()
    assert database(game[1]) == before


def test_read_only_preserves_exact_snapshot_other_profile_and_sessions(game):
    quest, state = game[:2]
    other = quest.schema.response_type("/api.User/Get")(user={"name": "Other manager"})
    state.save_snapshot("other", other.SerializeToString(), quest.schema.fingerprint)
    other_token, _ = state.login("other")
    before = database(state)
    assert quest.handle("/api.Quest/Top", b"") == quest.handle("/api.Quest/Top", b"")
    assert database(state) == before
    assert state.authenticated(game[4], "player") and state.authenticated(other_token, "other")
    assert state.snapshot("player")[0].endswith(b"\xf8\x7f\x01")


@pytest.mark.parametrize("table,change", [
    ("AreaGroup", lambda rows: rows[0].update(areaIds=["missing"])),
    ("AreaGroup", lambda rows: rows[1].update(areaIds=["area-1", "area-1"])),
    ("Area", lambda rows: rows[0].update(areaGroupId="wrong")),
    ("Area", lambda rows: rows[0].update(questIds=["quest-2-1"])),
    ("Quest", lambda rows: rows[0].update(areaId="wrong")),
])
def test_invalid_catalog_references_fail_explicitly(game, table, change):
    change(game[3][table])
    (game[2] / (table + ".json")).write_text(json.dumps(game[3][table]))
    before = database(game[1])
    with pytest.raises(RpcFailure) as caught:
        top(game)
    assert caught.value.code == RpcCode.FAILED_PRECONDITION
    assert database(game[1]) == before


@pytest.mark.parametrize("change", [
    lambda snapshot: setattr(snapshot.areas[0], "clearQuestCount", 3),
    lambda snapshot: snapshot.areas.add(areaId="missing"),
    lambda snapshot: snapshot.quests.add(questId="missing"),
    lambda snapshot: snapshot.quests.add(questId="quest-1-1", highestScore=-1),
    lambda snapshot: snapshot.quests.add(questId="quest-1-1", highestRank=1 << 35),
    lambda snapshot: snapshot.quests.add(questId="quest-1-1", highestScoreRank=99),
    lambda snapshot: snapshot.areas.add(areaId="area-1"),
])
def test_invalid_persisted_progress_fails_without_mutation(game, change):
    update(game, change)
    before = database(game[1])
    with pytest.raises(RpcFailure) as caught:
        top(game)
    assert caught.value.code == RpcCode.FAILED_PRECONDITION
    assert database(game[1]) == before


def test_constructor_and_unsupported_routes_are_lazy():
    quest = Quest(object(), object(), "profile", Path("/nonexistent"))
    assert quest.handle("/api.Quest/Start", b"invalid") is None
    assert quest.handle("/api.Tutorial/StartQuest", b"") is None


def test_malformed_request_missing_catalog_and_schema_mismatch_fail(game):
    with pytest.raises(RpcFailure) as caught:
        game[0].handle("/api.Quest/Top", b"\xff")
    assert caught.value.code == RpcCode.INVALID_ARGUMENT
    (game[2] / "AreaGroup.json").unlink()
    with pytest.raises(RpcFailure) as caught:
        top(game)
    assert caught.value.code == RpcCode.FAILED_PRECONDITION
    game[1].save_snapshot("player", b"", "different-schema")
    with pytest.raises(RpcFailure, match="different schema"):
        top(game)
