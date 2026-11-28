"""Real outing scenes for the separate, explicitly selected media account.

The original Company portal gates FunctionLock53 on area-main-013. This
provider exposes original character/place joins, persists watched gaze flags,
and closes outings without inventing gifts, missions, points or photo grants.
Ordinary acquisition and reward rules remain outside this gallery provider.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
import sqlite3
from types import MappingProxyType
from typing import Mapping

from google.protobuf.message import DecodeError

from .appearance import _owned
from .gameplay import _Catalog
from .live_assets import _wearable
from .media_access import MASTER_VERSION
from .rpc import RpcCode, RpcFailure

_USER = "/api.User/Get"
_LIST = "/api.Excursion/List"
_START = "/api.Excursion/Start"
_WATCH = "/api.Excursion/SetWatchedGazeReaction"
_FINISH = "/api.Excursion/Finish"
_CHECK = "/api.Photo/CheckExcursionShooting"
_ROUTES = frozenset((_LIST, _START, _WATCH, _FINISH, _CHECK))
_AREA = "area-main-013"
# Original 6.1.1 CostumeType pack SHA-256:
# 42bca0dec00f714e5c3510066a33d465f1d1afcca035eeea9fd315e0c1aa224e.
# Android omits offline master builders; tests check this runtime tuple against
# the builder's independently audited list without importing it at runtime.
_COSTUME_TYPE_IDS = ("casl", "gene", "hruh", "idol", "idol-miku", "idol-miku-mizg", "kion", "mizg",
                     "mizg-all-ng", "mizg-water-ng", "pajm", "schl", "sd-ambassador", "sd-police", "snro",
                     "trbl", "trbl-mizg", "trng", "waso")


def _fail(reason, code=RpcCode.FAILED_PRECONDITION):
    raise RpcFailure(code, "Local media outing: " + reason)


def _identity(value):
    return isinstance(value, str) and bool(value)


def _strings(row, name):
    values = row.get(name, [])
    if (not isinstance(values, list) or any(not _identity(value) for value in values)
            or len(values) != len(set(values))):
        _fail("invalid original outfit restrictions")
    return tuple(values)


@dataclass(frozen=True)
class ExcursionPlan:
    master_version: str
    quest_ids: tuple[str, ...]
    places: Mapping[str, tuple[str, ...]]
    settings: Mapping[tuple[str, str], str]
    reactions: Mapping[tuple[str, str, int], tuple[tuple[str, ...], tuple[str, ...], tuple[int, ...]]]
    _master_dir: str | None = field(default=None, repr=False)


def prepare_excursion(master_dir):
    """Validate only public masters before an opted-in media DB is touched."""
    return _prepare_catalog(_Catalog(master_dir))


def _prepare_catalog(catalog):
    version = catalog.version()
    if version != MASTER_VERSION:
        from .latest_cohort_pins import MASTER_VERSION as latest_version
        from .public_cohort_support import require_master_cohort
        if version != latest_version:
            _fail("unsupported original master version")
        try:
            require_master_cohort(catalog.directory, "media_access")
        except (OSError, ValueError):
            _fail("the audited latest outing catalog is unavailable")
    characters = catalog.ids("Character", required=True)
    costumes = catalog.ids("Costume", required=True)
    types = {row.get("costumeTypeId") for row in costumes.values()}
    if any(not _identity(value) or value not in _COSTUME_TYPE_IDS for value in types):
        _fail("invalid original costume types")
    areas, quests = catalog.ids("Area", required=True), catalog.ids("Quest", required=True)
    area = areas.get(_AREA)
    ids = area.get("questIds") if area is not None else None
    if (area is None or area.get("type") != 1 or not isinstance(ids, list) or not ids
            or any(not _identity(key) or key not in quests or quests[key].get("areaId") != _AREA for key in ids)
            or len(ids) != len(set(ids))):
        _fail("the original outing access area is unavailable")
    places = {}
    for key, row in catalog.ids("ExcursionPlace", required=True).items():
        for field in ("name", "advAssetId", "idleCameraMotionAssetId", "backgroundAssetId", "bgmAssetId", "sceneLayoutAssetId"):
            if not _identity(row.get(field)):
                _fail("an original scene asset reference is missing")
        denied = _strings(row, "notWearableCostumeTypeIds")
        for field in ("advNotWearableCostumeTypeIds", "finishAdvNotWearableCostumeTypeIds"):
            if not set(_strings(row, field)).issubset(_COSTUME_TYPE_IDS):
                _fail("an original scene references an unknown costume type")
        if not set(denied).issubset(_COSTUME_TYPE_IDS):
            _fail("an original scene references an unknown costume type")
        places[key] = denied
    settings = {}
    for row in catalog.rows("ExcursionPlaceSetting", required=True):
        character, place = row.get("characterId"), row.get("excursionPlaceId")
        key = character, place
        if character not in characters or place not in places or key in settings:
            _fail("an original place/character reference is missing or duplicated")
        for field in ("advForceCostumeId", "forceCostumeId", "finishAdvForceCostumeId"):
            costume = costumes.get(row.get(field))
            if costume is None or costume.get("characterId") != character:
                _fail("an original forced costume has a different character")
        focal = [row.get(name) for name in ("minFocalLength", "defaultFocalLength", "maxFocalLength")]
        if (any(type(value) not in (int, float) or not math.isfinite(value) or value <= 0 for value in focal)
                or not focal[0] <= focal[1] <= focal[2]
                or type(row.get("sceneLayoutPositionIndex")) is not int or row["sceneLayoutPositionIndex"] < 0):
            _fail("an original place camera setting is malformed")
        settings[key] = row["forceCostumeId"]
    reactions = {}
    for row in catalog.rows("ExcursionGazeReaction", required=True):
        character, place, number = row.get("characterId"), row.get("excursionPlaceId"), row.get("number")
        key = character, place, number
        if ((character, place) not in settings or type(number) is not int or not 0 <= number <= 2**31-1
                or key in reactions or not _identity(row.get("motionAssetId"))):
            _fail("an original reaction reference is missing or duplicated")
        allow, deny = _strings(row, "unlockCostumeIds"), _strings(row, "unlockNotCostumeIds")
        if any(value not in costumes or costumes[value].get("characterId") != character for value in (*allow, *deny)):
            _fail("an original reaction references another character's costume")
        prerequisites = row.get("unlockGazeNumbers", [])
        if (not isinstance(prerequisites, list) or any(type(value) is not int or value <= 0 for value in prerequisites)
                or len(prerequisites) != len(set(prerequisites))):
            _fail("an original gaze dependency is malformed")
        reactions[key] = allow, deny, tuple(prerequisites)
    for character, place in settings:
        if (character, place, 0) not in reactions:
            _fail("an original scene has no idle reaction")
    for (character, place, number), (_, _, prerequisites) in reactions.items():
        if any(value == number or (character, place, value) not in reactions for value in prerequisites):
            _fail("an original gaze dependency has no reaction")
    return ExcursionPlan(version, tuple(ids), MappingProxyType(places),
                         MappingProxyType(settings), MappingProxyType(reactions),
                         str(catalog.directory) if version != MASTER_VERSION else None)


def apply_excursion_access(snapshot, plan):
    """Raise only the real media menu aggregate, with no quest result/reward."""
    if (not isinstance(plan, ExcursionPlan)
            or snapshot.DESCRIPTOR.full_name != "api.UserGetResponse" or not snapshot.HasField("user")):
        _fail("invalid media access plan or snapshot")
    if plan.master_version != MASTER_VERSION:
        from .latest_cohort_pins import MASTER_VERSION as latest_version
        if (plan.master_version != latest_version or type(plan._master_dir) is not str
                or _prepare_catalog(_Catalog(plan._master_dir)) != plan):
            _fail("invalid audited latest media access plan")
    areas = _owned(snapshot.areas, "areaId")
    target = areas.get(_AREA)
    if target is not None and target.clearQuestCount < 0:
        _fail("invalid existing outing access aggregate")
    if target is not None and target.clearQuestCount >= len(plan.quest_ids):
        return False
    if target is None:
        target = snapshot.areas.add(areaId=_AREA)
    target.clearQuestCount = len(plan.quest_ids)
    return True


class Excursions:
    def __init__(self, schema, state, profile, master_dir=None, *, media_mode=False):
        self.schema, self.state, self.profile = schema, state, profile
        self.catalog = _Catalog(master_dir)
        self.media_mode = media_mode is True
        self._plan = None

    def _prepare(self):
        if self._plan is None:
            self._plan = _prepare_catalog(self.catalog)
        return self._plan

    def _parse(self, raw):
        try:
            snapshot = self.schema.response_type(_USER).FromString(raw)
        except DecodeError:
            _fail("malformed local snapshot")
        if not snapshot.HasField("user"):
            _fail("local snapshot has no user state")
        return snapshot

    def _snapshot(self):
        value = self.state.snapshot(self.profile)
        if value is None or value[1] != self.schema.fingerprint:
            _fail("no local snapshot for this schema")
        return self._parse(value[0])

    def _place(self, snapshot, character, place=None):
        if not character or character not in self.catalog.ids("Character", required=True):
            _fail("unknown character", RpcCode.INVALID_ARGUMENT)
        if character not in _owned(snapshot.characters, "characterId"):
            _fail("character is not owned", RpcCode.PERMISSION_DENIED)
        plan = self._prepare()
        choices = sorted(location for owner, location in plan.settings if owner == character)
        if not choices:
            _fail("this character has no original outing places", RpcCode.NOT_FOUND)
        if place is not None and (not place or (character, place) not in plan.settings):
            _fail("unknown outing place for this character", RpcCode.INVALID_ARGUMENT)
        return choices

    def _style(self, snapshot, character, place, costume_id, hair_id):
        self._place(snapshot, character, place)
        if not costume_id or not hair_id:
            _fail("costume and hair are required", RpcCode.INVALID_ARGUMENT)
        costume = self.catalog.ids("Costume", required=True).get(costume_id)
        hair = self.catalog.ids("Hair", required=True).get(hair_id)
        if costume is None or hair is None or costume.get("characterId") != character or hair.get("characterId") != character:
            _fail("outfit belongs to another or unknown character", RpcCode.INVALID_ARGUMENT)
        if (costume_id not in _owned(snapshot.costumes, "costumeId")
                or hair_id not in _owned(snapshot.hairs, "hairId")):
            _fail("outfit is not owned", RpcCode.PERMISSION_DENIED)
        if not _wearable(hair, costume_id) or costume.get("costumeTypeId") in self._prepare().places[place]:
            _fail("outfit cannot be worn at this place", RpcCode.INVALID_ARGUMENT)

    def _reaction(self, character, place, number):
        if type(number) is not int or number <= 0 or (character, place, number) not in self._prepare().reactions:
            _fail("unknown watched reaction", RpcCode.INVALID_ARGUMENT)
        return self._prepare().reactions[character, place, number]

    @staticmethod
    def _watch(snapshot, result, character, place, numbers):
        existing = {}
        for row in snapshot.excursionGazeReactions:
            key = row.characterId, row.excursionPlaceId, row.gazeReactionNumber
            if not key[0] or not key[1] or key[2] <= 0 or key in existing:
                _fail("stored watched reactions are malformed")
            existing[key] = row
        changed = False
        for number in numbers:
            key = character, place, number
            row = existing.get(key)
            if row is None:
                row = snapshot.excursionGazeReactions.add(characterId=character, excursionPlaceId=place,
                                                         gazeReactionNumber=number)
                existing[key] = row
                changed = True
            # Retry ACKs retain the whole current row, including unknown fields.
            result.commonResponse.updatedData.excursionGazeReactions.add().CopyFrom(row)
        return changed

    def _session(self, db):
        db.execute("CREATE TABLE IF NOT EXISTS media_excursion_state (profile TEXT PRIMARY KEY "
                   "REFERENCES profiles(name) ON DELETE CASCADE, schema_sha256 TEXT NOT NULL, "
                   "active_character TEXT NOT NULL, active_place TEXT NOT NULL, "
                   "finished_character TEXT NOT NULL, finished_place TEXT NOT NULL, finish_request BLOB NOT NULL)")
        return db.execute("SELECT * FROM media_excursion_state WHERE profile=?", (self.profile,)).fetchone()

    def _transaction_snapshot(self, db):
        row = db.execute("SELECT response,schema_sha256 FROM snapshots WHERE profile=?", (self.profile,)).fetchone()
        if row is None or row["schema_sha256"] != self.schema.fingerprint:
            _fail("no local snapshot for this schema")
        raw = bytes(row["response"])
        return raw, self._parse(raw)

    def handle(self, path, plain):
        if (not self.media_mode or path not in _ROUTES or path not in self.schema.methods
                or self.catalog.directory is None):
            return None
        try:
            request = self.schema.request_type(path).FromString(plain)
        except DecodeError:
            _fail("malformed request", RpcCode.INVALID_ARGUMENT)
        self._prepare()
        result = self.schema.response_type(path)()
        result.commonResponse.SetInParent()
        if path == _LIST:
            result.excursionPlaceIds.extend(self._place(self._snapshot(), request.characterId))
        elif path == _CHECK:
            self._style(self._snapshot(), request.characterId, request.excursionPlaceId, request.costumeId, request.hairId)
        elif path == _WATCH:
            def update(raw):
                snapshot = self._parse(raw)
                self._place(snapshot, request.characterId, request.excursionPlaceId)
                self._reaction(request.characterId, request.excursionPlaceId, request.number)
                changed = self._watch(snapshot, result, request.characterId, request.excursionPlaceId, (request.number,))
                return snapshot.SerializeToString() if changed else raw
            try:
                self.state.mutate_snapshot(self.profile, self.schema.fingerprint, update)
            except ValueError:
                _fail("local snapshot schema cannot be changed")
        else:
            try:
                with self.state.connect() as db:
                    db.execute("BEGIN IMMEDIATE")
                    raw, snapshot = self._transaction_snapshot(db)
                    session = self._session(db)
                    if session is not None and session["schema_sha256"] != self.schema.fingerprint:
                        _fail("stored outing uses a different schema")
                    if path == _START:
                        self._place(snapshot, request.characterId, request.excursionPlaceId)
                        # Gallery visits can be reopened after the game closes;
                        # unlike a reward session they neither consume nor grant.
                        db.execute("INSERT INTO media_excursion_state VALUES (?,?,?,?,?,?,?) "
                                   "ON CONFLICT(profile) DO UPDATE SET active_character=excluded.active_character, "
                                   "active_place=excluded.active_place",
                                   (self.profile, self.schema.fingerprint, request.characterId, request.excursionPlaceId,
                                    "", "", b""))
                    else:
                        numbers = list(request.gazeReactionNumbers)
                        if len(numbers) != len(set(numbers)):
                            _fail("watched reactions must be unique", RpcCode.INVALID_ARGUMENT)
                        signature = json.dumps([sorted(numbers), request.costumeId, request.hairId],
                                               ensure_ascii=False, separators=(",", ":")).encode()
                        if session is None:
                            _fail("no outing is active")
                        character, place = session["active_character"], session["active_place"]
                        replay = not character and bytes(session["finish_request"]) == signature
                        if replay:
                            character, place = session["finished_character"], session["finished_place"]
                        if not character or not place:
                            _fail("no matching outing is active")
                        self._style(snapshot, character, place, request.costumeId, request.hairId)
                        for number in numbers:
                            allow, deny, _ = self._reaction(character, place, number)
                            if allow and request.costumeId not in allow or request.costumeId in deny:
                                _fail("reaction is unavailable for this outfit", RpcCode.INVALID_ARGUMENT)
                        changed = self._watch(snapshot, result, character, place, numbers)
                        if changed:
                            db.execute("UPDATE snapshots SET response=? WHERE profile=?",
                                       (snapshot.SerializeToString(), self.profile))
                        if not replay:
                            db.execute("UPDATE media_excursion_state SET active_character='',active_place='', "
                                       "finished_character=?,finished_place=?,finish_request=? WHERE profile=?",
                                       (character, place, signature, self.profile))
            except (ValueError, sqlite3.Error):
                _fail("local outing state is unavailable")
        return result.SerializeToString()
