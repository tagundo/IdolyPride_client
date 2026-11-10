"""Name updates pass through authentication and the encrypted HTTP/2 path."""
from contextlib import contextmanager

import grpc
import pytest

from idoly_local import codec
from idoly_local.application import Application
from idoly_local.catalog import FixtureStore, import_response
from idoly_local.h2_server import create_server

from test_profile_names import PATH, USER, dump, game, protected, schema, snapshot


@contextmanager
def connected(game, directory):
    provider, state, token, other_token = game
    application = Application(provider.schema, state, FixtureStore(directory, provider.schema), profile="player")
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


def test_actual_encrypted_request_requires_own_session_and_persists_authoritative_user(game, tmp_path):
    provider, state, token, other_token = game
    raw = provider.schema.request_type(PATH)(name="新しい名前").SerializeToString()
    expected = snapshot(game)
    expected.user.name = "新しい名前"
    kept, before = protected(state), dump(state)
    with connected(game, tmp_path / "fixtures") as invoke:
        for auth in (None, "not-a-session", other_token):
            with pytest.raises(grpc.RpcError) as error:
                invoke(PATH, raw, auth)
            assert error.value.code() == grpc.StatusCode.UNAUTHENTICATED
        for invalid in (b"\x0a\x80", b"\x0a\x01\xff",
                        provider.schema.request_type(PATH)(name="😀" * 6).SerializeToString()):
            with pytest.raises(grpc.RpcError) as error:
                invoke(PATH, invalid)
            assert error.value.code() == grpc.StatusCode.INVALID_ARGUMENT
        assert dump(state) == before
        result = provider.schema.response_type(PATH).FromString(invoke(PATH, raw))
        assert result.commonResponse.updatedData.user == expected.user
        assert invoke(USER) == expected.SerializeToString()
        after = dump(state)
        assert provider.schema.response_type(PATH).FromString(invoke(PATH, raw)) == result
        assert dump(state) == after
    assert protected(state) == kept
    assert state.authenticated(token, "player") and state.authenticated(other_token, "other")


def test_explicit_fixture_keeps_precedence_without_mutating_account(game, tmp_path):
    provider, state = game[:2]
    captured = provider.schema.response_type(PATH)()
    captured.commonResponse.updatedData.user.name = "Captured"
    source, directory = tmp_path / "response.pb", tmp_path / "fixtures"
    source.write_bytes(captured.SerializeToString())
    import_response(source, directory, provider.schema, PATH)
    before = dump(state)
    with connected(game, directory) as invoke:
        with pytest.raises(grpc.RpcError) as anonymous:
            invoke(PATH, auth=None)
        assert anonymous.value.code() == grpc.StatusCode.UNAUTHENTICATED
        assert invoke(PATH) == source.read_bytes()
    assert dump(state) == before
