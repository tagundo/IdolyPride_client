"""Audited starter equipment affects prepared live stats, never owned state."""
import pytest

from idoly_local import live_input as module
from idoly_local.rpc import RpcCode, RpcFailure
from test_live_input import game, schema, prepare, rewrite, user


VISUAL = "ac-1-visual-02"
VOCAL = "ac-1-vocal-02"


def accessory(identity, parameter):
    # Original public 6.1.1 functional fields; the two first-clear rewards have
    # one flat64 Part1 bonus and no multiplier, second bonus or wearer limits.
    return {"id": identity, "categoryType": 1, "param1Type": parameter,
            "param1Value": 64, "param1Permil": 0, "param2Type": 0,
            "param2Value": 0, "param2Permil": 0, "limitBreakPhase": 0,
            "limitBreakConsumptionId": "", "characterId": "", "characterGroupId": ""}


@pytest.fixture
def equipment(game):
    game[2]["Accessory"] = [accessory(VISUAL, 3), accessory(VOCAL, 2)]
    rewrite(game, "Accessory")
    return game


def position(game, index):
    return next(row for row in game[3].deckPositions if row.number == 1 and row.position == index)


def equip(game, identity, index=1, amount=1):
    position(game, index).part1AccessoryId = identity
    game[3].accessories.add(accessoryId=identity, amount=amount)


@pytest.mark.parametrize("identity,attribute", ((VISUAL, "visual"), (VOCAL, "vocal")))
def test_flat64_changes_only_the_wearer_prepared_parameter_and_is_not_stacked(equipment, identity, attribute):
    game = equipment
    baseline = prepare(game)
    expected = user(game, baseline)
    setattr(expected.userDeck.cards[2], attribute,
            getattr(expected.userDeck.cards[2], attribute) + 64)
    equip(game, identity, index=3)
    before = game[3].SerializeToString()
    actual = prepare(game)
    assert user(game, actual) == expected
    assert actual["input_version"] == 1 and set(actual["proto"]) == set(baseline["proto"])
    assert actual["cards"] == baseline["cards"]
    assert prepare(game) == actual
    assert game[3].SerializeToString() == before


def test_both_initial_rewards_apply_to_their_saved_wearers(equipment):
    game = equipment
    expected = user(game, prepare(game))
    expected.userDeck.cards[0].visual += 64
    expected.userDeck.cards[4].vocal += 64
    equip(game, VISUAL, index=1)
    equip(game, VOCAL, index=5)
    before = game[3].SerializeToString()
    assert user(game, prepare(game)) == expected
    assert game[3].SerializeToString() == before


def test_same_item_can_be_worn_twice_when_quantity_covers_selected_deck(equipment):
    game = equipment
    expected = user(game, prepare(game))
    expected.userDeck.cards[0].visual += 64
    expected.userDeck.cards[1].visual += 64
    equip(game, VISUAL, amount=2)
    position(game, 2).part1AccessoryId = VISUAL
    assert user(game, prepare(game)) == expected
    game[3].accessories[0].amount = 1
    before = game[3].SerializeToString()
    with pytest.raises(RpcFailure) as caught:
        prepare(game)
    assert caught.value.code == RpcCode.FAILED_PRECONDITION
    assert game[3].SerializeToString() == before


def test_equipment_in_another_saved_deck_does_not_consume_selected_quantity(equipment):
    game = equipment
    equip(game, VISUAL)
    selected = prepare(game)
    game[3].decks.add(number=2, name="Another saved unit")
    for index in range(1, 6):
        game[3].deckPositions.add(number=2, position=index, cardId=position(game, index).cardId,
                                  part1AccessoryId=VISUAL)
    before = game[3].SerializeToString()
    assert prepare(game) == selected
    assert game[3].SerializeToString() == before


@pytest.mark.parametrize("damage", ("unowned", "zero", "negative", "duplicate", "empty-id"))
def test_imported_inventory_cannot_supply_unowned_or_ambiguous_equipment(equipment, damage):
    game = equipment
    equip(game, VISUAL)
    if damage == "unowned":
        del game[3].accessories[:]
    elif damage in ("zero", "negative"):
        game[3].accessories[0].amount = 0 if damage == "zero" else -1
    elif damage == "duplicate":
        game[3].accessories.add(accessoryId=VISUAL, amount=1)
    else:
        game[3].accessories.add(accessoryId="", amount=1)
    before = game[3].SerializeToString()
    with pytest.raises(RpcFailure) as caught:
        prepare(game)
    assert caught.value.code == RpcCode.FAILED_PRECONDITION
    assert game[3].SerializeToString() == before


