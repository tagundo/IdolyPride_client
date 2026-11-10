"""Pure projection for the verified, unranked early card-enhancement form.

6.1.1 Card.GetParameterValue (0x4df0c54) and CalcCardParameter
(0x46a4b7c) floor once before and once after the rarity multiplier. The
official tutorial level-two response also keeps locked skill levels at one,
while their IDs remain empty. This module does not grant skills, calculate
support bonuses, spend inventory, persist state, or assign timestamps.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from google.protobuf import message_factory

from .gameplay import _Catalog
from .rpc import RpcCode, RpcFailure


_MAX = (1 << 63) - 1
_PARAMETERS = ("vocal", "dance", "visual", "stamina")


def _fail(reason: str, code: RpcCode = RpcCode.FAILED_PRECONDITION):
    raise RpcFailure(code, "Card enhancement: " + reason)


def _number(value, description: str, *, positive=False) -> int:
    if type(value) is not int and type(value) is not str:
        _fail("invalid " + description)
    try:
        result = int(value)
    except (ValueError, OverflowError):
        _fail("invalid " + description)
    if (result < int(positive) or result > _MAX
            or isinstance(value, str) and str(result) != value):
        _fail("invalid " + description)
    return result


def _levels(catalog, table, *, identity=None, threshold=None):
    result = {}
    for row in catalog.rows(table, required=True):
        if identity is not None and row.get("id") != identity:
            continue
        level = _number(row.get("level"), table + " level", positive=True)
        if level in result:
            _fail("duplicate " + table + " level")
        result[level] = row
    if not result:
        _fail("missing " + table + " levels")
    if threshold:
        previous = -1
        for level in sorted(result):
            value = _number(result[level].get(threshold), table + " threshold")
            if value <= previous or level == 1 and value != 0:
                _fail("invalid " + table + " thresholds")
            previous = value
        if 1 not in result:
            _fail("missing level-one " + table)
    return result


def _values(master, parameter, rarity, mental, technique):
    bonus = _number(rarity.get("parameterBonusPermil"), "rarity multiplier", positive=True)
    result = {"mental": mental, "technique": technique}
    for name in _PARAMETERS:
        value = _number(parameter.get("staminaValue" if name == "stamina" else "value"),
                        "base " + name)
        ratio = _number(master.get(name + "RatioPermil"), name + " ratio")
        amount = ((value * ratio) // 1000 * bonus) // 1000
        result[name] = _number(amount, name + " result")
    return result


def _release_scope(catalog, master):
    identity = master.get("cardLevelReleaseId")
    if not isinstance(identity, str) or not identity:
        _fail("missing card release identity")
    releases = _levels(catalog, "CardLevelRelease", identity=identity)
    first = releases.get(1)
    if first is None:
        _fail("missing initial releases")
    unlocked, photos, boundaries = set(), 0, []
    for level, row in releases.items():
        targets = row.get("targets")
        if not isinstance(targets, list):
            _fail("invalid release targets")
        seen = set()
        for target in targets:
            if not isinstance(target, dict):
                _fail("invalid release target")
            kind = _number(target.get("type"), "release type", positive=True)
            number = _number(target.get("number"), "release number", positive=True)
            if (kind, number) in seen or kind not in (1, 2, 3, 4, 7):
                _fail("unsupported or duplicate release target")
            seen.add((kind, number))
            if level > 1:
                boundaries.append(level)
            elif kind == 1 and number <= 4:
                unlocked.add(number)
            elif kind == 7:
                photos += number
            elif kind != 4:
                _fail("initial ability release is unsupported", RpcCode.UNIMPLEMENTED)
    if not unlocked:
        _fail("no initial learned skill")
    skills = catalog.ids("Skill", required=True)
    for slot in range(1, 5):
        identity = master.get("skillId" + str(slot), "")
        if not isinstance(identity, str) or identity and identity not in skills:
            _fail("invalid skill reference")
        if slot not in unlocked:
            continue
        skill = skills.get(identity)
        if skill is None or not isinstance(skill.get("levels"), list):
            _fail("missing learned skill")
        levels = {}
        for row in skill["levels"]:
            if not isinstance(row, dict):
                _fail("invalid skill level")
            level = _number(row.get("level"), "skill level", positive=True)
            required = _number(row.get("requiredCardLevel", 0), "skill required level")
            if level in levels:
                _fail("duplicate skill level")
            levels[level] = required
            if level > 1:
                if required <= 1:
                    _fail("initial skill upgrade is unsupported", RpcCode.UNIMPLEMENTED)
                boundaries.append(required)
        if levels.get(1, 2) > 1:
            _fail("missing usable initial skill level")
    return unlocked, photos, min(boundaries) if boundaries else None


@dataclass(frozen=True)
class EnhancementPlan:
    card: object
    required_pieces: int
    changed: bool


def prepare_enhancement(schema, master_dir: Path, card, target_level: int, *,
                        manager_level: int, normalize_starter_rarity: bool = False) -> EnhancementPlan:
    """Copy and enhance a known initial card below its next release boundary.

    ``normalize_starter_rarity`` is reserved for provenance-checked local
    starters whose initial rarity XP was historically omitted. Callers own
    that authorization and the atomic inventory transaction. A same-level
    retry preserves every byte and requires no pieces. Unsupported advanced
    forms fail before the input can be changed.

    Tables: Card, CardParameter, CardRarity, CardLevelRelease, Skill, Setting,
    Item, Consumption, CardLevel, ManagerLevel.
    """
    if type(target_level) is not int or target_level < 1:
        _fail("target level must be positive", RpcCode.INVALID_ARGUMENT)
    if type(manager_level) is not int or manager_level < 1:
        _fail("invalid manager level")
    if type(normalize_starter_rarity) is not bool:
        _fail("invalid starter normalization flag")
    snapshot_type = schema.response_type("/api.User/Get")
    card_type = message_factory.GetMessageClass(snapshot_type.DESCRIPTOR.fields_by_name["cards"].message_type)
    if not isinstance(card, card_type):
        _fail("card and schema do not match")
    catalog = _Catalog(master_dir)
    master = catalog.ids("Card", required=True).get(card.cardId)
    if master is None:
        _fail("unknown card")
    if card.supported or any((card.rank, card.rankTotalExp, card.evolutionLevel, card.evolutionLevelTotalExp)):
        _fail("support, rank and evolution are not supported", RpcCode.UNIMPLEMENTED)
    initial_rarity = _number(master.get("initialRarity"), "initial rarity", positive=True)
    if card.rarity != initial_rarity:
        _fail("changed card rarity is not supported", RpcCode.UNIMPLEMENTED)
    rarities = {}
    for row in catalog.rows("CardRarity", required=True):
        number = _number(row.get("rarity"), "rarity", positive=True)
        if number in rarities:
            _fail("duplicate rarity")
        rarities[number] = row
    rarity = rarities.get(card.rarity)
    if rarity is None:
        _fail("missing rarity")
    rarity_exp = _number(card.rarityTotalExp, "current rarity XP")
    thresholds = {number: _number(row.get("requiredExp"), "rarity XP") for number, row in rarities.items()}
    if any(thresholds[a] >= thresholds[b] for a, b in zip(sorted(thresholds), sorted(thresholds)[1:])):
        _fail("invalid rarity thresholds")
    normalize_rarity = bool(normalize_starter_rarity and rarity_exp == 0 and thresholds[card.rarity] > 0)
    if not normalize_rarity:
        eligible = [number for number, threshold in thresholds.items() if threshold <= rarity_exp]
        if not eligible or max(eligible) != card.rarity:
            _fail("rarity and rarity XP disagree")
    levels = _levels(catalog, "CardLevel", threshold="requiredExp")
    total_exp = _number(card.totalExp, "current XP")
    current_level = max(level for level, row in levels.items()
                        if _number(row["requiredExp"], "card threshold") <= total_exp)
    if card.level != current_level or card.baseLevel != current_level:
        _fail("level and XP disagree")
    if target_level < current_level:
        _fail("target level is below the current level", RpcCode.INVALID_ARGUMENT)
    if target_level not in levels:
        _fail("unknown target level", RpcCode.INVALID_ARGUMENT)
    managers = _levels(catalog, "ManagerLevel", threshold="requiredExp")
    manager = managers.get(manager_level)
    if manager is None:
        _fail("unknown manager level")
    cap = min(_number(manager.get("maxCardLevel"), "manager card cap", positive=True),
              _number(rarity.get("levelLimit"), "rarity card cap", positive=True))
    if target_level > cap:
        _fail("target exceeds the card level cap", RpcCode.INVALID_ARGUMENT)
    item = catalog.ids("Item", required=True).get("item-card_enhance")
    if (item is None or type(item.get("type")) is not int or item["type"] != 1
            or type(item.get("value")) is not int or item["value"] != 1):
        _fail("unsupported enhancement item")
    consumption = catalog.ids("Consumption", required=True).get("consumption_1")
    expected = [{"resourceType": 1, "resourceIds": ["item-card_enhance"], "amount": 1, "subResourceIds": []}]
    resources = consumption.get("resources") if consumption else None
    if (resources != expected or type(resources[0].get("resourceType")) is not int
            or type(resources[0].get("amount")) is not int):
        _fail("unsupported enhancement consumption")
    unlocked, photos, boundary = _release_scope(catalog, master)
    if boundary is not None and max(current_level, target_level) >= boundary:
        _fail("the next card release or skill upgrade is not supported", RpcCode.UNIMPLEMENTED)
    settings = catalog.rows("Setting", required=True)
    if len(settings) != 1:
        _fail("one Setting row is required")
    mental = _number(settings[0].get("cardDefaultMental"), "default mental")
    technique = _number(settings[0].get("cardDefaultTechnique"), "default technique")
    parameter_id = master.get("cardParameterId")
    if not isinstance(parameter_id, str) or not parameter_id:
        _fail("missing parameter identity")
    parameters = _levels(catalog, "CardParameter", identity=parameter_id)
    if current_level not in parameters or target_level not in parameters:
        _fail("missing card parameters")
    current_values = _values(master, parameters[current_level], rarity, mental, technique)
    for name, value in current_values.items():
        if getattr(card, name) != value or name in _PARAMETERS and getattr(card, "base" + name.capitalize()) != value:
            _fail("current card has an unsupported parameter projection", RpcCode.UNIMPLEMENTED)
    if card.photoEquipableCount != photos or card.basePhotoEquipableCount != photos:
        _fail("current photo slots do not match the initial releases")
    for slot in range(1, 5):
        expected_id = master.get("skillId" + str(slot), "") if slot in unlocked else ""
        for prefix in ("", "base"):
            identity_field = ("skillId" if not prefix else "baseSkillId") + str(slot)
            level_field = ("skillLevel" if not prefix else "baseSkillLevel") + str(slot)
            if getattr(card, identity_field) != expected_id:
                _fail("current learned skills do not match the initial releases")
            allowed = (1,) if slot in unlocked else (0, 1)
            if getattr(card, level_field) not in allowed:
                _fail("trained skills are not supported", RpcCode.UNIMPLEMENTED)
    for kind in ("Live", "Activity"):
        for prefix in (kind.lower(), "base" + kind):
            if getattr(card, prefix + "AbilityId") or getattr(card, prefix + "AbilityLevel") not in (0, 1):
                _fail("learned abilities are not supported", RpcCode.UNIMPLEMENTED)
    result = card_type()
    result.CopyFrom(card)
    if target_level == current_level:
        return EnhancementPlan(result, 0, False)
    result.totalExp = _number(levels[target_level]["requiredExp"], "target XP")
    result.level = result.baseLevel = target_level
    if normalize_rarity:
        result.rarityTotalExp = thresholds[card.rarity]
    for name, value in _values(master, parameters[target_level], rarity, mental, technique).items():
        setattr(result, name, value)
        if name in _PARAMETERS:
            setattr(result, "base" + name.capitalize(), value)
    for slot in range(1, 5):
        setattr(result, "skillLevel" + str(slot), 1)
        setattr(result, "baseSkillLevel" + str(slot), 1)
    for kind in ("Live", "Activity"):
        setattr(result, kind.lower() + "AbilityLevel", 1)
        setattr(result, "base" + kind + "AbilityLevel", 1)
    return EnhancementPlan(result, result.totalExp - total_exp, True)
