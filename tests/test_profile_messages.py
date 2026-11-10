"""Introductions preserve the authoritative profile and unrelated local state."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from google.protobuf import descriptor_pb2
import pytest

from idoly_local.profile_messages import ProfileMessages
from idoly_local.rpc import RpcCode, RpcFailure
from idoly_local.schema import Schema
from idoly_local.state import State
from test_profile_names import USER, UNKNOWN, dump, game, small_schema as name_schema


PATH = "/api.Profile/UpdateMessage"


def small_schema(path):
    name_schema(path)
    descriptors = descriptor_pb2.FileDescriptorSet.FromString(path.read_bytes())
    file = descriptors.file[0]
    profile = next(message for message in file.message_type if message.name == "SavedProfile")
    for name, number, kind in (("message", 4, 9), ("birthMonth", 5, 3), ("birthDay", 6, 3),
                               ("layoutType", 8, 5)):
        profile.field.add(name=name, number=number, label=1, type=kind)
    request = file.message_type.add(name="ProfileMessageRequest")
    request.field.add(name="message", number=1, label=1, type=9)
    mission = file.message_type.add(name="ProfileMessageMission")
    for name, number, kind in (("missionId", 1, 9), ("currentThreshold", 2, 3),
                               ("progress", 3, 3), ("statusType", 4, 5), ("lastUpdateTime", 5, 3)):
        mission.field.add(name=name, number=number, label=1, type=kind)
    for name in ("UserGetResponse", "UpdatedData"):
        next(message for message in file.message_type if message.name == name).field.add(
            name="missions", number=100, label=3, type=11, type_name=".api.ProfileMessageMission")
    service = next(service for service in file.service if service.name == "Profile")
    service.method.add(name="UpdateMessage", input_type=".api.ProfileMessageRequest",
                       output_type=".api.ActionResponse")
    path.write_bytes(descriptors.SerializeToString())
    return Schema.from_descriptor_set(path)


@pytest.fixture(scope="module", params=("small", "client-6.1.1"))
def schema(request, tmp_path_factory):
    if request.param == "small":
        return small_schema(tmp_path_factory.mktemp("profile-message-schema") / "schema.pb")
    source = Path(__file__).resolve().parents[1] / "data/protocol/idolypride-6.1.1.pb"
    if not source.is_file():
        pytest.skip("Optional recovered 6.1.1 descriptor is unavailable")
    return Schema.from_descriptor_set(source)


@pytest.fixture
def messages(game):
    names, state = game[:2]
    def prepare(raw):
        value = names.schema.response_type(USER).FromString(raw)
        value.profile.message = "Original introduction"
        value.profile.birthMonth, value.profile.birthDay, value.profile.layoutType = 2, 29, 2
        value.profile.MergeFromString(UNKNOWN)
        value.missions.add(missionId="ms-normal-profile_setting", currentThreshold=0,
                           progress=0, statusType=1, lastUpdateTime=123456)
        return value.SerializeToString()
    state.mutate_snapshot("player", names.schema.fingerprint, prepare)
    return ProfileMessages(names.schema, state, "player")


def snapshot(game):
    return game[0].schema.response_type(USER).FromString(game[1].snapshot("player")[0])


def unrelated(state):
    with state.connect() as connection:
        names = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        tables = {name: [tuple(row) for row in connection.execute('SELECT * FROM "' + name + '" ORDER BY 1')]
                  for name in names if name != "snapshots"}
    return tables, state.snapshot("other")


def call(messages, value):
    raw = messages.schema.request_type(PATH)(message=value).SerializeToString()
    return messages.schema.response_type(PATH).FromString(messages.handle(PATH, raw))


@pytest.mark.parametrize("value", ("A", "あ" * 60, "x" * 60, "😀" * 30, "e\u0301" * 30,
                                   "  Introduction  ", "a\nb", "a\rb", "a\r\nb"))
def test_exact_text_and_full_profile_delta_persist_without_other_changes(game, messages, value):
    state = game[1]
    expected = snapshot(game)
    expected.profile.message = value
    kept = unrelated(state)
    result = call(messages, value)
    assert state.snapshot("player")[0] == expected.SerializeToString()
    assert result.commonResponse.updatedData.profile == expected.profile
    assert {field.name for field, _ in result.commonResponse.updatedData.ListFields()} == {"profile"}
    assert not result.commonResponse.deletedData.ListFields()
    assert unrelated(state) == kept
    assert UNKNOWN in result.commonResponse.updatedData.profile.SerializeToString()
    before_retry = dump(state)
    assert call(messages, value) == result
    restarted = State(state.path)
    replay = ProfileMessages(messages.schema, restarted, "player")
    assert replay.handle(PATH, messages.schema.request_type(PATH)(message=value).SerializeToString()) == result.SerializeToString()
    assert dump(restarted) == before_retry
    assert restarted.authenticated(game[2], "player") and restarted.authenticated(game[3], "other")


@pytest.mark.parametrize("value", ("", " ", "\u3000\u00a0", "\r\n", "\t", "a\tb",
                                   "x" * 61, "😀" * 31, "e\u0301" * 31))
def test_local_input_policy_rejects_without_partial_writes(game, messages, value):
    before = dump(game[1])
    with pytest.raises(RpcFailure) as error:
        call(messages, value)
    assert error.value.code == RpcCode.INVALID_ARGUMENT
    assert dump(game[1]) == before


@pytest.mark.parametrize("raw", (b"\x0a\x80", b"\x0a\x01\xff"))
def test_malformed_protobuf_or_utf8_does_not_change_state(game, messages, raw):
    before = dump(game[1])
    with pytest.raises(RpcFailure) as error:
        messages.handle(PATH, raw)
    assert error.value.code == RpcCode.INVALID_ARGUMENT
    assert dump(game[1]) == before


@pytest.mark.parametrize("bad_state", ("missing", "different-schema", "malformed", "no-profile"))
def test_missing_or_invalid_profile_is_not_created_or_partially_saved(game, messages, bad_state):
    state = game[1]
    with state.connect() as connection:
        if bad_state == "missing":
            connection.execute("DELETE FROM snapshots WHERE profile='player'")
        else:
            value = snapshot(game)
            if bad_state == "no-profile":
                value.ClearField("profile")
            raw = b"\x0a\x80" if bad_state == "malformed" else value.SerializeToString()
            fingerprint = "different" if bad_state == "different-schema" else messages.schema.fingerprint
            connection.execute("UPDATE snapshots SET response=?,schema_sha256=? WHERE profile='player'", (raw, fingerprint))
    before = dump(state)
    with pytest.raises(RpcFailure) as error:
        call(messages, "Updated introduction")
    assert error.value.code == RpcCode.FAILED_PRECONDITION
    assert dump(state) == before


def test_concurrent_profile_field_updates_are_not_lost(game, messages):
    state = game[1]
    kept = unrelated(state)
    def update(index):
        if index % 2:
            call(messages, "Introduction " + str(index))
        else:
            def append(raw):
                value = messages.schema.response_type(USER).FromString(raw)
                value.profile.favoriteCharacterIds.append("character-" + str(index))
                return value.SerializeToString()
            state.mutate_snapshot("player", messages.schema.fingerprint, append)
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(update, range(20)))
    value = snapshot(game)
    assert set(value.profile.favoriteCharacterIds) == {"kept-character", *("character-" + str(i) for i in range(0, 20, 2))}
    assert value.profile.message in {"Introduction " + str(i) for i in range(1, 20, 2)}
    assert unrelated(state) == kept


def test_other_profile_routes_are_not_claimed(game, messages):
    before = dump(game[1])
    assert messages.handle("/api.Profile/UpdateName", b"") is None
    assert messages.handle("/api.Profile/UpdateBirthday", b"") is None
    assert dump(game[1]) == before
