"""Owned outfits are persisted through the actual encrypted application API."""
from contextlib import contextmanager

import grpc
import pytest

from idoly_local import codec
from idoly_local.application import Application
from idoly_local.catalog import FixtureStore, import_response
from idoly_local.h2_server import create_server

from test_appearance import BULK, CHECK, HAIR, LIVE, ROUTES, SET, USER, dump, game, protected, schema, snapshot


def values(path):
    return ({"costumeId": "cos-a1", "hairId": "hair-a1"} if path in (SET, LIVE) else
            {"costumeId": "cos-a1"} if path == CHECK else
            {"hairId": "hair-a1"} if path == HAIR else
            {"costumeIds": ["cos-a1"], "hairIds": ["hair-a1"]})


@contextmanager
def connected(game, directory):
    provider, state, master, _rows, token, _other_token = game
    application = Application(provider.schema, state, FixtureStore(directory, provider.schema),
                              profile="player", master_dir=master)
    server = create_server(application, port=0).start()
    try:
        with grpc.insecure_channel(f"127.0.0.1:{server.port}") as channel:
            grpc.channel_ready_future(channel).result(timeout=3)

            def invoke(path, *, raw=b"", authenticated=True):
                call = channel.unary_unary(path, request_serializer=codec.encode,
                                           response_deserializer=codec.decode)
                metadata = (("x-auth-token", token),) if authenticated else ()
                return call(raw, metadata=metadata, timeout=3)

            yield invoke
    finally:
        server.stop()


@pytest.mark.parametrize("path", ROUTES)
def test_all_five_apis_require_auth_validate_payload_and_persist_only_the_owned_change(game, tmp_path, path):
    provider, state = game[:2]
    raw = provider.schema.request_type(path)(**values(path)).SerializeToString()
    expected = snapshot(game)
    if path in (SET, LIVE):
        prefix = "favorite" if path == SET else "live"
        setattr(expected.characters[0], prefix + "CostumeId", "cos-a1")
        setattr(expected.characters[0], prefix + "HairId", "hair-a1")
    if path in (CHECK, BULK):
        expected.costumes[1].checked = True
    if path in (HAIR, BULK):
        expected.hairs[1].checked = True
    kept, before = protected(state), dump(state)
    with connected(game, tmp_path / "fixtures") as invoke:
        with pytest.raises(grpc.RpcError) as anonymous:
            invoke(path, raw=raw, authenticated=False)
        assert anonymous.value.code() == grpc.StatusCode.UNAUTHENTICATED
        with pytest.raises(grpc.RpcError) as malformed:
            invoke(path, raw=b"\x0a\x80")
        assert malformed.value.code() == grpc.StatusCode.INVALID_ARGUMENT
        assert dump(state) == before
        response = provider.schema.response_type(path).FromString(invoke(path, raw=raw))
        assert response.commonResponse.HasField("updatedData")
        assert response.commonResponse.HasField("deletedData")
        assert not response.commonResponse.deletedData.ListFields()
        assert invoke(USER) == expected.SerializeToString()
        after = dump(state)
        assert provider.schema.response_type(path).FromString(invoke(path, raw=raw)) == response
        assert dump(state) == after
    assert protected(state) == kept
    assert state.authenticated(game[4], "player") and state.authenticated(game[5], "other")


@pytest.mark.parametrize("path,request_values,code", (
    (SET, {"costumeId": "cos-unowned", "hairId": "hair-a1"}, grpc.StatusCode.PERMISSION_DENIED),
    (LIVE, {"costumeId": "cos-a1", "hairId": "hair-b0"}, grpc.StatusCode.INVALID_ARGUMENT),
    (BULK, {"costumeIds": ["cos-a1"], "hairIds": ["hair-a1", "hair-unowned"]}, grpc.StatusCode.PERMISSION_DENIED),
))
def test_invalid_outfits_and_mixed_bulk_batches_leave_the_whole_database_unchanged(
        game, tmp_path, path, request_values, code):
    before = dump(game[1])
    raw = game[0].schema.request_type(path)(**request_values).SerializeToString()
    with connected(game, tmp_path / "fixtures") as invoke:
        with pytest.raises(grpc.RpcError) as rejected:
            invoke(path, raw=raw)
        assert rejected.value.code() == code
    assert dump(game[1]) == before


def test_authenticated_imported_response_keeps_existing_fixture_precedence(game, tmp_path):
    provider, state = game[:2]
    captured = provider.schema.response_type(SET)()
    captured.commonResponse.updatedData.user.name = "Explicit private fixture"
    source, directory = tmp_path / "response.pb", tmp_path / "fixtures"
    source.write_bytes(captured.SerializeToString())
    import_response(source, directory, provider.schema, SET)
    # Without the fixture, this request refers to an unowned costume and fails.
    raw = provider.schema.request_type(SET)(costumeId="cos-unowned", hairId="hair-a1").SerializeToString()
    before = dump(state)
    with connected(game, directory) as invoke:
        with pytest.raises(grpc.RpcError) as anonymous:
            invoke(SET, raw=raw, authenticated=False)
        assert anonymous.value.code() == grpc.StatusCode.UNAUTHENTICATED
        assert invoke(SET, raw=raw) == source.read_bytes()
    assert dump(state) == before


def test_empty_bulk_is_authenticated_and_never_updates_a_snapshot(game, tmp_path):
    provider, state = game[:2]
    before = dump(state)
    with connected(game, tmp_path / "fixtures") as invoke:
        with pytest.raises(grpc.RpcError) as anonymous:
            invoke(BULK, authenticated=False)
        assert anonymous.value.code() == grpc.StatusCode.UNAUTHENTICATED
        for _ in range(2):
            response = provider.schema.response_type(BULK).FromString(invoke(BULK))
            assert response.commonResponse.HasField("updatedData")
            assert response.commonResponse.HasField("deletedData")
            assert not response.commonResponse.updatedData.ListFields()
            assert not response.commonResponse.deletedData.ListFields()
    assert dump(state) == before
