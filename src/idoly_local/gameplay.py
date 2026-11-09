"""Persistent local home and tutorial actions for the recovered 6.1.1 schema.

Evidence: api/home.proto, api/tutorial.proto, api/common_response.proto and the
matching master JSON tables. The 6.1.1 iOS UserTutorialCollection.IsFinished at
0x1e0d274 completes GameStart at step 150. TimeManager's 0x1d29230 uses Unix
milliseconds. No battle results, automatic rewards or event progress are faked.
"""
from __future__ import annotations

import json
from pathlib import Path
import time

from google.protobuf.message import DecodeError

from .rpc import RpcCode, RpcFailure


_USER_GET = "/api.User/Get"
_GAME_START = 1
_START_STEPS = {0, 10, 100, 110, 120, 130, 140, 150}
_START_FINISHED = 150
_DAY_MS = 86400000
_JST_MS = 9 * 3600000
_ROUTES = {
    "/api.Home/Login", "/api.Home/Enter", "/api.Home/SetReview",
    "/api.Home/SetCharacterPosition", "/api.Dokan/List", "/api.Notice/List",
    "/api.Master/GetVersion", "/api.Tutorial/Init", "/api.Tutorial/Progress",
    "/api.Tutorial/Skip",
}


def _now_ms() -> int:
    return time.time_ns() // 1000000


