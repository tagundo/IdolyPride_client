"""Saved-deck asset projection, independent of battle or reward handling."""
import json
from pathlib import Path

from google.protobuf import descriptor_pb2
import pytest

from idoly_local.quest import Quest
from idoly_local.rpc import RpcCode, RpcFailure
from idoly_local.schema import Schema
from idoly_local.state import State


PATH = "/api.Quest/ListAsset"


def minimal_schema(path):
    file = descriptor_pb2.FileDescriptorProto(name="live-assets-test.proto", package="api", syntax="proto3")
    def message(name, fields):
        target = file.message_type.add(name=name)
        for number, (name, kind, repeated) in enumerate(fields, 1):
            field = target.field.add(name=name, number=number, label=3 if repeated else 1)
            if isinstance(kind, int):
                field.type = kind
            else:
                field.type, field.type_name = 11, ".api." + kind
    def fields(*entries):
        return [(name, kind, False) for name, kind in entries]
    message("Empty", [])
    message("Manager", fields(("name", 9)))
    message("Character", fields(("characterId", 9), ("liveCostumeId", 9), ("liveHairId", 9), ("favoriteCostumeId", 9)))
    message("Card", fields(("cardId", 9), ("photoEquipableCount", 5)))
    message("Costume", fields(("costumeId", 9)))
    message("Hair", fields(("hairId", 9)))
    message("Photo", fields(("photoId", 9)))
    message("Accessory", fields(("accessoryId", 9), ("amount", 3)))
    message("Deck", fields(("number", 5), ("name", 9)))
    position_fields = fields(("position", 5), ("cardId", 9), ("part1AccessoryId", 9),
                             ("part2AccessoryId", 9), ("costumeId", 9), ("hairId", 9)) + [("photoIds", 9, True)]
    message("Position", fields(("number", 5)) + position_fields)
    message("BuddyPosition", position_fields + fields(("buddyUserId", 9)))
    message("UserGetResponse", fields(("user", "Manager")) + [
        (name, kind, True) for name, kind in (("characters", "Character"), ("cards", "Card"),
            ("costumes", "Costume"), ("hairs", "Hair"), ("photos", "Photo"),
            ("accessories", "Accessory"), ("decks", "Deck"), ("deckPositions", "Position"))])
    message("ListAssetRequest", fields(("questId", 9), ("deckNumber", 5), ("buddyDeckName", 9))
            + [("userBuddyDeckPositions", "BuddyPosition", True)])
    message("CharacterAsset", fields(("characterId", 9), ("costumeId", 9), ("hairId", 9)))
    message("CommonResponse", fields(("updatedData", "Empty"), ("deletedData", "Empty")))
    message("ListAssetResponse", [("characterAssets", "CharacterAsset", True)]
            + fields(("commonResponse", "CommonResponse")))
    for name, method, response in (("System", "Check", "Empty"), ("User", "Get", "UserGetResponse"),
                                   ("Quest", "ListAsset", "ListAssetResponse")):
        file.service.add(name=name).method.add(name=method,
            input_type=".api.ListAssetRequest" if name == "Quest" else ".api.Empty",
            output_type=".api." + response)
    result = descriptor_pb2.FileDescriptorSet()
    result.file.add().CopyFrom(file)
    path.write_bytes(result.SerializeToString())
    return Schema.from_descriptor_set(path)


@pytest.fixture(scope="module", params=("minimal", "client-6.1.1"))
def schema(request, tmp_path_factory):
    if request.param == "minimal":
        return minimal_schema(tmp_path_factory.mktemp("live-assets-schema") / "schema.pb")
    path = Path(__file__).resolve().parents[1] / "data/protocol/idolypride-6.1.1.pb"
    if not path.is_file():
        pytest.skip("Optional recovered client descriptor is unavailable")
    return Schema.from_descriptor_set(path)


