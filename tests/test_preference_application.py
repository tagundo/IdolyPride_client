"""Preference mutations use real encrypted transport and persistent profile auth."""
from contextlib import contextmanager

import grpc
import pytest

from idoly_local import codec
from idoly_local.application import Application
from idoly_local.catalog import FixtureStore
from idoly_local.h2_server import create_server

from test_photo_names import game, schema, dump

PHOTO, LAYOUT, USER = "/api.Photo/Update", "/api.Profile/UpdateLayout", "/api.User/Get"


@contextmanager
def connected(game, directory):
    provider, state, token, _ = game
    app = Application(provider.schema, state, FixtureStore(directory, provider.schema), profile="player")
    server = create_server(app, port=0).start()
    try:
        with grpc.insecure_channel(f"127.0.0.1:{server.port}") as channel:
            grpc.channel_ready_future(channel).result(timeout=3)
            def invoke(path, *, raw=b"", auth=token):
                call = channel.unary_unary(path, request_serializer=codec.encode,
                                          response_deserializer=codec.decode)
                return call(raw, metadata=(("x-auth-token", auth),) if auth else (), timeout=5)
            yield invoke
    finally:
        server.stop()


def test_encrypted_preferences_persist_and_repeat_without_additional_mutations(game, tmp_path):
    provider, state = game[:2]
    photo = provider.schema.request_type(PHOTO)(photoId="owned-photo", name="保存写真").SerializeToString()
    layout = provider.schema.request_type(LAYOUT)(layoutType=4, informationType=1, colorType=2).SerializeToString()
    with connected(game, tmp_path / "fixtures") as invoke:
        changed_photo = provider.schema.response_type(PHOTO).FromString(invoke(PHOTO, raw=photo))
        assert changed_photo.commonResponse.updatedData.photos[0].name == "保存写真"
        changed_profile = provider.schema.response_type(LAYOUT).FromString(invoke(LAYOUT, raw=layout))
        assert changed_profile.commonResponse.updatedData.profile.layoutType == 4
        before = dump(state)
        assert invoke(PHOTO, raw=photo) == changed_photo.SerializeToString()
        assert invoke(LAYOUT, raw=layout) == changed_profile.SerializeToString()
        assert dump(state) == before
        assert invoke(USER) == state.snapshot("player")[0]
    with connected(game, tmp_path / "fixtures") as invoke:
        assert invoke(PHOTO, raw=photo) == changed_photo.SerializeToString()
        assert invoke(LAYOUT, raw=layout) == changed_profile.SerializeToString()
        assert dump(state) == before


def test_missing_or_other_profile_auth_cannot_mutate_preferences(game, tmp_path):
    provider, state = game[:2]
    before = dump(state)
    with connected(game, tmp_path / "fixtures") as invoke:
        for path in (PHOTO, LAYOUT):
            for token in ("", game[3]):
                with pytest.raises(grpc.RpcError) as denied:
                    invoke(path, auth=token)
                assert denied.value.code() == grpc.StatusCode.UNAUTHENTICATED
    assert dump(state) == before
