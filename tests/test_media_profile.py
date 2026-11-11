"""Explicit media inventory stays master-backed and preserves existing rows."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from idoly_local.media_profile import apply_media_inventory, prepare_media_inventory
from idoly_local.rpc import RpcCode, RpcFailure
from idoly_local.schema import Schema


UNKNOWN = b"\x80\x4b\x7b"
NOW = 1794412800000


@pytest.fixture(scope="module")
def schema():
    source = Path(__file__).resolve().parents[1] / "data/protocol/idolypride-6.1.1.pb"
    if not source.is_file():
        pytest.skip("Recovered 6.1.1 descriptor is unavailable")
    return Schema.from_descriptor_set(source)


@pytest.fixture
def master(tmp_path):
    directory = tmp_path / "master"
    directory.mkdir()
    rows = {
        "Character": [{"id": "char-" + key, "type": kind,
                       "defaultCostumeId": "cos-" + key, "defaultLiveCostumeId": "cos-" + key,
                       "viewConditionId": "unresolved-view", "unlockConditionId": "unresolved-unlock"}
                      for key, kind in (("a", 1), ("mana", 3), ("collab", 4))],
        "Costume": [{"id": "cos-" + key, "characterId": "char-" + key,
                     "defaultHairId": "hair-" + key, "isUserUnavailable": False}
                    for key in ("a", "mana", "collab")],
        "Hair": [{"id": "hair-" + key, "characterId": "char-" + key,
                  "wearableCostumeIds": ["cos-" + key], "notWearableCostumeIds": []}
                 for key in ("a", "mana", "collab")],
        "Setting": [{"id": 1, "cardDefaultMental": 100, "cardDefaultTechnique": 100}],
        "CharacterActivityLevel": [{"level": 1, "maxStamina": 800}],
        "CardLevel": [{"level": 1, "requiredExp": "0"}],
        "CardParameter": [{"id": "parameter", "level": 1, "value": "213", "staminaValue": "850"}],
        "CardRarity": [{"rarity": 3, "parameterBonusPermil": 1100, "requiredExp": 35},
                       {"rarity": 5, "parameterBonusPermil": 1200, "requiredExp": 110}],
        "CardLevelRelease": [{"id": "release", "level": 1,
            "targets": [{"type": 1, "number": 1}, {"type": 4, "number": 1}, {"type": 7, "number": 2}]}],
        "Card": [], "Skill": [],
    }
    # NPCs can point at another actor's costume and must not be made playable.
    rows["Character"].append({"id": "char-npc", "type": 2, "defaultCostumeId": "cos-a"})
    rows["Costume"].extend([
        {"id": "cos-a-alt", "characterId": "char-a", "defaultHairId": "hair-a-alt",
         "isUserUnavailable": False, "isDisableAdmin": True},
        {"id": "cos-a-scene", "characterId": "char-a", "defaultHairId": "hair-a-scene",
         "isUserUnavailable": True},
    ])
    rows["Hair"].extend([
        {"id": "hair-a-alt", "characterId": "char-a", "wearableCostumeIds": ["cos-a-alt"],
         "notWearableCostumeIds": [], "isDisableAdmin": True},
        {"id": "hair-a-scene", "characterId": "char-a", "wearableCostumeIds": ["cos-a-scene"]},
        # Exact native rule: a nonmatching blacklist allows an outfit even
        # when its whitelist is not empty and does not contain that outfit.
        {"id": "hair-a-mixed", "characterId": "char-a", "wearableCostumeIds": ["cos-a-scene"],
         "notWearableCostumeIds": ["cos-a-scene"]},
    ])
    for key, owner, rarity in (("a", "a", 3), ("a-other", "a", 5),
                               ("mana", "mana", 5), ("collab", "collab", 5)):
        rows["Card"].append({"id": "card-" + key, "characterId": "char-" + owner,
            "initialRarity": rarity, "cardParameterId": "parameter", "cardLevelReleaseId": "release",
            "vocalRatioPermil": 404, "danceRatioPermil": 316, "visualRatioPermil": 280,
            "staminaRatioPermil": 1000, "skillId1": "skill-" + key, "skillId2": "locked-" + key,
            "skillId3": "", "skillId4": "", "liveAbilityId": "not-yet-learned",
            "activityAbilityId": "not-yet-learned"})
        rows["Skill"].extend([
            {"id": "skill-" + key, "levels": [{"level": 1, "requiredCardLevel": 1}]},
            {"id": "locked-" + key, "levels": [{"level": 1, "requiredCardLevel": 20}]},
        ])
    for name, values in rows.items():
        (directory / (name + ".json")).write_text(json.dumps(values))
    (directory / "!version.txt").write_text("synthetic-media-master")
    return directory, rows


@pytest.fixture
def snapshot(schema):
    result = schema.response_type("/api.User/Get")()
    result.user.name = "Keep manager"
    result.user.managerLevel = 3
    result.user.deckSequence = 4
    result.userPublic.serverUserId = "own-server"
    result.userPublic.publicUserId = "own-public"
    result.points.add(pointType=1, amount=77)
    result.tutorials.add(tutorialType=1, step=10)
    result.quests.add(questId="keep-quest", lastClearedTime=123)
    result.items.add(itemId="keep-item", amount=9)
    result.photos.add(photoId="keep-photo", locked=True)
    result.decks.add(number=4, name="Keep deck")
    result.characters.add(characterId="char-a", favoriteCostumeId="cos-a-alt",
        favoriteHairId="hair-a-alt", liveCostumeId="cos-a", liveHairId="hair-a", activityLevel=7)
    result.costumes.add(costumeId="cos-a-alt", obtainedTime=99, checked=False)
    result.hairs.add(hairId="hair-a-alt", checked=False)
    result.cards.add(cardId="card-a", level=9, totalExp=123, vocal=999).MergeFromString(UNKNOWN)
    result.MergeFromString(UNKNOWN)
    return result


def rewrite(master, table, change):
    directory, rows = master
    values = deepcopy(rows[table])
    change(values)
    (directory / (table + ".json")).write_text(json.dumps(values))


def test_prepares_all_card_owners_and_usable_appearances_without_progression(schema, master):
    plan = prepare_media_inventory(schema, master[0])
    assert plan.character_ids == ("char-a", "char-collab", "char-mana")
    assert len(plan.card_ids) == 4
    assert plan.costume_ids == ("cos-a", "cos-a-alt", "cos-collab", "cos-mana")
    assert plan.hair_ids == ("hair-a", "hair-a-alt", "hair-a-mixed", "hair-collab", "hair-mana")
    assert plan.master_version == "synthetic-media-master"
    assert plan.schema_fingerprint == schema.fingerprint


def test_append_preserves_every_existing_row_and_other_snapshot_field(schema, master, snapshot):
    plan = prepare_media_inventory(schema, master[0])
    before = snapshot.SerializeToString()
    existing = {name: {getattr(row, field): row.SerializeToString() for row in getattr(snapshot, name)}
                for name, field in (("characters", "characterId"), ("costumes", "costumeId"),
                                    ("hairs", "hairId"), ("cards", "cardId"))}
    assert apply_media_inventory(snapshot, plan, obtained_time=NOW)
    assert len(snapshot.characters) == 3 and len(snapshot.cards) == 4
    assert len(snapshot.costumes) == 4 and len(snapshot.hairs) == 5
    for name, field in (("characters", "characterId"), ("costumes", "costumeId"),
                        ("hairs", "hairId"), ("cards", "cardId")):
        current = {getattr(row, field): row for row in getattr(snapshot, name)}
        for identity, raw in existing[name].items():
            assert current[identity].SerializeToString() == raw
        kept = [row for row in getattr(snapshot, name) if getattr(row, field) in existing[name]]
        del getattr(snapshot, name)[:]
        getattr(snapshot, name).extend(kept)
    assert snapshot.SerializeToString() == before


def test_new_cards_have_real_initial_rarity_xp_two_floors_and_only_released_skills(schema, master, snapshot):
    plan = prepare_media_inventory(schema, master[0])
    apply_media_inventory(snapshot, plan, obtained_time=NOW)
    card = next(row for row in snapshot.cards if row.cardId == "card-mana")
    assert card.level == card.baseLevel == 1 and card.rarity == 5 and card.rarityTotalExp == 110
    assert card.vocal == card.baseVocal == ((213 * 404) // 1000 * 1200) // 1000
    assert card.stamina == card.baseStamina == 1020
    assert card.mental == card.technique == 100
    assert card.skillId1 == card.baseSkillId1 == "skill-mana"
    assert card.skillLevel1 == card.baseSkillLevel1 == 1
    assert not card.skillId2 and not card.baseSkillId2 and card.skillLevel2 == 0
    assert not card.liveAbilityId and not card.activityAbilityId
    assert card.photoEquipableCount == card.basePhotoEquipableCount == 2
    assert card.obtainedTime == NOW
    assert not snapshot.balance.freeBalance and snapshot.quests[0].lastClearedTime == 123


def test_repeat_is_byte_identical_and_does_not_restore_user_preferences(schema, master, snapshot):
    plan = prepare_media_inventory(schema, master[0])
    assert apply_media_inventory(snapshot, plan, obtained_time=NOW)
    snapshot.characters[1].favoriteCostumeId = "keep-choice"
    before = snapshot.SerializeToString()
    assert not apply_media_inventory(snapshot, plan, obtained_time=NOW + 1000)
    assert snapshot.SerializeToString() == before


@pytest.mark.parametrize("table,change", [
    ("Card", lambda values: values[0].update(characterId="char-npc")),
    ("Card", lambda values: values[0].update(cardParameterId="missing")),
    ("Card", lambda values: values[0].update(initialRarity=10)),
    ("Card", lambda values: values[0].update(skillId1="missing")),
    ("Card", lambda values: values.append(deepcopy(values[0]))),
    ("Costume", lambda values: values[0].update(defaultHairId="hair-mana")),
    ("Costume", lambda values: values[0].update(isUserUnavailable=True)),
    ("Hair", lambda values: values[0].update(wearableCostumeIds=["cos-mana"])),
    ("CardLevelRelease", lambda values: values[0]["targets"].append({"type": 2, "number": 1})),
    ("CardRarity", lambda values: values[0].update(requiredExp=-1)),
    ("CardRarity", lambda values: values[1].update(requiredExp=35)),
])
def test_invalid_master_is_rejected_before_any_snapshot_or_database_access(schema, master, snapshot, table, change):
    before = snapshot.SerializeToString()
    rewrite(master, table, change)
    with pytest.raises(RpcFailure) as error:
        prepare_media_inventory(schema, master[0])
    assert error.value.code == RpcCode.FAILED_PRECONDITION
    assert snapshot.SerializeToString() == before


@pytest.mark.parametrize("field,identity", [("characters", "characterId"), ("costumes", "costumeId"),
                                            ("hairs", "hairId"), ("cards", "cardId")])
def test_duplicate_existing_ownership_fails_without_partial_additions(schema, master, snapshot, field, identity):
    plan = prepare_media_inventory(schema, master[0])
    getattr(snapshot, field).add().CopyFrom(getattr(snapshot, field)[0])
    before = snapshot.SerializeToString()
    with pytest.raises(RpcFailure):
        apply_media_inventory(snapshot, plan, obtained_time=NOW)
    assert snapshot.SerializeToString() == before


@pytest.mark.parametrize("obtained_time", [True, 0, -1, "123", 1 << 63])
def test_invalid_timestamp_does_not_touch_snapshot(schema, master, snapshot, obtained_time):
    plan = prepare_media_inventory(schema, master[0])
    before = snapshot.SerializeToString()
    with pytest.raises(RpcFailure):
        apply_media_inventory(snapshot, plan, obtained_time=obtained_time)
    assert snapshot.SerializeToString() == before
