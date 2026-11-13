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
    "/api.Tutorial/Skip", "/api.Deck/Save", "/api.Deck/Delete",
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

    def hierarchy_grade(self, points: int = 0, best_id: str = "") -> str:
        """Resolve a real point-based grade without inventing global ranking."""
        details = self.ids("HierarchyDetailGrade", required=True)
        grades = self.ids("HierarchyGrade", required=True)
        if points < 0 or (best_id and best_id not in details):
            raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Local hierarchy state has invalid master references")
        eligible = []
        for key, row in details.items():
            try:
                if type(row["requiredHierarchyPoint"]) not in (int, str):
                    raise ValueError("Non-integer hierarchy threshold")
                threshold = int(row["requiredHierarchyPoint"])
                rank = row["requiredHierarchyRank"]
            except (KeyError, ValueError, TypeError, OverflowError):
                raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Invalid local hierarchy grade definition") from None
            if (row.get("hierarchyGradeId") not in grades or threshold < 0
                    or type(rank) is not int or rank < 0):
                raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Invalid local hierarchy grade references")
            if rank == 0 and threshold <= points:
                eligible.append((threshold, key))
        if not eligible:
            raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Local hierarchy catalog has no eligible base grade")
        highest = max(threshold for threshold, _ in eligible)
        candidates = [key for threshold, key in eligible if threshold == highest]
        if len(candidates) != 1:
            raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Local hierarchy grade threshold is ambiguous")
        return candidates[0]


