"""Finite normal-account Moshi Koi gameplay with atomic, portable progress.

Original 6.1.1 RPC/masters/ADV define the client contract. Inferred route data
is an explicitly pinned local compatibility policy for branching only. No
inferred choice or ending bonus changes actual UserLove.hiddenFavorability;
only the original present Item.value does. No stones or finish items are invented.
"""
from __future__ import annotations

import copy
import datetime
import hashlib
import json
import os
import stat
from pathlib import Path
import re
import time

from google.protobuf import message_factory
from google.protobuf.message import DecodeError

from .gameplay import _Catalog
from .rpc import RpcCode, RpcFailure

_USER = "/api.User/Get"
_PREFIX = "/api.Love/"
_NAMES = ("Title", "TitleExtra", "Register", "Top", "Start", "Restart", "Finish",
          "ResetReadingStoryStatus", "Present", "Save", "UpdateSaveName", "Load", "Reset",
          "ReceiveLessonReward", "PromoteLesson", "UpdateName", "GetMainCharacter")
ROUTES = frozenset(_PREFIX + name for name in _NAMES)
_MAX_PROGRESS = 128 * 1024
_I64 = (1 << 63) - 1
_DAY = 86400000
_JST = 9 * 3600000
_PROGRESS_FIELDS = {"schema", "love_id", "player_name", "registered_ms", "exp", "lesson_anchor_ms",
                    "last_play_ms", "path", "choices", "past_choices", "current", "saves",
                    "promotion_day", "promotion_used"}


def _valid(ok):
    if not ok:
        raise ValueError("love_progress_invalid")


def _id(value):
    return type(value) is str and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value) is not None


def _integer(value, maximum=_I64, minimum=0):
    return type(value) is int and minimum <= value <= maximum


def _name(value, *, empty=False):
    return (type(value) is str and (empty or bool(value.strip())) and len(value) <= 128
            and len(value.encode("utf-8")) <= 512 and not any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in value))


def _path(value):
    _valid(type(value) is list and 0 < len(value) <= 128
           and all(_id(item) for item in value) and len(set(value)) == len(value))


def _choices(value):
    _valid(type(value) is dict and len(value) <= 128)
    for episode, groups in value.items():
        _valid(_id(episode) and type(groups) is list and len(groups) <= 64)
        seen = set()
        for row in groups:
            _valid(type(row) is dict and set(row) == {"group", "index", "valid"}
                   and _integer(row["group"],64,1) and _integer(row["index"],64,1)
                   and type(row["valid"]) is bool and row["group"] not in seen)
            seen.add(row["group"])


def validate_progress(raw, love_id):
    """Pure archive validator: exact bounded JSON, no catalog or side effects.

    Account ZIP inspection uses this before a local DB is changed. References
    to the selected rule set are checked separately when gameplay is opened.
    """
    _valid(type(raw) is bytes and 0 < len(raw) <= _MAX_PROGRESS and _id(love_id))
    def pairs(items):
        out = {}
        for key,value in items:
            _valid(key not in out)
            out[key] = value
        return out
    try:
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        _valid(type(data) is dict and set(data) == _PROGRESS_FIELDS
               and type(data["schema"]) is int and data["schema"] == 1
               and data["love_id"] == love_id and _name(data["player_name"]))
        for key in ("registered_ms", "exp", "lesson_anchor_ms", "last_play_ms"):
            _valid(_integer(data[key]))
        _path(data["path"]);_choices(data["choices"])
        _valid(set(data["choices"]) <= set(data["path"]))
        past = data["past_choices"]
        _valid(type(past) is dict and len(past) <= 128)
        for episode, groups in past.items():
            _valid(_id(episode) and type(groups) is dict and len(groups) <= 64)
            for group, indices in groups.items():
                _valid(type(group) is str and re.fullmatch(r"[1-9][0-9]?", group) is not None
                       and int(group) <= 64 and type(indices) is list and len(indices) <= 64
                       and all(_integer(index,64,1) for index in indices)
                       and len(set(indices)) == len(indices))
        current = data["current"]
        _valid(current is None or type(current) is dict and set(current) == {"episode_id", "hint"}
               and current["episode_id"] in data["path"] and _integer(current["hint"],2))
        saves = data["saves"]
        _valid(type(saves) is list and len(saves) <= 10)
        slots = set()
        for save in saves:
            _valid(type(save) is dict and set(save) == {"slot", "name", "saved_ms", "path", "choices"}
                   and _integer(save["slot"],10,1) and save["slot"] not in slots
                   and _name(save["name"],empty=True) and _integer(save["saved_ms"]))
            slots.add(save["slot"]);_path(save["path"]);_choices(save["choices"])
            _valid(set(save["choices"]) <= set(save["path"]))
        day = data["promotion_day"]
        _valid(type(day) is str and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}",day) is not None)
        datetime.date.fromisoformat(day)
        _valid(_integer(data["promotion_used"],1000000))
        return data
    except (ValueError, TypeError, KeyError, UnicodeError, OverflowError, RecursionError):
        raise ValueError("love_progress_invalid") from None


def _encode_progress(data):
    raw = json.dumps(data, ensure_ascii=False, allow_nan=False, sort_keys=True,
                     separators=(",", ":")).encode("utf-8")
    validate_progress(raw,data["love_id"])
    return raw


def _fail(code="state_unavailable", status=RpcCode.FAILED_PRECONDITION):
    raise RpcFailure(status, "Local Moshi Koi: " + code)


