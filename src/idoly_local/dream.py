"""Read-only image-training entry for one preserved public Dream period.

No photo, generated area, mission, manual, reward or clock is changed here.
Official generated areas are separate from User.Get; a trained base without
that state must not be displayed as a newly generated or cleared area.
"""
from __future__ import annotations

import json
from pathlib import Path
import time

from google.protobuf import message_factory
from google.protobuf.message import DecodeError

from .gameplay import _Catalog
from .rpc import RpcCode, RpcFailure
from .dream_capture import (HOME, MATERIAL, QUEST, READS, load_dream_catalog,
                            sanitized_response)

SCHEMA_SHA256 = "0fcf90596261dcd9bbed165bd93859dc30127e2a494e6529bafbd8885675edf3"
MASTER_VERSION = "961e456499039e31248a818a911c8d95f92461f86aff4674ba07e29c32afcf60"
_TOP, _USER = "/api.Dream/Top", "/api.User/Get"
_SOURCE = {
    "repository": "Project-Hoshimi/sumire-sr-data",
    "commit": "c40ea107b9cc8e53ae1705f82a5c39cc9fe3be02",
    "path": "captures/2026-10-25_fresh_official/raw/00033.resp-plain.Home%3AEnter.bin",
    "sha256": "d956979f9d04a6a69ffc640ba6c2650f5bc7f34ece0236b466b37bdfcee5a193",
    "field": "eventInfo.dreamInfo",
}
_HOME = {
    "startTime": 1792033200000, "endTime": 1794711599000,
    "assetId": "event-dream-defalut", "bannerAssetId": "img_banner_l_event-dream-defalut",
    "order": 60, "unlockConditionId": "cd-dream-25-0320-play",
    "generateAreaItemId": "item-dream-generate-dream-25-0320",
    "eventMissionId": "event-dream-26-10",
}
_CONDITIONS = {
    "cd-dream-25-0320-play": [{"satisfyCondition": {"conditionId": "cd-clear-area-main-016"},
                              "term": {"nowAfter": "1742439600000", "nowBefore": "0"}}],
    "cd-clear-area-main-016": [{"clearArea": {"areaId": "area-main-016"}}],
    "cd-time-dream-26-10": [{"term": {"nowAfter": "1792033200000", "nowBefore": "1794711599000"}}],
}


def _need(ok, detail):
    if not ok:
        raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Dream read-only entry: " + detail)


