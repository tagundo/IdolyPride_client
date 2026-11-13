"""Photo reads/checks preserve inventory and require real image ownership."""
import json
from pathlib import Path

import pytest

from idoly_local.photo_shooting import PhotoSceneAccess, PhotoShootings, reserve_photo_image_ids
from idoly_local.rpc import RpcCode, RpcFailure
from idoly_local.schema import Schema
from idoly_local.state import State


USER = "/api.User/Get"
LIST = "/api.Photo/ListShooting"
CHECK = "/api.Photo/CheckShooting"
EXPRESSION_CHECK = "/api.Photo/CheckExpressionShooting"
CREATE = "/api.Photo/CreateShootings"
URL = "/api.Photo/GetImageURL"
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
    rows = {
        "Character": [{"id": "char-a"}, {"id": "char-b"}],
        "Costume": [{"id": "cos-a", "characterId": "char-a", "costumeTypeId": "casl"},
                    {"id": "cos-b", "characterId": "char-b", "costumeTypeId": "idol"},
                    {"id": "unowned", "characterId": "char-a", "costumeTypeId": "casl"}],
        "Hair": [{"id": "hair-a", "characterId": "char-a", "wearableCostumeIds": [],
                  "notWearableCostumeIds": []}, {"id": "hair-b", "characterId": "char-b",
                  "wearableCostumeIds": ["cos-b"], "notWearableCostumeIds": []}],
        "PhotoActivity": [{"id": "activity-a", "type": 1, "costumeTypeIds": ["casl"],
                           "impossibleShootingCharacterIds": []},
                          {"id": "activity-b", "type": 2, "costumeTypeIds": [],
                           "impossibleShootingCharacterIds": []}],
        "PhotoQuestMusic": [{"id": "music-a"}, {"id": "unowned-music"}],
        "PhotoQuestStage": [{"id": "stage-a"}],
        "Stage": [{"id": "expression-stage", "assetId": "expression-scene"}],
        "PhotoExpression": [{"id": "expression-a", "stageId": "expression-stage",
                             "characterAmountArray": [1, 2], "costumeTypeIds": ["casl"],
                             "impossibleShootingCharacterIds": []}],
    }
    for name, values in rows.items():
        (master / (name + ".json")).write_text(json.dumps(values))
    state = State(tmp_path / "state.sqlite")
    state.ensure_profile("player")
    value = schema.response_type(USER)()
    value.user.name = "Preserved manager"
    value.user.nextPhotoImageIds.append("already-reserved")
    for suffix in ("a", "b"):
        value.characters.add(characterId="char-" + suffix)
        value.costumes.add(costumeId="cos-" + suffix)
        value.hairs.add(hairId="hair-" + suffix)
    value.photos.add(photoId="owned-photo", assetId="owned-image", imageType=2, rarity=4, locked=True)
    value.photos.add(photoId="stock-photo", assetId="stock-image", imageType=1, rarity=5)
    value.items.add(itemId="item-photo_shooting-01", amount=1)
    value.MergeFromString(UNKNOWN)
    value.user.MergeFromString(UNKNOWN)
    state.save_snapshot("player", value.SerializeToString(), schema.fingerprint, starter_version=4)
    state.save_snapshot("other", value.SerializeToString(), schema.fingerprint)
    state.login("player")
    state.login("other")
    access = PhotoSceneAccess(activities={"activity-a": True, "activity-b": False},
                             musics={"music-a": True}, stages={"stage-a": True},
                             expressions={"expression-a": False})
    provider = PhotoShootings(schema, state, "player", master, scene_access=access)
    return provider, state, master, access


def dump(state):
    with state.connect() as connection:
        return tuple(connection.iterdump())


def call(game, path, **values):
    provider = game[0]
    result = provider.handle(path, provider.schema.request_type(path)(**values).SerializeToString())
    assert result is not None
    return provider.schema.response_type(path).FromString(result)


def quest_values():
    return dict(actionType=3, photoMusicId="music-a", photoStageId="stage-a",
                characterIds=["char-a"], costumeIds=["cos-a"], hairIds=["hair-a"])


def expression_game(game, *, media=False):
    provider, state, master, access = game
    access = PhotoSceneAccess(activities=access.activities, musics=access.musics,
                              stages=access.stages, expressions={"expression-a": True})
    return (PhotoShootings(provider.schema, state, "player", master, scene_access=access,
                           media_mode=media), state, master, access)


