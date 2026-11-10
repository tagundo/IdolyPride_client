"""Read-only playback of two pinned, public official tutorial performances.

These are fixed tutorial demonstrations, not simulations of a selected unit.
Their numeric/card/skill timeline is preserved. Captured identity, detail-log
handles and account updates are never returned or applied. Source provenance
and the sanitized payload hashes are independently pinned below.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from google.protobuf.message import DecodeError

from .gameplay import _Catalog
from .live_assets import _wearable
from .rpc import RpcCode, RpcFailure


_PATH = "/api.Tutorial/StartQuest"
_USER = "/api.User/Get"
_COMMIT = "c40ea107b9cc8e53ae1705f82a5c39cc9fe3be02"
_REPOSITORY = "Project-Hoshimi/sumire-sr-data"
_SCHEMA_SHA256 = "0fcf90596261dcd9bbed165bd93859dc30127e2a494e6529bafbd8885675edf3"
_SOURCES = {
    "short": {"raw_sha256": "532c199a7fe2daaeedf7ba9cb0c28a988d4dc0e549bcfd30dadcdf274d56f8ae",
              "raw_bytes": 31314, "git_blob_sha1": "2a6c581866d41c91ebc0890d19656b72ef7090ca",
              "sha256": "719068e48099082fad71760d65a88047182be8b858a3586f33f87b812103fba7",
              "bytes": 31243, "charts": 158, "score": 8813, "capture": "00026"},
    "full": {"raw_sha256": "0cd36f73aff5f733633528434a19af179797241f01195b0c4a2888d8736acd3c",
             "raw_bytes": 32321, "git_blob_sha1": "8d17c867ec2a6b30bf9a3fd938fc811f9cbeca1b",
             "sha256": "29ecb24412bd6a2034a8b31803fcb34a8cd6b6632c2f0a96fe0319c15236d562",
             "bytes": 32251, "charts": 156, "score": 10717, "capture": "00028"},
}


def _require(condition, detail):
    if not condition:
        raise ValueError("Invalid public tutorial replay: " + detail)


def _source_url(pin):
    return ("https://raw.githubusercontent.com/" + _REPOSITORY + "/" + _COMMIT
            + "/captures/2026-10-25_fresh_official/raw/" + pin["capture"]
            + ".resp-plain.Tutorial%3AStartQuest.bin")


def _settings(catalog):
    rows = catalog.rows("Setting", required=True)
    _require(len(rows) == 1, "one Setting row is required")
    result = {kind: rows[0].get("tutorial" + kind.capitalize() + "QuestId") for kind in _SOURCES}
    _require(all(isinstance(value, str) and value for value in result.values())
             and len(set(result.values())) == 2, "tutorial quest settings")
    return rows[0], result


def _unknown_and_enums(message):
    clean = type(message)()
    clean.CopyFrom(message)
    clean.DiscardUnknownFields()
    _require(clean.SerializeToString(deterministic=True) == message.SerializeToString(deterministic=True),
             "unknown protobuf fields")
    def walk(current):
        for field, value in current.ListFields():
            for item in value if field.is_repeated else (value,):
                if field.message_type:
                    walk(item)
                elif field.enum_type:
                    _require(item in field.enum_type.values_by_number, "unknown enum value")
                elif field.name in ("cardIndex", "targetCardIndex", "targetCardIndexes"):
                    _require(item in (1, 2, 3, 4, 5), "card index outside the canonical unit")
                elif field.name == "userIndex":
                    _require(item == 1, "user index outside the canonical player")
                elif field.name == "skillIndex":
                    _require(item == 1, "skill index outside the initial learned skills")
    walk(message)


def _validate_template(response, kind, quest_id, catalog, masters, setting):
    pin = _SOURCES[kind]
    _unknown_and_enums(response)
    _require(response.HasField("result"), "missing result")
    _require(response.HasField("commonResponse") and not response.commonResponse.SerializeToString(),
             "captured account updates were not removed")
    result = response.result
    _require(not result.detailLogId and not result.isDisplayDetailAvailable, "detail logging is not disabled")
    _require(len(result.userInfos) == 1, "one tutorial player is required")
    user = result.userInfos[0]
    _require(user.index == 1 and not user.isNpc and not user.userId and not user.name, "unsanitized player identity")
    _require(user.emblemId in masters["Emblem"], "unknown canonical emblem")
    _require(user.HasField("userDeck") and user.HasField("userResult"), "missing player deck or result")
    cards = list(user.userDeck.cards)
    _require([card.index for card in cards] == [1, 2, 3, 4, 5], "five ordered tutorial cards are required")
    _require(len({card.cardId for card in cards}) == 5, "duplicate tutorial cards")
    quest = masters["Quest"].get(quest_id)
    _require(quest is not None, "unknown tutorial quest")
    _require(quest.get("musicId") in masters["Music"] and quest.get("stageId") in masters["Stage"],
             "unknown tutorial music or stage")
    chart = sorted((row for row in catalog.rows("MusicChartPattern", required=True)
                    if row.get("id") == quest.get("musicChartPatternId") and row.get("type") != 0),
                   key=lambda row: row["number"])
    _require(len(chart) == pin["charts"] and len(result.charts) == pin["charts"], "chart count")
    _require([(row.number, row.chartType) for row in result.charts]
             == [(row["number"], row["type"]) for row in chart], "chart sequence differs from the master")
    _require(len({row.number for row in result.charts}) == len(result.charts), "duplicate chart numbers")
    parameters = {(row["id"], row["level"]): row for row in catalog.rows("CardParameter", required=True)}
    rarities = {row["rarity"]: row for row in catalog.rows("CardRarity", required=True)}
    assets, skill_levels = [], {}

    def asset(character_id, costume_id, hair_id):
        costume, hair = masters["Costume"].get(costume_id), masters["Hair"].get(hair_id)
        _require(character_id in masters["Character"] and costume is not None and hair is not None,
                 "unknown tutorial appearance")
        _require(costume.get("characterId") == hair.get("characterId") == character_id
                 and _wearable(hair, costume_id), "incompatible tutorial appearance")
        row = character_id, costume_id, hair_id
        if row not in assets:
            assets.append(row)

    for card in cards:
        master = masters["Card"].get(card.cardId)
        _require(master is not None and master.get("characterId") == card.displayCharacterId,
                 "unknown tutorial card or character")
        _require(card.level == 1 and card.rarity == master.get("initialRarity"), "tutorial card level or rarity")
        parameter = parameters.get((master.get("cardParameterId"), 1))
        rarity = rarities.get(card.rarity)
        _require(parameter is not None and rarity is not None, "missing tutorial parameters")
        for name in ("vocal", "dance", "visual", "stamina"):
            base = int(parameter["staminaValue" if name == "stamina" else "value"])
            expected = (base * master[name + "RatioPermil"] // 1000 * rarity["parameterBonusPermil"]) // 1000
            _require(getattr(card, name) == expected, "tutorial card parameter differs from the master")
        _require(card.mental == setting["cardDefaultMental"] and card.technique == setting["cardDefaultTechnique"],
                 "tutorial mental or technique")
        _require(0 < card.startStamina <= card.stamina and card.audienceAmount >= 0, "initial stamina or audience")
        _require((card.skillLevel1, card.skillLevel2, card.skillLevel3, card.skillLevel4) == (1, 0, 0, 0),
                 "tutorial learned skill levels")
        _require(len(card.skills) == 1 and card.skills[0].index == 1
                 and card.skills[0].skillId == master.get("skillId1") and card.skills[0].skillLevel == 1,
                 "tutorial first skill")
        skill = masters["Skill"].get(card.skills[0].skillId)
        _require(skill is not None, "unknown tutorial skill")
        levels = [level for level in skill.get("levels", []) if level.get("level") == 1]
        _require(len(levels) == 1, "missing tutorial skill level")
        level = levels[0]
        for trigger in [level.get("triggerId"), *(detail.get("triggerId") for detail in level.get("skillDetails", []))]:
            _require(not trigger or trigger in masters["SkillTrigger"], "unknown tutorial trigger")
        for detail in level.get("skillDetails", []):
            efficacy = masters["SkillEfficacy"].get(detail.get("efficacyId"))
            _require(efficacy is not None and (not efficacy.get("skillTargetId")
                     or efficacy["skillTargetId"] in masters["SkillTarget"]), "unknown tutorial efficacy or target")
        skill_levels[card.index] = level
        asset(card.displayCharacterId, card.displayCostumeId, card.displayHairId)
    _require(sum(card.audienceAmount for card in cards) == result.totalAudienceAmount, "audience total")
    _require(len(user.userDeck.extraCharacterInfos) == 1, "tutorial extra performer")
    for extra in user.userDeck.extraCharacterInfos:
        _require(extra.position == 6, "extra performer position")
        asset(extra.characterId, extra.costumeId, extra.hairId)
    _require(result.HasField("preChart"), "missing initial chart status")

    def statuses(row):
        _require(sorted(status.cardIndex for status in row.cardStatuses) == [1, 2, 3, 4, 5], "card status references")
        _require(len(row.userStatuses) == 1 and row.userStatuses[0].userIndex == 1
                 and row.userStatuses[0].totalScore >= 0, "user status references")
        _require(all(status.stamina >= 0 for status in row.cardStatuses), "negative tutorial stamina")
    statuses(result.preChart)
    last_score = result.preChart.userStatuses[0].totalScore
    _require(last_score == 0, "nonzero initial score")
    events = list(result.activatedPassiveSkills)
    events.extend(result.preChart.activatedPassiveSkills)
    if result.preChart.HasField("activatedSkill"):
        events.append(result.preChart.activatedSkill)
    for row in result.charts:
        statuses(row)
        _require(row.userStatuses[0].totalScore >= last_score, "decreasing tutorial score")
        last_score = row.userStatuses[0].totalScore
        _require(all(beat.cardIndex in skill_levels and beat.score >= 0 for beat in row.beats), "beat references")
        events.extend(row.activatedPassiveSkills)
        if row.HasField("activatedSkill"):
            events.append(row.activatedSkill)
    for event in events:
        _require(all(failure.cardIndex in skill_levels for failure in event.failures), "skill failure references")
        if event.cardIndex == 0:
            # The genuine captures record unsuccessful active-skill selection
            # as index0/skill0 plus failures (three short events, one full).
            _require(not event.activated and event.skillIndex == 0 and event.score == 0
                     and not event.details and event.failures, "failed skill-selection sentinel")
            continue
        _require(event.cardIndex in skill_levels and event.skillIndex == 1 and event.score >= 0, "skill references")
        for detail in event.details:
            _require(1 <= detail.efficacyIndex <= len(skill_levels[event.cardIndex].get("skillDetails", [])),
                     "efficacy index")
            _require(all(index in skill_levels for index in detail.targetCardIndexes)
                     and all(info.targetCardIndex in skill_levels for info in detail.targetCardInfos), "skill targets")
    score = user.userResult.score
    _require(score == pin["score"] == last_score, "final score differs from the canonical timeline")
    _require({row.cardId for row in user.userResult.cardResults} == {card.cardId for card in cards}
             and len(user.userResult.cardResults) == 5
             and sum(row.totalScore for row in user.userResult.cardResults) == score, "per-card score totals")
    _require(result.cleared == (score >= int(quest["clearScore"])), "clear threshold")
    _require(len(response.rankPatterns) == 3 and all(row.plus == 0 for row in response.rankPatterns), "rank patterns")
    _require([(row.rankType, row.thresholdScore) for row in response.rankPatterns]
             == [(3, int(quest["clearScore"]) * 12 // 10), (2, int(quest["clearScore"])), (1, 0)], "rank thresholds")
    return tuple(assets)


@dataclass(frozen=True)
class _Replay:
    kind: str
    quest_id: str
    payload: bytes
    assets: tuple
    card_ids: tuple


def _load(schema, master_dir, directory):
    directory, master_dir = Path(directory), Path(master_dir)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    _require(isinstance(manifest, dict), "manifest object")
    _require(type(manifest.get("schema")) is int and manifest["schema"] == 1
             and manifest.get("fixed_demo") is True, "manifest format")
    _require(manifest.get("schema_sha256") == schema.fingerprint == _SCHEMA_SHA256, "schema fingerprint")
    _require(manifest.get("source_repository") == _REPOSITORY and manifest.get("source_commit") == _COMMIT,
             "source revision")
    _require(isinstance(manifest.get("sanitization"), dict), "sanitization object")
    for key, expected in {"user_identity_removed": True, "detail_log_removed": True,
                          "detail_available": False, "common_response_empty": True}.items():
        _require(manifest.get("sanitization", {}).get(key) is expected, "sanitization declaration")
    catalog = _Catalog(master_dir)
    _require(manifest.get("master_version") == catalog.version() and catalog.version(), "master version")
    setting, quest_ids = _settings(catalog)
    masters = {table: catalog.ids(table, required=True) for table in
               ("Quest", "Music", "Stage", "Card", "Character", "Costume", "Hair", "Skill",
                "Emblem", "SkillEfficacy", "SkillTrigger", "SkillTarget")}
    entries = manifest.get("replays")
    _require(isinstance(entries, list) and len(entries) == 2, "two replay entries are required")
    templates, report = {}, []
    for entry in entries:
        _require(isinstance(entry, dict), "replay entry object")
        kind = entry.get("kind")
        _require(kind in _SOURCES and quest_ids[kind] not in templates, "duplicate or unknown replay kind")
        pin = _SOURCES[kind]
        _require(entry.get("quest_id") == quest_ids[kind] and entry.get("file") == "tutorial-" + kind + ".pb",
                 "replay quest or filename")
        source = entry.get("source", {})
        _require(isinstance(source, dict), "replay source object")
        _require(source.get("source_url") == _source_url(pin) and source.get("source_commit") == _COMMIT,
                 "replay source URL")
        _require(all(source.get(key) == pin[key] for key in ("raw_sha256", "raw_bytes", "git_blob_sha1")),
                 "original source digest")
        path = directory / entry["file"]
        _require(path.resolve().is_relative_to(directory.resolve()), "replay path escapes its directory")
        payload = path.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        _require(len(payload) == entry.get("bytes") == pin["bytes"]
                 and digest == entry.get("sha256") == pin["sha256"], "sanitized replay digest")
        response = schema.response_type(_PATH).FromString(payload)
        assets = _validate_template(response, kind, quest_ids[kind], catalog, masters, setting)
        templates[quest_ids[kind]] = _Replay(kind, quest_ids[kind], payload, assets,
            tuple(card.cardId for card in response.result.userInfos[0].userDeck.cards))
        report.append({"kind": kind, "quest_id": quest_ids[kind], "sha256": digest,
                       "charts": len(response.result.charts), "score": pin["score"], "appearance_count": len(assets)})
    return templates, masters["Emblem"], {"schema": 1, "schema_sha256": schema.fingerprint,
        "master_version": manifest["master_version"], "fixed_demo": True, "read_only": True,
        "replays": sorted(report, key=lambda row: row["kind"])}


def validate_replays(schema, master_dir, replay_dir):
    """Pure builder validation; returns JSON-safe metadata without identities."""
    try:
        return _load(schema, master_dir, replay_dir)[2]
    except (OSError, DecodeError, RpcFailure, KeyError, TypeError, OverflowError) as error:
        raise ValueError("Invalid public tutorial replay bundle") from error


class TutorialReplays:
    """Optional lazy provider; a missing source bundle leaves RPC unsupported."""

    def __init__(self, schema, state, profile, master_dir, directory=None):
        self.schema, self.state, self.profile = schema, state, profile
        self.master_dir = Path(master_dir) if master_dir is not None else None
        self.directory = (Path(directory) if directory is not None else
                          self.master_dir.parent / "public-tutorial" if self.master_dir is not None else None)
        self._loaded = None

    def _enabled(self):
        return self.master_dir is not None and self.directory is not None and self.directory.exists()

    def _templates(self):
        if self._loaded is None:
            try:
                self._loaded = _load(self.schema, self.master_dir, self.directory)
            except (OSError, ValueError, DecodeError, RpcFailure, KeyError, TypeError, OverflowError):
                raise RpcFailure(RpcCode.FAILED_PRECONDITION, "The public tutorial replay bundle is incompatible") from None
        return self._loaded

    def _owned(self, snapshot, replay):
        if not isinstance(snapshot, self.schema.response_type(_USER)):
            raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Tutorial snapshot uses a different schema")
        cards = {row.cardId for row in snapshot.cards}
        characters = {row.characterId for row in snapshot.characters}
        costumes = {row.costumeId for row in snapshot.costumes}
        hairs = {row.hairId for row in snapshot.hairs}
        if (not set(replay.card_ids).issubset(cards) or any(character not in characters or costume not in costumes
                or hair not in hairs for character, costume, hair in replay.assets)):
            raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Canonical tutorial performers are missing from this profile")

    def handle(self, path, plain):
        if path != _PATH or not self._enabled():
            return None
        try:
            request = self.schema.request_type(path).FromString(plain)
        except DecodeError:
            raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Malformed Tutorial.StartQuest request") from None
        templates, emblems, _ = self._templates()
        replay = templates.get(request.questId)
        if replay is None:
            raise RpcFailure(RpcCode.UNIMPLEMENTED, "Only the two canonical tutorial demonstrations are available")
        saved = self.state.snapshot(self.profile)
        if saved is None or saved[1] != self.schema.fingerprint:
            raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Tutorial profile snapshot is missing or uses a different schema")
        try:
            snapshot = self.schema.response_type(_USER).FromString(saved[0])
        except DecodeError:
            raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Tutorial profile snapshot is malformed") from None
        self._owned(snapshot, replay)
        if not snapshot.userPublic.publicUserId or not snapshot.user.name:
            raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Local tutorial identity is incomplete")
        response = self.schema.response_type(path).FromString(replay.payload)
        user = response.result.userInfos[0]
        user.userId, user.name = snapshot.userPublic.publicUserId, snapshot.user.name
        if snapshot.user.emblemId in emblems:
            user.emblemId = snapshot.user.emblemId
        return response.SerializeToString()

    def append_assets(self, result, snapshot, quest_id):
        if not self._enabled():
            return
        _, ids = _settings(_Catalog(self.master_dir))
        if quest_id not in ids.values():
            return
        replay = self._templates()[0][quest_id]
        self._owned(snapshot, replay)
        seen = {(row.characterId, row.costumeId, row.hairId) for row in result.characterAssets}
        for character, costume, hair in replay.assets:
            if (character, costume, hair) not in seen:
                result.characterAssets.add(characterId=character, costumeId=costume, hairId=hair)
                seen.add((character, costume, hair))
