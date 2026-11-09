"""Canonical initial reward projection, with no network or live-account input."""
import json
from pathlib import Path

from google.protobuf import descriptor_pb2
import pytest

from idoly_local.initial_inventory import apply_initial_inventory, prepare_initial_inventory
from idoly_local.rpc import RpcCode, RpcFailure
from idoly_local.schema import Schema


def minimal_schema(path):
    file = descriptor_pb2.FileDescriptorProto(name="initial-inventory-test.proto", package="api", syntax="proto3")
    def message(name, fields):
        result = file.message_type.add(name=name)
        for number, (name, kind, repeated) in enumerate(fields, 1):
            field = result.field.add(name=name, number=number, label=3 if repeated else 1)
            if isinstance(kind, int):
                field.type = kind
            else:
                field.type, field.type_name = 11, ".api." + kind
    def scalar(kind, names):
        return [(name, kind, False) for name in names.split()]
    message("Empty", [])
    message("Manager", scalar(9, "name") + scalar(5, "managerLevel"))
    message("Character", scalar(9, "characterId"))
    message("Costume", scalar(9, "costumeId"))
    message("Hair", scalar(9, "hairId"))
    message("Item", scalar(9, "itemId") + scalar(3, "amount expiredTime"))
    message("Balance", scalar(3, "gold stone"))
    message("Tutorial", scalar(5, "tutorialType step"))
    card_fields = scalar(9, "cardId skillId1 skillId2 skillId3 skillId4 liveAbilityId activityAbilityId "
                         "baseSkillId1 baseSkillId2 baseSkillId3 baseSkillId4 baseLiveAbilityId baseActivityAbilityId")
    card_fields += scalar(5, "rarityTotalExp rankTotalExp displayType level rarity rank evolutionLevel "
                          "skillLevel1 skillLevel2 skillLevel3 skillLevel4 liveAbilityLevel activityAbilityLevel "
                          "photoEquipableCount baseLevel baseSkillLevel1 baseSkillLevel2 baseSkillLevel3 "
                          "baseSkillLevel4 baseLiveAbilityLevel baseActivityAbilityLevel basePhotoEquipableCount")
    card_fields += scalar(3, "totalExp obtainedTime lastEnhanceTime evolutionLevelTotalExp vocal dance visual "
                          "stamina mental technique baseVocal baseDance baseVisual baseStamina")
    card_fields += scalar(8, "supported")
    message("Card", card_fields)
    message("UserGetResponse", [("user", "Manager", False), ("balance", "Balance", False)] + [
        (name, kind, True) for name, kind in [("characters", "Character"), ("costumes", "Costume"),
            ("hairs", "Hair"), ("items", "Item"), ("cards", "Card"), ("tutorials", "Tutorial")]])
    file.service.add(name="System").method.add(name="Check", input_type=".api.Empty", output_type=".api.Empty")
    file.service.add(name="User").method.add(name="Get", input_type=".api.Empty", output_type=".api.UserGetResponse")
    result = descriptor_pb2.FileDescriptorSet()
    result.file.add().CopyFrom(file)
    path.write_bytes(result.SerializeToString())
    return Schema.from_descriptor_set(path)


@pytest.fixture(scope="module", params=("minimal", "client-6.1.1"))
def schema(request, tmp_path_factory):
    if request.param == "minimal":
        return minimal_schema(tmp_path_factory.mktemp("initial-schema") / "schema.pb")
    path = Path(__file__).resolve().parents[1] / "data/protocol/idolypride-6.1.1.pb"
    if not path.is_file():
        pytest.skip("Optional recovered client descriptor is unavailable")
    return Schema.from_descriptor_set(path)