@pytest.mark.parametrize("legacy", (False, True))
def test_expression_preview_accepts_owned_legacy_or_current_styles_without_writes(game, legacy):
    enabled = expression_game(game)
    values = dict(photoExpressionId="expression-a")
    if legacy:
        values.update(characterId="char-a", costumeId="cos-a", hairId="hair-a")
    else:
        values.update(characterIds=["char-a"], costumeIds=["cos-a"], hairIds=["hair-a"])
    before = dump(game[1])
    result = call(enabled, EXPRESSION_CHECK, **values)
    assert result.HasField("commonResponse")
    assert result.commonResponse.SerializeToString() == b""
    assert not result.commonResponse.HasField("updatedData")
    assert not result.commonResponse.HasField("deletedData")
    assert call(enabled, EXPRESSION_CHECK, **values) == result
    assert dump(game[1]) == before


def test_expression_gallery_supports_master_cast_count_and_all_owned_compatible_outfits(game):
    values = dict(photoExpressionId="expression-a", characterIds=["char-a", "char-b"],
                  costumeIds=["cos-a", "cos-b"], hairIds=["hair-a", "hair-b"])
    before = dump(game[1])
    result = call(expression_game(game, media=True), EXPRESSION_CHECK, **values)
    assert result.commonResponse.SerializeToString() == b""
    with pytest.raises(RpcFailure) as error:
        call(expression_game(game), EXPRESSION_CHECK, **values)
    assert error.value.code == RpcCode.INVALID_ARGUMENT
    assert dump(game[1]) == before


@pytest.mark.parametrize("change,code", (
    ({"photoExpressionId": ""}, RpcCode.INVALID_ARGUMENT),
    ({"photoExpressionId": "absent"}, RpcCode.INVALID_ARGUMENT),
    ({"characterIds": [], "costumeIds": [], "hairIds": []}, RpcCode.INVALID_ARGUMENT),
    ({"characterIds": ["char-a"] * 3, "costumeIds": ["cos-a"] * 3,
      "hairIds": ["hair-a"] * 3}, RpcCode.INVALID_ARGUMENT),
    ({"costumeIds": []}, RpcCode.INVALID_ARGUMENT),
    ({"costumeIds": ["unowned"]}, RpcCode.PERMISSION_DENIED),
    ({"hairIds": ["hair-b"]}, RpcCode.INVALID_ARGUMENT),
    ({"characterId": "char-b", "costumeId": "cos-b", "hairId": "hair-b"}, RpcCode.INVALID_ARGUMENT),
))
def test_expression_invalid_selection_never_changes_profile(game, change, code):
    values = dict(photoExpressionId="expression-a", characterIds=["char-a"],
                  costumeIds=["cos-a"], hairIds=["hair-a"])
    values.update(change)
    before = dump(game[1])
    with pytest.raises(RpcFailure) as error:
        call(expression_game(game, media=True), EXPRESSION_CHECK, **values)
    assert error.value.code == code
    assert dump(game[1]) == before


def test_expression_locked_access_is_not_inferred_from_master_or_pose_ownership(game):
    before = dump(game[1])
    with pytest.raises(RpcFailure) as error:
        call(game, EXPRESSION_CHECK, photoExpressionId="expression-a",
             characterId="char-a", costumeId="cos-a", hairId="hair-a")
    assert error.value.code == RpcCode.PERMISSION_DENIED
    assert dump(game[1]) == before


@pytest.mark.parametrize("field,value", (
    ("stageId", "missing-stage"), ("characterAmountArray", []),
    ("characterAmountArray", [0]), ("characterAmountArray", [True]),
    ("characterAmountArray", [1, 1]),
))
def test_expression_requires_real_stage_and_valid_master_cast_before_success(game, field, value):
    master = game[2] / "PhotoExpression.json"
    rows = json.loads(master.read_text()); rows[0][field] = value
    master.write_text(json.dumps(rows))
    before = dump(game[1])
    with pytest.raises(RpcFailure) as error:
        call(expression_game(game, media=True), EXPRESSION_CHECK, photoExpressionId="expression-a",
             characterId="char-a", costumeId="cos-a", hairId="hair-a")
    assert error.value.code == RpcCode.FAILED_PRECONDITION
    assert dump(game[1]) == before


