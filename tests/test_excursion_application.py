"""Outing restoration reaches the encrypted, authenticated gallery boundary."""
import pytest

from idoly_local import codec
from idoly_local.application import Application
from idoly_local.catalog import FixtureStore
from idoly_local.h2_server import Context
from idoly_local.photo_shooting import PhotoSceneAccess
from idoly_local.rpc import RpcCode, RpcFailure
from test_excursion import game, schema, snapshot, dump, _LIST, _START, _WATCH, _FINISH, _CHECK


def app(game, *, media=True):
    provider, state, master, _tables, _token = game
    return Application(provider.schema, state, FixtureStore(master.parent / "fixtures", provider.schema),
        profile="gallery" if media else "ordinary", master_dir=master,
        media_mode=media, photo_scene_access=PhotoSceneAccess())


def invoke(game, application, path, values, *, token=None):
    raw = application.schema.request_type(path)(**values).SerializeToString()
    context = Context((("x-auth-token", token),) if token else ())
    result = application.handle(path, codec.encode(raw), context)
    return application.schema.response_type(path).FromString(result)


def test_full_outing_flow_uses_live_gallery_state_and_retains_replay_ack(game):
    application = app(game)
    token = game[4]
    before = snapshot(game)
    ordinary = game[1].snapshot("ordinary")
    listed = invoke(game, application, _LIST, {"characterId": "char-a"}, token=token)
    assert list(listed.excursionPlaceIds) == ["park", "pool"]
    invoke(game, application, _START, {"characterId": "char-a", "excursionPlaceId": "park"}, token=token)
    watched = invoke(game, application, _WATCH,
        {"characterId": "char-a", "excursionPlaceId": "park", "number": 1}, token=token)
    assert watched.commonResponse.updatedData.excursionGazeReactions[0].gazeReactionNumber == 1
    invoke(game, application, _CHECK,
        {"characterId": "char-a", "excursionPlaceId": "park", "costumeId": "cos-a", "hairId": "hair-a"},
        token=token)
    values = {"gazeReactionNumbers": [1], "costumeId": "cos-a", "hairId": "hair-a"}
    finished = invoke(game, application, _FINISH, values, token=token)
    saved = dump(game)
    assert not finished.rewardResults
    assert invoke(game, app(game), _FINISH, values, token=token) == finished
    assert dump(game) == saved
    assert snapshot(game).balance == before.balance
    assert list(snapshot(game).items) == list(before.items)
    assert game[1].snapshot("ordinary") == ordinary


@pytest.mark.parametrize("path,values", (
    (_LIST, {"characterId": "char-a"}),
    (_START, {"characterId": "char-a", "excursionPlaceId": "park"}),
    (_WATCH, {"characterId": "char-a", "excursionPlaceId": "park", "number": 1}),
    (_FINISH, {"costumeId": "cos-a", "hairId": "hair-a"}),
    (_CHECK, {"characterId": "char-a", "excursionPlaceId": "park", "costumeId": "cos-a", "hairId": "hair-a"}),
))
def test_outing_calls_require_authentication_before_any_session_or_snapshot_write(game, path, values):
    before = dump(game)
    with pytest.raises(RpcFailure) as error:
        invoke(game, app(game), path, values)
    assert error.value.code == RpcCode.UNAUTHENTICATED
    assert dump(game) == before


def test_ordinary_profile_does_not_gain_gallery_outing_behaviour(game):
    token, _ = game[1].login("ordinary")
    before = dump(game)
    with pytest.raises(RpcFailure) as error:
        invoke(game, app(game, media=False), _LIST, {"characterId": "char-a"}, token=token)
    assert error.value.code == RpcCode.UNIMPLEMENTED
    assert dump(game) == before