@pytest.mark.parametrize("field,value", (
    ("categoryType", 2), ("param1Type", 2), ("param1Value", 65),
    ("param1Permil", 100), ("param2Type", 1), ("param2Value", 1),
    ("param2Permil", 1), ("characterId", "char-a"),
    ("characterGroupId", "group-1"), ("limitBreakPhase", 1),
    ("limitBreakConsumptionId", "unsupported"), ("param1Value", "64"),
    ("param1Permil", False), ("categoryType", True), ("param1Value", None),
))
def test_corrupt_or_nonplain_master_cannot_be_treated_as_flat64(equipment, field, value):
    game = equipment
    equip(game, VISUAL)
    row = game[2]["Accessory"][0]
    if value is None:
        del row[field]
    else:
        row[field] = value
    rewrite(game, "Accessory")
    before = game[3].SerializeToString()
    with pytest.raises(RpcFailure) as caught:
        prepare(game)
    assert caught.value.code == RpcCode.FAILED_PRECONDITION
    assert game[3].SerializeToString() == before


@pytest.mark.parametrize("damage", ("missing-record", "duplicate-master", "missing-table"))
def test_master_identity_must_resolve_without_duplicates(equipment, damage):
    game = equipment
    equip(game, VISUAL)
    if damage == "missing-table":
        (game[1] / "Accessory.json").unlink()
    else:
        if damage == "missing-record":
            game[2]["Accessory"].pop(0)
        else:
            game[2]["Accessory"].append(dict(game[2]["Accessory"][0]))
        rewrite(game, "Accessory")
    before = game[3].SerializeToString()
    with pytest.raises(RpcFailure) as caught:
        prepare(game)
    assert caught.value.code == RpcCode.FAILED_PRECONDITION
    assert game[3].SerializeToString() == before


def test_part2_remains_unsupported_even_for_owned_initial_item(equipment):
    game = equipment
    equip(game, VISUAL)
    position(game, 1).part1AccessoryId = ""
    position(game, 1).part2AccessoryId = VISUAL
    before = game[3].SerializeToString()
    with pytest.raises(RpcFailure) as caught:
        prepare(game)
    assert caught.value.code == RpcCode.UNIMPLEMENTED
    assert game[3].SerializeToString() == before


@pytest.mark.parametrize("field,value", (("liveAbilityId", "ability-off-deck"),
    ("baseLiveAbilityId", "ability-off-deck"), ("liveAbilityLevel", 2),
    ("baseLiveAbilityLevel", 2), ("liveAbilityLevel", -1), ("baseLiveAbilityLevel", -1)))
def test_off_deck_owned_ability_cannot_silently_boost_accessory(equipment, field, value):
    game = equipment
    equip(game, VOCAL)
    off = game[3].cards.add()
    off.CopyFrom(game[3].cards[0])
    off.cardId = "card-off-deck"
    setattr(off, field, value)
    game[2]["Card"].append({**game[2]["Card"][0], "id": off.cardId})
    rewrite(game, "Card")
    before = game[3].SerializeToString()
    with pytest.raises(RpcFailure) as caught:
        prepare(game)
    assert caught.value.code == RpcCode.UNIMPLEMENTED
    assert game[3].SerializeToString() == before


def test_locked_empty_ability_ids_with_initial_levels_zero_or_one_are_supported(equipment):
    game = equipment
    equip(game, VOCAL)
    for index, card in enumerate(game[3].cards):
        card.liveAbilityId = card.baseLiveAbilityId = ""
        card.liveAbilityLevel = index % 2
        card.baseLiveAbilityLevel = 1 - index % 2
    before = game[3].SerializeToString()
    assert user(game, prepare(game)).userDeck.cards[0].vocal == 93 + 64
    assert game[3].SerializeToString() == before


def test_flat_addition_checks_int64_overflow_even_if_card_validation_changes(equipment, monkeypatch):
    game = equipment
    equip(game, VOCAL)
    card = next(row for row in game[3].cards if row.cardId == position(game, 1).cardId)
    card.vocal = (1 << 63) - 1
    # Isolate arithmetic's own boundary from the independent base-card master
    # validator, which correctly rejects this value in ordinary preparation.
    monkeypatch.setattr(module, "prepare_enhancement", lambda *args, **kwargs: None)
    before = game[3].SerializeToString()
    with pytest.raises(RpcFailure, match="accessory parameter overflows") as caught:
        prepare(game)
    assert caught.value.code == RpcCode.FAILED_PRECONDITION
    assert game[3].SerializeToString() == before
