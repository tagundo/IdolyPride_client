"""Read-only prepared input for the pinned first main area, local rules v5.

The native engine receives current owned card parameters and learned skills,
not a captured account or a predetermined result. Appearance projection uses
the separately recovered 6.1.1 DeckCard getters. Settlement is the caller's
responsibility and must use the same transactional snapshot as this input.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from google.protobuf import message_factory
from google.protobuf.json_format import ParseDict, ParseError

from .card_progression import prepare_enhancement
from .gameplay import _Catalog
from .live_accessories import prepare_starter_accessories
from .live_assets import project_live_assets
from .rpc import RpcCode, RpcFailure


RULESET = "live-v5"
MAIN_QUEST_ID = "qt-main-1-001-01"
MAIN_AREA_ID = "area-main-001"


@dataclass(frozen=True)
class MainQuestDefinition:
    quest_id: str
    music_id: str
    chart_id: str
    reference_chart_id: str
    clear_score: int
    manager_exp: int
    card_exp: int
    reward_id: str
    rewards: tuple[tuple[int, str, int], ...]


# Audited 6.1.1 first-area definitions, not a rule for arbitrary main quests.
# Keep the reference chart explicit: using the first song's chart for another
# song would silently change the local-v5 beat normalization.
MAIN_QUEST_DEFINITIONS = (
    MainQuestDefinition(MAIN_QUEST_ID, "music-hsm-006", "chart-hsm-006-002", "chart-hsm-006-001",
        3000, 50, 40, "rd-main-quest-001-01", ((1, "item-card_enhance", 290),
        (8, "", 500), (15, "", 50), (3, "ac-1-visual-02", 1))),
    MainQuestDefinition("qt-main-1-001-02", "music-sun-001", "chart-sun-001-002", "chart-sun-001-001",
        5400, 65, 57, "rd-main-quest-001-02", ((1, "item-card_enhance", 590),
        (8, "", 500), (15, "", 50), (3, "ac-1-vocal-02", 1))),
    MainQuestDefinition("qt-main-1-001-03", "music-moon-004", "chart-moon-004-002", "chart-moon-004-001",
        10000, 85, 74, "rd-main-quest-001-03", ((1, "item-card_enhance", 890),
        (8, "", 500), (15, "", 50), (1, "item-photo_shooting-01", 1))),
)
MAIN_QUEST_IDS = tuple(row.quest_id for row in MAIN_QUEST_DEFINITIONS)
SCHEMA_SHA256 = "0fcf90596261dcd9bbed165bd93859dc30127e2a494e6529bafbd8885675edf3"
MASTER_VERSION = "961e456499039e31248a818a911c8d95f92461f86aff4674ba07e29c32afcf60"
REQUIRED_MASTER_TABLES = (
    "Area", "Quest", "Stage", "Setting", "Music", "MusicChartPattern", "Card", "Character", "Costume", "Hair",
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


def main_quest_definition(quest_id):
    return next((row for row in MAIN_QUEST_DEFINITIONS if row.quest_id == quest_id), None)


def validated_main_quest(catalog, definition):
    """Validate the bounded stage contract without reading or changing progress."""
    quest = catalog.ids("Quest", required=True).get(definition.quest_id)
    area = catalog.ids("Area", required=True).get(MAIN_AREA_ID)
    if (quest is None or area is None or quest.get("areaId") != MAIN_AREA_ID
            or area.get("type") != 1 or area.get("questIds") != list(MAIN_QUEST_IDS)):
        _fail("the supported quest has an invalid main-area link")
    if (quest.get("viewConditionId") or quest.get("unlockConditionId")
            or area.get("viewConditionId") or area.get("unlockConditionId")
            or quest.get("liveBonusGroupId") or quest.get("QuestCharacterAdvantageId")):
        _fail("quest conditions or live bonuses are not supported", RpcCode.UNIMPLEMENTED)
    if (quest.get("musicId") != definition.music_id
            or quest.get("musicChartPatternId") != definition.chart_id
            or quest.get("stageId") != "stage-live-house-00-00"
            or _number(quest.get("clearScore"), "clear score", positive=True) != definition.clear_score
            or _number(quest.get("rewardManagerExp"), "manager experience") != definition.manager_exp
            or _number(quest.get("rewardCardExp"), "card experience") != definition.card_exp
            or quest.get("clearRewardId") != definition.reward_id
            or _number(quest.get("ticketAmount", 0), "ticket cost") != 0
            or _number(quest.get("dailyLimitCount", 0), "daily limit") != 0
            or type(quest.get("liveSkipType")) is not int or quest["liveSkipType"] != 2):
        _fail("the supported first-area definition differs from its pin")
    if (definition.music_id not in catalog.ids("Music", required=True)
            or quest["stageId"] not in catalog.ids("Stage", required=True)):
        _fail("quest music or stage reference is missing")
    return quest, area


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

    Only the three first-area main quests are supported. Cards must remain in the
    verified unranked, unsupported-by-assistance initial form below the next
    release/skill-upgrade boundary. An initial rarity XP of zero is accepted as
    the historical starter representation, without changing it or granting XP.
    Only the two pinned plain first-area accessory additions are prepared;
    photos, other accessories, buddies and result/reward calculation are absent.
    """
    definition = main_quest_definition(quest_id)
    if definition is None:
        _fail("this main quest is not supported", RpcCode.UNIMPLEMENTED)
    if type(deck_number) is not int or deck_number <= 0:
        _fail("a positive saved deck number is required", RpcCode.INVALID_ARGUMENT)
    if type(seed) is not int or not 0 <= seed < 1 << 64:
        _fail("seed must be an unsigned 64-bit integer", RpcCode.INVALID_ARGUMENT)
    catalog = _Catalog(Path(master_dir) if master_dir is not None else None)
    if schema.fingerprint != SCHEMA_SHA256:
        _fail("the audited 6.1.1 schema and master version are required")
    if catalog.version() != MASTER_VERSION:
        if catalog.version() != _LATEST_MASTER_VERSION:
            _fail("the audited 6.1.1 schema and master version are required")
        from .public_cohort_support import require_master_cohort
        try:
            require_master_cohort(master_dir, "main_live")
        except (OSError, ValueError):
            _fail("latest public master cohort is unapproved or changed")
    if not isinstance(snapshot, schema.response_type("/api.User/Get")):
        _fail("snapshot and schema do not match")
    if not snapshot.HasField("user") or not snapshot.HasField("userPublic") or not snapshot.userPublic.publicUserId:
        _fail("a local user and public identity are required")
    for table in REQUIRED_MASTER_TABLES:
        catalog.rows(table, required=True)
    quest, _area = validated_main_quest(catalog, definition)
    for field in ("difficultyLevel", "maxCapacity", "mentalThreshold"):
        _number(quest.get(field), field, positive=True)
    positions = sorted((row for row in snapshot.deckPositions if row.number == deck_number), key=lambda row: row.position)
    accessory_bonuses = prepare_starter_accessories(snapshot, positions, catalog)
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
    reference = _chart(catalog, definition.reference_chart_id)
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
        attribute = accessory_bonuses.get(position.position)
        if attribute is not None:
            value = _number(getattr(live, attribute), "accessory base parameter")
            if value > (1 << 63) - 1 - 64:
                _fail("live accessory parameter overflows")
            setattr(live, attribute, value + 64)
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