def _day(now):
    return datetime.datetime.fromtimestamp((now + _JST)/1000,datetime.timezone.utc).date().isoformat()


_MAX_DISPLAY_TEXT = 4 * 1024 * 1024


def _display_pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("love_display_text_invalid")
        result[key] = value
    return result


def _display_read(path, maximum):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= maximum:
            raise ValueError("love_display_text_invalid")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            raw = stream.read(maximum + 1)
        if len(raw) != info.st_size:
            raise ValueError("love_display_text_invalid")
        return raw
    finally:
        os.close(descriptor)


def _display_map(value):
    if type(value) is not dict or len(value) > 32768:
        raise ValueError("love_display_text_invalid")
    total = 0
    result = {}
    for source, target in value.items():
        if (type(source) is not str or type(target) is not str or not source
                or "\0" in source or "\0" in target):
            raise ValueError("love_display_text_invalid")
        source_bytes, target_bytes = len(source.encode("utf-8")), len(target.encode("utf-8"))
        if source_bytes > 4096 or target_bytes > 16384:
            raise ValueError("love_display_text_invalid")
        total += source_bytes + target_bytes
        if total > _MAX_DISPLAY_TEXT:
            raise ValueError("love_display_text_invalid")
        if target:
            result[source] = target
    return result


def load_display_text(cache_root, *, language, platform):
    """Read existing exact generic translations once; never translate game data.

    Optional absent text groups retain Japanese. Corrupt or substituted groups
    fail with a fixed code. The normal resource installer owns their immutable
    outer package pin; this reader also verifies the inner text pack hash.
    """
    if language not in ("ja", "ko", "en") or platform not in ("android", "ios"):
        raise ValueError("love_display_text_invalid")
    if language == "ja":
        return {}
    from .bundled_translations import resolve_translation_root
    try:
        root = resolve_translation_root(cache_root, platform=platform) / language
        if root.is_symlink():
            raise ValueError("love_display_text_invalid")
        pack_path, manifest_path = root / "text.json", root / "text-manifest.json"
        if not os.path.lexists(pack_path) and not os.path.lexists(manifest_path):
            return {}
        report = json.loads(_display_read(manifest_path, 128 * 1024).decode("utf-8"),
                            object_pairs_hook=_display_pairs)
        record = report.get("pack") if type(report) is dict else None
        if (report.get("schema") != 1 or type(report.get("schema")) is not int
                or report.get("language") != language or type(record) is not dict
                or set(record) != {"name", "bytes", "sha256"} or record["name"] != "text.json"
                or type(record["bytes"]) is not int or not 0 < record["bytes"] <= _MAX_DISPLAY_TEXT
                or type(record["sha256"]) is not str or not re.fullmatch(r"[0-9a-f]{64}", record["sha256"])):
            raise ValueError("love_display_text_invalid")
        raw = _display_read(pack_path, _MAX_DISPLAY_TEXT)
        if len(raw) != record["bytes"] or hashlib.sha256(raw).hexdigest() != record["sha256"]:
            raise ValueError("love_display_text_invalid")
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=_display_pairs)
        if (type(data) is not dict or set(data) != {"schema", "language", "ui", "generic", "split", "phone"}
                or type(data["schema"]) is not int or data["schema"] != 1 or data["language"] != language):
            raise ValueError("love_display_text_invalid")
        return _display_map(data["generic"])
    except (OSError, ValueError, TypeError, KeyError, AttributeError, UnicodeError, RecursionError):
        raise ValueError("love_display_text_invalid") from None


