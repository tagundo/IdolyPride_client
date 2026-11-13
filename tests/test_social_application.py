"""Authenticated local list contracts through encrypted unary HTTP/2."""
import grpc
import pytest

from idoly_local import codec
from idoly_local.application import Application
from idoly_local.catalog import FixtureStore
from idoly_local.h2_server import create_server
from idoly_local.state import State

from test_social import ROUTES, schema


def database(state):
    with state.connect() as db:
        return tuple(db.iterdump())


def test_six_local_lists_require_auth_and_validate_requests_over_real_http2(schema, tmp_path):
    state = State(tmp_path / "profiles.sqlite")
    state.save_snapshot("local", b"untouched local snapshot", schema.fingerprint, starter_version=4)
    token, _ = state.login("local")
    fixtures = FixtureStore(tmp_path / "fixtures", schema)
    application = Application(schema, state, fixtures, profile="local")
    before = database(state)
    server = create_server(application, port=0).start()
    try:
        with grpc.insecure_channel(f"127.0.0.1:{server.port}") as channel:
            grpc.channel_ready_future(channel).result(timeout=3)
            metadata = (("x-auth-token", token),)
            for path in ROUTES:
                request = schema.request_type(path)()
                if path == "/api.Gift/List":
                    request.offset, request.sortType = 100, 1
                    request.filters.append(999)
                invoke = channel.unary_unary(path, request_serializer=codec.encode,
                                              response_deserializer=codec.decode)
                with pytest.raises(grpc.RpcError) as error:
                    invoke(request.SerializeToString(), timeout=3)
                assert error.value.code() == grpc.StatusCode.UNAUTHENTICATED
                result = schema.response_type(path).FromString(
                    invoke(request.SerializeToString(), metadata=metadata, timeout=3))
                assert result.HasField("commonResponse")
                assert not result.commonResponse.HasField("updatedData")
                assert not result.commonResponse.HasField("deletedData")
                assert result.commonResponse.SerializeToString() == b""
                assert not (result.gifts if path.startswith("/api.Gift/") else result.profiles)
                if path == "/api.Gift/List":
                    assert result.count == 0 and result.hasNext is False
                assert schema.response_type(path).FromString(invoke(
                    request.SerializeToString(), metadata=metadata, timeout=3)) == result

            gift = channel.unary_unary("/api.Gift/List", request_serializer=codec.encode,
                                       response_deserializer=codec.decode)
            for request in (schema.request_type("/api.Gift/List")(offset=-1),
                            schema.request_type("/api.Gift/List")(sortType=99)):
                with pytest.raises(grpc.RpcError) as error:
                    gift(request.SerializeToString(), metadata=metadata, timeout=3)
                assert error.value.code() == grpc.StatusCode.INVALID_ARGUMENT
            with pytest.raises(grpc.RpcError) as error:
                gift(b"\x0a\x80", metadata=metadata, timeout=3)
            assert error.value.code() == grpc.StatusCode.INVALID_ARGUMENT
            assert database(state) == before
            assert state.authenticated(token, "local")
    finally:
        server.stop()
