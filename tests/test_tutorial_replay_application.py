"""Recorded tutorial playback keeps transport, authentication and state boundaries."""
from contextlib import contextmanager
import json

import grpc
import pytest

from idoly_local import codec
from idoly_local.application import Application
from idoly_local.catalog import FixtureStore, import_response
from idoly_local.h2_server import create_server

from test_tutorial_replay import game, schema


PATH = "/api.Tutorial/StartQuest"
ASSETS = "/api.Quest/ListAsset"


def database(state):
    with state.connect() as connection:
        return list(connection.iterdump())


@contextmanager
def connected(game, fixture_directory):
    replays, state, master, _rows, token, _replay_directory = game
    application = Application(replays.schema, state, FixtureStore(fixture_directory, replays.schema),
                              profile=replays.profile, master_dir=master)
    server = create_server(application, port=0).start()
    try:
        with grpc.insecure_channel(f"127.0.0.1:{server.port}") as channel:
            grpc.channel_ready_future(channel).result(timeout=3)

            def invoke(path, message=None, *, authenticated=True, raw=None):
                call = channel.unary_unary(path, request_serializer=codec.encode,
                                           response_deserializer=codec.decode)
                plain = raw if raw is not None else message.SerializeToString()
                metadata = (("x-auth-token", token),) if authenticated else ()
                return call(plain, metadata=metadata, timeout=3)

            yield application, invoke
    finally:
        server.stop()


def user(game):
    replays, state = game[:2]
    return replays.schema.response_type("/api.User/Get").FromString(state.snapshot(replays.profile)[0])


def template(game, kind):
    return game[0].schema.response_type(PATH).FromString(
        (game[5] / ("tutorial-" + kind + ".pb")).read_bytes())


def main_quest(game):
    return next(row["id"] for row in json.loads((game[2] / "Quest.json").read_text())
                if row["id"] not in ("qt-tutorial-short", "qt-tutorial-full"))


@pytest.mark.parametrize("kind", ("short", "full"))
def test_encrypted_replay_joins_local_public_identity_and_preserves_canonical_data(game, tmp_path, kind):
    replays, state = game[:2]
    before = database(state)
    local = user(game)
    # Different identities make accidentally binding to the server ID visible.
    assert local.userPublic.publicUserId and local.userPublic.publicUserId != local.userPublic.serverUserId
    canonical = template(game, kind)
    request = replays.schema.request_type(PATH)(questId="qt-tutorial-" + kind)
    with connected(game, tmp_path / "fixtures") as (_application, invoke):
        with pytest.raises(grpc.RpcError) as rejected:
            invoke(PATH, request, authenticated=False)
        assert rejected.value.code() == grpc.StatusCode.UNAUTHENTICATED
        with pytest.raises(grpc.RpcError) as malformed:
            invoke(PATH, raw=b"\x80")
        assert malformed.value.code() == grpc.StatusCode.INVALID_ARGUMENT
        for _ in range(2):
            response = replays.schema.response_type(PATH).FromString(invoke(PATH, request))
            assert len(response.result.userInfos) == 1
            observed = response.result.userInfos[0]
            assert observed.userId == local.userPublic.publicUserId
            assert observed.name == local.user.name
            assert not response.result.detailLogId and not response.result.isDisplayDetailAvailable
            assert response.HasField("commonResponse") and not response.commonResponse.SerializeToString()
            assert [row.SerializeToString(deterministic=True) for row in response.rankPatterns] == [
                row.SerializeToString(deterministic=True) for row in canonical.rankPatterns]
            # Restore only display identity to compare the entire canonical
            # timeline, skill effects, cards, scores, indices and ordering.
            expected = type(response.result)()
            expected.CopyFrom(response.result)
            for actual, source in zip(expected.userInfos, canonical.result.userInfos):
                actual.userId, actual.name, actual.emblemId = source.userId, source.name, source.emblemId
            assert expected.SerializeToString(deterministic=True) == canonical.result.SerializeToString(deterministic=True)
    assert database(state) == before
    assert state.authenticated(game[4], replays.profile)


@pytest.mark.parametrize("kind,expected_count", (("short", 8), ("full", 9), ("main", 5)))
def test_encrypted_asset_prefetch_keeps_saved_unit_first_and_adds_only_canonical_resources(
        game, tmp_path, kind, expected_count):
    replays, state, master = game[:3]
    before = database(state)
    snapshot = user(game)
    cards = {row["id"]: row for row in json.loads((master / "Card.json").read_text())}
    positions = sorted((row for row in snapshot.deckPositions if row.number == 1), key=lambda row: row.position)
    selected = [(cards[row.cardId]["characterId"], row.costumeId, row.hairId) for row in positions]
    expected = list(selected)
    quest_id = main_quest(game) if kind == "main" else "qt-tutorial-" + kind
    if kind != "main":
        fixed = template(game, kind).result.userInfos[0].userDeck
        expected.extend((row.displayCharacterId, row.displayCostumeId, row.displayHairId) for row in fixed.cards)
        expected.extend((row.characterId, row.costumeId, row.hairId) for row in fixed.extraCharacterInfos)
    expected = list(dict.fromkeys(expected))
    assert len(selected) == 5 and len(expected) == expected_count
    request = replays.schema.request_type(ASSETS)(questId=quest_id, deckNumber=1,
        buddyDeckName=next(row.name for row in snapshot.decks if row.number == 1))
    with connected(game, tmp_path / "fixtures") as (_application, invoke):
        response = replays.schema.response_type(ASSETS).FromString(invoke(ASSETS, request))
        assert [(row.characterId, row.costumeId, row.hairId) for row in response.characterAssets] == expected
        assert not response.commonResponse.SerializeToString()
    assert database(state) == before


def test_authenticated_explicit_fixture_precedes_recorded_tutorial_handler(game, tmp_path):
    replays, state = game[:2]
    captured = replays.schema.response_type(PATH)()
    captured.commonResponse.SetInParent()
    captured.result.userInfos.add(userId="explicit-fixture-identity", name="Explicit fixture")
    source, fixtures = tmp_path / "explicit.pb", tmp_path / "fixtures"
    source.write_bytes(captured.SerializeToString())
    import_response(source, fixtures, replays.schema, PATH)
    before = database(state)
    # The fixed replay handler would reject this quest. The explicitly imported
    # response must retain the existing authenticated fixture precedence.
    request = replays.schema.request_type(PATH)(questId="explicit-fixture-only")
    with connected(game, fixtures) as (_application, invoke):
        with pytest.raises(grpc.RpcError) as rejected:
            invoke(PATH, request, authenticated=False)
        assert rejected.value.code() == grpc.StatusCode.UNAUTHENTICATED
        assert invoke(PATH, request) == source.read_bytes()
    assert database(state) == before


def test_recorded_tutorial_does_not_turn_unknown_or_general_battles_into_success(game, tmp_path):
    replays, state = game[:2]
    before = database(state)
    with connected(game, tmp_path / "fixtures") as (_application, invoke):
        for quest_id in ("missing-quest", main_quest(game)):
            request = replays.schema.request_type(PATH)(questId=quest_id)
            with pytest.raises(grpc.RpcError) as unsupported:
                invoke(PATH, request)
            assert unsupported.value.code() == grpc.StatusCode.UNIMPLEMENTED
        with pytest.raises(grpc.RpcError) as battle:
            invoke("/api.Quest/Start", raw=b"")
        assert battle.value.code() == grpc.StatusCode.UNIMPLEMENTED
    assert database(state) == before
