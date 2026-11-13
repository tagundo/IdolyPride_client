"""Company gallery reads use public masters without reporting or granting state."""
import json
from pathlib import Path

import pytest

from idoly_local.company import CompanyReads, prepare_company_reads
from idoly_local.rpc import RpcCode, RpcFailure
from idoly_local.schema import Schema
from idoly_local.state import State


TOP = "/api.Company/Top"
ENJOY = "/api.Company/EnjoyCharacterTop"
USER = "/api.User/Get"
UNKNOWN = b"\x80\x4b\x7b"


@pytest.fixture(scope="module")
def schema():
    source = Path(__file__).resolve().parents[1] / "data/protocol/idolypride-6.1.1.pb"
    if not source.is_file():
        pytest.skip("Recovered 6.1.1 descriptor is unavailable")
    return Schema.from_descriptor_set(source)


@pytest.fixture
def game(schema, tmp_path):
    master = tmp_path / "master"
    master.mkdir()
    tables = {
        "Character": [{"id": "char-a"}, {"id": "char-b"}, {"id": "char-special"},
                      {"id": "char-unowned"}],
        "CompanyGrade": [{"id": "grade-next", "requiredPoint": "200"},
                         {"id": "grade-base", "requiredPoint": "0"}],
        "CompanyTrustLevel": [{"levelKey": 2, "requiredPoint": "100"},
                              {"levelKey": 1, "requiredPoint": "0"}],
        "CompanyEnjoyCharacterLevel": [{"levelKey": 1, "requiredPoint": "0"},
                                       {"levelKey": 2, "requiredPoint": "10"}],
        "CompanyEnjoyCharacterLevelSetting": [
            {"characterId": "char-a", "levelKey": 1, "achieveRewardId": "reward-a1"},
            {"characterId": "char-a", "levelKey": 2, "achieveRewardId": "reward-a2"},
            {"characterId": "char-b", "levelKey": 1, "achieveRewardId": "reward-b1"},
        ],
        "Mission": [
            {"id": "trust", "companyTrustMissionCategoryType": 3,
             "progresses": [{"threshold": "10"}]},
            {"id": "enjoy-a", "companyEnjoyCharacterId": "char-a",
             "companyEnjoyCharacterMissionCategoryType": 2,
             "progresses": [{"threshold": "20"}]},
            {"id": "enjoy-b", "companyEnjoyCharacterId": "char-b",
             "companyEnjoyCharacterMissionCategoryType": 1,
             "progresses": [{"threshold": "30"}]},
            {"id": "unstarted-trust", "companyTrustMissionCategoryType": 1,
             "progresses": [{"threshold": "10"}]},
        ],
    }
    for name, rows in tables.items():
        (master / (name + ".json")).write_text(json.dumps(rows))
    state = State(tmp_path / "state.sqlite")
    state.ensure_profile("media")
    snapshot = schema.response_type(USER)()
    snapshot.user.name = "Media manager"
    snapshot.user.MergeFromString(UNKNOWN)
    snapshot.company.enjoyPoint = 123
    snapshot.company.trustPoint = 456
    snapshot.company.salaryPoint = 789
    snapshot.company.isAlreadyTransitioned = True
    snapshot.company.MergeFromString(UNKNOWN)
    for identity in ("char-a", "char-b", "char-special"):
        snapshot.characters.add(characterId=identity, companyEnjoyPoint=7)
    for identity, threshold in (("trust", 10), ("enjoy-a", 20), ("enjoy-b", 30), ("legacy", 5)):
        snapshot.missions.add(missionId=identity, currentThreshold=threshold,
                              progress=1, statusType=1).MergeFromString(UNKNOWN)
    snapshot.items.add(itemId="preserved-currency", amount=13)
    snapshot.MergeFromString(UNKNOWN)
    state.save_snapshot("media", snapshot.SerializeToString(), schema.fingerprint, starter_version=4)
    state.save_snapshot("ordinary", snapshot.SerializeToString(), schema.fingerprint)
    state.login("media")
    state.login("ordinary")
    return CompanyReads(schema, state, "media", master, media_mode=True), state, master


def dump(state):
    with state.connect() as connection:
        return tuple(connection.iterdump())


def call(game, path, **values):
    provider = game[0]
    raw = provider.handle(path, provider.schema.request_type(path)(**values).SerializeToString())
    assert raw is not None
    return provider.schema.response_type(path).FromString(raw)


