"""Read-only prepared input for the pinned first main live, local rules v5.

The native engine receives current owned card parameters and learned skills,
not a captured account or a predetermined result. Appearance projection uses
the separately recovered 6.1.1 DeckCard getters. Settlement is the caller's
responsibility and must use the same transactional snapshot as this input.
"""
from __future__ import annotations

import base64
from pathlib import Path

from google.protobuf import message_factory
from google.protobuf.json_format import ParseDict, ParseError

from .card_progression import prepare_enhancement
from .gameplay import _Catalog
from .live_assets import project_live_assets
from .rpc import RpcCode, RpcFailure


RULESET = "live-v5"
MAIN_QUEST_ID = "qt-main-1-001-01"
MAIN_AREA_ID = "area-main-001"
SCHEMA_SHA256 = "0fcf90596261dcd9bbed165bd93859dc30127e2a494e6529bafbd8885675edf3"
MASTER_VERSION = "961e456499039e31248a818a911c8d95f92461f86aff4674ba07e29c32afcf60"
REQUIRED_MASTER_TABLES = (
    "Area", "Quest", "Setting", "Music", "MusicChartPattern", "Card", "Character", "Costume", "Hair",
    "Skill", "SkillEfficacy", "SkillTrigger", "SkillTarget", "CardParameter", "CardRarity",
    "CardLevelRelease", "CardLevel", "ManagerLevel", "Item", "Consumption", "QuestPressure",
    "QuestAudienceAdvantage", "ComboAdvantage", "QuestStaminaConsumption",
)


def _fail(detail, code=RpcCode.FAILED_PRECONDITION):
    raise RpcFailure(code, "Local live input: " + detail)


def _number(value, label, *, positive=False):
    if type(value) is not int and type(value) is not str:
        _fail("invalid " + label)
    try:
        result = int(value)
    except (ValueError, OverflowError):
        _fail("invalid " + label)
    if (result < int(positive) or result > (1 << 63) - 1
            or isinstance(value, str) and str(result) != value):
        _fail("invalid " + label)
    return result


def _identity(value, label, *, optional=False):
    if not isinstance(value, str) or not optional and not value:
        _fail("invalid " + label)
    return value


def _known(message):
    for field, value in message.ListFields():
        for item in value if field.is_repeated else (value,):
            if field.message_type is not None:
                _known(item)
            elif field.enum_type is not None and item not in field.enum_type.values_by_number:
                _fail("unknown master enum")


def _master_message(schema, table, row):
    try:
        cls = message_factory.GetMessageClass(schema.pool.FindMessageTypeByName("master." + table))
        result = cls()
        ParseDict(row, result)
        _known(result)
        return result
    except (KeyError, ValueError, TypeError, ParseError):
        _fail("malformed " + table + " master record")


def _chart(catalog, identity):
    rows = [row for row in catalog.rows("MusicChartPattern", required=True) if row.get("id") == identity]
    if not rows or len(rows) > 10000:
        _fail("missing or oversized music chart")
    seen, has_beats = set(), False
    for row in rows:
        number = _number(row.get("number"), "chart number")
        kind = _number(row.get("type", 0), "chart type")
        position = _number(row.get("position", 0), "chart position")
        if number in seen or kind not in (0, 1, 2, 3) or kind in (2, 3) and not 1 <= position <= 5:
            _fail("invalid chart ordering, type or skill position")
        seen.add(number)
        has_beats = has_beats or kind == 1
    if not has_beats:
        _fail("this first main live requires ordinary beats")
    return sorted(rows, key=lambda row: _number(row["number"], "chart number"))


