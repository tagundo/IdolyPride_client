"""Favorite selections retain order, ownership and unrelated persistent state."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json

from google.protobuf import descriptor_pb2
import pytest

from idoly_local.profile_favorites import ProfileFavorites
from idoly_local.rpc import RpcCode, RpcFailure
from idoly_local.schema import Schema
from idoly_local.state import State
from test_profile_names import USER, UNKNOWN, dump, game, protected, small_schema as name_schema


PATH = "/api.Profile/UpdateFavoriteCharacters"


def small_schema(path):
    name_schema(path)
    descriptors = descriptor_pb2.FileDescriptorSet.FromString(path.read_bytes())
    file = descriptors.file[0]
    mission = file.message_type.add(name="FavoriteUnrelatedMission")
    mission.field.add(name="missionId", number=1, label=1, type=9)
    mission.field.add(name="progress", number=3, label=1, type=3)
    for name in ("UserGetResponse", "UpdatedData"):
        next(message for message in file.message_type if message.name == name).field.add(
            name="missions", number=100, label=3, type=11, type_name=".api.FavoriteUnrelatedMission")
    request = file.message_type.add(name="FavoriteCharactersRequest")
    request.field.add(name="favoriteCharacterIds", number=1, label=3, type=9)
    service = next(service for service in file.service if service.name == "Profile")
    service.method.add(name="UpdateFavoriteCharacters", input_type=".api.FavoriteCharactersRequest",
                       output_type=".api.ActionResponse")
    path.write_bytes(descriptors.SerializeToString())
    return Schema.from_descriptor_set(path)


@pytest.fixture(scope="module", params=("small", "client-6.1.1"))
def schema(request, tmp_path_factory):
    if request.param == "small":
        return small_schema(tmp_path_factory.mktemp("profile-favorites-schema") / "schema.pb")
    source = Path(__file__).resolve().parents[1] / "data/protocol/idolypride-6.1.1.pb"
    if not source.is_file():
        pytest.skip("Optional recovered 6.1.1 descriptor is unavailable")
    return Schema.from_descriptor_set(source)


@pytest.fixture
def favorites(game, tmp_path):
    provider, state = game[:2]
    master = tmp_path / "master"
    master.mkdir()
    (master / "Character.json").write_text(json.dumps([{"id": key} for key in
        ("character-a", "character-b", "character-c", "not-owned")]))
    def prepare(raw):
        value = provider.schema.response_type(USER).FromString(raw)
        value.profile.MergeFromString(UNKNOWN)
        for key in ("character-a", "character-b", "character-c"):
            value.characters.add(characterId=key).MergeFromString(UNKNOWN)
        value.missions.add(missionId="ms-unrelated", progress=123).MergeFromString(UNKNOWN)
        return value.SerializeToString()
    state.mutate_snapshot("player", provider.schema.fingerprint, prepare)
    return ProfileFavorites(provider.schema, state, "player", master)


def snapshot(game):
    return game[0].schema.response_type(USER).FromString(game[1].snapshot("player")[0])


def call(favorites, ids):
    raw = favorites.schema.request_type(PATH)(favoriteCharacterIds=ids).SerializeToString()
    return favorites.schema.response_type(PATH).FromString(favorites.handle(PATH, raw))


@pytest.mark.parametrize("ids", ((), ("character-a",), ("character-c", "character-a"),
                                ("character-c", "character-b", "character-a")))
def test_ordered_selection_and_clearing_change_only_profile_favorites(game, favorites, ids):
    state = game[1]
    expected = snapshot(game)
    del expected.profile.favoriteCharacterIds[:]
    expected.profile.favoriteCharacterIds.extend(ids)
    kept = protected(state)
    result = call(favorites, ids)
    assert state.snapshot("player")[0] == expected.SerializeToString()
    assert tuple(result.commonResponse.updatedData.profile.favoriteCharacterIds) == ids
    assert result.commonResponse.updatedData.profile == expected.profile
    assert {field.name for field, _ in result.commonResponse.updatedData.ListFields()} == {"profile"}
    assert not result.commonResponse.deletedData.ListFields()
    assert UNKNOWN in result.commonResponse.updatedData.profile.SerializeToString()
    assert protected(state) == kept
    before_retry = dump(state)
    assert call(favorites, ids) == result
    restarted = State(state.path)
    replay = ProfileFavorites(favorites.schema, restarted, "player", favorites.catalog.directory)
    raw = favorites.schema.request_type(PATH)(favoriteCharacterIds=ids).SerializeToString()
    assert replay.handle(PATH, raw) == result.SerializeToString()
    assert dump(restarted) == before_retry
    assert restarted.authenticated(game[2], "player") and restarted.authenticated(game[3], "other")


def test_reordering_is_saved_instead_of_treated_as_a_set(game, favorites):
    call(favorites, ("character-a", "character-b"))
    call(favorites, ("character-b", "character-a"))
    assert list(snapshot(game).profile.favoriteCharacterIds) == ["character-b", "character-a"]


def test_identical_retry_preserves_even_noncanonical_original_wire_order(game, favorites):
    call(favorites, ["character-a"])
    state = game[1]
    original = UNKNOWN + state.snapshot("player")[0]
    with state.connect() as connection:
        connection.execute("UPDATE snapshots SET response=? WHERE profile='player'", (original,))
    # A normal reserialization would move this leading unknown field to the
    # unknown-field tail. An identical selection must keep the original bytes.
    assert snapshot(game).SerializeToString() != original
    call(favorites, ["character-a"])
    assert state.snapshot("player")[0] == original


@pytest.mark.parametrize("ids,code", (([""], RpcCode.INVALID_ARGUMENT),
    (["character-a", "character-a"], RpcCode.INVALID_ARGUMENT),
    (["character-a", "character-b", "character-c", "not-owned"], RpcCode.INVALID_ARGUMENT),
    (["unknown"], RpcCode.INVALID_ARGUMENT), (["not-owned"], RpcCode.PERMISSION_DENIED)))
def test_invalid_or_unowned_selection_leaves_entire_database_unchanged(game, favorites, ids, code):
    before = dump(game[1])
    with pytest.raises(RpcFailure) as error:
        call(favorites, ids)
    assert error.value.code == code
    assert dump(game[1]) == before


@pytest.mark.parametrize("raw", (b"\x0a\x80", b"\x0a\x01\xff"))
def test_malformed_protobuf_or_utf8_is_rejected(game, favorites, raw):
    before = dump(game[1])
    with pytest.raises(RpcFailure) as error:
        favorites.handle(PATH, raw)
    assert error.value.code == RpcCode.INVALID_ARGUMENT
    assert dump(game[1]) == before


@pytest.mark.parametrize("problem", ("missing", "wrong-schema", "malformed", "no-profile", "no-user",
                                    "empty-owned-id", "duplicate-owned-id", "missing-master", "duplicate-master"))
def test_unusable_state_or_catalog_is_not_repaired_or_partially_saved(game, favorites, problem):
    provider, state = game[:2]
    with state.connect() as connection:
        if problem == "missing":
            connection.execute("DELETE FROM snapshots WHERE profile='player'")
        elif problem == "wrong-schema":
            connection.execute("UPDATE snapshots SET schema_sha256='other' WHERE profile='player'")
        elif problem in ("malformed", "no-profile", "no-user", "empty-owned-id", "duplicate-owned-id"):
            value = snapshot(game)
            if problem.startswith("no-"):
                value.ClearField(problem[3:])
            elif problem in ("empty-owned-id", "duplicate-owned-id"):
                value.characters.add(characterId="" if problem == "empty-owned-id" else "character-a")
            raw = b"\x0a\x80" if problem == "malformed" else value.SerializeToString()
            connection.execute("UPDATE snapshots SET response=? WHERE profile='player'", (raw,))
    if problem == "missing-master":
        (favorites.catalog.directory / "Character.json").unlink()
    elif problem == "duplicate-master":
        (favorites.catalog.directory / "Character.json").write_text('[{"id":"character-a"},{"id":"character-a"}]')
    before = dump(state)
    with pytest.raises(RpcFailure) as error:
        call(favorites, ["character-a"])
    assert error.value.code == RpcCode.FAILED_PRECONDITION
    assert dump(state) == before


def test_clearing_stale_imported_selection_needs_no_master_or_inventory(game, favorites):
    (favorites.catalog.directory / "Character.json").unlink()
    def remove_owned(raw):
        value = favorites.schema.response_type(USER).FromString(raw)
        del value.characters[:]
        return value.SerializeToString()
    game[1].mutate_snapshot("player", favorites.schema.fingerprint, remove_owned)
    assert not call(favorites, []).commonResponse.updatedData.profile.favoriteCharacterIds
    assert not snapshot(game).profile.favoriteCharacterIds


def test_ownership_of_another_local_profile_never_authorizes_selection(game, favorites):
    state = game[1]
    def prepare_other(raw):
        value = favorites.schema.response_type(USER).FromString(raw)
        value.characters.add(characterId="not-owned")
        return value.SerializeToString()
    state.mutate_snapshot("other", favorites.schema.fingerprint, prepare_other)
    before = dump(state)
    with pytest.raises(RpcFailure) as error:
        call(favorites, ["not-owned"])
    assert error.value.code == RpcCode.PERMISSION_DENIED
    assert dump(state) == before


def test_nonempty_selection_does_not_create_missing_owned_inventory(game, favorites):
    def remove_owned(raw):
        value = favorites.schema.response_type(USER).FromString(raw)
        del value.characters[:]
        return value.SerializeToString()
    game[1].mutate_snapshot("player", favorites.schema.fingerprint, remove_owned)
    before = dump(game[1])
    with pytest.raises(RpcFailure) as error:
        call(favorites, ["character-a"])
    assert error.value.code == RpcCode.PERMISSION_DENIED
    assert dump(game[1]) == before


def test_concurrent_name_updates_and_selections_do_not_overwrite_each_other(game, favorites):
    names, state = game[:2]
    def update(index):
        if index % 2:
            call(favorites, ["character-a", "character-b"])
        else:
            raw = names.schema.request_type("/api.Profile/UpdateName")(name="Manager" + str(index)).SerializeToString()
            names.handle("/api.Profile/UpdateName", raw)
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(update, range(20)))
    value = snapshot(game)
    assert value.user.name in {"Manager" + str(index) for index in range(0, 20, 2)}
    assert list(value.profile.favoriteCharacterIds) == ["character-a", "character-b"]


def test_other_routes_are_not_claimed(game, favorites):
    before = dump(game[1])
    assert favorites.handle("/api.Profile/UpdateBackground", b"") is None
    assert favorites.handle("/api.Profile/UpdateName", b"") is None
    assert dump(game[1]) == before
