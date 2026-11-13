"""Media startup supplies the image IDs indexed by the original transition.

Android 6.1.1 SelectCreatePhotoAsync directly indexes
IPhotographyTransition.NextPhotoImageIds before either create RPC. Its getter
reads the current User.nextPhotoImageIds, so testing the reservation helper
alone cannot detect a missing startup call.
"""
import os
from pathlib import Path

import pytest

from idoly_local import codec
from idoly_local.application import Application
from idoly_local.catalog import FixtureStore
from idoly_local.gameplay import seed_starter_profile
from idoly_local.h2_server import Context
from idoly_local.media_runtime import prepare_media_profile
from idoly_local.photo_shooting import valid_image_id
from idoly_local.rpc import RpcCode, RpcFailure
from idoly_local.state import State
from test_photo_shooting import schema, USER, EXPRESSION_CHECK, UNKNOWN


@pytest.fixture(scope="module")
def original_photo_master():
    default = Path(__file__).resolve().parents[1] / "data/master-json"
    configured = os.environ.get("IDOLY_TEST_MASTER_DIR")
    directory = Path(configured) if configured else default
    missing = [name for name in ("PhotoPose", "PhotoPoseMotion", "ExcursionPlace",
                                "ExcursionPlaceSetting", "ExcursionGazeReaction")
               if not (directory / (name + ".json")).is_file()]
    if missing:
        if configured:
            pytest.fail("Configured original master directory lacks required photo tables")
        pytest.skip("Original public media startup masters are unavailable")
    return directory


def invoke(application, token, path, **values):
    request = application.schema.request_type(path)(**values).SerializeToString()
    result = application.handle(path, codec.encode(request), Context((("x-auth-token", token),)))
    return application.schema.response_type(path).FromString(result)


def seeded_state(schema, master, tmp_path):
    state = State(tmp_path / "media.db")
    for profile in ("media", "ordinary"):
        seed_starter_profile(state, schema, profile, master)
    token, _ = state.login("media")
    return state, token


@pytest.mark.parametrize("existing_ids", ((), ("preserved-one", "preserved-two")))
def test_real_media_startup_repairs_transition_image_ids_without_photos_or_film_changes(
        schema, original_photo_master, tmp_path, existing_ids):
    master = original_photo_master
    state, token = seeded_state(schema, master, tmp_path)
    value = schema.response_type(USER).FromString(state.snapshot("media")[0])
    assert not value.user.nextPhotoImageIds
    value.user.nextPhotoImageId = "legacy-kept"
    value.user.nextPhotoImageIds.extend(existing_ids)
    value.user.MergeFromString(UNKNOWN)
    value.MergeFromString(UNKNOWN)
    state.mutate_snapshot("media", schema.fingerprint, lambda _: value.SerializeToString())
    ordinary_before = state.snapshot("ordinary")
    photos_before = tuple(row.SerializeToString() for row in value.photos)
    items_before = tuple(row.SerializeToString() for row in value.items)
    # Exact original failure: even selection index zero cannot be read when
    # startup left this array empty. A partly populated old account also fails
    # at the first unreserved selection, before any creation request is sent.
    selected_index = len(existing_ids)
    with pytest.raises(IndexError):
        value.user.nextPhotoImageIds[selected_index]

    scenes = prepare_media_profile(state, schema, "media", master)
    application = Application(schema, state, FixtureStore(tmp_path / "fixtures", schema),
        profile="media", master_dir=master, media_mode=True, photo_scene_access=scenes)
    response = invoke(application, token, USER)
    assert valid_image_id(response.user.nextPhotoImageIds[selected_index])
    assert valid_image_id(response.user.nextPhotoImageIds[19])
    assert len(set(response.user.nextPhotoImageIds)) == len(response.user.nextPhotoImageIds)
    assert list(response.user.nextPhotoImageIds[:len(existing_ids)]) == list(existing_ids)
    assert response.user.nextPhotoImageId == "legacy-kept"
    assert UNKNOWN in response.user.SerializeToString() and UNKNOWN in response.SerializeToString()
    assert tuple(row.SerializeToString() for row in response.photos) == photos_before
    assert tuple(row.SerializeToString() for row in response.items) == items_before
    assert state.snapshot("ordinary") == ordinary_before
    assert state.authenticated(token, "media")

    # Preview still checks a real original scene and compatible owned style.
    # Neither that check nor reopening the gallery consumes a reservation.
    character = next(row for row in response.characters if row.characterId == "char-ai")
    before_check = state.snapshot("media")
    checked = invoke(application, token, EXPRESSION_CHECK,
        photoExpressionId="photo_expression-lesson_03", characterIds=[character.characterId],
        costumeIds=[character.favoriteCostumeId], hairIds=[character.favoriteHairId])
    assert checked.HasField("commonResponse") and not checked.commonResponse.ListFields()
    assert state.snapshot("media") == before_check
    prepare_media_profile(state, schema, "media", master)
    assert state.snapshot("media") == before_check
    assert invoke(application, token, USER) == response
    assert state.snapshot("ordinary") == ordinary_before


def test_malformed_existing_reservations_abort_real_media_upgrade_atomically(
        schema, original_photo_master, tmp_path):
    state, token = seeded_state(schema, original_photo_master, tmp_path)
    value = schema.response_type(USER).FromString(state.snapshot("media")[0])
    value.user.nextPhotoImageIds.extend(("duplicate", "duplicate"))
    state.mutate_snapshot("media", schema.fingerprint, lambda _: value.SerializeToString())
    with state.connect() as connection:
        before = tuple(connection.iterdump())
    with pytest.raises(RpcFailure) as rejected:
        prepare_media_profile(state, schema, "media", original_photo_master)
    assert rejected.value.code == RpcCode.FAILED_PRECONDITION
    with state.connect() as connection:
        assert tuple(connection.iterdump()) == before
    assert state.authenticated(token, "media")