class Gameplay:
    """Handle an explicit local feature allowlist; other methods return None."""

    def __init__(self, schema, state, profile: str, master_dir: Path | None = None, *, lessons=None, stories=None,
                 story_extra_fixture=None, dream=None):
        self.schema, self.state, self.profile = schema, state, profile
        self.catalog = _Catalog(master_dir)
        self.lessons = lessons
        self.stories = stories
        self.story_extra_fixture = story_extra_fixture
        self.dream = dream

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

    def _save_deck(self, snapshot, request, result):
        # The recovered 6.1.1 request contains the client's selected positions,
        # not optimizer inputs. QuestAuto (4) is set after the client builds and
        # serializes its entrusted formation (0x51fe7e8..0x51fe82c). ManualAuto
        # (3) is another known save provenance, with the same request contract.
        # Keep that layout, including explicit removals, instead of replacing it
        # with a guessed team. Borrowed buddies still require a rental contract
        # that transaction.UserDeckPosition cannot represent.
        if request.deckEditType not in (1, 2, 3, 4):
            raise RpcFailure(RpcCode.UNIMPLEMENTED, "Unknown local deck editing mode")
        if any(row.buddyUserId for row in request.userDeckPositions):
            raise RpcFailure(RpcCode.UNIMPLEMENTED, "Borrowed buddy deck positions are not supported")
        if request.number < 0:
            raise RpcFailure(RpcCode.INVALID_ARGUMENT, "A nonnegative deck number is required")
        deck = next((row for row in snapshot.decks if row.number == request.number), None)
        creating = request.number == 0
        number = request.number
        if creating:
            # Android 6.1.1 CreateDeck (0x51f7504) uses a Number=0
            # placeholder; CreateDeckSaveRequest (0x51fa93c) copies that value.
            settings = self.catalog.rows("Setting", required=True)
            limit = settings[0].get("deckCountMax") if len(settings) == 1 else None
            if type(limit) is not int or limit <= 0:
                raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Missing local deck count limit")
            numbers = [row.number for row in snapshot.decks]
            if (any(value <= 0 for value in numbers) or len(set(numbers)) != len(numbers)
                    or snapshot.user.deckSequence < 0):
                raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Local deck identities are invalid")
            if len(numbers) >= limit:
                raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Local deck count limit reached")
            number = max([snapshot.user.deckSequence, *numbers]) + 1
            if number > 2147483647:
                raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Local deck sequence exhausted")
        elif deck is None:
            raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Unknown local deck number")
        requested = list(request.userDeckPositions)
        if (any(not 1 <= row.position <= 5 for row in requested)
                or len({row.position for row in requested}) != len(requested)):
            raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Deck positions must have distinct indices from 1 to 5")
        if request.questId and request.questId not in self.catalog.ids("Quest", required=True):
            raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Unknown local quest reference")
        cards = {row.cardId: row for row in snapshot.cards}
        master_cards = self.catalog.ids("Card", required=bool(requested))
        costumes = {row.costumeId for row in snapshot.costumes}
        hairs = {row.hairId for row in snapshot.hairs}
        photos = {row.photoId for row in snapshot.photos}
        accessories = {row.accessoryId: row.amount for row in snapshot.accessories}
        costume_master = self.catalog.ids("Costume")
        hair_master = self.catalog.ids("Hair")
        accessory_master = self.catalog.ids("Accessory", required=any(
            row.part1AccessoryId or row.part2AccessoryId for row in requested))
        used_cards, used_photos, used_accessories = set(), set(), {}
        for row in requested:
            if not row.cardId or row.cardId not in cards or row.cardId not in master_cards or row.cardId in used_cards:
                raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Deck cards must be distinct owned master cards")
            used_cards.add(row.cardId)
            character = master_cards[row.cardId].get("characterId")
            for key, owned, master, label in ((row.costumeId, costumes, costume_master, "costume"),
                                             (row.hairId, hairs, hair_master, "hair")):
                if key and (key not in owned or key not in master or master[key].get("characterId") != character):
                    raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Deck " + label + " must belong to the owned card character")
            if (len(set(row.photoIds)) != len(row.photoIds) or any(key not in photos or key in used_photos for key in row.photoIds)
                    or len(row.photoIds) > cards[row.cardId].photoEquipableCount):
                raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Deck photos must be owned, distinct and within the card limit")
            used_photos.update(row.photoIds)
            for slot, key in ((1, row.part1AccessoryId), (2, row.part2AccessoryId)):
                if not key:
                    continue
                used_accessories[key] = used_accessories.get(key, 0) + 1
                if (used_accessories[key] > accessories.get(key, 0) or key not in accessory_master
                        or accessory_master[key].get("categoryType") != slot):
                    raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Deck accessory must be owned and match its slot")
                restriction = accessory_master[key].get("characterId")
                if restriction and restriction != character:
                    raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Deck accessory belongs to a different character")
                if accessory_master[key].get("characterGroupId"):
                    raise RpcFailure(RpcCode.UNIMPLEMENTED, "Character-group accessory restrictions require their master catalog")
        if creating:
            deck = snapshot.decks.add(number=number)
            snapshot.user.deckSequence = number
        old = [row for row in snapshot.deckPositions if row.number == number]
        kept = [row for row in snapshot.deckPositions if row.number != number]
        for row in old:
            if row.position not in {entry.position for entry in requested}:
                result.commonResponse.deletedData.deckPositions.add().CopyFrom(row)
        del snapshot.deckPositions[:]
        snapshot.deckPositions.extend(kept)
        old_by_position = {row.position: row for row in old}
        for row in requested:
            target = snapshot.deckPositions.add()
            if row.position in old_by_position:
                target.CopyFrom(old_by_position[row.position])  # Preserve unknown fields.
            target.number, target.position = number, row.position
            for name in ("cardId", "part1AccessoryId", "part2AccessoryId", "costumeId", "hairId"):
                setattr(target, name, getattr(row, name))
            del target.photoIds[:]
            target.photoIds.extend(row.photoIds)
        deck.name = request.name
        # Original DeckManager consumes the API status and rebuilds from its
        # persistent keyed user collections. ACK the affected unit in full,
        # including unchanged rows on retry, without replacing unrelated units.
        updated = result.commonResponse.updatedData
        updated.decks.add().CopyFrom(deck)
        updated.deckPositions.extend(row for row in snapshot.deckPositions if row.number == number)
        if creating:
            updated.user.CopyFrom(snapshot.user)
        return ()

    @staticmethod
    def _delete_deck(snapshot, request, result):
        if request.number <= 0:
            raise RpcFailure(RpcCode.INVALID_ARGUMENT, "A positive existing deck number is required")
        decks = [row for row in snapshot.decks if row.number == request.number]
        if not decks:
            raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Unknown local deck number")
        positions = [row for row in snapshot.deckPositions if row.number == request.number]
        result.commonResponse.deletedData.decks.extend(decks)
        result.commonResponse.deletedData.deckPositions.extend(positions)
        kept_decks = [row for row in snapshot.decks if row.number != request.number]
        kept_positions = [row for row in snapshot.deckPositions if row.number != request.number]
        del snapshot.decks[:]
        snapshot.decks.extend(kept_decks)
        del snapshot.deckPositions[:]
        snapshot.deckPositions.extend(kept_positions)
        # The original diff consumer permits null/null, but requires a present
        # UpdatedData whenever DeletedData is non-null. Keep this empty child;
        # only the explicit keyed deletions need to be applied to the client.
        result.commonResponse.updatedData.SetInParent()
        return ()

    def handle(self, path: str, request_bytes: bytes) -> bytes | None:
        if path not in _ROUTES:
            return None
        try:
            request = self.schema.request_type(path).FromString(request_bytes)
        except DecodeError:
            raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Malformed gameplay protobuf request") from None
        result = self.schema.response_type(path)()

        if path == "/api.Deck/Save":
            self._mutate(result, lambda snapshot: self._save_deck(snapshot, request, result))
        elif path == "/api.Deck/Delete":
            self._mutate(result, lambda snapshot: self._delete_deck(snapshot, request, result))
        elif path == "/api.Master/GetVersion":
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
            # HomeTop.SetHomeEnterData immediately dereferences this master
            # grade (Android 6.1.1 0x566c1c4..0x566c1d4). Presence alone is
            # insufficient: an empty currentDetailGradeId resolves to null.
            result.hierarchyNotiInfo.currentDetailGradeId = self.catalog.hierarchy_grade(
                snapshot.hierarchy.currentFixedPoint + snapshot.hierarchy.currentVariablePoint,
                snapshot.hierarchy.bestDetailGradeId)
            # These ordinary home/activity containers have empty-state readers.
            # Keep optional special-event messages absent: Android 6.1.1
            # HomeTop.ShouldHideLoading (0x566c9b0) checks whether
            # homeFishHeavenInfo is null. Even an empty message suppresses
            # LoadingManager.Hide (0x5675ff4..0x5676008).
            for field in ("fanEventInfo", "promotionInfo", "refreshInfo", "bannerInfo", "eventInfo",
                          "pvpInfo", "hierarchyNotiInfo", "notiStoneShopItem", "notiNormalShopItem",
                          "notiShowcaseShopItem", "leagueInfo", "loveInfo", "companyInfo"):
                if field in result.DESCRIPTOR.fields_by_name:
                    getattr(result, field).SetInParent()
            if self.dream is not None and "eventInfo" in result.DESCRIPTOR.fields_by_name:
                info = self.dream.home_info(snapshot)
                if info is not None:
                    result.eventInfo.dreamInfo.CopyFrom(info)
            if self.stories is not None:
                extra = (self.story_extra_fixture() if self.story_extra_fixture is not None
                         and "/api.Story/ListExtra" in self.schema.methods else None)
                if extra is not None and "extraStoryPartInfos" in result.DESCRIPTOR.fields_by_name:
                    try:
                        captured = self.schema.response_type("/api.Story/ListExtra").FromString(extra)
                    except DecodeError:
                        raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Account story catalog fixture is malformed") from None
                    result.extraStoryPartInfos.extend(captured.infos)
                else:
                    self.stories.fill_home(result)
            # Older/minimal descriptors and catalogs predate ordinary lesson
            # support. The shipped 6.1.1 catalog declares its step duration.
            ordinary = (self.lessons is not None and "/api.Activity/ReceiveLessonReward" in self.schema.methods
                        and any("secondsPerActivityLessonStep" in row for row in self.catalog.rows("Setting")))
            if ordinary:
                result.lessonProgress.CopyFrom(self.lessons.progress(result.currentMainAreaId))
            else:
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


