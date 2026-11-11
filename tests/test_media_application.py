"""Media routes cannot be shadowed by captured ordinary account responses."""
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
