"""Profile/card choices preserve ownership and unrelated state across a full edit flow."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
import json
import sys
from types import SimpleNamespace

import grpc
import pytest

from idoly_local import codec
from idoly_local.application import Application
from idoly_local.catalog import FixtureStore, import_response
from idoly_local.h2_server import create_server
from idoly_local.profile_preferences import ProfilePreferences
from idoly_local.rpc import RpcCode, RpcFailure
from idoly_local.schema import Schema
from idoly_local.state import State
from test_profile_names import USER, UNKNOWN, dump, game, protected


BUDDY = "/api.Profile/UpdateBuddyCard"
DECORATION = "/api.Profile/UpdateDecoration"
BACKGROUND = "/api.Profile/UpdateBackground"
DISPLAY = "/api.Card/UpdateDisplayType"
PATHS = (BUDDY, DECORATION, BACKGROUND, DISPLAY)


@pytest.fixture(scope="module")
def schema():
    source = Path(__file__).resolve().parents[1] / "data/protocol/idolypride-6.1.1.pb"
    if not source.is_file():
        pytest.skip("Original recovered 6.1.1 schema is unavailable")
    return Schema.from_descriptor_set(source)


@pytest.fixture
def preferences(game, tmp_path):
    provider, state = game[:2]
    master = tmp_path / "master"
    master.mkdir()
    definitions = (("kept-card", 5), ("card-low", 2), ("card-evolved", 5),
                   ("card-no-evolved-image", 5), ("card-locked", 2), ("not-owned", 5))
    (master / "Card.json").write_text(json.dumps([
        {"id": key, "initialRarity": rarity} for key, rarity in definitions]))
    image_rows = []
    for key, rarity in definitions:
        choices = (1, 2) if rarity == 2 else (2, 3) if key == "card-evolved" else (2,)
        image_rows.extend({"cardId": key, "displayType": choice,
                           "imageType": 1 if choice == 1 else 2} for choice in choices)
    (master / "CardImage.json").write_text(json.dumps(image_rows))
    (master / "Decoration.json").write_text(json.dumps([
        {"id": key} for key in ("deco-a", "deco-b", "deco-not-owned")]))

    def prepare(raw):
        value = provider.schema.response_type(USER).FromString(raw)
        value.user.buddyCardId = "kept-card"
        value.cards[0].rarity = 5
        value.cards[0].displayType = 2
        for key, rarity, evolution in (("card-low", 5, 0), ("card-evolved", 5, 1),
                                       ("card-no-evolved-image", 5, 1), ("card-locked", 2, 0)):
            value.cards.add(cardId=key, rarity=rarity, evolutionLevel=evolution,
                            displayType=1 if key == "card-locked" else 2).MergeFromString(UNKNOWN)
        value.profile.backgroundType = 1
        value.profile.decorationId = "deco-a"
        value.profile.message = "kept introduction"
        value.profile.birthMonth, value.profile.birthDay = 2, 29
        value.profile.MergeFromString(UNKNOWN)
        for key in ("deco-a", "deco-b"):
            value.decorations.add(decorationId=key).MergeFromString(UNKNOWN)
        value.photos.add(photoId="photo-a", rarity=5, level=20).MergeFromString(UNKNOWN)
        value.missions.add(missionId="kept-mission", progress=123).MergeFromString(UNKNOWN)
        return value.SerializeToString()
    state.mutate_snapshot("player", provider.schema.fingerprint, prepare)
    return ProfilePreferences(provider.schema, state, "player", master)


def snapshot(game):
    return game[0].schema.response_type(USER).FromString(game[1].snapshot("player")[0])


def call(preferences, path, **kwargs):
    raw = preferences.schema.request_type(path)(**kwargs).SerializeToString()
    return preferences.schema.response_type(path).FromString(preferences.handle(path, raw))


def test_original_schema_fields_and_enum_contract(schema):
    expected = {
        BUDDY: (("cardId", 1),), DECORATION: (("decorationId", 1),),
        DISPLAY: (("cardId", 1), ("displayType", 2)),
        BACKGROUND: (("backgroundType", 1), ("favoriteCardId", 2),
                     ("favoritePhotoId", 3), ("favoriteCardDisplayType", 4)),
    }
    for path, fields in expected.items():
        request = schema.request_type(path)()
        assert tuple((f.name, f.number) for f in request.DESCRIPTOR.fields) == fields
        assert schema.response_type(path)().DESCRIPTOR.fields_by_name["commonResponse"].number == 9999
    card = schema.response_type(USER)().cards.add()
    assert card.DESCRIPTOR.fields_by_name["displayType"].number == 13
    assert set(schema.request_type(DISPLAY)().DESCRIPTOR.fields_by_name["displayType"].enum_type.values_by_number) == {0, 1, 2, 3}


def test_connected_profile_edit_flow_and_card_illustration_keep_all_unrelated_state(game, preferences):
    expected = snapshot(game)
    kept = protected(game[1])
    expected.user.buddyCardId = "card-low"
    result = call(preferences, BUDDY, cardId="card-low")
    assert result.commonResponse.updatedData.user == expected.user
    assert {f.name for f, _ in result.commonResponse.updatedData.ListFields()} == {"user"}

    expected.profile.decorationId = "deco-b"
    result = call(preferences, DECORATION, decorationId="deco-b")
    assert result.commonResponse.updatedData.profile == expected.profile
    expected.profile.backgroundType = 3
    expected.profile.favoritePhotoId = "photo-a"
    result = call(preferences, BACKGROUND, backgroundType=3, favoritePhotoId="photo-a")
    assert result.commonResponse.updatedData.profile == expected.profile

    expected.profile.backgroundType = 2
    expected.profile.favoriteCardId = "card-evolved"
    expected.profile.favoriteCardDisplayType = 3
    result = call(preferences, BACKGROUND, backgroundType=2, favoriteCardId="card-evolved",
                  favoritePhotoId="photo-a", favoriteCardDisplayType=3)
    assert result.commonResponse.updatedData.profile == expected.profile

    expected.cards[1].displayType = 1
    result = call(preferences, DISPLAY, cardId="card-low", displayType=1)
    assert list(result.commonResponse.updatedData.cards) == [expected.cards[1]]
    assert {f.name for f, _ in result.commonResponse.updatedData.ListFields()} == {"cards"}
    assert not result.commonResponse.HasField("deletedData")
    assert UNKNOWN in result.commonResponse.updatedData.cards[0].SerializeToString()
    assert game[1].snapshot("player")[0] == expected.SerializeToString()
    assert protected(game[1]) == kept


@pytest.mark.parametrize("path,values", (
    (BUDDY, {"cardId": "kept-card"}),
    (DECORATION, {"decorationId": "deco-a"}),
    (BACKGROUND, {"backgroundType": 1}),
    (DISPLAY, {"cardId": "kept-card", "displayType": 2}),
))
def test_identical_retries_preserve_noncanonical_wire_and_do_not_write(game, preferences, monkeypatch, path, values):
    original = UNKNOWN + game[1].snapshot("player")[0]
    with game[1].connect() as db:
        db.execute("UPDATE snapshots SET response=? WHERE profile='player'", (original,))
    assert snapshot(game).SerializeToString() != original
    before = dump(game[1])
    statements, connect = [], game[1].connect
    @contextmanager
    def traced():
        with connect() as db:
            db.set_trace_callback(statements.append)
            yield db
    monkeypatch.setattr(game[1], "connect", traced)
    first = call(preferences, path, **values)
    assert call(preferences, path, **values) == first
    assert game[1].snapshot("player")[0] == original and dump(game[1]) == before
    assert not any(sql.upper().startswith("UPDATE SNAPSHOTS") for sql in statements)


@pytest.mark.parametrize("path,values", (
    (BUDDY, {"cardId": "card-low"}),
    (DECORATION, {"decorationId": "deco-b"}),
    (BACKGROUND, {"backgroundType": 2, "favoriteCardId": "card-evolved", "favoriteCardDisplayType": 3}),
    (DISPLAY, {"cardId": "card-low", "displayType": 1}),
))
def test_preferences_survive_restart_and_exact_retry_without_other_account_changes(game, preferences, path, values):
    result = call(preferences, path, **values)
    before, kept = dump(game[1]), protected(game[1])
    restarted = State(game[1].path)
    provider = ProfilePreferences(preferences.schema, restarted, "player", preferences.catalog.directory)
    assert call(provider, path, **values) == result
    assert dump(restarted) == before and protected(restarted) == kept
    assert restarted.authenticated(game[2], "player") and restarted.authenticated(game[3], "other")


@pytest.mark.parametrize("path,values,code", (
    (BUDDY, {"cardId": ""}, RpcCode.INVALID_ARGUMENT),
    (BUDDY, {"cardId": "unknown"}, RpcCode.INVALID_ARGUMENT),
    (BUDDY, {"cardId": "not-owned"}, RpcCode.PERMISSION_DENIED),
    (DECORATION, {"decorationId": ""}, RpcCode.INVALID_ARGUMENT),
    (DECORATION, {"decorationId": "unknown"}, RpcCode.INVALID_ARGUMENT),
    (DECORATION, {"decorationId": "deco-not-owned"}, RpcCode.PERMISSION_DENIED),
    (DISPLAY, {"cardId": "kept-card", "displayType": 0}, RpcCode.INVALID_ARGUMENT),
    (DISPLAY, {"cardId": "kept-card", "displayType": 4}, RpcCode.INVALID_ARGUMENT),
    (DISPLAY, {"cardId": "kept-card", "displayType": -1}, RpcCode.INVALID_ARGUMENT),
    (DISPLAY, {"cardId": "not-owned", "displayType": 2}, RpcCode.PERMISSION_DENIED),
    (DISPLAY, {"cardId": "card-locked", "displayType": 2}, RpcCode.PERMISSION_DENIED),
    (DISPLAY, {"cardId": "kept-card", "displayType": 3}, RpcCode.PERMISSION_DENIED),
    (DISPLAY, {"cardId": "card-no-evolved-image", "displayType": 3}, RpcCode.INVALID_ARGUMENT),
    (DISPLAY, {"cardId": "kept-card", "displayType": 1}, RpcCode.INVALID_ARGUMENT),
    (BACKGROUND, {"backgroundType": 0}, RpcCode.INVALID_ARGUMENT),
    (BACKGROUND, {"backgroundType": 4}, RpcCode.INVALID_ARGUMENT),
    (BACKGROUND, {"backgroundType": 2}, RpcCode.INVALID_ARGUMENT),
    (BACKGROUND, {"backgroundType": 3}, RpcCode.INVALID_ARGUMENT),
    (BACKGROUND, {"backgroundType": 1, "favoriteCardDisplayType": 2}, RpcCode.INVALID_ARGUMENT),
    (BACKGROUND, {"backgroundType": 3, "favoritePhotoId": "not-owned"}, RpcCode.PERMISSION_DENIED),
    (BACKGROUND, {"backgroundType": 2, "favoriteCardId": "card-locked", "favoriteCardDisplayType": 2}, RpcCode.PERMISSION_DENIED),
    (BACKGROUND, {"backgroundType": 3, "favoritePhotoId": "photo-a", "favoriteCardId": "not-owned"}, RpcCode.PERMISSION_DENIED),
))
def test_invalid_or_unowned_requests_change_no_database_state(game, preferences, path, values, code):
    before = dump(game[1])
    with pytest.raises(RpcFailure) as error:
        call(preferences, path, **values)
    assert error.value.code == code
    assert dump(game[1]) == before


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("raw", (b"\x0a\x80", b"\x0a\x01\xff"))
def test_malformed_requests_are_invalid_without_writes(game, preferences, path, raw):
    before = dump(game[1])
    with pytest.raises(RpcFailure) as error:
        preferences.handle(path, raw)
    assert error.value.code == RpcCode.INVALID_ARGUMENT
    assert dump(game[1]) == before


@pytest.mark.parametrize("key,effective", (("card-low", 2), ("card-evolved", 3), ("kept-card", 2), ("card-locked", 1)))
def test_profile_auto_background_keeps_auto_but_validates_actual_selected_image(game, preferences, key, effective):
    result = call(preferences, BACKGROUND, backgroundType=2, favoriteCardId=key)
    assert result.commonResponse.updatedData.profile.favoriteCardDisplayType == 0
    assert snapshot(game).profile.favoriteCardId == key
    # Auto has no separate image definition: the exact effective stage must exist.
    provider = ProfilePreferences(preferences.schema, game[1], "player", preferences.catalog.directory)
    rows = json.loads((provider.catalog.directory / "CardImage.json").read_text())
    (provider.catalog.directory / "CardImage.json").write_text(json.dumps(
        [row for row in rows if (row["cardId"], row["displayType"]) != (key, effective)]))
    before = dump(game[1])
    with pytest.raises(RpcFailure) as error:
        call(provider, BACKGROUND, backgroundType=2, favoriteCardId=key)
    assert error.value.code == RpcCode.INVALID_ARGUMENT and dump(game[1]) == before


def test_default_background_clears_favorite_references_without_revoking_inventory(game, preferences):
    call(preferences, BACKGROUND, backgroundType=2, favoriteCardId="card-low",
         favoritePhotoId="photo-a", favoriteCardDisplayType=1)
    expected = snapshot(game)
    expected.profile.backgroundType = 1
    expected.profile.favoriteCardId = expected.profile.favoritePhotoId = ""
    expected.profile.favoriteCardDisplayType = 0
    assert call(preferences, BACKGROUND, backgroundType=1).commonResponse.updatedData.profile == expected.profile
    assert game[1].snapshot("player")[0] == expected.SerializeToString()


@pytest.mark.parametrize("problem", ("missing", "wrong-schema", "malformed", "no-user", "no-profile",
                                    "duplicate-card", "duplicate-decoration", "duplicate-photo"))
def test_invalid_saved_state_never_repairs_or_partially_updates(game, preferences, problem):
    state = game[1]
    path, values = BACKGROUND, {"backgroundType": 3, "favoritePhotoId": "photo-a"}
    with state.connect() as db:
        if problem == "missing":
            db.execute("DELETE FROM snapshots WHERE profile='player'")
        elif problem == "wrong-schema":
            db.execute("UPDATE snapshots SET schema_sha256='other' WHERE profile='player'")
        else:
            value = snapshot(game)
            if problem == "no-user":
                value.ClearField("user")
            elif problem == "no-profile":
                value.ClearField("profile")
            elif problem == "duplicate-card":
                value.cards.add(cardId="card-low")
                path, values = BUDDY, {"cardId": "card-low"}
            elif problem == "duplicate-decoration":
                value.decorations.add(decorationId="deco-a")
                path, values = DECORATION, {"decorationId": "deco-a"}
            elif problem == "duplicate-photo":
                value.photos.add(photoId="photo-a")
            raw = b"\x0a\x80" if problem == "malformed" else value.SerializeToString()
            db.execute("UPDATE snapshots SET response=? WHERE profile='player'", (raw,))
    before = dump(state)
    with pytest.raises(RpcFailure) as error:
        call(preferences, path, **values)
    assert error.value.code == RpcCode.FAILED_PRECONDITION and dump(state) == before


@pytest.mark.parametrize("problem", ("missing", "malformed", "duplicate", "bad-display", "bad-kind"))
def test_invalid_image_catalog_is_not_ignored_or_replaced(game, preferences, problem):
    source = preferences.catalog.directory / "CardImage.json"
    if problem == "missing":
        source.unlink()
    elif problem == "malformed":
        source.write_text("{")
    else:
        rows = json.loads(source.read_text())
        if problem == "duplicate":
            rows.append(rows[0])
        else:
            rows[0]["displayType" if problem == "bad-display" else "imageType"] = 9
        source.write_text(json.dumps(rows))
    before = dump(game[1])
    with pytest.raises(RpcFailure) as error:
        call(preferences, DISPLAY, cardId="card-low", displayType=1)
    assert error.value.code == RpcCode.FAILED_PRECONDITION and dump(game[1]) == before


def test_concurrent_edits_do_not_overwrite_other_preferences(game, preferences):
    edits = ((BUDDY, {"cardId": "card-low"}), (DECORATION, {"decorationId": "deco-b"}),
             (BACKGROUND, {"backgroundType": 3, "favoritePhotoId": "photo-a"}),
             (DISPLAY, {"cardId": "card-evolved", "displayType": 3}))
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda item: call(preferences, item[0], **item[1]), edits))
    value = snapshot(game)
    assert value.user.buddyCardId == "card-low" and value.profile.decorationId == "deco-b"
    assert value.profile.backgroundType == 3 and value.profile.favoritePhotoId == "photo-a"
    assert next(c for c in value.cards if c.cardId == "card-evolved").displayType == 3
    assert len(results) == 4


def test_missing_master_selection_does_not_authorize_other_accounts_inventory(game, preferences):
    def add_other(raw):
        value = preferences.schema.response_type(USER).FromString(raw)
        value.cards.add(cardId="not-owned", rarity=5)
        value.decorations.add(decorationId="deco-not-owned")
        return value.SerializeToString()
    game[1].mutate_snapshot("other", preferences.schema.fingerprint, add_other)
    before = dump(game[1])
    for path, values in ((BUDDY, {"cardId": "not-owned"}),
                         (DECORATION, {"decorationId": "deco-not-owned"})):
        with pytest.raises(RpcFailure) as error:
            call(preferences, path, **values)
        assert error.value.code == RpcCode.PERMISSION_DENIED
    assert dump(game[1]) == before


@contextmanager
def connected(game, preferences, directory):
    provider, state, token, other_token = game
    application = Application(provider.schema, state, FixtureStore(directory, provider.schema),
                              profile="player", master_dir=preferences.catalog.directory)
    server = create_server(application, port=0).start()
    try:
        with grpc.insecure_channel(f"127.0.0.1:{server.port}") as channel:
            grpc.channel_ready_future(channel).result(timeout=3)
            def invoke(path, raw=b"", auth=token):
                rpc = channel.unary_unary(path, request_serializer=codec.encode, response_deserializer=codec.decode)
                metadata = (("x-auth-token", auth),) if auth else ()
                return rpc(raw, metadata=metadata, timeout=3)
            yield invoke
    finally:
        server.stop()


def test_actual_encrypted_edit_flow_requires_current_account_session_and_persists(game, preferences, tmp_path):
    edits = ((BUDDY, {"cardId": "card-low"}), (DECORATION, {"decorationId": "deco-b"}),
             (BACKGROUND, {"backgroundType": 3, "favoritePhotoId": "photo-a"}),
             (DISPLAY, {"cardId": "card-low", "displayType": 1}))
    before = dump(game[1])
    with connected(game, preferences, tmp_path / "fixtures") as invoke:
        for path, values in edits:
            raw = preferences.schema.request_type(path)(**values).SerializeToString()
            for auth in (None, "unknown", game[3]):
                with pytest.raises(grpc.RpcError) as error:
                    invoke(path, raw, auth)
                assert error.value.code() == grpc.StatusCode.UNAUTHENTICATED
            assert dump(game[1]) == before
        for path, values in edits:
            raw = preferences.schema.request_type(path)(**values).SerializeToString()
            result = preferences.schema.response_type(path).FromString(invoke(path, raw))
            assert result.commonResponse.HasField("updatedData")
            after = dump(game[1])
            assert invoke(path, raw) == result.SerializeToString()
            assert dump(game[1]) == after
        assert invoke(USER) == game[1].snapshot("player")[0]


def test_explicit_response_fixture_keeps_precedence_without_mutation(game, preferences, tmp_path):
    response = preferences.schema.response_type(BUDDY)()
    response.commonResponse.updatedData.user.buddyCardId = "captured-buddy"
    source, directory = tmp_path / "response.pb", tmp_path / "fixtures"
    source.write_bytes(response.SerializeToString())
    import_response(source, directory, preferences.schema, BUDDY)
    before = dump(game[1])
    with connected(game, preferences, directory) as invoke:
        with pytest.raises(grpc.RpcError) as error:
            invoke(BUDDY, auth=None)
        assert error.value.code() == grpc.StatusCode.UNAUTHENTICATED
        assert invoke(BUDDY) == source.read_bytes()
    assert dump(game[1]) == before


@pytest.mark.parametrize("table,path,values", (
    ("CardImage", DISPLAY, {"cardId": "card-low", "displayType": 1}),
    ("Decoration", DECORATION, {"decorationId": "deco-b"}),
))
def test_only_matching_master_version_can_fill_absent_table_from_verified_supplement(
        game, preferences, monkeypatch, table, path, values):
    directory = preferences.catalog.directory
    rows = (directory / (table + ".json")).read_text()
    (directory / (table + ".json")).unlink()
    version = "961e456499039e31248a818a911c8d95f92461f86aff4674ba07e29c32afcf60"
    # The module contains data strings only; the other table is deliberately
    # invalid so this request must not eagerly parse or require both tables.
    fallback = SimpleNamespace(MASTER_VERSION=version,
        ROWS_JSON={table: rows, "Decoration" if table == "CardImage" else "CardImage": "{"})
    monkeypatch.setitem(sys.modules, "idoly_local.preference_master_data", fallback)
    version_path = directory / "!version.txt"
    before = dump(game[1])
    for bad in (None, "", "foreign-version"):
        if bad is None:
            if version_path.exists():
                version_path.unlink()
        else:
            version_path.write_text(bad)
        with pytest.raises(RpcFailure) as error:
            call(preferences, path, **values)
        assert error.value.code == RpcCode.FAILED_PRECONDITION and dump(game[1]) == before
    version_path.write_text(version + "\n")
    result = call(preferences, path, **values)
    assert result.commonResponse.HasField("updatedData")
    assert table in preferences.catalog.loaded
    assert ("Decoration" if table == "CardImage" else "CardImage") not in preferences.catalog.loaded


@pytest.mark.parametrize("present", ("[]", "{", "broken-link"))
def test_present_invalid_master_never_uses_supplement_even_with_matching_version(
        game, preferences, monkeypatch, present):
    version = "961e456499039e31248a818a911c8d95f92461f86aff4674ba07e29c32afcf60"
    directory = preferences.catalog.directory
    source = directory / "Decoration.json"
    valid_rows = source.read_text()
    monkeypatch.setitem(sys.modules, "idoly_local.preference_master_data",
        SimpleNamespace(MASTER_VERSION=version, ROWS_JSON={"Decoration": valid_rows}))
    (directory / "!version.txt").write_text(version)
    if present == "broken-link":
        source.unlink()
        source.symlink_to(directory / "does-not-exist.json")
    else:
        source.write_text(present)
    before = dump(game[1])
    with pytest.raises(RpcFailure) as error:
        call(preferences, DECORATION, decorationId="deco-b")
    assert error.value.code == RpcCode.FAILED_PRECONDITION and dump(game[1]) == before


def test_existing_custom_table_keeps_precedence_over_supplement(game, preferences, monkeypatch):
    monkeypatch.setitem(sys.modules, "idoly_local.preference_master_data",
        SimpleNamespace(MASTER_VERSION="wrong", ROWS_JSON={"CardImage": "{", "Decoration": "{"}))
    (preferences.catalog.directory / "!version.txt").write_text("custom-catalog")
    assert call(preferences, DECORATION, decorationId="deco-b").commonResponse.updatedData.profile.decorationId == "deco-b"
    assert call(preferences, DISPLAY, cardId="card-low", displayType=1).commonResponse.updatedData.cards[0].displayType == 1


def test_generated_preference_supplement_matches_recorded_original_tables():
    import hashlib
    from idoly_local import preference_master_data as data
    root = Path(__file__).resolve().parents[1]
    proof = json.loads((root / "docs/preference-master-data.json").read_text())
    assert proof["status"] == "PASS" and proof["input_unchanged"] is True
    assert data.MASTER_VERSION == proof["master_version"] == "961e456499039e31248a818a911c8d95f92461f86aff4674ba07e29c32afcf60"
    assert data.SOURCE_BYTES == proof["source"]["bytes"] == 191343014
    assert data.SOURCE_SHA256 == proof["source"]["sha256"] == "37dbf0fb9bac5d860991753d2e41ff0c269684bfca673ba41e1bcb897651c223"
    assert data.SCHEMA_SHA256 == proof["schema_sha256"] == "c82cee62abdca7144d11e710a6f773211464a89d2ddede207999a0a5e7aec8ad"
    raw_module = Path(data.__file__).read_bytes()
    assert len(raw_module) == proof["output"]["module"]["bytes"]
    assert hashlib.sha256(raw_module).hexdigest() == proof["output"]["module"]["sha256"]
    assert set(data.ROWS_JSON) == set(data.PACKS) == {"CardImage", "Decoration"}
    for table, expected_count in (("CardImage", 611), ("Decoration", 361)):
        record = proof["packs"][table]
        assert data.PACKS[table] == record
        encoded = data.ROWS_JSON[table].encode("ascii")
        assert len(encoded) == record["json_bytes"]
        assert hashlib.sha256(encoded).hexdigest() == record["json_sha256"]
        rows = json.loads(encoded)
        assert len(rows) == record["rows"] == expected_count
        identities = [(row["cardId"], row["displayType"]) if table == "CardImage" else row["id"] for row in rows]
        assert len(set(identities)) == len(identities)


def test_actual_pinned_supplement_fallback_updates_owned_card_and_decoration(game, tmp_path):
    import os
    from idoly_local import preference_master_data as data
    root = Path(__file__).resolve().parents[1]
    explicit = os.environ.get("IDOLY_PREFERENCE_MASTER_DIR")
    source = Path(explicit) if explicit else root / "data/master-json"
    required = tuple(source / name for name in ("Card.json", "!version.txt"))
    if not all(path.is_file() for path in required):
        if explicit:
            pytest.fail("The required pinned real-master gate input is incomplete")
        pytest.skip("Original public master catalog is unavailable")
    assert (source / "!version.txt").read_text().strip() == data.MASTER_VERSION
    masters = {row["id"]: row for row in json.loads((source / "Card.json").read_text())}
    images = {(row["cardId"], row["displayType"]) for row in json.loads(data.ROWS_JSON["CardImage"])}
    selected_card = next(key for key, row in masters.items()
                         if row["initialRarity"] == 5 and (key, 2) in images and (key, 1) not in images)
    selected_decoration = json.loads(data.ROWS_JSON["Decoration"])[0]["id"]
    directory = tmp_path / "original-preference-master"
    directory.mkdir()
    # These two inputs are copied verbatim. Both supplementary JSON files are
    # deliberately absent: the actual generated module is the only fallback.
    for path in required:
        (directory / path.name).write_bytes(path.read_bytes())
    assert not (directory / "CardImage.json").exists()
    assert not (directory / "Decoration.json").exists()
    def own_test_rows(raw):
        value = game[0].schema.response_type(USER).FromString(raw)
        value.cards.add(cardId=selected_card, rarity=5).MergeFromString(UNKNOWN)
        value.decorations.add(decorationId=selected_decoration).MergeFromString(UNKNOWN)
        return value.SerializeToString()
    game[1].mutate_snapshot("player", game[0].schema.fingerprint, own_test_rows)
    provider = ProfilePreferences(game[0].schema, game[1], "player", directory)
    expected, kept = snapshot(game), protected(game[1])
    selected = next(row for row in expected.cards if row.cardId == selected_card)
    selected.displayType = 2
    result = call(provider, DISPLAY, cardId=selected_card, displayType=2)
    assert list(result.commonResponse.updatedData.cards) == [selected]
    assert "CardImage" in provider.catalog.loaded and "Decoration" not in provider.catalog.loaded
    expected.profile.decorationId = selected_decoration
    result = call(provider, DECORATION, decorationId=selected_decoration)
    assert result.commonResponse.updatedData.profile == expected.profile
    assert game[1].snapshot("player")[0] == expected.SerializeToString()
    assert protected(game[1]) == kept
    before = dump(game[1])
    call(provider, DISPLAY, cardId=selected_card, displayType=2)
    call(provider, DECORATION, decorationId=selected_decoration)
    assert dump(game[1]) == before