@pytest.fixture
def prepared(schema, tmp_path):
    root = tmp_path / "master"
    root.mkdir()
    identities = ["a", "b", "c", "d", "e"]
    resources = [{"resourceType": 4, "resourceId": "char-" + key, "amount": 1} for key in identities]
    # Card order deliberately differs: never zip the two resource lists.
    resources += [{"resourceType": 2, "resourceId": "card-" + key, "amount": 1} for key in reversed(identities)]
    resources += [{"resourceType": 1, "resourceId": "film", "amount": 1},
                  {"resourceType": 1, "resourceId": "enhance", "amount": 100}]
    rows = {
        "Reward": [{"id": "initial_user_reward", "resources": resources},
                   {"id": "initial_user_gift", "resources": [{"resourceType": 15, "resourceId": "", "amount": 3000}]}],
        "Character": [{"id": "char-" + key, "defaultCostumeId": "costume-" + key,
                       "defaultLiveCostumeId": "costume-" + key} for key in identities],
        "Costume": [{"id": "costume-" + key, "characterId": "char-" + key,
                     "defaultHairId": "hair-" + key} for key in identities],
        "Hair": [{"id": "hair-" + key, "characterId": "char-" + key} for key in identities],
        "Item": [{"id": "film"}, {"id": "enhance"}],
        "Card": [{"id": "card-" + key, "characterId": "char-" + key, "initialRarity": 3,
                  "cardParameterId": "parameters", "cardLevelReleaseId": "release",
                  "vocalRatioPermil": 400, "danceRatioPermil": 320, "visualRatioPermil": 280,
                  "staminaRatioPermil": 1000, "skillId1": "skill-1", "skillId2": "skill-2",
                  "skillId3": "skill-3", "skillId4": "skill-4", "liveAbilityId": "live-ability",
                  "activityAbilityId": "activity-ability", "rewardCostumeId": "costume-" + key,
                  "rewardHairIds": ["hair-" + key]} for key in identities],
        "CardParameter": [{"id": "parameters", "level": 1, "value": "213", "staminaValue": "850"},
                          {"id": "parameters", "level": 2, "value": "300", "staminaValue": "900"}],
        "CardRarity": [{"rarity": 3, "parameterBonusPermil": 1100}],
        "CardLevelRelease": [{"id": "release", "level": 1, "targets": [
            {"type": 1, "number": 1}, {"type": 4, "number": 1}, {"type": 7, "number": 2}]},
            {"id": "release", "level": 20, "targets": [{"type": 1, "number": 2}]},
            {"id": "release", "level": 30, "targets": [{"type": 2, "number": 1}]}],
        "Skill": [{"id": "skill-1", "levels": [{"level": 1, "requiredCardLevel": 1}]},
                  {"id": "skill-2", "levels": [{"level": 1, "requiredCardLevel": 20}]},
                  {"id": "skill-3", "levels": [{"level": 1, "requiredCardLevel": 80}]},
                  {"id": "skill-4", "levels": [{"level": 1, "requiredCardLevel": 120}]}],
        "Setting": [{"cardDefaultMental": 100, "cardDefaultTechnique": 100}],
    }
    for table, data in rows.items():
        (root / (table + ".json")).write_text(json.dumps(data))
    snapshot = schema.response_type("/api.User/Get")()
    snapshot.user.name = "Existing local manager"
    snapshot.user.managerLevel = 1
    balance_field = next(field for field in snapshot.balance.DESCRIPTOR.fields if field.type in (3, 5))
    setattr(snapshot.balance, balance_field.name, 123)
    snapshot.tutorials.add(tutorialType=1, step=10)
    for key in identities:
        snapshot.characters.add(characterId="char-" + key)
        snapshot.costumes.add(costumeId="costume-" + key)
        snapshot.hairs.add(hairId="hair-" + key)
    # The apply operation must preserve fields it does not interpret.
    snapshot.ParseFromString(snapshot.SerializeToString() + b"\xf8\x7f\x01")
    return schema, root, rows, snapshot


def plan(prepared):
    return prepare_initial_inventory(prepared[0], prepared[1])


def test_prepare_is_read_only_and_respects_reward_owners_not_entry_order(prepared):
    original = prepared[3].SerializeToString()
    inventory = plan(prepared)
    assert inventory.character_ids == tuple("char-" + key for key in "abcde")
    assert inventory.card_ids == tuple("card-" + key for key in "edcba")
    assert dict(inventory.card_by_character) == {"char-" + key: "card-" + key for key in "abcde"}
    assert inventory.item_amounts == (("film", 1), ("enhance", 100))
    with pytest.raises(TypeError):
        inventory.card_by_character["char-a"] = "different"
    assert prepared[3].SerializeToString() == original


def test_apply_initial_cards_matches_two_floor_native_stats_and_preserves_other_state(prepared):
    inventory, snapshot = plan(prepared), prepared[3]
    original = prepared[0].response_type("/api.User/Get")()
    original.CopyFrom(snapshot)
    apply_initial_inventory(snapshot, inventory, obtained_time=123456789)
    assert len(snapshot.cards) == 5
    for card in snapshot.cards:
        assert (card.level, card.baseLevel, card.rarity, card.displayType) == (1, 1, 3, 1)
        assert (card.vocal, card.dance, card.visual, card.stamina) == (93, 74, 64, 935)
        assert (card.baseVocal, card.baseDance, card.baseVisual, card.baseStamina) == (93, 74, 64, 935)
        assert (card.mental, card.technique, card.photoEquipableCount, card.basePhotoEquipableCount) == (100, 100, 2, 2)
        assert card.obtainedTime == 123456789 and not card.supported
        assert not any((card.totalExp, card.rarityTotalExp, card.rankTotalExp, card.rank,
                        card.evolutionLevelTotalExp, card.evolutionLevel, card.lastEnhanceTime))
    assert [(row.itemId, row.amount, row.expiredTime) for row in snapshot.items] == [("film", 1, 0), ("enhance", 100, 0)]
    restored = prepared[0].response_type("/api.User/Get")()
    restored.CopyFrom(snapshot)
    del restored.cards[:]
    del restored.items[:]
    assert restored.SerializeToString() == original.SerializeToString()