@pytest.fixture
def game(schema, tmp_path):
    directory = tmp_path / "master"
    directory.mkdir()
    names = "abcde"
    rows = {
        "Quest": [{"id": "quest-main", "areaId": "area-main"},
                  {"id": "qt-tutorial-full", "areaId": "area-tutorial"},
                  {"id": "qt-tutorial-short", "areaId": "area-tutorial"}],
        "Area": [{"id": "area-main", "type": 1}, {"id": "area-tutorial", "type": 101}],
        "Card": [{"id": "card-" + name, "characterId": "char-" + name} for name in names],
        "Character": [{"id": "char-" + name, "defaultLiveCostumeId": "cos-" + name + "-live",
                       "defaultCostumeId": "cos-" + name + "-default"} for name in names],
        "Costume": [{"id": "cos-" + name + "-" + variant, "characterId": "char-" + name,
                     "defaultHairId": "hair-" + name + "-" + variant}
                    for name in names for variant in ("default", "live", "selected")],
        "Hair": [{"id": "hair-" + name + "-" + variant, "characterId": "char-" + name,
                  "wearableCostumeIds": ["cos-" + name + "-" + variant], "notWearableCostumeIds": []}
                 for name in names for variant in ("default", "live", "selected")],
        "Accessory": [{"id": "accessory-1", "categoryType": 1}],
    }
    for table, data in rows.items():
        (directory / (table + ".json")).write_text(json.dumps(data))
    snapshot = schema.response_type("/api.User/Get")()
    snapshot.user.name = "Preserved manager"
    snapshot.decks.add(number=1, name="Local deck")
    snapshot.photos.add(photoId="photo-1")
    snapshot.accessories.add(accessoryId="accessory-1", amount=1)
    for index, name in reversed(list(enumerate(names, 1))):
        snapshot.cards.add(cardId="card-" + name, photoEquipableCount=2)
        snapshot.characters.add(characterId="char-" + name, liveCostumeId="cos-" + name + "-live",
                                liveHairId="hair-" + name + "-live", favoriteCostumeId="cos-" + name + "-selected")
        snapshot.deckPositions.add(number=1, position=index, cardId="card-" + name,
                                   costumeId="cos-" + name + "-selected", hairId="hair-" + name + "-selected")
        for variant in ("default", "live", "selected"):
            snapshot.costumes.add(costumeId="cos-" + name + "-" + variant)
            snapshot.hairs.add(hairId="hair-" + name + "-" + variant)
    position = next(row for row in snapshot.deckPositions if row.position == 1)
    position.photoIds.append("photo-1")
    position.part1AccessoryId = "accessory-1"
    state = State(tmp_path / "profiles.sqlite")
    state.save_snapshot("player", snapshot.SerializeToString() + b"\xf8\x7f\x01", schema.fingerprint)
    token, _ = state.login("player")
    return Quest(schema, state, "player", directory), state, directory, rows, token


def request(game, **values):
    return game[0].schema.request_type(PATH)(questId="quest-main", deckNumber=1,
                                           buddyDeckName="Local deck", **values)


def response(game, query=None):
    quest = game[0]
    raw = quest.handle(PATH, (query or request(game)).SerializeToString())
    return quest.schema.response_type(PATH).FromString(raw)


def mutate(game, change):
    quest, state = game[:2]
    def update(raw):
        snapshot = quest.schema.response_type("/api.User/Get").FromString(raw)
        change(snapshot)
        return snapshot.SerializeToString()
    state.mutate_snapshot(quest.profile, quest.schema.fingerprint, update)


def slot(snapshot, number=1):
    return next(row for row in snapshot.deckPositions if row.position == number and row.number == 1)


def character(snapshot, name="a"):
    return next(row for row in snapshot.characters if row.characterId == "char-" + name)


def master(game, table, change):
    change(game[3][table])
    (game[2] / (table + ".json")).write_text(json.dumps(game[3][table]))


def database(state):
    with state.connect() as db:
        return list(db.iterdump())


def test_selected_saved_appearances_are_ordered_and_whole_database_is_unchanged(game):
    before = database(game[1])
    result = response(game)
    assert [(row.characterId, row.costumeId, row.hairId) for row in result.characterAssets] == [
        ("char-" + name, "cos-" + name + "-selected", "hair-" + name + "-selected") for name in "abcde"]
    assert result.HasField("commonResponse") and not result.commonResponse.SerializeToString()
    assert database(game[1]) == before
    assert game[1].authenticated(game[4], "player")