_LATEST_MASTER_VERSION = "6b77e0d8a64b26d5bebd09a7c19a47f2dfad2af914c5160418aa2e7292e13a11"
LATEST_SEMANTIC_REASONS = frozenset(("schema_changed", "version_changed", "input_invalid",
    "dream_source_changed", "dream_setting_changed", "dream_condition_changed", "dream_manual_changed",
    "dream_mission_changed", "dream_area_changed", "dream_quest_changed", "main_quest_changed",
    "main_chart_changed", "main_numeric_changed", "main_card_changed", "main_skill_changed",
    "main_model_changed", "main_membership_changed", "main_reference_missing", "main_addition_scope_changed"))


class LatestSemanticsError(ValueError):
    def __init__(self, scope, reason):
        scope = scope if scope in ("dream", "main_live") else "main_live"
        reason = reason if reason in LATEST_SEMANTIC_REASONS else "input_invalid"
        self.code = "latest_" + scope + "_semantics_changed"
        self.receipt = {"schema":1, "scope":scope, "status":"FAIL", "reason_code":reason}
        super().__init__(self.code + ":" + reason)


def _audit_need(ok, scope, reason):
    if not ok: raise LatestSemanticsError(scope, reason)


def _audit_canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def _audit_read(path, maximum=64 * 1024 * 1024):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as source:
        before = os.fstat(source.fileno())
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= maximum: raise ValueError()
        raw = source.read(maximum + 1)
        after = os.fstat(source.fileno())
        if len(raw) != before.st_size or (before.st_size,before.st_mtime_ns,before.st_ctime_ns) != (after.st_size,after.st_mtime_ns,after.st_ctime_ns): raise ValueError()
        return raw