def test_level_one_unlocks_only_first_skill_in_current_and_base_fields(prepared):
    apply_initial_inventory(prepared[3], plan(prepared), obtained_time=1)
    for card in prepared[3].cards:
        assert card.skillId1 == card.baseSkillId1 == "skill-1"
        assert card.skillLevel1 == card.baseSkillLevel1 == 1
        for number in (2, 3, 4):
            assert getattr(card, "skillId" + str(number)) == getattr(card, "baseSkillId" + str(number)) == ""
            assert getattr(card, "skillLevel" + str(number)) == getattr(card, "baseSkillLevel" + str(number)) == 0
        for prefix in ("live", "activity"):
            assert getattr(card, prefix + "AbilityId") == getattr(card, "base" + prefix.capitalize() + "AbilityId") == ""
            assert getattr(card, prefix + "AbilityLevel") == getattr(card, "base" + prefix.capitalize() + "AbilityLevel") == 0


def test_photo_release_numbers_add_slots_instead_of_taking_maximum(prepared):
    prepared[2]["CardLevelRelease"][0]["targets"].append({"type": 7, "number": 1})
    (prepared[1] / "CardLevelRelease.json").write_text(json.dumps(prepared[2]["CardLevelRelease"]))
    apply_initial_inventory(prepared[3], plan(prepared), obtained_time=1)
    assert all(card.photoEquipableCount == card.basePhotoEquipableCount == 3 for card in prepared[3].cards)


@pytest.mark.parametrize("table,change", [
    ("Reward", lambda rows: rows[0].update(id="wrong-reward")),
    ("Reward", lambda rows: rows[0]["resources"].append({"resourceType": 15, "resourceId": "stone", "amount": 3000})),
    ("Reward", lambda rows: rows[0]["resources"][0].update(amount=2)),
    ("Reward", lambda rows: rows[0]["resources"].append(dict(rows[0]["resources"][0]))),
    ("Card", lambda rows: rows[0].update(characterId="char-b")),
    ("Card", lambda rows: rows[0].update(cardParameterId="missing")),
    ("Card", lambda rows: rows[0].update(vocalRatioPermil=-1)),
    ("Card", lambda rows: rows[0].update(initialRarity=99)),
    ("Card", lambda rows: rows[0].update(skillId1="missing")),
    ("Card", lambda rows: rows[0].update(skillId2="missing")),
    ("Card", lambda rows: rows[0].update(rewardCostumeId="costume-b")),
    ("Card", lambda rows: rows[0].update(rewardHairIds=["hair-b"])),
    ("CardParameter", lambda rows: rows.append(dict(rows[0]))),
    ("CardParameter", lambda rows: rows[0].update(value=True)),
    ("CardRarity", lambda rows: rows.append(dict(rows[0]))),
    ("CardLevelRelease", lambda rows: rows[0].update(targets=[])),
    ("CardLevelRelease", lambda rows: rows[0]["targets"].append({"type": 2, "number": 1})),
    ("Skill", lambda rows: rows[0]["levels"][0].update(requiredCardLevel=20)),
    ("Skill", lambda rows: rows[0]["levels"].append(dict(rows[0]["levels"][0]))),
    ("Item", lambda rows: rows.pop()),
    ("Setting", lambda rows: rows[0].update(cardDefaultMental=-1)),
])
def test_invalid_canonical_definitions_fail_before_changing_snapshot(prepared, table, change):
    original = prepared[3].SerializeToString()
    change(prepared[2][table])
    (prepared[1] / (table + ".json")).write_text(json.dumps(prepared[2][table]))
    with pytest.raises(RpcFailure) as caught:
        plan(prepared)
    assert caught.value.code == RpcCode.FAILED_PRECONDITION
    assert prepared[3].SerializeToString() == original


@pytest.mark.parametrize("change", [
    lambda snapshot: snapshot.cards.add(cardId="existing"),
    lambda snapshot: snapshot.items.add(itemId="existing", amount=1),
    lambda snapshot: snapshot.characters.pop(),
    lambda snapshot: snapshot.characters.add(characterId="char-a"),
    lambda snapshot: snapshot.costumes.pop(),
    lambda snapshot: snapshot.hairs.pop(),
])
def test_apply_rejects_nonempty_or_unprepared_inventory_atomically(prepared, change):
    inventory = plan(prepared)
    change(prepared[3])
    original = prepared[3].SerializeToString()
    with pytest.raises(RpcFailure) as caught:
        apply_initial_inventory(prepared[3], inventory, obtained_time=1)
    assert caught.value.code == RpcCode.FAILED_PRECONDITION
    assert prepared[3].SerializeToString() == original


def test_second_application_does_not_duplicate_resources(prepared):
    inventory = plan(prepared)
    apply_initial_inventory(prepared[3], inventory, obtained_time=1)
    original = prepared[3].SerializeToString()
    with pytest.raises(RpcFailure):
        apply_initial_inventory(prepared[3], inventory, obtained_time=2)
    assert prepared[3].SerializeToString() == original


@pytest.mark.parametrize("timestamp", [0, -1, True, "1", 1 << 64])
def test_invalid_obtained_time_does_not_partly_apply(prepared, timestamp):
    original = prepared[3].SerializeToString()
    with pytest.raises(RpcFailure):
        apply_initial_inventory(prepared[3], plan(prepared), obtained_time=timestamp)
    assert prepared[3].SerializeToString() == original
