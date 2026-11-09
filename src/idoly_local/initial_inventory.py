"""Prepare the public initial_user_reward inventory for a new local profile.

This follows the recovered 6.1.1 Reward/Card/Setting tables. The official RPC
which applied that reward is not known; this is a local account-bootstrap
policy, not an emulation of a verified Auth/Tutorial grant transaction.

Native evidence: Card.GetParameterValue (0x4df0c54) and CalcCardParameter
(0x46a4b7c) apply two integer floors. UserCard skill-data getters (0x479f324
and following) treat a nonempty, resolvable skill ID as learned, so unreleased
skills must have both an empty ID and level zero. No formation, gifts, premium
currency, quest clears or tutorial progress are supplied by this module.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

from google.protobuf import message_factory

from .gameplay import _Catalog
from .rpc import RpcCode, RpcFailure


_REWARD = "initial_user_reward"
_USER_GET = "/api.User/Get"
_ITEM, _CARD, _CHARACTER = 1, 2, 4


def _invalid(reason: str):
    raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Invalid initial inventory: " + reason)


def _number(value, description: str, *, positive: bool = False, text: bool = False) -> int:
    if type(value) is not int and not (text and isinstance(value, str)):
        _invalid(description)
    try:
        number = int(value)
    except (ValueError, OverflowError):
        _invalid(description)
    if (number < int(positive) or number > (1 << 63) - 1
            or isinstance(value, str) and str(number) != value):
        _invalid(description)
    return number


def _identity(value, description: str) -> str:
    if not isinstance(value, str) or not value:
        _invalid(description)
    return value


def _level_rows(catalog: _Catalog, table: str):
    result = {}
    for row in catalog.rows(table, required=True):
        identity = _identity(row.get("id"), table + " identity")
        level = _number(row.get("level"), table + " level", positive=True)
        key = identity, level
        if key in result:
            _invalid("duplicate " + table + " level")
        result[key] = row
    return result


def _initial_releases(card, releases):
    identity = _identity(card.get("cardLevelReleaseId"), "card level-release identity")
    row = releases.get((identity, 1))
    if row is None:
        _invalid("missing level-one card releases")
    targets = row.get("targets")
    if not isinstance(targets, list):
        _invalid("card release targets")
    skills, photos, seen = set(), 0, set()
    for target in targets:
        if not isinstance(target, dict):
            _invalid("card release target")
        kind = _number(target.get("type"), "card release type", positive=True)
        number = _number(target.get("number"), "card release number", positive=True)
        if (kind, number) in seen:
            _invalid("duplicate card release target")
        seen.add((kind, number))
        if kind == 1:  # CardLevelReleaseType.Skill
            if number > 4:
                _invalid("unsupported initial skill position")
            skills.add(number)
        elif kind == 7:  # Each Photo target adds this many slots.
            photos += number
        elif kind == 4:  # Story visibility is not a read/clear transaction.
            continue
        elif kind in (2, 3):
            _invalid("level-one ability releases need a separate supported contract")
        else:
            _invalid("unsupported card release type")
    if 1 not in skills:
        _invalid("initial card has no first skill")
    return skills, photos


def _initial_skill(skills, identity: str):
    row = skills.get(identity)
    if row is None:
        _invalid("unknown initial skill identity")
    levels = row.get("levels")
    if not isinstance(levels, list) or any(not isinstance(level, dict) for level in levels):
        _invalid("skill levels")
    numbers = [_number(level.get("level"), "skill level", positive=True) for level in levels]
    if len(numbers) != len(set(numbers)):
        _invalid("duplicate skill level")
    first = [level for level in levels if level.get("level") == 1]
    if len(first) != 1 or _number(first[0].get("requiredCardLevel", 0), "skill required level") > 1:
        _invalid("initial skill has no usable first level")


@dataclass(frozen=True)
class InitialInventory:
    """An immutable prepared grant; protobuf payloads contain no timestamps."""

    schema_fingerprint: str
    character_ids: tuple[str, ...]
    card_ids: tuple[str, ...]
    item_amounts: tuple[tuple[str, int], ...]
    required_costume_ids: tuple[str, ...]
    required_hair_ids: tuple[str, ...]
    _card_owners: tuple[tuple[str, str], ...] = field(repr=False)
    _cards: tuple[bytes, ...] = field(repr=False)
    _snapshot_type: type = field(repr=False, compare=False)
    _card_type: type = field(repr=False, compare=False)

    @property
    def card_by_character(self):
        """Actual Card.characterId mapping; reward entry orders can differ."""
        return MappingProxyType(dict(self._card_owners))


def prepare_initial_inventory(schema, master_dir: Path) -> InitialInventory:
    """Validate the named original reward and prepare level-one card payloads.

    Required JSON tables: Reward, Item, Character, Costume, Hair, Card,
    CardParameter, CardRarity, CardLevelRelease, Skill and Setting. Preparation
    has no state access and never applies initial_user_gift or another reward.
    """
    catalog = _Catalog(master_dir)
    reward = catalog.ids("Reward", required=True).get(_REWARD)
    if reward is None:
        _invalid("missing initial_user_reward")
    resources = reward.get("resources")
    if not isinstance(resources, list) or not resources:
        _invalid("empty initial_user_reward")
    selected = {_ITEM: [], _CARD: [], _CHARACTER: []}
    seen = set()
    for resource in resources:
        if not isinstance(resource, dict):
            _invalid("reward resource")
        kind = _number(resource.get("resourceType"), "reward resource type", positive=True)
        identity = _identity(resource.get("resourceId"), "reward resource identity")
        amount = _number(resource.get("amount"), "reward resource amount", positive=True)
        if kind not in selected or (kind, identity) in seen:
            _invalid("unsupported or duplicate reward resource")
        if kind != _ITEM and amount != 1:
            _invalid("initial unique resources must have amount one")
        selected[kind].append((identity, amount))
        seen.add((kind, identity))
    if not selected[_CARD] or not selected[_CHARACTER]:
        _invalid("initial reward needs cards and characters")
    cards = catalog.ids("Card", required=True)
    characters = catalog.ids("Character", required=True)
    costumes = catalog.ids("Costume", required=True)
    hairs = catalog.ids("Hair", required=True)
    items = catalog.ids("Item", required=True)
    skills = catalog.ids("Skill", required=True)
    parameters = _level_rows(catalog, "CardParameter")
    releases = _level_rows(catalog, "CardLevelRelease")
    rarities = {}
    for row in catalog.rows("CardRarity", required=True):
        rarity = _number(row.get("rarity"), "card rarity", positive=True)
        if rarity in rarities:
            _invalid("duplicate card rarity")
        rarities[rarity] = row
    settings = catalog.rows("Setting", required=True)
    if len(settings) != 1:
        _invalid("one Setting row is required")
    mental = _number(settings[0].get("cardDefaultMental"), "default mental")
    technique = _number(settings[0].get("cardDefaultTechnique"), "default technique")
    for identity, _ in selected[_ITEM]:
        if identity not in items:
            _invalid("unknown initial item identity")
    character_ids = tuple(identity for identity, _ in selected[_CHARACTER])
    required_costumes, required_hairs = set(), set()

    def appearance(costume_id, owner):
        costume_id = _identity(costume_id, "initial costume identity")
        costume = costumes.get(costume_id)
        if costume is None or costume.get("characterId") != owner:
            _invalid("initial costume ownership")
        hair_id = _identity(costume.get("defaultHairId"), "initial default hair")
        if hair_id not in hairs or hairs[hair_id].get("characterId") != owner:
            _invalid("initial hair ownership")
        required_costumes.add(costume_id)
        required_hairs.add(hair_id)

    for identity in character_ids:
        character = characters.get(identity)
        if character is None:
            _invalid("unknown initial character identity")
        appearance(character.get("defaultCostumeId"), identity)
        if character.get("defaultLiveCostumeId"):
            appearance(character["defaultLiveCostumeId"], identity)
    snapshot_type = schema.response_type(_USER_GET)
    card_type = message_factory.GetMessageClass(snapshot_type.DESCRIPTOR.fields_by_name["cards"].message_type)
    prepared, owners = [], []
    for identity, _ in selected[_CARD]:
        card = cards.get(identity)
        if card is None:
            _invalid("unknown initial card identity")
        owner = card.get("characterId")
        if owner not in character_ids or any(character == owner for character, _ in owners):
            _invalid("initial cards must match their distinct reward characters")
        owners.append((owner, identity))
        rarity = _number(card.get("initialRarity"), "initial card rarity", positive=True)
        rarity_row = rarities.get(rarity)
        if rarity_row is None:
            _invalid("missing initial rarity parameters")
        parameter_id = _identity(card.get("cardParameterId"), "card parameter identity")
        parameter = parameters.get((parameter_id, 1))
        if parameter is None:
            _invalid("missing level-one card parameters")
        bonus = _number(rarity_row.get("parameterBonusPermil"), "rarity parameter multiplier", positive=True)
        value = _number(parameter.get("value"), "base card parameter", text=True)
        stamina_value = _number(parameter.get("staminaValue"), "base stamina parameter", text=True)
        values = dict(cardId=identity, level=1, baseLevel=1, rarity=rarity,
                      mental=mental, technique=technique, displayType=1)
        for name in ("vocal", "dance", "visual", "stamina"):
            ratio = _number(card.get(name + "RatioPermil"), name + " ratio")
            base = stamina_value if name == "stamina" else value
            amount = ((base * ratio) // 1000 * bonus) // 1000
            _number(amount, name + " result")
            values[name] = values["base" + name.capitalize()] = amount
        unlocked, photo_slots = _initial_releases(card, releases)
        values["photoEquipableCount"] = values["basePhotoEquipableCount"] = photo_slots
        for position in range(1, 5):
            reference = card.get("skillId" + str(position), "")
            if not isinstance(reference, str) or reference and reference not in skills:
                _invalid("unknown card skill master reference")
        for position in unlocked:
            identity_field = "skillId" + str(position)
            skill = _identity(card.get(identity_field), "released initial skill")
            _initial_skill(skills, skill)
            values[identity_field] = values["baseSkillId" + str(position)] = skill
            values["skillLevel" + str(position)] = values["baseSkillLevel" + str(position)] = 1
        if card.get("rewardCostumeId"):
            appearance(card["rewardCostumeId"], owner)
        hair_rewards = card.get("rewardHairIds", [])
        if not isinstance(hair_rewards, list):
            _invalid("initial card hair rewards")
        for hair_id in [*hair_rewards, *([card["rewardHairId"]] if card.get("rewardHairId") else [])]:
            hair_id = _identity(hair_id, "initial card hair reward")
            if hair_id not in hairs or hairs[hair_id].get("characterId") != owner:
                _invalid("initial card hair reward ownership")
            required_hairs.add(hair_id)
        prepared.append(card_type(**values).SerializeToString())
    if {owner for owner, _ in owners} != set(character_ids):
        _invalid("each initial character needs its canonical card")
    return InitialInventory(schema.fingerprint, character_ids,
                            tuple(identity for identity, _ in selected[_CARD]), tuple(selected[_ITEM]),
                            tuple(sorted(required_costumes)), tuple(sorted(required_hairs)),
                            tuple(owners), tuple(prepared), snapshot_type, card_type)


def apply_initial_inventory(snapshot, plan: InitialInventory, *, obtained_time: int) -> None:
    """Apply once to an empty local starter snapshot, preserving other fields.

    Persistence/provenance checks belong to the caller's State transaction.
    This deliberately refuses existing inventory and does not select a deck.
    The already prepared character/default-appearance grant must be present.
    Validation completes before changing even the caller's in-memory snapshot.
    """
    obtained_time = _number(obtained_time, "obtained timestamp", positive=True)
    if not isinstance(snapshot, plan._snapshot_type):
        _invalid("snapshot and prepared schema do not match")
    if snapshot.cards or snapshot.items:
        _invalid("inventory is not an empty local starter")
    owned = [row.characterId for row in snapshot.characters]
    if len(owned) != len(set(owned)) or not set(plan.character_ids).issubset(owned):
        _invalid("initial reward characters have not been prepared")
    if not set(plan.required_costume_ids).issubset(row.costumeId for row in snapshot.costumes):
        _invalid("initial reward costumes have not been prepared")
    if not set(plan.required_hair_ids).issubset(row.hairId for row in snapshot.hairs):
        _invalid("initial reward hairs have not been prepared")
    result = plan._snapshot_type()
    result.CopyFrom(snapshot)
    for payload in plan._cards:
        card = result.cards.add()
        card.ParseFromString(payload)
        card.obtainedTime = obtained_time
    for identity, amount in plan.item_amounts:
        result.items.add(itemId=identity, amount=amount, expiredTime=0)
    snapshot.CopyFrom(result)
