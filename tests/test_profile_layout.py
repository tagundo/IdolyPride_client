"""Profile appearance updates affect only existing local preferences."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from idoly_local.profile_layout import ProfileLayout
from idoly_local.rpc import RpcCode, RpcFailure
from idoly_local.schema import Schema
from idoly_local.state import State


PATH, USER = "/api.Profile/UpdateLayout", "/api.User/Get"
FIELDS = ("layoutType", "informationType", "colorType")
UNKNOWN = b"\x80\x4b\x7b"


@pytest.fixture(scope="module")
def schema():
    source = Path(__file__).resolve().parents[1] / "data/protocol/idolypride-6.1.1.pb"
    if not source.is_file():
        pytest.skip("Original 6.1.1 schema is unavailable")
    return Schema.from_descriptor_set(source)


@pytest.fixture
def game(schema, tmp_path):
    state = State(tmp_path / "state.db")
    for name in ("player", "other"):
        identity = state.ensure_profile(name)
        value = schema.response_type(USER)()
        value.user.name = name
        value.user.managerLevel = 15
        value.userPublic.serverUserId = identity["server_id"]
        value.userPublic.publicUserId = identity["public_id"]
        value.profile.layoutType, value.profile.informationType, value.profile.colorType = (1, 2, 3)
        value.profile.favoriteCardId = "kept-card-" + name
        value.profile.favoritePhotoId = "kept-photo-" + name
        value.profile.message = "kept introduction"
        value.profile.MergeFromString(UNKNOWN)
        value.items.add(itemId="kept-item", amount=11).MergeFromString(UNKNOWN)
        value.photos.add(photoId="kept-photo-" + name, rarity=5, level=20).MergeFromString(UNKNOWN)
        value.missions.add(missionId="kept-mission", progress=17)
        value.MergeFromString(UNKNOWN)
        state.save_snapshot(name, value.SerializeToString(), schema.fingerprint)
        state.mutate_snapshot(name, schema.fingerprint, lambda raw: raw, setting_info=b"kept settings\x00")
    token, _ = state.login("player")
    other_token, _ = state.login("other")
    return SimpleNamespace(schema=schema, state=state, token=token, other_token=other_token,
        provider=ProfileLayout(schema, state, "player"))


def dump(state):
    with state.connect() as db:
        return tuple(db.iterdump())


def protected(state):
    with state.connect() as db:
        tables = tuple(row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"))
        result = {}
        for table in tables:
            rows = db.execute("SELECT * FROM " + table + " ORDER BY rowid").fetchall()
            result[table] = tuple(tuple(row) for row in rows if table != "snapshots" or row[0] != "player")
        return result


def snapshot(game):
    return game.schema.response_type(USER).FromString(game.state.snapshot("player")[0])


def call(game, choices):
    raw = game.schema.request_type(PATH)(**dict(zip(FIELDS, choices))).SerializeToString()
    return game.schema.response_type(PATH).FromString(game.provider.handle(PATH, raw))


def test_original_schema_exposes_exactly_four_defined_choices_per_preference(schema):
    request = schema.request_type(PATH)()
    assert [field.name for field in request.DESCRIPTOR.fields] == list(FIELDS)
    for field in request.DESCRIPTOR.fields:
        assert set(field.enum_type.values_by_number) == {0, 1, 2, 3, 4}


@pytest.mark.parametrize("choices", ((1, 2, 3), (4, 3, 2), (2, 4, 1)))
def test_native_choices_update_only_profile_and_survive_restart(game, choices):
    expected = snapshot(game)
    for name, value in zip(FIELDS, choices):
        setattr(expected.profile, name, value)
    kept = protected(game.state)
    result = call(game, choices)
    assert game.state.snapshot("player")[0] == expected.SerializeToString()
    assert result.commonResponse.updatedData.profile == expected.profile
    assert {field.name for field, _ in result.commonResponse.updatedData.ListFields()} == {"profile"}
    assert not result.commonResponse.deletedData.ListFields()
    assert UNKNOWN in result.commonResponse.updatedData.profile.SerializeToString()
    assert protected(game.state) == kept
    before_retry = dump(game.state)
    assert call(game, choices) == result and dump(game.state) == before_retry
    restarted = State(game.state.path)
    provider = ProfileLayout(game.schema, restarted, "player")
    request = game.schema.request_type(PATH)(**dict(zip(FIELDS, choices))).SerializeToString()
    assert provider.handle(PATH, request) == result.SerializeToString()
    assert dump(restarted) == before_retry
    assert restarted.authenticated(game.token, "player")
    assert restarted.authenticated(game.other_token, "other")


def test_identical_retry_keeps_noncanonical_original_wire_order(game):
    original = UNKNOWN + game.state.snapshot("player")[0]
    with game.state.connect() as db:
        db.execute("UPDATE snapshots SET response=? WHERE profile='player'", (original,))
    assert snapshot(game).SerializeToString() != original
    before = dump(game.state)
    call(game, (1, 2, 3))
    assert game.state.snapshot("player")[0] == original and dump(game.state) == before


@pytest.mark.parametrize("field,bad", (("layoutType", 0), ("informationType", 5),
    ("colorType", -1), ("layoutType", 2147483647)))
def test_undefined_or_unknown_enum_rolls_back_entire_request(game, field, bad):
    values = dict(zip(FIELDS, (4, 4, 4)))
    values[field] = bad
    raw = game.schema.request_type(PATH)(**values).SerializeToString()
    before = dump(game.state)
    with pytest.raises(RpcFailure) as error:
        game.provider.handle(PATH, raw)
    assert error.value.code == RpcCode.INVALID_ARGUMENT and dump(game.state) == before


@pytest.mark.parametrize("raw", (b"", b"\x08\x80", b"\x0a\x80", b"\x08\x01\x10\x02"))
def test_malformed_or_incomplete_request_never_writes(game, raw):
    before = dump(game.state)
    with pytest.raises(RpcFailure) as error:
        game.provider.handle(PATH, raw)
    assert error.value.code == RpcCode.INVALID_ARGUMENT and dump(game.state) == before


@pytest.mark.parametrize("problem", ("missing", "wrong-schema", "malformed", "no-user", "no-profile"))
def test_unavailable_or_incomplete_snapshot_is_never_fabricated(game, problem):
    with game.state.connect() as db:
        if problem == "missing":
            db.execute("DELETE FROM snapshots WHERE profile='player'")
        elif problem == "wrong-schema":
            db.execute("UPDATE snapshots SET schema_sha256='foreign-schema' WHERE profile='player'")
        else:
            value = snapshot(game)
            if problem.startswith("no-"):
                value.ClearField(problem[3:])
            raw = b"\x0a\x80" if problem == "malformed" else value.SerializeToString()
            db.execute("UPDATE snapshots SET response=? WHERE profile='player'", (raw,))
    before = dump(game.state)
    with pytest.raises(RpcFailure) as error:
        call(game, (4, 3, 2))
    assert error.value.code == RpcCode.FAILED_PRECONDITION and dump(game.state) == before


def test_unsupported_routes_and_schema_leave_all_profiles_untouched(game):
    before = dump(game.state)
    assert game.provider.handle("/api.Profile/UpdateName", b"not protobuf") is None
    without_route = SimpleNamespace(methods={})
    assert ProfileLayout(without_route, game.state, "player").handle(PATH, b"not protobuf") is None
    assert dump(game.state) == before


def test_missing_local_profile_cannot_modify_another_profiles_snapshot(game):
    raw = game.schema.request_type(PATH)(layoutType=4, informationType=4, colorType=4).SerializeToString()
    before = dump(game.state)
    with pytest.raises(RpcFailure) as error:
        ProfileLayout(game.schema, game.state, "foreign").handle(PATH, raw)
    assert error.value.code == RpcCode.FAILED_PRECONDITION and dump(game.state) == before


def test_atomic_callback_observes_latest_unrelated_mutation(game):
    def name_update():
        def update(raw):
            value = game.schema.response_type(USER).FromString(raw)
            value.user.name = "concurrent name"
            return value.SerializeToString()
        game.state.mutate_snapshot("player", game.schema.fingerprint, update)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = (pool.submit(call, game, (4, 3, 2)), pool.submit(name_update))
        for future in futures:
            future.result()
    value = snapshot(game)
    assert value.user.name == "concurrent name"
    assert tuple(getattr(value.profile, name) for name in FIELDS) == (4, 3, 2)
