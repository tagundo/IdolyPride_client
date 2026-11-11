"""Preserved VENUS reads cross the actual encrypted HTTP/2 application route."""
from contextlib import contextmanager
import json

import grpc
import pytest

from idoly_local import codec
from idoly_local.application import Application
from idoly_local.catalog import FixtureStore, import_response
from idoly_local.h2_server import create_server

from test_pvp import game, schema
from test_live_assets import game as asset_game


@contextmanager
def connected(game, directory):
    app = Application(game.schema, game.state, FixtureStore(directory, game.schema),
                      profile="player", master_dir=game.master)
    server = create_server(app, port=0).start()
    try:
        with grpc.insecure_channel(f"127.0.0.1:{server.port}") as channel:
            grpc.channel_ready_future(channel).result(timeout=3)
            def invoke(path, request=b"", *, authenticated=True):
                call = channel.unary_unary(path, request_serializer=codec.encode,
                                          response_deserializer=codec.decode)
                headers = (("x-auth-token", game.token),) if authenticated else ()
                return call(request, metadata=headers, timeout=5)
            yield app, invoke
    finally:
        server.stop()


def dump(game):
    with game.state.connect() as db:
        return tuple(db.iterdump())


def test_private_venus_read_is_authenticated_and_does_not_reapply_official_deltas(game, tmp_path):
    before = dump(game)
    with connected(game, tmp_path / "fixtures") as (_, invoke):
        with pytest.raises(grpc.RpcError) as denied:
            invoke("/api.Pvp/Top", authenticated=False)
        assert denied.value.code() == grpc.StatusCode.UNAUTHENTICATED
        raw = invoke("/api.Pvp/Top")
        response = game.schema.response_type("/api.Pvp/Top").FromString(raw)
        assert response.topResult.pvpSeason.id == game.top.topResult.pvpSeason.id
        assert not response.commonResponse.updatedData.HasField("balance")
        request = game.schema.request_type("/api.Pvp/ListAsset")(
            pvpSeasonId=response.topResult.pvpSeason.id,
            opponentId=response.opponentInfos[0].opponentId, deckNumber=1)
        assets = game.schema.response_type("/api.Pvp/ListAsset").FromString(
            invoke("/api.Pvp/ListAsset", request.SerializeToString()))
        assert len(assets.characterAssets) == len(assets.opponentCharacterAssets) == 5
        assert not assets.commonResponse.updatedData.HasField("user")
        # Starting a battle requires a settlement implementation, not a cached result.
        with pytest.raises(grpc.RpcError) as unsupported:
            invoke("/api.Pvp/Start")
        assert unsupported.value.code() == grpc.StatusCode.UNIMPLEMENTED
        assert invoke("/api.User/Get") == game.state.snapshot("player")[0]
    assert dump(game) == before


def test_exact_response_fixture_retains_priority_over_catalog_provider(game, tmp_path):
    source = tmp_path / "top.pb"
    captured = game.schema.response_type("/api.Pvp/Top")()
    captured.topResult.rank = 12345
    source.write_bytes(captured.SerializeToString())
    directory = tmp_path / "fixtures"
    import_response(source, directory, game.schema, "/api.Pvp/Top")
    before = dump(game)
    with connected(game, directory) as (_, invoke):
        assert invoke("/api.Pvp/Top") == source.read_bytes()
    assert dump(game) == before


def test_missing_private_catalog_returns_precondition_after_authentication(game, tmp_path):
    game.path.unlink()
    before = dump(game)
    with connected(game, tmp_path / "fixtures") as (_, invoke):
        with pytest.raises(grpc.RpcError) as missing:
            invoke("/api.Pvp/Top")
        assert missing.value.code() == grpc.StatusCode.FAILED_PRECONDITION
    assert dump(game) == before


def test_top_only_venus_reads_cross_authenticated_transport_without_fabricating_appearance(game, tmp_path):
    game.data["responses"] = [row for row in game.data["responses"] if row["method"] != "/api.Pvp/ListAsset"]
    game.path.write_text(json.dumps(game.data))
    snapshot = game.state.snapshot("player")[0]
    before = dump(game)
    with connected(game, tmp_path / "fixtures") as (_, invoke):
        top = game.schema.response_type("/api.Pvp/Top").FromString(invoke("/api.Pvp/Top"))
        assert not top.commonResponse.ListFields()
        request = game.schema.request_type("/api.Pvp/ListOpponent")(pvpSeasonId=top.topResult.pvpSeason.id)
        opponents = game.schema.response_type("/api.Pvp/ListOpponent").FromString(
            invoke("/api.Pvp/ListOpponent", request.SerializeToString()))
        assert opponents.opponentInfos == top.opponentInfos and not opponents.commonResponse.ListFields()
        query = game.schema.request_type("/api.Pvp/ListAsset")(pvpSeasonId=top.topResult.pvpSeason.id,
            opponentId=top.opponentInfos[0].opponentId, deckNumber=1)
        with pytest.raises(grpc.RpcError) as missing:
            invoke("/api.Pvp/ListAsset", query.SerializeToString())
        assert missing.value.code() == grpc.StatusCode.FAILED_PRECONDITION
        assert missing.value.details() == "VENUS capture unavailable: opponent_appearance_missing"
        assert invoke("/api.User/Get") == snapshot
    assert game.state.snapshot("player")[0] == snapshot and dump(game) == before


def test_photo_creation_without_preserved_scene_cannot_consume_film_or_mutate_account(game, tmp_path):
    before = dump(game)
    with connected(game, tmp_path / "fixtures") as (_, invoke):
        for path in ("/api.Photo/ListShooting", "/api.Photo/CreateShootings"):
            with pytest.raises(grpc.RpcError) as missing:
                invoke(path)
            assert missing.value.code() == grpc.StatusCode.FAILED_PRECONDITION
    assert dump(game) == before
