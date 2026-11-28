"""Explicit media inventory stays master-backed and preserves existing rows."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from idoly_local.media_profile import apply_media_inventory, prepare_media_inventory
from idoly_local.media_outfit_policy import (
    ADMIN_COSTUME_IDS, ADMIN_HAIR_IDS, COSTUME_IDS, is_audited_work_costume,
    is_audited_admin_costume, is_audited_admin_hair,
)
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
        favoriteHairId="hair-a-alt", liveCostumeId="cos-a", liveHairId="hair-a", activityLevel=7,
        audienceCandidateAmount=123)
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


@pytest.fixture
def work_master(master):
    directory, original = master
    rows = deepcopy(original)
    rows["Character"].append({"id": "char-ai", "type": 1,
        "defaultCostumeId": "cos-ai", "defaultLiveCostumeId": "cos-ai"})
    card = deepcopy(rows["Card"][0])
    card.update(id="card-ai", characterId="char-ai")
    rows["Card"].append(card)
    rows["Costume"].extend([
        {"id": "cos-ai", "characterId": "char-ai", "defaultHairId": "hair-ai",
         "isUserUnavailable": False},
        {"id": "cos-ai-mizg-00", "characterId": "char-ai", "costumeTypeId": "mizg",
         "bodyAssetId": "ai-mizg-00", "defaultHairId": "hair-ai-mizg-00",
         "isUserUnavailable": True, "isDisableAdmin": False},
        {"id": "cos-ai-sdam-00", "characterId": "char-ai", "costumeTypeId": "sd-ambassador",
         "bodyAssetId": "ai-sdam-00", "defaultHairId": "hair-ai-sdam-00",
         "isUserUnavailable": True, "isDisableAdmin": False},
        {"id": "cos-npc-mizg-00", "characterId": "char-npc", "costumeTypeId": "mizg",
         "bodyAssetId": "npc-mizg-00", "defaultHairId": "hair-npc-mizg-00",
         "isUserUnavailable": True, "isDisableAdmin": False},
    ])
    for suffix in ("ai", "ai-mizg-00", "ai-sdam-00", "npc-mizg-00"):
        rows["Hair"].append({"id": "hair-" + suffix,
            "characterId": "char-npc" if suffix.startswith("npc-") else "char-ai",
            "wearableCostumeIds": ["cos-" + suffix], "notWearableCostumeIds": []})
    for table, values in rows.items():
        (directory / (table + ".json")).write_text(json.dumps(values))
    return directory, rows


def test_prepares_all_card_owners_and_usable_appearances_without_progression(schema, master):
    plan = prepare_media_inventory(schema, master[0])
    assert plan.character_ids == ("char-a", "char-collab", "char-mana")
    assert len(plan.card_ids) == 4
    assert plan.costume_ids == ("cos-a", "cos-a-alt", "cos-collab", "cos-mana")
    assert plan.hair_ids == ("hair-a", "hair-a-alt", "hair-a-mixed", "hair-collab", "hair-mana")
    assert plan.master_version == "synthetic-media-master"
    assert plan.schema_fingerprint == schema.fingerprint


def test_audited_bath_outfit_and_its_hair_are_added_but_sd_and_npc_models_are_not(
        schema, work_master, snapshot):
    directory, rows = work_master
    before_sources = {source.name: source.read_bytes() for source in directory.iterdir()}
    plan = prepare_media_inventory(schema, directory)
    assert "cos-ai-mizg-00" in plan.costume_ids and "hair-ai-mizg-00" in plan.hair_ids
    assert "cos-ai-sdam-00" not in plan.costume_ids and "hair-ai-sdam-00" not in plan.hair_ids
    assert "cos-npc-mizg-00" not in plan.costume_ids and "hair-npc-mizg-00" not in plan.hair_ids
    # Upgrade an existing media inventory. Keep its chosen outfit, old row
    # payloads/unknown fields and every unrelated balance/progression field.
    snapshot.characters.add(characterId="char-ai", favoriteCostumeId="cos-ai",
        favoriteHairId="hair-ai", liveCostumeId="cos-ai", liveHairId="hair-ai",
        audienceCandidateAmount=42)
    snapshot.costumes.add(costumeId="cos-ai", checked=False, obtainedTime=123).MergeFromString(UNKNOWN)
    snapshot.hairs.add(hairId="hair-ai", checked=False).MergeFromString(UNKNOWN)
    expected = type(snapshot)()
    expected.CopyFrom(snapshot)
    for character in expected.characters:
        character.audienceCandidateAmount = 1000
    assert apply_media_inventory(snapshot, plan, obtained_time=NOW)
    assert next(row for row in snapshot.costumes if row.costumeId == "cos-ai-mizg-00").checked
    assert next(row for row in snapshot.hairs if row.hairId == "hair-ai-mizg-00").checked
    current_ai = next(row for row in snapshot.characters if row.characterId == "char-ai")
    assert current_ai == next(row for row in expected.characters if row.characterId == "char-ai")
    once = snapshot.SerializeToString()
    assert not apply_media_inventory(snapshot, plan, obtained_time=NOW + 1000)
    assert snapshot.SerializeToString() == once
    for field, identity in (("characters", "characterId"), ("costumes", "costumeId"),
                            ("hairs", "hairId"), ("cards", "cardId")):
        originals = {getattr(row, identity): row for row in getattr(expected, field)}
        kept = [row for row in getattr(snapshot, field) if getattr(row, identity) in originals]
        assert all(row == originals[getattr(row, identity)] for row in kept)
        del getattr(snapshot, field)[:]
        getattr(snapshot, field).extend(kept)
    assert snapshot == expected
    assert {source.name: source.read_bytes() for source in directory.iterdir()} == before_sources
    bath = next(row for row in rows["Costume"] if row["id"] == "cos-ai-mizg-00")
    assert bath["isUserUnavailable"] is True


@pytest.mark.parametrize("change", [
    {"characterId": "char-a"}, {"costumeTypeId": "sd-ambassador"},
    {"bodyAssetId": "missing-body"}, {"defaultHairId": "hair-a"},
    {"isDisableAdmin": True},
])
def test_audited_bath_definition_drift_fails_before_touching_snapshot(schema, work_master, snapshot, change):
    before = snapshot.SerializeToString()
    rewrite(work_master, "Costume", lambda rows: next(
        row for row in rows if row["id"] == "cos-ai-mizg-00").update(change))
    with pytest.raises(RpcFailure) as error:
        prepare_media_inventory(schema, work_master[0])
    assert error.value.code == RpcCode.FAILED_PRECONDITION
    assert snapshot.SerializeToString() == before


def test_audited_bath_still_requires_compatible_same_owner_default_hair(schema, work_master, snapshot):
    before = snapshot.SerializeToString()
    rewrite(work_master, "Hair", lambda rows: next(
        row for row in rows if row["id"] == "hair-ai-mizg-00").update(
            wearableCostumeIds=[], notWearableCostumeIds=["cos-ai-mizg-00"]))
    with pytest.raises(RpcFailure) as error:
        prepare_media_inventory(schema, work_master[0])
    assert error.value.code == RpcCode.FAILED_PRECONDITION
    assert snapshot.SerializeToString() == before


def test_actual_bath_policy_has_exact_original_3d_rows_and_expected_inventory_counts(schema):
    directory = Path(__file__).resolve().parents[1] / "data/master-json"
    if not (directory / "Costume.json").is_file():
        pytest.skip("Original public master catalog is unavailable")
    originals = json.loads((directory / "Costume.json").read_text())
    policy = [row for row in originals if row["id"] in COSTUME_IDS]
    assert len(policy) == len(COSTUME_IDS) == 21
    assert all(row["isUserUnavailable"] and is_audited_work_costume(row) for row in policy)
    plan = prepare_media_inventory(schema, directory)
    assert len(plan.costume_ids) == 921 and len(plan.hair_ids) == 1113
    assert COSTUME_IDS <= set(plan.costume_ids)
    assert {row["defaultHairId"] for row in policy} <= set(plan.hair_ids)
    excluded = {row["id"] for row in originals if row["costumeTypeId"] in ("sd-ambassador", "sd-police")}
    assert len(excluded) == 40 and not excluded.intersection(plan.costume_ids)
    admin_costumes = [row for row in originals if row["isDisableAdmin"]]
    assert {row["id"] for row in admin_costumes} == ADMIN_COSTUME_IDS
    assert len(admin_costumes) == 18 and all(is_audited_admin_costume(row) for row in admin_costumes)
    admin_hairs = [row for row in json.loads((directory / "Hair.json").read_text())
                   if row["isDisableAdmin"]]
    assert {row["id"] for row in admin_hairs} == ADMIN_HAIR_IDS
    assert len(admin_hairs) == 19 and all(is_audited_admin_hair(row) for row in admin_hairs)
    assert ADMIN_COSTUME_IDS <= set(plan.costume_ids)
    assert ADMIN_HAIR_IDS <= set(plan.hair_ids)


@pytest.mark.parametrize("field,value", (("characterId", "char-other"),
    ("bodyAssetId", "missing-body"), ("defaultHairId", "hair-other"),
    ("costumeTypeId", "sd-ambassador")))
def test_admin_costume_policy_checks_real_assets_and_owner(field, value):
    row = {"id": "cos-ai-buny-00", "characterId": "char-ai", "costumeTypeId": "idol",
           "bodyAssetId": "ai-buny-00", "defaultHairId": "hair-ai-buny-00",
           "isUserUnavailable": False, "isDisableAdmin": True}
    assert is_audited_admin_costume(row)
    row[field] = value
    assert not is_audited_admin_costume(row)


@pytest.mark.parametrize("field,value", (("characterId", "char-other"),
    ("hairAssetId", "missing-hair"), ("faceAssetId", "missing-face"),
    ("fittingCostumeId", "cos-other")))
def test_admin_hair_policy_checks_real_assets_owner_and_fitting_reference(field, value):
    row = {"id": "hair-kor-hair-00", "characterId": "char-kor", "hairAssetId": "kor-hair-00",
           "faceAssetId": "kor-base-00", "fittingCostumeId": "cos-kor-casl-00",
           "isDisableAdmin": True}
    assert is_audited_admin_hair(row)
    row[field] = value
    assert not is_audited_admin_hair(row)


def test_append_preserves_every_existing_row_and_other_snapshot_field(schema, master, snapshot):
    plan = prepare_media_inventory(schema, master[0])
    snapshot.characters[0].audienceCandidateAmount = 4321
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
    assert card.displayType == 2
    assert card.obtainedTime == NOW
    assert not snapshot.balance.freeBalance and snapshot.quests[0].lastClearedTime == 123


def test_new_cards_use_original_initial_rarity_display_stage(schema, master):
    snapshot = schema.response_type("/api.User/Get")()
    snapshot.user.name = "New media manager"
    plan = prepare_media_inventory(schema, master[0])
    assert apply_media_inventory(snapshot, plan, obtained_time=NOW)
    assert {row.cardId: row.displayType for row in snapshot.cards} == {
        "card-a": 1, "card-a-other": 2, "card-collab": 2, "card-mana": 2}


@pytest.mark.parametrize("low_rarity_choice", [1, 2])
@pytest.mark.parametrize("high_rarity_choice", [2, 3])
def test_existing_media_repairs_only_unavailable_initial_five_star_display_and_preserves_state(
        schema, master, snapshot, low_rarity_choice, high_rarity_choice):
    plan = prepare_media_inventory(schema, master[0])
    assert apply_media_inventory(snapshot, plan, obtained_time=NOW)
    cards = {row.cardId: row for row in snapshot.cards}
    # A low-initial-rarity card can grow to five stars and still keep display 1.
    cards["card-a"].rarity = 5
    cards["card-a"].displayType = low_rarity_choice
    cards["card-mana"].displayType = high_rarity_choice
    cards["card-collab"].displayType = 3
    invalid = cards["card-a-other"]
    invalid.displayType = 1
    invalid.level = 41
    invalid.totalExp = 9876
    invalid.rarity = 8
    invalid.evolutionLevel = 1
    invalid.obtainedTime = 123
    invalid.MergeFromString(UNKNOWN)
    snapshot.MergeFromString(UNKNOWN)
    expected = type(snapshot)()
    expected.CopyFrom(snapshot)
    next(row for row in expected.cards if row.cardId == "card-a-other").displayType = 2
    assert apply_media_inventory(snapshot, plan, obtained_time=NOW + 1000)
    assert snapshot.SerializeToString() == expected.SerializeToString()
    before = snapshot.SerializeToString()
    assert not apply_media_inventory(snapshot, plan, obtained_time=NOW + 2000)
    assert snapshot.SerializeToString() == before


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


@pytest.mark.parametrize("candidate", [-1, 0, 1, 10, 999])
def test_sparse_media_audience_is_repaired_without_fan_or_progress_changes(schema, master, snapshot, candidate):
    plan = prepare_media_inventory(schema, master[0])
    apply_media_inventory(snapshot, plan, obtained_time=NOW)
    actor = next(row for row in snapshot.characters if row.characterId == "char-a")
    actor.audienceCandidateAmount = candidate
    actor.lightFanAmount, actor.middleFanAmount, actor.heavyFanAmount = 11, 22, 33
    actor.MergeFromString(UNKNOWN)
    snapshot.characters.add(characterId="unrelated-npc", audienceCandidateAmount=0)
    positive = next(row for row in snapshot.characters if row.characterId == "char-mana")
    positive.audienceCandidateAmount = 4321
    expected = type(snapshot).FromString(snapshot.SerializeToString())
    next(row for row in expected.characters if row.characterId == "char-a").audienceCandidateAmount = 1000
    assert apply_media_inventory(snapshot, plan, obtained_time=NOW + 1)
    assert snapshot.SerializeToString() == expected.SerializeToString()
    before = snapshot.SerializeToString()
    assert not apply_media_inventory(snapshot, plan, obtained_time=NOW + 2)
    assert snapshot.SerializeToString() == before


def test_new_media_characters_have_positive_visual_audience_and_zero_actual_fans(schema, master):
    plan = prepare_media_inventory(schema, master[0])
    snapshot = schema.response_type("/api.User/Get")()
    snapshot.user.name = "Media"
    assert apply_media_inventory(snapshot, plan, obtained_time=NOW)
    assert all(row.audienceCandidateAmount == 1000 for row in snapshot.characters)
    assert all((row.lightFanAmount, row.middleFanAmount, row.heavyFanAmount) == (0, 0, 0)
               for row in snapshot.characters)


def test_real_mana_and_collaborators_receive_the_native_fan_average_minimum_without_invented_fans(schema):
    """Regression against the original getter's normal/special branch.

    The 6.1.1 native getter ignores special actors' raw candidate field. It
    derives candidates from the normal roster's average three fan tiers and
    the master minimum. Raising their raw zero/ten alone cannot fix this path.
    """
    from math import ceil
    from idoly_local.media_master_build import expanded_rows
    directory = Path(__file__).resolve().parents[1] / "data/master-json"
    if not (directory / "Character.json").is_file():
        pytest.skip("Original public master catalog is unavailable")
    sources = {name: json.loads((directory / (name + ".json")).read_text())
               for name in ("Character", "Card", "Setting")}
    original_setting = deepcopy(sources["Setting"])
    actors = {row["id"]: row for row in sources["Character"]}
    special = {"char-mna", "char-cca", "char-chk", "char-chn", "char-mku", "char-rik", "char-ymk", "char-yo"}
    owners = {row["characterId"] for row in sources["Card"]}
    assert special == {owner for owner in owners if actors[owner]["type"] in (3, 4)}
    plan = prepare_media_inventory(schema, directory)
    snapshot = schema.response_type("/api.User/Get")()
    snapshot.user.name = "Media"
    assert apply_media_inventory(snapshot, plan, obtained_time=NOW)
    characters = {row.characterId: row for row in snapshot.characters}
    normals = [characters[owner] for owner in owners if actors[owner]["type"] == 1]
    assert len(normals) == 20 and all(row.audienceCandidateAmount == 1000 for row in normals)

    def native_candidates(setting, owner):
        if actors[owner]["type"] == 1:
            return characters[owner].audienceCandidateAmount
        average_fans = [sum(getattr(row, tier + "FanAmount") for row in normals) // len(normals)
                        for tier in ("light", "middle", "heavy")]
        weights = [setting["live" + tier + "FanAmountWeightPermil"] for tier in ("Light", "Middle", "Heavy")]
        return max(setting["liveMinimumGuaranteedAudienceAmount"],
                   sum(amount * weight // 1000 for amount, weight in zip(average_fans, weights)))

    cast = ["char-ktn", "char-ngs", "char-mna", "char-rik", "char-yo"]
    original = sources["Setting"][0]
    assert original["liveMinimumGuaranteedAudienceAmount"] == 10
    assert [native_candidates(original, owner) for owner in cast] == [1000, 1000, 10, 10, 10]
    gallery = expanded_rows("Setting", sources["Setting"])[0]
    assert all(native_candidates(gallery, owner) == 1000 for owner in owners)
    counts = [native_candidates(gallery, owner) for owner in cast]
    # Original full-audience helper normalizes these five weights to 10,000.
    assert [ceil(count * 10000 / sum(counts)) for count in counts] == [2000] * 5
    assert all((row.lightFanAmount, row.middleFanAmount, row.heavyFanAmount) == (0, 0, 0)
               for row in snapshot.characters)
    assert sources["Setting"] == original_setting


def test_media_decoration_upgrade_adds_only_missing_rows_and_preserves_selection_and_unknown_fields(
        schema, master, snapshot):
    original_plan = prepare_media_inventory(schema, master[0])
    assert original_plan.decoration_ids == ()
    assert apply_media_inventory(snapshot, original_plan, obtained_time=NOW)
    snapshot.profile.decorationId = "deco-a"
    snapshot.decorations.add(decorationId="deco-a").MergeFromString(UNKNOWN)
    snapshot.decorations.add(decorationId="kept-legacy-decoration").MergeFromString(UNKNOWN)
    source = master[0] / "Decoration.json"
    source.write_text(json.dumps([{"id": "deco-b"}, {"id": "deco-a"}]))
    plan = prepare_media_inventory(schema, master[0])
    assert plan.decoration_ids == ("deco-a", "deco-b")
    expected = type(snapshot).FromString(snapshot.SerializeToString())
    expected.decorations.add(decorationId="deco-b")
    before_master = source.read_bytes()
    assert apply_media_inventory(snapshot, plan, obtained_time=NOW + 1)
    assert snapshot.SerializeToString() == expected.SerializeToString()
    assert UNKNOWN in snapshot.decorations[0].SerializeToString()
    assert snapshot.profile.decorationId == "deco-a"
    before_retry = snapshot.SerializeToString()
    assert not apply_media_inventory(snapshot, plan, obtained_time=NOW + 2)
    assert snapshot.SerializeToString() == before_retry and source.read_bytes() == before_master


@pytest.mark.parametrize("invalid", ("empty", "duplicate", "missing-id", "empty-id", "wrong-shape", "broken-link"))
def test_invalid_custom_decoration_master_fails_before_any_media_inventory_change(
        schema, master, snapshot, invalid):
    source = master[0] / "Decoration.json"
    if invalid == "broken-link":
        source.symlink_to(master[0] / "missing-decoration.json")
    else:
        value = {"empty": [], "duplicate": [{"id": "a"}, {"id": "a"}], "missing-id": [{}],
                 "empty-id": [{"id": ""}], "wrong-shape": {"id": "a"}}[invalid]
        source.write_text(json.dumps(value))
    before = snapshot.SerializeToString()
    with pytest.raises(RpcFailure) as error:
        prepare_media_inventory(schema, master[0])
    assert error.value.code == RpcCode.FAILED_PRECONDITION
    assert snapshot.SerializeToString() == before


@pytest.mark.parametrize("bad", (("deco-a", "deco-a"), ("",), ["deco-a"]))
def test_invalid_prepared_decoration_identities_cannot_partially_apply_other_media_grants(
        schema, master, snapshot, bad):
    from dataclasses import replace
    plan = replace(prepare_media_inventory(schema, master[0]), decoration_ids=bad)
    before = snapshot.SerializeToString()
    with pytest.raises(RpcFailure) as error:
        apply_media_inventory(snapshot, plan, obtained_time=NOW)
    assert error.value.code == RpcCode.FAILED_PRECONDITION and snapshot.SerializeToString() == before


@pytest.mark.parametrize("invalid", ("empty", "duplicate"))
def test_invalid_existing_decoration_inventory_cannot_partially_add_characters_or_cards(
        schema, master, snapshot, invalid):
    (master[0] / "Decoration.json").write_text('[{"id":"deco-a"},{"id":"deco-b"}]')
    plan = prepare_media_inventory(schema, master[0])
    snapshot.decorations.add(decorationId="deco-a")
    snapshot.decorations.add(decorationId="" if invalid == "empty" else "deco-a")
    before = snapshot.SerializeToString()
    with pytest.raises(RpcFailure) as error:
        apply_media_inventory(snapshot, plan, obtained_time=NOW)
    assert error.value.code == RpcCode.FAILED_PRECONDITION and snapshot.SerializeToString() == before


def test_custom_catalog_without_decoration_table_preserves_old_plan_constructor_and_existing_rows(
        schema, master, snapshot):
    from idoly_local.media_profile import MediaInventoryPlan
    plan = prepare_media_inventory(schema, master[0])
    assert plan.decoration_ids == ()
    old = MediaInventoryPlan(plan.schema_fingerprint, plan.master_version, plan.character_ids,
        plan.costume_ids, plan.hair_ids, plan.card_ids, plan._appearances, plan._cards,
        plan._stamina, plan._snapshot_type)
    assert old.decoration_ids == ()
    retained = snapshot.decorations.add(decorationId="kept-decoration")
    retained.MergeFromString(UNKNOWN)
    raw = retained.SerializeToString()
    assert apply_media_inventory(snapshot, old, obtained_time=NOW)
    assert len(snapshot.decorations) == 1 and snapshot.decorations[0].SerializeToString() == raw


def test_schema_without_decoration_inventory_fails_clearly_for_present_decoration_master(
        master, tmp_path):
    from test_gameplay import synthetic_schema
    (master[0] / "Decoration.json").write_text('[{"id":"deco-a"}]')
    old = synthetic_schema(tmp_path / "old-protocol.pb")
    assert "decorations" not in old.response_type("/api.User/Get").DESCRIPTOR.fields_by_name
    with pytest.raises(RpcFailure) as error:
        prepare_media_inventory(old, master[0])
    assert error.value.code == RpcCode.FAILED_PRECONDITION
    assert "schema has no decoration inventory" in str(error.value)


def test_actual_pinned_media_inventory_includes_all_verified_decorations(schema, snapshot):
    import os
    from idoly_local import preference_master_data as data
    root = Path(__file__).resolve().parents[1]
    explicit = os.environ.get("IDOLY_PREFERENCE_MASTER_DIR")
    directory = Path(explicit) if explicit else root / "data/master-json"
    required = tuple(directory / name for name in ("Card.json", "Costume.json", "!version.txt"))
    if not all(path.is_file() for path in required):
        if explicit:
            pytest.fail("The required pinned real media-master gate input is incomplete")
        pytest.skip("Original public master catalog is unavailable")
    assert (directory / "!version.txt").read_text().strip() == data.MASTER_VERSION
    expected_ids = tuple(sorted(row["id"] for row in json.loads(data.ROWS_JSON["Decoration"])))
    assert len(expected_ids) == 361
    plan = prepare_media_inventory(schema, directory)
    assert plan.decoration_ids == expected_ids
    original = snapshot.decorations.add(decorationId=expected_ids[0])
    original.MergeFromString(UNKNOWN)
    retained = original.SerializeToString()
    snapshot.decorations.add(decorationId="kept-custom-decoration").MergeFromString(UNKNOWN)
    snapshot.profile.decorationId = expected_ids[0]
    protected = type(snapshot).FromString(snapshot.SerializeToString())
    assert apply_media_inventory(snapshot, plan, obtained_time=NOW)
    current = {row.decorationId: row for row in snapshot.decorations}
    assert len(current) == 362 and set(expected_ids) <= set(current)
    assert current[expected_ids[0]].SerializeToString() == retained
    assert snapshot.profile == protected.profile
    inventory_fields = ("characters", "costumes", "hairs", "cards", "decorations")
    rest = type(snapshot).FromString(snapshot.SerializeToString())
    for field in inventory_fields:
        rest.ClearField(field)
        protected.ClearField(field)
    assert rest.SerializeToString() == protected.SerializeToString()
    before_retry = snapshot.SerializeToString()
    assert not apply_media_inventory(snapshot, plan, obtained_time=NOW + 1)
    assert snapshot.SerializeToString() == before_retry
