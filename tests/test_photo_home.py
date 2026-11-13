"""The Pose top cast gate consumes Home's scene cache before Photo RPCs.

Original Android 6.1.1: PhotographyTopScreenPresenter validator0x59c32ac
calls PhotographyOutGameUtility.ValidateExpressionCharacter0x59bd634.
UserDataManager.SetCustomData copies HomeEnterResponse.photoExpressions at
0x4672d58..0x4672d5c. An empty Home cache rejects every cast member even
when UserPhotoPose ownership and Photo.ListShooting are already populated.
"""
import json
from pathlib import Path

import pytest

from idoly_local import codec
from idoly_local.application import Application
from idoly_local.catalog import FixtureStore
from idoly_local.h2_server import Context
from idoly_local.media_settings import DEFAULTS
from idoly_local.photo_shooting import PhotoSceneAccess
from idoly_local.rpc import RpcCode, RpcFailure
from test_media_stories import game, schema, UNKNOWN


REGULAR = ("char-ai", "char-aoi", "char-chs", "char-hrk", "char-kan", "char-kkr", "char-kor",
           "char-ktn", "char-mei", "char-mhk", "char-mna", "char-ngs", "char-rei", "char-rio",
           "char-rui", "char-ski", "char-skr", "char-smr", "char-suz", "char-szk", "char-yu")
EXCLUDED = ("char-mku", "char-chk", "char-ymk", "char-rik", "char-yo", "char-chn", "char-cca")
HOME = "/api.Home/Enter"
LIST = "/api.Photo/ListShooting"


@pytest.fixture
def photo_home(game, tmp_path):
    rows = {
        "Area": [{"id": "home-main", "type": 1, "order": 1, "questIds": []}],
        "HierarchyGrade": [{"id": "home-grade"}],
        "HierarchyDetailGrade": [{"id": "home-detail", "hierarchyGradeId": "home-grade",
                                   "requiredHierarchyPoint": 0, "requiredHierarchyRank": 0}],
        "PhotoActivity": [{"id": "activity"}],
        "PhotoQuestMusic": [{"id": "three-d"}, {"id": "video"}],
        "PhotoQuestStage": [{"id": "stage"}],
        "PhotoExpression": [{"id": "expression", "impossibleShootingCharacterIds": list(EXCLUDED),
                             "impossiblePhotoPoseIds": ["other-pose"]}],
        "Music": [{"id": "three-d", "is3dAvailable": True, "mvAssetId": ""},
                  {"id": "video", "is3dAvailable": False, "mvAssetId": "movie"}],
    }
    for table, values in rows.items():
        (game.master / (table + ".json")).write_text(json.dumps(values))
    raw, fingerprint = game.state.snapshot("media")
    snapshot = game.schema.response_type("/api.User/Get").FromString(raw)
    for character in (*REGULAR, *EXCLUDED):
        snapshot.characters.add(characterId=character)
    snapshot.photoPoses.add(photoPoseId="owned-pose").MergeFromString(UNKNOWN)
    snapshot.photoPoses.add(photoPoseId="other-pose")
    game.state.mutate_snapshot("media", fingerprint, lambda _: snapshot.SerializeToString())
    access = PhotoSceneAccess(activities={"activity": True}, musics={"three-d": True, "video": True},
                              stages={"stage": True}, expressions={"expression": True})
    application = Application(game.schema, game.state, FixtureStore(tmp_path / "fixtures", game.schema),
                              profile="media", master_dir=game.master, media_mode=True,
                              photo_scene_access=access)
    game.application, game.photo_rows = application, rows
    return game


def invoke(game, path, *, authenticated=True):
    request = game.schema.request_type(path)().SerializeToString()
    context = Context((("x-auth-token", game.token),) if authenticated else ())
    return game.schema.response_type(path).FromString(game.application.handle(path, codec.encode(request), context))


def native_pose_cast_allowed(character, snapshot, home, expressions, motion_pairs):
    """Contract of the original validator, not the server projection helper.

    It reads owned character poses, then separately checks whether every
    unlocked cached expression excludes all poses or the current character.
    The originals deliberately retain collaboration character exclusions.
    """
    poses = {row.photoPoseId for row in snapshot.photoPoses
             if (row.photoPoseId, character) in motion_pairs}
    if not poses:
        return False
    all_poses_impossible = all_characters_invalid = True
    for row in home.photoExpressions:
        if not row.isUnlocked:
            continue
        master = expressions[row.photoExpressionId]
        all_poses_impossible &= all(pose in master.get("impossiblePhotoPoseIds", []) for pose in poses)
        all_characters_invalid &= character in master.get("impossibleShootingCharacterIds", [])
    return not all_poses_impossible and not all_characters_invalid


