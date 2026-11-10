"""Profile entry and manager-name updates share the real encrypted application."""
from contextlib import contextmanager

import grpc
import pytest

from idoly_local import codec
from idoly_local.application import Application
from idoly_local.catalog import FixtureStore, import_response
from idoly_local.h2_server import create_server

from test_profile_names import PATH as NAME, USER, dump, protected
from test_profile_top import PATH, game, schema, top


@contextmanager
def connected(game, top, directory):
    provider, master = top[:2]
    application = Application(provider.schema, game[1], FixtureStore(directory, provider.schema),
                              profile="player", master_dir=master)
    server = create_server(application, port=0).start()
    try:
        with grpc.insecure_channel(f"127.0.0.1:{server.port}") as channel:
            grpc.channel_ready_future(channel).result(timeout=3)
            def invoke(path, raw=b"", auth=game[2]):
                call = channel.unary_unary(path, request_serializer=codec.encode, response_deserializer=codec.decode)
                metadata = (("x-auth-token", auth),) if auth else ()
                return call(raw, metadata=metadata, timeout=3)
            yield invoke
    finally:
        server.stop()


def test_authenticated_profile_top_then_name_update_retains_header_and_session(game, top, tmp_path):
    provider = top[0]
    before, kept = dump(game[1]), protected(game[1])
    with connected(game, top, tmp_path / "fixtures") as invoke:
        for token in (None, "invalid", game[3]):
            with pytest.raises(grpc.RpcError) as error:
                invoke(PATH, auth=token)
            assert error.value.code() == grpc.StatusCode.UNAUTHENTICATED
        with pytest.raises(grpc.RpcError) as malformed:
            invoke(PATH, b"\x0a\x80")
        assert malformed.value.code() == grpc.StatusCode.INVALID_ARGUMENT
        raw = invoke(PATH)
        result = provider.schema.response_type(PATH).FromString(raw)
        assert result.hierarchyCurrentDetailGradeId == "detail-low"
        assert result.hierarchyCurrentRank == 0 and not result.friendProfiles
        assert dump(game[1]) == before
        renamed = provider.schema.response_type(NAME).FromString(invoke(NAME,
            provider.schema.request_type(NAME)(name="管理者").SerializeToString()))
        assert renamed.commonResponse.updatedData.user.name == "管理者"
        changed = dump(game[1])
        assert invoke(PATH) == raw
        assert provider.schema.response_type(USER).FromString(invoke(USER)).user.name == "管理者"
        assert dump(game[1]) == changed
    assert protected(game[1]) == kept


def test_captured_profile_top_keeps_authentication_and_fixture_precedence(game, top, tmp_path):
    provider, state = top[0], game[1]
    captured = provider.schema.response_type(PATH)(hierarchyCurrentDetailGradeId="captured-grade", hierarchyCurrentRank=123)
    captured.commonResponse.SetInParent()
    source, directory = tmp_path / "response.pb", tmp_path / "fixtures"
    source.write_bytes(captured.SerializeToString())
    import_response(source, directory, provider.schema, PATH)
    before = dump(state)
    with connected(game, top, directory) as invoke:
        with pytest.raises(grpc.RpcError) as anonymous:
            invoke(PATH, auth=None)
        assert anonymous.value.code() == grpc.StatusCode.UNAUTHENTICATED
        assert invoke(PATH) == source.read_bytes()
    assert dump(state) == before