def test_list_preserves_locked_rows_and_does_not_infer_master_ownership(game):
    before = dump(game[1])
    result = call(game, LIST)
    assert [(row.photoActivityId, row.isUnlocked) for row in result.activities] == [
        ("activity-a", True), ("activity-b", False)]
    assert [(row.musicId, row.isUnlocked) for row in result.musics] == [("music-a", True)]
    assert [(row.stageId, row.isUnlocked) for row in result.stages] == [("stage-a", True)]
    assert [(row.photoExpressionId, row.isUnlocked) for row in result.expressions] == [("expression-a", False)]
    assert result.HasField("DokanInfo")
    assert result.HasField("commonResponse")
    assert not result.commonResponse.HasField("updatedData")
    assert not result.commonResponse.HasField("deletedData")
    assert result.commonResponse.SerializeToString() == b""
    assert call(game, LIST) == result
    assert dump(game[1]) == before


def test_missing_unlock_evidence_fails_and_empty_preserved_catalog_is_valid(game):
    provider, state, master = game[:3]
    before = dump(state)
    missing = PhotoShootings(provider.schema, state, "player", master)
    with pytest.raises(RpcFailure, match="scene unlocks"):
        missing.handle(LIST, b"")
    empty = PhotoShootings(provider.schema, state, "player", master,
                           scene_access=lambda profile: PhotoSceneAccess())
    result = provider.schema.response_type(LIST).FromString(empty.handle(LIST, b""))
    assert not result.activities and not result.musics and not result.stages
    assert result.HasField("commonResponse")
    assert not result.commonResponse.HasField("updatedData")
    assert not result.commonResponse.HasField("deletedData")
    assert dump(state) == before


def test_checks_validate_real_owned_scene_and_styles_without_writes(game):
    before = dump(game[1])
    for values in (quest_values(), dict(actionType=1, photoActivityId="activity-a",
            characterIds=["char-a"], costumeIds=["cos-a"], hairIds=["hair-a"])):
        result = call(game, CHECK, **values)
        assert result.HasField("commonResponse")
        assert not result.commonResponse.HasField("updatedData")
        assert not result.commonResponse.HasField("deletedData")
        assert result.commonResponse.SerializeToString() == b""
        assert call(game, CHECK, **values) == result
    assert dump(game[1]) == before


@pytest.mark.parametrize("change,code", (
    ({"photoMusicId": "unowned-music"}, RpcCode.FAILED_PRECONDITION),
    ({"photoStageId": "unknown-stage"}, RpcCode.INVALID_ARGUMENT),
    ({"costumeIds": ["unowned"]}, RpcCode.PERMISSION_DENIED),
    ({"costumeIds": ["cos-b"]}, RpcCode.INVALID_ARGUMENT),
    ({"hairIds": ["hair-b"]}, RpcCode.INVALID_ARGUMENT),
    ({"hairIds": []}, RpcCode.INVALID_ARGUMENT),
    ({"characterIds": []}, RpcCode.INVALID_ARGUMENT),
    ({"actionType": 4}, RpcCode.INVALID_ARGUMENT),
))
def test_invalid_checks_fail_atomically(game, change, code):
    values = quest_values() | change
    before = dump(game[1])
    with pytest.raises(RpcFailure) as error:
        call(game, CHECK, **values)
    assert error.value.code == code
    assert dump(game[1]) == before


def test_activity_restrictions_and_locked_scenes_are_enforced(game):
    before = dump(game[1])
    for values in (
        dict(actionType=2, photoActivityId="activity-b", characterIds=["char-a"],
             costumeIds=["cos-a"], hairIds=["hair-a"]),
        dict(actionType=1, photoActivityId="activity-a", characterIds=["char-b"],
             costumeIds=["cos-b"], hairIds=["hair-b"]),
    ):
        with pytest.raises(RpcFailure):
            call(game, CHECK, **values)
    assert dump(game[1]) == before


def media_game(game):
    provider, state, master, access = game
    return (PhotoShootings(provider.schema, state, provider.profile, master,
                           scene_access=access, media_mode=True), state, master, access)


def test_media_job_accepts_owned_outfit_of_other_type_without_changing_normal_mode_or_state(game):
    values = dict(actionType=1, photoActivityId="activity-a", characterIds=["char-b"],
                  costumeIds=["cos-b"], hairIds=["hair-b"])
    before = dump(game[1])
    with pytest.raises(RpcFailure) as error:
        call(game, CHECK, **values)
    assert error.value.code == RpcCode.INVALID_ARGUMENT
    result = call(media_game(game), CHECK, **values)
    assert result.HasField("commonResponse")
    assert not result.commonResponse.HasField("updatedData")
    assert not result.commonResponse.HasField("deletedData")
    assert result.commonResponse.SerializeToString() == b""
    assert call(media_game(game), CHECK, **values) == result
    # Selecting a gallery job never changes the normal provider or any
    # profile, session, inventory/film row, counter or unknown protobuf field.
    with pytest.raises(RpcFailure) as error:
        call(game, CHECK, **values)
    assert error.value.code == RpcCode.INVALID_ARGUMENT
    assert dump(game[1]) == before


