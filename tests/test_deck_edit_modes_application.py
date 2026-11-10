"""Client-computed automatic formations cross the encrypted save boundary."""
import grpc
import pytest

from idoly_local import codec
from idoly_local.application import Application
from idoly_local.catalog import FixtureStore, import_response
from idoly_local.h2_server import create_server
from idoly_local.state import State

from test_gameplay import game, schema, master_dir


PATH = "/api.Deck/Save"
USER = "/api.User/Get"
# A protobuf-reserved field number cannot overlap either independent schema.
UNKNOWN = b"\xc8\xa3\x09\x7b"  # field19001, varint123


def request_for(game, mode, number):
    user = game.schema.response_type(USER).FromString(game.state.snapshot(game.profile)[0])
    request = game.schema.request_type(PATH)(number=number, name="Selected auto unit", deckEditType=mode,
                                            questId="quest-1")
    # Deliberately preserve a client-selected order rather than optimizing or
    # replacing it on the server. The request is a complete occupied layout.
    for slot, card in zip((5, 2, 4), reversed(list(user.cards)[:3])):
        request.userDeckPositions.add(position=slot, cardId=card.cardId)
    return request


def add_unknowns(game):
    def update(raw):
        user = game.schema.response_type(USER).FromString(raw)
        user.MergeFromString(UNKNOWN)
        user.user.MergeFromString(UNKNOWN)
        for row in (*user.decks, *user.deckPositions, *user.cards):
            row.MergeFromString(UNKNOWN)
        return user.SerializeToString()
    game.state.mutate_snapshot(game.profile, game.schema.fingerprint, update)


def protected(state):
    with state.connect() as db:
        return {name: db.execute("SELECT * FROM " + name + " ORDER BY 1").fetchall()
                for name in ("profiles", "sessions", "profile_settings", "starter_profiles")}


def projection(user, sequence):
    result = type(user).FromString(user.SerializeToString())
    result.ClearField("decks")
    result.ClearField("deckPositions")
    result.user.deckSequence = sequence
    return result.SerializeToString(deterministic=True)


@pytest.mark.parametrize("mode", (3, 4))
@pytest.mark.parametrize("number", (0, 1))
def test_selected_auto_save_authentication_delta_and_restart(game, tmp_path, mode, number):
    add_unknowns(game)
    token, _ = game.state.login(game.profile)
    request = request_for(game, mode, number)
    before = game.schema.response_type(USER).FromString(game.state.snapshot(game.profile)[0])
    protected_before = protected(game.state)
    application = Application(game.schema, game.state, FixtureStore(tmp_path / "fixtures", game.schema),
                              profile=game.profile, master_dir=game.catalog.directory)
    server = create_server(application, port=0).start()
    try:
        with grpc.insecure_channel("127.0.0.1:" + str(server.port)) as channel:
            grpc.channel_ready_future(channel).result(timeout=3)
            invoke = channel.unary_unary(PATH, request_serializer=codec.encode, response_deserializer=codec.decode)
            raw_before = game.state.snapshot(game.profile)
            with pytest.raises(grpc.RpcError) as error:
                invoke(request.SerializeToString(), timeout=3)
            assert error.value.code() == grpc.StatusCode.UNAUTHENTICATED
            assert game.state.snapshot(game.profile) == raw_before
            response = game.schema.response_type(PATH).FromString(invoke(
                request.SerializeToString(), metadata=(("x-auth-token", token),), timeout=3))
    finally:
        server.stop()
    after = game.schema.response_type(USER).FromString(game.state.snapshot(game.profile)[0])
    saved_number = before.user.deckSequence + 1 if number == 0 else number
    assert after.user.deckSequence == (saved_number if number == 0 else before.user.deckSequence)
    assert [(row.position, row.cardId) for row in after.deckPositions if row.number == saved_number] == [
        (row.position, row.cardId) for row in request.userDeckPositions]
    assert next(row.name for row in after.decks if row.number == saved_number) == request.name
    assert projection(after, before.user.deckSequence) == projection(before, before.user.deckSequence)
    assert list(response.commonResponse.updatedData.decks) == list(after.decks)
    assert list(response.commonResponse.updatedData.deckPositions) == list(after.deckPositions)
    if number:
        old = {row.position: row for row in before.deckPositions if row.number == number}
        assert [row.SerializeToString() for row in response.commonResponse.deletedData.deckPositions] == [
            row.SerializeToString() for row in before.deckPositions
            if row.number == number and row.position not in {entry.position for entry in request.userDeckPositions}]
        for row in after.deckPositions:
            if row.number == number and row.position in old:
                assert UNKNOWN in row.SerializeToString()
        assert UNKNOWN in next(row for row in after.decks if row.number == number).SerializeToString()
    else:
        assert list(after.decks[:-1]) == list(before.decks)
        assert [row for row in after.deckPositions if row.number != saved_number] == list(before.deckPositions)
        assert response.commonResponse.updatedData.user == after.user
    assert protected(game.state) == protected_before

    # Reopen both state and transport and use the same original session.
    restarted_state = State(game.state.path)
    restarted = create_server(Application(game.schema, restarted_state,
        FixtureStore(tmp_path / "fixtures", game.schema), profile=game.profile,
        master_dir=game.catalog.directory), port=0).start()
    try:
        with grpc.insecure_channel("127.0.0.1:" + str(restarted.port)) as channel:
            grpc.channel_ready_future(channel).result(timeout=3)
            get = channel.unary_unary(USER, request_serializer=codec.encode, response_deserializer=codec.decode)
            restored = game.schema.response_type(USER).FromString(get(b"", metadata=(("x-auth-token", token),), timeout=3))
            assert restored == after
    finally:
        restarted.stop()
    assert protected(restarted_state) == protected_before