@pytest.mark.parametrize("quest_id", ["quest-main", "qt-tutorial-full", "qt-tutorial-short"])
def test_main_full_and_short_share_same_real_appearances(game, quest_id):
    query = request(game)
    query.questId = quest_id
    assert response(game, query).SerializeToString() == response(game).SerializeToString()


def test_normal_deck_name_is_allowed_without_rentals_and_rentals_are_explicitly_unsupported(game):
    query = request(game)
    query.buddyDeckName = "A normal renamed unit"
    assert len(response(game, query).characterAssets) == 5
    query.userBuddyDeckPositions.add(position=1, buddyUserId="other-user", cardId="other-card")
    with pytest.raises(RpcFailure) as caught:
        response(game, query)
    assert caught.value.code == RpcCode.UNIMPLEMENTED


def test_explicit_pair_bypasses_broken_unused_character_preferences(game):
    def change(snapshot):
        actor = character(snapshot)
        actor.liveCostumeId = actor.favoriteCostumeId = actor.liveHairId = "missing"
    mutate(game, change)
    before = database(game[1])
    result = response(game).characterAssets[0]
    assert (result.costumeId, result.hairId) == ("cos-a-selected", "hair-a-selected")
    assert database(game[1]) == before


def test_blank_overrides_resolve_character_live_appearance(game):
    mutate(game, lambda snapshot: slot(snapshot).ClearField("costumeId"))
    mutate(game, lambda snapshot: slot(snapshot).ClearField("hairId"))
    before = database(game[1])
    result = response(game).characterAssets[0]
    assert (result.costumeId, result.hairId) == ("cos-a-live", "hair-a-live")
    assert database(game[1]) == before


@pytest.mark.parametrize("invalid", ["missing", "unowned"])
def test_invalid_or_unowned_global_preferences_fall_back_without_state_changes(game, invalid):
    def change(snapshot):
        slot(snapshot).ClearField("costumeId")
        slot(snapshot).ClearField("hairId")
        actor = character(snapshot)
        actor.liveCostumeId = "missing" if invalid == "missing" else "cos-a-selected"
        actor.liveHairId = "missing" if invalid == "missing" else "hair-a-selected"
        actor.favoriteCostumeId = "missing"
        if invalid == "unowned":
            costumes = [row for row in snapshot.costumes if row.costumeId != "cos-a-selected"]
            hairs = [row for row in snapshot.hairs if row.hairId != "hair-a-selected"]
            del snapshot.costumes[:]
            del snapshot.hairs[:]
            snapshot.costumes.extend(costumes)
            snapshot.hairs.extend(hairs)
    mutate(game, change)
    before = database(game[1])
    result = response(game).characterAssets[0]
    assert (result.costumeId, result.hairId) == ("cos-a-live", "hair-a-live")
    assert database(game[1]) == before


def test_missing_live_master_default_uses_valid_favorite_then_character_default(game):
    master(game, "Character", lambda rows: rows[0].update(defaultLiveCostumeId=""))
    def change(snapshot):
        slot(snapshot).ClearField("costumeId")
        slot(snapshot).ClearField("hairId")
        character(snapshot).ClearField("liveCostumeId")
    mutate(game, change)
    assert response(game).characterAssets[0].costumeId == "cos-a-selected"
    mutate(game, lambda snapshot: setattr(character(snapshot), "favoriteCostumeId", "missing"))
    assert response(game).characterAssets[0].costumeId == "cos-a-default"


def test_costume_override_with_empty_or_incompatible_hair_uses_selected_costume_default(game):
    mutate(game, lambda snapshot: slot(snapshot).ClearField("hairId"))
    assert response(game).characterAssets[0].hairId == "hair-a-selected"
    mutate(game, lambda snapshot: setattr(slot(snapshot), "hairId", "hair-a-default"))
    assert response(game).characterAssets[0].hairId == "hair-a-selected"


