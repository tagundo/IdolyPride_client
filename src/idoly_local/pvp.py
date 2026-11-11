"""Private, captured VENUS season reads; no matchmaking or battle settlement.

VENUS season/quest/opponent definitions are dynamic API data, not Master.Quest.
Only a complete, pinned capture belonging to this same local account is used.
The catalog is private user data and must never be included in app payloads.
"""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import re
import time

from google.protobuf.message import DecodeError

from .gameplay import _Catalog
from .live_assets import _wearable, project_saved_deck_assets
from .rpc import RpcCode, RpcFailure

_TOP = "/api.Pvp/Top"
_OPPONENTS = "/api.Pvp/ListOpponent"
_ASSET = "/api.Pvp/ListAsset"
_USER = "/api.User/Get"
_MASTER = "/api.Master/Get"
_QUEST = "/api.Quest/Top"
_READS = {_TOP, _OPPONENTS, _ASSET}
_RECORDS = _READS | {_USER, _MASTER, _QUEST}
_AREA = "area-main-011"
_MAX_CATALOG = 32 * 1024 * 1024
_MAX_RECORD = 16 * 1024 * 1024
_HASH = re.compile(r"[0-9a-f]{64}\Z")


def _fail(reason):
    # Fixed reasons only: private paths, identifiers and native details never
    # become logs through the transport's error reporting.
    raise RpcFailure(RpcCode.FAILED_PRECONDITION, "VENUS capture unavailable: " + reason)


def _now_ms():
    return time.time_ns() // 1000000


def _need(value, reason="catalog_invalid"):
    if not value:
        _fail(reason)


def _owner(snapshot):
    _need(snapshot.HasField("user") and snapshot.HasField("userPublic"), "owner_missing")
    pair = (snapshot.userPublic.serverUserId, snapshot.userPublic.publicUserId)
    _need(all(isinstance(value, str) and 0 < len(value) <= 256 for value in pair), "owner_missing")
    return pair


