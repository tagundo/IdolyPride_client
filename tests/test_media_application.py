"""Media routes cannot be shadowed by captured ordinary account responses."""
import json
from pathlib import Path

import pytest

from idoly_local import codec
from idoly_local.application import Application
from idoly_local.catalog import FixtureStore, import_response
from idoly_local.h2_server import Context
from idoly_local.photo_shooting import PhotoSceneAccess
from idoly_local.rpc import RpcCode, RpcFailure
from test_media_stories import game, schema


def captured(game, root, path, response):
    source = root / (path.replace("/", "-") + ".pb")
    source.write_bytes(response.SerializeToString())
    import_response(source, root / "fixtures", game.schema, path)


def app(game, root, media, *, master_response=None):
    return Application(game.schema, game.state, FixtureStore(root / "fixtures", game.schema),
        profile="media", master_dir=game.master, media_mode=media,
        master_response=master_response,
        photo_scene_access=PhotoSceneAccess())


def invoke(game, application, path, *, authenticated=True):
    context = Context((("x-auth-token", game.token),) if authenticated else ())
    request = game.schema.request_type(path)().SerializeToString()
    raw = application.handle(path, codec.encode(request), context)
    return game.schema.response_type(path).FromString(raw)


def test_media_master_version_matches_served_packs_and_preserves_original_catalog(game, tmp_path):
    version_path = "/api.Master/GetVersion"
    old = game.schema.response_type(version_path)(version="captured-original-version")
    captured(game, tmp_path, version_path, old)
    tag = game.schema.response_type("/api.Master/Get")()
    tag.masterTag.version = "local-media-outfits-v1-current"
    tag.masterTag.masterTagPacks.add(type="PhotoActivity", fileName="media-photo.db", fileSize=123)
    source_version = (game.master / "!version.txt").read_bytes()
    before = game.state.snapshot("media")
    normal = app(game, tmp_path, False, master_response=tag.SerializeToString())
    assert invoke(game, normal, version_path) == old
    media = app(game, tmp_path, True, master_response=tag.SerializeToString())
    assert invoke(game, media, version_path).version == invoke(game, media, "/api.Master/Get").masterTag.version
    with pytest.raises(RpcFailure) as denied:
        invoke(game, media, version_path, authenticated=False)
    assert denied.value.code == RpcCode.UNAUTHENTICATED
    assert (game.master / "!version.txt").read_bytes() == source_version
    assert game.state.snapshot("media") == before


@pytest.mark.parametrize("raw", [b"\xff", b""])
def test_media_rejects_a_master_response_without_a_usable_version(game, tmp_path, raw):
    with pytest.raises(ValueError, match="Media client master response"):
        app(game, tmp_path, True, master_response=raw)


def test_media_user_get_uses_live_state_while_normal_fixture_precedence_is_unchanged(game, tmp_path):
    response = game.schema.response_type("/api.User/Get")()
    response.user.name = "Captured old account"
    captured(game, tmp_path, "/api.User/Get", response)
    assert invoke(game, app(game, tmp_path, False), "/api.User/Get").user.name == "Captured old account"
    application = app(game, tmp_path, True)
    before = game.state.snapshot("media")
    assert invoke(game, application, "/api.User/Get").user.name == "Media"
    assert game.state.snapshot("media") == before
    with pytest.raises(RpcFailure) as denied:
        invoke(game, application, "/api.User/Get", authenticated=False)
    assert denied.value.code == RpcCode.UNAUTHENTICATED


def test_media_360_catalog_route_keeps_auth_and_ignores_old_account_capture(game, tmp_path):
    path = "/api.PhotoPanorama/List"
    old = game.schema.response_type(path)()
    old.musics.add(musicId="captured-locked-music", isUnlocked=False)
    captured(game, tmp_path, path, old)
    assert invoke(game, app(game, tmp_path, False), path) == old
    application = app(game, tmp_path, True)
    current = game.schema.response_type(path)()
    current.musics.add(musicId="current-media-music", isUnlocked=True)
    application.media_panorama.handle = lambda route, plain: current.SerializeToString() if route == path else None
    before = game.state.snapshot("media")
    assert invoke(game, application, path) == current
    with pytest.raises(RpcFailure) as denied:
        invoke(game, application, path, authenticated=False)
    assert denied.value.code == RpcCode.UNAUTHENTICATED
    assert game.state.snapshot("media") == before


def test_media_company_route_keeps_auth_and_live_catalog_precedence(game, tmp_path):
    path = "/api.Company/Top"
    old = game.schema.response_type(path)()
    old.companyGradeInfos.add(id="captured-grade")
    captured(game, tmp_path, path, old)
    assert invoke(game, app(game, tmp_path, False), path) == old
    application = app(game, tmp_path, True)
    current = game.schema.response_type(path)()
    current.companyGradeInfos.add(id="current-media-grade")
    application.company_reads.handle = lambda route, plain: current.SerializeToString() if route == path else None
    before = game.state.snapshot("media")
    assert invoke(game, application, path) == current
    with pytest.raises(RpcFailure) as denied:
        invoke(game, application, path, authenticated=False)
    assert denied.value.code == RpcCode.UNAUTHENTICATED
    assert game.state.snapshot("media") == before


