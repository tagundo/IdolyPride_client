"""Owned emblem preferences preserve account state and survive lost replies."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
import json
from types import SimpleNamespace

from google.protobuf import descriptor_pb2
import pytest

from idoly_local.profile_emblems import ProfileEmblems
from idoly_local.rpc import RpcCode, RpcFailure
from idoly_local.schema import Schema
from idoly_local.state import State
from test_profile_names import USER, UNKNOWN, dump, game, protected, small_schema as name_schema


PATH = "/api.Profile/UpdateEmblem"


def small_schema(path):
    name_schema(path)
    descriptors = descriptor_pb2.FileDescriptorSet.FromString(path.read_bytes())
    file = descriptors.file[0]
    next(message for message in file.message_type if message.name == "Manager").field.add(
        name="emblemId", number=24, label=1, type=9)
    emblem = file.message_type.add(name="OwnedEmblem")
    emblem.field.add(name="emblemId", number=1, label=1, type=9)
    mission = file.message_type.add(name="EmblemUnrelatedMission")
    mission.field.add(name="missionId", number=1, label=1, type=9)
    mission.field.add(name="progress", number=3, label=1, type=3)
    for name in ("UserGetResponse", "UpdatedData"):
        message = next(message for message in file.message_type if message.name == name)
        message.field.add(name="emblems", number=100, label=3, type=11, type_name=".api.OwnedEmblem")
        message.field.add(name="missions", number=101, label=3, type=11,
                          type_name=".api.EmblemUnrelatedMission")
    request = file.message_type.add(name="ProfileEmblemRequest")
    request.field.add(name="emblemId", number=1, label=1, type=9)
    next(service for service in file.service if service.name == "Profile").method.add(
        name="UpdateEmblem", input_type=".api.ProfileEmblemRequest", output_type=".api.ActionResponse")
    path.write_bytes(descriptors.SerializeToString())
    return Schema.from_descriptor_set(path)


@pytest.fixture(scope="module", params=("small", "client-6.1.1"))
def schema(request, tmp_path_factory):
    if request.param == "small":
        return small_schema(tmp_path_factory.mktemp("profile-emblems-schema") / "schema.pb")
    source = Path(__file__).resolve().parents[1] / "data/protocol/idolypride-6.1.1.pb"
    if not source.is_file():
        pytest.skip("Optional recovered 6.1.1 descriptor is unavailable")
    return Schema.from_descriptor_set(source)


@pytest.fixture
def emblems(game, tmp_path):
    names, state = game[:2]
    master = tmp_path / "master"
    master.mkdir()
    (master / "Emblem.json").write_text(json.dumps(
        [{"id": key} for key in ("emblem-a", "emblem-b", "emblem-not-owned")]))
    def prepare(raw):
        value = names.schema.response_type(USER).FromString(raw)
        value.user.emblemId = "emblem-a"
        for key in ("emblem-a", "emblem-b"):
            value.emblems.add(emblemId=key).MergeFromString(UNKNOWN)
        value.missions.add(missionId="kept-mission", progress=123).MergeFromString(UNKNOWN)
        return value.SerializeToString()
    state.mutate_snapshot("player", names.schema.fingerprint, prepare)
    return ProfileEmblems(names.schema, state, "player", master)


def snapshot(game):
    return game[0].schema.response_type(USER).FromString(game[1].snapshot("player")[0])


def call(emblems, identity):
    raw = emblems.schema.request_type(PATH)(emblemId=identity).SerializeToString()
    return emblems.schema.response_type(PATH).FromString(emblems.handle(PATH, raw))


def test_owned_selection_changes_only_user_emblem_and_persists_through_restart(game, emblems):
    state = game[1]
    expected = snapshot(game)
    expected.user.emblemId = "emblem-b"
    kept = protected(state)
    result = call(emblems, "emblem-b")
    assert state.snapshot("player")[0] == expected.SerializeToString()
    assert result.HasField("commonResponse")
    assert result.commonResponse.HasField("updatedData")
    assert not result.commonResponse.HasField("deletedData")
    assert result.commonResponse.updatedData.user == expected.user
    assert {field.name for field, _ in result.commonResponse.updatedData.ListFields()} == {"user"}
    assert UNKNOWN in result.commonResponse.updatedData.user.SerializeToString()
    assert protected(state) == kept
    before_retry = dump(state)
    assert call(emblems, "emblem-b") == result
    restarted = State(state.path)
    replay = ProfileEmblems(emblems.schema, restarted, "player", emblems.catalog.directory)
    raw = emblems.schema.request_type(PATH)(emblemId="emblem-b").SerializeToString()
    assert replay.handle(PATH, raw) == result.SerializeToString()
    assert dump(restarted) == before_retry
    assert restarted.authenticated(game[2], "player")
    assert restarted.authenticated(game[3], "other")


def test_identical_retry_keeps_original_wire_bytes_and_avoids_snapshot_write(game, emblems, monkeypatch):
    state = game[1]
    original = UNKNOWN + state.snapshot("player")[0]
    with state.connect() as db:
        db.execute("UPDATE snapshots SET response=? WHERE profile='player'", (original,))
    expected = snapshot(game)
    assert expected.SerializeToString() != original
    before = dump(state)
    statements = []
    connect = state.connect
    @contextmanager
    def traced_connect():
        with connect() as db:
            db.set_trace_callback(statements.append)
            yield db
    monkeypatch.setattr(state, "connect", traced_connect)
    result = call(emblems, "emblem-a")
    assert result.commonResponse.updatedData.user == expected.user
    assert state.snapshot("player")[0] == original
    assert dump(state) == before
    assert not any(sql.upper().startswith("UPDATE SNAPSHOTS") for sql in statements)


@pytest.mark.parametrize("identity,code", (("", RpcCode.INVALID_ARGUMENT),
    ("unknown", RpcCode.INVALID_ARGUMENT), ("emblem-not-owned", RpcCode.PERMISSION_DENIED)))
def test_invalid_or_unowned_selection_is_not_granted_and_changes_no_database_state(
        game, emblems, identity, code):
    before = dump(game[1])
    with pytest.raises(RpcFailure) as error:
        call(emblems, identity)
    assert error.value.code == code
    assert dump(game[1]) == before


@pytest.mark.parametrize("raw", (b"\x0a\x80", b"\x0a\x01\xff"))
def test_malformed_protobuf_or_utf8_is_invalid_without_writes(game, emblems, raw):
    before = dump(game[1])
    with pytest.raises(RpcFailure) as error:
        emblems.handle(PATH, raw)
    assert error.value.code == RpcCode.INVALID_ARGUMENT
    assert dump(game[1]) == before


@pytest.mark.parametrize("problem", ("missing", "wrong-schema", "malformed", "no-user",
    "empty-owned-id", "duplicate-owned-id", "missing-master", "malformed-master", "duplicate-master"))
def test_unusable_state_or_master_is_not_repaired_or_partially_saved(game, emblems, problem):
    state = game[1]
    with state.connect() as db:
        if problem == "missing":
            db.execute("DELETE FROM snapshots WHERE profile='player'")
        elif problem == "wrong-schema":
            db.execute("UPDATE snapshots SET schema_sha256='other' WHERE profile='player'")
        elif problem in ("malformed", "no-user", "empty-owned-id", "duplicate-owned-id"):
            value = snapshot(game)
            if problem == "no-user":
                value.ClearField("user")
            elif problem in ("empty-owned-id", "duplicate-owned-id"):
                value.emblems.add(emblemId="" if problem == "empty-owned-id" else "emblem-a")
            raw = b"\x0a\x80" if problem == "malformed" else value.SerializeToString()
            db.execute("UPDATE snapshots SET response=? WHERE profile='player'", (raw,))
    source = emblems.catalog.directory / "Emblem.json"
    if problem == "missing-master":
        source.unlink()
    elif problem == "malformed-master":
        source.write_text("{")
    elif problem == "duplicate-master":
        source.write_text('[{"id":"emblem-a"},{"id":"emblem-a"}]')
    before = dump(state)
    with pytest.raises(RpcFailure) as error:
        call(emblems, "emblem-b")
    assert error.value.code == RpcCode.FAILED_PRECONDITION
    assert dump(state) == before


def test_other_profile_ownership_does_not_authorize_emblem(game, emblems):
    state = game[1]
    def prepare_other(raw):
        value = emblems.schema.response_type(USER).FromString(raw)
        value.emblems.add(emblemId="emblem-not-owned")
        return value.SerializeToString()
    state.mutate_snapshot("other", emblems.schema.fingerprint, prepare_other)
    before = dump(state)
    with pytest.raises(RpcFailure) as error:
        call(emblems, "emblem-not-owned")
    assert error.value.code == RpcCode.PERMISSION_DENIED
    assert dump(state) == before


def test_empty_inventory_does_not_create_emblem_ownership(game, emblems):
    def remove_owned(raw):
        value = emblems.schema.response_type(USER).FromString(raw)
        del value.emblems[:]
        return value.SerializeToString()
    game[1].mutate_snapshot("player", emblems.schema.fingerprint, remove_owned)
    before = dump(game[1])
    with pytest.raises(RpcFailure) as error:
        call(emblems, "emblem-b")
    assert error.value.code == RpcCode.PERMISSION_DENIED
    assert dump(game[1]) == before


def test_emblem_and_unrelated_name_updates_do_not_overwrite_each_other(game, emblems):
    names, state = game[:2]
    kept = protected(state)
    def update(index):
        if index % 2:
            call(emblems, "emblem-b")
        else:
            raw = names.schema.request_type("/api.Profile/UpdateName")(name="Name" + str(index)).SerializeToString()
            names.handle("/api.Profile/UpdateName", raw)
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(update, range(20)))
    value = snapshot(game)
    assert value.user.emblemId == "emblem-b"
    assert value.user.name in {"Name" + str(index) for index in range(0, 20, 2)}
    assert protected(state) == kept


def test_unrelated_route_and_unavailable_method_are_not_claimed(game, emblems):
    before = dump(game[1])
    assert emblems.handle("/api.Profile/UpdateName", b"") is None
    unavailable = ProfileEmblems(SimpleNamespace(methods={}), game[1], "player", emblems.catalog.directory)
    assert unavailable.handle(PATH, b"") is None
    assert dump(game[1]) == before
