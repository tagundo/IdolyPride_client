#!/usr/bin/env python3
"""Private frozen server engine controlled by the native app over JSON lines."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import signal
import socket
import sqlite3
import sys
import threading
import time

from payload import install_payload

_OUTPUT_LOCK = threading.Lock()
_TUTORIAL_PINS = {
    "short": ("719068e48099082fad71760d65a88047182be8b858a3586f33f87b812103fba7", 158, 8813),
    "full": ("29ecb24412bd6a2034a8b31803fcb34a8cd6b6632c2f0a96fe0319c15236d562", 156, 10717),
}


def emit(event: str, **values):
    with _OUTPUT_LOCK:
        print(json.dumps({"event": event, **values}, ensure_ascii=False), flush=True)


class Controller:
    def __init__(self, data_dir, server_data, profile="sandbox", emit_event=emit):
        self.data_dir, self.server_data = Path(data_dir), Path(server_data)
        self.profile, self.emit = profile, emit_event
        self.lock = threading.RLock()
        self.runtime = self.worker = None
        self.cancelled = False
        self.closed = False

    def log(self, message):
        self.emit("log", message=str(message))

    def status(self):
        with self.lock:
            runtime = self.runtime
            starting = bool(self.worker and self.worker.is_alive() and runtime is None and not self.cancelled)
            status = runtime.status() if runtime else {
                "running": False, "profile": self.profile,
                "grpc_address": "127.0.0.1:50051", "asset_url": "http://127.0.0.1:8080"}
            status = {key: value for key, value in status.items() if key != "logs"}
            status["starting"] = starting
            status["can_stop"] = runtime is not None or starting
        self.emit("status", status=status)
        return status

    def start(self):
        with self.lock:
            if self.closed or self.runtime or (self.worker and self.worker.is_alive()):
                return self.status()
            self.cancelled = False
            self.worker = threading.Thread(target=self._start, name="local-server-start", daemon=False)
            self.worker.start()
        self.status()

    def _start(self):
        runtime = None
        try:
            self.log("서버 데이터를 준비하고 있습니다.")
            install_payload(self.server_data, self.data_dir, self.log)
            from idoly_local import app_runtime
            with self.lock:
                if self.cancelled or self.closed:
                    return
            runtime = app_runtime.start(self.data_dir, profile=self.profile, log_callback=self.log)
            with self.lock:
                self.runtime = runtime
                cancelled = self.cancelled or self.closed
            if cancelled:
                self.stop()
            else:
                self.log("로컬 서버가 시작되었습니다.")
        except Exception as error:
            if runtime is not None:
                with self.lock:
                    self.runtime = runtime
                self.stop()
            self.log(f"서버 시작 실패: {type(error).__name__}: {error}")
            self.emit("error", message="서버를 시작하지 못했습니다. 데이터와 포트 사용 상태를 확인해 주세요.")
        finally:
            # This worker is about to finish; avoid reporting a stale starting state.
            with self.lock:
                self.worker = None
            self.status()

    def stop(self):
        with self.lock:
            self.cancelled = True
            runtime = self.runtime
        if runtime is not None:
            try:
                runtime.stop()
            except Exception as error:
                self.log(f"서버 중지 실패: {type(error).__name__}: {error}")
                self.emit("error", message="서버를 완전히 중지하지 못했습니다. 중지를 다시 눌러 주세요.")
            else:
                with self.lock:
                    if self.runtime is runtime:
                        self.runtime = None
                self.log("로컬 서버가 중지되었습니다.")
        return self.status()

    def close(self):
        with self.lock:
            self.closed = True
            worker = self.worker
        self.stop()
        if worker and worker is not threading.current_thread():
            worker.join(timeout=20)
        self.stop()


def _rpc(address, schema, method, request=None, token=None, *, expected_status="0"):
    """Exercise the frozen pure-Python HTTP/2 stack without importing grpcio."""
    from h2.config import H2Configuration
    from h2.connection import H2Connection
    from h2.events import DataReceived, ResponseReceived, StreamEnded, TrailersReceived
    from idoly_local import codec

    if request is None:
        request = schema.request_type(method)()
    payload = codec.encode(request.SerializeToString())
    host, port = address.rsplit(":", 1)
    client = H2Connection(H2Configuration(client_side=True, header_encoding="utf-8"))
    client.initiate_connection()
    headers = [(":method", "POST"), (":scheme", "http"), (":authority", address),
        (":path", method), ("content-type", "application/grpc+proto"), ("te", "trailers")]
    if token is not None:
        headers.append(("x-auth-token", token))
    client.send_headers(1, headers)
    client.send_data(1, b"\0" + len(payload).to_bytes(4, "big") + payload, end_stream=True)
    body, status, ended = bytearray(), None, False
    with socket.create_connection((host, int(port)), timeout=5) as stream:
        stream.sendall(client.data_to_send())
        while not ended:
            data = stream.recv(65535)
            if not data:
                raise RuntimeError("HTTP/2 RPC ended before its trailers")
            for event in client.receive_data(data):
                if isinstance(event, DataReceived):
                    body.extend(event.data)
                    client.acknowledge_received_data(event.flow_controlled_length, event.stream_id)
                elif isinstance(event, (ResponseReceived, TrailersReceived)):
                    status = dict(event.headers).get("grpc-status", status)
                elif isinstance(event, StreamEnded):
                    ended = True
            pending = client.data_to_send()
            if pending:
                stream.sendall(pending)
    if status != expected_status:
        raise RuntimeError("Local RPC returned an unexpected gRPC status: " + method)
    if expected_status != "0":
        if body:
            raise RuntimeError("Rejected local RPC unexpectedly returned a message: " + method)
        return None
    if len(body) < 5 or body[0] != 0 or int.from_bytes(body[1:5], "big") != len(body) - 5:
        raise RuntimeError("Local RPC returned an invalid gRPC response: " + method)
    return schema.response_type(method).FromString(codec.decode(bytes(body[5:])))


def _home_hierarchy_reference(home, data_dir):
    grade_id = home.hierarchyNotiInfo.currentDetailGradeId
    if not grade_id:
        return False
    master_dir = Path(data_dir) / "master-json"
    details = json.loads((master_dir / "HierarchyDetailGrade.json").read_text())
    grades = json.loads((master_dir / "HierarchyGrade.json").read_text())
    matches = [row for row in details if row.get("id") == grade_id]
    if len(matches) != 1:
        return False
    parent_id = matches[0].get("hierarchyGradeId")
    return bool(parent_id) and sum(row.get("id") == parent_id for row in grades) == 1


def _home_positions_distinct(user):
    positions = list(user.homePositions)
    assigned = {row.characterId for row in positions}
    owned = {row.characterId for row in user.characters}
    return (len(positions) == 4 and {row.homePositionType for row in positions} == {1, 2, 3, 4}
            and len(assigned) == 4 and assigned.issubset(owned)
            and all(not row.isCharacterRandom and not row.isCostumeRandom for row in positions)
            and next(row.characterId for row in positions if row.homePositionType == 1) == "char-ktn")


def _initial_inventory_reference(user, data_dir):
    """Check bootstrap inventory directly against public tables, not seeding code."""
    master = Path(data_dir) / "master-json"
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


def _quest_tutorial_pending(user):
    starts = [row for row in user.tutorials if row.tutorialType == 1]
    if len(starts) > 1 or starts and starts[0].step < 0:
        raise RuntimeError("Quest smoke check needs an unambiguous GameStart tutorial state")
    return not starts or starts[0].step < 150


def _quest_list_asset_reference(response, user, data_dir, tutorial=None):
    """Verify the seeded explicit unit against owned state and public tables.

    This smoke fixture has explicit compatible costume/hair IDs in every slot;
    sparse-deck fallback behavior is tested by the server's own request tests.
    """
    def indexed(values, key, description):
        result = {}
        for row in values:
            identity = row.get(key) if isinstance(row, dict) else getattr(row, key)
            if not isinstance(identity, str) or not identity or identity in result:
                raise RuntimeError("Live asset check needs unique " + description + " identities")
            result[identity] = row
        return result

    master = Path(data_dir) / "master-json"
    tables = {}
    for name in ("Card", "Character", "Costume", "Hair"):
        rows = json.loads((master / (name + ".json")).read_text())
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise RuntimeError("Live asset check needs a public " + name + " table")
        tables[name] = indexed(rows, "id", "public " + name)
    owned = {name: indexed(getattr(user, name), key, "owned " + name)
             for name, key in (("cards", "cardId"), ("characters", "characterId"),
                               ("costumes", "costumeId"), ("hairs", "hairId"))}
    decks = [row for row in user.decks if row.number == 1]
    positions = sorted((row for row in user.deckPositions if row.number == 1), key=lambda row: row.position)
    if (len(decks) != 1 or len(positions) != 5
            or [row.position for row in positions] != [1, 2, 3, 4, 5]):
        raise RuntimeError("Live asset check needs a complete five-slot deck one")
    expected = type(response)()
    expected.commonResponse.SetInParent()
    seen_characters = set()
    for position in positions:
        card = tables["Card"].get(position.cardId)
        character_id = card.get("characterId") if card else None
        costume = tables["Costume"].get(position.costumeId)
        hair = tables["Hair"].get(position.hairId)
        allowed = (hair.get("wearableCostumeIds") or []) if hair else []
        denied = (hair.get("notWearableCostumeIds") or []) if hair else []
        wearable = (not allowed and not denied) or position.costumeId in allowed or (
            bool(denied) and position.costumeId not in denied)
        if (position.cardId not in owned["cards"] or character_id not in owned["characters"]
                or character_id not in tables["Character"] or character_id in seen_characters
                or position.costumeId not in owned["costumes"] or position.hairId not in owned["hairs"]
                or costume is None or hair is None or costume.get("characterId") != character_id
                or hair.get("characterId") != character_id or not wearable):
            raise RuntimeError("Live asset unit has an unowned or incompatible card/character/appearance")
        seen_characters.add(character_id)
        expected.characterAssets.add(characterId=character_id, costumeId=position.costumeId, hairId=position.hairId)
    if tutorial is not None:
        seen = {(row.characterId, row.costumeId, row.hairId) for row in expected.characterAssets}
        for triple in _tutorial_appearances(tutorial):
            if triple not in seen:
                expected.characterAssets.add(characterId=triple[0], costumeId=triple[1], hairId=triple[2])
                seen.add(triple)
    if response.SerializeToString(deterministic=True) != expected.SerializeToString(deterministic=True):
        raise RuntimeError("Quest.ListAsset must return ordered owned appearances, required recorded extras and an empty common response")
    return len(expected.characterAssets)


def _tutorial_fixture(response_type, data_dir, kind):
    raw = (Path(data_dir) / "public-tutorial" / ("tutorial-" + kind + ".pb")).read_bytes()
    if hashlib.sha256(raw).hexdigest() != _TUTORIAL_PINS[kind][0]:
        raise RuntimeError("Public tutorial fixture does not match the pinned sanitized official capture")
    return response_type.FromString(raw)


def _tutorial_appearances(replay):
    if len(replay.result.userInfos) != 1:
        raise RuntimeError("Tutorial replay must retain the single captured demonstration user")
    deck = replay.result.userInfos[0].userDeck
    if ([row.index for row in deck.cards] != [1, 2, 3, 4, 5]
            or len(deck.extraCharacterInfos) != 1 or deck.extraCharacterInfos[0].position != 6):
        raise RuntimeError("Tutorial replay needs the five recorded cards and its sixth appearance")
    return [(row.displayCharacterId, row.displayCostumeId, row.displayHairId) for row in deck.cards] + [
        (row.characterId, row.costumeId, row.hairId) for row in deck.extraCharacterInfos]


def _tutorial_replay_reference(response, user, data_dir, kind):
    """Compare the complete official recording after the three local identity fields."""
    canonical = _tutorial_fixture(type(response), data_dir, kind)
    master = Path(data_dir) / "master-json"

    def rows(name):
        values = json.loads((master / (name + ".json")).read_text())
        if not isinstance(values, list) or not values or any(not isinstance(row, dict) for row in values):
            raise RuntimeError("Tutorial replay needs a public " + name + " table")
        return values

    def indexed(name):
        values = rows(name)
        result = {row.get("id"): row for row in values}
        if len(result) != len(values) or any(not isinstance(key, str) or not key for key in result):
            raise RuntimeError("Tutorial replay needs unique public " + name + " identities")
        return result

    tables = {name: indexed(name) for name in ("Quest", "Area", "Music", "Stage", "Emblem", "Card",
              "Character", "Costume", "Hair", "Skill", "SkillEfficacy", "SkillTrigger", "SkillTarget")}
    settings = rows("Setting")
    field = "tutorial" + kind.capitalize() + "QuestId"
    quest_id = settings[0].get(field) if len(settings) == 1 else None
    quest = tables["Quest"].get(quest_id)
    if (quest_id != "qt-tutorial-" + kind or quest is None
            or quest.get("areaId") not in tables["Area"]
            or tables["Area"][quest["areaId"]].get("type") != 101
            or quest.get("musicId") not in tables["Music"] or quest.get("stageId") not in tables["Stage"]):
        raise RuntimeError("Tutorial quest/music/stage does not resolve through the bundled master")
    chart_keys = {(row.get("number"), row.get("type")) for row in rows("MusicChartPattern")
                  if row.get("id") == quest.get("musicChartPatternId")}
    if not chart_keys or any((row.number, row.chartType) not in chart_keys for row in canonical.result.charts):
        raise RuntimeError("Recorded tutorial charts do not resolve through the quest music pattern")
    for character, costume, hair in _tutorial_appearances(canonical):
        costume_row, hair_row = tables["Costume"].get(costume), tables["Hair"].get(hair)
        allowed = (hair_row.get("wearableCostumeIds") or []) if hair_row else []
        denied = (hair_row.get("notWearableCostumeIds") or []) if hair_row else []
        wearable = (not allowed and not denied) or costume in allowed or (bool(denied) and costume not in denied)
        if (character not in tables["Character"] or costume_row is None or hair_row is None
                or costume_row.get("characterId") != character or hair_row.get("characterId") != character or not wearable):
            raise RuntimeError("Recorded tutorial appearance does not resolve through the bundled master")
    owned_cards = {row.cardId: row for row in user.cards}
    for card in canonical.result.userInfos[0].userDeck.cards:
        public = tables["Card"].get(card.cardId)
        if public is None or public.get("characterId") != card.displayCharacterId:
            raise RuntimeError("Recorded tutorial card does not resolve to its displayed character")
        owned_card = owned_cards.get(card.cardId)
        parameters = ("level", "rarity", "vocal", "dance", "visual", "stamina", "mental", "technique",
                      "skillLevel1", "skillLevel2", "skillLevel3", "skillLevel4")
        # smoke() has independently checked every initial UserCard against
        # public CardParameter/Rarity's two integer floors and skill releases.
        if (owned_card is None or card.startStamina != card.stamina
                or any(getattr(card, field) != getattr(owned_card, field) for field in parameters)):
            raise RuntimeError("Recorded tutorial parameters differ from the master-verified initial owned card")
        for skill in card.skills:
            public_skill = tables["Skill"].get(skill.skillId)
            levels = [row for row in public_skill.get("levels", []) if row.get("level") == skill.skillLevel] if public_skill else []
            if skill.skillId not in {public.get("skillId" + str(i)) for i in range(1, 5)} or len(levels) != 1:
                raise RuntimeError("Recorded tutorial skill does not resolve through its public card/level")
            level = levels[0]
            if level.get("triggerId") and level["triggerId"] not in tables["SkillTrigger"]:
                raise RuntimeError("Recorded tutorial skill trigger is absent from the public master")
            for detail in level.get("skillDetails", []):
                efficacy = tables["SkillEfficacy"].get(detail.get("efficacyId"))
                if (efficacy is None
                        or (efficacy.get("skillTargetId") and efficacy["skillTargetId"] not in tables["SkillTarget"])
                        or (detail.get("triggerId") and detail["triggerId"] not in tables["SkillTrigger"])):
                    raise RuntimeError("Recorded tutorial skill detail does not resolve through the public master")
    if not user.userPublic.publicUserId:
        raise RuntimeError("Tutorial replay smoke needs the local public user ID")
    expected = type(response)()
    expected.CopyFrom(canonical)
    info = expected.result.userInfos[0]
    info.userId, info.name = user.userPublic.publicUserId, user.user.name
    if user.user.emblemId in tables["Emblem"]:
        info.emblemId = user.user.emblemId
    if info.emblemId not in tables["Emblem"]:
        raise RuntimeError("Tutorial replay emblem does not resolve through the bundled master")
    if response.SerializeToString(deterministic=True) != expected.SerializeToString(deterministic=True):
        raise RuntimeError("Tutorial replay differs from the pinned official result/ranks beyond local identity")
    chart_count, score = len(response.result.charts), response.result.userInfos[0].userResult.score
    if (chart_count, score) != _TUTORIAL_PINS[kind][1:]:
        raise RuntimeError("Tutorial replay changed its official chart count or score")
    return {"tutorial_replay_" + kind + "_charts": chart_count, "tutorial_replay_" + kind + "_score": score}


def _whole_database_state(data_dir):
    """Keep a logical all-table snapshot in memory; never export account rows."""
    path = (Path(data_dir) / "state.db").resolve()
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as connection:
        return tuple(connection.iterdump())


def _preserved_database_state(data_dir):
    """Keep identity/session/settings/upgrade rows in memory during progression."""
    path = (Path(data_dir) / "state.db").resolve()
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as connection:
        return {name: connection.execute("SELECT * FROM " + name + " ORDER BY 1").fetchall()
                for name in ("profiles", "sessions", "profile_settings", "starter_profiles")}


def _quest_catalog_reference(top, main, data_dir, user):
    """Check encrypted responses against the bundled public table references."""
    if ([group.SerializeToString() for group in top.mainAreaGroups]
            != [group.SerializeToString() for group in main.areaGroups]):
        raise RuntimeError("Quest.Top and Quest.ListMain returned different main area groups")
    if (not top.HasField("pvpInfo") or top.pvpInfo.HasField("latestPvpSeason")
            or not top.HasField("hierarchyNotiInfo") or not _home_hierarchy_reference(top, data_dir)):
        raise RuntimeError("Quest.Top omitted required local PvP/hierarchy references")
    master_dir = Path(data_dir) / "master-json"

    def rows(name):
        values = json.loads((master_dir / (name + ".json")).read_text())
        identities = [row.get("id") for row in values]
        if not values or any(not isinstance(key, str) or not key for key in identities) or len(set(identities)) != len(values):
            raise RuntimeError("Quest smoke check needs unique bundled " + name + " identities")
        return {row["id"]: row for row in values}

    groups, areas, quests = rows("AreaGroup"), rows("Area"), rows("Quest")
    tutorial_pending = _quest_tutorial_pending(user)
    normal_ids = {key for key, row in areas.items() if row.get("type") == 1}
    tutorial_ids = {key for key, row in areas.items() if row.get("type") == 101}
    main_ids = normal_ids | tutorial_ids if tutorial_pending else normal_ids
    if tutorial_pending and (tutorial_ids != {"area-tutorial"}
            or areas["area-tutorial"].get("areaGroupId") != "area-main-group-999"
            or areas["area-tutorial"].get("questIds") != ["qt-tutorial-full", "qt-tutorial-short"]):
        raise RuntimeError("Pending GameStart needs the real tutorial group and full/short quest alternatives")
    ordered_groups = sorted(groups.values(), key=lambda row: (int(row.get("order", 0)), row["id"]))
    expected_groups = []
    for group in ordered_groups:
        area_ids = group.get("areaIds")
        if not isinstance(area_ids, list) or not area_ids or any(key not in areas for key in area_ids):
            raise RuntimeError("Bundled AreaGroup references an absent area")
        if any(key in main_ids for key in area_ids):
            expected_groups.append(group)
    if [group.areaGroupId for group in top.mainAreaGroups] != [group["id"] for group in expected_groups]:
        raise RuntimeError("Quest group identities/order do not match the bundled AreaGroup catalog")
    seen_areas, seen_quests = set(), set()
    for output_group, group in zip(top.mainAreaGroups, expected_groups):
        if [area.areaId for area in output_group.areas] != group["areaIds"]:
            raise RuntimeError("Quest area identities/order do not match bundled AreaGroup references")
        for output_area in output_group.areas:
            area_id = output_area.areaId
            area = areas[area_id]
            if (area_id not in main_ids or area_id in seen_areas
                    or area.get("areaGroupId") != group["id"]):
                raise RuntimeError("Quest area does not belong to its bundled main group")
            seen_areas.add(area_id)
            quest_ids = area.get("questIds")
            if not quest_ids or [quest.questId for quest in output_area.quests] != quest_ids:
                raise RuntimeError("Quest identities/order do not match bundled Area references")
            for output_quest in output_area.quests:
                quest_id = output_quest.questId
                if (quest_id in seen_quests or quest_id not in quests
                        or quests[quest_id].get("areaId") != area_id):
                    raise RuntimeError("Quest does not belong to its bundled main area")
                if output_quest.campaignDropRewardIds:
                    raise RuntimeError("Local quest catalog advertised an unsupported campaign")
                seen_quests.add(quest_id)
            if area_id in tutorial_ids and (not output_area.unlocked
                    or not all(quest.isPlayable for quest in output_area.quests)):
                raise RuntimeError("Pending tutorial full/short alternatives must be available")
    if not normal_ids or seen_areas != main_ids or not seen_quests:
        raise RuntimeError("Quest responses did not cover the bundled main catalog")
    contest_rows = [row for row in areas.values() if row.get("type") == 2]
    if len(contest_rows) != 1 or contest_rows[0]["id"] != "area-contest-001":
        raise RuntimeError("Quest.Top needs the real type-2 contest area")
    contest = contest_rows[0]
    contest_ids = contest.get("questIds")
    if (not isinstance(contest_ids, list) or len(contest_ids) != 23 or len(set(contest_ids)) != 23
            or any(key not in quests or quests[key].get("areaId") != contest["id"] for key in contest_ids)):
        raise RuntimeError("Bundled contest area must reference its 23 real quests")
    if (not top.HasField("contestArea") or top.contestArea.areaId != contest["id"]
            or [quest.questId for quest in top.contestArea.quests] != contest_ids
            or top.contestArea.unlocked
            or any(quest.isPlayable or quest.playableCount or quest.campaignDropRewardIds for quest in top.contestArea.quests)):
        raise RuntimeError("Quest.Top contest catalog must be complete, locked, unplayable and campaign-free")
    first_area = next(area for group in top.mainAreaGroups for area in group.areas if area.areaId in normal_ids)
    first_quest = first_area.quests[0]
    if not first_area.unlocked or not first_quest.isPlayable or first_quest.cleared:
        raise RuntimeError("Fresh starter's first main quest must be playable and uncleared")
    return first_quest.questId


def smoke(data_dir, server_data, report_path):
    from http.client import HTTPConnection
    from urllib.parse import quote, urlsplit
    from idoly_local import app_runtime
    from idoly_local.schema import Schema
    from idoly_local.state import State

    install_payload(server_data, data_dir)
    runtime = app_runtime.start(data_dir, grpc_port=0, asset_port=0)
    report = {"frozen_runtime": bool(getattr(sys, "frozen", False)), "server_started": False,
              "encrypted_system_check": False, "anonymous_refund_term": False, "anonymous_public_text": False,
              "local_auth": False, "home_login": False, "home_enter": False,
              "home_hierarchy_reference": False, "home_fish_heaven_absent": False,
              "starter_roster_complete": False, "home_positions_distinct": False,
              "quest_top_list_main": False, "quest_catalog_readonly": False,
              "quest_contest_area_locked": False, "quest_tutorial_context": False,
              "quest_list_asset": False, "quest_list_asset_tutorial_full": False,
              "quest_list_asset_tutorial_short": False, "quest_list_asset_ordinary_buddy_name": False,
              "quest_list_asset_rental_rejected": False, "quest_list_asset_readonly": False,
              "tutorial_replay_short": False, "tutorial_replay_full": False,
              "tutorial_replay_canonical": False, "tutorial_replay_master_references": False,
              "tutorial_replay_readonly": False, "tutorial_replay_assets_covered": False,
              "initial_inventory_master_backed": False, "default_unit_complete": False,
              "initial_inventory_readonly": False, "starter_inventory_persisted": False,
              "tutorial_continuation_persisted": False, "tutorial_continuation_identity_preserved": False,
              "tutorial_continuation_sessions_preserved": False, "tutorial_continuation_settings_preserved": False,
              "settings_persisted": False, "profile_persisted": False,
              "asset_range": False, "server_stopped": False, "game_client_tested": False}
    try:
        status = runtime.status()
        report["server_started"] = bool(status["running"])
        schema = Schema.from_descriptor_set(Path(data_dir) / "protocol/idolypride-6.1.1.pb")
        address = status["grpc_address"]
        check = _rpc(address, schema, "/api.System/Check")
        report["encrypted_system_check"] = check.keepAliveTimeMilliseconds > 0
        refund = _rpc(address, schema, "/api.Refund/GetTerm")
        report["anonymous_refund_term"] = (
            refund.endDatetime, refund.startDatetime, refund.shopInvalidStartDatetime
        ) == (4102444800000, 4102444800000, 0)
        if not report["anonymous_refund_term"]:
            raise RuntimeError("Local refund period must be inactive and the unsupported financial shop closed")
        # These title-screen calls must succeed before any local Auth.Login.
        rule_request = schema.request_type("/api.Master/Rule")(ruleType=1)
        rule = _rpc(address, schema, "/api.Master/Rule", rule_request)
        help_request = schema.request_type("/api.Master/GetHelpCategory")(helpType=1)
        help_response = _rpc(address, schema, "/api.Master/GetHelpCategory", help_request)
        report["anonymous_public_text"] = bool(rule.text and help_response.helpCategories)
        login = _rpc(address, schema, "/api.Auth/Login")
        token = login.gameAuthToken
        if not token:
            raise RuntimeError("Local Auth.Login did not issue a local session")
        report["local_auth"] = True
        before = _rpc(address, schema, "/api.User/Get", token=token)
        # HomeOfficeActors selects from the master's unlocked normal roster,
        # then requires a matching UserCharacter with owned favorite/live
        # appearances. Checking the actual RPC catches the former five-row
        # seed even if initialization and Home.Enter themselves succeed.
        required_characters = {"char-ai", "char-aoi", "char-chs", "char-hrk", "char-kkr", "char-ktn",
            "char-mei", "char-ngs", "char-rei", "char-rio", "char-rui", "char-ski", "char-skr",
            "char-smr", "char-suz", "char-szk", "char-yu"}
        characters = {row.characterId: row for row in before.characters}
        costumes = {row.costumeId for row in before.costumes if row.costumeId}
        hairs = {row.hairId for row in before.hairs if row.hairId}
        report["starter_roster_complete"] = required_characters.issubset(characters) and all(
            characters[key].favoriteCostumeId in costumes and characters[key].liveCostumeId in costumes
            and characters[key].favoriteHairId in hairs and characters[key].liveHairId in hairs
            for key in required_characters)
        if not report["starter_roster_complete"]:
            raise RuntimeError("User.Get must contain all 17 starter characters and their owned favorite/live appearances")
        report["home_positions_distinct"] = _home_positions_distinct(before)
        if not report["home_positions_distinct"]:
            raise RuntimeError("User.Get must assign four distinct owned home characters and preserve Home1 char-ktn")
        report.update(_initial_inventory_reference(before, data_dir))
        report["initial_inventory_master_backed"] = report["default_unit_complete"] = True
        saved_before_quests = State(Path(data_dir) / "state.db").snapshot("sandbox")
        top = _rpc(address, schema, "/api.Quest/Top", token=token)
        main = _rpc(address, schema, "/api.Quest/ListMain", token=token)
        report["quest_catalog_first_quest"] = _quest_catalog_reference(top, main, data_dir, before)
        report["quest_catalog_group_count"] = len(top.mainAreaGroups)
        report["quest_catalog_area_count"] = sum(len(group.areas) for group in top.mainAreaGroups)
        report["quest_catalog_quest_count"] = sum(len(area.quests) for group in top.mainAreaGroups for area in group.areas)
        report["quest_contest_quest_count"] = len(top.contestArea.quests)
        report["quest_tutorial_pending"] = _quest_tutorial_pending(before)
        report["quest_contest_area_locked"] = report["quest_tutorial_context"] = True
        report["quest_top_list_main"] = True
        after_quests = _rpc(address, schema, "/api.User/Get", token=token)
        report["quest_catalog_readonly"] = (
            State(Path(data_dir) / "state.db").snapshot("sandbox") == saved_before_quests
            and after_quests.SerializeToString() == before.SerializeToString())
        if not report["quest_catalog_readonly"]:
            raise RuntimeError("Read-only Quest.Top/ListMain changed the local snapshot")
        report["initial_inventory_readonly"] = True
        saved_before_assets = State(Path(data_dir) / "state.db").snapshot("sandbox")
        whole_before_replays = _whole_database_state(data_dir)
        deck = next(row for row in before.decks if row.number == 1)
        if not deck.name:
            raise RuntimeError("Live asset smoke needs the saved ordinary nonempty deck name")
        for quest_id, flag in (("qt-tutorial-full", "quest_list_asset_tutorial_full"),
                               ("qt-tutorial-short", "quest_list_asset_tutorial_short"),
                               (report["quest_catalog_first_quest"], "quest_list_asset_ordinary_buddy_name")):
            request = schema.request_type("/api.Quest/ListAsset")(
                questId=quest_id, deckNumber=1, buddyDeckName=deck.name)
            assets = _rpc(address, schema, "/api.Quest/ListAsset", request, token)
            kind = quest_id.removeprefix("qt-tutorial-") if quest_id.startswith("qt-tutorial-") else None
            canonical = _tutorial_fixture(schema.response_type("/api.Tutorial/StartQuest"), data_dir, kind) if kind else None
            count = _quest_list_asset_reference(assets, before, data_dir, canonical)
            report["quest_list_asset_tutorial_" + kind + "_count" if kind else "quest_list_asset_count"] = count
            report[flag] = True
        if (report["quest_list_asset_tutorial_short_count"], report["quest_list_asset_tutorial_full_count"]) != (8, 9):
            raise RuntimeError("Tutorial ListAsset did not include the selected unit plus the six recorded appearances")
        report["tutorial_replay_assets_covered"] = True
        rental = schema.request_type("/api.Quest/ListAsset")(
            questId=report["quest_catalog_first_quest"], deckNumber=1, buddyDeckName=deck.name)
        position = next(row for row in before.deckPositions if row.number == 1 and row.position == 1)
        rental.userBuddyDeckPositions.add(position=1, cardId=position.cardId,
            costumeId=position.costumeId, hairId=position.hairId, buddyUserId="unsupported-local-rental")
        _rpc(address, schema, "/api.Quest/ListAsset", rental, token, expected_status="12")
        report["quest_list_asset_rental_rejected"] = True
        settings = json.loads((Path(data_dir) / "master-json/Setting.json").read_text())
        if len(settings) != 1:
            raise RuntimeError("Tutorial replay smoke needs the single public Setting row")
        for kind in ("short", "full"):
            request = schema.request_type("/api.Tutorial/StartQuest")(
                questId=settings[0]["tutorial" + kind.capitalize() + "QuestId"])
            replay = _rpc(address, schema, "/api.Tutorial/StartQuest", request, token)
            report.update(_tutorial_replay_reference(replay, before, data_dir, kind))
            report["tutorial_replay_" + kind] = True
        report["tutorial_replay_canonical"] = report["tutorial_replay_master_references"] = True
        after_assets = _rpc(address, schema, "/api.User/Get", token=token)
        report["quest_list_asset_readonly"] = (
            State(Path(data_dir) / "state.db").snapshot("sandbox") == saved_before_assets
            and after_assets.SerializeToString(deterministic=True) == before.SerializeToString(deterministic=True))
        report["tutorial_replay_readonly"] = report["quest_list_asset_readonly"] and (
            _whole_database_state(data_dir) == whole_before_replays)
        if not report["tutorial_replay_readonly"]:
            raise RuntimeError("Tutorial/asset replay requests changed the local snapshot or another database table")
        report["quest_list_asset"] = True
        home_request = schema.request_type("/api.Home/Login")()
        home_request.settingInfo.soundBgm = 37
        home_request.settingInfo.soundEffect = 29
        home_request.settingInfo.soundVoice = 61
        home_request.settingInfo.frameRate = 30
        home_request.settingInfo.nightMode = True
        expected_settings = home_request.settingInfo.SerializeToString()
        home_login = _rpc(address, schema, "/api.Home/Login", home_request, token)
        report["home_login"] = home_login.HasField("commonResponse")
        home = _rpc(address, schema, "/api.Home/Enter", token=token)
        report["home_enter"] = bool(home.currentMainAreaId and home.HasField("lessonProgress"))
        report["home_fish_heaven_absent"] = not home.HasField("homeFishHeavenInfo")
        if not report["home_fish_heaven_absent"]:
            raise RuntimeError("Home.Enter advertised an inactive fish-heaven event and may suppress LoadingManager.Hide")
        report["home_hierarchy_reference"] = _home_hierarchy_reference(home, data_dir)
        if not report["home_hierarchy_reference"]:
            raise RuntimeError("Home.Enter hierarchy grade does not resolve through the bundled master tables")
        _rpc(address, schema, "/api.Home/SetReview", token=token)
        changed = _rpc(address, schema, "/api.User/Get", token=token)
        if changed.user.name != before.user.name or not changed.user.isReviewed or changed.user.lastLoginTime <= 0:
            raise RuntimeError("Home calls did not preserve and update the local user")
        # All canonical replay and whole-database read-only assertions above
        # have completed before the following intentional gameplay mutations.
        from idoly_local.tutorial_qa import (assert_tutorial_continuation_snapshot,
                                           run_tutorial_continuation)
        preserved = _preserved_database_state(data_dir)
        continuation = run_tutorial_continuation(schema,
            lambda path, request: _rpc(address, schema, path, request, token),
            Path(data_dir) / "master-json", label="macOS frozen")
        report["tutorial_continuation"] = continuation
        changed = _rpc(address, schema, "/api.User/Get", token=token)
        saved_user = changed.SerializeToString()
        tag = json.loads((Path(data_dir) / "original-master/master-tag.json").read_text())
        filename = tag["masterTagPacks"][0]["fileName"]
        expected = (Path(data_dir) / "original-master/assets/master" / filename).read_bytes()[:64]
        url = urlsplit(status["asset_url"])
        connection = HTTPConnection(url.hostname, url.port, timeout=5)
        try:
            connection.request("GET", "/master/" + quote(filename, safe=""), headers={"Range": "bytes=0-63"})
            result = connection.getresponse()
            report["asset_range"] = result.status == 206 and result.read() == expected
        finally:
            connection.close()
        runtime.stop()
        # Reopen both listeners and SQLite state, then reuse the previous local
        # session to prove mutations survived a fresh runtime instance.
        runtime = app_runtime.start(data_dir, grpc_port=0, asset_port=0)
        restored = _rpc(runtime.status()["grpc_address"], schema, "/api.User/Get", token=token)
        assert_tutorial_continuation_snapshot(schema, restored, continuation)
        if _preserved_database_state(data_dir) != preserved:
            raise RuntimeError("Tutorial continuation changed identity, sessions, settings or the starter marker")
        report.update(tutorial_continuation_persisted=True, tutorial_continuation_identity_preserved=True,
                      tutorial_continuation_sessions_preserved=True, tutorial_continuation_settings_preserved=True)
        report["profile_persisted"] = restored.SerializeToString() == saved_user
        report["starter_inventory_persisted"] = report["profile_persisted"]
        settings = State(Path(data_dir) / "state.db").settings("sandbox")
        report["settings_persisted"] = settings == (expected_settings, schema.fingerprint)
    finally:
        runtime.stop()
        report["server_stopped"] = runtime.status()["running"] is False
    report_path = Path(report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    required = ("server_started", "encrypted_system_check", "anonymous_refund_term", "anonymous_public_text", "local_auth", "home_login",
                "home_enter", "home_hierarchy_reference", "home_fish_heaven_absent", "starter_roster_complete", "home_positions_distinct",
                "quest_top_list_main", "quest_catalog_readonly", "quest_contest_area_locked", "quest_tutorial_context",
                "quest_list_asset", "quest_list_asset_tutorial_full", "quest_list_asset_tutorial_short",
                "quest_list_asset_ordinary_buddy_name", "quest_list_asset_rental_rejected", "quest_list_asset_readonly",
                "tutorial_replay_short", "tutorial_replay_full", "tutorial_replay_canonical",
                "tutorial_replay_master_references", "tutorial_replay_readonly", "tutorial_replay_assets_covered",
                "initial_inventory_master_backed", "default_unit_complete", "initial_inventory_readonly", "starter_inventory_persisted",
                "tutorial_continuation_persisted", "tutorial_continuation_identity_preserved",
                "tutorial_continuation_sessions_preserved", "tutorial_continuation_settings_preserved",
                "settings_persisted", "profile_persisted", "asset_range", "server_stopped")
    if not all(report[key] for key in required):
        raise RuntimeError("Bundled engine smoke check failed")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--server-data", required=True, type=Path)
    parser.add_argument("--json-control", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    if args.smoke:
        if args.report is None:
            parser.error("--smoke requires --report")
        smoke(args.data_dir, args.server_data, args.report)
        return 0
    controller = Controller(args.data_dir, args.server_data)

    def stop_signal(_signum, _frame):
        controller.close()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop_signal)
    signal.signal(signal.SIGINT, stop_signal)
    controller.status()
    try:
        for line in sys.stdin:
            try:
                command = json.loads(line)
            except (ValueError, TypeError):
                emit("error", message="앱 제어 요청을 읽지 못했습니다.")
                continue
            action = command.get("action") if isinstance(command, dict) else None
            if action == "start":
                controller.start()
            elif action == "stop":
                controller.stop()
            elif action == "status":
                controller.status()
            elif action == "quit":
                break
            else:
                emit("error", message="지원하지 않는 앱 제어 요청입니다.")
    finally:
        controller.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