def _starter_roster(catalog):
    """Close the office actor pool over the unconditional normal characters.

    Android 6.1.1 GetSubCharacterCandidate selects unlocked normal master rows,
    without filtering UserCharacter ownership. CreateActorDescriptor then
    dereferences FindById. The five photo-tutorial characters are not that pool.
    """
    settings = catalog.rows("Setting", required=True)
    if len(settings) != 1:
        raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Starter seeding needs one Setting master row")
    photo_ids = settings[0].get("tutorialPhotoShootingCharacterIds")
    if (not isinstance(photo_ids, list) or not photo_ids
            or any(not isinstance(key, str) or not key for key in photo_ids)
            or len(set(photo_ids)) != len(photo_ids)):
        raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Starter character identities are missing from Setting")
    characters = catalog.ids("Character", required=True)
    baseline = []
    for key, row in characters.items():
        if type(row.get("type")) is not int or row["type"] != 1:
            continue
        conditions = [row.get(name, "") for name in ("viewConditionId", "unlockConditionId")]
        if any(not isinstance(value, str) for value in conditions):
            raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Invalid starter character conditions")
        if not any(conditions):
            baseline.append(key)
    if not baseline or not set(photo_ids).issubset(baseline):
        raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Starter office roster is incomplete in master")
    ids = list(dict.fromkeys([*photo_ids, *sorted(baseline)]))
    costumes = catalog.ids("Costume", required=True)
    hairs = catalog.ids("Hair", required=True)
    appearances = {}
    for key in ids:
        character = characters[key]
        default = character.get("defaultCostumeId")
        live = character.get("defaultLiveCostumeId") or default
        selected = []
        for costume_id in (default, live):
            costume = costumes.get(costume_id)
            if costume is None or costume.get("characterId") != key or costume.get("isUserUnavailable", False):
                raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Starter costume does not belong to its character")
            hair_id = costume.get("defaultHairId")
            hair = hairs.get(hair_id)
            if hair is None or hair.get("characterId") != key:
                raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Starter hair does not belong to its character")
            wearable = hair.get("wearableCostumeIds")
            if wearable is not None and (not isinstance(wearable, list) or costume_id not in wearable):
                raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Starter hair cannot wear its costume")
            selected.append((costume_id, hair_id))
        appearances[key] = selected
    stamina_rows = catalog.rows("CharacterActivityLevel", required=True)
    stamina = next((row.get("maxStamina") for row in stamina_rows if row.get("level") == 1), None)
    if type(stamina) is not int or stamina < 0:
        raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Starter activity stamina is missing from master")
    return photo_ids, ids, appearances, stamina