@pytest.mark.parametrize("path", (CHECK, EXPRESSION_CHECK))
def test_application_wires_gallery_job_policy_only_after_authentication(game, tmp_path, path):
    from idoly_local import codec
    from idoly_local.application import Application
    from idoly_local.catalog import FixtureStore

    class Context:
        def __init__(self, metadata):
            self.metadata = metadata

        def invocation_metadata(self):
            return self.metadata

        def abort(self, code, details):
            raise RpcFailure(code, details)

    provider, state, master, access = expression_game(game) if path == EXPRESSION_CHECK else game
    fixtures = FixtureStore(tmp_path / "fixtures", provider.schema)
    ordinary = Application(provider.schema, state, fixtures, profile="player", master_dir=master,
                           photo_scene_access=access)
    gallery = Application(provider.schema, state, fixtures, profile="player", master_dir=master,
                          photo_scene_access=access, media_mode=True)
    token, _ = state.login("player")
    values = dict(characterIds=["char-b"], costumeIds=["cos-b"], hairIds=["hair-b"])
    values.update(dict(photoExpressionId="expression-a") if path == EXPRESSION_CHECK else
                  dict(actionType=1, photoActivityId="activity-a"))
    request = provider.schema.request_type(path)(**values)
    envelope = codec.encode(request.SerializeToString())
    context = Context((("x-auth-token", token),))
    before = dump(state)
    with pytest.raises(RpcFailure) as error:
        gallery.handle(path, envelope, Context(()))
    assert error.value.code == RpcCode.UNAUTHENTICATED
    with pytest.raises(RpcFailure) as error:
        ordinary.handle(path, envelope, context)
    assert error.value.code == RpcCode.INVALID_ARGUMENT
    result = provider.schema.response_type(path).FromString(gallery.handle(path, envelope, context))
    assert result.HasField("commonResponse")
    assert not result.commonResponse.HasField("updatedData")
    assert not result.commonResponse.HasField("deletedData")
    assert result.commonResponse.SerializeToString() == b""
    assert provider.schema.response_type(path).FromString(
        gallery.handle(path, envelope, context)) == result
    assert dump(state) == before


@pytest.mark.parametrize("case,code", (
    ("blocked-character", RpcCode.INVALID_ARGUMENT),
    ("unowned-costume", RpcCode.PERMISSION_DENIED),
    ("unowned-character", RpcCode.PERMISSION_DENIED),
    ("wrong-character", RpcCode.INVALID_ARGUMENT),
    ("incompatible-hair", RpcCode.INVALID_ARGUMENT),
    ("locked-activity", RpcCode.FAILED_PRECONDITION),
))
def test_media_job_keeps_character_ownership_hair_and_scene_guards(game, case, code):
    provider, state, master, _ = game
    values = dict(actionType=1, photoActivityId="activity-a", characterIds=["char-a"],
                  costumeIds=["cos-a"], hairIds=["hair-a"])
    if case == "blocked-character":
        source = master / "PhotoActivity.json"
        rows = json.loads(source.read_text())
        rows[0]["impossibleShootingCharacterIds"] = ["char-b"]
        source.write_text(json.dumps(rows))
        values.update(characterIds=["char-b"], costumeIds=["cos-b"], hairIds=["hair-b"])
    elif case == "unowned-costume":
        values["costumeIds"] = ["unowned"]
    elif case == "unowned-character":
        raw, fingerprint = state.snapshot("player")
        snapshot = provider.schema.response_type(USER).FromString(raw)
        del snapshot.characters[0]
        state.mutate_snapshot("player", fingerprint, lambda _: snapshot.SerializeToString())
    elif case == "wrong-character":
        values["costumeIds"] = ["cos-b"]
    elif case == "incompatible-hair":
        source = master / "Hair.json"
        rows = json.loads(source.read_text())
        rows[0]["wearableCostumeIds"] = ["unowned"]
        source.write_text(json.dumps(rows))
    else:
        values["actionType"] = 2
        values["photoActivityId"] = "activity-b"
    before = dump(state)
    with pytest.raises(RpcFailure) as error:
        call(media_game(game), CHECK, **values)
    assert error.value.code == code
    assert dump(state) == before


