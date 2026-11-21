"""Owned emblem updates travel through the authenticated encrypted dispatcher."""
from contextlib import contextmanager
import grpc
import pytest

from idoly_local import codec
from idoly_local.application import Application
from idoly_local.catalog import FixtureStore
from idoly_local.h2_server import create_server
from test_profile_emblems import PATH, USER, dump, emblems, game, schema, snapshot


@contextmanager
def connected(game, emblems, directory):
    provider, state, token, _other = game
    app = Application(provider.schema, state, FixtureStore(directory, provider.schema),
                      profile="player", master_dir=emblems.catalog.directory)
    server = create_server(app, port=0).start()
    try:
        with grpc.insecure_channel(f"127.0.0.1:{server.port}") as channel:
            grpc.channel_ready_future(channel).result(timeout=3)
            def invoke(path, raw=b"", auth=token):
                call = channel.unary_unary(path, request_serializer=codec.encode,
                                           response_deserializer=codec.decode)
                return call(raw, metadata=(("x-auth-token", auth),) if auth else (), timeout=3)
            yield invoke
    finally:
        server.stop()


def test_emblem_dispatch_requires_own_session_and_retains_current_user_across_reconnect(
        game, emblems, tmp_path):
    provider, state, _token, other_token = game
    request = provider.schema.request_type(PATH)(emblemId="emblem-b").SerializeToString()
    before = dump(state)
    with connected(game, emblems, tmp_path / "fixtures") as invoke:
        for auth in (None, "invalid", other_token):
            with pytest.raises(grpc.RpcError) as failure:
                invoke(PATH, request, auth)
            assert failure.value.code() == grpc.StatusCode.UNAUTHENTICATED
        assert dump(state) == before
        with pytest.raises(grpc.RpcError) as failure:
            invoke(PATH, b"\x0a\x80")
        assert failure.value.code() == grpc.StatusCode.INVALID_ARGUMENT
        assert dump(state) == before
        raw = invoke(PATH, request)
        result = provider.schema.response_type(PATH).FromString(raw)
        assert result.commonResponse.updatedData.user == snapshot(game).user
        assert snapshot(game).user.emblemId == "emblem-b"
        after = dump(state)
        assert invoke(PATH, request) == raw and dump(state) == after
    with connected(game, emblems, tmp_path / "other-fixtures") as invoke:
        assert invoke(USER) == snapshot(game).SerializeToString()
        assert invoke(PATH, request) == raw
    assert dump(state) == after
