"""Data-free early enhancement tests, including the native 52-value oracle."""
import json
from pathlib import Path

import pytest

from idoly_local.card_progression import prepare_enhancement
from idoly_local.rpc import RpcCode, RpcFailure
from idoly_local.schema import Schema
from test_initial_inventory import minimal_schema


@pytest.fixture(scope="module", params=("minimal", "client-6.1.1"))
def schema(request, tmp_path_factory):
    if request.param == "minimal":
        return minimal_schema(tmp_path_factory.mktemp("card-schema") / "schema.pb")
    path = Path(__file__).resolve().parents[1] / "data/protocol/idolypride-6.1.1.pb"
    if not path.is_file():
        pytest.skip("Optional recovered client descriptor is unavailable")
    return Schema.from_descriptor_set(path)


def synthetic_fixture(tmp_path, schema):
    """Small original-shaped master, usable without any game distribution."""
    root = tmp_path / "master"
    root.mkdir()
    thresholds = (0, 40, 100, 180, 290, 440, 640, 900, 1250, 1720, 2490, 3590)
    parameters = (213, 301, 398, 499, 616, 720, 823, 926, 1030, 1133, 1259, 1385)
    stamina = (850, 852, 853, 856, 859, 860, 863, 864, 867, 869, 871, 875)
    rows = {
        "Card": [{"id": "card", "initialRarity": 3, "cardParameterId": "parameter",
                  "cardLevelReleaseId": "release", "vocalRatioPermil": 400,
                  "danceRatioPermil": 320, "visualRatioPermil": 280, "staminaRatioPermil": 1000,
                  "skillId1": "skill-1", "skillId2": "skill-2", "skillId3": "", "skillId4": ""}],
        "CardParameter": [{"id": "parameter", "level": i + 1, "value": str(value),
                           "staminaValue": str(stamina[i])} for i, value in enumerate(parameters)],
        "CardRarity": [{"rarity": 1, "requiredExp": 0, "parameterBonusPermil": 1000, "levelLimit": 20},
                       {"rarity": 2, "requiredExp": 10, "parameterBonusPermil": 1050, "levelLimit": 40},
                       {"rarity": 3, "requiredExp": 35, "parameterBonusPermil": 1100, "levelLimit": 60},
                       {"rarity": 4, "requiredExp": 85, "parameterBonusPermil": 1150, "levelLimit": 80}],
        "CardLevel": [{"level": i + 1, "requiredExp": str(value)} for i, value in enumerate(thresholds)]
                     + [{"level": 20, "requiredExp": "10000"}],
        "ManagerLevel": [{"level": 1, "requiredExp": "0", "maxCardLevel": 11},
                         {"level": 2, "requiredExp": "50", "maxCardLevel": 12},
                         {"level": 3, "requiredExp": "115", "maxCardLevel": 60}],
        "CardLevelRelease": [{"id": "release", "level": 1, "targets": [
            {"type": 1, "number": 1}, {"type": 4, "number": 1}, {"type": 7, "number": 2}]},
            {"id": "release", "level": 20, "targets": [{"type": 1, "number": 2}]}],
        "Skill": [{"id": "skill-1", "levels": [{"level": 1, "requiredCardLevel": 0},
                    {"level": 2, "requiredCardLevel": 40}]},
                  {"id": "skill-2", "levels": [{"level": 1, "requiredCardLevel": 0}]}],
        "Setting": [{"cardDefaultMental": 100, "cardDefaultTechnique": 100}],
        "Item": [{"id": "item-card_enhance", "type": 1, "value": 1}],
        "Consumption": [{"id": "consumption_1", "resources": [{"resourceType": 1,
            "resourceIds": ["item-card_enhance"], "amount": 1, "subResourceIds": []}]}],
    }
    for table, data in rows.items():
        (root / (table + ".json")).write_text(json.dumps(data))
    snapshot = schema.response_type("/api.User/Get")()
    card = snapshot.cards.add(cardId="card", level=1, baseLevel=1, rarity=3, rarityTotalExp=35,
        vocal=93, dance=74, visual=64, stamina=935, mental=100, technique=100,
        baseVocal=93, baseDance=74, baseVisual=64, baseStamina=935,
        skillId1="skill-1", baseSkillId1="skill-1", skillLevel1=1, baseSkillLevel1=1,
        photoEquipableCount=2, basePhotoEquipableCount=2, obtainedTime=123, lastEnhanceTime=456,
        displayType=1)
    return schema, root, rows, card


