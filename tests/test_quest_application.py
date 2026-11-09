"""Main-live reads through the shared app's authenticated encrypted transport."""
import grpc
import pytest

from idoly_local import codec
from idoly_local.application import Application
from idoly_local.catalog import FixtureStore, import_response
from idoly_local.h2_server import create_server

from test_quest import game, schema


def test_main_live_reads_over_encrypted_http2_preserve_profile(game, tmp_path):
    quest, state, directory, _, token = game
    before = state.snapshot("player")
    application = Application(quest.schema, state, FixtureStore(tmp_path / "fixtures", quest.schema),
                              profile="player", master_dir=directory)
    server = create_server(application, port=0).start()
    try:
        with grpc.insecure_channel(f"127.0.0.1:{server.port}") as channel:
            grpc.channel_ready_future(channel).result(timeout=3)
            def request(path, *, authenticated=True, payload=b""):
                call = channel.unary_unary(path, request_serializer=codec.encode,
                                          response_deserializer=codec.decode)
                metadata = (("x-auth-token", token),) if authenticated else ()
                raw = call(payload, metadata=metadata, timeout=3)
                return quest.schema.response_type(path).FromString(raw)

            with pytest.raises(grpc.RpcError) as failure:
                request("/api.Quest/Top", authenticated=False)
            assert failure.value.code() == grpc.StatusCode.UNAUTHENTICATED
            with pytest.raises(grpc.RpcError) as failure:
                request("/api.Quest/Top", payload=b"\x80")
            assert failure.value.code() == grpc.StatusCode.INVALID_ARGUMENT
            top = request("/api.Quest/Top")
            main = request("/api.Quest/ListMain")
            assert [row.SerializeToString() for row in top.mainAreaGroups] == [
                row.SerializeToString() for row in main.areaGroups]
            assert top.mainAreaGroups[0].areas[0].quests[0].isPlayable
            assert top.HasField("pvpInfo") and top.HasField("hierarchyNotiInfo")
            assert state.snapshot("player") == before
            assert state.authenticated(token, "player")
    finally:
        server.stop()


def test_imported_main_live_response_keeps_fixture_precedence(game, tmp_path):
    quest, state, directory, _, token = game
    path = "/api.Quest/Top"
    captured = quest.schema.response_type(path)()
    captured.mainAreaGroups.add(areaGroupId="captured-group")
    source = tmp_path / "captured.pb"
    source.write_bytes(captured.SerializeToString())
    fixtures = tmp_path / "fixtures"
    import_response(source, fixtures, quest.schema, path)
    application = Application(quest.schema, state, FixtureStore(fixtures, quest.schema),
                              profile="player", master_dir=directory)

    class Context:
        def invocation_metadata(self):
            return (("x-auth-token", token),)
        def abort(self, code, detail):
            pytest.fail("Unexpected application failure: " + str(code))

    assert application.handle(path, codec.encode(b""), Context()) == captured.SerializeToString()
