"""Read/check the original 360 LIVE menu in an explicitly separate media mode.

Original Panorama uses PhotoPanorama.List/CheckShooting, not Photo.ListShooting
or the PhotoQuestMusic catalog. The caller must enable this provider only in
media mode. Conditions are intentionally bypassed there; no photo creation,
film use, account delta, live result or resource bytes are generated.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from types import MappingProxyType

from google.protobuf.message import DecodeError

from .appearance import _owned
from .gameplay import _Catalog
from .live_assets import _wearable
from .panorama_rules import MASTER_PANORAMA_RULES, MASTER_VERSION, PANORAMA_RULES, UNLOCK_CONDITION
from .rpc import RpcCode, RpcFailure


_USER = "/api.User/Get"
_LIST = "/api.PhotoPanorama/List"
_CHECK = "/api.PhotoPanorama/CheckShooting"
_ROUTES = frozenset((_LIST, _CHECK))


def _fail(message, code=RpcCode.FAILED_PRECONDITION):
    raise RpcFailure(code, message)


def _text(value):
    return isinstance(value, str) and bool(value)


@dataclass(frozen=True)
class MediaPanoramaScene:
    music_id: str
    stage_id: str
    asset_id: str
    order: int
    view_condition_id: str
    cast_count: int


def _projection(musics, stages):
    rules = (*PANORAMA_RULES, *MASTER_PANORAMA_RULES)
    music_rows = []
    for rule in rules:
        row = musics[rule.music_id]
        value = {key: row.get(key) for key in ("id", "assetId", "is360LiveExist", "displayCharacterAmount")}
        if rule in MASTER_PANORAMA_RULES:
            value.update(selectableStageIds=row.get("selectableStageIds"), releaseTime=str(row.get("releaseTime")))
        music_rows.append(value)
    stage_rows = []
    for identity in sorted({rule.stage_id for rule in rules}):
        row = stages[identity]
        stage_rows.append({"id": row["id"], "assetId": row.get("assetId"),
            "cameraPositions": [{key: position.get(key) for key in ("name", "index")}
                                for position in row["cameraPositions"]]})
    return {"schema": 1, "musics": music_rows, "stages": stage_rows}


def _latest_pin(catalog):
    from . import latest_cohort_pins as pins
    values = getattr(pins, "PROJECTION_SHA256", None)
    digest = values.get("panorama") if type(values) is dict else None
    if (catalog.version() != pins.MASTER_VERSION or type(digest) is not str or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)):
        _fail("The media 360 LIVE catalog needs its audited latest cohort")
    from .public_cohort_support import require_master_cohort
    try:
        require_master_cohort(catalog.directory, "panorama")
    except (OSError, ValueError):
        _fail("The media 360 LIVE catalog needs its audited latest cohort")
    return digest


def _prepare(catalog):
    latest_pin = _latest_pin(catalog) if catalog.version() != MASTER_VERSION else None
    musics, stages = catalog.ids("Music", required=True), catalog.ids("Stage", required=True)
    result, orders = {}, set()

    def add_scene(rule, view_condition_id):
        music, stage = musics.get(rule.music_id), stages.get(rule.stage_id)
        if (rule.music_id in result or type(rule.order) is not int or rule.order <= 0
                or rule.order in orders
                or music is None or type(music.get("is360LiveExist")) is not bool
                or not music["is360LiveExist"] or not _text(music.get("assetId"))
                or stage is None or not _text(stage.get("assetId"))):
            _fail("The media 360 LIVE catalog has an invalid public scene reference")
        cast_count, cameras = music.get("displayCharacterAmount"), stage.get("cameraPositions")
        if (type(cast_count) is not int or not 0 < cast_count <= 32
                or not isinstance(cameras, list) or not cameras
                or any(not isinstance(row, dict) or not _text(row.get("name"))
                       or type(row.get("index")) is not int or row["index"] < 0 for row in cameras)
                or len({row["index"] for row in cameras}) != len(cameras)):
            _fail("The media 360 LIVE scene lacks a valid cast or panorama camera")
        result[rule.music_id] = MediaPanoramaScene(rule.music_id, rule.stage_id, music["assetId"],
            rule.order, view_condition_id, cast_count)
        orders.add(rule.order)

    for rule in PANORAMA_RULES:
        if not _text(rule.view_condition_id):
            _fail("The factual 360 LIVE catalog has an invalid condition reference")
        add_scene(rule, rule.view_condition_id)
    for rule in MASTER_PANORAMA_RULES:
        music = musics.get(rule.music_id)
        if (music is None or music.get("selectableStageIds") != [rule.stage_id]
                or type(music.get("releaseTime")) not in (int, str)
                or str(music["releaseTime"]) != str(rule.release_time)):
            _fail("The master-backed 360 LIVE music lacks its exact original stage or release")
        add_scene(rule, "")
    if latest_pin is not None:
        raw = json.dumps(_projection(musics, stages), sort_keys=True, ensure_ascii=False,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
        if hashlib.sha256(raw).hexdigest() != latest_pin:
            _fail("The media 360 LIVE scene references differ from the audited latest cohort")
    return MappingProxyType(result)


def prepare_media_panorama(master_dir):
    """Purely validate fourteen factual and one master-backed panorama scene.

    Existing Music/Stage tables suffice; no PhotoQuestMusic or new master table
    is needed. This does not infer a stage for other is360LiveExist music rows.
    """
    return _prepare(_Catalog(master_dir))


class MediaPanorama:
    """Lazy media-only list/check provider; creation is deliberately unhandled."""

    def __init__(self, schema, state, profile, master_dir=None):
        self.schema, self.state, self.profile = schema, state, profile
        self.catalog = _Catalog(master_dir)
        self._scenes = None

    def _snapshot(self):
        stored = self.state.snapshot(self.profile)
        if stored is None or stored[1] != self.schema.fingerprint:
            _fail("The media 360 LIVE profile has no snapshot for this schema")
        try:
            snapshot = self.schema.response_type(_USER).FromString(stored[0])
        except DecodeError:
            _fail("The media 360 LIVE snapshot is malformed")
        if not snapshot.HasField("user"):
            _fail("The media 360 LIVE profile has no user state")
        return snapshot

    def _check(self, request, snapshot, scenes):
        scene = scenes.get(request.photoMusicId)
        if scene is None:
            music = self.catalog.ids("Music", required=True).get(request.photoMusicId)
            if music is not None and music.get("is360LiveExist") is True:
                _fail("This 360 LIVE music has no verified local panorama scene")
            _fail("Unknown 360 LIVE music", RpcCode.INVALID_ARGUMENT)
        characters = list(request.characterIds)
        costumes, hairs = list(request.costumeIds), list(request.hairIds)
        # Original SetMusicAndCameraData (0x591b550) reads Music's cast amount;
        # OnExecuteConfirmSheetAsync (0x5925618) sends the API row's musicId.
        if (len(characters) != scene.cast_count or len(costumes) != len(characters)
                or len(hairs) != len(characters) or len(set(characters)) != len(characters)
                or any(not identity for identity in (*characters, *costumes, *hairs))):
            _fail("Matching unique 360 LIVE characters and outfits are required", RpcCode.INVALID_ARGUMENT)
        character_master = self.catalog.ids("Character", required=True)
        costume_master = self.catalog.ids("Costume", required=True)
        hair_master = self.catalog.ids("Hair", required=True)
        owned_characters = _owned(snapshot.characters, "characterId")
        owned_costumes = _owned(snapshot.costumes, "costumeId")
        owned_hairs = _owned(snapshot.hairs, "hairId")
        for character, costume, hair in zip(characters, costumes, hairs):
            costume_row, hair_row = costume_master.get(costume), hair_master.get(hair)
            if character not in character_master or costume_row is None or hair_row is None:
                _fail("Unknown 360 LIVE character or outfit", RpcCode.INVALID_ARGUMENT)
            if character not in owned_characters or costume not in owned_costumes or hair not in owned_hairs:
                _fail("The 360 LIVE character or outfit is not owned", RpcCode.PERMISSION_DENIED)
            if costume_row.get("characterId") != character or hair_row.get("characterId") != character:
                _fail("360 LIVE character and outfit do not match", RpcCode.INVALID_ARGUMENT)
            if not _wearable(hair_row, costume):
                _fail("The 360 LIVE hair cannot be worn with this costume", RpcCode.INVALID_ARGUMENT)

    def handle(self, path, plain):
        if path not in _ROUTES or path not in self.schema.methods or self.catalog.directory is None:
            return None
        try:
            request = self.schema.request_type(path).FromString(plain)
        except DecodeError:
            _fail("Malformed 360 LIVE request", RpcCode.INVALID_ARGUMENT)
        if self._scenes is None:
            self._scenes = _prepare(self.catalog)
        snapshot = self._snapshot()
        result = self.schema.response_type(path)()
        if path == _LIST:
            for scene in sorted(self._scenes.values(), key=lambda value: value.order):
                # Original PanoramaMusicListCellView.SetView resolves this
                # ID in ConditionDescriptionMaster and dereferences the
                # description even when isUnlocked is true. Keep the actual
                # description reference; only the safe view term is empty.
                result.musics.add(musicId=scene.music_id, stageId=scene.stage_id, assetId=scene.asset_id,
                    order=scene.order, isUnlocked=True, unlockConditionId=UNLOCK_CONDITION,
                    viewConditionId="")
        else:
            self._check(request, snapshot, self._scenes)
        # List/check do not change user state. An empty Common parent avoids
        # constructing both delta DTOs and dispatching empty client updates.
        result.commonResponse.SetInParent()
        return result.SerializeToString()