@pytest.mark.parametrize("value", (None, 0, 1, "true"))
def test_photo_media_mode_requires_an_explicit_boolean(game, value):
    provider, state, master, access = game
    before = dump(state)
    with pytest.raises(ValueError, match="explicit boolean"):
        PhotoShootings(provider.schema, state, provider.profile, master,
                       scene_access=access, media_mode=value)
    assert dump(state) == before


def test_creation_cannot_consume_film_or_fabricate_photo_without_upload_and_verified_rules(game):
    before = dump(game[1])
    values = quest_values() | {"createShootingParams": [dict(photoImageId="already-reserved",
              itemId="item-photo_shooting-01", mainCharacterId="char-a")], "manualCount": 1}
    for _ in range(2):
        with pytest.raises(RpcFailure, match="finalized image upload") as error:
            call(game, CREATE, **values)
        assert error.value.code == RpcCode.FAILED_PRECONDITION
    assert dump(game[1]) == before


def test_photo_urls_require_owned_user_image_and_finalized_provider(game):
    provider = game[0]
    before = dump(game[1])
    for asset, code in (("owned-image", RpcCode.NOT_FOUND), ("missing", RpcCode.PERMISSION_DENIED),
                         ("stock-image", RpcCode.PERMISSION_DENIED), ("../escape", RpcCode.INVALID_ARGUMENT)):
        with pytest.raises(RpcFailure) as error:
            call(game, URL, type=3, assetIds=[asset])
        assert error.value.code == code
    requested = []
    def image_urls(profile, asset):
        requested.append((profile, asset))
        return ("http://127.0.0.1:8080/photo/owned-image.jpg", "")
    provider.image_urls = image_urls
    result = call(game, URL, type=3, assetIds=["owned-image"])
    assert requested == [("player", "owned-image")]
    assert result.urlList[0].assetId == "owned-image"
    assert result.urlList[0].origUrl == result.urlList[0].tmbUrl
    assert dump(game[1]) == before


@pytest.mark.parametrize("route", (LIST, CHECK, CREATE, URL))
def test_malformed_requests_do_not_write(game, route):
    before = dump(game[1])
    with pytest.raises(RpcFailure) as error:
        game[0].handle(route, b"\x0a\x80")
    assert error.value.code == RpcCode.INVALID_ARGUMENT
    assert dump(game[1]) == before


def test_reservations_preserve_legacy_and_unknown_fields_and_are_idempotent(schema):
    value = schema.response_type(USER)()
    value.user.nextPhotoImageId = "legacy-preserved"
    value.user.nextPhotoImageIds.extend(["existing-a", "existing-b"])
    value.user.MergeFromString(UNKNOWN)
    expected = type(value.user)()
    expected.CopyFrom(value.user)
    ids = iter(["existing-a", *["new-" + str(i) for i in range(18)]])
    assert reserve_photo_image_ids(value.user, id_factory=lambda: next(ids))
    assert list(value.user.nextPhotoImageIds) == ["existing-a", "existing-b", *["new-" + str(i) for i in range(18)]]
    before = value.user.SerializeToString()
    assert not reserve_photo_image_ids(value.user, id_factory=lambda: pytest.fail("must not generate"))
    assert value.user.SerializeToString() == before
    del value.user.nextPhotoImageIds[2:]
    assert value.user.SerializeToString() == expected.SerializeToString()


@pytest.mark.parametrize("ids", (["duplicate", "duplicate"], ["../invalid"], [""]))
def test_invalid_imported_reservations_are_not_silently_replaced(schema, ids):
    user = schema.response_type(USER)().user
    user.nextPhotoImageIds.extend(ids)
    before = user.SerializeToString()
    with pytest.raises(RpcFailure):
        reserve_photo_image_ids(user)
    assert user.SerializeToString() == before


def test_broken_reservation_generator_cannot_partially_write(schema):
    user = schema.response_type(USER)().user
    user.nextPhotoImageIds.append("keep")
    before = user.SerializeToString()
    with pytest.raises(RpcFailure, match="unique image IDs"):
        reserve_photo_image_ids(user, id_factory=lambda: "keep")
    assert user.SerializeToString() == before
