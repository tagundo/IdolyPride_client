"""Actual photo toggle contract, atomic batches, durable receipts and transport."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
import sqlite3

import grpc
import pytest

from idoly_local import codec
from idoly_local.application import Application
from idoly_local.catalog import FixtureStore
from idoly_local.h2_server import create_server
from idoly_local.photo_preferences import PhotoPreferences
from idoly_local.rpc import RpcCode, RpcFailure
from idoly_local.schema import Schema
from idoly_local.state import State


PATH, USER = "/api.Photo/SwitchLock", "/api.User/Get"
UNKNOWN = b"\x80\x4b\x7b"


@pytest.fixture(scope="module", params=("idolypride-6.1.1.pb", "idolypride-6.1.1-ios.pb"))
def schema(request):
    path = Path(__file__).resolve().parents[1] / "data/protocol" / request.param
    if not path.is_file():
        pytest.skip("Recovered original platform descriptor unavailable")
    return Schema.from_descriptor_set(path)


@pytest.fixture
def game(schema, tmp_path):
    state = State(tmp_path / "state.sqlite")
    identity = state.ensure_profile("player")
    data = schema.response_type(USER)()
    data.user.name, data.user.lastLoginTime = "Manager", 123456789
    data.userPublic.serverUserId = identity["server_id"]
    data.userPublic.publicUserId = identity["public_id"]
    data.profile.favoritePhotoId = "photo-a"
    data.profile.MergeFromString(UNKNOWN)
    a = data.photos.add(photoId="photo-a", name="Favorite", rarity=4, level=30,
        locked=True, isDreamBase=True, photoRecipeId="recipe", assetId="private-image")
    a.characterIds.extend(("character-a", "character-b"))
    a.abilities.add(photoAbilityId="ability", effectValue=123)
    a.MergeFromString(UNKNOWN)
    data.photos.add(photoId="photo-b", name="Other", rarity=1, locked=False)
    data.photos.add(photoId="photo-c", name="Untouched", rarity=2, locked=True)
    data.items.add(itemId="kept-item", amount=13)
    data.cards.add(cardId="kept-card", totalExp=5678)
    data.MergeFromString(UNKNOWN)
    state.save_snapshot("player", data.SerializeToString(), schema.fingerprint, starter_version=4)
    state.mutate_snapshot("player", schema.fingerprint, lambda raw: raw, setting_info=b"settings\x00")
    state.mutate_lesson_snapshot("player", schema.fingerprint, lambda raw, _: (raw, b"lesson\x00"))
    other = schema.response_type(USER)()
    other.user.name = "Other manager"
    other.photos.add(photoId="foreign-photo", locked=True)
    state.save_snapshot("other", other.SerializeToString(), schema.fingerprint)
    token, _ = state.login("player")
    other_token, _ = state.login("other")
    return PhotoPreferences(schema, state, "player"), state, token, other_token


def snapshot(game):
    return game[0].schema.response_type(USER).FromString(game[1].snapshot("player")[0])


def dump(state):
    with state.connect() as db:
        return tuple(db.iterdump())


def protected(state):
    with state.connect() as db:
        result = {name: [tuple(row) for row in db.execute('SELECT * FROM "' + name + '" ORDER BY 1')]
                  for name in ("profiles", "sessions", "profile_settings", "starter_profiles",
                               "profile_lesson_progress", "main_live_attempts")}
    return result, state.snapshot("other")


def body(game, identities=("photo-a",)):
    return game[0].schema.request_type(PATH)(photoIds=identities).SerializeToString()


def call(game, identities=("photo-a",), request_id="1"):
    provider = game[0]
    return provider.handle(PATH, body(game, identities), request_id=request_id)


def test_actual_contract_is_photo_ids_toggle_and_full_updated_photo_ack(schema):
    fields = schema.request_type(PATH).DESCRIPTOR.fields
    assert [(field.name, field.number, field.type, field.is_repeated)
            for field in fields] == [("photoIds", 1, 9, True)]
    response = schema.response_type(PATH)()
    assert response.DESCRIPTOR.fields_by_name["commonResponse"].number == 9999
    photo = schema.response_type(USER)().photos.add()
    assert photo.DESCRIPTOR.fields_by_name["locked"].number == 9
    assert photo.DESCRIPTOR.fields_by_name["locked"].type == 8


@pytest.mark.parametrize("identities", (("photo-a",), ("photo-b",), ("photo-b", "photo-a")))
def test_toggle_changes_only_owned_lock_flags_and_returns_full_rows_in_request_order(game, identities):
    provider, state, token, other_token = game
    expected = snapshot(game)
    rows = {photo.photoId: photo for photo in expected.photos}
    for identity in identities:
        rows[identity].locked = not rows[identity].locked
    kept = protected(state)
    raw = call(game, identities)
    result = provider.schema.response_type(PATH).FromString(raw)
    assert snapshot(game) == expected
    assert list(result.commonResponse.updatedData.photos) == [rows[key] for key in identities]
    assert {field.name for field, _ in result.commonResponse.updatedData.ListFields()} == {"photos"}
    assert not result.commonResponse.HasField("deletedData")
    for photo in result.commonResponse.updatedData.photos:
        if photo.photoId == "photo-a":
            assert UNKNOWN in photo.SerializeToString()
    assert protected(state) == kept
    assert state.authenticated(token, "player") and state.authenticated(other_token, "other")
    before_retry = dump(state)
    assert call(game, identities) == raw and dump(state) == before_retry
    restarted = State(state.path)
    replay = PhotoPreferences(provider.schema, restarted, "player")
    assert replay.handle(PATH, body(game, identities), request_id="1") == raw
    assert dump(restarted) == before_retry


def test_new_id_toggles_again_but_late_retry_returns_old_ack_without_reverting_current_state(game):
    first = call(game, request_id="1")
    assert not snapshot(game).photos[0].locked
    second = call(game, request_id="2")
    assert snapshot(game).photos[0].locked and second != first
    before_retry = dump(game[1])
    assert call(game, request_id="1") == first
    assert snapshot(game).photos[0].locked and dump(game[1]) == before_retry
    assert call(game, request_id="2") == second and dump(game[1]) == before_retry


@pytest.mark.parametrize("identities,code", [
    ((), RpcCode.INVALID_ARGUMENT),
    (("",), RpcCode.INVALID_ARGUMENT),
    (("photo-a", ""), RpcCode.INVALID_ARGUMENT),
    (("photo-a", "photo-a"), RpcCode.INVALID_ARGUMENT),
    (("missing",), RpcCode.PERMISSION_DENIED),
    (("foreign-photo",), RpcCode.PERMISSION_DENIED),
    (("photo-a", "foreign-photo"), RpcCode.PERMISSION_DENIED),
    (("photo-a", "photo-b", "missing"), RpcCode.PERMISSION_DENIED),
])
def test_invalid_or_partly_unowned_batches_do_not_change_snapshot_or_leave_receipt(game, identities, code):
    before = dump(game[1])
    with pytest.raises(RpcFailure) as failure:
        call(game, identities)
    assert failure.value.code == code and dump(game[1]) == before


@pytest.mark.parametrize("request_id", (None, "", "0", "01", "+1", "-1", " 1", "1 ",
                                        "1.0", str(1 << 64), 1, True))
def test_toggle_requires_canonical_cache_identity_before_mutation(game, request_id):
    before = dump(game[1])
    with pytest.raises(RpcFailure) as failure:
        call(game, request_id=request_id)
    assert failure.value.code == RpcCode.INVALID_ARGUMENT and dump(game[1]) == before


def test_malformed_request_and_conflicting_body_reuse_are_atomic(game):
    provider, state = game[:2]
    before = dump(state)
    with pytest.raises(RpcFailure) as failure:
        provider.handle(PATH, b"\x0a\x80", request_id="1")
    assert failure.value.code == RpcCode.INVALID_ARGUMENT and dump(state) == before
    call(game)
    before = dump(state)
    with pytest.raises(RpcFailure) as failure:
        call(game, ("photo-b",))
    assert failure.value.code == RpcCode.INVALID_ARGUMENT and dump(state) == before


@pytest.mark.parametrize("damage", ("duplicate-photo", "empty-photo", "missing-user",
                                    "malformed-snapshot", "wrong-schema", "no-snapshot"))
def test_malformed_inventory_or_snapshot_never_masks_failure_or_writes_receipts(game, damage):
    provider, state = game[:2]
    data = snapshot(game)
    if damage == "duplicate-photo":
        data.photos.add(photoId="photo-a")
    elif damage == "empty-photo":
        data.photos.add(name="No identity")
    elif damage == "missing-user":
        data.ClearField("user")
    raw = b"\xff" if damage == "malformed-snapshot" else data.SerializeToString()
    state.mutate_snapshot("player", provider.schema.fingerprint, lambda _: raw)
    if damage == "wrong-schema":
        with state.connect() as db:
            db.execute("UPDATE snapshots SET schema_sha256=? WHERE profile=?", ("different", "player"))
    if damage == "no-snapshot":
        with state.connect() as db:
            db.execute("DELETE FROM snapshots WHERE profile=?", ("player",))
    before = dump(state)
    with pytest.raises(RpcFailure) as failure:
        call(game)
    assert failure.value.code == RpcCode.FAILED_PRECONDITION and dump(state) == before


def test_concurrent_duplicate_requests_toggle_once_and_distinct_ids_are_serialized(game):
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: call(game), range(16)))
    assert len(set(results)) == 1 and not snapshot(game).photos[0].locked
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda identity: call(game, request_id=str(identity)), range(2, 6)))
    assert not snapshot(game).photos[0].locked


def test_receipt_insert_failure_rolls_back_every_photo_in_batch(game):
    _, state = game[:2]
    with state.connect() as db:
        db.execute("CREATE TRIGGER reject_preference BEFORE INSERT ON preference_receipts "
                   "BEGIN SELECT RAISE(ABORT,'receipt failure'); END;")
    before = dump(state)
    with pytest.raises(sqlite3.IntegrityError):
        call(game, ("photo-a", "photo-b"))
    assert dump(state) == before


def test_explicit_snapshot_import_clears_only_its_receipts_and_starts_a_new_toggle_timeline(game):
    provider, state = game[:2]
    original = state.snapshot("player")[0]
    call(game)
    other_before = state.snapshot("other")
    state.save_snapshot("player", original, provider.schema.fingerprint)
    assert state.snapshot("other") == other_before
    assert snapshot(game).photos[0].locked
    call(game)
    assert not snapshot(game).photos[0].locked


def test_unrelated_preference_paths_remain_unhandled_without_a_request_identity(game):
    for path in ("/api.Photo/Update", "/api.Photo/Delete", "/api.Photo/Enhance"):
        assert game[0].handle(path, b"") is None


@contextmanager
def connected(game, directory):
    provider, state, token, _ = game
    app = Application(provider.schema, state, FixtureStore(directory, provider.schema),
                      profile="player")
    server = create_server(app, port=0).start()
    try:
        with grpc.insecure_channel(f"127.0.0.1:{server.port}") as channel:
            grpc.channel_ready_future(channel).result(timeout=3)
            def invoke(path=PATH, raw=None, auth=token, headers=(("x-app-request-id", "1"),)):
                rpc = channel.unary_unary(path, request_serializer=codec.encode,
                                         response_deserializer=codec.decode)
                metadata = ((("x-auth-token", auth),) if auth else ()) + tuple(headers)
                return rpc(body(game) if raw is None else raw, metadata=metadata, timeout=3)
            yield invoke
    finally:
        server.stop()


def test_authenticated_encrypted_dispatch_toggles_once_and_replays_after_reconnect(game, tmp_path):
    _, state, token, other_token = game
    before = dump(state)
    with connected(game, tmp_path / "fixtures") as invoke:
        for auth in (None, "invalid", other_token):
            with pytest.raises(grpc.RpcError) as failure:
                invoke(auth=auth)
            assert failure.value.code() == grpc.StatusCode.UNAUTHENTICATED
        assert dump(state) == before
        raw = invoke()
        assert not snapshot(game).photos[0].locked
        after = dump(state)
        assert invoke() == raw and dump(state) == after
    with connected(game, tmp_path / "reconnected") as invoke:
        assert invoke(raw=b"", path=USER) == state.snapshot("player")[0]
        assert invoke() == raw
    assert dump(state) == after and state.authenticated(token, "player")


@pytest.mark.parametrize("headers", ((), (("x-app-request-id", "01"),),
    (("x-app-request-id", "1"), ("x-app-request-id", "1")),
    (("x-app-request-id", "1"), ("x-app-request-id", "2"))))
def test_dispatch_rejects_missing_or_duplicate_request_identity_before_any_toggle(game, tmp_path, headers):
    before = dump(game[1])
    with connected(game, tmp_path / "fixtures") as invoke:
        with pytest.raises(grpc.RpcError) as failure:
            invoke(headers=headers)
        assert failure.value.code() == grpc.StatusCode.INVALID_ARGUMENT
    assert dump(game[1]) == before