@pytest.fixture
def game(schema, tmp_path):
    return synthetic_fixture(tmp_path, schema)


def enhance(game, target=2, **kwargs):
    schema, root, _, card = game
    kwargs.setdefault("manager_level", 2)
    return prepare_enhancement(schema, root, card, target, **kwargs)


def rewrite(game, table):
    (game[1] / (table + ".json")).write_text(json.dumps(game[2][table]))


def test_official_kotono_level_two_stats_two_floors_and_no_input_mutation(game):
    card = game[3]
    card.ParseFromString(card.SerializeToString() + b"\xf8\x7f\x01")
    before = card.SerializeToString()
    result = enhance(game)
    assert result.changed and result.required_pieces == 40
    assert (result.card.level, result.card.baseLevel, result.card.totalExp) == (2, 2, 40)
    # Independent A64 CalcCardParameter oracle plus official 00040 response.
    assert (result.card.vocal, result.card.dance, result.card.visual, result.card.stamina) == (132, 105, 92, 937)
    assert (result.card.baseVocal, result.card.baseDance, result.card.baseVisual, result.card.baseStamina) == (132, 105, 92, 937)
    assert (result.card.mental, result.card.technique, result.card.rarity, result.card.rarityTotalExp) == (100, 100, 3, 35)
    assert (result.card.obtainedTime, result.card.lastEnhanceTime, result.card.displayType) == (123, 456, 1)
    assert b"\xf8\x7f\x01" in result.card.SerializeToString()
    assert card.SerializeToString() == before


# Native 0x46a4bf0..0x46a4c40 executed independently in Unicorn: Nagisa
# levels 1..12 (48 values), plus Kotono level2 above (4 values).
@pytest.mark.parametrize("level,expected", list(enumerate((
    (95, 77, 67, 841), (135, 108, 95, 842), (179, 144, 126, 843),
    (224, 180, 158, 847), (277, 223, 195, 850), (324, 260, 228, 851),
    (370, 298, 261, 853), (416, 335, 294, 854), (464, 372, 327, 858),
    (510, 410, 360, 860), (567, 456, 401, 861), (623, 502, 441, 865)), 1)))
def test_nagisa_native_regression_48_values(game, level, expected):
    master, card = game[2]["Card"][0], game[3]
    for name, ratio in zip(("vocal", "dance", "visual", "stamina"), (410, 330, 290, 900)):
        master[name + "RatioPermil"] = ratio
    for name, value in zip(("vocal", "dance", "visual", "stamina"), (95, 77, 67, 841)):
        setattr(card, name, value)
        setattr(card, "base" + name.capitalize(), value)
    rewrite(game, "Card")
    result = enhance(game, level)
    assert tuple(getattr(result.card, field) for field in ("vocal", "dance", "visual", "stamina")) == expected


def test_partial_xp_spends_only_cumulative_threshold_difference(game):
    game[3].totalExp = 15
    result = enhance(game, 3)
    assert result.required_pieces == 85 and result.card.totalExp == 100


def test_same_level_is_byte_identical_and_leaves_legacy_rarity_untouched(game):
    game[3].rarityTotalExp = 0
    before = game[3].SerializeToString()
    result = enhance(game, 1, normalize_starter_rarity=True)
    assert not result.changed and result.required_pieces == 0
    assert result.card.SerializeToString() == before


def test_legacy_rarity_requires_explicit_provenance_flag_and_preserves_partial_rarity(game):
    game[3].rarityTotalExp = 0
    with pytest.raises(RpcFailure) as error:
        enhance(game)
    assert error.value.code == RpcCode.FAILED_PRECONDITION
    result = enhance(game, normalize_starter_rarity=True)
    assert result.card.rarity == 3 and result.card.rarityTotalExp == 35
    assert game[3].rarityTotalExp == 0
    game[3].rarityTotalExp = 60
    assert enhance(game).card.rarityTotalExp == 60


def test_locked_levels_normalize_without_granting_any_locked_skill_or_ability(game):
    card = enhance(game).card
    for slot in range(1, 5):
        assert getattr(card, "skillLevel" + str(slot)) == getattr(card, "baseSkillLevel" + str(slot)) == 1
        expected = "skill-1" if slot == 1 else ""
        assert getattr(card, "skillId" + str(slot)) == getattr(card, "baseSkillId" + str(slot)) == expected
    for prefix in ("live", "activity", "baseLive", "baseActivity"):
        assert getattr(card, prefix + "AbilityLevel") == 1
        assert getattr(card, prefix + "AbilityId") == ""


