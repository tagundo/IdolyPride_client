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


def app(game, root, media):
    return Application(game.schema, game.state, FixtureStore(root / "fixtures", game.schema),
        profile="media", master_dir=game.master, media_mode=media,
        photo_scene_access=PhotoSceneAccess())


def invoke(game, application, path, *, authenticated=True):
    context = Context((("x-auth-token", game.token),) if authenticated else ())
    request = game.schema.request_type(path)().SerializeToString()
    raw = application.handle(path, codec.encode(request), context)
    return game.schema.response_type(path).FromString(raw)


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