class Love:
    """Seventeen original RPCs, limited to locally scheduled, validated rules."""
    def __init__(self, schema, state, profile, master_dir, *, catalog_path=None,
                 event_settings=None, clock=None, media_mode=False, display_text=None):
        self.schema, self.state, self.profile = schema, state, profile
        self.master_dir, self.catalog_path = master_dir, catalog_path
        self.catalog = _Catalog(master_dir)
        self.settings = copy.deepcopy(event_settings) if event_settings is not None else {
            "schema":1, "revision":0, "love_events":[]}
        self.clock = clock or (lambda: time.time_ns() // 1000000)
        self.media_mode = media_mode is True
        self._prepared = None
        self._display_text = _display_map(display_text) if display_text is not None else {}

    def _text(self, original):
        return self._display_text.get(original, original)

    @staticmethod
    def handles(path):
        return path in ROUTES

    def _now(self):
        now = self.clock()
        if not _integer(now,253402214399999):
            _fail("clock_invalid")
        return now

    def _active(self, now):
        settings = self.settings
        if (type(settings) is not dict or settings.get("schema") != 1
                or type(settings.get("love_events")) is not list or len(settings["love_events"]) > 64):
            _fail("event_settings_invalid")
        active, seen = {}, set()
        for row in settings["love_events"]:
            if (type(row) is not dict or set(row) != {"event_id","start_time_ms","end_time_ms"}
                    or not _id(row["event_id"]) or row["event_id"] in seen
                    or not _integer(row["start_time_ms"],253402214399999)
                    or not _integer(row["end_time_ms"],253402214399999)
                    or row["end_time_ms"] and row["end_time_ms"] <= row["start_time_ms"]):
                _fail("event_settings_invalid")
            seen.add(row["event_id"])
            if row["start_time_ms"] <= now and (not row["end_time_ms"] or now < row["end_time_ms"]):
                active[row["event_id"]] = row
        return active

    def _load(self):
        if self._prepared is None:
            from .love_catalog import load_love_catalog
            try:
                self._prepared = load_love_catalog(self.schema,self.master_dir,self.catalog_path)
            except (ValueError,OSError,KeyError,TypeError):
                _fail("catalog_unavailable")
        return self._prepared

    def _event(self, identity, now):
        if identity not in self._active(now):
            _fail("event_disabled_or_outside_period")
        event = self._load()["events"].get(identity)
        if event is None:
            _fail("event_unsupported",RpcCode.UNIMPLEMENTED)
        return event

    def _parse(self, raw):
        try:
            value = self.schema.response_type(_USER).FromString(raw)
        except (DecodeError,UnicodeError):
            _fail("snapshot_invalid")
        if not value.HasField("user"):
            _fail("snapshot_invalid")
        return value

    def _snapshot(self):
        row = self.state.snapshot(self.profile)
        if row is None or row[1] != self.schema.fingerprint:
            _fail("snapshot_unavailable")
        return self._parse(row[0])

    @staticmethod
    def _number(value, *, minimum=0):
        if type(value) is str and re.fullmatch(r"-?(?:0|[1-9][0-9]*)",value):
            value = int(value)
        if not _integer(value,minimum=minimum):
            _fail("catalog_amount_invalid")
        return value

    @staticmethod
    def _love(snapshot, identity, *, create=False):
        rows = [row for row in snapshot.loves if row.loveId == identity]
        if len(rows) > 1:
            _fail("love_state_ambiguous")
        return rows[0] if rows else snapshot.loves.add(loveId=identity) if create else None

    def _progress(self, raw, identity, event):
        try:
            data = validate_progress(raw,identity)
        except ValueError:
            _fail("progress_invalid")
        self._references(data,event)
        return data

    def _references(self, data, event):
        episodes, routes = event["episodes"],event["routes"]
        def verify(path,choices):
            if any(key not in episodes or key not in routes for key in path):
                _fail("progress_rules_differ")
            for key, rows in choices.items():
                groups = {row["index"]:row for row in routes[key].get("groups",[])}
                for row in rows:
                    if row["group"] not in groups or not 1 <= row["index"] <= groups[row["group"]]["count"]:
                        _fail("progress_rules_differ")
        verify(data["path"],data["choices"])
        for saved in data["saves"]:
            verify(saved["path"],saved["choices"])
        for key, entries in data["past_choices"].items():
            if key not in routes:
                _fail("progress_rules_differ")
            groups = {str(row["index"]):row for row in routes[key].get("groups",[])}
            if any(group not in groups or any(index > groups[group]["count"] for index in indices)
                   for group,indices in entries.items()):
                _fail("progress_rules_differ")

    def _progress_ruleset(self, row):
        plan = self._load()
        current = plan["ruleset_sha256"]
        aliases = plan.get("progress_ruleset_aliases", [])
        if (type(aliases) is not list or len(aliases) > 1
                or any(type(value) is not str or not re.fullmatch(r"[0-9a-f]{64}", value) for value in aliases)):
            _fail("progress_rules_differ")
        if row is None:
            return current
        if row[1] != self.schema.fingerprint or row[2] not in (current, *aliases):
            _fail("progress_rules_differ")
        # A validated compatibility alias is an accepted existing storage pin,
        # never an instruction to rewrite account metadata or archive bytes.
        return row[2]

    def _saved(self, identity, event):
        row = self.state.love_progress(self.profile,identity)
        if row is None:
            return None
        self._progress_ruleset(row)
        return self._progress(row[0],identity,event)

    def _unlocked(self, snapshot, event):
        if self.media_mode:
            return True
        identity = event.get("unlockConditionId","")
        condition = self.catalog.ids("Condition",required=True).get(identity)
        settings = condition.get("settings") if condition else None
        if (type(settings) is not list or len(settings) != 1 or set(settings[0]) != {"clearArea"}
                or set(settings[0]["clearArea"]) != {"areaId"}):
            _fail("unlock_condition_unsupported",RpcCode.UNIMPLEMENTED)
        area_id = settings[0]["clearArea"]["areaId"]
        area = self.catalog.ids("Area",required=True).get(area_id)
        quests = area.get("questIds") if area else None
        if type(quests) is not list or not quests or len(set(quests)) != len(quests):
            _fail("unlock_area_invalid")
        rows = [row for row in snapshot.areas if row.areaId == area_id]
        if len(rows) > 1 or rows and rows[0].clearQuestCount < 0:
            _fail("unlock_area_invalid")
        return bool(rows and rows[0].clearQuestCount >= len(quests))

    def _first(self, event):
        ids = [key for key,row in event["episodes"].items() if row.get("episode") == 1]
        if len(ids) != 1:
            _fail("first_episode_ambiguous")
        return ids[0]

    def _new(self, identity, event, name, now):
        return {"schema":1,"love_id":identity,"player_name":name,"registered_ms":now,
                "exp":max(self._number(row.get("requiredExp",0)) for row in event["levels"]) if self.media_mode else 0,
                "lesson_anchor_ms":now,"last_play_ms":now,"path":[self._first(event)],"choices":{},
                "past_choices":{},"current":None,"saves":[],"promotion_day":_day(now),"promotion_used":0}

    def _name(self, value):
        # Ten Unicode scalar characters is a deliberately finite local
        # compatibility limit, not a newly claimed original server setting.
        if not _name(value) or len(value) > 10:
            _fail("name_invalid",RpcCode.INVALID_ARGUMENT)
        return value

    def _level(self, event, exp):
        levels = sorted(event["levels"],key=lambda row:row["level"])
        if not levels or levels[0]["level"] != 1:
            _fail("levels_invalid")
        current = levels[0]
        for row in levels:
            if self._number(row.get("requiredExp",0)) > exp:
                break
            current = row
        return current

    def _hint(self, event, data, requested):
        if self.media_mode:
            if not _integer(requested,2):_fail("hint_locked",RpcCode.INVALID_ARGUMENT)
            return 2
        level = self._level(event,data["exp"])["level"]
        unlocked = max([0]+[int(key) for key,value in event["hintUnlockLevels"].items() if value <= level])
        if not _integer(requested,2) or requested > unlocked:
            _fail("hint_locked",RpcCode.INVALID_ARGUMENT)
        return unlocked

    def _main_character(self, event):
        values = event.get("mainCharacters") or [{"characterId":event.get("characterId"),
            "costumeId":event.get("costumeId"),"assetId":event.get("characterAssetId"),"color":event.get("color")}]
        # Stable first heroine is an explicit local policy. Unknown official
        # rotation weights are not reproduced by a fabricated random process.
        selected = values[0]
        cls = message_factory.GetMessageClass(self.schema.pool.FindMessageTypeByName("api.LoveMainCharacterInfo"))
        return cls(**selected)

    def _lesson_progress(self, result, event, data):
        hours = self._number(event["lessonMaxHours"],minimum=1)
        if hours > 24:
            _fail("lesson_policy_unsupported")
        result.lastReceiveTime = data["lesson_anchor_ms"]
        result.maxRewardTime = min(_I64,data["lesson_anchor_ms"]+hours*3600000)

    def _info(self, snapshot, identity, event, schedule, now):
        cls = message_factory.GetMessageClass(self.schema.pool.FindMessageTypeByName("api.LoveInfo"))
        info = cls(loveId=identity,description=self._text(event["description"]),assetId=event.get("assetId",identity),
            baseType=event.get("baseType",1),type=2 if schedule["end_time_ms"] else 1,
            startTime=schedule["start_time_ms"],endTime=schedule["end_time_ms"],
            unlockConditionId=event["unlockConditionId"],isUnlocked=self._unlocked(snapshot,event),
            isHideManagerVoiceSwitch=event.get("hideManagerVoiceSwitch",False))
        info.mainCharacterInfo.CopyFrom(self._main_character(event))
        info.characterId,info.costumeId=info.mainCharacterInfo.characterId,info.mainCharacterInfo.costumeId
        data = self._saved(identity,event)
        love = self._love(snapshot,identity)
        info.isUnplayed = data is None and (self.media_mode or love is None)
        info.lastPlayTime = data["last_play_ms"] if data else 0
        info.isLessonRewardMax = bool(not self.media_mode and data and now >= data["lesson_anchor_ms"]+event["lessonMaxHours"]*3600000)
        present = event.get("presentItemId","")
        info.hasHiddenFavorabilityObtainItem = bool(not self.media_mode and present and self._item_amount(snapshot,present,now)>0)
        # Mission grants/claims remain separate APIs. These IDs are original
        # UI references and never mark a task received or award a reward.
        info.eventMissionIds.extend(event.get("eventMissionIds",[]))
        info.limitedEventMissionIds.extend(event.get("limitedEventMissionIds",[]))
        unlocked = set(love.unlockedLoveStoryEndIDs) if love else set()
        for ending in event["endings"]:
            info.storyEndInfos.add(id=ending["id"],name=self._text(ending["name"]),unlocked=self.media_mode or ending["id"] in unlocked)
        return info

    def home_info(self, snapshot=None):
        now = self._now()
        active = self._active(now)
        if not active:
            return None
        plan = self._load()
        snapshot = snapshot if snapshot is not None else self._snapshot()
        overall_cls = message_factory.GetMessageClass(self.schema.pool.FindMessageTypeByName("api.HomeLoveInfo"))
        entry_cls = message_factory.GetMessageClass(self.schema.pool.FindMessageTypeByName("api.HomeLoveEventInfo"))
        overall,entries = overall_cls(),[]
        for order,(identity,schedule) in enumerate(sorted(active.items())):
            event = plan["events"].get(identity)
            if event is None:
                _fail("event_unsupported",RpcCode.UNIMPLEMENTED)
            info = self._info(snapshot,identity,event,schedule,now)
            row = entry_cls(id=identity,name=self._text(event["name"]),startTime=info.startTime,endTime=info.endTime,
                bannerAssetId=event["bannerAssetId"],order=order,unlockConditionId=info.unlockConditionId,
                isUnlocked=info.isUnlocked,isLessonRewardMax=info.isLessonRewardMax,
                isUnplayed=info.isUnplayed,hasHiddenFavorabilityObtainItem=info.hasHiddenFavorabilityObtainItem,
                baseType=info.baseType,limitedExtraTitleAssetId=event.get("titleAssetId","") if info.baseType==2 else "")
            row.eventMissionIds.extend(info.eventMissionIds);row.limitedEventMissionIds.extend(info.limitedEventMissionIds)
            entries.append(row)
            # Local navigation policy: the ordinary Love button opens the
            # original STANDARD Title/character picker. Extra has its own
            # TitleExtra entry; an Extra-only schedule must not open an empty
            # standard picker. No claim of an observed server aggregate rule.
            if info.baseType == 1:
                overall.isViewable = True
                overall.isUnlocked = overall.isUnlocked or info.isUnlocked
                if not overall.unlockConditionId:overall.unlockConditionId = info.unlockConditionId
                overall.existsLessonRewardMaxLove |= info.isLessonRewardMax
                overall.existsUnplayedLove |= info.isUnplayed
                overall.existsHasHiddenFavorabilityObtainItemLove |= info.hasHiddenFavorabilityObtainItem
                for mission in info.eventMissionIds:
                    if mission not in overall.eventMissionIds:overall.eventMissionIds.append(mission)
        return overall,entries

    def _mutate(self, identity, event, result, operation, now, *, registering=False):
        def callback(snapshot_raw, progress_raw):
            snapshot = self._parse(snapshot_raw)
            original_snapshot = snapshot.SerializeToString()
            if not self._unlocked(snapshot,event):
                _fail("event_locked",RpcCode.PERMISSION_DENIED)
            data = self._progress(progress_raw,identity,event) if progress_raw is not None else None
            original_data = copy.deepcopy(data)
            love = self._love(snapshot,identity)
            if registering:
                if data is not None:
                    _fail("already_registered",RpcCode.ALREADY_EXISTS)
                if love is not None and not self.media_mode:
                    _fail("imported_progress_unavailable")
            elif data is None or love is None:
                _fail("registration_required")
            if data is not None and bool(data["current"]) != love.isReadingStory:
                _fail("reading_state_inconsistent")
            updated = result.commonResponse.updatedData
            updated.SetInParent()
            data,love = operation(snapshot,data,love,updated)
            if (not -(1<<63) <= love.hiddenFavorability <= _I64
                    or not self.media_mode and set(love.unlockedLoveStoryEndIDs)-{row["id"] for row in event["endings"]}):
                _fail("love_state_invalid")
            updated.loves.add().CopyFrom(love)
            self._references(data,event)
            encoded_snapshot = snapshot.SerializeToString()
            encoded_progress = progress_raw if progress_raw is not None and data == original_data else _encode_progress(data)
            return (snapshot_raw if encoded_snapshot == original_snapshot else encoded_snapshot),encoded_progress
        try:
            row = self.state.love_progress(self.profile,identity)
            ruleset = self._progress_ruleset(row)
            self.state.mutate_love_snapshot(self.profile,self.schema.fingerprint,identity,ruleset,callback)
        except ValueError:
            _fail("progress_unavailable_or_rules_changed")

    @staticmethod
    def _item_amount(snapshot, identity, now):
        rows = [row for row in snapshot.items if row.itemId == identity]
        if len({row.expiredTime for row in rows}) != len(rows) or any(row.amount < 0 or row.expiredTime < 0 for row in rows):
            _fail("item_state_invalid")
        return sum(row.amount for row in rows if not row.expiredTime or now < row.expiredTime)

    def _consume(self, snapshot, identity, amount, updated, now):
        if not _id(identity) or not _integer(amount):
            _fail("item_definition_invalid")
        if self._item_amount(snapshot,identity,now) < amount:
            _fail("item_insufficient",RpcCode.RESOURCE_EXHAUSTED)
        remaining = amount
        for row in sorted((r for r in snapshot.items if r.itemId==identity and (not r.expiredTime or now<r.expiredTime)),
                          key=lambda r:(r.expiredTime==0,r.expiredTime)):
            count = min(remaining,row.amount)
            if count:
                row.amount-=count;remaining-=count;updated.items.add().CopyFrom(row)
            if not remaining:break

    def _grant_item(self,snapshot,identity,amount,updated):
        if not amount:return
        rows = [row for row in snapshot.items if row.itemId==identity and row.expiredTime==0]
        if len(rows)>1 or rows and (rows[0].amount<0 or rows[0].amount>_I64-amount):
            _fail("item_amount_overflow",RpcCode.OUT_OF_RANGE)
        row = rows[0] if rows else snapshot.items.add(itemId=identity)
        row.amount+=amount;updated.items.add().CopyFrom(row)

    def _condition_matches(self, conditions, episode, choices):
        for condition in conditions:
            if set(condition)-{"episode","group","choice"}:
                _fail("branch_unsupported",RpcCode.UNIMPLEMENTED)
            key = condition.get("episode",episode)
            matches = [row for row in choices.get(key,[]) if row["group"]==condition["group"] and row["valid"]]
            if not matches or matches[0]["index"] != condition["choice"]:return False
        return True

    def _route_points(self,event,choices):
        total=0
        for episode,rows in choices.items():
            groups={row["index"]:row for row in event["routes"][episode].get("groups",[])}
            for row in rows:
                if row["valid"]:
                    values=groups[row["group"]].get("points",[])
                    if values:total+=values[row["index"]-1]
        if not -(1<<63)<=total<=_I64:_fail("route_score_overflow",RpcCode.OUT_OF_RANGE)
        return total

    def _choice_response(self,result,event,data,episode,hint):
        route=event["routes"][episode]
        for group in route.get("groups",[]):
            row=result.storyChoiceGroupInfos.add(groupIndex=group["index"])
            row.existsObtainableFavorabilityDifference=hint>=1 and group.get("best",0)>0
            past=data["past_choices"].get(episode,{}).get(str(group["index"]),[])
            for index in range(1,group["count"]+1):
                row.storyChoiceInfos.add(index=index,isBestObtainableFavorability=hint>=2 and index==group.get("best",0),
                                        isPastSelected=index in past)
        for branch in route.get("branches",[]):
            if set(branch)-{"group","match","otherwise","all"}:_fail("branch_unsupported",RpcCode.UNIMPLEMENTED)
            result.advBranchInfos.add(groupIndex=branch["group"],index=branch["match"] if self._condition_matches(
                branch.get("all",[]),episode,data["choices"]) else branch["otherwise"])

    def _select(self,event,data,episode,request):
        route=event["routes"][episode]
        groups={row["index"]:row for row in route.get("groups",[])}
        selected={}
        if len(request.selectStoryChoiceInfos)>4096:_fail("choice_invalid",RpcCode.INVALID_ARGUMENT)
        for row in request.selectStoryChoiceInfos:
            if row.groupIndex not in groups or not 1<=row.index<=groups[row.groupIndex]["count"]:
                _fail("choice_invalid",RpcCode.INVALID_ARGUMENT)
            # The original client also echoes old alternatives as isValid=false.
            # Validate their identities but do not treat history as an active
            # route choice or reject a later valid choice for the same group.
            if not row.isValid:continue
            if row.groupIndex in selected:_fail("choice_invalid",RpcCode.INVALID_ARGUMENT)
            selected[row.groupIndex]={"group":row.groupIndex,"index":row.index,"valid":True}
        # Evaluate conditional groups against earlier selections in this very
        # request as well as preserved earlier episodes, never trust isValid.
        trial=copy.deepcopy(data["choices"]);trial[episode]=list(selected.values())
        for index,group in groups.items():
            required=self._condition_matches(group.get("requires",[]),episode,trial)
            row=selected.get(index)
            if required and (row is None or not row["valid"]) or not required and row is not None and row["valid"]:
                _fail("choice_path_invalid",RpcCode.INVALID_ARGUMENT)
        return [selected[key] for key in sorted(selected)]

    def _resolve(self,event,episode,choices):
        route=event["routes"][episode];points=self._route_points(event,choices)
        for outcome in route.get("outcomes",[]):
            if set(outcome)-{"all","next","ending","minPoints","maxPoints"}:
                _fail("branch_unsupported",RpcCode.UNIMPLEMENTED)
            if (self._condition_matches(outcome.get("all",[]),episode,choices)
                    and ("minPoints" not in outcome or points>=outcome["minPoints"])
                    and ("maxPoints" not in outcome or points<=outcome["maxPoints"])):
                return outcome.get("next"),outcome.get("ending")
        if route.get("next"):return route["next"],None
        _fail("branch_unresolved",RpcCode.UNIMPLEMENTED)

    def _episode_event(self,episode,now):
        matches=[(identity,event) for identity,event in self._load()["events"].items() if episode in event["episodes"]]
        if len(matches)!=1:_fail("episode_unknown",RpcCode.NOT_FOUND)
        identity,event=matches[0];self._event(identity,now)
        return identity,event

    def _start(self,event,data,love,snapshot,result,request,now,updated,restart):
        episode=request.storyEpisodeId
        if event["episodes"][episode].get("advEvidence",{}).get("available") is False:
            _fail("adv_evidence_unavailable",RpcCode.UNIMPLEMENTED)
        if episode not in data["path"]:_fail("episode_not_on_route")
        level=self._level(event,data["exp"])["level"]
        number=event["episodes"][episode]["episode"]
        required=event["episodeUnlockLevels"].get(str(number),event["episodeUnlockLevels"].get(number))
        if required is None or not self.media_mode and level<required:_fail("episode_level_locked")
        unlocked_hint=self._hint(event,data,request.hintLevel)
        if data["current"] and data["current"]["episode_id"]!=episode:_fail("different_episode_active")
        if restart and not data["current"]:_fail("episode_not_active")
        if not data["current"]:
            cost=self._number(event["episodes"][episode].get("consumptionItemAmount",0))
            if {row["id"] for row in event["endings"]} <= set(love.unlockedLoveStoryEndIDs):cost=0
            if cost and not self.media_mode:self._consume(snapshot,event["storyReadItemId"],cost,updated,now)
        data["current"]={"episode_id":episode,"hint":request.hintLevel}
        data["last_play_ms"]=now;love.isReadingStory=True
        # Return metadata for all unlocked hint levels so the original client
        # can change its local hint display while ADV is already playing.
        self._choice_response(result,event,data,episode,unlocked_hint)

    def _finish(self,event,data,love,snapshot,result,request,now,updated):
        episode=request.storyEpisodeId
        if data["current"] is None or data["current"]["episode_id"]!=episode:_fail("episode_not_active")
        self._hint(event,data,request.hintLevel)
        selected=self._select(event,data,episode,request)
        position=data["path"].index(episode)
        data["path"]=data["path"][:position+1]
        data["choices"]={key:rows for key,rows in data["choices"].items() if key in data["path"][:-1]}
        data["choices"][episode]=selected
        next_id,end_id=self._resolve(event,episode,data["choices"])
        past=data["past_choices"].setdefault(episode,{})
        for row in selected:
            if row["valid"]:
                seen=past.setdefault(str(row["group"]),[])
                if row["index"] not in seen:seen.append(row["index"])
        if end_id:
            matches=[row for row in event["endings"] if row["id"]==end_id]
            if len(matches)!=1:_fail("ending_unsupported",RpcCode.UNIMPLEMENTED)
            ending=matches[0]
            result.storyEndName=self._text(ending["name"]);result.endRollAssetId=ending.get("endRollAssetId","")
            if end_id not in love.unlockedLoveStoryEndIDs:
                # Inferred first-ending favorability is metadata only. It is
                # not accrued to actual account state without official proof.
                result.unlockSave=not love.unlockedLoveStoryEndIDs
                love.unlockedLoveStoryEndIDs.append(end_id)
            data["path"]=[self._first(event)];data["choices"]={}
        else:
            if (next_id not in event["episodes"] or next_id not in event["routes"]
                    or event["episodes"][next_id].get("advEvidence",{}).get("available") is False
                    or next_id in data["path"]):
                _fail("branch_unsupported",RpcCode.UNIMPLEMENTED)
            data["path"].append(next_id)
        # Both inferred choice and ending scores stay outside UserLove's
        # real affinity. Finishing still records actual seen story/end IDs.
        love.isReadingStory=False
        data["current"]=None;data["last_play_ms"]=now
        story=event["episodes"][episode]["storyId"]
        rows=[row for row in snapshot.stories if row.storyId==story]
        if len(rows)>1:_fail("story_state_ambiguous")
        target=rows[0] if rows else snapshot.stories.add(storyId=story)
        target.statusType=2;updated.stories.add().CopyFrom(target)

    def _top(self,result,snapshot,event,data,love):
        result.loveName=self._text(event["name"]);result.playerName=data["player_name"];result.exp=data["exp"]
        self._lesson_progress(result.lessonProgress,event,data)
        result.storyEpisodeIds.extend(data["path"])
        result.saveInfo.unlocked=self.media_mode or bool(love.unlockedLoveStoryEndIDs)
        for save in sorted(data["saves"],key=lambda row:row["slot"]):
            result.saveInfo.saveDataInfos.add(slotNumber=save["slot"],saveTime=save["saved_ms"],
                latestStoryEpisodeId=save["path"][-1],name=save["name"])
        result.itemInfo.storyReadItemId=event["storyReadItemId"]
        result.itemInfo.hiddenFavorabilityObtainItemId=event.get("presentItemId","")
        result.itemInfo.lessonPromoteItemId=event["promoteItemId"]
        result.hiddenFavorability=max(0,love.hiddenFavorability)
        for end in event["endings"]:
            result.storyEndInfos.add(id=end["id"],name=self._text(end["name"]),unlocked=self.media_mode or end["id"] in love.unlockedLoveStoryEndIDs)
        level=self._level(event,data["exp"])["level"]
        for row in event["levels"]:
            if row["level"]>((level+5)//5)*5:continue
            info=result.loveLevelInfos.add(level=row["level"],isTextViewable=row["level"]<=level+1)
            for number,required in event["episodeUnlockLevels"].items():
                if required==row["level"]:info.unlockStoryEpisode=int(number)
            for hint,required in event["hintUnlockLevels"].items():
                if required==row["level"]:info.unlockLoveHintType=int(hint)
        result.bannerAssetId=event["bannerAssetId"];result.expAssetId=event.get("expAssetId","exp-"+event["loveId"])
        result.loveSimpleName=self._text(event.get("simpleName",""));result.mainCharacterInfo.CopyFrom(self._main_character(event))
        result.noticeInfo.SetInParent()
        groups=self.catalog.ids("EventMission")
        users={row.missionId:row for row in snapshot.missions}
        for field,ids in ((result.eventMissionInfos,event.get("eventMissionIds",[])),
                          (result.limitedEventMissionInfos,event.get("limitedEventMissionIds",[]))):
            for identity in ids:
                if identity not in groups:_fail("mission_catalog_missing")
                entry=field.add(id=identity,unlocked=False)
                # Existing task rows may be inspected; unsupported task reward
                # eligibility is kept locked until its separate API is restored.
                entry.userMissions.extend(users[key] for key in groups[identity].get("missionIds",[]) if key in users)

    def _lesson(self,result,snapshot,event,data,updated,now,promote):
        if self.media_mode:
            if promote:_fail("media_has_no_item_actions")
            data["lesson_anchor_ms"]=max(now,data["lesson_anchor_ms"])
            result.obtainExp=0;result.totalExp=data["exp"]
            self._lesson_progress(result.lessonProgress,event,data)
            return
        step=self._number(event.get("lessonStepSeconds"),minimum=1)*1000
        if step>3600000:_fail("lesson_step_unsupported")
        if promote:
            identity=event["promoteItemId"]
            item=self.catalog.ids("Item",required=True).get(identity)
            if item is None or item.get("type")!=9003:_fail("promote_item_invalid")
            steps=self._number(item.get("value"),minimum=1)*60000//step
            if not 0<steps<=8640:_fail("promote_duration_unsupported")
            self._consume(snapshot,identity,1,updated,now)
            day=_day(now)
            data["promotion_used"]=data["promotion_used"]+1 if data["promotion_day"]==day else 1
            data["promotion_day"]=day
        else:
            window=self._number(event["lessonMaxHours"],minimum=1)*3600000
            elapsed=max(0,min(now,data["lesson_anchor_ms"]+window)-data["lesson_anchor_ms"])
            steps=elapsed//step
            if steps>8640:_fail("lesson_duration_unsupported")
            if now>=data["lesson_anchor_ms"]:
                data["lesson_anchor_ms"]=now-(now-data["lesson_anchor_ms"])%step
        # One claim uses the master rates at its PRE-claim level, including
        # claims that cross a level. requiredExp is a level threshold, not an
        # invented cap on accumulated experience. This also keeps work O(1).
        before=data["exp"];row=self._level(event,before)
        experience=steps*self._number(row.get("lessonStepRewardExp",0))
        earned=steps*self._number(row.get("lessonStepRewardStoryReadItemAmount",0))
        if experience>_I64-before or earned>_I64:_fail("lesson_reward_overflow",RpcCode.OUT_OF_RANGE)
        data["exp"]+=experience
        self._grant_item(snapshot,event["storyReadItemId"],earned,updated)
        if earned:result.rewards.add(resourceType=1,resourceId=event["storyReadItemId"],amount=earned)
        result.obtainExp=experience;result.totalExp=data["exp"]
        self._lesson_progress(result.lessonProgress,event,data)

    def handle(self,path,request_bytes):
        if path not in ROUTES:return None
        now=self._now();active=self._active(now)
        if not active:_fail("event_disabled_or_outside_period")
        if path not in self.schema.methods:_fail("schema_unsupported",RpcCode.UNIMPLEMENTED)
        try:
            request=self.schema.request_type(path).FromString(request_bytes)
        except (DecodeError,UnicodeError,TypeError):
            _fail("request_invalid",RpcCode.INVALID_ARGUMENT)
        result=self.schema.response_type(path)()
        name=path[len(_PREFIX):]
        if name in ("Title","TitleExtra"):
            snapshot=self._snapshot();plan=self._load()
            if name=="Title":
                for identity,schedule in sorted(active.items()):
                    event=self._event(identity,now)
                    if event.get("baseType",1)==1:result.loveInfos.add().CopyFrom(self._info(snapshot,identity,event,schedule,now))
            else:
                identity=request.loveId;event=self._event(identity,now)
                if event.get("baseType",1)!=2:_fail("extra_title_required",RpcCode.INVALID_ARGUMENT)
                result.loveInfo.CopyFrom(self._info(snapshot,identity,event,active[identity],now))
                result.titleAssetId=event["titleAssetId"]
            result.commonResponse.updatedData.SetInParent()
            return result.SerializeToString()
        if name in ("Start","Restart","Finish"):
            identity,event=self._episode_event(request.storyEpisodeId,now)
        else:
            identity=request.loveId;event=self._event(identity,now)
        def operation(snapshot,data,love,updated):
            if name=="Register":
                data=self._new(identity,event,self._name(request.name),now)
                love=self._love(snapshot,identity,create=True)
                love.isReadingStory=False
            elif name=="Top":
                data["last_play_ms"]=now;self._top(result,snapshot,event,data,love)
            elif name in ("Start","Restart"):
                self._start(event,data,love,snapshot,result,request,now,updated,name=="Restart")
            elif name=="Finish":
                self._finish(event,data,love,snapshot,result,request,now,updated)
            elif name=="ResetReadingStoryStatus":
                data["current"]=None;love.isReadingStory=False
            elif name=="Present":
                if self.media_mode:_fail("media_has_no_item_actions")
                present=event.get("presentItemId")
                master=self.catalog.ids("Item",required=True).get(present)
                if master is None or master.get("type")!=9002:_fail("present_unavailable")
                value=self._number(master.get("value"),minimum=1)
                if love.hiddenFavorability>_I64-value:_fail("favorability_overflow",RpcCode.OUT_OF_RANGE)
                self._consume(snapshot,present,1,updated,now)
                love.hiddenFavorability+=value;result.hiddenFavorability=max(0,love.hiddenFavorability)
            elif name in ("Save","UpdateSaveName","Load"):
                slots=event.get("saveSlotCount")
                if not _integer(slots,10,1):_fail("save_policy_invalid")
                if not self.media_mode and not love.unlockedLoveStoryEndIDs:_fail("save_locked")
                if not 1<=request.slotNumber<=slots:_fail("save_slot_invalid",RpcCode.INVALID_ARGUMENT)
                if data["current"]:_fail("finish_reading_first")
                matches=[row for row in data["saves"] if row["slot"]==request.slotNumber]
                saved=matches[0] if matches else None
                if name=="Save":
                    value={"slot":request.slotNumber,"name":saved["name"] if saved else "","saved_ms":now,
                           "path":copy.deepcopy(data["path"]),"choices":copy.deepcopy(data["choices"])}
                    if saved:data["saves"].remove(saved)
                    data["saves"].append(value)
                elif saved is None:_fail("save_not_found",RpcCode.NOT_FOUND)
                elif name=="UpdateSaveName":saved["name"]=self._name(request.name)
                else:
                    data["path"]=copy.deepcopy(saved["path"]);data["choices"]=copy.deepcopy(saved["choices"])
                    result.storyEpisodeIds.extend(data["path"])
            elif name=="Reset":
                if data["current"]:_fail("finish_reading_first")
                data["path"]=[self._first(event)];data["choices"]={};result.storyEpisodeIds.extend(data["path"])
            elif name in ("ReceiveLessonReward","PromoteLesson"):
                self._lesson(result,snapshot,event,data,updated,now,name=="PromoteLesson")
            elif name=="UpdateName":data["player_name"]=self._name(request.name)
            elif name=="GetMainCharacter":result.mainCharacterInfo.CopyFrom(self._main_character(event))
            else:_fail("method_unsupported",RpcCode.UNIMPLEMENTED)
            return data,love
        self._mutate(identity,event,result,operation,now,registering=name=="Register")
        return result.SerializeToString()