@pytest.mark.parametrize("target", (0, -1, True, "2", 9999))
def test_invalid_target_fails_without_mutation(game, target):
    before = game[3].SerializeToString()
    with pytest.raises(RpcFailure) as error:
        enhance(game, target)
    assert error.value.code == RpcCode.INVALID_ARGUMENT
    assert game[3].SerializeToString() == before


def test_manager_cap_and_rarity_cap_are_both_enforced(game):
    with pytest.raises(RpcFailure) as error:
        enhance(game, 12, manager_level=1)
    assert error.value.code == RpcCode.INVALID_ARGUMENT
    game[2]["CardRarity"][2]["levelLimit"] = 2
    rewrite(game, "CardRarity")
    with pytest.raises(RpcFailure) as error:
        enhance(game, 3)
    assert error.value.code == RpcCode.INVALID_ARGUMENT


def test_release_boundary_and_earlier_learned_skill_upgrade_fail_closed(game):
    with pytest.raises(RpcFailure) as error:
        enhance(game, 20, manager_level=3)
    assert error.value.code == RpcCode.UNIMPLEMENTED
    game[2]["Skill"][0]["levels"][1]["requiredCardLevel"] = 8
    rewrite(game, "Skill")
    with pytest.raises(RpcFailure) as error:
        enhance(game, 8)
    assert error.value.code == RpcCode.UNIMPLEMENTED


@pytest.mark.parametrize("field,value", (("supported", True), ("rank", 1), ("rankTotalExp", 1),
    ("evolutionLevel", 1), ("evolutionLevelTotalExp", 1), ("rarity", 4), ("vocal", 999),
    ("skillLevel1", 2), ("activityAbilityLevel", 2)))
def test_unsupported_projection_is_never_overwritten(game, field, value):
    setattr(game[3], field, value)
    before = game[3].SerializeToString()
    with pytest.raises(RpcFailure) as error:
        enhance(game)
    assert error.value.code == RpcCode.UNIMPLEMENTED
    assert game[3].SerializeToString() == before


@pytest.mark.parametrize("mutation", ("gold-cost", "piece-cost", "bad-item", "duplicate-level",
    "bad-threshold", "missing-parameter", "bad-skill-id", "bad-photo-count", "bad-xp"))
def test_bad_catalog_or_state_fails_before_output(game, mutation):
    rows = game[2]
    if mutation == "gold-cost":
        rows["Consumption"][0]["resources"].append({"resourceType": 8, "amount": 1})
        rewrite(game, "Consumption")
    elif mutation == "piece-cost":
        rows["Consumption"][0]["resources"][0]["amount"] = 2
        rewrite(game, "Consumption")
    elif mutation == "bad-item":
        rows["Item"][0]["value"] = 2
        rewrite(game, "Item")
    elif mutation == "duplicate-level":
        rows["CardLevel"].append(dict(rows["CardLevel"][0]))
        rewrite(game, "CardLevel")
    elif mutation == "bad-threshold":
        rows["CardLevel"][1]["requiredExp"] = "0"
        rewrite(game, "CardLevel")
    elif mutation == "missing-parameter":
        rows["CardParameter"][:] = rows["CardParameter"][:1]
        rewrite(game, "CardParameter")
    elif mutation == "bad-skill-id":
        game[3].skillId2 = "skill-2"
    elif mutation == "bad-photo-count":
        game[3].photoEquipableCount = 3
    else:
        game[3].totalExp = 40
    before = game[3].SerializeToString()
    with pytest.raises(RpcFailure) as error:
        enhance(game)
    assert error.value.code == RpcCode.FAILED_PRECONDITION
    assert game[3].SerializeToString() == before


def test_completed_enhancement_retry_never_spends_or_normalizes_further(game):
    card = enhance(game).card
    game[3].CopyFrom(card)
    before = card.SerializeToString()
    result = enhance(game)
    assert not result.changed and result.required_pieces == 0 and result.card.SerializeToString() == before
    with pytest.raises(RpcFailure) as error:
        enhance(game, 1)
    assert error.value.code == RpcCode.INVALID_ARGUMENT
