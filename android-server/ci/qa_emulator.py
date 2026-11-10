#!/usr/bin/env python3
"""Exercise the native Android server UI and real encrypted loopback RPCs.

Only an emulator target is accepted. UI taps use fresh uiautomator node bounds;
screenshots, UI XML, logcat and a credential-free result report are retained.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import tempfile
import time
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

import grpc

from idoly_local import codec
from idoly_local.schema import Schema


PACKAGE = "game.qualiarts.idolypride.localserver"
ACTIVITY = PACKAGE + "/.MainActivity"
LOCAL_REFUND_DATE = 4102444800000  # 2100-01-01 UTC, safely convertible to JST.
PHOTO_CHARACTERS = ("char-ktn", "char-ngs", "char-mei", "char-suz", "char-ski")
STARTER_CHARACTERS = frozenset(("char-ai", "char-aoi", "char-chs", "char-hrk", "char-kkr",
    *PHOTO_CHARACTERS, "char-rei", "char-rio", "char-rui", "char-skr", "char-smr", "char-szk", "char-yu"))
PRIVATE_DATABASE = "files/data/state.db"
PRESERVED_TABLES = ("profiles", "sessions", "profile_settings")
QA_UNKNOWN_PB = b"\x80\x4b\x7b"  # Unknown response field 1200, value 123.
TUTORIAL_REPLAYS = {
    "short": (31243, "719068e48099082fad71760d65a88047182be8b858a3586f33f87b812103fba7", 158, 8813),
    "full": (32251, "29ecb24412bd6a2034a8b31803fcb34a8cd6b6632c2f0a96fe0319c15236d562", 156, 10717),
}


class QA:
    def __init__(self, adb, serial, artifacts):
        self.command = [adb, "-s", serial]
        self.artifacts = artifacts
        artifacts.mkdir(parents=True, exist_ok=True)
        self.forwarded = []

    def adb(self, *args, binary=False, check=True):
        # A cold 98 MB install may compile DEX under software CPU emulation.
        timeout = 300 if args and args[0] == "install" else 90
        result = subprocess.run([*self.command, *args], capture_output=True, text=not binary, timeout=timeout)
        if check and result.returncode:
            raise RuntimeError("adb command failed: " + " ".join(args[:3]))
        return result.stdout

    def capture(self, stage):
        raw = self.adb("exec-out", "uiautomator", "dump", "/dev/tty")
        begin, end = raw.find("<hierarchy"), raw.rfind("</hierarchy>")
        if begin < 0 or end < 0:
            raise RuntimeError("uiautomator did not return a UI hierarchy")
        xml = raw[begin:end + len("</hierarchy>")]
        (self.artifacts / (stage + ".xml")).write_text(xml, encoding="utf-8")
        (self.artifacts / (stage + ".png")).write_bytes(self.adb("exec-out", "screencap", "-p", binary=True))
        return ET.fromstring(xml)

    def tap(self, label, stage):
        for attempt in range(5):
            hierarchy = self.capture(stage + "-" + str(attempt))
            for node in hierarchy.iter("node"):
                if node.get("text") != label or node.get("enabled") != "true":
                    continue
                bounds = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", node.get("bounds", ""))
                if bounds:
                    left, top, right, bottom = map(int, bounds.groups())
                    self.adb("shell", "input", "tap", str((left + right) // 2), str((top + bottom) // 2))
                    return
            time.sleep(0.5)
        raise RuntimeError("Enabled UI button not found: " + label)

    def forward(self, device_port):
        value = self.adb("forward", "tcp:0", "tcp:" + str(device_port)).strip()
        port = int(value)
        self.forwarded.append(port)
        return port

    def close(self):
        (self.artifacts / "logcat.txt").write_text(self.adb("logcat", "-d", check=False), encoding="utf-8")
        (self.artifacts / "crash-logcat.txt").write_text(self.adb("logcat", "-b", "crash", "-d", check=False), encoding="utf-8")
        for port in self.forwarded:
            self.adb("forward", "--remove", "tcp:" + str(port), check=False)


def rpc(schema, port, method, token=None, request=None):
    if request is None:
        request = schema.request_type(method)()
    metadata = (("x-auth-token", token),) if token else ()
    with grpc.insecure_channel("127.0.0.1:" + str(port)) as channel:
        raw = channel.unary_unary(method)(codec.encode(request.SerializeToString()), metadata=metadata, timeout=2)
    return schema.response_type(method).FromString(codec.decode(raw))


def bootstrap(schema, port):
    """Follow the observed title-screen order without a prior local login."""
    check = rpc(schema, port, "/api.System/Check")
    term = rpc(schema, port, "/api.Refund/GetTerm")
    # In the client, zero refund dates mean an unbounded active refund period.
    # A future period hides that entry, while shopInvalid=0 closes the unsupported
    # financial shop. Positive shopInvalid would advertise a normal stone shop.
    actual = (term.endDatetime, term.startDatetime, term.shopInvalidStartDatetime)
    if actual != (LOCAL_REFUND_DATE, LOCAL_REFUND_DATE, 0) or term.startDatetime <= time.time() * 1000:
        raise RuntimeError("Anonymous Refund.GetTerm did not disable local refund and financial entries")
    login = rpc(schema, port, "/api.Auth/Login")
    return check, login


def wait_server(schema, port, expected=True, timeout=120):
    deadline = time.monotonic() + timeout
    next_progress = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            rpc(schema, port, "/api.System/Check")
            ready = True
        except grpc.RpcError:
            ready = False
        if ready == expected:
            return
        if time.monotonic() >= next_progress:
            print("Waiting for native server " + ("startup" if expected else "shutdown"), flush=True)
            next_progress = time.monotonic() + 15
        time.sleep(0.5)
    raise RuntimeError("Server did not " + ("start" if expected else "stop") + " before the timeout")


def assert_starter_roster(user):
    if len(user.characters) != 17 or {row.characterId for row in user.characters} != STARTER_CHARACTERS:
        raise RuntimeError("Native starter roster does not contain the 17 unconditional office characters")
    costumes = {row.costumeId for row in user.costumes}
    hairs = {row.hairId for row in user.hairs}
    for row in user.characters:
        if (not row.favoriteCostumeId or row.favoriteCostumeId not in costumes
                or not row.liveCostumeId or row.liveCostumeId not in costumes
                or not row.favoriteHairId or row.favoriteHairId not in hairs
                or not row.liveHairId or row.liveHairId not in hairs):
            raise RuntimeError("Native starter character is missing an owned favorite/live appearance")


def assert_starter_home_positions(user):
    positions = {row.homePositionType: row for row in user.homePositions}
    expected = dict(zip((1, 2, 3, 4), PHOTO_CHARACTERS[:4]))
    if (len(user.homePositions) != 4 or set(positions) != set(expected)
            or any(positions[kind].characterId != key for kind, key in expected.items())
            or any(row.isCharacterRandom or row.isCostumeRandom for row in positions.values())
            or not set(expected.values()).issubset({row.characterId for row in user.characters})):
        raise RuntimeError("Native starter home pages must contain four distinct owned fixed characters")


def _legacy_home_projection(user):
    """Normalize only the three home character IDs the version-3 repair owns."""
    projected = type(user)()
    projected.CopyFrom(user)
    for row in projected.homePositions:
        if row.homePositionType in (2, 3, 4):
            row.characterId = PHOTO_CHARACTERS[0]
    return projected


def tutorial_pending(user):
    starts = [row for row in user.tutorials if row.tutorialType == 1]
    if len(starts) > 1 or starts and starts[0].step < 0:
        raise RuntimeError("Invalid GameStart tutorial context in the tested user snapshot")
    return not starts or starts[0].step < 150


def assert_quest_catalog(top, main, master_dir, user):
    """Compare encrypted read-only responses with the actual bundled catalog."""
    master_dir = Path(master_dir)
    tables = {name: json.loads((master_dir / (name + ".json")).read_text())
              for name in ("AreaGroup", "Area", "Quest")}
    areas = {row["id"]: row for row in tables["Area"]}
    quests = {row["id"]: row for row in tables["Quest"]}
    pending = tutorial_pending(user)
    active_types = {1, 101} if pending else {1}
    tutorial_rows = [row for row in tables["Area"] if row["type"] == 101]
    if pending and (len(tutorial_rows) != 1 or tutorial_rows[0]["id"] != "area-tutorial"
                    or tutorial_rows[0].get("areaGroupId") != "area-main-group-999"
                    or tutorial_rows[0].get("questIds") != ["qt-tutorial-full", "qt-tutorial-short"]):
        raise RuntimeError("Pending GameStart needs the actual group999 tutorial full/short alternatives")
    expected = []
    for group in sorted(tables["AreaGroup"], key=lambda row: (int(row.get("order", 0)), row["id"])):
        if not any(areas[key]["type"] in active_types for key in group["areaIds"]):
            continue
        group_areas = []
        for key in group["areaIds"]:
            area = areas[key]
            if area["type"] not in active_types or area["areaGroupId"] != group["id"]:
                raise RuntimeError("Bundled main-live area does not resolve to its group")
            if any(quests[quest_id]["areaId"] != key for quest_id in area["questIds"]):
                raise RuntimeError("Bundled main-live quest does not resolve to its area")
            group_areas.append((key, list(area["questIds"])))
        expected.append((group["id"], group_areas))
    actual = [(group.areaGroupId, [(area.areaId, [row.questId for row in area.quests])
                                  for area in group.areas]) for group in top.mainAreaGroups]
    if (not expected or actual != expected or [row.SerializeToString() for row in top.mainAreaGroups]
            != [row.SerializeToString() for row in main.areaGroups]):
        raise RuntimeError("Quest.Top/ListMain groups do not match the actual bundled main-live catalog")
    tutorial_areas = [area for group in top.mainAreaGroups for area in group.areas
                      if areas[area.areaId]["type"] == 101]
    if (pending and not tutorial_areas or not pending and tutorial_areas
            or any(not area.unlocked or not area.quests or any(not row.isPlayable for row in area.quests)
                   for area in tutorial_areas)):
        raise RuntimeError("Quest.Top/ListMain omitted or misrepresented the user's tutorial context")
    if any(row.campaignDropRewardIds for group in top.mainAreaGroups for area in group.areas for row in area.quests):
        raise RuntimeError("Read-only quest catalog fabricated campaign rewards")
    first_area = next(area for group in top.mainAreaGroups for area in group.areas
                      if areas[area.areaId]["type"] == 1)
    first = first_area.quests[0]
    if not first_area.unlocked or not first.isPlayable or first.cleared:
        raise RuntimeError("Fresh main-live catalog did not expose the first uncleared playable quest")
    if (not top.HasField("pvpInfo") or top.pvpInfo.HasField("latestPvpSeason")
            or not top.HasField("hierarchyNotiInfo") or not top.hierarchyNotiInfo.currentDetailGradeId):
        raise RuntimeError("Quest.Top omitted required containers or fabricated a competitive season")
    contests = [row for row in tables["Area"] if row["type"] == 2]
    if len(contests) != 1 or contests[0]["id"] != "area-contest-001":
        raise RuntimeError("Bundled contest catalog does not contain the actual type-2 area")
    contest = contests[0]
    expected_contest = contest["questIds"]
    if (len(expected_contest) != 23 or len(set(expected_contest)) != 23
            or any(quests[key]["areaId"] != contest["id"] for key in expected_contest)
            or not top.HasField("contestArea") or top.contestArea.areaId != contest["id"]
            or top.contestArea.unlocked or [row.questId for row in top.contestArea.quests] != expected_contest
            or any(row.isPlayable or row.playableCount or row.campaignDropRewardIds for row in top.contestArea.quests)):
        raise RuntimeError("Quest.Top must expose all 23 real contest quests as locked, unplayable and without campaigns")
    return first.questId


def assert_initial_inventory(user, master_dir):
    """Check bootstrap inventory directly against public tables, not seeding code."""
    master = Path(master_dir)
    tables = {name: json.loads((master / (name + ".json")).read_text()) for name in
              ("Reward", "Item", "Card", "CardParameter", "CardRarity", "CardLevelRelease", "Skill",
               "Setting", "Character", "Costume", "Hair")}

    def one(name, predicate):
        matches = [row for row in tables[name] if predicate(row)]
        if len(matches) != 1:
            raise RuntimeError("Initial inventory needs one matching public " + name + " row")
        return matches[0]

    def indexed(name):
        values = tables[name]
        result = {row["id"]: row for row in values}
        if len(result) != len(values):
            raise RuntimeError("Initial inventory has duplicate public " + name + " identities")
        return result

    reward = one("Reward", lambda row: row.get("id") == "initial_user_reward")
    resources = reward["resources"]
    if any(row.get("resourceType") not in (1, 2, 4) for row in resources):
        raise RuntimeError("Initial reward contains unsupported resources")
    grants = {kind: [row for row in resources if row["resourceType"] == kind] for kind in (1, 2, 4)}
    card_ids = [row["resourceId"] for row in grants[2]]
    character_ids = [row["resourceId"] for row in grants[4]]
    item_amounts = {row["resourceId"]: int(row["amount"]) for row in grants[1]}
    if (len(card_ids) != 17 or len(set(card_ids)) != 17
            or len(character_ids) != 17 or len(set(character_ids)) != 17
            or len(grants[1]) != 2 or len(item_amounts) != 2
            or any(int(row["amount"]) != 1 for kind in (2, 4) for row in grants[kind])):
        raise RuntimeError("Canonical initial reward must contain 17 unique cards/characters and two items")
    cards, skills, items = indexed("Card"), indexed("Skill"), indexed("Item")
    characters, costumes, hairs = indexed("Character"), indexed("Costume"), indexed("Hair")
    if (not set(character_ids).issubset(characters) or not set(item_amounts).issubset(items)
            or not set(character_ids).issubset(row.characterId for row in user.characters)):
        raise RuntimeError("Initial reward resources do not resolve to public character/item tables")
    if (len(user.cards) != 17 or {row.cardId for row in user.cards} != set(card_ids)
            or len(user.items) != 2 or {row.itemId: row.amount for row in user.items} != item_amounts
            or any(row.expiredTime for row in user.items) or user.balance.SerializeToString()):
        raise RuntimeError("User.Get does not contain exactly the canonical initial cards/items without premium currency")
    setting = one("Setting", lambda _row: True)
    owners = set()
    for observed in user.cards:
        card = cards.get(observed.cardId)
        if card is None or card.get("characterId") not in character_ids or card["characterId"] in owners:
            raise RuntimeError("Initial cards must resolve to distinct canonical reward characters")
        owners.add(card["characterId"])
        rarity = one("CardRarity", lambda row: row.get("rarity") == card["initialRarity"])
        parameter = one("CardParameter", lambda row: row.get("id") == card["cardParameterId"] and row.get("level") == 1)
        release = one("CardLevelRelease", lambda row: row.get("id") == card["cardLevelReleaseId"] and row.get("level") == 1)
        expected = type(observed)(cardId=observed.cardId, level=1, baseLevel=1, rarity=card["initialRarity"],
                                  mental=setting["cardDefaultMental"], technique=setting["cardDefaultTechnique"], displayType=1)
        for name in ("vocal", "dance", "visual", "stamina"):
            base = int(parameter["staminaValue"] if name == "stamina" else parameter["value"])
            # Both integer floors are observable in the client parameter calculation.
            value = (base * int(card[name + "RatioPermil"]) // 1000) * int(rarity["parameterBonusPermil"]) // 1000
            setattr(expected, name, value)
            setattr(expected, "base" + name.capitalize(), value)
        targets = release["targets"]
        if any(row["type"] not in (1, 4, 7) for row in targets):
            raise RuntimeError("Initial level-one release contains unsupported skill/ability targets")
        unlocked = {row["number"] for row in targets if row["type"] == 1}
        if 1 not in unlocked or not unlocked.issubset({1, 2, 3, 4}):
            raise RuntimeError("Initial card release does not define a valid first learned skill")
        expected.photoEquipableCount = expected.basePhotoEquipableCount = sum(
            row["number"] for row in targets if row["type"] == 7)
        for position in unlocked:
            skill_id = card["skillId" + str(position)]
            skill = skills.get(skill_id)
            first = [row for row in skill.get("levels", []) if row.get("level") == 1] if skill else []
            if len(first) != 1 or int(first[0].get("requiredCardLevel", 0)) > 1:
                raise RuntimeError("Initial learned skill does not resolve to a usable first skill level")
            for prefix in ("skillId", "baseSkillId"):
                setattr(expected, prefix + str(position), skill_id)
            for prefix in ("skillLevel", "baseSkillLevel"):
                setattr(expected, prefix + str(position), 1)
        actual = type(observed)()
        actual.CopyFrom(observed)
        actual.ClearField("obtainedTime")
        if (observed.obtainedTime <= 0
                or actual.SerializeToString(deterministic=True) != expected.SerializeToString(deterministic=True)):
            raise RuntimeError("Initial UserCard fields differ from public level-one parameters/releases/skills")
    if owners != set(character_ids):
        raise RuntimeError("Initial cards do not cover the canonical reward characters")
    if (len(user.decks) != 1 or user.decks[0].number != 1 or user.user.deckSequence != 1
            or len(user.deckPositions) != 5 or {row.number for row in user.deckPositions} != {1}
            or {row.position for row in user.deckPositions} != {1, 2, 3, 4, 5}
            or len({row.cardId for row in user.deckPositions}) != 5):
        raise RuntimeError("Default unit must contain five distinct owned cards in deck-one slots 1..5")
    owned_cards = {row.cardId for row in user.cards}
    owned_costumes = {row.costumeId for row in user.costumes}
    owned_hairs = {row.hairId for row in user.hairs}
    unit_characters = set()
    for position in user.deckPositions:
        card = cards.get(position.cardId)
        owner = card.get("characterId") if card else None
        costume, hair = costumes.get(position.costumeId), hairs.get(position.hairId)
        if (position.cardId not in owned_cards or owner in unit_characters
                or position.costumeId not in owned_costumes or position.hairId not in owned_hairs
                or costume is None or hair is None
                or costume.get("characterId") != owner or hair.get("characterId") != owner
                or (hair.get("wearableCostumeIds") is not None and position.costumeId not in hair["wearableCostumeIds"])
                or position.part1AccessoryId or position.part2AccessoryId or position.photoIds):
            raise RuntimeError("Default unit has an unowned, repeated or mismatched card/appearance reference")
        unit_characters.add(owner)
    return {"initial_card_count": len(user.cards), "initial_item_count": len(user.items), "default_unit_slot_count": 5}


def load_tutorial_replay(schema, directory, kind):
    """Read the pinned, sanitized public demonstration, never a user capture."""
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text())
    size, digest, charts, score = TUTORIAL_REPLAYS[kind]
    entry = next(row for row in manifest["replays"] if row["kind"] == kind)
    expected_file = "tutorial-" + kind + ".pb"
    payload = (directory / expected_file).read_bytes()
    if (manifest.get("fixed_demo") is not True or manifest.get("schema_sha256") != schema.fingerprint
            or manifest.get("source_repository") != "Project-Hoshimi/sumire-sr-data"
            or manifest.get("source_commit") != "c40ea107b9cc8e53ae1705f82a5c39cc9fe3be02"
            or entry.get("file") != expected_file or entry.get("quest_id") != "qt-tutorial-" + kind
            or entry.get("bytes") != size or entry.get("sha256") != digest
            or len(payload) != size or hashlib.sha256(payload).hexdigest() != digest):
        raise RuntimeError("Tutorial QA needs the exact pinned sanitized public demonstration")
    canonical = schema.response_type("/api.Tutorial/StartQuest").FromString(payload)
    if (len(canonical.result.userInfos) != 1 or len(canonical.result.charts) != charts
            or canonical.result.userInfos[0].userResult.score != score
            or canonical.result.userInfos[0].userId or canonical.result.userInfos[0].name
            or canonical.result.detailLogId or canonical.result.isDisplayDetailAvailable
            or not canonical.HasField("commonResponse") or canonical.commonResponse.SerializeToString()):
        raise RuntimeError("Tutorial QA canonical record contains identity, state updates or invalid totals")
    return canonical


def tutorial_assets(canonical):
    deck = canonical.result.userInfos[0].userDeck
    assets = [(row.displayCharacterId, row.displayCostumeId, row.displayHairId) for row in deck.cards]
    assets.extend((row.characterId, row.costumeId, row.hairId) for row in deck.extraCharacterInfos)
    if len(deck.cards) != 5 or len(deck.extraCharacterInfos) != 1 or len(set(assets)) != 6:
        raise RuntimeError("Tutorial QA needs all six real recorded model appearances")
    return assets


def assert_live_assets(response, user, master_dir, deck_number=1, *, replay=None):
    """Check the native fixture's explicit owned unit against public references.

    The starter unit stores its live appearance IDs in every slot. Comparing
    those exact IDs independently also detects missing, reordered or unrelated
    assets without treating a successful preflight as a completed download.
    """
    master = Path(master_dir)
    tables = {name: json.loads((master / (name + ".json")).read_text())
              for name in ("Card", "Character", "Costume", "Hair")}
    cards, costumes, hairs = ({row["id"]: row for row in tables[name]}
                              for name in ("Card", "Costume", "Hair"))
    characters = {row["id"] for row in tables["Character"]}
    positions = sorted((row for row in user.deckPositions if row.number == deck_number),
                       key=lambda row: row.position)
    if (len([row for row in user.decks if row.number == deck_number]) != 1
            or [row.position for row in positions] != [1, 2, 3, 4, 5]):
        raise RuntimeError("ListAsset QA needs one saved five-slot unit")
    owned_cards = {row.cardId for row in user.cards}
    owned_characters = {row.characterId for row in user.characters}
    owned_costumes = {row.costumeId for row in user.costumes}
    owned_hairs = {row.hairId for row in user.hairs}
    expected = []
    for position in positions:
        card = cards.get(position.cardId)
        owner = card.get("characterId") if card else None
        costume, hair = costumes.get(position.costumeId), hairs.get(position.hairId)
        allowed = hair.get("wearableCostumeIds", []) if hair else []
        denied = hair.get("notWearableCostumeIds", []) if hair else []
        compatible = (not allowed and not denied or position.costumeId in allowed
                      or bool(denied) and position.costumeId not in denied)
        if (position.cardId not in owned_cards or owner not in owned_characters or owner not in characters
                or position.costumeId not in owned_costumes or position.hairId not in owned_hairs
                or costume is None or hair is None
                or costume.get("characterId") != owner or hair.get("characterId") != owner
                or not compatible):
            raise RuntimeError("ListAsset QA unit has an unowned or incompatible explicit appearance")
        expected.append((owner, position.costumeId, position.hairId))
    if len({row[0] for row in expected}) != 5:
        raise RuntimeError("ListAsset QA needs five distinct owned unit characters")
    if replay is not None:
        for owner, costume_id, hair_id in tutorial_assets(replay):
            costume, hair = costumes.get(costume_id), hairs.get(hair_id)
            if (owner not in characters or costume is None or hair is None
                    or costume.get("characterId") != owner or hair.get("characterId") != owner):
                raise RuntimeError("Tutorial ListAsset has an unresolved recorded appearance")
            appearance = (owner, costume_id, hair_id)
            if appearance not in expected:
                expected.append(appearance)
    exact = type(response)()
    exact.commonResponse.SetInParent()
    for owner, costume, hair in expected:
        exact.characterAssets.add(characterId=owner, costumeId=costume, hairId=hair)
    if response.SerializeToString(deterministic=True) != exact.SerializeToString(deterministic=True):
        raise RuntimeError("ListAsset must return the exact ordered owned unit and required recorded appearances without state updates")
    return len(response.characterAssets)


def assert_tutorial_replay(response, canonical, user, master_dir, kind):
    """Compare every replay value, permitting only the local display identity."""
    master = Path(master_dir)
    tables = {name: json.loads((master / (name + ".json")).read_text()) for name in
              ("Card", "Character", "Costume", "Hair", "CardParameter", "CardRarity", "Skill", "Setting", "Emblem",
               "Quest", "Area", "Music", "MusicChartPattern", "Stage", "SkillEfficacy", "SkillTrigger", "SkillTarget")}
    indexed = {name: {row["id"]: row for row in tables[name]} for name in
               ("Card", "Character", "Costume", "Hair", "Skill", "Emblem", "SkillEfficacy", "SkillTrigger", "SkillTarget")}
    setting = tables["Setting"][0]
    quest_id = setting["tutorial" + kind.capitalize() + "QuestId"]
    quests = [row for row in tables["Quest"] if row["id"] == quest_id]
    if (quest_id != "qt-tutorial-" + kind or len(quests) != 1
            or quests[0]["areaId"] not in {row["id"] for row in tables["Area"] if row["type"] == 101}
            or quests[0]["musicId"] not in {row["id"] for row in tables["Music"]}
            or quests[0]["stageId"] not in {row["id"] for row in tables["Stage"]}):
        raise RuntimeError("Tutorial replay quest, area, music or stage does not resolve to the public master")
    pattern = {row["number"]: row for row in tables["MusicChartPattern"] if row["id"] == quests[0]["musicChartPatternId"]}
    if (not pattern or any(chart.number not in pattern or chart.chartType != pattern[chart.number]["type"]
                           for chart in canonical.result.charts)):
        raise RuntimeError("Tutorial replay timeline does not match the public music chart pattern")
    for owner, costume_id, hair_id in tutorial_assets(canonical):
        hair = indexed["Hair"].get(hair_id, {})
        allowed, denied = hair.get("wearableCostumeIds", []), hair.get("notWearableCostumeIds", [])
        compatible = not allowed and not denied or costume_id in allowed or bool(denied) and costume_id not in denied
        if (owner not in indexed["Character"] or costume_id not in indexed["Costume"]
                or hair_id not in indexed["Hair"] or indexed["Costume"][costume_id]["characterId"] != owner
                or indexed["Hair"][hair_id]["characterId"] != owner or not compatible):
            raise RuntimeError("Tutorial replay has an invalid public appearance reference")
    for card in canonical.result.userInfos[0].userDeck.cards:
        public = indexed["Card"].get(card.cardId)
        if public is None or public["characterId"] != card.displayCharacterId or card.level != 1:
            raise RuntimeError("Tutorial replay card does not resolve to its level-one public master")
        parameter = [row for row in tables["CardParameter"] if row["id"] == public["cardParameterId"] and row["level"] == 1]
        rarity = [row for row in tables["CardRarity"] if row["rarity"] == card.rarity]
        if len(parameter) != 1 or len(rarity) != 1 or card.rarity != public["initialRarity"]:
            raise RuntimeError("Tutorial replay card parameters do not resolve to the public master")
        for name in ("vocal", "dance", "visual", "stamina"):
            base = int(parameter[0]["staminaValue"] if name == "stamina" else parameter[0]["value"])
            value = (base * int(public[name + "RatioPermil"]) // 1000) * int(rarity[0]["parameterBonusPermil"]) // 1000
            if getattr(card, name) != value or name == "stamina" and card.startStamina != value:
                raise RuntimeError("Tutorial replay numeric parameters differ from the public master")
        if card.mental != setting["cardDefaultMental"] or card.technique != setting["cardDefaultTechnique"]:
            raise RuntimeError("Tutorial replay mental/technique differ from the public master")
        for skill in card.skills:
            public_skill = indexed["Skill"].get(skill.skillId)
            levels = [row for row in public_skill["levels"] if row["level"] == skill.skillLevel] if public_skill else []
            if (skill.skillId not in [public.get("skillId" + str(i)) for i in (1, 2, 3, 4)]
                    or len(levels) != 1):
                raise RuntimeError("Tutorial replay skill does not resolve to the public master")
            level = levels[0]
            if level.get("triggerId") and level["triggerId"] not in indexed["SkillTrigger"]:
                raise RuntimeError("Tutorial replay skill trigger does not resolve to the public master")
            for detail in level.get("skillDetails", []):
                efficacy = indexed["SkillEfficacy"].get(detail.get("efficacyId"))
                if (efficacy is None or efficacy.get("skillTargetId") and efficacy["skillTargetId"] not in indexed["SkillTarget"]
                        or detail.get("triggerId") and detail["triggerId"] not in indexed["SkillTrigger"]):
                    raise RuntimeError("Tutorial replay skill detail does not resolve to the public master")
    expected = type(canonical)()
    expected.CopyFrom(canonical)
    info = expected.result.userInfos[0]
    info.userId, info.name = user.userPublic.publicUserId, user.user.name
    if user.user.emblemId in indexed["Emblem"]:
        info.emblemId = user.user.emblemId
    if (not info.userId or not info.name or info.emblemId not in indexed["Emblem"]
            or response.SerializeToString(deterministic=True) != expected.SerializeToString(deterministic=True)):
        raise RuntimeError("Tutorial reply differs from the original fixed demonstration beyond local display identity")
    return {"tutorial_replay_" + kind + "_charts": len(response.result.charts),
            "tutorial_replay_" + kind + "_score": response.result.userInfos[0].userResult.score}


def _without_initial_inventory(user):
    """Remove only independently verified new inventory and default unit rows."""
    projected = type(user)()
    projected.CopyFrom(user)
    for field in ("cards", "items", "deckPositions"):
        projected.ClearField(field)
    return projected


def _legacy_projection(user):
    """Remove only the 12 office actors and their unshared owned appearances."""
    projected = type(user)()
    projected.CopyFrom(user)
    kept = [row for row in user.characters if row.characterId in PHOTO_CHARACTERS]
    removed = [row for row in user.characters if row.characterId not in PHOTO_CHARACTERS]
    costume_ids = lambda rows: {key for row in rows for key in (row.favoriteCostumeId, row.liveCostumeId)}
    hair_ids = lambda rows: {key for row in rows for key in (row.favoriteHairId, row.liveHairId)}
    removed_costumes = costume_ids(removed) - costume_ids(kept)
    removed_hairs = hair_ids(removed) - hair_ids(kept)
    for name, remove in (("characters", lambda row: row.characterId not in PHOTO_CHARACTERS),
                         ("costumes", lambda row: row.costumeId in removed_costumes),
                         ("hairs", lambda row: row.hairId in removed_hairs)):
        rows = getattr(projected, name)
        for index in reversed(range(len(rows))):
            if remove(rows[index]):
                del rows[index]
    return projected


def _guard_stopped_emulator(qa):
    if (not qa.command[-1].startswith("emulator-")
            or qa.adb("shell", "getprop", "ro.kernel.qemu").strip() != "1"):
        raise RuntimeError("Private database upgrade QA accepts a disposable emulator only")
    if qa.adb("shell", "pidof", "-s", PACKAGE, check=False).strip():
        raise RuntimeError("Private database upgrade QA requires a force-stopped server process")


def _copy_private_database(qa, directory):
    _guard_stopped_emulator(qa)
    path = Path(directory) / "state.db"
    payload = qa.adb("exec-out", "run-as", PACKAGE, "cat", PRIVATE_DATABASE, binary=True)
    if not payload.startswith(b"SQLite format 3\0"):
        raise RuntimeError("Stopped emulator private database is not SQLite")
    path.write_bytes(payload)
    path.chmod(0o600)
    # A forced process exit may leave committed pages in WAL. Copy it before
    # opening SQLite so the host recovers every page; no SHM copy is needed.
    wal_present = subprocess.run([*qa.command, "shell", "run-as", PACKAGE, "test", "-s", PRIVATE_DATABASE + "-wal"],
                                 capture_output=True, timeout=90)
    if wal_present.returncode not in (0, 1):
        raise RuntimeError("Could not inspect the stopped emulator database WAL")
    if wal_present.returncode == 0:
        wal = qa.adb("exec-out", "run-as", PACKAGE, "cat", PRIVATE_DATABASE + "-wal", binary=True)
        if not wal:
            raise RuntimeError("Nonempty stopped emulator database WAL could not be copied")
        wal_path = path.with_name("state.db-wal")
        wal_path.write_bytes(wal)
        wal_path.chmod(0o600)
    return path


def _checkpoint(db):
    if db.execute("PRAGMA integrity_check").fetchone() != ("ok",):
        raise RuntimeError("Synthetic emulator database failed SQLite integrity check")
    if db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0] != 0:
        raise RuntimeError("Synthetic emulator database WAL could not be checkpointed")


def private_database_snapshot(qa):
    """Keep the complete synthetic DB only in memory and a private temp dir."""
    with tempfile.TemporaryDirectory(prefix="idoly-native-readonly-") as directory:
        path = _copy_private_database(qa, directory)
        with sqlite3.connect(path) as db:
            if db.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise RuntimeError("Synthetic emulator read-only database failed integrity check")
            return tuple(db.iterdump())


def _preserved_tables(db):
    return {name: db.execute("SELECT * FROM " + name + " ORDER BY 1").fetchall() for name in PRESERVED_TABLES}


def stage_legacy_starter(qa, schema, expected_user, *, master_dir, legacy_roster=True, inventory_only=False):
    """Recreate an old starter layout only inside this disposable emulator.

    Private DB/WAL bytes live in a TemporaryDirectory and memory, never QA
    artifacts. All identity, session, settings and other snapshot fields remain.
    """
    with tempfile.TemporaryDirectory(prefix="idoly-native-upgrade-") as directory:
        path = _copy_private_database(qa, directory)
        db = sqlite3.connect(path)
        try:
            _checkpoint(db)
            identity = db.execute("SELECT name FROM profiles").fetchall()
            snapshots = db.execute("SELECT profile,response,schema_sha256 FROM snapshots").fetchall()
            marker = db.execute("SELECT profile,version FROM starter_profiles").fetchall()
            if identity != [("sandbox",)] or len(snapshots) != 1 or marker != [("sandbox", 4)]:
                raise RuntimeError("Legacy upgrade fixture requires the fresh synthetic sandbox only")
            profile, payload, fingerprint = snapshots[0]
            if profile != "sandbox" or fingerprint != schema.fingerprint:
                raise RuntimeError("Legacy upgrade fixture does not match the tested schema")
            user = schema.response_type("/api.User/Get").FromString(payload)
            assert_starter_roster(user)
            assert_starter_home_positions(user)
            assert_initial_inventory(user, master_dir)
            if user.SerializeToString(deterministic=True) != expected_user.SerializeToString(deterministic=True):
                raise RuntimeError("Stopped synthetic snapshot differs from the tested RPC state")
            if tuple(user.profile.favoriteCharacterIds) != PHOTO_CHARACTERS:
                raise RuntimeError("Legacy upgrade fixture does not match the five photo idols")
            starts = [row for row in user.tutorials if row.tutorialType == 1]
            if len(starts) != 1 or starts[0].step not in (0, 10) or inventory_only and legacy_roster:
                raise RuntimeError("Legacy inventory fixture requires the unchanged known pre-live tutorial state")
            preserved = _preserved_tables(db)
            legacy = _without_initial_inventory(user)
            if legacy_roster:
                legacy = _legacy_projection(legacy)
            if not inventory_only:
                legacy = _legacy_home_projection(legacy)
            if legacy_roster and (len(legacy.characters) != 5
                                  or {row.characterId for row in legacy.characters} != set(PHOTO_CHARACTERS)):
                raise RuntimeError("Legacy upgrade fixture did not produce exactly five idols")
            if not inventory_only and any(row.characterId != PHOTO_CHARACTERS[0] for row in legacy.homePositions):
                raise RuntimeError("Legacy upgrade fixture did not explicitly restore all four old Kotono assignments")
            if legacy_roster:
                legacy = type(user).FromString(legacy.SerializeToString() + QA_UNKNOWN_PB)
            db.execute("UPDATE snapshots SET response=? WHERE profile=?", (legacy.SerializeToString(), profile))
            if legacy_roster:
                db.execute("DELETE FROM starter_profiles WHERE profile=?", (profile,))
            else:
                db.execute("UPDATE starter_profiles SET version=? WHERE profile=?", (3 if inventory_only else 2, profile))
            db.commit()
            if _preserved_tables(db) != preserved:
                raise RuntimeError("Legacy fixture changed preserved synthetic database rows")
            _checkpoint(db)
        finally:
            db.close()
        replacement = path.read_bytes()
        _guard_stopped_emulator(qa)
        # Host SQLite has recovered/checkpointed the complete old WAL. Remove
        # only the stopped target's stale sidecars before replacing its DB.
        qa.adb("shell", "run-as", PACKAGE, "rm", "-f", PRIVATE_DATABASE + "-wal", PRIVATE_DATABASE + "-shm")
        written = subprocess.run([*qa.command, "shell", "run-as", PACKAGE, "dd", "of=" + PRIVATE_DATABASE],
                                 input=replacement, capture_output=True, timeout=90)
        if written.returncode:
            raise RuntimeError("Could not restore the synthetic legacy database to the stopped emulator")
        if qa.adb("exec-out", "run-as", PACKAGE, "cat", PRIVATE_DATABASE, binary=True) != replacement:
            raise RuntimeError("Synthetic legacy database write verification failed")
    return legacy, preserved


def verify_upgrade_database(qa, preserved):
    with tempfile.TemporaryDirectory(prefix="idoly-native-upgrade-verify-") as directory:
        path = _copy_private_database(qa, directory)
        db = sqlite3.connect(path)
        try:
            _checkpoint(db)
            if _preserved_tables(db) != preserved:
                raise RuntimeError("Native starter upgrade changed identity, sessions or settings")
            if db.execute("SELECT profile,version FROM starter_profiles").fetchall() != [("sandbox", 4)]:
                raise RuntimeError("Native starter upgrade did not persist its migration marker")
        finally:
            db.close()


def exercise_tutorial_continuation(qa, schema, grpc_port, token, master_dir, startup_timeout, preserved):
    """Continue only after the canonical replay's stopped whole-DB check.

    The caller has finished every read-only replay assertion before this
    function starts any progression. Reuse the original local session across
    the later native process restart; issuing another login would hide a lost
    session or change the identity-preservation evidence.
    """
    from idoly_local.tutorial_qa import (assert_tutorial_continuation_snapshot,
                                       run_tutorial_continuation)

    qa.adb("shell", "am", "start", "-n", ACTIVITY)
    qa.tap("서버 시작", "17-continuation-start")
    wait_server(schema, grpc_port, timeout=startup_timeout)
    print("Continuing the tutorial through encrypted native-server RPCs", flush=True)
    receipt = run_tutorial_continuation(schema,
        lambda path, request: rpc(schema, grpc_port, path, token, request),
        master_dir, label="Android native")
    qa.capture("18-continuation-complete")
    qa.tap("서버 중지", "19-continuation-stop")
    wait_server(schema, grpc_port, expected=False, timeout=30)
    qa.adb("shell", "am", "force-stop", PACKAGE)
    verify_upgrade_database(qa, preserved)

    qa.adb("shell", "am", "start", "-n", ACTIVITY)
    qa.tap("서버 시작", "20-continuation-persistence-restart")
    wait_server(schema, grpc_port, timeout=startup_timeout)
    restored = rpc(schema, grpc_port, "/api.User/Get", token)
    assert_tutorial_continuation_snapshot(schema, restored, receipt)
    if QA_UNKNOWN_PB not in restored.SerializeToString():
        raise RuntimeError("Tutorial continuation lost the imported unknown protobuf field")
    qa.capture("21-continuation-persisted")
    qa.tap("서버 중지", "22-continuation-final-stop")
    wait_server(schema, grpc_port, expected=False, timeout=30)
    qa.adb("shell", "am", "force-stop", PACKAGE)
    verify_upgrade_database(qa, preserved)
    return {"tutorial_continuation": receipt, "tutorial_continuation_persisted": True,
            "tutorial_continuation_identity_preserved": True, "tutorial_continuation_sessions_preserved": True,
            "tutorial_continuation_settings_preserved": True, "tutorial_continuation_unknown_fields_preserved": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apk", type=Path, required=True)
    parser.add_argument("--descriptor-set", type=Path, default=Path("data/protocol/idolypride-6.1.1.pb"))
    parser.add_argument("--master-dir", type=Path, default=Path("data/master-json"))
    parser.add_argument("--public-tutorial-dir", type=Path, default=Path("data/public-tutorial"))
    parser.add_argument("--artifacts", type=Path, default=Path("data/android-server-qa"))
    parser.add_argument("--adb", default="adb")
    parser.add_argument("--serial", default="emulator-5554")
    parser.add_argument("--startup-timeout", type=float, default=600,
                        help="Seconds allowed for native Python startup, including a cold software-emulator launch")
    args = parser.parse_args()
    if args.startup_timeout <= 0:
        parser.error("--startup-timeout must be positive")
    qa = QA(args.adb, args.serial, args.artifacts)
    result = {"ok": False, "target": "Android emulator", "device_game_client_tested": False}
    try:
        if not args.serial.startswith("emulator-") or qa.adb("shell", "getprop", "ro.kernel.qemu").strip() != "1":
            raise RuntimeError("This QA driver accepts an emulator only")
        print("Installing the native server APK", flush=True)
        qa.adb("install", "-r", "-g", str(args.apk.resolve()))
        qa.adb("logcat", "-c")
        qa.adb("shell", "am", "force-stop", PACKAGE)
        qa.adb("shell", "am", "start", "-n", ACTIVITY)
        grpc_port, asset_port = qa.forward(50051), qa.forward(8080)
        schema = Schema.from_descriptor_set(args.descriptor_set)
        replays = {kind: load_tutorial_replay(schema, args.public_tutorial_dir, kind) for kind in TUTORIAL_REPLAYS}
        print("Starting the server through its native UI", flush=True)
        qa.tap("서버 시작", "01-start")
        wait_server(schema, grpc_port, timeout=args.startup_timeout)
        print("Native server ready; checking encrypted RPCs and HTTP files", flush=True)
        qa.capture("02-running")
        check, login = bootstrap(schema, grpc_port)
        result.update(anonymous_refund_term=True, refund_term_inactive=True,
                      bootstrap_rpc_order=["System.Check", "Refund.GetTerm", "Auth.Login"])
        if not login.gameAuthToken:
            raise RuntimeError("Local login did not return a session")
        user = rpc(schema, grpc_port, "/api.User/Get", login.gameAuthToken)
        if not user.HasField("user") or not user.user.name:
            raise RuntimeError("Local User.Get snapshot is absent")
        assert_starter_roster(user)
        assert_starter_home_positions(user)
        result.update(assert_initial_inventory(user, args.master_dir))
        result.update(initial_inventory_master_backed=True, default_unit_complete=True)
        result["starter_roster_complete"] = True
        result["home_positions_distinct"] = True
        quest_top = rpc(schema, grpc_port, "/api.Quest/Top", login.gameAuthToken)
        quest_main = rpc(schema, grpc_port, "/api.Quest/ListMain", login.gameAuthToken)
        result["quest_catalog_first_quest"] = assert_quest_catalog(quest_top, quest_main, args.master_dir, user)
        result.update(quest_contest_area_locked=True, quest_tutorial_context=True,
                      quest_tutorial_pending=tutorial_pending(user),
                      quest_contest_quest_count=len(quest_top.contestArea.quests),
                      quest_catalog_group_count=len(quest_top.mainAreaGroups),
                      quest_catalog_area_count=sum(len(group.areas) for group in quest_top.mainAreaGroups),
                      quest_catalog_quest_count=sum(len(area.quests) for group in quest_top.mainAreaGroups for area in group.areas))
        quest_user = rpc(schema, grpc_port, "/api.User/Get", login.gameAuthToken)
        if quest_user.SerializeToString(deterministic=True) != user.SerializeToString(deterministic=True):
            raise RuntimeError("Read-only Quest.Top/ListMain mutated the local user snapshot")
        result.update(quest_top_list_main=True, quest_catalog_readonly=True, initial_inventory_readonly=True)
        deck = next(row for row in user.decks if row.number == 1)
        if not deck.name:
            raise RuntimeError("ListAsset QA needs the saved unit's ordinary nonempty name")
        for quest_id, flag in (("qt-tutorial-full", "quest_list_asset_tutorial_full"),
                               ("qt-tutorial-short", "quest_list_asset_tutorial_short"),
                               (result["quest_catalog_first_quest"], "quest_list_asset_ordinary_buddy_name")):
            request = schema.request_type("/api.Quest/ListAsset")(
                questId=quest_id, deckNumber=deck.number, buddyDeckName=deck.name)
            assets = rpc(schema, grpc_port, "/api.Quest/ListAsset", login.gameAuthToken, request)
            kind = {"qt-tutorial-full": "full", "qt-tutorial-short": "short"}.get(quest_id)
            count = assert_live_assets(assets, user, args.master_dir, deck.number,
                                       replay=replays[kind] if kind else None)
            if kind:
                result["quest_list_asset_tutorial_" + kind + "_count"] = count
            else:
                result["quest_list_asset_count"] = count
            result[flag] = True
        result["tutorial_replay_assets_covered"] = True
        rental = schema.request_type("/api.Quest/ListAsset")(
            questId=result["quest_catalog_first_quest"], deckNumber=deck.number, buddyDeckName=deck.name)
        rental.userBuddyDeckPositions.add(position=1, cardId=user.deckPositions[0].cardId,
                                         buddyUserId="unsupported-local-rental")
        try:
            rpc(schema, grpc_port, "/api.Quest/ListAsset", login.gameAuthToken, rental)
        except grpc.RpcError as error:
            if error.code() != grpc.StatusCode.UNIMPLEMENTED:
                raise RuntimeError("ListAsset rental positions must remain explicitly unsupported") from error
        else:
            raise RuntimeError("ListAsset accepted unsupported rental positions")
        after_assets = rpc(schema, grpc_port, "/api.User/Get", login.gameAuthToken)
        if after_assets.SerializeToString(deterministic=True) != user.SerializeToString(deterministic=True):
            raise RuntimeError("Read-only Quest.ListAsset changed the whole saved user snapshot")
        result.update(quest_list_asset=True, quest_list_asset_readonly=True, quest_list_asset_rental_rejected=True)
        home_request = schema.request_type("/api.Home/Login")()
        home_request.settingInfo.soundBgm = 37
        home_request.settingInfo.soundEffect = 29
        home_request.settingInfo.soundVoice = 61
        home_request.settingInfo.frameRate = 30
        home_request.settingInfo.nightMode = True
        rpc(schema, grpc_port, "/api.Home/Login", login.gameAuthToken, home_request)
        home = rpc(schema, grpc_port, "/api.Home/Enter", login.gameAuthToken)
        if not home.currentMainAreaId:
            raise RuntimeError("Local Home.Enter did not resolve the bundled starting area")
        if not home.HasField("hierarchyNotiInfo") or not home.hierarchyNotiInfo.currentDetailGradeId:
            raise RuntimeError("Local Home.Enter did not resolve the bundled hierarchy grade")
        if home.HasField("homeFishHeavenInfo"):
            raise RuntimeError("Local Home.Enter advertised an inactive fish-heaven event and may suppress LoadingManager.Hide")
        result["home_fish_heaven_absent"] = True
        rpc(schema, grpc_port, "/api.Home/SetReview", login.gameAuthToken)
        changed = rpc(schema, grpc_port, "/api.User/Get", login.gameAuthToken)
        if not changed.user.isReviewed or changed.user.lastLoginTime <= 0:
            raise RuntimeError("Local gameplay changes were not saved")
        master = rpc(schema, grpc_port, "/api.Master/Get", login.gameAuthToken)
        if not master.masterTag.masterTagPacks:
            raise RuntimeError("Local master archive is absent")
        filename = master.masterTag.masterTagPacks[0].fileName
        from urllib.parse import quote

        request = Request("http://127.0.0.1:" + str(asset_port) + "/master/" + quote(filename, safe=""), headers={"Range": "bytes=0-31"})
        with urlopen(request, timeout=5) as response:
            if response.status != 206 or len(response.read()) != 32:
                raise RuntimeError("Local master HTTP byte range failed")
        result.update(system_check=check.keepAliveTimeMilliseconds > 0, local_auth=True, home_rpcs=True,
                      home_hierarchy_reference=True,
                      user_snapshot=True, master_packs=len(master.masterTag.masterTagPacks), asset_range=True)
        qa.tap("서버 중지", "03-stop")
        wait_server(schema, grpc_port, expected=False, timeout=30)
        qa.capture("04-stopped")
        # Stop the whole process, preserving its private DB, then exercise a
        # fresh service instance and the previously issued local session.
        qa.adb("shell", "am", "force-stop", PACKAGE)
        legacy, preserved = stage_legacy_starter(qa, schema, changed, master_dir=args.master_dir)
        qa.adb("shell", "am", "start", "-n", ACTIVITY)
        print("Restarting the app to verify the native five-to-seventeen starter upgrade", flush=True)
        qa.tap("서버 시작", "05-restart")
        wait_server(schema, grpc_port, timeout=args.startup_timeout)
        restored = rpc(schema, grpc_port, "/api.User/Get", login.gameAuthToken)
        if restored.user.name != user.user.name or not restored.user.isReviewed:
            raise RuntimeError("Restart did not preserve the local profile")
        assert_starter_roster(restored)
        assert_starter_home_positions(restored)
        assert_initial_inventory(restored, args.master_dir)
        if (_legacy_home_projection(_legacy_projection(_without_initial_inventory(restored))).SerializeToString(deterministic=True)
                != legacy.SerializeToString(deterministic=True)):
            raise RuntimeError("Native starter upgrade changed existing snapshot fields or appearance rows")
        old_home1 = next(row.SerializeToString() for row in legacy.homePositions if row.homePositionType == 1)
        if next(row.SerializeToString() for row in restored.homePositions if row.homePositionType == 1) != old_home1:
            raise RuntimeError("Native starter upgrade changed the original Home1 assignment")
        result.update(restart_session_preserved=True, gameplay_change_preserved=True, port_rebound=True)
        result.update(legacy_starter_upgraded=True, legacy_home_positions_upgraded=True,
                      upgrade_snapshot_fields_preserved=True)
        qa.capture("06-restarted")
        qa.tap("서버 중지", "07-legacy-upgrade-stop")
        wait_server(schema, grpc_port, expected=False, timeout=30)
        qa.adb("shell", "am", "force-stop", PACKAGE)
        verify_upgrade_database(qa, preserved)
        legacy_v2, preserved_v2 = stage_legacy_starter(qa, schema, restored, master_dir=args.master_dir, legacy_roster=False)
        if preserved_v2 != preserved:
            raise RuntimeError("Version-2 fixture changed original identity, sessions or settings")
        qa.adb("shell", "am", "start", "-n", ACTIVITY)
        print("Restarting the native version-2 all-Kotono starter to verify distinct home pages", flush=True)
        qa.tap("서버 시작", "08-version2-restart")
        wait_server(schema, grpc_port, timeout=args.startup_timeout)
        repaired_v2 = rpc(schema, grpc_port, "/api.User/Get", login.gameAuthToken)
        assert_starter_roster(repaired_v2)
        assert_starter_home_positions(repaired_v2)
        assert_initial_inventory(repaired_v2, args.master_dir)
        if (_legacy_home_projection(_without_initial_inventory(repaired_v2)).SerializeToString(deterministic=True)
                != legacy_v2.SerializeToString(deterministic=True)):
            raise RuntimeError("Version-2 home repair changed fields beyond the three allowed home character IDs")
        if (next(row.SerializeToString() for row in repaired_v2.homePositions if row.homePositionType == 1) != old_home1
                or QA_UNKNOWN_PB not in repaired_v2.SerializeToString()
                or [row.SerializeToString() for row in repaired_v2.tutorials]
                != [row.SerializeToString() for row in legacy_v2.tutorials]):
            raise RuntimeError("Version-2 home repair changed Home1, unknown protobuf data or tutorial progress")
        result.update(version2_home_positions_upgraded=True, upgrade_home1_preserved=True,
                      upgrade_unknown_fields_preserved=True, upgrade_tutorial_preserved=True)
        qa.capture("09-version2-restarted")
        qa.tap("서버 중지", "10-home-upgrade-stop")
        wait_server(schema, grpc_port, expected=False, timeout=30)
        qa.adb("shell", "am", "force-stop", PACKAGE)
        verify_upgrade_database(qa, preserved)
        legacy_v3, preserved_v3 = stage_legacy_starter(qa, schema, repaired_v2, master_dir=args.master_dir,
                                                     legacy_roster=False, inventory_only=True)
        if preserved_v3 != preserved:
            raise RuntimeError("Version-3 fixture changed original identity, sessions or settings")
        qa.adb("shell", "am", "start", "-n", ACTIVITY)
        print("Restarting the native version-3 empty inventory to verify its initial cards and unit", flush=True)
        qa.tap("서버 시작", "11-version3-restart")
        wait_server(schema, grpc_port, timeout=args.startup_timeout)
        repaired_v3 = rpc(schema, grpc_port, "/api.User/Get", login.gameAuthToken)
        assert_initial_inventory(repaired_v3, args.master_dir)
        if (_without_initial_inventory(repaired_v3).SerializeToString(deterministic=True)
                != legacy_v3.SerializeToString(deterministic=True)):
            raise RuntimeError("Version-3 inventory repair changed pre-existing snapshot fields")
        result["version3_inventory_upgraded"] = True
        qa.capture("12-version3-restarted")
        qa.tap("서버 중지", "13-inventory-upgrade-stop")
        wait_server(schema, grpc_port, expected=False, timeout=30)
        qa.adb("shell", "am", "force-stop", PACKAGE)
        verify_upgrade_database(qa, preserved)
        tutorial_database_before = private_database_snapshot(qa)
        qa.adb("shell", "am", "start", "-n", ACTIVITY)
        qa.tap("서버 시작", "14-inventory-persistence-restart")
        wait_server(schema, grpc_port, timeout=args.startup_timeout)
        persisted = rpc(schema, grpc_port, "/api.User/Get", login.gameAuthToken)
        if persisted.SerializeToString(deterministic=True) != repaired_v3.SerializeToString(deterministic=True):
            raise RuntimeError("Marker-4 restart changed the completed starter inventory or other snapshot fields")
        result["starter_inventory_persisted"] = True
        for kind, canonical in replays.items():
            request = schema.request_type("/api.Tutorial/StartQuest")(questId="qt-tutorial-" + kind)
            replay = rpc(schema, grpc_port, "/api.Tutorial/StartQuest", login.gameAuthToken, request)
            result.update(assert_tutorial_replay(replay, canonical, persisted, args.master_dir, kind))
            result["tutorial_replay_" + kind] = True
        after_replays = rpc(schema, grpc_port, "/api.User/Get", login.gameAuthToken)
        if after_replays.SerializeToString(deterministic=True) != persisted.SerializeToString(deterministic=True):
            raise RuntimeError("Tutorial demonstration changed the whole user snapshot")
        result.update(tutorial_replay_canonical=True, tutorial_replay_master_references=True)
        qa.capture("15-inventory-persisted")
        qa.tap("서버 중지", "16-final-stop")
        wait_server(schema, grpc_port, expected=False, timeout=30)
        qa.adb("shell", "am", "force-stop", PACKAGE)
        verify_upgrade_database(qa, preserved)
        if private_database_snapshot(qa) != tutorial_database_before:
            raise RuntimeError("Tutorial demonstration changed synthetic identity, session, settings, marker or snapshot database rows")
        result["tutorial_replay_readonly"] = True
        result.update(upgrade_identity_preserved=True, upgrade_sessions_preserved=True, upgrade_settings_preserved=True)
        result.update(exercise_tutorial_continuation(qa, schema, grpc_port, login.gameAuthToken,
                                                    args.master_dir, args.startup_timeout, preserved))
        qa.adb("shell", "am", "start", "-n", ACTIVITY)
        result.update(ok=True, final_stop=True)
    except BaseException as error:
        result["error_type"] = type(error).__name__
        result["error"] = str(error)
        raise
    finally:
        try:
            qa.capture("23-final")
        except Exception:
            pass
        qa.close()
        (args.artifacts / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
