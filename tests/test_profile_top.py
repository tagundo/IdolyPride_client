"""Profile headers use saved hierarchy points and never update the account."""
from pathlib import Path
import json

from google.protobuf import descriptor_pb2
import pytest

from idoly_local.gameplay import _Catalog
from idoly_local.profile_top import ProfileTop
from idoly_local.rpc import RpcCode, RpcFailure
from idoly_local.schema import Schema
from idoly_local.state import State
from test_profile_names import USER, dump, game, protected, small_schema as name_schema


PATH = "/api.Profile/Top"


def small_schema(path):
    name_schema(path)
    descriptors = descriptor_pb2.FileDescriptorSet.FromString(path.read_bytes())
    file = descriptors.file[0]
    response = file.message_type.add(name="ProfileTopResponse")
    response.field.add(name="hierarchyCurrentDetailGradeId", number=1, label=1, type=9)
    response.field.add(name="hierarchyCurrentRank", number=2, label=1, type=5)
    response.field.add(name="friendProfiles", number=3, label=3, type=11, type_name=".api.Empty")
    response.field.add(name="commonResponse", number=9999, label=1, type=11, type_name=".api.CommonResponse")
    service = next(service for service in file.service if service.name == "Profile")
    service.method.add(name="Top", input_type=".api.Empty", output_type=".api.ProfileTopResponse")
    path.write_bytes(descriptors.SerializeToString())
    return Schema.from_descriptor_set(path)


@pytest.fixture(scope="module", params=("small", "client-6.1.1"))
def schema(request, tmp_path_factory):
    if request.param == "small":
        return small_schema(tmp_path_factory.mktemp("profile-top-schema") / "schema.pb")
    source = Path(__file__).resolve().parents[1] / "data/protocol/idolypride-6.1.1.pb"
    if not source.is_file():
        pytest.skip("Optional recovered 6.1.1 descriptor is unavailable")
    return Schema.from_descriptor_set(source)


@pytest.fixture
def top(game, tmp_path):
    master = tmp_path / "master"
    master.mkdir()
    grades = [{"id": "grade-low"}, {"id": "grade-high"}]
    details = [
        {"id": "detail-low", "hierarchyGradeId": "grade-low", "requiredHierarchyPoint": "0", "requiredHierarchyRank": 0},
        {"id": "detail-high", "hierarchyGradeId": "grade-high", "requiredHierarchyPoint": "100", "requiredHierarchyRank": 0},
        {"id": "detail-ranked", "hierarchyGradeId": "grade-high", "requiredHierarchyPoint": "200", "requiredHierarchyRank": 1},
    ]
    (master / "HierarchyGrade.json").write_text(json.dumps(grades))
    (master / "HierarchyDetailGrade.json").write_text(json.dumps(details))
    provider, state = game[:2]
    def prepare(raw):
        snapshot = provider.schema.response_type(USER).FromString(raw)
        snapshot.hierarchy.bestDetailGradeId = "detail-low"
        return snapshot.SerializeToString()
    state.mutate_snapshot("player", provider.schema.fingerprint, prepare)
    return ProfileTop(provider.schema, state, "player", _Catalog(master)), master, details, grades


def change(game, **values):
    provider, state = game[:2]
    def update(raw):
        snapshot = provider.schema.response_type(USER).FromString(raw)
        for key, value in values.items():
            setattr(snapshot.hierarchy, key, value)
        return snapshot.SerializeToString()
    state.mutate_snapshot("player", provider.schema.fingerprint, update)


@pytest.mark.parametrize("fixed,variable,expected", ((0, 0, "detail-low"), (60, 39, "detail-low"),
    (60, 40, "detail-high"), (150, 100, "detail-high")))
def test_saved_points_select_real_unranked_grade_without_any_writes(game, top, fixed, variable, expected):
    provider, master = top[:2]
    change(game, currentFixedPoint=fixed, currentVariablePoint=variable)
    before = dump(game[1])
    master_bytes = {path.name: path.read_bytes() for path in master.iterdir()}
    result = provider.schema.response_type(PATH).FromString(provider.handle(PATH, b""))
    assert result.hierarchyCurrentDetailGradeId == expected
    assert result.hierarchyCurrentRank == 0
    assert not result.friendProfiles
    assert result.HasField("commonResponse")
    assert not result.commonResponse.ListFields()
    assert dump(game[1]) == before
    assert {path.name: path.read_bytes() for path in master.iterdir()} == master_bytes
    assert provider.handle(PATH, b"") == result.SerializeToString()
    restarted = State(game[1].path)
    replay = ProfileTop(provider.schema, restarted, "player", _Catalog(master))
    assert replay.handle(PATH, b"") == result.SerializeToString()
    assert dump(restarted) == before


@pytest.mark.parametrize("problem", ("negative-points", "unknown-best", "missing-table", "empty-table",
                                    "missing-parent", "ambiguous-threshold", "invalid-threshold"))
def test_inconsistent_snapshot_or_catalog_fails_instead_of_empty_success(game, top, problem):
    provider, master, details, grades = top
    if problem == "negative-points":
        change(game, currentFixedPoint=-1)
    elif problem == "unknown-best":
        change(game, bestDetailGradeId="missing")
    elif problem == "missing-table":
        (master / "HierarchyDetailGrade.json").unlink()
    elif problem == "empty-table":
        (master / "HierarchyDetailGrade.json").write_text("[]")
    else:
        if problem == "missing-parent":
            details[0]["hierarchyGradeId"] = "missing"
        elif problem == "ambiguous-threshold":
            details.append(dict(details[0], id="another-zero-grade"))
        else:
            details[0]["requiredHierarchyPoint"] = "not-a-number"
        (master / "HierarchyDetailGrade.json").write_text(json.dumps(details))
    before = dump(game[1])
    with pytest.raises(RpcFailure) as error:
        provider.handle(PATH, b"")
    assert error.value.code == RpcCode.FAILED_PRECONDITION
    assert dump(game[1]) == before


@pytest.mark.parametrize("problem", ("missing", "wrong-schema", "malformed", "no-user"))
def test_unusable_profile_snapshot_is_rejected_without_changes(game, top, problem):
    provider, state = top[0], game[1]
    with state.connect() as connection:
        if problem == "missing":
            connection.execute("DELETE FROM snapshots WHERE profile='player'")
        elif problem == "wrong-schema":
            connection.execute("UPDATE snapshots SET schema_sha256='other' WHERE profile='player'")
        else:
            raw = b"\x0a\x80" if problem == "malformed" else provider.schema.response_type(USER)().SerializeToString()
            connection.execute("UPDATE snapshots SET response=? WHERE profile='player'", (raw,))
    before = dump(state)
    with pytest.raises(RpcFailure) as error:
        provider.handle(PATH, b"")
    assert error.value.code == RpcCode.FAILED_PRECONDITION
    assert dump(state) == before


def test_malformed_request_and_other_profile_routes_do_not_touch_database(game, top):
    provider = top[0]
    before = dump(game[1])
    with pytest.raises(RpcFailure) as error:
        provider.handle(PATH, b"\x0a\x80")
    assert error.value.code == RpcCode.INVALID_ARGUMENT
    assert provider.handle("/api.Profile/FindUser", b"") is None
    assert dump(game[1]) == before
