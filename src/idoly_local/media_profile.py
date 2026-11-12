"""Explicit local media inventory, independent of normal account progression.

The caller must opt into a separate media profile/database before applying
this plan. It grants real master-backed media ownership; it does not emulate
an official grant, spend currency, clear quests, or mark stories as read.
Preparation and application deliberately have no State/database access.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from google.protobuf import message_factory

from .appearance import _owned
from .gameplay import _Catalog
from .initial_inventory import _initial_releases, _initial_skill, _level_rows
from .live_assets import _wearable
from .media_outfit_policy import COSTUME_IDS, is_audited_work_costume
from .rpc import RpcCode, RpcFailure


_USER = "/api.User/Get"
_MAX = (1 << 63) - 1


def _fail(reason):
    raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Invalid media inventory: " + reason)


def _number(value, description, *, positive=False):
    if type(value) not in (int, str):
        _fail(description)
    try:
        result = int(value)
    except (ValueError, TypeError, OverflowError):
        _fail(description)
    if (not int(positive) <= result <= _MAX
            or isinstance(value, str) and str(result) != value):
        _fail(description)
    return result


def _identity(value, description):
    if not isinstance(value, str) or not value:
        _fail(description)
    return value


@dataclass(frozen=True)
class MediaInventoryPlan:
    """Validated, timestamp-free inventory for an explicitly selected profile."""

    schema_fingerprint: str
    master_version: str | None
    character_ids: tuple[str, ...]
    costume_ids: tuple[str, ...]
    hair_ids: tuple[str, ...]
    card_ids: tuple[str, ...]
    _appearances: tuple[tuple[str, str, str, str, str], ...] = field(repr=False)
    _cards: tuple[bytes, ...] = field(repr=False)
    _stamina: int = field(repr=False)
    _snapshot_type: type = field(repr=False, compare=False)


def prepare_media_inventory(schema, master_dir: Path) -> MediaInventoryPlan:
    """Prepare all real card owners and their user-available wearable outfits.

    Card owners cover normal, Mana and collaboration characters in 6.1.1.
    NPC-only Character rows are not given invented cards or appearances.
    Acquisition/view conditions are intentionally ignored in this opt-in
    local mode. ``isUserUnavailable`` costumes are excluded except for the
    twenty-one audited 3D hot-spring work outfits; SD-only definitions and
    hair with no compatible same-owner outfit remain excluded.
    Existing user-available admin-hidden rows remain owned; the separate media
    client master clears only their audited visibility flags.

    Every card starts at its actual initial rarity and level one, using the
    same two integer floors and initial skill-release checks as the starter.
    Original 6.1.1 Card.get_IllustrationStage selects stage one when initial
    rarity exceeds four; its explicit display enum is AfterLimitBreak (2).
    No extra master tables beyond the normal payload are required.
    """
    catalog = _Catalog(master_dir)
    cards = catalog.ids("Card", required=True)
    characters = catalog.ids("Character", required=True)
    costumes = catalog.ids("Costume", required=True)
    hairs = catalog.ids("Hair", required=True)
    owners = {_identity(row.get("characterId"), "card character") for row in cards.values()}
    for owner in owners:
        character = characters.get(owner)
        if (character is None or type(character.get("type")) is not int
                or character["type"] not in (1, 3, 4)):
            _fail("card owner is not a playable character")

    available_costumes = {}
    by_owner = {owner: [] for owner in owners}
    for identity, row in costumes.items():
        if row.get("characterId") not in owners:
            continue
        unavailable = row.get("isUserUnavailable", False)
        if type(unavailable) is not bool:
            _fail("costume user availability")
        if unavailable:
            if identity not in COSTUME_IDS:
                continue
            if not is_audited_work_costume(row):
                _fail("audited work costume owner or resource reference")
        owner = row["characterId"]
        hair = hairs.get(_identity(row.get("defaultHairId"), "costume default hair"))
        if (hair is None or hair.get("characterId") != owner
                or not _wearable(hair, identity)):
            _fail("costume default hair ownership or compatibility")
        available_costumes[identity] = row
        by_owner[owner].append(identity)
    if any(not values for values in by_owner.values()):
        _fail("playable character has no available costume")

    available_hairs = set()
    for identity, row in hairs.items():
        owner = row.get("characterId")
        if owner in owners and any(_wearable(row, costume) for costume in by_owner[owner]):
            available_hairs.add(identity)
    appearances = []
    for owner in sorted(owners):
        character = characters[owner]
        default = _identity(character.get("defaultCostumeId"), "character default costume")
        live = character.get("defaultLiveCostumeId") or default
        if default not in by_owner[owner] or live not in by_owner[owner]:
            _fail("character default outfit is not available for its owner")
        default_hair = available_costumes[default]["defaultHairId"]
        live_hair = available_costumes[live]["defaultHairId"]
        if default_hair not in available_hairs or live_hair not in available_hairs:
            _fail("character default hair is unavailable")
        appearances.append((owner, default, default_hair, live, live_hair))

    settings = catalog.rows("Setting", required=True)
    if len(settings) != 1:
        _fail("one Setting row is required")
    mental = _number(settings[0].get("cardDefaultMental"), "default mental")
    technique = _number(settings[0].get("cardDefaultTechnique"), "default technique")
    activity = [row for row in catalog.rows("CharacterActivityLevel", required=True) if row.get("level") == 1]
    if len(activity) != 1:
        _fail("one level-one activity row is required")
    stamina = _number(activity[0].get("maxStamina"), "initial activity stamina")
    parameters = _level_rows(catalog, "CardParameter")
    releases = _level_rows(catalog, "CardLevelRelease")
    skills = catalog.ids("Skill", required=True)
    rarities = {}
    for row in catalog.rows("CardRarity", required=True):
        rarity = _number(row.get("rarity"), "rarity", positive=True)
        if rarity in rarities:
            _fail("duplicate rarity")
        rarities[rarity] = row
    thresholds = {rarity: _number(row.get("requiredExp"), "rarity XP")
                  for rarity, row in rarities.items()}
    ordered = sorted(thresholds)
    if any(thresholds[first] >= thresholds[second] for first, second in zip(ordered, ordered[1:])):
        _fail("rarity XP thresholds are not increasing")
    level_one = [row for row in catalog.rows("CardLevel", required=True) if row.get("level") == 1]
    if len(level_one) != 1 or _number(level_one[0].get("requiredExp"), "initial card XP") != 0:
        _fail("initial card experience threshold")
    snapshot_type = schema.response_type(_USER)
    card_type = message_factory.GetMessageClass(snapshot_type.DESCRIPTOR.fields_by_name["cards"].message_type)
    prepared = []
    for identity in sorted(cards):
        card = cards[identity]
        rarity = _number(card.get("initialRarity"), "initial rarity", positive=True)
        rarity_row = rarities.get(rarity)
        if rarity_row is None:
            _fail("missing initial rarity")
        bonus = _number(rarity_row.get("parameterBonusPermil"), "rarity multiplier", positive=True)
        rarity_exp = thresholds[rarity]
        parameter_id = _identity(card.get("cardParameterId"), "card parameter")
        parameter = parameters.get((parameter_id, 1))
        if parameter is None:
            _fail("missing initial card parameter")
        values = dict(cardId=identity, level=1, baseLevel=1, rarity=rarity,
                      rarityTotalExp=rarity_exp, mental=mental, technique=technique,
                      displayType=2 if rarity > 4 else 1)
        for name in ("vocal", "dance", "visual", "stamina"):
            base = _number(parameter.get("staminaValue" if name == "stamina" else "value"),
                           "initial card parameter")
            ratio = _number(card.get(name + "RatioPermil"), "card parameter ratio")
            value = ((base * ratio) // 1000 * bonus) // 1000
            values[name] = values["base" + name.capitalize()] = _number(value, "card parameter result")
        unlocked, photos = _initial_releases(card, releases)
        values["photoEquipableCount"] = values["basePhotoEquipableCount"] = photos
        for slot in range(1, 5):
            reference = card.get("skillId" + str(slot), "")
            if not isinstance(reference, str) or reference and reference not in skills:
                _fail("unknown card skill")
            if slot in unlocked:
                _initial_skill(skills, _identity(reference, "initial learned skill"))
                values["skillId" + str(slot)] = values["baseSkillId" + str(slot)] = reference
                values["skillLevel" + str(slot)] = values["baseSkillLevel" + str(slot)] = 1
        prepared.append(card_type(**values).SerializeToString())
    return MediaInventoryPlan(schema.fingerprint, catalog.version(), tuple(sorted(owners)),
        tuple(sorted(available_costumes)), tuple(sorted(available_hairs)), tuple(sorted(cards)),
        tuple(appearances), tuple(prepared), stamina, snapshot_type)


def apply_media_inventory(snapshot, plan: MediaInventoryPlan, *, obtained_time: int) -> bool:
    """Append ownership and repair the original media seed's invalid display.

    Call only for an explicitly chosen media profile. This pure function cannot
    select, import, overwrite or authenticate another profile. A False return
    means the caller should keep its original snapshot bytes verbatim.

    The old media seed assigned display 1 even to initial five-star cards,
    whose pinned 6.1.1 CardImage rows have only displays 2 (and sometimes 3).
    Repair only that invalid choice. Existing growth, valid display choices,
    unknown fields and all unrelated rows remain byte-for-byte unchanged.
    """
    if not isinstance(plan, MediaInventoryPlan) or not isinstance(snapshot, plan._snapshot_type):
        _fail("snapshot and prepared schema do not match")
    if not snapshot.HasField("user"):
        _fail("snapshot has no user")
    if type(obtained_time) is not int:
        _fail("obtained timestamp")
    obtained_time = _number(obtained_time, "obtained timestamp", positive=True)
    owned_characters = _owned(snapshot.characters, "characterId")
    owned_costumes = _owned(snapshot.costumes, "costumeId")
    owned_hairs = _owned(snapshot.hairs, "hairId")
    owned_cards = _owned(snapshot.cards, "cardId")
    result = plan._snapshot_type()
    result.CopyFrom(snapshot)
    result_cards = {row.cardId: row for row in result.cards}
    changed = False
    for owner, default, hair, live, live_hair in plan._appearances:
        if owner not in owned_characters:
            result.characters.add(characterId=owner, favoriteCostumeId=default,
                favoriteHairId=hair, liveCostumeId=live, liveHairId=live_hair,
                activityLevel=1, activityStamina=plan._stamina, staminaUpdatedTime=obtained_time)
            changed = True
    for identity in plan.costume_ids:
        if identity not in owned_costumes:
            result.costumes.add(costumeId=identity, checked=True, obtainedTime=obtained_time)
            changed = True
    for identity in plan.hair_ids:
        if identity not in owned_hairs:
            result.hairs.add(hairId=identity, checked=True)
            changed = True
    for identity, payload in zip(plan.card_ids, plan._cards):
        if identity not in owned_cards:
            row = result.cards.add()
            row.ParseFromString(payload)
            row.obtainedTime = obtained_time
            changed = True
        elif owned_cards[identity].displayType == 1:
            initial = type(owned_cards[identity]).FromString(payload)
            if initial.displayType == 2:
                result_cards[identity].displayType = 2
                changed = True
    if changed:
        snapshot.CopyFrom(result)
    return changed