class _Catalog:
    def __init__(self, directory: Path | None):
        self.directory = Path(directory) if directory is not None else None
        self.loaded = {}

    def rows(self, table: str, *, required: bool = False) -> list[dict]:
        if table not in self.loaded:
            source = self.directory / (table + ".json") if self.directory is not None else None
            if source is None or not source.is_file():
                self.loaded[table] = []
            else:
                try:
                    rows = json.loads(source.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Invalid local master table: " + table) from None
                if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                    raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Invalid local master table: " + table)
                self.loaded[table] = rows
        rows = self.loaded[table]
        if required and not rows:
            raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Missing local master table: " + table)
        return rows

    def ids(self, table: str, *, required: bool = False) -> dict[str, dict]:
        rows = self.rows(table, required=required)
        result = {}
        for row in rows:
            key = row.get("id")
            if not isinstance(key, str) or not key or key in result:
                raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Invalid local master identities: " + table)
            result[key] = row
        return result

    def main_areas(self) -> list[dict]:
        rows = self.ids("Area").values()
        if any(type(row.get("order", 0)) is not int for row in rows):
            raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Invalid local master ordering: Area")
        return sorted((row for row in rows if row.get("type") == 1),
                      key=lambda row: (row.get("order", 0), row["id"]))

    def version(self) -> str | None:
        if self.directory is None:
            return None
        source = self.directory / "!version.txt"
        if not source.is_file():
            return None
        value = source.read_text(encoding="utf-8").strip()
        return value or None


class Gameplay:
    """Handle an explicit local feature allowlist; other methods return None."""

    def __init__(self, schema, state, profile: str, master_dir: Path | None = None):
        self.schema, self.state, self.profile = schema, state, profile
        self.catalog = _Catalog(master_dir)

    def _parse_user(self, payload: bytes):
        try:
            user = self.schema.response_type(_USER_GET).FromString(payload)
        except DecodeError:
            raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Local profile snapshot is malformed") from None
        if not user.HasField("user"):
            raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Local profile has no user state")
        return user

    def _snapshot(self):
        snapshot = self.state.snapshot(self.profile)
        if snapshot is None:
            raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Local profile has no snapshot")
        payload, fingerprint = snapshot
        if fingerprint != self.schema.fingerprint:
            raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Local profile snapshot uses a different schema")
        return self._parse_user(payload)

    @staticmethod
    def _common(result, snapshot=None, fields=()):
        common = result.commonResponse
        common.SetInParent()
        if snapshot is None:
            return
        updated = common.updatedData
        for name in fields:
            field = updated.DESCRIPTOR.fields_by_name.get(name)
            if field is None:
                continue
            target, source = getattr(updated, name), getattr(snapshot, name)
            if field.is_repeated:
                target.extend(source)
            else:
                target.CopyFrom(source)

    def _mutate(self, result, change, *, setting_info: bytes | None = None):
        def update(payload):
            snapshot = self._parse_user(payload)
            fields = change(snapshot)
            self._common(result, snapshot, fields)
            return snapshot.SerializeToString()

        try:
            self.state.mutate_snapshot(self.profile, self.schema.fingerprint, update, setting_info=setting_info)
        except ValueError:
            raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Local profile cannot be updated with this schema") from None

    @staticmethod
    def _tutorial(snapshot, kind: int):
        for entry in snapshot.tutorials:
            if entry.tutorialType == kind:
                return entry
        return snapshot.tutorials.add(tutorialType=kind)

    def _progress_steps(self, kind: int) -> set[int] | None:
        for row in self.catalog.rows("Tutorial"):
            if row.get("type") == kind:
                steps = {entry["step"] for entry in row.get("stepInfo", [])
                         if isinstance(entry, dict) and type(entry.get("step")) is int}
                return steps | {0}
        return _START_STEPS if kind == _GAME_START else None

    def _current_area(self, snapshot) -> str:
        areas = self.catalog.main_areas()
        if not areas:
            # UserArea rows do not carry an AreaType. Their first entry may
            # be a contest/daily area, so the master owns main-area selection.
            raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Home.Enter needs the local Area master catalog")
        progress = {entry.areaId: entry for entry in snapshot.areas}
        current = areas[0]["id"]
        for index, area in enumerate(areas):
            row = progress.get(area["id"])
            if row is None or not (row.clearQuestCount or row.lastClearedTime):
                continue
            current = area["id"]
            if area.get("questIds") and row.clearQuestCount >= len(area["questIds"]):
                current = areas[min(index + 1, len(areas) - 1)]["id"]
        return current

    def handle(self, path: str, request_bytes: bytes) -> bytes | None:
        if path not in _ROUTES:
            return None
        try:
            request = self.schema.request_type(path).FromString(request_bytes)
        except DecodeError:
            raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Malformed gameplay protobuf request") from None
        result = self.schema.response_type(path)()

        if path == "/api.Master/GetVersion":
            version = self.catalog.version()
            if version is None:
                return None
            result.version = version
        elif path in ("/api.Dokan/List", "/api.Notice/List"):
            # These are explicit empty local catalogs, with no external events,
            # announcements, pagination cursor or account-side mutation.
            self._common(result)
        elif path == "/api.Home/Login":
            settings = request.settingInfo.SerializeToString() if request.HasField("settingInfo") else None
            now = _now_ms()

            def login(snapshot):
                old = snapshot.user.lastLoginTime
                if old <= 0 or (old + _JST_MS) // _DAY_MS < (now + _JST_MS) // _DAY_MS:
                    snapshot.totalCount.loginCount += 1
                snapshot.user.lastLoginTime = max(old, now)
                if not snapshot.user.gameStartTime:
                    snapshot.user.gameStartTime = now
                return ("user", "totalCount")

            self._mutate(result, login, setting_info=settings)
            result.paidJpy.SetInParent()
        elif path == "/api.Home/Enter":
            snapshot = self._snapshot()
            result.currentMainAreaId = self._current_area(snapshot)
            # Presence is deliberate for the client's home/activity container
            # reads. Pending rewards/events remain absent, not fabricated.
            for field in ("fanEventInfo", "promotionInfo", "refreshInfo", "bannerInfo", "eventInfo",
                          "pvpInfo", "hierarchyNotiInfo", "notiStoneShopItem", "notiNormalShopItem",
                          "notiShowcaseShopItem", "leagueInfo", "loveInfo", "companyInfo", "homeFishHeavenInfo"):
                if field in result.DESCRIPTOR.fields_by_name:
                    getattr(result, field).SetInParent()
            result.lessonProgress.currentAreaId = result.currentMainAreaId
            result.lessonProgress.lastReceiveTime = _now_ms()
            result.lessonProgress.maxRewardTime = result.lessonProgress.lastReceiveTime
            if "lessonInfo" in result.DESCRIPTOR.fields_by_name:
                result.lessonInfo.lessonProgress.CopyFrom(result.lessonProgress)
            self._common(result)
        elif path == "/api.Home/SetReview":
            def review(snapshot):
                snapshot.user.isReviewed = True
                return ("user",)

            self._mutate(result, review)
        elif path == "/api.Home/SetCharacterPosition":
            field = request.DESCRIPTOR.fields_by_name["positions"].message_type.fields_by_name["type"]
            kinds = {value.number for value in field.enum_type.values} - {0}
            requested = list(request.positions)
            if len({entry.type for entry in requested}) != len(requested) or any(entry.type not in kinds for entry in requested):
                raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Home positions require distinct supported types")

            def positions(snapshot):
                owned = {entry.characterId for entry in snapshot.characters}
                for position in requested:
                    if ((position.characterId and position.characterId not in owned)
                            or (not position.characterId and not position.isCharacterRandom)):
                        raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Home position character must be owned")
                for position in requested:
                    target = next((entry for entry in snapshot.homePositions if entry.homePositionType == position.type), None)
                    if target is None:
                        target = snapshot.homePositions.add(homePositionType=position.type)
                    target.characterId = position.characterId
                    target.isCharacterRandom = position.isCharacterRandom
                    target.isCostumeRandom = position.isCostumeRandom
                return ("homePositions",)

            self._mutate(result, positions)
        elif path == "/api.Tutorial/Init":
            if not request.name.strip():
                raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Tutorial name must not be empty")

            def initialize(snapshot):
                snapshot.user.name = request.name
                target = self._tutorial(snapshot, _GAME_START)
                target.step = max(target.step, 10)
                return ("user", "tutorials")

            self._mutate(result, initialize)
        elif path == "/api.Tutorial/Progress":
            enum = request.DESCRIPTOR.fields_by_name["type"].enum_type
            if request.type == 0 or request.type not in {value.number for value in enum.values}:
                raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Unknown tutorial type")
            steps = self._progress_steps(request.type)
            if steps is None:
                raise RpcFailure(RpcCode.UNIMPLEMENTED, "Tutorial progression requires its local master definition")
            if request.step not in steps:
                raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Tutorial step is not in the local master definition")

            def progress(snapshot):
                target = self._tutorial(snapshot, request.type)
                target.step = max(target.step, request.step)
                if request.type == _GAME_START and target.step >= _START_FINISHED and not snapshot.user.tutorialClearedTime:
                    snapshot.user.tutorialClearedTime = _now_ms()
                return ("tutorials", "user")

            self._mutate(result, progress)
        elif path == "/api.Tutorial/Skip":
            def skip(snapshot):
                target = self._tutorial(snapshot, _GAME_START)
                target.step = max(target.step, _START_FINISHED)
                if not snapshot.user.tutorialClearedTime:
                    snapshot.user.tutorialClearedTime = _now_ms()
                return ("tutorials", "user")

            self._mutate(result, skip)
        return result.SerializeToString()


def seed_starter_profile(state, schema, profile: str, master_dir: Path, *, manager_name: str = "Local Manager") -> bytes:
    """Create a new, master-backed tutorial-start snapshot, never an import.

    This grants the five tutorial shooting characters' default appearances and
    one empty deck. It grants no cards, currencies, battle clears or rewards.
    Catalog validation finishes before any profile snapshot is written.
    """
    if state.snapshot(profile) is not None:
        raise RpcFailure(RpcCode.ALREADY_EXISTS, "Starter seeding requires a profile without a snapshot")
    if not isinstance(manager_name, str) or not manager_name.strip():
        raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Starter manager name must not be empty")
    catalog = _Catalog(master_dir)
    settings = catalog.rows("Setting", required=True)
    if len(settings) != 1:
        raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Starter seeding needs one Setting master row")
    ids = settings[0].get("tutorialPhotoShootingCharacterIds")
    if (not isinstance(ids, list) or not ids or any(not isinstance(key, str) for key in ids)
            or len(set(ids)) != len(ids)):
        raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Starter character identities are missing from Setting")
    characters = catalog.ids("Character", required=True)
    costumes = catalog.ids("Costume", required=True)
    hairs = catalog.ids("Hair", required=True)
    areas = catalog.main_areas()
    quests = catalog.ids("Quest", required=True)
    if not areas or not areas[0].get("questIds") or any(key not in quests or quests[key].get("areaId") != areas[0]["id"] for key in areas[0]["questIds"]):
        raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Starter main area and quest identities do not match")
    stamina_rows = catalog.rows("CharacterActivityLevel", required=True)
    stamina = next((row.get("maxStamina") for row in stamina_rows if row.get("level") == 1), None)
    if type(stamina) is not int or stamina < 0:
        raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Starter activity stamina is missing from master")
    now = _now_ms()
    snapshot = schema.response_type(_USER_GET)()
    # UserGet singleton models exist even when a local collection is empty.
    for field in snapshot.DESCRIPTOR.fields:
        if field.message_type is not None and not field.is_repeated:
            getattr(snapshot, field.name).SetInParent()
    snapshot.user.name = manager_name
    snapshot.user.managerLevel = 1
    snapshot.user.gameStartTime = now
    snapshot.user.deckSequence = 1
    snapshot.decks.add(number=1, name="Local deck")
    owned_costumes, owned_hairs = set(), set()
    for key in ids:
        character = characters.get(key)
        if character is None:
            raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Starter character is absent from master")
        default = character.get("defaultCostumeId")
        live = character.get("defaultLiveCostumeId") or default
        selected = []
        for costume_id in (default, live):
            costume = costumes.get(costume_id)
            if costume is None or costume.get("characterId") != key or costume.get("isUserUnavailable", False):
                raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Starter costume does not belong to its character")
            hair_id = costume.get("defaultHairId")
            if hair_id not in hairs or hairs[hair_id].get("characterId") != key:
                raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Starter hair does not belong to its character")
            selected.append(hair_id)
            if costume_id not in owned_costumes:
                snapshot.costumes.add(costumeId=costume_id, checked=True, obtainedTime=now)
                owned_costumes.add(costume_id)
            if hair_id not in owned_hairs:
                snapshot.hairs.add(hairId=hair_id, checked=True)
                owned_hairs.add(hair_id)
        snapshot.characters.add(characterId=key, favoriteCostumeId=default, liveCostumeId=live,
                                favoriteHairId=selected[0], liveHairId=selected[1], activityLevel=1,
                                activityStamina=stamina, staminaUpdatedTime=now)
    field = snapshot.DESCRIPTOR.fields_by_name["homePositions"].message_type.fields_by_name["homePositionType"]
    for value in field.enum_type.values:
        if value.number:
            snapshot.homePositions.add(homePositionType=value.number, characterId=ids[0])
    snapshot.areas.add(areaId=areas[0]["id"])
    snapshot.tutorials.add(tutorialType=_GAME_START, step=0)
    snapshot.profile.favoriteCharacterIds.extend(ids)
    identity = state.ensure_profile(profile)
    snapshot.userPublic.serverUserId = identity["server_id"]
    snapshot.userPublic.publicUserId = identity["public_id"]
    payload = snapshot.SerializeToString()
    state.save_snapshot(profile, payload, schema.fingerprint)
    return payload