def test_real_home_route_populates_the_native_pose_cast_cache_without_state_writes(photo_home):
    game = photo_home
    before = game.state.snapshot("media")
    with game.state.connect() as db:
        database_before = tuple(db.iterdump())
    snapshot = game.schema.response_type("/api.User/Get").FromString(before[0])
    expressions = {row["id"]: row for row in game.photo_rows["PhotoExpression"]}
    motions = {("owned-pose", character) for character in (*REGULAR, *EXCLUDED)}
    # This reproduces the old failure: poses owned and the list RPC unlocked,
    # but the client's independently bootstrapped Home cache is still empty.
    listing = invoke(game, LIST)
    assert listing.expressions[0].isUnlocked
    empty_home = game.schema.response_type(HOME)()
    assert not any(native_pose_cast_allowed(character, snapshot, empty_home, expressions, motions)
                   for character in REGULAR)
    home = invoke(game, HOME)
    assert [row.photoExpressionId for row in home.photoExpressions] == ["expression"]
    assert all(native_pose_cast_allowed(character, snapshot, home, expressions, motions)
               for character in REGULAR)
    assert not any(native_pose_cast_allowed(character, snapshot, home, expressions, motions)
                   for character in EXCLUDED)
    for source, target in (("activities", "photoActivities"), ("musics", "photoMusics"),
                           ("stages", "photoStages"), ("expressions", "photoExpressions")):
        assert getattr(home, target) == getattr(listing, source)
    assert game.state.snapshot("media") == before
    with game.state.connect() as db:
        assert tuple(db.iterdump()) == database_before
    with pytest.raises(RpcFailure) as denied:
        invoke(game, HOME, authenticated=False)
    assert denied.value.code == RpcCode.UNAUTHENTICATED
    assert game.state.snapshot("media") == before


def test_home_photo_projection_replaces_old_scene_cache_but_preserves_unrelated_unknown_fields(photo_home):
    game = photo_home
    home = game.schema.response_type(HOME)(currentMainAreaId="keep-area")
    home.commonResponse.updatedData.user.name = "keep-current-ACK"
    home.commonResponse.updatedData.user.MergeFromString(UNKNOWN)
    home.eventInfo.SetInParent()
    home.MergeFromString(UNKNOWN)
    for target, identity in (("photoActivities", "photoActivityId"), ("photoMusics", "musicId"),
                             ("photoStages", "stageId"), ("photoExpressions", "photoExpressionId")):
        setattr(getattr(home, target).add(isUnlocked=False), identity, "old-scene")
    unchanged = game.schema.response_type(HOME)()
    unchanged.CopyFrom(home)
    for name in ("photoActivities", "photoMusics", "photoStages", "photoExpressions"):
        unchanged.ClearField(name)
    game.application.photo_shootings.fill_home(home)
    for name in ("photoActivities", "photoMusics", "photoStages", "photoExpressions"):
        assert all(row.isUnlocked for row in getattr(home, name))
        home.ClearField(name)
    assert home.SerializeToString() == unchanged.SerializeToString()


def test_home_and_list_use_same_current_movie_filter(photo_home):
    game = photo_home
    game.application.photo_shootings.media_settings = {**DEFAULTS, "hide_video_mv": True}
    listing, home = invoke(game, LIST), invoke(game, HOME)
    assert [row.musicId for row in listing.musics] == ["three-d"]
    assert home.photoMusics == listing.musics
    assert home.photoExpressions == listing.expressions


def test_invalid_home_photo_projection_does_not_partly_replace_cached_rows(photo_home):
    game = photo_home
    home = game.schema.response_type(HOME)()
    home.photoExpressions.add(photoExpressionId="keep-before-error", isUnlocked=False)
    before = home.SerializeToString()
    game.application.photo_shootings.scene_access = PhotoSceneAccess(
        activities={"activity": True}, expressions={"not-an-original-expression": True})
    with pytest.raises(RpcFailure) as denied:
        game.application.photo_shootings.fill_home(home)
    assert denied.value.code == RpcCode.FAILED_PRECONDITION
    assert home.SerializeToString() == before


def test_ordinary_home_is_not_given_gallery_scene_access(photo_home):
    provider = photo_home.application.photo_shootings
    provider.media_mode = False
    provider.scene_access = None
    home = photo_home.schema.response_type(HOME)(currentMainAreaId="ordinary-current-area")
    home.photoExpressions.add(photoExpressionId="preserved-private-locked", isUnlocked=False).MergeFromString(UNKNOWN)
    home.MergeFromString(UNKNOWN)
    before = home.SerializeToString()
    provider.fill_home(home)
    assert home.SerializeToString() == before