def prepare_main_live(schema, master_dir, snapshot, quest_id, deck_number, seed):
    """Prepare JSON-v1 without mutating the supplied snapshot or any storage.

    Only the first ordinary main quest is supported. Cards must remain in the
    verified unranked, unsupported-by-assistance initial form below the next
    release/skill-upgrade boundary. An initial rarity XP of zero is accepted as
    the historical starter representation, without changing it or granting XP.
    No photo/accessory/buddy preparation or result/reward calculation occurs.
    """
    if quest_id != MAIN_QUEST_ID:
        _fail("this main quest is not supported", RpcCode.UNIMPLEMENTED)
    if type(deck_number) is not int or deck_number <= 0:
        _fail("a positive saved deck number is required", RpcCode.INVALID_ARGUMENT)
    if type(seed) is not int or not 0 <= seed < 1 << 64:
        _fail("seed must be an unsigned 64-bit integer", RpcCode.INVALID_ARGUMENT)
    catalog = _Catalog(Path(master_dir) if master_dir is not None else None)
    if schema.fingerprint != SCHEMA_SHA256 or catalog.version() != MASTER_VERSION:
        _fail("the audited 6.1.1 schema and master version are required")
    if not isinstance(snapshot, schema.response_type("/api.User/Get")):
        _fail("snapshot and schema do not match")
    if not snapshot.HasField("user") or not snapshot.HasField("userPublic") or not snapshot.userPublic.publicUserId:
        _fail("a local user and public identity are required")
    for table in REQUIRED_MASTER_TABLES:
        catalog.rows(table, required=True)
    quest = catalog.ids("Quest", required=True).get(quest_id)
    if quest is None:
        _fail("the supported quest is missing from master data")
    areas = catalog.ids("Area", required=True)
    area = areas.get(MAIN_AREA_ID)
    if (quest.get("areaId") != MAIN_AREA_ID or area is None or area.get("type") != 1
            or quest_id not in area.get("questIds", [])):
        _fail("the supported quest has an invalid main-area link")
    if (quest.get("viewConditionId") or quest.get("unlockConditionId")
            or area.get("viewConditionId") or area.get("unlockConditionId")
            or quest.get("liveBonusGroupId") or quest.get("QuestCharacterAdvantageId")):
        _fail("quest conditions or live bonuses are not supported", RpcCode.UNIMPLEMENTED)
    if (_number(quest.get("clearScore"), "clear score", positive=True) != 3000
            or quest.get("musicId") != "music-hsm-006"
            or quest.get("musicChartPatternId") != "chart-hsm-006-002"
            or _number(quest.get("ticketAmount", 0), "ticket cost") != 0):
        _fail("the supported first-quest definition differs from its pin")
    for field in ("difficultyLevel", "maxCapacity", "mentalThreshold"):
        _number(quest.get(field), field, positive=True)
    positions = sorted((row for row in snapshot.deckPositions if row.number == deck_number), key=lambda row: row.position)
    if any(row.photoIds or row.part1AccessoryId or row.part2AccessoryId for row in positions):
        _fail("live photo and accessory bonuses are not supported", RpcCode.UNIMPLEMENTED)
    query = schema.request_type("/api.Quest/ListAsset")(questId=quest_id, deckNumber=deck_number)
    appearances = project_live_assets(schema, snapshot, query, catalog).characterAssets
    decks = [row for row in snapshot.decks if row.number == deck_number]
    if len(decks) != 1:
        _fail("the selected saved deck is ambiguous")
    cards = {row.cardId: row for row in snapshot.cards}
    characters = {row.characterId: row for row in snapshot.characters}
    masters = catalog.ids("Card", required=True)
    owners = catalog.ids("Character", required=True)
    music = catalog.ids("Music", required=True).get(quest["musicId"])
    pressure_id = _identity(quest.get("questPressureId"), "quest pressure reference")
    pressure = catalog.ids("QuestPressure", required=True).get(pressure_id)
    if music is None or pressure is None:
        _fail("quest music or pressure reference is missing")
    if _number(pressure.get("weightPermil"), "pressure weight", positive=True) == 0:
        _fail("invalid pressure weight")
    chart = _chart(catalog, quest["musicChartPatternId"])
    reference = _chart(catalog, "chart-hsm-006-001")
    audience_id = _identity(quest.get("QuestAudienceAdvantageId"), "quest audience reference")
    combo_id = _identity(music.get("comboAdvantageId"), "music combo reference")
    audience = [row for row in catalog.rows("QuestAudienceAdvantage") if row.get("id") == audience_id]
    combo = [row for row in catalog.rows("ComboAdvantage") if row.get("id") == combo_id]
    if not audience or not combo:
        _fail("audience or combo references are missing")
    for rows, key in ((audience, "audienceAmount"), (combo, "comboCount"),
                      (catalog.rows("QuestStaminaConsumption"), "remainStaminaRatioPercent")):
        values = [_number(row.get(key), key) for row in rows]
        if len(set(values)) != len(values):
            _fail("numeric live master breakpoints are ambiguous")
    user_type = message_factory.GetMessageClass(schema.pool.FindMessageTypeByName("api.LiveUserInfo"))
    user = user_type(index=1, userId=snapshot.userPublic.publicUserId, name=snapshot.user.name, isNpc=False)
    user.userDeck.deckName = decks[0].name
    metadata, learned = [], set()
    for position, appearance in zip(positions, appearances):
        card = cards[position.cardId]
        # Same-level validation is pure and retains every input/unknown field.
        prepare_enhancement(schema, Path(master_dir), card, card.level,
                            manager_level=snapshot.user.managerLevel,
                            normalize_starter_rarity=card.rarityTotalExp == 0)
        master = masters[card.cardId]
        owner = appearance.characterId
        if master.get("characterId") != owner:
            _fail("card and display character disagree")
        character = characters[owner]
        live = user.userDeck.cards.add(index=position.position, cardId=card.cardId, level=card.level,
            rarity=card.rarity, evolutionLevel=card.evolutionLevel, vocal=card.vocal, dance=card.dance,
            visual=card.visual, stamina=card.stamina, mental=card.mental, technique=card.technique,
            displayCharacterId=owner, displayCostumeId=appearance.costumeId, displayHairId=appearance.hairId)
        for slot in range(1, 5):
            identity = getattr(card, "skillId" + str(slot))
            if identity:
                learned.add(identity)
                live.skills.add(index=slot, skillId=identity, skillLevel=getattr(card, "skillLevel" + str(slot)), possessionType=1)
        ratios = [(kind, _number(master.get(name + "RatioPermil"), name + " ratio"))
                  for kind, name in ((1, "vocal"), (2, "dance"), (3, "visual"))]
        kind = _number(master.get("type"), "card type", positive=True)
        if kind not in (1, 2, 3):
            _fail("unknown card scoring role")
        group = owners[owner].get("characterGroupId")
        if not isinstance(group, str) or not group:
            _fail("missing character scoring group")
        metadata.append({"index": position.position, "character_id": owner, "group_id": group,
            "type": kind, "attribute": max(ratios, key=lambda row: row[1])[0],
            "light_fans": _number(getattr(character, "lightFanAmount", 0), "light fans"),
            "middle_fans": _number(getattr(character, "middleFanAmount", 0), "middle fans"),
            "heavy_fans": _number(getattr(character, "heavyFanAmount", 0), "heavy fans")})
    skills = catalog.ids("Skill", required=True)
    efficacies = catalog.ids("SkillEfficacy", required=True)
    triggers = catalog.ids("SkillTrigger", required=True)
    targets = catalog.ids("SkillTarget", required=True)
    effects = set()
    for identity in learned:
        skill = skills[identity]
        levels = [row for row in skill.get("levels", []) if row.get("level") == 1]
        details = levels[0].get("skillDetails") if len(levels) == 1 else None
        if not isinstance(details, list) or not details or any(not isinstance(row, dict) for row in details):
            _fail("learned skill lacks usable effects")
        for trigger in [levels[0].get("triggerId", ""), *[row.get("triggerId", "") for row in details]]:
            _identity(trigger, "skill trigger reference", optional=True)
            if trigger and trigger not in triggers:
                _fail("learned skill has a missing trigger")
        for detail in details:
            effect_id = _identity(detail.get("efficacyId"), "skill efficacy reference")
            if effect_id not in efficacies:
                _fail("learned skill has a missing efficacy")
            effects.add(effect_id)
            target = _identity(efficacies[effect_id].get("skillTargetId", ""), "skill target reference", optional=True)
            if target and target not in targets:
                _fail("learned effect has a missing target")
    selected = {"Quest": [quest], "Setting": catalog.rows("Setting"), "Chart": chart,
        "ReferenceChart": reference, "UserInfo": [user], "QuestPressure": [pressure],
        "QuestAudienceAdvantage": audience, "ComboAdvantage": combo,
        "QuestStaminaConsumption": catalog.rows("QuestStaminaConsumption"),
        "Skill": [skills[key] for key in sorted(learned)],
        "SkillEfficacy": [efficacies[key] for key in sorted(effects)],
        "SkillTrigger": list(triggers.values()), "SkillTarget": list(targets.values())}
    prepared = {}
    for table, rows in selected.items():
        actual = "MusicChartPattern" if table in ("Chart", "ReferenceChart") else table
        messages = rows if table == "UserInfo" else [_master_message(schema, actual, row) for row in rows]
        prepared[table] = [base64.b64encode(message.SerializeToString(deterministic=True)).decode("ascii") for message in messages]
    return {"input_version": 1, "seed": seed, "music_id": music["id"], "proto": prepared,
            "cards": metadata, "schema_sha256": schema.fingerprint, "master_version": catalog.version()}