def _bytes(value, digest):
    _need(type(value) is str and type(digest) is str and _HASH.fullmatch(digest))
    _need(len(value) <= ((_MAX_RECORD + 2) // 3) * 4)
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, TypeError):
        _fail("catalog_invalid")
    _need(len(raw) <= _MAX_RECORD and base64.b64encode(raw).decode() == value)
    _need(hashlib.sha256(raw).hexdigest() == digest, "source_pin_mismatch")
    return raw


def _known_enums(message):
    for field, value in message.ListFields():
        for item in value if field.is_repeated else (value,):
            if field.message_type is not None:
                _known_enums(item)
            elif field.enum_type is not None:
                _need(item in field.enum_type.values_by_number)


class Pvp:
    def __init__(self, schema, state, profile, master_dir, *, catalog_path=None):
        self.schema, self.state, self.profile = schema, state, profile
        self.catalog = _Catalog(master_dir)
        self.catalog_path = (Path(catalog_path) if catalog_path is not None else
                             Path(master_dir).parent / "pvp-catalog.json" if master_dir is not None else None)

    def _snapshot(self):
        saved = self.state.snapshot(self.profile)
        _need(saved is not None and saved[1] == self.schema.fingerprint, "snapshot_incompatible")
        try:
            return self.schema.response_type(_USER).FromString(saved[0])
        except (DecodeError, ValueError, TypeError):
            _fail("snapshot_incompatible")

    def _gate(self, snapshot):
        area = self.catalog.ids("Area", required=True).get(_AREA)
        _need(area is not None and isinstance(area.get("questIds"), list)
              and area["questIds"] and all(type(value) is str and value for value in area["questIds"])
              and len(set(area["questIds"])) == len(area["questIds"]), "unlock_definition_missing")
        quests = self.catalog.ids("Quest", required=True)
        _need(all(identity in quests and quests[identity].get("areaId") == _AREA
                  for identity in area["questIds"]), "unlock_definition_missing")
        rows = [row for row in snapshot.areas if row.areaId == _AREA]
        _need(len(rows) == 1 and rows[0].clearQuestCount == len(area["questIds"])
              and rows[0].lastClearedTime > 0, "locked")
        progress = {}
        for row in snapshot.quests:
            _need(row.questId not in progress, "snapshot_incompatible")
            progress[row.questId] = row.lastClearedTime
        _need(all(progress.get(identity, 0) > 0 for identity in area["questIds"]), "locked")

    def _assets_valid(self, assets, opponent):
        _need(len(assets) == 5, "opponent_appearance_missing")
        cards = self.catalog.ids("Card", required=True)
        characters = self.catalog.ids("Character", required=True)
        costumes = self.catalog.ids("Costume", required=True)
        hairs = self.catalog.ids("Hair", required=True)
        ordered = sorted(opponent.cardInfos, key=lambda row: row.position)
        for row, card in zip(assets, ordered):
            costume, hair = costumes.get(row.costumeId), hairs.get(row.hairId)
            _need(cards[card.cardId].get("characterId") == row.characterId
                  and row.characterId in characters and costume is not None and hair is not None
                  and costume.get("characterId") == row.characterId
                  and hair.get("characterId") == row.characterId
                  and _wearable(hair, row.costumeId), "opponent_appearance_invalid")

    def _quest_valid(self, quest):
        _need(bool(quest.id) and quest.maxCapacity > 0 and quest.mentalThreshold > 0, "battle_definition_missing")
        for table, field in (("Stage", "stageId"), ("Music", "musicId"),
                             ("MusicChartPattern", "musicChartPatternId"), ("QuestPressure", "questPressureId"),
                             ("QuestAudienceAdvantage", "QuestAudienceAdvantageId")):
            identity = getattr(quest, field)
            rows = self.catalog.rows(table, required=True)
            _need(bool(identity) and any(row.get("id") == identity for row in rows), "battle_master_missing")
        for table, field in (("QuestCharacterAdvantage", "QuestCharacterAdvantageId"),
                             ("LiveBonusGroup", "liveBonusGroupId")):
            identity = getattr(quest, field)
            if identity:
                key = "groupId" if table == "LiveBonusGroup" else "id"
                _need(any(row.get(key) == identity for row in self.catalog.rows(table, required=True)), "battle_master_missing")
        _need(all(getattr(quest, field.name) >= 0 for field in quest.DESCRIPTOR.fields
                  if field.type in (field.TYPE_INT32, field.TYPE_INT64)), "battle_definition_invalid")
        _known_enums(quest)

    def _load(self, snapshot):
        try:
            self._gate(snapshot)
            owner = _owner(snapshot)
            profile = self.state.profile(self.profile)
            _need(profile is not None and (profile["server_id"], profile["public_id"]) == owner,
                  "owner_mismatch")
            _need(self.catalog_path is not None and self.catalog_path.is_file(), "catalog_missing")
            with self.catalog_path.open("rb") as stream:
                raw = stream.read(_MAX_CATALOG + 1)
            _need(len(raw) <= _MAX_CATALOG)
            data = json.loads(raw)
            _need(isinstance(data, dict) and type(data.get("schema")) is int and data["schema"] == 1)
            _need(data.get("schema_sha256") == self.schema.fingerprint, "schema_mismatch")
            _need(bool(self.catalog.version()) and data.get("master_version") == self.catalog.version(), "master_mismatch")
            _need(data.get("owner") == {"server_user_id": owner[0], "public_user_id": owner[1]}, "owner_mismatch")
            captured = data.get("captured_at_ms")
            now = _now_ms()
            _need(type(captured) is int and 0 < captured <= now, "capture_time_invalid")
            records = data.get("responses")
            _need(isinstance(records, list) and 5 <= len(records) <= 256)
            parsed, seen = {}, set()
            for record in records:
                _need(isinstance(record, dict) and record.get("method") in _RECORDS)
                path = record["method"]
                request_raw = _bytes(record.get("request_b64"), record.get("request_sha256"))
                response_raw = _bytes(record.get("response_b64"), record.get("response_sha256"))
                request = self.schema.request_type(path).FromString(request_raw)
                response = self.schema.response_type(path).FromString(response_raw)
                if path in {_USER, _MASTER, _TOP, _QUEST}:
                    _need(request_raw == b"")
                    key = path
                else:
                    _need(bool(request.pvpSeasonId))
                    key = (path, request.opponentId) if path == _ASSET else path
                _need(key not in seen, "duplicate_source")
                seen.add(key)
                parsed[key] = (request, response)
            _need(all(path in parsed for path in (_USER, _MASTER, _QUEST, _TOP)), "definition_missing")
            _need(_owner(parsed[_USER][1]) == owner, "owner_mismatch")
            master = parsed[_MASTER][1]
            _need(master.HasField("masterTag") and master.masterTag.version == data["master_version"], "master_mismatch")
            packs = master.masterTag.masterTagPacks
            _need(bool(packs) and len({row.type for row in packs}) == len(packs)
                  and len({row.fileName for row in packs}) == len(packs)
                  and all(row.type and row.fileName and row.fileSize > 0 and row.cryptoKey
                          and row.downloadUrl.startswith("https://climaster.game-idolypride.jp/")
                          for row in packs), "master_mismatch")
            top = parsed[_TOP][1]
            _need(top.HasField("topResult") and top.topResult.HasField("pvpSeason")
                  and top.topResult.HasField("pvpQuest") and top.topResult.HasField("userPvpSeason"), "definition_missing")
            result, season = top.topResult, top.topResult.pvpSeason
            _need(bool(season.id) and 0 < season.startTime <= captured <= now <= season.endTime
                  and season.endTime <= season.aggregateEndTime
                  and season.endTime < season.nextStartTime, "season_inactive")
            _need(season.challengeCount >= 0 and result.rank >= 0 and result.pvpTicketAvailableAmount >= 0
                  and result.userPvpSeason.point >= 0 and result.userPvpSeason.challengeCount >= 0)
            self._quest_valid(result.pvpQuest)
            header = parsed[_QUEST][1]
            _need(header.HasField("pvpInfo") and header.pvpInfo.HasField("latestPvpSeason"), "season_header_missing")
            hs = header.pvpInfo.latestPvpSeason
            _need(all(getattr(hs, key) == getattr(season, key) for key in
                      ("id", "name", "startTime", "endTime", "aggregateEndTime", "challengeCount", "nextStartTime")), "season_mismatch")
            _need(header.pvpInfo.rank >= 0 and 0 <= header.pvpInfo.remainingChallengeCount <= season.challengeCount)
            rewards = self.catalog.ids("Reward", required=bool(result.pvpRewards))
            for reward in result.pvpRewards:
                _need(0 <= reward.rankFrom and reward.hierarchyVariablePoint >= 0)
                _need(all(not identity or identity in rewards for identity in
                          (reward.rankingRewardId, reward.challengeRewardId)), "reward_definition_missing")
            _need(len({row.opponentId for row in top.opponentInfos}) == len(top.opponentInfos), "duplicate_source")
            opponents = list(top.opponentInfos)
            if _OPPONENTS in parsed:
                request, response = parsed[_OPPONENTS]
                _need(request.pvpSeasonId == season.id, "season_mismatch")
                _need(len({row.opponentId for row in response.opponentInfos}) == len(response.opponentInfos), "duplicate_source")
                opponents += list(response.opponentInfos)
            _need(bool(top.opponentInfos), "opponent_definition_missing")
            cards = self.catalog.ids("Card", required=True)
            by_id = {}
            for opponent in opponents:
                _need(bool(opponent.opponentId) and opponent.point >= 0 and opponent.rank >= 0
                      and opponent.managerLevel > 0 and len(opponent.cardInfos) == 5, "opponent_definition_invalid")
                _need(sorted(row.position for row in opponent.cardInfos) == [1, 2, 3, 4, 5])
                _need(len({row.cardId for row in opponent.cardInfos}) == 5, "opponent_definition_invalid")
                _need(all(row.cardId in cards and row.level > 0 and row.rarity > 0 and row.evolutionLevel >= 0
                          and min(row.lightFanAmount, row.middleFanAmount, row.heavyFanAmount) >= 0
                          for row in opponent.cardInfos), "opponent_definition_invalid")
                prior = by_id.get(opponent.opponentId)
                _need(prior is None or prior.SerializeToString() == opponent.SerializeToString(), "opponent_source_mismatch")
                by_id[opponent.opponentId] = opponent
            appearances = {}
            for identity in by_id:
                _need((_ASSET, identity) in parsed, "opponent_appearance_missing")
                request, response = parsed[(_ASSET, identity)]
                _need(request.pvpSeasonId == season.id and request.deckNumber > 0, "season_mismatch")
                self._assets_valid(response.opponentCharacterAssets, by_id[identity])
                appearances[identity] = response
            _need(all(not isinstance(key, tuple) or key[1] in by_id for key in parsed), "opponent_source_mismatch")
            return top, parsed.get(_OPPONENTS, (None, None))[1], header.pvpInfo, appearances
        except RpcFailure:
            raise
        except (OSError, ValueError, TypeError, KeyError, AttributeError, DecodeError, RecursionError):
            _fail("catalog_invalid")

    def quest_top_info(self, snapshot):
        """Optional menu header. An absent/closed/private-mismatched catalog hides it."""
        try:
            _top, _opponents, header, _assets = self._load(snapshot)
            result = self.schema.response_type(_QUEST)().pvpInfo
            result.CopyFrom(header)
            return result
        except RpcFailure:
            return None

    def handle(self, path, plain):
        if path not in _READS:
            return None
        try:
            request = self.schema.request_type(path).FromString(plain)
        except (DecodeError, ValueError, TypeError):
            raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Malformed VENUS read request") from None
        snapshot = self._snapshot()
        top, captured_opponents, _header, assets = self._load(snapshot)
        result = self.schema.response_type(path)()
        if path == _TOP:
            result.CopyFrom(top)
        else:
            if request.pvpSeasonId != top.topResult.pvpSeason.id:
                raise RpcFailure(RpcCode.INVALID_ARGUMENT, "VENUS season does not match the private capture")
            if path == _OPPONENTS:
                if captured_opponents is not None:
                    result.CopyFrom(captured_opponents)
                else:
                    result.opponentInfos.extend(top.opponentInfos)
            else:
                if request.opponentId not in assets:
                    raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Unknown captured VENUS opponent")
                own = project_saved_deck_assets(self.schema, snapshot, request.deckNumber, self.catalog)
                result.CopyFrom(assets[request.opponentId])
                del result.characterAssets[:]
                result.characterAssets.extend(own.characterAssets)
        # A captured read can contain official lazy-initialization deltas. They
        # are never applied to this local account or replayed into its cache.
        result.ClearField("commonResponse")
        result.commonResponse.SetInParent()
        return result.SerializeToString()
