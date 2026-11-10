"""Live appearance reads retain authentication and encrypted HTTP/2 behavior."""
import grpc
import pytest

from idoly_local import codec
from idoly_local.application import Application
from idoly_local.catalog import FixtureStore, import_response
from idoly_local.h2_server import create_server

from test_live_assets import game, schema


PATH = "/api.Quest/ListAsset"


def database(state):
    with state.connect() as db:
        return list(db.iterdump())


def test_live_asset_read_over_encrypted_http2_preserves_entire_database(game, tmp_path):
    quest, state, directory, rows, token = game
    before = database(state)
    user = quest.schema.response_type("/api.User/Get").FromString(state.snapshot(quest.profile)[0])
    cards = {row["id"]: row for row in rows["Card"]}
    positions = sorted((row for row in user.deckPositions if row.number == 1), key=lambda row: row.position)
    expected = [(cards[row.cardId]["characterId"], row.costumeId, row.hairId) for row in positions]
    assert len(expected) == 5
    request = quest.schema.request_type(PATH)(questId=rows["Quest"][0]["id"], deckNumber=1,
                                            buddyDeckName="Local deck")
    application = Application(quest.schema, state, FixtureStore(tmp_path / "fixtures", quest.schema),
                              profile=quest.profile, master_dir=directory)
    server = create_server(application, port=0).start()
    try:
        with grpc.insecure_channel(f"127.0.0.1:{server.port}") as channel:
            grpc.channel_ready_future(channel).result(timeout=3)
            call = channel.unary_unary(PATH, request_serializer=codec.encode, response_deserializer=codec.decode)
            metadata = (("x-auth-token", token),)
            with pytest.raises(grpc.RpcError) as failure:
                call(request.SerializeToString(), timeout=3)
            assert failure.value.code() == grpc.StatusCode.UNAUTHENTICATED
            with pytest.raises(grpc.RpcError) as failure:
                call(b"\x80", metadata=metadata, timeout=3)
            assert failure.value.code() == grpc.StatusCode.INVALID_ARGUMENT
            for _ in range(2):
                raw = call(request.SerializeToString(), metadata=metadata, timeout=3)
                result = quest.schema.response_type(PATH).FromString(raw)
                assert [(row.characterId, row.costumeId, row.hairId) for row in result.characterAssets] == expected
                assert result.HasField("commonResponse") and not result.commonResponse.SerializeToString()
            request.userBuddyDeckPositions.add(position=1, buddyUserId="unimplemented-rental")
            with pytest.raises(grpc.RpcError) as failure:
                call(request.SerializeToString(), metadata=metadata, timeout=3)
            assert failure.value.code() == grpc.StatusCode.UNIMPLEMENTED
            assert database(state) == before
            assert state.authenticated(token, quest.profile)
    finally:
        server.stop()


def test_live_asset_capture_retains_fixture_precedence(game, tmp_path):
    quest, state, directory, rows, token = game
    captured = quest.schema.response_type(PATH)()
    captured.commonResponse.SetInParent()
    captured.characterAssets.add(characterId="captured-character", costumeId="captured-costume",
                                  hairId="captured-hair")
    source = tmp_path / "captured.pb"
    source.write_bytes(captured.SerializeToString())
    fixtures = tmp_path / "fixtures"
    import_response(source, fixtures, quest.schema, PATH)
    before = database(state)
    application = Application(quest.schema, state, FixtureStore(fixtures, quest.schema),
                              profile=quest.profile, master_dir=directory)

    class Context:
        def invocation_metadata(self):
            return (("x-auth-token", token),)

        def abort(self, code, detail):
            pytest.fail("Unexpected application failure: " + str(code))

    request = quest.schema.request_type(PATH)(questId=rows["Quest"][0]["id"], deckNumber=1)
    assert application.handle(PATH, codec.encode(request.SerializeToString()), Context()) == captured.SerializeToString()
    assert database(state) == before


def test_real_client_preparation_saves_existing_unit_without_starting_battle(game, tmp_path):
    quest, state, directory, rows, token = game
    if "/api.Deck/Save" not in quest.schema.methods:
        pytest.skip("The minimal resource-only descriptor omits Deck.Save; the recovered client schema covers it")
    user_type = quest.schema.response_type("/api.User/Get")
    before = user_type.FromString(state.snapshot(quest.profile)[0])
    deck = next(row for row in before.decks if row.number == 1)
    selected = sorted((row for row in before.deckPositions if row.number == 1), key=lambda row: row.position)
    request = quest.schema.request_type(PATH)(questId=rows["Quest"][0]["id"], deckNumber=1,
                                            buddyDeckName=deck.name)
    application = Application(quest.schema, state, FixtureStore(tmp_path / "fixtures", quest.schema),
                              profile=quest.profile, master_dir=directory)
    server = create_server(application, port=0).start()
    try:
        with grpc.insecure_channel(f"127.0.0.1:{server.port}") as channel:
            grpc.channel_ready_future(channel).result(timeout=3)
            metadata = (("x-auth-token", token),)

            def invoke(path, message):
                call = channel.unary_unary(path, request_serializer=codec.encode, response_deserializer=codec.decode)
                return quest.schema.response_type(path).FromString(
                    call(message.SerializeToString(), metadata=metadata, timeout=3))

            assert len(invoke(PATH, request).characterAssets) == 5
            save = quest.schema.request_type("/api.Deck/Save")(number=1, name=deck.name,
                questId=request.questId, deckEditType=1)
            for row in selected:
                target = save.userDeckPositions.add(position=row.position, cardId=row.cardId,
                    costumeId=row.costumeId, hairId=row.hairId,
                    part1AccessoryId=row.part1AccessoryId, part2AccessoryId=row.part2AccessoryId)
                target.photoIds.extend(row.photoIds)
            saved = invoke("/api.Deck/Save", save)
            assert len(saved.commonResponse.updatedData.deckPositions) >= 5
            after = user_type.FromString(state.snapshot(quest.profile)[0])
            assert {(row.number, row.position): row.SerializeToString() for row in after.deckPositions} == {
                (row.number, row.position): row.SerializeToString() for row in before.deckPositions}
            del after.deckPositions[:]
            del before.deckPositions[:]
            assert after.SerializeToString() == before.SerializeToString()
            unchanged = database(state)
            with pytest.raises(grpc.RpcError) as failure:
                invoke("/api.Tutorial/StartQuest", quest.schema.request_type("/api.Tutorial/StartQuest")(
                    questId=request.questId))
            assert failure.value.code() == grpc.StatusCode.UNIMPLEMENTED
            assert database(state) == unchanged
            assert state.authenticated(token, quest.profile)
    finally:
        server.stop()