class Dream:
    """Expose preserved metadata and owned photos, without generation support."""

    def __init__(self, schema, state, profile, master_dir, *, catalog_path=None,
                 capture_catalog_path=None, clock=None):
        self.schema, self.state, self.profile = schema, state, profile
        self.catalog = _Catalog(master_dir)
        self.catalog_path = (Path(catalog_path) if catalog_path is not None else
                             Path(master_dir).parent / "dream-catalog.json" if master_dir is not None else None)
        self.capture_catalog_path = (Path(capture_catalog_path) if capture_catalog_path is not None else
                             Path(master_dir).parent / "dream-private-catalog.json" if master_dir is not None else None)
        self.clock = clock if clock is not None else lambda: time.time_ns() // 1000000

    def _admit_master(self):
        version = self.catalog.version()
        if version == MASTER_VERSION: return
        from .live_input import _LATEST_MASTER_VERSION
        _need(version == _LATEST_MASTER_VERSION, "master version differs")
        from .public_cohort_support import require_master_cohort
        try: require_master_cohort(self.catalog.directory, "dream")
        except (OSError, ValueError): _need(False, "latest public master cohort is unapproved or changed")

    def _condition_matches(self, row, expected):
        if self.catalog.version() == MASTER_VERSION:
            return row.get("settings") == expected
        from .live_input import _master_message
        actual = _master_message(self.schema,"Condition",row)
        wanted = _master_message(self.schema,"Condition",{"id":row["id"],"settings":expected})
        return list(actual.settings) == list(wanted.settings)

    def _private(self, snapshot):
        if self.capture_catalog_path is None or not self.capture_catalog_path.exists():
            return None
        self._admit_master()
        profile = self.state.profile(self.profile)
        _need(profile is not None and snapshot.HasField("userPublic")
              and (profile["server_id"], profile["public_id"]) ==
              (snapshot.userPublic.serverUserId, snapshot.userPublic.publicUserId), "private capture owner differs")
        return load_dream_catalog(self.schema, self.capture_catalog_path,
            master_version=self.catalog.version(), snapshot=snapshot, now_ms=self.clock())

    def _private_definition(self):
        # A private capture supplies seasonal data independently of the public
        # October fixture. Its original area-16 unlock still comes from master.
        conditions = self.catalog.ids("Condition", required=True)
        for identity in ("cd-dream-25-0320-play", "cd-clear-area-main-016"):
            _need(identity in conditions and self._condition_matches(conditions[identity], _CONDITIONS[identity]),
                  "private capture unlock condition differs")
        area = self.catalog.ids("Area", required=True).get("area-main-016")
        _need(area is not None and isinstance(area.get("questIds"), list) and bool(area["questIds"])
              and all(type(key) is str and bool(key) for key in area["questIds"])
              and len(area["questIds"]) == len(set(area["questIds"])), "private capture unlock area is absent")
        quests = self.catalog.ids("Quest", required=True)
        _need(all(key in quests and quests[key].get("areaId") == "area-main-016" for key in area["questIds"]),
              "private capture unlock quests differ")
        return None, area

    def _private_masters(self, parsed):
        def present(table, identity):
            # Chart patterns/advantages/bonus groups intentionally have many
            # rows sharing one ID. _Catalog.ids is only for unique-ID tables.
            key = "groupId" if table == "LiveBonusGroup" else "id"
            return any(row.get(key) == identity for row in self.catalog.rows(table, required=True))

        home, top = parsed[HOME][1].eventInfo.dreamInfo, parsed[_TOP][1]
        _need(home.unlockConditionId == "cd-dream-25-0320-play"
              and top.seasonInfo.generateAreaItemId in self.catalog.ids("Item", required=True),
              "private capture season references differ")
        ability_refs = [value.photoAbilityId for row in top.dreamUserPhotos for value in row.abilities]
        for key, (_, response) in parsed.items():
            if isinstance(key, tuple) and key[0] == MATERIAL:
                ability_refs.extend(value.photoAbilityId for row in response.userMaterialPhotos
                                    for value in row.enhancePlanAbilities)
            elif isinstance(key, tuple) and key[0] == QUEST:
                ability_refs.extend(value.photoAbilityId for row in response.questInfos
                                    for value in row.userPhotoAbilityUpInfos)
        abilities = self.catalog.ids("PhotoAbility", required=bool(ability_refs))
        _need(all(identity in abilities for identity in ability_refs), "private capture photo ability differs")
        for key, (_, response) in parsed.items():
            if isinstance(key, tuple) and key[0] == QUEST:
                for quest in response.questInfos:
                    for table, field in (("Stage", "stageId"), ("Music", "musicId"),
                        ("MusicChartPattern", "musicChartPatternId"), ("QuestPressure", "questPressureId"),
                        ("QuestAudienceAdvantage", "questAudienceAdvantageId")):
                        _need(bool(getattr(quest, field)) and present(table, getattr(quest, field)),
                              "private capture quest master differs")
                    for table, field in (("QuestCharacterAdvantage", "questCharacterAdvantageId"),
                                         ("LiveBonusGroup", "liveBonusGroupId")):
                        identity = getattr(quest, field)
                        _need(not identity or present(table, identity),
                              "private capture quest master differs")

    def _definition(self):
        if self.catalog_path is None or not self.catalog_path.is_file():
            return None
        try:
            raw = self.catalog_path.read_bytes()
            _need(len(raw) <= 65536, "catalog is oversized")
            saved = json.loads(raw)
        except (OSError, ValueError):
            raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Dream read-only entry: invalid catalog") from None
        _need(isinstance(saved, dict) and set(saved) == {
            "schema", "catalog_id", "schema_sha256", "master_version", "source", "home"}, "catalog shape differs")
        _need(type(saved["schema"]) is int and saved["schema"] == 1
              and saved["catalog_id"] == "public-dream-2026-10", "catalog version differs")
        _need(self.schema.fingerprint == SCHEMA_SHA256 and saved["schema_sha256"] == SCHEMA_SHA256,
              "schema differs")
        self._admit_master()
        _need(saved["master_version"] == self.catalog.version(), "master version differs")
        _need(saved["source"] == _SOURCE and saved["home"] == _HOME, "public source or projection differs")
        _need(all(type(saved["home"][key]) is int for key in ("startTime", "endTime", "order")),
              "time or ordering type differs")
        settings = self.catalog.rows("Setting", required=True)
        _need(len(settings) == 1 and settings[0].get("dreamAreaName") == "イメージトレーニング"
              and type(settings[0].get("dreamGenerateAreaBasePhotoRequiredRarity")) is int
              and settings[0]["dreamGenerateAreaBasePhotoRequiredRarity"] == 4, "Dream setting differs")
        _need(_HOME["generateAreaItemId"] in self.catalog.ids("Item", required=True), "manual master is missing")
        conditions = self.catalog.ids("Condition", required=True)
        for identity, expected in _CONDITIONS.items():
            _need(identity in conditions and self._condition_matches(conditions[identity], expected),
                  "preserved condition differs")
        event = self.catalog.ids("EventMission", required=True).get(_HOME["eventMissionId"])
        _need(event is not None and event.get("viewConditionId") == "cd-time-dream-26-10"
              and event.get("unlockConditionId") == _HOME["unlockConditionId"]
              and event.get("assetId") == _HOME["bannerAssetId"], "monthly mission references differ")
        area = self.catalog.ids("Area", required=True).get("area-main-016")
        _need(area is not None and type(area.get("type")) is int and area["type"] == 1
              and isinstance(area.get("questIds"), list) and bool(area["questIds"])
              and all(isinstance(key, str) and key for key in area["questIds"])
              and len(area["questIds"]) == len(set(area["questIds"])),
              "unlock area master is missing or ambiguous")
        quests = self.catalog.ids("Quest", required=True)
        _need(all(key in quests and quests[key].get("areaId") == area["id"] for key in area["questIds"]),
              "unlock area quest references differ")
        return settings[0], area

    def _snapshot(self):
        saved = self.state.snapshot(self.profile)
        _need(saved is not None and saved[1] == self.schema.fingerprint, "snapshot or schema is unavailable")
        try:
            snapshot = self.schema.response_type(_USER).FromString(saved[0])
        except (DecodeError, UnicodeError):
            raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Dream read-only entry: malformed snapshot") from None
        _need(snapshot.HasField("user"), "local user state is absent")
        return snapshot

    def _unlocked(self, snapshot, definition):
        now = self.clock()
        _need(type(now) is int and now >= 0, "local clock is unavailable")
        rows = [row for row in snapshot.areas if row.areaId == "area-main-016"]
        _need(len(rows) <= 1, "unlock area state is ambiguous")
        if not rows:
            return False
        row = rows[0]
        _need(row.clearQuestCount >= 0 and row.lastClearedTime >= 0, "unlock area state is invalid")
        return now >= 1742439600000 and row.clearQuestCount >= len(definition[1]["questIds"])

    def home_info(self, snapshot=None):
        """Return a fresh safe DTO, or None for an older payload without this catalog.

        Its period remains the observed October period, including after expiry.
        This neither creates a November season nor rewrites the global clock.
        """
        if ((self.capture_catalog_path is None or not self.capture_catalog_path.exists())
                and (self.catalog_path is None or not self.catalog_path.is_file())):
            return None
        snapshot = snapshot if snapshot is not None else self._snapshot()
        _need(isinstance(snapshot, self.schema.response_type(_USER)) and snapshot.HasField("user"),
              "snapshot type differs")
        private = self._private(snapshot)
        if private is not None:
            self._private_masters(private)
            definition = self._private_definition()
            source = private[HOME][1].eventInfo.dreamInfo
            info = type(source)()
            info.CopyFrom(source)
            info.DiscardUnknownFields()
            info.name = private[_TOP][1].seasonInfo.name
            info.isUnlocked = self._unlocked(snapshot, definition)
            info.isReceivableLoginReward = False
            return info
        definition = self._definition()
        if definition is None:
            return None
        _need(isinstance(snapshot, self.schema.response_type(_USER)) and snapshot.HasField("user"),
              "snapshot type differs")
        cls = message_factory.GetMessageClass(self.schema.pool.FindMessageTypeByName("api.HomeDreamInfo"))
        info = cls(name=definition[0]["dreamAreaName"], **_HOME)
        info.isUnlocked = self._unlocked(snapshot, definition)
        # isReceivableLoginReward stays false: no monthly grant was implemented.
        return info

    def handle(self, path, plain):
        if path not in READS or path not in self.schema.methods:
            return None
        if ((self.capture_catalog_path is None or not self.capture_catalog_path.exists())
                and (self.catalog_path is None or not self.catalog_path.is_file())):
            return None
        try:
            request = self.schema.request_type(path).FromString(plain)
        except (DecodeError, UnicodeError):
            raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Malformed Dream read request") from None
        snapshot = self._snapshot()
        private = self._private(snapshot)
        if private is not None:
            definition = self._private_definition()
            _need(self._unlocked(snapshot, definition), "image training remains locked until main area 16 is cleared")
            self._private_masters(private)
            key = path if path == _TOP else (path, request.basePhotoId)
            _need(key in private, "requested photo read was not preserved")
            return sanitized_response(private[key][1]).SerializeToString()
        if path != _TOP:
            return None
        definition = self._definition()
        if definition is None:
            return None
        _need(self._unlocked(snapshot, definition), "image training remains locked until main area 16 is cleared")
        info = self.home_info(snapshot)
        result = self.schema.response_type(path)()
        result.seasonInfo.name = info.name
        result.seasonInfo.startTime, result.seasonInfo.endTime = info.startTime, info.endTime
        result.seasonInfo.generateAreaItemId, result.seasonInfo.assetId = info.generateAreaItemId, info.assetId
        # Season ID, rank colours and notices are absent from the preserved
        # Home DTO. Do not synthesize them from another server's balancing.
        seen = set()
        for photo in snapshot.photos:
            _need(bool(photo.photoId) and photo.photoId not in seen and photo.rarity >= 0 and photo.level >= 0,
                  "owned photo state is invalid or ambiguous")
            seen.add(photo.photoId)
            _need(not photo.isDreamBase, "generated base needs its captured private Dream area state")
            if photo.rarity >= 4:
                result.dreamUserPhotos.add(photoId=photo.photoId, isDisableGenerateArea=True)
        # No monthly mission rows, login gift, generated area or photo growth is
        # invented. Missing eventMissionInfo explicitly hides the client button.
        result.commonResponse.SetInParent()
        return result.SerializeToString()