@pytest.mark.parametrize("mode", (3, 4))
def test_client_auto_empty_layout_is_saved_without_inventing_cards(game, mode):
    # CreateDeckSaveRequest filters empty card slots; it does not encode an
    # absent row as a request for the server to choose a replacement idol.
    before = game.schema.response_type(USER).FromString(game.state.snapshot(game.profile)[0])
    request = game.schema.request_type(PATH)(number=1, name="Empty selected unit", deckEditType=mode)
    result = game.schema.response_type(PATH).FromString(game.handle(PATH, request.SerializeToString()))
    after = game.schema.response_type(USER).FromString(game.state.snapshot(game.profile)[0])
    assert not after.deckPositions
    assert list(result.commonResponse.deletedData.deckPositions) == list(before.deckPositions)
    assert projection(after, before.user.deckSequence) == projection(before, before.user.deckSequence)


@pytest.mark.parametrize("mode", (3, 4))
@pytest.mark.parametrize("bad", ("unowned", "duplicate_position", "duplicate_card", "unknown_quest", "buddy"))
def test_invalid_client_auto_selection_is_not_replaced_with_a_guessed_team(game, mode, bad):
    request = request_for(game, mode, 1)
    if bad == "unowned":
        request.userDeckPositions[0].cardId = "not-owned"
    elif bad == "duplicate_position":
        request.userDeckPositions[1].position = request.userDeckPositions[0].position
    elif bad == "duplicate_card":
        request.userDeckPositions[1].cardId = request.userDeckPositions[0].cardId
    elif bad == "unknown_quest":
        request.questId = "not-a-quest"
    elif bad == "buddy":
        request.userDeckPositions[0].buddyUserId = "borrowed"
    before = game.state.snapshot(game.profile)
    from idoly_local.rpc import RpcCode, RpcFailure
    with pytest.raises(RpcFailure) as error:
        game.handle(PATH, request.SerializeToString())
    assert error.value.code == (RpcCode.UNIMPLEMENTED if bad == "buddy" else RpcCode.INVALID_ARGUMENT)
    assert game.state.snapshot(game.profile) == before


@pytest.mark.parametrize("mode", (3, 4))
def test_explicit_auto_save_fixture_still_has_precedence(game, tmp_path, mode):
    token, _ = game.state.login(game.profile)
    response = game.schema.response_type(PATH)()
    response.commonResponse.SetInParent()
    source = tmp_path / "response.pb"
    source.write_bytes(response.SerializeToString())
    fixtures = tmp_path / "fixtures"
    import_response(source, fixtures, game.schema, PATH)
    application = Application(game.schema, game.state, FixtureStore(fixtures, game.schema),
                              profile=game.profile, master_dir=game.catalog.directory)
    before = game.state.snapshot(game.profile)

    class Context:
        def invocation_metadata(self):
            return (("x-auth-token", token),)
        def abort(self, code, detail):
            pytest.fail("Unexpected fixture failure: " + str(code))

    request = request_for(game, mode, 0)
    assert application.handle(PATH, codec.encode(request.SerializeToString()), Context()) == response.SerializeToString()
    assert game.state.snapshot(game.profile) == before
