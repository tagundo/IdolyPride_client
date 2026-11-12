"""Photo scene checks and image reservations without fabricated photographs.

The 6.1.1 protocol separates scene unlocks, reserved upload IDs and UserPhoto
records.  A master scene is not proof of normal-profile ownership and an upload
ID is not an image. Callers provide scene access from preserved ownership or
an explicit separate media-mode policy, and finalized image URLs.
Creation remains blocked until the local upload/generation flow is available;
this module never consumes film or creates a placeholder PhotoImageType.User.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import re
from uuid import uuid4

from google.protobuf.message import DecodeError

from .appearance import _owned
from .gameplay import _Catalog
from .live_assets import _wearable
from .rpc import RpcCode, RpcFailure


_USER = "/api.User/Get"
_LIST = "/api.Photo/ListShooting"
_CHECK = "/api.Photo/CheckShooting"
_CREATE = "/api.Photo/CreateShootings"
_URL = "/api.Photo/GetImageURL"
_ROUTES = frozenset((_LIST, _CHECK, _CREATE, _URL))
_SAFE_IMAGE_ID = re.compile(r"[A-Za-z0-9_.~-]{1,251}\Z")
RESERVED_IMAGE_COUNT = 20
_MV_SCENE = object()


def _fail(message, code=RpcCode.FAILED_PRECONDITION):
    raise RpcFailure(code, message)


def valid_image_id(value):
    return isinstance(value, str) and value not in (".", "..") and bool(_SAFE_IMAGE_ID.fullmatch(value))


def reserve_photo_image_ids(user, *, id_factory=lambda: str(uuid4())):
    """Fill the native client's upload reservations, preserving all existing IDs.

    This operates on a protobuf User only.  Persist it in the caller's existing
    snapshot transaction and return updatedData.user if it changed.  Reservation
    creates no image, photo, film or scene unlock.  The deprecated single ID and
    imported arrays longer than twenty are deliberately retained.
    """
    current = list(user.nextPhotoImageIds)
    if any(not valid_image_id(value) for value in current) or len(set(current)) != len(current):
        _fail("Photo image reservations are malformed")
    if len(current) >= RESERVED_IMAGE_COUNT:
        return False
    seen = set(current)
    # UUID collisions should be exceptional. A bounded loop also makes a broken
    # injected generator fail before touching the caller's User.
    additions = []
    for _ in range(RESERVED_IMAGE_COUNT * 4):
        candidate = id_factory()
        if not valid_image_id(candidate):
            _fail("Photo reservation generator returned an invalid image ID")
        if candidate not in seen:
            seen.add(candidate)
            additions.append(candidate)
            if len(current) + len(additions) == RESERVED_IMAGE_COUNT:
                user.nextPhotoImageIds.extend(additions)
                return True
    _fail("Photo reservation generator could not produce unique image IDs")


@dataclass(frozen=True)
class PhotoSceneAccess:
    """Explicit per-profile scene access, including locked rows.

    IDs use the native API names: activities and expressions use their photo
    IDs, musics use musicId, and stages use stageId. This value object infers
    nothing. Normal profiles use preserved access; a separately enabled media
    profile may supply an explicit all-unlocked public-master policy.
    """
    activities: Mapping[str, bool] = field(default_factory=dict)
    musics: Mapping[str, bool] = field(default_factory=dict)
    stages: Mapping[str, bool] = field(default_factory=dict)
    expressions: Mapping[str, bool] = field(default_factory=dict)


class PhotoShootings:
    """Read/check photo endpoints; unsupported creation fails before any writes.

    ``scene_access`` may be a PhotoSceneAccess or a callback accepting the local
    profile name and returning one.  ``image_urls(profile, asset_id)`` must return
    (original_url, thumbnail_url) for a finalized image owned by that profile,
    or None.  A missing original image must not be replaced with a stock asset.
    """

    def __init__(self, schema, state, profile, master_dir=None, *, scene_access=None, image_urls=None,
                 media_mode=False):
        if type(media_mode) is not bool:
            raise ValueError("Media mode must be an explicit boolean")
        self.schema, self.state, self.profile = schema, state, profile
        self.catalog = _Catalog(master_dir)
        self.scene_access = scene_access
        self.image_urls = image_urls
        self.media_mode = media_mode

    def _snapshot(self):
        stored = self.state.snapshot(self.profile)
        if stored is None or stored[1] != self.schema.fingerprint:
            _fail("Local photo profile has no snapshot for this schema")
        try:
            snapshot = self.schema.response_type(_USER).FromString(stored[0])
        except DecodeError:
            _fail("Local photo snapshot is malformed")
        if not snapshot.HasField("user"):
            _fail("Local photo profile has no user state")
        return snapshot

    def _access(self):
        access = self.scene_access(self.profile) if callable(self.scene_access) else self.scene_access
        if not isinstance(access, PhotoSceneAccess):
            _fail("Preserved photo scene unlocks are unavailable locally")
        for name in ("activities", "musics", "stages", "expressions"):
            entries = getattr(access, name)
            if (not isinstance(entries, Mapping)
                    or any(not isinstance(key, str) or not key or type(value) is not bool
                           for key, value in entries.items())):
                _fail("Preserved photo scene unlocks are malformed")
        return access

    @staticmethod
    def _common(result):
        result.commonResponse.updatedData.SetInParent()
        result.commonResponse.deletedData.SetInParent()

    def _list(self, result, access):
        for table, source, target, identity in (
            ("PhotoActivity", access.activities, result.activities, "photoActivityId"),
            ("PhotoQuestMusic", access.musics, result.musics, "musicId"),
            ("PhotoQuestStage", access.stages, result.stages, "stageId"),
            ("PhotoExpression", access.expressions, result.expressions, "photoExpressionId"),
        ):
            if not source:
                continue
            masters = self.catalog.ids(table, required=True)
            if any(key not in masters for key in source):
                _fail("Preserved photo scene has an unknown master reference")
            for key in sorted(source):
                row = target.add(isUnlocked=source[key])
                setattr(row, identity, key)
        result.DokanInfo.SetInParent()
        self._common(result)

    def _scene(self, request, access):
        if request.actionType in (1, 2):
            key = request.photoActivityId
            if not key:
                _fail("A photo activity ID is required", RpcCode.INVALID_ARGUMENT)
            activity = self.catalog.ids("PhotoActivity", required=True).get(key)
            if activity is None or activity.get("type") != request.actionType:
                _fail("Unknown photo activity or mismatched action type", RpcCode.INVALID_ARGUMENT)
            if access.activities.get(key) is not True:
                _fail("The photo activity is not owned and unlocked")
            return activity
        if request.actionType == 3:
            if not request.photoMusicId:
                _fail("A photo music ID is required", RpcCode.INVALID_ARGUMENT)
            if request.photoMusicId not in self.catalog.ids("PhotoQuestMusic", required=True):
                _fail("Unknown local photo music or stage", RpcCode.INVALID_ARGUMENT)
            if access.musics.get(request.photoMusicId) is not True:
                _fail("The photo music or stage is not owned and unlocked")
            if not request.photoStageId:
                # Original LivePhotography.OnExecuteConfirmSheetAsync chooses
                # an empty stage for MV songs before Photo.CheckShootingAsync
                # (0x59b8660..0x59b902c). Music.IsMvMusic (0x4e7af24) uses
                # the real master mvAssetId, not a music-ID prefix.
                music = self.catalog.ids("Music", required=True).get(request.photoMusicId)
                if music is not None and isinstance(music.get("mvAssetId"), str) and music["mvAssetId"]:
                    return _MV_SCENE
                _fail("A photo stage ID is required for a 3D live", RpcCode.INVALID_ARGUMENT)
            if request.photoStageId not in self.catalog.ids("PhotoQuestStage", required=True):
                _fail("Unknown local photo music or stage", RpcCode.INVALID_ARGUMENT)
            if access.stages.get(request.photoStageId) is not True:
                _fail("The photo music or stage is not owned and unlocked")
            return None
        _fail("Unsupported photo shooting action type", RpcCode.INVALID_ARGUMENT)

    def _styles(self, request, snapshot, activity):
        characters, costumes, hairs = list(request.characterIds), list(request.costumeIds), list(request.hairIds)
        # A movie creates no 3D actors. The native caller constructs these
        # arrays from its current selection before branching to the empty MV
        # stage. Accept an entirely empty selection without inventing actors;
        # any supplied cast still passes every ordinary ownership/style check.
        if activity is _MV_SCENE and not characters and not costumes and not hairs:
            return
        if (not characters or len(costumes) != len(characters)
                or len(hairs) != len(characters)
                or any(not value for value in [*characters, *costumes, *hairs])):
            _fail("Matching nonempty photo character/style lists are required", RpcCode.INVALID_ARGUMENT)
        character_master = self.catalog.ids("Character", required=True)
        costume_master = self.catalog.ids("Costume", required=True)
        hair_master = self.catalog.ids("Hair", required=True)
        owned_characters = _owned(snapshot.characters, "characterId")
        owned_costumes = _owned(snapshot.costumes, "costumeId")
        owned_hairs = _owned(snapshot.hairs, "hairId")
        for character, costume, hair in zip(characters, costumes, hairs):
            definition, hair_definition = costume_master.get(costume), hair_master.get(hair)
            if character not in character_master or definition is None or hair_definition is None:
                _fail("Unknown photo character or outfit", RpcCode.INVALID_ARGUMENT)
            if character not in owned_characters or costume not in owned_costumes or hair not in owned_hairs:
                _fail("The photo character or outfit is not owned", RpcCode.PERMISSION_DENIED)
            if definition.get("characterId") != character or hair_definition.get("characterId") != character:
                _fail("Photo character and outfit do not match", RpcCode.INVALID_ARGUMENT)
            if not _wearable(hair_definition, costume):
                _fail("The photo hair cannot be worn with this costume", RpcCode.INVALID_ARGUMENT)
            if activity is not None and activity is not _MV_SCENE:
                denied = activity.get("impossibleShootingCharacterIds", [])
                allowed = activity.get("costumeTypeIds", [])
                if not isinstance(denied, list) or not isinstance(allowed, list):
                    _fail("Photo activity style restrictions are malformed")
                # The separate gallery permits all owned compatible outfits
                # for a job, while retaining character/motion exclusions.
                # The client selector also needs its media master override;
                # this check alone cannot expand that original UI list.
                if (character in denied
                        or not self.media_mode and allowed and definition.get("costumeTypeId") not in allowed):
                    _fail("The photo activity does not allow this character or costume", RpcCode.INVALID_ARGUMENT)

    def _urls(self, request, result, snapshot):
        if request.type not in (1, 2, 3):
            _fail("Unsupported photo image request type", RpcCode.INVALID_ARGUMENT)
        assets = list(request.assetIds)
        if any(not valid_image_id(value) for value in assets):
            _fail("Invalid photo image asset IDs", RpcCode.INVALID_ARGUMENT)
        photos = {}
        for photo in snapshot.photos:
            if photo.assetId in assets and photo.imageType == 2:
                photos[photo.assetId] = photo
        for asset in assets:
            if asset not in photos:
                _fail("The requested user photo image is not owned", RpcCode.PERMISSION_DENIED)
            urls = self.image_urls(self.profile, asset) if self.image_urls is not None else None
            if (not isinstance(urls, tuple) or len(urls) != 2 or not isinstance(urls[0], str)
                    or not urls[0] or not isinstance(urls[1], str)):
                _fail("The original photo image has not been preserved locally", RpcCode.NOT_FOUND)
            entry = result.urlList.add(assetId=asset)
            if request.type in (1, 3):
                entry.origUrl = urls[0]
            if request.type in (2, 3):
                entry.tmbUrl = urls[1] or urls[0]

    def handle(self, path, plain):
        if path not in _ROUTES or path not in self.schema.methods or self.catalog.directory is None:
            return None
        try:
            request = self.schema.request_type(path).FromString(plain)
        except DecodeError:
            _fail("Malformed photo request", RpcCode.INVALID_ARGUMENT)
        result = self.schema.response_type(path)()
        snapshot = self._snapshot()
        if path == _URL:
            self._urls(request, result, snapshot)
        elif path == _LIST:
            self._list(result, self._access())
        else:
            activity = self._scene(request, self._access())
            self._styles(request, snapshot, activity)
            if path == _CREATE:
                _fail("Local photo creation requires finalized image upload and verified film generation rules")
            self._common(result)
        return result.SerializeToString()