def _append_starter_characters(snapshot, ids, appearances, stamina, now):
    owned_characters = {row.characterId for row in snapshot.characters}
    owned_costumes = {row.costumeId for row in snapshot.costumes}
    owned_hairs = {row.hairId for row in snapshot.hairs}
    for key in ids:
        if key in owned_characters:
            continue
        (default, hair), (live, live_hair) = appearances[key]
        for costume_id, hair_id in appearances[key]:
            if costume_id not in owned_costumes:
                snapshot.costumes.add(costumeId=costume_id, checked=True, obtainedTime=now)
                owned_costumes.add(costume_id)
            if hair_id not in owned_hairs:
                snapshot.hairs.add(hairId=hair_id, checked=True)
                owned_hairs.add(hair_id)
        snapshot.characters.add(characterId=key, favoriteCostumeId=default, liveCostumeId=live,
                                favoriteHairId=hair, liveHairId=live_hair, activityLevel=1,
                                activityStamina=stamina, staminaUpdatedTime=now)


def _legacy_starter(snapshot, photo_ids, appearances, identity):
    """Recognize only the old server's otherwise unmarked starter layout."""
    starter_lists = {"characters", "costumes", "hairs", "decks", "areas", "tutorials", "homePositions"}
    mutable_singletons = {"user", "userPublic", "totalCount", "profile", "hierarchy"}
    for field in snapshot.DESCRIPTOR.fields:
        value = getattr(snapshot, field.name)
        if field.is_repeated and field.name not in starter_lists and value:
            return False
        if (field.message_type is not None and not field.is_repeated
                and field.name not in mutable_singletons and value.SerializeToString()):
            return False
    if (identity is None or snapshot.user.managerLevel != 1 or snapshot.user.deckSequence != 1
            or snapshot.user.gameStartTime <= 0 or len(snapshot.decks) != 1
            or snapshot.decks[0].number != 1 or snapshot.decks[0].name != "Local deck"
            or snapshot.cards or snapshot.deckPositions
            or len(snapshot.characters) != len(photo_ids)
            or {row.characterId for row in snapshot.characters} != set(photo_ids)
            or list(snapshot.profile.favoriteCharacterIds) != photo_ids
            or snapshot.userPublic.serverUserId != identity["server_id"]
            or snapshot.userPublic.publicUserId != identity["public_id"]):
        return False
    expected_costumes, expected_hairs = set(), set()
    for row in snapshot.characters:
        (default, hair), (live, live_hair) = appearances[row.characterId]
        if ((row.favoriteCostumeId, row.favoriteHairId, row.liveCostumeId, row.liveHairId)
                != (default, hair, live, live_hair)):
            return False
        expected_costumes.update((default, live))
        expected_hairs.update((hair, live_hair))
    if (len(snapshot.costumes) != len(expected_costumes) or len(snapshot.hairs) != len(expected_hairs)
            or {row.costumeId for row in snapshot.costumes} != expected_costumes
            or {row.hairId for row in snapshot.hairs} != expected_hairs):
        return False
    field = snapshot.DESCRIPTOR.fields_by_name["homePositions"].message_type.fields_by_name["homePositionType"]
    kinds = {value.number for value in field.enum_type.values if value.number}
    return (len(snapshot.homePositions) == len(kinds)
            and {row.homePositionType for row in snapshot.homePositions} == kinds
            and all(row.characterId == photo_ids[0] and not row.isCharacterRandom and not row.isCostumeRandom
                    for row in snapshot.homePositions))


