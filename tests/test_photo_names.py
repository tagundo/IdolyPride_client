"""Owned photo rename keeps its native contract and unrelated account state."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from idoly_local.photo_names import PhotoNames
from idoly_local.rpc import RpcCode, RpcFailure
from idoly_local.schema import Schema
from idoly_local.state import State


PATH, USER = "/api.Photo/Update", "/api.User/Get"
UNKNOWN = b"\x80\x4b\x7b"


@pytest.fixture(scope="module")
def schema():
    path = Path(__file__).resolve().parents[1] / "data/protocol/idolypride-6.1.1.pb"
    if not path.is_file():
        pytest.skip("Original 6.1.1 descriptor unavailable")
    return Schema.from_descriptor_set(path)


@pytest.fixture
def game(schema, tmp_path):
    state = State(tmp_path / "state.db")
    identity = state.ensure_profile("player")
    snapshot = schema.response_type(USER)()
    snapshot.user.name, snapshot.user.lastLoginTime = "Manager", 123456789
    snapshot.userPublic.serverUserId = identity["server_id"]
    snapshot.userPublic.publicUserId = identity["public_id"]
    snapshot.profile.favoritePhotoId = "owned-photo"
    photo = snapshot.photos.add(photoId="owned-photo", name="Original", rarity=4, level=30,
        locked=True, isDreamBase=True, photoRecipeId="recipe", assetId="private-image")
    photo.characterIds.extend(["character-a", "character-b"])
    photo.abilities.add(photoAbilityId="ability", effectValue=123)
    photo.MergeFromString(UNKNOWN)
    snapshot.photos.add(photoId="another-owned", name="Unchanged", rarity=1)
    snapshot.items.add(itemId="manual", amount=4)
    snapshot.cards.add(cardId="card", totalExp=5678)
    snapshot.MergeFromString(UNKNOWN)
    state.save_snapshot("player", snapshot.SerializeToString(), schema.fingerprint, starter_version=4)
    state.mutate_snapshot("player", schema.fingerprint, lambda raw: raw, setting_info=b"settings\x00")
    state.mutate_lesson_snapshot("player", schema.fingerprint, lambda raw, _: (raw, b"lesson clock\x00"))
    other = schema.response_type(USER)()
    other.user.name = "Another manager"
    other.photos.add(photoId="other-profile-photo", name="Foreign")
    state.save_snapshot("other", other.SerializeToString(), schema.fingerprint)
    token, _ = state.login("player")
    other_token, _ = state.login("other")
    return PhotoNames(schema, state, "player"), state, token, other_token


def snapshot(game):
    return game[0].schema.response_type(USER).FromString(game[1].snapshot("player")[0])


def dump(state):
    with state.connect() as db:
        return tuple(db.iterdump())


def protected(state):
    with state.connect() as db:
        values = {name: [tuple(row) for row in db.execute('SELECT * FROM "' + name + '" ORDER BY 1')]
                  for name in ("profiles", "sessions", "profile_settings", "starter_profiles", "profile_lesson_progress")}
    return values, state.snapshot("other")


def call(game, name, photo_id="owned-photo"):
    provider = game[0]
    request = provider.schema.request_type(PATH)(photoId=photo_id, name=name).SerializeToString()
    return provider.schema.response_type(PATH).FromString(provider.handle(PATH, request))


@pytest.mark.parametrize("name", ("あいうえおかきくけこさし", "한국어写真", " Photo "))
def test_only_owned_name_and_full_photo_delta_persist_without_other_changes(game, name):
    provider, state = game[:2]
    expected = snapshot(game)
    expected.photos[0].name = name
    kept = protected(state)
    result = call(game, name)
    assert state.snapshot("player")[0] == expected.SerializeToString()
    assert result.commonResponse.updatedData.photos == [expected.photos[0]]
    assert {field.name for field, _ in result.commonResponse.updatedData.ListFields()} == {"photos"}
    assert not result.commonResponse.deletedData.ListFields()
    assert UNKNOWN in result.commonResponse.updatedData.photos[0].SerializeToString()
    assert protected(state) == kept
    assert snapshot(game).photos[0].isDreamBase and snapshot(game).photos[0].locked
    assert snapshot(game).profile.favoritePhotoId == "owned-photo"
    before_retry = dump(state)
    assert call(game, name) == result and dump(state) == before_retry
    restarted = State(state.path)
    replay = PhotoNames(provider.schema, restarted, "player")
    request = provider.schema.request_type(PATH)(photoId="owned-photo", name=name).SerializeToString()
    assert replay.handle(PATH, request) == result.SerializeToString()
    assert dump(restarted) == before_retry
    assert restarted.authenticated(game[2], "player") and restarted.authenticated(game[3], "other")


@pytest.mark.parametrize("name", ("", " ", "\u3000\u00a0", "x" * 13, "e\u0301" * 7,
    "😀", "a\nb", "a\rb", "a\tb"))
def test_native_invalid_names_do_not_change_database(game, name):
    before = dump(game[1])
    with pytest.raises(RpcFailure) as error: call(game, name)
    assert error.value.code == RpcCode.INVALID_ARGUMENT and dump(game[1]) == before


@pytest.mark.parametrize("char", ("\u0301", "\u093e", "\u20dd", "\u00a9", "\u266f",
                                  "\u259f", "\u2600", "\u26ff", "\u2700"))
def test_native_combining_symbol_and_miscellaneous_symbol_filters_reject_without_writes(game, char):
    # Mn/Mc/Me/So are rejected by category. U+266F is Sm and is rejected
    # separately by the original regex's inclusive U+2600..U+26FF range.
    before = dump(game[1])
    with pytest.raises(RpcFailure) as error:
        call(game, "a" + char)
    assert error.value.code == RpcCode.INVALID_ARGUMENT and dump(game[1]) == before


@pytest.mark.parametrize("name", ("a\u00b4", "a\u02ff", "a\u25ff", "a\u27c0"))
def test_native_category_and_symbol_range_boundaries_preserve_permitted_text(game, name):
    # Permitted Sk/Sm and U+25FF immediately below the regex range must not
    # become a blanket rejection of all accented text or symbols.
    assert call(game, name).commonResponse.updatedData.photos[0].name == name


@pytest.mark.parametrize("photo_id,code", (("", RpcCode.INVALID_ARGUMENT), ("not-owned", RpcCode.PERMISSION_DENIED),
                                        ("other-profile-photo", RpcCode.PERMISSION_DENIED)))
def test_empty_unknown_or_other_profile_ids_never_create_or_modify_photos(game, photo_id, code):
    before = dump(game[1])
    with pytest.raises(RpcFailure) as error: call(game, "New", photo_id)
    assert error.value.code == code and dump(game[1]) == before


@pytest.mark.parametrize("raw", (b"\x0a\x80", b"\x0a\x01\xff", b"\x12\x01\xff"))
def test_malformed_protobuf_or_utf8_has_no_writes(game, raw):
    before = dump(game[1])
    with pytest.raises(RpcFailure) as error: game[0].handle(PATH, raw)
    assert error.value.code == RpcCode.INVALID_ARGUMENT and dump(game[1]) == before


@pytest.mark.parametrize("kind", ("missing", "different-schema", "malformed", "no-user", "duplicate", "empty-id"))
def test_incomplete_or_ambiguous_snapshot_is_not_repaired_by_renaming(game, kind):
    provider, state = game[:2]
    if kind == "missing":
        with state.connect() as db: db.execute("DELETE FROM snapshots WHERE profile='player'")
    elif kind in {"duplicate", "empty-id"}:
        value = snapshot(game)
        if kind == "duplicate": value.photos.add().CopyFrom(value.photos[0])
        else: value.photos[1].photoId = ""
        with state.connect() as db:
            db.execute("UPDATE snapshots SET response=? WHERE profile='player'", (value.SerializeToString(),))
    else:
        raw = (b"\x0a\x80" if kind == "malformed" else provider.schema.response_type(USER)().SerializeToString()
               if kind == "no-user" else state.snapshot("player")[0])
        with state.connect() as db:
            db.execute("UPDATE snapshots SET response=?,schema_sha256=? WHERE profile='player'",
                       (raw, "other" if kind == "different-schema" else provider.schema.fingerprint))
    before = dump(state)
    with pytest.raises(RpcFailure) as error: call(game, "New")
    assert error.value.code == RpcCode.FAILED_PRECONDITION and dump(state) == before


def test_rename_transaction_does_not_lose_concurrent_resource_updates(game):
    provider, state = game[:2]
    kept = protected(state)
    def act(index):
        if index % 2:
            call(game, "Photo" + str(index))
        else:
            def update(raw):
                value = provider.schema.response_type(USER).FromString(raw)
                value.items[0].amount += 1
                return value.SerializeToString()
            state.mutate_snapshot("player", provider.schema.fingerprint, update)
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(act, range(20)))
    assert snapshot(game).items[0].amount == 14
    assert snapshot(game).photos[0].name in {"Photo" + str(number) for number in range(1, 20, 2)}
    assert protected(state) == kept


def test_non_photo_rename_routes_are_not_claimed(game):
    before = dump(game[1])
    assert game[0].handle("/api.Photo/SwitchLock", b"") is None
    assert game[0].handle("/api.Profile/UpdateName", b"") is None
    assert dump(game[1]) == before