def audit_latest_dream_semantics(schema, legacy_master_dir, latest_all_master_dir):
    """Prove preserved October controls only; never create optional Dream data."""
    from .live_input import (_AuditCatalog, _LATEST_MASTER_VERSION, _audit_need, _audit_equal,
        _audit_wire, _audit_conditions, _audit_receipt, _master_message, LatestSemanticsError)
    scope = "dream"
    try:
        _audit_need(schema.fingerprint == SCHEMA_SHA256,scope,"schema_changed")
        old=_AuditCatalog(schema,legacy_master_dir,MASTER_VERSION,scope)
        latest=_AuditCatalog(schema,latest_all_master_dir,_LATEST_MASTER_VERSION,scope)
        settings=[]
        for catalog in (old,latest):
            rows=catalog.rows("Setting",required=True)
            _audit_need(len(rows)==1 and rows[0].get("dreamAreaName")=="イメージトレーニング"
                        and type(rows[0].get("dreamGenerateAreaBasePhotoRequiredRarity")) is int
                        and rows[0]["dreamGenerateAreaBasePhotoRequiredRarity"]==4,scope,"dream_setting_changed")
            settings.append({key:rows[0][key] for key in ("dreamAreaName","dreamGenerateAreaBasePhotoRequiredRarity")})
            conditions=catalog.ids("Condition",required=True)
            for identity,expected in _CONDITIONS.items():
                row=conditions.get(identity)
                _audit_need(row is not None,scope,"dream_condition_changed")
                actual=_master_message(schema,"Condition",row)
                wanted=_master_message(schema,"Condition",{"id":identity,"settings":expected})
                _audit_need(list(actual.settings)==list(wanted.settings),scope,"dream_condition_changed")
        _audit_need(settings[0]==settings[1],scope,"dream_setting_changed")
        first=_audit_conditions(old,_CONDITIONS);second=_audit_conditions(latest,_CONDITIONS)
        _audit_equal(schema,"Condition",first,second,scope,"dream_condition_changed")
        projection={"source":_SOURCE,"home":_HOME,"settings":settings[0],"conditions":_audit_wire(schema,"Condition",first)}
        for table,identity,reason in (("Item",_HOME["generateAreaItemId"],"dream_manual_changed"),
                                      ("EventMission",_HOME["eventMissionId"],"dream_mission_changed"),
                                      ("Area","area-main-016","dream_area_changed")):
            a,b=old.ids(table,required=True).get(identity),latest.ids(table,required=True).get(identity)
            _audit_need(a is not None and b is not None,scope,reason)
            _audit_equal(schema,table,[a],[b],scope,reason)
            projection[table]=_audit_wire(schema,table,[a])
        event=latest.ids("EventMission")[_HOME["eventMissionId"]]
        _audit_need(event.get("viewConditionId")=="cd-time-dream-26-10"
                    and event.get("unlockConditionId")==_HOME["unlockConditionId"]
                    and event.get("assetId")==_HOME["bannerAssetId"],scope,"dream_mission_changed")
        area=latest.ids("Area")["area-main-016"]
        quests=area.get("questIds")
        _audit_need(type(area.get("type")) is int and area["type"]==1 and type(quests) is list
                    and quests and len(set(quests))==len(quests),scope,"dream_area_changed")
        a,b=old.ids("Quest",required=True),latest.ids("Quest",required=True)
        _audit_need(all(key in a and key in b and a[key].get("areaId")==area["id"] and b[key].get("areaId")==area["id"] for key in quests),scope,"dream_quest_changed")
        _audit_equal(schema,"Quest",[a[key] for key in quests],[b[key] for key in quests],scope,"dream_quest_changed")
        projection["Quest"]=_audit_wire(schema,"Quest",[a[key] for key in quests])
        return _audit_receipt(scope,schema,old,latest,projection,{"public_source_preserved":True,
            "optional_capture_created":False,"period_changed":False,"condition_count":len(first),"area_16_quests":len(quests),
            "manual_changed":False,"mission_changed":False})
    except LatestSemanticsError: raise
    except Exception:
        raise LatestSemanticsError(scope,"input_invalid") from None