class _AuditCatalog(_Catalog):
    """Build-only public input reader; never reads runtime authority or State."""
    def __init__(self, schema, directory, expected, scope):
        super().__init__(Path(directory))
        self.schema, self.scope, self.pins = schema, scope, {}
        raw = _audit_read(self.directory / "!version.txt", 4096)
        _audit_need(raw.decode("utf-8").strip() == expected, scope, "version_changed")
        self.pins["!version.txt"] = hashlib.sha256(raw).hexdigest()
        self.expected = expected

    def version(self): return self.expected

    def rows(self, table, *, required=False):
        if table not in self.loaded:
            from .schema import normalize_master_row
            raw = _audit_read(self.directory / (table + ".json"))
            def pairs(items):
                value = {}
                for key,item in items:
                    if key in value: raise ValueError()
                    value[key] = item
                return value
            rows = json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            _audit_need(type(rows) is list and len(rows) <= 500000 and all(type(row) is dict for row in rows), self.scope, "input_invalid")
            descriptor = self.schema.pool.FindMessageTypeByName("master." + table)
            self.loaded[table] = [normalize_master_row(table, row, descriptor)[0] for row in rows]
            self.pins[table + ".json"] = hashlib.sha256(raw).hexdigest()
        return super().rows(table, required=required)


def _audit_wire(schema, table, rows):
    from .schema import normalize_master_row
    descriptor = schema.pool.FindMessageTypeByName("master." + table)
    return sorted(hashlib.sha256(_master_message(schema, table, normalize_master_row(table,row,descriptor)[0]).SerializeToString(deterministic=True)).hexdigest() for row in rows)


def _audit_equal(schema, table, old, new, scope, reason):
    _audit_need(_audit_wire(schema,table,old) == _audit_wire(schema,table,new), scope, reason)


def _audit_conditions(catalog, seeds):
    index = catalog.ids("Condition", required=True)
    pending, seen = list(seeds), set()
    def strings(value):
        if type(value) is str: yield value
        elif type(value) is dict:
            for item in value.values(): yield from strings(item)
        elif type(value) is list:
            for item in value: yield from strings(item)
    while pending:
        key = pending.pop()
        if key in seen: continue
        _audit_need(key in index and len(seen) < 100000, catalog.scope, "dream_condition_changed")
        seen.add(key)
        pending.extend(value for value in strings(index[key]) if value.startswith("cd-") and value not in seen)
    return [index[key] for key in sorted(seen)]