@pytest.mark.parametrize("allowed,denied,expected", [
    ([], [], "hair-a-default"),
    ([], ["cos-a-default"], "hair-a-default"),
    ([], ["cos-a-selected"], "hair-a-selected"),
    (["cos-a-default"], ["cos-a-default"], "hair-a-default"),
    (["cos-a-selected"], ["cos-a-selected"], "hair-a-default"),
])
def test_hair_whitelist_blacklist_follow_native_compatibility(game, allowed, denied, expected):
    def change(rows):
        row = next(row for row in rows if row["id"] == "hair-a-default")
        row.update(wearableCostumeIds=allowed, notWearableCostumeIds=denied)
    master(game, "Hair", change)
    mutate(game, lambda snapshot: setattr(slot(snapshot), "hairId", "hair-a-default"))
    assert response(game).characterAssets[0].hairId == expected


@pytest.mark.parametrize("kind", ["costume", "hair"])
def test_unowned_explicit_overrides_are_rejected_instead_of_silently_defaulting(game, kind):
    def change(snapshot):
        rows = snapshot.costumes if kind == "costume" else snapshot.hairs
        field = kind + "Id"
        identity = ("cos" if kind == "costume" else "hair") + "-a-selected"
        kept = [row for row in rows if getattr(row, field) != identity]
        del rows[:]
        rows.extend(kept)
    mutate(game, change)
    before = database(game[1])
    with pytest.raises(RpcFailure) as caught:
        response(game)
    assert caught.value.code == RpcCode.FAILED_PRECONDITION
    assert database(game[1]) == before


def test_two_distinct_cards_of_the_same_character_are_valid_asset_references(game):
    master(game, "Card", lambda rows: rows[1].update(characterId="char-a"))
    def change(snapshot):
        slot(snapshot, 2).costumeId, slot(snapshot, 2).hairId = "cos-a-selected", "hair-a-selected"
    mutate(game, change)
    result = response(game)
    assert [row.characterId for row in result.characterAssets[:2]] == ["char-a", "char-a"]


@pytest.mark.parametrize("change", [
    lambda snapshot: snapshot.deckPositions.pop(),
    lambda snapshot: setattr(slot(snapshot), "position", 0),
    lambda snapshot: setattr(slot(snapshot), "position", 2),
    lambda snapshot: setattr(slot(snapshot), "cardId", "missing"),
    lambda snapshot: setattr(slot(snapshot), "cardId", "card-b"),
    lambda snapshot: setattr(slot(snapshot), "costumeId", "missing"),
    lambda snapshot: setattr(slot(snapshot), "costumeId", "cos-b-selected"),
    lambda snapshot: setattr(slot(snapshot), "hairId", "hair-b-selected"),
    lambda snapshot: slot(snapshot).photoIds.append("missing"),
    lambda snapshot: slot(snapshot, 2).photoIds.append("photo-1"),
    lambda snapshot: setattr(slot(snapshot, 2), "part1AccessoryId", "accessory-1"),
    lambda snapshot: setattr(slot(snapshot), "part1AccessoryId", "missing"),
])
def test_invalid_saved_references_fail_without_mutation(game, change):
    mutate(game, change)
    before = database(game[1])
    with pytest.raises(RpcFailure) as caught:
        response(game)
    assert caught.value.code == RpcCode.FAILED_PRECONDITION
    assert database(game[1]) == before


@pytest.mark.parametrize("values", [{"questId": "missing"}, {"questId": ""}, {"deckNumber": 0},
                                   {"deckNumber": -1}, {"deckNumber": 99}])
def test_invalid_request_references_fail_explicitly(game, values):
    query = request(game)
    for key, value in values.items():
        setattr(query, key, value)
    with pytest.raises(RpcFailure) as caught:
        response(game, query)
    assert caught.value.code == RpcCode.INVALID_ARGUMENT


def test_malformed_request_schema_mismatch_and_unimplemented_battle_stay_distinct(game):
    with pytest.raises(RpcFailure) as caught:
        game[0].handle(PATH, b"\xff")
    assert caught.value.code == RpcCode.INVALID_ARGUMENT
    assert game[0].handle("/api.Quest/Start", b"") is None
    game[1].save_snapshot("player", b"", "different-schema")
    with pytest.raises(RpcFailure, match="different schema"):
        response(game)