def repair_starter_roster(state, schema, profile: str, master_dir: Path) -> bool:
    """Add missing office actors only to a tagged or recognized local starter.

    Explicit imports are version 0 and never repaired. Older databases have no
    marker, so their five-character layout must match the original seeder.
    Existing rows, progress, identities, unknown fields and sessions survive.
    """
    current = state.snapshot(profile)
    version = state.starter_version(profile)
    if current is None or version == 0 or (version is not None and version >= 2):
        return False
    if current[1] != schema.fingerprint:
        return False
    photo_ids, ids, appearances, stamina = _starter_roster(_Catalog(master_dir))
    identity = state.profile(profile)

    def repair(payload, origin):
        if origin == 0 or (origin is not None and origin >= 2):
            return None
        try:
            snapshot = schema.response_type(_USER_GET).FromString(payload)
        except DecodeError:
            raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Local starter snapshot is malformed") from None
        if not snapshot.HasField("user"):
            return None
        if origin is None and not _legacy_starter(snapshot, photo_ids, appearances, identity):
            return None
        _append_starter_characters(snapshot, ids, appearances, stamina, _now_ms())
        return snapshot.SerializeToString(), 2

    return state.mutate_starter_snapshot(profile, schema.fingerprint, repair) is not None


def _starter_home_positions(schema, photo_ids, character_ids):
    """Assign a distinct owned starter to each of the four 6.1.1 home pages.

    The client swaps an already assigned character when editing a page.
    Distinct IDs also keep separate page-loading jobs from repositioning and
    changing renderer references on the same cached default actor.
    """
    field = schema.response_type(_USER_GET).DESCRIPTOR.fields_by_name["homePositions"]
    kinds = sorted(value.number for value in field.message_type.fields_by_name[
        "homePositionType"].enum_type.values if value.number)
    choices = list(dict.fromkeys([*photo_ids, *character_ids]))
    if kinds != [1, 2, 3, 4] or len(choices) < len(kinds):
        raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Starter home pages need four distinct characters")
    return dict(zip(kinds, choices))


