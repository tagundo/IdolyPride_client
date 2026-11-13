"""Manager name mutations retain unrelated game state and match the input ABI."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

from google.protobuf import descriptor_pb2
import pytest

from idoly_local.profile_names import ProfileNames
from idoly_local.rpc import RpcCode, RpcFailure
from idoly_local.schema import Schema
from idoly_local.state import State
from test_gameplay import synthetic_schema


PATH = "/api.Profile/UpdateName"
USER = "/api.User/Get"
UNKNOWN = b"\x80\x4b\x7b"


def small_schema(path):
    synthetic_schema(path)
    descriptors = descriptor_pb2.FileDescriptorSet.FromString(path.read_bytes())
    file = descriptors.file[0]
    # Service names and message names share one protobuf package namespace.
    for message in file.message_type:
        if message.name == "Profile":
            message.name = "SavedProfile"
        for field in message.field:
            if field.type_name == ".api.Profile":
                field.type_name = ".api.SavedProfile"
    request = file.message_type.add(name="ProfileNameRequest")
    request.field.add(name="name", number=1, label=1, type=9)
    file.service.add(name="Profile").method.add(name="UpdateName",
        input_type=".api.ProfileNameRequest", output_type=".api.ActionResponse")
    path.write_bytes(descriptors.SerializeToString())
    return Schema.from_descriptor_set(path)


@pytest.fixture(scope="module", params=("small", "client-6.1.1"))
def schema(request, tmp_path_factory):
    if request.param == "small":
        return small_schema(tmp_path_factory.mktemp("profile-name-schema") / "schema.pb")
    source = Path(__file__).resolve().parents[1] / "data/protocol/idolypride-6.1.1.pb"
    if not source.is_file():
        pytest.skip("Optional recovered 6.1.1 descriptor is unavailable")
    return Schema.from_descriptor_set(source)


@pytest.fixture
def game(schema, tmp_path):
    state = State(tmp_path / "state.db")
    identity = state.ensure_profile("player")
    snapshot = schema.response_type(USER)()
    snapshot.user.name = "Old manager"
    snapshot.user.managerLevel, snapshot.user.lastLoginTime = 7, 123456789
    snapshot.user.MergeFromString(UNKNOWN)
    snapshot.userPublic.serverUserId = identity["server_id"]
    snapshot.userPublic.publicUserId = identity["public_id"]
    snapshot.items.add(itemId="kept-item", amount=123)
    snapshot.cards.add(cardId="kept-card", totalExp=12345)
    snapshot.profile.favoriteCharacterIds.append("kept-character")
    snapshot.balance.MergeFromString(UNKNOWN)
    snapshot.MergeFromString(UNKNOWN)
    state.save_snapshot("player", snapshot.SerializeToString(), schema.fingerprint, starter_version=4)
    state.mutate_snapshot("player", schema.fingerprint, lambda raw: raw, setting_info=b"settings\x00")
    state.mutate_lesson_snapshot("player", schema.fingerprint, lambda raw, _: (raw, b"lesson clock\x00"))
    state.save_snapshot("other", snapshot.SerializeToString(), schema.fingerprint)
    token, _ = state.login("player")
    other_token, _ = state.login("other")
    return ProfileNames(schema, state, "player"), state, token, other_token


def snapshot(game):
    return game[0].schema.response_type(USER).FromString(game[1].snapshot("player")[0])


def dump(state):
    with state.connect() as connection:
        return tuple(connection.iterdump())


def protected(state):
    with state.connect() as connection:
        tables = {name: [tuple(row) for row in connection.execute('SELECT * FROM "' + name + '" ORDER BY 1')]
                  for name in ("profiles", "sessions", "profile_settings", "starter_profiles", "profile_lesson_progress")}
    return tables, state.snapshot("other")


def call(game, name):
    provider = game[0]
    raw = provider.schema.request_type(PATH)(name=name).SerializeToString()
    return provider.schema.response_type(PATH).FromString(provider.handle(PATH, raw))


@pytest.mark.parametrize("name", ("Manager", "あいうえおかきくけこ", "😀" * 5, "e\u0301" * 5, " A B "))
def test_exact_name_and_authoritative_user_persist_without_other_changes(game, name):
    provider, state = game[:2]
    expected = snapshot(game)
    expected.user.name = name
    kept = protected(state)
    result = call(game, name)
    assert state.snapshot("player")[0] == expected.SerializeToString()
    assert result.commonResponse.updatedData.user == expected.user
    assert {field.name for field, _ in result.commonResponse.updatedData.ListFields()} == {"user"}
    assert not result.commonResponse.deletedData.ListFields()
    assert protected(state) == kept
    before_retry = dump(state)
    assert call(game, name) == result
    restarted = State(state.path)
    replay = ProfileNames(provider.schema, restarted, "player")
    assert replay.handle(PATH, provider.schema.request_type(PATH)(name=name).SerializeToString()) == result.SerializeToString()
    assert dump(restarted) == before_retry
    assert restarted.authenticated(game[2], "player") and restarted.authenticated(game[3], "other")


def test_identical_name_ack_preserves_noncanonical_snapshot_without_sql_update(game, monkeypatch):
    provider, state = game[:2]
    call(game, "Manager")
    original = UNKNOWN + state.snapshot("player")[0]
    with state.connect() as connection:
        connection.execute("UPDATE snapshots SET response=? WHERE profile='player'", (original,))
    expected = provider.schema.response_type(USER).FromString(original)
    assert expected.SerializeToString() != original
    before, kept = dump(state), protected(state)
    statements = []
    connect = state.connect

    @contextmanager
    def traced_connect():
        with connect() as connection:
            connection.set_trace_callback(statements.append)
            yield connection

    monkeypatch.setattr(state, "connect", traced_connect)
    for _ in range(2):
        result = call(game, "Manager")
        assert result.commonResponse.updatedData.user == expected.user
        assert UNKNOWN in result.commonResponse.updatedData.user.SerializeToString()
        assert state.snapshot("player")[0] == original
        assert dump(state) == before
    assert not any(sql.upper().startswith("UPDATE SNAPSHOTS") for sql in statements)

    # A real change still commits its complete post-image and current ACK.
    changed = call(game, "New name")
    expected.user.name = "New name"
    assert changed.commonResponse.updatedData.user == expected.user
    assert state.snapshot("player")[0] == expected.SerializeToString()
    assert sum(sql.upper().startswith("UPDATE SNAPSHOTS") for sql in statements) == 1
    assert protected(state) == kept


@pytest.mark.parametrize("name", ("", " ", "\u3000\u00a0", "x" * 11, "😀" * 6,
                                  "e\u0301" * 6, "a\nb", "a\rb", "a\tb"))
def test_rejected_names_leave_entire_database_unchanged(game, name):
    before = dump(game[1])
    with pytest.raises(RpcFailure) as error:
        call(game, name)
    assert error.value.code == RpcCode.INVALID_ARGUMENT
    assert dump(game[1]) == before


@pytest.mark.parametrize("raw", (b"\x0a\x80", b"\x0a\x01\xff"))
def test_malformed_protobuf_or_utf8_is_invalid_without_writes(game, raw):
    before = dump(game[1])
    with pytest.raises(RpcFailure) as error:
        game[0].handle(PATH, raw)
    assert error.value.code == RpcCode.INVALID_ARGUMENT
    assert dump(game[1]) == before


@pytest.mark.parametrize("bad_state", ("missing", "different-schema", "malformed", "no-user"))
def test_missing_or_incompatible_snapshot_is_rejected_without_partial_writes(game, bad_state):
    provider, state = game[:2]
    if bad_state == "missing":
        with state.connect() as connection:
            connection.execute("DELETE FROM snapshots WHERE profile='player'")
    else:
        raw = (b"\x0a\x80" if bad_state == "malformed" else
               provider.schema.response_type(USER)().SerializeToString() if bad_state == "no-user" else
               state.snapshot("player")[0])
        fingerprint = "different" if bad_state == "different-schema" else provider.schema.fingerprint
        with state.connect() as connection:
            connection.execute("UPDATE snapshots SET response=?,schema_sha256=? WHERE profile='player'", (raw, fingerprint))
    before = dump(state)
    with pytest.raises(RpcFailure) as error:
        call(game, "New name")
    assert error.value.code == RpcCode.FAILED_PRECONDITION
    assert dump(state) == before


def test_name_changes_do_not_overwrite_concurrent_unrelated_updates(game):
    provider, state = game[:2]
    kept = protected(state)
    def update(index):
        if index % 2:
            call(game, "Name" + str(index))
        else:
            def increment(raw):
                value = provider.schema.response_type(USER).FromString(raw)
                value.user.lastLoginTime += 1
                return value.SerializeToString()
            state.mutate_snapshot("player", provider.schema.fingerprint, increment)
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(update, range(20)))
    value = snapshot(game)
    assert value.user.lastLoginTime == 123456799
    assert value.user.name in {"Name" + str(i) for i in range(1, 20, 2)}
    assert protected(state) == kept


def test_unrelated_route_is_not_claimed(game):
    before = dump(game[1])
    assert game[0].handle("/api.Profile/UpdateMessage", b"") is None
    assert dump(game[1]) == before
