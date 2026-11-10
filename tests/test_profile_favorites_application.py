"""Favorite selection travels through authenticated encrypted HTTP/2 dispatch."""
from contextlib import contextmanager

import grpc
import pytest

from idoly_local import codec
from idoly_local.application import Application
from idoly_local.catalog import FixtureStore, import_response
from idoly_local.h2_server import create_server
from test_profile_favorites import PATH, USER, dump, favorites, game, schema, snapshot


@contextmanager
def connected(game, favorites, directory):
    provider, state, token, _ = game
    application = Application(provider.schema, state, FixtureStore(directory, provider.schema), profile="player",
                              master_dir=favorites.catalog.directory)
    server = create_server(application, port=0).start()
    try:
        with grpc.insecure_channel(f"127.0.0.1:{server.port}") as channel:
            grpc.channel_ready_future(channel).result(timeout=3)
            def invoke(path, raw=b"", auth=token):
                call = channel.unary_unary(path, request_serializer=codec.encode, response_deserializer=codec.decode)
                metadata = (("x-auth-token", auth),) if auth else ()
                return call(raw, metadata=metadata, timeout=3)
            yield invoke
    finally:
        server.stop()


def test_ordered_favorites_require_own_session_and_persist_authoritative_profile(game, favorites, tmp_path):
    provider, state, token, other_token = game
    raw = provider.schema.request_type(PATH)(favoriteCharacterIds=["character-c", "character-a"]).SerializeToString()
    before = dump(state)
    with connected(game, favorites, tmp_path / "fixtures") as invoke:
        for auth in (None, "invalid", other_token):
            with pytest.raises(grpc.RpcError) as failure:
                invoke(PATH, raw, auth)
            assert failure.value.code() == grpc.StatusCode.UNAUTHENTICATED
        for invalid in (b"\x0a\x80", provider.schema.request_type(PATH)(favoriteCharacterIds=["character-a"] * 2).SerializeToString()):
            with pytest.raises(grpc.RpcError) as failure:
                invoke(PATH, invalid)
            assert failure.value.code() == grpc.StatusCode.INVALID_ARGUMENT
        assert dump(state) == before
        result = provider.schema.response_type(PATH).FromString(invoke(PATH, raw))
        assert list(result.commonResponse.updatedData.profile.favoriteCharacterIds) == ["character-c", "character-a"]
        assert invoke(USER) == snapshot(game).SerializeToString()
        after = dump(state)
        assert provider.schema.response_type(PATH).FromString(invoke(PATH, raw)) == result
        assert dump(state) == after
        cleared = provider.schema.response_type(PATH).FromString(invoke(PATH))
        assert not cleared.commonResponse.updatedData.profile.favoriteCharacterIds
        assert not snapshot(game).profile.favoriteCharacterIds


def test_explicit_fixture_still_precedes_handler_without_bypassing_auth(game, favorites, tmp_path):
    provider, state = game[:2]
    captured = provider.schema.response_type(PATH)()
    captured.commonResponse.updatedData.profile.favoriteCharacterIds.append("fixture-only-character")
    source, directory = tmp_path / "favorites.pb", tmp_path / "fixtures"
    source.write_bytes(captured.SerializeToString())
    import_response(source, directory, provider.schema, PATH)
    before = dump(state)
    with connected(game, favorites, directory) as invoke:
        with pytest.raises(grpc.RpcError) as failure:
            invoke(PATH, auth=None)
        assert failure.value.code() == grpc.StatusCode.UNAUTHENTICATED
        assert invoke(PATH) == source.read_bytes()
    assert dump(state) == before