def repair_starter_home_positions(state, schema, profile: str, master_dir: Path) -> bool:
    """Repair only the version-2 starter's exact repeated fixed-page layout.

    Imports, unmarked snapshots and customized/random assignments are never
    changed. Legacy roster repair must run first to establish version 2.
    Character rows, other protobuf fields and existing sessions are preserved.
    """
    current = state.snapshot(profile)
    if (current is None or state.starter_version(profile) != 2
            or current[1] != schema.fingerprint):
        return False
    photo_ids, ids, _appearances, _stamina = _starter_roster(_Catalog(master_dir))
    positions = _starter_home_positions(schema, photo_ids, ids)

    def repair(payload, origin):
        if origin != 2:
            return None
        try:
            snapshot = schema.response_type(_USER_GET).FromString(payload)
        except DecodeError:
            raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Local starter snapshot is malformed") from None
        if (not snapshot.HasField("user") or len(snapshot.homePositions) != len(positions)
                or {row.homePositionType for row in snapshot.homePositions} != set(positions)
                or any(row.characterId != photo_ids[0] or row.isCharacterRandom or row.isCostumeRandom
                       for row in snapshot.homePositions)
                or not set(positions.values()).issubset({row.characterId for row in snapshot.characters})):
            return None
        for row in snapshot.homePositions:
            row.characterId = positions[row.homePositionType]
        return snapshot.SerializeToString(), 3

    return state.mutate_starter_snapshot(profile, schema.fingerprint, repair) is not None


def _fill_starter_deck(snapshot, catalog, photo_ids):
    """Put the five initial photo idols in the local default unit.

    This is a local starting formation, not a recovered official tutorial deck
    template. It uses only initial-reward cards and already owned live outfits.
    """
    if (len(photo_ids) != 5 or snapshot.deckPositions or len(snapshot.decks) != 1
            or snapshot.decks[0].number != 1):
        raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Starter formation needs five idols and one empty local deck")
    master = catalog.ids("Card", required=True)
    characters = {row.characterId: row for row in snapshot.characters}
    costumes = {row.costumeId for row in snapshot.costumes}
    hairs = {row.hairId for row in snapshot.hairs}
    selected = []
    for key in photo_ids:
        cards = [row.cardId for row in snapshot.cards
                 if row.cardId in master and master[row.cardId].get("characterId") == key]
        character = characters.get(key)
        if (len(cards) != 1 or character is None or character.liveCostumeId not in costumes
                or character.liveHairId not in hairs):
            raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Starter formation has invalid owned card or appearance references")
        selected.append((cards[0], character.liveCostumeId, character.liveHairId))
    for position, (card, costume, hair) in enumerate(selected, 1):
        snapshot.deckPositions.add(number=1, position=position, cardId=card,
                                   costumeId=costume, hairId=hair)


def repair_starter_inventory(state, schema, profile: str, master_dir: Path) -> bool:
    """Fill only the old tagged, empty, pre-live local starter once.

    Imports, custom decks/inventory and progressed accounts are excluded. The
    snapshot, origin marker and opaque fields share one SQLite transaction;
    settings and sessions are not replaced.
    """
    current = state.snapshot(profile)
    if (current is None or state.starter_version(profile) != 3
            or current[1] != schema.fingerprint):
        return False
    from .initial_inventory import prepare_initial_inventory, apply_initial_inventory

    catalog = _Catalog(master_dir)
    photo_ids, _ids, _appearances, _stamina = _starter_roster(catalog)
    plan = None

    def repair(payload, origin):
        nonlocal plan
        if origin != 3:
            return None
        try:
            snapshot = schema.response_type(_USER_GET).FromString(payload)
        except DecodeError:
            raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Local starter snapshot is malformed") from None
        starts = [row for row in snapshot.tutorials if row.tutorialType == _GAME_START]
        if (not snapshot.HasField("user") or snapshot.user.managerLevel != 1
                or snapshot.user.deckSequence != 1 or snapshot.user.tutorialClearedTime
                or len(snapshot.decks) != 1 or snapshot.decks[0].number != 1
                or snapshot.decks[0].name != "Local deck"
                or snapshot.cards or snapshot.items or snapshot.deckPositions
                or snapshot.photos or snapshot.accessories or snapshot.balance.SerializeToString()
                or len(starts) != 1 or starts[0].step not in (0, 10)
                or snapshot.quests or any(row.clearQuestCount or row.lastClearedTime for row in snapshot.areas)):
            return None
        if plan is None:
            plan = prepare_initial_inventory(schema, master_dir)
        apply_initial_inventory(snapshot, plan, obtained_time=_now_ms())
        _fill_starter_deck(snapshot, catalog, photo_ids)
        return snapshot.SerializeToString(), 4

    return state.mutate_starter_snapshot(profile, schema.fingerprint, repair) is not None