@pytest.mark.parametrize("skip", (False, True))
def test_top_returns_real_grade_levels_and_only_preserved_missions_without_writes(game, skip):
    before = dump(game[1])
    result = call(game, TOP, isSkipReportMissions=skip)
    assert [row.id for row in result.companyGradeInfos] == ["grade-base", "grade-next"]
    assert [row.levelKey for row in result.trustLevelInfos] == [1, 2]
    assert [row.categoryType for row in result.trustMissionInfos] == [1, 2, 3, 4]
    assert [(row.categoryType, [mission.missionId for mission in row.userMissions])
            for row in result.trustMissionInfos] == [(1, []), (2, []), (3, ["trust"]), (4, [])]
    stored = game[0].schema.response_type(USER).FromString(game[1].snapshot("media")[0])
    assert result.trustMissionInfos[2].userMissions[0] == stored.missions[0]
    assert not any(row.isReceivable or row.isAlreadyReceived for row in result.companyGradeInfos)
    assert not any(row.isReceivable or row.isAlreadyReceived for row in result.trustLevelInfos)
    assert not result.currentRank and not result.thisMonthSalaryPoint
    assert not result.receivableLevelRewardEnjoyCharacterIds and not result.dokanInfos
    assert result.HasField("commonResponse")
    assert not result.commonResponse.HasField("updatedData")
    assert not result.commonResponse.HasField("deletedData")
    assert result.commonResponse.SerializeToString() == b""
    assert dump(game[1]) == before
    assert call(game, TOP, isSkipReportMissions=skip) == result
    assert dump(game[1]) == before


def test_character_read_returns_only_actual_character_settings_and_stored_missions(game):
    before = dump(game[1])
    result = call(game, ENJOY, characterId="char-a")
    assert [(row.characterId, row.levelKey) for row in result.enjoyLevelInfos] == [
        ("char-a", 1), ("char-a", 2)]
    assert [(row.categoryType, [mission.missionId for mission in row.userMissions])
            for row in result.missionInfos] == [(1, []), (2, ["enjoy-a"]), (3, [])]
    assert not any(row.isReceivable or row.isAlreadyReceived for row in result.enjoyLevelInfos)
    assert result.HasField("commonResponse")
    assert not result.commonResponse.HasField("updatedData")
    assert not result.commonResponse.HasField("deletedData")
    assert result.commonResponse.SerializeToString() == b""
    assert call(game, ENJOY, characterId="char-a") == result
    assert dump(game[1]) == before


@pytest.mark.parametrize("identity,code", (("", RpcCode.INVALID_ARGUMENT),
    ("unknown", RpcCode.INVALID_ARGUMENT), ("char-unowned", RpcCode.PERMISSION_DENIED),
    ("char-special", RpcCode.FAILED_PRECONDITION)))
def test_character_read_rejects_invalid_or_unowned_ids_atomically(game, identity, code):
    before = dump(game[1])
    with pytest.raises(RpcFailure) as error:
        call(game, ENJOY, characterId=identity)
    assert error.value.code == code
    assert dump(game[1]) == before


def test_normal_mode_and_unimplemented_claim_paths_stay_unhandled(game):
    provider, state, master = game
    before = dump(state)
    normal = CompanyReads(provider.schema, state, "ordinary", master)
    assert normal.handle(TOP, b"") is None
    assert normal.handle(ENJOY, b"") is None
    for path in ("/api.Company/ReceiveGradeRewards", "/api.Company/BulkReceiveMission",
                 "/api.Company/UseEnjoyObtainPointItem", "/api.Company/ListRanking"):
        assert provider.handle(path, b"") is None
    assert dump(state) == before


def test_malformed_requests_and_missing_tables_fail_without_writes(game):
    before = dump(game[1])
    with pytest.raises(RpcFailure) as error:
        game[0].handle(TOP, b"\xff")
    assert error.value.code == RpcCode.INVALID_ARGUMENT
    (game[2] / "CompanyGrade.json").unlink()
    with pytest.raises(RpcFailure) as error:
        call(game, TOP)
    assert error.value.code == RpcCode.FAILED_PRECONDITION
    assert dump(game[1]) == before


def test_invalid_company_mission_reference_is_not_rewritten_or_reported(game):
    provider, state, _ = game
    raw, fingerprint = state.snapshot("media")
    snapshot = provider.schema.response_type(USER).FromString(raw)
    snapshot.missions[0].currentThreshold = 999
    state.mutate_snapshot("media", fingerprint, lambda _: snapshot.SerializeToString())
    before = dump(state)
    with pytest.raises(RpcFailure) as error:
        call(game, TOP)
    assert error.value.code == RpcCode.FAILED_PRECONDITION
    assert dump(state) == before


def test_schema_mismatch_fails_before_state_changes(game):
    provider, state, _ = game
    raw, _ = state.snapshot("media")
    state.save_snapshot("media", raw, "different-schema")
    before = dump(state)
    with pytest.raises(RpcFailure) as error:
        call(game, TOP)
    assert error.value.code == RpcCode.FAILED_PRECONDITION
    assert dump(state) == before


def test_catalog_validation_is_pure_and_rejects_dangling_character_level_references(game):
    _, state, master = game
    before = dump(state)
    grades, trust, settings, characters = prepare_company_reads(master)
    assert set(grades) == {"grade-base", "grade-next"}
    assert set(trust) == {1, 2}
    assert settings == {"char-a": {1, 2}, "char-b": {1}}
    assert "char-special" in characters
    source = master / "CompanyEnjoyCharacterLevelSetting.json"
    rows = json.loads(source.read_text())
    rows.append({"characterId": "char-a", "levelKey": 99, "achieveRewardId": "missing-level"})
    source.write_text(json.dumps(rows))
    with pytest.raises(RpcFailure) as error:
        prepare_company_reads(master)
    assert error.value.code == RpcCode.FAILED_PRECONDITION
    assert dump(state) == before