def test_media_home_uses_live_handler_and_same_story_parts_as_media_list(game, tmp_path):
    response = game.schema.response_type("/api.Home/Enter")(currentMainAreaId="old-capture")
    captured(game, tmp_path, "/api.Home/Enter", response)
    application = app(game, tmp_path, True)
    live = game.schema.response_type("/api.Home/Enter")(currentMainAreaId="current-media-area")
    application.gameplay.handle = lambda path, plain: live.SerializeToString()
    before = game.state.snapshot("media")
    actual = invoke(game, application, "/api.Home/Enter")
    expected = invoke(game, application, "/api.Story/ListExtra")
    assert actual.currentMainAreaId == "current-media-area"
    assert actual.extraStoryPartInfos == expected.infos
    assert game.state.snapshot("media") == before


def test_media_home_after_photography_entry_marker_does_not_accrue_unsupported_area_lessons(game, tmp_path):
    for table, rows in {
        "Area": [
            {"id": "area-main-001", "type": 1, "order": 1, "questIds": ["quest-1"]},
            {"id": "area-main-002", "type": 1, "order": 2, "questIds": ["quest-2"]},
            {"id": "area-main-003", "type": 1, "order": 3, "questIds": ["quest-3"]},
        ],
        "Setting": [{"secondsPerActivityLessonStep": 10}],
        "HierarchyGrade": [{"id": "home-grade"}],
        "HierarchyDetailGrade": [{"id": "home-detail", "hierarchyGradeId": "home-grade",
                                   "requiredHierarchyPoint": 0, "requiredHierarchyRank": 0}],
    }.items():
        (game.master / (table + ".json")).write_text(json.dumps(rows))
    raw, fingerprint = game.state.snapshot("media")
    snapshot = game.schema.response_type("/api.User/Get").FromString(raw)
    snapshot.areas.add(areaId="area-main-002", clearQuestCount=1)
    game.state.mutate_snapshot("media", fingerprint, lambda _: snapshot.SerializeToString())
    application = app(game, tmp_path, True)
    ordinary = app(game, tmp_path, False)
    assert ordinary.gameplay.lessons is ordinary.lessons
    # The media account's real new frontier previously invoked the normal
    # first-area policy and failed before the home response was returned.
    assert application.gameplay.lessons is None
    before = game.state.snapshot("media")
    with game.state.connect() as db:
        old_clock = db.execute("SELECT response FROM profile_lesson_progress WHERE profile='media'").fetchone()
    home = invoke(game, application, "/api.Home/Enter")
    assert home.currentMainAreaId == home.lessonProgress.currentAreaId == "area-main-003"
    assert home.lessonProgress.maxRewardTime == home.lessonProgress.lastReceiveTime
    assert game.state.snapshot("media") == before
    with game.state.connect() as db:
        assert db.execute("SELECT response FROM profile_lesson_progress WHERE profile='media'").fetchone() == old_clock


@pytest.mark.parametrize("source_path", ("/api.Story/ListExtra", "/api.Home/Enter"))
def test_media_home_ignores_conflicting_captured_story_permissions_while_normal_keeps_them(game, tmp_path, source_path):
    # Exercise the real Gameplay.Home.Enter callback, rather than replacing its
    # handler. These are the only extra masters its empty home needs.
    for table, rows in {
        "Area": [{"id": "home-main", "type": 1, "order": 1, "questIds": []}],
        "HierarchyGrade": [{"id": "home-grade"}],
        "HierarchyDetailGrade": [{"id": "home-detail", "hierarchyGradeId": "home-grade",
                                   "requiredHierarchyPoint": 0, "requiredHierarchyRank": 0}],
    }.items():
        (game.master / (table + ".json")).write_text(json.dumps(rows))
    for index, unlocked in enumerate((True, False)):
        response = game.schema.response_type(source_path)()
        target = response.infos if source_path == "/api.Story/ListExtra" else response.extraStoryPartInfos
        part = target.add(id="extra-part", unlocked=unlocked)
        story = part.stories.add(id="extra", unlocked=unlocked)
        story.episodes.add(episode=1, unlocked=unlocked)
        source = tmp_path / ("conflicting-" + str(index) + ".pb")
        source.write_bytes(response.SerializeToString())
        # A fallback capture and an exact-request capture are both valid
        # FixtureStore entries, but their eligibility intentionally disagrees.
        request = None
        if index:
            request = tmp_path / "captured-request.pb"
            request.write_bytes(game.schema.request_type(source_path)().SerializeToString())
        import_response(source, tmp_path / "fixtures", game.schema, source_path, request=request)
    media = app(game, tmp_path, True)
    ordinary = app(game, tmp_path, False)
    assert len(media.fixtures.variants(source_path)) == 2
    before = game.state.snapshot("media")
    home = invoke(game, media, "/api.Home/Enter")
    expected = invoke(game, media, "/api.Story/ListExtra")
    assert home.currentMainAreaId == "home-main"
    assert home.extraStoryPartInfos == expected.infos
    assert game.state.snapshot("media") == before
    with pytest.raises(RpcFailure, match="variants disagree") as denied:
        ordinary._story_extra_fixture()
    assert denied.value.code == RpcCode.FAILED_PRECONDITION
    if source_path == "/api.Story/ListExtra":
        with pytest.raises(RpcFailure, match="variants disagree") as denied:
            invoke(game, ordinary, "/api.Home/Enter")
        assert denied.value.code == RpcCode.FAILED_PRECONDITION
    assert game.state.snapshot("media") == before