def seed_starter_profile(state, schema, profile: str, master_dir: Path, *, manager_name: str = "Local Manager") -> bytes:
    """Create a new, master-backed tutorial-start snapshot, never an import.

    This prepares the unconditional normal office characters, their default
    appearances and the canonical initial reward inventory. The first five
    photo idols form the local default deck. No clears or event rewards are
    granted. Catalog validation finishes before any profile is written.
    """
    if state.snapshot(profile) is not None:
        raise RpcFailure(RpcCode.ALREADY_EXISTS, "Starter seeding requires a profile without a snapshot")
    if not isinstance(manager_name, str) or not manager_name.strip():
        raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Starter manager name must not be empty")
    catalog = _Catalog(master_dir)
    from .initial_inventory import prepare_initial_inventory, apply_initial_inventory
    inventory = prepare_initial_inventory(schema, master_dir)
    photo_ids, ids, appearances, stamina = _starter_roster(catalog)
    home_positions = _starter_home_positions(schema, photo_ids, ids)
    areas = catalog.main_areas()
    quests = catalog.ids("Quest", required=True)
    if not areas or not areas[0].get("questIds") or any(key not in quests or quests[key].get("areaId") != areas[0]["id"] for key in areas[0]["questIds"]):
        raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Starter main area and quest identities do not match")
    base_hierarchy_grade = catalog.hierarchy_grade()
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
    snapshot.hierarchy.bestDetailGradeId = base_hierarchy_grade
    snapshot.decks.add(number=1, name="Local deck")
    _append_starter_characters(snapshot, ids, appearances, stamina, now)
    apply_initial_inventory(snapshot, inventory, obtained_time=now)
    _fill_starter_deck(snapshot, catalog, photo_ids)
    for kind, character_id in home_positions.items():
        snapshot.homePositions.add(homePositionType=kind, characterId=character_id)
    snapshot.areas.add(areaId=areas[0]["id"])
    snapshot.tutorials.add(tutorialType=_GAME_START, step=0)
    snapshot.profile.favoriteCharacterIds.extend(photo_ids)
    from .card_level_missions import initialize_mission
    has_mission = initialize_mission(snapshot, catalog, now)
    identity = state.ensure_profile(profile)
    snapshot.userPublic.serverUserId = identity["server_id"]
    snapshot.userPublic.publicUserId = identity["public_id"]
    payload = snapshot.SerializeToString()
    state.save_snapshot(profile, payload, schema.fingerprint, starter_version=5 if has_mission else 4)
    return payload


def repair_starter_card_level_mission(state, schema, profile: str, master_dir: Path) -> bool:
    """Add the evidenced achievement only to an explicitly version-4 starter.

    Imports, unmarked/older origins and existing mission rows are not reset.
    Missing Mission data in old payloads preserves their previous behavior.
    """
    current = state.snapshot(profile)
    if current is None or state.starter_version(profile) != 4 or current[1] != schema.fingerprint:
        return False
    from .card_level_missions import initialize_mission, mission_master, saved_mission
    catalog = _Catalog(master_dir)
    thresholds = mission_master(catalog, optional=True)
    if thresholds is None:
        return False

    def repair(payload, origin):
        if origin != 4:
            return None
        try:
            snapshot = schema.response_type(_USER_GET).FromString(payload)
        except (DecodeError, UnicodeError):
            raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Local starter snapshot is malformed") from None
        if not snapshot.HasField("user"):
            raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Local starter has no user state")
        if "missions" not in snapshot.DESCRIPTOR.fields_by_name:
            return None
        # Existing rows can carry imported thresholds/receipts or unknown
        # fields. Validate, preserve byte-for-byte, and only advance the marker.
        if saved_mission(snapshot, thresholds) is not None:
            return payload, 5
        if not initialize_mission(snapshot, catalog, _now_ms()):
            return None
        return snapshot.SerializeToString(), 5

    return state.mutate_starter_snapshot(profile, schema.fingerprint, repair) is not None