def _audit_receipt(scope, schema, old, latest, projection, checks):
    for source in (old, latest):
        for name, expected in source.pins.items():
            _audit_need(hashlib.sha256(_audit_read(source.directory / name)).hexdigest() == expected, scope, "input_invalid")
    return {"schema":1, "scope":scope, "status":"PASS", "schema_sha256":schema.fingerprint,
        "legacy_master_version":MASTER_VERSION, "master_version":_LATEST_MASTER_VERSION,
        "projection_equal":True, "external_controls_equal":True,
        "projection_sha256":hashlib.sha256(_audit_canonical(projection)).hexdigest(), "checks":checks,
        "input_files":{"legacy":dict(sorted(old.pins.items())),"latest":dict(sorted(latest.pins.items()))},
        "state_changed":False,"runtime_authority_consumed":False}


def audit_latest_main_live_semantics(schema, legacy_master_dir, latest_all_master_dir):
    """Compare live-v5 prepared-input controls, permitting bounded new inventory."""
    scope = "main_live"
    try:
        _audit_need(schema.fingerprint == SCHEMA_SHA256, scope, "schema_changed")
        old = _AuditCatalog(schema,legacy_master_dir,MASTER_VERSION,scope)
        latest = _AuditCatalog(schema,latest_all_master_dir,_LATEST_MASTER_VERSION,scope)
        projection = {"ruleset":RULESET,"quests":[],"retained":{}}
        for definition in MAIN_QUEST_DEFINITIONS:
            first, area = validated_main_quest(old,definition)
            second, new_area = validated_main_quest(latest,definition)
            _audit_equal(schema,"Quest",[first],[second],scope,"main_quest_changed")
            _audit_equal(schema,"Area",[area],[new_area],scope,"main_quest_changed")
            for identity in (definition.chart_id,definition.reference_chart_id):
                _audit_equal(schema,"MusicChartPattern",_chart(old,identity),_chart(latest,identity),scope,"main_chart_changed")
            for table, identity in (("Stage",first["stageId"]),("Music",first["musicId"]),
                                    ("Reward",definition.reward_id),("QuestPressure",first["questPressureId"])):
                a,b = old.ids(table,required=True).get(identity), latest.ids(table,required=True).get(identity)
                _audit_need(a is not None and b is not None,scope,"main_reference_missing")
                _audit_equal(schema,table,[a],[b],scope,"main_quest_changed")
            for table,identity,key in (("QuestAudienceAdvantage",first["QuestAudienceAdvantageId"],"audienceAmount"),
                                      ("ComboAdvantage",old.ids("Music")[first["musicId"]]["comboAdvantageId"],"comboCount")):
                a=[row for row in old.rows(table,required=True) if row.get("id")==identity]
                b=[row for row in latest.rows(table,required=True) if row.get("id")==identity]
                _audit_need(a and b and len({_number(row.get(key),key) for row in b})==len(b),scope,"main_numeric_changed")
                _audit_equal(schema,table,a,b,scope,"main_numeric_changed")
            projection["quests"].append(definition.quest_id)
        for table in ("Setting","CardParameter","CardRarity","CardLevelRelease","CardLevel","ManagerLevel",
                      "Consumption","QuestStaminaConsumption"):
            a,b=old.rows(table,required=True),latest.rows(table,required=True)
            _audit_equal(schema,table,a,b,scope,"main_numeric_changed")
            projection["retained"][table]=_audit_wire(schema,table,a)
        for table, ids in (("Item",{"item-card_enhance","item-photo_shooting-01"}),
                           ("Accessory",{"ac-1-vocal-02","ac-1-visual-02"})):
            a,b=old.ids(table,required=True),latest.ids(table,required=True)
            _audit_need(ids <= a.keys() and ids <= b.keys(),scope,"main_reference_missing")
            _audit_equal(schema,table,[a[key] for key in sorted(ids)],[b[key] for key in sorted(ids)],scope,"main_numeric_changed")
        # Validate complete candidate rows before selecting their used fields;
        # an additive record is never permission to ignore unknown JSON keys.
        for table in ("Card", "Character", "Costume", "Hair"):
            _audit_wire(schema,table,latest.rows(table,required=True))
        cards, new_cards=old.ids("Card",required=True), latest.ids("Card",required=True)
        _audit_need(cards.keys() <= new_cards.keys() and len(new_cards)-len(cards)<=1,scope,"main_addition_scope_changed")
        _audit_equal(schema,"Card",list(cards.values()),[new_cards[key] for key in cards],scope,"main_card_changed")
        for table in ("Skill","SkillEfficacy","SkillTrigger","SkillTarget"):
            a,b=old.ids(table,required=True),latest.ids(table,required=True)
            _audit_need(a.keys() <= b.keys(),scope,"main_skill_changed")
            _audit_equal(schema,table,list(a.values()),[b[key] for key in a],scope,"main_skill_changed")
            projection["retained"][table]=_audit_wire(schema,table,list(a.values()))
        characters,new_characters=old.ids("Character",required=True),latest.ids("Character",required=True)
        costumes,new_costumes=old.ids("Costume",required=True),latest.ids("Costume",required=True)
        hairs,new_hairs=old.ids("Hair",required=True),latest.ids("Hair",required=True)
        for a,b,limit in ((costumes,new_costumes,17),(hairs,new_hairs,45)):
            _audit_need(a.keys() <= b.keys() and len(b)-len(a)<=limit,scope,"main_addition_scope_changed")
        owners={row["characterId"] for row in new_cards.values()}
        _audit_need(owners <= characters.keys() and owners <= new_characters.keys(),scope,"main_reference_missing")
        for key in sorted(owners):
            a,b=characters[key],new_characters[key]
            fields=("id","assetId","characterGroupId","defaultCostumeId","defaultLiveCostumeId")
            _audit_need({name:a.get(name,"") for name in fields}=={name:b.get(name,"") for name in fields},scope,"main_model_changed")
            for field,index in (("costumeIds",new_costumes),("hairIds",new_hairs)):
                first,second=a.get(field,[]),b.get(field,[])
                _audit_need(type(first) is list and type(second) is list and set(first)<=set(second)
                            and len(second)==len(set(second)) and all(value in index and index[value].get("characterId")==key for value in second),scope,"main_membership_changed")
        for table,a,b,fields in (("Costume",costumes,new_costumes,("id","characterId","bodyAssetId","defaultHairId")),
                                  ("Hair",hairs,new_hairs,("id","characterId","hairAssetId","faceAssetId","fittingCostumeId"))):
            projection["retained"][table]={key:{field:row.get(field,"") for field in fields} for key,row in a.items()}
            _audit_need(all({field:row.get(field,"") for field in fields}=={field:b[key].get(field,"") for field in fields} for key,row in a.items()),scope,"main_model_changed")
        from .live_assets import _wearable
        for key,hair in hairs.items():
            related=[name for name,row in costumes.items() if row.get("characterId")==hair.get("characterId")]
            _audit_need(all(_wearable(hair,name)==_wearable(new_hairs[key],name) for name in related),scope,"main_membership_changed")
        for row in new_cards.values():
            for slot in range(1,5):
                identity=row.get("skillId"+str(slot),"")
                _audit_need(not identity or identity in latest.ids("Skill"),scope,"main_reference_missing")
        projection["retained"]["Card"]=_audit_wire(schema,"Card",list(cards.values()))
        return _audit_receipt(scope,schema,old,latest,projection,{"old_cards_unchanged":len(cards),
            "new_cards":len(new_cards)-len(cards),"old_costumes_preserved":len(costumes),"new_costumes":len(new_costumes)-len(costumes),
            "old_hairs_preserved":len(hairs),"new_hairs":len(new_hairs)-len(hairs),"first_quests":3,"ruleset":RULESET})
    except LatestSemanticsError: raise
    except Exception:
        raise LatestSemanticsError(scope,"input_invalid") from None
