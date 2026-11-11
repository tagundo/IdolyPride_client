"""The original MV check has an empty stage and remains a read-only operation."""
import json

import pytest

from idoly_local.photo_shooting import PhotoSceneAccess
from idoly_local.rpc import RpcCode, RpcFailure
from test_photo_shooting import game as photo_game, schema, call, dump, CHECK, CREATE


@pytest.fixture
def movie(photo_game):
    provider, _, master, access = photo_game
    music = [
        {"id": "movie-a", "is3dAvailable": False, "mvAssetId": "actual-master-movie"},
        {"id": "music-a", "is3dAvailable": True, "mvAssetId": ""},
    ]
    (master / "Music.json").write_text(json.dumps(music))
    path = master / "PhotoQuestMusic.json"
    rows = json.loads(path.read_text())
    rows.append({"id": "movie-a"})
    path.write_text(json.dumps(rows))
    provider.scene_access = PhotoSceneAccess(activities=access.activities,
        musics=dict(access.musics) | {"movie-a": True}, stages=access.stages,
        expressions=access.expressions)
    return photo_game


def values():
    return dict(actionType=3, photoMusicId="movie-a", photoStageId="")


def test_real_movie_can_check_with_empty_stage_and_no_invented_cast(movie):
    before = dump(movie[1])
    result = call(movie, CHECK, **values())
    assert result.commonResponse.HasField("updatedData")
    assert not result.commonResponse.updatedData.ListFields()
    assert not result.commonResponse.deletedData.ListFields()
    assert call(movie, CHECK, **values()) == result
    assert dump(movie[1]) == before


def test_supplied_movie_cast_still_requires_owned_matching_compatible_styles(movie):
    before = dump(movie[1])
    cast = dict(characterIds=["char-a"], costumeIds=["cos-a"], hairIds=["hair-a"])
    call(movie, CHECK, **(values() | cast))
    for change, code in (
        ({"costumeIds": ["unowned"]}, RpcCode.PERMISSION_DENIED),
        ({"costumeIds": ["cos-b"]}, RpcCode.INVALID_ARGUMENT),
        ({"hairIds": ["hair-b"]}, RpcCode.INVALID_ARGUMENT),
        ({"hairIds": []}, RpcCode.INVALID_ARGUMENT),
        ({"characterIds": []}, RpcCode.INVALID_ARGUMENT),
    ):
        with pytest.raises(RpcFailure) as denied:
            call(movie, CHECK, **(values() | cast | change))
        assert denied.value.code == code
    assert dump(movie[1]) == before


@pytest.mark.parametrize("kind", ("ordinary-3d", "empty-asset", "wrong-asset-type", "unknown-music",
                                  "unknown-stage", "locked"))
def test_empty_stage_does_not_bypass_ordinary_or_invalid_or_locked_movie_checks(movie, kind):
    provider, state, master, access = movie
    request = values()
    if kind == "ordinary-3d":
        request["photoMusicId"] = "music-a"
    elif kind in ("empty-asset", "wrong-asset-type"):
        path = master / "Music.json"
        rows = json.loads(path.read_text())
        rows[0]["mvAssetId"] = "" if kind == "empty-asset" else 5
        path.write_text(json.dumps(rows))
    elif kind == "unknown-music":
        request["photoMusicId"] = "unknown-private-movie"
    elif kind == "unknown-stage":
        request["photoStageId"] = "unknown-private-stage"
    else:
        provider.scene_access = PhotoSceneAccess(activities=access.activities,
            musics=dict(access.musics) | {"movie-a": False}, stages=access.stages,
            expressions=access.expressions)
    before = dump(state)
    with pytest.raises(RpcFailure) as denied:
        call(movie, CHECK, **request)
    assert denied.value.code == (RpcCode.FAILED_PRECONDITION if kind == "locked" else RpcCode.INVALID_ARGUMENT)
    assert "unknown-private" not in denied.value.details
    assert dump(state) == before


def test_movie_classifier_uses_master_asset_not_music_id_prefix_or_3d_flag(movie):
    provider, state, master, _ = movie
    path = master / "Music.json"
    rows = json.loads(path.read_text())
    rows[0]["is3dAvailable"] = True
    path.write_text(json.dumps(rows))
    before = dump(state)
    call(movie, CHECK, **values())
    assert dump(state) == before


def test_movie_check_does_not_implement_photo_upload_creation_or_film_consumption(movie):
    before = dump(movie[1])
    with pytest.raises(RpcFailure, match="finalized image upload") as denied:
        call(movie, CREATE, **(values() | {"createShootingParams": [{"photoImageId": "already-reserved",
             "itemId": "item-photo_shooting-01", "mainCharacterId": "char-a"}], "manualCount": 1}))
    assert denied.value.code == RpcCode.FAILED_PRECONDITION
    assert dump(movie[1]) == before
